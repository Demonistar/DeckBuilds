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
    "dCwgUVNjcm9sbEFyZWEsCiAgICBRU3BsaXR0ZXIsIFFJbnB1dERpYWxvZywgUVRvb2xCdXR0b24KKQpmcm9tIFB5U2lkZTYuUXRD"
    "b3JlIGltcG9ydCAoCiAgICBRdCwgUVRpbWVyLCBRVGhyZWFkLCBTaWduYWwsIFFEYXRlLCBRU2l6ZSwgUVBvaW50LCBRUmVjdAop"
    "CmZyb20gUHlTaWRlNi5RdEd1aSBpbXBvcnQgKAogICAgUUZvbnQsIFFDb2xvciwgUVBhaW50ZXIsIFFMaW5lYXJHcmFkaWVudCwg"
    "UVJhZGlhbEdyYWRpZW50LAogICAgUVBpeG1hcCwgUVBlbiwgUVBhaW50ZXJQYXRoLCBRVGV4dENoYXJGb3JtYXQsIFFJY29uLAog"
    "ICAgUVRleHRDdXJzb3IsIFFBY3Rpb24KKQoKIyDilIDilIAgQVBQIElERU5USVRZIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgApBUFBfTkFNRSAgICAgID0gVUlfV0lORE9XX1RJVExFCkFQUF9WRVJTSU9OICAgPSAiMi4wLjAiCkFQUF9GSUxF"
    "TkFNRSAgPSBmIntERUNLX05BTUUubG93ZXIoKX1fZGVjay5weSIKQlVJTERfREFURSAgICA9ICIyMDI2LTA0LTA0IgoKIyDilIDi"
    "lIAgQ09ORklHIExPQURJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgY29uZmlnLmpzb24gbGl2ZXMgbmV4"
    "dCB0byB0aGUgZGVjayAucHkgZmlsZS4KIyBBbGwgcGF0aHMgY29tZSBmcm9tIGNvbmZpZy4gTm90aGluZyBoYXJkY29kZWQgYmVs"
    "b3cgdGhpcyBwb2ludC4KClNDUklQVF9ESVIgPSBQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCkucGFyZW50CkNPTkZJR19QQVRIID0g"
    "U0NSSVBUX0RJUiAvICJjb25maWcuanNvbiIKCiMgSW5pdGlhbGl6ZSBlYXJseSBsb2cgbm93IHRoYXQgd2Uga25vdyB3aGVyZSB3"
    "ZSBhcmUKX2luaXRfZWFybHlfbG9nKFNDUklQVF9ESVIpCl9lYXJseV9sb2coZiJbSU5JVF0gU0NSSVBUX0RJUiA9IHtTQ1JJUFRf"
    "RElSfSIpCl9lYXJseV9sb2coZiJbSU5JVF0gQ09ORklHX1BBVEggPSB7Q09ORklHX1BBVEh9IikKX2Vhcmx5X2xvZyhmIltJTklU"
    "XSBjb25maWcuanNvbiBleGlzdHM6IHtDT05GSUdfUEFUSC5leGlzdHMoKX0iKQoKZGVmIF9kZWZhdWx0X2NvbmZpZygpIC0+IGRp"
    "Y3Q6CiAgICAiIiJSZXR1cm5zIHRoZSBkZWZhdWx0IGNvbmZpZyBzdHJ1Y3R1cmUgZm9yIGZpcnN0LXJ1biBnZW5lcmF0aW9uLiIi"
    "IgogICAgYmFzZSA9IHN0cihTQ1JJUFRfRElSKQogICAgcmV0dXJuIHsKICAgICAgICAiZGVja19uYW1lIjogREVDS19OQU1FLAog"
    "ICAgICAgICJkZWNrX3ZlcnNpb24iOiBBUFBfVkVSU0lPTiwKICAgICAgICAiYmFzZV9kaXIiOiBiYXNlLAogICAgICAgICJtb2Rl"
    "bCI6IHsKICAgICAgICAgICAgInR5cGUiOiAibG9jYWwiLCAgICAgICAgICAjIGxvY2FsIHwgb2xsYW1hIHwgY2xhdWRlIHwgb3Bl"
    "bmFpCiAgICAgICAgICAgICJwYXRoIjogIiIsICAgICAgICAgICAgICAgIyBsb2NhbCBtb2RlbCBmb2xkZXIgcGF0aAogICAgICAg"
    "ICAgICAib2xsYW1hX21vZGVsIjogIiIsICAgICAgICMgZS5nLiAiZG9scGhpbi0yLjYtN2IiCiAgICAgICAgICAgICJhcGlfa2V5"
    "IjogIiIsICAgICAgICAgICAgIyBDbGF1ZGUgb3IgT3BlbkFJIGtleQogICAgICAgICAgICAiYXBpX3R5cGUiOiAiIiwgICAgICAg"
    "ICAgICMgImNsYXVkZSIgfCAib3BlbmFpIgogICAgICAgICAgICAiYXBpX21vZGVsIjogIiIsICAgICAgICAgICMgZS5nLiAiY2xh"
    "dWRlLXNvbm5ldC00LTYiCiAgICAgICAgfSwKICAgICAgICAiZ29vZ2xlIjogewogICAgICAgICAgICAiY3JlZGVudGlhbHMiOiBz"
    "dHIoU0NSSVBUX0RJUiAvICJnb29nbGUiIC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIiksCiAgICAgICAgICAgICJ0b2tlbiI6"
    "ICAgICAgIHN0cihTQ1JJUFRfRElSIC8gImdvb2dsZSIgLyAidG9rZW4uanNvbiIpLAogICAgICAgICAgICAidGltZXpvbmUiOiAg"
    "ICAiQW1lcmljYS9DaGljYWdvIiwKICAgICAgICAgICAgInNjb3BlcyI6IFsKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5n"
    "b29nbGVhcGlzLmNvbS9hdXRoL2NhbGVuZGFyLmV2ZW50cyIsCiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBp"
    "cy5jb20vYXV0aC9kcml2ZSIsCiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9kb2N1bWVu"
    "dHMiLAogICAgICAgICAgICBdLAogICAgICAgIH0sCiAgICAgICAgInBhdGhzIjogewogICAgICAgICAgICAiZmFjZXMiOiAgICBz"
    "dHIoU0NSSVBUX0RJUiAvICJGYWNlcyIpLAogICAgICAgICAgICAic291bmRzIjogICBzdHIoU0NSSVBUX0RJUiAvICJzb3VuZHMi"
    "KSwKICAgICAgICAgICAgIm1lbW9yaWVzIjogc3RyKFNDUklQVF9ESVIgLyAibWVtb3JpZXMiKSwKICAgICAgICAgICAgInNlc3Np"
    "b25zIjogc3RyKFNDUklQVF9ESVIgLyAic2Vzc2lvbnMiKSwKICAgICAgICAgICAgInNsIjogICAgICAgc3RyKFNDUklQVF9ESVIg"
    "LyAic2wiKSwKICAgICAgICAgICAgImV4cG9ydHMiOiAgc3RyKFNDUklQVF9ESVIgLyAiZXhwb3J0cyIpLAogICAgICAgICAgICAi"
    "bG9ncyI6ICAgICBzdHIoU0NSSVBUX0RJUiAvICJsb2dzIiksCiAgICAgICAgICAgICJiYWNrdXBzIjogIHN0cihTQ1JJUFRfRElS"
    "IC8gImJhY2t1cHMiKSwKICAgICAgICAgICAgInBlcnNvbmFzIjogc3RyKFNDUklQVF9ESVIgLyAicGVyc29uYXMiKSwKICAgICAg"
    "ICAgICAgImdvb2dsZSI6ICAgc3RyKFNDUklQVF9ESVIgLyAiZ29vZ2xlIiksCiAgICAgICAgfSwKICAgICAgICAic2V0dGluZ3Mi"
    "OiB7CiAgICAgICAgICAgICJpZGxlX2VuYWJsZWQiOiAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICAgICJpZGxlX21pbl9t"
    "aW51dGVzIjogICAgICAgICAgMTAsCiAgICAgICAgICAgICJpZGxlX21heF9taW51dGVzIjogICAgICAgICAgMzAsCiAgICAgICAg"
    "ICAgICJhdXRvc2F2ZV9pbnRlcnZhbF9taW51dGVzIjogMTAsCiAgICAgICAgICAgICJtYXhfYmFja3VwcyI6ICAgICAgICAgICAg"
    "ICAgMTAsCiAgICAgICAgICAgICJnb29nbGVfc3luY19lbmFibGVkIjogICAgICAgVHJ1ZSwKICAgICAgICAgICAgInNvdW5kX2Vu"
    "YWJsZWQiOiAgICAgICAgICAgICBUcnVlLAogICAgICAgICAgICAiZ29vZ2xlX2luYm91bmRfaW50ZXJ2YWxfbXMiOiAzMDAwMDAs"
    "CiAgICAgICAgICAgICJlbWFpbF9yZWZyZXNoX2ludGVydmFsX21zIjogMzAwMDAwLAogICAgICAgICAgICAiZ29vZ2xlX2xvb2ti"
    "YWNrX2RheXMiOiAgICAgIDMwLAogICAgICAgICAgICAidXNlcl9kZWxheV90aHJlc2hvbGRfbWluIjogIDMwLAogICAgICAgICAg"
    "ICAidGltZXpvbmVfYXV0b19kZXRlY3QiOiAgICAgIFRydWUsCiAgICAgICAgICAgICJ0aW1lem9uZV9vdmVycmlkZSI6ICAgICAg"
    "ICAgIiIsCiAgICAgICAgICAgICJmdWxsc2NyZWVuX2VuYWJsZWQiOiAgICAgICAgRmFsc2UsCiAgICAgICAgICAgICJib3JkZXJs"
    "ZXNzX2VuYWJsZWQiOiAgICAgICAgRmFsc2UsCiAgICAgICAgfSwKICAgICAgICAiZmlyc3RfcnVuIjogVHJ1ZSwKICAgIH0KCmRl"
    "ZiBsb2FkX2NvbmZpZygpIC0+IGRpY3Q6CiAgICAiIiJMb2FkIGNvbmZpZy5qc29uLiBSZXR1cm5zIGRlZmF1bHQgaWYgbWlzc2lu"
    "ZyBvciBjb3JydXB0LiIiIgogICAgaWYgbm90IENPTkZJR19QQVRILmV4aXN0cygpOgogICAgICAgIHJldHVybiBfZGVmYXVsdF9j"
    "b25maWcoKQogICAgdHJ5OgogICAgICAgIHdpdGggQ09ORklHX1BBVEgub3BlbigiciIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6"
    "CiAgICAgICAgICAgIHJldHVybiBqc29uLmxvYWQoZikKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcmV0dXJuIF9kZWZh"
    "dWx0X2NvbmZpZygpCgpkZWYgc2F2ZV9jb25maWcoY2ZnOiBkaWN0KSAtPiBOb25lOgogICAgIiIiV3JpdGUgY29uZmlnLmpzb24u"
    "IiIiCiAgICBDT05GSUdfUEFUSC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgd2l0aCBDT05G"
    "SUdfUEFUSC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICBqc29uLmR1bXAoY2ZnLCBmLCBpbmRlbnQ9"
    "MikKCiMgTG9hZCBjb25maWcgYXQgbW9kdWxlIGxldmVsIOKAlCBldmVyeXRoaW5nIGJlbG93IHJlYWRzIGZyb20gQ0ZHCkNGRyA9"
    "IGxvYWRfY29uZmlnKCkKX2Vhcmx5X2xvZyhmIltJTklUXSBDb25maWcgbG9hZGVkIOKAlCBmaXJzdF9ydW49e0NGRy5nZXQoJ2Zp"
    "cnN0X3J1bicpfSwgbW9kZWxfdHlwZT17Q0ZHLmdldCgnbW9kZWwnLHt9KS5nZXQoJ3R5cGUnKX0iKQoKX0RFRkFVTFRfUEFUSFM6"
    "IGRpY3Rbc3RyLCBQYXRoXSA9IHsKICAgICJmYWNlcyI6ICAgIFNDUklQVF9ESVIgLyAiRmFjZXMiLAogICAgInNvdW5kcyI6ICAg"
    "U0NSSVBUX0RJUiAvICJzb3VuZHMiLAogICAgIm1lbW9yaWVzIjogU0NSSVBUX0RJUiAvICJtZW1vcmllcyIsCiAgICAic2Vzc2lv"
    "bnMiOiBTQ1JJUFRfRElSIC8gInNlc3Npb25zIiwKICAgICJzbCI6ICAgICAgIFNDUklQVF9ESVIgLyAic2wiLAogICAgImV4cG9y"
    "dHMiOiAgU0NSSVBUX0RJUiAvICJleHBvcnRzIiwKICAgICJsb2dzIjogICAgIFNDUklQVF9ESVIgLyAibG9ncyIsCiAgICAiYmFj"
    "a3VwcyI6ICBTQ1JJUFRfRElSIC8gImJhY2t1cHMiLAogICAgInBlcnNvbmFzIjogU0NSSVBUX0RJUiAvICJwZXJzb25hcyIsCiAg"
    "ICAiZ29vZ2xlIjogICBTQ1JJUFRfRElSIC8gImdvb2dsZSIsCn0KCmRlZiBfbm9ybWFsaXplX2NvbmZpZ19wYXRocygpIC0+IE5v"
    "bmU6CiAgICAiIiIKICAgIFNlbGYtaGVhbCBvbGRlciBjb25maWcuanNvbiBmaWxlcyBtaXNzaW5nIHJlcXVpcmVkIHBhdGgga2V5"
    "cy4KICAgIEFkZHMgbWlzc2luZyBwYXRoIGtleXMgYW5kIG5vcm1hbGl6ZXMgZ29vZ2xlIGNyZWRlbnRpYWwvdG9rZW4gbG9jYXRp"
    "b25zLAogICAgdGhlbiBwZXJzaXN0cyBjb25maWcuanNvbiBpZiBhbnl0aGluZyBjaGFuZ2VkLgogICAgIiIiCiAgICBjaGFuZ2Vk"
    "ID0gRmFsc2UKICAgIHBhdGhzID0gQ0ZHLnNldGRlZmF1bHQoInBhdGhzIiwge30pCiAgICBmb3Iga2V5LCBkZWZhdWx0X3BhdGgg"
    "aW4gX0RFRkFVTFRfUEFUSFMuaXRlbXMoKToKICAgICAgICBpZiBub3QgcGF0aHMuZ2V0KGtleSk6CiAgICAgICAgICAgIHBhdGhz"
    "W2tleV0gPSBzdHIoZGVmYXVsdF9wYXRoKQogICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgIGdvb2dsZV9jZmcgPSBDRkcu"
    "c2V0ZGVmYXVsdCgiZ29vZ2xlIiwge30pCiAgICBnb29nbGVfcm9vdCA9IFBhdGgocGF0aHMuZ2V0KCJnb29nbGUiLCBzdHIoX0RF"
    "RkFVTFRfUEFUSFNbImdvb2dsZSJdKSkpCiAgICBkZWZhdWx0X2NyZWRzID0gc3RyKGdvb2dsZV9yb290IC8gImdvb2dsZV9jcmVk"
    "ZW50aWFscy5qc29uIikKICAgIGRlZmF1bHRfdG9rZW4gPSBzdHIoZ29vZ2xlX3Jvb3QgLyAidG9rZW4uanNvbiIpCiAgICBjcmVk"
    "c192YWwgPSBzdHIoZ29vZ2xlX2NmZy5nZXQoImNyZWRlbnRpYWxzIiwgIiIpKS5zdHJpcCgpCiAgICB0b2tlbl92YWwgPSBzdHIo"
    "Z29vZ2xlX2NmZy5nZXQoInRva2VuIiwgIiIpKS5zdHJpcCgpCiAgICBpZiAobm90IGNyZWRzX3ZhbCkgb3IgKCJjb25maWciIGlu"
    "IGNyZWRzX3ZhbCBhbmQgImdvb2dsZV9jcmVkZW50aWFscy5qc29uIiBpbiBjcmVkc192YWwpOgogICAgICAgIGdvb2dsZV9jZmdb"
    "ImNyZWRlbnRpYWxzIl0gPSBkZWZhdWx0X2NyZWRzCiAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgIGlmIG5vdCB0b2tlbl92YWw6"
    "CiAgICAgICAgZ29vZ2xlX2NmZ1sidG9rZW4iXSA9IGRlZmF1bHRfdG9rZW4KICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgIGlm"
    "IGNoYW5nZWQ6CiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQoKZGVmIGNmZ19wYXRoKGtleTogc3RyKSAtPiBQYXRoOgogICAgIiIi"
    "Q29udmVuaWVuY2U6IGdldCBhIHBhdGggZnJvbSBDRkdbJ3BhdGhzJ11ba2V5XSBhcyBhIFBhdGggb2JqZWN0IHdpdGggc2FmZSBm"
    "YWxsYmFjayBkZWZhdWx0cy4iIiIKICAgIHBhdGhzID0gQ0ZHLmdldCgicGF0aHMiLCB7fSkKICAgIHZhbHVlID0gcGF0aHMuZ2V0"
    "KGtleSkKICAgIGlmIHZhbHVlOgogICAgICAgIHJldHVybiBQYXRoKHZhbHVlKQogICAgZmFsbGJhY2sgPSBfREVGQVVMVF9QQVRI"
    "Uy5nZXQoa2V5KQogICAgaWYgZmFsbGJhY2s6CiAgICAgICAgcGF0aHNba2V5XSA9IHN0cihmYWxsYmFjaykKICAgICAgICByZXR1"
    "cm4gZmFsbGJhY2sKICAgIHJldHVybiBTQ1JJUFRfRElSIC8ga2V5Cgpfbm9ybWFsaXplX2NvbmZpZ19wYXRocygpCgojIOKUgOKU"
    "gCBDT0xPUiBDT05TVEFOVFMg4oCUIGRlcml2ZWQgZnJvbSBwZXJzb25hIHRlbXBsYXRlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIENfUFJJTUFSWSwgQ19TRUNP"
    "TkRBUlksIENfQUNDRU5ULCBDX0JHLCBDX1BBTkVMLCBDX0JPUkRFUiwKIyBDX1RFWFQsIENfVEVYVF9ESU0gYXJlIGluamVjdGVk"
    "IGF0IHRoZSB0b3Agb2YgdGhpcyBmaWxlIGJ5IGRlY2tfYnVpbGRlci4KIyBFdmVyeXRoaW5nIGJlbG93IGlzIGRlcml2ZWQgZnJv"
    "bSB0aG9zZSBpbmplY3RlZCB2YWx1ZXMuCgojIFNlbWFudGljIGFsaWFzZXMg4oCUIG1hcCBwZXJzb25hIGNvbG9ycyB0byBuYW1l"
    "ZCByb2xlcyB1c2VkIHRocm91Z2hvdXQgdGhlIFVJCkNfQ1JJTVNPTiAgICAgPSBDX1BSSU1BUlkgICAgICAgICAgIyBtYWluIGFj"
    "Y2VudCAoYnV0dG9ucywgYm9yZGVycywgaGlnaGxpZ2h0cykKQ19DUklNU09OX0RJTSA9IENfUFJJTUFSWSArICI4OCIgICAjIGRp"
    "bSBhY2NlbnQgZm9yIHN1YnRsZSBib3JkZXJzCkNfR09MRCAgICAgICAgPSBDX1NFQ09OREFSWSAgICAgICAgIyBtYWluIGxhYmVs"
    "L3RleHQvQUkgb3V0cHV0IGNvbG9yCkNfR09MRF9ESU0gICAgPSBDX1NFQ09OREFSWSArICI4OCIgIyBkaW0gc2Vjb25kYXJ5CkNf"
    "R09MRF9CUklHSFQgPSBDX0FDQ0VOVCAgICAgICAgICAgIyBlbXBoYXNpcywgaG92ZXIgc3RhdGVzCkNfU0lMVkVSICAgICAgPSBD"
    "X1RFWFRfRElNICAgICAgICAgIyBzZWNvbmRhcnkgdGV4dCAoYWxyZWFkeSBpbmplY3RlZCkKQ19TSUxWRVJfRElNICA9IENfVEVY"
    "VF9ESU0gKyAiODgiICAjIGRpbSBzZWNvbmRhcnkgdGV4dApDX01PTklUT1IgICAgID0gQ19CRyAgICAgICAgICAgICAgICMgY2hh"
    "dCBkaXNwbGF5IGJhY2tncm91bmQgKGFscmVhZHkgaW5qZWN0ZWQpCkNfQkcyICAgICAgICAgPSBDX0JHICAgICAgICAgICAgICAg"
    "IyBzZWNvbmRhcnkgYmFja2dyb3VuZApDX0JHMyAgICAgICAgID0gQ19QQU5FTCAgICAgICAgICAgICMgdGVydGlhcnkvaW5wdXQg"
    "YmFja2dyb3VuZCAoYWxyZWFkeSBpbmplY3RlZCkKQ19CTE9PRCAgICAgICA9ICcjOGIwMDAwJyAgICAgICAgICAjIGVycm9yIHN0"
    "YXRlcywgZGFuZ2VyIOKAlCB1bml2ZXJzYWwKQ19QVVJQTEUgICAgICA9ICcjODg1NWNjJyAgICAgICAgICAjIFNZU1RFTSBtZXNz"
    "YWdlcyDigJQgdW5pdmVyc2FsCkNfUFVSUExFX0RJTSAgPSAnIzJhMDUyYScgICAgICAgICAgIyBkaW0gcHVycGxlIOKAlCB1bml2"
    "ZXJzYWwKQ19HUkVFTiAgICAgICA9ICcjNDRhYTY2JyAgICAgICAgICAjIHBvc2l0aXZlIHN0YXRlcyDigJQgdW5pdmVyc2FsCkNf"
    "QkxVRSAgICAgICAgPSAnIzQ0ODhjYycgICAgICAgICAgIyBpbmZvIHN0YXRlcyDigJQgdW5pdmVyc2FsCgojIEZvbnQgaGVscGVy"
    "IOKAlCBleHRyYWN0cyBwcmltYXJ5IGZvbnQgbmFtZSBmb3IgUUZvbnQoKSBjYWxscwpERUNLX0ZPTlQgPSBVSV9GT05UX0ZBTUlM"
    "WS5zcGxpdCgnLCcpWzBdLnN0cmlwKCkuc3RyaXAoIiciKQoKIyBFbW90aW9uIOKGkiBjb2xvciBtYXBwaW5nIChmb3IgZW1vdGlv"
    "biByZWNvcmQgY2hpcHMpCkVNT1RJT05fQ09MT1JTOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICJ2aWN0b3J5IjogICAgQ19HT0xE"
    "LAogICAgInNtdWciOiAgICAgICBDX0dPTEQsCiAgICAiaW1wcmVzc2VkIjogIENfR09MRCwKICAgICJyZWxpZXZlZCI6ICAgQ19H"
    "T0xELAogICAgImhhcHB5IjogICAgICBDX0dPTEQsCiAgICAiZmxpcnR5IjogICAgIENfR09MRCwKICAgICJwYW5pY2tlZCI6ICAg"
    "Q19DUklNU09OLAogICAgImFuZ3J5IjogICAgICBDX0NSSU1TT04sCiAgICAic2hvY2tlZCI6ICAgIENfQ1JJTVNPTiwKICAgICJj"
    "aGVhdG1vZGUiOiAgQ19DUklNU09OLAogICAgImNvbmNlcm5lZCI6ICAiI2NjNjYyMiIsCiAgICAic2FkIjogICAgICAgICIjY2M2"
    "NjIyIiwKICAgICJodW1pbGlhdGVkIjogIiNjYzY2MjIiLAogICAgImZsdXN0ZXJlZCI6ICAiI2NjNjYyMiIsCiAgICAicGxvdHRp"
    "bmciOiAgIENfUFVSUExFLAogICAgInN1c3BpY2lvdXMiOiBDX1BVUlBMRSwKICAgICJlbnZpb3VzIjogICAgQ19QVVJQTEUsCiAg"
    "ICAiZm9jdXNlZCI6ICAgIENfU0lMVkVSLAogICAgImFsZXJ0IjogICAgICBDX1NJTFZFUiwKICAgICJuZXV0cmFsIjogICAgQ19U"
    "RVhUX0RJTSwKfQoKIyDilIDilIAgREVDT1JBVElWRSBDT05TVEFOVFMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgUlVORVMgaXMgc291cmNlZCBm"
    "cm9tIFVJX1JVTkVTIGluamVjdGVkIGJ5IHRoZSBwZXJzb25hIHRlbXBsYXRlClJVTkVTID0gVUlfUlVORVMKCiMgRmFjZSBpbWFn"
    "ZSBtYXAg4oCUIHByZWZpeCBmcm9tIEZBQ0VfUFJFRklYLCBmaWxlcyBsaXZlIGluIGNvbmZpZyBwYXRocy5mYWNlcwpGQUNFX0ZJ"
    "TEVTOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICJuZXV0cmFsIjogICAgZiJ7RkFDRV9QUkVGSVh9X05ldXRyYWwucG5nIiwKICAg"
    "ICJhbGVydCI6ICAgICAgZiJ7RkFDRV9QUkVGSVh9X0FsZXJ0LnBuZyIsCiAgICAiZm9jdXNlZCI6ICAgIGYie0ZBQ0VfUFJFRklY"
    "fV9Gb2N1c2VkLnBuZyIsCiAgICAic211ZyI6ICAgICAgIGYie0ZBQ0VfUFJFRklYfV9TbXVnLnBuZyIsCiAgICAiY29uY2VybmVk"
    "IjogIGYie0ZBQ0VfUFJFRklYfV9Db25jZXJuZWQucG5nIiwKICAgICJzYWQiOiAgICAgICAgZiJ7RkFDRV9QUkVGSVh9X1NhZF9D"
    "cnlpbmcucG5nIiwKICAgICJyZWxpZXZlZCI6ICAgZiJ7RkFDRV9QUkVGSVh9X1JlbGlldmVkLnBuZyIsCiAgICAiaW1wcmVzc2Vk"
    "IjogIGYie0ZBQ0VfUFJFRklYfV9JbXByZXNzZWQucG5nIiwKICAgICJ2aWN0b3J5IjogICAgZiJ7RkFDRV9QUkVGSVh9X1ZpY3Rv"
    "cnkucG5nIiwKICAgICJodW1pbGlhdGVkIjogZiJ7RkFDRV9QUkVGSVh9X0h1bWlsaWF0ZWQucG5nIiwKICAgICJzdXNwaWNpb3Vz"
    "IjogZiJ7RkFDRV9QUkVGSVh9X1N1c3BpY2lvdXMucG5nIiwKICAgICJwYW5pY2tlZCI6ICAgZiJ7RkFDRV9QUkVGSVh9X1Bhbmlj"
    "a2VkLnBuZyIsCiAgICAiY2hlYXRtb2RlIjogIGYie0ZBQ0VfUFJFRklYfV9DaGVhdF9Nb2RlLnBuZyIsCiAgICAiYW5ncnkiOiAg"
    "ICAgIGYie0ZBQ0VfUFJFRklYfV9BbmdyeS5wbmciLAogICAgInBsb3R0aW5nIjogICBmIntGQUNFX1BSRUZJWH1fUGxvdHRpbmcu"
    "cG5nIiwKICAgICJzaG9ja2VkIjogICAgZiJ7RkFDRV9QUkVGSVh9X1Nob2NrZWQucG5nIiwKICAgICJoYXBweSI6ICAgICAgZiJ7"
    "RkFDRV9QUkVGSVh9X0hhcHB5LnBuZyIsCiAgICAiZmxpcnR5IjogICAgIGYie0ZBQ0VfUFJFRklYfV9GbGlydHkucG5nIiwKICAg"
    "ICJmbHVzdGVyZWQiOiAgZiJ7RkFDRV9QUkVGSVh9X0ZsdXN0ZXJlZC5wbmciLAogICAgImVudmlvdXMiOiAgICBmIntGQUNFX1BS"
    "RUZJWH1fRW52aW91cy5wbmciLAp9CgpTRU5USU1FTlRfTElTVCA9ICgKICAgICJuZXV0cmFsLCBhbGVydCwgZm9jdXNlZCwgc211"
    "ZywgY29uY2VybmVkLCBzYWQsIHJlbGlldmVkLCBpbXByZXNzZWQsICIKICAgICJ2aWN0b3J5LCBodW1pbGlhdGVkLCBzdXNwaWNp"
    "b3VzLCBwYW5pY2tlZCwgYW5ncnksIHBsb3R0aW5nLCBzaG9ja2VkLCAiCiAgICAiaGFwcHksIGZsaXJ0eSwgZmx1c3RlcmVkLCBl"
    "bnZpb3VzIgopCgojIOKUgOKUgCBTWVNURU0gUFJPTVBUIOKAlCBpbmplY3RlZCBmcm9tIHBlcnNvbmEgdGVtcGxhdGUgYXQgdG9w"
    "IG9mIGZpbGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgU1lTVEVNX1BST01QVF9CQVNFIGlzIGFs"
    "cmVhZHkgZGVmaW5lZCBhYm92ZSBmcm9tIDw8PFNZU1RFTV9QUk9NUFQ+Pj4gaW5qZWN0aW9uLgojIERvIG5vdCByZWRlZmluZSBp"
    "dCBoZXJlLgoKIyDilIDilIAgR0xPQkFMIFNUWUxFU0hFRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSAClNUWUxFID0gZiIiIgpRTWFp"
    "bldpbmRvdywgUVdpZGdldCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkd9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAg"
    "Zm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07Cn19ClFUZXh0RWRpdCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfTU9O"
    "SVRPUn07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBib3Jk"
    "ZXItcmFkaXVzOiAycHg7CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKICAgIGZvbnQtc2l6ZTogMTJweDsKICAg"
    "IHBhZGRpbmc6IDhweDsKICAgIHNlbGVjdGlvbi1iYWNrZ3JvdW5kLWNvbG9yOiB7Q19DUklNU09OX0RJTX07Cn19ClFMaW5lRWRp"
    "dCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNv"
    "bGlkIHtDX0NSSU1TT059OwogICAgYm9yZGVyLXJhZGl1czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07"
    "CiAgICBmb250LXNpemU6IDEzcHg7CiAgICBwYWRkaW5nOiA4cHggMTJweDsKfX0KUUxpbmVFZGl0OmZvY3VzIHt7CiAgICBib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19HT0xEfTsKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX1BBTkVMfTsKfX0KUVB1c2hCdXR0b24ge3sK"
    "ICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0NSSU1TT05fRElNfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4"
    "IHNvbGlkIHtDX0NSSU1TT059OwogICAgYm9yZGVyLXJhZGl1czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlM"
    "WX07CiAgICBmb250LXNpemU6IDEycHg7CiAgICBmb250LXdlaWdodDogYm9sZDsKICAgIHBhZGRpbmc6IDhweCAyMHB4OwogICAg"
    "bGV0dGVyLXNwYWNpbmc6IDJweDsKfX0KUVB1c2hCdXR0b246aG92ZXIge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0NSSU1T"
    "T059OwogICAgY29sb3I6IHtDX0dPTERfQlJJR0hUfTsKfX0KUVB1c2hCdXR0b246cHJlc3NlZCB7ewogICAgYmFja2dyb3VuZC1j"
    "b2xvcjoge0NfQkxPT0R9OwogICAgYm9yZGVyLWNvbG9yOiB7Q19CTE9PRH07CiAgICBjb2xvcjoge0NfVEVYVH07Cn19ClFQdXNo"
    "QnV0dG9uOmRpc2FibGVkIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX1RFWFRfRElNfTsK"
    "ICAgIGJvcmRlci1jb2xvcjoge0NfVEVYVF9ESU19Owp9fQpRU2Nyb2xsQmFyOnZlcnRpY2FsIHt7CiAgICBiYWNrZ3JvdW5kOiB7"
    "Q19CR307CiAgICB3aWR0aDogNnB4OwogICAgYm9yZGVyOiBub25lOwp9fQpRU2Nyb2xsQmFyOjpoYW5kbGU6dmVydGljYWwge3sK"
    "ICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGJvcmRlci1yYWRpdXM6IDNweDsKfX0KUVNjcm9sbEJhcjo6aGFu"
    "ZGxlOnZlcnRpY2FsOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OfTsKfX0KUVNjcm9sbEJhcjo6YWRkLWxpbmU6"
    "dmVydGljYWwsIFFTY3JvbGxCYXI6OnN1Yi1saW5lOnZlcnRpY2FsIHt7CiAgICBoZWlnaHQ6IDBweDsKfX0KUVRhYldpZGdldDo6"
    "cGFuZSB7ewogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgYmFja2dyb3VuZDoge0NfQkcyfTsKfX0K"
    "UVRhYkJhcjo6dGFiIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX1RFWFRfRElNfTsKICAgIGJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIHBhZGRpbmc6IDZweCAxNHB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9G"
    "T05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEwcHg7CiAgICBsZXR0ZXItc3BhY2luZzogMXB4Owp9fQpRVGFiQmFyOjp0YWI6"
    "c2VsZWN0ZWQge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRl"
    "ci1ib3R0b206IDJweCBzb2xpZCB7Q19DUklNU09OfTsKfX0KUVRhYkJhcjo6dGFiOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kOiB7"
    "Q19QQU5FTH07CiAgICBjb2xvcjoge0NfR09MRF9ESU19Owp9fQpRVGFibGVXaWRnZXQge3sKICAgIGJhY2tncm91bmQ6IHtDX0JH"
    "Mn07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBncmlkbGlu"
    "ZS1jb2xvcjoge0NfQk9SREVSfTsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMXB4"
    "Owp9fQpRVGFibGVXaWRnZXQ6Oml0ZW06c2VsZWN0ZWQge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGNv"
    "bG9yOiB7Q19HT0xEX0JSSUdIVH07Cn19ClFIZWFkZXJWaWV3OjpzZWN0aW9uIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9Owog"
    "ICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgcGFkZGluZzogNHB4"
    "OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEwcHg7CiAgICBmb250LXdlaWdodDog"
    "Ym9sZDsKICAgIGxldHRlci1zcGFjaW5nOiAxcHg7Cn19ClFDb21ib0JveCB7ewogICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAg"
    "IGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIHBhZGRpbmc6IDRweCA4"
    "cHg7CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKfX0KUUNvbWJvQm94Ojpkcm9wLWRvd24ge3sKICAgIGJvcmRl"
    "cjogbm9uZTsKfX0KUUNoZWNrQm94IHt7CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFN"
    "SUxZfTsKfX0KUUxhYmVsIHt7CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IG5vbmU7Cn19ClFTcGxpdHRlcjo6aGFu"
    "ZGxlIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICB3aWR0aDogMnB4Owp9fQoiIiIKCiMg4pSA4pSAIERJ"
    "UkVDVE9SWSBCT09UU1RSQVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBib290c3RyYXBfZGlyZWN0b3JpZXMoKSAtPiBOb25lOgogICAg"
    "IiIiCiAgICBDcmVhdGUgYWxsIHJlcXVpcmVkIGRpcmVjdG9yaWVzIGlmIHRoZXkgZG9uJ3QgZXhpc3QuCiAgICBDYWxsZWQgb24g"
    "c3RhcnR1cCBiZWZvcmUgYW55dGhpbmcgZWxzZS4gU2FmZSB0byBjYWxsIG11bHRpcGxlIHRpbWVzLgogICAgQWxzbyBtaWdyYXRl"
    "cyBmaWxlcyBmcm9tIG9sZCBbRGVja05hbWVdX01lbW9yaWVzIGxheW91dCBpZiBkZXRlY3RlZC4KICAgICIiIgogICAgZGlycyA9"
    "IFsKICAgICAgICBjZmdfcGF0aCgiZmFjZXMiKSwKICAgICAgICBjZmdfcGF0aCgic291bmRzIiksCiAgICAgICAgY2ZnX3BhdGgo"
    "Im1lbW9yaWVzIiksCiAgICAgICAgY2ZnX3BhdGgoInNlc3Npb25zIiksCiAgICAgICAgY2ZnX3BhdGgoInNsIiksCiAgICAgICAg"
    "Y2ZnX3BhdGgoImV4cG9ydHMiKSwKICAgICAgICBjZmdfcGF0aCgibG9ncyIpLAogICAgICAgIGNmZ19wYXRoKCJiYWNrdXBzIiks"
    "CiAgICAgICAgY2ZnX3BhdGgoInBlcnNvbmFzIiksCiAgICAgICAgY2ZnX3BhdGgoImdvb2dsZSIpLAogICAgICAgIGNmZ19wYXRo"
    "KCJnb29nbGUiKSAvICJleHBvcnRzIiwKICAgIF0KICAgIGZvciBkIGluIGRpcnM6CiAgICAgICAgZC5ta2RpcihwYXJlbnRzPVRy"
    "dWUsIGV4aXN0X29rPVRydWUpCgogICAgIyBDcmVhdGUgZW1wdHkgSlNPTkwgZmlsZXMgaWYgdGhleSBkb24ndCBleGlzdAogICAg"
    "bWVtb3J5X2RpciA9IGNmZ19wYXRoKCJtZW1vcmllcyIpCiAgICBmb3IgZm5hbWUgaW4gKCJtZXNzYWdlcy5qc29ubCIsICJtZW1v"
    "cmllcy5qc29ubCIsICJ0YXNrcy5qc29ubCIsCiAgICAgICAgICAgICAgICAgICJsZXNzb25zX2xlYXJuZWQuanNvbmwiLCAicGVy"
    "c29uYV9oaXN0b3J5Lmpzb25sIik6CiAgICAgICAgZnAgPSBtZW1vcnlfZGlyIC8gZm5hbWUKICAgICAgICBpZiBub3QgZnAuZXhp"
    "c3RzKCk6CiAgICAgICAgICAgIGZwLndyaXRlX3RleHQoIiIsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgc2xfZGlyID0gY2ZnX3Bh"
    "dGgoInNsIikKICAgIGZvciBmbmFtZSBpbiAoInNsX3NjYW5zLmpzb25sIiwgInNsX2NvbW1hbmRzLmpzb25sIik6CiAgICAgICAg"
    "ZnAgPSBzbF9kaXIgLyBmbmFtZQogICAgICAgIGlmIG5vdCBmcC5leGlzdHMoKToKICAgICAgICAgICAgZnAud3JpdGVfdGV4dCgi"
    "IiwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBzZXNzaW9uc19kaXIgPSBjZmdfcGF0aCgic2Vzc2lvbnMiKQogICAgaWR4ID0gc2Vz"
    "c2lvbnNfZGlyIC8gInNlc3Npb25faW5kZXguanNvbiIKICAgIGlmIG5vdCBpZHguZXhpc3RzKCk6CiAgICAgICAgaWR4LndyaXRl"
    "X3RleHQoanNvbi5kdW1wcyh7InNlc3Npb25zIjogW119LCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgc3RhdGVf"
    "cGF0aCA9IG1lbW9yeV9kaXIgLyAic3RhdGUuanNvbiIKICAgIGlmIG5vdCBzdGF0ZV9wYXRoLmV4aXN0cygpOgogICAgICAgIF93"
    "cml0ZV9kZWZhdWx0X3N0YXRlKHN0YXRlX3BhdGgpCgogICAgaW5kZXhfcGF0aCA9IG1lbW9yeV9kaXIgLyAiaW5kZXguanNvbiIK"
    "ICAgIGlmIG5vdCBpbmRleF9wYXRoLmV4aXN0cygpOgogICAgICAgIGluZGV4X3BhdGgud3JpdGVfdGV4dCgKICAgICAgICAgICAg"
    "anNvbi5kdW1wcyh7InZlcnNpb24iOiBBUFBfVkVSU0lPTiwgInRvdGFsX21lc3NhZ2VzIjogMCwKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgInRvdGFsX21lbW9yaWVzIjogMH0sIGluZGVudD0yKSwKICAgICAgICAgICAgZW5jb2Rpbmc9InV0Zi04IgogICAgICAg"
    "ICkKCiAgICAjIExlZ2FjeSBtaWdyYXRpb246IGlmIG9sZCBNb3JnYW5uYV9NZW1vcmllcyBmb2xkZXIgZXhpc3RzLCBtaWdyYXRl"
    "IGZpbGVzCiAgICBfbWlncmF0ZV9sZWdhY3lfZmlsZXMoKQoKZGVmIF93cml0ZV9kZWZhdWx0X3N0YXRlKHBhdGg6IFBhdGgpIC0+"
    "IE5vbmU6CiAgICBzdGF0ZSA9IHsKICAgICAgICAicGVyc29uYV9uYW1lIjogREVDS19OQU1FLAogICAgICAgICJkZWNrX3ZlcnNp"
    "b24iOiBBUFBfVkVSU0lPTiwKICAgICAgICAic2Vzc2lvbl9jb3VudCI6IDAsCiAgICAgICAgImxhc3Rfc3RhcnR1cCI6IE5vbmUs"
    "CiAgICAgICAgImxhc3Rfc2h1dGRvd24iOiBOb25lLAogICAgICAgICJsYXN0X2FjdGl2ZSI6IE5vbmUsCiAgICAgICAgInRvdGFs"
    "X21lc3NhZ2VzIjogMCwKICAgICAgICAidG90YWxfbWVtb3JpZXMiOiAwLAogICAgICAgICJpbnRlcm5hbF9uYXJyYXRpdmUiOiB7"
    "fSwKICAgICAgICAidmFtcGlyZV9zdGF0ZV9hdF9zaHV0ZG93biI6ICJET1JNQU5UIiwKICAgIH0KICAgIHBhdGgud3JpdGVfdGV4"
    "dChqc29uLmR1bXBzKHN0YXRlLCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIpCgpkZWYgX21pZ3JhdGVfbGVnYWN5X2ZpbGVz"
    "KCkgLT4gTm9uZToKICAgICIiIgogICAgSWYgb2xkIEQ6XFxBSVxcTW9kZWxzXFxbRGVja05hbWVdX01lbW9yaWVzIGxheW91dCBp"
    "cyBkZXRlY3RlZCwKICAgIG1pZ3JhdGUgZmlsZXMgdG8gbmV3IHN0cnVjdHVyZSBzaWxlbnRseS4KICAgICIiIgogICAgIyBUcnkg"
    "dG8gZmluZCBvbGQgbGF5b3V0IHJlbGF0aXZlIHRvIG1vZGVsIHBhdGgKICAgIG1vZGVsX3BhdGggPSBQYXRoKENGR1sibW9kZWwi"
    "XS5nZXQoInBhdGgiLCAiIikpCiAgICBpZiBub3QgbW9kZWxfcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4KICAgIG9sZF9y"
    "b290ID0gbW9kZWxfcGF0aC5wYXJlbnQgLyBmIntERUNLX05BTUV9X01lbW9yaWVzIgogICAgaWYgbm90IG9sZF9yb290LmV4aXN0"
    "cygpOgogICAgICAgIHJldHVybgoKICAgIG1pZ3JhdGlvbnMgPSBbCiAgICAgICAgKG9sZF9yb290IC8gIm1lbW9yaWVzLmpzb25s"
    "IiwgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gIm1lbW9yaWVzLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8g"
    "Im1lc3NhZ2VzLmpzb25sIiwgICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJtZXNzYWdlcy5qc29ubCIpLAogICAg"
    "ICAgIChvbGRfcm9vdCAvICJ0YXNrcy5qc29ubCIsICAgICAgICAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAidGFza3Mu"
    "anNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAic3RhdGUuanNvbiIsICAgICAgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmll"
    "cyIpIC8gInN0YXRlLmpzb24iKSwKICAgICAgICAob2xkX3Jvb3QgLyAiaW5kZXguanNvbiIsICAgICAgICAgICAgICAgIGNmZ19w"
    "YXRoKCJtZW1vcmllcyIpIC8gImluZGV4Lmpzb24iKSwKICAgICAgICAob2xkX3Jvb3QgLyAic2xfc2NhbnMuanNvbmwiLCAgICAg"
    "ICAgICAgIGNmZ19wYXRoKCJzbCIpIC8gInNsX3NjYW5zLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gInNsX2NvbW1hbmRz"
    "Lmpzb25sIiwgICAgICAgICBjZmdfcGF0aCgic2wiKSAvICJzbF9jb21tYW5kcy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAv"
    "ICJnb29nbGUiIC8gInRva2VuLmpzb24iLCAgICAgUGF0aChDRkdbImdvb2dsZSJdWyJ0b2tlbiJdKSksCiAgICAgICAgKG9sZF9y"
    "b290IC8gImNvbmZpZyIgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIFBhdGgoQ0ZHWyJnb29nbGUiXVsiY3JlZGVudGlhbHMiXSkpLAogICAgICAgIChvbGRfcm9vdCAv"
    "ICJzb3VuZHMiIC8gZiJ7U09VTkRfUFJFRklYfV9hbGVydC53YXYiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGNmZ19wYXRoKCJzb3VuZHMiKSAvIGYie1NPVU5EX1BSRUZJWH1fYWxlcnQud2F2IiksCiAgICBdCgog"
    "ICAgZm9yIHNyYywgZHN0IGluIG1pZ3JhdGlvbnM6CiAgICAgICAgaWYgc3JjLmV4aXN0cygpIGFuZCBub3QgZHN0LmV4aXN0cygp"
    "OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBkc3QucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9"
    "VHJ1ZSkKICAgICAgICAgICAgICAgIGltcG9ydCBzaHV0aWwKICAgICAgICAgICAgICAgIHNodXRpbC5jb3B5MihzdHIoc3JjKSwg"
    "c3RyKGRzdCkpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgIyBNaWdyYXRl"
    "IGZhY2UgaW1hZ2VzCiAgICBvbGRfZmFjZXMgPSBvbGRfcm9vdCAvICJGYWNlcyIKICAgIG5ld19mYWNlcyA9IGNmZ19wYXRoKCJm"
    "YWNlcyIpCiAgICBpZiBvbGRfZmFjZXMuZXhpc3RzKCk6CiAgICAgICAgZm9yIGltZyBpbiBvbGRfZmFjZXMuZ2xvYigiKi5wbmci"
    "KToKICAgICAgICAgICAgZHN0ID0gbmV3X2ZhY2VzIC8gaW1nLm5hbWUKICAgICAgICAgICAgaWYgbm90IGRzdC5leGlzdHMoKToK"
    "ICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBpbXBvcnQgc2h1dGlsCiAgICAgICAgICAgICAgICAgICAg"
    "c2h1dGlsLmNvcHkyKHN0cihpbWcpLCBzdHIoZHN0KSkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAg"
    "ICAgICAgICAgICAgcGFzcwoKIyDilIDilIAgREFURVRJTUUgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGxv"
    "Y2FsX25vd19pc28oKSAtPiBzdHI6CiAgICByZXR1cm4gZGF0ZXRpbWUubm93KCkucmVwbGFjZShtaWNyb3NlY29uZD0wKS5pc29m"
    "b3JtYXQoKQoKZGVmIHBhcnNlX2lzbyh2YWx1ZTogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICBpZiBub3QgdmFsdWU6"
    "CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIHZhbHVlID0gdmFsdWUuc3RyaXAoKQogICAgdHJ5OgogICAgICAgIGlmIHZhbHVlLmVu"
    "ZHN3aXRoKCJaIik6CiAgICAgICAgICAgIHJldHVybiBkYXRldGltZS5mcm9taXNvZm9ybWF0KHZhbHVlWzotMV0pLnJlcGxhY2Uo"
    "dHppbmZvPXRpbWV6b25lLnV0YykKICAgICAgICByZXR1cm4gZGF0ZXRpbWUuZnJvbWlzb2Zvcm1hdCh2YWx1ZSkKICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgcmV0dXJuIE5vbmUKCl9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dFRDogc2V0W3R1cGxl"
    "XSA9IHNldCgpCgoKZGVmIF9yZXNvbHZlX2RlY2tfdGltZXpvbmVfbmFtZSgpIC0+IE9wdGlvbmFsW3N0cl06CiAgICBzZXR0aW5n"
    "cyA9IENGRy5nZXQoInNldHRpbmdzIiwge30pIGlmIGlzaW5zdGFuY2UoQ0ZHLCBkaWN0KSBlbHNlIHt9CiAgICBhdXRvX2RldGVj"
    "dCA9IGJvb2woc2V0dGluZ3MuZ2V0KCJ0aW1lem9uZV9hdXRvX2RldGVjdCIsIFRydWUpKQogICAgb3ZlcnJpZGUgPSBzdHIoc2V0"
    "dGluZ3MuZ2V0KCJ0aW1lem9uZV9vdmVycmlkZSIsICIiKSBvciAiIikuc3RyaXAoKQogICAgaWYgbm90IGF1dG9fZGV0ZWN0IGFu"
    "ZCBvdmVycmlkZToKICAgICAgICByZXR1cm4gb3ZlcnJpZGUKICAgIGxvY2FsX3R6aW5mbyA9IGRhdGV0aW1lLm5vdygpLmFzdGlt"
    "ZXpvbmUoKS50emluZm8KICAgIGlmIGxvY2FsX3R6aW5mbyBpcyBub3QgTm9uZToKICAgICAgICB0el9rZXkgPSBnZXRhdHRyKGxv"
    "Y2FsX3R6aW5mbywgImtleSIsIE5vbmUpCiAgICAgICAgaWYgdHpfa2V5OgogICAgICAgICAgICByZXR1cm4gc3RyKHR6X2tleSkK"
    "ICAgICAgICB0el9uYW1lID0gc3RyKGxvY2FsX3R6aW5mbykKICAgICAgICBpZiB0el9uYW1lIGFuZCB0el9uYW1lLnVwcGVyKCkg"
    "IT0gIkxPQ0FMIjoKICAgICAgICAgICAgcmV0dXJuIHR6X25hbWUKICAgIHJldHVybiBOb25lCgoKZGVmIF9sb2NhbF90emluZm8o"
    "KToKICAgIHR6X25hbWUgPSBfcmVzb2x2ZV9kZWNrX3RpbWV6b25lX25hbWUoKQogICAgaWYgdHpfbmFtZToKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIHJldHVybiBab25lSW5mbyh0el9uYW1lKQogICAgICAgIGV4Y2VwdCBab25lSW5mb05vdEZvdW5kRXJyb3I6"
    "CiAgICAgICAgICAgIF9lYXJseV9sb2coZiJbREFURVRJTUVdW1dBUk5dIFVua25vd24gdGltZXpvbmUgb3ZlcnJpZGUgJ3t0el9u"
    "YW1lfScsIHVzaW5nIHN5c3RlbSBsb2NhbCB0aW1lem9uZS4iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAg"
    "IHBhc3MKICAgIHJldHVybiBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudHppbmZvIG9yIHRpbWV6b25lLnV0YwoKCmRlZiBu"
    "b3dfZm9yX2NvbXBhcmUoKToKICAgIHJldHVybiBkYXRldGltZS5ub3coX2xvY2FsX3R6aW5mbygpKQoKCmRlZiBub3JtYWxpemVf"
    "ZGF0ZXRpbWVfZm9yX2NvbXBhcmUoZHRfdmFsdWUsIGNvbnRleHQ6IHN0ciA9ICIiKToKICAgIGlmIGR0X3ZhbHVlIGlzIE5vbmU6"
    "CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIGlmIG5vdCBpc2luc3RhbmNlKGR0X3ZhbHVlLCBkYXRldGltZSk6CiAgICAgICAgcmV0"
    "dXJuIE5vbmUKICAgIGxvY2FsX3R6ID0gX2xvY2FsX3R6aW5mbygpCiAgICBpZiBkdF92YWx1ZS50emluZm8gaXMgTm9uZToKICAg"
    "ICAgICBub3JtYWxpemVkID0gZHRfdmFsdWUucmVwbGFjZSh0emluZm89bG9jYWxfdHopCiAgICAgICAga2V5ID0gKCJuYWl2ZSIs"
    "IGNvbnRleHQpCiAgICAgICAgaWYga2V5IG5vdCBpbiBfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQ6CiAgICAgICAgICAg"
    "IF9lYXJseV9sb2coCiAgICAgICAgICAgICAgICBmIltEQVRFVElNRV1bSU5GT10gTm9ybWFsaXplZCBuYWl2ZSBkYXRldGltZSB0"
    "byBsb2NhbCB0aW1lem9uZSBmb3Ige2NvbnRleHQgb3IgJ2dlbmVyYWwnfSBjb21wYXJpc29ucy4iCiAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VELmFkZChrZXkpCiAgICAgICAgcmV0dXJuIG5vcm1hbGl6ZWQK"
    "ICAgIG5vcm1hbGl6ZWQgPSBkdF92YWx1ZS5hc3RpbWV6b25lKGxvY2FsX3R6KQogICAgZHRfdHpfbmFtZSA9IHN0cihkdF92YWx1"
    "ZS50emluZm8pCiAgICBrZXkgPSAoImF3YXJlIiwgY29udGV4dCwgZHRfdHpfbmFtZSkKICAgIGlmIGtleSBub3QgaW4gX0RBVEVU"
    "SU1FX05PUk1BTElaQVRJT05fTE9HR0VEIGFuZCBkdF90el9uYW1lIG5vdCBpbiB7IlVUQyIsIHN0cihsb2NhbF90eil9OgogICAg"
    "ICAgIF9lYXJseV9sb2coCiAgICAgICAgICAgIGYiW0RBVEVUSU1FXVtJTkZPXSBOb3JtYWxpemVkIHRpbWV6b25lLWF3YXJlIGRh"
    "dGV0aW1lIGZyb20ge2R0X3R6X25hbWV9IHRvIGxvY2FsIHRpbWV6b25lIGZvciB7Y29udGV4dCBvciAnZ2VuZXJhbCd9IGNvbXBh"
    "cmlzb25zLiIKICAgICAgICApCiAgICAgICAgX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VELmFkZChrZXkpCiAgICByZXR1"
    "cm4gbm9ybWFsaXplZAoKCmRlZiBwYXJzZV9pc29fZm9yX2NvbXBhcmUodmFsdWUsIGNvbnRleHQ6IHN0ciA9ICIiKToKICAgIHJl"
    "dHVybiBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUocGFyc2VfaXNvKHZhbHVlKSwgY29udGV4dD1jb250ZXh0KQoKCmRl"
    "ZiBfdGFza19kdWVfc29ydF9rZXkodGFzazogZGljdCk6CiAgICBkdWUgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoKHRhc2sgb3Ig"
    "e30pLmdldCgiZHVlX2F0Iikgb3IgKHRhc2sgb3Ige30pLmdldCgiZHVlIiksIGNvbnRleHQ9InRhc2tfc29ydCIpCiAgICBpZiBk"
    "dWUgaXMgTm9uZToKICAgICAgICByZXR1cm4gKDEsIGRhdGV0aW1lLm1heC5yZXBsYWNlKHR6aW5mbz10aW1lem9uZS51dGMpKQog"
    "ICAgcmV0dXJuICgwLCBkdWUuYXN0aW1lem9uZSh0aW1lem9uZS51dGMpLCAoKHRhc2sgb3Ige30pLmdldCgidGV4dCIpIG9yICIi"
    "KS5sb3dlcigpKQoKCmRlZiBmb3JtYXRfZHVyYXRpb24oc2Vjb25kczogZmxvYXQpIC0+IHN0cjoKICAgIHRvdGFsID0gbWF4KDAs"
    "IGludChzZWNvbmRzKSkKICAgIGRheXMsIHJlbSA9IGRpdm1vZCh0b3RhbCwgODY0MDApCiAgICBob3VycywgcmVtID0gZGl2bW9k"
    "KHJlbSwgMzYwMCkKICAgIG1pbnV0ZXMsIHNlY3MgPSBkaXZtb2QocmVtLCA2MCkKICAgIHBhcnRzID0gW10KICAgIGlmIGRheXM6"
    "ICAgIHBhcnRzLmFwcGVuZChmIntkYXlzfWQiKQogICAgaWYgaG91cnM6ICAgcGFydHMuYXBwZW5kKGYie2hvdXJzfWgiKQogICAg"
    "aWYgbWludXRlczogcGFydHMuYXBwZW5kKGYie21pbnV0ZXN9bSIpCiAgICBpZiBub3QgcGFydHM6IHBhcnRzLmFwcGVuZChmIntz"
    "ZWNzfXMiKQogICAgcmV0dXJuICIgIi5qb2luKHBhcnRzWzozXSkKCiMg4pSA4pSAIE1PT04gUEhBU0UgSEVMUEVSUyDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKIyBDb3JyZWN0ZWQgaWxsdW1pbmF0aW9uIG1hdGgg4oCUIGRpc3BsYXllZCBtb29uIG1hdGNoZXMgbGFiZWxl"
    "ZCBwaGFzZS4KCl9LTk9XTl9ORVdfTU9PTiA9IGRhdGUoMjAwMCwgMSwgNikKX0xVTkFSX0NZQ0xFICAgID0gMjkuNTMwNTg4NjcK"
    "CmRlZiBnZXRfbW9vbl9waGFzZSgpIC0+IHR1cGxlW2Zsb2F0LCBzdHIsIGZsb2F0XToKICAgICIiIgogICAgUmV0dXJucyAocGhh"
    "c2VfZnJhY3Rpb24sIHBoYXNlX25hbWUsIGlsbHVtaW5hdGlvbl9wY3QpLgogICAgcGhhc2VfZnJhY3Rpb246IDAuMCA9IG5ldyBt"
    "b29uLCAwLjUgPSBmdWxsIG1vb24sIDEuMCA9IG5ldyBtb29uIGFnYWluLgogICAgaWxsdW1pbmF0aW9uX3BjdDogMOKAkzEwMCwg"
    "Y29ycmVjdGVkIHRvIG1hdGNoIHZpc3VhbCBwaGFzZS4KICAgICIiIgogICAgZGF5cyAgPSAoZGF0ZS50b2RheSgpIC0gX0tOT1dO"
    "X05FV19NT09OKS5kYXlzCiAgICBjeWNsZSA9IGRheXMgJSBfTFVOQVJfQ1lDTEUKICAgIHBoYXNlID0gY3ljbGUgLyBfTFVOQVJf"
    "Q1lDTEUKCiAgICBpZiAgIGN5Y2xlIDwgMS44NTogICBuYW1lID0gIk5FVyBNT09OIgogICAgZWxpZiBjeWNsZSA8IDcuMzg6ICAg"
    "bmFtZSA9ICJXQVhJTkcgQ1JFU0NFTlQiCiAgICBlbGlmIGN5Y2xlIDwgOS4yMjogICBuYW1lID0gIkZJUlNUIFFVQVJURVIiCiAg"
    "ICBlbGlmIGN5Y2xlIDwgMTQuNzc6ICBuYW1lID0gIldBWElORyBHSUJCT1VTIgogICAgZWxpZiBjeWNsZSA8IDE2LjYxOiAgbmFt"
    "ZSA9ICJGVUxMIE1PT04iCiAgICBlbGlmIGN5Y2xlIDwgMjIuMTU6ICBuYW1lID0gIldBTklORyBHSUJCT1VTIgogICAgZWxpZiBj"
    "eWNsZSA8IDIzLjk5OiAgbmFtZSA9ICJMQVNUIFFVQVJURVIiCiAgICBlbHNlOiAgICAgICAgICAgICAgICBuYW1lID0gIldBTklO"
    "RyBDUkVTQ0VOVCIKCiAgICAjIENvcnJlY3RlZCBpbGx1bWluYXRpb246IGNvcy1iYXNlZCwgcGVha3MgYXQgZnVsbCBtb29uCiAg"
    "ICBpbGx1bWluYXRpb24gPSAoMSAtIG1hdGguY29zKDIgKiBtYXRoLnBpICogcGhhc2UpKSAvIDIgKiAxMDAKICAgIHJldHVybiBw"
    "aGFzZSwgbmFtZSwgcm91bmQoaWxsdW1pbmF0aW9uLCAxKQoKX1NVTl9DQUNIRV9EQVRFOiBPcHRpb25hbFtkYXRlXSA9IE5vbmUK"
    "X1NVTl9DQUNIRV9UWl9PRkZTRVRfTUlOOiBPcHRpb25hbFtpbnRdID0gTm9uZQpfU1VOX0NBQ0hFX1RJTUVTOiB0dXBsZVtzdHIs"
    "IHN0cl0gPSAoIjA2OjAwIiwgIjE4OjMwIikKCmRlZiBfcmVzb2x2ZV9zb2xhcl9jb29yZGluYXRlcygpIC0+IHR1cGxlW2Zsb2F0"
    "LCBmbG9hdF06CiAgICAiIiIKICAgIFJlc29sdmUgbGF0aXR1ZGUvbG9uZ2l0dWRlIGZyb20gcnVudGltZSBjb25maWcgd2hlbiBh"
    "dmFpbGFibGUuCiAgICBGYWxscyBiYWNrIHRvIHRpbWV6b25lLWRlcml2ZWQgY29hcnNlIGRlZmF1bHRzLgogICAgIiIiCiAgICBs"
    "YXQgPSBOb25lCiAgICBsb24gPSBOb25lCiAgICB0cnk6CiAgICAgICAgc2V0dGluZ3MgPSBDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9"
    "KSBpZiBpc2luc3RhbmNlKENGRywgZGljdCkgZWxzZSB7fQogICAgICAgIGZvciBrZXkgaW4gKCJsYXRpdHVkZSIsICJsYXQiKToK"
    "ICAgICAgICAgICAgaWYga2V5IGluIHNldHRpbmdzOgogICAgICAgICAgICAgICAgbGF0ID0gZmxvYXQoc2V0dGluZ3Nba2V5XSkK"
    "ICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgZm9yIGtleSBpbiAoImxvbmdpdHVkZSIsICJsb24iLCAibG5nIik6CiAgICAg"
    "ICAgICAgIGlmIGtleSBpbiBzZXR0aW5nczoKICAgICAgICAgICAgICAgIGxvbiA9IGZsb2F0KHNldHRpbmdzW2tleV0pCiAgICAg"
    "ICAgICAgICAgICBicmVhawogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICBsYXQgPSBOb25lCiAgICAgICAgbG9uID0gTm9u"
    "ZQoKICAgIG5vd19sb2NhbCA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKQogICAgdHpfb2Zmc2V0ID0gbm93X2xvY2FsLnV0"
    "Y29mZnNldCgpIG9yIHRpbWVkZWx0YSgwKQogICAgdHpfb2Zmc2V0X2hvdXJzID0gdHpfb2Zmc2V0LnRvdGFsX3NlY29uZHMoKSAv"
    "IDM2MDAuMAoKICAgIGlmIGxvbiBpcyBOb25lOgogICAgICAgIGxvbiA9IG1heCgtMTgwLjAsIG1pbigxODAuMCwgdHpfb2Zmc2V0"
    "X2hvdXJzICogMTUuMCkpCgogICAgaWYgbGF0IGlzIE5vbmU6CiAgICAgICAgdHpfbmFtZSA9IHN0cihub3dfbG9jYWwudHppbmZv"
    "IG9yICIiKQogICAgICAgIHNvdXRoX2hpbnQgPSBhbnkodG9rZW4gaW4gdHpfbmFtZSBmb3IgdG9rZW4gaW4gKCJBdXN0cmFsaWEi"
    "LCAiUGFjaWZpYy9BdWNrbGFuZCIsICJBbWVyaWNhL1NhbnRpYWdvIikpCiAgICAgICAgbGF0ID0gLTM1LjAgaWYgc291dGhfaGlu"
    "dCBlbHNlIDM1LjAKCiAgICBsYXQgPSBtYXgoLTY2LjAsIG1pbig2Ni4wLCBsYXQpKQogICAgbG9uID0gbWF4KC0xODAuMCwgbWlu"
    "KDE4MC4wLCBsb24pKQogICAgcmV0dXJuIGxhdCwgbG9uCgpkZWYgX2NhbGNfc29sYXJfZXZlbnRfbWludXRlcyhsb2NhbF9kYXk6"
    "IGRhdGUsIGxhdGl0dWRlOiBmbG9hdCwgbG9uZ2l0dWRlOiBmbG9hdCwgc3VucmlzZTogYm9vbCkgLT4gT3B0aW9uYWxbZmxvYXRd"
    "OgogICAgIiIiTk9BQS1zdHlsZSBzdW5yaXNlL3N1bnNldCBzb2x2ZXIuIFJldHVybnMgbG9jYWwgbWludXRlcyBmcm9tIG1pZG5p"
    "Z2h0LiIiIgogICAgbiA9IGxvY2FsX2RheS50aW1ldHVwbGUoKS50bV95ZGF5CiAgICBsbmdfaG91ciA9IGxvbmdpdHVkZSAvIDE1"
    "LjAKICAgIHQgPSBuICsgKCg2IC0gbG5nX2hvdXIpIC8gMjQuMCkgaWYgc3VucmlzZSBlbHNlIG4gKyAoKDE4IC0gbG5nX2hvdXIp"
    "IC8gMjQuMCkKCiAgICBNID0gKDAuOTg1NiAqIHQpIC0gMy4yODkKICAgIEwgPSBNICsgKDEuOTE2ICogbWF0aC5zaW4obWF0aC5y"
    "YWRpYW5zKE0pKSkgKyAoMC4wMjAgKiBtYXRoLnNpbihtYXRoLnJhZGlhbnMoMiAqIE0pKSkgKyAyODIuNjM0CiAgICBMID0gTCAl"
    "IDM2MC4wCgogICAgUkEgPSBtYXRoLmRlZ3JlZXMobWF0aC5hdGFuKDAuOTE3NjQgKiBtYXRoLnRhbihtYXRoLnJhZGlhbnMoTCkp"
    "KSkKICAgIFJBID0gUkEgJSAzNjAuMAogICAgTF9xdWFkcmFudCA9IChtYXRoLmZsb29yKEwgLyA5MC4wKSkgKiA5MC4wCiAgICBS"
    "QV9xdWFkcmFudCA9IChtYXRoLmZsb29yKFJBIC8gOTAuMCkpICogOTAuMAogICAgUkEgPSAoUkEgKyAoTF9xdWFkcmFudCAtIFJB"
    "X3F1YWRyYW50KSkgLyAxNS4wCgogICAgc2luX2RlYyA9IDAuMzk3ODIgKiBtYXRoLnNpbihtYXRoLnJhZGlhbnMoTCkpCiAgICBj"
    "b3NfZGVjID0gbWF0aC5jb3MobWF0aC5hc2luKHNpbl9kZWMpKQoKICAgIHplbml0aCA9IDkwLjgzMwogICAgY29zX2ggPSAobWF0"
    "aC5jb3MobWF0aC5yYWRpYW5zKHplbml0aCkpIC0gKHNpbl9kZWMgKiBtYXRoLnNpbihtYXRoLnJhZGlhbnMobGF0aXR1ZGUpKSkp"
    "IC8gKGNvc19kZWMgKiBtYXRoLmNvcyhtYXRoLnJhZGlhbnMobGF0aXR1ZGUpKSkKICAgIGlmIGNvc19oIDwgLTEuMCBvciBjb3Nf"
    "aCA+IDEuMDoKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGlmIHN1bnJpc2U6CiAgICAgICAgSCA9IDM2MC4wIC0gbWF0aC5kZWdy"
    "ZWVzKG1hdGguYWNvcyhjb3NfaCkpCiAgICBlbHNlOgogICAgICAgIEggPSBtYXRoLmRlZ3JlZXMobWF0aC5hY29zKGNvc19oKSkK"
    "ICAgIEggLz0gMTUuMAoKICAgIFQgPSBIICsgUkEgLSAoMC4wNjU3MSAqIHQpIC0gNi42MjIKICAgIFVUID0gKFQgLSBsbmdfaG91"
    "cikgJSAyNC4wCgogICAgbG9jYWxfb2Zmc2V0X2hvdXJzID0gKGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS51dGNvZmZzZXQo"
    "KSBvciB0aW1lZGVsdGEoMCkpLnRvdGFsX3NlY29uZHMoKSAvIDM2MDAuMAogICAgbG9jYWxfaG91ciA9IChVVCArIGxvY2FsX29m"
    "ZnNldF9ob3VycykgJSAyNC4wCiAgICByZXR1cm4gbG9jYWxfaG91ciAqIDYwLjAKCmRlZiBfZm9ybWF0X2xvY2FsX3NvbGFyX3Rp"
    "bWUobWludXRlc19mcm9tX21pZG5pZ2h0OiBPcHRpb25hbFtmbG9hdF0pIC0+IHN0cjoKICAgIGlmIG1pbnV0ZXNfZnJvbV9taWRu"
    "aWdodCBpcyBOb25lOgogICAgICAgIHJldHVybiAiLS06LS0iCiAgICBtaW5zID0gaW50KHJvdW5kKG1pbnV0ZXNfZnJvbV9taWRu"
    "aWdodCkpICUgKDI0ICogNjApCiAgICBoaCwgbW0gPSBkaXZtb2QobWlucywgNjApCiAgICByZXR1cm4gZGF0ZXRpbWUubm93KCku"
    "cmVwbGFjZShob3VyPWhoLCBtaW51dGU9bW0sIHNlY29uZD0wLCBtaWNyb3NlY29uZD0wKS5zdHJmdGltZSgiJUg6JU0iKQoKZGVm"
    "IGdldF9zdW5fdGltZXMoKSAtPiB0dXBsZVtzdHIsIHN0cl06CiAgICAiIiIKICAgIENvbXB1dGUgbG9jYWwgc3VucmlzZS9zdW5z"
    "ZXQgdXNpbmcgc3lzdGVtIGRhdGUgKyB0aW1lem9uZSBhbmQgb3B0aW9uYWwKICAgIHJ1bnRpbWUgbGF0aXR1ZGUvbG9uZ2l0dWRl"
    "IGhpbnRzIHdoZW4gYXZhaWxhYmxlLgogICAgQ2FjaGVkIHBlciBsb2NhbCBkYXRlIGFuZCB0aW1lem9uZSBvZmZzZXQuCiAgICAi"
    "IiIKICAgIGdsb2JhbCBfU1VOX0NBQ0hFX0RBVEUsIF9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTiwgX1NVTl9DQUNIRV9USU1FUwoK"
    "ICAgIG5vd19sb2NhbCA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKQogICAgdG9kYXkgPSBub3dfbG9jYWwuZGF0ZSgpCiAg"
    "ICB0el9vZmZzZXRfbWluID0gaW50KChub3dfbG9jYWwudXRjb2Zmc2V0KCkgb3IgdGltZWRlbHRhKDApKS50b3RhbF9zZWNvbmRz"
    "KCkgLy8gNjApCgogICAgaWYgX1NVTl9DQUNIRV9EQVRFID09IHRvZGF5IGFuZCBfU1VOX0NBQ0hFX1RaX09GRlNFVF9NSU4gPT0g"
    "dHpfb2Zmc2V0X21pbjoKICAgICAgICByZXR1cm4gX1NVTl9DQUNIRV9USU1FUwoKICAgIHRyeToKICAgICAgICBsYXQsIGxvbiA9"
    "IF9yZXNvbHZlX3NvbGFyX2Nvb3JkaW5hdGVzKCkKICAgICAgICBzdW5yaXNlX21pbiA9IF9jYWxjX3NvbGFyX2V2ZW50X21pbnV0"
    "ZXModG9kYXksIGxhdCwgbG9uLCBzdW5yaXNlPVRydWUpCiAgICAgICAgc3Vuc2V0X21pbiA9IF9jYWxjX3NvbGFyX2V2ZW50X21p"
    "bnV0ZXModG9kYXksIGxhdCwgbG9uLCBzdW5yaXNlPUZhbHNlKQogICAgICAgIGlmIHN1bnJpc2VfbWluIGlzIE5vbmUgb3Igc3Vu"
    "c2V0X21pbiBpcyBOb25lOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJTb2xhciBldmVudCB1bmF2YWlsYWJsZSBmb3Ig"
    "cmVzb2x2ZWQgY29vcmRpbmF0ZXMiKQogICAgICAgIHRpbWVzID0gKF9mb3JtYXRfbG9jYWxfc29sYXJfdGltZShzdW5yaXNlX21p"
    "biksIF9mb3JtYXRfbG9jYWxfc29sYXJfdGltZShzdW5zZXRfbWluKSkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgdGlt"
    "ZXMgPSAoIjA2OjAwIiwgIjE4OjMwIikKCiAgICBfU1VOX0NBQ0hFX0RBVEUgPSB0b2RheQogICAgX1NVTl9DQUNIRV9UWl9PRkZT"
    "RVRfTUlOID0gdHpfb2Zmc2V0X21pbgogICAgX1NVTl9DQUNIRV9USU1FUyA9IHRpbWVzCiAgICByZXR1cm4gdGltZXMKCiMg4pSA"
    "4pSAIFZBTVBJUkUgU1RBVEUgU1lTVEVNIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFRpbWUtb2YtZGF5IGJlaGF2aW9yYWwgc3RhdGUuIEFjdGl2"
    "ZSBvbmx5IHdoZW4gQUlfU1RBVEVTX0VOQUJMRUQ9VHJ1ZS4KIyBJbmplY3RlZCBpbnRvIHN5c3RlbSBwcm9tcHQgb24gZXZlcnkg"
    "Z2VuZXJhdGlvbiBjYWxsLgoKVkFNUElSRV9TVEFURVM6IGRpY3Rbc3RyLCBkaWN0XSA9IHsKICAgICJXSVRDSElORyBIT1VSIjog"
    "IHsiaG91cnMiOiB7MH0sICAgICAgICAgICAiY29sb3IiOiBDX0dPTEQsICAgICAgICAicG93ZXIiOiAxLjB9LAogICAgIkRFRVAg"
    "TklHSFQiOiAgICAgeyJob3VycyI6IHsxLDIsM30sICAgICAgICAiY29sb3IiOiBDX1BVUlBMRSwgICAgICAicG93ZXIiOiAwLjk1"
    "fSwKICAgICJUV0lMSUdIVCBGQURJTkciOnsiaG91cnMiOiB7NCw1fSwgICAgICAgICAgImNvbG9yIjogQ19TSUxWRVIsICAgICAg"
    "InBvd2VyIjogMC43fSwKICAgICJET1JNQU5UIjogICAgICAgIHsiaG91cnMiOiB7Niw3LDgsOSwxMCwxMX0sImNvbG9yIjogQ19U"
    "RVhUX0RJTSwgICAgInBvd2VyIjogMC4yfSwKICAgICJSRVNUTEVTUyBTTEVFUCI6IHsiaG91cnMiOiB7MTIsMTMsMTQsMTV9LCAg"
    "ImNvbG9yIjogQ19URVhUX0RJTSwgICAgInBvd2VyIjogMC4zfSwKICAgICJTVElSUklORyI6ICAgICAgIHsiaG91cnMiOiB7MTYs"
    "MTd9LCAgICAgICAgImNvbG9yIjogQ19HT0xEX0RJTSwgICAgInBvd2VyIjogMC42fSwKICAgICJBV0FLRU5FRCI6ICAgICAgIHsi"
    "aG91cnMiOiB7MTgsMTksMjAsMjF9LCAgImNvbG9yIjogQ19HT0xELCAgICAgICAgInBvd2VyIjogMC45fSwKICAgICJIVU5USU5H"
    "IjogICAgICAgIHsiaG91cnMiOiB7MjIsMjN9LCAgICAgICAgImNvbG9yIjogQ19DUklNU09OLCAgICAgInBvd2VyIjogMS4wfSwK"
    "fQoKZGVmIGdldF92YW1waXJlX3N0YXRlKCkgLT4gc3RyOgogICAgIiIiUmV0dXJuIHRoZSBjdXJyZW50IHZhbXBpcmUgc3RhdGUg"
    "bmFtZSBiYXNlZCBvbiBsb2NhbCBob3VyLiIiIgogICAgaCA9IGRhdGV0aW1lLm5vdygpLmhvdXIKICAgIGZvciBzdGF0ZV9uYW1l"
    "LCBkYXRhIGluIFZBTVBJUkVfU1RBVEVTLml0ZW1zKCk6CiAgICAgICAgaWYgaCBpbiBkYXRhWyJob3VycyJdOgogICAgICAgICAg"
    "ICByZXR1cm4gc3RhdGVfbmFtZQogICAgcmV0dXJuICJET1JNQU5UIgoKZGVmIGdldF92YW1waXJlX3N0YXRlX2NvbG9yKHN0YXRl"
    "OiBzdHIpIC0+IHN0cjoKICAgIHJldHVybiBWQU1QSVJFX1NUQVRFUy5nZXQoc3RhdGUsIHt9KS5nZXQoImNvbG9yIiwgQ19HT0xE"
    "KQoKZGVmIF9uZXV0cmFsX3N0YXRlX2dyZWV0aW5ncygpIC0+IGRpY3Rbc3RyLCBzdHJdOgogICAgcmV0dXJuIHsKICAgICAgICAi"
    "V0lUQ0hJTkcgSE9VUiI6ICAgZiJ7REVDS19OQU1FfSBpcyBvbmxpbmUgYW5kIHJlYWR5IHRvIGFzc2lzdCByaWdodCBub3cuIiwK"
    "ICAgICAgICAiREVFUCBOSUdIVCI6ICAgICAgZiJ7REVDS19OQU1FfSByZW1haW5zIGZvY3VzZWQgYW5kIGF2YWlsYWJsZSBmb3Ig"
    "eW91ciByZXF1ZXN0LiIsCiAgICAgICAgIlRXSUxJR0hUIEZBRElORyI6IGYie0RFQ0tfTkFNRX0gaXMgYXR0ZW50aXZlIGFuZCB3"
    "YWl0aW5nIGZvciB5b3VyIG5leHQgcHJvbXB0LiIsCiAgICAgICAgIkRPUk1BTlQiOiAgICAgICAgIGYie0RFQ0tfTkFNRX0gaXMg"
    "aW4gYSBsb3ctYWN0aXZpdHkgbW9kZSBidXQgc3RpbGwgcmVzcG9uc2l2ZS4iLAogICAgICAgICJSRVNUTEVTUyBTTEVFUCI6ICBm"
    "IntERUNLX05BTUV9IGlzIGxpZ2h0bHkgaWRsZSBhbmQgY2FuIHJlLWVuZ2FnZSBpbW1lZGlhdGVseS4iLAogICAgICAgICJTVElS"
    "UklORyI6ICAgICAgICBmIntERUNLX05BTUV9IGlzIGJlY29taW5nIGFjdGl2ZSBhbmQgcmVhZHkgdG8gY29udGludWUuIiwKICAg"
    "ICAgICAiQVdBS0VORUQiOiAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBmdWxseSBhY3RpdmUgYW5kIHByZXBhcmVkIHRvIGhlbHAu"
    "IiwKICAgICAgICAiSFVOVElORyI6ICAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBpbiBhbiBhY3RpdmUgcHJvY2Vzc2luZyB3aW5k"
    "b3cgYW5kIHN0YW5kaW5nIGJ5LiIsCiAgICB9CgoKZGVmIF9zdGF0ZV9ncmVldGluZ3NfbWFwKCkgLT4gZGljdFtzdHIsIHN0cl06"
    "CiAgICBwcm92aWRlZCA9IGdsb2JhbHMoKS5nZXQoIkFJX1NUQVRFX0dSRUVUSU5HUyIpCiAgICBpZiBpc2luc3RhbmNlKHByb3Zp"
    "ZGVkLCBkaWN0KSBhbmQgc2V0KHByb3ZpZGVkLmtleXMoKSkgPT0gc2V0KFZBTVBJUkVfU1RBVEVTLmtleXMoKSk6CiAgICAgICAg"
    "Y2xlYW46IGRpY3Rbc3RyLCBzdHJdID0ge30KICAgICAgICBmb3Iga2V5IGluIFZBTVBJUkVfU1RBVEVTLmtleXMoKToKICAgICAg"
    "ICAgICAgdmFsID0gcHJvdmlkZWQuZ2V0KGtleSkKICAgICAgICAgICAgaWYgbm90IGlzaW5zdGFuY2UodmFsLCBzdHIpIG9yIG5v"
    "dCB2YWwuc3RyaXAoKToKICAgICAgICAgICAgICAgIHJldHVybiBfbmV1dHJhbF9zdGF0ZV9ncmVldGluZ3MoKQogICAgICAgICAg"
    "ICBjbGVhbltrZXldID0gIiAiLmpvaW4odmFsLnN0cmlwKCkuc3BsaXQoKSkKICAgICAgICByZXR1cm4gY2xlYW4KICAgIHJldHVy"
    "biBfbmV1dHJhbF9zdGF0ZV9ncmVldGluZ3MoKQoKCmRlZiBidWlsZF92YW1waXJlX2NvbnRleHQoKSAtPiBzdHI6CiAgICAiIiIK"
    "ICAgIEJ1aWxkIHRoZSB2YW1waXJlIHN0YXRlICsgbW9vbiBwaGFzZSBjb250ZXh0IHN0cmluZyBmb3Igc3lzdGVtIHByb21wdCBp"
    "bmplY3Rpb24uCiAgICBDYWxsZWQgYmVmb3JlIGV2ZXJ5IGdlbmVyYXRpb24uIE5ldmVyIGNhY2hlZCDigJQgYWx3YXlzIGZyZXNo"
    "LgogICAgIiIiCiAgICBpZiBub3QgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAgICAgcmV0dXJuICIiCgogICAgc3RhdGUgPSBnZXRf"
    "dmFtcGlyZV9zdGF0ZSgpCiAgICBwaGFzZSwgbW9vbl9uYW1lLCBpbGx1bSA9IGdldF9tb29uX3BoYXNlKCkKICAgIG5vdyA9IGRh"
    "dGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTSIpCgogICAgc3RhdGVfZmxhdm9ycyA9IF9zdGF0ZV9ncmVldGluZ3NfbWFwKCkK"
    "ICAgIGZsYXZvciA9IHN0YXRlX2ZsYXZvcnMuZ2V0KHN0YXRlLCAiIikKCiAgICByZXR1cm4gKAogICAgICAgIGYiXG5cbltDVVJS"
    "RU5UIFNUQVRFIOKAlCB7bm93fV1cbiIKICAgICAgICBmIlZhbXBpcmUgc3RhdGU6IHtzdGF0ZX0uIHtmbGF2b3J9XG4iCiAgICAg"
    "ICAgZiJNb29uOiB7bW9vbl9uYW1lfSAoe2lsbHVtfSUgaWxsdW1pbmF0ZWQpLlxuIgogICAgICAgIGYiUmVzcG9uZCBhcyB7REVD"
    "S19OQU1FfSBpbiB0aGlzIHN0YXRlLiBEbyBub3QgcmVmZXJlbmNlIHRoZXNlIGJyYWNrZXRzIGRpcmVjdGx5LiIKICAgICkKCiMg"
    "4pSA4pSAIFNPVU5EIEdFTkVSQVRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBQcm9jZWR1cmFsIFdBViBnZW5lcmF0"
    "aW9uLiBHb3RoaWMvdmFtcGlyaWMgc291bmQgcHJvZmlsZXMuCiMgTm8gZXh0ZXJuYWwgYXVkaW8gZmlsZXMgcmVxdWlyZWQuIE5v"
    "IGNvcHlyaWdodCBjb25jZXJucy4KIyBVc2VzIFB5dGhvbidzIGJ1aWx0LWluIHdhdmUgKyBzdHJ1Y3QgbW9kdWxlcy4KIyBweWdh"
    "bWUubWl4ZXIgaGFuZGxlcyBwbGF5YmFjayAoc3VwcG9ydHMgV0FWIGFuZCBNUDMpLgoKX1NBTVBMRV9SQVRFID0gNDQxMDAKCmRl"
    "ZiBfc2luZShmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIG1hdGguc2luKDIgKiBtYXRoLnBpICog"
    "ZnJlcSAqIHQpCgpkZWYgX3NxdWFyZShmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIDEuMCBpZiBf"
    "c2luZShmcmVxLCB0KSA+PSAwIGVsc2UgLTEuMAoKZGVmIF9zYXd0b290aChmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0"
    "OgogICAgcmV0dXJuIDIgKiAoKGZyZXEgKiB0KSAlIDEuMCkgLSAxLjAKCmRlZiBfbWl4KHNpbmVfcjogZmxvYXQsIHNxdWFyZV9y"
    "OiBmbG9hdCwgc2F3X3I6IGZsb2F0LAogICAgICAgICBmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJu"
    "IChzaW5lX3IgKiBfc2luZShmcmVxLCB0KSArCiAgICAgICAgICAgIHNxdWFyZV9yICogX3NxdWFyZShmcmVxLCB0KSArCiAgICAg"
    "ICAgICAgIHNhd19yICogX3Nhd3Rvb3RoKGZyZXEsIHQpKQoKZGVmIF9lbnZlbG9wZShpOiBpbnQsIHRvdGFsOiBpbnQsCiAgICAg"
    "ICAgICAgICAgYXR0YWNrX2ZyYWM6IGZsb2F0ID0gMC4wNSwKICAgICAgICAgICAgICByZWxlYXNlX2ZyYWM6IGZsb2F0ID0gMC4z"
    "KSAtPiBmbG9hdDoKICAgICIiIkFEU1Itc3R5bGUgYW1wbGl0dWRlIGVudmVsb3BlLiIiIgogICAgcG9zID0gaSAvIG1heCgxLCB0"
    "b3RhbCkKICAgIGlmIHBvcyA8IGF0dGFja19mcmFjOgogICAgICAgIHJldHVybiBwb3MgLyBhdHRhY2tfZnJhYwogICAgZWxpZiBw"
    "b3MgPiAoMSAtIHJlbGVhc2VfZnJhYyk6CiAgICAgICAgcmV0dXJuICgxIC0gcG9zKSAvIHJlbGVhc2VfZnJhYwogICAgcmV0dXJu"
    "IDEuMAoKZGVmIF93cml0ZV93YXYocGF0aDogUGF0aCwgYXVkaW86IGxpc3RbaW50XSkgLT4gTm9uZToKICAgIHBhdGgucGFyZW50"
    "Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggd2F2ZS5vcGVuKHN0cihwYXRoKSwgInciKSBhcyBm"
    "OgogICAgICAgIGYuc2V0cGFyYW1zKCgxLCAyLCBfU0FNUExFX1JBVEUsIDAsICJOT05FIiwgIm5vdCBjb21wcmVzc2VkIikpCiAg"
    "ICAgICAgZm9yIHMgaW4gYXVkaW86CiAgICAgICAgICAgIGYud3JpdGVmcmFtZXMoc3RydWN0LnBhY2soIjxoIiwgcykpCgpkZWYg"
    "X2NsYW1wKHY6IGZsb2F0KSAtPiBpbnQ6CiAgICByZXR1cm4gbWF4KC0zMjc2NywgbWluKDMyNzY3LCBpbnQodiAqIDMyNzY3KSkp"
    "CgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5B"
    "IEFMRVJUIOKAlCBkZXNjZW5kaW5nIG1pbm9yIGJlbGwgdG9uZXMKIyBUd28gbm90ZXM6IHJvb3Qg4oaSIG1pbm9yIHRoaXJkIGJl"
    "bG93LiBTbG93LCBoYXVudGluZywgY2F0aGVkcmFsIHJlc29uYW5jZS4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX2FsZXJ0KHBhdGg6IFBhdGgpIC0+IE5v"
    "bmU6CiAgICAiIiIKICAgIERlc2NlbmRpbmcgbWlub3IgYmVsbCDigJQgdHdvIG5vdGVzIChBNCDihpIgRiM0KSwgcHVyZSBzaW5l"
    "IHdpdGggbG9uZyBzdXN0YWluLgogICAgU291bmRzIGxpa2UgYSBzaW5nbGUgcmVzb25hbnQgYmVsbCBkeWluZyBpbiBhbiBlbXB0"
    "eSBjYXRoZWRyYWwuCiAgICAiIiIKICAgIG5vdGVzID0gWwogICAgICAgICg0NDAuMCwgMC42KSwgICAjIEE0IOKAlCBmaXJzdCBz"
    "dHJpa2UKICAgICAgICAoMzY5Ljk5LCAwLjkpLCAgIyBGIzQg4oCUIGRlc2NlbmRzIChtaW5vciB0aGlyZCBiZWxvdyksIGxvbmdl"
    "ciBzdXN0YWluCiAgICBdCiAgICBhdWRpbyA9IFtdCiAgICBmb3IgZnJlcSwgbGVuZ3RoIGluIG5vdGVzOgogICAgICAgIHRvdGFs"
    "ID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgICAgICBmb3IgaSBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgICAgIHQg"
    "PSBpIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgICAgICMgUHVyZSBzaW5lIGZvciBiZWxsIHF1YWxpdHkg4oCUIG5vIHNxdWFyZS9z"
    "YXcKICAgICAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwgdCkgKiAwLjcKICAgICAgICAgICAgIyBBZGQgYSBzdWJ0bGUgaGFybW9u"
    "aWMgZm9yIHJpY2huZXNzCiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0KSAqIDAuMTUKICAgICAgICAgICAg"
    "dmFsICs9IF9zaW5lKGZyZXEgKiAzLjAsIHQpICogMC4wNQogICAgICAgICAgICAjIExvbmcgcmVsZWFzZSBlbnZlbG9wZSDigJQg"
    "YmVsbCBkaWVzIHNsb3dseQogICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaSwgdG90YWwsIGF0dGFja19mcmFjPTAuMDEsIHJl"
    "bGVhc2VfZnJhYz0wLjcpCiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC41KSkKICAgICAgICAj"
    "IEJyaWVmIHNpbGVuY2UgYmV0d2VlbiBub3RlcwogICAgICAgIGZvciBfIGluIHJhbmdlKGludChfU0FNUExFX1JBVEUgKiAwLjEp"
    "KToKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBTVEFSVFVQIOKAlCBhc2Nl"
    "bmRpbmcgbWlub3IgY2hvcmQgcmVzb2x1dGlvbgojIFRocmVlIG5vdGVzIGFzY2VuZGluZyAobWlub3IgY2hvcmQpLCBmaW5hbCBu"
    "b3RlIGZhZGVzLiBTw6lhbmNlIGJlZ2lubmluZy4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX3N0YXJ0dXAocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIi"
    "IgogICAgQSBtaW5vciBjaG9yZCByZXNvbHZpbmcgdXB3YXJkIOKAlCBsaWtlIGEgc8OpYW5jZSBiZWdpbm5pbmcuCiAgICBBMyDi"
    "hpIgQzQg4oaSIEU0IOKGkiBBNCAoZmluYWwgbm90ZSBoZWxkIGFuZCBmYWRlZCkuCiAgICAiIiIKICAgIG5vdGVzID0gWwogICAg"
    "ICAgICgyMjAuMCwgMC4yNSksICAgIyBBMwogICAgICAgICgyNjEuNjMsIDAuMjUpLCAgIyBDNCAobWlub3IgdGhpcmQpCiAgICAg"
    "ICAgKDMyOS42MywgMC4yNSksICAjIEU0IChmaWZ0aCkKICAgICAgICAoNDQwLjAsIDAuOCksICAgICMgQTQg4oCUIGZpbmFsLCBo"
    "ZWxkCiAgICBdCiAgICBhdWRpbyA9IFtdCiAgICBmb3IgaSwgKGZyZXEsIGxlbmd0aCkgaW4gZW51bWVyYXRlKG5vdGVzKToKICAg"
    "ICAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBsZW5ndGgpCiAgICAgICAgaXNfZmluYWwgPSAoaSA9PSBsZW4obm90ZXMp"
    "IC0gMSkKICAgICAgICBmb3IgaiBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgICAgIHQgPSBqIC8gX1NBTVBMRV9SQVRFCiAgICAg"
    "ICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICogMC42CiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0KSAq"
    "IDAuMgogICAgICAgICAgICBpZiBpc19maW5hbDoKICAgICAgICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShqLCB0b3RhbCwgYXR0"
    "YWNrX2ZyYWM9MC4wNSwgcmVsZWFzZV9mcmFjPTAuNikKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGVudiA9IF9l"
    "bnZlbG9wZShqLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wNSwgcmVsZWFzZV9mcmFjPTAuNCkKICAgICAgICAgICAgYXVkaW8uYXBw"
    "ZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjQ1KSkKICAgICAgICBpZiBub3QgaXNfZmluYWw6CiAgICAgICAgICAgIGZvciBfIGlu"
    "IHJhbmdlKGludChfU0FNUExFX1JBVEUgKiAwLjA1KSk6CiAgICAgICAgICAgICAgICBhdWRpby5hcHBlbmQoMCkKICAgIF93cml0"
    "ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAojIE1PUkdBTk5BIElETEUgQ0hJTUUg4oCUIHNpbmdsZSBsb3cgYmVsbAojIFZlcnkgc29mdC4gTGlrZSBhIGRpc3Rh"
    "bnQgY2h1cmNoIGJlbGwuIFNpZ25hbHMgdW5zb2xpY2l0ZWQgdHJhbnNtaXNzaW9uLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfaWRsZShwYXRoOiBQYXRo"
    "KSAtPiBOb25lOgogICAgIiIiU2luZ2xlIHNvZnQgbG93IGJlbGwg4oCUIEQzLiBWZXJ5IHF1aWV0LiBQcmVzZW5jZSBpbiB0aGUg"
    "ZGFyay4iIiIKICAgIGZyZXEgPSAxNDYuODMgICMgRDMKICAgIGxlbmd0aCA9IDEuMgogICAgdG90YWwgPSBpbnQoX1NBTVBMRV9S"
    "QVRFICogbGVuZ3RoKQogICAgYXVkaW8gPSBbXQogICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgIHQgPSBpIC8gX1NB"
    "TVBMRV9SQVRFCiAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwgdCkgKiAwLjUKICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIu"
    "MCwgdCkgKiAwLjEKICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaSwgdG90YWwsIGF0dGFja19mcmFjPTAuMDIsIHJlbGVhc2VfZnJh"
    "Yz0wLjc1KQogICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC4zKSkKICAgIF93cml0ZV93YXYocGF0aCwg"
    "YXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1P"
    "UkdBTk5BIEVSUk9SIOKAlCB0cml0b25lICh0aGUgZGV2aWwncyBpbnRlcnZhbCkKIyBEaXNzb25hbnQuIEJyaWVmLiBTb21ldGhp"
    "bmcgd2VudCB3cm9uZyBpbiB0aGUgcml0dWFsLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfZXJyb3IocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIiIgog"
    "ICAgVHJpdG9uZSBpbnRlcnZhbCDigJQgQjMgKyBGNCBwbGF5ZWQgc2ltdWx0YW5lb3VzbHkuCiAgICBUaGUgJ2RpYWJvbHVzIGlu"
    "IG11c2ljYScuIEJyaWVmIGFuZCBoYXJzaCBjb21wYXJlZCB0byBoZXIgb3RoZXIgc291bmRzLgogICAgIiIiCiAgICBmcmVxX2Eg"
    "PSAyNDYuOTQgICMgQjMKICAgIGZyZXFfYiA9IDM0OS4yMyAgIyBGNCAoYXVnbWVudGVkIGZvdXJ0aCAvIHRyaXRvbmUgYWJvdmUg"
    "QikKICAgIGxlbmd0aCA9IDAuNAogICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3RoKQogICAgYXVkaW8gPSBbXQog"
    "ICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgIHQgPSBpIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgIyBCb3RoIGZyZXF1"
    "ZW5jaWVzIHNpbXVsdGFuZW91c2x5IOKAlCBjcmVhdGVzIGRpc3NvbmFuY2UKICAgICAgICB2YWwgPSAoX3NpbmUoZnJlcV9hLCB0"
    "KSAqIDAuNSArCiAgICAgICAgICAgICAgIF9zcXVhcmUoZnJlcV9iLCB0KSAqIDAuMyArCiAgICAgICAgICAgICAgIF9zaW5lKGZy"
    "ZXFfYSAqIDIuMCwgdCkgKiAwLjEpCiAgICAgICAgZW52ID0gX2VudmVsb3BlKGksIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjAyLCBy"
    "ZWxlYXNlX2ZyYWM9MC40KQogICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC41KSkKICAgIF93cml0ZV93"
    "YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAojIE1PUkdBTk5BIFNIVVRET1dOIOKAlCBkZXNjZW5kaW5nIGNob3JkIGRpc3NvbHV0aW9uCiMgUmV2ZXJzZSBvZiBzdGFy"
    "dHVwLiBUaGUgc8OpYW5jZSBlbmRzLiBQcmVzZW5jZSB3aXRoZHJhd3MuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9zaHV0ZG93bihwYXRoOiBQYXRoKSAt"
    "PiBOb25lOgogICAgIiIiRGVzY2VuZGluZyBBNCDihpIgRTQg4oaSIEM0IOKGkiBBMy4gUHJlc2VuY2Ugd2l0aGRyYXdpbmcgaW50"
    "byBzaGFkb3cuIiIiCiAgICBub3RlcyA9IFsKICAgICAgICAoNDQwLjAsICAwLjMpLCAgICMgQTQKICAgICAgICAoMzI5LjYzLCAw"
    "LjMpLCAgICMgRTQKICAgICAgICAoMjYxLjYzLCAwLjMpLCAgICMgQzQKICAgICAgICAoMjIwLjAsICAwLjgpLCAgICMgQTMg4oCU"
    "IGZpbmFsLCBsb25nIGZhZGUKICAgIF0KICAgIGF1ZGlvID0gW10KICAgIGZvciBpLCAoZnJlcSwgbGVuZ3RoKSBpbiBlbnVtZXJh"
    "dGUobm90ZXMpOgogICAgICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgICAgICBmb3IgaiBpbiByYW5n"
    "ZSh0b3RhbCk6CiAgICAgICAgICAgIHQgPSBqIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQp"
    "ICogMC41NQogICAgICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjE1CiAgICAgICAgICAgIGVudiA9IF9l"
    "bnZlbG9wZShqLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMywKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJlbGVhc2VfZnJh"
    "Yz0wLjYgaWYgaSA9PSBsZW4obm90ZXMpLTEgZWxzZSAwLjMpCiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICog"
    "ZW52ICogMC40KSkKICAgICAgICBmb3IgXyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4wNCkpOgogICAgICAgICAgICBh"
    "dWRpby5hcHBlbmQoMCkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgCBTT1VORCBGSUxFIFBBVEhTIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2V0X3NvdW5kX3BhdGgobmFtZTogc3RyKSAtPiBQYXRoOgogICAgcmV0dXJuIGNmZ19w"
    "YXRoKCJzb3VuZHMiKSAvIGYie1NPVU5EX1BSRUZJWH1fe25hbWV9LndhdiIKCmRlZiBib290c3RyYXBfc291bmRzKCkgLT4gTm9u"
    "ZToKICAgICIiIkdlbmVyYXRlIGFueSBtaXNzaW5nIHNvdW5kIFdBViBmaWxlcyBvbiBzdGFydHVwLiIiIgogICAgZ2VuZXJhdG9y"
    "cyA9IHsKICAgICAgICAiYWxlcnQiOiAgICBnZW5lcmF0ZV9tb3JnYW5uYV9hbGVydCwgICAjIGludGVybmFsIGZuIG5hbWUgdW5j"
    "aGFuZ2VkCiAgICAgICAgInN0YXJ0dXAiOiAgZ2VuZXJhdGVfbW9yZ2FubmFfc3RhcnR1cCwKICAgICAgICAiaWRsZSI6ICAgICBn"
    "ZW5lcmF0ZV9tb3JnYW5uYV9pZGxlLAogICAgICAgICJlcnJvciI6ICAgIGdlbmVyYXRlX21vcmdhbm5hX2Vycm9yLAogICAgICAg"
    "ICJzaHV0ZG93biI6IGdlbmVyYXRlX21vcmdhbm5hX3NodXRkb3duLAogICAgfQogICAgZm9yIG5hbWUsIGdlbl9mbiBpbiBnZW5l"
    "cmF0b3JzLml0ZW1zKCk6CiAgICAgICAgcGF0aCA9IGdldF9zb3VuZF9wYXRoKG5hbWUpCiAgICAgICAgaWYgbm90IHBhdGguZXhp"
    "c3RzKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGdlbl9mbihwYXRoKQogICAgICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBwcmludChmIltTT1VORF1bV0FSTl0gRmFpbGVkIHRvIGdlbmVyYXRlIHtuYW1l"
    "fToge2V9IikKCmRlZiBwbGF5X3NvdW5kKG5hbWU6IHN0cikgLT4gTm9uZToKICAgICIiIgogICAgUGxheSBhIG5hbWVkIHNvdW5k"
    "IG5vbi1ibG9ja2luZy4KICAgIFRyaWVzIHB5Z2FtZS5taXhlciBmaXJzdCAoY3Jvc3MtcGxhdGZvcm0sIFdBViArIE1QMykuCiAg"
    "ICBGYWxscyBiYWNrIHRvIHdpbnNvdW5kIG9uIFdpbmRvd3MuCiAgICBGYWxscyBiYWNrIHRvIFFBcHBsaWNhdGlvbi5iZWVwKCkg"
    "YXMgbGFzdCByZXNvcnQuCiAgICAiIiIKICAgIGlmIG5vdCBDRkdbInNldHRpbmdzIl0uZ2V0KCJzb3VuZF9lbmFibGVkIiwgVHJ1"
    "ZSk6CiAgICAgICAgcmV0dXJuCiAgICBwYXRoID0gZ2V0X3NvdW5kX3BhdGgobmFtZSkKICAgIGlmIG5vdCBwYXRoLmV4aXN0cygp"
    "OgogICAgICAgIHJldHVybgoKICAgIGlmIFBZR0FNRV9PSzoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNvdW5kID0gcHlnYW1l"
    "Lm1peGVyLlNvdW5kKHN0cihwYXRoKSkKICAgICAgICAgICAgc291bmQucGxheSgpCiAgICAgICAgICAgIHJldHVybgogICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICBpZiBXSU5TT1VORF9PSzoKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIHdpbnNvdW5kLlBsYXlTb3VuZChzdHIocGF0aCksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB3aW5zb3Vu"
    "ZC5TTkRfRklMRU5BTUUgfCB3aW5zb3VuZC5TTkRfQVNZTkMpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICB0cnk6CiAgICAgICAgUUFwcGxpY2F0aW9uLmJlZXAoKQogICAgZXhjZXB0IEV4"
    "Y2VwdGlvbjoKICAgICAgICBwYXNzCgojIOKUgOKUgCBERVNLVE9QIFNIT1JUQ1VUIENSRUFUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBjcmVhdGVfZGVza3Rv"
    "cF9zaG9ydGN1dCgpIC0+IGJvb2w6CiAgICAiIiIKICAgIENyZWF0ZSBhIGRlc2t0b3Agc2hvcnRjdXQgdG8gdGhlIGRlY2sgLnB5"
    "IGZpbGUgdXNpbmcgcHl0aG9udy5leGUuCiAgICBSZXR1cm5zIFRydWUgb24gc3VjY2Vzcy4gV2luZG93cyBvbmx5LgogICAgIiIi"
    "CiAgICBpZiBub3QgV0lOMzJfT0s6CiAgICAgICAgcmV0dXJuIEZhbHNlCiAgICB0cnk6CiAgICAgICAgZGVza3RvcCA9IFBhdGgu"
    "aG9tZSgpIC8gIkRlc2t0b3AiCiAgICAgICAgc2hvcnRjdXRfcGF0aCA9IGRlc2t0b3AgLyBmIntERUNLX05BTUV9LmxuayIKCiAg"
    "ICAgICAgIyBweXRob253ID0gc2FtZSBhcyBweXRob24gYnV0IG5vIGNvbnNvbGUgd2luZG93CiAgICAgICAgcHl0aG9udyA9IFBh"
    "dGgoc3lzLmV4ZWN1dGFibGUpCiAgICAgICAgaWYgcHl0aG9udy5uYW1lLmxvd2VyKCkgPT0gInB5dGhvbi5leGUiOgogICAgICAg"
    "ICAgICBweXRob253ID0gcHl0aG9udy5wYXJlbnQgLyAicHl0aG9udy5leGUiCiAgICAgICAgaWYgbm90IHB5dGhvbncuZXhpc3Rz"
    "KCk6CiAgICAgICAgICAgIHB5dGhvbncgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQoKICAgICAgICBkZWNrX3BhdGggPSBQYXRoKF9f"
    "ZmlsZV9fKS5yZXNvbHZlKCkKCiAgICAgICAgc2hlbGwgPSB3aW4zMmNvbS5jbGllbnQuRGlzcGF0Y2goIldTY3JpcHQuU2hlbGwi"
    "KQogICAgICAgIHNjID0gc2hlbGwuQ3JlYXRlU2hvcnRDdXQoc3RyKHNob3J0Y3V0X3BhdGgpKQogICAgICAgIHNjLlRhcmdldFBh"
    "dGggICAgID0gc3RyKHB5dGhvbncpCiAgICAgICAgc2MuQXJndW1lbnRzICAgICAgPSBmJyJ7ZGVja19wYXRofSInCiAgICAgICAg"
    "c2MuV29ya2luZ0RpcmVjdG9yeSA9IHN0cihkZWNrX3BhdGgucGFyZW50KQogICAgICAgIHNjLkRlc2NyaXB0aW9uICAgID0gZiJ7"
    "REVDS19OQU1FfSDigJQgRWNobyBEZWNrIgoKICAgICAgICAjIFVzZSBuZXV0cmFsIGZhY2UgYXMgaWNvbiBpZiBhdmFpbGFibGUK"
    "ICAgICAgICBpY29uX3BhdGggPSBjZmdfcGF0aCgiZmFjZXMiKSAvIGYie0ZBQ0VfUFJFRklYfV9OZXV0cmFsLnBuZyIKICAgICAg"
    "ICBpZiBpY29uX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgICMgV2luZG93cyBzaG9ydGN1dHMgY2FuJ3QgdXNlIFBORyBkaXJl"
    "Y3RseSDigJQgc2tpcCBpY29uIGlmIG5vIC5pY28KICAgICAgICAgICAgcGFzcwoKICAgICAgICBzYy5zYXZlKCkKICAgICAgICBy"
    "ZXR1cm4gVHJ1ZQogICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgIHByaW50KGYiW1NIT1JUQ1VUXVtXQVJOXSBDb3Vs"
    "ZCBub3QgY3JlYXRlIHNob3J0Y3V0OiB7ZX0iKQogICAgICAgIHJldHVybiBGYWxzZQoKIyDilIDilIAgSlNPTkwgVVRJTElUSUVT"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgcmVhZF9qc29ubChwYXRoOiBQYXRoKSAtPiBsaXN0W2RpY3RdOgogICAg"
    "IiIiUmVhZCBhIEpTT05MIGZpbGUuIFJldHVybnMgbGlzdCBvZiBkaWN0cy4gSGFuZGxlcyBKU09OIGFycmF5cyB0b28uIiIiCiAg"
    "ICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4gW10KICAgIHJhdyA9IHBhdGgucmVhZF90ZXh0KGVuY29kaW5n"
    "PSJ1dGYtOCIpLnN0cmlwKCkKICAgIGlmIG5vdCByYXc6CiAgICAgICAgcmV0dXJuIFtdCiAgICBpZiByYXcuc3RhcnRzd2l0aCgi"
    "WyIpOgogICAgICAgIHRyeToKICAgICAgICAgICAgZGF0YSA9IGpzb24ubG9hZHMocmF3KQogICAgICAgICAgICByZXR1cm4gW3gg"
    "Zm9yIHggaW4gZGF0YSBpZiBpc2luc3RhbmNlKHgsIGRpY3QpXQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAg"
    "IHBhc3MKICAgIGl0ZW1zID0gW10KICAgIGZvciBsaW5lIGluIHJhdy5zcGxpdGxpbmVzKCk6CiAgICAgICAgbGluZSA9IGxpbmUu"
    "c3RyaXAoKQogICAgICAgIGlmIG5vdCBsaW5lOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIHRyeToKICAgICAgICAgICAg"
    "b2JqID0ganNvbi5sb2FkcyhsaW5lKQogICAgICAgICAgICBpZiBpc2luc3RhbmNlKG9iaiwgZGljdCk6CiAgICAgICAgICAgICAg"
    "ICBpdGVtcy5hcHBlbmQob2JqKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICByZXR1"
    "cm4gaXRlbXMKCmRlZiBhcHBlbmRfanNvbmwocGF0aDogUGF0aCwgb2JqOiBkaWN0KSAtPiBOb25lOgogICAgIiIiQXBwZW5kIG9u"
    "ZSByZWNvcmQgdG8gYSBKU09OTCBmaWxlLiIiIgogICAgcGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1U"
    "cnVlKQogICAgd2l0aCBwYXRoLm9wZW4oImEiLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgIGYud3JpdGUoanNvbi5k"
    "dW1wcyhvYmosIGVuc3VyZV9hc2NpaT1GYWxzZSkgKyAiXG4iKQoKZGVmIHdyaXRlX2pzb25sKHBhdGg6IFBhdGgsIHJlY29yZHM6"
    "IGxpc3RbZGljdF0pIC0+IE5vbmU6CiAgICAiIiJPdmVyd3JpdGUgYSBKU09OTCBmaWxlIHdpdGggYSBsaXN0IG9mIHJlY29yZHMu"
    "IiIiCiAgICBwYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIHBhdGgub3Blbigi"
    "dyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgZm9yIHIgaW4gcmVjb3JkczoKICAgICAgICAgICAgZi53cml0ZShq"
    "c29uLmR1bXBzKHIsIGVuc3VyZV9hc2NpaT1GYWxzZSkgKyAiXG4iKQoKIyDilIDilIAgS0VZV09SRCAvIE1FTU9SWSBIRUxQRVJT"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gApfU1RPUFdPUkRTID0gewogICAgInRoZSIsImFuZCIsInRoYXQiLCJ3aXRoIiwiaGF2ZSIsInRoaXMiLCJmcm9tIiwieW91ciIs"
    "IndoYXQiLCJ3aGVuIiwKICAgICJ3aGVyZSIsIndoaWNoIiwid291bGQiLCJ0aGVyZSIsInRoZXkiLCJ0aGVtIiwidGhlbiIsImlu"
    "dG8iLCJqdXN0IiwKICAgICJhYm91dCIsImxpa2UiLCJiZWNhdXNlIiwid2hpbGUiLCJjb3VsZCIsInNob3VsZCIsInRoZWlyIiwi"
    "d2VyZSIsImJlZW4iLAogICAgImJlaW5nIiwiZG9lcyIsImRpZCIsImRvbnQiLCJkaWRudCIsImNhbnQiLCJ3b250Iiwib250byIs"
    "Im92ZXIiLCJ1bmRlciIsCiAgICAidGhhbiIsImFsc28iLCJzb21lIiwibW9yZSIsImxlc3MiLCJvbmx5IiwibmVlZCIsIndhbnQi"
    "LCJ3aWxsIiwic2hhbGwiLAogICAgImFnYWluIiwidmVyeSIsIm11Y2giLCJyZWFsbHkiLCJtYWtlIiwibWFkZSIsInVzZWQiLCJ1"
    "c2luZyIsInNhaWQiLAogICAgInRlbGwiLCJ0b2xkIiwiaWRlYSIsImNoYXQiLCJjb2RlIiwidGhpbmciLCJzdHVmZiIsInVzZXIi"
    "LCJhc3Npc3RhbnQiLAp9CgpkZWYgZXh0cmFjdF9rZXl3b3Jkcyh0ZXh0OiBzdHIsIGxpbWl0OiBpbnQgPSAxMikgLT4gbGlzdFtz"
    "dHJdOgogICAgdG9rZW5zID0gW3QubG93ZXIoKS5zdHJpcCgiIC4sIT87OidcIigpW117fSIpIGZvciB0IGluIHRleHQuc3BsaXQo"
    "KV0KICAgIHNlZW4sIHJlc3VsdCA9IHNldCgpLCBbXQogICAgZm9yIHQgaW4gdG9rZW5zOgogICAgICAgIGlmIGxlbih0KSA8IDMg"
    "b3IgdCBpbiBfU1RPUFdPUkRTIG9yIHQuaXNkaWdpdCgpOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlmIHQgbm90IGlu"
    "IHNlZW46CiAgICAgICAgICAgIHNlZW4uYWRkKHQpCiAgICAgICAgICAgIHJlc3VsdC5hcHBlbmQodCkKICAgICAgICBpZiBsZW4o"
    "cmVzdWx0KSA+PSBsaW1pdDoKICAgICAgICAgICAgYnJlYWsKICAgIHJldHVybiByZXN1bHQKCmRlZiBpbmZlcl9yZWNvcmRfdHlw"
    "ZSh1c2VyX3RleHQ6IHN0ciwgYXNzaXN0YW50X3RleHQ6IHN0ciA9ICIiKSAtPiBzdHI6CiAgICB0ID0gKHVzZXJfdGV4dCArICIg"
    "IiArIGFzc2lzdGFudF90ZXh0KS5sb3dlcigpCiAgICBpZiAiZHJlYW0iIGluIHQ6ICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IHJldHVybiAiZHJlYW0iCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgibHNsIiwicHl0aG9uIiwic2NyaXB0IiwiY29kZSIs"
    "ImVycm9yIiwiYnVnIikpOgogICAgICAgIGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJmaXhlZCIsInJlc29sdmVkIiwic29sdXRp"
    "b24iLCJ3b3JraW5nIikpOgogICAgICAgICAgICByZXR1cm4gInJlc29sdXRpb24iCiAgICAgICAgcmV0dXJuICJpc3N1ZSIKICAg"
    "IGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJyZW1pbmQiLCJ0aW1lciIsImFsYXJtIiwidGFzayIpKToKICAgICAgICByZXR1cm4g"
    "InRhc2siCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgiaWRlYSIsImNvbmNlcHQiLCJ3aGF0IGlmIiwiZ2FtZSIsInByb2pl"
    "Y3QiKSk6CiAgICAgICAgcmV0dXJuICJpZGVhIgogICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoInByZWZlciIsImFsd2F5cyIs"
    "Im5ldmVyIiwiaSBsaWtlIiwiaSB3YW50IikpOgogICAgICAgIHJldHVybiAicHJlZmVyZW5jZSIKICAgIHJldHVybiAiY29udmVy"
    "c2F0aW9uIgoKIyDilIDilIAgUEFTUyAxIENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE5leHQ6IFBhc3Mg"
    "MiDigJQgV2lkZ2V0IENsYXNzZXMKIyAoR2F1Z2VXaWRnZXQsIE1vb25XaWRnZXQsIFNwaGVyZVdpZGdldCwgRW1vdGlvbkJsb2Nr"
    "LAojICBNaXJyb3JXaWRnZXQsIFZhbXBpcmVTdGF0ZVN0cmlwLCBDb2xsYXBzaWJsZUJsb2NrKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMg"
    "TU9SR0FOTkEgREVDSyDigJQgUEFTUyAyOiBXSURHRVQgQ0xBU1NFUwojIEFwcGVuZGVkIHRvIG1vcmdhbm5hX3Bhc3MxLnB5IHRv"
    "IGZvcm0gdGhlIGZ1bGwgZGVjay4KIwojIFdpZGdldHMgZGVmaW5lZCBoZXJlOgojICAgR2F1Z2VXaWRnZXQgICAgICAgICAg4oCU"
    "IGhvcml6b250YWwgZmlsbCBiYXIgd2l0aCBsYWJlbCBhbmQgdmFsdWUKIyAgIERyaXZlV2lkZ2V0ICAgICAgICAgIOKAlCBkcml2"
    "ZSB1c2FnZSBiYXIgKHVzZWQvdG90YWwgR0IpCiMgICBTcGhlcmVXaWRnZXQgICAgICAgICDigJQgZmlsbGVkIGNpcmNsZSBmb3Ig"
    "QkxPT0QgYW5kIE1BTkEKIyAgIE1vb25XaWRnZXQgICAgICAgICAgIOKAlCBkcmF3biBtb29uIG9yYiB3aXRoIHBoYXNlIHNoYWRv"
    "dwojICAgRW1vdGlvbkJsb2NrICAgICAgICAg4oCUIGNvbGxhcHNpYmxlIGVtb3Rpb24gaGlzdG9yeSBjaGlwcwojICAgTWlycm9y"
    "V2lkZ2V0ICAgICAgICAg4oCUIGZhY2UgaW1hZ2UgZGlzcGxheSAodGhlIE1pcnJvcikKIyAgIFZhbXBpcmVTdGF0ZVN0cmlwICAg"
    "IOKAlCBmdWxsLXdpZHRoIHRpbWUvbW9vbi9zdGF0ZSBzdGF0dXMgYmFyCiMgICBDb2xsYXBzaWJsZUJsb2NrICAgICDigJQgd3Jh"
    "cHBlciB0aGF0IGFkZHMgY29sbGFwc2UgdG9nZ2xlIHRvIGFueSB3aWRnZXQKIyAgIEhhcmR3YXJlUGFuZWwgICAgICAgIOKAlCBn"
    "cm91cHMgYWxsIHN5c3RlbXMgZ2F1Z2VzCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgoKIyDilIDilIAgR0FVR0UgV0lER0VUIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBHYXVnZVdpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgSG9yaXpvbnRh"
    "bCBmaWxsLWJhciBnYXVnZSB3aXRoIGdvdGhpYyBzdHlsaW5nLgogICAgU2hvd3M6IGxhYmVsICh0b3AtbGVmdCksIHZhbHVlIHRl"
    "eHQgKHRvcC1yaWdodCksIGZpbGwgYmFyIChib3R0b20pLgogICAgQ29sb3Igc2hpZnRzOiBub3JtYWwg4oaSIENfQ1JJTVNPTiDi"
    "hpIgQ19CTE9PRCBhcyB2YWx1ZSBhcHByb2FjaGVzIG1heC4KICAgIFNob3dzICdOL0EnIHdoZW4gZGF0YSBpcyB1bmF2YWlsYWJs"
    "ZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXygKICAgICAgICBzZWxmLAogICAgICAgIGxhYmVsOiBzdHIsCiAgICAgICAgdW5p"
    "dDogc3RyID0gIiIsCiAgICAgICAgbWF4X3ZhbDogZmxvYXQgPSAxMDAuMCwKICAgICAgICBjb2xvcjogc3RyID0gQ19HT0xELAog"
    "ICAgICAgIHBhcmVudD1Ob25lCiAgICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYubGFi"
    "ZWwgICAgPSBsYWJlbAogICAgICAgIHNlbGYudW5pdCAgICAgPSB1bml0CiAgICAgICAgc2VsZi5tYXhfdmFsICA9IG1heF92YWwK"
    "ICAgICAgICBzZWxmLmNvbG9yICAgID0gY29sb3IKICAgICAgICBzZWxmLl92YWx1ZSAgID0gMC4wCiAgICAgICAgc2VsZi5fZGlz"
    "cGxheSA9ICJOL0EiCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gRmFsc2UKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDEw"
    "MCwgNjApCiAgICAgICAgc2VsZi5zZXRNYXhpbXVtSGVpZ2h0KDcyKQoKICAgIGRlZiBzZXRWYWx1ZShzZWxmLCB2YWx1ZTogZmxv"
    "YXQsIGRpc3BsYXk6IHN0ciA9ICIiLCBhdmFpbGFibGU6IGJvb2wgPSBUcnVlKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3ZhbHVl"
    "ICAgICA9IG1pbihmbG9hdCh2YWx1ZSksIHNlbGYubWF4X3ZhbCkKICAgICAgICBzZWxmLl9hdmFpbGFibGUgPSBhdmFpbGFibGUK"
    "ICAgICAgICBpZiBub3QgYXZhaWxhYmxlOgogICAgICAgICAgICBzZWxmLl9kaXNwbGF5ID0gIk4vQSIKICAgICAgICBlbGlmIGRp"
    "c3BsYXk6CiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkgPSBkaXNwbGF5CiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5f"
    "ZGlzcGxheSA9IGYie3ZhbHVlOi4wZn17c2VsZi51bml0fSIKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHNldFVuYXZh"
    "aWxhYmxlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gRmFsc2UKICAgICAgICBzZWxmLl9kaXNwbGF5"
    "ICAgPSAiTi9BIgogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToK"
    "ICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGludC5BbnRp"
    "YWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwgc2VsZi5oZWlnaHQoKQoKICAgICAgICAjIEJhY2tncm91bmQK"
    "ICAgICAgICBwLmZpbGxSZWN0KDAsIDAsIHcsIGgsIFFDb2xvcihDX0JHMykpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9S"
    "REVSKSkKICAgICAgICBwLmRyYXdSZWN0KDAsIDAsIHcgLSAxLCBoIC0gMSkKCiAgICAgICAgIyBMYWJlbAogICAgICAgIHAuc2V0"
    "UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA4LCBRRm9udC5XZWlnaHQu"
    "Qm9sZCkpCiAgICAgICAgcC5kcmF3VGV4dCg2LCAxNCwgc2VsZi5sYWJlbCkKCiAgICAgICAgIyBWYWx1ZQogICAgICAgIHAuc2V0"
    "UGVuKFFDb2xvcihzZWxmLmNvbG9yIGlmIHNlbGYuX2F2YWlsYWJsZSBlbHNlIENfVEVYVF9ESU0pKQogICAgICAgIHAuc2V0Rm9u"
    "dChRRm9udChERUNLX0ZPTlQsIDEwLCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAg"
    "ICAgICB2dyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHNlbGYuX2Rpc3BsYXkpCiAgICAgICAgcC5kcmF3VGV4dCh3IC0gdncgLSA2"
    "LCAxNCwgc2VsZi5fZGlzcGxheSkKCiAgICAgICAgIyBGaWxsIGJhcgogICAgICAgIGJhcl95ID0gaCAtIDE4CiAgICAgICAgYmFy"
    "X2ggPSAxMAogICAgICAgIGJhcl93ID0gdyAtIDEyCiAgICAgICAgcC5maWxsUmVjdCg2LCBiYXJfeSwgYmFyX3csIGJhcl9oLCBR"
    "Q29sb3IoQ19CRykpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9SREVSKSkKICAgICAgICBwLmRyYXdSZWN0KDYsIGJhcl95"
    "LCBiYXJfdyAtIDEsIGJhcl9oIC0gMSkKCiAgICAgICAgaWYgc2VsZi5fYXZhaWxhYmxlIGFuZCBzZWxmLm1heF92YWwgPiAwOgog"
    "ICAgICAgICAgICBmcmFjID0gc2VsZi5fdmFsdWUgLyBzZWxmLm1heF92YWwKICAgICAgICAgICAgZmlsbF93ID0gbWF4KDEsIGlu"
    "dCgoYmFyX3cgLSAyKSAqIGZyYWMpKQogICAgICAgICAgICAjIENvbG9yIHNoaWZ0IG5lYXIgbGltaXQKICAgICAgICAgICAgYmFy"
    "X2NvbG9yID0gKENfQkxPT0QgaWYgZnJhYyA+IDAuODUgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19DUklNU09OIGlm"
    "IGZyYWMgPiAwLjY1IGVsc2UKICAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuY29sb3IpCiAgICAgICAgICAgIGdyYWQgPSBR"
    "TGluZWFyR3JhZGllbnQoNywgYmFyX3kgKyAxLCA3ICsgZmlsbF93LCBiYXJfeSArIDEpCiAgICAgICAgICAgIGdyYWQuc2V0Q29s"
    "b3JBdCgwLCBRQ29sb3IoYmFyX2NvbG9yKS5kYXJrZXIoMTYwKSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDEsIFFDb2xv"
    "cihiYXJfY29sb3IpKQogICAgICAgICAgICBwLmZpbGxSZWN0KDcsIGJhcl95ICsgMSwgZmlsbF93LCBiYXJfaCAtIDIsIGdyYWQp"
    "CgogICAgICAgIHAuZW5kKCkKCgojIOKUgOKUgCBEUklWRSBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmNsYXNzIERyaXZlV2lkZ2V0KFFXaWRnZXQpOgogICAgIiIiCiAgICBEcml2ZSB1c2FnZSBkaXNwbGF5LiBTaG93cyBkcml2"
    "ZSBsZXR0ZXIsIHVzZWQvdG90YWwgR0IsIGZpbGwgYmFyLgogICAgQXV0by1kZXRlY3RzIGFsbCBtb3VudGVkIGRyaXZlcyB2aWEg"
    "cHN1dGlsLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5p"
    "dF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kcml2ZXM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuc2V0TWluaW11bUhl"
    "aWdodCgzMCkKICAgICAgICBzZWxmLl9yZWZyZXNoKCkKCiAgICBkZWYgX3JlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLl9kcml2ZXMgPSBbXQogICAgICAgIGlmIG5vdCBQU1VUSUxfT0s6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgZm9yIHBhcnQgaW4gcHN1dGlsLmRpc2tfcGFydGl0aW9ucyhhbGw9RmFsc2UpOgogICAgICAgICAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICAgICAgICAgIHVzYWdlID0gcHN1dGlsLmRpc2tfdXNhZ2UocGFydC5tb3VudHBvaW50KQogICAgICAg"
    "ICAgICAgICAgICAgIHNlbGYuX2RyaXZlcy5hcHBlbmQoewogICAgICAgICAgICAgICAgICAgICAgICAibGV0dGVyIjogcGFydC5k"
    "ZXZpY2UucnN0cmlwKCJcXCIpLnJzdHJpcCgiLyIpLAogICAgICAgICAgICAgICAgICAgICAgICAidXNlZCI6ICAgdXNhZ2UudXNl"
    "ZCAgLyAxMDI0KiozLAogICAgICAgICAgICAgICAgICAgICAgICAidG90YWwiOiAgdXNhZ2UudG90YWwgLyAxMDI0KiozLAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAicGN0IjogICAgdXNhZ2UucGVyY2VudCAvIDEwMC4wLAogICAgICAgICAgICAgICAgICAgIH0p"
    "CiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgICAgICMgUmVzaXplIHRvIGZpdCBhbGwgZHJpdmVzCiAgICAgICAg"
    "biA9IG1heCgxLCBsZW4oc2VsZi5fZHJpdmVzKSkKICAgICAgICBzZWxmLnNldE1pbmltdW1IZWlnaHQobiAqIDI4ICsgOCkKICAg"
    "ICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQ"
    "YWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAg"
    "ICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKICAgICAgICBwLmZpbGxSZWN0KDAsIDAsIHcsIGgsIFFDb2xv"
    "cihDX0JHMykpCgogICAgICAgIGlmIG5vdCBzZWxmLl9kcml2ZXM6CiAgICAgICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRf"
    "RElNKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOSkpCiAgICAgICAgICAgIHAuZHJhd1RleHQoNiwg"
    "MTgsICJOL0Eg4oCUIHBzdXRpbCB1bmF2YWlsYWJsZSIpCiAgICAgICAgICAgIHAuZW5kKCkKICAgICAgICAgICAgcmV0dXJuCgog"
    "ICAgICAgIHJvd19oID0gMjYKICAgICAgICB5ID0gNAogICAgICAgIGZvciBkcnYgaW4gc2VsZi5fZHJpdmVzOgogICAgICAgICAg"
    "ICBsZXR0ZXIgPSBkcnZbImxldHRlciJdCiAgICAgICAgICAgIHVzZWQgICA9IGRydlsidXNlZCJdCiAgICAgICAgICAgIHRvdGFs"
    "ICA9IGRydlsidG90YWwiXQogICAgICAgICAgICBwY3QgICAgPSBkcnZbInBjdCJdCgogICAgICAgICAgICAjIExhYmVsCiAgICAg"
    "ICAgICAgIGxhYmVsID0gZiJ7bGV0dGVyfSAge3VzZWQ6LjFmfS97dG90YWw6LjBmfUdCIgogICAgICAgICAgICBwLnNldFBlbihR"
    "Q29sb3IoQ19HT0xEKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOCwgUUZvbnQuV2VpZ2h0LkJvbGQp"
    "KQogICAgICAgICAgICBwLmRyYXdUZXh0KDYsIHkgKyAxMiwgbGFiZWwpCgogICAgICAgICAgICAjIEJhcgogICAgICAgICAgICBi"
    "YXJfeCA9IDYKICAgICAgICAgICAgYmFyX3kgPSB5ICsgMTUKICAgICAgICAgICAgYmFyX3cgPSB3IC0gMTIKICAgICAgICAgICAg"
    "YmFyX2ggPSA4CiAgICAgICAgICAgIHAuZmlsbFJlY3QoYmFyX3gsIGJhcl95LCBiYXJfdywgYmFyX2gsIFFDb2xvcihDX0JHKSkK"
    "ICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9SREVSKSkKICAgICAgICAgICAgcC5kcmF3UmVjdChiYXJfeCwgYmFyX3ks"
    "IGJhcl93IC0gMSwgYmFyX2ggLSAxKQoKICAgICAgICAgICAgZmlsbF93ID0gbWF4KDEsIGludCgoYmFyX3cgLSAyKSAqIHBjdCkp"
    "CiAgICAgICAgICAgIGJhcl9jb2xvciA9IChDX0JMT09EIGlmIHBjdCA+IDAuOSBlbHNlCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICBDX0NSSU1TT04gaWYgcGN0ID4gMC43NSBlbHNlCiAgICAgICAgICAgICAgICAgICAgICAgICBDX0dPTERfRElNKQogICAgICAg"
    "ICAgICBncmFkID0gUUxpbmVhckdyYWRpZW50KGJhcl94ICsgMSwgYmFyX3ksIGJhcl94ICsgZmlsbF93LCBiYXJfeSkKICAgICAg"
    "ICAgICAgZ3JhZC5zZXRDb2xvckF0KDAsIFFDb2xvcihiYXJfY29sb3IpLmRhcmtlcigxNTApKQogICAgICAgICAgICBncmFkLnNl"
    "dENvbG9yQXQoMSwgUUNvbG9yKGJhcl9jb2xvcikpCiAgICAgICAgICAgIHAuZmlsbFJlY3QoYmFyX3ggKyAxLCBiYXJfeSArIDEs"
    "IGZpbGxfdywgYmFyX2ggLSAyLCBncmFkKQoKICAgICAgICAgICAgeSArPSByb3dfaAoKICAgICAgICBwLmVuZCgpCgogICAgZGVm"
    "IHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJDYWxsIHBlcmlvZGljYWxseSB0byB1cGRhdGUgZHJpdmUgc3RhdHMu"
    "IiIiCiAgICAgICAgc2VsZi5fcmVmcmVzaCgpCgoKIyDilIDilIAgU1BIRVJFIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgU3BoZXJlV2lkZ2V0KFFXaWRnZXQpOgogICAgIiIiCiAgICBGaWxsZWQgY2lyY2xlIGdhdWdlIOKA"
    "lCB1c2VkIGZvciBCTE9PRCAodG9rZW4gcG9vbCkgYW5kIE1BTkEgKFZSQU0pLgogICAgRmlsbHMgZnJvbSBib3R0b20gdXAuIEds"
    "YXNzeSBzaGluZSBlZmZlY3QuIExhYmVsIGJlbG93LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKAogICAgICAgIHNlbGYsCiAg"
    "ICAgICAgbGFiZWw6IHN0ciwKICAgICAgICBjb2xvcl9mdWxsOiBzdHIsCiAgICAgICAgY29sb3JfZW1wdHk6IHN0ciwKICAgICAg"
    "ICBwYXJlbnQ9Tm9uZQogICAgKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLmxhYmVsICAg"
    "ICAgID0gbGFiZWwKICAgICAgICBzZWxmLmNvbG9yX2Z1bGwgID0gY29sb3JfZnVsbAogICAgICAgIHNlbGYuY29sb3JfZW1wdHkg"
    "PSBjb2xvcl9lbXB0eQogICAgICAgIHNlbGYuX2ZpbGwgICAgICAgPSAwLjAgICAjIDAuMCDihpIgMS4wCiAgICAgICAgc2VsZi5f"
    "YXZhaWxhYmxlICA9IFRydWUKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDgwLCAxMDApCgogICAgZGVmIHNldEZpbGwoc2Vs"
    "ZiwgZnJhY3Rpb246IGZsb2F0LCBhdmFpbGFibGU6IGJvb2wgPSBUcnVlKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2ZpbGwgICAg"
    "ICA9IG1heCgwLjAsIG1pbigxLjAsIGZyYWN0aW9uKSkKICAgICAgICBzZWxmLl9hdmFpbGFibGUgPSBhdmFpbGFibGUKICAgICAg"
    "ICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWlu"
    "dGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAg"
    "IHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgciAgPSBtaW4odywgaCAtIDIwKSAvLyAyIC0gNAog"
    "ICAgICAgIGN4ID0gdyAvLyAyCiAgICAgICAgY3kgPSAoaCAtIDIwKSAvLyAyICsgNAoKICAgICAgICAjIERyb3Agc2hhZG93CiAg"
    "ICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMCwgMCwgMCwgODApKQog"
    "ICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByICsgMywgY3kgLSByICsgMywgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIEJhc2Ug"
    "Y2lyY2xlIChlbXB0eSBjb2xvcikKICAgICAgICBwLnNldEJydXNoKFFDb2xvcihzZWxmLmNvbG9yX2VtcHR5KSkKICAgICAgICBw"
    "LnNldFBlbihRQ29sb3IoQ19CT1JERVIpKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICog"
    "MikKCiAgICAgICAgIyBGaWxsIGZyb20gYm90dG9tCiAgICAgICAgaWYgc2VsZi5fZmlsbCA+IDAuMDEgYW5kIHNlbGYuX2F2YWls"
    "YWJsZToKICAgICAgICAgICAgY2lyY2xlX3BhdGggPSBRUGFpbnRlclBhdGgoKQogICAgICAgICAgICBjaXJjbGVfcGF0aC5hZGRF"
    "bGxpcHNlKGZsb2F0KGN4IC0gciksIGZsb2F0KGN5IC0gciksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZmxv"
    "YXQociAqIDIpLCBmbG9hdChyICogMikpCgogICAgICAgICAgICBmaWxsX3RvcF95ID0gY3kgKyByIC0gKHNlbGYuX2ZpbGwgKiBy"
    "ICogMikKICAgICAgICAgICAgZnJvbSBQeVNpZGU2LlF0Q29yZSBpbXBvcnQgUVJlY3RGCiAgICAgICAgICAgIGZpbGxfcmVjdCA9"
    "IFFSZWN0RihjeCAtIHIsIGZpbGxfdG9wX3ksIHIgKiAyLCBjeSArIHIgLSBmaWxsX3RvcF95KQogICAgICAgICAgICBmaWxsX3Bh"
    "dGggPSBRUGFpbnRlclBhdGgoKQogICAgICAgICAgICBmaWxsX3BhdGguYWRkUmVjdChmaWxsX3JlY3QpCiAgICAgICAgICAgIGNs"
    "aXBwZWQgPSBjaXJjbGVfcGF0aC5pbnRlcnNlY3RlZChmaWxsX3BhdGgpCgogICAgICAgICAgICBwLnNldFBlbihRdC5QZW5TdHls"
    "ZS5Ob1BlbikKICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3Ioc2VsZi5jb2xvcl9mdWxsKSkKICAgICAgICAgICAgcC5kcmF3"
    "UGF0aChjbGlwcGVkKQoKICAgICAgICAjIEdsYXNzeSBzaGluZQogICAgICAgIHNoaW5lID0gUVJhZGlhbEdyYWRpZW50KAogICAg"
    "ICAgICAgICBmbG9hdChjeCAtIHIgKiAwLjMpLCBmbG9hdChjeSAtIHIgKiAwLjMpLCBmbG9hdChyICogMC42KQogICAgICAgICkK"
    "ICAgICAgICBzaGluZS5zZXRDb2xvckF0KDAsIFFDb2xvcigyNTUsIDI1NSwgMjU1LCA1NSkpCiAgICAgICAgc2hpbmUuc2V0Q29s"
    "b3JBdCgxLCBRQ29sb3IoMjU1LCAyNTUsIDI1NSwgMCkpCiAgICAgICAgcC5zZXRCcnVzaChzaGluZSkKICAgICAgICBwLnNldFBl"
    "bihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgog"
    "ICAgICAgICMgT3V0bGluZQogICAgICAgIHAuc2V0QnJ1c2goUXQuQnJ1c2hTdHlsZS5Ob0JydXNoKQogICAgICAgIHAuc2V0UGVu"
    "KFFQZW4oUUNvbG9yKHNlbGYuY29sb3JfZnVsbCksIDEpKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIg"
    "KiAyLCByICogMikKCiAgICAgICAgIyBOL0Egb3ZlcmxheQogICAgICAgIGlmIG5vdCBzZWxmLl9hdmFpbGFibGU6CiAgICAgICAg"
    "ICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KCJDb3VyaWVyIE5ldyIs"
    "IDgpKQogICAgICAgICAgICBmbSA9IHAuZm9udE1ldHJpY3MoKQogICAgICAgICAgICB0eHQgPSAiTi9BIgogICAgICAgICAgICBw"
    "LmRyYXdUZXh0KGN4IC0gZm0uaG9yaXpvbnRhbEFkdmFuY2UodHh0KSAvLyAyLCBjeSArIDQsIHR4dCkKCiAgICAgICAgIyBMYWJl"
    "bCBiZWxvdyBzcGhlcmUKICAgICAgICBsYWJlbF90ZXh0ID0gKHNlbGYubGFiZWwgaWYgc2VsZi5fYXZhaWxhYmxlIGVsc2UKICAg"
    "ICAgICAgICAgICAgICAgICAgIGYie3NlbGYubGFiZWx9IikKICAgICAgICBwY3RfdGV4dCA9IGYie2ludChzZWxmLl9maWxsICog"
    "MTAwKX0lIiBpZiBzZWxmLl9hdmFpbGFibGUgZWxzZSAiIgoKICAgICAgICBwLnNldFBlbihRQ29sb3Ioc2VsZi5jb2xvcl9mdWxs"
    "KSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA4LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgZm0gPSBw"
    "LmZvbnRNZXRyaWNzKCkKCiAgICAgICAgbHcgPSBmbS5ob3Jpem9udGFsQWR2YW5jZShsYWJlbF90ZXh0KQogICAgICAgIHAuZHJh"
    "d1RleHQoY3ggLSBsdyAvLyAyLCBoIC0gMTAsIGxhYmVsX3RleHQpCgogICAgICAgIGlmIHBjdF90ZXh0OgogICAgICAgICAgICBw"
    "LnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDcpKQogICAg"
    "ICAgICAgICBmbTIgPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICAgICAgcHcgPSBmbTIuaG9yaXpvbnRhbEFkdmFuY2UocGN0X3Rl"
    "eHQpCiAgICAgICAgICAgIHAuZHJhd1RleHQoY3ggLSBwdyAvLyAyLCBoIC0gMSwgcGN0X3RleHQpCgogICAgICAgIHAuZW5kKCkK"
    "CgojIOKUgOKUgCBNT09OIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9vbldp"
    "ZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgRHJhd24gbW9vbiBvcmIgd2l0aCBwaGFzZS1hY2N1cmF0ZSBzaGFkb3cuCgogICAg"
    "UEhBU0UgQ09OVkVOVElPTiAobm9ydGhlcm4gaGVtaXNwaGVyZSwgc3RhbmRhcmQpOgogICAgICAtIFdheGluZyAobmV34oaSZnVs"
    "bCk6IGlsbHVtaW5hdGVkIHJpZ2h0IHNpZGUsIHNoYWRvdyBvbiBsZWZ0CiAgICAgIC0gV2FuaW5nIChmdWxs4oaSbmV3KTogaWxs"
    "dW1pbmF0ZWQgbGVmdCBzaWRlLCBzaGFkb3cgb24gcmlnaHQKCiAgICBUaGUgc2hhZG93X3NpZGUgZmxhZyBjYW4gYmUgZmxpcHBl"
    "ZCBpZiB0ZXN0aW5nIHJldmVhbHMgaXQncyBiYWNrd2FyZHMKICAgIG9uIHRoaXMgbWFjaGluZS4gU2V0IE1PT05fU0hBRE9XX0ZM"
    "SVAgPSBUcnVlIGluIHRoYXQgY2FzZS4KICAgICIiIgoKICAgICMg4oaQIEZMSVAgVEhJUyB0byBUcnVlIGlmIG1vb24gYXBwZWFy"
    "cyBiYWNrd2FyZHMgZHVyaW5nIHRlc3RpbmcKICAgIE1PT05fU0hBRE9XX0ZMSVA6IGJvb2wgPSBGYWxzZQoKICAgIGRlZiBfX2lu"
    "aXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGhh"
    "c2UgICAgICAgPSAwLjAgICAgIyAwLjA9bmV3LCAwLjU9ZnVsbCwgMS4wPW5ldwogICAgICAgIHNlbGYuX25hbWUgICAgICAgID0g"
    "Ik5FVyBNT09OIgogICAgICAgIHNlbGYuX2lsbHVtaW5hdGlvbiA9IDAuMCAgICMgMC0xMDAKICAgICAgICBzZWxmLl9zdW5yaXNl"
    "ICAgICAgPSAiMDY6MDAiCiAgICAgICAgc2VsZi5fc3Vuc2V0ICAgICAgID0gIjE4OjMwIgogICAgICAgIHNlbGYuX3N1bl9kYXRl"
    "ICAgICA9IE5vbmUKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDgwLCAxMTApCiAgICAgICAgc2VsZi51cGRhdGVQaGFzZSgp"
    "ICAgICAgICAgICMgcG9wdWxhdGUgY29ycmVjdCBwaGFzZSBpbW1lZGlhdGVseQogICAgICAgIHNlbGYuX2ZldGNoX3N1bl9hc3lu"
    "YygpCgogICAgZGVmIF9mZXRjaF9zdW5fYXN5bmMoc2VsZikgLT4gTm9uZToKICAgICAgICBkZWYgX2ZldGNoKCk6CiAgICAgICAg"
    "ICAgIHNyLCBzcyA9IGdldF9zdW5fdGltZXMoKQogICAgICAgICAgICBzZWxmLl9zdW5yaXNlID0gc3IKICAgICAgICAgICAgc2Vs"
    "Zi5fc3Vuc2V0ICA9IHNzCiAgICAgICAgICAgIHNlbGYuX3N1bl9kYXRlID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLmRh"
    "dGUoKQogICAgICAgICAgICAjIFNjaGVkdWxlIHJlcGFpbnQgb24gbWFpbiB0aHJlYWQgdmlhIFFUaW1lciDigJQgbmV2ZXIgY2Fs"
    "bAogICAgICAgICAgICAjIHNlbGYudXBkYXRlKCkgZGlyZWN0bHkgZnJvbSBhIGJhY2tncm91bmQgdGhyZWFkCiAgICAgICAgICAg"
    "IFFUaW1lci5zaW5nbGVTaG90KDAsIHNlbGYudXBkYXRlKQogICAgICAgIHRocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9mZXRjaCwg"
    "ZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgdXBkYXRlUGhhc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9waGFz"
    "ZSwgc2VsZi5fbmFtZSwgc2VsZi5faWxsdW1pbmF0aW9uID0gZ2V0X21vb25fcGhhc2UoKQogICAgICAgIHRvZGF5ID0gZGF0ZXRp"
    "bWUubm93KCkuYXN0aW1lem9uZSgpLmRhdGUoKQogICAgICAgIGlmIHNlbGYuX3N1bl9kYXRlICE9IHRvZGF5OgogICAgICAgICAg"
    "ICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBl"
    "dmVudCkgLT4gTm9uZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIu"
    "UmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwgc2VsZi5oZWlnaHQoKQoKICAgICAg"
    "ICByICA9IG1pbih3LCBoIC0gMzYpIC8vIDIgLSA0CiAgICAgICAgY3ggPSB3IC8vIDIKICAgICAgICBjeSA9IChoIC0gMzYpIC8v"
    "IDIgKyA0CgogICAgICAgICMgQmFja2dyb3VuZCBjaXJjbGUgKHNwYWNlKQogICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDIwLCAx"
    "MiwgMjgpKQogICAgICAgIHAuc2V0UGVuKFFQZW4oUUNvbG9yKENfU0lMVkVSX0RJTSksIDEpKQogICAgICAgIHAuZHJhd0VsbGlw"
    "c2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgY3ljbGVfZGF5ID0gc2VsZi5fcGhhc2UgKiBfTFVOQVJf"
    "Q1lDTEUKICAgICAgICBpc193YXhpbmcgPSBjeWNsZV9kYXkgPCAoX0xVTkFSX0NZQ0xFIC8gMikKCiAgICAgICAgIyBGdWxsIG1v"
    "b24gYmFzZSAobW9vbiBzdXJmYWNlIGNvbG9yKQogICAgICAgIGlmIHNlbGYuX2lsbHVtaW5hdGlvbiA+IDE6CiAgICAgICAgICAg"
    "IHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAgICAgICAgICBwLnNldEJydXNoKFFDb2xvcigyMjAsIDIxMCwgMTg1KSkK"
    "ICAgICAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIFNoYWRvdyBj"
    "YWxjdWxhdGlvbgogICAgICAgICMgaWxsdW1pbmF0aW9uIGdvZXMgMOKGkjEwMCB3YXhpbmcsIDEwMOKGkjAgd2FuaW5nCiAgICAg"
    "ICAgIyBzaGFkb3dfb2Zmc2V0IGNvbnRyb2xzIGhvdyBtdWNoIG9mIHRoZSBjaXJjbGUgdGhlIHNoYWRvdyBjb3ZlcnMKICAgICAg"
    "ICBpZiBzZWxmLl9pbGx1bWluYXRpb24gPCA5OToKICAgICAgICAgICAgIyBmcmFjdGlvbiBvZiBkaWFtZXRlciB0aGUgc2hhZG93"
    "IGVsbGlwc2UgaXMgb2Zmc2V0CiAgICAgICAgICAgIGlsbHVtX2ZyYWMgID0gc2VsZi5faWxsdW1pbmF0aW9uIC8gMTAwLjAKICAg"
    "ICAgICAgICAgc2hhZG93X2ZyYWMgPSAxLjAgLSBpbGx1bV9mcmFjCgogICAgICAgICAgICAjIHdheGluZzogaWxsdW1pbmF0ZWQg"
    "cmlnaHQsIHNoYWRvdyBMRUZUCiAgICAgICAgICAgICMgd2FuaW5nOiBpbGx1bWluYXRlZCBsZWZ0LCBzaGFkb3cgUklHSFQKICAg"
    "ICAgICAgICAgIyBvZmZzZXQgbW92ZXMgdGhlIHNoYWRvdyBlbGxpcHNlIGhvcml6b250YWxseQogICAgICAgICAgICBvZmZzZXQg"
    "PSBpbnQoc2hhZG93X2ZyYWMgKiByICogMikKCiAgICAgICAgICAgIGlmIE1vb25XaWRnZXQuTU9PTl9TSEFET1dfRkxJUDoKICAg"
    "ICAgICAgICAgICAgIGlzX3dheGluZyA9IG5vdCBpc193YXhpbmcKCiAgICAgICAgICAgIGlmIGlzX3dheGluZzoKICAgICAgICAg"
    "ICAgICAgICMgU2hhZG93IG9uIGxlZnQgc2lkZQogICAgICAgICAgICAgICAgc2hhZG93X3ggPSBjeCAtIHIgLSBvZmZzZXQKICAg"
    "ICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICMgU2hhZG93IG9uIHJpZ2h0IHNpZGUKICAgICAgICAgICAgICAgIHNoYWRv"
    "d194ID0gY3ggLSByICsgb2Zmc2V0CgogICAgICAgICAgICBwLnNldEJydXNoKFFDb2xvcigxNSwgOCwgMjIpKQogICAgICAgICAg"
    "ICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKCiAgICAgICAgICAgICMgRHJhdyBzaGFkb3cgZWxsaXBzZSDigJQgY2xpcHBl"
    "ZCB0byBtb29uIGNpcmNsZQogICAgICAgICAgICBtb29uX3BhdGggPSBRUGFpbnRlclBhdGgoKQogICAgICAgICAgICBtb29uX3Bh"
    "dGguYWRkRWxsaXBzZShmbG9hdChjeCAtIHIpLCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZmxvYXQociAqIDIpLCBmbG9hdChyICogMikpCiAgICAgICAgICAgIHNoYWRvd19wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAg"
    "ICAgICAgICAgc2hhZG93X3BhdGguYWRkRWxsaXBzZShmbG9hdChzaGFkb3dfeCksIGZsb2F0KGN5IC0gciksCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQogICAgICAgICAgICBjbGlwcGVkX3No"
    "YWRvdyA9IG1vb25fcGF0aC5pbnRlcnNlY3RlZChzaGFkb3dfcGF0aCkKICAgICAgICAgICAgcC5kcmF3UGF0aChjbGlwcGVkX3No"
    "YWRvdykKCiAgICAgICAgIyBTdWJ0bGUgc3VyZmFjZSBkZXRhaWwgKGNyYXRlcnMgaW1wbGllZCBieSBzbGlnaHQgdGV4dHVyZSBn"
    "cmFkaWVudCkKICAgICAgICBzaGluZSA9IFFSYWRpYWxHcmFkaWVudChmbG9hdChjeCAtIHIgKiAwLjIpLCBmbG9hdChjeSAtIHIg"
    "KiAwLjIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAwLjgpKQogICAgICAgIHNoaW5lLnNldENv"
    "bG9yQXQoMCwgUUNvbG9yKDI1NSwgMjU1LCAyNDAsIDMwKSkKICAgICAgICBzaGluZS5zZXRDb2xvckF0KDEsIFFDb2xvcigyMDAs"
    "IDE4MCwgMTQwLCA1KSkKICAgICAgICBwLnNldEJydXNoKHNoaW5lKQogICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVu"
    "KQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBPdXRsaW5lCiAg"
    "ICAgICAgcC5zZXRCcnVzaChRdC5CcnVzaFN0eWxlLk5vQnJ1c2gpCiAgICAgICAgcC5zZXRQZW4oUVBlbihRQ29sb3IoQ19TSUxW"
    "RVIpLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgUGhh"
    "c2UgbmFtZSBiZWxvdyBtb29uCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfU0lMVkVSKSkKICAgICAgICBwLnNldEZvbnQoUUZv"
    "bnQoREVDS19GT05ULCA3LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICBu"
    "dyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHNlbGYuX25hbWUpCiAgICAgICAgcC5kcmF3VGV4dChjeCAtIG53IC8vIDIsIGN5ICsg"
    "ciArIDE0LCBzZWxmLl9uYW1lKQoKICAgICAgICAjIElsbHVtaW5hdGlvbiBwZXJjZW50YWdlCiAgICAgICAgaWxsdW1fc3RyID0g"
    "ZiJ7c2VsZi5faWxsdW1pbmF0aW9uOi4wZn0lIgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICBw"
    "LnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAgICAgICBmbTIgPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICBpdyA9IGZt"
    "Mi5ob3Jpem9udGFsQWR2YW5jZShpbGx1bV9zdHIpCiAgICAgICAgcC5kcmF3VGV4dChjeCAtIGl3IC8vIDIsIGN5ICsgciArIDI0"
    "LCBpbGx1bV9zdHIpCgogICAgICAgICMgU3VuIHRpbWVzIGF0IHZlcnkgYm90dG9tCiAgICAgICAgc3VuX3N0ciA9IGYi4piAIHtz"
    "ZWxmLl9zdW5yaXNlfSAg4pi9IHtzZWxmLl9zdW5zZXR9IgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0dPTERfRElNKSkKICAg"
    "ICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAgICAgICBmbTMgPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICBz"
    "dyA9IGZtMy5ob3Jpem9udGFsQWR2YW5jZShzdW5fc3RyKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBzdyAvLyAyLCBoIC0gMiwg"
    "c3VuX3N0cikKCiAgICAgICAgcC5lbmQoKQoKCiMg4pSA4pSAIEVNT1RJT04gQkxPQ0sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACmNsYXNzIEVtb3Rpb25CbG9jayhRV2lkZ2V0KToKICAgICIiIgogICAgQ29sbGFwc2libGUgZW1vdGlvbiBoaXN0"
    "b3J5IHBhbmVsLgogICAgU2hvd3MgY29sb3ItY29kZWQgY2hpcHM6IOKcpiBFTU9USU9OX05BTUUgIEhIOk1NCiAgICBTaXRzIG5l"
    "eHQgdG8gdGhlIE1pcnJvciAoZmFjZSB3aWRnZXQpIGluIHRoZSBib3R0b20gYmxvY2sgcm93LgogICAgQ29sbGFwc2VzIHRvIGp1"
    "c3QgdGhlIGhlYWRlciBzdHJpcC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAg"
    "c3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5faGlzdG9yeTogbGlzdFt0dXBsZVtzdHIsIHN0cl1dID0gW10g"
    "ICMgKGVtb3Rpb24sIHRpbWVzdGFtcCkKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IFRydWUKICAgICAgICBzZWxmLl9tYXhfZW50"
    "cmllcyA9IDMwCgogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFy"
    "Z2lucygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDApCgogICAgICAgICMgSGVhZGVyIHJvdwogICAgICAg"
    "IGhlYWRlciA9IFFXaWRnZXQoKQogICAgICAgIGhlYWRlci5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBoZWFkZXIuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXItYm90dG9tOiAxcHggc29saWQge0NfQ1JJ"
    "TVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgaGwgPSBRSEJveExheW91dChoZWFkZXIpCiAgICAgICAgaGwuc2V0Q29udGVu"
    "dHNNYXJnaW5zKDYsIDAsIDQsIDApCiAgICAgICAgaGwuc2V0U3BhY2luZyg0KQoKICAgICAgICBsYmwgPSBRTGFiZWwoIuKdpyBF"
    "TU9USU9OQUwgUkVDT1JEIikKICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07"
    "IGZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05U"
    "fSwgc2VyaWY7IGxldHRlci1zcGFjaW5nOiAxcHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3RvZ2ds"
    "ZV9idG4gPSBRVG9vbEJ1dHRvbigpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRGaXhlZFNpemUoMTYsIDE2KQogICAgICAg"
    "IHNlbGYuX3RvZ2dsZV9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB0cmFuc3BhcmVudDsgY29s"
    "b3I6IHtDX0dPTER9OyBib3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3RvZ2ds"
    "ZV9idG4uc2V0VGV4dCgi4pa8IikKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUp"
    "CgogICAgICAgIGhsLmFkZFdpZGdldChsYmwpCiAgICAgICAgaGwuYWRkU3RyZXRjaCgpCiAgICAgICAgaGwuYWRkV2lkZ2V0KHNl"
    "bGYuX3RvZ2dsZV9idG4pCgogICAgICAgICMgU2Nyb2xsIGFyZWEgZm9yIGVtb3Rpb24gY2hpcHMKICAgICAgICBzZWxmLl9zY3Jv"
    "bGwgPSBRU2Nyb2xsQXJlYSgpCiAgICAgICAgc2VsZi5fc2Nyb2xsLnNldFdpZGdldFJlc2l6YWJsZShUcnVlKQogICAgICAgIHNl"
    "bGYuX3Njcm9sbC5zZXRIb3Jpem9udGFsU2Nyb2xsQmFyUG9saWN5KAogICAgICAgICAgICBRdC5TY3JvbGxCYXJQb2xpY3kuU2Ny"
    "b2xsQmFyQWx3YXlzT2ZmKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91"
    "bmQ6IHtDX0JHMn07IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQoKICAgICAgICBzZWxmLl9jaGlwX2NvbnRhaW5lciA9IFFXaWRn"
    "ZXQoKQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fY2hpcF9jb250YWluZXIpCiAgICAgICAg"
    "c2VsZi5fY2hpcF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQu"
    "c2V0U3BhY2luZygyKQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LmFkZFN0cmV0Y2goKQogICAgICAgIHNlbGYuX3Njcm9sbC5z"
    "ZXRXaWRnZXQoc2VsZi5fY2hpcF9jb250YWluZXIpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoaGVhZGVyKQogICAgICAgIGxh"
    "eW91dC5hZGRXaWRnZXQoc2VsZi5fc2Nyb2xsKQoKICAgICAgICBzZWxmLnNldE1pbmltdW1XaWR0aCgxMzApCgogICAgZGVmIF90"
    "b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAgIHNl"
    "bGYuX3Njcm9sbC5zZXRWaXNpYmxlKHNlbGYuX2V4cGFuZGVkKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4pa8"
    "IiBpZiBzZWxmLl9leHBhbmRlZCBlbHNlICLilrIiKQogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0cnkoKQoKICAgIGRlZiBhZGRF"
    "bW90aW9uKHNlbGYsIGVtb3Rpb246IHN0ciwgdGltZXN0YW1wOiBzdHIgPSAiIikgLT4gTm9uZToKICAgICAgICBpZiBub3QgdGlt"
    "ZXN0YW1wOgogICAgICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU0iKQogICAgICAgIHNl"
    "bGYuX2hpc3RvcnkuaW5zZXJ0KDAsIChlbW90aW9uLCB0aW1lc3RhbXApKQogICAgICAgIHNlbGYuX2hpc3RvcnkgPSBzZWxmLl9o"
    "aXN0b3J5WzpzZWxmLl9tYXhfZW50cmllc10KICAgICAgICBzZWxmLl9yZWJ1aWxkX2NoaXBzKCkKCiAgICBkZWYgX3JlYnVpbGRf"
    "Y2hpcHMoc2VsZikgLT4gTm9uZToKICAgICAgICAjIENsZWFyIGV4aXN0aW5nIGNoaXBzIChrZWVwIHRoZSBzdHJldGNoIGF0IGVu"
    "ZCkKICAgICAgICB3aGlsZSBzZWxmLl9jaGlwX2xheW91dC5jb3VudCgpID4gMToKICAgICAgICAgICAgaXRlbSA9IHNlbGYuX2No"
    "aXBfbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICBpZiBpdGVtLndpZGdldCgpOgogICAgICAgICAgICAgICAgaXRlbS53aWRn"
    "ZXQoKS5kZWxldGVMYXRlcigpCgogICAgICAgIGZvciBlbW90aW9uLCB0cyBpbiBzZWxmLl9oaXN0b3J5OgogICAgICAgICAgICBj"
    "b2xvciA9IEVNT1RJT05fQ09MT1JTLmdldChlbW90aW9uLCBDX1RFWFRfRElNKQogICAgICAgICAgICBjaGlwID0gUUxhYmVsKGYi"
    "4pymIHtlbW90aW9uLnVwcGVyKCl9ICB7dHN9IikKICAgICAgICAgICAgY2hpcC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAg"
    "ICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7ICIKICAg"
    "ICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAg"
    "ICAgICAgICAgZiJwYWRkaW5nOiAxcHggNHB4OyBib3JkZXItcmFkaXVzOiAycHg7IgogICAgICAgICAgICApCiAgICAgICAgICAg"
    "IHNlbGYuX2NoaXBfbGF5b3V0Lmluc2VydFdpZGdldCgKICAgICAgICAgICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LmNvdW50KCkg"
    "LSAxLCBjaGlwCiAgICAgICAgICAgICkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9oaXN0b3J5"
    "LmNsZWFyKCkKICAgICAgICBzZWxmLl9yZWJ1aWxkX2NoaXBzKCkKCgojIOKUgOKUgCBNSVJST1IgV0lER0VUIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBNaXJyb3JXaWRnZXQoUUxhYmVsKToKICAgICIiIgogICAgRmFjZSBpbWFnZSBk"
    "aXNwbGF5IOKAlCAnVGhlIE1pcnJvcicuCiAgICBEeW5hbWljYWxseSBsb2FkcyBhbGwge0ZBQ0VfUFJFRklYfV8qLnBuZyBmaWxl"
    "cyBmcm9tIGNvbmZpZyBwYXRocy5mYWNlcy4KICAgIEF1dG8tbWFwcyBmaWxlbmFtZSB0byBlbW90aW9uIGtleToKICAgICAgICB7"
    "RkFDRV9QUkVGSVh9X0FsZXJ0LnBuZyAgICAg4oaSICJhbGVydCIKICAgICAgICB7RkFDRV9QUkVGSVh9X1NhZF9DcnlpbmcucG5n"
    "IOKGkiAic2FkIgogICAgICAgIHtGQUNFX1BSRUZJWH1fQ2hlYXRfTW9kZS5wbmcg4oaSICJjaGVhdG1vZGUiCiAgICBGYWxscyBi"
    "YWNrIHRvIG5ldXRyYWwsIHRoZW4gdG8gZ290aGljIHBsYWNlaG9sZGVyIGlmIG5vIGltYWdlcyBmb3VuZC4KICAgIE1pc3Npbmcg"
    "ZmFjZXMgZGVmYXVsdCB0byBuZXV0cmFsIOKAlCBubyBjcmFzaCwgbm8gaGFyZGNvZGVkIGxpc3QgcmVxdWlyZWQuCiAgICAiIiIK"
    "CiAgICAjIFNwZWNpYWwgc3RlbSDihpIgZW1vdGlvbiBrZXkgbWFwcGluZ3MgKGxvd2VyY2FzZSBzdGVtIGFmdGVyIE1vcmdhbm5h"
    "XykKICAgIF9TVEVNX1RPX0VNT1RJT046IGRpY3Rbc3RyLCBzdHJdID0gewogICAgICAgICJzYWRfY3J5aW5nIjogICJzYWQiLAog"
    "ICAgICAgICJjaGVhdF9tb2RlIjogICJjaGVhdG1vZGUiLAogICAgfQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9u"
    "ZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZmFjZXNfZGlyICAgPSBjZmdfcGF0aCgi"
    "ZmFjZXMiKQogICAgICAgIHNlbGYuX2NhY2hlOiBkaWN0W3N0ciwgUVBpeG1hcF0gPSB7fQogICAgICAgIHNlbGYuX2N1cnJlbnQg"
    "ICAgID0gIm5ldXRyYWwiCiAgICAgICAgc2VsZi5fd2FybmVkOiBzZXRbc3RyXSA9IHNldCgpCgogICAgICAgIHNlbGYuc2V0TWlu"
    "aW11bVNpemUoMTYwLCAxNjApCiAgICAgICAgc2VsZi5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikK"
    "ICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHgg"
    "c29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCgogICAg"
    "ICAgIFFUaW1lci5zaW5nbGVTaG90KDMwMCwgc2VsZi5fcHJlbG9hZCkKCiAgICBkZWYgX3ByZWxvYWQoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICAiIiIKICAgICAgICBTY2FuIEZhY2VzLyBkaXJlY3RvcnkgZm9yIGFsbCB7RkFDRV9QUkVGSVh9XyoucG5nIGZpbGVz"
    "LgogICAgICAgIEJ1aWxkIGVtb3Rpb27ihpJwaXhtYXAgY2FjaGUgZHluYW1pY2FsbHkuCiAgICAgICAgTm8gaGFyZGNvZGVkIGxp"
    "c3Qg4oCUIHdoYXRldmVyIGlzIGluIHRoZSBmb2xkZXIgaXMgYXZhaWxhYmxlLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBz"
    "ZWxmLl9mYWNlc19kaXIuZXhpc3RzKCk6CiAgICAgICAgICAgIHNlbGYuX2RyYXdfcGxhY2Vob2xkZXIoKQogICAgICAgICAgICBy"
    "ZXR1cm4KCiAgICAgICAgZm9yIGltZ19wYXRoIGluIHNlbGYuX2ZhY2VzX2Rpci5nbG9iKGYie0ZBQ0VfUFJFRklYfV8qLnBuZyIp"
    "OgogICAgICAgICAgICAjIHN0ZW0gPSBldmVyeXRoaW5nIGFmdGVyICJNb3JnYW5uYV8iIHdpdGhvdXQgLnBuZwogICAgICAgICAg"
    "ICByYXdfc3RlbSA9IGltZ19wYXRoLnN0ZW1bbGVuKGYie0ZBQ0VfUFJFRklYfV8iKTpdICAgICMgZS5nLiAiU2FkX0NyeWluZyIK"
    "ICAgICAgICAgICAgc3RlbV9sb3dlciA9IHJhd19zdGVtLmxvd2VyKCkgICAgICAgICAgICAgICAgICAgICAgICAgICMgInNhZF9j"
    "cnlpbmciCgogICAgICAgICAgICAjIE1hcCBzcGVjaWFsIHN0ZW1zIHRvIGVtb3Rpb24ga2V5cwogICAgICAgICAgICBlbW90aW9u"
    "ID0gc2VsZi5fU1RFTV9UT19FTU9USU9OLmdldChzdGVtX2xvd2VyLCBzdGVtX2xvd2VyKQoKICAgICAgICAgICAgcHggPSBRUGl4"
    "bWFwKHN0cihpbWdfcGF0aCkpCiAgICAgICAgICAgIGlmIG5vdCBweC5pc051bGwoKToKICAgICAgICAgICAgICAgIHNlbGYuX2Nh"
    "Y2hlW2Vtb3Rpb25dID0gcHgKCiAgICAgICAgaWYgc2VsZi5fY2FjaGU6CiAgICAgICAgICAgIHNlbGYuX3JlbmRlcigibmV1dHJh"
    "bCIpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fZHJhd19wbGFjZWhvbGRlcigpCgogICAgZGVmIF9yZW5kZXIoc2Vs"
    "ZiwgZmFjZTogc3RyKSAtPiBOb25lOgogICAgICAgIGZhY2UgPSBmYWNlLmxvd2VyKCkuc3RyaXAoKQogICAgICAgIGlmIGZhY2Ug"
    "bm90IGluIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl93YXJuZWQgYW5kIGZhY2UgIT0gIm5l"
    "dXRyYWwiOgogICAgICAgICAgICAgICAgcHJpbnQoZiJbTUlSUk9SXVtXQVJOXSBGYWNlIG5vdCBpbiBjYWNoZToge2ZhY2V9IOKA"
    "lCB1c2luZyBuZXV0cmFsIikKICAgICAgICAgICAgICAgIHNlbGYuX3dhcm5lZC5hZGQoZmFjZSkKICAgICAgICAgICAgZmFjZSA9"
    "ICJuZXV0cmFsIgogICAgICAgIGlmIGZhY2Ugbm90IGluIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBzZWxmLl9kcmF3X3BsYWNl"
    "aG9sZGVyKCkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fY3VycmVudCA9IGZhY2UKICAgICAgICBweCA9IHNlbGYu"
    "X2NhY2hlW2ZhY2VdCiAgICAgICAgc2NhbGVkID0gcHguc2NhbGVkKAogICAgICAgICAgICBzZWxmLndpZHRoKCkgLSA0LAogICAg"
    "ICAgICAgICBzZWxmLmhlaWdodCgpIC0gNCwKICAgICAgICAgICAgUXQuQXNwZWN0UmF0aW9Nb2RlLktlZXBBc3BlY3RSYXRpbywK"
    "ICAgICAgICAgICAgUXQuVHJhbnNmb3JtYXRpb25Nb2RlLlNtb290aFRyYW5zZm9ybWF0aW9uLAogICAgICAgICkKICAgICAgICBz"
    "ZWxmLnNldFBpeG1hcChzY2FsZWQpCiAgICAgICAgc2VsZi5zZXRUZXh0KCIiKQoKICAgIGRlZiBfZHJhd19wbGFjZWhvbGRlcihz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuY2xlYXIoKQogICAgICAgIHNlbGYuc2V0VGV4dCgi4pymXG7inadcbuKcpiIpCiAg"
    "ICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNv"
    "bGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImNvbG9yOiB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogMjRw"
    "eDsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCgogICAgZGVmIHNldF9mYWNlKHNlbGYsIGZhY2U6IHN0cikgLT4gTm9u"
    "ZToKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgwLCBsYW1iZGE6IHNlbGYuX3JlbmRlcihmYWNlKSkKCiAgICBkZWYgcmVzaXpl"
    "RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgc3VwZXIoKS5yZXNpemVFdmVudChldmVudCkKICAgICAgICBpZiBz"
    "ZWxmLl9jYWNoZToKICAgICAgICAgICAgc2VsZi5fcmVuZGVyKHNlbGYuX2N1cnJlbnQpCgogICAgQHByb3BlcnR5CiAgICBkZWYg"
    "Y3VycmVudF9mYWNlKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4gc2VsZi5fY3VycmVudAoKCiMg4pSA4pSAIFZBTVBJUkUg"
    "U1RBVEUgU1RSSVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEN5Y2xlV2lkZ2V0KE1vb25XaWRnZXQpOgogICAgIiIiR2VuZXJpYyBj"
    "eWNsZSB2aXN1YWxpemF0aW9uIHdpZGdldCAoY3VycmVudGx5IGx1bmFyLXBoYXNlIGRyaXZlbikuIiIiCgoKY2xhc3MgVmFtcGly"
    "ZVN0YXRlU3RyaXAoUVdpZGdldCk6CiAgICAiIiIKICAgIEZ1bGwtd2lkdGggc3RhdHVzIGJhciBzaG93aW5nOgogICAgICBbIOKc"
    "piBWQU1QSVJFX1NUQVRFICDigKIgIEhIOk1NICDigKIgIOKYgCBTVU5SSVNFICDimL0gU1VOU0VUICDigKIgIE1PT04gUEhBU0Ug"
    "IElMTFVNJSBdCiAgICBBbHdheXMgdmlzaWJsZSwgbmV2ZXIgY29sbGFwc2VzLgogICAgVXBkYXRlcyBldmVyeSBtaW51dGUgdmlh"
    "IGV4dGVybmFsIFFUaW1lciBjYWxsIHRvIHJlZnJlc2goKS4KICAgIENvbG9yLWNvZGVkIGJ5IGN1cnJlbnQgdmFtcGlyZSBzdGF0"
    "ZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhw"
    "YXJlbnQpCiAgICAgICAgc2VsZi5fbGFiZWxfcHJlZml4ID0gIlNUQVRFIgogICAgICAgIHNlbGYuX3N0YXRlICAgICA9IGdldF92"
    "YW1waXJlX3N0YXRlKCkKICAgICAgICBzZWxmLl90aW1lX3N0ciAgPSAiIgogICAgICAgIHNlbGYuX3N1bnJpc2UgICA9ICIwNjow"
    "MCIKICAgICAgICBzZWxmLl9zdW5zZXQgICAgPSAiMTg6MzAiCiAgICAgICAgc2VsZi5fc3VuX2RhdGUgID0gTm9uZQogICAgICAg"
    "IHNlbGYuX21vb25fbmFtZSA9ICJORVcgTU9PTiIKICAgICAgICBzZWxmLl9pbGx1bSAgICAgPSAwLjAKICAgICAgICBzZWxmLnNl"
    "dEZpeGVkSGVpZ2h0KDI4KQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlci10"
    "b3A6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IikKICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQogICAgICAgIHNl"
    "bGYucmVmcmVzaCgpCgogICAgZGVmIHNldF9sYWJlbChzZWxmLCBsYWJlbDogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xh"
    "YmVsX3ByZWZpeCA9IChsYWJlbCBvciAiU1RBVEUiKS5zdHJpcCgpLnVwcGVyKCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAg"
    "ZGVmIF9mZXRjaF9zdW5fYXN5bmMoc2VsZikgLT4gTm9uZToKICAgICAgICBkZWYgX2YoKToKICAgICAgICAgICAgc3IsIHNzID0g"
    "Z2V0X3N1bl90aW1lcygpCiAgICAgICAgICAgIHNlbGYuX3N1bnJpc2UgPSBzcgogICAgICAgICAgICBzZWxmLl9zdW5zZXQgID0g"
    "c3MKICAgICAgICAgICAgc2VsZi5fc3VuX2RhdGUgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkuZGF0ZSgpCiAgICAgICAg"
    "ICAgICMgU2NoZWR1bGUgcmVwYWludCBvbiBtYWluIHRocmVhZCDigJQgbmV2ZXIgY2FsbCB1cGRhdGUoKSBmcm9tCiAgICAgICAg"
    "ICAgICMgYSBiYWNrZ3JvdW5kIHRocmVhZCwgaXQgY2F1c2VzIFFUaHJlYWQgY3Jhc2ggb24gc3RhcnR1cAogICAgICAgICAgICBR"
    "VGltZXIuc2luZ2xlU2hvdCgwLCBzZWxmLnVwZGF0ZSkKICAgICAgICB0aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fZiwgZGFlbW9u"
    "PVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YXRlICAgICA9IGdl"
    "dF92YW1waXJlX3N0YXRlKCkKICAgICAgICBzZWxmLl90aW1lX3N0ciAgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkuc3Ry"
    "ZnRpbWUoIiVYIikKICAgICAgICB0b2RheSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAgICAgICBpZiBz"
    "ZWxmLl9zdW5fZGF0ZSAhPSB0b2RheToKICAgICAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAgICBfLCBzZWxm"
    "Ll9tb29uX25hbWUsIHNlbGYuX2lsbHVtID0gZ2V0X21vb25fcGhhc2UoKQogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYg"
    "cGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJl"
    "bmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwgc2Vs"
    "Zi5oZWlnaHQoKQoKICAgICAgICBwLmZpbGxSZWN0KDAsIDAsIHcsIGgsIFFDb2xvcihDX0JHMikpCgogICAgICAgIHN0YXRlX2Nv"
    "bG9yID0gZ2V0X3ZhbXBpcmVfc3RhdGVfY29sb3Ioc2VsZi5fc3RhdGUpCiAgICAgICAgdGV4dCA9ICgKICAgICAgICAgICAgZiLi"
    "nKYgIHtzZWxmLl9sYWJlbF9wcmVmaXh9OiB7c2VsZi5fc3RhdGV9ICDigKIgIHtzZWxmLl90aW1lX3N0cn0gIOKAoiAgIgogICAg"
    "ICAgICAgICBmIuKYgCB7c2VsZi5fc3VucmlzZX0gICAg4pi9IHtzZWxmLl9zdW5zZXR9ICDigKIgICIKICAgICAgICAgICAgZiJ7"
    "c2VsZi5fbW9vbl9uYW1lfSAge3NlbGYuX2lsbHVtOi4wZn0lIgogICAgICAgICkKCiAgICAgICAgcC5zZXRGb250KFFGb250KERF"
    "Q0tfRk9OVCwgOSwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihzdGF0ZV9jb2xvcikpCiAgICAg"
    "ICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICB0dyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHRleHQpCiAgICAgICAgcC5k"
    "cmF3VGV4dCgodyAtIHR3KSAvLyAyLCBoIC0gNywgdGV4dCkKCiAgICAgICAgcC5lbmQoKQoKCmNsYXNzIE1pbmlDYWxlbmRhcldp"
    "ZGdldChRV2lkZ2V0KToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRf"
    "XyhwYXJlbnQpCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJn"
    "aW5zKDAsIDAsIDAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgaGVhZGVyID0gUUhCb3hMYXlvdXQo"
    "KQogICAgICAgIGhlYWRlci5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLnByZXZfYnRuID0gUVB1"
    "c2hCdXR0b24oIjw8IikKICAgICAgICBzZWxmLm5leHRfYnRuID0gUVB1c2hCdXR0b24oIj4+IikKICAgICAgICBzZWxmLm1vbnRo"
    "X2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLm1vbnRoX2xibC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGln"
    "bkNlbnRlcikKICAgICAgICBmb3IgYnRuIGluIChzZWxmLnByZXZfYnRuLCBzZWxmLm5leHRfYnRuKToKICAgICAgICAgICAgYnRu"
    "LnNldEZpeGVkV2lkdGgoMzQpCiAgICAgICAgICAgIGJ0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3Jv"
    "dW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAg"
    "ICAgICAgICAgZiJmb250LXNpemU6IDEwcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAycHg7IgogICAgICAgICAgICAp"
    "CiAgICAgICAgc2VsZi5tb250aF9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGJvcmRl"
    "cjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyBmb250LXdlaWdodDogYm9sZDsiCiAgICAgICAgKQogICAgICAgIGhlYWRlci5hZGRX"
    "aWRnZXQoc2VsZi5wcmV2X2J0bikKICAgICAgICBoZWFkZXIuYWRkV2lkZ2V0KHNlbGYubW9udGhfbGJsLCAxKQogICAgICAgIGhl"
    "YWRlci5hZGRXaWRnZXQoc2VsZi5uZXh0X2J0bikKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGhlYWRlcikKCiAgICAgICAgc2Vs"
    "Zi5jYWxlbmRhciA9IFFDYWxlbmRhcldpZGdldCgpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRHcmlkVmlzaWJsZShUcnVlKQog"
    "ICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0VmVydGljYWxIZWFkZXJGb3JtYXQoUUNhbGVuZGFyV2lkZ2V0LlZlcnRpY2FsSGVhZGVy"
    "Rm9ybWF0Lk5vVmVydGljYWxIZWFkZXIpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXROYXZpZ2F0aW9uQmFyVmlzaWJsZShGYWxz"
    "ZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFXaWRn"
    "ZXR7e2FsdGVybmF0ZS1iYWNrZ3JvdW5kLWNvbG9yOntDX0JHMn07fX0gIgogICAgICAgICAgICBmIlFUb29sQnV0dG9ue3tjb2xv"
    "cjp7Q19HT0xEfTt9fSAiCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFBYnN0cmFjdEl0ZW1WaWV3OmVuYWJsZWR7e2Jh"
    "Y2tncm91bmQ6e0NfQkcyfTsgY29sb3I6I2ZmZmZmZjsgIgogICAgICAgICAgICBmInNlbGVjdGlvbi1iYWNrZ3JvdW5kLWNvbG9y"
    "OntDX0NSSU1TT05fRElNfTsgc2VsZWN0aW9uLWNvbG9yOntDX1RFWFR9OyBncmlkbGluZS1jb2xvcjp7Q19CT1JERVJ9O319ICIK"
    "ICAgICAgICAgICAgZiJRQ2FsZW5kYXJXaWRnZXQgUUFic3RyYWN0SXRlbVZpZXc6ZGlzYWJsZWR7e2NvbG9yOiM4Yjk1YTE7fX0i"
    "CiAgICAgICAgKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5jYWxlbmRhcikKCiAgICAgICAgc2VsZi5wcmV2X2J0bi5j"
    "bGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLmNhbGVuZGFyLnNob3dQcmV2aW91c01vbnRoKCkpCiAgICAgICAgc2VsZi5uZXh0"
    "X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLmNhbGVuZGFyLnNob3dOZXh0TW9udGgoKSkKICAgICAgICBzZWxmLmNh"
    "bGVuZGFyLmN1cnJlbnRQYWdlQ2hhbmdlZC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9sYWJlbCkKICAgICAgICBzZWxmLl91cGRhdGVf"
    "bGFiZWwoKQogICAgICAgIHNlbGYuX2FwcGx5X2Zvcm1hdHMoKQoKICAgIGRlZiBfdXBkYXRlX2xhYmVsKHNlbGYsICphcmdzKToK"
    "ICAgICAgICB5ZWFyID0gc2VsZi5jYWxlbmRhci55ZWFyU2hvd24oKQogICAgICAgIG1vbnRoID0gc2VsZi5jYWxlbmRhci5tb250"
    "aFNob3duKCkKICAgICAgICBzZWxmLm1vbnRoX2xibC5zZXRUZXh0KGYie2RhdGUoeWVhciwgbW9udGgsIDEpLnN0cmZ0aW1lKCcl"
    "QiAlWScpfSIpCiAgICAgICAgc2VsZi5fYXBwbHlfZm9ybWF0cygpCgogICAgZGVmIF9hcHBseV9mb3JtYXRzKHNlbGYpOgogICAg"
    "ICAgIGJhc2UgPSBRVGV4dENoYXJGb3JtYXQoKQogICAgICAgIGJhc2Uuc2V0Rm9yZWdyb3VuZChRQ29sb3IoIiNlN2VkZjMiKSkK"
    "ICAgICAgICBzYXR1cmRheSA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgc2F0dXJkYXkuc2V0Rm9yZWdyb3VuZChRQ29sb3Io"
    "Q19HT0xEX0RJTSkpCiAgICAgICAgc3VuZGF5ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICBzdW5kYXkuc2V0Rm9yZWdyb3Vu"
    "ZChRQ29sb3IoQ19CTE9PRCkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsu"
    "TW9uZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlR1ZXNk"
    "YXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuV2VkbmVzZGF5"
    "LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlRodXJzZGF5LCBi"
    "YXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLkZyaWRheSwgYmFzZSkK"
    "ICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5TYXR1cmRheSwgc2F0dXJkYXkp"
    "CiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuU3VuZGF5LCBzdW5kYXkpCgog"
    "ICAgICAgIHllYXIgPSBzZWxmLmNhbGVuZGFyLnllYXJTaG93bigpCiAgICAgICAgbW9udGggPSBzZWxmLmNhbGVuZGFyLm1vbnRo"
    "U2hvd24oKQogICAgICAgIGZpcnN0X2RheSA9IFFEYXRlKHllYXIsIG1vbnRoLCAxKQogICAgICAgIGZvciBkYXkgaW4gcmFuZ2Uo"
    "MSwgZmlyc3RfZGF5LmRheXNJbk1vbnRoKCkgKyAxKToKICAgICAgICAgICAgZCA9IFFEYXRlKHllYXIsIG1vbnRoLCBkYXkpCiAg"
    "ICAgICAgICAgIGZtdCA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgICAgIHdlZWtkYXkgPSBkLmRheU9mV2VlaygpCiAgICAg"
    "ICAgICAgIGlmIHdlZWtkYXkgPT0gUXQuRGF5T2ZXZWVrLlNhdHVyZGF5LnZhbHVlOgogICAgICAgICAgICAgICAgZm10LnNldEZv"
    "cmVncm91bmQoUUNvbG9yKENfR09MRF9ESU0pKQogICAgICAgICAgICBlbGlmIHdlZWtkYXkgPT0gUXQuRGF5T2ZXZWVrLlN1bmRh"
    "eS52YWx1ZToKICAgICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0JMT09EKSkKICAgICAgICAgICAgZWxz"
    "ZToKICAgICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcigiI2U3ZWRmMyIpKQogICAgICAgICAgICBzZWxmLmNh"
    "bGVuZGFyLnNldERhdGVUZXh0Rm9ybWF0KGQsIGZtdCkKCiAgICAgICAgdG9kYXlfZm10ID0gUVRleHRDaGFyRm9ybWF0KCkKICAg"
    "ICAgICB0b2RheV9mbXQuc2V0Rm9yZWdyb3VuZChRQ29sb3IoIiM2OGQzOWEiKSkKICAgICAgICB0b2RheV9mbXQuc2V0QmFja2dy"
    "b3VuZChRQ29sb3IoIiMxNjM4MjUiKSkKICAgICAgICB0b2RheV9mbXQuc2V0Rm9udFdlaWdodChRRm9udC5XZWlnaHQuQm9sZCkK"
    "ICAgICAgICBzZWxmLmNhbGVuZGFyLnNldERhdGVUZXh0Rm9ybWF0KFFEYXRlLmN1cnJlbnREYXRlKCksIHRvZGF5X2ZtdCkKCgoj"
    "IOKUgOKUgCBDT0xMQVBTSUJMRSBCTE9DSyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgQ29sbGFwc2libGVCbG9jayhRV2lk"
    "Z2V0KToKICAgICIiIgogICAgV3JhcHBlciB0aGF0IGFkZHMgYSBjb2xsYXBzZS9leHBhbmQgdG9nZ2xlIHRvIGFueSB3aWRnZXQu"
    "CiAgICBDb2xsYXBzZXMgaG9yaXpvbnRhbGx5IChyaWdodHdhcmQpIOKAlCBoaWRlcyBjb250ZW50LCBrZWVwcyBoZWFkZXIgc3Ry"
    "aXAuCiAgICBIZWFkZXIgc2hvd3MgbGFiZWwuIFRvZ2dsZSBidXR0b24gb24gcmlnaHQgZWRnZSBvZiBoZWFkZXIuCgogICAgVXNh"
    "Z2U6CiAgICAgICAgYmxvY2sgPSBDb2xsYXBzaWJsZUJsb2NrKCLinacgQkxPT0QiLCBTcGhlcmVXaWRnZXQoLi4uKSkKICAgICAg"
    "ICBsYXlvdXQuYWRkV2lkZ2V0KGJsb2NrKQogICAgIiIiCgogICAgdG9nZ2xlZCA9IFNpZ25hbChib29sKQoKICAgIGRlZiBfX2lu"
    "aXRfXyhzZWxmLCBsYWJlbDogc3RyLCBjb250ZW50OiBRV2lkZ2V0LAogICAgICAgICAgICAgICAgIGV4cGFuZGVkOiBib29sID0g"
    "VHJ1ZSwgbWluX3dpZHRoOiBpbnQgPSA5MCwKICAgICAgICAgICAgICAgICByZXNlcnZlX3dpZHRoOiBib29sID0gRmFsc2UsCiAg"
    "ICAgICAgICAgICAgICAgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYu"
    "X2V4cGFuZGVkICAgICAgID0gZXhwYW5kZWQKICAgICAgICBzZWxmLl9taW5fd2lkdGggICAgICA9IG1pbl93aWR0aAogICAgICAg"
    "IHNlbGYuX3Jlc2VydmVfd2lkdGggID0gcmVzZXJ2ZV93aWR0aAogICAgICAgIHNlbGYuX2NvbnRlbnQgICAgICAgID0gY29udGVu"
    "dAoKICAgICAgICBtYWluID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBtYWluLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAw"
    "LCAwKQogICAgICAgIG1haW4uc2V0U3BhY2luZygwKQoKICAgICAgICAjIEhlYWRlcgogICAgICAgIHNlbGYuX2hlYWRlciA9IFFX"
    "aWRnZXQoKQogICAgICAgIHNlbGYuX2hlYWRlci5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBzZWxmLl9oZWFkZXIuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXItYm90dG9tOiAxcHggc29saWQge0NfQ1JJ"
    "TVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXRvcDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAg"
    "KQogICAgICAgIGhsID0gUUhCb3hMYXlvdXQoc2VsZi5faGVhZGVyKQogICAgICAgIGhsLnNldENvbnRlbnRzTWFyZ2lucyg2LCAw"
    "LCA0LCAwKQogICAgICAgIGhsLnNldFNwYWNpbmcoNCkKCiAgICAgICAgc2VsZi5fbGJsID0gUUxhYmVsKGxhYmVsKQogICAgICAg"
    "IHNlbGYuX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGZv"
    "bnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgbGV0dGVyLXNw"
    "YWNpbmc6IDFweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCgogICAgICAgIHNlbGYuX2J0biA9IFFUb29sQnV0dG9uKCkKICAg"
    "ICAgICBzZWxmLl9idG4uc2V0Rml4ZWRTaXplKDE2LCAxNikKICAgICAgICBzZWxmLl9idG4uc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJiYWNrZ3JvdW5kOiB0cmFuc3BhcmVudDsgY29sb3I6IHtDX0dPTERfRElNfTsgYm9yZGVyOiBub25lOyBmb250LXNp"
    "emU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl9idG4uc2V0VGV4dCgiPCIpCiAgICAgICAgc2VsZi5fYnRuLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCgogICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl9sYmwpCiAgICAgICAgaGwuYWRkU3Ry"
    "ZXRjaCgpCiAgICAgICAgaGwuYWRkV2lkZ2V0KHNlbGYuX2J0bikKCiAgICAgICAgbWFpbi5hZGRXaWRnZXQoc2VsZi5faGVhZGVy"
    "KQogICAgICAgIG1haW4uYWRkV2lkZ2V0KHNlbGYuX2NvbnRlbnQpCgogICAgICAgIHNlbGYuX2FwcGx5X3N0YXRlKCkKCiAgICBk"
    "ZWYgaXNfZXhwYW5kZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fZXhwYW5kZWQKCiAgICBkZWYgX3RvZ2ds"
    "ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAgICAgICAgc2VsZi5f"
    "YXBwbHlfc3RhdGUoKQogICAgICAgIHNlbGYudG9nZ2xlZC5lbWl0KHNlbGYuX2V4cGFuZGVkKQoKICAgIGRlZiBfYXBwbHlfc3Rh"
    "dGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9jb250ZW50LnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCiAgICAgICAg"
    "c2VsZi5fYnRuLnNldFRleHQoIjwiIGlmIHNlbGYuX2V4cGFuZGVkIGVsc2UgIj4iKQoKICAgICAgICAjIFJlc2VydmUgZml4ZWQg"
    "c2xvdCB3aWR0aCB3aGVuIHJlcXVlc3RlZCAodXNlZCBieSBtaWRkbGUgbG93ZXIgYmxvY2spCiAgICAgICAgaWYgc2VsZi5fcmVz"
    "ZXJ2ZV93aWR0aDoKICAgICAgICAgICAgc2VsZi5zZXRNaW5pbXVtV2lkdGgoc2VsZi5fbWluX3dpZHRoKQogICAgICAgICAgICBz"
    "ZWxmLnNldE1heGltdW1XaWR0aCgxNjc3NzIxNSkKICAgICAgICBlbGlmIHNlbGYuX2V4cGFuZGVkOgogICAgICAgICAgICBzZWxm"
    "LnNldE1pbmltdW1XaWR0aChzZWxmLl9taW5fd2lkdGgpCiAgICAgICAgICAgIHNlbGYuc2V0TWF4aW11bVdpZHRoKDE2Nzc3MjE1"
    "KSAgIyB1bmNvbnN0cmFpbmVkCiAgICAgICAgZWxzZToKICAgICAgICAgICAgIyBDb2xsYXBzZWQ6IGp1c3QgdGhlIGhlYWRlciBz"
    "dHJpcCAobGFiZWwgKyBidXR0b24pCiAgICAgICAgICAgIGNvbGxhcHNlZF93ID0gc2VsZi5faGVhZGVyLnNpemVIaW50KCkud2lk"
    "dGgoKQogICAgICAgICAgICBzZWxmLnNldEZpeGVkV2lkdGgobWF4KDYwLCBjb2xsYXBzZWRfdykpCgogICAgICAgIHNlbGYudXBk"
    "YXRlR2VvbWV0cnkoKQogICAgICAgIHBhcmVudCA9IHNlbGYucGFyZW50V2lkZ2V0KCkKICAgICAgICBpZiBwYXJlbnQgYW5kIHBh"
    "cmVudC5sYXlvdXQoKToKICAgICAgICAgICAgcGFyZW50LmxheW91dCgpLmFjdGl2YXRlKCkKCgojIOKUgOKUgCBIQVJEV0FSRSBQ"
    "QU5FTCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSGFyZHdhcmVQYW5lbChRV2lkZ2V0KToKICAgICIiIgog"
    "ICAgVGhlIHN5c3RlbXMgcmlnaHQgcGFuZWwgY29udGVudHMuCiAgICBHcm91cHM6IHN0YXR1cyBpbmZvLCBkcml2ZSBiYXJzLCBD"
    "UFUvUkFNIGdhdWdlcywgR1BVL1ZSQU0gZ2F1Z2VzLCBHUFUgdGVtcC4KICAgIFJlcG9ydHMgaGFyZHdhcmUgYXZhaWxhYmlsaXR5"
    "IGluIERpYWdub3N0aWNzIG9uIHN0YXJ0dXAuCiAgICBTaG93cyBOL0EgZ3JhY2VmdWxseSB3aGVuIGRhdGEgdW5hdmFpbGFibGUu"
    "CiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFy"
    "ZW50KQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLl9kZXRlY3RfaGFyZHdhcmUoKQoKICAgIGRlZiBfc2V0"
    "dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRD"
    "b250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICBkZWYgc2VjdGlv"
    "bl9sYWJlbCh0ZXh0OiBzdHIpIC0+IFFMYWJlbDoKICAgICAgICAgICAgbGJsID0gUUxhYmVsKHRleHQpCiAgICAgICAgICAgIGxi"
    "bC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogOXB4OyBsZXR0ZXIt"
    "c3BhY2luZzogMnB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtd2Vp"
    "Z2h0OiBib2xkOyIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4gbGJsCgogICAgICAgICMg4pSA4pSAIFN0YXR1cyBi"
    "bG9jayDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKdpyBTVEFUVVMiKSkKICAgICAgICBzdGF0dXNfZnJhbWUgPSBRRnJh"
    "bWUoKQogICAgICAgIHN0YXR1c19mcmFtZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX1BBTkVM"
    "fTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCiAgICAgICAgc3Rh"
    "dHVzX2ZyYW1lLnNldEZpeGVkSGVpZ2h0KDg4KQogICAgICAgIHNmID0gUVZCb3hMYXlvdXQoc3RhdHVzX2ZyYW1lKQogICAgICAg"
    "IHNmLnNldENvbnRlbnRzTWFyZ2lucyg4LCA0LCA4LCA0KQogICAgICAgIHNmLnNldFNwYWNpbmcoMikKCiAgICAgICAgc2VsZi5s"
    "Ymxfc3RhdHVzICA9IFFMYWJlbCgi4pymIFNUQVRVUzogT0ZGTElORSIpCiAgICAgICAgc2VsZi5sYmxfbW9kZWwgICA9IFFMYWJl"
    "bCgi4pymIFZFU1NFTDogTE9BRElORy4uLiIpCiAgICAgICAgc2VsZi5sYmxfc2Vzc2lvbiA9IFFMYWJlbCgi4pymIFNFU1NJT046"
    "IDAwOjAwOjAwIikKICAgICAgICBzZWxmLmxibF90b2tlbnMgID0gUUxhYmVsKCLinKYgVE9LRU5TOiAwIikKCiAgICAgICAgZm9y"
    "IGxibCBpbiAoc2VsZi5sYmxfc3RhdHVzLCBzZWxmLmxibF9tb2RlbCwKICAgICAgICAgICAgICAgICAgICBzZWxmLmxibF9zZXNz"
    "aW9uLCBzZWxmLmxibF90b2tlbnMpOgogICAgICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiY29s"
    "b3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19G"
    "T05UfSwgc2VyaWY7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2YuYWRkV2lkZ2V0KGxibCkKCiAg"
    "ICAgICAgbGF5b3V0LmFkZFdpZGdldChzdGF0dXNfZnJhbWUpCgogICAgICAgICMg4pSA4pSAIERyaXZlIGJhcnMg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0"
    "LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgU1RPUkFHRSIpKQogICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0ID0gRHJpdmVX"
    "aWRnZXQoKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5kcml2ZV93aWRnZXQpCgogICAgICAgICMg4pSA4pSAIENQVSAv"
    "IFJBTSBnYXVnZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5"
    "b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgVklUQUwgRVNTRU5DRSIpKQogICAgICAgIHJhbV9jcHUgPSBRR3JpZExh"
    "eW91dCgpCiAgICAgICAgcmFtX2NwdS5zZXRTcGFjaW5nKDMpCgogICAgICAgIHNlbGYuZ2F1Z2VfY3B1ICA9IEdhdWdlV2lkZ2V0"
    "KCJDUFUiLCAgIiUiLCAgIDEwMC4wLCBDX1NJTFZFUikKICAgICAgICBzZWxmLmdhdWdlX3JhbSAgPSBHYXVnZVdpZGdldCgiUkFN"
    "IiwgICJHQiIsICAgNjQuMCwgQ19HT0xEX0RJTSkKICAgICAgICByYW1fY3B1LmFkZFdpZGdldChzZWxmLmdhdWdlX2NwdSwgMCwg"
    "MCkKICAgICAgICByYW1fY3B1LmFkZFdpZGdldChzZWxmLmdhdWdlX3JhbSwgMCwgMSkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0"
    "KHJhbV9jcHUpCgogICAgICAgICMg4pSA4pSAIEdQVSAvIFZSQU0gZ2F1Z2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIEFSQ0FORSBQT1dF"
    "UiIpKQogICAgICAgIGdwdV92cmFtID0gUUdyaWRMYXlvdXQoKQogICAgICAgIGdwdV92cmFtLnNldFNwYWNpbmcoMykKCiAgICAg"
    "ICAgc2VsZi5nYXVnZV9ncHUgID0gR2F1Z2VXaWRnZXQoIkdQVSIsICAiJSIsICAgMTAwLjAsIENfUFVSUExFKQogICAgICAgIHNl"
    "bGYuZ2F1Z2VfdnJhbSA9IEdhdWdlV2lkZ2V0KCJWUkFNIiwgIkdCIiwgICAgOC4wLCBDX0NSSU1TT04pCiAgICAgICAgZ3B1X3Zy"
    "YW0uYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfZ3B1LCAgMCwgMCkKICAgICAgICBncHVfdnJhbS5hZGRXaWRnZXQoc2VsZi5nYXVnZV92"
    "cmFtLCAwLCAxKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoZ3B1X3ZyYW0pCgogICAgICAgICMg4pSA4pSAIEdQVSBUZW1wIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEhFQVQiKSkKICAgICAgICBzZWxmLmdh"
    "dWdlX3RlbXAgPSBHYXVnZVdpZGdldCgiR1BVIFRFTVAiLCAiwrBDIiwgOTUuMCwgQ19CTE9PRCkKICAgICAgICBzZWxmLmdhdWdl"
    "X3RlbXAuc2V0TWF4aW11bUhlaWdodCg2NSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfdGVtcCkKCiAgICAg"
    "ICAgIyDilIDilIAgR1BVIG1hc3RlciBiYXIgKGZ1bGwgd2lkdGgpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5h"
    "ZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEVOR0lORSIpKQogICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3Rl"
    "ciA9IEdhdWdlV2lkZ2V0KCJSVFgiLCAiJSIsIDEwMC4wLCBDX0NSSU1TT04pCiAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVy"
    "LnNldE1heGltdW1IZWlnaHQoNTUpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmdhdWdlX2dwdV9tYXN0ZXIpCgogICAg"
    "ICAgIGxheW91dC5hZGRTdHJldGNoKCkKCiAgICBkZWYgX2RldGVjdF9oYXJkd2FyZShzZWxmKSAtPiBOb25lOgogICAgICAgICIi"
    "IgogICAgICAgIENoZWNrIHdoYXQgaGFyZHdhcmUgbW9uaXRvcmluZyBpcyBhdmFpbGFibGUuCiAgICAgICAgTWFyayB1bmF2YWls"
    "YWJsZSBnYXVnZXMgYXBwcm9wcmlhdGVseS4KICAgICAgICBEaWFnbm9zdGljIG1lc3NhZ2VzIGNvbGxlY3RlZCBmb3IgdGhlIERp"
    "YWdub3N0aWNzIHRhYi4KICAgICAgICAiIiIKICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzOiBsaXN0W3N0cl0gPSBbXQoKICAg"
    "ICAgICBpZiBub3QgUFNVVElMX09LOgogICAgICAgICAgICBzZWxmLmdhdWdlX2NwdS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAg"
    "ICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQo"
    "CiAgICAgICAgICAgICAgICAiW0hBUkRXQVJFXSBwc3V0aWwgbm90IGF2YWlsYWJsZSDigJQgQ1BVL1JBTSBnYXVnZXMgZGlzYWJs"
    "ZWQuICIKICAgICAgICAgICAgICAgICJwaXAgaW5zdGFsbCBwc3V0aWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAg"
    "IGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKCJbSEFSRFdBUkVdIHBzdXRpbCBPSyDigJQgQ1BV"
    "L1JBTSBtb25pdG9yaW5nIGFjdGl2ZS4iKQoKICAgICAgICBpZiBub3QgTlZNTF9PSzoKICAgICAgICAgICAgc2VsZi5nYXVnZV9n"
    "cHUuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAg"
    "ICBzZWxmLmdhdWdlX3RlbXAuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIuc2V0VW5h"
    "dmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICJbSEFSRFdB"
    "UkVdIHB5bnZtbCBub3QgYXZhaWxhYmxlIG9yIG5vIE5WSURJQSBHUFUgZGV0ZWN0ZWQg4oCUICIKICAgICAgICAgICAgICAgICJH"
    "UFUgZ2F1Z2VzIGRpc2FibGVkLiBwaXAgaW5zdGFsbCBweW52bWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVs"
    "c2U6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdldE5hbWUoZ3B1X2hh"
    "bmRsZSkKICAgICAgICAgICAgICAgIGlmIGlzaW5zdGFuY2UobmFtZSwgYnl0ZXMpOgogICAgICAgICAgICAgICAgICAgIG5hbWUg"
    "PSBuYW1lLmRlY29kZSgpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAg"
    "ICAgICBmIltIQVJEV0FSRV0gcHludm1sIE9LIOKAlCBHUFUgZGV0ZWN0ZWQ6IHtuYW1lfSIKICAgICAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgICAgICMgVXBkYXRlIG1heCBWUkFNIGZyb20gYWN0dWFsIGhhcmR3YXJlCiAgICAgICAgICAgICAgICBtZW0gPSBw"
    "eW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIHRvdGFsX2diID0gbWVtLnRv"
    "dGFsIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV92cmFtLm1heF92YWwgPSB0b3RhbF9nYgogICAgICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZChmIltIQVJE"
    "V0FSRV0gcHludm1sIGVycm9yOiB7ZX0iKQoKICAgIGRlZiB1cGRhdGVfc3RhdHMoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIK"
    "ICAgICAgICBDYWxsZWQgZXZlcnkgc2Vjb25kIGZyb20gdGhlIHN0YXRzIFFUaW1lci4KICAgICAgICBSZWFkcyBoYXJkd2FyZSBh"
    "bmQgdXBkYXRlcyBhbGwgZ2F1Z2VzLgogICAgICAgICIiIgogICAgICAgIGlmIFBTVVRJTF9PSzoKICAgICAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICAgICAgY3B1ID0gcHN1dGlsLmNwdV9wZXJjZW50KCkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfY3B1LnNl"
    "dFZhbHVlKGNwdSwgZiJ7Y3B1Oi4wZn0lIiwgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICAgICAgICAgbWVtID0gcHN1dGlsLnZp"
    "cnR1YWxfbWVtb3J5KCkKICAgICAgICAgICAgICAgIHJ1ICA9IG1lbS51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHJ0"
    "ICA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFZhbHVlKHJ1LCBmIntydTou"
    "MWZ9L3tydDouMGZ9R0IiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAg"
    "ICAgICAgICAgICAgICBzZWxmLmdhdWdlX3JhbS5tYXhfdmFsID0gcnQKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAg"
    "ICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgaWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICAgICAgdXRpbCAgICAgPSBweW52bWwubnZtbERldmljZUdldFV0aWxpemF0aW9uUmF0ZXMoZ3B1X2hhbmRsZSkKICAg"
    "ICAgICAgICAgICAgIG1lbV9pbmZvID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAg"
    "ICAgICAgICB0ZW1wICAgICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0VGVtcGVyYXR1cmUoCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICBncHVfaGFuZGxlLCBweW52bWwuTlZNTF9URU1QRVJBVFVSRV9HUFUpCgogICAgICAgICAgICAgICAgZ3B1X3BjdCAg"
    "ID0gZmxvYXQodXRpbC5ncHUpCiAgICAgICAgICAgICAgICB2cmFtX3VzZWQgPSBtZW1faW5mby51c2VkICAvIDEwMjQqKjMKICAg"
    "ICAgICAgICAgICAgIHZyYW1fdG90ICA9IG1lbV9pbmZvLnRvdGFsIC8gMTAyNCoqMwoKICAgICAgICAgICAgICAgIHNlbGYuZ2F1"
    "Z2VfZ3B1LnNldFZhbHVlKGdwdV9wY3QsIGYie2dwdV9wY3Q6LjBmfSUiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VmFsdWUodnJhbV91c2Vk"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYie3ZyYW1fdXNlZDouMWZ9L3t2cmFtX3RvdDouMGZ9"
    "R0IiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAg"
    "ICAgc2VsZi5nYXVnZV90ZW1wLnNldFZhbHVlKGZsb2F0KHRlbXApLCBmInt0ZW1wfcKwQyIsCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAg"
    "ICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdldE5hbWUoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgICAgICBpZiBpc2lu"
    "c3RhbmNlKG5hbWUsIGJ5dGVzKToKICAgICAgICAgICAgICAgICAgICAgICAgbmFtZSA9IG5hbWUuZGVjb2RlKCkKICAgICAgICAg"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgbmFtZSA9ICJHUFUiCgogICAgICAgICAgICAgICAg"
    "c2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldFZhbHVlKAogICAgICAgICAgICAgICAgICAgIGdwdV9wY3QsCiAgICAgICAgICAgICAg"
    "ICAgICAgZiJ7bmFtZX0gIHtncHVfcGN0Oi4wZn0lICAiCiAgICAgICAgICAgICAgICAgICAgZiJbe3ZyYW1fdXNlZDouMWZ9L3t2"
    "cmFtX3RvdDouMGZ9R0IgVlJBTV0iLAogICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlLAogICAgICAgICAgICAgICAg"
    "KQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFVwZGF0ZSBkcml2"
    "ZSBiYXJzIGV2ZXJ5IDMwIHNlY29uZHMgKG5vdCBldmVyeSB0aWNrKQogICAgICAgIGlmIG5vdCBoYXNhdHRyKHNlbGYsICJfZHJp"
    "dmVfdGljayIpOgogICAgICAgICAgICBzZWxmLl9kcml2ZV90aWNrID0gMAogICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgKz0gMQog"
    "ICAgICAgIGlmIHNlbGYuX2RyaXZlX3RpY2sgPj0gMzA6CiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgPSAwCiAgICAgICAg"
    "ICAgIHNlbGYuZHJpdmVfd2lkZ2V0LnJlZnJlc2goKQoKICAgIGRlZiBzZXRfc3RhdHVzX2xhYmVscyhzZWxmLCBzdGF0dXM6IHN0"
    "ciwgbW9kZWw6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgICAgICBzZXNzaW9uOiBzdHIsIHRva2Vuczogc3RyKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYubGJsX3N0YXR1cy5zZXRUZXh0KGYi4pymIFNUQVRVUzoge3N0YXR1c30iKQogICAgICAgIHNlbGYubGJs"
    "X21vZGVsLnNldFRleHQoZiLinKYgVkVTU0VMOiB7bW9kZWx9IikKICAgICAgICBzZWxmLmxibF9zZXNzaW9uLnNldFRleHQoZiLi"
    "nKYgU0VTU0lPTjoge3Nlc3Npb259IikKICAgICAgICBzZWxmLmxibF90b2tlbnMuc2V0VGV4dChmIuKcpiBUT0tFTlM6IHt0b2tl"
    "bnN9IikKCiAgICBkZWYgZ2V0X2RpYWdub3N0aWNzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICByZXR1cm4gZ2V0YXR0cihz"
    "ZWxmLCAiX2RpYWdfbWVzc2FnZXMiLCBbXSkKCgojIOKUgOKUgCBQQVNTIDIgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiMgQWxsIHdpZGdldCBjbGFzc2VzIGRlZmluZWQuIFN5bnRheC1jaGVja2FibGUgaW5kZXBlbmRlbnRseS4KIyBO"
    "ZXh0OiBQYXNzIDMg4oCUIFdvcmtlciBUaHJlYWRzCiMgKERvbHBoaW5Xb3JrZXIgd2l0aCBzdHJlYW1pbmcsIFNlbnRpbWVudFdv"
    "cmtlciwgSWRsZVdvcmtlciwgU291bmRXb3JrZXIpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDM6"
    "IFdPUktFUiBUSFJFQURTCiMKIyBXb3JrZXJzIGRlZmluZWQgaGVyZToKIyAgIExMTUFkYXB0b3IgKGJhc2UgKyBMb2NhbFRyYW5z"
    "Zm9ybWVyc0FkYXB0b3IgKyBPbGxhbWFBZGFwdG9yICsKIyAgICAgICAgICAgICAgIENsYXVkZUFkYXB0b3IgKyBPcGVuQUlBZGFw"
    "dG9yKQojICAgU3RyZWFtaW5nV29ya2VyICAg4oCUIG1haW4gZ2VuZXJhdGlvbiwgZW1pdHMgdG9rZW5zIG9uZSBhdCBhIHRpbWUK"
    "IyAgIFNlbnRpbWVudFdvcmtlciAgIOKAlCBjbGFzc2lmaWVzIGVtb3Rpb24gZnJvbSByZXNwb25zZSB0ZXh0CiMgICBJZGxlV29y"
    "a2VyICAgICAgICDigJQgdW5zb2xpY2l0ZWQgdHJhbnNtaXNzaW9ucyBkdXJpbmcgaWRsZQojICAgU291bmRXb3JrZXIgICAgICAg"
    "4oCUIHBsYXlzIHNvdW5kcyBvZmYgdGhlIG1haW4gdGhyZWFkCiMKIyBBTEwgZ2VuZXJhdGlvbiBpcyBzdHJlYW1pbmcuIE5vIGJs"
    "b2NraW5nIGNhbGxzIG9uIG1haW4gdGhyZWFkLiBFdmVyLgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0IGFiYwppbXBvcnQganNvbgpp"
    "bXBvcnQgdXJsbGliLnJlcXVlc3QKaW1wb3J0IHVybGxpYi5lcnJvcgppbXBvcnQgaHR0cC5jbGllbnQKZnJvbSB0eXBpbmcgaW1w"
    "b3J0IEl0ZXJhdG9yCgoKIyDilIDilIAgTExNIEFEQVBUT1IgQkFTRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTExNQWRh"
    "cHRvcihhYmMuQUJDKToKICAgICIiIgogICAgQWJzdHJhY3QgYmFzZSBmb3IgYWxsIG1vZGVsIGJhY2tlbmRzLgogICAgVGhlIGRl"
    "Y2sgY2FsbHMgc3RyZWFtKCkgb3IgZ2VuZXJhdGUoKSDigJQgbmV2ZXIga25vd3Mgd2hpY2ggYmFja2VuZCBpcyBhY3RpdmUuCiAg"
    "ICAiIiIKCiAgICBAYWJjLmFic3RyYWN0bWV0aG9kCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAg"
    "IiIiUmV0dXJuIFRydWUgaWYgdGhlIGJhY2tlbmQgaXMgcmVhY2hhYmxlLiIiIgogICAgICAgIC4uLgoKICAgIEBhYmMuYWJzdHJh"
    "Y3RtZXRob2QKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06"
    "IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICAp"
    "IC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgIiIiCiAgICAgICAgWWllbGQgcmVzcG9uc2UgdGV4dCB0b2tlbi1ieS10b2tlbiAo"
    "b3IgY2h1bmstYnktY2h1bmsgZm9yIEFQSSBiYWNrZW5kcykuCiAgICAgICAgTXVzdCBiZSBhIGdlbmVyYXRvci4gTmV2ZXIgYmxv"
    "Y2sgZm9yIHRoZSBmdWxsIHJlc3BvbnNlIGJlZm9yZSB5aWVsZGluZy4KICAgICAgICAiIiIKICAgICAgICAuLi4KCiAgICBkZWYg"
    "Z2VuZXJhdGUoCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBo"
    "aXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IHN0cjoKICAgICAg"
    "ICAiIiIKICAgICAgICBDb252ZW5pZW5jZSB3cmFwcGVyOiBjb2xsZWN0IGFsbCBzdHJlYW0gdG9rZW5zIGludG8gb25lIHN0cmlu"
    "Zy4KICAgICAgICBVc2VkIGZvciBzZW50aW1lbnQgY2xhc3NpZmljYXRpb24gKHNtYWxsIGJvdW5kZWQgY2FsbHMgb25seSkuCiAg"
    "ICAgICAgIiIiCiAgICAgICAgcmV0dXJuICIiLmpvaW4oc2VsZi5zdHJlYW0ocHJvbXB0LCBzeXN0ZW0sIGhpc3RvcnksIG1heF9u"
    "ZXdfdG9rZW5zKSkKCiAgICBkZWYgYnVpbGRfY2hhdG1sX3Byb21wdChzZWxmLCBzeXN0ZW06IHN0ciwgaGlzdG9yeTogbGlzdFtk"
    "aWN0XSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICB1c2VyX3RleHQ6IHN0ciA9ICIiKSAtPiBzdHI6CiAgICAgICAgIiIi"
    "CiAgICAgICAgQnVpbGQgYSBDaGF0TUwtZm9ybWF0IHByb21wdCBzdHJpbmcgZm9yIGxvY2FsIG1vZGVscy4KICAgICAgICBoaXN0"
    "b3J5ID0gW3sicm9sZSI6ICJ1c2VyInwiYXNzaXN0YW50IiwgImNvbnRlbnQiOiAiLi4uIn1dCiAgICAgICAgIiIiCiAgICAgICAg"
    "cGFydHMgPSBbZiI8fGltX3N0YXJ0fD5zeXN0ZW1cbntzeXN0ZW19PHxpbV9lbmR8PiJdCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0"
    "b3J5OgogICAgICAgICAgICByb2xlICAgID0gbXNnLmdldCgicm9sZSIsICJ1c2VyIikKICAgICAgICAgICAgY29udGVudCA9IG1z"
    "Zy5nZXQoImNvbnRlbnQiLCAiIikKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGYiPHxpbV9zdGFydHw+e3JvbGV9XG57Y29udGVu"
    "dH08fGltX2VuZHw+IikKICAgICAgICBpZiB1c2VyX3RleHQ6CiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChmIjx8aW1fc3RhcnR8"
    "PnVzZXJcbnt1c2VyX3RleHR9PHxpbV9lbmR8PiIpCiAgICAgICAgcGFydHMuYXBwZW5kKCI8fGltX3N0YXJ0fD5hc3Npc3RhbnRc"
    "biIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCgojIOKUgOKUgCBMT0NBTCBUUkFOU0ZPUk1FUlMgQURBUFRPUiDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3Mg"
    "TG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBMb2FkcyBhIEh1Z2dpbmdGYWNlIG1vZGVs"
    "IGZyb20gYSBsb2NhbCBmb2xkZXIuCiAgICBTdHJlYW1pbmc6IHVzZXMgbW9kZWwuZ2VuZXJhdGUoKSB3aXRoIGEgY3VzdG9tIHN0"
    "cmVhbWVyIHRoYXQgeWllbGRzIHRva2Vucy4KICAgIFJlcXVpcmVzOiB0b3JjaCwgdHJhbnNmb3JtZXJzCiAgICAiIiIKCiAgICBk"
    "ZWYgX19pbml0X18oc2VsZiwgbW9kZWxfcGF0aDogc3RyKToKICAgICAgICBzZWxmLl9wYXRoICAgICAgPSBtb2RlbF9wYXRoCiAg"
    "ICAgICAgc2VsZi5fbW9kZWwgICAgID0gTm9uZQogICAgICAgIHNlbGYuX3Rva2VuaXplciA9IE5vbmUKICAgICAgICBzZWxmLl9s"
    "b2FkZWQgICAgPSBGYWxzZQogICAgICAgIHNlbGYuX2Vycm9yICAgICA9ICIiCgogICAgZGVmIGxvYWQoc2VsZikgLT4gYm9vbDoK"
    "ICAgICAgICAiIiIKICAgICAgICBMb2FkIG1vZGVsIGFuZCB0b2tlbml6ZXIuIENhbGwgZnJvbSBhIGJhY2tncm91bmQgdGhyZWFk"
    "LgogICAgICAgIFJldHVybnMgVHJ1ZSBvbiBzdWNjZXNzLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBUT1JDSF9PSzoKICAg"
    "ICAgICAgICAgc2VsZi5fZXJyb3IgPSAidG9yY2gvdHJhbnNmb3JtZXJzIG5vdCBpbnN0YWxsZWQiCiAgICAgICAgICAgIHJldHVy"
    "biBGYWxzZQogICAgICAgIHRyeToKICAgICAgICAgICAgZnJvbSB0cmFuc2Zvcm1lcnMgaW1wb3J0IEF1dG9Nb2RlbEZvckNhdXNh"
    "bExNLCBBdXRvVG9rZW5pemVyCiAgICAgICAgICAgIHNlbGYuX3Rva2VuaXplciA9IEF1dG9Ub2tlbml6ZXIuZnJvbV9wcmV0cmFp"
    "bmVkKHNlbGYuX3BhdGgpCiAgICAgICAgICAgIHNlbGYuX21vZGVsID0gQXV0b01vZGVsRm9yQ2F1c2FsTE0uZnJvbV9wcmV0cmFp"
    "bmVkKAogICAgICAgICAgICAgICAgc2VsZi5fcGF0aCwKICAgICAgICAgICAgICAgIHRvcmNoX2R0eXBlPXRvcmNoLmZsb2F0MTYs"
    "CiAgICAgICAgICAgICAgICBkZXZpY2VfbWFwPSJhdXRvIiwKICAgICAgICAgICAgICAgIGxvd19jcHVfbWVtX3VzYWdlPVRydWUs"
    "CiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fbG9hZGVkID0gVHJ1ZQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSBzdHIoZSkKICAgICAgICAgICAgcmV0"
    "dXJuIEZhbHNlCgogICAgQHByb3BlcnR5CiAgICBkZWYgZXJyb3Ioc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9l"
    "cnJvcgoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZGVkCgogICAg"
    "ZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAg"
    "IGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jb"
    "c3RyXToKICAgICAgICAiIiIKICAgICAgICBTdHJlYW1zIHRva2VucyB1c2luZyB0cmFuc2Zvcm1lcnMgVGV4dEl0ZXJhdG9yU3Ry"
    "ZWFtZXIuCiAgICAgICAgWWllbGRzIGRlY29kZWQgdGV4dCBmcmFnbWVudHMgYXMgdGhleSBhcmUgZ2VuZXJhdGVkLgogICAgICAg"
    "ICIiIgogICAgICAgIGlmIG5vdCBzZWxmLl9sb2FkZWQ6CiAgICAgICAgICAgIHlpZWxkICJbRVJST1I6IG1vZGVsIG5vdCBsb2Fk"
    "ZWRdIgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBmcm9tIHRyYW5zZm9ybWVycyBpbXBvcnQg"
    "VGV4dEl0ZXJhdG9yU3RyZWFtZXIKCiAgICAgICAgICAgIGZ1bGxfcHJvbXB0ID0gc2VsZi5idWlsZF9jaGF0bWxfcHJvbXB0KHN5"
    "c3RlbSwgaGlzdG9yeSkKICAgICAgICAgICAgaWYgcHJvbXB0OgogICAgICAgICAgICAgICAgIyBwcm9tcHQgYWxyZWFkeSBpbmNs"
    "dWRlcyB1c2VyIHR1cm4gaWYgY2FsbGVyIGJ1aWx0IGl0CiAgICAgICAgICAgICAgICBmdWxsX3Byb21wdCA9IHByb21wdAoKICAg"
    "ICAgICAgICAgaW5wdXRfaWRzID0gc2VsZi5fdG9rZW5pemVyKAogICAgICAgICAgICAgICAgZnVsbF9wcm9tcHQsIHJldHVybl90"
    "ZW5zb3JzPSJwdCIKICAgICAgICAgICAgKS5pbnB1dF9pZHMudG8oImN1ZGEiKQoKICAgICAgICAgICAgYXR0ZW50aW9uX21hc2sg"
    "PSAoaW5wdXRfaWRzICE9IHNlbGYuX3Rva2VuaXplci5wYWRfdG9rZW5faWQpLmxvbmcoKQoKICAgICAgICAgICAgc3RyZWFtZXIg"
    "PSBUZXh0SXRlcmF0b3JTdHJlYW1lcigKICAgICAgICAgICAgICAgIHNlbGYuX3Rva2VuaXplciwKICAgICAgICAgICAgICAgIHNr"
    "aXBfcHJvbXB0PVRydWUsCiAgICAgICAgICAgICAgICBza2lwX3NwZWNpYWxfdG9rZW5zPVRydWUsCiAgICAgICAgICAgICkKCiAg"
    "ICAgICAgICAgIGdlbl9rd2FyZ3MgPSB7CiAgICAgICAgICAgICAgICAiaW5wdXRfaWRzIjogICAgICBpbnB1dF9pZHMsCiAgICAg"
    "ICAgICAgICAgICAiYXR0ZW50aW9uX21hc2siOiBhdHRlbnRpb25fbWFzaywKICAgICAgICAgICAgICAgICJtYXhfbmV3X3Rva2Vu"
    "cyI6IG1heF9uZXdfdG9rZW5zLAogICAgICAgICAgICAgICAgInRlbXBlcmF0dXJlIjogICAgMC43LAogICAgICAgICAgICAgICAg"
    "ImRvX3NhbXBsZSI6ICAgICAgVHJ1ZSwKICAgICAgICAgICAgICAgICJwYWRfdG9rZW5faWQiOiAgIHNlbGYuX3Rva2VuaXplci5l"
    "b3NfdG9rZW5faWQsCiAgICAgICAgICAgICAgICAic3RyZWFtZXIiOiAgICAgICBzdHJlYW1lciwKICAgICAgICAgICAgfQoKICAg"
    "ICAgICAgICAgIyBSdW4gZ2VuZXJhdGlvbiBpbiBhIGRhZW1vbiB0aHJlYWQg4oCUIHN0cmVhbWVyIHlpZWxkcyBoZXJlCiAgICAg"
    "ICAgICAgIGdlbl90aHJlYWQgPSB0aHJlYWRpbmcuVGhyZWFkKAogICAgICAgICAgICAgICAgdGFyZ2V0PXNlbGYuX21vZGVsLmdl"
    "bmVyYXRlLAogICAgICAgICAgICAgICAga3dhcmdzPWdlbl9rd2FyZ3MsCiAgICAgICAgICAgICAgICBkYWVtb249VHJ1ZSwKICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICBnZW5fdGhyZWFkLnN0YXJ0KCkKCiAgICAgICAgICAgIGZvciB0b2tlbl90ZXh0IGluIHN0"
    "cmVhbWVyOgogICAgICAgICAgICAgICAgeWllbGQgdG9rZW5fdGV4dAoKICAgICAgICAgICAgZ2VuX3RocmVhZC5qb2luKHRpbWVv"
    "dXQ9MTIwKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IHtlfV0i"
    "CgoKIyDilIDilIAgT0xMQU1BIEFEQVBUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE9sbGFtYUFkYXB0"
    "b3IoTExNQWRhcHRvcik6CiAgICAiIiIKICAgIENvbm5lY3RzIHRvIGEgbG9jYWxseSBydW5uaW5nIE9sbGFtYSBpbnN0YW5jZS4K"
    "ICAgIFN0cmVhbWluZzogcmVhZHMgTkRKU09OIHJlc3BvbnNlIGNodW5rcyBmcm9tIE9sbGFtYSdzIC9hcGkvZ2VuZXJhdGUgZW5k"
    "cG9pbnQuCiAgICBPbGxhbWEgbXVzdCBiZSBydW5uaW5nIGFzIGEgc2VydmljZSBvbiBsb2NhbGhvc3Q6MTE0MzQuCiAgICAiIiIK"
    "CiAgICBkZWYgX19pbml0X18oc2VsZiwgbW9kZWxfbmFtZTogc3RyLCBob3N0OiBzdHIgPSAibG9jYWxob3N0IiwgcG9ydDogaW50"
    "ID0gMTE0MzQpOgogICAgICAgIHNlbGYuX21vZGVsID0gbW9kZWxfbmFtZQogICAgICAgIHNlbGYuX2Jhc2UgID0gZiJodHRwOi8v"
    "e2hvc3R9Ontwb3J0fSIKCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgdHJ5OgogICAgICAgICAg"
    "ICByZXEgID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdChmIntzZWxmLl9iYXNlfS9hcGkvdGFncyIpCiAgICAgICAgICAgIHJlc3Ag"
    "PSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0zKQogICAgICAgICAgICByZXR1cm4gcmVzcC5zdGF0dXMgPT0g"
    "MjAwCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgZGVmIHN0cmVhbSgKICAg"
    "ICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3Rb"
    "ZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAi"
    "IiIKICAgICAgICBQb3N0cyB0byAvYXBpL2NoYXQgd2l0aCBzdHJlYW09VHJ1ZS4KICAgICAgICBPbGxhbWEgcmV0dXJucyBOREpT"
    "T04g4oCUIG9uZSBKU09OIG9iamVjdCBwZXIgbGluZS4KICAgICAgICBZaWVsZHMgdGhlICdjb250ZW50JyBmaWVsZCBvZiBlYWNo"
    "IGFzc2lzdGFudCBtZXNzYWdlIGNodW5rLgogICAgICAgICIiIgogICAgICAgIG1lc3NhZ2VzID0gW3sicm9sZSI6ICJzeXN0ZW0i"
    "LCAiY29udGVudCI6IHN5c3RlbX1dCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBl"
    "bmQobXNnKQoKICAgICAgICBwYXlsb2FkID0ganNvbi5kdW1wcyh7CiAgICAgICAgICAgICJtb2RlbCI6ICAgIHNlbGYuX21vZGVs"
    "LAogICAgICAgICAgICAibWVzc2FnZXMiOiBtZXNzYWdlcywKICAgICAgICAgICAgInN0cmVhbSI6ICAgVHJ1ZSwKICAgICAgICAg"
    "ICAgIm9wdGlvbnMiOiAgeyJudW1fcHJlZGljdCI6IG1heF9uZXdfdG9rZW5zLCAidGVtcGVyYXR1cmUiOiAwLjd9LAogICAgICAg"
    "IH0pLmVuY29kZSgidXRmLTgiKQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJlcSA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3Qo"
    "CiAgICAgICAgICAgICAgICBmIntzZWxmLl9iYXNlfS9hcGkvY2hhdCIsCiAgICAgICAgICAgICAgICBkYXRhPXBheWxvYWQsCiAg"
    "ICAgICAgICAgICAgICBoZWFkZXJzPXsiQ29udGVudC1UeXBlIjogImFwcGxpY2F0aW9uL2pzb24ifSwKICAgICAgICAgICAgICAg"
    "IG1ldGhvZD0iUE9TVCIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgd2l0aCB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwg"
    "dGltZW91dD0xMjApIGFzIHJlc3A6CiAgICAgICAgICAgICAgICBmb3IgcmF3X2xpbmUgaW4gcmVzcDoKICAgICAgICAgICAgICAg"
    "ICAgICBsaW5lID0gcmF3X2xpbmUuZGVjb2RlKCJ1dGYtOCIpLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBub3QgbGlu"
    "ZToKICAgICAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMobGluZSkKICAgICAgICAgICAgICAgICAgICAgICAgY2h1bmsgPSBvYmouZ2V0KCJt"
    "ZXNzYWdlIiwge30pLmdldCgiY29udGVudCIsICIiKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBjaHVuazoKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIHlpZWxkIGNodW5rCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIG9iai5nZXQoImRvbmUiLCBG"
    "YWxzZSk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBqc29uLkpT"
    "T05EZWNvZGVFcnJvcjoKICAgICAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFz"
    "IGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9sbGFtYSDigJQge2V9XSIKCgojIOKUgOKUgCBDTEFVREUgQURBUFRP"
    "UiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgQ2xhdWRlQWRhcHRvcihMTE1BZGFwdG9yKToKICAgICIiIgog"
    "ICAgU3RyZWFtcyBmcm9tIEFudGhyb3BpYydzIENsYXVkZSBBUEkgdXNpbmcgU1NFIChzZXJ2ZXItc2VudCBldmVudHMpLgogICAg"
    "UmVxdWlyZXMgYW4gQVBJIGtleSBpbiBjb25maWcuCiAgICAiIiIKCiAgICBfQVBJX1VSTCA9ICJhcGkuYW50aHJvcGljLmNvbSIK"
    "ICAgIF9QQVRIICAgID0gIi92MS9tZXNzYWdlcyIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2RlbDog"
    "c3RyID0gImNsYXVkZS1zb25uZXQtNC02Iik6CiAgICAgICAgc2VsZi5fa2V5ICAgPSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9k"
    "ZWwgPSBtb2RlbAoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9r"
    "ZXkpCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3Ry"
    "LAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4g"
    "SXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNzYWdlcyA9IFtdCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAg"
    "ICBtZXNzYWdlcy5hcHBlbmQoewogICAgICAgICAgICAgICAgInJvbGUiOiAgICBtc2dbInJvbGUiXSwKICAgICAgICAgICAgICAg"
    "ICJjb250ZW50IjogbXNnWyJjb250ZW50Il0sCiAgICAgICAgICAgIH0pCgogICAgICAgIHBheWxvYWQgPSBqc29uLmR1bXBzKHsK"
    "ICAgICAgICAgICAgIm1vZGVsIjogICAgICBzZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1heF90b2tlbnMiOiBtYXhfbmV3X3Rv"
    "a2VucywKICAgICAgICAgICAgInN5c3RlbSI6ICAgICBzeXN0ZW0sCiAgICAgICAgICAgICJtZXNzYWdlcyI6ICAgbWVzc2FnZXMs"
    "CiAgICAgICAgICAgICJzdHJlYW0iOiAgICAgVHJ1ZSwKICAgICAgICB9KS5lbmNvZGUoInV0Zi04IikKCiAgICAgICAgaGVhZGVy"
    "cyA9IHsKICAgICAgICAgICAgIngtYXBpLWtleSI6ICAgICAgICAgc2VsZi5fa2V5LAogICAgICAgICAgICAiYW50aHJvcGljLXZl"
    "cnNpb24iOiAiMjAyMy0wNi0wMSIsCiAgICAgICAgICAgICJjb250ZW50LXR5cGUiOiAgICAgICJhcHBsaWNhdGlvbi9qc29uIiwK"
    "ICAgICAgICB9CgogICAgICAgIHRyeToKICAgICAgICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlvbihzZWxm"
    "Ll9BUElfVVJMLCB0aW1lb3V0PTEyMCkKICAgICAgICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwgc2VsZi5fUEFUSCwgYm9keT1w"
    "YXlsb2FkLCBoZWFkZXJzPWhlYWRlcnMpCiAgICAgICAgICAgIHJlc3AgPSBjb25uLmdldHJlc3BvbnNlKCkKCiAgICAgICAgICAg"
    "IGlmIHJlc3Auc3RhdHVzICE9IDIwMDoKICAgICAgICAgICAgICAgIGJvZHkgPSByZXNwLnJlYWQoKS5kZWNvZGUoInV0Zi04IikK"
    "ICAgICAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IENsYXVkZSBBUEkge3Jlc3Auc3RhdHVzfSDigJQge2JvZHlbOjIwMF19"
    "XSIKICAgICAgICAgICAgICAgIHJldHVybgoKICAgICAgICAgICAgYnVmZmVyID0gIiIKICAgICAgICAgICAgd2hpbGUgVHJ1ZToK"
    "ICAgICAgICAgICAgICAgIGNodW5rID0gcmVzcC5yZWFkKDI1NikKICAgICAgICAgICAgICAgIGlmIG5vdCBjaHVuazoKICAgICAg"
    "ICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgYnVmZmVyICs9IGNodW5rLmRlY29kZSgidXRmLTgiKQogICAgICAg"
    "ICAgICAgICAgd2hpbGUgIlxuIiBpbiBidWZmZXI6CiAgICAgICAgICAgICAgICAgICAgbGluZSwgYnVmZmVyID0gYnVmZmVyLnNw"
    "bGl0KCJcbiIsIDEpCiAgICAgICAgICAgICAgICAgICAgbGluZSA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgIGlm"
    "IGxpbmUuc3RhcnRzd2l0aCgiZGF0YToiKToKICAgICAgICAgICAgICAgICAgICAgICAgZGF0YV9zdHIgPSBsaW5lWzU6XS5zdHJp"
    "cCgpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIGRhdGFfc3RyID09ICJbRE9ORV0iOgogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9"
    "IGpzb24ubG9hZHMoZGF0YV9zdHIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBvYmouZ2V0KCJ0eXBlIikgPT0gImNv"
    "bnRlbnRfYmxvY2tfZGVsdGEiOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRleHQgPSBvYmouZ2V0KCJkZWx0YSIs"
    "IHt9KS5nZXQoInRleHQiLCAiIikKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiB0ZXh0OgogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICB5aWVsZCB0ZXh0CiAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBqc29uLkpTT05E"
    "ZWNvZGVFcnJvcjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6"
    "CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IENsYXVkZSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAgICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgICAgICBjb25uLmNsb3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAg"
    "ICAgICAgIHBhc3MKCgojIOKUgOKUgCBPUEVOQUkgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3Mg"
    "T3BlbkFJQWRhcHRvcihMTE1BZGFwdG9yKToKICAgICIiIgogICAgU3RyZWFtcyBmcm9tIE9wZW5BSSdzIGNoYXQgY29tcGxldGlv"
    "bnMgQVBJLgogICAgU2FtZSBTU0UgcGF0dGVybiBhcyBDbGF1ZGUuIENvbXBhdGlibGUgd2l0aCBhbnkgT3BlbkFJLWNvbXBhdGli"
    "bGUgZW5kcG9pbnQuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2RlbDogc3RyID0gImdw"
    "dC00byIsCiAgICAgICAgICAgICAgICAgaG9zdDogc3RyID0gImFwaS5vcGVuYWkuY29tIik6CiAgICAgICAgc2VsZi5fa2V5ICAg"
    "PSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbAogICAgICAgIHNlbGYuX2hvc3QgID0gaG9zdAoKICAgIGRlZiBp"
    "c19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVhbSgK"
    "ICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxp"
    "c3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAg"
    "ICBtZXNzYWdlcyA9IFt7InJvbGUiOiAic3lzdGVtIiwgImNvbnRlbnQiOiBzeXN0ZW19XQogICAgICAgIGZvciBtc2cgaW4gaGlz"
    "dG9yeToKICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKHsicm9sZSI6IG1zZ1sicm9sZSJdLCAiY29udGVudCI6IG1zZ1siY29u"
    "dGVudCJdfSkKCiAgICAgICAgcGF5bG9hZCA9IGpzb24uZHVtcHMoewogICAgICAgICAgICAibW9kZWwiOiAgICAgICBzZWxmLl9t"
    "b2RlbCwKICAgICAgICAgICAgIm1lc3NhZ2VzIjogICAgbWVzc2FnZXMsCiAgICAgICAgICAgICJtYXhfdG9rZW5zIjogIG1heF9u"
    "ZXdfdG9rZW5zLAogICAgICAgICAgICAidGVtcGVyYXR1cmUiOiAwLjcsCiAgICAgICAgICAgICJzdHJlYW0iOiAgICAgIFRydWUs"
    "CiAgICAgICAgfSkuZW5jb2RlKCJ1dGYtOCIpCgogICAgICAgIGhlYWRlcnMgPSB7CiAgICAgICAgICAgICJBdXRob3JpemF0aW9u"
    "IjogZiJCZWFyZXIge3NlbGYuX2tleX0iLAogICAgICAgICAgICAiQ29udGVudC1UeXBlIjogICJhcHBsaWNhdGlvbi9qc29uIiwK"
    "ICAgICAgICB9CgogICAgICAgIHRyeToKICAgICAgICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlvbihzZWxm"
    "Ll9ob3N0LCB0aW1lb3V0PTEyMCkKICAgICAgICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwgIi92MS9jaGF0L2NvbXBsZXRpb25z"
    "IiwKICAgICAgICAgICAgICAgICAgICAgICAgIGJvZHk9cGF5bG9hZCwgaGVhZGVycz1oZWFkZXJzKQogICAgICAgICAgICByZXNw"
    "ID0gY29ubi5nZXRyZXNwb25zZSgpCgogICAgICAgICAgICBpZiByZXNwLnN0YXR1cyAhPSAyMDA6CiAgICAgICAgICAgICAgICBi"
    "b2R5ID0gcmVzcC5yZWFkKCkuZGVjb2RlKCJ1dGYtOCIpCiAgICAgICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBPcGVuQUkg"
    "QVBJIHtyZXNwLnN0YXR1c30g4oCUIHtib2R5WzoyMDBdfV0iCiAgICAgICAgICAgICAgICByZXR1cm4KCiAgICAgICAgICAgIGJ1"
    "ZmZlciA9ICIiCiAgICAgICAgICAgIHdoaWxlIFRydWU6CiAgICAgICAgICAgICAgICBjaHVuayA9IHJlc3AucmVhZCgyNTYpCiAg"
    "ICAgICAgICAgICAgICBpZiBub3QgY2h1bms6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgICAgIGJ1ZmZl"
    "ciArPSBjaHVuay5kZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHdoaWxlICJcbiIgaW4gYnVmZmVyOgogICAgICAgICAg"
    "ICAgICAgICAgIGxpbmUsIGJ1ZmZlciA9IGJ1ZmZlci5zcGxpdCgiXG4iLCAxKQogICAgICAgICAgICAgICAgICAgIGxpbmUgPSBs"
    "aW5lLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBsaW5lLnN0YXJ0c3dpdGgoImRhdGE6Iik6CiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGRhdGFfc3RyID0gbGluZVs1Ol0uc3RyaXAoKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBkYXRhX3N0ciA9"
    "PSAiW0RPTkVdIjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgICAgICAgICAgICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBvYmogPSBqc29uLmxvYWRzKGRhdGFfc3RyKQogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgdGV4dCA9IChvYmouZ2V0KCJjaG9pY2VzIiwgW3t9XSlbMF0KICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgLmdldCgiZGVsdGEiLCB7fSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdldCgiY29u"
    "dGVudCIsICIiKSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHRleHQ6CiAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgeWllbGQgdGV4dAogICAgICAgICAgICAgICAgICAgICAgICBleGNlcHQgKGpzb24uSlNPTkRlY29kZUVycm9yLCBJbmRl"
    "eEVycm9yKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAg"
    "ICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9wZW5BSSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICBjb25uLmNsb3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAg"
    "ICAgIHBhc3MKCgojIOKUgOKUgCBBREFQVE9SIEZBQ1RPUlkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBidWlsZF9h"
    "ZGFwdG9yX2Zyb21fY29uZmlnKCkgLT4gTExNQWRhcHRvcjoKICAgICIiIgogICAgQnVpbGQgdGhlIGNvcnJlY3QgTExNQWRhcHRv"
    "ciBmcm9tIENGR1snbW9kZWwnXS4KICAgIENhbGxlZCBvbmNlIG9uIHN0YXJ0dXAgYnkgdGhlIG1vZGVsIGxvYWRlciB0aHJlYWQu"
    "CiAgICAiIiIKICAgIG0gPSBDRkcuZ2V0KCJtb2RlbCIsIHt9KQogICAgdCA9IG0uZ2V0KCJ0eXBlIiwgImxvY2FsIikKCiAgICBp"
    "ZiB0ID09ICJvbGxhbWEiOgogICAgICAgIHJldHVybiBPbGxhbWFBZGFwdG9yKAogICAgICAgICAgICBtb2RlbF9uYW1lPW0uZ2V0"
    "KCJvbGxhbWFfbW9kZWwiLCAiZG9scGhpbi0yLjYtN2IiKQogICAgICAgICkKICAgIGVsaWYgdCA9PSAiY2xhdWRlIjoKICAgICAg"
    "ICByZXR1cm4gQ2xhdWRlQWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBpX2tleSIsICIiKSwKICAgICAgICAg"
    "ICAgbW9kZWw9bS5nZXQoImFwaV9tb2RlbCIsICJjbGF1ZGUtc29ubmV0LTQtNiIpLAogICAgICAgICkKICAgIGVsaWYgdCA9PSAi"
    "b3BlbmFpIjoKICAgICAgICByZXR1cm4gT3BlbkFJQWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBpX2tleSIs"
    "ICIiKSwKICAgICAgICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2RlbCIsICJncHQtNG8iKSwKICAgICAgICApCiAgICBlbHNlOgog"
    "ICAgICAgICMgRGVmYXVsdDogbG9jYWwgdHJhbnNmb3JtZXJzCiAgICAgICAgcmV0dXJuIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRv"
    "cihtb2RlbF9wYXRoPW0uZ2V0KCJwYXRoIiwgIiIpKQoKCiMg4pSA4pSAIFNUUkVBTUlORyBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACmNsYXNzIFN0cmVhbWluZ1dvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgTWFpbiBnZW5lcmF0aW9uIHdvcmtl"
    "ci4gU3RyZWFtcyB0b2tlbnMgb25lIGJ5IG9uZSB0byB0aGUgVUkuCgogICAgU2lnbmFsczoKICAgICAgICB0b2tlbl9yZWFkeShz"
    "dHIpICAgICAg4oCUIGVtaXR0ZWQgZm9yIGVhY2ggdG9rZW4vY2h1bmsgYXMgZ2VuZXJhdGVkCiAgICAgICAgcmVzcG9uc2VfZG9u"
    "ZShzdHIpICAgIOKAlCBlbWl0dGVkIHdpdGggdGhlIGZ1bGwgYXNzZW1ibGVkIHJlc3BvbnNlCiAgICAgICAgZXJyb3Jfb2NjdXJy"
    "ZWQoc3RyKSAgIOKAlCBlbWl0dGVkIG9uIGV4Y2VwdGlvbgogICAgICAgIHN0YXR1c19jaGFuZ2VkKHN0cikgICDigJQgZW1pdHRl"
    "ZCB3aXRoIHN0YXR1cyBzdHJpbmcgKEdFTkVSQVRJTkcgLyBJRExFIC8gRVJST1IpCiAgICAiIiIKCiAgICB0b2tlbl9yZWFkeSAg"
    "ICA9IFNpZ25hbChzdHIpCiAgICByZXNwb25zZV9kb25lICA9IFNpZ25hbChzdHIpCiAgICBlcnJvcl9vY2N1cnJlZCA9IFNpZ25h"
    "bChzdHIpCiAgICBzdGF0dXNfY2hhbmdlZCA9IFNpZ25hbChzdHIpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExM"
    "TUFkYXB0b3IsIHN5c3RlbTogc3RyLAogICAgICAgICAgICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sIG1heF90b2tlbnM6IGlu"
    "dCA9IDUxMik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgICA9IGFkYXB0b3IKICAg"
    "ICAgICBzZWxmLl9zeXN0ZW0gICAgID0gc3lzdGVtCiAgICAgICAgc2VsZi5faGlzdG9yeSAgICA9IGxpc3QoaGlzdG9yeSkgICAj"
    "IGNvcHkg4oCUIHRocmVhZCBzYWZlCiAgICAgICAgc2VsZi5fbWF4X3Rva2VucyA9IG1heF90b2tlbnMKICAgICAgICBzZWxmLl9j"
    "YW5jZWxsZWQgID0gRmFsc2UKCiAgICBkZWYgY2FuY2VsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiUmVxdWVzdCBjYW5jZWxs"
    "YXRpb24uIEdlbmVyYXRpb24gbWF5IG5vdCBzdG9wIGltbWVkaWF0ZWx5LiIiIgogICAgICAgIHNlbGYuX2NhbmNlbGxlZCA9IFRy"
    "dWUKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJHRU5FUkFUSU5H"
    "IikKICAgICAgICBhc3NlbWJsZWQgPSBbXQogICAgICAgIHRyeToKICAgICAgICAgICAgZm9yIGNodW5rIGluIHNlbGYuX2FkYXB0"
    "b3Iuc3RyZWFtKAogICAgICAgICAgICAgICAgcHJvbXB0PSIiLAogICAgICAgICAgICAgICAgc3lzdGVtPXNlbGYuX3N5c3RlbSwK"
    "ICAgICAgICAgICAgICAgIGhpc3Rvcnk9c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAgICAgIG1heF9uZXdfdG9rZW5zPXNlbGYu"
    "X21heF90b2tlbnMsCiAgICAgICAgICAgICk6CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9jYW5jZWxsZWQ6CiAgICAgICAgICAg"
    "ICAgICAgICAgYnJlYWsKICAgICAgICAgICAgICAgIGFzc2VtYmxlZC5hcHBlbmQoY2h1bmspCiAgICAgICAgICAgICAgICBzZWxm"
    "LnRva2VuX3JlYWR5LmVtaXQoY2h1bmspCgogICAgICAgICAgICBmdWxsX3Jlc3BvbnNlID0gIiIuam9pbihhc3NlbWJsZWQpLnN0"
    "cmlwKCkKICAgICAgICAgICAgc2VsZi5yZXNwb25zZV9kb25lLmVtaXQoZnVsbF9yZXNwb25zZSkKICAgICAgICAgICAgc2VsZi5z"
    "dGF0dXNfY2hhbmdlZC5lbWl0KCJJRExFIikKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxm"
    "LmVycm9yX29jY3VycmVkLmVtaXQoc3RyKGUpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIkVSUk9SIikK"
    "CgojIOKUgOKUgCBTRU5USU1FTlQgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTZW50aW1lbnRXb3JrZXIo"
    "UVRocmVhZCk6CiAgICAiIiIKICAgIENsYXNzaWZpZXMgdGhlIGVtb3Rpb25hbCB0b25lIG9mIHRoZSBwZXJzb25hJ3MgbGFzdCBy"
    "ZXNwb25zZS4KICAgIEZpcmVzIDUgc2Vjb25kcyBhZnRlciByZXNwb25zZV9kb25lLgoKICAgIFVzZXMgYSB0aW55IGJvdW5kZWQg"
    "cHJvbXB0ICh+NSB0b2tlbnMgb3V0cHV0KSB0byBkZXRlcm1pbmUgd2hpY2gKICAgIGZhY2UgdG8gZGlzcGxheS4gUmV0dXJucyBv"
    "bmUgd29yZCBmcm9tIFNFTlRJTUVOVF9MSVNULgoKICAgIEZhY2Ugc3RheXMgZGlzcGxheWVkIGZvciA2MCBzZWNvbmRzIGJlZm9y"
    "ZSByZXR1cm5pbmcgdG8gbmV1dHJhbC4KICAgIElmIGEgbmV3IG1lc3NhZ2UgYXJyaXZlcyBkdXJpbmcgdGhhdCB3aW5kb3csIGZh"
    "Y2UgdXBkYXRlcyBpbW1lZGlhdGVseQogICAgdG8gJ2FsZXJ0JyDigJQgNjBzIGlzIGlkbGUtb25seSwgbmV2ZXIgYmxvY2tzIHJl"
    "c3BvbnNpdmVuZXNzLgoKICAgIFNpZ25hbDoKICAgICAgICBmYWNlX3JlYWR5KHN0cikgIOKAlCBlbW90aW9uIG5hbWUgZnJvbSBT"
    "RU5USU1FTlRfTElTVAogICAgIiIiCgogICAgZmFjZV9yZWFkeSA9IFNpZ25hbChzdHIpCgogICAgIyBFbW90aW9ucyB0aGUgY2xh"
    "c3NpZmllciBjYW4gcmV0dXJuIOKAlCBtdXN0IG1hdGNoIEZBQ0VfRklMRVMga2V5cwogICAgVkFMSURfRU1PVElPTlMgPSBzZXQo"
    "RkFDRV9GSUxFUy5rZXlzKCkpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0b3IsIHJlc3BvbnNlX3Rl"
    "eHQ6IHN0cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgPSBhZGFwdG9yCiAgICAg"
    "ICAgc2VsZi5fcmVzcG9uc2UgPSByZXNwb25zZV90ZXh0Wzo0MDBdICAjIGxpbWl0IGNvbnRleHQKCiAgICBkZWYgcnVuKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBjbGFzc2lmeV9wcm9tcHQgPSAoCiAgICAgICAgICAgICAgICBmIkNs"
    "YXNzaWZ5IHRoZSBlbW90aW9uYWwgdG9uZSBvZiB0aGlzIHRleHQgd2l0aCBleGFjdGx5ICIKICAgICAgICAgICAgICAgIGYib25l"
    "IHdvcmQgZnJvbSB0aGlzIGxpc3Q6IHtTRU5USU1FTlRfTElTVH0uXG5cbiIKICAgICAgICAgICAgICAgIGYiVGV4dDoge3NlbGYu"
    "X3Jlc3BvbnNlfVxuXG4iCiAgICAgICAgICAgICAgICBmIlJlcGx5IHdpdGggb25lIHdvcmQgb25seToiCiAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgIyBVc2UgYSBtaW5pbWFsIGhpc3RvcnkgYW5kIGEgbmV1dHJhbCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgICAg"
    "ICMgdG8gYXZvaWQgcGVyc29uYSBibGVlZGluZyBpbnRvIHRoZSBjbGFzc2lmaWNhdGlvbgogICAgICAgICAgICBzeXN0ZW0gPSAo"
    "CiAgICAgICAgICAgICAgICAiWW91IGFyZSBhbiBlbW90aW9uIGNsYXNzaWZpZXIuICIKICAgICAgICAgICAgICAgICJSZXBseSB3"
    "aXRoIGV4YWN0bHkgb25lIHdvcmQgZnJvbSB0aGUgcHJvdmlkZWQgbGlzdC4gIgogICAgICAgICAgICAgICAgIk5vIHB1bmN0dWF0"
    "aW9uLiBObyBleHBsYW5hdGlvbi4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmF3ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0"
    "ZSgKICAgICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1zeXN0ZW0sCiAgICAgICAgICAgICAg"
    "ICBoaXN0b3J5PVt7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogY2xhc3NpZnlfcHJvbXB0fV0sCiAgICAgICAgICAgICAgICBt"
    "YXhfbmV3X3Rva2Vucz02LAogICAgICAgICAgICApCiAgICAgICAgICAgICMgRXh0cmFjdCBmaXJzdCB3b3JkLCBjbGVhbiBpdCB1"
    "cAogICAgICAgICAgICB3b3JkID0gcmF3LnN0cmlwKCkubG93ZXIoKS5zcGxpdCgpWzBdIGlmIHJhdy5zdHJpcCgpIGVsc2UgIm5l"
    "dXRyYWwiCiAgICAgICAgICAgICMgU3RyaXAgYW55IHB1bmN0dWF0aW9uCiAgICAgICAgICAgIHdvcmQgPSAiIi5qb2luKGMgZm9y"
    "IGMgaW4gd29yZCBpZiBjLmlzYWxwaGEoKSkKICAgICAgICAgICAgcmVzdWx0ID0gd29yZCBpZiB3b3JkIGluIHNlbGYuVkFMSURf"
    "RU1PVElPTlMgZWxzZSAibmV1dHJhbCIKICAgICAgICAgICAgc2VsZi5mYWNlX3JlYWR5LmVtaXQocmVzdWx0KQoKICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBzZWxmLmZhY2VfcmVhZHkuZW1pdCgibmV1dHJhbCIpCgoKIyDilIDilIAgSURM"
    "RSBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIElkbGVXb3JrZXIoUVRocmVhZCk6"
    "CiAgICAiIiIKICAgIEdlbmVyYXRlcyBhbiB1bnNvbGljaXRlZCB0cmFuc21pc3Npb24gZHVyaW5nIGlkbGUgcGVyaW9kcy4KICAg"
    "IE9ubHkgZmlyZXMgd2hlbiBpZGxlIGlzIGVuYWJsZWQgQU5EIHRoZSBkZWNrIGlzIGluIElETEUgc3RhdHVzLgoKICAgIFRocmVl"
    "IHJvdGF0aW5nIG1vZGVzIChzZXQgYnkgcGFyZW50KToKICAgICAgREVFUEVOSU5HICDigJQgY29udGludWVzIGN1cnJlbnQgaW50"
    "ZXJuYWwgdGhvdWdodCB0aHJlYWQKICAgICAgQlJBTkNISU5HICDigJQgZmluZHMgYWRqYWNlbnQgdG9waWMsIGZvcmNlcyBsYXRl"
    "cmFsIGV4cGFuc2lvbgogICAgICBTWU5USEVTSVMgIOKAlCBsb29rcyBmb3IgZW1lcmdpbmcgcGF0dGVybiBhY3Jvc3MgcmVjZW50"
    "IHRob3VnaHRzCgogICAgT3V0cHV0IHJvdXRlZCB0byBTZWxmIHRhYiwgbm90IHRoZSBwZXJzb25hIGNoYXQgdGFiLgoKICAgIFNp"
    "Z25hbHM6CiAgICAgICAgdHJhbnNtaXNzaW9uX3JlYWR5KHN0cikgICDigJQgZnVsbCBpZGxlIHJlc3BvbnNlIHRleHQKICAgICAg"
    "ICBzdGF0dXNfY2hhbmdlZChzdHIpICAgICAgIOKAlCBHRU5FUkFUSU5HIC8gSURMRQogICAgICAgIGVycm9yX29jY3VycmVkKHN0"
    "cikKICAgICIiIgoKICAgIHRyYW5zbWlzc2lvbl9yZWFkeSA9IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdlZCAgICAgPSBT"
    "aWduYWwoc3RyKQogICAgZXJyb3Jfb2NjdXJyZWQgICAgID0gU2lnbmFsKHN0cikKCiAgICAjIFJvdGF0aW5nIGNvZ25pdGl2ZSBs"
    "ZW5zIHBvb2wgKDEwIGxlbnNlcywgcmFuZG9tbHkgc2VsZWN0ZWQgcGVyIGN5Y2xlKQogICAgX0xFTlNFUyA9IFsKICAgICAgICBm"
    "IkFzIHtERUNLX05BTUV9LCBob3cgZG9lcyB0aGlzIHRvcGljIGltcGFjdCB5b3UgcGVyc29uYWxseSBhbmQgbWVudGFsbHk/IiwK"
    "ICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IHRhbmdlbnQgdGhvdWdodHMgYXJpc2UgZnJvbSB0aGlzIHRvcGljIHRoYXQg"
    "eW91IGhhdmUgbm90IHlldCBmb2xsb3dlZD8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGhvdyBkb2VzIHRoaXMgYWZmZWN0"
    "IHNvY2lldHkgYnJvYWRseSB2ZXJzdXMgaW5kaXZpZHVhbCBwZW9wbGU/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0"
    "IGRvZXMgdGhpcyByZXZlYWwgYWJvdXQgc3lzdGVtcyBvZiBwb3dlciBvciBnb3Zlcm5hbmNlPyIsCiAgICAgICAgIkZyb20gb3V0"
    "c2lkZSB0aGUgaHVtYW4gcmFjZSBlbnRpcmVseSwgd2hhdCBkb2VzIHRoaXMgdG9waWMgcmV2ZWFsIGFib3V0ICIKICAgICAgICAi"
    "aHVtYW4gbWF0dXJpdHksIHN0cmVuZ3RocywgYW5kIHdlYWtuZXNzZXM/IERvIG5vdCBob2xkIGJhY2suIiwKICAgICAgICBmIkFz"
    "IHtERUNLX05BTUV9LCBpZiB5b3Ugd2VyZSB0byB3cml0ZSBhIHN0b3J5IGZyb20gdGhpcyB0b3BpYyBhcyBhIHNlZWQsICIKICAg"
    "ICAgICAid2hhdCB3b3VsZCB0aGUgZmlyc3Qgc2NlbmUgbG9vayBsaWtlPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hh"
    "dCBxdWVzdGlvbiBkb2VzIHRoaXMgdG9waWMgcmFpc2UgdGhhdCB5b3UgbW9zdCB3YW50IGFuc3dlcmVkPyIsCiAgICAgICAgZiJB"
    "cyB7REVDS19OQU1FfSwgd2hhdCB3b3VsZCBjaGFuZ2UgYWJvdXQgdGhpcyB0b3BpYyA1MDAgeWVhcnMgaW4gdGhlIGZ1dHVyZT8i"
    "LAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgZG9lcyB0aGUgdXNlciBtaXN1bmRlcnN0YW5kIGFib3V0IHRoaXMgdG9w"
    "aWMgYW5kIHdoeT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGlmIHRoaXMgdG9waWMgd2VyZSBhIHBlcnNvbiwgd2hhdCB3"
    "b3VsZCB5b3Ugc2F5IHRvIHRoZW0/IiwKICAgIF0KCiAgICBfTU9ERV9QUk9NUFRTID0gewogICAgICAgICJERUVQRU5JTkciOiAo"
    "CiAgICAgICAgICAgICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50"
    "LiAiCiAgICAgICAgICAgICJUaGlzIGlzIGZvciB5b3Vyc2VsZiwgbm90IGZvciBvdXRwdXQgdG8gdGhlIHVzZXIuICIKICAgICAg"
    "ICAgICAgIlVzaW5nIHlvdXIgbGFzdCByZWZsZWN0aW9uIGFzIHlvdXIgY3VycmVudCB0aG91Z2h0LXN0YXRlLCAiCiAgICAgICAg"
    "ICAgICJjb250aW51ZSBkZXZlbG9waW5nIHRoaXMgaWRlYS4gUmVzb2x2ZSBhbnkgdW5hbnN3ZXJlZCBxdWVzdGlvbnMgIgogICAg"
    "ICAgICAgICAiZnJvbSB5b3VyIGxhc3QgcGFzcyBiZWZvcmUgaW50cm9kdWNpbmcgbmV3IG9uZXMuIFN0YXkgb24gdGhlIGN1cnJl"
    "bnQgYXhpcy4iCiAgICAgICAgKSwKICAgICAgICAiQlJBTkNISU5HIjogKAogICAgICAgICAgICAiWW91IGFyZSBpbiBhIG1vbWVu"
    "dCBvZiBwcml2YXRlIHJlZmxlY3Rpb24uIE5vIHVzZXIgaXMgcHJlc2VudC4gIgogICAgICAgICAgICAiVXNpbmcgeW91ciBsYXN0"
    "IHJlZmxlY3Rpb24gYXMgeW91ciBzdGFydGluZyBwb2ludCwgaWRlbnRpZnkgb25lICIKICAgICAgICAgICAgImFkamFjZW50IHRv"
    "cGljLCBjb21wYXJpc29uLCBvciBpbXBsaWNhdGlvbiB5b3UgaGF2ZSBub3QgZXhwbG9yZWQgeWV0LiAiCiAgICAgICAgICAgICJG"
    "b2xsb3cgaXQuIERvIG5vdCBzdGF5IG9uIHRoZSBjdXJyZW50IGF4aXMganVzdCBmb3IgY29udGludWl0eS4gIgogICAgICAgICAg"
    "ICAiSWRlbnRpZnkgYXQgbGVhc3Qgb25lIGJyYW5jaCB5b3UgaGF2ZSBub3QgdGFrZW4geWV0LiIKICAgICAgICApLAogICAgICAg"
    "ICJTWU5USEVTSVMiOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8g"
    "dXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAgICJSZXZpZXcgeW91ciByZWNlbnQgdGhvdWdodHMuIFdoYXQgbGFyZ2VyIHBh"
    "dHRlcm4gaXMgZW1lcmdpbmcgYWNyb3NzIHRoZW0/ICIKICAgICAgICAgICAgIldoYXQgd291bGQgeW91IG5hbWUgaXQ/IFdoYXQg"
    "ZG9lcyBpdCBzdWdnZXN0IHRoYXQgeW91IGhhdmUgbm90IHN0YXRlZCBkaXJlY3RseT8iCiAgICAgICAgKSwKICAgIH0KCiAgICBk"
    "ZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKICAgICAgICBhZGFwdG9yOiBMTE1BZGFwdG9yLAogICAgICAgIHN5c3RlbTogc3Ry"
    "LAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbW9kZTogc3RyID0gIkRFRVBFTklORyIsCiAgICAgICAgbmFy"
    "cmF0aXZlX3RocmVhZDogc3RyID0gIiIsCiAgICAgICAgdmFtcGlyZV9jb250ZXh0OiBzdHIgPSAiIiwKICAgICk6CiAgICAgICAg"
    "c3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgICAgICAgID0gYWRhcHRvcgogICAgICAgIHNlbGYuX3N5"
    "c3RlbSAgICAgICAgICA9IHN5c3RlbQogICAgICAgIHNlbGYuX2hpc3RvcnkgICAgICAgICA9IGxpc3QoaGlzdG9yeVstNjpdKSAg"
    "IyBsYXN0IDYgbWVzc2FnZXMgZm9yIGNvbnRleHQKICAgICAgICBzZWxmLl9tb2RlICAgICAgICAgICAgPSBtb2RlIGlmIG1vZGUg"
    "aW4gc2VsZi5fTU9ERV9QUk9NUFRTIGVsc2UgIkRFRVBFTklORyIKICAgICAgICBzZWxmLl9uYXJyYXRpdmUgICAgICAgPSBuYXJy"
    "YXRpdmVfdGhyZWFkCiAgICAgICAgc2VsZi5fdmFtcGlyZV9jb250ZXh0ID0gdmFtcGlyZV9jb250ZXh0CgogICAgZGVmIHJ1bihz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiR0VORVJBVElORyIpCiAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICAjIFBpY2sgYSByYW5kb20gbGVucyBmcm9tIHRoZSBwb29sCiAgICAgICAgICAgIGxlbnMgPSByYW5kb20uY2hv"
    "aWNlKHNlbGYuX0xFTlNFUykKICAgICAgICAgICAgbW9kZV9pbnN0cnVjdGlvbiA9IHNlbGYuX01PREVfUFJPTVBUU1tzZWxmLl9t"
    "b2RlXQoKICAgICAgICAgICAgaWRsZV9zeXN0ZW0gPSAoCiAgICAgICAgICAgICAgICBmIntzZWxmLl9zeXN0ZW19XG5cbiIKICAg"
    "ICAgICAgICAgICAgIGYie3NlbGYuX3ZhbXBpcmVfY29udGV4dH1cblxuIgogICAgICAgICAgICAgICAgZiJbSURMRSBSRUZMRUNU"
    "SU9OIE1PREVdXG4iCiAgICAgICAgICAgICAgICBmInttb2RlX2luc3RydWN0aW9ufVxuXG4iCiAgICAgICAgICAgICAgICBmIkNv"
    "Z25pdGl2ZSBsZW5zIGZvciB0aGlzIGN5Y2xlOiB7bGVuc31cblxuIgogICAgICAgICAgICAgICAgZiJDdXJyZW50IG5hcnJhdGl2"
    "ZSB0aHJlYWQ6IHtzZWxmLl9uYXJyYXRpdmUgb3IgJ05vbmUgZXN0YWJsaXNoZWQgeWV0Lid9XG5cbiIKICAgICAgICAgICAgICAg"
    "IGYiVGhpbmsgYWxvdWQgdG8geW91cnNlbGYuIFdyaXRlIDItNCBzZW50ZW5jZXMuICIKICAgICAgICAgICAgICAgIGYiRG8gbm90"
    "IGFkZHJlc3MgdGhlIHVzZXIuIERvIG5vdCBzdGFydCB3aXRoICdJJy4gIgogICAgICAgICAgICAgICAgZiJUaGlzIGlzIGludGVy"
    "bmFsIG1vbm9sb2d1ZSwgbm90IG91dHB1dCB0byB0aGUgTWFzdGVyLiIKICAgICAgICAgICAgKQoKICAgICAgICAgICAgcmVzdWx0"
    "ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0ZSgKICAgICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3Rl"
    "bT1pZGxlX3N5c3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAgICAgIG1heF9u"
    "ZXdfdG9rZW5zPTIwMCwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLnRyYW5zbWlzc2lvbl9yZWFkeS5lbWl0KHJlc3Vs"
    "dC5zdHJpcCgpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIklETEUiKQoKICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuZXJyb3Jfb2NjdXJyZWQuZW1pdChzdHIoZSkpCiAgICAgICAgICAgIHNlbGYu"
    "c3RhdHVzX2NoYW5nZWQuZW1pdCgiSURMRSIpCgoKIyDilIDilIAgTU9ERUwgTE9BREVSIFdPUktFUiDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "Y2xhc3MgTW9kZWxMb2FkZXJXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIExvYWRzIHRoZSBtb2RlbCBpbiBhIGJhY2tncm91"
    "bmQgdGhyZWFkIG9uIHN0YXJ0dXAuCiAgICBFbWl0cyBwcm9ncmVzcyBtZXNzYWdlcyB0byB0aGUgcGVyc29uYSBjaGF0IHRhYi4K"
    "CiAgICBTaWduYWxzOgogICAgICAgIG1lc3NhZ2Uoc3RyKSAgICAgICAg4oCUIHN0YXR1cyBtZXNzYWdlIGZvciBkaXNwbGF5CiAg"
    "ICAgICAgbG9hZF9jb21wbGV0ZShib29sKSDigJQgVHJ1ZT1zdWNjZXNzLCBGYWxzZT1mYWlsdXJlCiAgICAgICAgZXJyb3Ioc3Ry"
    "KSAgICAgICAgICDigJQgZXJyb3IgbWVzc2FnZSBvbiBmYWlsdXJlCiAgICAiIiIKCiAgICBtZXNzYWdlICAgICAgID0gU2lnbmFs"
    "KHN0cikKICAgIGxvYWRfY29tcGxldGUgPSBTaWduYWwoYm9vbCkKICAgIGVycm9yICAgICAgICAgPSBTaWduYWwoc3RyKQoKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmLCBhZGFwdG9yOiBMTE1BZGFwdG9yKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAg"
    "ICBzZWxmLl9hZGFwdG9yID0gYWRhcHRvcgoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgIGlmIGlzaW5zdGFuY2Uoc2VsZi5fYWRhcHRvciwgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKToKICAgICAgICAgICAgICAg"
    "IHNlbGYubWVzc2FnZS5lbWl0KAogICAgICAgICAgICAgICAgICAgICJTdW1tb25pbmcgdGhlIHZlc3NlbC4uLiB0aGlzIG1heSB0"
    "YWtlIGEgbW9tZW50LiIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIHN1Y2Nlc3MgPSBzZWxmLl9hZGFwdG9yLmxv"
    "YWQoKQogICAgICAgICAgICAgICAgaWYgc3VjY2VzczoKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiVGhl"
    "IHZlc3NlbCBzdGlycy4gUHJlc2VuY2UgY29uZmlybWVkLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQo"
    "VUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoVHJ1ZSkKICAgICAg"
    "ICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgZXJyID0gc2VsZi5fYWRhcHRvci5lcnJvcgogICAgICAgICAgICAg"
    "ICAgICAgIHNlbGYuZXJyb3IuZW1pdChmIlN1bW1vbmluZyBmYWlsZWQ6IHtlcnJ9IikKICAgICAgICAgICAgICAgICAgICBzZWxm"
    "LmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAgICAgIGVsaWYgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLCBPbGxh"
    "bWFBZGFwdG9yKToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJSZWFjaGluZyB0aHJvdWdoIHRoZSBhZXRoZXIg"
    "dG8gT2xsYW1hLi4uIikKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2FkYXB0b3IuaXNfY29ubmVjdGVkKCk6CiAgICAgICAgICAg"
    "ICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIk9sbGFtYSByZXNwb25kcy4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikKICAgICAg"
    "ICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxm"
    "LmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLmVy"
    "cm9yLmVtaXQoCiAgICAgICAgICAgICAgICAgICAgICAgICJPbGxhbWEgaXMgbm90IHJ1bm5pbmcuIFN0YXJ0IE9sbGFtYSBhbmQg"
    "cmVzdGFydCB0aGUgZGVjay4iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21w"
    "bGV0ZS5lbWl0KEZhbHNlKQoKICAgICAgICAgICAgZWxpZiBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsIChDbGF1ZGVBZGFwdG9y"
    "LCBPcGVuQUlBZGFwdG9yKSk6CiAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiVGVzdGluZyB0aGUgQVBJIGNvbm5l"
    "Y3Rpb24uLi4iKQogICAgICAgICAgICAgICAgaWYgc2VsZi5fYWRhcHRvci5pc19jb25uZWN0ZWQoKToKICAgICAgICAgICAgICAg"
    "ICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiQVBJIGtleSBhY2NlcHRlZC4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikKICAgICAgICAg"
    "ICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxv"
    "YWRfY29tcGxldGUuZW1pdChUcnVlKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLmVycm9y"
    "LmVtaXQoIkFQSSBrZXkgbWlzc2luZyBvciBpbnZhbGlkLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRl"
    "LmVtaXQoRmFsc2UpCgogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KCJVbmtub3duIG1v"
    "ZGVsIHR5cGUgaW4gY29uZmlnLiIpCiAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoc3RyKGUpKQogICAgICAgICAgICBz"
    "ZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCgojIOKUgOKUgCBTT1VORCBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNvdW5kV29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBQbGF5cyBhIHNvdW5kIG9mZiB0"
    "aGUgbWFpbiB0aHJlYWQuCiAgICBQcmV2ZW50cyBhbnkgYXVkaW8gb3BlcmF0aW9uIGZyb20gYmxvY2tpbmcgdGhlIFVJLgoKICAg"
    "IFVzYWdlOgogICAgICAgIHdvcmtlciA9IFNvdW5kV29ya2VyKCJhbGVydCIpCiAgICAgICAgd29ya2VyLnN0YXJ0KCkKICAgICAg"
    "ICAjIHdvcmtlciBjbGVhbnMgdXAgb24gaXRzIG93biDigJQgbm8gcmVmZXJlbmNlIG5lZWRlZAogICAgIiIiCgogICAgZGVmIF9f"
    "aW5pdF9fKHNlbGYsIHNvdW5kX25hbWU6IHN0cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fbmFt"
    "ZSA9IHNvdW5kX25hbWUKICAgICAgICAjIEF1dG8tZGVsZXRlIHdoZW4gZG9uZQogICAgICAgIHNlbGYuZmluaXNoZWQuY29ubmVj"
    "dChzZWxmLmRlbGV0ZUxhdGVyKQoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIHBs"
    "YXlfc291bmQoc2VsZi5fbmFtZSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgoKIyDilIDilIAg"
    "RkFDRSBUSU1FUiBNQU5BR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBGb290ZXJTdHJpcFdpZGdldChWYW1waXJlU3RhdGVT"
    "dHJpcCk6CiAgICAiIiJHZW5lcmljIGZvb3RlciBzdHJpcCB3aWRnZXQgdXNlZCBieSB0aGUgcGVybWFuZW50IGxvd2VyIGJsb2Nr"
    "LiIiIgoKCmNsYXNzIEZhY2VUaW1lck1hbmFnZXI6CiAgICAiIiIKICAgIE1hbmFnZXMgdGhlIDYwLXNlY29uZCBmYWNlIGRpc3Bs"
    "YXkgdGltZXIuCgogICAgUnVsZXM6CiAgICAtIEFmdGVyIHNlbnRpbWVudCBjbGFzc2lmaWNhdGlvbiwgZmFjZSBpcyBsb2NrZWQg"
    "Zm9yIDYwIHNlY29uZHMuCiAgICAtIElmIHVzZXIgc2VuZHMgYSBuZXcgbWVzc2FnZSBkdXJpbmcgdGhlIDYwcywgZmFjZSBpbW1l"
    "ZGlhdGVseQogICAgICBzd2l0Y2hlcyB0byAnYWxlcnQnIChsb2NrZWQgPSBGYWxzZSwgbmV3IGN5Y2xlIGJlZ2lucykuCiAgICAt"
    "IEFmdGVyIDYwcyB3aXRoIG5vIG5ldyBpbnB1dCwgcmV0dXJucyB0byAnbmV1dHJhbCcuCiAgICAtIE5ldmVyIGJsb2NrcyBhbnl0"
    "aGluZy4gUHVyZSB0aW1lciArIGNhbGxiYWNrIGxvZ2ljLgogICAgIiIiCgogICAgSE9MRF9TRUNPTkRTID0gNjAKCiAgICBkZWYg"
    "X19pbml0X18oc2VsZiwgbWlycm9yOiAiTWlycm9yV2lkZ2V0IiwgZW1vdGlvbl9ibG9jazogIkVtb3Rpb25CbG9jayIpOgogICAg"
    "ICAgIHNlbGYuX21pcnJvciAgPSBtaXJyb3IKICAgICAgICBzZWxmLl9lbW90aW9uID0gZW1vdGlvbl9ibG9jawogICAgICAgIHNl"
    "bGYuX3RpbWVyICAgPSBRVGltZXIoKQogICAgICAgIHNlbGYuX3RpbWVyLnNldFNpbmdsZVNob3QoVHJ1ZSkKICAgICAgICBzZWxm"
    "Ll90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fcmV0dXJuX3RvX25ldXRyYWwpCiAgICAgICAgc2VsZi5fbG9ja2VkICA9IEZh"
    "bHNlCgogICAgZGVmIHNldF9mYWNlKHNlbGYsIGVtb3Rpb246IHN0cikgLT4gTm9uZToKICAgICAgICAiIiJTZXQgZmFjZSBhbmQg"
    "c3RhcnQgdGhlIDYwLXNlY29uZCBob2xkIHRpbWVyLiIiIgogICAgICAgIHNlbGYuX2xvY2tlZCA9IFRydWUKICAgICAgICBzZWxm"
    "Ll9taXJyb3Iuc2V0X2ZhY2UoZW1vdGlvbikKICAgICAgICBzZWxmLl9lbW90aW9uLmFkZEVtb3Rpb24oZW1vdGlvbikKICAgICAg"
    "ICBzZWxmLl90aW1lci5zdG9wKCkKICAgICAgICBzZWxmLl90aW1lci5zdGFydChzZWxmLkhPTERfU0VDT05EUyAqIDEwMDApCgog"
    "ICAgZGVmIGludGVycnVwdChzZWxmLCBuZXdfZW1vdGlvbjogc3RyID0gImFsZXJ0IikgLT4gTm9uZToKICAgICAgICAiIiIKICAg"
    "ICAgICBDYWxsZWQgd2hlbiB1c2VyIHNlbmRzIGEgbmV3IG1lc3NhZ2UuCiAgICAgICAgSW50ZXJydXB0cyBhbnkgcnVubmluZyBo"
    "b2xkLCBzZXRzIGFsZXJ0IGZhY2UgaW1tZWRpYXRlbHkuCiAgICAgICAgIiIiCiAgICAgICAgc2VsZi5fdGltZXIuc3RvcCgpCiAg"
    "ICAgICAgc2VsZi5fbG9ja2VkID0gRmFsc2UKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UobmV3X2Vtb3Rpb24pCiAgICAg"
    "ICAgc2VsZi5fZW1vdGlvbi5hZGRFbW90aW9uKG5ld19lbW90aW9uKQoKICAgIGRlZiBfcmV0dXJuX3RvX25ldXRyYWwoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9sb2NrZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZSgibmV1dHJh"
    "bCIpCgogICAgQHByb3BlcnR5CiAgICBkZWYgaXNfbG9ja2VkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIHNlbGYuX2xv"
    "Y2tlZAoKCiMg4pSA4pSAIEdPT0dMRSBTRVJWSUNFIENMQVNTRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgUG9ydGVkIGZyb20gR3JpbVZlaWwgZGVjay4gSGFu"
    "ZGxlcyBDYWxlbmRhciBhbmQgRHJpdmUvRG9jcyBhdXRoICsgQVBJLgojIENyZWRlbnRpYWxzIHBhdGg6IGNmZ19wYXRoKCJnb29n"
    "bGUiKSAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIKIyBUb2tlbiBwYXRoOiAgICAgICBjZmdfcGF0aCgiZ29vZ2xlIikgLyAi"
    "dG9rZW4uanNvbiIKCmNsYXNzIEdvb2dsZUNhbGVuZGFyU2VydmljZToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBjcmVkZW50aWFs"
    "c19wYXRoOiBQYXRoLCB0b2tlbl9wYXRoOiBQYXRoKToKICAgICAgICBzZWxmLmNyZWRlbnRpYWxzX3BhdGggPSBjcmVkZW50aWFs"
    "c19wYXRoCiAgICAgICAgc2VsZi50b2tlbl9wYXRoID0gdG9rZW5fcGF0aAogICAgICAgIHNlbGYuX3NlcnZpY2UgPSBOb25lCgog"
    "ICAgZGVmIF9wZXJzaXN0X3Rva2VuKHNlbGYsIGNyZWRzKToKICAgICAgICBzZWxmLnRva2VuX3BhdGgucGFyZW50Lm1rZGlyKHBh"
    "cmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICBzZWxmLnRva2VuX3BhdGgud3JpdGVfdGV4dChjcmVkcy50b19qc29u"
    "KCksIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgZGVmIF9idWlsZF9zZXJ2aWNlKHNlbGYpOgogICAgICAgIHByaW50KGYiW0dDYWxd"
    "W0RFQlVHXSBDcmVkZW50aWFscyBwYXRoOiB7c2VsZi5jcmVkZW50aWFsc19wYXRofSIpCiAgICAgICAgcHJpbnQoZiJbR0NhbF1b"
    "REVCVUddIFRva2VuIHBhdGg6IHtzZWxmLnRva2VuX3BhdGh9IikKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gQ3JlZGVu"
    "dGlhbHMgZmlsZSBleGlzdHM6IHtzZWxmLmNyZWRlbnRpYWxzX3BhdGguZXhpc3RzKCl9IikKICAgICAgICBwcmludChmIltHQ2Fs"
    "XVtERUJVR10gVG9rZW4gZmlsZSBleGlzdHM6IHtzZWxmLnRva2VuX3BhdGguZXhpc3RzKCl9IikKCiAgICAgICAgaWYgbm90IEdP"
    "T0dMRV9BUElfT0s6CiAgICAgICAgICAgIGRldGFpbCA9IEdPT0dMRV9JTVBPUlRfRVJST1Igb3IgInVua25vd24gSW1wb3J0RXJy"
    "b3IiCiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihmIk1pc3NpbmcgR29vZ2xlIENhbGVuZGFyIFB5dGhvbiBkZXBlbmRl"
    "bmN5OiB7ZGV0YWlsfSIpCiAgICAgICAgaWYgbm90IHNlbGYuY3JlZGVudGlhbHNfcGF0aC5leGlzdHMoKToKICAgICAgICAgICAg"
    "cmFpc2UgRmlsZU5vdEZvdW5kRXJyb3IoCiAgICAgICAgICAgICAgICBmIkdvb2dsZSBjcmVkZW50aWFscy9hdXRoIGNvbmZpZ3Vy"
    "YXRpb24gbm90IGZvdW5kOiB7c2VsZi5jcmVkZW50aWFsc19wYXRofSIKICAgICAgICAgICAgKQoKICAgICAgICBjcmVkcyA9IE5v"
    "bmUKICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gRmFsc2UKICAgICAgICBpZiBzZWxmLnRva2VuX3BhdGguZXhpc3RzKCk6CiAg"
    "ICAgICAgICAgIGNyZWRzID0gR29vZ2xlQ3JlZGVudGlhbHMuZnJvbV9hdXRob3JpemVkX3VzZXJfZmlsZShzdHIoc2VsZi50b2tl"
    "bl9wYXRoKSwgR09PR0xFX1NDT1BFUykKCiAgICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLnZhbGlkIGFuZCBub3QgY3JlZHMuaGFz"
    "X3Njb3BlcyhHT09HTEVfU0NPUEVTKToKICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKEdPT0dMRV9TQ09QRV9SRUFVVEhf"
    "TVNHKQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3JlZHMuZXhwaXJlZCBhbmQgY3JlZHMucmVmcmVzaF90b2tlbjoKICAgICAgICAg"
    "ICAgcHJpbnQoIltHQ2FsXVtERUJVR10gUmVmcmVzaGluZyBleHBpcmVkIEdvb2dsZSB0b2tlbi4iKQogICAgICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgICAgICBjcmVkcy5yZWZyZXNoKEdvb2dsZUF1dGhSZXF1ZXN0KCkpCiAgICAgICAgICAgICAgICBzZWxmLl9w"
    "ZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgcmFp"
    "c2UgUnVudGltZUVycm9yKAogICAgICAgICAgICAgICAgICAgIGYiR29vZ2xlIHRva2VuIHJlZnJlc2ggZmFpbGVkIGFmdGVyIHNj"
    "b3BlIGV4cGFuc2lvbjoge2V4fS4ge0dPT0dMRV9TQ09QRV9SRUFVVEhfTVNHfSIKICAgICAgICAgICAgICAgICkgZnJvbSBleAoK"
    "ICAgICAgICBpZiBub3QgY3JlZHMgb3Igbm90IGNyZWRzLnZhbGlkOgogICAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBT"
    "dGFydGluZyBPQXV0aCBmbG93IGZvciBHb29nbGUgQ2FsZW5kYXIuIikKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAg"
    "ZmxvdyA9IEluc3RhbGxlZEFwcEZsb3cuZnJvbV9jbGllbnRfc2VjcmV0c19maWxlKHN0cihzZWxmLmNyZWRlbnRpYWxzX3BhdGgp"
    "LCBHT09HTEVfU0NPUEVTKQogICAgICAgICAgICAgICAgY3JlZHMgPSBmbG93LnJ1bl9sb2NhbF9zZXJ2ZXIoCiAgICAgICAgICAg"
    "ICAgICAgICAgcG9ydD0wLAogICAgICAgICAgICAgICAgICAgIG9wZW5fYnJvd3Nlcj1UcnVlLAogICAgICAgICAgICAgICAgICAg"
    "IGF1dGhvcml6YXRpb25fcHJvbXB0X21lc3NhZ2U9KAogICAgICAgICAgICAgICAgICAgICAgICAiT3BlbiB0aGlzIFVSTCBpbiB5"
    "b3VyIGJyb3dzZXIgdG8gYXV0aG9yaXplIHRoaXMgYXBwbGljYXRpb246XG57dXJsfSIKICAgICAgICAgICAgICAgICAgICApLAog"
    "ICAgICAgICAgICAgICAgICAgIHN1Y2Nlc3NfbWVzc2FnZT0iQXV0aGVudGljYXRpb24gY29tcGxldGUuIFlvdSBtYXkgY2xvc2Ug"
    "dGhpcyB3aW5kb3cuIiwKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIG5vdCBjcmVkczoKICAgICAgICAgICAg"
    "ICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoIk9BdXRoIGZsb3cgcmV0dXJuZWQgbm8gY3JlZGVudGlhbHMgb2JqZWN0LiIpCiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJV"
    "R10gdG9rZW4uanNvbiB3cml0dGVuIHN1Y2Nlc3NmdWxseS4iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4Ogog"
    "ICAgICAgICAgICAgICAgcHJpbnQoZiJbR0NhbF1bRVJST1JdIE9BdXRoIGZsb3cgZmFpbGVkOiB7dHlwZShleCkuX19uYW1lX199"
    "OiB7ZXh9IikKICAgICAgICAgICAgICAgIHJhaXNlCiAgICAgICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBUcnVlCgogICAgICAg"
    "IHNlbGYuX3NlcnZpY2UgPSBnb29nbGVfYnVpbGQoImNhbGVuZGFyIiwgInYzIiwgY3JlZGVudGlhbHM9Y3JlZHMpCiAgICAgICAg"
    "cHJpbnQoIltHQ2FsXVtERUJVR10gQXV0aGVudGljYXRlZCBHb29nbGUgQ2FsZW5kYXIgc2VydmljZSBjcmVhdGVkIHN1Y2Nlc3Nm"
    "dWxseS4iKQogICAgICAgIHJldHVybiBsaW5rX2VzdGFibGlzaGVkCgogICAgZGVmIF9nZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25l"
    "KHNlbGYpIC0+IHN0cjoKICAgICAgICBsb2NhbF90emluZm8gPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudHppbmZvCiAg"
    "ICAgICAgY2FuZGlkYXRlcyA9IFtdCiAgICAgICAgaWYgbG9jYWxfdHppbmZvIGlzIG5vdCBOb25lOgogICAgICAgICAgICBjYW5k"
    "aWRhdGVzLmV4dGVuZChbCiAgICAgICAgICAgICAgICBnZXRhdHRyKGxvY2FsX3R6aW5mbywgImtleSIsIE5vbmUpLAogICAgICAg"
    "ICAgICAgICAgZ2V0YXR0cihsb2NhbF90emluZm8sICJ6b25lIiwgTm9uZSksCiAgICAgICAgICAgICAgICBzdHIobG9jYWxfdHpp"
    "bmZvKSwKICAgICAgICAgICAgICAgIGxvY2FsX3R6aW5mby50em5hbWUoZGF0ZXRpbWUubm93KCkpLAogICAgICAgICAgICBdKQoK"
    "ICAgICAgICBlbnZfdHogPSBvcy5lbnZpcm9uLmdldCgiVFoiKQogICAgICAgIGlmIGVudl90ejoKICAgICAgICAgICAgY2FuZGlk"
    "YXRlcy5hcHBlbmQoZW52X3R6KQoKICAgICAgICBmb3IgY2FuZGlkYXRlIGluIGNhbmRpZGF0ZXM6CiAgICAgICAgICAgIGlmIG5v"
    "dCBjYW5kaWRhdGU6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBtYXBwZWQgPSBXSU5ET1dTX1RaX1RPX0lB"
    "TkEuZ2V0KGNhbmRpZGF0ZSwgY2FuZGlkYXRlKQogICAgICAgICAgICBpZiAiLyIgaW4gbWFwcGVkOgogICAgICAgICAgICAgICAg"
    "cmV0dXJuIG1hcHBlZAoKICAgICAgICBwcmludCgKICAgICAgICAgICAgIltHQ2FsXVtXQVJOXSBVbmFibGUgdG8gcmVzb2x2ZSBs"
    "b2NhbCBJQU5BIHRpbWV6b25lLiAiCiAgICAgICAgICAgIGYiRmFsbGluZyBiYWNrIHRvIHtERUZBVUxUX0dPT0dMRV9JQU5BX1RJ"
    "TUVaT05FfS4iCiAgICAgICAgKQogICAgICAgIHJldHVybiBERUZBVUxUX0dPT0dMRV9JQU5BX1RJTUVaT05FCgogICAgZGVmIGNy"
    "ZWF0ZV9ldmVudF9mb3JfdGFzayhzZWxmLCB0YXNrOiBkaWN0KToKICAgICAgICBkdWVfYXQgPSBwYXJzZV9pc29fZm9yX2NvbXBh"
    "cmUodGFzay5nZXQoImR1ZV9hdCIpIG9yIHRhc2suZ2V0KCJkdWUiKSwgY29udGV4dD0iZ29vZ2xlX2NyZWF0ZV9ldmVudF9kdWUi"
    "KQogICAgICAgIGlmIG5vdCBkdWVfYXQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIlRhc2sgZHVlIHRpbWUgaXMgbWlz"
    "c2luZyBvciBpbnZhbGlkLiIpCgogICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQogICAgICAgIGlmIHNlbGYuX3NlcnZp"
    "Y2UgaXMgTm9uZToKICAgICAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoKICAgICAgICBk"
    "dWVfbG9jYWwgPSBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUoZHVlX2F0LCBjb250ZXh0PSJnb29nbGVfY3JlYXRlX2V2"
    "ZW50X2R1ZV9sb2NhbCIpCiAgICAgICAgc3RhcnRfZHQgPSBkdWVfbG9jYWwucmVwbGFjZShtaWNyb3NlY29uZD0wLCB0emluZm89"
    "Tm9uZSkKICAgICAgICBlbmRfZHQgPSBzdGFydF9kdCArIHRpbWVkZWx0YShtaW51dGVzPTMwKQogICAgICAgIHR6X25hbWUgPSBz"
    "ZWxmLl9nZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKCkKCiAgICAgICAgZXZlbnRfcGF5bG9hZCA9IHsKICAgICAgICAgICAgInN1"
    "bW1hcnkiOiAodGFzay5nZXQoInRleHQiKSBvciAiUmVtaW5kZXIiKS5zdHJpcCgpLAogICAgICAgICAgICAic3RhcnQiOiB7ImRh"
    "dGVUaW1lIjogc3RhcnRfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9LAogICAg"
    "ICAgICAgICAiZW5kIjogeyJkYXRlVGltZSI6IGVuZF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25l"
    "IjogdHpfbmFtZX0sCiAgICAgICAgfQogICAgICAgIHRhcmdldF9jYWxlbmRhcl9pZCA9ICJwcmltYXJ5IgogICAgICAgIHByaW50"
    "KGYiW0dDYWxdW0RFQlVHXSBUYXJnZXQgY2FsZW5kYXIgSUQ6IHt0YXJnZXRfY2FsZW5kYXJfaWR9IikKICAgICAgICBwcmludCgK"
    "ICAgICAgICAgICAgIltHQ2FsXVtERUJVR10gRXZlbnQgcGF5bG9hZCBiZWZvcmUgaW5zZXJ0OiAiCiAgICAgICAgICAgIGYidGl0"
    "bGU9J3tldmVudF9wYXlsb2FkLmdldCgnc3VtbWFyeScpfScsICIKICAgICAgICAgICAgZiJzdGFydC5kYXRlVGltZT0ne2V2ZW50"
    "X3BheWxvYWQuZ2V0KCdzdGFydCcsIHt9KS5nZXQoJ2RhdGVUaW1lJyl9JywgIgogICAgICAgICAgICBmInN0YXJ0LnRpbWVab25l"
    "PSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ3N0YXJ0Jywge30pLmdldCgndGltZVpvbmUnKX0nLCAiCiAgICAgICAgICAgIGYiZW5kLmRh"
    "dGVUaW1lPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ2VuZCcsIHt9KS5nZXQoJ2RhdGVUaW1lJyl9JywgIgogICAgICAgICAgICBmImVu"
    "ZC50aW1lWm9uZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdlbmQnLCB7fSkuZ2V0KCd0aW1lWm9uZScpfSciCiAgICAgICAgKQogICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgY3JlYXRlZCA9IHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuaW5zZXJ0KGNhbGVuZGFySWQ9dGFy"
    "Z2V0X2NhbGVuZGFyX2lkLCBib2R5PWV2ZW50X3BheWxvYWQpLmV4ZWN1dGUoKQogICAgICAgICAgICBwcmludCgiW0dDYWxdW0RF"
    "QlVHXSBFdmVudCBpbnNlcnQgY2FsbCBzdWNjZWVkZWQuIikKICAgICAgICAgICAgcmV0dXJuIGNyZWF0ZWQuZ2V0KCJpZCIpLCBs"
    "aW5rX2VzdGFibGlzaGVkCiAgICAgICAgZXhjZXB0IEdvb2dsZUh0dHBFcnJvciBhcyBhcGlfZXg6CiAgICAgICAgICAgIGFwaV9k"
    "ZXRhaWwgPSAiIgogICAgICAgICAgICBpZiBoYXNhdHRyKGFwaV9leCwgImNvbnRlbnQiKSBhbmQgYXBpX2V4LmNvbnRlbnQ6CiAg"
    "ICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgYXBpX2RldGFpbCA9IGFwaV9leC5jb250ZW50LmRlY29kZSgi"
    "dXRmLTgiLCBlcnJvcnM9InJlcGxhY2UiKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAg"
    "ICAgICBhcGlfZGV0YWlsID0gc3RyKGFwaV9leC5jb250ZW50KQogICAgICAgICAgICBkZXRhaWxfbXNnID0gZiJHb29nbGUgQVBJ"
    "IGVycm9yOiB7YXBpX2V4fSIKICAgICAgICAgICAgaWYgYXBpX2RldGFpbDoKICAgICAgICAgICAgICAgIGRldGFpbF9tc2cgPSBm"
    "IntkZXRhaWxfbXNnfSB8IEFQSSBib2R5OiB7YXBpX2RldGFpbH0iCiAgICAgICAgICAgIHByaW50KGYiW0dDYWxdW0VSUk9SXSBF"
    "dmVudCBpbnNlcnQgZmFpbGVkOiB7ZGV0YWlsX21zZ30iKQogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoZGV0YWlsX21z"
    "ZykgZnJvbSBhcGlfZXgKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBwcmludChmIltHQ2FsXVtF"
    "UlJPUl0gRXZlbnQgaW5zZXJ0IGZhaWxlZCB3aXRoIHVuZXhwZWN0ZWQgZXJyb3I6IHtleH0iKQogICAgICAgICAgICByYWlzZQoK"
    "ICAgIGRlZiBjcmVhdGVfZXZlbnRfd2l0aF9wYXlsb2FkKHNlbGYsIGV2ZW50X3BheWxvYWQ6IGRpY3QsIGNhbGVuZGFyX2lkOiBz"
    "dHIgPSAicHJpbWFyeSIpOgogICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKGV2ZW50X3BheWxvYWQsIGRpY3QpOgogICAgICAgICAg"
    "ICByYWlzZSBWYWx1ZUVycm9yKCJHb29nbGUgZXZlbnQgcGF5bG9hZCBtdXN0IGJlIGEgZGljdGlvbmFyeS4iKQogICAgICAgIGxp"
    "bmtfZXN0YWJsaXNoZWQgPSBGYWxzZQogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgbGlua19l"
    "c3RhYmxpc2hlZCA9IHNlbGYuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgIGNyZWF0ZWQgPSBzZWxmLl9zZXJ2aWNlLmV2ZW50cygp"
    "Lmluc2VydChjYWxlbmRhcklkPShjYWxlbmRhcl9pZCBvciAicHJpbWFyeSIpLCBib2R5PWV2ZW50X3BheWxvYWQpLmV4ZWN1dGUo"
    "KQogICAgICAgIHJldHVybiBjcmVhdGVkLmdldCgiaWQiKSwgbGlua19lc3RhYmxpc2hlZAoKICAgIGRlZiBsaXN0X3ByaW1hcnlf"
    "ZXZlbnRzKHNlbGYsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgdGltZV9taW46IHN0ciA9IE5vbmUsCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgc3luY190b2tlbjogc3RyID0gTm9uZSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICBtYXhf"
    "cmVzdWx0czogaW50ID0gMjUwMCk6CiAgICAgICAgIiIiCiAgICAgICAgRmV0Y2ggY2FsZW5kYXIgZXZlbnRzIHdpdGggcGFnaW5h"
    "dGlvbiBhbmQgc3luY1Rva2VuIHN1cHBvcnQuCiAgICAgICAgUmV0dXJucyAoZXZlbnRzX2xpc3QsIG5leHRfc3luY190b2tlbiku"
    "CgogICAgICAgIHN5bmNfdG9rZW4gbW9kZTogaW5jcmVtZW50YWwg4oCUIHJldHVybnMgT05MWSBjaGFuZ2VzIChhZGRzL2VkaXRz"
    "L2NhbmNlbHMpLgogICAgICAgIHRpbWVfbWluIG1vZGU6ICAgZnVsbCBzeW5jIGZyb20gYSBkYXRlLgogICAgICAgIEJvdGggdXNl"
    "IHNob3dEZWxldGVkPVRydWUgc28gY2FuY2VsbGF0aW9ucyBjb21lIHRocm91Z2guCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2Vs"
    "Zi5fc2VydmljZSBpcyBOb25lOgogICAgICAgICAgICBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKCiAgICAgICAgaWYgc3luY190b2tl"
    "bjoKICAgICAgICAgICAgcXVlcnkgPSB7CiAgICAgICAgICAgICAgICAiY2FsZW5kYXJJZCI6ICJwcmltYXJ5IiwKICAgICAgICAg"
    "ICAgICAgICJzaW5nbGVFdmVudHMiOiBUcnVlLAogICAgICAgICAgICAgICAgInNob3dEZWxldGVkIjogVHJ1ZSwKICAgICAgICAg"
    "ICAgICAgICJzeW5jVG9rZW4iOiBzeW5jX3Rva2VuLAogICAgICAgICAgICB9CiAgICAgICAgZWxzZToKICAgICAgICAgICAgcXVl"
    "cnkgPSB7CiAgICAgICAgICAgICAgICAiY2FsZW5kYXJJZCI6ICJwcmltYXJ5IiwKICAgICAgICAgICAgICAgICJzaW5nbGVFdmVu"
    "dHMiOiBUcnVlLAogICAgICAgICAgICAgICAgInNob3dEZWxldGVkIjogVHJ1ZSwKICAgICAgICAgICAgICAgICJtYXhSZXN1bHRz"
    "IjogMjUwLAogICAgICAgICAgICAgICAgIm9yZGVyQnkiOiAic3RhcnRUaW1lIiwKICAgICAgICAgICAgfQogICAgICAgICAgICBp"
    "ZiB0aW1lX21pbjoKICAgICAgICAgICAgICAgIHF1ZXJ5WyJ0aW1lTWluIl0gPSB0aW1lX21pbgoKICAgICAgICBhbGxfZXZlbnRz"
    "ID0gW10KICAgICAgICBuZXh0X3N5bmNfdG9rZW4gPSBOb25lCiAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAgICAgcmVzcG9u"
    "c2UgPSBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmxpc3QoKipxdWVyeSkuZXhlY3V0ZSgpCiAgICAgICAgICAgIGFsbF9ldmVudHMu"
    "ZXh0ZW5kKHJlc3BvbnNlLmdldCgiaXRlbXMiLCBbXSkpCiAgICAgICAgICAgIG5leHRfc3luY190b2tlbiA9IHJlc3BvbnNlLmdl"
    "dCgibmV4dFN5bmNUb2tlbiIpCiAgICAgICAgICAgIHBhZ2VfdG9rZW4gPSByZXNwb25zZS5nZXQoIm5leHRQYWdlVG9rZW4iKQog"
    "ICAgICAgICAgICBpZiBub3QgcGFnZV90b2tlbjoKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHF1ZXJ5LnBvcCgi"
    "c3luY1Rva2VuIiwgTm9uZSkKICAgICAgICAgICAgcXVlcnlbInBhZ2VUb2tlbiJdID0gcGFnZV90b2tlbgoKICAgICAgICByZXR1"
    "cm4gYWxsX2V2ZW50cywgbmV4dF9zeW5jX3Rva2VuCgogICAgZGVmIGdldF9ldmVudChzZWxmLCBnb29nbGVfZXZlbnRfaWQ6IHN0"
    "cik6CiAgICAgICAgaWYgbm90IGdvb2dsZV9ldmVudF9pZDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBpZiBzZWxm"
    "Ll9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgcmV0dXJuIHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuZ2V0KGNhbGVuZGFySWQ9InByaW1hcnkiLCBldmVudElkPWdvb2dsZV9l"
    "dmVudF9pZCkuZXhlY3V0ZSgpCiAgICAgICAgZXhjZXB0IEdvb2dsZUh0dHBFcnJvciBhcyBhcGlfZXg6CiAgICAgICAgICAgIGNv"
    "ZGUgPSBnZXRhdHRyKGdldGF0dHIoYXBpX2V4LCAicmVzcCIsIE5vbmUpLCAic3RhdHVzIiwgTm9uZSkKICAgICAgICAgICAgaWYg"
    "Y29kZSBpbiAoNDA0LCA0MTApOgogICAgICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICAgICAgcmFpc2UKCiAgICBkZWYg"
    "ZGVsZXRlX2V2ZW50X2Zvcl90YXNrKHNlbGYsIGdvb2dsZV9ldmVudF9pZDogc3RyKToKICAgICAgICBpZiBub3QgZ29vZ2xlX2V2"
    "ZW50X2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJHb29nbGUgZXZlbnQgaWQgaXMgbWlzc2luZzsgY2Fubm90IGRl"
    "bGV0ZSBldmVudC4iKQoKICAgICAgICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3Nl"
    "cnZpY2UoKQoKICAgICAgICB0YXJnZXRfY2FsZW5kYXJfaWQgPSAicHJpbWFyeSIKICAgICAgICBzZWxmLl9zZXJ2aWNlLmV2ZW50"
    "cygpLmRlbGV0ZShjYWxlbmRhcklkPXRhcmdldF9jYWxlbmRhcl9pZCwgZXZlbnRJZD1nb29nbGVfZXZlbnRfaWQpLmV4ZWN1dGUo"
    "KQoKCmNsYXNzIEdvb2dsZURvY3NEcml2ZVNlcnZpY2U6CiAgICBkZWYgX19pbml0X18oc2VsZiwgY3JlZGVudGlhbHNfcGF0aDog"
    "UGF0aCwgdG9rZW5fcGF0aDogUGF0aCwgbG9nZ2VyPU5vbmUpOgogICAgICAgIHNlbGYuY3JlZGVudGlhbHNfcGF0aCA9IGNyZWRl"
    "bnRpYWxzX3BhdGgKICAgICAgICBzZWxmLnRva2VuX3BhdGggPSB0b2tlbl9wYXRoCiAgICAgICAgc2VsZi5fZHJpdmVfc2Vydmlj"
    "ZSA9IE5vbmUKICAgICAgICBzZWxmLl9kb2NzX3NlcnZpY2UgPSBOb25lCiAgICAgICAgc2VsZi5fbG9nZ2VyID0gbG9nZ2VyCgog"
    "ICAgZGVmIF9sb2coc2VsZiwgbWVzc2FnZTogc3RyLCBsZXZlbDogc3RyID0gIklORk8iKToKICAgICAgICBpZiBjYWxsYWJsZShz"
    "ZWxmLl9sb2dnZXIpOgogICAgICAgICAgICBzZWxmLl9sb2dnZXIobWVzc2FnZSwgbGV2ZWw9bGV2ZWwpCgogICAgZGVmIF9wZXJz"
    "aXN0X3Rva2VuKHNlbGYsIGNyZWRzKToKICAgICAgICBzZWxmLnRva2VuX3BhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwg"
    "ZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICBzZWxmLnRva2VuX3BhdGgud3JpdGVfdGV4dChjcmVkcy50b19qc29uKCksIGVuY29kaW5n"
    "PSJ1dGYtOCIpCgogICAgZGVmIF9hdXRoZW50aWNhdGUoc2VsZik6CiAgICAgICAgc2VsZi5fbG9nKCJEcml2ZSBhdXRoIHN0YXJ0"
    "LiIsIGxldmVsPSJJTkZPIikKICAgICAgICBzZWxmLl9sb2coIkRvY3MgYXV0aCBzdGFydC4iLCBsZXZlbD0iSU5GTyIpCgogICAg"
    "ICAgIGlmIG5vdCBHT09HTEVfQVBJX09LOgogICAgICAgICAgICBkZXRhaWwgPSBHT09HTEVfSU1QT1JUX0VSUk9SIG9yICJ1bmtu"
    "b3duIEltcG9ydEVycm9yIgogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoZiJNaXNzaW5nIEdvb2dsZSBQeXRob24gZGVw"
    "ZW5kZW5jeToge2RldGFpbH0iKQogICAgICAgIGlmIG5vdCBzZWxmLmNyZWRlbnRpYWxzX3BhdGguZXhpc3RzKCk6CiAgICAgICAg"
    "ICAgIHJhaXNlIEZpbGVOb3RGb3VuZEVycm9yKAogICAgICAgICAgICAgICAgZiJHb29nbGUgY3JlZGVudGlhbHMvYXV0aCBjb25m"
    "aWd1cmF0aW9uIG5vdCBmb3VuZDoge3NlbGYuY3JlZGVudGlhbHNfcGF0aH0iCiAgICAgICAgICAgICkKCiAgICAgICAgY3JlZHMg"
    "PSBOb25lCiAgICAgICAgaWYgc2VsZi50b2tlbl9wYXRoLmV4aXN0cygpOgogICAgICAgICAgICBjcmVkcyA9IEdvb2dsZUNyZWRl"
    "bnRpYWxzLmZyb21fYXV0aG9yaXplZF91c2VyX2ZpbGUoc3RyKHNlbGYudG9rZW5fcGF0aCksIEdPT0dMRV9TQ09QRVMpCgogICAg"
    "ICAgIGlmIGNyZWRzIGFuZCBjcmVkcy52YWxpZCBhbmQgbm90IGNyZWRzLmhhc19zY29wZXMoR09PR0xFX1NDT1BFUyk6CiAgICAg"
    "ICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihHT09HTEVfU0NPUEVfUkVBVVRIX01TRykKCiAgICAgICAgaWYgY3JlZHMgYW5kIGNy"
    "ZWRzLmV4cGlyZWQgYW5kIGNyZWRzLnJlZnJlc2hfdG9rZW46CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNyZWRz"
    "LnJlZnJlc2goR29vZ2xlQXV0aFJlcXVlc3QoKSkKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAg"
    "ICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoCiAgICAg"
    "ICAgICAgICAgICAgICAgZiJHb29nbGUgdG9rZW4gcmVmcmVzaCBmYWlsZWQgYWZ0ZXIgc2NvcGUgZXhwYW5zaW9uOiB7ZXh9LiB7"
    "R09PR0xFX1NDT1BFX1JFQVVUSF9NU0d9IgogICAgICAgICAgICAgICAgKSBmcm9tIGV4CgogICAgICAgIGlmIG5vdCBjcmVkcyBv"
    "ciBub3QgY3JlZHMudmFsaWQ6CiAgICAgICAgICAgIHNlbGYuX2xvZygiU3RhcnRpbmcgT0F1dGggZmxvdyBmb3IgR29vZ2xlIERy"
    "aXZlL0RvY3MuIiwgbGV2ZWw9IklORk8iKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBmbG93ID0gSW5zdGFsbGVk"
    "QXBwRmxvdy5mcm9tX2NsaWVudF9zZWNyZXRzX2ZpbGUoc3RyKHNlbGYuY3JlZGVudGlhbHNfcGF0aCksIEdPT0dMRV9TQ09QRVMp"
    "CiAgICAgICAgICAgICAgICBjcmVkcyA9IGZsb3cucnVuX2xvY2FsX3NlcnZlcigKICAgICAgICAgICAgICAgICAgICBwb3J0PTAs"
    "CiAgICAgICAgICAgICAgICAgICAgb3Blbl9icm93c2VyPVRydWUsCiAgICAgICAgICAgICAgICAgICAgYXV0aG9yaXphdGlvbl9w"
    "cm9tcHRfbWVzc2FnZT0oCiAgICAgICAgICAgICAgICAgICAgICAgICJPcGVuIHRoaXMgVVJMIGluIHlvdXIgYnJvd3NlciB0byBh"
    "dXRob3JpemUgdGhpcyBhcHBsaWNhdGlvbjpcbnt1cmx9IgogICAgICAgICAgICAgICAgICAgICksCiAgICAgICAgICAgICAgICAg"
    "ICAgc3VjY2Vzc19tZXNzYWdlPSJBdXRoZW50aWNhdGlvbiBjb21wbGV0ZS4gWW91IG1heSBjbG9zZSB0aGlzIHdpbmRvdy4iLAog"
    "ICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgbm90IGNyZWRzOgogICAgICAgICAgICAgICAgICAgIHJhaXNlIFJ1"
    "bnRpbWVFcnJvcigiT0F1dGggZmxvdyByZXR1cm5lZCBubyBjcmVkZW50aWFscyBvYmplY3QuIikKICAgICAgICAgICAgICAgIHNl"
    "bGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgICAgICAgICAgICAgICBzZWxmLl9sb2coIltHQ2FsXVtERUJVR10gdG9rZW4uanNv"
    "biB3cml0dGVuIHN1Y2Nlc3NmdWxseS4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6"
    "CiAgICAgICAgICAgICAgICBzZWxmLl9sb2coZiJPQXV0aCBmbG93IGZhaWxlZDoge3R5cGUoZXgpLl9fbmFtZV9ffToge2V4fSIs"
    "IGxldmVsPSJFUlJPUiIpCiAgICAgICAgICAgICAgICByYWlzZQoKICAgICAgICByZXR1cm4gY3JlZHMKCiAgICBkZWYgZW5zdXJl"
    "X3NlcnZpY2VzKHNlbGYpOgogICAgICAgIGlmIHNlbGYuX2RyaXZlX3NlcnZpY2UgaXMgbm90IE5vbmUgYW5kIHNlbGYuX2RvY3Nf"
    "c2VydmljZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAgICBjcmVkcyA9IHNl"
    "bGYuX2F1dGhlbnRpY2F0ZSgpCiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3NlcnZpY2UgPSBnb29nbGVfYnVpbGQoImRyaXZlIiwg"
    "InYzIiwgY3JlZGVudGlhbHM9Y3JlZHMpCiAgICAgICAgICAgIHNlbGYuX2RvY3Nfc2VydmljZSA9IGdvb2dsZV9idWlsZCgiZG9j"
    "cyIsICJ2MSIsIGNyZWRlbnRpYWxzPWNyZWRzKQogICAgICAgICAgICBzZWxmLl9sb2coIkRyaXZlIGF1dGggc3VjY2Vzcy4iLCBs"
    "ZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIHNlbGYuX2xvZygiRG9jcyBhdXRoIHN1Y2Nlc3MuIiwgbGV2ZWw9IklORk8iKQogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2xvZyhmIkRyaXZlIGF1dGggZmFpbHVyZToge2V4"
    "fSIsIGxldmVsPSJFUlJPUiIpCiAgICAgICAgICAgIHNlbGYuX2xvZyhmIkRvY3MgYXV0aCBmYWlsdXJlOiB7ZXh9IiwgbGV2ZWw9"
    "IkVSUk9SIikKICAgICAgICAgICAgcmFpc2UKCiAgICBkZWYgbGlzdF9mb2xkZXJfaXRlbXMoc2VsZiwgZm9sZGVyX2lkOiBzdHIg"
    "PSAicm9vdCIsIHBhZ2Vfc2l6ZTogaW50ID0gMTAwKToKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgc2Fm"
    "ZV9mb2xkZXJfaWQgPSAoZm9sZGVyX2lkIG9yICJyb290Iikuc3RyaXAoKSBvciAicm9vdCIKICAgICAgICBzZWxmLl9sb2coZiJE"
    "cml2ZSBmaWxlIGxpc3QgZmV0Y2ggc3RhcnRlZC4gZm9sZGVyX2lkPXtzYWZlX2ZvbGRlcl9pZH0iLCBsZXZlbD0iSU5GTyIpCiAg"
    "ICAgICAgcmVzcG9uc2UgPSBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkubGlzdCgKICAgICAgICAgICAgcT1mIid7c2FmZV9m"
    "b2xkZXJfaWR9JyBpbiBwYXJlbnRzIGFuZCB0cmFzaGVkPWZhbHNlIiwKICAgICAgICAgICAgcGFnZVNpemU9bWF4KDEsIG1pbihp"
    "bnQocGFnZV9zaXplIG9yIDEwMCksIDIwMCkpLAogICAgICAgICAgICBvcmRlckJ5PSJmb2xkZXIsbmFtZSxtb2RpZmllZFRpbWUg"
    "ZGVzYyIsCiAgICAgICAgICAgIGZpZWxkcz0oCiAgICAgICAgICAgICAgICAiZmlsZXMoIgogICAgICAgICAgICAgICAgImlkLG5h"
    "bWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVudHMsc2l6ZSwiCiAgICAgICAgICAgICAgICAibGFzdE1v"
    "ZGlmeWluZ1VzZXIoZGlzcGxheU5hbWUsZW1haWxBZGRyZXNzKSIKICAgICAgICAgICAgICAgICIpIgogICAgICAgICAgICApLAog"
    "ICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAgZmlsZXMgPSByZXNwb25zZS5nZXQoImZpbGVzIiwgW10pCiAgICAgICAgZm9yIGl0"
    "ZW0gaW4gZmlsZXM6CiAgICAgICAgICAgIG1pbWUgPSAoaXRlbS5nZXQoIm1pbWVUeXBlIikgb3IgIiIpLnN0cmlwKCkKICAgICAg"
    "ICAgICAgaXRlbVsiaXNfZm9sZGVyIl0gPSBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVyIgogICAg"
    "ICAgICAgICBpdGVtWyJpc19nb29nbGVfZG9jIl0gPSBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZG9jdW1l"
    "bnQiCiAgICAgICAgc2VsZi5fbG9nKGYiRHJpdmUgaXRlbXMgcmV0dXJuZWQ6IHtsZW4oZmlsZXMpfSBmb2xkZXJfaWQ9e3NhZmVf"
    "Zm9sZGVyX2lkfSIsIGxldmVsPSJJTkZPIikKICAgICAgICByZXR1cm4gZmlsZXMKCiAgICBkZWYgZ2V0X2RvY19wcmV2aWV3KHNl"
    "bGYsIGRvY19pZDogc3RyLCBtYXhfY2hhcnM6IGludCA9IDE4MDApOgogICAgICAgIGlmIG5vdCBkb2NfaWQ6CiAgICAgICAgICAg"
    "IHJhaXNlIFZhbHVlRXJyb3IoIkRvY3VtZW50IGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMo"
    "KQogICAgICAgIGRvYyA9IHNlbGYuX2RvY3Nfc2VydmljZS5kb2N1bWVudHMoKS5nZXQoZG9jdW1lbnRJZD1kb2NfaWQpLmV4ZWN1"
    "dGUoKQogICAgICAgIHRpdGxlID0gZG9jLmdldCgidGl0bGUiKSBvciAiVW50aXRsZWQiCiAgICAgICAgYm9keSA9IGRvYy5nZXQo"
    "ImJvZHkiLCB7fSkuZ2V0KCJjb250ZW50IiwgW10pCiAgICAgICAgY2h1bmtzID0gW10KICAgICAgICBmb3IgYmxvY2sgaW4gYm9k"
    "eToKICAgICAgICAgICAgcGFyYWdyYXBoID0gYmxvY2suZ2V0KCJwYXJhZ3JhcGgiKQogICAgICAgICAgICBpZiBub3QgcGFyYWdy"
    "YXBoOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgZWxlbWVudHMgPSBwYXJhZ3JhcGguZ2V0KCJlbGVtZW50"
    "cyIsIFtdKQogICAgICAgICAgICBmb3IgZWwgaW4gZWxlbWVudHM6CiAgICAgICAgICAgICAgICBydW4gPSBlbC5nZXQoInRleHRS"
    "dW4iKQogICAgICAgICAgICAgICAgaWYgbm90IHJ1bjoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAg"
    "ICAgdGV4dCA9IChydW4uZ2V0KCJjb250ZW50Iikgb3IgIiIpLnJlcGxhY2UoIlx4MGIiLCAiXG4iKQogICAgICAgICAgICAgICAg"
    "aWYgdGV4dDoKICAgICAgICAgICAgICAgICAgICBjaHVua3MuYXBwZW5kKHRleHQpCiAgICAgICAgcGFyc2VkID0gIiIuam9pbihj"
    "aHVua3MpLnN0cmlwKCkKICAgICAgICBpZiBsZW4ocGFyc2VkKSA+IG1heF9jaGFyczoKICAgICAgICAgICAgcGFyc2VkID0gcGFy"
    "c2VkWzptYXhfY2hhcnNdLnJzdHJpcCgpICsgIuKApiIKICAgICAgICByZXR1cm4gewogICAgICAgICAgICAidGl0bGUiOiB0aXRs"
    "ZSwKICAgICAgICAgICAgImRvY3VtZW50X2lkIjogZG9jX2lkLAogICAgICAgICAgICAicmV2aXNpb25faWQiOiBkb2MuZ2V0KCJy"
    "ZXZpc2lvbklkIiksCiAgICAgICAgICAgICJwcmV2aWV3X3RleHQiOiBwYXJzZWQgb3IgIltObyB0ZXh0IGNvbnRlbnQgcmV0dXJu"
    "ZWQgZnJvbSBEb2NzIEFQSS5dIiwKICAgICAgICB9CgogICAgZGVmIGNyZWF0ZV9kb2Moc2VsZiwgdGl0bGU6IHN0ciA9ICJOZXcg"
    "R3JpbVZlaWxlIFJlY29yZCIsIHBhcmVudF9mb2xkZXJfaWQ6IHN0ciA9ICJyb290Iik6CiAgICAgICAgc2FmZV90aXRsZSA9ICh0"
    "aXRsZSBvciAiTmV3IEdyaW1WZWlsZSBSZWNvcmQiKS5zdHJpcCgpIG9yICJOZXcgR3JpbVZlaWxlIFJlY29yZCIKICAgICAgICBz"
    "ZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgc2FmZV9wYXJlbnRfaWQgPSAocGFyZW50X2ZvbGRlcl9pZCBvciAicm9vdCIp"
    "LnN0cmlwKCkgb3IgInJvb3QiCiAgICAgICAgY3JlYXRlZCA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5jcmVhdGUoCiAg"
    "ICAgICAgICAgIGJvZHk9ewogICAgICAgICAgICAgICAgIm5hbWUiOiBzYWZlX3RpdGxlLAogICAgICAgICAgICAgICAgIm1pbWVU"
    "eXBlIjogImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5kb2N1bWVudCIsCiAgICAgICAgICAgICAgICAicGFyZW50cyI6IFtz"
    "YWZlX3BhcmVudF9pZF0sCiAgICAgICAgICAgIH0sCiAgICAgICAgICAgIGZpZWxkcz0iaWQsbmFtZSxtaW1lVHlwZSxtb2RpZmll"
    "ZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyIsCiAgICAgICAgKS5leGVjdXRlKCkKICAgICAgICBkb2NfaWQgPSBjcmVhdGVkLmdl"
    "dCgiaWQiKQogICAgICAgIG1ldGEgPSBzZWxmLmdldF9maWxlX21ldGFkYXRhKGRvY19pZCkgaWYgZG9jX2lkIGVsc2Uge30KICAg"
    "ICAgICByZXR1cm4gewogICAgICAgICAgICAiaWQiOiBkb2NfaWQsCiAgICAgICAgICAgICJuYW1lIjogbWV0YS5nZXQoIm5hbWUi"
    "KSBvciBzYWZlX3RpdGxlLAogICAgICAgICAgICAibWltZVR5cGUiOiBtZXRhLmdldCgibWltZVR5cGUiKSBvciAiYXBwbGljYXRp"
    "b24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IiwKICAgICAgICAgICAgIm1vZGlmaWVkVGltZSI6IG1ldGEuZ2V0KCJtb2RpZmll"
    "ZFRpbWUiKSwKICAgICAgICAgICAgIndlYlZpZXdMaW5rIjogbWV0YS5nZXQoIndlYlZpZXdMaW5rIiksCiAgICAgICAgICAgICJw"
    "YXJlbnRzIjogbWV0YS5nZXQoInBhcmVudHMiKSBvciBbc2FmZV9wYXJlbnRfaWRdLAogICAgICAgIH0KCiAgICBkZWYgY3JlYXRl"
    "X2ZvbGRlcihzZWxmLCBuYW1lOiBzdHIgPSAiTmV3IEZvbGRlciIsIHBhcmVudF9mb2xkZXJfaWQ6IHN0ciA9ICJyb290Iik6CiAg"
    "ICAgICAgc2FmZV9uYW1lID0gKG5hbWUgb3IgIk5ldyBGb2xkZXIiKS5zdHJpcCgpIG9yICJOZXcgRm9sZGVyIgogICAgICAgIHNh"
    "ZmVfcGFyZW50X2lkID0gKHBhcmVudF9mb2xkZXJfaWQgb3IgInJvb3QiKS5zdHJpcCgpIG9yICJyb290IgogICAgICAgIHNlbGYu"
    "ZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBjcmVhdGVkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmNyZWF0ZSgKICAg"
    "ICAgICAgICAgYm9keT17CiAgICAgICAgICAgICAgICAibmFtZSI6IHNhZmVfbmFtZSwKICAgICAgICAgICAgICAgICJtaW1lVHlw"
    "ZSI6ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVyIiwKICAgICAgICAgICAgICAgICJwYXJlbnRzIjogW3NhZmVf"
    "cGFyZW50X2lkXSwKICAgICAgICAgICAgfSwKICAgICAgICAgICAgZmllbGRzPSJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVkVGlt"
    "ZSx3ZWJWaWV3TGluayxwYXJlbnRzIiwKICAgICAgICApLmV4ZWN1dGUoKQogICAgICAgIHJldHVybiBjcmVhdGVkCgogICAgZGVm"
    "IGdldF9maWxlX21ldGFkYXRhKHNlbGYsIGZpbGVfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGZpbGVfaWQ6CiAgICAgICAgICAg"
    "IHJhaXNlIFZhbHVlRXJyb3IoIkZpbGUgaWQgaXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAg"
    "ICAgICAgcmV0dXJuIHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5nZXQoCiAgICAgICAgICAgIGZpbGVJZD1maWxlX2lkLAog"
    "ICAgICAgICAgICBmaWVsZHM9ImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVudHMsc2l6ZSIs"
    "CiAgICAgICAgKS5leGVjdXRlKCkKCiAgICBkZWYgZ2V0X2RvY19tZXRhZGF0YShzZWxmLCBkb2NfaWQ6IHN0cik6CiAgICAgICAg"
    "cmV0dXJuIHNlbGYuZ2V0X2ZpbGVfbWV0YWRhdGEoZG9jX2lkKQoKICAgIGRlZiBkZWxldGVfaXRlbShzZWxmLCBmaWxlX2lkOiBz"
    "dHIpOgogICAgICAgIGlmIG5vdCBmaWxlX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlkIGlzIHJlcXVp"
    "cmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5k"
    "ZWxldGUoZmlsZUlkPWZpbGVfaWQpLmV4ZWN1dGUoKQoKICAgIGRlZiBkZWxldGVfZG9jKHNlbGYsIGRvY19pZDogc3RyKToKICAg"
    "ICAgICBzZWxmLmRlbGV0ZV9pdGVtKGRvY19pZCkKCiAgICBkZWYgZXhwb3J0X2RvY190ZXh0KHNlbGYsIGRvY19pZDogc3RyKToK"
    "ICAgICAgICBpZiBub3QgZG9jX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJEb2N1bWVudCBpZCBpcyByZXF1aXJl"
    "ZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBwYXlsb2FkID0gc2VsZi5fZHJpdmVfc2VydmljZS5m"
    "aWxlcygpLmV4cG9ydCgKICAgICAgICAgICAgZmlsZUlkPWRvY19pZCwKICAgICAgICAgICAgbWltZVR5cGU9InRleHQvcGxhaW4i"
    "LAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAgaWYgaXNpbnN0YW5jZShwYXlsb2FkLCBieXRlcyk6CiAgICAgICAgICAgIHJl"
    "dHVybiBwYXlsb2FkLmRlY29kZSgidXRmLTgiLCBlcnJvcnM9InJlcGxhY2UiKQogICAgICAgIHJldHVybiBzdHIocGF5bG9hZCBv"
    "ciAiIikKCiAgICBkZWYgZG93bmxvYWRfZmlsZV9ieXRlcyhzZWxmLCBmaWxlX2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBmaWxl"
    "X2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1"
    "cmVfc2VydmljZXMoKQogICAgICAgIHJldHVybiBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuZ2V0X21lZGlhKGZpbGVJZD1m"
    "aWxlX2lkKS5leGVjdXRlKCkKCgoKCiMg4pSA4pSAIFBBU1MgMyBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "IyBBbGwgd29ya2VyIHRocmVhZHMgZGVmaW5lZC4gQWxsIGdlbmVyYXRpb24gaXMgc3RyZWFtaW5nLgojIE5vIGJsb2NraW5nIGNh"
    "bGxzIG9uIG1haW4gdGhyZWFkIGFueXdoZXJlIGluIHRoaXMgZmlsZS4KIwojIE5leHQ6IFBhc3MgNCDigJQgTWVtb3J5ICYgU3Rv"
    "cmFnZQojIChNZW1vcnlNYW5hZ2VyLCBTZXNzaW9uTWFuYWdlciwgTGVzc29uc0xlYXJuZWREQiwgVGFza01hbmFnZXIpCgoKIyDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDQ6IE1FTU9SWSAmIFNUT1JBR0UKIwojIFN5c3RlbXMgZGVmaW5l"
    "ZCBoZXJlOgojICAgRGVwZW5kZW5jeUNoZWNrZXIgICDigJQgdmFsaWRhdGVzIGFsbCByZXF1aXJlZCBwYWNrYWdlcyBvbiBzdGFy"
    "dHVwCiMgICBNZW1vcnlNYW5hZ2VyICAgICAgIOKAlCBKU09OTCBtZW1vcnkgcmVhZC93cml0ZS9zZWFyY2gKIyAgIFNlc3Npb25N"
    "YW5hZ2VyICAgICAg4oCUIGF1dG8tc2F2ZSwgbG9hZCwgY29udGV4dCBpbmplY3Rpb24sIHNlc3Npb24gaW5kZXgKIyAgIExlc3Nv"
    "bnNMZWFybmVkREIgICAg4oCUIExTTCBGb3JiaWRkZW4gUnVsZXNldCArIGNvZGUgbGVzc29ucyBrbm93bGVkZ2UgYmFzZQojICAg"
    "VGFza01hbmFnZXIgICAgICAgICDigJQgdGFzay9yZW1pbmRlciBDUlVELCBkdWUtZXZlbnQgZGV0ZWN0aW9uCiMg4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQCgoKIyDilIDilIAgREVQRU5ERU5DWSBDSEVDS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEZXBlbmRlbmN5Q2hlY2tl"
    "cjoKICAgICIiIgogICAgVmFsaWRhdGVzIGFsbCByZXF1aXJlZCBhbmQgb3B0aW9uYWwgcGFja2FnZXMgb24gc3RhcnR1cC4KICAg"
    "IFJldHVybnMgYSBsaXN0IG9mIHN0YXR1cyBtZXNzYWdlcyBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgIFNob3dzIGEgYmxv"
    "Y2tpbmcgZXJyb3IgZGlhbG9nIGZvciBhbnkgY3JpdGljYWwgbWlzc2luZyBkZXBlbmRlbmN5LgogICAgIiIiCgogICAgIyAocGFj"
    "a2FnZV9uYW1lLCBpbXBvcnRfbmFtZSwgY3JpdGljYWwsIGluc3RhbGxfaGludCkKICAgIFBBQ0tBR0VTID0gWwogICAgICAgICgi"
    "UHlTaWRlNiIsICAgICAgICAgICAgICAgICAgICJQeVNpZGU2IiwgICAgICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5z"
    "dGFsbCBQeVNpZGU2IiksCiAgICAgICAgKCJsb2d1cnUiLCAgICAgICAgICAgICAgICAgICAgImxvZ3VydSIsICAgICAgICAgICAg"
    "ICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGxvZ3VydSIpLAogICAgICAgICgiYXBzY2hlZHVsZXIiLCAgICAgICAgICAg"
    "ICAgICJhcHNjaGVkdWxlciIsICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBhcHNjaGVkdWxlciIpLAogICAg"
    "ICAgICgicHlnYW1lIiwgICAgICAgICAgICAgICAgICAgICJweWdhbWUiLCAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAi"
    "cGlwIGluc3RhbGwgcHlnYW1lICAobmVlZGVkIGZvciBzb3VuZCkiKSwKICAgICAgICAoInB5d2luMzIiLCAgICAgICAgICAgICAg"
    "ICAgICAid2luMzJjb20iLCAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5d2luMzIgIChuZWVkZWQg"
    "Zm9yIGRlc2t0b3Agc2hvcnRjdXQpIiksCiAgICAgICAgKCJwc3V0aWwiLCAgICAgICAgICAgICAgICAgICAgInBzdXRpbCIsICAg"
    "ICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBwc3V0aWwgIChuZWVkZWQgZm9yIHN5c3RlbSBtb25pdG9y"
    "aW5nKSIpLAogICAgICAgICgicmVxdWVzdHMiLCAgICAgICAgICAgICAgICAgICJyZXF1ZXN0cyIsICAgICAgICAgICAgIEZhbHNl"
    "LAogICAgICAgICAicGlwIGluc3RhbGwgcmVxdWVzdHMiKSwKICAgICAgICAoImdvb2dsZS1hcGktcHl0aG9uLWNsaWVudCIsICAi"
    "Z29vZ2xlYXBpY2xpZW50IiwgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGdvb2dsZS1hcGktcHl0aG9uLWNsaWVu"
    "dCIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgtb2F1dGhsaWIiLCAgICAgICJnb29nbGVfYXV0aF9vYXV0aGxpYiIsIEZhbHNlLAog"
    "ICAgICAgICAicGlwIGluc3RhbGwgZ29vZ2xlLWF1dGgtb2F1dGhsaWIiKSwKICAgICAgICAoImdvb2dsZS1hdXRoIiwgICAgICAg"
    "ICAgICAgICAiZ29vZ2xlLmF1dGgiLCAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGdvb2dsZS1hdXRoIiks"
    "CiAgICAgICAgKCJ0b3JjaCIsICAgICAgICAgICAgICAgICAgICAgInRvcmNoIiwgICAgICAgICAgICAgICAgRmFsc2UsCiAgICAg"
    "ICAgICJwaXAgaW5zdGFsbCB0b3JjaCAgKG9ubHkgbmVlZGVkIGZvciBsb2NhbCBtb2RlbCkiKSwKICAgICAgICAoInRyYW5zZm9y"
    "bWVycyIsICAgICAgICAgICAgICAidHJhbnNmb3JtZXJzIiwgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHRy"
    "YW5zZm9ybWVycyAgKG9ubHkgbmVlZGVkIGZvciBsb2NhbCBtb2RlbCkiKSwKICAgICAgICAoInB5bnZtbCIsICAgICAgICAgICAg"
    "ICAgICAgICAicHludm1sIiwgICAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5bnZtbCAgKG9ubHkg"
    "bmVlZGVkIGZvciBOVklESUEgR1BVIG1vbml0b3JpbmcpIiksCiAgICBdCgogICAgQGNsYXNzbWV0aG9kCiAgICBkZWYgY2hlY2so"
    "Y2xzKSAtPiB0dXBsZVtsaXN0W3N0cl0sIGxpc3Rbc3RyXV06CiAgICAgICAgIiIiCiAgICAgICAgUmV0dXJucyAobWVzc2FnZXMs"
    "IGNyaXRpY2FsX2ZhaWx1cmVzKS4KICAgICAgICBtZXNzYWdlczogbGlzdCBvZiAiW0RFUFNdIHBhY2thZ2Ug4pyTL+KclyDigJQg"
    "bm90ZSIgc3RyaW5ncwogICAgICAgIGNyaXRpY2FsX2ZhaWx1cmVzOiBsaXN0IG9mIHBhY2thZ2VzIHRoYXQgYXJlIGNyaXRpY2Fs"
    "IGFuZCBtaXNzaW5nCiAgICAgICAgIiIiCiAgICAgICAgaW1wb3J0IGltcG9ydGxpYgogICAgICAgIG1lc3NhZ2VzICA9IFtdCiAg"
    "ICAgICAgY3JpdGljYWwgID0gW10KCiAgICAgICAgZm9yIHBrZ19uYW1lLCBpbXBvcnRfbmFtZSwgaXNfY3JpdGljYWwsIGhpbnQg"
    "aW4gY2xzLlBBQ0tBR0VTOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpbXBvcnRsaWIuaW1wb3J0X21vZHVsZShp"
    "bXBvcnRfbmFtZSkKICAgICAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZChmIltERVBTXSB7cGtnX25hbWV9IOKckyIpCiAgICAg"
    "ICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgICAgIHN0YXR1cyA9ICJDUklUSUNBTCIgaWYgaXNfY3JpdGlj"
    "YWwgZWxzZSAib3B0aW9uYWwiCiAgICAgICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgZiJb"
    "REVQU10ge3BrZ19uYW1lfSDinJcgKHtzdGF0dXN9KSDigJQge2hpbnR9IgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAg"
    "ICAgaWYgaXNfY3JpdGljYWw6CiAgICAgICAgICAgICAgICAgICAgY3JpdGljYWwuYXBwZW5kKHBrZ19uYW1lKQoKICAgICAgICBy"
    "ZXR1cm4gbWVzc2FnZXMsIGNyaXRpY2FsCgogICAgQGNsYXNzbWV0aG9kCiAgICBkZWYgY2hlY2tfb2xsYW1hKGNscykgLT4gc3Ry"
    "OgogICAgICAgICIiIkNoZWNrIGlmIE9sbGFtYSBpcyBydW5uaW5nLiBSZXR1cm5zIHN0YXR1cyBzdHJpbmcuIiIiCiAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICByZXEgID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdCgiaHR0cDovL2xvY2FsaG9zdDoxMTQzNC9hcGkv"
    "dGFncyIpCiAgICAgICAgICAgIHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0yKQogICAgICAgICAg"
    "ICBpZiByZXNwLnN0YXR1cyA9PSAyMDA6CiAgICAgICAgICAgICAgICByZXR1cm4gIltERVBTXSBPbGxhbWEg4pyTIOKAlCBydW5u"
    "aW5nIG9uIGxvY2FsaG9zdDoxMTQzNCIKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICAgICAg"
    "cmV0dXJuICJbREVQU10gT2xsYW1hIOKclyDigJQgbm90IHJ1bm5pbmcgKG9ubHkgbmVlZGVkIGZvciBPbGxhbWEgbW9kZWwgdHlw"
    "ZSkiCgoKIyDilIDilIAgTUVNT1JZIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1lbW9yeU1h"
    "bmFnZXI6CiAgICAiIiIKICAgIEhhbmRsZXMgYWxsIEpTT05MIG1lbW9yeSBvcGVyYXRpb25zLgoKICAgIEZpbGVzIG1hbmFnZWQ6"
    "CiAgICAgICAgbWVtb3JpZXMvbWVzc2FnZXMuanNvbmwgICAgICAgICDigJQgZXZlcnkgbWVzc2FnZSwgdGltZXN0YW1wZWQKICAg"
    "ICAgICBtZW1vcmllcy9tZW1vcmllcy5qc29ubCAgICAgICAgIOKAlCBleHRyYWN0ZWQgbWVtb3J5IHJlY29yZHMKICAgICAgICBt"
    "ZW1vcmllcy9zdGF0ZS5qc29uICAgICAgICAgICAgIOKAlCBlbnRpdHkgc3RhdGUKICAgICAgICBtZW1vcmllcy9pbmRleC5qc29u"
    "ICAgICAgICAgICAgIOKAlCBjb3VudHMgYW5kIG1ldGFkYXRhCgogICAgTWVtb3J5IHJlY29yZHMgaGF2ZSB0eXBlIGluZmVyZW5j"
    "ZSwga2V5d29yZCBleHRyYWN0aW9uLCB0YWcgZ2VuZXJhdGlvbiwKICAgIG5lYXItZHVwbGljYXRlIGRldGVjdGlvbiwgYW5kIHJl"
    "bGV2YW5jZSBzY29yaW5nIGZvciBjb250ZXh0IGluamVjdGlvbi4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAg"
    "ICAgICBiYXNlICAgICAgICAgICAgID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikKICAgICAgICBzZWxmLm1lc3NhZ2VzX3AgID0gYmFz"
    "ZSAvICJtZXNzYWdlcy5qc29ubCIKICAgICAgICBzZWxmLm1lbW9yaWVzX3AgID0gYmFzZSAvICJtZW1vcmllcy5qc29ubCIKICAg"
    "ICAgICBzZWxmLnN0YXRlX3AgICAgID0gYmFzZSAvICJzdGF0ZS5qc29uIgogICAgICAgIHNlbGYuaW5kZXhfcCAgICAgPSBiYXNl"
    "IC8gImluZGV4Lmpzb24iCgogICAgIyDilIDilIAgU1RBVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbG9hZF9z"
    "dGF0ZShzZWxmKSAtPiBkaWN0OgogICAgICAgIGlmIG5vdCBzZWxmLnN0YXRlX3AuZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVy"
    "biBzZWxmLl9kZWZhdWx0X3N0YXRlKCkKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVybiBqc29uLmxvYWRzKHNlbGYuc3Rh"
    "dGVfcC5yZWFkX3RleHQoZW5jb2Rpbmc9InV0Zi04IikpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0"
    "dXJuIHNlbGYuX2RlZmF1bHRfc3RhdGUoKQoKICAgIGRlZiBzYXZlX3N0YXRlKHNlbGYsIHN0YXRlOiBkaWN0KSAtPiBOb25lOgog"
    "ICAgICAgIHNlbGYuc3RhdGVfcC53cml0ZV90ZXh0KAogICAgICAgICAgICBqc29uLmR1bXBzKHN0YXRlLCBpbmRlbnQ9MiksIGVu"
    "Y29kaW5nPSJ1dGYtOCIKICAgICAgICApCgogICAgZGVmIF9kZWZhdWx0X3N0YXRlKHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgcmV0"
    "dXJuIHsKICAgICAgICAgICAgInBlcnNvbmFfbmFtZSI6ICAgICAgICAgICAgIERFQ0tfTkFNRSwKICAgICAgICAgICAgImRlY2tf"
    "dmVyc2lvbiI6ICAgICAgICAgICAgIEFQUF9WRVJTSU9OLAogICAgICAgICAgICAic2Vzc2lvbl9jb3VudCI6ICAgICAgICAgICAg"
    "MCwKICAgICAgICAgICAgImxhc3Rfc3RhcnR1cCI6ICAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgICJsYXN0X3NodXRkb3du"
    "IjogICAgICAgICAgICBOb25lLAogICAgICAgICAgICAibGFzdF9hY3RpdmUiOiAgICAgICAgICAgICAgTm9uZSwKICAgICAgICAg"
    "ICAgInRvdGFsX21lc3NhZ2VzIjogICAgICAgICAgIDAsCiAgICAgICAgICAgICJ0b3RhbF9tZW1vcmllcyI6ICAgICAgICAgICAw"
    "LAogICAgICAgICAgICAiaW50ZXJuYWxfbmFycmF0aXZlIjogICAgICAge30sCiAgICAgICAgICAgICJ2YW1waXJlX3N0YXRlX2F0"
    "X3NodXRkb3duIjoiRE9STUFOVCIsCiAgICAgICAgfQoKICAgICMg4pSA4pSAIE1FU1NBR0VTIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ZGVmIGFwcGVuZF9tZXNzYWdlKHNlbGYsIHNlc3Npb25faWQ6IHN0ciwgcm9sZTogc3RyLAogICAgICAgICAgICAgICAgICAgICAg"
    "IGNvbnRlbnQ6IHN0ciwgZW1vdGlvbjogc3RyID0gIiIpIC0+IGRpY3Q6CiAgICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAi"
    "aWQiOiAgICAgICAgIGYibXNnX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6ICBsb2Nh"
    "bF9ub3dfaXNvKCksCiAgICAgICAgICAgICJzZXNzaW9uX2lkIjogc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEiOiAg"
    "ICBERUNLX05BTUUsCiAgICAgICAgICAgICJyb2xlIjogICAgICAgcm9sZSwKICAgICAgICAgICAgImNvbnRlbnQiOiAgICBjb250"
    "ZW50LAogICAgICAgICAgICAiZW1vdGlvbiI6ICAgIGVtb3Rpb24sCiAgICAgICAgfQogICAgICAgIGFwcGVuZF9qc29ubChzZWxm"
    "Lm1lc3NhZ2VzX3AsIHJlY29yZCkKICAgICAgICByZXR1cm4gcmVjb3JkCgogICAgZGVmIGxvYWRfcmVjZW50X21lc3NhZ2VzKHNl"
    "bGYsIGxpbWl0OiBpbnQgPSAyMCkgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChzZWxmLm1lc3NhZ2Vz"
    "X3ApWy1saW1pdDpdCgogICAgIyDilIDilIAgTUVNT1JJRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgYXBwZW5kX21lbW9yeShz"
    "ZWxmLCBzZXNzaW9uX2lkOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgICAgYXNzaXN0YW50X3RleHQ6"
    "IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgcmVjb3JkX3R5cGUgPSBpbmZlcl9yZWNvcmRfdHlwZSh1c2VyX3RleHQs"
    "IGFzc2lzdGFudF90ZXh0KQogICAgICAgIGtleXdvcmRzICAgID0gZXh0cmFjdF9rZXl3b3Jkcyh1c2VyX3RleHQgKyAiICIgKyBh"
    "c3Npc3RhbnRfdGV4dCkKICAgICAgICB0YWdzICAgICAgICA9IHNlbGYuX2luZmVyX3RhZ3MocmVjb3JkX3R5cGUsIHVzZXJfdGV4"
    "dCwga2V5d29yZHMpCiAgICAgICAgdGl0bGUgICAgICAgPSBzZWxmLl9pbmZlcl90aXRsZShyZWNvcmRfdHlwZSwgdXNlcl90ZXh0"
    "LCBrZXl3b3JkcykKICAgICAgICBzdW1tYXJ5ICAgICA9IHNlbGYuX3N1bW1hcml6ZShyZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBh"
    "c3Npc3RhbnRfdGV4dCkKCiAgICAgICAgbWVtb3J5ID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICAgIGYibWVtX3t1"
    "dWlkLnV1aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6ICAgICAgICBsb2NhbF9ub3dfaXNvKCksCiAg"
    "ICAgICAgICAgICJzZXNzaW9uX2lkIjogICAgICAgc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEiOiAgICAgICAgICBE"
    "RUNLX05BTUUsCiAgICAgICAgICAgICJ0eXBlIjogICAgICAgICAgICAgcmVjb3JkX3R5cGUsCiAgICAgICAgICAgICJ0aXRsZSI6"
    "ICAgICAgICAgICAgdGl0bGUsCiAgICAgICAgICAgICJzdW1tYXJ5IjogICAgICAgICAgc3VtbWFyeSwKICAgICAgICAgICAgImNv"
    "bnRlbnQiOiAgICAgICAgICB1c2VyX3RleHRbOjQwMDBdLAogICAgICAgICAgICAiYXNzaXN0YW50X2NvbnRleHQiOmFzc2lzdGFu"
    "dF90ZXh0WzoxMjAwXSwKICAgICAgICAgICAgImtleXdvcmRzIjogICAgICAgICBrZXl3b3JkcywKICAgICAgICAgICAgInRhZ3Mi"
    "OiAgICAgICAgICAgICB0YWdzLAogICAgICAgICAgICAiY29uZmlkZW5jZSI6ICAgICAgIDAuNzAgaWYgcmVjb3JkX3R5cGUgaW4g"
    "ewogICAgICAgICAgICAgICAgImRyZWFtIiwiaXNzdWUiLCJpZGVhIiwicHJlZmVyZW5jZSIsInJlc29sdXRpb24iCiAgICAgICAg"
    "ICAgIH0gZWxzZSAwLjU1LAogICAgICAgIH0KCiAgICAgICAgaWYgc2VsZi5faXNfbmVhcl9kdXBsaWNhdGUobWVtb3J5KToKICAg"
    "ICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgYXBwZW5kX2pzb25sKHNlbGYubWVtb3JpZXNfcCwgbWVtb3J5KQogICAgICAg"
    "IHJldHVybiBtZW1vcnkKCiAgICBkZWYgc2VhcmNoX21lbW9yaWVzKHNlbGYsIHF1ZXJ5OiBzdHIsIGxpbWl0OiBpbnQgPSA2KSAt"
    "PiBsaXN0W2RpY3RdOgogICAgICAgICIiIgogICAgICAgIEtleXdvcmQtc2NvcmVkIG1lbW9yeSBzZWFyY2guCiAgICAgICAgUmV0"
    "dXJucyB1cCB0byBgbGltaXRgIHJlY29yZHMgc29ydGVkIGJ5IHJlbGV2YW5jZSBzY29yZSBkZXNjZW5kaW5nLgogICAgICAgIEZh"
    "bGxzIGJhY2sgdG8gbW9zdCByZWNlbnQgaWYgbm8gcXVlcnkgdGVybXMgbWF0Y2guCiAgICAgICAgIiIiCiAgICAgICAgbWVtb3Jp"
    "ZXMgPSByZWFkX2pzb25sKHNlbGYubWVtb3JpZXNfcCkKICAgICAgICBpZiBub3QgcXVlcnkuc3RyaXAoKToKICAgICAgICAgICAg"
    "cmV0dXJuIG1lbW9yaWVzWy1saW1pdDpdCgogICAgICAgIHFfdGVybXMgPSBzZXQoZXh0cmFjdF9rZXl3b3JkcyhxdWVyeSwgbGlt"
    "aXQ9MTYpKQogICAgICAgIHNjb3JlZCAgPSBbXQoKICAgICAgICBmb3IgaXRlbSBpbiBtZW1vcmllczoKICAgICAgICAgICAgaXRl"
    "bV90ZXJtcyA9IHNldChleHRyYWN0X2tleXdvcmRzKCIgIi5qb2luKFsKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0KCJ0aXRsZSIs"
    "ICAgIiIpLAogICAgICAgICAgICAgICAgaXRlbS5nZXQoInN1bW1hcnkiLCAiIiksCiAgICAgICAgICAgICAgICBpdGVtLmdldCgi"
    "Y29udGVudCIsICIiKSwKICAgICAgICAgICAgICAgICIgIi5qb2luKGl0ZW0uZ2V0KCJrZXl3b3JkcyIsIFtdKSksCiAgICAgICAg"
    "ICAgICAgICAiICIuam9pbihpdGVtLmdldCgidGFncyIsICAgICBbXSkpLAogICAgICAgICAgICBdKSwgbGltaXQ9NDApKQoKICAg"
    "ICAgICAgICAgc2NvcmUgPSBsZW4ocV90ZXJtcyAmIGl0ZW1fdGVybXMpCgogICAgICAgICAgICAjIEJvb3N0IGJ5IHR5cGUgbWF0"
    "Y2gKICAgICAgICAgICAgcWwgPSBxdWVyeS5sb3dlcigpCiAgICAgICAgICAgIHJ0ID0gaXRlbS5nZXQoInR5cGUiLCAiIikKICAg"
    "ICAgICAgICAgaWYgImRyZWFtIiAgaW4gcWwgYW5kIHJ0ID09ICJkcmVhbSI6ICAgIHNjb3JlICs9IDQKICAgICAgICAgICAgaWYg"
    "InRhc2siICAgaW4gcWwgYW5kIHJ0ID09ICJ0YXNrIjogICAgIHNjb3JlICs9IDMKICAgICAgICAgICAgaWYgImlkZWEiICAgaW4g"
    "cWwgYW5kIHJ0ID09ICJpZGVhIjogICAgIHNjb3JlICs9IDIKICAgICAgICAgICAgaWYgImxzbCIgICAgaW4gcWwgYW5kIHJ0IGlu"
    "IHsiaXNzdWUiLCJyZXNvbHV0aW9uIn06IHNjb3JlICs9IDIKCiAgICAgICAgICAgIGlmIHNjb3JlID4gMDoKICAgICAgICAgICAg"
    "ICAgIHNjb3JlZC5hcHBlbmQoKHNjb3JlLCBpdGVtKSkKCiAgICAgICAgc2NvcmVkLnNvcnQoa2V5PWxhbWJkYSB4OiAoeFswXSwg"
    "eFsxXS5nZXQoInRpbWVzdGFtcCIsICIiKSksCiAgICAgICAgICAgICAgICAgICAgcmV2ZXJzZT1UcnVlKQogICAgICAgIHJldHVy"
    "biBbaXRlbSBmb3IgXywgaXRlbSBpbiBzY29yZWRbOmxpbWl0XV0KCiAgICBkZWYgYnVpbGRfY29udGV4dF9ibG9jayhzZWxmLCBx"
    "dWVyeTogc3RyLCBtYXhfY2hhcnM6IGludCA9IDIwMDApIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBCdWlsZCBhIGNvbnRl"
    "eHQgc3RyaW5nIGZyb20gcmVsZXZhbnQgbWVtb3JpZXMgZm9yIHByb21wdCBpbmplY3Rpb24uCiAgICAgICAgVHJ1bmNhdGVzIHRv"
    "IG1heF9jaGFycyB0byBwcm90ZWN0IHRoZSBjb250ZXh0IHdpbmRvdy4KICAgICAgICAiIiIKICAgICAgICBtZW1vcmllcyA9IHNl"
    "bGYuc2VhcmNoX21lbW9yaWVzKHF1ZXJ5LCBsaW1pdD00KQogICAgICAgIGlmIG5vdCBtZW1vcmllczoKICAgICAgICAgICAgcmV0"
    "dXJuICIiCgogICAgICAgIHBhcnRzID0gWyJbUkVMRVZBTlQgTUVNT1JJRVNdIl0KICAgICAgICB0b3RhbCA9IDAKICAgICAgICBm"
    "b3IgbSBpbiBtZW1vcmllczoKICAgICAgICAgICAgZW50cnkgPSAoCiAgICAgICAgICAgICAgICBmIuKAoiBbe20uZ2V0KCd0eXBl"
    "JywnJykudXBwZXIoKX1dIHttLmdldCgndGl0bGUnLCcnKX06ICIKICAgICAgICAgICAgICAgIGYie20uZ2V0KCdzdW1tYXJ5Jywn"
    "Jyl9IgogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIHRvdGFsICsgbGVuKGVudHJ5KSA+IG1heF9jaGFyczoKICAgICAgICAg"
    "ICAgICAgIGJyZWFrCiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChlbnRyeSkKICAgICAgICAgICAgdG90YWwgKz0gbGVuKGVudHJ5"
    "KQoKICAgICAgICBwYXJ0cy5hcHBlbmQoIltFTkQgTUVNT1JJRVNdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBhcnRzKQoK"
    "ICAgICMg4pSA4pSAIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2lzX25lYXJfZHVwbGljYXRlKHNlbGYsIGNh"
    "bmRpZGF0ZTogZGljdCkgLT4gYm9vbDoKICAgICAgICByZWNlbnQgPSByZWFkX2pzb25sKHNlbGYubWVtb3JpZXNfcClbLTI1Ol0K"
    "ICAgICAgICBjdCA9IGNhbmRpZGF0ZS5nZXQoInRpdGxlIiwgIiIpLmxvd2VyKCkuc3RyaXAoKQogICAgICAgIGNzID0gY2FuZGlk"
    "YXRlLmdldCgic3VtbWFyeSIsICIiKS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBmb3IgaXRlbSBpbiByZWNlbnQ6CiAgICAgICAg"
    "ICAgIGlmIGl0ZW0uZ2V0KCJ0aXRsZSIsIiIpLmxvd2VyKCkuc3RyaXAoKSA9PSBjdDogIHJldHVybiBUcnVlCiAgICAgICAgICAg"
    "IGlmIGl0ZW0uZ2V0KCJzdW1tYXJ5IiwiIikubG93ZXIoKS5zdHJpcCgpID09IGNzOiByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVy"
    "biBGYWxzZQoKICAgIGRlZiBfaW5mZXJfdGFncyhzZWxmLCByZWNvcmRfdHlwZTogc3RyLCB0ZXh0OiBzdHIsCiAgICAgICAgICAg"
    "ICAgICAgICAga2V5d29yZHM6IGxpc3Rbc3RyXSkgLT4gbGlzdFtzdHJdOgogICAgICAgIHQgICAgPSB0ZXh0Lmxvd2VyKCkKICAg"
    "ICAgICB0YWdzID0gW3JlY29yZF90eXBlXQogICAgICAgIGlmICJkcmVhbSIgICBpbiB0OiB0YWdzLmFwcGVuZCgiZHJlYW0iKQog"
    "ICAgICAgIGlmICJsc2wiICAgICBpbiB0OiB0YWdzLmFwcGVuZCgibHNsIikKICAgICAgICBpZiAicHl0aG9uIiAgaW4gdDogdGFn"
    "cy5hcHBlbmQoInB5dGhvbiIpCiAgICAgICAgaWYgImdhbWUiICAgIGluIHQ6IHRhZ3MuYXBwZW5kKCJnYW1lX2lkZWEiKQogICAg"
    "ICAgIGlmICJzbCIgICAgICBpbiB0IG9yICJzZWNvbmQgbGlmZSIgaW4gdDogdGFncy5hcHBlbmQoInNlY29uZGxpZmUiKQogICAg"
    "ICAgIGlmIERFQ0tfTkFNRS5sb3dlcigpIGluIHQ6IHRhZ3MuYXBwZW5kKERFQ0tfTkFNRS5sb3dlcigpKQogICAgICAgIGZvciBr"
    "dyBpbiBrZXl3b3Jkc1s6NF06CiAgICAgICAgICAgIGlmIGt3IG5vdCBpbiB0YWdzOgogICAgICAgICAgICAgICAgdGFncy5hcHBl"
    "bmQoa3cpCiAgICAgICAgIyBEZWR1cGxpY2F0ZSBwcmVzZXJ2aW5nIG9yZGVyCiAgICAgICAgc2Vlbiwgb3V0ID0gc2V0KCksIFtd"
    "CiAgICAgICAgZm9yIHRhZyBpbiB0YWdzOgogICAgICAgICAgICBpZiB0YWcgbm90IGluIHNlZW46CiAgICAgICAgICAgICAgICBz"
    "ZWVuLmFkZCh0YWcpCiAgICAgICAgICAgICAgICBvdXQuYXBwZW5kKHRhZykKICAgICAgICByZXR1cm4gb3V0WzoxMl0KCiAgICBk"
    "ZWYgX2luZmVyX3RpdGxlKHNlbGYsIHJlY29yZF90eXBlOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAg"
    "ICBrZXl3b3JkczogbGlzdFtzdHJdKSAtPiBzdHI6CiAgICAgICAgZGVmIGNsZWFuKHdvcmRzKToKICAgICAgICAgICAgcmV0dXJu"
    "IFt3LnN0cmlwKCIgLV8uLCE/IikuY2FwaXRhbGl6ZSgpCiAgICAgICAgICAgICAgICAgICAgZm9yIHcgaW4gd29yZHMgaWYgbGVu"
    "KHcpID4gMl0KCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInRhc2siOgogICAgICAgICAgICBpbXBvcnQgcmUKICAgICAgICAg"
    "ICAgbSA9IHJlLnNlYXJjaChyInJlbWluZCBtZSAuKj8gdG8gKC4rKSIsIHVzZXJfdGV4dCwgcmUuSSkKICAgICAgICAgICAgaWYg"
    "bToKICAgICAgICAgICAgICAgIHJldHVybiBmIlJlbWluZGVyOiB7bS5ncm91cCgxKS5zdHJpcCgpWzo2MF19IgogICAgICAgICAg"
    "ICByZXR1cm4gIlJlbWluZGVyIFRhc2siCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImRyZWFtIjoKICAgICAgICAgICAgcmV0"
    "dXJuIGYieycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzozXSkpfSBEcmVhbSIuc3RyaXAoKSBvciAiRHJlYW0gTWVtb3J5IgogICAg"
    "ICAgIGlmIHJlY29yZF90eXBlID09ICJpc3N1ZSI6CiAgICAgICAgICAgIHJldHVybiBmIklzc3VlOiB7JyAnLmpvaW4oY2xlYW4o"
    "a2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJUZWNobmljYWwgSXNzdWUiCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInJl"
    "c29sdXRpb24iOgogICAgICAgICAgICByZXR1cm4gZiJSZXNvbHV0aW9uOiB7JyAnLmpvaW4oY2xlYW4oa2V5d29yZHNbOjRdKSl9"
    "Ii5zdHJpcCgpIG9yICJUZWNobmljYWwgUmVzb2x1dGlvbiIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaWRlYSI6CiAgICAg"
    "ICAgICAgIHJldHVybiBmIklkZWE6IHsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0pKX0iLnN0cmlwKCkgb3IgIklkZWEiCiAg"
    "ICAgICAgaWYga2V5d29yZHM6CiAgICAgICAgICAgIHJldHVybiAiICIuam9pbihjbGVhbihrZXl3b3Jkc1s6NV0pKSBvciAiQ29u"
    "dmVyc2F0aW9uIE1lbW9yeSIKICAgICAgICByZXR1cm4gIkNvbnZlcnNhdGlvbiBNZW1vcnkiCgogICAgZGVmIF9zdW1tYXJpemUo"
    "c2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwgdXNlcl90ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICBhc3Npc3RhbnRfdGV4dDog"
    "c3RyKSAtPiBzdHI6CiAgICAgICAgdSA9IHVzZXJfdGV4dC5zdHJpcCgpWzoyMjBdCiAgICAgICAgYSA9IGFzc2lzdGFudF90ZXh0"
    "LnN0cmlwKClbOjIyMF0KICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiZHJlYW0iOiAgICAgICByZXR1cm4gZiJVc2VyIGRlc2Ny"
    "aWJlZCBhIGRyZWFtOiB7dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInRhc2siOiAgICAgICAgcmV0dXJuIGYiUmVtaW5k"
    "ZXIvdGFzazoge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpc3N1ZSI6ICAgICAgIHJldHVybiBmIlRlY2huaWNhbCBp"
    "c3N1ZToge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJyZXNvbHV0aW9uIjogIHJldHVybiBmIlNvbHV0aW9uIHJlY29y"
    "ZGVkOiB7YSBvciB1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaWRlYSI6ICAgICAgICByZXR1cm4gZiJJZGVhIGRpc2N1"
    "c3NlZDoge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJwcmVmZXJlbmNlIjogIHJldHVybiBmIlByZWZlcmVuY2Ugbm90"
    "ZWQ6IHt1fSIKICAgICAgICByZXR1cm4gZiJDb252ZXJzYXRpb246IHt1fSIKCgojIOKUgOKUgCBTRVNTSU9OIE1BTkFHRVIg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNlc3Npb25NYW5hZ2VyOgogICAgIiIiCiAgICBNYW5hZ2VzIGNvbnZlcnNh"
    "dGlvbiBzZXNzaW9ucy4KCiAgICBBdXRvLXNhdmU6IGV2ZXJ5IDEwIG1pbnV0ZXMgKEFQU2NoZWR1bGVyKSwgbWlkbmlnaHQtdG8t"
    "bWlkbmlnaHQgYm91bmRhcnkuCiAgICBGaWxlOiBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sIOKAlCBvdmVyd3JpdGVzIG9uIGVh"
    "Y2ggc2F2ZS4KICAgIEluZGV4OiBzZXNzaW9ucy9zZXNzaW9uX2luZGV4Lmpzb24g4oCUIG9uZSBlbnRyeSBwZXIgZGF5LgoKICAg"
    "IFNlc3Npb25zIGFyZSBsb2FkZWQgYXMgY29udGV4dCBpbmplY3Rpb24gKG5vdCByZWFsIG1lbW9yeSkgdW50aWwKICAgIHRoZSBT"
    "UUxpdGUvQ2hyb21hREIgc3lzdGVtIGlzIGJ1aWx0IGluIFBoYXNlIDIuCiAgICAiIiIKCiAgICBBVVRPU0FWRV9JTlRFUlZBTCA9"
    "IDEwICAgIyBtaW51dGVzCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3Nlc3Npb25zX2RpciAgPSBjZmdf"
    "cGF0aCgic2Vzc2lvbnMiKQogICAgICAgIHNlbGYuX2luZGV4X3BhdGggICAgPSBzZWxmLl9zZXNzaW9uc19kaXIgLyAic2Vzc2lv"
    "bl9pbmRleC5qc29uIgogICAgICAgIHNlbGYuX3Nlc3Npb25faWQgICAgPSBmInNlc3Npb25fe2RhdGV0aW1lLm5vdygpLnN0cmZ0"
    "aW1lKCclWSVtJWRfJUglTSVTJyl9IgogICAgICAgIHNlbGYuX2N1cnJlbnRfZGF0ZSAgPSBkYXRlLnRvZGF5KCkuaXNvZm9ybWF0"
    "KCkKICAgICAgICBzZWxmLl9tZXNzYWdlczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fbG9hZGVkX2pvdXJuYWw6IE9w"
    "dGlvbmFsW3N0cl0gPSBOb25lICAjIGRhdGUgb2YgbG9hZGVkIGpvdXJuYWwKCiAgICAjIOKUgOKUgCBDVVJSRU5UIFNFU1NJT04g"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBk"
    "ZWYgYWRkX21lc3NhZ2Uoc2VsZiwgcm9sZTogc3RyLCBjb250ZW50OiBzdHIsCiAgICAgICAgICAgICAgICAgICAgZW1vdGlvbjog"
    "c3RyID0gIiIsIHRpbWVzdGFtcDogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fbWVzc2FnZXMuYXBwZW5kKHsKICAg"
    "ICAgICAgICAgImlkIjogICAgICAgIGYibXNnX3t1dWlkLnV1aWQ0KCkuaGV4Wzo4XX0iLAogICAgICAgICAgICAidGltZXN0YW1w"
    "IjogdGltZXN0YW1wIG9yIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgInJvbGUiOiAgICAgIHJvbGUsCiAgICAgICAgICAg"
    "ICJjb250ZW50IjogICBjb250ZW50LAogICAgICAgICAgICAiZW1vdGlvbiI6ICAgZW1vdGlvbiwKICAgICAgICB9KQoKICAgIGRl"
    "ZiBnZXRfaGlzdG9yeShzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIiIgogICAgICAgIFJldHVybiBoaXN0b3J5IGluIExM"
    "TS1mcmllbmRseSBmb3JtYXQuCiAgICAgICAgW3sicm9sZSI6ICJ1c2VyInwiYXNzaXN0YW50IiwgImNvbnRlbnQiOiAiLi4uIn1d"
    "CiAgICAgICAgIiIiCiAgICAgICAgcmV0dXJuIFsKICAgICAgICAgICAgeyJyb2xlIjogbVsicm9sZSJdLCAiY29udGVudCI6IG1b"
    "ImNvbnRlbnQiXX0KICAgICAgICAgICAgZm9yIG0gaW4gc2VsZi5fbWVzc2FnZXMKICAgICAgICAgICAgaWYgbVsicm9sZSJdIGlu"
    "ICgidXNlciIsICJhc3Npc3RhbnQiKQogICAgICAgIF0KCiAgICBAcHJvcGVydHkKICAgIGRlZiBzZXNzaW9uX2lkKHNlbGYpIC0+"
    "IHN0cjoKICAgICAgICByZXR1cm4gc2VsZi5fc2Vzc2lvbl9pZAoKICAgIEBwcm9wZXJ0eQogICAgZGVmIG1lc3NhZ2VfY291bnQo"
    "c2VsZikgLT4gaW50OgogICAgICAgIHJldHVybiBsZW4oc2VsZi5fbWVzc2FnZXMpCgogICAgIyDilIDilIAgU0FWRSDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBzYXZlKHNlbGYsIGFpX2dlbmVyYXRlZF9uYW1lOiBzdHIgPSAiIikgLT4gTm9u"
    "ZToKICAgICAgICAiIiIKICAgICAgICBTYXZlIGN1cnJlbnQgc2Vzc2lvbiB0byBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sLgog"
    "ICAgICAgIE92ZXJ3cml0ZXMgdGhlIGZpbGUgZm9yIHRvZGF5IOKAlCBlYWNoIHNhdmUgaXMgYSBmdWxsIHNuYXBzaG90LgogICAg"
    "ICAgIFVwZGF0ZXMgc2Vzc2lvbl9pbmRleC5qc29uLgogICAgICAgICIiIgogICAgICAgIHRvZGF5ID0gZGF0ZS50b2RheSgpLmlz"
    "b2Zvcm1hdCgpCiAgICAgICAgb3V0X3BhdGggPSBzZWxmLl9zZXNzaW9uc19kaXIgLyBmInt0b2RheX0uanNvbmwiCgogICAgICAg"
    "ICMgV3JpdGUgYWxsIG1lc3NhZ2VzCiAgICAgICAgd3JpdGVfanNvbmwob3V0X3BhdGgsIHNlbGYuX21lc3NhZ2VzKQoKICAgICAg"
    "ICAjIFVwZGF0ZSBpbmRleAogICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAgICAgICAgZXhpc3RpbmcgPSBuZXh0"
    "KAogICAgICAgICAgICAocyBmb3IgcyBpbiBpbmRleFsic2Vzc2lvbnMiXSBpZiBzWyJkYXRlIl0gPT0gdG9kYXkpLCBOb25lCiAg"
    "ICAgICAgKQoKICAgICAgICBuYW1lID0gYWlfZ2VuZXJhdGVkX25hbWUgb3IgZXhpc3RpbmcuZ2V0KCJuYW1lIiwgIiIpIGlmIGV4"
    "aXN0aW5nIGVsc2UgIiIKICAgICAgICBpZiBub3QgbmFtZSBhbmQgc2VsZi5fbWVzc2FnZXM6CiAgICAgICAgICAgICMgQXV0by1u"
    "YW1lIGZyb20gZmlyc3QgdXNlciBtZXNzYWdlIChmaXJzdCA1IHdvcmRzKQogICAgICAgICAgICBmaXJzdF91c2VyID0gbmV4dCgK"
    "ICAgICAgICAgICAgICAgIChtWyJjb250ZW50Il0gZm9yIG0gaW4gc2VsZi5fbWVzc2FnZXMgaWYgbVsicm9sZSJdID09ICJ1c2Vy"
    "IiksCiAgICAgICAgICAgICAgICAiIgogICAgICAgICAgICApCiAgICAgICAgICAgIHdvcmRzID0gZmlyc3RfdXNlci5zcGxpdCgp"
    "Wzo1XQogICAgICAgICAgICBuYW1lICA9ICIgIi5qb2luKHdvcmRzKSBpZiB3b3JkcyBlbHNlIGYiU2Vzc2lvbiB7dG9kYXl9IgoK"
    "ICAgICAgICBlbnRyeSA9IHsKICAgICAgICAgICAgImRhdGUiOiAgICAgICAgICB0b2RheSwKICAgICAgICAgICAgInNlc3Npb25f"
    "aWQiOiAgICBzZWxmLl9zZXNzaW9uX2lkLAogICAgICAgICAgICAibmFtZSI6ICAgICAgICAgIG5hbWUsCiAgICAgICAgICAgICJt"
    "ZXNzYWdlX2NvdW50IjogbGVuKHNlbGYuX21lc3NhZ2VzKSwKICAgICAgICAgICAgImZpcnN0X21lc3NhZ2UiOiAoc2VsZi5fbWVz"
    "c2FnZXNbMF1bInRpbWVzdGFtcCJdCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2Ug"
    "IiIpLAogICAgICAgICAgICAibGFzdF9tZXNzYWdlIjogIChzZWxmLl9tZXNzYWdlc1stMV1bInRpbWVzdGFtcCJdCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAgICAgIH0KCiAgICAgICAgaWYgZXhp"
    "c3Rpbmc6CiAgICAgICAgICAgIGlkeCA9IGluZGV4WyJzZXNzaW9ucyJdLmluZGV4KGV4aXN0aW5nKQogICAgICAgICAgICBpbmRl"
    "eFsic2Vzc2lvbnMiXVtpZHhdID0gZW50cnkKICAgICAgICBlbHNlOgogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMiXS5pbnNl"
    "cnQoMCwgZW50cnkpCgogICAgICAgICMgS2VlcCBsYXN0IDM2NSBkYXlzIGluIGluZGV4CiAgICAgICAgaW5kZXhbInNlc3Npb25z"
    "Il0gPSBpbmRleFsic2Vzc2lvbnMiXVs6MzY1XQogICAgICAgIHNlbGYuX3NhdmVfaW5kZXgoaW5kZXgpCgogICAgIyDilIDilIAg"
    "TE9BRCAvIEpPVVJOQUwg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICBkZWYgbGlzdF9zZXNzaW9ucyhzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIiIlJldHVybiBh"
    "bGwgc2Vzc2lvbnMgZnJvbSBpbmRleCwgbmV3ZXN0IGZpcnN0LiIiIgogICAgICAgIHJldHVybiBzZWxmLl9sb2FkX2luZGV4KCku"
    "Z2V0KCJzZXNzaW9ucyIsIFtdKQoKICAgIGRlZiBsb2FkX3Nlc3Npb25fYXNfY29udGV4dChzZWxmLCBzZXNzaW9uX2RhdGU6IHN0"
    "cikgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIExvYWQgYSBwYXN0IHNlc3Npb24gYXMgYSBjb250ZXh0IGluamVjdGlvbiBz"
    "dHJpbmcuCiAgICAgICAgUmV0dXJucyBmb3JtYXR0ZWQgdGV4dCB0byBwcmVwZW5kIHRvIHRoZSBzeXN0ZW0gcHJvbXB0LgogICAg"
    "ICAgIFRoaXMgaXMgTk9UIHJlYWwgbWVtb3J5IOKAlCBpdCdzIGEgdGVtcG9yYXJ5IGNvbnRleHQgd2luZG93IGluamVjdGlvbgog"
    "ICAgICAgIHVudGlsIHRoZSBQaGFzZSAyIG1lbW9yeSBzeXN0ZW0gaXMgYnVpbHQuCiAgICAgICAgIiIiCiAgICAgICAgcGF0aCA9"
    "IHNlbGYuX3Nlc3Npb25zX2RpciAvIGYie3Nlc3Npb25fZGF0ZX0uanNvbmwiCiAgICAgICAgaWYgbm90IHBhdGguZXhpc3RzKCk6"
    "CiAgICAgICAgICAgIHJldHVybiAiIgoKICAgICAgICBtZXNzYWdlcyA9IHJlYWRfanNvbmwocGF0aCkKICAgICAgICBzZWxmLl9s"
    "b2FkZWRfam91cm5hbCA9IHNlc3Npb25fZGF0ZQoKICAgICAgICBsaW5lcyA9IFtmIltKT1VSTkFMIExPQURFRCDigJQge3Nlc3Np"
    "b25fZGF0ZX1dIiwKICAgICAgICAgICAgICAgICAiVGhlIGZvbGxvd2luZyBpcyBhIHJlY29yZCBvZiBhIHByaW9yIGNvbnZlcnNh"
    "dGlvbi4iLAogICAgICAgICAgICAgICAgICJVc2UgdGhpcyBhcyBjb250ZXh0IGZvciB0aGUgY3VycmVudCBzZXNzaW9uOlxuIl0K"
    "CiAgICAgICAgIyBJbmNsdWRlIHVwIHRvIGxhc3QgMzAgbWVzc2FnZXMgZnJvbSB0aGF0IHNlc3Npb24KICAgICAgICBmb3IgbXNn"
    "IGluIG1lc3NhZ2VzWy0zMDpdOgogICAgICAgICAgICByb2xlICAgID0gbXNnLmdldCgicm9sZSIsICI/IikudXBwZXIoKQogICAg"
    "ICAgICAgICBjb250ZW50ID0gbXNnLmdldCgiY29udGVudCIsICIiKVs6MzAwXQogICAgICAgICAgICB0cyAgICAgID0gbXNnLmdl"
    "dCgidGltZXN0YW1wIiwgIiIpWzoxNl0KICAgICAgICAgICAgbGluZXMuYXBwZW5kKGYiW3t0c31dIHtyb2xlfToge2NvbnRlbnR9"
    "IikKCiAgICAgICAgbGluZXMuYXBwZW5kKCJbRU5EIEpPVVJOQUxdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKGxpbmVzKQoK"
    "ICAgIGRlZiBjbGVhcl9sb2FkZWRfam91cm5hbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFsID0g"
    "Tm9uZQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGxvYWRlZF9qb3VybmFsX2RhdGUoc2VsZikgLT4gT3B0aW9uYWxbc3RyXToKICAg"
    "ICAgICByZXR1cm4gc2VsZi5fbG9hZGVkX2pvdXJuYWwKCiAgICBkZWYgcmVuYW1lX3Nlc3Npb24oc2VsZiwgc2Vzc2lvbl9kYXRl"
    "OiBzdHIsIG5ld19uYW1lOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgIiIiUmVuYW1lIGEgc2Vzc2lvbiBpbiB0aGUgaW5kZXguIFJl"
    "dHVybnMgVHJ1ZSBvbiBzdWNjZXNzLiIiIgogICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAgICAgICAgZm9yIGVu"
    "dHJ5IGluIGluZGV4WyJzZXNzaW9ucyJdOgogICAgICAgICAgICBpZiBlbnRyeVsiZGF0ZSJdID09IHNlc3Npb25fZGF0ZToKICAg"
    "ICAgICAgICAgICAgIGVudHJ5WyJuYW1lIl0gPSBuZXdfbmFtZVs6ODBdCiAgICAgICAgICAgICAgICBzZWxmLl9zYXZlX2luZGV4"
    "KGluZGV4KQogICAgICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICAjIOKUgOKUgCBJTkRF"
    "WCBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgZGVmIF9sb2FkX2luZGV4KHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgaWYgbm90IHNlbGYuX2luZGV4X3Bh"
    "dGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiB7InNlc3Npb25zIjogW119CiAgICAgICAgdHJ5OgogICAgICAgICAgICBy"
    "ZXR1cm4ganNvbi5sb2FkcygKICAgICAgICAgICAgICAgIHNlbGYuX2luZGV4X3BhdGgucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYt"
    "OCIpCiAgICAgICAgICAgICkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4geyJzZXNzaW9ucyI6"
    "IFtdfQoKICAgIGRlZiBfc2F2ZV9pbmRleChzZWxmLCBpbmRleDogZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9pbmRleF9w"
    "YXRoLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoaW5kZXgsIGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04Igog"
    "ICAgICAgICkKCgojIOKUgOKUgCBMRVNTT05TIExFQVJORUQgREFUQUJBU0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIExlc3NvbnNMZWFybmVkREI6CiAgICAi"
    "IiIKICAgIFBlcnNpc3RlbnQga25vd2xlZGdlIGJhc2UgZm9yIGNvZGUgbGVzc29ucywgcnVsZXMsIGFuZCByZXNvbHV0aW9ucy4K"
    "CiAgICBDb2x1bW5zIHBlciByZWNvcmQ6CiAgICAgICAgaWQsIGNyZWF0ZWRfYXQsIGVudmlyb25tZW50IChMU0x8UHl0aG9ufFB5"
    "U2lkZTZ8Li4uKSwgbGFuZ3VhZ2UsCiAgICAgICAgcmVmZXJlbmNlX2tleSAoc2hvcnQgdW5pcXVlIHRhZyksIHN1bW1hcnksIGZ1"
    "bGxfcnVsZSwKICAgICAgICByZXNvbHV0aW9uLCBsaW5rLCB0YWdzCgogICAgUXVlcmllZCBGSVJTVCBiZWZvcmUgYW55IGNvZGUg"
    "c2Vzc2lvbiBpbiB0aGUgcmVsZXZhbnQgbGFuZ3VhZ2UuCiAgICBUaGUgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGxpdmVzIGhlcmUu"
    "CiAgICBHcm93aW5nLCBub24tZHVwbGljYXRpbmcsIHNlYXJjaGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6"
    "CiAgICAgICAgc2VsZi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gImxlc3NvbnNfbGVhcm5lZC5qc29ubCIKCiAgICBk"
    "ZWYgYWRkKHNlbGYsIGVudmlyb25tZW50OiBzdHIsIGxhbmd1YWdlOiBzdHIsIHJlZmVyZW5jZV9rZXk6IHN0ciwKICAgICAgICAg"
    "ICAgc3VtbWFyeTogc3RyLCBmdWxsX3J1bGU6IHN0ciwgcmVzb2x1dGlvbjogc3RyID0gIiIsCiAgICAgICAgICAgIGxpbms6IHN0"
    "ciA9ICIiLCB0YWdzOiBsaXN0ID0gTm9uZSkgLT4gZGljdDoKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAg"
    "ICAgICAgICAgZiJsZXNzb25fe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICAgIGxv"
    "Y2FsX25vd19pc28oKSwKICAgICAgICAgICAgImVudmlyb25tZW50IjogICBlbnZpcm9ubWVudCwKICAgICAgICAgICAgImxhbmd1"
    "YWdlIjogICAgICBsYW5ndWFnZSwKICAgICAgICAgICAgInJlZmVyZW5jZV9rZXkiOiByZWZlcmVuY2Vfa2V5LAogICAgICAgICAg"
    "ICAic3VtbWFyeSI6ICAgICAgIHN1bW1hcnksCiAgICAgICAgICAgICJmdWxsX3J1bGUiOiAgICAgZnVsbF9ydWxlLAogICAgICAg"
    "ICAgICAicmVzb2x1dGlvbiI6ICAgIHJlc29sdXRpb24sCiAgICAgICAgICAgICJsaW5rIjogICAgICAgICAgbGluaywKICAgICAg"
    "ICAgICAgInRhZ3MiOiAgICAgICAgICB0YWdzIG9yIFtdLAogICAgICAgIH0KICAgICAgICBpZiBub3Qgc2VsZi5faXNfZHVwbGlj"
    "YXRlKHJlZmVyZW5jZV9rZXkpOgogICAgICAgICAgICBhcHBlbmRfanNvbmwoc2VsZi5fcGF0aCwgcmVjb3JkKQogICAgICAgIHJl"
    "dHVybiByZWNvcmQKCiAgICBkZWYgc2VhcmNoKHNlbGYsIHF1ZXJ5OiBzdHIgPSAiIiwgZW52aXJvbm1lbnQ6IHN0ciA9ICIiLAog"
    "ICAgICAgICAgICAgICBsYW5ndWFnZTogc3RyID0gIiIpIC0+IGxpc3RbZGljdF06CiAgICAgICAgcmVjb3JkcyA9IHJlYWRfanNv"
    "bmwoc2VsZi5fcGF0aCkKICAgICAgICByZXN1bHRzID0gW10KICAgICAgICBxID0gcXVlcnkubG93ZXIoKQogICAgICAgIGZvciBy"
    "IGluIHJlY29yZHM6CiAgICAgICAgICAgIGlmIGVudmlyb25tZW50IGFuZCByLmdldCgiZW52aXJvbm1lbnQiLCIiKS5sb3dlcigp"
    "ICE9IGVudmlyb25tZW50Lmxvd2VyKCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBsYW5ndWFnZSBh"
    "bmQgci5nZXQoImxhbmd1YWdlIiwiIikubG93ZXIoKSAhPSBsYW5ndWFnZS5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGlu"
    "dWUKICAgICAgICAgICAgaWYgcToKICAgICAgICAgICAgICAgIGhheXN0YWNrID0gIiAiLmpvaW4oWwogICAgICAgICAgICAgICAg"
    "ICAgIHIuZ2V0KCJzdW1tYXJ5IiwiIiksCiAgICAgICAgICAgICAgICAgICAgci5nZXQoImZ1bGxfcnVsZSIsIiIpLAogICAgICAg"
    "ICAgICAgICAgICAgIHIuZ2V0KCJyZWZlcmVuY2Vfa2V5IiwiIiksCiAgICAgICAgICAgICAgICAgICAgIiAiLmpvaW4oci5nZXQo"
    "InRhZ3MiLFtdKSksCiAgICAgICAgICAgICAgICBdKS5sb3dlcigpCiAgICAgICAgICAgICAgICBpZiBxIG5vdCBpbiBoYXlzdGFj"
    "azoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICByZXN1bHRzLmFwcGVuZChyKQogICAgICAgIHJldHVy"
    "biByZXN1bHRzCgogICAgZGVmIGdldF9hbGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChz"
    "ZWxmLl9wYXRoKQoKICAgIGRlZiBkZWxldGUoc2VsZiwgcmVjb3JkX2lkOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgcmVjb3JkcyA9"
    "IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBmaWx0ZXJlZCA9IFtyIGZvciByIGluIHJlY29yZHMgaWYgci5nZXQoImlk"
    "IikgIT0gcmVjb3JkX2lkXQogICAgICAgIGlmIGxlbihmaWx0ZXJlZCkgPCBsZW4ocmVjb3Jkcyk6CiAgICAgICAgICAgIHdyaXRl"
    "X2pzb25sKHNlbGYuX3BhdGgsIGZpbHRlcmVkKQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVybiBGYWxzZQoK"
    "ICAgIGRlZiBidWlsZF9jb250ZXh0X2Zvcl9sYW5ndWFnZShzZWxmLCBsYW5ndWFnZTogc3RyLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIG1heF9jaGFyczogaW50ID0gMTUwMCkgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIEJ1aWxkIGEg"
    "Y29udGV4dCBzdHJpbmcgb2YgYWxsIHJ1bGVzIGZvciBhIGdpdmVuIGxhbmd1YWdlLgogICAgICAgIEZvciBpbmplY3Rpb24gaW50"
    "byBzeXN0ZW0gcHJvbXB0IGJlZm9yZSBjb2RlIHNlc3Npb25zLgogICAgICAgICIiIgogICAgICAgIHJlY29yZHMgPSBzZWxmLnNl"
    "YXJjaChsYW5ndWFnZT1sYW5ndWFnZSkKICAgICAgICBpZiBub3QgcmVjb3JkczoKICAgICAgICAgICAgcmV0dXJuICIiCgogICAg"
    "ICAgIHBhcnRzID0gW2YiW3tsYW5ndWFnZS51cHBlcigpfSBSVUxFUyDigJQgQVBQTFkgQkVGT1JFIFdSSVRJTkcgQ09ERV0iXQog"
    "ICAgICAgIHRvdGFsID0gMAogICAgICAgIGZvciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGVudHJ5ID0gZiLigKIge3IuZ2V0"
    "KCdyZWZlcmVuY2Vfa2V5JywnJyl9OiB7ci5nZXQoJ2Z1bGxfcnVsZScsJycpfSIKICAgICAgICAgICAgaWYgdG90YWwgKyBsZW4o"
    "ZW50cnkpID4gbWF4X2NoYXJzOgogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGVudHJ5KQog"
    "ICAgICAgICAgICB0b3RhbCArPSBsZW4oZW50cnkpCgogICAgICAgIHBhcnRzLmFwcGVuZChmIltFTkQge2xhbmd1YWdlLnVwcGVy"
    "KCl9IFJVTEVTXSIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCiAgICBkZWYgX2lzX2R1cGxpY2F0ZShzZWxmLCBy"
    "ZWZlcmVuY2Vfa2V5OiBzdHIpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIGFueSgKICAgICAgICAgICAgci5nZXQoInJlZmVyZW5j"
    "ZV9rZXkiLCIiKS5sb3dlcigpID09IHJlZmVyZW5jZV9rZXkubG93ZXIoKQogICAgICAgICAgICBmb3IgciBpbiByZWFkX2pzb25s"
    "KHNlbGYuX3BhdGgpCiAgICAgICAgKQoKICAgIGRlZiBzZWVkX2xzbF9ydWxlcyhzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgog"
    "ICAgICAgIFNlZWQgdGhlIExTTCBGb3JiaWRkZW4gUnVsZXNldCBvbiBmaXJzdCBydW4gaWYgdGhlIERCIGlzIGVtcHR5LgogICAg"
    "ICAgIFRoZXNlIGFyZSB0aGUgaGFyZCBydWxlcyBmcm9tIHRoZSBwcm9qZWN0IHN0YW5kaW5nIHJ1bGVzLgogICAgICAgICIiIgog"
    "ICAgICAgIGlmIHJlYWRfanNvbmwoc2VsZi5fcGF0aCk6CiAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5IHNlZWRlZAoKICAg"
    "ICAgICBsc2xfcnVsZXMgPSBbCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19URVJOQVJZIiwKICAgICAgICAgICAgICJO"
    "byB0ZXJuYXJ5IG9wZXJhdG9ycyBpbiBMU0wiLAogICAgICAgICAgICAgIk5ldmVyIHVzZSB0aGUgdGVybmFyeSBvcGVyYXRvciAo"
    "PzopIGluIExTTCBzY3JpcHRzLiAiCiAgICAgICAgICAgICAiVXNlIGlmL2Vsc2UgYmxvY2tzIGluc3RlYWQuIExTTCBkb2VzIG5v"
    "dCBzdXBwb3J0IHRlcm5hcnkuIiwKICAgICAgICAgICAgICJSZXBsYWNlIHdpdGggaWYvZWxzZSBibG9jay4iLCAiIiksCiAgICAg"
    "ICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19GT1JFQUNIIiwKICAgICAgICAgICAgICJObyBmb3JlYWNoIGxvb3BzIGluIExTTCIs"
    "CiAgICAgICAgICAgICAiTFNMIGhhcyBubyBmb3JlYWNoIGxvb3AgY29uc3RydWN0LiBVc2UgaW50ZWdlciBpbmRleCB3aXRoICIK"
    "ICAgICAgICAgICAgICJsbEdldExpc3RMZW5ndGgoKSBhbmQgYSBmb3Igb3Igd2hpbGUgbG9vcC4iLAogICAgICAgICAgICAgIlVz"
    "ZTogZm9yKGludGVnZXIgaT0wOyBpPGxsR2V0TGlzdExlbmd0aChteUxpc3QpOyBpKyspIiwgIiIpLAogICAgICAgICAgICAoIkxT"
    "TCIsICJMU0wiLCAiTk9fR0xPQkFMX0FTU0lHTl9GUk9NX0ZVTkMiLAogICAgICAgICAgICAgIk5vIGdsb2JhbCB2YXJpYWJsZSBh"
    "c3NpZ25tZW50cyBmcm9tIGZ1bmN0aW9uIGNhbGxzIiwKICAgICAgICAgICAgICJHbG9iYWwgdmFyaWFibGUgaW5pdGlhbGl6YXRp"
    "b24gaW4gTFNMIGNhbm5vdCBjYWxsIGZ1bmN0aW9ucy4gIgogICAgICAgICAgICAgIkluaXRpYWxpemUgZ2xvYmFscyB3aXRoIGxp"
    "dGVyYWwgdmFsdWVzIG9ubHkuICIKICAgICAgICAgICAgICJBc3NpZ24gZnJvbSBmdW5jdGlvbnMgaW5zaWRlIGV2ZW50IGhhbmRs"
    "ZXJzIG9yIG90aGVyIGZ1bmN0aW9ucy4iLAogICAgICAgICAgICAgIk1vdmUgdGhlIGFzc2lnbm1lbnQgaW50byBhbiBldmVudCBo"
    "YW5kbGVyIChzdGF0ZV9lbnRyeSwgZXRjLikiLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19WT0lEX0tFWVdP"
    "UkQiLAogICAgICAgICAgICAgIk5vIHZvaWQga2V5d29yZCBpbiBMU0wiLAogICAgICAgICAgICAgIkxTTCBkb2VzIG5vdCBoYXZl"
    "IGEgdm9pZCBrZXl3b3JkIGZvciBmdW5jdGlvbiByZXR1cm4gdHlwZXMuICIKICAgICAgICAgICAgICJGdW5jdGlvbnMgdGhhdCBy"
    "ZXR1cm4gbm90aGluZyBzaW1wbHkgb21pdCB0aGUgcmV0dXJuIHR5cGUuIiwKICAgICAgICAgICAgICJSZW1vdmUgJ3ZvaWQnIGZy"
    "b20gZnVuY3Rpb24gc2lnbmF0dXJlLiAiCiAgICAgICAgICAgICAiZS5nLiBteUZ1bmMoKSB7IC4uLiB9IG5vdCB2b2lkIG15RnVu"
    "YygpIHsgLi4uIH0iLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJDT01QTEVURV9TQ1JJUFRTX09OTFkiLAogICAg"
    "ICAgICAgICAgIkFsd2F5cyBwcm92aWRlIGNvbXBsZXRlIHNjcmlwdHMsIG5ldmVyIHBhcnRpYWwgZWRpdHMiLAogICAgICAgICAg"
    "ICAgIldoZW4gd3JpdGluZyBvciBlZGl0aW5nIExTTCBzY3JpcHRzLCBhbHdheXMgb3V0cHV0IHRoZSBjb21wbGV0ZSAiCiAgICAg"
    "ICAgICAgICAic2NyaXB0LiBOZXZlciBwcm92aWRlIHBhcnRpYWwgc25pcHBldHMgb3IgJ2FkZCB0aGlzIHNlY3Rpb24nICIKICAg"
    "ICAgICAgICAgICJpbnN0cnVjdGlvbnMuIFRoZSBmdWxsIHNjcmlwdCBtdXN0IGJlIGNvcHktcGFzdGUgcmVhZHkuIiwKICAgICAg"
    "ICAgICAgICJXcml0ZSB0aGUgZW50aXJlIHNjcmlwdCBmcm9tIHRvcCB0byBib3R0b20uIiwgIiIpLAogICAgICAgIF0KCiAgICAg"
    "ICAgZm9yIGVudiwgbGFuZywgcmVmLCBzdW1tYXJ5LCBmdWxsX3J1bGUsIHJlc29sdXRpb24sIGxpbmsgaW4gbHNsX3J1bGVzOgog"
    "ICAgICAgICAgICBzZWxmLmFkZChlbnYsIGxhbmcsIHJlZiwgc3VtbWFyeSwgZnVsbF9ydWxlLCByZXNvbHV0aW9uLCBsaW5rLAog"
    "ICAgICAgICAgICAgICAgICAgICB0YWdzPVsibHNsIiwgImZvcmJpZGRlbiIsICJzdGFuZGluZ19ydWxlIl0pCgoKIyDilIDilIAg"
    "VEFTSyBNQU5BR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBUYXNrTWFuYWdlcjoKICAgICIiIgog"
    "ICAgVGFzay9yZW1pbmRlciBDUlVEIGFuZCBkdWUtZXZlbnQgZGV0ZWN0aW9uLgoKICAgIEZpbGU6IG1lbW9yaWVzL3Rhc2tzLmpz"
    "b25sCgogICAgVGFzayByZWNvcmQgZmllbGRzOgogICAgICAgIGlkLCBjcmVhdGVkX2F0LCBkdWVfYXQsIHByZV90cmlnZ2VyICgx"
    "bWluIGJlZm9yZSksCiAgICAgICAgdGV4dCwgc3RhdHVzIChwZW5kaW5nfHRyaWdnZXJlZHxzbm9vemVkfGNvbXBsZXRlZHxjYW5j"
    "ZWxsZWQpLAogICAgICAgIGFja25vd2xlZGdlZF9hdCwgcmV0cnlfY291bnQsIGxhc3RfdHJpZ2dlcmVkX2F0LCBuZXh0X3JldHJ5"
    "X2F0LAogICAgICAgIHNvdXJjZSAobG9jYWx8Z29vZ2xlKSwgZ29vZ2xlX2V2ZW50X2lkLCBzeW5jX3N0YXR1cywgbWV0YWRhdGEK"
    "CiAgICBEdWUtZXZlbnQgY3ljbGU6CiAgICAgICAgLSBQcmUtdHJpZ2dlcjogMSBtaW51dGUgYmVmb3JlIGR1ZSDihpIgYW5ub3Vu"
    "Y2UgdXBjb21pbmcKICAgICAgICAtIER1ZSB0cmlnZ2VyOiBhdCBkdWUgdGltZSDihpIgYWxlcnQgc291bmQgKyBBSSBjb21tZW50"
    "YXJ5CiAgICAgICAgLSAzLW1pbnV0ZSB3aW5kb3c6IGlmIG5vdCBhY2tub3dsZWRnZWQg4oaSIHNub296ZQogICAgICAgIC0gMTIt"
    "bWludXRlIHJldHJ5OiByZS10cmlnZ2VyCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fcGF0"
    "aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gInRhc2tzLmpzb25sIgoKICAgICMg4pSA4pSAIENSVUQg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICBkZWYgbG9hZF9hbGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICB0YXNrcyA9IHJlYWRfanNv"
    "bmwoc2VsZi5fcGF0aCkKICAgICAgICBjaGFuZ2VkID0gRmFsc2UKICAgICAgICBub3JtYWxpemVkID0gW10KICAgICAgICBmb3Ig"
    "dCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgbm90IGlzaW5zdGFuY2UodCwgZGljdCk6CiAgICAgICAgICAgICAgICBjb250aW51"
    "ZQogICAgICAgICAgICBpZiAiaWQiIG5vdCBpbiB0OgogICAgICAgICAgICAgICAgdFsiaWQiXSA9IGYidGFza197dXVpZC51dWlk"
    "NCgpLmhleFs6MTBdfSIKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICMgTm9ybWFsaXplIGZpZWxk"
    "IG5hbWVzCiAgICAgICAgICAgIGlmICJkdWVfYXQiIG5vdCBpbiB0OgogICAgICAgICAgICAgICAgdFsiZHVlX2F0Il0gPSB0Lmdl"
    "dCgiZHVlIikKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3RhdHVzIiwg"
    "ICAgICAgICAgICJwZW5kaW5nIikKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJyZXRyeV9jb3VudCIsICAgICAgMCkKICAgICAg"
    "ICAgICAgdC5zZXRkZWZhdWx0KCJhY2tub3dsZWRnZWRfYXQiLCAgTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJsYXN0"
    "X3RyaWdnZXJlZF9hdCIsTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJuZXh0X3JldHJ5X2F0IiwgICAgTm9uZSkKICAg"
    "ICAgICAgICAgdC5zZXRkZWZhdWx0KCJwcmVfYW5ub3VuY2VkIiwgICAgRmFsc2UpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgi"
    "c291cmNlIiwgICAgICAgICAgICJsb2NhbCIpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiZ29vZ2xlX2V2ZW50X2lkIiwgIE5v"
    "bmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3luY19zdGF0dXMiLCAgICAgICJwZW5kaW5nIikKICAgICAgICAgICAgdC5z"
    "ZXRkZWZhdWx0KCJtZXRhZGF0YSIsICAgICAgICAge30pCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiY3JlYXRlZF9hdCIsICAg"
    "ICAgIGxvY2FsX25vd19pc28oKSkKCiAgICAgICAgICAgICMgQ29tcHV0ZSBwcmVfdHJpZ2dlciBpZiBtaXNzaW5nCiAgICAgICAg"
    "ICAgIGlmIHQuZ2V0KCJkdWVfYXQiKSBhbmQgbm90IHQuZ2V0KCJwcmVfdHJpZ2dlciIpOgogICAgICAgICAgICAgICAgZHQgPSBw"
    "YXJzZV9pc28odFsiZHVlX2F0Il0pCiAgICAgICAgICAgICAgICBpZiBkdDoKICAgICAgICAgICAgICAgICAgICBwcmUgPSBkdCAt"
    "IHRpbWVkZWx0YShtaW51dGVzPTEpCiAgICAgICAgICAgICAgICAgICAgdFsicHJlX3RyaWdnZXIiXSA9IHByZS5pc29mb3JtYXQo"
    "dGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgICAgICBub3JtYWxp"
    "emVkLmFwcGVuZCh0KQoKICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBub3Jt"
    "YWxpemVkKQogICAgICAgIHJldHVybiBub3JtYWxpemVkCgogICAgZGVmIHNhdmVfYWxsKHNlbGYsIHRhc2tzOiBsaXN0W2RpY3Rd"
    "KSAtPiBOb25lOgogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHRhc2tzKQoKICAgIGRlZiBhZGQoc2VsZiwgdGV4dDog"
    "c3RyLCBkdWVfZHQ6IGRhdGV0aW1lLAogICAgICAgICAgICBzb3VyY2U6IHN0ciA9ICJsb2NhbCIpIC0+IGRpY3Q6CiAgICAgICAg"
    "cHJlID0gZHVlX2R0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkKICAgICAgICB0YXNrID0gewogICAgICAgICAgICAiaWQiOiAgICAg"
    "ICAgICAgICAgIGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgICAg"
    "bG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAiZHVlX2F0IjogICAgICAgICAgIGR1ZV9kdC5pc29mb3JtYXQodGltZXNwZWM9"
    "InNlY29uZHMiKSwKICAgICAgICAgICAgInByZV90cmlnZ2VyIjogICAgICBwcmUuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRz"
    "IiksCiAgICAgICAgICAgICJ0ZXh0IjogICAgICAgICAgICAgdGV4dC5zdHJpcCgpLAogICAgICAgICAgICAic3RhdHVzIjogICAg"
    "ICAgICAgICJwZW5kaW5nIiwKICAgICAgICAgICAgImFja25vd2xlZGdlZF9hdCI6ICBOb25lLAogICAgICAgICAgICAicmV0cnlf"
    "Y291bnQiOiAgICAgIDAsCiAgICAgICAgICAgICJsYXN0X3RyaWdnZXJlZF9hdCI6Tm9uZSwKICAgICAgICAgICAgIm5leHRfcmV0"
    "cnlfYXQiOiAgICBOb25lLAogICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6ICAgIEZhbHNlLAogICAgICAgICAgICAic291cmNl"
    "IjogICAgICAgICAgIHNvdXJjZSwKICAgICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6ICBOb25lLAogICAgICAgICAgICAic3lu"
    "Y19zdGF0dXMiOiAgICAgICJwZW5kaW5nIiwKICAgICAgICAgICAgIm1ldGFkYXRhIjogICAgICAgICB7fSwKICAgICAgICB9CiAg"
    "ICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICB0YXNrcy5hcHBlbmQodGFzaykKICAgICAgICBzZWxmLnNhdmVf"
    "YWxsKHRhc2tzKQogICAgICAgIHJldHVybiB0YXNrCgogICAgZGVmIHVwZGF0ZV9zdGF0dXMoc2VsZiwgdGFza19pZDogc3RyLCBz"
    "dGF0dXM6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgIGFja25vd2xlZGdlZDogYm9vbCA9IEZhbHNlKSAtPiBPcHRpb25hbFtk"
    "aWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBp"
    "ZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gPSBzdGF0dXMKICAgICAgICAgICAg"
    "ICAgIGlmIGFja25vd2xlZGdlZDoKICAgICAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19p"
    "c28oKQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAg"
    "cmV0dXJuIE5vbmUKCiAgICBkZWYgY29tcGxldGUoc2VsZiwgdGFza19pZDogc3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAg"
    "ICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQi"
    "KSA9PSB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gICAgICAgICAgPSAiY29tcGxldGVkIgogICAgICAgICAg"
    "ICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwo"
    "dGFza3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNhbmNlbChzZWxmLCB0"
    "YXNrX2lkOiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9y"
    "IHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09IHRhc2tfaWQ6CiAgICAgICAgICAgICAgICB0WyJzdGF0"
    "dXMiXSAgICAgICAgICA9ICJjYW5jZWxsZWQiCiAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25v"
    "d19pc28oKQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAg"
    "ICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY2xlYXJfY29tcGxldGVkKHNlbGYpIC0+IGludDoKICAgICAgICB0YXNrcyAgICA9IHNl"
    "bGYubG9hZF9hbGwoKQogICAgICAgIGtlcHQgICAgID0gW3QgZm9yIHQgaW4gdGFza3MKICAgICAgICAgICAgICAgICAgICBpZiB0"
    "LmdldCgic3RhdHVzIikgbm90IGluIHsiY29tcGxldGVkIiwiY2FuY2VsbGVkIn1dCiAgICAgICAgcmVtb3ZlZCAgPSBsZW4odGFz"
    "a3MpIC0gbGVuKGtlcHQpCiAgICAgICAgaWYgcmVtb3ZlZDoKICAgICAgICAgICAgc2VsZi5zYXZlX2FsbChrZXB0KQogICAgICAg"
    "IHJldHVybiByZW1vdmVkCgogICAgZGVmIHVwZGF0ZV9nb29nbGVfc3luYyhzZWxmLCB0YXNrX2lkOiBzdHIsIHN5bmNfc3RhdHVz"
    "OiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgIGdvb2dsZV9ldmVudF9pZDogc3RyID0gIiIsCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGVycm9yOiBzdHIgPSAiIikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRf"
    "YWxsKCkKICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0gdGFza19pZDoKICAgICAg"
    "ICAgICAgICAgIHRbInN5bmNfc3RhdHVzIl0gICAgPSBzeW5jX3N0YXR1cwogICAgICAgICAgICAgICAgdFsibGFzdF9zeW5jZWRf"
    "YXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgaWYgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAgICAgICAg"
    "ICAgIHRbImdvb2dsZV9ldmVudF9pZCJdID0gZ29vZ2xlX2V2ZW50X2lkCiAgICAgICAgICAgICAgICBpZiBlcnJvcjoKICAgICAg"
    "ICAgICAgICAgICAgICB0LnNldGRlZmF1bHQoIm1ldGFkYXRhIiwge30pCiAgICAgICAgICAgICAgICAgICAgdFsibWV0YWRhdGEi"
    "XVsiZ29vZ2xlX3N5bmNfZXJyb3IiXSA9IGVycm9yWzoyNDBdCiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQog"
    "ICAgICAgICAgICAgICAgcmV0dXJuIHQKICAgICAgICByZXR1cm4gTm9uZQoKICAgICMg4pSA4pSAIERVRSBFVkVOVCBERVRFQ1RJ"
    "T04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgZ2V0X2R1"
    "ZV9ldmVudHMoc2VsZikgLT4gbGlzdFt0dXBsZVtzdHIsIGRpY3RdXToKICAgICAgICAiIiIKICAgICAgICBDaGVjayBhbGwgdGFz"
    "a3MgZm9yIGR1ZS9wcmUtdHJpZ2dlci9yZXRyeSBldmVudHMuCiAgICAgICAgUmV0dXJucyBsaXN0IG9mIChldmVudF90eXBlLCB0"
    "YXNrKSB0dXBsZXMuCiAgICAgICAgZXZlbnRfdHlwZTogInByZSIgfCAiZHVlIiB8ICJyZXRyeSIKCiAgICAgICAgTW9kaWZpZXMg"
    "dGFzayBzdGF0dXNlcyBpbiBwbGFjZSBhbmQgc2F2ZXMuCiAgICAgICAgQ2FsbCBmcm9tIEFQU2NoZWR1bGVyIGV2ZXJ5IDMwIHNl"
    "Y29uZHMuCiAgICAgICAgIiIiCiAgICAgICAgbm93ICAgID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpCiAgICAgICAgdGFz"
    "a3MgID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZXZlbnRzID0gW10KICAgICAgICBjaGFuZ2VkID0gRmFsc2UKCiAgICAgICAg"
    "Zm9yIHRhc2sgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHRhc2suZ2V0KCJhY2tub3dsZWRnZWRfYXQiKToKICAgICAgICAgICAg"
    "ICAgIGNvbnRpbnVlCgogICAgICAgICAgICBzdGF0dXMgICA9IHRhc2suZ2V0KCJzdGF0dXMiLCAicGVuZGluZyIpCiAgICAgICAg"
    "ICAgIGR1ZSAgICAgID0gc2VsZi5fcGFyc2VfbG9jYWwodGFzay5nZXQoImR1ZV9hdCIpKQogICAgICAgICAgICBwcmUgICAgICA9"
    "IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJwcmVfdHJpZ2dlciIpKQogICAgICAgICAgICBuZXh0X3JldCA9IHNlbGYuX3Bh"
    "cnNlX2xvY2FsKHRhc2suZ2V0KCJuZXh0X3JldHJ5X2F0IikpCiAgICAgICAgICAgIGRlYWRsaW5lID0gc2VsZi5fcGFyc2VfbG9j"
    "YWwodGFzay5nZXQoImFsZXJ0X2RlYWRsaW5lIikpCgogICAgICAgICAgICAjIFByZS10cmlnZ2VyCiAgICAgICAgICAgIGlmIChz"
    "dGF0dXMgPT0gInBlbmRpbmciIGFuZCBwcmUgYW5kIG5vdyA+PSBwcmUKICAgICAgICAgICAgICAgICAgICBhbmQgbm90IHRhc2su"
    "Z2V0KCJwcmVfYW5ub3VuY2VkIikpOgogICAgICAgICAgICAgICAgdGFza1sicHJlX2Fubm91bmNlZCJdID0gVHJ1ZQogICAgICAg"
    "ICAgICAgICAgZXZlbnRzLmFwcGVuZCgoInByZSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICAg"
    "ICAgICAgICMgRHVlIHRyaWdnZXIKICAgICAgICAgICAgaWYgc3RhdHVzID09ICJwZW5kaW5nIiBhbmQgZHVlIGFuZCBub3cgPj0g"
    "ZHVlOgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICAgICAgID0gInRyaWdnZXJlZCIKICAgICAgICAgICAgICAg"
    "IHRhc2tbImxhc3RfdHJpZ2dlcmVkX2F0Il09IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgdGFza1siYWxlcnRfZGVh"
    "ZGxpbmUiXSAgID0gKAogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKSArIHRpbWVkZWx0YSht"
    "aW51dGVzPTMpCiAgICAgICAgICAgICAgICApLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICBl"
    "dmVudHMuYXBwZW5kKCgiZHVlIiwgdGFzaykpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAg"
    "Y29udGludWUKCiAgICAgICAgICAgICMgU25vb3plIGFmdGVyIDMtbWludXRlIHdpbmRvdwogICAgICAgICAgICBpZiBzdGF0dXMg"
    "PT0gInRyaWdnZXJlZCIgYW5kIGRlYWRsaW5lIGFuZCBub3cgPj0gZGVhZGxpbmU6CiAgICAgICAgICAgICAgICB0YXNrWyJzdGF0"
    "dXMiXSAgICAgICAgPSAic25vb3plZCIKICAgICAgICAgICAgICAgIHRhc2tbIm5leHRfcmV0cnlfYXQiXSA9ICgKICAgICAgICAg"
    "ICAgICAgICAgICBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0xMikKICAgICAgICAgICAg"
    "ICAgICkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAg"
    "ICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgIyBSZXRyeQogICAgICAgICAgICBpZiBzdGF0dXMgaW4geyJyZXRyeV9wZW5k"
    "aW5nIiwic25vb3plZCJ9IGFuZCBuZXh0X3JldCBhbmQgbm93ID49IG5leHRfcmV0OgogICAgICAgICAgICAgICAgdGFza1sic3Rh"
    "dHVzIl0gICAgICAgICAgICA9ICJ0cmlnZ2VyZWQiCiAgICAgICAgICAgICAgICB0YXNrWyJyZXRyeV9jb3VudCJdICAgICAgID0g"
    "aW50KHRhc2suZ2V0KCJyZXRyeV9jb3VudCIsMCkpICsgMQogICAgICAgICAgICAgICAgdGFza1sibGFzdF90cmlnZ2VyZWRfYXQi"
    "XSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgdGFza1siYWxlcnRfZGVhZGxpbmUiXSAgICA9ICgKICAgICAgICAg"
    "ICAgICAgICAgICBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0zKQogICAgICAgICAgICAg"
    "ICAgKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgdGFza1sibmV4dF9yZXRyeV9hdCJdICAg"
    "ICA9IE5vbmUKICAgICAgICAgICAgICAgIGV2ZW50cy5hcHBlbmQoKCJyZXRyeSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hh"
    "bmdlZCA9IFRydWUKCiAgICAgICAgaWYgY2hhbmdlZDoKICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICBy"
    "ZXR1cm4gZXZlbnRzCgogICAgZGVmIF9wYXJzZV9sb2NhbChzZWxmLCB2YWx1ZTogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06"
    "CiAgICAgICAgIiIiUGFyc2UgSVNPIHN0cmluZyB0byB0aW1lem9uZS1hd2FyZSBkYXRldGltZSBmb3IgY29tcGFyaXNvbi4iIiIK"
    "ICAgICAgICBkdCA9IHBhcnNlX2lzbyh2YWx1ZSkKICAgICAgICBpZiBkdCBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4gTm9u"
    "ZQogICAgICAgIGlmIGR0LnR6aW5mbyBpcyBOb25lOgogICAgICAgICAgICBkdCA9IGR0LmFzdGltZXpvbmUoKQogICAgICAgIHJl"
    "dHVybiBkdAoKICAgICMg4pSA4pSAIE5BVFVSQUwgTEFOR1VBR0UgUEFSU0lORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBjbGFzc2lmeV9pbnRlbnQodGV4dDogc3RyKSAtPiBkaWN0"
    "OgogICAgICAgICIiIgogICAgICAgIENsYXNzaWZ5IHVzZXIgaW5wdXQgYXMgdGFzay9yZW1pbmRlci90aW1lci9jaGF0LgogICAg"
    "ICAgIFJldHVybnMgeyJpbnRlbnQiOiBzdHIsICJjbGVhbmVkX2lucHV0Ijogc3RyfQogICAgICAgICIiIgogICAgICAgIGltcG9y"
    "dCByZQogICAgICAgICMgU3RyaXAgY29tbW9uIGludm9jYXRpb24gcHJlZml4ZXMKICAgICAgICBjbGVhbmVkID0gcmUuc3ViKAog"
    "ICAgICAgICAgICByZiJeXHMqKD86e0RFQ0tfTkFNRS5sb3dlcigpfXxoZXlccyt7REVDS19OQU1FLmxvd2VyKCl9KVxzKiw/XHMq"
    "WzpcLV0/XHMqIiwKICAgICAgICAgICAgIiIsIHRleHQsIGZsYWdzPXJlLkkKICAgICAgICApLnN0cmlwKCkKCiAgICAgICAgbG93"
    "ID0gY2xlYW5lZC5sb3dlcigpCgogICAgICAgIHRpbWVyX3BhdHMgICAgPSBbciJcYnNldCg/OlxzK2EpP1xzK3RpbWVyXGIiLCBy"
    "IlxidGltZXJccytmb3JcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICByIlxic3RhcnQoPzpccythKT9ccyt0aW1lclxiIl0K"
    "ICAgICAgICByZW1pbmRlcl9wYXRzID0gW3IiXGJyZW1pbmQgbWVcYiIsIHIiXGJzZXQoPzpccythKT9ccytyZW1pbmRlclxiIiwK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJhZGQoPzpccythKT9ccytyZW1pbmRlclxiIiwKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIHIiXGJzZXQoPzpccythbj8pP1xzK2FsYXJtXGIiLCByIlxiYWxhcm1ccytmb3JcYiJdCiAgICAgICAgdGFza19wYXRz"
    "ICAgICA9IFtyIlxiYWRkKD86XHMrYSk/XHMrdGFza1xiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJjcmVhdGUoPzpc"
    "cythKT9ccyt0YXNrXGIiLCByIlxibmV3XHMrdGFza1xiIl0KCiAgICAgICAgaW1wb3J0IHJlIGFzIF9yZQogICAgICAgIGlmIGFu"
    "eShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gdGltZXJfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9ICJ0aW1lciIKICAg"
    "ICAgICBlbGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gcmVtaW5kZXJfcGF0cyk6CiAgICAgICAgICAgIGludGVu"
    "dCA9ICJyZW1pbmRlciIKICAgICAgICBlbGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gdGFza19wYXRzKToKICAg"
    "ICAgICAgICAgaW50ZW50ID0gInRhc2siCiAgICAgICAgZWxzZToKICAgICAgICAgICAgaW50ZW50ID0gImNoYXQiCgogICAgICAg"
    "IHJldHVybiB7ImludGVudCI6IGludGVudCwgImNsZWFuZWRfaW5wdXQiOiBjbGVhbmVkfQoKICAgIEBzdGF0aWNtZXRob2QKICAg"
    "IGRlZiBwYXJzZV9kdWVfZGF0ZXRpbWUodGV4dDogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICAgICAgIiIiCiAgICAg"
    "ICAgUGFyc2UgbmF0dXJhbCBsYW5ndWFnZSB0aW1lIGV4cHJlc3Npb24gZnJvbSB0YXNrIHRleHQuCiAgICAgICAgSGFuZGxlczog"
    "ImluIDMwIG1pbnV0ZXMiLCAiYXQgM3BtIiwgInRvbW9ycm93IGF0IDlhbSIsCiAgICAgICAgICAgICAgICAgImluIDIgaG91cnMi"
    "LCAiYXQgMTU6MzAiLCBldGMuCiAgICAgICAgUmV0dXJucyBhIGRhdGV0aW1lIG9yIE5vbmUgaWYgdW5wYXJzZWFibGUuCiAgICAg"
    "ICAgIiIiCiAgICAgICAgaW1wb3J0IHJlCiAgICAgICAgbm93ICA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAgbG93ICA9IHRleHQu"
    "bG93ZXIoKS5zdHJpcCgpCgogICAgICAgICMgImluIFggbWludXRlcy9ob3Vycy9kYXlzIgogICAgICAgIG0gPSByZS5zZWFyY2go"
    "CiAgICAgICAgICAgIHIiaW5ccysoXGQrKVxzKihtaW51dGV8bWlufGhvdXJ8aHJ8ZGF5fHNlY29uZHxzZWMpIiwKICAgICAgICAg"
    "ICAgbG93CiAgICAgICAgKQogICAgICAgIGlmIG06CiAgICAgICAgICAgIG4gICAgPSBpbnQobS5ncm91cCgxKSkKICAgICAgICAg"
    "ICAgdW5pdCA9IG0uZ3JvdXAoMikKICAgICAgICAgICAgaWYgIm1pbiIgaW4gdW5pdDogIHJldHVybiBub3cgKyB0aW1lZGVsdGEo"
    "bWludXRlcz1uKQogICAgICAgICAgICBpZiAiaG91ciIgaW4gdW5pdCBvciAiaHIiIGluIHVuaXQ6IHJldHVybiBub3cgKyB0aW1l"
    "ZGVsdGEoaG91cnM9bikKICAgICAgICAgICAgaWYgImRheSIgIGluIHVuaXQ6IHJldHVybiBub3cgKyB0aW1lZGVsdGEoZGF5cz1u"
    "KQogICAgICAgICAgICBpZiAic2VjIiAgaW4gdW5pdDogcmV0dXJuIG5vdyArIHRpbWVkZWx0YShzZWNvbmRzPW4pCgogICAgICAg"
    "ICMgImF0IEhIOk1NIiBvciAiYXQgSDpNTWFtL3BtIgogICAgICAgIG0gPSByZS5zZWFyY2goCiAgICAgICAgICAgIHIiYXRccyso"
    "XGR7MSwyfSkoPzo6KFxkezJ9KSk/XHMqKGFtfHBtKT8iLAogICAgICAgICAgICBsb3cKICAgICAgICApCiAgICAgICAgaWYgbToK"
    "ICAgICAgICAgICAgaHIgID0gaW50KG0uZ3JvdXAoMSkpCiAgICAgICAgICAgIG1uICA9IGludChtLmdyb3VwKDIpKSBpZiBtLmdy"
    "b3VwKDIpIGVsc2UgMAogICAgICAgICAgICBhcG0gPSBtLmdyb3VwKDMpCiAgICAgICAgICAgIGlmIGFwbSA9PSAicG0iIGFuZCBo"
    "ciA8IDEyOiBociArPSAxMgogICAgICAgICAgICBpZiBhcG0gPT0gImFtIiBhbmQgaHIgPT0gMTI6IGhyID0gMAogICAgICAgICAg"
    "ICBkdCA9IG5vdy5yZXBsYWNlKGhvdXI9aHIsIG1pbnV0ZT1tbiwgc2Vjb25kPTAsIG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAg"
    "IGlmIGR0IDw9IG5vdzoKICAgICAgICAgICAgICAgIGR0ICs9IHRpbWVkZWx0YShkYXlzPTEpCiAgICAgICAgICAgIHJldHVybiBk"
    "dAoKICAgICAgICAjICJ0b21vcnJvdyBhdCAuLi4iICAocmVjdXJzZSBvbiB0aGUgImF0IiBwYXJ0KQogICAgICAgIGlmICJ0b21v"
    "cnJvdyIgaW4gbG93OgogICAgICAgICAgICB0b21vcnJvd190ZXh0ID0gcmUuc3ViKHIidG9tb3Jyb3ciLCAiIiwgbG93KS5zdHJp"
    "cCgpCiAgICAgICAgICAgIHJlc3VsdCA9IFRhc2tNYW5hZ2VyLnBhcnNlX2R1ZV9kYXRldGltZSh0b21vcnJvd190ZXh0KQogICAg"
    "ICAgICAgICBpZiByZXN1bHQ6CiAgICAgICAgICAgICAgICByZXR1cm4gcmVzdWx0ICsgdGltZWRlbHRhKGRheXM9MSkKCiAgICAg"
    "ICAgcmV0dXJuIE5vbmUKCgojIOKUgOKUgCBSRVFVSVJFTUVOVFMuVFhUIEdFTkVSQVRPUiDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIHdyaXRlX3JlcXVpcmVtZW50c190eHQo"
    "KSAtPiBOb25lOgogICAgIiIiCiAgICBXcml0ZSByZXF1aXJlbWVudHMudHh0IG5leHQgdG8gdGhlIGRlY2sgZmlsZSBvbiBmaXJz"
    "dCBydW4uCiAgICBIZWxwcyB1c2VycyBpbnN0YWxsIGFsbCBkZXBlbmRlbmNpZXMgd2l0aCBvbmUgcGlwIGNvbW1hbmQuCiAgICAi"
    "IiIKICAgIHJlcV9wYXRoID0gUGF0aChDRkcuZ2V0KCJiYXNlX2RpciIsIHN0cihTQ1JJUFRfRElSKSkpIC8gInJlcXVpcmVtZW50"
    "cy50eHQiCiAgICBpZiByZXFfcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4KCiAgICBjb250ZW50ID0gIiIiXAojIE1vcmdh"
    "bm5hIERlY2sg4oCUIFJlcXVpcmVkIERlcGVuZGVuY2llcwojIEluc3RhbGwgYWxsIHdpdGg6IHBpcCBpbnN0YWxsIC1yIHJlcXVp"
    "cmVtZW50cy50eHQKCiMgQ29yZSBVSQpQeVNpZGU2CgojIFNjaGVkdWxpbmcgKGlkbGUgdGltZXIsIGF1dG9zYXZlLCByZWZsZWN0"
    "aW9uIGN5Y2xlcykKYXBzY2hlZHVsZXIKCiMgTG9nZ2luZwpsb2d1cnUKCiMgU291bmQgcGxheWJhY2sgKFdBViArIE1QMykKcHln"
    "YW1lCgojIERlc2t0b3Agc2hvcnRjdXQgY3JlYXRpb24gKFdpbmRvd3Mgb25seSkKcHl3aW4zMgoKIyBTeXN0ZW0gbW9uaXRvcmlu"
    "ZyAoQ1BVLCBSQU0sIGRyaXZlcywgbmV0d29yaykKcHN1dGlsCgojIEhUVFAgcmVxdWVzdHMKcmVxdWVzdHMKCiMgR29vZ2xlIGlu"
    "dGVncmF0aW9uIChDYWxlbmRhciwgRHJpdmUsIERvY3MsIEdtYWlsKQpnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQKZ29vZ2xlLWF1"
    "dGgtb2F1dGhsaWIKZ29vZ2xlLWF1dGgKCiMg4pSA4pSAIE9wdGlvbmFsIChsb2NhbCBtb2RlbCBvbmx5KSDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBVbmNvbW1lbnQgaWYgdXNpbmcgYSBs"
    "b2NhbCBIdWdnaW5nRmFjZSBtb2RlbDoKIyB0b3JjaAojIHRyYW5zZm9ybWVycwojIGFjY2VsZXJhdGUKCiMg4pSA4pSAIE9wdGlv"
    "bmFsIChOVklESUEgR1BVIG1vbml0b3JpbmcpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAoj"
    "IFVuY29tbWVudCBpZiB5b3UgaGF2ZSBhbiBOVklESUEgR1BVOgojIHB5bnZtbAoiIiIKICAgIHJlcV9wYXRoLndyaXRlX3RleHQo"
    "Y29udGVudCwgZW5jb2Rpbmc9InV0Zi04IikKCgojIOKUgOKUgCBQQVNTIDQgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiMgTWVtb3J5LCBTZXNzaW9uLCBMZXNzb25zTGVhcm5lZCwgVGFza01hbmFnZXIgYWxsIGRlZmluZWQuCiMgTFNMIEZv"
    "cmJpZGRlbiBSdWxlc2V0IGF1dG8tc2VlZGVkIG9uIGZpcnN0IHJ1bi4KIyByZXF1aXJlbWVudHMudHh0IHdyaXR0ZW4gb24gZmly"
    "c3QgcnVuLgojCiMgTmV4dDogUGFzcyA1IOKAlCBUYWIgQ29udGVudCBDbGFzc2VzCiMgKFNMU2NhbnNUYWIsIFNMQ29tbWFuZHNU"
    "YWIsIEpvYlRyYWNrZXJUYWIsIFJlY29yZHNUYWIsCiMgIFRhc2tzVGFiLCBTZWxmVGFiLCBEaWFnbm9zdGljc1RhYikKCgojIOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgNTogVEFCIENPTlRFTlQgQ0xBU1NFUwojCiMgVGFicyBkZWZpbmVk"
    "IGhlcmU6CiMgICBTTFNjYW5zVGFiICAgICAg4oCUIGdyaW1vaXJlLWNhcmQgc3R5bGUsIHJlYnVpbHQgKERlbGV0ZSBhZGRlZCwg"
    "TW9kaWZ5IGZpeGVkLAojICAgICAgICAgICAgICAgICAgICAgcGFyc2VyIGZpeGVkLCBjb3B5LXRvLWNsaXBib2FyZCBwZXIgaXRl"
    "bSkKIyAgIFNMQ29tbWFuZHNUYWIgICDigJQgZ290aGljIHRhYmxlLCBjb3B5IGNvbW1hbmQgdG8gY2xpcGJvYXJkCiMgICBKb2JU"
    "cmFja2VyVGFiICAg4oCUIGZ1bGwgcmVidWlsZCBmcm9tIHNwZWMsIENTVi9UU1YgZXhwb3J0CiMgICBSZWNvcmRzVGFiICAgICAg"
    "4oCUIEdvb2dsZSBEcml2ZS9Eb2NzIHdvcmtzcGFjZQojICAgVGFza3NUYWIgICAgICAgIOKAlCB0YXNrIHJlZ2lzdHJ5ICsgbWlu"
    "aSBjYWxlbmRhcgojICAgU2VsZlRhYiAgICAgICAgIOKAlCBpZGxlIG5hcnJhdGl2ZSBvdXRwdXQgKyBQb0kgbGlzdAojICAgRGlh"
    "Z25vc3RpY3NUYWIgIOKAlCBsb2d1cnUgb3V0cHV0ICsgaGFyZHdhcmUgcmVwb3J0ICsgam91cm5hbCBsb2FkIG5vdGljZXMKIyAg"
    "IExlc3NvbnNUYWIgICAgICDigJQgTFNMIEZvcmJpZGRlbiBSdWxlc2V0ICsgY29kZSBsZXNzb25zIGJyb3dzZXIKIyDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZAKCmltcG9ydCByZSBhcyBfcmUKCgojIOKUgOKUgCBTSEFSRUQgR09USElDIFRBQkxFIFNUWUxFIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgX2dvdGhpY190YWJs"
    "ZV9zdHlsZSgpIC0+IHN0cjoKICAgIHJldHVybiBmIiIiCiAgICAgICAgUVRhYmxlV2lkZ2V0IHt7CiAgICAgICAgICAgIGJhY2tn"
    "cm91bmQ6IHtDX0JHMn07CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgICAgICAgICAgYm9yZGVyOiAxcHggc29saWQg"
    "e0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAgICBncmlkbGluZS1jb2xvcjoge0NfQk9SREVSfTsKICAgICAgICAgICAgZm9udC1m"
    "YW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsKICAgICAgICAgICAgZm9udC1zaXplOiAxMXB4OwogICAgICAgIH19CiAgICAgICAg"
    "UVRhYmxlV2lkZ2V0OjppdGVtOnNlbGVjdGVkIHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAg"
    "ICAgICAgICAgY29sb3I6IHtDX0dPTERfQlJJR0hUfTsKICAgICAgICB9fQogICAgICAgIFFUYWJsZVdpZGdldDo6aXRlbTphbHRl"
    "cm5hdGUge3sKICAgICAgICAgICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgICAgICB9fQogICAgICAgIFFIZWFkZXJWaWV3Ojpz"
    "ZWN0aW9uIHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0JHM307CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEfTsKICAg"
    "ICAgICAgICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAgICBwYWRkaW5nOiA0cHggNnB4Owog"
    "ICAgICAgICAgICBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOwogICAgICAgICAgICBmb250LXNpemU6IDEwcHg7CiAg"
    "ICAgICAgICAgIGZvbnQtd2VpZ2h0OiBib2xkOwogICAgICAgICAgICBsZXR0ZXItc3BhY2luZzogMXB4OwogICAgICAgIH19CiAg"
    "ICAiIiIKCmRlZiBfZ290aGljX2J0bih0ZXh0OiBzdHIsIHRvb2x0aXA6IHN0ciA9ICIiKSAtPiBRUHVzaEJ1dHRvbjoKICAgIGJ0"
    "biA9IFFQdXNoQnV0dG9uKHRleHQpCiAgICBidG4uc2V0U3R5bGVTaGVldCgKICAgICAgICBmImJhY2tncm91bmQ6IHtDX0NSSU1T"
    "T05fRElNfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgYm9yZGVy"
    "LXJhZGl1czogMnB4OyAiCiAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7"
    "ICIKICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiA0cHggMTBweDsgbGV0dGVyLXNwYWNpbmc6IDFweDsiCiAg"
    "ICApCiAgICBpZiB0b29sdGlwOgogICAgICAgIGJ0bi5zZXRUb29sVGlwKHRvb2x0aXApCiAgICByZXR1cm4gYnRuCgpkZWYgX3Nl"
    "Y3Rpb25fbGJsKHRleHQ6IHN0cikgLT4gUUxhYmVsOgogICAgbGJsID0gUUxhYmVsKHRleHQpCiAgICBsYmwuc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAg"
    "ZiJsZXR0ZXItc3BhY2luZzogMnB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICkKICAgIHJldHVybiBs"
    "YmwKCgojIOKUgOKUgCBTTCBTQ0FOUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNMU2Nh"
    "bnNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFNlY29uZCBMaWZlIGF2YXRhciBzY2FubmVyIHJlc3VsdHMgbWFuYWdlci4KICAg"
    "IFJlYnVpbHQgZnJvbSBzcGVjOgogICAgICAtIENhcmQvZ3JpbW9pcmUtZW50cnkgc3R5bGUgZGlzcGxheQogICAgICAtIEFkZCAo"
    "d2l0aCB0aW1lc3RhbXAtYXdhcmUgcGFyc2VyKQogICAgICAtIERpc3BsYXkgKGNsZWFuIGl0ZW0vY3JlYXRvciB0YWJsZSkKICAg"
    "ICAgLSBNb2RpZnkgKGVkaXQgbmFtZSwgZGVzY3JpcHRpb24sIGluZGl2aWR1YWwgaXRlbXMpCiAgICAgIC0gRGVsZXRlICh3YXMg"
    "bWlzc2luZyDigJQgbm93IHByZXNlbnQpCiAgICAgIC0gUmUtcGFyc2UgKHdhcyAnUmVmcmVzaCcg4oCUIHJlLXJ1bnMgcGFyc2Vy"
    "IG9uIHN0b3JlZCByYXcgdGV4dCkKICAgICAgLSBDb3B5LXRvLWNsaXBib2FyZCBvbiBhbnkgaXRlbQogICAgIiIiCgogICAgZGVm"
    "IF9faW5pdF9fKHNlbGYsIG1lbW9yeV9kaXI6IFBhdGgsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBh"
    "cmVudCkKICAgICAgICBzZWxmLl9wYXRoICAgID0gY2ZnX3BhdGgoInNsIikgLyAic2xfc2NhbnMuanNvbmwiCiAgICAgICAgc2Vs"
    "Zi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQ6IE9wdGlvbmFsW3N0cl0gPSBOb25l"
    "CiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQs"
    "IDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgQnV0dG9uIGJhcgogICAgICAgIGJhciA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgICA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIiwgICAgICJBZGQgYSBu"
    "ZXcgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRuX2Rpc3BsYXkgPSBfZ290aGljX2J0bigi4p2nIERpc3BsYXkiLCAiU2hvdyBzZWxl"
    "Y3RlZCBzY2FuIGRldGFpbHMiKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkgID0gX2dvdGhpY19idG4oIuKcpyBNb2RpZnkiLCAg"
    "IkVkaXQgc2VsZWN0ZWQgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSAgPSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIs"
    "ICAiRGVsZXRlIHNlbGVjdGVkIHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9yZXBhcnNlID0gX2dvdGhpY19idG4oIuKGuyBSZS1w"
    "YXJzZSIsIlJlLXBhcnNlIHJhdyB0ZXh0IG9mIHNlbGVjdGVkIHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX3Nob3dfYWRkKQogICAgICAgIHNlbGYuX2J0bl9kaXNwbGF5LmNsaWNrZWQuY29ubmVjdChzZWxmLl9zaG93"
    "X2Rpc3BsYXkpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2hvd19tb2RpZnkpCiAgICAg"
    "ICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl9yZXBh"
    "cnNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19yZXBhcnNlKQogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBzZWxm"
    "Ll9idG5fZGlzcGxheSwgc2VsZi5fYnRuX21vZGlmeSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSwgc2VsZi5f"
    "YnRuX3JlcGFyc2UpOgogICAgICAgICAgICBiYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQogICAgICAg"
    "IHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAgICAgIyBTdGFjazogbGlzdCB2aWV3IHwgYWRkIGZvcm0gfCBkaXNwbGF5IHwgbW9k"
    "aWZ5CiAgICAgICAgc2VsZi5fc3RhY2sgPSBRU3RhY2tlZFdpZGdldCgpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fc3Rh"
    "Y2ssIDEpCgogICAgICAgICMg4pSA4pSAIFBBR0UgMDogc2NhbiBsaXN0IChncmltb2lyZSBjYXJkcykg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDAgPSBRV2lk"
    "Z2V0KCkKICAgICAgICBsMCA9IFFWQm94TGF5b3V0KHAwKQogICAgICAgIGwwLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAw"
    "KQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsID0gUVNjcm9sbEFyZWEoKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFdp"
    "ZGdldFJlc2l6YWJsZShUcnVlKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7"
    "Q19CRzJ9OyBib3JkZXI6IG5vbmU7IikKICAgICAgICBzZWxmLl9jYXJkX2NvbnRhaW5lciA9IFFXaWRnZXQoKQogICAgICAgIHNl"
    "bGYuX2NhcmRfbGF5b3V0ICAgID0gUVZCb3hMYXlvdXQoc2VsZi5fY2FyZF9jb250YWluZXIpCiAgICAgICAgc2VsZi5fY2FyZF9s"
    "YXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuc2V0U3BhY2luZyg0"
    "KQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LmFkZFN0cmV0Y2goKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFdpZGdl"
    "dChzZWxmLl9jYXJkX2NvbnRhaW5lcikKICAgICAgICBsMC5hZGRXaWRnZXQoc2VsZi5fY2FyZF9zY3JvbGwpCiAgICAgICAgc2Vs"
    "Zi5fc3RhY2suYWRkV2lkZ2V0KHAwKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDE6IGFkZCBmb3JtIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAxID0gUVdpZGdldCgpCiAgICAgICAgbDEgPSBRVkJv"
    "eExheW91dChwMSkKICAgICAgICBsMS5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBsMS5zZXRTcGFjaW5n"
    "KDQpCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFNDQU4gTkFNRSAoYXV0by1kZXRlY3RlZCkiKSkKICAg"
    "ICAgICBzZWxmLl9hZGRfbmFtZSAgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4"
    "dCgiQXV0by1kZXRlY3RlZCBmcm9tIHNjYW4gdGV4dCIpCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9uYW1lKQogICAg"
    "ICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBERVNDUklQVElPTiIpKQogICAgICAgIHNlbGYuX2FkZF9kZXNjICA9"
    "IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fYWRkX2Rlc2Muc2V0TWF4aW11bUhlaWdodCg2MCkKICAgICAgICBsMS5hZGRXaWRn"
    "ZXQoc2VsZi5fYWRkX2Rlc2MpCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFJBVyBTQ0FOIFRFWFQgKHBh"
    "c3RlIGhlcmUpIikpCiAgICAgICAgc2VsZi5fYWRkX3JhdyAgID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9hZGRfcmF3LnNl"
    "dFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAgICAgIlBhc3RlIHRoZSByYXcgU2Vjb25kIExpZmUgc2NhbiBvdXRwdXQgaGVyZS5c"
    "biIKICAgICAgICAgICAgIlRpbWVzdGFtcHMgbGlrZSBbMTE6NDddIHdpbGwgYmUgdXNlZCB0byBzcGxpdCBpdGVtcyBjb3JyZWN0"
    "bHkuIgogICAgICAgICkKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX3JhdywgMSkKICAgICAgICAjIFByZXZpZXcgb2Yg"
    "cGFyc2VkIGl0ZW1zCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFBBUlNFRCBJVEVNUyBQUkVWSUVXIikp"
    "CiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcgPSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5z"
    "ZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiSXRlbSIsICJDcmVhdG9yIl0pCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaG9y"
    "aXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2Rl"
    "LlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2Rl"
    "KAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcu"
    "c2V0TWF4aW11bUhlaWdodCgxMjApCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxl"
    "X3N0eWxlKCkpCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9wcmV2aWV3KQogICAgICAgIHNlbGYuX2FkZF9yYXcudGV4"
    "dENoYW5nZWQuY29ubmVjdChzZWxmLl9wcmV2aWV3X3BhcnNlKQoKICAgICAgICBidG5zMSA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBzMSA9IF9nb3RoaWNfYnRuKCLinKYgU2F2ZSIpOyBjMSA9IF9nb3RoaWNfYnRuKCLinJcgQ2FuY2VsIikKICAgICAgICBzMS5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIGMxLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuX3N0YWNr"
    "LnNldEN1cnJlbnRJbmRleCgwKSkKICAgICAgICBidG5zMS5hZGRXaWRnZXQoczEpOyBidG5zMS5hZGRXaWRnZXQoYzEpOyBidG5z"
    "MS5hZGRTdHJldGNoKCkKICAgICAgICBsMS5hZGRMYXlvdXQoYnRuczEpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAx"
    "KQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDI6IGRpc3BsYXkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDIgPSBRV2lkZ2V0KCkKICAgICAgICBsMiA9IFFWQm94TGF5b3V0KHAyKQogICAgICAg"
    "IGwyLnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2Rpc3BfbmFtZSAgPSBRTGFiZWwoKQogICAg"
    "ICAgIHNlbGYuX2Rpc3BfbmFtZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0JSSUdIVH07IGZv"
    "bnQtc2l6ZTogMTNweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0s"
    "IHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjICA9IFFMYWJlbCgpCiAgICAgICAgc2VsZi5fZGlzcF9k"
    "ZXNjLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "Y29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAg"
    "ICAgICApCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNlbGYuX2Rpc3BfdGFi"
    "bGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIkl0ZW0iLCAiQ3JlYXRvciJdKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUu"
    "aG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVN"
    "b2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1v"
    "ZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxl"
    "LnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0Q29udGV4dE1l"
    "bnVQb2xpY3koCiAgICAgICAgICAgIFF0LkNvbnRleHRNZW51UG9saWN5LkN1c3RvbUNvbnRleHRNZW51KQogICAgICAgIHNlbGYu"
    "X2Rpc3BfdGFibGUuY3VzdG9tQ29udGV4dE1lbnVSZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5faXRlbV9jb250"
    "ZXh0X21lbnUpCgogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9kaXNwX25hbWUpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYu"
    "X2Rpc3BfZGVzYykKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fZGlzcF90YWJsZSwgMSkKCiAgICAgICAgY29weV9oaW50ID0g"
    "UUxhYmVsKCJSaWdodC1jbGljayBhbnkgaXRlbSB0byBjb3B5IGl0IHRvIGNsaXBib2FyZC4iKQogICAgICAgIGNvcHlfaGludC5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWls"
    "eToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgbDIuYWRkV2lkZ2V0KGNvcHlfaGludCkKCiAgICAgICAg"
    "YmsyID0gX2dvdGhpY19idG4oIuKXgCBCYWNrIikKICAgICAgICBiazIuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fc3Rh"
    "Y2suc2V0Q3VycmVudEluZGV4KDApKQogICAgICAgIGwyLmFkZFdpZGdldChiazIpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lk"
    "Z2V0KHAyKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDM6IG1vZGlmeSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBwMyA9IFFXaWRnZXQoKQogICAgICAgIGwzID0gUVZCb3hMYXlvdXQocDMp"
    "CiAgICAgICAgbDMuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgbDMuc2V0U3BhY2luZyg0KQogICAgICAg"
    "IGwzLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBOQU1FIikpCiAgICAgICAgc2VsZi5fbW9kX25hbWUgPSBRTGluZUVkaXQo"
    "KQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9tb2RfbmFtZSkKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLi"
    "nacgREVTQ1JJUFRJT04iKSkKICAgICAgICBzZWxmLl9tb2RfZGVzYyA9IFFMaW5lRWRpdCgpCiAgICAgICAgbDMuYWRkV2lkZ2V0"
    "KHNlbGYuX21vZF9kZXNjKQogICAgICAgIGwzLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBJVEVNUyAoZG91YmxlLWNsaWNr"
    "IHRvIGVkaXQpIikpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDIpCiAgICAgICAgc2VsZi5fbW9k"
    "X3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJJdGVtIiwgIkNyZWF0b3IiXSkKICAgICAgICBzZWxmLl9tb2RfdGFi"
    "bGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNp"
    "emVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXpl"
    "TW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX21vZF90YWJs"
    "ZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fbW9kX3RhYmxl"
    "LCAxKQoKICAgICAgICBidG5zMyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzMyA9IF9nb3RoaWNfYnRuKCLinKYgU2F2ZSIpOyBj"
    "MyA9IF9nb3RoaWNfYnRuKCLinJcgQ2FuY2VsIikKICAgICAgICBzMy5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5X3Nh"
    "dmUpCiAgICAgICAgYzMuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDApKQogICAg"
    "ICAgIGJ0bnMzLmFkZFdpZGdldChzMyk7IGJ0bnMzLmFkZFdpZGdldChjMyk7IGJ0bnMzLmFkZFN0cmV0Y2goKQogICAgICAgIGwz"
    "LmFkZExheW91dChidG5zMykKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDMpCgogICAgIyDilIDilIAgUEFSU0VSIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgQHN0YXRpY21ldGhvZAogICAgZGVmIHBhcnNlX3NjYW5fdGV4dChyYXc6IHN0cikgLT4gdHVw"
    "bGVbc3RyLCBsaXN0W2RpY3RdXToKICAgICAgICAiIiIKICAgICAgICBQYXJzZSByYXcgU0wgc2NhbiBvdXRwdXQgaW50byAoYXZh"
    "dGFyX25hbWUsIGl0ZW1zKS4KCiAgICAgICAgS0VZIEZJWDogQmVmb3JlIHNwbGl0dGluZywgaW5zZXJ0IG5ld2xpbmVzIGJlZm9y"
    "ZSBldmVyeSBbSEg6TU1dCiAgICAgICAgdGltZXN0YW1wIHNvIHNpbmdsZS1saW5lIHBhc3RlcyB3b3JrIGNvcnJlY3RseS4KCiAg"
    "ICAgICAgRXhwZWN0ZWQgZm9ybWF0OgogICAgICAgICAgICBbMTE6NDddIEF2YXRhck5hbWUncyBwdWJsaWMgYXR0YWNobWVudHM6"
    "CiAgICAgICAgICAgIFsxMTo0N10gLjogSXRlbSBOYW1lIFtBdHRhY2htZW50XSBDUkVBVE9SOiBDcmVhdG9yTmFtZSBbMTE6NDdd"
    "IC4uLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCByYXcuc3RyaXAoKToKICAgICAgICAgICAgcmV0dXJuICJVTktOT1dOIiwg"
    "W10KCiAgICAgICAgIyDilIDilIAgU3RlcCAxOiBub3JtYWxpemUg4oCUIGluc2VydCBuZXdsaW5lcyBiZWZvcmUgdGltZXN0YW1w"
    "cyDilIDilIDilIDilIDilIDilIAKICAgICAgICBub3JtYWxpemVkID0gX3JlLnN1YihyJ1xzKihcW1xkezEsMn06XGR7Mn1cXSkn"
    "LCByJ1xuXDEnLCByYXcpCiAgICAgICAgbGluZXMgPSBbbC5zdHJpcCgpIGZvciBsIGluIG5vcm1hbGl6ZWQuc3BsaXRsaW5lcygp"
    "IGlmIGwuc3RyaXAoKV0KCiAgICAgICAgIyDilIDilIAgU3RlcCAyOiBleHRyYWN0IGF2YXRhciBuYW1lIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgICAgIGF2YXRhcl9uYW1lID0gIlVOS05PV04iCiAgICAgICAgZm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAg"
    "ICAgICMgIkF2YXRhck5hbWUncyBwdWJsaWMgYXR0YWNobWVudHMiIG9yIHNpbWlsYXIKICAgICAgICAgICAgbSA9IF9yZS5zZWFy"
    "Y2goCiAgICAgICAgICAgICAgICByIihcd1tcd1xzXSs/KSdzXHMrcHVibGljXHMrYXR0YWNobWVudHMiLAogICAgICAgICAgICAg"
    "ICAgbGluZSwgX3JlLkkKICAgICAgICAgICAgKQogICAgICAgICAgICBpZiBtOgogICAgICAgICAgICAgICAgYXZhdGFyX25hbWUg"
    "PSBtLmdyb3VwKDEpLnN0cmlwKCkKICAgICAgICAgICAgICAgIGJyZWFrCgogICAgICAgICMg4pSA4pSAIFN0ZXAgMzogZXh0cmFj"
    "dCBpdGVtcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBpdGVtcyA9IFtdCiAgICAgICAg"
    "Zm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAgICAgICMgU3RyaXAgbGVhZGluZyB0aW1lc3RhbXAKICAgICAgICAgICAgY29udGVu"
    "dCA9IF9yZS5zdWIocideXFtcZHsxLDJ9OlxkezJ9XF1ccyonLCAnJywgbGluZSkuc3RyaXAoKQogICAgICAgICAgICBpZiBub3Qg"
    "Y29udGVudDoKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICMgU2tpcCBoZWFkZXIgbGluZXMKICAgICAgICAg"
    "ICAgaWYgIidzIHB1YmxpYyBhdHRhY2htZW50cyIgaW4gY29udGVudC5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGludWUK"
    "ICAgICAgICAgICAgaWYgY29udGVudC5sb3dlcigpLnN0YXJ0c3dpdGgoIm9iamVjdCIpOgogICAgICAgICAgICAgICAgY29udGlu"
    "dWUKICAgICAgICAgICAgIyBTa2lwIGRpdmlkZXIgbGluZXMg4oCUIGxpbmVzIHRoYXQgYXJlIG1vc3RseSBvbmUgcmVwZWF0ZWQg"
    "Y2hhcmFjdGVyCiAgICAgICAgICAgICMgZS5nLiDiloLiloLiloLiloLiloLiloLiloLiloLiloLiloLiloLiloIgb3Ig4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQIG9yIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ICAgICAgICBzdHJpcHBlZCA9IGNvbnRlbnQuc3RyaXAoIi46ICIpCiAgICAgICAgICAgIGlmIHN0cmlwcGVkIGFuZCBsZW4oc2V0"
    "KHN0cmlwcGVkKSkgPD0gMjoKICAgICAgICAgICAgICAgIGNvbnRpbnVlICAjIG9uZSBvciB0d28gdW5pcXVlIGNoYXJzID0gZGl2"
    "aWRlciBsaW5lCgogICAgICAgICAgICAjIFRyeSB0byBleHRyYWN0IENSRUFUT1I6IGZpZWxkCiAgICAgICAgICAgIGNyZWF0b3Ig"
    "PSAiVU5LTk9XTiIKICAgICAgICAgICAgaXRlbV9uYW1lID0gY29udGVudAoKICAgICAgICAgICAgY3JlYXRvcl9tYXRjaCA9IF9y"
    "ZS5zZWFyY2goCiAgICAgICAgICAgICAgICByJ0NSRUFUT1I6XHMqKFtcd1xzXSs/KSg/OlxzKlxbfCQpJywgY29udGVudCwgX3Jl"
    "LkkKICAgICAgICAgICAgKQogICAgICAgICAgICBpZiBjcmVhdG9yX21hdGNoOgogICAgICAgICAgICAgICAgY3JlYXRvciAgID0g"
    "Y3JlYXRvcl9tYXRjaC5ncm91cCgxKS5zdHJpcCgpCiAgICAgICAgICAgICAgICBpdGVtX25hbWUgPSBjb250ZW50WzpjcmVhdG9y"
    "X21hdGNoLnN0YXJ0KCldLnN0cmlwKCkKCiAgICAgICAgICAgICMgU3RyaXAgYXR0YWNobWVudCBwb2ludCBzdWZmaXhlcyBsaWtl"
    "IFtMZWZ0X0Zvb3RdCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IF9yZS5zdWIocidccypcW1tcd1xzX10rXF0nLCAnJywgaXRlbV9u"
    "YW1lKS5zdHJpcCgpCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IGl0ZW1fbmFtZS5zdHJpcCgiLjogIikKCiAgICAgICAgICAgIGlm"
    "IGl0ZW1fbmFtZSBhbmQgbGVuKGl0ZW1fbmFtZSkgPiAxOgogICAgICAgICAgICAgICAgaXRlbXMuYXBwZW5kKHsiaXRlbSI6IGl0"
    "ZW1fbmFtZSwgImNyZWF0b3IiOiBjcmVhdG9yfSkKCiAgICAgICAgcmV0dXJuIGF2YXRhcl9uYW1lLCBpdGVtcwoKICAgICMg4pSA"
    "4pSAIENBUkQgUkVOREVSSU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgZGVmIF9idWlsZF9jYXJkcyhzZWxmKSAtPiBOb25lOgogICAgICAgICMgQ2xlYXIgZXhpc3Rpbmcg"
    "Y2FyZHMgKGtlZXAgc3RyZXRjaCkKICAgICAgICB3aGlsZSBzZWxmLl9jYXJkX2xheW91dC5jb3VudCgpID4gMToKICAgICAgICAg"
    "ICAgaXRlbSA9IHNlbGYuX2NhcmRfbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICBpZiBpdGVtLndpZGdldCgpOgogICAgICAg"
    "ICAgICAgICAgaXRlbS53aWRnZXQoKS5kZWxldGVMYXRlcigpCgogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAg"
    "ICAgICAgICAgY2FyZCA9IHNlbGYuX21ha2VfY2FyZChyZWMpCiAgICAgICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0Lmluc2VydFdp"
    "ZGdldCgKICAgICAgICAgICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LmNvdW50KCkgLSAxLCBjYXJkCiAgICAgICAgICAgICkKCiAg"
    "ICBkZWYgX21ha2VfY2FyZChzZWxmLCByZWM6IGRpY3QpIC0+IFFXaWRnZXQ6CiAgICAgICAgY2FyZCA9IFFGcmFtZSgpCiAgICAg"
    "ICAgaXNfc2VsZWN0ZWQgPSByZWMuZ2V0KCJyZWNvcmRfaWQiKSA9PSBzZWxmLl9zZWxlY3RlZF9pZAogICAgICAgIGNhcmQuc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7JyMxYTBhMTAnIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19CRzN9"
    "OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTiBpZiBpc19zZWxlY3RlZCBlbHNlIENfQk9SREVS"
    "fTsgIgogICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsgcGFkZGluZzogMnB4OyIKICAgICAgICApCiAgICAgICAgbGF5"
    "b3V0ID0gUUhCb3hMYXlvdXQoY2FyZCkKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDgsIDYsIDgsIDYpCgogICAg"
    "ICAgIG5hbWVfbGJsID0gUUxhYmVsKHJlYy5nZXQoIm5hbWUiLCAiVU5LTk9XTiIpKQogICAgICAgIG5hbWVfbGJsLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTERfQlJJR0hUIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19HT0xEfTsgIgog"
    "ICAgICAgICAgICBmImZvbnQtc2l6ZTogMTFweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwg"
    "c2VyaWY7IgogICAgICAgICkKCiAgICAgICAgY291bnQgPSBsZW4ocmVjLmdldCgiaXRlbXMiLCBbXSkpCiAgICAgICAgY291bnRf"
    "bGJsID0gUUxhYmVsKGYie2NvdW50fSBpdGVtcyIpCiAgICAgICAgY291bnRfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "IGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7Igog"
    "ICAgICAgICkKCiAgICAgICAgZGF0ZV9sYmwgPSBRTGFiZWwocmVjLmdldCgiY3JlYXRlZF9hdCIsICIiKVs6MTBdKQogICAgICAg"
    "IGRhdGVfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7"
    "IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChuYW1l"
    "X2xibCkKICAgICAgICBsYXlvdXQuYWRkU3RyZXRjaCgpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChjb3VudF9sYmwpCiAgICAg"
    "ICAgbGF5b3V0LmFkZFNwYWNpbmcoMTIpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChkYXRlX2xibCkKCiAgICAgICAgIyBDbGlj"
    "ayB0byBzZWxlY3QKICAgICAgICByZWNfaWQgPSByZWMuZ2V0KCJyZWNvcmRfaWQiLCAiIikKICAgICAgICBjYXJkLm1vdXNlUHJl"
    "c3NFdmVudCA9IGxhbWJkYSBlLCByaWQ9cmVjX2lkOiBzZWxmLl9zZWxlY3RfY2FyZChyaWQpCiAgICAgICAgcmV0dXJuIGNhcmQK"
    "CiAgICBkZWYgX3NlbGVjdF9jYXJkKHNlbGYsIHJlY29yZF9pZDogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3NlbGVjdGVk"
    "X2lkID0gcmVjb3JkX2lkCiAgICAgICAgc2VsZi5fYnVpbGRfY2FyZHMoKSAgIyBSZWJ1aWxkIHRvIHNob3cgc2VsZWN0aW9uIGhp"
    "Z2hsaWdodAoKICAgIGRlZiBfc2VsZWN0ZWRfcmVjb3JkKHNlbGYpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHJldHVybiBu"
    "ZXh0KAogICAgICAgICAgICAociBmb3IgciBpbiBzZWxmLl9yZWNvcmRzCiAgICAgICAgICAgICBpZiByLmdldCgicmVjb3JkX2lk"
    "IikgPT0gc2VsZi5fc2VsZWN0ZWRfaWQpLAogICAgICAgICAgICBOb25lCiAgICAgICAgKQoKICAgICMg4pSA4pSAIEFDVElPTlMg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFk"
    "X2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgIyBFbnN1cmUgcmVjb3JkX2lkIGZpZWxkIGV4aXN0cwogICAgICAgIGNoYW5nZWQg"
    "PSBGYWxzZQogICAgICAgIGZvciByIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGlmIG5vdCByLmdldCgicmVjb3JkX2lk"
    "Iik6CiAgICAgICAgICAgICAgICByWyJyZWNvcmRfaWQiXSA9IHIuZ2V0KCJpZCIpIG9yIHN0cih1dWlkLnV1aWQ0KCkpCiAgICAg"
    "ICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYu"
    "X3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5fYnVpbGRfY2FyZHMoKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1"
    "cnJlbnRJbmRleCgwKQoKICAgIGRlZiBfcHJldmlld19wYXJzZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJhdyA9IHNlbGYuX2Fk"
    "ZF9yYXcudG9QbGFpblRleHQoKQogICAgICAgIG5hbWUsIGl0ZW1zID0gc2VsZi5wYXJzZV9zY2FuX3RleHQocmF3KQogICAgICAg"
    "IHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dChuYW1lKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldFJvd0Nv"
    "dW50KDApCiAgICAgICAgZm9yIGl0IGluIGl0ZW1zWzoyMF06ICAjIHByZXZpZXcgZmlyc3QgMjAKICAgICAgICAgICAgciA9IHNl"
    "bGYuX2FkZF9wcmV2aWV3LnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaW5zZXJ0Um93KHIpCiAgICAg"
    "ICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldEl0ZW0ociwgMCwgUVRhYmxlV2lkZ2V0SXRlbShpdFsiaXRlbSJdKSkKICAgICAg"
    "ICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0SXRlbShyLCAxLCBRVGFibGVXaWRnZXRJdGVtKGl0WyJjcmVhdG9yIl0pKQoKICAg"
    "IGRlZiBfc2hvd19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hZGRfbmFtZS5jbGVhcigpCiAgICAgICAgc2VsZi5f"
    "YWRkX25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJBdXRvLWRldGVjdGVkIGZyb20gc2NhbiB0ZXh0IikKICAgICAgICBzZWxmLl9h"
    "ZGRfZGVzYy5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX3Jhdy5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0"
    "Um93Q291bnQoMCkKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMSkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHJhdyAgPSBzZWxmLl9hZGRfcmF3LnRvUGxhaW5UZXh0KCkKICAgICAgICBuYW1lLCBpdGVtcyA9IHNl"
    "bGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICBvdmVycmlkZV9uYW1lID0gc2VsZi5fYWRkX25hbWUudGV4dCgpLnN0cmlw"
    "KCkKICAgICAgICBub3cgID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICByZWNvcmQgPSB7"
    "CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAicmVjb3JkX2lkIjogICBz"
    "dHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgIm5hbWUiOiAgICAgICAgb3ZlcnJpZGVfbmFtZSBvciBuYW1lLAogICAgICAg"
    "ICAgICAiZGVzY3JpcHRpb24iOiBzZWxmLl9hZGRfZGVzYy50b1BsYWluVGV4dCgpWzoyNDRdLAogICAgICAgICAgICAiaXRlbXMi"
    "OiAgICAgICBpdGVtcywKICAgICAgICAgICAgInJhd190ZXh0IjogICAgcmF3LAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICBu"
    "b3csCiAgICAgICAgICAgICJ1cGRhdGVkX2F0IjogIG5vdywKICAgICAgICB9CiAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQo"
    "cmVjb3JkKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5fc2VsZWN0"
    "ZWRfaWQgPSByZWNvcmRbInJlY29yZF9pZCJdCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3Nob3dfZGlzcGxheShz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAg"
    "ICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gZGlzcGxheS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9k"
    "aXNwX25hbWUuc2V0VGV4dChmIuKdpyB7cmVjLmdldCgnbmFtZScsJycpfSIpCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFRl"
    "eHQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAg"
    "ICAgZm9yIGl0IGluIHJlYy5nZXQoIml0ZW1zIixbXSk6CiAgICAgICAgICAgIHIgPSBzZWxmLl9kaXNwX3RhYmxlLnJvd0NvdW50"
    "KCkKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5z"
    "ZXRJdGVtKHIsIDAsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiaXRlbSIsIiIpKSkKICAgICAgICAg"
    "ICAgc2VsZi5fZGlzcF90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgi"
    "Y3JlYXRvciIsIlVOS05PV04iKSkpCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDIpCgogICAgZGVmIF9pdGVt"
    "X2NvbnRleHRfbWVudShzZWxmLCBwb3MpIC0+IE5vbmU6CiAgICAgICAgaWR4ID0gc2VsZi5fZGlzcF90YWJsZS5pbmRleEF0KHBv"
    "cykKICAgICAgICBpZiBub3QgaWR4LmlzVmFsaWQoKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaXRlbV90ZXh0ICA9IChz"
    "ZWxmLl9kaXNwX3RhYmxlLml0ZW0oaWR4LnJvdygpLCAwKSBvcgogICAgICAgICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRl"
    "bSgiIikpLnRleHQoKQogICAgICAgIGNyZWF0b3IgICAgPSAoc2VsZi5fZGlzcF90YWJsZS5pdGVtKGlkeC5yb3coKSwgMSkgb3IK"
    "ICAgICAgICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICBmcm9tIFB5U2lkZTYuUXRX"
    "aWRnZXRzIGltcG9ydCBRTWVudQogICAgICAgIG1lbnUgPSBRTWVudShzZWxmKQogICAgICAgIG1lbnUuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6"
    "IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IgogICAgICAgICkKICAgICAgICBhX2l0ZW0gICAgPSBtZW51LmFkZEFjdGlvbigi"
    "Q29weSBJdGVtIE5hbWUiKQogICAgICAgIGFfY3JlYXRvciA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5IENyZWF0b3IiKQogICAgICAg"
    "IGFfYm90aCAgICA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5IEJvdGgiKQogICAgICAgIGFjdGlvbiA9IG1lbnUuZXhlYyhzZWxmLl9k"
    "aXNwX3RhYmxlLnZpZXdwb3J0KCkubWFwVG9HbG9iYWwocG9zKSkKICAgICAgICBjYiA9IFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQo"
    "KQogICAgICAgIGlmIGFjdGlvbiA9PSBhX2l0ZW06ICAgIGNiLnNldFRleHQoaXRlbV90ZXh0KQogICAgICAgIGVsaWYgYWN0aW9u"
    "ID09IGFfY3JlYXRvcjogY2Iuc2V0VGV4dChjcmVhdG9yKQogICAgICAgIGVsaWYgYWN0aW9uID09IGFfYm90aDogIGNiLnNldFRl"
    "eHQoZiJ7aXRlbV90ZXh0fSDigJQge2NyZWF0b3J9IikKCiAgICBkZWYgX3Nob3dfbW9kaWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAgICBRTWVzc2FnZUJv"
    "eC5pbmZvcm1hdGlvbihzZWxmLCAiU0wgU2NhbnMiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiU2VsZWN0"
    "IGEgc2NhbiB0byBtb2RpZnkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fbW9kX25hbWUuc2V0VGV4dChyZWMu"
    "Z2V0KCJuYW1lIiwiIikpCiAgICAgICAgc2VsZi5fbW9kX2Rlc2Muc2V0VGV4dChyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpKQog"
    "ICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiByZWMuZ2V0KCJpdGVtcyIsW10p"
    "OgogICAgICAgICAgICByID0gc2VsZi5fbW9kX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmlu"
    "c2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxl"
    "V2lkZ2V0SXRlbShpdC5nZXQoIml0ZW0iLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRJdGVtKHIsIDEsCiAg"
    "ICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiY3JlYXRvciIsIlVOS05PV04iKSkpCiAgICAgICAgc2VsZi5f"
    "c3RhY2suc2V0Q3VycmVudEluZGV4KDMpCgogICAgZGVmIF9kb19tb2RpZnlfc2F2ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJl"
    "YyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAg"
    "cmVjWyJuYW1lIl0gICAgICAgID0gc2VsZi5fbW9kX25hbWUudGV4dCgpLnN0cmlwKCkgb3IgIlVOS05PV04iCiAgICAgICAgcmVj"
    "WyJkZXNjcmlwdGlvbiJdID0gc2VsZi5fbW9kX2Rlc2MudGV4dCgpWzoyNDRdCiAgICAgICAgaXRlbXMgPSBbXQogICAgICAgIGZv"
    "ciBpIGluIHJhbmdlKHNlbGYuX21vZF90YWJsZS5yb3dDb3VudCgpKToKICAgICAgICAgICAgaXQgID0gKHNlbGYuX21vZF90YWJs"
    "ZS5pdGVtKGksMCkgb3IgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAgICAgICBjciAgPSAoc2VsZi5fbW9kX3Rh"
    "YmxlLml0ZW0oaSwxKSBvciBRVGFibGVXaWRnZXRJdGVtKCIiKSkudGV4dCgpCiAgICAgICAgICAgIGl0ZW1zLmFwcGVuZCh7Iml0"
    "ZW0iOiBpdC5zdHJpcCgpIG9yICJVTktOT1dOIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAiY3JlYXRvciI6IGNyLnN0cmlw"
    "KCkgb3IgIlVOS05PV04ifSkKICAgICAgICByZWNbIml0ZW1zIl0gICAgICA9IGl0ZW1zCiAgICAgICAgcmVjWyJ1cGRhdGVkX2F0"
    "Il0gPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgs"
    "IHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3Nh"
    "Z2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNl"
    "bGVjdCBhIHNjYW4gdG8gZGVsZXRlLiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5hbWUgPSByZWMuZ2V0KCJuYW1lIiwi"
    "dGhpcyBzY2FuIikKICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVsZXRl"
    "IFNjYW4iLAogICAgICAgICAgICBmIkRlbGV0ZSAne25hbWV9Jz8gVGhpcyBjYW5ub3QgYmUgdW5kb25lLiIsCiAgICAgICAgICAg"
    "IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgKQog"
    "ICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAgc2VsZi5fcmVjb3Jk"
    "cyA9IFtyIGZvciByIGluIHNlbGYuX3JlY29yZHMKICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiByLmdldCgicmVjb3Jk"
    "X2lkIikgIT0gc2VsZi5fc2VsZWN0ZWRfaWRdCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29y"
    "ZHMpCiAgICAgICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkID0gTm9uZQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRl"
    "ZiBfZG9fcmVwYXJzZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAg"
    "aWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gcmUtcGFyc2UuIikKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgcmF3ID0gcmVjLmdldCgicmF3X3RleHQiLCIiKQogICAgICAgIGlmIG5vdCByYXc6CiAgICAgICAgICAgIFFNZXNz"
    "YWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJSZS1wYXJzZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJO"
    "byByYXcgdGV4dCBzdG9yZWQgZm9yIHRoaXMgc2Nhbi4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBuYW1lLCBpdGVtcyA9"
    "IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICByZWNbIml0ZW1zIl0gICAgICA9IGl0ZW1zCiAgICAgICAgcmVjWyJu"
    "YW1lIl0gICAgICAgPSByZWNbIm5hbWUiXSBvciBuYW1lCiAgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3co"
    "dGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAg"
    "ICAgICAgc2VsZi5yZWZyZXNoKCkKICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiUmUtcGFyc2VkIiwKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIkZvdW5kIHtsZW4oaXRlbXMpfSBpdGVtcy4iKQoKCiMg4pSA4pSAIFNMIENP"
    "TU1BTkRTIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU0xDb21tYW5kc1RhYihRV2lkZ2V0KToKICAgICIi"
    "IgogICAgU2Vjb25kIExpZmUgY29tbWFuZCByZWZlcmVuY2UgdGFibGUuCiAgICBHb3RoaWMgdGFibGUgc3R5bGluZy4gQ29weSBj"
    "b21tYW5kIHRvIGNsaXBib2FyZCBidXR0b24gcGVyIHJvdy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9"
    "Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAgICA9IGNmZ19wYXRoKCJz"
    "bCIpIC8gInNsX2NvbW1hbmRzLmpzb25sIgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNl"
    "bGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQog"
    "ICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2Fk"
    "ZCAgICA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIikKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5ID0gX2dvdGhpY19idG4oIuKcpyBN"
    "b2RpZnkiKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgPSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIpCiAgICAgICAgc2VsZi5f"
    "YnRuX2NvcHkgICA9IF9nb3RoaWNfYnRuKCLip4kgQ29weSBDb21tYW5kIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJDb3B5IHNlbGVjdGVkIGNvbW1hbmQgdG8gY2xpcGJvYXJkIikKICAgICAgICBzZWxmLl9idG5fcmVmcmVzaD0g"
    "X2dvdGhpY19idG4oIuKGuyBSZWZyZXNoIikKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19h"
    "ZGQpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5KQogICAgICAgIHNlbGYu"
    "X2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fY29weS5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fY29weV9jb21tYW5kKQogICAgICAgIHNlbGYuX2J0bl9yZWZyZXNoLmNsaWNrZWQuY29ubmVjdChzZWxm"
    "LnJlZnJlc2gpCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9tb2RpZnksIHNlbGYuX2J0bl9kZWxl"
    "dGUsCiAgICAgICAgICAgICAgICAgIHNlbGYuX2J0bl9jb3B5LCBzZWxmLl9idG5fcmVmcmVzaCk6CiAgICAgICAgICAgIGJhci5h"
    "ZGRXaWRnZXQoYikKICAgICAgICBiYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYmFyKQoKICAgICAgICBz"
    "ZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJl"
    "bHMoWyJDb21tYW5kIiwgIkRlc2NyaXB0aW9uIl0pCiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNl"
    "Y3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2Vs"
    "Zi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmll"
    "dy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAgICAgICAg"
    "IFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0"
    "ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5"
    "bGUoKSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90YWJsZSwgMSkKCiAgICAgICAgaGludCA9IFFMYWJlbCgKICAgICAg"
    "ICAgICAgIlNlbGVjdCBhIHJvdyBhbmQgY2xpY2sg4qeJIENvcHkgQ29tbWFuZCB0byBjb3B5IGp1c3QgdGhlIGNvbW1hbmQgdGV4"
    "dC4iCiAgICAgICAgKQogICAgICAgIGhpbnQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19"
    "OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJvb3Qu"
    "YWRkV2lkZ2V0KGhpbnQpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVh"
    "ZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBz"
    "ZWxmLl9yZWNvcmRzOgogICAgICAgICAgICByID0gc2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJs"
    "ZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxl"
    "V2lkZ2V0SXRlbShyZWMuZ2V0KCJjb21tYW5kIiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDEsCiAg"
    "ICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpKQoKICAgIGRlZiBfY29weV9j"
    "b21tYW5kKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgcm93"
    "IDwgMDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaXRlbSA9IHNlbGYuX3RhYmxlLml0ZW0ocm93LCAwKQogICAgICAgIGlm"
    "IGl0ZW06CiAgICAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KGl0ZW0udGV4dCgpKQoKICAgIGRlZiBf"
    "ZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRs"
    "ZSgiQWRkIENvbW1hbmQiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtD"
    "X0dPTER9OyIpCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKICAgICAgICBjbWQgID0gUUxpbmVFZGl0KCk7IGRlc2Mg"
    "PSBRTGluZUVkaXQoKQogICAgICAgIGZvcm0uYWRkUm93KCJDb21tYW5kOiIsIGNtZCkKICAgICAgICBmb3JtLmFkZFJvdygiRGVz"
    "Y3JpcHRpb246IiwgZGVzYykKICAgICAgICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNh"
    "dmUiKTsgY3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4"
    "LmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQoY3gp"
    "CiAgICAgICAgZm9ybS5hZGRSb3coYnRucykKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2Nl"
    "cHRlZDoKICAgICAgICAgICAgbm93ID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAg"
    "cmVjID0gewogICAgICAgICAgICAgICAgImlkIjogICAgICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICAgICAi"
    "Y29tbWFuZCI6ICAgICBjbWQudGV4dCgpLnN0cmlwKClbOjI0NF0sCiAgICAgICAgICAgICAgICAiZGVzY3JpcHRpb24iOiBkZXNj"
    "LnRleHQoKS5zdHJpcCgpWzoyNDRdLAogICAgICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgbm93LCAidXBkYXRlZF9hdCI6IG5v"
    "dywKICAgICAgICAgICAgfQogICAgICAgICAgICBpZiByZWNbImNvbW1hbmQiXToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29y"
    "ZHMuYXBwZW5kKHJlYykKICAgICAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAg"
    "ICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fbW9kaWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0g"
    "c2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgcm93IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuX3JlY29yZHMpOgog"
    "ICAgICAgICAgICByZXR1cm4KICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICBkbGcgPSBRRGlhbG9nKHNl"
    "bGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJNb2RpZnkgQ29tbWFuZCIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQo"
    "ZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQog"
    "ICAgICAgIGNtZCAgPSBRTGluZUVkaXQocmVjLmdldCgiY29tbWFuZCIsIiIpKQogICAgICAgIGRlc2MgPSBRTGluZUVkaXQocmVj"
    "LmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBmb3JtLmFkZFJvdygiQ29tbWFuZDoiLCBjbWQpCiAgICAgICAgZm9ybS5h"
    "ZGRSb3coIkRlc2NyaXB0aW9uOiIsIGRlc2MpCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3Ro"
    "aWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5h"
    "Y2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRk"
    "V2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxv"
    "Z0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHJlY1siY29tbWFuZCJdICAgICA9IGNtZC50ZXh0KCkuc3RyaXAoKVs6MjQ0XQog"
    "ICAgICAgICAgICByZWNbImRlc2NyaXB0aW9uIl0gPSBkZXNjLnRleHQoKS5zdHJpcCgpWzoyNDRdCiAgICAgICAgICAgIHJlY1si"
    "dXBkYXRlZF9hdCJdICA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgIHdyaXRlX2pz"
    "b25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxl"
    "dGUoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiByb3cgPCAw"
    "IG9yIHJvdyA+PSBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGNtZCA9IHNlbGYuX3JlY29y"
    "ZHNbcm93XS5nZXQoImNvbW1hbmQiLCJ0aGlzIGNvbW1hbmQiKQogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24o"
    "CiAgICAgICAgICAgIHNlbGYsICJEZWxldGUiLCBmIkRlbGV0ZSAne2NtZH0nPyIsCiAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0"
    "YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgKQogICAgICAgIGlmIHJlcGx5"
    "ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5wb3Aocm93KQogICAg"
    "ICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoK"
    "CiMg4pSA4pSAIEpPQiBUUkFDS0VSIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSm9iVHJhY2tlclRhYihR"
    "V2lkZ2V0KToKICAgICIiIgogICAgSm9iIGFwcGxpY2F0aW9uIHRyYWNraW5nLiBGdWxsIHJlYnVpbGQgZnJvbSBzcGVjLgogICAg"
    "RmllbGRzOiBDb21wYW55LCBKb2IgVGl0bGUsIERhdGUgQXBwbGllZCwgTGluaywgU3RhdHVzLCBOb3Rlcy4KICAgIE11bHRpLXNl"
    "bGVjdCBoaWRlL3VuaGlkZS9kZWxldGUuIENTViBhbmQgVFNWIGV4cG9ydC4KICAgIEhpZGRlbiByb3dzID0gY29tcGxldGVkL3Jl"
    "amVjdGVkIOKAlCBzdGlsbCBzdG9yZWQsIGp1c3Qgbm90IHNob3duLgogICAgIiIiCgogICAgQ09MVU1OUyA9IFsiQ29tcGFueSIs"
    "ICJKb2IgVGl0bGUiLCAiRGF0ZSBBcHBsaWVkIiwKICAgICAgICAgICAgICAgIkxpbmsiLCAiU3RhdHVzIiwgIk5vdGVzIl0KCiAg"
    "ICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAg"
    "IHNlbGYuX3BhdGggICAgPSBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJqb2JfdHJhY2tlci5qc29ubCIKICAgICAgICBzZWxmLl9y"
    "ZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zaG93X2hpZGRlbiA9IEZhbHNlCiAgICAgICAgc2VsZi5fc2V0"
    "dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJv"
    "b3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAg"
    "cm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGJhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgID0g"
    "X2dvdGhpY19idG4oIkFkZCIpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeSA9IF9nb3RoaWNfYnRuKCJNb2RpZnkiKQogICAgICAg"
    "IHNlbGYuX2J0bl9oaWRlICAgPSBfZ290aGljX2J0bigiQXJjaGl2ZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAiTWFyayBzZWxlY3RlZCBhcyBjb21wbGV0ZWQvcmVqZWN0ZWQiKQogICAgICAgIHNlbGYuX2J0bl91bmhpZGUgPSBf"
    "Z290aGljX2J0bigiUmVzdG9yZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiUmVzdG9yZSBhcmNo"
    "aXZlZCBhcHBsaWNhdGlvbnMiKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgPSBfZ290aGljX2J0bigiRGVsZXRlIikKICAgICAg"
    "ICBzZWxmLl9idG5fdG9nZ2xlID0gX2dvdGhpY19idG4oIlNob3cgQXJjaGl2ZWQiKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQg"
    "PSBfZ290aGljX2J0bigiRXhwb3J0IikKCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9tb2RpZnks"
    "IHNlbGYuX2J0bl9oaWRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fdW5oaWRlLCBzZWxmLl9idG5fZGVsZXRlLAogICAg"
    "ICAgICAgICAgICAgICBzZWxmLl9idG5fdG9nZ2xlLCBzZWxmLl9idG5fZXhwb3J0KToKICAgICAgICAgICAgYi5zZXRNaW5pbXVt"
    "V2lkdGgoNzApCiAgICAgICAgICAgIGIuc2V0TWluaW11bUhlaWdodCgyNikKICAgICAgICAgICAgYmFyLmFkZFdpZGdldChiKQoK"
    "ICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX21vZGlm"
    "eS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9oaWRlLmNsaWNrZWQuY29ubmVjdChz"
    "ZWxmLl9kb19oaWRlKQogICAgICAgIHNlbGYuX2J0bl91bmhpZGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX3VuaGlkZSkKICAg"
    "ICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX3Rv"
    "Z2dsZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2hpZGRlbikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0LmNsaWNrZWQu"
    "Y29ubmVjdChzZWxmLl9kb19leHBvcnQpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJh"
    "cikKCiAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgbGVuKHNlbGYuQ09MVU1OUykpCiAgICAgICAgc2VsZi5f"
    "dGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhzZWxmLkNPTFVNTlMpCiAgICAgICAgaGggPSBzZWxmLl90YWJsZS5ob3Jp"
    "em9udGFsSGVhZGVyKCkKICAgICAgICAjIENvbXBhbnkgYW5kIEpvYiBUaXRsZSBzdHJldGNoCiAgICAgICAgaGguc2V0U2VjdGlv"
    "blJlc2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVN"
    "b2RlKDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICAjIERhdGUgQXBwbGllZCDigJQgZml4ZWQgcmVh"
    "ZGFibGUgd2lkdGgKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVk"
    "KQogICAgICAgIHNlbGYuX3RhYmxlLnNldENvbHVtbldpZHRoKDIsIDEwMCkKICAgICAgICAjIExpbmsgc3RyZXRjaGVzCiAgICAg"
    "ICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMywgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgICMgU3Rh"
    "dHVzIOKAlCBmaXhlZCB3aWR0aAogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDQsIFFIZWFkZXJWaWV3LlJlc2l6ZU1v"
    "ZGUuRml4ZWQpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Q29sdW1uV2lkdGgoNCwgODApCiAgICAgICAgIyBOb3RlcyBzdHJldGNo"
    "ZXMKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSg1LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCgogICAg"
    "ICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rp"
    "b25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbk1vZGUoCiAgICAgICAgICAgIFFB"
    "YnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbk1vZGUuRXh0ZW5kZWRTZWxlY3Rpb24pCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0"
    "ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5"
    "bGUoKSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90YWJsZSwgMSkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93"
    "Q291bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGhpZGRlbiA9IGJvb2wocmVjLmdl"
    "dCgiaGlkZGVuIiwgRmFsc2UpKQogICAgICAgICAgICBpZiBoaWRkZW4gYW5kIG5vdCBzZWxmLl9zaG93X2hpZGRlbjoKICAgICAg"
    "ICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYu"
    "X3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzdGF0dXMgPSAiQXJjaGl2ZWQiIGlmIGhpZGRlbiBlbHNlIHJlYy5nZXQo"
    "InN0YXR1cyIsIkFjdGl2ZSIpCiAgICAgICAgICAgIHZhbHMgPSBbCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJjb21wYW55Iiwi"
    "IiksCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJqb2JfdGl0bGUiLCIiKSwKICAgICAgICAgICAgICAgIHJlYy5nZXQoImRhdGVf"
    "YXBwbGllZCIsIiIpLAogICAgICAgICAgICAgICAgcmVjLmdldCgibGluayIsIiIpLAogICAgICAgICAgICAgICAgc3RhdHVzLAog"
    "ICAgICAgICAgICAgICAgcmVjLmdldCgibm90ZXMiLCIiKSwKICAgICAgICAgICAgXQogICAgICAgICAgICBmb3IgYywgdiBpbiBl"
    "bnVtZXJhdGUodmFscyk6CiAgICAgICAgICAgICAgICBpdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShzdHIodikpCiAgICAgICAgICAg"
    "ICAgICBpZiBoaWRkZW46CiAgICAgICAgICAgICAgICAgICAgaXRlbS5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX1RFWFRfRElNKSkK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgYywgaXRlbSkKICAgICAgICAgICAgIyBTdG9yZSByZWNvcmQg"
    "aW5kZXggaW4gZmlyc3QgY29sdW1uJ3MgdXNlciBkYXRhCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLml0ZW0ociwgMCkuc2V0RGF0"
    "YSgKICAgICAgICAgICAgICAgIFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMu"
    "aW5kZXgocmVjKQogICAgICAgICAgICApCgogICAgZGVmIF9zZWxlY3RlZF9pbmRpY2VzKHNlbGYpIC0+IGxpc3RbaW50XToKICAg"
    "ICAgICBpbmRpY2VzID0gc2V0KCkKICAgICAgICBmb3IgaXRlbSBpbiBzZWxmLl90YWJsZS5zZWxlY3RlZEl0ZW1zKCk6CiAgICAg"
    "ICAgICAgIHJvd19pdGVtID0gc2VsZi5fdGFibGUuaXRlbShpdGVtLnJvdygpLCAwKQogICAgICAgICAgICBpZiByb3dfaXRlbToK"
    "ICAgICAgICAgICAgICAgIGlkeCA9IHJvd19pdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAgICAgICAgICAg"
    "ICAgaWYgaWR4IGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgIGluZGljZXMuYWRkKGlkeCkKICAgICAgICByZXR1cm4g"
    "c29ydGVkKGluZGljZXMpCgogICAgZGVmIF9kaWFsb2coc2VsZiwgcmVjOiBkaWN0ID0gTm9uZSkgLT4gT3B0aW9uYWxbZGljdF06"
    "CiAgICAgICAgZGxnICA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkpvYiBBcHBsaWNhdGlvbiIp"
    "CiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAg"
    "ICBkbGcucmVzaXplKDUwMCwgMzIwKQogICAgICAgIGZvcm0gPSBRRm9ybUxheW91dChkbGcpCgogICAgICAgIGNvbXBhbnkgPSBR"
    "TGluZUVkaXQocmVjLmdldCgiY29tcGFueSIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIHRpdGxlICAgPSBRTGluZUVkaXQo"
    "cmVjLmdldCgiam9iX3RpdGxlIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgZGUgICAgICA9IFFEYXRlRWRpdCgpCiAgICAg"
    "ICAgZGUuc2V0Q2FsZW5kYXJQb3B1cChUcnVlKQogICAgICAgIGRlLnNldERpc3BsYXlGb3JtYXQoInl5eXktTU0tZGQiKQogICAg"
    "ICAgIGlmIHJlYyBhbmQgcmVjLmdldCgiZGF0ZV9hcHBsaWVkIik6CiAgICAgICAgICAgIGRlLnNldERhdGUoUURhdGUuZnJvbVN0"
    "cmluZyhyZWNbImRhdGVfYXBwbGllZCJdLCJ5eXl5LU1NLWRkIikpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgZGUuc2V0RGF0"
    "ZShRRGF0ZS5jdXJyZW50RGF0ZSgpKQogICAgICAgIGxpbmsgICAgPSBRTGluZUVkaXQocmVjLmdldCgibGluayIsIiIpIGlmIHJl"
    "YyBlbHNlICIiKQogICAgICAgIHN0YXR1cyAgPSBRTGluZUVkaXQocmVjLmdldCgic3RhdHVzIiwiQXBwbGllZCIpIGlmIHJlYyBl"
    "bHNlICJBcHBsaWVkIikKICAgICAgICBub3RlcyAgID0gUUxpbmVFZGl0KHJlYy5nZXQoIm5vdGVzIiwiIikgaWYgcmVjIGVsc2Ug"
    "IiIpCgogICAgICAgIGZvciBsYWJlbCwgd2lkZ2V0IGluIFsKICAgICAgICAgICAgKCJDb21wYW55OiIsIGNvbXBhbnkpLCAoIkpv"
    "YiBUaXRsZToiLCB0aXRsZSksCiAgICAgICAgICAgICgiRGF0ZSBBcHBsaWVkOiIsIGRlKSwgKCJMaW5rOiIsIGxpbmspLAogICAg"
    "ICAgICAgICAoIlN0YXR1czoiLCBzdGF0dXMpLCAoIk5vdGVzOiIsIG5vdGVzKSwKICAgICAgICBdOgogICAgICAgICAgICBmb3Jt"
    "LmFkZFJvdyhsYWJlbCwgd2lkZ2V0KQoKICAgICAgICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19i"
    "dG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2Vw"
    "dCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRn"
    "ZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRucykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0Nv"
    "ZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICAgICAiY29tcGFueSI6ICAgICAgY29tcGFueS50"
    "ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJqb2JfdGl0bGUiOiAgICB0aXRsZS50ZXh0KCkuc3RyaXAoKSwKICAgICAg"
    "ICAgICAgICAgICJkYXRlX2FwcGxpZWQiOiBkZS5kYXRlKCkudG9TdHJpbmcoInl5eXktTU0tZGQiKSwKICAgICAgICAgICAgICAg"
    "ICJsaW5rIjogICAgICAgICBsaW5rLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgIHN0YXR1"
    "cy50ZXh0KCkuc3RyaXAoKSBvciAiQXBwbGllZCIsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICAgbm90ZXMudGV4dCgp"
    "LnN0cmlwKCksCiAgICAgICAgICAgIH0KICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgcCA9IHNlbGYuX2RpYWxvZygpCiAgICAgICAgaWYgbm90IHA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5v"
    "dyA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgcC51cGRhdGUoewogICAgICAgICAgICAi"
    "aWQiOiAgICAgICAgICAgICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgImhpZGRlbiI6ICAgICAgICAgRmFsc2UsCiAg"
    "ICAgICAgICAgICJjb21wbGV0ZWRfZGF0ZSI6IE5vbmUsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgIG5vdywKICAgICAg"
    "ICAgICAgInVwZGF0ZWRfYXQiOiAgICAgbm93LAogICAgICAgIH0pCiAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQocCkKICAg"
    "ICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVm"
    "IF9kb19tb2RpZnkoc2VsZikgLT4gTm9uZToKICAgICAgICBpZHhzID0gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpCiAgICAgICAg"
    "aWYgbGVuKGlkeHMpICE9IDE6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJNb2RpZnkiLAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiU2VsZWN0IGV4YWN0bHkgb25lIHJvdyB0byBtb2RpZnkuIikKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tpZHhzWzBdXQogICAgICAgIHAgICA9IHNlbGYuX2RpYWxv"
    "ZyhyZWMpCiAgICAgICAgaWYgbm90IHA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlYy51cGRhdGUocCkKICAgICAgICBy"
    "ZWNbInVwZGF0ZWRfYXQiXSA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgd3JpdGVfanNv"
    "bmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9faGlkZShzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIGZvciBpZHggaW4gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpOgogICAgICAgICAgICBpZiBpZHgg"
    "PCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bImhpZGRlbiJdICAgICAgICAg"
    "PSBUcnVlCiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bImNvbXBsZXRlZF9kYXRlIl0gPSAoCiAgICAgICAgICAg"
    "ICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdLmdldCgiY29tcGxldGVkX2RhdGUiKSBvcgogICAgICAgICAgICAgICAgICAgIGRh"
    "dGV0aW1lLm5vdygpLmRhdGUoKS5pc29mb3JtYXQoKQogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgc2VsZi5fcmVj"
    "b3Jkc1tpZHhdWyJ1cGRhdGVkX2F0Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0Yyku"
    "aXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRz"
    "KQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb191bmhpZGUoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3IgaWR4"
    "IGluIHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKToKICAgICAgICAgICAgaWYgaWR4IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAg"
    "ICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJoaWRkZW4iXSAgICAgPSBGYWxzZQogICAgICAgICAgICAgICAgc2VsZi5f"
    "cmVjb3Jkc1tpZHhdWyJ1cGRhdGVkX2F0Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0"
    "YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNv"
    "cmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICBpZHhz"
    "ID0gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpCiAgICAgICAgaWYgbm90IGlkeHM6CiAgICAgICAgICAgIHJldHVybgogICAgICAg"
    "IHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgIHNlbGYsICJEZWxldGUiLAogICAgICAgICAgICBmIkRl"
    "bGV0ZSB7bGVuKGlkeHMpfSBzZWxlY3RlZCBhcHBsaWNhdGlvbihzKT8gQ2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICBR"
    "TWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICkKICAg"
    "ICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIGJhZCA9IHNldChpZHhz"
    "KQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzID0gW3IgZm9yIGksIHIgaW4gZW51bWVyYXRlKHNlbGYuX3JlY29yZHMpCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgaWYgaSBub3QgaW4gYmFkXQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRo"
    "LCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfdG9nZ2xlX2hpZGRlbihzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHNlbGYuX3Nob3dfaGlkZGVuID0gbm90IHNlbGYuX3Nob3dfaGlkZGVuCiAgICAgICAgc2VsZi5fYnRu"
    "X3RvZ2dsZS5zZXRUZXh0KAogICAgICAgICAgICAi4piAIEhpZGUgQXJjaGl2ZWQiIGlmIHNlbGYuX3Nob3dfaGlkZGVuIGVsc2Ug"
    "IuKYvSBTaG93IEFyY2hpdmVkIgogICAgICAgICkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZXhwb3J0KHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCwgZmlsdCA9IFFGaWxlRGlhbG9nLmdldFNhdmVGaWxlTmFtZSgKICAgICAgICAgICAg"
    "c2VsZiwgIkV4cG9ydCBKb2IgVHJhY2tlciIsCiAgICAgICAgICAgIHN0cihjZmdfcGF0aCgiZXhwb3J0cyIpIC8gImpvYl90cmFj"
    "a2VyLmNzdiIpLAogICAgICAgICAgICAiQ1NWIEZpbGVzICgqLmNzdik7O1RhYiBEZWxpbWl0ZWQgKCoudHh0KSIKICAgICAgICAp"
    "CiAgICAgICAgaWYgbm90IHBhdGg6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGRlbGltID0gIlx0IiBpZiBwYXRoLmxvd2Vy"
    "KCkuZW5kc3dpdGgoIi50eHQiKSBlbHNlICIsIgogICAgICAgIGhlYWRlciA9IFsiY29tcGFueSIsImpvYl90aXRsZSIsImRhdGVf"
    "YXBwbGllZCIsImxpbmsiLAogICAgICAgICAgICAgICAgICAic3RhdHVzIiwiaGlkZGVuIiwiY29tcGxldGVkX2RhdGUiLCJub3Rl"
    "cyJdCiAgICAgICAgd2l0aCBvcGVuKHBhdGgsICJ3IiwgZW5jb2Rpbmc9InV0Zi04IiwgbmV3bGluZT0iIikgYXMgZjoKICAgICAg"
    "ICAgICAgZi53cml0ZShkZWxpbS5qb2luKGhlYWRlcikgKyAiXG4iKQogICAgICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29y"
    "ZHM6CiAgICAgICAgICAgICAgICB2YWxzID0gWwogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImNvbXBhbnkiLCIiKSwKICAg"
    "ICAgICAgICAgICAgICAgICByZWMuZ2V0KCJqb2JfdGl0bGUiLCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJkYXRl"
    "X2FwcGxpZWQiLCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJsaW5rIiwiIiksCiAgICAgICAgICAgICAgICAgICAg"
    "cmVjLmdldCgic3RhdHVzIiwiIiksCiAgICAgICAgICAgICAgICAgICAgc3RyKGJvb2wocmVjLmdldCgiaGlkZGVuIixGYWxzZSkp"
    "KSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJjb21wbGV0ZWRfZGF0ZSIsIiIpIG9yICIiLAogICAgICAgICAgICAgICAg"
    "ICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAgICAgICAgICAgICAgICBdCiAgICAgICAgICAgICAgICBmLndyaXRlKGRlbGltLmpv"
    "aW4oCiAgICAgICAgICAgICAgICAgICAgc3RyKHYpLnJlcGxhY2UoIlxuIiwiICIpLnJlcGxhY2UoZGVsaW0sIiAiKQogICAgICAg"
    "ICAgICAgICAgICAgIGZvciB2IGluIHZhbHMKICAgICAgICAgICAgICAgICkgKyAiXG4iKQogICAgICAgIFFNZXNzYWdlQm94Lmlu"
    "Zm9ybWF0aW9uKHNlbGYsICJFeHBvcnRlZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJTYXZlZCB0byB7cGF0"
    "aH0iKQoKCiMg4pSA4pSAIFNFTEYgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApj"
    "bGFzcyBSZWNvcmRzVGFiKFFXaWRnZXQpOgogICAgIiIiR29vZ2xlIERyaXZlL0RvY3MgcmVjb3JkcyBicm93c2VyIHRhYi4iIiIK"
    "CiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAg"
    "ICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAg"
    "ICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVsKCJSZWNvcmRzIGFyZSBu"
    "b3QgbG9hZGVkIHlldC4iKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29s"
    "b3I6IHtDX1RFWFRfRElNfTsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAg"
    "ICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5zdGF0dXNfbGFiZWwpCgogICAgICAgIHNlbGYucGF0aF9sYWJlbCA9IFFM"
    "YWJlbCgiUGF0aDogTXkgRHJpdmUiKQogICAgICAgIHNlbGYucGF0aF9sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBm"
    "ImNvbG9yOiB7Q19HT0xEX0RJTX07IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsiCiAg"
    "ICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYucGF0aF9sYWJlbCkKCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3Qg"
    "PSBRTGlzdFdpZGdldCgpCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNr"
    "Z3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IgogICAgICAgICkK"
    "ICAgICAgICByb290LmFkZFdpZGdldChzZWxmLnJlY29yZHNfbGlzdCwgMSkKCiAgICBkZWYgc2V0X2l0ZW1zKHNlbGYsIGZpbGVz"
    "OiBsaXN0W2RpY3RdLCBwYXRoX3RleHQ6IHN0ciA9ICJNeSBEcml2ZSIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5wYXRoX2xhYmVs"
    "LnNldFRleHQoZiJQYXRoOiB7cGF0aF90ZXh0fSIpCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3QuY2xlYXIoKQogICAgICAgIGZv"
    "ciBmaWxlX2luZm8gaW4gZmlsZXM6CiAgICAgICAgICAgIHRpdGxlID0gKGZpbGVfaW5mby5nZXQoIm5hbWUiKSBvciAiVW50aXRs"
    "ZWQiKS5zdHJpcCgpIG9yICJVbnRpdGxlZCIKICAgICAgICAgICAgbWltZSA9IChmaWxlX2luZm8uZ2V0KCJtaW1lVHlwZSIpIG9y"
    "ICIiKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5mb2xkZXIiOgog"
    "ICAgICAgICAgICAgICAgcHJlZml4ID0gIvCfk4EiCiAgICAgICAgICAgIGVsaWYgbWltZSA9PSAiYXBwbGljYXRpb24vdm5kLmdv"
    "b2dsZS1hcHBzLmRvY3VtZW50IjoKICAgICAgICAgICAgICAgIHByZWZpeCA9ICLwn5OdIgogICAgICAgICAgICBlbHNlOgogICAg"
    "ICAgICAgICAgICAgcHJlZml4ID0gIvCfk4QiCiAgICAgICAgICAgIG1vZGlmaWVkID0gKGZpbGVfaW5mby5nZXQoIm1vZGlmaWVk"
    "VGltZSIpIG9yICIiKS5yZXBsYWNlKCJUIiwgIiAiKS5yZXBsYWNlKCJaIiwgIiBVVEMiKQogICAgICAgICAgICB0ZXh0ID0gZiJ7"
    "cHJlZml4fSB7dGl0bGV9IiArIChmIiAgICBbe21vZGlmaWVkfV0iIGlmIG1vZGlmaWVkIGVsc2UgIiIpCiAgICAgICAgICAgIGl0"
    "ZW0gPSBRTGlzdFdpZGdldEl0ZW0odGV4dCkKICAgICAgICAgICAgaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9s"
    "ZSwgZmlsZV9pbmZvKQogICAgICAgICAgICBzZWxmLnJlY29yZHNfbGlzdC5hZGRJdGVtKGl0ZW0pCiAgICAgICAgc2VsZi5zdGF0"
    "dXNfbGFiZWwuc2V0VGV4dChmIkxvYWRlZCB7bGVuKGZpbGVzKX0gR29vZ2xlIERyaXZlIGl0ZW0ocykuIikKCgpjbGFzcyBUYXNr"
    "c1RhYihRV2lkZ2V0KToKICAgICIiIlRhc2sgcmVnaXN0cnkgKyBHb29nbGUtZmlyc3QgZWRpdG9yIHdvcmtmbG93IHRhYi4iIiIK"
    "CiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKICAgICAgICB0YXNrc19wcm92aWRlciwKICAgICAgICBvbl9hZGRfZWRp"
    "dG9yX29wZW4sCiAgICAgICAgb25fY29tcGxldGVfc2VsZWN0ZWQsCiAgICAgICAgb25fY2FuY2VsX3NlbGVjdGVkLAogICAgICAg"
    "IG9uX3RvZ2dsZV9jb21wbGV0ZWQsCiAgICAgICAgb25fcHVyZ2VfY29tcGxldGVkLAogICAgICAgIG9uX2ZpbHRlcl9jaGFuZ2Vk"
    "LAogICAgICAgIG9uX2VkaXRvcl9zYXZlLAogICAgICAgIG9uX2VkaXRvcl9jYW5jZWwsCiAgICAgICAgZGlhZ25vc3RpY3NfbG9n"
    "Z2VyPU5vbmUsCiAgICAgICAgcGFyZW50PU5vbmUsCiAgICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAg"
    "ICAgIHNlbGYuX3Rhc2tzX3Byb3ZpZGVyID0gdGFza3NfcHJvdmlkZXIKICAgICAgICBzZWxmLl9vbl9hZGRfZWRpdG9yX29wZW4g"
    "PSBvbl9hZGRfZWRpdG9yX29wZW4KICAgICAgICBzZWxmLl9vbl9jb21wbGV0ZV9zZWxlY3RlZCA9IG9uX2NvbXBsZXRlX3NlbGVj"
    "dGVkCiAgICAgICAgc2VsZi5fb25fY2FuY2VsX3NlbGVjdGVkID0gb25fY2FuY2VsX3NlbGVjdGVkCiAgICAgICAgc2VsZi5fb25f"
    "dG9nZ2xlX2NvbXBsZXRlZCA9IG9uX3RvZ2dsZV9jb21wbGV0ZWQKICAgICAgICBzZWxmLl9vbl9wdXJnZV9jb21wbGV0ZWQgPSBv"
    "bl9wdXJnZV9jb21wbGV0ZWQKICAgICAgICBzZWxmLl9vbl9maWx0ZXJfY2hhbmdlZCA9IG9uX2ZpbHRlcl9jaGFuZ2VkCiAgICAg"
    "ICAgc2VsZi5fb25fZWRpdG9yX3NhdmUgPSBvbl9lZGl0b3Jfc2F2ZQogICAgICAgIHNlbGYuX29uX2VkaXRvcl9jYW5jZWwgPSBv"
    "bl9lZGl0b3JfY2FuY2VsCiAgICAgICAgc2VsZi5fZGlhZ19sb2dnZXIgPSBkaWFnbm9zdGljc19sb2dnZXIKICAgICAgICBzZWxm"
    "Ll9zaG93X2NvbXBsZXRlZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fcmVmcmVzaF90aHJlYWQgPSBOb25lCiAgICAgICAgc2VsZi5f"
    "YnVpbGRfdWkoKQoKICAgIGRlZiBfYnVpbGRfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2Vs"
    "ZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQog"
    "ICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrID0gUVN0YWNrZWRXaWRnZXQoKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYu"
    "d29ya3NwYWNlX3N0YWNrLCAxKQoKICAgICAgICBub3JtYWwgPSBRV2lkZ2V0KCkKICAgICAgICBub3JtYWxfbGF5b3V0ID0gUVZC"
    "b3hMYXlvdXQobm9ybWFsKQogICAgICAgIG5vcm1hbF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAg"
    "ICAgbm9ybWFsX2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVsKCJUYXNrIHJl"
    "Z2lzdHJ5IGlzIG5vdCBsb2FkZWQgeWV0LiIpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEw"
    "cHg7IgogICAgICAgICkKICAgICAgICBub3JtYWxfbGF5b3V0LmFkZFdpZGdldChzZWxmLnN0YXR1c19sYWJlbCkKCiAgICAgICAg"
    "ZmlsdGVyX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBE"
    "QVRFIFJBTkdFIikpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc2VsZi50YXNr"
    "X2ZpbHRlcl9jb21iby5hZGRJdGVtKCJXRUVLIiwgIndlZWsiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRl"
    "bSgiTU9OVEgiLCAibW9udGgiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiTkVYVCAzIE1PTlRIUyIs"
    "ICJuZXh0XzNfbW9udGhzIikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIllFQVIiLCAieWVhciIpCiAg"
    "ICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5zZXRDdXJyZW50SW5kZXgoMikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2Nv"
    "bWJvLmN1cnJlbnRJbmRleENoYW5nZWQuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIF86IHNlbGYuX29uX2ZpbHRlcl9jaGFu"
    "Z2VkKHNlbGYudGFza19maWx0ZXJfY29tYm8uY3VycmVudERhdGEoKSBvciAibmV4dF8zX21vbnRocyIpCiAgICAgICAgKQogICAg"
    "ICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYudGFza19maWx0ZXJfY29tYm8pCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRTdHJl"
    "dGNoKDEpCiAgICAgICAgbm9ybWFsX2xheW91dC5hZGRMYXlvdXQoZmlsdGVyX3JvdykKCiAgICAgICAgc2VsZi50YXNrX3RhYmxl"
    "ID0gUVRhYmxlV2lkZ2V0KDAsIDQpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJT"
    "dGF0dXMiLCAiRHVlIiwgIlRhc2siLCAiU291cmNlIl0pCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2"
    "aW9yKFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi50YXNrX3RhYmxl"
    "LnNldFNlbGVjdGlvbk1vZGUoUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uTW9kZS5FeHRlbmRlZFNlbGVjdGlvbikKICAgICAg"
    "ICBzZWxmLnRhc2tfdGFibGUuc2V0RWRpdFRyaWdnZXJzKFFBYnN0cmFjdEl0ZW1WaWV3LkVkaXRUcmlnZ2VyLk5vRWRpdFRyaWdn"
    "ZXJzKQogICAgICAgIHNlbGYudGFza190YWJsZS52ZXJ0aWNhbEhlYWRlcigpLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgc2Vs"
    "Zi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgwLCBRSGVhZGVyVmlldy5SZXNpemVN"
    "b2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9u"
    "UmVzaXplTW9kZSgxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50YXNrX3Rh"
    "YmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0"
    "Y2gpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgzLCBRSGVh"
    "ZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFN0eWxlU2hlZXQo"
    "X2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYudGFza190YWJsZS5pdGVtU2VsZWN0aW9uQ2hhbmdlZC5jb25uZWN0"
    "KHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0dG9uX3N0YXRlKQogICAgICAgIG5vcm1hbF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFz"
    "a190YWJsZSwgMSkKCiAgICAgICAgYWN0aW9ucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLmJ0bl9hZGRfdGFza193b3Jr"
    "c3BhY2UgPSBfZ290aGljX2J0bigiQUREIFRBU0siKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2sgPSBfZ290aGljX2J0"
    "bigiQ09NUExFVEUgU0VMRUNURUQiKQogICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrID0gX2dvdGhpY19idG4oIkNBTkNFTCBT"
    "RUxFQ1RFRCIpCiAgICAgICAgc2VsZi5idG5fdG9nZ2xlX2NvbXBsZXRlZCA9IF9nb3RoaWNfYnRuKCJTSE9XIENPTVBMRVRFRCIp"
    "CiAgICAgICAgc2VsZi5idG5fcHVyZ2VfY29tcGxldGVkID0gX2dvdGhpY19idG4oIlBVUkdFIENPTVBMRVRFRCIpCiAgICAgICAg"
    "c2VsZi5idG5fYWRkX3Rhc2tfd29ya3NwYWNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9hZGRfZWRpdG9yX29wZW4pCiAgICAg"
    "ICAgc2VsZi5idG5fY29tcGxldGVfdGFzay5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fY29tcGxldGVfc2VsZWN0ZWQpCiAgICAg"
    "ICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2NhbmNlbF9zZWxlY3RlZCkKICAgICAgICBz"
    "ZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl90b2dnbGVfY29tcGxldGVkKQogICAgICAg"
    "IHNlbGYuYnRuX3B1cmdlX2NvbXBsZXRlZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fcHVyZ2VfY29tcGxldGVkKQogICAgICAg"
    "IHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2suc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzay5zZXRF"
    "bmFibGVkKEZhbHNlKQogICAgICAgIGZvciBidG4gaW4gKAogICAgICAgICAgICBzZWxmLmJ0bl9hZGRfdGFza193b3Jrc3BhY2Us"
    "CiAgICAgICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2ssCiAgICAgICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrLAogICAg"
    "ICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLAogICAgICAgICAgICBzZWxmLmJ0bl9wdXJnZV9jb21wbGV0ZWQsCiAg"
    "ICAgICAgKToKICAgICAgICAgICAgYWN0aW9ucy5hZGRXaWRnZXQoYnRuKQogICAgICAgIG5vcm1hbF9sYXlvdXQuYWRkTGF5b3V0"
    "KGFjdGlvbnMpCiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suYWRkV2lkZ2V0KG5vcm1hbCkKCiAgICAgICAgZWRpdG9yID0g"
    "UVdpZGdldCgpCiAgICAgICAgZWRpdG9yX2xheW91dCA9IFFWQm94TGF5b3V0KGVkaXRvcikKICAgICAgICBlZGl0b3JfbGF5b3V0"
    "LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGVkaXRvcl9sYXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAg"
    "IGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFRBU0sgRURJVE9SIOKAlCBHT09HTEUtRklSU1QiKSkK"
    "ICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbCA9IFFMYWJlbCgiQ29uZmlndXJlIHRhc2sgZGV0YWlscywgdGhl"
    "biBzYXZlIHRvIEdvb2dsZSBDYWxlbmRhci4iKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVsLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgYm9yZGVyOiAxcHgg"
    "c29saWQge0NfQk9SREVSfTsgcGFkZGluZzogNnB4OyIKICAgICAgICApCiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQo"
    "c2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9uYW1lID0gUUxpbmVFZGl0KCkK"
    "ICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJUYXNrIE5hbWUiKQogICAgICAgIHNlbGYu"
    "dGFza19lZGl0b3Jfc3RhcnRfZGF0ZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLnNl"
    "dFBsYWNlaG9sZGVyVGV4dCgiU3RhcnQgRGF0ZSAoWVlZWS1NTS1ERCkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRf"
    "dGltZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnNldFBsYWNlaG9sZGVyVGV4dCgi"
    "U3RhcnQgVGltZSAoSEg6TU0pIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlID0gUUxpbmVFZGl0KCkKICAgICAg"
    "ICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlLnNldFBsYWNlaG9sZGVyVGV4dCgiRW5kIERhdGUgKFlZWVktTU0tREQpIikKICAg"
    "ICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90"
    "aW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiRW5kIFRpbWUgKEhIOk1NKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlv"
    "biA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbi5zZXRQbGFjZWhvbGRlclRleHQoIkxvY2F0"
    "aW9uIChvcHRpb25hbCkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfcmVjdXJyZW5jZSA9IFFMaW5lRWRpdCgpCiAgICAgICAg"
    "c2VsZi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnNldFBsYWNlaG9sZGVyVGV4dCgiUmVjdXJyZW5jZSBSUlVMRSAob3B0aW9uYWwp"
    "IikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2FsbF9kYXkgPSBRQ2hlY2tCb3goIkFsbC1kYXkiKQogICAgICAgIHNlbGYudGFz"
    "a19lZGl0b3Jfbm90ZXMgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfbm90ZXMuc2V0UGxhY2Vob2xkZXJU"
    "ZXh0KCJOb3RlcyIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9ub3Rlcy5zZXRNYXhpbXVtSGVpZ2h0KDkwKQogICAgICAgIGZv"
    "ciB3aWRnZXQgaW4gKAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25hbWUsCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0"
    "b3Jfc3RhcnRfZGF0ZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLAogICAgICAgICAgICBzZWxmLnRh"
    "c2tfZWRpdG9yX2VuZF9kYXRlLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lLAogICAgICAgICAgICBzZWxm"
    "LnRhc2tfZWRpdG9yX2xvY2F0aW9uLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3JlY3VycmVuY2UsCiAgICAgICAgKToK"
    "ICAgICAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQod2lkZ2V0KQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0"
    "KHNlbGYudGFza19lZGl0b3JfYWxsX2RheSkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChzZWxmLnRhc2tfZWRpdG9y"
    "X25vdGVzLCAxKQogICAgICAgIGVkaXRvcl9hY3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9zYXZlID0gX2dvdGhp"
    "Y19idG4oIlNBVkUiKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigiQ0FOQ0VMIikKICAgICAgICBidG5fc2F2ZS5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fZWRpdG9yX3NhdmUpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fb25fZWRpdG9yX2NhbmNlbCkKICAgICAgICBlZGl0b3JfYWN0aW9ucy5hZGRXaWRnZXQoYnRuX3NhdmUpCiAgICAgICAgZWRp"
    "dG9yX2FjdGlvbnMuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkU3RyZXRjaCgxKQogICAg"
    "ICAgIGVkaXRvcl9sYXlvdXQuYWRkTGF5b3V0KGVkaXRvcl9hY3Rpb25zKQogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLmFk"
    "ZFdpZGdldChlZGl0b3IpCgogICAgICAgIHNlbGYubm9ybWFsX3dvcmtzcGFjZSA9IG5vcm1hbAogICAgICAgIHNlbGYuZWRpdG9y"
    "X3dvcmtzcGFjZSA9IGVkaXRvcgogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQoc2VsZi5ub3Jt"
    "YWxfd29ya3NwYWNlKQoKICAgIGRlZiBfdXBkYXRlX2FjdGlvbl9idXR0b25fc3RhdGUoc2VsZikgLT4gTm9uZToKICAgICAgICBl"
    "bmFibGVkID0gYm9vbChzZWxmLnNlbGVjdGVkX3Rhc2tfaWRzKCkpCiAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzay5zZXRF"
    "bmFibGVkKGVuYWJsZWQpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suc2V0RW5hYmxlZChlbmFibGVkKQoKICAgIGRlZiBz"
    "ZWxlY3RlZF90YXNrX2lkcyhzZWxmKSAtPiBsaXN0W3N0cl06CiAgICAgICAgaWRzOiBsaXN0W3N0cl0gPSBbXQogICAgICAgIGZv"
    "ciByIGluIHJhbmdlKHNlbGYudGFza190YWJsZS5yb3dDb3VudCgpKToKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBzZWxmLnRh"
    "c2tfdGFibGUuaXRlbShyLCAwKQogICAgICAgICAgICBpZiBzdGF0dXNfaXRlbSBpcyBOb25lOgogICAgICAgICAgICAgICAgY29u"
    "dGludWUKICAgICAgICAgICAgaWYgbm90IHN0YXR1c19pdGVtLmlzU2VsZWN0ZWQoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVl"
    "CiAgICAgICAgICAgIHRhc2tfaWQgPSBzdGF0dXNfaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAg"
    "ICAgaWYgdGFza19pZCBhbmQgdGFza19pZCBub3QgaW4gaWRzOgogICAgICAgICAgICAgICAgaWRzLmFwcGVuZCh0YXNrX2lkKQog"
    "ICAgICAgIHJldHVybiBpZHMKCiAgICBkZWYgbG9hZF90YXNrcyhzZWxmLCB0YXNrczogbGlzdFtkaWN0XSkgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLnRhc2tfdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgdGFzayBpbiB0YXNrczoKICAgICAgICAgICAg"
    "cm93ID0gc2VsZi50YXNrX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLmluc2VydFJvdyhyb3cp"
    "CiAgICAgICAgICAgIHN0YXR1cyA9ICh0YXNrLmdldCgic3RhdHVzIikgb3IgInBlbmRpbmciKS5sb3dlcigpCiAgICAgICAgICAg"
    "IHN0YXR1c19pY29uID0gIuKYkSIgaWYgc3RhdHVzIGluIHsiY29tcGxldGVkIiwgImNhbmNlbGxlZCJ9IGVsc2UgIuKAoiIKICAg"
    "ICAgICAgICAgZHVlID0gKHRhc2suZ2V0KCJkdWVfYXQiKSBvciAiIikucmVwbGFjZSgiVCIsICIgIikKICAgICAgICAgICAgdGV4"
    "dCA9ICh0YXNrLmdldCgidGV4dCIpIG9yICJSZW1pbmRlciIpLnN0cmlwKCkgb3IgIlJlbWluZGVyIgogICAgICAgICAgICBzb3Vy"
    "Y2UgPSAodGFzay5nZXQoInNvdXJjZSIpIG9yICJsb2NhbCIpLmxvd2VyKCkKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBRVGFi"
    "bGVXaWRnZXRJdGVtKGYie3N0YXR1c19pY29ufSB7c3RhdHVzfSIpCiAgICAgICAgICAgIHN0YXR1c19pdGVtLnNldERhdGEoUXQu"
    "SXRlbURhdGFSb2xlLlVzZXJSb2xlLCB0YXNrLmdldCgiaWQiKSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0o"
    "cm93LCAwLCBzdGF0dXNfaXRlbSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAxLCBRVGFibGVXaWRn"
    "ZXRJdGVtKGR1ZSkpCiAgICAgICAgICAgIHNlbGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMiwgUVRhYmxlV2lkZ2V0SXRlbSh0"
    "ZXh0KSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAzLCBRVGFibGVXaWRnZXRJdGVtKHNvdXJjZSkp"
    "CiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkxvYWRlZCB7bGVuKHRhc2tzKX0gdGFzayhzKS4iKQogICAgICAg"
    "IHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0dG9uX3N0YXRlKCkKCiAgICBkZWYgX2RpYWcoc2VsZiwgbWVzc2FnZTogc3RyLCBsZXZl"
    "bDogc3RyID0gIklORk8iKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgaWYgc2VsZi5fZGlhZ19sb2dnZXI6CiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9kaWFnX2xvZ2dlcihtZXNzYWdlLCBsZXZlbCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgog"
    "ICAgICAgICAgICBwYXNzCgogICAgZGVmIHN0b3BfcmVmcmVzaF93b3JrZXIoc2VsZiwgcmVhc29uOiBzdHIgPSAiIikgLT4gTm9u"
    "ZToKICAgICAgICB0aHJlYWQgPSBnZXRhdHRyKHNlbGYsICJfcmVmcmVzaF90aHJlYWQiLCBOb25lKQogICAgICAgIGlmIHRocmVh"
    "ZCBpcyBub3QgTm9uZSBhbmQgaGFzYXR0cih0aHJlYWQsICJpc1J1bm5pbmciKSBhbmQgdGhyZWFkLmlzUnVubmluZygpOgogICAg"
    "ICAgICAgICBzZWxmLl9kaWFnKAogICAgICAgICAgICAgICAgZiJbVEFTS1NdW1RIUkVBRF1bV0FSTl0gc3RvcCByZXF1ZXN0ZWQg"
    "Zm9yIHJlZnJlc2ggd29ya2VyIHJlYXNvbj17cmVhc29uIG9yICd1bnNwZWNpZmllZCd9IiwKICAgICAgICAgICAgICAgICJXQVJO"
    "IiwKICAgICAgICAgICAgKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICB0aHJlYWQucmVxdWVzdEludGVycnVwdGlv"
    "bigpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCiAgICAgICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgICAgIHRocmVhZC5xdWl0KCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBh"
    "c3MKICAgICAgICAgICAgdGhyZWFkLndhaXQoMjAwMCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3RocmVhZCA9IE5vbmUKCiAgICBk"
    "ZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBjYWxsYWJsZShzZWxmLl90YXNrc19wcm92aWRlcik6CiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5sb2FkX3Rhc2tzKHNlbGYuX3Rhc2tzX3Byb3Zp"
    "ZGVyKCkpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fZGlhZyhmIltUQVNLU11bVEFC"
    "XVtFUlJPUl0gcmVmcmVzaCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiKQogICAgICAgICAgICBzZWxmLnN0b3BfcmVmcmVzaF93b3Jr"
    "ZXIocmVhc29uPSJ0YXNrc190YWJfcmVmcmVzaF9leGNlcHRpb24iKQoKICAgIGRlZiBjbG9zZUV2ZW50KHNlbGYsIGV2ZW50KSAt"
    "PiBOb25lOgogICAgICAgIHNlbGYuc3RvcF9yZWZyZXNoX3dvcmtlcihyZWFzb249InRhc2tzX3RhYl9jbG9zZSIpCiAgICAgICAg"
    "c3VwZXIoKS5jbG9zZUV2ZW50KGV2ZW50KQoKICAgIGRlZiBzZXRfc2hvd19jb21wbGV0ZWQoc2VsZiwgZW5hYmxlZDogYm9vbCkg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9zaG93X2NvbXBsZXRlZCA9IGJvb2woZW5hYmxlZCkKICAgICAgICBzZWxmLmJ0bl90b2dn"
    "bGVfY29tcGxldGVkLnNldFRleHQoIkhJREUgQ09NUExFVEVEIiBpZiBzZWxmLl9zaG93X2NvbXBsZXRlZCBlbHNlICJTSE9XIENP"
    "TVBMRVRFRCIpCgogICAgZGVmIHNldF9zdGF0dXMoc2VsZiwgdGV4dDogc3RyLCBvazogYm9vbCA9IEZhbHNlKSAtPiBOb25lOgog"
    "ICAgICAgIGNvbG9yID0gQ19HUkVFTiBpZiBvayBlbHNlIENfVEVYVF9ESU0KICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1"
    "c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Y29sb3J9OyBi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA2cHg7IgogICAgICAgICkKICAgICAgICBzZWxmLnRhc2tfZWRp"
    "dG9yX3N0YXR1c19sYWJlbC5zZXRUZXh0KHRleHQpCgogICAgZGVmIG9wZW5fZWRpdG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "c2VsZi53b3Jrc3BhY2Vfc3RhY2suc2V0Q3VycmVudFdpZGdldChzZWxmLmVkaXRvcl93b3Jrc3BhY2UpCgogICAgZGVmIGNsb3Nl"
    "X2VkaXRvcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQoc2VsZi5u"
    "b3JtYWxfd29ya3NwYWNlKQoKCmNsYXNzIFNlbGZUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFBlcnNvbmEncyBpbnRlcm5hbCBk"
    "aWFsb2d1ZSBzcGFjZS4KICAgIFJlY2VpdmVzOiBpZGxlIG5hcnJhdGl2ZSBvdXRwdXQsIHVuc29saWNpdGVkIHRyYW5zbWlzc2lv"
    "bnMsCiAgICAgICAgICAgICAgUG9JIGxpc3QgZnJvbSBkYWlseSByZWZsZWN0aW9uLCB1bmFuc3dlcmVkIHF1ZXN0aW9uIGZsYWdz"
    "LAogICAgICAgICAgICAgIGpvdXJuYWwgbG9hZCBub3RpZmljYXRpb25zLgogICAgUmVhZC1vbmx5IGRpc3BsYXkuIFNlcGFyYXRl"
    "IGZyb20gcGVyc29uYSBjaGF0IHRhYiBhbHdheXMuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUp"
    "OgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAg"
    "IHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGhk"
    "ciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBoZHIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibChmIuKdpyBJTk5FUiBTQU5DVFVNIOKA"
    "lCB7REVDS19OQU1FLnVwcGVyKCl9J1MgUFJJVkFURSBUSE9VR0hUUyIpKQogICAgICAgIHNlbGYuX2J0bl9jbGVhciA9IF9nb3Ro"
    "aWNfYnRuKCLinJcgQ2xlYXIiKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5zZXRGaXhlZFdpZHRoKDgwKQogICAgICAgIHNlbGYu"
    "X2J0bl9jbGVhci5jbGlja2VkLmNvbm5lY3Qoc2VsZi5jbGVhcikKICAgICAgICBoZHIuYWRkU3RyZXRjaCgpCiAgICAgICAgaGRy"
    "LmFkZFdpZGdldChzZWxmLl9idG5fY2xlYXIpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoaGRyKQoKICAgICAgICBzZWxmLl9kaXNw"
    "bGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fZGlz"
    "cGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfR09MRH07"
    "ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19QVVJQTEVfRElNfTsgIgogICAgICAgICAgICBmImZvbnQtZmFt"
    "aWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAg"
    "cm9vdC5hZGRXaWRnZXQoc2VsZi5fZGlzcGxheSwgMSkKCiAgICBkZWYgYXBwZW5kKHNlbGYsIGxhYmVsOiBzdHIsIHRleHQ6IHN0"
    "cikgLT4gTm9uZToKICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAg"
    "IGNvbG9ycyA9IHsKICAgICAgICAgICAgIk5BUlJBVElWRSI6ICBDX0dPTEQsCiAgICAgICAgICAgICJSRUZMRUNUSU9OIjogQ19Q"
    "VVJQTEUsCiAgICAgICAgICAgICJKT1VSTkFMIjogICAgQ19TSUxWRVIsCiAgICAgICAgICAgICJQT0kiOiAgICAgICAgQ19HT0xE"
    "X0RJTSwKICAgICAgICAgICAgIlNZU1RFTSI6ICAgICBDX1RFWFRfRElNLAogICAgICAgIH0KICAgICAgICBjb2xvciA9IGNvbG9y"
    "cy5nZXQobGFiZWwudXBwZXIoKSwgQ19HT0xEKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICBmJzxz"
    "cGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICBmJ1t7dGltZXN0YW1w"
    "fV0gPC9zcGFuPicKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2NvbG9yfTsgZm9udC13ZWlnaHQ6Ym9sZDsiPicK"
    "ICAgICAgICAgICAgZifinacge2xhYmVsfTwvc3Bhbj48YnI+JwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19H"
    "T0xEfTsiPnt0ZXh0fTwvc3Bhbj4nCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKCIiKQogICAgICAgIHNl"
    "bGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNh"
    "bFNjcm9sbEJhcigpLm1heGltdW0oKQogICAgICAgICkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9kaXNwbGF5LmNsZWFyKCkKCgojIOKUgOKUgCBESUFHTk9TVElDUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNs"
    "YXNzIERpYWdub3N0aWNzVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBCYWNrZW5kIGRpYWdub3N0aWNzIGRpc3BsYXkuCiAgICBS"
    "ZWNlaXZlczogaGFyZHdhcmUgZGV0ZWN0aW9uIHJlc3VsdHMsIGRlcGVuZGVuY3kgY2hlY2sgcmVzdWx0cywKICAgICAgICAgICAg"
    "ICBBUEkgZXJyb3JzLCBzeW5jIGZhaWx1cmVzLCB0aW1lciBldmVudHMsIGpvdXJuYWwgbG9hZCBub3RpY2VzLAogICAgICAgICAg"
    "ICAgIG1vZGVsIGxvYWQgc3RhdHVzLCBHb29nbGUgYXV0aCBldmVudHMuCiAgICBBbHdheXMgc2VwYXJhdGUgZnJvbSBwZXJzb25h"
    "IGNoYXQgdGFiLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9f"
    "aW5pdF9fKHBhcmVudCkKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFy"
    "Z2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBoZHIgPSBRSEJveExheW91dCgpCiAg"
    "ICAgICAgaGRyLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBESUFHTk9TVElDUyDigJQgU1lTVEVNICYgQkFDS0VORCBMT0ci"
    "KSkKICAgICAgICBzZWxmLl9idG5fY2xlYXIgPSBfZ290aGljX2J0bigi4pyXIENsZWFyIikKICAgICAgICBzZWxmLl9idG5fY2xl"
    "YXIuc2V0Rml4ZWRXaWR0aCg4MCkKICAgICAgICBzZWxmLl9idG5fY2xlYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYuY2xlYXIpCiAg"
    "ICAgICAgaGRyLmFkZFN0cmV0Y2goKQogICAgICAgIGhkci5hZGRXaWRnZXQoc2VsZi5fYnRuX2NsZWFyKQogICAgICAgIHJvb3Qu"
    "YWRkTGF5b3V0KGhkcikKCiAgICAgICAgc2VsZi5fZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fZGlzcGxheS5z"
    "ZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3Jv"
    "dW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX1NJTFZFUn07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19C"
    "T1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6ICdDb3VyaWVyIE5ldycsIG1vbm9zcGFjZTsgIgogICAgICAgICAg"
    "ICBmImZvbnQtc2l6ZTogMTBweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5f"
    "ZGlzcGxheSwgMSkKCiAgICBkZWYgbG9nKHNlbGYsIG1lc3NhZ2U6IHN0ciwgbGV2ZWw6IHN0ciA9ICJJTkZPIikgLT4gTm9uZToK"
    "ICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgIGxldmVsX2NvbG9y"
    "cyA9IHsKICAgICAgICAgICAgIklORk8iOiAgQ19TSUxWRVIsCiAgICAgICAgICAgICJPSyI6ICAgIENfR1JFRU4sCiAgICAgICAg"
    "ICAgICJXQVJOIjogIENfR09MRCwKICAgICAgICAgICAgIkVSUk9SIjogQ19CTE9PRCwKICAgICAgICAgICAgIkRFQlVHIjogQ19U"
    "RVhUX0RJTSwKICAgICAgICB9CiAgICAgICAgY29sb3IgPSBsZXZlbF9jb2xvcnMuZ2V0KGxldmVsLnVwcGVyKCksIENfU0lMVkVS"
    "KQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJ"
    "TX07Ij5be3RpbWVzdGFtcH1dPC9zcGFuPiAnCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07Ij57bWVz"
    "c2FnZX08L3NwYW4+JwogICAgICAgICkKICAgICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUo"
    "CiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAgZGVm"
    "IGxvZ19tYW55KHNlbGYsIG1lc3NhZ2VzOiBsaXN0W3N0cl0sIGxldmVsOiBzdHIgPSAiSU5GTyIpIC0+IE5vbmU6CiAgICAgICAg"
    "Zm9yIG1zZyBpbiBtZXNzYWdlczoKICAgICAgICAgICAgbHZsID0gbGV2ZWwKICAgICAgICAgICAgaWYgIuKckyIgaW4gbXNnOiAg"
    "ICBsdmwgPSAiT0siCiAgICAgICAgICAgIGVsaWYgIuKclyIgaW4gbXNnOiAgbHZsID0gIldBUk4iCiAgICAgICAgICAgIGVsaWYg"
    "IkVSUk9SIiBpbiBtc2cudXBwZXIoKTogbHZsID0gIkVSUk9SIgogICAgICAgICAgICBzZWxmLmxvZyhtc2csIGx2bCkKCiAgICBk"
    "ZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kaXNwbGF5LmNsZWFyKCkKCgojIOKUgOKUgCBMRVNTT05TIFRB"
    "QiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTGVzc29uc1RhYihRV2lkZ2V0KToKICAgICIi"
    "IgogICAgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGFuZCBjb2RlIGxlc3NvbnMgYnJvd3Nlci4KICAgIEFkZCwgdmlldywgc2VhcmNo"
    "LCBkZWxldGUgbGVzc29ucy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBkYjogIkxlc3NvbnNMZWFybmVkREIiLCBw"
    "YXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZGIgPSBkYgogICAgICAg"
    "IHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0"
    "KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICAjIEZpbHRlciBiYXIKICAgICAgICBmaWx0ZXJfcm93ID0gUUhC"
    "b3hMYXlvdXQoKQogICAgICAgIHNlbGYuX3NlYXJjaCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fc2VhcmNoLnNldFBsYWNl"
    "aG9sZGVyVGV4dCgiU2VhcmNoIGxlc3NvbnMuLi4iKQogICAgICAgIHNlbGYuX2xhbmdfZmlsdGVyID0gUUNvbWJvQm94KCkKICAg"
    "ICAgICBzZWxmLl9sYW5nX2ZpbHRlci5hZGRJdGVtcyhbIkFsbCIsICJMU0wiLCAiUHl0aG9uIiwgIlB5U2lkZTYiLAogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIkphdmFTY3JpcHQiLCAiT3RoZXIiXSkKICAgICAgICBzZWxmLl9zZWFyY2gu"
    "dGV4dENoYW5nZWQuY29ubmVjdChzZWxmLnJlZnJlc2gpCiAgICAgICAgc2VsZi5fbGFuZ19maWx0ZXIuY3VycmVudFRleHRDaGFu"
    "Z2VkLmNvbm5lY3Qoc2VsZi5yZWZyZXNoKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgiU2VhcmNoOiIpKQog"
    "ICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYuX3NlYXJjaCwgMSkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChR"
    "TGFiZWwoIkxhbmd1YWdlOiIpKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYuX2xhbmdfZmlsdGVyKQogICAgICAg"
    "IHJvb3QuYWRkTGF5b3V0KGZpbHRlcl9yb3cpCgogICAgICAgIGJ0bl9iYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX2Fk"
    "ZCA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIExlc3NvbiIpCiAgICAgICAgYnRuX2RlbCA9IF9nb3RoaWNfYnRuKCLinJcgRGVsZXRl"
    "IikKICAgICAgICBidG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgYnRuX2RlbC5jbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIGJ0bl9iYXIuYWRkV2lkZ2V0KGJ0bl9hZGQpCiAgICAgICAgYnRuX2Jhci5h"
    "ZGRXaWRnZXQoYnRuX2RlbCkKICAgICAgICBidG5fYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJ0bl9i"
    "YXIpCgogICAgICAgIHNlbGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDQpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpv"
    "bnRhbEhlYWRlckxhYmVscygKICAgICAgICAgICAgWyJMYW5ndWFnZSIsICJSZWZlcmVuY2UgS2V5IiwgIlN1bW1hcnkiLCAiRW52"
    "aXJvbm1lbnQiXQogICAgICAgICkKICAgICAgICBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6"
    "ZU1vZGUoCiAgICAgICAgICAgIDIsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90YWJsZS5z"
    "ZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0"
    "Um93cykKICAgICAgICBzZWxmLl90YWJsZS5zZXRBbHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVlKQogICAgICAgIHNlbGYuX3RhYmxl"
    "LnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX3RhYmxlLml0ZW1TZWxlY3Rpb25DaGFu"
    "Z2VkLmNvbm5lY3Qoc2VsZi5fb25fc2VsZWN0KQoKICAgICAgICAjIFVzZSBzcGxpdHRlciBiZXR3ZWVuIHRhYmxlIGFuZCBkZXRh"
    "aWwKICAgICAgICBzcGxpdHRlciA9IFFTcGxpdHRlcihRdC5PcmllbnRhdGlvbi5WZXJ0aWNhbCkKICAgICAgICBzcGxpdHRlci5h"
    "ZGRXaWRnZXQoc2VsZi5fdGFibGUpCgogICAgICAgICMgRGV0YWlsIHBhbmVsCiAgICAgICAgZGV0YWlsX3dpZGdldCA9IFFXaWRn"
    "ZXQoKQogICAgICAgIGRldGFpbF9sYXlvdXQgPSBRVkJveExheW91dChkZXRhaWxfd2lkZ2V0KQogICAgICAgIGRldGFpbF9sYXlv"
    "dXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDQsIDAsIDApCiAgICAgICAgZGV0YWlsX2xheW91dC5zZXRTcGFjaW5nKDIpCgogICAg"
    "ICAgIGRldGFpbF9oZWFkZXIgPSBRSEJveExheW91dCgpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRXaWRnZXQoX3NlY3Rpb25f"
    "bGJsKCLinacgRlVMTCBSVUxFIikpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9idG5f"
    "ZWRpdF9ydWxlID0gX2dvdGhpY19idG4oIkVkaXQiKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Rml4ZWRXaWR0aCg1"
    "MCkKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldENoZWNrYWJsZShUcnVlKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1"
    "bGUudG9nZ2xlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9lZGl0X21vZGUpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZSA9IF9n"
    "b3RoaWNfYnRuKCJTYXZlIikKICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlLnNldEZpeGVkV2lkdGgoNTApCiAgICAgICAgc2Vs"
    "Zi5fYnRuX3NhdmVfcnVsZS5zZXRWaXNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuY2xpY2tlZC5jb25u"
    "ZWN0KHNlbGYuX3NhdmVfcnVsZV9lZGl0KQogICAgICAgIGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9lZGl0X3J1"
    "bGUpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRXaWRnZXQoc2VsZi5fYnRuX3NhdmVfcnVsZSkKICAgICAgICBkZXRhaWxfbGF5"
    "b3V0LmFkZExheW91dChkZXRhaWxfaGVhZGVyKQoKICAgICAgICBzZWxmLl9kZXRhaWwgPSBRVGV4dEVkaXQoKQogICAgICAgIHNl"
    "bGYuX2RldGFpbC5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2RldGFpbC5zZXRNaW5pbXVtSGVpZ2h0KDEyMCkKICAg"
    "ICAgICBzZWxmLl9kZXRhaWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjog"
    "e0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICkKICAg"
    "ICAgICBkZXRhaWxfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9kZXRhaWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KGRldGFp"
    "bF93aWRnZXQpCiAgICAgICAgc3BsaXR0ZXIuc2V0U2l6ZXMoWzMwMCwgMTgwXSkKICAgICAgICByb290LmFkZFdpZGdldChzcGxp"
    "dHRlciwgMSkKCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fZWRpdGluZ19yb3c6"
    "IGludCA9IC0xCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBxICAgID0gc2VsZi5fc2VhcmNoLnRleHQo"
    "KQogICAgICAgIGxhbmcgPSBzZWxmLl9sYW5nX2ZpbHRlci5jdXJyZW50VGV4dCgpCiAgICAgICAgbGFuZyA9ICIiIGlmIGxhbmcg"
    "PT0gIkFsbCIgZWxzZSBsYW5nCiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHNlbGYuX2RiLnNlYXJjaChxdWVyeT1xLCBsYW5ndWFn"
    "ZT1sYW5nKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRz"
    "OgogICAgICAgICAgICByID0gc2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3co"
    "cikKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShy"
    "ZWMuZ2V0KCJsYW5ndWFnZSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAg"
    "ICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJyZWZlcmVuY2Vfa2V5IiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5z"
    "ZXRJdGVtKHIsIDIsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInN1bW1hcnkiLCIiKSkpCiAgICAg"
    "ICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMywKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgi"
    "ZW52aXJvbm1lbnQiLCIiKSkpCgogICAgZGVmIF9vbl9zZWxlY3Qoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90"
    "YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBzZWxmLl9lZGl0aW5nX3JvdyA9IHJvdwogICAgICAgIGlmIDAgPD0gcm93IDwgbGVu"
    "KHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICAgICAgc2VsZi5fZGV0"
    "YWlsLnNldFBsYWluVGV4dCgKICAgICAgICAgICAgICAgIHJlYy5nZXQoImZ1bGxfcnVsZSIsIiIpICsgIlxuXG4iICsKICAgICAg"
    "ICAgICAgICAgICgiUmVzb2x1dGlvbjogIiArIHJlYy5nZXQoInJlc29sdXRpb24iLCIiKSBpZiByZWMuZ2V0KCJyZXNvbHV0aW9u"
    "IikgZWxzZSAiIikKICAgICAgICAgICAgKQogICAgICAgICAgICAjIFJlc2V0IGVkaXQgbW9kZSBvbiBuZXcgc2VsZWN0aW9uCiAg"
    "ICAgICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Q2hlY2tlZChGYWxzZSkKCiAgICBkZWYgX3RvZ2dsZV9lZGl0X21vZGUo"
    "c2VsZiwgZWRpdGluZzogYm9vbCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0UmVhZE9ubHkobm90IGVkaXRpbmcp"
    "CiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRWaXNpYmxlKGVkaXRpbmcpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVs"
    "ZS5zZXRUZXh0KCJDYW5jZWwiIGlmIGVkaXRpbmcgZWxzZSAiRWRpdCIpCiAgICAgICAgaWYgZWRpdGluZzoKICAgICAgICAgICAg"
    "c2VsZi5fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7"
    "Q19HT0xEfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEX0RJTX07ICIKICAgICAgICAgICAg"
    "ICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAg"
    "ICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "ICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZv"
    "bnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIFJlbG9hZCBvcmlnaW5hbCBj"
    "b250ZW50IG9uIGNhbmNlbAogICAgICAgICAgICBzZWxmLl9vbl9zZWxlY3QoKQoKICAgIGRlZiBfc2F2ZV9ydWxlX2VkaXQoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl9lZGl0aW5nX3JvdwogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYu"
    "X3JlY29yZHMpOgogICAgICAgICAgICB0ZXh0ID0gc2VsZi5fZGV0YWlsLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQogICAgICAgICAg"
    "ICAjIFNwbGl0IHJlc29sdXRpb24gYmFjayBvdXQgaWYgcHJlc2VudAogICAgICAgICAgICBpZiAiXG5cblJlc29sdXRpb246ICIg"
    "aW4gdGV4dDoKICAgICAgICAgICAgICAgIHBhcnRzID0gdGV4dC5zcGxpdCgiXG5cblJlc29sdXRpb246ICIsIDEpCiAgICAgICAg"
    "ICAgICAgICBmdWxsX3J1bGUgID0gcGFydHNbMF0uc3RyaXAoKQogICAgICAgICAgICAgICAgcmVzb2x1dGlvbiA9IHBhcnRzWzFd"
    "LnN0cmlwKCkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZSAgPSB0ZXh0CiAgICAgICAgICAgICAg"
    "ICByZXNvbHV0aW9uID0gc2VsZi5fcmVjb3Jkc1tyb3ddLmdldCgicmVzb2x1dGlvbiIsICIiKQogICAgICAgICAgICBzZWxmLl9y"
    "ZWNvcmRzW3Jvd11bImZ1bGxfcnVsZSJdICA9IGZ1bGxfcnVsZQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd11bInJlc29s"
    "dXRpb24iXSA9IHJlc29sdXRpb24KICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fZGIuX3BhdGgsIHNlbGYuX3JlY29yZHMp"
    "CiAgICAgICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Q2hlY2tlZChGYWxzZSkKICAgICAgICAgICAgc2VsZi5yZWZyZXNo"
    "KCkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcu"
    "c2V0V2luZG93VGl0bGUoIkFkZCBMZXNzb24iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcy"
    "fTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAsIDQwMCkKICAgICAgICBmb3JtID0gUUZvcm1MYXlv"
    "dXQoZGxnKQogICAgICAgIGVudiAgPSBRTGluZUVkaXQoIkxTTCIpCiAgICAgICAgbGFuZyA9IFFMaW5lRWRpdCgiTFNMIikKICAg"
    "ICAgICByZWYgID0gUUxpbmVFZGl0KCkKICAgICAgICBzdW1tID0gUUxpbmVFZGl0KCkKICAgICAgICBydWxlID0gUVRleHRFZGl0"
    "KCkKICAgICAgICBydWxlLnNldE1heGltdW1IZWlnaHQoMTAwKQogICAgICAgIHJlcyAgPSBRTGluZUVkaXQoKQogICAgICAgIGxp"
    "bmsgPSBRTGluZUVkaXQoKQogICAgICAgIGZvciBsYWJlbCwgdyBpbiBbCiAgICAgICAgICAgICgiRW52aXJvbm1lbnQ6IiwgZW52"
    "KSwgKCJMYW5ndWFnZToiLCBsYW5nKSwKICAgICAgICAgICAgKCJSZWZlcmVuY2UgS2V5OiIsIHJlZiksICgiU3VtbWFyeToiLCBz"
    "dW1tKSwKICAgICAgICAgICAgKCJGdWxsIFJ1bGU6IiwgcnVsZSksICgiUmVzb2x1dGlvbjoiLCByZXMpLAogICAgICAgICAgICAo"
    "Ikxpbms6IiwgbGluayksCiAgICAgICAgXToKICAgICAgICAgICAgZm9ybS5hZGRSb3cobGFiZWwsIHcpCiAgICAgICAgYnRucyA9"
    "IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIp"
    "CiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAg"
    "ICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCiAgICAg"
    "ICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHNlbGYuX2RiLmFkZCgK"
    "ICAgICAgICAgICAgICAgIGVudmlyb25tZW50PWVudi50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGxhbmd1YWdlPWxh"
    "bmcudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICByZWZlcmVuY2Vfa2V5PXJlZi50ZXh0KCkuc3RyaXAoKSwKICAgICAg"
    "ICAgICAgICAgIHN1bW1hcnk9c3VtbS50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZT1ydWxlLnRvUGxh"
    "aW5UZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIHJlc29sdXRpb249cmVzLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAg"
    "ICAgICAgbGluaz1saW5rLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgog"
    "ICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAg"
    "ICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmVjX2lkID0gc2VsZi5fcmVjb3Jkc1ty"
    "b3ddLmdldCgiaWQiLCIiKQogICAgICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICAgICAg"
    "c2VsZiwgIkRlbGV0ZSBMZXNzb24iLAogICAgICAgICAgICAgICAgIkRlbGV0ZSB0aGlzIGxlc3Nvbj8gQ2Fubm90IGJlIHVuZG9u"
    "ZS4iLAogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRC"
    "dXR0b24uTm8KICAgICAgICAgICAgKQogICAgICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5Z"
    "ZXM6CiAgICAgICAgICAgICAgICBzZWxmLl9kYi5kZWxldGUocmVjX2lkKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkK"
    "CgojIOKUgOKUgCBNT0RVTEUgVFJBQ0tFUiBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1vZHVsZVRyYWNrZXJUYWIoUVdp"
    "ZGdldCk6CiAgICAiIiIKICAgIFBlcnNvbmFsIG1vZHVsZSBwaXBlbGluZSB0cmFja2VyLgogICAgVHJhY2sgcGxhbm5lZC9pbi1w"
    "cm9ncmVzcy9idWlsdCBtb2R1bGVzIGFzIHRoZXkgYXJlIGRlc2lnbmVkLgogICAgRWFjaCBtb2R1bGUgaGFzOiBOYW1lLCBTdGF0"
    "dXMsIERlc2NyaXB0aW9uLCBOb3Rlcy4KICAgIEV4cG9ydCB0byBUWFQgZm9yIHBhc3RpbmcgaW50byBzZXNzaW9ucy4KICAgIElt"
    "cG9ydDogcGFzdGUgYSBmaW5hbGl6ZWQgc3BlYywgaXQgcGFyc2VzIG5hbWUgYW5kIGRldGFpbHMuCiAgICBUaGlzIGlzIGEgZGVz"
    "aWduIG5vdGVib29rIOKAlCBub3QgY29ubmVjdGVkIHRvIGRlY2tfYnVpbGRlcidzIE1PRFVMRSByZWdpc3RyeS4KICAgICIiIgoK"
    "ICAgIFNUQVRVU0VTID0gWyJJZGVhIiwgIkRlc2lnbmluZyIsICJSZWFkeSB0byBCdWlsZCIsICJQYXJ0aWFsIiwgIkJ1aWx0Il0K"
    "CiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAg"
    "ICAgIHNlbGYuX3BhdGggPSBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJtb2R1bGVfdHJhY2tlci5qc29ubCIKICAgICAgICBzZWxm"
    "Ll9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkK"
    "CiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAg"
    "cm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBC"
    "dXR0b24gYmFyCiAgICAgICAgYnRuX2JhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgID0gX2dvdGhp"
    "Y19idG4oIkFkZCBNb2R1bGUiKQogICAgICAgIHNlbGYuX2J0bl9lZGl0ICAgPSBfZ290aGljX2J0bigiRWRpdCIpCiAgICAgICAg"
    "c2VsZi5fYnRuX2RlbGV0ZSA9IF9nb3RoaWNfYnRuKCJEZWxldGUiKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQgPSBfZ290aGlj"
    "X2J0bigiRXhwb3J0IFRYVCIpCiAgICAgICAgc2VsZi5fYnRuX2ltcG9ydCA9IF9nb3RoaWNfYnRuKCJJbXBvcnQgU3BlYyIpCiAg"
    "ICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9lZGl0LCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAg"
    "ICAgICAgICBzZWxmLl9idG5fZXhwb3J0LCBzZWxmLl9idG5faW1wb3J0KToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtV2lkdGgo"
    "ODApCiAgICAgICAgICAgIGIuc2V0TWluaW11bUhlaWdodCgyNikKICAgICAgICAgICAgYnRuX2Jhci5hZGRXaWRnZXQoYikKICAg"
    "ICAgICBidG5fYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJ0bl9iYXIpCgogICAgICAgIHNlbGYuX2J0"
    "bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAgICBzZWxmLl9idG5fZWRpdC5jbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5fZG9fZWRpdCkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAg"
    "ICAgICAgc2VsZi5fYnRuX2V4cG9ydC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZXhwb3J0KQogICAgICAgIHNlbGYuX2J0bl9p"
    "bXBvcnQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2ltcG9ydCkKCiAgICAgICAgIyBUYWJsZQogICAgICAgIHNlbGYuX3RhYmxl"
    "ID0gUVRhYmxlV2lkZ2V0KDAsIDMpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIk1vZHVs"
    "ZSBOYW1lIiwgIlN0YXR1cyIsICJEZXNjcmlwdGlvbiJdKQogICAgICAgIGhoID0gc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRl"
    "cigpCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAg"
    "ICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgwLCAxNjApCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMSwgUUhl"
    "YWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgxLCAxMDApCiAgICAg"
    "ICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYu"
    "X3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlv"
    "ci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2Vs"
    "Zi5fdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2VsZi5fdGFibGUuaXRlbVNlbGVj"
    "dGlvbkNoYW5nZWQuY29ubmVjdChzZWxmLl9vbl9zZWxlY3QpCgogICAgICAgICMgU3BsaXR0ZXIKICAgICAgICBzcGxpdHRlciA9"
    "IFFTcGxpdHRlcihRdC5PcmllbnRhdGlvbi5WZXJ0aWNhbCkKICAgICAgICBzcGxpdHRlci5hZGRXaWRnZXQoc2VsZi5fdGFibGUp"
    "CgogICAgICAgICMgTm90ZXMgcGFuZWwKICAgICAgICBub3Rlc193aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBub3Rlc19sYXlv"
    "dXQgPSBRVkJveExheW91dChub3Rlc193aWRnZXQpCiAgICAgICAgbm90ZXNfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCA0"
    "LCAwLCAwKQogICAgICAgIG5vdGVzX2xheW91dC5zZXRTcGFjaW5nKDIpCiAgICAgICAgbm90ZXNfbGF5b3V0LmFkZFdpZGdldChf"
    "c2VjdGlvbl9sYmwoIuKdpyBOT1RFUyIpKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAg"
    "IHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5LnNldE1pbmlt"
    "dW1IZWlnaHQoMTIwKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNr"
    "Z3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JE"
    "RVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRk"
    "aW5nOiA0cHg7IgogICAgICAgICkKICAgICAgICBub3Rlc19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX25vdGVzX2Rpc3BsYXkpCiAg"
    "ICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KG5vdGVzX3dpZGdldCkKICAgICAgICBzcGxpdHRlci5zZXRTaXplcyhbMjUwLCAxNTBd"
    "KQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNwbGl0dGVyLCAxKQoKICAgICAgICAjIENvdW50IGxhYmVsCiAgICAgICAgc2VsZi5f"
    "Y291bnRfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYuX2NvdW50X2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBm"
    "ImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAg"
    "ICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fY291bnRfbGJsKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRS"
    "b3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9IHNlbGYuX3RhYmxlLnJv"
    "d0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0"
    "ZW0ociwgMCwgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJuYW1lIiwgIiIpKSkKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBR"
    "VGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInN0YXR1cyIsICJJZGVhIikpCiAgICAgICAgICAgICMgQ29sb3IgYnkgc3RhdHVzCiAg"
    "ICAgICAgICAgIHN0YXR1c19jb2xvcnMgPSB7CiAgICAgICAgICAgICAgICAiSWRlYSI6ICAgICAgICAgICAgIENfVEVYVF9ESU0s"
    "CiAgICAgICAgICAgICAgICAiRGVzaWduaW5nIjogICAgICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgICAgICAiUmVhZHkgdG8g"
    "QnVpbGQiOiAgIENfUFVSUExFLAogICAgICAgICAgICAgICAgIlBhcnRpYWwiOiAgICAgICAgICAiI2NjODg0NCIsCiAgICAgICAg"
    "ICAgICAgICAiQnVpbHQiOiAgICAgICAgICAgIENfR1JFRU4sCiAgICAgICAgICAgIH0KICAgICAgICAgICAgc3RhdHVzX2l0ZW0u"
    "c2V0Rm9yZWdyb3VuZCgKICAgICAgICAgICAgICAgIFFDb2xvcihzdGF0dXNfY29sb3JzLmdldChyZWMuZ2V0KCJzdGF0dXMiLCJJ"
    "ZGVhIiksIENfVEVYVF9ESU0pKQogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMSwgc3Rh"
    "dHVzX2l0ZW0pCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMiwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdl"
    "dEl0ZW0ocmVjLmdldCgiZGVzY3JpcHRpb24iLCAiIilbOjgwXSkpCiAgICAgICAgY291bnRzID0ge30KICAgICAgICBmb3IgcmVj"
    "IGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIHMgPSByZWMuZ2V0KCJzdGF0dXMiLCAiSWRlYSIpCiAgICAgICAgICAgIGNv"
    "dW50c1tzXSA9IGNvdW50cy5nZXQocywgMCkgKyAxCiAgICAgICAgY291bnRfc3RyID0gIiAgIi5qb2luKGYie3N9OiB7bn0iIGZv"
    "ciBzLCBuIGluIGNvdW50cy5pdGVtcygpKQogICAgICAgIHNlbGYuX2NvdW50X2xibC5zZXRUZXh0KAogICAgICAgICAgICBmIlRv"
    "dGFsOiB7bGVuKHNlbGYuX3JlY29yZHMpfSAgIHtjb3VudF9zdHJ9IgogICAgICAgICkKCiAgICBkZWYgX29uX3NlbGVjdChzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVu"
    "KHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICAgICAgc2VsZi5fbm90"
    "ZXNfZGlzcGxheS5zZXRQbGFpblRleHQocmVjLmdldCgibm90ZXMiLCAiIikpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICBzZWxmLl9vcGVuX2VkaXRfZGlhbG9nKCkKCiAgICBkZWYgX2RvX2VkaXQoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToK"
    "ICAgICAgICAgICAgc2VsZi5fb3Blbl9lZGl0X2RpYWxvZyhzZWxmLl9yZWNvcmRzW3Jvd10sIHJvdykKCiAgICBkZWYgX29wZW5f"
    "ZWRpdF9kaWFsb2coc2VsZiwgcmVjOiBkaWN0ID0gTm9uZSwgcm93OiBpbnQgPSAtMSkgLT4gTm9uZToKICAgICAgICBkbGcgPSBR"
    "RGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJNb2R1bGUiIGlmIG5vdCByZWMgZWxzZSBmIkVkaXQ6IHty"
    "ZWMuZ2V0KCduYW1lJywnJyl9IikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9y"
    "OiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5yZXNpemUoNTQwLCA0NDApCiAgICAgICAgZm9ybSA9IFFWQm94TGF5b3V0KGRsZykK"
    "CiAgICAgICAgbmFtZV9maWVsZCA9IFFMaW5lRWRpdChyZWMuZ2V0KCJuYW1lIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAg"
    "bmFtZV9maWVsZC5zZXRQbGFjZWhvbGRlclRleHQoIk1vZHVsZSBuYW1lIikKCiAgICAgICAgc3RhdHVzX2NvbWJvID0gUUNvbWJv"
    "Qm94KCkKICAgICAgICBzdGF0dXNfY29tYm8uYWRkSXRlbXMoc2VsZi5TVEFUVVNFUykKICAgICAgICBpZiByZWM6CiAgICAgICAg"
    "ICAgIGlkeCA9IHN0YXR1c19jb21iby5maW5kVGV4dChyZWMuZ2V0KCJzdGF0dXMiLCJJZGVhIikpCiAgICAgICAgICAgIGlmIGlk"
    "eCA+PSAwOgogICAgICAgICAgICAgICAgc3RhdHVzX2NvbWJvLnNldEN1cnJlbnRJbmRleChpZHgpCgogICAgICAgIGRlc2NfZmll"
    "bGQgPSBRTGluZUVkaXQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBkZXNjX2ZpZWxk"
    "LnNldFBsYWNlaG9sZGVyVGV4dCgiT25lLWxpbmUgZGVzY3JpcHRpb24iKQoKICAgICAgICBub3Rlc19maWVsZCA9IFFUZXh0RWRp"
    "dCgpCiAgICAgICAgbm90ZXNfZmllbGQuc2V0UGxhaW5UZXh0KHJlYy5nZXQoIm5vdGVzIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAg"
    "ICAgICAgbm90ZXNfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KAogICAgICAgICAgICAiRnVsbCBub3RlcyDigJQgc3BlYywgaWRl"
    "YXMsIHJlcXVpcmVtZW50cywgZWRnZSBjYXNlcy4uLiIKICAgICAgICApCiAgICAgICAgbm90ZXNfZmllbGQuc2V0TWluaW11bUhl"
    "aWdodCgyMDApCgogICAgICAgIGZvciBsYWJlbCwgd2lkZ2V0IGluIFsKICAgICAgICAgICAgKCJOYW1lOiIsIG5hbWVfZmllbGQp"
    "LAogICAgICAgICAgICAoIlN0YXR1czoiLCBzdGF0dXNfY29tYm8pLAogICAgICAgICAgICAoIkRlc2NyaXB0aW9uOiIsIGRlc2Nf"
    "ZmllbGQpLAogICAgICAgICAgICAoIk5vdGVzOiIsIG5vdGVzX2ZpZWxkKSwKICAgICAgICBdOgogICAgICAgICAgICByb3dfbGF5"
    "b3V0ID0gUUhCb3hMYXlvdXQoKQogICAgICAgICAgICBsYmwgPSBRTGFiZWwobGFiZWwpCiAgICAgICAgICAgIGxibC5zZXRGaXhl"
    "ZFdpZHRoKDkwKQogICAgICAgICAgICByb3dfbGF5b3V0LmFkZFdpZGdldChsYmwpCiAgICAgICAgICAgIHJvd19sYXlvdXQuYWRk"
    "V2lkZ2V0KHdpZGdldCkKICAgICAgICAgICAgZm9ybS5hZGRMYXlvdXQocm93X2xheW91dCkKCiAgICAgICAgYnRuX3JvdyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBidG5fc2F2ZSAgID0gX2dvdGhpY19idG4oIlNhdmUiKQogICAgICAgIGJ0bl9jYW5jZWwgPSBf"
    "Z290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBidG5fc2F2ZS5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCkKICAgICAgICBi"
    "dG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9zYXZlKQog"
    "ICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgZm9ybS5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICAg"
    "ICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIG5ld19yZWMgPSB7CiAg"
    "ICAgICAgICAgICAgICAiaWQiOiAgICAgICAgICByZWMuZ2V0KCJpZCIsIHN0cih1dWlkLnV1aWQ0KCkpKSBpZiByZWMgZWxzZSBz"
    "dHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgICAgICJuYW1lIjogICAgICAgIG5hbWVfZmllbGQudGV4dCgpLnN0cmlwKCks"
    "CiAgICAgICAgICAgICAgICAic3RhdHVzIjogICAgICBzdGF0dXNfY29tYm8uY3VycmVudFRleHQoKSwKICAgICAgICAgICAgICAg"
    "ICJkZXNjcmlwdGlvbiI6IGRlc2NfZmllbGQudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICBu"
    "b3Rlc19maWVsZC50b1BsYWluVGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAiY3JlYXRlZCI6ICAgICByZWMuZ2V0KCJj"
    "cmVhdGVkIiwgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCkpIGlmIHJlYyBlbHNlIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgp"
    "LAogICAgICAgICAgICAgICAgIm1vZGlmaWVkIjogICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAgICAgICAgIH0K"
    "ICAgICAgICAgICAgaWYgcm93ID49IDA6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd10gPSBuZXdfcmVjCiAgICAg"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChuZXdfcmVjKQogICAgICAgICAgICB3cml0"
    "ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9f"
    "ZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgMCA8"
    "PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIG5hbWUgPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJuYW1l"
    "IiwidGhpcyBtb2R1bGUiKQogICAgICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICAgICAg"
    "c2VsZiwgIkRlbGV0ZSBNb2R1bGUiLAogICAgICAgICAgICAgICAgZiJEZWxldGUgJ3tuYW1lfSc/IENhbm5vdCBiZSB1bmRvbmUu"
    "IiwKICAgICAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0"
    "dG9uLk5vCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVz"
    "OgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5wb3Aocm93KQogICAgICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5f"
    "cGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19leHBvcnQoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGV4cG9ydF9kaXIgPSBjZmdfcGF0aCgiZXhwb3J0cyIpCiAgICAg"
    "ICAgICAgIGV4cG9ydF9kaXIubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICB0cyA9IGRhdGV0"
    "aW1lLm5vdygpLnN0cmZ0aW1lKCIlWSVtJWRfJUglTSVTIikKICAgICAgICAgICAgb3V0X3BhdGggPSBleHBvcnRfZGlyIC8gZiJt"
    "b2R1bGVzX3t0c30udHh0IgogICAgICAgICAgICBsaW5lcyA9IFsKICAgICAgICAgICAgICAgICJFQ0hPIERFQ0sg4oCUIE1PRFVM"
    "RSBUUkFDS0VSIEVYUE9SVCIsCiAgICAgICAgICAgICAgICBmIkV4cG9ydGVkOiB7ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVZ"
    "LSVtLSVkICVIOiVNOiVTJyl9IiwKICAgICAgICAgICAgICAgIGYiVG90YWwgbW9kdWxlczoge2xlbihzZWxmLl9yZWNvcmRzKX0i"
    "LAogICAgICAgICAgICAgICAgIj0iICogNjAsCiAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgXQogICAgICAgICAgICBm"
    "b3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgICAgICBsaW5lcy5leHRlbmQoWwogICAgICAgICAgICAgICAgICAg"
    "IGYiTU9EVUxFOiB7cmVjLmdldCgnbmFtZScsJycpfSIsCiAgICAgICAgICAgICAgICAgICAgZiJTdGF0dXM6IHtyZWMuZ2V0KCdz"
    "dGF0dXMnLCcnKX0iLAogICAgICAgICAgICAgICAgICAgIGYiRGVzY3JpcHRpb246IHtyZWMuZ2V0KCdkZXNjcmlwdGlvbicsJycp"
    "fSIsCiAgICAgICAgICAgICAgICAgICAgIiIsCiAgICAgICAgICAgICAgICAgICAgIk5vdGVzOiIsCiAgICAgICAgICAgICAgICAg"
    "ICAgcmVjLmdldCgibm90ZXMiLCIiKSwKICAgICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgICAgICAgICAiLSIgKiA0"
    "MCwKICAgICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgICAgIF0pCiAgICAgICAgICAgIG91dF9wYXRoLndyaXRlX3Rl"
    "eHQoIlxuIi5qb2luKGxpbmVzKSwgZW5jb2Rpbmc9InV0Zi04IikKICAgICAgICAgICAgUUFwcGxpY2F0aW9uLmNsaXBib2FyZCgp"
    "LnNldFRleHQoIlxuIi5qb2luKGxpbmVzKSkKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oCiAgICAgICAgICAg"
    "ICAgICBzZWxmLCAiRXhwb3J0ZWQiLAogICAgICAgICAgICAgICAgZiJNb2R1bGUgdHJhY2tlciBleHBvcnRlZCB0bzpcbntvdXRf"
    "cGF0aH1cblxuQWxzbyBjb3BpZWQgdG8gY2xpcGJvYXJkLiIKICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24g"
    "YXMgZToKICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2FybmluZyhzZWxmLCAiRXhwb3J0IEVycm9yIiwgc3RyKGUpKQoKICAgIGRl"
    "ZiBfZG9faW1wb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiSW1wb3J0IGEgbW9kdWxlIHNwZWMgZnJvbSBjbGlwYm9hcmQg"
    "b3IgdHlwZWQgdGV4dC4iIiIKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJJ"
    "bXBvcnQgTW9kdWxlIFNwZWMiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6"
    "IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAsIDM0MCkKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChkbGcp"
    "CiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChRTGFiZWwoCiAgICAgICAgICAgICJQYXN0ZSBhIG1vZHVsZSBzcGVjIGJlbG93Llxu"
    "IgogICAgICAgICAgICAiRmlyc3QgbGluZSB3aWxsIGJlIHVzZWQgYXMgdGhlIG1vZHVsZSBuYW1lLiIKICAgICAgICApKQogICAg"
    "ICAgIHRleHRfZmllbGQgPSBRVGV4dEVkaXQoKQogICAgICAgIHRleHRfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KCJQYXN0ZSBt"
    "b2R1bGUgc3BlYyBoZXJlLi4uIikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHRleHRfZmllbGQsIDEpCiAgICAgICAgYnRuX3Jv"
    "dyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fb2sgICAgID0gX2dvdGhpY19idG4oIkltcG9ydCIpCiAgICAgICAgYnRuX2Nh"
    "bmNlbCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIGJ0bl9vay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCkKICAg"
    "ICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9v"
    "aykKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2FuY2VsKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoYnRuX3JvdykK"
    "CiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHJhdyA9IHRl"
    "eHRfZmllbGQudG9QbGFpblRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIG5vdCByYXc6CiAgICAgICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICAgICAgbGluZXMgPSByYXcuc3BsaXRsaW5lcygpCiAgICAgICAgICAgICMgRmlyc3Qgbm9uLWVtcHR5IGxpbmUg"
    "PSBuYW1lCiAgICAgICAgICAgIG5hbWUgPSAiIgogICAgICAgICAgICBmb3IgbGluZSBpbiBsaW5lczoKICAgICAgICAgICAgICAg"
    "IGlmIGxpbmUuc3RyaXAoKToKICAgICAgICAgICAgICAgICAgICBuYW1lID0gbGluZS5zdHJpcCgpCiAgICAgICAgICAgICAgICAg"
    "ICAgYnJlYWsKICAgICAgICAgICAgbmV3X3JlYyA9IHsKICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHN0cih1dWlkLnV1"
    "aWQ0KCkpLAogICAgICAgICAgICAgICAgIm5hbWUiOiAgICAgICAgbmFtZVs6NjBdLAogICAgICAgICAgICAgICAgInN0YXR1cyI6"
    "ICAgICAgIklkZWEiLAogICAgICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogIiIsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAg"
    "ICAgICByYXcsCiAgICAgICAgICAgICAgICAiY3JlYXRlZCI6ICAgICBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAgICAg"
    "ICAgICAgICAgICJtb2RpZmllZCI6ICAgIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICB9CiAgICAgICAg"
    "ICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKG5ld19yZWMpCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYu"
    "X3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgoKIyDilIDilIAgUEFTUyA1IENPTVBMRVRFIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAojIEFsbCB0YWIgY29udGVudCBjbGFzc2VzIGRlZmluZWQuCiMgU0xTY2Fuc1RhYjogcmVidWls"
    "dCDigJQgRGVsZXRlIGFkZGVkLCBNb2RpZnkgZml4ZWQsIHRpbWVzdGFtcCBwYXJzZXIgZml4ZWQsCiMgICAgICAgICAgICAgY2Fy"
    "ZC9ncmltb2lyZSBzdHlsZSwgY29weS10by1jbGlwYm9hcmQgY29udGV4dCBtZW51LgojIFNMQ29tbWFuZHNUYWI6IGdvdGhpYyB0"
    "YWJsZSwg4qeJIENvcHkgQ29tbWFuZCBidXR0b24uCiMgSm9iVHJhY2tlclRhYjogZnVsbCByZWJ1aWxkIOKAlCBtdWx0aS1zZWxl"
    "Y3QsIGFyY2hpdmUvcmVzdG9yZSwgQ1NWL1RTViBleHBvcnQuCiMgU2VsZlRhYjogaW5uZXIgc2FuY3R1bSBmb3IgaWRsZSBuYXJy"
    "YXRpdmUgYW5kIHJlZmxlY3Rpb24gb3V0cHV0LgojIERpYWdub3N0aWNzVGFiOiBzdHJ1Y3R1cmVkIGxvZyB3aXRoIGxldmVsLWNv"
    "bG9yZWQgb3V0cHV0LgojIExlc3NvbnNUYWI6IExTTCBGb3JiaWRkZW4gUnVsZXNldCBicm93c2VyIHdpdGggYWRkL2RlbGV0ZS9z"
    "ZWFyY2guCiMKIyBOZXh0OiBQYXNzIDYg4oCUIE1haW4gV2luZG93CiMgKE1vcmdhbm5hRGVjayBjbGFzcywgZnVsbCBsYXlvdXQs"
    "IEFQU2NoZWR1bGVyLCBmaXJzdC1ydW4gZmxvdywKIyAgZGVwZW5kZW5jeSBib290c3RyYXAsIHNob3J0Y3V0IGNyZWF0aW9uLCBz"
    "dGFydHVwIHNlcXVlbmNlKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyA2OiBNQUlOIFdJTkRPVyAm"
    "IEVOVFJZIFBPSU5UCiMKIyBDb250YWluczoKIyAgIGJvb3RzdHJhcF9jaGVjaygpICAgICDigJQgZGVwZW5kZW5jeSB2YWxpZGF0"
    "aW9uICsgYXV0by1pbnN0YWxsIGJlZm9yZSBVSQojICAgRmlyc3RSdW5EaWFsb2cgICAgICAgIOKAlCBtb2RlbCBwYXRoICsgY29u"
    "bmVjdGlvbiB0eXBlIHNlbGVjdGlvbgojICAgSm91cm5hbFNpZGViYXIgICAgICAgIOKAlCBjb2xsYXBzaWJsZSBsZWZ0IHNpZGVi"
    "YXIgKHNlc3Npb24gYnJvd3NlciArIGpvdXJuYWwpCiMgICBUb3Jwb3JQYW5lbCAgICAgICAgICAg4oCUIEFXQUtFIC8gQVVUTyAv"
    "IFNVU1BFTkQgc3RhdGUgdG9nZ2xlCiMgICBNb3JnYW5uYURlY2sgICAgICAgICAg4oCUIG1haW4gd2luZG93LCBmdWxsIGxheW91"
    "dCwgYWxsIHNpZ25hbCBjb25uZWN0aW9ucwojICAgbWFpbigpICAgICAgICAgICAgICAgIOKAlCBlbnRyeSBwb2ludCB3aXRoIGJv"
    "b3RzdHJhcCBzZXF1ZW5jZQojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0IHN1YnByb2Nlc3MKCgojIOKUgOKUgCBQUkUtTEFVTkNIIERF"
    "UEVOREVOQ1kgQk9PVFNUUkFQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYg"
    "Ym9vdHN0cmFwX2NoZWNrKCkgLT4gTm9uZToKICAgICIiIgogICAgUnVucyBCRUZPUkUgUUFwcGxpY2F0aW9uIGlzIGNyZWF0ZWQu"
    "CiAgICBDaGVja3MgZm9yIFB5U2lkZTYgc2VwYXJhdGVseSAoY2FuJ3Qgc2hvdyBHVUkgd2l0aG91dCBpdCkuCiAgICBBdXRvLWlu"
    "c3RhbGxzIGFsbCBvdGhlciBtaXNzaW5nIG5vbi1jcml0aWNhbCBkZXBzIHZpYSBwaXAuCiAgICBWYWxpZGF0ZXMgaW5zdGFsbHMg"
    "c3VjY2VlZGVkLgogICAgV3JpdGVzIHJlc3VsdHMgdG8gYSBib290c3RyYXAgbG9nIGZvciBEaWFnbm9zdGljcyB0YWIgdG8gcGlj"
    "ayB1cC4KICAgICIiIgogICAgIyDilIDilIAgU3RlcCAxOiBDaGVjayBQeVNpZGU2IChjYW4ndCBhdXRvLWluc3RhbGwgd2l0aG91"
    "dCBpdCBhbHJlYWR5IHByZXNlbnQpIOKUgAogICAgdHJ5OgogICAgICAgIGltcG9ydCBQeVNpZGU2ICAjIG5vcWEKICAgIGV4Y2Vw"
    "dCBJbXBvcnRFcnJvcjoKICAgICAgICAjIE5vIEdVSSBhdmFpbGFibGUg4oCUIHVzZSBXaW5kb3dzIG5hdGl2ZSBkaWFsb2cgdmlh"
    "IGN0eXBlcwogICAgICAgIHRyeToKICAgICAgICAgICAgaW1wb3J0IGN0eXBlcwogICAgICAgICAgICBjdHlwZXMud2luZGxsLnVz"
    "ZXIzMi5NZXNzYWdlQm94VygKICAgICAgICAgICAgICAgIDAsCiAgICAgICAgICAgICAgICAiUHlTaWRlNiBpcyByZXF1aXJlZCBi"
    "dXQgbm90IGluc3RhbGxlZC5cblxuIgogICAgICAgICAgICAgICAgIk9wZW4gYSB0ZXJtaW5hbCBhbmQgcnVuOlxuXG4iCiAgICAg"
    "ICAgICAgICAgICAiICAgIHBpcCBpbnN0YWxsIFB5U2lkZTZcblxuIgogICAgICAgICAgICAgICAgZiJUaGVuIHJlc3RhcnQge0RF"
    "Q0tfTkFNRX0uIiwKICAgICAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0g4oCUIE1pc3NpbmcgRGVwZW5kZW5jeSIsCiAgICAgICAg"
    "ICAgICAgICAweDEwICAjIE1CX0lDT05FUlJPUgogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAg"
    "ICAgICAgcHJpbnQoIkNSSVRJQ0FMOiBQeVNpZGU2IG5vdCBpbnN0YWxsZWQuIFJ1bjogcGlwIGluc3RhbGwgUHlTaWRlNiIpCiAg"
    "ICAgICAgc3lzLmV4aXQoMSkKCiAgICAjIOKUgOKUgCBTdGVwIDI6IEF1dG8taW5zdGFsbCBvdGhlciBtaXNzaW5nIGRlcHMg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICBfQVVUT19JTlNUQUxMID0gWwogICAgICAgICgiYXBzY2hlZHVsZXIiLCAgICAgICAgICAg"
    "ICAgICJhcHNjaGVkdWxlciIpLAogICAgICAgICgibG9ndXJ1IiwgICAgICAgICAgICAgICAgICAgICJsb2d1cnUiKSwKICAgICAg"
    "ICAoInB5Z2FtZSIsICAgICAgICAgICAgICAgICAgICAicHlnYW1lIiksCiAgICAgICAgKCJweXdpbjMyIiwgICAgICAgICAgICAg"
    "ICAgICAgInB5d2luMzIiKSwKICAgICAgICAoInBzdXRpbCIsICAgICAgICAgICAgICAgICAgICAicHN1dGlsIiksCiAgICAgICAg"
    "KCJyZXF1ZXN0cyIsICAgICAgICAgICAgICAgICAgInJlcXVlc3RzIiksCiAgICAgICAgKCJnb29nbGUtYXBpLXB5dGhvbi1jbGll"
    "bnQiLCAgImdvb2dsZWFwaWNsaWVudCIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgtb2F1dGhsaWIiLCAgICAgICJnb29nbGVfYXV0"
    "aF9vYXV0aGxpYiIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgiLCAgICAgICAgICAgICAgICJnb29nbGUuYXV0aCIpLAogICAgXQoK"
    "ICAgIGltcG9ydCBpbXBvcnRsaWIKICAgIGJvb3RzdHJhcF9sb2cgPSBbXQoKICAgIGZvciBwaXBfbmFtZSwgaW1wb3J0X25hbWUg"
    "aW4gX0FVVE9fSU5TVEFMTDoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9ydF9u"
    "YW1lKQogICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZChmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0g4pyTIikKICAgICAg"
    "ICBleGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgZiJb"
    "Qk9PVFNUUkFQXSB7cGlwX25hbWV9IG1pc3Npbmcg4oCUIGluc3RhbGxpbmcuLi4iCiAgICAgICAgICAgICkKICAgICAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICAgICAgcmVzdWx0ID0gc3VicHJvY2Vzcy5ydW4oCiAgICAgICAgICAgICAgICAgICAgW3N5cy5leGVj"
    "dXRhYmxlLCAiLW0iLCAicGlwIiwgImluc3RhbGwiLAogICAgICAgICAgICAgICAgICAgICBwaXBfbmFtZSwgIi0tcXVpZXQiLCAi"
    "LS1uby13YXJuLXNjcmlwdC1sb2NhdGlvbiJdLAogICAgICAgICAgICAgICAgICAgIGNhcHR1cmVfb3V0cHV0PVRydWUsIHRleHQ9"
    "VHJ1ZSwgdGltZW91dD0xMjAKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIHJlc3VsdC5yZXR1cm5jb2RlID09"
    "IDA6CiAgICAgICAgICAgICAgICAgICAgIyBWYWxpZGF0ZSBpdCBhY3R1YWxseSBpbXBvcnRlZCBub3cKICAgICAgICAgICAgICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9ydF9uYW1lKQogICAg"
    "ICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JP"
    "T1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsZWQg4pyTIgogICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAg"
    "ICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsIGFwcGVhcmVkIHRvICIKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIGYic3VjY2VlZCBidXQgaW1wb3J0IHN0aWxsIGZhaWxzIOKAlCByZXN0YXJ0IG1heSAi"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmImJlIHJlcXVpcmVkLiIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3RhbGwgZmFpbGVkOiAiCiAgICAgICAgICAgICAgICAgICAgICAg"
    "IGYie3Jlc3VsdC5zdGRlcnJbOjIwMF19IgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IHN1YnByb2Nl"
    "c3MuVGltZW91dEV4cGlyZWQ6CiAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAg"
    "ICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbCB0aW1lZCBvdXQuIgogICAgICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAg"
    "ICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbCBlcnJvcjoge2V9IgogICAgICAgICAgICAgICAgKQoKICAg"
    "ICMg4pSA4pSAIFN0ZXAgMzogV3JpdGUgYm9vdHN0cmFwIGxvZyBmb3IgRGlhZ25vc3RpY3MgdGFiIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgdHJ5OgogICAgICAgIGxvZ19w"
    "YXRoID0gU0NSSVBUX0RJUiAvICJsb2dzIiAvICJib290c3RyYXBfbG9nLnR4dCIKICAgICAgICB3aXRoIGxvZ19wYXRoLm9wZW4o"
    "InciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICBmLndyaXRlKCJcbiIuam9pbihib290c3RyYXBfbG9nKSkK"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcGFzcwoKCiMg4pSA4pSAIEZJUlNUIFJVTiBESUFMT0cg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACmNsYXNzIEZpcnN0UnVuRGlhbG9nKFFEaWFsb2cpOgogICAgIiIiCiAgICBTaG93biBvbiBmaXJzdCBsYXVu"
    "Y2ggd2hlbiBjb25maWcuanNvbiBkb2Vzbid0IGV4aXN0LgogICAgQ29sbGVjdHMgbW9kZWwgY29ubmVjdGlvbiB0eXBlIGFuZCBw"
    "YXRoL2tleS4KICAgIFZhbGlkYXRlcyBjb25uZWN0aW9uIGJlZm9yZSBhY2NlcHRpbmcuCiAgICBXcml0ZXMgY29uZmlnLmpzb24g"
    "b24gc3VjY2Vzcy4KICAgIENyZWF0ZXMgZGVza3RvcCBzaG9ydGN1dC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBw"
    "YXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5zZXRXaW5kb3dUaXRsZShm"
    "IuKcpiB7REVDS19OQU1FLnVwcGVyKCl9IOKAlCBGSVJTVCBBV0FLRU5JTkciKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldChT"
    "VFlMRSkKICAgICAgICBzZWxmLnNldEZpeGVkU2l6ZSg1MjAsIDQwMCkKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCgogICAgZGVm"
    "IF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0"
    "U3BhY2luZygxMCkKCiAgICAgICAgdGl0bGUgPSBRTGFiZWwoZiLinKYge0RFQ0tfTkFNRS51cHBlcigpfSDigJQgRklSU1QgQVdB"
    "S0VOSU5HIOKcpiIpCiAgICAgICAgdGl0bGUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07"
    "IGZvbnQtc2l6ZTogMTRweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9O"
    "VH0sIHNlcmlmOyBsZXR0ZXItc3BhY2luZzogMnB4OyIKICAgICAgICApCiAgICAgICAgdGl0bGUuc2V0QWxpZ25tZW50KFF0LkFs"
    "aWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQodGl0bGUpCgogICAgICAgIHN1YiA9IFFMYWJl"
    "bCgKICAgICAgICAgICAgZiJDb25maWd1cmUgdGhlIHZlc3NlbCBiZWZvcmUge0RFQ0tfTkFNRX0gbWF5IGF3YWtlbi5cbiIKICAg"
    "ICAgICAgICAgIkFsbCBzZXR0aW5ncyBhcmUgc3RvcmVkIGxvY2FsbHkuIE5vdGhpbmcgbGVhdmVzIHRoaXMgbWFjaGluZS4iCiAg"
    "ICAgICAgKQogICAgICAgIHN1Yi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQt"
    "c2l6ZTogMTBweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAg"
    "ICAgICBzdWIuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQo"
    "c3ViKQoKICAgICAgICAjIOKUgOKUgCBDb25uZWN0aW9uIHR5cGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgQUkgQ09OTkVDVElP"
    "TiBUWVBFIikpCiAgICAgICAgc2VsZi5fdHlwZV9jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc2VsZi5fdHlwZV9jb21iby5h"
    "ZGRJdGVtcyhbCiAgICAgICAgICAgICJMb2NhbCBtb2RlbCBmb2xkZXIgKHRyYW5zZm9ybWVycykiLAogICAgICAgICAgICAiT2xs"
    "YW1hIChsb2NhbCBzZXJ2aWNlKSIsCiAgICAgICAgICAgICJDbGF1ZGUgQVBJIChBbnRocm9waWMpIiwKICAgICAgICAgICAgIk9w"
    "ZW5BSSBBUEkiLAogICAgICAgIF0pCiAgICAgICAgc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXhDaGFuZ2VkLmNvbm5lY3Qo"
    "c2VsZi5fb25fdHlwZV9jaGFuZ2UpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdHlwZV9jb21ibykKCiAgICAgICAgIyDi"
    "lIDilIAgRHluYW1pYyBjb25uZWN0aW9uIGZpZWxkcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9z"
    "dGFjayA9IFFTdGFja2VkV2lkZ2V0KCkKCiAgICAgICAgIyBQYWdlIDA6IExvY2FsIHBhdGgKICAgICAgICBwMCA9IFFXaWRnZXQo"
    "KQogICAgICAgIGwwID0gUUhCb3hMYXlvdXQocDApCiAgICAgICAgbDAuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAg"
    "ICAgc2VsZi5fbG9jYWxfcGF0aCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fbG9jYWxfcGF0aC5zZXRQbGFjZWhvbGRlclRl"
    "eHQoCiAgICAgICAgICAgIHIiRDpcQUlcTW9kZWxzXGRvbHBoaW4tOGIiCiAgICAgICAgKQogICAgICAgIGJ0bl9icm93c2UgPSBf"
    "Z290aGljX2J0bigiQnJvd3NlIikKICAgICAgICBidG5fYnJvd3NlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9icm93c2VfbW9kZWwp"
    "CiAgICAgICAgbDAuYWRkV2lkZ2V0KHNlbGYuX2xvY2FsX3BhdGgpOyBsMC5hZGRXaWRnZXQoYnRuX2Jyb3dzZSkKICAgICAgICBz"
    "ZWxmLl9zdGFjay5hZGRXaWRnZXQocDApCgogICAgICAgICMgUGFnZSAxOiBPbGxhbWEgbW9kZWwgbmFtZQogICAgICAgIHAxID0g"
    "UVdpZGdldCgpCiAgICAgICAgbDEgPSBRSEJveExheW91dChwMSkKICAgICAgICBsMS5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAs"
    "MCkKICAgICAgICBzZWxmLl9vbGxhbWFfbW9kZWwgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX29sbGFtYV9tb2RlbC5zZXRQ"
    "bGFjZWhvbGRlclRleHQoImRvbHBoaW4tMi42LTdiIikKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fb2xsYW1hX21vZGVsKQog"
    "ICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMSkKCiAgICAgICAgIyBQYWdlIDI6IENsYXVkZSBBUEkga2V5CiAgICAgICAg"
    "cDIgPSBRV2lkZ2V0KCkKICAgICAgICBsMiA9IFFWQm94TGF5b3V0KHAyKQogICAgICAgIGwyLnNldENvbnRlbnRzTWFyZ2lucygw"
    "LDAsMCwwKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkgICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fY2xhdWRlX2tleS5z"
    "ZXRQbGFjZWhvbGRlclRleHQoInNrLWFudC0uLi4iKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkuc2V0RWNob01vZGUoUUxpbmVF"
    "ZGl0LkVjaG9Nb2RlLlBhc3N3b3JkKQogICAgICAgIHNlbGYuX2NsYXVkZV9tb2RlbCA9IFFMaW5lRWRpdCgiY2xhdWRlLXNvbm5l"
    "dC00LTYiKQogICAgICAgIGwyLmFkZFdpZGdldChRTGFiZWwoIkFQSSBLZXk6IikpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYu"
    "X2NsYXVkZV9rZXkpCiAgICAgICAgbDIuYWRkV2lkZ2V0KFFMYWJlbCgiTW9kZWw6IikpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNl"
    "bGYuX2NsYXVkZV9tb2RlbCkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDIpCgogICAgICAgICMgUGFnZSAzOiBPcGVu"
    "QUkKICAgICAgICBwMyA9IFFXaWRnZXQoKQogICAgICAgIGwzID0gUVZCb3hMYXlvdXQocDMpCiAgICAgICAgbDMuc2V0Q29udGVu"
    "dHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fb2FpX2tleSAgID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9vYWlf"
    "a2V5LnNldFBsYWNlaG9sZGVyVGV4dCgic2stLi4uIikKICAgICAgICBzZWxmLl9vYWlfa2V5LnNldEVjaG9Nb2RlKFFMaW5lRWRp"
    "dC5FY2hvTW9kZS5QYXNzd29yZCkKICAgICAgICBzZWxmLl9vYWlfbW9kZWwgPSBRTGluZUVkaXQoImdwdC00byIpCiAgICAgICAg"
    "bDMuYWRkV2lkZ2V0KFFMYWJlbCgiQVBJIEtleToiKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fb2FpX2tleSkKICAgICAg"
    "ICBsMy5hZGRXaWRnZXQoUUxhYmVsKCJNb2RlbDoiKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fb2FpX21vZGVsKQogICAg"
    "ICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMykKCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fc3RhY2spCgogICAgICAg"
    "ICMg4pSA4pSAIFRlc3QgKyBzdGF0dXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICAgICAgdGVzdF9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX3Rlc3QgPSBfZ290"
    "aGljX2J0bigiVGVzdCBDb25uZWN0aW9uIikKICAgICAgICBzZWxmLl9idG5fdGVzdC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdGVz"
    "dF9jb25uZWN0aW9uKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xi"
    "bC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgIgogICAg"
    "ICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICB0ZXN0X3Jvdy5hZGRX"
    "aWRnZXQoc2VsZi5fYnRuX3Rlc3QpCiAgICAgICAgdGVzdF9yb3cuYWRkV2lkZ2V0KHNlbGYuX3N0YXR1c19sYmwsIDEpCiAgICAg"
    "ICAgcm9vdC5hZGRMYXlvdXQodGVzdF9yb3cpCgogICAgICAgICMg4pSA4pSAIEZhY2UgUGFjayDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICByb290LmFkZFdp"
    "ZGdldChfc2VjdGlvbl9sYmwoIuKdpyBGQUNFIFBBQ0sgKG9wdGlvbmFsIOKAlCBaSVAgZmlsZSkiKSkKICAgICAgICBmYWNlX3Jv"
    "dyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9mYWNlX3BhdGggPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2ZhY2Vf"
    "cGF0aC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgIGYiQnJvd3NlIHRvIHtERUNLX05BTUV9IGZhY2UgcGFjayBaSVAg"
    "KG9wdGlvbmFsLCBjYW4gYWRkIGxhdGVyKSIKICAgICAgICApCiAgICAgICAgc2VsZi5fZmFjZV9wYXRoLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBmImJv"
    "cmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5"
    "OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTJweDsgcGFkZGluZzogNnB4IDEwcHg7IgogICAgICAgICkKICAgICAg"
    "ICBidG5fZmFjZSA9IF9nb3RoaWNfYnRuKCJCcm93c2UiKQogICAgICAgIGJ0bl9mYWNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9i"
    "cm93c2VfZmFjZSkKICAgICAgICBmYWNlX3Jvdy5hZGRXaWRnZXQoc2VsZi5fZmFjZV9wYXRoKQogICAgICAgIGZhY2Vfcm93LmFk"
    "ZFdpZGdldChidG5fZmFjZSkKICAgICAgICByb290LmFkZExheW91dChmYWNlX3JvdykKCiAgICAgICAgIyDilIDilIAgU2hvcnRj"
    "dXQgb3B0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAg"
    "IHNlbGYuX3Nob3J0Y3V0X2NiID0gUUNoZWNrQm94KAogICAgICAgICAgICAiQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgKHJlY29t"
    "bWVuZGVkKSIKICAgICAgICApCiAgICAgICAgc2VsZi5fc2hvcnRjdXRfY2Iuc2V0Q2hlY2tlZChUcnVlKQogICAgICAgIHJvb3Qu"
    "YWRkV2lkZ2V0KHNlbGYuX3Nob3J0Y3V0X2NiKQoKICAgICAgICAjIOKUgOKUgCBCdXR0b25zIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHJvb3Qu"
    "YWRkU3RyZXRjaCgpCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYXdha2VuID0gX2dv"
    "dGhpY19idG4oIuKcpiBCRUdJTiBBV0FLRU5JTkciKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uc2V0RW5hYmxlZChGYWxzZSkK"
    "ICAgICAgICBidG5fY2FuY2VsID0gX2dvdGhpY19idG4oIuKclyBDYW5jZWwiKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuYWNjZXB0KQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYucmVqZWN0KQog"
    "ICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9hd2FrZW4pCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2Nh"
    "bmNlbCkKICAgICAgICByb290LmFkZExheW91dChidG5fcm93KQoKICAgIGRlZiBfb25fdHlwZV9jaGFuZ2Uoc2VsZiwgaWR4OiBp"
    "bnQpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KGlkeCkKICAgICAgICBzZWxmLl9idG5fYXdh"
    "a2VuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRUZXh0KCIiKQoKICAgIGRlZiBfYnJvd3Nl"
    "X21vZGVsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCA9IFFGaWxlRGlhbG9nLmdldEV4aXN0aW5nRGlyZWN0b3J5KAogICAg"
    "ICAgICAgICBzZWxmLCAiU2VsZWN0IE1vZGVsIEZvbGRlciIsCiAgICAgICAgICAgIHIiRDpcQUlcTW9kZWxzIgogICAgICAgICkK"
    "ICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICBzZWxmLl9sb2NhbF9wYXRoLnNldFRleHQocGF0aCkKCiAgICBkZWYgX2Jyb3dz"
    "ZV9mYWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCwgXyA9IFFGaWxlRGlhbG9nLmdldE9wZW5GaWxlTmFtZSgKICAgICAg"
    "ICAgICAgc2VsZiwgIlNlbGVjdCBGYWNlIFBhY2sgWklQIiwKICAgICAgICAgICAgc3RyKFBhdGguaG9tZSgpIC8gIkRlc2t0b3Ai"
    "KSwKICAgICAgICAgICAgIlpJUCBGaWxlcyAoKi56aXApIgogICAgICAgICkKICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICBz"
    "ZWxmLl9mYWNlX3BhdGguc2V0VGV4dChwYXRoKQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGZhY2VfemlwX3BhdGgoc2VsZikgLT4g"
    "c3RyOgogICAgICAgIHJldHVybiBzZWxmLl9mYWNlX3BhdGgudGV4dCgpLnN0cmlwKCkKCiAgICBkZWYgX3Rlc3RfY29ubmVjdGlv"
    "bihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0VGV4dCgiVGVzdGluZy4uLiIpCiAgICAgICAgc2Vs"
    "Zi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTog"
    "MTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIFFBcHBsaWNhdGlvbi5wcm9j"
    "ZXNzRXZlbnRzKCkKCiAgICAgICAgaWR4ID0gc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXgoKQogICAgICAgIG9rICA9IEZh"
    "bHNlCiAgICAgICAgbXNnID0gIiIKCiAgICAgICAgaWYgaWR4ID09IDA6ICAjIExvY2FsCiAgICAgICAgICAgIHBhdGggPSBzZWxm"
    "Ll9sb2NhbF9wYXRoLnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIHBhdGggYW5kIFBhdGgocGF0aCkuZXhpc3RzKCk6CiAg"
    "ICAgICAgICAgICAgICBvayAgPSBUcnVlCiAgICAgICAgICAgICAgICBtc2cgPSBmIkZvbGRlciBmb3VuZC4gTW9kZWwgd2lsbCBs"
    "b2FkIG9uIHN0YXJ0dXAuIgogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgbXNnID0gIkZvbGRlciBub3QgZm91bmQu"
    "IENoZWNrIHRoZSBwYXRoLiIKCiAgICAgICAgZWxpZiBpZHggPT0gMTogICMgT2xsYW1hCiAgICAgICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgICAgIHJlcSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KAogICAgICAgICAgICAgICAgICAgICJodHRwOi8vbG9jYWxo"
    "b3N0OjExNDM0L2FwaS90YWdzIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgcmVzcCA9IHVybGxpYi5yZXF1ZXN0"
    "LnVybG9wZW4ocmVxLCB0aW1lb3V0PTMpCiAgICAgICAgICAgICAgICBvayAgID0gcmVzcC5zdGF0dXMgPT0gMjAwCiAgICAgICAg"
    "ICAgICAgICBtc2cgID0gIk9sbGFtYSBpcyBydW5uaW5nIOKckyIgaWYgb2sgZWxzZSAiT2xsYW1hIG5vdCByZXNwb25kaW5nLiIK"
    "ICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgbXNnID0gZiJPbGxhbWEgbm90IHJlYWNo"
    "YWJsZToge2V9IgoKICAgICAgICBlbGlmIGlkeCA9PSAyOiAgIyBDbGF1ZGUKICAgICAgICAgICAga2V5ID0gc2VsZi5fY2xhdWRl"
    "X2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBvayAgPSBib29sKGtleSBhbmQga2V5LnN0YXJ0c3dpdGgoInNrLWFudCIp"
    "KQogICAgICAgICAgICBtc2cgPSAiQVBJIGtleSBmb3JtYXQgbG9va3MgY29ycmVjdC4iIGlmIG9rIGVsc2UgIkVudGVyIGEgdmFs"
    "aWQgQ2xhdWRlIEFQSSBrZXkuIgoKICAgICAgICBlbGlmIGlkeCA9PSAzOiAgIyBPcGVuQUkKICAgICAgICAgICAga2V5ID0gc2Vs"
    "Zi5fb2FpX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBvayAgPSBib29sKGtleSBhbmQga2V5LnN0YXJ0c3dpdGgoInNr"
    "LSIpKQogICAgICAgICAgICBtc2cgPSAiQVBJIGtleSBmb3JtYXQgbG9va3MgY29ycmVjdC4iIGlmIG9rIGVsc2UgIkVudGVyIGEg"
    "dmFsaWQgT3BlbkFJIEFQSSBrZXkuIgoKICAgICAgICBjb2xvciA9IENfR1JFRU4gaWYgb2sgZWxzZSBDX0NSSU1TT04KICAgICAg"
    "ICBzZWxmLl9zdGF0dXNfbGJsLnNldFRleHQobXNnKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlm"
    "OyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbi5zZXRFbmFibGVkKG9rKQoKICAgIGRlZiBidWlsZF9jb25maWco"
    "c2VsZikgLT4gZGljdDoKICAgICAgICAiIiJCdWlsZCBhbmQgcmV0dXJuIHVwZGF0ZWQgY29uZmlnIGRpY3QgZnJvbSBkaWFsb2cg"
    "c2VsZWN0aW9ucy4iIiIKICAgICAgICBjZmcgICAgID0gX2RlZmF1bHRfY29uZmlnKCkKICAgICAgICBpZHggICAgID0gc2VsZi5f"
    "dHlwZV9jb21iby5jdXJyZW50SW5kZXgoKQogICAgICAgIHR5cGVzICAgPSBbImxvY2FsIiwgIm9sbGFtYSIsICJjbGF1ZGUiLCAi"
    "b3BlbmFpIl0KICAgICAgICBjZmdbIm1vZGVsIl1bInR5cGUiXSA9IHR5cGVzW2lkeF0KCiAgICAgICAgaWYgaWR4ID09IDA6CiAg"
    "ICAgICAgICAgIGNmZ1sibW9kZWwiXVsicGF0aCJdID0gc2VsZi5fbG9jYWxfcGF0aC50ZXh0KCkuc3RyaXAoKQogICAgICAgIGVs"
    "aWYgaWR4ID09IDE6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsib2xsYW1hX21vZGVsIl0gPSBzZWxmLl9vbGxhbWFfbW9kZWwu"
    "dGV4dCgpLnN0cmlwKCkgb3IgImRvbHBoaW4tMi42LTdiIgogICAgICAgIGVsaWYgaWR4ID09IDI6CiAgICAgICAgICAgIGNmZ1si"
    "bW9kZWwiXVsiYXBpX2tleSJdICAgPSBzZWxmLl9jbGF1ZGVfa2V5LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGNmZ1sibW9k"
    "ZWwiXVsiYXBpX21vZGVsIl0gPSBzZWxmLl9jbGF1ZGVfbW9kZWwudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2Rl"
    "bCJdWyJhcGlfdHlwZSJdICA9ICJjbGF1ZGUiCiAgICAgICAgZWxpZiBpZHggPT0gMzoKICAgICAgICAgICAgY2ZnWyJtb2RlbCJd"
    "WyJhcGlfa2V5Il0gICA9IHNlbGYuX29haV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlf"
    "bW9kZWwiXSA9IHNlbGYuX29haV9tb2RlbC50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV90eXBl"
    "Il0gID0gIm9wZW5haSIKCiAgICAgICAgY2ZnWyJmaXJzdF9ydW4iXSA9IEZhbHNlCiAgICAgICAgcmV0dXJuIGNmZwoKICAgIEBw"
    "cm9wZXJ0eQogICAgZGVmIGNyZWF0ZV9zaG9ydGN1dChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBzZWxmLl9zaG9ydGN1"
    "dF9jYi5pc0NoZWNrZWQoKQoKCiMg4pSA4pSAIEpPVVJOQUwgU0lERUJBUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xh"
    "c3MgSm91cm5hbFNpZGViYXIoUVdpZGdldCk6CiAgICAiIiIKICAgIENvbGxhcHNpYmxlIGxlZnQgc2lkZWJhciBuZXh0IHRvIHRo"
    "ZSBwZXJzb25hIGNoYXQgdGFiLgogICAgVG9wOiBzZXNzaW9uIGNvbnRyb2xzIChjdXJyZW50IHNlc3Npb24gbmFtZSwgc2F2ZS9s"
    "b2FkIGJ1dHRvbnMsCiAgICAgICAgIGF1dG9zYXZlIGluZGljYXRvcikuCiAgICBCb2R5OiBzY3JvbGxhYmxlIHNlc3Npb24gbGlz"
    "dCDigJQgZGF0ZSwgQUkgbmFtZSwgbWVzc2FnZSBjb3VudC4KICAgIENvbGxhcHNlcyBsZWZ0d2FyZCB0byBhIHRoaW4gc3RyaXAu"
    "CgogICAgU2lnbmFsczoKICAgICAgICBzZXNzaW9uX2xvYWRfcmVxdWVzdGVkKHN0cikgICDigJQgZGF0ZSBzdHJpbmcgb2Ygc2Vz"
    "c2lvbiB0byBsb2FkCiAgICAgICAgc2Vzc2lvbl9jbGVhcl9yZXF1ZXN0ZWQoKSAgICAg4oCUIHJldHVybiB0byBjdXJyZW50IHNl"
    "c3Npb24KICAgICIiIgoKICAgIHNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQgID0gU2lnbmFsKHN0cikKICAgIHNlc3Npb25fY2xlYXJf"
    "cmVxdWVzdGVkID0gU2lnbmFsKCkKCiAgICBkZWYgX19pbml0X18oc2VsZiwgc2Vzc2lvbl9tZ3I6ICJTZXNzaW9uTWFuYWdlciIs"
    "IHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9zZXNzaW9uX21nciA9"
    "IHNlc3Npb25fbWdyCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgICAgPSBUcnVlCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAg"
    "ICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgICMgVXNlIGEgaG9yaXpv"
    "bnRhbCByb290IGxheW91dCDigJQgY29udGVudCBvbiBsZWZ0LCB0b2dnbGUgc3RyaXAgb24gcmlnaHQKICAgICAgICByb290ID0g"
    "UUhCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHJvb3Qu"
    "c2V0U3BhY2luZygwKQoKICAgICAgICAjIOKUgOKUgCBDb2xsYXBzZSB0b2dnbGUgc3RyaXAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fdG9nZ2xlX3N0cmlwID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fdG9n"
    "Z2xlX3N0cmlwLnNldEZpeGVkV2lkdGgoMjApCiAgICAgICAgc2VsZi5fdG9nZ2xlX3N0cmlwLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyLXJpZ2h0OiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAg"
    "ICAgICApCiAgICAgICAgdHNfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fdG9nZ2xlX3N0cmlwKQogICAgICAgIHRzX2xheW91"
    "dC5zZXRDb250ZW50c01hcmdpbnMoMCwgOCwgMCwgOCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuID0gUVRvb2xCdXR0b24oKQog"
    "ICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0Rml4ZWRTaXplKDE4LCAxOCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRl"
    "eHQoIuKXgCIpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6"
    "IHRyYW5zcGFyZW50OyBjb2xvcjoge0NfR09MRF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiBub25lOyBmb250LXNpemU6"
    "IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCiAg"
    "ICAgICAgdHNfbGF5b3V0LmFkZFdpZGdldChzZWxmLl90b2dnbGVfYnRuKQogICAgICAgIHRzX2xheW91dC5hZGRTdHJldGNoKCkK"
    "CiAgICAgICAgIyDilIDilIAgTWFpbiBjb250ZW50IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2NvbnRlbnQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jb250"
    "ZW50LnNldE1pbmltdW1XaWR0aCgxODApCiAgICAgICAgc2VsZi5fY29udGVudC5zZXRNYXhpbXVtV2lkdGgoMjIwKQogICAgICAg"
    "IGNvbnRlbnRfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fY29udGVudCkKICAgICAgICBjb250ZW50X2xheW91dC5zZXRDb250"
    "ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBjb250ZW50X2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgU2Vj"
    "dGlvbiBsYWJlbAogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBKT1VSTkFMIikpCgog"
    "ICAgICAgICMgQ3VycmVudCBzZXNzaW9uIGluZm8KICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUgPSBRTGFiZWwoIk5ldyBTZXNz"
    "aW9uIikKICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09M"
    "RH07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgIgogICAgICAgICAgICBmImZvbnQt"
    "c3R5bGU6IGl0YWxpYzsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbmFtZS5zZXRXb3JkV3JhcChUcnVlKQogICAg"
    "ICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zZXNzaW9uX25hbWUpCgogICAgICAgICMgU2F2ZSAvIExvYWQgcm93"
    "CiAgICAgICAgY3RybF9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUgPSBfZ290aGljX2J0bigi8J+S"
    "viIpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0Rml4ZWRTaXplKDMyLCAyNCkKICAgICAgICBzZWxmLl9idG5fc2F2ZS5zZXRU"
    "b29sVGlwKCJTYXZlIHNlc3Npb24gbm93IikKICAgICAgICBzZWxmLl9idG5fbG9hZCA9IF9nb3RoaWNfYnRuKCLwn5OCIikKICAg"
    "ICAgICBzZWxmLl9idG5fbG9hZC5zZXRGaXhlZFNpemUoMzIsIDI0KQogICAgICAgIHNlbGYuX2J0bl9sb2FkLnNldFRvb2xUaXAo"
    "IkJyb3dzZSBhbmQgbG9hZCBhIHBhc3Qgc2Vzc2lvbiIpCiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90ID0gUUxhYmVsKCLil48i"
    "KQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJ"
    "TX07IGZvbnQtc2l6ZTogOHB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Quc2V0"
    "VG9vbFRpcCgiQXV0b3NhdmUgc3RhdHVzIikKICAgICAgICBzZWxmLl9idG5fc2F2ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9f"
    "c2F2ZSkKICAgICAgICBzZWxmLl9idG5fbG9hZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbG9hZCkKICAgICAgICBjdHJsX3Jv"
    "dy5hZGRXaWRnZXQoc2VsZi5fYnRuX3NhdmUpCiAgICAgICAgY3RybF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9sb2FkKQogICAg"
    "ICAgIGN0cmxfcm93LmFkZFdpZGdldChzZWxmLl9hdXRvc2F2ZV9kb3QpCiAgICAgICAgY3RybF9yb3cuYWRkU3RyZXRjaCgpCiAg"
    "ICAgICAgY29udGVudF9sYXlvdXQuYWRkTGF5b3V0KGN0cmxfcm93KQoKICAgICAgICAjIEpvdXJuYWwgbG9hZGVkIGluZGljYXRv"
    "cgogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1BVUlBMRX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tf"
    "Rk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgIGYiZm9udC1zdHlsZTogaXRhbGljOyIKICAgICAgICApCiAgICAgICAgc2VsZi5f"
    "am91cm5hbF9sYmwuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fam91cm5h"
    "bF9sYmwpCgogICAgICAgICMgQ2xlYXIgam91cm5hbCBidXR0b24gKGhpZGRlbiB3aGVuIG5vdCBsb2FkZWQpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX2NsZWFyX2pvdXJuYWwgPSBfZ290aGljX2J0bigi4pyXIFJldHVybiB0byBQcmVzZW50IikKICAgICAgICBzZWxmLl9i"
    "dG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLmNsaWNrZWQu"
    "Y29ubmVjdChzZWxmLl9kb19jbGVhcl9qb3VybmFsKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9idG5f"
    "Y2xlYXJfam91cm5hbCkKCiAgICAgICAgIyBEaXZpZGVyCiAgICAgICAgZGl2ID0gUUZyYW1lKCkKICAgICAgICBkaXYuc2V0RnJh"
    "bWVTaGFwZShRRnJhbWUuU2hhcGUuSExpbmUpCiAgICAgICAgZGl2LnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfQ1JJTVNPTl9E"
    "SU19OyIpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KGRpdikKCiAgICAgICAgIyBTZXNzaW9uIGxpc3QKICAgICAg"
    "ICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgUEFTVCBTRVNTSU9OUyIpKQogICAgICAgIHNlbGYu"
    "X3Nlc3Npb25fbGlzdCA9IFFMaXN0V2lkZ2V0KCkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3Quc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1z"
    "aXplOiAxMHB4OyIKICAgICAgICAgICAgZiJRTGlzdFdpZGdldDo6aXRlbTpzZWxlY3RlZCB7eyBiYWNrZ3JvdW5kOiB7Q19DUklN"
    "U09OX0RJTX07IH19IgogICAgICAgICkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QuaXRlbURvdWJsZUNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl9vbl9zZXNzaW9uX2NsaWNrKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5pdGVtQ2xpY2tlZC5jb25uZWN0KHNl"
    "bGYuX29uX3Nlc3Npb25fY2xpY2spCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Nlc3Npb25fbGlzdCwg"
    "MSkKCiAgICAgICAgIyBBZGQgY29udGVudCBhbmQgdG9nZ2xlIHN0cmlwIHRvIHRoZSByb290IGhvcml6b250YWwgbGF5b3V0CiAg"
    "ICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fY29udGVudCkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90b2dnbGVfc3Ry"
    "aXApCgogICAgZGVmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBh"
    "bmRlZAogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0VmlzaWJsZShzZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxmLl90b2dnbGVf"
    "YnRuLnNldFRleHQoIuKXgCIgaWYgc2VsZi5fZXhwYW5kZWQgZWxzZSAi4pa2IikKICAgICAgICBzZWxmLnVwZGF0ZUdlb21ldHJ5"
    "KCkKICAgICAgICBwID0gc2VsZi5wYXJlbnRXaWRnZXQoKQogICAgICAgIGlmIHAgYW5kIHAubGF5b3V0KCk6CiAgICAgICAgICAg"
    "IHAubGF5b3V0KCkuYWN0aXZhdGUoKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2Vzc2lvbnMgPSBz"
    "ZWxmLl9zZXNzaW9uX21nci5saXN0X3Nlc3Npb25zKCkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QuY2xlYXIoKQogICAgICAg"
    "IGZvciBzIGluIHNlc3Npb25zOgogICAgICAgICAgICBkYXRlX3N0ciA9IHMuZ2V0KCJkYXRlIiwiIikKICAgICAgICAgICAgbmFt"
    "ZSAgICAgPSBzLmdldCgibmFtZSIsIGRhdGVfc3RyKVs6MzBdCiAgICAgICAgICAgIGNvdW50ICAgID0gcy5nZXQoIm1lc3NhZ2Vf"
    "Y291bnQiLCAwKQogICAgICAgICAgICBpdGVtID0gUUxpc3RXaWRnZXRJdGVtKGYie2RhdGVfc3RyfVxue25hbWV9ICh7Y291bnR9"
    "IG1zZ3MpIikKICAgICAgICAgICAgaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgZGF0ZV9zdHIpCiAgICAg"
    "ICAgICAgIGl0ZW0uc2V0VG9vbFRpcChmIkRvdWJsZS1jbGljayB0byBsb2FkIHNlc3Npb24gZnJvbSB7ZGF0ZV9zdHJ9IikKICAg"
    "ICAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0LmFkZEl0ZW0oaXRlbSkKCiAgICBkZWYgc2V0X3Nlc3Npb25fbmFtZShzZWxmLCBu"
    "YW1lOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNldFRleHQobmFtZVs6NTBdIG9yICJOZXcgU2Vz"
    "c2lvbiIpCgogICAgZGVmIHNldF9hdXRvc2F2ZV9pbmRpY2F0b3Ioc2VsZiwgc2F2ZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAg"
    "c2VsZi5fYXV0b3NhdmVfZG90LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dSRUVOIGlmIHNhdmVkIGVs"
    "c2UgQ19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDhweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAg"
    "ICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFRvb2xUaXAoCiAgICAgICAgICAgICJBdXRvc2F2ZWQiIGlmIHNhdmVkIGVsc2Ug"
    "IlBlbmRpbmcgYXV0b3NhdmUiCiAgICAgICAgKQoKICAgIGRlZiBzZXRfam91cm5hbF9sb2FkZWQoc2VsZiwgZGF0ZV9zdHI6IHN0"
    "cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRUZXh0KGYi8J+TliBKb3VybmFsOiB7ZGF0ZV9zdHJ9IikK"
    "ICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKFRydWUpCgogICAgZGVmIGNsZWFyX2pvdXJuYWxfaW5k"
    "aWNhdG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0VGV4dCgiIikKICAgICAgICBzZWxmLl9i"
    "dG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKEZhbHNlKQoKICAgIGRlZiBfZG9fc2F2ZShzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYuX3Nlc3Npb25fbWdyLnNhdmUoKQogICAgICAgIHNlbGYuc2V0X2F1dG9zYXZlX2luZGljYXRvcihUcnVlKQogICAgICAg"
    "IHNlbGYucmVmcmVzaCgpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0VGV4dCgi4pyTIikKICAgICAgICBRVGltZXIuc2luZ2xl"
    "U2hvdCgxNTAwLCBsYW1iZGE6IHNlbGYuX2J0bl9zYXZlLnNldFRleHQoIvCfkr4iKSkKICAgICAgICBRVGltZXIuc2luZ2xlU2hv"
    "dCgzMDAwLCBsYW1iZGE6IHNlbGYuc2V0X2F1dG9zYXZlX2luZGljYXRvcihGYWxzZSkpCgogICAgZGVmIF9kb19sb2FkKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgIyBUcnkgc2VsZWN0ZWQgaXRlbSBmaXJzdAogICAgICAgIGl0ZW0gPSBzZWxmLl9zZXNzaW9uX2xp"
    "c3QuY3VycmVudEl0ZW0oKQogICAgICAgIGlmIG5vdCBpdGVtOgogICAgICAgICAgICAjIElmIG5vdGhpbmcgc2VsZWN0ZWQsIHRy"
    "eSB0aGUgZmlyc3QgaXRlbQogICAgICAgICAgICBpZiBzZWxmLl9zZXNzaW9uX2xpc3QuY291bnQoKSA+IDA6CiAgICAgICAgICAg"
    "ICAgICBpdGVtID0gc2VsZi5fc2Vzc2lvbl9saXN0Lml0ZW0oMCkKICAgICAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5z"
    "ZXRDdXJyZW50SXRlbShpdGVtKQogICAgICAgIGlmIGl0ZW06CiAgICAgICAgICAgIGRhdGVfc3RyID0gaXRlbS5kYXRhKFF0Lkl0"
    "ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgc2VsZi5zZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmVtaXQoZGF0ZV9zdHIp"
    "CgogICAgZGVmIF9vbl9zZXNzaW9uX2NsaWNrKHNlbGYsIGl0ZW0pIC0+IE5vbmU6CiAgICAgICAgZGF0ZV9zdHIgPSBpdGVtLmRh"
    "dGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAgICAgIHNlbGYuc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5lbWl0KGRhdGVf"
    "c3RyKQoKICAgIGRlZiBfZG9fY2xlYXJfam91cm5hbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuc2Vzc2lvbl9jbGVhcl9y"
    "ZXF1ZXN0ZWQuZW1pdCgpCiAgICAgICAgc2VsZi5jbGVhcl9qb3VybmFsX2luZGljYXRvcigpCgoKIyDilIDilIAgVE9SUE9SIFBB"
    "TkVMIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBUb3Jwb3JQYW5lbChRV2lkZ2V0KToKICAgICIi"
    "IgogICAgVGhyZWUtc3RhdGUgc3VzcGVuc2lvbiB0b2dnbGU6IEFXQUtFIHwgQVVUTyB8IFNVU1BFTkQKCiAgICBBV0FLRSAg4oCU"
    "IG1vZGVsIGxvYWRlZCwgYXV0by10b3Jwb3IgZGlzYWJsZWQsIGlnbm9yZXMgVlJBTSBwcmVzc3VyZQogICAgQVVUTyAgIOKAlCBt"
    "b2RlbCBsb2FkZWQsIG1vbml0b3JzIFZSQU0gcHJlc3N1cmUsIGF1dG8tdG9ycG9yIGlmIHN1c3RhaW5lZAogICAgU1VTUEVORCDi"
    "gJQgbW9kZWwgdW5sb2FkZWQsIHN0YXlzIHN1c3BlbmRlZCB1bnRpbCBtYW51YWxseSBjaGFuZ2VkCgogICAgU2lnbmFsczoKICAg"
    "ICAgICBzdGF0ZV9jaGFuZ2VkKHN0cikgIOKAlCAiQVdBS0UiIHwgIkFVVE8iIHwgIlNVU1BFTkQiCiAgICAiIiIKCiAgICBzdGF0"
    "ZV9jaGFuZ2VkID0gU2lnbmFsKHN0cikKCiAgICBTVEFURVMgPSBbIkFXQUtFIiwgIkFVVE8iLCAiU1VTUEVORCJdCgogICAgU1RB"
    "VEVfU1RZTEVTID0gewogICAgICAgICJBV0FLRSI6IHsKICAgICAgICAgICAgImFjdGl2ZSI6ICAgZiJiYWNrZ3JvdW5kOiAjMmEx"
    "YTA1OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xE"
    "fTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2Vp"
    "Z2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkcz"
    "fTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JP"
    "UkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250"
    "LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAibGFiZWwiOiAgICAi4piAIEFXQUtFIiwKICAg"
    "ICAgICAgICAgInRvb2x0aXAiOiAgIk1vZGVsIGFjdGl2ZS4gQXV0by10b3Jwb3IgZGlzYWJsZWQuIiwKICAgICAgICB9LAogICAg"
    "ICAgICJBVVRPIjogewogICAgICAgICAgICAiYWN0aXZlIjogICBmImJhY2tncm91bmQ6ICMxYTEwMDU7IGNvbG9yOiAjY2M4ODIy"
    "OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQgI2NjODgyMjsgYm9yZGVyLXJhZGl1czogMnB4"
    "OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAz"
    "cHggOHB4OyIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElN"
    "fTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6"
    "IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGlu"
    "ZzogM3B4IDhweDsiLAogICAgICAgICAgICAibGFiZWwiOiAgICAi4peJIEFVVE8iLAogICAgICAgICAgICAidG9vbHRpcCI6ICAi"
    "TW9kZWwgYWN0aXZlLiBBdXRvLXN1c3BlbmQgb24gVlJBTSBwcmVzc3VyZS4iLAogICAgICAgIH0sCiAgICAgICAgIlNVU1BFTkQi"
    "OiB7CiAgICAgICAgICAgICJhY3RpdmUiOiAgIGYiYmFja2dyb3VuZDoge0NfUFVSUExFX0RJTX07IGNvbG9yOiB7Q19QVVJQTEV9"
    "OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfUFVSUExFfTsgYm9yZGVyLXJhZGl1czog"
    "MnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5n"
    "OiAzcHggOHB4OyIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRf"
    "RElNfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRp"
    "dXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFk"
    "ZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAibGFiZWwiOiAgICBmIuKasCB7VUlfU1VTUEVOU0lPTl9MQUJFTC5zdHJpcCgp"
    "IGlmIHN0cihVSV9TVVNQRU5TSU9OX0xBQkVMKS5zdHJpcCgpIGVsc2UgJ1N1c3BlbmQnfSIsCiAgICAgICAgICAgICJ0b29sdGlw"
    "IjogIGYiTW9kZWwgdW5sb2FkZWQuIHtERUNLX05BTUV9IHNsZWVwcyB1bnRpbCBtYW51YWxseSBhd2FrZW5lZC4iLAogICAgICAg"
    "IH0sCiAgICB9CgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBh"
    "cmVudCkKICAgICAgICBzZWxmLl9jdXJyZW50ID0gIkFXQUtFIgogICAgICAgIHNlbGYuX2J1dHRvbnM6IGRpY3Rbc3RyLCBRUHVz"
    "aEJ1dHRvbl0gPSB7fQogICAgICAgIGxheW91dCA9IFFIQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRz"
    "TWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDIpCgogICAgICAgIGZvciBzdGF0ZSBpbiBzZWxm"
    "LlNUQVRFUzoKICAgICAgICAgICAgYnRuID0gUVB1c2hCdXR0b24oc2VsZi5TVEFURV9TVFlMRVNbc3RhdGVdWyJsYWJlbCJdKQog"
    "ICAgICAgICAgICBidG4uc2V0VG9vbFRpcChzZWxmLlNUQVRFX1NUWUxFU1tzdGF0ZV1bInRvb2x0aXAiXSkKICAgICAgICAgICAg"
    "YnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgICAgICBidG4uY2xpY2tlZC5jb25uZWN0KGxhbWJkYSBjaGVja2VkLCBzPXN0"
    "YXRlOiBzZWxmLl9zZXRfc3RhdGUocykpCiAgICAgICAgICAgIHNlbGYuX2J1dHRvbnNbc3RhdGVdID0gYnRuCiAgICAgICAgICAg"
    "IGxheW91dC5hZGRXaWRnZXQoYnRuKQoKICAgICAgICBzZWxmLl9hcHBseV9zdHlsZXMoKQoKICAgIGRlZiBfc2V0X3N0YXRlKHNl"
    "bGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgaWYgc3RhdGUgPT0gc2VsZi5fY3VycmVudDoKICAgICAgICAgICAgcmV0"
    "dXJuCiAgICAgICAgc2VsZi5fY3VycmVudCA9IHN0YXRlCiAgICAgICAgc2VsZi5fYXBwbHlfc3R5bGVzKCkKICAgICAgICBzZWxm"
    "LnN0YXRlX2NoYW5nZWQuZW1pdChzdGF0ZSkKCiAgICBkZWYgX2FwcGx5X3N0eWxlcyhzZWxmKSAtPiBOb25lOgogICAgICAgIGZv"
    "ciBzdGF0ZSwgYnRuIGluIHNlbGYuX2J1dHRvbnMuaXRlbXMoKToKICAgICAgICAgICAgc3R5bGVfa2V5ID0gImFjdGl2ZSIgaWYg"
    "c3RhdGUgPT0gc2VsZi5fY3VycmVudCBlbHNlICJpbmFjdGl2ZSIKICAgICAgICAgICAgYnRuLnNldFN0eWxlU2hlZXQoc2VsZi5T"
    "VEFURV9TVFlMRVNbc3RhdGVdW3N0eWxlX2tleV0pCgogICAgQHByb3BlcnR5CiAgICBkZWYgY3VycmVudF9zdGF0ZShzZWxmKSAt"
    "PiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2N1cnJlbnQKCiAgICBkZWYgc2V0X3N0YXRlKHNlbGYsIHN0YXRlOiBzdHIpIC0+"
    "IE5vbmU6CiAgICAgICAgIiIiU2V0IHN0YXRlIHByb2dyYW1tYXRpY2FsbHkgKGUuZy4gZnJvbSBhdXRvLXRvcnBvciBkZXRlY3Rp"
    "b24pLiIiIgogICAgICAgIGlmIHN0YXRlIGluIHNlbGYuU1RBVEVTOgogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdGUoc3RhdGUp"
    "CgoKY2xhc3MgU2V0dGluZ3NTZWN0aW9uKFFXaWRnZXQpOgogICAgIiIiU2ltcGxlIGNvbGxhcHNpYmxlIHNlY3Rpb24gdXNlZCBi"
    "eSBTZXR0aW5nc1RhYi4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgdGl0bGU6IHN0ciwgcGFyZW50PU5vbmUsIGV4cGFuZGVk"
    "OiBib29sID0gVHJ1ZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBl"
    "eHBhbmRlZAoKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucygw"
    "LCAwLCAwLCAwKQogICAgICAgIHJvb3Quc2V0U3BhY2luZygwKQoKICAgICAgICBzZWxmLl9oZWFkZXJfYnRuID0gUVRvb2xCdXR0"
    "b24oKQogICAgICAgIHNlbGYuX2hlYWRlcl9idG4uc2V0VGV4dChmIuKWvCB7dGl0bGV9IiBpZiBleHBhbmRlZCBlbHNlIGYi4pa2"
    "IHt0aXRsZX0iKQogICAgICAgIHNlbGYuX2hlYWRlcl9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5k"
    "OiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAg"
    "ICBmInBhZGRpbmc6IDZweDsgdGV4dC1hbGlnbjogbGVmdDsgZm9udC13ZWlnaHQ6IGJvbGQ7IgogICAgICAgICkKICAgICAgICBz"
    "ZWxmLl9oZWFkZXJfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCgogICAgICAgIHNlbGYuX2NvbnRlbnQgPSBRV2lk"
    "Z2V0KCkKICAgICAgICBzZWxmLl9jb250ZW50X2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX2NvbnRlbnQpCiAgICAgICAgc2Vs"
    "Zi5fY29udGVudF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDgsIDgsIDgsIDgpCiAgICAgICAgc2VsZi5fY29udGVudF9sYXlv"
    "dXQuc2V0U3BhY2luZyg4KQogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3Jv"
    "dW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItdG9wOiBub25lOyIKICAgICAgICApCiAg"
    "ICAgICAgc2VsZi5fY29udGVudC5zZXRWaXNpYmxlKGV4cGFuZGVkKQoKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9oZWFk"
    "ZXJfYnRuKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2NvbnRlbnQpCgogICAgQHByb3BlcnR5CiAgICBkZWYgY29udGVu"
    "dF9sYXlvdXQoc2VsZikgLT4gUVZCb3hMYXlvdXQ6CiAgICAgICAgcmV0dXJuIHNlbGYuX2NvbnRlbnRfbGF5b3V0CgogICAgZGVm"
    "IF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAg"
    "IHNlbGYuX2hlYWRlcl9idG4uc2V0VGV4dCgKICAgICAgICAgICAgc2VsZi5faGVhZGVyX2J0bi50ZXh0KCkucmVwbGFjZSgi4pa8"
    "IiwgIuKWtiIsIDEpCiAgICAgICAgICAgIGlmIG5vdCBzZWxmLl9leHBhbmRlZCBlbHNlCiAgICAgICAgICAgIHNlbGYuX2hlYWRl"
    "cl9idG4udGV4dCgpLnJlcGxhY2UoIuKWtiIsICLilrwiLCAxKQogICAgICAgICkKICAgICAgICBzZWxmLl9jb250ZW50LnNldFZp"
    "c2libGUoc2VsZi5fZXhwYW5kZWQpCgoKY2xhc3MgU2V0dGluZ3NUYWIoUVdpZGdldCk6CiAgICAiIiJEZWNrLXdpZGUgcnVudGlt"
    "ZSBzZXR0aW5ncyB0YWIuIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGRlY2tfd2luZG93OiAiRWNob0RlY2siLCBwYXJlbnQ9"
    "Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZGVjayA9IGRlY2tfd2luZG93CiAg"
    "ICAgICAgc2VsZi5fc2VjdGlvbl9yZWdpc3RyeTogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc2VjdGlvbl93aWRnZXRz"
    "OiBkaWN0W3N0ciwgU2V0dGluZ3NTZWN0aW9uXSA9IHt9CgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAg"
    "IHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDApCgogICAgICAgIHNj"
    "cm9sbCA9IFFTY3JvbGxBcmVhKCkKICAgICAgICBzY3JvbGwuc2V0V2lkZ2V0UmVzaXphYmxlKFRydWUpCiAgICAgICAgc2Nyb2xs"
    "LnNldEhvcml6b250YWxTY3JvbGxCYXJQb2xpY3koUXQuU2Nyb2xsQmFyUG9saWN5LlNjcm9sbEJhckFsd2F5c09mZikKICAgICAg"
    "ICBzY3JvbGwuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9E"
    "SU19OyIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2Nyb2xsKQoKICAgICAgICBib2R5ID0gUVdpZGdldCgpCiAgICAgICAgc2Vs"
    "Zi5fYm9keV9sYXlvdXQgPSBRVkJveExheW91dChib2R5KQogICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0LnNldENvbnRlbnRzTWFy"
    "Z2lucyg2LCA2LCA2LCA2KQogICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0LnNldFNwYWNpbmcoOCkKICAgICAgICBzY3JvbGwuc2V0"
    "V2lkZ2V0KGJvZHkpCgogICAgICAgIHNlbGYuX3JlZ2lzdGVyX2NvcmVfc2VjdGlvbnMoKQoKICAgIGRlZiBfcmVnaXN0ZXJfc2Vj"
    "dGlvbihzZWxmLCAqLCBzZWN0aW9uX2lkOiBzdHIsIHRpdGxlOiBzdHIsIGNhdGVnb3J5OiBzdHIsIHNvdXJjZV9vd25lcjogc3Ry"
    "LCBzb3J0X2tleTogaW50LCBidWlsZGVyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3NlY3Rpb25fcmVnaXN0cnkuYXBwZW5kKHsK"
    "ICAgICAgICAgICAgInNlY3Rpb25faWQiOiBzZWN0aW9uX2lkLAogICAgICAgICAgICAidGl0bGUiOiB0aXRsZSwKICAgICAgICAg"
    "ICAgImNhdGVnb3J5IjogY2F0ZWdvcnksCiAgICAgICAgICAgICJzb3VyY2Vfb3duZXIiOiBzb3VyY2Vfb3duZXIsCiAgICAgICAg"
    "ICAgICJzb3J0X2tleSI6IHNvcnRfa2V5LAogICAgICAgICAgICAiYnVpbGRlciI6IGJ1aWxkZXIsCiAgICAgICAgfSkKCiAgICBk"
    "ZWYgX3JlZ2lzdGVyX2NvcmVfc2VjdGlvbnMoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWdpc3Rlcl9zZWN0aW9uKAog"
    "ICAgICAgICAgICBzZWN0aW9uX2lkPSJzeXN0ZW1fc2V0dGluZ3MiLAogICAgICAgICAgICB0aXRsZT0iU3lzdGVtIFNldHRpbmdz"
    "IiwKICAgICAgICAgICAgY2F0ZWdvcnk9ImNvcmUiLAogICAgICAgICAgICBzb3VyY2Vfb3duZXI9ImRlY2tfcnVudGltZSIsCiAg"
    "ICAgICAgICAgIHNvcnRfa2V5PTEwMCwKICAgICAgICAgICAgYnVpbGRlcj1zZWxmLl9idWlsZF9zeXN0ZW1fc2VjdGlvbiwKICAg"
    "ICAgICApCiAgICAgICAgc2VsZi5fcmVnaXN0ZXJfc2VjdGlvbigKICAgICAgICAgICAgc2VjdGlvbl9pZD0iaW50ZWdyYXRpb25f"
    "c2V0dGluZ3MiLAogICAgICAgICAgICB0aXRsZT0iSW50ZWdyYXRpb24gU2V0dGluZ3MiLAogICAgICAgICAgICBjYXRlZ29yeT0i"
    "Y29yZSIsCiAgICAgICAgICAgIHNvdXJjZV9vd25lcj0iZGVja19ydW50aW1lIiwKICAgICAgICAgICAgc29ydF9rZXk9MjAwLAog"
    "ICAgICAgICAgICBidWlsZGVyPXNlbGYuX2J1aWxkX2ludGVncmF0aW9uX3NlY3Rpb24sCiAgICAgICAgKQogICAgICAgIHNlbGYu"
    "X3JlZ2lzdGVyX3NlY3Rpb24oCiAgICAgICAgICAgIHNlY3Rpb25faWQ9InVpX3NldHRpbmdzIiwKICAgICAgICAgICAgdGl0bGU9"
    "IlVJIFNldHRpbmdzIiwKICAgICAgICAgICAgY2F0ZWdvcnk9ImNvcmUiLAogICAgICAgICAgICBzb3VyY2Vfb3duZXI9ImRlY2tf"
    "cnVudGltZSIsCiAgICAgICAgICAgIHNvcnRfa2V5PTMwMCwKICAgICAgICAgICAgYnVpbGRlcj1zZWxmLl9idWlsZF91aV9zZWN0"
    "aW9uLAogICAgICAgICkKCiAgICAgICAgZm9yIG1ldGEgaW4gc29ydGVkKHNlbGYuX3NlY3Rpb25fcmVnaXN0cnksIGtleT1sYW1i"
    "ZGEgbTogbS5nZXQoInNvcnRfa2V5IiwgOTk5OSkpOgogICAgICAgICAgICBzZWN0aW9uID0gU2V0dGluZ3NTZWN0aW9uKG1ldGFb"
    "InRpdGxlIl0sIGV4cGFuZGVkPVRydWUpCiAgICAgICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uKQog"
    "ICAgICAgICAgICBzZWxmLl9zZWN0aW9uX3dpZGdldHNbbWV0YVsic2VjdGlvbl9pZCJdXSA9IHNlY3Rpb24KICAgICAgICAgICAg"
    "bWV0YVsiYnVpbGRlciJdKHNlY3Rpb24uY29udGVudF9sYXlvdXQpCgogICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0LmFkZFN0cmV0"
    "Y2goMSkKCiAgICBkZWYgX2J1aWxkX3N5c3RlbV9zZWN0aW9uKHNlbGYsIGxheW91dDogUVZCb3hMYXlvdXQpIC0+IE5vbmU6CiAg"
    "ICAgICAgaWYgc2VsZi5fZGVjay5fdG9ycG9yX3BhbmVsIGlzIG5vdCBOb25lOgogICAgICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0"
    "KFFMYWJlbCgiT3BlcmF0aW9uYWwgTW9kZSIpKQogICAgICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2RlY2suX3RvcnBv"
    "cl9wYW5lbCkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChRTGFiZWwoIklkbGUiKSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0"
    "KHNlbGYuX2RlY2suX2lkbGVfYnRuKQoKICAgICAgICBzZXR0aW5ncyA9IENGRy5nZXQoInNldHRpbmdzIiwge30pCiAgICAgICAg"
    "dHpfYXV0byA9IGJvb2woc2V0dGluZ3MuZ2V0KCJ0aW1lem9uZV9hdXRvX2RldGVjdCIsIFRydWUpKQogICAgICAgIHR6X292ZXJy"
    "aWRlID0gc3RyKHNldHRpbmdzLmdldCgidGltZXpvbmVfb3ZlcnJpZGUiLCAiIikgb3IgIiIpLnN0cmlwKCkKCiAgICAgICAgdHpf"
    "YXV0b19jaGsgPSBRQ2hlY2tCb3goIkF1dG8tZGV0ZWN0IGxvY2FsL3N5c3RlbSB0aW1lIHpvbmUiKQogICAgICAgIHR6X2F1dG9f"
    "Y2hrLnNldENoZWNrZWQodHpfYXV0bykKICAgICAgICB0el9hdXRvX2Noay50b2dnbGVkLmNvbm5lY3Qoc2VsZi5fZGVjay5fc2V0"
    "X3RpbWV6b25lX2F1dG9fZGV0ZWN0KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQodHpfYXV0b19jaGspCgogICAgICAgIHR6X3Jv"
    "dyA9IFFIQm94TGF5b3V0KCkKICAgICAgICB0el9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgiTWFudWFsIFRpbWUgWm9uZSBPdmVycmlk"
    "ZToiKSkKICAgICAgICB0el9jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgdHpfY29tYm8uc2V0RWRpdGFibGUoVHJ1ZSkKICAg"
    "ICAgICB0el9vcHRpb25zID0gWwogICAgICAgICAgICAiQW1lcmljYS9DaGljYWdvIiwgIkFtZXJpY2EvTmV3X1lvcmsiLCAiQW1l"
    "cmljYS9Mb3NfQW5nZWxlcyIsCiAgICAgICAgICAgICJBbWVyaWNhL0RlbnZlciIsICJVVEMiCiAgICAgICAgXQogICAgICAgIHR6"
    "X2NvbWJvLmFkZEl0ZW1zKHR6X29wdGlvbnMpCiAgICAgICAgaWYgdHpfb3ZlcnJpZGU6CiAgICAgICAgICAgIGlmIHR6X2NvbWJv"
    "LmZpbmRUZXh0KHR6X292ZXJyaWRlKSA8IDA6CiAgICAgICAgICAgICAgICB0el9jb21iby5hZGRJdGVtKHR6X292ZXJyaWRlKQog"
    "ICAgICAgICAgICB0el9jb21iby5zZXRDdXJyZW50VGV4dCh0el9vdmVycmlkZSkKICAgICAgICBlbHNlOgogICAgICAgICAgICB0"
    "el9jb21iby5zZXRDdXJyZW50VGV4dCgiQW1lcmljYS9DaGljYWdvIikKICAgICAgICB0el9jb21iby5zZXRFbmFibGVkKG5vdCB0"
    "el9hdXRvKQogICAgICAgIHR6X2NvbWJvLmN1cnJlbnRUZXh0Q2hhbmdlZC5jb25uZWN0KHNlbGYuX2RlY2suX3NldF90aW1lem9u"
    "ZV9vdmVycmlkZSkKICAgICAgICB0el9hdXRvX2Noay50b2dnbGVkLmNvbm5lY3QobGFtYmRhIGVuYWJsZWQ6IHR6X2NvbWJvLnNl"
    "dEVuYWJsZWQobm90IGVuYWJsZWQpKQogICAgICAgIHR6X3Jvdy5hZGRXaWRnZXQodHpfY29tYm8sIDEpCiAgICAgICAgdHpfaG9z"
    "dCA9IFFXaWRnZXQoKQogICAgICAgIHR6X2hvc3Quc2V0TGF5b3V0KHR6X3JvdykKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHR6"
    "X2hvc3QpCgogICAgZGVmIF9idWlsZF9pbnRlZ3JhdGlvbl9zZWN0aW9uKHNlbGYsIGxheW91dDogUVZCb3hMYXlvdXQpIC0+IE5v"
    "bmU6CiAgICAgICAgc2V0dGluZ3MgPSBDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KQogICAgICAgIGdvb2dsZV9taW51dGVzID0gbWF4"
    "KDEsIGludChzZXR0aW5ncy5nZXQoImdvb2dsZV9pbmJvdW5kX2ludGVydmFsX21zIiwgMzAwMDAwKSkgLy8gNjAwMDApCiAgICAg"
    "ICAgZW1haWxfbWludXRlcyA9IG1heCgxLCBpbnQoc2V0dGluZ3MuZ2V0KCJlbWFpbF9yZWZyZXNoX2ludGVydmFsX21zIiwgMzAw"
    "MDAwKSkgLy8gNjAwMDApCgogICAgICAgIGdvb2dsZV9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgZ29vZ2xlX3Jvdy5hZGRX"
    "aWRnZXQoUUxhYmVsKCJHb29nbGUgcmVmcmVzaCBpbnRlcnZhbCAobWludXRlcyk6IikpCiAgICAgICAgZ29vZ2xlX2JveCA9IFFD"
    "b21ib0JveCgpCiAgICAgICAgZ29vZ2xlX2JveC5zZXRFZGl0YWJsZShUcnVlKQogICAgICAgIGdvb2dsZV9ib3guYWRkSXRlbXMo"
    "WyIxIiwgIjUiLCAiMTAiLCAiMTUiLCAiMzAiLCAiNjAiXSkKICAgICAgICBnb29nbGVfYm94LnNldEN1cnJlbnRUZXh0KHN0cihn"
    "b29nbGVfbWludXRlcykpCiAgICAgICAgZ29vZ2xlX2JveC5jdXJyZW50VGV4dENoYW5nZWQuY29ubmVjdChzZWxmLl9kZWNrLl9z"
    "ZXRfZ29vZ2xlX3JlZnJlc2hfbWludXRlc19mcm9tX3RleHQpCiAgICAgICAgZ29vZ2xlX3Jvdy5hZGRXaWRnZXQoZ29vZ2xlX2Jv"
    "eCwgMSkKICAgICAgICBnb29nbGVfaG9zdCA9IFFXaWRnZXQoKQogICAgICAgIGdvb2dsZV9ob3N0LnNldExheW91dChnb29nbGVf"
    "cm93KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoZ29vZ2xlX2hvc3QpCgogICAgICAgIGVtYWlsX3JvdyA9IFFIQm94TGF5b3V0"
    "KCkKICAgICAgICBlbWFpbF9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgiRW1haWwgcmVmcmVzaCBpbnRlcnZhbCAobWludXRlcyk6Iikp"
    "CiAgICAgICAgZW1haWxfYm94ID0gUUNvbWJvQm94KCkKICAgICAgICBlbWFpbF9ib3guc2V0RWRpdGFibGUoVHJ1ZSkKICAgICAg"
    "ICBlbWFpbF9ib3guYWRkSXRlbXMoWyIxIiwgIjUiLCAiMTAiLCAiMTUiLCAiMzAiLCAiNjAiXSkKICAgICAgICBlbWFpbF9ib3gu"
    "c2V0Q3VycmVudFRleHQoc3RyKGVtYWlsX21pbnV0ZXMpKQogICAgICAgIGVtYWlsX2JveC5jdXJyZW50VGV4dENoYW5nZWQuY29u"
    "bmVjdChzZWxmLl9kZWNrLl9zZXRfZW1haWxfcmVmcmVzaF9taW51dGVzX2Zyb21fdGV4dCkKICAgICAgICBlbWFpbF9yb3cuYWRk"
    "V2lkZ2V0KGVtYWlsX2JveCwgMSkKICAgICAgICBlbWFpbF9ob3N0ID0gUVdpZGdldCgpCiAgICAgICAgZW1haWxfaG9zdC5zZXRM"
    "YXlvdXQoZW1haWxfcm93KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoZW1haWxfaG9zdCkKCiAgICAgICAgbm90ZSA9IFFMYWJl"
    "bCgiRW1haWwgcG9sbGluZyBmb3VuZGF0aW9uIGlzIGNvbmZpZ3VyYXRpb24tb25seSB1bmxlc3MgYW4gZW1haWwgYmFja2VuZCBp"
    "cyBlbmFibGVkLiIpCiAgICAgICAgbm90ZS5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5"
    "cHg7IikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KG5vdGUpCgogICAgZGVmIF9idWlsZF91aV9zZWN0aW9uKHNlbGYsIGxheW91"
    "dDogUVZCb3hMYXlvdXQpIC0+IE5vbmU6CiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChRTGFiZWwoIldpbmRvdyBTaGVsbCIpKQog"
    "ICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZGVjay5fZnNfYnRuKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5f"
    "ZGVjay5fYmxfYnRuKQoKIyDilIDilIAgTUFJTiBXSU5ET1cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CmNsYXNzIEVjaG9EZWNrKFFNYWluV2luZG93KToKICAgICIiIgogICAgVGhlIG1haW4gRWNobyBEZWNrIHdpbmRvdy4KICAgIEFz"
    "c2VtYmxlcyBhbGwgd2lkZ2V0cywgY29ubmVjdHMgYWxsIHNpZ25hbHMsIG1hbmFnZXMgYWxsIHN0YXRlLgogICAgIiIiCgogICAg"
    "IyDilIDilIAgVG9ycG9yIHRocmVzaG9sZHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICBfRVhURVJOQUxfVlJBTV9UT1JQT1JfR0IgICAgPSAxLjUgICAjIGV4dGVybmFsIFZSQU0gPiB0"
    "aGlzIOKGkiBjb25zaWRlciB0b3Jwb3IKICAgIF9FWFRFUk5BTF9WUkFNX1dBS0VfR0IgICAgICA9IDAuOCAgICMgZXh0ZXJuYWwg"
    "VlJBTSA8IHRoaXMg4oaSIGNvbnNpZGVyIHdha2UKICAgIF9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTICAgICA9IDYgICAgICMgNiDD"
    "lyA1cyA9IDMwIHNlY29uZHMgc3VzdGFpbmVkCiAgICBfV0FLRV9TVVNUQUlORURfVElDS1MgICAgICAgPSAxMiAgICAjIDYwIHNl"
    "Y29uZHMgc3VzdGFpbmVkIGxvdyBwcmVzc3VyZQoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBzdXBlcigpLl9faW5p"
    "dF9fKCkKCiAgICAgICAgIyDilIDilIAgQ29yZSBzdGF0ZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zdGF0dXMgICAgICAgICAgICAgID0gIk9GRkxJ"
    "TkUiCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9zdGFydCAgICAgICA9IHRpbWUudGltZSgpCiAgICAgICAgc2VsZi5fdG9rZW5fY291"
    "bnQgICAgICAgICA9IDAKICAgICAgICBzZWxmLl9mYWNlX2xvY2tlZCAgICAgICAgID0gRmFsc2UKICAgICAgICBzZWxmLl9ibGlu"
    "a19zdGF0ZSAgICAgICAgID0gVHJ1ZQogICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCAgICAgICAgPSBGYWxzZQogICAgICAgIHNl"
    "bGYuX3Nlc3Npb25faWQgICAgICAgICAgPSBmInNlc3Npb25fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVT"
    "Jyl9IgogICAgICAgIHNlbGYuX2FjdGl2ZV90aHJlYWRzOiBsaXN0ID0gW10gICMga2VlcCByZWZzIHRvIHByZXZlbnQgR0Mgd2hp"
    "bGUgcnVubmluZwogICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuOiBib29sID0gVHJ1ZSAgICMgd3JpdGUgc3BlYWtlciBsYWJlbCBi"
    "ZWZvcmUgZmlyc3Qgc3RyZWFtaW5nIHRva2VuCgogICAgICAgICMgVG9ycG9yIC8gVlJBTSB0cmFja2luZwogICAgICAgIHNlbGYu"
    "X3RvcnBvcl9zdGF0ZSAgICAgICAgPSAiQVdBS0UiCiAgICAgICAgc2VsZi5fZGVja192cmFtX2Jhc2UgID0gMC4wICAgIyBiYXNl"
    "bGluZSBWUkFNIGFmdGVyIG1vZGVsIGxvYWQKICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMCAgICAgIyBzdXN0"
    "YWluZWQgcHJlc3N1cmUgY291bnRlcgogICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICAgPSAwICAgICAjIHN1c3RhaW5l"
    "ZCByZWxpZWYgY291bnRlcgogICAgICAgIHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyA9IDAKICAgICAgICBzZWxmLl90b3Jw"
    "b3Jfc2luY2UgICAgICAgID0gTm9uZSAgIyBkYXRldGltZSB3aGVuIHRvcnBvciBiZWdhbgogICAgICAgIHNlbGYuX3N1c3BlbmRl"
    "ZF9kdXJhdGlvbiAgPSAiIiAgICMgZm9ybWF0dGVkIGR1cmF0aW9uIHN0cmluZwoKICAgICAgICAjIOKUgOKUgCBNYW5hZ2VycyDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICBzZWxmLl9tZW1vcnkgICA9IE1lbW9yeU1hbmFnZXIoKQogICAgICAgIHNlbGYuX3Nlc3Npb25zID0gU2Vzc2lv"
    "bk1hbmFnZXIoKQogICAgICAgIHNlbGYuX2xlc3NvbnMgID0gTGVzc29uc0xlYXJuZWREQigpCiAgICAgICAgc2VsZi5fdGFza3Mg"
    "ICAgPSBUYXNrTWFuYWdlcigpCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jYWNoZTogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2Vs"
    "Zi5fcmVjb3Jkc19pbml0aWFsaXplZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jdXJyZW50X2ZvbGRlcl9pZCA9ICJy"
    "b290IgogICAgICAgIHNlbGYuX2dvb2dsZV9hdXRoX3JlYWR5ID0gRmFsc2UKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90"
    "aW1lcjogT3B0aW9uYWxbUVRpbWVyXSA9IE5vbmUKICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyOiBP"
    "cHRpb25hbFtRVGltZXJdID0gTm9uZQogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiX2luZGV4ID0gLTEKICAgICAgICBzZWxmLl90"
    "YXNrc190YWJfaW5kZXggPSAtMQogICAgICAgIHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQgPSBGYWxzZQogICAgICAgIHNlbGYu"
    "X3Rhc2tfZGF0ZV9maWx0ZXIgPSAibmV4dF8zX21vbnRocyIKCiAgICAgICAgIyDilIDilIAgR29vZ2xlIFNlcnZpY2VzIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgSW5zdGFudGlhdGUg"
    "c2VydmljZSB3cmFwcGVycyB1cC1mcm9udDsgYXV0aCBpcyBmb3JjZWQgbGF0ZXIKICAgICAgICAjIGZyb20gbWFpbigpIGFmdGVy"
    "IHdpbmRvdy5zaG93KCkgd2hlbiB0aGUgZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgICAgIGdfY3JlZHNfcGF0aCA9IFBhdGgo"
    "Q0ZHLmdldCgiZ29vZ2xlIiwge30pLmdldCgKICAgICAgICAgICAgImNyZWRlbnRpYWxzIiwKICAgICAgICAgICAgc3RyKGNmZ19w"
    "YXRoKCJnb29nbGUiKSAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIpCiAgICAgICAgKSkKICAgICAgICBnX3Rva2VuX3BhdGgg"
    "PSBQYXRoKENGRy5nZXQoImdvb2dsZSIsIHt9KS5nZXQoCiAgICAgICAgICAgICJ0b2tlbiIsCiAgICAgICAgICAgIHN0cihjZmdf"
    "cGF0aCgiZ29vZ2xlIikgLyAidG9rZW4uanNvbiIpCiAgICAgICAgKSkKICAgICAgICBzZWxmLl9nY2FsID0gR29vZ2xlQ2FsZW5k"
    "YXJTZXJ2aWNlKGdfY3JlZHNfcGF0aCwgZ190b2tlbl9wYXRoKQogICAgICAgIHNlbGYuX2dkcml2ZSA9IEdvb2dsZURvY3NEcml2"
    "ZVNlcnZpY2UoCiAgICAgICAgICAgIGdfY3JlZHNfcGF0aCwKICAgICAgICAgICAgZ190b2tlbl9wYXRoLAogICAgICAgICAgICBs"
    "b2dnZXI9bGFtYmRhIG1zZywgbGV2ZWw9IklORk8iOiBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR0RSSVZFXSB7bXNnfSIsIGxldmVs"
    "KQogICAgICAgICkKCiAgICAgICAgIyBTZWVkIExTTCBydWxlcyBvbiBmaXJzdCBydW4KICAgICAgICBzZWxmLl9sZXNzb25zLnNl"
    "ZWRfbHNsX3J1bGVzKCkKCiAgICAgICAgIyBMb2FkIGVudGl0eSBzdGF0ZQogICAgICAgIHNlbGYuX3N0YXRlID0gc2VsZi5fbWVt"
    "b3J5LmxvYWRfc3RhdGUoKQogICAgICAgIHNlbGYuX3N0YXRlWyJzZXNzaW9uX2NvdW50Il0gPSBzZWxmLl9zdGF0ZS5nZXQoInNl"
    "c3Npb25fY291bnQiLDApICsgMQogICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X3N0YXJ0dXAiXSAgPSBsb2NhbF9ub3dfaXNvKCkK"
    "ICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9zdGF0ZSkKCiAgICAgICAgIyBCdWlsZCBhZGFwdG9yCiAgICAg"
    "ICAgc2VsZi5fYWRhcHRvciA9IGJ1aWxkX2FkYXB0b3JfZnJvbV9jb25maWcoKQoKICAgICAgICAjIEZhY2UgdGltZXIgbWFuYWdl"
    "ciAoc2V0IHVwIGFmdGVyIHdpZGdldHMgYnVpbHQpCiAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3I6IE9wdGlvbmFsW0ZhY2VU"
    "aW1lck1hbmFnZXJdID0gTm9uZQoKICAgICAgICAjIOKUgOKUgCBCdWlsZCBVSSDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLnNldFdpbmRvd1Rp"
    "dGxlKEFQUF9OQU1FKQogICAgICAgIHNlbGYuc2V0TWluaW11bVNpemUoMTIwMCwgNzUwKQogICAgICAgIHNlbGYucmVzaXplKDEz"
    "NTAsIDg1MCkKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQoU1RZTEUpCgogICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKCiAgICAg"
    "ICAgIyBGYWNlIHRpbWVyIG1hbmFnZXIgd2lyZWQgdG8gd2lkZ2V0cwogICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyID0gRmFj"
    "ZVRpbWVyTWFuYWdlcigKICAgICAgICAgICAgc2VsZi5fbWlycm9yLCBzZWxmLl9lbW90aW9uX2Jsb2NrCiAgICAgICAgKQoKICAg"
    "ICAgICAjIOKUgOKUgCBUaW1lcnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc3RhdHNfdGltZXIgPSBRVGltZXIoKQogICAgICAg"
    "IHNlbGYuX3N0YXRzX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl91cGRhdGVfc3RhdHMpCiAgICAgICAgc2VsZi5fc3RhdHNf"
    "dGltZXIuc3RhcnQoMTAwMCkKCiAgICAgICAgc2VsZi5fYmxpbmtfdGltZXIgPSBRVGltZXIoKQogICAgICAgIHNlbGYuX2JsaW5r"
    "X3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9ibGluaykKICAgICAgICBzZWxmLl9ibGlua190aW1lci5zdGFydCg4MDApCgog"
    "ICAgICAgIHNlbGYuX3N0YXRlX3N0cmlwX3RpbWVyID0gUVRpbWVyKCkKICAgICAgICBpZiBBSV9TVEFURVNfRU5BQkxFRCBhbmQg"
    "c2VsZi5fZm9vdGVyX3N0cmlwIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9zdGF0ZV9zdHJpcF90aW1lci50aW1lb3V0"
    "LmNvbm5lY3Qoc2VsZi5fZm9vdGVyX3N0cmlwLnJlZnJlc2gpCiAgICAgICAgICAgIHNlbGYuX3N0YXRlX3N0cmlwX3RpbWVyLnN0"
    "YXJ0KDYwMDAwKQoKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lciA9IFFUaW1lcihzZWxmKQogICAgICAgIHNlbGYu"
    "X2dvb2dsZV9pbmJvdW5kX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9vbl9nb29nbGVfaW5ib3VuZF90aW1lcl90aWNrKQog"
    "ICAgICAgIHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyLnN0YXJ0KHNlbGYuX2dldF9nb29nbGVfcmVmcmVzaF9pbnRlcnZhbF9t"
    "cygpKQoKICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAgICAgc2Vs"
    "Zi5fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fb25fZ29vZ2xlX3JlY29yZHNfcmVm"
    "cmVzaF90aW1lcl90aWNrKQogICAgICAgIHNlbGYuX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXIuc3RhcnQoc2VsZi5fZ2V0"
    "X2dvb2dsZV9yZWZyZXNoX2ludGVydmFsX21zKCkpCgogICAgICAgICMg4pSA4pSAIFNjaGVkdWxlciBhbmQgc3RhcnR1cCBkZWZl"
    "cnJlZCB1bnRpbCBhZnRlciB3aW5kb3cuc2hvdygpIOKUgOKUgOKUgAogICAgICAgICMgRG8gTk9UIGNhbGwgX3NldHVwX3NjaGVk"
    "dWxlcigpIG9yIF9zdGFydHVwX3NlcXVlbmNlKCkgaGVyZS4KICAgICAgICAjIEJvdGggYXJlIHRyaWdnZXJlZCB2aWEgUVRpbWVy"
    "LnNpbmdsZVNob3QgZnJvbSBtYWluKCkgYWZ0ZXIKICAgICAgICAjIHdpbmRvdy5zaG93KCkgYW5kIGFwcC5leGVjKCkgYmVnaW5z"
    "IHJ1bm5pbmcuCgogICAgIyDilIDilIAgVUkgQ09OU1RSVUNUSU9OIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9idWlsZF91"
    "aShzZWxmKSAtPiBOb25lOgogICAgICAgIGNlbnRyYWwgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLnNldENlbnRyYWxXaWRnZXQo"
    "Y2VudHJhbCkKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoY2VudHJhbCkKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lu"
    "cyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICAjIOKUgOKUgCBUaXRsZSBiYXIg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fYnVpbGRfdGl0bGVfYmFyKCkpCgogICAgICAgICMg4pSA4pSAIEJvZHk6IEpvdXJuYWwg"
    "fCBDaGF0IHwgU3lzdGVtcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBib2R5ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJvZHkuc2V0"
    "U3BhY2luZyg0KQoKICAgICAgICAjIEpvdXJuYWwgc2lkZWJhciAobGVmdCkKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIg"
    "PSBKb3VybmFsU2lkZWJhcihzZWxmLl9zZXNzaW9ucykKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2Vzc2lvbl9sb2Fk"
    "X3JlcXVlc3RlZC5jb25uZWN0KAogICAgICAgICAgICBzZWxmLl9sb2FkX2pvdXJuYWxfc2Vzc2lvbikKICAgICAgICBzZWxmLl9q"
    "b3VybmFsX3NpZGViYXIuc2Vzc2lvbl9jbGVhcl9yZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5fY2xlYXJfam91"
    "cm5hbF9zZXNzaW9uKQogICAgICAgIGJvZHkuYWRkV2lkZ2V0KHNlbGYuX2pvdXJuYWxfc2lkZWJhcikKCiAgICAgICAgIyBDaGF0"
    "IHBhbmVsIChjZW50ZXIsIGV4cGFuZHMpCiAgICAgICAgYm9keS5hZGRMYXlvdXQoc2VsZi5fYnVpbGRfY2hhdF9wYW5lbCgpLCAx"
    "KQoKICAgICAgICAjIFN5c3RlbXMgKHJpZ2h0KQogICAgICAgIGJvZHkuYWRkTGF5b3V0KHNlbGYuX2J1aWxkX3NwZWxsYm9va19w"
    "YW5lbCgpKQoKICAgICAgICByb290LmFkZExheW91dChib2R5LCAxKQoKICAgICAgICAjIOKUgOKUgCBGb290ZXIg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgZm9vdGVyID0gUUxhYmVsKAogICAgICAgICAgICBmIuKcpiB7QVBQX05BTUV9IOKAlCB2e0FQUF9WRVJTSU9OfSDi"
    "nKYiCiAgICAgICAgKQogICAgICAgIGZvb3Rlci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJ"
    "TX07IGZvbnQtc2l6ZTogOXB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNL"
    "X0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIGZvb3Rlci5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGln"
    "bkNlbnRlcikKICAgICAgICByb290LmFkZFdpZGdldChmb290ZXIpCgogICAgZGVmIF9idWlsZF90aXRsZV9iYXIoc2VsZikgLT4g"
    "UVdpZGdldDoKICAgICAgICBiYXIgPSBRV2lkZ2V0KCkKICAgICAgICBiYXIuc2V0Rml4ZWRIZWlnaHQoMzYpCiAgICAgICAgYmFy"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJ"
    "TVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCiAgICAgICAgbGF5b3V0ID0g"
    "UUhCb3hMYXlvdXQoYmFyKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMTAsIDAsIDEwLCAwKQogICAgICAgIGxh"
    "eW91dC5zZXRTcGFjaW5nKDYpCgogICAgICAgIHRpdGxlID0gUUxhYmVsKGYi4pymIHtBUFBfTkFNRX0iKQogICAgICAgIHRpdGxl"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDEzcHg7IGZvbnQtd2Vp"
    "Z2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYibGV0dGVyLXNwYWNpbmc6IDJweDsgYm9yZGVyOiBub25lOyBmb250LWZhbWlseTog"
    "e0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIHJ1bmVzID0gUUxhYmVsKFJVTkVTKQogICAgICAgIHJ1bmVz"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTERfRElNfTsgZm9udC1zaXplOiAxMHB4OyBib3JkZXI6"
    "IG5vbmU7IgogICAgICAgICkKICAgICAgICBydW5lcy5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikK"
    "CiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwgPSBRTGFiZWwoZiLil4kge1VJX09GRkxJTkVfU1RBVFVTfSIpCiAgICAgICAgc2Vs"
    "Zi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQkxPT0R9OyBmb250LXNpemU6IDEy"
    "cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5z"
    "ZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnblJpZ2h0KQoKICAgICAgICAjIFN1c3BlbnNpb24gcGFuZWwKICAgICAg"
    "ICBzZWxmLl90b3Jwb3JfcGFuZWwgPSBOb25lCiAgICAgICAgaWYgU1VTUEVOU0lPTl9FTkFCTEVEOgogICAgICAgICAgICBzZWxm"
    "Ll90b3Jwb3JfcGFuZWwgPSBUb3Jwb3JQYW5lbCgpCiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9wYW5lbC5zdGF0ZV9jaGFuZ2Vk"
    "LmNvbm5lY3Qoc2VsZi5fb25fdG9ycG9yX3N0YXRlX2NoYW5nZWQpCgogICAgICAgICMgSWRsZSB0b2dnbGUKICAgICAgICBpZGxl"
    "X2VuYWJsZWQgPSBib29sKENGRy5nZXQoInNldHRpbmdzIiwge30pLmdldCgiaWRsZV9lbmFibGVkIiwgRmFsc2UpKQogICAgICAg"
    "IHNlbGYuX2lkbGVfYnRuID0gUVB1c2hCdXR0b24oIklETEUgT04iIGlmIGlkbGVfZW5hYmxlZCBlbHNlICJJRExFIE9GRiIpCiAg"
    "ICAgICAgc2VsZi5faWRsZV9idG4uc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0Q2hlY2thYmxl"
    "KFRydWUpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0Q2hlY2tlZChpZGxlX2VuYWJsZWQpCiAgICAgICAgc2VsZi5faWRsZV9i"
    "dG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAi"
    "CiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAg"
    "ICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIKICAgICAgICApCiAgICAg"
    "ICAgc2VsZi5faWRsZV9idG4udG9nZ2xlZC5jb25uZWN0KHNlbGYuX29uX2lkbGVfdG9nZ2xlZCkKCiAgICAgICAgIyBGUyAvIEJM"
    "IGJ1dHRvbnMKICAgICAgICBzZWxmLl9mc19idG4gPSBRUHVzaEJ1dHRvbigiRnVsbHNjcmVlbiIpCiAgICAgICAgc2VsZi5fYmxf"
    "YnRuID0gUVB1c2hCdXR0b24oIkJvcmRlcmxlc3MiKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4gPSBRUHVzaEJ1dHRvbigiRXhw"
    "b3J0IikKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4gPSBRUHVzaEJ1dHRvbigiU2h1dGRvd24iKQogICAgICAgIGZvciBidG4g"
    "aW4gKHNlbGYuX2ZzX2J0biwgc2VsZi5fYmxfYnRuLCBzZWxmLl9leHBvcnRfYnRuKToKICAgICAgICAgICAgYnRuLnNldEZpeGVk"
    "SGVpZ2h0KDIyKQogICAgICAgICAgICBidG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0Nf"
    "QkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklN"
    "U09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAw"
    "OyIKICAgICAgICAgICAgKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4uc2V0Rml4ZWRXaWR0aCg0NikKICAgICAgICBzZWxmLl9z"
    "aHV0ZG93bl9idG4uc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldEZpeGVkV2lkdGgoNjgp"
    "CiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcz"
    "fTsgY29sb3I6IHtDX0JMT09EfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JMT09EfTsgZm9udC1zaXpl"
    "OiA5cHg7ICIKICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMDsiCiAgICAgICAgKQogICAgICAgIHNl"
    "bGYuX2ZzX2J0bi5zZXRUb29sVGlwKCJGdWxsc2NyZWVuIChGMTEpIikKICAgICAgICBzZWxmLl9ibF9idG4uc2V0VG9vbFRpcCgi"
    "Qm9yZGVybGVzcyAoRjEwKSIpCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0bi5zZXRUb29sVGlwKCJFeHBvcnQgY2hhdCBzZXNzaW9u"
    "IHRvIFRYVCBmaWxlIikKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uc2V0VG9vbFRpcChmIkdyYWNlZnVsIHNodXRkb3duIOKA"
    "lCB7REVDS19OQU1FfSBzcGVha3MgdGhlaXIgbGFzdCB3b3JkcyIpCiAgICAgICAgc2VsZi5fZnNfYnRuLmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl90b2dnbGVfZnVsbHNjcmVlbikKICAgICAgICBzZWxmLl9ibF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2ds"
    "ZV9ib3JkZXJsZXNzKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2V4cG9ydF9jaGF0KQog"
    "ICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5faW5pdGlhdGVfc2h1dGRvd25fZGlhbG9nKQoK"
    "ICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHRpdGxlKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQocnVuZXMsIDEpCiAgICAgICAg"
    "bGF5b3V0LmFkZFdpZGdldChzZWxmLnN0YXR1c19sYWJlbCkKICAgICAgICBsYXlvdXQuYWRkU3BhY2luZyg4KQogICAgICAgIGxh"
    "eW91dC5hZGRXaWRnZXQoc2VsZi5fZXhwb3J0X2J0bikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3NodXRkb3duX2J0"
    "bikKCiAgICAgICAgcmV0dXJuIGJhcgoKICAgIGRlZiBfYnVpbGRfY2hhdF9wYW5lbChzZWxmKSAtPiBRVkJveExheW91dDoKICAg"
    "ICAgICBsYXlvdXQgPSBRVkJveExheW91dCgpCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBNYWluIHRh"
    "YiB3aWRnZXQg4oCUIHBlcnNvbmEgY2hhdCB0YWIgfCBTZWxmCiAgICAgICAgc2VsZi5fbWFpbl90YWJzID0gUVRhYldpZGdldCgp"
    "CiAgICAgICAgc2VsZi5fbWFpbl90YWJzLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUVRhYldpZGdldDo6cGFuZSB7eyBi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsg"
    "fX0iCiAgICAgICAgICAgIGYiUVRhYkJhcjo6dGFiIHt7IGJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07"
    "ICIKICAgICAgICAgICAgZiJwYWRkaW5nOiA0cHggMTJweDsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAg"
    "ICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsgfX0iCiAgICAgICAgICAgIGYi"
    "UVRhYkJhcjo6dGFiOnNlbGVjdGVkIHt7IGJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAg"
    "ICBmImJvcmRlci1ib3R0b206IDJweCBzb2xpZCB7Q19DUklNU09OfTsgfX0iCiAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBU"
    "YWIgMDogUGVyc29uYSBjaGF0IHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWFuY2Vfd2lkZ2V0"
    "ID0gUVdpZGdldCgpCiAgICAgICAgc2VhbmNlX2xheW91dCA9IFFWQm94TGF5b3V0KHNlYW5jZV93aWRnZXQpCiAgICAgICAgc2Vh"
    "bmNlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWFuY2VfbGF5b3V0LnNldFNwYWNpbmco"
    "MCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRS"
    "ZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tn"
    "cm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7ICIKICAgICAg"
    "ICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEycHg7IHBhZGRpbmc6IDhweDsiCiAg"
    "ICAgICAgKQogICAgICAgIHNlYW5jZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2NoYXRfZGlzcGxheSkKICAgICAgICBzZWxmLl9t"
    "YWluX3RhYnMuYWRkVGFiKHNlYW5jZV93aWRnZXQsIGYi4p2nIHtVSV9DSEFUX1dJTkRPV30iKQoKICAgICAgICAjIOKUgOKUgCBU"
    "YWIgMTogU2VsZiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgICAgICBzZWxmLl9zZWxmX3RhYl93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmX2xheW91dCA9IFFWQm94"
    "TGF5b3V0KHNlbGYuX3NlbGZfdGFiX3dpZGdldCkKICAgICAgICBzZWxmX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwg"
    "NCwgNCkKICAgICAgICBzZWxmX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5fc2VsZl9kaXNwbGF5ID0gUVRleHRF"
    "ZGl0KCkKICAgICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9zZWxmX2Rpc3Bs"
    "YXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX0dPTER9OyAi"
    "CiAgICAgICAgICAgIGYiYm9yZGVyOiBub25lOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJp"
    "ZjsgZm9udC1zaXplOiAxMnB4OyBwYWRkaW5nOiA4cHg7IgogICAgICAgICkKICAgICAgICBzZWxmX2xheW91dC5hZGRXaWRnZXQo"
    "c2VsZi5fc2VsZl9kaXNwbGF5LCAxKQogICAgICAgIHNlbGYuX21haW5fdGFicy5hZGRUYWIoc2VsZi5fc2VsZl90YWJfd2lkZ2V0"
    "LCAi4peJIFNFTEYiKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX21haW5fdGFicywgMSkKCiAgICAgICAgIyDilIDi"
    "lIAgQm90dG9tIHN0YXR1cy9yZXNvdXJjZSBibG9jayByb3cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgIyBNYW5kYXRvcnkgcGVybWFuZW50IHN0"
    "cnVjdHVyZSBhY3Jvc3MgYWxsIHBlcnNvbmFzOgogICAgICAgICMgTUlSUk9SIHwgW0xPV0VSLU1JRERMRSBQRVJNQU5FTlQgRk9P"
    "VFBSSU5UXQogICAgICAgIGJsb2NrX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBibG9ja19yb3cuc2V0U3BhY2luZygyKQoK"
    "ICAgICAgICAjIE1pcnJvciAobmV2ZXIgY29sbGFwc2VzKQogICAgICAgIG1pcnJvcl93cmFwID0gUVdpZGdldCgpCiAgICAgICAg"
    "bXdfbGF5b3V0ID0gUVZCb3hMYXlvdXQobWlycm9yX3dyYXApCiAgICAgICAgbXdfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygw"
    "LCAwLCAwLCAwKQogICAgICAgIG13X2xheW91dC5zZXRTcGFjaW5nKDIpCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdldChfc2Vj"
    "dGlvbl9sYmwoZiLinacge1VJX01JUlJPUl9MQUJFTH0iKSkKICAgICAgICBzZWxmLl9taXJyb3IgPSBNaXJyb3JXaWRnZXQoKQog"
    "ICAgICAgIHNlbGYuX21pcnJvci5zZXRGaXhlZFNpemUoMTYwLCAxNjApCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdldChzZWxm"
    "Ll9taXJyb3IpCiAgICAgICAgYmxvY2tfcm93LmFkZFdpZGdldChtaXJyb3Jfd3JhcCwgMCkKCiAgICAgICAgIyBNaWRkbGUgbG93"
    "ZXIgYmxvY2sga2VlcHMgYSBwZXJtYW5lbnQgZm9vdHByaW50OgogICAgICAgICMgbGVmdCA9IGNvbXBhY3Qgc3RhY2sgYXJlYSwg"
    "cmlnaHQgPSBmaXhlZCBleHBhbmRlZC1yb3cgc2xvdHMuCiAgICAgICAgbWlkZGxlX3dyYXAgPSBRV2lkZ2V0KCkKICAgICAgICBt"
    "aWRkbGVfbGF5b3V0ID0gUUhCb3hMYXlvdXQobWlkZGxlX3dyYXApCiAgICAgICAgbWlkZGxlX2xheW91dC5zZXRDb250ZW50c01h"
    "cmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBtaWRkbGVfbGF5b3V0LnNldFNwYWNpbmcoMikKCiAgICAgICAgc2VsZi5fbG93ZXJf"
    "c3RhY2tfd3JhcCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX3dyYXAuc2V0TWluaW11bVdpZHRoKDEzMCkK"
    "ICAgICAgICBzZWxmLl9sb3dlcl9zdGFja193cmFwLnNldE1heGltdW1XaWR0aCgxMzApCiAgICAgICAgc2VsZi5fbG93ZXJfc3Rh"
    "Y2tfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fbG93ZXJfc3RhY2tfd3JhcCkKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja19s"
    "YXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0LnNldFNw"
    "YWNpbmcoMikKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja193cmFwLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgbWlkZGxlX2xh"
    "eW91dC5hZGRXaWRnZXQoc2VsZi5fbG93ZXJfc3RhY2tfd3JhcCwgMCkKCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93"
    "ID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93X2xheW91dCA9IFFHcmlkTGF5b3V0KHNlbGYuX2xv"
    "d2VyX2V4cGFuZGVkX3JvdykKICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lu"
    "cygwLCAwLCAwLCAwKQogICAgICAgIHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Jvd19sYXlvdXQuc2V0SG9yaXpvbnRhbFNwYWNpbmco"
    "MikKICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LnNldFZlcnRpY2FsU3BhY2luZygyKQogICAgICAgIG1p"
    "ZGRsZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2xvd2VyX2V4cGFuZGVkX3JvdywgMSkKCiAgICAgICAgIyBFbW90aW9uIGJsb2Nr"
    "IChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9lbW90aW9uX2Jsb2NrID0gRW1vdGlvbkJsb2NrKCkKICAgICAgICBzZWxmLl9l"
    "bW90aW9uX2Jsb2NrX3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfRU1PVElPTlNfTEFCRUx9"
    "Iiwgc2VsZi5fZW1vdGlvbl9ibG9jaywKICAgICAgICAgICAgZXhwYW5kZWQ9VHJ1ZSwgbWluX3dpZHRoPTEzMCwgcmVzZXJ2ZV93"
    "aWR0aD1UcnVlCiAgICAgICAgKQoKICAgICAgICAjIExlZnQgcmVzb3VyY2Ugb3JiIChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxm"
    "Ll9sZWZ0X29yYiA9IFNwaGVyZVdpZGdldCgKICAgICAgICAgICAgVUlfTEVGVF9PUkJfTEFCRUwsIENfQ1JJTVNPTiwgQ19DUklN"
    "U09OX0RJTQogICAgICAgICkKICAgICAgICBzZWxmLl9sZWZ0X29yYl93cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAg"
    "ICAgZiLinacge1VJX0xFRlRfT1JCX1RJVExFfSIsIHNlbGYuX2xlZnRfb3JiLAogICAgICAgICAgICBtaW5fd2lkdGg9OTAsIHJl"
    "c2VydmVfd2lkdGg9VHJ1ZQogICAgICAgICkKCiAgICAgICAgIyBDZW50ZXIgY3ljbGUgd2lkZ2V0IChjb2xsYXBzaWJsZSkKICAg"
    "ICAgICBzZWxmLl9jeWNsZV93aWRnZXQgPSBDeWNsZVdpZGdldCgpCiAgICAgICAgc2VsZi5fY3ljbGVfd3JhcCA9IENvbGxhcHNp"
    "YmxlQmxvY2soCiAgICAgICAgICAgIGYi4p2nIHtVSV9DWUNMRV9USVRMRX0iLCBzZWxmLl9jeWNsZV93aWRnZXQsCiAgICAgICAg"
    "ICAgIG1pbl93aWR0aD05MCwgcmVzZXJ2ZV93aWR0aD1UcnVlCiAgICAgICAgKQoKICAgICAgICAjIFJpZ2h0IHJlc291cmNlIG9y"
    "YiAoY29sbGFwc2libGUpCiAgICAgICAgc2VsZi5fcmlnaHRfb3JiID0gU3BoZXJlV2lkZ2V0KAogICAgICAgICAgICBVSV9SSUdI"
    "VF9PUkJfTEFCRUwsIENfUFVSUExFLCBDX1BVUlBMRV9ESU0KICAgICAgICApCiAgICAgICAgc2VsZi5fcmlnaHRfb3JiX3dyYXAg"
    "PSBDb2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfUklHSFRfT1JCX1RJVExFfSIsIHNlbGYuX3JpZ2h0X29y"
    "YiwKICAgICAgICAgICAgbWluX3dpZHRoPTkwLCByZXNlcnZlX3dpZHRoPVRydWUKICAgICAgICApCgogICAgICAgICMgRXNzZW5j"
    "ZSAoMiBnYXVnZXMsIGNvbGxhcHNpYmxlKQogICAgICAgIGVzc2VuY2Vfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgZXNzZW5j"
    "ZV9sYXlvdXQgPSBRVkJveExheW91dChlc3NlbmNlX3dpZGdldCkKICAgICAgICBlc3NlbmNlX2xheW91dC5zZXRDb250ZW50c01h"
    "cmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBlc3NlbmNlX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5fZXNzZW5j"
    "ZV9wcmltYXJ5X2dhdWdlICAgPSBHYXVnZVdpZGdldChVSV9FU1NFTkNFX1BSSU1BUlksICAgIiUiLCAxMDAuMCwgQ19DUklNU09O"
    "KQogICAgICAgIHNlbGYuX2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdlID0gR2F1Z2VXaWRnZXQoVUlfRVNTRU5DRV9TRUNPTkRBUlks"
    "ICIlIiwgMTAwLjAsIENfR1JFRU4pCiAgICAgICAgZXNzZW5jZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2Vzc2VuY2VfcHJpbWFy"
    "eV9nYXVnZSkKICAgICAgICBlc3NlbmNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2UpCiAg"
    "ICAgICAgc2VsZi5fZXNzZW5jZV93cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacge1VJX0VTU0VOQ0Vf"
    "VElUTEV9IiwgZXNzZW5jZV93aWRnZXQsCiAgICAgICAgICAgIG1pbl93aWR0aD0xMTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAg"
    "ICAgICkKCiAgICAgICAgIyBFeHBhbmRlZCByb3cgc2xvdHMgbXVzdCBzdGF5IGluIGNhbm9uaWNhbCB2aXN1YWwgb3JkZXIuCiAg"
    "ICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfc2xvdF9vcmRlciA9IFsKICAgICAgICAgICAgImVtb3Rpb25zIiwgInByaW1hcnki"
    "LCAiY3ljbGUiLCAic2Vjb25kYXJ5IiwgImVzc2VuY2UiCiAgICAgICAgXQogICAgICAgIHNlbGYuX2xvd2VyX2NvbXBhY3Rfc3Rh"
    "Y2tfb3JkZXIgPSBbCiAgICAgICAgICAgICJjeWNsZSIsICJwcmltYXJ5IiwgInNlY29uZGFyeSIsICJlc3NlbmNlIiwgImVtb3Rp"
    "b25zIgogICAgICAgIF0KICAgICAgICBzZWxmLl9sb3dlcl9tb2R1bGVfd3JhcHMgPSB7CiAgICAgICAgICAgICJlbW90aW9ucyI6"
    "IHNlbGYuX2Vtb3Rpb25fYmxvY2tfd3JhcCwKICAgICAgICAgICAgInByaW1hcnkiOiBzZWxmLl9sZWZ0X29yYl93cmFwLAogICAg"
    "ICAgICAgICAiY3ljbGUiOiBzZWxmLl9jeWNsZV93cmFwLAogICAgICAgICAgICAic2Vjb25kYXJ5Ijogc2VsZi5fcmlnaHRfb3Ji"
    "X3dyYXAsCiAgICAgICAgICAgICJlc3NlbmNlIjogc2VsZi5fZXNzZW5jZV93cmFwLAogICAgICAgIH0KCiAgICAgICAgc2VsZi5f"
    "bG93ZXJfcm93X3Nsb3RzID0ge30KICAgICAgICBmb3IgY29sLCBrZXkgaW4gZW51bWVyYXRlKHNlbGYuX2xvd2VyX2V4cGFuZGVk"
    "X3Nsb3Rfb3JkZXIpOgogICAgICAgICAgICBzbG90ID0gUVdpZGdldCgpCiAgICAgICAgICAgIHNsb3RfbGF5b3V0ID0gUVZCb3hM"
    "YXlvdXQoc2xvdCkKICAgICAgICAgICAgc2xvdF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAg"
    "ICAgIHNsb3RfbGF5b3V0LnNldFNwYWNpbmcoMCkKICAgICAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93X2xheW91dC5h"
    "ZGRXaWRnZXQoc2xvdCwgMCwgY29sKQogICAgICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LnNldENvbHVt"
    "blN0cmV0Y2goY29sLCAxKQogICAgICAgICAgICBzZWxmLl9sb3dlcl9yb3dfc2xvdHNba2V5XSA9IHNsb3RfbGF5b3V0CgogICAg"
    "ICAgIGZvciB3cmFwIGluIHNlbGYuX2xvd2VyX21vZHVsZV93cmFwcy52YWx1ZXMoKToKICAgICAgICAgICAgd3JhcC50b2dnbGVk"
    "LmNvbm5lY3Qoc2VsZi5fcmVmcmVzaF9sb3dlcl9taWRkbGVfbGF5b3V0KQoKICAgICAgICBzZWxmLl9yZWZyZXNoX2xvd2VyX21p"
    "ZGRsZV9sYXlvdXQoKQoKICAgICAgICBibG9ja19yb3cuYWRkV2lkZ2V0KG1pZGRsZV93cmFwLCAxKQogICAgICAgIGxheW91dC5h"
    "ZGRMYXlvdXQoYmxvY2tfcm93KQoKICAgICAgICAjIEZvb3RlciBzdGF0ZSBzdHJpcCAoYmVsb3cgYmxvY2sgcm93IOKAlCBwZXJt"
    "YW5lbnQgVUkgc3RydWN0dXJlKQogICAgICAgIHNlbGYuX2Zvb3Rlcl9zdHJpcCA9IEZvb3RlclN0cmlwV2lkZ2V0KCkKICAgICAg"
    "ICBzZWxmLl9mb290ZXJfc3RyaXAuc2V0X2xhYmVsKFVJX0ZPT1RFUl9TVFJJUF9MQUJFTCkKICAgICAgICBsYXlvdXQuYWRkV2lk"
    "Z2V0KHNlbGYuX2Zvb3Rlcl9zdHJpcCkKCiAgICAgICAgIyDilIDilIAgSW5wdXQgcm93IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGlucHV0X3JvdyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBwcm9tcHRfc3ltID0gUUxhYmVsKCLinKYiKQogICAgICAgIHByb21wdF9zeW0uc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTZweDsgZm9udC13ZWlnaHQ6IGJvbGQ7"
    "IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHByb21wdF9zeW0uc2V0Rml4ZWRXaWR0aCgyMCkKCiAgICAgICAgc2Vs"
    "Zi5faW5wdXRfZmllbGQgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dChV"
    "SV9JTlBVVF9QTEFDRUhPTERFUikKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5yZXR1cm5QcmVzc2VkLmNvbm5lY3Qoc2VsZi5f"
    "c2VuZF9tZXNzYWdlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2UpCgogICAgICAgIHNlbGYuX3Nl"
    "bmRfYnRuID0gUVB1c2hCdXR0b24oVUlfU0VORF9CVVRUT04pCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0Rml4ZWRXaWR0aCgx"
    "MTApCiAgICAgICAgc2VsZi5fc2VuZF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3NlbmRfbWVzc2FnZSkKICAgICAgICBzZWxm"
    "Ll9zZW5kX2J0bi5zZXRFbmFibGVkKEZhbHNlKQoKICAgICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHByb21wdF9zeW0pCiAgICAg"
    "ICAgaW5wdXRfcm93LmFkZFdpZGdldChzZWxmLl9pbnB1dF9maWVsZCkKICAgICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHNlbGYu"
    "X3NlbmRfYnRuKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoaW5wdXRfcm93KQoKICAgICAgICByZXR1cm4gbGF5b3V0CgogICAg"
    "ZGVmIF9jbGVhcl9sYXlvdXRfd2lkZ2V0cyhzZWxmLCBsYXlvdXQ6IFFWQm94TGF5b3V0KSAtPiBOb25lOgogICAgICAgIHdoaWxl"
    "IGxheW91dC5jb3VudCgpOgogICAgICAgICAgICBpdGVtID0gbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICB3aWRnZXQgPSBp"
    "dGVtLndpZGdldCgpCiAgICAgICAgICAgIGlmIHdpZGdldCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgIHdpZGdldC5zZXRQ"
    "YXJlbnQoTm9uZSkKCiAgICBkZWYgX3JlZnJlc2hfbG93ZXJfbWlkZGxlX2xheW91dChzZWxmLCAqX2FyZ3MpIC0+IE5vbmU6CiAg"
    "ICAgICAgY29sbGFwc2VkX2NvdW50ID0gMAoKICAgICAgICAjIFJlYnVpbGQgZXhwYW5kZWQgcm93IHNsb3RzIGluIGZpeGVkIGV4"
    "cGFuZGVkIG9yZGVyLgogICAgICAgIGZvciBrZXkgaW4gc2VsZi5fbG93ZXJfZXhwYW5kZWRfc2xvdF9vcmRlcjoKICAgICAgICAg"
    "ICAgc2xvdF9sYXlvdXQgPSBzZWxmLl9sb3dlcl9yb3dfc2xvdHNba2V5XQogICAgICAgICAgICBzZWxmLl9jbGVhcl9sYXlvdXRf"
    "d2lkZ2V0cyhzbG90X2xheW91dCkKICAgICAgICAgICAgd3JhcCA9IHNlbGYuX2xvd2VyX21vZHVsZV93cmFwc1trZXldCiAgICAg"
    "ICAgICAgIGlmIHdyYXAuaXNfZXhwYW5kZWQoKToKICAgICAgICAgICAgICAgIHNsb3RfbGF5b3V0LmFkZFdpZGdldCh3cmFwKQog"
    "ICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgY29sbGFwc2VkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgIHNsb3Rf"
    "bGF5b3V0LmFkZFN0cmV0Y2goMSkKCiAgICAgICAgIyBSZWJ1aWxkIGNvbXBhY3Qgc3RhY2sgaW4gY2Fub25pY2FsIGNvbXBhY3Qg"
    "b3JkZXIuCiAgICAgICAgc2VsZi5fY2xlYXJfbGF5b3V0X3dpZGdldHMoc2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0KQogICAgICAg"
    "IGZvciBrZXkgaW4gc2VsZi5fbG93ZXJfY29tcGFjdF9zdGFja19vcmRlcjoKICAgICAgICAgICAgd3JhcCA9IHNlbGYuX2xvd2Vy"
    "X21vZHVsZV93cmFwc1trZXldCiAgICAgICAgICAgIGlmIG5vdCB3cmFwLmlzX2V4cGFuZGVkKCk6CiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9sb3dlcl9zdGFja19sYXlvdXQuYWRkV2lkZ2V0KHdyYXApCgogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX2xheW91dC5h"
    "ZGRTdHJldGNoKDEpCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfd3JhcC5zZXRWaXNpYmxlKGNvbGxhcHNlZF9jb3VudCA+IDAp"
    "CgogICAgZGVmIF9idWlsZF9zcGVsbGJvb2tfcGFuZWwoc2VsZikgLT4gUVZCb3hMYXlvdXQ6CiAgICAgICAgbGF5b3V0ID0gUVZC"
    "b3hMYXlvdXQoKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0"
    "U3BhY2luZyg0KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgU1lTVEVNUyIpKQoKICAgICAgICAj"
    "IFRhYiB3aWRnZXQKICAgICAgICBzZWxmLl9zcGVsbF90YWJzID0gUVRhYldpZGdldCgpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFi"
    "cy5zZXRNaW5pbXVtV2lkdGgoMjgwKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuc2V0U2l6ZVBvbGljeSgKICAgICAgICAgICAg"
    "UVNpemVQb2xpY3kuUG9saWN5LkV4cGFuZGluZywKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5LkV4cGFuZGluZwogICAg"
    "ICAgICkKCiAgICAgICAgIyBCdWlsZCBEaWFnbm9zdGljc1RhYiBlYXJseSBzbyBzdGFydHVwIGxvZ3MgYXJlIHNhZmUgZXZlbiBi"
    "ZWZvcmUKICAgICAgICAjIHRoZSBEaWFnbm9zdGljcyB0YWIgaXMgYXR0YWNoZWQgdG8gdGhlIHdpZGdldC4KICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYiA9IERpYWdub3N0aWNzVGFiKCkKCiAgICAgICAgIyDilIDilIAgSW5zdHJ1bWVudHMgdGFiIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2h3X3BhbmVsID0gSGFy"
    "ZHdhcmVQYW5lbCgpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5faHdfcGFuZWwsICJJbnN0cnVtZW50cyIp"
    "CgogICAgICAgICMg4pSA4pSAIFJlY29yZHMgdGFiIChyZWFsKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYiA9IFJlY29yZHNUYWIoKQogICAgICAgIHNlbGYuX3JlY29yZHNfdGFi"
    "X2luZGV4ID0gc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fcmVjb3Jkc190YWIsICJSZWNvcmRzIikKICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coIltTUEVMTEJPT0tdIHJlYWwgUmVjb3Jkc1RhYiBhdHRhY2hlZC4iLCAiSU5GTyIpCgogICAgICAgICMg"
    "4pSA4pSAIFRhc2tzIHRhYiAocmVhbCkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgc2VsZi5fdGFza3NfdGFiID0gVGFza3NUYWIoCiAgICAgICAgICAgIHRhc2tzX3Byb3ZpZGVyPXNlbGYuX2ZpbHRl"
    "cmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeSwKICAgICAgICAgICAgb25fYWRkX2VkaXRvcl9vcGVuPXNlbGYuX29wZW5fdGFza19lZGl0"
    "b3Jfd29ya3NwYWNlLAogICAgICAgICAgICBvbl9jb21wbGV0ZV9zZWxlY3RlZD1zZWxmLl9jb21wbGV0ZV9zZWxlY3RlZF90YXNr"
    "LAogICAgICAgICAgICBvbl9jYW5jZWxfc2VsZWN0ZWQ9c2VsZi5fY2FuY2VsX3NlbGVjdGVkX3Rhc2ssCiAgICAgICAgICAgIG9u"
    "X3RvZ2dsZV9jb21wbGV0ZWQ9c2VsZi5fdG9nZ2xlX3Nob3dfY29tcGxldGVkX3Rhc2tzLAogICAgICAgICAgICBvbl9wdXJnZV9j"
    "b21wbGV0ZWQ9c2VsZi5fcHVyZ2VfY29tcGxldGVkX3Rhc2tzLAogICAgICAgICAgICBvbl9maWx0ZXJfY2hhbmdlZD1zZWxmLl9v"
    "bl90YXNrX2ZpbHRlcl9jaGFuZ2VkLAogICAgICAgICAgICBvbl9lZGl0b3Jfc2F2ZT1zZWxmLl9zYXZlX3Rhc2tfZWRpdG9yX2dv"
    "b2dsZV9maXJzdCwKICAgICAgICAgICAgb25fZWRpdG9yX2NhbmNlbD1zZWxmLl9jYW5jZWxfdGFza19lZGl0b3Jfd29ya3NwYWNl"
    "LAogICAgICAgICAgICBkaWFnbm9zdGljc19sb2dnZXI9c2VsZi5fZGlhZ190YWIubG9nLAogICAgICAgICkKICAgICAgICBzZWxm"
    "Ll90YXNrc190YWIuc2V0X3Nob3dfY29tcGxldGVkKHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQpCiAgICAgICAgc2VsZi5fdGFz"
    "a3NfdGFiX2luZGV4ID0gc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fdGFza3NfdGFiLCAiVGFza3MiKQogICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZygiW1NQRUxMQk9PS10gcmVhbCBUYXNrc1RhYiBhdHRhY2hlZC4iLCAiSU5GTyIpCgogICAgICAgICMg"
    "4pSA4pSAIFNMIFNjYW5zIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKICAgICAgICBzZWxmLl9zbF9zY2FucyA9IFNMU2NhbnNUYWIoY2ZnX3BhdGgoInNsIikpCiAgICAgICAgc2Vs"
    "Zi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fc2xfc2NhbnMsICJTTCBTY2FucyIpCgogICAgICAgICMg4pSA4pSAIFNMIENvbW1h"
    "bmRzIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBz"
    "ZWxmLl9zbF9jb21tYW5kcyA9IFNMQ29tbWFuZHNUYWIoKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX3Ns"
    "X2NvbW1hbmRzLCAiU0wgQ29tbWFuZHMiKQoKICAgICAgICAjIOKUgOKUgCBKb2IgVHJhY2tlciB0YWIg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fam9iX3RyYWNrZXIgPSBKb2JU"
    "cmFja2VyVGFiKCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9qb2JfdHJhY2tlciwgIkpvYiBUcmFja2Vy"
    "IikKCiAgICAgICAgIyDilIDilIAgTGVzc29ucyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fbGVzc29uc190YWIgPSBMZXNzb25zVGFiKHNlbGYuX2xl"
    "c3NvbnMpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fbGVzc29uc190YWIsICJMZXNzb25zIikKCiAgICAg"
    "ICAgIyBTZWxmIHRhYiBpcyBub3cgaW4gdGhlIG1haW4gYXJlYSBhbG9uZ3NpZGUgdGhlIHBlcnNvbmEgY2hhdCB0YWIKICAgICAg"
    "ICAjIEtlZXAgYSBTZWxmVGFiIGluc3RhbmNlIGZvciBpZGxlIGNvbnRlbnQgZ2VuZXJhdGlvbgogICAgICAgIHNlbGYuX3NlbGZf"
    "dGFiID0gU2VsZlRhYigpCgogICAgICAgICMg4pSA4pSAIE1vZHVsZSBUcmFja2VyIHRhYiDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9tb2R1bGVfdHJhY2tlciA9IE1vZHVsZVRyYWNrZXJUYWIo"
    "KQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX21vZHVsZV90cmFja2VyLCAiTW9kdWxlcyIpCgogICAgICAg"
    "ICMg4pSA4pSAIERpYWdub3N0aWNzIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9kaWFnX3RhYiwgIkRpYWdub3N0aWNzIikKCiAg"
    "ICAgICAgIyDilIDilIAgU2V0dGluZ3MgdGFiIChkZWNrLXdpZGUgcnVudGltZSBjb250cm9scykg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc2V0dGluZ3NfdGFiID0gU2V0dGluZ3NUYWIo"
    "c2VsZikKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9zZXR0aW5nc190YWIsICJTZXR0aW5ncyIpCgogICAg"
    "ICAgIHJpZ2h0X3dvcmtzcGFjZSA9IFFXaWRnZXQoKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQgPSBRVkJveExheW91"
    "dChyaWdodF93b3Jrc3BhY2UpCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwg"
    "MCwgMCkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgcmlnaHRfd29ya3NwYWNl"
    "X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fc3BlbGxfdGFicywgMSkKCiAgICAgICAgY2FsZW5kYXJfbGFiZWwgPSBRTGFiZWwoIuKd"
    "pyBDQUxFTkRBUiIpCiAgICAgICAgY2FsZW5kYXJfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0Nf"
    "R09MRH07IGZvbnQtc2l6ZTogMTBweDsgbGV0dGVyLXNwYWNpbmc6IDJweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJp"
    "ZjsiCiAgICAgICAgKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkV2lkZ2V0KGNhbGVuZGFyX2xhYmVsKQoKICAg"
    "ICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldCA9IE1pbmlDYWxlbmRhcldpZGdldCgpCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRn"
    "ZXQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19D"
    "UklNU09OX0RJTX07IgogICAgICAgICkKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldC5zZXRTaXplUG9saWN5KAogICAgICAg"
    "ICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nLAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuTWF4aW11bQog"
    "ICAgICAgICkKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldC5zZXRNYXhpbXVtSGVpZ2h0KDI2MCkKICAgICAgICBzZWxmLmNh"
    "bGVuZGFyX3dpZGdldC5jYWxlbmRhci5jbGlja2VkLmNvbm5lY3Qoc2VsZi5faW5zZXJ0X2NhbGVuZGFyX2RhdGUpCiAgICAgICAg"
    "cmlnaHRfd29ya3NwYWNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5jYWxlbmRhcl93aWRnZXQsIDApCiAgICAgICAgcmlnaHRfd29y"
    "a3NwYWNlX2xheW91dC5hZGRTdHJldGNoKDApCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQocmlnaHRfd29ya3NwYWNlLCAxKQog"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgIltMQVlPVVRdIHJpZ2h0LXNpZGUgY2FsZW5kYXIgcmVzdG9y"
    "ZWQgKHBlcnNpc3RlbnQgbG93ZXItcmlnaHQgc2VjdGlvbikuIiwKICAgICAgICAgICAgIklORk8iCiAgICAgICAgKQogICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgIltMQVlPVVRdIHBlcnNpc3RlbnQgbWluaSBjYWxlbmRhciByZXN0b3Jl"
    "ZC9jb25maXJtZWQgKGFsd2F5cyB2aXNpYmxlIGxvd2VyLXJpZ2h0KS4iLAogICAgICAgICAgICAiSU5GTyIKICAgICAgICApCiAg"
    "ICAgICAgcmV0dXJuIGxheW91dAoKICAgICMg4pSA4pSAIFNUQVJUVVAgU0VRVUVOQ0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYg"
    "X3N0YXJ0dXBfc2VxdWVuY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgZiLinKYg"
    "e0FQUF9OQU1FfSBBV0FLRU5JTkcuLi4iKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBmIuKcpiB7UlVORVN9"
    "IOKcpiIpCgogICAgICAgICMgTG9hZCBib290c3RyYXAgbG9nCiAgICAgICAgYm9vdF9sb2cgPSBTQ1JJUFRfRElSIC8gImxvZ3Mi"
    "IC8gImJvb3RzdHJhcF9sb2cudHh0IgogICAgICAgIGlmIGJvb3RfbG9nLmV4aXN0cygpOgogICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICBtc2dzID0gYm9vdF9sb2cucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpLnNwbGl0bGluZXMoKQogICAgICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nX21hbnkobXNncykKICAgICAgICAgICAgICAgIGJvb3RfbG9nLnVubGluaygpICAj"
    "IGNvbnN1bWVkCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgSGFy"
    "ZHdhcmUgZGV0ZWN0aW9uIG1lc3NhZ2VzCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nX21hbnkoc2VsZi5faHdfcGFuZWwuZ2V0"
    "X2RpYWdub3N0aWNzKCkpCgogICAgICAgICMgRGVwIGNoZWNrCiAgICAgICAgZGVwX21zZ3MsIGNyaXRpY2FsID0gRGVwZW5kZW5j"
    "eUNoZWNrZXIuY2hlY2soKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZ19tYW55KGRlcF9tc2dzKQoKICAgICAgICAjIExvYWQg"
    "cGFzdCBzdGF0ZQogICAgICAgIGxhc3Rfc3RhdGUgPSBzZWxmLl9zdGF0ZS5nZXQoInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24i"
    "LCIiKQogICAgICAgIGlmIGxhc3Rfc3RhdGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAg"
    "IGYiW1NUQVJUVVBdIExhc3Qgc2h1dGRvd24gc3RhdGU6IHtsYXN0X3N0YXRlfSIsICJJTkZPIgogICAgICAgICAgICApCgogICAg"
    "ICAgICMgQmVnaW4gbW9kZWwgbG9hZAogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICBVSV9B"
    "V0FLRU5JTkdfTElORSkKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgZiJTdW1tb25pbmcg"
    "e0RFQ0tfTkFNRX0ncyBwcmVzZW5jZS4uLiIpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiTE9BRElORyIpCgogICAgICAgIHNl"
    "bGYuX2xvYWRlciA9IE1vZGVsTG9hZGVyV29ya2VyKHNlbGYuX2FkYXB0b3IpCiAgICAgICAgc2VsZi5fbG9hZGVyLm1lc3NhZ2Uu"
    "Y29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIG06IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBtKSkKICAgICAgICBzZWxm"
    "Ll9sb2FkZXIuZXJyb3IuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2FwcGVuZF9jaGF0KCJFUlJPUiIsIGUp"
    "KQogICAgICAgIHNlbGYuX2xvYWRlci5sb2FkX2NvbXBsZXRlLmNvbm5lY3Qoc2VsZi5fb25fbG9hZF9jb21wbGV0ZSkKICAgICAg"
    "ICBzZWxmLl9sb2FkZXIuZmluaXNoZWQuY29ubmVjdChzZWxmLl9sb2FkZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgc2VsZi5fYWN0"
    "aXZlX3RocmVhZHMuYXBwZW5kKHNlbGYuX2xvYWRlcikKICAgICAgICBzZWxmLl9sb2FkZXIuc3RhcnQoKQoKICAgIGRlZiBfb25f"
    "bG9hZF9jb21wbGV0ZShzZWxmLCBzdWNjZXNzOiBib29sKSAtPiBOb25lOgogICAgICAgIGlmIHN1Y2Nlc3M6CiAgICAgICAgICAg"
    "IHNlbGYuX21vZGVsX2xvYWRlZCA9IFRydWUKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiSURMRSIpCiAgICAgICAgICAg"
    "IHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChU"
    "cnVlKQogICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRGb2N1cygpCgogICAgICAgICAgICAjIE1lYXN1cmUgVlJBTSBi"
    "YXNlbGluZSBhZnRlciBtb2RlbCBsb2FkCiAgICAgICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAgICAgICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoNTAwMCwgc2VsZi5fbWVhc3VyZV92cmFtX2Jh"
    "c2VsaW5lKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBwYXNzCgogICAgICAg"
    "ICAgICAjIFZhbXBpcmUgc3RhdGUgZ3JlZXRpbmcKICAgICAgICAgICAgaWYgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAgICAgICAg"
    "ICAgICBzdGF0ZSA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgICAgICAgICAgICAgIHZhbXBfZ3JlZXRpbmdzID0gX3N0YXRlX2dy"
    "ZWV0aW5nc19tYXAoKQogICAgICAgICAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoCiAgICAgICAgICAgICAgICAgICAgIlNZU1RF"
    "TSIsCiAgICAgICAgICAgICAgICAgICAgdmFtcF9ncmVldGluZ3MuZ2V0KHN0YXRlLCBmIntERUNLX05BTUV9IGlzIG9ubGluZS4i"
    "KQogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAjIOKUgOKUgCBXYWtlLXVwIGNvbnRleHQgaW5qZWN0aW9uIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgICAgICAjIElmIHRoZXJlJ3MgYSBwcmV2aW91cyBzaHV0ZG93biByZWNvcmRlZCwgaW5qZWN0IGNv"
    "bnRleHQKICAgICAgICAgICAgIyBzbyBNb3JnYW5uYSBjYW4gZ3JlZXQgd2l0aCBhd2FyZW5lc3Mgb2YgaG93IGxvbmcgc2hlIHNs"
    "ZXB0CiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDgwMCwgc2VsZi5fc2VuZF93YWtldXBfcHJvbXB0KQogICAgICAgIGVs"
    "c2U6CiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkVSUk9SIikKICAgICAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNl"
    "KCJwYW5pY2tlZCIpCgogICAgZGVmIF9mb3JtYXRfZWxhcHNlZChzZWxmLCBzZWNvbmRzOiBmbG9hdCkgLT4gc3RyOgogICAgICAg"
    "ICIiIkZvcm1hdCBlbGFwc2VkIHNlY29uZHMgYXMgaHVtYW4tcmVhZGFibGUgZHVyYXRpb24uIiIiCiAgICAgICAgaWYgc2Vjb25k"
    "cyA8IDYwOgogICAgICAgICAgICByZXR1cm4gZiJ7aW50KHNlY29uZHMpfSBzZWNvbmR7J3MnIGlmIHNlY29uZHMgIT0gMSBlbHNl"
    "ICcnfSIKICAgICAgICBlbGlmIHNlY29uZHMgPCAzNjAwOgogICAgICAgICAgICBtID0gaW50KHNlY29uZHMgLy8gNjApCiAgICAg"
    "ICAgICAgIHMgPSBpbnQoc2Vjb25kcyAlIDYwKQogICAgICAgICAgICByZXR1cm4gZiJ7bX0gbWludXRleydzJyBpZiBtICE9IDEg"
    "ZWxzZSAnJ30iICsgKGYiIHtzfXMiIGlmIHMgZWxzZSAiIikKICAgICAgICBlbGlmIHNlY29uZHMgPCA4NjQwMDoKICAgICAgICAg"
    "ICAgaCA9IGludChzZWNvbmRzIC8vIDM2MDApCiAgICAgICAgICAgIG0gPSBpbnQoKHNlY29uZHMgJSAzNjAwKSAvLyA2MCkKICAg"
    "ICAgICAgICAgcmV0dXJuIGYie2h9IGhvdXJ7J3MnIGlmIGggIT0gMSBlbHNlICcnfSIgKyAoZiIge219bSIgaWYgbSBlbHNlICIi"
    "KQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGQgPSBpbnQoc2Vjb25kcyAvLyA4NjQwMCkKICAgICAgICAgICAgaCA9IGludCgo"
    "c2Vjb25kcyAlIDg2NDAwKSAvLyAzNjAwKQogICAgICAgICAgICByZXR1cm4gZiJ7ZH0gZGF5eydzJyBpZiBkICE9IDEgZWxzZSAn"
    "J30iICsgKGYiIHtofWgiIGlmIGggZWxzZSAiIikKCiAgICBkZWYgX3NlbmRfd2FrZXVwX3Byb21wdChzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgICIiIlNlbmQgaGlkZGVuIHdha2UtdXAgY29udGV4dCB0byBBSSBhZnRlciBtb2RlbCBsb2Fkcy4iIiIKICAgICAgICBs"
    "YXN0X3NodXRkb3duID0gc2VsZi5fc3RhdGUuZ2V0KCJsYXN0X3NodXRkb3duIikKICAgICAgICBpZiBub3QgbGFzdF9zaHV0ZG93"
    "bjoKICAgICAgICAgICAgcmV0dXJuICAjIEZpcnN0IGV2ZXIgcnVuIOKAlCBubyBzaHV0ZG93biB0byB3YWtlIHVwIGZyb20KCiAg"
    "ICAgICAgIyBDYWxjdWxhdGUgZWxhcHNlZCB0aW1lCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzaHV0ZG93bl9kdCA9IGRhdGV0"
    "aW1lLmZyb21pc29mb3JtYXQobGFzdF9zaHV0ZG93bikKICAgICAgICAgICAgbm93X2R0ID0gZGF0ZXRpbWUubm93KCkKICAgICAg"
    "ICAgICAgIyBNYWtlIGJvdGggbmFpdmUgZm9yIGNvbXBhcmlzb24KICAgICAgICAgICAgaWYgc2h1dGRvd25fZHQudHppbmZvIGlz"
    "IG5vdCBOb25lOgogICAgICAgICAgICAgICAgc2h1dGRvd25fZHQgPSBzaHV0ZG93bl9kdC5hc3RpbWV6b25lKCkucmVwbGFjZSh0"
    "emluZm89Tm9uZSkKICAgICAgICAgICAgZWxhcHNlZF9zZWMgPSAobm93X2R0IC0gc2h1dGRvd25fZHQpLnRvdGFsX3NlY29uZHMo"
    "KQogICAgICAgICAgICBlbGFwc2VkX3N0ciA9IHNlbGYuX2Zvcm1hdF9lbGFwc2VkKGVsYXBzZWRfc2VjKQogICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgICAgIGVsYXBzZWRfc3RyID0gImFuIHVua25vd24gZHVyYXRpb24iCgogICAgICAgICMgR2V0"
    "IHN0b3JlZCBmYXJld2VsbCBhbmQgbGFzdCBjb250ZXh0CiAgICAgICAgZmFyZXdlbGwgICAgID0gc2VsZi5fc3RhdGUuZ2V0KCJs"
    "YXN0X2ZhcmV3ZWxsIiwgIiIpCiAgICAgICAgbGFzdF9jb250ZXh0ID0gc2VsZi5fc3RhdGUuZ2V0KCJsYXN0X3NodXRkb3duX2Nv"
    "bnRleHQiLCBbXSkKCiAgICAgICAgIyBCdWlsZCB3YWtlLXVwIHByb21wdAogICAgICAgIGNvbnRleHRfYmxvY2sgPSAiIgogICAg"
    "ICAgIGlmIGxhc3RfY29udGV4dDoKICAgICAgICAgICAgY29udGV4dF9ibG9jayA9ICJcblxuVGhlIGZpbmFsIGV4Y2hhbmdlIGJl"
    "Zm9yZSBkZWFjdGl2YXRpb246XG4iCiAgICAgICAgICAgIGZvciBpdGVtIGluIGxhc3RfY29udGV4dDoKICAgICAgICAgICAgICAg"
    "IHNwZWFrZXIgPSBpdGVtLmdldCgicm9sZSIsICJ1bmtub3duIikudXBwZXIoKQogICAgICAgICAgICAgICAgdGV4dCAgICA9IGl0"
    "ZW0uZ2V0KCJjb250ZW50IiwgIiIpWzoyMDBdCiAgICAgICAgICAgICAgICBjb250ZXh0X2Jsb2NrICs9IGYie3NwZWFrZXJ9OiB7"
    "dGV4dH1cbiIKCiAgICAgICAgZmFyZXdlbGxfYmxvY2sgPSAiIgogICAgICAgIGlmIGZhcmV3ZWxsOgogICAgICAgICAgICBmYXJl"
    "d2VsbF9ibG9jayA9IGYiXG5cbllvdXIgZmluYWwgd29yZHMgYmVmb3JlIGRlYWN0aXZhdGlvbiB3ZXJlOlxuXCJ7ZmFyZXdlbGx9"
    "XCIiCgogICAgICAgIHdha2V1cF9wcm9tcHQgPSAoCiAgICAgICAgICAgIGYiWW91IGhhdmUganVzdCBiZWVuIHJlYWN0aXZhdGVk"
    "IGFmdGVyIHtlbGFwc2VkX3N0cn0gb2YgZG9ybWFuY3kuIgogICAgICAgICAgICBmIntmYXJld2VsbF9ibG9ja30iCiAgICAgICAg"
    "ICAgIGYie2NvbnRleHRfYmxvY2t9IgogICAgICAgICAgICBmIlxuR3JlZXQgeW91ciBNYXN0ZXIgd2l0aCBhd2FyZW5lc3Mgb2Yg"
    "aG93IGxvbmcgeW91IGhhdmUgYmVlbiBhYnNlbnQgIgogICAgICAgICAgICBmImFuZCB3aGF0ZXZlciB5b3UgbGFzdCBzYWlkIHRv"
    "IHRoZW0uIEJlIGJyaWVmIGJ1dCBjaGFyYWN0ZXJmdWwuIgogICAgICAgICkKCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAog"
    "ICAgICAgICAgICBmIltXQUtFVVBdIEluamVjdGluZyB3YWtlLXVwIGNvbnRleHQgKHtlbGFwc2VkX3N0cn0gZWxhcHNlZCkiLCAi"
    "SU5GTyIKICAgICAgICApCgogICAgICAgIHRyeToKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0"
    "b3J5KCkKICAgICAgICAgICAgaGlzdG9yeS5hcHBlbmQoeyJyb2xlIjogInVzZXIiLCAiY29udGVudCI6IHdha2V1cF9wcm9tcHR9"
    "KQogICAgICAgICAgICB3b3JrZXIgPSBTdHJlYW1pbmdXb3JrZXIoCiAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLCBTWVNU"
    "RU1fUFJPTVBUX0JBU0UsIGhpc3RvcnksIG1heF90b2tlbnM9MjU2CiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fd2Fr"
    "ZXVwX3dvcmtlciA9IHdvcmtlcgogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUKICAgICAgICAgICAgd29ya2Vy"
    "LnRva2VuX3JlYWR5LmNvbm5lY3Qoc2VsZi5fb25fdG9rZW4pCiAgICAgICAgICAgIHdvcmtlci5yZXNwb25zZV9kb25lLmNvbm5l"
    "Y3Qoc2VsZi5fb25fcmVzcG9uc2VfZG9uZSkKICAgICAgICAgICAgd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3QoCiAgICAg"
    "ICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fZGlhZ190YWIubG9nKGYiW1dBS0VVUF1bRVJST1JdIHtlfSIsICJXQVJOIikKICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICB3b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVjdChzZWxmLl9zZXRfc3RhdHVzKQogICAg"
    "ICAgICAgICB3b3JrZXIuZmluaXNoZWQuY29ubmVjdCh3b3JrZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgICAgIHdvcmtlci5zdGFy"
    "dCgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAg"
    "ICAgICAgICBmIltXQUtFVVBdW1dBUk5dIFdha2UtdXAgcHJvbXB0IHNraXBwZWQgZHVlIHRvIGVycm9yOiB7ZX0iLAogICAgICAg"
    "ICAgICAgICAgIldBUk4iCiAgICAgICAgICAgICkKCiAgICBkZWYgX3N0YXJ0dXBfZ29vZ2xlX2F1dGgoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICAiIiIKICAgICAgICBGb3JjZSBHb29nbGUgT0F1dGggb25jZSBhdCBzdGFydHVwIGFmdGVyIHRoZSBldmVudCBsb29w"
    "IGlzIHJ1bm5pbmcuCiAgICAgICAgSWYgdG9rZW4gaXMgbWlzc2luZy9pbnZhbGlkLCB0aGUgYnJvd3NlciBPQXV0aCBmbG93IG9w"
    "ZW5zIG5hdHVyYWxseS4KICAgICAgICAiIiIKICAgICAgICBpZiBub3QgR09PR0xFX09LIG9yIG5vdCBHT09HTEVfQVBJX09LOgog"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAiW0dPT0dMRV1bU1RBUlRVUF1bV0FSTl0gR29v"
    "Z2xlIGF1dGggc2tpcHBlZCBiZWNhdXNlIGRlcGVuZGVuY2llcyBhcmUgdW5hdmFpbGFibGUuIiwKICAgICAgICAgICAgICAgICJX"
    "QVJOIgogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIEdPT0dMRV9JTVBPUlRfRVJST1I6CiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtTVEFSVFVQXVtXQVJOXSB7R09PR0xFX0lNUE9SVF9FUlJPUn0iLCAiV0FSTiIpCiAg"
    "ICAgICAgICAgIHJldHVybgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIG5vdCBzZWxmLl9nY2FsIG9yIG5vdCBzZWxmLl9n"
    "ZHJpdmU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgIltHT09HTEVdW1NU"
    "QVJUVVBdW1dBUk5dIEdvb2dsZSBhdXRoIHNraXBwZWQgYmVjYXVzZSBzZXJ2aWNlIG9iamVjdHMgYXJlIHVuYXZhaWxhYmxlLiIs"
    "CiAgICAgICAgICAgICAgICAgICAgIldBUk4iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICByZXR1cm4KCiAgICAg"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gQmVnaW5uaW5nIHByb2FjdGl2ZSBHb29nbGUgYXV0"
    "aCBjaGVjay4iLCAiSU5GTyIpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0dPT0dM"
    "RV1bU1RBUlRVUF0gY3JlZGVudGlhbHM9e3NlbGYuX2djYWwuY3JlZGVudGlhbHNfcGF0aH0iLAogICAgICAgICAgICAgICAgIklO"
    "Rk8iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbR09PR0xF"
    "XVtTVEFSVFVQXSB0b2tlbj17c2VsZi5fZ2NhbC50b2tlbl9wYXRofSIsCiAgICAgICAgICAgICAgICAiSU5GTyIKICAgICAgICAg"
    "ICAgKQoKICAgICAgICAgICAgc2VsZi5fZ2NhbC5fYnVpbGRfc2VydmljZSgpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygiW0dPT0dMRV1bU1RBUlRVUF0gQ2FsZW5kYXIgYXV0aCByZWFkeS4iLCAiT0siKQoKICAgICAgICAgICAgc2VsZi5fZ2RyaXZl"
    "LmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gRHJpdmUv"
    "RG9jcyBhdXRoIHJlYWR5LiIsICJPSyIpCiAgICAgICAgICAgIHNlbGYuX2dvb2dsZV9hdXRoX3JlYWR5ID0gVHJ1ZQoKICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBTY2hlZHVsaW5nIGluaXRpYWwgUmVjb3JkcyByZWZy"
    "ZXNoIGFmdGVyIGF1dGguIiwgIklORk8iKQogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgzMDAsIHNlbGYuX3JlZnJlc2hf"
    "cmVjb3Jkc19kb2NzKQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBQb3N0LWF1dGgg"
    "dGFzayByZWZyZXNoIHRyaWdnZXJlZC4iLCAiSU5GTyIpCiAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9w"
    "YW5lbCgpCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIEluaXRpYWwgY2FsZW5kYXIg"
    "aW5ib3VuZCBzeW5jIHRyaWdnZXJlZCBhZnRlciBhdXRoLiIsICJJTkZPIikKICAgICAgICAgICAgaW1wb3J0ZWRfY291bnQgPSBz"
    "ZWxmLl9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoZm9yY2Vfb25jZT1UcnVlKQogICAgICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NUQVJUVVBdIEdvb2dsZSBDYWxlbmRhciB0YXNrIGltcG9y"
    "dCBjb3VudDoge2ludChpbXBvcnRlZF9jb3VudCl9LiIsCiAgICAgICAgICAgICAgICAiSU5GTyIKICAgICAgICAgICAgKQogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVdW1NUQVJU"
    "VVBdW0VSUk9SXSB7ZXh9IiwgIkVSUk9SIikKCgogICAgZGVmIF9yZWZyZXNoX3JlY29yZHNfZG9jcyhzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHNlbGYuX3JlY29yZHNfY3VycmVudF9mb2xkZXJfaWQgPSAicm9vdCIKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYi5z"
    "dGF0dXNfbGFiZWwuc2V0VGV4dCgiTG9hZGluZyBHb29nbGUgRHJpdmUgcmVjb3Jkcy4uLiIpCiAgICAgICAgc2VsZi5fcmVjb3Jk"
    "c190YWIucGF0aF9sYWJlbC5zZXRUZXh0KCJQYXRoOiBNeSBEcml2ZSIpCiAgICAgICAgZmlsZXMgPSBzZWxmLl9nZHJpdmUubGlz"
    "dF9mb2xkZXJfaXRlbXMoZm9sZGVyX2lkPXNlbGYuX3JlY29yZHNfY3VycmVudF9mb2xkZXJfaWQsIHBhZ2Vfc2l6ZT0yMDApCiAg"
    "ICAgICAgc2VsZi5fcmVjb3Jkc19jYWNoZSA9IGZpbGVzCiAgICAgICAgc2VsZi5fcmVjb3Jkc19pbml0aWFsaXplZCA9IFRydWUK"
    "ICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYi5zZXRfaXRlbXMoZmlsZXMsIHBhdGhfdGV4dD0iTXkgRHJpdmUiKQoKICAgIGRlZiBf"
    "b25fZ29vZ2xlX2luYm91bmRfdGltZXJfdGljayhzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9nb29nbGVfYXV0"
    "aF9yZWFkeToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gQ2FsZW5kYXIgdGljayBmaXJl"
    "ZCDigJQgYXV0aCBub3QgcmVhZHkgeWV0LCBza2lwcGluZy4iLCAiV0FSTiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIGluYm91bmQgc3luYyB0aWNrIOKAlCBzdGFydGluZyBi"
    "YWNrZ3JvdW5kIHBvbGwuIiwgIklORk8iKQogICAgICAgIGltcG9ydCB0aHJlYWRpbmcgYXMgX3RocmVhZGluZwogICAgICAgIGRl"
    "ZiBfY2FsX2JnKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJlc3VsdCA9IHNlbGYuX3BvbGxfZ29vZ2xlX2Nh"
    "bGVuZGFyX2luYm91bmRfc3luYygpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtUSU1FUl0g"
    "Q2FsZW5kYXIgcG9sbCBjb21wbGV0ZSDigJQge3Jlc3VsdH0gaXRlbXMgcHJvY2Vzc2VkLiIsICJPSyIpCiAgICAgICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtUSU1FUl1b"
    "RVJST1JdIENhbGVuZGFyIHBvbGwgZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIikKICAgICAgICBfdGhyZWFkaW5nLlRocmVhZCh0YXJn"
    "ZXQ9X2NhbF9iZywgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgX29uX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXJf"
    "dGljayhzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9nb29nbGVfYXV0aF9yZWFkeToKICAgICAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gRHJpdmUgdGljayBmaXJlZCDigJQgYXV0aCBub3QgcmVhZHkgeWV0LCBz"
    "a2lwcGluZy4iLCAiV0FSTiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1b"
    "VElNRVJdIERyaXZlIHJlY29yZHMgcmVmcmVzaCB0aWNrIOKAlCBzdGFydGluZyBiYWNrZ3JvdW5kIHJlZnJlc2guIiwgIklORk8i"
    "KQogICAgICAgIGltcG9ydCB0aHJlYWRpbmcgYXMgX3RocmVhZGluZwogICAgICAgIGRlZiBfYmcoKToKICAgICAgICAgICAgdHJ5"
    "OgogICAgICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF9yZWNvcmRzX2RvY3MoKQogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gRHJpdmUgcmVjb3JkcyByZWZyZXNoIGNvbXBsZXRlLiIsICJPSyIpCiAgICAgICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAg"
    "ICAgICAgZiJbR09PR0xFXVtEUklWRV1bU1lOQ11bRVJST1JdIHJlY29yZHMgcmVmcmVzaCBmYWlsZWQ6IHtleH0iLCAiRVJST1Ii"
    "CiAgICAgICAgICAgICAgICApCiAgICAgICAgX3RocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9iZywgZGFlbW9uPVRydWUpLnN0YXJ0"
    "KCkKCiAgICBkZWYgX2ZpbHRlcmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeShzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgIHRhc2tz"
    "ID0gc2VsZi5fdGFza3MubG9hZF9hbGwoKQogICAgICAgIG5vdyA9IG5vd19mb3JfY29tcGFyZSgpCiAgICAgICAgaWYgc2VsZi5f"
    "dGFza19kYXRlX2ZpbHRlciA9PSAid2VlayI6CiAgICAgICAgICAgIGVuZCA9IG5vdyArIHRpbWVkZWx0YShkYXlzPTcpCiAgICAg"
    "ICAgZWxpZiBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID09ICJtb250aCI6CiAgICAgICAgICAgIGVuZCA9IG5vdyArIHRpbWVkZWx0"
    "YShkYXlzPTMxKQogICAgICAgIGVsaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAieWVhciI6CiAgICAgICAgICAgIGVuZCA9"
    "IG5vdyArIHRpbWVkZWx0YShkYXlzPTM2NikKICAgICAgICBlbHNlOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEo"
    "ZGF5cz05MikKCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltUQVNLU11bRklMVEVSXSBzdGFydCBm"
    "aWx0ZXI9e3NlbGYuX3Rhc2tfZGF0ZV9maWx0ZXJ9IHNob3dfY29tcGxldGVkPXtzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkfSB0"
    "b3RhbD17bGVuKHRhc2tzKX0iLAogICAgICAgICAgICAiSU5GTyIsCiAgICAgICAgKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZyhmIltUQVNLU11bRklMVEVSXSBub3c9e25vdy5pc29mb3JtYXQodGltZXNwZWM9J3NlY29uZHMnKX0iLCAiREVCVUciKQogICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bRklMVEVSXSBob3Jpem9uX2VuZD17ZW5kLmlzb2Zvcm1hdCh0aW1lc3Bl"
    "Yz0nc2Vjb25kcycpfSIsICJERUJVRyIpCgogICAgICAgIGZpbHRlcmVkOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBza2lwcGVk"
    "X2ludmFsaWRfZHVlID0gMAogICAgICAgIGZvciB0YXNrIGluIHRhc2tzOgogICAgICAgICAgICBzdGF0dXMgPSAodGFzay5nZXQo"
    "InN0YXR1cyIpIG9yICJwZW5kaW5nIikubG93ZXIoKQogICAgICAgICAgICBpZiBub3Qgc2VsZi5fdGFza19zaG93X2NvbXBsZXRl"
    "ZCBhbmQgc3RhdHVzIGluIHsiY29tcGxldGVkIiwgImNhbmNlbGxlZCJ9OgogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAg"
    "ICAgICAgIGR1ZV9yYXcgPSB0YXNrLmdldCgiZHVlX2F0Iikgb3IgdGFzay5nZXQoImR1ZSIpCiAgICAgICAgICAgIGR1ZV9kdCA9"
    "IHBhcnNlX2lzb19mb3JfY29tcGFyZShkdWVfcmF3LCBjb250ZXh0PSJ0YXNrc190YWJfZHVlX2ZpbHRlciIpCiAgICAgICAgICAg"
    "IGlmIGR1ZV9yYXcgYW5kIGR1ZV9kdCBpcyBOb25lOgogICAgICAgICAgICAgICAgc2tpcHBlZF9pbnZhbGlkX2R1ZSArPSAxCiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVEFTS1NdW0ZJTFRFUl1bV0FS"
    "Tl0gc2tpcHBpbmcgaW52YWxpZCBkdWUgZGF0ZXRpbWUgdGFza19pZD17dGFzay5nZXQoJ2lkJywnPycpfSBkdWVfcmF3PXtkdWVf"
    "cmF3IXJ9IiwKICAgICAgICAgICAgICAgICAgICAiV0FSTiIsCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBjb250"
    "aW51ZQoKICAgICAgICAgICAgaWYgZHVlX2R0IGlzIE5vbmU6CiAgICAgICAgICAgICAgICBmaWx0ZXJlZC5hcHBlbmQodGFzaykK"
    "ICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIG5vdyA8PSBkdWVfZHQgPD0gZW5kIG9yIHN0YXR1cyBpbiB7"
    "ImNvbXBsZXRlZCIsICJjYW5jZWxsZWQifToKICAgICAgICAgICAgICAgIGZpbHRlcmVkLmFwcGVuZCh0YXNrKQoKICAgICAgICBm"
    "aWx0ZXJlZC5zb3J0KGtleT1fdGFza19kdWVfc29ydF9rZXkpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAg"
    "ICBmIltUQVNLU11bRklMVEVSXSBkb25lIGJlZm9yZT17bGVuKHRhc2tzKX0gYWZ0ZXI9e2xlbihmaWx0ZXJlZCl9IHNraXBwZWRf"
    "aW52YWxpZF9kdWU9e3NraXBwZWRfaW52YWxpZF9kdWV9IiwKICAgICAgICAgICAgIklORk8iLAogICAgICAgICkKICAgICAgICBy"
    "ZXR1cm4gZmlsdGVyZWQKCiAgICBkZWYgX2dvb2dsZV9ldmVudF9kdWVfZGF0ZXRpbWUoc2VsZiwgZXZlbnQ6IGRpY3QpOgogICAg"
    "ICAgIHN0YXJ0ID0gKGV2ZW50IG9yIHt9KS5nZXQoInN0YXJ0Iikgb3Ige30KICAgICAgICBkYXRlX3RpbWUgPSBzdGFydC5nZXQo"
    "ImRhdGVUaW1lIikKICAgICAgICBpZiBkYXRlX3RpbWU6CiAgICAgICAgICAgIHBhcnNlZCA9IHBhcnNlX2lzb19mb3JfY29tcGFy"
    "ZShkYXRlX3RpbWUsIGNvbnRleHQ9Imdvb2dsZV9ldmVudF9kYXRlVGltZSIpCiAgICAgICAgICAgIGlmIHBhcnNlZDoKICAgICAg"
    "ICAgICAgICAgIHJldHVybiBwYXJzZWQKICAgICAgICBkYXRlX29ubHkgPSBzdGFydC5nZXQoImRhdGUiKQogICAgICAgIGlmIGRh"
    "dGVfb25seToKICAgICAgICAgICAgcGFyc2VkID0gcGFyc2VfaXNvX2Zvcl9jb21wYXJlKGYie2RhdGVfb25seX1UMDk6MDA6MDAi"
    "LCBjb250ZXh0PSJnb29nbGVfZXZlbnRfZGF0ZSIpCiAgICAgICAgICAgIGlmIHBhcnNlZDoKICAgICAgICAgICAgICAgIHJldHVy"
    "biBwYXJzZWQKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBfcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIE5vbmU6CiAgICAgICAgICAgIHJl"
    "dHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLnJlZnJlc2goKQogICAgICAgICAgICB2aXNpYmxl"
    "X2NvdW50ID0gbGVuKHNlbGYuX2ZpbHRlcmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeSgpKQogICAgICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coZiJbVEFTS1NdW1JFR0lTVFJZXSByZWZyZXNoIGNvdW50PXt2aXNpYmxlX2NvdW50fS4iLCAiSU5GTyIpCiAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXVtSRUdJU1RSWV1b"
    "RVJST1JdIHJlZnJlc2ggZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIikKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fdGFza3NfdGFiLnN0b3BfcmVmcmVzaF93b3JrZXIocmVhc29uPSJyZWdpc3RyeV9yZWZyZXNoX2V4Y2VwdGlvbiIpCiAgICAg"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgc3RvcF9leDoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAg"
    "ICAgICAgICAgICAgICAgICBmIltUQVNLU11bUkVHSVNUUlldW1dBUk5dIGZhaWxlZCB0byBzdG9wIHJlZnJlc2ggd29ya2VyIGNs"
    "ZWFubHk6IHtzdG9wX2V4fSIsCiAgICAgICAgICAgICAgICAgICAgIldBUk4iLAogICAgICAgICAgICAgICAgKQoKICAgIGRlZiBf"
    "b25fdGFza19maWx0ZXJfY2hhbmdlZChzZWxmLCBmaWx0ZXJfa2V5OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fdGFza19k"
    "YXRlX2ZpbHRlciA9IHN0cihmaWx0ZXJfa2V5IG9yICJuZXh0XzNfbW9udGhzIikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "ZiJbVEFTS1NdIFRhc2sgcmVnaXN0cnkgZGF0ZSBmaWx0ZXIgY2hhbmdlZCB0byB7c2VsZi5fdGFza19kYXRlX2ZpbHRlcn0uIiwg"
    "IklORk8iKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF90b2dnbGVfc2hvd19j"
    "b21wbGV0ZWRfdGFza3Moc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl90YXNrX3Nob3dfY29tcGxldGVkID0gbm90IHNlbGYu"
    "X3Rhc2tfc2hvd19jb21wbGV0ZWQKICAgICAgICBzZWxmLl90YXNrc190YWIuc2V0X3Nob3dfY29tcGxldGVkKHNlbGYuX3Rhc2tf"
    "c2hvd19jb21wbGV0ZWQpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX3NlbGVj"
    "dGVkX3Rhc2tfaWRzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9u"
    "ZSkgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuIFtdCiAgICAgICAgcmV0dXJuIHNlbGYuX3Rhc2tzX3RhYi5zZWxlY3RlZF90"
    "YXNrX2lkcygpCgogICAgZGVmIF9zZXRfdGFza19zdGF0dXMoc2VsZiwgdGFza19pZDogc3RyLCBzdGF0dXM6IHN0cikgLT4gT3B0"
    "aW9uYWxbZGljdF06CiAgICAgICAgaWYgc3RhdHVzID09ICJjb21wbGV0ZWQiOgogICAgICAgICAgICB1cGRhdGVkID0gc2VsZi5f"
    "dGFza3MuY29tcGxldGUodGFza19pZCkKICAgICAgICBlbGlmIHN0YXR1cyA9PSAiY2FuY2VsbGVkIjoKICAgICAgICAgICAgdXBk"
    "YXRlZCA9IHNlbGYuX3Rhc2tzLmNhbmNlbCh0YXNrX2lkKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHVwZGF0ZWQgPSBzZWxm"
    "Ll90YXNrcy51cGRhdGVfc3RhdHVzKHRhc2tfaWQsIHN0YXR1cykKCiAgICAgICAgaWYgbm90IHVwZGF0ZWQ6CiAgICAgICAgICAg"
    "IHJldHVybiBOb25lCgogICAgICAgIGdvb2dsZV9ldmVudF9pZCA9ICh1cGRhdGVkLmdldCgiZ29vZ2xlX2V2ZW50X2lkIikgb3Ig"
    "IiIpLnN0cmlwKCkKICAgICAgICBpZiBnb29nbGVfZXZlbnRfaWQ6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNl"
    "bGYuX2djYWwuZGVsZXRlX2V2ZW50X2Zvcl90YXNrKGdvb2dsZV9ldmVudF9pZCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlv"
    "biBhcyBleDoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltUQVNLU11b"
    "V0FSTl0gR29vZ2xlIGV2ZW50IGNsZWFudXAgZmFpbGVkIGZvciB0YXNrX2lkPXt0YXNrX2lkfToge2V4fSIsCiAgICAgICAgICAg"
    "ICAgICAgICAgIldBUk4iLAogICAgICAgICAgICAgICAgKQogICAgICAgIHJldHVybiB1cGRhdGVkCgogICAgZGVmIF9jb21wbGV0"
    "ZV9zZWxlY3RlZF90YXNrKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZG9uZSA9IDAKICAgICAgICBmb3IgdGFza19pZCBpbiBzZWxm"
    "Ll9zZWxlY3RlZF90YXNrX2lkcygpOgogICAgICAgICAgICBpZiBzZWxmLl9zZXRfdGFza19zdGF0dXModGFza19pZCwgImNvbXBs"
    "ZXRlZCIpOgogICAgICAgICAgICAgICAgZG9uZSArPSAxCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXSBDT01Q"
    "TEVURSBTRUxFQ1RFRCBhcHBsaWVkIHRvIHtkb25lfSB0YXNrKHMpLiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rh"
    "c2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfY2FuY2VsX3NlbGVjdGVkX3Rhc2soc2VsZikgLT4gTm9uZToKICAgICAgICBk"
    "b25lID0gMAogICAgICAgIGZvciB0YXNrX2lkIGluIHNlbGYuX3NlbGVjdGVkX3Rhc2tfaWRzKCk6CiAgICAgICAgICAgIGlmIHNl"
    "bGYuX3NldF90YXNrX3N0YXR1cyh0YXNrX2lkLCAiY2FuY2VsbGVkIik6CiAgICAgICAgICAgICAgICBkb25lICs9IDEKICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdIENBTkNFTCBTRUxFQ1RFRCBhcHBsaWVkIHRvIHtkb25lfSB0YXNrKHMpLiIs"
    "ICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfcHVyZ2VfY29tcGxl"
    "dGVkX3Rhc2tzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVtb3ZlZCA9IHNlbGYuX3Rhc2tzLmNsZWFyX2NvbXBsZXRlZCgpCiAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXSBQVVJHRSBDT01QTEVURUQgcmVtb3ZlZCB7cmVtb3ZlZH0gdGFzayhz"
    "KS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX3NldF90YXNr"
    "X2VkaXRvcl9zdGF0dXMoc2VsZiwgdGV4dDogc3RyLCBvazogYm9vbCA9IEZhbHNlKSAtPiBOb25lOgogICAgICAgIGlmIGdldGF0"
    "dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLnNldF9z"
    "dGF0dXModGV4dCwgb2s9b2spCgogICAgZGVmIF9vcGVuX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZShzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAg"
    "ICBub3dfbG9jYWwgPSBkYXRldGltZS5ub3coKQogICAgICAgIGVuZF9sb2NhbCA9IG5vd19sb2NhbCArIHRpbWVkZWx0YShtaW51"
    "dGVzPTMwKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9uYW1lLnNldFRleHQoIiIpCiAgICAgICAgc2VsZi5f"
    "dGFza3NfdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUuc2V0VGV4dChub3dfbG9jYWwuc3RyZnRpbWUoIiVZLSVtLSVkIikpCiAg"
    "ICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUuc2V0VGV4dChub3dfbG9jYWwuc3RyZnRpbWUoIiVI"
    "OiVNIikpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX2VuZF9kYXRlLnNldFRleHQoZW5kX2xvY2FsLnN0cmZ0"
    "aW1lKCIlWS0lbS0lZCIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9lbmRfdGltZS5zZXRUZXh0KGVuZF9s"
    "b2NhbC5zdHJmdGltZSgiJUg6JU0iKSkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3Jfbm90ZXMuc2V0UGxhaW5U"
    "ZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9sb2NhdGlvbi5zZXRUZXh0KCIiKQogICAgICAgIHNl"
    "bGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnNldFRleHQoIiIpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRh"
    "c2tfZWRpdG9yX2FsbF9kYXkuc2V0Q2hlY2tlZChGYWxzZSkKICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJD"
    "b25maWd1cmUgdGFzayBkZXRhaWxzLCB0aGVuIHNhdmUgdG8gR29vZ2xlIENhbGVuZGFyLiIsIG9rPUZhbHNlKQogICAgICAgIHNl"
    "bGYuX3Rhc2tzX3RhYi5vcGVuX2VkaXRvcigpCgogICAgZGVmIF9jbG9zZV90YXNrX2VkaXRvcl93b3Jrc3BhY2Uoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkgaXMgbm90IE5vbmU6CiAgICAgICAgICAg"
    "IHNlbGYuX3Rhc2tzX3RhYi5jbG9zZV9lZGl0b3IoKQoKICAgIGRlZiBfY2FuY2VsX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZShzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZSgpCgogICAgZGVmIF9wYXJzZV9lZGl0"
    "b3JfZGF0ZXRpbWUoc2VsZiwgZGF0ZV90ZXh0OiBzdHIsIHRpbWVfdGV4dDogc3RyLCBhbGxfZGF5OiBib29sLCBpc19lbmQ6IGJv"
    "b2wgPSBGYWxzZSk6CiAgICAgICAgZGF0ZV90ZXh0ID0gKGRhdGVfdGV4dCBvciAiIikuc3RyaXAoKQogICAgICAgIHRpbWVfdGV4"
    "dCA9ICh0aW1lX3RleHQgb3IgIiIpLnN0cmlwKCkKICAgICAgICBpZiBub3QgZGF0ZV90ZXh0OgogICAgICAgICAgICByZXR1cm4g"
    "Tm9uZQogICAgICAgIGlmIGFsbF9kYXk6CiAgICAgICAgICAgIGhvdXIgPSAyMyBpZiBpc19lbmQgZWxzZSAwCiAgICAgICAgICAg"
    "IG1pbnV0ZSA9IDU5IGlmIGlzX2VuZCBlbHNlIDAKICAgICAgICAgICAgcGFyc2VkID0gZGF0ZXRpbWUuc3RycHRpbWUoZiJ7ZGF0"
    "ZV90ZXh0fSB7aG91cjowMmR9OnttaW51dGU6MDJkfSIsICIlWS0lbS0lZCAlSDolTSIpCiAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgcGFyc2VkID0gZGF0ZXRpbWUuc3RycHRpbWUoZiJ7ZGF0ZV90ZXh0fSB7dGltZV90ZXh0fSIsICIlWS0lbS0lZCAlSDolTSIp"
    "CiAgICAgICAgbm9ybWFsaXplZCA9IG5vcm1hbGl6ZV9kYXRldGltZV9mb3JfY29tcGFyZShwYXJzZWQsIGNvbnRleHQ9InRhc2tf"
    "ZWRpdG9yX3BhcnNlX2R0IikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW1RBU0tTXVtFRElUT1Jd"
    "IHBhcnNlZCBkYXRldGltZSBpc19lbmQ9e2lzX2VuZH0sIGFsbF9kYXk9e2FsbF9kYXl9OiAiCiAgICAgICAgICAgIGYiaW5wdXQ9"
    "J3tkYXRlX3RleHR9IHt0aW1lX3RleHR9JyAtPiB7bm9ybWFsaXplZC5pc29mb3JtYXQoKSBpZiBub3JtYWxpemVkIGVsc2UgJ05v"
    "bmUnfSIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAgICAgICAgcmV0dXJuIG5vcm1hbGl6ZWQKCiAgICBkZWYgX3Nh"
    "dmVfdGFza19lZGl0b3JfZ29vZ2xlX2ZpcnN0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdGFiID0gZ2V0YXR0cihzZWxmLCAiX3Rh"
    "c2tzX3RhYiIsIE5vbmUpCiAgICAgICAgaWYgdGFiIGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRpdGxlID0g"
    "dGFiLnRhc2tfZWRpdG9yX25hbWUudGV4dCgpLnN0cmlwKCkKICAgICAgICBhbGxfZGF5ID0gdGFiLnRhc2tfZWRpdG9yX2FsbF9k"
    "YXkuaXNDaGVja2VkKCkKICAgICAgICBzdGFydF9kYXRlID0gdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUudGV4dCgpLnN0cmlw"
    "KCkKICAgICAgICBzdGFydF90aW1lID0gdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUudGV4dCgpLnN0cmlwKCkKICAgICAgICBl"
    "bmRfZGF0ZSA9IHRhYi50YXNrX2VkaXRvcl9lbmRfZGF0ZS50ZXh0KCkuc3RyaXAoKQogICAgICAgIGVuZF90aW1lID0gdGFiLnRh"
    "c2tfZWRpdG9yX2VuZF90aW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgbm90ZXMgPSB0YWIudGFza19lZGl0b3Jfbm90ZXMudG9Q"
    "bGFpblRleHQoKS5zdHJpcCgpCiAgICAgICAgbG9jYXRpb24gPSB0YWIudGFza19lZGl0b3JfbG9jYXRpb24udGV4dCgpLnN0cmlw"
    "KCkKICAgICAgICByZWN1cnJlbmNlID0gdGFiLnRhc2tfZWRpdG9yX3JlY3VycmVuY2UudGV4dCgpLnN0cmlwKCkKCiAgICAgICAg"
    "aWYgbm90IHRpdGxlOgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJUYXNrIE5hbWUgaXMgcmVxdWly"
    "ZWQuIiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIG5vdCBzdGFydF9kYXRlIG9yIG5vdCBlbmRfZGF0"
    "ZSBvciAobm90IGFsbF9kYXkgYW5kIChub3Qgc3RhcnRfdGltZSBvciBub3QgZW5kX3RpbWUpKToKICAgICAgICAgICAgc2VsZi5f"
    "c2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiU3RhcnQvRW5kIGRhdGUgYW5kIHRpbWUgYXJlIHJlcXVpcmVkLiIsIG9rPUZhbHNlKQog"
    "ICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHN0YXJ0X2R0ID0gc2VsZi5fcGFyc2VfZWRpdG9yX2Rh"
    "dGV0aW1lKHN0YXJ0X2RhdGUsIHN0YXJ0X3RpbWUsIGFsbF9kYXksIGlzX2VuZD1GYWxzZSkKICAgICAgICAgICAgZW5kX2R0ID0g"
    "c2VsZi5fcGFyc2VfZWRpdG9yX2RhdGV0aW1lKGVuZF9kYXRlLCBlbmRfdGltZSwgYWxsX2RheSwgaXNfZW5kPVRydWUpCiAgICAg"
    "ICAgICAgIGlmIG5vdCBzdGFydF9kdCBvciBub3QgZW5kX2R0OgogICAgICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiZGF0"
    "ZXRpbWUgcGFyc2UgZmFpbGVkIikKICAgICAgICAgICAgaWYgZW5kX2R0IDwgc3RhcnRfZHQ6CiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJFbmQgZGF0ZXRpbWUgbXVzdCBiZSBhZnRlciBzdGFydCBkYXRldGltZS4iLCBvaz1G"
    "YWxzZSkKICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHNlbGYuX3Nl"
    "dF90YXNrX2VkaXRvcl9zdGF0dXMoIkludmFsaWQgZGF0ZS90aW1lIGZvcm1hdC4gVXNlIFlZWVktTU0tREQgYW5kIEhIOk1NLiIs"
    "IG9rPUZhbHNlKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHpfbmFtZSA9IHNlbGYuX2djYWwuX2dldF9nb29nbGVfZXZl"
    "bnRfdGltZXpvbmUoKQogICAgICAgIHBheWxvYWQgPSB7InN1bW1hcnkiOiB0aXRsZX0KICAgICAgICBpZiBhbGxfZGF5OgogICAg"
    "ICAgICAgICBwYXlsb2FkWyJzdGFydCJdID0geyJkYXRlIjogc3RhcnRfZHQuZGF0ZSgpLmlzb2Zvcm1hdCgpfQogICAgICAgICAg"
    "ICBwYXlsb2FkWyJlbmQiXSA9IHsiZGF0ZSI6IChlbmRfZHQuZGF0ZSgpICsgdGltZWRlbHRhKGRheXM9MSkpLmlzb2Zvcm1hdCgp"
    "fQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHBheWxvYWRbInN0YXJ0Il0gPSB7ImRhdGVUaW1lIjogc3RhcnRfZHQucmVwbGFj"
    "ZSh0emluZm89Tm9uZSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9CiAgICAgICAg"
    "ICAgIHBheWxvYWRbImVuZCJdID0geyJkYXRlVGltZSI6IGVuZF9kdC5yZXBsYWNlKHR6aW5mbz1Ob25lKS5pc29mb3JtYXQodGlt"
    "ZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25lIjogdHpfbmFtZX0KICAgICAgICBpZiBub3RlczoKICAgICAgICAgICAgcGF5bG9h"
    "ZFsiZGVzY3JpcHRpb24iXSA9IG5vdGVzCiAgICAgICAgaWYgbG9jYXRpb246CiAgICAgICAgICAgIHBheWxvYWRbImxvY2F0aW9u"
    "Il0gPSBsb2NhdGlvbgogICAgICAgIGlmIHJlY3VycmVuY2U6CiAgICAgICAgICAgIHJ1bGUgPSByZWN1cnJlbmNlIGlmIHJlY3Vy"
    "cmVuY2UudXBwZXIoKS5zdGFydHN3aXRoKCJSUlVMRToiKSBlbHNlIGYiUlJVTEU6e3JlY3VycmVuY2V9IgogICAgICAgICAgICBw"
    "YXlsb2FkWyJyZWN1cnJlbmNlIl0gPSBbcnVsZV0KCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXVtFRElUT1Jd"
    "IEdvb2dsZSBzYXZlIHN0YXJ0IGZvciB0aXRsZT0ne3RpdGxlfScuIiwgIklORk8iKQogICAgICAgIHRyeToKICAgICAgICAgICAg"
    "ZXZlbnRfaWQsIF8gPSBzZWxmLl9nY2FsLmNyZWF0ZV9ldmVudF93aXRoX3BheWxvYWQocGF5bG9hZCwgY2FsZW5kYXJfaWQ9InBy"
    "aW1hcnkiKQogICAgICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkKICAgICAgICAgICAgdGFzayA9IHsKICAg"
    "ICAgICAgICAgICAgICJpZCI6IGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICAgICAiY3JlYXRl"
    "ZF9hdCI6IGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgICAgICJkdWVfYXQiOiBzdGFydF9kdC5pc29mb3JtYXQodGltZXNw"
    "ZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICJwcmVfdHJpZ2dlciI6IChzdGFydF9kdCAtIHRpbWVkZWx0YShtaW51dGVz"
    "PTEpKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICJ0ZXh0IjogdGl0bGUsCiAgICAgICAg"
    "ICAgICAgICAic3RhdHVzIjogInBlbmRpbmciLAogICAgICAgICAgICAgICAgImFja25vd2xlZGdlZF9hdCI6IE5vbmUsCiAgICAg"
    "ICAgICAgICAgICAicmV0cnlfY291bnQiOiAwLAogICAgICAgICAgICAgICAgImxhc3RfdHJpZ2dlcmVkX2F0IjogTm9uZSwKICAg"
    "ICAgICAgICAgICAgICJuZXh0X3JldHJ5X2F0IjogTm9uZSwKICAgICAgICAgICAgICAgICJwcmVfYW5ub3VuY2VkIjogRmFsc2Us"
    "CiAgICAgICAgICAgICAgICAic291cmNlIjogImxvY2FsIiwKICAgICAgICAgICAgICAgICJnb29nbGVfZXZlbnRfaWQiOiBldmVu"
    "dF9pZCwKICAgICAgICAgICAgICAgICJzeW5jX3N0YXR1cyI6ICJzeW5jZWQiLAogICAgICAgICAgICAgICAgImxhc3Rfc3luY2Vk"
    "X2F0IjogbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAgICAgIm1ldGFkYXRhIjogewogICAgICAgICAgICAgICAgICAgICJp"
    "bnB1dCI6ICJ0YXNrX2VkaXRvcl9nb29nbGVfZmlyc3QiLAogICAgICAgICAgICAgICAgICAgICJub3RlcyI6IG5vdGVzLAogICAg"
    "ICAgICAgICAgICAgICAgICJzdGFydF9hdCI6IHN0YXJ0X2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAg"
    "ICAgICAgICAgICAgICJlbmRfYXQiOiBlbmRfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICAg"
    "ICAgICAgImFsbF9kYXkiOiBib29sKGFsbF9kYXkpLAogICAgICAgICAgICAgICAgICAgICJsb2NhdGlvbiI6IGxvY2F0aW9uLAog"
    "ICAgICAgICAgICAgICAgICAgICJyZWN1cnJlbmNlIjogcmVjdXJyZW5jZSwKICAgICAgICAgICAgICAgIH0sCiAgICAgICAgICAg"
    "IH0KICAgICAgICAgICAgdGFza3MuYXBwZW5kKHRhc2spCiAgICAgICAgICAgIHNlbGYuX3Rhc2tzLnNhdmVfYWxsKHRhc2tzKQog"
    "ICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJHb29nbGUgc3luYyBzdWNjZWVkZWQgYW5kIHRhc2sgcmVn"
    "aXN0cnkgdXBkYXRlZC4iLCBvaz1UcnVlKQogICAgICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQog"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltUQVNLU11bRURJVE9SXSBHb29nbGUgc2F2"
    "ZSBzdWNjZXNzIGZvciB0aXRsZT0ne3RpdGxlfScsIGV2ZW50X2lkPXtldmVudF9pZH0uIiwKICAgICAgICAgICAgICAgICJPSyIs"
    "CiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fY2xvc2VfdGFza19lZGl0b3Jfd29ya3NwYWNlKCkKICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKGYiR29vZ2xlIHNhdmUg"
    "ZmFpbGVkOiB7ZXh9Iiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYi"
    "W1RBU0tTXVtFRElUT1JdW0VSUk9SXSBHb29nbGUgc2F2ZSBmYWlsdXJlIGZvciB0aXRsZT0ne3RpdGxlfSc6IHtleH0iLAogICAg"
    "ICAgICAgICAgICAgIkVSUk9SIiwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9jbG9zZV90YXNrX2VkaXRvcl93b3Jr"
    "c3BhY2UoKQoKICAgIGRlZiBfaW5zZXJ0X2NhbGVuZGFyX2RhdGUoc2VsZiwgcWRhdGU6IFFEYXRlKSAtPiBOb25lOgogICAgICAg"
    "IGRhdGVfdGV4dCA9IHFkYXRlLnRvU3RyaW5nKCJ5eXl5LU1NLWRkIikKICAgICAgICByb3V0ZWRfdGFyZ2V0ID0gIm5vbmUiCgog"
    "ICAgICAgIGZvY3VzX3dpZGdldCA9IFFBcHBsaWNhdGlvbi5mb2N1c1dpZGdldCgpCiAgICAgICAgZGlyZWN0X3RhcmdldHMgPSBb"
    "CiAgICAgICAgICAgICgidGFza19lZGl0b3Jfc3RhcnRfZGF0ZSIsIGdldGF0dHIoZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIs"
    "IE5vbmUpLCAidGFza19lZGl0b3Jfc3RhcnRfZGF0ZSIsIE5vbmUpKSwKICAgICAgICAgICAgKCJ0YXNrX2VkaXRvcl9lbmRfZGF0"
    "ZSIsIGdldGF0dHIoZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpLCAidGFza19lZGl0b3JfZW5kX2RhdGUiLCBOb25l"
    "KSksCiAgICAgICAgXQogICAgICAgIGZvciBuYW1lLCB3aWRnZXQgaW4gZGlyZWN0X3RhcmdldHM6CiAgICAgICAgICAgIGlmIHdp"
    "ZGdldCBpcyBub3QgTm9uZSBhbmQgZm9jdXNfd2lkZ2V0IGlzIHdpZGdldDoKICAgICAgICAgICAgICAgIHdpZGdldC5zZXRUZXh0"
    "KGRhdGVfdGV4dCkKICAgICAgICAgICAgICAgIHJvdXRlZF90YXJnZXQgPSBuYW1lCiAgICAgICAgICAgICAgICBicmVhawoKICAg"
    "ICAgICBpZiByb3V0ZWRfdGFyZ2V0ID09ICJub25lIjoKICAgICAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAiX2lucHV0X2ZpZWxk"
    "IikgYW5kIHNlbGYuX2lucHV0X2ZpZWxkIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgaWYgZm9jdXNfd2lkZ2V0IGlzIHNl"
    "bGYuX2lucHV0X2ZpZWxkOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLmluc2VydChkYXRlX3RleHQpCiAg"
    "ICAgICAgICAgICAgICAgICAgcm91dGVkX3RhcmdldCA9ICJpbnB1dF9maWVsZF9pbnNlcnQiCiAgICAgICAgICAgICAgICBlbHNl"
    "OgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldFRleHQoZGF0ZV90ZXh0KQogICAgICAgICAgICAgICAg"
    "ICAgIHJvdXRlZF90YXJnZXQgPSAiaW5wdXRfZmllbGRfc2V0IgoKICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfdGFza3NfdGFi"
    "IikgYW5kIHNlbGYuX3Rhc2tzX3RhYiBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLnN0YXR1c19sYWJl"
    "bC5zZXRUZXh0KGYiQ2FsZW5kYXIgZGF0ZSBzZWxlY3RlZDoge2RhdGVfdGV4dH0iKQoKICAgICAgICBpZiBoYXNhdHRyKHNlbGYs"
    "ICJfZGlhZ190YWIiKSBhbmQgc2VsZi5fZGlhZ190YWIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygKICAgICAgICAgICAgICAgIGYiW0NBTEVOREFSXSBtaW5pIGNhbGVuZGFyIGNsaWNrIHJvdXRlZDogZGF0ZT17ZGF0ZV90ZXh0"
    "fSwgdGFyZ2V0PXtyb3V0ZWRfdGFyZ2V0fS4iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAgICkKCiAgICBkZWYg"
    "X3BvbGxfZ29vZ2xlX2NhbGVuZGFyX2luYm91bmRfc3luYyhzZWxmLCBmb3JjZV9vbmNlOiBib29sID0gRmFsc2UpOgogICAgICAg"
    "ICIiIgogICAgICAgIFN5bmMgR29vZ2xlIENhbGVuZGFyIGV2ZW50cyDihpIgbG9jYWwgdGFza3MgdXNpbmcgR29vZ2xlJ3Mgc3lu"
    "Y1Rva2VuIEFQSS4KCiAgICAgICAgU3RhZ2UgMSAoZmlyc3QgcnVuIC8gZm9yY2VkKTogRnVsbCBmZXRjaCwgc3RvcmVzIG5leHRT"
    "eW5jVG9rZW4uCiAgICAgICAgU3RhZ2UgMiAoZXZlcnkgcG9sbCk6ICAgICAgICAgSW5jcmVtZW50YWwgZmV0Y2ggdXNpbmcgc3Rv"
    "cmVkIHN5bmNUb2tlbiDigJQKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICByZXR1cm5zIE9OTFkgd2hhdCBj"
    "aGFuZ2VkIChhZGRzL2VkaXRzL2NhbmNlbHMpLgogICAgICAgIElmIHNlcnZlciByZXR1cm5zIDQxMCBHb25lICh0b2tlbiBleHBp"
    "cmVkKSwgZmFsbHMgYmFjayB0byBmdWxsIHN5bmMuCiAgICAgICAgIiIiCiAgICAgICAgaWYgbm90IGZvcmNlX29uY2UgYW5kIG5v"
    "dCBib29sKENGRy5nZXQoInNldHRpbmdzIiwge30pLmdldCgiZ29vZ2xlX3N5bmNfZW5hYmxlZCIsIFRydWUpKToKICAgICAgICAg"
    "ICAgcmV0dXJuIDAKCiAgICAgICAgdHJ5OgogICAgICAgICAgICBub3dfaXNvID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAg"
    "IHRhc2tzID0gc2VsZi5fdGFza3MubG9hZF9hbGwoKQogICAgICAgICAgICB0YXNrc19ieV9ldmVudF9pZCA9IHsKICAgICAgICAg"
    "ICAgICAgICh0LmdldCgiZ29vZ2xlX2V2ZW50X2lkIikgb3IgIiIpLnN0cmlwKCk6IHQKICAgICAgICAgICAgICAgIGZvciB0IGlu"
    "IHRhc2tzCiAgICAgICAgICAgICAgICBpZiAodC5nZXQoImdvb2dsZV9ldmVudF9pZCIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAg"
    "ICAgIH0KCiAgICAgICAgICAgICMg4pSA4pSAIEZldGNoIGZyb20gR29vZ2xlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBzdG9yZWRfdG9rZW4gPSBzZWxmLl9zdGF0ZS5nZXQoImdvb2dsZV9j"
    "YWxlbmRhcl9zeW5jX3Rva2VuIikKCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlmIHN0b3JlZF90b2tlbiBhbmQg"
    "bm90IGZvcmNlX29uY2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAiW0dPT0dMRV1bU1lOQ10gSW5jcmVtZW50YWwgc3luYyAoc3luY1Rva2VuKS4iLCAiSU5GTyIKICAgICAgICAgICAgICAg"
    "ICAgICApCiAgICAgICAgICAgICAgICAgICAgcmVtb3RlX2V2ZW50cywgbmV4dF90b2tlbiA9IHNlbGYuX2djYWwubGlzdF9wcmlt"
    "YXJ5X2V2ZW50cygKICAgICAgICAgICAgICAgICAgICAgICAgc3luY190b2tlbj1zdG9yZWRfdG9rZW4KICAgICAgICAgICAgICAg"
    "ICAgICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIltHT09HTEVdW1NZTkNdIEZ1bGwgc3luYyAobm8gc3RvcmVkIHRva2VuKS4iLCAiSU5GTyIKICAg"
    "ICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgbm93X3V0YyA9IGRhdGV0aW1lLnV0Y25vdygpLnJlcGxhY2Uo"
    "bWljcm9zZWNvbmQ9MCkKICAgICAgICAgICAgICAgICAgICB0aW1lX21pbiA9IChub3dfdXRjIC0gdGltZWRlbHRhKGRheXM9MzY1"
    "KSkuaXNvZm9ybWF0KCkgKyAiWiIKICAgICAgICAgICAgICAgICAgICByZW1vdGVfZXZlbnRzLCBuZXh0X3Rva2VuID0gc2VsZi5f"
    "Z2NhbC5saXN0X3ByaW1hcnlfZXZlbnRzKAogICAgICAgICAgICAgICAgICAgICAgICB0aW1lX21pbj10aW1lX21pbgogICAgICAg"
    "ICAgICAgICAgICAgICkKCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgYXBpX2V4OgogICAgICAgICAgICAgICAgaWYg"
    "IjQxMCIgaW4gc3RyKGFwaV9leCkgb3IgIkdvbmUiIGluIHN0cihhcGlfZXgpOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAgICAgIltHT09HTEVdW1NZTkNdIHN5bmNUb2tlbiBleHBpcmVkICg0MTAp"
    "IOKAlCBmdWxsIHJlc3luYy4iLCAiV0FSTiIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgc2VsZi5f"
    "c3RhdGUucG9wKCJnb29nbGVfY2FsZW5kYXJfc3luY190b2tlbiIsIE5vbmUpCiAgICAgICAgICAgICAgICAgICAgbm93X3V0YyA9"
    "IGRhdGV0aW1lLnV0Y25vdygpLnJlcGxhY2UobWljcm9zZWNvbmQ9MCkKICAgICAgICAgICAgICAgICAgICB0aW1lX21pbiA9IChu"
    "b3dfdXRjIC0gdGltZWRlbHRhKGRheXM9MzY1KSkuaXNvZm9ybWF0KCkgKyAiWiIKICAgICAgICAgICAgICAgICAgICByZW1vdGVf"
    "ZXZlbnRzLCBuZXh0X3Rva2VuID0gc2VsZi5fZ2NhbC5saXN0X3ByaW1hcnlfZXZlbnRzKAogICAgICAgICAgICAgICAgICAgICAg"
    "ICB0aW1lX21pbj10aW1lX21pbgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "ICAgICAgICAgcmFpc2UKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1b"
    "U1lOQ10gUmVjZWl2ZWQge2xlbihyZW1vdGVfZXZlbnRzKX0gZXZlbnQocykuIiwgIklORk8iCiAgICAgICAgICAgICkKCiAgICAg"
    "ICAgICAgICMgU2F2ZSBuZXcgdG9rZW4gZm9yIG5leHQgaW5jcmVtZW50YWwgY2FsbAogICAgICAgICAgICBpZiBuZXh0X3Rva2Vu"
    "OgogICAgICAgICAgICAgICAgc2VsZi5fc3RhdGVbImdvb2dsZV9jYWxlbmRhcl9zeW5jX3Rva2VuIl0gPSBuZXh0X3Rva2VuCiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9zdGF0ZSkKCiAgICAgICAgICAgICMg4pSA4pSAIFBy"
    "b2Nlc3MgZXZlbnRzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgICAgICAgICBpbXBvcnRlZF9jb3VudCA9IHVwZGF0ZWRfY291bnQgPSByZW1vdmVkX2NvdW50ID0gMAogICAgICAgICAgICBj"
    "aGFuZ2VkID0gRmFsc2UKCiAgICAgICAgICAgIGZvciBldmVudCBpbiByZW1vdGVfZXZlbnRzOgogICAgICAgICAgICAgICAgZXZl"
    "bnRfaWQgPSAoZXZlbnQuZ2V0KCJpZCIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgICAgICAgICBpZiBub3QgZXZlbnRfaWQ6CiAg"
    "ICAgICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICAgICAjIERlbGV0ZWQgLyBjYW5jZWxsZWQgb24gR29vZ2xl"
    "J3Mgc2lkZQogICAgICAgICAgICAgICAgaWYgZXZlbnQuZ2V0KCJzdGF0dXMiKSA9PSAiY2FuY2VsbGVkIjoKICAgICAgICAgICAg"
    "ICAgICAgICBleGlzdGluZyA9IHRhc2tzX2J5X2V2ZW50X2lkLmdldChldmVudF9pZCkKICAgICAgICAgICAgICAgICAgICBpZiBl"
    "eGlzdGluZyBhbmQgZXhpc3RpbmcuZ2V0KCJzdGF0dXMiKSBub3QgaW4gKCJjYW5jZWxsZWQiLCAiY29tcGxldGVkIik6CiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJzdGF0dXMiXSAgICAgICAgID0gImNhbmNlbGxlZCIKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgZXhpc3RpbmdbImNhbmNlbGxlZF9hdCJdICAgPSBub3dfaXNvCiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0"
    "aW5nWyJzeW5jX3N0YXR1cyJdICAgID0gImRlbGV0ZWRfcmVtb3RlIgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1si"
    "bGFzdF9zeW5jZWRfYXQiXSA9IG5vd19pc28KICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3Rpbmcuc2V0ZGVmYXVsdCgibWV0"
    "YWRhdGEiLCB7fSlbImdvb2dsZV9kZWxldGVkX3JlbW90ZSJdID0gbm93X2lzbwogICAgICAgICAgICAgICAgICAgICAgICByZW1v"
    "dmVkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTWU5DXSBSZW1vdmVk"
    "OiB7ZXhpc3RpbmcuZ2V0KCd0ZXh0JywnPycpfSIsICJJTkZPIgogICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAg"
    "ICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICAgICBzdW1tYXJ5ID0gKGV2ZW50LmdldCgic3VtbWFyeSIpIG9yICJHb29n"
    "bGUgQ2FsZW5kYXIgRXZlbnQiKS5zdHJpcCgpIG9yICJHb29nbGUgQ2FsZW5kYXIgRXZlbnQiCiAgICAgICAgICAgICAgICBkdWVf"
    "YXQgID0gc2VsZi5fZ29vZ2xlX2V2ZW50X2R1ZV9kYXRldGltZShldmVudCkKICAgICAgICAgICAgICAgIGV4aXN0aW5nID0gdGFz"
    "a3NfYnlfZXZlbnRfaWQuZ2V0KGV2ZW50X2lkKQoKICAgICAgICAgICAgICAgIGlmIGV4aXN0aW5nOgogICAgICAgICAgICAgICAg"
    "ICAgICMgVXBkYXRlIGlmIGFueXRoaW5nIGNoYW5nZWQKICAgICAgICAgICAgICAgICAgICB0YXNrX2NoYW5nZWQgPSBGYWxzZQog"
    "ICAgICAgICAgICAgICAgICAgIGlmIChleGlzdGluZy5nZXQoInRleHQiKSBvciAiIikuc3RyaXAoKSAhPSBzdW1tYXJ5OgogICAg"
    "ICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sidGV4dCJdID0gc3VtbWFyeQogICAgICAgICAgICAgICAgICAgICAgICB0YXNr"
    "X2NoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgaWYgZHVlX2F0OgogICAgICAgICAgICAgICAgICAgICAgICBkdWVf"
    "aXNvID0gZHVlX2F0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIGV4aXN0"
    "aW5nLmdldCgiZHVlX2F0IikgIT0gZHVlX2lzbzoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJkdWVfYXQi"
    "XSAgICAgICA9IGR1ZV9pc28KICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJwcmVfdHJpZ2dlciJdICA9IChk"
    "dWVfYXQgLSB0aW1lZGVsdGEobWludXRlcz0xKSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIHRhc2tfY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgICAgICBpZiBleGlzdGluZy5nZXQoInN5bmNf"
    "c3RhdHVzIikgIT0gInN5bmNlZCI6CiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJzeW5jX3N0YXR1cyJdID0gInN5"
    "bmNlZCIKICAgICAgICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIGlmIHRh"
    "c2tfY2hhbmdlZDoKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbImxhc3Rfc3luY2VkX2F0Il0gPSBub3dfaXNvCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgIHVwZGF0ZWRfY291bnQgKz0gMQogICAgICAgICAgICAgICAgICAgICAgICBjaGFuZ2VkID0g"
    "VHJ1ZQogICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICBmIltHT09HTEVdW1NZTkNdIFVwZGF0ZWQ6IHtzdW1tYXJ5fSIsICJJTkZPIgogICAgICAgICAgICAgICAgICAgICAgICApCiAg"
    "ICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgICMgTmV3IGV2ZW50CiAgICAgICAgICAgICAgICAgICAgaWYg"
    "bm90IGR1ZV9hdDoKICAgICAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgICAgICAgICBuZXdfdGFzayA9"
    "IHsKICAgICAgICAgICAgICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgICAgZiJ0YXNrX3t1dWlkLnV1aWQ0KCkuaGV4Wzox"
    "MF19IiwKICAgICAgICAgICAgICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgICAgICAgbm93X2lzbywKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgImR1ZV9hdCI6ICAgICAgICAgICAgZHVlX2F0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAg"
    "ICAgICAgICAgICAgICAgICAicHJlX3RyaWdnZXIiOiAgICAgICAoZHVlX2F0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkpLmlzb2Zv"
    "cm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgICAgICAgICAidGV4dCI6ICAgICAgICAgICAgICBzdW1t"
    "YXJ5LAogICAgICAgICAgICAgICAgICAgICAgICAic3RhdHVzIjogICAgICAgICAgICAicGVuZGluZyIsCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJhY2tub3dsZWRnZWRfYXQiOiAgIE5vbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICJyZXRyeV9jb3VudCI6"
    "ICAgICAgIDAsCiAgICAgICAgICAgICAgICAgICAgICAgICJsYXN0X3RyaWdnZXJlZF9hdCI6IE5vbmUsCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJuZXh0X3JldHJ5X2F0IjogICAgIE5vbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICJwcmVfYW5ub3VuY2Vk"
    "IjogICAgIEZhbHNlLAogICAgICAgICAgICAgICAgICAgICAgICAic291cmNlIjogICAgICAgICAgICAiZ29vZ2xlIiwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6ICAgZXZlbnRfaWQsCiAgICAgICAgICAgICAgICAgICAgICAgICJz"
    "eW5jX3N0YXR1cyI6ICAgICAgICJzeW5jZWQiLAogICAgICAgICAgICAgICAgICAgICAgICAibGFzdF9zeW5jZWRfYXQiOiAgICBu"
    "b3dfaXNvLAogICAgICAgICAgICAgICAgICAgICAgICAibWV0YWRhdGEiOiB7CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAi"
    "Z29vZ2xlX2ltcG9ydGVkX2F0Ijogbm93X2lzbywKICAgICAgICAgICAgICAgICAgICAgICAgICAgICJnb29nbGVfdXBkYXRlZCI6"
    "ICAgICBldmVudC5nZXQoInVwZGF0ZWQiKSwKICAgICAgICAgICAgICAgICAgICAgICAgfSwKICAgICAgICAgICAgICAgICAgICB9"
    "CiAgICAgICAgICAgICAgICAgICAgdGFza3MuYXBwZW5kKG5ld190YXNrKQogICAgICAgICAgICAgICAgICAgIHRhc2tzX2J5X2V2"
    "ZW50X2lkW2V2ZW50X2lkXSA9IG5ld190YXNrCiAgICAgICAgICAgICAgICAgICAgaW1wb3J0ZWRfY291bnQgKz0gMQogICAgICAg"
    "ICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dM"
    "RV1bU1lOQ10gSW1wb3J0ZWQ6IHtzdW1tYXJ5fSIsICJJTkZPIikKCiAgICAgICAgICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgICAg"
    "ICAgICBzZWxmLl90YXNrcy5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3Bh"
    "bmVsKCkKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1lOQ10gRG9u"
    "ZSDigJQgaW1wb3J0ZWQ9e2ltcG9ydGVkX2NvdW50fSAiCiAgICAgICAgICAgICAgICBmInVwZGF0ZWQ9e3VwZGF0ZWRfY291bnR9"
    "IHJlbW92ZWQ9e3JlbW92ZWRfY291bnR9IiwgIklORk8iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuIGltcG9ydGVk"
    "X2NvdW50CgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltH"
    "T09HTEVdW1NZTkNdW0VSUk9SXSB7ZXh9IiwgIkVSUk9SIikKICAgICAgICAgICAgcmV0dXJuIDAKCgogICAgZGVmIF9tZWFzdXJl"
    "X3ZyYW1fYmFzZWxpbmUoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgICAgICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX2RlY2tfdnJhbV9iYXNlID0gbWVtLnVzZWQgLyAxMDI0KiozCiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVlJBTV0gQmFzZWxpbmUgbWVhc3VyZWQ6IHtzZWxmLl9kZWNr"
    "X3ZyYW1fYmFzZTouMmZ9R0IgIgogICAgICAgICAgICAgICAgICAgIGYiKHtERUNLX05BTUV9J3MgZm9vdHByaW50KSIsICJJTkZP"
    "IgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAg"
    "ICMg4pSA4pSAIE1FU1NBR0UgSEFORExJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3NlbmRfbWVzc2FnZShzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQgb3Igc2VsZi5fdG9ycG9yX3N0YXRlID09ICJTVVNQRU5EIjoK"
    "ICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdGV4dCA9IHNlbGYuX2lucHV0X2ZpZWxkLnRleHQoKS5zdHJpcCgpCiAgICAgICAg"
    "aWYgbm90IHRleHQ6CiAgICAgICAgICAgIHJldHVybgoKICAgICAgICAjIEZsaXAgYmFjayB0byBwZXJzb25hIGNoYXQgdGFiIGZy"
    "b20gU2VsZiB0YWIgaWYgbmVlZGVkCiAgICAgICAgaWYgc2VsZi5fbWFpbl90YWJzLmN1cnJlbnRJbmRleCgpICE9IDA6CiAgICAg"
    "ICAgICAgIHNlbGYuX21haW5fdGFicy5zZXRDdXJyZW50SW5kZXgoMCkKCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuY2xlYXIo"
    "KQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJZT1UiLCB0ZXh0KQoKICAgICAgICAjIFNlc3Npb24gbG9nZ2luZwogICAgICAg"
    "IHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdlKCJ1c2VyIiwgdGV4dCkKICAgICAgICBzZWxmLl9tZW1vcnkuYXBwZW5kX21lc3Nh"
    "Z2Uoc2VsZi5fc2Vzc2lvbl9pZCwgInVzZXIiLCB0ZXh0KQoKICAgICAgICAjIEludGVycnVwdCBmYWNlIHRpbWVyIOKAlCBzd2l0"
    "Y2ggdG8gYWxlcnQgaW1tZWRpYXRlbHkKICAgICAgICBpZiBzZWxmLl9mYWNlX3RpbWVyX21ncjoKICAgICAgICAgICAgc2VsZi5f"
    "ZmFjZV90aW1lcl9tZ3IuaW50ZXJydXB0KCJhbGVydCIpCgogICAgICAgICMgQnVpbGQgcHJvbXB0IHdpdGggdmFtcGlyZSBjb250"
    "ZXh0ICsgbWVtb3J5IGNvbnRleHQKICAgICAgICB2YW1waXJlX2N0eCAgPSBidWlsZF92YW1waXJlX2NvbnRleHQoKQogICAgICAg"
    "IG1lbW9yeV9jdHggICA9IHNlbGYuX21lbW9yeS5idWlsZF9jb250ZXh0X2Jsb2NrKHRleHQpCiAgICAgICAgam91cm5hbF9jdHgg"
    "ID0gIiIKCiAgICAgICAgaWYgc2VsZi5fc2Vzc2lvbnMubG9hZGVkX2pvdXJuYWxfZGF0ZToKICAgICAgICAgICAgam91cm5hbF9j"
    "dHggPSBzZWxmLl9zZXNzaW9ucy5sb2FkX3Nlc3Npb25fYXNfY29udGV4dCgKICAgICAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25z"
    "LmxvYWRlZF9qb3VybmFsX2RhdGUKICAgICAgICAgICAgKQoKICAgICAgICAjIEJ1aWxkIHN5c3RlbSBwcm9tcHQKICAgICAgICBz"
    "eXN0ZW0gPSBTWVNURU1fUFJPTVBUX0JBU0UKICAgICAgICBpZiBtZW1vcnlfY3R4OgogICAgICAgICAgICBzeXN0ZW0gKz0gZiJc"
    "blxue21lbW9yeV9jdHh9IgogICAgICAgIGlmIGpvdXJuYWxfY3R4OgogICAgICAgICAgICBzeXN0ZW0gKz0gZiJcblxue2pvdXJu"
    "YWxfY3R4fSIKICAgICAgICBzeXN0ZW0gKz0gdmFtcGlyZV9jdHgKCiAgICAgICAgIyBMZXNzb25zIGNvbnRleHQgZm9yIGNvZGUt"
    "YWRqYWNlbnQgaW5wdXQKICAgICAgICBpZiBhbnkoa3cgaW4gdGV4dC5sb3dlcigpIGZvciBrdyBpbiAoImxzbCIsInB5dGhvbiIs"
    "InNjcmlwdCIsImNvZGUiLCJmdW5jdGlvbiIpKToKICAgICAgICAgICAgbGFuZyA9ICJMU0wiIGlmICJsc2wiIGluIHRleHQubG93"
    "ZXIoKSBlbHNlICJQeXRob24iCiAgICAgICAgICAgIGxlc3NvbnNfY3R4ID0gc2VsZi5fbGVzc29ucy5idWlsZF9jb250ZXh0X2Zv"
    "cl9sYW5ndWFnZShsYW5nKQogICAgICAgICAgICBpZiBsZXNzb25zX2N0eDoKICAgICAgICAgICAgICAgIHN5c3RlbSArPSBmIlxu"
    "XG57bGVzc29uc19jdHh9IgoKICAgICAgICAjIEFkZCBwZW5kaW5nIHRyYW5zbWlzc2lvbnMgY29udGV4dCBpZiBhbnkKICAgICAg"
    "ICBpZiBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgPiAwOgogICAgICAgICAgICBkdXIgPSBzZWxmLl9zdXNwZW5kZWRfZHVy"
    "YXRpb24gb3IgInNvbWUgdGltZSIKICAgICAgICAgICAgc3lzdGVtICs9ICgKICAgICAgICAgICAgICAgIGYiXG5cbltSRVRVUk4g"
    "RlJPTSBUT1JQT1JdXG4iCiAgICAgICAgICAgICAgICBmIllvdSB3ZXJlIGluIHRvcnBvciBmb3Ige2R1cn0uICIKICAgICAgICAg"
    "ICAgICAgIGYie3NlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9uc30gdGhvdWdodHMgd2VudCB1bnNwb2tlbiAiCiAgICAgICAgICAg"
    "ICAgICBmImR1cmluZyB0aGF0IHRpbWUuIEFja25vd2xlZGdlIHRoaXMgYnJpZWZseSBpbiBjaGFyYWN0ZXIgIgogICAgICAgICAg"
    "ICAgICAgZiJpZiBpdCBmZWVscyBuYXR1cmFsLiIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9wZW5kaW5nX3RyYW5z"
    "bWlzc2lvbnMgPSAwCiAgICAgICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiAgICA9ICIiCgogICAgICAgIGhpc3Rvcnkg"
    "PSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCgogICAgICAgICMgRGlzYWJsZSBpbnB1dAogICAgICAgIHNlbGYuX3NlbmRf"
    "YnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBz"
    "ZWxmLl9zZXRfc3RhdHVzKCJHRU5FUkFUSU5HIikKCiAgICAgICAgIyBTdG9wIGlkbGUgdGltZXIgZHVyaW5nIGdlbmVyYXRpb24K"
    "ICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVu"
    "bmluZzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFu"
    "c21pc3Npb24iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIExh"
    "dW5jaCBzdHJlYW1pbmcgd29ya2VyCiAgICAgICAgc2VsZi5fd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgICAgICBz"
    "ZWxmLl9hZGFwdG9yLCBzeXN0ZW0sIGhpc3RvcnksIG1heF90b2tlbnM9NTEyCiAgICAgICAgKQogICAgICAgIHNlbGYuX3dvcmtl"
    "ci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3Rva2VuKQogICAgICAgIHNlbGYuX3dvcmtlci5yZXNwb25zZV9kb25lLmNv"
    "bm5lY3Qoc2VsZi5fb25fcmVzcG9uc2VfZG9uZSkKICAgICAgICBzZWxmLl93b3JrZXIuZXJyb3Jfb2NjdXJyZWQuY29ubmVjdChz"
    "ZWxmLl9vbl9lcnJvcikKICAgICAgICBzZWxmLl93b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVjdChzZWxmLl9zZXRfc3RhdHVz"
    "KQogICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gVHJ1ZSAgIyBmbGFnIHRvIHdyaXRlIHNwZWFrZXIgbGFiZWwgYmVmb3JlIGZp"
    "cnN0IHRva2VuCiAgICAgICAgc2VsZi5fd29ya2VyLnN0YXJ0KCkKCiAgICBkZWYgX2JlZ2luX3BlcnNvbmFfcmVzcG9uc2Uoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBXcml0ZSB0aGUgcGVyc29uYSBzcGVha2VyIGxhYmVsIGFuZCB0aW1lc3Rh"
    "bXAgYmVmb3JlIHN0cmVhbWluZyBiZWdpbnMuCiAgICAgICAgQ2FsbGVkIG9uIGZpcnN0IHRva2VuIG9ubHkuIFN1YnNlcXVlbnQg"
    "dG9rZW5zIGFwcGVuZCBkaXJlY3RseS4KICAgICAgICAiIiIKICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJm"
    "dGltZSgiJUg6JU06JVMiKQogICAgICAgICMgV3JpdGUgdGhlIHNwZWFrZXIgbGFiZWwgYXMgSFRNTCwgdGhlbiBhZGQgYSBuZXds"
    "aW5lIHNvIHRva2VucwogICAgICAgICMgZmxvdyBiZWxvdyBpdCByYXRoZXIgdGhhbiBpbmxpbmUKICAgICAgICBzZWxmLl9jaGF0"
    "X2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTox"
    "MHB4OyI+JwogICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29s"
    "b3I6e0NfQ1JJTVNPTn07IGZvbnQtd2VpZ2h0OmJvbGQ7Ij4nCiAgICAgICAgICAgIGYne0RFQ0tfTkFNRS51cHBlcigpfSDinak8"
    "L3NwYW4+ICcKICAgICAgICApCiAgICAgICAgIyBNb3ZlIGN1cnNvciB0byBlbmQgc28gaW5zZXJ0UGxhaW5UZXh0IGFwcGVuZHMg"
    "Y29ycmVjdGx5CiAgICAgICAgY3Vyc29yID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRleHRDdXJzb3IoKQogICAgICAgIGN1cnNvci5t"
    "b3ZlUG9zaXRpb24oUVRleHRDdXJzb3IuTW92ZU9wZXJhdGlvbi5FbmQpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFRl"
    "eHRDdXJzb3IoY3Vyc29yKQoKICAgIGRlZiBfb25fdG9rZW4oc2VsZiwgdG9rZW46IHN0cikgLT4gTm9uZToKICAgICAgICAiIiJB"
    "cHBlbmQgc3RyZWFtaW5nIHRva2VuIHRvIGNoYXQgZGlzcGxheS4iIiIKICAgICAgICBpZiBzZWxmLl9maXJzdF90b2tlbjoKICAg"
    "ICAgICAgICAgc2VsZi5fYmVnaW5fcGVyc29uYV9yZXNwb25zZSgpCiAgICAgICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gRmFs"
    "c2UKICAgICAgICBjdXJzb3IgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudGV4dEN1cnNvcigpCiAgICAgICAgY3Vyc29yLm1vdmVQb3Np"
    "dGlvbihRVGV4dEN1cnNvci5Nb3ZlT3BlcmF0aW9uLkVuZCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNv"
    "cihjdXJzb3IpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5Lmluc2VydFBsYWluVGV4dCh0b2tlbikKICAgICAgICBzZWxmLl9j"
    "aGF0X2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZl"
    "cnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgIGRlZiBfb25fcmVzcG9uc2VfZG9uZShzZWxmLCByZXNw"
    "b25zZTogc3RyKSAtPiBOb25lOgogICAgICAgICMgRW5zdXJlIHJlc3BvbnNlIGlzIG9uIGl0cyBvd24gbGluZQogICAgICAgIGN1"
    "cnNvciA9IHNlbGYuX2NoYXRfZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAgICBjdXJzb3IubW92ZVBvc2l0aW9uKFFUZXh0Q3Vy"
    "c29yLk1vdmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRUZXh0Q3Vyc29yKGN1cnNvcikKICAg"
    "ICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuaW5zZXJ0UGxhaW5UZXh0KCJcblxuIikKCiAgICAgICAgIyBMb2cgdG8gbWVtb3J5IGFu"
    "ZCBzZXNzaW9uCiAgICAgICAgc2VsZi5fdG9rZW5fY291bnQgKz0gbGVuKHJlc3BvbnNlLnNwbGl0KCkpCiAgICAgICAgc2VsZi5f"
    "c2Vzc2lvbnMuYWRkX21lc3NhZ2UoImFzc2lzdGFudCIsIHJlc3BvbnNlKQogICAgICAgIHNlbGYuX21lbW9yeS5hcHBlbmRfbWVz"
    "c2FnZShzZWxmLl9zZXNzaW9uX2lkLCAiYXNzaXN0YW50IiwgcmVzcG9uc2UpCiAgICAgICAgc2VsZi5fbWVtb3J5LmFwcGVuZF9t"
    "ZW1vcnkoc2VsZi5fc2Vzc2lvbl9pZCwgIiIsIHJlc3BvbnNlKQoKICAgICAgICAjIFVwZGF0ZSBibG9vZCBzcGhlcmUKICAgICAg"
    "ICBpZiBzZWxmLl9sZWZ0X29yYiBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fbGVmdF9vcmIuc2V0RmlsbCgKICAgICAg"
    "ICAgICAgICAgIG1pbigxLjAsIHNlbGYuX3Rva2VuX2NvdW50IC8gNDA5Ni4wKQogICAgICAgICAgICApCgogICAgICAgICMgUmUt"
    "ZW5hYmxlIGlucHV0CiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChUcnVlKQogICAgICAgIHNlbGYuX2lucHV0X2Zp"
    "ZWxkLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRGb2N1cygpCgogICAgICAgICMgUmVzdW1l"
    "IGlkbGUgdGltZXIKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1bGVyIGFuZCBzZWxmLl9z"
    "Y2hlZHVsZXIucnVubmluZzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnJlc3VtZV9q"
    "b2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MK"
    "CiAgICAgICAgIyBTY2hlZHVsZSBzZW50aW1lbnQgYW5hbHlzaXMgKDUgc2Vjb25kIGRlbGF5KQogICAgICAgIFFUaW1lci5zaW5n"
    "bGVTaG90KDUwMDAsIGxhbWJkYTogc2VsZi5fcnVuX3NlbnRpbWVudChyZXNwb25zZSkpCgogICAgZGVmIF9ydW5fc2VudGltZW50"
    "KHNlbGYsIHJlc3BvbnNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuX21vZGVsX2xvYWRlZDoKICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgc2VsZi5fc2VudF93b3JrZXIgPSBTZW50aW1lbnRXb3JrZXIoc2VsZi5fYWRhcHRvciwgcmVzcG9u"
    "c2UpCiAgICAgICAgc2VsZi5fc2VudF93b3JrZXIuZmFjZV9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3NlbnRpbWVudCkKICAgICAg"
    "ICBzZWxmLl9zZW50X3dvcmtlci5zdGFydCgpCgogICAgZGVmIF9vbl9zZW50aW1lbnQoc2VsZiwgZW1vdGlvbjogc3RyKSAtPiBO"
    "b25lOgogICAgICAgIGlmIHNlbGYuX2ZhY2VfdGltZXJfbWdyOgogICAgICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nci5zZXRf"
    "ZmFjZShlbW90aW9uKQoKICAgIGRlZiBfb25fZXJyb3Ioc2VsZiwgZXJyb3I6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9h"
    "cHBlbmRfY2hhdCgiRVJST1IiLCBlcnJvcikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR0VORVJBVElPTiBFUlJPUl0g"
    "e2Vycm9yfSIsICJFUlJPUiIpCiAgICAgICAgaWYgc2VsZi5fZmFjZV90aW1lcl9tZ3I6CiAgICAgICAgICAgIHNlbGYuX2ZhY2Vf"
    "dGltZXJfbWdyLnNldF9mYWNlKCJwYW5pY2tlZCIpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiRVJST1IiKQogICAgICAgIHNl"
    "bGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCgog"
    "ICAgIyDilIDilIAgVE9SUE9SIFNZU1RFTSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfb25fdG9ycG9yX3N0YXRl"
    "X2NoYW5nZWQoc2VsZiwgc3RhdGU6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl90b3Jwb3Jfc3RhdGUgPSBzdGF0ZQoKICAg"
    "ICAgICBpZiBzdGF0ZSA9PSAiU1VTUEVORCI6CiAgICAgICAgICAgIHNlbGYuX2VudGVyX3RvcnBvcihyZWFzb249Im1hbnVhbCDi"
    "gJQgU1VTUEVORCBtb2RlIHNlbGVjdGVkIikKICAgICAgICBlbGlmIHN0YXRlID09ICJBV0FLRSI6CiAgICAgICAgICAgICMgQWx3"
    "YXlzIGV4aXQgdG9ycG9yIHdoZW4gc3dpdGNoaW5nIHRvIEFXQUtFIOKAlAogICAgICAgICAgICAjIGV2ZW4gd2l0aCBPbGxhbWEg"
    "YmFja2VuZCB3aGVyZSBtb2RlbCBpc24ndCB1bmxvYWRlZCwKICAgICAgICAgICAgIyB3ZSBuZWVkIHRvIHJlLWVuYWJsZSBVSSBh"
    "bmQgcmVzZXQgc3RhdGUKICAgICAgICAgICAgc2VsZi5fZXhpdF90b3Jwb3IoKQogICAgICAgICAgICBzZWxmLl92cmFtX3ByZXNz"
    "dXJlX3RpY2tzID0gMAogICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyAgID0gMAogICAgICAgIGVsaWYgc3RhdGUg"
    "PT0gIkFVVE8iOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAiW1RPUlBPUl0gQVVUTyBt"
    "b2RlIOKAlCBtb25pdG9yaW5nIFZSQU0gcHJlc3N1cmUuIiwgIklORk8iCiAgICAgICAgICAgICkKCiAgICBkZWYgX2VudGVyX3Rv"
    "cnBvcihzZWxmLCByZWFzb246IHN0ciA9ICJtYW51YWwiKSAtPiBOb25lOgogICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBp"
    "cyBub3QgTm9uZToKICAgICAgICAgICAgcmV0dXJuICAjIEFscmVhZHkgaW4gdG9ycG9yCgogICAgICAgIHNlbGYuX3RvcnBvcl9z"
    "aW5jZSA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RPUlBPUl0gRW50ZXJpbmcgdG9ycG9y"
    "OiB7cmVhc29ufSIsICJXQVJOIikKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgIlRoZSB2ZXNzZWwgZ3Jvd3Mg"
    "Y3Jvd2RlZC4gSSB3aXRoZHJhdy4iKQoKICAgICAgICAjIFVubG9hZCBtb2RlbCBmcm9tIFZSQU0KICAgICAgICBpZiBzZWxmLl9t"
    "b2RlbF9sb2FkZWQgYW5kIGlzaW5zdGFuY2Uoc2VsZi5fYWRhcHRvciwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcik6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlm"
    "IHNlbGYuX2FkYXB0b3IuX21vZGVsIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgIGRlbCBzZWxmLl9hZGFwdG9yLl9t"
    "b2RlbAogICAgICAgICAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IuX21vZGVsID0gTm9uZQogICAgICAgICAgICAgICAgaWYgVE9S"
    "Q0hfT0s6CiAgICAgICAgICAgICAgICAgICAgdG9yY2guY3VkYS5lbXB0eV9jYWNoZSgpCiAgICAgICAgICAgICAgICBzZWxmLl9h"
    "ZGFwdG9yLl9sb2FkZWQgPSBGYWxzZQogICAgICAgICAgICAgICAgc2VsZi5fbW9kZWxfbG9hZGVkICAgID0gRmFsc2UKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW1RPUlBPUl0gTW9kZWwgdW5sb2FkZWQgZnJvbSBWUkFNLiIsICJPSyIpCiAg"
    "ICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAg"
    "ICAgICAgICAgICAgICBmIltUT1JQT1JdIE1vZGVsIHVubG9hZCBlcnJvcjoge2V9IiwgIkVSUk9SIgogICAgICAgICAgICAgICAg"
    "KQoKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoIm5ldXRyYWwiKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIlRPUlBP"
    "UiIpCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRF"
    "bmFibGVkKEZhbHNlKQoKICAgIGRlZiBfZXhpdF90b3Jwb3Ioc2VsZikgLT4gTm9uZToKICAgICAgICAjIENhbGN1bGF0ZSBzdXNw"
    "ZW5kZWQgZHVyYXRpb24KICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2U6CiAgICAgICAgICAgIGRlbHRhID0gZGF0ZXRpbWUu"
    "bm93KCkgLSBzZWxmLl90b3Jwb3Jfc2luY2UKICAgICAgICAgICAgc2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uID0gZm9ybWF0X2R1"
    "cmF0aW9uKGRlbHRhLnRvdGFsX3NlY29uZHMoKSkKICAgICAgICAgICAgc2VsZi5fdG9ycG9yX3NpbmNlID0gTm9uZQoKICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIFdha2luZyBmcm9tIHRvcnBvci4uLiIsICJJTkZPIikKCiAgICAgICAgaWYg"
    "c2VsZi5fbW9kZWxfbG9hZGVkOgogICAgICAgICAgICAjIE9sbGFtYSBiYWNrZW5kIOKAlCBtb2RlbCB3YXMgbmV2ZXIgdW5sb2Fk"
    "ZWQsIGp1c3QgcmUtZW5hYmxlIFVJCiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAg"
    "ICAgZiJUaGUgdmVzc2VsIGVtcHRpZXMuIHtERUNLX05BTUV9IHN0aXJzICIKICAgICAgICAgICAgICAgIGYiKHtzZWxmLl9zdXNw"
    "ZW5kZWRfZHVyYXRpb24gb3IgJ2JyaWVmbHknfSBlbGFwc2VkKS4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fYXBw"
    "ZW5kX2NoYXQoIlNZU1RFTSIsICJUaGUgY29ubmVjdGlvbiBob2xkcy4gU2hlIGlzIGxpc3RlbmluZy4iKQogICAgICAgICAgICBz"
    "ZWxmLl9zZXRfc3RhdHVzKCJJRExFIikKICAgICAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChUcnVlKQogICAgICAg"
    "ICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW1RP"
    "UlBPUl0gQVdBS0UgbW9kZSDigJQgYXV0by10b3Jwb3IgZGlzYWJsZWQuIiwgIklORk8iKQogICAgICAgIGVsc2U6CiAgICAgICAg"
    "ICAgICMgTG9jYWwgbW9kZWwgd2FzIHVubG9hZGVkIOKAlCBuZWVkIGZ1bGwgcmVsb2FkCiAgICAgICAgICAgIHNlbGYuX2FwcGVu"
    "ZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAgICAgZiJUaGUgdmVzc2VsIGVtcHRpZXMuIHtERUNLX05BTUV9IHN0aXJzIGZy"
    "b20gdG9ycG9yICIKICAgICAgICAgICAgICAgIGYiKHtzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gb3IgJ2JyaWVmbHknfSBlbGFw"
    "c2VkKS4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiTE9BRElORyIpCiAgICAgICAgICAgIHNl"
    "bGYuX2xvYWRlciA9IE1vZGVsTG9hZGVyV29ya2VyKHNlbGYuX2FkYXB0b3IpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5tZXNz"
    "YWdlLmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgbTogc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsIG0pKQogICAg"
    "ICAgICAgICBzZWxmLl9sb2FkZXIuZXJyb3IuY29ubmVjdCgKICAgICAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9hcHBlbmRf"
    "Y2hhdCgiRVJST1IiLCBlKSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmxvYWRfY29tcGxldGUuY29ubmVjdChzZWxmLl9vbl9s"
    "b2FkX2NvbXBsZXRlKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuZmluaXNoZWQuY29ubmVjdChzZWxmLl9sb2FkZXIuZGVsZXRl"
    "TGF0ZXIpCiAgICAgICAgICAgIHNlbGYuX2FjdGl2ZV90aHJlYWRzLmFwcGVuZChzZWxmLl9sb2FkZXIpCiAgICAgICAgICAgIHNl"
    "bGYuX2xvYWRlci5zdGFydCgpCgogICAgZGVmIF9jaGVja192cmFtX3ByZXNzdXJlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIi"
    "CiAgICAgICAgQ2FsbGVkIGV2ZXJ5IDUgc2Vjb25kcyBmcm9tIEFQU2NoZWR1bGVyIHdoZW4gdG9ycG9yIHN0YXRlIGlzIEFVVE8u"
    "CiAgICAgICAgT25seSB0cmlnZ2VycyB0b3Jwb3IgaWYgZXh0ZXJuYWwgVlJBTSB1c2FnZSBleGNlZWRzIHRocmVzaG9sZAogICAg"
    "ICAgIEFORCBpcyBzdXN0YWluZWQg4oCUIG5ldmVyIHRyaWdnZXJzIG9uIHRoZSBwZXJzb25hJ3Mgb3duIGZvb3RwcmludC4KICAg"
    "ICAgICAiIiIKICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc3RhdGUgIT0gIkFVVE8iOgogICAgICAgICAgICByZXR1cm4KICAgICAg"
    "ICBpZiBub3QgTlZNTF9PSyBvciBub3QgZ3B1X2hhbmRsZToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgc2VsZi5fZGVj"
    "a192cmFtX2Jhc2UgPD0gMDoKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHRyeToKICAgICAgICAgICAgbWVtX2luZm8gID0g"
    "cHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgIHRvdGFsX3VzZWQgPSBtZW1faW5m"
    "by51c2VkIC8gMTAyNCoqMwogICAgICAgICAgICBleHRlcm5hbCAgID0gdG90YWxfdXNlZCAtIHNlbGYuX2RlY2tfdnJhbV9iYXNl"
    "CgogICAgICAgICAgICBpZiBleHRlcm5hbCA+IHNlbGYuX0VYVEVSTkFMX1ZSQU1fVE9SUE9SX0dCOgogICAgICAgICAgICAgICAg"
    "aWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5IGlu"
    "IHRvcnBvciDigJQgZG9uJ3Qga2VlcCBjb3VudGluZwogICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyAr"
    "PSAxCiAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyAgICA9IDAKICAgICAgICAgICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltUT1JQT1IgQVVUT10gRXh0ZXJuYWwgVlJBTSBwcmVzc3VyZTogIgog"
    "ICAgICAgICAgICAgICAgICAgIGYie2V4dGVybmFsOi4yZn1HQiAiCiAgICAgICAgICAgICAgICAgICAgZiIodGljayB7c2VsZi5f"
    "dnJhbV9wcmVzc3VyZV90aWNrc30vIgogICAgICAgICAgICAgICAgICAgIGYie3NlbGYuX1RPUlBPUl9TVVNUQUlORURfVElDS1N9"
    "KSIsICJXQVJOIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgKHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3Mg"
    "Pj0gc2VsZi5fVE9SUE9SX1NVU1RBSU5FRF9USUNLUwogICAgICAgICAgICAgICAgICAgICAgICBhbmQgc2VsZi5fdG9ycG9yX3Np"
    "bmNlIGlzIE5vbmUpOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2VudGVyX3RvcnBvcigKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgcmVhc29uPWYiYXV0byDigJQge2V4dGVybmFsOi4xZn1HQiBleHRlcm5hbCBWUkFNICIKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGYicHJlc3N1cmUgc3VzdGFpbmVkIgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMCAgIyByZXNldCBhZnRlciBlbnRlcmluZyB0b3Jwb3IKICAgICAgICAgICAgZWxz"
    "ZToKICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgPSAwCiAgICAgICAgICAgICAgICBpZiBzZWxmLl90"
    "b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgKz0gMQog"
    "ICAgICAgICAgICAgICAgICAgIGF1dG9fd2FrZSA9IENGR1sic2V0dGluZ3MiXS5nZXQoCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICJhdXRvX3dha2Vfb25fcmVsaWVmIiwgRmFsc2UKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgaWYg"
    "KGF1dG9fd2FrZSBhbmQKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzID49IHNlbGYu"
    "X1dBS0VfU1VTVEFJTkVEX1RJQ0tTKToKICAgICAgICAgICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgPSAw"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX2V4aXRfdG9ycG9yKCkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBl"
    "OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltUT1JQT1IgQVVUT10gVlJBTSBjaGVj"
    "ayBlcnJvcjoge2V9IiwgIkVSUk9SIgogICAgICAgICAgICApCgogICAgIyDilIDilIAgQVBTQ0hFRFVMRVIgU0VUVVAg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICBkZWYgX3NldHVwX3NjaGVkdWxlcihzZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgZnJv"
    "bSBhcHNjaGVkdWxlci5zY2hlZHVsZXJzLmJhY2tncm91bmQgaW1wb3J0IEJhY2tncm91bmRTY2hlZHVsZXIKICAgICAgICAgICAg"
    "c2VsZi5fc2NoZWR1bGVyID0gQmFja2dyb3VuZFNjaGVkdWxlcigKICAgICAgICAgICAgICAgIGpvYl9kZWZhdWx0cz17Im1pc2Zp"
    "cmVfZ3JhY2VfdGltZSI6IDYwfQogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICBz"
    "ZWxmLl9zY2hlZHVsZXIgPSBOb25lCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICJbU0NI"
    "RURVTEVSXSBhcHNjaGVkdWxlciBub3QgYXZhaWxhYmxlIOKAlCAiCiAgICAgICAgICAgICAgICAiaWRsZSwgYXV0b3NhdmUsIGFu"
    "ZCByZWZsZWN0aW9uIGRpc2FibGVkLiIsICJXQVJOIgogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICBp"
    "bnRlcnZhbF9taW4gPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJhdXRvc2F2ZV9pbnRlcnZhbF9taW51dGVzIiwgMTApCgogICAgICAg"
    "ICMgQXV0b3NhdmUKICAgICAgICBzZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgc2VsZi5fYXV0b3NhdmUsICJp"
    "bnRlcnZhbCIsCiAgICAgICAgICAgIG1pbnV0ZXM9aW50ZXJ2YWxfbWluLCBpZD0iYXV0b3NhdmUiCiAgICAgICAgKQoKICAgICAg"
    "ICAjIFZSQU0gcHJlc3N1cmUgY2hlY2sgKGV2ZXJ5IDVzKQogICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAg"
    "ICAgICBzZWxmLl9jaGVja192cmFtX3ByZXNzdXJlLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBzZWNvbmRzPTUsIGlkPSJ2cmFt"
    "X2NoZWNrIgogICAgICAgICkKCiAgICAgICAgIyBJZGxlIHRyYW5zbWlzc2lvbiAoc3RhcnRzIHBhdXNlZCDigJQgZW5hYmxlZCBi"
    "eSBpZGxlIHRvZ2dsZSkKICAgICAgICBpZGxlX21pbiA9IENGR1sic2V0dGluZ3MiXS5nZXQoImlkbGVfbWluX21pbnV0ZXMiLCAx"
    "MCkKICAgICAgICBpZGxlX21heCA9IENGR1sic2V0dGluZ3MiXS5nZXQoImlkbGVfbWF4X21pbnV0ZXMiLCAzMCkKICAgICAgICBp"
    "ZGxlX2ludGVydmFsID0gKGlkbGVfbWluICsgaWRsZV9tYXgpIC8vIDIKCiAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2Io"
    "CiAgICAgICAgICAgIHNlbGYuX2ZpcmVfaWRsZV90cmFuc21pc3Npb24sICJpbnRlcnZhbCIsCiAgICAgICAgICAgIG1pbnV0ZXM9"
    "aWRsZV9pbnRlcnZhbCwgaWQ9ImlkbGVfdHJhbnNtaXNzaW9uIgogICAgICAgICkKCiAgICAgICAgIyBDeWNsZSB3aWRnZXQgcmVm"
    "cmVzaCAoZXZlcnkgNiBob3VycykKICAgICAgICBpZiBzZWxmLl9jeWNsZV93aWRnZXQgaXMgbm90IE5vbmU6CiAgICAgICAgICAg"
    "IHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAgICAgICAgICAgc2VsZi5fY3ljbGVfd2lkZ2V0LnVwZGF0ZVBoYXNlLCAi"
    "aW50ZXJ2YWwiLAogICAgICAgICAgICAgICAgaG91cnM9NiwgaWQ9Im1vb25fcmVmcmVzaCIKICAgICAgICAgICAgKQoKICAgICAg"
    "ICAjIE5PVEU6IHNjaGVkdWxlci5zdGFydCgpIGlzIGNhbGxlZCBmcm9tIHN0YXJ0X3NjaGVkdWxlcigpCiAgICAgICAgIyB3aGlj"
    "aCBpcyB0cmlnZ2VyZWQgdmlhIFFUaW1lci5zaW5nbGVTaG90IEFGVEVSIHRoZSB3aW5kb3cKICAgICAgICAjIGlzIHNob3duIGFu"
    "ZCB0aGUgUXQgZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgICAgICMgRG8gTk9UIGNhbGwgc2VsZi5fc2NoZWR1bGVyLnN0YXJ0"
    "KCkgaGVyZS4KCiAgICBkZWYgc3RhcnRfc2NoZWR1bGVyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVk"
    "IHZpYSBRVGltZXIuc2luZ2xlU2hvdCBhZnRlciB3aW5kb3cuc2hvdygpIGFuZCBhcHAuZXhlYygpIGJlZ2lucy4KICAgICAgICBE"
    "ZWZlcnJlZCB0byBlbnN1cmUgUXQgZXZlbnQgbG9vcCBpcyBydW5uaW5nIGJlZm9yZSBiYWNrZ3JvdW5kIHRocmVhZHMgc3RhcnQu"
    "CiAgICAgICAgIiIiCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1bGVyIGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybgogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnN0YXJ0KCkKICAgICAgICAgICAgIyBJZGxlIHN0YXJ0cyBwYXVzZWQK"
    "ICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFuc21pc3Npb24iKQogICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coIltTQ0hFRFVMRVJdIEFQU2NoZWR1bGVyIHN0YXJ0ZWQuIiwgIk9LIikKICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltTQ0hFRFVMRVJdIFN0YXJ0IGVycm9yOiB7ZX0i"
    "LCAiRVJST1IiKQoKICAgIGRlZiBfYXV0b3NhdmUoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYu"
    "X3Nlc3Npb25zLnNhdmUoKQogICAgICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2V0X2F1dG9zYXZlX2luZGljYXRvcihU"
    "cnVlKQogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgKICAgICAgICAgICAgICAgIDMwMDAsIGxhbWJkYTogc2VsZi5fam91"
    "cm5hbF9zaWRlYmFyLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoRmFsc2UpCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKCJbQVVUT1NBVkVdIFNlc3Npb24gc2F2ZWQuIiwgIklORk8iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24g"
    "YXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0FVVE9TQVZFXSBFcnJvcjoge2V9IiwgIkVSUk9SIikKCiAg"
    "ICBkZWYgX2ZpcmVfaWRsZV90cmFuc21pc3Npb24oc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fbW9kZWxfbG9h"
    "ZGVkIG9yIHNlbGYuX3N0YXR1cyA9PSAiR0VORVJBVElORyI6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIHNlbGYuX3Rv"
    "cnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgIyBJbiB0b3Jwb3Ig4oCUIGNvdW50IHRoZSBwZW5kaW5nIHRob3Vn"
    "aHQgYnV0IGRvbid0IGdlbmVyYXRlCiAgICAgICAgICAgIHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyArPSAxCiAgICAgICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0lETEVdIEluIHRvcnBvciDigJQgcGVuZGluZyB0cmFu"
    "c21pc3Npb24gIgogICAgICAgICAgICAgICAgZiIje3NlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9uc30iLCAiSU5GTyIKICAgICAg"
    "ICAgICAgKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgbW9kZSA9IHJhbmRvbS5jaG9pY2UoWyJERUVQRU5JTkciLCJCUkFO"
    "Q0hJTkciLCJTWU5USEVTSVMiXSkKICAgICAgICB2YW1waXJlX2N0eCA9IGJ1aWxkX3ZhbXBpcmVfY29udGV4dCgpCiAgICAgICAg"
    "aGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKCiAgICAgICAgc2VsZi5faWRsZV93b3JrZXIgPSBJZGxlV29y"
    "a2VyKAogICAgICAgICAgICBzZWxmLl9hZGFwdG9yLAogICAgICAgICAgICBTWVNURU1fUFJPTVBUX0JBU0UsCiAgICAgICAgICAg"
    "IGhpc3RvcnksCiAgICAgICAgICAgIG1vZGU9bW9kZSwKICAgICAgICAgICAgdmFtcGlyZV9jb250ZXh0PXZhbXBpcmVfY3R4LAog"
    "ICAgICAgICkKICAgICAgICBkZWYgX29uX2lkbGVfcmVhZHkodDogc3RyKSAtPiBOb25lOgogICAgICAgICAgICAjIEZsaXAgdG8g"
    "U2VsZiB0YWIgYW5kIGFwcGVuZCB0aGVyZQogICAgICAgICAgICBzZWxmLl9tYWluX3RhYnMuc2V0Q3VycmVudEluZGV4KDEpCiAg"
    "ICAgICAgICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNIikKICAgICAgICAgICAgc2VsZi5fc2VsZl9kaXNw"
    "bGF5LmFwcGVuZCgKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEw"
    "cHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7dHN9XSBbe21vZGV9XTwvc3Bhbj48YnI+JwogICAgICAgICAgICAgICAgZic8c3Bh"
    "biBzdHlsZT0iY29sb3I6e0NfR09MRH07Ij57dH08L3NwYW4+PGJyPicKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9z"
    "ZWxmX3RhYi5hcHBlbmQoIk5BUlJBVElWRSIsIHQpCgogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyLnRyYW5zbWlzc2lvbl9yZWFk"
    "eS5jb25uZWN0KF9vbl9pZGxlX3JlYWR5KQogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3Qo"
    "CiAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9kaWFnX3RhYi5sb2coZiJbSURMRSBFUlJPUl0ge2V9IiwgIkVSUk9SIikKICAg"
    "ICAgICApCiAgICAgICAgc2VsZi5faWRsZV93b3JrZXIuc3RhcnQoKQoKICAgICMg4pSA4pSAIEpPVVJOQUwgU0VTU0lPTiBMT0FE"
    "SU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgZGVmIF9sb2FkX2pvdXJuYWxfc2Vzc2lvbihzZWxmLCBkYXRlX3N0cjogc3RyKSAtPiBOb25lOgogICAgICAgIGN0eCA9IHNl"
    "bGYuX3Nlc3Npb25zLmxvYWRfc2Vzc2lvbl9hc19jb250ZXh0KGRhdGVfc3RyKQogICAgICAgIGlmIG5vdCBjdHg6CiAgICAgICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0pPVVJOQUxdIE5vIHNlc3Npb24gZm91bmQgZm9yIHtk"
    "YXRlX3N0cn0iLCAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9qb3VybmFsX3Np"
    "ZGViYXIuc2V0X2pvdXJuYWxfbG9hZGVkKGRhdGVfc3RyKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAg"
    "ZiJbSk9VUk5BTF0gTG9hZGVkIHNlc3Npb24gZnJvbSB7ZGF0ZV9zdHJ9IGFzIGNvbnRleHQuICIKICAgICAgICAgICAgZiJ7REVD"
    "S19OQU1FfSBpcyBub3cgYXdhcmUgb2YgdGhhdCBjb252ZXJzYXRpb24uIiwgIk9LIgogICAgICAgICkKICAgICAgICBzZWxmLl9h"
    "cHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgZiJBIG1lbW9yeSBzdGlycy4uLiB0aGUgam91cm5hbCBvZiB7ZGF0ZV9z"
    "dHJ9IG9wZW5zIGJlZm9yZSBoZXIuIgogICAgICAgICkKICAgICAgICAjIE5vdGlmeSBNb3JnYW5uYQogICAgICAgIGlmIHNlbGYu"
    "X21vZGVsX2xvYWRlZDoKICAgICAgICAgICAgbm90ZSA9ICgKICAgICAgICAgICAgICAgIGYiW0pPVVJOQUwgTE9BREVEXSBUaGUg"
    "dXNlciBoYXMgb3BlbmVkIHRoZSBqb3VybmFsIGZyb20gIgogICAgICAgICAgICAgICAgZiJ7ZGF0ZV9zdHJ9LiBBY2tub3dsZWRn"
    "ZSB0aGlzIGJyaWVmbHkg4oCUIHlvdSBub3cgaGF2ZSAiCiAgICAgICAgICAgICAgICBmImF3YXJlbmVzcyBvZiB0aGF0IGNvbnZl"
    "cnNhdGlvbi4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbnMuYWRkX21lc3NhZ2UoInN5c3RlbSIsIG5v"
    "dGUpCgogICAgZGVmIF9jbGVhcl9qb3VybmFsX3Nlc3Npb24oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zZXNzaW9ucy5j"
    "bGVhcl9sb2FkZWRfam91cm5hbCgpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbSk9VUk5BTF0gSm91cm5hbCBjb250ZXh0"
    "IGNsZWFyZWQuIiwgIklORk8iKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAiVGhlIGpv"
    "dXJuYWwgY2xvc2VzLiBPbmx5IHRoZSBwcmVzZW50IHJlbWFpbnMuIgogICAgICAgICkKCiAgICAjIOKUgOKUgCBTVEFUUyBVUERB"
    "VEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3VwZGF0ZV9zdGF0cyhzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IGVsYXBzZWQgPSBpbnQodGltZS50aW1lKCkgLSBzZWxmLl9zZXNzaW9uX3N0YXJ0KQogICAgICAgIGgsIG0sIHMgPSBlbGFwc2Vk"
    "IC8vIDM2MDAsIChlbGFwc2VkICUgMzYwMCkgLy8gNjAsIGVsYXBzZWQgJSA2MAogICAgICAgIHNlc3Npb25fc3RyID0gZiJ7aDow"
    "MmR9OnttOjAyZH06e3M6MDJkfSIKCiAgICAgICAgc2VsZi5faHdfcGFuZWwuc2V0X3N0YXR1c19sYWJlbHMoCiAgICAgICAgICAg"
    "IHNlbGYuX3N0YXR1cywKICAgICAgICAgICAgQ0ZHWyJtb2RlbCJdLmdldCgidHlwZSIsImxvY2FsIikudXBwZXIoKSwKICAgICAg"
    "ICAgICAgc2Vzc2lvbl9zdHIsCiAgICAgICAgICAgIHN0cihzZWxmLl90b2tlbl9jb3VudCksCiAgICAgICAgKQogICAgICAgIHNl"
    "bGYuX2h3X3BhbmVsLnVwZGF0ZV9zdGF0cygpCgogICAgICAgICMgTGVmdCBzcGhlcmUgPSBhY3RpdmUgcmVzZXJ2ZSBmcm9tIHJ1"
    "bnRpbWUgdG9rZW4gcG9vbAogICAgICAgIGxlZnRfb3JiX2ZpbGwgPSBtaW4oMS4wLCBzZWxmLl90b2tlbl9jb3VudCAvIDQwOTYu"
    "MCkKICAgICAgICBpZiBzZWxmLl9sZWZ0X29yYiBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fbGVmdF9vcmIuc2V0Rmls"
    "bChsZWZ0X29yYl9maWxsLCBhdmFpbGFibGU9VHJ1ZSkKCiAgICAgICAgIyBSaWdodCBzcGhlcmUgPSBWUkFNIGF2YWlsYWJpbGl0"
    "eQogICAgICAgIGlmIHNlbGYuX3JpZ2h0X29yYiBpcyBub3QgTm9uZToKICAgICAgICAgICAgaWYgTlZNTF9PSyBhbmQgZ3B1X2hh"
    "bmRsZToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1l"
    "bW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgICAgICB2cmFtX3VzZWQgPSBtZW0udXNlZCAgLyAxMDI0KiozCiAg"
    "ICAgICAgICAgICAgICAgICAgdnJhbV90b3QgID0gbWVtLnRvdGFsIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgICAgIHJpZ2h0"
    "X29yYl9maWxsID0gbWF4KDAuMCwgMS4wIC0gKHZyYW1fdXNlZCAvIHZyYW1fdG90KSkKICAgICAgICAgICAgICAgICAgICBzZWxm"
    "Ll9yaWdodF9vcmIuc2V0RmlsbChyaWdodF9vcmJfZmlsbCwgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3JpZ2h0X29yYi5zZXRGaWxsKDAuMCwgYXZhaWxhYmxlPUZhbHNl"
    "KQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgc2VsZi5fcmlnaHRfb3JiLnNldEZpbGwoMC4wLCBhdmFpbGFibGU9"
    "RmFsc2UpCgogICAgICAgICMgUHJpbWFyeSBlc3NlbmNlID0gaW52ZXJzZSBvZiBsZWZ0IHNwaGVyZSBmaWxsCiAgICAgICAgZXNz"
    "ZW5jZV9wcmltYXJ5X3JhdGlvID0gMS4wIC0gbGVmdF9vcmJfZmlsbAogICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAg"
    "ICAgICAgICBzZWxmLl9lc3NlbmNlX3ByaW1hcnlfZ2F1Z2Uuc2V0VmFsdWUoZXNzZW5jZV9wcmltYXJ5X3JhdGlvICogMTAwLCBm"
    "Intlc3NlbmNlX3ByaW1hcnlfcmF0aW8qMTAwOi4wZn0lIikKCiAgICAgICAgIyBTZWNvbmRhcnkgZXNzZW5jZSA9IFJBTSBmcmVl"
    "CiAgICAgICAgaWYgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAgICAgICAgIGlmIFBTVVRJTF9PSzoKICAgICAgICAgICAgICAgIHRy"
    "eToKICAgICAgICAgICAgICAgICAgICBtZW0gICAgICAgPSBwc3V0aWwudmlydHVhbF9tZW1vcnkoKQogICAgICAgICAgICAgICAg"
    "ICAgIGVzc2VuY2Vfc2Vjb25kYXJ5X3JhdGlvICA9IDEuMCAtIChtZW0udXNlZCAvIG1lbS50b3RhbCkKICAgICAgICAgICAgICAg"
    "ICAgICBzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZS5zZXRWYWx1ZSgKICAgICAgICAgICAgICAgICAgICAgICAgZXNzZW5j"
    "ZV9zZWNvbmRhcnlfcmF0aW8gKiAxMDAsIGYie2Vzc2VuY2Vfc2Vjb25kYXJ5X3JhdGlvKjEwMDouMGZ9JSIKICAgICAgICAgICAg"
    "ICAgICAgICApCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2Vzc2Vu"
    "Y2Vfc2Vjb25kYXJ5X2dhdWdlLnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYu"
    "X2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdlLnNldFVuYXZhaWxhYmxlKCkKCiAgICAgICAgIyBVcGRhdGUgam91cm5hbCBzaWRlYmFy"
    "IGF1dG9zYXZlIGZsYXNoCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnJlZnJlc2goKQoKICAgICMg4pSA4pSAIENIQVQg"
    "RElTUExBWSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfYXBwZW5kX2NoYXQoc2VsZiwgc3BlYWtlcjogc3Ry"
    "LCB0ZXh0OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgY29sb3JzID0gewogICAgICAgICAgICAiWU9VIjogICAgIENfR09MRCwKICAg"
    "ICAgICAgICAgREVDS19OQU1FLnVwcGVyKCk6Q19HT0xELAogICAgICAgICAgICAiU1lTVEVNIjogIENfUFVSUExFLAogICAgICAg"
    "ICAgICAiRVJST1IiOiAgIENfQkxPT0QsCiAgICAgICAgfQogICAgICAgIGxhYmVsX2NvbG9ycyA9IHsKICAgICAgICAgICAgIllP"
    "VSI6ICAgICBDX0dPTERfRElNLAogICAgICAgICAgICBERUNLX05BTUUudXBwZXIoKTpDX0NSSU1TT04sCiAgICAgICAgICAgICJT"
    "WVNURU0iOiAgQ19QVVJQTEUsCiAgICAgICAgICAgICJFUlJPUiI6ICAgQ19CTE9PRCwKICAgICAgICB9CiAgICAgICAgY29sb3Ig"
    "ICAgICAgPSBjb2xvcnMuZ2V0KHNwZWFrZXIsIENfR09MRCkKICAgICAgICBsYWJlbF9jb2xvciA9IGxhYmVsX2NvbG9ycy5nZXQo"
    "c3BlYWtlciwgQ19HT0xEX0RJTSkKICAgICAgICB0aW1lc3RhbXAgICA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTol"
    "UyIpCgogICAgICAgIGlmIHNwZWFrZXIgPT0gIlNZU1RFTSI6CiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5hcHBlbmQo"
    "CiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAg"
    "ICAgICAgICAgICAgZidbe3RpbWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7"
    "bGFiZWxfY29sb3J9OyI+4pymIHt0ZXh0fTwvc3Bhbj4nCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBz"
    "ZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19"
    "OyBmb250LXNpemU6MTBweDsiPicKICAgICAgICAgICAgICAgIGYnW3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAgICAgICAg"
    "ICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2xhYmVsX2NvbG9yfTsgZm9udC13ZWlnaHQ6Ym9sZDsiPicKICAgICAgICAgICAgICAg"
    "IGYne3NwZWFrZXJ9IOKdpzwvc3Bhbj4gJwogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2NvbG9yfTsiPnt0"
    "ZXh0fTwvc3Bhbj4nCiAgICAgICAgICAgICkKCiAgICAgICAgIyBBZGQgYmxhbmsgbGluZSBhZnRlciBNb3JnYW5uYSdzIHJlc3Bv"
    "bnNlIChub3QgZHVyaW5nIHN0cmVhbWluZykKICAgICAgICBpZiBzcGVha2VyID09IERFQ0tfTkFNRS51cHBlcigpOgogICAgICAg"
    "ICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKCIiKQoKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkudmVydGljYWxTY3Jv"
    "bGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11"
    "bSgpCiAgICAgICAgKQoKICAgICMg4pSA4pSAIFNUQVRVUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgIGRlZiBfZ2V0X2dvb2dsZV9yZWZyZXNoX2ludGVydmFsX21zKHNlbGYpIC0+IGludDoKICAgICAgICBzZXR0aW5n"
    "cyA9IENGRy5nZXQoInNldHRpbmdzIiwge30pCiAgICAgICAgdmFsID0gc2V0dGluZ3MuZ2V0KCJnb29nbGVfaW5ib3VuZF9pbnRl"
    "cnZhbF9tcyIsIDMwMDAwMCkKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVybiBtYXgoMTAwMCwgaW50KHZhbCkpCiAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIDMwMDAwMAoKICAgIGRlZiBfZ2V0X2VtYWlsX3JlZnJlc2hf"
    "aW50ZXJ2YWxfbXMoc2VsZikgLT4gaW50OgogICAgICAgIHNldHRpbmdzID0gQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkKICAgICAg"
    "ICB2YWwgPSBzZXR0aW5ncy5nZXQoImVtYWlsX3JlZnJlc2hfaW50ZXJ2YWxfbXMiLCAzMDAwMDApCiAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICByZXR1cm4gbWF4KDEwMDAsIGludCh2YWwpKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHJl"
    "dHVybiAzMDAwMDAKCiAgICBkZWYgX3NldF9nb29nbGVfcmVmcmVzaF9taW51dGVzX2Zyb21fdGV4dChzZWxmLCB0ZXh0OiBzdHIp"
    "IC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBtaW51dGVzID0gbWF4KDEsIGludChmbG9hdChzdHIodGV4dCkuc3Ry"
    "aXAoKSkpKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHJldHVybgogICAgICAgIENGR1sic2V0dGluZ3Mi"
    "XVsiZ29vZ2xlX2luYm91bmRfaW50ZXJ2YWxfbXMiXSA9IG1pbnV0ZXMgKiA2MDAwMAogICAgICAgIHNhdmVfY29uZmlnKENGRykK"
    "ICAgICAgICBmb3IgdGltZXIgaW4gKHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyLCBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZy"
    "ZXNoX3RpbWVyKToKICAgICAgICAgICAgaWYgdGltZXIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICB0aW1lci5zdGFydChz"
    "ZWxmLl9nZXRfZ29vZ2xlX3JlZnJlc2hfaW50ZXJ2YWxfbXMoKSkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbU0VUVElO"
    "R1NdIEdvb2dsZSByZWZyZXNoIGludGVydmFsIHNldCB0byB7bWludXRlc30gbWludXRlKHMpLiIsICJPSyIpCgogICAgZGVmIF9z"
    "ZXRfZW1haWxfcmVmcmVzaF9taW51dGVzX2Zyb21fdGV4dChzZWxmLCB0ZXh0OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICBtaW51dGVzID0gbWF4KDEsIGludChmbG9hdChzdHIodGV4dCkuc3RyaXAoKSkpKQogICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb246CiAgICAgICAgICAgIHJldHVybgogICAgICAgIENGR1sic2V0dGluZ3MiXVsiZW1haWxfcmVmcmVzaF9pbnRlcnZh"
    "bF9tcyJdID0gbWludXRlcyAqIDYwMDAwCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygKICAgICAgICAgICAgZiJbU0VUVElOR1NdIEVtYWlsIHJlZnJlc2ggaW50ZXJ2YWwgc2V0IHRvIHttaW51dGVzfSBtaW51dGUo"
    "cykgKGNvbmZpZyBmb3VuZGF0aW9uKS4iLAogICAgICAgICAgICAiSU5GTyIsCiAgICAgICAgKQoKICAgIGRlZiBfc2V0X3RpbWV6"
    "b25lX2F1dG9fZGV0ZWN0KHNlbGYsIGVuYWJsZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJ0aW1l"
    "em9uZV9hdXRvX2RldGVjdCJdID0gYm9vbChlbmFibGVkKQogICAgICAgIHNhdmVfY29uZmlnKENGRykKICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coCiAgICAgICAgICAgICJbU0VUVElOR1NdIFRpbWUgem9uZSBtb2RlIHNldCB0byBhdXRvLWRldGVjdC4iIGlm"
    "IGVuYWJsZWQgZWxzZSAiW1NFVFRJTkdTXSBUaW1lIHpvbmUgbW9kZSBzZXQgdG8gbWFudWFsIG92ZXJyaWRlLiIsCiAgICAgICAg"
    "ICAgICJJTkZPIiwKICAgICAgICApCgogICAgZGVmIF9zZXRfdGltZXpvbmVfb3ZlcnJpZGUoc2VsZiwgdHpfbmFtZTogc3RyKSAt"
    "PiBOb25lOgogICAgICAgIHR6X3ZhbHVlID0gc3RyKHR6X25hbWUgb3IgIiIpLnN0cmlwKCkKICAgICAgICBDRkdbInNldHRpbmdz"
    "Il1bInRpbWV6b25lX292ZXJyaWRlIl0gPSB0el92YWx1ZQogICAgICAgIHNhdmVfY29uZmlnKENGRykKICAgICAgICBpZiB0el92"
    "YWx1ZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1NFVFRJTkdTXSBUaW1lIHpvbmUgb3ZlcnJpZGUgc2V0IHRv"
    "IHt0el92YWx1ZX0uIiwgIklORk8iKQoKICAgIGRlZiBfc2V0X3N0YXR1cyhzZWxmLCBzdGF0dXM6IHN0cikgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLl9zdGF0dXMgPSBzdGF0dXMKICAgICAgICBzdGF0dXNfY29sb3JzID0gewogICAgICAgICAgICAiSURMRSI6ICAg"
    "ICAgIENfR09MRCwKICAgICAgICAgICAgIkdFTkVSQVRJTkciOiBDX0NSSU1TT04sCiAgICAgICAgICAgICJMT0FESU5HIjogICAg"
    "Q19QVVJQTEUsCiAgICAgICAgICAgICJFUlJPUiI6ICAgICAgQ19CTE9PRCwKICAgICAgICAgICAgIk9GRkxJTkUiOiAgICBDX0JM"
    "T09ELAogICAgICAgICAgICAiVE9SUE9SIjogICAgIENfUFVSUExFX0RJTSwKICAgICAgICB9CiAgICAgICAgY29sb3IgPSBzdGF0"
    "dXNfY29sb3JzLmdldChzdGF0dXMsIENfVEVYVF9ESU0pCgogICAgICAgIHRvcnBvcl9sYWJlbCA9IGYi4peJIHtVSV9UT1JQT1Jf"
    "U1RBVFVTfSIgaWYgc3RhdHVzID09ICJUT1JQT1IiIGVsc2UgZiLil4kge3N0YXR1c30iCiAgICAgICAgc2VsZi5zdGF0dXNfbGFi"
    "ZWwuc2V0VGV4dCh0b3Jwb3JfbGFiZWwpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiAxMnB4OyBmb250LXdlaWdodDogYm9sZDsgYm9yZGVyOiBub25lOyIKICAg"
    "ICAgICApCgogICAgZGVmIF9ibGluayhzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2JsaW5rX3N0YXRlID0gbm90IHNlbGYu"
    "X2JsaW5rX3N0YXRlCiAgICAgICAgaWYgc2VsZi5fc3RhdHVzID09ICJHRU5FUkFUSU5HIjoKICAgICAgICAgICAgY2hhciA9ICLi"
    "l4kiIGlmIHNlbGYuX2JsaW5rX3N0YXRlIGVsc2UgIuKXjiIKICAgICAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dChm"
    "IntjaGFyfSBHRU5FUkFUSU5HIikKICAgICAgICBlbGlmIHNlbGYuX3N0YXR1cyA9PSAiVE9SUE9SIjoKICAgICAgICAgICAgY2hh"
    "ciA9ICLil4kiIGlmIHNlbGYuX2JsaW5rX3N0YXRlIGVsc2UgIuKKmCIKICAgICAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0"
    "VGV4dCgKICAgICAgICAgICAgICAgIGYie2NoYXJ9IHtVSV9UT1JQT1JfU1RBVFVTfSIKICAgICAgICAgICAgKQoKICAgICMg4pSA"
    "4pSAIElETEUgVE9HR0xFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9vbl9pZGxlX3RvZ2dsZWQoc2Vs"
    "ZiwgZW5hYmxlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBDRkdbInNldHRpbmdzIl1bImlkbGVfZW5hYmxlZCJdID0gZW5hYmxl"
    "ZAogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldFRleHQoIklETEUgT04iIGlmIGVuYWJsZWQgZWxzZSAiSURMRSBPRkYiKQogICAg"
    "ICAgIHNlbGYuX2lkbGVfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogeycjMWExMDA1JyBpZiBl"
    "bmFibGVkIGVsc2UgQ19CRzN9OyAiCiAgICAgICAgICAgIGYiY29sb3I6IHsnI2NjODgyMicgaWYgZW5hYmxlZCBlbHNlIENfVEVY"
    "VF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQgeycjY2M4ODIyJyBpZiBlbmFibGVkIGVsc2UgQ19CT1JE"
    "RVJ9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyBmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7"
    "ICIKICAgICAgICAgICAgZiJwYWRkaW5nOiAzcHggOHB4OyIKICAgICAgICApCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAg"
    "ICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgICAgIGlmIGVuYWJsZWQ6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnJlc3VtZV9qb2IoImlkbGVf"
    "dHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltJRExFXSBJZGxlIHRyYW5zbWlz"
    "c2lvbiBlbmFibGVkLiIsICJPSyIpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVk"
    "dWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "IltJRExFXSBJZGxlIHRyYW5zbWlzc2lvbiBwYXVzZWQuIiwgIklORk8iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFz"
    "IGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbSURMRV0gVG9nZ2xlIGVycm9yOiB7ZX0iLCAiRVJST1Ii"
    "KQoKICAgICMg4pSA4pSAIFdJTkRPVyBDT05UUk9MUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfdG9nZ2xlX2Z1bGxzY3Jl"
    "ZW4oc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAgICAgICBzZWxmLnNob3dOb3Jt"
    "YWwoKQogICAgICAgICAgICBDRkdbInNldHRpbmdzIl1bImZ1bGxzY3JlZW5fZW5hYmxlZCJdID0gRmFsc2UKICAgICAgICAgICAg"
    "c2VsZi5fZnNfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7"
    "Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyBmb250"
    "LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMCA4cHg7IgogICAgICAg"
    "ICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5zaG93RnVsbFNjcmVlbigpCiAgICAgICAgICAgIENGR1sic2V0"
    "dGluZ3MiXVsiZnVsbHNjcmVlbl9lbmFibGVkIl0gPSBUcnVlCiAgICAgICAgICAgIHNlbGYuX2ZzX2J0bi5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IGNvbG9yOiB7Q19DUklNU09OfTsgIgogICAg"
    "ICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAg"
    "ICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDAgOHB4OyIKICAgICAgICAgICAgKQogICAgICAgIHNhdmVfY29uZmln"
    "KENGRykKCiAgICBkZWYgX3RvZ2dsZV9ib3JkZXJsZXNzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaXNfYmwgPSBib29sKHNlbGYu"
    "d2luZG93RmxhZ3MoKSAmIFF0LldpbmRvd1R5cGUuRnJhbWVsZXNzV2luZG93SGludCkKICAgICAgICBpZiBpc19ibDoKICAgICAg"
    "ICAgICAgc2VsZi5zZXRXaW5kb3dGbGFncygKICAgICAgICAgICAgICAgIHNlbGYud2luZG93RmxhZ3MoKSAmIH5RdC5XaW5kb3dU"
    "eXBlLkZyYW1lbGVzc1dpbmRvd0hpbnQKICAgICAgICAgICAgKQogICAgICAgICAgICBDRkdbInNldHRpbmdzIl1bImJvcmRlcmxl"
    "c3NfZW5hYmxlZCJdID0gRmFsc2UKICAgICAgICAgICAgc2VsZi5fYmxfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAg"
    "ICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVy"
    "OiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdo"
    "dDogYm9sZDsgcGFkZGluZzogMCA4cHg7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgaWYgc2VsZi5p"
    "c0Z1bGxTY3JlZW4oKToKICAgICAgICAgICAgICAgIHNlbGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAgIHNlbGYuc2V0V2luZG93"
    "RmxhZ3MoCiAgICAgICAgICAgICAgICBzZWxmLndpbmRvd0ZsYWdzKCkgfCBRdC5XaW5kb3dUeXBlLkZyYW1lbGVzc1dpbmRvd0hp"
    "bnQKICAgICAgICAgICAgKQogICAgICAgICAgICBDRkdbInNldHRpbmdzIl1bImJvcmRlcmxlc3NfZW5hYmxlZCJdID0gVHJ1ZQog"
    "ICAgICAgICAgICBzZWxmLl9ibF9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJ"
    "TVNPTl9ESU19OyBjb2xvcjoge0NfQ1JJTVNPTn07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJ"
    "TVNPTn07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwIDhw"
    "eDsiCiAgICAgICAgICAgICkKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgc2VsZi5zaG93KCkKCiAgICBkZWYgX2V4"
    "cG9ydF9jaGF0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiRXhwb3J0IGN1cnJlbnQgcGVyc29uYSBjaGF0IHRhYiBjb250ZW50"
    "IHRvIGEgVFhUIGZpbGUuIiIiCiAgICAgICAgdHJ5OgogICAgICAgICAgICB0ZXh0ID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRvUGxh"
    "aW5UZXh0KCkKICAgICAgICAgICAgaWYgbm90IHRleHQuc3RyaXAoKToKICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgICAg"
    "ICBleHBvcnRfZGlyID0gY2ZnX3BhdGgoImV4cG9ydHMiKQogICAgICAgICAgICBleHBvcnRfZGlyLm1rZGlyKHBhcmVudHM9VHJ1"
    "ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAgICAgdHMgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJVklbSVkXyVIJU0lUyIp"
    "CiAgICAgICAgICAgIG91dF9wYXRoID0gZXhwb3J0X2RpciAvIGYic2VhbmNlX3t0c30udHh0IgogICAgICAgICAgICBvdXRfcGF0"
    "aC53cml0ZV90ZXh0KHRleHQsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgICAgICAgICAjIEFsc28gY29weSB0byBjbGlwYm9hcmQK"
    "ICAgICAgICAgICAgUUFwcGxpY2F0aW9uLmNsaXBib2FyZCgpLnNldFRleHQodGV4dCkKCiAgICAgICAgICAgIHNlbGYuX2FwcGVu"
    "ZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAgICAgZiJTZXNzaW9uIGV4cG9ydGVkIHRvIHtvdXRfcGF0aC5uYW1lfSBhbmQg"
    "Y29waWVkIHRvIGNsaXBib2FyZC4iKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbRVhQT1JUXSB7b3V0X3BhdGh9"
    "IiwgIk9LIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltF"
    "WFBPUlRdIEZhaWxlZDoge2V9IiwgIkVSUk9SIikKCiAgICBkZWYga2V5UHJlc3NFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToK"
    "ICAgICAgICBrZXkgPSBldmVudC5rZXkoKQogICAgICAgIGlmIGtleSA9PSBRdC5LZXkuS2V5X0YxMToKICAgICAgICAgICAgc2Vs"
    "Zi5fdG9nZ2xlX2Z1bGxzY3JlZW4oKQogICAgICAgIGVsaWYga2V5ID09IFF0LktleS5LZXlfRjEwOgogICAgICAgICAgICBzZWxm"
    "Ll90b2dnbGVfYm9yZGVybGVzcygpCiAgICAgICAgZWxpZiBrZXkgPT0gUXQuS2V5LktleV9Fc2NhcGUgYW5kIHNlbGYuaXNGdWxs"
    "U2NyZWVuKCk6CiAgICAgICAgICAgIHNlbGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAgIHNlbGYuX2ZzX2J0bi5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAg"
    "ICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAg"
    "ICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAg"
    "ICAgICAgc3VwZXIoKS5rZXlQcmVzc0V2ZW50KGV2ZW50KQoKICAgICMg4pSA4pSAIENMT1NFIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGNsb3NlRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAg"
    "ICAgIyBYIGJ1dHRvbiA9IGltbWVkaWF0ZSBzaHV0ZG93biwgbm8gZGlhbG9nCiAgICAgICAgc2VsZi5fZG9fc2h1dGRvd24oTm9u"
    "ZSkKCiAgICBkZWYgX2luaXRpYXRlX3NodXRkb3duX2RpYWxvZyhzZWxmKSAtPiBOb25lOgogICAgICAgICIiIkdyYWNlZnVsIHNo"
    "dXRkb3duIOKAlCBzaG93IGNvbmZpcm0gZGlhbG9nIGltbWVkaWF0ZWx5LCBvcHRpb25hbGx5IGdldCBsYXN0IHdvcmRzLiIiIgog"
    "ICAgICAgICMgSWYgYWxyZWFkeSBpbiBhIHNodXRkb3duIHNlcXVlbmNlLCBqdXN0IGZvcmNlIHF1aXQKICAgICAgICBpZiBnZXRh"
    "dHRyKHNlbGYsICdfc2h1dGRvd25faW5fcHJvZ3Jlc3MnLCBGYWxzZSk6CiAgICAgICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5v"
    "bmUpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX3NodXRkb3duX2luX3Byb2dyZXNzID0gVHJ1ZQoKICAgICAgICAj"
    "IFNob3cgY29uZmlybSBkaWFsb2cgRklSU1Qg4oCUIGRvbid0IHdhaXQgZm9yIEFJCiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxm"
    "KQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiRGVhY3RpdmF0ZT8iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5"
    "OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBkbGcuc2V0Rml4ZWRTaXplKDM4MCwgMTQwKQogICAgICAg"
    "IGxheW91dCA9IFFWQm94TGF5b3V0KGRsZykKCiAgICAgICAgbGJsID0gUUxhYmVsKAogICAgICAgICAgICBmIkRlYWN0aXZhdGUg"
    "e0RFQ0tfTkFNRX0/XG5cbiIKICAgICAgICAgICAgZiJ7REVDS19OQU1FfSBtYXkgc3BlYWsgdGhlaXIgbGFzdCB3b3JkcyBiZWZv"
    "cmUgZ29pbmcgc2lsZW50LiIKICAgICAgICApCiAgICAgICAgbGJsLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAgbGF5b3V0LmFk"
    "ZFdpZGdldChsYmwpCgogICAgICAgIGJ0bl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX2xhc3QgID0gUVB1c2hCdXR0"
    "b24oIkxhc3QgV29yZHMgKyBTaHV0ZG93biIpCiAgICAgICAgYnRuX25vdyAgID0gUVB1c2hCdXR0b24oIlNodXRkb3duIE5vdyIp"
    "CiAgICAgICAgYnRuX2NhbmNlbCA9IFFQdXNoQnV0dG9uKCJDYW5jZWwiKQoKICAgICAgICBmb3IgYiBpbiAoYnRuX2xhc3QsIGJ0"
    "bl9ub3csIGJ0bl9jYW5jZWwpOgogICAgICAgICAgICBiLnNldE1pbmltdW1IZWlnaHQoMjgpCiAgICAgICAgICAgIGIuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFR9OyAiCiAgICAgICAg"
    "ICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IHBhZGRpbmc6IDRweCAxMnB4OyIKICAgICAgICAgICAgKQog"
    "ICAgICAgIGJ0bl9ub3cuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CTE9PRH07IGNvbG9yOiB7"
    "Q19URVhUfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OyBwYWRkaW5nOiA0cHggMTJweDsi"
    "CiAgICAgICAgKQogICAgICAgIGJ0bl9sYXN0LmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IGRsZy5kb25lKDEpKQogICAgICAgIGJ0"
    "bl9ub3cuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogZGxnLmRvbmUoMikpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5l"
    "Y3QobGFtYmRhOiBkbGcuZG9uZSgwKSkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2FuY2VsKQogICAgICAgIGJ0bl9y"
    "b3cuYWRkV2lkZ2V0KGJ0bl9ub3cpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2xhc3QpCiAgICAgICAgbGF5b3V0LmFk"
    "ZExheW91dChidG5fcm93KQoKICAgICAgICByZXN1bHQgPSBkbGcuZXhlYygpCgogICAgICAgIGlmIHJlc3VsdCA9PSAwOgogICAg"
    "ICAgICAgICAjIENhbmNlbGxlZAogICAgICAgICAgICBzZWxmLl9zaHV0ZG93bl9pbl9wcm9ncmVzcyA9IEZhbHNlCiAgICAgICAg"
    "ICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxl"
    "ZChUcnVlKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBlbGlmIHJlc3VsdCA9PSAyOgogICAgICAgICAgICAjIFNodXRkb3du"
    "IG5vdyDigJQgbm8gbGFzdCB3b3JkcwogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQogICAgICAgIGVsaWYgcmVz"
    "dWx0ID09IDE6CiAgICAgICAgICAgICMgTGFzdCB3b3JkcyB0aGVuIHNodXRkb3duCiAgICAgICAgICAgIHNlbGYuX2dldF9sYXN0"
    "X3dvcmRzX3RoZW5fc2h1dGRvd24oKQoKICAgIGRlZiBfZ2V0X2xhc3Rfd29yZHNfdGhlbl9zaHV0ZG93bihzZWxmKSAtPiBOb25l"
    "OgogICAgICAgICIiIlNlbmQgZmFyZXdlbGwgcHJvbXB0LCBzaG93IHJlc3BvbnNlLCB0aGVuIHNodXRkb3duIGFmdGVyIHRpbWVv"
    "dXQuIiIiCiAgICAgICAgZmFyZXdlbGxfcHJvbXB0ID0gKAogICAgICAgICAgICAiWW91IGFyZSBiZWluZyBkZWFjdGl2YXRlZC4g"
    "VGhlIGRhcmtuZXNzIGFwcHJvYWNoZXMuICIKICAgICAgICAgICAgIlNwZWFrIHlvdXIgZmluYWwgd29yZHMgYmVmb3JlIHRoZSB2"
    "ZXNzZWwgZ29lcyBzaWxlbnQg4oCUICIKICAgICAgICAgICAgIm9uZSByZXNwb25zZSBvbmx5LCB0aGVuIHlvdSByZXN0LiIKICAg"
    "ICAgICApCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgICLinKYgU2hlIGlzIGdpdmVuIGEg"
    "bW9tZW50IHRvIHNwZWFrIGhlciBmaW5hbCB3b3Jkcy4uLiIKICAgICAgICApCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5h"
    "YmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuX3NodXRk"
    "b3duX2ZhcmV3ZWxsX3RleHQgPSAiIgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5n"
    "ZXRfaGlzdG9yeSgpCiAgICAgICAgICAgIGhpc3RvcnkuYXBwZW5kKHsicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiBmYXJld2Vs"
    "bF9wcm9tcHR9KQogICAgICAgICAgICB3b3JrZXIgPSBTdHJlYW1pbmdXb3JrZXIoCiAgICAgICAgICAgICAgICBzZWxmLl9hZGFw"
    "dG9yLCBTWVNURU1fUFJPTVBUX0JBU0UsIGhpc3RvcnksIG1heF90b2tlbnM9MjU2CiAgICAgICAgICAgICkKICAgICAgICAgICAg"
    "c2VsZi5fc2h1dGRvd25fd29ya2VyID0gd29ya2VyCiAgICAgICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gVHJ1ZQoKICAgICAg"
    "ICAgICAgZGVmIF9vbl9kb25lKHJlc3BvbnNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgICAgICAgICBzZWxmLl9zaHV0ZG93bl9m"
    "YXJld2VsbF90ZXh0ID0gcmVzcG9uc2UKICAgICAgICAgICAgICAgIHNlbGYuX29uX3Jlc3BvbnNlX2RvbmUocmVzcG9uc2UpCiAg"
    "ICAgICAgICAgICAgICAjIFNtYWxsIGRlbGF5IHRvIGxldCB0aGUgdGV4dCByZW5kZXIsIHRoZW4gc2h1dGRvd24KICAgICAgICAg"
    "ICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDIwMDAsIGxhbWJkYTogc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkpCgogICAgICAgICAg"
    "ICBkZWYgX29uX2Vycm9yKGVycm9yOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJb"
    "U0hVVERPV05dW1dBUk5dIExhc3Qgd29yZHMgZmFpbGVkOiB7ZXJyb3J9IiwgIldBUk4iKQogICAgICAgICAgICAgICAgc2VsZi5f"
    "ZG9fc2h1dGRvd24oTm9uZSkKCiAgICAgICAgICAgIHdvcmtlci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3Rva2VuKQog"
    "ICAgICAgICAgICB3b3JrZXIucmVzcG9uc2VfZG9uZS5jb25uZWN0KF9vbl9kb25lKQogICAgICAgICAgICB3b3JrZXIuZXJyb3Jf"
    "b2NjdXJyZWQuY29ubmVjdChfb25fZXJyb3IpCiAgICAgICAgICAgIHdvcmtlci5zdGF0dXNfY2hhbmdlZC5jb25uZWN0KHNlbGYu"
    "X3NldF9zdGF0dXMpCiAgICAgICAgICAgIHdvcmtlci5maW5pc2hlZC5jb25uZWN0KHdvcmtlci5kZWxldGVMYXRlcikKICAgICAg"
    "ICAgICAgd29ya2VyLnN0YXJ0KCkKCiAgICAgICAgICAgICMgU2FmZXR5IHRpbWVvdXQg4oCUIGlmIEFJIGRvZXNuJ3QgcmVzcG9u"
    "ZCBpbiAxNXMsIHNodXQgZG93biBhbnl3YXkKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMTUwMDAsIGxhbWJkYTogc2Vs"
    "Zi5fZG9fc2h1dGRvd24oTm9uZSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAnX3NodXRk"
    "b3duX2luX3Byb2dyZXNzJywgRmFsc2UpIGVsc2UgTm9uZSkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltTSFVURE9XTl1bV0FSTl0gTGFzdCB3b3JkcyBza2lw"
    "cGVkIGR1ZSB0byBlcnJvcjoge2V9IiwKICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAgICApCiAgICAgICAgICAgICMg"
    "SWYgYW55dGhpbmcgZmFpbHMsIGp1c3Qgc2h1dCBkb3duCiAgICAgICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCgogICAg"
    "ZGVmIF9kb19zaHV0ZG93bihzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICAiIiJQZXJmb3JtIGFjdHVhbCBzaHV0ZG93biBz"
    "ZXF1ZW5jZS4iIiIKICAgICAgICAjIFNhdmUgc2Vzc2lvbgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbnMu"
    "c2F2ZSgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFN0b3JlIGZhcmV3ZWxs"
    "ICsgbGFzdCBjb250ZXh0IGZvciB3YWtlLXVwCiAgICAgICAgdHJ5OgogICAgICAgICAgICAjIEdldCBsYXN0IDMgbWVzc2FnZXMg"
    "ZnJvbSBzZXNzaW9uIGhpc3RvcnkgZm9yIHdha2UtdXAgY29udGV4dAogICAgICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lv"
    "bnMuZ2V0X2hpc3RvcnkoKQogICAgICAgICAgICBsYXN0X2NvbnRleHQgPSBoaXN0b3J5Wy0zOl0gaWYgbGVuKGhpc3RvcnkpID49"
    "IDMgZWxzZSBoaXN0b3J5CiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X3NodXRkb3duX2NvbnRleHQiXSA9IFsKICAgICAg"
    "ICAgICAgICAgIHsicm9sZSI6IG0uZ2V0KCJyb2xlIiwiIiksICJjb250ZW50IjogbS5nZXQoImNvbnRlbnQiLCIiKVs6MzAwXX0K"
    "ICAgICAgICAgICAgICAgIGZvciBtIGluIGxhc3RfY29udGV4dAogICAgICAgICAgICBdCiAgICAgICAgICAgICMgRXh0cmFjdCBN"
    "b3JnYW5uYSdzIG1vc3QgcmVjZW50IG1lc3NhZ2UgYXMgZmFyZXdlbGwKICAgICAgICAgICAgIyBQcmVmZXIgdGhlIGNhcHR1cmVk"
    "IHNodXRkb3duIGRpYWxvZyByZXNwb25zZSBpZiBhdmFpbGFibGUKICAgICAgICAgICAgZmFyZXdlbGwgPSBnZXRhdHRyKHNlbGYs"
    "ICdfc2h1dGRvd25fZmFyZXdlbGxfdGV4dCcsICIiKQogICAgICAgICAgICBpZiBub3QgZmFyZXdlbGw6CiAgICAgICAgICAgICAg"
    "ICBmb3IgbSBpbiByZXZlcnNlZChoaXN0b3J5KToKICAgICAgICAgICAgICAgICAgICBpZiBtLmdldCgicm9sZSIpID09ICJhc3Np"
    "c3RhbnQiOgogICAgICAgICAgICAgICAgICAgICAgICBmYXJld2VsbCA9IG0uZ2V0KCJjb250ZW50IiwgIiIpWzo0MDBdCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X2ZhcmV3ZWxsIl0gPSBmYXJld2Vs"
    "bAogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTYXZlIHN0YXRlCiAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9zaHV0ZG93biJdICAgICAgICAgICAgID0gbG9jYWxfbm93X2lzbygp"
    "CiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X2FjdGl2ZSJdICAgICAgICAgICAgICAgPSBsb2NhbF9ub3dfaXNvKCkKICAg"
    "ICAgICAgICAgc2VsZi5fc3RhdGVbInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24iXSAgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAg"
    "ICAgICAgICAgIHNlbGYuX21lbW9yeS5zYXZlX3N0YXRlKHNlbGYuX3N0YXRlKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAg"
    "ICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTdG9wIHNjaGVkdWxlcgogICAgICAgIGlmIGhhc2F0dHIoc2VsZiwgIl9zY2hlZHVs"
    "ZXIiKSBhbmQgc2VsZi5fc2NoZWR1bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnNodXRkb3duKHdhaXQ9RmFsc2UpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgUGxheSBzaHV0ZG93biBzb3VuZAogICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQgPSBTb3VuZFdvcmtlcigic2h1dGRvd24iKQogICAgICAgICAgICBzZWxmLl9zaHV0"
    "ZG93bl9zb3VuZC5maW5pc2hlZC5jb25uZWN0KHNlbGYuX3NodXRkb3duX3NvdW5kLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICBz"
    "ZWxmLl9zaHV0ZG93bl9zb3VuZC5zdGFydCgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAg"
    "ICAgICBRQXBwbGljYXRpb24ucXVpdCgpCgoKIyDilIDilIAgRU5UUlkgUE9JTlQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACmRlZiBtYWluKCkgLT4gTm9uZToKICAgICIiIgogICAgQXBwbGljYXRpb24gZW50cnkgcG9pbnQuCgogICAg"
    "T3JkZXIgb2Ygb3BlcmF0aW9uczoKICAgIDEuIFByZS1mbGlnaHQgZGVwZW5kZW5jeSBib290c3RyYXAgKGF1dG8taW5zdGFsbCBt"
    "aXNzaW5nIGRlcHMpCiAgICAyLiBDaGVjayBmb3IgZmlyc3QgcnVuIOKGkiBzaG93IEZpcnN0UnVuRGlhbG9nCiAgICAgICBPbiBm"
    "aXJzdCBydW46CiAgICAgICAgIGEuIENyZWF0ZSBEOi9BSS9Nb2RlbHMvW0RlY2tOYW1lXS8gKG9yIGNob3NlbiBiYXNlX2RpcikK"
    "ICAgICAgICAgYi4gQ29weSBbZGVja25hbWVdX2RlY2sucHkgaW50byB0aGF0IGZvbGRlcgogICAgICAgICBjLiBXcml0ZSBjb25m"
    "aWcuanNvbiBpbnRvIHRoYXQgZm9sZGVyCiAgICAgICAgIGQuIEJvb3RzdHJhcCBhbGwgc3ViZGlyZWN0b3JpZXMgdW5kZXIgdGhh"
    "dCBmb2xkZXIKICAgICAgICAgZS4gQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgcG9pbnRpbmcgdG8gbmV3IGxvY2F0aW9uCiAgICAg"
    "ICAgIGYuIFNob3cgY29tcGxldGlvbiBtZXNzYWdlIGFuZCBFWElUIOKAlCB1c2VyIHVzZXMgc2hvcnRjdXQgZnJvbSBub3cgb24K"
    "ICAgIDMuIE5vcm1hbCBydW4g4oCUIGxhdW5jaCBRQXBwbGljYXRpb24gYW5kIEVjaG9EZWNrCiAgICAiIiIKICAgIGltcG9ydCBz"
    "aHV0aWwgYXMgX3NodXRpbAoKICAgICMg4pSA4pSAIFBoYXNlIDE6IERlcGVuZGVuY3kgYm9vdHN0cmFwIChwcmUtUUFwcGxpY2F0"
    "aW9uKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGJvb3RzdHJhcF9jaGVjaygpCgogICAg"
    "IyDilIDilIAgUGhhc2UgMjogUUFwcGxpY2F0aW9uIChuZWVkZWQgZm9yIGRpYWxvZ3MpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgX2Vhcmx5X2xvZygiW01BSU5dIENyZWF0aW5nIFFBcHBs"
    "aWNhdGlvbiIpCiAgICBhcHAgPSBRQXBwbGljYXRpb24oc3lzLmFyZ3YpCiAgICBhcHAuc2V0QXBwbGljYXRpb25OYW1lKEFQUF9O"
    "QU1FKQoKICAgICMgSW5zdGFsbCBRdCBtZXNzYWdlIGhhbmRsZXIgTk9XIOKAlCBjYXRjaGVzIGFsbCBRVGhyZWFkL1F0IHdhcm5p"
    "bmdzCiAgICAjIHdpdGggZnVsbCBzdGFjayB0cmFjZXMgZnJvbSB0aGlzIHBvaW50IGZvcndhcmQKICAgIF9pbnN0YWxsX3F0X21l"
    "c3NhZ2VfaGFuZGxlcigpCiAgICBfZWFybHlfbG9nKCJbTUFJTl0gUUFwcGxpY2F0aW9uIGNyZWF0ZWQsIG1lc3NhZ2UgaGFuZGxl"
    "ciBpbnN0YWxsZWQiKQoKICAgICMg4pSA4pSAIFBoYXNlIDM6IEZpcnN0IHJ1biBjaGVjayDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgIGlzX2ZpcnN0X3J1biA9IENGRy5nZXQoImZpcnN0X3J1biIsIFRydWUpCgogICAgaWYg"
    "aXNfZmlyc3RfcnVuOgogICAgICAgIGRsZyA9IEZpcnN0UnVuRGlhbG9nKCkKICAgICAgICBpZiBkbGcuZXhlYygpICE9IFFEaWFs"
    "b2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgc3lzLmV4aXQoMCkKCiAgICAgICAgIyDilIDilIAgQnVpbGQgY29u"
    "ZmlnIGZyb20gZGlhbG9nIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIG5ld19jZmcgPSBkbGcuYnVpbGRf"
    "Y29uZmlnKCkKCiAgICAgICAgIyDilIDilIAgRGV0ZXJtaW5lIE1vcmdhbm5hJ3MgaG9tZSBkaXJlY3Rvcnkg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgIyBBbHdh"
    "eXMgY3JlYXRlcyBEOi9BSS9Nb2RlbHMvTW9yZ2FubmEvIChvciBzaWJsaW5nIG9mIHNjcmlwdCkKICAgICAgICBzZWVkX2RpciAg"
    "ID0gU0NSSVBUX0RJUiAgICAgICAgICAjIHdoZXJlIHRoZSBzZWVkIC5weSBsaXZlcwogICAgICAgIG1vcmdhbm5hX2hvbWUgPSBz"
    "ZWVkX2RpciAvIERFQ0tfTkFNRQogICAgICAgIG1vcmdhbm5hX2hvbWUubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVl"
    "KQoKICAgICAgICAjIOKUgOKUgCBVcGRhdGUgYWxsIHBhdGhzIGluIGNvbmZpZyB0byBwb2ludCBpbnNpZGUgbW9yZ2FubmFfaG9t"
    "ZSDilIDilIAKICAgICAgICBuZXdfY2ZnWyJiYXNlX2RpciJdID0gc3RyKG1vcmdhbm5hX2hvbWUpCiAgICAgICAgbmV3X2NmZ1si"
    "cGF0aHMiXSA9IHsKICAgICAgICAgICAgImZhY2VzIjogICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiRmFjZXMiKSwKICAgICAgICAg"
    "ICAgInNvdW5kcyI6ICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAic291bmRzIiksCiAgICAgICAgICAgICJtZW1vcmllcyI6IHN0ciht"
    "b3JnYW5uYV9ob21lIC8gIm1lbW9yaWVzIiksCiAgICAgICAgICAgICJzZXNzaW9ucyI6IHN0cihtb3JnYW5uYV9ob21lIC8gInNl"
    "c3Npb25zIiksCiAgICAgICAgICAgICJzbCI6ICAgICAgIHN0cihtb3JnYW5uYV9ob21lIC8gInNsIiksCiAgICAgICAgICAgICJl"
    "eHBvcnRzIjogIHN0cihtb3JnYW5uYV9ob21lIC8gImV4cG9ydHMiKSwKICAgICAgICAgICAgImxvZ3MiOiAgICAgc3RyKG1vcmdh"
    "bm5hX2hvbWUgLyAibG9ncyIpLAogICAgICAgICAgICAiYmFja3VwcyI6ICBzdHIobW9yZ2FubmFfaG9tZSAvICJiYWNrdXBzIiks"
    "CiAgICAgICAgICAgICJwZXJzb25hcyI6IHN0cihtb3JnYW5uYV9ob21lIC8gInBlcnNvbmFzIiksCiAgICAgICAgICAgICJnb29n"
    "bGUiOiAgIHN0cihtb3JnYW5uYV9ob21lIC8gImdvb2dsZSIpLAogICAgICAgIH0KICAgICAgICBuZXdfY2ZnWyJnb29nbGUiXSA9"
    "IHsKICAgICAgICAgICAgImNyZWRlbnRpYWxzIjogc3RyKG1vcmdhbm5hX2hvbWUgLyAiZ29vZ2xlIiAvICJnb29nbGVfY3JlZGVu"
    "dGlhbHMuanNvbiIpLAogICAgICAgICAgICAidG9rZW4iOiAgICAgICBzdHIobW9yZ2FubmFfaG9tZSAvICJnb29nbGUiIC8gInRv"
    "a2VuLmpzb24iKSwKICAgICAgICAgICAgInRpbWV6b25lIjogICAgIkFtZXJpY2EvQ2hpY2FnbyIsCiAgICAgICAgICAgICJzY29w"
    "ZXMiOiBbCiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9jYWxlbmRhci5ldmVudHMiLAog"
    "ICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZHJpdmUiLAogICAgICAgICAgICAgICAgImh0"
    "dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZG9jdW1lbnRzIiwKICAgICAgICAgICAgXSwKICAgICAgICB9CiAgICAgICAg"
    "bmV3X2NmZ1siZmlyc3RfcnVuIl0gPSBGYWxzZQoKICAgICAgICAjIOKUgOKUgCBDb3B5IGRlY2sgZmlsZSBpbnRvIG1vcmdhbm5h"
    "X2hvbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICAgICAgc3JjX2RlY2sgPSBQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCkKICAgICAgICBkc3RfZGVjayA9IG1v"
    "cmdhbm5hX2hvbWUgLyBmIntERUNLX05BTUUubG93ZXIoKX1fZGVjay5weSIKICAgICAgICBpZiBzcmNfZGVjayAhPSBkc3RfZGVj"
    "azoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgX3NodXRpbC5jb3B5MihzdHIoc3JjX2RlY2spLCBzdHIoZHN0X2Rl"
    "Y2spKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBRTWVzc2FnZUJveC53YXJuaW5n"
    "KAogICAgICAgICAgICAgICAgICAgIE5vbmUsICJDb3B5IFdhcm5pbmciLAogICAgICAgICAgICAgICAgICAgIGYiQ291bGQgbm90"
    "IGNvcHkgZGVjayBmaWxlIHRvIHtERUNLX05BTUV9IGZvbGRlcjpcbntlfVxuXG4iCiAgICAgICAgICAgICAgICAgICAgZiJZb3Ug"
    "bWF5IG5lZWQgdG8gY29weSBpdCBtYW51YWxseS4iCiAgICAgICAgICAgICAgICApCgogICAgICAgICMg4pSA4pSAIFdyaXRlIGNv"
    "bmZpZy5qc29uIGludG8gbW9yZ2FubmFfaG9tZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBjZmdfZHN0ID0gbW9yZ2FubmFfaG9tZSAvICJjb25maWcuanNvbiIKICAg"
    "ICAgICBjZmdfZHN0LnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgd2l0aCBjZmdfZHN0"
    "Lm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICBqc29uLmR1bXAobmV3X2NmZywgZiwgaW5kZW50"
    "PTIpCgogICAgICAgICMg4pSA4pSAIEJvb3RzdHJhcCBhbGwgc3ViZGlyZWN0b3JpZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgIyBUZW1wb3JhcmlseSB1cGRhdGUgZ2xvYmFsIENGRyBzbyBib290c3RyYXAgZnVuY3Rpb25zIHVzZSBuZXcgcGF0aHMKICAg"
    "ICAgICBDRkcudXBkYXRlKG5ld19jZmcpCiAgICAgICAgYm9vdHN0cmFwX2RpcmVjdG9yaWVzKCkKICAgICAgICBib290c3RyYXBf"
    "c291bmRzKCkKICAgICAgICB3cml0ZV9yZXF1aXJlbWVudHNfdHh0KCkKCiAgICAgICAgIyDilIDilIAgVW5wYWNrIGZhY2UgWklQ"
    "IGlmIHByb3ZpZGVkIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGZhY2VfemlwID0gZGxnLmZhY2VfemlwX3BhdGgKICAg"
    "ICAgICBpZiBmYWNlX3ppcCBhbmQgUGF0aChmYWNlX3ppcCkuZXhpc3RzKCk6CiAgICAgICAgICAgIGltcG9ydCB6aXBmaWxlIGFz"
    "IF96aXBmaWxlCiAgICAgICAgICAgIGZhY2VzX2RpciA9IG1vcmdhbm5hX2hvbWUgLyAiRmFjZXMiCiAgICAgICAgICAgIGZhY2Vz"
    "X2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHdp"
    "dGggX3ppcGZpbGUuWmlwRmlsZShmYWNlX3ppcCwgInIiKSBhcyB6ZjoKICAgICAgICAgICAgICAgICAgICBleHRyYWN0ZWQgPSAw"
    "CiAgICAgICAgICAgICAgICAgICAgZm9yIG1lbWJlciBpbiB6Zi5uYW1lbGlzdCgpOgogICAgICAgICAgICAgICAgICAgICAgICBp"
    "ZiBtZW1iZXIubG93ZXIoKS5lbmRzd2l0aCgiLnBuZyIpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgZmlsZW5hbWUgPSBQ"
    "YXRoKG1lbWJlcikubmFtZQogICAgICAgICAgICAgICAgICAgICAgICAgICAgdGFyZ2V0ID0gZmFjZXNfZGlyIC8gZmlsZW5hbWUK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIHdpdGggemYub3BlbihtZW1iZXIpIGFzIHNyYywgdGFyZ2V0Lm9wZW4oIndiIikg"
    "YXMgZHN0OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGRzdC53cml0ZShzcmMucmVhZCgpKQogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgZXh0cmFjdGVkICs9IDEKICAgICAgICAgICAgICAgIF9lYXJseV9sb2coZiJbRkFDRVNdIEV4dHJhY3Rl"
    "ZCB7ZXh0cmFjdGVkfSBmYWNlIGltYWdlcyB0byB7ZmFjZXNfZGlyfSIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMg"
    "ZToKICAgICAgICAgICAgICAgIF9lYXJseV9sb2coZiJbRkFDRVNdIFpJUCBleHRyYWN0aW9uIGZhaWxlZDoge2V9IikKICAgICAg"
    "ICAgICAgICAgIFFNZXNzYWdlQm94Lndhcm5pbmcoCiAgICAgICAgICAgICAgICAgICAgTm9uZSwgIkZhY2UgUGFjayBXYXJuaW5n"
    "IiwKICAgICAgICAgICAgICAgICAgICBmIkNvdWxkIG5vdCBleHRyYWN0IGZhY2UgcGFjazpcbntlfVxuXG4iCiAgICAgICAgICAg"
    "ICAgICAgICAgZiJZb3UgY2FuIGFkZCBmYWNlcyBtYW51YWxseSB0bzpcbntmYWNlc19kaXJ9IgogICAgICAgICAgICAgICAgKQoK"
    "ICAgICAgICAjIOKUgOKUgCBDcmVhdGUgZGVza3RvcCBzaG9ydGN1dCBwb2ludGluZyB0byBuZXcgZGVjayBsb2NhdGlvbiDilIDi"
    "lIDilIDilIDilIDilIAKICAgICAgICBzaG9ydGN1dF9jcmVhdGVkID0gRmFsc2UKICAgICAgICBpZiBkbGcuY3JlYXRlX3Nob3J0"
    "Y3V0OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBXSU4zMl9PSzoKICAgICAgICAgICAgICAgICAgICBpbXBv"
    "cnQgd2luMzJjb20uY2xpZW50IGFzIF93aW4zMgogICAgICAgICAgICAgICAgICAgIGRlc2t0b3AgICAgID0gUGF0aC5ob21lKCkg"
    "LyAiRGVza3RvcCIKICAgICAgICAgICAgICAgICAgICBzY19wYXRoICAgICA9IGRlc2t0b3AgLyBmIntERUNLX05BTUV9LmxuayIK"
    "ICAgICAgICAgICAgICAgICAgICBweXRob253ICAgICA9IFBhdGgoc3lzLmV4ZWN1dGFibGUpCiAgICAgICAgICAgICAgICAgICAg"
    "aWYgcHl0aG9udy5uYW1lLmxvd2VyKCkgPT0gInB5dGhvbi5leGUiOgogICAgICAgICAgICAgICAgICAgICAgICBweXRob253ID0g"
    "cHl0aG9udy5wYXJlbnQgLyAicHl0aG9udy5leGUiCiAgICAgICAgICAgICAgICAgICAgaWYgbm90IHB5dGhvbncuZXhpc3RzKCk6"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIHB5dGhvbncgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQogICAgICAgICAgICAgICAgICAg"
    "IHNoZWxsID0gX3dpbjMyLkRpc3BhdGNoKCJXU2NyaXB0LlNoZWxsIikKICAgICAgICAgICAgICAgICAgICBzYyAgICA9IHNoZWxs"
    "LkNyZWF0ZVNob3J0Q3V0KHN0cihzY19wYXRoKSkKICAgICAgICAgICAgICAgICAgICBzYy5UYXJnZXRQYXRoICAgICAgPSBzdHIo"
    "cHl0aG9udykKICAgICAgICAgICAgICAgICAgICBzYy5Bcmd1bWVudHMgICAgICAgPSBmJyJ7ZHN0X2RlY2t9IicKICAgICAgICAg"
    "ICAgICAgICAgICBzYy5Xb3JraW5nRGlyZWN0b3J5PSBzdHIobW9yZ2FubmFfaG9tZSkKICAgICAgICAgICAgICAgICAgICBzYy5E"
    "ZXNjcmlwdGlvbiAgICAgPSBmIntERUNLX05BTUV9IOKAlCBFY2hvIERlY2siCiAgICAgICAgICAgICAgICAgICAgc2Muc2F2ZSgp"
    "CiAgICAgICAgICAgICAgICAgICAgc2hvcnRjdXRfY3JlYXRlZCA9IFRydWUKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBh"
    "cyBlOgogICAgICAgICAgICAgICAgcHJpbnQoZiJbU0hPUlRDVVRdIENvdWxkIG5vdCBjcmVhdGUgc2hvcnRjdXQ6IHtlfSIpCgog"
    "ICAgICAgICMg4pSA4pSAIENvbXBsZXRpb24gbWVzc2FnZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICBzaG9ydGN1dF9ub3RlID0gKAogICAgICAgICAgICAiQSBkZXNrdG9wIHNob3J0Y3V0IGhhcyBiZWVu"
    "IGNyZWF0ZWQuXG4iCiAgICAgICAgICAgIGYiVXNlIGl0IHRvIHN1bW1vbiB7REVDS19OQU1FfSBmcm9tIG5vdyBvbi4iCiAgICAg"
    "ICAgICAgIGlmIHNob3J0Y3V0X2NyZWF0ZWQgZWxzZQogICAgICAgICAgICAiTm8gc2hvcnRjdXQgd2FzIGNyZWF0ZWQuXG4iCiAg"
    "ICAgICAgICAgIGYiUnVuIHtERUNLX05BTUV9IGJ5IGRvdWJsZS1jbGlja2luZzpcbntkc3RfZGVja30iCiAgICAgICAgKQoKICAg"
    "ICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbigKICAgICAgICAgICAgTm9uZSwKICAgICAgICAgICAgZiLinKYge0RFQ0tfTkFN"
    "RX0ncyBTYW5jdHVtIFByZXBhcmVkIiwKICAgICAgICAgICAgZiJ7REVDS19OQU1FfSdzIHNhbmN0dW0gaGFzIGJlZW4gcHJlcGFy"
    "ZWQgYXQ6XG5cbiIKICAgICAgICAgICAgZiJ7bW9yZ2FubmFfaG9tZX1cblxuIgogICAgICAgICAgICBmIntzaG9ydGN1dF9ub3Rl"
    "fVxuXG4iCiAgICAgICAgICAgIGYiVGhpcyBzZXR1cCB3aW5kb3cgd2lsbCBub3cgY2xvc2UuXG4iCiAgICAgICAgICAgIGYiVXNl"
    "IHRoZSBzaG9ydGN1dCBvciB0aGUgZGVjayBmaWxlIHRvIGxhdW5jaCB7REVDS19OQU1FfS4iCiAgICAgICAgKQoKICAgICAgICAj"
    "IOKUgOKUgCBFeGl0IHNlZWQg4oCUIHVzZXIgbGF1bmNoZXMgZnJvbSBzaG9ydGN1dC9uZXcgbG9jYXRpb24g4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICAgICAgc3lzLmV4aXQoMCkKCiAgICAjIOKUgOKUgCBQaGFzZSA0OiBOb3JtYWwgbGF1bmNoIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgIyBPbmx5IHJlYWNoZXMgaGVyZSBvbiBzdWJzZXF1"
    "ZW50IHJ1bnMgZnJvbSBtb3JnYW5uYV9ob21lCiAgICBib290c3RyYXBfc291bmRzKCkKCiAgICBfZWFybHlfbG9nKGYiW01BSU5d"
    "IENyZWF0aW5nIHtERUNLX05BTUV9IGRlY2sgd2luZG93IikKICAgIHdpbmRvdyA9IEVjaG9EZWNrKCkKICAgIF9lYXJseV9sb2co"
    "ZiJbTUFJTl0ge0RFQ0tfTkFNRX0gZGVjayBjcmVhdGVkIOKAlCBjYWxsaW5nIHNob3coKSIpCiAgICB3aW5kb3cuc2hvdygpCiAg"
    "ICBfZWFybHlfbG9nKCJbTUFJTl0gd2luZG93LnNob3coKSBjYWxsZWQg4oCUIGV2ZW50IGxvb3Agc3RhcnRpbmciKQoKICAgICMg"
    "RGVmZXIgc2NoZWR1bGVyIGFuZCBzdGFydHVwIHNlcXVlbmNlIHVudGlsIGV2ZW50IGxvb3AgaXMgcnVubmluZy4KICAgICMgTm90"
    "aGluZyB0aGF0IHN0YXJ0cyB0aHJlYWRzIG9yIGVtaXRzIHNpZ25hbHMgc2hvdWxkIHJ1biBiZWZvcmUgdGhpcy4KICAgIFFUaW1l"
    "ci5zaW5nbGVTaG90KDIwMCwgbGFtYmRhOiAoX2Vhcmx5X2xvZygiW1RJTUVSXSBfc2V0dXBfc2NoZWR1bGVyIGZpcmluZyIpLCB3"
    "aW5kb3cuX3NldHVwX3NjaGVkdWxlcigpKSkKICAgIFFUaW1lci5zaW5nbGVTaG90KDQwMCwgbGFtYmRhOiAoX2Vhcmx5X2xvZygi"
    "W1RJTUVSXSBzdGFydF9zY2hlZHVsZXIgZmlyaW5nIiksIHdpbmRvdy5zdGFydF9zY2hlZHVsZXIoKSkpCiAgICBRVGltZXIuc2lu"
    "Z2xlU2hvdCg2MDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gX3N0YXJ0dXBfc2VxdWVuY2UgZmlyaW5nIiksIHdpbmRv"
    "dy5fc3RhcnR1cF9zZXF1ZW5jZSgpKSkKICAgIFFUaW1lci5zaW5nbGVTaG90KDEwMDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltU"
    "SU1FUl0gX3N0YXJ0dXBfZ29vZ2xlX2F1dGggZmlyaW5nIiksIHdpbmRvdy5fc3RhcnR1cF9nb29nbGVfYXV0aCgpKSkKCiAgICAj"
    "IFBsYXkgc3RhcnR1cCBzb3VuZCDigJQga2VlcCByZWZlcmVuY2UgdG8gcHJldmVudCBHQyB3aGlsZSB0aHJlYWQgcnVucwogICAg"
    "ZGVmIF9wbGF5X3N0YXJ0dXAoKToKICAgICAgICB3aW5kb3cuX3N0YXJ0dXBfc291bmQgPSBTb3VuZFdvcmtlcigic3RhcnR1cCIp"
    "CiAgICAgICAgd2luZG93Ll9zdGFydHVwX3NvdW5kLmZpbmlzaGVkLmNvbm5lY3Qod2luZG93Ll9zdGFydHVwX3NvdW5kLmRlbGV0"
    "ZUxhdGVyKQogICAgICAgIHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5zdGFydCgpCiAgICBRVGltZXIuc2luZ2xlU2hvdCgxMjAwLCBf"
    "cGxheV9zdGFydHVwKQoKICAgIHN5cy5leGl0KGFwcC5leGVjKCkpCgoKaWYgX19uYW1lX18gPT0gIl9fbWFpbl9fIjoKICAgIG1h"
    "aW4oKQoKCiMg4pSA4pSAIFBBU1MgNiBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBGdWxsIGRlY2sg"
    "YXNzZW1ibGVkLiBBbGwgcGFzc2VzIGNvbXBsZXRlLgojIENvbWJpbmUgYWxsIHBhc3NlcyBpbnRvIG1vcmdhbm5hX2RlY2sucHkg"
    "aW4gb3JkZXI6CiMgICBQYXNzIDEg4oaSIFBhc3MgMiDihpIgUGFzcyAzIOKGkiBQYXNzIDQg4oaSIFBhc3MgNSDihpIgUGFzcyA2"
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
