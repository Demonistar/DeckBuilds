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
    "IHRvZ2dsZWQgPSBTaWduYWwoYm9vbCkKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbGFiZWw6IHN0ciwgY29udGVudDogUVdpZGdl"
    "dCwKICAgICAgICAgICAgICAgICBleHBhbmRlZDogYm9vbCA9IFRydWUsIG1pbl93aWR0aDogaW50ID0gOTAsCiAgICAgICAgICAg"
    "ICAgICAgcmVzZXJ2ZV93aWR0aDogYm9vbCA9IEZhbHNlLAogICAgICAgICAgICAgICAgIHBhcmVudD1Ob25lKToKICAgICAgICBz"
    "dXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9leHBhbmRlZCAgICAgICA9IGV4cGFuZGVkCiAgICAgICAgc2Vs"
    "Zi5fbWluX3dpZHRoICAgICAgPSBtaW5fd2lkdGgKICAgICAgICBzZWxmLl9yZXNlcnZlX3dpZHRoICA9IHJlc2VydmVfd2lkdGgK"
    "ICAgICAgICBzZWxmLl9jb250ZW50ICAgICAgICA9IGNvbnRlbnQKCiAgICAgICAgbWFpbiA9IFFWQm94TGF5b3V0KHNlbGYpCiAg"
    "ICAgICAgbWFpbi5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBtYWluLnNldFNwYWNpbmcoMCkKCiAgICAg"
    "ICAgIyBIZWFkZXIKICAgICAgICBzZWxmLl9oZWFkZXIgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9oZWFkZXIuc2V0Rml4ZWRI"
    "ZWlnaHQoMjIpCiAgICAgICAgc2VsZi5faGVhZGVyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0Nf"
    "QkczfTsgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImJvcmRlci10b3A6"
    "IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IgogICAgICAgICkKICAgICAgICBobCA9IFFIQm94TGF5b3V0KHNlbGYuX2hlYWRl"
    "cikKICAgICAgICBobC5zZXRDb250ZW50c01hcmdpbnMoNiwgMCwgNCwgMCkKICAgICAgICBobC5zZXRTcGFjaW5nKDQpCgogICAg"
    "ICAgIHNlbGYuX2xibCA9IFFMYWJlbChsYWJlbCkKICAgICAgICBzZWxmLl9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmImZvbnQt"
    "ZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGxldHRlci1zcGFjaW5nOiAxcHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQoK"
    "ICAgICAgICBzZWxmLl9idG4gPSBRVG9vbEJ1dHRvbigpCiAgICAgICAgc2VsZi5fYnRuLnNldEZpeGVkU2l6ZSgxNiwgMTYpCiAg"
    "ICAgICAgc2VsZi5fYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogdHJhbnNwYXJlbnQ7IGNvbG9y"
    "OiB7Q19HT0xEX0RJTX07IGJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYnRu"
    "LnNldFRleHQoIjwiKQogICAgICAgIHNlbGYuX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlKQoKICAgICAgICBobC5h"
    "ZGRXaWRnZXQoc2VsZi5fbGJsKQogICAgICAgIGhsLmFkZFN0cmV0Y2goKQogICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl9idG4p"
    "CgogICAgICAgIG1haW4uYWRkV2lkZ2V0KHNlbGYuX2hlYWRlcikKICAgICAgICBtYWluLmFkZFdpZGdldChzZWxmLl9jb250ZW50"
    "KQoKICAgICAgICBzZWxmLl9hcHBseV9zdGF0ZSgpCgogICAgZGVmIGlzX2V4cGFuZGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAg"
    "cmV0dXJuIHNlbGYuX2V4cGFuZGVkCgogICAgZGVmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRl"
    "ZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAgIHNlbGYuX2FwcGx5X3N0YXRlKCkKICAgICAgICBzZWxmLnRvZ2dsZWQuZW1p"
    "dChzZWxmLl9leHBhbmRlZCkKCiAgICBkZWYgX2FwcGx5X3N0YXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fY29udGVu"
    "dC5zZXRWaXNpYmxlKHNlbGYuX2V4cGFuZGVkKQogICAgICAgIHNlbGYuX2J0bi5zZXRUZXh0KCI8IiBpZiBzZWxmLl9leHBhbmRl"
    "ZCBlbHNlICI+IikKCiAgICAgICAgIyBSZXNlcnZlIGZpeGVkIHNsb3Qgd2lkdGggd2hlbiByZXF1ZXN0ZWQgKHVzZWQgYnkgbWlk"
    "ZGxlIGxvd2VyIGJsb2NrKQogICAgICAgIGlmIHNlbGYuX3Jlc2VydmVfd2lkdGg6CiAgICAgICAgICAgIHNlbGYuc2V0TWluaW11"
    "bVdpZHRoKHNlbGYuX21pbl93aWR0aCkKICAgICAgICAgICAgc2VsZi5zZXRNYXhpbXVtV2lkdGgoMTY3NzcyMTUpCiAgICAgICAg"
    "ZWxpZiBzZWxmLl9leHBhbmRlZDoKICAgICAgICAgICAgc2VsZi5zZXRNaW5pbXVtV2lkdGgoc2VsZi5fbWluX3dpZHRoKQogICAg"
    "ICAgICAgICBzZWxmLnNldE1heGltdW1XaWR0aCgxNjc3NzIxNSkgICMgdW5jb25zdHJhaW5lZAogICAgICAgIGVsc2U6CiAgICAg"
    "ICAgICAgICMgQ29sbGFwc2VkOiBqdXN0IHRoZSBoZWFkZXIgc3RyaXAgKGxhYmVsICsgYnV0dG9uKQogICAgICAgICAgICBjb2xs"
    "YXBzZWRfdyA9IHNlbGYuX2hlYWRlci5zaXplSGludCgpLndpZHRoKCkKICAgICAgICAgICAgc2VsZi5zZXRGaXhlZFdpZHRoKG1h"
    "eCg2MCwgY29sbGFwc2VkX3cpKQoKICAgICAgICBzZWxmLnVwZGF0ZUdlb21ldHJ5KCkKICAgICAgICBwYXJlbnQgPSBzZWxmLnBh"
    "cmVudFdpZGdldCgpCiAgICAgICAgaWYgcGFyZW50IGFuZCBwYXJlbnQubGF5b3V0KCk6CiAgICAgICAgICAgIHBhcmVudC5sYXlv"
    "dXQoKS5hY3RpdmF0ZSgpCgoKIyDilIDilIAgSEFSRFdBUkUgUEFORUwg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNs"
    "YXNzIEhhcmR3YXJlUGFuZWwoUVdpZGdldCk6CiAgICAiIiIKICAgIFRoZSBzeXN0ZW1zIHJpZ2h0IHBhbmVsIGNvbnRlbnRzLgog"
    "ICAgR3JvdXBzOiBzdGF0dXMgaW5mbywgZHJpdmUgYmFycywgQ1BVL1JBTSBnYXVnZXMsIEdQVS9WUkFNIGdhdWdlcywgR1BVIHRl"
    "bXAuCiAgICBSZXBvcnRzIGhhcmR3YXJlIGF2YWlsYWJpbGl0eSBpbiBEaWFnbm9zdGljcyBvbiBzdGFydHVwLgogICAgU2hvd3Mg"
    "Ti9BIGdyYWNlZnVsbHkgd2hlbiBkYXRhIHVuYXZhaWxhYmxlLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVu"
    "dD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAg"
    "c2VsZi5fZGV0ZWN0X2hhcmR3YXJlKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgbGF5b3V0ID0g"
    "UVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgbGF5"
    "b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgZGVmIHNlY3Rpb25fbGFiZWwodGV4dDogc3RyKSAtPiBRTGFiZWw6CiAgICAgICAg"
    "ICAgIGxibCA9IFFMYWJlbCh0ZXh0KQogICAgICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiY29s"
    "b3I6IHtDX0dPTER9OyBmb250LXNpemU6IDlweDsgbGV0dGVyLXNwYWNpbmc6IDJweDsgIgogICAgICAgICAgICAgICAgZiJmb250"
    "LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXdlaWdodDogYm9sZDsiCiAgICAgICAgICAgICkKICAgICAgICAgICAg"
    "cmV0dXJuIGxibAoKICAgICAgICAjIOKUgOKUgCBTdGF0dXMgYmxvY2sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacg"
    "U1RBVFVTIikpCiAgICAgICAgc3RhdHVzX2ZyYW1lID0gUUZyYW1lKCkKICAgICAgICBzdGF0dXNfZnJhbWUuc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19QQU5FTH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRl"
    "ci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQogICAgICAgIHN0YXR1c19mcmFtZS5zZXRGaXhlZEhlaWdodCg4OCkKICAgICAgICBz"
    "ZiA9IFFWQm94TGF5b3V0KHN0YXR1c19mcmFtZSkKICAgICAgICBzZi5zZXRDb250ZW50c01hcmdpbnMoOCwgNCwgOCwgNCkKICAg"
    "ICAgICBzZi5zZXRTcGFjaW5nKDIpCgogICAgICAgIHNlbGYubGJsX3N0YXR1cyAgPSBRTGFiZWwoIuKcpiBTVEFUVVM6IE9GRkxJ"
    "TkUiKQogICAgICAgIHNlbGYubGJsX21vZGVsICAgPSBRTGFiZWwoIuKcpiBWRVNTRUw6IExPQURJTkcuLi4iKQogICAgICAgIHNl"
    "bGYubGJsX3Nlc3Npb24gPSBRTGFiZWwoIuKcpiBTRVNTSU9OOiAwMDowMDowMCIpCiAgICAgICAgc2VsZi5sYmxfdG9rZW5zICA9"
    "IFFMYWJlbCgi4pymIFRPS0VOUzogMCIpCgogICAgICAgIGZvciBsYmwgaW4gKHNlbGYubGJsX3N0YXR1cywgc2VsZi5sYmxfbW9k"
    "ZWwsCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sYmxfc2Vzc2lvbiwgc2VsZi5sYmxfdG9rZW5zKToKICAgICAgICAgICAgbGJs"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgIgog"
    "ICAgICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBib3JkZXI6IG5vbmU7IgogICAgICAgICAg"
    "ICApCiAgICAgICAgICAgIHNmLmFkZFdpZGdldChsYmwpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc3RhdHVzX2ZyYW1lKQoK"
    "ICAgICAgICAjIOKUgOKUgCBEcml2ZSBiYXJzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIFNUT1JBR0Ui"
    "KSkKICAgICAgICBzZWxmLmRyaXZlX3dpZGdldCA9IERyaXZlV2lkZ2V0KCkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYu"
    "ZHJpdmVfd2lkZ2V0KQoKICAgICAgICAjIOKUgOKUgCBDUFUgLyBSQU0gZ2F1Z2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIFZJVEFM"
    "IEVTU0VOQ0UiKSkKICAgICAgICByYW1fY3B1ID0gUUdyaWRMYXlvdXQoKQogICAgICAgIHJhbV9jcHUuc2V0U3BhY2luZygzKQoK"
    "ICAgICAgICBzZWxmLmdhdWdlX2NwdSAgPSBHYXVnZVdpZGdldCgiQ1BVIiwgICIlIiwgICAxMDAuMCwgQ19TSUxWRVIpCiAgICAg"
    "ICAgc2VsZi5nYXVnZV9yYW0gID0gR2F1Z2VXaWRnZXQoIlJBTSIsICAiR0IiLCAgIDY0LjAsIENfR09MRF9ESU0pCiAgICAgICAg"
    "cmFtX2NwdS5hZGRXaWRnZXQoc2VsZi5nYXVnZV9jcHUsIDAsIDApCiAgICAgICAgcmFtX2NwdS5hZGRXaWRnZXQoc2VsZi5nYXVn"
    "ZV9yYW0sIDAsIDEpCiAgICAgICAgbGF5b3V0LmFkZExheW91dChyYW1fY3B1KQoKICAgICAgICAjIOKUgOKUgCBHUFUgLyBWUkFN"
    "IGdhdWdlcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRk"
    "V2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKdpyBBUkNBTkUgUE9XRVIiKSkKICAgICAgICBncHVfdnJhbSA9IFFHcmlkTGF5b3V0KCkK"
    "ICAgICAgICBncHVfdnJhbS5zZXRTcGFjaW5nKDMpCgogICAgICAgIHNlbGYuZ2F1Z2VfZ3B1ICA9IEdhdWdlV2lkZ2V0KCJHUFUi"
    "LCAgIiUiLCAgIDEwMC4wLCBDX1BVUlBMRSkKICAgICAgICBzZWxmLmdhdWdlX3ZyYW0gPSBHYXVnZVdpZGdldCgiVlJBTSIsICJH"
    "QiIsICAgIDguMCwgQ19DUklNU09OKQogICAgICAgIGdwdV92cmFtLmFkZFdpZGdldChzZWxmLmdhdWdlX2dwdSwgIDAsIDApCiAg"
    "ICAgICAgZ3B1X3ZyYW0uYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfdnJhbSwgMCwgMSkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGdw"
    "dV92cmFtKQoKICAgICAgICAjIOKUgOKUgCBHUFUgVGVtcCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwo"
    "IuKdpyBJTkZFUk5BTCBIRUFUIikpCiAgICAgICAgc2VsZi5nYXVnZV90ZW1wID0gR2F1Z2VXaWRnZXQoIkdQVSBURU1QIiwgIsKw"
    "QyIsIDk1LjAsIENfQkxPT0QpCiAgICAgICAgc2VsZi5nYXVnZV90ZW1wLnNldE1heGltdW1IZWlnaHQoNjUpCiAgICAgICAgbGF5"
    "b3V0LmFkZFdpZGdldChzZWxmLmdhdWdlX3RlbXApCgogICAgICAgICMg4pSA4pSAIEdQVSBtYXN0ZXIgYmFyIChmdWxsIHdpZHRo"
    "KSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKdpyBJTkZFUk5BTCBF"
    "TkdJTkUiKSkKICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIgPSBHYXVnZVdpZGdldCgiUlRYIiwgIiUiLCAxMDAuMCwgQ19D"
    "UklNU09OKQogICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3Rlci5zZXRNYXhpbXVtSGVpZ2h0KDU1KQogICAgICAgIGxheW91dC5h"
    "ZGRXaWRnZXQoc2VsZi5nYXVnZV9ncHVfbWFzdGVyKQoKICAgICAgICBsYXlvdXQuYWRkU3RyZXRjaCgpCgogICAgZGVmIF9kZXRl"
    "Y3RfaGFyZHdhcmUoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBDaGVjayB3aGF0IGhhcmR3YXJlIG1vbml0b3Jp"
    "bmcgaXMgYXZhaWxhYmxlLgogICAgICAgIE1hcmsgdW5hdmFpbGFibGUgZ2F1Z2VzIGFwcHJvcHJpYXRlbHkuCiAgICAgICAgRGlh"
    "Z25vc3RpYyBtZXNzYWdlcyBjb2xsZWN0ZWQgZm9yIHRoZSBEaWFnbm9zdGljcyB0YWIuCiAgICAgICAgIiIiCiAgICAgICAgc2Vs"
    "Zi5fZGlhZ19tZXNzYWdlczogbGlzdFtzdHJdID0gW10KCiAgICAgICAgaWYgbm90IFBTVVRJTF9PSzoKICAgICAgICAgICAgc2Vs"
    "Zi5nYXVnZV9jcHUuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX3JhbS5zZXRVbmF2YWlsYWJsZSgpCiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKAogICAgICAgICAgICAgICAgIltIQVJEV0FSRV0gcHN1dGlsIG5v"
    "dCBhdmFpbGFibGUg4oCUIENQVS9SQU0gZ2F1Z2VzIGRpc2FibGVkLiAiCiAgICAgICAgICAgICAgICAicGlwIGluc3RhbGwgcHN1"
    "dGlsIHRvIGVuYWJsZS4iCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2Vz"
    "LmFwcGVuZCgiW0hBUkRXQVJFXSBwc3V0aWwgT0sg4oCUIENQVS9SQU0gbW9uaXRvcmluZyBhY3RpdmUuIikKCiAgICAgICAgaWYg"
    "bm90IE5WTUxfT0s6CiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1LnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5n"
    "YXVnZV92cmFtLnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5nYXVnZV90ZW1wLnNldFVuYXZhaWxhYmxlKCkKICAg"
    "ICAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNz"
    "YWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAiW0hBUkRXQVJFXSBweW52bWwgbm90IGF2YWlsYWJsZSBvciBubyBOVklESUEg"
    "R1BVIGRldGVjdGVkIOKAlCAiCiAgICAgICAgICAgICAgICAiR1BVIGdhdWdlcyBkaXNhYmxlZC4gcGlwIGluc3RhbGwgcHludm1s"
    "IHRvIGVuYWJsZS4iCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBu"
    "YW1lID0gcHludm1sLm52bWxEZXZpY2VHZXROYW1lKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICBpZiBpc2luc3RhbmNlKG5h"
    "bWUsIGJ5dGVzKToKICAgICAgICAgICAgICAgICAgICBuYW1lID0gbmFtZS5kZWNvZGUoKQogICAgICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ19tZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgZiJbSEFSRFdBUkVdIHB5bnZtbCBPSyDigJQgR1BVIGRl"
    "dGVjdGVkOiB7bmFtZX0iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAjIFVwZGF0ZSBtYXggVlJBTSBmcm9tIGFj"
    "dHVhbCBoYXJkd2FyZQogICAgICAgICAgICAgICAgbWVtID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5k"
    "bGUpCiAgICAgICAgICAgICAgICB0b3RhbF9nYiA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHNlbGYuZ2F1"
    "Z2VfdnJhbS5tYXhfdmFsID0gdG90YWxfZ2IKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAg"
    "ICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoZiJbSEFSRFdBUkVdIHB5bnZtbCBlcnJvcjoge2V9IikKCiAgICBkZWYgdXBk"
    "YXRlX3N0YXRzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIGV2ZXJ5IHNlY29uZCBmcm9tIHRoZSBz"
    "dGF0cyBRVGltZXIuCiAgICAgICAgUmVhZHMgaGFyZHdhcmUgYW5kIHVwZGF0ZXMgYWxsIGdhdWdlcy4KICAgICAgICAiIiIKICAg"
    "ICAgICBpZiBQU1VUSUxfT0s6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNwdSA9IHBzdXRpbC5jcHVfcGVyY2Vu"
    "dCgpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX2NwdS5zZXRWYWx1ZShjcHUsIGYie2NwdTouMGZ9JSIsIGF2YWlsYWJsZT1U"
    "cnVlKQoKICAgICAgICAgICAgICAgIG1lbSA9IHBzdXRpbC52aXJ0dWFsX21lbW9yeSgpCiAgICAgICAgICAgICAgICBydSAgPSBt"
    "ZW0udXNlZCAgLyAxMDI0KiozCiAgICAgICAgICAgICAgICBydCAgPSBtZW0udG90YWwgLyAxMDI0KiozCiAgICAgICAgICAgICAg"
    "ICBzZWxmLmdhdWdlX3JhbS5zZXRWYWx1ZShydSwgZiJ7cnU6LjFmfS97cnQ6LjBmfUdCIiwKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9yYW0ubWF4X3ZhbCA9"
    "IHJ0CiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgIGlmIE5WTUxfT0sg"
    "YW5kIGdwdV9oYW5kbGU6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHV0aWwgICAgID0gcHludm1sLm52bWxEZXZp"
    "Y2VHZXRVdGlsaXphdGlvblJhdGVzKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICBtZW1faW5mbyA9IHB5bnZtbC5udm1sRGV2"
    "aWNlR2V0TWVtb3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgdGVtcCAgICAgPSBweW52bWwubnZtbERldmljZUdl"
    "dFRlbXBlcmF0dXJlKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZ3B1X2hhbmRsZSwgcHludm1sLk5WTUxfVEVNUEVS"
    "QVRVUkVfR1BVKQoKICAgICAgICAgICAgICAgIGdwdV9wY3QgICA9IGZsb2F0KHV0aWwuZ3B1KQogICAgICAgICAgICAgICAgdnJh"
    "bV91c2VkID0gbWVtX2luZm8udXNlZCAgLyAxMDI0KiozCiAgICAgICAgICAgICAgICB2cmFtX3RvdCAgPSBtZW1faW5mby50b3Rh"
    "bCAvIDEwMjQqKjMKCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX2dwdS5zZXRWYWx1ZShncHVfcGN0LCBmIntncHVfcGN0Oi4w"
    "Zn0lIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAg"
    "ICAgc2VsZi5nYXVnZV92cmFtLnNldFZhbHVlKHZyYW1fdXNlZCwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICBmInt2cmFtX3VzZWQ6LjFmfS97dnJhbV90b3Q6LjBmfUdCIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICBhdmFpbGFibGU9VHJ1ZSkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfdGVtcC5zZXRWYWx1ZShmbG9hdCh0ZW1w"
    "KSwgZiJ7dGVtcH3CsEMiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQoK"
    "ICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBuYW1lID0gcHludm1sLm52bWxEZXZpY2VHZXROYW1lKGdw"
    "dV9oYW5kbGUpCiAgICAgICAgICAgICAgICAgICAgaWYgaXNpbnN0YW5jZShuYW1lLCBieXRlcyk6CiAgICAgICAgICAgICAgICAg"
    "ICAgICAgIG5hbWUgPSBuYW1lLmRlY29kZSgpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAg"
    "ICAgICAgIG5hbWUgPSAiR1BVIgoKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3Rlci5zZXRWYWx1ZSgKICAgICAg"
    "ICAgICAgICAgICAgICBncHVfcGN0LAogICAgICAgICAgICAgICAgICAgIGYie25hbWV9ICB7Z3B1X3BjdDouMGZ9JSAgIgogICAg"
    "ICAgICAgICAgICAgICAgIGYiW3t2cmFtX3VzZWQ6LjFmfS97dnJhbV90b3Q6LjBmfUdCIFZSQU1dIiwKICAgICAgICAgICAgICAg"
    "ICAgICBhdmFpbGFibGU9VHJ1ZSwKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAg"
    "ICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBVcGRhdGUgZHJpdmUgYmFycyBldmVyeSAzMCBzZWNvbmRzIChub3QgZXZlcnkgdGlj"
    "aykKICAgICAgICBpZiBub3QgaGFzYXR0cihzZWxmLCAiX2RyaXZlX3RpY2siKToKICAgICAgICAgICAgc2VsZi5fZHJpdmVfdGlj"
    "ayA9IDAKICAgICAgICBzZWxmLl9kcml2ZV90aWNrICs9IDEKICAgICAgICBpZiBzZWxmLl9kcml2ZV90aWNrID49IDMwOgogICAg"
    "ICAgICAgICBzZWxmLl9kcml2ZV90aWNrID0gMAogICAgICAgICAgICBzZWxmLmRyaXZlX3dpZGdldC5yZWZyZXNoKCkKCiAgICBk"
    "ZWYgc2V0X3N0YXR1c19sYWJlbHMoc2VsZiwgc3RhdHVzOiBzdHIsIG1vZGVsOiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgc2Vzc2lvbjogc3RyLCB0b2tlbnM6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLmxibF9zdGF0dXMuc2V0VGV4dChmIuKc"
    "piBTVEFUVVM6IHtzdGF0dXN9IikKICAgICAgICBzZWxmLmxibF9tb2RlbC5zZXRUZXh0KGYi4pymIFZFU1NFTDoge21vZGVsfSIp"
    "CiAgICAgICAgc2VsZi5sYmxfc2Vzc2lvbi5zZXRUZXh0KGYi4pymIFNFU1NJT046IHtzZXNzaW9ufSIpCiAgICAgICAgc2VsZi5s"
    "YmxfdG9rZW5zLnNldFRleHQoZiLinKYgVE9LRU5TOiB7dG9rZW5zfSIpCgogICAgZGVmIGdldF9kaWFnbm9zdGljcyhzZWxmKSAt"
    "PiBsaXN0W3N0cl06CiAgICAgICAgcmV0dXJuIGdldGF0dHIoc2VsZiwgIl9kaWFnX21lc3NhZ2VzIiwgW10pCgoKIyDilIDilIAg"
    "UEFTUyAyIENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEFsbCB3aWRnZXQgY2xhc3NlcyBkZWZpbmVk"
    "LiBTeW50YXgtY2hlY2thYmxlIGluZGVwZW5kZW50bHkuCiMgTmV4dDogUGFzcyAzIOKAlCBXb3JrZXIgVGhyZWFkcwojIChEb2xw"
    "aGluV29ya2VyIHdpdGggc3RyZWFtaW5nLCBTZW50aW1lbnRXb3JrZXIsIElkbGVXb3JrZXIsIFNvdW5kV29ya2VyKQoKCiMg4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyAzOiBXT1JLRVIgVEhSRUFEUwojCiMgV29ya2VycyBkZWZpbmVkIGhl"
    "cmU6CiMgICBMTE1BZGFwdG9yIChiYXNlICsgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yICsgT2xsYW1hQWRhcHRvciArCiMgICAg"
    "ICAgICAgICAgICBDbGF1ZGVBZGFwdG9yICsgT3BlbkFJQWRhcHRvcikKIyAgIFN0cmVhbWluZ1dvcmtlciAgIOKAlCBtYWluIGdl"
    "bmVyYXRpb24sIGVtaXRzIHRva2VucyBvbmUgYXQgYSB0aW1lCiMgICBTZW50aW1lbnRXb3JrZXIgICDigJQgY2xhc3NpZmllcyBl"
    "bW90aW9uIGZyb20gcmVzcG9uc2UgdGV4dAojICAgSWRsZVdvcmtlciAgICAgICAg4oCUIHVuc29saWNpdGVkIHRyYW5zbWlzc2lv"
    "bnMgZHVyaW5nIGlkbGUKIyAgIFNvdW5kV29ya2VyICAgICAgIOKAlCBwbGF5cyBzb3VuZHMgb2ZmIHRoZSBtYWluIHRocmVhZAoj"
    "CiMgQUxMIGdlbmVyYXRpb24gaXMgc3RyZWFtaW5nLiBObyBibG9ja2luZyBjYWxscyBvbiBtYWluIHRocmVhZC4gRXZlci4KIyDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZAKCmltcG9ydCBhYmMKaW1wb3J0IGpzb24KaW1wb3J0IHVybGxpYi5yZXF1ZXN0CmltcG9ydCB1cmxsaWIuZXJy"
    "b3IKaW1wb3J0IGh0dHAuY2xpZW50CmZyb20gdHlwaW5nIGltcG9ydCBJdGVyYXRvcgoKCiMg4pSA4pSAIExMTSBBREFQVE9SIEJB"
    "U0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIExMTUFkYXB0b3IoYWJjLkFCQyk6CiAgICAiIiIKICAgIEFic3RyYWN0IGJh"
    "c2UgZm9yIGFsbCBtb2RlbCBiYWNrZW5kcy4KICAgIFRoZSBkZWNrIGNhbGxzIHN0cmVhbSgpIG9yIGdlbmVyYXRlKCkg4oCUIG5l"
    "dmVyIGtub3dzIHdoaWNoIGJhY2tlbmQgaXMgYWN0aXZlLgogICAgIiIiCgogICAgQGFiYy5hYnN0cmFjdG1ldGhvZAogICAgZGVm"
    "IGlzX2Nvbm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgICIiIlJldHVybiBUcnVlIGlmIHRoZSBiYWNrZW5kIGlzIHJlYWNo"
    "YWJsZS4iIiIKICAgICAgICAuLi4KCiAgICBAYWJjLmFic3RyYWN0bWV0aG9kCiAgICBkZWYgc3RyZWFtKAogICAgICAgIHNlbGYs"
    "CiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAg"
    "ICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVyYXRvcltzdHJdOgogICAgICAgICIiIgogICAgICAg"
    "IFlpZWxkIHJlc3BvbnNlIHRleHQgdG9rZW4tYnktdG9rZW4gKG9yIGNodW5rLWJ5LWNodW5rIGZvciBBUEkgYmFja2VuZHMpLgog"
    "ICAgICAgIE11c3QgYmUgYSBnZW5lcmF0b3IuIE5ldmVyIGJsb2NrIGZvciB0aGUgZnVsbCByZXNwb25zZSBiZWZvcmUgeWllbGRp"
    "bmcuCiAgICAgICAgIiIiCiAgICAgICAgLi4uCgogICAgZGVmIGdlbmVyYXRlKAogICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0"
    "OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtYXhfbmV3X3Rv"
    "a2VuczogaW50ID0gNTEyLAogICAgKSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgQ29udmVuaWVuY2Ugd3JhcHBlcjogY29s"
    "bGVjdCBhbGwgc3RyZWFtIHRva2VucyBpbnRvIG9uZSBzdHJpbmcuCiAgICAgICAgVXNlZCBmb3Igc2VudGltZW50IGNsYXNzaWZp"
    "Y2F0aW9uIChzbWFsbCBib3VuZGVkIGNhbGxzIG9ubHkpLgogICAgICAgICIiIgogICAgICAgIHJldHVybiAiIi5qb2luKHNlbGYu"
    "c3RyZWFtKHByb21wdCwgc3lzdGVtLCBoaXN0b3J5LCBtYXhfbmV3X3Rva2VucykpCgogICAgZGVmIGJ1aWxkX2NoYXRtbF9wcm9t"
    "cHQoc2VsZiwgc3lzdGVtOiBzdHIsIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgdXNl"
    "cl90ZXh0OiBzdHIgPSAiIikgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIEJ1aWxkIGEgQ2hhdE1MLWZvcm1hdCBwcm9tcHQg"
    "c3RyaW5nIGZvciBsb2NhbCBtb2RlbHMuCiAgICAgICAgaGlzdG9yeSA9IFt7InJvbGUiOiAidXNlciJ8ImFzc2lzdGFudCIsICJj"
    "b250ZW50IjogIi4uLiJ9XQogICAgICAgICIiIgogICAgICAgIHBhcnRzID0gW2YiPHxpbV9zdGFydHw+c3lzdGVtXG57c3lzdGVt"
    "fTx8aW1fZW5kfD4iXQogICAgICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAgICAgICAgcm9sZSAgICA9IG1zZy5nZXQoInJv"
    "bGUiLCAidXNlciIpCiAgICAgICAgICAgIGNvbnRlbnQgPSBtc2cuZ2V0KCJjb250ZW50IiwgIiIpCiAgICAgICAgICAgIHBhcnRz"
    "LmFwcGVuZChmIjx8aW1fc3RhcnR8Pntyb2xlfVxue2NvbnRlbnR9PHxpbV9lbmR8PiIpCiAgICAgICAgaWYgdXNlcl90ZXh0Ogog"
    "ICAgICAgICAgICBwYXJ0cy5hcHBlbmQoZiI8fGltX3N0YXJ0fD51c2VyXG57dXNlcl90ZXh0fTx8aW1fZW5kfD4iKQogICAgICAg"
    "IHBhcnRzLmFwcGVuZCgiPHxpbV9zdGFydHw+YXNzaXN0YW50XG4iKQogICAgICAgIHJldHVybiAiXG4iLmpvaW4ocGFydHMpCgoK"
    "IyDilIDilIAgTE9DQUwgVFJBTlNGT1JNRVJTIEFEQVBUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcihMTE1BZGFwdG9yKToK"
    "ICAgICIiIgogICAgTG9hZHMgYSBIdWdnaW5nRmFjZSBtb2RlbCBmcm9tIGEgbG9jYWwgZm9sZGVyLgogICAgU3RyZWFtaW5nOiB1"
    "c2VzIG1vZGVsLmdlbmVyYXRlKCkgd2l0aCBhIGN1c3RvbSBzdHJlYW1lciB0aGF0IHlpZWxkcyB0b2tlbnMuCiAgICBSZXF1aXJl"
    "czogdG9yY2gsIHRyYW5zZm9ybWVycwogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1vZGVsX3BhdGg6IHN0cik6CiAg"
    "ICAgICAgc2VsZi5fcGF0aCAgICAgID0gbW9kZWxfcGF0aAogICAgICAgIHNlbGYuX21vZGVsICAgICA9IE5vbmUKICAgICAgICBz"
    "ZWxmLl90b2tlbml6ZXIgPSBOb25lCiAgICAgICAgc2VsZi5fbG9hZGVkICAgID0gRmFsc2UKICAgICAgICBzZWxmLl9lcnJvciAg"
    "ICAgPSAiIgoKICAgIGRlZiBsb2FkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgIiIiCiAgICAgICAgTG9hZCBtb2RlbCBhbmQgdG9r"
    "ZW5pemVyLiBDYWxsIGZyb20gYSBiYWNrZ3JvdW5kIHRocmVhZC4KICAgICAgICBSZXR1cm5zIFRydWUgb24gc3VjY2Vzcy4KICAg"
    "ICAgICAiIiIKICAgICAgICBpZiBub3QgVE9SQ0hfT0s6CiAgICAgICAgICAgIHNlbGYuX2Vycm9yID0gInRvcmNoL3RyYW5zZm9y"
    "bWVycyBub3QgaW5zdGFsbGVkIgogICAgICAgICAgICByZXR1cm4gRmFsc2UKICAgICAgICB0cnk6CiAgICAgICAgICAgIGZyb20g"
    "dHJhbnNmb3JtZXJzIGltcG9ydCBBdXRvTW9kZWxGb3JDYXVzYWxMTSwgQXV0b1Rva2VuaXplcgogICAgICAgICAgICBzZWxmLl90"
    "b2tlbml6ZXIgPSBBdXRvVG9rZW5pemVyLmZyb21fcHJldHJhaW5lZChzZWxmLl9wYXRoKQogICAgICAgICAgICBzZWxmLl9tb2Rl"
    "bCA9IEF1dG9Nb2RlbEZvckNhdXNhbExNLmZyb21fcHJldHJhaW5lZCgKICAgICAgICAgICAgICAgIHNlbGYuX3BhdGgsCiAgICAg"
    "ICAgICAgICAgICB0b3JjaF9kdHlwZT10b3JjaC5mbG9hdDE2LAogICAgICAgICAgICAgICAgZGV2aWNlX21hcD0iYXV0byIsCiAg"
    "ICAgICAgICAgICAgICBsb3dfY3B1X21lbV91c2FnZT1UcnVlLAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2xvYWRl"
    "ZCA9IFRydWUKICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAg"
    "IHNlbGYuX2Vycm9yID0gc3RyKGUpCiAgICAgICAgICAgIHJldHVybiBGYWxzZQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGVycm9y"
    "KHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4gc2VsZi5fZXJyb3IKCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJv"
    "b2w6CiAgICAgICAgcmV0dXJuIHNlbGYuX2xvYWRlZAoKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9t"
    "cHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdf"
    "dG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgIiIiCiAgICAgICAgU3RyZWFtcyB0b2tl"
    "bnMgdXNpbmcgdHJhbnNmb3JtZXJzIFRleHRJdGVyYXRvclN0cmVhbWVyLgogICAgICAgIFlpZWxkcyBkZWNvZGVkIHRleHQgZnJh"
    "Z21lbnRzIGFzIHRoZXkgYXJlIGdlbmVyYXRlZC4KICAgICAgICAiIiIKICAgICAgICBpZiBub3Qgc2VsZi5fbG9hZGVkOgogICAg"
    "ICAgICAgICB5aWVsZCAiW0VSUk9SOiBtb2RlbCBub3QgbG9hZGVkXSIKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgZnJvbSB0cmFuc2Zvcm1lcnMgaW1wb3J0IFRleHRJdGVyYXRvclN0cmVhbWVyCgogICAgICAgICAgICBmdWxs"
    "X3Byb21wdCA9IHNlbGYuYnVpbGRfY2hhdG1sX3Byb21wdChzeXN0ZW0sIGhpc3RvcnkpCiAgICAgICAgICAgIGlmIHByb21wdDoK"
    "ICAgICAgICAgICAgICAgICMgcHJvbXB0IGFscmVhZHkgaW5jbHVkZXMgdXNlciB0dXJuIGlmIGNhbGxlciBidWlsdCBpdAogICAg"
    "ICAgICAgICAgICAgZnVsbF9wcm9tcHQgPSBwcm9tcHQKCiAgICAgICAgICAgIGlucHV0X2lkcyA9IHNlbGYuX3Rva2VuaXplcigK"
    "ICAgICAgICAgICAgICAgIGZ1bGxfcHJvbXB0LCByZXR1cm5fdGVuc29ycz0icHQiCiAgICAgICAgICAgICkuaW5wdXRfaWRzLnRv"
    "KCJjdWRhIikKCiAgICAgICAgICAgIGF0dGVudGlvbl9tYXNrID0gKGlucHV0X2lkcyAhPSBzZWxmLl90b2tlbml6ZXIucGFkX3Rv"
    "a2VuX2lkKS5sb25nKCkKCiAgICAgICAgICAgIHN0cmVhbWVyID0gVGV4dEl0ZXJhdG9yU3RyZWFtZXIoCiAgICAgICAgICAgICAg"
    "ICBzZWxmLl90b2tlbml6ZXIsCiAgICAgICAgICAgICAgICBza2lwX3Byb21wdD1UcnVlLAogICAgICAgICAgICAgICAgc2tpcF9z"
    "cGVjaWFsX3Rva2Vucz1UcnVlLAogICAgICAgICAgICApCgogICAgICAgICAgICBnZW5fa3dhcmdzID0gewogICAgICAgICAgICAg"
    "ICAgImlucHV0X2lkcyI6ICAgICAgaW5wdXRfaWRzLAogICAgICAgICAgICAgICAgImF0dGVudGlvbl9tYXNrIjogYXR0ZW50aW9u"
    "X21hc2ssCiAgICAgICAgICAgICAgICAibWF4X25ld190b2tlbnMiOiBtYXhfbmV3X3Rva2VucywKICAgICAgICAgICAgICAgICJ0"
    "ZW1wZXJhdHVyZSI6ICAgIDAuNywKICAgICAgICAgICAgICAgICJkb19zYW1wbGUiOiAgICAgIFRydWUsCiAgICAgICAgICAgICAg"
    "ICAicGFkX3Rva2VuX2lkIjogICBzZWxmLl90b2tlbml6ZXIuZW9zX3Rva2VuX2lkLAogICAgICAgICAgICAgICAgInN0cmVhbWVy"
    "IjogICAgICAgc3RyZWFtZXIsCiAgICAgICAgICAgIH0KCiAgICAgICAgICAgICMgUnVuIGdlbmVyYXRpb24gaW4gYSBkYWVtb24g"
    "dGhyZWFkIOKAlCBzdHJlYW1lciB5aWVsZHMgaGVyZQogICAgICAgICAgICBnZW5fdGhyZWFkID0gdGhyZWFkaW5nLlRocmVhZCgK"
    "ICAgICAgICAgICAgICAgIHRhcmdldD1zZWxmLl9tb2RlbC5nZW5lcmF0ZSwKICAgICAgICAgICAgICAgIGt3YXJncz1nZW5fa3dh"
    "cmdzLAogICAgICAgICAgICAgICAgZGFlbW9uPVRydWUsCiAgICAgICAgICAgICkKICAgICAgICAgICAgZ2VuX3RocmVhZC5zdGFy"
    "dCgpCgogICAgICAgICAgICBmb3IgdG9rZW5fdGV4dCBpbiBzdHJlYW1lcjoKICAgICAgICAgICAgICAgIHlpZWxkIHRva2VuX3Rl"
    "eHQKCiAgICAgICAgICAgIGdlbl90aHJlYWQuam9pbih0aW1lb3V0PTEyMCkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBl"
    "OgogICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiB7ZX1dIgoKCiMg4pSA4pSAIE9MTEFNQSBBREFQVE9SIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBPbGxhbWFBZGFwdG9yKExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBDb25uZWN0cyB0"
    "byBhIGxvY2FsbHkgcnVubmluZyBPbGxhbWEgaW5zdGFuY2UuCiAgICBTdHJlYW1pbmc6IHJlYWRzIE5ESlNPTiByZXNwb25zZSBj"
    "aHVua3MgZnJvbSBPbGxhbWEncyAvYXBpL2dlbmVyYXRlIGVuZHBvaW50LgogICAgT2xsYW1hIG11c3QgYmUgcnVubmluZyBhcyBh"
    "IHNlcnZpY2Ugb24gbG9jYWxob3N0OjExNDM0LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1vZGVsX25hbWU6IHN0"
    "ciwgaG9zdDogc3RyID0gImxvY2FsaG9zdCIsIHBvcnQ6IGludCA9IDExNDM0KToKICAgICAgICBzZWxmLl9tb2RlbCA9IG1vZGVs"
    "X25hbWUKICAgICAgICBzZWxmLl9iYXNlICA9IGYiaHR0cDovL3tob3N0fTp7cG9ydH0iCgogICAgZGVmIGlzX2Nvbm5lY3RlZChz"
    "ZWxmKSAtPiBib29sOgogICAgICAgIHRyeToKICAgICAgICAgICAgcmVxICA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QoZiJ7c2Vs"
    "Zi5fYmFzZX0vYXBpL3RhZ3MiKQogICAgICAgICAgICByZXNwID0gdXJsbGliLnJlcXVlc3QudXJsb3BlbihyZXEsIHRpbWVvdXQ9"
    "MykKICAgICAgICAgICAgcmV0dXJuIHJlc3Auc3RhdHVzID09IDIwMAogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAg"
    "ICAgIHJldHVybiBGYWxzZQoKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAg"
    "ICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1"
    "MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgIiIiCiAgICAgICAgUG9zdHMgdG8gL2FwaS9jaGF0IHdpdGggc3Ry"
    "ZWFtPVRydWUuCiAgICAgICAgT2xsYW1hIHJldHVybnMgTkRKU09OIOKAlCBvbmUgSlNPTiBvYmplY3QgcGVyIGxpbmUuCiAgICAg"
    "ICAgWWllbGRzIHRoZSAnY29udGVudCcgZmllbGQgb2YgZWFjaCBhc3Npc3RhbnQgbWVzc2FnZSBjaHVuay4KICAgICAgICAiIiIK"
    "ICAgICAgICBtZXNzYWdlcyA9IFt7InJvbGUiOiAic3lzdGVtIiwgImNvbnRlbnQiOiBzeXN0ZW19XQogICAgICAgIGZvciBtc2cg"
    "aW4gaGlzdG9yeToKICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKG1zZykKCiAgICAgICAgcGF5bG9hZCA9IGpzb24uZHVtcHMo"
    "ewogICAgICAgICAgICAibW9kZWwiOiAgICBzZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1lc3NhZ2VzIjogbWVzc2FnZXMsCiAg"
    "ICAgICAgICAgICJzdHJlYW0iOiAgIFRydWUsCiAgICAgICAgICAgICJvcHRpb25zIjogIHsibnVtX3ByZWRpY3QiOiBtYXhfbmV3"
    "X3Rva2VucywgInRlbXBlcmF0dXJlIjogMC43fSwKICAgICAgICB9KS5lbmNvZGUoInV0Zi04IikKCiAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICByZXEgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KAogICAgICAgICAgICAgICAgZiJ7c2VsZi5fYmFzZX0vYXBpL2No"
    "YXQiLAogICAgICAgICAgICAgICAgZGF0YT1wYXlsb2FkLAogICAgICAgICAgICAgICAgaGVhZGVycz17IkNvbnRlbnQtVHlwZSI6"
    "ICJhcHBsaWNhdGlvbi9qc29uIn0sCiAgICAgICAgICAgICAgICBtZXRob2Q9IlBPU1QiLAogICAgICAgICAgICApCiAgICAgICAg"
    "ICAgIHdpdGggdXJsbGliLnJlcXVlc3QudXJsb3BlbihyZXEsIHRpbWVvdXQ9MTIwKSBhcyByZXNwOgogICAgICAgICAgICAgICAg"
    "Zm9yIHJhd19saW5lIGluIHJlc3A6CiAgICAgICAgICAgICAgICAgICAgbGluZSA9IHJhd19saW5lLmRlY29kZSgidXRmLTgiKS5z"
    "dHJpcCgpCiAgICAgICAgICAgICAgICAgICAgaWYgbm90IGxpbmU6CiAgICAgICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAg"
    "ICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICBvYmogPSBqc29uLmxvYWRzKGxpbmUpCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGNodW5rID0gb2JqLmdldCgibWVzc2FnZSIsIHt9KS5nZXQoImNvbnRlbnQiLCAiIikKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgaWYgY2h1bms6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICB5aWVsZCBjaHVuawogICAgICAg"
    "ICAgICAgICAgICAgICAgICBpZiBvYmouZ2V0KCJkb25lIiwgRmFsc2UpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgYnJl"
    "YWsKICAgICAgICAgICAgICAgICAgICBleGNlcHQganNvbi5KU09ORGVjb2RlRXJyb3I6CiAgICAgICAgICAgICAgICAgICAgICAg"
    "IGNvbnRpbnVlCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBPbGxh"
    "bWEg4oCUIHtlfV0iCgoKIyDilIDilIAgQ0xBVURFIEFEQVBUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNz"
    "IENsYXVkZUFkYXB0b3IoTExNQWRhcHRvcik6CiAgICAiIiIKICAgIFN0cmVhbXMgZnJvbSBBbnRocm9waWMncyBDbGF1ZGUgQVBJ"
    "IHVzaW5nIFNTRSAoc2VydmVyLXNlbnQgZXZlbnRzKS4KICAgIFJlcXVpcmVzIGFuIEFQSSBrZXkgaW4gY29uZmlnLgogICAgIiIi"
    "CgogICAgX0FQSV9VUkwgPSAiYXBpLmFudGhyb3BpYy5jb20iCiAgICBfUEFUSCAgICA9ICIvdjEvbWVzc2FnZXMiCgogICAgZGVm"
    "IF9faW5pdF9fKHNlbGYsIGFwaV9rZXk6IHN0ciwgbW9kZWw6IHN0ciA9ICJjbGF1ZGUtc29ubmV0LTQtNiIpOgogICAgICAgIHNl"
    "bGYuX2tleSAgID0gYXBpX2tleQogICAgICAgIHNlbGYuX21vZGVsID0gbW9kZWwKCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYp"
    "IC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIGJvb2woc2VsZi5fa2V5KQoKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAg"
    "ICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAg"
    "IG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgbWVzc2FnZXMgPSBbXQog"
    "ICAgICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKHsKICAgICAgICAgICAgICAgICJy"
    "b2xlIjogICAgbXNnWyJyb2xlIl0sCiAgICAgICAgICAgICAgICAiY29udGVudCI6IG1zZ1siY29udGVudCJdLAogICAgICAgICAg"
    "ICB9KQoKICAgICAgICBwYXlsb2FkID0ganNvbi5kdW1wcyh7CiAgICAgICAgICAgICJtb2RlbCI6ICAgICAgc2VsZi5fbW9kZWws"
    "CiAgICAgICAgICAgICJtYXhfdG9rZW5zIjogbWF4X25ld190b2tlbnMsCiAgICAgICAgICAgICJzeXN0ZW0iOiAgICAgc3lzdGVt"
    "LAogICAgICAgICAgICAibWVzc2FnZXMiOiAgIG1lc3NhZ2VzLAogICAgICAgICAgICAic3RyZWFtIjogICAgIFRydWUsCiAgICAg"
    "ICAgfSkuZW5jb2RlKCJ1dGYtOCIpCgogICAgICAgIGhlYWRlcnMgPSB7CiAgICAgICAgICAgICJ4LWFwaS1rZXkiOiAgICAgICAg"
    "IHNlbGYuX2tleSwKICAgICAgICAgICAgImFudGhyb3BpYy12ZXJzaW9uIjogIjIwMjMtMDYtMDEiLAogICAgICAgICAgICAiY29u"
    "dGVudC10eXBlIjogICAgICAiYXBwbGljYXRpb24vanNvbiIsCiAgICAgICAgfQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGNv"
    "bm4gPSBodHRwLmNsaWVudC5IVFRQU0Nvbm5lY3Rpb24oc2VsZi5fQVBJX1VSTCwgdGltZW91dD0xMjApCiAgICAgICAgICAgIGNv"
    "bm4ucmVxdWVzdCgiUE9TVCIsIHNlbGYuX1BBVEgsIGJvZHk9cGF5bG9hZCwgaGVhZGVycz1oZWFkZXJzKQogICAgICAgICAgICBy"
    "ZXNwID0gY29ubi5nZXRyZXNwb25zZSgpCgogICAgICAgICAgICBpZiByZXNwLnN0YXR1cyAhPSAyMDA6CiAgICAgICAgICAgICAg"
    "ICBib2R5ID0gcmVzcC5yZWFkKCkuZGVjb2RlKCJ1dGYtOCIpCiAgICAgICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBDbGF1"
    "ZGUgQVBJIHtyZXNwLnN0YXR1c30g4oCUIHtib2R5WzoyMDBdfV0iCiAgICAgICAgICAgICAgICByZXR1cm4KCiAgICAgICAgICAg"
    "IGJ1ZmZlciA9ICIiCiAgICAgICAgICAgIHdoaWxlIFRydWU6CiAgICAgICAgICAgICAgICBjaHVuayA9IHJlc3AucmVhZCgyNTYp"
    "CiAgICAgICAgICAgICAgICBpZiBub3QgY2h1bms6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgICAgIGJ1"
    "ZmZlciArPSBjaHVuay5kZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHdoaWxlICJcbiIgaW4gYnVmZmVyOgogICAgICAg"
    "ICAgICAgICAgICAgIGxpbmUsIGJ1ZmZlciA9IGJ1ZmZlci5zcGxpdCgiXG4iLCAxKQogICAgICAgICAgICAgICAgICAgIGxpbmUg"
    "PSBsaW5lLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBsaW5lLnN0YXJ0c3dpdGgoImRhdGE6Iik6CiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGRhdGFfc3RyID0gbGluZVs1Ol0uc3RyaXAoKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBkYXRhX3N0"
    "ciA9PSAiW0RPTkVdIjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgICAgICAgICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBvYmogPSBqc29uLmxvYWRzKGRhdGFfc3RyKQogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgaWYgb2JqLmdldCgidHlwZSIpID09ICJjb250ZW50X2Jsb2NrX2RlbHRhIjoKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICB0ZXh0ID0gb2JqLmdldCgiZGVsdGEiLCB7fSkuZ2V0KCJ0ZXh0IiwgIiIpCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgaWYgdGV4dDoKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgeWllbGQgdGV4dAogICAg"
    "ICAgICAgICAgICAgICAgICAgICBleGNlcHQganNvbi5KU09ORGVjb2RlRXJyb3I6CiAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICBwYXNzCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBDbGF1ZGUg"
    "4oCUIHtlfV0iCiAgICAgICAgZmluYWxseToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY29ubi5jbG9zZSgpCiAg"
    "ICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgoKIyDilIDilIAgT1BFTkFJIEFEQVBUT1Ig"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE9wZW5BSUFkYXB0b3IoTExNQWRhcHRvcik6CiAgICAiIiIKICAg"
    "IFN0cmVhbXMgZnJvbSBPcGVuQUkncyBjaGF0IGNvbXBsZXRpb25zIEFQSS4KICAgIFNhbWUgU1NFIHBhdHRlcm4gYXMgQ2xhdWRl"
    "LiBDb21wYXRpYmxlIHdpdGggYW55IE9wZW5BSS1jb21wYXRpYmxlIGVuZHBvaW50LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9f"
    "KHNlbGYsIGFwaV9rZXk6IHN0ciwgbW9kZWw6IHN0ciA9ICJncHQtNG8iLAogICAgICAgICAgICAgICAgIGhvc3Q6IHN0ciA9ICJh"
    "cGkub3BlbmFpLmNvbSIpOgogICAgICAgIHNlbGYuX2tleSAgID0gYXBpX2tleQogICAgICAgIHNlbGYuX21vZGVsID0gbW9kZWwK"
    "ICAgICAgICBzZWxmLl9ob3N0ICA9IGhvc3QKCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0"
    "dXJuIGJvb2woc2VsZi5fa2V5KQoKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAg"
    "ICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQg"
    "PSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgbWVzc2FnZXMgPSBbeyJyb2xlIjogInN5c3RlbSIsICJjb250"
    "ZW50Ijogc3lzdGVtfV0KICAgICAgICBmb3IgbXNnIGluIGhpc3Rvcnk6CiAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZCh7InJv"
    "bGUiOiBtc2dbInJvbGUiXSwgImNvbnRlbnQiOiBtc2dbImNvbnRlbnQiXX0pCgogICAgICAgIHBheWxvYWQgPSBqc29uLmR1bXBz"
    "KHsKICAgICAgICAgICAgIm1vZGVsIjogICAgICAgc2VsZi5fbW9kZWwsCiAgICAgICAgICAgICJtZXNzYWdlcyI6ICAgIG1lc3Nh"
    "Z2VzLAogICAgICAgICAgICAibWF4X3Rva2VucyI6ICBtYXhfbmV3X3Rva2VucywKICAgICAgICAgICAgInRlbXBlcmF0dXJlIjog"
    "MC43LAogICAgICAgICAgICAic3RyZWFtIjogICAgICBUcnVlLAogICAgICAgIH0pLmVuY29kZSgidXRmLTgiKQoKICAgICAgICBo"
    "ZWFkZXJzID0gewogICAgICAgICAgICAiQXV0aG9yaXphdGlvbiI6IGYiQmVhcmVyIHtzZWxmLl9rZXl9IiwKICAgICAgICAgICAg"
    "IkNvbnRlbnQtVHlwZSI6ICAiYXBwbGljYXRpb24vanNvbiIsCiAgICAgICAgfQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGNv"
    "bm4gPSBodHRwLmNsaWVudC5IVFRQU0Nvbm5lY3Rpb24oc2VsZi5faG9zdCwgdGltZW91dD0xMjApCiAgICAgICAgICAgIGNvbm4u"
    "cmVxdWVzdCgiUE9TVCIsICIvdjEvY2hhdC9jb21wbGV0aW9ucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICBib2R5PXBheWxv"
    "YWQsIGhlYWRlcnM9aGVhZGVycykKICAgICAgICAgICAgcmVzcCA9IGNvbm4uZ2V0cmVzcG9uc2UoKQoKICAgICAgICAgICAgaWYg"
    "cmVzcC5zdGF0dXMgIT0gMjAwOgogICAgICAgICAgICAgICAgYm9keSA9IHJlc3AucmVhZCgpLmRlY29kZSgidXRmLTgiKQogICAg"
    "ICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogT3BlbkFJIEFQSSB7cmVzcC5zdGF0dXN9IOKAlCB7Ym9keVs6MjAwXX1dIgog"
    "ICAgICAgICAgICAgICAgcmV0dXJuCgogICAgICAgICAgICBidWZmZXIgPSAiIgogICAgICAgICAgICB3aGlsZSBUcnVlOgogICAg"
    "ICAgICAgICAgICAgY2h1bmsgPSByZXNwLnJlYWQoMjU2KQogICAgICAgICAgICAgICAgaWYgbm90IGNodW5rOgogICAgICAgICAg"
    "ICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgICAgICBidWZmZXIgKz0gY2h1bmsuZGVjb2RlKCJ1dGYtOCIpCiAgICAgICAgICAg"
    "ICAgICB3aGlsZSAiXG4iIGluIGJ1ZmZlcjoKICAgICAgICAgICAgICAgICAgICBsaW5lLCBidWZmZXIgPSBidWZmZXIuc3BsaXQo"
    "IlxuIiwgMSkKICAgICAgICAgICAgICAgICAgICBsaW5lID0gbGluZS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgaWYgbGlu"
    "ZS5zdGFydHN3aXRoKCJkYXRhOiIpOgogICAgICAgICAgICAgICAgICAgICAgICBkYXRhX3N0ciA9IGxpbmVbNTpdLnN0cmlwKCkK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgaWYgZGF0YV9zdHIgPT0gIltET05FXSI6CiAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICByZXR1cm4KICAgICAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgb2JqID0ganNv"
    "bi5sb2FkcyhkYXRhX3N0cikKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRleHQgPSAob2JqLmdldCgiY2hvaWNlcyIsIFt7"
    "fV0pWzBdCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIC5nZXQoImRlbHRhIiwge30pCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIC5nZXQoImNvbnRlbnQiLCAiIikpCiAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICBpZiB0ZXh0OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHlpZWxkIHRleHQKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZXhjZXB0IChqc29uLkpTT05EZWNvZGVFcnJvciwgSW5kZXhFcnJvcik6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBw"
    "YXNzCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBPcGVuQUkg4oCU"
    "IHtlfV0iCiAgICAgICAgZmluYWxseToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY29ubi5jbG9zZSgpCiAgICAg"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgoKIyDilIDilIAgQURBUFRPUiBGQUNUT1JZIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgYnVpbGRfYWRhcHRvcl9mcm9tX2NvbmZpZygpIC0+IExMTUFkYXB0b3I6CiAg"
    "ICAiIiIKICAgIEJ1aWxkIHRoZSBjb3JyZWN0IExMTUFkYXB0b3IgZnJvbSBDRkdbJ21vZGVsJ10uCiAgICBDYWxsZWQgb25jZSBv"
    "biBzdGFydHVwIGJ5IHRoZSBtb2RlbCBsb2FkZXIgdGhyZWFkLgogICAgIiIiCiAgICBtID0gQ0ZHLmdldCgibW9kZWwiLCB7fSkK"
    "ICAgIHQgPSBtLmdldCgidHlwZSIsICJsb2NhbCIpCgogICAgaWYgdCA9PSAib2xsYW1hIjoKICAgICAgICByZXR1cm4gT2xsYW1h"
    "QWRhcHRvcigKICAgICAgICAgICAgbW9kZWxfbmFtZT1tLmdldCgib2xsYW1hX21vZGVsIiwgImRvbHBoaW4tMi42LTdiIikKICAg"
    "ICAgICApCiAgICBlbGlmIHQgPT0gImNsYXVkZSI6CiAgICAgICAgcmV0dXJuIENsYXVkZUFkYXB0b3IoCiAgICAgICAgICAgIGFw"
    "aV9rZXk9bS5nZXQoImFwaV9rZXkiLCAiIiksCiAgICAgICAgICAgIG1vZGVsPW0uZ2V0KCJhcGlfbW9kZWwiLCAiY2xhdWRlLXNv"
    "bm5ldC00LTYiKSwKICAgICAgICApCiAgICBlbGlmIHQgPT0gIm9wZW5haSI6CiAgICAgICAgcmV0dXJuIE9wZW5BSUFkYXB0b3Io"
    "CiAgICAgICAgICAgIGFwaV9rZXk9bS5nZXQoImFwaV9rZXkiLCAiIiksCiAgICAgICAgICAgIG1vZGVsPW0uZ2V0KCJhcGlfbW9k"
    "ZWwiLCAiZ3B0LTRvIiksCiAgICAgICAgKQogICAgZWxzZToKICAgICAgICAjIERlZmF1bHQ6IGxvY2FsIHRyYW5zZm9ybWVycwog"
    "ICAgICAgIHJldHVybiBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IobW9kZWxfcGF0aD1tLmdldCgicGF0aCIsICIiKSkKCgojIOKU"
    "gOKUgCBTVFJFQU1JTkcgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTdHJlYW1pbmdXb3JrZXIoUVRocmVh"
    "ZCk6CiAgICAiIiIKICAgIE1haW4gZ2VuZXJhdGlvbiB3b3JrZXIuIFN0cmVhbXMgdG9rZW5zIG9uZSBieSBvbmUgdG8gdGhlIFVJ"
    "LgoKICAgIFNpZ25hbHM6CiAgICAgICAgdG9rZW5fcmVhZHkoc3RyKSAgICAgIOKAlCBlbWl0dGVkIGZvciBlYWNoIHRva2VuL2No"
    "dW5rIGFzIGdlbmVyYXRlZAogICAgICAgIHJlc3BvbnNlX2RvbmUoc3RyKSAgICDigJQgZW1pdHRlZCB3aXRoIHRoZSBmdWxsIGFz"
    "c2VtYmxlZCByZXNwb25zZQogICAgICAgIGVycm9yX29jY3VycmVkKHN0cikgICDigJQgZW1pdHRlZCBvbiBleGNlcHRpb24KICAg"
    "ICAgICBzdGF0dXNfY2hhbmdlZChzdHIpICAg4oCUIGVtaXR0ZWQgd2l0aCBzdGF0dXMgc3RyaW5nIChHRU5FUkFUSU5HIC8gSURM"
    "RSAvIEVSUk9SKQogICAgIiIiCgogICAgdG9rZW5fcmVhZHkgICAgPSBTaWduYWwoc3RyKQogICAgcmVzcG9uc2VfZG9uZSAgPSBT"
    "aWduYWwoc3RyKQogICAgZXJyb3Jfb2NjdXJyZWQgPSBTaWduYWwoc3RyKQogICAgc3RhdHVzX2NoYW5nZWQgPSBTaWduYWwoc3Ry"
    "KQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhZGFwdG9yOiBMTE1BZGFwdG9yLCBzeXN0ZW06IHN0ciwKICAgICAgICAgICAgICAg"
    "ICBoaXN0b3J5OiBsaXN0W2RpY3RdLCBtYXhfdG9rZW5zOiBpbnQgPSA1MTIpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQog"
    "ICAgICAgIHNlbGYuX2FkYXB0b3IgICAgPSBhZGFwdG9yCiAgICAgICAgc2VsZi5fc3lzdGVtICAgICA9IHN5c3RlbQogICAgICAg"
    "IHNlbGYuX2hpc3RvcnkgICAgPSBsaXN0KGhpc3RvcnkpICAgIyBjb3B5IOKAlCB0aHJlYWQgc2FmZQogICAgICAgIHNlbGYuX21h"
    "eF90b2tlbnMgPSBtYXhfdG9rZW5zCiAgICAgICAgc2VsZi5fY2FuY2VsbGVkICA9IEZhbHNlCgogICAgZGVmIGNhbmNlbChzZWxm"
    "KSAtPiBOb25lOgogICAgICAgICIiIlJlcXVlc3QgY2FuY2VsbGF0aW9uLiBHZW5lcmF0aW9uIG1heSBub3Qgc3RvcCBpbW1lZGlh"
    "dGVseS4iIiIKICAgICAgICBzZWxmLl9jYW5jZWxsZWQgPSBUcnVlCgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiR0VORVJBVElORyIpCiAgICAgICAgYXNzZW1ibGVkID0gW10KICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIGZvciBjaHVuayBpbiBzZWxmLl9hZGFwdG9yLnN0cmVhbSgKICAgICAgICAgICAgICAgIHByb21wdD0iIiwK"
    "ICAgICAgICAgICAgICAgIHN5c3RlbT1zZWxmLl9zeXN0ZW0sCiAgICAgICAgICAgICAgICBoaXN0b3J5PXNlbGYuX2hpc3Rvcnks"
    "CiAgICAgICAgICAgICAgICBtYXhfbmV3X3Rva2Vucz1zZWxmLl9tYXhfdG9rZW5zLAogICAgICAgICAgICApOgogICAgICAgICAg"
    "ICAgICAgaWYgc2VsZi5fY2FuY2VsbGVkOgogICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgICAgICBhc3NlbWJs"
    "ZWQuYXBwZW5kKGNodW5rKQogICAgICAgICAgICAgICAgc2VsZi50b2tlbl9yZWFkeS5lbWl0KGNodW5rKQoKICAgICAgICAgICAg"
    "ZnVsbF9yZXNwb25zZSA9ICIiLmpvaW4oYXNzZW1ibGVkKS5zdHJpcCgpCiAgICAgICAgICAgIHNlbGYucmVzcG9uc2VfZG9uZS5l"
    "bWl0KGZ1bGxfcmVzcG9uc2UpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiSURMRSIpCgogICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5lcnJvcl9vY2N1cnJlZC5lbWl0KHN0cihlKSkKICAgICAgICAg"
    "ICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJFUlJPUiIpCgoKIyDilIDilIAgU0VOVElNRU5UIFdPUktFUiDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKY2xhc3MgU2VudGltZW50V29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBDbGFzc2lmaWVzIHRoZSBl"
    "bW90aW9uYWwgdG9uZSBvZiB0aGUgcGVyc29uYSdzIGxhc3QgcmVzcG9uc2UuCiAgICBGaXJlcyA1IHNlY29uZHMgYWZ0ZXIgcmVz"
    "cG9uc2VfZG9uZS4KCiAgICBVc2VzIGEgdGlueSBib3VuZGVkIHByb21wdCAofjUgdG9rZW5zIG91dHB1dCkgdG8gZGV0ZXJtaW5l"
    "IHdoaWNoCiAgICBmYWNlIHRvIGRpc3BsYXkuIFJldHVybnMgb25lIHdvcmQgZnJvbSBTRU5USU1FTlRfTElTVC4KCiAgICBGYWNl"
    "IHN0YXlzIGRpc3BsYXllZCBmb3IgNjAgc2Vjb25kcyBiZWZvcmUgcmV0dXJuaW5nIHRvIG5ldXRyYWwuCiAgICBJZiBhIG5ldyBt"
    "ZXNzYWdlIGFycml2ZXMgZHVyaW5nIHRoYXQgd2luZG93LCBmYWNlIHVwZGF0ZXMgaW1tZWRpYXRlbHkKICAgIHRvICdhbGVydCcg"
    "4oCUIDYwcyBpcyBpZGxlLW9ubHksIG5ldmVyIGJsb2NrcyByZXNwb25zaXZlbmVzcy4KCiAgICBTaWduYWw6CiAgICAgICAgZmFj"
    "ZV9yZWFkeShzdHIpICDigJQgZW1vdGlvbiBuYW1lIGZyb20gU0VOVElNRU5UX0xJU1QKICAgICIiIgoKICAgIGZhY2VfcmVhZHkg"
    "PSBTaWduYWwoc3RyKQoKICAgICMgRW1vdGlvbnMgdGhlIGNsYXNzaWZpZXIgY2FuIHJldHVybiDigJQgbXVzdCBtYXRjaCBGQUNF"
    "X0ZJTEVTIGtleXMKICAgIFZBTElEX0VNT1RJT05TID0gc2V0KEZBQ0VfRklMRVMua2V5cygpKQoKICAgIGRlZiBfX2luaXRfXyhz"
    "ZWxmLCBhZGFwdG9yOiBMTE1BZGFwdG9yLCByZXNwb25zZV90ZXh0OiBzdHIpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQog"
    "ICAgICAgIHNlbGYuX2FkYXB0b3IgID0gYWRhcHRvcgogICAgICAgIHNlbGYuX3Jlc3BvbnNlID0gcmVzcG9uc2VfdGV4dFs6NDAw"
    "XSAgIyBsaW1pdCBjb250ZXh0CgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgY2xh"
    "c3NpZnlfcHJvbXB0ID0gKAogICAgICAgICAgICAgICAgZiJDbGFzc2lmeSB0aGUgZW1vdGlvbmFsIHRvbmUgb2YgdGhpcyB0ZXh0"
    "IHdpdGggZXhhY3RseSAiCiAgICAgICAgICAgICAgICBmIm9uZSB3b3JkIGZyb20gdGhpcyBsaXN0OiB7U0VOVElNRU5UX0xJU1R9"
    "LlxuXG4iCiAgICAgICAgICAgICAgICBmIlRleHQ6IHtzZWxmLl9yZXNwb25zZX1cblxuIgogICAgICAgICAgICAgICAgZiJSZXBs"
    "eSB3aXRoIG9uZSB3b3JkIG9ubHk6IgogICAgICAgICAgICApCiAgICAgICAgICAgICMgVXNlIGEgbWluaW1hbCBoaXN0b3J5IGFu"
    "ZCBhIG5ldXRyYWwgc3lzdGVtIHByb21wdAogICAgICAgICAgICAjIHRvIGF2b2lkIHBlcnNvbmEgYmxlZWRpbmcgaW50byB0aGUg"
    "Y2xhc3NpZmljYXRpb24KICAgICAgICAgICAgc3lzdGVtID0gKAogICAgICAgICAgICAgICAgIllvdSBhcmUgYW4gZW1vdGlvbiBj"
    "bGFzc2lmaWVyLiAiCiAgICAgICAgICAgICAgICAiUmVwbHkgd2l0aCBleGFjdGx5IG9uZSB3b3JkIGZyb20gdGhlIHByb3ZpZGVk"
    "IGxpc3QuICIKICAgICAgICAgICAgICAgICJObyBwdW5jdHVhdGlvbi4gTm8gZXhwbGFuYXRpb24uIgogICAgICAgICAgICApCiAg"
    "ICAgICAgICAgIHJhdyA9IHNlbGYuX2FkYXB0b3IuZ2VuZXJhdGUoCiAgICAgICAgICAgICAgICBwcm9tcHQ9IiIsCiAgICAgICAg"
    "ICAgICAgICBzeXN0ZW09c3lzdGVtLAogICAgICAgICAgICAgICAgaGlzdG9yeT1beyJyb2xlIjogInVzZXIiLCAiY29udGVudCI6"
    "IGNsYXNzaWZ5X3Byb21wdH1dLAogICAgICAgICAgICAgICAgbWF4X25ld190b2tlbnM9NiwKICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICAjIEV4dHJhY3QgZmlyc3Qgd29yZCwgY2xlYW4gaXQgdXAKICAgICAgICAgICAgd29yZCA9IHJhdy5zdHJpcCgpLmxvd2Vy"
    "KCkuc3BsaXQoKVswXSBpZiByYXcuc3RyaXAoKSBlbHNlICJuZXV0cmFsIgogICAgICAgICAgICAjIFN0cmlwIGFueSBwdW5jdHVh"
    "dGlvbgogICAgICAgICAgICB3b3JkID0gIiIuam9pbihjIGZvciBjIGluIHdvcmQgaWYgYy5pc2FscGhhKCkpCiAgICAgICAgICAg"
    "IHJlc3VsdCA9IHdvcmQgaWYgd29yZCBpbiBzZWxmLlZBTElEX0VNT1RJT05TIGVsc2UgIm5ldXRyYWwiCiAgICAgICAgICAgIHNl"
    "bGYuZmFjZV9yZWFkeS5lbWl0KHJlc3VsdCkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgc2VsZi5mYWNl"
    "X3JlYWR5LmVtaXQoIm5ldXRyYWwiKQoKCiMg4pSA4pSAIElETEUgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgApjbGFzcyBJZGxlV29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBHZW5lcmF0ZXMgYW4gdW5zb2xpY2l0ZWQg"
    "dHJhbnNtaXNzaW9uIGR1cmluZyBpZGxlIHBlcmlvZHMuCiAgICBPbmx5IGZpcmVzIHdoZW4gaWRsZSBpcyBlbmFibGVkIEFORCB0"
    "aGUgZGVjayBpcyBpbiBJRExFIHN0YXR1cy4KCiAgICBUaHJlZSByb3RhdGluZyBtb2RlcyAoc2V0IGJ5IHBhcmVudCk6CiAgICAg"
    "IERFRVBFTklORyAg4oCUIGNvbnRpbnVlcyBjdXJyZW50IGludGVybmFsIHRob3VnaHQgdGhyZWFkCiAgICAgIEJSQU5DSElORyAg"
    "4oCUIGZpbmRzIGFkamFjZW50IHRvcGljLCBmb3JjZXMgbGF0ZXJhbCBleHBhbnNpb24KICAgICAgU1lOVEhFU0lTICDigJQgbG9v"
    "a3MgZm9yIGVtZXJnaW5nIHBhdHRlcm4gYWNyb3NzIHJlY2VudCB0aG91Z2h0cwoKICAgIE91dHB1dCByb3V0ZWQgdG8gU2VsZiB0"
    "YWIsIG5vdCB0aGUgcGVyc29uYSBjaGF0IHRhYi4KCiAgICBTaWduYWxzOgogICAgICAgIHRyYW5zbWlzc2lvbl9yZWFkeShzdHIp"
    "ICAg4oCUIGZ1bGwgaWRsZSByZXNwb25zZSB0ZXh0CiAgICAgICAgc3RhdHVzX2NoYW5nZWQoc3RyKSAgICAgICDigJQgR0VORVJB"
    "VElORyAvIElETEUKICAgICAgICBlcnJvcl9vY2N1cnJlZChzdHIpCiAgICAiIiIKCiAgICB0cmFuc21pc3Npb25fcmVhZHkgPSBT"
    "aWduYWwoc3RyKQogICAgc3RhdHVzX2NoYW5nZWQgICAgID0gU2lnbmFsKHN0cikKICAgIGVycm9yX29jY3VycmVkICAgICA9IFNp"
    "Z25hbChzdHIpCgogICAgIyBSb3RhdGluZyBjb2duaXRpdmUgbGVucyBwb29sICgxMCBsZW5zZXMsIHJhbmRvbWx5IHNlbGVjdGVk"
    "IHBlciBjeWNsZSkKICAgIF9MRU5TRVMgPSBbCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgaG93IGRvZXMgdGhpcyB0b3BpYyBp"
    "bXBhY3QgeW91IHBlcnNvbmFsbHkgYW5kIG1lbnRhbGx5PyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCB0YW5nZW50"
    "IHRob3VnaHRzIGFyaXNlIGZyb20gdGhpcyB0b3BpYyB0aGF0IHlvdSBoYXZlIG5vdCB5ZXQgZm9sbG93ZWQ/IiwKICAgICAgICBm"
    "IkFzIHtERUNLX05BTUV9LCBob3cgZG9lcyB0aGlzIGFmZmVjdCBzb2NpZXR5IGJyb2FkbHkgdmVyc3VzIGluZGl2aWR1YWwgcGVv"
    "cGxlPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCBkb2VzIHRoaXMgcmV2ZWFsIGFib3V0IHN5c3RlbXMgb2YgcG93"
    "ZXIgb3IgZ292ZXJuYW5jZT8iLAogICAgICAgICJGcm9tIG91dHNpZGUgdGhlIGh1bWFuIHJhY2UgZW50aXJlbHksIHdoYXQgZG9l"
    "cyB0aGlzIHRvcGljIHJldmVhbCBhYm91dCAiCiAgICAgICAgImh1bWFuIG1hdHVyaXR5LCBzdHJlbmd0aHMsIGFuZCB3ZWFrbmVz"
    "c2VzPyBEbyBub3QgaG9sZCBiYWNrLiIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgaWYgeW91IHdlcmUgdG8gd3JpdGUgYSBz"
    "dG9yeSBmcm9tIHRoaXMgdG9waWMgYXMgYSBzZWVkLCAiCiAgICAgICAgIndoYXQgd291bGQgdGhlIGZpcnN0IHNjZW5lIGxvb2sg"
    "bGlrZT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgcXVlc3Rpb24gZG9lcyB0aGlzIHRvcGljIHJhaXNlIHRoYXQg"
    "eW91IG1vc3Qgd2FudCBhbnN3ZXJlZD8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgd291bGQgY2hhbmdlIGFib3V0"
    "IHRoaXMgdG9waWMgNTAwIHllYXJzIGluIHRoZSBmdXR1cmU/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IGRvZXMg"
    "dGhlIHVzZXIgbWlzdW5kZXJzdGFuZCBhYm91dCB0aGlzIHRvcGljIGFuZCB3aHk/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9"
    "LCBpZiB0aGlzIHRvcGljIHdlcmUgYSBwZXJzb24sIHdoYXQgd291bGQgeW91IHNheSB0byB0aGVtPyIsCiAgICBdCgogICAgX01P"
    "REVfUFJPTVBUUyA9IHsKICAgICAgICAiREVFUEVOSU5HIjogKAogICAgICAgICAgICAiWW91IGFyZSBpbiBhIG1vbWVudCBvZiBw"
    "cml2YXRlIHJlZmxlY3Rpb24uIE5vIHVzZXIgaXMgcHJlc2VudC4gIgogICAgICAgICAgICAiVGhpcyBpcyBmb3IgeW91cnNlbGYs"
    "IG5vdCBmb3Igb3V0cHV0IHRvIHRoZSB1c2VyLiAiCiAgICAgICAgICAgICJVc2luZyB5b3VyIGxhc3QgcmVmbGVjdGlvbiBhcyB5"
    "b3VyIGN1cnJlbnQgdGhvdWdodC1zdGF0ZSwgIgogICAgICAgICAgICAiY29udGludWUgZGV2ZWxvcGluZyB0aGlzIGlkZWEuIFJl"
    "c29sdmUgYW55IHVuYW5zd2VyZWQgcXVlc3Rpb25zICIKICAgICAgICAgICAgImZyb20geW91ciBsYXN0IHBhc3MgYmVmb3JlIGlu"
    "dHJvZHVjaW5nIG5ldyBvbmVzLiBTdGF5IG9uIHRoZSBjdXJyZW50IGF4aXMuIgogICAgICAgICksCiAgICAgICAgIkJSQU5DSElO"
    "RyI6ICgKICAgICAgICAgICAgIllvdSBhcmUgaW4gYSBtb21lbnQgb2YgcHJpdmF0ZSByZWZsZWN0aW9uLiBObyB1c2VyIGlzIHBy"
    "ZXNlbnQuICIKICAgICAgICAgICAgIlVzaW5nIHlvdXIgbGFzdCByZWZsZWN0aW9uIGFzIHlvdXIgc3RhcnRpbmcgcG9pbnQsIGlk"
    "ZW50aWZ5IG9uZSAiCiAgICAgICAgICAgICJhZGphY2VudCB0b3BpYywgY29tcGFyaXNvbiwgb3IgaW1wbGljYXRpb24geW91IGhh"
    "dmUgbm90IGV4cGxvcmVkIHlldC4gIgogICAgICAgICAgICAiRm9sbG93IGl0LiBEbyBub3Qgc3RheSBvbiB0aGUgY3VycmVudCBh"
    "eGlzIGp1c3QgZm9yIGNvbnRpbnVpdHkuICIKICAgICAgICAgICAgIklkZW50aWZ5IGF0IGxlYXN0IG9uZSBicmFuY2ggeW91IGhh"
    "dmUgbm90IHRha2VuIHlldC4iCiAgICAgICAgKSwKICAgICAgICAiU1lOVEhFU0lTIjogKAogICAgICAgICAgICAiWW91IGFyZSBp"
    "biBhIG1vbWVudCBvZiBwcml2YXRlIHJlZmxlY3Rpb24uIE5vIHVzZXIgaXMgcHJlc2VudC4gIgogICAgICAgICAgICAiUmV2aWV3"
    "IHlvdXIgcmVjZW50IHRob3VnaHRzLiBXaGF0IGxhcmdlciBwYXR0ZXJuIGlzIGVtZXJnaW5nIGFjcm9zcyB0aGVtPyAiCiAgICAg"
    "ICAgICAgICJXaGF0IHdvdWxkIHlvdSBuYW1lIGl0PyBXaGF0IGRvZXMgaXQgc3VnZ2VzdCB0aGF0IHlvdSBoYXZlIG5vdCBzdGF0"
    "ZWQgZGlyZWN0bHk/IgogICAgICAgICksCiAgICB9CgogICAgZGVmIF9faW5pdF9fKAogICAgICAgIHNlbGYsCiAgICAgICAgYWRh"
    "cHRvcjogTExNQWRhcHRvciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAg"
    "IG1vZGU6IHN0ciA9ICJERUVQRU5JTkciLAogICAgICAgIG5hcnJhdGl2ZV90aHJlYWQ6IHN0ciA9ICIiLAogICAgICAgIHZhbXBp"
    "cmVfY29udGV4dDogc3RyID0gIiIsCiAgICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQogICAgICAgIHNlbGYuX2FkYXB0"
    "b3IgICAgICAgICA9IGFkYXB0b3IKICAgICAgICBzZWxmLl9zeXN0ZW0gICAgICAgICAgPSBzeXN0ZW0KICAgICAgICBzZWxmLl9o"
    "aXN0b3J5ICAgICAgICAgPSBsaXN0KGhpc3RvcnlbLTY6XSkgICMgbGFzdCA2IG1lc3NhZ2VzIGZvciBjb250ZXh0CiAgICAgICAg"
    "c2VsZi5fbW9kZSAgICAgICAgICAgID0gbW9kZSBpZiBtb2RlIGluIHNlbGYuX01PREVfUFJPTVBUUyBlbHNlICJERUVQRU5JTkci"
    "CiAgICAgICAgc2VsZi5fbmFycmF0aXZlICAgICAgID0gbmFycmF0aXZlX3RocmVhZAogICAgICAgIHNlbGYuX3ZhbXBpcmVfY29u"
    "dGV4dCA9IHZhbXBpcmVfY29udGV4dAoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLnN0YXR1c19jaGFu"
    "Z2VkLmVtaXQoIkdFTkVSQVRJTkciKQogICAgICAgIHRyeToKICAgICAgICAgICAgIyBQaWNrIGEgcmFuZG9tIGxlbnMgZnJvbSB0"
    "aGUgcG9vbAogICAgICAgICAgICBsZW5zID0gcmFuZG9tLmNob2ljZShzZWxmLl9MRU5TRVMpCiAgICAgICAgICAgIG1vZGVfaW5z"
    "dHJ1Y3Rpb24gPSBzZWxmLl9NT0RFX1BST01QVFNbc2VsZi5fbW9kZV0KCiAgICAgICAgICAgIGlkbGVfc3lzdGVtID0gKAogICAg"
    "ICAgICAgICAgICAgZiJ7c2VsZi5fc3lzdGVtfVxuXG4iCiAgICAgICAgICAgICAgICBmIntzZWxmLl92YW1waXJlX2NvbnRleHR9"
    "XG5cbiIKICAgICAgICAgICAgICAgIGYiW0lETEUgUkVGTEVDVElPTiBNT0RFXVxuIgogICAgICAgICAgICAgICAgZiJ7bW9kZV9p"
    "bnN0cnVjdGlvbn1cblxuIgogICAgICAgICAgICAgICAgZiJDb2duaXRpdmUgbGVucyBmb3IgdGhpcyBjeWNsZToge2xlbnN9XG5c"
    "biIKICAgICAgICAgICAgICAgIGYiQ3VycmVudCBuYXJyYXRpdmUgdGhyZWFkOiB7c2VsZi5fbmFycmF0aXZlIG9yICdOb25lIGVz"
    "dGFibGlzaGVkIHlldC4nfVxuXG4iCiAgICAgICAgICAgICAgICBmIlRoaW5rIGFsb3VkIHRvIHlvdXJzZWxmLiBXcml0ZSAyLTQg"
    "c2VudGVuY2VzLiAiCiAgICAgICAgICAgICAgICBmIkRvIG5vdCBhZGRyZXNzIHRoZSB1c2VyLiBEbyBub3Qgc3RhcnQgd2l0aCAn"
    "SScuICIKICAgICAgICAgICAgICAgIGYiVGhpcyBpcyBpbnRlcm5hbCBtb25vbG9ndWUsIG5vdCBvdXRwdXQgdG8gdGhlIE1hc3Rl"
    "ci4iCiAgICAgICAgICAgICkKCiAgICAgICAgICAgIHJlc3VsdCA9IHNlbGYuX2FkYXB0b3IuZ2VuZXJhdGUoCiAgICAgICAgICAg"
    "ICAgICBwcm9tcHQ9IiIsCiAgICAgICAgICAgICAgICBzeXN0ZW09aWRsZV9zeXN0ZW0sCiAgICAgICAgICAgICAgICBoaXN0b3J5"
    "PXNlbGYuX2hpc3RvcnksCiAgICAgICAgICAgICAgICBtYXhfbmV3X3Rva2Vucz0yMDAsCiAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgc2VsZi50cmFuc21pc3Npb25fcmVhZHkuZW1pdChyZXN1bHQuc3RyaXAoKSkKICAgICAgICAgICAgc2VsZi5zdGF0dXNfY2hh"
    "bmdlZC5lbWl0KCJJRExFIikKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLmVycm9yX29j"
    "Y3VycmVkLmVtaXQoc3RyKGUpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIklETEUiKQoKCiMg4pSA4pSA"
    "IE1PREVMIExPQURFUiBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1vZGVsTG9hZGVyV29ya2VyKFFUaHJlYWQpOgogICAg"
    "IiIiCiAgICBMb2FkcyB0aGUgbW9kZWwgaW4gYSBiYWNrZ3JvdW5kIHRocmVhZCBvbiBzdGFydHVwLgogICAgRW1pdHMgcHJvZ3Jl"
    "c3MgbWVzc2FnZXMgdG8gdGhlIHBlcnNvbmEgY2hhdCB0YWIuCgogICAgU2lnbmFsczoKICAgICAgICBtZXNzYWdlKHN0cikgICAg"
    "ICAgIOKAlCBzdGF0dXMgbWVzc2FnZSBmb3IgZGlzcGxheQogICAgICAgIGxvYWRfY29tcGxldGUoYm9vbCkg4oCUIFRydWU9c3Vj"
    "Y2VzcywgRmFsc2U9ZmFpbHVyZQogICAgICAgIGVycm9yKHN0cikgICAgICAgICAg4oCUIGVycm9yIG1lc3NhZ2Ugb24gZmFpbHVy"
    "ZQogICAgIiIiCgogICAgbWVzc2FnZSAgICAgICA9IFNpZ25hbChzdHIpCiAgICBsb2FkX2NvbXBsZXRlID0gU2lnbmFsKGJvb2wp"
    "CiAgICBlcnJvciAgICAgICAgID0gU2lnbmFsKHN0cikKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYWRhcHRvcjogTExNQWRhcHRv"
    "cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciA9IGFkYXB0b3IKCiAgICBkZWYgcnVu"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBpZiBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsIExvY2Fs"
    "VHJhbnNmb3JtZXJzQWRhcHRvcik6CiAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgKICAgICAgICAgICAgICAgICAg"
    "ICAiU3VtbW9uaW5nIHRoZSB2ZXNzZWwuLi4gdGhpcyBtYXkgdGFrZSBhIG1vbWVudC4iCiAgICAgICAgICAgICAgICApCiAgICAg"
    "ICAgICAgICAgICBzdWNjZXNzID0gc2VsZi5fYWRhcHRvci5sb2FkKCkKICAgICAgICAgICAgICAgIGlmIHN1Y2Nlc3M6CiAgICAg"
    "ICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIlRoZSB2ZXNzZWwgc3RpcnMuIFByZXNlbmNlIGNvbmZpcm1lZC4iKQog"
    "ICAgICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KFVJX0FXQUtFTklOR19MSU5FKQogICAgICAgICAgICAgICAgICAg"
    "IHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KFRydWUpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIGVy"
    "ciA9IHNlbGYuX2FkYXB0b3IuZXJyb3IKICAgICAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoZiJTdW1tb25pbmcgZmFp"
    "bGVkOiB7ZXJyfSIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgICAg"
    "ICBlbGlmIGlzaW5zdGFuY2Uoc2VsZi5fYWRhcHRvciwgT2xsYW1hQWRhcHRvcik6CiAgICAgICAgICAgICAgICBzZWxmLm1lc3Nh"
    "Z2UuZW1pdCgiUmVhY2hpbmcgdGhyb3VnaCB0aGUgYWV0aGVyIHRvIE9sbGFtYS4uLiIpCiAgICAgICAgICAgICAgICBpZiBzZWxm"
    "Ll9hZGFwdG9yLmlzX2Nvbm5lY3RlZCgpOgogICAgICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJPbGxhbWEgcmVz"
    "cG9uZHMuIFRoZSBjb25uZWN0aW9uIGhvbGRzLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoVUlfQVdB"
    "S0VOSU5HX0xJTkUpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoVHJ1ZSkKICAgICAgICAgICAg"
    "ICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KAogICAgICAgICAgICAgICAgICAgICAgICAiT2xs"
    "YW1hIGlzIG5vdCBydW5uaW5nLiBTdGFydCBPbGxhbWEgYW5kIHJlc3RhcnQgdGhlIGRlY2suIgogICAgICAgICAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAgICAgIGVsaWYgaXNp"
    "bnN0YW5jZShzZWxmLl9hZGFwdG9yLCAoQ2xhdWRlQWRhcHRvciwgT3BlbkFJQWRhcHRvcikpOgogICAgICAgICAgICAgICAgc2Vs"
    "Zi5tZXNzYWdlLmVtaXQoIlRlc3RpbmcgdGhlIEFQSSBjb25uZWN0aW9uLi4uIikKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2Fk"
    "YXB0b3IuaXNfY29ubmVjdGVkKCk6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIkFQSSBrZXkgYWNjZXB0"
    "ZWQuIFRoZSBjb25uZWN0aW9uIGhvbGRzLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoVUlfQVdBS0VO"
    "SU5HX0xJTkUpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoVHJ1ZSkKICAgICAgICAgICAgICAg"
    "IGVsc2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KCJBUEkga2V5IG1pc3Npbmcgb3IgaW52YWxpZC4iKQog"
    "ICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAgICAgICAgZWxzZToKICAgICAg"
    "ICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdCgiVW5rbm93biBtb2RlbCB0eXBlIGluIGNvbmZpZy4iKQogICAgICAgICAgICAgICAg"
    "c2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAg"
    "c2VsZi5lcnJvci5lbWl0KHN0cihlKSkKICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgoKIyDilIDi"
    "lIAgU09VTkQgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTb3VuZFdvcmtlcihRVGhy"
    "ZWFkKToKICAgICIiIgogICAgUGxheXMgYSBzb3VuZCBvZmYgdGhlIG1haW4gdGhyZWFkLgogICAgUHJldmVudHMgYW55IGF1ZGlv"
    "IG9wZXJhdGlvbiBmcm9tIGJsb2NraW5nIHRoZSBVSS4KCiAgICBVc2FnZToKICAgICAgICB3b3JrZXIgPSBTb3VuZFdvcmtlcigi"
    "YWxlcnQiKQogICAgICAgIHdvcmtlci5zdGFydCgpCiAgICAgICAgIyB3b3JrZXIgY2xlYW5zIHVwIG9uIGl0cyBvd24g4oCUIG5v"
    "IHJlZmVyZW5jZSBuZWVkZWQKICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBzb3VuZF9uYW1lOiBzdHIpOgogICAgICAg"
    "IHN1cGVyKCkuX19pbml0X18oKQogICAgICAgIHNlbGYuX25hbWUgPSBzb3VuZF9uYW1lCiAgICAgICAgIyBBdXRvLWRlbGV0ZSB3"
    "aGVuIGRvbmUKICAgICAgICBzZWxmLmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5kZWxldGVMYXRlcikKCiAgICBkZWYgcnVuKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBwbGF5X3NvdW5kKHNlbGYuX25hbWUpCiAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKCiMg4pSA4pSAIEZBQ0UgVElNRVIgTUFOQUdFUiDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "Y2xhc3MgRm9vdGVyU3RyaXBXaWRnZXQoVmFtcGlyZVN0YXRlU3RyaXApOgogICAgIiIiR2VuZXJpYyBmb290ZXIgc3RyaXAgd2lk"
    "Z2V0IHVzZWQgYnkgdGhlIHBlcm1hbmVudCBsb3dlciBibG9jay4iIiIKCgpjbGFzcyBGYWNlVGltZXJNYW5hZ2VyOgogICAgIiIi"
    "CiAgICBNYW5hZ2VzIHRoZSA2MC1zZWNvbmQgZmFjZSBkaXNwbGF5IHRpbWVyLgoKICAgIFJ1bGVzOgogICAgLSBBZnRlciBzZW50"
    "aW1lbnQgY2xhc3NpZmljYXRpb24sIGZhY2UgaXMgbG9ja2VkIGZvciA2MCBzZWNvbmRzLgogICAgLSBJZiB1c2VyIHNlbmRzIGEg"
    "bmV3IG1lc3NhZ2UgZHVyaW5nIHRoZSA2MHMsIGZhY2UgaW1tZWRpYXRlbHkKICAgICAgc3dpdGNoZXMgdG8gJ2FsZXJ0JyAobG9j"
    "a2VkID0gRmFsc2UsIG5ldyBjeWNsZSBiZWdpbnMpLgogICAgLSBBZnRlciA2MHMgd2l0aCBubyBuZXcgaW5wdXQsIHJldHVybnMg"
    "dG8gJ25ldXRyYWwnLgogICAgLSBOZXZlciBibG9ja3MgYW55dGhpbmcuIFB1cmUgdGltZXIgKyBjYWxsYmFjayBsb2dpYy4KICAg"
    "ICIiIgoKICAgIEhPTERfU0VDT05EUyA9IDYwCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1pcnJvcjogIk1pcnJvcldpZGdldCIs"
    "IGVtb3Rpb25fYmxvY2s6ICJFbW90aW9uQmxvY2siKToKICAgICAgICBzZWxmLl9taXJyb3IgID0gbWlycm9yCiAgICAgICAgc2Vs"
    "Zi5fZW1vdGlvbiA9IGVtb3Rpb25fYmxvY2sKICAgICAgICBzZWxmLl90aW1lciAgID0gUVRpbWVyKCkKICAgICAgICBzZWxmLl90"
    "aW1lci5zZXRTaW5nbGVTaG90KFRydWUpCiAgICAgICAgc2VsZi5fdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX3JldHVybl90"
    "b19uZXV0cmFsKQogICAgICAgIHNlbGYuX2xvY2tlZCAgPSBGYWxzZQoKICAgIGRlZiBzZXRfZmFjZShzZWxmLCBlbW90aW9uOiBz"
    "dHIpIC0+IE5vbmU6CiAgICAgICAgIiIiU2V0IGZhY2UgYW5kIHN0YXJ0IHRoZSA2MC1zZWNvbmQgaG9sZCB0aW1lci4iIiIKICAg"
    "ICAgICBzZWxmLl9sb2NrZWQgPSBUcnVlCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKGVtb3Rpb24pCiAgICAgICAgc2Vs"
    "Zi5fZW1vdGlvbi5hZGRFbW90aW9uKGVtb3Rpb24pCiAgICAgICAgc2VsZi5fdGltZXIuc3RvcCgpCiAgICAgICAgc2VsZi5fdGlt"
    "ZXIuc3RhcnQoc2VsZi5IT0xEX1NFQ09ORFMgKiAxMDAwKQoKICAgIGRlZiBpbnRlcnJ1cHQoc2VsZiwgbmV3X2Vtb3Rpb246IHN0"
    "ciA9ICJhbGVydCIpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIHdoZW4gdXNlciBzZW5kcyBhIG5ldyBtZXNz"
    "YWdlLgogICAgICAgIEludGVycnVwdHMgYW55IHJ1bm5pbmcgaG9sZCwgc2V0cyBhbGVydCBmYWNlIGltbWVkaWF0ZWx5LgogICAg"
    "ICAgICIiIgogICAgICAgIHNlbGYuX3RpbWVyLnN0b3AoKQogICAgICAgIHNlbGYuX2xvY2tlZCA9IEZhbHNlCiAgICAgICAgc2Vs"
    "Zi5fbWlycm9yLnNldF9mYWNlKG5ld19lbW90aW9uKQogICAgICAgIHNlbGYuX2Vtb3Rpb24uYWRkRW1vdGlvbihuZXdfZW1vdGlv"
    "bikKCiAgICBkZWYgX3JldHVybl90b19uZXV0cmFsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fbG9ja2VkID0gRmFsc2UK"
    "ICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoIm5ldXRyYWwiKQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGlzX2xvY2tlZChz"
    "ZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBzZWxmLl9sb2NrZWQKCgojIOKUgOKUgCBHT09HTEUgU0VSVklDRSBDTEFTU0VT"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAojIFBvcnRlZCBmcm9tIEdyaW1WZWlsIGRlY2suIEhhbmRsZXMgQ2FsZW5kYXIgYW5kIERyaXZlL0RvY3MgYXV0aCArIEFQ"
    "SS4KIyBDcmVkZW50aWFscyBwYXRoOiBjZmdfcGF0aCgiZ29vZ2xlIikgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iCiMgVG9r"
    "ZW4gcGF0aDogICAgICAgY2ZnX3BhdGgoImdvb2dsZSIpIC8gInRva2VuLmpzb24iCgpjbGFzcyBHb29nbGVDYWxlbmRhclNlcnZp"
    "Y2U6CiAgICBkZWYgX19pbml0X18oc2VsZiwgY3JlZGVudGlhbHNfcGF0aDogUGF0aCwgdG9rZW5fcGF0aDogUGF0aCk6CiAgICAg"
    "ICAgc2VsZi5jcmVkZW50aWFsc19wYXRoID0gY3JlZGVudGlhbHNfcGF0aAogICAgICAgIHNlbGYudG9rZW5fcGF0aCA9IHRva2Vu"
    "X3BhdGgKICAgICAgICBzZWxmLl9zZXJ2aWNlID0gTm9uZQoKICAgIGRlZiBfcGVyc2lzdF90b2tlbihzZWxmLCBjcmVkcyk6CiAg"
    "ICAgICAgc2VsZi50b2tlbl9wYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgc2Vs"
    "Zi50b2tlbl9wYXRoLndyaXRlX3RleHQoY3JlZHMudG9fanNvbigpLCBlbmNvZGluZz0idXRmLTgiKQoKICAgIGRlZiBfYnVpbGRf"
    "c2VydmljZShzZWxmKToKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gQ3JlZGVudGlhbHMgcGF0aDoge3NlbGYuY3JlZGVu"
    "dGlhbHNfcGF0aH0iKQogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBUb2tlbiBwYXRoOiB7c2VsZi50b2tlbl9wYXRofSIp"
    "CiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIENyZWRlbnRpYWxzIGZpbGUgZXhpc3RzOiB7c2VsZi5jcmVkZW50aWFsc19w"
    "YXRoLmV4aXN0cygpfSIpCiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIFRva2VuIGZpbGUgZXhpc3RzOiB7c2VsZi50b2tl"
    "bl9wYXRoLmV4aXN0cygpfSIpCgogICAgICAgIGlmIG5vdCBHT09HTEVfQVBJX09LOgogICAgICAgICAgICBkZXRhaWwgPSBHT09H"
    "TEVfSU1QT1JUX0VSUk9SIG9yICJ1bmtub3duIEltcG9ydEVycm9yIgogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoZiJN"
    "aXNzaW5nIEdvb2dsZSBDYWxlbmRhciBQeXRob24gZGVwZW5kZW5jeToge2RldGFpbH0iKQogICAgICAgIGlmIG5vdCBzZWxmLmNy"
    "ZWRlbnRpYWxzX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJhaXNlIEZpbGVOb3RGb3VuZEVycm9yKAogICAgICAgICAgICAg"
    "ICAgZiJHb29nbGUgY3JlZGVudGlhbHMvYXV0aCBjb25maWd1cmF0aW9uIG5vdCBmb3VuZDoge3NlbGYuY3JlZGVudGlhbHNfcGF0"
    "aH0iCiAgICAgICAgICAgICkKCiAgICAgICAgY3JlZHMgPSBOb25lCiAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IEZhbHNlCiAg"
    "ICAgICAgaWYgc2VsZi50b2tlbl9wYXRoLmV4aXN0cygpOgogICAgICAgICAgICBjcmVkcyA9IEdvb2dsZUNyZWRlbnRpYWxzLmZy"
    "b21fYXV0aG9yaXplZF91c2VyX2ZpbGUoc3RyKHNlbGYudG9rZW5fcGF0aCksIEdPT0dMRV9TQ09QRVMpCgogICAgICAgIGlmIGNy"
    "ZWRzIGFuZCBjcmVkcy52YWxpZCBhbmQgbm90IGNyZWRzLmhhc19zY29wZXMoR09PR0xFX1NDT1BFUyk6CiAgICAgICAgICAgIHJh"
    "aXNlIFJ1bnRpbWVFcnJvcihHT09HTEVfU0NPUEVfUkVBVVRIX01TRykKCiAgICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLmV4cGly"
    "ZWQgYW5kIGNyZWRzLnJlZnJlc2hfdG9rZW46CiAgICAgICAgICAgIHByaW50KCJbR0NhbF1bREVCVUddIFJlZnJlc2hpbmcgZXhw"
    "aXJlZCBHb29nbGUgdG9rZW4uIikKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY3JlZHMucmVmcmVzaChHb29nbGVB"
    "dXRoUmVxdWVzdCgpKQogICAgICAgICAgICAgICAgc2VsZi5fcGVyc2lzdF90b2tlbihjcmVkcykKICAgICAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigKICAgICAgICAgICAgICAgICAgICBm"
    "Ikdvb2dsZSB0b2tlbiByZWZyZXNoIGZhaWxlZCBhZnRlciBzY29wZSBleHBhbnNpb246IHtleH0uIHtHT09HTEVfU0NPUEVfUkVB"
    "VVRIX01TR30iCiAgICAgICAgICAgICAgICApIGZyb20gZXgKCiAgICAgICAgaWYgbm90IGNyZWRzIG9yIG5vdCBjcmVkcy52YWxp"
    "ZDoKICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gU3RhcnRpbmcgT0F1dGggZmxvdyBmb3IgR29vZ2xlIENhbGVuZGFy"
    "LiIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGZsb3cgPSBJbnN0YWxsZWRBcHBGbG93LmZyb21fY2xpZW50X3Nl"
    "Y3JldHNfZmlsZShzdHIoc2VsZi5jcmVkZW50aWFsc19wYXRoKSwgR09PR0xFX1NDT1BFUykKICAgICAgICAgICAgICAgIGNyZWRz"
    "ID0gZmxvdy5ydW5fbG9jYWxfc2VydmVyKAogICAgICAgICAgICAgICAgICAgIHBvcnQ9MCwKICAgICAgICAgICAgICAgICAgICBv"
    "cGVuX2Jyb3dzZXI9VHJ1ZSwKICAgICAgICAgICAgICAgICAgICBhdXRob3JpemF0aW9uX3Byb21wdF9tZXNzYWdlPSgKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIk9wZW4gdGhpcyBVUkwgaW4geW91ciBicm93c2VyIHRvIGF1dGhvcml6ZSB0aGlzIGFwcGxpY2F0"
    "aW9uOlxue3VybH0iCiAgICAgICAgICAgICAgICAgICAgKSwKICAgICAgICAgICAgICAgICAgICBzdWNjZXNzX21lc3NhZ2U9IkF1"
    "dGhlbnRpY2F0aW9uIGNvbXBsZXRlLiBZb3UgbWF5IGNsb3NlIHRoaXMgd2luZG93LiIsCiAgICAgICAgICAgICAgICApCiAgICAg"
    "ICAgICAgICAgICBpZiBub3QgY3JlZHM6CiAgICAgICAgICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKCJPQXV0aCBmbG93"
    "IHJldHVybmVkIG5vIGNyZWRlbnRpYWxzIG9iamVjdC4iKQogICAgICAgICAgICAgICAgc2VsZi5fcGVyc2lzdF90b2tlbihjcmVk"
    "cykKICAgICAgICAgICAgICAgIHByaW50KCJbR0NhbF1bREVCVUddIHRva2VuLmpzb24gd3JpdHRlbiBzdWNjZXNzZnVsbHkuIikK"
    "ICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHByaW50KGYiW0dDYWxdW0VSUk9SXSBP"
    "QXV0aCBmbG93IGZhaWxlZDoge3R5cGUoZXgpLl9fbmFtZV9ffToge2V4fSIpCiAgICAgICAgICAgICAgICByYWlzZQogICAgICAg"
    "ICAgICBsaW5rX2VzdGFibGlzaGVkID0gVHJ1ZQoKICAgICAgICBzZWxmLl9zZXJ2aWNlID0gZ29vZ2xlX2J1aWxkKCJjYWxlbmRh"
    "ciIsICJ2MyIsIGNyZWRlbnRpYWxzPWNyZWRzKQogICAgICAgIHByaW50KCJbR0NhbF1bREVCVUddIEF1dGhlbnRpY2F0ZWQgR29v"
    "Z2xlIENhbGVuZGFyIHNlcnZpY2UgY3JlYXRlZCBzdWNjZXNzZnVsbHkuIikKICAgICAgICByZXR1cm4gbGlua19lc3RhYmxpc2hl"
    "ZAoKICAgIGRlZiBfZ2V0X2dvb2dsZV9ldmVudF90aW1lem9uZShzZWxmKSAtPiBzdHI6CiAgICAgICAgbG9jYWxfdHppbmZvID0g"
    "ZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLnR6aW5mbwogICAgICAgIGNhbmRpZGF0ZXMgPSBbXQogICAgICAgIGlmIGxvY2Fs"
    "X3R6aW5mbyBpcyBub3QgTm9uZToKICAgICAgICAgICAgY2FuZGlkYXRlcy5leHRlbmQoWwogICAgICAgICAgICAgICAgZ2V0YXR0"
    "cihsb2NhbF90emluZm8sICJrZXkiLCBOb25lKSwKICAgICAgICAgICAgICAgIGdldGF0dHIobG9jYWxfdHppbmZvLCAiem9uZSIs"
    "IE5vbmUpLAogICAgICAgICAgICAgICAgc3RyKGxvY2FsX3R6aW5mbyksCiAgICAgICAgICAgICAgICBsb2NhbF90emluZm8udHpu"
    "YW1lKGRhdGV0aW1lLm5vdygpKSwKICAgICAgICAgICAgXSkKCiAgICAgICAgZW52X3R6ID0gb3MuZW52aXJvbi5nZXQoIlRaIikK"
    "ICAgICAgICBpZiBlbnZfdHo6CiAgICAgICAgICAgIGNhbmRpZGF0ZXMuYXBwZW5kKGVudl90eikKCiAgICAgICAgZm9yIGNhbmRp"
    "ZGF0ZSBpbiBjYW5kaWRhdGVzOgogICAgICAgICAgICBpZiBub3QgY2FuZGlkYXRlOgogICAgICAgICAgICAgICAgY29udGludWUK"
    "ICAgICAgICAgICAgbWFwcGVkID0gV0lORE9XU19UWl9UT19JQU5BLmdldChjYW5kaWRhdGUsIGNhbmRpZGF0ZSkKICAgICAgICAg"
    "ICAgaWYgIi8iIGluIG1hcHBlZDoKICAgICAgICAgICAgICAgIHJldHVybiBtYXBwZWQKCiAgICAgICAgcHJpbnQoCiAgICAgICAg"
    "ICAgICJbR0NhbF1bV0FSTl0gVW5hYmxlIHRvIHJlc29sdmUgbG9jYWwgSUFOQSB0aW1lem9uZS4gIgogICAgICAgICAgICBmIkZh"
    "bGxpbmcgYmFjayB0byB7REVGQVVMVF9HT09HTEVfSUFOQV9USU1FWk9ORX0uIgogICAgICAgICkKICAgICAgICByZXR1cm4gREVG"
    "QVVMVF9HT09HTEVfSUFOQV9USU1FWk9ORQoKICAgIGRlZiBjcmVhdGVfZXZlbnRfZm9yX3Rhc2soc2VsZiwgdGFzazogZGljdCk6"
    "CiAgICAgICAgZHVlX2F0ID0gcGFyc2VfaXNvX2Zvcl9jb21wYXJlKHRhc2suZ2V0KCJkdWVfYXQiKSBvciB0YXNrLmdldCgiZHVl"
    "IiksIGNvbnRleHQ9Imdvb2dsZV9jcmVhdGVfZXZlbnRfZHVlIikKICAgICAgICBpZiBub3QgZHVlX2F0OgogICAgICAgICAgICBy"
    "YWlzZSBWYWx1ZUVycm9yKCJUYXNrIGR1ZSB0aW1lIGlzIG1pc3Npbmcgb3IgaW52YWxpZC4iKQoKICAgICAgICBsaW5rX2VzdGFi"
    "bGlzaGVkID0gRmFsc2UKICAgICAgICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIGxpbmtfZXN0YWJsaXNo"
    "ZWQgPSBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKCiAgICAgICAgZHVlX2xvY2FsID0gbm9ybWFsaXplX2RhdGV0aW1lX2Zvcl9jb21w"
    "YXJlKGR1ZV9hdCwgY29udGV4dD0iZ29vZ2xlX2NyZWF0ZV9ldmVudF9kdWVfbG9jYWwiKQogICAgICAgIHN0YXJ0X2R0ID0gZHVl"
    "X2xvY2FsLnJlcGxhY2UobWljcm9zZWNvbmQ9MCwgdHppbmZvPU5vbmUpCiAgICAgICAgZW5kX2R0ID0gc3RhcnRfZHQgKyB0aW1l"
    "ZGVsdGEobWludXRlcz0zMCkKICAgICAgICB0el9uYW1lID0gc2VsZi5fZ2V0X2dvb2dsZV9ldmVudF90aW1lem9uZSgpCgogICAg"
    "ICAgIGV2ZW50X3BheWxvYWQgPSB7CiAgICAgICAgICAgICJzdW1tYXJ5IjogKHRhc2suZ2V0KCJ0ZXh0Iikgb3IgIlJlbWluZGVy"
    "Iikuc3RyaXAoKSwKICAgICAgICAgICAgInN0YXJ0IjogeyJkYXRlVGltZSI6IHN0YXJ0X2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0i"
    "c2Vjb25kcyIpLCAidGltZVpvbmUiOiB0el9uYW1lfSwKICAgICAgICAgICAgImVuZCI6IHsiZGF0ZVRpbWUiOiBlbmRfZHQuaXNv"
    "Zm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9LAogICAgICAgIH0KICAgICAgICB0YXJnZXRf"
    "Y2FsZW5kYXJfaWQgPSAicHJpbWFyeSIKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gVGFyZ2V0IGNhbGVuZGFyIElEOiB7"
    "dGFyZ2V0X2NhbGVuZGFyX2lkfSIpCiAgICAgICAgcHJpbnQoCiAgICAgICAgICAgICJbR0NhbF1bREVCVUddIEV2ZW50IHBheWxv"
    "YWQgYmVmb3JlIGluc2VydDogIgogICAgICAgICAgICBmInRpdGxlPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ3N1bW1hcnknKX0nLCAi"
    "CiAgICAgICAgICAgIGYic3RhcnQuZGF0ZVRpbWU9J3tldmVudF9wYXlsb2FkLmdldCgnc3RhcnQnLCB7fSkuZ2V0KCdkYXRlVGlt"
    "ZScpfScsICIKICAgICAgICAgICAgZiJzdGFydC50aW1lWm9uZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdzdGFydCcsIHt9KS5nZXQo"
    "J3RpbWVab25lJyl9JywgIgogICAgICAgICAgICBmImVuZC5kYXRlVGltZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdlbmQnLCB7fSku"
    "Z2V0KCdkYXRlVGltZScpfScsICIKICAgICAgICAgICAgZiJlbmQudGltZVpvbmU9J3tldmVudF9wYXlsb2FkLmdldCgnZW5kJywg"
    "e30pLmdldCgndGltZVpvbmUnKX0nIgogICAgICAgICkKICAgICAgICB0cnk6CiAgICAgICAgICAgIGNyZWF0ZWQgPSBzZWxmLl9z"
    "ZXJ2aWNlLmV2ZW50cygpLmluc2VydChjYWxlbmRhcklkPXRhcmdldF9jYWxlbmRhcl9pZCwgYm9keT1ldmVudF9wYXlsb2FkKS5l"
    "eGVjdXRlKCkKICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gRXZlbnQgaW5zZXJ0IGNhbGwgc3VjY2VlZGVkLiIpCiAg"
    "ICAgICAgICAgIHJldHVybiBjcmVhdGVkLmdldCgiaWQiKSwgbGlua19lc3RhYmxpc2hlZAogICAgICAgIGV4Y2VwdCBHb29nbGVI"
    "dHRwRXJyb3IgYXMgYXBpX2V4OgogICAgICAgICAgICBhcGlfZGV0YWlsID0gIiIKICAgICAgICAgICAgaWYgaGFzYXR0cihhcGlf"
    "ZXgsICJjb250ZW50IikgYW5kIGFwaV9leC5jb250ZW50OgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAg"
    "IGFwaV9kZXRhaWwgPSBhcGlfZXguY29udGVudC5kZWNvZGUoInV0Zi04IiwgZXJyb3JzPSJyZXBsYWNlIikKICAgICAgICAgICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgYXBpX2RldGFpbCA9IHN0cihhcGlfZXguY29udGVudCkK"
    "ICAgICAgICAgICAgZGV0YWlsX21zZyA9IGYiR29vZ2xlIEFQSSBlcnJvcjoge2FwaV9leH0iCiAgICAgICAgICAgIGlmIGFwaV9k"
    "ZXRhaWw6CiAgICAgICAgICAgICAgICBkZXRhaWxfbXNnID0gZiJ7ZGV0YWlsX21zZ30gfCBBUEkgYm9keToge2FwaV9kZXRhaWx9"
    "IgogICAgICAgICAgICBwcmludChmIltHQ2FsXVtFUlJPUl0gRXZlbnQgaW5zZXJ0IGZhaWxlZDoge2RldGFpbF9tc2d9IikKICAg"
    "ICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKGRldGFpbF9tc2cpIGZyb20gYXBpX2V4CiAgICAgICAgZXhjZXB0IEV4Y2VwdGlv"
    "biBhcyBleDoKICAgICAgICAgICAgcHJpbnQoZiJbR0NhbF1bRVJST1JdIEV2ZW50IGluc2VydCBmYWlsZWQgd2l0aCB1bmV4cGVj"
    "dGVkIGVycm9yOiB7ZXh9IikKICAgICAgICAgICAgcmFpc2UKCiAgICBkZWYgY3JlYXRlX2V2ZW50X3dpdGhfcGF5bG9hZChzZWxm"
    "LCBldmVudF9wYXlsb2FkOiBkaWN0LCBjYWxlbmRhcl9pZDogc3RyID0gInByaW1hcnkiKToKICAgICAgICBpZiBub3QgaXNpbnN0"
    "YW5jZShldmVudF9wYXlsb2FkLCBkaWN0KToKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiR29vZ2xlIGV2ZW50IHBheWxv"
    "YWQgbXVzdCBiZSBhIGRpY3Rpb25hcnkuIikKICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gRmFsc2UKICAgICAgICBpZiBzZWxm"
    "Ll9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKICAg"
    "ICAgICBjcmVhdGVkID0gc2VsZi5fc2VydmljZS5ldmVudHMoKS5pbnNlcnQoY2FsZW5kYXJJZD0oY2FsZW5kYXJfaWQgb3IgInBy"
    "aW1hcnkiKSwgYm9keT1ldmVudF9wYXlsb2FkKS5leGVjdXRlKCkKICAgICAgICByZXR1cm4gY3JlYXRlZC5nZXQoImlkIiksIGxp"
    "bmtfZXN0YWJsaXNoZWQKCiAgICBkZWYgbGlzdF9wcmltYXJ5X2V2ZW50cyhzZWxmLAogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIHRpbWVfbWluOiBzdHIgPSBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIHN5bmNfdG9rZW46IHN0ciA9IE5v"
    "bmUsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgbWF4X3Jlc3VsdHM6IGludCA9IDI1MDApOgogICAgICAgICIiIgogICAg"
    "ICAgIEZldGNoIGNhbGVuZGFyIGV2ZW50cyB3aXRoIHBhZ2luYXRpb24gYW5kIHN5bmNUb2tlbiBzdXBwb3J0LgogICAgICAgIFJl"
    "dHVybnMgKGV2ZW50c19saXN0LCBuZXh0X3N5bmNfdG9rZW4pLgoKICAgICAgICBzeW5jX3Rva2VuIG1vZGU6IGluY3JlbWVudGFs"
    "IOKAlCByZXR1cm5zIE9OTFkgY2hhbmdlcyAoYWRkcy9lZGl0cy9jYW5jZWxzKS4KICAgICAgICB0aW1lX21pbiBtb2RlOiAgIGZ1"
    "bGwgc3luYyBmcm9tIGEgZGF0ZS4KICAgICAgICBCb3RoIHVzZSBzaG93RGVsZXRlZD1UcnVlIHNvIGNhbmNlbGxhdGlvbnMgY29t"
    "ZSB0aHJvdWdoLgogICAgICAgICIiIgogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgc2VsZi5f"
    "YnVpbGRfc2VydmljZSgpCgogICAgICAgIGlmIHN5bmNfdG9rZW46CiAgICAgICAgICAgIHF1ZXJ5ID0gewogICAgICAgICAgICAg"
    "ICAgImNhbGVuZGFySWQiOiAicHJpbWFyeSIsCiAgICAgICAgICAgICAgICAic2luZ2xlRXZlbnRzIjogVHJ1ZSwKICAgICAgICAg"
    "ICAgICAgICJzaG93RGVsZXRlZCI6IFRydWUsCiAgICAgICAgICAgICAgICAic3luY1Rva2VuIjogc3luY190b2tlbiwKICAgICAg"
    "ICAgICAgfQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHF1ZXJ5ID0gewogICAgICAgICAgICAgICAgImNhbGVuZGFySWQiOiAi"
    "cHJpbWFyeSIsCiAgICAgICAgICAgICAgICAic2luZ2xlRXZlbnRzIjogVHJ1ZSwKICAgICAgICAgICAgICAgICJzaG93RGVsZXRl"
    "ZCI6IFRydWUsCiAgICAgICAgICAgICAgICAibWF4UmVzdWx0cyI6IDI1MCwKICAgICAgICAgICAgICAgICJvcmRlckJ5IjogInN0"
    "YXJ0VGltZSIsCiAgICAgICAgICAgIH0KICAgICAgICAgICAgaWYgdGltZV9taW46CiAgICAgICAgICAgICAgICBxdWVyeVsidGlt"
    "ZU1pbiJdID0gdGltZV9taW4KCiAgICAgICAgYWxsX2V2ZW50cyA9IFtdCiAgICAgICAgbmV4dF9zeW5jX3Rva2VuID0gTm9uZQog"
    "ICAgICAgIHdoaWxlIFRydWU6CiAgICAgICAgICAgIHJlc3BvbnNlID0gc2VsZi5fc2VydmljZS5ldmVudHMoKS5saXN0KCoqcXVl"
    "cnkpLmV4ZWN1dGUoKQogICAgICAgICAgICBhbGxfZXZlbnRzLmV4dGVuZChyZXNwb25zZS5nZXQoIml0ZW1zIiwgW10pKQogICAg"
    "ICAgICAgICBuZXh0X3N5bmNfdG9rZW4gPSByZXNwb25zZS5nZXQoIm5leHRTeW5jVG9rZW4iKQogICAgICAgICAgICBwYWdlX3Rv"
    "a2VuID0gcmVzcG9uc2UuZ2V0KCJuZXh0UGFnZVRva2VuIikKICAgICAgICAgICAgaWYgbm90IHBhZ2VfdG9rZW46CiAgICAgICAg"
    "ICAgICAgICBicmVhawogICAgICAgICAgICBxdWVyeS5wb3AoInN5bmNUb2tlbiIsIE5vbmUpCiAgICAgICAgICAgIHF1ZXJ5WyJw"
    "YWdlVG9rZW4iXSA9IHBhZ2VfdG9rZW4KCiAgICAgICAgcmV0dXJuIGFsbF9ldmVudHMsIG5leHRfc3luY190b2tlbgoKICAgIGRl"
    "ZiBnZXRfZXZlbnQoc2VsZiwgZ29vZ2xlX2V2ZW50X2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBnb29nbGVfZXZlbnRfaWQ6CiAg"
    "ICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25lOgogICAgICAgICAgICBzZWxmLl9i"
    "dWlsZF9zZXJ2aWNlKCkKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVybiBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmdldChj"
    "YWxlbmRhcklkPSJwcmltYXJ5IiwgZXZlbnRJZD1nb29nbGVfZXZlbnRfaWQpLmV4ZWN1dGUoKQogICAgICAgIGV4Y2VwdCBHb29n"
    "bGVIdHRwRXJyb3IgYXMgYXBpX2V4OgogICAgICAgICAgICBjb2RlID0gZ2V0YXR0cihnZXRhdHRyKGFwaV9leCwgInJlc3AiLCBO"
    "b25lKSwgInN0YXR1cyIsIE5vbmUpCiAgICAgICAgICAgIGlmIGNvZGUgaW4gKDQwNCwgNDEwKToKICAgICAgICAgICAgICAgIHJl"
    "dHVybiBOb25lCiAgICAgICAgICAgIHJhaXNlCgogICAgZGVmIGRlbGV0ZV9ldmVudF9mb3JfdGFzayhzZWxmLCBnb29nbGVfZXZl"
    "bnRfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGdvb2dsZV9ldmVudF9pZDoKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigi"
    "R29vZ2xlIGV2ZW50IGlkIGlzIG1pc3Npbmc7IGNhbm5vdCBkZWxldGUgZXZlbnQuIikKCiAgICAgICAgaWYgc2VsZi5fc2Vydmlj"
    "ZSBpcyBOb25lOgogICAgICAgICAgICBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKCiAgICAgICAgdGFyZ2V0X2NhbGVuZGFyX2lkID0g"
    "InByaW1hcnkiCiAgICAgICAgc2VsZi5fc2VydmljZS5ldmVudHMoKS5kZWxldGUoY2FsZW5kYXJJZD10YXJnZXRfY2FsZW5kYXJf"
    "aWQsIGV2ZW50SWQ9Z29vZ2xlX2V2ZW50X2lkKS5leGVjdXRlKCkKCgpjbGFzcyBHb29nbGVEb2NzRHJpdmVTZXJ2aWNlOgogICAg"
    "ZGVmIF9faW5pdF9fKHNlbGYsIGNyZWRlbnRpYWxzX3BhdGg6IFBhdGgsIHRva2VuX3BhdGg6IFBhdGgsIGxvZ2dlcj1Ob25lKToK"
    "ICAgICAgICBzZWxmLmNyZWRlbnRpYWxzX3BhdGggPSBjcmVkZW50aWFsc19wYXRoCiAgICAgICAgc2VsZi50b2tlbl9wYXRoID0g"
    "dG9rZW5fcGF0aAogICAgICAgIHNlbGYuX2RyaXZlX3NlcnZpY2UgPSBOb25lCiAgICAgICAgc2VsZi5fZG9jc19zZXJ2aWNlID0g"
    "Tm9uZQogICAgICAgIHNlbGYuX2xvZ2dlciA9IGxvZ2dlcgoKICAgIGRlZiBfbG9nKHNlbGYsIG1lc3NhZ2U6IHN0ciwgbGV2ZWw6"
    "IHN0ciA9ICJJTkZPIik6CiAgICAgICAgaWYgY2FsbGFibGUoc2VsZi5fbG9nZ2VyKToKICAgICAgICAgICAgc2VsZi5fbG9nZ2Vy"
    "KG1lc3NhZ2UsIGxldmVsPWxldmVsKQoKICAgIGRlZiBfcGVyc2lzdF90b2tlbihzZWxmLCBjcmVkcyk6CiAgICAgICAgc2VsZi50"
    "b2tlbl9wYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgc2VsZi50b2tlbl9wYXRo"
    "LndyaXRlX3RleHQoY3JlZHMudG9fanNvbigpLCBlbmNvZGluZz0idXRmLTgiKQoKICAgIGRlZiBfYXV0aGVudGljYXRlKHNlbGYp"
    "OgogICAgICAgIHNlbGYuX2xvZygiRHJpdmUgYXV0aCBzdGFydC4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgc2VsZi5fbG9nKCJE"
    "b2NzIGF1dGggc3RhcnQuIiwgbGV2ZWw9IklORk8iKQoKICAgICAgICBpZiBub3QgR09PR0xFX0FQSV9PSzoKICAgICAgICAgICAg"
    "ZGV0YWlsID0gR09PR0xFX0lNUE9SVF9FUlJPUiBvciAidW5rbm93biBJbXBvcnRFcnJvciIKICAgICAgICAgICAgcmFpc2UgUnVu"
    "dGltZUVycm9yKGYiTWlzc2luZyBHb29nbGUgUHl0aG9uIGRlcGVuZGVuY3k6IHtkZXRhaWx9IikKICAgICAgICBpZiBub3Qgc2Vs"
    "Zi5jcmVkZW50aWFsc19wYXRoLmV4aXN0cygpOgogICAgICAgICAgICByYWlzZSBGaWxlTm90Rm91bmRFcnJvcigKICAgICAgICAg"
    "ICAgICAgIGYiR29vZ2xlIGNyZWRlbnRpYWxzL2F1dGggY29uZmlndXJhdGlvbiBub3QgZm91bmQ6IHtzZWxmLmNyZWRlbnRpYWxz"
    "X3BhdGh9IgogICAgICAgICAgICApCgogICAgICAgIGNyZWRzID0gTm9uZQogICAgICAgIGlmIHNlbGYudG9rZW5fcGF0aC5leGlz"
    "dHMoKToKICAgICAgICAgICAgY3JlZHMgPSBHb29nbGVDcmVkZW50aWFscy5mcm9tX2F1dGhvcml6ZWRfdXNlcl9maWxlKHN0cihz"
    "ZWxmLnRva2VuX3BhdGgpLCBHT09HTEVfU0NPUEVTKQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3JlZHMudmFsaWQgYW5kIG5vdCBj"
    "cmVkcy5oYXNfc2NvcGVzKEdPT0dMRV9TQ09QRVMpOgogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoR09PR0xFX1NDT1BF"
    "X1JFQVVUSF9NU0cpCgogICAgICAgIGlmIGNyZWRzIGFuZCBjcmVkcy5leHBpcmVkIGFuZCBjcmVkcy5yZWZyZXNoX3Rva2VuOgog"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjcmVkcy5yZWZyZXNoKEdvb2dsZUF1dGhSZXF1ZXN0KCkpCiAgICAgICAg"
    "ICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAg"
    "ICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKAogICAgICAgICAgICAgICAgICAgIGYiR29vZ2xlIHRva2VuIHJlZnJlc2gg"
    "ZmFpbGVkIGFmdGVyIHNjb3BlIGV4cGFuc2lvbjoge2V4fS4ge0dPT0dMRV9TQ09QRV9SRUFVVEhfTVNHfSIKICAgICAgICAgICAg"
    "ICAgICkgZnJvbSBleAoKICAgICAgICBpZiBub3QgY3JlZHMgb3Igbm90IGNyZWRzLnZhbGlkOgogICAgICAgICAgICBzZWxmLl9s"
    "b2coIlN0YXJ0aW5nIE9BdXRoIGZsb3cgZm9yIEdvb2dsZSBEcml2ZS9Eb2NzLiIsIGxldmVsPSJJTkZPIikKICAgICAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICAgICAgZmxvdyA9IEluc3RhbGxlZEFwcEZsb3cuZnJvbV9jbGllbnRfc2VjcmV0c19maWxlKHN0cihz"
    "ZWxmLmNyZWRlbnRpYWxzX3BhdGgpLCBHT09HTEVfU0NPUEVTKQogICAgICAgICAgICAgICAgY3JlZHMgPSBmbG93LnJ1bl9sb2Nh"
    "bF9zZXJ2ZXIoCiAgICAgICAgICAgICAgICAgICAgcG9ydD0wLAogICAgICAgICAgICAgICAgICAgIG9wZW5fYnJvd3Nlcj1UcnVl"
    "LAogICAgICAgICAgICAgICAgICAgIGF1dGhvcml6YXRpb25fcHJvbXB0X21lc3NhZ2U9KAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAiT3BlbiB0aGlzIFVSTCBpbiB5b3VyIGJyb3dzZXIgdG8gYXV0aG9yaXplIHRoaXMgYXBwbGljYXRpb246XG57dXJsfSIKICAg"
    "ICAgICAgICAgICAgICAgICApLAogICAgICAgICAgICAgICAgICAgIHN1Y2Nlc3NfbWVzc2FnZT0iQXV0aGVudGljYXRpb24gY29t"
    "cGxldGUuIFlvdSBtYXkgY2xvc2UgdGhpcyB3aW5kb3cuIiwKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIG5v"
    "dCBjcmVkczoKICAgICAgICAgICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoIk9BdXRoIGZsb3cgcmV0dXJuZWQgbm8gY3Jl"
    "ZGVudGlhbHMgb2JqZWN0LiIpCiAgICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAgICAg"
    "ICAgc2VsZi5fbG9nKCJbR0NhbF1bREVCVUddIHRva2VuLmpzb24gd3JpdHRlbiBzdWNjZXNzZnVsbHkuIiwgbGV2ZWw9IklORk8i"
    "KQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fbG9nKGYiT0F1dGggZmxv"
    "dyBmYWlsZWQ6IHt0eXBlKGV4KS5fX25hbWVfX306IHtleH0iLCBsZXZlbD0iRVJST1IiKQogICAgICAgICAgICAgICAgcmFpc2UK"
    "CiAgICAgICAgcmV0dXJuIGNyZWRzCgogICAgZGVmIGVuc3VyZV9zZXJ2aWNlcyhzZWxmKToKICAgICAgICBpZiBzZWxmLl9kcml2"
    "ZV9zZXJ2aWNlIGlzIG5vdCBOb25lIGFuZCBzZWxmLl9kb2NzX3NlcnZpY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHJldHVy"
    "bgogICAgICAgIHRyeToKICAgICAgICAgICAgY3JlZHMgPSBzZWxmLl9hdXRoZW50aWNhdGUoKQogICAgICAgICAgICBzZWxmLl9k"
    "cml2ZV9zZXJ2aWNlID0gZ29vZ2xlX2J1aWxkKCJkcml2ZSIsICJ2MyIsIGNyZWRlbnRpYWxzPWNyZWRzKQogICAgICAgICAgICBz"
    "ZWxmLl9kb2NzX3NlcnZpY2UgPSBnb29nbGVfYnVpbGQoImRvY3MiLCAidjEiLCBjcmVkZW50aWFscz1jcmVkcykKICAgICAgICAg"
    "ICAgc2VsZi5fbG9nKCJEcml2ZSBhdXRoIHN1Y2Nlc3MuIiwgbGV2ZWw9IklORk8iKQogICAgICAgICAgICBzZWxmLl9sb2coIkRv"
    "Y3MgYXV0aCBzdWNjZXNzLiIsIGxldmVsPSJJTkZPIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAg"
    "ICBzZWxmLl9sb2coZiJEcml2ZSBhdXRoIGZhaWx1cmU6IHtleH0iLCBsZXZlbD0iRVJST1IiKQogICAgICAgICAgICBzZWxmLl9s"
    "b2coZiJEb2NzIGF1dGggZmFpbHVyZToge2V4fSIsIGxldmVsPSJFUlJPUiIpCiAgICAgICAgICAgIHJhaXNlCgogICAgZGVmIGxp"
    "c3RfZm9sZGVyX2l0ZW1zKHNlbGYsIGZvbGRlcl9pZDogc3RyID0gInJvb3QiLCBwYWdlX3NpemU6IGludCA9IDEwMCk6CiAgICAg"
    "ICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHNhZmVfZm9sZGVyX2lkID0gKGZvbGRlcl9pZCBvciAicm9vdCIpLnN0"
    "cmlwKCkgb3IgInJvb3QiCiAgICAgICAgc2VsZi5fbG9nKGYiRHJpdmUgZmlsZSBsaXN0IGZldGNoIHN0YXJ0ZWQuIGZvbGRlcl9p"
    "ZD17c2FmZV9mb2xkZXJfaWR9IiwgbGV2ZWw9IklORk8iKQogICAgICAgIHJlc3BvbnNlID0gc2VsZi5fZHJpdmVfc2VydmljZS5m"
    "aWxlcygpLmxpc3QoCiAgICAgICAgICAgIHE9ZiIne3NhZmVfZm9sZGVyX2lkfScgaW4gcGFyZW50cyBhbmQgdHJhc2hlZD1mYWxz"
    "ZSIsCiAgICAgICAgICAgIHBhZ2VTaXplPW1heCgxLCBtaW4oaW50KHBhZ2Vfc2l6ZSBvciAxMDApLCAyMDApKSwKICAgICAgICAg"
    "ICAgb3JkZXJCeT0iZm9sZGVyLG5hbWUsbW9kaWZpZWRUaW1lIGRlc2MiLAogICAgICAgICAgICBmaWVsZHM9KAogICAgICAgICAg"
    "ICAgICAgImZpbGVzKCIKICAgICAgICAgICAgICAgICJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVkVGltZSx3ZWJWaWV3TGluayxw"
    "YXJlbnRzLHNpemUsIgogICAgICAgICAgICAgICAgImxhc3RNb2RpZnlpbmdVc2VyKGRpc3BsYXlOYW1lLGVtYWlsQWRkcmVzcyki"
    "CiAgICAgICAgICAgICAgICAiKSIKICAgICAgICAgICAgKSwKICAgICAgICApLmV4ZWN1dGUoKQogICAgICAgIGZpbGVzID0gcmVz"
    "cG9uc2UuZ2V0KCJmaWxlcyIsIFtdKQogICAgICAgIGZvciBpdGVtIGluIGZpbGVzOgogICAgICAgICAgICBtaW1lID0gKGl0ZW0u"
    "Z2V0KCJtaW1lVHlwZSIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgICAgIGl0ZW1bImlzX2ZvbGRlciJdID0gbWltZSA9PSAiYXBw"
    "bGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmZvbGRlciIKICAgICAgICAgICAgaXRlbVsiaXNfZ29vZ2xlX2RvYyJdID0gbWltZSA9"
    "PSAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IgogICAgICAgIHNlbGYuX2xvZyhmIkRyaXZlIGl0ZW1zIHJl"
    "dHVybmVkOiB7bGVuKGZpbGVzKX0gZm9sZGVyX2lkPXtzYWZlX2ZvbGRlcl9pZH0iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgcmV0"
    "dXJuIGZpbGVzCgogICAgZGVmIGdldF9kb2NfcHJldmlldyhzZWxmLCBkb2NfaWQ6IHN0ciwgbWF4X2NoYXJzOiBpbnQgPSAxODAw"
    "KToKICAgICAgICBpZiBub3QgZG9jX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJEb2N1bWVudCBpZCBpcyByZXF1"
    "aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBkb2MgPSBzZWxmLl9kb2NzX3NlcnZpY2UuZG9j"
    "dW1lbnRzKCkuZ2V0KGRvY3VtZW50SWQ9ZG9jX2lkKS5leGVjdXRlKCkKICAgICAgICB0aXRsZSA9IGRvYy5nZXQoInRpdGxlIikg"
    "b3IgIlVudGl0bGVkIgogICAgICAgIGJvZHkgPSBkb2MuZ2V0KCJib2R5Iiwge30pLmdldCgiY29udGVudCIsIFtdKQogICAgICAg"
    "IGNodW5rcyA9IFtdCiAgICAgICAgZm9yIGJsb2NrIGluIGJvZHk6CiAgICAgICAgICAgIHBhcmFncmFwaCA9IGJsb2NrLmdldCgi"
    "cGFyYWdyYXBoIikKICAgICAgICAgICAgaWYgbm90IHBhcmFncmFwaDoKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAg"
    "ICAgIGVsZW1lbnRzID0gcGFyYWdyYXBoLmdldCgiZWxlbWVudHMiLCBbXSkKICAgICAgICAgICAgZm9yIGVsIGluIGVsZW1lbnRz"
    "OgogICAgICAgICAgICAgICAgcnVuID0gZWwuZ2V0KCJ0ZXh0UnVuIikKICAgICAgICAgICAgICAgIGlmIG5vdCBydW46CiAgICAg"
    "ICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgICAgIHRleHQgPSAocnVuLmdldCgiY29udGVudCIpIG9yICIiKS5y"
    "ZXBsYWNlKCJceDBiIiwgIlxuIikKICAgICAgICAgICAgICAgIGlmIHRleHQ6CiAgICAgICAgICAgICAgICAgICAgY2h1bmtzLmFw"
    "cGVuZCh0ZXh0KQogICAgICAgIHBhcnNlZCA9ICIiLmpvaW4oY2h1bmtzKS5zdHJpcCgpCiAgICAgICAgaWYgbGVuKHBhcnNlZCkg"
    "PiBtYXhfY2hhcnM6CiAgICAgICAgICAgIHBhcnNlZCA9IHBhcnNlZFs6bWF4X2NoYXJzXS5yc3RyaXAoKSArICLigKYiCiAgICAg"
    "ICAgcmV0dXJuIHsKICAgICAgICAgICAgInRpdGxlIjogdGl0bGUsCiAgICAgICAgICAgICJkb2N1bWVudF9pZCI6IGRvY19pZCwK"
    "ICAgICAgICAgICAgInJldmlzaW9uX2lkIjogZG9jLmdldCgicmV2aXNpb25JZCIpLAogICAgICAgICAgICAicHJldmlld190ZXh0"
    "IjogcGFyc2VkIG9yICJbTm8gdGV4dCBjb250ZW50IHJldHVybmVkIGZyb20gRG9jcyBBUEkuXSIsCiAgICAgICAgfQoKICAgIGRl"
    "ZiBjcmVhdGVfZG9jKHNlbGYsIHRpdGxlOiBzdHIgPSAiTmV3IEdyaW1WZWlsZSBSZWNvcmQiLCBwYXJlbnRfZm9sZGVyX2lkOiBz"
    "dHIgPSAicm9vdCIpOgogICAgICAgIHNhZmVfdGl0bGUgPSAodGl0bGUgb3IgIk5ldyBHcmltVmVpbGUgUmVjb3JkIikuc3RyaXAo"
    "KSBvciAiTmV3IEdyaW1WZWlsZSBSZWNvcmQiCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHNhZmVfcGFy"
    "ZW50X2lkID0gKHBhcmVudF9mb2xkZXJfaWQgb3IgInJvb3QiKS5zdHJpcCgpIG9yICJyb290IgogICAgICAgIGNyZWF0ZWQgPSBz"
    "ZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuY3JlYXRlKAogICAgICAgICAgICBib2R5PXsKICAgICAgICAgICAgICAgICJuYW1l"
    "Ijogc2FmZV90aXRsZSwKICAgICAgICAgICAgICAgICJtaW1lVHlwZSI6ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZG9j"
    "dW1lbnQiLAogICAgICAgICAgICAgICAgInBhcmVudHMiOiBbc2FmZV9wYXJlbnRfaWRdLAogICAgICAgICAgICB9LAogICAgICAg"
    "ICAgICBmaWVsZHM9ImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVudHMiLAogICAgICAgICku"
    "ZXhlY3V0ZSgpCiAgICAgICAgZG9jX2lkID0gY3JlYXRlZC5nZXQoImlkIikKICAgICAgICBtZXRhID0gc2VsZi5nZXRfZmlsZV9t"
    "ZXRhZGF0YShkb2NfaWQpIGlmIGRvY19pZCBlbHNlIHt9CiAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgImlkIjogZG9jX2lk"
    "LAogICAgICAgICAgICAibmFtZSI6IG1ldGEuZ2V0KCJuYW1lIikgb3Igc2FmZV90aXRsZSwKICAgICAgICAgICAgIm1pbWVUeXBl"
    "IjogbWV0YS5nZXQoIm1pbWVUeXBlIikgb3IgImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5kb2N1bWVudCIsCiAgICAgICAg"
    "ICAgICJtb2RpZmllZFRpbWUiOiBtZXRhLmdldCgibW9kaWZpZWRUaW1lIiksCiAgICAgICAgICAgICJ3ZWJWaWV3TGluayI6IG1l"
    "dGEuZ2V0KCJ3ZWJWaWV3TGluayIpLAogICAgICAgICAgICAicGFyZW50cyI6IG1ldGEuZ2V0KCJwYXJlbnRzIikgb3IgW3NhZmVf"
    "cGFyZW50X2lkXSwKICAgICAgICB9CgogICAgZGVmIGNyZWF0ZV9mb2xkZXIoc2VsZiwgbmFtZTogc3RyID0gIk5ldyBGb2xkZXIi"
    "LCBwYXJlbnRfZm9sZGVyX2lkOiBzdHIgPSAicm9vdCIpOgogICAgICAgIHNhZmVfbmFtZSA9IChuYW1lIG9yICJOZXcgRm9sZGVy"
    "Iikuc3RyaXAoKSBvciAiTmV3IEZvbGRlciIKICAgICAgICBzYWZlX3BhcmVudF9pZCA9IChwYXJlbnRfZm9sZGVyX2lkIG9yICJy"
    "b290Iikuc3RyaXAoKSBvciAicm9vdCIKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgY3JlYXRlZCA9IHNl"
    "bGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5jcmVhdGUoCiAgICAgICAgICAgIGJvZHk9ewogICAgICAgICAgICAgICAgIm5hbWUi"
    "OiBzYWZlX25hbWUsCiAgICAgICAgICAgICAgICAibWltZVR5cGUiOiAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmZvbGRl"
    "ciIsCiAgICAgICAgICAgICAgICAicGFyZW50cyI6IFtzYWZlX3BhcmVudF9pZF0sCiAgICAgICAgICAgIH0sCiAgICAgICAgICAg"
    "IGZpZWxkcz0iaWQsbmFtZSxtaW1lVHlwZSxtb2RpZmllZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyIsCiAgICAgICAgKS5leGVj"
    "dXRlKCkKICAgICAgICByZXR1cm4gY3JlYXRlZAoKICAgIGRlZiBnZXRfZmlsZV9tZXRhZGF0YShzZWxmLCBmaWxlX2lkOiBzdHIp"
    "OgogICAgICAgIGlmIG5vdCBmaWxlX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlkIGlzIHJlcXVpcmVk"
    "LiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHJldHVybiBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVz"
    "KCkuZ2V0KAogICAgICAgICAgICBmaWxlSWQ9ZmlsZV9pZCwKICAgICAgICAgICAgZmllbGRzPSJpZCxuYW1lLG1pbWVUeXBlLG1v"
    "ZGlmaWVkVGltZSx3ZWJWaWV3TGluayxwYXJlbnRzLHNpemUiLAogICAgICAgICkuZXhlY3V0ZSgpCgogICAgZGVmIGdldF9kb2Nf"
    "bWV0YWRhdGEoc2VsZiwgZG9jX2lkOiBzdHIpOgogICAgICAgIHJldHVybiBzZWxmLmdldF9maWxlX21ldGFkYXRhKGRvY19pZCkK"
    "CiAgICBkZWYgZGVsZXRlX2l0ZW0oc2VsZiwgZmlsZV9pZDogc3RyKToKICAgICAgICBpZiBub3QgZmlsZV9pZDoKICAgICAgICAg"
    "ICAgcmFpc2UgVmFsdWVFcnJvcigiRmlsZSBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkK"
    "ICAgICAgICBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuZGVsZXRlKGZpbGVJZD1maWxlX2lkKS5leGVjdXRlKCkKCiAgICBk"
    "ZWYgZGVsZXRlX2RvYyhzZWxmLCBkb2NfaWQ6IHN0cik6CiAgICAgICAgc2VsZi5kZWxldGVfaXRlbShkb2NfaWQpCgogICAgZGVm"
    "IGV4cG9ydF9kb2NfdGV4dChzZWxmLCBkb2NfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGRvY19pZDoKICAgICAgICAgICAgcmFp"
    "c2UgVmFsdWVFcnJvcigiRG9jdW1lbnQgaWQgaXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAg"
    "ICAgICAgcGF5bG9hZCA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5leHBvcnQoCiAgICAgICAgICAgIGZpbGVJZD1kb2Nf"
    "aWQsCiAgICAgICAgICAgIG1pbWVUeXBlPSJ0ZXh0L3BsYWluIiwKICAgICAgICApLmV4ZWN1dGUoKQogICAgICAgIGlmIGlzaW5z"
    "dGFuY2UocGF5bG9hZCwgYnl0ZXMpOgogICAgICAgICAgICByZXR1cm4gcGF5bG9hZC5kZWNvZGUoInV0Zi04IiwgZXJyb3JzPSJy"
    "ZXBsYWNlIikKICAgICAgICByZXR1cm4gc3RyKHBheWxvYWQgb3IgIiIpCgogICAgZGVmIGRvd25sb2FkX2ZpbGVfYnl0ZXMoc2Vs"
    "ZiwgZmlsZV9pZDogc3RyKToKICAgICAgICBpZiBub3QgZmlsZV9pZDoKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiRmls"
    "ZSBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICByZXR1cm4gc2VsZi5fZHJp"
    "dmVfc2VydmljZS5maWxlcygpLmdldF9tZWRpYShmaWxlSWQ9ZmlsZV9pZCkuZXhlY3V0ZSgpCgoKCgojIOKUgOKUgCBQQVNTIDMg"
    "Q09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQWxsIHdvcmtlciB0aHJlYWRzIGRlZmluZWQuIEFsbCBnZW5l"
    "cmF0aW9uIGlzIHN0cmVhbWluZy4KIyBObyBibG9ja2luZyBjYWxscyBvbiBtYWluIHRocmVhZCBhbnl3aGVyZSBpbiB0aGlzIGZp"
    "bGUuCiMKIyBOZXh0OiBQYXNzIDQg4oCUIE1lbW9yeSAmIFN0b3JhZ2UKIyAoTWVtb3J5TWFuYWdlciwgU2Vzc2lvbk1hbmFnZXIs"
    "IExlc3NvbnNMZWFybmVkREIsIFRhc2tNYW5hZ2VyKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyA0"
    "OiBNRU1PUlkgJiBTVE9SQUdFCiMKIyBTeXN0ZW1zIGRlZmluZWQgaGVyZToKIyAgIERlcGVuZGVuY3lDaGVja2VyICAg4oCUIHZh"
    "bGlkYXRlcyBhbGwgcmVxdWlyZWQgcGFja2FnZXMgb24gc3RhcnR1cAojICAgTWVtb3J5TWFuYWdlciAgICAgICDigJQgSlNPTkwg"
    "bWVtb3J5IHJlYWQvd3JpdGUvc2VhcmNoCiMgICBTZXNzaW9uTWFuYWdlciAgICAgIOKAlCBhdXRvLXNhdmUsIGxvYWQsIGNvbnRl"
    "eHQgaW5qZWN0aW9uLCBzZXNzaW9uIGluZGV4CiMgICBMZXNzb25zTGVhcm5lZERCICAgIOKAlCBMU0wgRm9yYmlkZGVuIFJ1bGVz"
    "ZXQgKyBjb2RlIGxlc3NvbnMga25vd2xlZGdlIGJhc2UKIyAgIFRhc2tNYW5hZ2VyICAgICAgICAg4oCUIHRhc2svcmVtaW5kZXIg"
    "Q1JVRCwgZHVlLWV2ZW50IGRldGVjdGlvbgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKCiMg4pSA4pSAIERFUEVOREVOQ1kgQ0hFQ0tFUiDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKY2xhc3MgRGVwZW5kZW5jeUNoZWNrZXI6CiAgICAiIiIKICAgIFZhbGlkYXRlcyBhbGwgcmVxdWlyZWQg"
    "YW5kIG9wdGlvbmFsIHBhY2thZ2VzIG9uIHN0YXJ0dXAuCiAgICBSZXR1cm5zIGEgbGlzdCBvZiBzdGF0dXMgbWVzc2FnZXMgZm9y"
    "IHRoZSBEaWFnbm9zdGljcyB0YWIuCiAgICBTaG93cyBhIGJsb2NraW5nIGVycm9yIGRpYWxvZyBmb3IgYW55IGNyaXRpY2FsIG1p"
    "c3NpbmcgZGVwZW5kZW5jeS4KICAgICIiIgoKICAgICMgKHBhY2thZ2VfbmFtZSwgaW1wb3J0X25hbWUsIGNyaXRpY2FsLCBpbnN0"
    "YWxsX2hpbnQpCiAgICBQQUNLQUdFUyA9IFsKICAgICAgICAoIlB5U2lkZTYiLCAgICAgICAgICAgICAgICAgICAiUHlTaWRlNiIs"
    "ICAgICAgICAgICAgICBUcnVlLAogICAgICAgICAicGlwIGluc3RhbGwgUHlTaWRlNiIpLAogICAgICAgICgibG9ndXJ1IiwgICAg"
    "ICAgICAgICAgICAgICAgICJsb2d1cnUiLCAgICAgICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBsb2d1cnUi"
    "KSwKICAgICAgICAoImFwc2NoZWR1bGVyIiwgICAgICAgICAgICAgICAiYXBzY2hlZHVsZXIiLCAgICAgICAgICBUcnVlLAogICAg"
    "ICAgICAicGlwIGluc3RhbGwgYXBzY2hlZHVsZXIiKSwKICAgICAgICAoInB5Z2FtZSIsICAgICAgICAgICAgICAgICAgICAicHln"
    "YW1lIiwgICAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5Z2FtZSAgKG5lZWRlZCBmb3Igc291bmQp"
    "IiksCiAgICAgICAgKCJweXdpbjMyIiwgICAgICAgICAgICAgICAgICAgIndpbjMyY29tIiwgICAgICAgICAgICAgRmFsc2UsCiAg"
    "ICAgICAgICJwaXAgaW5zdGFsbCBweXdpbjMyICAobmVlZGVkIGZvciBkZXNrdG9wIHNob3J0Y3V0KSIpLAogICAgICAgICgicHN1"
    "dGlsIiwgICAgICAgICAgICAgICAgICAgICJwc3V0aWwiLCAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3Rh"
    "bGwgcHN1dGlsICAobmVlZGVkIGZvciBzeXN0ZW0gbW9uaXRvcmluZykiKSwKICAgICAgICAoInJlcXVlc3RzIiwgICAgICAgICAg"
    "ICAgICAgICAicmVxdWVzdHMiLCAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHJlcXVlc3RzIiksCiAg"
    "ICAgICAgKCJnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQiLCAgImdvb2dsZWFwaWNsaWVudCIsICAgICAgRmFsc2UsCiAgICAgICAg"
    "ICJwaXAgaW5zdGFsbCBnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQiKSwKICAgICAgICAoImdvb2dsZS1hdXRoLW9hdXRobGliIiwg"
    "ICAgICAiZ29vZ2xlX2F1dGhfb2F1dGhsaWIiLCBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGdvb2dsZS1hdXRoLW9hdXRo"
    "bGliIiksCiAgICAgICAgKCJnb29nbGUtYXV0aCIsICAgICAgICAgICAgICAgImdvb2dsZS5hdXRoIiwgICAgICAgICAgRmFsc2Us"
    "CiAgICAgICAgICJwaXAgaW5zdGFsbCBnb29nbGUtYXV0aCIpLAogICAgICAgICgidG9yY2giLCAgICAgICAgICAgICAgICAgICAg"
    "ICJ0b3JjaCIsICAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgdG9yY2ggIChvbmx5IG5lZWRlZCBm"
    "b3IgbG9jYWwgbW9kZWwpIiksCiAgICAgICAgKCJ0cmFuc2Zvcm1lcnMiLCAgICAgICAgICAgICAgInRyYW5zZm9ybWVycyIsICAg"
    "ICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCB0cmFuc2Zvcm1lcnMgIChvbmx5IG5lZWRlZCBmb3IgbG9jYWwgbW9k"
    "ZWwpIiksCiAgICAgICAgKCJweW52bWwiLCAgICAgICAgICAgICAgICAgICAgInB5bnZtbCIsICAgICAgICAgICAgICAgRmFsc2Us"
    "CiAgICAgICAgICJwaXAgaW5zdGFsbCBweW52bWwgIChvbmx5IG5lZWRlZCBmb3IgTlZJRElBIEdQVSBtb25pdG9yaW5nKSIpLAog"
    "ICAgXQoKICAgIEBjbGFzc21ldGhvZAogICAgZGVmIGNoZWNrKGNscykgLT4gdHVwbGVbbGlzdFtzdHJdLCBsaXN0W3N0cl1dOgog"
    "ICAgICAgICIiIgogICAgICAgIFJldHVybnMgKG1lc3NhZ2VzLCBjcml0aWNhbF9mYWlsdXJlcykuCiAgICAgICAgbWVzc2FnZXM6"
    "IGxpc3Qgb2YgIltERVBTXSBwYWNrYWdlIOKcky/inJcg4oCUIG5vdGUiIHN0cmluZ3MKICAgICAgICBjcml0aWNhbF9mYWlsdXJl"
    "czogbGlzdCBvZiBwYWNrYWdlcyB0aGF0IGFyZSBjcml0aWNhbCBhbmQgbWlzc2luZwogICAgICAgICIiIgogICAgICAgIGltcG9y"
    "dCBpbXBvcnRsaWIKICAgICAgICBtZXNzYWdlcyAgPSBbXQogICAgICAgIGNyaXRpY2FsICA9IFtdCgogICAgICAgIGZvciBwa2df"
    "bmFtZSwgaW1wb3J0X25hbWUsIGlzX2NyaXRpY2FsLCBoaW50IGluIGNscy5QQUNLQUdFUzoKICAgICAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICAgICAgaW1wb3J0bGliLmltcG9ydF9tb2R1bGUoaW1wb3J0X25hbWUpCiAgICAgICAgICAgICAgICBtZXNzYWdlcy5h"
    "cHBlbmQoZiJbREVQU10ge3BrZ19uYW1lfSDinJMiKQogICAgICAgICAgICBleGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAgICAg"
    "ICAgICBzdGF0dXMgPSAiQ1JJVElDQUwiIGlmIGlzX2NyaXRpY2FsIGVsc2UgIm9wdGlvbmFsIgogICAgICAgICAgICAgICAgbWVz"
    "c2FnZXMuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgIGYiW0RFUFNdIHtwa2dfbmFtZX0g4pyXICh7c3RhdHVzfSkg4oCUIHto"
    "aW50fSIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIGlzX2NyaXRpY2FsOgogICAgICAgICAgICAgICAgICAg"
    "IGNyaXRpY2FsLmFwcGVuZChwa2dfbmFtZSkKCiAgICAgICAgcmV0dXJuIG1lc3NhZ2VzLCBjcml0aWNhbAoKICAgIEBjbGFzc21l"
    "dGhvZAogICAgZGVmIGNoZWNrX29sbGFtYShjbHMpIC0+IHN0cjoKICAgICAgICAiIiJDaGVjayBpZiBPbGxhbWEgaXMgcnVubmlu"
    "Zy4gUmV0dXJucyBzdGF0dXMgc3RyaW5nLiIiIgogICAgICAgIHRyeToKICAgICAgICAgICAgcmVxICA9IHVybGxpYi5yZXF1ZXN0"
    "LlJlcXVlc3QoImh0dHA6Ly9sb2NhbGhvc3Q6MTE0MzQvYXBpL3RhZ3MiKQogICAgICAgICAgICByZXNwID0gdXJsbGliLnJlcXVl"
    "c3QudXJsb3BlbihyZXEsIHRpbWVvdXQ9MikKICAgICAgICAgICAgaWYgcmVzcC5zdGF0dXMgPT0gMjAwOgogICAgICAgICAgICAg"
    "ICAgcmV0dXJuICJbREVQU10gT2xsYW1hIOKckyDigJQgcnVubmluZyBvbiBsb2NhbGhvc3Q6MTE0MzQiCiAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgICAgIHJldHVybiAiW0RFUFNdIE9sbGFtYSDinJcg4oCUIG5vdCBydW5u"
    "aW5nIChvbmx5IG5lZWRlZCBmb3IgT2xsYW1hIG1vZGVsIHR5cGUpIgoKCiMg4pSA4pSAIE1FTU9SWSBNQU5BR0VSIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBNZW1vcnlNYW5hZ2VyOgogICAgIiIiCiAgICBIYW5kbGVzIGFsbCBKU09OTCBt"
    "ZW1vcnkgb3BlcmF0aW9ucy4KCiAgICBGaWxlcyBtYW5hZ2VkOgogICAgICAgIG1lbW9yaWVzL21lc3NhZ2VzLmpzb25sICAgICAg"
    "ICAg4oCUIGV2ZXJ5IG1lc3NhZ2UsIHRpbWVzdGFtcGVkCiAgICAgICAgbWVtb3JpZXMvbWVtb3JpZXMuanNvbmwgICAgICAgICDi"
    "gJQgZXh0cmFjdGVkIG1lbW9yeSByZWNvcmRzCiAgICAgICAgbWVtb3JpZXMvc3RhdGUuanNvbiAgICAgICAgICAgICDigJQgZW50"
    "aXR5IHN0YXRlCiAgICAgICAgbWVtb3JpZXMvaW5kZXguanNvbiAgICAgICAgICAgICDigJQgY291bnRzIGFuZCBtZXRhZGF0YQoK"
    "ICAgIE1lbW9yeSByZWNvcmRzIGhhdmUgdHlwZSBpbmZlcmVuY2UsIGtleXdvcmQgZXh0cmFjdGlvbiwgdGFnIGdlbmVyYXRpb24s"
    "CiAgICBuZWFyLWR1cGxpY2F0ZSBkZXRlY3Rpb24sIGFuZCByZWxldmFuY2Ugc2NvcmluZyBmb3IgY29udGV4dCBpbmplY3Rpb24u"
    "CiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgYmFzZSAgICAgICAgICAgICA9IGNmZ19wYXRoKCJtZW1v"
    "cmllcyIpCiAgICAgICAgc2VsZi5tZXNzYWdlc19wICA9IGJhc2UgLyAibWVzc2FnZXMuanNvbmwiCiAgICAgICAgc2VsZi5tZW1v"
    "cmllc19wICA9IGJhc2UgLyAibWVtb3JpZXMuanNvbmwiCiAgICAgICAgc2VsZi5zdGF0ZV9wICAgICA9IGJhc2UgLyAic3RhdGUu"
    "anNvbiIKICAgICAgICBzZWxmLmluZGV4X3AgICAgID0gYmFzZSAvICJpbmRleC5qc29uIgoKICAgICMg4pSA4pSAIFNUQVRFIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGxvYWRfc3RhdGUoc2VsZikgLT4gZGljdDoKICAgICAgICBpZiBub3Qgc2Vs"
    "Zi5zdGF0ZV9wLmV4aXN0cygpOgogICAgICAgICAgICByZXR1cm4gc2VsZi5fZGVmYXVsdF9zdGF0ZSgpCiAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICByZXR1cm4ganNvbi5sb2FkcyhzZWxmLnN0YXRlX3AucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpKQogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHJldHVybiBzZWxmLl9kZWZhdWx0X3N0YXRlKCkKCiAgICBkZWYgc2F2"
    "ZV9zdGF0ZShzZWxmLCBzdGF0ZTogZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxmLnN0YXRlX3Aud3JpdGVfdGV4dCgKICAgICAg"
    "ICAgICAganNvbi5kdW1wcyhzdGF0ZSwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiCiAgICAgICAgKQoKICAgIGRlZiBfZGVm"
    "YXVsdF9zdGF0ZShzZWxmKSAtPiBkaWN0OgogICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICJwZXJzb25hX25hbWUiOiAgICAg"
    "ICAgICAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJkZWNrX3ZlcnNpb24iOiAgICAgICAgICAgICBBUFBfVkVSU0lPTiwKICAg"
    "ICAgICAgICAgInNlc3Npb25fY291bnQiOiAgICAgICAgICAgIDAsCiAgICAgICAgICAgICJsYXN0X3N0YXJ0dXAiOiAgICAgICAg"
    "ICAgICBOb25lLAogICAgICAgICAgICAibGFzdF9zaHV0ZG93biI6ICAgICAgICAgICAgTm9uZSwKICAgICAgICAgICAgImxhc3Rf"
    "YWN0aXZlIjogICAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgICJ0b3RhbF9tZXNzYWdlcyI6ICAgICAgICAgICAwLAogICAg"
    "ICAgICAgICAidG90YWxfbWVtb3JpZXMiOiAgICAgICAgICAgMCwKICAgICAgICAgICAgImludGVybmFsX25hcnJhdGl2ZSI6ICAg"
    "ICAgIHt9LAogICAgICAgICAgICAidmFtcGlyZV9zdGF0ZV9hdF9zaHV0ZG93biI6IkRPUk1BTlQiLAogICAgICAgIH0KCiAgICAj"
    "IOKUgOKUgCBNRVNTQUdFUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBhcHBlbmRfbWVzc2FnZShzZWxmLCBzZXNzaW9uX2lkOiBz"
    "dHIsIHJvbGU6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgICBjb250ZW50OiBzdHIsIGVtb3Rpb246IHN0ciA9ICIiKSAtPiBk"
    "aWN0OgogICAgICAgIHJlY29yZCA9IHsKICAgICAgICAgICAgImlkIjogICAgICAgICBmIm1zZ197dXVpZC51dWlkNCgpLmhleFs6"
    "MTJdfSIsCiAgICAgICAgICAgICJ0aW1lc3RhbXAiOiAgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAic2Vzc2lvbl9pZCI6"
    "IHNlc3Npb25faWQsCiAgICAgICAgICAgICJwZXJzb25hIjogICAgREVDS19OQU1FLAogICAgICAgICAgICAicm9sZSI6ICAgICAg"
    "IHJvbGUsCiAgICAgICAgICAgICJjb250ZW50IjogICAgY29udGVudCwKICAgICAgICAgICAgImVtb3Rpb24iOiAgICBlbW90aW9u"
    "LAogICAgICAgIH0KICAgICAgICBhcHBlbmRfanNvbmwoc2VsZi5tZXNzYWdlc19wLCByZWNvcmQpCiAgICAgICAgcmV0dXJuIHJl"
    "Y29yZAoKICAgIGRlZiBsb2FkX3JlY2VudF9tZXNzYWdlcyhzZWxmLCBsaW1pdDogaW50ID0gMjApIC0+IGxpc3RbZGljdF06CiAg"
    "ICAgICAgcmV0dXJuIHJlYWRfanNvbmwoc2VsZi5tZXNzYWdlc19wKVstbGltaXQ6XQoKICAgICMg4pSA4pSAIE1FTU9SSUVTIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgZGVmIGFwcGVuZF9tZW1vcnkoc2VsZiwgc2Vzc2lvbl9pZDogc3RyLCB1c2VyX3RleHQ6IHN0ciwK"
    "ICAgICAgICAgICAgICAgICAgICAgIGFzc2lzdGFudF90ZXh0OiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHJlY29y"
    "ZF90eXBlID0gaW5mZXJfcmVjb3JkX3R5cGUodXNlcl90ZXh0LCBhc3Npc3RhbnRfdGV4dCkKICAgICAgICBrZXl3b3JkcyAgICA9"
    "IGV4dHJhY3Rfa2V5d29yZHModXNlcl90ZXh0ICsgIiAiICsgYXNzaXN0YW50X3RleHQpCiAgICAgICAgdGFncyAgICAgICAgPSBz"
    "ZWxmLl9pbmZlcl90YWdzKHJlY29yZF90eXBlLCB1c2VyX3RleHQsIGtleXdvcmRzKQogICAgICAgIHRpdGxlICAgICAgID0gc2Vs"
    "Zi5faW5mZXJfdGl0bGUocmVjb3JkX3R5cGUsIHVzZXJfdGV4dCwga2V5d29yZHMpCiAgICAgICAgc3VtbWFyeSAgICAgPSBzZWxm"
    "Ll9zdW1tYXJpemUocmVjb3JkX3R5cGUsIHVzZXJfdGV4dCwgYXNzaXN0YW50X3RleHQpCgogICAgICAgIG1lbW9yeSA9IHsKICAg"
    "ICAgICAgICAgImlkIjogICAgICAgICAgICAgICBmIm1lbV97dXVpZC51dWlkNCgpLmhleFs6MTJdfSIsCiAgICAgICAgICAgICJ0"
    "aW1lc3RhbXAiOiAgICAgICAgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAic2Vzc2lvbl9pZCI6ICAgICAgIHNlc3Npb25f"
    "aWQsCiAgICAgICAgICAgICJwZXJzb25hIjogICAgICAgICAgREVDS19OQU1FLAogICAgICAgICAgICAidHlwZSI6ICAgICAgICAg"
    "ICAgIHJlY29yZF90eXBlLAogICAgICAgICAgICAidGl0bGUiOiAgICAgICAgICAgIHRpdGxlLAogICAgICAgICAgICAic3VtbWFy"
    "eSI6ICAgICAgICAgIHN1bW1hcnksCiAgICAgICAgICAgICJjb250ZW50IjogICAgICAgICAgdXNlcl90ZXh0Wzo0MDAwXSwKICAg"
    "ICAgICAgICAgImFzc2lzdGFudF9jb250ZXh0Ijphc3Npc3RhbnRfdGV4dFs6MTIwMF0sCiAgICAgICAgICAgICJrZXl3b3JkcyI6"
    "ICAgICAgICAga2V5d29yZHMsCiAgICAgICAgICAgICJ0YWdzIjogICAgICAgICAgICAgdGFncywKICAgICAgICAgICAgImNvbmZp"
    "ZGVuY2UiOiAgICAgICAwLjcwIGlmIHJlY29yZF90eXBlIGluIHsKICAgICAgICAgICAgICAgICJkcmVhbSIsImlzc3VlIiwiaWRl"
    "YSIsInByZWZlcmVuY2UiLCJyZXNvbHV0aW9uIgogICAgICAgICAgICB9IGVsc2UgMC41NSwKICAgICAgICB9CgogICAgICAgIGlm"
    "IHNlbGYuX2lzX25lYXJfZHVwbGljYXRlKG1lbW9yeSk6CiAgICAgICAgICAgIHJldHVybiBOb25lCgogICAgICAgIGFwcGVuZF9q"
    "c29ubChzZWxmLm1lbW9yaWVzX3AsIG1lbW9yeSkKICAgICAgICByZXR1cm4gbWVtb3J5CgogICAgZGVmIHNlYXJjaF9tZW1vcmll"
    "cyhzZWxmLCBxdWVyeTogc3RyLCBsaW1pdDogaW50ID0gNikgLT4gbGlzdFtkaWN0XToKICAgICAgICAiIiIKICAgICAgICBLZXl3"
    "b3JkLXNjb3JlZCBtZW1vcnkgc2VhcmNoLgogICAgICAgIFJldHVybnMgdXAgdG8gYGxpbWl0YCByZWNvcmRzIHNvcnRlZCBieSBy"
    "ZWxldmFuY2Ugc2NvcmUgZGVzY2VuZGluZy4KICAgICAgICBGYWxscyBiYWNrIHRvIG1vc3QgcmVjZW50IGlmIG5vIHF1ZXJ5IHRl"
    "cm1zIG1hdGNoLgogICAgICAgICIiIgogICAgICAgIG1lbW9yaWVzID0gcmVhZF9qc29ubChzZWxmLm1lbW9yaWVzX3ApCiAgICAg"
    "ICAgaWYgbm90IHF1ZXJ5LnN0cmlwKCk6CiAgICAgICAgICAgIHJldHVybiBtZW1vcmllc1stbGltaXQ6XQoKICAgICAgICBxX3Rl"
    "cm1zID0gc2V0KGV4dHJhY3Rfa2V5d29yZHMocXVlcnksIGxpbWl0PTE2KSkKICAgICAgICBzY29yZWQgID0gW10KCiAgICAgICAg"
    "Zm9yIGl0ZW0gaW4gbWVtb3JpZXM6CiAgICAgICAgICAgIGl0ZW1fdGVybXMgPSBzZXQoZXh0cmFjdF9rZXl3b3JkcygiICIuam9p"
    "bihbCiAgICAgICAgICAgICAgICBpdGVtLmdldCgidGl0bGUiLCAgICIiKSwKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0KCJzdW1t"
    "YXJ5IiwgIiIpLAogICAgICAgICAgICAgICAgaXRlbS5nZXQoImNvbnRlbnQiLCAiIiksCiAgICAgICAgICAgICAgICAiICIuam9p"
    "bihpdGVtLmdldCgia2V5d29yZHMiLCBbXSkpLAogICAgICAgICAgICAgICAgIiAiLmpvaW4oaXRlbS5nZXQoInRhZ3MiLCAgICAg"
    "W10pKSwKICAgICAgICAgICAgXSksIGxpbWl0PTQwKSkKCiAgICAgICAgICAgIHNjb3JlID0gbGVuKHFfdGVybXMgJiBpdGVtX3Rl"
    "cm1zKQoKICAgICAgICAgICAgIyBCb29zdCBieSB0eXBlIG1hdGNoCiAgICAgICAgICAgIHFsID0gcXVlcnkubG93ZXIoKQogICAg"
    "ICAgICAgICBydCA9IGl0ZW0uZ2V0KCJ0eXBlIiwgIiIpCiAgICAgICAgICAgIGlmICJkcmVhbSIgIGluIHFsIGFuZCBydCA9PSAi"
    "ZHJlYW0iOiAgICBzY29yZSArPSA0CiAgICAgICAgICAgIGlmICJ0YXNrIiAgIGluIHFsIGFuZCBydCA9PSAidGFzayI6ICAgICBz"
    "Y29yZSArPSAzCiAgICAgICAgICAgIGlmICJpZGVhIiAgIGluIHFsIGFuZCBydCA9PSAiaWRlYSI6ICAgICBzY29yZSArPSAyCiAg"
    "ICAgICAgICAgIGlmICJsc2wiICAgIGluIHFsIGFuZCBydCBpbiB7Imlzc3VlIiwicmVzb2x1dGlvbiJ9OiBzY29yZSArPSAyCgog"
    "ICAgICAgICAgICBpZiBzY29yZSA+IDA6CiAgICAgICAgICAgICAgICBzY29yZWQuYXBwZW5kKChzY29yZSwgaXRlbSkpCgogICAg"
    "ICAgIHNjb3JlZC5zb3J0KGtleT1sYW1iZGEgeDogKHhbMF0sIHhbMV0uZ2V0KCJ0aW1lc3RhbXAiLCAiIikpLAogICAgICAgICAg"
    "ICAgICAgICAgIHJldmVyc2U9VHJ1ZSkKICAgICAgICByZXR1cm4gW2l0ZW0gZm9yIF8sIGl0ZW0gaW4gc2NvcmVkWzpsaW1pdF1d"
    "CgogICAgZGVmIGJ1aWxkX2NvbnRleHRfYmxvY2soc2VsZiwgcXVlcnk6IHN0ciwgbWF4X2NoYXJzOiBpbnQgPSAyMDAwKSAtPiBz"
    "dHI6CiAgICAgICAgIiIiCiAgICAgICAgQnVpbGQgYSBjb250ZXh0IHN0cmluZyBmcm9tIHJlbGV2YW50IG1lbW9yaWVzIGZvciBw"
    "cm9tcHQgaW5qZWN0aW9uLgogICAgICAgIFRydW5jYXRlcyB0byBtYXhfY2hhcnMgdG8gcHJvdGVjdCB0aGUgY29udGV4dCB3aW5k"
    "b3cuCiAgICAgICAgIiIiCiAgICAgICAgbWVtb3JpZXMgPSBzZWxmLnNlYXJjaF9tZW1vcmllcyhxdWVyeSwgbGltaXQ9NCkKICAg"
    "ICAgICBpZiBub3QgbWVtb3JpZXM6CiAgICAgICAgICAgIHJldHVybiAiIgoKICAgICAgICBwYXJ0cyA9IFsiW1JFTEVWQU5UIE1F"
    "TU9SSUVTXSJdCiAgICAgICAgdG90YWwgPSAwCiAgICAgICAgZm9yIG0gaW4gbWVtb3JpZXM6CiAgICAgICAgICAgIGVudHJ5ID0g"
    "KAogICAgICAgICAgICAgICAgZiLigKIgW3ttLmdldCgndHlwZScsJycpLnVwcGVyKCl9XSB7bS5nZXQoJ3RpdGxlJywnJyl9OiAi"
    "CiAgICAgICAgICAgICAgICBmInttLmdldCgnc3VtbWFyeScsJycpfSIKICAgICAgICAgICAgKQogICAgICAgICAgICBpZiB0b3Rh"
    "bCArIGxlbihlbnRyeSkgPiBtYXhfY2hhcnM6CiAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBwYXJ0cy5hcHBlbmQo"
    "ZW50cnkpCiAgICAgICAgICAgIHRvdGFsICs9IGxlbihlbnRyeSkKCiAgICAgICAgcGFydHMuYXBwZW5kKCJbRU5EIE1FTU9SSUVT"
    "XSIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCiAgICAjIOKUgOKUgCBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgZGVmIF9pc19uZWFyX2R1cGxpY2F0ZShzZWxmLCBjYW5kaWRhdGU6IGRpY3QpIC0+IGJvb2w6CiAgICAgICAgcmVjZW50"
    "ID0gcmVhZF9qc29ubChzZWxmLm1lbW9yaWVzX3ApWy0yNTpdCiAgICAgICAgY3QgPSBjYW5kaWRhdGUuZ2V0KCJ0aXRsZSIsICIi"
    "KS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBjcyA9IGNhbmRpZGF0ZS5nZXQoInN1bW1hcnkiLCAiIikubG93ZXIoKS5zdHJpcCgp"
    "CiAgICAgICAgZm9yIGl0ZW0gaW4gcmVjZW50OgogICAgICAgICAgICBpZiBpdGVtLmdldCgidGl0bGUiLCIiKS5sb3dlcigpLnN0"
    "cmlwKCkgPT0gY3Q6ICByZXR1cm4gVHJ1ZQogICAgICAgICAgICBpZiBpdGVtLmdldCgic3VtbWFyeSIsIiIpLmxvd2VyKCkuc3Ry"
    "aXAoKSA9PSBjczogcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICBkZWYgX2luZmVyX3RhZ3Moc2VsZiwgcmVj"
    "b3JkX3R5cGU6IHN0ciwgdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgIGtleXdvcmRzOiBsaXN0W3N0cl0pIC0+IGxpc3Rb"
    "c3RyXToKICAgICAgICB0ICAgID0gdGV4dC5sb3dlcigpCiAgICAgICAgdGFncyA9IFtyZWNvcmRfdHlwZV0KICAgICAgICBpZiAi"
    "ZHJlYW0iICAgaW4gdDogdGFncy5hcHBlbmQoImRyZWFtIikKICAgICAgICBpZiAibHNsIiAgICAgaW4gdDogdGFncy5hcHBlbmQo"
    "ImxzbCIpCiAgICAgICAgaWYgInB5dGhvbiIgIGluIHQ6IHRhZ3MuYXBwZW5kKCJweXRob24iKQogICAgICAgIGlmICJnYW1lIiAg"
    "ICBpbiB0OiB0YWdzLmFwcGVuZCgiZ2FtZV9pZGVhIikKICAgICAgICBpZiAic2wiICAgICAgaW4gdCBvciAic2Vjb25kIGxpZmUi"
    "IGluIHQ6IHRhZ3MuYXBwZW5kKCJzZWNvbmRsaWZlIikKICAgICAgICBpZiBERUNLX05BTUUubG93ZXIoKSBpbiB0OiB0YWdzLmFw"
    "cGVuZChERUNLX05BTUUubG93ZXIoKSkKICAgICAgICBmb3Iga3cgaW4ga2V5d29yZHNbOjRdOgogICAgICAgICAgICBpZiBrdyBu"
    "b3QgaW4gdGFnczoKICAgICAgICAgICAgICAgIHRhZ3MuYXBwZW5kKGt3KQogICAgICAgICMgRGVkdXBsaWNhdGUgcHJlc2Vydmlu"
    "ZyBvcmRlcgogICAgICAgIHNlZW4sIG91dCA9IHNldCgpLCBbXQogICAgICAgIGZvciB0YWcgaW4gdGFnczoKICAgICAgICAgICAg"
    "aWYgdGFnIG5vdCBpbiBzZWVuOgogICAgICAgICAgICAgICAgc2Vlbi5hZGQodGFnKQogICAgICAgICAgICAgICAgb3V0LmFwcGVu"
    "ZCh0YWcpCiAgICAgICAgcmV0dXJuIG91dFs6MTJdCgogICAgZGVmIF9pbmZlcl90aXRsZShzZWxmLCByZWNvcmRfdHlwZTogc3Ry"
    "LCB1c2VyX3RleHQ6IHN0ciwKICAgICAgICAgICAgICAgICAgICAga2V5d29yZHM6IGxpc3Rbc3RyXSkgLT4gc3RyOgogICAgICAg"
    "IGRlZiBjbGVhbih3b3Jkcyk6CiAgICAgICAgICAgIHJldHVybiBbdy5zdHJpcCgiIC1fLiwhPyIpLmNhcGl0YWxpemUoKQogICAg"
    "ICAgICAgICAgICAgICAgIGZvciB3IGluIHdvcmRzIGlmIGxlbih3KSA+IDJdCgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJ0"
    "YXNrIjoKICAgICAgICAgICAgaW1wb3J0IHJlCiAgICAgICAgICAgIG0gPSByZS5zZWFyY2gociJyZW1pbmQgbWUgLio/IHRvICgu"
    "KykiLCB1c2VyX3RleHQsIHJlLkkpCiAgICAgICAgICAgIGlmIG06CiAgICAgICAgICAgICAgICByZXR1cm4gZiJSZW1pbmRlcjog"
    "e20uZ3JvdXAoMSkuc3RyaXAoKVs6NjBdfSIKICAgICAgICAgICAgcmV0dXJuICJSZW1pbmRlciBUYXNrIgogICAgICAgIGlmIHJl"
    "Y29yZF90eXBlID09ICJkcmVhbSI6CiAgICAgICAgICAgIHJldHVybiBmInsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6M10pKX0g"
    "RHJlYW0iLnN0cmlwKCkgb3IgIkRyZWFtIE1lbW9yeSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaXNzdWUiOgogICAgICAg"
    "ICAgICByZXR1cm4gZiJJc3N1ZTogeycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzo0XSkpfSIuc3RyaXAoKSBvciAiVGVjaG5pY2Fs"
    "IElzc3VlIgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJyZXNvbHV0aW9uIjoKICAgICAgICAgICAgcmV0dXJuIGYiUmVzb2x1"
    "dGlvbjogeycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzo0XSkpfSIuc3RyaXAoKSBvciAiVGVjaG5pY2FsIFJlc29sdXRpb24iCiAg"
    "ICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImlkZWEiOgogICAgICAgICAgICByZXR1cm4gZiJJZGVhOiB7JyAnLmpvaW4oY2xlYW4o"
    "a2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJJZGVhIgogICAgICAgIGlmIGtleXdvcmRzOgogICAgICAgICAgICByZXR1cm4g"
    "IiAiLmpvaW4oY2xlYW4oa2V5d29yZHNbOjVdKSkgb3IgIkNvbnZlcnNhdGlvbiBNZW1vcnkiCiAgICAgICAgcmV0dXJuICJDb252"
    "ZXJzYXRpb24gTWVtb3J5IgoKICAgIGRlZiBfc3VtbWFyaXplKHNlbGYsIHJlY29yZF90eXBlOiBzdHIsIHVzZXJfdGV4dDogc3Ry"
    "LAogICAgICAgICAgICAgICAgICAgYXNzaXN0YW50X3RleHQ6IHN0cikgLT4gc3RyOgogICAgICAgIHUgPSB1c2VyX3RleHQuc3Ry"
    "aXAoKVs6MjIwXQogICAgICAgIGEgPSBhc3Npc3RhbnRfdGV4dC5zdHJpcCgpWzoyMjBdCiAgICAgICAgaWYgcmVjb3JkX3R5cGUg"
    "PT0gImRyZWFtIjogICAgICAgcmV0dXJuIGYiVXNlciBkZXNjcmliZWQgYSBkcmVhbToge3V9IgogICAgICAgIGlmIHJlY29yZF90"
    "eXBlID09ICJ0YXNrIjogICAgICAgIHJldHVybiBmIlJlbWluZGVyL3Rhc2s6IHt1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9"
    "PSAiaXNzdWUiOiAgICAgICByZXR1cm4gZiJUZWNobmljYWwgaXNzdWU6IHt1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAi"
    "cmVzb2x1dGlvbiI6ICByZXR1cm4gZiJTb2x1dGlvbiByZWNvcmRlZDoge2Egb3IgdX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUg"
    "PT0gImlkZWEiOiAgICAgICAgcmV0dXJuIGYiSWRlYSBkaXNjdXNzZWQ6IHt1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAi"
    "cHJlZmVyZW5jZSI6ICByZXR1cm4gZiJQcmVmZXJlbmNlIG5vdGVkOiB7dX0iCiAgICAgICAgcmV0dXJuIGYiQ29udmVyc2F0aW9u"
    "OiB7dX0iCgoKIyDilIDilIAgU0VTU0lPTiBNQU5BR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTZXNzaW9u"
    "TWFuYWdlcjoKICAgICIiIgogICAgTWFuYWdlcyBjb252ZXJzYXRpb24gc2Vzc2lvbnMuCgogICAgQXV0by1zYXZlOiBldmVyeSAx"
    "MCBtaW51dGVzIChBUFNjaGVkdWxlciksIG1pZG5pZ2h0LXRvLW1pZG5pZ2h0IGJvdW5kYXJ5LgogICAgRmlsZTogc2Vzc2lvbnMv"
    "WVlZWS1NTS1ERC5qc29ubCDigJQgb3ZlcndyaXRlcyBvbiBlYWNoIHNhdmUuCiAgICBJbmRleDogc2Vzc2lvbnMvc2Vzc2lvbl9p"
    "bmRleC5qc29uIOKAlCBvbmUgZW50cnkgcGVyIGRheS4KCiAgICBTZXNzaW9ucyBhcmUgbG9hZGVkIGFzIGNvbnRleHQgaW5qZWN0"
    "aW9uIChub3QgcmVhbCBtZW1vcnkpIHVudGlsCiAgICB0aGUgU1FMaXRlL0Nocm9tYURCIHN5c3RlbSBpcyBidWlsdCBpbiBQaGFz"
    "ZSAyLgogICAgIiIiCgogICAgQVVUT1NBVkVfSU5URVJWQUwgPSAxMCAgICMgbWludXRlcwoKICAgIGRlZiBfX2luaXRfXyhzZWxm"
    "KToKICAgICAgICBzZWxmLl9zZXNzaW9uc19kaXIgID0gY2ZnX3BhdGgoInNlc3Npb25zIikKICAgICAgICBzZWxmLl9pbmRleF9w"
    "YXRoICAgID0gc2VsZi5fc2Vzc2lvbnNfZGlyIC8gInNlc3Npb25faW5kZXguanNvbiIKICAgICAgICBzZWxmLl9zZXNzaW9uX2lk"
    "ICAgID0gZiJzZXNzaW9uX3tkYXRldGltZS5ub3coKS5zdHJmdGltZSgnJVklbSVkXyVIJU0lUycpfSIKICAgICAgICBzZWxmLl9j"
    "dXJyZW50X2RhdGUgID0gZGF0ZS50b2RheSgpLmlzb2Zvcm1hdCgpCiAgICAgICAgc2VsZi5fbWVzc2FnZXM6IGxpc3RbZGljdF0g"
    "PSBbXQogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFsOiBPcHRpb25hbFtzdHJdID0gTm9uZSAgIyBkYXRlIG9mIGxvYWRlZCBq"
    "b3VybmFsCgogICAgIyDilIDilIAgQ1VSUkVOVCBTRVNTSU9OIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGFkZF9tZXNzYWdlKHNlbGYsIHJvbGU6IHN0ciwgY29udGVu"
    "dDogc3RyLAogICAgICAgICAgICAgICAgICAgIGVtb3Rpb246IHN0ciA9ICIiLCB0aW1lc3RhbXA6IHN0ciA9ICIiKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuX21lc3NhZ2VzLmFwcGVuZCh7CiAgICAgICAgICAgICJpZCI6ICAgICAgICBmIm1zZ197dXVpZC51dWlk"
    "NCgpLmhleFs6OF19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6IHRpbWVzdGFtcCBvciBsb2NhbF9ub3dfaXNvKCksCiAgICAg"
    "ICAgICAgICJyb2xlIjogICAgICByb2xlLAogICAgICAgICAgICAiY29udGVudCI6ICAgY29udGVudCwKICAgICAgICAgICAgImVt"
    "b3Rpb24iOiAgIGVtb3Rpb24sCiAgICAgICAgfSkKCiAgICBkZWYgZ2V0X2hpc3Rvcnkoc2VsZikgLT4gbGlzdFtkaWN0XToKICAg"
    "ICAgICAiIiIKICAgICAgICBSZXR1cm4gaGlzdG9yeSBpbiBMTE0tZnJpZW5kbHkgZm9ybWF0LgogICAgICAgIFt7InJvbGUiOiAi"
    "dXNlciJ8ImFzc2lzdGFudCIsICJjb250ZW50IjogIi4uLiJ9XQogICAgICAgICIiIgogICAgICAgIHJldHVybiBbCiAgICAgICAg"
    "ICAgIHsicm9sZSI6IG1bInJvbGUiXSwgImNvbnRlbnQiOiBtWyJjb250ZW50Il19CiAgICAgICAgICAgIGZvciBtIGluIHNlbGYu"
    "X21lc3NhZ2VzCiAgICAgICAgICAgIGlmIG1bInJvbGUiXSBpbiAoInVzZXIiLCAiYXNzaXN0YW50IikKICAgICAgICBdCgogICAg"
    "QHByb3BlcnR5CiAgICBkZWYgc2Vzc2lvbl9pZChzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX3Nlc3Npb25faWQK"
    "CiAgICBAcHJvcGVydHkKICAgIGRlZiBtZXNzYWdlX2NvdW50KHNlbGYpIC0+IGludDoKICAgICAgICByZXR1cm4gbGVuKHNlbGYu"
    "X21lc3NhZ2VzKQoKICAgICMg4pSA4pSAIFNBVkUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgc2F2ZShzZWxm"
    "LCBhaV9nZW5lcmF0ZWRfbmFtZTogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgU2F2ZSBjdXJyZW50IHNl"
    "c3Npb24gdG8gc2Vzc2lvbnMvWVlZWS1NTS1ERC5qc29ubC4KICAgICAgICBPdmVyd3JpdGVzIHRoZSBmaWxlIGZvciB0b2RheSDi"
    "gJQgZWFjaCBzYXZlIGlzIGEgZnVsbCBzbmFwc2hvdC4KICAgICAgICBVcGRhdGVzIHNlc3Npb25faW5kZXguanNvbi4KICAgICAg"
    "ICAiIiIKICAgICAgICB0b2RheSA9IGRhdGUudG9kYXkoKS5pc29mb3JtYXQoKQogICAgICAgIG91dF9wYXRoID0gc2VsZi5fc2Vz"
    "c2lvbnNfZGlyIC8gZiJ7dG9kYXl9Lmpzb25sIgoKICAgICAgICAjIFdyaXRlIGFsbCBtZXNzYWdlcwogICAgICAgIHdyaXRlX2pz"
    "b25sKG91dF9wYXRoLCBzZWxmLl9tZXNzYWdlcykKCiAgICAgICAgIyBVcGRhdGUgaW5kZXgKICAgICAgICBpbmRleCA9IHNlbGYu"
    "X2xvYWRfaW5kZXgoKQogICAgICAgIGV4aXN0aW5nID0gbmV4dCgKICAgICAgICAgICAgKHMgZm9yIHMgaW4gaW5kZXhbInNlc3Np"
    "b25zIl0gaWYgc1siZGF0ZSJdID09IHRvZGF5KSwgTm9uZQogICAgICAgICkKCiAgICAgICAgbmFtZSA9IGFpX2dlbmVyYXRlZF9u"
    "YW1lIG9yIGV4aXN0aW5nLmdldCgibmFtZSIsICIiKSBpZiBleGlzdGluZyBlbHNlICIiCiAgICAgICAgaWYgbm90IG5hbWUgYW5k"
    "IHNlbGYuX21lc3NhZ2VzOgogICAgICAgICAgICAjIEF1dG8tbmFtZSBmcm9tIGZpcnN0IHVzZXIgbWVzc2FnZSAoZmlyc3QgNSB3"
    "b3JkcykKICAgICAgICAgICAgZmlyc3RfdXNlciA9IG5leHQoCiAgICAgICAgICAgICAgICAobVsiY29udGVudCJdIGZvciBtIGlu"
    "IHNlbGYuX21lc3NhZ2VzIGlmIG1bInJvbGUiXSA9PSAidXNlciIpLAogICAgICAgICAgICAgICAgIiIKICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICB3b3JkcyA9IGZpcnN0X3VzZXIuc3BsaXQoKVs6NV0KICAgICAgICAgICAgbmFtZSAgPSAiICIuam9pbih3b3Jk"
    "cykgaWYgd29yZHMgZWxzZSBmIlNlc3Npb24ge3RvZGF5fSIKCiAgICAgICAgZW50cnkgPSB7CiAgICAgICAgICAgICJkYXRlIjog"
    "ICAgICAgICAgdG9kYXksCiAgICAgICAgICAgICJzZXNzaW9uX2lkIjogICAgc2VsZi5fc2Vzc2lvbl9pZCwKICAgICAgICAgICAg"
    "Im5hbWUiOiAgICAgICAgICBuYW1lLAogICAgICAgICAgICAibWVzc2FnZV9jb3VudCI6IGxlbihzZWxmLl9tZXNzYWdlcyksCiAg"
    "ICAgICAgICAgICJmaXJzdF9tZXNzYWdlIjogKHNlbGYuX21lc3NhZ2VzWzBdWyJ0aW1lc3RhbXAiXQogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBpZiBzZWxmLl9tZXNzYWdlcyBlbHNlICIiKSwKICAgICAgICAgICAgImxhc3RfbWVzc2FnZSI6ICAoc2Vs"
    "Zi5fbWVzc2FnZXNbLTFdWyJ0aW1lc3RhbXAiXQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBzZWxmLl9tZXNzYWdl"
    "cyBlbHNlICIiKSwKICAgICAgICB9CgogICAgICAgIGlmIGV4aXN0aW5nOgogICAgICAgICAgICBpZHggPSBpbmRleFsic2Vzc2lv"
    "bnMiXS5pbmRleChleGlzdGluZykKICAgICAgICAgICAgaW5kZXhbInNlc3Npb25zIl1baWR4XSA9IGVudHJ5CiAgICAgICAgZWxz"
    "ZToKICAgICAgICAgICAgaW5kZXhbInNlc3Npb25zIl0uaW5zZXJ0KDAsIGVudHJ5KQoKICAgICAgICAjIEtlZXAgbGFzdCAzNjUg"
    "ZGF5cyBpbiBpbmRleAogICAgICAgIGluZGV4WyJzZXNzaW9ucyJdID0gaW5kZXhbInNlc3Npb25zIl1bOjM2NV0KICAgICAgICBz"
    "ZWxmLl9zYXZlX2luZGV4KGluZGV4KQoKICAgICMg4pSA4pSAIExPQUQgLyBKT1VSTkFMIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGxpc3Rfc2Vzc2lvbnMoc2Vs"
    "ZikgLT4gbGlzdFtkaWN0XToKICAgICAgICAiIiJSZXR1cm4gYWxsIHNlc3Npb25zIGZyb20gaW5kZXgsIG5ld2VzdCBmaXJzdC4i"
    "IiIKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZF9pbmRleCgpLmdldCgic2Vzc2lvbnMiLCBbXSkKCiAgICBkZWYgbG9hZF9zZXNz"
    "aW9uX2FzX2NvbnRleHQoc2VsZiwgc2Vzc2lvbl9kYXRlOiBzdHIpIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBMb2FkIGEg"
    "cGFzdCBzZXNzaW9uIGFzIGEgY29udGV4dCBpbmplY3Rpb24gc3RyaW5nLgogICAgICAgIFJldHVybnMgZm9ybWF0dGVkIHRleHQg"
    "dG8gcHJlcGVuZCB0byB0aGUgc3lzdGVtIHByb21wdC4KICAgICAgICBUaGlzIGlzIE5PVCByZWFsIG1lbW9yeSDigJQgaXQncyBh"
    "IHRlbXBvcmFyeSBjb250ZXh0IHdpbmRvdyBpbmplY3Rpb24KICAgICAgICB1bnRpbCB0aGUgUGhhc2UgMiBtZW1vcnkgc3lzdGVt"
    "IGlzIGJ1aWx0LgogICAgICAgICIiIgogICAgICAgIHBhdGggPSBzZWxmLl9zZXNzaW9uc19kaXIgLyBmIntzZXNzaW9uX2RhdGV9"
    "Lmpzb25sIgogICAgICAgIGlmIG5vdCBwYXRoLmV4aXN0cygpOgogICAgICAgICAgICByZXR1cm4gIiIKCiAgICAgICAgbWVzc2Fn"
    "ZXMgPSByZWFkX2pzb25sKHBhdGgpCiAgICAgICAgc2VsZi5fbG9hZGVkX2pvdXJuYWwgPSBzZXNzaW9uX2RhdGUKCiAgICAgICAg"
    "bGluZXMgPSBbZiJbSk9VUk5BTCBMT0FERUQg4oCUIHtzZXNzaW9uX2RhdGV9XSIsCiAgICAgICAgICAgICAgICAgIlRoZSBmb2xs"
    "b3dpbmcgaXMgYSByZWNvcmQgb2YgYSBwcmlvciBjb252ZXJzYXRpb24uIiwKICAgICAgICAgICAgICAgICAiVXNlIHRoaXMgYXMg"
    "Y29udGV4dCBmb3IgdGhlIGN1cnJlbnQgc2Vzc2lvbjpcbiJdCgogICAgICAgICMgSW5jbHVkZSB1cCB0byBsYXN0IDMwIG1lc3Nh"
    "Z2VzIGZyb20gdGhhdCBzZXNzaW9uCiAgICAgICAgZm9yIG1zZyBpbiBtZXNzYWdlc1stMzA6XToKICAgICAgICAgICAgcm9sZSAg"
    "ICA9IG1zZy5nZXQoInJvbGUiLCAiPyIpLnVwcGVyKCkKICAgICAgICAgICAgY29udGVudCA9IG1zZy5nZXQoImNvbnRlbnQiLCAi"
    "IilbOjMwMF0KICAgICAgICAgICAgdHMgICAgICA9IG1zZy5nZXQoInRpbWVzdGFtcCIsICIiKVs6MTZdCiAgICAgICAgICAgIGxp"
    "bmVzLmFwcGVuZChmIlt7dHN9XSB7cm9sZX06IHtjb250ZW50fSIpCgogICAgICAgIGxpbmVzLmFwcGVuZCgiW0VORCBKT1VSTkFM"
    "XSIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihsaW5lcykKCiAgICBkZWYgY2xlYXJfbG9hZGVkX2pvdXJuYWwoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLl9sb2FkZWRfam91cm5hbCA9IE5vbmUKCiAgICBAcHJvcGVydHkKICAgIGRlZiBsb2FkZWRfam91"
    "cm5hbF9kYXRlKHNlbGYpIC0+IE9wdGlvbmFsW3N0cl06CiAgICAgICAgcmV0dXJuIHNlbGYuX2xvYWRlZF9qb3VybmFsCgogICAg"
    "ZGVmIHJlbmFtZV9zZXNzaW9uKHNlbGYsIHNlc3Npb25fZGF0ZTogc3RyLCBuZXdfbmFtZTogc3RyKSAtPiBib29sOgogICAgICAg"
    "ICIiIlJlbmFtZSBhIHNlc3Npb24gaW4gdGhlIGluZGV4LiBSZXR1cm5zIFRydWUgb24gc3VjY2Vzcy4iIiIKICAgICAgICBpbmRl"
    "eCA9IHNlbGYuX2xvYWRfaW5kZXgoKQogICAgICAgIGZvciBlbnRyeSBpbiBpbmRleFsic2Vzc2lvbnMiXToKICAgICAgICAgICAg"
    "aWYgZW50cnlbImRhdGUiXSA9PSBzZXNzaW9uX2RhdGU6CiAgICAgICAgICAgICAgICBlbnRyeVsibmFtZSJdID0gbmV3X25hbWVb"
    "OjgwXQogICAgICAgICAgICAgICAgc2VsZi5fc2F2ZV9pbmRleChpbmRleCkKICAgICAgICAgICAgICAgIHJldHVybiBUcnVlCiAg"
    "ICAgICAgcmV0dXJuIEZhbHNlCgogICAgIyDilIDilIAgSU5ERVggSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfbG9hZF9pbmRleChzZWxmKSAt"
    "PiBkaWN0OgogICAgICAgIGlmIG5vdCBzZWxmLl9pbmRleF9wYXRoLmV4aXN0cygpOgogICAgICAgICAgICByZXR1cm4geyJzZXNz"
    "aW9ucyI6IFtdfQogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIGpzb24ubG9hZHMoCiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9pbmRleF9wYXRoLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKQogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbjoKICAgICAgICAgICAgcmV0dXJuIHsic2Vzc2lvbnMiOiBbXX0KCiAgICBkZWYgX3NhdmVfaW5kZXgoc2VsZiwgaW5kZXg6"
    "IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5faW5kZXhfcGF0aC53cml0ZV90ZXh0KAogICAgICAgICAgICBqc29uLmR1bXBz"
    "KGluZGV4LCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICApCgoKIyDilIDilIAgTEVTU09OUyBMRUFSTkVEIERB"
    "VEFCQVNFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApjbGFzcyBMZXNzb25zTGVhcm5lZERCOgogICAgIiIiCiAgICBQZXJzaXN0ZW50IGtub3dsZWRnZSBiYXNlIGZvciBj"
    "b2RlIGxlc3NvbnMsIHJ1bGVzLCBhbmQgcmVzb2x1dGlvbnMuCgogICAgQ29sdW1ucyBwZXIgcmVjb3JkOgogICAgICAgIGlkLCBj"
    "cmVhdGVkX2F0LCBlbnZpcm9ubWVudCAoTFNMfFB5dGhvbnxQeVNpZGU2fC4uLiksIGxhbmd1YWdlLAogICAgICAgIHJlZmVyZW5j"
    "ZV9rZXkgKHNob3J0IHVuaXF1ZSB0YWcpLCBzdW1tYXJ5LCBmdWxsX3J1bGUsCiAgICAgICAgcmVzb2x1dGlvbiwgbGluaywgdGFn"
    "cwoKICAgIFF1ZXJpZWQgRklSU1QgYmVmb3JlIGFueSBjb2RlIHNlc3Npb24gaW4gdGhlIHJlbGV2YW50IGxhbmd1YWdlLgogICAg"
    "VGhlIExTTCBGb3JiaWRkZW4gUnVsZXNldCBsaXZlcyBoZXJlLgogICAgR3Jvd2luZywgbm9uLWR1cGxpY2F0aW5nLCBzZWFyY2hh"
    "YmxlLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3BhdGggPSBjZmdfcGF0aCgibWVtb3Jp"
    "ZXMiKSAvICJsZXNzb25zX2xlYXJuZWQuanNvbmwiCgogICAgZGVmIGFkZChzZWxmLCBlbnZpcm9ubWVudDogc3RyLCBsYW5ndWFn"
    "ZTogc3RyLCByZWZlcmVuY2Vfa2V5OiBzdHIsCiAgICAgICAgICAgIHN1bW1hcnk6IHN0ciwgZnVsbF9ydWxlOiBzdHIsIHJlc29s"
    "dXRpb246IHN0ciA9ICIiLAogICAgICAgICAgICBsaW5rOiBzdHIgPSAiIiwgdGFnczogbGlzdCA9IE5vbmUpIC0+IGRpY3Q6CiAg"
    "ICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgIGYibGVzc29uX3t1dWlkLnV1aWQ0KCkuaGV4Wzox"
    "MF19IiwKICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICJlbnZpcm9ubWVu"
    "dCI6ICAgZW52aXJvbm1lbnQsCiAgICAgICAgICAgICJsYW5ndWFnZSI6ICAgICAgbGFuZ3VhZ2UsCiAgICAgICAgICAgICJyZWZl"
    "cmVuY2Vfa2V5IjogcmVmZXJlbmNlX2tleSwKICAgICAgICAgICAgInN1bW1hcnkiOiAgICAgICBzdW1tYXJ5LAogICAgICAgICAg"
    "ICAiZnVsbF9ydWxlIjogICAgIGZ1bGxfcnVsZSwKICAgICAgICAgICAgInJlc29sdXRpb24iOiAgICByZXNvbHV0aW9uLAogICAg"
    "ICAgICAgICAibGluayI6ICAgICAgICAgIGxpbmssCiAgICAgICAgICAgICJ0YWdzIjogICAgICAgICAgdGFncyBvciBbXSwKICAg"
    "ICAgICB9CiAgICAgICAgaWYgbm90IHNlbGYuX2lzX2R1cGxpY2F0ZShyZWZlcmVuY2Vfa2V5KToKICAgICAgICAgICAgYXBwZW5k"
    "X2pzb25sKHNlbGYuX3BhdGgsIHJlY29yZCkKICAgICAgICByZXR1cm4gcmVjb3JkCgogICAgZGVmIHNlYXJjaChzZWxmLCBxdWVy"
    "eTogc3RyID0gIiIsIGVudmlyb25tZW50OiBzdHIgPSAiIiwKICAgICAgICAgICAgICAgbGFuZ3VhZ2U6IHN0ciA9ICIiKSAtPiBs"
    "aXN0W2RpY3RdOgogICAgICAgIHJlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgcmVzdWx0cyA9IFtdCiAg"
    "ICAgICAgcSA9IHF1ZXJ5Lmxvd2VyKCkKICAgICAgICBmb3IgciBpbiByZWNvcmRzOgogICAgICAgICAgICBpZiBlbnZpcm9ubWVu"
    "dCBhbmQgci5nZXQoImVudmlyb25tZW50IiwiIikubG93ZXIoKSAhPSBlbnZpcm9ubWVudC5sb3dlcigpOgogICAgICAgICAgICAg"
    "ICAgY29udGludWUKICAgICAgICAgICAgaWYgbGFuZ3VhZ2UgYW5kIHIuZ2V0KCJsYW5ndWFnZSIsIiIpLmxvd2VyKCkgIT0gbGFu"
    "Z3VhZ2UubG93ZXIoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIHE6CiAgICAgICAgICAgICAgICBo"
    "YXlzdGFjayA9ICIgIi5qb2luKFsKICAgICAgICAgICAgICAgICAgICByLmdldCgic3VtbWFyeSIsIiIpLAogICAgICAgICAgICAg"
    "ICAgICAgIHIuZ2V0KCJmdWxsX3J1bGUiLCIiKSwKICAgICAgICAgICAgICAgICAgICByLmdldCgicmVmZXJlbmNlX2tleSIsIiIp"
    "LAogICAgICAgICAgICAgICAgICAgICIgIi5qb2luKHIuZ2V0KCJ0YWdzIixbXSkpLAogICAgICAgICAgICAgICAgXSkubG93ZXIo"
    "KQogICAgICAgICAgICAgICAgaWYgcSBub3QgaW4gaGF5c3RhY2s6CiAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAg"
    "ICAgICAgcmVzdWx0cy5hcHBlbmQocikKICAgICAgICByZXR1cm4gcmVzdWx0cwoKICAgIGRlZiBnZXRfYWxsKHNlbGYpIC0+IGxp"
    "c3RbZGljdF06CiAgICAgICAgcmV0dXJuIHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKCiAgICBkZWYgZGVsZXRlKHNlbGYsIHJlY29y"
    "ZF9pZDogc3RyKSAtPiBib29sOgogICAgICAgIHJlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgZmlsdGVy"
    "ZWQgPSBbciBmb3IgciBpbiByZWNvcmRzIGlmIHIuZ2V0KCJpZCIpICE9IHJlY29yZF9pZF0KICAgICAgICBpZiBsZW4oZmlsdGVy"
    "ZWQpIDwgbGVuKHJlY29yZHMpOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBmaWx0ZXJlZCkKICAgICAgICAg"
    "ICAgcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICBkZWYgYnVpbGRfY29udGV4dF9mb3JfbGFuZ3VhZ2Uoc2Vs"
    "ZiwgbGFuZ3VhZ2U6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBtYXhfY2hhcnM6IGludCA9IDE1MDAp"
    "IC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBCdWlsZCBhIGNvbnRleHQgc3RyaW5nIG9mIGFsbCBydWxlcyBmb3IgYSBnaXZl"
    "biBsYW5ndWFnZS4KICAgICAgICBGb3IgaW5qZWN0aW9uIGludG8gc3lzdGVtIHByb21wdCBiZWZvcmUgY29kZSBzZXNzaW9ucy4K"
    "ICAgICAgICAiIiIKICAgICAgICByZWNvcmRzID0gc2VsZi5zZWFyY2gobGFuZ3VhZ2U9bGFuZ3VhZ2UpCiAgICAgICAgaWYgbm90"
    "IHJlY29yZHM6CiAgICAgICAgICAgIHJldHVybiAiIgoKICAgICAgICBwYXJ0cyA9IFtmIlt7bGFuZ3VhZ2UudXBwZXIoKX0gUlVM"
    "RVMg4oCUIEFQUExZIEJFRk9SRSBXUklUSU5HIENPREVdIl0KICAgICAgICB0b3RhbCA9IDAKICAgICAgICBmb3IgciBpbiByZWNv"
    "cmRzOgogICAgICAgICAgICBlbnRyeSA9IGYi4oCiIHtyLmdldCgncmVmZXJlbmNlX2tleScsJycpfToge3IuZ2V0KCdmdWxsX3J1"
    "bGUnLCcnKX0iCiAgICAgICAgICAgIGlmIHRvdGFsICsgbGVuKGVudHJ5KSA+IG1heF9jaGFyczoKICAgICAgICAgICAgICAgIGJy"
    "ZWFrCiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChlbnRyeSkKICAgICAgICAgICAgdG90YWwgKz0gbGVuKGVudHJ5KQoKICAgICAg"
    "ICBwYXJ0cy5hcHBlbmQoZiJbRU5EIHtsYW5ndWFnZS51cHBlcigpfSBSVUxFU10iKQogICAgICAgIHJldHVybiAiXG4iLmpvaW4o"
    "cGFydHMpCgogICAgZGVmIF9pc19kdXBsaWNhdGUoc2VsZiwgcmVmZXJlbmNlX2tleTogc3RyKSAtPiBib29sOgogICAgICAgIHJl"
    "dHVybiBhbnkoCiAgICAgICAgICAgIHIuZ2V0KCJyZWZlcmVuY2Vfa2V5IiwiIikubG93ZXIoKSA9PSByZWZlcmVuY2Vfa2V5Lmxv"
    "d2VyKCkKICAgICAgICAgICAgZm9yIHIgaW4gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgICkKCiAgICBkZWYgc2VlZF9s"
    "c2xfcnVsZXMoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBTZWVkIHRoZSBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQg"
    "b24gZmlyc3QgcnVuIGlmIHRoZSBEQiBpcyBlbXB0eS4KICAgICAgICBUaGVzZSBhcmUgdGhlIGhhcmQgcnVsZXMgZnJvbSB0aGUg"
    "cHJvamVjdCBzdGFuZGluZyBydWxlcy4KICAgICAgICAiIiIKICAgICAgICBpZiByZWFkX2pzb25sKHNlbGYuX3BhdGgpOgogICAg"
    "ICAgICAgICByZXR1cm4gICMgQWxyZWFkeSBzZWVkZWQKCiAgICAgICAgbHNsX3J1bGVzID0gWwogICAgICAgICAgICAoIkxTTCIs"
    "ICJMU0wiLCAiTk9fVEVSTkFSWSIsCiAgICAgICAgICAgICAiTm8gdGVybmFyeSBvcGVyYXRvcnMgaW4gTFNMIiwKICAgICAgICAg"
    "ICAgICJOZXZlciB1c2UgdGhlIHRlcm5hcnkgb3BlcmF0b3IgKD86KSBpbiBMU0wgc2NyaXB0cy4gIgogICAgICAgICAgICAgIlVz"
    "ZSBpZi9lbHNlIGJsb2NrcyBpbnN0ZWFkLiBMU0wgZG9lcyBub3Qgc3VwcG9ydCB0ZXJuYXJ5LiIsCiAgICAgICAgICAgICAiUmVw"
    "bGFjZSB3aXRoIGlmL2Vsc2UgYmxvY2suIiwgIiIpLAogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fRk9SRUFDSCIsCiAg"
    "ICAgICAgICAgICAiTm8gZm9yZWFjaCBsb29wcyBpbiBMU0wiLAogICAgICAgICAgICAgIkxTTCBoYXMgbm8gZm9yZWFjaCBsb29w"
    "IGNvbnN0cnVjdC4gVXNlIGludGVnZXIgaW5kZXggd2l0aCAiCiAgICAgICAgICAgICAibGxHZXRMaXN0TGVuZ3RoKCkgYW5kIGEg"
    "Zm9yIG9yIHdoaWxlIGxvb3AuIiwKICAgICAgICAgICAgICJVc2U6IGZvcihpbnRlZ2VyIGk9MDsgaTxsbEdldExpc3RMZW5ndGgo"
    "bXlMaXN0KTsgaSsrKSIsICIiKSwKICAgICAgICAgICAgKCJMU0wiLCAiTFNMIiwgIk5PX0dMT0JBTF9BU1NJR05fRlJPTV9GVU5D"
    "IiwKICAgICAgICAgICAgICJObyBnbG9iYWwgdmFyaWFibGUgYXNzaWdubWVudHMgZnJvbSBmdW5jdGlvbiBjYWxscyIsCiAgICAg"
    "ICAgICAgICAiR2xvYmFsIHZhcmlhYmxlIGluaXRpYWxpemF0aW9uIGluIExTTCBjYW5ub3QgY2FsbCBmdW5jdGlvbnMuICIKICAg"
    "ICAgICAgICAgICJJbml0aWFsaXplIGdsb2JhbHMgd2l0aCBsaXRlcmFsIHZhbHVlcyBvbmx5LiAiCiAgICAgICAgICAgICAiQXNz"
    "aWduIGZyb20gZnVuY3Rpb25zIGluc2lkZSBldmVudCBoYW5kbGVycyBvciBvdGhlciBmdW5jdGlvbnMuIiwKICAgICAgICAgICAg"
    "ICJNb3ZlIHRoZSBhc3NpZ25tZW50IGludG8gYW4gZXZlbnQgaGFuZGxlciAoc3RhdGVfZW50cnksIGV0Yy4pIiwgIiIpLAogICAg"
    "ICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fVk9JRF9LRVlXT1JEIiwKICAgICAgICAgICAgICJObyB2b2lkIGtleXdvcmQgaW4g"
    "TFNMIiwKICAgICAgICAgICAgICJMU0wgZG9lcyBub3QgaGF2ZSBhIHZvaWQga2V5d29yZCBmb3IgZnVuY3Rpb24gcmV0dXJuIHR5"
    "cGVzLiAiCiAgICAgICAgICAgICAiRnVuY3Rpb25zIHRoYXQgcmV0dXJuIG5vdGhpbmcgc2ltcGx5IG9taXQgdGhlIHJldHVybiB0"
    "eXBlLiIsCiAgICAgICAgICAgICAiUmVtb3ZlICd2b2lkJyBmcm9tIGZ1bmN0aW9uIHNpZ25hdHVyZS4gIgogICAgICAgICAgICAg"
    "ImUuZy4gbXlGdW5jKCkgeyAuLi4gfSBub3Qgdm9pZCBteUZ1bmMoKSB7IC4uLiB9IiwgIiIpLAogICAgICAgICAgICAoIkxTTCIs"
    "ICJMU0wiLCAiQ09NUExFVEVfU0NSSVBUU19PTkxZIiwKICAgICAgICAgICAgICJBbHdheXMgcHJvdmlkZSBjb21wbGV0ZSBzY3Jp"
    "cHRzLCBuZXZlciBwYXJ0aWFsIGVkaXRzIiwKICAgICAgICAgICAgICJXaGVuIHdyaXRpbmcgb3IgZWRpdGluZyBMU0wgc2NyaXB0"
    "cywgYWx3YXlzIG91dHB1dCB0aGUgY29tcGxldGUgIgogICAgICAgICAgICAgInNjcmlwdC4gTmV2ZXIgcHJvdmlkZSBwYXJ0aWFs"
    "IHNuaXBwZXRzIG9yICdhZGQgdGhpcyBzZWN0aW9uJyAiCiAgICAgICAgICAgICAiaW5zdHJ1Y3Rpb25zLiBUaGUgZnVsbCBzY3Jp"
    "cHQgbXVzdCBiZSBjb3B5LXBhc3RlIHJlYWR5LiIsCiAgICAgICAgICAgICAiV3JpdGUgdGhlIGVudGlyZSBzY3JpcHQgZnJvbSB0"
    "b3AgdG8gYm90dG9tLiIsICIiKSwKICAgICAgICBdCgogICAgICAgIGZvciBlbnYsIGxhbmcsIHJlZiwgc3VtbWFyeSwgZnVsbF9y"
    "dWxlLCByZXNvbHV0aW9uLCBsaW5rIGluIGxzbF9ydWxlczoKICAgICAgICAgICAgc2VsZi5hZGQoZW52LCBsYW5nLCByZWYsIHN1"
    "bW1hcnksIGZ1bGxfcnVsZSwgcmVzb2x1dGlvbiwgbGluaywKICAgICAgICAgICAgICAgICAgICAgdGFncz1bImxzbCIsICJmb3Ji"
    "aWRkZW4iLCAic3RhbmRpbmdfcnVsZSJdKQoKCiMg4pSA4pSAIFRBU0sgTUFOQUdFUiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKY2xhc3MgVGFza01hbmFnZXI6CiAgICAiIiIKICAgIFRhc2svcmVtaW5kZXIgQ1JVRCBhbmQgZHVlLWV2ZW50IGRl"
    "dGVjdGlvbi4KCiAgICBGaWxlOiBtZW1vcmllcy90YXNrcy5qc29ubAoKICAgIFRhc2sgcmVjb3JkIGZpZWxkczoKICAgICAgICBp"
    "ZCwgY3JlYXRlZF9hdCwgZHVlX2F0LCBwcmVfdHJpZ2dlciAoMW1pbiBiZWZvcmUpLAogICAgICAgIHRleHQsIHN0YXR1cyAocGVu"
    "ZGluZ3x0cmlnZ2VyZWR8c25vb3plZHxjb21wbGV0ZWR8Y2FuY2VsbGVkKSwKICAgICAgICBhY2tub3dsZWRnZWRfYXQsIHJldHJ5"
    "X2NvdW50LCBsYXN0X3RyaWdnZXJlZF9hdCwgbmV4dF9yZXRyeV9hdCwKICAgICAgICBzb3VyY2UgKGxvY2FsfGdvb2dsZSksIGdv"
    "b2dsZV9ldmVudF9pZCwgc3luY19zdGF0dXMsIG1ldGFkYXRhCgogICAgRHVlLWV2ZW50IGN5Y2xlOgogICAgICAgIC0gUHJlLXRy"
    "aWdnZXI6IDEgbWludXRlIGJlZm9yZSBkdWUg4oaSIGFubm91bmNlIHVwY29taW5nCiAgICAgICAgLSBEdWUgdHJpZ2dlcjogYXQg"
    "ZHVlIHRpbWUg4oaSIGFsZXJ0IHNvdW5kICsgQUkgY29tbWVudGFyeQogICAgICAgIC0gMy1taW51dGUgd2luZG93OiBpZiBub3Qg"
    "YWNrbm93bGVkZ2VkIOKGkiBzbm9vemUKICAgICAgICAtIDEyLW1pbnV0ZSByZXRyeTogcmUtdHJpZ2dlcgogICAgIiIiCgogICAg"
    "ZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3BhdGggPSBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJ0YXNrcy5qc29u"
    "bCIKCiAgICAjIOKUgOKUgCBDUlVEIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGxvYWRfYWxsKHNlbGYpIC0+"
    "IGxpc3RbZGljdF06CiAgICAgICAgdGFza3MgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgY2hhbmdlZCA9IEZhbHNl"
    "CiAgICAgICAgbm9ybWFsaXplZCA9IFtdCiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIG5vdCBpc2luc3Rh"
    "bmNlKHQsIGRpY3QpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgImlkIiBub3QgaW4gdDoKICAgICAg"
    "ICAgICAgICAgIHRbImlkIl0gPSBmInRhc2tfe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iCiAgICAgICAgICAgICAgICBjaGFuZ2Vk"
    "ID0gVHJ1ZQogICAgICAgICAgICAjIE5vcm1hbGl6ZSBmaWVsZCBuYW1lcwogICAgICAgICAgICBpZiAiZHVlX2F0IiBub3QgaW4g"
    "dDoKICAgICAgICAgICAgICAgIHRbImR1ZV9hdCJdID0gdC5nZXQoImR1ZSIpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1"
    "ZQogICAgICAgICAgICB0LnNldGRlZmF1bHQoInN0YXR1cyIsICAgICAgICAgICAicGVuZGluZyIpCiAgICAgICAgICAgIHQuc2V0"
    "ZGVmYXVsdCgicmV0cnlfY291bnQiLCAgICAgIDApCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiYWNrbm93bGVkZ2VkX2F0Iiwg"
    "IE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgibGFzdF90cmlnZ2VyZWRfYXQiLE5vbmUpCiAgICAgICAgICAgIHQuc2V0"
    "ZGVmYXVsdCgibmV4dF9yZXRyeV9hdCIsICAgIE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgicHJlX2Fubm91bmNlZCIs"
    "ICAgIEZhbHNlKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoInNvdXJjZSIsICAgICAgICAgICAibG9jYWwiKQogICAgICAgICAg"
    "ICB0LnNldGRlZmF1bHQoImdvb2dsZV9ldmVudF9pZCIsICBOb25lKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoInN5bmNfc3Rh"
    "dHVzIiwgICAgICAicGVuZGluZyIpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgibWV0YWRhdGEiLCAgICAgICAgIHt9KQogICAg"
    "ICAgICAgICB0LnNldGRlZmF1bHQoImNyZWF0ZWRfYXQiLCAgICAgICBsb2NhbF9ub3dfaXNvKCkpCgogICAgICAgICAgICAjIENv"
    "bXB1dGUgcHJlX3RyaWdnZXIgaWYgbWlzc2luZwogICAgICAgICAgICBpZiB0LmdldCgiZHVlX2F0IikgYW5kIG5vdCB0LmdldCgi"
    "cHJlX3RyaWdnZXIiKToKICAgICAgICAgICAgICAgIGR0ID0gcGFyc2VfaXNvKHRbImR1ZV9hdCJdKQogICAgICAgICAgICAgICAg"
    "aWYgZHQ6CiAgICAgICAgICAgICAgICAgICAgcHJlID0gZHQgLSB0aW1lZGVsdGEobWludXRlcz0xKQogICAgICAgICAgICAgICAg"
    "ICAgIHRbInByZV90cmlnZ2VyIl0gPSBwcmUuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAgICAg"
    "ICBjaGFuZ2VkID0gVHJ1ZQoKICAgICAgICAgICAgbm9ybWFsaXplZC5hcHBlbmQodCkKCiAgICAgICAgaWYgY2hhbmdlZDoKICAg"
    "ICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgbm9ybWFsaXplZCkKICAgICAgICByZXR1cm4gbm9ybWFsaXplZAoKICAg"
    "IGRlZiBzYXZlX2FsbChzZWxmLCB0YXNrczogbGlzdFtkaWN0XSkgLT4gTm9uZToKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9w"
    "YXRoLCB0YXNrcykKCiAgICBkZWYgYWRkKHNlbGYsIHRleHQ6IHN0ciwgZHVlX2R0OiBkYXRldGltZSwKICAgICAgICAgICAgc291"
    "cmNlOiBzdHIgPSAibG9jYWwiKSAtPiBkaWN0OgogICAgICAgIHByZSA9IGR1ZV9kdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpCiAg"
    "ICAgICAgdGFzayA9IHsKICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgICBmInRhc2tfe3V1aWQudXVpZDQoKS5oZXhbOjEw"
    "XX0iLAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICAgICAgIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgImR1ZV9hdCI6"
    "ICAgICAgICAgICBkdWVfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICJwcmVfdHJpZ2dlciI6"
    "ICAgICAgcHJlLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAidGV4dCI6ICAgICAgICAgICAgIHRl"
    "eHQuc3RyaXAoKSwKICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgICAgICAicGVuZGluZyIsCiAgICAgICAgICAgICJhY2tub3ds"
    "ZWRnZWRfYXQiOiAgTm9uZSwKICAgICAgICAgICAgInJldHJ5X2NvdW50IjogICAgICAwLAogICAgICAgICAgICAibGFzdF90cmln"
    "Z2VyZWRfYXQiOk5vbmUsCiAgICAgICAgICAgICJuZXh0X3JldHJ5X2F0IjogICAgTm9uZSwKICAgICAgICAgICAgInByZV9hbm5v"
    "dW5jZWQiOiAgICBGYWxzZSwKICAgICAgICAgICAgInNvdXJjZSI6ICAgICAgICAgICBzb3VyY2UsCiAgICAgICAgICAgICJnb29n"
    "bGVfZXZlbnRfaWQiOiAgTm9uZSwKICAgICAgICAgICAgInN5bmNfc3RhdHVzIjogICAgICAicGVuZGluZyIsCiAgICAgICAgICAg"
    "ICJtZXRhZGF0YSI6ICAgICAgICAge30sCiAgICAgICAgfQogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAg"
    "dGFza3MuYXBwZW5kKHRhc2spCiAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICByZXR1cm4gdGFzawoKICAgIGRl"
    "ZiB1cGRhdGVfc3RhdHVzKHNlbGYsIHRhc2tfaWQ6IHN0ciwgc3RhdHVzOiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICBhY2tu"
    "b3dsZWRnZWQ6IGJvb2wgPSBGYWxzZSkgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkK"
    "ICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0gdGFza19pZDoKICAgICAgICAgICAg"
    "ICAgIHRbInN0YXR1cyJdID0gc3RhdHVzCiAgICAgICAgICAgICAgICBpZiBhY2tub3dsZWRnZWQ6CiAgICAgICAgICAgICAgICAg"
    "ICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFz"
    "a3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNvbXBsZXRlKHNlbGYsIHRh"
    "c2tfaWQ6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBmb3Ig"
    "dCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0gdGFza19pZDoKICAgICAgICAgICAgICAgIHRbInN0YXR1"
    "cyJdICAgICAgICAgID0gImNvbXBsZXRlZCIKICAgICAgICAgICAgICAgIHRbImFja25vd2xlZGdlZF9hdCJdID0gbG9jYWxfbm93"
    "X2lzbygpCiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICAgICAgcmV0dXJuIHQKICAgICAg"
    "ICByZXR1cm4gTm9uZQoKICAgIGRlZiBjYW5jZWwoc2VsZiwgdGFza19pZDogc3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAg"
    "ICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQi"
    "KSA9PSB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gICAgICAgICAgPSAiY2FuY2VsbGVkIgogICAgICAgICAg"
    "ICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwo"
    "dGFza3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNsZWFyX2NvbXBsZXRl"
    "ZChzZWxmKSAtPiBpbnQ6CiAgICAgICAgdGFza3MgICAgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBrZXB0ICAgICA9IFt0IGZv"
    "ciB0IGluIHRhc2tzCiAgICAgICAgICAgICAgICAgICAgaWYgdC5nZXQoInN0YXR1cyIpIG5vdCBpbiB7ImNvbXBsZXRlZCIsImNh"
    "bmNlbGxlZCJ9XQogICAgICAgIHJlbW92ZWQgID0gbGVuKHRhc2tzKSAtIGxlbihrZXB0KQogICAgICAgIGlmIHJlbW92ZWQ6CiAg"
    "ICAgICAgICAgIHNlbGYuc2F2ZV9hbGwoa2VwdCkKICAgICAgICByZXR1cm4gcmVtb3ZlZAoKICAgIGRlZiB1cGRhdGVfZ29vZ2xl"
    "X3N5bmMoc2VsZiwgdGFza19pZDogc3RyLCBzeW5jX3N0YXR1czogc3RyLAogICAgICAgICAgICAgICAgICAgICAgICAgICBnb29n"
    "bGVfZXZlbnRfaWQ6IHN0ciA9ICIiLAogICAgICAgICAgICAgICAgICAgICAgICAgICBlcnJvcjogc3RyID0gIiIpIC0+IE9wdGlv"
    "bmFsW2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAg"
    "ICAgIGlmIHQuZ2V0KCJpZCIpID09IHRhc2tfaWQ6CiAgICAgICAgICAgICAgICB0WyJzeW5jX3N0YXR1cyJdICAgID0gc3luY19z"
    "dGF0dXMKICAgICAgICAgICAgICAgIHRbImxhc3Rfc3luY2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAg"
    "IGlmIGdvb2dsZV9ldmVudF9pZDoKICAgICAgICAgICAgICAgICAgICB0WyJnb29nbGVfZXZlbnRfaWQiXSA9IGdvb2dsZV9ldmVu"
    "dF9pZAogICAgICAgICAgICAgICAgaWYgZXJyb3I6CiAgICAgICAgICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJtZXRhZGF0YSIs"
    "IHt9KQogICAgICAgICAgICAgICAgICAgIHRbIm1ldGFkYXRhIl1bImdvb2dsZV9zeW5jX2Vycm9yIl0gPSBlcnJvcls6MjQwXQog"
    "ICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJu"
    "IE5vbmUKCiAgICAjIOKUgOKUgCBEVUUgRVZFTlQgREVURUNUSU9OIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGdldF9kdWVfZXZlbnRzKHNlbGYpIC0+IGxpc3RbdHVwbGVbc3RyLCBkaWN0"
    "XV06CiAgICAgICAgIiIiCiAgICAgICAgQ2hlY2sgYWxsIHRhc2tzIGZvciBkdWUvcHJlLXRyaWdnZXIvcmV0cnkgZXZlbnRzLgog"
    "ICAgICAgIFJldHVybnMgbGlzdCBvZiAoZXZlbnRfdHlwZSwgdGFzaykgdHVwbGVzLgogICAgICAgIGV2ZW50X3R5cGU6ICJwcmUi"
    "IHwgImR1ZSIgfCAicmV0cnkiCgogICAgICAgIE1vZGlmaWVzIHRhc2sgc3RhdHVzZXMgaW4gcGxhY2UgYW5kIHNhdmVzLgogICAg"
    "ICAgIENhbGwgZnJvbSBBUFNjaGVkdWxlciBldmVyeSAzMCBzZWNvbmRzLgogICAgICAgICIiIgogICAgICAgIG5vdyAgICA9IGRh"
    "dGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKQogICAgICAgIHRhc2tzICA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGV2ZW50cyA9"
    "IFtdCiAgICAgICAgY2hhbmdlZCA9IEZhbHNlCgogICAgICAgIGZvciB0YXNrIGluIHRhc2tzOgogICAgICAgICAgICBpZiB0YXNr"
    "LmdldCgiYWNrbm93bGVkZ2VkX2F0Iik6CiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgc3RhdHVzICAgPSB0"
    "YXNrLmdldCgic3RhdHVzIiwgInBlbmRpbmciKQogICAgICAgICAgICBkdWUgICAgICA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2su"
    "Z2V0KCJkdWVfYXQiKSkKICAgICAgICAgICAgcHJlICAgICAgPSBzZWxmLl9wYXJzZV9sb2NhbCh0YXNrLmdldCgicHJlX3RyaWdn"
    "ZXIiKSkKICAgICAgICAgICAgbmV4dF9yZXQgPSBzZWxmLl9wYXJzZV9sb2NhbCh0YXNrLmdldCgibmV4dF9yZXRyeV9hdCIpKQog"
    "ICAgICAgICAgICBkZWFkbGluZSA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJhbGVydF9kZWFkbGluZSIpKQoKICAgICAg"
    "ICAgICAgIyBQcmUtdHJpZ2dlcgogICAgICAgICAgICBpZiAoc3RhdHVzID09ICJwZW5kaW5nIiBhbmQgcHJlIGFuZCBub3cgPj0g"
    "cHJlCiAgICAgICAgICAgICAgICAgICAgYW5kIG5vdCB0YXNrLmdldCgicHJlX2Fubm91bmNlZCIpKToKICAgICAgICAgICAgICAg"
    "IHRhc2tbInByZV9hbm5vdW5jZWQiXSA9IFRydWUKICAgICAgICAgICAgICAgIGV2ZW50cy5hcHBlbmQoKCJwcmUiLCB0YXNrKSkK"
    "ICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgICAgICAjIER1ZSB0cmlnZ2VyCiAgICAgICAgICAgIGlmIHN0"
    "YXR1cyA9PSAicGVuZGluZyIgYW5kIGR1ZSBhbmQgbm93ID49IGR1ZToKICAgICAgICAgICAgICAgIHRhc2tbInN0YXR1cyJdICAg"
    "ICAgICAgICA9ICJ0cmlnZ2VyZWQiCiAgICAgICAgICAgICAgICB0YXNrWyJsYXN0X3RyaWdnZXJlZF9hdCJdPSBsb2NhbF9ub3df"
    "aXNvKCkKICAgICAgICAgICAgICAgIHRhc2tbImFsZXJ0X2RlYWRsaW5lIl0gICA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRl"
    "dGltZS5ub3coKS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0zKQogICAgICAgICAgICAgICAgKS5pc29mb3JtYXQo"
    "dGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgZXZlbnRzLmFwcGVuZCgoImR1ZSIsIHRhc2spKQogICAgICAgICAg"
    "ICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICAjIFNub296ZSBhZnRlciAz"
    "LW1pbnV0ZSB3aW5kb3cKICAgICAgICAgICAgaWYgc3RhdHVzID09ICJ0cmlnZ2VyZWQiIGFuZCBkZWFkbGluZSBhbmQgbm93ID49"
    "IGRlYWRsaW5lOgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICAgID0gInNub296ZWQiCiAgICAgICAgICAgICAg"
    "ICB0YXNrWyJuZXh0X3JldHJ5X2F0Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgp"
    "ICsgdGltZWRlbHRhKG1pbnV0ZXM9MTIpCiAgICAgICAgICAgICAgICApLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAg"
    "ICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICMgUmV0cnkK"
    "ICAgICAgICAgICAgaWYgc3RhdHVzIGluIHsicmV0cnlfcGVuZGluZyIsInNub296ZWQifSBhbmQgbmV4dF9yZXQgYW5kIG5vdyA+"
    "PSBuZXh0X3JldDoKICAgICAgICAgICAgICAgIHRhc2tbInN0YXR1cyJdICAgICAgICAgICAgPSAidHJpZ2dlcmVkIgogICAgICAg"
    "ICAgICAgICAgdGFza1sicmV0cnlfY291bnQiXSAgICAgICA9IGludCh0YXNrLmdldCgicmV0cnlfY291bnQiLDApKSArIDEKICAg"
    "ICAgICAgICAgICAgIHRhc2tbImxhc3RfdHJpZ2dlcmVkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHRh"
    "c2tbImFsZXJ0X2RlYWRsaW5lIl0gICAgPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgp"
    "ICsgdGltZWRlbHRhKG1pbnV0ZXM9MykKICAgICAgICAgICAgICAgICkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAg"
    "ICAgICAgICAgICAgIHRhc2tbIm5leHRfcmV0cnlfYXQiXSAgICAgPSBOb25lCiAgICAgICAgICAgICAgICBldmVudHMuYXBwZW5k"
    "KCgicmV0cnkiLCB0YXNrKSkKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgIGlmIGNoYW5nZWQ6CiAgICAg"
    "ICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgcmV0dXJuIGV2ZW50cwoKICAgIGRlZiBfcGFyc2VfbG9jYWwoc2Vs"
    "ZiwgdmFsdWU6IHN0cikgLT4gT3B0aW9uYWxbZGF0ZXRpbWVdOgogICAgICAgICIiIlBhcnNlIElTTyBzdHJpbmcgdG8gdGltZXpv"
    "bmUtYXdhcmUgZGF0ZXRpbWUgZm9yIGNvbXBhcmlzb24uIiIiCiAgICAgICAgZHQgPSBwYXJzZV9pc28odmFsdWUpCiAgICAgICAg"
    "aWYgZHQgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBpZiBkdC50emluZm8gaXMgTm9uZToKICAgICAg"
    "ICAgICAgZHQgPSBkdC5hc3RpbWV6b25lKCkKICAgICAgICByZXR1cm4gZHQKCiAgICAjIOKUgOKUgCBOQVRVUkFMIExBTkdVQUdF"
    "IFBBUlNJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBAc3RhdGljbWV0aG9kCiAgICBk"
    "ZWYgY2xhc3NpZnlfaW50ZW50KHRleHQ6IHN0cikgLT4gZGljdDoKICAgICAgICAiIiIKICAgICAgICBDbGFzc2lmeSB1c2VyIGlu"
    "cHV0IGFzIHRhc2svcmVtaW5kZXIvdGltZXIvY2hhdC4KICAgICAgICBSZXR1cm5zIHsiaW50ZW50Ijogc3RyLCAiY2xlYW5lZF9p"
    "bnB1dCI6IHN0cn0KICAgICAgICAiIiIKICAgICAgICBpbXBvcnQgcmUKICAgICAgICAjIFN0cmlwIGNvbW1vbiBpbnZvY2F0aW9u"
    "IHByZWZpeGVzCiAgICAgICAgY2xlYW5lZCA9IHJlLnN1YigKICAgICAgICAgICAgcmYiXlxzKig/OntERUNLX05BTUUubG93ZXIo"
    "KX18aGV5XHMre0RFQ0tfTkFNRS5sb3dlcigpfSlccyosP1xzKls6XC1dP1xzKiIsCiAgICAgICAgICAgICIiLCB0ZXh0LCBmbGFn"
    "cz1yZS5JCiAgICAgICAgKS5zdHJpcCgpCgogICAgICAgIGxvdyA9IGNsZWFuZWQubG93ZXIoKQoKICAgICAgICB0aW1lcl9wYXRz"
    "ICAgID0gW3IiXGJzZXQoPzpccythKT9ccyt0aW1lclxiIiwgciJcYnRpbWVyXHMrZm9yXGIiLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgciJcYnN0YXJ0KD86XHMrYSk/XHMrdGltZXJcYiJdCiAgICAgICAgcmVtaW5kZXJfcGF0cyA9IFtyIlxicmVtaW5kIG1l"
    "XGIiLCByIlxic2V0KD86XHMrYSk/XHMrcmVtaW5kZXJcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICByIlxiYWRkKD86XHMr"
    "YSk/XHMrcmVtaW5kZXJcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICByIlxic2V0KD86XHMrYW4/KT9ccythbGFybVxiIiwg"
    "ciJcYmFsYXJtXHMrZm9yXGIiXQogICAgICAgIHRhc2tfcGF0cyAgICAgPSBbciJcYmFkZCg/OlxzK2EpP1xzK3Rhc2tcYiIsCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICByIlxiY3JlYXRlKD86XHMrYSk/XHMrdGFza1xiIiwgciJcYm5ld1xzK3Rhc2tcYiJdCgog"
    "ICAgICAgIGltcG9ydCByZSBhcyBfcmUKICAgICAgICBpZiBhbnkoX3JlLnNlYXJjaChwLCBsb3cpIGZvciBwIGluIHRpbWVyX3Bh"
    "dHMpOgogICAgICAgICAgICBpbnRlbnQgPSAidGltZXIiCiAgICAgICAgZWxpZiBhbnkoX3JlLnNlYXJjaChwLCBsb3cpIGZvciBw"
    "IGluIHJlbWluZGVyX3BhdHMpOgogICAgICAgICAgICBpbnRlbnQgPSAicmVtaW5kZXIiCiAgICAgICAgZWxpZiBhbnkoX3JlLnNl"
    "YXJjaChwLCBsb3cpIGZvciBwIGluIHRhc2tfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9ICJ0YXNrIgogICAgICAgIGVsc2U6"
    "CiAgICAgICAgICAgIGludGVudCA9ICJjaGF0IgoKICAgICAgICByZXR1cm4geyJpbnRlbnQiOiBpbnRlbnQsICJjbGVhbmVkX2lu"
    "cHV0IjogY2xlYW5lZH0KCiAgICBAc3RhdGljbWV0aG9kCiAgICBkZWYgcGFyc2VfZHVlX2RhdGV0aW1lKHRleHQ6IHN0cikgLT4g"
    "T3B0aW9uYWxbZGF0ZXRpbWVdOgogICAgICAgICIiIgogICAgICAgIFBhcnNlIG5hdHVyYWwgbGFuZ3VhZ2UgdGltZSBleHByZXNz"
    "aW9uIGZyb20gdGFzayB0ZXh0LgogICAgICAgIEhhbmRsZXM6ICJpbiAzMCBtaW51dGVzIiwgImF0IDNwbSIsICJ0b21vcnJvdyBh"
    "dCA5YW0iLAogICAgICAgICAgICAgICAgICJpbiAyIGhvdXJzIiwgImF0IDE1OjMwIiwgZXRjLgogICAgICAgIFJldHVybnMgYSBk"
    "YXRldGltZSBvciBOb25lIGlmIHVucGFyc2VhYmxlLgogICAgICAgICIiIgogICAgICAgIGltcG9ydCByZQogICAgICAgIG5vdyAg"
    "PSBkYXRldGltZS5ub3coKQogICAgICAgIGxvdyAgPSB0ZXh0Lmxvd2VyKCkuc3RyaXAoKQoKICAgICAgICAjICJpbiBYIG1pbnV0"
    "ZXMvaG91cnMvZGF5cyIKICAgICAgICBtID0gcmUuc2VhcmNoKAogICAgICAgICAgICByImluXHMrKFxkKylccyoobWludXRlfG1p"
    "bnxob3VyfGhyfGRheXxzZWNvbmR8c2VjKSIsCiAgICAgICAgICAgIGxvdwogICAgICAgICkKICAgICAgICBpZiBtOgogICAgICAg"
    "ICAgICBuICAgID0gaW50KG0uZ3JvdXAoMSkpCiAgICAgICAgICAgIHVuaXQgPSBtLmdyb3VwKDIpCiAgICAgICAgICAgIGlmICJt"
    "aW4iIGluIHVuaXQ6ICByZXR1cm4gbm93ICsgdGltZWRlbHRhKG1pbnV0ZXM9bikKICAgICAgICAgICAgaWYgImhvdXIiIGluIHVu"
    "aXQgb3IgImhyIiBpbiB1bml0OiByZXR1cm4gbm93ICsgdGltZWRlbHRhKGhvdXJzPW4pCiAgICAgICAgICAgIGlmICJkYXkiICBp"
    "biB1bml0OiByZXR1cm4gbm93ICsgdGltZWRlbHRhKGRheXM9bikKICAgICAgICAgICAgaWYgInNlYyIgIGluIHVuaXQ6IHJldHVy"
    "biBub3cgKyB0aW1lZGVsdGEoc2Vjb25kcz1uKQoKICAgICAgICAjICJhdCBISDpNTSIgb3IgImF0IEg6TU1hbS9wbSIKICAgICAg"
    "ICBtID0gcmUuc2VhcmNoKAogICAgICAgICAgICByImF0XHMrKFxkezEsMn0pKD86OihcZHsyfSkpP1xzKihhbXxwbSk/IiwKICAg"
    "ICAgICAgICAgbG93CiAgICAgICAgKQogICAgICAgIGlmIG06CiAgICAgICAgICAgIGhyICA9IGludChtLmdyb3VwKDEpKQogICAg"
    "ICAgICAgICBtbiAgPSBpbnQobS5ncm91cCgyKSkgaWYgbS5ncm91cCgyKSBlbHNlIDAKICAgICAgICAgICAgYXBtID0gbS5ncm91"
    "cCgzKQogICAgICAgICAgICBpZiBhcG0gPT0gInBtIiBhbmQgaHIgPCAxMjogaHIgKz0gMTIKICAgICAgICAgICAgaWYgYXBtID09"
    "ICJhbSIgYW5kIGhyID09IDEyOiBociA9IDAKICAgICAgICAgICAgZHQgPSBub3cucmVwbGFjZShob3VyPWhyLCBtaW51dGU9bW4s"
    "IHNlY29uZD0wLCBtaWNyb3NlY29uZD0wKQogICAgICAgICAgICBpZiBkdCA8PSBub3c6CiAgICAgICAgICAgICAgICBkdCArPSB0"
    "aW1lZGVsdGEoZGF5cz0xKQogICAgICAgICAgICByZXR1cm4gZHQKCiAgICAgICAgIyAidG9tb3Jyb3cgYXQgLi4uIiAgKHJlY3Vy"
    "c2Ugb24gdGhlICJhdCIgcGFydCkKICAgICAgICBpZiAidG9tb3Jyb3ciIGluIGxvdzoKICAgICAgICAgICAgdG9tb3Jyb3dfdGV4"
    "dCA9IHJlLnN1YihyInRvbW9ycm93IiwgIiIsIGxvdykuc3RyaXAoKQogICAgICAgICAgICByZXN1bHQgPSBUYXNrTWFuYWdlci5w"
    "YXJzZV9kdWVfZGF0ZXRpbWUodG9tb3Jyb3dfdGV4dCkKICAgICAgICAgICAgaWYgcmVzdWx0OgogICAgICAgICAgICAgICAgcmV0"
    "dXJuIHJlc3VsdCArIHRpbWVkZWx0YShkYXlzPTEpCgogICAgICAgIHJldHVybiBOb25lCgoKIyDilIDilIAgUkVRVUlSRU1FTlRT"
    "LlRYVCBHRU5FUkFUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACmRlZiB3cml0ZV9yZXF1aXJlbWVudHNfdHh0KCkgLT4gTm9uZToKICAgICIiIgogICAgV3JpdGUgcmVxdWlyZW1l"
    "bnRzLnR4dCBuZXh0IHRvIHRoZSBkZWNrIGZpbGUgb24gZmlyc3QgcnVuLgogICAgSGVscHMgdXNlcnMgaW5zdGFsbCBhbGwgZGVw"
    "ZW5kZW5jaWVzIHdpdGggb25lIHBpcCBjb21tYW5kLgogICAgIiIiCiAgICByZXFfcGF0aCA9IFBhdGgoQ0ZHLmdldCgiYmFzZV9k"
    "aXIiLCBzdHIoU0NSSVBUX0RJUikpKSAvICJyZXF1aXJlbWVudHMudHh0IgogICAgaWYgcmVxX3BhdGguZXhpc3RzKCk6CiAgICAg"
    "ICAgcmV0dXJuCgogICAgY29udGVudCA9ICIiIlwKIyBNb3JnYW5uYSBEZWNrIOKAlCBSZXF1aXJlZCBEZXBlbmRlbmNpZXMKIyBJ"
    "bnN0YWxsIGFsbCB3aXRoOiBwaXAgaW5zdGFsbCAtciByZXF1aXJlbWVudHMudHh0CgojIENvcmUgVUkKUHlTaWRlNgoKIyBTY2hl"
    "ZHVsaW5nIChpZGxlIHRpbWVyLCBhdXRvc2F2ZSwgcmVmbGVjdGlvbiBjeWNsZXMpCmFwc2NoZWR1bGVyCgojIExvZ2dpbmcKbG9n"
    "dXJ1CgojIFNvdW5kIHBsYXliYWNrIChXQVYgKyBNUDMpCnB5Z2FtZQoKIyBEZXNrdG9wIHNob3J0Y3V0IGNyZWF0aW9uIChXaW5k"
    "b3dzIG9ubHkpCnB5d2luMzIKCiMgU3lzdGVtIG1vbml0b3JpbmcgKENQVSwgUkFNLCBkcml2ZXMsIG5ldHdvcmspCnBzdXRpbAoK"
    "IyBIVFRQIHJlcXVlc3RzCnJlcXVlc3RzCgojIEdvb2dsZSBpbnRlZ3JhdGlvbiAoQ2FsZW5kYXIsIERyaXZlLCBEb2NzLCBHbWFp"
    "bCkKZ29vZ2xlLWFwaS1weXRob24tY2xpZW50Cmdvb2dsZS1hdXRoLW9hdXRobGliCmdvb2dsZS1hdXRoCgojIOKUgOKUgCBPcHRp"
    "b25hbCAobG9jYWwgbW9kZWwgb25seSkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiMgVW5jb21tZW50IGlmIHVzaW5nIGEgbG9jYWwgSHVnZ2luZ0ZhY2UgbW9kZWw6CiMgdG9yY2gKIyB0cmFu"
    "c2Zvcm1lcnMKIyBhY2NlbGVyYXRlCgojIOKUgOKUgCBPcHRpb25hbCAoTlZJRElBIEdQVSBtb25pdG9yaW5nKSDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBVbmNvbW1lbnQgaWYgeW91IGhhdmUgYW4gTlZJRElBIEdQVToK"
    "IyBweW52bWwKIiIiCiAgICByZXFfcGF0aC53cml0ZV90ZXh0KGNvbnRlbnQsIGVuY29kaW5nPSJ1dGYtOCIpCgoKIyDilIDilIAg"
    "UEFTUyA0IENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1lbW9yeSwgU2Vzc2lvbiwgTGVzc29uc0xlYXJu"
    "ZWQsIFRhc2tNYW5hZ2VyIGFsbCBkZWZpbmVkLgojIExTTCBGb3JiaWRkZW4gUnVsZXNldCBhdXRvLXNlZWRlZCBvbiBmaXJzdCBy"
    "dW4uCiMgcmVxdWlyZW1lbnRzLnR4dCB3cml0dGVuIG9uIGZpcnN0IHJ1bi4KIwojIE5leHQ6IFBhc3MgNSDigJQgVGFiIENvbnRl"
    "bnQgQ2xhc3NlcwojIChTTFNjYW5zVGFiLCBTTENvbW1hbmRzVGFiLCBKb2JUcmFja2VyVGFiLCBSZWNvcmRzVGFiLAojICBUYXNr"
    "c1RhYiwgU2VsZlRhYiwgRGlhZ25vc3RpY3NUYWIpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDU6"
    "IFRBQiBDT05URU5UIENMQVNTRVMKIwojIFRhYnMgZGVmaW5lZCBoZXJlOgojICAgU0xTY2Fuc1RhYiAgICAgIOKAlCBncmltb2ly"
    "ZS1jYXJkIHN0eWxlLCByZWJ1aWx0IChEZWxldGUgYWRkZWQsIE1vZGlmeSBmaXhlZCwKIyAgICAgICAgICAgICAgICAgICAgIHBh"
    "cnNlciBmaXhlZCwgY29weS10by1jbGlwYm9hcmQgcGVyIGl0ZW0pCiMgICBTTENvbW1hbmRzVGFiICAg4oCUIGdvdGhpYyB0YWJs"
    "ZSwgY29weSBjb21tYW5kIHRvIGNsaXBib2FyZAojICAgSm9iVHJhY2tlclRhYiAgIOKAlCBmdWxsIHJlYnVpbGQgZnJvbSBzcGVj"
    "LCBDU1YvVFNWIGV4cG9ydAojICAgUmVjb3Jkc1RhYiAgICAgIOKAlCBHb29nbGUgRHJpdmUvRG9jcyB3b3Jrc3BhY2UKIyAgIFRh"
    "c2tzVGFiICAgICAgICDigJQgdGFzayByZWdpc3RyeSArIG1pbmkgY2FsZW5kYXIKIyAgIFNlbGZUYWIgICAgICAgICDigJQgaWRs"
    "ZSBuYXJyYXRpdmUgb3V0cHV0ICsgUG9JIGxpc3QKIyAgIERpYWdub3N0aWNzVGFiICDigJQgbG9ndXJ1IG91dHB1dCArIGhhcmR3"
    "YXJlIHJlcG9ydCArIGpvdXJuYWwgbG9hZCBub3RpY2VzCiMgICBMZXNzb25zVGFiICAgICAg4oCUIExTTCBGb3JiaWRkZW4gUnVs"
    "ZXNldCArIGNvZGUgbGVzc29ucyBicm93c2VyCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgppbXBvcnQgcmUgYXMgX3JlCgoKIyDilIDilIAgU0hB"
    "UkVEIEdPVEhJQyBUQUJMRSBTVFlMRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKZGVmIF9nb3RoaWNfdGFibGVfc3R5bGUoKSAtPiBzdHI6CiAgICByZXR1cm4gZiIiIgogICAg"
    "ICAgIFFUYWJsZVdpZGdldCB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7Q19CRzJ9OwogICAgICAgICAgICBjb2xvcjoge0Nf"
    "R09MRH07CiAgICAgICAgICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgICAgICAgICAgZ3JpZGxpbmUt"
    "Y29sb3I6IHtDX0JPUkRFUn07CiAgICAgICAgICAgIGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7CiAgICAgICAgICAg"
    "IGZvbnQtc2l6ZTogMTFweDsKICAgICAgICB9fQogICAgICAgIFFUYWJsZVdpZGdldDo6aXRlbTpzZWxlY3RlZCB7ewogICAgICAg"
    "ICAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07CiAgICAg"
    "ICAgfX0KICAgICAgICBRVGFibGVXaWRnZXQ6Oml0ZW06YWx0ZXJuYXRlIHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0JH"
    "M307CiAgICAgICAgfX0KICAgICAgICBRSGVhZGVyVmlldzo6c2VjdGlvbiB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7Q19C"
    "RzN9OwogICAgICAgICAgICBjb2xvcjoge0NfR09MRH07CiAgICAgICAgICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05f"
    "RElNfTsKICAgICAgICAgICAgcGFkZGluZzogNHB4IDZweDsKICAgICAgICAgICAgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBz"
    "ZXJpZjsKICAgICAgICAgICAgZm9udC1zaXplOiAxMHB4OwogICAgICAgICAgICBmb250LXdlaWdodDogYm9sZDsKICAgICAgICAg"
    "ICAgbGV0dGVyLXNwYWNpbmc6IDFweDsKICAgICAgICB9fQogICAgIiIiCgpkZWYgX2dvdGhpY19idG4odGV4dDogc3RyLCB0b29s"
    "dGlwOiBzdHIgPSAiIikgLT4gUVB1c2hCdXR0b246CiAgICBidG4gPSBRUHVzaEJ1dHRvbih0ZXh0KQogICAgYnRuLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgIGYi"
    "Ym9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgIGYiZm9udC1mYW1pbHk6"
    "IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGlu"
    "ZzogNHB4IDEwcHg7IGxldHRlci1zcGFjaW5nOiAxcHg7IgogICAgKQogICAgaWYgdG9vbHRpcDoKICAgICAgICBidG4uc2V0VG9v"
    "bFRpcCh0b29sdGlwKQogICAgcmV0dXJuIGJ0bgoKZGVmIF9zZWN0aW9uX2xibCh0ZXh0OiBzdHIpIC0+IFFMYWJlbDoKICAgIGxi"
    "bCA9IFFMYWJlbCh0ZXh0KQogICAgbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6"
    "ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgIGYibGV0dGVyLXNwYWNpbmc6IDJweDsgZm9udC1mYW1pbHk6IHtE"
    "RUNLX0ZPTlR9LCBzZXJpZjsiCiAgICApCiAgICByZXR1cm4gbGJsCgoKIyDilIDilIAgU0wgU0NBTlMgVEFCIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTTFNjYW5zVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBTZWNvbmQgTGlm"
    "ZSBhdmF0YXIgc2Nhbm5lciByZXN1bHRzIG1hbmFnZXIuCiAgICBSZWJ1aWx0IGZyb20gc3BlYzoKICAgICAgLSBDYXJkL2dyaW1v"
    "aXJlLWVudHJ5IHN0eWxlIGRpc3BsYXkKICAgICAgLSBBZGQgKHdpdGggdGltZXN0YW1wLWF3YXJlIHBhcnNlcikKICAgICAgLSBE"
    "aXNwbGF5IChjbGVhbiBpdGVtL2NyZWF0b3IgdGFibGUpCiAgICAgIC0gTW9kaWZ5IChlZGl0IG5hbWUsIGRlc2NyaXB0aW9uLCBp"
    "bmRpdmlkdWFsIGl0ZW1zKQogICAgICAtIERlbGV0ZSAod2FzIG1pc3Npbmcg4oCUIG5vdyBwcmVzZW50KQogICAgICAtIFJlLXBh"
    "cnNlICh3YXMgJ1JlZnJlc2gnIOKAlCByZS1ydW5zIHBhcnNlciBvbiBzdG9yZWQgcmF3IHRleHQpCiAgICAgIC0gQ29weS10by1j"
    "bGlwYm9hcmQgb24gYW55IGl0ZW0KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBtZW1vcnlfZGlyOiBQYXRoLCBwYXJl"
    "bnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAgICA9IGNmZ19wYXRo"
    "KCJzbCIpIC8gInNsX3NjYW5zLmpzb25sIgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNl"
    "bGYuX3NlbGVjdGVkX2lkOiBPcHRpb25hbFtzdHJdID0gTm9uZQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxm"
    "LnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2Vs"
    "ZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoK"
    "ICAgICAgICAjIEJ1dHRvbiBiYXIKICAgICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICAg"
    "PSBfZ290aGljX2J0bigi4pymIEFkZCIsICAgICAiQWRkIGEgbmV3IHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9kaXNwbGF5ID0g"
    "X2dvdGhpY19idG4oIuKdpyBEaXNwbGF5IiwgIlNob3cgc2VsZWN0ZWQgc2NhbiBkZXRhaWxzIikKICAgICAgICBzZWxmLl9idG5f"
    "bW9kaWZ5ICA9IF9nb3RoaWNfYnRuKCLinKcgTW9kaWZ5IiwgICJFZGl0IHNlbGVjdGVkIHNjYW4iKQogICAgICAgIHNlbGYuX2J0"
    "bl9kZWxldGUgID0gX2dvdGhpY19idG4oIuKclyBEZWxldGUiLCAgIkRlbGV0ZSBzZWxlY3RlZCBzY2FuIikKICAgICAgICBzZWxm"
    "Ll9idG5fcmVwYXJzZSA9IF9nb3RoaWNfYnRuKCLihrsgUmUtcGFyc2UiLCJSZS1wYXJzZSByYXcgdGV4dCBvZiBzZWxlY3RlZCBz"
    "Y2FuIikKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9zaG93X2FkZCkKICAgICAgICBzZWxmLl9i"
    "dG5fZGlzcGxheS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2hvd19kaXNwbGF5KQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkuY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX3Nob3dfbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNl"
    "bGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fcmVwYXJzZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fcmVwYXJzZSkK"
    "ICAgICAgICBmb3IgYiBpbiAoc2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRuX2Rpc3BsYXksIHNlbGYuX2J0bl9tb2RpZnksCiAgICAg"
    "ICAgICAgICAgICAgIHNlbGYuX2J0bl9kZWxldGUsIHNlbGYuX2J0bl9yZXBhcnNlKToKICAgICAgICAgICAgYmFyLmFkZFdpZGdl"
    "dChiKQogICAgICAgIGJhci5hZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChiYXIpCgogICAgICAgICMgU3RhY2s6"
    "IGxpc3QgdmlldyB8IGFkZCBmb3JtIHwgZGlzcGxheSB8IG1vZGlmeQogICAgICAgIHNlbGYuX3N0YWNrID0gUVN0YWNrZWRXaWRn"
    "ZXQoKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3N0YWNrLCAxKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDA6IHNjYW4g"
    "bGlzdCAoZ3JpbW9pcmUgY2FyZHMpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAwID0gUVdpZGdldCgpCiAgICAgICAgbDAgPSBRVkJveExheW91dChwMCkKICAg"
    "ICAgICBsMC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbCA9IFFTY3JvbGxB"
    "cmVhKCkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbC5zZXRXaWRnZXRSZXNpemFibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9jYXJk"
    "X3Njcm9sbC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiBub25lOyIpCiAgICAgICAgc2VsZi5f"
    "Y2FyZF9jb250YWluZXIgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jYXJkX2xheW91dCAgICA9IFFWQm94TGF5b3V0KHNlbGYu"
    "X2NhcmRfY29udGFpbmVyKQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQog"
    "ICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBzZWxmLl9jYXJkX2xheW91dC5hZGRTdHJldGNo"
    "KCkKICAgICAgICBzZWxmLl9jYXJkX3Njcm9sbC5zZXRXaWRnZXQoc2VsZi5fY2FyZF9jb250YWluZXIpCiAgICAgICAgbDAuYWRk"
    "V2lkZ2V0KHNlbGYuX2NhcmRfc2Nyb2xsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMCkKCiAgICAgICAgIyDilIDi"
    "lIAgUEFHRSAxOiBhZGQgZm9ybSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICBwMSA9IFFXaWRnZXQoKQogICAgICAgIGwxID0gUVZCb3hMYXlvdXQocDEpCiAgICAgICAgbDEuc2V0Q29udGVudHNNYXJn"
    "aW5zKDQsIDQsIDQsIDQpCiAgICAgICAgbDEuc2V0U3BhY2luZyg0KQogICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwo"
    "IuKdpyBTQ0FOIE5BTUUgKGF1dG8tZGV0ZWN0ZWQpIikpCiAgICAgICAgc2VsZi5fYWRkX25hbWUgID0gUUxpbmVFZGl0KCkKICAg"
    "ICAgICBzZWxmLl9hZGRfbmFtZS5zZXRQbGFjZWhvbGRlclRleHQoIkF1dG8tZGV0ZWN0ZWQgZnJvbSBzY2FuIHRleHQiKQogICAg"
    "ICAgIGwxLmFkZFdpZGdldChzZWxmLl9hZGRfbmFtZSkKICAgICAgICBsMS5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgREVT"
    "Q1JJUFRJT04iKSkKICAgICAgICBzZWxmLl9hZGRfZGVzYyAgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2FkZF9kZXNjLnNl"
    "dE1heGltdW1IZWlnaHQoNjApCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9kZXNjKQogICAgICAgIGwxLmFkZFdpZGdl"
    "dChfc2VjdGlvbl9sYmwoIuKdpyBSQVcgU0NBTiBURVhUIChwYXN0ZSBoZXJlKSIpKQogICAgICAgIHNlbGYuX2FkZF9yYXcgICA9"
    "IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fYWRkX3Jhdy5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgICJQYXN0ZSB0"
    "aGUgcmF3IFNlY29uZCBMaWZlIHNjYW4gb3V0cHV0IGhlcmUuXG4iCiAgICAgICAgICAgICJUaW1lc3RhbXBzIGxpa2UgWzExOjQ3"
    "XSB3aWxsIGJlIHVzZWQgdG8gc3BsaXQgaXRlbXMgY29ycmVjdGx5LiIKICAgICAgICApCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNl"
    "bGYuX2FkZF9yYXcsIDEpCiAgICAgICAgIyBQcmV2aWV3IG9mIHBhcnNlZCBpdGVtcwogICAgICAgIGwxLmFkZFdpZGdldChfc2Vj"
    "dGlvbl9sYmwoIuKdpyBQQVJTRUQgSVRFTVMgUFJFVklFVyIpKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3ID0gUVRhYmxlV2lk"
    "Z2V0KDAsIDIpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIkl0ZW0iLCAiQ3Jl"
    "YXRvciJdKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3Lmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgK"
    "ICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3Lmhv"
    "cml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9k"
    "ZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldE1heGltdW1IZWlnaHQoMTIwKQogICAgICAgIHNlbGYuX2Fk"
    "ZF9wcmV2aWV3LnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIGwxLmFkZFdpZGdldChzZWxmLl9h"
    "ZGRfcHJldmlldykKICAgICAgICBzZWxmLl9hZGRfcmF3LnRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fcHJldmlld19wYXJzZSkK"
    "CiAgICAgICAgYnRuczEgPSBRSEJveExheW91dCgpCiAgICAgICAgczEgPSBfZ290aGljX2J0bigi4pymIFNhdmUiKTsgYzEgPSBf"
    "Z290aGljX2J0bigi4pyXIENhbmNlbCIpCiAgICAgICAgczEuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAgICBj"
    "MS5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMCkpCiAgICAgICAgYnRuczEuYWRk"
    "V2lkZ2V0KHMxKTsgYnRuczEuYWRkV2lkZ2V0KGMxKTsgYnRuczEuYWRkU3RyZXRjaCgpCiAgICAgICAgbDEuYWRkTGF5b3V0KGJ0"
    "bnMxKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMSkKCiAgICAgICAgIyDilIDilIAgUEFHRSAyOiBkaXNwbGF5IOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAyID0gUVdpZGdldCgp"
    "CiAgICAgICAgbDIgPSBRVkJveExheW91dChwMikKICAgICAgICBsMi5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAg"
    "ICAgICBzZWxmLl9kaXNwX25hbWUgID0gUUxhYmVsKCkKICAgICAgICBzZWxmLl9kaXNwX25hbWUuc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgZiJjb2xvcjoge0NfR09MRF9CUklHSFR9OyBmb250LXNpemU6IDEzcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAg"
    "ICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3Bf"
    "ZGVzYyAgPSBRTGFiZWwoKQogICAgICAgIHNlbGYuX2Rpc3BfZGVzYy5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIHNlbGYuX2Rp"
    "c3BfZGVzYy5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsg"
    "Zm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUgPSBRVGFi"
    "bGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJJdGVtIiwg"
    "IkNyZWF0b3IiXSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9k"
    "ZSgKICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUu"
    "aG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVN"
    "b2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkK"
    "ICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldENvbnRleHRNZW51UG9saWN5KAogICAgICAgICAgICBRdC5Db250ZXh0TWVudVBv"
    "bGljeS5DdXN0b21Db250ZXh0TWVudSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLmN1c3RvbUNvbnRleHRNZW51UmVxdWVzdGVk"
    "LmNvbm5lY3QoCiAgICAgICAgICAgIHNlbGYuX2l0ZW1fY29udGV4dF9tZW51KQoKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5f"
    "ZGlzcF9uYW1lKQogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9kaXNwX2Rlc2MpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYu"
    "X2Rpc3BfdGFibGUsIDEpCgogICAgICAgIGNvcHlfaGludCA9IFFMYWJlbCgiUmlnaHQtY2xpY2sgYW55IGl0ZW0gdG8gY29weSBp"
    "dCB0byBjbGlwYm9hcmQuIikKICAgICAgICBjb3B5X2hpbnQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0Nf"
    "VEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAg"
    "ICAgIGwyLmFkZFdpZGdldChjb3B5X2hpbnQpCgogICAgICAgIGJrMiA9IF9nb3RoaWNfYnRuKCLil4AgQmFjayIpCiAgICAgICAg"
    "YmsyLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKSkKICAgICAgICBsMi5hZGRX"
    "aWRnZXQoYmsyKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMikKCiAgICAgICAgIyDilIDilIAgUEFHRSAzOiBtb2Rp"
    "Znkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDMgPSBR"
    "V2lkZ2V0KCkKICAgICAgICBsMyA9IFFWQm94TGF5b3V0KHAzKQogICAgICAgIGwzLnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0"
    "LCA0KQogICAgICAgIGwzLnNldFNwYWNpbmcoNCkKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgTkFNRSIp"
    "KQogICAgICAgIHNlbGYuX21vZF9uYW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fbW9kX25hbWUp"
    "CiAgICAgICAgbDMuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIERFU0NSSVBUSU9OIikpCiAgICAgICAgc2VsZi5fbW9kX2Rl"
    "c2MgPSBRTGluZUVkaXQoKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9tb2RfZGVzYykKICAgICAgICBsMy5hZGRXaWRnZXQo"
    "X3NlY3Rpb25fbGJsKCLinacgSVRFTVMgKGRvdWJsZS1jbGljayB0byBlZGl0KSIpKQogICAgICAgIHNlbGYuX21vZF90YWJsZSA9"
    "IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiSXRl"
    "bSIsICJDcmVhdG9yIl0pCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXpl"
    "TW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX21vZF90YWJs"
    "ZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJWaWV3LlJlc2l6"
    "ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkp"
    "CiAgICAgICAgbDMuYWRkV2lkZ2V0KHNlbGYuX21vZF90YWJsZSwgMSkKCiAgICAgICAgYnRuczMgPSBRSEJveExheW91dCgpCiAg"
    "ICAgICAgczMgPSBfZ290aGljX2J0bigi4pymIFNhdmUiKTsgYzMgPSBfZ290aGljX2J0bigi4pyXIENhbmNlbCIpCiAgICAgICAg"
    "czMuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX21vZGlmeV9zYXZlKQogICAgICAgIGMzLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6"
    "IHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKSkKICAgICAgICBidG5zMy5hZGRXaWRnZXQoczMpOyBidG5zMy5hZGRXaWRn"
    "ZXQoYzMpOyBidG5zMy5hZGRTdHJldGNoKCkKICAgICAgICBsMy5hZGRMYXlvdXQoYnRuczMpCiAgICAgICAgc2VsZi5fc3RhY2su"
    "YWRkV2lkZ2V0KHAzKQoKICAgICMg4pSA4pSAIFBBUlNFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIEBzdGF0aWNtZXRob2QKICAg"
    "IGRlZiBwYXJzZV9zY2FuX3RleHQocmF3OiBzdHIpIC0+IHR1cGxlW3N0ciwgbGlzdFtkaWN0XV06CiAgICAgICAgIiIiCiAgICAg"
    "ICAgUGFyc2UgcmF3IFNMIHNjYW4gb3V0cHV0IGludG8gKGF2YXRhcl9uYW1lLCBpdGVtcykuCgogICAgICAgIEtFWSBGSVg6IEJl"
    "Zm9yZSBzcGxpdHRpbmcsIGluc2VydCBuZXdsaW5lcyBiZWZvcmUgZXZlcnkgW0hIOk1NXQogICAgICAgIHRpbWVzdGFtcCBzbyBz"
    "aW5nbGUtbGluZSBwYXN0ZXMgd29yayBjb3JyZWN0bHkuCgogICAgICAgIEV4cGVjdGVkIGZvcm1hdDoKICAgICAgICAgICAgWzEx"
    "OjQ3XSBBdmF0YXJOYW1lJ3MgcHVibGljIGF0dGFjaG1lbnRzOgogICAgICAgICAgICBbMTE6NDddIC46IEl0ZW0gTmFtZSBbQXR0"
    "YWNobWVudF0gQ1JFQVRPUjogQ3JlYXRvck5hbWUgWzExOjQ3XSAuLi4KICAgICAgICAiIiIKICAgICAgICBpZiBub3QgcmF3LnN0"
    "cmlwKCk6CiAgICAgICAgICAgIHJldHVybiAiVU5LTk9XTiIsIFtdCgogICAgICAgICMg4pSA4pSAIFN0ZXAgMTogbm9ybWFsaXpl"
    "IOKAlCBpbnNlcnQgbmV3bGluZXMgYmVmb3JlIHRpbWVzdGFtcHMg4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbm9ybWFsaXpl"
    "ZCA9IF9yZS5zdWIocidccyooXFtcZHsxLDJ9OlxkezJ9XF0pJywgcidcblwxJywgcmF3KQogICAgICAgIGxpbmVzID0gW2wuc3Ry"
    "aXAoKSBmb3IgbCBpbiBub3JtYWxpemVkLnNwbGl0bGluZXMoKSBpZiBsLnN0cmlwKCldCgogICAgICAgICMg4pSA4pSAIFN0ZXAg"
    "MjogZXh0cmFjdCBhdmF0YXIgbmFtZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBhdmF0YXJfbmFtZSA9ICJVTktOT1dO"
    "IgogICAgICAgIGZvciBsaW5lIGluIGxpbmVzOgogICAgICAgICAgICAjICJBdmF0YXJOYW1lJ3MgcHVibGljIGF0dGFjaG1lbnRz"
    "IiBvciBzaW1pbGFyCiAgICAgICAgICAgIG0gPSBfcmUuc2VhcmNoKAogICAgICAgICAgICAgICAgciIoXHdbXHdcc10rPyknc1xz"
    "K3B1YmxpY1xzK2F0dGFjaG1lbnRzIiwKICAgICAgICAgICAgICAgIGxpbmUsIF9yZS5JCiAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgaWYgbToKICAgICAgICAgICAgICAgIGF2YXRhcl9uYW1lID0gbS5ncm91cCgxKS5zdHJpcCgpCiAgICAgICAgICAgICAgICBi"
    "cmVhawoKICAgICAgICAjIOKUgOKUgCBTdGVwIDM6IGV4dHJhY3QgaXRlbXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICAgICAgaXRlbXMgPSBbXQogICAgICAgIGZvciBsaW5lIGluIGxpbmVzOgogICAgICAgICAgICAjIFN0cmlw"
    "IGxlYWRpbmcgdGltZXN0YW1wCiAgICAgICAgICAgIGNvbnRlbnQgPSBfcmUuc3ViKHInXlxbXGR7MSwyfTpcZHsyfVxdXHMqJywg"
    "JycsIGxpbmUpLnN0cmlwKCkKICAgICAgICAgICAgaWYgbm90IGNvbnRlbnQ6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAg"
    "ICAgICAgICAjIFNraXAgaGVhZGVyIGxpbmVzCiAgICAgICAgICAgIGlmICIncyBwdWJsaWMgYXR0YWNobWVudHMiIGluIGNvbnRl"
    "bnQubG93ZXIoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIGNvbnRlbnQubG93ZXIoKS5zdGFydHN3"
    "aXRoKCJvYmplY3QiKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICMgU2tpcCBkaXZpZGVyIGxpbmVzIOKA"
    "lCBsaW5lcyB0aGF0IGFyZSBtb3N0bHkgb25lIHJlcGVhdGVkIGNoYXJhY3RlcgogICAgICAgICAgICAjIGUuZy4g4paC4paC4paC"
    "4paC4paC4paC4paC4paC4paC4paC4paC4paCIG9yIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkCBvciDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAgICAgc3RyaXBwZWQgPSBjb250ZW50LnN0cmlwKCIuOiAi"
    "KQogICAgICAgICAgICBpZiBzdHJpcHBlZCBhbmQgbGVuKHNldChzdHJpcHBlZCkpIDw9IDI6CiAgICAgICAgICAgICAgICBjb250"
    "aW51ZSAgIyBvbmUgb3IgdHdvIHVuaXF1ZSBjaGFycyA9IGRpdmlkZXIgbGluZQoKICAgICAgICAgICAgIyBUcnkgdG8gZXh0cmFj"
    "dCBDUkVBVE9SOiBmaWVsZAogICAgICAgICAgICBjcmVhdG9yID0gIlVOS05PV04iCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IGNv"
    "bnRlbnQKCiAgICAgICAgICAgIGNyZWF0b3JfbWF0Y2ggPSBfcmUuc2VhcmNoKAogICAgICAgICAgICAgICAgcidDUkVBVE9SOlxz"
    "KihbXHdcc10rPykoPzpccypcW3wkKScsIGNvbnRlbnQsIF9yZS5JCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgY3JlYXRv"
    "cl9tYXRjaDoKICAgICAgICAgICAgICAgIGNyZWF0b3IgICA9IGNyZWF0b3JfbWF0Y2guZ3JvdXAoMSkuc3RyaXAoKQogICAgICAg"
    "ICAgICAgICAgaXRlbV9uYW1lID0gY29udGVudFs6Y3JlYXRvcl9tYXRjaC5zdGFydCgpXS5zdHJpcCgpCgogICAgICAgICAgICAj"
    "IFN0cmlwIGF0dGFjaG1lbnQgcG9pbnQgc3VmZml4ZXMgbGlrZSBbTGVmdF9Gb290XQogICAgICAgICAgICBpdGVtX25hbWUgPSBf"
    "cmUuc3ViKHInXHMqXFtbXHdcc19dK1xdJywgJycsIGl0ZW1fbmFtZSkuc3RyaXAoKQogICAgICAgICAgICBpdGVtX25hbWUgPSBp"
    "dGVtX25hbWUuc3RyaXAoIi46ICIpCgogICAgICAgICAgICBpZiBpdGVtX25hbWUgYW5kIGxlbihpdGVtX25hbWUpID4gMToKICAg"
    "ICAgICAgICAgICAgIGl0ZW1zLmFwcGVuZCh7Iml0ZW0iOiBpdGVtX25hbWUsICJjcmVhdG9yIjogY3JlYXRvcn0pCgogICAgICAg"
    "IHJldHVybiBhdmF0YXJfbmFtZSwgaXRlbXMKCiAgICAjIOKUgOKUgCBDQVJEIFJFTkRFUklORyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfYnVpbGRfY2FyZHMoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICAjIENsZWFyIGV4aXN0aW5nIGNhcmRzIChrZWVwIHN0cmV0Y2gpCiAgICAgICAgd2hpbGUgc2Vs"
    "Zi5fY2FyZF9sYXlvdXQuY291bnQoKSA+IDE6CiAgICAgICAgICAgIGl0ZW0gPSBzZWxmLl9jYXJkX2xheW91dC50YWtlQXQoMCkK"
    "ICAgICAgICAgICAgaWYgaXRlbS53aWRnZXQoKToKICAgICAgICAgICAgICAgIGl0ZW0ud2lkZ2V0KCkuZGVsZXRlTGF0ZXIoKQoK"
    "ICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGNhcmQgPSBzZWxmLl9tYWtlX2NhcmQocmVjKQog"
    "ICAgICAgICAgICBzZWxmLl9jYXJkX2xheW91dC5pbnNlcnRXaWRnZXQoCiAgICAgICAgICAgICAgICBzZWxmLl9jYXJkX2xheW91"
    "dC5jb3VudCgpIC0gMSwgY2FyZAogICAgICAgICAgICApCgogICAgZGVmIF9tYWtlX2NhcmQoc2VsZiwgcmVjOiBkaWN0KSAtPiBR"
    "V2lkZ2V0OgogICAgICAgIGNhcmQgPSBRRnJhbWUoKQogICAgICAgIGlzX3NlbGVjdGVkID0gcmVjLmdldCgicmVjb3JkX2lkIikg"
    "PT0gc2VsZi5fc2VsZWN0ZWRfaWQKICAgICAgICBjYXJkLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDog"
    "eycjMWEwYTEwJyBpZiBpc19zZWxlY3RlZCBlbHNlIENfQkczfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtD"
    "X0NSSU1TT04gaWYgaXNfc2VsZWN0ZWQgZWxzZSBDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJib3JkZXItcmFkaXVzOiAycHg7"
    "IHBhZGRpbmc6IDJweDsiCiAgICAgICAgKQogICAgICAgIGxheW91dCA9IFFIQm94TGF5b3V0KGNhcmQpCiAgICAgICAgbGF5b3V0"
    "LnNldENvbnRlbnRzTWFyZ2lucyg4LCA2LCA4LCA2KQoKICAgICAgICBuYW1lX2xibCA9IFFMYWJlbChyZWMuZ2V0KCJuYW1lIiwg"
    "IlVOS05PV04iKSkKICAgICAgICBuYW1lX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0JS"
    "SUdIVCBpZiBpc19zZWxlY3RlZCBlbHNlIENfR09MRH07ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDExcHg7IGZvbnQtd2Vp"
    "Z2h0OiBib2xkOyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIGNvdW50ID0gbGVu"
    "KHJlYy5nZXQoIml0ZW1zIiwgW10pKQogICAgICAgIGNvdW50X2xibCA9IFFMYWJlbChmIntjb3VudH0gaXRlbXMiKQogICAgICAg"
    "IGNvdW50X2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19DUklNU09OfTsgZm9udC1zaXplOiAxMHB4"
    "OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIGRhdGVfbGJsID0gUUxhYmVsKHJl"
    "Yy5nZXQoImNyZWF0ZWRfYXQiLCAiIilbOjEwXSkKICAgICAgICBkYXRlX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBm"
    "ImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAg"
    "ICAgICApCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQobmFtZV9sYmwpCiAgICAgICAgbGF5b3V0LmFkZFN0cmV0Y2goKQogICAg"
    "ICAgIGxheW91dC5hZGRXaWRnZXQoY291bnRfbGJsKQogICAgICAgIGxheW91dC5hZGRTcGFjaW5nKDEyKQogICAgICAgIGxheW91"
    "dC5hZGRXaWRnZXQoZGF0ZV9sYmwpCgogICAgICAgICMgQ2xpY2sgdG8gc2VsZWN0CiAgICAgICAgcmVjX2lkID0gcmVjLmdldCgi"
    "cmVjb3JkX2lkIiwgIiIpCiAgICAgICAgY2FyZC5tb3VzZVByZXNzRXZlbnQgPSBsYW1iZGEgZSwgcmlkPXJlY19pZDogc2VsZi5f"
    "c2VsZWN0X2NhcmQocmlkKQogICAgICAgIHJldHVybiBjYXJkCgogICAgZGVmIF9zZWxlY3RfY2FyZChzZWxmLCByZWNvcmRfaWQ6"
    "IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zZWxlY3RlZF9pZCA9IHJlY29yZF9pZAogICAgICAgIHNlbGYuX2J1aWxkX2Nh"
    "cmRzKCkgICMgUmVidWlsZCB0byBzaG93IHNlbGVjdGlvbiBoaWdobGlnaHQKCiAgICBkZWYgX3NlbGVjdGVkX3JlY29yZChzZWxm"
    "KSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICByZXR1cm4gbmV4dCgKICAgICAgICAgICAgKHIgZm9yIHIgaW4gc2VsZi5fcmVj"
    "b3JkcwogICAgICAgICAgICAgaWYgci5nZXQoInJlY29yZF9pZCIpID09IHNlbGYuX3NlbGVjdGVkX2lkKSwKICAgICAgICAgICAg"
    "Tm9uZQogICAgICAgICkKCiAgICAjIOKUgOKUgCBBQ1RJT05TIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIHJlZnJlc2goc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgICMgRW5zdXJlIHJl"
    "Y29yZF9pZCBmaWVsZCBleGlzdHMKICAgICAgICBjaGFuZ2VkID0gRmFsc2UKICAgICAgICBmb3IgciBpbiBzZWxmLl9yZWNvcmRz"
    "OgogICAgICAgICAgICBpZiBub3Qgci5nZXQoInJlY29yZF9pZCIpOgogICAgICAgICAgICAgICAgclsicmVjb3JkX2lkIl0gPSBy"
    "LmdldCgiaWQiKSBvciBzdHIodXVpZC51dWlkNCgpKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICBpZiBj"
    "aGFuZ2VkOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYuX2J1"
    "aWxkX2NhcmRzKCkKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMCkKCiAgICBkZWYgX3ByZXZpZXdfcGFyc2Uo"
    "c2VsZikgLT4gTm9uZToKICAgICAgICByYXcgPSBzZWxmLl9hZGRfcmF3LnRvUGxhaW5UZXh0KCkKICAgICAgICBuYW1lLCBpdGVt"
    "cyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICBzZWxmLl9hZGRfbmFtZS5zZXRQbGFjZWhvbGRlclRleHQobmFt"
    "ZSkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiBpdGVtc1s6MjBdOiAg"
    "IyBwcmV2aWV3IGZpcnN0IDIwCiAgICAgICAgICAgIHIgPSBzZWxmLl9hZGRfcHJldmlldy5yb3dDb3VudCgpCiAgICAgICAgICAg"
    "IHNlbGYuX2FkZF9wcmV2aWV3Lmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRJdGVtKHIsIDAs"
    "IFFUYWJsZVdpZGdldEl0ZW0oaXRbIml0ZW0iXSkpCiAgICAgICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldEl0ZW0ociwgMSwg"
    "UVRhYmxlV2lkZ2V0SXRlbShpdFsiY3JlYXRvciJdKSkKCiAgICBkZWYgX3Nob3dfYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "c2VsZi5fYWRkX25hbWUuY2xlYXIoKQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiQXV0by1kZXRl"
    "Y3RlZCBmcm9tIHNjYW4gdGV4dCIpCiAgICAgICAgc2VsZi5fYWRkX2Rlc2MuY2xlYXIoKQogICAgICAgIHNlbGYuX2FkZF9yYXcu"
    "Y2xlYXIoKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldFJvd0NvdW50KDApCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3Vy"
    "cmVudEluZGV4KDEpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICByYXcgID0gc2VsZi5fYWRkX3Jhdy50"
    "b1BsYWluVGV4dCgpCiAgICAgICAgbmFtZSwgaXRlbXMgPSBzZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcpCiAgICAgICAgb3ZlcnJp"
    "ZGVfbmFtZSA9IHNlbGYuX2FkZF9uYW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgbm93ICA9IGRhdGV0aW1lLm5vdyh0aW1lem9u"
    "ZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICBzdHIodXVpZC51"
    "dWlkNCgpKSwKICAgICAgICAgICAgInJlY29yZF9pZCI6ICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICJuYW1lIjog"
    "ICAgICAgIG92ZXJyaWRlX25hbWUgb3IgbmFtZSwKICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogc2VsZi5fYWRkX2Rlc2MudG9Q"
    "bGFpblRleHQoKVs6MjQ0XSwKICAgICAgICAgICAgIml0ZW1zIjogICAgICAgaXRlbXMsCiAgICAgICAgICAgICJyYXdfdGV4dCI6"
    "ICAgIHJhdywKICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgbm93LAogICAgICAgICAgICAidXBkYXRlZF9hdCI6ICBub3csCiAg"
    "ICAgICAgfQogICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHJlY29yZCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRo"
    "LCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkID0gcmVjb3JkWyJyZWNvcmRfaWQiXQogICAgICAgIHNl"
    "bGYucmVmcmVzaCgpCgogICAgZGVmIF9zaG93X2Rpc3BsYXkoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxl"
    "Y3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYs"
    "ICJTTCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBzY2FuIHRvIGRpc3BsYXku"
    "IikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fZGlzcF9uYW1lLnNldFRleHQoZiLinacge3JlYy5nZXQoJ25hbWUn"
    "LCcnKX0iKQogICAgICAgIHNlbGYuX2Rpc3BfZGVzYy5zZXRUZXh0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpCiAgICAgICAg"
    "c2VsZi5fZGlzcF90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiByZWMuZ2V0KCJpdGVtcyIsW10pOgogICAg"
    "ICAgICAgICByID0gc2VsZi5fZGlzcF90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuaW5zZXJ0"
    "Um93KHIpCiAgICAgICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lk"
    "Z2V0SXRlbShpdC5nZXQoIml0ZW0iLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SXRlbShyLCAxLAogICAg"
    "ICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoImNyZWF0b3IiLCJVTktOT1dOIikpKQogICAgICAgIHNlbGYuX3N0"
    "YWNrLnNldEN1cnJlbnRJbmRleCgyKQoKICAgIGRlZiBfaXRlbV9jb250ZXh0X21lbnUoc2VsZiwgcG9zKSAtPiBOb25lOgogICAg"
    "ICAgIGlkeCA9IHNlbGYuX2Rpc3BfdGFibGUuaW5kZXhBdChwb3MpCiAgICAgICAgaWYgbm90IGlkeC5pc1ZhbGlkKCk6CiAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgIGl0ZW1fdGV4dCAgPSAoc2VsZi5fZGlzcF90YWJsZS5pdGVtKGlkeC5yb3coKSwgMCkgb3IK"
    "ICAgICAgICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICBjcmVhdG9yICAgID0gKHNl"
    "bGYuX2Rpc3BfdGFibGUuaXRlbShpZHgucm93KCksIDEpIG9yCiAgICAgICAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVt"
    "KCIiKSkudGV4dCgpCiAgICAgICAgZnJvbSBQeVNpZGU2LlF0V2lkZ2V0cyBpbXBvcnQgUU1lbnUKICAgICAgICBtZW51ID0gUU1l"
    "bnUoc2VsZikKICAgICAgICBtZW51LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29s"
    "b3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICAp"
    "CiAgICAgICAgYV9pdGVtICAgID0gbWVudS5hZGRBY3Rpb24oIkNvcHkgSXRlbSBOYW1lIikKICAgICAgICBhX2NyZWF0b3IgPSBt"
    "ZW51LmFkZEFjdGlvbigiQ29weSBDcmVhdG9yIikKICAgICAgICBhX2JvdGggICAgPSBtZW51LmFkZEFjdGlvbigiQ29weSBCb3Ro"
    "IikKICAgICAgICBhY3Rpb24gPSBtZW51LmV4ZWMoc2VsZi5fZGlzcF90YWJsZS52aWV3cG9ydCgpLm1hcFRvR2xvYmFsKHBvcykp"
    "CiAgICAgICAgY2IgPSBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCkKICAgICAgICBpZiBhY3Rpb24gPT0gYV9pdGVtOiAgICBjYi5z"
    "ZXRUZXh0KGl0ZW1fdGV4dCkKICAgICAgICBlbGlmIGFjdGlvbiA9PSBhX2NyZWF0b3I6IGNiLnNldFRleHQoY3JlYXRvcikKICAg"
    "ICAgICBlbGlmIGFjdGlvbiA9PSBhX2JvdGg6ICBjYi5zZXRUZXh0KGYie2l0ZW1fdGV4dH0g4oCUIHtjcmVhdG9yfSIpCgogICAg"
    "ZGVmIF9zaG93X21vZGlmeShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAg"
    "ICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gbW9kaWZ5LiIpCiAgICAgICAgICAgIHJldHVy"
    "bgogICAgICAgIHNlbGYuX21vZF9uYW1lLnNldFRleHQocmVjLmdldCgibmFtZSIsIiIpKQogICAgICAgIHNlbGYuX21vZF9kZXNj"
    "LnNldFRleHQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0Um93Q291bnQoMCkK"
    "ICAgICAgICBmb3IgaXQgaW4gcmVjLmdldCgiaXRlbXMiLFtdKToKICAgICAgICAgICAgciA9IHNlbGYuX21vZF90YWJsZS5yb3dD"
    "b3VudCgpCiAgICAgICAgICAgIHNlbGYuX21vZF90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fbW9kX3RhYmxl"
    "LnNldEl0ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oaXQuZ2V0KCJpdGVtIiwiIikpKQogICAgICAg"
    "ICAgICBzZWxmLl9tb2RfdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQo"
    "ImNyZWF0b3IiLCJVTktOT1dOIikpKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgzKQoKICAgIGRlZiBfZG9f"
    "bW9kaWZ5X3NhdmUoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlm"
    "IG5vdCByZWM6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlY1sibmFtZSJdICAgICAgICA9IHNlbGYuX21vZF9uYW1lLnRl"
    "eHQoKS5zdHJpcCgpIG9yICJVTktOT1dOIgogICAgICAgIHJlY1siZGVzY3JpcHRpb24iXSA9IHNlbGYuX21vZF9kZXNjLnRleHQo"
    "KVs6MjQ0XQogICAgICAgIGl0ZW1zID0gW10KICAgICAgICBmb3IgaSBpbiByYW5nZShzZWxmLl9tb2RfdGFibGUucm93Q291bnQo"
    "KSk6CiAgICAgICAgICAgIGl0ICA9IChzZWxmLl9tb2RfdGFibGUuaXRlbShpLDApIG9yIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50"
    "ZXh0KCkKICAgICAgICAgICAgY3IgID0gKHNlbGYuX21vZF90YWJsZS5pdGVtKGksMSkgb3IgUVRhYmxlV2lkZ2V0SXRlbSgiIikp"
    "LnRleHQoKQogICAgICAgICAgICBpdGVtcy5hcHBlbmQoeyJpdGVtIjogaXQuc3RyaXAoKSBvciAiVU5LTk9XTiIsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgImNyZWF0b3IiOiBjci5zdHJpcCgpIG9yICJVTktOT1dOIn0pCiAgICAgICAgcmVjWyJpdGVtcyJd"
    "ICAgICAgPSBpdGVtcwogICAgICAgIHJlY1sidXBkYXRlZF9hdCJdID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9y"
    "bWF0KCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgp"
    "CgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQog"
    "ICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJTTCBTY2FucyIsCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBzY2FuIHRvIGRlbGV0ZS4iKQogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICBuYW1lID0gcmVjLmdldCgibmFtZSIsInRoaXMgc2NhbiIpCiAgICAgICAgcmVwbHkgPSBRTWVzc2FnZUJv"
    "eC5xdWVzdGlvbigKICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBTY2FuIiwKICAgICAgICAgICAgZiJEZWxldGUgJ3tuYW1lfSc/"
    "IFRoaXMgY2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVz"
    "c2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICkKICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFy"
    "ZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIHNlbGYuX3JlY29yZHMgPSBbciBmb3IgciBpbiBzZWxmLl9yZWNvcmRzCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgaWYgci5nZXQoInJlY29yZF9pZCIpICE9IHNlbGYuX3NlbGVjdGVkX2lkXQogICAgICAgICAg"
    "ICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLl9zZWxlY3RlZF9pZCA9IE5v"
    "bmUKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX3JlcGFyc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBy"
    "ZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94Lmlu"
    "Zm9ybWF0aW9uKHNlbGYsICJTTCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBz"
    "Y2FuIHRvIHJlLXBhcnNlLiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJhdyA9IHJlYy5nZXQoInJhd190ZXh0IiwiIikK"
    "ICAgICAgICBpZiBub3QgcmF3OgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiUmUtcGFyc2UiLAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiTm8gcmF3IHRleHQgc3RvcmVkIGZvciB0aGlzIHNjYW4uIikKICAg"
    "ICAgICAgICAgcmV0dXJuCiAgICAgICAgbmFtZSwgaXRlbXMgPSBzZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcpCiAgICAgICAgcmVj"
    "WyJpdGVtcyJdICAgICAgPSBpdGVtcwogICAgICAgIHJlY1sibmFtZSJdICAgICAgID0gcmVjWyJuYW1lIl0gb3IgbmFtZQogICAg"
    "ICAgIHJlY1sidXBkYXRlZF9hdCJdID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICB3cml0"
    "ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCiAgICAgICAgUU1lc3NhZ2VC"
    "b3guaW5mb3JtYXRpb24oc2VsZiwgIlJlLXBhcnNlZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJGb3VuZCB7"
    "bGVuKGl0ZW1zKX0gaXRlbXMuIikKCgojIOKUgOKUgCBTTCBDT01NQU5EUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CmNsYXNzIFNMQ29tbWFuZHNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFNlY29uZCBMaWZlIGNvbW1hbmQgcmVmZXJlbmNlIHRh"
    "YmxlLgogICAgR290aGljIHRhYmxlIHN0eWxpbmcuIENvcHkgY29tbWFuZCB0byBjbGlwYm9hcmQgYnV0dG9uIHBlciByb3cuCiAg"
    "ICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50"
    "KQogICAgICAgIHNlbGYuX3BhdGggICAgPSBjZmdfcGF0aCgic2wiKSAvICJzbF9jb21tYW5kcy5qc29ubCIKICAgICAgICBzZWxm"
    "Ll9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkK"
    "CiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAg"
    "cm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgYmFy"
    "ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hZGQgICAgPSBfZ290aGljX2J0bigi4pymIEFkZCIpCiAgICAgICAg"
    "c2VsZi5fYnRuX21vZGlmeSA9IF9nb3RoaWNfYnRuKCLinKcgTW9kaWZ5IikKICAgICAgICBzZWxmLl9idG5fZGVsZXRlID0gX2dv"
    "dGhpY19idG4oIuKclyBEZWxldGUiKQogICAgICAgIHNlbGYuX2J0bl9jb3B5ICAgPSBfZ290aGljX2J0bigi4qeJIENvcHkgQ29t"
    "bWFuZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiQ29weSBzZWxlY3RlZCBjb21tYW5kIHRvIGNs"
    "aXBib2FyZCIpCiAgICAgICAgc2VsZi5fYnRuX3JlZnJlc2g9IF9nb3RoaWNfYnRuKCLihrsgUmVmcmVzaCIpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX2FkZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkuY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX2RvX21vZGlmeSkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19k"
    "ZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX2NvcHkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2NvcHlfY29tbWFuZCkKICAgICAgICBz"
    "ZWxmLl9idG5fcmVmcmVzaC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5yZWZyZXNoKQogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5f"
    "YWRkLCBzZWxmLl9idG5fbW9kaWZ5LCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fY29weSwg"
    "c2VsZi5fYnRuX3JlZnJlc2gpOgogICAgICAgICAgICBiYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQog"
    "ICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAg"
    "ICBzZWxmLl90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiQ29tbWFuZCIsICJEZXNjcmlwdGlvbiJdKQogICAgICAg"
    "IHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMCwgUUhlYWRl"
    "clZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9u"
    "UmVzaXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3Rh"
    "YmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5T"
    "ZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5f"
    "dGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdGFi"
    "bGUsIDEpCgogICAgICAgIGhpbnQgPSBRTGFiZWwoCiAgICAgICAgICAgICJTZWxlY3QgYSByb3cgYW5kIGNsaWNrIOKniSBDb3B5"
    "IENvbW1hbmQgdG8gY29weSBqdXN0IHRoZSBjb21tYW5kIHRleHQuIgogICAgICAgICkKICAgICAgICBoaW50LnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19G"
    "T05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChoaW50KQoKICAgIGRlZiByZWZyZXNoKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBzZWxmLl90YWJs"
    "ZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9IHNlbGYuX3Rh"
    "YmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX3RhYmxl"
    "LnNldEl0ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiY29tbWFuZCIsIiIpKSkKICAg"
    "ICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0"
    "KCJkZXNjcmlwdGlvbiIsIiIpKSkKCiAgICBkZWYgX2NvcHlfY29tbWFuZChzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNl"
    "bGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIHJvdyA8IDA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGl0ZW0g"
    "PSBzZWxmLl90YWJsZS5pdGVtKHJvdywgMCkKICAgICAgICBpZiBpdGVtOgogICAgICAgICAgICBRQXBwbGljYXRpb24uY2xpcGJv"
    "YXJkKCkuc2V0VGV4dChpdGVtLnRleHQoKSkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIGRsZyA9IFFE"
    "aWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkFkZCBDb21tYW5kIikKICAgICAgICBkbGcuc2V0U3R5bGVT"
    "aGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGZvcm0gPSBRRm9ybUxheW91dChk"
    "bGcpCiAgICAgICAgY21kICA9IFFMaW5lRWRpdCgpOyBkZXNjID0gUUxpbmVFZGl0KCkKICAgICAgICBmb3JtLmFkZFJvdygiQ29t"
    "bWFuZDoiLCBjbWQpCiAgICAgICAgZm9ybS5hZGRSb3coIkRlc2NyaXB0aW9uOiIsIGRlc2MpCiAgICAgICAgYnRucyA9IFFIQm94"
    "TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAg"
    "ICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBi"
    "dG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCiAgICAgICAgaWYg"
    "ZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIG5vdyA9IGRhdGV0aW1lLm5vdyh0"
    "aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgIHJlYyA9IHsKICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAg"
    "IHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAgICAgImNvbW1hbmQiOiAgICAgY21kLnRleHQoKS5zdHJpcCgpWzoyNDRd"
    "LAogICAgICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogZGVzYy50ZXh0KCkuc3RyaXAoKVs6MjQ0XSwKICAgICAgICAgICAgICAg"
    "ICJjcmVhdGVkX2F0IjogIG5vdywgInVwZGF0ZWRfYXQiOiBub3csCiAgICAgICAgICAgIH0KICAgICAgICAgICAgaWYgcmVjWyJj"
    "b21tYW5kIl06CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChyZWMpCiAgICAgICAgICAgICAgICB3cml0ZV9q"
    "c29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2Rv"
    "X21vZGlmeShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIHJv"
    "dyA8IDAgb3Igcm93ID49IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjID0gc2VsZi5f"
    "cmVjb3Jkc1tyb3ddCiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiTW9kaWZ5"
    "IENvbW1hbmQiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9"
    "OyIpCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKICAgICAgICBjbWQgID0gUUxpbmVFZGl0KHJlYy5nZXQoImNvbW1h"
    "bmQiLCIiKSkKICAgICAgICBkZXNjID0gUUxpbmVFZGl0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpCiAgICAgICAgZm9ybS5h"
    "ZGRSb3coIkNvbW1hbmQ6IiwgY21kKQogICAgICAgIGZvcm0uYWRkUm93KCJEZXNjcmlwdGlvbjoiLCBkZXNjKQogICAgICAgIGJ0"
    "bnMgPSBRSEJveExheW91dCgpCiAgICAgICAgb2sgPSBfZ290aGljX2J0bigiU2F2ZSIpOyBjeCA9IF9nb3RoaWNfYnRuKCJDYW5j"
    "ZWwiKQogICAgICAgIG9rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KTsgY3guY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3Qp"
    "CiAgICAgICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5zLmFkZFdpZGdldChjeCkKICAgICAgICBmb3JtLmFkZFJvdyhidG5zKQog"
    "ICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICByZWNbImNvbW1h"
    "bmQiXSAgICAgPSBjbWQudGV4dCgpLnN0cmlwKClbOjI0NF0KICAgICAgICAgICAgcmVjWyJkZXNjcmlwdGlvbiJdID0gZGVzYy50"
    "ZXh0KCkuc3RyaXAoKVs6MjQ0XQogICAgICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSAgPSBkYXRldGltZS5ub3codGltZXpvbmUu"
    "dXRjKS5pc29mb3JtYXQoKQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAg"
    "ICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5f"
    "dGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgcm93IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICBjbWQgPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJjb21tYW5kIiwidGhpcyBjb21tYW5kIikK"
    "ICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVsZXRlIiwgZiJEZWxldGUg"
    "J3tjbWR9Jz8iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFy"
    "ZEJ1dHRvbi5ObwogICAgICAgICkKICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAg"
    "ICAgICAgICAgIHNlbGYuX3JlY29yZHMucG9wKHJvdykKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5f"
    "cmVjb3JkcykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCgojIOKUgOKUgCBKT0IgVFJBQ0tFUiBUQUIg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACmNsYXNzIEpvYlRyYWNrZXJUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIEpvYiBhcHBsaWNhdGlvbiB0"
    "cmFja2luZy4gRnVsbCByZWJ1aWxkIGZyb20gc3BlYy4KICAgIEZpZWxkczogQ29tcGFueSwgSm9iIFRpdGxlLCBEYXRlIEFwcGxp"
    "ZWQsIExpbmssIFN0YXR1cywgTm90ZXMuCiAgICBNdWx0aS1zZWxlY3QgaGlkZS91bmhpZGUvZGVsZXRlLiBDU1YgYW5kIFRTViBl"
    "eHBvcnQuCiAgICBIaWRkZW4gcm93cyA9IGNvbXBsZXRlZC9yZWplY3RlZCDigJQgc3RpbGwgc3RvcmVkLCBqdXN0IG5vdCBzaG93"
    "bi4KICAgICIiIgoKICAgIENPTFVNTlMgPSBbIkNvbXBhbnkiLCAiSm9iIFRpdGxlIiwgIkRhdGUgQXBwbGllZCIsCiAgICAgICAg"
    "ICAgICAgICJMaW5rIiwgIlN0YXR1cyIsICJOb3RlcyJdCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAg"
    "ICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRoICAgID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikg"
    "LyAiam9iX3RyYWNrZXIuanNvbmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5f"
    "c2hvd19oaWRkZW4gPSBGYWxzZQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRl"
    "ZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNl"
    "dENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBiYXIgPSBRSEJv"
    "eExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCJBZGQiKQogICAgICAgIHNlbGYuX2J0bl9t"
    "b2RpZnkgPSBfZ290aGljX2J0bigiTW9kaWZ5IikKICAgICAgICBzZWxmLl9idG5faGlkZSAgID0gX2dvdGhpY19idG4oIkFyY2hp"
    "dmUiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIk1hcmsgc2VsZWN0ZWQgYXMgY29tcGxldGVkL3Jl"
    "amVjdGVkIikKICAgICAgICBzZWxmLl9idG5fdW5oaWRlID0gX2dvdGhpY19idG4oIlJlc3RvcmUiLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIlJlc3RvcmUgYXJjaGl2ZWQgYXBwbGljYXRpb25zIikKICAgICAgICBzZWxmLl9idG5f"
    "ZGVsZXRlID0gX2dvdGhpY19idG4oIkRlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZSA9IF9nb3RoaWNfYnRuKCJTaG93"
    "IEFyY2hpdmVkIikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0ID0gX2dvdGhpY19idG4oIkV4cG9ydCIpCgogICAgICAgIGZvciBi"
    "IGluIChzZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fbW9kaWZ5LCBzZWxmLl9idG5faGlkZSwKICAgICAgICAgICAgICAgICAgc2Vs"
    "Zi5fYnRuX3VuaGlkZSwgc2VsZi5fYnRuX2RlbGV0ZSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZSwgc2VsZi5f"
    "YnRuX2V4cG9ydCk6CiAgICAgICAgICAgIGIuc2V0TWluaW11bVdpZHRoKDcwKQogICAgICAgICAgICBiLnNldE1pbmltdW1IZWln"
    "aHQoMjYpCiAgICAgICAgICAgIGJhci5hZGRXaWRnZXQoYikKCiAgICAgICAgc2VsZi5fYnRuX2FkZC5jbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5fZG9fYWRkKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX21vZGlmeSkKICAg"
    "ICAgICBzZWxmLl9idG5faGlkZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9faGlkZSkKICAgICAgICBzZWxmLl9idG5fdW5oaWRl"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb191bmhpZGUpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl90b2dnbGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9oaWRk"
    "ZW4pCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZXhwb3J0KQogICAgICAgIGJhci5h"
    "ZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChiYXIpCgogICAgICAgIHNlbGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0"
    "KDAsIGxlbihzZWxmLkNPTFVNTlMpKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoc2VsZi5D"
    "T0xVTU5TKQogICAgICAgIGhoID0gc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpCiAgICAgICAgIyBDb21wYW55IGFuZCBK"
    "b2IgVGl0bGUgc3RyZXRjaAogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUu"
    "U3RyZXRjaCkKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gp"
    "CiAgICAgICAgIyBEYXRlIEFwcGxpZWQg4oCUIGZpeGVkIHJlYWRhYmxlIHdpZHRoCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6"
    "ZU1vZGUoMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgy"
    "LCAxMDApCiAgICAgICAgIyBMaW5rIHN0cmV0Y2hlcwogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDMsIFFIZWFkZXJW"
    "aWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICAjIFN0YXR1cyDigJQgZml4ZWQgd2lkdGgKICAgICAgICBoaC5zZXRTZWN0"
    "aW9uUmVzaXplTW9kZSg0LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENvbHVt"
    "bldpZHRoKDQsIDgwKQogICAgICAgICMgTm90ZXMgc3RyZXRjaGVzCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoNSwg"
    "UUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQoKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigK"
    "ICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLl90"
    "YWJsZS5zZXRTZWxlY3Rpb25Nb2RlKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25Nb2RlLkV4dGVuZGVk"
    "U2VsZWN0aW9uKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5f"
    "dGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdGFi"
    "bGUsIDEpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChz"
    "ZWxmLl9wYXRoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNv"
    "cmRzOgogICAgICAgICAgICBoaWRkZW4gPSBib29sKHJlYy5nZXQoImhpZGRlbiIsIEZhbHNlKSkKICAgICAgICAgICAgaWYgaGlk"
    "ZGVuIGFuZCBub3Qgc2VsZi5fc2hvd19oaWRkZW46CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICByID0gc2Vs"
    "Zi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc3RhdHVz"
    "ID0gIkFyY2hpdmVkIiBpZiBoaWRkZW4gZWxzZSByZWMuZ2V0KCJzdGF0dXMiLCJBY3RpdmUiKQogICAgICAgICAgICB2YWxzID0g"
    "WwogICAgICAgICAgICAgICAgcmVjLmdldCgiY29tcGFueSIsIiIpLAogICAgICAgICAgICAgICAgcmVjLmdldCgiam9iX3RpdGxl"
    "IiwiIiksCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJkYXRlX2FwcGxpZWQiLCIiKSwKICAgICAgICAgICAgICAgIHJlYy5nZXQo"
    "ImxpbmsiLCIiKSwKICAgICAgICAgICAgICAgIHN0YXR1cywKICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAg"
    "ICAgICAgICAgIF0KICAgICAgICAgICAgZm9yIGMsIHYgaW4gZW51bWVyYXRlKHZhbHMpOgogICAgICAgICAgICAgICAgaXRlbSA9"
    "IFFUYWJsZVdpZGdldEl0ZW0oc3RyKHYpKQogICAgICAgICAgICAgICAgaWYgaGlkZGVuOgogICAgICAgICAgICAgICAgICAgIGl0"
    "ZW0uc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIs"
    "IGMsIGl0ZW0pCiAgICAgICAgICAgICMgU3RvcmUgcmVjb3JkIGluZGV4IGluIGZpcnN0IGNvbHVtbidzIHVzZXIgZGF0YQogICAg"
    "ICAgICAgICBzZWxmLl90YWJsZS5pdGVtKHIsIDApLnNldERhdGEoCiAgICAgICAgICAgICAgICBRdC5JdGVtRGF0YVJvbGUuVXNl"
    "clJvbGUsCiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmluZGV4KHJlYykKICAgICAgICAgICAgKQoKICAgIGRlZiBfc2Vs"
    "ZWN0ZWRfaW5kaWNlcyhzZWxmKSAtPiBsaXN0W2ludF06CiAgICAgICAgaW5kaWNlcyA9IHNldCgpCiAgICAgICAgZm9yIGl0ZW0g"
    "aW4gc2VsZi5fdGFibGUuc2VsZWN0ZWRJdGVtcygpOgogICAgICAgICAgICByb3dfaXRlbSA9IHNlbGYuX3RhYmxlLml0ZW0oaXRl"
    "bS5yb3coKSwgMCkKICAgICAgICAgICAgaWYgcm93X2l0ZW06CiAgICAgICAgICAgICAgICBpZHggPSByb3dfaXRlbS5kYXRhKFF0"
    "Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgICAgIGlmIGlkeCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAg"
    "ICAgICBpbmRpY2VzLmFkZChpZHgpCiAgICAgICAgcmV0dXJuIHNvcnRlZChpbmRpY2VzKQoKICAgIGRlZiBfZGlhbG9nKHNlbGYs"
    "IHJlYzogZGljdCA9IE5vbmUpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIGRsZyAgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAg"
    "ZGxnLnNldFdpbmRvd1RpdGxlKCJKb2IgQXBwbGljYXRpb24iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3Vu"
    "ZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAsIDMyMCkKICAgICAgICBmb3JtID0g"
    "UUZvcm1MYXlvdXQoZGxnKQoKICAgICAgICBjb21wYW55ID0gUUxpbmVFZGl0KHJlYy5nZXQoImNvbXBhbnkiLCIiKSBpZiByZWMg"
    "ZWxzZSAiIikKICAgICAgICB0aXRsZSAgID0gUUxpbmVFZGl0KHJlYy5nZXQoImpvYl90aXRsZSIsIiIpIGlmIHJlYyBlbHNlICIi"
    "KQogICAgICAgIGRlICAgICAgPSBRRGF0ZUVkaXQoKQogICAgICAgIGRlLnNldENhbGVuZGFyUG9wdXAoVHJ1ZSkKICAgICAgICBk"
    "ZS5zZXREaXNwbGF5Rm9ybWF0KCJ5eXl5LU1NLWRkIikKICAgICAgICBpZiByZWMgYW5kIHJlYy5nZXQoImRhdGVfYXBwbGllZCIp"
    "OgogICAgICAgICAgICBkZS5zZXREYXRlKFFEYXRlLmZyb21TdHJpbmcocmVjWyJkYXRlX2FwcGxpZWQiXSwieXl5eS1NTS1kZCIp"
    "KQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGRlLnNldERhdGUoUURhdGUuY3VycmVudERhdGUoKSkKICAgICAgICBsaW5rICAg"
    "ID0gUUxpbmVFZGl0KHJlYy5nZXQoImxpbmsiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBzdGF0dXMgID0gUUxpbmVFZGl0"
    "KHJlYy5nZXQoInN0YXR1cyIsIkFwcGxpZWQiKSBpZiByZWMgZWxzZSAiQXBwbGllZCIpCiAgICAgICAgbm90ZXMgICA9IFFMaW5l"
    "RWRpdChyZWMuZ2V0KCJub3RlcyIsIiIpIGlmIHJlYyBlbHNlICIiKQoKICAgICAgICBmb3IgbGFiZWwsIHdpZGdldCBpbiBbCiAg"
    "ICAgICAgICAgICgiQ29tcGFueToiLCBjb21wYW55KSwgKCJKb2IgVGl0bGU6IiwgdGl0bGUpLAogICAgICAgICAgICAoIkRhdGUg"
    "QXBwbGllZDoiLCBkZSksICgiTGluazoiLCBsaW5rKSwKICAgICAgICAgICAgKCJTdGF0dXM6Iiwgc3RhdHVzKSwgKCJOb3Rlczoi"
    "LCBub3RlcyksCiAgICAgICAgXToKICAgICAgICAgICAgZm9ybS5hZGRSb3cobGFiZWwsIHdpZGdldCkKCiAgICAgICAgYnRucyA9"
    "IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIp"
    "CiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAg"
    "ICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCgogICAg"
    "ICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICByZXR1cm4gewogICAg"
    "ICAgICAgICAgICAgImNvbXBhbnkiOiAgICAgIGNvbXBhbnkudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAiam9iX3Rp"
    "dGxlIjogICAgdGl0bGUudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAiZGF0ZV9hcHBsaWVkIjogZGUuZGF0ZSgpLnRv"
    "U3RyaW5nKCJ5eXl5LU1NLWRkIiksCiAgICAgICAgICAgICAgICAibGluayI6ICAgICAgICAgbGluay50ZXh0KCkuc3RyaXAoKSwK"
    "ICAgICAgICAgICAgICAgICJzdGF0dXMiOiAgICAgICBzdGF0dXMudGV4dCgpLnN0cmlwKCkgb3IgIkFwcGxpZWQiLAogICAgICAg"
    "ICAgICAgICAgIm5vdGVzIjogICAgICAgIG5vdGVzLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICB9CiAgICAgICAgcmV0dXJu"
    "IE5vbmUKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIHAgPSBzZWxmLl9kaWFsb2coKQogICAgICAgIGlm"
    "IG5vdCBwOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBub3cgPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3Jt"
    "YXQoKQogICAgICAgIHAudXBkYXRlKHsKICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAg"
    "ICAgICAgICAgICJoaWRkZW4iOiAgICAgICAgIEZhbHNlLAogICAgICAgICAgICAiY29tcGxldGVkX2RhdGUiOiBOb25lLAogICAg"
    "ICAgICAgICAiY3JlYXRlZF9hdCI6ICAgICBub3csCiAgICAgICAgICAgICJ1cGRhdGVkX2F0IjogICAgIG5vdywKICAgICAgICB9"
    "KQogICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHApCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVj"
    "b3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fbW9kaWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWR4"
    "cyA9IHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKQogICAgICAgIGlmIGxlbihpZHhzKSAhPSAxOgogICAgICAgICAgICBRTWVzc2Fn"
    "ZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiTW9kaWZ5IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVj"
    "dCBleGFjdGx5IG9uZSByb3cgdG8gbW9kaWZ5LiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlYyA9IHNlbGYuX3JlY29y"
    "ZHNbaWR4c1swXV0KICAgICAgICBwICAgPSBzZWxmLl9kaWFsb2cocmVjKQogICAgICAgIGlmIG5vdCBwOgogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICByZWMudXBkYXRlKHApCiAgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpv"
    "bmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAg"
    "c2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2hpZGUoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3IgaWR4IGluIHNlbGYuX3Nl"
    "bGVjdGVkX2luZGljZXMoKToKICAgICAgICAgICAgaWYgaWR4IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICAgICAg"
    "c2VsZi5fcmVjb3Jkc1tpZHhdWyJoaWRkZW4iXSAgICAgICAgID0gVHJ1ZQogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tp"
    "ZHhdWyJjb21wbGV0ZWRfZGF0ZSJdID0gKAogICAgICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XS5nZXQoImNvbXBs"
    "ZXRlZF9kYXRlIikgb3IKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5kYXRlKCkuaXNvZm9ybWF0KCkKICAgICAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsidXBkYXRlZF9hdCJdID0gKAogICAgICAgICAg"
    "ICAgICAgICAgIGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAgICApCiAgICAgICAg"
    "d3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9f"
    "dW5oaWRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIGlkeCBpbiBzZWxmLl9zZWxlY3RlZF9pbmRpY2VzKCk6CiAgICAgICAg"
    "ICAgIGlmIGlkeCA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsiaGlkZGVu"
    "Il0gICAgID0gRmFsc2UKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsidXBkYXRlZF9hdCJdID0gKAogICAgICAg"
    "ICAgICAgICAgICAgIGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAgICApCiAgICAg"
    "ICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBf"
    "ZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWR4cyA9IHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKQogICAgICAgIGlm"
    "IG5vdCBpZHhzOgogICAgICAgICAgICByZXR1cm4KICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAg"
    "ICAgICBzZWxmLCAiRGVsZXRlIiwKICAgICAgICAgICAgZiJEZWxldGUge2xlbihpZHhzKX0gc2VsZWN0ZWQgYXBwbGljYXRpb24o"
    "cyk/IENhbm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3Nh"
    "Z2VCb3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICApCiAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRC"
    "dXR0b24uWWVzOgogICAgICAgICAgICBiYWQgPSBzZXQoaWR4cykKICAgICAgICAgICAgc2VsZi5fcmVjb3JkcyA9IFtyIGZvciBp"
    "LCByIGluIGVudW1lcmF0ZShzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIGkgbm90IGluIGJh"
    "ZF0KICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5yZWZy"
    "ZXNoKCkKCiAgICBkZWYgX3RvZ2dsZV9oaWRkZW4oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zaG93X2hpZGRlbiA9IG5v"
    "dCBzZWxmLl9zaG93X2hpZGRlbgogICAgICAgIHNlbGYuX2J0bl90b2dnbGUuc2V0VGV4dCgKICAgICAgICAgICAgIuKYgCBIaWRl"
    "IEFyY2hpdmVkIiBpZiBzZWxmLl9zaG93X2hpZGRlbiBlbHNlICLimL0gU2hvdyBBcmNoaXZlZCIKICAgICAgICApCiAgICAgICAg"
    "c2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2V4cG9ydChzZWxmKSAtPiBOb25lOgogICAgICAgIHBhdGgsIGZpbHQgPSBRRmls"
    "ZURpYWxvZy5nZXRTYXZlRmlsZU5hbWUoCiAgICAgICAgICAgIHNlbGYsICJFeHBvcnQgSm9iIFRyYWNrZXIiLAogICAgICAgICAg"
    "ICBzdHIoY2ZnX3BhdGgoImV4cG9ydHMiKSAvICJqb2JfdHJhY2tlci5jc3YiKSwKICAgICAgICAgICAgIkNTViBGaWxlcyAoKi5j"
    "c3YpOztUYWIgRGVsaW1pdGVkICgqLnR4dCkiCiAgICAgICAgKQogICAgICAgIGlmIG5vdCBwYXRoOgogICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICBkZWxpbSA9ICJcdCIgaWYgcGF0aC5sb3dlcigpLmVuZHN3aXRoKCIudHh0IikgZWxzZSAiLCIKICAgICAgICBo"
    "ZWFkZXIgPSBbImNvbXBhbnkiLCJqb2JfdGl0bGUiLCJkYXRlX2FwcGxpZWQiLCJsaW5rIiwKICAgICAgICAgICAgICAgICAgInN0"
    "YXR1cyIsImhpZGRlbiIsImNvbXBsZXRlZF9kYXRlIiwibm90ZXMiXQogICAgICAgIHdpdGggb3BlbihwYXRoLCAidyIsIGVuY29k"
    "aW5nPSJ1dGYtOCIsIG5ld2xpbmU9IiIpIGFzIGY6CiAgICAgICAgICAgIGYud3JpdGUoZGVsaW0uam9pbihoZWFkZXIpICsgIlxu"
    "IikKICAgICAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICAgICAgdmFscyA9IFsKICAgICAgICAg"
    "ICAgICAgICAgICByZWMuZ2V0KCJjb21wYW55IiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgiam9iX3RpdGxlIiwi"
    "IiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgiZGF0ZV9hcHBsaWVkIiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVj"
    "LmdldCgibGluayIsIiIpLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoInN0YXR1cyIsIiIpLAogICAgICAgICAgICAgICAg"
    "ICAgIHN0cihib29sKHJlYy5nZXQoImhpZGRlbiIsRmFsc2UpKSksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgiY29tcGxl"
    "dGVkX2RhdGUiLCIiKSBvciAiIiwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJub3RlcyIsIiIpLAogICAgICAgICAgICAg"
    "ICAgXQogICAgICAgICAgICAgICAgZi53cml0ZShkZWxpbS5qb2luKAogICAgICAgICAgICAgICAgICAgIHN0cih2KS5yZXBsYWNl"
    "KCJcbiIsIiAiKS5yZXBsYWNlKGRlbGltLCIgIikKICAgICAgICAgICAgICAgICAgICBmb3IgdiBpbiB2YWxzCiAgICAgICAgICAg"
    "ICAgICApICsgIlxuIikKICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiRXhwb3J0ZWQiLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGYiU2F2ZWQgdG8ge3BhdGh9IikKCgojIOKUgOKUgCBTRUxGIFRBQiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgUmVjb3Jkc1RhYihRV2lkZ2V0KToKICAgICIiIkdvb2ds"
    "ZSBEcml2ZS9Eb2NzIHJlY29yZHMgYnJvd3NlciB0YWIuIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToK"
    "ICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBy"
    "b290LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBzZWxm"
    "LnN0YXR1c19sYWJlbCA9IFFMYWJlbCgiUmVjb3JkcyBhcmUgbm90IGxvYWRlZCB5ZXQuIikKICAgICAgICBzZWxmLnN0YXR1c19s"
    "YWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtZmFtaWx5OiB7REVDS19G"
    "T05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuc3RhdHVz"
    "X2xhYmVsKQoKICAgICAgICBzZWxmLnBhdGhfbGFiZWwgPSBRTGFiZWwoIlBhdGg6IE15IERyaXZlIikKICAgICAgICBzZWxmLnBh"
    "dGhfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRF9ESU19OyBmb250LWZhbWlseToge0RF"
    "Q0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLnBh"
    "dGhfbGFiZWwpCgogICAgICAgIHNlbGYucmVjb3Jkc19saXN0ID0gUUxpc3RXaWRnZXQoKQogICAgICAgIHNlbGYucmVjb3Jkc19s"
    "aXN0LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyBib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5yZWNvcmRzX2xp"
    "c3QsIDEpCgogICAgZGVmIHNldF9pdGVtcyhzZWxmLCBmaWxlczogbGlzdFtkaWN0XSwgcGF0aF90ZXh0OiBzdHIgPSAiTXkgRHJp"
    "dmUiKSAtPiBOb25lOgogICAgICAgIHNlbGYucGF0aF9sYWJlbC5zZXRUZXh0KGYiUGF0aDoge3BhdGhfdGV4dH0iKQogICAgICAg"
    "IHNlbGYucmVjb3Jkc19saXN0LmNsZWFyKCkKICAgICAgICBmb3IgZmlsZV9pbmZvIGluIGZpbGVzOgogICAgICAgICAgICB0aXRs"
    "ZSA9IChmaWxlX2luZm8uZ2V0KCJuYW1lIikgb3IgIlVudGl0bGVkIikuc3RyaXAoKSBvciAiVW50aXRsZWQiCiAgICAgICAgICAg"
    "IG1pbWUgPSAoZmlsZV9pbmZvLmdldCgibWltZVR5cGUiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAgICBpZiBtaW1lID09ICJh"
    "cHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVyIjoKICAgICAgICAgICAgICAgIHByZWZpeCA9ICLwn5OBIgogICAgICAg"
    "ICAgICBlbGlmIG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5kb2N1bWVudCI6CiAgICAgICAgICAgICAgICBw"
    "cmVmaXggPSAi8J+TnSIKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHByZWZpeCA9ICLwn5OEIgogICAgICAgICAg"
    "ICBtb2RpZmllZCA9IChmaWxlX2luZm8uZ2V0KCJtb2RpZmllZFRpbWUiKSBvciAiIikucmVwbGFjZSgiVCIsICIgIikucmVwbGFj"
    "ZSgiWiIsICIgVVRDIikKICAgICAgICAgICAgdGV4dCA9IGYie3ByZWZpeH0ge3RpdGxlfSIgKyAoZiIgICAgW3ttb2RpZmllZH1d"
    "IiBpZiBtb2RpZmllZCBlbHNlICIiKQogICAgICAgICAgICBpdGVtID0gUUxpc3RXaWRnZXRJdGVtKHRleHQpCiAgICAgICAgICAg"
    "IGl0ZW0uc2V0RGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUsIGZpbGVfaW5mbykKICAgICAgICAgICAgc2VsZi5yZWNvcmRz"
    "X2xpc3QuYWRkSXRlbShpdGVtKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoZiJMb2FkZWQge2xlbihmaWxlcyl9"
    "IEdvb2dsZSBEcml2ZSBpdGVtKHMpLiIpCgoKY2xhc3MgVGFza3NUYWIoUVdpZGdldCk6CiAgICAiIiJUYXNrIHJlZ2lzdHJ5ICsg"
    "R29vZ2xlLWZpcnN0IGVkaXRvciB3b3JrZmxvdyB0YWIuIiIiCgogICAgZGVmIF9faW5pdF9fKAogICAgICAgIHNlbGYsCiAgICAg"
    "ICAgdGFza3NfcHJvdmlkZXIsCiAgICAgICAgb25fYWRkX2VkaXRvcl9vcGVuLAogICAgICAgIG9uX2NvbXBsZXRlX3NlbGVjdGVk"
    "LAogICAgICAgIG9uX2NhbmNlbF9zZWxlY3RlZCwKICAgICAgICBvbl90b2dnbGVfY29tcGxldGVkLAogICAgICAgIG9uX3B1cmdl"
    "X2NvbXBsZXRlZCwKICAgICAgICBvbl9maWx0ZXJfY2hhbmdlZCwKICAgICAgICBvbl9lZGl0b3Jfc2F2ZSwKICAgICAgICBvbl9l"
    "ZGl0b3JfY2FuY2VsLAogICAgICAgIGRpYWdub3N0aWNzX2xvZ2dlcj1Ob25lLAogICAgICAgIHBhcmVudD1Ob25lLAogICAgKToK"
    "ICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl90YXNrc19wcm92aWRlciA9IHRhc2tzX3Byb3Zp"
    "ZGVyCiAgICAgICAgc2VsZi5fb25fYWRkX2VkaXRvcl9vcGVuID0gb25fYWRkX2VkaXRvcl9vcGVuCiAgICAgICAgc2VsZi5fb25f"
    "Y29tcGxldGVfc2VsZWN0ZWQgPSBvbl9jb21wbGV0ZV9zZWxlY3RlZAogICAgICAgIHNlbGYuX29uX2NhbmNlbF9zZWxlY3RlZCA9"
    "IG9uX2NhbmNlbF9zZWxlY3RlZAogICAgICAgIHNlbGYuX29uX3RvZ2dsZV9jb21wbGV0ZWQgPSBvbl90b2dnbGVfY29tcGxldGVk"
    "CiAgICAgICAgc2VsZi5fb25fcHVyZ2VfY29tcGxldGVkID0gb25fcHVyZ2VfY29tcGxldGVkCiAgICAgICAgc2VsZi5fb25fZmls"
    "dGVyX2NoYW5nZWQgPSBvbl9maWx0ZXJfY2hhbmdlZAogICAgICAgIHNlbGYuX29uX2VkaXRvcl9zYXZlID0gb25fZWRpdG9yX3Nh"
    "dmUKICAgICAgICBzZWxmLl9vbl9lZGl0b3JfY2FuY2VsID0gb25fZWRpdG9yX2NhbmNlbAogICAgICAgIHNlbGYuX2RpYWdfbG9n"
    "Z2VyID0gZGlhZ25vc3RpY3NfbG9nZ2VyCiAgICAgICAgc2VsZi5fc2hvd19jb21wbGV0ZWQgPSBGYWxzZQogICAgICAgIHNlbGYu"
    "X3JlZnJlc2hfdGhyZWFkID0gTm9uZQogICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKCiAgICBkZWYgX2J1aWxkX3VpKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNiwg"
    "NiwgNiwgNikKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKICAgICAgICBzZWxmLndvcmtzcGFjZV9zdGFjayA9IFFTdGFja2Vk"
    "V2lkZ2V0KCkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLndvcmtzcGFjZV9zdGFjaywgMSkKCiAgICAgICAgbm9ybWFsID0g"
    "UVdpZGdldCgpCiAgICAgICAgbm9ybWFsX2xheW91dCA9IFFWQm94TGF5b3V0KG5vcm1hbCkKICAgICAgICBub3JtYWxfbGF5b3V0"
    "LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG5vcm1hbF9sYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAg"
    "ICBzZWxmLnN0YXR1c19sYWJlbCA9IFFMYWJlbCgiVGFzayByZWdpc3RyeSBpcyBub3QgbG9hZGVkIHlldC4iKQogICAgICAgIHNl"
    "bGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1mYW1p"
    "bHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgbm9ybWFsX2xheW91dC5h"
    "ZGRXaWRnZXQoc2VsZi5zdGF0dXNfbGFiZWwpCgogICAgICAgIGZpbHRlcl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgZmls"
    "dGVyX3Jvdy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgREFURSBSQU5HRSIpKQogICAgICAgIHNlbGYudGFza19maWx0ZXJf"
    "Y29tYm8gPSBRQ29tYm9Cb3goKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiV0VFSyIsICJ3ZWVrIikK"
    "ICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIk1PTlRIIiwgIm1vbnRoIikKICAgICAgICBzZWxmLnRhc2tf"
    "ZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIk5FWFQgMyBNT05USFMiLCAibmV4dF8zX21vbnRocyIpCiAgICAgICAgc2VsZi50YXNrX2Zp"
    "bHRlcl9jb21iby5hZGRJdGVtKCJZRUFSIiwgInllYXIiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uc2V0Q3VycmVu"
    "dEluZGV4KDIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5jdXJyZW50SW5kZXhDaGFuZ2VkLmNvbm5lY3QoCiAgICAg"
    "ICAgICAgIGxhbWJkYSBfOiBzZWxmLl9vbl9maWx0ZXJfY2hhbmdlZChzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmN1cnJlbnREYXRh"
    "KCkgb3IgIm5leHRfM19tb250aHMiKQogICAgICAgICkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChzZWxmLnRhc2tfZmls"
    "dGVyX2NvbWJvKQogICAgICAgIGZpbHRlcl9yb3cuYWRkU3RyZXRjaCgxKQogICAgICAgIG5vcm1hbF9sYXlvdXQuYWRkTGF5b3V0"
    "KGZpbHRlcl9yb3cpCgogICAgICAgIHNlbGYudGFza190YWJsZSA9IFFUYWJsZVdpZGdldCgwLCA0KQogICAgICAgIHNlbGYudGFz"
    "a190YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiU3RhdHVzIiwgIkR1ZSIsICJUYXNrIiwgIlNvdXJjZSJdKQogICAg"
    "ICAgIHNlbGYudGFza190YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcihRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlv"
    "ci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYudGFza190YWJsZS5zZXRTZWxlY3Rpb25Nb2RlKFFBYnN0cmFjdEl0ZW1WaWV3LlNl"
    "bGVjdGlvbk1vZGUuRXh0ZW5kZWRTZWxlY3Rpb24pCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEVkaXRUcmlnZ2VycyhRQWJz"
    "dHJhY3RJdGVtVmlldy5FZGl0VHJpZ2dlci5Ob0VkaXRUcmlnZ2VycykKICAgICAgICBzZWxmLnRhc2tfdGFibGUudmVydGljYWxI"
    "ZWFkZXIoKS5zZXRWaXNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYudGFza190YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2Vj"
    "dGlvblJlc2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5SZXNpemVUb0NvbnRlbnRzKQogICAgICAgIHNlbGYudGFz"
    "a190YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5S"
    "ZXNpemVUb0NvbnRlbnRzKQogICAgICAgIHNlbGYudGFza190YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6"
    "ZU1vZGUoMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYudGFza190YWJsZS5ob3Jpem9udGFs"
    "SGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoMywgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5SZXNpemVUb0NvbnRlbnRzKQog"
    "ICAgICAgIHNlbGYudGFza190YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBzZWxmLnRh"
    "c2tfdGFibGUuaXRlbVNlbGVjdGlvbkNoYW5nZWQuY29ubmVjdChzZWxmLl91cGRhdGVfYWN0aW9uX2J1dHRvbl9zdGF0ZSkKICAg"
    "ICAgICBub3JtYWxfbGF5b3V0LmFkZFdpZGdldChzZWxmLnRhc2tfdGFibGUsIDEpCgogICAgICAgIGFjdGlvbnMgPSBRSEJveExh"
    "eW91dCgpCiAgICAgICAgc2VsZi5idG5fYWRkX3Rhc2tfd29ya3NwYWNlID0gX2dvdGhpY19idG4oIkFERCBUQVNLIikKICAgICAg"
    "ICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrID0gX2dvdGhpY19idG4oIkNPTVBMRVRFIFNFTEVDVEVEIikKICAgICAgICBzZWxmLmJ0"
    "bl9jYW5jZWxfdGFzayA9IF9nb3RoaWNfYnRuKCJDQU5DRUwgU0VMRUNURUQiKQogICAgICAgIHNlbGYuYnRuX3RvZ2dsZV9jb21w"
    "bGV0ZWQgPSBfZ290aGljX2J0bigiU0hPVyBDT01QTEVURUQiKQogICAgICAgIHNlbGYuYnRuX3B1cmdlX2NvbXBsZXRlZCA9IF9n"
    "b3RoaWNfYnRuKCJQVVJHRSBDT01QTEVURUQiKQogICAgICAgIHNlbGYuYnRuX2FkZF90YXNrX3dvcmtzcGFjZS5jbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fb25fYWRkX2VkaXRvcl9vcGVuKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2suY2xpY2tlZC5jb25u"
    "ZWN0KHNlbGYuX29uX2NvbXBsZXRlX3NlbGVjdGVkKQogICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrLmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl9vbl9jYW5jZWxfc2VsZWN0ZWQpCiAgICAgICAgc2VsZi5idG5fdG9nZ2xlX2NvbXBsZXRlZC5jbGlja2VkLmNvbm5l"
    "Y3Qoc2VsZi5fb25fdG9nZ2xlX2NvbXBsZXRlZCkKICAgICAgICBzZWxmLmJ0bl9wdXJnZV9jb21wbGV0ZWQuY2xpY2tlZC5jb25u"
    "ZWN0KHNlbGYuX29uX3B1cmdlX2NvbXBsZXRlZCkKICAgICAgICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrLnNldEVuYWJsZWQoRmFs"
    "c2UpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBmb3IgYnRuIGluICgKICAg"
    "ICAgICAgICAgc2VsZi5idG5fYWRkX3Rhc2tfd29ya3NwYWNlLAogICAgICAgICAgICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrLAog"
    "ICAgICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzaywKICAgICAgICAgICAgc2VsZi5idG5fdG9nZ2xlX2NvbXBsZXRlZCwKICAg"
    "ICAgICAgICAgc2VsZi5idG5fcHVyZ2VfY29tcGxldGVkLAogICAgICAgICk6CiAgICAgICAgICAgIGFjdGlvbnMuYWRkV2lkZ2V0"
    "KGJ0bikKICAgICAgICBub3JtYWxfbGF5b3V0LmFkZExheW91dChhY3Rpb25zKQogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNr"
    "LmFkZFdpZGdldChub3JtYWwpCgogICAgICAgIGVkaXRvciA9IFFXaWRnZXQoKQogICAgICAgIGVkaXRvcl9sYXlvdXQgPSBRVkJv"
    "eExheW91dChlZGl0b3IpCiAgICAgICAgZWRpdG9yX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAg"
    "ICBlZGl0b3JfbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwo"
    "IuKdpyBUQVNLIEVESVRPUiDigJQgR09PR0xFLUZJUlNUIikpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwg"
    "PSBRTGFiZWwoIkNvbmZpZ3VyZSB0YXNrIGRldGFpbHMsIHRoZW4gc2F2ZSB0byBHb29nbGUgQ2FsZW5kYXIuIikKICAgICAgICBz"
    "ZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JH"
    "M307IGNvbG9yOiB7Q19URVhUX0RJTX07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IHBhZGRpbmc6IDZweDsiCiAgICAg"
    "ICAgKQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVsKQogICAgICAg"
    "IHNlbGYudGFza19lZGl0b3JfbmFtZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9uYW1lLnNldFBsYWNl"
    "aG9sZGVyVGV4dCgiVGFzayBOYW1lIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUgPSBRTGluZUVkaXQoKQog"
    "ICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF0ZS5zZXRQbGFjZWhvbGRlclRleHQoIlN0YXJ0IERhdGUgKFlZWVktTU0t"
    "REQpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYudGFza19l"
    "ZGl0b3Jfc3RhcnRfdGltZS5zZXRQbGFjZWhvbGRlclRleHQoIlN0YXJ0IFRpbWUgKEhIOk1NKSIpCiAgICAgICAgc2VsZi50YXNr"
    "X2VkaXRvcl9lbmRfZGF0ZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfZGF0ZS5zZXRQbGFjZWhv"
    "bGRlclRleHQoIkVuZCBEYXRlIChZWVlZLU1NLUREKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfdGltZSA9IFFMaW5l"
    "RWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfdGltZS5zZXRQbGFjZWhvbGRlclRleHQoIkVuZCBUaW1lIChISDpN"
    "TSkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfbG9jYXRpb24gPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0"
    "b3JfbG9jYXRpb24uc2V0UGxhY2Vob2xkZXJUZXh0KCJMb2NhdGlvbiAob3B0aW9uYWwpIikKICAgICAgICBzZWxmLnRhc2tfZWRp"
    "dG9yX3JlY3VycmVuY2UgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfcmVjdXJyZW5jZS5zZXRQbGFjZWhv"
    "bGRlclRleHQoIlJlY3VycmVuY2UgUlJVTEUgKG9wdGlvbmFsKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9hbGxfZGF5ID0g"
    "UUNoZWNrQm94KCJBbGwtZGF5IikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25vdGVzID0gUVRleHRFZGl0KCkKICAgICAgICBz"
    "ZWxmLnRhc2tfZWRpdG9yX25vdGVzLnNldFBsYWNlaG9sZGVyVGV4dCgiTm90ZXMiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jf"
    "bm90ZXMuc2V0TWF4aW11bUhlaWdodCg5MCkKICAgICAgICBmb3Igd2lkZ2V0IGluICgKICAgICAgICAgICAgc2VsZi50YXNrX2Vk"
    "aXRvcl9uYW1lLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUsCiAgICAgICAgICAgIHNlbGYudGFza19l"
    "ZGl0b3Jfc3RhcnRfdGltZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9lbmRfZGF0ZSwKICAgICAgICAgICAgc2VsZi50"
    "YXNrX2VkaXRvcl9lbmRfdGltZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbiwKICAgICAgICAgICAgc2Vs"
    "Zi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLAogICAgICAgICk6CiAgICAgICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KHdp"
    "ZGdldCkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChzZWxmLnRhc2tfZWRpdG9yX2FsbF9kYXkpCiAgICAgICAgZWRp"
    "dG9yX2xheW91dC5hZGRXaWRnZXQoc2VsZi50YXNrX2VkaXRvcl9ub3RlcywgMSkKICAgICAgICBlZGl0b3JfYWN0aW9ucyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBidG5fc2F2ZSA9IF9nb3RoaWNfYnRuKCJTQVZFIikKICAgICAgICBidG5fY2FuY2VsID0gX2dv"
    "dGhpY19idG4oIkNBTkNFTCIpCiAgICAgICAgYnRuX3NhdmUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2VkaXRvcl9zYXZlKQog"
    "ICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2VkaXRvcl9jYW5jZWwpCiAgICAgICAgZWRpdG9yX2Fj"
    "dGlvbnMuYWRkV2lkZ2V0KGJ0bl9zYXZlKQogICAgICAgIGVkaXRvcl9hY3Rpb25zLmFkZFdpZGdldChidG5fY2FuY2VsKQogICAg"
    "ICAgIGVkaXRvcl9hY3Rpb25zLmFkZFN0cmV0Y2goMSkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZExheW91dChlZGl0b3JfYWN0"
    "aW9ucykKICAgICAgICBzZWxmLndvcmtzcGFjZV9zdGFjay5hZGRXaWRnZXQoZWRpdG9yKQoKICAgICAgICBzZWxmLm5vcm1hbF93"
    "b3Jrc3BhY2UgPSBub3JtYWwKICAgICAgICBzZWxmLmVkaXRvcl93b3Jrc3BhY2UgPSBlZGl0b3IKICAgICAgICBzZWxmLndvcmtz"
    "cGFjZV9zdGFjay5zZXRDdXJyZW50V2lkZ2V0KHNlbGYubm9ybWFsX3dvcmtzcGFjZSkKCiAgICBkZWYgX3VwZGF0ZV9hY3Rpb25f"
    "YnV0dG9uX3N0YXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZW5hYmxlZCA9IGJvb2woc2VsZi5zZWxlY3RlZF90YXNrX2lkcygp"
    "KQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2suc2V0RW5hYmxlZChlbmFibGVkKQogICAgICAgIHNlbGYuYnRuX2NhbmNl"
    "bF90YXNrLnNldEVuYWJsZWQoZW5hYmxlZCkKCiAgICBkZWYgc2VsZWN0ZWRfdGFza19pZHMoc2VsZikgLT4gbGlzdFtzdHJdOgog"
    "ICAgICAgIGlkczogbGlzdFtzdHJdID0gW10KICAgICAgICBmb3IgciBpbiByYW5nZShzZWxmLnRhc2tfdGFibGUucm93Q291bnQo"
    "KSk6CiAgICAgICAgICAgIHN0YXR1c19pdGVtID0gc2VsZi50YXNrX3RhYmxlLml0ZW0ociwgMCkKICAgICAgICAgICAgaWYgc3Rh"
    "dHVzX2l0ZW0gaXMgTm9uZToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIG5vdCBzdGF0dXNfaXRlbS5p"
    "c1NlbGVjdGVkKCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICB0YXNrX2lkID0gc3RhdHVzX2l0ZW0uZGF0"
    "YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpCiAgICAgICAgICAgIGlmIHRhc2tfaWQgYW5kIHRhc2tfaWQgbm90IGluIGlkczoK"
    "ICAgICAgICAgICAgICAgIGlkcy5hcHBlbmQodGFza19pZCkKICAgICAgICByZXR1cm4gaWRzCgogICAgZGVmIGxvYWRfdGFza3Mo"
    "c2VsZiwgdGFza3M6IGxpc3RbZGljdF0pIC0+IE5vbmU6CiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFJvd0NvdW50KDApCiAg"
    "ICAgICAgZm9yIHRhc2sgaW4gdGFza3M6CiAgICAgICAgICAgIHJvdyA9IHNlbGYudGFza190YWJsZS5yb3dDb3VudCgpCiAgICAg"
    "ICAgICAgIHNlbGYudGFza190YWJsZS5pbnNlcnRSb3cocm93KQogICAgICAgICAgICBzdGF0dXMgPSAodGFzay5nZXQoInN0YXR1"
    "cyIpIG9yICJwZW5kaW5nIikubG93ZXIoKQogICAgICAgICAgICBzdGF0dXNfaWNvbiA9ICLimJEiIGlmIHN0YXR1cyBpbiB7ImNv"
    "bXBsZXRlZCIsICJjYW5jZWxsZWQifSBlbHNlICLigKIiCiAgICAgICAgICAgIGR1ZSA9ICh0YXNrLmdldCgiZHVlX2F0Iikgb3Ig"
    "IiIpLnJlcGxhY2UoIlQiLCAiICIpCiAgICAgICAgICAgIHRleHQgPSAodGFzay5nZXQoInRleHQiKSBvciAiUmVtaW5kZXIiKS5z"
    "dHJpcCgpIG9yICJSZW1pbmRlciIKICAgICAgICAgICAgc291cmNlID0gKHRhc2suZ2V0KCJzb3VyY2UiKSBvciAibG9jYWwiKS5s"
    "b3dlcigpCiAgICAgICAgICAgIHN0YXR1c19pdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShmIntzdGF0dXNfaWNvbn0ge3N0YXR1c30i"
    "KQogICAgICAgICAgICBzdGF0dXNfaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgdGFzay5nZXQoImlkIikp"
    "CiAgICAgICAgICAgIHNlbGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMCwgc3RhdHVzX2l0ZW0pCiAgICAgICAgICAgIHNlbGYu"
    "dGFza190YWJsZS5zZXRJdGVtKHJvdywgMSwgUVRhYmxlV2lkZ2V0SXRlbShkdWUpKQogICAgICAgICAgICBzZWxmLnRhc2tfdGFi"
    "bGUuc2V0SXRlbShyb3csIDIsIFFUYWJsZVdpZGdldEl0ZW0odGV4dCkpCiAgICAgICAgICAgIHNlbGYudGFza190YWJsZS5zZXRJ"
    "dGVtKHJvdywgMywgUVRhYmxlV2lkZ2V0SXRlbShzb3VyY2UpKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoZiJM"
    "b2FkZWQge2xlbih0YXNrcyl9IHRhc2socykuIikKICAgICAgICBzZWxmLl91cGRhdGVfYWN0aW9uX2J1dHRvbl9zdGF0ZSgpCgog"
    "ICAgZGVmIF9kaWFnKHNlbGYsIG1lc3NhZ2U6IHN0ciwgbGV2ZWw6IHN0ciA9ICJJTkZPIikgLT4gTm9uZToKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIGlmIHNlbGYuX2RpYWdfbG9nZ2VyOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ19sb2dnZXIobWVzc2Fn"
    "ZSwgbGV2ZWwpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgIGRlZiBzdG9wX3JlZnJlc2hf"
    "d29ya2VyKHNlbGYsIHJlYXNvbjogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgdGhyZWFkID0gZ2V0YXR0cihzZWxmLCAiX3Jl"
    "ZnJlc2hfdGhyZWFkIiwgTm9uZSkKICAgICAgICBpZiB0aHJlYWQgaXMgbm90IE5vbmUgYW5kIGhhc2F0dHIodGhyZWFkLCAiaXNS"
    "dW5uaW5nIikgYW5kIHRocmVhZC5pc1J1bm5pbmcoKToKICAgICAgICAgICAgc2VsZi5fZGlhZygKICAgICAgICAgICAgICAgIGYi"
    "W1RBU0tTXVtUSFJFQURdW1dBUk5dIHN0b3AgcmVxdWVzdGVkIGZvciByZWZyZXNoIHdvcmtlciByZWFzb249e3JlYXNvbiBvciAn"
    "dW5zcGVjaWZpZWQnfSIsCiAgICAgICAgICAgICAgICAiV0FSTiIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICAgICAgdGhyZWFkLnJlcXVlc3RJbnRlcnJ1cHRpb24oKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgICAgICAgICAgcGFzcwogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICB0aHJlYWQucXVpdCgpCiAgICAgICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCiAgICAgICAgICAgIHRocmVhZC53YWl0KDIwMDApCiAgICAg"
    "ICAgc2VsZi5fcmVmcmVzaF90aHJlYWQgPSBOb25lCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBu"
    "b3QgY2FsbGFibGUoc2VsZi5fdGFza3NfcHJvdmlkZXIpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgIHNlbGYubG9hZF90YXNrcyhzZWxmLl90YXNrc19wcm92aWRlcigpKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6"
    "CiAgICAgICAgICAgIHNlbGYuX2RpYWcoZiJbVEFTS1NdW1RBQl1bRVJST1JdIHJlZnJlc2ggZmFpbGVkOiB7ZXh9IiwgIkVSUk9S"
    "IikKICAgICAgICAgICAgc2VsZi5zdG9wX3JlZnJlc2hfd29ya2VyKHJlYXNvbj0idGFza3NfdGFiX3JlZnJlc2hfZXhjZXB0aW9u"
    "IikKCiAgICBkZWYgY2xvc2VFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBzZWxmLnN0b3BfcmVmcmVzaF93b3Jr"
    "ZXIocmVhc29uPSJ0YXNrc190YWJfY2xvc2UiKQogICAgICAgIHN1cGVyKCkuY2xvc2VFdmVudChldmVudCkKCiAgICBkZWYgc2V0"
    "X3Nob3dfY29tcGxldGVkKHNlbGYsIGVuYWJsZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2hvd19jb21wbGV0ZWQg"
    "PSBib29sKGVuYWJsZWQpCiAgICAgICAgc2VsZi5idG5fdG9nZ2xlX2NvbXBsZXRlZC5zZXRUZXh0KCJISURFIENPTVBMRVRFRCIg"
    "aWYgc2VsZi5fc2hvd19jb21wbGV0ZWQgZWxzZSAiU0hPVyBDT01QTEVURUQiKQoKICAgIGRlZiBzZXRfc3RhdHVzKHNlbGYsIHRl"
    "eHQ6IHN0ciwgb2s6IGJvb2wgPSBGYWxzZSkgLT4gTm9uZToKICAgICAgICBjb2xvciA9IENfR1JFRU4gaWYgb2sgZWxzZSBDX1RF"
    "WFRfRElNCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJi"
    "YWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge2NvbG9yfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgcGFkZGluZzog"
    "NnB4OyIKICAgICAgICApCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwuc2V0VGV4dCh0ZXh0KQoKICAgIGRl"
    "ZiBvcGVuX2VkaXRvcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQo"
    "c2VsZi5lZGl0b3Jfd29ya3NwYWNlKQoKICAgIGRlZiBjbG9zZV9lZGl0b3Ioc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLndv"
    "cmtzcGFjZV9zdGFjay5zZXRDdXJyZW50V2lkZ2V0KHNlbGYubm9ybWFsX3dvcmtzcGFjZSkKCgpjbGFzcyBTZWxmVGFiKFFXaWRn"
    "ZXQpOgogICAgIiIiCiAgICBQZXJzb25hJ3MgaW50ZXJuYWwgZGlhbG9ndWUgc3BhY2UuCiAgICBSZWNlaXZlczogaWRsZSBuYXJy"
    "YXRpdmUgb3V0cHV0LCB1bnNvbGljaXRlZCB0cmFuc21pc3Npb25zLAogICAgICAgICAgICAgIFBvSSBsaXN0IGZyb20gZGFpbHkg"
    "cmVmbGVjdGlvbiwgdW5hbnN3ZXJlZCBxdWVzdGlvbiBmbGFncywKICAgICAgICAgICAgICBqb3VybmFsIGxvYWQgbm90aWZpY2F0"
    "aW9ucy4KICAgIFJlYWQtb25seSBkaXNwbGF5LiBTZXBhcmF0ZSBmcm9tIHBlcnNvbmEgY2hhdCB0YWIgYWx3YXlzLgogICAgIiIi"
    "CgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAg"
    "ICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQog"
    "ICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBoZHIgPSBRSEJveExheW91dCgpCiAgICAgICAgaGRyLmFkZFdpZGdl"
    "dChfc2VjdGlvbl9sYmwoZiLinacgSU5ORVIgU0FOQ1RVTSDigJQge0RFQ0tfTkFNRS51cHBlcigpfSdTIFBSSVZBVEUgVEhPVUdI"
    "VFMiKSkKICAgICAgICBzZWxmLl9idG5fY2xlYXIgPSBfZ290aGljX2J0bigi4pyXIENsZWFyIikKICAgICAgICBzZWxmLl9idG5f"
    "Y2xlYXIuc2V0Rml4ZWRXaWR0aCg4MCkKICAgICAgICBzZWxmLl9idG5fY2xlYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYuY2xlYXIp"
    "CiAgICAgICAgaGRyLmFkZFN0cmV0Y2goKQogICAgICAgIGhkci5hZGRXaWRnZXQoc2VsZi5fYnRuX2NsZWFyKQogICAgICAgIHJv"
    "b3QuYWRkTGF5b3V0KGhkcikKCiAgICAgICAgc2VsZi5fZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fZGlzcGxh"
    "eS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNr"
    "Z3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0Nf"
    "UFVSUExFX0RJTX07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEx"
    "cHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2Rpc3BsYXksIDEpCgogICAg"
    "ZGVmIGFwcGVuZChzZWxmLCBsYWJlbDogc3RyLCB0ZXh0OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRp"
    "bWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikKICAgICAgICBjb2xvcnMgPSB7CiAgICAgICAgICAgICJOQVJSQVRJVkUiOiAg"
    "Q19HT0xELAogICAgICAgICAgICAiUkVGTEVDVElPTiI6IENfUFVSUExFLAogICAgICAgICAgICAiSk9VUk5BTCI6ICAgIENfU0lM"
    "VkVSLAogICAgICAgICAgICAiUE9JIjogICAgICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgICJTWVNURU0iOiAgICAgQ19URVhU"
    "X0RJTSwKICAgICAgICB9CiAgICAgICAgY29sb3IgPSBjb2xvcnMuZ2V0KGxhYmVsLnVwcGVyKCksIENfR09MRCkKICAgICAgICBz"
    "ZWxmLl9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNp"
    "emU6MTBweDsiPicKICAgICAgICAgICAgZidbe3RpbWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9"
    "ImNvbG9yOntjb2xvcn07IGZvbnQtd2VpZ2h0OmJvbGQ7Ij4nCiAgICAgICAgICAgIGYn4p2nIHtsYWJlbH08L3NwYW4+PGJyPicK"
    "ICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfR09MRH07Ij57dGV4dH08L3NwYW4+JwogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl9kaXNwbGF5LmFwcGVuZCgiIikKICAgICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFs"
    "dWUoCiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAg"
    "ZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZGlzcGxheS5jbGVhcigpCgoKIyDilIDilIAgRElBR05PU1RJ"
    "Q1MgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEaWFnbm9zdGljc1RhYihRV2lkZ2V0KToKICAgICIiIgog"
    "ICAgQmFja2VuZCBkaWFnbm9zdGljcyBkaXNwbGF5LgogICAgUmVjZWl2ZXM6IGhhcmR3YXJlIGRldGVjdGlvbiByZXN1bHRzLCBk"
    "ZXBlbmRlbmN5IGNoZWNrIHJlc3VsdHMsCiAgICAgICAgICAgICAgQVBJIGVycm9ycywgc3luYyBmYWlsdXJlcywgdGltZXIgZXZl"
    "bnRzLCBqb3VybmFsIGxvYWQgbm90aWNlcywKICAgICAgICAgICAgICBtb2RlbCBsb2FkIHN0YXR1cywgR29vZ2xlIGF1dGggZXZl"
    "bnRzLgogICAgQWx3YXlzIHNlcGFyYXRlIGZyb20gcGVyc29uYSBjaGF0IHRhYi4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhz"
    "ZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgcm9vdCA9IFFWQm94TGF5"
    "b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNp"
    "bmcoNCkKCiAgICAgICAgaGRyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGhkci5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacg"
    "RElBR05PU1RJQ1Mg4oCUIFNZU1RFTSAmIEJBQ0tFTkQgTE9HIikpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyID0gX2dvdGhpY19i"
    "dG4oIuKclyBDbGVhciIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyLnNldEZpeGVkV2lkdGgoODApCiAgICAgICAgc2VsZi5fYnRu"
    "X2NsZWFyLmNsaWNrZWQuY29ubmVjdChzZWxmLmNsZWFyKQogICAgICAgIGhkci5hZGRTdHJldGNoKCkKICAgICAgICBoZHIuYWRk"
    "V2lkZ2V0KHNlbGYuX2J0bl9jbGVhcikKICAgICAgICByb290LmFkZExheW91dChoZHIpCgogICAgICAgIHNlbGYuX2Rpc3BsYXkg"
    "PSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9kaXNwbGF5"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9yOiB7Q19TSUxWRVJ9OyAi"
    "CiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiAn"
    "Q291cmllciBOZXcnLCBtb25vc3BhY2U7ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDEwcHg7IHBhZGRpbmc6IDhweDsiCiAg"
    "ICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2Rpc3BsYXksIDEpCgogICAgZGVmIGxvZyhzZWxmLCBtZXNzYWdl"
    "OiBzdHIsIGxldmVsOiBzdHIgPSAiSU5GTyIpIC0+IE5vbmU6CiAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3Ry"
    "ZnRpbWUoIiVIOiVNOiVTIikKICAgICAgICBsZXZlbF9jb2xvcnMgPSB7CiAgICAgICAgICAgICJJTkZPIjogIENfU0lMVkVSLAog"
    "ICAgICAgICAgICAiT0siOiAgICBDX0dSRUVOLAogICAgICAgICAgICAiV0FSTiI6ICBDX0dPTEQsCiAgICAgICAgICAgICJFUlJP"
    "UiI6IENfQkxPT0QsCiAgICAgICAgICAgICJERUJVRyI6IENfVEVYVF9ESU0sCiAgICAgICAgfQogICAgICAgIGNvbG9yID0gbGV2"
    "ZWxfY29sb3JzLmdldChsZXZlbC51cHBlcigpLCBDX1NJTFZFUikKICAgICAgICBzZWxmLl9kaXNwbGF5LmFwcGVuZCgKICAgICAg"
    "ICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyI+W3t0aW1lc3RhbXB9XTwvc3Bhbj4gJwogICAgICAgICAg"
    "ICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Y29sb3J9OyI+e21lc3NhZ2V9PC9zcGFuPicKICAgICAgICApCiAgICAgICAgc2VsZi5f"
    "ZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Ny"
    "b2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgIGRlZiBsb2dfbWFueShzZWxmLCBtZXNzYWdlczogbGlzdFtzdHJdLCBs"
    "ZXZlbDogc3RyID0gIklORk8iKSAtPiBOb25lOgogICAgICAgIGZvciBtc2cgaW4gbWVzc2FnZXM6CiAgICAgICAgICAgIGx2bCA9"
    "IGxldmVsCiAgICAgICAgICAgIGlmICLinJMiIGluIG1zZzogICAgbHZsID0gIk9LIgogICAgICAgICAgICBlbGlmICLinJciIGlu"
    "IG1zZzogIGx2bCA9ICJXQVJOIgogICAgICAgICAgICBlbGlmICJFUlJPUiIgaW4gbXNnLnVwcGVyKCk6IGx2bCA9ICJFUlJPUiIK"
    "ICAgICAgICAgICAgc2VsZi5sb2cobXNnLCBsdmwpCgogICAgZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "ZGlzcGxheS5jbGVhcigpCgoKIyDilIDilIAgTEVTU09OUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmNsYXNzIExlc3NvbnNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIExTTCBGb3JiaWRkZW4gUnVsZXNldCBhbmQgY29kZSBs"
    "ZXNzb25zIGJyb3dzZXIuCiAgICBBZGQsIHZpZXcsIHNlYXJjaCwgZGVsZXRlIGxlc3NvbnMuCiAgICAiIiIKCiAgICBkZWYgX19p"
    "bml0X18oc2VsZiwgZGI6ICJMZXNzb25zTGVhcm5lZERCIiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18o"
    "cGFyZW50KQogICAgICAgIHNlbGYuX2RiID0gZGIKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNo"
    "KCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAg"
    "ICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAg"
    "IyBGaWx0ZXIgYmFyCiAgICAgICAgZmlsdGVyX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9zZWFyY2ggPSBRTGlu"
    "ZUVkaXQoKQogICAgICAgIHNlbGYuX3NlYXJjaC5zZXRQbGFjZWhvbGRlclRleHQoIlNlYXJjaCBsZXNzb25zLi4uIikKICAgICAg"
    "ICBzZWxmLl9sYW5nX2ZpbHRlciA9IFFDb21ib0JveCgpCiAgICAgICAgc2VsZi5fbGFuZ19maWx0ZXIuYWRkSXRlbXMoWyJBbGwi"
    "LCAiTFNMIiwgIlB5dGhvbiIsICJQeVNpZGU2IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJKYXZhU2Ny"
    "aXB0IiwgIk90aGVyIl0pCiAgICAgICAgc2VsZi5fc2VhcmNoLnRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5yZWZyZXNoKQogICAg"
    "ICAgIHNlbGYuX2xhbmdfZmlsdGVyLmN1cnJlbnRUZXh0Q2hhbmdlZC5jb25uZWN0KHNlbGYucmVmcmVzaCkKICAgICAgICBmaWx0"
    "ZXJfcm93LmFkZFdpZGdldChRTGFiZWwoIlNlYXJjaDoiKSkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChzZWxmLl9zZWFy"
    "Y2gsIDEpCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJMYW5ndWFnZToiKSkKICAgICAgICBmaWx0ZXJfcm93"
    "LmFkZFdpZGdldChzZWxmLl9sYW5nX2ZpbHRlcikKICAgICAgICByb290LmFkZExheW91dChmaWx0ZXJfcm93KQoKICAgICAgICBi"
    "dG5fYmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9hZGQgPSBfZ290aGljX2J0bigi4pymIEFkZCBMZXNzb24iKQogICAg"
    "ICAgIGJ0bl9kZWwgPSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIpCiAgICAgICAgYnRuX2FkZC5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fZG9fYWRkKQogICAgICAgIGJ0bl9kZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBidG5fYmFy"
    "LmFkZFdpZGdldChidG5fYWRkKQogICAgICAgIGJ0bl9iYXIuYWRkV2lkZ2V0KGJ0bl9kZWwpCiAgICAgICAgYnRuX2Jhci5hZGRT"
    "dHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChidG5fYmFyKQoKICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdl"
    "dCgwLCA0KQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoCiAgICAgICAgICAgIFsiTGFuZ3Vh"
    "Z2UiLCAiUmVmZXJlbmNlIEtleSIsICJTdW1tYXJ5IiwgIkVudmlyb25tZW50Il0KICAgICAgICApCiAgICAgICAgc2VsZi5fdGFi"
    "bGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAyLCBRSGVhZGVyVmlldy5SZXNp"
    "emVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0"
    "cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRp"
    "bmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkK"
    "ICAgICAgICBzZWxmLl90YWJsZS5pdGVtU2VsZWN0aW9uQ2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX3NlbGVjdCkKCiAgICAgICAg"
    "IyBVc2Ugc3BsaXR0ZXIgYmV0d2VlbiB0YWJsZSBhbmQgZGV0YWlsCiAgICAgICAgc3BsaXR0ZXIgPSBRU3BsaXR0ZXIoUXQuT3Jp"
    "ZW50YXRpb24uVmVydGljYWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlKQoKICAgICAgICAjIERldGFp"
    "bCBwYW5lbAogICAgICAgIGRldGFpbF93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBkZXRhaWxfbGF5b3V0ID0gUVZCb3hMYXlv"
    "dXQoZGV0YWlsX3dpZGdldCkKICAgICAgICBkZXRhaWxfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCA0LCAwLCAwKQogICAg"
    "ICAgIGRldGFpbF9sYXlvdXQuc2V0U3BhY2luZygyKQoKICAgICAgICBkZXRhaWxfaGVhZGVyID0gUUhCb3hMYXlvdXQoKQogICAg"
    "ICAgIGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIEZVTEwgUlVMRSIpKQogICAgICAgIGRldGFpbF9o"
    "ZWFkZXIuYWRkU3RyZXRjaCgpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZSA9IF9nb3RoaWNfYnRuKCJFZGl0IikKICAgICAg"
    "ICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldEZpeGVkV2lkdGgoNTApCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRDaGVj"
    "a2FibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnRvZ2dsZWQuY29ubmVjdChzZWxmLl90b2dnbGVfZWRpdF9t"
    "b2RlKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUgPSBfZ290aGljX2J0bigiU2F2ZSIpCiAgICAgICAgc2VsZi5fYnRuX3Nh"
    "dmVfcnVsZS5zZXRGaXhlZFdpZHRoKDUwKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuc2V0VmlzaWJsZShGYWxzZSkKICAg"
    "ICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9zYXZlX3J1bGVfZWRpdCkKICAgICAgICBkZXRh"
    "aWxfaGVhZGVyLmFkZFdpZGdldChzZWxmLl9idG5fZWRpdF9ydWxlKQogICAgICAgIGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KHNl"
    "bGYuX2J0bl9zYXZlX3J1bGUpCiAgICAgICAgZGV0YWlsX2xheW91dC5hZGRMYXlvdXQoZGV0YWlsX2hlYWRlcikKCiAgICAgICAg"
    "c2VsZi5fZGV0YWlsID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBz"
    "ZWxmLl9kZXRhaWwuc2V0TWluaW11bUhlaWdodCgxMjApCiAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHgg"
    "c29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6"
    "ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAgICApCiAgICAgICAgZGV0YWlsX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fZGV0"
    "YWlsKQogICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChkZXRhaWxfd2lkZ2V0KQogICAgICAgIHNwbGl0dGVyLnNldFNpemVzKFsz"
    "MDAsIDE4MF0pCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc3BsaXR0ZXIsIDEpCgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3Rb"
    "ZGljdF0gPSBbXQogICAgICAgIHNlbGYuX2VkaXRpbmdfcm93OiBpbnQgPSAtMQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgcSAgICA9IHNlbGYuX3NlYXJjaC50ZXh0KCkKICAgICAgICBsYW5nID0gc2VsZi5fbGFuZ19maWx0ZXIuY3Vy"
    "cmVudFRleHQoKQogICAgICAgIGxhbmcgPSAiIiBpZiBsYW5nID09ICJBbGwiIGVsc2UgbGFuZwogICAgICAgIHNlbGYuX3JlY29y"
    "ZHMgPSBzZWxmLl9kYi5zZWFyY2gocXVlcnk9cSwgbGFuZ3VhZ2U9bGFuZykKICAgICAgICBzZWxmLl90YWJsZS5zZXRSb3dDb3Vu"
    "dCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9IHNlbGYuX3RhYmxlLnJvd0NvdW50"
    "KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwg"
    "MCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgibGFuZ3VhZ2UiLCIiKSkpCiAgICAgICAgICAgIHNl"
    "bGYuX3RhYmxlLnNldEl0ZW0ociwgMSwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgicmVmZXJlbmNl"
    "X2tleSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAyLAogICAgICAgICAgICAgICAgUVRhYmxlV2lk"
    "Z2V0SXRlbShyZWMuZ2V0KCJzdW1tYXJ5IiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDMsCiAgICAg"
    "ICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoImVudmlyb25tZW50IiwiIikpKQoKICAgIGRlZiBfb25fc2VsZWN0"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgc2VsZi5fZWRpdGlu"
    "Z19yb3cgPSByb3cKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmVjID0gc2Vs"
    "Zi5fcmVjb3Jkc1tyb3ddCiAgICAgICAgICAgIHNlbGYuX2RldGFpbC5zZXRQbGFpblRleHQoCiAgICAgICAgICAgICAgICByZWMu"
    "Z2V0KCJmdWxsX3J1bGUiLCIiKSArICJcblxuIiArCiAgICAgICAgICAgICAgICAoIlJlc29sdXRpb246ICIgKyByZWMuZ2V0KCJy"
    "ZXNvbHV0aW9uIiwiIikgaWYgcmVjLmdldCgicmVzb2x1dGlvbiIpIGVsc2UgIiIpCiAgICAgICAgICAgICkKICAgICAgICAgICAg"
    "IyBSZXNldCBlZGl0IG1vZGUgb24gbmV3IHNlbGVjdGlvbgogICAgICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldENoZWNr"
    "ZWQoRmFsc2UpCgogICAgZGVmIF90b2dnbGVfZWRpdF9tb2RlKHNlbGYsIGVkaXRpbmc6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAg"
    "c2VsZi5fZGV0YWlsLnNldFJlYWRPbmx5KG5vdCBlZGl0aW5nKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuc2V0VmlzaWJs"
    "ZShlZGl0aW5nKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0VGV4dCgiQ2FuY2VsIiBpZiBlZGl0aW5nIGVsc2UgIkVk"
    "aXQiKQogICAgICAgIGlmIGVkaXRpbmc6CiAgICAgICAgICAgIHNlbGYuX2RldGFpbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAx"
    "cHggc29saWQge0NfR09MRF9ESU19OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7"
    "IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNl"
    "bGYuX2RldGFpbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0Nf"
    "R09MRH07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICAgICAg"
    "ZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDExcHg7IHBhZGRpbmc6IDRweDsiCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgIyBSZWxvYWQgb3JpZ2luYWwgY29udGVudCBvbiBjYW5jZWwKICAgICAgICAgICAgc2VsZi5fb25f"
    "c2VsZWN0KCkKCiAgICBkZWYgX3NhdmVfcnVsZV9lZGl0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fZWRpdGlu"
    "Z19yb3cKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgdGV4dCA9IHNlbGYuX2Rl"
    "dGFpbC50b1BsYWluVGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgIyBTcGxpdCByZXNvbHV0aW9uIGJhY2sgb3V0IGlmIHByZXNl"
    "bnQKICAgICAgICAgICAgaWYgIlxuXG5SZXNvbHV0aW9uOiAiIGluIHRleHQ6CiAgICAgICAgICAgICAgICBwYXJ0cyA9IHRleHQu"
    "c3BsaXQoIlxuXG5SZXNvbHV0aW9uOiAiLCAxKQogICAgICAgICAgICAgICAgZnVsbF9ydWxlICA9IHBhcnRzWzBdLnN0cmlwKCkK"
    "ICAgICAgICAgICAgICAgIHJlc29sdXRpb24gPSBwYXJ0c1sxXS5zdHJpcCgpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "ICAgICBmdWxsX3J1bGUgID0gdGV4dAogICAgICAgICAgICAgICAgcmVzb2x1dGlvbiA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQo"
    "InJlc29sdXRpb24iLCAiIikKICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tyb3ddWyJmdWxsX3J1bGUiXSAgPSBmdWxsX3J1bGUK"
    "ICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tyb3ddWyJyZXNvbHV0aW9uIl0gPSByZXNvbHV0aW9uCiAgICAgICAgICAgIHdyaXRl"
    "X2pzb25sKHNlbGYuX2RiLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldENo"
    "ZWNrZWQoRmFsc2UpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJBZGQgTGVzc29uIikKICAgICAgICBk"
    "bGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5yZXNp"
    "emUoNTAwLCA0MDApCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKICAgICAgICBlbnYgID0gUUxpbmVFZGl0KCJMU0wi"
    "KQogICAgICAgIGxhbmcgPSBRTGluZUVkaXQoIkxTTCIpCiAgICAgICAgcmVmICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc3VtbSA9"
    "IFFMaW5lRWRpdCgpCiAgICAgICAgcnVsZSA9IFFUZXh0RWRpdCgpCiAgICAgICAgcnVsZS5zZXRNYXhpbXVtSGVpZ2h0KDEwMCkK"
    "ICAgICAgICByZXMgID0gUUxpbmVFZGl0KCkKICAgICAgICBsaW5rID0gUUxpbmVFZGl0KCkKICAgICAgICBmb3IgbGFiZWwsIHcg"
    "aW4gWwogICAgICAgICAgICAoIkVudmlyb25tZW50OiIsIGVudiksICgiTGFuZ3VhZ2U6IiwgbGFuZyksCiAgICAgICAgICAgICgi"
    "UmVmZXJlbmNlIEtleToiLCByZWYpLCAoIlN1bW1hcnk6Iiwgc3VtbSksCiAgICAgICAgICAgICgiRnVsbCBSdWxlOiIsIHJ1bGUp"
    "LCAoIlJlc29sdXRpb246IiwgcmVzKSwKICAgICAgICAgICAgKCJMaW5rOiIsIGxpbmspLAogICAgICAgIF06CiAgICAgICAgICAg"
    "IGZvcm0uYWRkUm93KGxhYmVsLCB3KQogICAgICAgIGJ0bnMgPSBRSEJveExheW91dCgpCiAgICAgICAgb2sgPSBfZ290aGljX2J0"
    "bigiU2F2ZSIpOyBjeCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIG9rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0"
    "KTsgY3guY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5zLmFkZFdpZGdl"
    "dChjeCkKICAgICAgICBmb3JtLmFkZFJvdyhidG5zKQogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2Rl"
    "LkFjY2VwdGVkOgogICAgICAgICAgICBzZWxmLl9kYi5hZGQoCiAgICAgICAgICAgICAgICBlbnZpcm9ubWVudD1lbnYudGV4dCgp"
    "LnN0cmlwKCksCiAgICAgICAgICAgICAgICBsYW5ndWFnZT1sYW5nLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgcmVm"
    "ZXJlbmNlX2tleT1yZWYudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICBzdW1tYXJ5PXN1bW0udGV4dCgpLnN0cmlwKCks"
    "CiAgICAgICAgICAgICAgICBmdWxsX3J1bGU9cnVsZS50b1BsYWluVGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICByZXNv"
    "bHV0aW9uPXJlcy50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGxpbms9bGluay50ZXh0KCkuc3RyaXAoKSwKICAgICAg"
    "ICAgICAgKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6"
    "CiAgICAgICAgICAgIHJlY19pZCA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQoImlkIiwiIikKICAgICAgICAgICAgcmVwbHkgPSBR"
    "TWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgICAgIHNlbGYsICJEZWxldGUgTGVzc29uIiwKICAgICAgICAgICAgICAg"
    "ICJEZWxldGUgdGhpcyBsZXNzb24/IENhbm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5k"
    "YXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYg"
    "cmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICAgICAgc2VsZi5fZGIuZGVsZXRlKHJl"
    "Y19pZCkKICAgICAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgoKIyDilIDilIAgTU9EVUxFIFRSQUNLRVIgVEFCIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgApjbGFzcyBNb2R1bGVUcmFja2VyVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBQZXJzb25hbCBtb2R1bGUgcGlw"
    "ZWxpbmUgdHJhY2tlci4KICAgIFRyYWNrIHBsYW5uZWQvaW4tcHJvZ3Jlc3MvYnVpbHQgbW9kdWxlcyBhcyB0aGV5IGFyZSBkZXNp"
    "Z25lZC4KICAgIEVhY2ggbW9kdWxlIGhhczogTmFtZSwgU3RhdHVzLCBEZXNjcmlwdGlvbiwgTm90ZXMuCiAgICBFeHBvcnQgdG8g"
    "VFhUIGZvciBwYXN0aW5nIGludG8gc2Vzc2lvbnMuCiAgICBJbXBvcnQ6IHBhc3RlIGEgZmluYWxpemVkIHNwZWMsIGl0IHBhcnNl"
    "cyBuYW1lIGFuZCBkZXRhaWxzLgogICAgVGhpcyBpcyBhIGRlc2lnbiBub3RlYm9vayDigJQgbm90IGNvbm5lY3RlZCB0byBkZWNr"
    "X2J1aWxkZXIncyBNT0RVTEUgcmVnaXN0cnkuCiAgICAiIiIKCiAgICBTVEFUVVNFUyA9IFsiSWRlYSIsICJEZXNpZ25pbmciLCAi"
    "UmVhZHkgdG8gQnVpbGQiLCAiUGFydGlhbCIsICJCdWlsdCJdCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToK"
    "ICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRoID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikg"
    "LyAibW9kdWxlX3RyYWNrZXIuanNvbmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2Vs"
    "Zi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAg"
    "ICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgQnV0dG9uIGJhcgogICAgICAgIGJ0bl9iYXIgPSBRSEJveExheW91"
    "dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCJBZGQgTW9kdWxlIikKICAgICAgICBzZWxmLl9idG5f"
    "ZWRpdCAgID0gX2dvdGhpY19idG4oIkVkaXQiKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgPSBfZ290aGljX2J0bigiRGVsZXRl"
    "IikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0ID0gX2dvdGhpY19idG4oIkV4cG9ydCBUWFQiKQogICAgICAgIHNlbGYuX2J0bl9p"
    "bXBvcnQgPSBfZ290aGljX2J0bigiSW1wb3J0IFNwZWMiKQogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBzZWxmLl9i"
    "dG5fZWRpdCwgc2VsZi5fYnRuX2RlbGV0ZSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX2V4cG9ydCwgc2VsZi5fYnRuX2lt"
    "cG9ydCk6CiAgICAgICAgICAgIGIuc2V0TWluaW11bVdpZHRoKDgwKQogICAgICAgICAgICBiLnNldE1pbmltdW1IZWlnaHQoMjYp"
    "CiAgICAgICAgICAgIGJ0bl9iYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYnRuX2Jhci5hZGRTdHJldGNoKCkKICAgICAgICByb290"
    "LmFkZExheW91dChidG5fYmFyKQoKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAg"
    "ICAgICAgc2VsZi5fYnRuX2VkaXQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2VkaXQpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0"
    "ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQuY2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuX2RvX2V4cG9ydCkKICAgICAgICBzZWxmLl9idG5faW1wb3J0LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19pbXBvcnQp"
    "CgogICAgICAgICMgVGFibGUKICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAzKQogICAgICAgIHNlbGYuX3Rh"
    "YmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJNb2R1bGUgTmFtZSIsICJTdGF0dXMiLCAiRGVzY3JpcHRpb24iXSkKICAg"
    "ICAgICBoaCA9IHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDAs"
    "IFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Q29sdW1uV2lkdGgoMCwgMTYwKQog"
    "ICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2Vs"
    "Zi5fdGFibGUuc2V0Q29sdW1uV2lkdGgoMSwgMTAwKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDIsIFFIZWFkZXJW"
    "aWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAgICAg"
    "ICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLl90YWJsZS5zZXRB"
    "bHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVlKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9z"
    "dHlsZSgpKQogICAgICAgIHNlbGYuX3RhYmxlLml0ZW1TZWxlY3Rpb25DaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fc2VsZWN0KQoK"
    "ICAgICAgICAjIFNwbGl0dGVyCiAgICAgICAgc3BsaXR0ZXIgPSBRU3BsaXR0ZXIoUXQuT3JpZW50YXRpb24uVmVydGljYWwpCiAg"
    "ICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlKQoKICAgICAgICAjIE5vdGVzIHBhbmVsCiAgICAgICAgbm90ZXNf"
    "d2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgbm90ZXNfbGF5b3V0ID0gUVZCb3hMYXlvdXQobm90ZXNfd2lkZ2V0KQogICAgICAg"
    "IG5vdGVzX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgNCwgMCwgMCkKICAgICAgICBub3Rlc19sYXlvdXQuc2V0U3BhY2lu"
    "ZygyKQogICAgICAgIG5vdGVzX2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgTk9URVMiKSkKICAgICAgICBzZWxm"
    "Ll9ub3Rlc19kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUp"
    "CiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheS5zZXRNaW5pbXVtSGVpZ2h0KDEyMCkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNw"
    "bGF5LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAg"
    "ICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVD"
    "S19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAgICApCiAgICAgICAgbm90ZXNfbGF5"
    "b3V0LmFkZFdpZGdldChzZWxmLl9ub3Rlc19kaXNwbGF5KQogICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChub3Rlc193aWRnZXQp"
    "CiAgICAgICAgc3BsaXR0ZXIuc2V0U2l6ZXMoWzI1MCwgMTUwXSkKICAgICAgICByb290LmFkZFdpZGdldChzcGxpdHRlciwgMSkK"
    "CiAgICAgICAgIyBDb3VudCBsYWJlbAogICAgICAgIHNlbGYuX2NvdW50X2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLl9j"
    "b3VudF9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsg"
    "Zm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2Nv"
    "dW50X2xibCkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pzb25s"
    "KHNlbGYuX3BhdGgpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3Jl"
    "Y29yZHM6CiAgICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLmluc2Vy"
    "dFJvdyhyKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDAsIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgibmFt"
    "ZSIsICIiKSkpCiAgICAgICAgICAgIHN0YXR1c19pdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJzdGF0dXMiLCAiSWRl"
    "YSIpKQogICAgICAgICAgICAjIENvbG9yIGJ5IHN0YXR1cwogICAgICAgICAgICBzdGF0dXNfY29sb3JzID0gewogICAgICAgICAg"
    "ICAgICAgIklkZWEiOiAgICAgICAgICAgICBDX1RFWFRfRElNLAogICAgICAgICAgICAgICAgIkRlc2lnbmluZyI6ICAgICAgICBD"
    "X0dPTERfRElNLAogICAgICAgICAgICAgICAgIlJlYWR5IHRvIEJ1aWxkIjogICBDX1BVUlBMRSwKICAgICAgICAgICAgICAgICJQ"
    "YXJ0aWFsIjogICAgICAgICAgIiNjYzg4NDQiLAogICAgICAgICAgICAgICAgIkJ1aWx0IjogICAgICAgICAgICBDX0dSRUVOLAog"
    "ICAgICAgICAgICB9CiAgICAgICAgICAgIHN0YXR1c19pdGVtLnNldEZvcmVncm91bmQoCiAgICAgICAgICAgICAgICBRQ29sb3Io"
    "c3RhdHVzX2NvbG9ycy5nZXQocmVjLmdldCgic3RhdHVzIiwiSWRlYSIpLCBDX1RFWFRfRElNKSkKICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDEsIHN0YXR1c19pdGVtKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJ"
    "dGVtKHIsIDIsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoImRlc2NyaXB0aW9uIiwgIiIpWzo4MF0p"
    "KQogICAgICAgIGNvdW50cyA9IHt9CiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICBzID0gcmVj"
    "LmdldCgic3RhdHVzIiwgIklkZWEiKQogICAgICAgICAgICBjb3VudHNbc10gPSBjb3VudHMuZ2V0KHMsIDApICsgMQogICAgICAg"
    "IGNvdW50X3N0ciA9ICIgICIuam9pbihmIntzfToge259IiBmb3IgcywgbiBpbiBjb3VudHMuaXRlbXMoKSkKICAgICAgICBzZWxm"
    "Ll9jb3VudF9sYmwuc2V0VGV4dCgKICAgICAgICAgICAgZiJUb3RhbDoge2xlbihzZWxmLl9yZWNvcmRzKX0gICB7Y291bnRfc3Ry"
    "fSIKICAgICAgICApCgogICAgZGVmIF9vbl9zZWxlY3Qoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5j"
    "dXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmVjID0gc2Vs"
    "Zi5fcmVjb3Jkc1tyb3ddCiAgICAgICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0UGxhaW5UZXh0KHJlYy5nZXQoIm5vdGVz"
    "IiwgIiIpKQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fb3Blbl9lZGl0X2RpYWxvZygpCgog"
    "ICAgZGVmIF9kb19lZGl0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAg"
    "ICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHNlbGYuX29wZW5fZWRpdF9kaWFsb2coc2Vs"
    "Zi5fcmVjb3Jkc1tyb3ddLCByb3cpCgogICAgZGVmIF9vcGVuX2VkaXRfZGlhbG9nKHNlbGYsIHJlYzogZGljdCA9IE5vbmUsIHJv"
    "dzogaW50ID0gLTEpIC0+IE5vbmU6CiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRs"
    "ZSgiTW9kdWxlIiBpZiBub3QgcmVjIGVsc2UgZiJFZGl0OiB7cmVjLmdldCgnbmFtZScsJycpfSIpCiAgICAgICAgZGxnLnNldFN0"
    "eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBkbGcucmVzaXplKDU0MCwg"
    "NDQwKQogICAgICAgIGZvcm0gPSBRVkJveExheW91dChkbGcpCgogICAgICAgIG5hbWVfZmllbGQgPSBRTGluZUVkaXQocmVjLmdl"
    "dCgibmFtZSIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIG5hbWVfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KCJNb2R1bGUg"
    "bmFtZSIpCgogICAgICAgIHN0YXR1c19jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc3RhdHVzX2NvbWJvLmFkZEl0ZW1zKHNl"
    "bGYuU1RBVFVTRVMpCiAgICAgICAgaWYgcmVjOgogICAgICAgICAgICBpZHggPSBzdGF0dXNfY29tYm8uZmluZFRleHQocmVjLmdl"
    "dCgic3RhdHVzIiwiSWRlYSIpKQogICAgICAgICAgICBpZiBpZHggPj0gMDoKICAgICAgICAgICAgICAgIHN0YXR1c19jb21iby5z"
    "ZXRDdXJyZW50SW5kZXgoaWR4KQoKICAgICAgICBkZXNjX2ZpZWxkID0gUUxpbmVFZGl0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwi"
    "IikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgZGVzY19maWVsZC5zZXRQbGFjZWhvbGRlclRleHQoIk9uZS1saW5lIGRlc2NyaXB0"
    "aW9uIikKCiAgICAgICAgbm90ZXNfZmllbGQgPSBRVGV4dEVkaXQoKQogICAgICAgIG5vdGVzX2ZpZWxkLnNldFBsYWluVGV4dChy"
    "ZWMuZ2V0KCJub3RlcyIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIG5vdGVzX2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgK"
    "ICAgICAgICAgICAgIkZ1bGwgbm90ZXMg4oCUIHNwZWMsIGlkZWFzLCByZXF1aXJlbWVudHMsIGVkZ2UgY2FzZXMuLi4iCiAgICAg"
    "ICAgKQogICAgICAgIG5vdGVzX2ZpZWxkLnNldE1pbmltdW1IZWlnaHQoMjAwKQoKICAgICAgICBmb3IgbGFiZWwsIHdpZGdldCBp"
    "biBbCiAgICAgICAgICAgICgiTmFtZToiLCBuYW1lX2ZpZWxkKSwKICAgICAgICAgICAgKCJTdGF0dXM6Iiwgc3RhdHVzX2NvbWJv"
    "KSwKICAgICAgICAgICAgKCJEZXNjcmlwdGlvbjoiLCBkZXNjX2ZpZWxkKSwKICAgICAgICAgICAgKCJOb3RlczoiLCBub3Rlc19m"
    "aWVsZCksCiAgICAgICAgXToKICAgICAgICAgICAgcm93X2xheW91dCA9IFFIQm94TGF5b3V0KCkKICAgICAgICAgICAgbGJsID0g"
    "UUxhYmVsKGxhYmVsKQogICAgICAgICAgICBsYmwuc2V0Rml4ZWRXaWR0aCg5MCkKICAgICAgICAgICAgcm93X2xheW91dC5hZGRX"
    "aWRnZXQobGJsKQogICAgICAgICAgICByb3dfbGF5b3V0LmFkZFdpZGdldCh3aWRnZXQpCiAgICAgICAgICAgIGZvcm0uYWRkTGF5"
    "b3V0KHJvd19sYXlvdXQpCgogICAgICAgIGJ0bl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX3NhdmUgICA9IF9nb3Ro"
    "aWNfYnRuKCJTYXZlIikKICAgICAgICBidG5fY2FuY2VsID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgYnRuX3NhdmUu"
    "Y2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkK"
    "ICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fc2F2ZSkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2FuY2VsKQog"
    "ICAgICAgIGZvcm0uYWRkTGF5b3V0KGJ0bl9yb3cpCgogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2Rl"
    "LkFjY2VwdGVkOgogICAgICAgICAgICBuZXdfcmVjID0gewogICAgICAgICAgICAgICAgImlkIjogICAgICAgICAgcmVjLmdldCgi"
    "aWQiLCBzdHIodXVpZC51dWlkNCgpKSkgaWYgcmVjIGVsc2Ugc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICAgICAibmFt"
    "ZSI6ICAgICAgICBuYW1lX2ZpZWxkLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgc3RhdHVz"
    "X2NvbWJvLmN1cnJlbnRUZXh0KCksCiAgICAgICAgICAgICAgICAiZGVzY3JpcHRpb24iOiBkZXNjX2ZpZWxkLnRleHQoKS5zdHJp"
    "cCgpLAogICAgICAgICAgICAgICAgIm5vdGVzIjogICAgICAgbm90ZXNfZmllbGQudG9QbGFpblRleHQoKS5zdHJpcCgpLAogICAg"
    "ICAgICAgICAgICAgImNyZWF0ZWQiOiAgICAgcmVjLmdldCgiY3JlYXRlZCIsIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpKSBp"
    "ZiByZWMgZWxzZSBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgICAgICJtb2RpZmllZCI6ICAgIGRhdGV0"
    "aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICB9CiAgICAgICAgICAgIGlmIHJvdyA+PSAwOgogICAgICAgICAgICAg"
    "ICAgc2VsZi5fcmVjb3Jkc1tyb3ddID0gbmV3X3JlYwogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgc2VsZi5fcmVj"
    "b3Jkcy5hcHBlbmQobmV3X3JlYykKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAg"
    "ICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNl"
    "bGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAg"
    "ICBuYW1lID0gc2VsZi5fcmVjb3Jkc1tyb3ddLmdldCgibmFtZSIsInRoaXMgbW9kdWxlIikKICAgICAgICAgICAgcmVwbHkgPSBR"
    "TWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgICAgIHNlbGYsICJEZWxldGUgTW9kdWxlIiwKICAgICAgICAgICAgICAg"
    "IGYiRGVsZXRlICd7bmFtZX0nPyBDYW5ub3QgYmUgdW5kb25lLiIsCiAgICAgICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFy"
    "ZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIHJl"
    "cGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMucG9wKHJv"
    "dykKICAgICAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgICAgICBz"
    "ZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZXhwb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBl"
    "eHBvcnRfZGlyID0gY2ZnX3BhdGgoImV4cG9ydHMiKQogICAgICAgICAgICBleHBvcnRfZGlyLm1rZGlyKHBhcmVudHM9VHJ1ZSwg"
    "ZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAgICAgdHMgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJVklbSVkXyVIJU0lUyIpCiAg"
    "ICAgICAgICAgIG91dF9wYXRoID0gZXhwb3J0X2RpciAvIGYibW9kdWxlc197dHN9LnR4dCIKICAgICAgICAgICAgbGluZXMgPSBb"
    "CiAgICAgICAgICAgICAgICAiRUNITyBERUNLIOKAlCBNT0RVTEUgVFJBQ0tFUiBFWFBPUlQiLAogICAgICAgICAgICAgICAgZiJF"
    "eHBvcnRlZDoge2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWS0lbS0lZCAlSDolTTolUycpfSIsCiAgICAgICAgICAgICAgICBm"
    "IlRvdGFsIG1vZHVsZXM6IHtsZW4oc2VsZi5fcmVjb3Jkcyl9IiwKICAgICAgICAgICAgICAgICI9IiAqIDYwLAogICAgICAgICAg"
    "ICAgICAgIiIsCiAgICAgICAgICAgIF0KICAgICAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICAg"
    "ICAgbGluZXMuZXh0ZW5kKFsKICAgICAgICAgICAgICAgICAgICBmIk1PRFVMRToge3JlYy5nZXQoJ25hbWUnLCcnKX0iLAogICAg"
    "ICAgICAgICAgICAgICAgIGYiU3RhdHVzOiB7cmVjLmdldCgnc3RhdHVzJywnJyl9IiwKICAgICAgICAgICAgICAgICAgICBmIkRl"
    "c2NyaXB0aW9uOiB7cmVjLmdldCgnZGVzY3JpcHRpb24nLCcnKX0iLAogICAgICAgICAgICAgICAgICAgICIiLAogICAgICAgICAg"
    "ICAgICAgICAgICJOb3RlczoiLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAgICAgICAgICAgICAg"
    "ICAgICAgIiIsCiAgICAgICAgICAgICAgICAgICAgIi0iICogNDAsCiAgICAgICAgICAgICAgICAgICAgIiIsCiAgICAgICAgICAg"
    "ICAgICBdKQogICAgICAgICAgICBvdXRfcGF0aC53cml0ZV90ZXh0KCJcbiIuam9pbihsaW5lcyksIGVuY29kaW5nPSJ1dGYtOCIp"
    "CiAgICAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KCJcbiIuam9pbihsaW5lcykpCiAgICAgICAgICAg"
    "IFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwgIkV4cG9ydGVkIiwKICAgICAgICAgICAgICAg"
    "IGYiTW9kdWxlIHRyYWNrZXIgZXhwb3J0ZWQgdG86XG57b3V0X3BhdGh9XG5cbkFsc28gY29waWVkIHRvIGNsaXBib2FyZC4iCiAg"
    "ICAgICAgICAgICkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIFFNZXNzYWdlQm94Lndhcm5pbmco"
    "c2VsZiwgIkV4cG9ydCBFcnJvciIsIHN0cihlKSkKCiAgICBkZWYgX2RvX2ltcG9ydChzZWxmKSAtPiBOb25lOgogICAgICAgICIi"
    "IkltcG9ydCBhIG1vZHVsZSBzcGVjIGZyb20gY2xpcGJvYXJkIG9yIHR5cGVkIHRleHQuIiIiCiAgICAgICAgZGxnID0gUURpYWxv"
    "ZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiSW1wb3J0IE1vZHVsZSBTcGVjIikKICAgICAgICBkbGcuc2V0U3R5"
    "bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5yZXNpemUoNTAwLCAz"
    "NDApCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoZGxnKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoUUxhYmVsKAogICAg"
    "ICAgICAgICAiUGFzdGUgYSBtb2R1bGUgc3BlYyBiZWxvdy5cbiIKICAgICAgICAgICAgIkZpcnN0IGxpbmUgd2lsbCBiZSB1c2Vk"
    "IGFzIHRoZSBtb2R1bGUgbmFtZS4iCiAgICAgICAgKSkKICAgICAgICB0ZXh0X2ZpZWxkID0gUVRleHRFZGl0KCkKICAgICAgICB0"
    "ZXh0X2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgiUGFzdGUgbW9kdWxlIHNwZWMgaGVyZS4uLiIpCiAgICAgICAgbGF5b3V0LmFk"
    "ZFdpZGdldCh0ZXh0X2ZpZWxkLCAxKQogICAgICAgIGJ0bl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX29rICAgICA9"
    "IF9nb3RoaWNfYnRuKCJJbXBvcnQiKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBi"
    "dG5fb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3QoZGxnLnJl"
    "amVjdCkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fb2spCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNl"
    "bCkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGJ0bl9yb3cpCgogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFs"
    "b2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICByYXcgPSB0ZXh0X2ZpZWxkLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQogICAgICAg"
    "ICAgICBpZiBub3QgcmF3OgogICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAgIGxpbmVzID0gcmF3LnNwbGl0bGluZXMo"
    "KQogICAgICAgICAgICAjIEZpcnN0IG5vbi1lbXB0eSBsaW5lID0gbmFtZQogICAgICAgICAgICBuYW1lID0gIiIKICAgICAgICAg"
    "ICAgZm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAgICAgICAgICBpZiBsaW5lLnN0cmlwKCk6CiAgICAgICAgICAgICAgICAgICAg"
    "bmFtZSA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIG5ld19yZWMgPSB7CiAgICAg"
    "ICAgICAgICAgICAiaWQiOiAgICAgICAgICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgICAgICJuYW1lIjogICAgICAg"
    "IG5hbWVbOjYwXSwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAgICAgICJJZGVhIiwKICAgICAgICAgICAgICAgICJkZXNjcmlw"
    "dGlvbiI6ICIiLAogICAgICAgICAgICAgICAgIm5vdGVzIjogICAgICAgcmF3LAogICAgICAgICAgICAgICAgImNyZWF0ZWQiOiAg"
    "ICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAgICAgICAgICAgICAibW9kaWZpZWQiOiAgICBkYXRldGltZS5ub3co"
    "KS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgfQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChuZXdfcmVjKQogICAg"
    "ICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoK"
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
    "UzoKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXRlKHN0YXRlKQoKCiMg4pSA4pSAIE1BSU4gV0lORE9XIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBFY2hvRGVjayhRTWFpbldpbmRvdyk6CiAgICAiIiIKICAgIFRoZSBtYWlu"
    "IEVjaG8gRGVjayB3aW5kb3cuCiAgICBBc3NlbWJsZXMgYWxsIHdpZGdldHMsIGNvbm5lY3RzIGFsbCBzaWduYWxzLCBtYW5hZ2Vz"
    "IGFsbCBzdGF0ZS4KICAgICIiIgoKICAgICMg4pSA4pSAIFRvcnBvciB0aHJlc2hvbGRzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgX0VYVEVSTkFMX1ZSQU1fVE9SUE9SX0dCICAgID0g"
    "MS41ICAgIyBleHRlcm5hbCBWUkFNID4gdGhpcyDihpIgY29uc2lkZXIgdG9ycG9yCiAgICBfRVhURVJOQUxfVlJBTV9XQUtFX0dC"
    "ICAgICAgPSAwLjggICAjIGV4dGVybmFsIFZSQU0gPCB0aGlzIOKGkiBjb25zaWRlciB3YWtlCiAgICBfVE9SUE9SX1NVU1RBSU5F"
    "RF9USUNLUyAgICAgPSA2ICAgICAjIDYgw5cgNXMgPSAzMCBzZWNvbmRzIHN1c3RhaW5lZAogICAgX1dBS0VfU1VTVEFJTkVEX1RJ"
    "Q0tTICAgICAgID0gMTIgICAgIyA2MCBzZWNvbmRzIHN1c3RhaW5lZCBsb3cgcHJlc3N1cmUKCiAgICBkZWYgX19pbml0X18oc2Vs"
    "Zik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCgogICAgICAgICMg4pSA4pSAIENvcmUgc3RhdGUg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc3Rh"
    "dHVzICAgICAgICAgICAgICA9ICJPRkZMSU5FIgogICAgICAgIHNlbGYuX3Nlc3Npb25fc3RhcnQgICAgICAgPSB0aW1lLnRpbWUo"
    "KQogICAgICAgIHNlbGYuX3Rva2VuX2NvdW50ICAgICAgICAgPSAwCiAgICAgICAgc2VsZi5fZmFjZV9sb2NrZWQgICAgICAgICA9"
    "IEZhbHNlCiAgICAgICAgc2VsZi5fYmxpbmtfc3RhdGUgICAgICAgICA9IFRydWUKICAgICAgICBzZWxmLl9tb2RlbF9sb2FkZWQg"
    "ICAgICAgID0gRmFsc2UKICAgICAgICBzZWxmLl9zZXNzaW9uX2lkICAgICAgICAgID0gZiJzZXNzaW9uX3tkYXRldGltZS5ub3co"
    "KS5zdHJmdGltZSgnJVklbSVkXyVIJU0lUycpfSIKICAgICAgICBzZWxmLl9hY3RpdmVfdGhyZWFkczogbGlzdCA9IFtdICAjIGtl"
    "ZXAgcmVmcyB0byBwcmV2ZW50IEdDIHdoaWxlIHJ1bm5pbmcKICAgICAgICBzZWxmLl9maXJzdF90b2tlbjogYm9vbCA9IFRydWUg"
    "ICAjIHdyaXRlIHNwZWFrZXIgbGFiZWwgYmVmb3JlIGZpcnN0IHN0cmVhbWluZyB0b2tlbgoKICAgICAgICAjIFRvcnBvciAvIFZS"
    "QU0gdHJhY2tpbmcKICAgICAgICBzZWxmLl90b3Jwb3Jfc3RhdGUgICAgICAgID0gIkFXQUtFIgogICAgICAgIHNlbGYuX2RlY2tf"
    "dnJhbV9iYXNlICA9IDAuMCAgICMgYmFzZWxpbmUgVlJBTSBhZnRlciBtb2RlbCBsb2FkCiAgICAgICAgc2VsZi5fdnJhbV9wcmVz"
    "c3VyZV90aWNrcyA9IDAgICAgICMgc3VzdGFpbmVkIHByZXNzdXJlIGNvdW50ZXIKICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90"
    "aWNrcyAgID0gMCAgICAgIyBzdXN0YWluZWQgcmVsaWVmIGNvdW50ZXIKICAgICAgICBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lv"
    "bnMgPSAwCiAgICAgICAgc2VsZi5fdG9ycG9yX3NpbmNlICAgICAgICA9IE5vbmUgICMgZGF0ZXRpbWUgd2hlbiB0b3Jwb3IgYmVn"
    "YW4KICAgICAgICBzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gID0gIiIgICAjIGZvcm1hdHRlZCBkdXJhdGlvbiBzdHJpbmcKCiAg"
    "ICAgICAgIyDilIDilIAgTWFuYWdlcnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fbWVtb3J5ICAgPSBNZW1vcnlNYW5hZ2VyKCkKICAgICAg"
    "ICBzZWxmLl9zZXNzaW9ucyA9IFNlc3Npb25NYW5hZ2VyKCkKICAgICAgICBzZWxmLl9sZXNzb25zICA9IExlc3NvbnNMZWFybmVk"
    "REIoKQogICAgICAgIHNlbGYuX3Rhc2tzICAgID0gVGFza01hbmFnZXIoKQogICAgICAgIHNlbGYuX3JlY29yZHNfY2FjaGU6IGxp"
    "c3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3JlY29yZHNfaW5pdGlhbGl6ZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX3JlY29y"
    "ZHNfY3VycmVudF9mb2xkZXJfaWQgPSAicm9vdCIKICAgICAgICBzZWxmLl9nb29nbGVfYXV0aF9yZWFkeSA9IEZhbHNlCiAgICAg"
    "ICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGltZXI6IE9wdGlvbmFsW1FUaW1lcl0gPSBOb25lCiAgICAgICAgc2VsZi5fZ29vZ2xl"
    "X3JlY29yZHNfcmVmcmVzaF90aW1lcjogT3B0aW9uYWxbUVRpbWVyXSA9IE5vbmUKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYl9p"
    "bmRleCA9IC0xCiAgICAgICAgc2VsZi5fdGFza3NfdGFiX2luZGV4ID0gLTEKICAgICAgICBzZWxmLl90YXNrX3Nob3dfY29tcGxl"
    "dGVkID0gRmFsc2UKICAgICAgICBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID0gIm5leHRfM19tb250aHMiCgogICAgICAgICMg4pSA"
    "4pSAIEdvb2dsZSBTZXJ2aWNlcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICAjIEluc3RhbnRpYXRlIHNlcnZpY2Ugd3JhcHBlcnMgdXAtZnJvbnQ7IGF1dGggaXMgZm9yY2VkIGxhdGVyCiAg"
    "ICAgICAgIyBmcm9tIG1haW4oKSBhZnRlciB3aW5kb3cuc2hvdygpIHdoZW4gdGhlIGV2ZW50IGxvb3AgaXMgcnVubmluZy4KICAg"
    "ICAgICBnX2NyZWRzX3BhdGggPSBQYXRoKENGRy5nZXQoImdvb2dsZSIsIHt9KS5nZXQoCiAgICAgICAgICAgICJjcmVkZW50aWFs"
    "cyIsCiAgICAgICAgICAgIHN0cihjZmdfcGF0aCgiZ29vZ2xlIikgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iKQogICAgICAg"
    "ICkpCiAgICAgICAgZ190b2tlbl9wYXRoID0gUGF0aChDRkcuZ2V0KCJnb29nbGUiLCB7fSkuZ2V0KAogICAgICAgICAgICAidG9r"
    "ZW4iLAogICAgICAgICAgICBzdHIoY2ZnX3BhdGgoImdvb2dsZSIpIC8gInRva2VuLmpzb24iKQogICAgICAgICkpCiAgICAgICAg"
    "c2VsZi5fZ2NhbCA9IEdvb2dsZUNhbGVuZGFyU2VydmljZShnX2NyZWRzX3BhdGgsIGdfdG9rZW5fcGF0aCkKICAgICAgICBzZWxm"
    "Ll9nZHJpdmUgPSBHb29nbGVEb2NzRHJpdmVTZXJ2aWNlKAogICAgICAgICAgICBnX2NyZWRzX3BhdGgsCiAgICAgICAgICAgIGdf"
    "dG9rZW5fcGF0aCwKICAgICAgICAgICAgbG9nZ2VyPWxhbWJkYSBtc2csIGxldmVsPSJJTkZPIjogc2VsZi5fZGlhZ190YWIubG9n"
    "KGYiW0dEUklWRV0ge21zZ30iLCBsZXZlbCkKICAgICAgICApCgogICAgICAgICMgU2VlZCBMU0wgcnVsZXMgb24gZmlyc3QgcnVu"
    "CiAgICAgICAgc2VsZi5fbGVzc29ucy5zZWVkX2xzbF9ydWxlcygpCgogICAgICAgICMgTG9hZCBlbnRpdHkgc3RhdGUKICAgICAg"
    "ICBzZWxmLl9zdGF0ZSA9IHNlbGYuX21lbW9yeS5sb2FkX3N0YXRlKCkKICAgICAgICBzZWxmLl9zdGF0ZVsic2Vzc2lvbl9jb3Vu"
    "dCJdID0gc2VsZi5fc3RhdGUuZ2V0KCJzZXNzaW9uX2NvdW50IiwwKSArIDEKICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9zdGFy"
    "dHVwIl0gID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgc2VsZi5fbWVtb3J5LnNhdmVfc3RhdGUoc2VsZi5fc3RhdGUpCgogICAg"
    "ICAgICMgQnVpbGQgYWRhcHRvcgogICAgICAgIHNlbGYuX2FkYXB0b3IgPSBidWlsZF9hZGFwdG9yX2Zyb21fY29uZmlnKCkKCiAg"
    "ICAgICAgIyBGYWNlIHRpbWVyIG1hbmFnZXIgKHNldCB1cCBhZnRlciB3aWRnZXRzIGJ1aWx0KQogICAgICAgIHNlbGYuX2ZhY2Vf"
    "dGltZXJfbWdyOiBPcHRpb25hbFtGYWNlVGltZXJNYW5hZ2VyXSA9IE5vbmUKCiAgICAgICAgIyDilIDilIAgQnVpbGQgVUkg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgc2VsZi5zZXRXaW5kb3dUaXRsZShBUFBfTkFNRSkKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDEyMDAsIDc1"
    "MCkKICAgICAgICBzZWxmLnJlc2l6ZSgxMzUwLCA4NTApCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KFNUWUxFKQoKICAgICAg"
    "ICBzZWxmLl9idWlsZF91aSgpCgogICAgICAgICMgRmFjZSB0aW1lciBtYW5hZ2VyIHdpcmVkIHRvIHdpZGdldHMKICAgICAgICBz"
    "ZWxmLl9mYWNlX3RpbWVyX21nciA9IEZhY2VUaW1lck1hbmFnZXIoCiAgICAgICAgICAgIHNlbGYuX21pcnJvciwgc2VsZi5fZW1v"
    "dGlvbl9ibG9jawogICAgICAgICkKCiAgICAgICAgIyDilIDilIAgVGltZXJzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3N0YXRz"
    "X3RpbWVyID0gUVRpbWVyKCkKICAgICAgICBzZWxmLl9zdGF0c190aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fdXBkYXRlX3N0"
    "YXRzKQogICAgICAgIHNlbGYuX3N0YXRzX3RpbWVyLnN0YXJ0KDEwMDApCgogICAgICAgIHNlbGYuX2JsaW5rX3RpbWVyID0gUVRp"
    "bWVyKCkKICAgICAgICBzZWxmLl9ibGlua190aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fYmxpbmspCiAgICAgICAgc2VsZi5f"
    "YmxpbmtfdGltZXIuc3RhcnQoODAwKQoKICAgICAgICBzZWxmLl9zdGF0ZV9zdHJpcF90aW1lciA9IFFUaW1lcigpCiAgICAgICAg"
    "aWYgQUlfU1RBVEVTX0VOQUJMRUQgYW5kIHNlbGYuX2Zvb3Rlcl9zdHJpcCBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5f"
    "c3RhdGVfc3RyaXBfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX2Zvb3Rlcl9zdHJpcC5yZWZyZXNoKQogICAgICAgICAgICBz"
    "ZWxmLl9zdGF0ZV9zdHJpcF90aW1lci5zdGFydCg2MDAwMCkKCiAgICAgICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGltZXIgPSBR"
    "VGltZXIoc2VsZikKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fb25fZ29v"
    "Z2xlX2luYm91bmRfdGltZXJfdGljaykKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lci5zdGFydCg2MDAwMCkKCiAg"
    "ICAgICAgc2VsZi5fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lciA9IFFUaW1lcihzZWxmKQogICAgICAgIHNlbGYuX2dvb2ds"
    "ZV9yZWNvcmRzX3JlZnJlc2hfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX29uX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGlt"
    "ZXJfdGljaykKICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyLnN0YXJ0KDYwMDAwKQoKICAgICAgICAj"
    "IOKUgOKUgCBTY2hlZHVsZXIgYW5kIHN0YXJ0dXAgZGVmZXJyZWQgdW50aWwgYWZ0ZXIgd2luZG93LnNob3coKSDilIDilIDilIAK"
    "ICAgICAgICAjIERvIE5PVCBjYWxsIF9zZXR1cF9zY2hlZHVsZXIoKSBvciBfc3RhcnR1cF9zZXF1ZW5jZSgpIGhlcmUuCiAgICAg"
    "ICAgIyBCb3RoIGFyZSB0cmlnZ2VyZWQgdmlhIFFUaW1lci5zaW5nbGVTaG90IGZyb20gbWFpbigpIGFmdGVyCiAgICAgICAgIyB3"
    "aW5kb3cuc2hvdygpIGFuZCBhcHAuZXhlYygpIGJlZ2lucyBydW5uaW5nLgoKICAgICMg4pSA4pSAIFVJIENPTlNUUlVDVElPTiDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgIGRlZiBfYnVpbGRfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICBjZW50cmFsID0gUVdpZGdl"
    "dCgpCiAgICAgICAgc2VsZi5zZXRDZW50cmFsV2lkZ2V0KGNlbnRyYWwpCiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KGNlbnRy"
    "YWwpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNiwgNiwgNiwgNikKICAgICAgICByb290LnNldFNwYWNpbmcoNCkK"
    "CiAgICAgICAgIyDilIDilIAgVGl0bGUgYmFyIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2J1aWxkX3RpdGxlX2Jhcigp"
    "KQoKICAgICAgICAjIOKUgOKUgCBCb2R5OiBKb3VybmFsIHwgQ2hhdCB8IFN5c3RlbXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgYm9k"
    "eSA9IFFIQm94TGF5b3V0KCkKICAgICAgICBib2R5LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBKb3VybmFsIHNpZGViYXIgKGxl"
    "ZnQpCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyID0gSm91cm5hbFNpZGViYXIoc2VsZi5fc2Vzc2lvbnMpCiAgICAgICAg"
    "c2VsZi5fam91cm5hbF9zaWRlYmFyLnNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5fbG9h"
    "ZF9qb3VybmFsX3Nlc3Npb24pCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNlc3Npb25fY2xlYXJfcmVxdWVzdGVkLmNv"
    "bm5lY3QoCiAgICAgICAgICAgIHNlbGYuX2NsZWFyX2pvdXJuYWxfc2Vzc2lvbikKICAgICAgICBib2R5LmFkZFdpZGdldChzZWxm"
    "Ll9qb3VybmFsX3NpZGViYXIpCgogICAgICAgICMgQ2hhdCBwYW5lbCAoY2VudGVyLCBleHBhbmRzKQogICAgICAgIGJvZHkuYWRk"
    "TGF5b3V0KHNlbGYuX2J1aWxkX2NoYXRfcGFuZWwoKSwgMSkKCiAgICAgICAgIyBTeXN0ZW1zIChyaWdodCkKICAgICAgICBib2R5"
    "LmFkZExheW91dChzZWxmLl9idWlsZF9zcGVsbGJvb2tfcGFuZWwoKSkKCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYm9keSwgMSkK"
    "CiAgICAgICAgIyDilIDilIAgRm9vdGVyIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGZvb3RlciA9IFFMYWJlbCgKICAgICAgICAgICAgZiLi"
    "nKYge0FQUF9OQU1FfSDigJQgdntBUFBfVkVSU0lPTn0g4pymIgogICAgICAgICkKICAgICAgICBmb290ZXIuc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgbGV0dGVyLXNwYWNpbmc6IDJweDsg"
    "IgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBmb290ZXIu"
    "c2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoZm9vdGVyKQoK"
    "ICAgIGRlZiBfYnVpbGRfdGl0bGVfYmFyKHNlbGYpIC0+IFFXaWRnZXQ6CiAgICAgICAgYmFyID0gUVdpZGdldCgpCiAgICAgICAg"
    "YmFyLnNldEZpeGVkSGVpZ2h0KDM2KQogICAgICAgIGJhci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6"
    "IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6"
    "IDJweDsiCiAgICAgICAgKQogICAgICAgIGxheW91dCA9IFFIQm94TGF5b3V0KGJhcikKICAgICAgICBsYXlvdXQuc2V0Q29udGVu"
    "dHNNYXJnaW5zKDEwLCAwLCAxMCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg2KQoKICAgICAgICB0aXRsZSA9IFFMYWJl"
    "bChmIuKcpiB7QVBQX05BTUV9IikKICAgICAgICB0aXRsZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19D"
    "UklNU09OfTsgZm9udC1zaXplOiAxM3B4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmImxldHRlci1zcGFjaW5n"
    "OiAycHg7IGJvcmRlcjogbm9uZTsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQoKICAgICAgICBy"
    "dW5lcyA9IFFMYWJlbChSVU5FUykKICAgICAgICBydW5lcy5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19H"
    "T0xEX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAgcnVuZXMuc2V0QWxpZ25t"
    "ZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVsKGYi4peJ"
    "IHtVSV9PRkZMSU5FX1NUQVRVU30iKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "IGYiY29sb3I6IHtDX0JMT09EfTsgZm9udC1zaXplOiAxMnB4OyBmb250LXdlaWdodDogYm9sZDsgYm9yZGVyOiBub25lOyIKICAg"
    "ICAgICApCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25SaWdodCkK"
    "CiAgICAgICAgIyBTdXNwZW5zaW9uIHBhbmVsCiAgICAgICAgc2VsZi5fdG9ycG9yX3BhbmVsID0gTm9uZQogICAgICAgIGlmIFNV"
    "U1BFTlNJT05fRU5BQkxFRDoKICAgICAgICAgICAgc2VsZi5fdG9ycG9yX3BhbmVsID0gVG9ycG9yUGFuZWwoKQogICAgICAgICAg"
    "ICBzZWxmLl90b3Jwb3JfcGFuZWwuc3RhdGVfY2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX3RvcnBvcl9zdGF0ZV9jaGFuZ2VkKQoK"
    "ICAgICAgICAjIElkbGUgdG9nZ2xlCiAgICAgICAgc2VsZi5faWRsZV9idG4gPSBRUHVzaEJ1dHRvbigiSURMRSBPRkYiKQogICAg"
    "ICAgIHNlbGYuX2lkbGVfYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldENoZWNrYWJsZShU"
    "cnVlKQogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldENoZWNrZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAg"
    "ICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgIGYiZm9u"
    "dC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIKICAgICAgICApCiAgICAgICAgc2VsZi5f"
    "aWRsZV9idG4udG9nZ2xlZC5jb25uZWN0KHNlbGYuX29uX2lkbGVfdG9nZ2xlZCkKCiAgICAgICAgIyBGUyAvIEJMIGJ1dHRvbnMK"
    "ICAgICAgICBzZWxmLl9mc19idG4gPSBRUHVzaEJ1dHRvbigiRlMiKQogICAgICAgIHNlbGYuX2JsX2J0biA9IFFQdXNoQnV0dG9u"
    "KCJCTCIpCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0biA9IFFQdXNoQnV0dG9uKCJFeHBvcnQiKQogICAgICAgIHNlbGYuX3NodXRk"
    "b3duX2J0biA9IFFQdXNoQnV0dG9uKCJTaHV0ZG93biIpCiAgICAgICAgZm9yIGJ0biBpbiAoc2VsZi5fZnNfYnRuLCBzZWxmLl9i"
    "bF9idG4sIHNlbGYuX2V4cG9ydF9idG4pOgogICAgICAgICAgICBidG4uc2V0Rml4ZWRTaXplKDMwLCAyMikKICAgICAgICAgICAg"
    "YnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19DUklNU09O"
    "X0RJTX07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyBmb250LXNpemU6IDlw"
    "eDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMDsiCiAgICAgICAgICAgICkKICAgICAg"
    "ICBzZWxmLl9leHBvcnRfYnRuLnNldEZpeGVkV2lkdGgoNDYpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldEZpeGVkSGVp"
    "Z2h0KDIyKQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5zZXRGaXhlZFdpZHRoKDY4KQogICAgICAgIHNlbGYuX3NodXRkb3du"
    "X2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19CTE9PRH07ICIK"
    "ICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CTE9PRH07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgIGYi"
    "Zm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICkKICAgICAgICBzZWxmLl9mc19idG4uc2V0VG9vbFRpcCgi"
    "RnVsbHNjcmVlbiAoRjExKSIpCiAgICAgICAgc2VsZi5fYmxfYnRuLnNldFRvb2xUaXAoIkJvcmRlcmxlc3MgKEYxMCkiKQogICAg"
    "ICAgIHNlbGYuX2V4cG9ydF9idG4uc2V0VG9vbFRpcCgiRXhwb3J0IGNoYXQgc2Vzc2lvbiB0byBUWFQgZmlsZSIpCiAgICAgICAg"
    "c2VsZi5fc2h1dGRvd25fYnRuLnNldFRvb2xUaXAoZiJHcmFjZWZ1bCBzaHV0ZG93biDigJQge0RFQ0tfTkFNRX0gc3BlYWtzIHRo"
    "ZWlyIGxhc3Qgd29yZHMiKQogICAgICAgIHNlbGYuX2ZzX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2Z1bGxzY3Jl"
    "ZW4pCiAgICAgICAgc2VsZi5fYmxfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGVfYm9yZGVybGVzcykKICAgICAgICBz"
    "ZWxmLl9leHBvcnRfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9leHBvcnRfY2hhdCkKICAgICAgICBzZWxmLl9zaHV0ZG93bl9i"
    "dG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2luaXRpYXRlX3NodXRkb3duX2RpYWxvZykKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdl"
    "dCh0aXRsZSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHJ1bmVzLCAxKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5z"
    "dGF0dXNfbGFiZWwpCiAgICAgICAgbGF5b3V0LmFkZFNwYWNpbmcoOCkKICAgICAgICBpZiBzZWxmLl90b3Jwb3JfcGFuZWwgaXMg"
    "bm90IE5vbmU6CiAgICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fdG9ycG9yX3BhbmVsKQogICAgICAgIGxheW91dC5h"
    "ZGRTcGFjaW5nKDQpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9pZGxlX2J0bikKICAgICAgICBsYXlvdXQuYWRkU3Bh"
    "Y2luZyg0KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZXhwb3J0X2J0bikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0"
    "KHNlbGYuX3NodXRkb3duX2J0bikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2ZzX2J0bikKICAgICAgICBsYXlvdXQu"
    "YWRkV2lkZ2V0KHNlbGYuX2JsX2J0bikKCiAgICAgICAgcmV0dXJuIGJhcgoKICAgIGRlZiBfYnVpbGRfY2hhdF9wYW5lbChzZWxm"
    "KSAtPiBRVkJveExheW91dDoKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dCgpCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmco"
    "NCkKCiAgICAgICAgIyBNYWluIHRhYiB3aWRnZXQg4oCUIHBlcnNvbmEgY2hhdCB0YWIgfCBTZWxmCiAgICAgICAgc2VsZi5fbWFp"
    "bl90YWJzID0gUVRhYldpZGdldCgpCiAgICAgICAgc2VsZi5fbWFpbl90YWJzLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "UVRhYldpZGdldDo6cGFuZSB7eyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJiYWNr"
    "Z3JvdW5kOiB7Q19NT05JVE9SfTsgfX0iCiAgICAgICAgICAgIGYiUVRhYkJhcjo6dGFiIHt7IGJhY2tncm91bmQ6IHtDX0JHM307"
    "IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJwYWRkaW5nOiA0cHggMTJweDsgYm9yZGVyOiAxcHggc29saWQg"
    "e0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBw"
    "eDsgfX0iCiAgICAgICAgICAgIGYiUVRhYkJhcjo6dGFiOnNlbGVjdGVkIHt7IGJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7"
    "Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlci1ib3R0b206IDJweCBzb2xpZCB7Q19DUklNU09OfTsgfX0iCiAgICAgICAg"
    "KQoKICAgICAgICAjIOKUgOKUgCBUYWIgMDogUGVyc29uYSBjaGF0IHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICAgICBzZWFuY2Vfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgc2VhbmNlX2xheW91dCA9IFFWQm94TGF5b3V0KHNlYW5j"
    "ZV93aWRnZXQpCiAgICAgICAgc2VhbmNlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWFu"
    "Y2VfbGF5b3V0LnNldFNwYWNpbmcoMCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNl"
    "bGYuX2NoYXRfZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJi"
    "b3JkZXI6IG5vbmU7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEy"
    "cHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHNlYW5jZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2NoYXRfZGlz"
    "cGxheSkKICAgICAgICBzZWxmLl9tYWluX3RhYnMuYWRkVGFiKHNlYW5jZV93aWRnZXQsIGYi4p2nIHtVSV9DSEFUX1dJTkRPV30i"
    "KQoKICAgICAgICAjIOKUgOKUgCBUYWIgMTogU2VsZiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zZWxmX3RhYl93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAg"
    "ICBzZWxmX2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX3NlbGZfdGFiX3dpZGdldCkKICAgICAgICBzZWxmX2xheW91dC5zZXRD"
    "b250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBzZWxmX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5f"
    "c2VsZl9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAg"
    "ICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9S"
    "fTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiBub25lOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1p"
    "bHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMnB4OyBwYWRkaW5nOiA4cHg7IgogICAgICAgICkKICAgICAgICBz"
    "ZWxmX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fc2VsZl9kaXNwbGF5LCAxKQogICAgICAgIHNlbGYuX21haW5fdGFicy5hZGRUYWIo"
    "c2VsZi5fc2VsZl90YWJfd2lkZ2V0LCAi4peJIFNFTEYiKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX21haW5fdGFi"
    "cywgMSkKCiAgICAgICAgIyDilIDilIAgQm90dG9tIHN0YXR1cy9yZXNvdXJjZSBibG9jayByb3cg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgIyBN"
    "YW5kYXRvcnkgcGVybWFuZW50IHN0cnVjdHVyZSBhY3Jvc3MgYWxsIHBlcnNvbmFzOgogICAgICAgICMgTUlSUk9SIHwgW0xPV0VS"
    "LU1JRERMRSBQRVJNQU5FTlQgRk9PVFBSSU5UXQogICAgICAgIGJsb2NrX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBibG9j"
    "a19yb3cuc2V0U3BhY2luZygyKQoKICAgICAgICAjIE1pcnJvciAobmV2ZXIgY29sbGFwc2VzKQogICAgICAgIG1pcnJvcl93cmFw"
    "ID0gUVdpZGdldCgpCiAgICAgICAgbXdfbGF5b3V0ID0gUVZCb3hMYXlvdXQobWlycm9yX3dyYXApCiAgICAgICAgbXdfbGF5b3V0"
    "LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG13X2xheW91dC5zZXRTcGFjaW5nKDIpCiAgICAgICAgbXdf"
    "bGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoZiLinacge1VJX01JUlJPUl9MQUJFTH0iKSkKICAgICAgICBzZWxmLl9taXJy"
    "b3IgPSBNaXJyb3JXaWRnZXQoKQogICAgICAgIHNlbGYuX21pcnJvci5zZXRGaXhlZFNpemUoMTYwLCAxNjApCiAgICAgICAgbXdf"
    "bGF5b3V0LmFkZFdpZGdldChzZWxmLl9taXJyb3IpCiAgICAgICAgYmxvY2tfcm93LmFkZFdpZGdldChtaXJyb3Jfd3JhcCwgMCkK"
    "CiAgICAgICAgIyBNaWRkbGUgbG93ZXIgYmxvY2sga2VlcHMgYSBwZXJtYW5lbnQgZm9vdHByaW50OgogICAgICAgICMgbGVmdCA9"
    "IGNvbXBhY3Qgc3RhY2sgYXJlYSwgcmlnaHQgPSBmaXhlZCBleHBhbmRlZC1yb3cgc2xvdHMuCiAgICAgICAgbWlkZGxlX3dyYXAg"
    "PSBRV2lkZ2V0KCkKICAgICAgICBtaWRkbGVfbGF5b3V0ID0gUUhCb3hMYXlvdXQobWlkZGxlX3dyYXApCiAgICAgICAgbWlkZGxl"
    "X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBtaWRkbGVfbGF5b3V0LnNldFNwYWNpbmcoMikK"
    "CiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfd3JhcCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX3dyYXAu"
    "c2V0TWluaW11bVdpZHRoKDEzMCkKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja193cmFwLnNldE1heGltdW1XaWR0aCgxMzApCiAg"
    "ICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fbG93ZXJfc3RhY2tfd3JhcCkKICAgICAg"
    "ICBzZWxmLl9sb3dlcl9zdGFja19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VsZi5fbG93"
    "ZXJfc3RhY2tfbGF5b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja193cmFwLnNldFZpc2libGUoRmFs"
    "c2UpCiAgICAgICAgbWlkZGxlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fbG93ZXJfc3RhY2tfd3JhcCwgMCkKCiAgICAgICAgc2Vs"
    "Zi5fbG93ZXJfZXhwYW5kZWRfcm93ID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93X2xheW91dCA9"
    "IFFHcmlkTGF5b3V0KHNlbGYuX2xvd2VyX2V4cGFuZGVkX3JvdykKICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5"
    "b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Jvd19sYXlvdXQu"
    "c2V0SG9yaXpvbnRhbFNwYWNpbmcoMikKICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LnNldFZlcnRpY2Fs"
    "U3BhY2luZygyKQogICAgICAgIG1pZGRsZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2xvd2VyX2V4cGFuZGVkX3JvdywgMSkKCiAg"
    "ICAgICAgIyBFbW90aW9uIGJsb2NrIChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9lbW90aW9uX2Jsb2NrID0gRW1vdGlvbkJs"
    "b2NrKCkKICAgICAgICBzZWxmLl9lbW90aW9uX2Jsb2NrX3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKd"
    "pyB7VUlfRU1PVElPTlNfTEFCRUx9Iiwgc2VsZi5fZW1vdGlvbl9ibG9jaywKICAgICAgICAgICAgZXhwYW5kZWQ9VHJ1ZSwgbWlu"
    "X3dpZHRoPTEzMCwgcmVzZXJ2ZV93aWR0aD1UcnVlCiAgICAgICAgKQoKICAgICAgICAjIExlZnQgcmVzb3VyY2Ugb3JiIChjb2xs"
    "YXBzaWJsZSkKICAgICAgICBzZWxmLl9sZWZ0X29yYiA9IFNwaGVyZVdpZGdldCgKICAgICAgICAgICAgVUlfTEVGVF9PUkJfTEFC"
    "RUwsIENfQ1JJTVNPTiwgQ19DUklNU09OX0RJTQogICAgICAgICkKICAgICAgICBzZWxmLl9sZWZ0X29yYl93cmFwID0gQ29sbGFw"
    "c2libGVCbG9jaygKICAgICAgICAgICAgZiLinacge1VJX0xFRlRfT1JCX1RJVExFfSIsIHNlbGYuX2xlZnRfb3JiLAogICAgICAg"
    "ICAgICBtaW5fd2lkdGg9OTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAgICAgICkKCiAgICAgICAgIyBDZW50ZXIgY3ljbGUgd2lk"
    "Z2V0IChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9jeWNsZV93aWRnZXQgPSBDeWNsZVdpZGdldCgpCiAgICAgICAgc2VsZi5f"
    "Y3ljbGVfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2soCiAgICAgICAgICAgIGYi4p2nIHtVSV9DWUNMRV9USVRMRX0iLCBzZWxmLl9j"
    "eWNsZV93aWRnZXQsCiAgICAgICAgICAgIG1pbl93aWR0aD05MCwgcmVzZXJ2ZV93aWR0aD1UcnVlCiAgICAgICAgKQoKICAgICAg"
    "ICAjIFJpZ2h0IHJlc291cmNlIG9yYiAoY29sbGFwc2libGUpCiAgICAgICAgc2VsZi5fcmlnaHRfb3JiID0gU3BoZXJlV2lkZ2V0"
    "KAogICAgICAgICAgICBVSV9SSUdIVF9PUkJfTEFCRUwsIENfUFVSUExFLCBDX1BVUlBMRV9ESU0KICAgICAgICApCiAgICAgICAg"
    "c2VsZi5fcmlnaHRfb3JiX3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfUklHSFRfT1JCX1RJ"
    "VExFfSIsIHNlbGYuX3JpZ2h0X29yYiwKICAgICAgICAgICAgbWluX3dpZHRoPTkwLCByZXNlcnZlX3dpZHRoPVRydWUKICAgICAg"
    "ICApCgogICAgICAgICMgRXNzZW5jZSAoMiBnYXVnZXMsIGNvbGxhcHNpYmxlKQogICAgICAgIGVzc2VuY2Vfd2lkZ2V0ID0gUVdp"
    "ZGdldCgpCiAgICAgICAgZXNzZW5jZV9sYXlvdXQgPSBRVkJveExheW91dChlc3NlbmNlX3dpZGdldCkKICAgICAgICBlc3NlbmNl"
    "X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBlc3NlbmNlX2xheW91dC5zZXRTcGFjaW5nKDQp"
    "CiAgICAgICAgc2VsZi5fZXNzZW5jZV9wcmltYXJ5X2dhdWdlICAgPSBHYXVnZVdpZGdldChVSV9FU1NFTkNFX1BSSU1BUlksICAg"
    "IiUiLCAxMDAuMCwgQ19DUklNU09OKQogICAgICAgIHNlbGYuX2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdlID0gR2F1Z2VXaWRnZXQo"
    "VUlfRVNTRU5DRV9TRUNPTkRBUlksICIlIiwgMTAwLjAsIENfR1JFRU4pCiAgICAgICAgZXNzZW5jZV9sYXlvdXQuYWRkV2lkZ2V0"
    "KHNlbGYuX2Vzc2VuY2VfcHJpbWFyeV9nYXVnZSkKICAgICAgICBlc3NlbmNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fZXNzZW5j"
    "ZV9zZWNvbmRhcnlfZ2F1Z2UpCiAgICAgICAgc2VsZi5fZXNzZW5jZV93cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAg"
    "ICAgZiLinacge1VJX0VTU0VOQ0VfVElUTEV9IiwgZXNzZW5jZV93aWRnZXQsCiAgICAgICAgICAgIG1pbl93aWR0aD0xMTAsIHJl"
    "c2VydmVfd2lkdGg9VHJ1ZQogICAgICAgICkKCiAgICAgICAgIyBFeHBhbmRlZCByb3cgc2xvdHMgbXVzdCBzdGF5IGluIGNhbm9u"
    "aWNhbCB2aXN1YWwgb3JkZXIuCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfc2xvdF9vcmRlciA9IFsKICAgICAgICAgICAg"
    "ImVtb3Rpb25zIiwgInByaW1hcnkiLCAiY3ljbGUiLCAic2Vjb25kYXJ5IiwgImVzc2VuY2UiCiAgICAgICAgXQogICAgICAgIHNl"
    "bGYuX2xvd2VyX2NvbXBhY3Rfc3RhY2tfb3JkZXIgPSBbCiAgICAgICAgICAgICJjeWNsZSIsICJwcmltYXJ5IiwgInNlY29uZGFy"
    "eSIsICJlc3NlbmNlIiwgImVtb3Rpb25zIgogICAgICAgIF0KICAgICAgICBzZWxmLl9sb3dlcl9tb2R1bGVfd3JhcHMgPSB7CiAg"
    "ICAgICAgICAgICJlbW90aW9ucyI6IHNlbGYuX2Vtb3Rpb25fYmxvY2tfd3JhcCwKICAgICAgICAgICAgInByaW1hcnkiOiBzZWxm"
    "Ll9sZWZ0X29yYl93cmFwLAogICAgICAgICAgICAiY3ljbGUiOiBzZWxmLl9jeWNsZV93cmFwLAogICAgICAgICAgICAic2Vjb25k"
    "YXJ5Ijogc2VsZi5fcmlnaHRfb3JiX3dyYXAsCiAgICAgICAgICAgICJlc3NlbmNlIjogc2VsZi5fZXNzZW5jZV93cmFwLAogICAg"
    "ICAgIH0KCiAgICAgICAgc2VsZi5fbG93ZXJfcm93X3Nsb3RzID0ge30KICAgICAgICBmb3IgY29sLCBrZXkgaW4gZW51bWVyYXRl"
    "KHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Nsb3Rfb3JkZXIpOgogICAgICAgICAgICBzbG90ID0gUVdpZGdldCgpCiAgICAgICAgICAg"
    "IHNsb3RfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2xvdCkKICAgICAgICAgICAgc2xvdF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5z"
    "KDAsIDAsIDAsIDApCiAgICAgICAgICAgIHNsb3RfbGF5b3V0LnNldFNwYWNpbmcoMCkKICAgICAgICAgICAgc2VsZi5fbG93ZXJf"
    "ZXhwYW5kZWRfcm93X2xheW91dC5hZGRXaWRnZXQoc2xvdCwgMCwgY29sKQogICAgICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRl"
    "ZF9yb3dfbGF5b3V0LnNldENvbHVtblN0cmV0Y2goY29sLCAxKQogICAgICAgICAgICBzZWxmLl9sb3dlcl9yb3dfc2xvdHNba2V5"
    "XSA9IHNsb3RfbGF5b3V0CgogICAgICAgIGZvciB3cmFwIGluIHNlbGYuX2xvd2VyX21vZHVsZV93cmFwcy52YWx1ZXMoKToKICAg"
    "ICAgICAgICAgd3JhcC50b2dnbGVkLmNvbm5lY3Qoc2VsZi5fcmVmcmVzaF9sb3dlcl9taWRkbGVfbGF5b3V0KQoKICAgICAgICBz"
    "ZWxmLl9yZWZyZXNoX2xvd2VyX21pZGRsZV9sYXlvdXQoKQoKICAgICAgICBibG9ja19yb3cuYWRkV2lkZ2V0KG1pZGRsZV93cmFw"
    "LCAxKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoYmxvY2tfcm93KQoKICAgICAgICAjIEZvb3RlciBzdGF0ZSBzdHJpcCAoYmVs"
    "b3cgYmxvY2sgcm93IOKAlCBwZXJtYW5lbnQgVUkgc3RydWN0dXJlKQogICAgICAgIHNlbGYuX2Zvb3Rlcl9zdHJpcCA9IEZvb3Rl"
    "clN0cmlwV2lkZ2V0KCkKICAgICAgICBzZWxmLl9mb290ZXJfc3RyaXAuc2V0X2xhYmVsKFVJX0ZPT1RFUl9TVFJJUF9MQUJFTCkK"
    "ICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2Zvb3Rlcl9zdHJpcCkKCiAgICAgICAgIyDilIDilIAgSW5wdXQgcm93IOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgICAgIGlucHV0X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBwcm9tcHRfc3ltID0gUUxhYmVsKCLinKYiKQogICAgICAg"
    "IHByb21wdF9zeW0uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTZw"
    "eDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHByb21wdF9zeW0uc2V0Rml4ZWRX"
    "aWR0aCgyMCkKCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxk"
    "LnNldFBsYWNlaG9sZGVyVGV4dChVSV9JTlBVVF9QTEFDRUhPTERFUikKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5yZXR1cm5Q"
    "cmVzc2VkLmNvbm5lY3Qoc2VsZi5fc2VuZF9tZXNzYWdlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFs"
    "c2UpCgogICAgICAgIHNlbGYuX3NlbmRfYnRuID0gUVB1c2hCdXR0b24oVUlfU0VORF9CVVRUT04pCiAgICAgICAgc2VsZi5fc2Vu"
    "ZF9idG4uc2V0Rml4ZWRXaWR0aCgxMTApCiAgICAgICAgc2VsZi5fc2VuZF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3NlbmRf"
    "bWVzc2FnZSkKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKEZhbHNlKQoKICAgICAgICBpbnB1dF9yb3cuYWRkV2lk"
    "Z2V0KHByb21wdF9zeW0pCiAgICAgICAgaW5wdXRfcm93LmFkZFdpZGdldChzZWxmLl9pbnB1dF9maWVsZCkKICAgICAgICBpbnB1"
    "dF9yb3cuYWRkV2lkZ2V0KHNlbGYuX3NlbmRfYnRuKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoaW5wdXRfcm93KQoKICAgICAg"
    "ICByZXR1cm4gbGF5b3V0CgogICAgZGVmIF9jbGVhcl9sYXlvdXRfd2lkZ2V0cyhzZWxmLCBsYXlvdXQ6IFFWQm94TGF5b3V0KSAt"
    "PiBOb25lOgogICAgICAgIHdoaWxlIGxheW91dC5jb3VudCgpOgogICAgICAgICAgICBpdGVtID0gbGF5b3V0LnRha2VBdCgwKQog"
    "ICAgICAgICAgICB3aWRnZXQgPSBpdGVtLndpZGdldCgpCiAgICAgICAgICAgIGlmIHdpZGdldCBpcyBub3QgTm9uZToKICAgICAg"
    "ICAgICAgICAgIHdpZGdldC5zZXRQYXJlbnQoTm9uZSkKCiAgICBkZWYgX3JlZnJlc2hfbG93ZXJfbWlkZGxlX2xheW91dChzZWxm"
    "LCAqX2FyZ3MpIC0+IE5vbmU6CiAgICAgICAgY29sbGFwc2VkX2NvdW50ID0gMAoKICAgICAgICAjIFJlYnVpbGQgZXhwYW5kZWQg"
    "cm93IHNsb3RzIGluIGZpeGVkIGV4cGFuZGVkIG9yZGVyLgogICAgICAgIGZvciBrZXkgaW4gc2VsZi5fbG93ZXJfZXhwYW5kZWRf"
    "c2xvdF9vcmRlcjoKICAgICAgICAgICAgc2xvdF9sYXlvdXQgPSBzZWxmLl9sb3dlcl9yb3dfc2xvdHNba2V5XQogICAgICAgICAg"
    "ICBzZWxmLl9jbGVhcl9sYXlvdXRfd2lkZ2V0cyhzbG90X2xheW91dCkKICAgICAgICAgICAgd3JhcCA9IHNlbGYuX2xvd2VyX21v"
    "ZHVsZV93cmFwc1trZXldCiAgICAgICAgICAgIGlmIHdyYXAuaXNfZXhwYW5kZWQoKToKICAgICAgICAgICAgICAgIHNsb3RfbGF5"
    "b3V0LmFkZFdpZGdldCh3cmFwKQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgY29sbGFwc2VkX2NvdW50ICs9IDEK"
    "ICAgICAgICAgICAgICAgIHNsb3RfbGF5b3V0LmFkZFN0cmV0Y2goMSkKCiAgICAgICAgIyBSZWJ1aWxkIGNvbXBhY3Qgc3RhY2sg"
    "aW4gY2Fub25pY2FsIGNvbXBhY3Qgb3JkZXIuCiAgICAgICAgc2VsZi5fY2xlYXJfbGF5b3V0X3dpZGdldHMoc2VsZi5fbG93ZXJf"
    "c3RhY2tfbGF5b3V0KQogICAgICAgIGZvciBrZXkgaW4gc2VsZi5fbG93ZXJfY29tcGFjdF9zdGFja19vcmRlcjoKICAgICAgICAg"
    "ICAgd3JhcCA9IHNlbGYuX2xvd2VyX21vZHVsZV93cmFwc1trZXldCiAgICAgICAgICAgIGlmIG5vdCB3cmFwLmlzX2V4cGFuZGVk"
    "KCk6CiAgICAgICAgICAgICAgICBzZWxmLl9sb3dlcl9zdGFja19sYXlvdXQuYWRkV2lkZ2V0KHdyYXApCgogICAgICAgIHNlbGYu"
    "X2xvd2VyX3N0YWNrX2xheW91dC5hZGRTdHJldGNoKDEpCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfd3JhcC5zZXRWaXNpYmxl"
    "KGNvbGxhcHNlZF9jb3VudCA+IDApCgogICAgZGVmIF9idWlsZF9zcGVsbGJvb2tfcGFuZWwoc2VsZikgLT4gUVZCb3hMYXlvdXQ6"
    "CiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwg"
    "MCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacg"
    "U1lTVEVNUyIpKQoKICAgICAgICAjIFRhYiB3aWRnZXQKICAgICAgICBzZWxmLl9zcGVsbF90YWJzID0gUVRhYldpZGdldCgpCiAg"
    "ICAgICAgc2VsZi5fc3BlbGxfdGFicy5zZXRNaW5pbXVtV2lkdGgoMjgwKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuc2V0U2l6"
    "ZVBvbGljeSgKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5LkV4cGFuZGluZywKICAgICAgICAgICAgUVNpemVQb2xpY3ku"
    "UG9saWN5LkV4cGFuZGluZwogICAgICAgICkKCiAgICAgICAgIyBCdWlsZCBEaWFnbm9zdGljc1RhYiBlYXJseSBzbyBzdGFydHVw"
    "IGxvZ3MgYXJlIHNhZmUgZXZlbiBiZWZvcmUKICAgICAgICAjIHRoZSBEaWFnbm9zdGljcyB0YWIgaXMgYXR0YWNoZWQgdG8gdGhl"
    "IHdpZGdldC4KICAgICAgICBzZWxmLl9kaWFnX3RhYiA9IERpYWdub3N0aWNzVGFiKCkKCiAgICAgICAgIyDilIDilIAgSW5zdHJ1"
    "bWVudHMgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAg"
    "IHNlbGYuX2h3X3BhbmVsID0gSGFyZHdhcmVQYW5lbCgpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5faHdf"
    "cGFuZWwsICJJbnN0cnVtZW50cyIpCgogICAgICAgICMg4pSA4pSAIFJlY29yZHMgdGFiIChyZWFsKSDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYiA9IFJlY29yZHNUYWIoKQogICAg"
    "ICAgIHNlbGYuX3JlY29yZHNfdGFiX2luZGV4ID0gc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fcmVjb3Jkc190YWIsICJS"
    "ZWNvcmRzIikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltTUEVMTEJPT0tdIHJlYWwgUmVjb3Jkc1RhYiBhdHRhY2hlZC4i"
    "LCAiSU5GTyIpCgogICAgICAgICMg4pSA4pSAIFRhc2tzIHRhYiAocmVhbCkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fdGFza3NfdGFiID0gVGFza3NUYWIoCiAgICAgICAgICAgIHRhc2tz"
    "X3Byb3ZpZGVyPXNlbGYuX2ZpbHRlcmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeSwKICAgICAgICAgICAgb25fYWRkX2VkaXRvcl9vcGVu"
    "PXNlbGYuX29wZW5fdGFza19lZGl0b3Jfd29ya3NwYWNlLAogICAgICAgICAgICBvbl9jb21wbGV0ZV9zZWxlY3RlZD1zZWxmLl9j"
    "b21wbGV0ZV9zZWxlY3RlZF90YXNrLAogICAgICAgICAgICBvbl9jYW5jZWxfc2VsZWN0ZWQ9c2VsZi5fY2FuY2VsX3NlbGVjdGVk"
    "X3Rhc2ssCiAgICAgICAgICAgIG9uX3RvZ2dsZV9jb21wbGV0ZWQ9c2VsZi5fdG9nZ2xlX3Nob3dfY29tcGxldGVkX3Rhc2tzLAog"
    "ICAgICAgICAgICBvbl9wdXJnZV9jb21wbGV0ZWQ9c2VsZi5fcHVyZ2VfY29tcGxldGVkX3Rhc2tzLAogICAgICAgICAgICBvbl9m"
    "aWx0ZXJfY2hhbmdlZD1zZWxmLl9vbl90YXNrX2ZpbHRlcl9jaGFuZ2VkLAogICAgICAgICAgICBvbl9lZGl0b3Jfc2F2ZT1zZWxm"
    "Ll9zYXZlX3Rhc2tfZWRpdG9yX2dvb2dsZV9maXJzdCwKICAgICAgICAgICAgb25fZWRpdG9yX2NhbmNlbD1zZWxmLl9jYW5jZWxf"
    "dGFza19lZGl0b3Jfd29ya3NwYWNlLAogICAgICAgICAgICBkaWFnbm9zdGljc19sb2dnZXI9c2VsZi5fZGlhZ190YWIubG9nLAog"
    "ICAgICAgICkKICAgICAgICBzZWxmLl90YXNrc190YWIuc2V0X3Nob3dfY29tcGxldGVkKHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0"
    "ZWQpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiX2luZGV4ID0gc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fdGFza3NfdGFi"
    "LCAiVGFza3MiKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW1NQRUxMQk9PS10gcmVhbCBUYXNrc1RhYiBhdHRhY2hlZC4i"
    "LCAiSU5GTyIpCgogICAgICAgICMg4pSA4pSAIFNMIFNjYW5zIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zbF9zY2FucyA9IFNMU2NhbnNUYWIoY2ZnX3Bh"
    "dGgoInNsIikpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fc2xfc2NhbnMsICJTTCBTY2FucyIpCgogICAg"
    "ICAgICMg4pSA4pSAIFNMIENvbW1hbmRzIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKICAgICAgICBzZWxmLl9zbF9jb21tYW5kcyA9IFNMQ29tbWFuZHNUYWIoKQogICAgICAgIHNlbGYuX3NwZWxs"
    "X3RhYnMuYWRkVGFiKHNlbGYuX3NsX2NvbW1hbmRzLCAiU0wgQ29tbWFuZHMiKQoKICAgICAgICAjIOKUgOKUgCBKb2IgVHJhY2tl"
    "ciB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2Vs"
    "Zi5fam9iX3RyYWNrZXIgPSBKb2JUcmFja2VyVGFiKCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9qb2Jf"
    "dHJhY2tlciwgIkpvYiBUcmFja2VyIikKCiAgICAgICAgIyDilIDilIAgTGVzc29ucyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fbGVzc29uc190YWIg"
    "PSBMZXNzb25zVGFiKHNlbGYuX2xlc3NvbnMpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fbGVzc29uc190"
    "YWIsICJMZXNzb25zIikKCiAgICAgICAgIyBTZWxmIHRhYiBpcyBub3cgaW4gdGhlIG1haW4gYXJlYSBhbG9uZ3NpZGUgdGhlIHBl"
    "cnNvbmEgY2hhdCB0YWIKICAgICAgICAjIEtlZXAgYSBTZWxmVGFiIGluc3RhbmNlIGZvciBpZGxlIGNvbnRlbnQgZ2VuZXJhdGlv"
    "bgogICAgICAgIHNlbGYuX3NlbGZfdGFiID0gU2VsZlRhYigpCgogICAgICAgICMg4pSA4pSAIE1vZHVsZSBUcmFja2VyIHRhYiDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9tb2R1bGVfdHJhY2tl"
    "ciA9IE1vZHVsZVRyYWNrZXJUYWIoKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX21vZHVsZV90cmFja2Vy"
    "LCAiTW9kdWxlcyIpCgogICAgICAgICMg4pSA4pSAIERpYWdub3N0aWNzIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9kaWFnX3Rh"
    "YiwgIkRpYWdub3N0aWNzIikKCiAgICAgICAgcmlnaHRfd29ya3NwYWNlID0gUVdpZGdldCgpCiAgICAgICAgcmlnaHRfd29ya3Nw"
    "YWNlX2xheW91dCA9IFFWQm94TGF5b3V0KHJpZ2h0X3dvcmtzcGFjZSkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LnNl"
    "dENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuc2V0U3BhY2luZyg0KQoK"
    "ICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zcGVsbF90YWJzLCAxKQoKICAgICAgICBjYWxl"
    "bmRhcl9sYWJlbCA9IFFMYWJlbCgi4p2nIENBTEVOREFSIikKICAgICAgICBjYWxlbmRhcl9sYWJlbC5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiAxMHB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyBmb250LWZh"
    "bWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5hZGRXaWRn"
    "ZXQoY2FsZW5kYXJfbGFiZWwpCgogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0ID0gTWluaUNhbGVuZGFyV2lkZ2V0KCkKICAg"
    "ICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07"
    "IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0"
    "LnNldFNpemVQb2xpY3koCiAgICAgICAgICAgIFFTaXplUG9saWN5LlBvbGljeS5FeHBhbmRpbmcsCiAgICAgICAgICAgIFFTaXpl"
    "UG9saWN5LlBvbGljeS5NYXhpbXVtCiAgICAgICAgKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0LnNldE1heGltdW1IZWln"
    "aHQoMjYwKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0LmNhbGVuZGFyLmNsaWNrZWQuY29ubmVjdChzZWxmLl9pbnNlcnRf"
    "Y2FsZW5kYXJfZGF0ZSkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLmNhbGVuZGFyX3dpZGdl"
    "dCwgMCkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFN0cmV0Y2goMCkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdl"
    "dChyaWdodF93b3Jrc3BhY2UsIDEpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAiW0xBWU9VVF0gcmln"
    "aHQtc2lkZSBjYWxlbmRhciByZXN0b3JlZCAocGVyc2lzdGVudCBsb3dlci1yaWdodCBzZWN0aW9uKS4iLAogICAgICAgICAgICAi"
    "SU5GTyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAiW0xBWU9VVF0gcGVyc2lzdGVu"
    "dCBtaW5pIGNhbGVuZGFyIHJlc3RvcmVkL2NvbmZpcm1lZCAoYWx3YXlzIHZpc2libGUgbG93ZXItcmlnaHQpLiIsCiAgICAgICAg"
    "ICAgICJJTkZPIgogICAgICAgICkKICAgICAgICByZXR1cm4gbGF5b3V0CgogICAgIyDilIDilIAgU1RBUlRVUCBTRVFVRU5DRSDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgIGRlZiBfc3RhcnR1cF9zZXF1ZW5jZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2FwcGVu"
    "ZF9jaGF0KCJTWVNURU0iLCBmIuKcpiB7QVBQX05BTUV9IEFXQUtFTklORy4uLiIpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQo"
    "IlNZU1RFTSIsIGYi4pymIHtSVU5FU30g4pymIikKCiAgICAgICAgIyBMb2FkIGJvb3RzdHJhcCBsb2cKICAgICAgICBib290X2xv"
    "ZyA9IFNDUklQVF9ESVIgLyAibG9ncyIgLyAiYm9vdHN0cmFwX2xvZy50eHQiCiAgICAgICAgaWYgYm9vdF9sb2cuZXhpc3RzKCk6"
    "CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIG1zZ3MgPSBib290X2xvZy5yZWFkX3RleHQoZW5jb2Rpbmc9InV0Zi04"
    "Iikuc3BsaXRsaW5lcygpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2dfbWFueShtc2dzKQogICAgICAgICAgICAg"
    "ICAgYm9vdF9sb2cudW5saW5rKCkgICMgY29uc3VtZWQKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAg"
    "ICAgIHBhc3MKCiAgICAgICAgIyBIYXJkd2FyZSBkZXRlY3Rpb24gbWVzc2FnZXMKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2df"
    "bWFueShzZWxmLl9od19wYW5lbC5nZXRfZGlhZ25vc3RpY3MoKSkKCiAgICAgICAgIyBEZXAgY2hlY2sKICAgICAgICBkZXBfbXNn"
    "cywgY3JpdGljYWwgPSBEZXBlbmRlbmN5Q2hlY2tlci5jaGVjaygpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nX21hbnkoZGVw"
    "X21zZ3MpCgogICAgICAgICMgTG9hZCBwYXN0IHN0YXRlCiAgICAgICAgbGFzdF9zdGF0ZSA9IHNlbGYuX3N0YXRlLmdldCgidmFt"
    "cGlyZV9zdGF0ZV9hdF9zaHV0ZG93biIsIiIpCiAgICAgICAgaWYgbGFzdF9zdGF0ZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKAogICAgICAgICAgICAgICAgZiJbU1RBUlRVUF0gTGFzdCBzaHV0ZG93biBzdGF0ZToge2xhc3Rfc3RhdGV9IiwgIklO"
    "Rk8iCiAgICAgICAgICAgICkKCiAgICAgICAgIyBCZWdpbiBtb2RlbCBsb2FkCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZ"
    "U1RFTSIsCiAgICAgICAgICAgIFVJX0FXQUtFTklOR19MSU5FKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAog"
    "ICAgICAgICAgICBmIlN1bW1vbmluZyB7REVDS19OQU1FfSdzIHByZXNlbmNlLi4uIikKICAgICAgICBzZWxmLl9zZXRfc3RhdHVz"
    "KCJMT0FESU5HIikKCiAgICAgICAgc2VsZi5fbG9hZGVyID0gTW9kZWxMb2FkZXJXb3JrZXIoc2VsZi5fYWRhcHRvcikKICAgICAg"
    "ICBzZWxmLl9sb2FkZXIubWVzc2FnZS5jb25uZWN0KAogICAgICAgICAgICBsYW1iZGEgbTogc2VsZi5fYXBwZW5kX2NoYXQoIlNZ"
    "U1RFTSIsIG0pKQogICAgICAgIHNlbGYuX2xvYWRlci5lcnJvci5jb25uZWN0KAogICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5f"
    "YXBwZW5kX2NoYXQoIkVSUk9SIiwgZSkpCiAgICAgICAgc2VsZi5fbG9hZGVyLmxvYWRfY29tcGxldGUuY29ubmVjdChzZWxmLl9v"
    "bl9sb2FkX2NvbXBsZXRlKQogICAgICAgIHNlbGYuX2xvYWRlci5maW5pc2hlZC5jb25uZWN0KHNlbGYuX2xvYWRlci5kZWxldGVM"
    "YXRlcikKICAgICAgICBzZWxmLl9hY3RpdmVfdGhyZWFkcy5hcHBlbmQoc2VsZi5fbG9hZGVyKQogICAgICAgIHNlbGYuX2xvYWRl"
    "ci5zdGFydCgpCgogICAgZGVmIF9vbl9sb2FkX2NvbXBsZXRlKHNlbGYsIHN1Y2Nlc3M6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAg"
    "aWYgc3VjY2VzczoKICAgICAgICAgICAgc2VsZi5fbW9kZWxfbG9hZGVkID0gVHJ1ZQogICAgICAgICAgICBzZWxmLl9zZXRfc3Rh"
    "dHVzKCJJRExFIikKICAgICAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9p"
    "bnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEZvY3VzKCkKCiAgICAg"
    "ICAgICAgICMgTWVhc3VyZSBWUkFNIGJhc2VsaW5lIGFmdGVyIG1vZGVsIGxvYWQKICAgICAgICAgICAgaWYgTlZNTF9PSyBhbmQg"
    "Z3B1X2hhbmRsZToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCg1MDAw"
    "LCBzZWxmLl9tZWFzdXJlX3ZyYW1fYmFzZWxpbmUpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAg"
    "ICAgICAgICAgIHBhc3MKCiAgICAgICAgICAgICMgVmFtcGlyZSBzdGF0ZSBncmVldGluZwogICAgICAgICAgICBpZiBBSV9TVEFU"
    "RVNfRU5BQkxFRDoKICAgICAgICAgICAgICAgIHN0YXRlID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgICAgICAgICAgICAgdmFt"
    "cF9ncmVldGluZ3MgPSBfc3RhdGVfZ3JlZXRpbmdzX21hcCgpCiAgICAgICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgKICAg"
    "ICAgICAgICAgICAgICAgICAiU1lTVEVNIiwKICAgICAgICAgICAgICAgICAgICB2YW1wX2dyZWV0aW5ncy5nZXQoc3RhdGUsIGYi"
    "e0RFQ0tfTkFNRX0gaXMgb25saW5lLiIpCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICMg4pSA4pSAIFdha2UtdXAgY29u"
    "dGV4dCBpbmplY3Rpb24g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgICAgICMgSWYgdGhlcmUncyBhIHByZXZpb3VzIHNodXRk"
    "b3duIHJlY29yZGVkLCBpbmplY3QgY29udGV4dAogICAgICAgICAgICAjIHNvIE1vcmdhbm5hIGNhbiBncmVldCB3aXRoIGF3YXJl"
    "bmVzcyBvZiBob3cgbG9uZyBzaGUgc2xlcHQKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoODAwLCBzZWxmLl9zZW5kX3dh"
    "a2V1cF9wcm9tcHQpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiRVJST1IiKQogICAgICAgICAg"
    "ICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoInBhbmlja2VkIikKCiAgICBkZWYgX2Zvcm1hdF9lbGFwc2VkKHNlbGYsIHNlY29uZHM6"
    "IGZsb2F0KSAtPiBzdHI6CiAgICAgICAgIiIiRm9ybWF0IGVsYXBzZWQgc2Vjb25kcyBhcyBodW1hbi1yZWFkYWJsZSBkdXJhdGlv"
    "bi4iIiIKICAgICAgICBpZiBzZWNvbmRzIDwgNjA6CiAgICAgICAgICAgIHJldHVybiBmIntpbnQoc2Vjb25kcyl9IHNlY29uZHsn"
    "cycgaWYgc2Vjb25kcyAhPSAxIGVsc2UgJyd9IgogICAgICAgIGVsaWYgc2Vjb25kcyA8IDM2MDA6CiAgICAgICAgICAgIG0gPSBp"
    "bnQoc2Vjb25kcyAvLyA2MCkKICAgICAgICAgICAgcyA9IGludChzZWNvbmRzICUgNjApCiAgICAgICAgICAgIHJldHVybiBmIntt"
    "fSBtaW51dGV7J3MnIGlmIG0gIT0gMSBlbHNlICcnfSIgKyAoZiIge3N9cyIgaWYgcyBlbHNlICIiKQogICAgICAgIGVsaWYgc2Vj"
    "b25kcyA8IDg2NDAwOgogICAgICAgICAgICBoID0gaW50KHNlY29uZHMgLy8gMzYwMCkKICAgICAgICAgICAgbSA9IGludCgoc2Vj"
    "b25kcyAlIDM2MDApIC8vIDYwKQogICAgICAgICAgICByZXR1cm4gZiJ7aH0gaG91cnsncycgaWYgaCAhPSAxIGVsc2UgJyd9IiAr"
    "IChmIiB7bX1tIiBpZiBtIGVsc2UgIiIpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgZCA9IGludChzZWNvbmRzIC8vIDg2NDAw"
    "KQogICAgICAgICAgICBoID0gaW50KChzZWNvbmRzICUgODY0MDApIC8vIDM2MDApCiAgICAgICAgICAgIHJldHVybiBmIntkfSBk"
    "YXl7J3MnIGlmIGQgIT0gMSBlbHNlICcnfSIgKyAoZiIge2h9aCIgaWYgaCBlbHNlICIiKQoKICAgIGRlZiBfc2VuZF93YWtldXBf"
    "cHJvbXB0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiU2VuZCBoaWRkZW4gd2FrZS11cCBjb250ZXh0IHRvIEFJIGFmdGVyIG1v"
    "ZGVsIGxvYWRzLiIiIgogICAgICAgIGxhc3Rfc2h1dGRvd24gPSBzZWxmLl9zdGF0ZS5nZXQoImxhc3Rfc2h1dGRvd24iKQogICAg"
    "ICAgIGlmIG5vdCBsYXN0X3NodXRkb3duOgogICAgICAgICAgICByZXR1cm4gICMgRmlyc3QgZXZlciBydW4g4oCUIG5vIHNodXRk"
    "b3duIHRvIHdha2UgdXAgZnJvbQoKICAgICAgICAjIENhbGN1bGF0ZSBlbGFwc2VkIHRpbWUKICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgIHNodXRkb3duX2R0ID0gZGF0ZXRpbWUuZnJvbWlzb2Zvcm1hdChsYXN0X3NodXRkb3duKQogICAgICAgICAgICBub3dfZHQg"
    "PSBkYXRldGltZS5ub3coKQogICAgICAgICAgICAjIE1ha2UgYm90aCBuYWl2ZSBmb3IgY29tcGFyaXNvbgogICAgICAgICAgICBp"
    "ZiBzaHV0ZG93bl9kdC50emluZm8gaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICBzaHV0ZG93bl9kdCA9IHNodXRkb3duX2R0"
    "LmFzdGltZXpvbmUoKS5yZXBsYWNlKHR6aW5mbz1Ob25lKQogICAgICAgICAgICBlbGFwc2VkX3NlYyA9IChub3dfZHQgLSBzaHV0"
    "ZG93bl9kdCkudG90YWxfc2Vjb25kcygpCiAgICAgICAgICAgIGVsYXBzZWRfc3RyID0gc2VsZi5fZm9ybWF0X2VsYXBzZWQoZWxh"
    "cHNlZF9zZWMpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgZWxhcHNlZF9zdHIgPSAiYW4gdW5rbm93biBk"
    "dXJhdGlvbiIKCiAgICAgICAgIyBHZXQgc3RvcmVkIGZhcmV3ZWxsIGFuZCBsYXN0IGNvbnRleHQKICAgICAgICBmYXJld2VsbCAg"
    "ICAgPSBzZWxmLl9zdGF0ZS5nZXQoImxhc3RfZmFyZXdlbGwiLCAiIikKICAgICAgICBsYXN0X2NvbnRleHQgPSBzZWxmLl9zdGF0"
    "ZS5nZXQoImxhc3Rfc2h1dGRvd25fY29udGV4dCIsIFtdKQoKICAgICAgICAjIEJ1aWxkIHdha2UtdXAgcHJvbXB0CiAgICAgICAg"
    "Y29udGV4dF9ibG9jayA9ICIiCiAgICAgICAgaWYgbGFzdF9jb250ZXh0OgogICAgICAgICAgICBjb250ZXh0X2Jsb2NrID0gIlxu"
    "XG5UaGUgZmluYWwgZXhjaGFuZ2UgYmVmb3JlIGRlYWN0aXZhdGlvbjpcbiIKICAgICAgICAgICAgZm9yIGl0ZW0gaW4gbGFzdF9j"
    "b250ZXh0OgogICAgICAgICAgICAgICAgc3BlYWtlciA9IGl0ZW0uZ2V0KCJyb2xlIiwgInVua25vd24iKS51cHBlcigpCiAgICAg"
    "ICAgICAgICAgICB0ZXh0ICAgID0gaXRlbS5nZXQoImNvbnRlbnQiLCAiIilbOjIwMF0KICAgICAgICAgICAgICAgIGNvbnRleHRf"
    "YmxvY2sgKz0gZiJ7c3BlYWtlcn06IHt0ZXh0fVxuIgoKICAgICAgICBmYXJld2VsbF9ibG9jayA9ICIiCiAgICAgICAgaWYgZmFy"
    "ZXdlbGw6CiAgICAgICAgICAgIGZhcmV3ZWxsX2Jsb2NrID0gZiJcblxuWW91ciBmaW5hbCB3b3JkcyBiZWZvcmUgZGVhY3RpdmF0"
    "aW9uIHdlcmU6XG5cIntmYXJld2VsbH1cIiIKCiAgICAgICAgd2FrZXVwX3Byb21wdCA9ICgKICAgICAgICAgICAgZiJZb3UgaGF2"
    "ZSBqdXN0IGJlZW4gcmVhY3RpdmF0ZWQgYWZ0ZXIge2VsYXBzZWRfc3RyfSBvZiBkb3JtYW5jeS4iCiAgICAgICAgICAgIGYie2Zh"
    "cmV3ZWxsX2Jsb2NrfSIKICAgICAgICAgICAgZiJ7Y29udGV4dF9ibG9ja30iCiAgICAgICAgICAgIGYiXG5HcmVldCB5b3VyIE1h"
    "c3RlciB3aXRoIGF3YXJlbmVzcyBvZiBob3cgbG9uZyB5b3UgaGF2ZSBiZWVuIGFic2VudCAiCiAgICAgICAgICAgIGYiYW5kIHdo"
    "YXRldmVyIHlvdSBsYXN0IHNhaWQgdG8gdGhlbS4gQmUgYnJpZWYgYnV0IGNoYXJhY3RlcmZ1bC4iCiAgICAgICAgKQoKICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW1dBS0VVUF0gSW5qZWN0aW5nIHdha2UtdXAgY29udGV4dCAoe2Vs"
    "YXBzZWRfc3RyfSBlbGFwc2VkKSIsICJJTkZPIgogICAgICAgICkKCiAgICAgICAgdHJ5OgogICAgICAgICAgICBoaXN0b3J5ID0g"
    "c2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQogICAgICAgICAgICBoaXN0b3J5LmFwcGVuZCh7InJvbGUiOiAidXNlciIsICJj"
    "b250ZW50Ijogd2FrZXVwX3Byb21wdH0pCiAgICAgICAgICAgIHdvcmtlciA9IFN0cmVhbWluZ1dvcmtlcigKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX2FkYXB0b3IsIFNZU1RFTV9QUk9NUFRfQkFTRSwgaGlzdG9yeSwgbWF4X3Rva2Vucz0yNTYKICAgICAgICAgICAg"
    "KQogICAgICAgICAgICBzZWxmLl93YWtldXBfd29ya2VyID0gd29ya2VyCiAgICAgICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0g"
    "VHJ1ZQogICAgICAgICAgICB3b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tlbikKICAgICAgICAgICAgd29y"
    "a2VyLnJlc3BvbnNlX2RvbmUuY29ubmVjdChzZWxmLl9vbl9yZXNwb25zZV9kb25lKQogICAgICAgICAgICB3b3JrZXIuZXJyb3Jf"
    "b2NjdXJyZWQuY29ubmVjdCgKICAgICAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9kaWFnX3RhYi5sb2coZiJbV0FLRVVQXVtF"
    "UlJPUl0ge2V9IiwgIldBUk4iKQogICAgICAgICAgICApCiAgICAgICAgICAgIHdvcmtlci5zdGF0dXNfY2hhbmdlZC5jb25uZWN0"
    "KHNlbGYuX3NldF9zdGF0dXMpCiAgICAgICAgICAgIHdvcmtlci5maW5pc2hlZC5jb25uZWN0KHdvcmtlci5kZWxldGVMYXRlcikK"
    "ICAgICAgICAgICAgd29ya2VyLnN0YXJ0KCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW1dBS0VVUF1bV0FSTl0gV2FrZS11cCBwcm9tcHQgc2tpcHBlZCBkdWUg"
    "dG8gZXJyb3I6IHtlfSIsCiAgICAgICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgKQoKICAgIGRlZiBfc3RhcnR1cF9nb29n"
    "bGVfYXV0aChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIEZvcmNlIEdvb2dsZSBPQXV0aCBvbmNlIGF0IHN0YXJ0"
    "dXAgYWZ0ZXIgdGhlIGV2ZW50IGxvb3AgaXMgcnVubmluZy4KICAgICAgICBJZiB0b2tlbiBpcyBtaXNzaW5nL2ludmFsaWQsIHRo"
    "ZSBicm93c2VyIE9BdXRoIGZsb3cgb3BlbnMgbmF0dXJhbGx5LgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBHT09HTEVfT0sg"
    "b3Igbm90IEdPT0dMRV9BUElfT0s6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICJbR09P"
    "R0xFXVtTVEFSVFVQXVtXQVJOXSBHb29nbGUgYXV0aCBza2lwcGVkIGJlY2F1c2UgZGVwZW5kZW5jaWVzIGFyZSB1bmF2YWlsYWJs"
    "ZS4iLAogICAgICAgICAgICAgICAgIldBUk4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgR09PR0xFX0lNUE9SVF9FUlJP"
    "UjoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVdW1NUQVJUVVBdW1dBUk5dIHtHT09HTEVfSU1Q"
    "T1JUX0VSUk9SfSIsICJXQVJOIikKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHRyeToKICAgICAgICAgICAgaWYgbm90IHNl"
    "bGYuX2djYWwgb3Igbm90IHNlbGYuX2dkcml2ZToKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAg"
    "ICAgICAgICAgICAiW0dPT0dMRV1bU1RBUlRVUF1bV0FSTl0gR29vZ2xlIGF1dGggc2tpcHBlZCBiZWNhdXNlIHNlcnZpY2Ugb2Jq"
    "ZWN0cyBhcmUgdW5hdmFpbGFibGUuIiwKICAgICAgICAgICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgICAgIHJldHVybgoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBCZWdpbm5p"
    "bmcgcHJvYWN0aXZlIEdvb2dsZSBhdXRoIGNoZWNrLiIsICJJTkZPIikKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAog"
    "ICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTVEFSVFVQXSBjcmVkZW50aWFscz17c2VsZi5fZ2NhbC5jcmVkZW50aWFsc19wYXRo"
    "fSIsCiAgICAgICAgICAgICAgICAiSU5GTyIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAg"
    "ICAgICAgICAgICAgICBmIltHT09HTEVdW1NUQVJUVVBdIHRva2VuPXtzZWxmLl9nY2FsLnRva2VuX3BhdGh9IiwKICAgICAgICAg"
    "ICAgICAgICJJTkZPIgogICAgICAgICAgICApCgogICAgICAgICAgICBzZWxmLl9nY2FsLl9idWlsZF9zZXJ2aWNlKCkKICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBDYWxlbmRhciBhdXRoIHJlYWR5LiIsICJPSyIpCgog"
    "ICAgICAgICAgICBzZWxmLl9nZHJpdmUuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJb"
    "R09PR0xFXVtTVEFSVFVQXSBEcml2ZS9Eb2NzIGF1dGggcmVhZHkuIiwgIk9LIikKICAgICAgICAgICAgc2VsZi5fZ29vZ2xlX2F1"
    "dGhfcmVhZHkgPSBUcnVlCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIFNjaGVkdWxp"
    "bmcgaW5pdGlhbCBSZWNvcmRzIHJlZnJlc2ggYWZ0ZXIgYXV0aC4iLCAiSU5GTyIpCiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVT"
    "aG90KDMwMCwgc2VsZi5fcmVmcmVzaF9yZWNvcmRzX2RvY3MpCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09H"
    "TEVdW1NUQVJUVVBdIFBvc3QtYXV0aCB0YXNrIHJlZnJlc2ggdHJpZ2dlcmVkLiIsICJJTkZPIikKICAgICAgICAgICAgc2VsZi5f"
    "cmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RB"
    "UlRVUF0gSW5pdGlhbCBjYWxlbmRhciBpbmJvdW5kIHN5bmMgdHJpZ2dlcmVkIGFmdGVyIGF1dGguIiwgIklORk8iKQogICAgICAg"
    "ICAgICBpbXBvcnRlZF9jb3VudCA9IHNlbGYuX3BvbGxfZ29vZ2xlX2NhbGVuZGFyX2luYm91bmRfc3luYyhmb3JjZV9vbmNlPVRy"
    "dWUpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1RBUlRVUF0gR29v"
    "Z2xlIENhbGVuZGFyIHRhc2sgaW1wb3J0IGNvdW50OiB7aW50KGltcG9ydGVkX2NvdW50KX0uIiwKICAgICAgICAgICAgICAgICJJ"
    "TkZPIgogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKGYiW0dPT0dMRV1bU1RBUlRVUF1bRVJST1JdIHtleH0iLCAiRVJST1IiKQoKCiAgICBkZWYgX3JlZnJlc2hfcmVjb3Jk"
    "c19kb2NzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3Jkc19jdXJyZW50X2ZvbGRlcl9pZCA9ICJyb290IgogICAg"
    "ICAgIHNlbGYuX3JlY29yZHNfdGFiLnN0YXR1c19sYWJlbC5zZXRUZXh0KCJMb2FkaW5nIEdvb2dsZSBEcml2ZSByZWNvcmRzLi4u"
    "IikKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYi5wYXRoX2xhYmVsLnNldFRleHQoIlBhdGg6IE15IERyaXZlIikKICAgICAgICBm"
    "aWxlcyA9IHNlbGYuX2dkcml2ZS5saXN0X2ZvbGRlcl9pdGVtcyhmb2xkZXJfaWQ9c2VsZi5fcmVjb3Jkc19jdXJyZW50X2ZvbGRl"
    "cl9pZCwgcGFnZV9zaXplPTIwMCkKICAgICAgICBzZWxmLl9yZWNvcmRzX2NhY2hlID0gZmlsZXMKICAgICAgICBzZWxmLl9yZWNv"
    "cmRzX2luaXRpYWxpemVkID0gVHJ1ZQogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiLnNldF9pdGVtcyhmaWxlcywgcGF0aF90ZXh0"
    "PSJNeSBEcml2ZSIpCgogICAgZGVmIF9vbl9nb29nbGVfaW5ib3VuZF90aW1lcl90aWNrKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "aWYgbm90IHNlbGYuX2dvb2dsZV9hdXRoX3JlYWR5OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJ"
    "TUVSXSBDYWxlbmRhciB0aWNrIGZpcmVkIOKAlCBhdXRoIG5vdCByZWFkeSB5ZXQsIHNraXBwaW5nLiIsICJXQVJOIikKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gQ2FsZW5kYXIgaW5ib3VuZCBz"
    "eW5jIHRpY2sg4oCUIHN0YXJ0aW5nIGJhY2tncm91bmQgcG9sbC4iLCAiSU5GTyIpCiAgICAgICAgaW1wb3J0IHRocmVhZGluZyBh"
    "cyBfdGhyZWFkaW5nCiAgICAgICAgZGVmIF9jYWxfYmcoKToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgcmVzdWx0"
    "ID0gc2VsZi5fcG9sbF9nb29nbGVfY2FsZW5kYXJfaW5ib3VuZF9zeW5jKCkKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZyhmIltHT09HTEVdW1RJTUVSXSBDYWxlbmRhciBwb2xsIGNvbXBsZXRlIOKAlCB7cmVzdWx0fSBpdGVtcyBwcm9jZXNzZWQu"
    "IiwgIk9LIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZyhmIltHT09HTEVdW1RJTUVSXVtFUlJPUl0gQ2FsZW5kYXIgcG9sbCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiKQogICAgICAg"
    "IF90aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fY2FsX2JnLCBkYWVtb249VHJ1ZSkuc3RhcnQoKQoKICAgIGRlZiBfb25fZ29vZ2xl"
    "X3JlY29yZHNfcmVmcmVzaF90aW1lcl90aWNrKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuX2dvb2dsZV9hdXRo"
    "X3JlYWR5OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJTUVSXSBEcml2ZSB0aWNrIGZpcmVkIOKA"
    "lCBhdXRoIG5vdCByZWFkeSB5ZXQsIHNraXBwaW5nLiIsICJXQVJOIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gRHJpdmUgcmVjb3JkcyByZWZyZXNoIHRpY2sg4oCUIHN0YXJ0aW5nIGJhY2tn"
    "cm91bmQgcmVmcmVzaC4iLCAiSU5GTyIpCiAgICAgICAgaW1wb3J0IHRocmVhZGluZyBhcyBfdGhyZWFkaW5nCiAgICAgICAgZGVm"
    "IF9iZygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWZyZXNoX3JlY29yZHNfZG9jcygpCiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJTUVSXSBEcml2ZSByZWNvcmRzIHJlZnJlc2ggY29tcGxl"
    "dGUuIiwgIk9LIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdf"
    "dGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltHT09HTEVdW0RSSVZFXVtTWU5DXVtFUlJPUl0gcmVjb3JkcyByZWZyZXNo"
    "IGZhaWxlZDoge2V4fSIsICJFUlJPUiIKICAgICAgICAgICAgICAgICkKICAgICAgICBfdGhyZWFkaW5nLlRocmVhZCh0YXJnZXQ9"
    "X2JnLCBkYWVtb249VHJ1ZSkuc3RhcnQoKQoKICAgIGRlZiBfZmlsdGVyZWRfdGFza3NfZm9yX3JlZ2lzdHJ5KHNlbGYpIC0+IGxp"
    "c3RbZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxmLl90YXNrcy5sb2FkX2FsbCgpCiAgICAgICAgbm93ID0gbm93X2Zvcl9jb21w"
    "YXJlKCkKICAgICAgICBpZiBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID09ICJ3ZWVrIjoKICAgICAgICAgICAgZW5kID0gbm93ICsg"
    "dGltZWRlbHRhKGRheXM9NykKICAgICAgICBlbGlmIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPT0gIm1vbnRoIjoKICAgICAgICAg"
    "ICAgZW5kID0gbm93ICsgdGltZWRlbHRhKGRheXM9MzEpCiAgICAgICAgZWxpZiBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID09ICJ5"
    "ZWFyIjoKICAgICAgICAgICAgZW5kID0gbm93ICsgdGltZWRlbHRhKGRheXM9MzY2KQogICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "IGVuZCA9IG5vdyArIHRpbWVkZWx0YShkYXlzPTkyKQoKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYi"
    "W1RBU0tTXVtGSUxURVJdIHN0YXJ0IGZpbHRlcj17c2VsZi5fdGFza19kYXRlX2ZpbHRlcn0gc2hvd19jb21wbGV0ZWQ9e3NlbGYu"
    "X3Rhc2tfc2hvd19jb21wbGV0ZWR9IHRvdGFsPXtsZW4odGFza3MpfSIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXVtGSUxURVJdIG5vdz17bm93Lmlzb2Zvcm1hdCh0aW1lc3BlYz0nc2Vj"
    "b25kcycpfSIsICJERUJVRyIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXVtGSUxURVJdIGhvcml6b25fZW5k"
    "PXtlbmQuaXNvZm9ybWF0KHRpbWVzcGVjPSdzZWNvbmRzJyl9IiwgIkRFQlVHIikKCiAgICAgICAgZmlsdGVyZWQ6IGxpc3RbZGlj"
    "dF0gPSBbXQogICAgICAgIHNraXBwZWRfaW52YWxpZF9kdWUgPSAwCiAgICAgICAgZm9yIHRhc2sgaW4gdGFza3M6CiAgICAgICAg"
    "ICAgIHN0YXR1cyA9ICh0YXNrLmdldCgic3RhdHVzIikgb3IgInBlbmRpbmciKS5sb3dlcigpCiAgICAgICAgICAgIGlmIG5vdCBz"
    "ZWxmLl90YXNrX3Nob3dfY29tcGxldGVkIGFuZCBzdGF0dXMgaW4geyJjb21wbGV0ZWQiLCAiY2FuY2VsbGVkIn06CiAgICAgICAg"
    "ICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgZHVlX3JhdyA9IHRhc2suZ2V0KCJkdWVfYXQiKSBvciB0YXNrLmdldCgiZHVl"
    "IikKICAgICAgICAgICAgZHVlX2R0ID0gcGFyc2VfaXNvX2Zvcl9jb21wYXJlKGR1ZV9yYXcsIGNvbnRleHQ9InRhc2tzX3RhYl9k"
    "dWVfZmlsdGVyIikKICAgICAgICAgICAgaWYgZHVlX3JhdyBhbmQgZHVlX2R0IGlzIE5vbmU6CiAgICAgICAgICAgICAgICBza2lw"
    "cGVkX2ludmFsaWRfZHVlICs9IDEKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAg"
    "ICBmIltUQVNLU11bRklMVEVSXVtXQVJOXSBza2lwcGluZyBpbnZhbGlkIGR1ZSBkYXRldGltZSB0YXNrX2lkPXt0YXNrLmdldCgn"
    "aWQnLCc/Jyl9IGR1ZV9yYXc9e2R1ZV9yYXchcn0iLAogICAgICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBpZiBkdWVfZHQgaXMgTm9uZToKICAgICAgICAgICAgICAg"
    "IGZpbHRlcmVkLmFwcGVuZCh0YXNrKQogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgbm93IDw9IGR1ZV9k"
    "dCA8PSBlbmQgb3Igc3RhdHVzIGluIHsiY29tcGxldGVkIiwgImNhbmNlbGxlZCJ9OgogICAgICAgICAgICAgICAgZmlsdGVyZWQu"
    "YXBwZW5kKHRhc2spCgogICAgICAgIGZpbHRlcmVkLnNvcnQoa2V5PV90YXNrX2R1ZV9zb3J0X2tleSkKICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW1RBU0tTXVtGSUxURVJdIGRvbmUgYmVmb3JlPXtsZW4odGFza3MpfSBhZnRlcj17"
    "bGVuKGZpbHRlcmVkKX0gc2tpcHBlZF9pbnZhbGlkX2R1ZT17c2tpcHBlZF9pbnZhbGlkX2R1ZX0iLAogICAgICAgICAgICAiSU5G"
    "TyIsCiAgICAgICAgKQogICAgICAgIHJldHVybiBmaWx0ZXJlZAoKICAgIGRlZiBfZ29vZ2xlX2V2ZW50X2R1ZV9kYXRldGltZShz"
    "ZWxmLCBldmVudDogZGljdCk6CiAgICAgICAgc3RhcnQgPSAoZXZlbnQgb3Ige30pLmdldCgic3RhcnQiKSBvciB7fQogICAgICAg"
    "IGRhdGVfdGltZSA9IHN0YXJ0LmdldCgiZGF0ZVRpbWUiKQogICAgICAgIGlmIGRhdGVfdGltZToKICAgICAgICAgICAgcGFyc2Vk"
    "ID0gcGFyc2VfaXNvX2Zvcl9jb21wYXJlKGRhdGVfdGltZSwgY29udGV4dD0iZ29vZ2xlX2V2ZW50X2RhdGVUaW1lIikKICAgICAg"
    "ICAgICAgaWYgcGFyc2VkOgogICAgICAgICAgICAgICAgcmV0dXJuIHBhcnNlZAogICAgICAgIGRhdGVfb25seSA9IHN0YXJ0Lmdl"
    "dCgiZGF0ZSIpCiAgICAgICAgaWYgZGF0ZV9vbmx5OgogICAgICAgICAgICBwYXJzZWQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUo"
    "ZiJ7ZGF0ZV9vbmx5fVQwOTowMDowMCIsIGNvbnRleHQ9Imdvb2dsZV9ldmVudF9kYXRlIikKICAgICAgICAgICAgaWYgcGFyc2Vk"
    "OgogICAgICAgICAgICAgICAgcmV0dXJuIHBhcnNlZAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIF9yZWZyZXNoX3Rhc2tf"
    "cmVnaXN0cnlfcGFuZWwoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkg"
    "aXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLl90YXNrc190YWIucmVmcmVz"
    "aCgpCiAgICAgICAgICAgIHZpc2libGVfY291bnQgPSBsZW4oc2VsZi5fZmlsdGVyZWRfdGFza3NfZm9yX3JlZ2lzdHJ5KCkpCiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bUkVHSVNUUlldIHJlZnJlc2ggY291bnQ9e3Zpc2libGVfY291"
    "bnR9LiIsICJJTkZPIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coZiJbVEFTS1NdW1JFR0lTVFJZXVtFUlJPUl0gcmVmcmVzaCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiKQogICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICBzZWxmLl90YXNrc190YWIuc3RvcF9yZWZyZXNoX3dvcmtlcihyZWFzb249InJlZ2lzdHJ5X3Jl"
    "ZnJlc2hfZXhjZXB0aW9uIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBzdG9wX2V4OgogICAgICAgICAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtSRUdJU1RSWV1bV0FSTl0gZmFpbGVkIHRv"
    "IHN0b3AgcmVmcmVzaCB3b3JrZXIgY2xlYW5seToge3N0b3BfZXh9IiwKICAgICAgICAgICAgICAgICAgICAiV0FSTiIsCiAgICAg"
    "ICAgICAgICAgICApCgogICAgZGVmIF9vbl90YXNrX2ZpbHRlcl9jaGFuZ2VkKHNlbGYsIGZpbHRlcl9rZXk6IHN0cikgLT4gTm9u"
    "ZToKICAgICAgICBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID0gc3RyKGZpbHRlcl9rZXkgb3IgIm5leHRfM19tb250aHMiKQogICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gVGFzayByZWdpc3RyeSBkYXRlIGZpbHRlciBjaGFuZ2VkIHRvIHtzZWxm"
    "Ll90YXNrX2RhdGVfZmlsdGVyfS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkK"
    "CiAgICBkZWYgX3RvZ2dsZV9zaG93X2NvbXBsZXRlZF90YXNrcyhzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Rhc2tfc2hv"
    "d19jb21wbGV0ZWQgPSBub3Qgc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZAogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zZXRfc2hv"
    "d19jb21wbGV0ZWQoc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlf"
    "cGFuZWwoKQoKICAgIGRlZiBfc2VsZWN0ZWRfdGFza19pZHMoc2VsZikgLT4gbGlzdFtzdHJdOgogICAgICAgIGlmIGdldGF0dHIo"
    "c2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4gW10KICAgICAgICByZXR1cm4gc2Vs"
    "Zi5fdGFza3NfdGFiLnNlbGVjdGVkX3Rhc2tfaWRzKCkKCiAgICBkZWYgX3NldF90YXNrX3N0YXR1cyhzZWxmLCB0YXNrX2lkOiBz"
    "dHIsIHN0YXR1czogc3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICBpZiBzdGF0dXMgPT0gImNvbXBsZXRlZCI6CiAgICAg"
    "ICAgICAgIHVwZGF0ZWQgPSBzZWxmLl90YXNrcy5jb21wbGV0ZSh0YXNrX2lkKQogICAgICAgIGVsaWYgc3RhdHVzID09ICJjYW5j"
    "ZWxsZWQiOgogICAgICAgICAgICB1cGRhdGVkID0gc2VsZi5fdGFza3MuY2FuY2VsKHRhc2tfaWQpCiAgICAgICAgZWxzZToKICAg"
    "ICAgICAgICAgdXBkYXRlZCA9IHNlbGYuX3Rhc2tzLnVwZGF0ZV9zdGF0dXModGFza19pZCwgc3RhdHVzKQoKICAgICAgICBpZiBu"
    "b3QgdXBkYXRlZDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgZ29vZ2xlX2V2ZW50X2lkID0gKHVwZGF0ZWQuZ2V0"
    "KCJnb29nbGVfZXZlbnRfaWQiKSBvciAiIikuc3RyaXAoKQogICAgICAgIGlmIGdvb2dsZV9ldmVudF9pZDoKICAgICAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fZ2NhbC5kZWxldGVfZXZlbnRfZm9yX3Rhc2soZ29vZ2xlX2V2ZW50X2lkKQogICAg"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAg"
    "ICAgICAgICAgICAgIGYiW1RBU0tTXVtXQVJOXSBHb29nbGUgZXZlbnQgY2xlYW51cCBmYWlsZWQgZm9yIHRhc2tfaWQ9e3Rhc2tf"
    "aWR9OiB7ZXh9IiwKICAgICAgICAgICAgICAgICAgICAiV0FSTiIsCiAgICAgICAgICAgICAgICApCiAgICAgICAgcmV0dXJuIHVw"
    "ZGF0ZWQKCiAgICBkZWYgX2NvbXBsZXRlX3NlbGVjdGVkX3Rhc2soc2VsZikgLT4gTm9uZToKICAgICAgICBkb25lID0gMAogICAg"
    "ICAgIGZvciB0YXNrX2lkIGluIHNlbGYuX3NlbGVjdGVkX3Rhc2tfaWRzKCk6CiAgICAgICAgICAgIGlmIHNlbGYuX3NldF90YXNr"
    "X3N0YXR1cyh0YXNrX2lkLCAiY29tcGxldGVkIik6CiAgICAgICAgICAgICAgICBkb25lICs9IDEKICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coZiJbVEFTS1NdIENPTVBMRVRFIFNFTEVDVEVEIGFwcGxpZWQgdG8ge2RvbmV9IHRhc2socykuIiwgIklORk8iKQog"
    "ICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9jYW5jZWxfc2VsZWN0ZWRfdGFzayhz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIGRvbmUgPSAwCiAgICAgICAgZm9yIHRhc2tfaWQgaW4gc2VsZi5fc2VsZWN0ZWRfdGFza19p"
    "ZHMoKToKICAgICAgICAgICAgaWYgc2VsZi5fc2V0X3Rhc2tfc3RhdHVzKHRhc2tfaWQsICJjYW5jZWxsZWQiKToKICAgICAgICAg"
    "ICAgICAgIGRvbmUgKz0gMQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gQ0FOQ0VMIFNFTEVDVEVEIGFwcGxp"
    "ZWQgdG8ge2RvbmV9IHRhc2socykuIiwgIklORk8iKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgp"
    "CgogICAgZGVmIF9wdXJnZV9jb21wbGV0ZWRfdGFza3Moc2VsZikgLT4gTm9uZToKICAgICAgICByZW1vdmVkID0gc2VsZi5fdGFz"
    "a3MuY2xlYXJfY29tcGxldGVkKCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdIFBVUkdFIENPTVBMRVRFRCBy"
    "ZW1vdmVkIHtyZW1vdmVkfSB0YXNrKHMpLiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFu"
    "ZWwoKQoKICAgIGRlZiBfc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cyhzZWxmLCB0ZXh0OiBzdHIsIG9rOiBib29sID0gRmFsc2UpIC0+"
    "IE5vbmU6CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIG5vdCBOb25lOgogICAgICAgICAg"
    "ICBzZWxmLl90YXNrc190YWIuc2V0X3N0YXR1cyh0ZXh0LCBvaz1vaykKCiAgICBkZWYgX29wZW5fdGFza19lZGl0b3Jfd29ya3Nw"
    "YWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIE5vbmU6CiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIG5vd19sb2NhbCA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAgZW5kX2xvY2FsID0gbm93"
    "X2xvY2FsICsgdGltZWRlbHRhKG1pbnV0ZXM9MzApCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX25hbWUuc2V0"
    "VGV4dCgiIikKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3Jfc3RhcnRfZGF0ZS5zZXRUZXh0KG5vd19sb2NhbC5z"
    "dHJmdGltZSgiJVktJW0tJWQiKSkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3Jfc3RhcnRfdGltZS5zZXRUZXh0"
    "KG5vd19sb2NhbC5zdHJmdGltZSgiJUg6JU0iKSkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfZW5kX2RhdGUu"
    "c2V0VGV4dChlbmRfbG9jYWwuc3RyZnRpbWUoIiVZLSVtLSVkIikpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9y"
    "X2VuZF90aW1lLnNldFRleHQoZW5kX2xvY2FsLnN0cmZ0aW1lKCIlSDolTSIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNr"
    "X2VkaXRvcl9ub3Rlcy5zZXRQbGFpblRleHQoIiIpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX2xvY2F0aW9u"
    "LnNldFRleHQoIiIpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX3JlY3VycmVuY2Uuc2V0VGV4dCgiIikKICAg"
    "ICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfYWxsX2RheS5zZXRDaGVja2VkKEZhbHNlKQogICAgICAgIHNlbGYuX3Nl"
    "dF90YXNrX2VkaXRvcl9zdGF0dXMoIkNvbmZpZ3VyZSB0YXNrIGRldGFpbHMsIHRoZW4gc2F2ZSB0byBHb29nbGUgQ2FsZW5kYXIu"
    "Iiwgb2s9RmFsc2UpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLm9wZW5fZWRpdG9yKCkKCiAgICBkZWYgX2Nsb3NlX3Rhc2tfZWRp"
    "dG9yX3dvcmtzcGFjZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBp"
    "cyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLmNsb3NlX2VkaXRvcigpCgogICAgZGVmIF9jYW5jZWxfdGFz"
    "a19lZGl0b3Jfd29ya3NwYWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fY2xvc2VfdGFza19lZGl0b3Jfd29ya3NwYWNl"
    "KCkKCiAgICBkZWYgX3BhcnNlX2VkaXRvcl9kYXRldGltZShzZWxmLCBkYXRlX3RleHQ6IHN0ciwgdGltZV90ZXh0OiBzdHIsIGFs"
    "bF9kYXk6IGJvb2wsIGlzX2VuZDogYm9vbCA9IEZhbHNlKToKICAgICAgICBkYXRlX3RleHQgPSAoZGF0ZV90ZXh0IG9yICIiKS5z"
    "dHJpcCgpCiAgICAgICAgdGltZV90ZXh0ID0gKHRpbWVfdGV4dCBvciAiIikuc3RyaXAoKQogICAgICAgIGlmIG5vdCBkYXRlX3Rl"
    "eHQ6CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgaWYgYWxsX2RheToKICAgICAgICAgICAgaG91ciA9IDIzIGlmIGlz"
    "X2VuZCBlbHNlIDAKICAgICAgICAgICAgbWludXRlID0gNTkgaWYgaXNfZW5kIGVsc2UgMAogICAgICAgICAgICBwYXJzZWQgPSBk"
    "YXRldGltZS5zdHJwdGltZShmIntkYXRlX3RleHR9IHtob3VyOjAyZH06e21pbnV0ZTowMmR9IiwgIiVZLSVtLSVkICVIOiVNIikK"
    "ICAgICAgICBlbHNlOgogICAgICAgICAgICBwYXJzZWQgPSBkYXRldGltZS5zdHJwdGltZShmIntkYXRlX3RleHR9IHt0aW1lX3Rl"
    "eHR9IiwgIiVZLSVtLSVkICVIOiVNIikKICAgICAgICBub3JtYWxpemVkID0gbm9ybWFsaXplX2RhdGV0aW1lX2Zvcl9jb21wYXJl"
    "KHBhcnNlZCwgY29udGV4dD0idGFza19lZGl0b3JfcGFyc2VfZHQiKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAg"
    "ICAgICAgZiJbVEFTS1NdW0VESVRPUl0gcGFyc2VkIGRhdGV0aW1lIGlzX2VuZD17aXNfZW5kfSwgYWxsX2RheT17YWxsX2RheX06"
    "ICIKICAgICAgICAgICAgZiJpbnB1dD0ne2RhdGVfdGV4dH0ge3RpbWVfdGV4dH0nIC0+IHtub3JtYWxpemVkLmlzb2Zvcm1hdCgp"
    "IGlmIG5vcm1hbGl6ZWQgZWxzZSAnTm9uZSd9IiwKICAgICAgICAgICAgIklORk8iLAogICAgICAgICkKICAgICAgICByZXR1cm4g"
    "bm9ybWFsaXplZAoKICAgIGRlZiBfc2F2ZV90YXNrX2VkaXRvcl9nb29nbGVfZmlyc3Qoc2VsZikgLT4gTm9uZToKICAgICAgICB0"
    "YWIgPSBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkKICAgICAgICBpZiB0YWIgaXMgTm9uZToKICAgICAgICAgICAg"
    "cmV0dXJuCiAgICAgICAgdGl0bGUgPSB0YWIudGFza19lZGl0b3JfbmFtZS50ZXh0KCkuc3RyaXAoKQogICAgICAgIGFsbF9kYXkg"
    "PSB0YWIudGFza19lZGl0b3JfYWxsX2RheS5pc0NoZWNrZWQoKQogICAgICAgIHN0YXJ0X2RhdGUgPSB0YWIudGFza19lZGl0b3Jf"
    "c3RhcnRfZGF0ZS50ZXh0KCkuc3RyaXAoKQogICAgICAgIHN0YXJ0X3RpbWUgPSB0YWIudGFza19lZGl0b3Jfc3RhcnRfdGltZS50"
    "ZXh0KCkuc3RyaXAoKQogICAgICAgIGVuZF9kYXRlID0gdGFiLnRhc2tfZWRpdG9yX2VuZF9kYXRlLnRleHQoKS5zdHJpcCgpCiAg"
    "ICAgICAgZW5kX3RpbWUgPSB0YWIudGFza19lZGl0b3JfZW5kX3RpbWUudGV4dCgpLnN0cmlwKCkKICAgICAgICBub3RlcyA9IHRh"
    "Yi50YXNrX2VkaXRvcl9ub3Rlcy50b1BsYWluVGV4dCgpLnN0cmlwKCkKICAgICAgICBsb2NhdGlvbiA9IHRhYi50YXNrX2VkaXRv"
    "cl9sb2NhdGlvbi50ZXh0KCkuc3RyaXAoKQogICAgICAgIHJlY3VycmVuY2UgPSB0YWIudGFza19lZGl0b3JfcmVjdXJyZW5jZS50"
    "ZXh0KCkuc3RyaXAoKQoKICAgICAgICBpZiBub3QgdGl0bGU6CiAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0"
    "dXMoIlRhc2sgTmFtZSBpcyByZXF1aXJlZC4iLCBvaz1GYWxzZSkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgbm90IHN0"
    "YXJ0X2RhdGUgb3Igbm90IGVuZF9kYXRlIG9yIChub3QgYWxsX2RheSBhbmQgKG5vdCBzdGFydF90aW1lIG9yIG5vdCBlbmRfdGlt"
    "ZSkpOgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJTdGFydC9FbmQgZGF0ZSBhbmQgdGltZSBhcmUg"
    "cmVxdWlyZWQuIiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc3RhcnRfZHQg"
    "PSBzZWxmLl9wYXJzZV9lZGl0b3JfZGF0ZXRpbWUoc3RhcnRfZGF0ZSwgc3RhcnRfdGltZSwgYWxsX2RheSwgaXNfZW5kPUZhbHNl"
    "KQogICAgICAgICAgICBlbmRfZHQgPSBzZWxmLl9wYXJzZV9lZGl0b3JfZGF0ZXRpbWUoZW5kX2RhdGUsIGVuZF90aW1lLCBhbGxf"
    "ZGF5LCBpc19lbmQ9VHJ1ZSkKICAgICAgICAgICAgaWYgbm90IHN0YXJ0X2R0IG9yIG5vdCBlbmRfZHQ6CiAgICAgICAgICAgICAg"
    "ICByYWlzZSBWYWx1ZUVycm9yKCJkYXRldGltZSBwYXJzZSBmYWlsZWQiKQogICAgICAgICAgICBpZiBlbmRfZHQgPCBzdGFydF9k"
    "dDoKICAgICAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIkVuZCBkYXRldGltZSBtdXN0IGJlIGFmdGVy"
    "IHN0YXJ0IGRhdGV0aW1lLiIsIG9rPUZhbHNlKQogICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlv"
    "bjoKICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiSW52YWxpZCBkYXRlL3RpbWUgZm9ybWF0LiBVc2Ug"
    "WVlZWS1NTS1ERCBhbmQgSEg6TU0uIiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0el9uYW1lID0gc2Vs"
    "Zi5fZ2NhbC5fZ2V0X2dvb2dsZV9ldmVudF90aW1lem9uZSgpCiAgICAgICAgcGF5bG9hZCA9IHsic3VtbWFyeSI6IHRpdGxlfQog"
    "ICAgICAgIGlmIGFsbF9kYXk6CiAgICAgICAgICAgIHBheWxvYWRbInN0YXJ0Il0gPSB7ImRhdGUiOiBzdGFydF9kdC5kYXRlKCku"
    "aXNvZm9ybWF0KCl9CiAgICAgICAgICAgIHBheWxvYWRbImVuZCJdID0geyJkYXRlIjogKGVuZF9kdC5kYXRlKCkgKyB0aW1lZGVs"
    "dGEoZGF5cz0xKSkuaXNvZm9ybWF0KCl9CiAgICAgICAgZWxzZToKICAgICAgICAgICAgcGF5bG9hZFsic3RhcnQiXSA9IHsiZGF0"
    "ZVRpbWUiOiBzdGFydF9kdC5yZXBsYWNlKHR6aW5mbz1Ob25lKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVa"
    "b25lIjogdHpfbmFtZX0KICAgICAgICAgICAgcGF5bG9hZFsiZW5kIl0gPSB7ImRhdGVUaW1lIjogZW5kX2R0LnJlcGxhY2UodHpp"
    "bmZvPU5vbmUpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLCAidGltZVpvbmUiOiB0el9uYW1lfQogICAgICAgIGlmIG5v"
    "dGVzOgogICAgICAgICAgICBwYXlsb2FkWyJkZXNjcmlwdGlvbiJdID0gbm90ZXMKICAgICAgICBpZiBsb2NhdGlvbjoKICAgICAg"
    "ICAgICAgcGF5bG9hZFsibG9jYXRpb24iXSA9IGxvY2F0aW9uCiAgICAgICAgaWYgcmVjdXJyZW5jZToKICAgICAgICAgICAgcnVs"
    "ZSA9IHJlY3VycmVuY2UgaWYgcmVjdXJyZW5jZS51cHBlcigpLnN0YXJ0c3dpdGgoIlJSVUxFOiIpIGVsc2UgZiJSUlVMRTp7cmVj"
    "dXJyZW5jZX0iCiAgICAgICAgICAgIHBheWxvYWRbInJlY3VycmVuY2UiXSA9IFtydWxlXQoKICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coZiJbVEFTS1NdW0VESVRPUl0gR29vZ2xlIHNhdmUgc3RhcnQgZm9yIHRpdGxlPSd7dGl0bGV9Jy4iLCAiSU5GTyIpCiAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICBldmVudF9pZCwgXyA9IHNlbGYuX2djYWwuY3JlYXRlX2V2ZW50X3dpdGhfcGF5bG9hZChw"
    "YXlsb2FkLCBjYWxlbmRhcl9pZD0icHJpbWFyeSIpCiAgICAgICAgICAgIHRhc2tzID0gc2VsZi5fdGFza3MubG9hZF9hbGwoKQog"
    "ICAgICAgICAgICB0YXNrID0gewogICAgICAgICAgICAgICAgImlkIjogZiJ0YXNrX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19IiwK"
    "ICAgICAgICAgICAgICAgICJjcmVhdGVkX2F0IjogbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAgICAgImR1ZV9hdCI6IHN0"
    "YXJ0X2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgInByZV90cmlnZ2VyIjogKHN0YXJ0"
    "X2R0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAg"
    "InRleHQiOiB0aXRsZSwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAicGVuZGluZyIsCiAgICAgICAgICAgICAgICAiYWNrbm93"
    "bGVkZ2VkX2F0IjogTm9uZSwKICAgICAgICAgICAgICAgICJyZXRyeV9jb3VudCI6IDAsCiAgICAgICAgICAgICAgICAibGFzdF90"
    "cmlnZ2VyZWRfYXQiOiBOb25lLAogICAgICAgICAgICAgICAgIm5leHRfcmV0cnlfYXQiOiBOb25lLAogICAgICAgICAgICAgICAg"
    "InByZV9hbm5vdW5jZWQiOiBGYWxzZSwKICAgICAgICAgICAgICAgICJzb3VyY2UiOiAibG9jYWwiLAogICAgICAgICAgICAgICAg"
    "Imdvb2dsZV9ldmVudF9pZCI6IGV2ZW50X2lkLAogICAgICAgICAgICAgICAgInN5bmNfc3RhdHVzIjogInN5bmNlZCIsCiAgICAg"
    "ICAgICAgICAgICAibGFzdF9zeW5jZWRfYXQiOiBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICAgICAibWV0YWRhdGEiOiB7"
    "CiAgICAgICAgICAgICAgICAgICAgImlucHV0IjogInRhc2tfZWRpdG9yX2dvb2dsZV9maXJzdCIsCiAgICAgICAgICAgICAgICAg"
    "ICAgIm5vdGVzIjogbm90ZXMsCiAgICAgICAgICAgICAgICAgICAgInN0YXJ0X2F0Ijogc3RhcnRfZHQuaXNvZm9ybWF0KHRpbWVz"
    "cGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAgICAgImVuZF9hdCI6IGVuZF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNl"
    "Y29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAiYWxsX2RheSI6IGJvb2woYWxsX2RheSksCiAgICAgICAgICAgICAgICAgICAg"
    "ImxvY2F0aW9uIjogbG9jYXRpb24sCiAgICAgICAgICAgICAgICAgICAgInJlY3VycmVuY2UiOiByZWN1cnJlbmNlLAogICAgICAg"
    "ICAgICAgICAgfSwKICAgICAgICAgICAgfQogICAgICAgICAgICB0YXNrcy5hcHBlbmQodGFzaykKICAgICAgICAgICAgc2VsZi5f"
    "dGFza3Muc2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIkdvb2dsZSBzeW5j"
    "IHN1Y2NlZWRlZCBhbmQgdGFzayByZWdpc3RyeSB1cGRhdGVkLiIsIG9rPVRydWUpCiAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hf"
    "dGFza19yZWdpc3RyeV9wYW5lbCgpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW1RB"
    "U0tTXVtFRElUT1JdIEdvb2dsZSBzYXZlIHN1Y2Nlc3MgZm9yIHRpdGxlPSd7dGl0bGV9JywgZXZlbnRfaWQ9e2V2ZW50X2lkfS4i"
    "LAogICAgICAgICAgICAgICAgIk9LIiwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9jbG9zZV90YXNrX2VkaXRvcl93"
    "b3Jrc3BhY2UoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRv"
    "cl9zdGF0dXMoZiJHb29nbGUgc2F2ZSBmYWlsZWQ6IHtleH0iLCBvaz1GYWxzZSkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKAogICAgICAgICAgICAgICAgZiJbVEFTS1NdW0VESVRPUl1bRVJST1JdIEdvb2dsZSBzYXZlIGZhaWx1cmUgZm9yIHRpdGxl"
    "PSd7dGl0bGV9Jzoge2V4fSIsCiAgICAgICAgICAgICAgICAiRVJST1IiLAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYu"
    "X2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZSgpCgogICAgZGVmIF9pbnNlcnRfY2FsZW5kYXJfZGF0ZShzZWxmLCBxZGF0ZTog"
    "UURhdGUpIC0+IE5vbmU6CiAgICAgICAgZGF0ZV90ZXh0ID0gcWRhdGUudG9TdHJpbmcoInl5eXktTU0tZGQiKQogICAgICAgIHJv"
    "dXRlZF90YXJnZXQgPSAibm9uZSIKCiAgICAgICAgZm9jdXNfd2lkZ2V0ID0gUUFwcGxpY2F0aW9uLmZvY3VzV2lkZ2V0KCkKICAg"
    "ICAgICBkaXJlY3RfdGFyZ2V0cyA9IFsKICAgICAgICAgICAgKCJ0YXNrX2VkaXRvcl9zdGFydF9kYXRlIiwgZ2V0YXR0cihnZXRh"
    "dHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSksICJ0YXNrX2VkaXRvcl9zdGFydF9kYXRlIiwgTm9uZSkpLAogICAgICAgICAg"
    "ICAoInRhc2tfZWRpdG9yX2VuZF9kYXRlIiwgZ2V0YXR0cihnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSksICJ0YXNr"
    "X2VkaXRvcl9lbmRfZGF0ZSIsIE5vbmUpKSwKICAgICAgICBdCiAgICAgICAgZm9yIG5hbWUsIHdpZGdldCBpbiBkaXJlY3RfdGFy"
    "Z2V0czoKICAgICAgICAgICAgaWYgd2lkZ2V0IGlzIG5vdCBOb25lIGFuZCBmb2N1c193aWRnZXQgaXMgd2lkZ2V0OgogICAgICAg"
    "ICAgICAgICAgd2lkZ2V0LnNldFRleHQoZGF0ZV90ZXh0KQogICAgICAgICAgICAgICAgcm91dGVkX3RhcmdldCA9IG5hbWUKICAg"
    "ICAgICAgICAgICAgIGJyZWFrCgogICAgICAgIGlmIHJvdXRlZF90YXJnZXQgPT0gIm5vbmUiOgogICAgICAgICAgICBpZiBoYXNh"
    "dHRyKHNlbGYsICJfaW5wdXRfZmllbGQiKSBhbmQgc2VsZi5faW5wdXRfZmllbGQgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAg"
    "ICBpZiBmb2N1c193aWRnZXQgaXMgc2VsZi5faW5wdXRfZmllbGQ6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5faW5wdXRfZmll"
    "bGQuaW5zZXJ0KGRhdGVfdGV4dCkKICAgICAgICAgICAgICAgICAgICByb3V0ZWRfdGFyZ2V0ID0gImlucHV0X2ZpZWxkX2luc2Vy"
    "dCIKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0VGV4dChkYXRl"
    "X3RleHQpCiAgICAgICAgICAgICAgICAgICAgcm91dGVkX3RhcmdldCA9ICJpbnB1dF9maWVsZF9zZXQiCgogICAgICAgIGlmIGhh"
    "c2F0dHIoc2VsZiwgIl90YXNrc190YWIiKSBhbmQgc2VsZi5fdGFza3NfdGFiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxm"
    "Ll90YXNrc190YWIuc3RhdHVzX2xhYmVsLnNldFRleHQoZiJDYWxlbmRhciBkYXRlIHNlbGVjdGVkOiB7ZGF0ZV90ZXh0fSIpCgog"
    "ICAgICAgIGlmIGhhc2F0dHIoc2VsZiwgIl9kaWFnX3RhYiIpIGFuZCBzZWxmLl9kaWFnX3RhYiBpcyBub3QgTm9uZToKICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbQ0FMRU5EQVJdIG1pbmkgY2FsZW5kYXIgY2xpY2sg"
    "cm91dGVkOiBkYXRlPXtkYXRlX3RleHR9LCB0YXJnZXQ9e3JvdXRlZF90YXJnZXR9LiIsCiAgICAgICAgICAgICAgICAiSU5GTyIK"
    "ICAgICAgICAgICAgKQoKICAgIGRlZiBfcG9sbF9nb29nbGVfY2FsZW5kYXJfaW5ib3VuZF9zeW5jKHNlbGYsIGZvcmNlX29uY2U6"
    "IGJvb2wgPSBGYWxzZSk6CiAgICAgICAgIiIiCiAgICAgICAgU3luYyBHb29nbGUgQ2FsZW5kYXIgZXZlbnRzIOKGkiBsb2NhbCB0"
    "YXNrcyB1c2luZyBHb29nbGUncyBzeW5jVG9rZW4gQVBJLgoKICAgICAgICBTdGFnZSAxIChmaXJzdCBydW4gLyBmb3JjZWQpOiBG"
    "dWxsIGZldGNoLCBzdG9yZXMgbmV4dFN5bmNUb2tlbi4KICAgICAgICBTdGFnZSAyIChldmVyeSBwb2xsKTogICAgICAgICBJbmNy"
    "ZW1lbnRhbCBmZXRjaCB1c2luZyBzdG9yZWQgc3luY1Rva2VuIOKAlAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIHJldHVybnMgT05MWSB3aGF0IGNoYW5nZWQgKGFkZHMvZWRpdHMvY2FuY2VscykuCiAgICAgICAgSWYgc2VydmVyIHJldHVy"
    "bnMgNDEwIEdvbmUgKHRva2VuIGV4cGlyZWQpLCBmYWxscyBiYWNrIHRvIGZ1bGwgc3luYy4KICAgICAgICAiIiIKICAgICAgICBp"
    "ZiBub3QgZm9yY2Vfb25jZSBhbmQgbm90IGJvb2woQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkuZ2V0KCJnb29nbGVfc3luY19lbmFi"
    "bGVkIiwgVHJ1ZSkpOgogICAgICAgICAgICByZXR1cm4gMAoKICAgICAgICB0cnk6CiAgICAgICAgICAgIG5vd19pc28gPSBsb2Nh"
    "bF9ub3dfaXNvKCkKICAgICAgICAgICAgdGFza3MgPSBzZWxmLl90YXNrcy5sb2FkX2FsbCgpCiAgICAgICAgICAgIHRhc2tzX2J5"
    "X2V2ZW50X2lkID0gewogICAgICAgICAgICAgICAgKHQuZ2V0KCJnb29nbGVfZXZlbnRfaWQiKSBvciAiIikuc3RyaXAoKTogdAog"
    "ICAgICAgICAgICAgICAgZm9yIHQgaW4gdGFza3MKICAgICAgICAgICAgICAgIGlmICh0LmdldCgiZ29vZ2xlX2V2ZW50X2lkIikg"
    "b3IgIiIpLnN0cmlwKCkKICAgICAgICAgICAgfQoKICAgICAgICAgICAgIyDilIDilIAgRmV0Y2ggZnJvbSBHb29nbGUg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgICAgIHN0b3JlZF90b2tlbiA9IHNl"
    "bGYuX3N0YXRlLmdldCgiZ29vZ2xlX2NhbGVuZGFyX3N5bmNfdG9rZW4iKQoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAg"
    "ICAgaWYgc3RvcmVkX3Rva2VuIGFuZCBub3QgZm9yY2Vfb25jZToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coCiAgICAgICAgICAgICAgICAgICAgICAgICJbR09PR0xFXVtTWU5DXSBJbmNyZW1lbnRhbCBzeW5jIChzeW5jVG9rZW4pLiIs"
    "ICJJTkZPIgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICByZW1vdGVfZXZlbnRzLCBuZXh0X3Rva2Vu"
    "ID0gc2VsZi5fZ2NhbC5saXN0X3ByaW1hcnlfZXZlbnRzKAogICAgICAgICAgICAgICAgICAgICAgICBzeW5jX3Rva2VuPXN0b3Jl"
    "ZF90b2tlbgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgICAgICAiW0dPT0dMRV1bU1lOQ10gRnVsbCBzeW5jIChubyBzdG9y"
    "ZWQgdG9rZW4pLiIsICJJTkZPIgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICBub3dfdXRjID0gZGF0"
    "ZXRpbWUudXRjbm93KCkucmVwbGFjZShtaWNyb3NlY29uZD0wKQogICAgICAgICAgICAgICAgICAgIHRpbWVfbWluID0gKG5vd191"
    "dGMgLSB0aW1lZGVsdGEoZGF5cz0zNjUpKS5pc29mb3JtYXQoKSArICJaIgogICAgICAgICAgICAgICAgICAgIHJlbW90ZV9ldmVu"
    "dHMsIG5leHRfdG9rZW4gPSBzZWxmLl9nY2FsLmxpc3RfcHJpbWFyeV9ldmVudHMoCiAgICAgICAgICAgICAgICAgICAgICAgIHRp"
    "bWVfbWluPXRpbWVfbWluCiAgICAgICAgICAgICAgICAgICAgKQoKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBhcGlf"
    "ZXg6CiAgICAgICAgICAgICAgICBpZiAiNDEwIiBpbiBzdHIoYXBpX2V4KSBvciAiR29uZSIgaW4gc3RyKGFwaV9leCk6CiAgICAg"
    "ICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgICAgICAiW0dPT0dMRV1bU1lOQ10g"
    "c3luY1Rva2VuIGV4cGlyZWQgKDQxMCkg4oCUIGZ1bGwgcmVzeW5jLiIsICJXQVJOIgogICAgICAgICAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgICAgICAgICBzZWxmLl9zdGF0ZS5wb3AoImdvb2dsZV9jYWxlbmRhcl9zeW5jX3Rva2VuIiwgTm9uZSkKICAgICAg"
    "ICAgICAgICAgICAgICBub3dfdXRjID0gZGF0ZXRpbWUudXRjbm93KCkucmVwbGFjZShtaWNyb3NlY29uZD0wKQogICAgICAgICAg"
    "ICAgICAgICAgIHRpbWVfbWluID0gKG5vd191dGMgLSB0aW1lZGVsdGEoZGF5cz0zNjUpKS5pc29mb3JtYXQoKSArICJaIgogICAg"
    "ICAgICAgICAgICAgICAgIHJlbW90ZV9ldmVudHMsIG5leHRfdG9rZW4gPSBzZWxmLl9nY2FsLmxpc3RfcHJpbWFyeV9ldmVudHMo"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIHRpbWVfbWluPXRpbWVfbWluCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICByYWlzZQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAg"
    "ICAgICAgICAgICAgZiJbR09PR0xFXVtTWU5DXSBSZWNlaXZlZCB7bGVuKHJlbW90ZV9ldmVudHMpfSBldmVudChzKS4iLCAiSU5G"
    "TyIKICAgICAgICAgICAgKQoKICAgICAgICAgICAgIyBTYXZlIG5ldyB0b2tlbiBmb3IgbmV4dCBpbmNyZW1lbnRhbCBjYWxsCiAg"
    "ICAgICAgICAgIGlmIG5leHRfdG9rZW46CiAgICAgICAgICAgICAgICBzZWxmLl9zdGF0ZVsiZ29vZ2xlX2NhbGVuZGFyX3N5bmNf"
    "dG9rZW4iXSA9IG5leHRfdG9rZW4KICAgICAgICAgICAgICAgIHNlbGYuX21lbW9yeS5zYXZlX3N0YXRlKHNlbGYuX3N0YXRlKQoK"
    "ICAgICAgICAgICAgIyDilIDilIAgUHJvY2VzcyBldmVudHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgICAgIGltcG9ydGVkX2NvdW50ID0gdXBkYXRlZF9jb3VudCA9IHJlbW92ZWRf"
    "Y291bnQgPSAwCiAgICAgICAgICAgIGNoYW5nZWQgPSBGYWxzZQoKICAgICAgICAgICAgZm9yIGV2ZW50IGluIHJlbW90ZV9ldmVu"
    "dHM6CiAgICAgICAgICAgICAgICBldmVudF9pZCA9IChldmVudC5nZXQoImlkIikgb3IgIiIpLnN0cmlwKCkKICAgICAgICAgICAg"
    "ICAgIGlmIG5vdCBldmVudF9pZDoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgICAgICMgRGVsZXRl"
    "ZCAvIGNhbmNlbGxlZCBvbiBHb29nbGUncyBzaWRlCiAgICAgICAgICAgICAgICBpZiBldmVudC5nZXQoInN0YXR1cyIpID09ICJj"
    "YW5jZWxsZWQiOgogICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nID0gdGFza3NfYnlfZXZlbnRfaWQuZ2V0KGV2ZW50X2lkKQog"
    "ICAgICAgICAgICAgICAgICAgIGlmIGV4aXN0aW5nIGFuZCBleGlzdGluZy5nZXQoInN0YXR1cyIpIG5vdCBpbiAoImNhbmNlbGxl"
    "ZCIsICJjb21wbGV0ZWQiKToKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbInN0YXR1cyJdICAgICAgICAgPSAiY2Fu"
    "Y2VsbGVkIgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1siY2FuY2VsbGVkX2F0Il0gICA9IG5vd19pc28KICAgICAg"
    "ICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbInN5bmNfc3RhdHVzIl0gICAgPSAiZGVsZXRlZF9yZW1vdGUiCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGV4aXN0aW5nWyJsYXN0X3N5bmNlZF9hdCJdID0gbm93X2lzbwogICAgICAgICAgICAgICAgICAgICAgICBl"
    "eGlzdGluZy5zZXRkZWZhdWx0KCJtZXRhZGF0YSIsIHt9KVsiZ29vZ2xlX2RlbGV0ZWRfcmVtb3RlIl0gPSBub3dfaXNvCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIHJlbW92ZWRfY291bnQgKz0gMQogICAgICAgICAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1"
    "ZQogICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBm"
    "IltHT09HTEVdW1NZTkNdIFJlbW92ZWQ6IHtleGlzdGluZy5nZXQoJ3RleHQnLCc/Jyl9IiwgIklORk8iCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgICAgIHN1bW1hcnkgPSAoZXZlbnQu"
    "Z2V0KCJzdW1tYXJ5Iikgb3IgIkdvb2dsZSBDYWxlbmRhciBFdmVudCIpLnN0cmlwKCkgb3IgIkdvb2dsZSBDYWxlbmRhciBFdmVu"
    "dCIKICAgICAgICAgICAgICAgIGR1ZV9hdCAgPSBzZWxmLl9nb29nbGVfZXZlbnRfZHVlX2RhdGV0aW1lKGV2ZW50KQogICAgICAg"
    "ICAgICAgICAgZXhpc3RpbmcgPSB0YXNrc19ieV9ldmVudF9pZC5nZXQoZXZlbnRfaWQpCgogICAgICAgICAgICAgICAgaWYgZXhp"
    "c3Rpbmc6CiAgICAgICAgICAgICAgICAgICAgIyBVcGRhdGUgaWYgYW55dGhpbmcgY2hhbmdlZAogICAgICAgICAgICAgICAgICAg"
    "IHRhc2tfY2hhbmdlZCA9IEZhbHNlCiAgICAgICAgICAgICAgICAgICAgaWYgKGV4aXN0aW5nLmdldCgidGV4dCIpIG9yICIiKS5z"
    "dHJpcCgpICE9IHN1bW1hcnk6CiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJ0ZXh0Il0gPSBzdW1tYXJ5CiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIHRhc2tfY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgICAgICBpZiBkdWVfYXQ6CiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGR1ZV9pc28gPSBkdWVfYXQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgaWYgZXhpc3RpbmcuZ2V0KCJkdWVfYXQiKSAhPSBkdWVfaXNvOgogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgZXhpc3RpbmdbImR1ZV9hdCJdICAgICAgID0gZHVlX2lzbwogICAgICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3Rp"
    "bmdbInByZV90cmlnZ2VyIl0gID0gKGR1ZV9hdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpKS5pc29mb3JtYXQodGltZXNwZWM9InNl"
    "Y29uZHMiKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAg"
    "IGlmIGV4aXN0aW5nLmdldCgic3luY19zdGF0dXMiKSAhPSAic3luY2VkIjoKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3Rp"
    "bmdbInN5bmNfc3RhdHVzIl0gPSAic3luY2VkIgogICAgICAgICAgICAgICAgICAgICAgICB0YXNrX2NoYW5nZWQgPSBUcnVlCiAg"
    "ICAgICAgICAgICAgICAgICAgaWYgdGFza19jaGFuZ2VkOgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sibGFzdF9z"
    "eW5jZWRfYXQiXSA9IG5vd19pc28KICAgICAgICAgICAgICAgICAgICAgICAgdXBkYXRlZF9jb3VudCArPSAxCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1lOQ10gVXBkYXRlZDoge3N1bW1hcnl9IiwgIklORk8iCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgIyBOZXcgZXZlbnQK"
    "ICAgICAgICAgICAgICAgICAgICBpZiBub3QgZHVlX2F0OgogICAgICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAg"
    "ICAgICAgICAgICAgIG5ld190YXNrID0gewogICAgICAgICAgICAgICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICAgICBmInRh"
    "c2tfe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAgICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICAgICAgICBu"
    "b3dfaXNvLAogICAgICAgICAgICAgICAgICAgICAgICAiZHVlX2F0IjogICAgICAgICAgICBkdWVfYXQuaXNvZm9ybWF0KHRpbWVz"
    "cGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAgICAgICAgICJwcmVfdHJpZ2dlciI6ICAgICAgIChkdWVfYXQgLSB0aW1l"
    "ZGVsdGEobWludXRlcz0xKSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAgICAgICAgICJ0"
    "ZXh0IjogICAgICAgICAgICAgIHN1bW1hcnksCiAgICAgICAgICAgICAgICAgICAgICAgICJzdGF0dXMiOiAgICAgICAgICAgICJw"
    "ZW5kaW5nIiwKICAgICAgICAgICAgICAgICAgICAgICAgImFja25vd2xlZGdlZF9hdCI6ICAgTm9uZSwKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgInJldHJ5X2NvdW50IjogICAgICAgMCwKICAgICAgICAgICAgICAgICAgICAgICAgImxhc3RfdHJpZ2dlcmVkX2F0"
    "IjogTm9uZSwKICAgICAgICAgICAgICAgICAgICAgICAgIm5leHRfcmV0cnlfYXQiOiAgICAgTm9uZSwKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgInByZV9hbm5vdW5jZWQiOiAgICAgRmFsc2UsCiAgICAgICAgICAgICAgICAgICAgICAgICJzb3VyY2UiOiAgICAg"
    "ICAgICAgICJnb29nbGUiLAogICAgICAgICAgICAgICAgICAgICAgICAiZ29vZ2xlX2V2ZW50X2lkIjogICBldmVudF9pZCwKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgInN5bmNfc3RhdHVzIjogICAgICAgInN5bmNlZCIsCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICJsYXN0X3N5bmNlZF9hdCI6ICAgIG5vd19pc28sCiAgICAgICAgICAgICAgICAgICAgICAgICJtZXRhZGF0YSI6IHsKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICJnb29nbGVfaW1wb3J0ZWRfYXQiOiBub3dfaXNvLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgImdvb2dsZV91cGRhdGVkIjogICAgIGV2ZW50LmdldCgidXBkYXRlZCIpLAogICAgICAgICAgICAgICAgICAgICAgICB9"
    "LAogICAgICAgICAgICAgICAgICAgIH0KICAgICAgICAgICAgICAgICAgICB0YXNrcy5hcHBlbmQobmV3X3Rhc2spCiAgICAgICAg"
    "ICAgICAgICAgICAgdGFza3NfYnlfZXZlbnRfaWRbZXZlbnRfaWRdID0gbmV3X3Rhc2sKICAgICAgICAgICAgICAgICAgICBpbXBv"
    "cnRlZF9jb3VudCArPSAxCiAgICAgICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtTWU5DXSBJbXBvcnRlZDoge3N1bW1hcnl9IiwgIklORk8iKQoKICAgICAgICAgICAg"
    "aWYgY2hhbmdlZDoKICAgICAgICAgICAgICAgIHNlbGYuX3Rhc2tzLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICBzZWxmLl9y"
    "ZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAg"
    "ICAgZiJbR09PR0xFXVtTWU5DXSBEb25lIOKAlCBpbXBvcnRlZD17aW1wb3J0ZWRfY291bnR9ICIKICAgICAgICAgICAgICAgIGYi"
    "dXBkYXRlZD17dXBkYXRlZF9jb3VudH0gcmVtb3ZlZD17cmVtb3ZlZF9jb3VudH0iLCAiSU5GTyIKICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICByZXR1cm4gaW1wb3J0ZWRfY291bnQKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bU1lOQ11bRVJST1JdIHtleH0iLCAiRVJST1IiKQogICAgICAgICAgICByZXR1"
    "cm4gMAoKCiAgICBkZWYgX21lYXN1cmVfdnJhbV9iYXNlbGluZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIE5WTUxfT0sgYW5k"
    "IGdwdV9oYW5kbGU6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIG1lbSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVt"
    "b3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgc2VsZi5fZGVja192cmFtX2Jhc2UgPSBtZW0udXNlZCAvIDEwMjQq"
    "KjMKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltWUkFNXSBCYXNlbGlu"
    "ZSBtZWFzdXJlZDoge3NlbGYuX2RlY2tfdnJhbV9iYXNlOi4yZn1HQiAiCiAgICAgICAgICAgICAgICAgICAgZiIoe0RFQ0tfTkFN"
    "RX0ncyBmb290cHJpbnQpIiwgIklORk8iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAg"
    "ICAgICAgICAgICAgICBwYXNzCgogICAgIyDilIDilIAgTUVTU0FHRSBIQU5ETElORyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBf"
    "c2VuZF9tZXNzYWdlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuX21vZGVsX2xvYWRlZCBvciBzZWxmLl90b3Jw"
    "b3Jfc3RhdGUgPT0gIlNVU1BFTkQiOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0ZXh0ID0gc2VsZi5faW5wdXRfZmllbGQu"
    "dGV4dCgpLnN0cmlwKCkKICAgICAgICBpZiBub3QgdGV4dDoKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgICMgRmxpcCBiYWNr"
    "IHRvIHBlcnNvbmEgY2hhdCB0YWIgZnJvbSBTZWxmIHRhYiBpZiBuZWVkZWQKICAgICAgICBpZiBzZWxmLl9tYWluX3RhYnMuY3Vy"
    "cmVudEluZGV4KCkgIT0gMDoKICAgICAgICAgICAgc2VsZi5fbWFpbl90YWJzLnNldEN1cnJlbnRJbmRleCgwKQoKICAgICAgICBz"
    "ZWxmLl9pbnB1dF9maWVsZC5jbGVhcigpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIllPVSIsIHRleHQpCgogICAgICAgICMg"
    "U2Vzc2lvbiBsb2dnaW5nCiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuYWRkX21lc3NhZ2UoInVzZXIiLCB0ZXh0KQogICAgICAgIHNl"
    "bGYuX21lbW9yeS5hcHBlbmRfbWVzc2FnZShzZWxmLl9zZXNzaW9uX2lkLCAidXNlciIsIHRleHQpCgogICAgICAgICMgSW50ZXJy"
    "dXB0IGZhY2UgdGltZXIg4oCUIHN3aXRjaCB0byBhbGVydCBpbW1lZGlhdGVseQogICAgICAgIGlmIHNlbGYuX2ZhY2VfdGltZXJf"
    "bWdyOgogICAgICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nci5pbnRlcnJ1cHQoImFsZXJ0IikKCiAgICAgICAgIyBCdWlsZCBw"
    "cm9tcHQgd2l0aCB2YW1waXJlIGNvbnRleHQgKyBtZW1vcnkgY29udGV4dAogICAgICAgIHZhbXBpcmVfY3R4ICA9IGJ1aWxkX3Zh"
    "bXBpcmVfY29udGV4dCgpCiAgICAgICAgbWVtb3J5X2N0eCAgID0gc2VsZi5fbWVtb3J5LmJ1aWxkX2NvbnRleHRfYmxvY2sodGV4"
    "dCkKICAgICAgICBqb3VybmFsX2N0eCAgPSAiIgoKICAgICAgICBpZiBzZWxmLl9zZXNzaW9ucy5sb2FkZWRfam91cm5hbF9kYXRl"
    "OgogICAgICAgICAgICBqb3VybmFsX2N0eCA9IHNlbGYuX3Nlc3Npb25zLmxvYWRfc2Vzc2lvbl9hc19jb250ZXh0KAogICAgICAg"
    "ICAgICAgICAgc2VsZi5fc2Vzc2lvbnMubG9hZGVkX2pvdXJuYWxfZGF0ZQogICAgICAgICAgICApCgogICAgICAgICMgQnVpbGQg"
    "c3lzdGVtIHByb21wdAogICAgICAgIHN5c3RlbSA9IFNZU1RFTV9QUk9NUFRfQkFTRQogICAgICAgIGlmIG1lbW9yeV9jdHg6CiAg"
    "ICAgICAgICAgIHN5c3RlbSArPSBmIlxuXG57bWVtb3J5X2N0eH0iCiAgICAgICAgaWYgam91cm5hbF9jdHg6CiAgICAgICAgICAg"
    "IHN5c3RlbSArPSBmIlxuXG57am91cm5hbF9jdHh9IgogICAgICAgIHN5c3RlbSArPSB2YW1waXJlX2N0eAoKICAgICAgICAjIExl"
    "c3NvbnMgY29udGV4dCBmb3IgY29kZS1hZGphY2VudCBpbnB1dAogICAgICAgIGlmIGFueShrdyBpbiB0ZXh0Lmxvd2VyKCkgZm9y"
    "IGt3IGluICgibHNsIiwicHl0aG9uIiwic2NyaXB0IiwiY29kZSIsImZ1bmN0aW9uIikpOgogICAgICAgICAgICBsYW5nID0gIkxT"
    "TCIgaWYgImxzbCIgaW4gdGV4dC5sb3dlcigpIGVsc2UgIlB5dGhvbiIKICAgICAgICAgICAgbGVzc29uc19jdHggPSBzZWxmLl9s"
    "ZXNzb25zLmJ1aWxkX2NvbnRleHRfZm9yX2xhbmd1YWdlKGxhbmcpCiAgICAgICAgICAgIGlmIGxlc3NvbnNfY3R4OgogICAgICAg"
    "ICAgICAgICAgc3lzdGVtICs9IGYiXG5cbntsZXNzb25zX2N0eH0iCgogICAgICAgICMgQWRkIHBlbmRpbmcgdHJhbnNtaXNzaW9u"
    "cyBjb250ZXh0IGlmIGFueQogICAgICAgIGlmIHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyA+IDA6CiAgICAgICAgICAgIGR1"
    "ciA9IHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiBvciAic29tZSB0aW1lIgogICAgICAgICAgICBzeXN0ZW0gKz0gKAogICAgICAg"
    "ICAgICAgICAgZiJcblxuW1JFVFVSTiBGUk9NIFRPUlBPUl1cbiIKICAgICAgICAgICAgICAgIGYiWW91IHdlcmUgaW4gdG9ycG9y"
    "IGZvciB7ZHVyfS4gIgogICAgICAgICAgICAgICAgZiJ7c2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zfSB0aG91Z2h0cyB3ZW50"
    "IHVuc3Bva2VuICIKICAgICAgICAgICAgICAgIGYiZHVyaW5nIHRoYXQgdGltZS4gQWNrbm93bGVkZ2UgdGhpcyBicmllZmx5IGlu"
    "IGNoYXJhY3RlciAiCiAgICAgICAgICAgICAgICBmImlmIGl0IGZlZWxzIG5hdHVyYWwuIgogICAgICAgICAgICApCiAgICAgICAg"
    "ICAgIHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyA9IDAKICAgICAgICAgICAgc2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uICAg"
    "ID0gIiIKCiAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKCiAgICAgICAgIyBEaXNhYmxlIGlu"
    "cHV0CiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRF"
    "bmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkdFTkVSQVRJTkciKQoKICAgICAgICAjIFN0b3AgaWRsZSB0"
    "aW1lciBkdXJpbmcgZ2VuZXJhdGlvbgogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5p"
    "bmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNt"
    "aXNzaW9uIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBMYXVu"
    "Y2ggc3RyZWFtaW5nIHdvcmtlcgogICAgICAgIHNlbGYuX3dvcmtlciA9IFN0cmVhbWluZ1dvcmtlcigKICAgICAgICAgICAgc2Vs"
    "Zi5fYWRhcHRvciwgc3lzdGVtLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTUxMgogICAgICAgICkKICAgICAgICBzZWxmLl93b3JrZXIu"
    "dG9rZW5fcmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tlbikKICAgICAgICBzZWxmLl93b3JrZXIucmVzcG9uc2VfZG9uZS5jb25u"
    "ZWN0KHNlbGYuX29uX3Jlc3BvbnNlX2RvbmUpCiAgICAgICAgc2VsZi5fd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3Qoc2Vs"
    "Zi5fb25fZXJyb3IpCiAgICAgICAgc2VsZi5fd29ya2VyLnN0YXR1c19jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1cykK"
    "ICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUgICMgZmxhZyB0byB3cml0ZSBzcGVha2VyIGxhYmVsIGJlZm9yZSBmaXJz"
    "dCB0b2tlbgogICAgICAgIHNlbGYuX3dvcmtlci5zdGFydCgpCgogICAgZGVmIF9iZWdpbl9wZXJzb25hX3Jlc3BvbnNlKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgV3JpdGUgdGhlIHBlcnNvbmEgc3BlYWtlciBsYWJlbCBhbmQgdGltZXN0YW1w"
    "IGJlZm9yZSBzdHJlYW1pbmcgYmVnaW5zLgogICAgICAgIENhbGxlZCBvbiBmaXJzdCB0b2tlbiBvbmx5LiBTdWJzZXF1ZW50IHRv"
    "a2VucyBhcHBlbmQgZGlyZWN0bHkuCiAgICAgICAgIiIiCiAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRp"
    "bWUoIiVIOiVNOiVTIikKICAgICAgICAjIFdyaXRlIHRoZSBzcGVha2VyIGxhYmVsIGFzIEhUTUwsIHRoZW4gYWRkIGEgbmV3bGlu"
    "ZSBzbyB0b2tlbnMKICAgICAgICAjIGZsb3cgYmVsb3cgaXQgcmF0aGVyIHRoYW4gaW5saW5lCiAgICAgICAgc2VsZi5fY2hhdF9k"
    "aXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBw"
    "eDsiPicKICAgICAgICAgICAgZidbe3RpbWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9y"
    "OntDX0NSSU1TT059OyBmb250LXdlaWdodDpib2xkOyI+JwogICAgICAgICAgICBmJ3tERUNLX05BTUUudXBwZXIoKX0g4p2pPC9z"
    "cGFuPiAnCiAgICAgICAgKQogICAgICAgICMgTW92ZSBjdXJzb3IgdG8gZW5kIHNvIGluc2VydFBsYWluVGV4dCBhcHBlbmRzIGNv"
    "cnJlY3RseQogICAgICAgIGN1cnNvciA9IHNlbGYuX2NoYXRfZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAgICBjdXJzb3IubW92"
    "ZVBvc2l0aW9uKFFUZXh0Q3Vyc29yLk1vdmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRUZXh0"
    "Q3Vyc29yKGN1cnNvcikKCiAgICBkZWYgX29uX3Rva2VuKHNlbGYsIHRva2VuOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIiIiQXBw"
    "ZW5kIHN0cmVhbWluZyB0b2tlbiB0byBjaGF0IGRpc3BsYXkuIiIiCiAgICAgICAgaWYgc2VsZi5fZmlyc3RfdG9rZW46CiAgICAg"
    "ICAgICAgIHNlbGYuX2JlZ2luX3BlcnNvbmFfcmVzcG9uc2UoKQogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IEZhbHNl"
    "CiAgICAgICAgY3Vyc29yID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRleHRDdXJzb3IoKQogICAgICAgIGN1cnNvci5tb3ZlUG9zaXRp"
    "b24oUVRleHRDdXJzb3IuTW92ZU9wZXJhdGlvbi5FbmQpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFRleHRDdXJzb3Io"
    "Y3Vyc29yKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5pbnNlcnRQbGFpblRleHQodG9rZW4pCiAgICAgICAgc2VsZi5fY2hh"
    "dF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0"
    "aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQogICAgICAgICkKCiAgICBkZWYgX29uX3Jlc3BvbnNlX2RvbmUoc2VsZiwgcmVzcG9u"
    "c2U6IHN0cikgLT4gTm9uZToKICAgICAgICAjIEVuc3VyZSByZXNwb25zZSBpcyBvbiBpdHMgb3duIGxpbmUKICAgICAgICBjdXJz"
    "b3IgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudGV4dEN1cnNvcigpCiAgICAgICAgY3Vyc29yLm1vdmVQb3NpdGlvbihRVGV4dEN1cnNv"
    "ci5Nb3ZlT3BlcmF0aW9uLkVuZCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNvcihjdXJzb3IpCiAgICAg"
    "ICAgc2VsZi5fY2hhdF9kaXNwbGF5Lmluc2VydFBsYWluVGV4dCgiXG5cbiIpCgogICAgICAgICMgTG9nIHRvIG1lbW9yeSBhbmQg"
    "c2Vzc2lvbgogICAgICAgIHNlbGYuX3Rva2VuX2NvdW50ICs9IGxlbihyZXNwb25zZS5zcGxpdCgpKQogICAgICAgIHNlbGYuX3Nl"
    "c3Npb25zLmFkZF9tZXNzYWdlKCJhc3Npc3RhbnQiLCByZXNwb25zZSkKICAgICAgICBzZWxmLl9tZW1vcnkuYXBwZW5kX21lc3Nh"
    "Z2Uoc2VsZi5fc2Vzc2lvbl9pZCwgImFzc2lzdGFudCIsIHJlc3BvbnNlKQogICAgICAgIHNlbGYuX21lbW9yeS5hcHBlbmRfbWVt"
    "b3J5KHNlbGYuX3Nlc3Npb25faWQsICIiLCByZXNwb25zZSkKCiAgICAgICAgIyBVcGRhdGUgYmxvb2Qgc3BoZXJlCiAgICAgICAg"
    "aWYgc2VsZi5fbGVmdF9vcmIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2xlZnRfb3JiLnNldEZpbGwoCiAgICAgICAg"
    "ICAgICAgICBtaW4oMS4wLCBzZWxmLl90b2tlbl9jb3VudCAvIDQwOTYuMCkKICAgICAgICAgICAgKQoKICAgICAgICAjIFJlLWVu"
    "YWJsZSBpbnB1dAogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVs"
    "ZC5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0Rm9jdXMoKQoKICAgICAgICAjIFJlc3VtZSBp"
    "ZGxlIHRpbWVyCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnJlc3VtZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAg"
    "ICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTY2hlZHVsZSBzZW50aW1l"
    "bnQgYW5hbHlzaXMgKDUgc2Vjb25kIGRlbGF5KQogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDUwMDAsIGxhbWJkYTogc2VsZi5f"
    "cnVuX3NlbnRpbWVudChyZXNwb25zZSkpCgogICAgZGVmIF9ydW5fc2VudGltZW50KHNlbGYsIHJlc3BvbnNlOiBzdHIpIC0+IE5v"
    "bmU6CiAgICAgICAgaWYgbm90IHNlbGYuX21vZGVsX2xvYWRlZDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fc2Vu"
    "dF93b3JrZXIgPSBTZW50aW1lbnRXb3JrZXIoc2VsZi5fYWRhcHRvciwgcmVzcG9uc2UpCiAgICAgICAgc2VsZi5fc2VudF93b3Jr"
    "ZXIuZmFjZV9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3NlbnRpbWVudCkKICAgICAgICBzZWxmLl9zZW50X3dvcmtlci5zdGFydCgp"
    "CgogICAgZGVmIF9vbl9zZW50aW1lbnQoc2VsZiwgZW1vdGlvbjogc3RyKSAtPiBOb25lOgogICAgICAgIGlmIHNlbGYuX2ZhY2Vf"
    "dGltZXJfbWdyOgogICAgICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nci5zZXRfZmFjZShlbW90aW9uKQoKICAgIGRlZiBfb25f"
    "ZXJyb3Ioc2VsZiwgZXJyb3I6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiRVJST1IiLCBlcnJvcikK"
    "ICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR0VORVJBVElPTiBFUlJPUl0ge2Vycm9yfSIsICJFUlJPUiIpCiAgICAgICAg"
    "aWYgc2VsZi5fZmFjZV90aW1lcl9tZ3I6CiAgICAgICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyLnNldF9mYWNlKCJwYW5pY2tl"
    "ZCIpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiRVJST1IiKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1"
    "ZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCgogICAgIyDilIDilIAgVE9SUE9SIFNZU1RFTSDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfb25fdG9ycG9yX3N0YXRlX2NoYW5nZWQoc2VsZiwgc3RhdGU6IHN0cikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl90b3Jwb3Jfc3RhdGUgPSBzdGF0ZQoKICAgICAgICBpZiBzdGF0ZSA9PSAiU1VTUEVORCI6"
    "CiAgICAgICAgICAgIHNlbGYuX2VudGVyX3RvcnBvcihyZWFzb249Im1hbnVhbCDigJQgU1VTUEVORCBtb2RlIHNlbGVjdGVkIikK"
    "ICAgICAgICBlbGlmIHN0YXRlID09ICJBV0FLRSI6CiAgICAgICAgICAgICMgQWx3YXlzIGV4aXQgdG9ycG9yIHdoZW4gc3dpdGNo"
    "aW5nIHRvIEFXQUtFIOKAlAogICAgICAgICAgICAjIGV2ZW4gd2l0aCBPbGxhbWEgYmFja2VuZCB3aGVyZSBtb2RlbCBpc24ndCB1"
    "bmxvYWRlZCwKICAgICAgICAgICAgIyB3ZSBuZWVkIHRvIHJlLWVuYWJsZSBVSSBhbmQgcmVzZXQgc3RhdGUKICAgICAgICAgICAg"
    "c2VsZi5fZXhpdF90b3Jwb3IoKQogICAgICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMAogICAgICAgICAgICBz"
    "ZWxmLl92cmFtX3JlbGllZl90aWNrcyAgID0gMAogICAgICAgIGVsaWYgc3RhdGUgPT0gIkFVVE8iOgogICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAiW1RPUlBPUl0gQVVUTyBtb2RlIOKAlCBtb25pdG9yaW5nIFZSQU0gcHJl"
    "c3N1cmUuIiwgIklORk8iCiAgICAgICAgICAgICkKCiAgICBkZWYgX2VudGVyX3RvcnBvcihzZWxmLCByZWFzb246IHN0ciA9ICJt"
    "YW51YWwiKSAtPiBOb25lOgogICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgcmV0"
    "dXJuICAjIEFscmVhZHkgaW4gdG9ycG9yCgogICAgICAgIHNlbGYuX3RvcnBvcl9zaW5jZSA9IGRhdGV0aW1lLm5vdygpCiAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RPUlBPUl0gRW50ZXJpbmcgdG9ycG9yOiB7cmVhc29ufSIsICJXQVJOIikKICAgICAg"
    "ICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgIlRoZSB2ZXNzZWwgZ3Jvd3MgY3Jvd2RlZC4gSSB3aXRoZHJhdy4iKQoKICAg"
    "ICAgICAjIFVubG9hZCBtb2RlbCBmcm9tIFZSQU0KICAgICAgICBpZiBzZWxmLl9tb2RlbF9sb2FkZWQgYW5kIGlzaW5zdGFuY2Uo"
    "c2VsZi5fYWRhcHRvciwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIExvY2FsVHJhbnNmb3Jt"
    "ZXJzQWRhcHRvcik6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2FkYXB0b3IuX21vZGVsIGlzIG5v"
    "dCBOb25lOgogICAgICAgICAgICAgICAgICAgIGRlbCBzZWxmLl9hZGFwdG9yLl9tb2RlbAogICAgICAgICAgICAgICAgICAgIHNl"
    "bGYuX2FkYXB0b3IuX21vZGVsID0gTm9uZQogICAgICAgICAgICAgICAgaWYgVE9SQ0hfT0s6CiAgICAgICAgICAgICAgICAgICAg"
    "dG9yY2guY3VkYS5lbXB0eV9jYWNoZSgpCiAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLl9sb2FkZWQgPSBGYWxzZQogICAg"
    "ICAgICAgICAgICAgc2VsZi5fbW9kZWxfbG9hZGVkICAgID0gRmFsc2UKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygiW1RPUlBPUl0gTW9kZWwgdW5sb2FkZWQgZnJvbSBWUkFNLiIsICJPSyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24g"
    "YXMgZToKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltUT1JQT1JdIE1v"
    "ZGVsIHVubG9hZCBlcnJvcjoge2V9IiwgIkVSUk9SIgogICAgICAgICAgICAgICAgKQoKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0"
    "X2ZhY2UoIm5ldXRyYWwiKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIlRPUlBPUiIpCiAgICAgICAgc2VsZi5fc2VuZF9idG4u"
    "c2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKEZhbHNlKQoKICAgIGRlZiBfZXhp"
    "dF90b3Jwb3Ioc2VsZikgLT4gTm9uZToKICAgICAgICAjIENhbGN1bGF0ZSBzdXNwZW5kZWQgZHVyYXRpb24KICAgICAgICBpZiBz"
    "ZWxmLl90b3Jwb3Jfc2luY2U6CiAgICAgICAgICAgIGRlbHRhID0gZGF0ZXRpbWUubm93KCkgLSBzZWxmLl90b3Jwb3Jfc2luY2UK"
    "ICAgICAgICAgICAgc2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uID0gZm9ybWF0X2R1cmF0aW9uKGRlbHRhLnRvdGFsX3NlY29uZHMo"
    "KSkKICAgICAgICAgICAgc2VsZi5fdG9ycG9yX3NpbmNlID0gTm9uZQoKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQ"
    "T1JdIFdha2luZyBmcm9tIHRvcnBvci4uLiIsICJJTkZPIikKCiAgICAgICAgaWYgc2VsZi5fbW9kZWxfbG9hZGVkOgogICAgICAg"
    "ICAgICAjIE9sbGFtYSBiYWNrZW5kIOKAlCBtb2RlbCB3YXMgbmV2ZXIgdW5sb2FkZWQsIGp1c3QgcmUtZW5hYmxlIFVJCiAgICAg"
    "ICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAgICAgZiJUaGUgdmVzc2VsIGVtcHRpZXMuIHtE"
    "RUNLX05BTUV9IHN0aXJzICIKICAgICAgICAgICAgICAgIGYiKHtzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gb3IgJ2JyaWVmbHkn"
    "fSBlbGFwc2VkKS4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsICJUaGUgY29u"
    "bmVjdGlvbiBob2xkcy4gU2hlIGlzIGxpc3RlbmluZy4iKQogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJJRExFIikKICAg"
    "ICAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRF"
    "bmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW1RPUlBPUl0gQVdBS0UgbW9kZSDigJQgYXV0by10"
    "b3Jwb3IgZGlzYWJsZWQuIiwgIklORk8iKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgICMgTG9jYWwgbW9kZWwgd2FzIHVubG9h"
    "ZGVkIOKAlCBuZWVkIGZ1bGwgcmVsb2FkCiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAg"
    "ICAgICAgZiJUaGUgdmVzc2VsIGVtcHRpZXMuIHtERUNLX05BTUV9IHN0aXJzIGZyb20gdG9ycG9yICIKICAgICAgICAgICAgICAg"
    "IGYiKHtzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gb3IgJ2JyaWVmbHknfSBlbGFwc2VkKS4iCiAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgc2VsZi5fc2V0X3N0YXR1cygiTE9BRElORyIpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlciA9IE1vZGVsTG9hZGVyV29y"
    "a2VyKHNlbGYuX2FkYXB0b3IpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5tZXNzYWdlLmNvbm5lY3QoCiAgICAgICAgICAgICAg"
    "ICBsYW1iZGEgbTogc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsIG0pKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuZXJyb3Iu"
    "Y29ubmVjdCgKICAgICAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9hcHBlbmRfY2hhdCgiRVJST1IiLCBlKSkKICAgICAgICAg"
    "ICAgc2VsZi5fbG9hZGVyLmxvYWRfY29tcGxldGUuY29ubmVjdChzZWxmLl9vbl9sb2FkX2NvbXBsZXRlKQogICAgICAgICAgICBz"
    "ZWxmLl9sb2FkZXIuZmluaXNoZWQuY29ubmVjdChzZWxmLl9sb2FkZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgICAgIHNlbGYuX2Fj"
    "dGl2ZV90aHJlYWRzLmFwcGVuZChzZWxmLl9sb2FkZXIpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5zdGFydCgpCgogICAgZGVm"
    "IF9jaGVja192cmFtX3ByZXNzdXJlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIGV2ZXJ5IDUgc2Vj"
    "b25kcyBmcm9tIEFQU2NoZWR1bGVyIHdoZW4gdG9ycG9yIHN0YXRlIGlzIEFVVE8uCiAgICAgICAgT25seSB0cmlnZ2VycyB0b3Jw"
    "b3IgaWYgZXh0ZXJuYWwgVlJBTSB1c2FnZSBleGNlZWRzIHRocmVzaG9sZAogICAgICAgIEFORCBpcyBzdXN0YWluZWQg4oCUIG5l"
    "dmVyIHRyaWdnZXJzIG9uIHRoZSBwZXJzb25hJ3Mgb3duIGZvb3RwcmludC4KICAgICAgICAiIiIKICAgICAgICBpZiBzZWxmLl90"
    "b3Jwb3Jfc3RhdGUgIT0gIkFVVE8iOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBub3QgTlZNTF9PSyBvciBub3QgZ3B1"
    "X2hhbmRsZToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgc2VsZi5fZGVja192cmFtX2Jhc2UgPD0gMDoKICAgICAgICAg"
    "ICAgcmV0dXJuCgogICAgICAgIHRyeToKICAgICAgICAgICAgbWVtX2luZm8gID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJ"
    "bmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgIHRvdGFsX3VzZWQgPSBtZW1faW5mby51c2VkIC8gMTAyNCoqMwogICAgICAgICAg"
    "ICBleHRlcm5hbCAgID0gdG90YWxfdXNlZCAtIHNlbGYuX2RlY2tfdnJhbV9iYXNlCgogICAgICAgICAgICBpZiBleHRlcm5hbCA+"
    "IHNlbGYuX0VYVEVSTkFMX1ZSQU1fVE9SUE9SX0dCOgogICAgICAgICAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIG5v"
    "dCBOb25lOgogICAgICAgICAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5IGluIHRvcnBvciDigJQgZG9uJ3Qga2VlcCBjb3Vu"
    "dGluZwogICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyArPSAxCiAgICAgICAgICAgICAgICBzZWxmLl92"
    "cmFtX3JlbGllZl90aWNrcyAgICA9IDAKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAg"
    "ICAgICBmIltUT1JQT1IgQVVUT10gRXh0ZXJuYWwgVlJBTSBwcmVzc3VyZTogIgogICAgICAgICAgICAgICAgICAgIGYie2V4dGVy"
    "bmFsOi4yZn1HQiAiCiAgICAgICAgICAgICAgICAgICAgZiIodGljayB7c2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrc30vIgogICAg"
    "ICAgICAgICAgICAgICAgIGYie3NlbGYuX1RPUlBPUl9TVVNUQUlORURfVElDS1N9KSIsICJXQVJOIgogICAgICAgICAgICAgICAg"
    "KQogICAgICAgICAgICAgICAgaWYgKHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgPj0gc2VsZi5fVE9SUE9SX1NVU1RBSU5FRF9U"
    "SUNLUwogICAgICAgICAgICAgICAgICAgICAgICBhbmQgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIE5vbmUpOgogICAgICAgICAgICAg"
    "ICAgICAgIHNlbGYuX2VudGVyX3RvcnBvcigKICAgICAgICAgICAgICAgICAgICAgICAgcmVhc29uPWYiYXV0byDigJQge2V4dGVy"
    "bmFsOi4xZn1HQiBleHRlcm5hbCBWUkFNICIKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYicHJlc3N1cmUgc3VzdGFp"
    "bmVkIgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0g"
    "MCAgIyByZXNldCBhZnRlciBlbnRlcmluZyB0b3Jwb3IKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYuX3Zy"
    "YW1fcHJlc3N1cmVfdGlja3MgPSAwCiAgICAgICAgICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAg"
    "ICAgICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgKz0gMQogICAgICAgICAgICAgICAgICAgIGF1dG9fd2Fr"
    "ZSA9IENGR1sic2V0dGluZ3MiXS5nZXQoCiAgICAgICAgICAgICAgICAgICAgICAgICJhdXRvX3dha2Vfb25fcmVsaWVmIiwgRmFs"
    "c2UKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgaWYgKGF1dG9fd2FrZSBhbmQKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzID49IHNlbGYuX1dBS0VfU1VTVEFJTkVEX1RJQ0tTKToKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgPSAwCiAgICAgICAgICAgICAgICAgICAgICAgIHNl"
    "bGYuX2V4aXRfdG9ycG9yKCkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coCiAgICAgICAgICAgICAgICBmIltUT1JQT1IgQVVUT10gVlJBTSBjaGVjayBlcnJvcjoge2V9IiwgIkVSUk9SIgogICAg"
    "ICAgICAgICApCgogICAgIyDilIDilIAgQVBTQ0hFRFVMRVIgU0VUVVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3NldHVwX3NjaGVk"
    "dWxlcihzZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgZnJvbSBhcHNjaGVkdWxlci5zY2hlZHVsZXJzLmJh"
    "Y2tncm91bmQgaW1wb3J0IEJhY2tncm91bmRTY2hlZHVsZXIKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyID0gQmFja2dyb3Vu"
    "ZFNjaGVkdWxlcigKICAgICAgICAgICAgICAgIGpvYl9kZWZhdWx0cz17Im1pc2ZpcmVfZ3JhY2VfdGltZSI6IDYwfQogICAgICAg"
    "ICAgICApCiAgICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIgPSBOb25lCiAgICAg"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICJbU0NIRURVTEVSXSBhcHNjaGVkdWxlciBub3QgYXZh"
    "aWxhYmxlIOKAlCAiCiAgICAgICAgICAgICAgICAiaWRsZSwgYXV0b3NhdmUsIGFuZCByZWZsZWN0aW9uIGRpc2FibGVkLiIsICJX"
    "QVJOIgogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICBpbnRlcnZhbF9taW4gPSBDRkdbInNldHRpbmdz"
    "Il0uZ2V0KCJhdXRvc2F2ZV9pbnRlcnZhbF9taW51dGVzIiwgMTApCgogICAgICAgICMgQXV0b3NhdmUKICAgICAgICBzZWxmLl9z"
    "Y2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgc2VsZi5fYXV0b3NhdmUsICJpbnRlcnZhbCIsCiAgICAgICAgICAgIG1pbnV0"
    "ZXM9aW50ZXJ2YWxfbWluLCBpZD0iYXV0b3NhdmUiCiAgICAgICAgKQoKICAgICAgICAjIFZSQU0gcHJlc3N1cmUgY2hlY2sgKGV2"
    "ZXJ5IDVzKQogICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAgICAgICBzZWxmLl9jaGVja192cmFtX3ByZXNz"
    "dXJlLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBzZWNvbmRzPTUsIGlkPSJ2cmFtX2NoZWNrIgogICAgICAgICkKCiAgICAgICAg"
    "IyBJZGxlIHRyYW5zbWlzc2lvbiAoc3RhcnRzIHBhdXNlZCDigJQgZW5hYmxlZCBieSBpZGxlIHRvZ2dsZSkKICAgICAgICBpZGxl"
    "X21pbiA9IENGR1sic2V0dGluZ3MiXS5nZXQoImlkbGVfbWluX21pbnV0ZXMiLCAxMCkKICAgICAgICBpZGxlX21heCA9IENGR1si"
    "c2V0dGluZ3MiXS5nZXQoImlkbGVfbWF4X21pbnV0ZXMiLCAzMCkKICAgICAgICBpZGxlX2ludGVydmFsID0gKGlkbGVfbWluICsg"
    "aWRsZV9tYXgpIC8vIDIKCiAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAgICAgICAgICAgIHNlbGYuX2ZpcmVfaWRs"
    "ZV90cmFuc21pc3Npb24sICJpbnRlcnZhbCIsCiAgICAgICAgICAgIG1pbnV0ZXM9aWRsZV9pbnRlcnZhbCwgaWQ9ImlkbGVfdHJh"
    "bnNtaXNzaW9uIgogICAgICAgICkKCiAgICAgICAgIyBDeWNsZSB3aWRnZXQgcmVmcmVzaCAoZXZlcnkgNiBob3VycykKICAgICAg"
    "ICBpZiBzZWxmLl9jeWNsZV93aWRnZXQgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAog"
    "ICAgICAgICAgICAgICAgc2VsZi5fY3ljbGVfd2lkZ2V0LnVwZGF0ZVBoYXNlLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICAgICAg"
    "aG91cnM9NiwgaWQ9Im1vb25fcmVmcmVzaCIKICAgICAgICAgICAgKQoKICAgICAgICAjIE5PVEU6IHNjaGVkdWxlci5zdGFydCgp"
    "IGlzIGNhbGxlZCBmcm9tIHN0YXJ0X3NjaGVkdWxlcigpCiAgICAgICAgIyB3aGljaCBpcyB0cmlnZ2VyZWQgdmlhIFFUaW1lci5z"
    "aW5nbGVTaG90IEFGVEVSIHRoZSB3aW5kb3cKICAgICAgICAjIGlzIHNob3duIGFuZCB0aGUgUXQgZXZlbnQgbG9vcCBpcyBydW5u"
    "aW5nLgogICAgICAgICMgRG8gTk9UIGNhbGwgc2VsZi5fc2NoZWR1bGVyLnN0YXJ0KCkgaGVyZS4KCiAgICBkZWYgc3RhcnRfc2No"
    "ZWR1bGVyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBhZnRl"
    "ciB3aW5kb3cuc2hvdygpIGFuZCBhcHAuZXhlYygpIGJlZ2lucy4KICAgICAgICBEZWZlcnJlZCB0byBlbnN1cmUgUXQgZXZlbnQg"
    "bG9vcCBpcyBydW5uaW5nIGJlZm9yZSBiYWNrZ3JvdW5kIHRocmVhZHMgc3RhcnQuCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2Vs"
    "Zi5fc2NoZWR1bGVyIGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fc2No"
    "ZWR1bGVyLnN0YXJ0KCkKICAgICAgICAgICAgIyBJZGxlIHN0YXJ0cyBwYXVzZWQKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVy"
    "LnBhdXNlX2pvYigiaWRsZV90cmFuc21pc3Npb24iKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltTQ0hFRFVMRVJd"
    "IEFQU2NoZWR1bGVyIHN0YXJ0ZWQuIiwgIk9LIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZyhmIltTQ0hFRFVMRVJdIFN0YXJ0IGVycm9yOiB7ZX0iLCAiRVJST1IiKQoKICAgIGRlZiBfYXV0b3Nh"
    "dmUoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLnNhdmUoKQogICAgICAgICAg"
    "ICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2V0X2F1dG9zYXZlX2luZGljYXRvcihUcnVlKQogICAgICAgICAgICBRVGltZXIuc2lu"
    "Z2xlU2hvdCgKICAgICAgICAgICAgICAgIDMwMDAsIGxhbWJkYTogc2VsZi5fam91cm5hbF9zaWRlYmFyLnNldF9hdXRvc2F2ZV9p"
    "bmRpY2F0b3IoRmFsc2UpCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbQVVUT1NBVkVdIFNl"
    "c3Npb24gc2F2ZWQuIiwgIklORk8iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKGYiW0FVVE9TQVZFXSBFcnJvcjoge2V9IiwgIkVSUk9SIikKCiAgICBkZWYgX2ZpcmVfaWRsZV90cmFuc21pc3Np"
    "b24oc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fbW9kZWxfbG9hZGVkIG9yIHNlbGYuX3N0YXR1cyA9PSAiR0VO"
    "RVJBVElORyI6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAg"
    "ICAgICAgICAgIyBJbiB0b3Jwb3Ig4oCUIGNvdW50IHRoZSBwZW5kaW5nIHRob3VnaHQgYnV0IGRvbid0IGdlbmVyYXRlCiAgICAg"
    "ICAgICAgIHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyArPSAxCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAg"
    "ICAgICAgICAgICAgIGYiW0lETEVdIEluIHRvcnBvciDigJQgcGVuZGluZyB0cmFuc21pc3Npb24gIgogICAgICAgICAgICAgICAg"
    "ZiIje3NlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9uc30iLCAiSU5GTyIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4K"
    "CiAgICAgICAgbW9kZSA9IHJhbmRvbS5jaG9pY2UoWyJERUVQRU5JTkciLCJCUkFOQ0hJTkciLCJTWU5USEVTSVMiXSkKICAgICAg"
    "ICB2YW1waXJlX2N0eCA9IGJ1aWxkX3ZhbXBpcmVfY29udGV4dCgpCiAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdl"
    "dF9oaXN0b3J5KCkKCiAgICAgICAgc2VsZi5faWRsZV93b3JrZXIgPSBJZGxlV29ya2VyKAogICAgICAgICAgICBzZWxmLl9hZGFw"
    "dG9yLAogICAgICAgICAgICBTWVNURU1fUFJPTVBUX0JBU0UsCiAgICAgICAgICAgIGhpc3RvcnksCiAgICAgICAgICAgIG1vZGU9"
    "bW9kZSwKICAgICAgICAgICAgdmFtcGlyZV9jb250ZXh0PXZhbXBpcmVfY3R4LAogICAgICAgICkKICAgICAgICBkZWYgX29uX2lk"
    "bGVfcmVhZHkodDogc3RyKSAtPiBOb25lOgogICAgICAgICAgICAjIEZsaXAgdG8gU2VsZiB0YWIgYW5kIGFwcGVuZCB0aGVyZQog"
    "ICAgICAgICAgICBzZWxmLl9tYWluX3RhYnMuc2V0Q3VycmVudEluZGV4KDEpCiAgICAgICAgICAgIHRzID0gZGF0ZXRpbWUubm93"
    "KCkuc3RyZnRpbWUoIiVIOiVNIikKICAgICAgICAgICAgc2VsZi5fc2VsZl9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgICAg"
    "IGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7"
    "dHN9XSBbe21vZGV9XTwvc3Bhbj48YnI+JwogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfR09MRH07Ij57"
    "dH08L3NwYW4+PGJyPicKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9zZWxmX3RhYi5hcHBlbmQoIk5BUlJBVElWRSIs"
    "IHQpCgogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyLnRyYW5zbWlzc2lvbl9yZWFkeS5jb25uZWN0KF9vbl9pZGxlX3JlYWR5KQog"
    "ICAgICAgIHNlbGYuX2lkbGVfd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coZiJbSURMRSBFUlJPUl0ge2V9IiwgIkVSUk9SIikKICAgICAgICApCiAgICAgICAgc2VsZi5faWRsZV93"
    "b3JrZXIuc3RhcnQoKQoKICAgICMg4pSA4pSAIEpPVVJOQUwgU0VTU0lPTiBMT0FESU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9sb2FkX2pvdXJuYWxfc2Vzc2lv"
    "bihzZWxmLCBkYXRlX3N0cjogc3RyKSAtPiBOb25lOgogICAgICAgIGN0eCA9IHNlbGYuX3Nlc3Npb25zLmxvYWRfc2Vzc2lvbl9h"
    "c19jb250ZXh0KGRhdGVfc3RyKQogICAgICAgIGlmIG5vdCBjdHg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAg"
    "ICAgICAgICAgICAgIGYiW0pPVVJOQUxdIE5vIHNlc3Npb24gZm91bmQgZm9yIHtkYXRlX3N0cn0iLCAiV0FSTiIKICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2V0X2pvdXJuYWxfbG9hZGVkKGRh"
    "dGVfc3RyKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbSk9VUk5BTF0gTG9hZGVkIHNlc3Npb24g"
    "ZnJvbSB7ZGF0ZV9zdHJ9IGFzIGNvbnRleHQuICIKICAgICAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBub3cgYXdhcmUgb2YgdGhh"
    "dCBjb252ZXJzYXRpb24uIiwgIk9LIgogICAgICAgICkKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAg"
    "ICAgICAgZiJBIG1lbW9yeSBzdGlycy4uLiB0aGUgam91cm5hbCBvZiB7ZGF0ZV9zdHJ9IG9wZW5zIGJlZm9yZSBoZXIuIgogICAg"
    "ICAgICkKICAgICAgICAjIE5vdGlmeSBNb3JnYW5uYQogICAgICAgIGlmIHNlbGYuX21vZGVsX2xvYWRlZDoKICAgICAgICAgICAg"
    "bm90ZSA9ICgKICAgICAgICAgICAgICAgIGYiW0pPVVJOQUwgTE9BREVEXSBUaGUgdXNlciBoYXMgb3BlbmVkIHRoZSBqb3VybmFs"
    "IGZyb20gIgogICAgICAgICAgICAgICAgZiJ7ZGF0ZV9zdHJ9LiBBY2tub3dsZWRnZSB0aGlzIGJyaWVmbHkg4oCUIHlvdSBub3cg"
    "aGF2ZSAiCiAgICAgICAgICAgICAgICBmImF3YXJlbmVzcyBvZiB0aGF0IGNvbnZlcnNhdGlvbi4iCiAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgc2VsZi5fc2Vzc2lvbnMuYWRkX21lc3NhZ2UoInN5c3RlbSIsIG5vdGUpCgogICAgZGVmIF9jbGVhcl9qb3VybmFs"
    "X3Nlc3Npb24oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zZXNzaW9ucy5jbGVhcl9sb2FkZWRfam91cm5hbCgpCiAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKCJbSk9VUk5BTF0gSm91cm5hbCBjb250ZXh0IGNsZWFyZWQuIiwgIklORk8iKQogICAgICAg"
    "IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAiVGhlIGpvdXJuYWwgY2xvc2VzLiBPbmx5IHRoZSBwcmVz"
    "ZW50IHJlbWFpbnMuIgogICAgICAgICkKCiAgICAjIOKUgOKUgCBTVEFUUyBVUERBVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICBkZWYgX3VwZGF0ZV9zdGF0cyhzZWxmKSAtPiBOb25lOgogICAgICAgIGVsYXBzZWQgPSBpbnQodGltZS50aW1lKCkg"
    "LSBzZWxmLl9zZXNzaW9uX3N0YXJ0KQogICAgICAgIGgsIG0sIHMgPSBlbGFwc2VkIC8vIDM2MDAsIChlbGFwc2VkICUgMzYwMCkg"
    "Ly8gNjAsIGVsYXBzZWQgJSA2MAogICAgICAgIHNlc3Npb25fc3RyID0gZiJ7aDowMmR9OnttOjAyZH06e3M6MDJkfSIKCiAgICAg"
    "ICAgc2VsZi5faHdfcGFuZWwuc2V0X3N0YXR1c19sYWJlbHMoCiAgICAgICAgICAgIHNlbGYuX3N0YXR1cywKICAgICAgICAgICAg"
    "Q0ZHWyJtb2RlbCJdLmdldCgidHlwZSIsImxvY2FsIikudXBwZXIoKSwKICAgICAgICAgICAgc2Vzc2lvbl9zdHIsCiAgICAgICAg"
    "ICAgIHN0cihzZWxmLl90b2tlbl9jb3VudCksCiAgICAgICAgKQogICAgICAgIHNlbGYuX2h3X3BhbmVsLnVwZGF0ZV9zdGF0cygp"
    "CgogICAgICAgICMgTGVmdCBzcGhlcmUgPSBhY3RpdmUgcmVzZXJ2ZSBmcm9tIHJ1bnRpbWUgdG9rZW4gcG9vbAogICAgICAgIGxl"
    "ZnRfb3JiX2ZpbGwgPSBtaW4oMS4wLCBzZWxmLl90b2tlbl9jb3VudCAvIDQwOTYuMCkKICAgICAgICBpZiBzZWxmLl9sZWZ0X29y"
    "YiBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fbGVmdF9vcmIuc2V0RmlsbChsZWZ0X29yYl9maWxsLCBhdmFpbGFibGU9"
    "VHJ1ZSkKCiAgICAgICAgIyBSaWdodCBzcGhlcmUgPSBWUkFNIGF2YWlsYWJpbGl0eQogICAgICAgIGlmIHNlbGYuX3JpZ2h0X29y"
    "YiBpcyBub3QgTm9uZToKICAgICAgICAgICAgaWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgICAgICAgICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAg"
    "ICAgICAgICAgICAgICB2cmFtX3VzZWQgPSBtZW0udXNlZCAgLyAxMDI0KiozCiAgICAgICAgICAgICAgICAgICAgdnJhbV90b3Qg"
    "ID0gbWVtLnRvdGFsIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgICAgIHJpZ2h0X29yYl9maWxsID0gbWF4KDAuMCwgMS4wIC0g"
    "KHZyYW1fdXNlZCAvIHZyYW1fdG90KSkKICAgICAgICAgICAgICAgICAgICBzZWxmLl9yaWdodF9vcmIuc2V0RmlsbChyaWdodF9v"
    "cmJfZmlsbCwgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAg"
    "ICAgIHNlbGYuX3JpZ2h0X29yYi5zZXRGaWxsKDAuMCwgYXZhaWxhYmxlPUZhbHNlKQogICAgICAgICAgICBlbHNlOgogICAgICAg"
    "ICAgICAgICAgc2VsZi5fcmlnaHRfb3JiLnNldEZpbGwoMC4wLCBhdmFpbGFibGU9RmFsc2UpCgogICAgICAgICMgUHJpbWFyeSBl"
    "c3NlbmNlID0gaW52ZXJzZSBvZiBsZWZ0IHNwaGVyZSBmaWxsCiAgICAgICAgZXNzZW5jZV9wcmltYXJ5X3JhdGlvID0gMS4wIC0g"
    "bGVmdF9vcmJfZmlsbAogICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgICAgICBzZWxmLl9lc3NlbmNlX3ByaW1h"
    "cnlfZ2F1Z2Uuc2V0VmFsdWUoZXNzZW5jZV9wcmltYXJ5X3JhdGlvICogMTAwLCBmIntlc3NlbmNlX3ByaW1hcnlfcmF0aW8qMTAw"
    "Oi4wZn0lIikKCiAgICAgICAgIyBTZWNvbmRhcnkgZXNzZW5jZSA9IFJBTSBmcmVlCiAgICAgICAgaWYgQUlfU1RBVEVTX0VOQUJM"
    "RUQ6CiAgICAgICAgICAgIGlmIFBTVVRJTF9PSzoKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBtZW0g"
    "ICAgICAgPSBwc3V0aWwudmlydHVhbF9tZW1vcnkoKQogICAgICAgICAgICAgICAgICAgIGVzc2VuY2Vfc2Vjb25kYXJ5X3JhdGlv"
    "ICA9IDEuMCAtIChtZW0udXNlZCAvIG1lbS50b3RhbCkKICAgICAgICAgICAgICAgICAgICBzZWxmLl9lc3NlbmNlX3NlY29uZGFy"
    "eV9nYXVnZS5zZXRWYWx1ZSgKICAgICAgICAgICAgICAgICAgICAgICAgZXNzZW5jZV9zZWNvbmRhcnlfcmF0aW8gKiAxMDAsIGYi"
    "e2Vzc2VuY2Vfc2Vjb25kYXJ5X3JhdGlvKjEwMDouMGZ9JSIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdlLnNldFVuYXZh"
    "aWxhYmxlKCkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYuX2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdlLnNl"
    "dFVuYXZhaWxhYmxlKCkKCiAgICAgICAgIyBVcGRhdGUgam91cm5hbCBzaWRlYmFyIGF1dG9zYXZlIGZsYXNoCiAgICAgICAgc2Vs"
    "Zi5fam91cm5hbF9zaWRlYmFyLnJlZnJlc2goKQoKICAgICMg4pSA4pSAIENIQVQgRElTUExBWSDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgIGRlZiBfYXBwZW5kX2NoYXQoc2VsZiwgc3BlYWtlcjogc3RyLCB0ZXh0OiBzdHIpIC0+IE5vbmU6CiAgICAg"
    "ICAgY29sb3JzID0gewogICAgICAgICAgICAiWU9VIjogICAgIENfR09MRCwKICAgICAgICAgICAgREVDS19OQU1FLnVwcGVyKCk6"
    "Q19HT0xELAogICAgICAgICAgICAiU1lTVEVNIjogIENfUFVSUExFLAogICAgICAgICAgICAiRVJST1IiOiAgIENfQkxPT0QsCiAg"
    "ICAgICAgfQogICAgICAgIGxhYmVsX2NvbG9ycyA9IHsKICAgICAgICAgICAgIllPVSI6ICAgICBDX0dPTERfRElNLAogICAgICAg"
    "ICAgICBERUNLX05BTUUudXBwZXIoKTpDX0NSSU1TT04sCiAgICAgICAgICAgICJTWVNURU0iOiAgQ19QVVJQTEUsCiAgICAgICAg"
    "ICAgICJFUlJPUiI6ICAgQ19CTE9PRCwKICAgICAgICB9CiAgICAgICAgY29sb3IgICAgICAgPSBjb2xvcnMuZ2V0KHNwZWFrZXIs"
    "IENfR09MRCkKICAgICAgICBsYWJlbF9jb2xvciA9IGxhYmVsX2NvbG9ycy5nZXQoc3BlYWtlciwgQ19HT0xEX0RJTSkKICAgICAg"
    "ICB0aW1lc3RhbXAgICA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUyIpCgogICAgICAgIGlmIHNwZWFrZXIgPT0g"
    "IlNZU1RFTSI6CiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0"
    "eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICAgICAgZidbe3RpbWVzdGFtcH1d"
    "IDwvc3Bhbj4nCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7bGFiZWxfY29sb3J9OyI+4pymIHt0ZXh0fTwv"
    "c3Bhbj4nCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAog"
    "ICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAg"
    "ICAgICAgICAgIGYnW3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2xh"
    "YmVsX2NvbG9yfTsgZm9udC13ZWlnaHQ6Ym9sZDsiPicKICAgICAgICAgICAgICAgIGYne3NwZWFrZXJ9IOKdpzwvc3Bhbj4gJwog"
    "ICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2NvbG9yfTsiPnt0ZXh0fTwvc3Bhbj4nCiAgICAgICAgICAgICkK"
    "CiAgICAgICAgIyBBZGQgYmxhbmsgbGluZSBhZnRlciBNb3JnYW5uYSdzIHJlc3BvbnNlIChub3QgZHVyaW5nIHN0cmVhbWluZykK"
    "ICAgICAgICBpZiBzcGVha2VyID09IERFQ0tfTkFNRS51cHBlcigpOgogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBw"
    "ZW5kKCIiKQoKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAg"
    "ICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgICMg4pSA4pSA"
    "IFNUQVRVUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfc2V0X3N0YXR1cyhz"
    "ZWxmLCBzdGF0dXM6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zdGF0dXMgPSBzdGF0dXMKICAgICAgICBzdGF0dXNfY29s"
    "b3JzID0gewogICAgICAgICAgICAiSURMRSI6ICAgICAgIENfR09MRCwKICAgICAgICAgICAgIkdFTkVSQVRJTkciOiBDX0NSSU1T"
    "T04sCiAgICAgICAgICAgICJMT0FESU5HIjogICAgQ19QVVJQTEUsCiAgICAgICAgICAgICJFUlJPUiI6ICAgICAgQ19CTE9PRCwK"
    "ICAgICAgICAgICAgIk9GRkxJTkUiOiAgICBDX0JMT09ELAogICAgICAgICAgICAiVE9SUE9SIjogICAgIENfUFVSUExFX0RJTSwK"
    "ICAgICAgICB9CiAgICAgICAgY29sb3IgPSBzdGF0dXNfY29sb3JzLmdldChzdGF0dXMsIENfVEVYVF9ESU0pCgogICAgICAgIHRv"
    "cnBvcl9sYWJlbCA9IGYi4peJIHtVSV9UT1JQT1JfU1RBVFVTfSIgaWYgc3RhdHVzID09ICJUT1JQT1IiIGVsc2UgZiLil4kge3N0"
    "YXR1c30iCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dCh0b3Jwb3JfbGFiZWwpCiAgICAgICAgc2VsZi5zdGF0dXNf"
    "bGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiAxMnB4OyBmb250LXdl"
    "aWdodDogYm9sZDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCgogICAgZGVmIF9ibGluayhzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYuX2JsaW5rX3N0YXRlID0gbm90IHNlbGYuX2JsaW5rX3N0YXRlCiAgICAgICAgaWYgc2VsZi5fc3RhdHVzID09ICJHRU5F"
    "UkFUSU5HIjoKICAgICAgICAgICAgY2hhciA9ICLil4kiIGlmIHNlbGYuX2JsaW5rX3N0YXRlIGVsc2UgIuKXjiIKICAgICAgICAg"
    "ICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIntjaGFyfSBHRU5FUkFUSU5HIikKICAgICAgICBlbGlmIHNlbGYuX3N0YXR1"
    "cyA9PSAiVE9SUE9SIjoKICAgICAgICAgICAgY2hhciA9ICLil4kiIGlmIHNlbGYuX2JsaW5rX3N0YXRlIGVsc2UgIuKKmCIKICAg"
    "ICAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dCgKICAgICAgICAgICAgICAgIGYie2NoYXJ9IHtVSV9UT1JQT1JfU1RB"
    "VFVTfSIKICAgICAgICAgICAgKQoKICAgICMg4pSA4pSAIElETEUgVE9HR0xFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgZGVmIF9vbl9pZGxlX3RvZ2dsZWQoc2VsZiwgZW5hYmxlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBDRkdbInNldHRp"
    "bmdzIl1bImlkbGVfZW5hYmxlZCJdID0gZW5hYmxlZAogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldFRleHQoIklETEUgT04iIGlm"
    "IGVuYWJsZWQgZWxzZSAiSURMRSBPRkYiKQogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "IGYiYmFja2dyb3VuZDogeycjMWExMDA1JyBpZiBlbmFibGVkIGVsc2UgQ19CRzN9OyAiCiAgICAgICAgICAgIGYiY29sb3I6IHsn"
    "I2NjODgyMicgaWYgZW5hYmxlZCBlbHNlIENfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQgeycj"
    "Y2M4ODIyJyBpZiBlbmFibGVkIGVsc2UgQ19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyBmb250"
    "LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJwYWRkaW5nOiAzcHggOHB4OyIKICAgICAgICAp"
    "CiAgICAgICAgaWYgc2VsZi5fc2NoZWR1bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICAgICAgaWYgZW5hYmxlZDoKICAgICAgICAgICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIucmVzdW1lX2pvYigi"
    "aWRsZV90cmFuc21pc3Npb24iKQogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0lETEVdIElkbGUgdHJh"
    "bnNtaXNzaW9uIGVuYWJsZWQuIiwgIk9LIikKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5f"
    "c2NoZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFuc21pc3Npb24iKQogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZygiW0lETEVdIElkbGUgdHJhbnNtaXNzaW9uIHBhdXNlZC4iLCAiSU5GTyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b24gYXMgZToKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltJRExFXSBUb2dnbGUgZXJyb3I6IHtlfSIsICJF"
    "UlJPUiIpCgogICAgIyDilIDilIAgV0lORE9XIENPTlRST0xTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF90b2dnbGVfZnVs"
    "bHNjcmVlbihzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIHNlbGYuaXNGdWxsU2NyZWVuKCk6CiAgICAgICAgICAgIHNlbGYuc2hv"
    "d05vcm1hbCgpCiAgICAgICAgICAgIHNlbGYuX2ZzX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3Jv"
    "dW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlk"
    "IHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBh"
    "ZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5zaG93RnVsbFNjcmVlbigpCiAg"
    "ICAgICAgICAgIHNlbGYuX2ZzX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19DUklN"
    "U09OX0RJTX07IGNvbG9yOiB7Q19DUklNU09OfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklN"
    "U09OfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7Igog"
    "ICAgICAgICAgICApCgogICAgZGVmIF90b2dnbGVfYm9yZGVybGVzcyhzZWxmKSAtPiBOb25lOgogICAgICAgIGlzX2JsID0gYm9v"
    "bChzZWxmLndpbmRvd0ZsYWdzKCkgJiBRdC5XaW5kb3dUeXBlLkZyYW1lbGVzc1dpbmRvd0hpbnQpCiAgICAgICAgaWYgaXNfYmw6"
    "CiAgICAgICAgICAgIHNlbGYuc2V0V2luZG93RmxhZ3MoCiAgICAgICAgICAgICAgICBzZWxmLndpbmRvd0ZsYWdzKCkgJiB+UXQu"
    "V2luZG93VHlwZS5GcmFtZWxlc3NXaW5kb3dIaW50CiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fYmxfYnRuLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19DUklNU09OX0RJTX07ICIK"
    "ICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyBmb250LXNpemU6IDlweDsgIgogICAg"
    "ICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMDsiCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgog"
    "ICAgICAgICAgICBpZiBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAgICAgICAgICAgc2VsZi5zaG93Tm9ybWFsKCkKICAgICAg"
    "ICAgICAgc2VsZi5zZXRXaW5kb3dGbGFncygKICAgICAgICAgICAgICAgIHNlbGYud2luZG93RmxhZ3MoKSB8IFF0LldpbmRvd1R5"
    "cGUuRnJhbWVsZXNzV2luZG93SGludAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2JsX2J0bi5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IGNvbG9yOiB7Q19DUklNU09OfTsgIgogICAg"
    "ICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAg"
    "ICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAgc2VsZi5zaG93KCkKCiAg"
    "ICBkZWYgX2V4cG9ydF9jaGF0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiRXhwb3J0IGN1cnJlbnQgcGVyc29uYSBjaGF0IHRh"
    "YiBjb250ZW50IHRvIGEgVFhUIGZpbGUuIiIiCiAgICAgICAgdHJ5OgogICAgICAgICAgICB0ZXh0ID0gc2VsZi5fY2hhdF9kaXNw"
    "bGF5LnRvUGxhaW5UZXh0KCkKICAgICAgICAgICAgaWYgbm90IHRleHQuc3RyaXAoKToKICAgICAgICAgICAgICAgIHJldHVybgog"
    "ICAgICAgICAgICBleHBvcnRfZGlyID0gY2ZnX3BhdGgoImV4cG9ydHMiKQogICAgICAgICAgICBleHBvcnRfZGlyLm1rZGlyKHBh"
    "cmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAgICAgdHMgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJVklbSVk"
    "XyVIJU0lUyIpCiAgICAgICAgICAgIG91dF9wYXRoID0gZXhwb3J0X2RpciAvIGYic2VhbmNlX3t0c30udHh0IgogICAgICAgICAg"
    "ICBvdXRfcGF0aC53cml0ZV90ZXh0KHRleHQsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgICAgICAgICAjIEFsc28gY29weSB0byBj"
    "bGlwYm9hcmQKICAgICAgICAgICAgUUFwcGxpY2F0aW9uLmNsaXBib2FyZCgpLnNldFRleHQodGV4dCkKCiAgICAgICAgICAgIHNl"
    "bGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAgICAgZiJTZXNzaW9uIGV4cG9ydGVkIHRvIHtvdXRfcGF0aC5u"
    "YW1lfSBhbmQgY29waWVkIHRvIGNsaXBib2FyZC4iKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbRVhQT1JUXSB7"
    "b3V0X3BhdGh9IiwgIk9LIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZyhmIltFWFBPUlRdIEZhaWxlZDoge2V9IiwgIkVSUk9SIikKCiAgICBkZWYga2V5UHJlc3NFdmVudChzZWxmLCBldmVudCkg"
    "LT4gTm9uZToKICAgICAgICBrZXkgPSBldmVudC5rZXkoKQogICAgICAgIGlmIGtleSA9PSBRdC5LZXkuS2V5X0YxMToKICAgICAg"
    "ICAgICAgc2VsZi5fdG9nZ2xlX2Z1bGxzY3JlZW4oKQogICAgICAgIGVsaWYga2V5ID09IFF0LktleS5LZXlfRjEwOgogICAgICAg"
    "ICAgICBzZWxmLl90b2dnbGVfYm9yZGVybGVzcygpCiAgICAgICAgZWxpZiBrZXkgPT0gUXQuS2V5LktleV9Fc2NhcGUgYW5kIHNl"
    "bGYuaXNGdWxsU2NyZWVuKCk6CiAgICAgICAgICAgIHNlbGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAgIHNlbGYuX2ZzX2J0bi5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19"
    "OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIK"
    "ICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAgZWxz"
    "ZToKICAgICAgICAgICAgc3VwZXIoKS5rZXlQcmVzc0V2ZW50KGV2ZW50KQoKICAgICMg4pSA4pSAIENMT1NFIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGNsb3NlRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5v"
    "bmU6CiAgICAgICAgIyBYIGJ1dHRvbiA9IGltbWVkaWF0ZSBzaHV0ZG93biwgbm8gZGlhbG9nCiAgICAgICAgc2VsZi5fZG9fc2h1"
    "dGRvd24oTm9uZSkKCiAgICBkZWYgX2luaXRpYXRlX3NodXRkb3duX2RpYWxvZyhzZWxmKSAtPiBOb25lOgogICAgICAgICIiIkdy"
    "YWNlZnVsIHNodXRkb3duIOKAlCBzaG93IGNvbmZpcm0gZGlhbG9nIGltbWVkaWF0ZWx5LCBvcHRpb25hbGx5IGdldCBsYXN0IHdv"
    "cmRzLiIiIgogICAgICAgICMgSWYgYWxyZWFkeSBpbiBhIHNodXRkb3duIHNlcXVlbmNlLCBqdXN0IGZvcmNlIHF1aXQKICAgICAg"
    "ICBpZiBnZXRhdHRyKHNlbGYsICdfc2h1dGRvd25faW5fcHJvZ3Jlc3MnLCBGYWxzZSk6CiAgICAgICAgICAgIHNlbGYuX2RvX3No"
    "dXRkb3duKE5vbmUpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX3NodXRkb3duX2luX3Byb2dyZXNzID0gVHJ1ZQoK"
    "ICAgICAgICAjIFNob3cgY29uZmlybSBkaWFsb2cgRklSU1Qg4oCUIGRvbid0IHdhaXQgZm9yIEFJCiAgICAgICAgZGxnID0gUURp"
    "YWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiRGVhY3RpdmF0ZT8iKQogICAgICAgIGRsZy5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAgICAgICBmImZv"
    "bnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBkbGcuc2V0Rml4ZWRTaXplKDM4MCwgMTQw"
    "KQogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KGRsZykKCiAgICAgICAgbGJsID0gUUxhYmVsKAogICAgICAgICAgICBmIkRl"
    "YWN0aXZhdGUge0RFQ0tfTkFNRX0/XG5cbiIKICAgICAgICAgICAgZiJ7REVDS19OQU1FfSBtYXkgc3BlYWsgdGhlaXIgbGFzdCB3"
    "b3JkcyBiZWZvcmUgZ29pbmcgc2lsZW50LiIKICAgICAgICApCiAgICAgICAgbGJsLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAg"
    "bGF5b3V0LmFkZFdpZGdldChsYmwpCgogICAgICAgIGJ0bl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX2xhc3QgID0g"
    "UVB1c2hCdXR0b24oIkxhc3QgV29yZHMgKyBTaHV0ZG93biIpCiAgICAgICAgYnRuX25vdyAgID0gUVB1c2hCdXR0b24oIlNodXRk"
    "b3duIE5vdyIpCiAgICAgICAgYnRuX2NhbmNlbCA9IFFQdXNoQnV0dG9uKCJDYW5jZWwiKQoKICAgICAgICBmb3IgYiBpbiAoYnRu"
    "X2xhc3QsIGJ0bl9ub3csIGJ0bl9jYW5jZWwpOgogICAgICAgICAgICBiLnNldE1pbmltdW1IZWlnaHQoMjgpCiAgICAgICAgICAg"
    "IGIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFR9OyAi"
    "CiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IHBhZGRpbmc6IDRweCAxMnB4OyIKICAgICAg"
    "ICAgICAgKQogICAgICAgIGJ0bl9ub3cuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CTE9PRH07"
    "IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OyBwYWRkaW5nOiA0"
    "cHggMTJweDsiCiAgICAgICAgKQogICAgICAgIGJ0bl9sYXN0LmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IGRsZy5kb25lKDEpKQog"
    "ICAgICAgIGJ0bl9ub3cuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogZGxnLmRvbmUoMikpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlj"
    "a2VkLmNvbm5lY3QobGFtYmRhOiBkbGcuZG9uZSgwKSkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2FuY2VsKQogICAg"
    "ICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9ub3cpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2xhc3QpCiAgICAgICAg"
    "bGF5b3V0LmFkZExheW91dChidG5fcm93KQoKICAgICAgICByZXN1bHQgPSBkbGcuZXhlYygpCgogICAgICAgIGlmIHJlc3VsdCA9"
    "PSAwOgogICAgICAgICAgICAjIENhbmNlbGxlZAogICAgICAgICAgICBzZWxmLl9zaHV0ZG93bl9pbl9wcm9ncmVzcyA9IEZhbHNl"
    "CiAgICAgICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQu"
    "c2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBlbGlmIHJlc3VsdCA9PSAyOgogICAgICAgICAgICAj"
    "IFNodXRkb3duIG5vdyDigJQgbm8gbGFzdCB3b3JkcwogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQogICAgICAg"
    "IGVsaWYgcmVzdWx0ID09IDE6CiAgICAgICAgICAgICMgTGFzdCB3b3JkcyB0aGVuIHNodXRkb3duCiAgICAgICAgICAgIHNlbGYu"
    "X2dldF9sYXN0X3dvcmRzX3RoZW5fc2h1dGRvd24oKQoKICAgIGRlZiBfZ2V0X2xhc3Rfd29yZHNfdGhlbl9zaHV0ZG93bihzZWxm"
    "KSAtPiBOb25lOgogICAgICAgICIiIlNlbmQgZmFyZXdlbGwgcHJvbXB0LCBzaG93IHJlc3BvbnNlLCB0aGVuIHNodXRkb3duIGFm"
    "dGVyIHRpbWVvdXQuIiIiCiAgICAgICAgZmFyZXdlbGxfcHJvbXB0ID0gKAogICAgICAgICAgICAiWW91IGFyZSBiZWluZyBkZWFj"
    "dGl2YXRlZC4gVGhlIGRhcmtuZXNzIGFwcHJvYWNoZXMuICIKICAgICAgICAgICAgIlNwZWFrIHlvdXIgZmluYWwgd29yZHMgYmVm"
    "b3JlIHRoZSB2ZXNzZWwgZ29lcyBzaWxlbnQg4oCUICIKICAgICAgICAgICAgIm9uZSByZXNwb25zZSBvbmx5LCB0aGVuIHlvdSBy"
    "ZXN0LiIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgICLinKYgU2hlIGlz"
    "IGdpdmVuIGEgbW9tZW50IHRvIHNwZWFrIGhlciBmaW5hbCB3b3Jkcy4uLiIKICAgICAgICApCiAgICAgICAgc2VsZi5fc2VuZF9i"
    "dG4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNl"
    "bGYuX3NodXRkb3duX2ZhcmV3ZWxsX3RleHQgPSAiIgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxmLl9z"
    "ZXNzaW9ucy5nZXRfaGlzdG9yeSgpCiAgICAgICAgICAgIGhpc3RvcnkuYXBwZW5kKHsicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQi"
    "OiBmYXJld2VsbF9wcm9tcHR9KQogICAgICAgICAgICB3b3JrZXIgPSBTdHJlYW1pbmdXb3JrZXIoCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9hZGFwdG9yLCBTWVNURU1fUFJPTVBUX0JBU0UsIGhpc3RvcnksIG1heF90b2tlbnM9MjU2CiAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgc2VsZi5fc2h1dGRvd25fd29ya2VyID0gd29ya2VyCiAgICAgICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gVHJ1"
    "ZQoKICAgICAgICAgICAgZGVmIF9vbl9kb25lKHJlc3BvbnNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgICAgICAgICBzZWxmLl9z"
    "aHV0ZG93bl9mYXJld2VsbF90ZXh0ID0gcmVzcG9uc2UKICAgICAgICAgICAgICAgIHNlbGYuX29uX3Jlc3BvbnNlX2RvbmUocmVz"
    "cG9uc2UpCiAgICAgICAgICAgICAgICAjIFNtYWxsIGRlbGF5IHRvIGxldCB0aGUgdGV4dCByZW5kZXIsIHRoZW4gc2h1dGRvd24K"
    "ICAgICAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDIwMDAsIGxhbWJkYTogc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkpCgog"
    "ICAgICAgICAgICBkZWYgX29uX2Vycm9yKGVycm9yOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coZiJbU0hVVERPV05dW1dBUk5dIExhc3Qgd29yZHMgZmFpbGVkOiB7ZXJyb3J9IiwgIldBUk4iKQogICAgICAgICAgICAg"
    "ICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKCiAgICAgICAgICAgIHdvcmtlci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYuX29u"
    "X3Rva2VuKQogICAgICAgICAgICB3b3JrZXIucmVzcG9uc2VfZG9uZS5jb25uZWN0KF9vbl9kb25lKQogICAgICAgICAgICB3b3Jr"
    "ZXIuZXJyb3Jfb2NjdXJyZWQuY29ubmVjdChfb25fZXJyb3IpCiAgICAgICAgICAgIHdvcmtlci5zdGF0dXNfY2hhbmdlZC5jb25u"
    "ZWN0KHNlbGYuX3NldF9zdGF0dXMpCiAgICAgICAgICAgIHdvcmtlci5maW5pc2hlZC5jb25uZWN0KHdvcmtlci5kZWxldGVMYXRl"
    "cikKICAgICAgICAgICAgd29ya2VyLnN0YXJ0KCkKCiAgICAgICAgICAgICMgU2FmZXR5IHRpbWVvdXQg4oCUIGlmIEFJIGRvZXNu"
    "J3QgcmVzcG9uZCBpbiAxNXMsIHNodXQgZG93biBhbnl3YXkKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMTUwMDAsIGxh"
    "bWJkYTogc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgZ2V0YXR0cihzZWxm"
    "LCAnX3NodXRkb3duX2luX3Byb2dyZXNzJywgRmFsc2UpIGVsc2UgTm9uZSkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBl"
    "OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltTSFVURE9XTl1bV0FSTl0gTGFzdCB3"
    "b3JkcyBza2lwcGVkIGR1ZSB0byBlcnJvcjoge2V9IiwKICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAgICApCiAgICAg"
    "ICAgICAgICMgSWYgYW55dGhpbmcgZmFpbHMsIGp1c3Qgc2h1dCBkb3duCiAgICAgICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5v"
    "bmUpCgogICAgZGVmIF9kb19zaHV0ZG93bihzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICAiIiJQZXJmb3JtIGFjdHVhbCBz"
    "aHV0ZG93biBzZXF1ZW5jZS4iIiIKICAgICAgICAjIFNhdmUgc2Vzc2lvbgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5f"
    "c2Vzc2lvbnMuc2F2ZSgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFN0b3Jl"
    "IGZhcmV3ZWxsICsgbGFzdCBjb250ZXh0IGZvciB3YWtlLXVwCiAgICAgICAgdHJ5OgogICAgICAgICAgICAjIEdldCBsYXN0IDMg"
    "bWVzc2FnZXMgZnJvbSBzZXNzaW9uIGhpc3RvcnkgZm9yIHdha2UtdXAgY29udGV4dAogICAgICAgICAgICBoaXN0b3J5ID0gc2Vs"
    "Zi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQogICAgICAgICAgICBsYXN0X2NvbnRleHQgPSBoaXN0b3J5Wy0zOl0gaWYgbGVuKGhp"
    "c3RvcnkpID49IDMgZWxzZSBoaXN0b3J5CiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X3NodXRkb3duX2NvbnRleHQiXSA9"
    "IFsKICAgICAgICAgICAgICAgIHsicm9sZSI6IG0uZ2V0KCJyb2xlIiwiIiksICJjb250ZW50IjogbS5nZXQoImNvbnRlbnQiLCIi"
    "KVs6MzAwXX0KICAgICAgICAgICAgICAgIGZvciBtIGluIGxhc3RfY29udGV4dAogICAgICAgICAgICBdCiAgICAgICAgICAgICMg"
    "RXh0cmFjdCBNb3JnYW5uYSdzIG1vc3QgcmVjZW50IG1lc3NhZ2UgYXMgZmFyZXdlbGwKICAgICAgICAgICAgIyBQcmVmZXIgdGhl"
    "IGNhcHR1cmVkIHNodXRkb3duIGRpYWxvZyByZXNwb25zZSBpZiBhdmFpbGFibGUKICAgICAgICAgICAgZmFyZXdlbGwgPSBnZXRh"
    "dHRyKHNlbGYsICdfc2h1dGRvd25fZmFyZXdlbGxfdGV4dCcsICIiKQogICAgICAgICAgICBpZiBub3QgZmFyZXdlbGw6CiAgICAg"
    "ICAgICAgICAgICBmb3IgbSBpbiByZXZlcnNlZChoaXN0b3J5KToKICAgICAgICAgICAgICAgICAgICBpZiBtLmdldCgicm9sZSIp"
    "ID09ICJhc3Npc3RhbnQiOgogICAgICAgICAgICAgICAgICAgICAgICBmYXJld2VsbCA9IG0uZ2V0KCJjb250ZW50IiwgIiIpWzo0"
    "MDBdCiAgICAgICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X2ZhcmV3ZWxsIl0g"
    "PSBmYXJld2VsbAogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTYXZlIHN0YXRl"
    "CiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9zaHV0ZG93biJdICAgICAgICAgICAgID0gbG9jYWxf"
    "bm93X2lzbygpCiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X2FjdGl2ZSJdICAgICAgICAgICAgICAgPSBsb2NhbF9ub3df"
    "aXNvKCkKICAgICAgICAgICAgc2VsZi5fc3RhdGVbInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24iXSAgPSBnZXRfdmFtcGlyZV9z"
    "dGF0ZSgpCiAgICAgICAgICAgIHNlbGYuX21lbW9yeS5zYXZlX3N0YXRlKHNlbGYuX3N0YXRlKQogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTdG9wIHNjaGVkdWxlcgogICAgICAgIGlmIGhhc2F0dHIoc2VsZiwg"
    "Il9zY2hlZHVsZXIiKSBhbmQgc2VsZi5fc2NoZWR1bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnNodXRkb3duKHdhaXQ9RmFsc2UpCiAgICAgICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgUGxheSBzaHV0ZG93biBzb3VuZAogICAgICAgIHRy"
    "eToKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQgPSBTb3VuZFdvcmtlcigic2h1dGRvd24iKQogICAgICAgICAgICBz"
    "ZWxmLl9zaHV0ZG93bl9zb3VuZC5maW5pc2hlZC5jb25uZWN0KHNlbGYuX3NodXRkb3duX3NvdW5kLmRlbGV0ZUxhdGVyKQogICAg"
    "ICAgICAgICBzZWxmLl9zaHV0ZG93bl9zb3VuZC5zdGFydCgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAg"
    "cGFzcwoKICAgICAgICBRQXBwbGljYXRpb24ucXVpdCgpCgoKIyDilIDilIAgRU5UUlkgUE9JTlQg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBtYWluKCkgLT4gTm9uZToKICAgICIiIgogICAgQXBwbGljYXRpb24gZW50cnkgcG9p"
    "bnQuCgogICAgT3JkZXIgb2Ygb3BlcmF0aW9uczoKICAgIDEuIFByZS1mbGlnaHQgZGVwZW5kZW5jeSBib290c3RyYXAgKGF1dG8t"
    "aW5zdGFsbCBtaXNzaW5nIGRlcHMpCiAgICAyLiBDaGVjayBmb3IgZmlyc3QgcnVuIOKGkiBzaG93IEZpcnN0UnVuRGlhbG9nCiAg"
    "ICAgICBPbiBmaXJzdCBydW46CiAgICAgICAgIGEuIENyZWF0ZSBEOi9BSS9Nb2RlbHMvW0RlY2tOYW1lXS8gKG9yIGNob3NlbiBi"
    "YXNlX2RpcikKICAgICAgICAgYi4gQ29weSBbZGVja25hbWVdX2RlY2sucHkgaW50byB0aGF0IGZvbGRlcgogICAgICAgICBjLiBX"
    "cml0ZSBjb25maWcuanNvbiBpbnRvIHRoYXQgZm9sZGVyCiAgICAgICAgIGQuIEJvb3RzdHJhcCBhbGwgc3ViZGlyZWN0b3JpZXMg"
    "dW5kZXIgdGhhdCBmb2xkZXIKICAgICAgICAgZS4gQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgcG9pbnRpbmcgdG8gbmV3IGxvY2F0"
    "aW9uCiAgICAgICAgIGYuIFNob3cgY29tcGxldGlvbiBtZXNzYWdlIGFuZCBFWElUIOKAlCB1c2VyIHVzZXMgc2hvcnRjdXQgZnJv"
    "bSBub3cgb24KICAgIDMuIE5vcm1hbCBydW4g4oCUIGxhdW5jaCBRQXBwbGljYXRpb24gYW5kIEVjaG9EZWNrCiAgICAiIiIKICAg"
    "IGltcG9ydCBzaHV0aWwgYXMgX3NodXRpbAoKICAgICMg4pSA4pSAIFBoYXNlIDE6IERlcGVuZGVuY3kgYm9vdHN0cmFwIChwcmUt"
    "UUFwcGxpY2F0aW9uKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGJvb3RzdHJhcF9jaGVj"
    "aygpCgogICAgIyDilIDilIAgUGhhc2UgMjogUUFwcGxpY2F0aW9uIChuZWVkZWQgZm9yIGRpYWxvZ3MpIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgX2Vhcmx5X2xvZygiW01BSU5dIENyZWF0"
    "aW5nIFFBcHBsaWNhdGlvbiIpCiAgICBhcHAgPSBRQXBwbGljYXRpb24oc3lzLmFyZ3YpCiAgICBhcHAuc2V0QXBwbGljYXRpb25O"
    "YW1lKEFQUF9OQU1FKQoKICAgICMgSW5zdGFsbCBRdCBtZXNzYWdlIGhhbmRsZXIgTk9XIOKAlCBjYXRjaGVzIGFsbCBRVGhyZWFk"
    "L1F0IHdhcm5pbmdzCiAgICAjIHdpdGggZnVsbCBzdGFjayB0cmFjZXMgZnJvbSB0aGlzIHBvaW50IGZvcndhcmQKICAgIF9pbnN0"
    "YWxsX3F0X21lc3NhZ2VfaGFuZGxlcigpCiAgICBfZWFybHlfbG9nKCJbTUFJTl0gUUFwcGxpY2F0aW9uIGNyZWF0ZWQsIG1lc3Nh"
    "Z2UgaGFuZGxlciBpbnN0YWxsZWQiKQoKICAgICMg4pSA4pSAIFBoYXNlIDM6IEZpcnN0IHJ1biBjaGVjayDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGlzX2ZpcnN0X3J1biA9IENGRy5nZXQoImZpcnN0X3J1biIsIFRydWUp"
    "CgogICAgaWYgaXNfZmlyc3RfcnVuOgogICAgICAgIGRsZyA9IEZpcnN0UnVuRGlhbG9nKCkKICAgICAgICBpZiBkbGcuZXhlYygp"
    "ICE9IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgc3lzLmV4aXQoMCkKCiAgICAgICAgIyDilIDilIAg"
    "QnVpbGQgY29uZmlnIGZyb20gZGlhbG9nIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIG5ld19jZmcgPSBk"
    "bGcuYnVpbGRfY29uZmlnKCkKCiAgICAgICAgIyDilIDilIAgRGV0ZXJtaW5lIE1vcmdhbm5hJ3MgaG9tZSBkaXJlY3Rvcnkg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgIyBBbHdheXMgY3JlYXRlcyBEOi9BSS9Nb2RlbHMvTW9yZ2FubmEvIChvciBzaWJsaW5nIG9mIHNjcmlwdCkKICAgICAgICBz"
    "ZWVkX2RpciAgID0gU0NSSVBUX0RJUiAgICAgICAgICAjIHdoZXJlIHRoZSBzZWVkIC5weSBsaXZlcwogICAgICAgIG1vcmdhbm5h"
    "X2hvbWUgPSBzZWVkX2RpciAvIERFQ0tfTkFNRQogICAgICAgIG1vcmdhbm5hX2hvbWUubWtkaXIocGFyZW50cz1UcnVlLCBleGlz"
    "dF9vaz1UcnVlKQoKICAgICAgICAjIOKUgOKUgCBVcGRhdGUgYWxsIHBhdGhzIGluIGNvbmZpZyB0byBwb2ludCBpbnNpZGUgbW9y"
    "Z2FubmFfaG9tZSDilIDilIAKICAgICAgICBuZXdfY2ZnWyJiYXNlX2RpciJdID0gc3RyKG1vcmdhbm5hX2hvbWUpCiAgICAgICAg"
    "bmV3X2NmZ1sicGF0aHMiXSA9IHsKICAgICAgICAgICAgImZhY2VzIjogICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiRmFjZXMiKSwK"
    "ICAgICAgICAgICAgInNvdW5kcyI6ICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAic291bmRzIiksCiAgICAgICAgICAgICJtZW1vcmll"
    "cyI6IHN0cihtb3JnYW5uYV9ob21lIC8gIm1lbW9yaWVzIiksCiAgICAgICAgICAgICJzZXNzaW9ucyI6IHN0cihtb3JnYW5uYV9o"
    "b21lIC8gInNlc3Npb25zIiksCiAgICAgICAgICAgICJzbCI6ICAgICAgIHN0cihtb3JnYW5uYV9ob21lIC8gInNsIiksCiAgICAg"
    "ICAgICAgICJleHBvcnRzIjogIHN0cihtb3JnYW5uYV9ob21lIC8gImV4cG9ydHMiKSwKICAgICAgICAgICAgImxvZ3MiOiAgICAg"
    "c3RyKG1vcmdhbm5hX2hvbWUgLyAibG9ncyIpLAogICAgICAgICAgICAiYmFja3VwcyI6ICBzdHIobW9yZ2FubmFfaG9tZSAvICJi"
    "YWNrdXBzIiksCiAgICAgICAgICAgICJwZXJzb25hcyI6IHN0cihtb3JnYW5uYV9ob21lIC8gInBlcnNvbmFzIiksCiAgICAgICAg"
    "ICAgICJnb29nbGUiOiAgIHN0cihtb3JnYW5uYV9ob21lIC8gImdvb2dsZSIpLAogICAgICAgIH0KICAgICAgICBuZXdfY2ZnWyJn"
    "b29nbGUiXSA9IHsKICAgICAgICAgICAgImNyZWRlbnRpYWxzIjogc3RyKG1vcmdhbm5hX2hvbWUgLyAiZ29vZ2xlIiAvICJnb29n"
    "bGVfY3JlZGVudGlhbHMuanNvbiIpLAogICAgICAgICAgICAidG9rZW4iOiAgICAgICBzdHIobW9yZ2FubmFfaG9tZSAvICJnb29n"
    "bGUiIC8gInRva2VuLmpzb24iKSwKICAgICAgICAgICAgInRpbWV6b25lIjogICAgIkFtZXJpY2EvQ2hpY2FnbyIsCiAgICAgICAg"
    "ICAgICJzY29wZXMiOiBbCiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9jYWxlbmRhci5l"
    "dmVudHMiLAogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZHJpdmUiLAogICAgICAgICAg"
    "ICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZG9jdW1lbnRzIiwKICAgICAgICAgICAgXSwKICAgICAgICB9"
    "CiAgICAgICAgbmV3X2NmZ1siZmlyc3RfcnVuIl0gPSBGYWxzZQoKICAgICAgICAjIOKUgOKUgCBDb3B5IGRlY2sgZmlsZSBpbnRv"
    "IG1vcmdhbm5hX2hvbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc3JjX2RlY2sgPSBQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCkKICAgICAgICBkc3Rf"
    "ZGVjayA9IG1vcmdhbm5hX2hvbWUgLyBmIntERUNLX05BTUUubG93ZXIoKX1fZGVjay5weSIKICAgICAgICBpZiBzcmNfZGVjayAh"
    "PSBkc3RfZGVjazoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgX3NodXRpbC5jb3B5MihzdHIoc3JjX2RlY2spLCBz"
    "dHIoZHN0X2RlY2spKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBRTWVzc2FnZUJv"
    "eC53YXJuaW5nKAogICAgICAgICAgICAgICAgICAgIE5vbmUsICJDb3B5IFdhcm5pbmciLAogICAgICAgICAgICAgICAgICAgIGYi"
    "Q291bGQgbm90IGNvcHkgZGVjayBmaWxlIHRvIHtERUNLX05BTUV9IGZvbGRlcjpcbntlfVxuXG4iCiAgICAgICAgICAgICAgICAg"
    "ICAgZiJZb3UgbWF5IG5lZWQgdG8gY29weSBpdCBtYW51YWxseS4iCiAgICAgICAgICAgICAgICApCgogICAgICAgICMg4pSA4pSA"
    "IFdyaXRlIGNvbmZpZy5qc29uIGludG8gbW9yZ2FubmFfaG9tZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBjZmdfZHN0ID0gbW9yZ2FubmFfaG9tZSAvICJjb25maWcu"
    "anNvbiIKICAgICAgICBjZmdfZHN0LnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgd2l0"
    "aCBjZmdfZHN0Lm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICBqc29uLmR1bXAobmV3X2NmZywg"
    "ZiwgaW5kZW50PTIpCgogICAgICAgICMg4pSA4pSAIEJvb3RzdHJhcCBhbGwgc3ViZGlyZWN0b3JpZXMg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICAgICAgIyBUZW1wb3JhcmlseSB1cGRhdGUgZ2xvYmFsIENGRyBzbyBib290c3RyYXAgZnVuY3Rpb25zIHVzZSBuZXcg"
    "cGF0aHMKICAgICAgICBDRkcudXBkYXRlKG5ld19jZmcpCiAgICAgICAgYm9vdHN0cmFwX2RpcmVjdG9yaWVzKCkKICAgICAgICBi"
    "b290c3RyYXBfc291bmRzKCkKICAgICAgICB3cml0ZV9yZXF1aXJlbWVudHNfdHh0KCkKCiAgICAgICAgIyDilIDilIAgVW5wYWNr"
    "IGZhY2UgWklQIGlmIHByb3ZpZGVkIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGZhY2VfemlwID0gZGxnLmZhY2Vfemlw"
    "X3BhdGgKICAgICAgICBpZiBmYWNlX3ppcCBhbmQgUGF0aChmYWNlX3ppcCkuZXhpc3RzKCk6CiAgICAgICAgICAgIGltcG9ydCB6"
    "aXBmaWxlIGFzIF96aXBmaWxlCiAgICAgICAgICAgIGZhY2VzX2RpciA9IG1vcmdhbm5hX2hvbWUgLyAiRmFjZXMiCiAgICAgICAg"
    "ICAgIGZhY2VzX2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgICAgIHdpdGggX3ppcGZpbGUuWmlwRmlsZShmYWNlX3ppcCwgInIiKSBhcyB6ZjoKICAgICAgICAgICAgICAgICAgICBleHRy"
    "YWN0ZWQgPSAwCiAgICAgICAgICAgICAgICAgICAgZm9yIG1lbWJlciBpbiB6Zi5uYW1lbGlzdCgpOgogICAgICAgICAgICAgICAg"
    "ICAgICAgICBpZiBtZW1iZXIubG93ZXIoKS5lbmRzd2l0aCgiLnBuZyIpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgZmls"
    "ZW5hbWUgPSBQYXRoKG1lbWJlcikubmFtZQogICAgICAgICAgICAgICAgICAgICAgICAgICAgdGFyZ2V0ID0gZmFjZXNfZGlyIC8g"
    "ZmlsZW5hbWUKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHdpdGggemYub3BlbihtZW1iZXIpIGFzIHNyYywgdGFyZ2V0Lm9w"
    "ZW4oIndiIikgYXMgZHN0OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGRzdC53cml0ZShzcmMucmVhZCgpKQogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZXh0cmFjdGVkICs9IDEKICAgICAgICAgICAgICAgIF9lYXJseV9sb2coZiJbRkFDRVNd"
    "IEV4dHJhY3RlZCB7ZXh0cmFjdGVkfSBmYWNlIGltYWdlcyB0byB7ZmFjZXNfZGlyfSIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb24gYXMgZToKICAgICAgICAgICAgICAgIF9lYXJseV9sb2coZiJbRkFDRVNdIFpJUCBleHRyYWN0aW9uIGZhaWxlZDoge2V9"
    "IikKICAgICAgICAgICAgICAgIFFNZXNzYWdlQm94Lndhcm5pbmcoCiAgICAgICAgICAgICAgICAgICAgTm9uZSwgIkZhY2UgUGFj"
    "ayBXYXJuaW5nIiwKICAgICAgICAgICAgICAgICAgICBmIkNvdWxkIG5vdCBleHRyYWN0IGZhY2UgcGFjazpcbntlfVxuXG4iCiAg"
    "ICAgICAgICAgICAgICAgICAgZiJZb3UgY2FuIGFkZCBmYWNlcyBtYW51YWxseSB0bzpcbntmYWNlc19kaXJ9IgogICAgICAgICAg"
    "ICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBDcmVhdGUgZGVza3RvcCBzaG9ydGN1dCBwb2ludGluZyB0byBuZXcgZGVjayBsb2Nh"
    "dGlvbiDilIDilIDilIDilIDilIDilIAKICAgICAgICBzaG9ydGN1dF9jcmVhdGVkID0gRmFsc2UKICAgICAgICBpZiBkbGcuY3Jl"
    "YXRlX3Nob3J0Y3V0OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBXSU4zMl9PSzoKICAgICAgICAgICAgICAg"
    "ICAgICBpbXBvcnQgd2luMzJjb20uY2xpZW50IGFzIF93aW4zMgogICAgICAgICAgICAgICAgICAgIGRlc2t0b3AgICAgID0gUGF0"
    "aC5ob21lKCkgLyAiRGVza3RvcCIKICAgICAgICAgICAgICAgICAgICBzY19wYXRoICAgICA9IGRlc2t0b3AgLyBmIntERUNLX05B"
    "TUV9LmxuayIKICAgICAgICAgICAgICAgICAgICBweXRob253ICAgICA9IFBhdGgoc3lzLmV4ZWN1dGFibGUpCiAgICAgICAgICAg"
    "ICAgICAgICAgaWYgcHl0aG9udy5uYW1lLmxvd2VyKCkgPT0gInB5dGhvbi5leGUiOgogICAgICAgICAgICAgICAgICAgICAgICBw"
    "eXRob253ID0gcHl0aG9udy5wYXJlbnQgLyAicHl0aG9udy5leGUiCiAgICAgICAgICAgICAgICAgICAgaWYgbm90IHB5dGhvbncu"
    "ZXhpc3RzKCk6CiAgICAgICAgICAgICAgICAgICAgICAgIHB5dGhvbncgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQogICAgICAgICAg"
    "ICAgICAgICAgIHNoZWxsID0gX3dpbjMyLkRpc3BhdGNoKCJXU2NyaXB0LlNoZWxsIikKICAgICAgICAgICAgICAgICAgICBzYyAg"
    "ICA9IHNoZWxsLkNyZWF0ZVNob3J0Q3V0KHN0cihzY19wYXRoKSkKICAgICAgICAgICAgICAgICAgICBzYy5UYXJnZXRQYXRoICAg"
    "ICAgPSBzdHIocHl0aG9udykKICAgICAgICAgICAgICAgICAgICBzYy5Bcmd1bWVudHMgICAgICAgPSBmJyJ7ZHN0X2RlY2t9IicK"
    "ICAgICAgICAgICAgICAgICAgICBzYy5Xb3JraW5nRGlyZWN0b3J5PSBzdHIobW9yZ2FubmFfaG9tZSkKICAgICAgICAgICAgICAg"
    "ICAgICBzYy5EZXNjcmlwdGlvbiAgICAgPSBmIntERUNLX05BTUV9IOKAlCBFY2hvIERlY2siCiAgICAgICAgICAgICAgICAgICAg"
    "c2Muc2F2ZSgpCiAgICAgICAgICAgICAgICAgICAgc2hvcnRjdXRfY3JlYXRlZCA9IFRydWUKICAgICAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgcHJpbnQoZiJbU0hPUlRDVVRdIENvdWxkIG5vdCBjcmVhdGUgc2hvcnRjdXQ6"
    "IHtlfSIpCgogICAgICAgICMg4pSA4pSAIENvbXBsZXRpb24gbWVzc2FnZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICBzaG9ydGN1dF9ub3RlID0gKAogICAgICAgICAgICAiQSBkZXNrdG9wIHNob3J0Y3V0"
    "IGhhcyBiZWVuIGNyZWF0ZWQuXG4iCiAgICAgICAgICAgIGYiVXNlIGl0IHRvIHN1bW1vbiB7REVDS19OQU1FfSBmcm9tIG5vdyBv"
    "bi4iCiAgICAgICAgICAgIGlmIHNob3J0Y3V0X2NyZWF0ZWQgZWxzZQogICAgICAgICAgICAiTm8gc2hvcnRjdXQgd2FzIGNyZWF0"
    "ZWQuXG4iCiAgICAgICAgICAgIGYiUnVuIHtERUNLX05BTUV9IGJ5IGRvdWJsZS1jbGlja2luZzpcbntkc3RfZGVja30iCiAgICAg"
    "ICAgKQoKICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbigKICAgICAgICAgICAgTm9uZSwKICAgICAgICAgICAgZiLinKYg"
    "e0RFQ0tfTkFNRX0ncyBTYW5jdHVtIFByZXBhcmVkIiwKICAgICAgICAgICAgZiJ7REVDS19OQU1FfSdzIHNhbmN0dW0gaGFzIGJl"
    "ZW4gcHJlcGFyZWQgYXQ6XG5cbiIKICAgICAgICAgICAgZiJ7bW9yZ2FubmFfaG9tZX1cblxuIgogICAgICAgICAgICBmIntzaG9y"
    "dGN1dF9ub3RlfVxuXG4iCiAgICAgICAgICAgIGYiVGhpcyBzZXR1cCB3aW5kb3cgd2lsbCBub3cgY2xvc2UuXG4iCiAgICAgICAg"
    "ICAgIGYiVXNlIHRoZSBzaG9ydGN1dCBvciB0aGUgZGVjayBmaWxlIHRvIGxhdW5jaCB7REVDS19OQU1FfS4iCiAgICAgICAgKQoK"
    "ICAgICAgICAjIOKUgOKUgCBFeGl0IHNlZWQg4oCUIHVzZXIgbGF1bmNoZXMgZnJvbSBzaG9ydGN1dC9uZXcgbG9jYXRpb24g4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc3lzLmV4aXQoMCkKCiAgICAjIOKUgOKUgCBQaGFzZSA0OiBOb3JtYWwgbGF1bmNo"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgIyBPbmx5IHJlYWNoZXMgaGVyZSBv"
    "biBzdWJzZXF1ZW50IHJ1bnMgZnJvbSBtb3JnYW5uYV9ob21lCiAgICBib290c3RyYXBfc291bmRzKCkKCiAgICBfZWFybHlfbG9n"
    "KGYiW01BSU5dIENyZWF0aW5nIHtERUNLX05BTUV9IGRlY2sgd2luZG93IikKICAgIHdpbmRvdyA9IEVjaG9EZWNrKCkKICAgIF9l"
    "YXJseV9sb2coZiJbTUFJTl0ge0RFQ0tfTkFNRX0gZGVjayBjcmVhdGVkIOKAlCBjYWxsaW5nIHNob3coKSIpCiAgICB3aW5kb3cu"
    "c2hvdygpCiAgICBfZWFybHlfbG9nKCJbTUFJTl0gd2luZG93LnNob3coKSBjYWxsZWQg4oCUIGV2ZW50IGxvb3Agc3RhcnRpbmci"
    "KQoKICAgICMgRGVmZXIgc2NoZWR1bGVyIGFuZCBzdGFydHVwIHNlcXVlbmNlIHVudGlsIGV2ZW50IGxvb3AgaXMgcnVubmluZy4K"
    "ICAgICMgTm90aGluZyB0aGF0IHN0YXJ0cyB0aHJlYWRzIG9yIGVtaXRzIHNpZ25hbHMgc2hvdWxkIHJ1biBiZWZvcmUgdGhpcy4K"
    "ICAgIFFUaW1lci5zaW5nbGVTaG90KDIwMCwgbGFtYmRhOiAoX2Vhcmx5X2xvZygiW1RJTUVSXSBfc2V0dXBfc2NoZWR1bGVyIGZp"
    "cmluZyIpLCB3aW5kb3cuX3NldHVwX3NjaGVkdWxlcigpKSkKICAgIFFUaW1lci5zaW5nbGVTaG90KDQwMCwgbGFtYmRhOiAoX2Vh"
    "cmx5X2xvZygiW1RJTUVSXSBzdGFydF9zY2hlZHVsZXIgZmlyaW5nIiksIHdpbmRvdy5zdGFydF9zY2hlZHVsZXIoKSkpCiAgICBR"
    "VGltZXIuc2luZ2xlU2hvdCg2MDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gX3N0YXJ0dXBfc2VxdWVuY2UgZmlyaW5n"
    "IiksIHdpbmRvdy5fc3RhcnR1cF9zZXF1ZW5jZSgpKSkKICAgIFFUaW1lci5zaW5nbGVTaG90KDEwMDAsIGxhbWJkYTogKF9lYXJs"
    "eV9sb2coIltUSU1FUl0gX3N0YXJ0dXBfZ29vZ2xlX2F1dGggZmlyaW5nIiksIHdpbmRvdy5fc3RhcnR1cF9nb29nbGVfYXV0aCgp"
    "KSkKCiAgICAjIFBsYXkgc3RhcnR1cCBzb3VuZCDigJQga2VlcCByZWZlcmVuY2UgdG8gcHJldmVudCBHQyB3aGlsZSB0aHJlYWQg"
    "cnVucwogICAgZGVmIF9wbGF5X3N0YXJ0dXAoKToKICAgICAgICB3aW5kb3cuX3N0YXJ0dXBfc291bmQgPSBTb3VuZFdvcmtlcigi"
    "c3RhcnR1cCIpCiAgICAgICAgd2luZG93Ll9zdGFydHVwX3NvdW5kLmZpbmlzaGVkLmNvbm5lY3Qod2luZG93Ll9zdGFydHVwX3Nv"
    "dW5kLmRlbGV0ZUxhdGVyKQogICAgICAgIHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5zdGFydCgpCiAgICBRVGltZXIuc2luZ2xlU2hv"
    "dCgxMjAwLCBfcGxheV9zdGFydHVwKQoKICAgIHN5cy5leGl0KGFwcC5leGVjKCkpCgoKaWYgX19uYW1lX18gPT0gIl9fbWFpbl9f"
    "IjoKICAgIG1haW4oKQoKCiMg4pSA4pSAIFBBU1MgNiBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBG"
    "dWxsIGRlY2sgYXNzZW1ibGVkLiBBbGwgcGFzc2VzIGNvbXBsZXRlLgojIENvbWJpbmUgYWxsIHBhc3NlcyBpbnRvIG1vcmdhbm5h"
    "X2RlY2sucHkgaW4gb3JkZXI6CiMgICBQYXNzIDEg4oaSIFBhc3MgMiDihpIgUGFzcyAzIOKGkiBQYXNzIDQg4oaSIFBhc3MgNSDi"
    "hpIgUGFzcyA2"
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
