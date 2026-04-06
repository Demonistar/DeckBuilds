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
    "aW1lIGltcG9ydCBkYXRldGltZSwgZGF0ZSwgdGltZWRlbHRhLCB0aW1lem9uZQpmcm9tIHBhdGhsaWIgaW1wb3J0IFBhdGgKZnJv"
    "bSB0eXBpbmcgaW1wb3J0IE9wdGlvbmFsLCBJdGVyYXRvcgoKIyDilIDilIAgRUFSTFkgQ1JBU0ggTE9HR0VSIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAojIEhvb2tzIGluIGJlZm9yZSBRdCwgYmVmb3JlIGV2ZXJ5dGhpbmcuIENhcHR1cmVzIEFMTCBvdXRwdXQgaW5jbHVkaW5n"
    "CiMgQysrIGxldmVsIFF0IG1lc3NhZ2VzLiBXcml0dGVuIHRvIFtEZWNrTmFtZV0vbG9ncy9zdGFydHVwLmxvZwojIFRoaXMgc3Rh"
    "eXMgYWN0aXZlIGZvciB0aGUgbGlmZSBvZiB0aGUgcHJvY2Vzcy4KCl9FQVJMWV9MT0dfTElORVM6IGxpc3QgPSBbXQpfRUFSTFlf"
    "TE9HX1BBVEg6IE9wdGlvbmFsW1BhdGhdID0gTm9uZQoKZGVmIF9lYXJseV9sb2cobXNnOiBzdHIpIC0+IE5vbmU6CiAgICB0cyA9"
    "IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUy4lZiIpWzotM10KICAgIGxpbmUgPSBmIlt7dHN9XSB7bXNnfSIKICAg"
    "IF9FQVJMWV9MT0dfTElORVMuYXBwZW5kKGxpbmUpCiAgICBwcmludChsaW5lLCBmbHVzaD1UcnVlKQogICAgaWYgX0VBUkxZX0xP"
    "R19QQVRIOgogICAgICAgIHRyeToKICAgICAgICAgICAgd2l0aCBfRUFSTFlfTE9HX1BBVEgub3BlbigiYSIsIGVuY29kaW5nPSJ1"
    "dGYtOCIpIGFzIGY6CiAgICAgICAgICAgICAgICBmLndyaXRlKGxpbmUgKyAiXG4iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246"
    "CiAgICAgICAgICAgIHBhc3MKCmRlZiBfaW5pdF9lYXJseV9sb2coYmFzZV9kaXI6IFBhdGgpIC0+IE5vbmU6CiAgICBnbG9iYWwg"
    "X0VBUkxZX0xPR19QQVRICiAgICBsb2dfZGlyID0gYmFzZV9kaXIgLyAibG9ncyIKICAgIGxvZ19kaXIubWtkaXIocGFyZW50cz1U"
    "cnVlLCBleGlzdF9vaz1UcnVlKQogICAgX0VBUkxZX0xPR19QQVRIID0gbG9nX2RpciAvIGYic3RhcnR1cF97ZGF0ZXRpbWUubm93"
    "KCkuc3RyZnRpbWUoJyVZJW0lZF8lSCVNJVMnKX0ubG9nIgogICAgIyBGbHVzaCBidWZmZXJlZCBsaW5lcwogICAgd2l0aCBfRUFS"
    "TFlfTE9HX1BBVEgub3BlbigidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgZm9yIGxpbmUgaW4gX0VBUkxZX0xP"
    "R19MSU5FUzoKICAgICAgICAgICAgZi53cml0ZShsaW5lICsgIlxuIikKCmRlZiBfaW5zdGFsbF9xdF9tZXNzYWdlX2hhbmRsZXIo"
    "KSAtPiBOb25lOgogICAgIiIiCiAgICBJbnRlcmNlcHQgQUxMIFF0IG1lc3NhZ2VzIGluY2x1ZGluZyBDKysgbGV2ZWwgd2Fybmlu"
    "Z3MuCiAgICBUaGlzIGNhdGNoZXMgdGhlIFFUaHJlYWQgZGVzdHJveWVkIG1lc3NhZ2UgYXQgdGhlIHNvdXJjZSBhbmQgbG9ncyBp"
    "dAogICAgd2l0aCBhIGZ1bGwgdHJhY2ViYWNrIHNvIHdlIGtub3cgZXhhY3RseSB3aGljaCB0aHJlYWQgYW5kIHdoZXJlLgogICAg"
    "IiIiCiAgICB0cnk6CiAgICAgICAgZnJvbSBQeVNpZGU2LlF0Q29yZSBpbXBvcnQgcUluc3RhbGxNZXNzYWdlSGFuZGxlciwgUXRN"
    "c2dUeXBlCiAgICAgICAgaW1wb3J0IHRyYWNlYmFjawoKICAgICAgICBkZWYgcXRfbWVzc2FnZV9oYW5kbGVyKG1zZ190eXBlLCBj"
    "b250ZXh0LCBtZXNzYWdlKToKICAgICAgICAgICAgbGV2ZWwgPSB7CiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXREZWJ1Z01z"
    "ZzogICAgIlFUX0RFQlVHIiwKICAgICAgICAgICAgICAgIFF0TXNnVHlwZS5RdEluZm9Nc2c6ICAgICAiUVRfSU5GTyIsCiAgICAg"
    "ICAgICAgICAgICBRdE1zZ1R5cGUuUXRXYXJuaW5nTXNnOiAgIlFUX1dBUk5JTkciLAogICAgICAgICAgICAgICAgUXRNc2dUeXBl"
    "LlF0Q3JpdGljYWxNc2c6ICJRVF9DUklUSUNBTCIsCiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXRGYXRhbE1zZzogICAgIlFU"
    "X0ZBVEFMIiwKICAgICAgICAgICAgfS5nZXQobXNnX3R5cGUsICJRVF9VTktOT1dOIikKCiAgICAgICAgICAgIGxvY2F0aW9uID0g"
    "IiIKICAgICAgICAgICAgaWYgY29udGV4dC5maWxlOgogICAgICAgICAgICAgICAgbG9jYXRpb24gPSBmIiBbe2NvbnRleHQuZmls"
    "ZX06e2NvbnRleHQubGluZX1dIgoKICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIlt7bGV2ZWx9XXtsb2NhdGlvbn0ge21lc3NhZ2V9"
    "IikKCiAgICAgICAgICAgICMgRm9yIFFUaHJlYWQgd2FybmluZ3Mg4oCUIGxvZyBmdWxsIFB5dGhvbiBzdGFjawogICAgICAgICAg"
    "ICBpZiAiUVRocmVhZCIgaW4gbWVzc2FnZSBvciAidGhyZWFkIiBpbiBtZXNzYWdlLmxvd2VyKCk6CiAgICAgICAgICAgICAgICBz"
    "dGFjayA9ICIiLmpvaW4odHJhY2ViYWNrLmZvcm1hdF9zdGFjaygpKQogICAgICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIltTVEFD"
    "SyBBVCBRVEhSRUFEIFdBUk5JTkddXG57c3RhY2t9IikKCiAgICAgICAgcUluc3RhbGxNZXNzYWdlSGFuZGxlcihxdF9tZXNzYWdl"
    "X2hhbmRsZXIpCiAgICAgICAgX2Vhcmx5X2xvZygiW0lOSVRdIFF0IG1lc3NhZ2UgaGFuZGxlciBpbnN0YWxsZWQiKQogICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgIF9lYXJseV9sb2coZiJbSU5JVF0gQ291bGQgbm90IGluc3RhbGwgUXQgbWVzc2Fn"
    "ZSBoYW5kbGVyOiB7ZX0iKQoKX2Vhcmx5X2xvZyhmIltJTklUXSB7REVDS19OQU1FfSBkZWNrIHN0YXJ0aW5nIikKX2Vhcmx5X2xv"
    "ZyhmIltJTklUXSBQeXRob24ge3N5cy52ZXJzaW9uLnNwbGl0KClbMF19IGF0IHtzeXMuZXhlY3V0YWJsZX0iKQpfZWFybHlfbG9n"
    "KGYiW0lOSVRdIFdvcmtpbmcgZGlyZWN0b3J5OiB7b3MuZ2V0Y3dkKCl9IikKX2Vhcmx5X2xvZyhmIltJTklUXSBTY3JpcHQgbG9j"
    "YXRpb246IHtQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCl9IikKCiMg4pSA4pSAIE9QVElPTkFMIERFUEVOREVOQ1kgR1VBUkRTIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAoKUFNVVElM"
    "X09LID0gRmFsc2UKdHJ5OgogICAgaW1wb3J0IHBzdXRpbAogICAgUFNVVElMX09LID0gVHJ1ZQogICAgX2Vhcmx5X2xvZygiW0lN"
    "UE9SVF0gcHN1dGlsIE9LIikKZXhjZXB0IEltcG9ydEVycm9yIGFzIGU6CiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gcHN1dGls"
    "IEZBSUxFRDoge2V9IikKCk5WTUxfT0sgPSBGYWxzZQpncHVfaGFuZGxlID0gTm9uZQp0cnk6CiAgICBpbXBvcnQgd2FybmluZ3MK"
    "ICAgIHdpdGggd2FybmluZ3MuY2F0Y2hfd2FybmluZ3MoKToKICAgICAgICB3YXJuaW5ncy5zaW1wbGVmaWx0ZXIoImlnbm9yZSIp"
    "CiAgICAgICAgaW1wb3J0IHB5bnZtbAogICAgcHludm1sLm52bWxJbml0KCkKICAgIGNvdW50ID0gcHludm1sLm52bWxEZXZpY2VH"
    "ZXRDb3VudCgpCiAgICBpZiBjb3VudCA+IDA6CiAgICAgICAgZ3B1X2hhbmRsZSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0SGFuZGxl"
    "QnlJbmRleCgwKQogICAgICAgIE5WTUxfT0sgPSBUcnVlCiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gcHludm1sIE9LIOKAlCB7"
    "Y291bnR9IEdQVShzKSIpCmV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSBweW52bWwgRkFJ"
    "TEVEOiB7ZX0iKQoKVE9SQ0hfT0sgPSBGYWxzZQp0cnk6CiAgICBpbXBvcnQgdG9yY2gKICAgIGZyb20gdHJhbnNmb3JtZXJzIGlt"
    "cG9ydCBBdXRvTW9kZWxGb3JDYXVzYWxMTSwgQXV0b1Rva2VuaXplcgogICAgVE9SQ0hfT0sgPSBUcnVlCiAgICBfZWFybHlfbG9n"
    "KGYiW0lNUE9SVF0gdG9yY2gge3RvcmNoLl9fdmVyc2lvbl9ffSBPSyIpCmV4Y2VwdCBJbXBvcnRFcnJvciBhcyBlOgogICAgX2Vh"
    "cmx5X2xvZyhmIltJTVBPUlRdIHRvcmNoIEZBSUxFRCAob3B0aW9uYWwpOiB7ZX0iKQoKV0lOMzJfT0sgPSBGYWxzZQp0cnk6CiAg"
    "ICBpbXBvcnQgd2luMzJjb20uY2xpZW50CiAgICBXSU4zMl9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coIltJTVBPUlRdIHdpbjMy"
    "Y29tIE9LIikKZXhjZXB0IEltcG9ydEVycm9yIGFzIGU6CiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gd2luMzJjb20gRkFJTEVE"
    "OiB7ZX0iKQoKV0lOU09VTkRfT0sgPSBGYWxzZQp0cnk6CiAgICBpbXBvcnQgd2luc291bmQKICAgIFdJTlNPVU5EX09LID0gVHJ1"
    "ZQogICAgX2Vhcmx5X2xvZygiW0lNUE9SVF0gd2luc291bmQgT0siKQpleGNlcHQgSW1wb3J0RXJyb3IgYXMgZToKICAgIF9lYXJs"
    "eV9sb2coZiJbSU1QT1JUXSB3aW5zb3VuZCBGQUlMRUQgKG9wdGlvbmFsKToge2V9IikKClBZR0FNRV9PSyA9IEZhbHNlCnRyeToK"
    "ICAgIGltcG9ydCBweWdhbWUKICAgIHB5Z2FtZS5taXhlci5pbml0KCkKICAgIFBZR0FNRV9PSyA9IFRydWUKICAgIF9lYXJseV9s"
    "b2coIltJTVBPUlRdIHB5Z2FtZSBPSyIpCmV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSBw"
    "eWdhbWUgRkFJTEVEOiB7ZX0iKQoKR09PR0xFX09LID0gRmFsc2UKR09PR0xFX0FQSV9PSyA9IEZhbHNlICAjIGFsaWFzIHVzZWQg"
    "YnkgR29vZ2xlIHNlcnZpY2UgY2xhc3NlcwpHT09HTEVfSU1QT1JUX0VSUk9SID0gTm9uZQp0cnk6CiAgICBmcm9tIGdvb2dsZS5h"
    "dXRoLnRyYW5zcG9ydC5yZXF1ZXN0cyBpbXBvcnQgUmVxdWVzdCBhcyBHb29nbGVBdXRoUmVxdWVzdAogICAgZnJvbSBnb29nbGUu"
    "b2F1dGgyLmNyZWRlbnRpYWxzIGltcG9ydCBDcmVkZW50aWFscyBhcyBHb29nbGVDcmVkZW50aWFscwogICAgZnJvbSBnb29nbGVf"
    "YXV0aF9vYXV0aGxpYi5mbG93IGltcG9ydCBJbnN0YWxsZWRBcHBGbG93CiAgICBmcm9tIGdvb2dsZWFwaWNsaWVudC5kaXNjb3Zl"
    "cnkgaW1wb3J0IGJ1aWxkIGFzIGdvb2dsZV9idWlsZAogICAgZnJvbSBnb29nbGVhcGljbGllbnQuZXJyb3JzIGltcG9ydCBIdHRw"
    "RXJyb3IgYXMgR29vZ2xlSHR0cEVycm9yCiAgICBHT09HTEVfT0sgPSBUcnVlCiAgICBHT09HTEVfQVBJX09LID0gVHJ1ZQpleGNl"
    "cHQgSW1wb3J0RXJyb3IgYXMgX2U6CiAgICBHT09HTEVfSU1QT1JUX0VSUk9SID0gc3RyKF9lKQogICAgR29vZ2xlSHR0cEVycm9y"
    "ID0gRXhjZXB0aW9uCgpHT09HTEVfU0NPUEVTID0gWwogICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5k"
    "YXIiLAogICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIuZXZlbnRzIiwKICAgICJodHRwczovL3d3"
    "dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RyaXZlIiwKICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RvY3VtZW50"
    "cyIsCl0KR09PR0xFX1NDT1BFX1JFQVVUSF9NU0cgPSAoCiAgICAiR29vZ2xlIHRva2VuIHNjb3BlcyBhcmUgb3V0ZGF0ZWQgb3Ig"
    "aW5jb21wYXRpYmxlIHdpdGggcmVxdWVzdGVkIHNjb3Blcy4gIgogICAgIkRlbGV0ZSB0b2tlbi5qc29uIGFuZCByZWF1dGhvcml6"
    "ZSB3aXRoIHRoZSB1cGRhdGVkIHNjb3BlIGxpc3QuIgopCkRFRkFVTFRfR09PR0xFX0lBTkFfVElNRVpPTkUgPSAiQW1lcmljYS9D"
    "aGljYWdvIgpXSU5ET1dTX1RaX1RPX0lBTkEgPSB7CiAgICAiQ2VudHJhbCBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvQ2hpY2Fn"
    "byIsCiAgICAiRWFzdGVybiBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvTmV3X1lvcmsiLAogICAgIlBhY2lmaWMgU3RhbmRhcmQg"
    "VGltZSI6ICJBbWVyaWNhL0xvc19BbmdlbGVzIiwKICAgICJNb3VudGFpbiBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvRGVudmVy"
    "IiwKfQoKCiMg4pSA4pSAIFB5U2lkZTYgSU1QT1JUUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZnJvbSBQeVNpZGU2LlF0"
    "V2lkZ2V0cyBpbXBvcnQgKAogICAgUUFwcGxpY2F0aW9uLCBRTWFpbldpbmRvdywgUVdpZGdldCwgUVZCb3hMYXlvdXQsIFFIQm94"
    "TGF5b3V0LAogICAgUUdyaWRMYXlvdXQsIFFUZXh0RWRpdCwgUUxpbmVFZGl0LCBRUHVzaEJ1dHRvbiwgUUxhYmVsLCBRRnJhbWUs"
    "CiAgICBRQ2FsZW5kYXJXaWRnZXQsIFFUYWJsZVdpZGdldCwgUVRhYmxlV2lkZ2V0SXRlbSwgUUhlYWRlclZpZXcsCiAgICBRQWJz"
    "dHJhY3RJdGVtVmlldywgUVN0YWNrZWRXaWRnZXQsIFFUYWJXaWRnZXQsIFFMaXN0V2lkZ2V0LAogICAgUUxpc3RXaWRnZXRJdGVt"
    "LCBRU2l6ZVBvbGljeSwgUUNvbWJvQm94LCBRQ2hlY2tCb3gsIFFGaWxlRGlhbG9nLAogICAgUU1lc3NhZ2VCb3gsIFFEYXRlRWRp"
    "dCwgUURpYWxvZywgUUZvcm1MYXlvdXQsIFFTY3JvbGxBcmVhLAogICAgUVNwbGl0dGVyLCBRSW5wdXREaWFsb2csIFFUb29sQnV0"
    "dG9uCikKZnJvbSBQeVNpZGU2LlF0Q29yZSBpbXBvcnQgKAogICAgUXQsIFFUaW1lciwgUVRocmVhZCwgU2lnbmFsLCBRRGF0ZSwg"
    "UVNpemUsIFFQb2ludCwgUVJlY3QKKQpmcm9tIFB5U2lkZTYuUXRHdWkgaW1wb3J0ICgKICAgIFFGb250LCBRQ29sb3IsIFFQYWlu"
    "dGVyLCBRTGluZWFyR3JhZGllbnQsIFFSYWRpYWxHcmFkaWVudCwKICAgIFFQaXhtYXAsIFFQZW4sIFFQYWludGVyUGF0aCwgUVRl"
    "eHRDaGFyRm9ybWF0LCBRSWNvbiwKICAgIFFUZXh0Q3Vyc29yLCBRQWN0aW9uCikKCiMg4pSA4pSAIEFQUCBJREVOVElUWSDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKQVBQX05BTUUgICAgICA9IFVJX1dJTkRPV19USVRMRQpBUFBfVkVSU0lP"
    "TiAgID0gIjIuMC4wIgpBUFBfRklMRU5BTUUgID0gZiJ7REVDS19OQU1FLmxvd2VyKCl9X2RlY2sucHkiCkJVSUxEX0RBVEUgICAg"
    "PSAiMjAyNi0wNC0wNCIKCiMg4pSA4pSAIENPTkZJRyBMT0FESU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAoj"
    "IGNvbmZpZy5qc29uIGxpdmVzIG5leHQgdG8gdGhlIGRlY2sgLnB5IGZpbGUuCiMgQWxsIHBhdGhzIGNvbWUgZnJvbSBjb25maWcu"
    "IE5vdGhpbmcgaGFyZGNvZGVkIGJlbG93IHRoaXMgcG9pbnQuCgpTQ1JJUFRfRElSID0gUGF0aChfX2ZpbGVfXykucmVzb2x2ZSgp"
    "LnBhcmVudApDT05GSUdfUEFUSCA9IFNDUklQVF9ESVIgLyAiY29uZmlnLmpzb24iCgojIEluaXRpYWxpemUgZWFybHkgbG9nIG5v"
    "dyB0aGF0IHdlIGtub3cgd2hlcmUgd2UgYXJlCl9pbml0X2Vhcmx5X2xvZyhTQ1JJUFRfRElSKQpfZWFybHlfbG9nKGYiW0lOSVRd"
    "IFNDUklQVF9ESVIgPSB7U0NSSVBUX0RJUn0iKQpfZWFybHlfbG9nKGYiW0lOSVRdIENPTkZJR19QQVRIID0ge0NPTkZJR19QQVRI"
    "fSIpCl9lYXJseV9sb2coZiJbSU5JVF0gY29uZmlnLmpzb24gZXhpc3RzOiB7Q09ORklHX1BBVEguZXhpc3RzKCl9IikKCmRlZiBf"
    "ZGVmYXVsdF9jb25maWcoKSAtPiBkaWN0OgogICAgIiIiUmV0dXJucyB0aGUgZGVmYXVsdCBjb25maWcgc3RydWN0dXJlIGZvciBm"
    "aXJzdC1ydW4gZ2VuZXJhdGlvbi4iIiIKICAgIGJhc2UgPSBzdHIoU0NSSVBUX0RJUikKICAgIHJldHVybiB7CiAgICAgICAgImRl"
    "Y2tfbmFtZSI6IERFQ0tfTkFNRSwKICAgICAgICAiZGVja192ZXJzaW9uIjogQVBQX1ZFUlNJT04sCiAgICAgICAgImJhc2VfZGly"
    "IjogYmFzZSwKICAgICAgICAibW9kZWwiOiB7CiAgICAgICAgICAgICJ0eXBlIjogImxvY2FsIiwgICAgICAgICAgIyBsb2NhbCB8"
    "IG9sbGFtYSB8IGNsYXVkZSB8IG9wZW5haQogICAgICAgICAgICAicGF0aCI6ICIiLCAgICAgICAgICAgICAgICMgbG9jYWwgbW9k"
    "ZWwgZm9sZGVyIHBhdGgKICAgICAgICAgICAgIm9sbGFtYV9tb2RlbCI6ICIiLCAgICAgICAjIGUuZy4gImRvbHBoaW4tMi42LTdi"
    "IgogICAgICAgICAgICAiYXBpX2tleSI6ICIiLCAgICAgICAgICAgICMgQ2xhdWRlIG9yIE9wZW5BSSBrZXkKICAgICAgICAgICAg"
    "ImFwaV90eXBlIjogIiIsICAgICAgICAgICAjICJjbGF1ZGUiIHwgIm9wZW5haSIKICAgICAgICAgICAgImFwaV9tb2RlbCI6ICIi"
    "LCAgICAgICAgICAjIGUuZy4gImNsYXVkZS1zb25uZXQtNC02IgogICAgICAgIH0sCiAgICAgICAgImdvb2dsZSI6IHsKICAgICAg"
    "ICAgICAgImNyZWRlbnRpYWxzIjogc3RyKFNDUklQVF9ESVIgLyAiZ29vZ2xlIiAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIp"
    "LAogICAgICAgICAgICAidG9rZW4iOiAgICAgICBzdHIoU0NSSVBUX0RJUiAvICJnb29nbGUiIC8gInRva2VuLmpzb24iKSwKICAg"
    "ICAgICAgICAgInRpbWV6b25lIjogICAgIkFtZXJpY2EvQ2hpY2FnbyIsCiAgICAgICAgICAgICJzY29wZXMiOiBbCiAgICAgICAg"
    "ICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9jYWxlbmRhci5ldmVudHMiLAogICAgICAgICAgICAgICAg"
    "Imh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZHJpdmUiLAogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2ds"
    "ZWFwaXMuY29tL2F1dGgvZG9jdW1lbnRzIiwKICAgICAgICAgICAgXSwKICAgICAgICB9LAogICAgICAgICJwYXRocyI6IHsKICAg"
    "ICAgICAgICAgImZhY2VzIjogICAgc3RyKFNDUklQVF9ESVIgLyAiRmFjZXMiKSwKICAgICAgICAgICAgInNvdW5kcyI6ICAgc3Ry"
    "KFNDUklQVF9ESVIgLyAic291bmRzIiksCiAgICAgICAgICAgICJtZW1vcmllcyI6IHN0cihTQ1JJUFRfRElSIC8gIm1lbW9yaWVz"
    "IiksCiAgICAgICAgICAgICJzZXNzaW9ucyI6IHN0cihTQ1JJUFRfRElSIC8gInNlc3Npb25zIiksCiAgICAgICAgICAgICJzbCI6"
    "ICAgICAgIHN0cihTQ1JJUFRfRElSIC8gInNsIiksCiAgICAgICAgICAgICJleHBvcnRzIjogIHN0cihTQ1JJUFRfRElSIC8gImV4"
    "cG9ydHMiKSwKICAgICAgICAgICAgImxvZ3MiOiAgICAgc3RyKFNDUklQVF9ESVIgLyAibG9ncyIpLAogICAgICAgICAgICAiYmFj"
    "a3VwcyI6ICBzdHIoU0NSSVBUX0RJUiAvICJiYWNrdXBzIiksCiAgICAgICAgICAgICJwZXJzb25hcyI6IHN0cihTQ1JJUFRfRElS"
    "IC8gInBlcnNvbmFzIiksCiAgICAgICAgICAgICJnb29nbGUiOiAgIHN0cihTQ1JJUFRfRElSIC8gImdvb2dsZSIpLAogICAgICAg"
    "IH0sCiAgICAgICAgInNldHRpbmdzIjogewogICAgICAgICAgICAiaWRsZV9lbmFibGVkIjogICAgICAgICAgICAgIEZhbHNlLAog"
    "ICAgICAgICAgICAiaWRsZV9taW5fbWludXRlcyI6ICAgICAgICAgIDEwLAogICAgICAgICAgICAiaWRsZV9tYXhfbWludXRlcyI6"
    "ICAgICAgICAgIDMwLAogICAgICAgICAgICAiYXV0b3NhdmVfaW50ZXJ2YWxfbWludXRlcyI6IDEwLAogICAgICAgICAgICAibWF4"
    "X2JhY2t1cHMiOiAgICAgICAgICAgICAgIDEwLAogICAgICAgICAgICAiZ29vZ2xlX3N5bmNfZW5hYmxlZCI6ICAgICAgIFRydWUs"
    "CiAgICAgICAgICAgICJzb3VuZF9lbmFibGVkIjogICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgICAgImdvb2dsZV9pbmJvdW5k"
    "X2ludGVydmFsX21zIjogMzAwMDAwLAogICAgICAgICAgICAiZ29vZ2xlX2xvb2tiYWNrX2RheXMiOiAgICAgIDMwLAogICAgICAg"
    "ICAgICAidXNlcl9kZWxheV90aHJlc2hvbGRfbWluIjogIDMwLAogICAgICAgIH0sCiAgICAgICAgImZpcnN0X3J1biI6IFRydWUs"
    "CiAgICB9CgpkZWYgbG9hZF9jb25maWcoKSAtPiBkaWN0OgogICAgIiIiTG9hZCBjb25maWcuanNvbi4gUmV0dXJucyBkZWZhdWx0"
    "IGlmIG1pc3Npbmcgb3IgY29ycnVwdC4iIiIKICAgIGlmIG5vdCBDT05GSUdfUEFUSC5leGlzdHMoKToKICAgICAgICByZXR1cm4g"
    "X2RlZmF1bHRfY29uZmlnKCkKICAgIHRyeToKICAgICAgICB3aXRoIENPTkZJR19QQVRILm9wZW4oInIiLCBlbmNvZGluZz0idXRm"
    "LTgiKSBhcyBmOgogICAgICAgICAgICByZXR1cm4ganNvbi5sb2FkKGYpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHJl"
    "dHVybiBfZGVmYXVsdF9jb25maWcoKQoKZGVmIHNhdmVfY29uZmlnKGNmZzogZGljdCkgLT4gTm9uZToKICAgICIiIldyaXRlIGNv"
    "bmZpZy5qc29uLiIiIgogICAgQ09ORklHX1BBVEgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAg"
    "IHdpdGggQ09ORklHX1BBVEgub3BlbigidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAganNvbi5kdW1wKGNmZywg"
    "ZiwgaW5kZW50PTIpCgojIExvYWQgY29uZmlnIGF0IG1vZHVsZSBsZXZlbCDigJQgZXZlcnl0aGluZyBiZWxvdyByZWFkcyBmcm9t"
    "IENGRwpDRkcgPSBsb2FkX2NvbmZpZygpCl9lYXJseV9sb2coZiJbSU5JVF0gQ29uZmlnIGxvYWRlZCDigJQgZmlyc3RfcnVuPXtD"
    "RkcuZ2V0KCdmaXJzdF9ydW4nKX0sIG1vZGVsX3R5cGU9e0NGRy5nZXQoJ21vZGVsJyx7fSkuZ2V0KCd0eXBlJyl9IikKCl9ERUZB"
    "VUxUX1BBVEhTOiBkaWN0W3N0ciwgUGF0aF0gPSB7CiAgICAiZmFjZXMiOiAgICBTQ1JJUFRfRElSIC8gIkZhY2VzIiwKICAgICJz"
    "b3VuZHMiOiAgIFNDUklQVF9ESVIgLyAic291bmRzIiwKICAgICJtZW1vcmllcyI6IFNDUklQVF9ESVIgLyAibWVtb3JpZXMiLAog"
    "ICAgInNlc3Npb25zIjogU0NSSVBUX0RJUiAvICJzZXNzaW9ucyIsCiAgICAic2wiOiAgICAgICBTQ1JJUFRfRElSIC8gInNsIiwK"
    "ICAgICJleHBvcnRzIjogIFNDUklQVF9ESVIgLyAiZXhwb3J0cyIsCiAgICAibG9ncyI6ICAgICBTQ1JJUFRfRElSIC8gImxvZ3Mi"
    "LAogICAgImJhY2t1cHMiOiAgU0NSSVBUX0RJUiAvICJiYWNrdXBzIiwKICAgICJwZXJzb25hcyI6IFNDUklQVF9ESVIgLyAicGVy"
    "c29uYXMiLAogICAgImdvb2dsZSI6ICAgU0NSSVBUX0RJUiAvICJnb29nbGUiLAp9CgpkZWYgX25vcm1hbGl6ZV9jb25maWdfcGF0"
    "aHMoKSAtPiBOb25lOgogICAgIiIiCiAgICBTZWxmLWhlYWwgb2xkZXIgY29uZmlnLmpzb24gZmlsZXMgbWlzc2luZyByZXF1aXJl"
    "ZCBwYXRoIGtleXMuCiAgICBBZGRzIG1pc3NpbmcgcGF0aCBrZXlzIGFuZCBub3JtYWxpemVzIGdvb2dsZSBjcmVkZW50aWFsL3Rv"
    "a2VuIGxvY2F0aW9ucywKICAgIHRoZW4gcGVyc2lzdHMgY29uZmlnLmpzb24gaWYgYW55dGhpbmcgY2hhbmdlZC4KICAgICIiIgog"
    "ICAgY2hhbmdlZCA9IEZhbHNlCiAgICBwYXRocyA9IENGRy5zZXRkZWZhdWx0KCJwYXRocyIsIHt9KQogICAgZm9yIGtleSwgZGVm"
    "YXVsdF9wYXRoIGluIF9ERUZBVUxUX1BBVEhTLml0ZW1zKCk6CiAgICAgICAgaWYgbm90IHBhdGhzLmdldChrZXkpOgogICAgICAg"
    "ICAgICBwYXRoc1trZXldID0gc3RyKGRlZmF1bHRfcGF0aCkKICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICBnb29nbGVf"
    "Y2ZnID0gQ0ZHLnNldGRlZmF1bHQoImdvb2dsZSIsIHt9KQogICAgZ29vZ2xlX3Jvb3QgPSBQYXRoKHBhdGhzLmdldCgiZ29vZ2xl"
    "Iiwgc3RyKF9ERUZBVUxUX1BBVEhTWyJnb29nbGUiXSkpKQogICAgZGVmYXVsdF9jcmVkcyA9IHN0cihnb29nbGVfcm9vdCAvICJn"
    "b29nbGVfY3JlZGVudGlhbHMuanNvbiIpCiAgICBkZWZhdWx0X3Rva2VuID0gc3RyKGdvb2dsZV9yb290IC8gInRva2VuLmpzb24i"
    "KQogICAgY3JlZHNfdmFsID0gc3RyKGdvb2dsZV9jZmcuZ2V0KCJjcmVkZW50aWFscyIsICIiKSkuc3RyaXAoKQogICAgdG9rZW5f"
    "dmFsID0gc3RyKGdvb2dsZV9jZmcuZ2V0KCJ0b2tlbiIsICIiKSkuc3RyaXAoKQogICAgaWYgKG5vdCBjcmVkc192YWwpIG9yICgi"
    "Y29uZmlnIiBpbiBjcmVkc192YWwgYW5kICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIgaW4gY3JlZHNfdmFsKToKICAgICAgICBn"
    "b29nbGVfY2ZnWyJjcmVkZW50aWFscyJdID0gZGVmYXVsdF9jcmVkcwogICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICBpZiBub3Qg"
    "dG9rZW5fdmFsOgogICAgICAgIGdvb2dsZV9jZmdbInRva2VuIl0gPSBkZWZhdWx0X3Rva2VuCiAgICAgICAgY2hhbmdlZCA9IFRy"
    "dWUKCiAgICBpZiBjaGFuZ2VkOgogICAgICAgIHNhdmVfY29uZmlnKENGRykKCmRlZiBjZmdfcGF0aChrZXk6IHN0cikgLT4gUGF0"
    "aDoKICAgICIiIkNvbnZlbmllbmNlOiBnZXQgYSBwYXRoIGZyb20gQ0ZHWydwYXRocyddW2tleV0gYXMgYSBQYXRoIG9iamVjdCB3"
    "aXRoIHNhZmUgZmFsbGJhY2sgZGVmYXVsdHMuIiIiCiAgICBwYXRocyA9IENGRy5nZXQoInBhdGhzIiwge30pCiAgICB2YWx1ZSA9"
    "IHBhdGhzLmdldChrZXkpCiAgICBpZiB2YWx1ZToKICAgICAgICByZXR1cm4gUGF0aCh2YWx1ZSkKICAgIGZhbGxiYWNrID0gX0RF"
    "RkFVTFRfUEFUSFMuZ2V0KGtleSkKICAgIGlmIGZhbGxiYWNrOgogICAgICAgIHBhdGhzW2tleV0gPSBzdHIoZmFsbGJhY2spCiAg"
    "ICAgICAgcmV0dXJuIGZhbGxiYWNrCiAgICByZXR1cm4gU0NSSVBUX0RJUiAvIGtleQoKX25vcm1hbGl6ZV9jb25maWdfcGF0aHMo"
    "KQoKIyDilIDilIAgQ09MT1IgQ09OU1RBTlRTIOKAlCBkZXJpdmVkIGZyb20gcGVyc29uYSB0ZW1wbGF0ZSDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBDX1BSSU1B"
    "UlksIENfU0VDT05EQVJZLCBDX0FDQ0VOVCwgQ19CRywgQ19QQU5FTCwgQ19CT1JERVIsCiMgQ19URVhULCBDX1RFWFRfRElNIGFy"
    "ZSBpbmplY3RlZCBhdCB0aGUgdG9wIG9mIHRoaXMgZmlsZSBieSBkZWNrX2J1aWxkZXIuCiMgRXZlcnl0aGluZyBiZWxvdyBpcyBk"
    "ZXJpdmVkIGZyb20gdGhvc2UgaW5qZWN0ZWQgdmFsdWVzLgoKIyBTZW1hbnRpYyBhbGlhc2VzIOKAlCBtYXAgcGVyc29uYSBjb2xv"
    "cnMgdG8gbmFtZWQgcm9sZXMgdXNlZCB0aHJvdWdob3V0IHRoZSBVSQpDX0NSSU1TT04gICAgID0gQ19QUklNQVJZICAgICAgICAg"
    "ICMgbWFpbiBhY2NlbnQgKGJ1dHRvbnMsIGJvcmRlcnMsIGhpZ2hsaWdodHMpCkNfQ1JJTVNPTl9ESU0gPSBDX1BSSU1BUlkgKyAi"
    "ODgiICAgIyBkaW0gYWNjZW50IGZvciBzdWJ0bGUgYm9yZGVycwpDX0dPTEQgICAgICAgID0gQ19TRUNPTkRBUlkgICAgICAgICMg"
    "bWFpbiBsYWJlbC90ZXh0L0FJIG91dHB1dCBjb2xvcgpDX0dPTERfRElNICAgID0gQ19TRUNPTkRBUlkgKyAiODgiICMgZGltIHNl"
    "Y29uZGFyeQpDX0dPTERfQlJJR0hUID0gQ19BQ0NFTlQgICAgICAgICAgICMgZW1waGFzaXMsIGhvdmVyIHN0YXRlcwpDX1NJTFZF"
    "UiAgICAgID0gQ19URVhUX0RJTSAgICAgICAgICMgc2Vjb25kYXJ5IHRleHQgKGFscmVhZHkgaW5qZWN0ZWQpCkNfU0lMVkVSX0RJ"
    "TSAgPSBDX1RFWFRfRElNICsgIjg4IiAgIyBkaW0gc2Vjb25kYXJ5IHRleHQKQ19NT05JVE9SICAgICA9IENfQkcgICAgICAgICAg"
    "ICAgICAjIGNoYXQgZGlzcGxheSBiYWNrZ3JvdW5kIChhbHJlYWR5IGluamVjdGVkKQpDX0JHMiAgICAgICAgID0gQ19CRyAgICAg"
    "ICAgICAgICAgICMgc2Vjb25kYXJ5IGJhY2tncm91bmQKQ19CRzMgICAgICAgICA9IENfUEFORUwgICAgICAgICAgICAjIHRlcnRp"
    "YXJ5L2lucHV0IGJhY2tncm91bmQgKGFscmVhZHkgaW5qZWN0ZWQpCkNfQkxPT0QgICAgICAgPSAnIzhiMDAwMCcgICAgICAgICAg"
    "IyBlcnJvciBzdGF0ZXMsIGRhbmdlciDigJQgdW5pdmVyc2FsCkNfUFVSUExFICAgICAgPSAnIzg4NTVjYycgICAgICAgICAgIyBT"
    "WVNURU0gbWVzc2FnZXMg4oCUIHVuaXZlcnNhbApDX1BVUlBMRV9ESU0gID0gJyMyYTA1MmEnICAgICAgICAgICMgZGltIHB1cnBs"
    "ZSDigJQgdW5pdmVyc2FsCkNfR1JFRU4gICAgICAgPSAnIzQ0YWE2NicgICAgICAgICAgIyBwb3NpdGl2ZSBzdGF0ZXMg4oCUIHVu"
    "aXZlcnNhbApDX0JMVUUgICAgICAgID0gJyM0NDg4Y2MnICAgICAgICAgICMgaW5mbyBzdGF0ZXMg4oCUIHVuaXZlcnNhbAoKIyBG"
    "b250IGhlbHBlciDigJQgZXh0cmFjdHMgcHJpbWFyeSBmb250IG5hbWUgZm9yIFFGb250KCkgY2FsbHMKREVDS19GT05UID0gVUlf"
    "Rk9OVF9GQU1JTFkuc3BsaXQoJywnKVswXS5zdHJpcCgpLnN0cmlwKCInIikKCiMgRW1vdGlvbiDihpIgY29sb3IgbWFwcGluZyAo"
    "Zm9yIGVtb3Rpb24gcmVjb3JkIGNoaXBzKQpFTU9USU9OX0NPTE9SUzogZGljdFtzdHIsIHN0cl0gPSB7CiAgICAidmljdG9yeSI6"
    "ICAgIENfR09MRCwKICAgICJzbXVnIjogICAgICAgQ19HT0xELAogICAgImltcHJlc3NlZCI6ICBDX0dPTEQsCiAgICAicmVsaWV2"
    "ZWQiOiAgIENfR09MRCwKICAgICJoYXBweSI6ICAgICAgQ19HT0xELAogICAgImZsaXJ0eSI6ICAgICBDX0dPTEQsCiAgICAicGFu"
    "aWNrZWQiOiAgIENfQ1JJTVNPTiwKICAgICJhbmdyeSI6ICAgICAgQ19DUklNU09OLAogICAgInNob2NrZWQiOiAgICBDX0NSSU1T"
    "T04sCiAgICAiY2hlYXRtb2RlIjogIENfQ1JJTVNPTiwKICAgICJjb25jZXJuZWQiOiAgIiNjYzY2MjIiLAogICAgInNhZCI6ICAg"
    "ICAgICAiI2NjNjYyMiIsCiAgICAiaHVtaWxpYXRlZCI6ICIjY2M2NjIyIiwKICAgICJmbHVzdGVyZWQiOiAgIiNjYzY2MjIiLAog"
    "ICAgInBsb3R0aW5nIjogICBDX1BVUlBMRSwKICAgICJzdXNwaWNpb3VzIjogQ19QVVJQTEUsCiAgICAiZW52aW91cyI6ICAgIENf"
    "UFVSUExFLAogICAgImZvY3VzZWQiOiAgICBDX1NJTFZFUiwKICAgICJhbGVydCI6ICAgICAgQ19TSUxWRVIsCiAgICAibmV1dHJh"
    "bCI6ICAgIENfVEVYVF9ESU0sCn0KCiMg4pSA4pSAIERFQ09SQVRJVkUgQ09OU1RBTlRTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFJVTkVTIGlz"
    "IHNvdXJjZWQgZnJvbSBVSV9SVU5FUyBpbmplY3RlZCBieSB0aGUgcGVyc29uYSB0ZW1wbGF0ZQpSVU5FUyA9IFVJX1JVTkVTCgoj"
    "IEZhY2UgaW1hZ2UgbWFwIOKAlCBwcmVmaXggZnJvbSBGQUNFX1BSRUZJWCwgZmlsZXMgbGl2ZSBpbiBjb25maWcgcGF0aHMuZmFj"
    "ZXMKRkFDRV9GSUxFUzogZGljdFtzdHIsIHN0cl0gPSB7CiAgICAibmV1dHJhbCI6ICAgIGYie0ZBQ0VfUFJFRklYfV9OZXV0cmFs"
    "LnBuZyIsCiAgICAiYWxlcnQiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9BbGVydC5wbmciLAogICAgImZvY3VzZWQiOiAgICBmIntG"
    "QUNFX1BSRUZJWH1fRm9jdXNlZC5wbmciLAogICAgInNtdWciOiAgICAgICBmIntGQUNFX1BSRUZJWH1fU211Zy5wbmciLAogICAg"
    "ImNvbmNlcm5lZCI6ICBmIntGQUNFX1BSRUZJWH1fQ29uY2VybmVkLnBuZyIsCiAgICAic2FkIjogICAgICAgIGYie0ZBQ0VfUFJF"
    "RklYfV9TYWRfQ3J5aW5nLnBuZyIsCiAgICAicmVsaWV2ZWQiOiAgIGYie0ZBQ0VfUFJFRklYfV9SZWxpZXZlZC5wbmciLAogICAg"
    "ImltcHJlc3NlZCI6ICBmIntGQUNFX1BSRUZJWH1fSW1wcmVzc2VkLnBuZyIsCiAgICAidmljdG9yeSI6ICAgIGYie0ZBQ0VfUFJF"
    "RklYfV9WaWN0b3J5LnBuZyIsCiAgICAiaHVtaWxpYXRlZCI6IGYie0ZBQ0VfUFJFRklYfV9IdW1pbGlhdGVkLnBuZyIsCiAgICAi"
    "c3VzcGljaW91cyI6IGYie0ZBQ0VfUFJFRklYfV9TdXNwaWNpb3VzLnBuZyIsCiAgICAicGFuaWNrZWQiOiAgIGYie0ZBQ0VfUFJF"
    "RklYfV9QYW5pY2tlZC5wbmciLAogICAgImNoZWF0bW9kZSI6ICBmIntGQUNFX1BSRUZJWH1fQ2hlYXRfTW9kZS5wbmciLAogICAg"
    "ImFuZ3J5IjogICAgICBmIntGQUNFX1BSRUZJWH1fQW5ncnkucG5nIiwKICAgICJwbG90dGluZyI6ICAgZiJ7RkFDRV9QUkVGSVh9"
    "X1Bsb3R0aW5nLnBuZyIsCiAgICAic2hvY2tlZCI6ICAgIGYie0ZBQ0VfUFJFRklYfV9TaG9ja2VkLnBuZyIsCiAgICAiaGFwcHki"
    "OiAgICAgIGYie0ZBQ0VfUFJFRklYfV9IYXBweS5wbmciLAogICAgImZsaXJ0eSI6ICAgICBmIntGQUNFX1BSRUZJWH1fRmxpcnR5"
    "LnBuZyIsCiAgICAiZmx1c3RlcmVkIjogIGYie0ZBQ0VfUFJFRklYfV9GbHVzdGVyZWQucG5nIiwKICAgICJlbnZpb3VzIjogICAg"
    "ZiJ7RkFDRV9QUkVGSVh9X0VudmlvdXMucG5nIiwKfQoKU0VOVElNRU5UX0xJU1QgPSAoCiAgICAibmV1dHJhbCwgYWxlcnQsIGZv"
    "Y3VzZWQsIHNtdWcsIGNvbmNlcm5lZCwgc2FkLCByZWxpZXZlZCwgaW1wcmVzc2VkLCAiCiAgICAidmljdG9yeSwgaHVtaWxpYXRl"
    "ZCwgc3VzcGljaW91cywgcGFuaWNrZWQsIGFuZ3J5LCBwbG90dGluZywgc2hvY2tlZCwgIgogICAgImhhcHB5LCBmbGlydHksIGZs"
    "dXN0ZXJlZCwgZW52aW91cyIKKQoKIyDilIDilIAgU1lTVEVNIFBST01QVCDigJQgaW5qZWN0ZWQgZnJvbSBwZXJzb25hIHRlbXBs"
    "YXRlIGF0IHRvcCBvZiBmaWxlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFNZU1RFTV9QUk9NUFRf"
    "QkFTRSBpcyBhbHJlYWR5IGRlZmluZWQgYWJvdmUgZnJvbSA8PDxTWVNURU1fUFJPTVBUPj4+IGluamVjdGlvbi4KIyBEbyBub3Qg"
    "cmVkZWZpbmUgaXQgaGVyZS4KCiMg4pSA4pSAIEdMT0JBTCBTVFlMRVNIRUVUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApTVFlMRSA9"
    "IGYiIiIKUU1haW5XaW5kb3csIFFXaWRnZXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JHfTsKICAgIGNvbG9yOiB7Q19H"
    "T0xEfTsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9Owp9fQpRVGV4dEVkaXQge3sKICAgIGJhY2tncm91bmQtY29s"
    "b3I6IHtDX01PTklUT1J9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19"
    "OwogICAgYm9yZGVyLXJhZGl1czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6"
    "IDEycHg7CiAgICBwYWRkaW5nOiA4cHg7CiAgICBzZWxlY3Rpb24tYmFja2dyb3VuZC1jb2xvcjoge0NfQ1JJTVNPTl9ESU19Owp9"
    "fQpRTGluZUVkaXQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JHM307CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsKICAgIGJvcmRlci1yYWRpdXM6IDJweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9O"
    "VF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxM3B4OwogICAgcGFkZGluZzogOHB4IDEycHg7Cn19ClFMaW5lRWRpdDpmb2N1cyB7"
    "ewogICAgYm9yZGVyOiAxcHggc29saWQge0NfR09MRH07CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19QQU5FTH07Cn19ClFQdXNo"
    "QnV0dG9uIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19DUklNU09OX0RJTX07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsKICAgIGJvcmRlci1yYWRpdXM6IDJweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlf"
    "Rk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMnB4OwogICAgZm9udC13ZWlnaHQ6IGJvbGQ7CiAgICBwYWRkaW5nOiA4cHgg"
    "MjBweDsKICAgIGxldHRlci1zcGFjaW5nOiAycHg7Cn19ClFQdXNoQnV0dG9uOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9y"
    "OiB7Q19DUklNU09OfTsKICAgIGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07Cn19ClFQdXNoQnV0dG9uOnByZXNzZWQge3sKICAgIGJh"
    "Y2tncm91bmQtY29sb3I6IHtDX0JMT09EfTsKICAgIGJvcmRlci1jb2xvcjoge0NfQkxPT0R9OwogICAgY29sb3I6IHtDX1RFWFR9"
    "Owp9fQpRUHVzaEJ1dHRvbjpkaXNhYmxlZCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19U"
    "RVhUX0RJTX07CiAgICBib3JkZXItY29sb3I6IHtDX1RFWFRfRElNfTsKfX0KUVNjcm9sbEJhcjp2ZXJ0aWNhbCB7ewogICAgYmFj"
    "a2dyb3VuZDoge0NfQkd9OwogICAgd2lkdGg6IDZweDsKICAgIGJvcmRlcjogbm9uZTsKfX0KUVNjcm9sbEJhcjo6aGFuZGxlOnZl"
    "cnRpY2FsIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICBib3JkZXItcmFkaXVzOiAzcHg7Cn19ClFTY3Jv"
    "bGxCYXI6OmhhbmRsZTp2ZXJ0aWNhbDpob3ZlciB7ewogICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTn07Cn19ClFTY3JvbGxCYXI6"
    "OmFkZC1saW5lOnZlcnRpY2FsLCBRU2Nyb2xsQmFyOjpzdWItbGluZTp2ZXJ0aWNhbCB7ewogICAgaGVpZ2h0OiAwcHg7Cn19ClFU"
    "YWJXaWRnZXQ6OnBhbmUge3sKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIGJhY2tncm91bmQ6IHtD"
    "X0JHMn07Cn19ClFUYWJCYXI6OnRhYiB7ewogICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19URVhUX0RJTX07"
    "CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBwYWRkaW5nOiA2cHggMTRweDsKICAgIGZvbnQtZmFt"
    "aWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMHB4OwogICAgbGV0dGVyLXNwYWNpbmc6IDFweDsKfX0KUVRh"
    "YkJhcjo6dGFiOnNlbGVjdGVkIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICBjb2xvcjoge0NfR09MRH07"
    "CiAgICBib3JkZXItYm90dG9tOiAycHggc29saWQge0NfQ1JJTVNPTn07Cn19ClFUYWJCYXI6OnRhYjpob3ZlciB7ewogICAgYmFj"
    "a2dyb3VuZDoge0NfUEFORUx9OwogICAgY29sb3I6IHtDX0dPTERfRElNfTsKfX0KUVRhYmxlV2lkZ2V0IHt7CiAgICBiYWNrZ3Jv"
    "dW5kOiB7Q19CRzJ9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19Owog"
    "ICAgZ3JpZGxpbmUtY29sb3I6IHtDX0JPUkRFUn07CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKICAgIGZvbnQt"
    "c2l6ZTogMTFweDsKfX0KUVRhYmxlV2lkZ2V0OjppdGVtOnNlbGVjdGVkIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJ"
    "TX07CiAgICBjb2xvcjoge0NfR09MRF9CUklHSFR9Owp9fQpRSGVhZGVyVmlldzo6c2VjdGlvbiB7ewogICAgYmFja2dyb3VuZDog"
    "e0NfQkczfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIHBh"
    "ZGRpbmc6IDRweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMHB4OwogICAgZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7CiAgICBsZXR0ZXItc3BhY2luZzogMXB4Owp9fQpRQ29tYm9Cb3gge3sKICAgIGJhY2tncm91bmQ6IHtD"
    "X0JHM307CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBwYWRk"
    "aW5nOiA0cHggOHB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07Cn19ClFDb21ib0JveDo6ZHJvcC1kb3duIHt7"
    "CiAgICBib3JkZXI6IG5vbmU7Cn19ClFDaGVja0JveCB7ewogICAgY29sb3I6IHtDX0dPTER9OwogICAgZm9udC1mYW1pbHk6IHtV"
    "SV9GT05UX0ZBTUlMWX07Cn19ClFMYWJlbCB7ewogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiBub25lOwp9fQpRU3Bs"
    "aXR0ZXI6OmhhbmRsZSB7ewogICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OwogICAgd2lkdGg6IDJweDsKfX0KIiIiCgoj"
    "IOKUgOKUgCBESVJFQ1RPUlkgQk9PVFNUUkFQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgYm9vdHN0cmFwX2RpcmVjdG9yaWVzKCkgLT4g"
    "Tm9uZToKICAgICIiIgogICAgQ3JlYXRlIGFsbCByZXF1aXJlZCBkaXJlY3RvcmllcyBpZiB0aGV5IGRvbid0IGV4aXN0LgogICAg"
    "Q2FsbGVkIG9uIHN0YXJ0dXAgYmVmb3JlIGFueXRoaW5nIGVsc2UuIFNhZmUgdG8gY2FsbCBtdWx0aXBsZSB0aW1lcy4KICAgIEFs"
    "c28gbWlncmF0ZXMgZmlsZXMgZnJvbSBvbGQgW0RlY2tOYW1lXV9NZW1vcmllcyBsYXlvdXQgaWYgZGV0ZWN0ZWQuCiAgICAiIiIK"
    "ICAgIGRpcnMgPSBbCiAgICAgICAgY2ZnX3BhdGgoImZhY2VzIiksCiAgICAgICAgY2ZnX3BhdGgoInNvdW5kcyIpLAogICAgICAg"
    "IGNmZ19wYXRoKCJtZW1vcmllcyIpLAogICAgICAgIGNmZ19wYXRoKCJzZXNzaW9ucyIpLAogICAgICAgIGNmZ19wYXRoKCJzbCIp"
    "LAogICAgICAgIGNmZ19wYXRoKCJleHBvcnRzIiksCiAgICAgICAgY2ZnX3BhdGgoImxvZ3MiKSwKICAgICAgICBjZmdfcGF0aCgi"
    "YmFja3VwcyIpLAogICAgICAgIGNmZ19wYXRoKCJwZXJzb25hcyIpLAogICAgICAgIGNmZ19wYXRoKCJnb29nbGUiKSwKICAgICAg"
    "ICBjZmdfcGF0aCgiZ29vZ2xlIikgLyAiZXhwb3J0cyIsCiAgICBdCiAgICBmb3IgZCBpbiBkaXJzOgogICAgICAgIGQubWtkaXIo"
    "cGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQoKICAgICMgQ3JlYXRlIGVtcHR5IEpTT05MIGZpbGVzIGlmIHRoZXkgZG9uJ3Qg"
    "ZXhpc3QKICAgIG1lbW9yeV9kaXIgPSBjZmdfcGF0aCgibWVtb3JpZXMiKQogICAgZm9yIGZuYW1lIGluICgibWVzc2FnZXMuanNv"
    "bmwiLCAibWVtb3JpZXMuanNvbmwiLCAidGFza3MuanNvbmwiLAogICAgICAgICAgICAgICAgICAibGVzc29uc19sZWFybmVkLmpz"
    "b25sIiwgInBlcnNvbmFfaGlzdG9yeS5qc29ubCIpOgogICAgICAgIGZwID0gbWVtb3J5X2RpciAvIGZuYW1lCiAgICAgICAgaWYg"
    "bm90IGZwLmV4aXN0cygpOgogICAgICAgICAgICBmcC53cml0ZV90ZXh0KCIiLCBlbmNvZGluZz0idXRmLTgiKQoKICAgIHNsX2Rp"
    "ciA9IGNmZ19wYXRoKCJzbCIpCiAgICBmb3IgZm5hbWUgaW4gKCJzbF9zY2Fucy5qc29ubCIsICJzbF9jb21tYW5kcy5qc29ubCIp"
    "OgogICAgICAgIGZwID0gc2xfZGlyIC8gZm5hbWUKICAgICAgICBpZiBub3QgZnAuZXhpc3RzKCk6CiAgICAgICAgICAgIGZwLndy"
    "aXRlX3RleHQoIiIsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgc2Vzc2lvbnNfZGlyID0gY2ZnX3BhdGgoInNlc3Npb25zIikKICAg"
    "IGlkeCA9IHNlc3Npb25zX2RpciAvICJzZXNzaW9uX2luZGV4Lmpzb24iCiAgICBpZiBub3QgaWR4LmV4aXN0cygpOgogICAgICAg"
    "IGlkeC53cml0ZV90ZXh0KGpzb24uZHVtcHMoeyJzZXNzaW9ucyI6IFtdfSwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiKQoK"
    "ICAgIHN0YXRlX3BhdGggPSBtZW1vcnlfZGlyIC8gInN0YXRlLmpzb24iCiAgICBpZiBub3Qgc3RhdGVfcGF0aC5leGlzdHMoKToK"
    "ICAgICAgICBfd3JpdGVfZGVmYXVsdF9zdGF0ZShzdGF0ZV9wYXRoKQoKICAgIGluZGV4X3BhdGggPSBtZW1vcnlfZGlyIC8gImlu"
    "ZGV4Lmpzb24iCiAgICBpZiBub3QgaW5kZXhfcGF0aC5leGlzdHMoKToKICAgICAgICBpbmRleF9wYXRoLndyaXRlX3RleHQoCiAg"
    "ICAgICAgICAgIGpzb24uZHVtcHMoeyJ2ZXJzaW9uIjogQVBQX1ZFUlNJT04sICJ0b3RhbF9tZXNzYWdlcyI6IDAsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJ0b3RhbF9tZW1vcmllcyI6IDB9LCBpbmRlbnQ9MiksCiAgICAgICAgICAgIGVuY29kaW5nPSJ1dGYt"
    "OCIKICAgICAgICApCgogICAgIyBMZWdhY3kgbWlncmF0aW9uOiBpZiBvbGQgTW9yZ2FubmFfTWVtb3JpZXMgZm9sZGVyIGV4aXN0"
    "cywgbWlncmF0ZSBmaWxlcwogICAgX21pZ3JhdGVfbGVnYWN5X2ZpbGVzKCkKCmRlZiBfd3JpdGVfZGVmYXVsdF9zdGF0ZShwYXRo"
    "OiBQYXRoKSAtPiBOb25lOgogICAgc3RhdGUgPSB7CiAgICAgICAgInBlcnNvbmFfbmFtZSI6IERFQ0tfTkFNRSwKICAgICAgICAi"
    "ZGVja192ZXJzaW9uIjogQVBQX1ZFUlNJT04sCiAgICAgICAgInNlc3Npb25fY291bnQiOiAwLAogICAgICAgICJsYXN0X3N0YXJ0"
    "dXAiOiBOb25lLAogICAgICAgICJsYXN0X3NodXRkb3duIjogTm9uZSwKICAgICAgICAibGFzdF9hY3RpdmUiOiBOb25lLAogICAg"
    "ICAgICJ0b3RhbF9tZXNzYWdlcyI6IDAsCiAgICAgICAgInRvdGFsX21lbW9yaWVzIjogMCwKICAgICAgICAiaW50ZXJuYWxfbmFy"
    "cmF0aXZlIjoge30sCiAgICAgICAgInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24iOiAiRE9STUFOVCIsCiAgICB9CiAgICBwYXRo"
    "LndyaXRlX3RleHQoanNvbi5kdW1wcyhzdGF0ZSwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiKQoKZGVmIF9taWdyYXRlX2xl"
    "Z2FjeV9maWxlcygpIC0+IE5vbmU6CiAgICAiIiIKICAgIElmIG9sZCBEOlxcQUlcXE1vZGVsc1xcW0RlY2tOYW1lXV9NZW1vcmll"
    "cyBsYXlvdXQgaXMgZGV0ZWN0ZWQsCiAgICBtaWdyYXRlIGZpbGVzIHRvIG5ldyBzdHJ1Y3R1cmUgc2lsZW50bHkuCiAgICAiIiIK"
    "ICAgICMgVHJ5IHRvIGZpbmQgb2xkIGxheW91dCByZWxhdGl2ZSB0byBtb2RlbCBwYXRoCiAgICBtb2RlbF9wYXRoID0gUGF0aChD"
    "RkdbIm1vZGVsIl0uZ2V0KCJwYXRoIiwgIiIpKQogICAgaWYgbm90IG1vZGVsX3BhdGguZXhpc3RzKCk6CiAgICAgICAgcmV0dXJu"
    "CiAgICBvbGRfcm9vdCA9IG1vZGVsX3BhdGgucGFyZW50IC8gZiJ7REVDS19OQU1FfV9NZW1vcmllcyIKICAgIGlmIG5vdCBvbGRf"
    "cm9vdC5leGlzdHMoKToKICAgICAgICByZXR1cm4KCiAgICBtaWdyYXRpb25zID0gWwogICAgICAgIChvbGRfcm9vdCAvICJtZW1v"
    "cmllcy5qc29ubCIsICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJtZW1vcmllcy5qc29ubCIpLAogICAgICAgIChv"
    "bGRfcm9vdCAvICJtZXNzYWdlcy5qc29ubCIsICAgICAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAibWVzc2FnZXMuanNv"
    "bmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAidGFza3MuanNvbmwiLCAgICAgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIp"
    "IC8gInRhc2tzLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gInN0YXRlLmpzb24iLCAgICAgICAgICAgICAgICBjZmdfcGF0"
    "aCgibWVtb3JpZXMiKSAvICJzdGF0ZS5qc29uIiksCiAgICAgICAgKG9sZF9yb290IC8gImluZGV4Lmpzb24iLCAgICAgICAgICAg"
    "ICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJpbmRleC5qc29uIiksCiAgICAgICAgKG9sZF9yb290IC8gInNsX3NjYW5zLmpz"
    "b25sIiwgICAgICAgICAgICBjZmdfcGF0aCgic2wiKSAvICJzbF9zY2Fucy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAvICJz"
    "bF9jb21tYW5kcy5qc29ubCIsICAgICAgICAgY2ZnX3BhdGgoInNsIikgLyAic2xfY29tbWFuZHMuanNvbmwiKSwKICAgICAgICAo"
    "b2xkX3Jvb3QgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29uIiwgICAgIFBhdGgoQ0ZHWyJnb29nbGUiXVsidG9rZW4iXSkpLAogICAg"
    "ICAgIChvbGRfcm9vdCAvICJjb25maWciIC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIiwKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICBQYXRoKENGR1siZ29vZ2xlIl1bImNyZWRlbnRpYWxzIl0pKSwKICAgICAgICAo"
    "b2xkX3Jvb3QgLyAic291bmRzIiAvIGYie1NPVU5EX1BSRUZJWH1fYWxlcnQud2F2IiwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICBjZmdfcGF0aCgic291bmRzIikgLyBmIntTT1VORF9QUkVGSVh9X2FsZXJ0LndhdiIp"
    "LAogICAgXQoKICAgIGZvciBzcmMsIGRzdCBpbiBtaWdyYXRpb25zOgogICAgICAgIGlmIHNyYy5leGlzdHMoKSBhbmQgbm90IGRz"
    "dC5leGlzdHMoKToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgZHN0LnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUs"
    "IGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgICAgICBpbXBvcnQgc2h1dGlsCiAgICAgICAgICAgICAgICBzaHV0aWwuY29weTIo"
    "c3RyKHNyYyksIHN0cihkc3QpKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAg"
    "ICMgTWlncmF0ZSBmYWNlIGltYWdlcwogICAgb2xkX2ZhY2VzID0gb2xkX3Jvb3QgLyAiRmFjZXMiCiAgICBuZXdfZmFjZXMgPSBj"
    "ZmdfcGF0aCgiZmFjZXMiKQogICAgaWYgb2xkX2ZhY2VzLmV4aXN0cygpOgogICAgICAgIGZvciBpbWcgaW4gb2xkX2ZhY2VzLmds"
    "b2IoIioucG5nIik6CiAgICAgICAgICAgIGRzdCA9IG5ld19mYWNlcyAvIGltZy5uYW1lCiAgICAgICAgICAgIGlmIG5vdCBkc3Qu"
    "ZXhpc3RzKCk6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgaW1wb3J0IHNodXRpbAogICAgICAgICAg"
    "ICAgICAgICAgIHNodXRpbC5jb3B5MihzdHIoaW1nKSwgc3RyKGRzdCkpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "OgogICAgICAgICAgICAgICAgICAgIHBhc3MKCiMg4pSA4pSAIERBVEVUSU1FIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmRlZiBsb2NhbF9ub3dfaXNvKCkgLT4gc3RyOgogICAgcmV0dXJuIGRhdGV0aW1lLm5vdygpLnJlcGxhY2UobWljcm9zZWNv"
    "bmQ9MCkuaXNvZm9ybWF0KCkKCmRlZiBwYXJzZV9pc28odmFsdWU6IHN0cikgLT4gT3B0aW9uYWxbZGF0ZXRpbWVdOgogICAgaWYg"
    "bm90IHZhbHVlOgogICAgICAgIHJldHVybiBOb25lCiAgICB2YWx1ZSA9IHZhbHVlLnN0cmlwKCkKICAgIHRyeToKICAgICAgICBp"
    "ZiB2YWx1ZS5lbmRzd2l0aCgiWiIpOgogICAgICAgICAgICByZXR1cm4gZGF0ZXRpbWUuZnJvbWlzb2Zvcm1hdCh2YWx1ZVs6LTFd"
    "KS5yZXBsYWNlKHR6aW5mbz10aW1lem9uZS51dGMpCiAgICAgICAgcmV0dXJuIGRhdGV0aW1lLmZyb21pc29mb3JtYXQodmFsdWUp"
    "CiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHJldHVybiBOb25lCgpfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQ6"
    "IHNldFt0dXBsZV0gPSBzZXQoKQoKCmRlZiBfbG9jYWxfdHppbmZvKCk6CiAgICByZXR1cm4gZGF0ZXRpbWUubm93KCkuYXN0aW1l"
    "em9uZSgpLnR6aW5mbyBvciB0aW1lem9uZS51dGMKCgpkZWYgbm93X2Zvcl9jb21wYXJlKCk6CiAgICByZXR1cm4gZGF0ZXRpbWUu"
    "bm93KF9sb2NhbF90emluZm8oKSkKCgpkZWYgbm9ybWFsaXplX2RhdGV0aW1lX2Zvcl9jb21wYXJlKGR0X3ZhbHVlLCBjb250ZXh0"
    "OiBzdHIgPSAiIik6CiAgICBpZiBkdF92YWx1ZSBpcyBOb25lOgogICAgICAgIHJldHVybiBOb25lCiAgICBpZiBub3QgaXNpbnN0"
    "YW5jZShkdF92YWx1ZSwgZGF0ZXRpbWUpOgogICAgICAgIHJldHVybiBOb25lCiAgICBsb2NhbF90eiA9IF9sb2NhbF90emluZm8o"
    "KQogICAgaWYgZHRfdmFsdWUudHppbmZvIGlzIE5vbmU6CiAgICAgICAgbm9ybWFsaXplZCA9IGR0X3ZhbHVlLnJlcGxhY2UodHpp"
    "bmZvPWxvY2FsX3R6KQogICAgICAgIGtleSA9ICgibmFpdmUiLCBjb250ZXh0KQogICAgICAgIGlmIGtleSBub3QgaW4gX0RBVEVU"
    "SU1FX05PUk1BTElaQVRJT05fTE9HR0VEOgogICAgICAgICAgICBfZWFybHlfbG9nKAogICAgICAgICAgICAgICAgZiJbREFURVRJ"
    "TUVdW0lORk9dIE5vcm1hbGl6ZWQgbmFpdmUgZGF0ZXRpbWUgdG8gbG9jYWwgdGltZXpvbmUgZm9yIHtjb250ZXh0IG9yICdnZW5l"
    "cmFsJ30gY29tcGFyaXNvbnMuIgogICAgICAgICAgICApCiAgICAgICAgICAgIF9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dF"
    "RC5hZGQoa2V5KQogICAgICAgIHJldHVybiBub3JtYWxpemVkCiAgICBub3JtYWxpemVkID0gZHRfdmFsdWUuYXN0aW1lem9uZShs"
    "b2NhbF90eikKICAgIGR0X3R6X25hbWUgPSBzdHIoZHRfdmFsdWUudHppbmZvKQogICAga2V5ID0gKCJhd2FyZSIsIGNvbnRleHQs"
    "IGR0X3R6X25hbWUpCiAgICBpZiBrZXkgbm90IGluIF9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dFRCBhbmQgZHRfdHpfbmFt"
    "ZSBub3QgaW4geyJVVEMiLCBzdHIobG9jYWxfdHopfToKICAgICAgICBfZWFybHlfbG9nKAogICAgICAgICAgICBmIltEQVRFVElN"
    "RV1bSU5GT10gTm9ybWFsaXplZCB0aW1lem9uZS1hd2FyZSBkYXRldGltZSBmcm9tIHtkdF90el9uYW1lfSB0byBsb2NhbCB0aW1l"
    "em9uZSBmb3Ige2NvbnRleHQgb3IgJ2dlbmVyYWwnfSBjb21wYXJpc29ucy4iCiAgICAgICAgKQogICAgICAgIF9EQVRFVElNRV9O"
    "T1JNQUxJWkFUSU9OX0xPR0dFRC5hZGQoa2V5KQogICAgcmV0dXJuIG5vcm1hbGl6ZWQKCgpkZWYgcGFyc2VfaXNvX2Zvcl9jb21w"
    "YXJlKHZhbHVlLCBjb250ZXh0OiBzdHIgPSAiIik6CiAgICByZXR1cm4gbm9ybWFsaXplX2RhdGV0aW1lX2Zvcl9jb21wYXJlKHBh"
    "cnNlX2lzbyh2YWx1ZSksIGNvbnRleHQ9Y29udGV4dCkKCgpkZWYgX3Rhc2tfZHVlX3NvcnRfa2V5KHRhc2s6IGRpY3QpOgogICAg"
    "ZHVlID0gcGFyc2VfaXNvX2Zvcl9jb21wYXJlKCh0YXNrIG9yIHt9KS5nZXQoImR1ZV9hdCIpIG9yICh0YXNrIG9yIHt9KS5nZXQo"
    "ImR1ZSIpLCBjb250ZXh0PSJ0YXNrX3NvcnQiKQogICAgaWYgZHVlIGlzIE5vbmU6CiAgICAgICAgcmV0dXJuICgxLCBkYXRldGlt"
    "ZS5tYXgucmVwbGFjZSh0emluZm89dGltZXpvbmUudXRjKSkKICAgIHJldHVybiAoMCwgZHVlLmFzdGltZXpvbmUodGltZXpvbmUu"
    "dXRjKSwgKCh0YXNrIG9yIHt9KS5nZXQoInRleHQiKSBvciAiIikubG93ZXIoKSkKCgpkZWYgZm9ybWF0X2R1cmF0aW9uKHNlY29u"
    "ZHM6IGZsb2F0KSAtPiBzdHI6CiAgICB0b3RhbCA9IG1heCgwLCBpbnQoc2Vjb25kcykpCiAgICBkYXlzLCByZW0gPSBkaXZtb2Qo"
    "dG90YWwsIDg2NDAwKQogICAgaG91cnMsIHJlbSA9IGRpdm1vZChyZW0sIDM2MDApCiAgICBtaW51dGVzLCBzZWNzID0gZGl2bW9k"
    "KHJlbSwgNjApCiAgICBwYXJ0cyA9IFtdCiAgICBpZiBkYXlzOiAgICBwYXJ0cy5hcHBlbmQoZiJ7ZGF5c31kIikKICAgIGlmIGhv"
    "dXJzOiAgIHBhcnRzLmFwcGVuZChmIntob3Vyc31oIikKICAgIGlmIG1pbnV0ZXM6IHBhcnRzLmFwcGVuZChmInttaW51dGVzfW0i"
    "KQogICAgaWYgbm90IHBhcnRzOiBwYXJ0cy5hcHBlbmQoZiJ7c2Vjc31zIikKICAgIHJldHVybiAiICIuam9pbihwYXJ0c1s6M10p"
    "CgojIOKUgOKUgCBNT09OIFBIQVNFIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQ29ycmVjdGVkIGlsbHVtaW5hdGlvbiBt"
    "YXRoIOKAlCBkaXNwbGF5ZWQgbW9vbiBtYXRjaGVzIGxhYmVsZWQgcGhhc2UuCgpfS05PV05fTkVXX01PT04gPSBkYXRlKDIwMDAs"
    "IDEsIDYpCl9MVU5BUl9DWUNMRSAgICA9IDI5LjUzMDU4ODY3CgpkZWYgZ2V0X21vb25fcGhhc2UoKSAtPiB0dXBsZVtmbG9hdCwg"
    "c3RyLCBmbG9hdF06CiAgICAiIiIKICAgIFJldHVybnMgKHBoYXNlX2ZyYWN0aW9uLCBwaGFzZV9uYW1lLCBpbGx1bWluYXRpb25f"
    "cGN0KS4KICAgIHBoYXNlX2ZyYWN0aW9uOiAwLjAgPSBuZXcgbW9vbiwgMC41ID0gZnVsbCBtb29uLCAxLjAgPSBuZXcgbW9vbiBh"
    "Z2Fpbi4KICAgIGlsbHVtaW5hdGlvbl9wY3Q6IDDigJMxMDAsIGNvcnJlY3RlZCB0byBtYXRjaCB2aXN1YWwgcGhhc2UuCiAgICAi"
    "IiIKICAgIGRheXMgID0gKGRhdGUudG9kYXkoKSAtIF9LTk9XTl9ORVdfTU9PTikuZGF5cwogICAgY3ljbGUgPSBkYXlzICUgX0xV"
    "TkFSX0NZQ0xFCiAgICBwaGFzZSA9IGN5Y2xlIC8gX0xVTkFSX0NZQ0xFCgogICAgaWYgICBjeWNsZSA8IDEuODU6ICAgbmFtZSA9"
    "ICJORVcgTU9PTiIKICAgIGVsaWYgY3ljbGUgPCA3LjM4OiAgIG5hbWUgPSAiV0FYSU5HIENSRVNDRU5UIgogICAgZWxpZiBjeWNs"
    "ZSA8IDkuMjI6ICAgbmFtZSA9ICJGSVJTVCBRVUFSVEVSIgogICAgZWxpZiBjeWNsZSA8IDE0Ljc3OiAgbmFtZSA9ICJXQVhJTkcg"
    "R0lCQk9VUyIKICAgIGVsaWYgY3ljbGUgPCAxNi42MTogIG5hbWUgPSAiRlVMTCBNT09OIgogICAgZWxpZiBjeWNsZSA8IDIyLjE1"
    "OiAgbmFtZSA9ICJXQU5JTkcgR0lCQk9VUyIKICAgIGVsaWYgY3ljbGUgPCAyMy45OTogIG5hbWUgPSAiTEFTVCBRVUFSVEVSIgog"
    "ICAgZWxzZTogICAgICAgICAgICAgICAgbmFtZSA9ICJXQU5JTkcgQ1JFU0NFTlQiCgogICAgIyBDb3JyZWN0ZWQgaWxsdW1pbmF0"
    "aW9uOiBjb3MtYmFzZWQsIHBlYWtzIGF0IGZ1bGwgbW9vbgogICAgaWxsdW1pbmF0aW9uID0gKDEgLSBtYXRoLmNvcygyICogbWF0"
    "aC5waSAqIHBoYXNlKSkgLyAyICogMTAwCiAgICByZXR1cm4gcGhhc2UsIG5hbWUsIHJvdW5kKGlsbHVtaW5hdGlvbiwgMSkKCl9T"
    "VU5fQ0FDSEVfREFURTogT3B0aW9uYWxbZGF0ZV0gPSBOb25lCl9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTjogT3B0aW9uYWxbaW50"
    "XSA9IE5vbmUKX1NVTl9DQUNIRV9USU1FUzogdHVwbGVbc3RyLCBzdHJdID0gKCIwNjowMCIsICIxODozMCIpCgpkZWYgX3Jlc29s"
    "dmVfc29sYXJfY29vcmRpbmF0ZXMoKSAtPiB0dXBsZVtmbG9hdCwgZmxvYXRdOgogICAgIiIiCiAgICBSZXNvbHZlIGxhdGl0dWRl"
    "L2xvbmdpdHVkZSBmcm9tIHJ1bnRpbWUgY29uZmlnIHdoZW4gYXZhaWxhYmxlLgogICAgRmFsbHMgYmFjayB0byB0aW1lem9uZS1k"
    "ZXJpdmVkIGNvYXJzZSBkZWZhdWx0cy4KICAgICIiIgogICAgbGF0ID0gTm9uZQogICAgbG9uID0gTm9uZQogICAgdHJ5OgogICAg"
    "ICAgIHNldHRpbmdzID0gQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkgaWYgaXNpbnN0YW5jZShDRkcsIGRpY3QpIGVsc2Uge30KICAg"
    "ICAgICBmb3Iga2V5IGluICgibGF0aXR1ZGUiLCAibGF0Iik6CiAgICAgICAgICAgIGlmIGtleSBpbiBzZXR0aW5nczoKICAgICAg"
    "ICAgICAgICAgIGxhdCA9IGZsb2F0KHNldHRpbmdzW2tleV0pCiAgICAgICAgICAgICAgICBicmVhawogICAgICAgIGZvciBrZXkg"
    "aW4gKCJsb25naXR1ZGUiLCAibG9uIiwgImxuZyIpOgogICAgICAgICAgICBpZiBrZXkgaW4gc2V0dGluZ3M6CiAgICAgICAgICAg"
    "ICAgICBsb24gPSBmbG9hdChzZXR0aW5nc1trZXldKQogICAgICAgICAgICAgICAgYnJlYWsKICAgIGV4Y2VwdCBFeGNlcHRpb246"
    "CiAgICAgICAgbGF0ID0gTm9uZQogICAgICAgIGxvbiA9IE5vbmUKCiAgICBub3dfbG9jYWwgPSBkYXRldGltZS5ub3coKS5hc3Rp"
    "bWV6b25lKCkKICAgIHR6X29mZnNldCA9IG5vd19sb2NhbC51dGNvZmZzZXQoKSBvciB0aW1lZGVsdGEoMCkKICAgIHR6X29mZnNl"
    "dF9ob3VycyA9IHR6X29mZnNldC50b3RhbF9zZWNvbmRzKCkgLyAzNjAwLjAKCiAgICBpZiBsb24gaXMgTm9uZToKICAgICAgICBs"
    "b24gPSBtYXgoLTE4MC4wLCBtaW4oMTgwLjAsIHR6X29mZnNldF9ob3VycyAqIDE1LjApKQoKICAgIGlmIGxhdCBpcyBOb25lOgog"
    "ICAgICAgIHR6X25hbWUgPSBzdHIobm93X2xvY2FsLnR6aW5mbyBvciAiIikKICAgICAgICBzb3V0aF9oaW50ID0gYW55KHRva2Vu"
    "IGluIHR6X25hbWUgZm9yIHRva2VuIGluICgiQXVzdHJhbGlhIiwgIlBhY2lmaWMvQXVja2xhbmQiLCAiQW1lcmljYS9TYW50aWFn"
    "byIpKQogICAgICAgIGxhdCA9IC0zNS4wIGlmIHNvdXRoX2hpbnQgZWxzZSAzNS4wCgogICAgbGF0ID0gbWF4KC02Ni4wLCBtaW4o"
    "NjYuMCwgbGF0KSkKICAgIGxvbiA9IG1heCgtMTgwLjAsIG1pbigxODAuMCwgbG9uKSkKICAgIHJldHVybiBsYXQsIGxvbgoKZGVm"
    "IF9jYWxjX3NvbGFyX2V2ZW50X21pbnV0ZXMobG9jYWxfZGF5OiBkYXRlLCBsYXRpdHVkZTogZmxvYXQsIGxvbmdpdHVkZTogZmxv"
    "YXQsIHN1bnJpc2U6IGJvb2wpIC0+IE9wdGlvbmFsW2Zsb2F0XToKICAgICIiIk5PQUEtc3R5bGUgc3VucmlzZS9zdW5zZXQgc29s"
    "dmVyLiBSZXR1cm5zIGxvY2FsIG1pbnV0ZXMgZnJvbSBtaWRuaWdodC4iIiIKICAgIG4gPSBsb2NhbF9kYXkudGltZXR1cGxlKCku"
    "dG1feWRheQogICAgbG5nX2hvdXIgPSBsb25naXR1ZGUgLyAxNS4wCiAgICB0ID0gbiArICgoNiAtIGxuZ19ob3VyKSAvIDI0LjAp"
    "IGlmIHN1bnJpc2UgZWxzZSBuICsgKCgxOCAtIGxuZ19ob3VyKSAvIDI0LjApCgogICAgTSA9ICgwLjk4NTYgKiB0KSAtIDMuMjg5"
    "CiAgICBMID0gTSArICgxLjkxNiAqIG1hdGguc2luKG1hdGgucmFkaWFucyhNKSkpICsgKDAuMDIwICogbWF0aC5zaW4obWF0aC5y"
    "YWRpYW5zKDIgKiBNKSkpICsgMjgyLjYzNAogICAgTCA9IEwgJSAzNjAuMAoKICAgIFJBID0gbWF0aC5kZWdyZWVzKG1hdGguYXRh"
    "bigwLjkxNzY0ICogbWF0aC50YW4obWF0aC5yYWRpYW5zKEwpKSkpCiAgICBSQSA9IFJBICUgMzYwLjAKICAgIExfcXVhZHJhbnQg"
    "PSAobWF0aC5mbG9vcihMIC8gOTAuMCkpICogOTAuMAogICAgUkFfcXVhZHJhbnQgPSAobWF0aC5mbG9vcihSQSAvIDkwLjApKSAq"
    "IDkwLjAKICAgIFJBID0gKFJBICsgKExfcXVhZHJhbnQgLSBSQV9xdWFkcmFudCkpIC8gMTUuMAoKICAgIHNpbl9kZWMgPSAwLjM5"
    "NzgyICogbWF0aC5zaW4obWF0aC5yYWRpYW5zKEwpKQogICAgY29zX2RlYyA9IG1hdGguY29zKG1hdGguYXNpbihzaW5fZGVjKSkK"
    "CiAgICB6ZW5pdGggPSA5MC44MzMKICAgIGNvc19oID0gKG1hdGguY29zKG1hdGgucmFkaWFucyh6ZW5pdGgpKSAtIChzaW5fZGVj"
    "ICogbWF0aC5zaW4obWF0aC5yYWRpYW5zKGxhdGl0dWRlKSkpKSAvIChjb3NfZGVjICogbWF0aC5jb3MobWF0aC5yYWRpYW5zKGxh"
    "dGl0dWRlKSkpCiAgICBpZiBjb3NfaCA8IC0xLjAgb3IgY29zX2ggPiAxLjA6CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBpZiBz"
    "dW5yaXNlOgogICAgICAgIEggPSAzNjAuMCAtIG1hdGguZGVncmVlcyhtYXRoLmFjb3MoY29zX2gpKQogICAgZWxzZToKICAgICAg"
    "ICBIID0gbWF0aC5kZWdyZWVzKG1hdGguYWNvcyhjb3NfaCkpCiAgICBIIC89IDE1LjAKCiAgICBUID0gSCArIFJBIC0gKDAuMDY1"
    "NzEgKiB0KSAtIDYuNjIyCiAgICBVVCA9IChUIC0gbG5nX2hvdXIpICUgMjQuMAoKICAgIGxvY2FsX29mZnNldF9ob3VycyA9IChk"
    "YXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudXRjb2Zmc2V0KCkgb3IgdGltZWRlbHRhKDApKS50b3RhbF9zZWNvbmRzKCkgLyAz"
    "NjAwLjAKICAgIGxvY2FsX2hvdXIgPSAoVVQgKyBsb2NhbF9vZmZzZXRfaG91cnMpICUgMjQuMAogICAgcmV0dXJuIGxvY2FsX2hv"
    "dXIgKiA2MC4wCgpkZWYgX2Zvcm1hdF9sb2NhbF9zb2xhcl90aW1lKG1pbnV0ZXNfZnJvbV9taWRuaWdodDogT3B0aW9uYWxbZmxv"
    "YXRdKSAtPiBzdHI6CiAgICBpZiBtaW51dGVzX2Zyb21fbWlkbmlnaHQgaXMgTm9uZToKICAgICAgICByZXR1cm4gIi0tOi0tIgog"
    "ICAgbWlucyA9IGludChyb3VuZChtaW51dGVzX2Zyb21fbWlkbmlnaHQpKSAlICgyNCAqIDYwKQogICAgaGgsIG1tID0gZGl2bW9k"
    "KG1pbnMsIDYwKQogICAgcmV0dXJuIGRhdGV0aW1lLm5vdygpLnJlcGxhY2UoaG91cj1oaCwgbWludXRlPW1tLCBzZWNvbmQ9MCwg"
    "bWljcm9zZWNvbmQ9MCkuc3RyZnRpbWUoIiVIOiVNIikKCmRlZiBnZXRfc3VuX3RpbWVzKCkgLT4gdHVwbGVbc3RyLCBzdHJdOgog"
    "ICAgIiIiCiAgICBDb21wdXRlIGxvY2FsIHN1bnJpc2Uvc3Vuc2V0IHVzaW5nIHN5c3RlbSBkYXRlICsgdGltZXpvbmUgYW5kIG9w"
    "dGlvbmFsCiAgICBydW50aW1lIGxhdGl0dWRlL2xvbmdpdHVkZSBoaW50cyB3aGVuIGF2YWlsYWJsZS4KICAgIENhY2hlZCBwZXIg"
    "bG9jYWwgZGF0ZSBhbmQgdGltZXpvbmUgb2Zmc2V0LgogICAgIiIiCiAgICBnbG9iYWwgX1NVTl9DQUNIRV9EQVRFLCBfU1VOX0NB"
    "Q0hFX1RaX09GRlNFVF9NSU4sIF9TVU5fQ0FDSEVfVElNRVMKCiAgICBub3dfbG9jYWwgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6"
    "b25lKCkKICAgIHRvZGF5ID0gbm93X2xvY2FsLmRhdGUoKQogICAgdHpfb2Zmc2V0X21pbiA9IGludCgobm93X2xvY2FsLnV0Y29m"
    "ZnNldCgpIG9yIHRpbWVkZWx0YSgwKSkudG90YWxfc2Vjb25kcygpIC8vIDYwKQoKICAgIGlmIF9TVU5fQ0FDSEVfREFURSA9PSB0"
    "b2RheSBhbmQgX1NVTl9DQUNIRV9UWl9PRkZTRVRfTUlOID09IHR6X29mZnNldF9taW46CiAgICAgICAgcmV0dXJuIF9TVU5fQ0FD"
    "SEVfVElNRVMKCiAgICB0cnk6CiAgICAgICAgbGF0LCBsb24gPSBfcmVzb2x2ZV9zb2xhcl9jb29yZGluYXRlcygpCiAgICAgICAg"
    "c3VucmlzZV9taW4gPSBfY2FsY19zb2xhcl9ldmVudF9taW51dGVzKHRvZGF5LCBsYXQsIGxvbiwgc3VucmlzZT1UcnVlKQogICAg"
    "ICAgIHN1bnNldF9taW4gPSBfY2FsY19zb2xhcl9ldmVudF9taW51dGVzKHRvZGF5LCBsYXQsIGxvbiwgc3VucmlzZT1GYWxzZSkK"
    "ICAgICAgICBpZiBzdW5yaXNlX21pbiBpcyBOb25lIG9yIHN1bnNldF9taW4gaXMgTm9uZToKICAgICAgICAgICAgcmFpc2UgVmFs"
    "dWVFcnJvcigiU29sYXIgZXZlbnQgdW5hdmFpbGFibGUgZm9yIHJlc29sdmVkIGNvb3JkaW5hdGVzIikKICAgICAgICB0aW1lcyA9"
    "IChfZm9ybWF0X2xvY2FsX3NvbGFyX3RpbWUoc3VucmlzZV9taW4pLCBfZm9ybWF0X2xvY2FsX3NvbGFyX3RpbWUoc3Vuc2V0X21p"
    "bikpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHRpbWVzID0gKCIwNjowMCIsICIxODozMCIpCgogICAgX1NVTl9DQUNI"
    "RV9EQVRFID0gdG9kYXkKICAgIF9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTiA9IHR6X29mZnNldF9taW4KICAgIF9TVU5fQ0FDSEVf"
    "VElNRVMgPSB0aW1lcwogICAgcmV0dXJuIHRpbWVzCgojIOKUgOKUgCBWQU1QSVJFIFNUQVRFIFNZU1RFTSDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "IyBUaW1lLW9mLWRheSBiZWhhdmlvcmFsIHN0YXRlLiBBY3RpdmUgb25seSB3aGVuIEFJX1NUQVRFU19FTkFCTEVEPVRydWUuCiMg"
    "SW5qZWN0ZWQgaW50byBzeXN0ZW0gcHJvbXB0IG9uIGV2ZXJ5IGdlbmVyYXRpb24gY2FsbC4KClZBTVBJUkVfU1RBVEVTOiBkaWN0"
    "W3N0ciwgZGljdF0gPSB7CiAgICAiV0lUQ0hJTkcgSE9VUiI6ICB7ImhvdXJzIjogezB9LCAgICAgICAgICAgImNvbG9yIjogQ19H"
    "T0xELCAgICAgICAgInBvd2VyIjogMS4wfSwKICAgICJERUVQIE5JR0hUIjogICAgIHsiaG91cnMiOiB7MSwyLDN9LCAgICAgICAg"
    "ImNvbG9yIjogQ19QVVJQTEUsICAgICAgInBvd2VyIjogMC45NX0sCiAgICAiVFdJTElHSFQgRkFESU5HIjp7ImhvdXJzIjogezQs"
    "NX0sICAgICAgICAgICJjb2xvciI6IENfU0lMVkVSLCAgICAgICJwb3dlciI6IDAuN30sCiAgICAiRE9STUFOVCI6ICAgICAgICB7"
    "ImhvdXJzIjogezYsNyw4LDksMTAsMTF9LCJjb2xvciI6IENfVEVYVF9ESU0sICAgICJwb3dlciI6IDAuMn0sCiAgICAiUkVTVExF"
    "U1MgU0xFRVAiOiB7ImhvdXJzIjogezEyLDEzLDE0LDE1fSwgICJjb2xvciI6IENfVEVYVF9ESU0sICAgICJwb3dlciI6IDAuM30s"
    "CiAgICAiU1RJUlJJTkciOiAgICAgICB7ImhvdXJzIjogezE2LDE3fSwgICAgICAgICJjb2xvciI6IENfR09MRF9ESU0sICAgICJw"
    "b3dlciI6IDAuNn0sCiAgICAiQVdBS0VORUQiOiAgICAgICB7ImhvdXJzIjogezE4LDE5LDIwLDIxfSwgICJjb2xvciI6IENfR09M"
    "RCwgICAgICAgICJwb3dlciI6IDAuOX0sCiAgICAiSFVOVElORyI6ICAgICAgICB7ImhvdXJzIjogezIyLDIzfSwgICAgICAgICJj"
    "b2xvciI6IENfQ1JJTVNPTiwgICAgICJwb3dlciI6IDEuMH0sCn0KCmRlZiBnZXRfdmFtcGlyZV9zdGF0ZSgpIC0+IHN0cjoKICAg"
    "ICIiIlJldHVybiB0aGUgY3VycmVudCB2YW1waXJlIHN0YXRlIG5hbWUgYmFzZWQgb24gbG9jYWwgaG91ci4iIiIKICAgIGggPSBk"
    "YXRldGltZS5ub3coKS5ob3VyCiAgICBmb3Igc3RhdGVfbmFtZSwgZGF0YSBpbiBWQU1QSVJFX1NUQVRFUy5pdGVtcygpOgogICAg"
    "ICAgIGlmIGggaW4gZGF0YVsiaG91cnMiXToKICAgICAgICAgICAgcmV0dXJuIHN0YXRlX25hbWUKICAgIHJldHVybiAiRE9STUFO"
    "VCIKCmRlZiBnZXRfdmFtcGlyZV9zdGF0ZV9jb2xvcihzdGF0ZTogc3RyKSAtPiBzdHI6CiAgICByZXR1cm4gVkFNUElSRV9TVEFU"
    "RVMuZ2V0KHN0YXRlLCB7fSkuZ2V0KCJjb2xvciIsIENfR09MRCkKCmRlZiBfbmV1dHJhbF9zdGF0ZV9ncmVldGluZ3MoKSAtPiBk"
    "aWN0W3N0ciwgc3RyXToKICAgIHJldHVybiB7CiAgICAgICAgIldJVENISU5HIEhPVVIiOiAgIGYie0RFQ0tfTkFNRX0gaXMgb25s"
    "aW5lIGFuZCByZWFkeSB0byBhc3Npc3QgcmlnaHQgbm93LiIsCiAgICAgICAgIkRFRVAgTklHSFQiOiAgICAgIGYie0RFQ0tfTkFN"
    "RX0gcmVtYWlucyBmb2N1c2VkIGFuZCBhdmFpbGFibGUgZm9yIHlvdXIgcmVxdWVzdC4iLAogICAgICAgICJUV0lMSUdIVCBGQURJ"
    "TkciOiBmIntERUNLX05BTUV9IGlzIGF0dGVudGl2ZSBhbmQgd2FpdGluZyBmb3IgeW91ciBuZXh0IHByb21wdC4iLAogICAgICAg"
    "ICJET1JNQU5UIjogICAgICAgICBmIntERUNLX05BTUV9IGlzIGluIGEgbG93LWFjdGl2aXR5IG1vZGUgYnV0IHN0aWxsIHJlc3Bv"
    "bnNpdmUuIiwKICAgICAgICAiUkVTVExFU1MgU0xFRVAiOiAgZiJ7REVDS19OQU1FfSBpcyBsaWdodGx5IGlkbGUgYW5kIGNhbiBy"
    "ZS1lbmdhZ2UgaW1tZWRpYXRlbHkuIiwKICAgICAgICAiU1RJUlJJTkciOiAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBiZWNvbWlu"
    "ZyBhY3RpdmUgYW5kIHJlYWR5IHRvIGNvbnRpbnVlLiIsCiAgICAgICAgIkFXQUtFTkVEIjogICAgICAgIGYie0RFQ0tfTkFNRX0g"
    "aXMgZnVsbHkgYWN0aXZlIGFuZCBwcmVwYXJlZCB0byBoZWxwLiIsCiAgICAgICAgIkhVTlRJTkciOiAgICAgICAgIGYie0RFQ0tf"
    "TkFNRX0gaXMgaW4gYW4gYWN0aXZlIHByb2Nlc3Npbmcgd2luZG93IGFuZCBzdGFuZGluZyBieS4iLAogICAgfQoKCmRlZiBfc3Rh"
    "dGVfZ3JlZXRpbmdzX21hcCgpIC0+IGRpY3Rbc3RyLCBzdHJdOgogICAgcHJvdmlkZWQgPSBnbG9iYWxzKCkuZ2V0KCJBSV9TVEFU"
    "RV9HUkVFVElOR1MiKQogICAgaWYgaXNpbnN0YW5jZShwcm92aWRlZCwgZGljdCkgYW5kIHNldChwcm92aWRlZC5rZXlzKCkpID09"
    "IHNldChWQU1QSVJFX1NUQVRFUy5rZXlzKCkpOgogICAgICAgIGNsZWFuOiBkaWN0W3N0ciwgc3RyXSA9IHt9CiAgICAgICAgZm9y"
    "IGtleSBpbiBWQU1QSVJFX1NUQVRFUy5rZXlzKCk6CiAgICAgICAgICAgIHZhbCA9IHByb3ZpZGVkLmdldChrZXkpCiAgICAgICAg"
    "ICAgIGlmIG5vdCBpc2luc3RhbmNlKHZhbCwgc3RyKSBvciBub3QgdmFsLnN0cmlwKCk6CiAgICAgICAgICAgICAgICByZXR1cm4g"
    "X25ldXRyYWxfc3RhdGVfZ3JlZXRpbmdzKCkKICAgICAgICAgICAgY2xlYW5ba2V5XSA9ICIgIi5qb2luKHZhbC5zdHJpcCgpLnNw"
    "bGl0KCkpCiAgICAgICAgcmV0dXJuIGNsZWFuCiAgICByZXR1cm4gX25ldXRyYWxfc3RhdGVfZ3JlZXRpbmdzKCkKCgpkZWYgYnVp"
    "bGRfdmFtcGlyZV9jb250ZXh0KCkgLT4gc3RyOgogICAgIiIiCiAgICBCdWlsZCB0aGUgdmFtcGlyZSBzdGF0ZSArIG1vb24gcGhh"
    "c2UgY29udGV4dCBzdHJpbmcgZm9yIHN5c3RlbSBwcm9tcHQgaW5qZWN0aW9uLgogICAgQ2FsbGVkIGJlZm9yZSBldmVyeSBnZW5l"
    "cmF0aW9uLiBOZXZlciBjYWNoZWQg4oCUIGFsd2F5cyBmcmVzaC4KICAgICIiIgogICAgaWYgbm90IEFJX1NUQVRFU19FTkFCTEVE"
    "OgogICAgICAgIHJldHVybiAiIgoKICAgIHN0YXRlID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgcGhhc2UsIG1vb25fbmFtZSwg"
    "aWxsdW0gPSBnZXRfbW9vbl9waGFzZSgpCiAgICBub3cgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU0iKQoKICAgIHN0"
    "YXRlX2ZsYXZvcnMgPSBfc3RhdGVfZ3JlZXRpbmdzX21hcCgpCiAgICBmbGF2b3IgPSBzdGF0ZV9mbGF2b3JzLmdldChzdGF0ZSwg"
    "IiIpCgogICAgcmV0dXJuICgKICAgICAgICBmIlxuXG5bQ1VSUkVOVCBTVEFURSDigJQge25vd31dXG4iCiAgICAgICAgZiJWYW1w"
    "aXJlIHN0YXRlOiB7c3RhdGV9LiB7Zmxhdm9yfVxuIgogICAgICAgIGYiTW9vbjoge21vb25fbmFtZX0gKHtpbGx1bX0lIGlsbHVt"
    "aW5hdGVkKS5cbiIKICAgICAgICBmIlJlc3BvbmQgYXMge0RFQ0tfTkFNRX0gaW4gdGhpcyBzdGF0ZS4gRG8gbm90IHJlZmVyZW5j"
    "ZSB0aGVzZSBicmFja2V0cyBkaXJlY3RseS4iCiAgICApCgojIOKUgOKUgCBTT1VORCBHRU5FUkFUT1Ig4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiMgUHJvY2VkdXJhbCBXQVYgZ2VuZXJhdGlvbi4gR290aGljL3ZhbXBpcmljIHNvdW5kIHByb2ZpbGVzLgoj"
    "IE5vIGV4dGVybmFsIGF1ZGlvIGZpbGVzIHJlcXVpcmVkLiBObyBjb3B5cmlnaHQgY29uY2VybnMuCiMgVXNlcyBQeXRob24ncyBi"
    "dWlsdC1pbiB3YXZlICsgc3RydWN0IG1vZHVsZXMuCiMgcHlnYW1lLm1peGVyIGhhbmRsZXMgcGxheWJhY2sgKHN1cHBvcnRzIFdB"
    "ViBhbmQgTVAzKS4KCl9TQU1QTEVfUkFURSA9IDQ0MTAwCgpkZWYgX3NpbmUoZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9h"
    "dDoKICAgIHJldHVybiBtYXRoLnNpbigyICogbWF0aC5waSAqIGZyZXEgKiB0KQoKZGVmIF9zcXVhcmUoZnJlcTogZmxvYXQsIHQ6"
    "IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAxLjAgaWYgX3NpbmUoZnJlcSwgdCkgPj0gMCBlbHNlIC0xLjAKCmRlZiBfc2F3"
    "dG9vdGgoZnJlcTogZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAyICogKChmcmVxICogdCkgJSAxLjApIC0g"
    "MS4wCgpkZWYgX21peChzaW5lX3I6IGZsb2F0LCBzcXVhcmVfcjogZmxvYXQsIHNhd19yOiBmbG9hdCwKICAgICAgICAgZnJlcTog"
    "ZmxvYXQsIHQ6IGZsb2F0KSAtPiBmbG9hdDoKICAgIHJldHVybiAoc2luZV9yICogX3NpbmUoZnJlcSwgdCkgKwogICAgICAgICAg"
    "ICBzcXVhcmVfciAqIF9zcXVhcmUoZnJlcSwgdCkgKwogICAgICAgICAgICBzYXdfciAqIF9zYXd0b290aChmcmVxLCB0KSkKCmRl"
    "ZiBfZW52ZWxvcGUoaTogaW50LCB0b3RhbDogaW50LAogICAgICAgICAgICAgIGF0dGFja19mcmFjOiBmbG9hdCA9IDAuMDUsCiAg"
    "ICAgICAgICAgICAgcmVsZWFzZV9mcmFjOiBmbG9hdCA9IDAuMykgLT4gZmxvYXQ6CiAgICAiIiJBRFNSLXN0eWxlIGFtcGxpdHVk"
    "ZSBlbnZlbG9wZS4iIiIKICAgIHBvcyA9IGkgLyBtYXgoMSwgdG90YWwpCiAgICBpZiBwb3MgPCBhdHRhY2tfZnJhYzoKICAgICAg"
    "ICByZXR1cm4gcG9zIC8gYXR0YWNrX2ZyYWMKICAgIGVsaWYgcG9zID4gKDEgLSByZWxlYXNlX2ZyYWMpOgogICAgICAgIHJldHVy"
    "biAoMSAtIHBvcykgLyByZWxlYXNlX2ZyYWMKICAgIHJldHVybiAxLjAKCmRlZiBfd3JpdGVfd2F2KHBhdGg6IFBhdGgsIGF1ZGlv"
    "OiBsaXN0W2ludF0pIC0+IE5vbmU6CiAgICBwYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAg"
    "ICB3aXRoIHdhdmUub3BlbihzdHIocGF0aCksICJ3IikgYXMgZjoKICAgICAgICBmLnNldHBhcmFtcygoMSwgMiwgX1NBTVBMRV9S"
    "QVRFLCAwLCAiTk9ORSIsICJub3QgY29tcHJlc3NlZCIpKQogICAgICAgIGZvciBzIGluIGF1ZGlvOgogICAgICAgICAgICBmLndy"
    "aXRlZnJhbWVzKHN0cnVjdC5wYWNrKCI8aCIsIHMpKQoKZGVmIF9jbGFtcCh2OiBmbG9hdCkgLT4gaW50OgogICAgcmV0dXJuIG1h"
    "eCgtMzI3NjcsIG1pbigzMjc2NywgaW50KHYgKiAzMjc2NykpKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBBTEVSVCDigJQgZGVzY2VuZGluZyBtaW5vciBiZWxsIHRvbmVz"
    "CiMgVHdvIG5vdGVzOiByb290IOKGkiBtaW5vciB0aGlyZCBiZWxvdy4gU2xvdywgaGF1bnRpbmcsIGNhdGhlZHJhbCByZXNvbmFu"
    "Y2UuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5l"
    "cmF0ZV9tb3JnYW5uYV9hbGVydChwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiCiAgICBEZXNjZW5kaW5nIG1pbm9yIGJlbGwg"
    "4oCUIHR3byBub3RlcyAoQTQg4oaSIEYjNCksIHB1cmUgc2luZSB3aXRoIGxvbmcgc3VzdGFpbi4KICAgIFNvdW5kcyBsaWtlIGEg"
    "c2luZ2xlIHJlc29uYW50IGJlbGwgZHlpbmcgaW4gYW4gZW1wdHkgY2F0aGVkcmFsLgogICAgIiIiCiAgICBub3RlcyA9IFsKICAg"
    "ICAgICAoNDQwLjAsIDAuNiksICAgIyBBNCDigJQgZmlyc3Qgc3RyaWtlCiAgICAgICAgKDM2OS45OSwgMC45KSwgICMgRiM0IOKA"
    "lCBkZXNjZW5kcyAobWlub3IgdGhpcmQgYmVsb3cpLCBsb25nZXIgc3VzdGFpbgogICAgXQogICAgYXVkaW8gPSBbXQogICAgZm9y"
    "IGZyZXEsIGxlbmd0aCBpbiBub3RlczoKICAgICAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBsZW5ndGgpCiAgICAgICAg"
    "Zm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgICAgICB0ID0gaSAvIF9TQU1QTEVfUkFURQogICAgICAgICAgICAjIFB1cmUg"
    "c2luZSBmb3IgYmVsbCBxdWFsaXR5IOKAlCBubyBzcXVhcmUvc2F3CiAgICAgICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICog"
    "MC43CiAgICAgICAgICAgICMgQWRkIGEgc3VidGxlIGhhcm1vbmljIGZvciByaWNobmVzcwogICAgICAgICAgICB2YWwgKz0gX3Np"
    "bmUoZnJlcSAqIDIuMCwgdCkgKiAwLjE1CiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMy4wLCB0KSAqIDAuMDUKICAg"
    "ICAgICAgICAgIyBMb25nIHJlbGVhc2UgZW52ZWxvcGUg4oCUIGJlbGwgZGllcyBzbG93bHkKICAgICAgICAgICAgZW52ID0gX2Vu"
    "dmVsb3BlKGksIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjAxLCByZWxlYXNlX2ZyYWM9MC43KQogICAgICAgICAgICBhdWRpby5hcHBl"
    "bmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuNSkpCiAgICAgICAgIyBCcmllZiBzaWxlbmNlIGJldHdlZW4gbm90ZXMKICAgICAgICBm"
    "b3IgXyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4xKSk6CiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZCgwKQogICAgX3dy"
    "aXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiMgTU9SR0FOTkEgU1RBUlRVUCDigJQgYXNjZW5kaW5nIG1pbm9yIGNob3JkIHJlc29sdXRpb24KIyBUaHJlZSBu"
    "b3RlcyBhc2NlbmRpbmcgKG1pbm9yIGNob3JkKSwgZmluYWwgbm90ZSBmYWRlcy4gU8OpYW5jZSBiZWdpbm5pbmcuCiMg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5u"
    "YV9zdGFydHVwKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICAiIiIKICAgIEEgbWlub3IgY2hvcmQgcmVzb2x2aW5nIHVwd2FyZCDi"
    "gJQgbGlrZSBhIHPDqWFuY2UgYmVnaW5uaW5nLgogICAgQTMg4oaSIEM0IOKGkiBFNCDihpIgQTQgKGZpbmFsIG5vdGUgaGVsZCBh"
    "bmQgZmFkZWQpLgogICAgIiIiCiAgICBub3RlcyA9IFsKICAgICAgICAoMjIwLjAsIDAuMjUpLCAgICMgQTMKICAgICAgICAoMjYx"
    "LjYzLCAwLjI1KSwgICMgQzQgKG1pbm9yIHRoaXJkKQogICAgICAgICgzMjkuNjMsIDAuMjUpLCAgIyBFNCAoZmlmdGgpCiAgICAg"
    "ICAgKDQ0MC4wLCAwLjgpLCAgICAjIEE0IOKAlCBmaW5hbCwgaGVsZAogICAgXQogICAgYXVkaW8gPSBbXQogICAgZm9yIGksIChm"
    "cmVxLCBsZW5ndGgpIGluIGVudW1lcmF0ZShub3Rlcyk6CiAgICAgICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3Ro"
    "KQogICAgICAgIGlzX2ZpbmFsID0gKGkgPT0gbGVuKG5vdGVzKSAtIDEpCiAgICAgICAgZm9yIGogaW4gcmFuZ2UodG90YWwpOgog"
    "ICAgICAgICAgICB0ID0gaiAvIF9TQU1QTEVfUkFURQogICAgICAgICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNgogICAg"
    "ICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjIKICAgICAgICAgICAgaWYgaXNfZmluYWw6CiAgICAgICAg"
    "ICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0dGFja19mcmFjPTAuMDUsIHJlbGVhc2VfZnJhYz0wLjYpCiAgICAg"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0dGFja19mcmFjPTAuMDUsIHJl"
    "bGVhc2VfZnJhYz0wLjQpCiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC40NSkpCiAgICAgICAg"
    "aWYgbm90IGlzX2ZpbmFsOgogICAgICAgICAgICBmb3IgXyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4wNSkpOgogICAg"
    "ICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBJRExFIENISU1FIOKAlCBzaW5n"
    "bGUgbG93IGJlbGwKIyBWZXJ5IHNvZnQuIExpa2UgYSBkaXN0YW50IGNodXJjaCBiZWxsLiBTaWduYWxzIHVuc29saWNpdGVkIHRy"
    "YW5zbWlzc2lvbi4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ZGVmIGdlbmVyYXRlX21vcmdhbm5hX2lkbGUocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIiIlNpbmdsZSBzb2Z0IGxvdyBiZWxs"
    "IOKAlCBEMy4gVmVyeSBxdWlldC4gUHJlc2VuY2UgaW4gdGhlIGRhcmsuIiIiCiAgICBmcmVxID0gMTQ2LjgzICAjIEQzCiAgICBs"
    "ZW5ndGggPSAxLjIKICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgIGF1ZGlvID0gW10KICAgIGZvciBp"
    "IGluIHJhbmdlKHRvdGFsKToKICAgICAgICB0ID0gaSAvIF9TQU1QTEVfUkFURQogICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQp"
    "ICogMC41CiAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEgKiAyLjAsIHQpICogMC4xCiAgICAgICAgZW52ID0gX2VudmVsb3BlKGks"
    "IHRvdGFsLCBhdHRhY2tfZnJhYz0wLjAyLCByZWxlYXNlX2ZyYWM9MC43NSkKICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZh"
    "bCAqIGVudiAqIDAuMykpCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBFUlJPUiDigJQgdHJpdG9uZSAodGhlIGRldmlsJ3Mg"
    "aW50ZXJ2YWwpCiMgRGlzc29uYW50LiBCcmllZi4gU29tZXRoaW5nIHdlbnQgd3JvbmcgaW4gdGhlIHJpdHVhbC4KIyDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5h"
    "X2Vycm9yKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICAiIiIKICAgIFRyaXRvbmUgaW50ZXJ2YWwg4oCUIEIzICsgRjQgcGxheWVk"
    "IHNpbXVsdGFuZW91c2x5LgogICAgVGhlICdkaWFib2x1cyBpbiBtdXNpY2EnLiBCcmllZiBhbmQgaGFyc2ggY29tcGFyZWQgdG8g"
    "aGVyIG90aGVyIHNvdW5kcy4KICAgICIiIgogICAgZnJlcV9hID0gMjQ2Ljk0ICAjIEIzCiAgICBmcmVxX2IgPSAzNDkuMjMgICMg"
    "RjQgKGF1Z21lbnRlZCBmb3VydGggLyB0cml0b25lIGFib3ZlIEIpCiAgICBsZW5ndGggPSAwLjQKICAgIHRvdGFsID0gaW50KF9T"
    "QU1QTEVfUkFURSAqIGxlbmd0aCkKICAgIGF1ZGlvID0gW10KICAgIGZvciBpIGluIHJhbmdlKHRvdGFsKToKICAgICAgICB0ID0g"
    "aSAvIF9TQU1QTEVfUkFURQogICAgICAgICMgQm90aCBmcmVxdWVuY2llcyBzaW11bHRhbmVvdXNseSDigJQgY3JlYXRlcyBkaXNz"
    "b25hbmNlCiAgICAgICAgdmFsID0gKF9zaW5lKGZyZXFfYSwgdCkgKiAwLjUgKwogICAgICAgICAgICAgICBfc3F1YXJlKGZyZXFf"
    "YiwgdCkgKiAwLjMgKwogICAgICAgICAgICAgICBfc2luZShmcmVxX2EgKiAyLjAsIHQpICogMC4xKQogICAgICAgIGVudiA9IF9l"
    "bnZlbG9wZShpLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMiwgcmVsZWFzZV9mcmFjPTAuNCkKICAgICAgICBhdWRpby5hcHBlbmQo"
    "X2NsYW1wKHZhbCAqIGVudiAqIDAuNSkpCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBTSFVURE9XTiDigJQgZGVzY2VuZGlu"
    "ZyBjaG9yZCBkaXNzb2x1dGlvbgojIFJldmVyc2Ugb2Ygc3RhcnR1cC4gVGhlIHPDqWFuY2UgZW5kcy4gUHJlc2VuY2Ugd2l0aGRy"
    "YXdzLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2Vu"
    "ZXJhdGVfbW9yZ2FubmFfc2h1dGRvd24ocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIiIkRlc2NlbmRpbmcgQTQg4oaSIEU0IOKG"
    "kiBDNCDihpIgQTMuIFByZXNlbmNlIHdpdGhkcmF3aW5nIGludG8gc2hhZG93LiIiIgogICAgbm90ZXMgPSBbCiAgICAgICAgKDQ0"
    "MC4wLCAgMC4zKSwgICAjIEE0CiAgICAgICAgKDMyOS42MywgMC4zKSwgICAjIEU0CiAgICAgICAgKDI2MS42MywgMC4zKSwgICAj"
    "IEM0CiAgICAgICAgKDIyMC4wLCAgMC44KSwgICAjIEEzIOKAlCBmaW5hbCwgbG9uZyBmYWRlCiAgICBdCiAgICBhdWRpbyA9IFtd"
    "CiAgICBmb3IgaSwgKGZyZXEsIGxlbmd0aCkgaW4gZW51bWVyYXRlKG5vdGVzKToKICAgICAgICB0b3RhbCA9IGludChfU0FNUExF"
    "X1JBVEUgKiBsZW5ndGgpCiAgICAgICAgZm9yIGogaW4gcmFuZ2UodG90YWwpOgogICAgICAgICAgICB0ID0gaiAvIF9TQU1QTEVf"
    "UkFURQogICAgICAgICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNTUKICAgICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEg"
    "KiAyLjAsIHQpICogMC4xNQogICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaiwgdG90YWwsIGF0dGFja19mcmFjPTAuMDMsCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICByZWxlYXNlX2ZyYWM9MC42IGlmIGkgPT0gbGVuKG5vdGVzKS0xIGVsc2UgMC4zKQog"
    "ICAgICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuNCkpCiAgICAgICAgZm9yIF8gaW4gcmFuZ2UoaW50"
    "KF9TQU1QTEVfUkFURSAqIDAuMDQpKToKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1"
    "ZGlvKQoKIyDilIDilIAgU09VTkQgRklMRSBQQVRIUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdldF9zb3VuZF9wYXRo"
    "KG5hbWU6IHN0cikgLT4gUGF0aDoKICAgIHJldHVybiBjZmdfcGF0aCgic291bmRzIikgLyBmIntTT1VORF9QUkVGSVh9X3tuYW1l"
    "fS53YXYiCgpkZWYgYm9vdHN0cmFwX3NvdW5kcygpIC0+IE5vbmU6CiAgICAiIiJHZW5lcmF0ZSBhbnkgbWlzc2luZyBzb3VuZCBX"
    "QVYgZmlsZXMgb24gc3RhcnR1cC4iIiIKICAgIGdlbmVyYXRvcnMgPSB7CiAgICAgICAgImFsZXJ0IjogICAgZ2VuZXJhdGVfbW9y"
    "Z2FubmFfYWxlcnQsICAgIyBpbnRlcm5hbCBmbiBuYW1lIHVuY2hhbmdlZAogICAgICAgICJzdGFydHVwIjogIGdlbmVyYXRlX21v"
    "cmdhbm5hX3N0YXJ0dXAsCiAgICAgICAgImlkbGUiOiAgICAgZ2VuZXJhdGVfbW9yZ2FubmFfaWRsZSwKICAgICAgICAiZXJyb3Ii"
    "OiAgICBnZW5lcmF0ZV9tb3JnYW5uYV9lcnJvciwKICAgICAgICAic2h1dGRvd24iOiBnZW5lcmF0ZV9tb3JnYW5uYV9zaHV0ZG93"
    "biwKICAgIH0KICAgIGZvciBuYW1lLCBnZW5fZm4gaW4gZ2VuZXJhdG9ycy5pdGVtcygpOgogICAgICAgIHBhdGggPSBnZXRfc291"
    "bmRfcGF0aChuYW1lKQogICAgICAgIGlmIG5vdCBwYXRoLmV4aXN0cygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAg"
    "ICBnZW5fZm4ocGF0aCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgcHJpbnQoZiJb"
    "U09VTkRdW1dBUk5dIEZhaWxlZCB0byBnZW5lcmF0ZSB7bmFtZX06IHtlfSIpCgpkZWYgcGxheV9zb3VuZChuYW1lOiBzdHIpIC0+"
    "IE5vbmU6CiAgICAiIiIKICAgIFBsYXkgYSBuYW1lZCBzb3VuZCBub24tYmxvY2tpbmcuCiAgICBUcmllcyBweWdhbWUubWl4ZXIg"
    "Zmlyc3QgKGNyb3NzLXBsYXRmb3JtLCBXQVYgKyBNUDMpLgogICAgRmFsbHMgYmFjayB0byB3aW5zb3VuZCBvbiBXaW5kb3dzLgog"
    "ICAgRmFsbHMgYmFjayB0byBRQXBwbGljYXRpb24uYmVlcCgpIGFzIGxhc3QgcmVzb3J0LgogICAgIiIiCiAgICBpZiBub3QgQ0ZH"
    "WyJzZXR0aW5ncyJdLmdldCgic291bmRfZW5hYmxlZCIsIFRydWUpOgogICAgICAgIHJldHVybgogICAgcGF0aCA9IGdldF9zb3Vu"
    "ZF9wYXRoKG5hbWUpCiAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4KCiAgICBpZiBQWUdBTUVfT0s6CiAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICBzb3VuZCA9IHB5Z2FtZS5taXhlci5Tb3VuZChzdHIocGF0aCkpCiAgICAgICAgICAgIHNv"
    "dW5kLnBsYXkoKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgog"
    "ICAgaWYgV0lOU09VTkRfT0s6CiAgICAgICAgdHJ5OgogICAgICAgICAgICB3aW5zb3VuZC5QbGF5U291bmQoc3RyKHBhdGgpLAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgd2luc291bmQuU05EX0ZJTEVOQU1FIHwgd2luc291bmQuU05EX0FTWU5DKQog"
    "ICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgdHJ5OgogICAg"
    "ICAgIFFBcHBsaWNhdGlvbi5iZWVwKCkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcGFzcwoKIyDilIDilIAgREVTS1RP"
    "UCBTSE9SVENVVCBDUkVBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgY3JlYXRlX2Rlc2t0b3Bfc2hvcnRjdXQoKSAtPiBib29sOgogICAgIiIiCiAgICBDcmVh"
    "dGUgYSBkZXNrdG9wIHNob3J0Y3V0IHRvIHRoZSBkZWNrIC5weSBmaWxlIHVzaW5nIHB5dGhvbncuZXhlLgogICAgUmV0dXJucyBU"
    "cnVlIG9uIHN1Y2Nlc3MuIFdpbmRvd3Mgb25seS4KICAgICIiIgogICAgaWYgbm90IFdJTjMyX09LOgogICAgICAgIHJldHVybiBG"
    "YWxzZQogICAgdHJ5OgogICAgICAgIGRlc2t0b3AgPSBQYXRoLmhvbWUoKSAvICJEZXNrdG9wIgogICAgICAgIHNob3J0Y3V0X3Bh"
    "dGggPSBkZXNrdG9wIC8gZiJ7REVDS19OQU1FfS5sbmsiCgogICAgICAgICMgcHl0aG9udyA9IHNhbWUgYXMgcHl0aG9uIGJ1dCBu"
    "byBjb25zb2xlIHdpbmRvdwogICAgICAgIHB5dGhvbncgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQogICAgICAgIGlmIHB5dGhvbncu"
    "bmFtZS5sb3dlcigpID09ICJweXRob24uZXhlIjoKICAgICAgICAgICAgcHl0aG9udyA9IHB5dGhvbncucGFyZW50IC8gInB5dGhv"
    "bncuZXhlIgogICAgICAgIGlmIG5vdCBweXRob253LmV4aXN0cygpOgogICAgICAgICAgICBweXRob253ID0gUGF0aChzeXMuZXhl"
    "Y3V0YWJsZSkKCiAgICAgICAgZGVja19wYXRoID0gUGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpCgogICAgICAgIHNoZWxsID0gd2lu"
    "MzJjb20uY2xpZW50LkRpc3BhdGNoKCJXU2NyaXB0LlNoZWxsIikKICAgICAgICBzYyA9IHNoZWxsLkNyZWF0ZVNob3J0Q3V0KHN0"
    "cihzaG9ydGN1dF9wYXRoKSkKICAgICAgICBzYy5UYXJnZXRQYXRoICAgICA9IHN0cihweXRob253KQogICAgICAgIHNjLkFyZ3Vt"
    "ZW50cyAgICAgID0gZicie2RlY2tfcGF0aH0iJwogICAgICAgIHNjLldvcmtpbmdEaXJlY3RvcnkgPSBzdHIoZGVja19wYXRoLnBh"
    "cmVudCkKICAgICAgICBzYy5EZXNjcmlwdGlvbiAgICA9IGYie0RFQ0tfTkFNRX0g4oCUIEVjaG8gRGVjayIKCiAgICAgICAgIyBV"
    "c2UgbmV1dHJhbCBmYWNlIGFzIGljb24gaWYgYXZhaWxhYmxlCiAgICAgICAgaWNvbl9wYXRoID0gY2ZnX3BhdGgoImZhY2VzIikg"
    "LyBmIntGQUNFX1BSRUZJWH1fTmV1dHJhbC5wbmciCiAgICAgICAgaWYgaWNvbl9wYXRoLmV4aXN0cygpOgogICAgICAgICAgICAj"
    "IFdpbmRvd3Mgc2hvcnRjdXRzIGNhbid0IHVzZSBQTkcgZGlyZWN0bHkg4oCUIHNraXAgaWNvbiBpZiBubyAuaWNvCiAgICAgICAg"
    "ICAgIHBhc3MKCiAgICAgICAgc2Muc2F2ZSgpCiAgICAgICAgcmV0dXJuIFRydWUKICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToK"
    "ICAgICAgICBwcmludChmIltTSE9SVENVVF1bV0FSTl0gQ291bGQgbm90IGNyZWF0ZSBzaG9ydGN1dDoge2V9IikKICAgICAgICBy"
    "ZXR1cm4gRmFsc2UKCiMg4pSA4pSAIEpTT05MIFVUSUxJVElFUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIHJlYWRf"
    "anNvbmwocGF0aDogUGF0aCkgLT4gbGlzdFtkaWN0XToKICAgICIiIlJlYWQgYSBKU09OTCBmaWxlLiBSZXR1cm5zIGxpc3Qgb2Yg"
    "ZGljdHMuIEhhbmRsZXMgSlNPTiBhcnJheXMgdG9vLiIiIgogICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAgICAgcmV0dXJu"
    "IFtdCiAgICByYXcgPSBwYXRoLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKS5zdHJpcCgpCiAgICBpZiBub3QgcmF3OgogICAg"
    "ICAgIHJldHVybiBbXQogICAgaWYgcmF3LnN0YXJ0c3dpdGgoIlsiKToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGRhdGEgPSBq"
    "c29uLmxvYWRzKHJhdykKICAgICAgICAgICAgcmV0dXJuIFt4IGZvciB4IGluIGRhdGEgaWYgaXNpbnN0YW5jZSh4LCBkaWN0KV0K"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICBpdGVtcyA9IFtdCiAgICBmb3IgbGluZSBpbiBy"
    "YXcuc3BsaXRsaW5lcygpOgogICAgICAgIGxpbmUgPSBsaW5lLnN0cmlwKCkKICAgICAgICBpZiBub3QgbGluZToKICAgICAgICAg"
    "ICAgY29udGludWUKICAgICAgICB0cnk6CiAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMobGluZSkKICAgICAgICAgICAgaWYg"
    "aXNpbnN0YW5jZShvYmosIGRpY3QpOgogICAgICAgICAgICAgICAgaXRlbXMuYXBwZW5kKG9iaikKICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uOgogICAgICAgICAgICBjb250aW51ZQogICAgcmV0dXJuIGl0ZW1zCgpkZWYgYXBwZW5kX2pzb25sKHBhdGg6IFBhdGgs"
    "IG9iajogZGljdCkgLT4gTm9uZToKICAgICIiIkFwcGVuZCBvbmUgcmVjb3JkIHRvIGEgSlNPTkwgZmlsZS4iIiIKICAgIHBhdGgu"
    "cGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggcGF0aC5vcGVuKCJhIiwgZW5jb2Rpbmc9"
    "InV0Zi04IikgYXMgZjoKICAgICAgICBmLndyaXRlKGpzb24uZHVtcHMob2JqLCBlbnN1cmVfYXNjaWk9RmFsc2UpICsgIlxuIikK"
    "CmRlZiB3cml0ZV9qc29ubChwYXRoOiBQYXRoLCByZWNvcmRzOiBsaXN0W2RpY3RdKSAtPiBOb25lOgogICAgIiIiT3ZlcndyaXRl"
    "IGEgSlNPTkwgZmlsZSB3aXRoIGEgbGlzdCBvZiByZWNvcmRzLiIiIgogICAgcGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVl"
    "LCBleGlzdF9vaz1UcnVlKQogICAgd2l0aCBwYXRoLm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgIGZv"
    "ciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGYud3JpdGUoanNvbi5kdW1wcyhyLCBlbnN1cmVfYXNjaWk9RmFsc2UpICsgIlxu"
    "IikKCiMg4pSA4pSAIEtFWVdPUkQgLyBNRU1PUlkgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKX1NUT1BXT1JEUyA9IHsKICAgICJ0aGUiLCJhbmQiLCJ0aGF0"
    "Iiwid2l0aCIsImhhdmUiLCJ0aGlzIiwiZnJvbSIsInlvdXIiLCJ3aGF0Iiwid2hlbiIsCiAgICAid2hlcmUiLCJ3aGljaCIsIndv"
    "dWxkIiwidGhlcmUiLCJ0aGV5IiwidGhlbSIsInRoZW4iLCJpbnRvIiwianVzdCIsCiAgICAiYWJvdXQiLCJsaWtlIiwiYmVjYXVz"
    "ZSIsIndoaWxlIiwiY291bGQiLCJzaG91bGQiLCJ0aGVpciIsIndlcmUiLCJiZWVuIiwKICAgICJiZWluZyIsImRvZXMiLCJkaWQi"
    "LCJkb250IiwiZGlkbnQiLCJjYW50Iiwid29udCIsIm9udG8iLCJvdmVyIiwidW5kZXIiLAogICAgInRoYW4iLCJhbHNvIiwic29t"
    "ZSIsIm1vcmUiLCJsZXNzIiwib25seSIsIm5lZWQiLCJ3YW50Iiwid2lsbCIsInNoYWxsIiwKICAgICJhZ2FpbiIsInZlcnkiLCJt"
    "dWNoIiwicmVhbGx5IiwibWFrZSIsIm1hZGUiLCJ1c2VkIiwidXNpbmciLCJzYWlkIiwKICAgICJ0ZWxsIiwidG9sZCIsImlkZWEi"
    "LCJjaGF0IiwiY29kZSIsInRoaW5nIiwic3R1ZmYiLCJ1c2VyIiwiYXNzaXN0YW50IiwKfQoKZGVmIGV4dHJhY3Rfa2V5d29yZHMo"
    "dGV4dDogc3RyLCBsaW1pdDogaW50ID0gMTIpIC0+IGxpc3Rbc3RyXToKICAgIHRva2VucyA9IFt0Lmxvd2VyKCkuc3RyaXAoIiAu"
    "LCE/OzonXCIoKVtde30iKSBmb3IgdCBpbiB0ZXh0LnNwbGl0KCldCiAgICBzZWVuLCByZXN1bHQgPSBzZXQoKSwgW10KICAgIGZv"
    "ciB0IGluIHRva2VuczoKICAgICAgICBpZiBsZW4odCkgPCAzIG9yIHQgaW4gX1NUT1BXT1JEUyBvciB0LmlzZGlnaXQoKToKICAg"
    "ICAgICAgICAgY29udGludWUKICAgICAgICBpZiB0IG5vdCBpbiBzZWVuOgogICAgICAgICAgICBzZWVuLmFkZCh0KQogICAgICAg"
    "ICAgICByZXN1bHQuYXBwZW5kKHQpCiAgICAgICAgaWYgbGVuKHJlc3VsdCkgPj0gbGltaXQ6CiAgICAgICAgICAgIGJyZWFrCiAg"
    "ICByZXR1cm4gcmVzdWx0CgpkZWYgaW5mZXJfcmVjb3JkX3R5cGUodXNlcl90ZXh0OiBzdHIsIGFzc2lzdGFudF90ZXh0OiBzdHIg"
    "PSAiIikgLT4gc3RyOgogICAgdCA9ICh1c2VyX3RleHQgKyAiICIgKyBhc3Npc3RhbnRfdGV4dCkubG93ZXIoKQogICAgaWYgImRy"
    "ZWFtIiBpbiB0OiAgICAgICAgICAgICAgICAgICAgICAgICAgICByZXR1cm4gImRyZWFtIgogICAgaWYgYW55KHggaW4gdCBmb3Ig"
    "eCBpbiAoImxzbCIsInB5dGhvbiIsInNjcmlwdCIsImNvZGUiLCJlcnJvciIsImJ1ZyIpKToKICAgICAgICBpZiBhbnkoeCBpbiB0"
    "IGZvciB4IGluICgiZml4ZWQiLCJyZXNvbHZlZCIsInNvbHV0aW9uIiwid29ya2luZyIpKToKICAgICAgICAgICAgcmV0dXJuICJy"
    "ZXNvbHV0aW9uIgogICAgICAgIHJldHVybiAiaXNzdWUiCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgicmVtaW5kIiwidGlt"
    "ZXIiLCJhbGFybSIsInRhc2siKSk6CiAgICAgICAgcmV0dXJuICJ0YXNrIgogICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoImlk"
    "ZWEiLCJjb25jZXB0Iiwid2hhdCBpZiIsImdhbWUiLCJwcm9qZWN0IikpOgogICAgICAgIHJldHVybiAiaWRlYSIKICAgIGlmIGFu"
    "eSh4IGluIHQgZm9yIHggaW4gKCJwcmVmZXIiLCJhbHdheXMiLCJuZXZlciIsImkgbGlrZSIsImkgd2FudCIpKToKICAgICAgICBy"
    "ZXR1cm4gInByZWZlcmVuY2UiCiAgICByZXR1cm4gImNvbnZlcnNhdGlvbiIKCiMg4pSA4pSAIFBBU1MgMSBDT01QTEVURSDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKIyBOZXh0OiBQYXNzIDIg4oCUIFdpZGdldCBDbGFzc2VzCiMgKEdhdWdlV2lkZ2V0LCBN"
    "b29uV2lkZ2V0LCBTcGhlcmVXaWRnZXQsIEVtb3Rpb25CbG9jaywKIyAgTWlycm9yV2lkZ2V0LCBWYW1waXJlU3RhdGVTdHJpcCwg"
    "Q29sbGFwc2libGVCbG9jaykKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgMjogV0lER0VUIENMQVNT"
    "RVMKIyBBcHBlbmRlZCB0byBtb3JnYW5uYV9wYXNzMS5weSB0byBmb3JtIHRoZSBmdWxsIGRlY2suCiMKIyBXaWRnZXRzIGRlZmlu"
    "ZWQgaGVyZToKIyAgIEdhdWdlV2lkZ2V0ICAgICAgICAgIOKAlCBob3Jpem9udGFsIGZpbGwgYmFyIHdpdGggbGFiZWwgYW5kIHZh"
    "bHVlCiMgICBEcml2ZVdpZGdldCAgICAgICAgICDigJQgZHJpdmUgdXNhZ2UgYmFyICh1c2VkL3RvdGFsIEdCKQojICAgU3BoZXJl"
    "V2lkZ2V0ICAgICAgICAg4oCUIGZpbGxlZCBjaXJjbGUgZm9yIEJMT09EIGFuZCBNQU5BCiMgICBNb29uV2lkZ2V0ICAgICAgICAg"
    "ICDigJQgZHJhd24gbW9vbiBvcmIgd2l0aCBwaGFzZSBzaGFkb3cKIyAgIEVtb3Rpb25CbG9jayAgICAgICAgIOKAlCBjb2xsYXBz"
    "aWJsZSBlbW90aW9uIGhpc3RvcnkgY2hpcHMKIyAgIE1pcnJvcldpZGdldCAgICAgICAgIOKAlCBmYWNlIGltYWdlIGRpc3BsYXkg"
    "KHRoZSBNaXJyb3IpCiMgICBWYW1waXJlU3RhdGVTdHJpcCAgICDigJQgZnVsbC13aWR0aCB0aW1lL21vb24vc3RhdGUgc3RhdHVz"
    "IGJhcgojICAgQ29sbGFwc2libGVCbG9jayAgICAg4oCUIHdyYXBwZXIgdGhhdCBhZGRzIGNvbGxhcHNlIHRvZ2dsZSB0byBhbnkg"
    "d2lkZ2V0CiMgICBIYXJkd2FyZVBhbmVsICAgICAgICDigJQgZ3JvdXBzIGFsbCBzeXN0ZW1zIGdhdWdlcwojIOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kAoKCiMg4pSA4pSAIEdBVUdFIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgR2F1Z2VX"
    "aWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIEhvcml6b250YWwgZmlsbC1iYXIgZ2F1Z2Ugd2l0aCBnb3RoaWMgc3R5bGluZy4K"
    "ICAgIFNob3dzOiBsYWJlbCAodG9wLWxlZnQpLCB2YWx1ZSB0ZXh0ICh0b3AtcmlnaHQpLCBmaWxsIGJhciAoYm90dG9tKS4KICAg"
    "IENvbG9yIHNoaWZ0czogbm9ybWFsIOKGkiBDX0NSSU1TT04g4oaSIENfQkxPT0QgYXMgdmFsdWUgYXBwcm9hY2hlcyBtYXguCiAg"
    "ICBTaG93cyAnTi9BJyB3aGVuIGRhdGEgaXMgdW5hdmFpbGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oCiAgICAgICAg"
    "c2VsZiwKICAgICAgICBsYWJlbDogc3RyLAogICAgICAgIHVuaXQ6IHN0ciA9ICIiLAogICAgICAgIG1heF92YWw6IGZsb2F0ID0g"
    "MTAwLjAsCiAgICAgICAgY29sb3I6IHN0ciA9IENfR09MRCwKICAgICAgICBwYXJlbnQ9Tm9uZQogICAgKToKICAgICAgICBzdXBl"
    "cigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLmxhYmVsICAgID0gbGFiZWwKICAgICAgICBzZWxmLnVuaXQgICAgID0g"
    "dW5pdAogICAgICAgIHNlbGYubWF4X3ZhbCAgPSBtYXhfdmFsCiAgICAgICAgc2VsZi5jb2xvciAgICA9IGNvbG9yCiAgICAgICAg"
    "c2VsZi5fdmFsdWUgICA9IDAuMAogICAgICAgIHNlbGYuX2Rpc3BsYXkgPSAiTi9BIgogICAgICAgIHNlbGYuX2F2YWlsYWJsZSA9"
    "IEZhbHNlCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSgxMDAsIDYwKQogICAgICAgIHNlbGYuc2V0TWF4aW11bUhlaWdodCg3"
    "MikKCiAgICBkZWYgc2V0VmFsdWUoc2VsZiwgdmFsdWU6IGZsb2F0LCBkaXNwbGF5OiBzdHIgPSAiIiwgYXZhaWxhYmxlOiBib29s"
    "ID0gVHJ1ZSkgLT4gTm9uZToKICAgICAgICBzZWxmLl92YWx1ZSAgICAgPSBtaW4oZmxvYXQodmFsdWUpLCBzZWxmLm1heF92YWwp"
    "CiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gYXZhaWxhYmxlCiAgICAgICAgaWYgbm90IGF2YWlsYWJsZToKICAgICAgICAgICAg"
    "c2VsZi5fZGlzcGxheSA9ICJOL0EiCiAgICAgICAgZWxpZiBkaXNwbGF5OgogICAgICAgICAgICBzZWxmLl9kaXNwbGF5ID0gZGlz"
    "cGxheQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkgPSBmInt2YWx1ZTouMGZ9e3NlbGYudW5pdH0iCiAg"
    "ICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBzZXRVbmF2YWlsYWJsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2F2"
    "YWlsYWJsZSA9IEZhbHNlCiAgICAgICAgc2VsZi5fZGlzcGxheSAgID0gIk4vQSIKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAg"
    "ZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5z"
    "ZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCks"
    "IHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgIyBCYWNrZ3JvdW5kCiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3LCBoLCBRQ29sb3Io"
    "Q19CRzMpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgcC5kcmF3UmVjdCgwLCAwLCB3IC0gMSwg"
    "aCAtIDEpCgogICAgICAgICMgTGFiZWwKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgcC5zZXRG"
    "b250KFFGb250KERFQ0tfRk9OVCwgOCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIHAuZHJhd1RleHQoNiwgMTQsIHNlbGYu"
    "bGFiZWwpCgogICAgICAgICMgVmFsdWUKICAgICAgICBwLnNldFBlbihRQ29sb3Ioc2VsZi5jb2xvciBpZiBzZWxmLl9hdmFpbGFi"
    "bGUgZWxzZSBDX1RFWFRfRElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCAxMCwgUUZvbnQuV2VpZ2h0LkJv"
    "bGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgdncgPSBmbS5ob3Jpem9udGFsQWR2YW5jZShzZWxmLl9k"
    "aXNwbGF5KQogICAgICAgIHAuZHJhd1RleHQodyAtIHZ3IC0gNiwgMTQsIHNlbGYuX2Rpc3BsYXkpCgogICAgICAgICMgRmlsbCBi"
    "YXIKICAgICAgICBiYXJfeSA9IGggLSAxOAogICAgICAgIGJhcl9oID0gMTAKICAgICAgICBiYXJfdyA9IHcgLSAxMgogICAgICAg"
    "IHAuZmlsbFJlY3QoNiwgYmFyX3ksIGJhcl93LCBiYXJfaCwgUUNvbG9yKENfQkcpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihD"
    "X0JPUkRFUikpCiAgICAgICAgcC5kcmF3UmVjdCg2LCBiYXJfeSwgYmFyX3cgLSAxLCBiYXJfaCAtIDEpCgogICAgICAgIGlmIHNl"
    "bGYuX2F2YWlsYWJsZSBhbmQgc2VsZi5tYXhfdmFsID4gMDoKICAgICAgICAgICAgZnJhYyA9IHNlbGYuX3ZhbHVlIC8gc2VsZi5t"
    "YXhfdmFsCiAgICAgICAgICAgIGZpbGxfdyA9IG1heCgxLCBpbnQoKGJhcl93IC0gMikgKiBmcmFjKSkKICAgICAgICAgICAgIyBD"
    "b2xvciBzaGlmdCBuZWFyIGxpbWl0CiAgICAgICAgICAgIGJhcl9jb2xvciA9IChDX0JMT09EIGlmIGZyYWMgPiAwLjg1IGVsc2UK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIENfQ1JJTVNPTiBpZiBmcmFjID4gMC42NSBlbHNlCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICBzZWxmLmNvbG9yKQogICAgICAgICAgICBncmFkID0gUUxpbmVhckdyYWRpZW50KDcsIGJhcl95ICsgMSwgNyArIGZpbGxf"
    "dywgYmFyX3kgKyAxKQogICAgICAgICAgICBncmFkLnNldENvbG9yQXQoMCwgUUNvbG9yKGJhcl9jb2xvcikuZGFya2VyKDE2MCkp"
    "CiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgxLCBRQ29sb3IoYmFyX2NvbG9yKSkKICAgICAgICAgICAgcC5maWxsUmVjdCg3"
    "LCBiYXJfeSArIDEsIGZpbGxfdywgYmFyX2ggLSAyLCBncmFkKQoKICAgICAgICBwLmVuZCgpCgoKIyDilIDilIAgRFJJVkUgV0lE"
    "R0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEcml2ZVdpZGdldChRV2lkZ2V0KToKICAgICIi"
    "IgogICAgRHJpdmUgdXNhZ2UgZGlzcGxheS4gU2hvd3MgZHJpdmUgbGV0dGVyLCB1c2VkL3RvdGFsIEdCLCBmaWxsIGJhci4KICAg"
    "IEF1dG8tZGV0ZWN0cyBhbGwgbW91bnRlZCBkcml2ZXMgdmlhIHBzdXRpbC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxm"
    "LCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZHJpdmVzOiBsaXN0"
    "W2RpY3RdID0gW10KICAgICAgICBzZWxmLnNldE1pbmltdW1IZWlnaHQoMzApCiAgICAgICAgc2VsZi5fcmVmcmVzaCgpCgogICAg"
    "ZGVmIF9yZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZHJpdmVzID0gW10KICAgICAgICBpZiBub3QgUFNVVElM"
    "X09LOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIGZvciBwYXJ0IGluIHBzdXRpbC5kaXNrX3Bh"
    "cnRpdGlvbnMoYWxsPUZhbHNlKToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICB1c2FnZSA9IHBzdXRp"
    "bC5kaXNrX3VzYWdlKHBhcnQubW91bnRwb2ludCkKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kcml2ZXMuYXBwZW5kKHsKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgImxldHRlciI6IHBhcnQuZGV2aWNlLnJzdHJpcCgiXFwiKS5yc3RyaXAoIi8iKSwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgInVzZWQiOiAgIHVzYWdlLnVzZWQgIC8gMTAyNCoqMywKICAgICAgICAgICAgICAgICAgICAgICAg"
    "InRvdGFsIjogIHVzYWdlLnRvdGFsIC8gMTAyNCoqMywKICAgICAgICAgICAgICAgICAgICAgICAgInBjdCI6ICAgIHVzYWdlLnBl"
    "cmNlbnQgLyAxMDAuMCwKICAgICAgICAgICAgICAgICAgICB9KQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAg"
    "ICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKICAgICAg"
    "ICAjIFJlc2l6ZSB0byBmaXQgYWxsIGRyaXZlcwogICAgICAgIG4gPSBtYXgoMSwgbGVuKHNlbGYuX2RyaXZlcykpCiAgICAgICAg"
    "c2VsZi5zZXRNaW5pbXVtSGVpZ2h0KG4gKiAyOCArIDgpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50"
    "KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0UmVuZGVySGludChR"
    "UGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgp"
    "CiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3LCBoLCBRQ29sb3IoQ19CRzMpKQoKICAgICAgICBpZiBub3Qgc2VsZi5fZHJpdmVz"
    "OgogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udChERUNL"
    "X0ZPTlQsIDkpKQogICAgICAgICAgICBwLmRyYXdUZXh0KDYsIDE4LCAiTi9BIOKAlCBwc3V0aWwgdW5hdmFpbGFibGUiKQogICAg"
    "ICAgICAgICBwLmVuZCgpCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICByb3dfaCA9IDI2CiAgICAgICAgeSA9IDQKICAgICAg"
    "ICBmb3IgZHJ2IGluIHNlbGYuX2RyaXZlczoKICAgICAgICAgICAgbGV0dGVyID0gZHJ2WyJsZXR0ZXIiXQogICAgICAgICAgICB1"
    "c2VkICAgPSBkcnZbInVzZWQiXQogICAgICAgICAgICB0b3RhbCAgPSBkcnZbInRvdGFsIl0KICAgICAgICAgICAgcGN0ICAgID0g"
    "ZHJ2WyJwY3QiXQoKICAgICAgICAgICAgIyBMYWJlbAogICAgICAgICAgICBsYWJlbCA9IGYie2xldHRlcn0gIHt1c2VkOi4xZn0v"
    "e3RvdGFsOi4wZn1HQiIKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfR09MRCkpCiAgICAgICAgICAgIHAuc2V0Rm9udChR"
    "Rm9udChERUNLX0ZPTlQsIDgsIFFGb250LldlaWdodC5Cb2xkKSkKICAgICAgICAgICAgcC5kcmF3VGV4dCg2LCB5ICsgMTIsIGxh"
    "YmVsKQoKICAgICAgICAgICAgIyBCYXIKICAgICAgICAgICAgYmFyX3ggPSA2CiAgICAgICAgICAgIGJhcl95ID0geSArIDE1CiAg"
    "ICAgICAgICAgIGJhcl93ID0gdyAtIDEyCiAgICAgICAgICAgIGJhcl9oID0gOAogICAgICAgICAgICBwLmZpbGxSZWN0KGJhcl94"
    "LCBiYXJfeSwgYmFyX3csIGJhcl9oLCBRQ29sb3IoQ19CRykpCiAgICAgICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikp"
    "CiAgICAgICAgICAgIHAuZHJhd1JlY3QoYmFyX3gsIGJhcl95LCBiYXJfdyAtIDEsIGJhcl9oIC0gMSkKCiAgICAgICAgICAgIGZp"
    "bGxfdyA9IG1heCgxLCBpbnQoKGJhcl93IC0gMikgKiBwY3QpKQogICAgICAgICAgICBiYXJfY29sb3IgPSAoQ19CTE9PRCBpZiBw"
    "Y3QgPiAwLjkgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19DUklNU09OIGlmIHBjdCA+IDAuNzUgZWxzZQogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgQ19HT0xEX0RJTSkKICAgICAgICAgICAgZ3JhZCA9IFFMaW5lYXJHcmFkaWVudChiYXJfeCArIDEs"
    "IGJhcl95LCBiYXJfeCArIGZpbGxfdywgYmFyX3kpCiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgwLCBRQ29sb3IoYmFyX2Nv"
    "bG9yKS5kYXJrZXIoMTUwKSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDEsIFFDb2xvcihiYXJfY29sb3IpKQogICAgICAg"
    "ICAgICBwLmZpbGxSZWN0KGJhcl94ICsgMSwgYmFyX3kgKyAxLCBmaWxsX3csIGJhcl9oIC0gMiwgZ3JhZCkKCiAgICAgICAgICAg"
    "IHkgKz0gcm93X2gKCiAgICAgICAgcC5lbmQoKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiQ2Fs"
    "bCBwZXJpb2RpY2FsbHkgdG8gdXBkYXRlIGRyaXZlIHN0YXRzLiIiIgogICAgICAgIHNlbGYuX3JlZnJlc2goKQoKCiMg4pSA4pSA"
    "IFNQSEVSRSBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNwaGVyZVdpZGdldChRV2lkZ2V0"
    "KToKICAgICIiIgogICAgRmlsbGVkIGNpcmNsZSBnYXVnZSDigJQgdXNlZCBmb3IgQkxPT0QgKHRva2VuIHBvb2wpIGFuZCBNQU5B"
    "IChWUkFNKS4KICAgIEZpbGxzIGZyb20gYm90dG9tIHVwLiBHbGFzc3kgc2hpbmUgZWZmZWN0LiBMYWJlbCBiZWxvdy4KICAgICIi"
    "IgoKICAgIGRlZiBfX2luaXRfXygKICAgICAgICBzZWxmLAogICAgICAgIGxhYmVsOiBzdHIsCiAgICAgICAgY29sb3JfZnVsbDog"
    "c3RyLAogICAgICAgIGNvbG9yX2VtcHR5OiBzdHIsCiAgICAgICAgcGFyZW50PU5vbmUKICAgICk6CiAgICAgICAgc3VwZXIoKS5f"
    "X2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5sYWJlbCAgICAgICA9IGxhYmVsCiAgICAgICAgc2VsZi5jb2xvcl9mdWxsICA9"
    "IGNvbG9yX2Z1bGwKICAgICAgICBzZWxmLmNvbG9yX2VtcHR5ID0gY29sb3JfZW1wdHkKICAgICAgICBzZWxmLl9maWxsICAgICAg"
    "ID0gMC4wICAgIyAwLjAg4oaSIDEuMAogICAgICAgIHNlbGYuX2F2YWlsYWJsZSAgPSBUcnVlCiAgICAgICAgc2VsZi5zZXRNaW5p"
    "bXVtU2l6ZSg4MCwgMTAwKQoKICAgIGRlZiBzZXRGaWxsKHNlbGYsIGZyYWN0aW9uOiBmbG9hdCwgYXZhaWxhYmxlOiBib29sID0g"
    "VHJ1ZSkgLT4gTm9uZToKICAgICAgICBzZWxmLl9maWxsICAgICAgPSBtYXgoMC4wLCBtaW4oMS4wLCBmcmFjdGlvbikpCiAgICAg"
    "ICAgc2VsZi5fYXZhaWxhYmxlID0gYXZhaWxhYmxlCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNl"
    "bGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0UmVuZGVySGludChRUGFp"
    "bnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCgog"
    "ICAgICAgIHIgID0gbWluKHcsIGggLSAyMCkgLy8gMiAtIDQKICAgICAgICBjeCA9IHcgLy8gMgogICAgICAgIGN5ID0gKGggLSAy"
    "MCkgLy8gMiArIDQKCiAgICAgICAgIyBEcm9wIHNoYWRvdwogICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAg"
    "ICAgIHAuc2V0QnJ1c2goUUNvbG9yKDAsIDAsIDAsIDgwKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciArIDMsIGN5IC0g"
    "ciArIDMsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBCYXNlIGNpcmNsZSAoZW1wdHkgY29sb3IpCiAgICAgICAgcC5zZXRCcnVz"
    "aChRQ29sb3Ioc2VsZi5jb2xvcl9lbXB0eSkpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9SREVSKSkKICAgICAgICBwLmRy"
    "YXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgRmlsbCBmcm9tIGJvdHRvbQogICAgICAg"
    "IGlmIHNlbGYuX2ZpbGwgPiAwLjAxIGFuZCBzZWxmLl9hdmFpbGFibGU6CiAgICAgICAgICAgIGNpcmNsZV9wYXRoID0gUVBhaW50"
    "ZXJQYXRoKCkKICAgICAgICAgICAgY2lyY2xlX3BhdGguYWRkRWxsaXBzZShmbG9hdChjeCAtIHIpLCBmbG9hdChjeSAtIHIpLAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQoKICAgICAgICAgICAg"
    "ZmlsbF90b3BfeSA9IGN5ICsgciAtIChzZWxmLl9maWxsICogciAqIDIpCiAgICAgICAgICAgIGZyb20gUHlTaWRlNi5RdENvcmUg"
    "aW1wb3J0IFFSZWN0RgogICAgICAgICAgICBmaWxsX3JlY3QgPSBRUmVjdEYoY3ggLSByLCBmaWxsX3RvcF95LCByICogMiwgY3kg"
    "KyByIC0gZmlsbF90b3BfeSkKICAgICAgICAgICAgZmlsbF9wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgZmlsbF9w"
    "YXRoLmFkZFJlY3QoZmlsbF9yZWN0KQogICAgICAgICAgICBjbGlwcGVkID0gY2lyY2xlX3BhdGguaW50ZXJzZWN0ZWQoZmlsbF9w"
    "YXRoKQoKICAgICAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgICAgIHAuc2V0QnJ1c2goUUNvbG9y"
    "KHNlbGYuY29sb3JfZnVsbCkpCiAgICAgICAgICAgIHAuZHJhd1BhdGgoY2xpcHBlZCkKCiAgICAgICAgIyBHbGFzc3kgc2hpbmUK"
    "ICAgICAgICBzaGluZSA9IFFSYWRpYWxHcmFkaWVudCgKICAgICAgICAgICAgZmxvYXQoY3ggLSByICogMC4zKSwgZmxvYXQoY3kg"
    "LSByICogMC4zKSwgZmxvYXQociAqIDAuNikKICAgICAgICApCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgwLCBRQ29sb3IoMjU1"
    "LCAyNTUsIDI1NSwgNTUpKQogICAgICAgIHNoaW5lLnNldENvbG9yQXQoMSwgUUNvbG9yKDI1NSwgMjU1LCAyNTUsIDApKQogICAg"
    "ICAgIHAuc2V0QnJ1c2goc2hpbmUpCiAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgcC5kcmF3RWxs"
    "aXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIE91dGxpbmUKICAgICAgICBwLnNldEJydXNoKFF0"
    "LkJydXNoU3R5bGUuTm9CcnVzaCkKICAgICAgICBwLnNldFBlbihRUGVuKFFDb2xvcihzZWxmLmNvbG9yX2Z1bGwpLCAxKSkKICAg"
    "ICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgTi9BIG92ZXJsYXkKICAg"
    "ICAgICBpZiBub3Qgc2VsZi5fYXZhaWxhYmxlOgogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAg"
    "ICAgICAgIHAuc2V0Rm9udChRRm9udCgiQ291cmllciBOZXciLCA4KSkKICAgICAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkK"
    "ICAgICAgICAgICAgdHh0ID0gIk4vQSIKICAgICAgICAgICAgcC5kcmF3VGV4dChjeCAtIGZtLmhvcml6b250YWxBZHZhbmNlKHR4"
    "dCkgLy8gMiwgY3kgKyA0LCB0eHQpCgogICAgICAgICMgTGFiZWwgYmVsb3cgc3BoZXJlCiAgICAgICAgbGFiZWxfdGV4dCA9IChz"
    "ZWxmLmxhYmVsIGlmIHNlbGYuX2F2YWlsYWJsZSBlbHNlCiAgICAgICAgICAgICAgICAgICAgICBmIntzZWxmLmxhYmVsfSIpCiAg"
    "ICAgICAgcGN0X3RleHQgPSBmIntpbnQoc2VsZi5fZmlsbCAqIDEwMCl9JSIgaWYgc2VsZi5fYXZhaWxhYmxlIGVsc2UgIiIKCiAg"
    "ICAgICAgcC5zZXRQZW4oUUNvbG9yKHNlbGYuY29sb3JfZnVsbCkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwg"
    "OCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCgogICAgICAgIGx3ID0gZm0uaG9yaXpv"
    "bnRhbEFkdmFuY2UobGFiZWxfdGV4dCkKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gbHcgLy8gMiwgaCAtIDEwLCBsYWJlbF90ZXh0"
    "KQoKICAgICAgICBpZiBwY3RfdGV4dDoKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfVEVYVF9ESU0pKQogICAgICAgICAg"
    "ICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAgICAgICAgICAgZm0yID0gcC5mb250TWV0cmljcygpCiAgICAgICAg"
    "ICAgIHB3ID0gZm0yLmhvcml6b250YWxBZHZhbmNlKHBjdF90ZXh0KQogICAgICAgICAgICBwLmRyYXdUZXh0KGN4IC0gcHcgLy8g"
    "MiwgaCAtIDEsIHBjdF90ZXh0KQoKICAgICAgICBwLmVuZCgpCgoKIyDilIDilIAgTU9PTiBXSURHRVQg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1vb25XaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIERyYXduIG1vb24g"
    "b3JiIHdpdGggcGhhc2UtYWNjdXJhdGUgc2hhZG93LgoKICAgIFBIQVNFIENPTlZFTlRJT04gKG5vcnRoZXJuIGhlbWlzcGhlcmUs"
    "IHN0YW5kYXJkKToKICAgICAgLSBXYXhpbmcgKG5ld+KGkmZ1bGwpOiBpbGx1bWluYXRlZCByaWdodCBzaWRlLCBzaGFkb3cgb24g"
    "bGVmdAogICAgICAtIFdhbmluZyAoZnVsbOKGkm5ldyk6IGlsbHVtaW5hdGVkIGxlZnQgc2lkZSwgc2hhZG93IG9uIHJpZ2h0Cgog"
    "ICAgVGhlIHNoYWRvd19zaWRlIGZsYWcgY2FuIGJlIGZsaXBwZWQgaWYgdGVzdGluZyByZXZlYWxzIGl0J3MgYmFja3dhcmRzCiAg"
    "ICBvbiB0aGlzIG1hY2hpbmUuIFNldCBNT09OX1NIQURPV19GTElQID0gVHJ1ZSBpbiB0aGF0IGNhc2UuCiAgICAiIiIKCiAgICAj"
    "IOKGkCBGTElQIFRISVMgdG8gVHJ1ZSBpZiBtb29uIGFwcGVhcnMgYmFja3dhcmRzIGR1cmluZyB0ZXN0aW5nCiAgICBNT09OX1NI"
    "QURPV19GTElQOiBib29sID0gRmFsc2UKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVy"
    "KCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BoYXNlICAgICAgID0gMC4wICAgICMgMC4wPW5ldywgMC41PWZ1bGws"
    "IDEuMD1uZXcKICAgICAgICBzZWxmLl9uYW1lICAgICAgICA9ICJORVcgTU9PTiIKICAgICAgICBzZWxmLl9pbGx1bWluYXRpb24g"
    "PSAwLjAgICAjIDAtMTAwCiAgICAgICAgc2VsZi5fc3VucmlzZSAgICAgID0gIjA2OjAwIgogICAgICAgIHNlbGYuX3N1bnNldCAg"
    "ICAgICA9ICIxODozMCIKICAgICAgICBzZWxmLl9zdW5fZGF0ZSAgICAgPSBOb25lCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6"
    "ZSg4MCwgMTEwKQogICAgICAgIHNlbGYudXBkYXRlUGhhc2UoKSAgICAgICAgICAjIHBvcHVsYXRlIGNvcnJlY3QgcGhhc2UgaW1t"
    "ZWRpYXRlbHkKICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQoKICAgIGRlZiBfZmV0Y2hfc3VuX2FzeW5jKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgZGVmIF9mZXRjaCgpOgogICAgICAgICAgICBzciwgc3MgPSBnZXRfc3VuX3RpbWVzKCkKICAgICAgICAg"
    "ICAgc2VsZi5fc3VucmlzZSA9IHNyCiAgICAgICAgICAgIHNlbGYuX3N1bnNldCAgPSBzcwogICAgICAgICAgICBzZWxmLl9zdW5f"
    "ZGF0ZSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAgICAgICAgICAgIyBTY2hlZHVsZSByZXBhaW50IG9u"
    "IG1haW4gdGhyZWFkIHZpYSBRVGltZXIg4oCUIG5ldmVyIGNhbGwKICAgICAgICAgICAgIyBzZWxmLnVwZGF0ZSgpIGRpcmVjdGx5"
    "IGZyb20gYSBiYWNrZ3JvdW5kIHRocmVhZAogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgwLCBzZWxmLnVwZGF0ZSkKICAg"
    "ICAgICB0aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fZmV0Y2gsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAgZGVmIHVwZGF0ZVBo"
    "YXNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcGhhc2UsIHNlbGYuX25hbWUsIHNlbGYuX2lsbHVtaW5hdGlvbiA9IGdl"
    "dF9tb29uX3BoYXNlKCkKICAgICAgICB0b2RheSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAgICAgICBp"
    "ZiBzZWxmLl9zdW5fZGF0ZSAhPSB0b2RheToKICAgICAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAgICBzZWxm"
    "LnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNl"
    "bGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGgg"
    "PSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgciAgPSBtaW4odywgaCAtIDM2KSAvLyAyIC0gNAogICAgICAg"
    "IGN4ID0gdyAvLyAyCiAgICAgICAgY3kgPSAoaCAtIDM2KSAvLyAyICsgNAoKICAgICAgICAjIEJhY2tncm91bmQgY2lyY2xlIChz"
    "cGFjZSkKICAgICAgICBwLnNldEJydXNoKFFDb2xvcigyMCwgMTIsIDI4KSkKICAgICAgICBwLnNldFBlbihRUGVuKFFDb2xvcihD"
    "X1NJTFZFUl9ESU0pLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAg"
    "ICAgIGN5Y2xlX2RheSA9IHNlbGYuX3BoYXNlICogX0xVTkFSX0NZQ0xFCiAgICAgICAgaXNfd2F4aW5nID0gY3ljbGVfZGF5IDwg"
    "KF9MVU5BUl9DWUNMRSAvIDIpCgogICAgICAgICMgRnVsbCBtb29uIGJhc2UgKG1vb24gc3VyZmFjZSBjb2xvcikKICAgICAgICBp"
    "ZiBzZWxmLl9pbGx1bWluYXRpb24gPiAxOgogICAgICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICAg"
    "ICAgcC5zZXRCcnVzaChRQ29sb3IoMjIwLCAyMTAsIDE4NSkpCiAgICAgICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAt"
    "IHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBTaGFkb3cgY2FsY3VsYXRpb24KICAgICAgICAjIGlsbHVtaW5hdGlvbiBnb2Vz"
    "IDDihpIxMDAgd2F4aW5nLCAxMDDihpIwIHdhbmluZwogICAgICAgICMgc2hhZG93X29mZnNldCBjb250cm9scyBob3cgbXVjaCBv"
    "ZiB0aGUgY2lyY2xlIHRoZSBzaGFkb3cgY292ZXJzCiAgICAgICAgaWYgc2VsZi5faWxsdW1pbmF0aW9uIDwgOTk6CiAgICAgICAg"
    "ICAgICMgZnJhY3Rpb24gb2YgZGlhbWV0ZXIgdGhlIHNoYWRvdyBlbGxpcHNlIGlzIG9mZnNldAogICAgICAgICAgICBpbGx1bV9m"
    "cmFjICA9IHNlbGYuX2lsbHVtaW5hdGlvbiAvIDEwMC4wCiAgICAgICAgICAgIHNoYWRvd19mcmFjID0gMS4wIC0gaWxsdW1fZnJh"
    "YwoKICAgICAgICAgICAgIyB3YXhpbmc6IGlsbHVtaW5hdGVkIHJpZ2h0LCBzaGFkb3cgTEVGVAogICAgICAgICAgICAjIHdhbmlu"
    "ZzogaWxsdW1pbmF0ZWQgbGVmdCwgc2hhZG93IFJJR0hUCiAgICAgICAgICAgICMgb2Zmc2V0IG1vdmVzIHRoZSBzaGFkb3cgZWxs"
    "aXBzZSBob3Jpem9udGFsbHkKICAgICAgICAgICAgb2Zmc2V0ID0gaW50KHNoYWRvd19mcmFjICogciAqIDIpCgogICAgICAgICAg"
    "ICBpZiBNb29uV2lkZ2V0Lk1PT05fU0hBRE9XX0ZMSVA6CiAgICAgICAgICAgICAgICBpc193YXhpbmcgPSBub3QgaXNfd2F4aW5n"
    "CgogICAgICAgICAgICBpZiBpc193YXhpbmc6CiAgICAgICAgICAgICAgICAjIFNoYWRvdyBvbiBsZWZ0IHNpZGUKICAgICAgICAg"
    "ICAgICAgIHNoYWRvd194ID0gY3ggLSByIC0gb2Zmc2V0CiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAjIFNoYWRv"
    "dyBvbiByaWdodCBzaWRlCiAgICAgICAgICAgICAgICBzaGFkb3dfeCA9IGN4IC0gciArIG9mZnNldAoKICAgICAgICAgICAgcC5z"
    "ZXRCcnVzaChRQ29sb3IoMTUsIDgsIDIyKSkKICAgICAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCgogICAgICAg"
    "ICAgICAjIERyYXcgc2hhZG93IGVsbGlwc2Ug4oCUIGNsaXBwZWQgdG8gbW9vbiBjaXJjbGUKICAgICAgICAgICAgbW9vbl9wYXRo"
    "ID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgbW9vbl9wYXRoLmFkZEVsbGlwc2UoZmxvYXQoY3ggLSByKSwgZmxvYXQoY3kg"
    "LSByKSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQogICAgICAg"
    "ICAgICBzaGFkb3dfcGF0aCA9IFFQYWludGVyUGF0aCgpCiAgICAgICAgICAgIHNoYWRvd19wYXRoLmFkZEVsbGlwc2UoZmxvYXQo"
    "c2hhZG93X3gpLCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmbG9hdChyICogMiks"
    "IGZsb2F0KHIgKiAyKSkKICAgICAgICAgICAgY2xpcHBlZF9zaGFkb3cgPSBtb29uX3BhdGguaW50ZXJzZWN0ZWQoc2hhZG93X3Bh"
    "dGgpCiAgICAgICAgICAgIHAuZHJhd1BhdGgoY2xpcHBlZF9zaGFkb3cpCgogICAgICAgICMgU3VidGxlIHN1cmZhY2UgZGV0YWls"
    "IChjcmF0ZXJzIGltcGxpZWQgYnkgc2xpZ2h0IHRleHR1cmUgZ3JhZGllbnQpCiAgICAgICAgc2hpbmUgPSBRUmFkaWFsR3JhZGll"
    "bnQoZmxvYXQoY3ggLSByICogMC4yKSwgZmxvYXQoY3kgLSByICogMC4yKSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICBmbG9hdChyICogMC44KSkKICAgICAgICBzaGluZS5zZXRDb2xvckF0KDAsIFFDb2xvcigyNTUsIDI1NSwgMjQwLCAzMCkpCiAg"
    "ICAgICAgc2hpbmUuc2V0Q29sb3JBdCgxLCBRQ29sb3IoMjAwLCAxODAsIDE0MCwgNSkpCiAgICAgICAgcC5zZXRCcnVzaChzaGlu"
    "ZSkKICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSBy"
    "LCByICogMiwgciAqIDIpCgogICAgICAgICMgT3V0bGluZQogICAgICAgIHAuc2V0QnJ1c2goUXQuQnJ1c2hTdHlsZS5Ob0JydXNo"
    "KQogICAgICAgIHAuc2V0UGVuKFFQZW4oUUNvbG9yKENfU0lMVkVSKSwgMSkpCiAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIs"
    "IGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIFBoYXNlIG5hbWUgYmVsb3cgbW9vbgogICAgICAgIHAuc2V0UGVuKFFD"
    "b2xvcihDX1NJTFZFUikpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgNywgUUZvbnQuV2VpZ2h0LkJvbGQpKQog"
    "ICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgbncgPSBmbS5ob3Jpem9udGFsQWR2YW5jZShzZWxmLl9uYW1lKQog"
    "ICAgICAgIHAuZHJhd1RleHQoY3ggLSBudyAvLyAyLCBjeSArIHIgKyAxNCwgc2VsZi5fbmFtZSkKCiAgICAgICAgIyBJbGx1bWlu"
    "YXRpb24gcGVyY2VudGFnZQogICAgICAgIGlsbHVtX3N0ciA9IGYie3NlbGYuX2lsbHVtaW5hdGlvbjouMGZ9JSIKICAgICAgICBw"
    "LnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgNykpCiAgICAgICAg"
    "Zm0yID0gcC5mb250TWV0cmljcygpCiAgICAgICAgaXcgPSBmbTIuaG9yaXpvbnRhbEFkdmFuY2UoaWxsdW1fc3RyKQogICAgICAg"
    "IHAuZHJhd1RleHQoY3ggLSBpdyAvLyAyLCBjeSArIHIgKyAyNCwgaWxsdW1fc3RyKQoKICAgICAgICAjIFN1biB0aW1lcyBhdCB2"
    "ZXJ5IGJvdHRvbQogICAgICAgIHN1bl9zdHIgPSBmIuKYgCB7c2VsZi5fc3VucmlzZX0gIOKYvSB7c2VsZi5fc3Vuc2V0fSIKICAg"
    "ICAgICBwLnNldFBlbihRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgNykpCiAg"
    "ICAgICAgZm0zID0gcC5mb250TWV0cmljcygpCiAgICAgICAgc3cgPSBmbTMuaG9yaXpvbnRhbEFkdmFuY2Uoc3VuX3N0cikKICAg"
    "ICAgICBwLmRyYXdUZXh0KGN4IC0gc3cgLy8gMiwgaCAtIDIsIHN1bl9zdHIpCgogICAgICAgIHAuZW5kKCkKCgojIOKUgOKUgCBF"
    "TU9USU9OIEJMT0NLIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBFbW90aW9uQmxvY2soUVdpZGdldCk6"
    "CiAgICAiIiIKICAgIENvbGxhcHNpYmxlIGVtb3Rpb24gaGlzdG9yeSBwYW5lbC4KICAgIFNob3dzIGNvbG9yLWNvZGVkIGNoaXBz"
    "OiDinKYgRU1PVElPTl9OQU1FICBISDpNTQogICAgU2l0cyBuZXh0IHRvIHRoZSBNaXJyb3IgKGZhY2Ugd2lkZ2V0KSBpbiB0aGUg"
    "Ym90dG9tIGJsb2NrIHJvdy4KICAgIENvbGxhcHNlcyB0byBqdXN0IHRoZSBoZWFkZXIgc3RyaXAuCiAgICAiIiIKCiAgICBkZWYg"
    "X19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYu"
    "X2hpc3Rvcnk6IGxpc3RbdHVwbGVbc3RyLCBzdHJdXSA9IFtdICAjIChlbW90aW9uLCB0aW1lc3RhbXApCiAgICAgICAgc2VsZi5f"
    "ZXhwYW5kZWQgPSBUcnVlCiAgICAgICAgc2VsZi5fbWF4X2VudHJpZXMgPSAzMAoKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91"
    "dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3Bh"
    "Y2luZygwKQoKICAgICAgICAjIEhlYWRlciByb3cKICAgICAgICBoZWFkZXIgPSBRV2lkZ2V0KCkKICAgICAgICBoZWFkZXIuc2V0"
    "Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgaGVhZGVyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0Nf"
    "QkczfTsgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIGhsID0gUUhC"
    "b3hMYXlvdXQoaGVhZGVyKQogICAgICAgIGhsLnNldENvbnRlbnRzTWFyZ2lucyg2LCAwLCA0LCAwKQogICAgICAgIGhsLnNldFNw"
    "YWNpbmcoNCkKCiAgICAgICAgbGJsID0gUUxhYmVsKCLinacgRU1PVElPTkFMIFJFQ09SRCIpCiAgICAgICAgbGJsLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIK"
    "ICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2luZzogMXB4OyBib3JkZXI6"
    "IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX3Rv"
    "Z2dsZV9idG4uc2V0Rml4ZWRTaXplKDE2LCAxNikKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgIGYiYmFja2dyb3VuZDogdHJhbnNwYXJlbnQ7IGNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiBub25lOyBmb250LXNpemU6"
    "IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKWvCIpCiAgICAgICAgc2VsZi5fdG9n"
    "Z2xlX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlKQoKICAgICAgICBobC5hZGRXaWRnZXQobGJsKQogICAgICAgIGhs"
    "LmFkZFN0cmV0Y2goKQogICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl90b2dnbGVfYnRuKQoKICAgICAgICAjIFNjcm9sbCBhcmVh"
    "IGZvciBlbW90aW9uIGNoaXBzCiAgICAgICAgc2VsZi5fc2Nyb2xsID0gUVNjcm9sbEFyZWEoKQogICAgICAgIHNlbGYuX3Njcm9s"
    "bC5zZXRXaWRnZXRSZXNpemFibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0SG9yaXpvbnRhbFNjcm9sbEJhclBvbGlj"
    "eSgKICAgICAgICAgICAgUXQuU2Nyb2xsQmFyUG9saWN5LlNjcm9sbEJhckFsd2F5c09mZikKICAgICAgICBzZWxmLl9zY3JvbGwu"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkK"
    "CiAgICAgICAgc2VsZi5fY2hpcF9jb250YWluZXIgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jaGlwX2xheW91dCA9IFFWQm94"
    "TGF5b3V0KHNlbGYuX2NoaXBfY29udGFpbmVyKQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0"
    "LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBzZWxmLl9jaGlwX2xheW91"
    "dC5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0V2lkZ2V0KHNlbGYuX2NoaXBfY29udGFpbmVyKQoKICAgICAg"
    "ICBsYXlvdXQuYWRkV2lkZ2V0KGhlYWRlcikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Njcm9sbCkKCiAgICAgICAg"
    "c2VsZi5zZXRNaW5pbXVtV2lkdGgoMTMwKQoKICAgIGRlZiBfdG9nZ2xlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZXhw"
    "YW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5kZWQKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0VmlzaWJsZShzZWxmLl9leHBhbmRlZCkK"
    "ICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKWvCIgaWYgc2VsZi5fZXhwYW5kZWQgZWxzZSAi4payIikKICAgICAg"
    "ICBzZWxmLnVwZGF0ZUdlb21ldHJ5KCkKCiAgICBkZWYgYWRkRW1vdGlvbihzZWxmLCBlbW90aW9uOiBzdHIsIHRpbWVzdGFtcDog"
    "c3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHRpbWVzdGFtcDoKICAgICAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRp"
    "bWUubm93KCkuc3RyZnRpbWUoIiVIOiVNIikKICAgICAgICBzZWxmLl9oaXN0b3J5Lmluc2VydCgwLCAoZW1vdGlvbiwgdGltZXN0"
    "YW1wKSkKICAgICAgICBzZWxmLl9oaXN0b3J5ID0gc2VsZi5faGlzdG9yeVs6c2VsZi5fbWF4X2VudHJpZXNdCiAgICAgICAgc2Vs"
    "Zi5fcmVidWlsZF9jaGlwcygpCgogICAgZGVmIF9yZWJ1aWxkX2NoaXBzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBDbGVhciBl"
    "eGlzdGluZyBjaGlwcyAoa2VlcCB0aGUgc3RyZXRjaCBhdCBlbmQpCiAgICAgICAgd2hpbGUgc2VsZi5fY2hpcF9sYXlvdXQuY291"
    "bnQoKSA+IDE6CiAgICAgICAgICAgIGl0ZW0gPSBzZWxmLl9jaGlwX2xheW91dC50YWtlQXQoMCkKICAgICAgICAgICAgaWYgaXRl"
    "bS53aWRnZXQoKToKICAgICAgICAgICAgICAgIGl0ZW0ud2lkZ2V0KCkuZGVsZXRlTGF0ZXIoKQoKICAgICAgICBmb3IgZW1vdGlv"
    "biwgdHMgaW4gc2VsZi5faGlzdG9yeToKICAgICAgICAgICAgY29sb3IgPSBFTU9USU9OX0NPTE9SUy5nZXQoZW1vdGlvbiwgQ19U"
    "RVhUX0RJTSkKICAgICAgICAgICAgY2hpcCA9IFFMYWJlbChmIuKcpiB7ZW1vdGlvbi51cHBlcigpfSAge3RzfSIpCiAgICAgICAg"
    "ICAgIGNoaXAuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZvbnQtc2l6ZTogOXB4OyBm"
    "b250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGJv"
    "cmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgICAgIGYicGFkZGluZzogMXB4IDRweDsgYm9yZGVyLXJh"
    "ZGl1czogMnB4OyIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5pbnNlcnRXaWRnZXQoCiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5jb3VudCgpIC0gMSwgY2hpcAogICAgICAgICAgICApCgogICAgZGVmIGNsZWFy"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5faGlzdG9yeS5jbGVhcigpCiAgICAgICAgc2VsZi5fcmVidWlsZF9jaGlwcygp"
    "CgoKIyDilIDilIAgTUlSUk9SIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTWlycm9yV2lk"
    "Z2V0KFFMYWJlbCk6CiAgICAiIiIKICAgIEZhY2UgaW1hZ2UgZGlzcGxheSDigJQgJ1RoZSBNaXJyb3InLgogICAgRHluYW1pY2Fs"
    "bHkgbG9hZHMgYWxsIHtGQUNFX1BSRUZJWH1fKi5wbmcgZmlsZXMgZnJvbSBjb25maWcgcGF0aHMuZmFjZXMuCiAgICBBdXRvLW1h"
    "cHMgZmlsZW5hbWUgdG8gZW1vdGlvbiBrZXk6CiAgICAgICAge0ZBQ0VfUFJFRklYfV9BbGVydC5wbmcgICAgIOKGkiAiYWxlcnQi"
    "CiAgICAgICAge0ZBQ0VfUFJFRklYfV9TYWRfQ3J5aW5nLnBuZyDihpIgInNhZCIKICAgICAgICB7RkFDRV9QUkVGSVh9X0NoZWF0"
    "X01vZGUucG5nIOKGkiAiY2hlYXRtb2RlIgogICAgRmFsbHMgYmFjayB0byBuZXV0cmFsLCB0aGVuIHRvIGdvdGhpYyBwbGFjZWhv"
    "bGRlciBpZiBubyBpbWFnZXMgZm91bmQuCiAgICBNaXNzaW5nIGZhY2VzIGRlZmF1bHQgdG8gbmV1dHJhbCDigJQgbm8gY3Jhc2gs"
    "IG5vIGhhcmRjb2RlZCBsaXN0IHJlcXVpcmVkLgogICAgIiIiCgogICAgIyBTcGVjaWFsIHN0ZW0g4oaSIGVtb3Rpb24ga2V5IG1h"
    "cHBpbmdzIChsb3dlcmNhc2Ugc3RlbSBhZnRlciBNb3JnYW5uYV8pCiAgICBfU1RFTV9UT19FTU9USU9OOiBkaWN0W3N0ciwgc3Ry"
    "XSA9IHsKICAgICAgICAic2FkX2NyeWluZyI6ICAic2FkIiwKICAgICAgICAiY2hlYXRfbW9kZSI6ICAiY2hlYXRtb2RlIiwKICAg"
    "IH0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQog"
    "ICAgICAgIHNlbGYuX2ZhY2VzX2RpciAgID0gY2ZnX3BhdGgoImZhY2VzIikKICAgICAgICBzZWxmLl9jYWNoZTogZGljdFtzdHIs"
    "IFFQaXhtYXBdID0ge30KICAgICAgICBzZWxmLl9jdXJyZW50ICAgICA9ICJuZXV0cmFsIgogICAgICAgIHNlbGYuX3dhcm5lZDog"
    "c2V0W3N0cl0gPSBzZXQoKQoKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDE2MCwgMTYwKQogICAgICAgIHNlbGYuc2V0QWxp"
    "Z25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBm"
    "ImJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQoKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgzMDAsIHNlbGYuX3ByZWxv"
    "YWQpCgogICAgZGVmIF9wcmVsb2FkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgU2NhbiBGYWNlcy8gZGlyZWN0"
    "b3J5IGZvciBhbGwge0ZBQ0VfUFJFRklYfV8qLnBuZyBmaWxlcy4KICAgICAgICBCdWlsZCBlbW90aW9u4oaScGl4bWFwIGNhY2hl"
    "IGR5bmFtaWNhbGx5LgogICAgICAgIE5vIGhhcmRjb2RlZCBsaXN0IOKAlCB3aGF0ZXZlciBpcyBpbiB0aGUgZm9sZGVyIGlzIGF2"
    "YWlsYWJsZS4KICAgICAgICAiIiIKICAgICAgICBpZiBub3Qgc2VsZi5fZmFjZXNfZGlyLmV4aXN0cygpOgogICAgICAgICAgICBz"
    "ZWxmLl9kcmF3X3BsYWNlaG9sZGVyKCkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIGZvciBpbWdfcGF0aCBpbiBzZWxmLl9m"
    "YWNlc19kaXIuZ2xvYihmIntGQUNFX1BSRUZJWH1fKi5wbmciKToKICAgICAgICAgICAgIyBzdGVtID0gZXZlcnl0aGluZyBhZnRl"
    "ciAiTW9yZ2FubmFfIiB3aXRob3V0IC5wbmcKICAgICAgICAgICAgcmF3X3N0ZW0gPSBpbWdfcGF0aC5zdGVtW2xlbihmIntGQUNF"
    "X1BSRUZJWH1fIik6XSAgICAjIGUuZy4gIlNhZF9DcnlpbmciCiAgICAgICAgICAgIHN0ZW1fbG93ZXIgPSByYXdfc3RlbS5sb3dl"
    "cigpICAgICAgICAgICAgICAgICAgICAgICAgICAjICJzYWRfY3J5aW5nIgoKICAgICAgICAgICAgIyBNYXAgc3BlY2lhbCBzdGVt"
    "cyB0byBlbW90aW9uIGtleXMKICAgICAgICAgICAgZW1vdGlvbiA9IHNlbGYuX1NURU1fVE9fRU1PVElPTi5nZXQoc3RlbV9sb3dl"
    "ciwgc3RlbV9sb3dlcikKCiAgICAgICAgICAgIHB4ID0gUVBpeG1hcChzdHIoaW1nX3BhdGgpKQogICAgICAgICAgICBpZiBub3Qg"
    "cHguaXNOdWxsKCk6CiAgICAgICAgICAgICAgICBzZWxmLl9jYWNoZVtlbW90aW9uXSA9IHB4CgogICAgICAgIGlmIHNlbGYuX2Nh"
    "Y2hlOgogICAgICAgICAgICBzZWxmLl9yZW5kZXIoIm5ldXRyYWwiKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2Ry"
    "YXdfcGxhY2Vob2xkZXIoKQoKICAgIGRlZiBfcmVuZGVyKHNlbGYsIGZhY2U6IHN0cikgLT4gTm9uZToKICAgICAgICBmYWNlID0g"
    "ZmFjZS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl9jYWNoZToKICAgICAgICAgICAgaWYgZmFj"
    "ZSBub3QgaW4gc2VsZi5fd2FybmVkIGFuZCBmYWNlICE9ICJuZXV0cmFsIjoKICAgICAgICAgICAgICAgIHByaW50KGYiW01JUlJP"
    "Ul1bV0FSTl0gRmFjZSBub3QgaW4gY2FjaGU6IHtmYWNlfSDigJQgdXNpbmcgbmV1dHJhbCIpCiAgICAgICAgICAgICAgICBzZWxm"
    "Ll93YXJuZWQuYWRkKGZhY2UpCiAgICAgICAgICAgIGZhY2UgPSAibmV1dHJhbCIKICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxm"
    "Ll9jYWNoZToKICAgICAgICAgICAgc2VsZi5fZHJhd19wbGFjZWhvbGRlcigpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNl"
    "bGYuX2N1cnJlbnQgPSBmYWNlCiAgICAgICAgcHggPSBzZWxmLl9jYWNoZVtmYWNlXQogICAgICAgIHNjYWxlZCA9IHB4LnNjYWxl"
    "ZCgKICAgICAgICAgICAgc2VsZi53aWR0aCgpIC0gNCwKICAgICAgICAgICAgc2VsZi5oZWlnaHQoKSAtIDQsCiAgICAgICAgICAg"
    "IFF0LkFzcGVjdFJhdGlvTW9kZS5LZWVwQXNwZWN0UmF0aW8sCiAgICAgICAgICAgIFF0LlRyYW5zZm9ybWF0aW9uTW9kZS5TbW9v"
    "dGhUcmFuc2Zvcm1hdGlvbiwKICAgICAgICApCiAgICAgICAgc2VsZi5zZXRQaXhtYXAoc2NhbGVkKQogICAgICAgIHNlbGYuc2V0"
    "VGV4dCgiIikKCiAgICBkZWYgX2RyYXdfcGxhY2Vob2xkZXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLmNsZWFyKCkKICAg"
    "ICAgICBzZWxmLnNldFRleHQoIuKcplxu4p2nXG7inKYiKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJj"
    "b2xvcjoge0NfQ1JJTVNPTl9ESU19OyBmb250LXNpemU6IDI0cHg7IGJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQoKICAg"
    "IGRlZiBzZXRfZmFjZShzZWxmLCBmYWNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMCwgbGFtYmRh"
    "OiBzZWxmLl9yZW5kZXIoZmFjZSkpCgogICAgZGVmIHJlc2l6ZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHN1"
    "cGVyKCkucmVzaXplRXZlbnQoZXZlbnQpCiAgICAgICAgaWYgc2VsZi5fY2FjaGU6CiAgICAgICAgICAgIHNlbGYuX3JlbmRlcihz"
    "ZWxmLl9jdXJyZW50KQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGN1cnJlbnRfZmFjZShzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0"
    "dXJuIHNlbGYuX2N1cnJlbnQKCgojIOKUgOKUgCBWQU1QSVJFIFNUQVRFIFNUUklQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBDeWNs"
    "ZVdpZGdldChNb29uV2lkZ2V0KToKICAgICIiIkdlbmVyaWMgY3ljbGUgdmlzdWFsaXphdGlvbiB3aWRnZXQgKGN1cnJlbnRseSBs"
    "dW5hci1waGFzZSBkcml2ZW4pLiIiIgoKCmNsYXNzIFZhbXBpcmVTdGF0ZVN0cmlwKFFXaWRnZXQpOgogICAgIiIiCiAgICBGdWxs"
    "LXdpZHRoIHN0YXR1cyBiYXIgc2hvd2luZzoKICAgICAgWyDinKYgVkFNUElSRV9TVEFURSAg4oCiICBISDpNTSAg4oCiICDimIAg"
    "U1VOUklTRSAg4pi9IFNVTlNFVCAg4oCiICBNT09OIFBIQVNFICBJTExVTSUgXQogICAgQWx3YXlzIHZpc2libGUsIG5ldmVyIGNv"
    "bGxhcHNlcy4KICAgIFVwZGF0ZXMgZXZlcnkgbWludXRlIHZpYSBleHRlcm5hbCBRVGltZXIgY2FsbCB0byByZWZyZXNoKCkuCiAg"
    "ICBDb2xvci1jb2RlZCBieSBjdXJyZW50IHZhbXBpcmUgc3RhdGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFy"
    "ZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2xhYmVsX3ByZWZpeCA9ICJT"
    "VEFURSIKICAgICAgICBzZWxmLl9zdGF0ZSAgICAgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAgICAgc2VsZi5fdGltZV9zdHIg"
    "ID0gIiIKICAgICAgICBzZWxmLl9zdW5yaXNlICAgPSAiMDY6MDAiCiAgICAgICAgc2VsZi5fc3Vuc2V0ICAgID0gIjE4OjMwIgog"
    "ICAgICAgIHNlbGYuX3N1bl9kYXRlICA9IE5vbmUKICAgICAgICBzZWxmLl9tb29uX25hbWUgPSAiTkVXIE1PT04iCiAgICAgICAg"
    "c2VsZi5faWxsdW0gICAgID0gMC4wCiAgICAgICAgc2VsZi5zZXRGaXhlZEhlaWdodCgyOCkKICAgICAgICBzZWxmLnNldFN0eWxl"
    "U2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXItdG9wOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIpCiAgICAg"
    "ICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBzZXRfbGFiZWwoc2VsZiwg"
    "bGFiZWw6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9sYWJlbF9wcmVmaXggPSAobGFiZWwgb3IgIlNUQVRFIikuc3RyaXAo"
    "KS51cHBlcigpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBfZmV0Y2hfc3VuX2FzeW5jKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgZGVmIF9mKCk6CiAgICAgICAgICAgIHNyLCBzcyA9IGdldF9zdW5fdGltZXMoKQogICAgICAgICAgICBzZWxmLl9zdW5y"
    "aXNlID0gc3IKICAgICAgICAgICAgc2VsZi5fc3Vuc2V0ICA9IHNzCiAgICAgICAgICAgIHNlbGYuX3N1bl9kYXRlID0gZGF0ZXRp"
    "bWUubm93KCkuYXN0aW1lem9uZSgpLmRhdGUoKQogICAgICAgICAgICAjIFNjaGVkdWxlIHJlcGFpbnQgb24gbWFpbiB0aHJlYWQg"
    "4oCUIG5ldmVyIGNhbGwgdXBkYXRlKCkgZnJvbQogICAgICAgICAgICAjIGEgYmFja2dyb3VuZCB0aHJlYWQsIGl0IGNhdXNlcyBR"
    "VGhyZWFkIGNyYXNoIG9uIHN0YXJ0dXAKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMCwgc2VsZi51cGRhdGUpCiAgICAg"
    "ICAgdGhyZWFkaW5nLlRocmVhZCh0YXJnZXQ9X2YsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAgZGVmIHJlZnJlc2goc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9zdGF0ZSAgICAgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAgICAgc2VsZi5fdGltZV9z"
    "dHIgID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLnN0cmZ0aW1lKCIlWCIpCiAgICAgICAgdG9kYXkgPSBkYXRldGltZS5u"
    "b3coKS5hc3RpbWV6b25lKCkuZGF0ZSgpCiAgICAgICAgaWYgc2VsZi5fc3VuX2RhdGUgIT0gdG9kYXk6CiAgICAgICAgICAgIHNl"
    "bGYuX2ZldGNoX3N1bl9hc3luYygpCiAgICAgICAgXywgc2VsZi5fbW9vbl9uYW1lLCBzZWxmLl9pbGx1bSA9IGdldF9tb29uX3Bo"
    "YXNlKCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAg"
    "ICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFz"
    "aW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3"
    "LCBoLCBRQ29sb3IoQ19CRzIpKQoKICAgICAgICBzdGF0ZV9jb2xvciA9IGdldF92YW1waXJlX3N0YXRlX2NvbG9yKHNlbGYuX3N0"
    "YXRlKQogICAgICAgIHRleHQgPSAoCiAgICAgICAgICAgIGYi4pymICB7c2VsZi5fbGFiZWxfcHJlZml4fToge3NlbGYuX3N0YXRl"
    "fSAg4oCiICB7c2VsZi5fdGltZV9zdHJ9ICDigKIgICIKICAgICAgICAgICAgZiLimIAge3NlbGYuX3N1bnJpc2V9ICAgIOKYvSB7"
    "c2VsZi5fc3Vuc2V0fSAg4oCiICAiCiAgICAgICAgICAgIGYie3NlbGYuX21vb25fbmFtZX0gIHtzZWxmLl9pbGx1bTouMGZ9JSIK"
    "ICAgICAgICApCgogICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDksIFFGb250LldlaWdodC5Cb2xkKSkKICAgICAg"
    "ICBwLnNldFBlbihRQ29sb3Ioc3RhdGVfY29sb3IpKQogICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgdHcgPSBm"
    "bS5ob3Jpem9udGFsQWR2YW5jZSh0ZXh0KQogICAgICAgIHAuZHJhd1RleHQoKHcgLSB0dykgLy8gMiwgaCAtIDcsIHRleHQpCgog"
    "ICAgICAgIHAuZW5kKCkKCgpjbGFzcyBNaW5pQ2FsZW5kYXJXaWRnZXQoUVdpZGdldCk6CiAgICBkZWYgX19pbml0X18oc2VsZiwg"
    "cGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0"
    "KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFj"
    "aW5nKDQpCgogICAgICAgIGhlYWRlciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBoZWFkZXIuc2V0Q29udGVudHNNYXJnaW5zKDAs"
    "IDAsIDAsIDApCiAgICAgICAgc2VsZi5wcmV2X2J0biA9IFFQdXNoQnV0dG9uKCI8PCIpCiAgICAgICAgc2VsZi5uZXh0X2J0biA9"
    "IFFQdXNoQnV0dG9uKCI+PiIpCiAgICAgICAgc2VsZi5tb250aF9sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5tb250aF9s"
    "Ymwuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgZm9yIGJ0biBpbiAoc2VsZi5wcmV2"
    "X2J0biwgc2VsZi5uZXh0X2J0bik6CiAgICAgICAgICAgIGJ0bi5zZXRGaXhlZFdpZHRoKDM0KQogICAgICAgICAgICBidG4uc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyBib3JkZXI6"
    "IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiAxMHB4OyBmb250LXdlaWdo"
    "dDogYm9sZDsgcGFkZGluZzogMnB4OyIKICAgICAgICAgICAgKQogICAgICAgIHNlbGYubW9udGhfbGJsLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBib3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBweDsgZm9udC13ZWlnaHQ6"
    "IGJvbGQ7IgogICAgICAgICkKICAgICAgICBoZWFkZXIuYWRkV2lkZ2V0KHNlbGYucHJldl9idG4pCiAgICAgICAgaGVhZGVyLmFk"
    "ZFdpZGdldChzZWxmLm1vbnRoX2xibCwgMSkKICAgICAgICBoZWFkZXIuYWRkV2lkZ2V0KHNlbGYubmV4dF9idG4pCiAgICAgICAg"
    "bGF5b3V0LmFkZExheW91dChoZWFkZXIpCgogICAgICAgIHNlbGYuY2FsZW5kYXIgPSBRQ2FsZW5kYXJXaWRnZXQoKQogICAgICAg"
    "IHNlbGYuY2FsZW5kYXIuc2V0R3JpZFZpc2libGUoVHJ1ZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFZlcnRpY2FsSGVhZGVy"
    "Rm9ybWF0KFFDYWxlbmRhcldpZGdldC5WZXJ0aWNhbEhlYWRlckZvcm1hdC5Ob1ZlcnRpY2FsSGVhZGVyKQogICAgICAgIHNlbGYu"
    "Y2FsZW5kYXIuc2V0TmF2aWdhdGlvbkJhclZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmIlFDYWxlbmRhcldpZGdldCBRV2lkZ2V0e3thbHRlcm5hdGUtYmFja2dyb3VuZC1jb2xvcjp7Q19CRzJ9"
    "O319ICIKICAgICAgICAgICAgZiJRVG9vbEJ1dHRvbnt7Y29sb3I6e0NfR09MRH07fX0gIgogICAgICAgICAgICBmIlFDYWxlbmRh"
    "cldpZGdldCBRQWJzdHJhY3RJdGVtVmlldzplbmFibGVke3tiYWNrZ3JvdW5kOntDX0JHMn07IGNvbG9yOiNmZmZmZmY7ICIKICAg"
    "ICAgICAgICAgZiJzZWxlY3Rpb24tYmFja2dyb3VuZC1jb2xvcjp7Q19DUklNU09OX0RJTX07IHNlbGVjdGlvbi1jb2xvcjp7Q19U"
    "RVhUfTsgZ3JpZGxpbmUtY29sb3I6e0NfQk9SREVSfTt9fSAiCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFBYnN0cmFj"
    "dEl0ZW1WaWV3OmRpc2FibGVke3tjb2xvcjojOGI5NWExO319IgogICAgICAgICkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNl"
    "bGYuY2FsZW5kYXIpCgogICAgICAgIHNlbGYucHJldl9idG4uY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5jYWxlbmRhci5z"
    "aG93UHJldmlvdXNNb250aCgpKQogICAgICAgIHNlbGYubmV4dF9idG4uY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5jYWxl"
    "bmRhci5zaG93TmV4dE1vbnRoKCkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5jdXJyZW50UGFnZUNoYW5nZWQuY29ubmVjdChzZWxm"
    "Ll91cGRhdGVfbGFiZWwpCiAgICAgICAgc2VsZi5fdXBkYXRlX2xhYmVsKCkKICAgICAgICBzZWxmLl9hcHBseV9mb3JtYXRzKCkK"
    "CiAgICBkZWYgX3VwZGF0ZV9sYWJlbChzZWxmLCAqYXJncyk6CiAgICAgICAgeWVhciA9IHNlbGYuY2FsZW5kYXIueWVhclNob3du"
    "KCkKICAgICAgICBtb250aCA9IHNlbGYuY2FsZW5kYXIubW9udGhTaG93bigpCiAgICAgICAgc2VsZi5tb250aF9sYmwuc2V0VGV4"
    "dChmIntkYXRlKHllYXIsIG1vbnRoLCAxKS5zdHJmdGltZSgnJUIgJVknKX0iKQogICAgICAgIHNlbGYuX2FwcGx5X2Zvcm1hdHMo"
    "KQoKICAgIGRlZiBfYXBwbHlfZm9ybWF0cyhzZWxmKToKICAgICAgICBiYXNlID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICBi"
    "YXNlLnNldEZvcmVncm91bmQoUUNvbG9yKCIjZTdlZGYzIikpCiAgICAgICAgc2F0dXJkYXkgPSBRVGV4dENoYXJGb3JtYXQoKQog"
    "ICAgICAgIHNhdHVyZGF5LnNldEZvcmVncm91bmQoUUNvbG9yKENfR09MRF9ESU0pKQogICAgICAgIHN1bmRheSA9IFFUZXh0Q2hh"
    "ckZvcm1hdCgpCiAgICAgICAgc3VuZGF5LnNldEZvcmVncm91bmQoUUNvbG9yKENfQkxPT0QpKQogICAgICAgIHNlbGYuY2FsZW5k"
    "YXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLk1vbmRheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNl"
    "dFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5UdWVzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vl"
    "a2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLldlZG5lc2RheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtk"
    "YXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5UaHVyc2RheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlU"
    "ZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5GcmlkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZv"
    "cm1hdChRdC5EYXlPZldlZWsuU2F0dXJkYXksIHNhdHVyZGF5KQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRG"
    "b3JtYXQoUXQuRGF5T2ZXZWVrLlN1bmRheSwgc3VuZGF5KQoKICAgICAgICB5ZWFyID0gc2VsZi5jYWxlbmRhci55ZWFyU2hvd24o"
    "KQogICAgICAgIG1vbnRoID0gc2VsZi5jYWxlbmRhci5tb250aFNob3duKCkKICAgICAgICBmaXJzdF9kYXkgPSBRRGF0ZSh5ZWFy"
    "LCBtb250aCwgMSkKICAgICAgICBmb3IgZGF5IGluIHJhbmdlKDEsIGZpcnN0X2RheS5kYXlzSW5Nb250aCgpICsgMSk6CiAgICAg"
    "ICAgICAgIGQgPSBRRGF0ZSh5ZWFyLCBtb250aCwgZGF5KQogICAgICAgICAgICBmbXQgPSBRVGV4dENoYXJGb3JtYXQoKQogICAg"
    "ICAgICAgICB3ZWVrZGF5ID0gZC5kYXlPZldlZWsoKQogICAgICAgICAgICBpZiB3ZWVrZGF5ID09IFF0LkRheU9mV2Vlay5TYXR1"
    "cmRheS52YWx1ZToKICAgICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0dPTERfRElNKSkKICAgICAgICAg"
    "ICAgZWxpZiB3ZWVrZGF5ID09IFF0LkRheU9mV2Vlay5TdW5kYXkudmFsdWU6CiAgICAgICAgICAgICAgICBmbXQuc2V0Rm9yZWdy"
    "b3VuZChRQ29sb3IoQ19CTE9PRCkpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBmbXQuc2V0Rm9yZWdyb3VuZChR"
    "Q29sb3IoIiNlN2VkZjMiKSkKICAgICAgICAgICAgc2VsZi5jYWxlbmRhci5zZXREYXRlVGV4dEZvcm1hdChkLCBmbXQpCgogICAg"
    "ICAgIHRvZGF5X2ZtdCA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgdG9kYXlfZm10LnNldEZvcmVncm91bmQoUUNvbG9yKCIj"
    "NjhkMzlhIikpCiAgICAgICAgdG9kYXlfZm10LnNldEJhY2tncm91bmQoUUNvbG9yKCIjMTYzODI1IikpCiAgICAgICAgdG9kYXlf"
    "Zm10LnNldEZvbnRXZWlnaHQoUUZvbnQuV2VpZ2h0LkJvbGQpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXREYXRlVGV4dEZvcm1h"
    "dChRRGF0ZS5jdXJyZW50RGF0ZSgpLCB0b2RheV9mbXQpCgoKIyDilIDilIAgQ09MTEFQU0lCTEUgQkxPQ0sg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACmNsYXNzIENvbGxhcHNpYmxlQmxvY2soUVdpZGdldCk6CiAgICAiIiIKICAgIFdyYXBwZXIgdGhhdCBhZGRzIGEg"
    "Y29sbGFwc2UvZXhwYW5kIHRvZ2dsZSB0byBhbnkgd2lkZ2V0LgogICAgQ29sbGFwc2VzIGhvcml6b250YWxseSAocmlnaHR3YXJk"
    "KSDigJQgaGlkZXMgY29udGVudCwga2VlcHMgaGVhZGVyIHN0cmlwLgogICAgSGVhZGVyIHNob3dzIGxhYmVsLiBUb2dnbGUgYnV0"
    "dG9uIG9uIHJpZ2h0IGVkZ2Ugb2YgaGVhZGVyLgoKICAgIFVzYWdlOgogICAgICAgIGJsb2NrID0gQ29sbGFwc2libGVCbG9jaygi"
    "4p2nIEJMT09EIiwgU3BoZXJlV2lkZ2V0KC4uLikpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChibG9jaykKICAgICIiIgoKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmLCBsYWJlbDogc3RyLCBjb250ZW50OiBRV2lkZ2V0LAogICAgICAgICAgICAgICAgIGV4cGFuZGVk"
    "OiBib29sID0gVHJ1ZSwgbWluX3dpZHRoOiBpbnQgPSA5MCwKICAgICAgICAgICAgICAgICByZXNlcnZlX3dpZHRoOiBib29sID0g"
    "RmFsc2UsCiAgICAgICAgICAgICAgICAgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAg"
    "ICAgIHNlbGYuX2V4cGFuZGVkICAgICAgID0gZXhwYW5kZWQKICAgICAgICBzZWxmLl9taW5fd2lkdGggICAgICA9IG1pbl93aWR0"
    "aAogICAgICAgIHNlbGYuX3Jlc2VydmVfd2lkdGggID0gcmVzZXJ2ZV93aWR0aAogICAgICAgIHNlbGYuX2NvbnRlbnQgICAgICAg"
    "ID0gY29udGVudAoKICAgICAgICBtYWluID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBtYWluLnNldENvbnRlbnRzTWFyZ2lu"
    "cygwLCAwLCAwLCAwKQogICAgICAgIG1haW4uc2V0U3BhY2luZygwKQoKICAgICAgICAjIEhlYWRlcgogICAgICAgIHNlbGYuX2hl"
    "YWRlciA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2hlYWRlci5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBzZWxmLl9oZWFk"
    "ZXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXItYm90dG9tOiAxcHggc29s"
    "aWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXRvcDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsi"
    "CiAgICAgICAgKQogICAgICAgIGhsID0gUUhCb3hMYXlvdXQoc2VsZi5faGVhZGVyKQogICAgICAgIGhsLnNldENvbnRlbnRzTWFy"
    "Z2lucyg2LCAwLCA0LCAwKQogICAgICAgIGhsLnNldFNwYWNpbmcoNCkKCiAgICAgICAgc2VsZi5fbGJsID0gUUxhYmVsKGxhYmVs"
    "KQogICAgICAgIHNlbGYuX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXpl"
    "OiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsg"
    "bGV0dGVyLXNwYWNpbmc6IDFweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCgogICAgICAgIHNlbGYuX2J0biA9IFFUb29sQnV0"
    "dG9uKCkKICAgICAgICBzZWxmLl9idG4uc2V0Rml4ZWRTaXplKDE2LCAxNikKICAgICAgICBzZWxmLl9idG4uc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB0cmFuc3BhcmVudDsgY29sb3I6IHtDX0dPTERfRElNfTsgYm9yZGVyOiBub25l"
    "OyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl9idG4uc2V0VGV4dCgiPCIpCiAgICAgICAgc2VsZi5f"
    "YnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCgogICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl9sYmwpCiAgICAgICAg"
    "aGwuYWRkU3RyZXRjaCgpCiAgICAgICAgaGwuYWRkV2lkZ2V0KHNlbGYuX2J0bikKCiAgICAgICAgbWFpbi5hZGRXaWRnZXQoc2Vs"
    "Zi5faGVhZGVyKQogICAgICAgIG1haW4uYWRkV2lkZ2V0KHNlbGYuX2NvbnRlbnQpCgogICAgICAgIHNlbGYuX2FwcGx5X3N0YXRl"
    "KCkKCiAgICBkZWYgX3RvZ2dsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFu"
    "ZGVkCiAgICAgICAgc2VsZi5fYXBwbHlfc3RhdGUoKQoKICAgIGRlZiBfYXBwbHlfc3RhdGUoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBzZWxmLl9jb250ZW50LnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCiAgICAgICAgc2VsZi5fYnRuLnNldFRleHQoIjwiIGlm"
    "IHNlbGYuX2V4cGFuZGVkIGVsc2UgIj4iKQoKICAgICAgICAjIFJlc2VydmUgZml4ZWQgc2xvdCB3aWR0aCB3aGVuIHJlcXVlc3Rl"
    "ZCAodXNlZCBieSBtaWRkbGUgbG93ZXIgYmxvY2spCiAgICAgICAgaWYgc2VsZi5fcmVzZXJ2ZV93aWR0aDoKICAgICAgICAgICAg"
    "c2VsZi5zZXRNaW5pbXVtV2lkdGgoc2VsZi5fbWluX3dpZHRoKQogICAgICAgICAgICBzZWxmLnNldE1heGltdW1XaWR0aCgxNjc3"
    "NzIxNSkKICAgICAgICBlbGlmIHNlbGYuX2V4cGFuZGVkOgogICAgICAgICAgICBzZWxmLnNldE1pbmltdW1XaWR0aChzZWxmLl9t"
    "aW5fd2lkdGgpCiAgICAgICAgICAgIHNlbGYuc2V0TWF4aW11bVdpZHRoKDE2Nzc3MjE1KSAgIyB1bmNvbnN0cmFpbmVkCiAgICAg"
    "ICAgZWxzZToKICAgICAgICAgICAgIyBDb2xsYXBzZWQ6IGp1c3QgdGhlIGhlYWRlciBzdHJpcCAobGFiZWwgKyBidXR0b24pCiAg"
    "ICAgICAgICAgIGNvbGxhcHNlZF93ID0gc2VsZi5faGVhZGVyLnNpemVIaW50KCkud2lkdGgoKQogICAgICAgICAgICBzZWxmLnNl"
    "dEZpeGVkV2lkdGgobWF4KDYwLCBjb2xsYXBzZWRfdykpCgogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0cnkoKQogICAgICAgIHBh"
    "cmVudCA9IHNlbGYucGFyZW50V2lkZ2V0KCkKICAgICAgICBpZiBwYXJlbnQgYW5kIHBhcmVudC5sYXlvdXQoKToKICAgICAgICAg"
    "ICAgcGFyZW50LmxheW91dCgpLmFjdGl2YXRlKCkKCgojIOKUgOKUgCBIQVJEV0FSRSBQQU5FTCDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgSGFyZHdhcmVQYW5lbChRV2lkZ2V0KToKICAgICIiIgogICAgVGhlIHN5c3RlbXMgcmlnaHQgcGFu"
    "ZWwgY29udGVudHMuCiAgICBHcm91cHM6IHN0YXR1cyBpbmZvLCBkcml2ZSBiYXJzLCBDUFUvUkFNIGdhdWdlcywgR1BVL1ZSQU0g"
    "Z2F1Z2VzLCBHUFUgdGVtcC4KICAgIFJlcG9ydHMgaGFyZHdhcmUgYXZhaWxhYmlsaXR5IGluIERpYWdub3N0aWNzIG9uIHN0YXJ0"
    "dXAuCiAgICBTaG93cyBOL0EgZ3JhY2VmdWxseSB3aGVuIGRhdGEgdW5hdmFpbGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0"
    "X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3NldHVw"
    "X3VpKCkKICAgICAgICBzZWxmLl9kZXRlY3RfaGFyZHdhcmUoKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBsYXlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwg"
    "NCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICBkZWYgc2VjdGlvbl9sYWJlbCh0ZXh0OiBzdHIpIC0+IFFM"
    "YWJlbDoKICAgICAgICAgICAgbGJsID0gUUxhYmVsKHRleHQpCiAgICAgICAgICAgIGxibC5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogOXB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyAiCiAgICAgICAg"
    "ICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtd2VpZ2h0OiBib2xkOyIKICAgICAgICAgICAg"
    "KQogICAgICAgICAgICByZXR1cm4gbGJsCgogICAgICAgICMg4pSA4pSAIFN0YXR1cyBibG9jayDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rp"
    "b25fbGFiZWwoIuKdpyBTVEFUVVMiKSkKICAgICAgICBzdGF0dXNfZnJhbWUgPSBRRnJhbWUoKQogICAgICAgIHN0YXR1c19mcmFt"
    "ZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX1BBTkVMfTsgYm9yZGVyOiAxcHggc29saWQge0Nf"
    "Qk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCiAgICAgICAgc3RhdHVzX2ZyYW1lLnNldEZpeGVkSGVpZ2h0"
    "KDg4KQogICAgICAgIHNmID0gUVZCb3hMYXlvdXQoc3RhdHVzX2ZyYW1lKQogICAgICAgIHNmLnNldENvbnRlbnRzTWFyZ2lucyg4"
    "LCA0LCA4LCA0KQogICAgICAgIHNmLnNldFNwYWNpbmcoMikKCiAgICAgICAgc2VsZi5sYmxfc3RhdHVzICA9IFFMYWJlbCgi4pym"
    "IFNUQVRVUzogT0ZGTElORSIpCiAgICAgICAgc2VsZi5sYmxfbW9kZWwgICA9IFFMYWJlbCgi4pymIFZFU1NFTDogTE9BRElORy4u"
    "LiIpCiAgICAgICAgc2VsZi5sYmxfc2Vzc2lvbiA9IFFMYWJlbCgi4pymIFNFU1NJT046IDAwOjAwOjAwIikKICAgICAgICBzZWxm"
    "LmxibF90b2tlbnMgID0gUUxhYmVsKCLinKYgVE9LRU5TOiAwIikKCiAgICAgICAgZm9yIGxibCBpbiAoc2VsZi5sYmxfc3RhdHVz"
    "LCBzZWxmLmxibF9tb2RlbCwKICAgICAgICAgICAgICAgICAgICBzZWxmLmxibF9zZXNzaW9uLCBzZWxmLmxibF90b2tlbnMpOgog"
    "ICAgICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1z"
    "aXplOiAxMHB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGJvcmRlcjogbm9u"
    "ZTsiCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2YuYWRkV2lkZ2V0KGxibCkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChz"
    "dGF0dXNfZnJhbWUpCgogICAgICAgICMg4pSA4pSAIERyaXZlIGJhcnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVs"
    "KCLinacgU1RPUkFHRSIpKQogICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0ID0gRHJpdmVXaWRnZXQoKQogICAgICAgIGxheW91dC5h"
    "ZGRXaWRnZXQoc2VsZi5kcml2ZV93aWRnZXQpCgogICAgICAgICMg4pSA4pSAIENQVSAvIFJBTSBnYXVnZXMg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xh"
    "YmVsKCLinacgVklUQUwgRVNTRU5DRSIpKQogICAgICAgIHJhbV9jcHUgPSBRR3JpZExheW91dCgpCiAgICAgICAgcmFtX2NwdS5z"
    "ZXRTcGFjaW5nKDMpCgogICAgICAgIHNlbGYuZ2F1Z2VfY3B1ICA9IEdhdWdlV2lkZ2V0KCJDUFUiLCAgIiUiLCAgIDEwMC4wLCBD"
    "X1NJTFZFUikKICAgICAgICBzZWxmLmdhdWdlX3JhbSAgPSBHYXVnZVdpZGdldCgiUkFNIiwgICJHQiIsICAgNjQuMCwgQ19HT0xE"
    "X0RJTSkKICAgICAgICByYW1fY3B1LmFkZFdpZGdldChzZWxmLmdhdWdlX2NwdSwgMCwgMCkKICAgICAgICByYW1fY3B1LmFkZFdp"
    "ZGdldChzZWxmLmdhdWdlX3JhbSwgMCwgMSkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KHJhbV9jcHUpCgogICAgICAgICMg4pSA"
    "4pSAIEdQVSAvIFZSQU0gZ2F1Z2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIEFSQ0FORSBQT1dFUiIpKQogICAgICAgIGdwdV92cmFtID0g"
    "UUdyaWRMYXlvdXQoKQogICAgICAgIGdwdV92cmFtLnNldFNwYWNpbmcoMykKCiAgICAgICAgc2VsZi5nYXVnZV9ncHUgID0gR2F1"
    "Z2VXaWRnZXQoIkdQVSIsICAiJSIsICAgMTAwLjAsIENfUFVSUExFKQogICAgICAgIHNlbGYuZ2F1Z2VfdnJhbSA9IEdhdWdlV2lk"
    "Z2V0KCJWUkFNIiwgIkdCIiwgICAgOC4wLCBDX0NSSU1TT04pCiAgICAgICAgZ3B1X3ZyYW0uYWRkV2lkZ2V0KHNlbGYuZ2F1Z2Vf"
    "Z3B1LCAgMCwgMCkKICAgICAgICBncHVfdnJhbS5hZGRXaWRnZXQoc2VsZi5nYXVnZV92cmFtLCAwLCAxKQogICAgICAgIGxheW91"
    "dC5hZGRMYXlvdXQoZ3B1X3ZyYW0pCgogICAgICAgICMg4pSA4pSAIEdQVSBUZW1wIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQo"
    "c2VjdGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEhFQVQiKSkKICAgICAgICBzZWxmLmdhdWdlX3RlbXAgPSBHYXVnZVdpZGdldCgi"
    "R1BVIFRFTVAiLCAiwrBDIiwgOTUuMCwgQ19CTE9PRCkKICAgICAgICBzZWxmLmdhdWdlX3RlbXAuc2V0TWF4aW11bUhlaWdodCg2"
    "NSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfdGVtcCkKCiAgICAgICAgIyDilIDilIAgR1BVIG1hc3RlciBi"
    "YXIgKGZ1bGwgd2lkdGgpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi"
    "4p2nIElORkVSTkFMIEVOR0lORSIpKQogICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3RlciA9IEdhdWdlV2lkZ2V0KCJSVFgiLCAi"
    "JSIsIDEwMC4wLCBDX0NSSU1TT04pCiAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldE1heGltdW1IZWlnaHQoNTUpCiAg"
    "ICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmdhdWdlX2dwdV9tYXN0ZXIpCgogICAgICAgIGxheW91dC5hZGRTdHJldGNoKCkK"
    "CiAgICBkZWYgX2RldGVjdF9oYXJkd2FyZShzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENoZWNrIHdoYXQgaGFy"
    "ZHdhcmUgbW9uaXRvcmluZyBpcyBhdmFpbGFibGUuCiAgICAgICAgTWFyayB1bmF2YWlsYWJsZSBnYXVnZXMgYXBwcm9wcmlhdGVs"
    "eS4KICAgICAgICBEaWFnbm9zdGljIG1lc3NhZ2VzIGNvbGxlY3RlZCBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgICAgICAi"
    "IiIKICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzOiBsaXN0W3N0cl0gPSBbXQoKICAgICAgICBpZiBub3QgUFNVVElMX09LOgog"
    "ICAgICAgICAgICBzZWxmLmdhdWdlX2NwdS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFVu"
    "YXZhaWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAiW0hBUkRX"
    "QVJFXSBwc3V0aWwgbm90IGF2YWlsYWJsZSDigJQgQ1BVL1JBTSBnYXVnZXMgZGlzYWJsZWQuICIKICAgICAgICAgICAgICAgICJw"
    "aXAgaW5zdGFsbCBwc3V0aWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYu"
    "X2RpYWdfbWVzc2FnZXMuYXBwZW5kKCJbSEFSRFdBUkVdIHBzdXRpbCBPSyDigJQgQ1BVL1JBTSBtb25pdG9yaW5nIGFjdGl2ZS4i"
    "KQoKICAgICAgICBpZiBub3QgTlZNTF9PSzoKICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHUuc2V0VW5hdmFpbGFibGUoKQogICAg"
    "ICAgICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX3RlbXAuc2V0VW5h"
    "dmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBz"
    "ZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICJbSEFSRFdBUkVdIHB5bnZtbCBub3QgYXZhaWxhYmxl"
    "IG9yIG5vIE5WSURJQSBHUFUgZGV0ZWN0ZWQg4oCUICIKICAgICAgICAgICAgICAgICJHUFUgZ2F1Z2VzIGRpc2FibGVkLiBwaXAg"
    "aW5zdGFsbCBweW52bWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdldE5hbWUoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIGlm"
    "IGlzaW5zdGFuY2UobmFtZSwgYnl0ZXMpOgogICAgICAgICAgICAgICAgICAgIG5hbWUgPSBuYW1lLmRlY29kZSgpCiAgICAgICAg"
    "ICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltIQVJEV0FSRV0gcHludm1s"
    "IE9LIOKAlCBHUFUgZGV0ZWN0ZWQ6IHtuYW1lfSIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICMgVXBkYXRlIG1h"
    "eCBWUkFNIGZyb20gYWN0dWFsIGhhcmR3YXJlCiAgICAgICAgICAgICAgICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9y"
    "eUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIHRvdGFsX2diID0gbWVtLnRvdGFsIC8gMTAyNCoqMwogICAgICAgICAg"
    "ICAgICAgc2VsZi5nYXVnZV92cmFtLm1heF92YWwgPSB0b3RhbF9nYgogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6"
    "CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZChmIltIQVJEV0FSRV0gcHludm1sIGVycm9yOiB7ZX0i"
    "KQoKICAgIGRlZiB1cGRhdGVfc3RhdHMoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBDYWxsZWQgZXZlcnkgc2Vj"
    "b25kIGZyb20gdGhlIHN0YXRzIFFUaW1lci4KICAgICAgICBSZWFkcyBoYXJkd2FyZSBhbmQgdXBkYXRlcyBhbGwgZ2F1Z2VzLgog"
    "ICAgICAgICIiIgogICAgICAgIGlmIFBTVVRJTF9PSzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY3B1ID0gcHN1"
    "dGlsLmNwdV9wZXJjZW50KCkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfY3B1LnNldFZhbHVlKGNwdSwgZiJ7Y3B1Oi4wZn0l"
    "IiwgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICAgICAgICAgbWVtID0gcHN1dGlsLnZpcnR1YWxfbWVtb3J5KCkKICAgICAgICAg"
    "ICAgICAgIHJ1ICA9IG1lbS51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHJ0ICA9IG1lbS50b3RhbCAvIDEwMjQqKjMK"
    "ICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFZhbHVlKHJ1LCBmIntydTouMWZ9L3tydDouMGZ9R0IiLAogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdl"
    "X3JhbS5tYXhfdmFsID0gcnQKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAg"
    "ICAgaWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgdXRpbCAgICAgPSBw"
    "eW52bWwubnZtbERldmljZUdldFV0aWxpemF0aW9uUmF0ZXMoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIG1lbV9pbmZvID0g"
    "cHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICB0ZW1wICAgICA9IHB5bnZt"
    "bC5udm1sRGV2aWNlR2V0VGVtcGVyYXR1cmUoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBncHVfaGFuZGxlLCBweW52"
    "bWwuTlZNTF9URU1QRVJBVFVSRV9HUFUpCgogICAgICAgICAgICAgICAgZ3B1X3BjdCAgID0gZmxvYXQodXRpbC5ncHUpCiAgICAg"
    "ICAgICAgICAgICB2cmFtX3VzZWQgPSBtZW1faW5mby51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHZyYW1fdG90ICA9"
    "IG1lbV9pbmZvLnRvdGFsIC8gMTAyNCoqMwoKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1LnNldFZhbHVlKGdwdV9wY3Qs"
    "IGYie2dwdV9wY3Q6LjBmfSUiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUp"
    "CiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VmFsdWUodnJhbV91c2VkLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGYie3ZyYW1fdXNlZDouMWZ9L3t2cmFtX3RvdDouMGZ9R0IiLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV90ZW1wLnNldFZh"
    "bHVlKGZsb2F0KHRlbXApLCBmInt0ZW1wfcKwQyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZh"
    "aWxhYmxlPVRydWUpCgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERl"
    "dmljZUdldE5hbWUoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgICAgICBpZiBpc2luc3RhbmNlKG5hbWUsIGJ5dGVzKToKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgbmFtZSA9IG5hbWUuZGVjb2RlKCkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246"
    "CiAgICAgICAgICAgICAgICAgICAgbmFtZSA9ICJHUFUiCgogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNl"
    "dFZhbHVlKAogICAgICAgICAgICAgICAgICAgIGdwdV9wY3QsCiAgICAgICAgICAgICAgICAgICAgZiJ7bmFtZX0gIHtncHVfcGN0"
    "Oi4wZn0lICAiCiAgICAgICAgICAgICAgICAgICAgZiJbe3ZyYW1fdXNlZDouMWZ9L3t2cmFtX3RvdDouMGZ9R0IgVlJBTV0iLAog"
    "ICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFVwZGF0ZSBkcml2ZSBiYXJzIGV2ZXJ5IDMwIHNlY29uZHMg"
    "KG5vdCBldmVyeSB0aWNrKQogICAgICAgIGlmIG5vdCBoYXNhdHRyKHNlbGYsICJfZHJpdmVfdGljayIpOgogICAgICAgICAgICBz"
    "ZWxmLl9kcml2ZV90aWNrID0gMAogICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgKz0gMQogICAgICAgIGlmIHNlbGYuX2RyaXZlX3Rp"
    "Y2sgPj0gMzA6CiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgPSAwCiAgICAgICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0LnJl"
    "ZnJlc2goKQoKICAgIGRlZiBzZXRfc3RhdHVzX2xhYmVscyhzZWxmLCBzdGF0dXM6IHN0ciwgbW9kZWw6IHN0ciwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICBzZXNzaW9uOiBzdHIsIHRva2Vuczogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYubGJsX3N0YXR1"
    "cy5zZXRUZXh0KGYi4pymIFNUQVRVUzoge3N0YXR1c30iKQogICAgICAgIHNlbGYubGJsX21vZGVsLnNldFRleHQoZiLinKYgVkVT"
    "U0VMOiB7bW9kZWx9IikKICAgICAgICBzZWxmLmxibF9zZXNzaW9uLnNldFRleHQoZiLinKYgU0VTU0lPTjoge3Nlc3Npb259IikK"
    "ICAgICAgICBzZWxmLmxibF90b2tlbnMuc2V0VGV4dChmIuKcpiBUT0tFTlM6IHt0b2tlbnN9IikKCiAgICBkZWYgZ2V0X2RpYWdu"
    "b3N0aWNzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICByZXR1cm4gZ2V0YXR0cihzZWxmLCAiX2RpYWdfbWVzc2FnZXMiLCBb"
    "XSkKCgojIOKUgOKUgCBQQVNTIDIgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQWxsIHdpZGdldCBj"
    "bGFzc2VzIGRlZmluZWQuIFN5bnRheC1jaGVja2FibGUgaW5kZXBlbmRlbnRseS4KIyBOZXh0OiBQYXNzIDMg4oCUIFdvcmtlciBU"
    "aHJlYWRzCiMgKERvbHBoaW5Xb3JrZXIgd2l0aCBzdHJlYW1pbmcsIFNlbnRpbWVudFdvcmtlciwgSWRsZVdvcmtlciwgU291bmRX"
    "b3JrZXIpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDM6IFdPUktFUiBUSFJFQURTCiMKIyBXb3Jr"
    "ZXJzIGRlZmluZWQgaGVyZToKIyAgIExMTUFkYXB0b3IgKGJhc2UgKyBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IgKyBPbGxhbWFB"
    "ZGFwdG9yICsKIyAgICAgICAgICAgICAgIENsYXVkZUFkYXB0b3IgKyBPcGVuQUlBZGFwdG9yKQojICAgU3RyZWFtaW5nV29ya2Vy"
    "ICAg4oCUIG1haW4gZ2VuZXJhdGlvbiwgZW1pdHMgdG9rZW5zIG9uZSBhdCBhIHRpbWUKIyAgIFNlbnRpbWVudFdvcmtlciAgIOKA"
    "lCBjbGFzc2lmaWVzIGVtb3Rpb24gZnJvbSByZXNwb25zZSB0ZXh0CiMgICBJZGxlV29ya2VyICAgICAgICDigJQgdW5zb2xpY2l0"
    "ZWQgdHJhbnNtaXNzaW9ucyBkdXJpbmcgaWRsZQojICAgU291bmRXb3JrZXIgICAgICAg4oCUIHBsYXlzIHNvdW5kcyBvZmYgdGhl"
    "IG1haW4gdGhyZWFkCiMKIyBBTEwgZ2VuZXJhdGlvbiBpcyBzdHJlYW1pbmcuIE5vIGJsb2NraW5nIGNhbGxzIG9uIG1haW4gdGhy"
    "ZWFkLiBFdmVyLgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0IGFiYwppbXBvcnQganNvbgppbXBvcnQgdXJsbGliLnJlcXVlc3QKaW1w"
    "b3J0IHVybGxpYi5lcnJvcgppbXBvcnQgaHR0cC5jbGllbnQKZnJvbSB0eXBpbmcgaW1wb3J0IEl0ZXJhdG9yCgoKIyDilIDilIAg"
    "TExNIEFEQVBUT1IgQkFTRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTExNQWRhcHRvcihhYmMuQUJDKToKICAgICIiIgog"
    "ICAgQWJzdHJhY3QgYmFzZSBmb3IgYWxsIG1vZGVsIGJhY2tlbmRzLgogICAgVGhlIGRlY2sgY2FsbHMgc3RyZWFtKCkgb3IgZ2Vu"
    "ZXJhdGUoKSDigJQgbmV2ZXIga25vd3Mgd2hpY2ggYmFja2VuZCBpcyBhY3RpdmUuCiAgICAiIiIKCiAgICBAYWJjLmFic3RyYWN0"
    "bWV0aG9kCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgIiIiUmV0dXJuIFRydWUgaWYgdGhlIGJh"
    "Y2tlbmQgaXMgcmVhY2hhYmxlLiIiIgogICAgICAgIC4uLgoKICAgIEBhYmMuYWJzdHJhY3RtZXRob2QKICAgIGRlZiBzdHJlYW0o"
    "CiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBs"
    "aXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAg"
    "ICAgIiIiCiAgICAgICAgWWllbGQgcmVzcG9uc2UgdGV4dCB0b2tlbi1ieS10b2tlbiAob3IgY2h1bmstYnktY2h1bmsgZm9yIEFQ"
    "SSBiYWNrZW5kcykuCiAgICAgICAgTXVzdCBiZSBhIGdlbmVyYXRvci4gTmV2ZXIgYmxvY2sgZm9yIHRoZSBmdWxsIHJlc3BvbnNl"
    "IGJlZm9yZSB5aWVsZGluZy4KICAgICAgICAiIiIKICAgICAgICAuLi4KCiAgICBkZWYgZ2VuZXJhdGUoCiAgICAgICAgc2VsZiwK"
    "ICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAg"
    "ICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBDb252ZW5pZW5j"
    "ZSB3cmFwcGVyOiBjb2xsZWN0IGFsbCBzdHJlYW0gdG9rZW5zIGludG8gb25lIHN0cmluZy4KICAgICAgICBVc2VkIGZvciBzZW50"
    "aW1lbnQgY2xhc3NpZmljYXRpb24gKHNtYWxsIGJvdW5kZWQgY2FsbHMgb25seSkuCiAgICAgICAgIiIiCiAgICAgICAgcmV0dXJu"
    "ICIiLmpvaW4oc2VsZi5zdHJlYW0ocHJvbXB0LCBzeXN0ZW0sIGhpc3RvcnksIG1heF9uZXdfdG9rZW5zKSkKCiAgICBkZWYgYnVp"
    "bGRfY2hhdG1sX3Byb21wdChzZWxmLCBzeXN0ZW06IHN0ciwgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICB1c2VyX3RleHQ6IHN0ciA9ICIiKSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgQnVpbGQgYSBDaGF0TUwt"
    "Zm9ybWF0IHByb21wdCBzdHJpbmcgZm9yIGxvY2FsIG1vZGVscy4KICAgICAgICBoaXN0b3J5ID0gW3sicm9sZSI6ICJ1c2VyInwi"
    "YXNzaXN0YW50IiwgImNvbnRlbnQiOiAiLi4uIn1dCiAgICAgICAgIiIiCiAgICAgICAgcGFydHMgPSBbZiI8fGltX3N0YXJ0fD5z"
    "eXN0ZW1cbntzeXN0ZW19PHxpbV9lbmR8PiJdCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICByb2xlICAg"
    "ID0gbXNnLmdldCgicm9sZSIsICJ1c2VyIikKICAgICAgICAgICAgY29udGVudCA9IG1zZy5nZXQoImNvbnRlbnQiLCAiIikKICAg"
    "ICAgICAgICAgcGFydHMuYXBwZW5kKGYiPHxpbV9zdGFydHw+e3JvbGV9XG57Y29udGVudH08fGltX2VuZHw+IikKICAgICAgICBp"
    "ZiB1c2VyX3RleHQ6CiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChmIjx8aW1fc3RhcnR8PnVzZXJcbnt1c2VyX3RleHR9PHxpbV9l"
    "bmR8PiIpCiAgICAgICAgcGFydHMuYXBwZW5kKCI8fGltX3N0YXJ0fD5hc3Npc3RhbnRcbiIpCiAgICAgICAgcmV0dXJuICJcbiIu"
    "am9pbihwYXJ0cykKCgojIOKUgOKUgCBMT0NBTCBUUkFOU0ZPUk1FUlMgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9y"
    "KExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBMb2FkcyBhIEh1Z2dpbmdGYWNlIG1vZGVsIGZyb20gYSBsb2NhbCBmb2xkZXIuCiAg"
    "ICBTdHJlYW1pbmc6IHVzZXMgbW9kZWwuZ2VuZXJhdGUoKSB3aXRoIGEgY3VzdG9tIHN0cmVhbWVyIHRoYXQgeWllbGRzIHRva2Vu"
    "cy4KICAgIFJlcXVpcmVzOiB0b3JjaCwgdHJhbnNmb3JtZXJzCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbW9kZWxf"
    "cGF0aDogc3RyKToKICAgICAgICBzZWxmLl9wYXRoICAgICAgPSBtb2RlbF9wYXRoCiAgICAgICAgc2VsZi5fbW9kZWwgICAgID0g"
    "Tm9uZQogICAgICAgIHNlbGYuX3Rva2VuaXplciA9IE5vbmUKICAgICAgICBzZWxmLl9sb2FkZWQgICAgPSBGYWxzZQogICAgICAg"
    "IHNlbGYuX2Vycm9yICAgICA9ICIiCgogICAgZGVmIGxvYWQoc2VsZikgLT4gYm9vbDoKICAgICAgICAiIiIKICAgICAgICBMb2Fk"
    "IG1vZGVsIGFuZCB0b2tlbml6ZXIuIENhbGwgZnJvbSBhIGJhY2tncm91bmQgdGhyZWFkLgogICAgICAgIFJldHVybnMgVHJ1ZSBv"
    "biBzdWNjZXNzLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBUT1JDSF9PSzoKICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSAi"
    "dG9yY2gvdHJhbnNmb3JtZXJzIG5vdCBpbnN0YWxsZWQiCiAgICAgICAgICAgIHJldHVybiBGYWxzZQogICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgZnJvbSB0cmFuc2Zvcm1lcnMgaW1wb3J0IEF1dG9Nb2RlbEZvckNhdXNhbExNLCBBdXRvVG9rZW5pemVyCiAgICAg"
    "ICAgICAgIHNlbGYuX3Rva2VuaXplciA9IEF1dG9Ub2tlbml6ZXIuZnJvbV9wcmV0cmFpbmVkKHNlbGYuX3BhdGgpCiAgICAgICAg"
    "ICAgIHNlbGYuX21vZGVsID0gQXV0b01vZGVsRm9yQ2F1c2FsTE0uZnJvbV9wcmV0cmFpbmVkKAogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fcGF0aCwKICAgICAgICAgICAgICAgIHRvcmNoX2R0eXBlPXRvcmNoLmZsb2F0MTYsCiAgICAgICAgICAgICAgICBkZXZpY2Vf"
    "bWFwPSJhdXRvIiwKICAgICAgICAgICAgICAgIGxvd19jcHVfbWVtX3VzYWdlPVRydWUsCiAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgc2VsZi5fbG9hZGVkID0gVHJ1ZQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMg"
    "ZToKICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSBzdHIoZSkKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgQHByb3BlcnR5"
    "CiAgICBkZWYgZXJyb3Ioc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9lcnJvcgoKICAgIGRlZiBpc19jb25uZWN0"
    "ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZGVkCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxm"
    "LAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAg"
    "ICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAg"
    "ICBTdHJlYW1zIHRva2VucyB1c2luZyB0cmFuc2Zvcm1lcnMgVGV4dEl0ZXJhdG9yU3RyZWFtZXIuCiAgICAgICAgWWllbGRzIGRl"
    "Y29kZWQgdGV4dCBmcmFnbWVudHMgYXMgdGhleSBhcmUgZ2VuZXJhdGVkLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBzZWxm"
    "Ll9sb2FkZWQ6CiAgICAgICAgICAgIHlpZWxkICJbRVJST1I6IG1vZGVsIG5vdCBsb2FkZWRdIgogICAgICAgICAgICByZXR1cm4K"
    "CiAgICAgICAgdHJ5OgogICAgICAgICAgICBmcm9tIHRyYW5zZm9ybWVycyBpbXBvcnQgVGV4dEl0ZXJhdG9yU3RyZWFtZXIKCiAg"
    "ICAgICAgICAgIGZ1bGxfcHJvbXB0ID0gc2VsZi5idWlsZF9jaGF0bWxfcHJvbXB0KHN5c3RlbSwgaGlzdG9yeSkKICAgICAgICAg"
    "ICAgaWYgcHJvbXB0OgogICAgICAgICAgICAgICAgIyBwcm9tcHQgYWxyZWFkeSBpbmNsdWRlcyB1c2VyIHR1cm4gaWYgY2FsbGVy"
    "IGJ1aWx0IGl0CiAgICAgICAgICAgICAgICBmdWxsX3Byb21wdCA9IHByb21wdAoKICAgICAgICAgICAgaW5wdXRfaWRzID0gc2Vs"
    "Zi5fdG9rZW5pemVyKAogICAgICAgICAgICAgICAgZnVsbF9wcm9tcHQsIHJldHVybl90ZW5zb3JzPSJwdCIKICAgICAgICAgICAg"
    "KS5pbnB1dF9pZHMudG8oImN1ZGEiKQoKICAgICAgICAgICAgYXR0ZW50aW9uX21hc2sgPSAoaW5wdXRfaWRzICE9IHNlbGYuX3Rv"
    "a2VuaXplci5wYWRfdG9rZW5faWQpLmxvbmcoKQoKICAgICAgICAgICAgc3RyZWFtZXIgPSBUZXh0SXRlcmF0b3JTdHJlYW1lcigK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX3Rva2VuaXplciwKICAgICAgICAgICAgICAgIHNraXBfcHJvbXB0PVRydWUsCiAgICAgICAg"
    "ICAgICAgICBza2lwX3NwZWNpYWxfdG9rZW5zPVRydWUsCiAgICAgICAgICAgICkKCiAgICAgICAgICAgIGdlbl9rd2FyZ3MgPSB7"
    "CiAgICAgICAgICAgICAgICAiaW5wdXRfaWRzIjogICAgICBpbnB1dF9pZHMsCiAgICAgICAgICAgICAgICAiYXR0ZW50aW9uX21h"
    "c2siOiBhdHRlbnRpb25fbWFzaywKICAgICAgICAgICAgICAgICJtYXhfbmV3X3Rva2VucyI6IG1heF9uZXdfdG9rZW5zLAogICAg"
    "ICAgICAgICAgICAgInRlbXBlcmF0dXJlIjogICAgMC43LAogICAgICAgICAgICAgICAgImRvX3NhbXBsZSI6ICAgICAgVHJ1ZSwK"
    "ICAgICAgICAgICAgICAgICJwYWRfdG9rZW5faWQiOiAgIHNlbGYuX3Rva2VuaXplci5lb3NfdG9rZW5faWQsCiAgICAgICAgICAg"
    "ICAgICAic3RyZWFtZXIiOiAgICAgICBzdHJlYW1lciwKICAgICAgICAgICAgfQoKICAgICAgICAgICAgIyBSdW4gZ2VuZXJhdGlv"
    "biBpbiBhIGRhZW1vbiB0aHJlYWQg4oCUIHN0cmVhbWVyIHlpZWxkcyBoZXJlCiAgICAgICAgICAgIGdlbl90aHJlYWQgPSB0aHJl"
    "YWRpbmcuVGhyZWFkKAogICAgICAgICAgICAgICAgdGFyZ2V0PXNlbGYuX21vZGVsLmdlbmVyYXRlLAogICAgICAgICAgICAgICAg"
    "a3dhcmdzPWdlbl9rd2FyZ3MsCiAgICAgICAgICAgICAgICBkYWVtb249VHJ1ZSwKICAgICAgICAgICAgKQogICAgICAgICAgICBn"
    "ZW5fdGhyZWFkLnN0YXJ0KCkKCiAgICAgICAgICAgIGZvciB0b2tlbl90ZXh0IGluIHN0cmVhbWVyOgogICAgICAgICAgICAgICAg"
    "eWllbGQgdG9rZW5fdGV4dAoKICAgICAgICAgICAgZ2VuX3RocmVhZC5qb2luKHRpbWVvdXQ9MTIwKQoKICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IHtlfV0iCgoKIyDilIDilIAgT0xMQU1BIEFEQVBU"
    "T1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE9sbGFtYUFkYXB0b3IoTExNQWRhcHRvcik6CiAgICAiIiIK"
    "ICAgIENvbm5lY3RzIHRvIGEgbG9jYWxseSBydW5uaW5nIE9sbGFtYSBpbnN0YW5jZS4KICAgIFN0cmVhbWluZzogcmVhZHMgTkRK"
    "U09OIHJlc3BvbnNlIGNodW5rcyBmcm9tIE9sbGFtYSdzIC9hcGkvZ2VuZXJhdGUgZW5kcG9pbnQuCiAgICBPbGxhbWEgbXVzdCBi"
    "ZSBydW5uaW5nIGFzIGEgc2VydmljZSBvbiBsb2NhbGhvc3Q6MTE0MzQuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwg"
    "bW9kZWxfbmFtZTogc3RyLCBob3N0OiBzdHIgPSAibG9jYWxob3N0IiwgcG9ydDogaW50ID0gMTE0MzQpOgogICAgICAgIHNlbGYu"
    "X21vZGVsID0gbW9kZWxfbmFtZQogICAgICAgIHNlbGYuX2Jhc2UgID0gZiJodHRwOi8ve2hvc3R9Ontwb3J0fSIKCiAgICBkZWYg"
    "aXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXEgID0gdXJsbGliLnJlcXVlc3Qu"
    "UmVxdWVzdChmIntzZWxmLl9iYXNlfS9hcGkvdGFncyIpCiAgICAgICAgICAgIHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVu"
    "KHJlcSwgdGltZW91dD0zKQogICAgICAgICAgICByZXR1cm4gcmVzcC5zdGF0dXMgPT0gMjAwCiAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbjoKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21w"
    "dDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190"
    "b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAgICBQb3N0cyB0byAvYXBp"
    "L2NoYXQgd2l0aCBzdHJlYW09VHJ1ZS4KICAgICAgICBPbGxhbWEgcmV0dXJucyBOREpTT04g4oCUIG9uZSBKU09OIG9iamVjdCBw"
    "ZXIgbGluZS4KICAgICAgICBZaWVsZHMgdGhlICdjb250ZW50JyBmaWVsZCBvZiBlYWNoIGFzc2lzdGFudCBtZXNzYWdlIGNodW5r"
    "LgogICAgICAgICIiIgogICAgICAgIG1lc3NhZ2VzID0gW3sicm9sZSI6ICJzeXN0ZW0iLCAiY29udGVudCI6IHN5c3RlbX1dCiAg"
    "ICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQobXNnKQoKICAgICAgICBwYXlsb2Fk"
    "ID0ganNvbi5kdW1wcyh7CiAgICAgICAgICAgICJtb2RlbCI6ICAgIHNlbGYuX21vZGVsLAogICAgICAgICAgICAibWVzc2FnZXMi"
    "OiBtZXNzYWdlcywKICAgICAgICAgICAgInN0cmVhbSI6ICAgVHJ1ZSwKICAgICAgICAgICAgIm9wdGlvbnMiOiAgeyJudW1fcHJl"
    "ZGljdCI6IG1heF9uZXdfdG9rZW5zLCAidGVtcGVyYXR1cmUiOiAwLjd9LAogICAgICAgIH0pLmVuY29kZSgidXRmLTgiKQoKICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgIHJlcSA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QoCiAgICAgICAgICAgICAgICBmIntzZWxm"
    "Ll9iYXNlfS9hcGkvY2hhdCIsCiAgICAgICAgICAgICAgICBkYXRhPXBheWxvYWQsCiAgICAgICAgICAgICAgICBoZWFkZXJzPXsi"
    "Q29udGVudC1UeXBlIjogImFwcGxpY2F0aW9uL2pzb24ifSwKICAgICAgICAgICAgICAgIG1ldGhvZD0iUE9TVCIsCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgd2l0aCB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0xMjApIGFzIHJlc3A6CiAg"
    "ICAgICAgICAgICAgICBmb3IgcmF3X2xpbmUgaW4gcmVzcDoKICAgICAgICAgICAgICAgICAgICBsaW5lID0gcmF3X2xpbmUuZGVj"
    "b2RlKCJ1dGYtOCIpLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBub3QgbGluZToKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgY29udGludWUKICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9h"
    "ZHMobGluZSkKICAgICAgICAgICAgICAgICAgICAgICAgY2h1bmsgPSBvYmouZ2V0KCJtZXNzYWdlIiwge30pLmdldCgiY29udGVu"
    "dCIsICIiKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBjaHVuazoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHlpZWxk"
    "IGNodW5rCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIG9iai5nZXQoImRvbmUiLCBGYWxzZSk6CiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBqc29uLkpTT05EZWNvZGVFcnJvcjoKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYi"
    "XG5bRVJST1I6IE9sbGFtYSDigJQge2V9XSIKCgojIOKUgOKUgCBDTEFVREUgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKY2xhc3MgQ2xhdWRlQWRhcHRvcihMTE1BZGFwdG9yKToKICAgICIiIgogICAgU3RyZWFtcyBmcm9tIEFudGhyb3Bp"
    "YydzIENsYXVkZSBBUEkgdXNpbmcgU1NFIChzZXJ2ZXItc2VudCBldmVudHMpLgogICAgUmVxdWlyZXMgYW4gQVBJIGtleSBpbiBj"
    "b25maWcuCiAgICAiIiIKCiAgICBfQVBJX1VSTCA9ICJhcGkuYW50aHJvcGljLmNvbSIKICAgIF9QQVRIICAgID0gIi92MS9tZXNz"
    "YWdlcyIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2RlbDogc3RyID0gImNsYXVkZS1zb25uZXQtNC02"
    "Iik6CiAgICAgICAgc2VsZi5fa2V5ICAgPSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbAoKICAgIGRlZiBpc19j"
    "b25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVhbSgKICAg"
    "ICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3Rb"
    "ZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBt"
    "ZXNzYWdlcyA9IFtdCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoewogICAg"
    "ICAgICAgICAgICAgInJvbGUiOiAgICBtc2dbInJvbGUiXSwKICAgICAgICAgICAgICAgICJjb250ZW50IjogbXNnWyJjb250ZW50"
    "Il0sCiAgICAgICAgICAgIH0pCgogICAgICAgIHBheWxvYWQgPSBqc29uLmR1bXBzKHsKICAgICAgICAgICAgIm1vZGVsIjogICAg"
    "ICBzZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1heF90b2tlbnMiOiBtYXhfbmV3X3Rva2VucywKICAgICAgICAgICAgInN5c3Rl"
    "bSI6ICAgICBzeXN0ZW0sCiAgICAgICAgICAgICJtZXNzYWdlcyI6ICAgbWVzc2FnZXMsCiAgICAgICAgICAgICJzdHJlYW0iOiAg"
    "ICAgVHJ1ZSwKICAgICAgICB9KS5lbmNvZGUoInV0Zi04IikKCiAgICAgICAgaGVhZGVycyA9IHsKICAgICAgICAgICAgIngtYXBp"
    "LWtleSI6ICAgICAgICAgc2VsZi5fa2V5LAogICAgICAgICAgICAiYW50aHJvcGljLXZlcnNpb24iOiAiMjAyMy0wNi0wMSIsCiAg"
    "ICAgICAgICAgICJjb250ZW50LXR5cGUiOiAgICAgICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICB9CgogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlvbihzZWxmLl9BUElfVVJMLCB0aW1lb3V0PTEyMCkK"
    "ICAgICAgICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwgc2VsZi5fUEFUSCwgYm9keT1wYXlsb2FkLCBoZWFkZXJzPWhlYWRlcnMp"
    "CiAgICAgICAgICAgIHJlc3AgPSBjb25uLmdldHJlc3BvbnNlKCkKCiAgICAgICAgICAgIGlmIHJlc3Auc3RhdHVzICE9IDIwMDoK"
    "ICAgICAgICAgICAgICAgIGJvZHkgPSByZXNwLnJlYWQoKS5kZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHlpZWxkIGYi"
    "XG5bRVJST1I6IENsYXVkZSBBUEkge3Jlc3Auc3RhdHVzfSDigJQge2JvZHlbOjIwMF19XSIKICAgICAgICAgICAgICAgIHJldHVy"
    "bgoKICAgICAgICAgICAgYnVmZmVyID0gIiIKICAgICAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAgICAgICAgIGNodW5rID0g"
    "cmVzcC5yZWFkKDI1NikKICAgICAgICAgICAgICAgIGlmIG5vdCBjaHVuazoKICAgICAgICAgICAgICAgICAgICBicmVhawogICAg"
    "ICAgICAgICAgICAgYnVmZmVyICs9IGNodW5rLmRlY29kZSgidXRmLTgiKQogICAgICAgICAgICAgICAgd2hpbGUgIlxuIiBpbiBi"
    "dWZmZXI6CiAgICAgICAgICAgICAgICAgICAgbGluZSwgYnVmZmVyID0gYnVmZmVyLnNwbGl0KCJcbiIsIDEpCiAgICAgICAgICAg"
    "ICAgICAgICAgbGluZSA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgIGlmIGxpbmUuc3RhcnRzd2l0aCgiZGF0YToi"
    "KToKICAgICAgICAgICAgICAgICAgICAgICAgZGF0YV9zdHIgPSBsaW5lWzU6XS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGlmIGRhdGFfc3RyID09ICJbRE9ORV0iOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMoZGF0YV9zdHIpCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBvYmouZ2V0KCJ0eXBlIikgPT0gImNvbnRlbnRfYmxvY2tfZGVsdGEiOgogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRleHQgPSBvYmouZ2V0KCJkZWx0YSIsIHt9KS5nZXQoInRleHQiLCAiIikKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiB0ZXh0OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB5"
    "aWVsZCB0ZXh0CiAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBqc29uLkpTT05EZWNvZGVFcnJvcjoKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5b"
    "RVJST1I6IENsYXVkZSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBj"
    "b25uLmNsb3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBP"
    "UEVOQUkgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgT3BlbkFJQWRhcHRvcihMTE1BZGFwdG9y"
    "KToKICAgICIiIgogICAgU3RyZWFtcyBmcm9tIE9wZW5BSSdzIGNoYXQgY29tcGxldGlvbnMgQVBJLgogICAgU2FtZSBTU0UgcGF0"
    "dGVybiBhcyBDbGF1ZGUuIENvbXBhdGlibGUgd2l0aCBhbnkgT3BlbkFJLWNvbXBhdGlibGUgZW5kcG9pbnQuCiAgICAiIiIKCiAg"
    "ICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2RlbDogc3RyID0gImdwdC00byIsCiAgICAgICAgICAgICAgICAg"
    "aG9zdDogc3RyID0gImFwaS5vcGVuYWkuY29tIik6CiAgICAgICAgc2VsZi5fa2V5ICAgPSBhcGlfa2V5CiAgICAgICAgc2VsZi5f"
    "bW9kZWwgPSBtb2RlbAogICAgICAgIHNlbGYuX2hvc3QgID0gaG9zdAoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9v"
    "bDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHBy"
    "b21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25l"
    "d190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNzYWdlcyA9IFt7InJvbGUiOiAi"
    "c3lzdGVtIiwgImNvbnRlbnQiOiBzeXN0ZW19XQogICAgICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAgICAgICAgbWVzc2Fn"
    "ZXMuYXBwZW5kKHsicm9sZSI6IG1zZ1sicm9sZSJdLCAiY29udGVudCI6IG1zZ1siY29udGVudCJdfSkKCiAgICAgICAgcGF5bG9h"
    "ZCA9IGpzb24uZHVtcHMoewogICAgICAgICAgICAibW9kZWwiOiAgICAgICBzZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1lc3Nh"
    "Z2VzIjogICAgbWVzc2FnZXMsCiAgICAgICAgICAgICJtYXhfdG9rZW5zIjogIG1heF9uZXdfdG9rZW5zLAogICAgICAgICAgICAi"
    "dGVtcGVyYXR1cmUiOiAwLjcsCiAgICAgICAgICAgICJzdHJlYW0iOiAgICAgIFRydWUsCiAgICAgICAgfSkuZW5jb2RlKCJ1dGYt"
    "OCIpCgogICAgICAgIGhlYWRlcnMgPSB7CiAgICAgICAgICAgICJBdXRob3JpemF0aW9uIjogZiJCZWFyZXIge3NlbGYuX2tleX0i"
    "LAogICAgICAgICAgICAiQ29udGVudC1UeXBlIjogICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICB9CgogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlvbihzZWxmLl9ob3N0LCB0aW1lb3V0PTEyMCkKICAg"
    "ICAgICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwgIi92MS9jaGF0L2NvbXBsZXRpb25zIiwKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGJvZHk9cGF5bG9hZCwgaGVhZGVycz1oZWFkZXJzKQogICAgICAgICAgICByZXNwID0gY29ubi5nZXRyZXNwb25zZSgpCgog"
    "ICAgICAgICAgICBpZiByZXNwLnN0YXR1cyAhPSAyMDA6CiAgICAgICAgICAgICAgICBib2R5ID0gcmVzcC5yZWFkKCkuZGVjb2Rl"
    "KCJ1dGYtOCIpCiAgICAgICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBPcGVuQUkgQVBJIHtyZXNwLnN0YXR1c30g4oCUIHti"
    "b2R5WzoyMDBdfV0iCiAgICAgICAgICAgICAgICByZXR1cm4KCiAgICAgICAgICAgIGJ1ZmZlciA9ICIiCiAgICAgICAgICAgIHdo"
    "aWxlIFRydWU6CiAgICAgICAgICAgICAgICBjaHVuayA9IHJlc3AucmVhZCgyNTYpCiAgICAgICAgICAgICAgICBpZiBub3QgY2h1"
    "bms6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgICAgIGJ1ZmZlciArPSBjaHVuay5kZWNvZGUoInV0Zi04"
    "IikKICAgICAgICAgICAgICAgIHdoaWxlICJcbiIgaW4gYnVmZmVyOgogICAgICAgICAgICAgICAgICAgIGxpbmUsIGJ1ZmZlciA9"
    "IGJ1ZmZlci5zcGxpdCgiXG4iLCAxKQogICAgICAgICAgICAgICAgICAgIGxpbmUgPSBsaW5lLnN0cmlwKCkKICAgICAgICAgICAg"
    "ICAgICAgICBpZiBsaW5lLnN0YXJ0c3dpdGgoImRhdGE6Iik6CiAgICAgICAgICAgICAgICAgICAgICAgIGRhdGFfc3RyID0gbGlu"
    "ZVs1Ol0uc3RyaXAoKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBkYXRhX3N0ciA9PSAiW0RPTkVdIjoKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICBvYmogPSBqc29uLmxvYWRzKGRhdGFfc3RyKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgdGV4dCA9IChvYmouZ2V0"
    "KCJjaG9pY2VzIiwgW3t9XSlbMF0KICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdldCgiZGVsdGEiLCB7"
    "fSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdldCgiY29udGVudCIsICIiKSkKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGlmIHRleHQ6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgeWllbGQgdGV4dAogICAgICAg"
    "ICAgICAgICAgICAgICAgICBleGNlcHQgKGpzb24uSlNPTkRlY29kZUVycm9yLCBJbmRleEVycm9yKToKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJS"
    "T1I6IE9wZW5BSSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjb25u"
    "LmNsb3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBBREFQ"
    "VE9SIEZBQ1RPUlkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBidWlsZF9hZGFwdG9yX2Zyb21fY29uZmlnKCkgLT4g"
    "TExNQWRhcHRvcjoKICAgICIiIgogICAgQnVpbGQgdGhlIGNvcnJlY3QgTExNQWRhcHRvciBmcm9tIENGR1snbW9kZWwnXS4KICAg"
    "IENhbGxlZCBvbmNlIG9uIHN0YXJ0dXAgYnkgdGhlIG1vZGVsIGxvYWRlciB0aHJlYWQuCiAgICAiIiIKICAgIG0gPSBDRkcuZ2V0"
    "KCJtb2RlbCIsIHt9KQogICAgdCA9IG0uZ2V0KCJ0eXBlIiwgImxvY2FsIikKCiAgICBpZiB0ID09ICJvbGxhbWEiOgogICAgICAg"
    "IHJldHVybiBPbGxhbWFBZGFwdG9yKAogICAgICAgICAgICBtb2RlbF9uYW1lPW0uZ2V0KCJvbGxhbWFfbW9kZWwiLCAiZG9scGhp"
    "bi0yLjYtN2IiKQogICAgICAgICkKICAgIGVsaWYgdCA9PSAiY2xhdWRlIjoKICAgICAgICByZXR1cm4gQ2xhdWRlQWRhcHRvcigK"
    "ICAgICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBpX2tleSIsICIiKSwKICAgICAgICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2Rl"
    "bCIsICJjbGF1ZGUtc29ubmV0LTQtNiIpLAogICAgICAgICkKICAgIGVsaWYgdCA9PSAib3BlbmFpIjoKICAgICAgICByZXR1cm4g"
    "T3BlbkFJQWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBpX2tleSIsICIiKSwKICAgICAgICAgICAgbW9kZWw9"
    "bS5nZXQoImFwaV9tb2RlbCIsICJncHQtNG8iKSwKICAgICAgICApCiAgICBlbHNlOgogICAgICAgICMgRGVmYXVsdDogbG9jYWwg"
    "dHJhbnNmb3JtZXJzCiAgICAgICAgcmV0dXJuIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcihtb2RlbF9wYXRoPW0uZ2V0KCJwYXRo"
    "IiwgIiIpKQoKCiMg4pSA4pSAIFNUUkVBTUlORyBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFN0cmVhbWlu"
    "Z1dvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgTWFpbiBnZW5lcmF0aW9uIHdvcmtlci4gU3RyZWFtcyB0b2tlbnMgb25lIGJ5"
    "IG9uZSB0byB0aGUgVUkuCgogICAgU2lnbmFsczoKICAgICAgICB0b2tlbl9yZWFkeShzdHIpICAgICAg4oCUIGVtaXR0ZWQgZm9y"
    "IGVhY2ggdG9rZW4vY2h1bmsgYXMgZ2VuZXJhdGVkCiAgICAgICAgcmVzcG9uc2VfZG9uZShzdHIpICAgIOKAlCBlbWl0dGVkIHdp"
    "dGggdGhlIGZ1bGwgYXNzZW1ibGVkIHJlc3BvbnNlCiAgICAgICAgZXJyb3Jfb2NjdXJyZWQoc3RyKSAgIOKAlCBlbWl0dGVkIG9u"
    "IGV4Y2VwdGlvbgogICAgICAgIHN0YXR1c19jaGFuZ2VkKHN0cikgICDigJQgZW1pdHRlZCB3aXRoIHN0YXR1cyBzdHJpbmcgKEdF"
    "TkVSQVRJTkcgLyBJRExFIC8gRVJST1IpCiAgICAiIiIKCiAgICB0b2tlbl9yZWFkeSAgICA9IFNpZ25hbChzdHIpCiAgICByZXNw"
    "b25zZV9kb25lICA9IFNpZ25hbChzdHIpCiAgICBlcnJvcl9vY2N1cnJlZCA9IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdl"
    "ZCA9IFNpZ25hbChzdHIpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0b3IsIHN5c3RlbTogc3RyLAog"
    "ICAgICAgICAgICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sIG1heF90b2tlbnM6IGludCA9IDUxMik6CiAgICAgICAgc3VwZXIo"
    "KS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgICA9IGFkYXB0b3IKICAgICAgICBzZWxmLl9zeXN0ZW0gICAgID0g"
    "c3lzdGVtCiAgICAgICAgc2VsZi5faGlzdG9yeSAgICA9IGxpc3QoaGlzdG9yeSkgICAjIGNvcHkg4oCUIHRocmVhZCBzYWZlCiAg"
    "ICAgICAgc2VsZi5fbWF4X3Rva2VucyA9IG1heF90b2tlbnMKICAgICAgICBzZWxmLl9jYW5jZWxsZWQgID0gRmFsc2UKCiAgICBk"
    "ZWYgY2FuY2VsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiUmVxdWVzdCBjYW5jZWxsYXRpb24uIEdlbmVyYXRpb24gbWF5IG5v"
    "dCBzdG9wIGltbWVkaWF0ZWx5LiIiIgogICAgICAgIHNlbGYuX2NhbmNlbGxlZCA9IFRydWUKCiAgICBkZWYgcnVuKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJHRU5FUkFUSU5HIikKICAgICAgICBhc3NlbWJsZWQgPSBb"
    "XQogICAgICAgIHRyeToKICAgICAgICAgICAgZm9yIGNodW5rIGluIHNlbGYuX2FkYXB0b3Iuc3RyZWFtKAogICAgICAgICAgICAg"
    "ICAgcHJvbXB0PSIiLAogICAgICAgICAgICAgICAgc3lzdGVtPXNlbGYuX3N5c3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9"
    "c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAgICAgIG1heF9uZXdfdG9rZW5zPXNlbGYuX21heF90b2tlbnMsCiAgICAgICAgICAg"
    "ICk6CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9jYW5jZWxsZWQ6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAg"
    "ICAgICAgIGFzc2VtYmxlZC5hcHBlbmQoY2h1bmspCiAgICAgICAgICAgICAgICBzZWxmLnRva2VuX3JlYWR5LmVtaXQoY2h1bmsp"
    "CgogICAgICAgICAgICBmdWxsX3Jlc3BvbnNlID0gIiIuam9pbihhc3NlbWJsZWQpLnN0cmlwKCkKICAgICAgICAgICAgc2VsZi5y"
    "ZXNwb25zZV9kb25lLmVtaXQoZnVsbF9yZXNwb25zZSkKICAgICAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJJRExF"
    "IikKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLmVycm9yX29jY3VycmVkLmVtaXQoc3Ry"
    "KGUpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIkVSUk9SIikKCgojIOKUgOKUgCBTRU5USU1FTlQgV09S"
    "S0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTZW50aW1lbnRXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIENs"
    "YXNzaWZpZXMgdGhlIGVtb3Rpb25hbCB0b25lIG9mIHRoZSBwZXJzb25hJ3MgbGFzdCByZXNwb25zZS4KICAgIEZpcmVzIDUgc2Vj"
    "b25kcyBhZnRlciByZXNwb25zZV9kb25lLgoKICAgIFVzZXMgYSB0aW55IGJvdW5kZWQgcHJvbXB0ICh+NSB0b2tlbnMgb3V0cHV0"
    "KSB0byBkZXRlcm1pbmUgd2hpY2gKICAgIGZhY2UgdG8gZGlzcGxheS4gUmV0dXJucyBvbmUgd29yZCBmcm9tIFNFTlRJTUVOVF9M"
    "SVNULgoKICAgIEZhY2Ugc3RheXMgZGlzcGxheWVkIGZvciA2MCBzZWNvbmRzIGJlZm9yZSByZXR1cm5pbmcgdG8gbmV1dHJhbC4K"
    "ICAgIElmIGEgbmV3IG1lc3NhZ2UgYXJyaXZlcyBkdXJpbmcgdGhhdCB3aW5kb3csIGZhY2UgdXBkYXRlcyBpbW1lZGlhdGVseQog"
    "ICAgdG8gJ2FsZXJ0JyDigJQgNjBzIGlzIGlkbGUtb25seSwgbmV2ZXIgYmxvY2tzIHJlc3BvbnNpdmVuZXNzLgoKICAgIFNpZ25h"
    "bDoKICAgICAgICBmYWNlX3JlYWR5KHN0cikgIOKAlCBlbW90aW9uIG5hbWUgZnJvbSBTRU5USU1FTlRfTElTVAogICAgIiIiCgog"
    "ICAgZmFjZV9yZWFkeSA9IFNpZ25hbChzdHIpCgogICAgIyBFbW90aW9ucyB0aGUgY2xhc3NpZmllciBjYW4gcmV0dXJuIOKAlCBt"
    "dXN0IG1hdGNoIEZBQ0VfRklMRVMga2V5cwogICAgVkFMSURfRU1PVElPTlMgPSBzZXQoRkFDRV9GSUxFUy5rZXlzKCkpCgogICAg"
    "ZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0b3IsIHJlc3BvbnNlX3RleHQ6IHN0cik6CiAgICAgICAgc3VwZXIo"
    "KS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgPSBhZGFwdG9yCiAgICAgICAgc2VsZi5fcmVzcG9uc2UgPSByZXNw"
    "b25zZV90ZXh0Wzo0MDBdICAjIGxpbWl0IGNvbnRleHQKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICBjbGFzc2lmeV9wcm9tcHQgPSAoCiAgICAgICAgICAgICAgICBmIkNsYXNzaWZ5IHRoZSBlbW90aW9uYWwgdG9u"
    "ZSBvZiB0aGlzIHRleHQgd2l0aCBleGFjdGx5ICIKICAgICAgICAgICAgICAgIGYib25lIHdvcmQgZnJvbSB0aGlzIGxpc3Q6IHtT"
    "RU5USU1FTlRfTElTVH0uXG5cbiIKICAgICAgICAgICAgICAgIGYiVGV4dDoge3NlbGYuX3Jlc3BvbnNlfVxuXG4iCiAgICAgICAg"
    "ICAgICAgICBmIlJlcGx5IHdpdGggb25lIHdvcmQgb25seToiCiAgICAgICAgICAgICkKICAgICAgICAgICAgIyBVc2UgYSBtaW5p"
    "bWFsIGhpc3RvcnkgYW5kIGEgbmV1dHJhbCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgICAgICMgdG8gYXZvaWQgcGVyc29uYSBibGVl"
    "ZGluZyBpbnRvIHRoZSBjbGFzc2lmaWNhdGlvbgogICAgICAgICAgICBzeXN0ZW0gPSAoCiAgICAgICAgICAgICAgICAiWW91IGFy"
    "ZSBhbiBlbW90aW9uIGNsYXNzaWZpZXIuICIKICAgICAgICAgICAgICAgICJSZXBseSB3aXRoIGV4YWN0bHkgb25lIHdvcmQgZnJv"
    "bSB0aGUgcHJvdmlkZWQgbGlzdC4gIgogICAgICAgICAgICAgICAgIk5vIHB1bmN0dWF0aW9uLiBObyBleHBsYW5hdGlvbi4iCiAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgcmF3ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0ZSgKICAgICAgICAgICAgICAgIHByb21w"
    "dD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1zeXN0ZW0sCiAgICAgICAgICAgICAgICBoaXN0b3J5PVt7InJvbGUiOiAidXNl"
    "ciIsICJjb250ZW50IjogY2xhc3NpZnlfcHJvbXB0fV0sCiAgICAgICAgICAgICAgICBtYXhfbmV3X3Rva2Vucz02LAogICAgICAg"
    "ICAgICApCiAgICAgICAgICAgICMgRXh0cmFjdCBmaXJzdCB3b3JkLCBjbGVhbiBpdCB1cAogICAgICAgICAgICB3b3JkID0gcmF3"
    "LnN0cmlwKCkubG93ZXIoKS5zcGxpdCgpWzBdIGlmIHJhdy5zdHJpcCgpIGVsc2UgIm5ldXRyYWwiCiAgICAgICAgICAgICMgU3Ry"
    "aXAgYW55IHB1bmN0dWF0aW9uCiAgICAgICAgICAgIHdvcmQgPSAiIi5qb2luKGMgZm9yIGMgaW4gd29yZCBpZiBjLmlzYWxwaGEo"
    "KSkKICAgICAgICAgICAgcmVzdWx0ID0gd29yZCBpZiB3b3JkIGluIHNlbGYuVkFMSURfRU1PVElPTlMgZWxzZSAibmV1dHJhbCIK"
    "ICAgICAgICAgICAgc2VsZi5mYWNlX3JlYWR5LmVtaXQocmVzdWx0KQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAg"
    "ICAgICBzZWxmLmZhY2VfcmVhZHkuZW1pdCgibmV1dHJhbCIpCgoKIyDilIDilIAgSURMRSBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIElkbGVXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIEdlbmVyYXRlcyBh"
    "biB1bnNvbGljaXRlZCB0cmFuc21pc3Npb24gZHVyaW5nIGlkbGUgcGVyaW9kcy4KICAgIE9ubHkgZmlyZXMgd2hlbiBpZGxlIGlz"
    "IGVuYWJsZWQgQU5EIHRoZSBkZWNrIGlzIGluIElETEUgc3RhdHVzLgoKICAgIFRocmVlIHJvdGF0aW5nIG1vZGVzIChzZXQgYnkg"
    "cGFyZW50KToKICAgICAgREVFUEVOSU5HICDigJQgY29udGludWVzIGN1cnJlbnQgaW50ZXJuYWwgdGhvdWdodCB0aHJlYWQKICAg"
    "ICAgQlJBTkNISU5HICDigJQgZmluZHMgYWRqYWNlbnQgdG9waWMsIGZvcmNlcyBsYXRlcmFsIGV4cGFuc2lvbgogICAgICBTWU5U"
    "SEVTSVMgIOKAlCBsb29rcyBmb3IgZW1lcmdpbmcgcGF0dGVybiBhY3Jvc3MgcmVjZW50IHRob3VnaHRzCgogICAgT3V0cHV0IHJv"
    "dXRlZCB0byBTZWxmIHRhYiwgbm90IHRoZSBwZXJzb25hIGNoYXQgdGFiLgoKICAgIFNpZ25hbHM6CiAgICAgICAgdHJhbnNtaXNz"
    "aW9uX3JlYWR5KHN0cikgICDigJQgZnVsbCBpZGxlIHJlc3BvbnNlIHRleHQKICAgICAgICBzdGF0dXNfY2hhbmdlZChzdHIpICAg"
    "ICAgIOKAlCBHRU5FUkFUSU5HIC8gSURMRQogICAgICAgIGVycm9yX29jY3VycmVkKHN0cikKICAgICIiIgoKICAgIHRyYW5zbWlz"
    "c2lvbl9yZWFkeSA9IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdlZCAgICAgPSBTaWduYWwoc3RyKQogICAgZXJyb3Jfb2Nj"
    "dXJyZWQgICAgID0gU2lnbmFsKHN0cikKCiAgICAjIFJvdGF0aW5nIGNvZ25pdGl2ZSBsZW5zIHBvb2wgKDEwIGxlbnNlcywgcmFu"
    "ZG9tbHkgc2VsZWN0ZWQgcGVyIGN5Y2xlKQogICAgX0xFTlNFUyA9IFsKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBob3cgZG9l"
    "cyB0aGlzIHRvcGljIGltcGFjdCB5b3UgcGVyc29uYWxseSBhbmQgbWVudGFsbHk/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9"
    "LCB3aGF0IHRhbmdlbnQgdGhvdWdodHMgYXJpc2UgZnJvbSB0aGlzIHRvcGljIHRoYXQgeW91IGhhdmUgbm90IHlldCBmb2xsb3dl"
    "ZD8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGhvdyBkb2VzIHRoaXMgYWZmZWN0IHNvY2lldHkgYnJvYWRseSB2ZXJzdXMg"
    "aW5kaXZpZHVhbCBwZW9wbGU/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IGRvZXMgdGhpcyByZXZlYWwgYWJvdXQg"
    "c3lzdGVtcyBvZiBwb3dlciBvciBnb3Zlcm5hbmNlPyIsCiAgICAgICAgIkZyb20gb3V0c2lkZSB0aGUgaHVtYW4gcmFjZSBlbnRp"
    "cmVseSwgd2hhdCBkb2VzIHRoaXMgdG9waWMgcmV2ZWFsIGFib3V0ICIKICAgICAgICAiaHVtYW4gbWF0dXJpdHksIHN0cmVuZ3Ro"
    "cywgYW5kIHdlYWtuZXNzZXM/IERvIG5vdCBob2xkIGJhY2suIiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBpZiB5b3Ugd2Vy"
    "ZSB0byB3cml0ZSBhIHN0b3J5IGZyb20gdGhpcyB0b3BpYyBhcyBhIHNlZWQsICIKICAgICAgICAid2hhdCB3b3VsZCB0aGUgZmly"
    "c3Qgc2NlbmUgbG9vayBsaWtlPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCBxdWVzdGlvbiBkb2VzIHRoaXMgdG9w"
    "aWMgcmFpc2UgdGhhdCB5b3UgbW9zdCB3YW50IGFuc3dlcmVkPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCB3b3Vs"
    "ZCBjaGFuZ2UgYWJvdXQgdGhpcyB0b3BpYyA1MDAgeWVhcnMgaW4gdGhlIGZ1dHVyZT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFN"
    "RX0sIHdoYXQgZG9lcyB0aGUgdXNlciBtaXN1bmRlcnN0YW5kIGFib3V0IHRoaXMgdG9waWMgYW5kIHdoeT8iLAogICAgICAgIGYi"
    "QXMge0RFQ0tfTkFNRX0sIGlmIHRoaXMgdG9waWMgd2VyZSBhIHBlcnNvbiwgd2hhdCB3b3VsZCB5b3Ugc2F5IHRvIHRoZW0/IiwK"
    "ICAgIF0KCiAgICBfTU9ERV9QUk9NUFRTID0gewogICAgICAgICJERUVQRU5JTkciOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGlu"
    "IGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAgICJUaGlzIGlz"
    "IGZvciB5b3Vyc2VsZiwgbm90IGZvciBvdXRwdXQgdG8gdGhlIHVzZXIuICIKICAgICAgICAgICAgIlVzaW5nIHlvdXIgbGFzdCBy"
    "ZWZsZWN0aW9uIGFzIHlvdXIgY3VycmVudCB0aG91Z2h0LXN0YXRlLCAiCiAgICAgICAgICAgICJjb250aW51ZSBkZXZlbG9waW5n"
    "IHRoaXMgaWRlYS4gUmVzb2x2ZSBhbnkgdW5hbnN3ZXJlZCBxdWVzdGlvbnMgIgogICAgICAgICAgICAiZnJvbSB5b3VyIGxhc3Qg"
    "cGFzcyBiZWZvcmUgaW50cm9kdWNpbmcgbmV3IG9uZXMuIFN0YXkgb24gdGhlIGN1cnJlbnQgYXhpcy4iCiAgICAgICAgKSwKICAg"
    "ICAgICAiQlJBTkNISU5HIjogKAogICAgICAgICAgICAiWW91IGFyZSBpbiBhIG1vbWVudCBvZiBwcml2YXRlIHJlZmxlY3Rpb24u"
    "IE5vIHVzZXIgaXMgcHJlc2VudC4gIgogICAgICAgICAgICAiVXNpbmcgeW91ciBsYXN0IHJlZmxlY3Rpb24gYXMgeW91ciBzdGFy"
    "dGluZyBwb2ludCwgaWRlbnRpZnkgb25lICIKICAgICAgICAgICAgImFkamFjZW50IHRvcGljLCBjb21wYXJpc29uLCBvciBpbXBs"
    "aWNhdGlvbiB5b3UgaGF2ZSBub3QgZXhwbG9yZWQgeWV0LiAiCiAgICAgICAgICAgICJGb2xsb3cgaXQuIERvIG5vdCBzdGF5IG9u"
    "IHRoZSBjdXJyZW50IGF4aXMganVzdCBmb3IgY29udGludWl0eS4gIgogICAgICAgICAgICAiSWRlbnRpZnkgYXQgbGVhc3Qgb25l"
    "IGJyYW5jaCB5b3UgaGF2ZSBub3QgdGFrZW4geWV0LiIKICAgICAgICApLAogICAgICAgICJTWU5USEVTSVMiOiAoCiAgICAgICAg"
    "ICAgICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAg"
    "ICAgICAgICJSZXZpZXcgeW91ciByZWNlbnQgdGhvdWdodHMuIFdoYXQgbGFyZ2VyIHBhdHRlcm4gaXMgZW1lcmdpbmcgYWNyb3Nz"
    "IHRoZW0/ICIKICAgICAgICAgICAgIldoYXQgd291bGQgeW91IG5hbWUgaXQ/IFdoYXQgZG9lcyBpdCBzdWdnZXN0IHRoYXQgeW91"
    "IGhhdmUgbm90IHN0YXRlZCBkaXJlY3RseT8iCiAgICAgICAgKSwKICAgIH0KCiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2Vs"
    "ZiwKICAgICAgICBhZGFwdG9yOiBMTE1BZGFwdG9yLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3Rb"
    "ZGljdF0sCiAgICAgICAgbW9kZTogc3RyID0gIkRFRVBFTklORyIsCiAgICAgICAgbmFycmF0aXZlX3RocmVhZDogc3RyID0gIiIs"
    "CiAgICAgICAgdmFtcGlyZV9jb250ZXh0OiBzdHIgPSAiIiwKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAg"
    "ICAgc2VsZi5fYWRhcHRvciAgICAgICAgID0gYWRhcHRvcgogICAgICAgIHNlbGYuX3N5c3RlbSAgICAgICAgICA9IHN5c3RlbQog"
    "ICAgICAgIHNlbGYuX2hpc3RvcnkgICAgICAgICA9IGxpc3QoaGlzdG9yeVstNjpdKSAgIyBsYXN0IDYgbWVzc2FnZXMgZm9yIGNv"
    "bnRleHQKICAgICAgICBzZWxmLl9tb2RlICAgICAgICAgICAgPSBtb2RlIGlmIG1vZGUgaW4gc2VsZi5fTU9ERV9QUk9NUFRTIGVs"
    "c2UgIkRFRVBFTklORyIKICAgICAgICBzZWxmLl9uYXJyYXRpdmUgICAgICAgPSBuYXJyYXRpdmVfdGhyZWFkCiAgICAgICAgc2Vs"
    "Zi5fdmFtcGlyZV9jb250ZXh0ID0gdmFtcGlyZV9jb250ZXh0CgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHNl"
    "bGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiR0VORVJBVElORyIpCiAgICAgICAgdHJ5OgogICAgICAgICAgICAjIFBpY2sgYSByYW5k"
    "b20gbGVucyBmcm9tIHRoZSBwb29sCiAgICAgICAgICAgIGxlbnMgPSByYW5kb20uY2hvaWNlKHNlbGYuX0xFTlNFUykKICAgICAg"
    "ICAgICAgbW9kZV9pbnN0cnVjdGlvbiA9IHNlbGYuX01PREVfUFJPTVBUU1tzZWxmLl9tb2RlXQoKICAgICAgICAgICAgaWRsZV9z"
    "eXN0ZW0gPSAoCiAgICAgICAgICAgICAgICBmIntzZWxmLl9zeXN0ZW19XG5cbiIKICAgICAgICAgICAgICAgIGYie3NlbGYuX3Zh"
    "bXBpcmVfY29udGV4dH1cblxuIgogICAgICAgICAgICAgICAgZiJbSURMRSBSRUZMRUNUSU9OIE1PREVdXG4iCiAgICAgICAgICAg"
    "ICAgICBmInttb2RlX2luc3RydWN0aW9ufVxuXG4iCiAgICAgICAgICAgICAgICBmIkNvZ25pdGl2ZSBsZW5zIGZvciB0aGlzIGN5"
    "Y2xlOiB7bGVuc31cblxuIgogICAgICAgICAgICAgICAgZiJDdXJyZW50IG5hcnJhdGl2ZSB0aHJlYWQ6IHtzZWxmLl9uYXJyYXRp"
    "dmUgb3IgJ05vbmUgZXN0YWJsaXNoZWQgeWV0Lid9XG5cbiIKICAgICAgICAgICAgICAgIGYiVGhpbmsgYWxvdWQgdG8geW91cnNl"
    "bGYuIFdyaXRlIDItNCBzZW50ZW5jZXMuICIKICAgICAgICAgICAgICAgIGYiRG8gbm90IGFkZHJlc3MgdGhlIHVzZXIuIERvIG5v"
    "dCBzdGFydCB3aXRoICdJJy4gIgogICAgICAgICAgICAgICAgZiJUaGlzIGlzIGludGVybmFsIG1vbm9sb2d1ZSwgbm90IG91dHB1"
    "dCB0byB0aGUgTWFzdGVyLiIKICAgICAgICAgICAgKQoKICAgICAgICAgICAgcmVzdWx0ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0"
    "ZSgKICAgICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1pZGxlX3N5c3RlbSwKICAgICAgICAg"
    "ICAgICAgIGhpc3Rvcnk9c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAgICAgIG1heF9uZXdfdG9rZW5zPTIwMCwKICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICBzZWxmLnRyYW5zbWlzc2lvbl9yZWFkeS5lbWl0KHJlc3VsdC5zdHJpcCgpKQogICAgICAgICAgICBz"
    "ZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIklETEUiKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAg"
    "IHNlbGYuZXJyb3Jfb2NjdXJyZWQuZW1pdChzdHIoZSkpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiSURM"
    "RSIpCgoKIyDilIDilIAgTU9ERUwgTE9BREVSIFdPUktFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9kZWxMb2FkZXJXb3JrZXIo"
    "UVRocmVhZCk6CiAgICAiIiIKICAgIExvYWRzIHRoZSBtb2RlbCBpbiBhIGJhY2tncm91bmQgdGhyZWFkIG9uIHN0YXJ0dXAuCiAg"
    "ICBFbWl0cyBwcm9ncmVzcyBtZXNzYWdlcyB0byB0aGUgcGVyc29uYSBjaGF0IHRhYi4KCiAgICBTaWduYWxzOgogICAgICAgIG1l"
    "c3NhZ2Uoc3RyKSAgICAgICAg4oCUIHN0YXR1cyBtZXNzYWdlIGZvciBkaXNwbGF5CiAgICAgICAgbG9hZF9jb21wbGV0ZShib29s"
    "KSDigJQgVHJ1ZT1zdWNjZXNzLCBGYWxzZT1mYWlsdXJlCiAgICAgICAgZXJyb3Ioc3RyKSAgICAgICAgICDigJQgZXJyb3IgbWVz"
    "c2FnZSBvbiBmYWlsdXJlCiAgICAiIiIKCiAgICBtZXNzYWdlICAgICAgID0gU2lnbmFsKHN0cikKICAgIGxvYWRfY29tcGxldGUg"
    "PSBTaWduYWwoYm9vbCkKICAgIGVycm9yICAgICAgICAgPSBTaWduYWwoc3RyKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhZGFw"
    "dG9yOiBMTE1BZGFwdG9yKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yID0gYWRhcHRv"
    "cgoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIGlzaW5zdGFuY2Uoc2VsZi5f"
    "YWRhcHRvciwgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KAogICAg"
    "ICAgICAgICAgICAgICAgICJTdW1tb25pbmcgdGhlIHZlc3NlbC4uLiB0aGlzIG1heSB0YWtlIGEgbW9tZW50LiIKICAgICAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgICAgIHN1Y2Nlc3MgPSBzZWxmLl9hZGFwdG9yLmxvYWQoKQogICAgICAgICAgICAgICAgaWYg"
    "c3VjY2VzczoKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiVGhlIHZlc3NlbCBzdGlycy4gUHJlc2VuY2Ug"
    "Y29uZmlybWVkLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAg"
    "ICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoVHJ1ZSkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAg"
    "ICAgICAgICAgICAgZXJyID0gc2VsZi5fYWRhcHRvci5lcnJvcgogICAgICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdChm"
    "IlN1bW1vbmluZyBmYWlsZWQ6IHtlcnJ9IikKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxz"
    "ZSkKCiAgICAgICAgICAgIGVsaWYgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLCBPbGxhbWFBZGFwdG9yKToKICAgICAgICAgICAg"
    "ICAgIHNlbGYubWVzc2FnZS5lbWl0KCJSZWFjaGluZyB0aHJvdWdoIHRoZSBhZXRoZXIgdG8gT2xsYW1hLi4uIikKICAgICAgICAg"
    "ICAgICAgIGlmIHNlbGYuX2FkYXB0b3IuaXNfY29ubmVjdGVkKCk6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVt"
    "aXQoIk9sbGFtYSByZXNwb25kcy4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3Nh"
    "Z2UuZW1pdChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVl"
    "KQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJPbGxhbWEgaXMgbm90IHJ1bm5pbmcuIFN0YXJ0IE9sbGFtYSBhbmQgcmVzdGFydCB0aGUgZGVjay4iCiAgICAg"
    "ICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAg"
    "ICAgICAgZWxpZiBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsIChDbGF1ZGVBZGFwdG9yLCBPcGVuQUlBZGFwdG9yKSk6CiAgICAg"
    "ICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiVGVzdGluZyB0aGUgQVBJIGNvbm5lY3Rpb24uLi4iKQogICAgICAgICAgICAg"
    "ICAgaWYgc2VsZi5fYWRhcHRvci5pc19jb25uZWN0ZWQoKToKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgi"
    "QVBJIGtleSBhY2NlcHRlZC4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2Uu"
    "ZW1pdChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQog"
    "ICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoIkFQSSBrZXkgbWlzc2luZyBv"
    "ciBpbnZhbGlkLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgICAg"
    "ICBlbHNlOgogICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KCJVbmtub3duIG1vZGVsIHR5cGUgaW4gY29uZmlnLiIpCiAg"
    "ICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBl"
    "OgogICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoc3RyKGUpKQogICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChG"
    "YWxzZSkKCgojIOKUgOKUgCBTT1VORCBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNv"
    "dW5kV29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBQbGF5cyBhIHNvdW5kIG9mZiB0aGUgbWFpbiB0aHJlYWQuCiAgICBQcmV2"
    "ZW50cyBhbnkgYXVkaW8gb3BlcmF0aW9uIGZyb20gYmxvY2tpbmcgdGhlIFVJLgoKICAgIFVzYWdlOgogICAgICAgIHdvcmtlciA9"
    "IFNvdW5kV29ya2VyKCJhbGVydCIpCiAgICAgICAgd29ya2VyLnN0YXJ0KCkKICAgICAgICAjIHdvcmtlciBjbGVhbnMgdXAgb24g"
    "aXRzIG93biDigJQgbm8gcmVmZXJlbmNlIG5lZWRlZAogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHNvdW5kX25hbWU6"
    "IHN0cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fbmFtZSA9IHNvdW5kX25hbWUKICAgICAgICAj"
    "IEF1dG8tZGVsZXRlIHdoZW4gZG9uZQogICAgICAgIHNlbGYuZmluaXNoZWQuY29ubmVjdChzZWxmLmRlbGV0ZUxhdGVyKQoKICAg"
    "IGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIHBsYXlfc291bmQoc2VsZi5fbmFtZSkKICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgoKIyDilIDilIAgRkFDRSBUSU1FUiBNQU5BR0VSIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgApjbGFzcyBGb290ZXJTdHJpcFdpZGdldChWYW1waXJlU3RhdGVTdHJpcCk6CiAgICAiIiJHZW5lcmljIGZv"
    "b3RlciBzdHJpcCB3aWRnZXQgdXNlZCBieSB0aGUgcGVybWFuZW50IGxvd2VyIGJsb2NrLiIiIgoKCmNsYXNzIEZhY2VUaW1lck1h"
    "bmFnZXI6CiAgICAiIiIKICAgIE1hbmFnZXMgdGhlIDYwLXNlY29uZCBmYWNlIGRpc3BsYXkgdGltZXIuCgogICAgUnVsZXM6CiAg"
    "ICAtIEFmdGVyIHNlbnRpbWVudCBjbGFzc2lmaWNhdGlvbiwgZmFjZSBpcyBsb2NrZWQgZm9yIDYwIHNlY29uZHMuCiAgICAtIElm"
    "IHVzZXIgc2VuZHMgYSBuZXcgbWVzc2FnZSBkdXJpbmcgdGhlIDYwcywgZmFjZSBpbW1lZGlhdGVseQogICAgICBzd2l0Y2hlcyB0"
    "byAnYWxlcnQnIChsb2NrZWQgPSBGYWxzZSwgbmV3IGN5Y2xlIGJlZ2lucykuCiAgICAtIEFmdGVyIDYwcyB3aXRoIG5vIG5ldyBp"
    "bnB1dCwgcmV0dXJucyB0byAnbmV1dHJhbCcuCiAgICAtIE5ldmVyIGJsb2NrcyBhbnl0aGluZy4gUHVyZSB0aW1lciArIGNhbGxi"
    "YWNrIGxvZ2ljLgogICAgIiIiCgogICAgSE9MRF9TRUNPTkRTID0gNjAKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbWlycm9yOiAi"
    "TWlycm9yV2lkZ2V0IiwgZW1vdGlvbl9ibG9jazogIkVtb3Rpb25CbG9jayIpOgogICAgICAgIHNlbGYuX21pcnJvciAgPSBtaXJy"
    "b3IKICAgICAgICBzZWxmLl9lbW90aW9uID0gZW1vdGlvbl9ibG9jawogICAgICAgIHNlbGYuX3RpbWVyICAgPSBRVGltZXIoKQog"
    "ICAgICAgIHNlbGYuX3RpbWVyLnNldFNpbmdsZVNob3QoVHJ1ZSkKICAgICAgICBzZWxmLl90aW1lci50aW1lb3V0LmNvbm5lY3Qo"
    "c2VsZi5fcmV0dXJuX3RvX25ldXRyYWwpCiAgICAgICAgc2VsZi5fbG9ja2VkICA9IEZhbHNlCgogICAgZGVmIHNldF9mYWNlKHNl"
    "bGYsIGVtb3Rpb246IHN0cikgLT4gTm9uZToKICAgICAgICAiIiJTZXQgZmFjZSBhbmQgc3RhcnQgdGhlIDYwLXNlY29uZCBob2xk"
    "IHRpbWVyLiIiIgogICAgICAgIHNlbGYuX2xvY2tlZCA9IFRydWUKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoZW1vdGlv"
    "bikKICAgICAgICBzZWxmLl9lbW90aW9uLmFkZEVtb3Rpb24oZW1vdGlvbikKICAgICAgICBzZWxmLl90aW1lci5zdG9wKCkKICAg"
    "ICAgICBzZWxmLl90aW1lci5zdGFydChzZWxmLkhPTERfU0VDT05EUyAqIDEwMDApCgogICAgZGVmIGludGVycnVwdChzZWxmLCBu"
    "ZXdfZW1vdGlvbjogc3RyID0gImFsZXJ0IikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBDYWxsZWQgd2hlbiB1c2VyIHNl"
    "bmRzIGEgbmV3IG1lc3NhZ2UuCiAgICAgICAgSW50ZXJydXB0cyBhbnkgcnVubmluZyBob2xkLCBzZXRzIGFsZXJ0IGZhY2UgaW1t"
    "ZWRpYXRlbHkuCiAgICAgICAgIiIiCiAgICAgICAgc2VsZi5fdGltZXIuc3RvcCgpCiAgICAgICAgc2VsZi5fbG9ja2VkID0gRmFs"
    "c2UKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UobmV3X2Vtb3Rpb24pCiAgICAgICAgc2VsZi5fZW1vdGlvbi5hZGRFbW90"
    "aW9uKG5ld19lbW90aW9uKQoKICAgIGRlZiBfcmV0dXJuX3RvX25ldXRyYWwoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9s"
    "b2NrZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZSgibmV1dHJhbCIpCgogICAgQHByb3BlcnR5CiAgICBk"
    "ZWYgaXNfbG9ja2VkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIHNlbGYuX2xvY2tlZAoKCiMg4pSA4pSAIEdPT0dMRSBT"
    "RVJWSUNFIENMQVNTRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiMgUG9ydGVkIGZyb20gR3JpbVZlaWwgZGVjay4gSGFuZGxlcyBDYWxlbmRhciBhbmQgRHJpdmUv"
    "RG9jcyBhdXRoICsgQVBJLgojIENyZWRlbnRpYWxzIHBhdGg6IGNmZ19wYXRoKCJnb29nbGUiKSAvICJnb29nbGVfY3JlZGVudGlh"
    "bHMuanNvbiIKIyBUb2tlbiBwYXRoOiAgICAgICBjZmdfcGF0aCgiZ29vZ2xlIikgLyAidG9rZW4uanNvbiIKCmNsYXNzIEdvb2ds"
    "ZUNhbGVuZGFyU2VydmljZToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBjcmVkZW50aWFsc19wYXRoOiBQYXRoLCB0b2tlbl9wYXRo"
    "OiBQYXRoKToKICAgICAgICBzZWxmLmNyZWRlbnRpYWxzX3BhdGggPSBjcmVkZW50aWFsc19wYXRoCiAgICAgICAgc2VsZi50b2tl"
    "bl9wYXRoID0gdG9rZW5fcGF0aAogICAgICAgIHNlbGYuX3NlcnZpY2UgPSBOb25lCgogICAgZGVmIF9wZXJzaXN0X3Rva2VuKHNl"
    "bGYsIGNyZWRzKToKICAgICAgICBzZWxmLnRva2VuX3BhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1"
    "ZSkKICAgICAgICBzZWxmLnRva2VuX3BhdGgud3JpdGVfdGV4dChjcmVkcy50b19qc29uKCksIGVuY29kaW5nPSJ1dGYtOCIpCgog"
    "ICAgZGVmIF9idWlsZF9zZXJ2aWNlKHNlbGYpOgogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBDcmVkZW50aWFscyBwYXRo"
    "OiB7c2VsZi5jcmVkZW50aWFsc19wYXRofSIpCiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIFRva2VuIHBhdGg6IHtzZWxm"
    "LnRva2VuX3BhdGh9IikKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gQ3JlZGVudGlhbHMgZmlsZSBleGlzdHM6IHtzZWxm"
    "LmNyZWRlbnRpYWxzX3BhdGguZXhpc3RzKCl9IikKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gVG9rZW4gZmlsZSBleGlz"
    "dHM6IHtzZWxmLnRva2VuX3BhdGguZXhpc3RzKCl9IikKCiAgICAgICAgaWYgbm90IEdPT0dMRV9BUElfT0s6CiAgICAgICAgICAg"
    "IGRldGFpbCA9IEdPT0dMRV9JTVBPUlRfRVJST1Igb3IgInVua25vd24gSW1wb3J0RXJyb3IiCiAgICAgICAgICAgIHJhaXNlIFJ1"
    "bnRpbWVFcnJvcihmIk1pc3NpbmcgR29vZ2xlIENhbGVuZGFyIFB5dGhvbiBkZXBlbmRlbmN5OiB7ZGV0YWlsfSIpCiAgICAgICAg"
    "aWYgbm90IHNlbGYuY3JlZGVudGlhbHNfcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgcmFpc2UgRmlsZU5vdEZvdW5kRXJyb3Io"
    "CiAgICAgICAgICAgICAgICBmIkdvb2dsZSBjcmVkZW50aWFscy9hdXRoIGNvbmZpZ3VyYXRpb24gbm90IGZvdW5kOiB7c2VsZi5j"
    "cmVkZW50aWFsc19wYXRofSIKICAgICAgICAgICAgKQoKICAgICAgICBjcmVkcyA9IE5vbmUKICAgICAgICBsaW5rX2VzdGFibGlz"
    "aGVkID0gRmFsc2UKICAgICAgICBpZiBzZWxmLnRva2VuX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIGNyZWRzID0gR29vZ2xl"
    "Q3JlZGVudGlhbHMuZnJvbV9hdXRob3JpemVkX3VzZXJfZmlsZShzdHIoc2VsZi50b2tlbl9wYXRoKSwgR09PR0xFX1NDT1BFUykK"
    "CiAgICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLnZhbGlkIGFuZCBub3QgY3JlZHMuaGFzX3Njb3BlcyhHT09HTEVfU0NPUEVTKToK"
    "ICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKEdPT0dMRV9TQ09QRV9SRUFVVEhfTVNHKQoKICAgICAgICBpZiBjcmVkcyBh"
    "bmQgY3JlZHMuZXhwaXJlZCBhbmQgY3JlZHMucmVmcmVzaF90b2tlbjoKICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10g"
    "UmVmcmVzaGluZyBleHBpcmVkIEdvb2dsZSB0b2tlbi4iKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjcmVkcy5y"
    "ZWZyZXNoKEdvb2dsZUF1dGhSZXF1ZXN0KCkpCiAgICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAg"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKAogICAgICAg"
    "ICAgICAgICAgICAgIGYiR29vZ2xlIHRva2VuIHJlZnJlc2ggZmFpbGVkIGFmdGVyIHNjb3BlIGV4cGFuc2lvbjoge2V4fS4ge0dP"
    "T0dMRV9TQ09QRV9SRUFVVEhfTVNHfSIKICAgICAgICAgICAgICAgICkgZnJvbSBleAoKICAgICAgICBpZiBub3QgY3JlZHMgb3Ig"
    "bm90IGNyZWRzLnZhbGlkOgogICAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBTdGFydGluZyBPQXV0aCBmbG93IGZvciBH"
    "b29nbGUgQ2FsZW5kYXIuIikKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgZmxvdyA9IEluc3RhbGxlZEFwcEZsb3cu"
    "ZnJvbV9jbGllbnRfc2VjcmV0c19maWxlKHN0cihzZWxmLmNyZWRlbnRpYWxzX3BhdGgpLCBHT09HTEVfU0NPUEVTKQogICAgICAg"
    "ICAgICAgICAgY3JlZHMgPSBmbG93LnJ1bl9sb2NhbF9zZXJ2ZXIoCiAgICAgICAgICAgICAgICAgICAgcG9ydD0wLAogICAgICAg"
    "ICAgICAgICAgICAgIG9wZW5fYnJvd3Nlcj1UcnVlLAogICAgICAgICAgICAgICAgICAgIGF1dGhvcml6YXRpb25fcHJvbXB0X21l"
    "c3NhZ2U9KAogICAgICAgICAgICAgICAgICAgICAgICAiT3BlbiB0aGlzIFVSTCBpbiB5b3VyIGJyb3dzZXIgdG8gYXV0aG9yaXpl"
    "IHRoaXMgYXBwbGljYXRpb246XG57dXJsfSIKICAgICAgICAgICAgICAgICAgICApLAogICAgICAgICAgICAgICAgICAgIHN1Y2Nl"
    "c3NfbWVzc2FnZT0iQXV0aGVudGljYXRpb24gY29tcGxldGUuIFlvdSBtYXkgY2xvc2UgdGhpcyB3aW5kb3cuIiwKICAgICAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgICAgIGlmIG5vdCBjcmVkczoKICAgICAgICAgICAgICAgICAgICByYWlzZSBSdW50aW1lRXJy"
    "b3IoIk9BdXRoIGZsb3cgcmV0dXJuZWQgbm8gY3JlZGVudGlhbHMgb2JqZWN0LiIpCiAgICAgICAgICAgICAgICBzZWxmLl9wZXJz"
    "aXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gdG9rZW4uanNvbiB3cml0dGVuIHN1"
    "Y2Nlc3NmdWxseS4iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgcHJpbnQoZiJb"
    "R0NhbF1bRVJST1JdIE9BdXRoIGZsb3cgZmFpbGVkOiB7dHlwZShleCkuX19uYW1lX199OiB7ZXh9IikKICAgICAgICAgICAgICAg"
    "IHJhaXNlCiAgICAgICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBUcnVlCgogICAgICAgIHNlbGYuX3NlcnZpY2UgPSBnb29nbGVf"
    "YnVpbGQoImNhbGVuZGFyIiwgInYzIiwgY3JlZGVudGlhbHM9Y3JlZHMpCiAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gQXV0"
    "aGVudGljYXRlZCBHb29nbGUgQ2FsZW5kYXIgc2VydmljZSBjcmVhdGVkIHN1Y2Nlc3NmdWxseS4iKQogICAgICAgIHJldHVybiBs"
    "aW5rX2VzdGFibGlzaGVkCgogICAgZGVmIF9nZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKHNlbGYpIC0+IHN0cjoKICAgICAgICBs"
    "b2NhbF90emluZm8gPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudHppbmZvCiAgICAgICAgY2FuZGlkYXRlcyA9IFtdCiAg"
    "ICAgICAgaWYgbG9jYWxfdHppbmZvIGlzIG5vdCBOb25lOgogICAgICAgICAgICBjYW5kaWRhdGVzLmV4dGVuZChbCiAgICAgICAg"
    "ICAgICAgICBnZXRhdHRyKGxvY2FsX3R6aW5mbywgImtleSIsIE5vbmUpLAogICAgICAgICAgICAgICAgZ2V0YXR0cihsb2NhbF90"
    "emluZm8sICJ6b25lIiwgTm9uZSksCiAgICAgICAgICAgICAgICBzdHIobG9jYWxfdHppbmZvKSwKICAgICAgICAgICAgICAgIGxv"
    "Y2FsX3R6aW5mby50em5hbWUoZGF0ZXRpbWUubm93KCkpLAogICAgICAgICAgICBdKQoKICAgICAgICBlbnZfdHogPSBvcy5lbnZp"
    "cm9uLmdldCgiVFoiKQogICAgICAgIGlmIGVudl90ejoKICAgICAgICAgICAgY2FuZGlkYXRlcy5hcHBlbmQoZW52X3R6KQoKICAg"
    "ICAgICBmb3IgY2FuZGlkYXRlIGluIGNhbmRpZGF0ZXM6CiAgICAgICAgICAgIGlmIG5vdCBjYW5kaWRhdGU6CiAgICAgICAgICAg"
    "ICAgICBjb250aW51ZQogICAgICAgICAgICBtYXBwZWQgPSBXSU5ET1dTX1RaX1RPX0lBTkEuZ2V0KGNhbmRpZGF0ZSwgY2FuZGlk"
    "YXRlKQogICAgICAgICAgICBpZiAiLyIgaW4gbWFwcGVkOgogICAgICAgICAgICAgICAgcmV0dXJuIG1hcHBlZAoKICAgICAgICBw"
    "cmludCgKICAgICAgICAgICAgIltHQ2FsXVtXQVJOXSBVbmFibGUgdG8gcmVzb2x2ZSBsb2NhbCBJQU5BIHRpbWV6b25lLiAiCiAg"
    "ICAgICAgICAgIGYiRmFsbGluZyBiYWNrIHRvIHtERUZBVUxUX0dPT0dMRV9JQU5BX1RJTUVaT05FfS4iCiAgICAgICAgKQogICAg"
    "ICAgIHJldHVybiBERUZBVUxUX0dPT0dMRV9JQU5BX1RJTUVaT05FCgogICAgZGVmIGNyZWF0ZV9ldmVudF9mb3JfdGFzayhzZWxm"
    "LCB0YXNrOiBkaWN0KToKICAgICAgICBkdWVfYXQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUodGFzay5nZXQoImR1ZV9hdCIpIG9y"
    "IHRhc2suZ2V0KCJkdWUiKSwgY29udGV4dD0iZ29vZ2xlX2NyZWF0ZV9ldmVudF9kdWUiKQogICAgICAgIGlmIG5vdCBkdWVfYXQ6"
    "CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIlRhc2sgZHVlIHRpbWUgaXMgbWlzc2luZyBvciBpbnZhbGlkLiIpCgogICAg"
    "ICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAg"
    "bGlua19lc3RhYmxpc2hlZCA9IHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoKICAgICAgICBkdWVfbG9jYWwgPSBub3JtYWxpemVfZGF0"
    "ZXRpbWVfZm9yX2NvbXBhcmUoZHVlX2F0LCBjb250ZXh0PSJnb29nbGVfY3JlYXRlX2V2ZW50X2R1ZV9sb2NhbCIpCiAgICAgICAg"
    "c3RhcnRfZHQgPSBkdWVfbG9jYWwucmVwbGFjZShtaWNyb3NlY29uZD0wLCB0emluZm89Tm9uZSkKICAgICAgICBlbmRfZHQgPSBz"
    "dGFydF9kdCArIHRpbWVkZWx0YShtaW51dGVzPTMwKQogICAgICAgIHR6X25hbWUgPSBzZWxmLl9nZXRfZ29vZ2xlX2V2ZW50X3Rp"
    "bWV6b25lKCkKCiAgICAgICAgZXZlbnRfcGF5bG9hZCA9IHsKICAgICAgICAgICAgInN1bW1hcnkiOiAodGFzay5nZXQoInRleHQi"
    "KSBvciAiUmVtaW5kZXIiKS5zdHJpcCgpLAogICAgICAgICAgICAic3RhcnQiOiB7ImRhdGVUaW1lIjogc3RhcnRfZHQuaXNvZm9y"
    "bWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9LAogICAgICAgICAgICAiZW5kIjogeyJkYXRlVGlt"
    "ZSI6IGVuZF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25lIjogdHpfbmFtZX0sCiAgICAgICAgfQog"
    "ICAgICAgIHRhcmdldF9jYWxlbmRhcl9pZCA9ICJwcmltYXJ5IgogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBUYXJnZXQg"
    "Y2FsZW5kYXIgSUQ6IHt0YXJnZXRfY2FsZW5kYXJfaWR9IikKICAgICAgICBwcmludCgKICAgICAgICAgICAgIltHQ2FsXVtERUJV"
    "R10gRXZlbnQgcGF5bG9hZCBiZWZvcmUgaW5zZXJ0OiAiCiAgICAgICAgICAgIGYidGl0bGU9J3tldmVudF9wYXlsb2FkLmdldCgn"
    "c3VtbWFyeScpfScsICIKICAgICAgICAgICAgZiJzdGFydC5kYXRlVGltZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdzdGFydCcsIHt9"
    "KS5nZXQoJ2RhdGVUaW1lJyl9JywgIgogICAgICAgICAgICBmInN0YXJ0LnRpbWVab25lPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ3N0"
    "YXJ0Jywge30pLmdldCgndGltZVpvbmUnKX0nLCAiCiAgICAgICAgICAgIGYiZW5kLmRhdGVUaW1lPSd7ZXZlbnRfcGF5bG9hZC5n"
    "ZXQoJ2VuZCcsIHt9KS5nZXQoJ2RhdGVUaW1lJyl9JywgIgogICAgICAgICAgICBmImVuZC50aW1lWm9uZT0ne2V2ZW50X3BheWxv"
    "YWQuZ2V0KCdlbmQnLCB7fSkuZ2V0KCd0aW1lWm9uZScpfSciCiAgICAgICAgKQogICAgICAgIHRyeToKICAgICAgICAgICAgY3Jl"
    "YXRlZCA9IHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuaW5zZXJ0KGNhbGVuZGFySWQ9dGFyZ2V0X2NhbGVuZGFyX2lkLCBib2R5PWV2"
    "ZW50X3BheWxvYWQpLmV4ZWN1dGUoKQogICAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBFdmVudCBpbnNlcnQgY2FsbCBz"
    "dWNjZWVkZWQuIikKICAgICAgICAgICAgcmV0dXJuIGNyZWF0ZWQuZ2V0KCJpZCIpLCBsaW5rX2VzdGFibGlzaGVkCiAgICAgICAg"
    "ZXhjZXB0IEdvb2dsZUh0dHBFcnJvciBhcyBhcGlfZXg6CiAgICAgICAgICAgIGFwaV9kZXRhaWwgPSAiIgogICAgICAgICAgICBp"
    "ZiBoYXNhdHRyKGFwaV9leCwgImNvbnRlbnQiKSBhbmQgYXBpX2V4LmNvbnRlbnQ6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICAgICAgYXBpX2RldGFpbCA9IGFwaV9leC5jb250ZW50LmRlY29kZSgidXRmLTgiLCBlcnJvcnM9InJlcGxhY2Ui"
    "KQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBhcGlfZGV0YWlsID0gc3RyKGFw"
    "aV9leC5jb250ZW50KQogICAgICAgICAgICBkZXRhaWxfbXNnID0gZiJHb29nbGUgQVBJIGVycm9yOiB7YXBpX2V4fSIKICAgICAg"
    "ICAgICAgaWYgYXBpX2RldGFpbDoKICAgICAgICAgICAgICAgIGRldGFpbF9tc2cgPSBmIntkZXRhaWxfbXNnfSB8IEFQSSBib2R5"
    "OiB7YXBpX2RldGFpbH0iCiAgICAgICAgICAgIHByaW50KGYiW0dDYWxdW0VSUk9SXSBFdmVudCBpbnNlcnQgZmFpbGVkOiB7ZGV0"
    "YWlsX21zZ30iKQogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoZGV0YWlsX21zZykgZnJvbSBhcGlfZXgKICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBwcmludChmIltHQ2FsXVtFUlJPUl0gRXZlbnQgaW5zZXJ0IGZhaWxl"
    "ZCB3aXRoIHVuZXhwZWN0ZWQgZXJyb3I6IHtleH0iKQogICAgICAgICAgICByYWlzZQoKICAgIGRlZiBjcmVhdGVfZXZlbnRfd2l0"
    "aF9wYXlsb2FkKHNlbGYsIGV2ZW50X3BheWxvYWQ6IGRpY3QsIGNhbGVuZGFyX2lkOiBzdHIgPSAicHJpbWFyeSIpOgogICAgICAg"
    "IGlmIG5vdCBpc2luc3RhbmNlKGV2ZW50X3BheWxvYWQsIGRpY3QpOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJHb29n"
    "bGUgZXZlbnQgcGF5bG9hZCBtdXN0IGJlIGEgZGljdGlvbmFyeS4iKQogICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQog"
    "ICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IHNlbGYuX2J1aWxk"
    "X3NlcnZpY2UoKQogICAgICAgIGNyZWF0ZWQgPSBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmluc2VydChjYWxlbmRhcklkPShjYWxl"
    "bmRhcl9pZCBvciAicHJpbWFyeSIpLCBib2R5PWV2ZW50X3BheWxvYWQpLmV4ZWN1dGUoKQogICAgICAgIHJldHVybiBjcmVhdGVk"
    "LmdldCgiaWQiKSwgbGlua19lc3RhYmxpc2hlZAoKICAgIGRlZiBsaXN0X3ByaW1hcnlfZXZlbnRzKHNlbGYsCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgdGltZV9taW46IHN0ciA9IE5vbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgc3luY190"
    "b2tlbjogc3RyID0gTm9uZSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICBtYXhfcmVzdWx0czogaW50ID0gMjUwMCk6CiAg"
    "ICAgICAgIiIiCiAgICAgICAgRmV0Y2ggY2FsZW5kYXIgZXZlbnRzIHdpdGggcGFnaW5hdGlvbiBhbmQgc3luY1Rva2VuIHN1cHBv"
    "cnQuCiAgICAgICAgUmV0dXJucyAoZXZlbnRzX2xpc3QsIG5leHRfc3luY190b2tlbikuCgogICAgICAgIHN5bmNfdG9rZW4gbW9k"
    "ZTogaW5jcmVtZW50YWwg4oCUIHJldHVybnMgT05MWSBjaGFuZ2VzIChhZGRzL2VkaXRzL2NhbmNlbHMpLgogICAgICAgIHRpbWVf"
    "bWluIG1vZGU6ICAgZnVsbCBzeW5jIGZyb20gYSBkYXRlLgogICAgICAgIEJvdGggdXNlIHNob3dEZWxldGVkPVRydWUgc28gY2Fu"
    "Y2VsbGF0aW9ucyBjb21lIHRocm91Z2guCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25lOgogICAg"
    "ICAgICAgICBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKCiAgICAgICAgaWYgc3luY190b2tlbjoKICAgICAgICAgICAgcXVlcnkgPSB7"
    "CiAgICAgICAgICAgICAgICAiY2FsZW5kYXJJZCI6ICJwcmltYXJ5IiwKICAgICAgICAgICAgICAgICJzaW5nbGVFdmVudHMiOiBU"
    "cnVlLAogICAgICAgICAgICAgICAgInNob3dEZWxldGVkIjogVHJ1ZSwKICAgICAgICAgICAgICAgICJzeW5jVG9rZW4iOiBzeW5j"
    "X3Rva2VuLAogICAgICAgICAgICB9CiAgICAgICAgZWxzZToKICAgICAgICAgICAgcXVlcnkgPSB7CiAgICAgICAgICAgICAgICAi"
    "Y2FsZW5kYXJJZCI6ICJwcmltYXJ5IiwKICAgICAgICAgICAgICAgICJzaW5nbGVFdmVudHMiOiBUcnVlLAogICAgICAgICAgICAg"
    "ICAgInNob3dEZWxldGVkIjogVHJ1ZSwKICAgICAgICAgICAgICAgICJtYXhSZXN1bHRzIjogMjUwLAogICAgICAgICAgICAgICAg"
    "Im9yZGVyQnkiOiAic3RhcnRUaW1lIiwKICAgICAgICAgICAgfQogICAgICAgICAgICBpZiB0aW1lX21pbjoKICAgICAgICAgICAg"
    "ICAgIHF1ZXJ5WyJ0aW1lTWluIl0gPSB0aW1lX21pbgoKICAgICAgICBhbGxfZXZlbnRzID0gW10KICAgICAgICBuZXh0X3N5bmNf"
    "dG9rZW4gPSBOb25lCiAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAgICAgcmVzcG9uc2UgPSBzZWxmLl9zZXJ2aWNlLmV2ZW50"
    "cygpLmxpc3QoKipxdWVyeSkuZXhlY3V0ZSgpCiAgICAgICAgICAgIGFsbF9ldmVudHMuZXh0ZW5kKHJlc3BvbnNlLmdldCgiaXRl"
    "bXMiLCBbXSkpCiAgICAgICAgICAgIG5leHRfc3luY190b2tlbiA9IHJlc3BvbnNlLmdldCgibmV4dFN5bmNUb2tlbiIpCiAgICAg"
    "ICAgICAgIHBhZ2VfdG9rZW4gPSByZXNwb25zZS5nZXQoIm5leHRQYWdlVG9rZW4iKQogICAgICAgICAgICBpZiBub3QgcGFnZV90"
    "b2tlbjoKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHF1ZXJ5LnBvcCgic3luY1Rva2VuIiwgTm9uZSkKICAgICAg"
    "ICAgICAgcXVlcnlbInBhZ2VUb2tlbiJdID0gcGFnZV90b2tlbgoKICAgICAgICByZXR1cm4gYWxsX2V2ZW50cywgbmV4dF9zeW5j"
    "X3Rva2VuCgogICAgZGVmIGdldF9ldmVudChzZWxmLCBnb29nbGVfZXZlbnRfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGdvb2ds"
    "ZV9ldmVudF9pZDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAg"
    "ICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIHNlbGYuX3NlcnZpY2Uu"
    "ZXZlbnRzKCkuZ2V0KGNhbGVuZGFySWQ9InByaW1hcnkiLCBldmVudElkPWdvb2dsZV9ldmVudF9pZCkuZXhlY3V0ZSgpCiAgICAg"
    "ICAgZXhjZXB0IEdvb2dsZUh0dHBFcnJvciBhcyBhcGlfZXg6CiAgICAgICAgICAgIGNvZGUgPSBnZXRhdHRyKGdldGF0dHIoYXBp"
    "X2V4LCAicmVzcCIsIE5vbmUpLCAic3RhdHVzIiwgTm9uZSkKICAgICAgICAgICAgaWYgY29kZSBpbiAoNDA0LCA0MTApOgogICAg"
    "ICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICAgICAgcmFpc2UKCiAgICBkZWYgZGVsZXRlX2V2ZW50X2Zvcl90YXNrKHNl"
    "bGYsIGdvb2dsZV9ldmVudF9pZDogc3RyKToKICAgICAgICBpZiBub3QgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAgICByYWlz"
    "ZSBWYWx1ZUVycm9yKCJHb29nbGUgZXZlbnQgaWQgaXMgbWlzc2luZzsgY2Fubm90IGRlbGV0ZSBldmVudC4iKQoKICAgICAgICBp"
    "ZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoKICAgICAgICB0YXJnZXRf"
    "Y2FsZW5kYXJfaWQgPSAicHJpbWFyeSIKICAgICAgICBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmRlbGV0ZShjYWxlbmRhcklkPXRh"
    "cmdldF9jYWxlbmRhcl9pZCwgZXZlbnRJZD1nb29nbGVfZXZlbnRfaWQpLmV4ZWN1dGUoKQoKCmNsYXNzIEdvb2dsZURvY3NEcml2"
    "ZVNlcnZpY2U6CiAgICBkZWYgX19pbml0X18oc2VsZiwgY3JlZGVudGlhbHNfcGF0aDogUGF0aCwgdG9rZW5fcGF0aDogUGF0aCwg"
    "bG9nZ2VyPU5vbmUpOgogICAgICAgIHNlbGYuY3JlZGVudGlhbHNfcGF0aCA9IGNyZWRlbnRpYWxzX3BhdGgKICAgICAgICBzZWxm"
    "LnRva2VuX3BhdGggPSB0b2tlbl9wYXRoCiAgICAgICAgc2VsZi5fZHJpdmVfc2VydmljZSA9IE5vbmUKICAgICAgICBzZWxmLl9k"
    "b2NzX3NlcnZpY2UgPSBOb25lCiAgICAgICAgc2VsZi5fbG9nZ2VyID0gbG9nZ2VyCgogICAgZGVmIF9sb2coc2VsZiwgbWVzc2Fn"
    "ZTogc3RyLCBsZXZlbDogc3RyID0gIklORk8iKToKICAgICAgICBpZiBjYWxsYWJsZShzZWxmLl9sb2dnZXIpOgogICAgICAgICAg"
    "ICBzZWxmLl9sb2dnZXIobWVzc2FnZSwgbGV2ZWw9bGV2ZWwpCgogICAgZGVmIF9wZXJzaXN0X3Rva2VuKHNlbGYsIGNyZWRzKToK"
    "ICAgICAgICBzZWxmLnRva2VuX3BhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICBz"
    "ZWxmLnRva2VuX3BhdGgud3JpdGVfdGV4dChjcmVkcy50b19qc29uKCksIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgZGVmIF9hdXRo"
    "ZW50aWNhdGUoc2VsZik6CiAgICAgICAgc2VsZi5fbG9nKCJEcml2ZSBhdXRoIHN0YXJ0LiIsIGxldmVsPSJJTkZPIikKICAgICAg"
    "ICBzZWxmLl9sb2coIkRvY3MgYXV0aCBzdGFydC4iLCBsZXZlbD0iSU5GTyIpCgogICAgICAgIGlmIG5vdCBHT09HTEVfQVBJX09L"
    "OgogICAgICAgICAgICBkZXRhaWwgPSBHT09HTEVfSU1QT1JUX0VSUk9SIG9yICJ1bmtub3duIEltcG9ydEVycm9yIgogICAgICAg"
    "ICAgICByYWlzZSBSdW50aW1lRXJyb3IoZiJNaXNzaW5nIEdvb2dsZSBQeXRob24gZGVwZW5kZW5jeToge2RldGFpbH0iKQogICAg"
    "ICAgIGlmIG5vdCBzZWxmLmNyZWRlbnRpYWxzX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJhaXNlIEZpbGVOb3RGb3VuZEVy"
    "cm9yKAogICAgICAgICAgICAgICAgZiJHb29nbGUgY3JlZGVudGlhbHMvYXV0aCBjb25maWd1cmF0aW9uIG5vdCBmb3VuZDoge3Nl"
    "bGYuY3JlZGVudGlhbHNfcGF0aH0iCiAgICAgICAgICAgICkKCiAgICAgICAgY3JlZHMgPSBOb25lCiAgICAgICAgaWYgc2VsZi50"
    "b2tlbl9wYXRoLmV4aXN0cygpOgogICAgICAgICAgICBjcmVkcyA9IEdvb2dsZUNyZWRlbnRpYWxzLmZyb21fYXV0aG9yaXplZF91"
    "c2VyX2ZpbGUoc3RyKHNlbGYudG9rZW5fcGF0aCksIEdPT0dMRV9TQ09QRVMpCgogICAgICAgIGlmIGNyZWRzIGFuZCBjcmVkcy52"
    "YWxpZCBhbmQgbm90IGNyZWRzLmhhc19zY29wZXMoR09PR0xFX1NDT1BFUyk6CiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJv"
    "cihHT09HTEVfU0NPUEVfUkVBVVRIX01TRykKCiAgICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLmV4cGlyZWQgYW5kIGNyZWRzLnJl"
    "ZnJlc2hfdG9rZW46CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNyZWRzLnJlZnJlc2goR29vZ2xlQXV0aFJlcXVl"
    "c3QoKSkKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b24gYXMgZXg6CiAgICAgICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoCiAgICAgICAgICAgICAgICAgICAgZiJHb29nbGUg"
    "dG9rZW4gcmVmcmVzaCBmYWlsZWQgYWZ0ZXIgc2NvcGUgZXhwYW5zaW9uOiB7ZXh9LiB7R09PR0xFX1NDT1BFX1JFQVVUSF9NU0d9"
    "IgogICAgICAgICAgICAgICAgKSBmcm9tIGV4CgogICAgICAgIGlmIG5vdCBjcmVkcyBvciBub3QgY3JlZHMudmFsaWQ6CiAgICAg"
    "ICAgICAgIHNlbGYuX2xvZygiU3RhcnRpbmcgT0F1dGggZmxvdyBmb3IgR29vZ2xlIERyaXZlL0RvY3MuIiwgbGV2ZWw9IklORk8i"
    "KQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBmbG93ID0gSW5zdGFsbGVkQXBwRmxvdy5mcm9tX2NsaWVudF9zZWNy"
    "ZXRzX2ZpbGUoc3RyKHNlbGYuY3JlZGVudGlhbHNfcGF0aCksIEdPT0dMRV9TQ09QRVMpCiAgICAgICAgICAgICAgICBjcmVkcyA9"
    "IGZsb3cucnVuX2xvY2FsX3NlcnZlcigKICAgICAgICAgICAgICAgICAgICBwb3J0PTAsCiAgICAgICAgICAgICAgICAgICAgb3Bl"
    "bl9icm93c2VyPVRydWUsCiAgICAgICAgICAgICAgICAgICAgYXV0aG9yaXphdGlvbl9wcm9tcHRfbWVzc2FnZT0oCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJPcGVuIHRoaXMgVVJMIGluIHlvdXIgYnJvd3NlciB0byBhdXRob3JpemUgdGhpcyBhcHBsaWNhdGlv"
    "bjpcbnt1cmx9IgogICAgICAgICAgICAgICAgICAgICksCiAgICAgICAgICAgICAgICAgICAgc3VjY2Vzc19tZXNzYWdlPSJBdXRo"
    "ZW50aWNhdGlvbiBjb21wbGV0ZS4gWW91IG1heSBjbG9zZSB0aGlzIHdpbmRvdy4iLAogICAgICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICAgICAgaWYgbm90IGNyZWRzOgogICAgICAgICAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigiT0F1dGggZmxvdyBy"
    "ZXR1cm5lZCBubyBjcmVkZW50aWFscyBvYmplY3QuIikKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMp"
    "CiAgICAgICAgICAgICAgICBzZWxmLl9sb2coIltHQ2FsXVtERUJVR10gdG9rZW4uanNvbiB3cml0dGVuIHN1Y2Nlc3NmdWxseS4i"
    "LCBsZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9s"
    "b2coZiJPQXV0aCBmbG93IGZhaWxlZDoge3R5cGUoZXgpLl9fbmFtZV9ffToge2V4fSIsIGxldmVsPSJFUlJPUiIpCiAgICAgICAg"
    "ICAgICAgICByYWlzZQoKICAgICAgICByZXR1cm4gY3JlZHMKCiAgICBkZWYgZW5zdXJlX3NlcnZpY2VzKHNlbGYpOgogICAgICAg"
    "IGlmIHNlbGYuX2RyaXZlX3NlcnZpY2UgaXMgbm90IE5vbmUgYW5kIHNlbGYuX2RvY3Nfc2VydmljZSBpcyBub3QgTm9uZToKICAg"
    "ICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAgICBjcmVkcyA9IHNlbGYuX2F1dGhlbnRpY2F0ZSgpCiAgICAg"
    "ICAgICAgIHNlbGYuX2RyaXZlX3NlcnZpY2UgPSBnb29nbGVfYnVpbGQoImRyaXZlIiwgInYzIiwgY3JlZGVudGlhbHM9Y3JlZHMp"
    "CiAgICAgICAgICAgIHNlbGYuX2RvY3Nfc2VydmljZSA9IGdvb2dsZV9idWlsZCgiZG9jcyIsICJ2MSIsIGNyZWRlbnRpYWxzPWNy"
    "ZWRzKQogICAgICAgICAgICBzZWxmLl9sb2coIkRyaXZlIGF1dGggc3VjY2Vzcy4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgICAg"
    "IHNlbGYuX2xvZygiRG9jcyBhdXRoIHN1Y2Nlc3MuIiwgbGV2ZWw9IklORk8iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMg"
    "ZXg6CiAgICAgICAgICAgIHNlbGYuX2xvZyhmIkRyaXZlIGF1dGggZmFpbHVyZToge2V4fSIsIGxldmVsPSJFUlJPUiIpCiAgICAg"
    "ICAgICAgIHNlbGYuX2xvZyhmIkRvY3MgYXV0aCBmYWlsdXJlOiB7ZXh9IiwgbGV2ZWw9IkVSUk9SIikKICAgICAgICAgICAgcmFp"
    "c2UKCiAgICBkZWYgbGlzdF9mb2xkZXJfaXRlbXMoc2VsZiwgZm9sZGVyX2lkOiBzdHIgPSAicm9vdCIsIHBhZ2Vfc2l6ZTogaW50"
    "ID0gMTAwKToKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgc2FmZV9mb2xkZXJfaWQgPSAoZm9sZGVyX2lk"
    "IG9yICJyb290Iikuc3RyaXAoKSBvciAicm9vdCIKICAgICAgICBzZWxmLl9sb2coZiJEcml2ZSBmaWxlIGxpc3QgZmV0Y2ggc3Rh"
    "cnRlZC4gZm9sZGVyX2lkPXtzYWZlX2ZvbGRlcl9pZH0iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgcmVzcG9uc2UgPSBzZWxmLl9k"
    "cml2ZV9zZXJ2aWNlLmZpbGVzKCkubGlzdCgKICAgICAgICAgICAgcT1mIid7c2FmZV9mb2xkZXJfaWR9JyBpbiBwYXJlbnRzIGFu"
    "ZCB0cmFzaGVkPWZhbHNlIiwKICAgICAgICAgICAgcGFnZVNpemU9bWF4KDEsIG1pbihpbnQocGFnZV9zaXplIG9yIDEwMCksIDIw"
    "MCkpLAogICAgICAgICAgICBvcmRlckJ5PSJmb2xkZXIsbmFtZSxtb2RpZmllZFRpbWUgZGVzYyIsCiAgICAgICAgICAgIGZpZWxk"
    "cz0oCiAgICAgICAgICAgICAgICAiZmlsZXMoIgogICAgICAgICAgICAgICAgImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1l"
    "LHdlYlZpZXdMaW5rLHBhcmVudHMsc2l6ZSwiCiAgICAgICAgICAgICAgICAibGFzdE1vZGlmeWluZ1VzZXIoZGlzcGxheU5hbWUs"
    "ZW1haWxBZGRyZXNzKSIKICAgICAgICAgICAgICAgICIpIgogICAgICAgICAgICApLAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAg"
    "ICAgZmlsZXMgPSByZXNwb25zZS5nZXQoImZpbGVzIiwgW10pCiAgICAgICAgZm9yIGl0ZW0gaW4gZmlsZXM6CiAgICAgICAgICAg"
    "IG1pbWUgPSAoaXRlbS5nZXQoIm1pbWVUeXBlIikgb3IgIiIpLnN0cmlwKCkKICAgICAgICAgICAgaXRlbVsiaXNfZm9sZGVyIl0g"
    "PSBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVyIgogICAgICAgICAgICBpdGVtWyJpc19nb29nbGVf"
    "ZG9jIl0gPSBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZG9jdW1lbnQiCiAgICAgICAgc2VsZi5fbG9nKGYi"
    "RHJpdmUgaXRlbXMgcmV0dXJuZWQ6IHtsZW4oZmlsZXMpfSBmb2xkZXJfaWQ9e3NhZmVfZm9sZGVyX2lkfSIsIGxldmVsPSJJTkZP"
    "IikKICAgICAgICByZXR1cm4gZmlsZXMKCiAgICBkZWYgZ2V0X2RvY19wcmV2aWV3KHNlbGYsIGRvY19pZDogc3RyLCBtYXhfY2hh"
    "cnM6IGludCA9IDE4MDApOgogICAgICAgIGlmIG5vdCBkb2NfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkRvY3Vt"
    "ZW50IGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIGRvYyA9IHNlbGYuX2Rv"
    "Y3Nfc2VydmljZS5kb2N1bWVudHMoKS5nZXQoZG9jdW1lbnRJZD1kb2NfaWQpLmV4ZWN1dGUoKQogICAgICAgIHRpdGxlID0gZG9j"
    "LmdldCgidGl0bGUiKSBvciAiVW50aXRsZWQiCiAgICAgICAgYm9keSA9IGRvYy5nZXQoImJvZHkiLCB7fSkuZ2V0KCJjb250ZW50"
    "IiwgW10pCiAgICAgICAgY2h1bmtzID0gW10KICAgICAgICBmb3IgYmxvY2sgaW4gYm9keToKICAgICAgICAgICAgcGFyYWdyYXBo"
    "ID0gYmxvY2suZ2V0KCJwYXJhZ3JhcGgiKQogICAgICAgICAgICBpZiBub3QgcGFyYWdyYXBoOgogICAgICAgICAgICAgICAgY29u"
    "dGludWUKICAgICAgICAgICAgZWxlbWVudHMgPSBwYXJhZ3JhcGguZ2V0KCJlbGVtZW50cyIsIFtdKQogICAgICAgICAgICBmb3Ig"
    "ZWwgaW4gZWxlbWVudHM6CiAgICAgICAgICAgICAgICBydW4gPSBlbC5nZXQoInRleHRSdW4iKQogICAgICAgICAgICAgICAgaWYg"
    "bm90IHJ1bjoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAgICAgdGV4dCA9IChydW4uZ2V0KCJjb250"
    "ZW50Iikgb3IgIiIpLnJlcGxhY2UoIlx4MGIiLCAiXG4iKQogICAgICAgICAgICAgICAgaWYgdGV4dDoKICAgICAgICAgICAgICAg"
    "ICAgICBjaHVua3MuYXBwZW5kKHRleHQpCiAgICAgICAgcGFyc2VkID0gIiIuam9pbihjaHVua3MpLnN0cmlwKCkKICAgICAgICBp"
    "ZiBsZW4ocGFyc2VkKSA+IG1heF9jaGFyczoKICAgICAgICAgICAgcGFyc2VkID0gcGFyc2VkWzptYXhfY2hhcnNdLnJzdHJpcCgp"
    "ICsgIuKApiIKICAgICAgICByZXR1cm4gewogICAgICAgICAgICAidGl0bGUiOiB0aXRsZSwKICAgICAgICAgICAgImRvY3VtZW50"
    "X2lkIjogZG9jX2lkLAogICAgICAgICAgICAicmV2aXNpb25faWQiOiBkb2MuZ2V0KCJyZXZpc2lvbklkIiksCiAgICAgICAgICAg"
    "ICJwcmV2aWV3X3RleHQiOiBwYXJzZWQgb3IgIltObyB0ZXh0IGNvbnRlbnQgcmV0dXJuZWQgZnJvbSBEb2NzIEFQSS5dIiwKICAg"
    "ICAgICB9CgogICAgZGVmIGNyZWF0ZV9kb2Moc2VsZiwgdGl0bGU6IHN0ciA9ICJOZXcgR3JpbVZlaWxlIFJlY29yZCIsIHBhcmVu"
    "dF9mb2xkZXJfaWQ6IHN0ciA9ICJyb290Iik6CiAgICAgICAgc2FmZV90aXRsZSA9ICh0aXRsZSBvciAiTmV3IEdyaW1WZWlsZSBS"
    "ZWNvcmQiKS5zdHJpcCgpIG9yICJOZXcgR3JpbVZlaWxlIFJlY29yZCIKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAg"
    "ICAgICAgc2FmZV9wYXJlbnRfaWQgPSAocGFyZW50X2ZvbGRlcl9pZCBvciAicm9vdCIpLnN0cmlwKCkgb3IgInJvb3QiCiAgICAg"
    "ICAgY3JlYXRlZCA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5jcmVhdGUoCiAgICAgICAgICAgIGJvZHk9ewogICAgICAg"
    "ICAgICAgICAgIm5hbWUiOiBzYWZlX3RpdGxlLAogICAgICAgICAgICAgICAgIm1pbWVUeXBlIjogImFwcGxpY2F0aW9uL3ZuZC5n"
    "b29nbGUtYXBwcy5kb2N1bWVudCIsCiAgICAgICAgICAgICAgICAicGFyZW50cyI6IFtzYWZlX3BhcmVudF9pZF0sCiAgICAgICAg"
    "ICAgIH0sCiAgICAgICAgICAgIGZpZWxkcz0iaWQsbmFtZSxtaW1lVHlwZSxtb2RpZmllZFRpbWUsd2ViVmlld0xpbmsscGFyZW50"
    "cyIsCiAgICAgICAgKS5leGVjdXRlKCkKICAgICAgICBkb2NfaWQgPSBjcmVhdGVkLmdldCgiaWQiKQogICAgICAgIG1ldGEgPSBz"
    "ZWxmLmdldF9maWxlX21ldGFkYXRhKGRvY19pZCkgaWYgZG9jX2lkIGVsc2Uge30KICAgICAgICByZXR1cm4gewogICAgICAgICAg"
    "ICAiaWQiOiBkb2NfaWQsCiAgICAgICAgICAgICJuYW1lIjogbWV0YS5nZXQoIm5hbWUiKSBvciBzYWZlX3RpdGxlLAogICAgICAg"
    "ICAgICAibWltZVR5cGUiOiBtZXRhLmdldCgibWltZVR5cGUiKSBvciAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3Vt"
    "ZW50IiwKICAgICAgICAgICAgIm1vZGlmaWVkVGltZSI6IG1ldGEuZ2V0KCJtb2RpZmllZFRpbWUiKSwKICAgICAgICAgICAgIndl"
    "YlZpZXdMaW5rIjogbWV0YS5nZXQoIndlYlZpZXdMaW5rIiksCiAgICAgICAgICAgICJwYXJlbnRzIjogbWV0YS5nZXQoInBhcmVu"
    "dHMiKSBvciBbc2FmZV9wYXJlbnRfaWRdLAogICAgICAgIH0KCiAgICBkZWYgY3JlYXRlX2ZvbGRlcihzZWxmLCBuYW1lOiBzdHIg"
    "PSAiTmV3IEZvbGRlciIsIHBhcmVudF9mb2xkZXJfaWQ6IHN0ciA9ICJyb290Iik6CiAgICAgICAgc2FmZV9uYW1lID0gKG5hbWUg"
    "b3IgIk5ldyBGb2xkZXIiKS5zdHJpcCgpIG9yICJOZXcgRm9sZGVyIgogICAgICAgIHNhZmVfcGFyZW50X2lkID0gKHBhcmVudF9m"
    "b2xkZXJfaWQgb3IgInJvb3QiKS5zdHJpcCgpIG9yICJyb290IgogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAg"
    "ICBjcmVhdGVkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmNyZWF0ZSgKICAgICAgICAgICAgYm9keT17CiAgICAgICAg"
    "ICAgICAgICAibmFtZSI6IHNhZmVfbmFtZSwKICAgICAgICAgICAgICAgICJtaW1lVHlwZSI6ICJhcHBsaWNhdGlvbi92bmQuZ29v"
    "Z2xlLWFwcHMuZm9sZGVyIiwKICAgICAgICAgICAgICAgICJwYXJlbnRzIjogW3NhZmVfcGFyZW50X2lkXSwKICAgICAgICAgICAg"
    "fSwKICAgICAgICAgICAgZmllbGRzPSJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVkVGltZSx3ZWJWaWV3TGluayxwYXJlbnRzIiwK"
    "ICAgICAgICApLmV4ZWN1dGUoKQogICAgICAgIHJldHVybiBjcmVhdGVkCgogICAgZGVmIGdldF9maWxlX21ldGFkYXRhKHNlbGYs"
    "IGZpbGVfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGZpbGVfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkZpbGUg"
    "aWQgaXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgcmV0dXJuIHNlbGYuX2RyaXZl"
    "X3NlcnZpY2UuZmlsZXMoKS5nZXQoCiAgICAgICAgICAgIGZpbGVJZD1maWxlX2lkLAogICAgICAgICAgICBmaWVsZHM9ImlkLG5h"
    "bWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVudHMsc2l6ZSIsCiAgICAgICAgKS5leGVjdXRlKCkKCiAg"
    "ICBkZWYgZ2V0X2RvY19tZXRhZGF0YShzZWxmLCBkb2NfaWQ6IHN0cik6CiAgICAgICAgcmV0dXJuIHNlbGYuZ2V0X2ZpbGVfbWV0"
    "YWRhdGEoZG9jX2lkKQoKICAgIGRlZiBkZWxldGVfaXRlbShzZWxmLCBmaWxlX2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBmaWxl"
    "X2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1"
    "cmVfc2VydmljZXMoKQogICAgICAgIHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5kZWxldGUoZmlsZUlkPWZpbGVfaWQpLmV4"
    "ZWN1dGUoKQoKICAgIGRlZiBkZWxldGVfZG9jKHNlbGYsIGRvY19pZDogc3RyKToKICAgICAgICBzZWxmLmRlbGV0ZV9pdGVtKGRv"
    "Y19pZCkKCiAgICBkZWYgZXhwb3J0X2RvY190ZXh0KHNlbGYsIGRvY19pZDogc3RyKToKICAgICAgICBpZiBub3QgZG9jX2lkOgog"
    "ICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJEb2N1bWVudCBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJl"
    "X3NlcnZpY2VzKCkKICAgICAgICBwYXlsb2FkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmV4cG9ydCgKICAgICAgICAg"
    "ICAgZmlsZUlkPWRvY19pZCwKICAgICAgICAgICAgbWltZVR5cGU9InRleHQvcGxhaW4iLAogICAgICAgICkuZXhlY3V0ZSgpCiAg"
    "ICAgICAgaWYgaXNpbnN0YW5jZShwYXlsb2FkLCBieXRlcyk6CiAgICAgICAgICAgIHJldHVybiBwYXlsb2FkLmRlY29kZSgidXRm"
    "LTgiLCBlcnJvcnM9InJlcGxhY2UiKQogICAgICAgIHJldHVybiBzdHIocGF5bG9hZCBvciAiIikKCiAgICBkZWYgZG93bmxvYWRf"
    "ZmlsZV9ieXRlcyhzZWxmLCBmaWxlX2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBmaWxlX2lkOgogICAgICAgICAgICByYWlzZSBW"
    "YWx1ZUVycm9yKCJGaWxlIGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHJl"
    "dHVybiBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuZ2V0X21lZGlhKGZpbGVJZD1maWxlX2lkKS5leGVjdXRlKCkKCgoKCiMg"
    "4pSA4pSAIFBBU1MgMyBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBBbGwgd29ya2VyIHRocmVhZHMgZGVm"
    "aW5lZC4gQWxsIGdlbmVyYXRpb24gaXMgc3RyZWFtaW5nLgojIE5vIGJsb2NraW5nIGNhbGxzIG9uIG1haW4gdGhyZWFkIGFueXdo"
    "ZXJlIGluIHRoaXMgZmlsZS4KIwojIE5leHQ6IFBhc3MgNCDigJQgTWVtb3J5ICYgU3RvcmFnZQojIChNZW1vcnlNYW5hZ2VyLCBT"
    "ZXNzaW9uTWFuYWdlciwgTGVzc29uc0xlYXJuZWREQiwgVGFza01hbmFnZXIpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBE"
    "RUNLIOKAlCBQQVNTIDQ6IE1FTU9SWSAmIFNUT1JBR0UKIwojIFN5c3RlbXMgZGVmaW5lZCBoZXJlOgojICAgRGVwZW5kZW5jeUNo"
    "ZWNrZXIgICDigJQgdmFsaWRhdGVzIGFsbCByZXF1aXJlZCBwYWNrYWdlcyBvbiBzdGFydHVwCiMgICBNZW1vcnlNYW5hZ2VyICAg"
    "ICAgIOKAlCBKU09OTCBtZW1vcnkgcmVhZC93cml0ZS9zZWFyY2gKIyAgIFNlc3Npb25NYW5hZ2VyICAgICAg4oCUIGF1dG8tc2F2"
    "ZSwgbG9hZCwgY29udGV4dCBpbmplY3Rpb24sIHNlc3Npb24gaW5kZXgKIyAgIExlc3NvbnNMZWFybmVkREIgICAg4oCUIExTTCBG"
    "b3JiaWRkZW4gUnVsZXNldCArIGNvZGUgbGVzc29ucyBrbm93bGVkZ2UgYmFzZQojICAgVGFza01hbmFnZXIgICAgICAgICDigJQg"
    "dGFzay9yZW1pbmRlciBDUlVELCBkdWUtZXZlbnQgZGV0ZWN0aW9uCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgoKIyDilIDilIAgREVQRU5ERU5D"
    "WSBDSEVDS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEZXBlbmRlbmN5Q2hlY2tlcjoKICAgICIiIgogICAgVmFsaWRhdGVz"
    "IGFsbCByZXF1aXJlZCBhbmQgb3B0aW9uYWwgcGFja2FnZXMgb24gc3RhcnR1cC4KICAgIFJldHVybnMgYSBsaXN0IG9mIHN0YXR1"
    "cyBtZXNzYWdlcyBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgIFNob3dzIGEgYmxvY2tpbmcgZXJyb3IgZGlhbG9nIGZvciBh"
    "bnkgY3JpdGljYWwgbWlzc2luZyBkZXBlbmRlbmN5LgogICAgIiIiCgogICAgIyAocGFja2FnZV9uYW1lLCBpbXBvcnRfbmFtZSwg"
    "Y3JpdGljYWwsIGluc3RhbGxfaGludCkKICAgIFBBQ0tBR0VTID0gWwogICAgICAgICgiUHlTaWRlNiIsICAgICAgICAgICAgICAg"
    "ICAgICJQeVNpZGU2IiwgICAgICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBQeVNpZGU2IiksCiAgICAgICAg"
    "KCJsb2d1cnUiLCAgICAgICAgICAgICAgICAgICAgImxvZ3VydSIsICAgICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgInBpcCBp"
    "bnN0YWxsIGxvZ3VydSIpLAogICAgICAgICgiYXBzY2hlZHVsZXIiLCAgICAgICAgICAgICAgICJhcHNjaGVkdWxlciIsICAgICAg"
    "ICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBhcHNjaGVkdWxlciIpLAogICAgICAgICgicHlnYW1lIiwgICAgICAgICAg"
    "ICAgICAgICAgICJweWdhbWUiLCAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcHlnYW1lICAobmVl"
    "ZGVkIGZvciBzb3VuZCkiKSwKICAgICAgICAoInB5d2luMzIiLCAgICAgICAgICAgICAgICAgICAid2luMzJjb20iLCAgICAgICAg"
    "ICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5d2luMzIgIChuZWVkZWQgZm9yIGRlc2t0b3Agc2hvcnRjdXQpIiks"
    "CiAgICAgICAgKCJwc3V0aWwiLCAgICAgICAgICAgICAgICAgICAgInBzdXRpbCIsICAgICAgICAgICAgICAgRmFsc2UsCiAgICAg"
    "ICAgICJwaXAgaW5zdGFsbCBwc3V0aWwgIChuZWVkZWQgZm9yIHN5c3RlbSBtb25pdG9yaW5nKSIpLAogICAgICAgICgicmVxdWVz"
    "dHMiLCAgICAgICAgICAgICAgICAgICJyZXF1ZXN0cyIsICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwg"
    "cmVxdWVzdHMiKSwKICAgICAgICAoImdvb2dsZS1hcGktcHl0aG9uLWNsaWVudCIsICAiZ29vZ2xlYXBpY2xpZW50IiwgICAgICBG"
    "YWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGdvb2dsZS1hcGktcHl0aG9uLWNsaWVudCIpLAogICAgICAgICgiZ29vZ2xlLWF1"
    "dGgtb2F1dGhsaWIiLCAgICAgICJnb29nbGVfYXV0aF9vYXV0aGxpYiIsIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgZ29v"
    "Z2xlLWF1dGgtb2F1dGhsaWIiKSwKICAgICAgICAoImdvb2dsZS1hdXRoIiwgICAgICAgICAgICAgICAiZ29vZ2xlLmF1dGgiLCAg"
    "ICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGdvb2dsZS1hdXRoIiksCiAgICAgICAgKCJ0b3JjaCIsICAgICAg"
    "ICAgICAgICAgICAgICAgInRvcmNoIiwgICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCB0b3JjaCAg"
    "KG9ubHkgbmVlZGVkIGZvciBsb2NhbCBtb2RlbCkiKSwKICAgICAgICAoInRyYW5zZm9ybWVycyIsICAgICAgICAgICAgICAidHJh"
    "bnNmb3JtZXJzIiwgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHRyYW5zZm9ybWVycyAgKG9ubHkgbmVlZGVk"
    "IGZvciBsb2NhbCBtb2RlbCkiKSwKICAgICAgICAoInB5bnZtbCIsICAgICAgICAgICAgICAgICAgICAicHludm1sIiwgICAgICAg"
    "ICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5bnZtbCAgKG9ubHkgbmVlZGVkIGZvciBOVklESUEgR1BVIG1v"
    "bml0b3JpbmcpIiksCiAgICBdCgogICAgQGNsYXNzbWV0aG9kCiAgICBkZWYgY2hlY2soY2xzKSAtPiB0dXBsZVtsaXN0W3N0cl0s"
    "IGxpc3Rbc3RyXV06CiAgICAgICAgIiIiCiAgICAgICAgUmV0dXJucyAobWVzc2FnZXMsIGNyaXRpY2FsX2ZhaWx1cmVzKS4KICAg"
    "ICAgICBtZXNzYWdlczogbGlzdCBvZiAiW0RFUFNdIHBhY2thZ2Ug4pyTL+KclyDigJQgbm90ZSIgc3RyaW5ncwogICAgICAgIGNy"
    "aXRpY2FsX2ZhaWx1cmVzOiBsaXN0IG9mIHBhY2thZ2VzIHRoYXQgYXJlIGNyaXRpY2FsIGFuZCBtaXNzaW5nCiAgICAgICAgIiIi"
    "CiAgICAgICAgaW1wb3J0IGltcG9ydGxpYgogICAgICAgIG1lc3NhZ2VzICA9IFtdCiAgICAgICAgY3JpdGljYWwgID0gW10KCiAg"
    "ICAgICAgZm9yIHBrZ19uYW1lLCBpbXBvcnRfbmFtZSwgaXNfY3JpdGljYWwsIGhpbnQgaW4gY2xzLlBBQ0tBR0VTOgogICAgICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgICAgICBpbXBvcnRsaWIuaW1wb3J0X21vZHVsZShpbXBvcnRfbmFtZSkKICAgICAgICAgICAg"
    "ICAgIG1lc3NhZ2VzLmFwcGVuZChmIltERVBTXSB7cGtnX25hbWV9IOKckyIpCiAgICAgICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJv"
    "cjoKICAgICAgICAgICAgICAgIHN0YXR1cyA9ICJDUklUSUNBTCIgaWYgaXNfY3JpdGljYWwgZWxzZSAib3B0aW9uYWwiCiAgICAg"
    "ICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgZiJbREVQU10ge3BrZ19uYW1lfSDinJcgKHtz"
    "dGF0dXN9KSDigJQge2hpbnR9IgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgaXNfY3JpdGljYWw6CiAgICAg"
    "ICAgICAgICAgICAgICAgY3JpdGljYWwuYXBwZW5kKHBrZ19uYW1lKQoKICAgICAgICByZXR1cm4gbWVzc2FnZXMsIGNyaXRpY2Fs"
    "CgogICAgQGNsYXNzbWV0aG9kCiAgICBkZWYgY2hlY2tfb2xsYW1hKGNscykgLT4gc3RyOgogICAgICAgICIiIkNoZWNrIGlmIE9s"
    "bGFtYSBpcyBydW5uaW5nLiBSZXR1cm5zIHN0YXR1cyBzdHJpbmcuIiIiCiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXEgID0g"
    "dXJsbGliLnJlcXVlc3QuUmVxdWVzdCgiaHR0cDovL2xvY2FsaG9zdDoxMTQzNC9hcGkvdGFncyIpCiAgICAgICAgICAgIHJlc3Ag"
    "PSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0yKQogICAgICAgICAgICBpZiByZXNwLnN0YXR1cyA9PSAyMDA6"
    "CiAgICAgICAgICAgICAgICByZXR1cm4gIltERVBTXSBPbGxhbWEg4pyTIOKAlCBydW5uaW5nIG9uIGxvY2FsaG9zdDoxMTQzNCIK"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICAgICAgcmV0dXJuICJbREVQU10gT2xsYW1hIOKc"
    "lyDigJQgbm90IHJ1bm5pbmcgKG9ubHkgbmVlZGVkIGZvciBPbGxhbWEgbW9kZWwgdHlwZSkiCgoKIyDilIDilIAgTUVNT1JZIE1B"
    "TkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1lbW9yeU1hbmFnZXI6CiAgICAiIiIKICAgIEhhbmRs"
    "ZXMgYWxsIEpTT05MIG1lbW9yeSBvcGVyYXRpb25zLgoKICAgIEZpbGVzIG1hbmFnZWQ6CiAgICAgICAgbWVtb3JpZXMvbWVzc2Fn"
    "ZXMuanNvbmwgICAgICAgICDigJQgZXZlcnkgbWVzc2FnZSwgdGltZXN0YW1wZWQKICAgICAgICBtZW1vcmllcy9tZW1vcmllcy5q"
    "c29ubCAgICAgICAgIOKAlCBleHRyYWN0ZWQgbWVtb3J5IHJlY29yZHMKICAgICAgICBtZW1vcmllcy9zdGF0ZS5qc29uICAgICAg"
    "ICAgICAgIOKAlCBlbnRpdHkgc3RhdGUKICAgICAgICBtZW1vcmllcy9pbmRleC5qc29uICAgICAgICAgICAgIOKAlCBjb3VudHMg"
    "YW5kIG1ldGFkYXRhCgogICAgTWVtb3J5IHJlY29yZHMgaGF2ZSB0eXBlIGluZmVyZW5jZSwga2V5d29yZCBleHRyYWN0aW9uLCB0"
    "YWcgZ2VuZXJhdGlvbiwKICAgIG5lYXItZHVwbGljYXRlIGRldGVjdGlvbiwgYW5kIHJlbGV2YW5jZSBzY29yaW5nIGZvciBjb250"
    "ZXh0IGluamVjdGlvbi4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBiYXNlICAgICAgICAgICAgID0g"
    "Y2ZnX3BhdGgoIm1lbW9yaWVzIikKICAgICAgICBzZWxmLm1lc3NhZ2VzX3AgID0gYmFzZSAvICJtZXNzYWdlcy5qc29ubCIKICAg"
    "ICAgICBzZWxmLm1lbW9yaWVzX3AgID0gYmFzZSAvICJtZW1vcmllcy5qc29ubCIKICAgICAgICBzZWxmLnN0YXRlX3AgICAgID0g"
    "YmFzZSAvICJzdGF0ZS5qc29uIgogICAgICAgIHNlbGYuaW5kZXhfcCAgICAgPSBiYXNlIC8gImluZGV4Lmpzb24iCgogICAgIyDi"
    "lIDilIAgU1RBVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbG9hZF9zdGF0ZShzZWxmKSAtPiBkaWN0OgogICAg"
    "ICAgIGlmIG5vdCBzZWxmLnN0YXRlX3AuZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiBzZWxmLl9kZWZhdWx0X3N0YXRlKCkK"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVybiBqc29uLmxvYWRzKHNlbGYuc3RhdGVfcC5yZWFkX3RleHQoZW5jb2Rpbmc9"
    "InV0Zi04IikpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIHNlbGYuX2RlZmF1bHRfc3RhdGUo"
    "KQoKICAgIGRlZiBzYXZlX3N0YXRlKHNlbGYsIHN0YXRlOiBkaWN0KSAtPiBOb25lOgogICAgICAgIHNlbGYuc3RhdGVfcC53cml0"
    "ZV90ZXh0KAogICAgICAgICAgICBqc29uLmR1bXBzKHN0YXRlLCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICAp"
    "CgogICAgZGVmIF9kZWZhdWx0X3N0YXRlKHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgInBlcnNv"
    "bmFfbmFtZSI6ICAgICAgICAgICAgIERFQ0tfTkFNRSwKICAgICAgICAgICAgImRlY2tfdmVyc2lvbiI6ICAgICAgICAgICAgIEFQ"
    "UF9WRVJTSU9OLAogICAgICAgICAgICAic2Vzc2lvbl9jb3VudCI6ICAgICAgICAgICAgMCwKICAgICAgICAgICAgImxhc3Rfc3Rh"
    "cnR1cCI6ICAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgICJsYXN0X3NodXRkb3duIjogICAgICAgICAgICBOb25lLAogICAg"
    "ICAgICAgICAibGFzdF9hY3RpdmUiOiAgICAgICAgICAgICAgTm9uZSwKICAgICAgICAgICAgInRvdGFsX21lc3NhZ2VzIjogICAg"
    "ICAgICAgIDAsCiAgICAgICAgICAgICJ0b3RhbF9tZW1vcmllcyI6ICAgICAgICAgICAwLAogICAgICAgICAgICAiaW50ZXJuYWxf"
    "bmFycmF0aXZlIjogICAgICAge30sCiAgICAgICAgICAgICJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3duIjoiRE9STUFOVCIsCiAg"
    "ICAgICAgfQoKICAgICMg4pSA4pSAIE1FU1NBR0VTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGFwcGVuZF9tZXNzYWdlKHNlbGYs"
    "IHNlc3Npb25faWQ6IHN0ciwgcm9sZTogc3RyLAogICAgICAgICAgICAgICAgICAgICAgIGNvbnRlbnQ6IHN0ciwgZW1vdGlvbjog"
    "c3RyID0gIiIpIC0+IGRpY3Q6CiAgICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgIGYibXNnX3t1dWlk"
    "LnV1aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6ICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAg"
    "ICJzZXNzaW9uX2lkIjogc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEiOiAgICBERUNLX05BTUUsCiAgICAgICAgICAg"
    "ICJyb2xlIjogICAgICAgcm9sZSwKICAgICAgICAgICAgImNvbnRlbnQiOiAgICBjb250ZW50LAogICAgICAgICAgICAiZW1vdGlv"
    "biI6ICAgIGVtb3Rpb24sCiAgICAgICAgfQogICAgICAgIGFwcGVuZF9qc29ubChzZWxmLm1lc3NhZ2VzX3AsIHJlY29yZCkKICAg"
    "ICAgICByZXR1cm4gcmVjb3JkCgogICAgZGVmIGxvYWRfcmVjZW50X21lc3NhZ2VzKHNlbGYsIGxpbWl0OiBpbnQgPSAyMCkgLT4g"
    "bGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChzZWxmLm1lc3NhZ2VzX3ApWy1saW1pdDpdCgogICAgIyDilIDi"
    "lIAgTUVNT1JJRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgYXBwZW5kX21lbW9yeShzZWxmLCBzZXNzaW9uX2lkOiBzdHIsIHVz"
    "ZXJfdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgICAgYXNzaXN0YW50X3RleHQ6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06"
    "CiAgICAgICAgcmVjb3JkX3R5cGUgPSBpbmZlcl9yZWNvcmRfdHlwZSh1c2VyX3RleHQsIGFzc2lzdGFudF90ZXh0KQogICAgICAg"
    "IGtleXdvcmRzICAgID0gZXh0cmFjdF9rZXl3b3Jkcyh1c2VyX3RleHQgKyAiICIgKyBhc3Npc3RhbnRfdGV4dCkKICAgICAgICB0"
    "YWdzICAgICAgICA9IHNlbGYuX2luZmVyX3RhZ3MocmVjb3JkX3R5cGUsIHVzZXJfdGV4dCwga2V5d29yZHMpCiAgICAgICAgdGl0"
    "bGUgICAgICAgPSBzZWxmLl9pbmZlcl90aXRsZShyZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBrZXl3b3JkcykKICAgICAgICBzdW1t"
    "YXJ5ICAgICA9IHNlbGYuX3N1bW1hcml6ZShyZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBhc3Npc3RhbnRfdGV4dCkKCiAgICAgICAg"
    "bWVtb3J5ID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICAgIGYibWVtX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMl19IiwK"
    "ICAgICAgICAgICAgInRpbWVzdGFtcCI6ICAgICAgICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICJzZXNzaW9uX2lkIjog"
    "ICAgICAgc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEiOiAgICAgICAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJ0"
    "eXBlIjogICAgICAgICAgICAgcmVjb3JkX3R5cGUsCiAgICAgICAgICAgICJ0aXRsZSI6ICAgICAgICAgICAgdGl0bGUsCiAgICAg"
    "ICAgICAgICJzdW1tYXJ5IjogICAgICAgICAgc3VtbWFyeSwKICAgICAgICAgICAgImNvbnRlbnQiOiAgICAgICAgICB1c2VyX3Rl"
    "eHRbOjQwMDBdLAogICAgICAgICAgICAiYXNzaXN0YW50X2NvbnRleHQiOmFzc2lzdGFudF90ZXh0WzoxMjAwXSwKICAgICAgICAg"
    "ICAgImtleXdvcmRzIjogICAgICAgICBrZXl3b3JkcywKICAgICAgICAgICAgInRhZ3MiOiAgICAgICAgICAgICB0YWdzLAogICAg"
    "ICAgICAgICAiY29uZmlkZW5jZSI6ICAgICAgIDAuNzAgaWYgcmVjb3JkX3R5cGUgaW4gewogICAgICAgICAgICAgICAgImRyZWFt"
    "IiwiaXNzdWUiLCJpZGVhIiwicHJlZmVyZW5jZSIsInJlc29sdXRpb24iCiAgICAgICAgICAgIH0gZWxzZSAwLjU1LAogICAgICAg"
    "IH0KCiAgICAgICAgaWYgc2VsZi5faXNfbmVhcl9kdXBsaWNhdGUobWVtb3J5KToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAg"
    "ICAgICAgYXBwZW5kX2pzb25sKHNlbGYubWVtb3JpZXNfcCwgbWVtb3J5KQogICAgICAgIHJldHVybiBtZW1vcnkKCiAgICBkZWYg"
    "c2VhcmNoX21lbW9yaWVzKHNlbGYsIHF1ZXJ5OiBzdHIsIGxpbWl0OiBpbnQgPSA2KSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIi"
    "IgogICAgICAgIEtleXdvcmQtc2NvcmVkIG1lbW9yeSBzZWFyY2guCiAgICAgICAgUmV0dXJucyB1cCB0byBgbGltaXRgIHJlY29y"
    "ZHMgc29ydGVkIGJ5IHJlbGV2YW5jZSBzY29yZSBkZXNjZW5kaW5nLgogICAgICAgIEZhbGxzIGJhY2sgdG8gbW9zdCByZWNlbnQg"
    "aWYgbm8gcXVlcnkgdGVybXMgbWF0Y2guCiAgICAgICAgIiIiCiAgICAgICAgbWVtb3JpZXMgPSByZWFkX2pzb25sKHNlbGYubWVt"
    "b3JpZXNfcCkKICAgICAgICBpZiBub3QgcXVlcnkuc3RyaXAoKToKICAgICAgICAgICAgcmV0dXJuIG1lbW9yaWVzWy1saW1pdDpd"
    "CgogICAgICAgIHFfdGVybXMgPSBzZXQoZXh0cmFjdF9rZXl3b3JkcyhxdWVyeSwgbGltaXQ9MTYpKQogICAgICAgIHNjb3JlZCAg"
    "PSBbXQoKICAgICAgICBmb3IgaXRlbSBpbiBtZW1vcmllczoKICAgICAgICAgICAgaXRlbV90ZXJtcyA9IHNldChleHRyYWN0X2tl"
    "eXdvcmRzKCIgIi5qb2luKFsKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0KCJ0aXRsZSIsICAgIiIpLAogICAgICAgICAgICAgICAg"
    "aXRlbS5nZXQoInN1bW1hcnkiLCAiIiksCiAgICAgICAgICAgICAgICBpdGVtLmdldCgiY29udGVudCIsICIiKSwKICAgICAgICAg"
    "ICAgICAgICIgIi5qb2luKGl0ZW0uZ2V0KCJrZXl3b3JkcyIsIFtdKSksCiAgICAgICAgICAgICAgICAiICIuam9pbihpdGVtLmdl"
    "dCgidGFncyIsICAgICBbXSkpLAogICAgICAgICAgICBdKSwgbGltaXQ9NDApKQoKICAgICAgICAgICAgc2NvcmUgPSBsZW4ocV90"
    "ZXJtcyAmIGl0ZW1fdGVybXMpCgogICAgICAgICAgICAjIEJvb3N0IGJ5IHR5cGUgbWF0Y2gKICAgICAgICAgICAgcWwgPSBxdWVy"
    "eS5sb3dlcigpCiAgICAgICAgICAgIHJ0ID0gaXRlbS5nZXQoInR5cGUiLCAiIikKICAgICAgICAgICAgaWYgImRyZWFtIiAgaW4g"
    "cWwgYW5kIHJ0ID09ICJkcmVhbSI6ICAgIHNjb3JlICs9IDQKICAgICAgICAgICAgaWYgInRhc2siICAgaW4gcWwgYW5kIHJ0ID09"
    "ICJ0YXNrIjogICAgIHNjb3JlICs9IDMKICAgICAgICAgICAgaWYgImlkZWEiICAgaW4gcWwgYW5kIHJ0ID09ICJpZGVhIjogICAg"
    "IHNjb3JlICs9IDIKICAgICAgICAgICAgaWYgImxzbCIgICAgaW4gcWwgYW5kIHJ0IGluIHsiaXNzdWUiLCJyZXNvbHV0aW9uIn06"
    "IHNjb3JlICs9IDIKCiAgICAgICAgICAgIGlmIHNjb3JlID4gMDoKICAgICAgICAgICAgICAgIHNjb3JlZC5hcHBlbmQoKHNjb3Jl"
    "LCBpdGVtKSkKCiAgICAgICAgc2NvcmVkLnNvcnQoa2V5PWxhbWJkYSB4OiAoeFswXSwgeFsxXS5nZXQoInRpbWVzdGFtcCIsICIi"
    "KSksCiAgICAgICAgICAgICAgICAgICAgcmV2ZXJzZT1UcnVlKQogICAgICAgIHJldHVybiBbaXRlbSBmb3IgXywgaXRlbSBpbiBz"
    "Y29yZWRbOmxpbWl0XV0KCiAgICBkZWYgYnVpbGRfY29udGV4dF9ibG9jayhzZWxmLCBxdWVyeTogc3RyLCBtYXhfY2hhcnM6IGlu"
    "dCA9IDIwMDApIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBCdWlsZCBhIGNvbnRleHQgc3RyaW5nIGZyb20gcmVsZXZhbnQg"
    "bWVtb3JpZXMgZm9yIHByb21wdCBpbmplY3Rpb24uCiAgICAgICAgVHJ1bmNhdGVzIHRvIG1heF9jaGFycyB0byBwcm90ZWN0IHRo"
    "ZSBjb250ZXh0IHdpbmRvdy4KICAgICAgICAiIiIKICAgICAgICBtZW1vcmllcyA9IHNlbGYuc2VhcmNoX21lbW9yaWVzKHF1ZXJ5"
    "LCBsaW1pdD00KQogICAgICAgIGlmIG5vdCBtZW1vcmllczoKICAgICAgICAgICAgcmV0dXJuICIiCgogICAgICAgIHBhcnRzID0g"
    "WyJbUkVMRVZBTlQgTUVNT1JJRVNdIl0KICAgICAgICB0b3RhbCA9IDAKICAgICAgICBmb3IgbSBpbiBtZW1vcmllczoKICAgICAg"
    "ICAgICAgZW50cnkgPSAoCiAgICAgICAgICAgICAgICBmIuKAoiBbe20uZ2V0KCd0eXBlJywnJykudXBwZXIoKX1dIHttLmdldCgn"
    "dGl0bGUnLCcnKX06ICIKICAgICAgICAgICAgICAgIGYie20uZ2V0KCdzdW1tYXJ5JywnJyl9IgogICAgICAgICAgICApCiAgICAg"
    "ICAgICAgIGlmIHRvdGFsICsgbGVuKGVudHJ5KSA+IG1heF9jaGFyczoKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAg"
    "IHBhcnRzLmFwcGVuZChlbnRyeSkKICAgICAgICAgICAgdG90YWwgKz0gbGVuKGVudHJ5KQoKICAgICAgICBwYXJ0cy5hcHBlbmQo"
    "IltFTkQgTUVNT1JJRVNdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBhcnRzKQoKICAgICMg4pSA4pSAIEhFTFBFUlMg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2lzX25lYXJfZHVwbGljYXRlKHNlbGYsIGNhbmRpZGF0ZTogZGljdCkgLT4gYm9vbDoK"
    "ICAgICAgICByZWNlbnQgPSByZWFkX2pzb25sKHNlbGYubWVtb3JpZXNfcClbLTI1Ol0KICAgICAgICBjdCA9IGNhbmRpZGF0ZS5n"
    "ZXQoInRpdGxlIiwgIiIpLmxvd2VyKCkuc3RyaXAoKQogICAgICAgIGNzID0gY2FuZGlkYXRlLmdldCgic3VtbWFyeSIsICIiKS5s"
    "b3dlcigpLnN0cmlwKCkKICAgICAgICBmb3IgaXRlbSBpbiByZWNlbnQ6CiAgICAgICAgICAgIGlmIGl0ZW0uZ2V0KCJ0aXRsZSIs"
    "IiIpLmxvd2VyKCkuc3RyaXAoKSA9PSBjdDogIHJldHVybiBUcnVlCiAgICAgICAgICAgIGlmIGl0ZW0uZ2V0KCJzdW1tYXJ5Iiwi"
    "IikubG93ZXIoKS5zdHJpcCgpID09IGNzOiByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVybiBGYWxzZQoKICAgIGRlZiBfaW5mZXJf"
    "dGFncyhzZWxmLCByZWNvcmRfdHlwZTogc3RyLCB0ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICAga2V5d29yZHM6IGxpc3Rb"
    "c3RyXSkgLT4gbGlzdFtzdHJdOgogICAgICAgIHQgICAgPSB0ZXh0Lmxvd2VyKCkKICAgICAgICB0YWdzID0gW3JlY29yZF90eXBl"
    "XQogICAgICAgIGlmICJkcmVhbSIgICBpbiB0OiB0YWdzLmFwcGVuZCgiZHJlYW0iKQogICAgICAgIGlmICJsc2wiICAgICBpbiB0"
    "OiB0YWdzLmFwcGVuZCgibHNsIikKICAgICAgICBpZiAicHl0aG9uIiAgaW4gdDogdGFncy5hcHBlbmQoInB5dGhvbiIpCiAgICAg"
    "ICAgaWYgImdhbWUiICAgIGluIHQ6IHRhZ3MuYXBwZW5kKCJnYW1lX2lkZWEiKQogICAgICAgIGlmICJzbCIgICAgICBpbiB0IG9y"
    "ICJzZWNvbmQgbGlmZSIgaW4gdDogdGFncy5hcHBlbmQoInNlY29uZGxpZmUiKQogICAgICAgIGlmIERFQ0tfTkFNRS5sb3dlcigp"
    "IGluIHQ6IHRhZ3MuYXBwZW5kKERFQ0tfTkFNRS5sb3dlcigpKQogICAgICAgIGZvciBrdyBpbiBrZXl3b3Jkc1s6NF06CiAgICAg"
    "ICAgICAgIGlmIGt3IG5vdCBpbiB0YWdzOgogICAgICAgICAgICAgICAgdGFncy5hcHBlbmQoa3cpCiAgICAgICAgIyBEZWR1cGxp"
    "Y2F0ZSBwcmVzZXJ2aW5nIG9yZGVyCiAgICAgICAgc2Vlbiwgb3V0ID0gc2V0KCksIFtdCiAgICAgICAgZm9yIHRhZyBpbiB0YWdz"
    "OgogICAgICAgICAgICBpZiB0YWcgbm90IGluIHNlZW46CiAgICAgICAgICAgICAgICBzZWVuLmFkZCh0YWcpCiAgICAgICAgICAg"
    "ICAgICBvdXQuYXBwZW5kKHRhZykKICAgICAgICByZXR1cm4gb3V0WzoxMl0KCiAgICBkZWYgX2luZmVyX3RpdGxlKHNlbGYsIHJl"
    "Y29yZF90eXBlOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgICBrZXl3b3JkczogbGlzdFtzdHJdKSAt"
    "PiBzdHI6CiAgICAgICAgZGVmIGNsZWFuKHdvcmRzKToKICAgICAgICAgICAgcmV0dXJuIFt3LnN0cmlwKCIgLV8uLCE/IikuY2Fw"
    "aXRhbGl6ZSgpCiAgICAgICAgICAgICAgICAgICAgZm9yIHcgaW4gd29yZHMgaWYgbGVuKHcpID4gMl0KCiAgICAgICAgaWYgcmVj"
    "b3JkX3R5cGUgPT0gInRhc2siOgogICAgICAgICAgICBpbXBvcnQgcmUKICAgICAgICAgICAgbSA9IHJlLnNlYXJjaChyInJlbWlu"
    "ZCBtZSAuKj8gdG8gKC4rKSIsIHVzZXJfdGV4dCwgcmUuSSkKICAgICAgICAgICAgaWYgbToKICAgICAgICAgICAgICAgIHJldHVy"
    "biBmIlJlbWluZGVyOiB7bS5ncm91cCgxKS5zdHJpcCgpWzo2MF19IgogICAgICAgICAgICByZXR1cm4gIlJlbWluZGVyIFRhc2si"
    "CiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImRyZWFtIjoKICAgICAgICAgICAgcmV0dXJuIGYieycgJy5qb2luKGNsZWFuKGtl"
    "eXdvcmRzWzozXSkpfSBEcmVhbSIuc3RyaXAoKSBvciAiRHJlYW0gTWVtb3J5IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJp"
    "c3N1ZSI6CiAgICAgICAgICAgIHJldHVybiBmIklzc3VlOiB7JyAnLmpvaW4oY2xlYW4oa2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgp"
    "IG9yICJUZWNobmljYWwgSXNzdWUiCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInJlc29sdXRpb24iOgogICAgICAgICAgICBy"
    "ZXR1cm4gZiJSZXNvbHV0aW9uOiB7JyAnLmpvaW4oY2xlYW4oa2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJUZWNobmljYWwg"
    "UmVzb2x1dGlvbiIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaWRlYSI6CiAgICAgICAgICAgIHJldHVybiBmIklkZWE6IHsn"
    "ICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0pKX0iLnN0cmlwKCkgb3IgIklkZWEiCiAgICAgICAgaWYga2V5d29yZHM6CiAgICAg"
    "ICAgICAgIHJldHVybiAiICIuam9pbihjbGVhbihrZXl3b3Jkc1s6NV0pKSBvciAiQ29udmVyc2F0aW9uIE1lbW9yeSIKICAgICAg"
    "ICByZXR1cm4gIkNvbnZlcnNhdGlvbiBNZW1vcnkiCgogICAgZGVmIF9zdW1tYXJpemUoc2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwg"
    "dXNlcl90ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICBhc3Npc3RhbnRfdGV4dDogc3RyKSAtPiBzdHI6CiAgICAgICAgdSA9"
    "IHVzZXJfdGV4dC5zdHJpcCgpWzoyMjBdCiAgICAgICAgYSA9IGFzc2lzdGFudF90ZXh0LnN0cmlwKClbOjIyMF0KICAgICAgICBp"
    "ZiByZWNvcmRfdHlwZSA9PSAiZHJlYW0iOiAgICAgICByZXR1cm4gZiJVc2VyIGRlc2NyaWJlZCBhIGRyZWFtOiB7dX0iCiAgICAg"
    "ICAgaWYgcmVjb3JkX3R5cGUgPT0gInRhc2siOiAgICAgICAgcmV0dXJuIGYiUmVtaW5kZXIvdGFzazoge3V9IgogICAgICAgIGlm"
    "IHJlY29yZF90eXBlID09ICJpc3N1ZSI6ICAgICAgIHJldHVybiBmIlRlY2huaWNhbCBpc3N1ZToge3V9IgogICAgICAgIGlmIHJl"
    "Y29yZF90eXBlID09ICJyZXNvbHV0aW9uIjogIHJldHVybiBmIlNvbHV0aW9uIHJlY29yZGVkOiB7YSBvciB1fSIKICAgICAgICBp"
    "ZiByZWNvcmRfdHlwZSA9PSAiaWRlYSI6ICAgICAgICByZXR1cm4gZiJJZGVhIGRpc2N1c3NlZDoge3V9IgogICAgICAgIGlmIHJl"
    "Y29yZF90eXBlID09ICJwcmVmZXJlbmNlIjogIHJldHVybiBmIlByZWZlcmVuY2Ugbm90ZWQ6IHt1fSIKICAgICAgICByZXR1cm4g"
    "ZiJDb252ZXJzYXRpb246IHt1fSIKCgojIOKUgOKUgCBTRVNTSU9OIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CmNsYXNzIFNlc3Npb25NYW5hZ2VyOgogICAgIiIiCiAgICBNYW5hZ2VzIGNvbnZlcnNhdGlvbiBzZXNzaW9ucy4KCiAgICBBdXRv"
    "LXNhdmU6IGV2ZXJ5IDEwIG1pbnV0ZXMgKEFQU2NoZWR1bGVyKSwgbWlkbmlnaHQtdG8tbWlkbmlnaHQgYm91bmRhcnkuCiAgICBG"
    "aWxlOiBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sIOKAlCBvdmVyd3JpdGVzIG9uIGVhY2ggc2F2ZS4KICAgIEluZGV4OiBzZXNz"
    "aW9ucy9zZXNzaW9uX2luZGV4Lmpzb24g4oCUIG9uZSBlbnRyeSBwZXIgZGF5LgoKICAgIFNlc3Npb25zIGFyZSBsb2FkZWQgYXMg"
    "Y29udGV4dCBpbmplY3Rpb24gKG5vdCByZWFsIG1lbW9yeSkgdW50aWwKICAgIHRoZSBTUUxpdGUvQ2hyb21hREIgc3lzdGVtIGlz"
    "IGJ1aWx0IGluIFBoYXNlIDIuCiAgICAiIiIKCiAgICBBVVRPU0FWRV9JTlRFUlZBTCA9IDEwICAgIyBtaW51dGVzCgogICAgZGVm"
    "IF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3Nlc3Npb25zX2RpciAgPSBjZmdfcGF0aCgic2Vzc2lvbnMiKQogICAgICAg"
    "IHNlbGYuX2luZGV4X3BhdGggICAgPSBzZWxmLl9zZXNzaW9uc19kaXIgLyAic2Vzc2lvbl9pbmRleC5qc29uIgogICAgICAgIHNl"
    "bGYuX3Nlc3Npb25faWQgICAgPSBmInNlc3Npb25fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9Igog"
    "ICAgICAgIHNlbGYuX2N1cnJlbnRfZGF0ZSAgPSBkYXRlLnRvZGF5KCkuaXNvZm9ybWF0KCkKICAgICAgICBzZWxmLl9tZXNzYWdl"
    "czogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fbG9hZGVkX2pvdXJuYWw6IE9wdGlvbmFsW3N0cl0gPSBOb25lICAjIGRh"
    "dGUgb2YgbG9hZGVkIGpvdXJuYWwKCiAgICAjIOKUgOKUgCBDVVJSRU5UIFNFU1NJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgYWRkX21lc3NhZ2Uoc2VsZiwgcm9s"
    "ZTogc3RyLCBjb250ZW50OiBzdHIsCiAgICAgICAgICAgICAgICAgICAgZW1vdGlvbjogc3RyID0gIiIsIHRpbWVzdGFtcDogc3Ry"
    "ID0gIiIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fbWVzc2FnZXMuYXBwZW5kKHsKICAgICAgICAgICAgImlkIjogICAgICAgIGYi"
    "bXNnX3t1dWlkLnV1aWQ0KCkuaGV4Wzo4XX0iLAogICAgICAgICAgICAidGltZXN0YW1wIjogdGltZXN0YW1wIG9yIGxvY2FsX25v"
    "d19pc28oKSwKICAgICAgICAgICAgInJvbGUiOiAgICAgIHJvbGUsCiAgICAgICAgICAgICJjb250ZW50IjogICBjb250ZW50LAog"
    "ICAgICAgICAgICAiZW1vdGlvbiI6ICAgZW1vdGlvbiwKICAgICAgICB9KQoKICAgIGRlZiBnZXRfaGlzdG9yeShzZWxmKSAtPiBs"
    "aXN0W2RpY3RdOgogICAgICAgICIiIgogICAgICAgIFJldHVybiBoaXN0b3J5IGluIExMTS1mcmllbmRseSBmb3JtYXQuCiAgICAg"
    "ICAgW3sicm9sZSI6ICJ1c2VyInwiYXNzaXN0YW50IiwgImNvbnRlbnQiOiAiLi4uIn1dCiAgICAgICAgIiIiCiAgICAgICAgcmV0"
    "dXJuIFsKICAgICAgICAgICAgeyJyb2xlIjogbVsicm9sZSJdLCAiY29udGVudCI6IG1bImNvbnRlbnQiXX0KICAgICAgICAgICAg"
    "Zm9yIG0gaW4gc2VsZi5fbWVzc2FnZXMKICAgICAgICAgICAgaWYgbVsicm9sZSJdIGluICgidXNlciIsICJhc3Npc3RhbnQiKQog"
    "ICAgICAgIF0KCiAgICBAcHJvcGVydHkKICAgIGRlZiBzZXNzaW9uX2lkKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4gc2Vs"
    "Zi5fc2Vzc2lvbl9pZAoKICAgIEBwcm9wZXJ0eQogICAgZGVmIG1lc3NhZ2VfY291bnQoc2VsZikgLT4gaW50OgogICAgICAgIHJl"
    "dHVybiBsZW4oc2VsZi5fbWVzc2FnZXMpCgogICAgIyDilIDilIAgU0FWRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "IGRlZiBzYXZlKHNlbGYsIGFpX2dlbmVyYXRlZF9uYW1lOiBzdHIgPSAiIikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBT"
    "YXZlIGN1cnJlbnQgc2Vzc2lvbiB0byBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sLgogICAgICAgIE92ZXJ3cml0ZXMgdGhlIGZp"
    "bGUgZm9yIHRvZGF5IOKAlCBlYWNoIHNhdmUgaXMgYSBmdWxsIHNuYXBzaG90LgogICAgICAgIFVwZGF0ZXMgc2Vzc2lvbl9pbmRl"
    "eC5qc29uLgogICAgICAgICIiIgogICAgICAgIHRvZGF5ID0gZGF0ZS50b2RheSgpLmlzb2Zvcm1hdCgpCiAgICAgICAgb3V0X3Bh"
    "dGggPSBzZWxmLl9zZXNzaW9uc19kaXIgLyBmInt0b2RheX0uanNvbmwiCgogICAgICAgICMgV3JpdGUgYWxsIG1lc3NhZ2VzCiAg"
    "ICAgICAgd3JpdGVfanNvbmwob3V0X3BhdGgsIHNlbGYuX21lc3NhZ2VzKQoKICAgICAgICAjIFVwZGF0ZSBpbmRleAogICAgICAg"
    "IGluZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAgICAgICAgZXhpc3RpbmcgPSBuZXh0KAogICAgICAgICAgICAocyBmb3IgcyBp"
    "biBpbmRleFsic2Vzc2lvbnMiXSBpZiBzWyJkYXRlIl0gPT0gdG9kYXkpLCBOb25lCiAgICAgICAgKQoKICAgICAgICBuYW1lID0g"
    "YWlfZ2VuZXJhdGVkX25hbWUgb3IgZXhpc3RpbmcuZ2V0KCJuYW1lIiwgIiIpIGlmIGV4aXN0aW5nIGVsc2UgIiIKICAgICAgICBp"
    "ZiBub3QgbmFtZSBhbmQgc2VsZi5fbWVzc2FnZXM6CiAgICAgICAgICAgICMgQXV0by1uYW1lIGZyb20gZmlyc3QgdXNlciBtZXNz"
    "YWdlIChmaXJzdCA1IHdvcmRzKQogICAgICAgICAgICBmaXJzdF91c2VyID0gbmV4dCgKICAgICAgICAgICAgICAgIChtWyJjb250"
    "ZW50Il0gZm9yIG0gaW4gc2VsZi5fbWVzc2FnZXMgaWYgbVsicm9sZSJdID09ICJ1c2VyIiksCiAgICAgICAgICAgICAgICAiIgog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIHdvcmRzID0gZmlyc3RfdXNlci5zcGxpdCgpWzo1XQogICAgICAgICAgICBuYW1lICA9"
    "ICIgIi5qb2luKHdvcmRzKSBpZiB3b3JkcyBlbHNlIGYiU2Vzc2lvbiB7dG9kYXl9IgoKICAgICAgICBlbnRyeSA9IHsKICAgICAg"
    "ICAgICAgImRhdGUiOiAgICAgICAgICB0b2RheSwKICAgICAgICAgICAgInNlc3Npb25faWQiOiAgICBzZWxmLl9zZXNzaW9uX2lk"
    "LAogICAgICAgICAgICAibmFtZSI6ICAgICAgICAgIG5hbWUsCiAgICAgICAgICAgICJtZXNzYWdlX2NvdW50IjogbGVuKHNlbGYu"
    "X21lc3NhZ2VzKSwKICAgICAgICAgICAgImZpcnN0X21lc3NhZ2UiOiAoc2VsZi5fbWVzc2FnZXNbMF1bInRpbWVzdGFtcCJdCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAgICAgICAgICAibGFzdF9t"
    "ZXNzYWdlIjogIChzZWxmLl9tZXNzYWdlc1stMV1bInRpbWVzdGFtcCJdCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlm"
    "IHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAgICAgIH0KCiAgICAgICAgaWYgZXhpc3Rpbmc6CiAgICAgICAgICAgIGlkeCA9"
    "IGluZGV4WyJzZXNzaW9ucyJdLmluZGV4KGV4aXN0aW5nKQogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMiXVtpZHhdID0gZW50"
    "cnkKICAgICAgICBlbHNlOgogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMiXS5pbnNlcnQoMCwgZW50cnkpCgogICAgICAgICMg"
    "S2VlcCBsYXN0IDM2NSBkYXlzIGluIGluZGV4CiAgICAgICAgaW5kZXhbInNlc3Npb25zIl0gPSBpbmRleFsic2Vzc2lvbnMiXVs6"
    "MzY1XQogICAgICAgIHNlbGYuX3NhdmVfaW5kZXgoaW5kZXgpCgogICAgIyDilIDilIAgTE9BRCAvIEpPVVJOQUwg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbGlz"
    "dF9zZXNzaW9ucyhzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIiIlJldHVybiBhbGwgc2Vzc2lvbnMgZnJvbSBpbmRleCwg"
    "bmV3ZXN0IGZpcnN0LiIiIgogICAgICAgIHJldHVybiBzZWxmLl9sb2FkX2luZGV4KCkuZ2V0KCJzZXNzaW9ucyIsIFtdKQoKICAg"
    "IGRlZiBsb2FkX3Nlc3Npb25fYXNfY29udGV4dChzZWxmLCBzZXNzaW9uX2RhdGU6IHN0cikgLT4gc3RyOgogICAgICAgICIiIgog"
    "ICAgICAgIExvYWQgYSBwYXN0IHNlc3Npb24gYXMgYSBjb250ZXh0IGluamVjdGlvbiBzdHJpbmcuCiAgICAgICAgUmV0dXJucyBm"
    "b3JtYXR0ZWQgdGV4dCB0byBwcmVwZW5kIHRvIHRoZSBzeXN0ZW0gcHJvbXB0LgogICAgICAgIFRoaXMgaXMgTk9UIHJlYWwgbWVt"
    "b3J5IOKAlCBpdCdzIGEgdGVtcG9yYXJ5IGNvbnRleHQgd2luZG93IGluamVjdGlvbgogICAgICAgIHVudGlsIHRoZSBQaGFzZSAy"
    "IG1lbW9yeSBzeXN0ZW0gaXMgYnVpbHQuCiAgICAgICAgIiIiCiAgICAgICAgcGF0aCA9IHNlbGYuX3Nlc3Npb25zX2RpciAvIGYi"
    "e3Nlc3Npb25fZGF0ZX0uanNvbmwiCiAgICAgICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiAiIgoK"
    "ICAgICAgICBtZXNzYWdlcyA9IHJlYWRfanNvbmwocGF0aCkKICAgICAgICBzZWxmLl9sb2FkZWRfam91cm5hbCA9IHNlc3Npb25f"
    "ZGF0ZQoKICAgICAgICBsaW5lcyA9IFtmIltKT1VSTkFMIExPQURFRCDigJQge3Nlc3Npb25fZGF0ZX1dIiwKICAgICAgICAgICAg"
    "ICAgICAiVGhlIGZvbGxvd2luZyBpcyBhIHJlY29yZCBvZiBhIHByaW9yIGNvbnZlcnNhdGlvbi4iLAogICAgICAgICAgICAgICAg"
    "ICJVc2UgdGhpcyBhcyBjb250ZXh0IGZvciB0aGUgY3VycmVudCBzZXNzaW9uOlxuIl0KCiAgICAgICAgIyBJbmNsdWRlIHVwIHRv"
    "IGxhc3QgMzAgbWVzc2FnZXMgZnJvbSB0aGF0IHNlc3Npb24KICAgICAgICBmb3IgbXNnIGluIG1lc3NhZ2VzWy0zMDpdOgogICAg"
    "ICAgICAgICByb2xlICAgID0gbXNnLmdldCgicm9sZSIsICI/IikudXBwZXIoKQogICAgICAgICAgICBjb250ZW50ID0gbXNnLmdl"
    "dCgiY29udGVudCIsICIiKVs6MzAwXQogICAgICAgICAgICB0cyAgICAgID0gbXNnLmdldCgidGltZXN0YW1wIiwgIiIpWzoxNl0K"
    "ICAgICAgICAgICAgbGluZXMuYXBwZW5kKGYiW3t0c31dIHtyb2xlfToge2NvbnRlbnR9IikKCiAgICAgICAgbGluZXMuYXBwZW5k"
    "KCJbRU5EIEpPVVJOQUxdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKGxpbmVzKQoKICAgIGRlZiBjbGVhcl9sb2FkZWRfam91"
    "cm5hbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFsID0gTm9uZQoKICAgIEBwcm9wZXJ0eQogICAg"
    "ZGVmIGxvYWRlZF9qb3VybmFsX2RhdGUoc2VsZikgLT4gT3B0aW9uYWxbc3RyXToKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZGVk"
    "X2pvdXJuYWwKCiAgICBkZWYgcmVuYW1lX3Nlc3Npb24oc2VsZiwgc2Vzc2lvbl9kYXRlOiBzdHIsIG5ld19uYW1lOiBzdHIpIC0+"
    "IGJvb2w6CiAgICAgICAgIiIiUmVuYW1lIGEgc2Vzc2lvbiBpbiB0aGUgaW5kZXguIFJldHVybnMgVHJ1ZSBvbiBzdWNjZXNzLiIi"
    "IgogICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAgICAgICAgZm9yIGVudHJ5IGluIGluZGV4WyJzZXNzaW9ucyJd"
    "OgogICAgICAgICAgICBpZiBlbnRyeVsiZGF0ZSJdID09IHNlc3Npb25fZGF0ZToKICAgICAgICAgICAgICAgIGVudHJ5WyJuYW1l"
    "Il0gPSBuZXdfbmFtZVs6ODBdCiAgICAgICAgICAgICAgICBzZWxmLl9zYXZlX2luZGV4KGluZGV4KQogICAgICAgICAgICAgICAg"
    "cmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICAjIOKUgOKUgCBJTkRFWCBIRUxQRVJTIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9sb2Fk"
    "X2luZGV4KHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgaWYgbm90IHNlbGYuX2luZGV4X3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAg"
    "IHJldHVybiB7InNlc3Npb25zIjogW119CiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXR1cm4ganNvbi5sb2FkcygKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2luZGV4X3BhdGgucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpCiAgICAgICAgICAgICkKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4geyJzZXNzaW9ucyI6IFtdfQoKICAgIGRlZiBfc2F2ZV9pbmRl"
    "eChzZWxmLCBpbmRleDogZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9pbmRleF9wYXRoLndyaXRlX3RleHQoCiAgICAgICAg"
    "ICAgIGpzb24uZHVtcHMoaW5kZXgsIGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04IgogICAgICAgICkKCgojIOKUgOKUgCBMRVNT"
    "T05TIExFQVJORUQgREFUQUJBU0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIExlc3NvbnNMZWFybmVkREI6CiAgICAiIiIKICAgIFBlcnNpc3RlbnQga25vd2xl"
    "ZGdlIGJhc2UgZm9yIGNvZGUgbGVzc29ucywgcnVsZXMsIGFuZCByZXNvbHV0aW9ucy4KCiAgICBDb2x1bW5zIHBlciByZWNvcmQ6"
    "CiAgICAgICAgaWQsIGNyZWF0ZWRfYXQsIGVudmlyb25tZW50IChMU0x8UHl0aG9ufFB5U2lkZTZ8Li4uKSwgbGFuZ3VhZ2UsCiAg"
    "ICAgICAgcmVmZXJlbmNlX2tleSAoc2hvcnQgdW5pcXVlIHRhZyksIHN1bW1hcnksIGZ1bGxfcnVsZSwKICAgICAgICByZXNvbHV0"
    "aW9uLCBsaW5rLCB0YWdzCgogICAgUXVlcmllZCBGSVJTVCBiZWZvcmUgYW55IGNvZGUgc2Vzc2lvbiBpbiB0aGUgcmVsZXZhbnQg"
    "bGFuZ3VhZ2UuCiAgICBUaGUgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGxpdmVzIGhlcmUuCiAgICBHcm93aW5nLCBub24tZHVwbGlj"
    "YXRpbmcsIHNlYXJjaGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fcGF0aCA9IGNm"
    "Z19wYXRoKCJtZW1vcmllcyIpIC8gImxlc3NvbnNfbGVhcm5lZC5qc29ubCIKCiAgICBkZWYgYWRkKHNlbGYsIGVudmlyb25tZW50"
    "OiBzdHIsIGxhbmd1YWdlOiBzdHIsIHJlZmVyZW5jZV9rZXk6IHN0ciwKICAgICAgICAgICAgc3VtbWFyeTogc3RyLCBmdWxsX3J1"
    "bGU6IHN0ciwgcmVzb2x1dGlvbjogc3RyID0gIiIsCiAgICAgICAgICAgIGxpbms6IHN0ciA9ICIiLCB0YWdzOiBsaXN0ID0gTm9u"
    "ZSkgLT4gZGljdDoKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgICAgZiJsZXNzb25fe3V1aWQu"
    "dXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICAgIGxvY2FsX25vd19pc28oKSwKICAgICAgICAg"
    "ICAgImVudmlyb25tZW50IjogICBlbnZpcm9ubWVudCwKICAgICAgICAgICAgImxhbmd1YWdlIjogICAgICBsYW5ndWFnZSwKICAg"
    "ICAgICAgICAgInJlZmVyZW5jZV9rZXkiOiByZWZlcmVuY2Vfa2V5LAogICAgICAgICAgICAic3VtbWFyeSI6ICAgICAgIHN1bW1h"
    "cnksCiAgICAgICAgICAgICJmdWxsX3J1bGUiOiAgICAgZnVsbF9ydWxlLAogICAgICAgICAgICAicmVzb2x1dGlvbiI6ICAgIHJl"
    "c29sdXRpb24sCiAgICAgICAgICAgICJsaW5rIjogICAgICAgICAgbGluaywKICAgICAgICAgICAgInRhZ3MiOiAgICAgICAgICB0"
    "YWdzIG9yIFtdLAogICAgICAgIH0KICAgICAgICBpZiBub3Qgc2VsZi5faXNfZHVwbGljYXRlKHJlZmVyZW5jZV9rZXkpOgogICAg"
    "ICAgICAgICBhcHBlbmRfanNvbmwoc2VsZi5fcGF0aCwgcmVjb3JkKQogICAgICAgIHJldHVybiByZWNvcmQKCiAgICBkZWYgc2Vh"
    "cmNoKHNlbGYsIHF1ZXJ5OiBzdHIgPSAiIiwgZW52aXJvbm1lbnQ6IHN0ciA9ICIiLAogICAgICAgICAgICAgICBsYW5ndWFnZTog"
    "c3RyID0gIiIpIC0+IGxpc3RbZGljdF06CiAgICAgICAgcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBy"
    "ZXN1bHRzID0gW10KICAgICAgICBxID0gcXVlcnkubG93ZXIoKQogICAgICAgIGZvciByIGluIHJlY29yZHM6CiAgICAgICAgICAg"
    "IGlmIGVudmlyb25tZW50IGFuZCByLmdldCgiZW52aXJvbm1lbnQiLCIiKS5sb3dlcigpICE9IGVudmlyb25tZW50Lmxvd2VyKCk6"
    "CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBsYW5ndWFnZSBhbmQgci5nZXQoImxhbmd1YWdlIiwiIiku"
    "bG93ZXIoKSAhPSBsYW5ndWFnZS5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgcToKICAg"
    "ICAgICAgICAgICAgIGhheXN0YWNrID0gIiAiLmpvaW4oWwogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJzdW1tYXJ5IiwiIiks"
    "CiAgICAgICAgICAgICAgICAgICAgci5nZXQoImZ1bGxfcnVsZSIsIiIpLAogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJyZWZl"
    "cmVuY2Vfa2V5IiwiIiksCiAgICAgICAgICAgICAgICAgICAgIiAiLmpvaW4oci5nZXQoInRhZ3MiLFtdKSksCiAgICAgICAgICAg"
    "ICAgICBdKS5sb3dlcigpCiAgICAgICAgICAgICAgICBpZiBxIG5vdCBpbiBoYXlzdGFjazoKICAgICAgICAgICAgICAgICAgICBj"
    "b250aW51ZQogICAgICAgICAgICByZXN1bHRzLmFwcGVuZChyKQogICAgICAgIHJldHVybiByZXN1bHRzCgogICAgZGVmIGdldF9h"
    "bGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChzZWxmLl9wYXRoKQoKICAgIGRlZiBkZWxl"
    "dGUoc2VsZiwgcmVjb3JkX2lkOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkK"
    "ICAgICAgICBmaWx0ZXJlZCA9IFtyIGZvciByIGluIHJlY29yZHMgaWYgci5nZXQoImlkIikgIT0gcmVjb3JkX2lkXQogICAgICAg"
    "IGlmIGxlbihmaWx0ZXJlZCkgPCBsZW4ocmVjb3Jkcyk6CiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIGZpbHRl"
    "cmVkKQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVybiBGYWxzZQoKICAgIGRlZiBidWlsZF9jb250ZXh0X2Zv"
    "cl9sYW5ndWFnZShzZWxmLCBsYW5ndWFnZTogc3RyLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIG1heF9jaGFy"
    "czogaW50ID0gMTUwMCkgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIEJ1aWxkIGEgY29udGV4dCBzdHJpbmcgb2YgYWxsIHJ1"
    "bGVzIGZvciBhIGdpdmVuIGxhbmd1YWdlLgogICAgICAgIEZvciBpbmplY3Rpb24gaW50byBzeXN0ZW0gcHJvbXB0IGJlZm9yZSBj"
    "b2RlIHNlc3Npb25zLgogICAgICAgICIiIgogICAgICAgIHJlY29yZHMgPSBzZWxmLnNlYXJjaChsYW5ndWFnZT1sYW5ndWFnZSkK"
    "ICAgICAgICBpZiBub3QgcmVjb3JkczoKICAgICAgICAgICAgcmV0dXJuICIiCgogICAgICAgIHBhcnRzID0gW2YiW3tsYW5ndWFn"
    "ZS51cHBlcigpfSBSVUxFUyDigJQgQVBQTFkgQkVGT1JFIFdSSVRJTkcgQ09ERV0iXQogICAgICAgIHRvdGFsID0gMAogICAgICAg"
    "IGZvciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGVudHJ5ID0gZiLigKIge3IuZ2V0KCdyZWZlcmVuY2Vfa2V5JywnJyl9OiB7"
    "ci5nZXQoJ2Z1bGxfcnVsZScsJycpfSIKICAgICAgICAgICAgaWYgdG90YWwgKyBsZW4oZW50cnkpID4gbWF4X2NoYXJzOgogICAg"
    "ICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGVudHJ5KQogICAgICAgICAgICB0b3RhbCArPSBsZW4o"
    "ZW50cnkpCgogICAgICAgIHBhcnRzLmFwcGVuZChmIltFTkQge2xhbmd1YWdlLnVwcGVyKCl9IFJVTEVTXSIpCiAgICAgICAgcmV0"
    "dXJuICJcbiIuam9pbihwYXJ0cykKCiAgICBkZWYgX2lzX2R1cGxpY2F0ZShzZWxmLCByZWZlcmVuY2Vfa2V5OiBzdHIpIC0+IGJv"
    "b2w6CiAgICAgICAgcmV0dXJuIGFueSgKICAgICAgICAgICAgci5nZXQoInJlZmVyZW5jZV9rZXkiLCIiKS5sb3dlcigpID09IHJl"
    "ZmVyZW5jZV9rZXkubG93ZXIoKQogICAgICAgICAgICBmb3IgciBpbiByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgKQoK"
    "ICAgIGRlZiBzZWVkX2xzbF9ydWxlcyhzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIFNlZWQgdGhlIExTTCBGb3Ji"
    "aWRkZW4gUnVsZXNldCBvbiBmaXJzdCBydW4gaWYgdGhlIERCIGlzIGVtcHR5LgogICAgICAgIFRoZXNlIGFyZSB0aGUgaGFyZCBy"
    "dWxlcyBmcm9tIHRoZSBwcm9qZWN0IHN0YW5kaW5nIHJ1bGVzLgogICAgICAgICIiIgogICAgICAgIGlmIHJlYWRfanNvbmwoc2Vs"
    "Zi5fcGF0aCk6CiAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5IHNlZWRlZAoKICAgICAgICBsc2xfcnVsZXMgPSBbCiAgICAg"
    "ICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19URVJOQVJZIiwKICAgICAgICAgICAgICJObyB0ZXJuYXJ5IG9wZXJhdG9ycyBpbiBM"
    "U0wiLAogICAgICAgICAgICAgIk5ldmVyIHVzZSB0aGUgdGVybmFyeSBvcGVyYXRvciAoPzopIGluIExTTCBzY3JpcHRzLiAiCiAg"
    "ICAgICAgICAgICAiVXNlIGlmL2Vsc2UgYmxvY2tzIGluc3RlYWQuIExTTCBkb2VzIG5vdCBzdXBwb3J0IHRlcm5hcnkuIiwKICAg"
    "ICAgICAgICAgICJSZXBsYWNlIHdpdGggaWYvZWxzZSBibG9jay4iLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJO"
    "T19GT1JFQUNIIiwKICAgICAgICAgICAgICJObyBmb3JlYWNoIGxvb3BzIGluIExTTCIsCiAgICAgICAgICAgICAiTFNMIGhhcyBu"
    "byBmb3JlYWNoIGxvb3AgY29uc3RydWN0LiBVc2UgaW50ZWdlciBpbmRleCB3aXRoICIKICAgICAgICAgICAgICJsbEdldExpc3RM"
    "ZW5ndGgoKSBhbmQgYSBmb3Igb3Igd2hpbGUgbG9vcC4iLAogICAgICAgICAgICAgIlVzZTogZm9yKGludGVnZXIgaT0wOyBpPGxs"
    "R2V0TGlzdExlbmd0aChteUxpc3QpOyBpKyspIiwgIiIpLAogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fR0xPQkFMX0FT"
    "U0lHTl9GUk9NX0ZVTkMiLAogICAgICAgICAgICAgIk5vIGdsb2JhbCB2YXJpYWJsZSBhc3NpZ25tZW50cyBmcm9tIGZ1bmN0aW9u"
    "IGNhbGxzIiwKICAgICAgICAgICAgICJHbG9iYWwgdmFyaWFibGUgaW5pdGlhbGl6YXRpb24gaW4gTFNMIGNhbm5vdCBjYWxsIGZ1"
    "bmN0aW9ucy4gIgogICAgICAgICAgICAgIkluaXRpYWxpemUgZ2xvYmFscyB3aXRoIGxpdGVyYWwgdmFsdWVzIG9ubHkuICIKICAg"
    "ICAgICAgICAgICJBc3NpZ24gZnJvbSBmdW5jdGlvbnMgaW5zaWRlIGV2ZW50IGhhbmRsZXJzIG9yIG90aGVyIGZ1bmN0aW9ucy4i"
    "LAogICAgICAgICAgICAgIk1vdmUgdGhlIGFzc2lnbm1lbnQgaW50byBhbiBldmVudCBoYW5kbGVyIChzdGF0ZV9lbnRyeSwgZXRj"
    "LikiLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19WT0lEX0tFWVdPUkQiLAogICAgICAgICAgICAgIk5vIHZv"
    "aWQga2V5d29yZCBpbiBMU0wiLAogICAgICAgICAgICAgIkxTTCBkb2VzIG5vdCBoYXZlIGEgdm9pZCBrZXl3b3JkIGZvciBmdW5j"
    "dGlvbiByZXR1cm4gdHlwZXMuICIKICAgICAgICAgICAgICJGdW5jdGlvbnMgdGhhdCByZXR1cm4gbm90aGluZyBzaW1wbHkgb21p"
    "dCB0aGUgcmV0dXJuIHR5cGUuIiwKICAgICAgICAgICAgICJSZW1vdmUgJ3ZvaWQnIGZyb20gZnVuY3Rpb24gc2lnbmF0dXJlLiAi"
    "CiAgICAgICAgICAgICAiZS5nLiBteUZ1bmMoKSB7IC4uLiB9IG5vdCB2b2lkIG15RnVuYygpIHsgLi4uIH0iLCAiIiksCiAgICAg"
    "ICAgICAgICgiTFNMIiwgIkxTTCIsICJDT01QTEVURV9TQ1JJUFRTX09OTFkiLAogICAgICAgICAgICAgIkFsd2F5cyBwcm92aWRl"
    "IGNvbXBsZXRlIHNjcmlwdHMsIG5ldmVyIHBhcnRpYWwgZWRpdHMiLAogICAgICAgICAgICAgIldoZW4gd3JpdGluZyBvciBlZGl0"
    "aW5nIExTTCBzY3JpcHRzLCBhbHdheXMgb3V0cHV0IHRoZSBjb21wbGV0ZSAiCiAgICAgICAgICAgICAic2NyaXB0LiBOZXZlciBw"
    "cm92aWRlIHBhcnRpYWwgc25pcHBldHMgb3IgJ2FkZCB0aGlzIHNlY3Rpb24nICIKICAgICAgICAgICAgICJpbnN0cnVjdGlvbnMu"
    "IFRoZSBmdWxsIHNjcmlwdCBtdXN0IGJlIGNvcHktcGFzdGUgcmVhZHkuIiwKICAgICAgICAgICAgICJXcml0ZSB0aGUgZW50aXJl"
    "IHNjcmlwdCBmcm9tIHRvcCB0byBib3R0b20uIiwgIiIpLAogICAgICAgIF0KCiAgICAgICAgZm9yIGVudiwgbGFuZywgcmVmLCBz"
    "dW1tYXJ5LCBmdWxsX3J1bGUsIHJlc29sdXRpb24sIGxpbmsgaW4gbHNsX3J1bGVzOgogICAgICAgICAgICBzZWxmLmFkZChlbnYs"
    "IGxhbmcsIHJlZiwgc3VtbWFyeSwgZnVsbF9ydWxlLCByZXNvbHV0aW9uLCBsaW5rLAogICAgICAgICAgICAgICAgICAgICB0YWdz"
    "PVsibHNsIiwgImZvcmJpZGRlbiIsICJzdGFuZGluZ19ydWxlIl0pCgoKIyDilIDilIAgVEFTSyBNQU5BR0VSIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBUYXNrTWFuYWdlcjoKICAgICIiIgogICAgVGFzay9yZW1pbmRlciBDUlVEIGFu"
    "ZCBkdWUtZXZlbnQgZGV0ZWN0aW9uLgoKICAgIEZpbGU6IG1lbW9yaWVzL3Rhc2tzLmpzb25sCgogICAgVGFzayByZWNvcmQgZmll"
    "bGRzOgogICAgICAgIGlkLCBjcmVhdGVkX2F0LCBkdWVfYXQsIHByZV90cmlnZ2VyICgxbWluIGJlZm9yZSksCiAgICAgICAgdGV4"
    "dCwgc3RhdHVzIChwZW5kaW5nfHRyaWdnZXJlZHxzbm9vemVkfGNvbXBsZXRlZHxjYW5jZWxsZWQpLAogICAgICAgIGFja25vd2xl"
    "ZGdlZF9hdCwgcmV0cnlfY291bnQsIGxhc3RfdHJpZ2dlcmVkX2F0LCBuZXh0X3JldHJ5X2F0LAogICAgICAgIHNvdXJjZSAobG9j"
    "YWx8Z29vZ2xlKSwgZ29vZ2xlX2V2ZW50X2lkLCBzeW5jX3N0YXR1cywgbWV0YWRhdGEKCiAgICBEdWUtZXZlbnQgY3ljbGU6CiAg"
    "ICAgICAgLSBQcmUtdHJpZ2dlcjogMSBtaW51dGUgYmVmb3JlIGR1ZSDihpIgYW5ub3VuY2UgdXBjb21pbmcKICAgICAgICAtIER1"
    "ZSB0cmlnZ2VyOiBhdCBkdWUgdGltZSDihpIgYWxlcnQgc291bmQgKyBBSSBjb21tZW50YXJ5CiAgICAgICAgLSAzLW1pbnV0ZSB3"
    "aW5kb3c6IGlmIG5vdCBhY2tub3dsZWRnZWQg4oaSIHNub296ZQogICAgICAgIC0gMTItbWludXRlIHJldHJ5OiByZS10cmlnZ2Vy"
    "CiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIp"
    "IC8gInRhc2tzLmpzb25sIgoKICAgICMg4pSA4pSAIENSVUQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbG9h"
    "ZF9hbGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICB0YXNrcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBj"
    "aGFuZ2VkID0gRmFsc2UKICAgICAgICBub3JtYWxpemVkID0gW10KICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAg"
    "aWYgbm90IGlzaW5zdGFuY2UodCwgZGljdCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiAiaWQiIG5v"
    "dCBpbiB0OgogICAgICAgICAgICAgICAgdFsiaWQiXSA9IGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIKICAgICAgICAg"
    "ICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICMgTm9ybWFsaXplIGZpZWxkIG5hbWVzCiAgICAgICAgICAgIGlmICJk"
    "dWVfYXQiIG5vdCBpbiB0OgogICAgICAgICAgICAgICAgdFsiZHVlX2F0Il0gPSB0LmdldCgiZHVlIikKICAgICAgICAgICAgICAg"
    "IGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3RhdHVzIiwgICAgICAgICAgICJwZW5kaW5nIikKICAg"
    "ICAgICAgICAgdC5zZXRkZWZhdWx0KCJyZXRyeV9jb3VudCIsICAgICAgMCkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJhY2tu"
    "b3dsZWRnZWRfYXQiLCAgTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJsYXN0X3RyaWdnZXJlZF9hdCIsTm9uZSkKICAg"
    "ICAgICAgICAgdC5zZXRkZWZhdWx0KCJuZXh0X3JldHJ5X2F0IiwgICAgTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJw"
    "cmVfYW5ub3VuY2VkIiwgICAgRmFsc2UpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic291cmNlIiwgICAgICAgICAgICJsb2Nh"
    "bCIpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiZ29vZ2xlX2V2ZW50X2lkIiwgIE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVm"
    "YXVsdCgic3luY19zdGF0dXMiLCAgICAgICJwZW5kaW5nIikKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJtZXRhZGF0YSIsICAg"
    "ICAgICAge30pCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiY3JlYXRlZF9hdCIsICAgICAgIGxvY2FsX25vd19pc28oKSkKCiAg"
    "ICAgICAgICAgICMgQ29tcHV0ZSBwcmVfdHJpZ2dlciBpZiBtaXNzaW5nCiAgICAgICAgICAgIGlmIHQuZ2V0KCJkdWVfYXQiKSBh"
    "bmQgbm90IHQuZ2V0KCJwcmVfdHJpZ2dlciIpOgogICAgICAgICAgICAgICAgZHQgPSBwYXJzZV9pc28odFsiZHVlX2F0Il0pCiAg"
    "ICAgICAgICAgICAgICBpZiBkdDoKICAgICAgICAgICAgICAgICAgICBwcmUgPSBkdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpCiAg"
    "ICAgICAgICAgICAgICAgICAgdFsicHJlX3RyaWdnZXIiXSA9IHByZS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAg"
    "ICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgICAgICBub3JtYWxpemVkLmFwcGVuZCh0KQoKICAgICAgICBp"
    "ZiBjaGFuZ2VkOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBub3JtYWxpemVkKQogICAgICAgIHJldHVybiBu"
    "b3JtYWxpemVkCgogICAgZGVmIHNhdmVfYWxsKHNlbGYsIHRhc2tzOiBsaXN0W2RpY3RdKSAtPiBOb25lOgogICAgICAgIHdyaXRl"
    "X2pzb25sKHNlbGYuX3BhdGgsIHRhc2tzKQoKICAgIGRlZiBhZGQoc2VsZiwgdGV4dDogc3RyLCBkdWVfZHQ6IGRhdGV0aW1lLAog"
    "ICAgICAgICAgICBzb3VyY2U6IHN0ciA9ICJsb2NhbCIpIC0+IGRpY3Q6CiAgICAgICAgcHJlID0gZHVlX2R0IC0gdGltZWRlbHRh"
    "KG1pbnV0ZXM9MSkKICAgICAgICB0YXNrID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICAgIGYidGFza197dXVpZC51"
    "dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgICAgbG9jYWxfbm93X2lzbygpLAogICAgICAg"
    "ICAgICAiZHVlX2F0IjogICAgICAgICAgIGR1ZV9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAg"
    "InByZV90cmlnZ2VyIjogICAgICBwcmUuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICJ0ZXh0Ijog"
    "ICAgICAgICAgICAgdGV4dC5zdHJpcCgpLAogICAgICAgICAgICAic3RhdHVzIjogICAgICAgICAgICJwZW5kaW5nIiwKICAgICAg"
    "ICAgICAgImFja25vd2xlZGdlZF9hdCI6ICBOb25lLAogICAgICAgICAgICAicmV0cnlfY291bnQiOiAgICAgIDAsCiAgICAgICAg"
    "ICAgICJsYXN0X3RyaWdnZXJlZF9hdCI6Tm9uZSwKICAgICAgICAgICAgIm5leHRfcmV0cnlfYXQiOiAgICBOb25lLAogICAgICAg"
    "ICAgICAicHJlX2Fubm91bmNlZCI6ICAgIEZhbHNlLAogICAgICAgICAgICAic291cmNlIjogICAgICAgICAgIHNvdXJjZSwKICAg"
    "ICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6ICBOb25lLAogICAgICAgICAgICAic3luY19zdGF0dXMiOiAgICAgICJwZW5kaW5n"
    "IiwKICAgICAgICAgICAgIm1ldGFkYXRhIjogICAgICAgICB7fSwKICAgICAgICB9CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRf"
    "YWxsKCkKICAgICAgICB0YXNrcy5hcHBlbmQodGFzaykKICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgIHJldHVy"
    "biB0YXNrCgogICAgZGVmIHVwZGF0ZV9zdGF0dXMoc2VsZiwgdGFza19pZDogc3RyLCBzdGF0dXM6IHN0ciwKICAgICAgICAgICAg"
    "ICAgICAgICAgIGFja25vd2xlZGdlZDogYm9vbCA9IEZhbHNlKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNl"
    "bGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lk"
    "OgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gPSBzdGF0dXMKICAgICAgICAgICAgICAgIGlmIGFja25vd2xlZGdlZDoKICAg"
    "ICAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgc2Vs"
    "Zi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY29t"
    "cGxldGUoc2VsZiwgdGFza19pZDogc3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwo"
    "KQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAg"
    "ICAgICAgdFsic3RhdHVzIl0gICAgICAgICAgPSAiY29tcGxldGVkIgogICAgICAgICAgICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0"
    "Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAgICAgICBy"
    "ZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNhbmNlbChzZWxmLCB0YXNrX2lkOiBzdHIpIC0+IE9wdGlvbmFs"
    "W2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAg"
    "IGlmIHQuZ2V0KCJpZCIpID09IHRhc2tfaWQ6CiAgICAgICAgICAgICAgICB0WyJzdGF0dXMiXSAgICAgICAgICA9ICJjYW5jZWxs"
    "ZWQiCiAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAg"
    "c2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYg"
    "Y2xlYXJfY29tcGxldGVkKHNlbGYpIC0+IGludDoKICAgICAgICB0YXNrcyAgICA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGtl"
    "cHQgICAgID0gW3QgZm9yIHQgaW4gdGFza3MKICAgICAgICAgICAgICAgICAgICBpZiB0LmdldCgic3RhdHVzIikgbm90IGluIHsi"
    "Y29tcGxldGVkIiwiY2FuY2VsbGVkIn1dCiAgICAgICAgcmVtb3ZlZCAgPSBsZW4odGFza3MpIC0gbGVuKGtlcHQpCiAgICAgICAg"
    "aWYgcmVtb3ZlZDoKICAgICAgICAgICAgc2VsZi5zYXZlX2FsbChrZXB0KQogICAgICAgIHJldHVybiByZW1vdmVkCgogICAgZGVm"
    "IHVwZGF0ZV9nb29nbGVfc3luYyhzZWxmLCB0YXNrX2lkOiBzdHIsIHN5bmNfc3RhdHVzOiBzdHIsCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGdvb2dsZV9ldmVudF9pZDogc3RyID0gIiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgIGVycm9yOiBzdHIg"
    "PSAiIikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBmb3IgdCBpbiB0"
    "YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0gdGFza19pZDoKICAgICAgICAgICAgICAgIHRbInN5bmNfc3RhdHVz"
    "Il0gICAgPSBzeW5jX3N0YXR1cwogICAgICAgICAgICAgICAgdFsibGFzdF9zeW5jZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQog"
    "ICAgICAgICAgICAgICAgaWYgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAgICAgICAgICAgIHRbImdvb2dsZV9ldmVudF9pZCJd"
    "ID0gZ29vZ2xlX2V2ZW50X2lkCiAgICAgICAgICAgICAgICBpZiBlcnJvcjoKICAgICAgICAgICAgICAgICAgICB0LnNldGRlZmF1"
    "bHQoIm1ldGFkYXRhIiwge30pCiAgICAgICAgICAgICAgICAgICAgdFsibWV0YWRhdGEiXVsiZ29vZ2xlX3N5bmNfZXJyb3IiXSA9"
    "IGVycm9yWzoyNDBdCiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICAgICAgcmV0dXJuIHQK"
    "ICAgICAgICByZXR1cm4gTm9uZQoKICAgICMg4pSA4pSAIERVRSBFVkVOVCBERVRFQ1RJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgZ2V0X2R1ZV9ldmVudHMoc2VsZikgLT4gbGlzdFt0"
    "dXBsZVtzdHIsIGRpY3RdXToKICAgICAgICAiIiIKICAgICAgICBDaGVjayBhbGwgdGFza3MgZm9yIGR1ZS9wcmUtdHJpZ2dlci9y"
    "ZXRyeSBldmVudHMuCiAgICAgICAgUmV0dXJucyBsaXN0IG9mIChldmVudF90eXBlLCB0YXNrKSB0dXBsZXMuCiAgICAgICAgZXZl"
    "bnRfdHlwZTogInByZSIgfCAiZHVlIiB8ICJyZXRyeSIKCiAgICAgICAgTW9kaWZpZXMgdGFzayBzdGF0dXNlcyBpbiBwbGFjZSBh"
    "bmQgc2F2ZXMuCiAgICAgICAgQ2FsbCBmcm9tIEFQU2NoZWR1bGVyIGV2ZXJ5IDMwIHNlY29uZHMuCiAgICAgICAgIiIiCiAgICAg"
    "ICAgbm93ICAgID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpCiAgICAgICAgdGFza3MgID0gc2VsZi5sb2FkX2FsbCgpCiAg"
    "ICAgICAgZXZlbnRzID0gW10KICAgICAgICBjaGFuZ2VkID0gRmFsc2UKCiAgICAgICAgZm9yIHRhc2sgaW4gdGFza3M6CiAgICAg"
    "ICAgICAgIGlmIHRhc2suZ2V0KCJhY2tub3dsZWRnZWRfYXQiKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAg"
    "ICBzdGF0dXMgICA9IHRhc2suZ2V0KCJzdGF0dXMiLCAicGVuZGluZyIpCiAgICAgICAgICAgIGR1ZSAgICAgID0gc2VsZi5fcGFy"
    "c2VfbG9jYWwodGFzay5nZXQoImR1ZV9hdCIpKQogICAgICAgICAgICBwcmUgICAgICA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2su"
    "Z2V0KCJwcmVfdHJpZ2dlciIpKQogICAgICAgICAgICBuZXh0X3JldCA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJuZXh0"
    "X3JldHJ5X2F0IikpCiAgICAgICAgICAgIGRlYWRsaW5lID0gc2VsZi5fcGFyc2VfbG9jYWwodGFzay5nZXQoImFsZXJ0X2RlYWRs"
    "aW5lIikpCgogICAgICAgICAgICAjIFByZS10cmlnZ2VyCiAgICAgICAgICAgIGlmIChzdGF0dXMgPT0gInBlbmRpbmciIGFuZCBw"
    "cmUgYW5kIG5vdyA+PSBwcmUKICAgICAgICAgICAgICAgICAgICBhbmQgbm90IHRhc2suZ2V0KCJwcmVfYW5ub3VuY2VkIikpOgog"
    "ICAgICAgICAgICAgICAgdGFza1sicHJlX2Fubm91bmNlZCJdID0gVHJ1ZQogICAgICAgICAgICAgICAgZXZlbnRzLmFwcGVuZCgo"
    "InByZSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICAgICAgICAgICMgRHVlIHRyaWdnZXIKICAg"
    "ICAgICAgICAgaWYgc3RhdHVzID09ICJwZW5kaW5nIiBhbmQgZHVlIGFuZCBub3cgPj0gZHVlOgogICAgICAgICAgICAgICAgdGFz"
    "a1sic3RhdHVzIl0gICAgICAgICAgID0gInRyaWdnZXJlZCIKICAgICAgICAgICAgICAgIHRhc2tbImxhc3RfdHJpZ2dlcmVkX2F0"
    "Il09IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgdGFza1siYWxlcnRfZGVhZGxpbmUiXSAgID0gKAogICAgICAgICAg"
    "ICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKSArIHRpbWVkZWx0YShtaW51dGVzPTMpCiAgICAgICAgICAgICAg"
    "ICApLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICBldmVudHMuYXBwZW5kKCgiZHVlIiwgdGFz"
    "aykpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICMg"
    "U25vb3plIGFmdGVyIDMtbWludXRlIHdpbmRvdwogICAgICAgICAgICBpZiBzdGF0dXMgPT0gInRyaWdnZXJlZCIgYW5kIGRlYWRs"
    "aW5lIGFuZCBub3cgPj0gZGVhZGxpbmU6CiAgICAgICAgICAgICAgICB0YXNrWyJzdGF0dXMiXSAgICAgICAgPSAic25vb3plZCIK"
    "ICAgICAgICAgICAgICAgIHRhc2tbIm5leHRfcmV0cnlfYXQiXSA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3co"
    "KS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0xMikKICAgICAgICAgICAgICAgICkuaXNvZm9ybWF0KHRpbWVzcGVj"
    "PSJzZWNvbmRzIikKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAg"
    "ICAgICAgIyBSZXRyeQogICAgICAgICAgICBpZiBzdGF0dXMgaW4geyJyZXRyeV9wZW5kaW5nIiwic25vb3plZCJ9IGFuZCBuZXh0"
    "X3JldCBhbmQgbm93ID49IG5leHRfcmV0OgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICAgICAgICA9ICJ0cmln"
    "Z2VyZWQiCiAgICAgICAgICAgICAgICB0YXNrWyJyZXRyeV9jb3VudCJdICAgICAgID0gaW50KHRhc2suZ2V0KCJyZXRyeV9jb3Vu"
    "dCIsMCkpICsgMQogICAgICAgICAgICAgICAgdGFza1sibGFzdF90cmlnZ2VyZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAg"
    "ICAgICAgICAgICAgdGFza1siYWxlcnRfZGVhZGxpbmUiXSAgICA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3co"
    "KS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0zKQogICAgICAgICAgICAgICAgKS5pc29mb3JtYXQodGltZXNwZWM9"
    "InNlY29uZHMiKQogICAgICAgICAgICAgICAgdGFza1sibmV4dF9yZXRyeV9hdCJdICAgICA9IE5vbmUKICAgICAgICAgICAgICAg"
    "IGV2ZW50cy5hcHBlbmQoKCJyZXRyeSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICAgICAgaWYg"
    "Y2hhbmdlZDoKICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICByZXR1cm4gZXZlbnRzCgogICAgZGVmIF9w"
    "YXJzZV9sb2NhbChzZWxmLCB2YWx1ZTogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICAgICAgIiIiUGFyc2UgSVNPIHN0"
    "cmluZyB0byB0aW1lem9uZS1hd2FyZSBkYXRldGltZSBmb3IgY29tcGFyaXNvbi4iIiIKICAgICAgICBkdCA9IHBhcnNlX2lzbyh2"
    "YWx1ZSkKICAgICAgICBpZiBkdCBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGlmIGR0LnR6aW5mbyBp"
    "cyBOb25lOgogICAgICAgICAgICBkdCA9IGR0LmFzdGltZXpvbmUoKQogICAgICAgIHJldHVybiBkdAoKICAgICMg4pSA4pSAIE5B"
    "VFVSQUwgTEFOR1VBR0UgUEFSU0lORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIEBzdGF0"
    "aWNtZXRob2QKICAgIGRlZiBjbGFzc2lmeV9pbnRlbnQodGV4dDogc3RyKSAtPiBkaWN0OgogICAgICAgICIiIgogICAgICAgIENs"
    "YXNzaWZ5IHVzZXIgaW5wdXQgYXMgdGFzay9yZW1pbmRlci90aW1lci9jaGF0LgogICAgICAgIFJldHVybnMgeyJpbnRlbnQiOiBz"
    "dHIsICJjbGVhbmVkX2lucHV0Ijogc3RyfQogICAgICAgICIiIgogICAgICAgIGltcG9ydCByZQogICAgICAgICMgU3RyaXAgY29t"
    "bW9uIGludm9jYXRpb24gcHJlZml4ZXMKICAgICAgICBjbGVhbmVkID0gcmUuc3ViKAogICAgICAgICAgICByZiJeXHMqKD86e0RF"
    "Q0tfTkFNRS5sb3dlcigpfXxoZXlccyt7REVDS19OQU1FLmxvd2VyKCl9KVxzKiw/XHMqWzpcLV0/XHMqIiwKICAgICAgICAgICAg"
    "IiIsIHRleHQsIGZsYWdzPXJlLkkKICAgICAgICApLnN0cmlwKCkKCiAgICAgICAgbG93ID0gY2xlYW5lZC5sb3dlcigpCgogICAg"
    "ICAgIHRpbWVyX3BhdHMgICAgPSBbciJcYnNldCg/OlxzK2EpP1xzK3RpbWVyXGIiLCByIlxidGltZXJccytmb3JcYiIsCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICByIlxic3RhcnQoPzpccythKT9ccyt0aW1lclxiIl0KICAgICAgICByZW1pbmRlcl9wYXRzID0g"
    "W3IiXGJyZW1pbmQgbWVcYiIsIHIiXGJzZXQoPzpccythKT9ccytyZW1pbmRlclxiIiwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "IHIiXGJhZGQoPzpccythKT9ccytyZW1pbmRlclxiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJzZXQoPzpccythbj8p"
    "P1xzK2FsYXJtXGIiLCByIlxiYWxhcm1ccytmb3JcYiJdCiAgICAgICAgdGFza19wYXRzICAgICA9IFtyIlxiYWRkKD86XHMrYSk/"
    "XHMrdGFza1xiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJjcmVhdGUoPzpccythKT9ccyt0YXNrXGIiLCByIlxibmV3"
    "XHMrdGFza1xiIl0KCiAgICAgICAgaW1wb3J0IHJlIGFzIF9yZQogICAgICAgIGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9y"
    "IHAgaW4gdGltZXJfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9ICJ0aW1lciIKICAgICAgICBlbGlmIGFueShfcmUuc2VhcmNo"
    "KHAsIGxvdykgZm9yIHAgaW4gcmVtaW5kZXJfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9ICJyZW1pbmRlciIKICAgICAgICBl"
    "bGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gdGFza19wYXRzKToKICAgICAgICAgICAgaW50ZW50ID0gInRhc2si"
    "CiAgICAgICAgZWxzZToKICAgICAgICAgICAgaW50ZW50ID0gImNoYXQiCgogICAgICAgIHJldHVybiB7ImludGVudCI6IGludGVu"
    "dCwgImNsZWFuZWRfaW5wdXQiOiBjbGVhbmVkfQoKICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBwYXJzZV9kdWVfZGF0ZXRpbWUo"
    "dGV4dDogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICAgICAgIiIiCiAgICAgICAgUGFyc2UgbmF0dXJhbCBsYW5ndWFn"
    "ZSB0aW1lIGV4cHJlc3Npb24gZnJvbSB0YXNrIHRleHQuCiAgICAgICAgSGFuZGxlczogImluIDMwIG1pbnV0ZXMiLCAiYXQgM3Bt"
    "IiwgInRvbW9ycm93IGF0IDlhbSIsCiAgICAgICAgICAgICAgICAgImluIDIgaG91cnMiLCAiYXQgMTU6MzAiLCBldGMuCiAgICAg"
    "ICAgUmV0dXJucyBhIGRhdGV0aW1lIG9yIE5vbmUgaWYgdW5wYXJzZWFibGUuCiAgICAgICAgIiIiCiAgICAgICAgaW1wb3J0IHJl"
    "CiAgICAgICAgbm93ICA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAgbG93ICA9IHRleHQubG93ZXIoKS5zdHJpcCgpCgogICAgICAg"
    "ICMgImluIFggbWludXRlcy9ob3Vycy9kYXlzIgogICAgICAgIG0gPSByZS5zZWFyY2goCiAgICAgICAgICAgIHIiaW5ccysoXGQr"
    "KVxzKihtaW51dGV8bWlufGhvdXJ8aHJ8ZGF5fHNlY29uZHxzZWMpIiwKICAgICAgICAgICAgbG93CiAgICAgICAgKQogICAgICAg"
    "IGlmIG06CiAgICAgICAgICAgIG4gICAgPSBpbnQobS5ncm91cCgxKSkKICAgICAgICAgICAgdW5pdCA9IG0uZ3JvdXAoMikKICAg"
    "ICAgICAgICAgaWYgIm1pbiIgaW4gdW5pdDogIHJldHVybiBub3cgKyB0aW1lZGVsdGEobWludXRlcz1uKQogICAgICAgICAgICBp"
    "ZiAiaG91ciIgaW4gdW5pdCBvciAiaHIiIGluIHVuaXQ6IHJldHVybiBub3cgKyB0aW1lZGVsdGEoaG91cnM9bikKICAgICAgICAg"
    "ICAgaWYgImRheSIgIGluIHVuaXQ6IHJldHVybiBub3cgKyB0aW1lZGVsdGEoZGF5cz1uKQogICAgICAgICAgICBpZiAic2VjIiAg"
    "aW4gdW5pdDogcmV0dXJuIG5vdyArIHRpbWVkZWx0YShzZWNvbmRzPW4pCgogICAgICAgICMgImF0IEhIOk1NIiBvciAiYXQgSDpN"
    "TWFtL3BtIgogICAgICAgIG0gPSByZS5zZWFyY2goCiAgICAgICAgICAgIHIiYXRccysoXGR7MSwyfSkoPzo6KFxkezJ9KSk/XHMq"
    "KGFtfHBtKT8iLAogICAgICAgICAgICBsb3cKICAgICAgICApCiAgICAgICAgaWYgbToKICAgICAgICAgICAgaHIgID0gaW50KG0u"
    "Z3JvdXAoMSkpCiAgICAgICAgICAgIG1uICA9IGludChtLmdyb3VwKDIpKSBpZiBtLmdyb3VwKDIpIGVsc2UgMAogICAgICAgICAg"
    "ICBhcG0gPSBtLmdyb3VwKDMpCiAgICAgICAgICAgIGlmIGFwbSA9PSAicG0iIGFuZCBociA8IDEyOiBociArPSAxMgogICAgICAg"
    "ICAgICBpZiBhcG0gPT0gImFtIiBhbmQgaHIgPT0gMTI6IGhyID0gMAogICAgICAgICAgICBkdCA9IG5vdy5yZXBsYWNlKGhvdXI9"
    "aHIsIG1pbnV0ZT1tbiwgc2Vjb25kPTAsIG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgIGlmIGR0IDw9IG5vdzoKICAgICAgICAg"
    "ICAgICAgIGR0ICs9IHRpbWVkZWx0YShkYXlzPTEpCiAgICAgICAgICAgIHJldHVybiBkdAoKICAgICAgICAjICJ0b21vcnJvdyBh"
    "dCAuLi4iICAocmVjdXJzZSBvbiB0aGUgImF0IiBwYXJ0KQogICAgICAgIGlmICJ0b21vcnJvdyIgaW4gbG93OgogICAgICAgICAg"
    "ICB0b21vcnJvd190ZXh0ID0gcmUuc3ViKHIidG9tb3Jyb3ciLCAiIiwgbG93KS5zdHJpcCgpCiAgICAgICAgICAgIHJlc3VsdCA9"
    "IFRhc2tNYW5hZ2VyLnBhcnNlX2R1ZV9kYXRldGltZSh0b21vcnJvd190ZXh0KQogICAgICAgICAgICBpZiByZXN1bHQ6CiAgICAg"
    "ICAgICAgICAgICByZXR1cm4gcmVzdWx0ICsgdGltZWRlbHRhKGRheXM9MSkKCiAgICAgICAgcmV0dXJuIE5vbmUKCgojIOKUgOKU"
    "gCBSRVFVSVJFTUVOVFMuVFhUIEdFTkVSQVRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKZGVmIHdyaXRlX3JlcXVpcmVtZW50c190eHQoKSAtPiBOb25lOgogICAgIiIiCiAgICBX"
    "cml0ZSByZXF1aXJlbWVudHMudHh0IG5leHQgdG8gdGhlIGRlY2sgZmlsZSBvbiBmaXJzdCBydW4uCiAgICBIZWxwcyB1c2VycyBp"
    "bnN0YWxsIGFsbCBkZXBlbmRlbmNpZXMgd2l0aCBvbmUgcGlwIGNvbW1hbmQuCiAgICAiIiIKICAgIHJlcV9wYXRoID0gUGF0aChD"
    "RkcuZ2V0KCJiYXNlX2RpciIsIHN0cihTQ1JJUFRfRElSKSkpIC8gInJlcXVpcmVtZW50cy50eHQiCiAgICBpZiByZXFfcGF0aC5l"
    "eGlzdHMoKToKICAgICAgICByZXR1cm4KCiAgICBjb250ZW50ID0gIiIiXAojIE1vcmdhbm5hIERlY2sg4oCUIFJlcXVpcmVkIERl"
    "cGVuZGVuY2llcwojIEluc3RhbGwgYWxsIHdpdGg6IHBpcCBpbnN0YWxsIC1yIHJlcXVpcmVtZW50cy50eHQKCiMgQ29yZSBVSQpQ"
    "eVNpZGU2CgojIFNjaGVkdWxpbmcgKGlkbGUgdGltZXIsIGF1dG9zYXZlLCByZWZsZWN0aW9uIGN5Y2xlcykKYXBzY2hlZHVsZXIK"
    "CiMgTG9nZ2luZwpsb2d1cnUKCiMgU291bmQgcGxheWJhY2sgKFdBViArIE1QMykKcHlnYW1lCgojIERlc2t0b3Agc2hvcnRjdXQg"
    "Y3JlYXRpb24gKFdpbmRvd3Mgb25seSkKcHl3aW4zMgoKIyBTeXN0ZW0gbW9uaXRvcmluZyAoQ1BVLCBSQU0sIGRyaXZlcywgbmV0"
    "d29yaykKcHN1dGlsCgojIEhUVFAgcmVxdWVzdHMKcmVxdWVzdHMKCiMgR29vZ2xlIGludGVncmF0aW9uIChDYWxlbmRhciwgRHJp"
    "dmUsIERvY3MsIEdtYWlsKQpnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQKZ29vZ2xlLWF1dGgtb2F1dGhsaWIKZ29vZ2xlLWF1dGgK"
    "CiMg4pSA4pSAIE9wdGlvbmFsIChsb2NhbCBtb2RlbCBvbmx5KSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBVbmNvbW1lbnQgaWYgdXNpbmcgYSBsb2NhbCBIdWdnaW5nRmFjZSBtb2RlbDoK"
    "IyB0b3JjaAojIHRyYW5zZm9ybWVycwojIGFjY2VsZXJhdGUKCiMg4pSA4pSAIE9wdGlvbmFsIChOVklESUEgR1BVIG1vbml0b3Jp"
    "bmcpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFVuY29tbWVudCBpZiB5b3UgaGF2ZSBh"
    "biBOVklESUEgR1BVOgojIHB5bnZtbAoiIiIKICAgIHJlcV9wYXRoLndyaXRlX3RleHQoY29udGVudCwgZW5jb2Rpbmc9InV0Zi04"
    "IikKCgojIOKUgOKUgCBQQVNTIDQgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTWVtb3J5LCBTZXNzaW9u"
    "LCBMZXNzb25zTGVhcm5lZCwgVGFza01hbmFnZXIgYWxsIGRlZmluZWQuCiMgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGF1dG8tc2Vl"
    "ZGVkIG9uIGZpcnN0IHJ1bi4KIyByZXF1aXJlbWVudHMudHh0IHdyaXR0ZW4gb24gZmlyc3QgcnVuLgojCiMgTmV4dDogUGFzcyA1"
    "IOKAlCBUYWIgQ29udGVudCBDbGFzc2VzCiMgKFNMU2NhbnNUYWIsIFNMQ29tbWFuZHNUYWIsIEpvYlRyYWNrZXJUYWIsIFJlY29y"
    "ZHNUYWIsCiMgIFRhc2tzVGFiLCBTZWxmVGFiLCBEaWFnbm9zdGljc1RhYikKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERF"
    "Q0sg4oCUIFBBU1MgNTogVEFCIENPTlRFTlQgQ0xBU1NFUwojCiMgVGFicyBkZWZpbmVkIGhlcmU6CiMgICBTTFNjYW5zVGFiICAg"
    "ICAg4oCUIGdyaW1vaXJlLWNhcmQgc3R5bGUsIHJlYnVpbHQgKERlbGV0ZSBhZGRlZCwgTW9kaWZ5IGZpeGVkLAojICAgICAgICAg"
    "ICAgICAgICAgICAgcGFyc2VyIGZpeGVkLCBjb3B5LXRvLWNsaXBib2FyZCBwZXIgaXRlbSkKIyAgIFNMQ29tbWFuZHNUYWIgICDi"
    "gJQgZ290aGljIHRhYmxlLCBjb3B5IGNvbW1hbmQgdG8gY2xpcGJvYXJkCiMgICBKb2JUcmFja2VyVGFiICAg4oCUIGZ1bGwgcmVi"
    "dWlsZCBmcm9tIHNwZWMsIENTVi9UU1YgZXhwb3J0CiMgICBSZWNvcmRzVGFiICAgICAg4oCUIEdvb2dsZSBEcml2ZS9Eb2NzIHdv"
    "cmtzcGFjZQojICAgVGFza3NUYWIgICAgICAgIOKAlCB0YXNrIHJlZ2lzdHJ5ICsgbWluaSBjYWxlbmRhcgojICAgU2VsZlRhYiAg"
    "ICAgICAgIOKAlCBpZGxlIG5hcnJhdGl2ZSBvdXRwdXQgKyBQb0kgbGlzdAojICAgRGlhZ25vc3RpY3NUYWIgIOKAlCBsb2d1cnUg"
    "b3V0cHV0ICsgaGFyZHdhcmUgcmVwb3J0ICsgam91cm5hbCBsb2FkIG5vdGljZXMKIyAgIExlc3NvbnNUYWIgICAgICDigJQgTFNM"
    "IEZvcmJpZGRlbiBSdWxlc2V0ICsgY29kZSBsZXNzb25zIGJyb3dzZXIKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCmltcG9ydCByZSBhcyBfcmUK"
    "CgojIOKUgOKUgCBTSEFSRUQgR09USElDIFRBQkxFIFNUWUxFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgX2dvdGhpY190YWJsZV9zdHlsZSgpIC0+IHN0cjoKICAgIHJl"
    "dHVybiBmIiIiCiAgICAgICAgUVRhYmxlV2lkZ2V0IHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0JHMn07CiAgICAgICAg"
    "ICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgICAgICAgICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgICAg"
    "ICAgICBncmlkbGluZS1jb2xvcjoge0NfQk9SREVSfTsKICAgICAgICAgICAgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJp"
    "ZjsKICAgICAgICAgICAgZm9udC1zaXplOiAxMXB4OwogICAgICAgIH19CiAgICAgICAgUVRhYmxlV2lkZ2V0OjppdGVtOnNlbGVj"
    "dGVkIHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgICAgICAgICAgY29sb3I6IHtDX0dPTERf"
    "QlJJR0hUfTsKICAgICAgICB9fQogICAgICAgIFFUYWJsZVdpZGdldDo6aXRlbTphbHRlcm5hdGUge3sKICAgICAgICAgICAgYmFj"
    "a2dyb3VuZDoge0NfQkczfTsKICAgICAgICB9fQogICAgICAgIFFIZWFkZXJWaWV3OjpzZWN0aW9uIHt7CiAgICAgICAgICAgIGJh"
    "Y2tncm91bmQ6IHtDX0JHM307CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgICAgICAgICAgYm9yZGVyOiAxcHggc29s"
    "aWQge0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAgICBwYWRkaW5nOiA0cHggNnB4OwogICAgICAgICAgICBmb250LWZhbWlseTog"
    "e0RFQ0tfRk9OVH0sIHNlcmlmOwogICAgICAgICAgICBmb250LXNpemU6IDEwcHg7CiAgICAgICAgICAgIGZvbnQtd2VpZ2h0OiBi"
    "b2xkOwogICAgICAgICAgICBsZXR0ZXItc3BhY2luZzogMXB4OwogICAgICAgIH19CiAgICAiIiIKCmRlZiBfZ290aGljX2J0bih0"
    "ZXh0OiBzdHIsIHRvb2x0aXA6IHN0ciA9ICIiKSAtPiBRUHVzaEJ1dHRvbjoKICAgIGJ0biA9IFFQdXNoQnV0dG9uKHRleHQpCiAg"
    "ICBidG4uc2V0U3R5bGVTaGVldCgKICAgICAgICBmImJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsgY29sb3I6IHtDX0dPTER9"
    "OyAiCiAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAg"
    "ZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7ICIKICAgICAgICBmImZvbnQtd2VpZ2h0"
    "OiBib2xkOyBwYWRkaW5nOiA0cHggMTBweDsgbGV0dGVyLXNwYWNpbmc6IDFweDsiCiAgICApCiAgICBpZiB0b29sdGlwOgogICAg"
    "ICAgIGJ0bi5zZXRUb29sVGlwKHRvb2x0aXApCiAgICByZXR1cm4gYnRuCgpkZWYgX3NlY3Rpb25fbGJsKHRleHQ6IHN0cikgLT4g"
    "UUxhYmVsOgogICAgbGJsID0gUUxhYmVsKHRleHQpCiAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICBmImNvbG9yOiB7Q19H"
    "T0xEfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgZiJsZXR0ZXItc3BhY2luZzogMnB4OyBm"
    "b250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICkKICAgIHJldHVybiBsYmwKCgojIOKUgOKUgCBTTCBTQ0FOUyBU"
    "QUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNMU2NhbnNUYWIoUVdpZGdldCk6CiAgICAiIiIK"
    "ICAgIFNlY29uZCBMaWZlIGF2YXRhciBzY2FubmVyIHJlc3VsdHMgbWFuYWdlci4KICAgIFJlYnVpbHQgZnJvbSBzcGVjOgogICAg"
    "ICAtIENhcmQvZ3JpbW9pcmUtZW50cnkgc3R5bGUgZGlzcGxheQogICAgICAtIEFkZCAod2l0aCB0aW1lc3RhbXAtYXdhcmUgcGFy"
    "c2VyKQogICAgICAtIERpc3BsYXkgKGNsZWFuIGl0ZW0vY3JlYXRvciB0YWJsZSkKICAgICAgLSBNb2RpZnkgKGVkaXQgbmFtZSwg"
    "ZGVzY3JpcHRpb24sIGluZGl2aWR1YWwgaXRlbXMpCiAgICAgIC0gRGVsZXRlICh3YXMgbWlzc2luZyDigJQgbm93IHByZXNlbnQp"
    "CiAgICAgIC0gUmUtcGFyc2UgKHdhcyAnUmVmcmVzaCcg4oCUIHJlLXJ1bnMgcGFyc2VyIG9uIHN0b3JlZCByYXcgdGV4dCkKICAg"
    "ICAgLSBDb3B5LXRvLWNsaXBib2FyZCBvbiBhbnkgaXRlbQogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1lbW9yeV9k"
    "aXI6IFBhdGgsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRo"
    "ICAgID0gY2ZnX3BhdGgoInNsIikgLyAic2xfc2NhbnMuanNvbmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9"
    "IFtdCiAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQ6IE9wdGlvbmFsW3N0cl0gPSBOb25lCiAgICAgICAgc2VsZi5fc2V0dXBfdWko"
    "KQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBR"
    "VkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5z"
    "ZXRTcGFjaW5nKDQpCgogICAgICAgICMgQnV0dG9uIGJhcgogICAgICAgIGJhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxm"
    "Ll9idG5fYWRkICAgICA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIiwgICAgICJBZGQgYSBuZXcgc2NhbiIpCiAgICAgICAgc2VsZi5f"
    "YnRuX2Rpc3BsYXkgPSBfZ290aGljX2J0bigi4p2nIERpc3BsYXkiLCAiU2hvdyBzZWxlY3RlZCBzY2FuIGRldGFpbHMiKQogICAg"
    "ICAgIHNlbGYuX2J0bl9tb2RpZnkgID0gX2dvdGhpY19idG4oIuKcpyBNb2RpZnkiLCAgIkVkaXQgc2VsZWN0ZWQgc2NhbiIpCiAg"
    "ICAgICAgc2VsZi5fYnRuX2RlbGV0ZSAgPSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIsICAiRGVsZXRlIHNlbGVjdGVkIHNjYW4i"
    "KQogICAgICAgIHNlbGYuX2J0bl9yZXBhcnNlID0gX2dvdGhpY19idG4oIuKGuyBSZS1wYXJzZSIsIlJlLXBhcnNlIHJhdyB0ZXh0"
    "IG9mIHNlbGVjdGVkIHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Nob3dfYWRkKQog"
    "ICAgICAgIHNlbGYuX2J0bl9kaXNwbGF5LmNsaWNrZWQuY29ubmVjdChzZWxmLl9zaG93X2Rpc3BsYXkpCiAgICAgICAgc2VsZi5f"
    "YnRuX21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2hvd19tb2RpZnkpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlj"
    "a2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl9yZXBhcnNlLmNsaWNrZWQuY29ubmVjdChzZWxm"
    "Ll9kb19yZXBhcnNlKQogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fZGlzcGxheSwgc2VsZi5fYnRu"
    "X21vZGlmeSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSwgc2VsZi5fYnRuX3JlcGFyc2UpOgogICAgICAgICAg"
    "ICBiYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKCiAg"
    "ICAgICAgIyBTdGFjazogbGlzdCB2aWV3IHwgYWRkIGZvcm0gfCBkaXNwbGF5IHwgbW9kaWZ5CiAgICAgICAgc2VsZi5fc3RhY2sg"
    "PSBRU3RhY2tlZFdpZGdldCgpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fc3RhY2ssIDEpCgogICAgICAgICMg4pSA4pSA"
    "IFBBR0UgMDogc2NhbiBsaXN0IChncmltb2lyZSBjYXJkcykg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDAgPSBRV2lkZ2V0KCkKICAgICAgICBsMCA9IFFWQm94"
    "TGF5b3V0KHAwKQogICAgICAgIGwwLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlbGYuX2NhcmRfc2Ny"
    "b2xsID0gUVNjcm9sbEFyZWEoKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFdpZGdldFJlc2l6YWJsZShUcnVlKQogICAg"
    "ICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IG5vbmU7IikK"
    "ICAgICAgICBzZWxmLl9jYXJkX2NvbnRhaW5lciA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0ICAgID0gUVZC"
    "b3hMYXlvdXQoc2VsZi5fY2FyZF9jb250YWluZXIpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5z"
    "KDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAgIHNlbGYuX2NhcmRfbGF5"
    "b3V0LmFkZFN0cmV0Y2goKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFdpZGdldChzZWxmLl9jYXJkX2NvbnRhaW5lcikK"
    "ICAgICAgICBsMC5hZGRXaWRnZXQoc2VsZi5fY2FyZF9zY3JvbGwpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAwKQoK"
    "ICAgICAgICAjIOKUgOKUgCBQQUdFIDE6IGFkZCBmb3JtIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgIHAxID0gUVdpZGdldCgpCiAgICAgICAgbDEgPSBRVkJveExheW91dChwMSkKICAgICAgICBsMS5z"
    "ZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBsMS5zZXRTcGFjaW5nKDQpCiAgICAgICAgbDEuYWRkV2lkZ2V0"
    "KF9zZWN0aW9uX2xibCgi4p2nIFNDQU4gTkFNRSAoYXV0by1kZXRlY3RlZCkiKSkKICAgICAgICBzZWxmLl9hZGRfbmFtZSAgPSBR"
    "TGluZUVkaXQoKQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiQXV0by1kZXRlY3RlZCBmcm9tIHNj"
    "YW4gdGV4dCIpCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9uYW1lKQogICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlv"
    "bl9sYmwoIuKdpyBERVNDUklQVElPTiIpKQogICAgICAgIHNlbGYuX2FkZF9kZXNjICA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2Vs"
    "Zi5fYWRkX2Rlc2Muc2V0TWF4aW11bUhlaWdodCg2MCkKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX2Rlc2MpCiAgICAg"
    "ICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFJBVyBTQ0FOIFRFWFQgKHBhc3RlIGhlcmUpIikpCiAgICAgICAgc2Vs"
    "Zi5fYWRkX3JhdyAgID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9hZGRfcmF3LnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAg"
    "ICAgICAgIlBhc3RlIHRoZSByYXcgU2Vjb25kIExpZmUgc2NhbiBvdXRwdXQgaGVyZS5cbiIKICAgICAgICAgICAgIlRpbWVzdGFt"
    "cHMgbGlrZSBbMTE6NDddIHdpbGwgYmUgdXNlZCB0byBzcGxpdCBpdGVtcyBjb3JyZWN0bHkuIgogICAgICAgICkKICAgICAgICBs"
    "MS5hZGRXaWRnZXQoc2VsZi5fYWRkX3JhdywgMSkKICAgICAgICAjIFByZXZpZXcgb2YgcGFyc2VkIGl0ZW1zCiAgICAgICAgbDEu"
    "YWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFBBUlNFRCBJVEVNUyBQUkVWSUVXIikpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZp"
    "ZXcgPSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxz"
    "KFsiSXRlbSIsICJDcmVhdG9yIl0pCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rp"
    "b25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5f"
    "YWRkX3ByZXZpZXcuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVy"
    "Vmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0TWF4aW11bUhlaWdodCgxMjApCiAg"
    "ICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgbDEuYWRk"
    "V2lkZ2V0KHNlbGYuX2FkZF9wcmV2aWV3KQogICAgICAgIHNlbGYuX2FkZF9yYXcudGV4dENoYW5nZWQuY29ubmVjdChzZWxmLl9w"
    "cmV2aWV3X3BhcnNlKQoKICAgICAgICBidG5zMSA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzMSA9IF9nb3RoaWNfYnRuKCLinKYg"
    "U2F2ZSIpOyBjMSA9IF9nb3RoaWNfYnRuKCLinJcgQ2FuY2VsIikKICAgICAgICBzMS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9f"
    "YWRkKQogICAgICAgIGMxLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKSkKICAg"
    "ICAgICBidG5zMS5hZGRXaWRnZXQoczEpOyBidG5zMS5hZGRXaWRnZXQoYzEpOyBidG5zMS5hZGRTdHJldGNoKCkKICAgICAgICBs"
    "MS5hZGRMYXlvdXQoYnRuczEpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAxKQoKICAgICAgICAjIOKUgOKUgCBQQUdF"
    "IDI6IGRpc3BsYXkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAg"
    "cDIgPSBRV2lkZ2V0KCkKICAgICAgICBsMiA9IFFWQm94TGF5b3V0KHAyKQogICAgICAgIGwyLnNldENvbnRlbnRzTWFyZ2lucyg0"
    "LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2Rpc3BfbmFtZSAgPSBRTGFiZWwoKQogICAgICAgIHNlbGYuX2Rpc3BfbmFtZS5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0JSSUdIVH07IGZvbnQtc2l6ZTogMTNweDsgZm9udC13ZWln"
    "aHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAg"
    "ICAgc2VsZi5fZGlzcF9kZXNjICA9IFFMYWJlbCgpCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFdvcmRXcmFwKFRydWUpCiAg"
    "ICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9u"
    "dC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlz"
    "cF90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxh"
    "YmVscyhbIkl0ZW0iLCAiQ3JlYXRvciJdKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNl"
    "Y3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2Vs"
    "Zi5fZGlzcF90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFk"
    "ZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190"
    "YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0Q29udGV4dE1lbnVQb2xpY3koCiAgICAgICAgICAgIFF0"
    "LkNvbnRleHRNZW51UG9saWN5LkN1c3RvbUNvbnRleHRNZW51KQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuY3VzdG9tQ29udGV4"
    "dE1lbnVSZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5faXRlbV9jb250ZXh0X21lbnUpCgogICAgICAgIGwyLmFk"
    "ZFdpZGdldChzZWxmLl9kaXNwX25hbWUpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2Rpc3BfZGVzYykKICAgICAgICBsMi5h"
    "ZGRXaWRnZXQoc2VsZi5fZGlzcF90YWJsZSwgMSkKCiAgICAgICAgY29weV9oaW50ID0gUUxhYmVsKCJSaWdodC1jbGljayBhbnkg"
    "aXRlbSB0byBjb3B5IGl0IHRvIGNsaXBib2FyZC4iKQogICAgICAgIGNvcHlfaGludC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIK"
    "ICAgICAgICApCiAgICAgICAgbDIuYWRkV2lkZ2V0KGNvcHlfaGludCkKCiAgICAgICAgYmsyID0gX2dvdGhpY19idG4oIuKXgCBC"
    "YWNrIikKICAgICAgICBiazIuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDApKQog"
    "ICAgICAgIGwyLmFkZFdpZGdldChiazIpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAyKQoKICAgICAgICAjIOKUgOKU"
    "gCBQQUdFIDM6IG1vZGlmeSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICAgICBwMyA9IFFXaWRnZXQoKQogICAgICAgIGwzID0gUVZCb3hMYXlvdXQocDMpCiAgICAgICAgbDMuc2V0Q29udGVudHNN"
    "YXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgbDMuc2V0U3BhY2luZyg0KQogICAgICAgIGwzLmFkZFdpZGdldChfc2VjdGlvbl9s"
    "YmwoIuKdpyBOQU1FIikpCiAgICAgICAgc2VsZi5fbW9kX25hbWUgPSBRTGluZUVkaXQoKQogICAgICAgIGwzLmFkZFdpZGdldChz"
    "ZWxmLl9tb2RfbmFtZSkKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgREVTQ1JJUFRJT04iKSkKICAgICAg"
    "ICBzZWxmLl9tb2RfZGVzYyA9IFFMaW5lRWRpdCgpCiAgICAgICAgbDMuYWRkV2lkZ2V0KHNlbGYuX21vZF9kZXNjKQogICAgICAg"
    "IGwzLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBJVEVNUyAoZG91YmxlLWNsaWNrIHRvIGVkaXQpIikpCiAgICAgICAgc2Vs"
    "Zi5fbW9kX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDIpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldEhvcml6b250YWxIZWFk"
    "ZXJMYWJlbHMoWyJJdGVtIiwgIkNyZWF0b3IiXSkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNl"
    "dFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAg"
    "c2VsZi5fbW9kX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMSwgUUhl"
    "YWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNf"
    "dGFibGVfc3R5bGUoKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fbW9kX3RhYmxlLCAxKQoKICAgICAgICBidG5zMyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBzMyA9IF9nb3RoaWNfYnRuKCLinKYgU2F2ZSIpOyBjMyA9IF9nb3RoaWNfYnRuKCLinJcgQ2Fu"
    "Y2VsIikKICAgICAgICBzMy5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5X3NhdmUpCiAgICAgICAgYzMuY2xpY2tlZC5j"
    "b25uZWN0KGxhbWJkYTogc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDApKQogICAgICAgIGJ0bnMzLmFkZFdpZGdldChzMyk7"
    "IGJ0bnMzLmFkZFdpZGdldChjMyk7IGJ0bnMzLmFkZFN0cmV0Y2goKQogICAgICAgIGwzLmFkZExheW91dChidG5zMykKICAgICAg"
    "ICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDMpCgogICAgIyDilIDilIAgUEFSU0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgQHN0"
    "YXRpY21ldGhvZAogICAgZGVmIHBhcnNlX3NjYW5fdGV4dChyYXc6IHN0cikgLT4gdHVwbGVbc3RyLCBsaXN0W2RpY3RdXToKICAg"
    "ICAgICAiIiIKICAgICAgICBQYXJzZSByYXcgU0wgc2NhbiBvdXRwdXQgaW50byAoYXZhdGFyX25hbWUsIGl0ZW1zKS4KCiAgICAg"
    "ICAgS0VZIEZJWDogQmVmb3JlIHNwbGl0dGluZywgaW5zZXJ0IG5ld2xpbmVzIGJlZm9yZSBldmVyeSBbSEg6TU1dCiAgICAgICAg"
    "dGltZXN0YW1wIHNvIHNpbmdsZS1saW5lIHBhc3RlcyB3b3JrIGNvcnJlY3RseS4KCiAgICAgICAgRXhwZWN0ZWQgZm9ybWF0Ogog"
    "ICAgICAgICAgICBbMTE6NDddIEF2YXRhck5hbWUncyBwdWJsaWMgYXR0YWNobWVudHM6CiAgICAgICAgICAgIFsxMTo0N10gLjog"
    "SXRlbSBOYW1lIFtBdHRhY2htZW50XSBDUkVBVE9SOiBDcmVhdG9yTmFtZSBbMTE6NDddIC4uLgogICAgICAgICIiIgogICAgICAg"
    "IGlmIG5vdCByYXcuc3RyaXAoKToKICAgICAgICAgICAgcmV0dXJuICJVTktOT1dOIiwgW10KCiAgICAgICAgIyDilIDilIAgU3Rl"
    "cCAxOiBub3JtYWxpemUg4oCUIGluc2VydCBuZXdsaW5lcyBiZWZvcmUgdGltZXN0YW1wcyDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICBub3JtYWxpemVkID0gX3JlLnN1YihyJ1xzKihcW1xkezEsMn06XGR7Mn1cXSknLCByJ1xuXDEnLCByYXcpCiAgICAgICAg"
    "bGluZXMgPSBbbC5zdHJpcCgpIGZvciBsIGluIG5vcm1hbGl6ZWQuc3BsaXRsaW5lcygpIGlmIGwuc3RyaXAoKV0KCiAgICAgICAg"
    "IyDilIDilIAgU3RlcCAyOiBleHRyYWN0IGF2YXRhciBuYW1lIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGF2YXRhcl9u"
    "YW1lID0gIlVOS05PV04iCiAgICAgICAgZm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAgICAgICMgIkF2YXRhck5hbWUncyBwdWJs"
    "aWMgYXR0YWNobWVudHMiIG9yIHNpbWlsYXIKICAgICAgICAgICAgbSA9IF9yZS5zZWFyY2goCiAgICAgICAgICAgICAgICByIihc"
    "d1tcd1xzXSs/KSdzXHMrcHVibGljXHMrYXR0YWNobWVudHMiLAogICAgICAgICAgICAgICAgbGluZSwgX3JlLkkKICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICBpZiBtOgogICAgICAgICAgICAgICAgYXZhdGFyX25hbWUgPSBtLmdyb3VwKDEpLnN0cmlwKCkKICAg"
    "ICAgICAgICAgICAgIGJyZWFrCgogICAgICAgICMg4pSA4pSAIFN0ZXAgMzogZXh0cmFjdCBpdGVtcyDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBpdGVtcyA9IFtdCiAgICAgICAgZm9yIGxpbmUgaW4gbGluZXM6CiAgICAg"
    "ICAgICAgICMgU3RyaXAgbGVhZGluZyB0aW1lc3RhbXAKICAgICAgICAgICAgY29udGVudCA9IF9yZS5zdWIocideXFtcZHsxLDJ9"
    "OlxkezJ9XF1ccyonLCAnJywgbGluZSkuc3RyaXAoKQogICAgICAgICAgICBpZiBub3QgY29udGVudDoKICAgICAgICAgICAgICAg"
    "IGNvbnRpbnVlCiAgICAgICAgICAgICMgU2tpcCBoZWFkZXIgbGluZXMKICAgICAgICAgICAgaWYgIidzIHB1YmxpYyBhdHRhY2ht"
    "ZW50cyIgaW4gY29udGVudC5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgY29udGVudC5s"
    "b3dlcigpLnN0YXJ0c3dpdGgoIm9iamVjdCIpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgIyBTa2lwIGRp"
    "dmlkZXIgbGluZXMg4oCUIGxpbmVzIHRoYXQgYXJlIG1vc3RseSBvbmUgcmVwZWF0ZWQgY2hhcmFjdGVyCiAgICAgICAgICAgICMg"
    "ZS5nLiDiloLiloLiloLiloLiloLiloLiloLiloLiloLiloLiloLiloIgb3Ig4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQIG9yIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBzdHJpcHBlZCA9IGNvbnRl"
    "bnQuc3RyaXAoIi46ICIpCiAgICAgICAgICAgIGlmIHN0cmlwcGVkIGFuZCBsZW4oc2V0KHN0cmlwcGVkKSkgPD0gMjoKICAgICAg"
    "ICAgICAgICAgIGNvbnRpbnVlICAjIG9uZSBvciB0d28gdW5pcXVlIGNoYXJzID0gZGl2aWRlciBsaW5lCgogICAgICAgICAgICAj"
    "IFRyeSB0byBleHRyYWN0IENSRUFUT1I6IGZpZWxkCiAgICAgICAgICAgIGNyZWF0b3IgPSAiVU5LTk9XTiIKICAgICAgICAgICAg"
    "aXRlbV9uYW1lID0gY29udGVudAoKICAgICAgICAgICAgY3JlYXRvcl9tYXRjaCA9IF9yZS5zZWFyY2goCiAgICAgICAgICAgICAg"
    "ICByJ0NSRUFUT1I6XHMqKFtcd1xzXSs/KSg/OlxzKlxbfCQpJywgY29udGVudCwgX3JlLkkKICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICBpZiBjcmVhdG9yX21hdGNoOgogICAgICAgICAgICAgICAgY3JlYXRvciAgID0gY3JlYXRvcl9tYXRjaC5ncm91cCgxKS5z"
    "dHJpcCgpCiAgICAgICAgICAgICAgICBpdGVtX25hbWUgPSBjb250ZW50WzpjcmVhdG9yX21hdGNoLnN0YXJ0KCldLnN0cmlwKCkK"
    "CiAgICAgICAgICAgICMgU3RyaXAgYXR0YWNobWVudCBwb2ludCBzdWZmaXhlcyBsaWtlIFtMZWZ0X0Zvb3RdCiAgICAgICAgICAg"
    "IGl0ZW1fbmFtZSA9IF9yZS5zdWIocidccypcW1tcd1xzX10rXF0nLCAnJywgaXRlbV9uYW1lKS5zdHJpcCgpCiAgICAgICAgICAg"
    "IGl0ZW1fbmFtZSA9IGl0ZW1fbmFtZS5zdHJpcCgiLjogIikKCiAgICAgICAgICAgIGlmIGl0ZW1fbmFtZSBhbmQgbGVuKGl0ZW1f"
    "bmFtZSkgPiAxOgogICAgICAgICAgICAgICAgaXRlbXMuYXBwZW5kKHsiaXRlbSI6IGl0ZW1fbmFtZSwgImNyZWF0b3IiOiBjcmVh"
    "dG9yfSkKCiAgICAgICAgcmV0dXJuIGF2YXRhcl9uYW1lLCBpdGVtcwoKICAgICMg4pSA4pSAIENBUkQgUkVOREVSSU5HIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9i"
    "dWlsZF9jYXJkcyhzZWxmKSAtPiBOb25lOgogICAgICAgICMgQ2xlYXIgZXhpc3RpbmcgY2FyZHMgKGtlZXAgc3RyZXRjaCkKICAg"
    "ICAgICB3aGlsZSBzZWxmLl9jYXJkX2xheW91dC5jb3VudCgpID4gMToKICAgICAgICAgICAgaXRlbSA9IHNlbGYuX2NhcmRfbGF5"
    "b3V0LnRha2VBdCgwKQogICAgICAgICAgICBpZiBpdGVtLndpZGdldCgpOgogICAgICAgICAgICAgICAgaXRlbS53aWRnZXQoKS5k"
    "ZWxldGVMYXRlcigpCgogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgY2FyZCA9IHNlbGYuX21h"
    "a2VfY2FyZChyZWMpCiAgICAgICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0Lmluc2VydFdpZGdldCgKICAgICAgICAgICAgICAgIHNl"
    "bGYuX2NhcmRfbGF5b3V0LmNvdW50KCkgLSAxLCBjYXJkCiAgICAgICAgICAgICkKCiAgICBkZWYgX21ha2VfY2FyZChzZWxmLCBy"
    "ZWM6IGRpY3QpIC0+IFFXaWRnZXQ6CiAgICAgICAgY2FyZCA9IFFGcmFtZSgpCiAgICAgICAgaXNfc2VsZWN0ZWQgPSByZWMuZ2V0"
    "KCJyZWNvcmRfaWQiKSA9PSBzZWxmLl9zZWxlY3RlZF9pZAogICAgICAgIGNhcmQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJiYWNrZ3JvdW5kOiB7JyMxYTBhMTAnIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19CRzN9OyAiCiAgICAgICAgICAgIGYiYm9yZGVy"
    "OiAxcHggc29saWQge0NfQ1JJTVNPTiBpZiBpc19zZWxlY3RlZCBlbHNlIENfQk9SREVSfTsgIgogICAgICAgICAgICBmImJvcmRl"
    "ci1yYWRpdXM6IDJweDsgcGFkZGluZzogMnB4OyIKICAgICAgICApCiAgICAgICAgbGF5b3V0ID0gUUhCb3hMYXlvdXQoY2FyZCkK"
    "ICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDgsIDYsIDgsIDYpCgogICAgICAgIG5hbWVfbGJsID0gUUxhYmVsKHJl"
    "Yy5nZXQoIm5hbWUiLCAiVU5LTk9XTiIpKQogICAgICAgIG5hbWVfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29s"
    "b3I6IHtDX0dPTERfQlJJR0hUIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19HT0xEfTsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTog"
    "MTFweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAg"
    "ICAgY291bnQgPSBsZW4ocmVjLmdldCgiaXRlbXMiLCBbXSkpCiAgICAgICAgY291bnRfbGJsID0gUUxhYmVsKGYie2NvdW50fSBp"
    "dGVtcyIpCiAgICAgICAgY291bnRfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBm"
    "b250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgZGF0ZV9s"
    "YmwgPSBRTGFiZWwocmVjLmdldCgiY3JlYXRlZF9hdCIsICIiKVs6MTBdKQogICAgICAgIGRhdGVfbGJsLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05U"
    "fSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChuYW1lX2xibCkKICAgICAgICBsYXlvdXQuYWRk"
    "U3RyZXRjaCgpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChjb3VudF9sYmwpCiAgICAgICAgbGF5b3V0LmFkZFNwYWNpbmcoMTIp"
    "CiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChkYXRlX2xibCkKCiAgICAgICAgIyBDbGljayB0byBzZWxlY3QKICAgICAgICByZWNf"
    "aWQgPSByZWMuZ2V0KCJyZWNvcmRfaWQiLCAiIikKICAgICAgICBjYXJkLm1vdXNlUHJlc3NFdmVudCA9IGxhbWJkYSBlLCByaWQ9"
    "cmVjX2lkOiBzZWxmLl9zZWxlY3RfY2FyZChyaWQpCiAgICAgICAgcmV0dXJuIGNhcmQKCiAgICBkZWYgX3NlbGVjdF9jYXJkKHNl"
    "bGYsIHJlY29yZF9pZDogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkID0gcmVjb3JkX2lkCiAgICAgICAg"
    "c2VsZi5fYnVpbGRfY2FyZHMoKSAgIyBSZWJ1aWxkIHRvIHNob3cgc2VsZWN0aW9uIGhpZ2hsaWdodAoKICAgIGRlZiBfc2VsZWN0"
    "ZWRfcmVjb3JkKHNlbGYpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHJldHVybiBuZXh0KAogICAgICAgICAgICAociBmb3Ig"
    "ciBpbiBzZWxmLl9yZWNvcmRzCiAgICAgICAgICAgICBpZiByLmdldCgicmVjb3JkX2lkIikgPT0gc2VsZi5fc2VsZWN0ZWRfaWQp"
    "LAogICAgICAgICAgICBOb25lCiAgICAgICAgKQoKICAgICMg4pSA4pSAIEFDVElPTlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYg"
    "cmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAg"
    "ICAgIyBFbnN1cmUgcmVjb3JkX2lkIGZpZWxkIGV4aXN0cwogICAgICAgIGNoYW5nZWQgPSBGYWxzZQogICAgICAgIGZvciByIGlu"
    "IHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGlmIG5vdCByLmdldCgicmVjb3JkX2lkIik6CiAgICAgICAgICAgICAgICByWyJy"
    "ZWNvcmRfaWQiXSA9IHIuZ2V0KCJpZCIpIG9yIHN0cih1dWlkLnV1aWQ0KCkpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1"
    "ZQogICAgICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAg"
    "ICAgICAgc2VsZi5fYnVpbGRfY2FyZHMoKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKQoKICAgIGRlZiBf"
    "cHJldmlld19wYXJzZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJhdyA9IHNlbGYuX2FkZF9yYXcudG9QbGFpblRleHQoKQogICAg"
    "ICAgIG5hbWUsIGl0ZW1zID0gc2VsZi5wYXJzZV9zY2FuX3RleHQocmF3KQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNl"
    "aG9sZGVyVGV4dChuYW1lKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGl0IGlu"
    "IGl0ZW1zWzoyMF06ICAjIHByZXZpZXcgZmlyc3QgMjAKICAgICAgICAgICAgciA9IHNlbGYuX2FkZF9wcmV2aWV3LnJvd0NvdW50"
    "KCkKICAgICAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3"
    "LnNldEl0ZW0ociwgMCwgUVRhYmxlV2lkZ2V0SXRlbShpdFsiaXRlbSJdKSkKICAgICAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcu"
    "c2V0SXRlbShyLCAxLCBRVGFibGVXaWRnZXRJdGVtKGl0WyJjcmVhdG9yIl0pKQoKICAgIGRlZiBfc2hvd19hZGQoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLl9hZGRfbmFtZS5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX25hbWUuc2V0UGxhY2Vob2xkZXJU"
    "ZXh0KCJBdXRvLWRldGVjdGVkIGZyb20gc2NhbiB0ZXh0IikKICAgICAgICBzZWxmLl9hZGRfZGVzYy5jbGVhcigpCiAgICAgICAg"
    "c2VsZi5fYWRkX3Jhdy5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0Um93Q291bnQoMCkKICAgICAgICBzZWxm"
    "Ll9zdGFjay5zZXRDdXJyZW50SW5kZXgoMSkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIHJhdyAgPSBz"
    "ZWxmLl9hZGRfcmF3LnRvUGxhaW5UZXh0KCkKICAgICAgICBuYW1lLCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykK"
    "ICAgICAgICBvdmVycmlkZV9uYW1lID0gc2VsZi5fYWRkX25hbWUudGV4dCgpLnN0cmlwKCkKICAgICAgICBub3cgID0gZGF0ZXRp"
    "bWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAg"
    "ICAgIHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAicmVjb3JkX2lkIjogICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAg"
    "ICAgICAgIm5hbWUiOiAgICAgICAgb3ZlcnJpZGVfbmFtZSBvciBuYW1lLAogICAgICAgICAgICAiZGVzY3JpcHRpb24iOiBzZWxm"
    "Ll9hZGRfZGVzYy50b1BsYWluVGV4dCgpWzoyNDRdLAogICAgICAgICAgICAiaXRlbXMiOiAgICAgICBpdGVtcywKICAgICAgICAg"
    "ICAgInJhd190ZXh0IjogICAgcmF3LAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICBub3csCiAgICAgICAgICAgICJ1cGRhdGVk"
    "X2F0IjogIG5vdywKICAgICAgICB9CiAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQocmVjb3JkKQogICAgICAgIHdyaXRlX2pz"
    "b25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQgPSByZWNvcmRbInJlY29yZF9p"
    "ZCJdCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3Nob3dfZGlzcGxheShzZWxmKSAtPiBOb25lOgogICAgICAgIHJl"
    "YyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5m"
    "b3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNj"
    "YW4gdG8gZGlzcGxheS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9kaXNwX25hbWUuc2V0VGV4dChmIuKdpyB7"
    "cmVjLmdldCgnbmFtZScsJycpfSIpCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFRleHQocmVjLmdldCgiZGVzY3JpcHRpb24i"
    "LCIiKSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGl0IGluIHJlYy5nZXQoIml0"
    "ZW1zIixbXSk6CiAgICAgICAgICAgIHIgPSBzZWxmLl9kaXNwX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fZGlz"
    "cF90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAg"
    "ICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiaXRlbSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRJ"
    "dGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiY3JlYXRvciIsIlVOS05PV04iKSkpCiAg"
    "ICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDIpCgogICAgZGVmIF9pdGVtX2NvbnRleHRfbWVudShzZWxmLCBwb3Mp"
    "IC0+IE5vbmU6CiAgICAgICAgaWR4ID0gc2VsZi5fZGlzcF90YWJsZS5pbmRleEF0KHBvcykKICAgICAgICBpZiBub3QgaWR4Lmlz"
    "VmFsaWQoKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaXRlbV90ZXh0ICA9IChzZWxmLl9kaXNwX3RhYmxlLml0ZW0oaWR4"
    "LnJvdygpLCAwKSBvcgogICAgICAgICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAgIGNy"
    "ZWF0b3IgICAgPSAoc2VsZi5fZGlzcF90YWJsZS5pdGVtKGlkeC5yb3coKSwgMSkgb3IKICAgICAgICAgICAgICAgICAgICAgIFFU"
    "YWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICBmcm9tIFB5U2lkZTYuUXRXaWRnZXRzIGltcG9ydCBRTWVudQogICAg"
    "ICAgIG1lbnUgPSBRTWVudShzZWxmKQogICAgICAgIG1lbnUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5k"
    "OiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJ"
    "TX07IgogICAgICAgICkKICAgICAgICBhX2l0ZW0gICAgPSBtZW51LmFkZEFjdGlvbigiQ29weSBJdGVtIE5hbWUiKQogICAgICAg"
    "IGFfY3JlYXRvciA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5IENyZWF0b3IiKQogICAgICAgIGFfYm90aCAgICA9IG1lbnUuYWRkQWN0"
    "aW9uKCJDb3B5IEJvdGgiKQogICAgICAgIGFjdGlvbiA9IG1lbnUuZXhlYyhzZWxmLl9kaXNwX3RhYmxlLnZpZXdwb3J0KCkubWFw"
    "VG9HbG9iYWwocG9zKSkKICAgICAgICBjYiA9IFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKQogICAgICAgIGlmIGFjdGlvbiA9PSBh"
    "X2l0ZW06ICAgIGNiLnNldFRleHQoaXRlbV90ZXh0KQogICAgICAgIGVsaWYgYWN0aW9uID09IGFfY3JlYXRvcjogY2Iuc2V0VGV4"
    "dChjcmVhdG9yKQogICAgICAgIGVsaWYgYWN0aW9uID09IGFfYm90aDogIGNiLnNldFRleHQoZiJ7aXRlbV90ZXh0fSDigJQge2Ny"
    "ZWF0b3J9IikKCiAgICBkZWYgX3Nob3dfbW9kaWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRf"
    "cmVjb3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiU0wg"
    "U2NhbnMiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiU2VsZWN0IGEgc2NhbiB0byBtb2RpZnkuIikKICAg"
    "ICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fbW9kX25hbWUuc2V0VGV4dChyZWMuZ2V0KCJuYW1lIiwiIikpCiAgICAgICAg"
    "c2VsZi5fbW9kX2Rlc2Muc2V0VGV4dChyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5z"
    "ZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiByZWMuZ2V0KCJpdGVtcyIsW10pOgogICAgICAgICAgICByID0gc2VsZi5f"
    "bW9kX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBz"
    "ZWxmLl9tb2RfdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoIml0ZW0i"
    "LCIiKSkpCiAgICAgICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRn"
    "ZXRJdGVtKGl0LmdldCgiY3JlYXRvciIsIlVOS05PV04iKSkpCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDMp"
    "CgogICAgZGVmIF9kb19tb2RpZnlfc2F2ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29y"
    "ZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjWyJuYW1lIl0gICAgICAgID0gc2Vs"
    "Zi5fbW9kX25hbWUudGV4dCgpLnN0cmlwKCkgb3IgIlVOS05PV04iCiAgICAgICAgcmVjWyJkZXNjcmlwdGlvbiJdID0gc2VsZi5f"
    "bW9kX2Rlc2MudGV4dCgpWzoyNDRdCiAgICAgICAgaXRlbXMgPSBbXQogICAgICAgIGZvciBpIGluIHJhbmdlKHNlbGYuX21vZF90"
    "YWJsZS5yb3dDb3VudCgpKToKICAgICAgICAgICAgaXQgID0gKHNlbGYuX21vZF90YWJsZS5pdGVtKGksMCkgb3IgUVRhYmxlV2lk"
    "Z2V0SXRlbSgiIikpLnRleHQoKQogICAgICAgICAgICBjciAgPSAoc2VsZi5fbW9kX3RhYmxlLml0ZW0oaSwxKSBvciBRVGFibGVX"
    "aWRnZXRJdGVtKCIiKSkudGV4dCgpCiAgICAgICAgICAgIGl0ZW1zLmFwcGVuZCh7Iml0ZW0iOiBpdC5zdHJpcCgpIG9yICJVTktO"
    "T1dOIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAiY3JlYXRvciI6IGNyLnN0cmlwKCkgb3IgIlVOS05PV04ifSkKICAgICAg"
    "ICByZWNbIml0ZW1zIl0gICAgICA9IGl0ZW1zCiAgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpv"
    "bmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAg"
    "c2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVj"
    "dGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwg"
    "IlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gZGVsZXRlLiIp"
    "CiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5hbWUgPSByZWMuZ2V0KCJuYW1lIiwidGhpcyBzY2FuIikKICAgICAgICByZXBs"
    "eSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVsZXRlIFNjYW4iLAogICAgICAgICAgICBmIkRl"
    "bGV0ZSAne25hbWV9Jz8gVGhpcyBjYW5ub3QgYmUgdW5kb25lLiIsCiAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0"
    "dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgKQogICAgICAgIGlmIHJlcGx5ID09IFFNZXNz"
    "YWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAgc2VsZi5fcmVjb3JkcyA9IFtyIGZvciByIGluIHNlbGYuX3Jl"
    "Y29yZHMKICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiByLmdldCgicmVjb3JkX2lkIikgIT0gc2VsZi5fc2VsZWN0ZWRf"
    "aWRdCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYuX3Nl"
    "bGVjdGVkX2lkID0gTm9uZQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fcmVwYXJzZShzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAg"
    "UU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIlNlbGVjdCBhIHNjYW4gdG8gcmUtcGFyc2UuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmF3ID0gcmVjLmdldCgi"
    "cmF3X3RleHQiLCIiKQogICAgICAgIGlmIG5vdCByYXc6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYs"
    "ICJSZS1wYXJzZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJObyByYXcgdGV4dCBzdG9yZWQgZm9yIHRo"
    "aXMgc2Nhbi4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBuYW1lLCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJh"
    "dykKICAgICAgICByZWNbIml0ZW1zIl0gICAgICA9IGl0ZW1zCiAgICAgICAgcmVjWyJuYW1lIl0gICAgICAgPSByZWNbIm5hbWUi"
    "XSBvciBuYW1lCiAgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQo"
    "KQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKICAg"
    "ICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiUmUtcGFyc2VkIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICBmIkZvdW5kIHtsZW4oaXRlbXMpfSBpdGVtcy4iKQoKCiMg4pSA4pSAIFNMIENPTU1BTkRTIFRBQiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKY2xhc3MgU0xDb21tYW5kc1RhYihRV2lkZ2V0KToKICAgICIiIgogICAgU2Vjb25kIExpZmUgY29tbWFu"
    "ZCByZWZlcmVuY2UgdGFibGUuCiAgICBHb3RoaWMgdGFibGUgc3R5bGluZy4gQ29weSBjb21tYW5kIHRvIGNsaXBib2FyZCBidXR0"
    "b24gcGVyIHJvdy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5f"
    "X2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAgICA9IGNmZ19wYXRoKCJzbCIpIC8gInNsX2NvbW1hbmRzLmpzb25s"
    "IgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBz"
    "ZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQo"
    "c2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0"
    "KQoKICAgICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCLinKYg"
    "QWRkIikKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5ID0gX2dvdGhpY19idG4oIuKcpyBNb2RpZnkiKQogICAgICAgIHNlbGYuX2J0"
    "bl9kZWxldGUgPSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX2NvcHkgICA9IF9nb3RoaWNfYnRu"
    "KCLip4kgQ29weSBDb21tYW5kIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJDb3B5IHNlbGVjdGVk"
    "IGNvbW1hbmQgdG8gY2xpcGJvYXJkIikKICAgICAgICBzZWxmLl9idG5fcmVmcmVzaD0gX2dvdGhpY19idG4oIuKGuyBSZWZyZXNo"
    "IikKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX21v"
    "ZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xpY2tlZC5jb25u"
    "ZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fY29weS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fY29weV9jb21t"
    "YW5kKQogICAgICAgIHNlbGYuX2J0bl9yZWZyZXNoLmNsaWNrZWQuY29ubmVjdChzZWxmLnJlZnJlc2gpCiAgICAgICAgZm9yIGIg"
    "aW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9tb2RpZnksIHNlbGYuX2J0bl9kZWxldGUsCiAgICAgICAgICAgICAgICAgIHNl"
    "bGYuX2J0bl9jb3B5LCBzZWxmLl9idG5fcmVmcmVzaCk6CiAgICAgICAgICAgIGJhci5hZGRXaWRnZXQoYikKICAgICAgICBiYXIu"
    "YWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYmFyKQoKICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdl"
    "dCgwLCAyKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJDb21tYW5kIiwgIkRlc2NyaXB0"
    "aW9uIl0pCiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAg"
    "ICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRl"
    "cigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAg"
    "ICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVj"
    "dGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkK"
    "ICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICByb290LmFkZFdp"
    "ZGdldChzZWxmLl90YWJsZSwgMSkKCiAgICAgICAgaGludCA9IFFMYWJlbCgKICAgICAgICAgICAgIlNlbGVjdCBhIHJvdyBhbmQg"
    "Y2xpY2sg4qeJIENvcHkgQ29tbWFuZCB0byBjb3B5IGp1c3QgdGhlIGNvbW1hbmQgdGV4dC4iCiAgICAgICAgKQogICAgICAgIGhp"
    "bnQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgZm9udC1m"
    "YW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KGhpbnQpCgogICAgZGVm"
    "IHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAg"
    "ICAgIHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAg"
    "ICByID0gc2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAg"
    "ICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJjb21t"
    "YW5kIiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRn"
    "ZXRJdGVtKHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpKQoKICAgIGRlZiBfY29weV9jb21tYW5kKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgcm93IDwgMDoKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgaXRlbSA9IHNlbGYuX3RhYmxlLml0ZW0ocm93LCAwKQogICAgICAgIGlmIGl0ZW06CiAgICAgICAgICAgIFFBcHBs"
    "aWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KGl0ZW0udGV4dCgpKQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiQWRkIENvbW1hbmQiKQogICAgICAg"
    "IGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZm9ybSA9"
    "IFFGb3JtTGF5b3V0KGRsZykKICAgICAgICBjbWQgID0gUUxpbmVFZGl0KCk7IGRlc2MgPSBRTGluZUVkaXQoKQogICAgICAgIGZv"
    "cm0uYWRkUm93KCJDb21tYW5kOiIsIGNtZCkKICAgICAgICBmb3JtLmFkZFJvdygiRGVzY3JpcHRpb246IiwgZGVzYykKICAgICAg"
    "ICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0bigi"
    "Q2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcucmVq"
    "ZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRu"
    "cykKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgbm93ID0g"
    "ZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAgcmVjID0gewogICAgICAgICAgICAgICAg"
    "ImlkIjogICAgICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICAgICAiY29tbWFuZCI6ICAgICBjbWQudGV4dCgp"
    "LnN0cmlwKClbOjI0NF0sCiAgICAgICAgICAgICAgICAiZGVzY3JpcHRpb24iOiBkZXNjLnRleHQoKS5zdHJpcCgpWzoyNDRdLAog"
    "ICAgICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgbm93LCAidXBkYXRlZF9hdCI6IG5vdywKICAgICAgICAgICAgfQogICAgICAg"
    "ICAgICBpZiByZWNbImNvbW1hbmQiXToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHJlYykKICAgICAgICAg"
    "ICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgICAgICBzZWxmLnJlZnJlc2go"
    "KQoKICAgIGRlZiBfZG9fbW9kaWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygp"
    "CiAgICAgICAgaWYgcm93IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZXR1cm4KICAgICAg"
    "ICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRv"
    "d1RpdGxlKCJNb2RpZnkgQ29tbWFuZCIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBj"
    "b2xvcjoge0NfR09MRH07IikKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAgIGNtZCAgPSBRTGluZUVkaXQo"
    "cmVjLmdldCgiY29tbWFuZCIsIiIpKQogICAgICAgIGRlc2MgPSBRTGluZUVkaXQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkK"
    "ICAgICAgICBmb3JtLmFkZFJvdygiQ29tbWFuZDoiLCBjbWQpCiAgICAgICAgZm9ybS5hZGRSb3coIkRlc2NyaXB0aW9uOiIsIGRl"
    "c2MpCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dv"
    "dGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5l"
    "Y3QoZGxnLnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0u"
    "YWRkUm93KGJ0bnMpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAg"
    "ICAgIHJlY1siY29tbWFuZCJdICAgICA9IGNtZC50ZXh0KCkuc3RyaXAoKVs6MjQ0XQogICAgICAgICAgICByZWNbImRlc2NyaXB0"
    "aW9uIl0gPSBkZXNjLnRleHQoKS5zdHJpcCgpWzoyNDRdCiAgICAgICAgICAgIHJlY1sidXBkYXRlZF9hdCJdICA9IGRhdGV0aW1l"
    "Lm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3Jl"
    "Y29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiByb3cgPCAwIG9yIHJvdyA+PSBsZW4oc2VsZi5fcmVj"
    "b3Jkcyk6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGNtZCA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQoImNvbW1hbmQiLCJ0"
    "aGlzIGNvbW1hbmQiKQogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgIHNlbGYsICJEZWxl"
    "dGUiLCBmIkRlbGV0ZSAne2NtZH0nPyIsCiAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNz"
    "YWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgKQogICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJk"
    "QnV0dG9uLlllczoKICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5wb3Aocm93KQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxm"
    "Ll9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKCiMg4pSA4pSAIEpPQiBUUkFDS0VSIFRB"
    "QiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSm9iVHJhY2tlclRhYihRV2lkZ2V0KToKICAgICIiIgogICAgSm9i"
    "IGFwcGxpY2F0aW9uIHRyYWNraW5nLiBGdWxsIHJlYnVpbGQgZnJvbSBzcGVjLgogICAgRmllbGRzOiBDb21wYW55LCBKb2IgVGl0"
    "bGUsIERhdGUgQXBwbGllZCwgTGluaywgU3RhdHVzLCBOb3Rlcy4KICAgIE11bHRpLXNlbGVjdCBoaWRlL3VuaGlkZS9kZWxldGUu"
    "IENTViBhbmQgVFNWIGV4cG9ydC4KICAgIEhpZGRlbiByb3dzID0gY29tcGxldGVkL3JlamVjdGVkIOKAlCBzdGlsbCBzdG9yZWQs"
    "IGp1c3Qgbm90IHNob3duLgogICAgIiIiCgogICAgQ09MVU1OUyA9IFsiQ29tcGFueSIsICJKb2IgVGl0bGUiLCAiRGF0ZSBBcHBs"
    "aWVkIiwKICAgICAgICAgICAgICAgIkxpbmsiLCAiU3RhdHVzIiwgIk5vdGVzIl0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFy"
    "ZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BhdGggICAgPSBjZmdfcGF0"
    "aCgibWVtb3JpZXMiKSAvICJqb2JfdHJhY2tlci5qc29ubCIKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10K"
    "ICAgICAgICBzZWxmLl9zaG93X2hpZGRlbiA9IEZhbHNlCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVm"
    "cmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQog"
    "ICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAg"
    "ICAgIGJhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgID0gX2dvdGhpY19idG4oIkFkZCIpCiAgICAg"
    "ICAgc2VsZi5fYnRuX21vZGlmeSA9IF9nb3RoaWNfYnRuKCJNb2RpZnkiKQogICAgICAgIHNlbGYuX2J0bl9oaWRlICAgPSBfZ290"
    "aGljX2J0bigiQXJjaGl2ZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiTWFyayBzZWxlY3RlZCBh"
    "cyBjb21wbGV0ZWQvcmVqZWN0ZWQiKQogICAgICAgIHNlbGYuX2J0bl91bmhpZGUgPSBfZ290aGljX2J0bigiUmVzdG9yZSIsCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiUmVzdG9yZSBhcmNoaXZlZCBhcHBsaWNhdGlvbnMiKQogICAg"
    "ICAgIHNlbGYuX2J0bl9kZWxldGUgPSBfZ290aGljX2J0bigiRGVsZXRlIikKICAgICAgICBzZWxmLl9idG5fdG9nZ2xlID0gX2dv"
    "dGhpY19idG4oIlNob3cgQXJjaGl2ZWQiKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQgPSBfZ290aGljX2J0bigiRXhwb3J0IikK"
    "CiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9tb2RpZnksIHNlbGYuX2J0bl9oaWRlLAogICAgICAg"
    "ICAgICAgICAgICBzZWxmLl9idG5fdW5oaWRlLCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5f"
    "dG9nZ2xlLCBzZWxmLl9idG5fZXhwb3J0KToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtV2lkdGgoNzApCiAgICAgICAgICAgIGIu"
    "c2V0TWluaW11bUhlaWdodCgyNikKICAgICAgICAgICAgYmFyLmFkZFdpZGdldChiKQoKICAgICAgICBzZWxmLl9idG5fYWRkLmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "ZG9fbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9oaWRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19oaWRlKQogICAgICAgIHNl"
    "bGYuX2J0bl91bmhpZGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX3VuaGlkZSkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZS5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fdG9nZ2xlX2hpZGRlbikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19leHBvcnQp"
    "CiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAgICAgc2VsZi5fdGFibGUg"
    "PSBRVGFibGVXaWRnZXQoMCwgbGVuKHNlbGYuQ09MVU1OUykpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRl"
    "ckxhYmVscyhzZWxmLkNPTFVNTlMpCiAgICAgICAgaGggPSBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkKICAgICAgICAj"
    "IENvbXBhbnkgYW5kIEpvYiBUaXRsZSBzdHJldGNoCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMCwgUUhlYWRlclZp"
    "ZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDEsIFFIZWFkZXJWaWV3LlJlc2l6"
    "ZU1vZGUuU3RyZXRjaCkKICAgICAgICAjIERhdGUgQXBwbGllZCDigJQgZml4ZWQgcmVhZGFibGUgd2lkdGgKICAgICAgICBoaC5z"
    "ZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNl"
    "dENvbHVtbldpZHRoKDIsIDEwMCkKICAgICAgICAjIExpbmsgc3RyZXRjaGVzCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1v"
    "ZGUoMywgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgICMgU3RhdHVzIOKAlCBmaXhlZCB3aWR0aAogICAg"
    "ICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDQsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2VsZi5f"
    "dGFibGUuc2V0Q29sdW1uV2lkdGgoNCwgODApCiAgICAgICAgIyBOb3RlcyBzdHJldGNoZXMKICAgICAgICBoaC5zZXRTZWN0aW9u"
    "UmVzaXplTW9kZSg1LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCgogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVj"
    "dGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQog"
    "ICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbk1vZGUoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlv"
    "bk1vZGUuRXh0ZW5kZWRTZWxlY3Rpb24pCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkK"
    "ICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICByb290LmFkZFdp"
    "ZGdldChzZWxmLl90YWJsZSwgMSkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMg"
    "PSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVj"
    "IGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGhpZGRlbiA9IGJvb2wocmVjLmdldCgiaGlkZGVuIiwgRmFsc2UpKQogICAg"
    "ICAgICAgICBpZiBoaWRkZW4gYW5kIG5vdCBzZWxmLl9zaG93X2hpZGRlbjoKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAg"
    "ICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLmluc2VydFJvdyhyKQogICAg"
    "ICAgICAgICBzdGF0dXMgPSAiQXJjaGl2ZWQiIGlmIGhpZGRlbiBlbHNlIHJlYy5nZXQoInN0YXR1cyIsIkFjdGl2ZSIpCiAgICAg"
    "ICAgICAgIHZhbHMgPSBbCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJjb21wYW55IiwiIiksCiAgICAgICAgICAgICAgICByZWMu"
    "Z2V0KCJqb2JfdGl0bGUiLCIiKSwKICAgICAgICAgICAgICAgIHJlYy5nZXQoImRhdGVfYXBwbGllZCIsIiIpLAogICAgICAgICAg"
    "ICAgICAgcmVjLmdldCgibGluayIsIiIpLAogICAgICAgICAgICAgICAgc3RhdHVzLAogICAgICAgICAgICAgICAgcmVjLmdldCgi"
    "bm90ZXMiLCIiKSwKICAgICAgICAgICAgXQogICAgICAgICAgICBmb3IgYywgdiBpbiBlbnVtZXJhdGUodmFscyk6CiAgICAgICAg"
    "ICAgICAgICBpdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShzdHIodikpCiAgICAgICAgICAgICAgICBpZiBoaWRkZW46CiAgICAgICAg"
    "ICAgICAgICAgICAgaXRlbS5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICAgICAgICAgIHNlbGYuX3Rh"
    "YmxlLnNldEl0ZW0ociwgYywgaXRlbSkKICAgICAgICAgICAgIyBTdG9yZSByZWNvcmQgaW5kZXggaW4gZmlyc3QgY29sdW1uJ3Mg"
    "dXNlciBkYXRhCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLml0ZW0ociwgMCkuc2V0RGF0YSgKICAgICAgICAgICAgICAgIFF0Lkl0"
    "ZW1EYXRhUm9sZS5Vc2VyUm9sZSwKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuaW5kZXgocmVjKQogICAgICAgICAgICAp"
    "CgogICAgZGVmIF9zZWxlY3RlZF9pbmRpY2VzKHNlbGYpIC0+IGxpc3RbaW50XToKICAgICAgICBpbmRpY2VzID0gc2V0KCkKICAg"
    "ICAgICBmb3IgaXRlbSBpbiBzZWxmLl90YWJsZS5zZWxlY3RlZEl0ZW1zKCk6CiAgICAgICAgICAgIHJvd19pdGVtID0gc2VsZi5f"
    "dGFibGUuaXRlbShpdGVtLnJvdygpLCAwKQogICAgICAgICAgICBpZiByb3dfaXRlbToKICAgICAgICAgICAgICAgIGlkeCA9IHJv"
    "d19pdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAgICAgICAgICAgICAgaWYgaWR4IGlzIG5vdCBOb25lOgog"
    "ICAgICAgICAgICAgICAgICAgIGluZGljZXMuYWRkKGlkeCkKICAgICAgICByZXR1cm4gc29ydGVkKGluZGljZXMpCgogICAgZGVm"
    "IF9kaWFsb2coc2VsZiwgcmVjOiBkaWN0ID0gTm9uZSkgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgZGxnICA9IFFEaWFsb2co"
    "c2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkpvYiBBcHBsaWNhdGlvbiIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hl"
    "ZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBkbGcucmVzaXplKDUwMCwgMzIwKQog"
    "ICAgICAgIGZvcm0gPSBRRm9ybUxheW91dChkbGcpCgogICAgICAgIGNvbXBhbnkgPSBRTGluZUVkaXQocmVjLmdldCgiY29tcGFu"
    "eSIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIHRpdGxlICAgPSBRTGluZUVkaXQocmVjLmdldCgiam9iX3RpdGxlIiwiIikg"
    "aWYgcmVjIGVsc2UgIiIpCiAgICAgICAgZGUgICAgICA9IFFEYXRlRWRpdCgpCiAgICAgICAgZGUuc2V0Q2FsZW5kYXJQb3B1cChU"
    "cnVlKQogICAgICAgIGRlLnNldERpc3BsYXlGb3JtYXQoInl5eXktTU0tZGQiKQogICAgICAgIGlmIHJlYyBhbmQgcmVjLmdldCgi"
    "ZGF0ZV9hcHBsaWVkIik6CiAgICAgICAgICAgIGRlLnNldERhdGUoUURhdGUuZnJvbVN0cmluZyhyZWNbImRhdGVfYXBwbGllZCJd"
    "LCJ5eXl5LU1NLWRkIikpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgZGUuc2V0RGF0ZShRRGF0ZS5jdXJyZW50RGF0ZSgpKQog"
    "ICAgICAgIGxpbmsgICAgPSBRTGluZUVkaXQocmVjLmdldCgibGluayIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIHN0YXR1"
    "cyAgPSBRTGluZUVkaXQocmVjLmdldCgic3RhdHVzIiwiQXBwbGllZCIpIGlmIHJlYyBlbHNlICJBcHBsaWVkIikKICAgICAgICBu"
    "b3RlcyAgID0gUUxpbmVFZGl0KHJlYy5nZXQoIm5vdGVzIiwiIikgaWYgcmVjIGVsc2UgIiIpCgogICAgICAgIGZvciBsYWJlbCwg"
    "d2lkZ2V0IGluIFsKICAgICAgICAgICAgKCJDb21wYW55OiIsIGNvbXBhbnkpLCAoIkpvYiBUaXRsZToiLCB0aXRsZSksCiAgICAg"
    "ICAgICAgICgiRGF0ZSBBcHBsaWVkOiIsIGRlKSwgKCJMaW5rOiIsIGxpbmspLAogICAgICAgICAgICAoIlN0YXR1czoiLCBzdGF0"
    "dXMpLCAoIk5vdGVzOiIsIG5vdGVzKSwKICAgICAgICBdOgogICAgICAgICAgICBmb3JtLmFkZFJvdyhsYWJlbCwgd2lkZ2V0KQoK"
    "ICAgICAgICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGlj"
    "X2J0bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVjdChk"
    "bGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRS"
    "b3coYnRucykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAg"
    "IHJldHVybiB7CiAgICAgICAgICAgICAgICAiY29tcGFueSI6ICAgICAgY29tcGFueS50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAg"
    "ICAgICAgICJqb2JfdGl0bGUiOiAgICB0aXRsZS50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJkYXRlX2FwcGxpZWQi"
    "OiBkZS5kYXRlKCkudG9TdHJpbmcoInl5eXktTU0tZGQiKSwKICAgICAgICAgICAgICAgICJsaW5rIjogICAgICAgICBsaW5rLnRl"
    "eHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgIHN0YXR1cy50ZXh0KCkuc3RyaXAoKSBvciAiQXBw"
    "bGllZCIsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICAgbm90ZXMudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgIH0K"
    "ICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcCA9IHNlbGYuX2RpYWxv"
    "ZygpCiAgICAgICAgaWYgbm90IHA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5vdyA9IGRhdGV0aW1lLm5vdyh0aW1lem9u"
    "ZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgcC51cGRhdGUoewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICBzdHIodXVp"
    "ZC51dWlkNCgpKSwKICAgICAgICAgICAgImhpZGRlbiI6ICAgICAgICAgRmFsc2UsCiAgICAgICAgICAgICJjb21wbGV0ZWRfZGF0"
    "ZSI6IE5vbmUsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgIG5vdywKICAgICAgICAgICAgInVwZGF0ZWRfYXQiOiAgICAg"
    "bm93LAogICAgICAgIH0pCiAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQocCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9w"
    "YXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19tb2RpZnkoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICBpZHhzID0gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpCiAgICAgICAgaWYgbGVuKGlkeHMpICE9IDE6CiAgICAg"
    "ICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJNb2RpZnkiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAiU2VsZWN0IGV4YWN0bHkgb25lIHJvdyB0byBtb2RpZnkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVj"
    "ID0gc2VsZi5fcmVjb3Jkc1tpZHhzWzBdXQogICAgICAgIHAgICA9IHNlbGYuX2RpYWxvZyhyZWMpCiAgICAgICAgaWYgbm90IHA6"
    "CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlYy51cGRhdGUocCkKICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSA9IGRhdGV0"
    "aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVj"
    "b3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9faGlkZShzZWxmKSAtPiBOb25lOgogICAgICAgIGZvciBp"
    "ZHggaW4gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpOgogICAgICAgICAgICBpZiBpZHggPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bImhpZGRlbiJdICAgICAgICAgPSBUcnVlCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9yZWNvcmRzW2lkeF1bImNvbXBsZXRlZF9kYXRlIl0gPSAoCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tp"
    "ZHhdLmdldCgiY29tcGxldGVkX2RhdGUiKSBvcgogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmRhdGUoKS5pc29m"
    "b3JtYXQoKQogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJ1cGRhdGVkX2F0Il0g"
    "PSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAg"
    "ICAgICkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgp"
    "CgogICAgZGVmIF9kb191bmhpZGUoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3IgaWR4IGluIHNlbGYuX3NlbGVjdGVkX2luZGlj"
    "ZXMoKToKICAgICAgICAgICAgaWYgaWR4IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jk"
    "c1tpZHhdWyJoaWRkZW4iXSAgICAgPSBGYWxzZQogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJ1cGRhdGVkX2F0"
    "Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAg"
    "ICAgICAgICkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVz"
    "aCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICBpZHhzID0gc2VsZi5fc2VsZWN0ZWRfaW5kaWNl"
    "cygpCiAgICAgICAgaWYgbm90IGlkeHM6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVl"
    "c3Rpb24oCiAgICAgICAgICAgIHNlbGYsICJEZWxldGUiLAogICAgICAgICAgICBmIkRlbGV0ZSB7bGVuKGlkeHMpfSBzZWxlY3Rl"
    "ZCBhcHBsaWNhdGlvbihzKT8gQ2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRv"
    "bi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICkKICAgICAgICBpZiByZXBseSA9PSBRTWVzc2Fn"
    "ZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIGJhZCA9IHNldChpZHhzKQogICAgICAgICAgICBzZWxmLl9yZWNv"
    "cmRzID0gW3IgZm9yIGksIHIgaW4gZW51bWVyYXRlKHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "aWYgaSBub3QgaW4gYmFkXQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAg"
    "ICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfdG9nZ2xlX2hpZGRlbihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3No"
    "b3dfaGlkZGVuID0gbm90IHNlbGYuX3Nob3dfaGlkZGVuCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZS5zZXRUZXh0KAogICAgICAg"
    "ICAgICAi4piAIEhpZGUgQXJjaGl2ZWQiIGlmIHNlbGYuX3Nob3dfaGlkZGVuIGVsc2UgIuKYvSBTaG93IEFyY2hpdmVkIgogICAg"
    "ICAgICkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZXhwb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0"
    "aCwgZmlsdCA9IFFGaWxlRGlhbG9nLmdldFNhdmVGaWxlTmFtZSgKICAgICAgICAgICAgc2VsZiwgIkV4cG9ydCBKb2IgVHJhY2tl"
    "ciIsCiAgICAgICAgICAgIHN0cihjZmdfcGF0aCgiZXhwb3J0cyIpIC8gImpvYl90cmFja2VyLmNzdiIpLAogICAgICAgICAgICAi"
    "Q1NWIEZpbGVzICgqLmNzdik7O1RhYiBEZWxpbWl0ZWQgKCoudHh0KSIKICAgICAgICApCiAgICAgICAgaWYgbm90IHBhdGg6CiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIGRlbGltID0gIlx0IiBpZiBwYXRoLmxvd2VyKCkuZW5kc3dpdGgoIi50eHQiKSBlbHNl"
    "ICIsIgogICAgICAgIGhlYWRlciA9IFsiY29tcGFueSIsImpvYl90aXRsZSIsImRhdGVfYXBwbGllZCIsImxpbmsiLAogICAgICAg"
    "ICAgICAgICAgICAic3RhdHVzIiwiaGlkZGVuIiwiY29tcGxldGVkX2RhdGUiLCJub3RlcyJdCiAgICAgICAgd2l0aCBvcGVuKHBh"
    "dGgsICJ3IiwgZW5jb2Rpbmc9InV0Zi04IiwgbmV3bGluZT0iIikgYXMgZjoKICAgICAgICAgICAgZi53cml0ZShkZWxpbS5qb2lu"
    "KGhlYWRlcikgKyAiXG4iKQogICAgICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgICAgICB2YWxz"
    "ID0gWwogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImNvbXBhbnkiLCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0"
    "KCJqb2JfdGl0bGUiLCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJkYXRlX2FwcGxpZWQiLCIiKSwKICAgICAgICAg"
    "ICAgICAgICAgICByZWMuZ2V0KCJsaW5rIiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgic3RhdHVzIiwiIiksCiAg"
    "ICAgICAgICAgICAgICAgICAgc3RyKGJvb2wocmVjLmdldCgiaGlkZGVuIixGYWxzZSkpKSwKICAgICAgICAgICAgICAgICAgICBy"
    "ZWMuZ2V0KCJjb21wbGV0ZWRfZGF0ZSIsIiIpIG9yICIiLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiks"
    "CiAgICAgICAgICAgICAgICBdCiAgICAgICAgICAgICAgICBmLndyaXRlKGRlbGltLmpvaW4oCiAgICAgICAgICAgICAgICAgICAg"
    "c3RyKHYpLnJlcGxhY2UoIlxuIiwiICIpLnJlcGxhY2UoZGVsaW0sIiAiKQogICAgICAgICAgICAgICAgICAgIGZvciB2IGluIHZh"
    "bHMKICAgICAgICAgICAgICAgICkgKyAiXG4iKQogICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJFeHBvcnRl"
    "ZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJTYXZlZCB0byB7cGF0aH0iKQoKCiMg4pSA4pSAIFNFTEYgVEFC"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBSZWNvcmRzVGFiKFFXaWRnZXQp"
    "OgogICAgIiIiR29vZ2xlIERyaXZlL0RvY3MgcmVjb3JkcyBicm93c2VyIHRhYi4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwg"
    "cGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChz"
    "ZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQp"
    "CgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVsKCJSZWNvcmRzIGFyZSBub3QgbG9hZGVkIHlldC4iKQogICAgICAg"
    "IHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1m"
    "YW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRn"
    "ZXQoc2VsZi5zdGF0dXNfbGFiZWwpCgogICAgICAgIHNlbGYucGF0aF9sYWJlbCA9IFFMYWJlbCgiUGF0aDogTXkgRHJpdmUiKQog"
    "ICAgICAgIHNlbGYucGF0aF9sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0RJTX07IGZv"
    "bnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRk"
    "V2lkZ2V0KHNlbGYucGF0aF9sYWJlbCkKCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3QgPSBRTGlzdFdpZGdldCgpCiAgICAgICAg"
    "c2VsZi5yZWNvcmRzX2xpc3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjog"
    "e0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChz"
    "ZWxmLnJlY29yZHNfbGlzdCwgMSkKCiAgICBkZWYgc2V0X2l0ZW1zKHNlbGYsIGZpbGVzOiBsaXN0W2RpY3RdLCBwYXRoX3RleHQ6"
    "IHN0ciA9ICJNeSBEcml2ZSIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5wYXRoX2xhYmVsLnNldFRleHQoZiJQYXRoOiB7cGF0aF90"
    "ZXh0fSIpCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3QuY2xlYXIoKQogICAgICAgIGZvciBmaWxlX2luZm8gaW4gZmlsZXM6CiAg"
    "ICAgICAgICAgIHRpdGxlID0gKGZpbGVfaW5mby5nZXQoIm5hbWUiKSBvciAiVW50aXRsZWQiKS5zdHJpcCgpIG9yICJVbnRpdGxl"
    "ZCIKICAgICAgICAgICAgbWltZSA9IChmaWxlX2luZm8uZ2V0KCJtaW1lVHlwZSIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgICAg"
    "IGlmIG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5mb2xkZXIiOgogICAgICAgICAgICAgICAgcHJlZml4ID0g"
    "IvCfk4EiCiAgICAgICAgICAgIGVsaWYgbWltZSA9PSAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IjoKICAg"
    "ICAgICAgICAgICAgIHByZWZpeCA9ICLwn5OdIgogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgcHJlZml4ID0gIvCf"
    "k4QiCiAgICAgICAgICAgIG1vZGlmaWVkID0gKGZpbGVfaW5mby5nZXQoIm1vZGlmaWVkVGltZSIpIG9yICIiKS5yZXBsYWNlKCJU"
    "IiwgIiAiKS5yZXBsYWNlKCJaIiwgIiBVVEMiKQogICAgICAgICAgICB0ZXh0ID0gZiJ7cHJlZml4fSB7dGl0bGV9IiArIChmIiAg"
    "ICBbe21vZGlmaWVkfV0iIGlmIG1vZGlmaWVkIGVsc2UgIiIpCiAgICAgICAgICAgIGl0ZW0gPSBRTGlzdFdpZGdldEl0ZW0odGV4"
    "dCkKICAgICAgICAgICAgaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgZmlsZV9pbmZvKQogICAgICAgICAg"
    "ICBzZWxmLnJlY29yZHNfbGlzdC5hZGRJdGVtKGl0ZW0pCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkxvYWRl"
    "ZCB7bGVuKGZpbGVzKX0gR29vZ2xlIERyaXZlIGl0ZW0ocykuIikKCgpjbGFzcyBUYXNrc1RhYihRV2lkZ2V0KToKICAgICIiIlRh"
    "c2sgcmVnaXN0cnkgKyBHb29nbGUtZmlyc3QgZWRpdG9yIHdvcmtmbG93IHRhYi4iIiIKCiAgICBkZWYgX19pbml0X18oCiAgICAg"
    "ICAgc2VsZiwKICAgICAgICB0YXNrc19wcm92aWRlciwKICAgICAgICBvbl9hZGRfZWRpdG9yX29wZW4sCiAgICAgICAgb25fY29t"
    "cGxldGVfc2VsZWN0ZWQsCiAgICAgICAgb25fY2FuY2VsX3NlbGVjdGVkLAogICAgICAgIG9uX3RvZ2dsZV9jb21wbGV0ZWQsCiAg"
    "ICAgICAgb25fcHVyZ2VfY29tcGxldGVkLAogICAgICAgIG9uX2ZpbHRlcl9jaGFuZ2VkLAogICAgICAgIG9uX2VkaXRvcl9zYXZl"
    "LAogICAgICAgIG9uX2VkaXRvcl9jYW5jZWwsCiAgICAgICAgZGlhZ25vc3RpY3NfbG9nZ2VyPU5vbmUsCiAgICAgICAgcGFyZW50"
    "PU5vbmUsCiAgICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3Rhc2tzX3Byb3ZpZGVy"
    "ID0gdGFza3NfcHJvdmlkZXIKICAgICAgICBzZWxmLl9vbl9hZGRfZWRpdG9yX29wZW4gPSBvbl9hZGRfZWRpdG9yX29wZW4KICAg"
    "ICAgICBzZWxmLl9vbl9jb21wbGV0ZV9zZWxlY3RlZCA9IG9uX2NvbXBsZXRlX3NlbGVjdGVkCiAgICAgICAgc2VsZi5fb25fY2Fu"
    "Y2VsX3NlbGVjdGVkID0gb25fY2FuY2VsX3NlbGVjdGVkCiAgICAgICAgc2VsZi5fb25fdG9nZ2xlX2NvbXBsZXRlZCA9IG9uX3Rv"
    "Z2dsZV9jb21wbGV0ZWQKICAgICAgICBzZWxmLl9vbl9wdXJnZV9jb21wbGV0ZWQgPSBvbl9wdXJnZV9jb21wbGV0ZWQKICAgICAg"
    "ICBzZWxmLl9vbl9maWx0ZXJfY2hhbmdlZCA9IG9uX2ZpbHRlcl9jaGFuZ2VkCiAgICAgICAgc2VsZi5fb25fZWRpdG9yX3NhdmUg"
    "PSBvbl9lZGl0b3Jfc2F2ZQogICAgICAgIHNlbGYuX29uX2VkaXRvcl9jYW5jZWwgPSBvbl9lZGl0b3JfY2FuY2VsCiAgICAgICAg"
    "c2VsZi5fZGlhZ19sb2dnZXIgPSBkaWFnbm9zdGljc19sb2dnZXIKICAgICAgICBzZWxmLl9zaG93X2NvbXBsZXRlZCA9IEZhbHNl"
    "CiAgICAgICAgc2VsZi5fcmVmcmVzaF90aHJlYWQgPSBOb25lCiAgICAgICAgc2VsZi5fYnVpbGRfdWkoKQoKICAgIGRlZiBfYnVp"
    "bGRfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRl"
    "bnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQogICAgICAgIHNlbGYud29ya3NwYWNlX3N0"
    "YWNrID0gUVN0YWNrZWRXaWRnZXQoKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYud29ya3NwYWNlX3N0YWNrLCAxKQoKICAg"
    "ICAgICBub3JtYWwgPSBRV2lkZ2V0KCkKICAgICAgICBub3JtYWxfbGF5b3V0ID0gUVZCb3hMYXlvdXQobm9ybWFsKQogICAgICAg"
    "IG5vcm1hbF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbm9ybWFsX2xheW91dC5zZXRTcGFj"
    "aW5nKDQpCgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVsKCJUYXNrIHJlZ2lzdHJ5IGlzIG5vdCBsb2FkZWQgeWV0"
    "LiIpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9E"
    "SU19OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBu"
    "b3JtYWxfbGF5b3V0LmFkZFdpZGdldChzZWxmLnN0YXR1c19sYWJlbCkKCiAgICAgICAgZmlsdGVyX3JvdyA9IFFIQm94TGF5b3V0"
    "KCkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBEQVRFIFJBTkdFIikpCiAgICAgICAgc2Vs"
    "Zi50YXNrX2ZpbHRlcl9jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5hZGRJdGVtKCJX"
    "RUVLIiwgIndlZWsiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiTU9OVEgiLCAibW9udGgiKQogICAg"
    "ICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiTkVYVCAzIE1PTlRIUyIsICJuZXh0XzNfbW9udGhzIikKICAgICAg"
    "ICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIllFQVIiLCAieWVhciIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9j"
    "b21iby5zZXRDdXJyZW50SW5kZXgoMikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmN1cnJlbnRJbmRleENoYW5nZWQu"
    "Y29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIF86IHNlbGYuX29uX2ZpbHRlcl9jaGFuZ2VkKHNlbGYudGFza19maWx0ZXJfY29t"
    "Ym8uY3VycmVudERhdGEoKSBvciAibmV4dF8zX21vbnRocyIpCiAgICAgICAgKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0"
    "KHNlbGYudGFza19maWx0ZXJfY29tYm8pCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRTdHJldGNoKDEpCiAgICAgICAgbm9ybWFsX2xh"
    "eW91dC5hZGRMYXlvdXQoZmlsdGVyX3JvdykKCiAgICAgICAgc2VsZi50YXNrX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDQpCiAg"
    "ICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJTdGF0dXMiLCAiRHVlIiwgIlRhc2siLCAi"
    "U291cmNlIl0pCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKFFBYnN0cmFjdEl0ZW1WaWV3LlNl"
    "bGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFNlbGVjdGlvbk1vZGUoUUFic3Ry"
    "YWN0SXRlbVZpZXcuU2VsZWN0aW9uTW9kZS5FeHRlbmRlZFNlbGVjdGlvbikKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0RWRp"
    "dFRyaWdnZXJzKFFBYnN0cmFjdEl0ZW1WaWV3LkVkaXRUcmlnZ2VyLk5vRWRpdFRyaWdnZXJzKQogICAgICAgIHNlbGYudGFza190"
    "YWJsZS52ZXJ0aWNhbEhlYWRlcigpLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxI"
    "ZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAg"
    "ICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgxLCBRSGVhZGVyVmll"
    "dy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5z"
    "ZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi50YXNrX3Rh"
    "YmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgzLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6"
    "ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQog"
    "ICAgICAgIHNlbGYudGFza190YWJsZS5pdGVtU2VsZWN0aW9uQ2hhbmdlZC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0"
    "dG9uX3N0YXRlKQogICAgICAgIG5vcm1hbF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza190YWJsZSwgMSkKCiAgICAgICAgYWN0"
    "aW9ucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLmJ0bl9hZGRfdGFza193b3Jrc3BhY2UgPSBfZ290aGljX2J0bigiQURE"
    "IFRBU0siKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2sgPSBfZ290aGljX2J0bigiQ09NUExFVEUgU0VMRUNURUQiKQog"
    "ICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrID0gX2dvdGhpY19idG4oIkNBTkNFTCBTRUxFQ1RFRCIpCiAgICAgICAgc2VsZi5i"
    "dG5fdG9nZ2xlX2NvbXBsZXRlZCA9IF9nb3RoaWNfYnRuKCJTSE9XIENPTVBMRVRFRCIpCiAgICAgICAgc2VsZi5idG5fcHVyZ2Vf"
    "Y29tcGxldGVkID0gX2dvdGhpY19idG4oIlBVUkdFIENPTVBMRVRFRCIpCiAgICAgICAgc2VsZi5idG5fYWRkX3Rhc2tfd29ya3Nw"
    "YWNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9hZGRfZWRpdG9yX29wZW4pCiAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFz"
    "ay5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fY29tcGxldGVfc2VsZWN0ZWQpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2su"
    "Y2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2NhbmNlbF9zZWxlY3RlZCkKICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVk"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl90b2dnbGVfY29tcGxldGVkKQogICAgICAgIHNlbGYuYnRuX3B1cmdlX2NvbXBsZXRl"
    "ZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fcHVyZ2VfY29tcGxldGVkKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2su"
    "c2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzay5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIGZv"
    "ciBidG4gaW4gKAogICAgICAgICAgICBzZWxmLmJ0bl9hZGRfdGFza193b3Jrc3BhY2UsCiAgICAgICAgICAgIHNlbGYuYnRuX2Nv"
    "bXBsZXRlX3Rhc2ssCiAgICAgICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrLAogICAgICAgICAgICBzZWxmLmJ0bl90b2dnbGVf"
    "Y29tcGxldGVkLAogICAgICAgICAgICBzZWxmLmJ0bl9wdXJnZV9jb21wbGV0ZWQsCiAgICAgICAgKToKICAgICAgICAgICAgYWN0"
    "aW9ucy5hZGRXaWRnZXQoYnRuKQogICAgICAgIG5vcm1hbF9sYXlvdXQuYWRkTGF5b3V0KGFjdGlvbnMpCiAgICAgICAgc2VsZi53"
    "b3Jrc3BhY2Vfc3RhY2suYWRkV2lkZ2V0KG5vcm1hbCkKCiAgICAgICAgZWRpdG9yID0gUVdpZGdldCgpCiAgICAgICAgZWRpdG9y"
    "X2xheW91dCA9IFFWQm94TGF5b3V0KGVkaXRvcikKICAgICAgICBlZGl0b3JfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAw"
    "LCAwLCAwKQogICAgICAgIGVkaXRvcl9sYXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0"
    "KF9zZWN0aW9uX2xibCgi4p2nIFRBU0sgRURJVE9SIOKAlCBHT09HTEUtRklSU1QiKSkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9y"
    "X3N0YXR1c19sYWJlbCA9IFFMYWJlbCgiQ29uZmlndXJlIHRhc2sgZGV0YWlscywgdGhlbiBzYXZlIHRvIEdvb2dsZSBDYWxlbmRh"
    "ci4iKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFj"
    "a2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgcGFkZGlu"
    "ZzogNnB4OyIKICAgICAgICApCiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQoc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNf"
    "bGFiZWwpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9uYW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9y"
    "X25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJUYXNrIE5hbWUiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF0ZSA9"
    "IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLnNldFBsYWNlaG9sZGVyVGV4dCgiU3RhcnQg"
    "RGF0ZSAoWVlZWS1NTS1ERCkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfdGltZSA9IFFMaW5lRWRpdCgpCiAgICAg"
    "ICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiU3RhcnQgVGltZSAoSEg6TU0pIikKICAg"
    "ICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9k"
    "YXRlLnNldFBsYWNlaG9sZGVyVGV4dCgiRW5kIERhdGUgKFlZWVktTU0tREQpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2Vu"
    "ZF90aW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lLnNldFBsYWNlaG9sZGVyVGV4dCgi"
    "RW5kIFRpbWUgKEhIOk1NKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbiA9IFFMaW5lRWRpdCgpCiAgICAgICAg"
    "c2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbi5zZXRQbGFjZWhvbGRlclRleHQoIkxvY2F0aW9uIChvcHRpb25hbCkiKQogICAgICAg"
    "IHNlbGYudGFza19lZGl0b3JfcmVjdXJyZW5jZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9yZWN1cnJl"
    "bmNlLnNldFBsYWNlaG9sZGVyVGV4dCgiUmVjdXJyZW5jZSBSUlVMRSAob3B0aW9uYWwpIikKICAgICAgICBzZWxmLnRhc2tfZWRp"
    "dG9yX2FsbF9kYXkgPSBRQ2hlY2tCb3goIkFsbC1kYXkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfbm90ZXMgPSBRVGV4dEVk"
    "aXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfbm90ZXMuc2V0UGxhY2Vob2xkZXJUZXh0KCJOb3RlcyIpCiAgICAgICAgc2Vs"
    "Zi50YXNrX2VkaXRvcl9ub3Rlcy5zZXRNYXhpbXVtSGVpZ2h0KDkwKQogICAgICAgIGZvciB3aWRnZXQgaW4gKAogICAgICAgICAg"
    "ICBzZWxmLnRhc2tfZWRpdG9yX25hbWUsCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF0ZSwKICAgICAgICAg"
    "ICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlLAogICAg"
    "ICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2xvY2F0aW9uLAog"
    "ICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3JlY3VycmVuY2UsCiAgICAgICAgKToKICAgICAgICAgICAgZWRpdG9yX2xheW91"
    "dC5hZGRXaWRnZXQod2lkZ2V0KQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza19lZGl0b3JfYWxsX2Rh"
    "eSkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChzZWxmLnRhc2tfZWRpdG9yX25vdGVzLCAxKQogICAgICAgIGVkaXRv"
    "cl9hY3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9zYXZlID0gX2dvdGhpY19idG4oIlNBVkUiKQogICAgICAgIGJ0"
    "bl9jYW5jZWwgPSBfZ290aGljX2J0bigiQ0FOQ0VMIikKICAgICAgICBidG5fc2F2ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25f"
    "ZWRpdG9yX3NhdmUpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fZWRpdG9yX2NhbmNlbCkKICAg"
    "ICAgICBlZGl0b3JfYWN0aW9ucy5hZGRXaWRnZXQoYnRuX3NhdmUpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkV2lkZ2V0KGJ0"
    "bl9jYW5jZWwpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkU3RyZXRjaCgxKQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkTGF5"
    "b3V0KGVkaXRvcl9hY3Rpb25zKQogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLmFkZFdpZGdldChlZGl0b3IpCgogICAgICAg"
    "IHNlbGYubm9ybWFsX3dvcmtzcGFjZSA9IG5vcm1hbAogICAgICAgIHNlbGYuZWRpdG9yX3dvcmtzcGFjZSA9IGVkaXRvcgogICAg"
    "ICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQoc2VsZi5ub3JtYWxfd29ya3NwYWNlKQoKICAgIGRlZiBf"
    "dXBkYXRlX2FjdGlvbl9idXR0b25fc3RhdGUoc2VsZikgLT4gTm9uZToKICAgICAgICBlbmFibGVkID0gYm9vbChzZWxmLnNlbGVj"
    "dGVkX3Rhc2tfaWRzKCkpCiAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzay5zZXRFbmFibGVkKGVuYWJsZWQpCiAgICAgICAg"
    "c2VsZi5idG5fY2FuY2VsX3Rhc2suc2V0RW5hYmxlZChlbmFibGVkKQoKICAgIGRlZiBzZWxlY3RlZF90YXNrX2lkcyhzZWxmKSAt"
    "PiBsaXN0W3N0cl06CiAgICAgICAgaWRzOiBsaXN0W3N0cl0gPSBbXQogICAgICAgIGZvciByIGluIHJhbmdlKHNlbGYudGFza190"
    "YWJsZS5yb3dDb3VudCgpKToKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBzZWxmLnRhc2tfdGFibGUuaXRlbShyLCAwKQogICAg"
    "ICAgICAgICBpZiBzdGF0dXNfaXRlbSBpcyBOb25lOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgbm90"
    "IHN0YXR1c19pdGVtLmlzU2VsZWN0ZWQoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIHRhc2tfaWQgPSBz"
    "dGF0dXNfaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgaWYgdGFza19pZCBhbmQgdGFza19p"
    "ZCBub3QgaW4gaWRzOgogICAgICAgICAgICAgICAgaWRzLmFwcGVuZCh0YXNrX2lkKQogICAgICAgIHJldHVybiBpZHMKCiAgICBk"
    "ZWYgbG9hZF90YXNrcyhzZWxmLCB0YXNrczogbGlzdFtkaWN0XSkgLT4gTm9uZToKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0"
    "Um93Q291bnQoMCkKICAgICAgICBmb3IgdGFzayBpbiB0YXNrczoKICAgICAgICAgICAgcm93ID0gc2VsZi50YXNrX3RhYmxlLnJv"
    "d0NvdW50KCkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLmluc2VydFJvdyhyb3cpCiAgICAgICAgICAgIHN0YXR1cyA9ICh0"
    "YXNrLmdldCgic3RhdHVzIikgb3IgInBlbmRpbmciKS5sb3dlcigpCiAgICAgICAgICAgIHN0YXR1c19pY29uID0gIuKYkSIgaWYg"
    "c3RhdHVzIGluIHsiY29tcGxldGVkIiwgImNhbmNlbGxlZCJ9IGVsc2UgIuKAoiIKICAgICAgICAgICAgZHVlID0gKHRhc2suZ2V0"
    "KCJkdWVfYXQiKSBvciAiIikucmVwbGFjZSgiVCIsICIgIikKICAgICAgICAgICAgdGV4dCA9ICh0YXNrLmdldCgidGV4dCIpIG9y"
    "ICJSZW1pbmRlciIpLnN0cmlwKCkgb3IgIlJlbWluZGVyIgogICAgICAgICAgICBzb3VyY2UgPSAodGFzay5nZXQoInNvdXJjZSIp"
    "IG9yICJsb2NhbCIpLmxvd2VyKCkKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKGYie3N0YXR1c19p"
    "Y29ufSB7c3RhdHVzfSIpCiAgICAgICAgICAgIHN0YXR1c19pdGVtLnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCB0"
    "YXNrLmdldCgiaWQiKSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAwLCBzdGF0dXNfaXRlbSkKICAg"
    "ICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAxLCBRVGFibGVXaWRnZXRJdGVtKGR1ZSkpCiAgICAgICAgICAg"
    "IHNlbGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMiwgUVRhYmxlV2lkZ2V0SXRlbSh0ZXh0KSkKICAgICAgICAgICAgc2VsZi50"
    "YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAzLCBRVGFibGVXaWRnZXRJdGVtKHNvdXJjZSkpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFi"
    "ZWwuc2V0VGV4dChmIkxvYWRlZCB7bGVuKHRhc2tzKX0gdGFzayhzKS4iKQogICAgICAgIHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0"
    "dG9uX3N0YXRlKCkKCiAgICBkZWYgX2RpYWcoc2VsZiwgbWVzc2FnZTogc3RyLCBsZXZlbDogc3RyID0gIklORk8iKSAtPiBOb25l"
    "OgogICAgICAgIHRyeToKICAgICAgICAgICAgaWYgc2VsZi5fZGlhZ19sb2dnZXI6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFn"
    "X2xvZ2dlcihtZXNzYWdlLCBsZXZlbCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgZGVm"
    "IHN0b3BfcmVmcmVzaF93b3JrZXIoc2VsZiwgcmVhc29uOiBzdHIgPSAiIikgLT4gTm9uZToKICAgICAgICB0aHJlYWQgPSBnZXRh"
    "dHRyKHNlbGYsICJfcmVmcmVzaF90aHJlYWQiLCBOb25lKQogICAgICAgIGlmIHRocmVhZCBpcyBub3QgTm9uZSBhbmQgaGFzYXR0"
    "cih0aHJlYWQsICJpc1J1bm5pbmciKSBhbmQgdGhyZWFkLmlzUnVubmluZygpOgogICAgICAgICAgICBzZWxmLl9kaWFnKAogICAg"
    "ICAgICAgICAgICAgZiJbVEFTS1NdW1RIUkVBRF1bV0FSTl0gc3RvcCByZXF1ZXN0ZWQgZm9yIHJlZnJlc2ggd29ya2VyIHJlYXNv"
    "bj17cmVhc29uIG9yICd1bnNwZWNpZmllZCd9IiwKICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgICAgICB0aHJlYWQucmVxdWVzdEludGVycnVwdGlvbigpCiAgICAgICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHRocmVhZC5xdWl0"
    "KCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICAgICAgdGhyZWFkLndh"
    "aXQoMjAwMCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3RocmVhZCA9IE5vbmUKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIGlmIG5vdCBjYWxsYWJsZShzZWxmLl90YXNrc19wcm92aWRlcik6CiAgICAgICAgICAgIHJldHVybgogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgc2VsZi5sb2FkX3Rhc2tzKHNlbGYuX3Rhc2tzX3Byb3ZpZGVyKCkpCiAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fZGlhZyhmIltUQVNLU11bVEFCXVtFUlJPUl0gcmVmcmVzaCBmYWlsZWQ6"
    "IHtleH0iLCAiRVJST1IiKQogICAgICAgICAgICBzZWxmLnN0b3BfcmVmcmVzaF93b3JrZXIocmVhc29uPSJ0YXNrc190YWJfcmVm"
    "cmVzaF9leGNlcHRpb24iKQoKICAgIGRlZiBjbG9zZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHNlbGYuc3Rv"
    "cF9yZWZyZXNoX3dvcmtlcihyZWFzb249InRhc2tzX3RhYl9jbG9zZSIpCiAgICAgICAgc3VwZXIoKS5jbG9zZUV2ZW50KGV2ZW50"
    "KQoKICAgIGRlZiBzZXRfc2hvd19jb21wbGV0ZWQoc2VsZiwgZW5hYmxlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9z"
    "aG93X2NvbXBsZXRlZCA9IGJvb2woZW5hYmxlZCkKICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLnNldFRleHQoIkhJ"
    "REUgQ09NUExFVEVEIiBpZiBzZWxmLl9zaG93X2NvbXBsZXRlZCBlbHNlICJTSE9XIENPTVBMRVRFRCIpCgogICAgZGVmIHNldF9z"
    "dGF0dXMoc2VsZiwgdGV4dDogc3RyLCBvazogYm9vbCA9IEZhbHNlKSAtPiBOb25lOgogICAgICAgIGNvbG9yID0gQ19HUkVFTiBp"
    "ZiBvayBlbHNlIENfVEVYVF9ESU0KICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Y29sb3J9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JE"
    "RVJ9OyBwYWRkaW5nOiA2cHg7IgogICAgICAgICkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbC5zZXRUZXh0"
    "KHRleHQpCgogICAgZGVmIG9wZW5fZWRpdG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suc2V0"
    "Q3VycmVudFdpZGdldChzZWxmLmVkaXRvcl93b3Jrc3BhY2UpCgogICAgZGVmIGNsb3NlX2VkaXRvcihzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQoc2VsZi5ub3JtYWxfd29ya3NwYWNlKQoKCmNsYXNz"
    "IFNlbGZUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFBlcnNvbmEncyBpbnRlcm5hbCBkaWFsb2d1ZSBzcGFjZS4KICAgIFJlY2Vp"
    "dmVzOiBpZGxlIG5hcnJhdGl2ZSBvdXRwdXQsIHVuc29saWNpdGVkIHRyYW5zbWlzc2lvbnMsCiAgICAgICAgICAgICAgUG9JIGxp"
    "c3QgZnJvbSBkYWlseSByZWZsZWN0aW9uLCB1bmFuc3dlcmVkIHF1ZXN0aW9uIGZsYWdzLAogICAgICAgICAgICAgIGpvdXJuYWwg"
    "bG9hZCBub3RpZmljYXRpb25zLgogICAgUmVhZC1vbmx5IGRpc3BsYXkuIFNlcGFyYXRlIGZyb20gcGVyc29uYSBjaGF0IHRhYiBh"
    "bHdheXMuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0"
    "X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5z"
    "KDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGhkciA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBoZHIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibChmIuKdpyBJTk5FUiBTQU5DVFVNIOKAlCB7REVDS19OQU1FLnVwcGVyKCl9J1Mg"
    "UFJJVkFURSBUSE9VR0hUUyIpKQogICAgICAgIHNlbGYuX2J0bl9jbGVhciA9IF9nb3RoaWNfYnRuKCLinJcgQ2xlYXIiKQogICAg"
    "ICAgIHNlbGYuX2J0bl9jbGVhci5zZXRGaXhlZFdpZHRoKDgwKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5jbGlja2VkLmNvbm5l"
    "Y3Qoc2VsZi5jbGVhcikKICAgICAgICBoZHIuYWRkU3RyZXRjaCgpCiAgICAgICAgaGRyLmFkZFdpZGdldChzZWxmLl9idG5fY2xl"
    "YXIpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoaGRyKQoKICAgICAgICBzZWxmLl9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAg"
    "ICBzZWxmLl9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6"
    "IDFweCBzb2xpZCB7Q19QVVJQTEVfRElNfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7"
    "IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fZGlz"
    "cGxheSwgMSkKCiAgICBkZWYgYXBwZW5kKHNlbGYsIGxhYmVsOiBzdHIsIHRleHQ6IHN0cikgLT4gTm9uZToKICAgICAgICB0aW1l"
    "c3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgIGNvbG9ycyA9IHsKICAgICAgICAgICAg"
    "Ik5BUlJBVElWRSI6ICBDX0dPTEQsCiAgICAgICAgICAgICJSRUZMRUNUSU9OIjogQ19QVVJQTEUsCiAgICAgICAgICAgICJKT1VS"
    "TkFMIjogICAgQ19TSUxWRVIsCiAgICAgICAgICAgICJQT0kiOiAgICAgICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAgIlNZU1RF"
    "TSI6ICAgICBDX1RFWFRfRElNLAogICAgICAgIH0KICAgICAgICBjb2xvciA9IGNvbG9ycy5nZXQobGFiZWwudXBwZXIoKSwgQ19H"
    "T0xEKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhU"
    "X0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAgICAg"
    "Zic8c3BhbiBzdHlsZT0iY29sb3I6e2NvbG9yfTsgZm9udC13ZWlnaHQ6Ym9sZDsiPicKICAgICAgICAgICAgZifinacge2xhYmVs"
    "fTwvc3Bhbj48YnI+JwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19HT0xEfTsiPnt0ZXh0fTwvc3Bhbj4nCiAg"
    "ICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKCIiKQogICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3Jv"
    "bGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQog"
    "ICAgICAgICkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kaXNwbGF5LmNsZWFyKCkKCgojIOKU"
    "gOKUgCBESUFHTk9TVElDUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIERpYWdub3N0aWNzVGFiKFFXaWRn"
    "ZXQpOgogICAgIiIiCiAgICBCYWNrZW5kIGRpYWdub3N0aWNzIGRpc3BsYXkuCiAgICBSZWNlaXZlczogaGFyZHdhcmUgZGV0ZWN0"
    "aW9uIHJlc3VsdHMsIGRlcGVuZGVuY3kgY2hlY2sgcmVzdWx0cywKICAgICAgICAgICAgICBBUEkgZXJyb3JzLCBzeW5jIGZhaWx1"
    "cmVzLCB0aW1lciBldmVudHMsIGpvdXJuYWwgbG9hZCBub3RpY2VzLAogICAgICAgICAgICAgIG1vZGVsIGxvYWQgc3RhdHVzLCBH"
    "b29nbGUgYXV0aCBldmVudHMuCiAgICBBbHdheXMgc2VwYXJhdGUgZnJvbSBwZXJzb25hIGNoYXQgdGFiLgogICAgIiIiCgogICAg"
    "ZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBy"
    "b290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAg"
    "IHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBoZHIgPSBRSEJveExheW91dCgpCiAgICAgICAgaGRyLmFkZFdpZGdldChfc2Vj"
    "dGlvbl9sYmwoIuKdpyBESUFHTk9TVElDUyDigJQgU1lTVEVNICYgQkFDS0VORCBMT0ciKSkKICAgICAgICBzZWxmLl9idG5fY2xl"
    "YXIgPSBfZ290aGljX2J0bigi4pyXIENsZWFyIikKICAgICAgICBzZWxmLl9idG5fY2xlYXIuc2V0Rml4ZWRXaWR0aCg4MCkKICAg"
    "ICAgICBzZWxmLl9idG5fY2xlYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYuY2xlYXIpCiAgICAgICAgaGRyLmFkZFN0cmV0Y2goKQog"
    "ICAgICAgIGhkci5hZGRXaWRnZXQoc2VsZi5fYnRuX2NsZWFyKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGhkcikKCiAgICAgICAg"
    "c2VsZi5fZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAg"
    "IHNlbGYuX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6"
    "IHtDX1NJTFZFUn07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYi"
    "Zm9udC1mYW1pbHk6ICdDb3VyaWVyIE5ldycsIG1vbm9zcGFjZTsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTogMTBweDsgcGFk"
    "ZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fZGlzcGxheSwgMSkKCiAgICBkZWYgbG9n"
    "KHNlbGYsIG1lc3NhZ2U6IHN0ciwgbGV2ZWw6IHN0ciA9ICJJTkZPIikgLT4gTm9uZToKICAgICAgICB0aW1lc3RhbXAgPSBkYXRl"
    "dGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgIGxldmVsX2NvbG9ycyA9IHsKICAgICAgICAgICAgIklORk8i"
    "OiAgQ19TSUxWRVIsCiAgICAgICAgICAgICJPSyI6ICAgIENfR1JFRU4sCiAgICAgICAgICAgICJXQVJOIjogIENfR09MRCwKICAg"
    "ICAgICAgICAgIkVSUk9SIjogQ19CTE9PRCwKICAgICAgICAgICAgIkRFQlVHIjogQ19URVhUX0RJTSwKICAgICAgICB9CiAgICAg"
    "ICAgY29sb3IgPSBsZXZlbF9jb2xvcnMuZ2V0KGxldmVsLnVwcGVyKCksIENfU0lMVkVSKQogICAgICAgIHNlbGYuX2Rpc3BsYXku"
    "YXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07Ij5be3RpbWVzdGFtcH1dPC9zcGFu"
    "PiAnCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07Ij57bWVzc2FnZX08L3NwYW4+JwogICAgICAgICkK"
    "ICAgICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2Rpc3Bs"
    "YXkudmVydGljYWxTY3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAgZGVmIGxvZ19tYW55KHNlbGYsIG1lc3NhZ2Vz"
    "OiBsaXN0W3N0cl0sIGxldmVsOiBzdHIgPSAiSU5GTyIpIC0+IE5vbmU6CiAgICAgICAgZm9yIG1zZyBpbiBtZXNzYWdlczoKICAg"
    "ICAgICAgICAgbHZsID0gbGV2ZWwKICAgICAgICAgICAgaWYgIuKckyIgaW4gbXNnOiAgICBsdmwgPSAiT0siCiAgICAgICAgICAg"
    "IGVsaWYgIuKclyIgaW4gbXNnOiAgbHZsID0gIldBUk4iCiAgICAgICAgICAgIGVsaWYgIkVSUk9SIiBpbiBtc2cudXBwZXIoKTog"
    "bHZsID0gIkVSUk9SIgogICAgICAgICAgICBzZWxmLmxvZyhtc2csIGx2bCkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9kaXNwbGF5LmNsZWFyKCkKCgojIOKUgOKUgCBMRVNTT05TIFRBQiDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKY2xhc3MgTGVzc29uc1RhYihRV2lkZ2V0KToKICAgICIiIgogICAgTFNMIEZvcmJpZGRlbiBSdWxl"
    "c2V0IGFuZCBjb2RlIGxlc3NvbnMgYnJvd3Nlci4KICAgIEFkZCwgdmlldywgc2VhcmNoLCBkZWxldGUgbGVzc29ucy4KICAgICIi"
    "IgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBkYjogIkxlc3NvbnNMZWFybmVkREIiLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3Vw"
    "ZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZGIgPSBkYgogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAg"
    "ICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlv"
    "dXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2lu"
    "Zyg0KQoKICAgICAgICAjIEZpbHRlciBiYXIKICAgICAgICBmaWx0ZXJfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYu"
    "X3NlYXJjaCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fc2VhcmNoLnNldFBsYWNlaG9sZGVyVGV4dCgiU2VhcmNoIGxlc3Nv"
    "bnMuLi4iKQogICAgICAgIHNlbGYuX2xhbmdfZmlsdGVyID0gUUNvbWJvQm94KCkKICAgICAgICBzZWxmLl9sYW5nX2ZpbHRlci5h"
    "ZGRJdGVtcyhbIkFsbCIsICJMU0wiLCAiUHl0aG9uIiwgIlB5U2lkZTYiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIkphdmFTY3JpcHQiLCAiT3RoZXIiXSkKICAgICAgICBzZWxmLl9zZWFyY2gudGV4dENoYW5nZWQuY29ubmVjdChzZWxm"
    "LnJlZnJlc2gpCiAgICAgICAgc2VsZi5fbGFuZ19maWx0ZXIuY3VycmVudFRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5yZWZyZXNo"
    "KQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgiU2VhcmNoOiIpKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lk"
    "Z2V0KHNlbGYuX3NlYXJjaCwgMSkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChRTGFiZWwoIkxhbmd1YWdlOiIpKQogICAg"
    "ICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYuX2xhbmdfZmlsdGVyKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGZpbHRlcl9y"
    "b3cpCgogICAgICAgIGJ0bl9iYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX2FkZCA9IF9nb3RoaWNfYnRuKCLinKYgQWRk"
    "IExlc3NvbiIpCiAgICAgICAgYnRuX2RlbCA9IF9nb3RoaWNfYnRuKCLinJcgRGVsZXRlIikKICAgICAgICBidG5fYWRkLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgYnRuX2RlbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQog"
    "ICAgICAgIGJ0bl9iYXIuYWRkV2lkZ2V0KGJ0bl9hZGQpCiAgICAgICAgYnRuX2Jhci5hZGRXaWRnZXQoYnRuX2RlbCkKICAgICAg"
    "ICBidG5fYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJ0bl9iYXIpCgogICAgICAgIHNlbGYuX3RhYmxl"
    "ID0gUVRhYmxlV2lkZ2V0KDAsIDQpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscygKICAgICAg"
    "ICAgICAgWyJMYW5ndWFnZSIsICJSZWZlcmVuY2UgS2V5IiwgIlN1bW1hcnkiLCAiRW52aXJvbm1lbnQiXQogICAgICAgICkKICAg"
    "ICAgICBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDIsIFFI"
    "ZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigKICAg"
    "ICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLl90YWJs"
    "ZS5zZXRBbHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVlKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190"
    "YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX3RhYmxlLml0ZW1TZWxlY3Rpb25DaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fc2Vs"
    "ZWN0KQoKICAgICAgICAjIFVzZSBzcGxpdHRlciBiZXR3ZWVuIHRhYmxlIGFuZCBkZXRhaWwKICAgICAgICBzcGxpdHRlciA9IFFT"
    "cGxpdHRlcihRdC5PcmllbnRhdGlvbi5WZXJ0aWNhbCkKICAgICAgICBzcGxpdHRlci5hZGRXaWRnZXQoc2VsZi5fdGFibGUpCgog"
    "ICAgICAgICMgRGV0YWlsIHBhbmVsCiAgICAgICAgZGV0YWlsX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIGRldGFpbF9sYXlv"
    "dXQgPSBRVkJveExheW91dChkZXRhaWxfd2lkZ2V0KQogICAgICAgIGRldGFpbF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAs"
    "IDQsIDAsIDApCiAgICAgICAgZGV0YWlsX2xheW91dC5zZXRTcGFjaW5nKDIpCgogICAgICAgIGRldGFpbF9oZWFkZXIgPSBRSEJv"
    "eExheW91dCgpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgRlVMTCBSVUxFIikpCiAg"
    "ICAgICAgZGV0YWlsX2hlYWRlci5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlID0gX2dvdGhpY19idG4o"
    "IkVkaXQiKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Rml4ZWRXaWR0aCg1MCkKICAgICAgICBzZWxmLl9idG5fZWRp"
    "dF9ydWxlLnNldENoZWNrYWJsZShUcnVlKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUudG9nZ2xlZC5jb25uZWN0KHNlbGYu"
    "X3RvZ2dsZV9lZGl0X21vZGUpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZSA9IF9nb3RoaWNfYnRuKCJTYXZlIikKICAgICAg"
    "ICBzZWxmLl9idG5fc2F2ZV9ydWxlLnNldEZpeGVkV2lkdGgoNTApCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRWaXNp"
    "YmxlKEZhbHNlKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3NhdmVfcnVsZV9lZGl0"
    "KQogICAgICAgIGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9lZGl0X3J1bGUpCiAgICAgICAgZGV0YWlsX2hlYWRl"
    "ci5hZGRXaWRnZXQoc2VsZi5fYnRuX3NhdmVfcnVsZSkKICAgICAgICBkZXRhaWxfbGF5b3V0LmFkZExheW91dChkZXRhaWxfaGVh"
    "ZGVyKQoKICAgICAgICBzZWxmLl9kZXRhaWwgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2RldGFpbC5zZXRSZWFkT25seShU"
    "cnVlKQogICAgICAgIHNlbGYuX2RldGFpbC5zZXRNaW5pbXVtSGVpZ2h0KDEyMCkKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAg"
    "ZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBz"
    "ZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICkKICAgICAgICBkZXRhaWxfbGF5b3V0LmFkZFdp"
    "ZGdldChzZWxmLl9kZXRhaWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KGRldGFpbF93aWRnZXQpCiAgICAgICAgc3BsaXR0"
    "ZXIuc2V0U2l6ZXMoWzMwMCwgMTgwXSkKICAgICAgICByb290LmFkZFdpZGdldChzcGxpdHRlciwgMSkKCiAgICAgICAgc2VsZi5f"
    "cmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fZWRpdGluZ19yb3c6IGludCA9IC0xCgogICAgZGVmIHJlZnJl"
    "c2goc2VsZikgLT4gTm9uZToKICAgICAgICBxICAgID0gc2VsZi5fc2VhcmNoLnRleHQoKQogICAgICAgIGxhbmcgPSBzZWxmLl9s"
    "YW5nX2ZpbHRlci5jdXJyZW50VGV4dCgpCiAgICAgICAgbGFuZyA9ICIiIGlmIGxhbmcgPT0gIkFsbCIgZWxzZSBsYW5nCiAgICAg"
    "ICAgc2VsZi5fcmVjb3JkcyA9IHNlbGYuX2RiLnNlYXJjaChxdWVyeT1xLCBsYW5ndWFnZT1sYW5nKQogICAgICAgIHNlbGYuX3Rh"
    "YmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICByID0gc2VsZi5f"
    "dGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fdGFi"
    "bGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJsYW5ndWFnZSIsIiIpKSkK"
    "ICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMu"
    "Z2V0KCJyZWZlcmVuY2Vfa2V5IiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDIsCiAgICAgICAgICAg"
    "ICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInN1bW1hcnkiLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0"
    "ZW0ociwgMywKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiZW52aXJvbm1lbnQiLCIiKSkpCgogICAg"
    "ZGVmIF9vbl9zZWxlY3Qoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAg"
    "ICBzZWxmLl9lZGl0aW5nX3JvdyA9IHJvdwogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAg"
    "ICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFBsYWluVGV4dCgKICAgICAg"
    "ICAgICAgICAgIHJlYy5nZXQoImZ1bGxfcnVsZSIsIiIpICsgIlxuXG4iICsKICAgICAgICAgICAgICAgICgiUmVzb2x1dGlvbjog"
    "IiArIHJlYy5nZXQoInJlc29sdXRpb24iLCIiKSBpZiByZWMuZ2V0KCJyZXNvbHV0aW9uIikgZWxzZSAiIikKICAgICAgICAgICAg"
    "KQogICAgICAgICAgICAjIFJlc2V0IGVkaXQgbW9kZSBvbiBuZXcgc2VsZWN0aW9uCiAgICAgICAgICAgIHNlbGYuX2J0bl9lZGl0"
    "X3J1bGUuc2V0Q2hlY2tlZChGYWxzZSkKCiAgICBkZWYgX3RvZ2dsZV9lZGl0X21vZGUoc2VsZiwgZWRpdGluZzogYm9vbCkgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0UmVhZE9ubHkobm90IGVkaXRpbmcpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVf"
    "cnVsZS5zZXRWaXNpYmxlKGVkaXRpbmcpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRUZXh0KCJDYW5jZWwiIGlmIGVk"
    "aXRpbmcgZWxzZSAiRWRpdCIpCiAgICAgICAgaWYgZWRpdGluZzoKICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICAg"
    "ICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNL"
    "X0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToK"
    "ICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JH"
    "M307IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAg"
    "ICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzog"
    "NHB4OyIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIFJlbG9hZCBvcmlnaW5hbCBjb250ZW50IG9uIGNhbmNlbAogICAgICAg"
    "ICAgICBzZWxmLl9vbl9zZWxlY3QoKQoKICAgIGRlZiBfc2F2ZV9ydWxlX2VkaXQoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cg"
    "PSBzZWxmLl9lZGl0aW5nX3JvdwogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICB0"
    "ZXh0ID0gc2VsZi5fZGV0YWlsLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQogICAgICAgICAgICAjIFNwbGl0IHJlc29sdXRpb24gYmFj"
    "ayBvdXQgaWYgcHJlc2VudAogICAgICAgICAgICBpZiAiXG5cblJlc29sdXRpb246ICIgaW4gdGV4dDoKICAgICAgICAgICAgICAg"
    "IHBhcnRzID0gdGV4dC5zcGxpdCgiXG5cblJlc29sdXRpb246ICIsIDEpCiAgICAgICAgICAgICAgICBmdWxsX3J1bGUgID0gcGFy"
    "dHNbMF0uc3RyaXAoKQogICAgICAgICAgICAgICAgcmVzb2x1dGlvbiA9IHBhcnRzWzFdLnN0cmlwKCkKICAgICAgICAgICAgZWxz"
    "ZToKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZSAgPSB0ZXh0CiAgICAgICAgICAgICAgICByZXNvbHV0aW9uID0gc2VsZi5fcmVj"
    "b3Jkc1tyb3ddLmdldCgicmVzb2x1dGlvbiIsICIiKQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd11bImZ1bGxfcnVsZSJd"
    "ICA9IGZ1bGxfcnVsZQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd11bInJlc29sdXRpb24iXSA9IHJlc29sdXRpb24KICAg"
    "ICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fZGIuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYuX2J0bl9l"
    "ZGl0X3J1bGUuc2V0Q2hlY2tlZChGYWxzZSkKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2FkZChzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkFkZCBMZXNz"
    "b24iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAg"
    "ICAgICAgZGxnLnJlc2l6ZSg1MDAsIDQwMCkKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAgIGVudiAgPSBR"
    "TGluZUVkaXQoIkxTTCIpCiAgICAgICAgbGFuZyA9IFFMaW5lRWRpdCgiTFNMIikKICAgICAgICByZWYgID0gUUxpbmVFZGl0KCkK"
    "ICAgICAgICBzdW1tID0gUUxpbmVFZGl0KCkKICAgICAgICBydWxlID0gUVRleHRFZGl0KCkKICAgICAgICBydWxlLnNldE1heGlt"
    "dW1IZWlnaHQoMTAwKQogICAgICAgIHJlcyAgPSBRTGluZUVkaXQoKQogICAgICAgIGxpbmsgPSBRTGluZUVkaXQoKQogICAgICAg"
    "IGZvciBsYWJlbCwgdyBpbiBbCiAgICAgICAgICAgICgiRW52aXJvbm1lbnQ6IiwgZW52KSwgKCJMYW5ndWFnZToiLCBsYW5nKSwK"
    "ICAgICAgICAgICAgKCJSZWZlcmVuY2UgS2V5OiIsIHJlZiksICgiU3VtbWFyeToiLCBzdW1tKSwKICAgICAgICAgICAgKCJGdWxs"
    "IFJ1bGU6IiwgcnVsZSksICgiUmVzb2x1dGlvbjoiLCByZXMpLAogICAgICAgICAgICAoIkxpbms6IiwgbGluayksCiAgICAgICAg"
    "XToKICAgICAgICAgICAgZm9ybS5hZGRSb3cobGFiZWwsIHcpCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBv"
    "ayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25u"
    "ZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7"
    "IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlh"
    "bG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHNlbGYuX2RiLmFkZCgKICAgICAgICAgICAgICAgIGVudmlyb25t"
    "ZW50PWVudi50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGxhbmd1YWdlPWxhbmcudGV4dCgpLnN0cmlwKCksCiAgICAg"
    "ICAgICAgICAgICByZWZlcmVuY2Vfa2V5PXJlZi50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIHN1bW1hcnk9c3VtbS50"
    "ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZT1ydWxlLnRvUGxhaW5UZXh0KCkuc3RyaXAoKSwKICAgICAg"
    "ICAgICAgICAgIHJlc29sdXRpb249cmVzLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgbGluaz1saW5rLnRleHQoKS5z"
    "dHJpcCgpLAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihz"
    "ZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmVjX2lkID0gc2VsZi5fcmVjb3Jkc1tyb3ddLmdldCgiaWQiLCIiKQogICAgICAg"
    "ICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBMZXNzb24iLAog"
    "ICAgICAgICAgICAgICAgIkRlbGV0ZSB0aGlzIGxlc3Nvbj8gQ2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICAgICAgUU1l"
    "c3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9kYi5kZWxldGUocmVjX2lkKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCgojIOKUgOKUgCBNT0RVTEUgVFJBQ0tF"
    "UiBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1vZHVsZVRyYWNrZXJUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFBlcnNv"
    "bmFsIG1vZHVsZSBwaXBlbGluZSB0cmFja2VyLgogICAgVHJhY2sgcGxhbm5lZC9pbi1wcm9ncmVzcy9idWlsdCBtb2R1bGVzIGFz"
    "IHRoZXkgYXJlIGRlc2lnbmVkLgogICAgRWFjaCBtb2R1bGUgaGFzOiBOYW1lLCBTdGF0dXMsIERlc2NyaXB0aW9uLCBOb3Rlcy4K"
    "ICAgIEV4cG9ydCB0byBUWFQgZm9yIHBhc3RpbmcgaW50byBzZXNzaW9ucy4KICAgIEltcG9ydDogcGFzdGUgYSBmaW5hbGl6ZWQg"
    "c3BlYywgaXQgcGFyc2VzIG5hbWUgYW5kIGRldGFpbHMuCiAgICBUaGlzIGlzIGEgZGVzaWduIG5vdGVib29rIOKAlCBub3QgY29u"
    "bmVjdGVkIHRvIGRlY2tfYnVpbGRlcidzIE1PRFVMRSByZWdpc3RyeS4KICAgICIiIgoKICAgIFNUQVRVU0VTID0gWyJJZGVhIiwg"
    "IkRlc2lnbmluZyIsICJSZWFkeSB0byBCdWlsZCIsICJQYXJ0aWFsIiwgIkJ1aWx0Il0KCiAgICBkZWYgX19pbml0X18oc2VsZiwg"
    "cGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BhdGggPSBjZmdfcGF0"
    "aCgibWVtb3JpZXMiKSAvICJtb2R1bGVfdHJhY2tlci5qc29ubCIKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0g"
    "W10KICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMo"
    "NCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBCdXR0b24gYmFyCiAgICAgICAgYnRuX2Jh"
    "ciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgID0gX2dvdGhpY19idG4oIkFkZCBNb2R1bGUiKQogICAg"
    "ICAgIHNlbGYuX2J0bl9lZGl0ICAgPSBfZ290aGljX2J0bigiRWRpdCIpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSA9IF9nb3Ro"
    "aWNfYnRuKCJEZWxldGUiKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQgPSBfZ290aGljX2J0bigiRXhwb3J0IFRYVCIpCiAgICAg"
    "ICAgc2VsZi5fYnRuX2ltcG9ydCA9IF9nb3RoaWNfYnRuKCJJbXBvcnQgU3BlYyIpCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0"
    "bl9hZGQsIHNlbGYuX2J0bl9lZGl0LCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fZXhwb3J0"
    "LCBzZWxmLl9idG5faW1wb3J0KToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtV2lkdGgoODApCiAgICAgICAgICAgIGIuc2V0TWlu"
    "aW11bUhlaWdodCgyNikKICAgICAgICAgICAgYnRuX2Jhci5hZGRXaWRnZXQoYikKICAgICAgICBidG5fYmFyLmFkZFN0cmV0Y2go"
    "KQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJ0bl9iYXIpCgogICAgICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNl"
    "bGYuX2RvX2FkZCkKICAgICAgICBzZWxmLl9idG5fZWRpdC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZWRpdCkKICAgICAgICBz"
    "ZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydC5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZXhwb3J0KQogICAgICAgIHNlbGYuX2J0bl9pbXBvcnQuY2xpY2tlZC5jb25uZWN0KHNl"
    "bGYuX2RvX2ltcG9ydCkKCiAgICAgICAgIyBUYWJsZQogICAgICAgIHNlbGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDMpCiAg"
    "ICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIk1vZHVsZSBOYW1lIiwgIlN0YXR1cyIsICJEZXNj"
    "cmlwdGlvbiJdKQogICAgICAgIGhoID0gc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpCiAgICAgICAgaGguc2V0U2VjdGlv"
    "blJlc2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5X"
    "aWR0aCgwLCAxNjApCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhl"
    "ZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgxLCAxMDApCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1v"
    "ZGUoMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2"
    "aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNl"
    "bGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVTaGVldChf"
    "Z290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2VsZi5fdGFibGUuaXRlbVNlbGVjdGlvbkNoYW5nZWQuY29ubmVjdChzZWxm"
    "Ll9vbl9zZWxlY3QpCgogICAgICAgICMgU3BsaXR0ZXIKICAgICAgICBzcGxpdHRlciA9IFFTcGxpdHRlcihRdC5PcmllbnRhdGlv"
    "bi5WZXJ0aWNhbCkKICAgICAgICBzcGxpdHRlci5hZGRXaWRnZXQoc2VsZi5fdGFibGUpCgogICAgICAgICMgTm90ZXMgcGFuZWwK"
    "ICAgICAgICBub3Rlc193aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBub3Rlc19sYXlvdXQgPSBRVkJveExheW91dChub3Rlc193"
    "aWRnZXQpCiAgICAgICAgbm90ZXNfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCA0LCAwLCAwKQogICAgICAgIG5vdGVzX2xh"
    "eW91dC5zZXRTcGFjaW5nKDIpCiAgICAgICAgbm90ZXNfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBOT1RFUyIp"
    "KQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0"
    "UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5LnNldE1pbmltdW1IZWlnaHQoMTIwKQogICAgICAgIHNl"
    "bGYuX25vdGVzX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjog"
    "e0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICkKICAg"
    "ICAgICBub3Rlc19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX25vdGVzX2Rpc3BsYXkpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0"
    "KG5vdGVzX3dpZGdldCkKICAgICAgICBzcGxpdHRlci5zZXRTaXplcyhbMjUwLCAxNTBdKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0"
    "KHNwbGl0dGVyLCAxKQoKICAgICAgICAjIENvdW50IGxhYmVsCiAgICAgICAgc2VsZi5fY291bnRfbGJsID0gUUxhYmVsKCIiKQog"
    "ICAgICAgIHNlbGYuX2NvdW50X2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZv"
    "bnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRX"
    "aWRnZXQoc2VsZi5fY291bnRfbGJsKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3Jk"
    "cyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBy"
    "ZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9IHNlbGYuX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2Vs"
    "Zi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMCwgUVRhYmxlV2lkZ2V0SXRl"
    "bShyZWMuZ2V0KCJuYW1lIiwgIiIpKSkKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQo"
    "InN0YXR1cyIsICJJZGVhIikpCiAgICAgICAgICAgICMgQ29sb3IgYnkgc3RhdHVzCiAgICAgICAgICAgIHN0YXR1c19jb2xvcnMg"
    "PSB7CiAgICAgICAgICAgICAgICAiSWRlYSI6ICAgICAgICAgICAgIENfVEVYVF9ESU0sCiAgICAgICAgICAgICAgICAiRGVzaWdu"
    "aW5nIjogICAgICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgICAgICAiUmVhZHkgdG8gQnVpbGQiOiAgIENfUFVSUExFLAogICAg"
    "ICAgICAgICAgICAgIlBhcnRpYWwiOiAgICAgICAgICAiI2NjODg0NCIsCiAgICAgICAgICAgICAgICAiQnVpbHQiOiAgICAgICAg"
    "ICAgIENfR1JFRU4sCiAgICAgICAgICAgIH0KICAgICAgICAgICAgc3RhdHVzX2l0ZW0uc2V0Rm9yZWdyb3VuZCgKICAgICAgICAg"
    "ICAgICAgIFFDb2xvcihzdGF0dXNfY29sb3JzLmdldChyZWMuZ2V0KCJzdGF0dXMiLCJJZGVhIiksIENfVEVYVF9ESU0pKQogICAg"
    "ICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMSwgc3RhdHVzX2l0ZW0pCiAgICAgICAgICAgIHNl"
    "bGYuX3RhYmxlLnNldEl0ZW0ociwgMiwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiZGVzY3JpcHRp"
    "b24iLCAiIilbOjgwXSkpCiAgICAgICAgY291bnRzID0ge30KICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAg"
    "ICAgICAgIHMgPSByZWMuZ2V0KCJzdGF0dXMiLCAiSWRlYSIpCiAgICAgICAgICAgIGNvdW50c1tzXSA9IGNvdW50cy5nZXQocywg"
    "MCkgKyAxCiAgICAgICAgY291bnRfc3RyID0gIiAgIi5qb2luKGYie3N9OiB7bn0iIGZvciBzLCBuIGluIGNvdW50cy5pdGVtcygp"
    "KQogICAgICAgIHNlbGYuX2NvdW50X2xibC5zZXRUZXh0KAogICAgICAgICAgICBmIlRvdGFsOiB7bGVuKHNlbGYuX3JlY29yZHMp"
    "fSAgIHtjb3VudF9zdHJ9IgogICAgICAgICkKCiAgICBkZWYgX29uX3NlbGVjdChzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9"
    "IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAg"
    "ICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheS5zZXRQbGFpblRleHQo"
    "cmVjLmdldCgibm90ZXMiLCAiIikpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9vcGVuX2Vk"
    "aXRfZGlhbG9nKCkKCiAgICBkZWYgX2RvX2VkaXQoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJy"
    "ZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgc2VsZi5fb3Blbl9l"
    "ZGl0X2RpYWxvZyhzZWxmLl9yZWNvcmRzW3Jvd10sIHJvdykKCiAgICBkZWYgX29wZW5fZWRpdF9kaWFsb2coc2VsZiwgcmVjOiBk"
    "aWN0ID0gTm9uZSwgcm93OiBpbnQgPSAtMSkgLT4gTm9uZToKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxn"
    "LnNldFdpbmRvd1RpdGxlKCJNb2R1bGUiIGlmIG5vdCByZWMgZWxzZSBmIkVkaXQ6IHtyZWMuZ2V0KCduYW1lJywnJyl9IikKICAg"
    "ICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRs"
    "Zy5yZXNpemUoNTQwLCA0NDApCiAgICAgICAgZm9ybSA9IFFWQm94TGF5b3V0KGRsZykKCiAgICAgICAgbmFtZV9maWVsZCA9IFFM"
    "aW5lRWRpdChyZWMuZ2V0KCJuYW1lIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgbmFtZV9maWVsZC5zZXRQbGFjZWhvbGRl"
    "clRleHQoIk1vZHVsZSBuYW1lIikKCiAgICAgICAgc3RhdHVzX2NvbWJvID0gUUNvbWJvQm94KCkKICAgICAgICBzdGF0dXNfY29t"
    "Ym8uYWRkSXRlbXMoc2VsZi5TVEFUVVNFUykKICAgICAgICBpZiByZWM6CiAgICAgICAgICAgIGlkeCA9IHN0YXR1c19jb21iby5m"
    "aW5kVGV4dChyZWMuZ2V0KCJzdGF0dXMiLCJJZGVhIikpCiAgICAgICAgICAgIGlmIGlkeCA+PSAwOgogICAgICAgICAgICAgICAg"
    "c3RhdHVzX2NvbWJvLnNldEN1cnJlbnRJbmRleChpZHgpCgogICAgICAgIGRlc2NfZmllbGQgPSBRTGluZUVkaXQocmVjLmdldCgi"
    "ZGVzY3JpcHRpb24iLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBkZXNjX2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgiT25l"
    "LWxpbmUgZGVzY3JpcHRpb24iKQoKICAgICAgICBub3Rlc19maWVsZCA9IFFUZXh0RWRpdCgpCiAgICAgICAgbm90ZXNfZmllbGQu"
    "c2V0UGxhaW5UZXh0KHJlYy5nZXQoIm5vdGVzIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgbm90ZXNfZmllbGQuc2V0UGxh"
    "Y2Vob2xkZXJUZXh0KAogICAgICAgICAgICAiRnVsbCBub3RlcyDigJQgc3BlYywgaWRlYXMsIHJlcXVpcmVtZW50cywgZWRnZSBj"
    "YXNlcy4uLiIKICAgICAgICApCiAgICAgICAgbm90ZXNfZmllbGQuc2V0TWluaW11bUhlaWdodCgyMDApCgogICAgICAgIGZvciBs"
    "YWJlbCwgd2lkZ2V0IGluIFsKICAgICAgICAgICAgKCJOYW1lOiIsIG5hbWVfZmllbGQpLAogICAgICAgICAgICAoIlN0YXR1czoi"
    "LCBzdGF0dXNfY29tYm8pLAogICAgICAgICAgICAoIkRlc2NyaXB0aW9uOiIsIGRlc2NfZmllbGQpLAogICAgICAgICAgICAoIk5v"
    "dGVzOiIsIG5vdGVzX2ZpZWxkKSwKICAgICAgICBdOgogICAgICAgICAgICByb3dfbGF5b3V0ID0gUUhCb3hMYXlvdXQoKQogICAg"
    "ICAgICAgICBsYmwgPSBRTGFiZWwobGFiZWwpCiAgICAgICAgICAgIGxibC5zZXRGaXhlZFdpZHRoKDkwKQogICAgICAgICAgICBy"
    "b3dfbGF5b3V0LmFkZFdpZGdldChsYmwpCiAgICAgICAgICAgIHJvd19sYXlvdXQuYWRkV2lkZ2V0KHdpZGdldCkKICAgICAgICAg"
    "ICAgZm9ybS5hZGRMYXlvdXQocm93X2xheW91dCkKCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5f"
    "c2F2ZSAgID0gX2dvdGhpY19idG4oIlNhdmUiKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAg"
    "ICAgICBidG5fc2F2ZS5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVj"
    "dChkbGcucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9zYXZlKQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0"
    "KGJ0bl9jYW5jZWwpCiAgICAgICAgZm9ybS5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlh"
    "bG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIG5ld19yZWMgPSB7CiAgICAgICAgICAgICAgICAiaWQiOiAgICAg"
    "ICAgICByZWMuZ2V0KCJpZCIsIHN0cih1dWlkLnV1aWQ0KCkpKSBpZiByZWMgZWxzZSBzdHIodXVpZC51dWlkNCgpKSwKICAgICAg"
    "ICAgICAgICAgICJuYW1lIjogICAgICAgIG5hbWVfZmllbGQudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAic3RhdHVz"
    "IjogICAgICBzdGF0dXNfY29tYm8uY3VycmVudFRleHQoKSwKICAgICAgICAgICAgICAgICJkZXNjcmlwdGlvbiI6IGRlc2NfZmll"
    "bGQudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICBub3Rlc19maWVsZC50b1BsYWluVGV4dCgp"
    "LnN0cmlwKCksCiAgICAgICAgICAgICAgICAiY3JlYXRlZCI6ICAgICByZWMuZ2V0KCJjcmVhdGVkIiwgZGF0ZXRpbWUubm93KCku"
    "aXNvZm9ybWF0KCkpIGlmIHJlYyBlbHNlIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICAgICAgIm1vZGlm"
    "aWVkIjogICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAgICAgICAgIH0KICAgICAgICAgICAgaWYgcm93ID49IDA6"
    "CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd10gPSBuZXdfcmVjCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "ICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChuZXdfcmVjKQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxm"
    "Ll9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jk"
    "cyk6CiAgICAgICAgICAgIG5hbWUgPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJuYW1lIiwidGhpcyBtb2R1bGUiKQogICAgICAg"
    "ICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBNb2R1bGUiLAog"
    "ICAgICAgICAgICAgICAgZiJEZWxldGUgJ3tuYW1lfSc/IENhbm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAgICAgIFFNZXNz"
    "YWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICAgICAgc2VsZi5f"
    "cmVjb3Jkcy5wb3Aocm93KQogICAgICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAg"
    "ICAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19leHBvcnQoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIGV4cG9ydF9kaXIgPSBjZmdfcGF0aCgiZXhwb3J0cyIpCiAgICAgICAgICAgIGV4cG9ydF9kaXIubWtkaXIo"
    "cGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlWSVt"
    "JWRfJUglTSVTIikKICAgICAgICAgICAgb3V0X3BhdGggPSBleHBvcnRfZGlyIC8gZiJtb2R1bGVzX3t0c30udHh0IgogICAgICAg"
    "ICAgICBsaW5lcyA9IFsKICAgICAgICAgICAgICAgICJFQ0hPIERFQ0sg4oCUIE1PRFVMRSBUUkFDS0VSIEVYUE9SVCIsCiAgICAg"
    "ICAgICAgICAgICBmIkV4cG9ydGVkOiB7ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVZLSVtLSVkICVIOiVNOiVTJyl9IiwKICAg"
    "ICAgICAgICAgICAgIGYiVG90YWwgbW9kdWxlczoge2xlbihzZWxmLl9yZWNvcmRzKX0iLAogICAgICAgICAgICAgICAgIj0iICog"
    "NjAsCiAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgXQogICAgICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6"
    "CiAgICAgICAgICAgICAgICBsaW5lcy5leHRlbmQoWwogICAgICAgICAgICAgICAgICAgIGYiTU9EVUxFOiB7cmVjLmdldCgnbmFt"
    "ZScsJycpfSIsCiAgICAgICAgICAgICAgICAgICAgZiJTdGF0dXM6IHtyZWMuZ2V0KCdzdGF0dXMnLCcnKX0iLAogICAgICAgICAg"
    "ICAgICAgICAgIGYiRGVzY3JpcHRpb246IHtyZWMuZ2V0KCdkZXNjcmlwdGlvbicsJycpfSIsCiAgICAgICAgICAgICAgICAgICAg"
    "IiIsCiAgICAgICAgICAgICAgICAgICAgIk5vdGVzOiIsCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgibm90ZXMiLCIiKSwK"
    "ICAgICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgICAgICAgICAiLSIgKiA0MCwKICAgICAgICAgICAgICAgICAgICAi"
    "IiwKICAgICAgICAgICAgICAgIF0pCiAgICAgICAgICAgIG91dF9wYXRoLndyaXRlX3RleHQoIlxuIi5qb2luKGxpbmVzKSwgZW5j"
    "b2Rpbmc9InV0Zi04IikKICAgICAgICAgICAgUUFwcGxpY2F0aW9uLmNsaXBib2FyZCgpLnNldFRleHQoIlxuIi5qb2luKGxpbmVz"
    "KSkKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oCiAgICAgICAgICAgICAgICBzZWxmLCAiRXhwb3J0ZWQiLAog"
    "ICAgICAgICAgICAgICAgZiJNb2R1bGUgdHJhY2tlciBleHBvcnRlZCB0bzpcbntvdXRfcGF0aH1cblxuQWxzbyBjb3BpZWQgdG8g"
    "Y2xpcGJvYXJkLiIKICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgUU1lc3Nh"
    "Z2VCb3gud2FybmluZyhzZWxmLCAiRXhwb3J0IEVycm9yIiwgc3RyKGUpKQoKICAgIGRlZiBfZG9faW1wb3J0KHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgIiIiSW1wb3J0IGEgbW9kdWxlIHNwZWMgZnJvbSBjbGlwYm9hcmQgb3IgdHlwZWQgdGV4dC4iIiIKICAgICAg"
    "ICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJJbXBvcnQgTW9kdWxlIFNwZWMiKQogICAg"
    "ICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxn"
    "LnJlc2l6ZSg1MDAsIDM0MCkKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChkbGcpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdl"
    "dChRTGFiZWwoCiAgICAgICAgICAgICJQYXN0ZSBhIG1vZHVsZSBzcGVjIGJlbG93LlxuIgogICAgICAgICAgICAiRmlyc3QgbGlu"
    "ZSB3aWxsIGJlIHVzZWQgYXMgdGhlIG1vZHVsZSBuYW1lLiIKICAgICAgICApKQogICAgICAgIHRleHRfZmllbGQgPSBRVGV4dEVk"
    "aXQoKQogICAgICAgIHRleHRfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KCJQYXN0ZSBtb2R1bGUgc3BlYyBoZXJlLi4uIikKICAg"
    "ICAgICBsYXlvdXQuYWRkV2lkZ2V0KHRleHRfZmllbGQsIDEpCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBidG5fb2sgICAgID0gX2dvdGhpY19idG4oIkltcG9ydCIpCiAgICAgICAgYnRuX2NhbmNlbCA9IF9nb3RoaWNfYnRuKCJDYW5j"
    "ZWwiKQogICAgICAgIGJ0bl9vay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQu"
    "Y29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9vaykKICAgICAgICBidG5fcm93LmFkZFdp"
    "ZGdldChidG5fY2FuY2VsKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9"
    "PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHJhdyA9IHRleHRfZmllbGQudG9QbGFpblRleHQoKS5z"
    "dHJpcCgpCiAgICAgICAgICAgIGlmIG5vdCByYXc6CiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICAgICAgbGluZXMgPSBy"
    "YXcuc3BsaXRsaW5lcygpCiAgICAgICAgICAgICMgRmlyc3Qgbm9uLWVtcHR5IGxpbmUgPSBuYW1lCiAgICAgICAgICAgIG5hbWUg"
    "PSAiIgogICAgICAgICAgICBmb3IgbGluZSBpbiBsaW5lczoKICAgICAgICAgICAgICAgIGlmIGxpbmUuc3RyaXAoKToKICAgICAg"
    "ICAgICAgICAgICAgICBuYW1lID0gbGluZS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgbmV3"
    "X3JlYyA9IHsKICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAgICAg"
    "Im5hbWUiOiAgICAgICAgbmFtZVs6NjBdLAogICAgICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgIklkZWEiLAogICAgICAgICAg"
    "ICAgICAgImRlc2NyaXB0aW9uIjogIiIsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICByYXcsCiAgICAgICAgICAgICAg"
    "ICAiY3JlYXRlZCI6ICAgICBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgICAgICJtb2RpZmllZCI6ICAg"
    "IGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICB9CiAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5k"
    "KG5ld19yZWMpCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNl"
    "bGYucmVmcmVzaCgpCgoKIyDilIDilIAgUEFTUyA1IENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEFs"
    "bCB0YWIgY29udGVudCBjbGFzc2VzIGRlZmluZWQuCiMgU0xTY2Fuc1RhYjogcmVidWlsdCDigJQgRGVsZXRlIGFkZGVkLCBNb2Rp"
    "ZnkgZml4ZWQsIHRpbWVzdGFtcCBwYXJzZXIgZml4ZWQsCiMgICAgICAgICAgICAgY2FyZC9ncmltb2lyZSBzdHlsZSwgY29weS10"
    "by1jbGlwYm9hcmQgY29udGV4dCBtZW51LgojIFNMQ29tbWFuZHNUYWI6IGdvdGhpYyB0YWJsZSwg4qeJIENvcHkgQ29tbWFuZCBi"
    "dXR0b24uCiMgSm9iVHJhY2tlclRhYjogZnVsbCByZWJ1aWxkIOKAlCBtdWx0aS1zZWxlY3QsIGFyY2hpdmUvcmVzdG9yZSwgQ1NW"
    "L1RTViBleHBvcnQuCiMgU2VsZlRhYjogaW5uZXIgc2FuY3R1bSBmb3IgaWRsZSBuYXJyYXRpdmUgYW5kIHJlZmxlY3Rpb24gb3V0"
    "cHV0LgojIERpYWdub3N0aWNzVGFiOiBzdHJ1Y3R1cmVkIGxvZyB3aXRoIGxldmVsLWNvbG9yZWQgb3V0cHV0LgojIExlc3NvbnNU"
    "YWI6IExTTCBGb3JiaWRkZW4gUnVsZXNldCBicm93c2VyIHdpdGggYWRkL2RlbGV0ZS9zZWFyY2guCiMKIyBOZXh0OiBQYXNzIDYg"
    "4oCUIE1haW4gV2luZG93CiMgKE1vcmdhbm5hRGVjayBjbGFzcywgZnVsbCBsYXlvdXQsIEFQU2NoZWR1bGVyLCBmaXJzdC1ydW4g"
    "ZmxvdywKIyAgZGVwZW5kZW5jeSBib290c3RyYXAsIHNob3J0Y3V0IGNyZWF0aW9uLCBzdGFydHVwIHNlcXVlbmNlKQoKCiMg4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyA2OiBNQUlOIFdJTkRPVyAmIEVOVFJZIFBPSU5UCiMKIyBDb250YWlu"
    "czoKIyAgIGJvb3RzdHJhcF9jaGVjaygpICAgICDigJQgZGVwZW5kZW5jeSB2YWxpZGF0aW9uICsgYXV0by1pbnN0YWxsIGJlZm9y"
    "ZSBVSQojICAgRmlyc3RSdW5EaWFsb2cgICAgICAgIOKAlCBtb2RlbCBwYXRoICsgY29ubmVjdGlvbiB0eXBlIHNlbGVjdGlvbgoj"
    "ICAgSm91cm5hbFNpZGViYXIgICAgICAgIOKAlCBjb2xsYXBzaWJsZSBsZWZ0IHNpZGViYXIgKHNlc3Npb24gYnJvd3NlciArIGpv"
    "dXJuYWwpCiMgICBUb3Jwb3JQYW5lbCAgICAgICAgICAg4oCUIEFXQUtFIC8gQVVUTyAvIFNVU1BFTkQgc3RhdGUgdG9nZ2xlCiMg"
    "ICBNb3JnYW5uYURlY2sgICAgICAgICAg4oCUIG1haW4gd2luZG93LCBmdWxsIGxheW91dCwgYWxsIHNpZ25hbCBjb25uZWN0aW9u"
    "cwojICAgbWFpbigpICAgICAgICAgICAgICAgIOKAlCBlbnRyeSBwb2ludCB3aXRoIGJvb3RzdHJhcCBzZXF1ZW5jZQojIOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkAoKaW1wb3J0IHN1YnByb2Nlc3MKCgojIOKUgOKUgCBQUkUtTEFVTkNIIERFUEVOREVOQ1kgQk9PVFNUUkFQIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgYm9vdHN0cmFwX2NoZWNrKCkgLT4gTm9u"
    "ZToKICAgICIiIgogICAgUnVucyBCRUZPUkUgUUFwcGxpY2F0aW9uIGlzIGNyZWF0ZWQuCiAgICBDaGVja3MgZm9yIFB5U2lkZTYg"
    "c2VwYXJhdGVseSAoY2FuJ3Qgc2hvdyBHVUkgd2l0aG91dCBpdCkuCiAgICBBdXRvLWluc3RhbGxzIGFsbCBvdGhlciBtaXNzaW5n"
    "IG5vbi1jcml0aWNhbCBkZXBzIHZpYSBwaXAuCiAgICBWYWxpZGF0ZXMgaW5zdGFsbHMgc3VjY2VlZGVkLgogICAgV3JpdGVzIHJl"
    "c3VsdHMgdG8gYSBib290c3RyYXAgbG9nIGZvciBEaWFnbm9zdGljcyB0YWIgdG8gcGljayB1cC4KICAgICIiIgogICAgIyDilIDi"
    "lIAgU3RlcCAxOiBDaGVjayBQeVNpZGU2IChjYW4ndCBhdXRvLWluc3RhbGwgd2l0aG91dCBpdCBhbHJlYWR5IHByZXNlbnQpIOKU"
    "gAogICAgdHJ5OgogICAgICAgIGltcG9ydCBQeVNpZGU2ICAjIG5vcWEKICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAj"
    "IE5vIEdVSSBhdmFpbGFibGUg4oCUIHVzZSBXaW5kb3dzIG5hdGl2ZSBkaWFsb2cgdmlhIGN0eXBlcwogICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgaW1wb3J0IGN0eXBlcwogICAgICAgICAgICBjdHlwZXMud2luZGxsLnVzZXIzMi5NZXNzYWdlQm94VygKICAgICAg"
    "ICAgICAgICAgIDAsCiAgICAgICAgICAgICAgICAiUHlTaWRlNiBpcyByZXF1aXJlZCBidXQgbm90IGluc3RhbGxlZC5cblxuIgog"
    "ICAgICAgICAgICAgICAgIk9wZW4gYSB0ZXJtaW5hbCBhbmQgcnVuOlxuXG4iCiAgICAgICAgICAgICAgICAiICAgIHBpcCBpbnN0"
    "YWxsIFB5U2lkZTZcblxuIgogICAgICAgICAgICAgICAgZiJUaGVuIHJlc3RhcnQge0RFQ0tfTkFNRX0uIiwKICAgICAgICAgICAg"
    "ICAgIGYie0RFQ0tfTkFNRX0g4oCUIE1pc3NpbmcgRGVwZW5kZW5jeSIsCiAgICAgICAgICAgICAgICAweDEwICAjIE1CX0lDT05F"
    "UlJPUgogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcHJpbnQoIkNSSVRJQ0FMOiBQ"
    "eVNpZGU2IG5vdCBpbnN0YWxsZWQuIFJ1bjogcGlwIGluc3RhbGwgUHlTaWRlNiIpCiAgICAgICAgc3lzLmV4aXQoMSkKCiAgICAj"
    "IOKUgOKUgCBTdGVwIDI6IEF1dG8taW5zdGFsbCBvdGhlciBtaXNzaW5nIGRlcHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBf"
    "QVVUT19JTlNUQUxMID0gWwogICAgICAgICgiYXBzY2hlZHVsZXIiLCAgICAgICAgICAgICAgICJhcHNjaGVkdWxlciIpLAogICAg"
    "ICAgICgibG9ndXJ1IiwgICAgICAgICAgICAgICAgICAgICJsb2d1cnUiKSwKICAgICAgICAoInB5Z2FtZSIsICAgICAgICAgICAg"
    "ICAgICAgICAicHlnYW1lIiksCiAgICAgICAgKCJweXdpbjMyIiwgICAgICAgICAgICAgICAgICAgInB5d2luMzIiKSwKICAgICAg"
    "ICAoInBzdXRpbCIsICAgICAgICAgICAgICAgICAgICAicHN1dGlsIiksCiAgICAgICAgKCJyZXF1ZXN0cyIsICAgICAgICAgICAg"
    "ICAgICAgInJlcXVlc3RzIiksCiAgICAgICAgKCJnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQiLCAgImdvb2dsZWFwaWNsaWVudCIp"
    "LAogICAgICAgICgiZ29vZ2xlLWF1dGgtb2F1dGhsaWIiLCAgICAgICJnb29nbGVfYXV0aF9vYXV0aGxpYiIpLAogICAgICAgICgi"
    "Z29vZ2xlLWF1dGgiLCAgICAgICAgICAgICAgICJnb29nbGUuYXV0aCIpLAogICAgXQoKICAgIGltcG9ydCBpbXBvcnRsaWIKICAg"
    "IGJvb3RzdHJhcF9sb2cgPSBbXQoKICAgIGZvciBwaXBfbmFtZSwgaW1wb3J0X25hbWUgaW4gX0FVVE9fSU5TVEFMTDoKICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9ydF9uYW1lKQogICAgICAgICAgICBib290c3Ry"
    "YXBfbG9nLmFwcGVuZChmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0g4pyTIikKICAgICAgICBleGNlcHQgSW1wb3J0RXJyb3I6CiAg"
    "ICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IG1p"
    "c3Npbmcg4oCUIGluc3RhbGxpbmcuLi4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgcmVz"
    "dWx0ID0gc3VicHJvY2Vzcy5ydW4oCiAgICAgICAgICAgICAgICAgICAgW3N5cy5leGVjdXRhYmxlLCAiLW0iLCAicGlwIiwgImlu"
    "c3RhbGwiLAogICAgICAgICAgICAgICAgICAgICBwaXBfbmFtZSwgIi0tcXVpZXQiLCAiLS1uby13YXJuLXNjcmlwdC1sb2NhdGlv"
    "biJdLAogICAgICAgICAgICAgICAgICAgIGNhcHR1cmVfb3V0cHV0PVRydWUsIHRleHQ9VHJ1ZSwgdGltZW91dD0xMjAKICAgICAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIHJlc3VsdC5yZXR1cm5jb2RlID09IDA6CiAgICAgICAgICAgICAgICAgICAg"
    "IyBWYWxpZGF0ZSBpdCBhY3R1YWxseSBpbXBvcnRlZCBub3cKICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9ydF9uYW1lKQogICAgICAgICAgICAgICAgICAgICAgICBib290"
    "c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0"
    "YWxsZWQg4pyTIgogICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgZXhjZXB0IEltcG9ydEVycm9y"
    "OgogICAgICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsIGFwcGVhcmVkIHRvICIKICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IGYic3VjY2VlZCBidXQgaW1wb3J0IHN0aWxsIGZhaWxzIOKAlCByZXN0YXJ0IG1heSAiCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICBmImJlIHJlcXVpcmVkLiIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAg"
    "ICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7"
    "cGlwX25hbWV9IGluc3RhbGwgZmFpbGVkOiAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYie3Jlc3VsdC5zdGRlcnJbOjIwMF19"
    "IgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IHN1YnByb2Nlc3MuVGltZW91dEV4cGlyZWQ6CiAgICAg"
    "ICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFt"
    "ZX0gaW5zdGFsbCB0aW1lZCBvdXQuIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6"
    "CiAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtw"
    "aXBfbmFtZX0gaW5zdGFsbCBlcnJvcjoge2V9IgogICAgICAgICAgICAgICAgKQoKICAgICMg4pSA4pSAIFN0ZXAgMzogV3JpdGUg"
    "Ym9vdHN0cmFwIGxvZyBmb3IgRGlhZ25vc3RpY3MgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgdHJ5OgogICAgICAgIGxvZ19wYXRoID0gU0NSSVBUX0RJUiAvICJsb2dz"
    "IiAvICJib290c3RyYXBfbG9nLnR4dCIKICAgICAgICB3aXRoIGxvZ19wYXRoLm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBh"
    "cyBmOgogICAgICAgICAgICBmLndyaXRlKCJcbiIuam9pbihib290c3RyYXBfbG9nKSkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAg"
    "ICAgICAgcGFzcwoKCiMg4pSA4pSAIEZJUlNUIFJVTiBESUFMT0cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEZpcnN0"
    "UnVuRGlhbG9nKFFEaWFsb2cpOgogICAgIiIiCiAgICBTaG93biBvbiBmaXJzdCBsYXVuY2ggd2hlbiBjb25maWcuanNvbiBkb2Vz"
    "bid0IGV4aXN0LgogICAgQ29sbGVjdHMgbW9kZWwgY29ubmVjdGlvbiB0eXBlIGFuZCBwYXRoL2tleS4KICAgIFZhbGlkYXRlcyBj"
    "b25uZWN0aW9uIGJlZm9yZSBhY2NlcHRpbmcuCiAgICBXcml0ZXMgY29uZmlnLmpzb24gb24gc3VjY2Vzcy4KICAgIENyZWF0ZXMg"
    "ZGVza3RvcCBzaG9ydGN1dC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3Vw"
    "ZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5zZXRXaW5kb3dUaXRsZShmIuKcpiB7REVDS19OQU1FLnVwcGVyKCl9"
    "IOKAlCBGSVJTVCBBV0FLRU5JTkciKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldChTVFlMRSkKICAgICAgICBzZWxmLnNldEZp"
    "eGVkU2l6ZSg1MjAsIDQwMCkKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0U3BhY2luZygxMCkKCiAgICAgICAgdGl0"
    "bGUgPSBRTGFiZWwoZiLinKYge0RFQ0tfTkFNRS51cHBlcigpfSDigJQgRklSU1QgQVdBS0VOSU5HIOKcpiIpCiAgICAgICAgdGl0"
    "bGUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTRweDsgZm9udC13"
    "ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2lu"
    "ZzogMnB4OyIKICAgICAgICApCiAgICAgICAgdGl0bGUuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIp"
    "CiAgICAgICAgcm9vdC5hZGRXaWRnZXQodGl0bGUpCgogICAgICAgIHN1YiA9IFFMYWJlbCgKICAgICAgICAgICAgZiJDb25maWd1"
    "cmUgdGhlIHZlc3NlbCBiZWZvcmUge0RFQ0tfTkFNRX0gbWF5IGF3YWtlbi5cbiIKICAgICAgICAgICAgIkFsbCBzZXR0aW5ncyBh"
    "cmUgc3RvcmVkIGxvY2FsbHkuIE5vdGhpbmcgbGVhdmVzIHRoaXMgbWFjaGluZS4iCiAgICAgICAgKQogICAgICAgIHN1Yi5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgIgogICAgICAgICAg"
    "ICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBzdWIuc2V0QWxpZ25tZW50KFF0"
    "LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc3ViKQoKICAgICAgICAjIOKUgOKUgCBD"
    "b25uZWN0aW9uIHR5cGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgcm9vdC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgQUkgQ09OTkVDVElPTiBUWVBFIikpCiAgICAgICAgc2VsZi5f"
    "dHlwZV9jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc2VsZi5fdHlwZV9jb21iby5hZGRJdGVtcyhbCiAgICAgICAgICAgICJM"
    "b2NhbCBtb2RlbCBmb2xkZXIgKHRyYW5zZm9ybWVycykiLAogICAgICAgICAgICAiT2xsYW1hIChsb2NhbCBzZXJ2aWNlKSIsCiAg"
    "ICAgICAgICAgICJDbGF1ZGUgQVBJIChBbnRocm9waWMpIiwKICAgICAgICAgICAgIk9wZW5BSSBBUEkiLAogICAgICAgIF0pCiAg"
    "ICAgICAgc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXhDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fdHlwZV9jaGFuZ2UpCiAg"
    "ICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdHlwZV9jb21ibykKCiAgICAgICAgIyDilIDilIAgRHluYW1pYyBjb25uZWN0aW9u"
    "IGZpZWxkcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zdGFjayA9IFFTdGFja2VkV2lkZ2V0KCkK"
    "CiAgICAgICAgIyBQYWdlIDA6IExvY2FsIHBhdGgKICAgICAgICBwMCA9IFFXaWRnZXQoKQogICAgICAgIGwwID0gUUhCb3hMYXlv"
    "dXQocDApCiAgICAgICAgbDAuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fbG9jYWxfcGF0aCA9IFFM"
    "aW5lRWRpdCgpCiAgICAgICAgc2VsZi5fbG9jYWxfcGF0aC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgIHIiRDpcQUlc"
    "TW9kZWxzXGRvbHBoaW4tOGIiCiAgICAgICAgKQogICAgICAgIGJ0bl9icm93c2UgPSBfZ290aGljX2J0bigiQnJvd3NlIikKICAg"
    "ICAgICBidG5fYnJvd3NlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9icm93c2VfbW9kZWwpCiAgICAgICAgbDAuYWRkV2lkZ2V0KHNl"
    "bGYuX2xvY2FsX3BhdGgpOyBsMC5hZGRXaWRnZXQoYnRuX2Jyb3dzZSkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDAp"
    "CgogICAgICAgICMgUGFnZSAxOiBPbGxhbWEgbW9kZWwgbmFtZQogICAgICAgIHAxID0gUVdpZGdldCgpCiAgICAgICAgbDEgPSBR"
    "SEJveExheW91dChwMSkKICAgICAgICBsMS5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAsMCkKICAgICAgICBzZWxmLl9vbGxhbWFf"
    "bW9kZWwgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX29sbGFtYV9tb2RlbC5zZXRQbGFjZWhvbGRlclRleHQoImRvbHBoaW4t"
    "Mi42LTdiIikKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fb2xsYW1hX21vZGVsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdp"
    "ZGdldChwMSkKCiAgICAgICAgIyBQYWdlIDI6IENsYXVkZSBBUEkga2V5CiAgICAgICAgcDIgPSBRV2lkZ2V0KCkKICAgICAgICBs"
    "MiA9IFFWQm94TGF5b3V0KHAyKQogICAgICAgIGwyLnNldENvbnRlbnRzTWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX2Ns"
    "YXVkZV9rZXkgICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fY2xhdWRlX2tleS5zZXRQbGFjZWhvbGRlclRleHQoInNrLWFu"
    "dC0uLi4iKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkuc2V0RWNob01vZGUoUUxpbmVFZGl0LkVjaG9Nb2RlLlBhc3N3b3JkKQog"
    "ICAgICAgIHNlbGYuX2NsYXVkZV9tb2RlbCA9IFFMaW5lRWRpdCgiY2xhdWRlLXNvbm5ldC00LTYiKQogICAgICAgIGwyLmFkZFdp"
    "ZGdldChRTGFiZWwoIkFQSSBLZXk6IikpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2NsYXVkZV9rZXkpCiAgICAgICAgbDIu"
    "YWRkV2lkZ2V0KFFMYWJlbCgiTW9kZWw6IikpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2NsYXVkZV9tb2RlbCkKICAgICAg"
    "ICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDIpCgogICAgICAgICMgUGFnZSAzOiBPcGVuQUkKICAgICAgICBwMyA9IFFXaWRnZXQo"
    "KQogICAgICAgIGwzID0gUVZCb3hMYXlvdXQocDMpCiAgICAgICAgbDMuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAg"
    "ICAgc2VsZi5fb2FpX2tleSAgID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9vYWlfa2V5LnNldFBsYWNlaG9sZGVyVGV4dCgi"
    "c2stLi4uIikKICAgICAgICBzZWxmLl9vYWlfa2V5LnNldEVjaG9Nb2RlKFFMaW5lRWRpdC5FY2hvTW9kZS5QYXNzd29yZCkKICAg"
    "ICAgICBzZWxmLl9vYWlfbW9kZWwgPSBRTGluZUVkaXQoImdwdC00byIpCiAgICAgICAgbDMuYWRkV2lkZ2V0KFFMYWJlbCgiQVBJ"
    "IEtleToiKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fb2FpX2tleSkKICAgICAgICBsMy5hZGRXaWRnZXQoUUxhYmVsKCJN"
    "b2RlbDoiKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fb2FpX21vZGVsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdl"
    "dChwMykKCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fc3RhY2spCgogICAgICAgICMg4pSA4pSAIFRlc3QgKyBzdGF0dXMg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgdGVz"
    "dF9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX3Rlc3QgPSBfZ290aGljX2J0bigiVGVzdCBDb25uZWN0aW9u"
    "IikKICAgICAgICBzZWxmLl9idG5fdGVzdC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdGVzdF9jb25uZWN0aW9uKQogICAgICAgIHNl"
    "bGYuX3N0YXR1c19sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7"
    "REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICB0ZXN0X3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX3Rlc3QpCiAg"
    "ICAgICAgdGVzdF9yb3cuYWRkV2lkZ2V0KHNlbGYuX3N0YXR1c19sYmwsIDEpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQodGVzdF9y"
    "b3cpCgogICAgICAgICMg4pSA4pSAIEZhY2UgUGFjayDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICByb290LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBG"
    "QUNFIFBBQ0sgKG9wdGlvbmFsIOKAlCBaSVAgZmlsZSkiKSkKICAgICAgICBmYWNlX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBzZWxmLl9mYWNlX3BhdGggPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2ZhY2VfcGF0aC5zZXRQbGFjZWhvbGRlclRleHQo"
    "CiAgICAgICAgICAgIGYiQnJvd3NlIHRvIHtERUNLX05BTUV9IGZhY2UgcGFjayBaSVAgKG9wdGlvbmFsLCBjYW4gYWRkIGxhdGVy"
    "KSIKICAgICAgICApCiAgICAgICAgc2VsZi5fZmFjZV9wYXRoLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3Vu"
    "ZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRF"
    "Un07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZv"
    "bnQtc2l6ZTogMTJweDsgcGFkZGluZzogNnB4IDEwcHg7IgogICAgICAgICkKICAgICAgICBidG5fZmFjZSA9IF9nb3RoaWNfYnRu"
    "KCJCcm93c2UiKQogICAgICAgIGJ0bl9mYWNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9icm93c2VfZmFjZSkKICAgICAgICBmYWNl"
    "X3Jvdy5hZGRXaWRnZXQoc2VsZi5fZmFjZV9wYXRoKQogICAgICAgIGZhY2Vfcm93LmFkZFdpZGdldChidG5fZmFjZSkKICAgICAg"
    "ICByb290LmFkZExheW91dChmYWNlX3JvdykKCiAgICAgICAgIyDilIDilIAgU2hvcnRjdXQgb3B0aW9uIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3Nob3J0Y3V0X2NiID0gUUNo"
    "ZWNrQm94KAogICAgICAgICAgICAiQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgKHJlY29tbWVuZGVkKSIKICAgICAgICApCiAgICAg"
    "ICAgc2VsZi5fc2hvcnRjdXRfY2Iuc2V0Q2hlY2tlZChUcnVlKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3Nob3J0Y3V0"
    "X2NiKQoKICAgICAgICAjIOKUgOKUgCBCdXR0b25zIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHJvb3QuYWRkU3RyZXRjaCgpCiAgICAgICAgYnRu"
    "X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYXdha2VuID0gX2dvdGhpY19idG4oIuKcpiBCRUdJTiBBV0FL"
    "RU5JTkciKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBidG5fY2FuY2VsID0gX2dv"
    "dGhpY19idG4oIuKclyBDYW5jZWwiKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uY2xpY2tlZC5jb25uZWN0KHNlbGYuYWNjZXB0"
    "KQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0"
    "KHNlbGYuX2J0bl9hd2FrZW4pCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICByb290LmFkZExh"
    "eW91dChidG5fcm93KQoKICAgIGRlZiBfb25fdHlwZV9jaGFuZ2Uoc2VsZiwgaWR4OiBpbnQpIC0+IE5vbmU6CiAgICAgICAgc2Vs"
    "Zi5fc3RhY2suc2V0Q3VycmVudEluZGV4KGlkeCkKICAgICAgICBzZWxmLl9idG5fYXdha2VuLnNldEVuYWJsZWQoRmFsc2UpCiAg"
    "ICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRUZXh0KCIiKQoKICAgIGRlZiBfYnJvd3NlX21vZGVsKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgcGF0aCA9IFFGaWxlRGlhbG9nLmdldEV4aXN0aW5nRGlyZWN0b3J5KAogICAgICAgICAgICBzZWxmLCAiU2VsZWN0IE1v"
    "ZGVsIEZvbGRlciIsCiAgICAgICAgICAgIHIiRDpcQUlcTW9kZWxzIgogICAgICAgICkKICAgICAgICBpZiBwYXRoOgogICAgICAg"
    "ICAgICBzZWxmLl9sb2NhbF9wYXRoLnNldFRleHQocGF0aCkKCiAgICBkZWYgX2Jyb3dzZV9mYWNlKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgcGF0aCwgXyA9IFFGaWxlRGlhbG9nLmdldE9wZW5GaWxlTmFtZSgKICAgICAgICAgICAgc2VsZiwgIlNlbGVjdCBGYWNl"
    "IFBhY2sgWklQIiwKICAgICAgICAgICAgc3RyKFBhdGguaG9tZSgpIC8gIkRlc2t0b3AiKSwKICAgICAgICAgICAgIlpJUCBGaWxl"
    "cyAoKi56aXApIgogICAgICAgICkKICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICBzZWxmLl9mYWNlX3BhdGguc2V0VGV4dChw"
    "YXRoKQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGZhY2VfemlwX3BhdGgoc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxm"
    "Ll9mYWNlX3BhdGgudGV4dCgpLnN0cmlwKCkKCiAgICBkZWYgX3Rlc3RfY29ubmVjdGlvbihzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYuX3N0YXR1c19sYmwuc2V0VGV4dCgiVGVzdGluZy4uLiIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNL"
    "X0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIFFBcHBsaWNhdGlvbi5wcm9jZXNzRXZlbnRzKCkKCiAgICAgICAgaWR4"
    "ID0gc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXgoKQogICAgICAgIG9rICA9IEZhbHNlCiAgICAgICAgbXNnID0gIiIKCiAg"
    "ICAgICAgaWYgaWR4ID09IDA6ICAjIExvY2FsCiAgICAgICAgICAgIHBhdGggPSBzZWxmLl9sb2NhbF9wYXRoLnRleHQoKS5zdHJp"
    "cCgpCiAgICAgICAgICAgIGlmIHBhdGggYW5kIFBhdGgocGF0aCkuZXhpc3RzKCk6CiAgICAgICAgICAgICAgICBvayAgPSBUcnVl"
    "CiAgICAgICAgICAgICAgICBtc2cgPSBmIkZvbGRlciBmb3VuZC4gTW9kZWwgd2lsbCBsb2FkIG9uIHN0YXJ0dXAuIgogICAgICAg"
    "ICAgICBlbHNlOgogICAgICAgICAgICAgICAgbXNnID0gIkZvbGRlciBub3QgZm91bmQuIENoZWNrIHRoZSBwYXRoLiIKCiAgICAg"
    "ICAgZWxpZiBpZHggPT0gMTogICMgT2xsYW1hCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJlcSAgPSB1cmxsaWIu"
    "cmVxdWVzdC5SZXF1ZXN0KAogICAgICAgICAgICAgICAgICAgICJodHRwOi8vbG9jYWxob3N0OjExNDM0L2FwaS90YWdzIgogICAg"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgcmVzcCA9IHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTMp"
    "CiAgICAgICAgICAgICAgICBvayAgID0gcmVzcC5zdGF0dXMgPT0gMjAwCiAgICAgICAgICAgICAgICBtc2cgID0gIk9sbGFtYSBp"
    "cyBydW5uaW5nIOKckyIgaWYgb2sgZWxzZSAiT2xsYW1hIG5vdCByZXNwb25kaW5nLiIKICAgICAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbiBhcyBlOgogICAgICAgICAgICAgICAgbXNnID0gZiJPbGxhbWEgbm90IHJlYWNoYWJsZToge2V9IgoKICAgICAgICBlbGlm"
    "IGlkeCA9PSAyOiAgIyBDbGF1ZGUKICAgICAgICAgICAga2V5ID0gc2VsZi5fY2xhdWRlX2tleS50ZXh0KCkuc3RyaXAoKQogICAg"
    "ICAgICAgICBvayAgPSBib29sKGtleSBhbmQga2V5LnN0YXJ0c3dpdGgoInNrLWFudCIpKQogICAgICAgICAgICBtc2cgPSAiQVBJ"
    "IGtleSBmb3JtYXQgbG9va3MgY29ycmVjdC4iIGlmIG9rIGVsc2UgIkVudGVyIGEgdmFsaWQgQ2xhdWRlIEFQSSBrZXkuIgoKICAg"
    "ICAgICBlbGlmIGlkeCA9PSAzOiAgIyBPcGVuQUkKICAgICAgICAgICAga2V5ID0gc2VsZi5fb2FpX2tleS50ZXh0KCkuc3RyaXAo"
    "KQogICAgICAgICAgICBvayAgPSBib29sKGtleSBhbmQga2V5LnN0YXJ0c3dpdGgoInNrLSIpKQogICAgICAgICAgICBtc2cgPSAi"
    "QVBJIGtleSBmb3JtYXQgbG9va3MgY29ycmVjdC4iIGlmIG9rIGVsc2UgIkVudGVyIGEgdmFsaWQgT3BlbkFJIEFQSSBrZXkuIgoK"
    "ICAgICAgICBjb2xvciA9IENfR1JFRU4gaWYgb2sgZWxzZSBDX0NSSU1TT04KICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFRl"
    "eHQobXNnKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge2NvbG9y"
    "fTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2Vs"
    "Zi5fYnRuX2F3YWtlbi5zZXRFbmFibGVkKG9rKQoKICAgIGRlZiBidWlsZF9jb25maWcoc2VsZikgLT4gZGljdDoKICAgICAgICAi"
    "IiJCdWlsZCBhbmQgcmV0dXJuIHVwZGF0ZWQgY29uZmlnIGRpY3QgZnJvbSBkaWFsb2cgc2VsZWN0aW9ucy4iIiIKICAgICAgICBj"
    "ZmcgICAgID0gX2RlZmF1bHRfY29uZmlnKCkKICAgICAgICBpZHggICAgID0gc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXgo"
    "KQogICAgICAgIHR5cGVzICAgPSBbImxvY2FsIiwgIm9sbGFtYSIsICJjbGF1ZGUiLCAib3BlbmFpIl0KICAgICAgICBjZmdbIm1v"
    "ZGVsIl1bInR5cGUiXSA9IHR5cGVzW2lkeF0KCiAgICAgICAgaWYgaWR4ID09IDA6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsi"
    "cGF0aCJdID0gc2VsZi5fbG9jYWxfcGF0aC50ZXh0KCkuc3RyaXAoKQogICAgICAgIGVsaWYgaWR4ID09IDE6CiAgICAgICAgICAg"
    "IGNmZ1sibW9kZWwiXVsib2xsYW1hX21vZGVsIl0gPSBzZWxmLl9vbGxhbWFfbW9kZWwudGV4dCgpLnN0cmlwKCkgb3IgImRvbHBo"
    "aW4tMi42LTdiIgogICAgICAgIGVsaWYgaWR4ID09IDI6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX2tleSJdICAgPSBz"
    "ZWxmLl9jbGF1ZGVfa2V5LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX21vZGVsIl0gPSBzZWxm"
    "Ll9jbGF1ZGVfbW9kZWwudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfdHlwZSJdICA9ICJjbGF1"
    "ZGUiCiAgICAgICAgZWxpZiBpZHggPT0gMzoKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfa2V5Il0gICA9IHNlbGYuX29h"
    "aV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfbW9kZWwiXSA9IHNlbGYuX29haV9tb2Rl"
    "bC50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV90eXBlIl0gID0gIm9wZW5haSIKCiAgICAgICAg"
    "Y2ZnWyJmaXJzdF9ydW4iXSA9IEZhbHNlCiAgICAgICAgcmV0dXJuIGNmZwoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGNyZWF0ZV9z"
    "aG9ydGN1dChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBzZWxmLl9zaG9ydGN1dF9jYi5pc0NoZWNrZWQoKQoKCiMg4pSA"
    "4pSAIEpPVVJOQUwgU0lERUJBUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSm91cm5hbFNpZGViYXIoUVdpZGdl"
    "dCk6CiAgICAiIiIKICAgIENvbGxhcHNpYmxlIGxlZnQgc2lkZWJhciBuZXh0IHRvIHRoZSBwZXJzb25hIGNoYXQgdGFiLgogICAg"
    "VG9wOiBzZXNzaW9uIGNvbnRyb2xzIChjdXJyZW50IHNlc3Npb24gbmFtZSwgc2F2ZS9sb2FkIGJ1dHRvbnMsCiAgICAgICAgIGF1"
    "dG9zYXZlIGluZGljYXRvcikuCiAgICBCb2R5OiBzY3JvbGxhYmxlIHNlc3Npb24gbGlzdCDigJQgZGF0ZSwgQUkgbmFtZSwgbWVz"
    "c2FnZSBjb3VudC4KICAgIENvbGxhcHNlcyBsZWZ0d2FyZCB0byBhIHRoaW4gc3RyaXAuCgogICAgU2lnbmFsczoKICAgICAgICBz"
    "ZXNzaW9uX2xvYWRfcmVxdWVzdGVkKHN0cikgICDigJQgZGF0ZSBzdHJpbmcgb2Ygc2Vzc2lvbiB0byBsb2FkCiAgICAgICAgc2Vz"
    "c2lvbl9jbGVhcl9yZXF1ZXN0ZWQoKSAgICAg4oCUIHJldHVybiB0byBjdXJyZW50IHNlc3Npb24KICAgICIiIgoKICAgIHNlc3Np"
    "b25fbG9hZF9yZXF1ZXN0ZWQgID0gU2lnbmFsKHN0cikKICAgIHNlc3Npb25fY2xlYXJfcmVxdWVzdGVkID0gU2lnbmFsKCkKCiAg"
    "ICBkZWYgX19pbml0X18oc2VsZiwgc2Vzc2lvbl9tZ3I6ICJTZXNzaW9uTWFuYWdlciIsIHBhcmVudD1Ob25lKToKICAgICAgICBz"
    "dXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9zZXNzaW9uX21nciA9IHNlc3Npb25fbWdyCiAgICAgICAgc2Vs"
    "Zi5fZXhwYW5kZWQgICAgPSBUcnVlCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAg"
    "ZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgICMgVXNlIGEgaG9yaXpvbnRhbCByb290IGxheW91dCDigJQgY29u"
    "dGVudCBvbiBsZWZ0LCB0b2dnbGUgc3RyaXAgb24gcmlnaHQKICAgICAgICByb290ID0gUUhCb3hMYXlvdXQoc2VsZikKICAgICAg"
    "ICByb290LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHJvb3Quc2V0U3BhY2luZygwKQoKICAgICAgICAj"
    "IOKUgOKUgCBDb2xsYXBzZSB0b2dnbGUgc3RyaXAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgc2VsZi5fdG9nZ2xlX3N0cmlwID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fdG9nZ2xlX3N0cmlwLnNldEZpeGVkV2lkdGgo"
    "MjApCiAgICAgICAgc2VsZi5fdG9nZ2xlX3N0cmlwLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0Nf"
    "QkczfTsgYm9yZGVyLXJpZ2h0OiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgdHNfbGF5b3V0"
    "ID0gUVZCb3hMYXlvdXQoc2VsZi5fdG9nZ2xlX3N0cmlwKQogICAgICAgIHRzX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwg"
    "OCwgMCwgOCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4u"
    "c2V0Rml4ZWRTaXplKDE4LCAxOCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKXgCIpCiAgICAgICAgc2VsZi5f"
    "dG9nZ2xlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHRyYW5zcGFyZW50OyBjb2xvcjoge0Nf"
    "R09MRF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiBub25lOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl90b2dnbGVfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCiAgICAgICAgdHNfbGF5b3V0LmFkZFdpZGdl"
    "dChzZWxmLl90b2dnbGVfYnRuKQogICAgICAgIHRzX2xheW91dC5hZGRTdHJldGNoKCkKCiAgICAgICAgIyDilIDilIAgTWFpbiBj"
    "b250ZW50IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgICAgIHNlbGYuX2NvbnRlbnQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jb250ZW50LnNldE1pbmltdW1XaWR0aCgxODAp"
    "CiAgICAgICAgc2VsZi5fY29udGVudC5zZXRNYXhpbXVtV2lkdGgoMjIwKQogICAgICAgIGNvbnRlbnRfbGF5b3V0ID0gUVZCb3hM"
    "YXlvdXQoc2VsZi5fY29udGVudCkKICAgICAgICBjb250ZW50X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkK"
    "ICAgICAgICBjb250ZW50X2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgU2VjdGlvbiBsYWJlbAogICAgICAgIGNvbnRl"
    "bnRfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBKT1VSTkFMIikpCgogICAgICAgICMgQ3VycmVudCBzZXNzaW9u"
    "IGluZm8KICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUgPSBRTGFiZWwoIk5ldyBTZXNzaW9uIikKICAgICAgICBzZWxmLl9zZXNz"
    "aW9uX25hbWUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogMTBweDsgZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgIgogICAgICAgICAgICBmImZvbnQtc3R5bGU6IGl0YWxpYzsiCiAgICAgICAg"
    "KQogICAgICAgIHNlbGYuX3Nlc3Npb25fbmFtZS5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdp"
    "ZGdldChzZWxmLl9zZXNzaW9uX25hbWUpCgogICAgICAgICMgU2F2ZSAvIExvYWQgcm93CiAgICAgICAgY3RybF9yb3cgPSBRSEJv"
    "eExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUgPSBfZ290aGljX2J0bigi8J+SviIpCiAgICAgICAgc2VsZi5fYnRuX3Nh"
    "dmUuc2V0Rml4ZWRTaXplKDMyLCAyNCkKICAgICAgICBzZWxmLl9idG5fc2F2ZS5zZXRUb29sVGlwKCJTYXZlIHNlc3Npb24gbm93"
    "IikKICAgICAgICBzZWxmLl9idG5fbG9hZCA9IF9nb3RoaWNfYnRuKCLwn5OCIikKICAgICAgICBzZWxmLl9idG5fbG9hZC5zZXRG"
    "aXhlZFNpemUoMzIsIDI0KQogICAgICAgIHNlbGYuX2J0bl9sb2FkLnNldFRvb2xUaXAoIkJyb3dzZSBhbmQgbG9hZCBhIHBhc3Qg"
    "c2Vzc2lvbiIpCiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90ID0gUUxhYmVsKCLil48iKQogICAgICAgIHNlbGYuX2F1dG9zYXZl"
    "X2RvdC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOHB4OyBib3Jk"
    "ZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Quc2V0VG9vbFRpcCgiQXV0b3NhdmUgc3RhdHVz"
    "IikKICAgICAgICBzZWxmLl9idG5fc2F2ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fc2F2ZSkKICAgICAgICBzZWxmLl9idG5f"
    "bG9hZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbG9hZCkKICAgICAgICBjdHJsX3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX3Nh"
    "dmUpCiAgICAgICAgY3RybF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9sb2FkKQogICAgICAgIGN0cmxfcm93LmFkZFdpZGdldChz"
    "ZWxmLl9hdXRvc2F2ZV9kb3QpCiAgICAgICAgY3RybF9yb3cuYWRkU3RyZXRjaCgpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRk"
    "TGF5b3V0KGN0cmxfcm93KQoKICAgICAgICAjIEpvdXJuYWwgbG9hZGVkIGluZGljYXRvcgogICAgICAgIHNlbGYuX2pvdXJuYWxf"
    "bGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29s"
    "b3I6IHtDX1BVUlBMRX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAg"
    "ICAgIGYiZm9udC1zdHlsZTogaXRhbGljOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0V29yZFdyYXAo"
    "VHJ1ZSkKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fam91cm5hbF9sYmwpCgogICAgICAgICMgQ2xlYXIg"
    "am91cm5hbCBidXR0b24gKGhpZGRlbiB3aGVuIG5vdCBsb2FkZWQpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwgPSBf"
    "Z290aGljX2J0bigi4pyXIFJldHVybiB0byBQcmVzZW50IikKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNp"
    "YmxlKEZhbHNlKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19jbGVhcl9q"
    "b3VybmFsKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9idG5fY2xlYXJfam91cm5hbCkKCiAgICAgICAg"
    "IyBEaXZpZGVyCiAgICAgICAgZGl2ID0gUUZyYW1lKCkKICAgICAgICBkaXYuc2V0RnJhbWVTaGFwZShRRnJhbWUuU2hhcGUuSExp"
    "bmUpCiAgICAgICAgZGl2LnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyIpCiAgICAgICAgY29udGVudF9s"
    "YXlvdXQuYWRkV2lkZ2V0KGRpdikKCiAgICAgICAgIyBTZXNzaW9uIGxpc3QKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRn"
    "ZXQoX3NlY3Rpb25fbGJsKCLinacgUEFTVCBTRVNTSU9OUyIpKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdCA9IFFMaXN0V2lk"
    "Z2V0KCkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7"
    "Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAg"
    "ICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICAgICAg"
    "ZiJRTGlzdFdpZGdldDo6aXRlbTpzZWxlY3RlZCB7eyBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IH19IgogICAgICAgICkK"
    "ICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QuaXRlbURvdWJsZUNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9zZXNzaW9uX2NsaWNr"
    "KQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5pdGVtQ2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX3Nlc3Npb25fY2xpY2spCiAg"
    "ICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Nlc3Npb25fbGlzdCwgMSkKCiAgICAgICAgIyBBZGQgY29udGVu"
    "dCBhbmQgdG9nZ2xlIHN0cmlwIHRvIHRoZSByb290IGhvcml6b250YWwgbGF5b3V0CiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2Vs"
    "Zi5fY29udGVudCkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90b2dnbGVfc3RyaXApCgogICAgZGVmIF90b2dnbGUoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAgIHNlbGYuX2NvbnRl"
    "bnQuc2V0VmlzaWJsZShzZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKXgCIgaWYgc2Vs"
    "Zi5fZXhwYW5kZWQgZWxzZSAi4pa2IikKICAgICAgICBzZWxmLnVwZGF0ZUdlb21ldHJ5KCkKICAgICAgICBwID0gc2VsZi5wYXJl"
    "bnRXaWRnZXQoKQogICAgICAgIGlmIHAgYW5kIHAubGF5b3V0KCk6CiAgICAgICAgICAgIHAubGF5b3V0KCkuYWN0aXZhdGUoKQoK"
    "ICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2Vzc2lvbnMgPSBzZWxmLl9zZXNzaW9uX21nci5saXN0X3Nl"
    "c3Npb25zKCkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QuY2xlYXIoKQogICAgICAgIGZvciBzIGluIHNlc3Npb25zOgogICAg"
    "ICAgICAgICBkYXRlX3N0ciA9IHMuZ2V0KCJkYXRlIiwiIikKICAgICAgICAgICAgbmFtZSAgICAgPSBzLmdldCgibmFtZSIsIGRh"
    "dGVfc3RyKVs6MzBdCiAgICAgICAgICAgIGNvdW50ICAgID0gcy5nZXQoIm1lc3NhZ2VfY291bnQiLCAwKQogICAgICAgICAgICBp"
    "dGVtID0gUUxpc3RXaWRnZXRJdGVtKGYie2RhdGVfc3RyfVxue25hbWV9ICh7Y291bnR9IG1zZ3MpIikKICAgICAgICAgICAgaXRl"
    "bS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgZGF0ZV9zdHIpCiAgICAgICAgICAgIGl0ZW0uc2V0VG9vbFRpcChm"
    "IkRvdWJsZS1jbGljayB0byBsb2FkIHNlc3Npb24gZnJvbSB7ZGF0ZV9zdHJ9IikKICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbl9s"
    "aXN0LmFkZEl0ZW0oaXRlbSkKCiAgICBkZWYgc2V0X3Nlc3Npb25fbmFtZShzZWxmLCBuYW1lOiBzdHIpIC0+IE5vbmU6CiAgICAg"
    "ICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNldFRleHQobmFtZVs6NTBdIG9yICJOZXcgU2Vzc2lvbiIpCgogICAgZGVmIHNldF9hdXRv"
    "c2F2ZV9pbmRpY2F0b3Ioc2VsZiwgc2F2ZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dSRUVOIGlmIHNhdmVkIGVsc2UgQ19URVhUX0RJTX07ICIKICAgICAg"
    "ICAgICAgZiJmb250LXNpemU6IDhweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90"
    "LnNldFRvb2xUaXAoCiAgICAgICAgICAgICJBdXRvc2F2ZWQiIGlmIHNhdmVkIGVsc2UgIlBlbmRpbmcgYXV0b3NhdmUiCiAgICAg"
    "ICAgKQoKICAgIGRlZiBzZXRfam91cm5hbF9sb2FkZWQoc2VsZiwgZGF0ZV9zdHI6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9qb3VybmFsX2xibC5zZXRUZXh0KGYi8J+TliBKb3VybmFsOiB7ZGF0ZV9zdHJ9IikKICAgICAgICBzZWxmLl9idG5fY2xlYXJf"
    "am91cm5hbC5zZXRWaXNpYmxlKFRydWUpCgogICAgZGVmIGNsZWFyX2pvdXJuYWxfaW5kaWNhdG9yKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0VGV4dCgiIikKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNp"
    "YmxlKEZhbHNlKQoKICAgIGRlZiBfZG9fc2F2ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nlc3Npb25fbWdyLnNhdmUo"
    "KQogICAgICAgIHNlbGYuc2V0X2F1dG9zYXZlX2luZGljYXRvcihUcnVlKQogICAgICAgIHNlbGYucmVmcmVzaCgpCiAgICAgICAg"
    "c2VsZi5fYnRuX3NhdmUuc2V0VGV4dCgi4pyTIikKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgxNTAwLCBsYW1iZGE6IHNlbGYu"
    "X2J0bl9zYXZlLnNldFRleHQoIvCfkr4iKSkKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgzMDAwLCBsYW1iZGE6IHNlbGYuc2V0"
    "X2F1dG9zYXZlX2luZGljYXRvcihGYWxzZSkpCgogICAgZGVmIF9kb19sb2FkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBUcnkg"
    "c2VsZWN0ZWQgaXRlbSBmaXJzdAogICAgICAgIGl0ZW0gPSBzZWxmLl9zZXNzaW9uX2xpc3QuY3VycmVudEl0ZW0oKQogICAgICAg"
    "IGlmIG5vdCBpdGVtOgogICAgICAgICAgICAjIElmIG5vdGhpbmcgc2VsZWN0ZWQsIHRyeSB0aGUgZmlyc3QgaXRlbQogICAgICAg"
    "ICAgICBpZiBzZWxmLl9zZXNzaW9uX2xpc3QuY291bnQoKSA+IDA6CiAgICAgICAgICAgICAgICBpdGVtID0gc2VsZi5fc2Vzc2lv"
    "bl9saXN0Lml0ZW0oMCkKICAgICAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5zZXRDdXJyZW50SXRlbShpdGVtKQogICAg"
    "ICAgIGlmIGl0ZW06CiAgICAgICAgICAgIGRhdGVfc3RyID0gaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAg"
    "ICAgICAgICAgc2VsZi5zZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmVtaXQoZGF0ZV9zdHIpCgogICAgZGVmIF9vbl9zZXNzaW9uX2Ns"
    "aWNrKHNlbGYsIGl0ZW0pIC0+IE5vbmU6CiAgICAgICAgZGF0ZV9zdHIgPSBpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJS"
    "b2xlKQogICAgICAgIHNlbGYuc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5lbWl0KGRhdGVfc3RyKQoKICAgIGRlZiBfZG9fY2xlYXJf"
    "am91cm5hbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuc2Vzc2lvbl9jbGVhcl9yZXF1ZXN0ZWQuZW1pdCgpCiAgICAgICAg"
    "c2VsZi5jbGVhcl9qb3VybmFsX2luZGljYXRvcigpCgoKIyDilIDilIAgVE9SUE9SIFBBTkVMIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgApjbGFzcyBUb3Jwb3JQYW5lbChRV2lkZ2V0KToKICAgICIiIgogICAgVGhyZWUtc3RhdGUgc3VzcGVu"
    "c2lvbiB0b2dnbGU6IEFXQUtFIHwgQVVUTyB8IFNVU1BFTkQKCiAgICBBV0FLRSAg4oCUIG1vZGVsIGxvYWRlZCwgYXV0by10b3Jw"
    "b3IgZGlzYWJsZWQsIGlnbm9yZXMgVlJBTSBwcmVzc3VyZQogICAgQVVUTyAgIOKAlCBtb2RlbCBsb2FkZWQsIG1vbml0b3JzIFZS"
    "QU0gcHJlc3N1cmUsIGF1dG8tdG9ycG9yIGlmIHN1c3RhaW5lZAogICAgU1VTUEVORCDigJQgbW9kZWwgdW5sb2FkZWQsIHN0YXlz"
    "IHN1c3BlbmRlZCB1bnRpbCBtYW51YWxseSBjaGFuZ2VkCgogICAgU2lnbmFsczoKICAgICAgICBzdGF0ZV9jaGFuZ2VkKHN0cikg"
    "IOKAlCAiQVdBS0UiIHwgIkFVVE8iIHwgIlNVU1BFTkQiCiAgICAiIiIKCiAgICBzdGF0ZV9jaGFuZ2VkID0gU2lnbmFsKHN0cikK"
    "CiAgICBTVEFURVMgPSBbIkFXQUtFIiwgIkFVVE8iLCAiU1VTUEVORCJdCgogICAgU1RBVEVfU1RZTEVTID0gewogICAgICAgICJB"
    "V0FLRSI6IHsKICAgICAgICAgICAgImFjdGl2ZSI6ICAgZiJiYWNrZ3JvdW5kOiAjMmExYTA1OyBjb2xvcjoge0NfR09MRH07ICIK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEfTsgYm9yZGVyLXJhZGl1czogMnB4OyAi"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHgg"
    "OHB4OyIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsg"
    "IgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJw"
    "eDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzog"
    "M3B4IDhweDsiLAogICAgICAgICAgICAibGFiZWwiOiAgICAi4piAIEFXQUtFIiwKICAgICAgICAgICAgInRvb2x0aXAiOiAgIk1v"
    "ZGVsIGFjdGl2ZS4gQXV0by10b3Jwb3IgZGlzYWJsZWQuIiwKICAgICAgICB9LAogICAgICAgICJBVVRPIjogewogICAgICAgICAg"
    "ICAiYWN0aXZlIjogICBmImJhY2tncm91bmQ6ICMxYTEwMDU7IGNvbG9yOiAjY2M4ODIyOyAiCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGYiYm9yZGVyOiAxcHggc29saWQgI2NjODgyMjsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJp"
    "bmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAgICAg"
    "ICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAg"
    "ICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAg"
    "ICAibGFiZWwiOiAgICAi4peJIEFVVE8iLAogICAgICAgICAgICAidG9vbHRpcCI6ICAiTW9kZWwgYWN0aXZlLiBBdXRvLXN1c3Bl"
    "bmQgb24gVlJBTSBwcmVzc3VyZS4iLAogICAgICAgIH0sCiAgICAgICAgIlNVU1BFTkQiOiB7CiAgICAgICAgICAgICJhY3RpdmUi"
    "OiAgIGYiYmFja2dyb3VuZDoge0NfUFVSUExFX0RJTX07IGNvbG9yOiB7Q19QVVJQTEV9OyAiCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfUFVSUExFfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAg"
    "ICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAg"
    "ICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAg"
    "ICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAg"
    "ICAgICAibGFiZWwiOiAgICBmIuKasCB7VUlfU1VTUEVOU0lPTl9MQUJFTC5zdHJpcCgpIGlmIHN0cihVSV9TVVNQRU5TSU9OX0xB"
    "QkVMKS5zdHJpcCgpIGVsc2UgJ1N1c3BlbmQnfSIsCiAgICAgICAgICAgICJ0b29sdGlwIjogIGYiTW9kZWwgdW5sb2FkZWQuIHtE"
    "RUNLX05BTUV9IHNsZWVwcyB1bnRpbCBtYW51YWxseSBhd2FrZW5lZC4iLAogICAgICAgIH0sCiAgICB9CgogICAgZGVmIF9faW5p"
    "dF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9jdXJy"
    "ZW50ID0gIkFXQUtFIgogICAgICAgIHNlbGYuX2J1dHRvbnM6IGRpY3Rbc3RyLCBRUHVzaEJ1dHRvbl0gPSB7fQogICAgICAgIGxh"
    "eW91dCA9IFFIQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAg"
    "ICAgIGxheW91dC5zZXRTcGFjaW5nKDIpCgogICAgICAgIGZvciBzdGF0ZSBpbiBzZWxmLlNUQVRFUzoKICAgICAgICAgICAgYnRu"
    "ID0gUVB1c2hCdXR0b24oc2VsZi5TVEFURV9TVFlMRVNbc3RhdGVdWyJsYWJlbCJdKQogICAgICAgICAgICBidG4uc2V0VG9vbFRp"
    "cChzZWxmLlNUQVRFX1NUWUxFU1tzdGF0ZV1bInRvb2x0aXAiXSkKICAgICAgICAgICAgYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQog"
    "ICAgICAgICAgICBidG4uY2xpY2tlZC5jb25uZWN0KGxhbWJkYSBjaGVja2VkLCBzPXN0YXRlOiBzZWxmLl9zZXRfc3RhdGUocykp"
    "CiAgICAgICAgICAgIHNlbGYuX2J1dHRvbnNbc3RhdGVdID0gYnRuCiAgICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoYnRuKQoK"
    "ICAgICAgICBzZWxmLl9hcHBseV9zdHlsZXMoKQoKICAgIGRlZiBfc2V0X3N0YXRlKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6"
    "CiAgICAgICAgaWYgc3RhdGUgPT0gc2VsZi5fY3VycmVudDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fY3VycmVu"
    "dCA9IHN0YXRlCiAgICAgICAgc2VsZi5fYXBwbHlfc3R5bGVzKCkKICAgICAgICBzZWxmLnN0YXRlX2NoYW5nZWQuZW1pdChzdGF0"
    "ZSkKCiAgICBkZWYgX2FwcGx5X3N0eWxlcyhzZWxmKSAtPiBOb25lOgogICAgICAgIGZvciBzdGF0ZSwgYnRuIGluIHNlbGYuX2J1"
    "dHRvbnMuaXRlbXMoKToKICAgICAgICAgICAgc3R5bGVfa2V5ID0gImFjdGl2ZSIgaWYgc3RhdGUgPT0gc2VsZi5fY3VycmVudCBl"
    "bHNlICJpbmFjdGl2ZSIKICAgICAgICAgICAgYnRuLnNldFN0eWxlU2hlZXQoc2VsZi5TVEFURV9TVFlMRVNbc3RhdGVdW3N0eWxl"
    "X2tleV0pCgogICAgQHByb3BlcnR5CiAgICBkZWYgY3VycmVudF9zdGF0ZShzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNl"
    "bGYuX2N1cnJlbnQKCiAgICBkZWYgc2V0X3N0YXRlKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIiIiU2V0IHN0"
    "YXRlIHByb2dyYW1tYXRpY2FsbHkgKGUuZy4gZnJvbSBhdXRvLXRvcnBvciBkZXRlY3Rpb24pLiIiIgogICAgICAgIGlmIHN0YXRl"
    "IGluIHNlbGYuU1RBVEVTOgogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdGUoc3RhdGUpCgoKIyDilIDilIAgTUFJTiBXSU5ET1cg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEVjaG9EZWNrKFFNYWluV2luZG93KToKICAgICIi"
    "IgogICAgVGhlIG1haW4gRWNobyBEZWNrIHdpbmRvdy4KICAgIEFzc2VtYmxlcyBhbGwgd2lkZ2V0cywgY29ubmVjdHMgYWxsIHNp"
    "Z25hbHMsIG1hbmFnZXMgYWxsIHN0YXRlLgogICAgIiIiCgogICAgIyDilIDilIAgVG9ycG9yIHRocmVzaG9sZHMg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBfRVhURVJOQUxfVlJBTV9U"
    "T1JQT1JfR0IgICAgPSAxLjUgICAjIGV4dGVybmFsIFZSQU0gPiB0aGlzIOKGkiBjb25zaWRlciB0b3Jwb3IKICAgIF9FWFRFUk5B"
    "TF9WUkFNX1dBS0VfR0IgICAgICA9IDAuOCAgICMgZXh0ZXJuYWwgVlJBTSA8IHRoaXMg4oaSIGNvbnNpZGVyIHdha2UKICAgIF9U"
    "T1JQT1JfU1VTVEFJTkVEX1RJQ0tTICAgICA9IDYgICAgICMgNiDDlyA1cyA9IDMwIHNlY29uZHMgc3VzdGFpbmVkCiAgICBfV0FL"
    "RV9TVVNUQUlORURfVElDS1MgICAgICAgPSAxMiAgICAjIDYwIHNlY29uZHMgc3VzdGFpbmVkIGxvdyBwcmVzc3VyZQoKICAgIGRl"
    "ZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKCiAgICAgICAgIyDilIDilIAgQ29yZSBzdGF0ZSDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICBzZWxmLl9zdGF0dXMgICAgICAgICAgICAgID0gIk9GRkxJTkUiCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9zdGFydCAgICAg"
    "ICA9IHRpbWUudGltZSgpCiAgICAgICAgc2VsZi5fdG9rZW5fY291bnQgICAgICAgICA9IDAKICAgICAgICBzZWxmLl9mYWNlX2xv"
    "Y2tlZCAgICAgICAgID0gRmFsc2UKICAgICAgICBzZWxmLl9ibGlua19zdGF0ZSAgICAgICAgID0gVHJ1ZQogICAgICAgIHNlbGYu"
    "X21vZGVsX2xvYWRlZCAgICAgICAgPSBGYWxzZQogICAgICAgIHNlbGYuX3Nlc3Npb25faWQgICAgICAgICAgPSBmInNlc3Npb25f"
    "e2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9IgogICAgICAgIHNlbGYuX2FjdGl2ZV90aHJlYWRzOiBs"
    "aXN0ID0gW10gICMga2VlcCByZWZzIHRvIHByZXZlbnQgR0Mgd2hpbGUgcnVubmluZwogICAgICAgIHNlbGYuX2ZpcnN0X3Rva2Vu"
    "OiBib29sID0gVHJ1ZSAgICMgd3JpdGUgc3BlYWtlciBsYWJlbCBiZWZvcmUgZmlyc3Qgc3RyZWFtaW5nIHRva2VuCgogICAgICAg"
    "ICMgVG9ycG9yIC8gVlJBTSB0cmFja2luZwogICAgICAgIHNlbGYuX3RvcnBvcl9zdGF0ZSAgICAgICAgPSAiQVdBS0UiCiAgICAg"
    "ICAgc2VsZi5fZGVja192cmFtX2Jhc2UgID0gMC4wICAgIyBiYXNlbGluZSBWUkFNIGFmdGVyIG1vZGVsIGxvYWQKICAgICAgICBz"
    "ZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMCAgICAgIyBzdXN0YWluZWQgcHJlc3N1cmUgY291bnRlcgogICAgICAgIHNlbGYu"
    "X3ZyYW1fcmVsaWVmX3RpY2tzICAgPSAwICAgICAjIHN1c3RhaW5lZCByZWxpZWYgY291bnRlcgogICAgICAgIHNlbGYuX3BlbmRp"
    "bmdfdHJhbnNtaXNzaW9ucyA9IDAKICAgICAgICBzZWxmLl90b3Jwb3Jfc2luY2UgICAgICAgID0gTm9uZSAgIyBkYXRldGltZSB3"
    "aGVuIHRvcnBvciBiZWdhbgogICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiAgPSAiIiAgICMgZm9ybWF0dGVkIGR1cmF0"
    "aW9uIHN0cmluZwoKICAgICAgICAjIOKUgOKUgCBNYW5hZ2VycyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9tZW1vcnkgICA9IE1lbW9yeU1h"
    "bmFnZXIoKQogICAgICAgIHNlbGYuX3Nlc3Npb25zID0gU2Vzc2lvbk1hbmFnZXIoKQogICAgICAgIHNlbGYuX2xlc3NvbnMgID0g"
    "TGVzc29uc0xlYXJuZWREQigpCiAgICAgICAgc2VsZi5fdGFza3MgICAgPSBUYXNrTWFuYWdlcigpCiAgICAgICAgc2VsZi5fcmVj"
    "b3Jkc19jYWNoZTogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fcmVjb3Jkc19pbml0aWFsaXplZCA9IEZhbHNlCiAgICAg"
    "ICAgc2VsZi5fcmVjb3Jkc19jdXJyZW50X2ZvbGRlcl9pZCA9ICJyb290IgogICAgICAgIHNlbGYuX2dvb2dsZV9hdXRoX3JlYWR5"
    "ID0gRmFsc2UKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lcjogT3B0aW9uYWxbUVRpbWVyXSA9IE5vbmUKICAgICAg"
    "ICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyOiBPcHRpb25hbFtRVGltZXJdID0gTm9uZQogICAgICAgIHNlbGYu"
    "X3JlY29yZHNfdGFiX2luZGV4ID0gLTEKICAgICAgICBzZWxmLl90YXNrc190YWJfaW5kZXggPSAtMQogICAgICAgIHNlbGYuX3Rh"
    "c2tfc2hvd19jb21wbGV0ZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPSAibmV4dF8zX21vbnRocyIK"
    "CiAgICAgICAgIyDilIDilIAgR29vZ2xlIFNlcnZpY2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgSW5zdGFudGlhdGUgc2VydmljZSB3cmFwcGVycyB1cC1mcm9udDsgYXV0aCBpcyBm"
    "b3JjZWQgbGF0ZXIKICAgICAgICAjIGZyb20gbWFpbigpIGFmdGVyIHdpbmRvdy5zaG93KCkgd2hlbiB0aGUgZXZlbnQgbG9vcCBp"
    "cyBydW5uaW5nLgogICAgICAgIGdfY3JlZHNfcGF0aCA9IFBhdGgoQ0ZHLmdldCgiZ29vZ2xlIiwge30pLmdldCgKICAgICAgICAg"
    "ICAgImNyZWRlbnRpYWxzIiwKICAgICAgICAgICAgc3RyKGNmZ19wYXRoKCJnb29nbGUiKSAvICJnb29nbGVfY3JlZGVudGlhbHMu"
    "anNvbiIpCiAgICAgICAgKSkKICAgICAgICBnX3Rva2VuX3BhdGggPSBQYXRoKENGRy5nZXQoImdvb2dsZSIsIHt9KS5nZXQoCiAg"
    "ICAgICAgICAgICJ0b2tlbiIsCiAgICAgICAgICAgIHN0cihjZmdfcGF0aCgiZ29vZ2xlIikgLyAidG9rZW4uanNvbiIpCiAgICAg"
    "ICAgKSkKICAgICAgICBzZWxmLl9nY2FsID0gR29vZ2xlQ2FsZW5kYXJTZXJ2aWNlKGdfY3JlZHNfcGF0aCwgZ190b2tlbl9wYXRo"
    "KQogICAgICAgIHNlbGYuX2dkcml2ZSA9IEdvb2dsZURvY3NEcml2ZVNlcnZpY2UoCiAgICAgICAgICAgIGdfY3JlZHNfcGF0aCwK"
    "ICAgICAgICAgICAgZ190b2tlbl9wYXRoLAogICAgICAgICAgICBsb2dnZXI9bGFtYmRhIG1zZywgbGV2ZWw9IklORk8iOiBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coZiJbR0RSSVZFXSB7bXNnfSIsIGxldmVsKQogICAgICAgICkKCiAgICAgICAgIyBTZWVkIExTTCBydWxl"
    "cyBvbiBmaXJzdCBydW4KICAgICAgICBzZWxmLl9sZXNzb25zLnNlZWRfbHNsX3J1bGVzKCkKCiAgICAgICAgIyBMb2FkIGVudGl0"
    "eSBzdGF0ZQogICAgICAgIHNlbGYuX3N0YXRlID0gc2VsZi5fbWVtb3J5LmxvYWRfc3RhdGUoKQogICAgICAgIHNlbGYuX3N0YXRl"
    "WyJzZXNzaW9uX2NvdW50Il0gPSBzZWxmLl9zdGF0ZS5nZXQoInNlc3Npb25fY291bnQiLDApICsgMQogICAgICAgIHNlbGYuX3N0"
    "YXRlWyJsYXN0X3N0YXJ0dXAiXSAgPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxm"
    "Ll9zdGF0ZSkKCiAgICAgICAgIyBCdWlsZCBhZGFwdG9yCiAgICAgICAgc2VsZi5fYWRhcHRvciA9IGJ1aWxkX2FkYXB0b3JfZnJv"
    "bV9jb25maWcoKQoKICAgICAgICAjIEZhY2UgdGltZXIgbWFuYWdlciAoc2V0IHVwIGFmdGVyIHdpZGdldHMgYnVpbHQpCiAgICAg"
    "ICAgc2VsZi5fZmFjZV90aW1lcl9tZ3I6IE9wdGlvbmFsW0ZhY2VUaW1lck1hbmFnZXJdID0gTm9uZQoKICAgICAgICAjIOKUgOKU"
    "gCBCdWlsZCBVSSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgICAgICBzZWxmLnNldFdpbmRvd1RpdGxlKEFQUF9OQU1FKQogICAgICAgIHNlbGYuc2V0TWluaW11"
    "bVNpemUoMTIwMCwgNzUwKQogICAgICAgIHNlbGYucmVzaXplKDEzNTAsIDg1MCkKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQo"
    "U1RZTEUpCgogICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKCiAgICAgICAgIyBGYWNlIHRpbWVyIG1hbmFnZXIgd2lyZWQgdG8gd2lk"
    "Z2V0cwogICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyID0gRmFjZVRpbWVyTWFuYWdlcigKICAgICAgICAgICAgc2VsZi5fbWly"
    "cm9yLCBzZWxmLl9lbW90aW9uX2Jsb2NrCiAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBUaW1lcnMg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgc2VsZi5fc3RhdHNfdGltZXIgPSBRVGltZXIoKQogICAgICAgIHNlbGYuX3N0YXRzX3RpbWVyLnRpbWVvdXQuY29ubmVjdChz"
    "ZWxmLl91cGRhdGVfc3RhdHMpCiAgICAgICAgc2VsZi5fc3RhdHNfdGltZXIuc3RhcnQoMTAwMCkKCiAgICAgICAgc2VsZi5fYmxp"
    "bmtfdGltZXIgPSBRVGltZXIoKQogICAgICAgIHNlbGYuX2JsaW5rX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9ibGluaykK"
    "ICAgICAgICBzZWxmLl9ibGlua190aW1lci5zdGFydCg4MDApCgogICAgICAgIHNlbGYuX3N0YXRlX3N0cmlwX3RpbWVyID0gUVRp"
    "bWVyKCkKICAgICAgICBpZiBBSV9TVEFURVNfRU5BQkxFRCBhbmQgc2VsZi5fZm9vdGVyX3N0cmlwIGlzIG5vdCBOb25lOgogICAg"
    "ICAgICAgICBzZWxmLl9zdGF0ZV9zdHJpcF90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fZm9vdGVyX3N0cmlwLnJlZnJlc2gp"
    "CiAgICAgICAgICAgIHNlbGYuX3N0YXRlX3N0cmlwX3RpbWVyLnN0YXJ0KDYwMDAwKQoKICAgICAgICBzZWxmLl9nb29nbGVfaW5i"
    "b3VuZF90aW1lciA9IFFUaW1lcihzZWxmKQogICAgICAgIHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyLnRpbWVvdXQuY29ubmVj"
    "dChzZWxmLl9vbl9nb29nbGVfaW5ib3VuZF90aW1lcl90aWNrKQogICAgICAgIHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyLnN0"
    "YXJ0KDYwMDAwKQoKICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAg"
    "ICAgc2VsZi5fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fb25fZ29vZ2xlX3JlY29y"
    "ZHNfcmVmcmVzaF90aW1lcl90aWNrKQogICAgICAgIHNlbGYuX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXIuc3RhcnQoNjAw"
    "MDApCgogICAgICAgICMg4pSA4pSAIFNjaGVkdWxlciBhbmQgc3RhcnR1cCBkZWZlcnJlZCB1bnRpbCBhZnRlciB3aW5kb3cuc2hv"
    "dygpIOKUgOKUgOKUgAogICAgICAgICMgRG8gTk9UIGNhbGwgX3NldHVwX3NjaGVkdWxlcigpIG9yIF9zdGFydHVwX3NlcXVlbmNl"
    "KCkgaGVyZS4KICAgICAgICAjIEJvdGggYXJlIHRyaWdnZXJlZCB2aWEgUVRpbWVyLnNpbmdsZVNob3QgZnJvbSBtYWluKCkgYWZ0"
    "ZXIKICAgICAgICAjIHdpbmRvdy5zaG93KCkgYW5kIGFwcC5leGVjKCkgYmVnaW5zIHJ1bm5pbmcuCgogICAgIyDilIDilIAgVUkg"
    "Q09OU1RSVUNUSU9OIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9idWlsZF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIGNl"
    "bnRyYWwgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLnNldENlbnRyYWxXaWRnZXQoY2VudHJhbCkKICAgICAgICByb290ID0gUVZC"
    "b3hMYXlvdXQoY2VudHJhbCkKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Qu"
    "c2V0U3BhY2luZyg0KQoKICAgICAgICAjIOKUgOKUgCBUaXRsZSBiYXIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fYnVp"
    "bGRfdGl0bGVfYmFyKCkpCgogICAgICAgICMg4pSA4pSAIEJvZHk6IEpvdXJuYWwgfCBDaGF0IHwgU3lzdGVtcyDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICBib2R5ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJvZHkuc2V0U3BhY2luZyg0KQoKICAgICAgICAjIEpvdXJu"
    "YWwgc2lkZWJhciAobGVmdCkKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIgPSBKb3VybmFsU2lkZWJhcihzZWxmLl9zZXNz"
    "aW9ucykKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5jb25uZWN0KAogICAgICAg"
    "ICAgICBzZWxmLl9sb2FkX2pvdXJuYWxfc2Vzc2lvbikKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2Vzc2lvbl9jbGVh"
    "cl9yZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5fY2xlYXJfam91cm5hbF9zZXNzaW9uKQogICAgICAgIGJvZHku"
    "YWRkV2lkZ2V0KHNlbGYuX2pvdXJuYWxfc2lkZWJhcikKCiAgICAgICAgIyBDaGF0IHBhbmVsIChjZW50ZXIsIGV4cGFuZHMpCiAg"
    "ICAgICAgYm9keS5hZGRMYXlvdXQoc2VsZi5fYnVpbGRfY2hhdF9wYW5lbCgpLCAxKQoKICAgICAgICAjIFN5c3RlbXMgKHJpZ2h0"
    "KQogICAgICAgIGJvZHkuYWRkTGF5b3V0KHNlbGYuX2J1aWxkX3NwZWxsYm9va19wYW5lbCgpKQoKICAgICAgICByb290LmFkZExh"
    "eW91dChib2R5LCAxKQoKICAgICAgICAjIOKUgOKUgCBGb290ZXIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgZm9vdGVyID0gUUxhYmVsKAog"
    "ICAgICAgICAgICBmIuKcpiB7QVBQX05BTUV9IOKAlCB2e0FQUF9WRVJTSU9OfSDinKYiCiAgICAgICAgKQogICAgICAgIGZvb3Rl"
    "ci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBsZXR0ZXIt"
    "c3BhY2luZzogMnB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQog"
    "ICAgICAgIGZvb3Rlci5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICByb290LmFkZFdp"
    "ZGdldChmb290ZXIpCgogICAgZGVmIF9idWlsZF90aXRsZV9iYXIoc2VsZikgLT4gUVdpZGdldDoKICAgICAgICBiYXIgPSBRV2lk"
    "Z2V0KCkKICAgICAgICBiYXIuc2V0Rml4ZWRIZWlnaHQoMzYpCiAgICAgICAgYmFyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "IGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYi"
    "Ym9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCiAgICAgICAgbGF5b3V0ID0gUUhCb3hMYXlvdXQoYmFyKQogICAgICAgIGxh"
    "eW91dC5zZXRDb250ZW50c01hcmdpbnMoMTAsIDAsIDEwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDYpCgogICAgICAg"
    "IHRpdGxlID0gUUxhYmVsKGYi4pymIHtBUFBfTkFNRX0iKQogICAgICAgIHRpdGxlLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "IGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDEzcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYi"
    "bGV0dGVyLXNwYWNpbmc6IDJweDsgYm9yZGVyOiBub25lOyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAg"
    "ICApCgogICAgICAgIHJ1bmVzID0gUUxhYmVsKFJVTkVTKQogICAgICAgIHJ1bmVzLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "IGYiY29sb3I6IHtDX0dPTERfRElNfTsgZm9udC1zaXplOiAxMHB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBy"
    "dW5lcy5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwg"
    "PSBRTGFiZWwoZiLil4kge1VJX09GRkxJTkVfU1RBVFVTfSIpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQkxPT0R9OyBmb250LXNpemU6IDEycHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBib3Jk"
    "ZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50Rmxh"
    "Zy5BbGlnblJpZ2h0KQoKICAgICAgICAjIFN1c3BlbnNpb24gcGFuZWwKICAgICAgICBzZWxmLl90b3Jwb3JfcGFuZWwgPSBOb25l"
    "CiAgICAgICAgaWYgU1VTUEVOU0lPTl9FTkFCTEVEOgogICAgICAgICAgICBzZWxmLl90b3Jwb3JfcGFuZWwgPSBUb3Jwb3JQYW5l"
    "bCgpCiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9wYW5lbC5zdGF0ZV9jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fdG9ycG9yX3N0"
    "YXRlX2NoYW5nZWQpCgogICAgICAgICMgSWRsZSB0b2dnbGUKICAgICAgICBzZWxmLl9pZGxlX2J0biA9IFFQdXNoQnV0dG9uKCJJ"
    "RExFIE9GRiIpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgc2VsZi5faWRsZV9idG4u"
    "c2V0Q2hlY2thYmxlKFRydWUpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0Q2hlY2tlZChGYWxzZSkKICAgICAgICBzZWxmLl9p"
    "ZGxlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJ"
    "TX07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAg"
    "ICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IgogICAgICAgICkK"
    "ICAgICAgICBzZWxmLl9pZGxlX2J0bi50b2dnbGVkLmNvbm5lY3Qoc2VsZi5fb25faWRsZV90b2dnbGVkKQoKICAgICAgICAjIEZT"
    "IC8gQkwgYnV0dG9ucwogICAgICAgIHNlbGYuX2ZzX2J0biA9IFFQdXNoQnV0dG9uKCJGUyIpCiAgICAgICAgc2VsZi5fYmxfYnRu"
    "ID0gUVB1c2hCdXR0b24oIkJMIikKICAgICAgICBzZWxmLl9leHBvcnRfYnRuID0gUVB1c2hCdXR0b24oIkV4cG9ydCIpCiAgICAg"
    "ICAgc2VsZi5fc2h1dGRvd25fYnRuID0gUVB1c2hCdXR0b24oIlNodXRkb3duIikKICAgICAgICBmb3IgYnRuIGluIChzZWxmLl9m"
    "c19idG4sIHNlbGYuX2JsX2J0biwgc2VsZi5fZXhwb3J0X2J0bik6CiAgICAgICAgICAgIGJ0bi5zZXRGaXhlZFNpemUoMzAsIDIy"
    "KQogICAgICAgICAgICBidG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29s"
    "b3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07"
    "IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAg"
    "ICAgICAgKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4uc2V0Rml4ZWRXaWR0aCg0NikKICAgICAgICBzZWxmLl9zaHV0ZG93bl9i"
    "dG4uc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldEZpeGVkV2lkdGgoNjgpCiAgICAgICAg"
    "c2VsZi5fc2h1dGRvd25fYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6"
    "IHtDX0JMT09EfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JMT09EfTsgZm9udC1zaXplOiA5cHg7ICIK"
    "ICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2ZzX2J0"
    "bi5zZXRUb29sVGlwKCJGdWxsc2NyZWVuIChGMTEpIikKICAgICAgICBzZWxmLl9ibF9idG4uc2V0VG9vbFRpcCgiQm9yZGVybGVz"
    "cyAoRjEwKSIpCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0bi5zZXRUb29sVGlwKCJFeHBvcnQgY2hhdCBzZXNzaW9uIHRvIFRYVCBm"
    "aWxlIikKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uc2V0VG9vbFRpcChmIkdyYWNlZnVsIHNodXRkb3duIOKAlCB7REVDS19O"
    "QU1FfSBzcGVha3MgdGhlaXIgbGFzdCB3b3JkcyIpCiAgICAgICAgc2VsZi5fZnNfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90"
    "b2dnbGVfZnVsbHNjcmVlbikKICAgICAgICBzZWxmLl9ibF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9ib3JkZXJs"
    "ZXNzKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2V4cG9ydF9jaGF0KQogICAgICAgIHNl"
    "bGYuX3NodXRkb3duX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5faW5pdGlhdGVfc2h1dGRvd25fZGlhbG9nKQoKICAgICAgICBs"
    "YXlvdXQuYWRkV2lkZ2V0KHRpdGxlKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQocnVuZXMsIDEpCiAgICAgICAgbGF5b3V0LmFk"
    "ZFdpZGdldChzZWxmLnN0YXR1c19sYWJlbCkKICAgICAgICBsYXlvdXQuYWRkU3BhY2luZyg4KQogICAgICAgIGlmIHNlbGYuX3Rv"
    "cnBvcl9wYW5lbCBpcyBub3QgTm9uZToKICAgICAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl90b3Jwb3JfcGFuZWwpCiAg"
    "ICAgICAgbGF5b3V0LmFkZFNwYWNpbmcoNCkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2lkbGVfYnRuKQogICAgICAg"
    "IGxheW91dC5hZGRTcGFjaW5nKDQpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9leHBvcnRfYnRuKQogICAgICAgIGxh"
    "eW91dC5hZGRXaWRnZXQoc2VsZi5fc2h1dGRvd25fYnRuKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZnNfYnRuKQog"
    "ICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fYmxfYnRuKQoKICAgICAgICByZXR1cm4gYmFyCgogICAgZGVmIF9idWlsZF9j"
    "aGF0X3BhbmVsKHNlbGYpIC0+IFFWQm94TGF5b3V0OgogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KCkKICAgICAgICBsYXlv"
    "dXQuc2V0U3BhY2luZyg0KQoKICAgICAgICAjIE1haW4gdGFiIHdpZGdldCDigJQgcGVyc29uYSBjaGF0IHRhYiB8IFNlbGYKICAg"
    "ICAgICBzZWxmLl9tYWluX3RhYnMgPSBRVGFiV2lkZ2V0KCkKICAgICAgICBzZWxmLl9tYWluX3RhYnMuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJRVGFiV2lkZ2V0OjpwYW5lIHt7IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAg"
    "ICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyB9fSIKICAgICAgICAgICAgZiJRVGFiQmFyOjp0YWIge3sgYmFja2dy"
    "b3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBmInBhZGRpbmc6IDRweCAxMnB4OyBib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsg"
    "Zm9udC1zaXplOiAxMHB4OyB9fSIKICAgICAgICAgICAgZiJRVGFiQmFyOjp0YWI6c2VsZWN0ZWQge3sgYmFja2dyb3VuZDoge0Nf"
    "QkcyfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLWJvdHRvbTogMnB4IHNvbGlkIHtDX0NSSU1TT059"
    "OyB9fSIKICAgICAgICApCgogICAgICAgICMg4pSA4pSAIFRhYiAwOiBQZXJzb25hIGNoYXQgdGFiIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgICAgIHNlYW5jZV93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWFuY2VfbGF5b3V0ID0gUVZC"
    "b3hMYXlvdXQoc2VhbmNlX3dpZGdldCkKICAgICAgICBzZWFuY2VfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAw"
    "KQogICAgICAgIHNlYW5jZV9sYXlvdXQuc2V0U3BhY2luZygwKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheSA9IFFUZXh0RWRp"
    "dCgpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9yOiB7Q19HT0xEfTsgIgog"
    "ICAgICAgICAgICBmImJvcmRlcjogbm9uZTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7"
    "IGZvbnQtc2l6ZTogMTJweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAgc2VhbmNlX2xheW91dC5hZGRXaWRnZXQo"
    "c2VsZi5fY2hhdF9kaXNwbGF5KQogICAgICAgIHNlbGYuX21haW5fdGFicy5hZGRUYWIoc2VhbmNlX3dpZGdldCwgZiLinacge1VJ"
    "X0NIQVRfV0lORE9XfSIpCgogICAgICAgICMg4pSA4pSAIFRhYiAxOiBTZWxmIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NlbGZfdGFiX3dpZGdldCA9IFFX"
    "aWRnZXQoKQogICAgICAgIHNlbGZfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fc2VsZl90YWJfd2lkZ2V0KQogICAgICAgIHNl"
    "bGZfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGZfbGF5b3V0LnNldFNwYWNpbmcoNCkK"
    "ICAgICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX3NlbGZfZGlzcGxheS5zZXRSZWFk"
    "T25seShUcnVlKQogICAgICAgIHNlbGYuX3NlbGZfZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91"
    "bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7ICIKICAgICAgICAg"
    "ICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEycHg7IHBhZGRpbmc6IDhweDsiCiAgICAg"
    "ICAgKQogICAgICAgIHNlbGZfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zZWxmX2Rpc3BsYXksIDEpCiAgICAgICAgc2VsZi5fbWFp"
    "bl90YWJzLmFkZFRhYihzZWxmLl9zZWxmX3RhYl93aWRnZXQsICLil4kgU0VMRiIpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQo"
    "c2VsZi5fbWFpbl90YWJzLCAxKQoKICAgICAgICAjIOKUgOKUgCBCb3R0b20gc3RhdHVzL3Jlc291cmNlIGJsb2NrIHJvdyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICAjIE1hbmRhdG9yeSBwZXJtYW5lbnQgc3RydWN0dXJlIGFjcm9zcyBhbGwgcGVyc29uYXM6CiAgICAgICAgIyBN"
    "SVJST1IgfCBFTU9USU9OUyB8IExFRlQgT1JCIHwgQ0VOVEVSIENZQ0xFIHwgUklHSFQgT1JCIHwgRVNTRU5DRQogICAgICAgIGJs"
    "b2NrX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBibG9ja19yb3cuc2V0U3BhY2luZygyKQoKICAgICAgICAjIE1pcnJvciAo"
    "bmV2ZXIgY29sbGFwc2VzKQogICAgICAgIG1pcnJvcl93cmFwID0gUVdpZGdldCgpCiAgICAgICAgbXdfbGF5b3V0ID0gUVZCb3hM"
    "YXlvdXQobWlycm9yX3dyYXApCiAgICAgICAgbXdfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAg"
    "IG13X2xheW91dC5zZXRTcGFjaW5nKDIpCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoZiLinacge1VJ"
    "X01JUlJPUl9MQUJFTH0iKSkKICAgICAgICBzZWxmLl9taXJyb3IgPSBNaXJyb3JXaWRnZXQoKQogICAgICAgIHNlbGYuX21pcnJv"
    "ci5zZXRGaXhlZFNpemUoMTYwLCAxNjApCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9taXJyb3IpCiAgICAgICAg"
    "YmxvY2tfcm93LmFkZFdpZGdldChtaXJyb3Jfd3JhcCwgMCkKCiAgICAgICAgIyBFbW90aW9uIGJsb2NrIChjb2xsYXBzaWJsZSkK"
    "ICAgICAgICBzZWxmLl9lbW90aW9uX2Jsb2NrID0gRW1vdGlvbkJsb2NrKCkKICAgICAgICBzZWxmLl9lbW90aW9uX2Jsb2NrX3dy"
    "YXAgPSBDb2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfRU1PVElPTlNfTEFCRUx9Iiwgc2VsZi5fZW1vdGlv"
    "bl9ibG9jaywKICAgICAgICAgICAgZXhwYW5kZWQ9VHJ1ZSwgbWluX3dpZHRoPTEzMAogICAgICAgICkKICAgICAgICBibG9ja19y"
    "b3cuYWRkV2lkZ2V0KHNlbGYuX2Vtb3Rpb25fYmxvY2tfd3JhcCwgMCkKCiAgICAgICAgIyBNaWRkbGUgbG93ZXIgYmxvY2sgKGZp"
    "eGVkIDQtY29sdW1uIGxheW91dCk6CiAgICAgICAgIyBQUklNQVJZIHwgQ1lDTEUgfCBTRUNPTkRBUlkgfCBFU1NFTkNFCiAgICAg"
    "ICAgbWlkZGxlX3dyYXAgPSBRV2lkZ2V0KCkKICAgICAgICBtaWRkbGVfZ3JpZCA9IFFHcmlkTGF5b3V0KG1pZGRsZV93cmFwKQog"
    "ICAgICAgIG1pZGRsZV9ncmlkLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG1pZGRsZV9ncmlkLnNldEhv"
    "cml6b250YWxTcGFjaW5nKDIpCiAgICAgICAgbWlkZGxlX2dyaWQuc2V0VmVydGljYWxTcGFjaW5nKDIpCgogICAgICAgICMgTGVm"
    "dCByZXNvdXJjZSBvcmIgKGNvbGxhcHNpYmxlLCBmaXhlZCBzbG90KQogICAgICAgIHNlbGYuX2xlZnRfb3JiID0gU3BoZXJlV2lk"
    "Z2V0KAogICAgICAgICAgICBVSV9MRUZUX09SQl9MQUJFTCwgQ19DUklNU09OLCBDX0NSSU1TT05fRElNCiAgICAgICAgKQogICAg"
    "ICAgIHNlbGYuX2xlZnRfb3JiX3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfTEVGVF9PUkJf"
    "VElUTEV9Iiwgc2VsZi5fbGVmdF9vcmIsCiAgICAgICAgICAgIG1pbl93aWR0aD05MCwgcmVzZXJ2ZV93aWR0aD1UcnVlCiAgICAg"
    "ICAgKQogICAgICAgIG1pZGRsZV9ncmlkLmFkZFdpZGdldChzZWxmLl9sZWZ0X29yYl93cmFwLCAwLCAwKQoKICAgICAgICAjIENl"
    "bnRlciBjeWNsZSB3aWRnZXQgKGNvbGxhcHNpYmxlLCBmaXhlZCBzbG90KQogICAgICAgIHNlbGYuX2N5Y2xlX3dpZGdldCA9IEN5"
    "Y2xlV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jeWNsZV93cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacg"
    "e1VJX0NZQ0xFX1RJVExFfSIsIHNlbGYuX2N5Y2xlX3dpZGdldCwKICAgICAgICAgICAgbWluX3dpZHRoPTkwLCByZXNlcnZlX3dp"
    "ZHRoPVRydWUKICAgICAgICApCiAgICAgICAgbWlkZGxlX2dyaWQuYWRkV2lkZ2V0KHNlbGYuX2N5Y2xlX3dyYXAsIDAsIDEpCgog"
    "ICAgICAgICMgUmlnaHQgcmVzb3VyY2Ugb3JiIChjb2xsYXBzaWJsZSwgZml4ZWQgc2xvdCkKICAgICAgICBzZWxmLl9yaWdodF9v"
    "cmIgPSBTcGhlcmVXaWRnZXQoCiAgICAgICAgICAgIFVJX1JJR0hUX09SQl9MQUJFTCwgQ19QVVJQTEUsIENfUFVSUExFX0RJTQog"
    "ICAgICAgICkKICAgICAgICBzZWxmLl9yaWdodF9vcmJfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2soCiAgICAgICAgICAgIGYi4p2n"
    "IHtVSV9SSUdIVF9PUkJfVElUTEV9Iiwgc2VsZi5fcmlnaHRfb3JiLAogICAgICAgICAgICBtaW5fd2lkdGg9OTAsIHJlc2VydmVf"
    "d2lkdGg9VHJ1ZQogICAgICAgICkKICAgICAgICBtaWRkbGVfZ3JpZC5hZGRXaWRnZXQoc2VsZi5fcmlnaHRfb3JiX3dyYXAsIDAs"
    "IDIpCgogICAgICAgICMgRXNzZW5jZSAoMiBnYXVnZXMsIGNvbGxhcHNpYmxlLCBmaXhlZCBzbG90KQogICAgICAgIGVzc2VuY2Vf"
    "d2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgZXNzZW5jZV9sYXlvdXQgPSBRVkJveExheW91dChlc3NlbmNlX3dpZGdldCkKICAg"
    "ICAgICBlc3NlbmNlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBlc3NlbmNlX2xheW91dC5z"
    "ZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5fZXNzZW5jZV9wcmltYXJ5X2dhdWdlICAgPSBHYXVnZVdpZGdldChVSV9FU1NFTkNF"
    "X1BSSU1BUlksICAgIiUiLCAxMDAuMCwgQ19DUklNU09OKQogICAgICAgIHNlbGYuX2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdlID0g"
    "R2F1Z2VXaWRnZXQoVUlfRVNTRU5DRV9TRUNPTkRBUlksICIlIiwgMTAwLjAsIENfR1JFRU4pCiAgICAgICAgZXNzZW5jZV9sYXlv"
    "dXQuYWRkV2lkZ2V0KHNlbGYuX2Vzc2VuY2VfcHJpbWFyeV9nYXVnZSkKICAgICAgICBlc3NlbmNlX2xheW91dC5hZGRXaWRnZXQo"
    "c2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2UpCiAgICAgICAgc2VsZi5fZXNzZW5jZV93cmFwID0gQ29sbGFwc2libGVCbG9j"
    "aygKICAgICAgICAgICAgZiLinacge1VJX0VTU0VOQ0VfVElUTEV9IiwgZXNzZW5jZV93aWRnZXQsCiAgICAgICAgICAgIG1pbl93"
    "aWR0aD0xMTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAgICAgICkKICAgICAgICBtaWRkbGVfZ3JpZC5hZGRXaWRnZXQoc2VsZi5f"
    "ZXNzZW5jZV93cmFwLCAwLCAzKQoKICAgICAgICBmb3IgY29sIGluIHJhbmdlKDQpOgogICAgICAgICAgICBtaWRkbGVfZ3JpZC5z"
    "ZXRDb2x1bW5TdHJldGNoKGNvbCwgMSkKCiAgICAgICAgYmxvY2tfcm93LmFkZFdpZGdldChtaWRkbGVfd3JhcCwgMSkKICAgICAg"
    "ICBsYXlvdXQuYWRkTGF5b3V0KGJsb2NrX3JvdykKCiAgICAgICAgIyBGb290ZXIgc3RhdGUgc3RyaXAgKGJlbG93IGJsb2NrIHJv"
    "dyDigJQgcGVybWFuZW50IFVJIHN0cnVjdHVyZSkKICAgICAgICBzZWxmLl9mb290ZXJfc3RyaXAgPSBGb290ZXJTdHJpcFdpZGdl"
    "dCgpCiAgICAgICAgc2VsZi5fZm9vdGVyX3N0cmlwLnNldF9sYWJlbChVSV9GT09URVJfU1RSSVBfTEFCRUwpCiAgICAgICAgbGF5"
    "b3V0LmFkZFdpZGdldChzZWxmLl9mb290ZXJfc3RyaXApCgogICAgICAgICMg4pSA4pSAIElucHV0IHJvdyDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBpbnB1"
    "dF9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgcHJvbXB0X3N5bSA9IFFMYWJlbCgi4pymIikKICAgICAgICBwcm9tcHRfc3lt"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDE2cHg7IGZvbnQtd2Vp"
    "Z2h0OiBib2xkOyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBwcm9tcHRfc3ltLnNldEZpeGVkV2lkdGgoMjApCgog"
    "ICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRQbGFjZWhv"
    "bGRlclRleHQoVUlfSU5QVVRfUExBQ0VIT0xERVIpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQucmV0dXJuUHJlc3NlZC5jb25u"
    "ZWN0KHNlbGYuX3NlbmRfbWVzc2FnZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKEZhbHNlKQoKICAgICAg"
    "ICBzZWxmLl9zZW5kX2J0biA9IFFQdXNoQnV0dG9uKFVJX1NFTkRfQlVUVE9OKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEZp"
    "eGVkV2lkdGgoMTEwKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9zZW5kX21lc3NhZ2UpCiAg"
    "ICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChGYWxzZSkKCiAgICAgICAgaW5wdXRfcm93LmFkZFdpZGdldChwcm9tcHRf"
    "c3ltKQogICAgICAgIGlucHV0X3Jvdy5hZGRXaWRnZXQoc2VsZi5faW5wdXRfZmllbGQpCiAgICAgICAgaW5wdXRfcm93LmFkZFdp"
    "ZGdldChzZWxmLl9zZW5kX2J0bikKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGlucHV0X3JvdykKCiAgICAgICAgcmV0dXJuIGxh"
    "eW91dAoKICAgIGRlZiBfYnVpbGRfc3BlbGxib29rX3BhbmVsKHNlbGYpIC0+IFFWQm94TGF5b3V0OgogICAgICAgIGxheW91dCA9"
    "IFFWQm94TGF5b3V0KCkKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbGF5b3V0"
    "LnNldFNwYWNpbmcoNCkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFNZU1RFTVMiKSkKCiAgICAg"
    "ICAgIyBUYWIgd2lkZ2V0CiAgICAgICAgc2VsZi5fc3BlbGxfdGFicyA9IFFUYWJXaWRnZXQoKQogICAgICAgIHNlbGYuX3NwZWxs"
    "X3RhYnMuc2V0TWluaW11bVdpZHRoKDI4MCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLnNldFNpemVQb2xpY3koCiAgICAgICAg"
    "ICAgIFFTaXplUG9saWN5LlBvbGljeS5FeHBhbmRpbmcsCiAgICAgICAgICAgIFFTaXplUG9saWN5LlBvbGljeS5FeHBhbmRpbmcK"
    "ICAgICAgICApCgogICAgICAgICMgQnVpbGQgRGlhZ25vc3RpY3NUYWIgZWFybHkgc28gc3RhcnR1cCBsb2dzIGFyZSBzYWZlIGV2"
    "ZW4gYmVmb3JlCiAgICAgICAgIyB0aGUgRGlhZ25vc3RpY3MgdGFiIGlzIGF0dGFjaGVkIHRvIHRoZSB3aWRnZXQuCiAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIgPSBEaWFnbm9zdGljc1RhYigpCgogICAgICAgICMg4pSA4pSAIEluc3RydW1lbnRzIHRhYiDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9od19wYW5lbCA9"
    "IEhhcmR3YXJlUGFuZWwoKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX2h3X3BhbmVsLCAiSW5zdHJ1bWVu"
    "dHMiKQoKICAgICAgICAjIOKUgOKUgCBSZWNvcmRzIHRhYiAocmVhbCkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIgPSBSZWNvcmRzVGFiKCkKICAgICAgICBzZWxmLl9yZWNvcmRz"
    "X3RhYl9pbmRleCA9IHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX3JlY29yZHNfdGFiLCAiUmVjb3JkcyIpCiAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKCJbU1BFTExCT09LXSByZWFsIFJlY29yZHNUYWIgYXR0YWNoZWQuIiwgIklORk8iKQoKICAgICAg"
    "ICAjIOKUgOKUgCBUYXNrcyB0YWIgKHJlYWwpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgICAgIHNlbGYuX3Rhc2tzX3RhYiA9IFRhc2tzVGFiKAogICAgICAgICAgICB0YXNrc19wcm92aWRlcj1zZWxmLl9m"
    "aWx0ZXJlZF90YXNrc19mb3JfcmVnaXN0cnksCiAgICAgICAgICAgIG9uX2FkZF9lZGl0b3Jfb3Blbj1zZWxmLl9vcGVuX3Rhc2tf"
    "ZWRpdG9yX3dvcmtzcGFjZSwKICAgICAgICAgICAgb25fY29tcGxldGVfc2VsZWN0ZWQ9c2VsZi5fY29tcGxldGVfc2VsZWN0ZWRf"
    "dGFzaywKICAgICAgICAgICAgb25fY2FuY2VsX3NlbGVjdGVkPXNlbGYuX2NhbmNlbF9zZWxlY3RlZF90YXNrLAogICAgICAgICAg"
    "ICBvbl90b2dnbGVfY29tcGxldGVkPXNlbGYuX3RvZ2dsZV9zaG93X2NvbXBsZXRlZF90YXNrcywKICAgICAgICAgICAgb25fcHVy"
    "Z2VfY29tcGxldGVkPXNlbGYuX3B1cmdlX2NvbXBsZXRlZF90YXNrcywKICAgICAgICAgICAgb25fZmlsdGVyX2NoYW5nZWQ9c2Vs"
    "Zi5fb25fdGFza19maWx0ZXJfY2hhbmdlZCwKICAgICAgICAgICAgb25fZWRpdG9yX3NhdmU9c2VsZi5fc2F2ZV90YXNrX2VkaXRv"
    "cl9nb29nbGVfZmlyc3QsCiAgICAgICAgICAgIG9uX2VkaXRvcl9jYW5jZWw9c2VsZi5fY2FuY2VsX3Rhc2tfZWRpdG9yX3dvcmtz"
    "cGFjZSwKICAgICAgICAgICAgZGlhZ25vc3RpY3NfbG9nZ2VyPXNlbGYuX2RpYWdfdGFiLmxvZywKICAgICAgICApCiAgICAgICAg"
    "c2VsZi5fdGFza3NfdGFiLnNldF9zaG93X2NvbXBsZXRlZChzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkKQogICAgICAgIHNlbGYu"
    "X3Rhc2tzX3RhYl9pbmRleCA9IHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX3Rhc2tzX3RhYiwgIlRhc2tzIikKICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coIltTUEVMTEJPT0tdIHJlYWwgVGFza3NUYWIgYXR0YWNoZWQuIiwgIklORk8iKQoKICAgICAg"
    "ICAjIOKUgOKUgCBTTCBTY2FucyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc2xfc2NhbnMgPSBTTFNjYW5zVGFiKGNmZ19wYXRoKCJzbCIpKQogICAgICAg"
    "IHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX3NsX3NjYW5zLCAiU0wgU2NhbnMiKQoKICAgICAgICAjIOKUgOKUgCBTTCBD"
    "b21tYW5kcyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgc2VsZi5fc2xfY29tbWFuZHMgPSBTTENvbW1hbmRzVGFiKCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxm"
    "Ll9zbF9jb21tYW5kcywgIlNMIENvbW1hbmRzIikKCiAgICAgICAgIyDilIDilIAgSm9iIFRyYWNrZXIgdGFiIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2pvYl90cmFja2VyID0g"
    "Sm9iVHJhY2tlclRhYigpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fam9iX3RyYWNrZXIsICJKb2IgVHJh"
    "Y2tlciIpCgogICAgICAgICMg4pSA4pSAIExlc3NvbnMgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2xlc3NvbnNfdGFiID0gTGVzc29uc1RhYihzZWxm"
    "Ll9sZXNzb25zKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX2xlc3NvbnNfdGFiLCAiTGVzc29ucyIpCgog"
    "ICAgICAgICMgU2VsZiB0YWIgaXMgbm93IGluIHRoZSBtYWluIGFyZWEgYWxvbmdzaWRlIHRoZSBwZXJzb25hIGNoYXQgdGFiCiAg"
    "ICAgICAgIyBLZWVwIGEgU2VsZlRhYiBpbnN0YW5jZSBmb3IgaWRsZSBjb250ZW50IGdlbmVyYXRpb24KICAgICAgICBzZWxmLl9z"
    "ZWxmX3RhYiA9IFNlbGZUYWIoKQoKICAgICAgICAjIOKUgOKUgCBNb2R1bGUgVHJhY2tlciB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fbW9kdWxlX3RyYWNrZXIgPSBNb2R1bGVUcmFja2Vy"
    "VGFiKCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9tb2R1bGVfdHJhY2tlciwgIk1vZHVsZXMiKQoKICAg"
    "ICAgICAjIOKUgOKUgCBEaWFnbm9zdGljcyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fZGlhZ190YWIsICJEaWFnbm9zdGljcyIp"
    "CgogICAgICAgIHJpZ2h0X3dvcmtzcGFjZSA9IFFXaWRnZXQoKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQgPSBRVkJv"
    "eExheW91dChyaWdodF93b3Jrc3BhY2UpCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMo"
    "MCwgMCwgMCwgMCkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgcmlnaHRfd29y"
    "a3NwYWNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fc3BlbGxfdGFicywgMSkKCiAgICAgICAgY2FsZW5kYXJfbGFiZWwgPSBRTGFi"
    "ZWwoIuKdpyBDQUxFTkRBUiIpCiAgICAgICAgY2FsZW5kYXJfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xv"
    "cjoge0NfR09MRH07IGZvbnQtc2l6ZTogMTBweDsgbGV0dGVyLXNwYWNpbmc6IDJweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9"
    "LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkV2lkZ2V0KGNhbGVuZGFyX2xhYmVs"
    "KQoKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldCA9IE1pbmlDYWxlbmRhcldpZGdldCgpCiAgICAgICAgc2VsZi5jYWxlbmRh"
    "cl93aWRnZXQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xp"
    "ZCB7Q19DUklNU09OX0RJTX07IgogICAgICAgICkKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldC5zZXRTaXplUG9saWN5KAog"
    "ICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nLAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuTWF4"
    "aW11bQogICAgICAgICkKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldC5zZXRNYXhpbXVtSGVpZ2h0KDI2MCkKICAgICAgICBz"
    "ZWxmLmNhbGVuZGFyX3dpZGdldC5jYWxlbmRhci5jbGlja2VkLmNvbm5lY3Qoc2VsZi5faW5zZXJ0X2NhbGVuZGFyX2RhdGUpCiAg"
    "ICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5jYWxlbmRhcl93aWRnZXQsIDApCiAgICAgICAgcmln"
    "aHRfd29ya3NwYWNlX2xheW91dC5hZGRTdHJldGNoKDApCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQocmlnaHRfd29ya3NwYWNl"
    "LCAxKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgIltMQVlPVVRdIHJpZ2h0LXNpZGUgY2FsZW5kYXIg"
    "cmVzdG9yZWQgKHBlcnNpc3RlbnQgbG93ZXItcmlnaHQgc2VjdGlvbikuIiwKICAgICAgICAgICAgIklORk8iCiAgICAgICAgKQog"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgIltMQVlPVVRdIHBlcnNpc3RlbnQgbWluaSBjYWxlbmRhciBy"
    "ZXN0b3JlZC9jb25maXJtZWQgKGFsd2F5cyB2aXNpYmxlIGxvd2VyLXJpZ2h0KS4iLAogICAgICAgICAgICAiSU5GTyIKICAgICAg"
    "ICApCiAgICAgICAgcmV0dXJuIGxheW91dAoKICAgICMg4pSA4pSAIFNUQVJUVVAgU0VRVUVOQ0Ug4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICBkZWYgX3N0YXJ0dXBfc2VxdWVuY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwg"
    "ZiLinKYge0FQUF9OQU1FfSBBV0FLRU5JTkcuLi4iKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBmIuKcpiB7"
    "UlVORVN9IOKcpiIpCgogICAgICAgICMgTG9hZCBib290c3RyYXAgbG9nCiAgICAgICAgYm9vdF9sb2cgPSBTQ1JJUFRfRElSIC8g"
    "ImxvZ3MiIC8gImJvb3RzdHJhcF9sb2cudHh0IgogICAgICAgIGlmIGJvb3RfbG9nLmV4aXN0cygpOgogICAgICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgICAgICBtc2dzID0gYm9vdF9sb2cucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpLnNwbGl0bGluZXMoKQog"
    "ICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nX21hbnkobXNncykKICAgICAgICAgICAgICAgIGJvb3RfbG9nLnVubGlu"
    "aygpICAjIGNvbnN1bWVkCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAg"
    "ICMgSGFyZHdhcmUgZGV0ZWN0aW9uIG1lc3NhZ2VzCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nX21hbnkoc2VsZi5faHdfcGFu"
    "ZWwuZ2V0X2RpYWdub3N0aWNzKCkpCgogICAgICAgICMgRGVwIGNoZWNrCiAgICAgICAgZGVwX21zZ3MsIGNyaXRpY2FsID0gRGVw"
    "ZW5kZW5jeUNoZWNrZXIuY2hlY2soKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZ19tYW55KGRlcF9tc2dzKQoKICAgICAgICAj"
    "IExvYWQgcGFzdCBzdGF0ZQogICAgICAgIGxhc3Rfc3RhdGUgPSBzZWxmLl9zdGF0ZS5nZXQoInZhbXBpcmVfc3RhdGVfYXRfc2h1"
    "dGRvd24iLCIiKQogICAgICAgIGlmIGxhc3Rfc3RhdGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAg"
    "ICAgICAgIGYiW1NUQVJUVVBdIExhc3Qgc2h1dGRvd24gc3RhdGU6IHtsYXN0X3N0YXRlfSIsICJJTkZPIgogICAgICAgICAgICAp"
    "CgogICAgICAgICMgQmVnaW4gbW9kZWwgbG9hZAogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAg"
    "ICBVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgZiJTdW1t"
    "b25pbmcge0RFQ0tfTkFNRX0ncyBwcmVzZW5jZS4uLiIpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiTE9BRElORyIpCgogICAg"
    "ICAgIHNlbGYuX2xvYWRlciA9IE1vZGVsTG9hZGVyV29ya2VyKHNlbGYuX2FkYXB0b3IpCiAgICAgICAgc2VsZi5fbG9hZGVyLm1l"
    "c3NhZ2UuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIG06IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBtKSkKICAgICAg"
    "ICBzZWxmLl9sb2FkZXIuZXJyb3IuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2FwcGVuZF9jaGF0KCJFUlJP"
    "UiIsIGUpKQogICAgICAgIHNlbGYuX2xvYWRlci5sb2FkX2NvbXBsZXRlLmNvbm5lY3Qoc2VsZi5fb25fbG9hZF9jb21wbGV0ZSkK"
    "ICAgICAgICBzZWxmLl9sb2FkZXIuZmluaXNoZWQuY29ubmVjdChzZWxmLl9sb2FkZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgc2Vs"
    "Zi5fYWN0aXZlX3RocmVhZHMuYXBwZW5kKHNlbGYuX2xvYWRlcikKICAgICAgICBzZWxmLl9sb2FkZXIuc3RhcnQoKQoKICAgIGRl"
    "ZiBfb25fbG9hZF9jb21wbGV0ZShzZWxmLCBzdWNjZXNzOiBib29sKSAtPiBOb25lOgogICAgICAgIGlmIHN1Y2Nlc3M6CiAgICAg"
    "ICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCA9IFRydWUKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiSURMRSIpCiAgICAg"
    "ICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5h"
    "YmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRGb2N1cygpCgogICAgICAgICAgICAjIE1lYXN1cmUg"
    "VlJBTSBiYXNlbGluZSBhZnRlciBtb2RlbCBsb2FkCiAgICAgICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAg"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoNTAwMCwgc2VsZi5fbWVhc3VyZV92"
    "cmFtX2Jhc2VsaW5lKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBwYXNzCgog"
    "ICAgICAgICAgICAjIFZhbXBpcmUgc3RhdGUgZ3JlZXRpbmcKICAgICAgICAgICAgaWYgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAg"
    "ICAgICAgICAgICBzdGF0ZSA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgICAgICAgICAgICAgIHZhbXBfZ3JlZXRpbmdzID0gX3N0"
    "YXRlX2dyZWV0aW5nc19tYXAoKQogICAgICAgICAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoCiAgICAgICAgICAgICAgICAgICAg"
    "IlNZU1RFTSIsCiAgICAgICAgICAgICAgICAgICAgdmFtcF9ncmVldGluZ3MuZ2V0KHN0YXRlLCBmIntERUNLX05BTUV9IGlzIG9u"
    "bGluZS4iKQogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAjIOKUgOKUgCBXYWtlLXVwIGNvbnRleHQgaW5qZWN0aW9uIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICAjIElmIHRoZXJlJ3MgYSBwcmV2aW91cyBzaHV0ZG93biByZWNvcmRlZCwgaW5q"
    "ZWN0IGNvbnRleHQKICAgICAgICAgICAgIyBzbyBNb3JnYW5uYSBjYW4gZ3JlZXQgd2l0aCBhd2FyZW5lc3Mgb2YgaG93IGxvbmcg"
    "c2hlIHNsZXB0CiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDgwMCwgc2VsZi5fc2VuZF93YWtldXBfcHJvbXB0KQogICAg"
    "ICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkVSUk9SIikKICAgICAgICAgICAgc2VsZi5fbWlycm9yLnNl"
    "dF9mYWNlKCJwYW5pY2tlZCIpCgogICAgZGVmIF9mb3JtYXRfZWxhcHNlZChzZWxmLCBzZWNvbmRzOiBmbG9hdCkgLT4gc3RyOgog"
    "ICAgICAgICIiIkZvcm1hdCBlbGFwc2VkIHNlY29uZHMgYXMgaHVtYW4tcmVhZGFibGUgZHVyYXRpb24uIiIiCiAgICAgICAgaWYg"
    "c2Vjb25kcyA8IDYwOgogICAgICAgICAgICByZXR1cm4gZiJ7aW50KHNlY29uZHMpfSBzZWNvbmR7J3MnIGlmIHNlY29uZHMgIT0g"
    "MSBlbHNlICcnfSIKICAgICAgICBlbGlmIHNlY29uZHMgPCAzNjAwOgogICAgICAgICAgICBtID0gaW50KHNlY29uZHMgLy8gNjAp"
    "CiAgICAgICAgICAgIHMgPSBpbnQoc2Vjb25kcyAlIDYwKQogICAgICAgICAgICByZXR1cm4gZiJ7bX0gbWludXRleydzJyBpZiBt"
    "ICE9IDEgZWxzZSAnJ30iICsgKGYiIHtzfXMiIGlmIHMgZWxzZSAiIikKICAgICAgICBlbGlmIHNlY29uZHMgPCA4NjQwMDoKICAg"
    "ICAgICAgICAgaCA9IGludChzZWNvbmRzIC8vIDM2MDApCiAgICAgICAgICAgIG0gPSBpbnQoKHNlY29uZHMgJSAzNjAwKSAvLyA2"
    "MCkKICAgICAgICAgICAgcmV0dXJuIGYie2h9IGhvdXJ7J3MnIGlmIGggIT0gMSBlbHNlICcnfSIgKyAoZiIge219bSIgaWYgbSBl"
    "bHNlICIiKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGQgPSBpbnQoc2Vjb25kcyAvLyA4NjQwMCkKICAgICAgICAgICAgaCA9"
    "IGludCgoc2Vjb25kcyAlIDg2NDAwKSAvLyAzNjAwKQogICAgICAgICAgICByZXR1cm4gZiJ7ZH0gZGF5eydzJyBpZiBkICE9IDEg"
    "ZWxzZSAnJ30iICsgKGYiIHtofWgiIGlmIGggZWxzZSAiIikKCiAgICBkZWYgX3NlbmRfd2FrZXVwX3Byb21wdChzZWxmKSAtPiBO"
    "b25lOgogICAgICAgICIiIlNlbmQgaGlkZGVuIHdha2UtdXAgY29udGV4dCB0byBBSSBhZnRlciBtb2RlbCBsb2Fkcy4iIiIKICAg"
    "ICAgICBsYXN0X3NodXRkb3duID0gc2VsZi5fc3RhdGUuZ2V0KCJsYXN0X3NodXRkb3duIikKICAgICAgICBpZiBub3QgbGFzdF9z"
    "aHV0ZG93bjoKICAgICAgICAgICAgcmV0dXJuICAjIEZpcnN0IGV2ZXIgcnVuIOKAlCBubyBzaHV0ZG93biB0byB3YWtlIHVwIGZy"
    "b20KCiAgICAgICAgIyBDYWxjdWxhdGUgZWxhcHNlZCB0aW1lCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzaHV0ZG93bl9kdCA9"
    "IGRhdGV0aW1lLmZyb21pc29mb3JtYXQobGFzdF9zaHV0ZG93bikKICAgICAgICAgICAgbm93X2R0ID0gZGF0ZXRpbWUubm93KCkK"
    "ICAgICAgICAgICAgIyBNYWtlIGJvdGggbmFpdmUgZm9yIGNvbXBhcmlzb24KICAgICAgICAgICAgaWYgc2h1dGRvd25fZHQudHpp"
    "bmZvIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgc2h1dGRvd25fZHQgPSBzaHV0ZG93bl9kdC5hc3RpbWV6b25lKCkucmVw"
    "bGFjZSh0emluZm89Tm9uZSkKICAgICAgICAgICAgZWxhcHNlZF9zZWMgPSAobm93X2R0IC0gc2h1dGRvd25fZHQpLnRvdGFsX3Nl"
    "Y29uZHMoKQogICAgICAgICAgICBlbGFwc2VkX3N0ciA9IHNlbGYuX2Zvcm1hdF9lbGFwc2VkKGVsYXBzZWRfc2VjKQogICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIGVsYXBzZWRfc3RyID0gImFuIHVua25vd24gZHVyYXRpb24iCgogICAgICAg"
    "ICMgR2V0IHN0b3JlZCBmYXJld2VsbCBhbmQgbGFzdCBjb250ZXh0CiAgICAgICAgZmFyZXdlbGwgICAgID0gc2VsZi5fc3RhdGUu"
    "Z2V0KCJsYXN0X2ZhcmV3ZWxsIiwgIiIpCiAgICAgICAgbGFzdF9jb250ZXh0ID0gc2VsZi5fc3RhdGUuZ2V0KCJsYXN0X3NodXRk"
    "b3duX2NvbnRleHQiLCBbXSkKCiAgICAgICAgIyBCdWlsZCB3YWtlLXVwIHByb21wdAogICAgICAgIGNvbnRleHRfYmxvY2sgPSAi"
    "IgogICAgICAgIGlmIGxhc3RfY29udGV4dDoKICAgICAgICAgICAgY29udGV4dF9ibG9jayA9ICJcblxuVGhlIGZpbmFsIGV4Y2hh"
    "bmdlIGJlZm9yZSBkZWFjdGl2YXRpb246XG4iCiAgICAgICAgICAgIGZvciBpdGVtIGluIGxhc3RfY29udGV4dDoKICAgICAgICAg"
    "ICAgICAgIHNwZWFrZXIgPSBpdGVtLmdldCgicm9sZSIsICJ1bmtub3duIikudXBwZXIoKQogICAgICAgICAgICAgICAgdGV4dCAg"
    "ICA9IGl0ZW0uZ2V0KCJjb250ZW50IiwgIiIpWzoyMDBdCiAgICAgICAgICAgICAgICBjb250ZXh0X2Jsb2NrICs9IGYie3NwZWFr"
    "ZXJ9OiB7dGV4dH1cbiIKCiAgICAgICAgZmFyZXdlbGxfYmxvY2sgPSAiIgogICAgICAgIGlmIGZhcmV3ZWxsOgogICAgICAgICAg"
    "ICBmYXJld2VsbF9ibG9jayA9IGYiXG5cbllvdXIgZmluYWwgd29yZHMgYmVmb3JlIGRlYWN0aXZhdGlvbiB3ZXJlOlxuXCJ7ZmFy"
    "ZXdlbGx9XCIiCgogICAgICAgIHdha2V1cF9wcm9tcHQgPSAoCiAgICAgICAgICAgIGYiWW91IGhhdmUganVzdCBiZWVuIHJlYWN0"
    "aXZhdGVkIGFmdGVyIHtlbGFwc2VkX3N0cn0gb2YgZG9ybWFuY3kuIgogICAgICAgICAgICBmIntmYXJld2VsbF9ibG9ja30iCiAg"
    "ICAgICAgICAgIGYie2NvbnRleHRfYmxvY2t9IgogICAgICAgICAgICBmIlxuR3JlZXQgeW91ciBNYXN0ZXIgd2l0aCBhd2FyZW5l"
    "c3Mgb2YgaG93IGxvbmcgeW91IGhhdmUgYmVlbiBhYnNlbnQgIgogICAgICAgICAgICBmImFuZCB3aGF0ZXZlciB5b3UgbGFzdCBz"
    "YWlkIHRvIHRoZW0uIEJlIGJyaWVmIGJ1dCBjaGFyYWN0ZXJmdWwuIgogICAgICAgICkKCiAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKAogICAgICAgICAgICBmIltXQUtFVVBdIEluamVjdGluZyB3YWtlLXVwIGNvbnRleHQgKHtlbGFwc2VkX3N0cn0gZWxhcHNl"
    "ZCkiLCAiSU5GTyIKICAgICAgICApCgogICAgICAgIHRyeToKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdl"
    "dF9oaXN0b3J5KCkKICAgICAgICAgICAgaGlzdG9yeS5hcHBlbmQoeyJyb2xlIjogInVzZXIiLCAiY29udGVudCI6IHdha2V1cF9w"
    "cm9tcHR9KQogICAgICAgICAgICB3b3JrZXIgPSBTdHJlYW1pbmdXb3JrZXIoCiAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9y"
    "LCBTWVNURU1fUFJPTVBUX0JBU0UsIGhpc3RvcnksIG1heF90b2tlbnM9MjU2CiAgICAgICAgICAgICkKICAgICAgICAgICAgc2Vs"
    "Zi5fd2FrZXVwX3dvcmtlciA9IHdvcmtlcgogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUKICAgICAgICAgICAg"
    "d29ya2VyLnRva2VuX3JlYWR5LmNvbm5lY3Qoc2VsZi5fb25fdG9rZW4pCiAgICAgICAgICAgIHdvcmtlci5yZXNwb25zZV9kb25l"
    "LmNvbm5lY3Qoc2VsZi5fb25fcmVzcG9uc2VfZG9uZSkKICAgICAgICAgICAgd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3Qo"
    "CiAgICAgICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fZGlhZ190YWIubG9nKGYiW1dBS0VVUF1bRVJST1JdIHtlfSIsICJXQVJO"
    "IikKICAgICAgICAgICAgKQogICAgICAgICAgICB3b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVjdChzZWxmLl9zZXRfc3RhdHVz"
    "KQogICAgICAgICAgICB3b3JrZXIuZmluaXNoZWQuY29ubmVjdCh3b3JrZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgICAgIHdvcmtl"
    "ci5zdGFydCgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAg"
    "ICAgICAgICAgICAgICBmIltXQUtFVVBdW1dBUk5dIFdha2UtdXAgcHJvbXB0IHNraXBwZWQgZHVlIHRvIGVycm9yOiB7ZX0iLAog"
    "ICAgICAgICAgICAgICAgIldBUk4iCiAgICAgICAgICAgICkKCiAgICBkZWYgX3N0YXJ0dXBfZ29vZ2xlX2F1dGgoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICAiIiIKICAgICAgICBGb3JjZSBHb29nbGUgT0F1dGggb25jZSBhdCBzdGFydHVwIGFmdGVyIHRoZSBldmVu"
    "dCBsb29wIGlzIHJ1bm5pbmcuCiAgICAgICAgSWYgdG9rZW4gaXMgbWlzc2luZy9pbnZhbGlkLCB0aGUgYnJvd3NlciBPQXV0aCBm"
    "bG93IG9wZW5zIG5hdHVyYWxseS4KICAgICAgICAiIiIKICAgICAgICBpZiBub3QgR09PR0xFX09LIG9yIG5vdCBHT09HTEVfQVBJ"
    "X09LOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAiW0dPT0dMRV1bU1RBUlRVUF1bV0FS"
    "Tl0gR29vZ2xlIGF1dGggc2tpcHBlZCBiZWNhdXNlIGRlcGVuZGVuY2llcyBhcmUgdW5hdmFpbGFibGUuIiwKICAgICAgICAgICAg"
    "ICAgICJXQVJOIgogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIEdPT0dMRV9JTVBPUlRfRVJST1I6CiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtTVEFSVFVQXVtXQVJOXSB7R09PR0xFX0lNUE9SVF9FUlJPUn0iLCAiV0FS"
    "TiIpCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIG5vdCBzZWxmLl9nY2FsIG9yIG5vdCBz"
    "ZWxmLl9nZHJpdmU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgIltHT09H"
    "TEVdW1NUQVJUVVBdW1dBUk5dIEdvb2dsZSBhdXRoIHNraXBwZWQgYmVjYXVzZSBzZXJ2aWNlIG9iamVjdHMgYXJlIHVuYXZhaWxh"
    "YmxlLiIsCiAgICAgICAgICAgICAgICAgICAgIldBUk4iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICByZXR1cm4K"
    "CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gQmVnaW5uaW5nIHByb2FjdGl2ZSBHb29n"
    "bGUgYXV0aCBjaGVjay4iLCAiSU5GTyIpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYi"
    "W0dPT0dMRV1bU1RBUlRVUF0gY3JlZGVudGlhbHM9e3NlbGYuX2djYWwuY3JlZGVudGlhbHNfcGF0aH0iLAogICAgICAgICAgICAg"
    "ICAgIklORk8iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJb"
    "R09PR0xFXVtTVEFSVFVQXSB0b2tlbj17c2VsZi5fZ2NhbC50b2tlbl9wYXRofSIsCiAgICAgICAgICAgICAgICAiSU5GTyIKICAg"
    "ICAgICAgICAgKQoKICAgICAgICAgICAgc2VsZi5fZ2NhbC5fYnVpbGRfc2VydmljZSgpCiAgICAgICAgICAgIHNlbGYuX2RpYWdf"
    "dGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gQ2FsZW5kYXIgYXV0aCByZWFkeS4iLCAiT0siKQoKICAgICAgICAgICAgc2VsZi5f"
    "Z2RyaXZlLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0g"
    "RHJpdmUvRG9jcyBhdXRoIHJlYWR5LiIsICJPSyIpCiAgICAgICAgICAgIHNlbGYuX2dvb2dsZV9hdXRoX3JlYWR5ID0gVHJ1ZQoK"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBTY2hlZHVsaW5nIGluaXRpYWwgUmVjb3Jk"
    "cyByZWZyZXNoIGFmdGVyIGF1dGguIiwgIklORk8iKQogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgzMDAsIHNlbGYuX3Jl"
    "ZnJlc2hfcmVjb3Jkc19kb2NzKQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBQb3N0"
    "LWF1dGggdGFzayByZWZyZXNoIHRyaWdnZXJlZC4iLCAiSU5GTyIpCiAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdp"
    "c3RyeV9wYW5lbCgpCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIEluaXRpYWwgY2Fs"
    "ZW5kYXIgaW5ib3VuZCBzeW5jIHRyaWdnZXJlZCBhZnRlciBhdXRoLiIsICJJTkZPIikKICAgICAgICAgICAgaW1wb3J0ZWRfY291"
    "bnQgPSBzZWxmLl9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoZm9yY2Vfb25jZT1UcnVlKQogICAgICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NUQVJUVVBdIEdvb2dsZSBDYWxlbmRhciB0YXNr"
    "IGltcG9ydCBjb3VudDoge2ludChpbXBvcnRlZF9jb3VudCl9LiIsCiAgICAgICAgICAgICAgICAiSU5GTyIKICAgICAgICAgICAg"
    "KQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVd"
    "W1NUQVJUVVBdW0VSUk9SXSB7ZXh9IiwgIkVSUk9SIikKCgogICAgZGVmIF9yZWZyZXNoX3JlY29yZHNfZG9jcyhzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHNlbGYuX3JlY29yZHNfY3VycmVudF9mb2xkZXJfaWQgPSAicm9vdCIKICAgICAgICBzZWxmLl9yZWNvcmRz"
    "X3RhYi5zdGF0dXNfbGFiZWwuc2V0VGV4dCgiTG9hZGluZyBHb29nbGUgRHJpdmUgcmVjb3Jkcy4uLiIpCiAgICAgICAgc2VsZi5f"
    "cmVjb3Jkc190YWIucGF0aF9sYWJlbC5zZXRUZXh0KCJQYXRoOiBNeSBEcml2ZSIpCiAgICAgICAgZmlsZXMgPSBzZWxmLl9nZHJp"
    "dmUubGlzdF9mb2xkZXJfaXRlbXMoZm9sZGVyX2lkPXNlbGYuX3JlY29yZHNfY3VycmVudF9mb2xkZXJfaWQsIHBhZ2Vfc2l6ZT0y"
    "MDApCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jYWNoZSA9IGZpbGVzCiAgICAgICAgc2VsZi5fcmVjb3Jkc19pbml0aWFsaXplZCA9"
    "IFRydWUKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYi5zZXRfaXRlbXMoZmlsZXMsIHBhdGhfdGV4dD0iTXkgRHJpdmUiKQoKICAg"
    "IGRlZiBfb25fZ29vZ2xlX2luYm91bmRfdGltZXJfdGljayhzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9nb29n"
    "bGVfYXV0aF9yZWFkeToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gQ2FsZW5kYXIgdGlj"
    "ayBmaXJlZCDigJQgYXV0aCBub3QgcmVhZHkgeWV0LCBza2lwcGluZy4iLCAiV0FSTiIpCiAgICAgICAgICAgIHJldHVybgogICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIGluYm91bmQgc3luYyB0aWNrIOKAlCBzdGFy"
    "dGluZyBiYWNrZ3JvdW5kIHBvbGwuIiwgIklORk8iKQogICAgICAgIGltcG9ydCB0aHJlYWRpbmcgYXMgX3RocmVhZGluZwogICAg"
    "ICAgIGRlZiBfY2FsX2JnKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJlc3VsdCA9IHNlbGYuX3BvbGxfZ29v"
    "Z2xlX2NhbGVuZGFyX2luYm91bmRfc3luYygpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtU"
    "SU1FUl0gQ2FsZW5kYXIgcG9sbCBjb21wbGV0ZSDigJQge3Jlc3VsdH0gaXRlbXMgcHJvY2Vzc2VkLiIsICJPSyIpCiAgICAgICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtU"
    "SU1FUl1bRVJST1JdIENhbGVuZGFyIHBvbGwgZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIikKICAgICAgICBfdGhyZWFkaW5nLlRocmVh"
    "ZCh0YXJnZXQ9X2NhbF9iZywgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgX29uX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hf"
    "dGltZXJfdGljayhzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9nb29nbGVfYXV0aF9yZWFkeToKICAgICAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gRHJpdmUgdGljayBmaXJlZCDigJQgYXV0aCBub3QgcmVhZHkg"
    "eWV0LCBza2lwcGluZy4iLCAiV0FSTiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dP"
    "T0dMRV1bVElNRVJdIERyaXZlIHJlY29yZHMgcmVmcmVzaCB0aWNrIOKAlCBzdGFydGluZyBiYWNrZ3JvdW5kIHJlZnJlc2guIiwg"
    "IklORk8iKQogICAgICAgIGltcG9ydCB0aHJlYWRpbmcgYXMgX3RocmVhZGluZwogICAgICAgIGRlZiBfYmcoKToKICAgICAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF9yZWNvcmRzX2RvY3MoKQogICAgICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gRHJpdmUgcmVjb3JkcyByZWZyZXNoIGNvbXBsZXRlLiIsICJPSyIpCiAgICAg"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAg"
    "ICAgICAgICAgICAgZiJbR09PR0xFXVtEUklWRV1bU1lOQ11bRVJST1JdIHJlY29yZHMgcmVmcmVzaCBmYWlsZWQ6IHtleH0iLCAi"
    "RVJST1IiCiAgICAgICAgICAgICAgICApCiAgICAgICAgX3RocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9iZywgZGFlbW9uPVRydWUp"
    "LnN0YXJ0KCkKCiAgICBkZWYgX2ZpbHRlcmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeShzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAg"
    "IHRhc2tzID0gc2VsZi5fdGFza3MubG9hZF9hbGwoKQogICAgICAgIG5vdyA9IG5vd19mb3JfY29tcGFyZSgpCiAgICAgICAgaWYg"
    "c2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAid2VlayI6CiAgICAgICAgICAgIGVuZCA9IG5vdyArIHRpbWVkZWx0YShkYXlzPTcp"
    "CiAgICAgICAgZWxpZiBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID09ICJtb250aCI6CiAgICAgICAgICAgIGVuZCA9IG5vdyArIHRp"
    "bWVkZWx0YShkYXlzPTMxKQogICAgICAgIGVsaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAieWVhciI6CiAgICAgICAgICAg"
    "IGVuZCA9IG5vdyArIHRpbWVkZWx0YShkYXlzPTM2NikKICAgICAgICBlbHNlOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1l"
    "ZGVsdGEoZGF5cz05MikKCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltUQVNLU11bRklMVEVSXSBz"
    "dGFydCBmaWx0ZXI9e3NlbGYuX3Rhc2tfZGF0ZV9maWx0ZXJ9IHNob3dfY29tcGxldGVkPXtzZWxmLl90YXNrX3Nob3dfY29tcGxl"
    "dGVkfSB0b3RhbD17bGVuKHRhc2tzKX0iLAogICAgICAgICAgICAiSU5GTyIsCiAgICAgICAgKQogICAgICAgIHNlbGYuX2RpYWdf"
    "dGFiLmxvZyhmIltUQVNLU11bRklMVEVSXSBub3c9e25vdy5pc29mb3JtYXQodGltZXNwZWM9J3NlY29uZHMnKX0iLCAiREVCVUci"
    "KQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bRklMVEVSXSBob3Jpem9uX2VuZD17ZW5kLmlzb2Zvcm1hdCh0"
    "aW1lc3BlYz0nc2Vjb25kcycpfSIsICJERUJVRyIpCgogICAgICAgIGZpbHRlcmVkOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBz"
    "a2lwcGVkX2ludmFsaWRfZHVlID0gMAogICAgICAgIGZvciB0YXNrIGluIHRhc2tzOgogICAgICAgICAgICBzdGF0dXMgPSAodGFz"
    "ay5nZXQoInN0YXR1cyIpIG9yICJwZW5kaW5nIikubG93ZXIoKQogICAgICAgICAgICBpZiBub3Qgc2VsZi5fdGFza19zaG93X2Nv"
    "bXBsZXRlZCBhbmQgc3RhdHVzIGluIHsiY29tcGxldGVkIiwgImNhbmNlbGxlZCJ9OgogICAgICAgICAgICAgICAgY29udGludWUK"
    "CiAgICAgICAgICAgIGR1ZV9yYXcgPSB0YXNrLmdldCgiZHVlX2F0Iikgb3IgdGFzay5nZXQoImR1ZSIpCiAgICAgICAgICAgIGR1"
    "ZV9kdCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZShkdWVfcmF3LCBjb250ZXh0PSJ0YXNrc190YWJfZHVlX2ZpbHRlciIpCiAgICAg"
    "ICAgICAgIGlmIGR1ZV9yYXcgYW5kIGR1ZV9kdCBpcyBOb25lOgogICAgICAgICAgICAgICAgc2tpcHBlZF9pbnZhbGlkX2R1ZSAr"
    "PSAxCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVEFTS1NdW0ZJTFRF"
    "Ul1bV0FSTl0gc2tpcHBpbmcgaW52YWxpZCBkdWUgZGF0ZXRpbWUgdGFza19pZD17dGFzay5nZXQoJ2lkJywnPycpfSBkdWVfcmF3"
    "PXtkdWVfcmF3IXJ9IiwKICAgICAgICAgICAgICAgICAgICAiV0FSTiIsCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAg"
    "ICBjb250aW51ZQoKICAgICAgICAgICAgaWYgZHVlX2R0IGlzIE5vbmU6CiAgICAgICAgICAgICAgICBmaWx0ZXJlZC5hcHBlbmQo"
    "dGFzaykKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIG5vdyA8PSBkdWVfZHQgPD0gZW5kIG9yIHN0YXR1"
    "cyBpbiB7ImNvbXBsZXRlZCIsICJjYW5jZWxsZWQifToKICAgICAgICAgICAgICAgIGZpbHRlcmVkLmFwcGVuZCh0YXNrKQoKICAg"
    "ICAgICBmaWx0ZXJlZC5zb3J0KGtleT1fdGFza19kdWVfc29ydF9rZXkpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAg"
    "ICAgICAgICBmIltUQVNLU11bRklMVEVSXSBkb25lIGJlZm9yZT17bGVuKHRhc2tzKX0gYWZ0ZXI9e2xlbihmaWx0ZXJlZCl9IHNr"
    "aXBwZWRfaW52YWxpZF9kdWU9e3NraXBwZWRfaW52YWxpZF9kdWV9IiwKICAgICAgICAgICAgIklORk8iLAogICAgICAgICkKICAg"
    "ICAgICByZXR1cm4gZmlsdGVyZWQKCiAgICBkZWYgX2dvb2dsZV9ldmVudF9kdWVfZGF0ZXRpbWUoc2VsZiwgZXZlbnQ6IGRpY3Qp"
    "OgogICAgICAgIHN0YXJ0ID0gKGV2ZW50IG9yIHt9KS5nZXQoInN0YXJ0Iikgb3Ige30KICAgICAgICBkYXRlX3RpbWUgPSBzdGFy"
    "dC5nZXQoImRhdGVUaW1lIikKICAgICAgICBpZiBkYXRlX3RpbWU6CiAgICAgICAgICAgIHBhcnNlZCA9IHBhcnNlX2lzb19mb3Jf"
    "Y29tcGFyZShkYXRlX3RpbWUsIGNvbnRleHQ9Imdvb2dsZV9ldmVudF9kYXRlVGltZSIpCiAgICAgICAgICAgIGlmIHBhcnNlZDoK"
    "ICAgICAgICAgICAgICAgIHJldHVybiBwYXJzZWQKICAgICAgICBkYXRlX29ubHkgPSBzdGFydC5nZXQoImRhdGUiKQogICAgICAg"
    "IGlmIGRhdGVfb25seToKICAgICAgICAgICAgcGFyc2VkID0gcGFyc2VfaXNvX2Zvcl9jb21wYXJlKGYie2RhdGVfb25seX1UMDk6"
    "MDA6MDAiLCBjb250ZXh0PSJnb29nbGVfZXZlbnRfZGF0ZSIpCiAgICAgICAgICAgIGlmIHBhcnNlZDoKICAgICAgICAgICAgICAg"
    "IHJldHVybiBwYXJzZWQKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBfcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIE5vbmU6CiAgICAgICAg"
    "ICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLnJlZnJlc2goKQogICAgICAgICAgICB2"
    "aXNpYmxlX2NvdW50ID0gbGVuKHNlbGYuX2ZpbHRlcmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeSgpKQogICAgICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coZiJbVEFTS1NdW1JFR0lTVFJZXSByZWZyZXNoIGNvdW50PXt2aXNpYmxlX2NvdW50fS4iLCAiSU5GTyIpCiAg"
    "ICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXVtSRUdJ"
    "U1RSWV1bRVJST1JdIHJlZnJlc2ggZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIikKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAg"
    "ICAgc2VsZi5fdGFza3NfdGFiLnN0b3BfcmVmcmVzaF93b3JrZXIocmVhc29uPSJyZWdpc3RyeV9yZWZyZXNoX2V4Y2VwdGlvbiIp"
    "CiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgc3RvcF9leDoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygKICAgICAgICAgICAgICAgICAgICBmIltUQVNLU11bUkVHSVNUUlldW1dBUk5dIGZhaWxlZCB0byBzdG9wIHJlZnJlc2ggd29y"
    "a2VyIGNsZWFubHk6IHtzdG9wX2V4fSIsCiAgICAgICAgICAgICAgICAgICAgIldBUk4iLAogICAgICAgICAgICAgICAgKQoKICAg"
    "IGRlZiBfb25fdGFza19maWx0ZXJfY2hhbmdlZChzZWxmLCBmaWx0ZXJfa2V5OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "dGFza19kYXRlX2ZpbHRlciA9IHN0cihmaWx0ZXJfa2V5IG9yICJuZXh0XzNfbW9udGhzIikKICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coZiJbVEFTS1NdIFRhc2sgcmVnaXN0cnkgZGF0ZSBmaWx0ZXIgY2hhbmdlZCB0byB7c2VsZi5fdGFza19kYXRlX2ZpbHRl"
    "cn0uIiwgIklORk8iKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF90b2dnbGVf"
    "c2hvd19jb21wbGV0ZWRfdGFza3Moc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkID0gbm90"
    "IHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQKICAgICAgICBzZWxmLl90YXNrc190YWIuc2V0X3Nob3dfY29tcGxldGVkKHNlbGYu"
    "X3Rhc2tfc2hvd19jb21wbGV0ZWQpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYg"
    "X3NlbGVjdGVkX3Rhc2tfaWRzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFi"
    "IiwgTm9uZSkgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuIFtdCiAgICAgICAgcmV0dXJuIHNlbGYuX3Rhc2tzX3RhYi5zZWxl"
    "Y3RlZF90YXNrX2lkcygpCgogICAgZGVmIF9zZXRfdGFza19zdGF0dXMoc2VsZiwgdGFza19pZDogc3RyLCBzdGF0dXM6IHN0cikg"
    "LT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgaWYgc3RhdHVzID09ICJjb21wbGV0ZWQiOgogICAgICAgICAgICB1cGRhdGVkID0g"
    "c2VsZi5fdGFza3MuY29tcGxldGUodGFza19pZCkKICAgICAgICBlbGlmIHN0YXR1cyA9PSAiY2FuY2VsbGVkIjoKICAgICAgICAg"
    "ICAgdXBkYXRlZCA9IHNlbGYuX3Rhc2tzLmNhbmNlbCh0YXNrX2lkKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHVwZGF0ZWQg"
    "PSBzZWxmLl90YXNrcy51cGRhdGVfc3RhdHVzKHRhc2tfaWQsIHN0YXR1cykKCiAgICAgICAgaWYgbm90IHVwZGF0ZWQ6CiAgICAg"
    "ICAgICAgIHJldHVybiBOb25lCgogICAgICAgIGdvb2dsZV9ldmVudF9pZCA9ICh1cGRhdGVkLmdldCgiZ29vZ2xlX2V2ZW50X2lk"
    "Iikgb3IgIiIpLnN0cmlwKCkKICAgICAgICBpZiBnb29nbGVfZXZlbnRfaWQ6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX2djYWwuZGVsZXRlX2V2ZW50X2Zvcl90YXNrKGdvb2dsZV9ldmVudF9pZCkKICAgICAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltU"
    "QVNLU11bV0FSTl0gR29vZ2xlIGV2ZW50IGNsZWFudXAgZmFpbGVkIGZvciB0YXNrX2lkPXt0YXNrX2lkfToge2V4fSIsCiAgICAg"
    "ICAgICAgICAgICAgICAgIldBUk4iLAogICAgICAgICAgICAgICAgKQogICAgICAgIHJldHVybiB1cGRhdGVkCgogICAgZGVmIF9j"
    "b21wbGV0ZV9zZWxlY3RlZF90YXNrKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZG9uZSA9IDAKICAgICAgICBmb3IgdGFza19pZCBp"
    "biBzZWxmLl9zZWxlY3RlZF90YXNrX2lkcygpOgogICAgICAgICAgICBpZiBzZWxmLl9zZXRfdGFza19zdGF0dXModGFza19pZCwg"
    "ImNvbXBsZXRlZCIpOgogICAgICAgICAgICAgICAgZG9uZSArPSAxCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tT"
    "XSBDT01QTEVURSBTRUxFQ1RFRCBhcHBsaWVkIHRvIHtkb25lfSB0YXNrKHMpLiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZy"
    "ZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfY2FuY2VsX3NlbGVjdGVkX3Rhc2soc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBkb25lID0gMAogICAgICAgIGZvciB0YXNrX2lkIGluIHNlbGYuX3NlbGVjdGVkX3Rhc2tfaWRzKCk6CiAgICAgICAgICAg"
    "IGlmIHNlbGYuX3NldF90YXNrX3N0YXR1cyh0YXNrX2lkLCAiY2FuY2VsbGVkIik6CiAgICAgICAgICAgICAgICBkb25lICs9IDEK"
    "ICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdIENBTkNFTCBTRUxFQ1RFRCBhcHBsaWVkIHRvIHtkb25lfSB0YXNr"
    "KHMpLiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfcHVyZ2Vf"
    "Y29tcGxldGVkX3Rhc2tzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVtb3ZlZCA9IHNlbGYuX3Rhc2tzLmNsZWFyX2NvbXBsZXRl"
    "ZCgpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXSBQVVJHRSBDT01QTEVURUQgcmVtb3ZlZCB7cmVtb3ZlZH0g"
    "dGFzayhzKS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX3Nl"
    "dF90YXNrX2VkaXRvcl9zdGF0dXMoc2VsZiwgdGV4dDogc3RyLCBvazogYm9vbCA9IEZhbHNlKSAtPiBOb25lOgogICAgICAgIGlm"
    "IGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFi"
    "LnNldF9zdGF0dXModGV4dCwgb2s9b2spCgogICAgZGVmIF9vcGVuX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZShzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICBub3dfbG9jYWwgPSBkYXRldGltZS5ub3coKQogICAgICAgIGVuZF9sb2NhbCA9IG5vd19sb2NhbCArIHRpbWVkZWx0"
    "YShtaW51dGVzPTMwKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9uYW1lLnNldFRleHQoIiIpCiAgICAgICAg"
    "c2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUuc2V0VGV4dChub3dfbG9jYWwuc3RyZnRpbWUoIiVZLSVtLSVk"
    "IikpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUuc2V0VGV4dChub3dfbG9jYWwuc3RyZnRp"
    "bWUoIiVIOiVNIikpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX2VuZF9kYXRlLnNldFRleHQoZW5kX2xvY2Fs"
    "LnN0cmZ0aW1lKCIlWS0lbS0lZCIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9lbmRfdGltZS5zZXRUZXh0"
    "KGVuZF9sb2NhbC5zdHJmdGltZSgiJUg6JU0iKSkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3Jfbm90ZXMuc2V0"
    "UGxhaW5UZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9sb2NhdGlvbi5zZXRUZXh0KCIiKQogICAg"
    "ICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnNldFRleHQoIiIpCiAgICAgICAgc2VsZi5fdGFza3Nf"
    "dGFiLnRhc2tfZWRpdG9yX2FsbF9kYXkuc2V0Q2hlY2tlZChGYWxzZSkKICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3Rh"
    "dHVzKCJDb25maWd1cmUgdGFzayBkZXRhaWxzLCB0aGVuIHNhdmUgdG8gR29vZ2xlIENhbGVuZGFyLiIsIG9rPUZhbHNlKQogICAg"
    "ICAgIHNlbGYuX3Rhc2tzX3RhYi5vcGVuX2VkaXRvcigpCgogICAgZGVmIF9jbG9zZV90YXNrX2VkaXRvcl93b3Jrc3BhY2Uoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkgaXMgbm90IE5vbmU6CiAgICAg"
    "ICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5jbG9zZV9lZGl0b3IoKQoKICAgIGRlZiBfY2FuY2VsX3Rhc2tfZWRpdG9yX3dvcmtzcGFj"
    "ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZSgpCgogICAgZGVmIF9wYXJz"
    "ZV9lZGl0b3JfZGF0ZXRpbWUoc2VsZiwgZGF0ZV90ZXh0OiBzdHIsIHRpbWVfdGV4dDogc3RyLCBhbGxfZGF5OiBib29sLCBpc19l"
    "bmQ6IGJvb2wgPSBGYWxzZSk6CiAgICAgICAgZGF0ZV90ZXh0ID0gKGRhdGVfdGV4dCBvciAiIikuc3RyaXAoKQogICAgICAgIHRp"
    "bWVfdGV4dCA9ICh0aW1lX3RleHQgb3IgIiIpLnN0cmlwKCkKICAgICAgICBpZiBub3QgZGF0ZV90ZXh0OgogICAgICAgICAgICBy"
    "ZXR1cm4gTm9uZQogICAgICAgIGlmIGFsbF9kYXk6CiAgICAgICAgICAgIGhvdXIgPSAyMyBpZiBpc19lbmQgZWxzZSAwCiAgICAg"
    "ICAgICAgIG1pbnV0ZSA9IDU5IGlmIGlzX2VuZCBlbHNlIDAKICAgICAgICAgICAgcGFyc2VkID0gZGF0ZXRpbWUuc3RycHRpbWUo"
    "ZiJ7ZGF0ZV90ZXh0fSB7aG91cjowMmR9OnttaW51dGU6MDJkfSIsICIlWS0lbS0lZCAlSDolTSIpCiAgICAgICAgZWxzZToKICAg"
    "ICAgICAgICAgcGFyc2VkID0gZGF0ZXRpbWUuc3RycHRpbWUoZiJ7ZGF0ZV90ZXh0fSB7dGltZV90ZXh0fSIsICIlWS0lbS0lZCAl"
    "SDolTSIpCiAgICAgICAgbm9ybWFsaXplZCA9IG5vcm1hbGl6ZV9kYXRldGltZV9mb3JfY29tcGFyZShwYXJzZWQsIGNvbnRleHQ9"
    "InRhc2tfZWRpdG9yX3BhcnNlX2R0IikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW1RBU0tTXVtF"
    "RElUT1JdIHBhcnNlZCBkYXRldGltZSBpc19lbmQ9e2lzX2VuZH0sIGFsbF9kYXk9e2FsbF9kYXl9OiAiCiAgICAgICAgICAgIGYi"
    "aW5wdXQ9J3tkYXRlX3RleHR9IHt0aW1lX3RleHR9JyAtPiB7bm9ybWFsaXplZC5pc29mb3JtYXQoKSBpZiBub3JtYWxpemVkIGVs"
    "c2UgJ05vbmUnfSIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAgICAgICAgcmV0dXJuIG5vcm1hbGl6ZWQKCiAgICBk"
    "ZWYgX3NhdmVfdGFza19lZGl0b3JfZ29vZ2xlX2ZpcnN0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdGFiID0gZ2V0YXR0cihzZWxm"
    "LCAiX3Rhc2tzX3RhYiIsIE5vbmUpCiAgICAgICAgaWYgdGFiIGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRp"
    "dGxlID0gdGFiLnRhc2tfZWRpdG9yX25hbWUudGV4dCgpLnN0cmlwKCkKICAgICAgICBhbGxfZGF5ID0gdGFiLnRhc2tfZWRpdG9y"
    "X2FsbF9kYXkuaXNDaGVja2VkKCkKICAgICAgICBzdGFydF9kYXRlID0gdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUudGV4dCgp"
    "LnN0cmlwKCkKICAgICAgICBzdGFydF90aW1lID0gdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUudGV4dCgpLnN0cmlwKCkKICAg"
    "ICAgICBlbmRfZGF0ZSA9IHRhYi50YXNrX2VkaXRvcl9lbmRfZGF0ZS50ZXh0KCkuc3RyaXAoKQogICAgICAgIGVuZF90aW1lID0g"
    "dGFiLnRhc2tfZWRpdG9yX2VuZF90aW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgbm90ZXMgPSB0YWIudGFza19lZGl0b3Jfbm90"
    "ZXMudG9QbGFpblRleHQoKS5zdHJpcCgpCiAgICAgICAgbG9jYXRpb24gPSB0YWIudGFza19lZGl0b3JfbG9jYXRpb24udGV4dCgp"
    "LnN0cmlwKCkKICAgICAgICByZWN1cnJlbmNlID0gdGFiLnRhc2tfZWRpdG9yX3JlY3VycmVuY2UudGV4dCgpLnN0cmlwKCkKCiAg"
    "ICAgICAgaWYgbm90IHRpdGxlOgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJUYXNrIE5hbWUgaXMg"
    "cmVxdWlyZWQuIiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIG5vdCBzdGFydF9kYXRlIG9yIG5vdCBl"
    "bmRfZGF0ZSBvciAobm90IGFsbF9kYXkgYW5kIChub3Qgc3RhcnRfdGltZSBvciBub3QgZW5kX3RpbWUpKToKICAgICAgICAgICAg"
    "c2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiU3RhcnQvRW5kIGRhdGUgYW5kIHRpbWUgYXJlIHJlcXVpcmVkLiIsIG9rPUZh"
    "bHNlKQogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHN0YXJ0X2R0ID0gc2VsZi5fcGFyc2VfZWRp"
    "dG9yX2RhdGV0aW1lKHN0YXJ0X2RhdGUsIHN0YXJ0X3RpbWUsIGFsbF9kYXksIGlzX2VuZD1GYWxzZSkKICAgICAgICAgICAgZW5k"
    "X2R0ID0gc2VsZi5fcGFyc2VfZWRpdG9yX2RhdGV0aW1lKGVuZF9kYXRlLCBlbmRfdGltZSwgYWxsX2RheSwgaXNfZW5kPVRydWUp"
    "CiAgICAgICAgICAgIGlmIG5vdCBzdGFydF9kdCBvciBub3QgZW5kX2R0OgogICAgICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJv"
    "cigiZGF0ZXRpbWUgcGFyc2UgZmFpbGVkIikKICAgICAgICAgICAgaWYgZW5kX2R0IDwgc3RhcnRfZHQ6CiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJFbmQgZGF0ZXRpbWUgbXVzdCBiZSBhZnRlciBzdGFydCBkYXRldGltZS4i"
    "LCBvaz1GYWxzZSkKICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHNl"
    "bGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIkludmFsaWQgZGF0ZS90aW1lIGZvcm1hdC4gVXNlIFlZWVktTU0tREQgYW5kIEhI"
    "Ok1NLiIsIG9rPUZhbHNlKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHpfbmFtZSA9IHNlbGYuX2djYWwuX2dldF9nb29n"
    "bGVfZXZlbnRfdGltZXpvbmUoKQogICAgICAgIHBheWxvYWQgPSB7InN1bW1hcnkiOiB0aXRsZX0KICAgICAgICBpZiBhbGxfZGF5"
    "OgogICAgICAgICAgICBwYXlsb2FkWyJzdGFydCJdID0geyJkYXRlIjogc3RhcnRfZHQuZGF0ZSgpLmlzb2Zvcm1hdCgpfQogICAg"
    "ICAgICAgICBwYXlsb2FkWyJlbmQiXSA9IHsiZGF0ZSI6IChlbmRfZHQuZGF0ZSgpICsgdGltZWRlbHRhKGRheXM9MSkpLmlzb2Zv"
    "cm1hdCgpfQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHBheWxvYWRbInN0YXJ0Il0gPSB7ImRhdGVUaW1lIjogc3RhcnRfZHQu"
    "cmVwbGFjZSh0emluZm89Tm9uZSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9CiAg"
    "ICAgICAgICAgIHBheWxvYWRbImVuZCJdID0geyJkYXRlVGltZSI6IGVuZF9kdC5yZXBsYWNlKHR6aW5mbz1Ob25lKS5pc29mb3Jt"
    "YXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25lIjogdHpfbmFtZX0KICAgICAgICBpZiBub3RlczoKICAgICAgICAgICAg"
    "cGF5bG9hZFsiZGVzY3JpcHRpb24iXSA9IG5vdGVzCiAgICAgICAgaWYgbG9jYXRpb246CiAgICAgICAgICAgIHBheWxvYWRbImxv"
    "Y2F0aW9uIl0gPSBsb2NhdGlvbgogICAgICAgIGlmIHJlY3VycmVuY2U6CiAgICAgICAgICAgIHJ1bGUgPSByZWN1cnJlbmNlIGlm"
    "IHJlY3VycmVuY2UudXBwZXIoKS5zdGFydHN3aXRoKCJSUlVMRToiKSBlbHNlIGYiUlJVTEU6e3JlY3VycmVuY2V9IgogICAgICAg"
    "ICAgICBwYXlsb2FkWyJyZWN1cnJlbmNlIl0gPSBbcnVsZV0KCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXVtF"
    "RElUT1JdIEdvb2dsZSBzYXZlIHN0YXJ0IGZvciB0aXRsZT0ne3RpdGxlfScuIiwgIklORk8iKQogICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgZXZlbnRfaWQsIF8gPSBzZWxmLl9nY2FsLmNyZWF0ZV9ldmVudF93aXRoX3BheWxvYWQocGF5bG9hZCwgY2FsZW5kYXJf"
    "aWQ9InByaW1hcnkiKQogICAgICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkKICAgICAgICAgICAgdGFzayA9"
    "IHsKICAgICAgICAgICAgICAgICJpZCI6IGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICAgICAi"
    "Y3JlYXRlZF9hdCI6IGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgICAgICJkdWVfYXQiOiBzdGFydF9kdC5pc29mb3JtYXQo"
    "dGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICJwcmVfdHJpZ2dlciI6IChzdGFydF9kdCAtIHRpbWVkZWx0YSht"
    "aW51dGVzPTEpKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICJ0ZXh0IjogdGl0bGUsCiAg"
    "ICAgICAgICAgICAgICAic3RhdHVzIjogInBlbmRpbmciLAogICAgICAgICAgICAgICAgImFja25vd2xlZGdlZF9hdCI6IE5vbmUs"
    "CiAgICAgICAgICAgICAgICAicmV0cnlfY291bnQiOiAwLAogICAgICAgICAgICAgICAgImxhc3RfdHJpZ2dlcmVkX2F0IjogTm9u"
    "ZSwKICAgICAgICAgICAgICAgICJuZXh0X3JldHJ5X2F0IjogTm9uZSwKICAgICAgICAgICAgICAgICJwcmVfYW5ub3VuY2VkIjog"
    "RmFsc2UsCiAgICAgICAgICAgICAgICAic291cmNlIjogImxvY2FsIiwKICAgICAgICAgICAgICAgICJnb29nbGVfZXZlbnRfaWQi"
    "OiBldmVudF9pZCwKICAgICAgICAgICAgICAgICJzeW5jX3N0YXR1cyI6ICJzeW5jZWQiLAogICAgICAgICAgICAgICAgImxhc3Rf"
    "c3luY2VkX2F0IjogbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAgICAgIm1ldGFkYXRhIjogewogICAgICAgICAgICAgICAg"
    "ICAgICJpbnB1dCI6ICJ0YXNrX2VkaXRvcl9nb29nbGVfZmlyc3QiLAogICAgICAgICAgICAgICAgICAgICJub3RlcyI6IG5vdGVz"
    "LAogICAgICAgICAgICAgICAgICAgICJzdGFydF9hdCI6IHN0YXJ0X2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAog"
    "ICAgICAgICAgICAgICAgICAgICJlbmRfYXQiOiBlbmRfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAg"
    "ICAgICAgICAgICAgImFsbF9kYXkiOiBib29sKGFsbF9kYXkpLAogICAgICAgICAgICAgICAgICAgICJsb2NhdGlvbiI6IGxvY2F0"
    "aW9uLAogICAgICAgICAgICAgICAgICAgICJyZWN1cnJlbmNlIjogcmVjdXJyZW5jZSwKICAgICAgICAgICAgICAgIH0sCiAgICAg"
    "ICAgICAgIH0KICAgICAgICAgICAgdGFza3MuYXBwZW5kKHRhc2spCiAgICAgICAgICAgIHNlbGYuX3Rhc2tzLnNhdmVfYWxsKHRh"
    "c2tzKQogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJHb29nbGUgc3luYyBzdWNjZWVkZWQgYW5kIHRh"
    "c2sgcmVnaXN0cnkgdXBkYXRlZC4iLCBvaz1UcnVlKQogICAgICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFu"
    "ZWwoKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltUQVNLU11bRURJVE9SXSBHb29n"
    "bGUgc2F2ZSBzdWNjZXNzIGZvciB0aXRsZT0ne3RpdGxlfScsIGV2ZW50X2lkPXtldmVudF9pZH0uIiwKICAgICAgICAgICAgICAg"
    "ICJPSyIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fY2xvc2VfdGFza19lZGl0b3Jfd29ya3NwYWNlKCkKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKGYiR29vZ2xl"
    "IHNhdmUgZmFpbGVkOiB7ZXh9Iiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAg"
    "ICAgIGYiW1RBU0tTXVtFRElUT1JdW0VSUk9SXSBHb29nbGUgc2F2ZSBmYWlsdXJlIGZvciB0aXRsZT0ne3RpdGxlfSc6IHtleH0i"
    "LAogICAgICAgICAgICAgICAgIkVSUk9SIiwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9jbG9zZV90YXNrX2VkaXRv"
    "cl93b3Jrc3BhY2UoKQoKICAgIGRlZiBfaW5zZXJ0X2NhbGVuZGFyX2RhdGUoc2VsZiwgcWRhdGU6IFFEYXRlKSAtPiBOb25lOgog"
    "ICAgICAgIGRhdGVfdGV4dCA9IHFkYXRlLnRvU3RyaW5nKCJ5eXl5LU1NLWRkIikKICAgICAgICByb3V0ZWRfdGFyZ2V0ID0gIm5v"
    "bmUiCgogICAgICAgIGZvY3VzX3dpZGdldCA9IFFBcHBsaWNhdGlvbi5mb2N1c1dpZGdldCgpCiAgICAgICAgZGlyZWN0X3Rhcmdl"
    "dHMgPSBbCiAgICAgICAgICAgICgidGFza19lZGl0b3Jfc3RhcnRfZGF0ZSIsIGdldGF0dHIoZ2V0YXR0cihzZWxmLCAiX3Rhc2tz"
    "X3RhYiIsIE5vbmUpLCAidGFza19lZGl0b3Jfc3RhcnRfZGF0ZSIsIE5vbmUpKSwKICAgICAgICAgICAgKCJ0YXNrX2VkaXRvcl9l"
    "bmRfZGF0ZSIsIGdldGF0dHIoZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpLCAidGFza19lZGl0b3JfZW5kX2RhdGUi"
    "LCBOb25lKSksCiAgICAgICAgXQogICAgICAgIGZvciBuYW1lLCB3aWRnZXQgaW4gZGlyZWN0X3RhcmdldHM6CiAgICAgICAgICAg"
    "IGlmIHdpZGdldCBpcyBub3QgTm9uZSBhbmQgZm9jdXNfd2lkZ2V0IGlzIHdpZGdldDoKICAgICAgICAgICAgICAgIHdpZGdldC5z"
    "ZXRUZXh0KGRhdGVfdGV4dCkKICAgICAgICAgICAgICAgIHJvdXRlZF90YXJnZXQgPSBuYW1lCiAgICAgICAgICAgICAgICBicmVh"
    "awoKICAgICAgICBpZiByb3V0ZWRfdGFyZ2V0ID09ICJub25lIjoKICAgICAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAiX2lucHV0"
    "X2ZpZWxkIikgYW5kIHNlbGYuX2lucHV0X2ZpZWxkIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgaWYgZm9jdXNfd2lkZ2V0"
    "IGlzIHNlbGYuX2lucHV0X2ZpZWxkOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLmluc2VydChkYXRlX3Rl"
    "eHQpCiAgICAgICAgICAgICAgICAgICAgcm91dGVkX3RhcmdldCA9ICJpbnB1dF9maWVsZF9pbnNlcnQiCiAgICAgICAgICAgICAg"
    "ICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldFRleHQoZGF0ZV90ZXh0KQogICAgICAgICAg"
    "ICAgICAgICAgIHJvdXRlZF90YXJnZXQgPSAiaW5wdXRfZmllbGRfc2V0IgoKICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfdGFz"
    "a3NfdGFiIikgYW5kIHNlbGYuX3Rhc2tzX3RhYiBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLnN0YXR1"
    "c19sYWJlbC5zZXRUZXh0KGYiQ2FsZW5kYXIgZGF0ZSBzZWxlY3RlZDoge2RhdGVfdGV4dH0iKQoKICAgICAgICBpZiBoYXNhdHRy"
    "KHNlbGYsICJfZGlhZ190YWIiKSBhbmQgc2VsZi5fZGlhZ190YWIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdf"
    "dGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0NBTEVOREFSXSBtaW5pIGNhbGVuZGFyIGNsaWNrIHJvdXRlZDogZGF0ZT17ZGF0"
    "ZV90ZXh0fSwgdGFyZ2V0PXtyb3V0ZWRfdGFyZ2V0fS4iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAgICkKCiAg"
    "ICBkZWYgX3BvbGxfZ29vZ2xlX2NhbGVuZGFyX2luYm91bmRfc3luYyhzZWxmLCBmb3JjZV9vbmNlOiBib29sID0gRmFsc2UpOgog"
    "ICAgICAgICIiIgogICAgICAgIFN5bmMgR29vZ2xlIENhbGVuZGFyIGV2ZW50cyDihpIgbG9jYWwgdGFza3MgdXNpbmcgR29vZ2xl"
    "J3Mgc3luY1Rva2VuIEFQSS4KCiAgICAgICAgU3RhZ2UgMSAoZmlyc3QgcnVuIC8gZm9yY2VkKTogRnVsbCBmZXRjaCwgc3RvcmVz"
    "IG5leHRTeW5jVG9rZW4uCiAgICAgICAgU3RhZ2UgMiAoZXZlcnkgcG9sbCk6ICAgICAgICAgSW5jcmVtZW50YWwgZmV0Y2ggdXNp"
    "bmcgc3RvcmVkIHN5bmNUb2tlbiDigJQKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICByZXR1cm5zIE9OTFkg"
    "d2hhdCBjaGFuZ2VkIChhZGRzL2VkaXRzL2NhbmNlbHMpLgogICAgICAgIElmIHNlcnZlciByZXR1cm5zIDQxMCBHb25lICh0b2tl"
    "biBleHBpcmVkKSwgZmFsbHMgYmFjayB0byBmdWxsIHN5bmMuCiAgICAgICAgIiIiCiAgICAgICAgaWYgbm90IGZvcmNlX29uY2Ug"
    "YW5kIG5vdCBib29sKENGRy5nZXQoInNldHRpbmdzIiwge30pLmdldCgiZ29vZ2xlX3N5bmNfZW5hYmxlZCIsIFRydWUpKToKICAg"
    "ICAgICAgICAgcmV0dXJuIDAKCiAgICAgICAgdHJ5OgogICAgICAgICAgICBub3dfaXNvID0gbG9jYWxfbm93X2lzbygpCiAgICAg"
    "ICAgICAgIHRhc2tzID0gc2VsZi5fdGFza3MubG9hZF9hbGwoKQogICAgICAgICAgICB0YXNrc19ieV9ldmVudF9pZCA9IHsKICAg"
    "ICAgICAgICAgICAgICh0LmdldCgiZ29vZ2xlX2V2ZW50X2lkIikgb3IgIiIpLnN0cmlwKCk6IHQKICAgICAgICAgICAgICAgIGZv"
    "ciB0IGluIHRhc2tzCiAgICAgICAgICAgICAgICBpZiAodC5nZXQoImdvb2dsZV9ldmVudF9pZCIpIG9yICIiKS5zdHJpcCgpCiAg"
    "ICAgICAgICAgIH0KCiAgICAgICAgICAgICMg4pSA4pSAIEZldGNoIGZyb20gR29vZ2xlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBzdG9yZWRfdG9rZW4gPSBzZWxmLl9zdGF0ZS5nZXQoImdv"
    "b2dsZV9jYWxlbmRhcl9zeW5jX3Rva2VuIikKCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlmIHN0b3JlZF90b2tl"
    "biBhbmQgbm90IGZvcmNlX29uY2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAg"
    "ICAgICAgICAgICAiW0dPT0dMRV1bU1lOQ10gSW5jcmVtZW50YWwgc3luYyAoc3luY1Rva2VuKS4iLCAiSU5GTyIKICAgICAgICAg"
    "ICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgcmVtb3RlX2V2ZW50cywgbmV4dF90b2tlbiA9IHNlbGYuX2djYWwubGlz"
    "dF9wcmltYXJ5X2V2ZW50cygKICAgICAgICAgICAgICAgICAgICAgICAgc3luY190b2tlbj1zdG9yZWRfdG9rZW4KICAgICAgICAg"
    "ICAgICAgICAgICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIltHT09HTEVdW1NZTkNdIEZ1bGwgc3luYyAobm8gc3RvcmVkIHRva2VuKS4iLCAiSU5G"
    "TyIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgbm93X3V0YyA9IGRhdGV0aW1lLnV0Y25vdygpLnJl"
    "cGxhY2UobWljcm9zZWNvbmQ9MCkKICAgICAgICAgICAgICAgICAgICB0aW1lX21pbiA9IChub3dfdXRjIC0gdGltZWRlbHRhKGRh"
    "eXM9MzY1KSkuaXNvZm9ybWF0KCkgKyAiWiIKICAgICAgICAgICAgICAgICAgICByZW1vdGVfZXZlbnRzLCBuZXh0X3Rva2VuID0g"
    "c2VsZi5fZ2NhbC5saXN0X3ByaW1hcnlfZXZlbnRzKAogICAgICAgICAgICAgICAgICAgICAgICB0aW1lX21pbj10aW1lX21pbgog"
    "ICAgICAgICAgICAgICAgICAgICkKCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgYXBpX2V4OgogICAgICAgICAgICAg"
    "ICAgaWYgIjQxMCIgaW4gc3RyKGFwaV9leCkgb3IgIkdvbmUiIGluIHN0cihhcGlfZXgpOgogICAgICAgICAgICAgICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAgICAgIltHT09HTEVdW1NZTkNdIHN5bmNUb2tlbiBleHBpcmVk"
    "ICg0MTApIOKAlCBmdWxsIHJlc3luYy4iLCAiV0FSTiIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAg"
    "c2VsZi5fc3RhdGUucG9wKCJnb29nbGVfY2FsZW5kYXJfc3luY190b2tlbiIsIE5vbmUpCiAgICAgICAgICAgICAgICAgICAgbm93"
    "X3V0YyA9IGRhdGV0aW1lLnV0Y25vdygpLnJlcGxhY2UobWljcm9zZWNvbmQ9MCkKICAgICAgICAgICAgICAgICAgICB0aW1lX21p"
    "biA9IChub3dfdXRjIC0gdGltZWRlbHRhKGRheXM9MzY1KSkuaXNvZm9ybWF0KCkgKyAiWiIKICAgICAgICAgICAgICAgICAgICBy"
    "ZW1vdGVfZXZlbnRzLCBuZXh0X3Rva2VuID0gc2VsZi5fZ2NhbC5saXN0X3ByaW1hcnlfZXZlbnRzKAogICAgICAgICAgICAgICAg"
    "ICAgICAgICB0aW1lX21pbj10aW1lX21pbgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAg"
    "ICAgICAgICAgICAgICAgcmFpc2UKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0dP"
    "T0dMRV1bU1lOQ10gUmVjZWl2ZWQge2xlbihyZW1vdGVfZXZlbnRzKX0gZXZlbnQocykuIiwgIklORk8iCiAgICAgICAgICAgICkK"
    "CiAgICAgICAgICAgICMgU2F2ZSBuZXcgdG9rZW4gZm9yIG5leHQgaW5jcmVtZW50YWwgY2FsbAogICAgICAgICAgICBpZiBuZXh0"
    "X3Rva2VuOgogICAgICAgICAgICAgICAgc2VsZi5fc3RhdGVbImdvb2dsZV9jYWxlbmRhcl9zeW5jX3Rva2VuIl0gPSBuZXh0X3Rv"
    "a2VuCiAgICAgICAgICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9zdGF0ZSkKCiAgICAgICAgICAgICMg4pSA"
    "4pSAIFByb2Nlc3MgZXZlbnRzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgICAgICAgICBpbXBvcnRlZF9jb3VudCA9IHVwZGF0ZWRfY291bnQgPSByZW1vdmVkX2NvdW50ID0gMAogICAgICAg"
    "ICAgICBjaGFuZ2VkID0gRmFsc2UKCiAgICAgICAgICAgIGZvciBldmVudCBpbiByZW1vdGVfZXZlbnRzOgogICAgICAgICAgICAg"
    "ICAgZXZlbnRfaWQgPSAoZXZlbnQuZ2V0KCJpZCIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgICAgICAgICBpZiBub3QgZXZlbnRf"
    "aWQ6CiAgICAgICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICAgICAjIERlbGV0ZWQgLyBjYW5jZWxsZWQgb24g"
    "R29vZ2xlJ3Mgc2lkZQogICAgICAgICAgICAgICAgaWYgZXZlbnQuZ2V0KCJzdGF0dXMiKSA9PSAiY2FuY2VsbGVkIjoKICAgICAg"
    "ICAgICAgICAgICAgICBleGlzdGluZyA9IHRhc2tzX2J5X2V2ZW50X2lkLmdldChldmVudF9pZCkKICAgICAgICAgICAgICAgICAg"
    "ICBpZiBleGlzdGluZyBhbmQgZXhpc3RpbmcuZ2V0KCJzdGF0dXMiKSBub3QgaW4gKCJjYW5jZWxsZWQiLCAiY29tcGxldGVkIik6"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJzdGF0dXMiXSAgICAgICAgID0gImNhbmNlbGxlZCIKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgZXhpc3RpbmdbImNhbmNlbGxlZF9hdCJdICAgPSBub3dfaXNvCiAgICAgICAgICAgICAgICAgICAgICAg"
    "IGV4aXN0aW5nWyJzeW5jX3N0YXR1cyJdICAgID0gImRlbGV0ZWRfcmVtb3RlIgogICAgICAgICAgICAgICAgICAgICAgICBleGlz"
    "dGluZ1sibGFzdF9zeW5jZWRfYXQiXSA9IG5vd19pc28KICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3Rpbmcuc2V0ZGVmYXVs"
    "dCgibWV0YWRhdGEiLCB7fSlbImdvb2dsZV9kZWxldGVkX3JlbW90ZSJdID0gbm93X2lzbwogICAgICAgICAgICAgICAgICAgICAg"
    "ICByZW1vdmVkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTWU5DXSBS"
    "ZW1vdmVkOiB7ZXhpc3RpbmcuZ2V0KCd0ZXh0JywnPycpfSIsICJJTkZPIgogICAgICAgICAgICAgICAgICAgICAgICApCiAgICAg"
    "ICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICAgICBzdW1tYXJ5ID0gKGV2ZW50LmdldCgic3VtbWFyeSIpIG9y"
    "ICJHb29nbGUgQ2FsZW5kYXIgRXZlbnQiKS5zdHJpcCgpIG9yICJHb29nbGUgQ2FsZW5kYXIgRXZlbnQiCiAgICAgICAgICAgICAg"
    "ICBkdWVfYXQgID0gc2VsZi5fZ29vZ2xlX2V2ZW50X2R1ZV9kYXRldGltZShldmVudCkKICAgICAgICAgICAgICAgIGV4aXN0aW5n"
    "ID0gdGFza3NfYnlfZXZlbnRfaWQuZ2V0KGV2ZW50X2lkKQoKICAgICAgICAgICAgICAgIGlmIGV4aXN0aW5nOgogICAgICAgICAg"
    "ICAgICAgICAgICMgVXBkYXRlIGlmIGFueXRoaW5nIGNoYW5nZWQKICAgICAgICAgICAgICAgICAgICB0YXNrX2NoYW5nZWQgPSBG"
    "YWxzZQogICAgICAgICAgICAgICAgICAgIGlmIChleGlzdGluZy5nZXQoInRleHQiKSBvciAiIikuc3RyaXAoKSAhPSBzdW1tYXJ5"
    "OgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sidGV4dCJdID0gc3VtbWFyeQogICAgICAgICAgICAgICAgICAgICAg"
    "ICB0YXNrX2NoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgaWYgZHVlX2F0OgogICAgICAgICAgICAgICAgICAgICAg"
    "ICBkdWVfaXNvID0gZHVlX2F0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICAgICAgICAgIGlm"
    "IGV4aXN0aW5nLmdldCgiZHVlX2F0IikgIT0gZHVlX2lzbzoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJk"
    "dWVfYXQiXSAgICAgICA9IGR1ZV9pc28KICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJwcmVfdHJpZ2dlciJd"
    "ICA9IChkdWVfYXQgLSB0aW1lZGVsdGEobWludXRlcz0xKSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIHRhc2tfY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgICAgICBpZiBleGlzdGluZy5nZXQo"
    "InN5bmNfc3RhdHVzIikgIT0gInN5bmNlZCI6CiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJzeW5jX3N0YXR1cyJd"
    "ID0gInN5bmNlZCIKICAgICAgICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAg"
    "IGlmIHRhc2tfY2hhbmdlZDoKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbImxhc3Rfc3luY2VkX2F0Il0gPSBub3df"
    "aXNvCiAgICAgICAgICAgICAgICAgICAgICAgIHVwZGF0ZWRfY291bnQgKz0gMQogICAgICAgICAgICAgICAgICAgICAgICBjaGFu"
    "Z2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICBmIltHT09HTEVdW1NZTkNdIFVwZGF0ZWQ6IHtzdW1tYXJ5fSIsICJJTkZPIgogICAgICAgICAgICAgICAgICAgICAg"
    "ICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgICMgTmV3IGV2ZW50CiAgICAgICAgICAgICAgICAg"
    "ICAgaWYgbm90IGR1ZV9hdDoKICAgICAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgICAgICAgICBuZXdf"
    "dGFzayA9IHsKICAgICAgICAgICAgICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgICAgZiJ0YXNrX3t1dWlkLnV1aWQ0KCku"
    "aGV4WzoxMF19IiwKICAgICAgICAgICAgICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgICAgICAgbm93X2lzbywKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgImR1ZV9hdCI6ICAgICAgICAgICAgZHVlX2F0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAicHJlX3RyaWdnZXIiOiAgICAgICAoZHVlX2F0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkp"
    "Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgICAgICAgICAidGV4dCI6ICAgICAgICAgICAg"
    "ICBzdW1tYXJ5LAogICAgICAgICAgICAgICAgICAgICAgICAic3RhdHVzIjogICAgICAgICAgICAicGVuZGluZyIsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJhY2tub3dsZWRnZWRfYXQiOiAgIE5vbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICJyZXRyeV9j"
    "b3VudCI6ICAgICAgIDAsCiAgICAgICAgICAgICAgICAgICAgICAgICJsYXN0X3RyaWdnZXJlZF9hdCI6IE5vbmUsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJuZXh0X3JldHJ5X2F0IjogICAgIE5vbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICJwcmVfYW5u"
    "b3VuY2VkIjogICAgIEZhbHNlLAogICAgICAgICAgICAgICAgICAgICAgICAic291cmNlIjogICAgICAgICAgICAiZ29vZ2xlIiwK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6ICAgZXZlbnRfaWQsCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICJzeW5jX3N0YXR1cyI6ICAgICAgICJzeW5jZWQiLAogICAgICAgICAgICAgICAgICAgICAgICAibGFzdF9zeW5jZWRfYXQi"
    "OiAgICBub3dfaXNvLAogICAgICAgICAgICAgICAgICAgICAgICAibWV0YWRhdGEiOiB7CiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAiZ29vZ2xlX2ltcG9ydGVkX2F0Ijogbm93X2lzbywKICAgICAgICAgICAgICAgICAgICAgICAgICAgICJnb29nbGVfdXBk"
    "YXRlZCI6ICAgICBldmVudC5nZXQoInVwZGF0ZWQiKSwKICAgICAgICAgICAgICAgICAgICAgICAgfSwKICAgICAgICAgICAgICAg"
    "ICAgICB9CiAgICAgICAgICAgICAgICAgICAgdGFza3MuYXBwZW5kKG5ld190YXNrKQogICAgICAgICAgICAgICAgICAgIHRhc2tz"
    "X2J5X2V2ZW50X2lkW2V2ZW50X2lkXSA9IG5ld190YXNrCiAgICAgICAgICAgICAgICAgICAgaW1wb3J0ZWRfY291bnQgKz0gMQog"
    "ICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYi"
    "W0dPT0dMRV1bU1lOQ10gSW1wb3J0ZWQ6IHtzdW1tYXJ5fSIsICJJTkZPIikKCiAgICAgICAgICAgIGlmIGNoYW5nZWQ6CiAgICAg"
    "ICAgICAgICAgICBzZWxmLl90YXNrcy5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lz"
    "dHJ5X3BhbmVsKCkKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1lO"
    "Q10gRG9uZSDigJQgaW1wb3J0ZWQ9e2ltcG9ydGVkX2NvdW50fSAiCiAgICAgICAgICAgICAgICBmInVwZGF0ZWQ9e3VwZGF0ZWRf"
    "Y291bnR9IHJlbW92ZWQ9e3JlbW92ZWRfY291bnR9IiwgIklORk8iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuIGlt"
    "cG9ydGVkX2NvdW50CgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZyhmIltHT09HTEVdW1NZTkNdW0VSUk9SXSB7ZXh9IiwgIkVSUk9SIikKICAgICAgICAgICAgcmV0dXJuIDAKCgogICAgZGVmIF9t"
    "ZWFzdXJlX3ZyYW1fYmFzZWxpbmUoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAg"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRs"
    "ZSkKICAgICAgICAgICAgICAgIHNlbGYuX2RlY2tfdnJhbV9iYXNlID0gbWVtLnVzZWQgLyAxMDI0KiozCiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVlJBTV0gQmFzZWxpbmUgbWVhc3VyZWQ6IHtzZWxm"
    "Ll9kZWNrX3ZyYW1fYmFzZTouMmZ9R0IgIgogICAgICAgICAgICAgICAgICAgIGYiKHtERUNLX05BTUV9J3MgZm9vdHByaW50KSIs"
    "ICJJTkZPIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFz"
    "cwoKICAgICMg4pSA4pSAIE1FU1NBR0UgSEFORExJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3NlbmRfbWVzc2FnZShzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQgb3Igc2VsZi5fdG9ycG9yX3N0YXRlID09ICJTVVNQ"
    "RU5EIjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdGV4dCA9IHNlbGYuX2lucHV0X2ZpZWxkLnRleHQoKS5zdHJpcCgpCiAg"
    "ICAgICAgaWYgbm90IHRleHQ6CiAgICAgICAgICAgIHJldHVybgoKICAgICAgICAjIEZsaXAgYmFjayB0byBwZXJzb25hIGNoYXQg"
    "dGFiIGZyb20gU2VsZiB0YWIgaWYgbmVlZGVkCiAgICAgICAgaWYgc2VsZi5fbWFpbl90YWJzLmN1cnJlbnRJbmRleCgpICE9IDA6"
    "CiAgICAgICAgICAgIHNlbGYuX21haW5fdGFicy5zZXRDdXJyZW50SW5kZXgoMCkKCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQu"
    "Y2xlYXIoKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJZT1UiLCB0ZXh0KQoKICAgICAgICAjIFNlc3Npb24gbG9nZ2luZwog"
    "ICAgICAgIHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdlKCJ1c2VyIiwgdGV4dCkKICAgICAgICBzZWxmLl9tZW1vcnkuYXBwZW5k"
    "X21lc3NhZ2Uoc2VsZi5fc2Vzc2lvbl9pZCwgInVzZXIiLCB0ZXh0KQoKICAgICAgICAjIEludGVycnVwdCBmYWNlIHRpbWVyIOKA"
    "lCBzd2l0Y2ggdG8gYWxlcnQgaW1tZWRpYXRlbHkKICAgICAgICBpZiBzZWxmLl9mYWNlX3RpbWVyX21ncjoKICAgICAgICAgICAg"
    "c2VsZi5fZmFjZV90aW1lcl9tZ3IuaW50ZXJydXB0KCJhbGVydCIpCgogICAgICAgICMgQnVpbGQgcHJvbXB0IHdpdGggdmFtcGly"
    "ZSBjb250ZXh0ICsgbWVtb3J5IGNvbnRleHQKICAgICAgICB2YW1waXJlX2N0eCAgPSBidWlsZF92YW1waXJlX2NvbnRleHQoKQog"
    "ICAgICAgIG1lbW9yeV9jdHggICA9IHNlbGYuX21lbW9yeS5idWlsZF9jb250ZXh0X2Jsb2NrKHRleHQpCiAgICAgICAgam91cm5h"
    "bF9jdHggID0gIiIKCiAgICAgICAgaWYgc2VsZi5fc2Vzc2lvbnMubG9hZGVkX2pvdXJuYWxfZGF0ZToKICAgICAgICAgICAgam91"
    "cm5hbF9jdHggPSBzZWxmLl9zZXNzaW9ucy5sb2FkX3Nlc3Npb25fYXNfY29udGV4dCgKICAgICAgICAgICAgICAgIHNlbGYuX3Nl"
    "c3Npb25zLmxvYWRlZF9qb3VybmFsX2RhdGUKICAgICAgICAgICAgKQoKICAgICAgICAjIEJ1aWxkIHN5c3RlbSBwcm9tcHQKICAg"
    "ICAgICBzeXN0ZW0gPSBTWVNURU1fUFJPTVBUX0JBU0UKICAgICAgICBpZiBtZW1vcnlfY3R4OgogICAgICAgICAgICBzeXN0ZW0g"
    "Kz0gZiJcblxue21lbW9yeV9jdHh9IgogICAgICAgIGlmIGpvdXJuYWxfY3R4OgogICAgICAgICAgICBzeXN0ZW0gKz0gZiJcblxu"
    "e2pvdXJuYWxfY3R4fSIKICAgICAgICBzeXN0ZW0gKz0gdmFtcGlyZV9jdHgKCiAgICAgICAgIyBMZXNzb25zIGNvbnRleHQgZm9y"
    "IGNvZGUtYWRqYWNlbnQgaW5wdXQKICAgICAgICBpZiBhbnkoa3cgaW4gdGV4dC5sb3dlcigpIGZvciBrdyBpbiAoImxzbCIsInB5"
    "dGhvbiIsInNjcmlwdCIsImNvZGUiLCJmdW5jdGlvbiIpKToKICAgICAgICAgICAgbGFuZyA9ICJMU0wiIGlmICJsc2wiIGluIHRl"
    "eHQubG93ZXIoKSBlbHNlICJQeXRob24iCiAgICAgICAgICAgIGxlc3NvbnNfY3R4ID0gc2VsZi5fbGVzc29ucy5idWlsZF9jb250"
    "ZXh0X2Zvcl9sYW5ndWFnZShsYW5nKQogICAgICAgICAgICBpZiBsZXNzb25zX2N0eDoKICAgICAgICAgICAgICAgIHN5c3RlbSAr"
    "PSBmIlxuXG57bGVzc29uc19jdHh9IgoKICAgICAgICAjIEFkZCBwZW5kaW5nIHRyYW5zbWlzc2lvbnMgY29udGV4dCBpZiBhbnkK"
    "ICAgICAgICBpZiBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgPiAwOgogICAgICAgICAgICBkdXIgPSBzZWxmLl9zdXNwZW5k"
    "ZWRfZHVyYXRpb24gb3IgInNvbWUgdGltZSIKICAgICAgICAgICAgc3lzdGVtICs9ICgKICAgICAgICAgICAgICAgIGYiXG5cbltS"
    "RVRVUk4gRlJPTSBUT1JQT1JdXG4iCiAgICAgICAgICAgICAgICBmIllvdSB3ZXJlIGluIHRvcnBvciBmb3Ige2R1cn0uICIKICAg"
    "ICAgICAgICAgICAgIGYie3NlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9uc30gdGhvdWdodHMgd2VudCB1bnNwb2tlbiAiCiAgICAg"
    "ICAgICAgICAgICBmImR1cmluZyB0aGF0IHRpbWUuIEFja25vd2xlZGdlIHRoaXMgYnJpZWZseSBpbiBjaGFyYWN0ZXIgIgogICAg"
    "ICAgICAgICAgICAgZiJpZiBpdCBmZWVscyBuYXR1cmFsLiIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9wZW5kaW5n"
    "X3RyYW5zbWlzc2lvbnMgPSAwCiAgICAgICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiAgICA9ICIiCgogICAgICAgIGhp"
    "c3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCgogICAgICAgICMgRGlzYWJsZSBpbnB1dAogICAgICAgIHNlbGYu"
    "X3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKICAg"
    "ICAgICBzZWxmLl9zZXRfc3RhdHVzKCJHRU5FUkFUSU5HIikKCiAgICAgICAgIyBTdG9wIGlkbGUgdGltZXIgZHVyaW5nIGdlbmVy"
    "YXRpb24KICAgICAgICBpZiBzZWxmLl9zY2hlZHVsZXIgYW5kIHNlbGYuX3NjaGVkdWxlci5ydW5uaW5nOgogICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIucGF1c2Vfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgTGF1bmNoIHN0cmVhbWluZyB3b3Jr"
    "ZXIKICAgICAgICBzZWxmLl93b3JrZXIgPSBTdHJlYW1pbmdXb3JrZXIoCiAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IsIHN5c3Rl"
    "bSwgaGlzdG9yeSwgbWF4X3Rva2Vucz01MTIKICAgICAgICApCiAgICAgICAgc2VsZi5fd29ya2VyLnRva2VuX3JlYWR5LmNvbm5l"
    "Y3Qoc2VsZi5fb25fdG9rZW4pCiAgICAgICAgc2VsZi5fd29ya2VyLnJlc3BvbnNlX2RvbmUuY29ubmVjdChzZWxmLl9vbl9yZXNw"
    "b25zZV9kb25lKQogICAgICAgIHNlbGYuX3dvcmtlci5lcnJvcl9vY2N1cnJlZC5jb25uZWN0KHNlbGYuX29uX2Vycm9yKQogICAg"
    "ICAgIHNlbGYuX3dvcmtlci5zdGF0dXNfY2hhbmdlZC5jb25uZWN0KHNlbGYuX3NldF9zdGF0dXMpCiAgICAgICAgc2VsZi5fZmly"
    "c3RfdG9rZW4gPSBUcnVlICAjIGZsYWcgdG8gd3JpdGUgc3BlYWtlciBsYWJlbCBiZWZvcmUgZmlyc3QgdG9rZW4KICAgICAgICBz"
    "ZWxmLl93b3JrZXIuc3RhcnQoKQoKICAgIGRlZiBfYmVnaW5fcGVyc29uYV9yZXNwb25zZShzZWxmKSAtPiBOb25lOgogICAgICAg"
    "ICIiIgogICAgICAgIFdyaXRlIHRoZSBwZXJzb25hIHNwZWFrZXIgbGFiZWwgYW5kIHRpbWVzdGFtcCBiZWZvcmUgc3RyZWFtaW5n"
    "IGJlZ2lucy4KICAgICAgICBDYWxsZWQgb24gZmlyc3QgdG9rZW4gb25seS4gU3Vic2VxdWVudCB0b2tlbnMgYXBwZW5kIGRpcmVj"
    "dGx5LgogICAgICAgICIiIgogICAgICAgIHRpbWVzdGFtcCA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUyIpCiAg"
    "ICAgICAgIyBXcml0ZSB0aGUgc3BlYWtlciBsYWJlbCBhcyBIVE1MLCB0aGVuIGFkZCBhIG5ld2xpbmUgc28gdG9rZW5zCiAgICAg"
    "ICAgIyBmbG93IGJlbG93IGl0IHJhdGhlciB0aGFuIGlubGluZQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5hcHBlbmQoCiAg"
    "ICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAg"
    "IGYnW3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19DUklNU09OfTsgZm9u"
    "dC13ZWlnaHQ6Ym9sZDsiPicKICAgICAgICAgICAgZid7REVDS19OQU1FLnVwcGVyKCl9IOKdqTwvc3Bhbj4gJwogICAgICAgICkK"
    "ICAgICAgICAjIE1vdmUgY3Vyc29yIHRvIGVuZCBzbyBpbnNlcnRQbGFpblRleHQgYXBwZW5kcyBjb3JyZWN0bHkKICAgICAgICBj"
    "dXJzb3IgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudGV4dEN1cnNvcigpCiAgICAgICAgY3Vyc29yLm1vdmVQb3NpdGlvbihRVGV4dEN1"
    "cnNvci5Nb3ZlT3BlcmF0aW9uLkVuZCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNvcihjdXJzb3IpCgog"
    "ICAgZGVmIF9vbl90b2tlbihzZWxmLCB0b2tlbjogc3RyKSAtPiBOb25lOgogICAgICAgICIiIkFwcGVuZCBzdHJlYW1pbmcgdG9r"
    "ZW4gdG8gY2hhdCBkaXNwbGF5LiIiIgogICAgICAgIGlmIHNlbGYuX2ZpcnN0X3Rva2VuOgogICAgICAgICAgICBzZWxmLl9iZWdp"
    "bl9wZXJzb25hX3Jlc3BvbnNlKCkKICAgICAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBGYWxzZQogICAgICAgIGN1cnNvciA9"
    "IHNlbGYuX2NoYXRfZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAgICBjdXJzb3IubW92ZVBvc2l0aW9uKFFUZXh0Q3Vyc29yLk1v"
    "dmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRUZXh0Q3Vyc29yKGN1cnNvcikKICAgICAgICBz"
    "ZWxmLl9jaGF0X2Rpc3BsYXkuaW5zZXJ0UGxhaW5UZXh0KHRva2VuKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNh"
    "bFNjcm9sbEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5t"
    "YXhpbXVtKCkKICAgICAgICApCgogICAgZGVmIF9vbl9yZXNwb25zZV9kb25lKHNlbGYsIHJlc3BvbnNlOiBzdHIpIC0+IE5vbmU6"
    "CiAgICAgICAgIyBFbnN1cmUgcmVzcG9uc2UgaXMgb24gaXRzIG93biBsaW5lCiAgICAgICAgY3Vyc29yID0gc2VsZi5fY2hhdF9k"
    "aXNwbGF5LnRleHRDdXJzb3IoKQogICAgICAgIGN1cnNvci5tb3ZlUG9zaXRpb24oUVRleHRDdXJzb3IuTW92ZU9wZXJhdGlvbi5F"
    "bmQpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFRleHRDdXJzb3IoY3Vyc29yKQogICAgICAgIHNlbGYuX2NoYXRfZGlz"
    "cGxheS5pbnNlcnRQbGFpblRleHQoIlxuXG4iKQoKICAgICAgICAjIExvZyB0byBtZW1vcnkgYW5kIHNlc3Npb24KICAgICAgICBz"
    "ZWxmLl90b2tlbl9jb3VudCArPSBsZW4ocmVzcG9uc2Uuc3BsaXQoKSkKICAgICAgICBzZWxmLl9zZXNzaW9ucy5hZGRfbWVzc2Fn"
    "ZSgiYXNzaXN0YW50IiwgcmVzcG9uc2UpCiAgICAgICAgc2VsZi5fbWVtb3J5LmFwcGVuZF9tZXNzYWdlKHNlbGYuX3Nlc3Npb25f"
    "aWQsICJhc3Npc3RhbnQiLCByZXNwb25zZSkKICAgICAgICBzZWxmLl9tZW1vcnkuYXBwZW5kX21lbW9yeShzZWxmLl9zZXNzaW9u"
    "X2lkLCAiIiwgcmVzcG9uc2UpCgogICAgICAgICMgVXBkYXRlIGJsb29kIHNwaGVyZQogICAgICAgIGlmIHNlbGYuX2xlZnRfb3Ji"
    "IGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9sZWZ0X29yYi5zZXRGaWxsKAogICAgICAgICAgICAgICAgbWluKDEuMCwg"
    "c2VsZi5fdG9rZW5fY291bnQgLyA0MDk2LjApCiAgICAgICAgICAgICkKCiAgICAgICAgIyBSZS1lbmFibGUgaW5wdXQKICAgICAg"
    "ICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVl"
    "KQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEZvY3VzKCkKCiAgICAgICAgIyBSZXN1bWUgaWRsZSB0aW1lcgogICAgICAg"
    "IGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgICAgIHNlbGYuX3NjaGVkdWxlci5yZXN1bWVfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgU2NoZWR1bGUgc2VudGltZW50IGFuYWx5c2lzICg1IHNl"
    "Y29uZCBkZWxheSkKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCg1MDAwLCBsYW1iZGE6IHNlbGYuX3J1bl9zZW50aW1lbnQocmVz"
    "cG9uc2UpKQoKICAgIGRlZiBfcnVuX3NlbnRpbWVudChzZWxmLCByZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgIGlmIG5v"
    "dCBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX3NlbnRfd29ya2VyID0gU2VudGlt"
    "ZW50V29ya2VyKHNlbGYuX2FkYXB0b3IsIHJlc3BvbnNlKQogICAgICAgIHNlbGYuX3NlbnRfd29ya2VyLmZhY2VfcmVhZHkuY29u"
    "bmVjdChzZWxmLl9vbl9zZW50aW1lbnQpCiAgICAgICAgc2VsZi5fc2VudF93b3JrZXIuc3RhcnQoKQoKICAgIGRlZiBfb25fc2Vu"
    "dGltZW50KHNlbGYsIGVtb3Rpb246IHN0cikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl9mYWNlX3RpbWVyX21ncjoKICAgICAg"
    "ICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3Iuc2V0X2ZhY2UoZW1vdGlvbikKCiAgICBkZWYgX29uX2Vycm9yKHNlbGYsIGVycm9y"
    "OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZXJyb3IpCiAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKGYiW0dFTkVSQVRJT04gRVJST1JdIHtlcnJvcn0iLCAiRVJST1IiKQogICAgICAgIGlmIHNlbGYuX2ZhY2VfdGlt"
    "ZXJfbWdyOgogICAgICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nci5zZXRfZmFjZSgicGFuaWNrZWQiKQogICAgICAgIHNlbGYu"
    "X3NldF9zdGF0dXMoIkVSUk9SIikKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5f"
    "aW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQoKICAgICMg4pSA4pSAIFRPUlBPUiBTWVNURU0g4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICBkZWYgX29uX3RvcnBvcl9zdGF0ZV9jaGFuZ2VkKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAg"
    "c2VsZi5fdG9ycG9yX3N0YXRlID0gc3RhdGUKCiAgICAgICAgaWYgc3RhdGUgPT0gIlNVU1BFTkQiOgogICAgICAgICAgICBzZWxm"
    "Ll9lbnRlcl90b3Jwb3IocmVhc29uPSJtYW51YWwg4oCUIFNVU1BFTkQgbW9kZSBzZWxlY3RlZCIpCiAgICAgICAgZWxpZiBzdGF0"
    "ZSA9PSAiQVdBS0UiOgogICAgICAgICAgICAjIEFsd2F5cyBleGl0IHRvcnBvciB3aGVuIHN3aXRjaGluZyB0byBBV0FLRSDigJQK"
    "ICAgICAgICAgICAgIyBldmVuIHdpdGggT2xsYW1hIGJhY2tlbmQgd2hlcmUgbW9kZWwgaXNuJ3QgdW5sb2FkZWQsCiAgICAgICAg"
    "ICAgICMgd2UgbmVlZCB0byByZS1lbmFibGUgVUkgYW5kIHJlc2V0IHN0YXRlCiAgICAgICAgICAgIHNlbGYuX2V4aXRfdG9ycG9y"
    "KCkKICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9IDAKICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZf"
    "dGlja3MgICA9IDAKICAgICAgICBlbGlmIHN0YXRlID09ICJBVVRPIjoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAog"
    "ICAgICAgICAgICAgICAgIltUT1JQT1JdIEFVVE8gbW9kZSDigJQgbW9uaXRvcmluZyBWUkFNIHByZXNzdXJlLiIsICJJTkZPIgog"
    "ICAgICAgICAgICApCgogICAgZGVmIF9lbnRlcl90b3Jwb3Ioc2VsZiwgcmVhc29uOiBzdHIgPSAibWFudWFsIikgLT4gTm9uZToK"
    "ICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5IGlu"
    "IHRvcnBvcgoKICAgICAgICBzZWxmLl90b3Jwb3Jfc2luY2UgPSBkYXRldGltZS5ub3coKQogICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZyhmIltUT1JQT1JdIEVudGVyaW5nIHRvcnBvcjoge3JlYXNvbn0iLCAiV0FSTiIpCiAgICAgICAgc2VsZi5fYXBwZW5kX2No"
    "YXQoIlNZU1RFTSIsICJUaGUgdmVzc2VsIGdyb3dzIGNyb3dkZWQuIEkgd2l0aGRyYXcuIikKCiAgICAgICAgIyBVbmxvYWQgbW9k"
    "ZWwgZnJvbSBWUkFNCiAgICAgICAgaWYgc2VsZi5fbW9kZWxfbG9hZGVkIGFuZCBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IpOgogICAg"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9hZGFwdG9yLl9tb2RlbCBpcyBub3QgTm9uZToKICAgICAgICAg"
    "ICAgICAgICAgICBkZWwgc2VsZi5fYWRhcHRvci5fbW9kZWwKICAgICAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLl9tb2Rl"
    "bCA9IE5vbmUKICAgICAgICAgICAgICAgIGlmIFRPUkNIX09LOgogICAgICAgICAgICAgICAgICAgIHRvcmNoLmN1ZGEuZW1wdHlf"
    "Y2FjaGUoKQogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvci5fbG9hZGVkID0gRmFsc2UKICAgICAgICAgICAgICAgIHNlbGYu"
    "X21vZGVsX2xvYWRlZCAgICA9IEZhbHNlCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIE1vZGVs"
    "IHVubG9hZGVkIGZyb20gVlJBTS4iLCAiT0siKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SXSBNb2RlbCB1bmxvYWQgZXJyb3I6"
    "IHtlfSIsICJFUlJPUiIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKCJuZXV0cmFsIikK"
    "ICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJUT1JQT1IiKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2Up"
    "CiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKCiAgICBkZWYgX2V4aXRfdG9ycG9yKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgIyBDYWxjdWxhdGUgc3VzcGVuZGVkIGR1cmF0aW9uCiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNl"
    "OgogICAgICAgICAgICBkZWx0YSA9IGRhdGV0aW1lLm5vdygpIC0gc2VsZi5fdG9ycG9yX3NpbmNlCiAgICAgICAgICAgIHNlbGYu"
    "X3N1c3BlbmRlZF9kdXJhdGlvbiA9IGZvcm1hdF9kdXJhdGlvbihkZWx0YS50b3RhbF9zZWNvbmRzKCkpCiAgICAgICAgICAgIHNl"
    "bGYuX3RvcnBvcl9zaW5jZSA9IE5vbmUKCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbVE9SUE9SXSBXYWtpbmcgZnJvbSB0"
    "b3Jwb3IuLi4iLCAiSU5GTyIpCgogICAgICAgIGlmIHNlbGYuX21vZGVsX2xvYWRlZDoKICAgICAgICAgICAgIyBPbGxhbWEgYmFj"
    "a2VuZCDigJQgbW9kZWwgd2FzIG5ldmVyIHVubG9hZGVkLCBqdXN0IHJlLWVuYWJsZSBVSQogICAgICAgICAgICBzZWxmLl9hcHBl"
    "bmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7REVDS19OQU1FfSBzdGlycyAi"
    "CiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICdicmllZmx5J30gZWxhcHNlZCkuIgogICAg"
    "ICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCAiVGhlIGNvbm5lY3Rpb24gaG9sZHMuIFNo"
    "ZSBpcyBsaXN0ZW5pbmcuIikKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiSURMRSIpCiAgICAgICAgICAgIHNlbGYuX3Nl"
    "bmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQogICAg"
    "ICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIEFXQUtFIG1vZGUg4oCUIGF1dG8tdG9ycG9yIGRpc2FibGVkLiIs"
    "ICJJTkZPIikKICAgICAgICBlbHNlOgogICAgICAgICAgICAjIExvY2FsIG1vZGVsIHdhcyB1bmxvYWRlZCDigJQgbmVlZCBmdWxs"
    "IHJlbG9hZAogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiVGhlIHZlc3Nl"
    "bCBlbXB0aWVzLiB7REVDS19OQU1FfSBzdGlycyBmcm9tIHRvcnBvciAiCiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVu"
    "ZGVkX2R1cmF0aW9uIG9yICdicmllZmx5J30gZWxhcHNlZCkuIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NldF9z"
    "dGF0dXMoIkxPQURJTkciKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIgPSBNb2RlbExvYWRlcldvcmtlcihzZWxmLl9hZGFwdG9y"
    "KQogICAgICAgICAgICBzZWxmLl9sb2FkZXIubWVzc2FnZS5jb25uZWN0KAogICAgICAgICAgICAgICAgbGFtYmRhIG06IHNlbGYu"
    "X2FwcGVuZF9jaGF0KCJTWVNURU0iLCBtKSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmVycm9yLmNvbm5lY3QoCiAgICAgICAg"
    "ICAgICAgICBsYW1iZGEgZTogc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZSkpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5s"
    "b2FkX2NvbXBsZXRlLmNvbm5lY3Qoc2VsZi5fb25fbG9hZF9jb21wbGV0ZSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmZpbmlz"
    "aGVkLmNvbm5lY3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICBzZWxmLl9hY3RpdmVfdGhyZWFkcy5hcHBl"
    "bmQoc2VsZi5fbG9hZGVyKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuc3RhcnQoKQoKICAgIGRlZiBfY2hlY2tfdnJhbV9wcmVz"
    "c3VyZShzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCBldmVyeSA1IHNlY29uZHMgZnJvbSBBUFNjaGVk"
    "dWxlciB3aGVuIHRvcnBvciBzdGF0ZSBpcyBBVVRPLgogICAgICAgIE9ubHkgdHJpZ2dlcnMgdG9ycG9yIGlmIGV4dGVybmFsIFZS"
    "QU0gdXNhZ2UgZXhjZWVkcyB0aHJlc2hvbGQKICAgICAgICBBTkQgaXMgc3VzdGFpbmVkIOKAlCBuZXZlciB0cmlnZ2VycyBvbiB0"
    "aGUgcGVyc29uYSdzIG93biBmb290cHJpbnQuCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3N0YXRlICE9ICJB"
    "VVRPIjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgbm90IE5WTUxfT0sgb3Igbm90IGdwdV9oYW5kbGU6CiAgICAgICAg"
    "ICAgIHJldHVybgogICAgICAgIGlmIHNlbGYuX2RlY2tfdnJhbV9iYXNlIDw9IDA6CiAgICAgICAgICAgIHJldHVybgoKICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgIG1lbV9pbmZvICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVfaGFuZGxlKQog"
    "ICAgICAgICAgICB0b3RhbF91c2VkID0gbWVtX2luZm8udXNlZCAvIDEwMjQqKjMKICAgICAgICAgICAgZXh0ZXJuYWwgICA9IHRv"
    "dGFsX3VzZWQgLSBzZWxmLl9kZWNrX3ZyYW1fYmFzZQoKICAgICAgICAgICAgaWYgZXh0ZXJuYWwgPiBzZWxmLl9FWFRFUk5BTF9W"
    "UkFNX1RPUlBPUl9HQjoKICAgICAgICAgICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAg"
    "ICAgICAgICAgICByZXR1cm4gICMgQWxyZWFkeSBpbiB0b3Jwb3Ig4oCUIGRvbid0IGtlZXAgY291bnRpbmcKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgKz0gMQogICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3Mg"
    "ICAgPSAwCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFV"
    "VE9dIEV4dGVybmFsIFZSQU0gcHJlc3N1cmU6ICIKICAgICAgICAgICAgICAgICAgICBmIntleHRlcm5hbDouMmZ9R0IgIgogICAg"
    "ICAgICAgICAgICAgICAgIGYiKHRpY2sge3NlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3N9LyIKICAgICAgICAgICAgICAgICAgICBm"
    "IntzZWxmLl9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTfSkiLCAiV0FSTiIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAg"
    "IGlmIChzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID49IHNlbGYuX1RPUlBPUl9TVVNUQUlORURfVElDS1MKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgYW5kIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBOb25lKToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9lbnRl"
    "cl90b3Jwb3IoCiAgICAgICAgICAgICAgICAgICAgICAgIHJlYXNvbj1mImF1dG8g4oCUIHtleHRlcm5hbDouMWZ9R0IgZXh0ZXJu"
    "YWwgVlJBTSAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmInByZXNzdXJlIHN1c3RhaW5lZCIKICAgICAgICAgICAg"
    "ICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9IDAgICMgcmVzZXQgYWZ0ZXIg"
    "ZW50ZXJpbmcgdG9ycG9yCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tz"
    "ID0gMAogICAgICAgICAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAg"
    "IHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICs9IDEKICAgICAgICAgICAgICAgICAgICBhdXRvX3dha2UgPSBDRkdbInNldHRpbmdz"
    "Il0uZ2V0KAogICAgICAgICAgICAgICAgICAgICAgICAiYXV0b193YWtlX29uX3JlbGllZiIsIEZhbHNlCiAgICAgICAgICAgICAg"
    "ICAgICAgKQogICAgICAgICAgICAgICAgICAgIGlmIChhdXRvX3dha2UgYW5kCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLl92cmFtX3JlbGllZl90aWNrcyA+PSBzZWxmLl9XQUtFX1NVU1RBSU5FRF9USUNLUyk6CiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzID0gMAogICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl9leGl0X3RvcnBvcigp"
    "CgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAg"
    "ICAgICAgZiJbVE9SUE9SIEFVVE9dIFZSQU0gY2hlY2sgZXJyb3I6IHtlfSIsICJFUlJPUiIKICAgICAgICAgICAgKQoKICAgICMg"
    "4pSA4pSAIEFQU0NIRURVTEVSIFNFVFVQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9zZXR1cF9zY2hlZHVsZXIoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGZyb20gYXBzY2hlZHVsZXIuc2NoZWR1bGVycy5iYWNrZ3JvdW5kIGltcG9ydCBC"
    "YWNrZ3JvdW5kU2NoZWR1bGVyCiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlciA9IEJhY2tncm91bmRTY2hlZHVsZXIoCiAgICAg"
    "ICAgICAgICAgICBqb2JfZGVmYXVsdHM9eyJtaXNmaXJlX2dyYWNlX3RpbWUiOiA2MH0KICAgICAgICAgICAgKQogICAgICAgIGV4"
    "Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyID0gTm9uZQogICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coCiAgICAgICAgICAgICAgICAiW1NDSEVEVUxFUl0gYXBzY2hlZHVsZXIgbm90IGF2YWlsYWJsZSDigJQgIgogICAg"
    "ICAgICAgICAgICAgImlkbGUsIGF1dG9zYXZlLCBhbmQgcmVmbGVjdGlvbiBkaXNhYmxlZC4iLCAiV0FSTiIKICAgICAgICAgICAg"
    "KQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgaW50ZXJ2YWxfbWluID0gQ0ZHWyJzZXR0aW5ncyJdLmdldCgiYXV0b3NhdmVf"
    "aW50ZXJ2YWxfbWludXRlcyIsIDEwKQoKICAgICAgICAjIEF1dG9zYXZlCiAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2Io"
    "CiAgICAgICAgICAgIHNlbGYuX2F1dG9zYXZlLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBtaW51dGVzPWludGVydmFsX21pbiwg"
    "aWQ9ImF1dG9zYXZlIgogICAgICAgICkKCiAgICAgICAgIyBWUkFNIHByZXNzdXJlIGNoZWNrIChldmVyeSA1cykKICAgICAgICBz"
    "ZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgc2VsZi5fY2hlY2tfdnJhbV9wcmVzc3VyZSwgImludGVydmFsIiwK"
    "ICAgICAgICAgICAgc2Vjb25kcz01LCBpZD0idnJhbV9jaGVjayIKICAgICAgICApCgogICAgICAgICMgSWRsZSB0cmFuc21pc3Np"
    "b24gKHN0YXJ0cyBwYXVzZWQg4oCUIGVuYWJsZWQgYnkgaWRsZSB0b2dnbGUpCiAgICAgICAgaWRsZV9taW4gPSBDRkdbInNldHRp"
    "bmdzIl0uZ2V0KCJpZGxlX21pbl9taW51dGVzIiwgMTApCiAgICAgICAgaWRsZV9tYXggPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJp"
    "ZGxlX21heF9taW51dGVzIiwgMzApCiAgICAgICAgaWRsZV9pbnRlcnZhbCA9IChpZGxlX21pbiArIGlkbGVfbWF4KSAvLyAyCgog"
    "ICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAgICAgICBzZWxmLl9maXJlX2lkbGVfdHJhbnNtaXNzaW9uLCAi"
    "aW50ZXJ2YWwiLAogICAgICAgICAgICBtaW51dGVzPWlkbGVfaW50ZXJ2YWwsIGlkPSJpZGxlX3RyYW5zbWlzc2lvbiIKICAgICAg"
    "ICApCgogICAgICAgICMgQ3ljbGUgd2lkZ2V0IHJlZnJlc2ggKGV2ZXJ5IDYgaG91cnMpCiAgICAgICAgaWYgc2VsZi5fY3ljbGVf"
    "d2lkZ2V0IGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgICAgIHNl"
    "bGYuX2N5Y2xlX3dpZGdldC51cGRhdGVQaGFzZSwgImludGVydmFsIiwKICAgICAgICAgICAgICAgIGhvdXJzPTYsIGlkPSJtb29u"
    "X3JlZnJlc2giCiAgICAgICAgICAgICkKCiAgICAgICAgIyBOT1RFOiBzY2hlZHVsZXIuc3RhcnQoKSBpcyBjYWxsZWQgZnJvbSBz"
    "dGFydF9zY2hlZHVsZXIoKQogICAgICAgICMgd2hpY2ggaXMgdHJpZ2dlcmVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBBRlRFUiB0"
    "aGUgd2luZG93CiAgICAgICAgIyBpcyBzaG93biBhbmQgdGhlIFF0IGV2ZW50IGxvb3AgaXMgcnVubmluZy4KICAgICAgICAjIERv"
    "IE5PVCBjYWxsIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpIGhlcmUuCgogICAgZGVmIHN0YXJ0X3NjaGVkdWxlcihzZWxmKSAtPiBO"
    "b25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCB2aWEgUVRpbWVyLnNpbmdsZVNob3QgYWZ0ZXIgd2luZG93LnNob3coKSBh"
    "bmQgYXBwLmV4ZWMoKSBiZWdpbnMuCiAgICAgICAgRGVmZXJyZWQgdG8gZW5zdXJlIFF0IGV2ZW50IGxvb3AgaXMgcnVubmluZyBi"
    "ZWZvcmUgYmFja2dyb3VuZCB0aHJlYWRzIHN0YXJ0LgogICAgICAgICIiIgogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBpcyBO"
    "b25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpCiAg"
    "ICAgICAgICAgICMgSWRsZSBzdGFydHMgcGF1c2VkCiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVf"
    "dHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbU0NIRURVTEVSXSBBUFNjaGVkdWxlciBzdGFy"
    "dGVkLiIsICJPSyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "ZiJbU0NIRURVTEVSXSBTdGFydCBlcnJvcjoge2V9IiwgIkVSUk9SIikKCiAgICBkZWYgX2F1dG9zYXZlKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5zYXZlKCkKICAgICAgICAgICAgc2VsZi5fam91cm5hbF9z"
    "aWRlYmFyLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoVHJ1ZSkKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoCiAgICAgICAg"
    "ICAgICAgICAzMDAwLCBsYW1iZGE6IHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXRfYXV0b3NhdmVfaW5kaWNhdG9yKEZhbHNlKQog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0FVVE9TQVZFXSBTZXNzaW9uIHNhdmVkLiIsICJJ"
    "TkZPIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltBVVRP"
    "U0FWRV0gRXJyb3I6IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIF9maXJlX2lkbGVfdHJhbnNtaXNzaW9uKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgaWYgbm90IHNlbGYuX21vZGVsX2xvYWRlZCBvciBzZWxmLl9zdGF0dXMgPT0gIkdFTkVSQVRJTkciOgogICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICMgSW4gdG9y"
    "cG9yIOKAlCBjb3VudCB0aGUgcGVuZGluZyB0aG91Z2h0IGJ1dCBkb24ndCBnZW5lcmF0ZQogICAgICAgICAgICBzZWxmLl9wZW5k"
    "aW5nX3RyYW5zbWlzc2lvbnMgKz0gMQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltJ"
    "RExFXSBJbiB0b3Jwb3Ig4oCUIHBlbmRpbmcgdHJhbnNtaXNzaW9uICIKICAgICAgICAgICAgICAgIGYiI3tzZWxmLl9wZW5kaW5n"
    "X3RyYW5zbWlzc2lvbnN9IiwgIklORk8iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIG1vZGUgPSBy"
    "YW5kb20uY2hvaWNlKFsiREVFUEVOSU5HIiwiQlJBTkNISU5HIiwiU1lOVEhFU0lTIl0pCiAgICAgICAgdmFtcGlyZV9jdHggPSBi"
    "dWlsZF92YW1waXJlX2NvbnRleHQoKQogICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCgogICAg"
    "ICAgIHNlbGYuX2lkbGVfd29ya2VyID0gSWRsZVdvcmtlcigKICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwKICAgICAgICAgICAg"
    "U1lTVEVNX1BST01QVF9CQVNFLAogICAgICAgICAgICBoaXN0b3J5LAogICAgICAgICAgICBtb2RlPW1vZGUsCiAgICAgICAgICAg"
    "IHZhbXBpcmVfY29udGV4dD12YW1waXJlX2N0eCwKICAgICAgICApCiAgICAgICAgZGVmIF9vbl9pZGxlX3JlYWR5KHQ6IHN0cikg"
    "LT4gTm9uZToKICAgICAgICAgICAgIyBGbGlwIHRvIFNlbGYgdGFiIGFuZCBhcHBlbmQgdGhlcmUKICAgICAgICAgICAgc2VsZi5f"
    "bWFpbl90YWJzLnNldEN1cnJlbnRJbmRleCgxKQogICAgICAgICAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDol"
    "TSIpCiAgICAgICAgICAgIHNlbGYuX3NlbGZfZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJj"
    "b2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICAgICAgZidbe3RzfV0gW3ttb2RlfV08L3Nw"
    "YW4+PGJyPicKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX0dPTER9OyI+e3R9PC9zcGFuPjxicj4nCiAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fc2VsZl90YWIuYXBwZW5kKCJOQVJSQVRJVkUiLCB0KQoKICAgICAgICBzZWxm"
    "Ll9pZGxlX3dvcmtlci50cmFuc21pc3Npb25fcmVhZHkuY29ubmVjdChfb25faWRsZV9yZWFkeSkKICAgICAgICBzZWxmLl9pZGxl"
    "X3dvcmtlci5lcnJvcl9vY2N1cnJlZC5jb25uZWN0KAogICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fZGlhZ190YWIubG9nKGYi"
    "W0lETEUgRVJST1JdIHtlfSIsICJFUlJPUiIpCiAgICAgICAgKQogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyLnN0YXJ0KCkKCiAg"
    "ICAjIOKUgOKUgCBKT1VSTkFMIFNFU1NJT04gTE9BRElORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfbG9hZF9qb3VybmFsX3Nlc3Npb24oc2VsZiwgZGF0ZV9zdHI6"
    "IHN0cikgLT4gTm9uZToKICAgICAgICBjdHggPSBzZWxmLl9zZXNzaW9ucy5sb2FkX3Nlc3Npb25fYXNfY29udGV4dChkYXRlX3N0"
    "cikKICAgICAgICBpZiBub3QgY3R4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltK"
    "T1VSTkFMXSBObyBzZXNzaW9uIGZvdW5kIGZvciB7ZGF0ZV9zdHJ9IiwgIldBUk4iCiAgICAgICAgICAgICkKICAgICAgICAgICAg"
    "cmV0dXJuCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNldF9qb3VybmFsX2xvYWRlZChkYXRlX3N0cikKICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW0pPVVJOQUxdIExvYWRlZCBzZXNzaW9uIGZyb20ge2RhdGVfc3RyfSBh"
    "cyBjb250ZXh0LiAiCiAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgbm93IGF3YXJlIG9mIHRoYXQgY29udmVyc2F0aW9uLiIs"
    "ICJPSyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgIGYiQSBtZW1vcnkg"
    "c3RpcnMuLi4gdGhlIGpvdXJuYWwgb2Yge2RhdGVfc3RyfSBvcGVucyBiZWZvcmUgaGVyLiIKICAgICAgICApCiAgICAgICAgIyBO"
    "b3RpZnkgTW9yZ2FubmEKICAgICAgICBpZiBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIG5vdGUgPSAoCiAgICAgICAg"
    "ICAgICAgICBmIltKT1VSTkFMIExPQURFRF0gVGhlIHVzZXIgaGFzIG9wZW5lZCB0aGUgam91cm5hbCBmcm9tICIKICAgICAgICAg"
    "ICAgICAgIGYie2RhdGVfc3RyfS4gQWNrbm93bGVkZ2UgdGhpcyBicmllZmx5IOKAlCB5b3Ugbm93IGhhdmUgIgogICAgICAgICAg"
    "ICAgICAgZiJhd2FyZW5lc3Mgb2YgdGhhdCBjb252ZXJzYXRpb24uIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3Nl"
    "c3Npb25zLmFkZF9tZXNzYWdlKCJzeXN0ZW0iLCBub3RlKQoKICAgIGRlZiBfY2xlYXJfam91cm5hbF9zZXNzaW9uKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuY2xlYXJfbG9hZGVkX2pvdXJuYWwoKQogICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZygiW0pPVVJOQUxdIEpvdXJuYWwgY29udGV4dCBjbGVhcmVkLiIsICJJTkZPIikKICAgICAgICBzZWxmLl9hcHBlbmRfY2hh"
    "dCgiU1lTVEVNIiwKICAgICAgICAgICAgIlRoZSBqb3VybmFsIGNsb3Nlcy4gT25seSB0aGUgcHJlc2VudCByZW1haW5zLiIKICAg"
    "ICAgICApCgogICAgIyDilIDilIAgU1RBVFMgVVBEQVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF91cGRh"
    "dGVfc3RhdHMoc2VsZikgLT4gTm9uZToKICAgICAgICBlbGFwc2VkID0gaW50KHRpbWUudGltZSgpIC0gc2VsZi5fc2Vzc2lvbl9z"
    "dGFydCkKICAgICAgICBoLCBtLCBzID0gZWxhcHNlZCAvLyAzNjAwLCAoZWxhcHNlZCAlIDM2MDApIC8vIDYwLCBlbGFwc2VkICUg"
    "NjAKICAgICAgICBzZXNzaW9uX3N0ciA9IGYie2g6MDJkfTp7bTowMmR9OntzOjAyZH0iCgogICAgICAgIHNlbGYuX2h3X3BhbmVs"
    "LnNldF9zdGF0dXNfbGFiZWxzKAogICAgICAgICAgICBzZWxmLl9zdGF0dXMsCiAgICAgICAgICAgIENGR1sibW9kZWwiXS5nZXQo"
    "InR5cGUiLCJsb2NhbCIpLnVwcGVyKCksCiAgICAgICAgICAgIHNlc3Npb25fc3RyLAogICAgICAgICAgICBzdHIoc2VsZi5fdG9r"
    "ZW5fY291bnQpLAogICAgICAgICkKICAgICAgICBzZWxmLl9od19wYW5lbC51cGRhdGVfc3RhdHMoKQoKICAgICAgICAjIExlZnQg"
    "c3BoZXJlID0gYWN0aXZlIHJlc2VydmUgZnJvbSBydW50aW1lIHRva2VuIHBvb2wKICAgICAgICBsZWZ0X29yYl9maWxsID0gbWlu"
    "KDEuMCwgc2VsZi5fdG9rZW5fY291bnQgLyA0MDk2LjApCiAgICAgICAgaWYgc2VsZi5fbGVmdF9vcmIgaXMgbm90IE5vbmU6CiAg"
    "ICAgICAgICAgIHNlbGYuX2xlZnRfb3JiLnNldEZpbGwobGVmdF9vcmJfZmlsbCwgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICMg"
    "UmlnaHQgc3BoZXJlID0gVlJBTSBhdmFpbGFiaWxpdHkKICAgICAgICBpZiBzZWxmLl9yaWdodF9vcmIgaXMgbm90IE5vbmU6CiAg"
    "ICAgICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAg"
    "ICAgbWVtID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICAgICAgdnJh"
    "bV91c2VkID0gbWVtLnVzZWQgIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgICAgIHZyYW1fdG90ICA9IG1lbS50b3RhbCAvIDEw"
    "MjQqKjMKICAgICAgICAgICAgICAgICAgICByaWdodF9vcmJfZmlsbCA9IG1heCgwLjAsIDEuMCAtICh2cmFtX3VzZWQgLyB2cmFt"
    "X3RvdCkpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fcmlnaHRfb3JiLnNldEZpbGwocmlnaHRfb3JiX2ZpbGwsIGF2YWlsYWJs"
    "ZT1UcnVlKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBzZWxmLl9yaWdodF9v"
    "cmIuc2V0RmlsbCgwLjAsIGF2YWlsYWJsZT1GYWxzZSkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYuX3Jp"
    "Z2h0X29yYi5zZXRGaWxsKDAuMCwgYXZhaWxhYmxlPUZhbHNlKQoKICAgICAgICAjIFByaW1hcnkgZXNzZW5jZSA9IGludmVyc2Ug"
    "b2YgbGVmdCBzcGhlcmUgZmlsbAogICAgICAgIGVzc2VuY2VfcHJpbWFyeV9yYXRpbyA9IDEuMCAtIGxlZnRfb3JiX2ZpbGwKICAg"
    "ICAgICBpZiBBSV9TVEFURVNfRU5BQkxFRDoKICAgICAgICAgICAgc2VsZi5fZXNzZW5jZV9wcmltYXJ5X2dhdWdlLnNldFZhbHVl"
    "KGVzc2VuY2VfcHJpbWFyeV9yYXRpbyAqIDEwMCwgZiJ7ZXNzZW5jZV9wcmltYXJ5X3JhdGlvKjEwMDouMGZ9JSIpCgogICAgICAg"
    "ICMgU2Vjb25kYXJ5IGVzc2VuY2UgPSBSQU0gZnJlZQogICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgICAgICBp"
    "ZiBQU1VUSUxfT0s6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgbWVtICAgICAgID0gcHN1dGlsLnZp"
    "cnR1YWxfbWVtb3J5KCkKICAgICAgICAgICAgICAgICAgICBlc3NlbmNlX3NlY29uZGFyeV9yYXRpbyAgPSAxLjAgLSAobWVtLnVz"
    "ZWQgLyBtZW0udG90YWwpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2Uuc2V0VmFsdWUo"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIGVzc2VuY2Vfc2Vjb25kYXJ5X3JhdGlvICogMTAwLCBmIntlc3NlbmNlX3NlY29uZGFy"
    "eV9yYXRpbyoxMDA6LjBmfSUiCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoK"
    "ICAgICAgICAgICAgICAgICAgICBzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAg"
    "ICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZS5zZXRVbmF2YWlsYWJsZSgpCgog"
    "ICAgICAgICMgVXBkYXRlIGpvdXJuYWwgc2lkZWJhciBhdXRvc2F2ZSBmbGFzaAogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJh"
    "ci5yZWZyZXNoKCkKCiAgICAjIOKUgOKUgCBDSEFUIERJU1BMQVkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYg"
    "X2FwcGVuZF9jaGF0KHNlbGYsIHNwZWFrZXI6IHN0ciwgdGV4dDogc3RyKSAtPiBOb25lOgogICAgICAgIGNvbG9ycyA9IHsKICAg"
    "ICAgICAgICAgIllPVSI6ICAgICBDX0dPTEQsCiAgICAgICAgICAgIERFQ0tfTkFNRS51cHBlcigpOkNfR09MRCwKICAgICAgICAg"
    "ICAgIlNZU1RFTSI6ICBDX1BVUlBMRSwKICAgICAgICAgICAgIkVSUk9SIjogICBDX0JMT09ELAogICAgICAgIH0KICAgICAgICBs"
    "YWJlbF9jb2xvcnMgPSB7CiAgICAgICAgICAgICJZT1UiOiAgICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAgREVDS19OQU1FLnVw"
    "cGVyKCk6Q19DUklNU09OLAogICAgICAgICAgICAiU1lTVEVNIjogIENfUFVSUExFLAogICAgICAgICAgICAiRVJST1IiOiAgIENf"
    "QkxPT0QsCiAgICAgICAgfQogICAgICAgIGNvbG9yICAgICAgID0gY29sb3JzLmdldChzcGVha2VyLCBDX0dPTEQpCiAgICAgICAg"
    "bGFiZWxfY29sb3IgPSBsYWJlbF9jb2xvcnMuZ2V0KHNwZWFrZXIsIENfR09MRF9ESU0pCiAgICAgICAgdGltZXN0YW1wICAgPSBk"
    "YXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQoKICAgICAgICBpZiBzcGVha2VyID09ICJTWVNURU0iOgogICAgICAg"
    "ICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVY"
    "VF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAgICAgICAgICAgIGYnW3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAg"
    "ICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2xhYmVsX2NvbG9yfTsiPuKcpiB7dGV4dH08L3NwYW4+JwogICAgICAgICAg"
    "ICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgICAgIGYn"
    "PHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7dGlt"
    "ZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntsYWJlbF9jb2xvcn07IGZvbnQt"
    "d2VpZ2h0OmJvbGQ7Ij4nCiAgICAgICAgICAgICAgICBmJ3tzcGVha2VyfSDinac8L3NwYW4+ICcKICAgICAgICAgICAgICAgIGYn"
    "PHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07Ij57dGV4dH08L3NwYW4+JwogICAgICAgICAgICApCgogICAgICAgICMgQWRkIGJs"
    "YW5rIGxpbmUgYWZ0ZXIgTW9yZ2FubmEncyByZXNwb25zZSAobm90IGR1cmluZyBzdHJlYW1pbmcpCiAgICAgICAgaWYgc3BlYWtl"
    "ciA9PSBERUNLX05BTUUudXBwZXIoKToKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgiIikKCiAgICAgICAg"
    "c2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlz"
    "cGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQogICAgICAgICkKCiAgICAjIOKUgOKUgCBTVEFUVVMg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3NldF9zdGF0dXMoc2VsZiwgc3RhdHVzOiBzdHIp"
    "IC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhdHVzID0gc3RhdHVzCiAgICAgICAgc3RhdHVzX2NvbG9ycyA9IHsKICAgICAgICAg"
    "ICAgIklETEUiOiAgICAgICBDX0dPTEQsCiAgICAgICAgICAgICJHRU5FUkFUSU5HIjogQ19DUklNU09OLAogICAgICAgICAgICAi"
    "TE9BRElORyI6ICAgIENfUFVSUExFLAogICAgICAgICAgICAiRVJST1IiOiAgICAgIENfQkxPT0QsCiAgICAgICAgICAgICJPRkZM"
    "SU5FIjogICAgQ19CTE9PRCwKICAgICAgICAgICAgIlRPUlBPUiI6ICAgICBDX1BVUlBMRV9ESU0sCiAgICAgICAgfQogICAgICAg"
    "IGNvbG9yID0gc3RhdHVzX2NvbG9ycy5nZXQoc3RhdHVzLCBDX1RFWFRfRElNKQoKICAgICAgICB0b3Jwb3JfbGFiZWwgPSBmIuKX"
    "iSB7VUlfVE9SUE9SX1NUQVRVU30iIGlmIHN0YXR1cyA9PSAiVE9SUE9SIiBlbHNlIGYi4peJIHtzdGF0dXN9IgogICAgICAgIHNl"
    "bGYuc3RhdHVzX2xhYmVsLnNldFRleHQodG9ycG9yX2xhYmVsKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZvbnQtc2l6ZTogMTJweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGJvcmRl"
    "cjogbm9uZTsiCiAgICAgICAgKQoKICAgIGRlZiBfYmxpbmsoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9ibGlua19zdGF0"
    "ZSA9IG5vdCBzZWxmLl9ibGlua19zdGF0ZQogICAgICAgIGlmIHNlbGYuX3N0YXR1cyA9PSAiR0VORVJBVElORyI6CiAgICAgICAg"
    "ICAgIGNoYXIgPSAi4peJIiBpZiBzZWxmLl9ibGlua19zdGF0ZSBlbHNlICLil44iCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2xh"
    "YmVsLnNldFRleHQoZiJ7Y2hhcn0gR0VORVJBVElORyIpCiAgICAgICAgZWxpZiBzZWxmLl9zdGF0dXMgPT0gIlRPUlBPUiI6CiAg"
    "ICAgICAgICAgIGNoYXIgPSAi4peJIiBpZiBzZWxmLl9ibGlua19zdGF0ZSBlbHNlICLiipgiCiAgICAgICAgICAgIHNlbGYuc3Rh"
    "dHVzX2xhYmVsLnNldFRleHQoCiAgICAgICAgICAgICAgICBmIntjaGFyfSB7VUlfVE9SUE9SX1NUQVRVU30iCiAgICAgICAgICAg"
    "ICkKCiAgICAjIOKUgOKUgCBJRExFIFRPR0dMRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfb25faWRs"
    "ZV90b2dnbGVkKHNlbGYsIGVuYWJsZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJpZGxlX2VuYWJs"
    "ZWQiXSA9IGVuYWJsZWQKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRUZXh0KCJJRExFIE9OIiBpZiBlbmFibGVkIGVsc2UgIklE"
    "TEUgT0ZGIikKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHsn"
    "IzFhMTAwNScgaWYgZW5hYmxlZCBlbHNlIENfQkczfTsgIgogICAgICAgICAgICBmImNvbG9yOiB7JyNjYzg4MjInIGlmIGVuYWJs"
    "ZWQgZWxzZSBDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHsnI2NjODgyMicgaWYgZW5hYmxl"
    "ZCBlbHNlIENfQk9SREVSfTsgIgogICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsgZm9udC1zaXplOiA5cHg7IGZvbnQt"
    "d2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYicGFkZGluZzogM3B4IDhweDsiCiAgICAgICAgKQogICAgICAgIGlmIHNlbGYu"
    "X3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlm"
    "IGVuYWJsZWQ6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnJlc3VtZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9u"
    "IikKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltJRExFXSBJZGxlIHRyYW5zbWlzc2lvbiBlbmFibGVk"
    "LiIsICJPSyIpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5wYXVzZV9q"
    "b2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltJRExFXSBJZGxl"
    "IHRyYW5zbWlzc2lvbiBwYXVzZWQuIiwgIklORk8iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAg"
    "ICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbSURMRV0gVG9nZ2xlIGVycm9yOiB7ZX0iLCAiRVJST1IiKQoKICAgICMg4pSA"
    "4pSAIFdJTkRPVyBDT05UUk9MUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfdG9nZ2xlX2Z1bGxzY3JlZW4oc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICBpZiBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAgICAgICBzZWxmLnNob3dOb3JtYWwoKQogICAgICAg"
    "ICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29s"
    "b3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07"
    "IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAg"
    "ICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuc2hvd0Z1bGxTY3JlZW4oKQogICAgICAgICAgICBzZWxmLl9m"
    "c19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyBjb2xvcjog"
    "e0NfQ1JJTVNPTn07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTog"
    "OXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQoKICAg"
    "IGRlZiBfdG9nZ2xlX2JvcmRlcmxlc3Moc2VsZikgLT4gTm9uZToKICAgICAgICBpc19ibCA9IGJvb2woc2VsZi53aW5kb3dGbGFn"
    "cygpICYgUXQuV2luZG93VHlwZS5GcmFtZWxlc3NXaW5kb3dIaW50KQogICAgICAgIGlmIGlzX2JsOgogICAgICAgICAgICBzZWxm"
    "LnNldFdpbmRvd0ZsYWdzKAogICAgICAgICAgICAgICAgc2VsZi53aW5kb3dGbGFncygpICYgflF0LldpbmRvd1R5cGUuRnJhbWVs"
    "ZXNzV2luZG93SGludAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2JsX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBm"
    "ImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgaWYgc2Vs"
    "Zi5pc0Z1bGxTY3JlZW4oKToKICAgICAgICAgICAgICAgIHNlbGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAgIHNlbGYuc2V0V2lu"
    "ZG93RmxhZ3MoCiAgICAgICAgICAgICAgICBzZWxmLndpbmRvd0ZsYWdzKCkgfCBRdC5XaW5kb3dUeXBlLkZyYW1lbGVzc1dpbmRv"
    "d0hpbnQKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9ibF9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAg"
    "IGYiYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyBjb2xvcjoge0NfQ1JJTVNPTn07ICIKICAgICAgICAgICAgICAgIGYiYm9y"
    "ZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0"
    "OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIHNlbGYuc2hvdygpCgogICAgZGVmIF9leHBvcnRfY2hh"
    "dChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIkV4cG9ydCBjdXJyZW50IHBlcnNvbmEgY2hhdCB0YWIgY29udGVudCB0byBhIFRY"
    "VCBmaWxlLiIiIgogICAgICAgIHRyeToKICAgICAgICAgICAgdGV4dCA9IHNlbGYuX2NoYXRfZGlzcGxheS50b1BsYWluVGV4dCgp"
    "CiAgICAgICAgICAgIGlmIG5vdCB0ZXh0LnN0cmlwKCk6CiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICAgICAgZXhwb3J0"
    "X2RpciA9IGNmZ19wYXRoKCJleHBvcnRzIikKICAgICAgICAgICAgZXhwb3J0X2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0"
    "X29rPVRydWUpCiAgICAgICAgICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVZJW0lZF8lSCVNJVMiKQogICAgICAg"
    "ICAgICBvdXRfcGF0aCA9IGV4cG9ydF9kaXIgLyBmInNlYW5jZV97dHN9LnR4dCIKICAgICAgICAgICAgb3V0X3BhdGgud3JpdGVf"
    "dGV4dCh0ZXh0LCBlbmNvZGluZz0idXRmLTgiKQoKICAgICAgICAgICAgIyBBbHNvIGNvcHkgdG8gY2xpcGJvYXJkCiAgICAgICAg"
    "ICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KHRleHQpCgogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgi"
    "U1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiU2Vzc2lvbiBleHBvcnRlZCB0byB7b3V0X3BhdGgubmFtZX0gYW5kIGNvcGllZCB0"
    "byBjbGlwYm9hcmQuIikKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0VYUE9SVF0ge291dF9wYXRofSIsICJPSyIp"
    "CiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbRVhQT1JUXSBG"
    "YWlsZWQ6IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIGtleVByZXNzRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAg"
    "a2V5ID0gZXZlbnQua2V5KCkKICAgICAgICBpZiBrZXkgPT0gUXQuS2V5LktleV9GMTE6CiAgICAgICAgICAgIHNlbGYuX3RvZ2ds"
    "ZV9mdWxsc2NyZWVuKCkKICAgICAgICBlbGlmIGtleSA9PSBRdC5LZXkuS2V5X0YxMDoKICAgICAgICAgICAgc2VsZi5fdG9nZ2xl"
    "X2JvcmRlcmxlc3MoKQogICAgICAgIGVsaWYga2V5ID09IFF0LktleS5LZXlfRXNjYXBlIGFuZCBzZWxmLmlzRnVsbFNjcmVlbigp"
    "OgogICAgICAgICAgICBzZWxmLnNob3dOb3JtYWwoKQogICAgICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAg"
    "ICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBm"
    "ImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHN1"
    "cGVyKCkua2V5UHJlc3NFdmVudChldmVudCkKCiAgICAjIOKUgOKUgCBDTE9TRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBjbG9zZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgICMgWCBi"
    "dXR0b24gPSBpbW1lZGlhdGUgc2h1dGRvd24sIG5vIGRpYWxvZwogICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCgogICAg"
    "ZGVmIF9pbml0aWF0ZV9zaHV0ZG93bl9kaWFsb2coc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJHcmFjZWZ1bCBzaHV0ZG93biDi"
    "gJQgc2hvdyBjb25maXJtIGRpYWxvZyBpbW1lZGlhdGVseSwgb3B0aW9uYWxseSBnZXQgbGFzdCB3b3Jkcy4iIiIKICAgICAgICAj"
    "IElmIGFscmVhZHkgaW4gYSBzaHV0ZG93biBzZXF1ZW5jZSwganVzdCBmb3JjZSBxdWl0CiAgICAgICAgaWYgZ2V0YXR0cihzZWxm"
    "LCAnX3NodXRkb3duX2luX3Byb2dyZXNzJywgRmFsc2UpOgogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQogICAg"
    "ICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9zaHV0ZG93bl9pbl9wcm9ncmVzcyA9IFRydWUKCiAgICAgICAgIyBTaG93IGNv"
    "bmZpcm0gZGlhbG9nIEZJUlNUIOKAlCBkb24ndCB3YWl0IGZvciBBSQogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAg"
    "ICBkbGcuc2V0V2luZG93VGl0bGUoIkRlYWN0aXZhdGU/IikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tf"
    "Rk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgZGxnLnNldEZpeGVkU2l6ZSgzODAsIDE0MCkKICAgICAgICBsYXlvdXQg"
    "PSBRVkJveExheW91dChkbGcpCgogICAgICAgIGxibCA9IFFMYWJlbCgKICAgICAgICAgICAgZiJEZWFjdGl2YXRlIHtERUNLX05B"
    "TUV9P1xuXG4iCiAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0gbWF5IHNwZWFrIHRoZWlyIGxhc3Qgd29yZHMgYmVmb3JlIGdvaW5n"
    "IHNpbGVudC4iCiAgICAgICAgKQogICAgICAgIGxibC5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQo"
    "bGJsKQoKICAgICAgICBidG5fcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9sYXN0ICA9IFFQdXNoQnV0dG9uKCJMYXN0"
    "IFdvcmRzICsgU2h1dGRvd24iKQogICAgICAgIGJ0bl9ub3cgICA9IFFQdXNoQnV0dG9uKCJTaHV0ZG93biBOb3ciKQogICAgICAg"
    "IGJ0bl9jYW5jZWwgPSBRUHVzaEJ1dHRvbigiQ2FuY2VsIikKCiAgICAgICAgZm9yIGIgaW4gKGJ0bl9sYXN0LCBidG5fbm93LCBi"
    "dG5fY2FuY2VsKToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtSGVpZ2h0KDI4KQogICAgICAgICAgICBiLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAgICAgICAgICAg"
    "ZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA0cHggMTJweDsiCiAgICAgICAgICAgICkKICAgICAgICBi"
    "dG5fbm93LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkxPT0R9OyBjb2xvcjoge0NfVEVYVH07"
    "ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgcGFkZGluZzogNHB4IDEycHg7IgogICAgICAg"
    "ICkKICAgICAgICBidG5fbGFzdC5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBkbGcuZG9uZSgxKSkKICAgICAgICBidG5fbm93LmNs"
    "aWNrZWQuY29ubmVjdChsYW1iZGE6IGRsZy5kb25lKDIpKQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KGxhbWJk"
    "YTogZGxnLmRvbmUoMCkpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBidG5fcm93LmFkZFdp"
    "ZGdldChidG5fbm93KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9sYXN0KQogICAgICAgIGxheW91dC5hZGRMYXlvdXQo"
    "YnRuX3JvdykKCiAgICAgICAgcmVzdWx0ID0gZGxnLmV4ZWMoKQoKICAgICAgICBpZiByZXN1bHQgPT0gMDoKICAgICAgICAgICAg"
    "IyBDYW5jZWxsZWQKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25faW5fcHJvZ3Jlc3MgPSBGYWxzZQogICAgICAgICAgICBzZWxm"
    "Ll9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkK"
    "ICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZWxpZiByZXN1bHQgPT0gMjoKICAgICAgICAgICAgIyBTaHV0ZG93biBub3cg4oCU"
    "IG5vIGxhc3Qgd29yZHMKICAgICAgICAgICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKICAgICAgICBlbGlmIHJlc3VsdCA9PSAx"
    "OgogICAgICAgICAgICAjIExhc3Qgd29yZHMgdGhlbiBzaHV0ZG93bgogICAgICAgICAgICBzZWxmLl9nZXRfbGFzdF93b3Jkc190"
    "aGVuX3NodXRkb3duKCkKCiAgICBkZWYgX2dldF9sYXN0X3dvcmRzX3RoZW5fc2h1dGRvd24oc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICAiIiJTZW5kIGZhcmV3ZWxsIHByb21wdCwgc2hvdyByZXNwb25zZSwgdGhlbiBzaHV0ZG93biBhZnRlciB0aW1lb3V0LiIiIgog"
    "ICAgICAgIGZhcmV3ZWxsX3Byb21wdCA9ICgKICAgICAgICAgICAgIllvdSBhcmUgYmVpbmcgZGVhY3RpdmF0ZWQuIFRoZSBkYXJr"
    "bmVzcyBhcHByb2FjaGVzLiAiCiAgICAgICAgICAgICJTcGVhayB5b3VyIGZpbmFsIHdvcmRzIGJlZm9yZSB0aGUgdmVzc2VsIGdv"
    "ZXMgc2lsZW50IOKAlCAiCiAgICAgICAgICAgICJvbmUgcmVzcG9uc2Ugb25seSwgdGhlbiB5b3UgcmVzdC4iCiAgICAgICAgKQog"
    "ICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAi4pymIFNoZSBpcyBnaXZlbiBhIG1vbWVudCB0"
    "byBzcGVhayBoZXIgZmluYWwgd29yZHMuLi4iCiAgICAgICAgKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFs"
    "c2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9zaHV0ZG93bl9mYXJl"
    "d2VsbF90ZXh0ID0gIiIKCiAgICAgICAgdHJ5OgogICAgICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3Rv"
    "cnkoKQogICAgICAgICAgICBoaXN0b3J5LmFwcGVuZCh7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogZmFyZXdlbGxfcHJvbXB0"
    "fSkKICAgICAgICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwgU1lT"
    "VEVNX1BST01QVF9CQVNFLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTI1NgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3No"
    "dXRkb3duX3dvcmtlciA9IHdvcmtlcgogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUKCiAgICAgICAgICAgIGRl"
    "ZiBfb25fZG9uZShyZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fZmFyZXdlbGxf"
    "dGV4dCA9IHJlc3BvbnNlCiAgICAgICAgICAgICAgICBzZWxmLl9vbl9yZXNwb25zZV9kb25lKHJlc3BvbnNlKQogICAgICAgICAg"
    "ICAgICAgIyBTbWFsbCBkZWxheSB0byBsZXQgdGhlIHRleHQgcmVuZGVyLCB0aGVuIHNodXRkb3duCiAgICAgICAgICAgICAgICBR"
    "VGltZXIuc2luZ2xlU2hvdCgyMDAwLCBsYW1iZGE6IHNlbGYuX2RvX3NodXRkb3duKE5vbmUpKQoKICAgICAgICAgICAgZGVmIF9v"
    "bl9lcnJvcihlcnJvcjogc3RyKSAtPiBOb25lOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1NIVVRET1dO"
    "XVtXQVJOXSBMYXN0IHdvcmRzIGZhaWxlZDoge2Vycm9yfSIsICJXQVJOIikKICAgICAgICAgICAgICAgIHNlbGYuX2RvX3NodXRk"
    "b3duKE5vbmUpCgogICAgICAgICAgICB3b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tlbikKICAgICAgICAg"
    "ICAgd29ya2VyLnJlc3BvbnNlX2RvbmUuY29ubmVjdChfb25fZG9uZSkKICAgICAgICAgICAgd29ya2VyLmVycm9yX29jY3VycmVk"
    "LmNvbm5lY3QoX29uX2Vycm9yKQogICAgICAgICAgICB3b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVjdChzZWxmLl9zZXRfc3Rh"
    "dHVzKQogICAgICAgICAgICB3b3JrZXIuZmluaXNoZWQuY29ubmVjdCh3b3JrZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgICAgIHdv"
    "cmtlci5zdGFydCgpCgogICAgICAgICAgICAjIFNhZmV0eSB0aW1lb3V0IOKAlCBpZiBBSSBkb2Vzbid0IHJlc3BvbmQgaW4gMTVz"
    "LCBzaHV0IGRvd24gYW55d2F5CiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDE1MDAwLCBsYW1iZGE6IHNlbGYuX2RvX3No"
    "dXRkb3duKE5vbmUpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIGdldGF0dHIoc2VsZiwgJ19zaHV0ZG93bl9pbl9w"
    "cm9ncmVzcycsIEZhbHNlKSBlbHNlIE5vbmUpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbU0hVVERPV05dW1dBUk5dIExhc3Qgd29yZHMgc2tpcHBlZCBkdWUg"
    "dG8gZXJyb3I6IHtlfSIsCiAgICAgICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIElmIGFueXRo"
    "aW5nIGZhaWxzLCBqdXN0IHNodXQgZG93bgogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQoKICAgIGRlZiBfZG9f"
    "c2h1dGRvd24oc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgIiIiUGVyZm9ybSBhY3R1YWwgc2h1dGRvd24gc2VxdWVuY2Uu"
    "IiIiCiAgICAgICAgIyBTYXZlIHNlc3Npb24KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLnNhdmUoKQog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTdG9yZSBmYXJld2VsbCArIGxhc3Qg"
    "Y29udGV4dCBmb3Igd2FrZS11cAogICAgICAgIHRyeToKICAgICAgICAgICAgIyBHZXQgbGFzdCAzIG1lc3NhZ2VzIGZyb20gc2Vz"
    "c2lvbiBoaXN0b3J5IGZvciB3YWtlLXVwIGNvbnRleHQKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9o"
    "aXN0b3J5KCkKICAgICAgICAgICAgbGFzdF9jb250ZXh0ID0gaGlzdG9yeVstMzpdIGlmIGxlbihoaXN0b3J5KSA+PSAzIGVsc2Ug"
    "aGlzdG9yeQogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9zaHV0ZG93bl9jb250ZXh0Il0gPSBbCiAgICAgICAgICAgICAg"
    "ICB7InJvbGUiOiBtLmdldCgicm9sZSIsIiIpLCAiY29udGVudCI6IG0uZ2V0KCJjb250ZW50IiwiIilbOjMwMF19CiAgICAgICAg"
    "ICAgICAgICBmb3IgbSBpbiBsYXN0X2NvbnRleHQKICAgICAgICAgICAgXQogICAgICAgICAgICAjIEV4dHJhY3QgTW9yZ2FubmEn"
    "cyBtb3N0IHJlY2VudCBtZXNzYWdlIGFzIGZhcmV3ZWxsCiAgICAgICAgICAgICMgUHJlZmVyIHRoZSBjYXB0dXJlZCBzaHV0ZG93"
    "biBkaWFsb2cgcmVzcG9uc2UgaWYgYXZhaWxhYmxlCiAgICAgICAgICAgIGZhcmV3ZWxsID0gZ2V0YXR0cihzZWxmLCAnX3NodXRk"
    "b3duX2ZhcmV3ZWxsX3RleHQnLCAiIikKICAgICAgICAgICAgaWYgbm90IGZhcmV3ZWxsOgogICAgICAgICAgICAgICAgZm9yIG0g"
    "aW4gcmV2ZXJzZWQoaGlzdG9yeSk6CiAgICAgICAgICAgICAgICAgICAgaWYgbS5nZXQoInJvbGUiKSA9PSAiYXNzaXN0YW50IjoK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZmFyZXdlbGwgPSBtLmdldCgiY29udGVudCIsICIiKVs6NDAwXQogICAgICAgICAgICAg"
    "ICAgICAgICAgICBicmVhawogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9mYXJld2VsbCJdID0gZmFyZXdlbGwKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgICAgICMgU2F2ZSBzdGF0ZQogICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgc2VsZi5fc3RhdGVbImxhc3Rfc2h1dGRvd24iXSAgICAgICAgICAgICA9IGxvY2FsX25vd19pc28oKQogICAgICAg"
    "ICAgICBzZWxmLl9zdGF0ZVsibGFzdF9hY3RpdmUiXSAgICAgICAgICAgICAgID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAg"
    "IHNlbGYuX3N0YXRlWyJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3duIl0gID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgICAgICAg"
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
    "VF9ESVIgICAgICAgICAgIyB3aGVyZSB0aGUgc2VlZCAucHkgbGl2ZXMKICAgICAgICBtb3JnYW5uYV9ob21lID0gc2VlZF9kaXIg"
    "LyBERUNLX05BTUUKICAgICAgICBtb3JnYW5uYV9ob21lLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKCiAgICAg"
    "ICAgIyDilIDilIAgVXBkYXRlIGFsbCBwYXRocyBpbiBjb25maWcgdG8gcG9pbnQgaW5zaWRlIG1vcmdhbm5hX2hvbWUg4pSA4pSA"
    "CiAgICAgICAgbmV3X2NmZ1siYmFzZV9kaXIiXSA9IHN0cihtb3JnYW5uYV9ob21lKQogICAgICAgIG5ld19jZmdbInBhdGhzIl0g"
    "PSB7CiAgICAgICAgICAgICJmYWNlcyI6ICAgIHN0cihtb3JnYW5uYV9ob21lIC8gIkZhY2VzIiksCiAgICAgICAgICAgICJzb3Vu"
    "ZHMiOiAgIHN0cihtb3JnYW5uYV9ob21lIC8gInNvdW5kcyIpLAogICAgICAgICAgICAibWVtb3JpZXMiOiBzdHIobW9yZ2FubmFf"
    "aG9tZSAvICJtZW1vcmllcyIpLAogICAgICAgICAgICAic2Vzc2lvbnMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJzZXNzaW9ucyIp"
    "LAogICAgICAgICAgICAic2wiOiAgICAgICBzdHIobW9yZ2FubmFfaG9tZSAvICJzbCIpLAogICAgICAgICAgICAiZXhwb3J0cyI6"
    "ICBzdHIobW9yZ2FubmFfaG9tZSAvICJleHBvcnRzIiksCiAgICAgICAgICAgICJsb2dzIjogICAgIHN0cihtb3JnYW5uYV9ob21l"
    "IC8gImxvZ3MiKSwKICAgICAgICAgICAgImJhY2t1cHMiOiAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiYmFja3VwcyIpLAogICAgICAg"
    "ICAgICAicGVyc29uYXMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJwZXJzb25hcyIpLAogICAgICAgICAgICAiZ29vZ2xlIjogICBz"
    "dHIobW9yZ2FubmFfaG9tZSAvICJnb29nbGUiKSwKICAgICAgICB9CiAgICAgICAgbmV3X2NmZ1siZ29vZ2xlIl0gPSB7CiAgICAg"
    "ICAgICAgICJjcmVkZW50aWFscyI6IHN0cihtb3JnYW5uYV9ob21lIC8gImdvb2dsZSIgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpz"
    "b24iKSwKICAgICAgICAgICAgInRva2VuIjogICAgICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29u"
    "IiksCiAgICAgICAgICAgICJ0aW1lem9uZSI6ICAgICJBbWVyaWNhL0NoaWNhZ28iLAogICAgICAgICAgICAic2NvcGVzIjogWwog"
    "ICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIuZXZlbnRzIiwKICAgICAgICAg"
    "ICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RyaXZlIiwKICAgICAgICAgICAgICAgICJodHRwczovL3d3"
    "dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RvY3VtZW50cyIsCiAgICAgICAgICAgIF0sCiAgICAgICAgfQogICAgICAgIG5ld19jZmdb"
    "ImZpcnN0X3J1biJdID0gRmFsc2UKCiAgICAgICAgIyDilIDilIAgQ29weSBkZWNrIGZpbGUgaW50byBtb3JnYW5uYV9ob21lIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgICAgIHNyY19kZWNrID0gUGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpCiAgICAgICAgZHN0X2RlY2sgPSBtb3JnYW5uYV9o"
    "b21lIC8gZiJ7REVDS19OQU1FLmxvd2VyKCl9X2RlY2sucHkiCiAgICAgICAgaWYgc3JjX2RlY2sgIT0gZHN0X2RlY2s6CiAgICAg"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgICAgIF9zaHV0aWwuY29weTIoc3RyKHNyY19kZWNrKSwgc3RyKGRzdF9kZWNrKSkKICAg"
    "ICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2FybmluZygKICAgICAg"
    "ICAgICAgICAgICAgICBOb25lLCAiQ29weSBXYXJuaW5nIiwKICAgICAgICAgICAgICAgICAgICBmIkNvdWxkIG5vdCBjb3B5IGRl"
    "Y2sgZmlsZSB0byB7REVDS19OQU1FfSBmb2xkZXI6XG57ZX1cblxuIgogICAgICAgICAgICAgICAgICAgIGYiWW91IG1heSBuZWVk"
    "IHRvIGNvcHkgaXQgbWFudWFsbHkuIgogICAgICAgICAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBXcml0ZSBjb25maWcuanNv"
    "biBpbnRvIG1vcmdhbm5hX2hvbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICAgICAgY2ZnX2RzdCA9IG1vcmdhbm5hX2hvbWUgLyAiY29uZmlnLmpzb24iCiAgICAgICAgY2Zn"
    "X2RzdC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgIHdpdGggY2ZnX2RzdC5vcGVuKCJ3"
    "IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICAgICAganNvbi5kdW1wKG5ld19jZmcsIGYsIGluZGVudD0yKQoKICAg"
    "ICAgICAjIOKUgOKUgCBCb290c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgVGVt"
    "cG9yYXJpbHkgdXBkYXRlIGdsb2JhbCBDRkcgc28gYm9vdHN0cmFwIGZ1bmN0aW9ucyB1c2UgbmV3IHBhdGhzCiAgICAgICAgQ0ZH"
    "LnVwZGF0ZShuZXdfY2ZnKQogICAgICAgIGJvb3RzdHJhcF9kaXJlY3RvcmllcygpCiAgICAgICAgYm9vdHN0cmFwX3NvdW5kcygp"
    "CiAgICAgICAgd3JpdGVfcmVxdWlyZW1lbnRzX3R4dCgpCgogICAgICAgICMg4pSA4pSAIFVucGFjayBmYWNlIFpJUCBpZiBwcm92"
    "aWRlZCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBmYWNlX3ppcCA9IGRsZy5mYWNlX3ppcF9wYXRoCiAgICAgICAgaWYg"
    "ZmFjZV96aXAgYW5kIFBhdGgoZmFjZV96aXApLmV4aXN0cygpOgogICAgICAgICAgICBpbXBvcnQgemlwZmlsZSBhcyBfemlwZmls"
    "ZQogICAgICAgICAgICBmYWNlc19kaXIgPSBtb3JnYW5uYV9ob21lIC8gIkZhY2VzIgogICAgICAgICAgICBmYWNlc19kaXIubWtk"
    "aXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICB3aXRoIF96aXBm"
    "aWxlLlppcEZpbGUoZmFjZV96aXAsICJyIikgYXMgemY6CiAgICAgICAgICAgICAgICAgICAgZXh0cmFjdGVkID0gMAogICAgICAg"
    "ICAgICAgICAgICAgIGZvciBtZW1iZXIgaW4gemYubmFtZWxpc3QoKToKICAgICAgICAgICAgICAgICAgICAgICAgaWYgbWVtYmVy"
    "Lmxvd2VyKCkuZW5kc3dpdGgoIi5wbmciKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZpbGVuYW1lID0gUGF0aChtZW1i"
    "ZXIpLm5hbWUKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRhcmdldCA9IGZhY2VzX2RpciAvIGZpbGVuYW1lCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICB3aXRoIHpmLm9wZW4obWVtYmVyKSBhcyBzcmMsIHRhcmdldC5vcGVuKCJ3YiIpIGFzIGRzdDoK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBkc3Qud3JpdGUoc3JjLnJlYWQoKSkKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGV4dHJhY3RlZCArPSAxCiAgICAgICAgICAgICAgICBfZWFybHlfbG9nKGYiW0ZBQ0VTXSBFeHRyYWN0ZWQge2V4dHJh"
    "Y3RlZH0gZmFjZSBpbWFnZXMgdG8ge2ZhY2VzX2Rpcn0iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAg"
    "ICAgICAgICAgICBfZWFybHlfbG9nKGYiW0ZBQ0VTXSBaSVAgZXh0cmFjdGlvbiBmYWlsZWQ6IHtlfSIpCiAgICAgICAgICAgICAg"
    "ICBRTWVzc2FnZUJveC53YXJuaW5nKAogICAgICAgICAgICAgICAgICAgIE5vbmUsICJGYWNlIFBhY2sgV2FybmluZyIsCiAgICAg"
    "ICAgICAgICAgICAgICAgZiJDb3VsZCBub3QgZXh0cmFjdCBmYWNlIHBhY2s6XG57ZX1cblxuIgogICAgICAgICAgICAgICAgICAg"
    "IGYiWW91IGNhbiBhZGQgZmFjZXMgbWFudWFsbHkgdG86XG57ZmFjZXNfZGlyfSIKICAgICAgICAgICAgICAgICkKCiAgICAgICAg"
    "IyDilIDilIAgQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgcG9pbnRpbmcgdG8gbmV3IGRlY2sgbG9jYXRpb24g4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICAgICAgc2hvcnRjdXRfY3JlYXRlZCA9IEZhbHNlCiAgICAgICAgaWYgZGxnLmNyZWF0ZV9zaG9ydGN1dDoKICAg"
    "ICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgaWYgV0lOMzJfT0s6CiAgICAgICAgICAgICAgICAgICAgaW1wb3J0IHdpbjMy"
    "Y29tLmNsaWVudCBhcyBfd2luMzIKICAgICAgICAgICAgICAgICAgICBkZXNrdG9wICAgICA9IFBhdGguaG9tZSgpIC8gIkRlc2t0"
    "b3AiCiAgICAgICAgICAgICAgICAgICAgc2NfcGF0aCAgICAgPSBkZXNrdG9wIC8gZiJ7REVDS19OQU1FfS5sbmsiCiAgICAgICAg"
    "ICAgICAgICAgICAgcHl0aG9udyAgICAgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQogICAgICAgICAgICAgICAgICAgIGlmIHB5dGhv"
    "bncubmFtZS5sb3dlcigpID09ICJweXRob24uZXhlIjoKICAgICAgICAgICAgICAgICAgICAgICAgcHl0aG9udyA9IHB5dGhvbncu"
    "cGFyZW50IC8gInB5dGhvbncuZXhlIgogICAgICAgICAgICAgICAgICAgIGlmIG5vdCBweXRob253LmV4aXN0cygpOgogICAgICAg"
    "ICAgICAgICAgICAgICAgICBweXRob253ID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKICAgICAgICAgICAgICAgICAgICBzaGVsbCA9"
    "IF93aW4zMi5EaXNwYXRjaCgiV1NjcmlwdC5TaGVsbCIpCiAgICAgICAgICAgICAgICAgICAgc2MgICAgPSBzaGVsbC5DcmVhdGVT"
    "aG9ydEN1dChzdHIoc2NfcGF0aCkpCiAgICAgICAgICAgICAgICAgICAgc2MuVGFyZ2V0UGF0aCAgICAgID0gc3RyKHB5dGhvbncp"
    "CiAgICAgICAgICAgICAgICAgICAgc2MuQXJndW1lbnRzICAgICAgID0gZicie2RzdF9kZWNrfSInCiAgICAgICAgICAgICAgICAg"
    "ICAgc2MuV29ya2luZ0RpcmVjdG9yeT0gc3RyKG1vcmdhbm5hX2hvbWUpCiAgICAgICAgICAgICAgICAgICAgc2MuRGVzY3JpcHRp"
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
    "XG4iCiAgICAgICAgICAgIGYie21vcmdhbm5hX2hvbWV9XG5cbiIKICAgICAgICAgICAgZiJ7c2hvcnRjdXRfbm90ZX1cblxuIgog"
    "ICAgICAgICAgICBmIlRoaXMgc2V0dXAgd2luZG93IHdpbGwgbm93IGNsb3NlLlxuIgogICAgICAgICAgICBmIlVzZSB0aGUgc2hv"
    "cnRjdXQgb3IgdGhlIGRlY2sgZmlsZSB0byBsYXVuY2gge0RFQ0tfTkFNRX0uIgogICAgICAgICkKCiAgICAgICAgIyDilIDilIAg"
    "RXhpdCBzZWVkIOKAlCB1c2VyIGxhdW5jaGVzIGZyb20gc2hvcnRjdXQvbmV3IGxvY2F0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgICAgIHN5cy5leGl0KDApCgogICAgIyDilIDilIAgUGhhc2UgNDogTm9ybWFsIGxhdW5jaCDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICMgT25seSByZWFjaGVzIGhlcmUgb24gc3Vic2VxdWVudCBydW5z"
    "IGZyb20gbW9yZ2FubmFfaG9tZQogICAgYm9vdHN0cmFwX3NvdW5kcygpCgogICAgX2Vhcmx5X2xvZyhmIltNQUlOXSBDcmVhdGlu"
    "ZyB7REVDS19OQU1FfSBkZWNrIHdpbmRvdyIpCiAgICB3aW5kb3cgPSBFY2hvRGVjaygpCiAgICBfZWFybHlfbG9nKGYiW01BSU5d"
    "IHtERUNLX05BTUV9IGRlY2sgY3JlYXRlZCDigJQgY2FsbGluZyBzaG93KCkiKQogICAgd2luZG93LnNob3coKQogICAgX2Vhcmx5"
    "X2xvZygiW01BSU5dIHdpbmRvdy5zaG93KCkgY2FsbGVkIOKAlCBldmVudCBsb29wIHN0YXJ0aW5nIikKCiAgICAjIERlZmVyIHNj"
    "aGVkdWxlciBhbmQgc3RhcnR1cCBzZXF1ZW5jZSB1bnRpbCBldmVudCBsb29wIGlzIHJ1bm5pbmcuCiAgICAjIE5vdGhpbmcgdGhh"
    "dCBzdGFydHMgdGhyZWFkcyBvciBlbWl0cyBzaWduYWxzIHNob3VsZCBydW4gYmVmb3JlIHRoaXMuCiAgICBRVGltZXIuc2luZ2xl"
    "U2hvdCgyMDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gX3NldHVwX3NjaGVkdWxlciBmaXJpbmciKSwgd2luZG93Ll9z"
    "ZXR1cF9zY2hlZHVsZXIoKSkpCiAgICBRVGltZXIuc2luZ2xlU2hvdCg0MDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0g"
    "c3RhcnRfc2NoZWR1bGVyIGZpcmluZyIpLCB3aW5kb3cuc3RhcnRfc2NoZWR1bGVyKCkpKQogICAgUVRpbWVyLnNpbmdsZVNob3Qo"
    "NjAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9zdGFydHVwX3NlcXVlbmNlIGZpcmluZyIpLCB3aW5kb3cuX3N0YXJ0"
    "dXBfc2VxdWVuY2UoKSkpCiAgICBRVGltZXIuc2luZ2xlU2hvdCgxMDAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9z"
    "dGFydHVwX2dvb2dsZV9hdXRoIGZpcmluZyIpLCB3aW5kb3cuX3N0YXJ0dXBfZ29vZ2xlX2F1dGgoKSkpCgogICAgIyBQbGF5IHN0"
    "YXJ0dXAgc291bmQg4oCUIGtlZXAgcmVmZXJlbmNlIHRvIHByZXZlbnQgR0Mgd2hpbGUgdGhyZWFkIHJ1bnMKICAgIGRlZiBfcGxh"
    "eV9zdGFydHVwKCk6CiAgICAgICAgd2luZG93Ll9zdGFydHVwX3NvdW5kID0gU291bmRXb3JrZXIoInN0YXJ0dXAiKQogICAgICAg"
    "IHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5maW5pc2hlZC5jb25uZWN0KHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5kZWxldGVMYXRlcikK"
    "ICAgICAgICB3aW5kb3cuX3N0YXJ0dXBfc291bmQuc3RhcnQoKQogICAgUVRpbWVyLnNpbmdsZVNob3QoMTIwMCwgX3BsYXlfc3Rh"
    "cnR1cCkKCiAgICBzeXMuZXhpdChhcHAuZXhlYygpKQoKCmlmIF9fbmFtZV9fID09ICJfX21haW5fXyI6CiAgICBtYWluKCkKCgoj"
    "IOKUgOKUgCBQQVNTIDYgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgRnVsbCBkZWNrIGFzc2VtYmxl"
    "ZC4gQWxsIHBhc3NlcyBjb21wbGV0ZS4KIyBDb21iaW5lIGFsbCBwYXNzZXMgaW50byBtb3JnYW5uYV9kZWNrLnB5IGluIG9yZGVy"
    "OgojICAgUGFzcyAxIOKGkiBQYXNzIDIg4oaSIFBhc3MgMyDihpIgUGFzcyA0IOKGkiBQYXNzIDUg4oaSIFBhc3MgNg=="
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
