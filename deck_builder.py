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
    "dice_roller":        "# [MODULE: dice_roller — BUILT — see DiceRollerTab class]",
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
    "dCwgUVNjcm9sbEFyZWEsCiAgICBRU3BsaXR0ZXIsIFFJbnB1dERpYWxvZywgUVRvb2xCdXR0b24sIFFTcGluQm94CikKZnJvbSBQ"
    "eVNpZGU2LlF0Q29yZSBpbXBvcnQgKAogICAgUXQsIFFUaW1lciwgUVRocmVhZCwgU2lnbmFsLCBRRGF0ZSwgUVNpemUsIFFQb2lu"
    "dCwgUVJlY3QKKQpmcm9tIFB5U2lkZTYuUXRHdWkgaW1wb3J0ICgKICAgIFFGb250LCBRQ29sb3IsIFFQYWludGVyLCBRTGluZWFy"
    "R3JhZGllbnQsIFFSYWRpYWxHcmFkaWVudCwKICAgIFFQaXhtYXAsIFFQZW4sIFFQYWludGVyUGF0aCwgUVRleHRDaGFyRm9ybWF0"
    "LCBRSWNvbiwKICAgIFFUZXh0Q3Vyc29yLCBRQWN0aW9uCikKCiMg4pSA4pSAIEFQUCBJREVOVElUWSDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKQVBQX05BTUUgICAgICA9IFVJX1dJTkRPV19USVRMRQpBUFBfVkVSU0lPTiAgID0gIjIuMC4w"
    "IgpBUFBfRklMRU5BTUUgID0gZiJ7REVDS19OQU1FLmxvd2VyKCl9X2RlY2sucHkiCkJVSUxEX0RBVEUgICAgPSAiMjAyNi0wNC0w"
    "NCIKCiMg4pSA4pSAIENPTkZJRyBMT0FESU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIGNvbmZpZy5qc29u"
    "IGxpdmVzIG5leHQgdG8gdGhlIGRlY2sgLnB5IGZpbGUuCiMgQWxsIHBhdGhzIGNvbWUgZnJvbSBjb25maWcuIE5vdGhpbmcgaGFy"
    "ZGNvZGVkIGJlbG93IHRoaXMgcG9pbnQuCgpTQ1JJUFRfRElSID0gUGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpLnBhcmVudApDT05G"
    "SUdfUEFUSCA9IFNDUklQVF9ESVIgLyAiY29uZmlnLmpzb24iCgojIEluaXRpYWxpemUgZWFybHkgbG9nIG5vdyB0aGF0IHdlIGtu"
    "b3cgd2hlcmUgd2UgYXJlCl9pbml0X2Vhcmx5X2xvZyhTQ1JJUFRfRElSKQpfZWFybHlfbG9nKGYiW0lOSVRdIFNDUklQVF9ESVIg"
    "PSB7U0NSSVBUX0RJUn0iKQpfZWFybHlfbG9nKGYiW0lOSVRdIENPTkZJR19QQVRIID0ge0NPTkZJR19QQVRIfSIpCl9lYXJseV9s"
    "b2coZiJbSU5JVF0gY29uZmlnLmpzb24gZXhpc3RzOiB7Q09ORklHX1BBVEguZXhpc3RzKCl9IikKCmRlZiBfZGVmYXVsdF9jb25m"
    "aWcoKSAtPiBkaWN0OgogICAgIiIiUmV0dXJucyB0aGUgZGVmYXVsdCBjb25maWcgc3RydWN0dXJlIGZvciBmaXJzdC1ydW4gZ2Vu"
    "ZXJhdGlvbi4iIiIKICAgIGJhc2UgPSBzdHIoU0NSSVBUX0RJUikKICAgIHJldHVybiB7CiAgICAgICAgImRlY2tfbmFtZSI6IERF"
    "Q0tfTkFNRSwKICAgICAgICAiZGVja192ZXJzaW9uIjogQVBQX1ZFUlNJT04sCiAgICAgICAgImJhc2VfZGlyIjogYmFzZSwKICAg"
    "ICAgICAibW9kZWwiOiB7CiAgICAgICAgICAgICJ0eXBlIjogImxvY2FsIiwgICAgICAgICAgIyBsb2NhbCB8IG9sbGFtYSB8IGNs"
    "YXVkZSB8IG9wZW5haQogICAgICAgICAgICAicGF0aCI6ICIiLCAgICAgICAgICAgICAgICMgbG9jYWwgbW9kZWwgZm9sZGVyIHBh"
    "dGgKICAgICAgICAgICAgIm9sbGFtYV9tb2RlbCI6ICIiLCAgICAgICAjIGUuZy4gImRvbHBoaW4tMi42LTdiIgogICAgICAgICAg"
    "ICAiYXBpX2tleSI6ICIiLCAgICAgICAgICAgICMgQ2xhdWRlIG9yIE9wZW5BSSBrZXkKICAgICAgICAgICAgImFwaV90eXBlIjog"
    "IiIsICAgICAgICAgICAjICJjbGF1ZGUiIHwgIm9wZW5haSIKICAgICAgICAgICAgImFwaV9tb2RlbCI6ICIiLCAgICAgICAgICAj"
    "IGUuZy4gImNsYXVkZS1zb25uZXQtNC02IgogICAgICAgIH0sCiAgICAgICAgImdvb2dsZSI6IHsKICAgICAgICAgICAgImNyZWRl"
    "bnRpYWxzIjogc3RyKFNDUklQVF9ESVIgLyAiZ29vZ2xlIiAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIpLAogICAgICAgICAg"
    "ICAidG9rZW4iOiAgICAgICBzdHIoU0NSSVBUX0RJUiAvICJnb29nbGUiIC8gInRva2VuLmpzb24iKSwKICAgICAgICAgICAgInRp"
    "bWV6b25lIjogICAgIkFtZXJpY2EvQ2hpY2FnbyIsCiAgICAgICAgICAgICJzY29wZXMiOiBbCiAgICAgICAgICAgICAgICAiaHR0"
    "cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9jYWxlbmRhci5ldmVudHMiLAogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3"
    "Lmdvb2dsZWFwaXMuY29tL2F1dGgvZHJpdmUiLAogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1"
    "dGgvZG9jdW1lbnRzIiwKICAgICAgICAgICAgXSwKICAgICAgICB9LAogICAgICAgICJwYXRocyI6IHsKICAgICAgICAgICAgImZh"
    "Y2VzIjogICAgc3RyKFNDUklQVF9ESVIgLyAiRmFjZXMiKSwKICAgICAgICAgICAgInNvdW5kcyI6ICAgc3RyKFNDUklQVF9ESVIg"
    "LyAic291bmRzIiksCiAgICAgICAgICAgICJtZW1vcmllcyI6IHN0cihTQ1JJUFRfRElSIC8gIm1lbW9yaWVzIiksCiAgICAgICAg"
    "ICAgICJzZXNzaW9ucyI6IHN0cihTQ1JJUFRfRElSIC8gInNlc3Npb25zIiksCiAgICAgICAgICAgICJzbCI6ICAgICAgIHN0cihT"
    "Q1JJUFRfRElSIC8gInNsIiksCiAgICAgICAgICAgICJleHBvcnRzIjogIHN0cihTQ1JJUFRfRElSIC8gImV4cG9ydHMiKSwKICAg"
    "ICAgICAgICAgImxvZ3MiOiAgICAgc3RyKFNDUklQVF9ESVIgLyAibG9ncyIpLAogICAgICAgICAgICAiYmFja3VwcyI6ICBzdHIo"
    "U0NSSVBUX0RJUiAvICJiYWNrdXBzIiksCiAgICAgICAgICAgICJwZXJzb25hcyI6IHN0cihTQ1JJUFRfRElSIC8gInBlcnNvbmFz"
    "IiksCiAgICAgICAgICAgICJnb29nbGUiOiAgIHN0cihTQ1JJUFRfRElSIC8gImdvb2dsZSIpLAogICAgICAgIH0sCiAgICAgICAg"
    "InNldHRpbmdzIjogewogICAgICAgICAgICAiaWRsZV9lbmFibGVkIjogICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAgICAi"
    "aWRsZV9taW5fbWludXRlcyI6ICAgICAgICAgIDEwLAogICAgICAgICAgICAiaWRsZV9tYXhfbWludXRlcyI6ICAgICAgICAgIDMw"
    "LAogICAgICAgICAgICAiYXV0b3NhdmVfaW50ZXJ2YWxfbWludXRlcyI6IDEwLAogICAgICAgICAgICAibWF4X2JhY2t1cHMiOiAg"
    "ICAgICAgICAgICAgIDEwLAogICAgICAgICAgICAiZ29vZ2xlX3N5bmNfZW5hYmxlZCI6ICAgICAgIFRydWUsCiAgICAgICAgICAg"
    "ICJzb3VuZF9lbmFibGVkIjogICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgICAgImdvb2dsZV9pbmJvdW5kX2ludGVydmFsX21z"
    "IjogMzAwMDAsCiAgICAgICAgICAgICJlbWFpbF9yZWZyZXNoX2ludGVydmFsX21zIjogMzAwMDAwLAogICAgICAgICAgICAiZ29v"
    "Z2xlX2xvb2tiYWNrX2RheXMiOiAgICAgIDMwLAogICAgICAgICAgICAidXNlcl9kZWxheV90aHJlc2hvbGRfbWluIjogIDMwLAog"
    "ICAgICAgICAgICAidGltZXpvbmVfYXV0b19kZXRlY3QiOiAgICAgIFRydWUsCiAgICAgICAgICAgICJ0aW1lem9uZV9vdmVycmlk"
    "ZSI6ICAgICAgICAgIiIsCiAgICAgICAgICAgICJmdWxsc2NyZWVuX2VuYWJsZWQiOiAgICAgICAgRmFsc2UsCiAgICAgICAgICAg"
    "ICJib3JkZXJsZXNzX2VuYWJsZWQiOiAgICAgICAgRmFsc2UsCiAgICAgICAgfSwKICAgICAgICAiZmlyc3RfcnVuIjogVHJ1ZSwK"
    "ICAgIH0KCmRlZiBsb2FkX2NvbmZpZygpIC0+IGRpY3Q6CiAgICAiIiJMb2FkIGNvbmZpZy5qc29uLiBSZXR1cm5zIGRlZmF1bHQg"
    "aWYgbWlzc2luZyBvciBjb3JydXB0LiIiIgogICAgaWYgbm90IENPTkZJR19QQVRILmV4aXN0cygpOgogICAgICAgIHJldHVybiBf"
    "ZGVmYXVsdF9jb25maWcoKQogICAgdHJ5OgogICAgICAgIHdpdGggQ09ORklHX1BBVEgub3BlbigiciIsIGVuY29kaW5nPSJ1dGYt"
    "OCIpIGFzIGY6CiAgICAgICAgICAgIHJldHVybiBqc29uLmxvYWQoZikKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcmV0"
    "dXJuIF9kZWZhdWx0X2NvbmZpZygpCgpkZWYgc2F2ZV9jb25maWcoY2ZnOiBkaWN0KSAtPiBOb25lOgogICAgIiIiV3JpdGUgY29u"
    "ZmlnLmpzb24uIiIiCiAgICBDT05GSUdfUEFUSC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAg"
    "d2l0aCBDT05GSUdfUEFUSC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICBqc29uLmR1bXAoY2ZnLCBm"
    "LCBpbmRlbnQ9MikKCiMgTG9hZCBjb25maWcgYXQgbW9kdWxlIGxldmVsIOKAlCBldmVyeXRoaW5nIGJlbG93IHJlYWRzIGZyb20g"
    "Q0ZHCkNGRyA9IGxvYWRfY29uZmlnKCkKX2Vhcmx5X2xvZyhmIltJTklUXSBDb25maWcgbG9hZGVkIOKAlCBmaXJzdF9ydW49e0NG"
    "Ry5nZXQoJ2ZpcnN0X3J1bicpfSwgbW9kZWxfdHlwZT17Q0ZHLmdldCgnbW9kZWwnLHt9KS5nZXQoJ3R5cGUnKX0iKQoKX0RFRkFV"
    "TFRfUEFUSFM6IGRpY3Rbc3RyLCBQYXRoXSA9IHsKICAgICJmYWNlcyI6ICAgIFNDUklQVF9ESVIgLyAiRmFjZXMiLAogICAgInNv"
    "dW5kcyI6ICAgU0NSSVBUX0RJUiAvICJzb3VuZHMiLAogICAgIm1lbW9yaWVzIjogU0NSSVBUX0RJUiAvICJtZW1vcmllcyIsCiAg"
    "ICAic2Vzc2lvbnMiOiBTQ1JJUFRfRElSIC8gInNlc3Npb25zIiwKICAgICJzbCI6ICAgICAgIFNDUklQVF9ESVIgLyAic2wiLAog"
    "ICAgImV4cG9ydHMiOiAgU0NSSVBUX0RJUiAvICJleHBvcnRzIiwKICAgICJsb2dzIjogICAgIFNDUklQVF9ESVIgLyAibG9ncyIs"
    "CiAgICAiYmFja3VwcyI6ICBTQ1JJUFRfRElSIC8gImJhY2t1cHMiLAogICAgInBlcnNvbmFzIjogU0NSSVBUX0RJUiAvICJwZXJz"
    "b25hcyIsCiAgICAiZ29vZ2xlIjogICBTQ1JJUFRfRElSIC8gImdvb2dsZSIsCn0KCmRlZiBfbm9ybWFsaXplX2NvbmZpZ19wYXRo"
    "cygpIC0+IE5vbmU6CiAgICAiIiIKICAgIFNlbGYtaGVhbCBvbGRlciBjb25maWcuanNvbiBmaWxlcyBtaXNzaW5nIHJlcXVpcmVk"
    "IHBhdGgga2V5cy4KICAgIEFkZHMgbWlzc2luZyBwYXRoIGtleXMgYW5kIG5vcm1hbGl6ZXMgZ29vZ2xlIGNyZWRlbnRpYWwvdG9r"
    "ZW4gbG9jYXRpb25zLAogICAgdGhlbiBwZXJzaXN0cyBjb25maWcuanNvbiBpZiBhbnl0aGluZyBjaGFuZ2VkLgogICAgIiIiCiAg"
    "ICBjaGFuZ2VkID0gRmFsc2UKICAgIHBhdGhzID0gQ0ZHLnNldGRlZmF1bHQoInBhdGhzIiwge30pCiAgICBmb3Iga2V5LCBkZWZh"
    "dWx0X3BhdGggaW4gX0RFRkFVTFRfUEFUSFMuaXRlbXMoKToKICAgICAgICBpZiBub3QgcGF0aHMuZ2V0KGtleSk6CiAgICAgICAg"
    "ICAgIHBhdGhzW2tleV0gPSBzdHIoZGVmYXVsdF9wYXRoKQogICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgIGdvb2dsZV9j"
    "ZmcgPSBDRkcuc2V0ZGVmYXVsdCgiZ29vZ2xlIiwge30pCiAgICBnb29nbGVfcm9vdCA9IFBhdGgocGF0aHMuZ2V0KCJnb29nbGUi"
    "LCBzdHIoX0RFRkFVTFRfUEFUSFNbImdvb2dsZSJdKSkpCiAgICBkZWZhdWx0X2NyZWRzID0gc3RyKGdvb2dsZV9yb290IC8gImdv"
    "b2dsZV9jcmVkZW50aWFscy5qc29uIikKICAgIGRlZmF1bHRfdG9rZW4gPSBzdHIoZ29vZ2xlX3Jvb3QgLyAidG9rZW4uanNvbiIp"
    "CiAgICBjcmVkc192YWwgPSBzdHIoZ29vZ2xlX2NmZy5nZXQoImNyZWRlbnRpYWxzIiwgIiIpKS5zdHJpcCgpCiAgICB0b2tlbl92"
    "YWwgPSBzdHIoZ29vZ2xlX2NmZy5nZXQoInRva2VuIiwgIiIpKS5zdHJpcCgpCiAgICBpZiAobm90IGNyZWRzX3ZhbCkgb3IgKCJj"
    "b25maWciIGluIGNyZWRzX3ZhbCBhbmQgImdvb2dsZV9jcmVkZW50aWFscy5qc29uIiBpbiBjcmVkc192YWwpOgogICAgICAgIGdv"
    "b2dsZV9jZmdbImNyZWRlbnRpYWxzIl0gPSBkZWZhdWx0X2NyZWRzCiAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgIGlmIG5vdCB0"
    "b2tlbl92YWw6CiAgICAgICAgZ29vZ2xlX2NmZ1sidG9rZW4iXSA9IGRlZmF1bHRfdG9rZW4KICAgICAgICBjaGFuZ2VkID0gVHJ1"
    "ZQoKICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQoKZGVmIGNmZ19wYXRoKGtleTogc3RyKSAtPiBQYXRo"
    "OgogICAgIiIiQ29udmVuaWVuY2U6IGdldCBhIHBhdGggZnJvbSBDRkdbJ3BhdGhzJ11ba2V5XSBhcyBhIFBhdGggb2JqZWN0IHdp"
    "dGggc2FmZSBmYWxsYmFjayBkZWZhdWx0cy4iIiIKICAgIHBhdGhzID0gQ0ZHLmdldCgicGF0aHMiLCB7fSkKICAgIHZhbHVlID0g"
    "cGF0aHMuZ2V0KGtleSkKICAgIGlmIHZhbHVlOgogICAgICAgIHJldHVybiBQYXRoKHZhbHVlKQogICAgZmFsbGJhY2sgPSBfREVG"
    "QVVMVF9QQVRIUy5nZXQoa2V5KQogICAgaWYgZmFsbGJhY2s6CiAgICAgICAgcGF0aHNba2V5XSA9IHN0cihmYWxsYmFjaykKICAg"
    "ICAgICByZXR1cm4gZmFsbGJhY2sKICAgIHJldHVybiBTQ1JJUFRfRElSIC8ga2V5Cgpfbm9ybWFsaXplX2NvbmZpZ19wYXRocygp"
    "CgojIOKUgOKUgCBDT0xPUiBDT05TVEFOVFMg4oCUIGRlcml2ZWQgZnJvbSBwZXJzb25hIHRlbXBsYXRlIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIENfUFJJTUFS"
    "WSwgQ19TRUNPTkRBUlksIENfQUNDRU5ULCBDX0JHLCBDX1BBTkVMLCBDX0JPUkRFUiwKIyBDX1RFWFQsIENfVEVYVF9ESU0gYXJl"
    "IGluamVjdGVkIGF0IHRoZSB0b3Agb2YgdGhpcyBmaWxlIGJ5IGRlY2tfYnVpbGRlci4KIyBFdmVyeXRoaW5nIGJlbG93IGlzIGRl"
    "cml2ZWQgZnJvbSB0aG9zZSBpbmplY3RlZCB2YWx1ZXMuCgojIFNlbWFudGljIGFsaWFzZXMg4oCUIG1hcCBwZXJzb25hIGNvbG9y"
    "cyB0byBuYW1lZCByb2xlcyB1c2VkIHRocm91Z2hvdXQgdGhlIFVJCkNfQ1JJTVNPTiAgICAgPSBDX1BSSU1BUlkgICAgICAgICAg"
    "IyBtYWluIGFjY2VudCAoYnV0dG9ucywgYm9yZGVycywgaGlnaGxpZ2h0cykKQ19DUklNU09OX0RJTSA9IENfUFJJTUFSWSArICI4"
    "OCIgICAjIGRpbSBhY2NlbnQgZm9yIHN1YnRsZSBib3JkZXJzCkNfR09MRCAgICAgICAgPSBDX1NFQ09OREFSWSAgICAgICAgIyBt"
    "YWluIGxhYmVsL3RleHQvQUkgb3V0cHV0IGNvbG9yCkNfR09MRF9ESU0gICAgPSBDX1NFQ09OREFSWSArICI4OCIgIyBkaW0gc2Vj"
    "b25kYXJ5CkNfR09MRF9CUklHSFQgPSBDX0FDQ0VOVCAgICAgICAgICAgIyBlbXBoYXNpcywgaG92ZXIgc3RhdGVzCkNfU0lMVkVS"
    "ICAgICAgPSBDX1RFWFRfRElNICAgICAgICAgIyBzZWNvbmRhcnkgdGV4dCAoYWxyZWFkeSBpbmplY3RlZCkKQ19TSUxWRVJfRElN"
    "ICA9IENfVEVYVF9ESU0gKyAiODgiICAjIGRpbSBzZWNvbmRhcnkgdGV4dApDX01PTklUT1IgICAgID0gQ19CRyAgICAgICAgICAg"
    "ICAgICMgY2hhdCBkaXNwbGF5IGJhY2tncm91bmQgKGFscmVhZHkgaW5qZWN0ZWQpCkNfQkcyICAgICAgICAgPSBDX0JHICAgICAg"
    "ICAgICAgICAgIyBzZWNvbmRhcnkgYmFja2dyb3VuZApDX0JHMyAgICAgICAgID0gQ19QQU5FTCAgICAgICAgICAgICMgdGVydGlh"
    "cnkvaW5wdXQgYmFja2dyb3VuZCAoYWxyZWFkeSBpbmplY3RlZCkKQ19CTE9PRCAgICAgICA9ICcjOGIwMDAwJyAgICAgICAgICAj"
    "IGVycm9yIHN0YXRlcywgZGFuZ2VyIOKAlCB1bml2ZXJzYWwKQ19QVVJQTEUgICAgICA9ICcjODg1NWNjJyAgICAgICAgICAjIFNZ"
    "U1RFTSBtZXNzYWdlcyDigJQgdW5pdmVyc2FsCkNfUFVSUExFX0RJTSAgPSAnIzJhMDUyYScgICAgICAgICAgIyBkaW0gcHVycGxl"
    "IOKAlCB1bml2ZXJzYWwKQ19HUkVFTiAgICAgICA9ICcjNDRhYTY2JyAgICAgICAgICAjIHBvc2l0aXZlIHN0YXRlcyDigJQgdW5p"
    "dmVyc2FsCkNfQkxVRSAgICAgICAgPSAnIzQ0ODhjYycgICAgICAgICAgIyBpbmZvIHN0YXRlcyDigJQgdW5pdmVyc2FsCgojIEZv"
    "bnQgaGVscGVyIOKAlCBleHRyYWN0cyBwcmltYXJ5IGZvbnQgbmFtZSBmb3IgUUZvbnQoKSBjYWxscwpERUNLX0ZPTlQgPSBVSV9G"
    "T05UX0ZBTUlMWS5zcGxpdCgnLCcpWzBdLnN0cmlwKCkuc3RyaXAoIiciKQoKIyBFbW90aW9uIOKGkiBjb2xvciBtYXBwaW5nIChm"
    "b3IgZW1vdGlvbiByZWNvcmQgY2hpcHMpCkVNT1RJT05fQ09MT1JTOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICJ2aWN0b3J5Ijog"
    "ICAgQ19HT0xELAogICAgInNtdWciOiAgICAgICBDX0dPTEQsCiAgICAiaW1wcmVzc2VkIjogIENfR09MRCwKICAgICJyZWxpZXZl"
    "ZCI6ICAgQ19HT0xELAogICAgImhhcHB5IjogICAgICBDX0dPTEQsCiAgICAiZmxpcnR5IjogICAgIENfR09MRCwKICAgICJwYW5p"
    "Y2tlZCI6ICAgQ19DUklNU09OLAogICAgImFuZ3J5IjogICAgICBDX0NSSU1TT04sCiAgICAic2hvY2tlZCI6ICAgIENfQ1JJTVNP"
    "TiwKICAgICJjaGVhdG1vZGUiOiAgQ19DUklNU09OLAogICAgImNvbmNlcm5lZCI6ICAiI2NjNjYyMiIsCiAgICAic2FkIjogICAg"
    "ICAgICIjY2M2NjIyIiwKICAgICJodW1pbGlhdGVkIjogIiNjYzY2MjIiLAogICAgImZsdXN0ZXJlZCI6ICAiI2NjNjYyMiIsCiAg"
    "ICAicGxvdHRpbmciOiAgIENfUFVSUExFLAogICAgInN1c3BpY2lvdXMiOiBDX1BVUlBMRSwKICAgICJlbnZpb3VzIjogICAgQ19Q"
    "VVJQTEUsCiAgICAiZm9jdXNlZCI6ICAgIENfU0lMVkVSLAogICAgImFsZXJ0IjogICAgICBDX1NJTFZFUiwKICAgICJuZXV0cmFs"
    "IjogICAgQ19URVhUX0RJTSwKfQoKIyDilIDilIAgREVDT1JBVElWRSBDT05TVEFOVFMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgUlVORVMgaXMg"
    "c291cmNlZCBmcm9tIFVJX1JVTkVTIGluamVjdGVkIGJ5IHRoZSBwZXJzb25hIHRlbXBsYXRlClJVTkVTID0gVUlfUlVORVMKCiMg"
    "RmFjZSBpbWFnZSBtYXAg4oCUIHByZWZpeCBmcm9tIEZBQ0VfUFJFRklYLCBmaWxlcyBsaXZlIGluIGNvbmZpZyBwYXRocy5mYWNl"
    "cwpGQUNFX0ZJTEVTOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICJuZXV0cmFsIjogICAgZiJ7RkFDRV9QUkVGSVh9X05ldXRyYWwu"
    "cG5nIiwKICAgICJhbGVydCI6ICAgICAgZiJ7RkFDRV9QUkVGSVh9X0FsZXJ0LnBuZyIsCiAgICAiZm9jdXNlZCI6ICAgIGYie0ZB"
    "Q0VfUFJFRklYfV9Gb2N1c2VkLnBuZyIsCiAgICAic211ZyI6ICAgICAgIGYie0ZBQ0VfUFJFRklYfV9TbXVnLnBuZyIsCiAgICAi"
    "Y29uY2VybmVkIjogIGYie0ZBQ0VfUFJFRklYfV9Db25jZXJuZWQucG5nIiwKICAgICJzYWQiOiAgICAgICAgZiJ7RkFDRV9QUkVG"
    "SVh9X1NhZF9DcnlpbmcucG5nIiwKICAgICJyZWxpZXZlZCI6ICAgZiJ7RkFDRV9QUkVGSVh9X1JlbGlldmVkLnBuZyIsCiAgICAi"
    "aW1wcmVzc2VkIjogIGYie0ZBQ0VfUFJFRklYfV9JbXByZXNzZWQucG5nIiwKICAgICJ2aWN0b3J5IjogICAgZiJ7RkFDRV9QUkVG"
    "SVh9X1ZpY3RvcnkucG5nIiwKICAgICJodW1pbGlhdGVkIjogZiJ7RkFDRV9QUkVGSVh9X0h1bWlsaWF0ZWQucG5nIiwKICAgICJz"
    "dXNwaWNpb3VzIjogZiJ7RkFDRV9QUkVGSVh9X1N1c3BpY2lvdXMucG5nIiwKICAgICJwYW5pY2tlZCI6ICAgZiJ7RkFDRV9QUkVG"
    "SVh9X1Bhbmlja2VkLnBuZyIsCiAgICAiY2hlYXRtb2RlIjogIGYie0ZBQ0VfUFJFRklYfV9DaGVhdF9Nb2RlLnBuZyIsCiAgICAi"
    "YW5ncnkiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9BbmdyeS5wbmciLAogICAgInBsb3R0aW5nIjogICBmIntGQUNFX1BSRUZJWH1f"
    "UGxvdHRpbmcucG5nIiwKICAgICJzaG9ja2VkIjogICAgZiJ7RkFDRV9QUkVGSVh9X1Nob2NrZWQucG5nIiwKICAgICJoYXBweSI6"
    "ICAgICAgZiJ7RkFDRV9QUkVGSVh9X0hhcHB5LnBuZyIsCiAgICAiZmxpcnR5IjogICAgIGYie0ZBQ0VfUFJFRklYfV9GbGlydHku"
    "cG5nIiwKICAgICJmbHVzdGVyZWQiOiAgZiJ7RkFDRV9QUkVGSVh9X0ZsdXN0ZXJlZC5wbmciLAogICAgImVudmlvdXMiOiAgICBm"
    "IntGQUNFX1BSRUZJWH1fRW52aW91cy5wbmciLAp9CgpTRU5USU1FTlRfTElTVCA9ICgKICAgICJuZXV0cmFsLCBhbGVydCwgZm9j"
    "dXNlZCwgc211ZywgY29uY2VybmVkLCBzYWQsIHJlbGlldmVkLCBpbXByZXNzZWQsICIKICAgICJ2aWN0b3J5LCBodW1pbGlhdGVk"
    "LCBzdXNwaWNpb3VzLCBwYW5pY2tlZCwgYW5ncnksIHBsb3R0aW5nLCBzaG9ja2VkLCAiCiAgICAiaGFwcHksIGZsaXJ0eSwgZmx1"
    "c3RlcmVkLCBlbnZpb3VzIgopCgojIOKUgOKUgCBTWVNURU0gUFJPTVBUIOKAlCBpbmplY3RlZCBmcm9tIHBlcnNvbmEgdGVtcGxh"
    "dGUgYXQgdG9wIG9mIGZpbGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgU1lTVEVNX1BST01QVF9C"
    "QVNFIGlzIGFscmVhZHkgZGVmaW5lZCBhYm92ZSBmcm9tIDw8PFNZU1RFTV9QUk9NUFQ+Pj4gaW5qZWN0aW9uLgojIERvIG5vdCBy"
    "ZWRlZmluZSBpdCBoZXJlLgoKIyDilIDilIAgR0xPQkFMIFNUWUxFU0hFRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSAClNUWUxFID0g"
    "ZiIiIgpRTWFpbldpbmRvdywgUVdpZGdldCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkd9OwogICAgY29sb3I6IHtDX0dP"
    "TER9OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07Cn19ClFUZXh0RWRpdCB7ewogICAgYmFja2dyb3VuZC1jb2xv"
    "cjoge0NfTU9OSVRPUn07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07"
    "CiAgICBib3JkZXItcmFkaXVzOiAycHg7CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKICAgIGZvbnQtc2l6ZTog"
    "MTJweDsKICAgIHBhZGRpbmc6IDhweDsKICAgIHNlbGVjdGlvbi1iYWNrZ3JvdW5kLWNvbG9yOiB7Q19DUklNU09OX0RJTX07Cn19"
    "ClFMaW5lRWRpdCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0NSSU1TT059OwogICAgYm9yZGVyLXJhZGl1czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05U"
    "X0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEzcHg7CiAgICBwYWRkaW5nOiA4cHggMTJweDsKfX0KUUxpbmVFZGl0OmZvY3VzIHt7"
    "CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEfTsKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX1BBTkVMfTsKfX0KUVB1c2hC"
    "dXR0b24ge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0NSSU1TT05fRElNfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJv"
    "cmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OwogICAgYm9yZGVyLXJhZGl1czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9G"
    "T05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEycHg7CiAgICBmb250LXdlaWdodDogYm9sZDsKICAgIHBhZGRpbmc6IDhweCAy"
    "MHB4OwogICAgbGV0dGVyLXNwYWNpbmc6IDJweDsKfX0KUVB1c2hCdXR0b246aG92ZXIge3sKICAgIGJhY2tncm91bmQtY29sb3I6"
    "IHtDX0NSSU1TT059OwogICAgY29sb3I6IHtDX0dPTERfQlJJR0hUfTsKfX0KUVB1c2hCdXR0b246cHJlc3NlZCB7ewogICAgYmFj"
    "a2dyb3VuZC1jb2xvcjoge0NfQkxPT0R9OwogICAgYm9yZGVyLWNvbG9yOiB7Q19CTE9PRH07CiAgICBjb2xvcjoge0NfVEVYVH07"
    "Cn19ClFQdXNoQnV0dG9uOmRpc2FibGVkIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX1RF"
    "WFRfRElNfTsKICAgIGJvcmRlci1jb2xvcjoge0NfVEVYVF9ESU19Owp9fQpRU2Nyb2xsQmFyOnZlcnRpY2FsIHt7CiAgICBiYWNr"
    "Z3JvdW5kOiB7Q19CR307CiAgICB3aWR0aDogNnB4OwogICAgYm9yZGVyOiBub25lOwp9fQpRU2Nyb2xsQmFyOjpoYW5kbGU6dmVy"
    "dGljYWwge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGJvcmRlci1yYWRpdXM6IDNweDsKfX0KUVNjcm9s"
    "bEJhcjo6aGFuZGxlOnZlcnRpY2FsOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OfTsKfX0KUVNjcm9sbEJhcjo6"
    "YWRkLWxpbmU6dmVydGljYWwsIFFTY3JvbGxCYXI6OnN1Yi1saW5lOnZlcnRpY2FsIHt7CiAgICBoZWlnaHQ6IDBweDsKfX0KUVRh"
    "YldpZGdldDo6cGFuZSB7ewogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgYmFja2dyb3VuZDoge0Nf"
    "QkcyfTsKfX0KUVRhYkJhcjo6dGFiIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX1RFWFRfRElNfTsK"
    "ICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIHBhZGRpbmc6IDZweCAxNHB4OwogICAgZm9udC1mYW1p"
    "bHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEwcHg7CiAgICBsZXR0ZXItc3BhY2luZzogMXB4Owp9fQpRVGFi"
    "QmFyOjp0YWI6c2VsZWN0ZWQge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsK"
    "ICAgIGJvcmRlci1ib3R0b206IDJweCBzb2xpZCB7Q19DUklNU09OfTsKfX0KUVRhYkJhcjo6dGFiOmhvdmVyIHt7CiAgICBiYWNr"
    "Z3JvdW5kOiB7Q19QQU5FTH07CiAgICBjb2xvcjoge0NfR09MRF9ESU19Owp9fQpRVGFibGVXaWRnZXQge3sKICAgIGJhY2tncm91"
    "bmQ6IHtDX0JHMn07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAg"
    "ICBncmlkbGluZS1jb2xvcjoge0NfQk9SREVSfTsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1z"
    "aXplOiAxMXB4Owp9fQpRVGFibGVXaWRnZXQ6Oml0ZW06c2VsZWN0ZWQge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElN"
    "fTsKICAgIGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07Cn19ClFIZWFkZXJWaWV3OjpzZWN0aW9uIHt7CiAgICBiYWNrZ3JvdW5kOiB7"
    "Q19CRzN9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgcGFk"
    "ZGluZzogNHB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEwcHg7CiAgICBmb250"
    "LXdlaWdodDogYm9sZDsKICAgIGxldHRlci1zcGFjaW5nOiAxcHg7Cn19ClFDb21ib0JveCB7ewogICAgYmFja2dyb3VuZDoge0Nf"
    "QkczfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIHBhZGRp"
    "bmc6IDRweCA4cHg7CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKfX0KUUNvbWJvQm94Ojpkcm9wLWRvd24ge3sK"
    "ICAgIGJvcmRlcjogbm9uZTsKfX0KUUNoZWNrQm94IHt7CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBmb250LWZhbWlseToge1VJ"
    "X0ZPTlRfRkFNSUxZfTsKfX0KUUxhYmVsIHt7CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IG5vbmU7Cn19ClFTcGxp"
    "dHRlcjo6aGFuZGxlIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiAgICB3aWR0aDogMnB4Owp9fQoiIiIKCiMg"
    "4pSA4pSAIERJUkVDVE9SWSBCT09UU1RSQVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBib290c3RyYXBfZGlyZWN0b3JpZXMoKSAtPiBO"
    "b25lOgogICAgIiIiCiAgICBDcmVhdGUgYWxsIHJlcXVpcmVkIGRpcmVjdG9yaWVzIGlmIHRoZXkgZG9uJ3QgZXhpc3QuCiAgICBD"
    "YWxsZWQgb24gc3RhcnR1cCBiZWZvcmUgYW55dGhpbmcgZWxzZS4gU2FmZSB0byBjYWxsIG11bHRpcGxlIHRpbWVzLgogICAgQWxz"
    "byBtaWdyYXRlcyBmaWxlcyBmcm9tIG9sZCBbRGVja05hbWVdX01lbW9yaWVzIGxheW91dCBpZiBkZXRlY3RlZC4KICAgICIiIgog"
    "ICAgZGlycyA9IFsKICAgICAgICBjZmdfcGF0aCgiZmFjZXMiKSwKICAgICAgICBjZmdfcGF0aCgic291bmRzIiksCiAgICAgICAg"
    "Y2ZnX3BhdGgoIm1lbW9yaWVzIiksCiAgICAgICAgY2ZnX3BhdGgoInNlc3Npb25zIiksCiAgICAgICAgY2ZnX3BhdGgoInNsIiks"
    "CiAgICAgICAgY2ZnX3BhdGgoImV4cG9ydHMiKSwKICAgICAgICBjZmdfcGF0aCgibG9ncyIpLAogICAgICAgIGNmZ19wYXRoKCJi"
    "YWNrdXBzIiksCiAgICAgICAgY2ZnX3BhdGgoInBlcnNvbmFzIiksCiAgICAgICAgY2ZnX3BhdGgoImdvb2dsZSIpLAogICAgICAg"
    "IGNmZ19wYXRoKCJnb29nbGUiKSAvICJleHBvcnRzIiwKICAgIF0KICAgIGZvciBkIGluIGRpcnM6CiAgICAgICAgZC5ta2Rpcihw"
    "YXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCgogICAgIyBDcmVhdGUgZW1wdHkgSlNPTkwgZmlsZXMgaWYgdGhleSBkb24ndCBl"
    "eGlzdAogICAgbWVtb3J5X2RpciA9IGNmZ19wYXRoKCJtZW1vcmllcyIpCiAgICBmb3IgZm5hbWUgaW4gKCJtZXNzYWdlcy5qc29u"
    "bCIsICJtZW1vcmllcy5qc29ubCIsICJ0YXNrcy5qc29ubCIsCiAgICAgICAgICAgICAgICAgICJsZXNzb25zX2xlYXJuZWQuanNv"
    "bmwiLCAicGVyc29uYV9oaXN0b3J5Lmpzb25sIik6CiAgICAgICAgZnAgPSBtZW1vcnlfZGlyIC8gZm5hbWUKICAgICAgICBpZiBu"
    "b3QgZnAuZXhpc3RzKCk6CiAgICAgICAgICAgIGZwLndyaXRlX3RleHQoIiIsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgc2xfZGly"
    "ID0gY2ZnX3BhdGgoInNsIikKICAgIGZvciBmbmFtZSBpbiAoInNsX3NjYW5zLmpzb25sIiwgInNsX2NvbW1hbmRzLmpzb25sIik6"
    "CiAgICAgICAgZnAgPSBzbF9kaXIgLyBmbmFtZQogICAgICAgIGlmIG5vdCBmcC5leGlzdHMoKToKICAgICAgICAgICAgZnAud3Jp"
    "dGVfdGV4dCgiIiwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBzZXNzaW9uc19kaXIgPSBjZmdfcGF0aCgic2Vzc2lvbnMiKQogICAg"
    "aWR4ID0gc2Vzc2lvbnNfZGlyIC8gInNlc3Npb25faW5kZXguanNvbiIKICAgIGlmIG5vdCBpZHguZXhpc3RzKCk6CiAgICAgICAg"
    "aWR4LndyaXRlX3RleHQoanNvbi5kdW1wcyh7InNlc3Npb25zIjogW119LCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIpCgog"
    "ICAgc3RhdGVfcGF0aCA9IG1lbW9yeV9kaXIgLyAic3RhdGUuanNvbiIKICAgIGlmIG5vdCBzdGF0ZV9wYXRoLmV4aXN0cygpOgog"
    "ICAgICAgIF93cml0ZV9kZWZhdWx0X3N0YXRlKHN0YXRlX3BhdGgpCgogICAgaW5kZXhfcGF0aCA9IG1lbW9yeV9kaXIgLyAiaW5k"
    "ZXguanNvbiIKICAgIGlmIG5vdCBpbmRleF9wYXRoLmV4aXN0cygpOgogICAgICAgIGluZGV4X3BhdGgud3JpdGVfdGV4dCgKICAg"
    "ICAgICAgICAganNvbi5kdW1wcyh7InZlcnNpb24iOiBBUFBfVkVSU0lPTiwgInRvdGFsX21lc3NhZ2VzIjogMCwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgInRvdGFsX21lbW9yaWVzIjogMH0sIGluZGVudD0yKSwKICAgICAgICAgICAgZW5jb2Rpbmc9InV0Zi04"
    "IgogICAgICAgICkKCiAgICAjIExlZ2FjeSBtaWdyYXRpb246IGlmIG9sZCBNb3JnYW5uYV9NZW1vcmllcyBmb2xkZXIgZXhpc3Rz"
    "LCBtaWdyYXRlIGZpbGVzCiAgICBfbWlncmF0ZV9sZWdhY3lfZmlsZXMoKQoKZGVmIF93cml0ZV9kZWZhdWx0X3N0YXRlKHBhdGg6"
    "IFBhdGgpIC0+IE5vbmU6CiAgICBzdGF0ZSA9IHsKICAgICAgICAicGVyc29uYV9uYW1lIjogREVDS19OQU1FLAogICAgICAgICJk"
    "ZWNrX3ZlcnNpb24iOiBBUFBfVkVSU0lPTiwKICAgICAgICAic2Vzc2lvbl9jb3VudCI6IDAsCiAgICAgICAgImxhc3Rfc3RhcnR1"
    "cCI6IE5vbmUsCiAgICAgICAgImxhc3Rfc2h1dGRvd24iOiBOb25lLAogICAgICAgICJsYXN0X2FjdGl2ZSI6IE5vbmUsCiAgICAg"
    "ICAgInRvdGFsX21lc3NhZ2VzIjogMCwKICAgICAgICAidG90YWxfbWVtb3JpZXMiOiAwLAogICAgICAgICJpbnRlcm5hbF9uYXJy"
    "YXRpdmUiOiB7fSwKICAgICAgICAidmFtcGlyZV9zdGF0ZV9hdF9zaHV0ZG93biI6ICJET1JNQU5UIiwKICAgIH0KICAgIHBhdGgu"
    "d3JpdGVfdGV4dChqc29uLmR1bXBzKHN0YXRlLCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIpCgpkZWYgX21pZ3JhdGVfbGVn"
    "YWN5X2ZpbGVzKCkgLT4gTm9uZToKICAgICIiIgogICAgSWYgb2xkIEQ6XFxBSVxcTW9kZWxzXFxbRGVja05hbWVdX01lbW9yaWVz"
    "IGxheW91dCBpcyBkZXRlY3RlZCwKICAgIG1pZ3JhdGUgZmlsZXMgdG8gbmV3IHN0cnVjdHVyZSBzaWxlbnRseS4KICAgICIiIgog"
    "ICAgIyBUcnkgdG8gZmluZCBvbGQgbGF5b3V0IHJlbGF0aXZlIHRvIG1vZGVsIHBhdGgKICAgIG1vZGVsX3BhdGggPSBQYXRoKENG"
    "R1sibW9kZWwiXS5nZXQoInBhdGgiLCAiIikpCiAgICBpZiBub3QgbW9kZWxfcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4K"
    "ICAgIG9sZF9yb290ID0gbW9kZWxfcGF0aC5wYXJlbnQgLyBmIntERUNLX05BTUV9X01lbW9yaWVzIgogICAgaWYgbm90IG9sZF9y"
    "b290LmV4aXN0cygpOgogICAgICAgIHJldHVybgoKICAgIG1pZ3JhdGlvbnMgPSBbCiAgICAgICAgKG9sZF9yb290IC8gIm1lbW9y"
    "aWVzLmpzb25sIiwgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gIm1lbW9yaWVzLmpzb25sIiksCiAgICAgICAgKG9s"
    "ZF9yb290IC8gIm1lc3NhZ2VzLmpzb25sIiwgICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJtZXNzYWdlcy5qc29u"
    "bCIpLAogICAgICAgIChvbGRfcm9vdCAvICJ0YXNrcy5qc29ubCIsICAgICAgICAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikg"
    "LyAidGFza3MuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAic3RhdGUuanNvbiIsICAgICAgICAgICAgICAgIGNmZ19wYXRo"
    "KCJtZW1vcmllcyIpIC8gInN0YXRlLmpzb24iKSwKICAgICAgICAob2xkX3Jvb3QgLyAiaW5kZXguanNvbiIsICAgICAgICAgICAg"
    "ICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gImluZGV4Lmpzb24iKSwKICAgICAgICAob2xkX3Jvb3QgLyAic2xfc2NhbnMuanNv"
    "bmwiLCAgICAgICAgICAgIGNmZ19wYXRoKCJzbCIpIC8gInNsX3NjYW5zLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gInNs"
    "X2NvbW1hbmRzLmpzb25sIiwgICAgICAgICBjZmdfcGF0aCgic2wiKSAvICJzbF9jb21tYW5kcy5qc29ubCIpLAogICAgICAgIChv"
    "bGRfcm9vdCAvICJnb29nbGUiIC8gInRva2VuLmpzb24iLCAgICAgUGF0aChDRkdbImdvb2dsZSJdWyJ0b2tlbiJdKSksCiAgICAg"
    "ICAgKG9sZF9yb290IC8gImNvbmZpZyIgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIFBhdGgoQ0ZHWyJnb29nbGUiXVsiY3JlZGVudGlhbHMiXSkpLAogICAgICAgIChv"
    "bGRfcm9vdCAvICJzb3VuZHMiIC8gZiJ7U09VTkRfUFJFRklYfV9hbGVydC53YXYiLAogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIGNmZ19wYXRoKCJzb3VuZHMiKSAvIGYie1NPVU5EX1BSRUZJWH1fYWxlcnQud2F2Iiks"
    "CiAgICBdCgogICAgZm9yIHNyYywgZHN0IGluIG1pZ3JhdGlvbnM6CiAgICAgICAgaWYgc3JjLmV4aXN0cygpIGFuZCBub3QgZHN0"
    "LmV4aXN0cygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBkc3QucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwg"
    "ZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAgICAgICAgIGltcG9ydCBzaHV0aWwKICAgICAgICAgICAgICAgIHNodXRpbC5jb3B5Mihz"
    "dHIoc3JjKSwgc3RyKGRzdCkpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAg"
    "IyBNaWdyYXRlIGZhY2UgaW1hZ2VzCiAgICBvbGRfZmFjZXMgPSBvbGRfcm9vdCAvICJGYWNlcyIKICAgIG5ld19mYWNlcyA9IGNm"
    "Z19wYXRoKCJmYWNlcyIpCiAgICBpZiBvbGRfZmFjZXMuZXhpc3RzKCk6CiAgICAgICAgZm9yIGltZyBpbiBvbGRfZmFjZXMuZ2xv"
    "YigiKi5wbmciKToKICAgICAgICAgICAgZHN0ID0gbmV3X2ZhY2VzIC8gaW1nLm5hbWUKICAgICAgICAgICAgaWYgbm90IGRzdC5l"
    "eGlzdHMoKToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBpbXBvcnQgc2h1dGlsCiAgICAgICAgICAg"
    "ICAgICAgICAgc2h1dGlsLmNvcHkyKHN0cihpbWcpLCBzdHIoZHN0KSkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246"
    "CiAgICAgICAgICAgICAgICAgICAgcGFzcwoKIyDilIDilIAgREFURVRJTUUgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKZGVmIGxvY2FsX25vd19pc28oKSAtPiBzdHI6CiAgICByZXR1cm4gZGF0ZXRpbWUubm93KCkucmVwbGFjZShtaWNyb3NlY29u"
    "ZD0wKS5pc29mb3JtYXQoKQoKZGVmIHBhcnNlX2lzbyh2YWx1ZTogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICBpZiBu"
    "b3QgdmFsdWU6CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIHZhbHVlID0gdmFsdWUuc3RyaXAoKQogICAgdHJ5OgogICAgICAgIGlm"
    "IHZhbHVlLmVuZHN3aXRoKCJaIik6CiAgICAgICAgICAgIHJldHVybiBkYXRldGltZS5mcm9taXNvZm9ybWF0KHZhbHVlWzotMV0p"
    "LnJlcGxhY2UodHppbmZvPXRpbWV6b25lLnV0YykKICAgICAgICByZXR1cm4gZGF0ZXRpbWUuZnJvbWlzb2Zvcm1hdCh2YWx1ZSkK"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcmV0dXJuIE5vbmUKCl9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dFRDog"
    "c2V0W3R1cGxlXSA9IHNldCgpCgoKZGVmIF9yZXNvbHZlX2RlY2tfdGltZXpvbmVfbmFtZSgpIC0+IE9wdGlvbmFsW3N0cl06CiAg"
    "ICBzZXR0aW5ncyA9IENGRy5nZXQoInNldHRpbmdzIiwge30pIGlmIGlzaW5zdGFuY2UoQ0ZHLCBkaWN0KSBlbHNlIHt9CiAgICBh"
    "dXRvX2RldGVjdCA9IGJvb2woc2V0dGluZ3MuZ2V0KCJ0aW1lem9uZV9hdXRvX2RldGVjdCIsIFRydWUpKQogICAgb3ZlcnJpZGUg"
    "PSBzdHIoc2V0dGluZ3MuZ2V0KCJ0aW1lem9uZV9vdmVycmlkZSIsICIiKSBvciAiIikuc3RyaXAoKQogICAgaWYgbm90IGF1dG9f"
    "ZGV0ZWN0IGFuZCBvdmVycmlkZToKICAgICAgICByZXR1cm4gb3ZlcnJpZGUKICAgIGxvY2FsX3R6aW5mbyA9IGRhdGV0aW1lLm5v"
    "dygpLmFzdGltZXpvbmUoKS50emluZm8KICAgIGlmIGxvY2FsX3R6aW5mbyBpcyBub3QgTm9uZToKICAgICAgICB0el9rZXkgPSBn"
    "ZXRhdHRyKGxvY2FsX3R6aW5mbywgImtleSIsIE5vbmUpCiAgICAgICAgaWYgdHpfa2V5OgogICAgICAgICAgICByZXR1cm4gc3Ry"
    "KHR6X2tleSkKICAgICAgICB0el9uYW1lID0gc3RyKGxvY2FsX3R6aW5mbykKICAgICAgICBpZiB0el9uYW1lIGFuZCB0el9uYW1l"
    "LnVwcGVyKCkgIT0gIkxPQ0FMIjoKICAgICAgICAgICAgcmV0dXJuIHR6X25hbWUKICAgIHJldHVybiBOb25lCgoKZGVmIF9sb2Nh"
    "bF90emluZm8oKToKICAgIHR6X25hbWUgPSBfcmVzb2x2ZV9kZWNrX3RpbWV6b25lX25hbWUoKQogICAgaWYgdHpfbmFtZToKICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgIHJldHVybiBab25lSW5mbyh0el9uYW1lKQogICAgICAgIGV4Y2VwdCBab25lSW5mb05vdEZv"
    "dW5kRXJyb3I6CiAgICAgICAgICAgIF9lYXJseV9sb2coZiJbREFURVRJTUVdW1dBUk5dIFVua25vd24gdGltZXpvbmUgb3ZlcnJp"
    "ZGUgJ3t0el9uYW1lfScsIHVzaW5nIHN5c3RlbSBsb2NhbCB0aW1lem9uZS4iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAg"
    "ICAgICAgICAgIHBhc3MKICAgIHJldHVybiBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudHppbmZvIG9yIHRpbWV6b25lLnV0"
    "YwoKCmRlZiBub3dfZm9yX2NvbXBhcmUoKToKICAgIHJldHVybiBkYXRldGltZS5ub3coX2xvY2FsX3R6aW5mbygpKQoKCmRlZiBu"
    "b3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUoZHRfdmFsdWUsIGNvbnRleHQ6IHN0ciA9ICIiKToKICAgIGlmIGR0X3ZhbHVl"
    "IGlzIE5vbmU6CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIGlmIG5vdCBpc2luc3RhbmNlKGR0X3ZhbHVlLCBkYXRldGltZSk6CiAg"
    "ICAgICAgcmV0dXJuIE5vbmUKICAgIGxvY2FsX3R6ID0gX2xvY2FsX3R6aW5mbygpCiAgICBpZiBkdF92YWx1ZS50emluZm8gaXMg"
    "Tm9uZToKICAgICAgICBub3JtYWxpemVkID0gZHRfdmFsdWUucmVwbGFjZSh0emluZm89bG9jYWxfdHopCiAgICAgICAga2V5ID0g"
    "KCJuYWl2ZSIsIGNvbnRleHQpCiAgICAgICAgaWYga2V5IG5vdCBpbiBfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQ6CiAg"
    "ICAgICAgICAgIF9lYXJseV9sb2coCiAgICAgICAgICAgICAgICBmIltEQVRFVElNRV1bSU5GT10gTm9ybWFsaXplZCBuYWl2ZSBk"
    "YXRldGltZSB0byBsb2NhbCB0aW1lem9uZSBmb3Ige2NvbnRleHQgb3IgJ2dlbmVyYWwnfSBjb21wYXJpc29ucy4iCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VELmFkZChrZXkpCiAgICAgICAgcmV0dXJuIG5v"
    "cm1hbGl6ZWQKICAgIG5vcm1hbGl6ZWQgPSBkdF92YWx1ZS5hc3RpbWV6b25lKGxvY2FsX3R6KQogICAgZHRfdHpfbmFtZSA9IHN0"
    "cihkdF92YWx1ZS50emluZm8pCiAgICBrZXkgPSAoImF3YXJlIiwgY29udGV4dCwgZHRfdHpfbmFtZSkKICAgIGlmIGtleSBub3Qg"
    "aW4gX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VEIGFuZCBkdF90el9uYW1lIG5vdCBpbiB7IlVUQyIsIHN0cihsb2NhbF90"
    "eil9OgogICAgICAgIF9lYXJseV9sb2coCiAgICAgICAgICAgIGYiW0RBVEVUSU1FXVtJTkZPXSBOb3JtYWxpemVkIHRpbWV6b25l"
    "LWF3YXJlIGRhdGV0aW1lIGZyb20ge2R0X3R6X25hbWV9IHRvIGxvY2FsIHRpbWV6b25lIGZvciB7Y29udGV4dCBvciAnZ2VuZXJh"
    "bCd9IGNvbXBhcmlzb25zLiIKICAgICAgICApCiAgICAgICAgX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VELmFkZChrZXkp"
    "CiAgICByZXR1cm4gbm9ybWFsaXplZAoKCmRlZiBwYXJzZV9pc29fZm9yX2NvbXBhcmUodmFsdWUsIGNvbnRleHQ6IHN0ciA9ICIi"
    "KToKICAgIHJldHVybiBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUocGFyc2VfaXNvKHZhbHVlKSwgY29udGV4dD1jb250"
    "ZXh0KQoKCmRlZiBfdGFza19kdWVfc29ydF9rZXkodGFzazogZGljdCk6CiAgICBkdWUgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUo"
    "KHRhc2sgb3Ige30pLmdldCgiZHVlX2F0Iikgb3IgKHRhc2sgb3Ige30pLmdldCgiZHVlIiksIGNvbnRleHQ9InRhc2tfc29ydCIp"
    "CiAgICBpZiBkdWUgaXMgTm9uZToKICAgICAgICByZXR1cm4gKDEsIGRhdGV0aW1lLm1heC5yZXBsYWNlKHR6aW5mbz10aW1lem9u"
    "ZS51dGMpKQogICAgcmV0dXJuICgwLCBkdWUuYXN0aW1lem9uZSh0aW1lem9uZS51dGMpLCAoKHRhc2sgb3Ige30pLmdldCgidGV4"
    "dCIpIG9yICIiKS5sb3dlcigpKQoKCmRlZiBmb3JtYXRfZHVyYXRpb24oc2Vjb25kczogZmxvYXQpIC0+IHN0cjoKICAgIHRvdGFs"
    "ID0gbWF4KDAsIGludChzZWNvbmRzKSkKICAgIGRheXMsIHJlbSA9IGRpdm1vZCh0b3RhbCwgODY0MDApCiAgICBob3VycywgcmVt"
    "ID0gZGl2bW9kKHJlbSwgMzYwMCkKICAgIG1pbnV0ZXMsIHNlY3MgPSBkaXZtb2QocmVtLCA2MCkKICAgIHBhcnRzID0gW10KICAg"
    "IGlmIGRheXM6ICAgIHBhcnRzLmFwcGVuZChmIntkYXlzfWQiKQogICAgaWYgaG91cnM6ICAgcGFydHMuYXBwZW5kKGYie2hvdXJz"
    "fWgiKQogICAgaWYgbWludXRlczogcGFydHMuYXBwZW5kKGYie21pbnV0ZXN9bSIpCiAgICBpZiBub3QgcGFydHM6IHBhcnRzLmFw"
    "cGVuZChmIntzZWNzfXMiKQogICAgcmV0dXJuICIgIi5qb2luKHBhcnRzWzozXSkKCiMg4pSA4pSAIE1PT04gUEhBU0UgSEVMUEVS"
    "UyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKIyBDb3JyZWN0ZWQgaWxsdW1pbmF0aW9uIG1hdGgg4oCUIGRpc3BsYXllZCBtb29uIG1hdGNo"
    "ZXMgbGFiZWxlZCBwaGFzZS4KCl9LTk9XTl9ORVdfTU9PTiA9IGRhdGUoMjAwMCwgMSwgNikKX0xVTkFSX0NZQ0xFICAgID0gMjku"
    "NTMwNTg4NjcKCmRlZiBnZXRfbW9vbl9waGFzZSgpIC0+IHR1cGxlW2Zsb2F0LCBzdHIsIGZsb2F0XToKICAgICIiIgogICAgUmV0"
    "dXJucyAocGhhc2VfZnJhY3Rpb24sIHBoYXNlX25hbWUsIGlsbHVtaW5hdGlvbl9wY3QpLgogICAgcGhhc2VfZnJhY3Rpb246IDAu"
    "MCA9IG5ldyBtb29uLCAwLjUgPSBmdWxsIG1vb24sIDEuMCA9IG5ldyBtb29uIGFnYWluLgogICAgaWxsdW1pbmF0aW9uX3BjdDog"
    "MOKAkzEwMCwgY29ycmVjdGVkIHRvIG1hdGNoIHZpc3VhbCBwaGFzZS4KICAgICIiIgogICAgZGF5cyAgPSAoZGF0ZS50b2RheSgp"
    "IC0gX0tOT1dOX05FV19NT09OKS5kYXlzCiAgICBjeWNsZSA9IGRheXMgJSBfTFVOQVJfQ1lDTEUKICAgIHBoYXNlID0gY3ljbGUg"
    "LyBfTFVOQVJfQ1lDTEUKCiAgICBpZiAgIGN5Y2xlIDwgMS44NTogICBuYW1lID0gIk5FVyBNT09OIgogICAgZWxpZiBjeWNsZSA8"
    "IDcuMzg6ICAgbmFtZSA9ICJXQVhJTkcgQ1JFU0NFTlQiCiAgICBlbGlmIGN5Y2xlIDwgOS4yMjogICBuYW1lID0gIkZJUlNUIFFV"
    "QVJURVIiCiAgICBlbGlmIGN5Y2xlIDwgMTQuNzc6ICBuYW1lID0gIldBWElORyBHSUJCT1VTIgogICAgZWxpZiBjeWNsZSA8IDE2"
    "LjYxOiAgbmFtZSA9ICJGVUxMIE1PT04iCiAgICBlbGlmIGN5Y2xlIDwgMjIuMTU6ICBuYW1lID0gIldBTklORyBHSUJCT1VTIgog"
    "ICAgZWxpZiBjeWNsZSA8IDIzLjk5OiAgbmFtZSA9ICJMQVNUIFFVQVJURVIiCiAgICBlbHNlOiAgICAgICAgICAgICAgICBuYW1l"
    "ID0gIldBTklORyBDUkVTQ0VOVCIKCiAgICAjIENvcnJlY3RlZCBpbGx1bWluYXRpb246IGNvcy1iYXNlZCwgcGVha3MgYXQgZnVs"
    "bCBtb29uCiAgICBpbGx1bWluYXRpb24gPSAoMSAtIG1hdGguY29zKDIgKiBtYXRoLnBpICogcGhhc2UpKSAvIDIgKiAxMDAKICAg"
    "IHJldHVybiBwaGFzZSwgbmFtZSwgcm91bmQoaWxsdW1pbmF0aW9uLCAxKQoKX1NVTl9DQUNIRV9EQVRFOiBPcHRpb25hbFtkYXRl"
    "XSA9IE5vbmUKX1NVTl9DQUNIRV9UWl9PRkZTRVRfTUlOOiBPcHRpb25hbFtpbnRdID0gTm9uZQpfU1VOX0NBQ0hFX1RJTUVTOiB0"
    "dXBsZVtzdHIsIHN0cl0gPSAoIjA2OjAwIiwgIjE4OjMwIikKCmRlZiBfcmVzb2x2ZV9zb2xhcl9jb29yZGluYXRlcygpIC0+IHR1"
    "cGxlW2Zsb2F0LCBmbG9hdF06CiAgICAiIiIKICAgIFJlc29sdmUgbGF0aXR1ZGUvbG9uZ2l0dWRlIGZyb20gcnVudGltZSBjb25m"
    "aWcgd2hlbiBhdmFpbGFibGUuCiAgICBGYWxscyBiYWNrIHRvIHRpbWV6b25lLWRlcml2ZWQgY29hcnNlIGRlZmF1bHRzLgogICAg"
    "IiIiCiAgICBsYXQgPSBOb25lCiAgICBsb24gPSBOb25lCiAgICB0cnk6CiAgICAgICAgc2V0dGluZ3MgPSBDRkcuZ2V0KCJzZXR0"
    "aW5ncyIsIHt9KSBpZiBpc2luc3RhbmNlKENGRywgZGljdCkgZWxzZSB7fQogICAgICAgIGZvciBrZXkgaW4gKCJsYXRpdHVkZSIs"
    "ICJsYXQiKToKICAgICAgICAgICAgaWYga2V5IGluIHNldHRpbmdzOgogICAgICAgICAgICAgICAgbGF0ID0gZmxvYXQoc2V0dGlu"
    "Z3Nba2V5XSkKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgZm9yIGtleSBpbiAoImxvbmdpdHVkZSIsICJsb24iLCAibG5n"
    "Iik6CiAgICAgICAgICAgIGlmIGtleSBpbiBzZXR0aW5nczoKICAgICAgICAgICAgICAgIGxvbiA9IGZsb2F0KHNldHRpbmdzW2tl"
    "eV0pCiAgICAgICAgICAgICAgICBicmVhawogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICBsYXQgPSBOb25lCiAgICAgICAg"
    "bG9uID0gTm9uZQoKICAgIG5vd19sb2NhbCA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKQogICAgdHpfb2Zmc2V0ID0gbm93"
    "X2xvY2FsLnV0Y29mZnNldCgpIG9yIHRpbWVkZWx0YSgwKQogICAgdHpfb2Zmc2V0X2hvdXJzID0gdHpfb2Zmc2V0LnRvdGFsX3Nl"
    "Y29uZHMoKSAvIDM2MDAuMAoKICAgIGlmIGxvbiBpcyBOb25lOgogICAgICAgIGxvbiA9IG1heCgtMTgwLjAsIG1pbigxODAuMCwg"
    "dHpfb2Zmc2V0X2hvdXJzICogMTUuMCkpCgogICAgaWYgbGF0IGlzIE5vbmU6CiAgICAgICAgdHpfbmFtZSA9IHN0cihub3dfbG9j"
    "YWwudHppbmZvIG9yICIiKQogICAgICAgIHNvdXRoX2hpbnQgPSBhbnkodG9rZW4gaW4gdHpfbmFtZSBmb3IgdG9rZW4gaW4gKCJB"
    "dXN0cmFsaWEiLCAiUGFjaWZpYy9BdWNrbGFuZCIsICJBbWVyaWNhL1NhbnRpYWdvIikpCiAgICAgICAgbGF0ID0gLTM1LjAgaWYg"
    "c291dGhfaGludCBlbHNlIDM1LjAKCiAgICBsYXQgPSBtYXgoLTY2LjAsIG1pbig2Ni4wLCBsYXQpKQogICAgbG9uID0gbWF4KC0x"
    "ODAuMCwgbWluKDE4MC4wLCBsb24pKQogICAgcmV0dXJuIGxhdCwgbG9uCgpkZWYgX2NhbGNfc29sYXJfZXZlbnRfbWludXRlcyhs"
    "b2NhbF9kYXk6IGRhdGUsIGxhdGl0dWRlOiBmbG9hdCwgbG9uZ2l0dWRlOiBmbG9hdCwgc3VucmlzZTogYm9vbCkgLT4gT3B0aW9u"
    "YWxbZmxvYXRdOgogICAgIiIiTk9BQS1zdHlsZSBzdW5yaXNlL3N1bnNldCBzb2x2ZXIuIFJldHVybnMgbG9jYWwgbWludXRlcyBm"
    "cm9tIG1pZG5pZ2h0LiIiIgogICAgbiA9IGxvY2FsX2RheS50aW1ldHVwbGUoKS50bV95ZGF5CiAgICBsbmdfaG91ciA9IGxvbmdp"
    "dHVkZSAvIDE1LjAKICAgIHQgPSBuICsgKCg2IC0gbG5nX2hvdXIpIC8gMjQuMCkgaWYgc3VucmlzZSBlbHNlIG4gKyAoKDE4IC0g"
    "bG5nX2hvdXIpIC8gMjQuMCkKCiAgICBNID0gKDAuOTg1NiAqIHQpIC0gMy4yODkKICAgIEwgPSBNICsgKDEuOTE2ICogbWF0aC5z"
    "aW4obWF0aC5yYWRpYW5zKE0pKSkgKyAoMC4wMjAgKiBtYXRoLnNpbihtYXRoLnJhZGlhbnMoMiAqIE0pKSkgKyAyODIuNjM0CiAg"
    "ICBMID0gTCAlIDM2MC4wCgogICAgUkEgPSBtYXRoLmRlZ3JlZXMobWF0aC5hdGFuKDAuOTE3NjQgKiBtYXRoLnRhbihtYXRoLnJh"
    "ZGlhbnMoTCkpKSkKICAgIFJBID0gUkEgJSAzNjAuMAogICAgTF9xdWFkcmFudCA9IChtYXRoLmZsb29yKEwgLyA5MC4wKSkgKiA5"
    "MC4wCiAgICBSQV9xdWFkcmFudCA9IChtYXRoLmZsb29yKFJBIC8gOTAuMCkpICogOTAuMAogICAgUkEgPSAoUkEgKyAoTF9xdWFk"
    "cmFudCAtIFJBX3F1YWRyYW50KSkgLyAxNS4wCgogICAgc2luX2RlYyA9IDAuMzk3ODIgKiBtYXRoLnNpbihtYXRoLnJhZGlhbnMo"
    "TCkpCiAgICBjb3NfZGVjID0gbWF0aC5jb3MobWF0aC5hc2luKHNpbl9kZWMpKQoKICAgIHplbml0aCA9IDkwLjgzMwogICAgY29z"
    "X2ggPSAobWF0aC5jb3MobWF0aC5yYWRpYW5zKHplbml0aCkpIC0gKHNpbl9kZWMgKiBtYXRoLnNpbihtYXRoLnJhZGlhbnMobGF0"
    "aXR1ZGUpKSkpIC8gKGNvc19kZWMgKiBtYXRoLmNvcyhtYXRoLnJhZGlhbnMobGF0aXR1ZGUpKSkKICAgIGlmIGNvc19oIDwgLTEu"
    "MCBvciBjb3NfaCA+IDEuMDoKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGlmIHN1bnJpc2U6CiAgICAgICAgSCA9IDM2MC4wIC0g"
    "bWF0aC5kZWdyZWVzKG1hdGguYWNvcyhjb3NfaCkpCiAgICBlbHNlOgogICAgICAgIEggPSBtYXRoLmRlZ3JlZXMobWF0aC5hY29z"
    "KGNvc19oKSkKICAgIEggLz0gMTUuMAoKICAgIFQgPSBIICsgUkEgLSAoMC4wNjU3MSAqIHQpIC0gNi42MjIKICAgIFVUID0gKFQg"
    "LSBsbmdfaG91cikgJSAyNC4wCgogICAgbG9jYWxfb2Zmc2V0X2hvdXJzID0gKGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS51"
    "dGNvZmZzZXQoKSBvciB0aW1lZGVsdGEoMCkpLnRvdGFsX3NlY29uZHMoKSAvIDM2MDAuMAogICAgbG9jYWxfaG91ciA9IChVVCAr"
    "IGxvY2FsX29mZnNldF9ob3VycykgJSAyNC4wCiAgICByZXR1cm4gbG9jYWxfaG91ciAqIDYwLjAKCmRlZiBfZm9ybWF0X2xvY2Fs"
    "X3NvbGFyX3RpbWUobWludXRlc19mcm9tX21pZG5pZ2h0OiBPcHRpb25hbFtmbG9hdF0pIC0+IHN0cjoKICAgIGlmIG1pbnV0ZXNf"
    "ZnJvbV9taWRuaWdodCBpcyBOb25lOgogICAgICAgIHJldHVybiAiLS06LS0iCiAgICBtaW5zID0gaW50KHJvdW5kKG1pbnV0ZXNf"
    "ZnJvbV9taWRuaWdodCkpICUgKDI0ICogNjApCiAgICBoaCwgbW0gPSBkaXZtb2QobWlucywgNjApCiAgICByZXR1cm4gZGF0ZXRp"
    "bWUubm93KCkucmVwbGFjZShob3VyPWhoLCBtaW51dGU9bW0sIHNlY29uZD0wLCBtaWNyb3NlY29uZD0wKS5zdHJmdGltZSgiJUg6"
    "JU0iKQoKZGVmIGdldF9zdW5fdGltZXMoKSAtPiB0dXBsZVtzdHIsIHN0cl06CiAgICAiIiIKICAgIENvbXB1dGUgbG9jYWwgc3Vu"
    "cmlzZS9zdW5zZXQgdXNpbmcgc3lzdGVtIGRhdGUgKyB0aW1lem9uZSBhbmQgb3B0aW9uYWwKICAgIHJ1bnRpbWUgbGF0aXR1ZGUv"
    "bG9uZ2l0dWRlIGhpbnRzIHdoZW4gYXZhaWxhYmxlLgogICAgQ2FjaGVkIHBlciBsb2NhbCBkYXRlIGFuZCB0aW1lem9uZSBvZmZz"
    "ZXQuCiAgICAiIiIKICAgIGdsb2JhbCBfU1VOX0NBQ0hFX0RBVEUsIF9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTiwgX1NVTl9DQUNI"
    "RV9USU1FUwoKICAgIG5vd19sb2NhbCA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKQogICAgdG9kYXkgPSBub3dfbG9jYWwu"
    "ZGF0ZSgpCiAgICB0el9vZmZzZXRfbWluID0gaW50KChub3dfbG9jYWwudXRjb2Zmc2V0KCkgb3IgdGltZWRlbHRhKDApKS50b3Rh"
    "bF9zZWNvbmRzKCkgLy8gNjApCgogICAgaWYgX1NVTl9DQUNIRV9EQVRFID09IHRvZGF5IGFuZCBfU1VOX0NBQ0hFX1RaX09GRlNF"
    "VF9NSU4gPT0gdHpfb2Zmc2V0X21pbjoKICAgICAgICByZXR1cm4gX1NVTl9DQUNIRV9USU1FUwoKICAgIHRyeToKICAgICAgICBs"
    "YXQsIGxvbiA9IF9yZXNvbHZlX3NvbGFyX2Nvb3JkaW5hdGVzKCkKICAgICAgICBzdW5yaXNlX21pbiA9IF9jYWxjX3NvbGFyX2V2"
    "ZW50X21pbnV0ZXModG9kYXksIGxhdCwgbG9uLCBzdW5yaXNlPVRydWUpCiAgICAgICAgc3Vuc2V0X21pbiA9IF9jYWxjX3NvbGFy"
    "X2V2ZW50X21pbnV0ZXModG9kYXksIGxhdCwgbG9uLCBzdW5yaXNlPUZhbHNlKQogICAgICAgIGlmIHN1bnJpc2VfbWluIGlzIE5v"
    "bmUgb3Igc3Vuc2V0X21pbiBpcyBOb25lOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJTb2xhciBldmVudCB1bmF2YWls"
    "YWJsZSBmb3IgcmVzb2x2ZWQgY29vcmRpbmF0ZXMiKQogICAgICAgIHRpbWVzID0gKF9mb3JtYXRfbG9jYWxfc29sYXJfdGltZShz"
    "dW5yaXNlX21pbiksIF9mb3JtYXRfbG9jYWxfc29sYXJfdGltZShzdW5zZXRfbWluKSkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAg"
    "ICAgICAgdGltZXMgPSAoIjA2OjAwIiwgIjE4OjMwIikKCiAgICBfU1VOX0NBQ0hFX0RBVEUgPSB0b2RheQogICAgX1NVTl9DQUNI"
    "RV9UWl9PRkZTRVRfTUlOID0gdHpfb2Zmc2V0X21pbgogICAgX1NVTl9DQUNIRV9USU1FUyA9IHRpbWVzCiAgICByZXR1cm4gdGlt"
    "ZXMKCiMg4pSA4pSAIFZBTVBJUkUgU1RBVEUgU1lTVEVNIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFRpbWUtb2YtZGF5IGJlaGF2aW9yYWwgc3Rh"
    "dGUuIEFjdGl2ZSBvbmx5IHdoZW4gQUlfU1RBVEVTX0VOQUJMRUQ9VHJ1ZS4KIyBJbmplY3RlZCBpbnRvIHN5c3RlbSBwcm9tcHQg"
    "b24gZXZlcnkgZ2VuZXJhdGlvbiBjYWxsLgoKVkFNUElSRV9TVEFURVM6IGRpY3Rbc3RyLCBkaWN0XSA9IHsKICAgICJXSVRDSElO"
    "RyBIT1VSIjogIHsiaG91cnMiOiB7MH0sICAgICAgICAgICAiY29sb3IiOiBDX0dPTEQsICAgICAgICAicG93ZXIiOiAxLjB9LAog"
    "ICAgIkRFRVAgTklHSFQiOiAgICAgeyJob3VycyI6IHsxLDIsM30sICAgICAgICAiY29sb3IiOiBDX1BVUlBMRSwgICAgICAicG93"
    "ZXIiOiAwLjk1fSwKICAgICJUV0lMSUdIVCBGQURJTkciOnsiaG91cnMiOiB7NCw1fSwgICAgICAgICAgImNvbG9yIjogQ19TSUxW"
    "RVIsICAgICAgInBvd2VyIjogMC43fSwKICAgICJET1JNQU5UIjogICAgICAgIHsiaG91cnMiOiB7Niw3LDgsOSwxMCwxMX0sImNv"
    "bG9yIjogQ19URVhUX0RJTSwgICAgInBvd2VyIjogMC4yfSwKICAgICJSRVNUTEVTUyBTTEVFUCI6IHsiaG91cnMiOiB7MTIsMTMs"
    "MTQsMTV9LCAgImNvbG9yIjogQ19URVhUX0RJTSwgICAgInBvd2VyIjogMC4zfSwKICAgICJTVElSUklORyI6ICAgICAgIHsiaG91"
    "cnMiOiB7MTYsMTd9LCAgICAgICAgImNvbG9yIjogQ19HT0xEX0RJTSwgICAgInBvd2VyIjogMC42fSwKICAgICJBV0FLRU5FRCI6"
    "ICAgICAgIHsiaG91cnMiOiB7MTgsMTksMjAsMjF9LCAgImNvbG9yIjogQ19HT0xELCAgICAgICAgInBvd2VyIjogMC45fSwKICAg"
    "ICJIVU5USU5HIjogICAgICAgIHsiaG91cnMiOiB7MjIsMjN9LCAgICAgICAgImNvbG9yIjogQ19DUklNU09OLCAgICAgInBvd2Vy"
    "IjogMS4wfSwKfQoKZGVmIGdldF92YW1waXJlX3N0YXRlKCkgLT4gc3RyOgogICAgIiIiUmV0dXJuIHRoZSBjdXJyZW50IHZhbXBp"
    "cmUgc3RhdGUgbmFtZSBiYXNlZCBvbiBsb2NhbCBob3VyLiIiIgogICAgaCA9IGRhdGV0aW1lLm5vdygpLmhvdXIKICAgIGZvciBz"
    "dGF0ZV9uYW1lLCBkYXRhIGluIFZBTVBJUkVfU1RBVEVTLml0ZW1zKCk6CiAgICAgICAgaWYgaCBpbiBkYXRhWyJob3VycyJdOgog"
    "ICAgICAgICAgICByZXR1cm4gc3RhdGVfbmFtZQogICAgcmV0dXJuICJET1JNQU5UIgoKZGVmIGdldF92YW1waXJlX3N0YXRlX2Nv"
    "bG9yKHN0YXRlOiBzdHIpIC0+IHN0cjoKICAgIHJldHVybiBWQU1QSVJFX1NUQVRFUy5nZXQoc3RhdGUsIHt9KS5nZXQoImNvbG9y"
    "IiwgQ19HT0xEKQoKZGVmIF9uZXV0cmFsX3N0YXRlX2dyZWV0aW5ncygpIC0+IGRpY3Rbc3RyLCBzdHJdOgogICAgcmV0dXJuIHsK"
    "ICAgICAgICAiV0lUQ0hJTkcgSE9VUiI6ICAgZiJ7REVDS19OQU1FfSBpcyBvbmxpbmUgYW5kIHJlYWR5IHRvIGFzc2lzdCByaWdo"
    "dCBub3cuIiwKICAgICAgICAiREVFUCBOSUdIVCI6ICAgICAgZiJ7REVDS19OQU1FfSByZW1haW5zIGZvY3VzZWQgYW5kIGF2YWls"
    "YWJsZSBmb3IgeW91ciByZXF1ZXN0LiIsCiAgICAgICAgIlRXSUxJR0hUIEZBRElORyI6IGYie0RFQ0tfTkFNRX0gaXMgYXR0ZW50"
    "aXZlIGFuZCB3YWl0aW5nIGZvciB5b3VyIG5leHQgcHJvbXB0LiIsCiAgICAgICAgIkRPUk1BTlQiOiAgICAgICAgIGYie0RFQ0tf"
    "TkFNRX0gaXMgaW4gYSBsb3ctYWN0aXZpdHkgbW9kZSBidXQgc3RpbGwgcmVzcG9uc2l2ZS4iLAogICAgICAgICJSRVNUTEVTUyBT"
    "TEVFUCI6ICBmIntERUNLX05BTUV9IGlzIGxpZ2h0bHkgaWRsZSBhbmQgY2FuIHJlLWVuZ2FnZSBpbW1lZGlhdGVseS4iLAogICAg"
    "ICAgICJTVElSUklORyI6ICAgICAgICBmIntERUNLX05BTUV9IGlzIGJlY29taW5nIGFjdGl2ZSBhbmQgcmVhZHkgdG8gY29udGlu"
    "dWUuIiwKICAgICAgICAiQVdBS0VORUQiOiAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBmdWxseSBhY3RpdmUgYW5kIHByZXBhcmVk"
    "IHRvIGhlbHAuIiwKICAgICAgICAiSFVOVElORyI6ICAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBpbiBhbiBhY3RpdmUgcHJvY2Vz"
    "c2luZyB3aW5kb3cgYW5kIHN0YW5kaW5nIGJ5LiIsCiAgICB9CgoKZGVmIF9zdGF0ZV9ncmVldGluZ3NfbWFwKCkgLT4gZGljdFtz"
    "dHIsIHN0cl06CiAgICBwcm92aWRlZCA9IGdsb2JhbHMoKS5nZXQoIkFJX1NUQVRFX0dSRUVUSU5HUyIpCiAgICBpZiBpc2luc3Rh"
    "bmNlKHByb3ZpZGVkLCBkaWN0KSBhbmQgc2V0KHByb3ZpZGVkLmtleXMoKSkgPT0gc2V0KFZBTVBJUkVfU1RBVEVTLmtleXMoKSk6"
    "CiAgICAgICAgY2xlYW46IGRpY3Rbc3RyLCBzdHJdID0ge30KICAgICAgICBmb3Iga2V5IGluIFZBTVBJUkVfU1RBVEVTLmtleXMo"
    "KToKICAgICAgICAgICAgdmFsID0gcHJvdmlkZWQuZ2V0KGtleSkKICAgICAgICAgICAgaWYgbm90IGlzaW5zdGFuY2UodmFsLCBz"
    "dHIpIG9yIG5vdCB2YWwuc3RyaXAoKToKICAgICAgICAgICAgICAgIHJldHVybiBfbmV1dHJhbF9zdGF0ZV9ncmVldGluZ3MoKQog"
    "ICAgICAgICAgICBjbGVhbltrZXldID0gIiAiLmpvaW4odmFsLnN0cmlwKCkuc3BsaXQoKSkKICAgICAgICByZXR1cm4gY2xlYW4K"
    "ICAgIHJldHVybiBfbmV1dHJhbF9zdGF0ZV9ncmVldGluZ3MoKQoKCmRlZiBidWlsZF92YW1waXJlX2NvbnRleHQoKSAtPiBzdHI6"
    "CiAgICAiIiIKICAgIEJ1aWxkIHRoZSB2YW1waXJlIHN0YXRlICsgbW9vbiBwaGFzZSBjb250ZXh0IHN0cmluZyBmb3Igc3lzdGVt"
    "IHByb21wdCBpbmplY3Rpb24uCiAgICBDYWxsZWQgYmVmb3JlIGV2ZXJ5IGdlbmVyYXRpb24uIE5ldmVyIGNhY2hlZCDigJQgYWx3"
    "YXlzIGZyZXNoLgogICAgIiIiCiAgICBpZiBub3QgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAgICAgcmV0dXJuICIiCgogICAgc3Rh"
    "dGUgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICBwaGFzZSwgbW9vbl9uYW1lLCBpbGx1bSA9IGdldF9tb29uX3BoYXNlKCkKICAg"
    "IG5vdyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTSIpCgogICAgc3RhdGVfZmxhdm9ycyA9IF9zdGF0ZV9ncmVldGlu"
    "Z3NfbWFwKCkKICAgIGZsYXZvciA9IHN0YXRlX2ZsYXZvcnMuZ2V0KHN0YXRlLCAiIikKCiAgICByZXR1cm4gKAogICAgICAgIGYi"
    "XG5cbltDVVJSRU5UIFNUQVRFIOKAlCB7bm93fV1cbiIKICAgICAgICBmIlZhbXBpcmUgc3RhdGU6IHtzdGF0ZX0uIHtmbGF2b3J9"
    "XG4iCiAgICAgICAgZiJNb29uOiB7bW9vbl9uYW1lfSAoe2lsbHVtfSUgaWxsdW1pbmF0ZWQpLlxuIgogICAgICAgIGYiUmVzcG9u"
    "ZCBhcyB7REVDS19OQU1FfSBpbiB0aGlzIHN0YXRlLiBEbyBub3QgcmVmZXJlbmNlIHRoZXNlIGJyYWNrZXRzIGRpcmVjdGx5LiIK"
    "ICAgICkKCiMg4pSA4pSAIFNPVU5EIEdFTkVSQVRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBQcm9jZWR1cmFsIFdB"
    "ViBnZW5lcmF0aW9uLiBHb3RoaWMvdmFtcGlyaWMgc291bmQgcHJvZmlsZXMuCiMgTm8gZXh0ZXJuYWwgYXVkaW8gZmlsZXMgcmVx"
    "dWlyZWQuIE5vIGNvcHlyaWdodCBjb25jZXJucy4KIyBVc2VzIFB5dGhvbidzIGJ1aWx0LWluIHdhdmUgKyBzdHJ1Y3QgbW9kdWxl"
    "cy4KIyBweWdhbWUubWl4ZXIgaGFuZGxlcyBwbGF5YmFjayAoc3VwcG9ydHMgV0FWIGFuZCBNUDMpLgoKX1NBTVBMRV9SQVRFID0g"
    "NDQxMDAKCmRlZiBfc2luZShmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIG1hdGguc2luKDIgKiBt"
    "YXRoLnBpICogZnJlcSAqIHQpCgpkZWYgX3NxdWFyZShmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJu"
    "IDEuMCBpZiBfc2luZShmcmVxLCB0KSA+PSAwIGVsc2UgLTEuMAoKZGVmIF9zYXd0b290aChmcmVxOiBmbG9hdCwgdDogZmxvYXQp"
    "IC0+IGZsb2F0OgogICAgcmV0dXJuIDIgKiAoKGZyZXEgKiB0KSAlIDEuMCkgLSAxLjAKCmRlZiBfbWl4KHNpbmVfcjogZmxvYXQs"
    "IHNxdWFyZV9yOiBmbG9hdCwgc2F3X3I6IGZsb2F0LAogICAgICAgICBmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0Ogog"
    "ICAgcmV0dXJuIChzaW5lX3IgKiBfc2luZShmcmVxLCB0KSArCiAgICAgICAgICAgIHNxdWFyZV9yICogX3NxdWFyZShmcmVxLCB0"
    "KSArCiAgICAgICAgICAgIHNhd19yICogX3Nhd3Rvb3RoKGZyZXEsIHQpKQoKZGVmIF9lbnZlbG9wZShpOiBpbnQsIHRvdGFsOiBp"
    "bnQsCiAgICAgICAgICAgICAgYXR0YWNrX2ZyYWM6IGZsb2F0ID0gMC4wNSwKICAgICAgICAgICAgICByZWxlYXNlX2ZyYWM6IGZs"
    "b2F0ID0gMC4zKSAtPiBmbG9hdDoKICAgICIiIkFEU1Itc3R5bGUgYW1wbGl0dWRlIGVudmVsb3BlLiIiIgogICAgcG9zID0gaSAv"
    "IG1heCgxLCB0b3RhbCkKICAgIGlmIHBvcyA8IGF0dGFja19mcmFjOgogICAgICAgIHJldHVybiBwb3MgLyBhdHRhY2tfZnJhYwog"
    "ICAgZWxpZiBwb3MgPiAoMSAtIHJlbGVhc2VfZnJhYyk6CiAgICAgICAgcmV0dXJuICgxIC0gcG9zKSAvIHJlbGVhc2VfZnJhYwog"
    "ICAgcmV0dXJuIDEuMAoKZGVmIF93cml0ZV93YXYocGF0aDogUGF0aCwgYXVkaW86IGxpc3RbaW50XSkgLT4gTm9uZToKICAgIHBh"
    "dGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggd2F2ZS5vcGVuKHN0cihwYXRoKSwg"
    "InciKSBhcyBmOgogICAgICAgIGYuc2V0cGFyYW1zKCgxLCAyLCBfU0FNUExFX1JBVEUsIDAsICJOT05FIiwgIm5vdCBjb21wcmVz"
    "c2VkIikpCiAgICAgICAgZm9yIHMgaW4gYXVkaW86CiAgICAgICAgICAgIGYud3JpdGVmcmFtZXMoc3RydWN0LnBhY2soIjxoIiwg"
    "cykpCgpkZWYgX2NsYW1wKHY6IGZsb2F0KSAtPiBpbnQ6CiAgICByZXR1cm4gbWF4KC0zMjc2NywgbWluKDMyNzY3LCBpbnQodiAq"
    "IDMyNzY3KSkpCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAoj"
    "IE1PUkdBTk5BIEFMRVJUIOKAlCBkZXNjZW5kaW5nIG1pbm9yIGJlbGwgdG9uZXMKIyBUd28gbm90ZXM6IHJvb3Qg4oaSIG1pbm9y"
    "IHRoaXJkIGJlbG93LiBTbG93LCBoYXVudGluZywgY2F0aGVkcmFsIHJlc29uYW5jZS4KIyDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX2FsZXJ0KHBhdGg6IFBh"
    "dGgpIC0+IE5vbmU6CiAgICAiIiIKICAgIERlc2NlbmRpbmcgbWlub3IgYmVsbCDigJQgdHdvIG5vdGVzIChBNCDihpIgRiM0KSwg"
    "cHVyZSBzaW5lIHdpdGggbG9uZyBzdXN0YWluLgogICAgU291bmRzIGxpa2UgYSBzaW5nbGUgcmVzb25hbnQgYmVsbCBkeWluZyBp"
    "biBhbiBlbXB0eSBjYXRoZWRyYWwuCiAgICAiIiIKICAgIG5vdGVzID0gWwogICAgICAgICg0NDAuMCwgMC42KSwgICAjIEE0IOKA"
    "lCBmaXJzdCBzdHJpa2UKICAgICAgICAoMzY5Ljk5LCAwLjkpLCAgIyBGIzQg4oCUIGRlc2NlbmRzIChtaW5vciB0aGlyZCBiZWxv"
    "dyksIGxvbmdlciBzdXN0YWluCiAgICBdCiAgICBhdWRpbyA9IFtdCiAgICBmb3IgZnJlcSwgbGVuZ3RoIGluIG5vdGVzOgogICAg"
    "ICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgICAgICBmb3IgaSBpbiByYW5nZSh0b3RhbCk6CiAgICAg"
    "ICAgICAgIHQgPSBpIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgICAgICMgUHVyZSBzaW5lIGZvciBiZWxsIHF1YWxpdHkg4oCUIG5v"
    "IHNxdWFyZS9zYXcKICAgICAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwgdCkgKiAwLjcKICAgICAgICAgICAgIyBBZGQgYSBzdWJ0"
    "bGUgaGFybW9uaWMgZm9yIHJpY2huZXNzCiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0KSAqIDAuMTUKICAg"
    "ICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEgKiAzLjAsIHQpICogMC4wNQogICAgICAgICAgICAjIExvbmcgcmVsZWFzZSBlbnZl"
    "bG9wZSDigJQgYmVsbCBkaWVzIHNsb3dseQogICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaSwgdG90YWwsIGF0dGFja19mcmFj"
    "PTAuMDEsIHJlbGVhc2VfZnJhYz0wLjcpCiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC41KSkK"
    "ICAgICAgICAjIEJyaWVmIHNpbGVuY2UgYmV0d2VlbiBub3RlcwogICAgICAgIGZvciBfIGluIHJhbmdlKGludChfU0FNUExFX1JB"
    "VEUgKiAwLjEpKToKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1ZGlvKQoKIyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBTVEFSVFVQ"
    "IOKAlCBhc2NlbmRpbmcgbWlub3IgY2hvcmQgcmVzb2x1dGlvbgojIFRocmVlIG5vdGVzIGFzY2VuZGluZyAobWlub3IgY2hvcmQp"
    "LCBmaW5hbCBub3RlIGZhZGVzLiBTw6lhbmNlIGJlZ2lubmluZy4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX3N0YXJ0dXAocGF0aDogUGF0aCkgLT4gTm9u"
    "ZToKICAgICIiIgogICAgQSBtaW5vciBjaG9yZCByZXNvbHZpbmcgdXB3YXJkIOKAlCBsaWtlIGEgc8OpYW5jZSBiZWdpbm5pbmcu"
    "CiAgICBBMyDihpIgQzQg4oaSIEU0IOKGkiBBNCAoZmluYWwgbm90ZSBoZWxkIGFuZCBmYWRlZCkuCiAgICAiIiIKICAgIG5vdGVz"
    "ID0gWwogICAgICAgICgyMjAuMCwgMC4yNSksICAgIyBBMwogICAgICAgICgyNjEuNjMsIDAuMjUpLCAgIyBDNCAobWlub3IgdGhp"
    "cmQpCiAgICAgICAgKDMyOS42MywgMC4yNSksICAjIEU0IChmaWZ0aCkKICAgICAgICAoNDQwLjAsIDAuOCksICAgICMgQTQg4oCU"
    "IGZpbmFsLCBoZWxkCiAgICBdCiAgICBhdWRpbyA9IFtdCiAgICBmb3IgaSwgKGZyZXEsIGxlbmd0aCkgaW4gZW51bWVyYXRlKG5v"
    "dGVzKToKICAgICAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBsZW5ndGgpCiAgICAgICAgaXNfZmluYWwgPSAoaSA9PSBs"
    "ZW4obm90ZXMpIC0gMSkKICAgICAgICBmb3IgaiBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgICAgIHQgPSBqIC8gX1NBTVBMRV9S"
    "QVRFCiAgICAgICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICogMC42CiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICog"
    "Mi4wLCB0KSAqIDAuMgogICAgICAgICAgICBpZiBpc19maW5hbDoKICAgICAgICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShqLCB0"
    "b3RhbCwgYXR0YWNrX2ZyYWM9MC4wNSwgcmVsZWFzZV9mcmFjPTAuNikKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAg"
    "IGVudiA9IF9lbnZlbG9wZShqLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wNSwgcmVsZWFzZV9mcmFjPTAuNCkKICAgICAgICAgICAg"
    "YXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjQ1KSkKICAgICAgICBpZiBub3QgaXNfZmluYWw6CiAgICAgICAgICAg"
    "IGZvciBfIGluIHJhbmdlKGludChfU0FNUExFX1JBVEUgKiAwLjA1KSk6CiAgICAgICAgICAgICAgICBhdWRpby5hcHBlbmQoMCkK"
    "ICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIElETEUgQ0hJTUUg4oCUIHNpbmdsZSBsb3cgYmVsbAojIFZlcnkgc29mdC4gTGlr"
    "ZSBhIGRpc3RhbnQgY2h1cmNoIGJlbGwuIFNpZ25hbHMgdW5zb2xpY2l0ZWQgdHJhbnNtaXNzaW9uLgojIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfaWRsZShw"
    "YXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiU2luZ2xlIHNvZnQgbG93IGJlbGwg4oCUIEQzLiBWZXJ5IHF1aWV0LiBQcmVzZW5j"
    "ZSBpbiB0aGUgZGFyay4iIiIKICAgIGZyZXEgPSAxNDYuODMgICMgRDMKICAgIGxlbmd0aCA9IDEuMgogICAgdG90YWwgPSBpbnQo"
    "X1NBTVBMRV9SQVRFICogbGVuZ3RoKQogICAgYXVkaW8gPSBbXQogICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgIHQg"
    "PSBpIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwgdCkgKiAwLjUKICAgICAgICB2YWwgKz0gX3NpbmUo"
    "ZnJlcSAqIDIuMCwgdCkgKiAwLjEKICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaSwgdG90YWwsIGF0dGFja19mcmFjPTAuMDIsIHJl"
    "bGVhc2VfZnJhYz0wLjc1KQogICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC4zKSkKICAgIF93cml0ZV93"
    "YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAojIE1PUkdBTk5BIEVSUk9SIOKAlCB0cml0b25lICh0aGUgZGV2aWwncyBpbnRlcnZhbCkKIyBEaXNzb25hbnQuIEJyaWVm"
    "LiBTb21ldGhpbmcgd2VudCB3cm9uZyBpbiB0aGUgcml0dWFsLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfZXJyb3IocGF0aDogUGF0aCkgLT4gTm9uZToK"
    "ICAgICIiIgogICAgVHJpdG9uZSBpbnRlcnZhbCDigJQgQjMgKyBGNCBwbGF5ZWQgc2ltdWx0YW5lb3VzbHkuCiAgICBUaGUgJ2Rp"
    "YWJvbHVzIGluIG11c2ljYScuIEJyaWVmIGFuZCBoYXJzaCBjb21wYXJlZCB0byBoZXIgb3RoZXIgc291bmRzLgogICAgIiIiCiAg"
    "ICBmcmVxX2EgPSAyNDYuOTQgICMgQjMKICAgIGZyZXFfYiA9IDM0OS4yMyAgIyBGNCAoYXVnbWVudGVkIGZvdXJ0aCAvIHRyaXRv"
    "bmUgYWJvdmUgQikKICAgIGxlbmd0aCA9IDAuNAogICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3RoKQogICAgYXVk"
    "aW8gPSBbXQogICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgIHQgPSBpIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgIyBC"
    "b3RoIGZyZXF1ZW5jaWVzIHNpbXVsdGFuZW91c2x5IOKAlCBjcmVhdGVzIGRpc3NvbmFuY2UKICAgICAgICB2YWwgPSAoX3NpbmUo"
    "ZnJlcV9hLCB0KSAqIDAuNSArCiAgICAgICAgICAgICAgIF9zcXVhcmUoZnJlcV9iLCB0KSAqIDAuMyArCiAgICAgICAgICAgICAg"
    "IF9zaW5lKGZyZXFfYSAqIDIuMCwgdCkgKiAwLjEpCiAgICAgICAgZW52ID0gX2VudmVsb3BlKGksIHRvdGFsLCBhdHRhY2tfZnJh"
    "Yz0wLjAyLCByZWxlYXNlX2ZyYWM9MC40KQogICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC41KSkKICAg"
    "IF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIFNIVVRET1dOIOKAlCBkZXNjZW5kaW5nIGNob3JkIGRpc3NvbHV0aW9uCiMgUmV2ZXJz"
    "ZSBvZiBzdGFydHVwLiBUaGUgc8OpYW5jZSBlbmRzLiBQcmVzZW5jZSB3aXRoZHJhd3MuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9zaHV0ZG93bihwYXRo"
    "OiBQYXRoKSAtPiBOb25lOgogICAgIiIiRGVzY2VuZGluZyBBNCDihpIgRTQg4oaSIEM0IOKGkiBBMy4gUHJlc2VuY2Ugd2l0aGRy"
    "YXdpbmcgaW50byBzaGFkb3cuIiIiCiAgICBub3RlcyA9IFsKICAgICAgICAoNDQwLjAsICAwLjMpLCAgICMgQTQKICAgICAgICAo"
    "MzI5LjYzLCAwLjMpLCAgICMgRTQKICAgICAgICAoMjYxLjYzLCAwLjMpLCAgICMgQzQKICAgICAgICAoMjIwLjAsICAwLjgpLCAg"
    "ICMgQTMg4oCUIGZpbmFsLCBsb25nIGZhZGUKICAgIF0KICAgIGF1ZGlvID0gW10KICAgIGZvciBpLCAoZnJlcSwgbGVuZ3RoKSBp"
    "biBlbnVtZXJhdGUobm90ZXMpOgogICAgICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgICAgICBmb3Ig"
    "aiBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgICAgIHQgPSBqIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgICAgIHZhbCA9IF9zaW5l"
    "KGZyZXEsIHQpICogMC41NQogICAgICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjE1CiAgICAgICAgICAg"
    "IGVudiA9IF9lbnZlbG9wZShqLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMywKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJl"
    "bGVhc2VfZnJhYz0wLjYgaWYgaSA9PSBsZW4obm90ZXMpLTEgZWxzZSAwLjMpCiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZChfY2xh"
    "bXAodmFsICogZW52ICogMC40KSkKICAgICAgICBmb3IgXyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4wNCkpOgogICAg"
    "ICAgICAgICBhdWRpby5hcHBlbmQoMCkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgCBTT1VORCBGSUxFIFBB"
    "VEhTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2V0X3NvdW5kX3BhdGgobmFtZTogc3RyKSAtPiBQYXRoOgogICAgcmV0"
    "dXJuIGNmZ19wYXRoKCJzb3VuZHMiKSAvIGYie1NPVU5EX1BSRUZJWH1fe25hbWV9LndhdiIKCmRlZiBib290c3RyYXBfc291bmRz"
    "KCkgLT4gTm9uZToKICAgICIiIkdlbmVyYXRlIGFueSBtaXNzaW5nIHNvdW5kIFdBViBmaWxlcyBvbiBzdGFydHVwLiIiIgogICAg"
    "Z2VuZXJhdG9ycyA9IHsKICAgICAgICAiYWxlcnQiOiAgICBnZW5lcmF0ZV9tb3JnYW5uYV9hbGVydCwgICAjIGludGVybmFsIGZu"
    "IG5hbWUgdW5jaGFuZ2VkCiAgICAgICAgInN0YXJ0dXAiOiAgZ2VuZXJhdGVfbW9yZ2FubmFfc3RhcnR1cCwKICAgICAgICAiaWRs"
    "ZSI6ICAgICBnZW5lcmF0ZV9tb3JnYW5uYV9pZGxlLAogICAgICAgICJlcnJvciI6ICAgIGdlbmVyYXRlX21vcmdhbm5hX2Vycm9y"
    "LAogICAgICAgICJzaHV0ZG93biI6IGdlbmVyYXRlX21vcmdhbm5hX3NodXRkb3duLAogICAgfQogICAgZm9yIG5hbWUsIGdlbl9m"
    "biBpbiBnZW5lcmF0b3JzLml0ZW1zKCk6CiAgICAgICAgcGF0aCA9IGdldF9zb3VuZF9wYXRoKG5hbWUpCiAgICAgICAgaWYgbm90"
    "IHBhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGdlbl9mbihwYXRoKQogICAgICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBwcmludChmIltTT1VORF1bV0FSTl0gRmFpbGVkIHRvIGdlbmVy"
    "YXRlIHtuYW1lfToge2V9IikKCmRlZiBwbGF5X3NvdW5kKG5hbWU6IHN0cikgLT4gTm9uZToKICAgICIiIgogICAgUGxheSBhIG5h"
    "bWVkIHNvdW5kIG5vbi1ibG9ja2luZy4KICAgIFRyaWVzIHB5Z2FtZS5taXhlciBmaXJzdCAoY3Jvc3MtcGxhdGZvcm0sIFdBViAr"
    "IE1QMykuCiAgICBGYWxscyBiYWNrIHRvIHdpbnNvdW5kIG9uIFdpbmRvd3MuCiAgICBGYWxscyBiYWNrIHRvIFFBcHBsaWNhdGlv"
    "bi5iZWVwKCkgYXMgbGFzdCByZXNvcnQuCiAgICAiIiIKICAgIGlmIG5vdCBDRkdbInNldHRpbmdzIl0uZ2V0KCJzb3VuZF9lbmFi"
    "bGVkIiwgVHJ1ZSk6CiAgICAgICAgcmV0dXJuCiAgICBwYXRoID0gZ2V0X3NvdW5kX3BhdGgobmFtZSkKICAgIGlmIG5vdCBwYXRo"
    "LmV4aXN0cygpOgogICAgICAgIHJldHVybgoKICAgIGlmIFBZR0FNRV9PSzoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNvdW5k"
    "ID0gcHlnYW1lLm1peGVyLlNvdW5kKHN0cihwYXRoKSkKICAgICAgICAgICAgc291bmQucGxheSgpCiAgICAgICAgICAgIHJldHVy"
    "bgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICBpZiBXSU5TT1VORF9PSzoKICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgIHdpbnNvdW5kLlBsYXlTb3VuZChzdHIocGF0aCksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICB3aW5zb3VuZC5TTkRfRklMRU5BTUUgfCB3aW5zb3VuZC5TTkRfQVNZTkMpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICB0cnk6CiAgICAgICAgUUFwcGxpY2F0aW9uLmJlZXAoKQogICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICBwYXNzCgojIOKUgOKUgCBERVNLVE9QIFNIT1JUQ1VUIENSRUFUT1Ig4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBjcmVh"
    "dGVfZGVza3RvcF9zaG9ydGN1dCgpIC0+IGJvb2w6CiAgICAiIiIKICAgIENyZWF0ZSBhIGRlc2t0b3Agc2hvcnRjdXQgdG8gdGhl"
    "IGRlY2sgLnB5IGZpbGUgdXNpbmcgcHl0aG9udy5leGUuCiAgICBSZXR1cm5zIFRydWUgb24gc3VjY2Vzcy4gV2luZG93cyBvbmx5"
    "LgogICAgIiIiCiAgICBpZiBub3QgV0lOMzJfT0s6CiAgICAgICAgcmV0dXJuIEZhbHNlCiAgICB0cnk6CiAgICAgICAgZGVza3Rv"
    "cCA9IFBhdGguaG9tZSgpIC8gIkRlc2t0b3AiCiAgICAgICAgc2hvcnRjdXRfcGF0aCA9IGRlc2t0b3AgLyBmIntERUNLX05BTUV9"
    "LmxuayIKCiAgICAgICAgIyBweXRob253ID0gc2FtZSBhcyBweXRob24gYnV0IG5vIGNvbnNvbGUgd2luZG93CiAgICAgICAgcHl0"
    "aG9udyA9IFBhdGgoc3lzLmV4ZWN1dGFibGUpCiAgICAgICAgaWYgcHl0aG9udy5uYW1lLmxvd2VyKCkgPT0gInB5dGhvbi5leGUi"
    "OgogICAgICAgICAgICBweXRob253ID0gcHl0aG9udy5wYXJlbnQgLyAicHl0aG9udy5leGUiCiAgICAgICAgaWYgbm90IHB5dGhv"
    "bncuZXhpc3RzKCk6CiAgICAgICAgICAgIHB5dGhvbncgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQoKICAgICAgICBkZWNrX3BhdGgg"
    "PSBQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCkKCiAgICAgICAgc2hlbGwgPSB3aW4zMmNvbS5jbGllbnQuRGlzcGF0Y2goIldTY3Jp"
    "cHQuU2hlbGwiKQogICAgICAgIHNjID0gc2hlbGwuQ3JlYXRlU2hvcnRDdXQoc3RyKHNob3J0Y3V0X3BhdGgpKQogICAgICAgIHNj"
    "LlRhcmdldFBhdGggICAgID0gc3RyKHB5dGhvbncpCiAgICAgICAgc2MuQXJndW1lbnRzICAgICAgPSBmJyJ7ZGVja19wYXRofSIn"
    "CiAgICAgICAgc2MuV29ya2luZ0RpcmVjdG9yeSA9IHN0cihkZWNrX3BhdGgucGFyZW50KQogICAgICAgIHNjLkRlc2NyaXB0aW9u"
    "ICAgID0gZiJ7REVDS19OQU1FfSDigJQgRWNobyBEZWNrIgoKICAgICAgICAjIFVzZSBuZXV0cmFsIGZhY2UgYXMgaWNvbiBpZiBh"
    "dmFpbGFibGUKICAgICAgICBpY29uX3BhdGggPSBjZmdfcGF0aCgiZmFjZXMiKSAvIGYie0ZBQ0VfUFJFRklYfV9OZXV0cmFsLnBu"
    "ZyIKICAgICAgICBpZiBpY29uX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgICMgV2luZG93cyBzaG9ydGN1dHMgY2FuJ3QgdXNl"
    "IFBORyBkaXJlY3RseSDigJQgc2tpcCBpY29uIGlmIG5vIC5pY28KICAgICAgICAgICAgcGFzcwoKICAgICAgICBzYy5zYXZlKCkK"
    "ICAgICAgICByZXR1cm4gVHJ1ZQogICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgIHByaW50KGYiW1NIT1JUQ1VUXVtX"
    "QVJOXSBDb3VsZCBub3QgY3JlYXRlIHNob3J0Y3V0OiB7ZX0iKQogICAgICAgIHJldHVybiBGYWxzZQoKIyDilIDilIAgSlNPTkwg"
    "VVRJTElUSUVTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgcmVhZF9qc29ubChwYXRoOiBQYXRoKSAtPiBsaXN0W2Rp"
    "Y3RdOgogICAgIiIiUmVhZCBhIEpTT05MIGZpbGUuIFJldHVybnMgbGlzdCBvZiBkaWN0cy4gSGFuZGxlcyBKU09OIGFycmF5cyB0"
    "b28uIiIiCiAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4gW10KICAgIHJhdyA9IHBhdGgucmVhZF90ZXh0"
    "KGVuY29kaW5nPSJ1dGYtOCIpLnN0cmlwKCkKICAgIGlmIG5vdCByYXc6CiAgICAgICAgcmV0dXJuIFtdCiAgICBpZiByYXcuc3Rh"
    "cnRzd2l0aCgiWyIpOgogICAgICAgIHRyeToKICAgICAgICAgICAgZGF0YSA9IGpzb24ubG9hZHMocmF3KQogICAgICAgICAgICBy"
    "ZXR1cm4gW3ggZm9yIHggaW4gZGF0YSBpZiBpc2luc3RhbmNlKHgsIGRpY3QpXQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAg"
    "ICAgICAgICAgIHBhc3MKICAgIGl0ZW1zID0gW10KICAgIGZvciBsaW5lIGluIHJhdy5zcGxpdGxpbmVzKCk6CiAgICAgICAgbGlu"
    "ZSA9IGxpbmUuc3RyaXAoKQogICAgICAgIGlmIG5vdCBsaW5lOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgb2JqID0ganNvbi5sb2FkcyhsaW5lKQogICAgICAgICAgICBpZiBpc2luc3RhbmNlKG9iaiwgZGljdCk6CiAgICAg"
    "ICAgICAgICAgICBpdGVtcy5hcHBlbmQob2JqKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIGNvbnRpbnVl"
    "CiAgICByZXR1cm4gaXRlbXMKCmRlZiBhcHBlbmRfanNvbmwocGF0aDogUGF0aCwgb2JqOiBkaWN0KSAtPiBOb25lOgogICAgIiIi"
    "QXBwZW5kIG9uZSByZWNvcmQgdG8gYSBKU09OTCBmaWxlLiIiIgogICAgcGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBl"
    "eGlzdF9vaz1UcnVlKQogICAgd2l0aCBwYXRoLm9wZW4oImEiLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgIGYud3Jp"
    "dGUoanNvbi5kdW1wcyhvYmosIGVuc3VyZV9hc2NpaT1GYWxzZSkgKyAiXG4iKQoKZGVmIHdyaXRlX2pzb25sKHBhdGg6IFBhdGgs"
    "IHJlY29yZHM6IGxpc3RbZGljdF0pIC0+IE5vbmU6CiAgICAiIiJPdmVyd3JpdGUgYSBKU09OTCBmaWxlIHdpdGggYSBsaXN0IG9m"
    "IHJlY29yZHMuIiIiCiAgICBwYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIHBh"
    "dGgub3BlbigidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgZm9yIHIgaW4gcmVjb3JkczoKICAgICAgICAgICAg"
    "Zi53cml0ZShqc29uLmR1bXBzKHIsIGVuc3VyZV9hc2NpaT1GYWxzZSkgKyAiXG4iKQoKIyDilIDilIAgS0VZV09SRCAvIE1FTU9S"
    "WSBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgApfU1RPUFdPUkRTID0gewogICAgInRoZSIsImFuZCIsInRoYXQiLCJ3aXRoIiwiaGF2ZSIsInRoaXMiLCJmcm9t"
    "IiwieW91ciIsIndoYXQiLCJ3aGVuIiwKICAgICJ3aGVyZSIsIndoaWNoIiwid291bGQiLCJ0aGVyZSIsInRoZXkiLCJ0aGVtIiwi"
    "dGhlbiIsImludG8iLCJqdXN0IiwKICAgICJhYm91dCIsImxpa2UiLCJiZWNhdXNlIiwid2hpbGUiLCJjb3VsZCIsInNob3VsZCIs"
    "InRoZWlyIiwid2VyZSIsImJlZW4iLAogICAgImJlaW5nIiwiZG9lcyIsImRpZCIsImRvbnQiLCJkaWRudCIsImNhbnQiLCJ3b250"
    "Iiwib250byIsIm92ZXIiLCJ1bmRlciIsCiAgICAidGhhbiIsImFsc28iLCJzb21lIiwibW9yZSIsImxlc3MiLCJvbmx5IiwibmVl"
    "ZCIsIndhbnQiLCJ3aWxsIiwic2hhbGwiLAogICAgImFnYWluIiwidmVyeSIsIm11Y2giLCJyZWFsbHkiLCJtYWtlIiwibWFkZSIs"
    "InVzZWQiLCJ1c2luZyIsInNhaWQiLAogICAgInRlbGwiLCJ0b2xkIiwiaWRlYSIsImNoYXQiLCJjb2RlIiwidGhpbmciLCJzdHVm"
    "ZiIsInVzZXIiLCJhc3Npc3RhbnQiLAp9CgpkZWYgZXh0cmFjdF9rZXl3b3Jkcyh0ZXh0OiBzdHIsIGxpbWl0OiBpbnQgPSAxMikg"
    "LT4gbGlzdFtzdHJdOgogICAgdG9rZW5zID0gW3QubG93ZXIoKS5zdHJpcCgiIC4sIT87OidcIigpW117fSIpIGZvciB0IGluIHRl"
    "eHQuc3BsaXQoKV0KICAgIHNlZW4sIHJlc3VsdCA9IHNldCgpLCBbXQogICAgZm9yIHQgaW4gdG9rZW5zOgogICAgICAgIGlmIGxl"
    "bih0KSA8IDMgb3IgdCBpbiBfU1RPUFdPUkRTIG9yIHQuaXNkaWdpdCgpOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlm"
    "IHQgbm90IGluIHNlZW46CiAgICAgICAgICAgIHNlZW4uYWRkKHQpCiAgICAgICAgICAgIHJlc3VsdC5hcHBlbmQodCkKICAgICAg"
    "ICBpZiBsZW4ocmVzdWx0KSA+PSBsaW1pdDoKICAgICAgICAgICAgYnJlYWsKICAgIHJldHVybiByZXN1bHQKCmRlZiBpbmZlcl9y"
    "ZWNvcmRfdHlwZSh1c2VyX3RleHQ6IHN0ciwgYXNzaXN0YW50X3RleHQ6IHN0ciA9ICIiKSAtPiBzdHI6CiAgICB0ID0gKHVzZXJf"
    "dGV4dCArICIgIiArIGFzc2lzdGFudF90ZXh0KS5sb3dlcigpCiAgICBpZiAiZHJlYW0iIGluIHQ6ICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIHJldHVybiAiZHJlYW0iCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgibHNsIiwicHl0aG9uIiwic2NyaXB0"
    "IiwiY29kZSIsImVycm9yIiwiYnVnIikpOgogICAgICAgIGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJmaXhlZCIsInJlc29sdmVk"
    "Iiwic29sdXRpb24iLCJ3b3JraW5nIikpOgogICAgICAgICAgICByZXR1cm4gInJlc29sdXRpb24iCiAgICAgICAgcmV0dXJuICJp"
    "c3N1ZSIKICAgIGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJyZW1pbmQiLCJ0aW1lciIsImFsYXJtIiwidGFzayIpKToKICAgICAg"
    "ICByZXR1cm4gInRhc2siCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgiaWRlYSIsImNvbmNlcHQiLCJ3aGF0IGlmIiwiZ2Ft"
    "ZSIsInByb2plY3QiKSk6CiAgICAgICAgcmV0dXJuICJpZGVhIgogICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoInByZWZlciIs"
    "ImFsd2F5cyIsIm5ldmVyIiwiaSBsaWtlIiwiaSB3YW50IikpOgogICAgICAgIHJldHVybiAicHJlZmVyZW5jZSIKICAgIHJldHVy"
    "biAiY29udmVyc2F0aW9uIgoKIyDilIDilIAgUEFTUyAxIENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE5l"
    "eHQ6IFBhc3MgMiDigJQgV2lkZ2V0IENsYXNzZXMKIyAoR2F1Z2VXaWRnZXQsIE1vb25XaWRnZXQsIFNwaGVyZVdpZGdldCwgRW1v"
    "dGlvbkJsb2NrLAojICBNaXJyb3JXaWRnZXQsIFZhbXBpcmVTdGF0ZVN0cmlwLCBDb2xsYXBzaWJsZUJsb2NrKQoKCiMg4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyAyOiBXSURHRVQgQ0xBU1NFUwojIEFwcGVuZGVkIHRvIG1vcmdhbm5hX3Bh"
    "c3MxLnB5IHRvIGZvcm0gdGhlIGZ1bGwgZGVjay4KIwojIFdpZGdldHMgZGVmaW5lZCBoZXJlOgojICAgR2F1Z2VXaWRnZXQgICAg"
    "ICAgICAg4oCUIGhvcml6b250YWwgZmlsbCBiYXIgd2l0aCBsYWJlbCBhbmQgdmFsdWUKIyAgIERyaXZlV2lkZ2V0ICAgICAgICAg"
    "IOKAlCBkcml2ZSB1c2FnZSBiYXIgKHVzZWQvdG90YWwgR0IpCiMgICBTcGhlcmVXaWRnZXQgICAgICAgICDigJQgZmlsbGVkIGNp"
    "cmNsZSBmb3IgQkxPT0QgYW5kIE1BTkEKIyAgIE1vb25XaWRnZXQgICAgICAgICAgIOKAlCBkcmF3biBtb29uIG9yYiB3aXRoIHBo"
    "YXNlIHNoYWRvdwojICAgRW1vdGlvbkJsb2NrICAgICAgICAg4oCUIGNvbGxhcHNpYmxlIGVtb3Rpb24gaGlzdG9yeSBjaGlwcwoj"
    "ICAgTWlycm9yV2lkZ2V0ICAgICAgICAg4oCUIGZhY2UgaW1hZ2UgZGlzcGxheSAodGhlIE1pcnJvcikKIyAgIFZhbXBpcmVTdGF0"
    "ZVN0cmlwICAgIOKAlCBmdWxsLXdpZHRoIHRpbWUvbW9vbi9zdGF0ZSBzdGF0dXMgYmFyCiMgICBDb2xsYXBzaWJsZUJsb2NrICAg"
    "ICDigJQgd3JhcHBlciB0aGF0IGFkZHMgY29sbGFwc2UgdG9nZ2xlIHRvIGFueSB3aWRnZXQKIyAgIEhhcmR3YXJlUGFuZWwgICAg"
    "ICAgIOKAlCBncm91cHMgYWxsIHN5c3RlbXMgZ2F1Z2VzCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgoKIyDilIDilIAgR0FVR0UgV0lER0VUIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBHYXVnZVdpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAg"
    "SG9yaXpvbnRhbCBmaWxsLWJhciBnYXVnZSB3aXRoIGdvdGhpYyBzdHlsaW5nLgogICAgU2hvd3M6IGxhYmVsICh0b3AtbGVmdCks"
    "IHZhbHVlIHRleHQgKHRvcC1yaWdodCksIGZpbGwgYmFyIChib3R0b20pLgogICAgQ29sb3Igc2hpZnRzOiBub3JtYWwg4oaSIENf"
    "Q1JJTVNPTiDihpIgQ19CTE9PRCBhcyB2YWx1ZSBhcHByb2FjaGVzIG1heC4KICAgIFNob3dzICdOL0EnIHdoZW4gZGF0YSBpcyB1"
    "bmF2YWlsYWJsZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXygKICAgICAgICBzZWxmLAogICAgICAgIGxhYmVsOiBzdHIsCiAg"
    "ICAgICAgdW5pdDogc3RyID0gIiIsCiAgICAgICAgbWF4X3ZhbDogZmxvYXQgPSAxMDAuMCwKICAgICAgICBjb2xvcjogc3RyID0g"
    "Q19HT0xELAogICAgICAgIHBhcmVudD1Ob25lCiAgICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAg"
    "IHNlbGYubGFiZWwgICAgPSBsYWJlbAogICAgICAgIHNlbGYudW5pdCAgICAgPSB1bml0CiAgICAgICAgc2VsZi5tYXhfdmFsICA9"
    "IG1heF92YWwKICAgICAgICBzZWxmLmNvbG9yICAgID0gY29sb3IKICAgICAgICBzZWxmLl92YWx1ZSAgID0gMC4wCiAgICAgICAg"
    "c2VsZi5fZGlzcGxheSA9ICJOL0EiCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gRmFsc2UKICAgICAgICBzZWxmLnNldE1pbmlt"
    "dW1TaXplKDEwMCwgNjApCiAgICAgICAgc2VsZi5zZXRNYXhpbXVtSGVpZ2h0KDcyKQoKICAgIGRlZiBzZXRWYWx1ZShzZWxmLCB2"
    "YWx1ZTogZmxvYXQsIGRpc3BsYXk6IHN0ciA9ICIiLCBhdmFpbGFibGU6IGJvb2wgPSBUcnVlKSAtPiBOb25lOgogICAgICAgIHNl"
    "bGYuX3ZhbHVlICAgICA9IG1pbihmbG9hdCh2YWx1ZSksIHNlbGYubWF4X3ZhbCkKICAgICAgICBzZWxmLl9hdmFpbGFibGUgPSBh"
    "dmFpbGFibGUKICAgICAgICBpZiBub3QgYXZhaWxhYmxlOgogICAgICAgICAgICBzZWxmLl9kaXNwbGF5ID0gIk4vQSIKICAgICAg"
    "ICBlbGlmIGRpc3BsYXk6CiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkgPSBkaXNwbGF5CiAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgc2VsZi5fZGlzcGxheSA9IGYie3ZhbHVlOi4wZn17c2VsZi51bml0fSIKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVm"
    "IHNldFVuYXZhaWxhYmxlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gRmFsc2UKICAgICAgICBzZWxm"
    "Ll9kaXNwbGF5ICAgPSAiTi9BIgogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkg"
    "LT4gTm9uZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVy"
    "SGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwgc2VsZi5oZWlnaHQoKQoKICAgICAgICAjIEJh"
    "Y2tncm91bmQKICAgICAgICBwLmZpbGxSZWN0KDAsIDAsIHcsIGgsIFFDb2xvcihDX0JHMykpCiAgICAgICAgcC5zZXRQZW4oUUNv"
    "bG9yKENfQk9SREVSKSkKICAgICAgICBwLmRyYXdSZWN0KDAsIDAsIHcgLSAxLCBoIC0gMSkKCiAgICAgICAgIyBMYWJlbAogICAg"
    "ICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA4LCBRRm9u"
    "dC5XZWlnaHQuQm9sZCkpCiAgICAgICAgcC5kcmF3VGV4dCg2LCAxNCwgc2VsZi5sYWJlbCkKCiAgICAgICAgIyBWYWx1ZQogICAg"
    "ICAgIHAuc2V0UGVuKFFDb2xvcihzZWxmLmNvbG9yIGlmIHNlbGYuX2F2YWlsYWJsZSBlbHNlIENfVEVYVF9ESU0pKQogICAgICAg"
    "IHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDEwLCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRy"
    "aWNzKCkKICAgICAgICB2dyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHNlbGYuX2Rpc3BsYXkpCiAgICAgICAgcC5kcmF3VGV4dCh3"
    "IC0gdncgLSA2LCAxNCwgc2VsZi5fZGlzcGxheSkKCiAgICAgICAgIyBGaWxsIGJhcgogICAgICAgIGJhcl95ID0gaCAtIDE4CiAg"
    "ICAgICAgYmFyX2ggPSAxMAogICAgICAgIGJhcl93ID0gdyAtIDEyCiAgICAgICAgcC5maWxsUmVjdCg2LCBiYXJfeSwgYmFyX3cs"
    "IGJhcl9oLCBRQ29sb3IoQ19CRykpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9SREVSKSkKICAgICAgICBwLmRyYXdSZWN0"
    "KDYsIGJhcl95LCBiYXJfdyAtIDEsIGJhcl9oIC0gMSkKCiAgICAgICAgaWYgc2VsZi5fYXZhaWxhYmxlIGFuZCBzZWxmLm1heF92"
    "YWwgPiAwOgogICAgICAgICAgICBmcmFjID0gc2VsZi5fdmFsdWUgLyBzZWxmLm1heF92YWwKICAgICAgICAgICAgZmlsbF93ID0g"
    "bWF4KDEsIGludCgoYmFyX3cgLSAyKSAqIGZyYWMpKQogICAgICAgICAgICAjIENvbG9yIHNoaWZ0IG5lYXIgbGltaXQKICAgICAg"
    "ICAgICAgYmFyX2NvbG9yID0gKENfQkxPT0QgaWYgZnJhYyA+IDAuODUgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19D"
    "UklNU09OIGlmIGZyYWMgPiAwLjY1IGVsc2UKICAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuY29sb3IpCiAgICAgICAgICAg"
    "IGdyYWQgPSBRTGluZWFyR3JhZGllbnQoNywgYmFyX3kgKyAxLCA3ICsgZmlsbF93LCBiYXJfeSArIDEpCiAgICAgICAgICAgIGdy"
    "YWQuc2V0Q29sb3JBdCgwLCBRQ29sb3IoYmFyX2NvbG9yKS5kYXJrZXIoMTYwKSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0"
    "KDEsIFFDb2xvcihiYXJfY29sb3IpKQogICAgICAgICAgICBwLmZpbGxSZWN0KDcsIGJhcl95ICsgMSwgZmlsbF93LCBiYXJfaCAt"
    "IDIsIGdyYWQpCgogICAgICAgIHAuZW5kKCkKCgojIOKUgOKUgCBEUklWRSBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACmNsYXNzIERyaXZlV2lkZ2V0KFFXaWRnZXQpOgogICAgIiIiCiAgICBEcml2ZSB1c2FnZSBkaXNwbGF5LiBT"
    "aG93cyBkcml2ZSBsZXR0ZXIsIHVzZWQvdG90YWwgR0IsIGZpbGwgYmFyLgogICAgQXV0by1kZXRlY3RzIGFsbCBtb3VudGVkIGRy"
    "aXZlcyB2aWEgcHN1dGlsLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBl"
    "cigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kcml2ZXM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuc2V0"
    "TWluaW11bUhlaWdodCgzMCkKICAgICAgICBzZWxmLl9yZWZyZXNoKCkKCiAgICBkZWYgX3JlZnJlc2goc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9kcml2ZXMgPSBbXQogICAgICAgIGlmIG5vdCBQU1VUSUxfT0s6CiAgICAgICAgICAgIHJldHVybgogICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgZm9yIHBhcnQgaW4gcHN1dGlsLmRpc2tfcGFydGl0aW9ucyhhbGw9RmFsc2UpOgogICAgICAg"
    "ICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIHVzYWdlID0gcHN1dGlsLmRpc2tfdXNhZ2UocGFydC5tb3VudHBvaW50"
    "KQogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RyaXZlcy5hcHBlbmQoewogICAgICAgICAgICAgICAgICAgICAgICAibGV0dGVy"
    "IjogcGFydC5kZXZpY2UucnN0cmlwKCJcXCIpLnJzdHJpcCgiLyIpLAogICAgICAgICAgICAgICAgICAgICAgICAidXNlZCI6ICAg"
    "dXNhZ2UudXNlZCAgLyAxMDI0KiozLAogICAgICAgICAgICAgICAgICAgICAgICAidG90YWwiOiAgdXNhZ2UudG90YWwgLyAxMDI0"
    "KiozLAogICAgICAgICAgICAgICAgICAgICAgICAicGN0IjogICAgdXNhZ2UucGVyY2VudCAvIDEwMC4wLAogICAgICAgICAgICAg"
    "ICAgICAgIH0pCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAg"
    "ICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgICAgICMgUmVzaXplIHRvIGZpdCBhbGwgZHJpdmVz"
    "CiAgICAgICAgbiA9IG1heCgxLCBsZW4oc2VsZi5fZHJpdmVzKSkKICAgICAgICBzZWxmLnNldE1pbmltdW1IZWlnaHQobiAqIDI4"
    "ICsgOCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAg"
    "ICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFz"
    "aW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKICAgICAgICBwLmZpbGxSZWN0KDAsIDAsIHcs"
    "IGgsIFFDb2xvcihDX0JHMykpCgogICAgICAgIGlmIG5vdCBzZWxmLl9kcml2ZXM6CiAgICAgICAgICAgIHAuc2V0UGVuKFFDb2xv"
    "cihDX1RFWFRfRElNKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOSkpCiAgICAgICAgICAgIHAuZHJh"
    "d1RleHQoNiwgMTgsICJOL0Eg4oCUIHBzdXRpbCB1bmF2YWlsYWJsZSIpCiAgICAgICAgICAgIHAuZW5kKCkKICAgICAgICAgICAg"
    "cmV0dXJuCgogICAgICAgIHJvd19oID0gMjYKICAgICAgICB5ID0gNAogICAgICAgIGZvciBkcnYgaW4gc2VsZi5fZHJpdmVzOgog"
    "ICAgICAgICAgICBsZXR0ZXIgPSBkcnZbImxldHRlciJdCiAgICAgICAgICAgIHVzZWQgICA9IGRydlsidXNlZCJdCiAgICAgICAg"
    "ICAgIHRvdGFsICA9IGRydlsidG90YWwiXQogICAgICAgICAgICBwY3QgICAgPSBkcnZbInBjdCJdCgogICAgICAgICAgICAjIExh"
    "YmVsCiAgICAgICAgICAgIGxhYmVsID0gZiJ7bGV0dGVyfSAge3VzZWQ6LjFmfS97dG90YWw6LjBmfUdCIgogICAgICAgICAgICBw"
    "LnNldFBlbihRQ29sb3IoQ19HT0xEKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOCwgUUZvbnQuV2Vp"
    "Z2h0LkJvbGQpKQogICAgICAgICAgICBwLmRyYXdUZXh0KDYsIHkgKyAxMiwgbGFiZWwpCgogICAgICAgICAgICAjIEJhcgogICAg"
    "ICAgICAgICBiYXJfeCA9IDYKICAgICAgICAgICAgYmFyX3kgPSB5ICsgMTUKICAgICAgICAgICAgYmFyX3cgPSB3IC0gMTIKICAg"
    "ICAgICAgICAgYmFyX2ggPSA4CiAgICAgICAgICAgIHAuZmlsbFJlY3QoYmFyX3gsIGJhcl95LCBiYXJfdywgYmFyX2gsIFFDb2xv"
    "cihDX0JHKSkKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9SREVSKSkKICAgICAgICAgICAgcC5kcmF3UmVjdChiYXJf"
    "eCwgYmFyX3ksIGJhcl93IC0gMSwgYmFyX2ggLSAxKQoKICAgICAgICAgICAgZmlsbF93ID0gbWF4KDEsIGludCgoYmFyX3cgLSAy"
    "KSAqIHBjdCkpCiAgICAgICAgICAgIGJhcl9jb2xvciA9IChDX0JMT09EIGlmIHBjdCA+IDAuOSBlbHNlCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICBDX0NSSU1TT04gaWYgcGN0ID4gMC43NSBlbHNlCiAgICAgICAgICAgICAgICAgICAgICAgICBDX0dPTERfRElN"
    "KQogICAgICAgICAgICBncmFkID0gUUxpbmVhckdyYWRpZW50KGJhcl94ICsgMSwgYmFyX3ksIGJhcl94ICsgZmlsbF93LCBiYXJf"
    "eSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDAsIFFDb2xvcihiYXJfY29sb3IpLmRhcmtlcigxNTApKQogICAgICAgICAg"
    "ICBncmFkLnNldENvbG9yQXQoMSwgUUNvbG9yKGJhcl9jb2xvcikpCiAgICAgICAgICAgIHAuZmlsbFJlY3QoYmFyX3ggKyAxLCBi"
    "YXJfeSArIDEsIGZpbGxfdywgYmFyX2ggLSAyLCBncmFkKQoKICAgICAgICAgICAgeSArPSByb3dfaAoKICAgICAgICBwLmVuZCgp"
    "CgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJDYWxsIHBlcmlvZGljYWxseSB0byB1cGRhdGUgZHJp"
    "dmUgc3RhdHMuIiIiCiAgICAgICAgc2VsZi5fcmVmcmVzaCgpCgoKIyDilIDilIAgU1BIRVJFIFdJREdFVCDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU3BoZXJlV2lkZ2V0KFFXaWRnZXQpOgogICAgIiIiCiAgICBGaWxsZWQgY2lyY2xl"
    "IGdhdWdlIOKAlCB1c2VkIGZvciBCTE9PRCAodG9rZW4gcG9vbCkgYW5kIE1BTkEgKFZSQU0pLgogICAgRmlsbHMgZnJvbSBib3R0"
    "b20gdXAuIEdsYXNzeSBzaGluZSBlZmZlY3QuIExhYmVsIGJlbG93LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKAogICAgICAg"
    "IHNlbGYsCiAgICAgICAgbGFiZWw6IHN0ciwKICAgICAgICBjb2xvcl9mdWxsOiBzdHIsCiAgICAgICAgY29sb3JfZW1wdHk6IHN0"
    "ciwKICAgICAgICBwYXJlbnQ9Tm9uZQogICAgKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxm"
    "LmxhYmVsICAgICAgID0gbGFiZWwKICAgICAgICBzZWxmLmNvbG9yX2Z1bGwgID0gY29sb3JfZnVsbAogICAgICAgIHNlbGYuY29s"
    "b3JfZW1wdHkgPSBjb2xvcl9lbXB0eQogICAgICAgIHNlbGYuX2ZpbGwgICAgICAgPSAwLjAgICAjIDAuMCDihpIgMS4wCiAgICAg"
    "ICAgc2VsZi5fYXZhaWxhYmxlICA9IFRydWUKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDgwLCAxMDApCgogICAgZGVmIHNl"
    "dEZpbGwoc2VsZiwgZnJhY3Rpb246IGZsb2F0LCBhdmFpbGFibGU6IGJvb2wgPSBUcnVlKSAtPiBOb25lOgogICAgICAgIHNlbGYu"
    "X2ZpbGwgICAgICA9IG1heCgwLjAsIG1pbigxLjAsIGZyYWN0aW9uKSkKICAgICAgICBzZWxmLl9hdmFpbGFibGUgPSBhdmFpbGFi"
    "bGUKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAg"
    "cCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5n"
    "KQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgciAgPSBtaW4odywgaCAtIDIwKSAv"
    "LyAyIC0gNAogICAgICAgIGN4ID0gdyAvLyAyCiAgICAgICAgY3kgPSAoaCAtIDIwKSAvLyAyICsgNAoKICAgICAgICAjIERyb3Ag"
    "c2hhZG93CiAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMCwgMCwg"
    "MCwgODApKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByICsgMywgY3kgLSByICsgMywgciAqIDIsIHIgKiAyKQoKICAgICAg"
    "ICAjIEJhc2UgY2lyY2xlIChlbXB0eSBjb2xvcikKICAgICAgICBwLnNldEJydXNoKFFDb2xvcihzZWxmLmNvbG9yX2VtcHR5KSkK"
    "ICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19CT1JERVIpKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIg"
    "KiAyLCByICogMikKCiAgICAgICAgIyBGaWxsIGZyb20gYm90dG9tCiAgICAgICAgaWYgc2VsZi5fZmlsbCA+IDAuMDEgYW5kIHNl"
    "bGYuX2F2YWlsYWJsZToKICAgICAgICAgICAgY2lyY2xlX3BhdGggPSBRUGFpbnRlclBhdGgoKQogICAgICAgICAgICBjaXJjbGVf"
    "cGF0aC5hZGRFbGxpcHNlKGZsb2F0KGN4IC0gciksIGZsb2F0KGN5IC0gciksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgZmxvYXQociAqIDIpLCBmbG9hdChyICogMikpCgogICAgICAgICAgICBmaWxsX3RvcF95ID0gY3kgKyByIC0gKHNlbGYu"
    "X2ZpbGwgKiByICogMikKICAgICAgICAgICAgZnJvbSBQeVNpZGU2LlF0Q29yZSBpbXBvcnQgUVJlY3RGCiAgICAgICAgICAgIGZp"
    "bGxfcmVjdCA9IFFSZWN0RihjeCAtIHIsIGZpbGxfdG9wX3ksIHIgKiAyLCBjeSArIHIgLSBmaWxsX3RvcF95KQogICAgICAgICAg"
    "ICBmaWxsX3BhdGggPSBRUGFpbnRlclBhdGgoKQogICAgICAgICAgICBmaWxsX3BhdGguYWRkUmVjdChmaWxsX3JlY3QpCiAgICAg"
    "ICAgICAgIGNsaXBwZWQgPSBjaXJjbGVfcGF0aC5pbnRlcnNlY3RlZChmaWxsX3BhdGgpCgogICAgICAgICAgICBwLnNldFBlbihR"
    "dC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3Ioc2VsZi5jb2xvcl9mdWxsKSkKICAgICAgICAg"
    "ICAgcC5kcmF3UGF0aChjbGlwcGVkKQoKICAgICAgICAjIEdsYXNzeSBzaGluZQogICAgICAgIHNoaW5lID0gUVJhZGlhbEdyYWRp"
    "ZW50KAogICAgICAgICAgICBmbG9hdChjeCAtIHIgKiAwLjMpLCBmbG9hdChjeSAtIHIgKiAwLjMpLCBmbG9hdChyICogMC42KQog"
    "ICAgICAgICkKICAgICAgICBzaGluZS5zZXRDb2xvckF0KDAsIFFDb2xvcigyNTUsIDI1NSwgMjU1LCA1NSkpCiAgICAgICAgc2hp"
    "bmUuc2V0Q29sb3JBdCgxLCBRQ29sb3IoMjU1LCAyNTUsIDI1NSwgMCkpCiAgICAgICAgcC5zZXRCcnVzaChzaGluZSkKICAgICAg"
    "ICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwg"
    "ciAqIDIpCgogICAgICAgICMgT3V0bGluZQogICAgICAgIHAuc2V0QnJ1c2goUXQuQnJ1c2hTdHlsZS5Ob0JydXNoKQogICAgICAg"
    "IHAuc2V0UGVuKFFQZW4oUUNvbG9yKHNlbGYuY29sb3JfZnVsbCksIDEpKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBj"
    "eSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBOL0Egb3ZlcmxheQogICAgICAgIGlmIG5vdCBzZWxmLl9hdmFpbGFibGU6"
    "CiAgICAgICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KCJDb3Vy"
    "aWVyIE5ldyIsIDgpKQogICAgICAgICAgICBmbSA9IHAuZm9udE1ldHJpY3MoKQogICAgICAgICAgICB0eHQgPSAiTi9BIgogICAg"
    "ICAgICAgICBwLmRyYXdUZXh0KGN4IC0gZm0uaG9yaXpvbnRhbEFkdmFuY2UodHh0KSAvLyAyLCBjeSArIDQsIHR4dCkKCiAgICAg"
    "ICAgIyBMYWJlbCBiZWxvdyBzcGhlcmUKICAgICAgICBsYWJlbF90ZXh0ID0gKHNlbGYubGFiZWwgaWYgc2VsZi5fYXZhaWxhYmxl"
    "IGVsc2UKICAgICAgICAgICAgICAgICAgICAgIGYie3NlbGYubGFiZWx9IikKICAgICAgICBwY3RfdGV4dCA9IGYie2ludChzZWxm"
    "Ll9maWxsICogMTAwKX0lIiBpZiBzZWxmLl9hdmFpbGFibGUgZWxzZSAiIgoKICAgICAgICBwLnNldFBlbihRQ29sb3Ioc2VsZi5j"
    "b2xvcl9mdWxsKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA4LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAg"
    "ICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKCiAgICAgICAgbHcgPSBmbS5ob3Jpem9udGFsQWR2YW5jZShsYWJlbF90ZXh0KQogICAg"
    "ICAgIHAuZHJhd1RleHQoY3ggLSBsdyAvLyAyLCBoIC0gMTAsIGxhYmVsX3RleHQpCgogICAgICAgIGlmIHBjdF90ZXh0OgogICAg"
    "ICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQs"
    "IDcpKQogICAgICAgICAgICBmbTIgPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICAgICAgcHcgPSBmbTIuaG9yaXpvbnRhbEFkdmFu"
    "Y2UocGN0X3RleHQpCiAgICAgICAgICAgIHAuZHJhd1RleHQoY3ggLSBwdyAvLyAyLCBoIC0gMSwgcGN0X3RleHQpCgogICAgICAg"
    "IHAuZW5kKCkKCgojIOKUgOKUgCBNT09OIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xh"
    "c3MgTW9vbldpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgRHJhd24gbW9vbiBvcmIgd2l0aCBwaGFzZS1hY2N1cmF0ZSBzaGFk"
    "b3cuCgogICAgUEhBU0UgQ09OVkVOVElPTiAobm9ydGhlcm4gaGVtaXNwaGVyZSwgc3RhbmRhcmQpOgogICAgICAtIFdheGluZyAo"
    "bmV34oaSZnVsbCk6IGlsbHVtaW5hdGVkIHJpZ2h0IHNpZGUsIHNoYWRvdyBvbiBsZWZ0CiAgICAgIC0gV2FuaW5nIChmdWxs4oaS"
    "bmV3KTogaWxsdW1pbmF0ZWQgbGVmdCBzaWRlLCBzaGFkb3cgb24gcmlnaHQKCiAgICBUaGUgc2hhZG93X3NpZGUgZmxhZyBjYW4g"
    "YmUgZmxpcHBlZCBpZiB0ZXN0aW5nIHJldmVhbHMgaXQncyBiYWNrd2FyZHMKICAgIG9uIHRoaXMgbWFjaGluZS4gU2V0IE1PT05f"
    "U0hBRE9XX0ZMSVAgPSBUcnVlIGluIHRoYXQgY2FzZS4KICAgICIiIgoKICAgICMg4oaQIEZMSVAgVEhJUyB0byBUcnVlIGlmIG1v"
    "b24gYXBwZWFycyBiYWNrd2FyZHMgZHVyaW5nIHRlc3RpbmcKICAgIE1PT05fU0hBRE9XX0ZMSVA6IGJvb2wgPSBGYWxzZQoKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAg"
    "c2VsZi5fcGhhc2UgICAgICAgPSAwLjAgICAgIyAwLjA9bmV3LCAwLjU9ZnVsbCwgMS4wPW5ldwogICAgICAgIHNlbGYuX25hbWUg"
    "ICAgICAgID0gIk5FVyBNT09OIgogICAgICAgIHNlbGYuX2lsbHVtaW5hdGlvbiA9IDAuMCAgICMgMC0xMDAKICAgICAgICBzZWxm"
    "Ll9zdW5yaXNlICAgICAgPSAiMDY6MDAiCiAgICAgICAgc2VsZi5fc3Vuc2V0ICAgICAgID0gIjE4OjMwIgogICAgICAgIHNlbGYu"
    "X3N1bl9kYXRlICAgICA9IE5vbmUKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDgwLCAxMTApCiAgICAgICAgc2VsZi51cGRh"
    "dGVQaGFzZSgpICAgICAgICAgICMgcG9wdWxhdGUgY29ycmVjdCBwaGFzZSBpbW1lZGlhdGVseQogICAgICAgIHNlbGYuX2ZldGNo"
    "X3N1bl9hc3luYygpCgogICAgZGVmIF9mZXRjaF9zdW5fYXN5bmMoc2VsZikgLT4gTm9uZToKICAgICAgICBkZWYgX2ZldGNoKCk6"
    "CiAgICAgICAgICAgIHNyLCBzcyA9IGdldF9zdW5fdGltZXMoKQogICAgICAgICAgICBzZWxmLl9zdW5yaXNlID0gc3IKICAgICAg"
    "ICAgICAgc2VsZi5fc3Vuc2V0ICA9IHNzCiAgICAgICAgICAgIHNlbGYuX3N1bl9kYXRlID0gZGF0ZXRpbWUubm93KCkuYXN0aW1l"
    "em9uZSgpLmRhdGUoKQogICAgICAgICAgICAjIFNjaGVkdWxlIHJlcGFpbnQgb24gbWFpbiB0aHJlYWQgdmlhIFFUaW1lciDigJQg"
    "bmV2ZXIgY2FsbAogICAgICAgICAgICAjIHNlbGYudXBkYXRlKCkgZGlyZWN0bHkgZnJvbSBhIGJhY2tncm91bmQgdGhyZWFkCiAg"
    "ICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDAsIHNlbGYudXBkYXRlKQogICAgICAgIHRocmVhZGluZy5UaHJlYWQodGFyZ2V0"
    "PV9mZXRjaCwgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgdXBkYXRlUGhhc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLl9waGFzZSwgc2VsZi5fbmFtZSwgc2VsZi5faWxsdW1pbmF0aW9uID0gZ2V0X21vb25fcGhhc2UoKQogICAgICAgIHRvZGF5"
    "ID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLmRhdGUoKQogICAgICAgIGlmIHNlbGYuX3N1bl9kYXRlICE9IHRvZGF5Ogog"
    "ICAgICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVu"
    "dChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQo"
    "UVBhaW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwgc2VsZi5oZWlnaHQo"
    "KQoKICAgICAgICByICA9IG1pbih3LCBoIC0gMzYpIC8vIDIgLSA0CiAgICAgICAgY3ggPSB3IC8vIDIKICAgICAgICBjeSA9ICho"
    "IC0gMzYpIC8vIDIgKyA0CgogICAgICAgICMgQmFja2dyb3VuZCBjaXJjbGUgKHNwYWNlKQogICAgICAgIHAuc2V0QnJ1c2goUUNv"
    "bG9yKDIwLCAxMiwgMjgpKQogICAgICAgIHAuc2V0UGVuKFFQZW4oUUNvbG9yKENfU0lMVkVSX0RJTSksIDEpKQogICAgICAgIHAu"
    "ZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgY3ljbGVfZGF5ID0gc2VsZi5fcGhhc2Ug"
    "KiBfTFVOQVJfQ1lDTEUKICAgICAgICBpc193YXhpbmcgPSBjeWNsZV9kYXkgPCAoX0xVTkFSX0NZQ0xFIC8gMikKCiAgICAgICAg"
    "IyBGdWxsIG1vb24gYmFzZSAobW9vbiBzdXJmYWNlIGNvbG9yKQogICAgICAgIGlmIHNlbGYuX2lsbHVtaW5hdGlvbiA+IDE6CiAg"
    "ICAgICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAgICAgICAgICBwLnNldEJydXNoKFFDb2xvcigyMjAsIDIx"
    "MCwgMTg1KSkKICAgICAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAj"
    "IFNoYWRvdyBjYWxjdWxhdGlvbgogICAgICAgICMgaWxsdW1pbmF0aW9uIGdvZXMgMOKGkjEwMCB3YXhpbmcsIDEwMOKGkjAgd2Fu"
    "aW5nCiAgICAgICAgIyBzaGFkb3dfb2Zmc2V0IGNvbnRyb2xzIGhvdyBtdWNoIG9mIHRoZSBjaXJjbGUgdGhlIHNoYWRvdyBjb3Zl"
    "cnMKICAgICAgICBpZiBzZWxmLl9pbGx1bWluYXRpb24gPCA5OToKICAgICAgICAgICAgIyBmcmFjdGlvbiBvZiBkaWFtZXRlciB0"
    "aGUgc2hhZG93IGVsbGlwc2UgaXMgb2Zmc2V0CiAgICAgICAgICAgIGlsbHVtX2ZyYWMgID0gc2VsZi5faWxsdW1pbmF0aW9uIC8g"
    "MTAwLjAKICAgICAgICAgICAgc2hhZG93X2ZyYWMgPSAxLjAgLSBpbGx1bV9mcmFjCgogICAgICAgICAgICAjIHdheGluZzogaWxs"
    "dW1pbmF0ZWQgcmlnaHQsIHNoYWRvdyBMRUZUCiAgICAgICAgICAgICMgd2FuaW5nOiBpbGx1bWluYXRlZCBsZWZ0LCBzaGFkb3cg"
    "UklHSFQKICAgICAgICAgICAgIyBvZmZzZXQgbW92ZXMgdGhlIHNoYWRvdyBlbGxpcHNlIGhvcml6b250YWxseQogICAgICAgICAg"
    "ICBvZmZzZXQgPSBpbnQoc2hhZG93X2ZyYWMgKiByICogMikKCiAgICAgICAgICAgIGlmIE1vb25XaWRnZXQuTU9PTl9TSEFET1df"
    "RkxJUDoKICAgICAgICAgICAgICAgIGlzX3dheGluZyA9IG5vdCBpc193YXhpbmcKCiAgICAgICAgICAgIGlmIGlzX3dheGluZzoK"
    "ICAgICAgICAgICAgICAgICMgU2hhZG93IG9uIGxlZnQgc2lkZQogICAgICAgICAgICAgICAgc2hhZG93X3ggPSBjeCAtIHIgLSBv"
    "ZmZzZXQKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICMgU2hhZG93IG9uIHJpZ2h0IHNpZGUKICAgICAgICAgICAg"
    "ICAgIHNoYWRvd194ID0gY3ggLSByICsgb2Zmc2V0CgogICAgICAgICAgICBwLnNldEJydXNoKFFDb2xvcigxNSwgOCwgMjIpKQog"
    "ICAgICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKCiAgICAgICAgICAgICMgRHJhdyBzaGFkb3cgZWxsaXBzZSDi"
    "gJQgY2xpcHBlZCB0byBtb29uIGNpcmNsZQogICAgICAgICAgICBtb29uX3BhdGggPSBRUGFpbnRlclBhdGgoKQogICAgICAgICAg"
    "ICBtb29uX3BhdGguYWRkRWxsaXBzZShmbG9hdChjeCAtIHIpLCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgZmxvYXQociAqIDIpLCBmbG9hdChyICogMikpCiAgICAgICAgICAgIHNoYWRvd19wYXRoID0gUVBhaW50ZXJQ"
    "YXRoKCkKICAgICAgICAgICAgc2hhZG93X3BhdGguYWRkRWxsaXBzZShmbG9hdChzaGFkb3dfeCksIGZsb2F0KGN5IC0gciksCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQogICAgICAgICAgICBj"
    "bGlwcGVkX3NoYWRvdyA9IG1vb25fcGF0aC5pbnRlcnNlY3RlZChzaGFkb3dfcGF0aCkKICAgICAgICAgICAgcC5kcmF3UGF0aChj"
    "bGlwcGVkX3NoYWRvdykKCiAgICAgICAgIyBTdWJ0bGUgc3VyZmFjZSBkZXRhaWwgKGNyYXRlcnMgaW1wbGllZCBieSBzbGlnaHQg"
    "dGV4dHVyZSBncmFkaWVudCkKICAgICAgICBzaGluZSA9IFFSYWRpYWxHcmFkaWVudChmbG9hdChjeCAtIHIgKiAwLjIpLCBmbG9h"
    "dChjeSAtIHIgKiAwLjIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAwLjgpKQogICAgICAgIHNo"
    "aW5lLnNldENvbG9yQXQoMCwgUUNvbG9yKDI1NSwgMjU1LCAyNDAsIDMwKSkKICAgICAgICBzaGluZS5zZXRDb2xvckF0KDEsIFFD"
    "b2xvcigyMDAsIDE4MCwgMTQwLCA1KSkKICAgICAgICBwLnNldEJydXNoKHNoaW5lKQogICAgICAgIHAuc2V0UGVuKFF0LlBlblN0"
    "eWxlLk5vUGVuKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBP"
    "dXRsaW5lCiAgICAgICAgcC5zZXRCcnVzaChRdC5CcnVzaFN0eWxlLk5vQnJ1c2gpCiAgICAgICAgcC5zZXRQZW4oUVBlbihRQ29s"
    "b3IoQ19TSUxWRVIpLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAg"
    "ICAgICMgUGhhc2UgbmFtZSBiZWxvdyBtb29uCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfU0lMVkVSKSkKICAgICAgICBwLnNl"
    "dEZvbnQoUUZvbnQoREVDS19GT05ULCA3LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkK"
    "ICAgICAgICBudyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHNlbGYuX25hbWUpCiAgICAgICAgcC5kcmF3VGV4dChjeCAtIG53IC8v"
    "IDIsIGN5ICsgciArIDE0LCBzZWxmLl9uYW1lKQoKICAgICAgICAjIElsbHVtaW5hdGlvbiBwZXJjZW50YWdlCiAgICAgICAgaWxs"
    "dW1fc3RyID0gZiJ7c2VsZi5faWxsdW1pbmF0aW9uOi4wZn0lIgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkK"
    "ICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAgICAgICBmbTIgPSBwLmZvbnRNZXRyaWNzKCkKICAgICAg"
    "ICBpdyA9IGZtMi5ob3Jpem9udGFsQWR2YW5jZShpbGx1bV9zdHIpCiAgICAgICAgcC5kcmF3VGV4dChjeCAtIGl3IC8vIDIsIGN5"
    "ICsgciArIDI0LCBpbGx1bV9zdHIpCgogICAgICAgICMgU3VuIHRpbWVzIGF0IHZlcnkgYm90dG9tCiAgICAgICAgc3VuX3N0ciA9"
    "IGYi4piAIHtzZWxmLl9zdW5yaXNlfSAg4pi9IHtzZWxmLl9zdW5zZXR9IgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0dPTERf"
    "RElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAgICAgICBmbTMgPSBwLmZvbnRNZXRyaWNzKCkK"
    "ICAgICAgICBzdyA9IGZtMy5ob3Jpem9udGFsQWR2YW5jZShzdW5fc3RyKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBzdyAvLyAy"
    "LCBoIC0gMiwgc3VuX3N0cikKCiAgICAgICAgcC5lbmQoKQoKCiMg4pSA4pSAIEVNT1RJT04gQkxPQ0sg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEVtb3Rpb25CbG9jayhRV2lkZ2V0KToKICAgICIiIgogICAgQ29sbGFwc2libGUgZW1v"
    "dGlvbiBoaXN0b3J5IHBhbmVsLgogICAgU2hvd3MgY29sb3ItY29kZWQgY2hpcHM6IOKcpiBFTU9USU9OX05BTUUgIEhIOk1NCiAg"
    "ICBTaXRzIG5leHQgdG8gdGhlIE1pcnJvciAoZmFjZSB3aWRnZXQpIGluIHRoZSBib3R0b20gYmxvY2sgcm93LgogICAgQ29sbGFw"
    "c2VzIHRvIGp1c3QgdGhlIGhlYWRlciBzdHJpcC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6"
    "CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5faGlzdG9yeTogbGlzdFt0dXBsZVtzdHIsIHN0"
    "cl1dID0gW10gICMgKGVtb3Rpb24sIHRpbWVzdGFtcCkKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IFRydWUKICAgICAgICBzZWxm"
    "Ll9tYXhfZW50cmllcyA9IDMwCgogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENv"
    "bnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDApCgogICAgICAgICMgSGVhZGVyIHJv"
    "dwogICAgICAgIGhlYWRlciA9IFFXaWRnZXQoKQogICAgICAgIGhlYWRlci5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBoZWFk"
    "ZXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXItYm90dG9tOiAxcHggc29s"
    "aWQge0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgaGwgPSBRSEJveExheW91dChoZWFkZXIpCiAgICAgICAgaGwu"
    "c2V0Q29udGVudHNNYXJnaW5zKDYsIDAsIDQsIDApCiAgICAgICAgaGwuc2V0U3BhY2luZyg0KQoKICAgICAgICBsYmwgPSBRTGFi"
    "ZWwoIuKdpyBFTU9USU9OQUwgUkVDT1JEIikKICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjog"
    "e0NfR09MRH07IGZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7"
    "REVDS19GT05UfSwgc2VyaWY7IGxldHRlci1zcGFjaW5nOiAxcHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNl"
    "bGYuX3RvZ2dsZV9idG4gPSBRVG9vbEJ1dHRvbigpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRGaXhlZFNpemUoMTYsIDE2"
    "KQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB0cmFuc3Bh"
    "cmVudDsgY29sb3I6IHtDX0dPTER9OyBib3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHNl"
    "bGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4pa8IikKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxm"
    "Ll90b2dnbGUpCgogICAgICAgIGhsLmFkZFdpZGdldChsYmwpCiAgICAgICAgaGwuYWRkU3RyZXRjaCgpCiAgICAgICAgaGwuYWRk"
    "V2lkZ2V0KHNlbGYuX3RvZ2dsZV9idG4pCgogICAgICAgICMgU2Nyb2xsIGFyZWEgZm9yIGVtb3Rpb24gY2hpcHMKICAgICAgICBz"
    "ZWxmLl9zY3JvbGwgPSBRU2Nyb2xsQXJlYSgpCiAgICAgICAgc2VsZi5fc2Nyb2xsLnNldFdpZGdldFJlc2l6YWJsZShUcnVlKQog"
    "ICAgICAgIHNlbGYuX3Njcm9sbC5zZXRIb3Jpem9udGFsU2Nyb2xsQmFyUG9saWN5KAogICAgICAgICAgICBRdC5TY3JvbGxCYXJQ"
    "b2xpY3kuU2Nyb2xsQmFyQWx3YXlzT2ZmKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBm"
    "ImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQoKICAgICAgICBzZWxmLl9jaGlwX2NvbnRhaW5l"
    "ciA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fY2hpcF9jb250YWluZXIp"
    "CiAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZi5fY2hp"
    "cF9sYXlvdXQuc2V0U3BhY2luZygyKQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LmFkZFN0cmV0Y2goKQogICAgICAgIHNlbGYu"
    "X3Njcm9sbC5zZXRXaWRnZXQoc2VsZi5fY2hpcF9jb250YWluZXIpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoaGVhZGVyKQog"
    "ICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fc2Nyb2xsKQoKICAgICAgICBzZWxmLnNldE1pbmltdW1XaWR0aCgxMzApCgog"
    "ICAgZGVmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAog"
    "ICAgICAgIHNlbGYuX3Njcm9sbC5zZXRWaXNpYmxlKHNlbGYuX2V4cGFuZGVkKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0"
    "VGV4dCgi4pa8IiBpZiBzZWxmLl9leHBhbmRlZCBlbHNlICLilrIiKQogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0cnkoKQoKICAg"
    "IGRlZiBhZGRFbW90aW9uKHNlbGYsIGVtb3Rpb246IHN0ciwgdGltZXN0YW1wOiBzdHIgPSAiIikgLT4gTm9uZToKICAgICAgICBp"
    "ZiBub3QgdGltZXN0YW1wOgogICAgICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU0iKQog"
    "ICAgICAgIHNlbGYuX2hpc3RvcnkuaW5zZXJ0KDAsIChlbW90aW9uLCB0aW1lc3RhbXApKQogICAgICAgIHNlbGYuX2hpc3Rvcnkg"
    "PSBzZWxmLl9oaXN0b3J5WzpzZWxmLl9tYXhfZW50cmllc10KICAgICAgICBzZWxmLl9yZWJ1aWxkX2NoaXBzKCkKCiAgICBkZWYg"
    "X3JlYnVpbGRfY2hpcHMoc2VsZikgLT4gTm9uZToKICAgICAgICAjIENsZWFyIGV4aXN0aW5nIGNoaXBzIChrZWVwIHRoZSBzdHJl"
    "dGNoIGF0IGVuZCkKICAgICAgICB3aGlsZSBzZWxmLl9jaGlwX2xheW91dC5jb3VudCgpID4gMToKICAgICAgICAgICAgaXRlbSA9"
    "IHNlbGYuX2NoaXBfbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICBpZiBpdGVtLndpZGdldCgpOgogICAgICAgICAgICAgICAg"
    "aXRlbS53aWRnZXQoKS5kZWxldGVMYXRlcigpCgogICAgICAgIGZvciBlbW90aW9uLCB0cyBpbiBzZWxmLl9oaXN0b3J5OgogICAg"
    "ICAgICAgICBjb2xvciA9IEVNT1RJT05fQ09MT1JTLmdldChlbW90aW9uLCBDX1RFWFRfRElNKQogICAgICAgICAgICBjaGlwID0g"
    "UUxhYmVsKGYi4pymIHtlbW90aW9uLnVwcGVyKCl9ICB7dHN9IikKICAgICAgICAgICAgY2hpcC5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICAgICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2Vy"
    "aWY7ICIKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsg"
    "IgogICAgICAgICAgICAgICAgZiJwYWRkaW5nOiAxcHggNHB4OyBib3JkZXItcmFkaXVzOiAycHg7IgogICAgICAgICAgICApCiAg"
    "ICAgICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0Lmluc2VydFdpZGdldCgKICAgICAgICAgICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0"
    "LmNvdW50KCkgLSAxLCBjaGlwCiAgICAgICAgICAgICkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9oaXN0b3J5LmNsZWFyKCkKICAgICAgICBzZWxmLl9yZWJ1aWxkX2NoaXBzKCkKCgojIOKUgOKUgCBNSVJST1IgV0lER0VUIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBNaXJyb3JXaWRnZXQoUUxhYmVsKToKICAgICIiIgogICAgRmFj"
    "ZSBpbWFnZSBkaXNwbGF5IOKAlCAnVGhlIE1pcnJvcicuCiAgICBEeW5hbWljYWxseSBsb2FkcyBhbGwge0ZBQ0VfUFJFRklYfV8q"
    "LnBuZyBmaWxlcyBmcm9tIGNvbmZpZyBwYXRocy5mYWNlcy4KICAgIEF1dG8tbWFwcyBmaWxlbmFtZSB0byBlbW90aW9uIGtleToK"
    "ICAgICAgICB7RkFDRV9QUkVGSVh9X0FsZXJ0LnBuZyAgICAg4oaSICJhbGVydCIKICAgICAgICB7RkFDRV9QUkVGSVh9X1NhZF9D"
    "cnlpbmcucG5nIOKGkiAic2FkIgogICAgICAgIHtGQUNFX1BSRUZJWH1fQ2hlYXRfTW9kZS5wbmcg4oaSICJjaGVhdG1vZGUiCiAg"
    "ICBGYWxscyBiYWNrIHRvIG5ldXRyYWwsIHRoZW4gdG8gZ290aGljIHBsYWNlaG9sZGVyIGlmIG5vIGltYWdlcyBmb3VuZC4KICAg"
    "IE1pc3NpbmcgZmFjZXMgZGVmYXVsdCB0byBuZXV0cmFsIOKAlCBubyBjcmFzaCwgbm8gaGFyZGNvZGVkIGxpc3QgcmVxdWlyZWQu"
    "CiAgICAiIiIKCiAgICAjIFNwZWNpYWwgc3RlbSDihpIgZW1vdGlvbiBrZXkgbWFwcGluZ3MgKGxvd2VyY2FzZSBzdGVtIGFmdGVy"
    "IE1vcmdhbm5hXykKICAgIF9TVEVNX1RPX0VNT1RJT046IGRpY3Rbc3RyLCBzdHJdID0gewogICAgICAgICJzYWRfY3J5aW5nIjog"
    "ICJzYWQiLAogICAgICAgICJjaGVhdF9tb2RlIjogICJjaGVhdG1vZGUiLAogICAgfQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBw"
    "YXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZmFjZXNfZGlyICAgPSBj"
    "ZmdfcGF0aCgiZmFjZXMiKQogICAgICAgIHNlbGYuX2NhY2hlOiBkaWN0W3N0ciwgUVBpeG1hcF0gPSB7fQogICAgICAgIHNlbGYu"
    "X2N1cnJlbnQgICAgID0gIm5ldXRyYWwiCiAgICAgICAgc2VsZi5fd2FybmVkOiBzZXRbc3RyXSA9IHNldCgpCgogICAgICAgIHNl"
    "bGYuc2V0TWluaW11bVNpemUoMTYwLCAxNjApCiAgICAgICAgc2VsZi5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGln"
    "bkNlbnRlcikKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9y"
    "ZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAg"
    "ICApCgogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDMwMCwgc2VsZi5fcHJlbG9hZCkKCiAgICBkZWYgX3ByZWxvYWQoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBTY2FuIEZhY2VzLyBkaXJlY3RvcnkgZm9yIGFsbCB7RkFDRV9QUkVGSVh9Xyou"
    "cG5nIGZpbGVzLgogICAgICAgIEJ1aWxkIGVtb3Rpb27ihpJwaXhtYXAgY2FjaGUgZHluYW1pY2FsbHkuCiAgICAgICAgTm8gaGFy"
    "ZGNvZGVkIGxpc3Qg4oCUIHdoYXRldmVyIGlzIGluIHRoZSBmb2xkZXIgaXMgYXZhaWxhYmxlLgogICAgICAgICIiIgogICAgICAg"
    "IGlmIG5vdCBzZWxmLl9mYWNlc19kaXIuZXhpc3RzKCk6CiAgICAgICAgICAgIHNlbGYuX2RyYXdfcGxhY2Vob2xkZXIoKQogICAg"
    "ICAgICAgICByZXR1cm4KCiAgICAgICAgZm9yIGltZ19wYXRoIGluIHNlbGYuX2ZhY2VzX2Rpci5nbG9iKGYie0ZBQ0VfUFJFRklY"
    "fV8qLnBuZyIpOgogICAgICAgICAgICAjIHN0ZW0gPSBldmVyeXRoaW5nIGFmdGVyICJNb3JnYW5uYV8iIHdpdGhvdXQgLnBuZwog"
    "ICAgICAgICAgICByYXdfc3RlbSA9IGltZ19wYXRoLnN0ZW1bbGVuKGYie0ZBQ0VfUFJFRklYfV8iKTpdICAgICMgZS5nLiAiU2Fk"
    "X0NyeWluZyIKICAgICAgICAgICAgc3RlbV9sb3dlciA9IHJhd19zdGVtLmxvd2VyKCkgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICMgInNhZF9jcnlpbmciCgogICAgICAgICAgICAjIE1hcCBzcGVjaWFsIHN0ZW1zIHRvIGVtb3Rpb24ga2V5cwogICAgICAgICAg"
    "ICBlbW90aW9uID0gc2VsZi5fU1RFTV9UT19FTU9USU9OLmdldChzdGVtX2xvd2VyLCBzdGVtX2xvd2VyKQoKICAgICAgICAgICAg"
    "cHggPSBRUGl4bWFwKHN0cihpbWdfcGF0aCkpCiAgICAgICAgICAgIGlmIG5vdCBweC5pc051bGwoKToKICAgICAgICAgICAgICAg"
    "IHNlbGYuX2NhY2hlW2Vtb3Rpb25dID0gcHgKCiAgICAgICAgaWYgc2VsZi5fY2FjaGU6CiAgICAgICAgICAgIHNlbGYuX3JlbmRl"
    "cigibmV1dHJhbCIpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fZHJhd19wbGFjZWhvbGRlcigpCgogICAgZGVmIF9y"
    "ZW5kZXIoc2VsZiwgZmFjZTogc3RyKSAtPiBOb25lOgogICAgICAgIGZhY2UgPSBmYWNlLmxvd2VyKCkuc3RyaXAoKQogICAgICAg"
    "IGlmIGZhY2Ugbm90IGluIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl93YXJuZWQgYW5kIGZh"
    "Y2UgIT0gIm5ldXRyYWwiOgogICAgICAgICAgICAgICAgcHJpbnQoZiJbTUlSUk9SXVtXQVJOXSBGYWNlIG5vdCBpbiBjYWNoZTog"
    "e2ZhY2V9IOKAlCB1c2luZyBuZXV0cmFsIikKICAgICAgICAgICAgICAgIHNlbGYuX3dhcm5lZC5hZGQoZmFjZSkKICAgICAgICAg"
    "ICAgZmFjZSA9ICJuZXV0cmFsIgogICAgICAgIGlmIGZhY2Ugbm90IGluIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBzZWxmLl9k"
    "cmF3X3BsYWNlaG9sZGVyKCkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fY3VycmVudCA9IGZhY2UKICAgICAgICBw"
    "eCA9IHNlbGYuX2NhY2hlW2ZhY2VdCiAgICAgICAgc2NhbGVkID0gcHguc2NhbGVkKAogICAgICAgICAgICBzZWxmLndpZHRoKCkg"
    "LSA0LAogICAgICAgICAgICBzZWxmLmhlaWdodCgpIC0gNCwKICAgICAgICAgICAgUXQuQXNwZWN0UmF0aW9Nb2RlLktlZXBBc3Bl"
    "Y3RSYXRpbywKICAgICAgICAgICAgUXQuVHJhbnNmb3JtYXRpb25Nb2RlLlNtb290aFRyYW5zZm9ybWF0aW9uLAogICAgICAgICkK"
    "ICAgICAgICBzZWxmLnNldFBpeG1hcChzY2FsZWQpCiAgICAgICAgc2VsZi5zZXRUZXh0KCIiKQoKICAgIGRlZiBfZHJhd19wbGFj"
    "ZWhvbGRlcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuY2xlYXIoKQogICAgICAgIHNlbGYuc2V0VGV4dCgi4pymXG7inadc"
    "buKcpiIpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImNvbG9yOiB7Q19DUklNU09OX0RJTX07IGZvbnQt"
    "c2l6ZTogMjRweDsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCgogICAgZGVmIHNldF9mYWNlKHNlbGYsIGZhY2U6IHN0"
    "cikgLT4gTm9uZToKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgwLCBsYW1iZGE6IHNlbGYuX3JlbmRlcihmYWNlKSkKCiAgICBk"
    "ZWYgcmVzaXplRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgc3VwZXIoKS5yZXNpemVFdmVudChldmVudCkKICAg"
    "ICAgICBpZiBzZWxmLl9jYWNoZToKICAgICAgICAgICAgc2VsZi5fcmVuZGVyKHNlbGYuX2N1cnJlbnQpCgogICAgQHByb3BlcnR5"
    "CiAgICBkZWYgY3VycmVudF9mYWNlKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4gc2VsZi5fY3VycmVudAoKCiMg4pSA4pSA"
    "IFZBTVBJUkUgU1RBVEUgU1RSSVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEN5Y2xlV2lkZ2V0KE1vb25XaWRnZXQpOgogICAgIiIi"
    "R2VuZXJpYyBjeWNsZSB2aXN1YWxpemF0aW9uIHdpZGdldCAoY3VycmVudGx5IGx1bmFyLXBoYXNlIGRyaXZlbikuIiIiCgoKY2xh"
    "c3MgVmFtcGlyZVN0YXRlU3RyaXAoUVdpZGdldCk6CiAgICAiIiIKICAgIEZ1bGwtd2lkdGggc3RhdHVzIGJhciBzaG93aW5nOgog"
    "ICAgICBbIOKcpiBWQU1QSVJFX1NUQVRFICDigKIgIEhIOk1NICDigKIgIOKYgCBTVU5SSVNFICDimL0gU1VOU0VUICDigKIgIE1P"
    "T04gUEhBU0UgIElMTFVNJSBdCiAgICBBbHdheXMgdmlzaWJsZSwgbmV2ZXIgY29sbGFwc2VzLgogICAgVXBkYXRlcyBldmVyeSBt"
    "aW51dGUgdmlhIGV4dGVybmFsIFFUaW1lciBjYWxsIHRvIHJlZnJlc2goKS4KICAgIENvbG9yLWNvZGVkIGJ5IGN1cnJlbnQgdmFt"
    "cGlyZSBzdGF0ZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5f"
    "X2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fbGFiZWxfcHJlZml4ID0gIlNUQVRFIgogICAgICAgIHNlbGYuX3N0YXRlICAg"
    "ICA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgICAgICBzZWxmLl90aW1lX3N0ciAgPSAiIgogICAgICAgIHNlbGYuX3N1bnJpc2Ug"
    "ICA9ICIwNjowMCIKICAgICAgICBzZWxmLl9zdW5zZXQgICAgPSAiMTg6MzAiCiAgICAgICAgc2VsZi5fc3VuX2RhdGUgID0gTm9u"
    "ZQogICAgICAgIHNlbGYuX21vb25fbmFtZSA9ICJORVcgTU9PTiIKICAgICAgICBzZWxmLl9pbGx1bSAgICAgPSAwLjAKICAgICAg"
    "ICBzZWxmLnNldEZpeGVkSGVpZ2h0KDI4KQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07"
    "IGJvcmRlci10b3A6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IikKICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQog"
    "ICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIHNldF9sYWJlbChzZWxmLCBsYWJlbDogc3RyKSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYuX2xhYmVsX3ByZWZpeCA9IChsYWJlbCBvciAiU1RBVEUiKS5zdHJpcCgpLnVwcGVyKCkKICAgICAgICBzZWxmLnVwZGF0"
    "ZSgpCgogICAgZGVmIF9mZXRjaF9zdW5fYXN5bmMoc2VsZikgLT4gTm9uZToKICAgICAgICBkZWYgX2YoKToKICAgICAgICAgICAg"
    "c3IsIHNzID0gZ2V0X3N1bl90aW1lcygpCiAgICAgICAgICAgIHNlbGYuX3N1bnJpc2UgPSBzcgogICAgICAgICAgICBzZWxmLl9z"
    "dW5zZXQgID0gc3MKICAgICAgICAgICAgc2VsZi5fc3VuX2RhdGUgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkuZGF0ZSgp"
    "CiAgICAgICAgICAgICMgU2NoZWR1bGUgcmVwYWludCBvbiBtYWluIHRocmVhZCDigJQgbmV2ZXIgY2FsbCB1cGRhdGUoKSBmcm9t"
    "CiAgICAgICAgICAgICMgYSBiYWNrZ3JvdW5kIHRocmVhZCwgaXQgY2F1c2VzIFFUaHJlYWQgY3Jhc2ggb24gc3RhcnR1cAogICAg"
    "ICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgwLCBzZWxmLnVwZGF0ZSkKICAgICAgICB0aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1f"
    "ZiwgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YXRl"
    "ICAgICA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgICAgICBzZWxmLl90aW1lX3N0ciAgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6"
    "b25lKCkuc3RyZnRpbWUoIiVYIikKICAgICAgICB0b2RheSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAg"
    "ICAgICBpZiBzZWxmLl9zdW5fZGF0ZSAhPSB0b2RheToKICAgICAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAg"
    "ICBfLCBzZWxmLl9tb29uX25hbWUsIHNlbGYuX2lsbHVtID0gZ2V0X21vb25fcGhhc2UoKQogICAgICAgIHNlbGYudXBkYXRlKCkK"
    "CiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAg"
    "ICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lk"
    "dGgoKSwgc2VsZi5oZWlnaHQoKQoKICAgICAgICBwLmZpbGxSZWN0KDAsIDAsIHcsIGgsIFFDb2xvcihDX0JHMikpCgogICAgICAg"
    "IHN0YXRlX2NvbG9yID0gZ2V0X3ZhbXBpcmVfc3RhdGVfY29sb3Ioc2VsZi5fc3RhdGUpCiAgICAgICAgdGV4dCA9ICgKICAgICAg"
    "ICAgICAgZiLinKYgIHtzZWxmLl9sYWJlbF9wcmVmaXh9OiB7c2VsZi5fc3RhdGV9ICDigKIgIHtzZWxmLl90aW1lX3N0cn0gIOKA"
    "oiAgIgogICAgICAgICAgICBmIuKYgCB7c2VsZi5fc3VucmlzZX0gICAg4pi9IHtzZWxmLl9zdW5zZXR9ICDigKIgICIKICAgICAg"
    "ICAgICAgZiJ7c2VsZi5fbW9vbl9uYW1lfSAge3NlbGYuX2lsbHVtOi4wZn0lIgogICAgICAgICkKCiAgICAgICAgcC5zZXRGb250"
    "KFFGb250KERFQ0tfRk9OVCwgOSwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihzdGF0ZV9jb2xv"
    "cikpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICB0dyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHRleHQpCiAg"
    "ICAgICAgcC5kcmF3VGV4dCgodyAtIHR3KSAvLyAyLCBoIC0gNywgdGV4dCkKCiAgICAgICAgcC5lbmQoKQoKCmNsYXNzIE1pbmlD"
    "YWxlbmRhcldpZGdldChRV2lkZ2V0KToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIo"
    "KS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29u"
    "dGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgaGVhZGVyID0gUUhC"
    "b3hMYXlvdXQoKQogICAgICAgIGhlYWRlci5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLnByZXZf"
    "YnRuID0gUVB1c2hCdXR0b24oIjw8IikKICAgICAgICBzZWxmLm5leHRfYnRuID0gUVB1c2hCdXR0b24oIj4+IikKICAgICAgICBz"
    "ZWxmLm1vbnRoX2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLm1vbnRoX2xibC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50"
    "RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBmb3IgYnRuIGluIChzZWxmLnByZXZfYnRuLCBzZWxmLm5leHRfYnRuKToKICAgICAg"
    "ICAgICAgYnRuLnNldEZpeGVkV2lkdGgoMzQpCiAgICAgICAgICAgIGJ0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAg"
    "ZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsg"
    "IgogICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDEwcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAycHg7IgogICAg"
    "ICAgICAgICApCiAgICAgICAgc2VsZi5tb250aF9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09M"
    "RH07IGJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyBmb250LXdlaWdodDogYm9sZDsiCiAgICAgICAgKQogICAgICAgIGhl"
    "YWRlci5hZGRXaWRnZXQoc2VsZi5wcmV2X2J0bikKICAgICAgICBoZWFkZXIuYWRkV2lkZ2V0KHNlbGYubW9udGhfbGJsLCAxKQog"
    "ICAgICAgIGhlYWRlci5hZGRXaWRnZXQoc2VsZi5uZXh0X2J0bikKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGhlYWRlcikKCiAg"
    "ICAgICAgc2VsZi5jYWxlbmRhciA9IFFDYWxlbmRhcldpZGdldCgpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRHcmlkVmlzaWJs"
    "ZShUcnVlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0VmVydGljYWxIZWFkZXJGb3JtYXQoUUNhbGVuZGFyV2lkZ2V0LlZlcnRp"
    "Y2FsSGVhZGVyRm9ybWF0Lk5vVmVydGljYWxIZWFkZXIpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXROYXZpZ2F0aW9uQmFyVmlz"
    "aWJsZShGYWxzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lk"
    "Z2V0IFFXaWRnZXR7e2FsdGVybmF0ZS1iYWNrZ3JvdW5kLWNvbG9yOntDX0JHMn07fX0gIgogICAgICAgICAgICBmIlFUb29sQnV0"
    "dG9ue3tjb2xvcjp7Q19HT0xEfTt9fSAiCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFBYnN0cmFjdEl0ZW1WaWV3OmVu"
    "YWJsZWR7e2JhY2tncm91bmQ6e0NfQkcyfTsgY29sb3I6I2ZmZmZmZjsgIgogICAgICAgICAgICBmInNlbGVjdGlvbi1iYWNrZ3Jv"
    "dW5kLWNvbG9yOntDX0NSSU1TT05fRElNfTsgc2VsZWN0aW9uLWNvbG9yOntDX1RFWFR9OyBncmlkbGluZS1jb2xvcjp7Q19CT1JE"
    "RVJ9O319ICIKICAgICAgICAgICAgZiJRQ2FsZW5kYXJXaWRnZXQgUUFic3RyYWN0SXRlbVZpZXc6ZGlzYWJsZWR7e2NvbG9yOiM4"
    "Yjk1YTE7fX0iCiAgICAgICAgKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5jYWxlbmRhcikKCiAgICAgICAgc2VsZi5w"
    "cmV2X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLmNhbGVuZGFyLnNob3dQcmV2aW91c01vbnRoKCkpCiAgICAgICAg"
    "c2VsZi5uZXh0X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLmNhbGVuZGFyLnNob3dOZXh0TW9udGgoKSkKICAgICAg"
    "ICBzZWxmLmNhbGVuZGFyLmN1cnJlbnRQYWdlQ2hhbmdlZC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9sYWJlbCkKICAgICAgICBzZWxm"
    "Ll91cGRhdGVfbGFiZWwoKQogICAgICAgIHNlbGYuX2FwcGx5X2Zvcm1hdHMoKQoKICAgIGRlZiBfdXBkYXRlX2xhYmVsKHNlbGYs"
    "ICphcmdzKToKICAgICAgICB5ZWFyID0gc2VsZi5jYWxlbmRhci55ZWFyU2hvd24oKQogICAgICAgIG1vbnRoID0gc2VsZi5jYWxl"
    "bmRhci5tb250aFNob3duKCkKICAgICAgICBzZWxmLm1vbnRoX2xibC5zZXRUZXh0KGYie2RhdGUoeWVhciwgbW9udGgsIDEpLnN0"
    "cmZ0aW1lKCclQiAlWScpfSIpCiAgICAgICAgc2VsZi5fYXBwbHlfZm9ybWF0cygpCgogICAgZGVmIF9hcHBseV9mb3JtYXRzKHNl"
    "bGYpOgogICAgICAgIGJhc2UgPSBRVGV4dENoYXJGb3JtYXQoKQogICAgICAgIGJhc2Uuc2V0Rm9yZWdyb3VuZChRQ29sb3IoIiNl"
    "N2VkZjMiKSkKICAgICAgICBzYXR1cmRheSA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgc2F0dXJkYXkuc2V0Rm9yZWdyb3Vu"
    "ZChRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgc3VuZGF5ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICBzdW5kYXkuc2V0"
    "Rm9yZWdyb3VuZChRQ29sb3IoQ19CTE9PRCkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5E"
    "YXlPZldlZWsuTW9uZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZX"
    "ZWVrLlR1ZXNkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsu"
    "V2VkbmVzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlRo"
    "dXJzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLkZyaWRh"
    "eSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5TYXR1cmRheSwg"
    "c2F0dXJkYXkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuU3VuZGF5LCBz"
    "dW5kYXkpCgogICAgICAgIHllYXIgPSBzZWxmLmNhbGVuZGFyLnllYXJTaG93bigpCiAgICAgICAgbW9udGggPSBzZWxmLmNhbGVu"
    "ZGFyLm1vbnRoU2hvd24oKQogICAgICAgIGZpcnN0X2RheSA9IFFEYXRlKHllYXIsIG1vbnRoLCAxKQogICAgICAgIGZvciBkYXkg"
    "aW4gcmFuZ2UoMSwgZmlyc3RfZGF5LmRheXNJbk1vbnRoKCkgKyAxKToKICAgICAgICAgICAgZCA9IFFEYXRlKHllYXIsIG1vbnRo"
    "LCBkYXkpCiAgICAgICAgICAgIGZtdCA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgICAgIHdlZWtkYXkgPSBkLmRheU9mV2Vl"
    "aygpCiAgICAgICAgICAgIGlmIHdlZWtkYXkgPT0gUXQuRGF5T2ZXZWVrLlNhdHVyZGF5LnZhbHVlOgogICAgICAgICAgICAgICAg"
    "Zm10LnNldEZvcmVncm91bmQoUUNvbG9yKENfR09MRF9ESU0pKQogICAgICAgICAgICBlbGlmIHdlZWtkYXkgPT0gUXQuRGF5T2ZX"
    "ZWVrLlN1bmRheS52YWx1ZToKICAgICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0JMT09EKSkKICAgICAg"
    "ICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcigiI2U3ZWRmMyIpKQogICAgICAgICAg"
    "ICBzZWxmLmNhbGVuZGFyLnNldERhdGVUZXh0Rm9ybWF0KGQsIGZtdCkKCiAgICAgICAgdG9kYXlfZm10ID0gUVRleHRDaGFyRm9y"
    "bWF0KCkKICAgICAgICB0b2RheV9mbXQuc2V0Rm9yZWdyb3VuZChRQ29sb3IoIiM2OGQzOWEiKSkKICAgICAgICB0b2RheV9mbXQu"
    "c2V0QmFja2dyb3VuZChRQ29sb3IoIiMxNjM4MjUiKSkKICAgICAgICB0b2RheV9mbXQuc2V0Rm9udFdlaWdodChRRm9udC5XZWln"
    "aHQuQm9sZCkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldERhdGVUZXh0Rm9ybWF0KFFEYXRlLmN1cnJlbnREYXRlKCksIHRvZGF5"
    "X2ZtdCkKCgojIOKUgOKUgCBDT0xMQVBTSUJMRSBCTE9DSyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgQ29sbGFwc2libGVC"
    "bG9jayhRV2lkZ2V0KToKICAgICIiIgogICAgV3JhcHBlciB0aGF0IGFkZHMgYSBjb2xsYXBzZS9leHBhbmQgdG9nZ2xlIHRvIGFu"
    "eSB3aWRnZXQuCiAgICBDb2xsYXBzZXMgaG9yaXpvbnRhbGx5IChyaWdodHdhcmQpIOKAlCBoaWRlcyBjb250ZW50LCBrZWVwcyBo"
    "ZWFkZXIgc3RyaXAuCiAgICBIZWFkZXIgc2hvd3MgbGFiZWwuIFRvZ2dsZSBidXR0b24gb24gcmlnaHQgZWRnZSBvZiBoZWFkZXIu"
    "CgogICAgVXNhZ2U6CiAgICAgICAgYmxvY2sgPSBDb2xsYXBzaWJsZUJsb2NrKCLinacgQkxPT0QiLCBTcGhlcmVXaWRnZXQoLi4u"
    "KSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGJsb2NrKQogICAgIiIiCgogICAgdG9nZ2xlZCA9IFNpZ25hbChib29sKQoKICAg"
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
    "KCkKCiAgICBkZWYgaXNfZXhwYW5kZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fZXhwYW5kZWQKCiAgICBk"
    "ZWYgX3RvZ2dsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAgICAg"
    "ICAgc2VsZi5fYXBwbHlfc3RhdGUoKQogICAgICAgIHNlbGYudG9nZ2xlZC5lbWl0KHNlbGYuX2V4cGFuZGVkKQoKICAgIGRlZiBf"
    "YXBwbHlfc3RhdGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9jb250ZW50LnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQp"
    "CiAgICAgICAgc2VsZi5fYnRuLnNldFRleHQoIjwiIGlmIHNlbGYuX2V4cGFuZGVkIGVsc2UgIj4iKQoKICAgICAgICAjIFJlc2Vy"
    "dmUgZml4ZWQgc2xvdCB3aWR0aCB3aGVuIHJlcXVlc3RlZCAodXNlZCBieSBtaWRkbGUgbG93ZXIgYmxvY2spCiAgICAgICAgaWYg"
    "c2VsZi5fcmVzZXJ2ZV93aWR0aDoKICAgICAgICAgICAgc2VsZi5zZXRNaW5pbXVtV2lkdGgoc2VsZi5fbWluX3dpZHRoKQogICAg"
    "ICAgICAgICBzZWxmLnNldE1heGltdW1XaWR0aCgxNjc3NzIxNSkKICAgICAgICBlbGlmIHNlbGYuX2V4cGFuZGVkOgogICAgICAg"
    "ICAgICBzZWxmLnNldE1pbmltdW1XaWR0aChzZWxmLl9taW5fd2lkdGgpCiAgICAgICAgICAgIHNlbGYuc2V0TWF4aW11bVdpZHRo"
    "KDE2Nzc3MjE1KSAgIyB1bmNvbnN0cmFpbmVkCiAgICAgICAgZWxzZToKICAgICAgICAgICAgIyBDb2xsYXBzZWQ6IGp1c3QgdGhl"
    "IGhlYWRlciBzdHJpcCAobGFiZWwgKyBidXR0b24pCiAgICAgICAgICAgIGNvbGxhcHNlZF93ID0gc2VsZi5faGVhZGVyLnNpemVI"
    "aW50KCkud2lkdGgoKQogICAgICAgICAgICBzZWxmLnNldEZpeGVkV2lkdGgobWF4KDYwLCBjb2xsYXBzZWRfdykpCgogICAgICAg"
    "IHNlbGYudXBkYXRlR2VvbWV0cnkoKQogICAgICAgIHBhcmVudCA9IHNlbGYucGFyZW50V2lkZ2V0KCkKICAgICAgICBpZiBwYXJl"
    "bnQgYW5kIHBhcmVudC5sYXlvdXQoKToKICAgICAgICAgICAgcGFyZW50LmxheW91dCgpLmFjdGl2YXRlKCkKCgojIOKUgOKUgCBI"
    "QVJEV0FSRSBQQU5FTCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSGFyZHdhcmVQYW5lbChRV2lkZ2V0KToK"
    "ICAgICIiIgogICAgVGhlIHN5c3RlbXMgcmlnaHQgcGFuZWwgY29udGVudHMuCiAgICBHcm91cHM6IHN0YXR1cyBpbmZvLCBkcml2"
    "ZSBiYXJzLCBDUFUvUkFNIGdhdWdlcywgR1BVL1ZSQU0gZ2F1Z2VzLCBHUFUgdGVtcC4KICAgIFJlcG9ydHMgaGFyZHdhcmUgYXZh"
    "aWxhYmlsaXR5IGluIERpYWdub3N0aWNzIG9uIHN0YXJ0dXAuCiAgICBTaG93cyBOL0EgZ3JhY2VmdWxseSB3aGVuIGRhdGEgdW5h"
    "dmFpbGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19p"
    "bml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLl9kZXRlY3RfaGFyZHdhcmUoKQoKICAg"
    "IGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxh"
    "eW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICBk"
    "ZWYgc2VjdGlvbl9sYWJlbCh0ZXh0OiBzdHIpIC0+IFFMYWJlbDoKICAgICAgICAgICAgbGJsID0gUUxhYmVsKHRleHQpCiAgICAg"
    "ICAgICAgIGxibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogOXB4"
    "OyBsZXR0ZXItc3BhY2luZzogMnB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7"
    "IGZvbnQtd2VpZ2h0OiBib2xkOyIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4gbGJsCgogICAgICAgICMg4pSA4pSA"
    "IFN0YXR1cyBibG9jayDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKdpyBTVEFUVVMiKSkKICAgICAgICBzdGF0dXNfZnJh"
    "bWUgPSBRRnJhbWUoKQogICAgICAgIHN0YXR1c19mcmFtZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6"
    "IHtDX1BBTkVMfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCiAg"
    "ICAgICAgc3RhdHVzX2ZyYW1lLnNldEZpeGVkSGVpZ2h0KDg4KQogICAgICAgIHNmID0gUVZCb3hMYXlvdXQoc3RhdHVzX2ZyYW1l"
    "KQogICAgICAgIHNmLnNldENvbnRlbnRzTWFyZ2lucyg4LCA0LCA4LCA0KQogICAgICAgIHNmLnNldFNwYWNpbmcoMikKCiAgICAg"
    "ICAgc2VsZi5sYmxfc3RhdHVzICA9IFFMYWJlbCgi4pymIFNUQVRVUzogT0ZGTElORSIpCiAgICAgICAgc2VsZi5sYmxfbW9kZWwg"
    "ICA9IFFMYWJlbCgi4pymIFZFU1NFTDogTE9BRElORy4uLiIpCiAgICAgICAgc2VsZi5sYmxfc2Vzc2lvbiA9IFFMYWJlbCgi4pym"
    "IFNFU1NJT046IDAwOjAwOjAwIikKICAgICAgICBzZWxmLmxibF90b2tlbnMgID0gUUxhYmVsKCLinKYgVE9LRU5TOiAwIikKCiAg"
    "ICAgICAgZm9yIGxibCBpbiAoc2VsZi5sYmxfc3RhdHVzLCBzZWxmLmxibF9tb2RlbCwKICAgICAgICAgICAgICAgICAgICBzZWxm"
    "LmxibF9zZXNzaW9uLCBzZWxmLmxibF90b2tlbnMpOgogICAgICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5"
    "OiB7REVDS19GT05UfSwgc2VyaWY7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2YuYWRkV2lkZ2V0"
    "KGxibCkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzdGF0dXNfZnJhbWUpCgogICAgICAgICMg4pSA4pSAIERyaXZlIGJhcnMg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgU1RPUkFHRSIpKQogICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0"
    "ID0gRHJpdmVXaWRnZXQoKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5kcml2ZV93aWRnZXQpCgogICAgICAgICMg4pSA"
    "4pSAIENQVSAvIFJBTSBnYXVnZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgVklUQUwgRVNTRU5DRSIpKQogICAgICAgIHJhbV9jcHUg"
    "PSBRR3JpZExheW91dCgpCiAgICAgICAgcmFtX2NwdS5zZXRTcGFjaW5nKDMpCgogICAgICAgIHNlbGYuZ2F1Z2VfY3B1ICA9IEdh"
    "dWdlV2lkZ2V0KCJDUFUiLCAgIiUiLCAgIDEwMC4wLCBDX1NJTFZFUikKICAgICAgICBzZWxmLmdhdWdlX3JhbSAgPSBHYXVnZVdp"
    "ZGdldCgiUkFNIiwgICJHQiIsICAgNjQuMCwgQ19HT0xEX0RJTSkKICAgICAgICByYW1fY3B1LmFkZFdpZGdldChzZWxmLmdhdWdl"
    "X2NwdSwgMCwgMCkKICAgICAgICByYW1fY3B1LmFkZFdpZGdldChzZWxmLmdhdWdlX3JhbSwgMCwgMSkKICAgICAgICBsYXlvdXQu"
    "YWRkTGF5b3V0KHJhbV9jcHUpCgogICAgICAgICMg4pSA4pSAIEdQVSAvIFZSQU0gZ2F1Z2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIEFS"
    "Q0FORSBQT1dFUiIpKQogICAgICAgIGdwdV92cmFtID0gUUdyaWRMYXlvdXQoKQogICAgICAgIGdwdV92cmFtLnNldFNwYWNpbmco"
    "MykKCiAgICAgICAgc2VsZi5nYXVnZV9ncHUgID0gR2F1Z2VXaWRnZXQoIkdQVSIsICAiJSIsICAgMTAwLjAsIENfUFVSUExFKQog"
    "ICAgICAgIHNlbGYuZ2F1Z2VfdnJhbSA9IEdhdWdlV2lkZ2V0KCJWUkFNIiwgIkdCIiwgICAgOC4wLCBDX0NSSU1TT04pCiAgICAg"
    "ICAgZ3B1X3ZyYW0uYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfZ3B1LCAgMCwgMCkKICAgICAgICBncHVfdnJhbS5hZGRXaWRnZXQoc2Vs"
    "Zi5nYXVnZV92cmFtLCAwLCAxKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoZ3B1X3ZyYW0pCgogICAgICAgICMg4pSA4pSAIEdQ"
    "VSBUZW1wIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEhFQVQiKSkKICAgICAg"
    "ICBzZWxmLmdhdWdlX3RlbXAgPSBHYXVnZVdpZGdldCgiR1BVIFRFTVAiLCAiwrBDIiwgOTUuMCwgQ19CTE9PRCkKICAgICAgICBz"
    "ZWxmLmdhdWdlX3RlbXAuc2V0TWF4aW11bUhlaWdodCg2NSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfdGVt"
    "cCkKCiAgICAgICAgIyDilIDilIAgR1BVIG1hc3RlciBiYXIgKGZ1bGwgd2lkdGgpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAg"
    "IGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEVOR0lORSIpKQogICAgICAgIHNlbGYuZ2F1Z2Vf"
    "Z3B1X21hc3RlciA9IEdhdWdlV2lkZ2V0KCJSVFgiLCAiJSIsIDEwMC4wLCBDX0NSSU1TT04pCiAgICAgICAgc2VsZi5nYXVnZV9n"
    "cHVfbWFzdGVyLnNldE1heGltdW1IZWlnaHQoNTUpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmdhdWdlX2dwdV9tYXN0"
    "ZXIpCgogICAgICAgIGxheW91dC5hZGRTdHJldGNoKCkKCiAgICBkZWYgX2RldGVjdF9oYXJkd2FyZShzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgICIiIgogICAgICAgIENoZWNrIHdoYXQgaGFyZHdhcmUgbW9uaXRvcmluZyBpcyBhdmFpbGFibGUuCiAgICAgICAgTWFy"
    "ayB1bmF2YWlsYWJsZSBnYXVnZXMgYXBwcm9wcmlhdGVseS4KICAgICAgICBEaWFnbm9zdGljIG1lc3NhZ2VzIGNvbGxlY3RlZCBm"
    "b3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgICAgICAiIiIKICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzOiBsaXN0W3N0cl0g"
    "PSBbXQoKICAgICAgICBpZiBub3QgUFNVVElMX09LOgogICAgICAgICAgICBzZWxmLmdhdWdlX2NwdS5zZXRVbmF2YWlsYWJsZSgp"
    "CiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdl"
    "cy5hcHBlbmQoCiAgICAgICAgICAgICAgICAiW0hBUkRXQVJFXSBwc3V0aWwgbm90IGF2YWlsYWJsZSDigJQgQ1BVL1JBTSBnYXVn"
    "ZXMgZGlzYWJsZWQuICIKICAgICAgICAgICAgICAgICJwaXAgaW5zdGFsbCBwc3V0aWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAg"
    "KQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKCJbSEFSRFdBUkVdIHBzdXRpbCBP"
    "SyDigJQgQ1BVL1JBTSBtb25pdG9yaW5nIGFjdGl2ZS4iKQoKICAgICAgICBpZiBub3QgTlZNTF9PSzoKICAgICAgICAgICAgc2Vs"
    "Zi5nYXVnZV9ncHUuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VW5hdmFpbGFibGUoKQog"
    "ICAgICAgICAgICBzZWxmLmdhdWdlX3RlbXAuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0"
    "ZXIuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAg"
    "ICJbSEFSRFdBUkVdIHB5bnZtbCBub3QgYXZhaWxhYmxlIG9yIG5vIE5WSURJQSBHUFUgZGV0ZWN0ZWQg4oCUICIKICAgICAgICAg"
    "ICAgICAgICJHUFUgZ2F1Z2VzIGRpc2FibGVkLiBwaXAgaW5zdGFsbCBweW52bWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQog"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdldE5h"
    "bWUoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIGlmIGlzaW5zdGFuY2UobmFtZSwgYnl0ZXMpOgogICAgICAgICAgICAgICAg"
    "ICAgIG5hbWUgPSBuYW1lLmRlY29kZSgpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAg"
    "ICAgICAgICAgICAgICBmIltIQVJEV0FSRV0gcHludm1sIE9LIOKAlCBHUFUgZGV0ZWN0ZWQ6IHtuYW1lfSIKICAgICAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgICAgICMgVXBkYXRlIG1heCBWUkFNIGZyb20gYWN0dWFsIGhhcmR3YXJlCiAgICAgICAgICAgICAg"
    "ICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIHRvdGFsX2di"
    "ID0gbWVtLnRvdGFsIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV92cmFtLm1heF92YWwgPSB0b3RhbF9nYgog"
    "ICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVu"
    "ZChmIltIQVJEV0FSRV0gcHludm1sIGVycm9yOiB7ZX0iKQoKICAgIGRlZiB1cGRhdGVfc3RhdHMoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICAiIiIKICAgICAgICBDYWxsZWQgZXZlcnkgc2Vjb25kIGZyb20gdGhlIHN0YXRzIFFUaW1lci4KICAgICAgICBSZWFkcyBo"
    "YXJkd2FyZSBhbmQgdXBkYXRlcyBhbGwgZ2F1Z2VzLgogICAgICAgICIiIgogICAgICAgIGlmIFBTVVRJTF9PSzoKICAgICAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICAgICAgY3B1ID0gcHN1dGlsLmNwdV9wZXJjZW50KCkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1"
    "Z2VfY3B1LnNldFZhbHVlKGNwdSwgZiJ7Y3B1Oi4wZn0lIiwgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICAgICAgICAgbWVtID0g"
    "cHN1dGlsLnZpcnR1YWxfbWVtb3J5KCkKICAgICAgICAgICAgICAgIHJ1ICA9IG1lbS51c2VkICAvIDEwMjQqKjMKICAgICAgICAg"
    "ICAgICAgIHJ0ICA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFZhbHVlKHJ1"
    "LCBmIntydTouMWZ9L3tydDouMGZ9R0IiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxl"
    "PVRydWUpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3JhbS5tYXhfdmFsID0gcnQKICAgICAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgaWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICAgICAgdXRpbCAgICAgPSBweW52bWwubnZtbERldmljZUdldFV0aWxpemF0aW9uUmF0ZXMoZ3B1X2hh"
    "bmRsZSkKICAgICAgICAgICAgICAgIG1lbV9pbmZvID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUp"
    "CiAgICAgICAgICAgICAgICB0ZW1wICAgICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0VGVtcGVyYXR1cmUoCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICBncHVfaGFuZGxlLCBweW52bWwuTlZNTF9URU1QRVJBVFVSRV9HUFUpCgogICAgICAgICAgICAgICAg"
    "Z3B1X3BjdCAgID0gZmxvYXQodXRpbC5ncHUpCiAgICAgICAgICAgICAgICB2cmFtX3VzZWQgPSBtZW1faW5mby51c2VkICAvIDEw"
    "MjQqKjMKICAgICAgICAgICAgICAgIHZyYW1fdG90ICA9IG1lbV9pbmZvLnRvdGFsIC8gMTAyNCoqMwoKICAgICAgICAgICAgICAg"
    "IHNlbGYuZ2F1Z2VfZ3B1LnNldFZhbHVlKGdwdV9wY3QsIGYie2dwdV9wY3Q6LjBmfSUiLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VmFsdWUo"
    "dnJhbV91c2VkLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYie3ZyYW1fdXNlZDouMWZ9L3t2cmFt"
    "X3RvdDouMGZ9R0IiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQogICAg"
    "ICAgICAgICAgICAgc2VsZi5nYXVnZV90ZW1wLnNldFZhbHVlKGZsb2F0KHRlbXApLCBmInt0ZW1wfcKwQyIsCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdldE5hbWUoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgICAg"
    "ICBpZiBpc2luc3RhbmNlKG5hbWUsIGJ5dGVzKToKICAgICAgICAgICAgICAgICAgICAgICAgbmFtZSA9IG5hbWUuZGVjb2RlKCkK"
    "ICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgbmFtZSA9ICJHUFUiCgogICAgICAg"
    "ICAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldFZhbHVlKAogICAgICAgICAgICAgICAgICAgIGdwdV9wY3QsCiAgICAg"
    "ICAgICAgICAgICAgICAgZiJ7bmFtZX0gIHtncHVfcGN0Oi4wZn0lICAiCiAgICAgICAgICAgICAgICAgICAgZiJbe3ZyYW1fdXNl"
    "ZDouMWZ9L3t2cmFtX3RvdDouMGZ9R0IgVlJBTV0iLAogICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlLAogICAgICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFVw"
    "ZGF0ZSBkcml2ZSBiYXJzIGV2ZXJ5IDMwIHNlY29uZHMgKG5vdCBldmVyeSB0aWNrKQogICAgICAgIGlmIG5vdCBoYXNhdHRyKHNl"
    "bGYsICJfZHJpdmVfdGljayIpOgogICAgICAgICAgICBzZWxmLl9kcml2ZV90aWNrID0gMAogICAgICAgIHNlbGYuX2RyaXZlX3Rp"
    "Y2sgKz0gMQogICAgICAgIGlmIHNlbGYuX2RyaXZlX3RpY2sgPj0gMzA6CiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgPSAw"
    "CiAgICAgICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0LnJlZnJlc2goKQoKICAgIGRlZiBzZXRfc3RhdHVzX2xhYmVscyhzZWxmLCBz"
    "dGF0dXM6IHN0ciwgbW9kZWw6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgICAgICBzZXNzaW9uOiBzdHIsIHRva2Vuczogc3Ry"
    "KSAtPiBOb25lOgogICAgICAgIHNlbGYubGJsX3N0YXR1cy5zZXRUZXh0KGYi4pymIFNUQVRVUzoge3N0YXR1c30iKQogICAgICAg"
    "IHNlbGYubGJsX21vZGVsLnNldFRleHQoZiLinKYgVkVTU0VMOiB7bW9kZWx9IikKICAgICAgICBzZWxmLmxibF9zZXNzaW9uLnNl"
    "dFRleHQoZiLinKYgU0VTU0lPTjoge3Nlc3Npb259IikKICAgICAgICBzZWxmLmxibF90b2tlbnMuc2V0VGV4dChmIuKcpiBUT0tF"
    "TlM6IHt0b2tlbnN9IikKCiAgICBkZWYgZ2V0X2RpYWdub3N0aWNzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICByZXR1cm4g"
    "Z2V0YXR0cihzZWxmLCAiX2RpYWdfbWVzc2FnZXMiLCBbXSkKCgojIOKUgOKUgCBQQVNTIDIgQ09NUExFVEUg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiMgQWxsIHdpZGdldCBjbGFzc2VzIGRlZmluZWQuIFN5bnRheC1jaGVja2FibGUgaW5kZXBlbmRl"
    "bnRseS4KIyBOZXh0OiBQYXNzIDMg4oCUIFdvcmtlciBUaHJlYWRzCiMgKERvbHBoaW5Xb3JrZXIgd2l0aCBzdHJlYW1pbmcsIFNl"
    "bnRpbWVudFdvcmtlciwgSWRsZVdvcmtlciwgU291bmRXb3JrZXIpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKA"
    "lCBQQVNTIDM6IFdPUktFUiBUSFJFQURTCiMKIyBXb3JrZXJzIGRlZmluZWQgaGVyZToKIyAgIExMTUFkYXB0b3IgKGJhc2UgKyBM"
    "b2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IgKyBPbGxhbWFBZGFwdG9yICsKIyAgICAgICAgICAgICAgIENsYXVkZUFkYXB0b3IgKyBP"
    "cGVuQUlBZGFwdG9yKQojICAgU3RyZWFtaW5nV29ya2VyICAg4oCUIG1haW4gZ2VuZXJhdGlvbiwgZW1pdHMgdG9rZW5zIG9uZSBh"
    "dCBhIHRpbWUKIyAgIFNlbnRpbWVudFdvcmtlciAgIOKAlCBjbGFzc2lmaWVzIGVtb3Rpb24gZnJvbSByZXNwb25zZSB0ZXh0CiMg"
    "ICBJZGxlV29ya2VyICAgICAgICDigJQgdW5zb2xpY2l0ZWQgdHJhbnNtaXNzaW9ucyBkdXJpbmcgaWRsZQojICAgU291bmRXb3Jr"
    "ZXIgICAgICAg4oCUIHBsYXlzIHNvdW5kcyBvZmYgdGhlIG1haW4gdGhyZWFkCiMKIyBBTEwgZ2VuZXJhdGlvbiBpcyBzdHJlYW1p"
    "bmcuIE5vIGJsb2NraW5nIGNhbGxzIG9uIG1haW4gdGhyZWFkLiBFdmVyLgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0IGFiYwppbXBv"
    "cnQganNvbgppbXBvcnQgdXJsbGliLnJlcXVlc3QKaW1wb3J0IHVybGxpYi5lcnJvcgppbXBvcnQgaHR0cC5jbGllbnQKZnJvbSB0"
    "eXBpbmcgaW1wb3J0IEl0ZXJhdG9yCgoKIyDilIDilIAgTExNIEFEQVBUT1IgQkFTRSDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xh"
    "c3MgTExNQWRhcHRvcihhYmMuQUJDKToKICAgICIiIgogICAgQWJzdHJhY3QgYmFzZSBmb3IgYWxsIG1vZGVsIGJhY2tlbmRzLgog"
    "ICAgVGhlIGRlY2sgY2FsbHMgc3RyZWFtKCkgb3IgZ2VuZXJhdGUoKSDigJQgbmV2ZXIga25vd3Mgd2hpY2ggYmFja2VuZCBpcyBh"
    "Y3RpdmUuCiAgICAiIiIKCiAgICBAYWJjLmFic3RyYWN0bWV0aG9kCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6"
    "CiAgICAgICAgIiIiUmV0dXJuIFRydWUgaWYgdGhlIGJhY2tlbmQgaXMgcmVhY2hhYmxlLiIiIgogICAgICAgIC4uLgoKICAgIEBh"
    "YmMuYWJzdHJhY3RtZXRob2QKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAg"
    "ICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1"
    "MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgIiIiCiAgICAgICAgWWllbGQgcmVzcG9uc2UgdGV4dCB0b2tlbi1i"
    "eS10b2tlbiAob3IgY2h1bmstYnktY2h1bmsgZm9yIEFQSSBiYWNrZW5kcykuCiAgICAgICAgTXVzdCBiZSBhIGdlbmVyYXRvci4g"
    "TmV2ZXIgYmxvY2sgZm9yIHRoZSBmdWxsIHJlc3BvbnNlIGJlZm9yZSB5aWVsZGluZy4KICAgICAgICAiIiIKICAgICAgICAuLi4K"
    "CiAgICBkZWYgZ2VuZXJhdGUoCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwK"
    "ICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IHN0"
    "cjoKICAgICAgICAiIiIKICAgICAgICBDb252ZW5pZW5jZSB3cmFwcGVyOiBjb2xsZWN0IGFsbCBzdHJlYW0gdG9rZW5zIGludG8g"
    "b25lIHN0cmluZy4KICAgICAgICBVc2VkIGZvciBzZW50aW1lbnQgY2xhc3NpZmljYXRpb24gKHNtYWxsIGJvdW5kZWQgY2FsbHMg"
    "b25seSkuCiAgICAgICAgIiIiCiAgICAgICAgcmV0dXJuICIiLmpvaW4oc2VsZi5zdHJlYW0ocHJvbXB0LCBzeXN0ZW0sIGhpc3Rv"
    "cnksIG1heF9uZXdfdG9rZW5zKSkKCiAgICBkZWYgYnVpbGRfY2hhdG1sX3Byb21wdChzZWxmLCBzeXN0ZW06IHN0ciwgaGlzdG9y"
    "eTogbGlzdFtkaWN0XSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICB1c2VyX3RleHQ6IHN0ciA9ICIiKSAtPiBzdHI6CiAg"
    "ICAgICAgIiIiCiAgICAgICAgQnVpbGQgYSBDaGF0TUwtZm9ybWF0IHByb21wdCBzdHJpbmcgZm9yIGxvY2FsIG1vZGVscy4KICAg"
    "ICAgICBoaXN0b3J5ID0gW3sicm9sZSI6ICJ1c2VyInwiYXNzaXN0YW50IiwgImNvbnRlbnQiOiAiLi4uIn1dCiAgICAgICAgIiIi"
    "CiAgICAgICAgcGFydHMgPSBbZiI8fGltX3N0YXJ0fD5zeXN0ZW1cbntzeXN0ZW19PHxpbV9lbmR8PiJdCiAgICAgICAgZm9yIG1z"
    "ZyBpbiBoaXN0b3J5OgogICAgICAgICAgICByb2xlICAgID0gbXNnLmdldCgicm9sZSIsICJ1c2VyIikKICAgICAgICAgICAgY29u"
    "dGVudCA9IG1zZy5nZXQoImNvbnRlbnQiLCAiIikKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGYiPHxpbV9zdGFydHw+e3JvbGV9"
    "XG57Y29udGVudH08fGltX2VuZHw+IikKICAgICAgICBpZiB1c2VyX3RleHQ6CiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChmIjx8"
    "aW1fc3RhcnR8PnVzZXJcbnt1c2VyX3RleHR9PHxpbV9lbmR8PiIpCiAgICAgICAgcGFydHMuYXBwZW5kKCI8fGltX3N0YXJ0fD5h"
    "c3Npc3RhbnRcbiIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCgojIOKUgOKUgCBMT0NBTCBUUkFOU0ZPUk1FUlMg"
    "QURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKY2xhc3MgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBMb2FkcyBhIEh1Z2dpbmdG"
    "YWNlIG1vZGVsIGZyb20gYSBsb2NhbCBmb2xkZXIuCiAgICBTdHJlYW1pbmc6IHVzZXMgbW9kZWwuZ2VuZXJhdGUoKSB3aXRoIGEg"
    "Y3VzdG9tIHN0cmVhbWVyIHRoYXQgeWllbGRzIHRva2Vucy4KICAgIFJlcXVpcmVzOiB0b3JjaCwgdHJhbnNmb3JtZXJzCiAgICAi"
    "IiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbW9kZWxfcGF0aDogc3RyKToKICAgICAgICBzZWxmLl9wYXRoICAgICAgPSBtb2Rl"
    "bF9wYXRoCiAgICAgICAgc2VsZi5fbW9kZWwgICAgID0gTm9uZQogICAgICAgIHNlbGYuX3Rva2VuaXplciA9IE5vbmUKICAgICAg"
    "ICBzZWxmLl9sb2FkZWQgICAgPSBGYWxzZQogICAgICAgIHNlbGYuX2Vycm9yICAgICA9ICIiCgogICAgZGVmIGxvYWQoc2VsZikg"
    "LT4gYm9vbDoKICAgICAgICAiIiIKICAgICAgICBMb2FkIG1vZGVsIGFuZCB0b2tlbml6ZXIuIENhbGwgZnJvbSBhIGJhY2tncm91"
    "bmQgdGhyZWFkLgogICAgICAgIFJldHVybnMgVHJ1ZSBvbiBzdWNjZXNzLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBUT1JD"
    "SF9PSzoKICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSAidG9yY2gvdHJhbnNmb3JtZXJzIG5vdCBpbnN0YWxsZWQiCiAgICAgICAg"
    "ICAgIHJldHVybiBGYWxzZQogICAgICAgIHRyeToKICAgICAgICAgICAgZnJvbSB0cmFuc2Zvcm1lcnMgaW1wb3J0IEF1dG9Nb2Rl"
    "bEZvckNhdXNhbExNLCBBdXRvVG9rZW5pemVyCiAgICAgICAgICAgIHNlbGYuX3Rva2VuaXplciA9IEF1dG9Ub2tlbml6ZXIuZnJv"
    "bV9wcmV0cmFpbmVkKHNlbGYuX3BhdGgpCiAgICAgICAgICAgIHNlbGYuX21vZGVsID0gQXV0b01vZGVsRm9yQ2F1c2FsTE0uZnJv"
    "bV9wcmV0cmFpbmVkKAogICAgICAgICAgICAgICAgc2VsZi5fcGF0aCwKICAgICAgICAgICAgICAgIHRvcmNoX2R0eXBlPXRvcmNo"
    "LmZsb2F0MTYsCiAgICAgICAgICAgICAgICBkZXZpY2VfbWFwPSJhdXRvIiwKICAgICAgICAgICAgICAgIGxvd19jcHVfbWVtX3Vz"
    "YWdlPVRydWUsCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fbG9hZGVkID0gVHJ1ZQogICAgICAgICAgICByZXR1cm4g"
    "VHJ1ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSBzdHIoZSkKICAgICAg"
    "ICAgICAgcmV0dXJuIEZhbHNlCgogICAgQHByb3BlcnR5CiAgICBkZWYgZXJyb3Ioc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVy"
    "biBzZWxmLl9lcnJvcgoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fbG9h"
    "ZGVkCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3Ry"
    "LAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4g"
    "SXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAgICBTdHJlYW1zIHRva2VucyB1c2luZyB0cmFuc2Zvcm1lcnMgVGV4dEl0"
    "ZXJhdG9yU3RyZWFtZXIuCiAgICAgICAgWWllbGRzIGRlY29kZWQgdGV4dCBmcmFnbWVudHMgYXMgdGhleSBhcmUgZ2VuZXJhdGVk"
    "LgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBzZWxmLl9sb2FkZWQ6CiAgICAgICAgICAgIHlpZWxkICJbRVJST1I6IG1vZGVs"
    "IG5vdCBsb2FkZWRdIgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBmcm9tIHRyYW5zZm9ybWVy"
    "cyBpbXBvcnQgVGV4dEl0ZXJhdG9yU3RyZWFtZXIKCiAgICAgICAgICAgIGZ1bGxfcHJvbXB0ID0gc2VsZi5idWlsZF9jaGF0bWxf"
    "cHJvbXB0KHN5c3RlbSwgaGlzdG9yeSkKICAgICAgICAgICAgaWYgcHJvbXB0OgogICAgICAgICAgICAgICAgIyBwcm9tcHQgYWxy"
    "ZWFkeSBpbmNsdWRlcyB1c2VyIHR1cm4gaWYgY2FsbGVyIGJ1aWx0IGl0CiAgICAgICAgICAgICAgICBmdWxsX3Byb21wdCA9IHBy"
    "b21wdAoKICAgICAgICAgICAgaW5wdXRfaWRzID0gc2VsZi5fdG9rZW5pemVyKAogICAgICAgICAgICAgICAgZnVsbF9wcm9tcHQs"
    "IHJldHVybl90ZW5zb3JzPSJwdCIKICAgICAgICAgICAgKS5pbnB1dF9pZHMudG8oImN1ZGEiKQoKICAgICAgICAgICAgYXR0ZW50"
    "aW9uX21hc2sgPSAoaW5wdXRfaWRzICE9IHNlbGYuX3Rva2VuaXplci5wYWRfdG9rZW5faWQpLmxvbmcoKQoKICAgICAgICAgICAg"
    "c3RyZWFtZXIgPSBUZXh0SXRlcmF0b3JTdHJlYW1lcigKICAgICAgICAgICAgICAgIHNlbGYuX3Rva2VuaXplciwKICAgICAgICAg"
    "ICAgICAgIHNraXBfcHJvbXB0PVRydWUsCiAgICAgICAgICAgICAgICBza2lwX3NwZWNpYWxfdG9rZW5zPVRydWUsCiAgICAgICAg"
    "ICAgICkKCiAgICAgICAgICAgIGdlbl9rd2FyZ3MgPSB7CiAgICAgICAgICAgICAgICAiaW5wdXRfaWRzIjogICAgICBpbnB1dF9p"
    "ZHMsCiAgICAgICAgICAgICAgICAiYXR0ZW50aW9uX21hc2siOiBhdHRlbnRpb25fbWFzaywKICAgICAgICAgICAgICAgICJtYXhf"
    "bmV3X3Rva2VucyI6IG1heF9uZXdfdG9rZW5zLAogICAgICAgICAgICAgICAgInRlbXBlcmF0dXJlIjogICAgMC43LAogICAgICAg"
    "ICAgICAgICAgImRvX3NhbXBsZSI6ICAgICAgVHJ1ZSwKICAgICAgICAgICAgICAgICJwYWRfdG9rZW5faWQiOiAgIHNlbGYuX3Rv"
    "a2VuaXplci5lb3NfdG9rZW5faWQsCiAgICAgICAgICAgICAgICAic3RyZWFtZXIiOiAgICAgICBzdHJlYW1lciwKICAgICAgICAg"
    "ICAgfQoKICAgICAgICAgICAgIyBSdW4gZ2VuZXJhdGlvbiBpbiBhIGRhZW1vbiB0aHJlYWQg4oCUIHN0cmVhbWVyIHlpZWxkcyBo"
    "ZXJlCiAgICAgICAgICAgIGdlbl90aHJlYWQgPSB0aHJlYWRpbmcuVGhyZWFkKAogICAgICAgICAgICAgICAgdGFyZ2V0PXNlbGYu"
    "X21vZGVsLmdlbmVyYXRlLAogICAgICAgICAgICAgICAga3dhcmdzPWdlbl9rd2FyZ3MsCiAgICAgICAgICAgICAgICBkYWVtb249"
    "VHJ1ZSwKICAgICAgICAgICAgKQogICAgICAgICAgICBnZW5fdGhyZWFkLnN0YXJ0KCkKCiAgICAgICAgICAgIGZvciB0b2tlbl90"
    "ZXh0IGluIHN0cmVhbWVyOgogICAgICAgICAgICAgICAgeWllbGQgdG9rZW5fdGV4dAoKICAgICAgICAgICAgZ2VuX3RocmVhZC5q"
    "b2luKHRpbWVvdXQ9MTIwKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJS"
    "T1I6IHtlfV0iCgoKIyDilIDilIAgT0xMQU1BIEFEQVBUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE9s"
    "bGFtYUFkYXB0b3IoTExNQWRhcHRvcik6CiAgICAiIiIKICAgIENvbm5lY3RzIHRvIGEgbG9jYWxseSBydW5uaW5nIE9sbGFtYSBp"
    "bnN0YW5jZS4KICAgIFN0cmVhbWluZzogcmVhZHMgTkRKU09OIHJlc3BvbnNlIGNodW5rcyBmcm9tIE9sbGFtYSdzIC9hcGkvZ2Vu"
    "ZXJhdGUgZW5kcG9pbnQuCiAgICBPbGxhbWEgbXVzdCBiZSBydW5uaW5nIGFzIGEgc2VydmljZSBvbiBsb2NhbGhvc3Q6MTE0MzQu"
    "CiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbW9kZWxfbmFtZTogc3RyLCBob3N0OiBzdHIgPSAibG9jYWxob3N0Iiwg"
    "cG9ydDogaW50ID0gMTE0MzQpOgogICAgICAgIHNlbGYuX21vZGVsID0gbW9kZWxfbmFtZQogICAgICAgIHNlbGYuX2Jhc2UgID0g"
    "ZiJodHRwOi8ve2hvc3R9Ontwb3J0fSIKCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICByZXEgID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdChmIntzZWxmLl9iYXNlfS9hcGkvdGFncyIpCiAgICAgICAg"
    "ICAgIHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0zKQogICAgICAgICAgICByZXR1cm4gcmVzcC5z"
    "dGF0dXMgPT0gMjAwCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgZGVmIHN0"
    "cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rv"
    "cnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToK"
    "ICAgICAgICAiIiIKICAgICAgICBQb3N0cyB0byAvYXBpL2NoYXQgd2l0aCBzdHJlYW09VHJ1ZS4KICAgICAgICBPbGxhbWEgcmV0"
    "dXJucyBOREpTT04g4oCUIG9uZSBKU09OIG9iamVjdCBwZXIgbGluZS4KICAgICAgICBZaWVsZHMgdGhlICdjb250ZW50JyBmaWVs"
    "ZCBvZiBlYWNoIGFzc2lzdGFudCBtZXNzYWdlIGNodW5rLgogICAgICAgICIiIgogICAgICAgIG1lc3NhZ2VzID0gW3sicm9sZSI6"
    "ICJzeXN0ZW0iLCAiY29udGVudCI6IHN5c3RlbX1dCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNz"
    "YWdlcy5hcHBlbmQobXNnKQoKICAgICAgICBwYXlsb2FkID0ganNvbi5kdW1wcyh7CiAgICAgICAgICAgICJtb2RlbCI6ICAgIHNl"
    "bGYuX21vZGVsLAogICAgICAgICAgICAibWVzc2FnZXMiOiBtZXNzYWdlcywKICAgICAgICAgICAgInN0cmVhbSI6ICAgVHJ1ZSwK"
    "ICAgICAgICAgICAgIm9wdGlvbnMiOiAgeyJudW1fcHJlZGljdCI6IG1heF9uZXdfdG9rZW5zLCAidGVtcGVyYXR1cmUiOiAwLjd9"
    "LAogICAgICAgIH0pLmVuY29kZSgidXRmLTgiKQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJlcSA9IHVybGxpYi5yZXF1ZXN0"
    "LlJlcXVlc3QoCiAgICAgICAgICAgICAgICBmIntzZWxmLl9iYXNlfS9hcGkvY2hhdCIsCiAgICAgICAgICAgICAgICBkYXRhPXBh"
    "eWxvYWQsCiAgICAgICAgICAgICAgICBoZWFkZXJzPXsiQ29udGVudC1UeXBlIjogImFwcGxpY2F0aW9uL2pzb24ifSwKICAgICAg"
    "ICAgICAgICAgIG1ldGhvZD0iUE9TVCIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgd2l0aCB1cmxsaWIucmVxdWVzdC51cmxv"
    "cGVuKHJlcSwgdGltZW91dD0xMjApIGFzIHJlc3A6CiAgICAgICAgICAgICAgICBmb3IgcmF3X2xpbmUgaW4gcmVzcDoKICAgICAg"
    "ICAgICAgICAgICAgICBsaW5lID0gcmF3X2xpbmUuZGVjb2RlKCJ1dGYtOCIpLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBp"
    "ZiBub3QgbGluZToKICAgICAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMobGluZSkKICAgICAgICAgICAgICAgICAgICAgICAgY2h1bmsgPSBv"
    "YmouZ2V0KCJtZXNzYWdlIiwge30pLmdldCgiY29udGVudCIsICIiKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBjaHVuazoK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIHlpZWxkIGNodW5rCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIG9iai5nZXQo"
    "ImRvbmUiLCBGYWxzZSk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgICAgIGV4Y2Vw"
    "dCBqc29uLkpTT05EZWNvZGVFcnJvcjoKICAgICAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9sbGFtYSDigJQge2V9XSIKCgojIOKUgOKUgCBDTEFV"
    "REUgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgQ2xhdWRlQWRhcHRvcihMTE1BZGFwdG9yKToK"
    "ICAgICIiIgogICAgU3RyZWFtcyBmcm9tIEFudGhyb3BpYydzIENsYXVkZSBBUEkgdXNpbmcgU1NFIChzZXJ2ZXItc2VudCBldmVu"
    "dHMpLgogICAgUmVxdWlyZXMgYW4gQVBJIGtleSBpbiBjb25maWcuCiAgICAiIiIKCiAgICBfQVBJX1VSTCA9ICJhcGkuYW50aHJv"
    "cGljLmNvbSIKICAgIF9QQVRIICAgID0gIi92MS9tZXNzYWdlcyIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3Ry"
    "LCBtb2RlbDogc3RyID0gImNsYXVkZS1zb25uZXQtNC02Iik6CiAgICAgICAgc2VsZi5fa2V5ICAgPSBhcGlfa2V5CiAgICAgICAg"
    "c2VsZi5fbW9kZWwgPSBtb2RlbAoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gYm9v"
    "bChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5"
    "c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwK"
    "ICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNzYWdlcyA9IFtdCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5Ogog"
    "ICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoewogICAgICAgICAgICAgICAgInJvbGUiOiAgICBtc2dbInJvbGUiXSwKICAgICAg"
    "ICAgICAgICAgICJjb250ZW50IjogbXNnWyJjb250ZW50Il0sCiAgICAgICAgICAgIH0pCgogICAgICAgIHBheWxvYWQgPSBqc29u"
    "LmR1bXBzKHsKICAgICAgICAgICAgIm1vZGVsIjogICAgICBzZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1heF90b2tlbnMiOiBt"
    "YXhfbmV3X3Rva2VucywKICAgICAgICAgICAgInN5c3RlbSI6ICAgICBzeXN0ZW0sCiAgICAgICAgICAgICJtZXNzYWdlcyI6ICAg"
    "bWVzc2FnZXMsCiAgICAgICAgICAgICJzdHJlYW0iOiAgICAgVHJ1ZSwKICAgICAgICB9KS5lbmNvZGUoInV0Zi04IikKCiAgICAg"
    "ICAgaGVhZGVycyA9IHsKICAgICAgICAgICAgIngtYXBpLWtleSI6ICAgICAgICAgc2VsZi5fa2V5LAogICAgICAgICAgICAiYW50"
    "aHJvcGljLXZlcnNpb24iOiAiMjAyMy0wNi0wMSIsCiAgICAgICAgICAgICJjb250ZW50LXR5cGUiOiAgICAgICJhcHBsaWNhdGlv"
    "bi9qc29uIiwKICAgICAgICB9CgogICAgICAgIHRyeToKICAgICAgICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVj"
    "dGlvbihzZWxmLl9BUElfVVJMLCB0aW1lb3V0PTEyMCkKICAgICAgICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwgc2VsZi5fUEFU"
    "SCwgYm9keT1wYXlsb2FkLCBoZWFkZXJzPWhlYWRlcnMpCiAgICAgICAgICAgIHJlc3AgPSBjb25uLmdldHJlc3BvbnNlKCkKCiAg"
    "ICAgICAgICAgIGlmIHJlc3Auc3RhdHVzICE9IDIwMDoKICAgICAgICAgICAgICAgIGJvZHkgPSByZXNwLnJlYWQoKS5kZWNvZGUo"
    "InV0Zi04IikKICAgICAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IENsYXVkZSBBUEkge3Jlc3Auc3RhdHVzfSDigJQge2Jv"
    "ZHlbOjIwMF19XSIKICAgICAgICAgICAgICAgIHJldHVybgoKICAgICAgICAgICAgYnVmZmVyID0gIiIKICAgICAgICAgICAgd2hp"
    "bGUgVHJ1ZToKICAgICAgICAgICAgICAgIGNodW5rID0gcmVzcC5yZWFkKDI1NikKICAgICAgICAgICAgICAgIGlmIG5vdCBjaHVu"
    "azoKICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgYnVmZmVyICs9IGNodW5rLmRlY29kZSgidXRmLTgi"
    "KQogICAgICAgICAgICAgICAgd2hpbGUgIlxuIiBpbiBidWZmZXI6CiAgICAgICAgICAgICAgICAgICAgbGluZSwgYnVmZmVyID0g"
    "YnVmZmVyLnNwbGl0KCJcbiIsIDEpCiAgICAgICAgICAgICAgICAgICAgbGluZSA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAg"
    "ICAgICAgIGlmIGxpbmUuc3RhcnRzd2l0aCgiZGF0YToiKToKICAgICAgICAgICAgICAgICAgICAgICAgZGF0YV9zdHIgPSBsaW5l"
    "WzU6XS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIGRhdGFfc3RyID09ICJbRE9ORV0iOgogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIG9iaiA9IGpzb24ubG9hZHMoZGF0YV9zdHIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBvYmouZ2V0KCJ0eXBl"
    "IikgPT0gImNvbnRlbnRfYmxvY2tfZGVsdGEiOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRleHQgPSBvYmouZ2V0"
    "KCJkZWx0YSIsIHt9KS5nZXQoInRleHQiLCAiIikKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiB0ZXh0OgogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB5aWVsZCB0ZXh0CiAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBq"
    "c29uLkpTT05EZWNvZGVFcnJvcjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0"
    "aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IENsYXVkZSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5Ogog"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjb25uLmNsb3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoK"
    "ICAgICAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBPUEVOQUkgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKY2xhc3MgT3BlbkFJQWRhcHRvcihMTE1BZGFwdG9yKToKICAgICIiIgogICAgU3RyZWFtcyBmcm9tIE9wZW5BSSdzIGNoYXQg"
    "Y29tcGxldGlvbnMgQVBJLgogICAgU2FtZSBTU0UgcGF0dGVybiBhcyBDbGF1ZGUuIENvbXBhdGlibGUgd2l0aCBhbnkgT3BlbkFJ"
    "LWNvbXBhdGlibGUgZW5kcG9pbnQuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2RlbDog"
    "c3RyID0gImdwdC00byIsCiAgICAgICAgICAgICAgICAgaG9zdDogc3RyID0gImFwaS5vcGVuYWkuY29tIik6CiAgICAgICAgc2Vs"
    "Zi5fa2V5ICAgPSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbAogICAgICAgIHNlbGYuX2hvc3QgID0gaG9zdAoK"
    "ICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVm"
    "IHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhp"
    "c3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3Ry"
    "XToKICAgICAgICBtZXNzYWdlcyA9IFt7InJvbGUiOiAic3lzdGVtIiwgImNvbnRlbnQiOiBzeXN0ZW19XQogICAgICAgIGZvciBt"
    "c2cgaW4gaGlzdG9yeToKICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKHsicm9sZSI6IG1zZ1sicm9sZSJdLCAiY29udGVudCI6"
    "IG1zZ1siY29udGVudCJdfSkKCiAgICAgICAgcGF5bG9hZCA9IGpzb24uZHVtcHMoewogICAgICAgICAgICAibW9kZWwiOiAgICAg"
    "ICBzZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1lc3NhZ2VzIjogICAgbWVzc2FnZXMsCiAgICAgICAgICAgICJtYXhfdG9rZW5z"
    "IjogIG1heF9uZXdfdG9rZW5zLAogICAgICAgICAgICAidGVtcGVyYXR1cmUiOiAwLjcsCiAgICAgICAgICAgICJzdHJlYW0iOiAg"
    "ICAgIFRydWUsCiAgICAgICAgfSkuZW5jb2RlKCJ1dGYtOCIpCgogICAgICAgIGhlYWRlcnMgPSB7CiAgICAgICAgICAgICJBdXRo"
    "b3JpemF0aW9uIjogZiJCZWFyZXIge3NlbGYuX2tleX0iLAogICAgICAgICAgICAiQ29udGVudC1UeXBlIjogICJhcHBsaWNhdGlv"
    "bi9qc29uIiwKICAgICAgICB9CgogICAgICAgIHRyeToKICAgICAgICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVj"
    "dGlvbihzZWxmLl9ob3N0LCB0aW1lb3V0PTEyMCkKICAgICAgICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwgIi92MS9jaGF0L2Nv"
    "bXBsZXRpb25zIiwKICAgICAgICAgICAgICAgICAgICAgICAgIGJvZHk9cGF5bG9hZCwgaGVhZGVycz1oZWFkZXJzKQogICAgICAg"
    "ICAgICByZXNwID0gY29ubi5nZXRyZXNwb25zZSgpCgogICAgICAgICAgICBpZiByZXNwLnN0YXR1cyAhPSAyMDA6CiAgICAgICAg"
    "ICAgICAgICBib2R5ID0gcmVzcC5yZWFkKCkuZGVjb2RlKCJ1dGYtOCIpCiAgICAgICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9S"
    "OiBPcGVuQUkgQVBJIHtyZXNwLnN0YXR1c30g4oCUIHtib2R5WzoyMDBdfV0iCiAgICAgICAgICAgICAgICByZXR1cm4KCiAgICAg"
    "ICAgICAgIGJ1ZmZlciA9ICIiCiAgICAgICAgICAgIHdoaWxlIFRydWU6CiAgICAgICAgICAgICAgICBjaHVuayA9IHJlc3AucmVh"
    "ZCgyNTYpCiAgICAgICAgICAgICAgICBpZiBub3QgY2h1bms6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAg"
    "ICAgIGJ1ZmZlciArPSBjaHVuay5kZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHdoaWxlICJcbiIgaW4gYnVmZmVyOgog"
    "ICAgICAgICAgICAgICAgICAgIGxpbmUsIGJ1ZmZlciA9IGJ1ZmZlci5zcGxpdCgiXG4iLCAxKQogICAgICAgICAgICAgICAgICAg"
    "IGxpbmUgPSBsaW5lLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBsaW5lLnN0YXJ0c3dpdGgoImRhdGE6Iik6CiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGRhdGFfc3RyID0gbGluZVs1Ol0uc3RyaXAoKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBk"
    "YXRhX3N0ciA9PSAiW0RPTkVdIjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgICAgICAgICAgICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBvYmogPSBqc29uLmxvYWRzKGRhdGFfc3RyKQogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgdGV4dCA9IChvYmouZ2V0KCJjaG9pY2VzIiwgW3t9XSlbMF0KICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgLmdldCgiZGVsdGEiLCB7fSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "LmdldCgiY29udGVudCIsICIiKSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHRleHQ6CiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgeWllbGQgdGV4dAogICAgICAgICAgICAgICAgICAgICAgICBleGNlcHQgKGpzb24uSlNPTkRlY29kZUVy"
    "cm9yLCBJbmRleEVycm9yKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "IGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9wZW5BSSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAg"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjb25uLmNsb3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAg"
    "ICAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBBREFQVE9SIEZBQ1RPUlkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRl"
    "ZiBidWlsZF9hZGFwdG9yX2Zyb21fY29uZmlnKCkgLT4gTExNQWRhcHRvcjoKICAgICIiIgogICAgQnVpbGQgdGhlIGNvcnJlY3Qg"
    "TExNQWRhcHRvciBmcm9tIENGR1snbW9kZWwnXS4KICAgIENhbGxlZCBvbmNlIG9uIHN0YXJ0dXAgYnkgdGhlIG1vZGVsIGxvYWRl"
    "ciB0aHJlYWQuCiAgICAiIiIKICAgIG0gPSBDRkcuZ2V0KCJtb2RlbCIsIHt9KQogICAgdCA9IG0uZ2V0KCJ0eXBlIiwgImxvY2Fs"
    "IikKCiAgICBpZiB0ID09ICJvbGxhbWEiOgogICAgICAgIHJldHVybiBPbGxhbWFBZGFwdG9yKAogICAgICAgICAgICBtb2RlbF9u"
    "YW1lPW0uZ2V0KCJvbGxhbWFfbW9kZWwiLCAiZG9scGhpbi0yLjYtN2IiKQogICAgICAgICkKICAgIGVsaWYgdCA9PSAiY2xhdWRl"
    "IjoKICAgICAgICByZXR1cm4gQ2xhdWRlQWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBpX2tleSIsICIiKSwK"
    "ICAgICAgICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2RlbCIsICJjbGF1ZGUtc29ubmV0LTQtNiIpLAogICAgICAgICkKICAgIGVs"
    "aWYgdCA9PSAib3BlbmFpIjoKICAgICAgICByZXR1cm4gT3BlbkFJQWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdldCgi"
    "YXBpX2tleSIsICIiKSwKICAgICAgICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2RlbCIsICJncHQtNG8iKSwKICAgICAgICApCiAg"
    "ICBlbHNlOgogICAgICAgICMgRGVmYXVsdDogbG9jYWwgdHJhbnNmb3JtZXJzCiAgICAgICAgcmV0dXJuIExvY2FsVHJhbnNmb3Jt"
    "ZXJzQWRhcHRvcihtb2RlbF9wYXRoPW0uZ2V0KCJwYXRoIiwgIiIpKQoKCiMg4pSA4pSAIFNUUkVBTUlORyBXT1JLRVIg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFN0cmVhbWluZ1dvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgTWFpbiBnZW5lcmF0"
    "aW9uIHdvcmtlci4gU3RyZWFtcyB0b2tlbnMgb25lIGJ5IG9uZSB0byB0aGUgVUkuCgogICAgU2lnbmFsczoKICAgICAgICB0b2tl"
    "bl9yZWFkeShzdHIpICAgICAg4oCUIGVtaXR0ZWQgZm9yIGVhY2ggdG9rZW4vY2h1bmsgYXMgZ2VuZXJhdGVkCiAgICAgICAgcmVz"
    "cG9uc2VfZG9uZShzdHIpICAgIOKAlCBlbWl0dGVkIHdpdGggdGhlIGZ1bGwgYXNzZW1ibGVkIHJlc3BvbnNlCiAgICAgICAgZXJy"
    "b3Jfb2NjdXJyZWQoc3RyKSAgIOKAlCBlbWl0dGVkIG9uIGV4Y2VwdGlvbgogICAgICAgIHN0YXR1c19jaGFuZ2VkKHN0cikgICDi"
    "gJQgZW1pdHRlZCB3aXRoIHN0YXR1cyBzdHJpbmcgKEdFTkVSQVRJTkcgLyBJRExFIC8gRVJST1IpCiAgICAiIiIKCiAgICB0b2tl"
    "bl9yZWFkeSAgICA9IFNpZ25hbChzdHIpCiAgICByZXNwb25zZV9kb25lICA9IFNpZ25hbChzdHIpCiAgICBlcnJvcl9vY2N1cnJl"
    "ZCA9IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdlZCA9IFNpZ25hbChzdHIpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFk"
    "YXB0b3I6IExMTUFkYXB0b3IsIHN5c3RlbTogc3RyLAogICAgICAgICAgICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sIG1heF90"
    "b2tlbnM6IGludCA9IDUxMik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgICA9IGFk"
    "YXB0b3IKICAgICAgICBzZWxmLl9zeXN0ZW0gICAgID0gc3lzdGVtCiAgICAgICAgc2VsZi5faGlzdG9yeSAgICA9IGxpc3QoaGlz"
    "dG9yeSkgICAjIGNvcHkg4oCUIHRocmVhZCBzYWZlCiAgICAgICAgc2VsZi5fbWF4X3Rva2VucyA9IG1heF90b2tlbnMKICAgICAg"
    "ICBzZWxmLl9jYW5jZWxsZWQgID0gRmFsc2UKCiAgICBkZWYgY2FuY2VsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiUmVxdWVz"
    "dCBjYW5jZWxsYXRpb24uIEdlbmVyYXRpb24gbWF5IG5vdCBzdG9wIGltbWVkaWF0ZWx5LiIiIgogICAgICAgIHNlbGYuX2NhbmNl"
    "bGxlZCA9IFRydWUKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJH"
    "RU5FUkFUSU5HIikKICAgICAgICBhc3NlbWJsZWQgPSBbXQogICAgICAgIHRyeToKICAgICAgICAgICAgZm9yIGNodW5rIGluIHNl"
    "bGYuX2FkYXB0b3Iuc3RyZWFtKAogICAgICAgICAgICAgICAgcHJvbXB0PSIiLAogICAgICAgICAgICAgICAgc3lzdGVtPXNlbGYu"
    "X3N5c3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAgICAgIG1heF9uZXdfdG9r"
    "ZW5zPXNlbGYuX21heF90b2tlbnMsCiAgICAgICAgICAgICk6CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9jYW5jZWxsZWQ6CiAg"
    "ICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgICAgIGFzc2VtYmxlZC5hcHBlbmQoY2h1bmspCiAgICAgICAgICAg"
    "ICAgICBzZWxmLnRva2VuX3JlYWR5LmVtaXQoY2h1bmspCgogICAgICAgICAgICBmdWxsX3Jlc3BvbnNlID0gIiIuam9pbihhc3Nl"
    "bWJsZWQpLnN0cmlwKCkKICAgICAgICAgICAgc2VsZi5yZXNwb25zZV9kb25lLmVtaXQoZnVsbF9yZXNwb25zZSkKICAgICAgICAg"
    "ICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJJRExFIikKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAg"
    "ICAgICBzZWxmLmVycm9yX29jY3VycmVkLmVtaXQoc3RyKGUpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQo"
    "IkVSUk9SIikKCgojIOKUgOKUgCBTRU5USU1FTlQgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTZW50aW1l"
    "bnRXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIENsYXNzaWZpZXMgdGhlIGVtb3Rpb25hbCB0b25lIG9mIHRoZSBwZXJzb25h"
    "J3MgbGFzdCByZXNwb25zZS4KICAgIEZpcmVzIDUgc2Vjb25kcyBhZnRlciByZXNwb25zZV9kb25lLgoKICAgIFVzZXMgYSB0aW55"
    "IGJvdW5kZWQgcHJvbXB0ICh+NSB0b2tlbnMgb3V0cHV0KSB0byBkZXRlcm1pbmUgd2hpY2gKICAgIGZhY2UgdG8gZGlzcGxheS4g"
    "UmV0dXJucyBvbmUgd29yZCBmcm9tIFNFTlRJTUVOVF9MSVNULgoKICAgIEZhY2Ugc3RheXMgZGlzcGxheWVkIGZvciA2MCBzZWNv"
    "bmRzIGJlZm9yZSByZXR1cm5pbmcgdG8gbmV1dHJhbC4KICAgIElmIGEgbmV3IG1lc3NhZ2UgYXJyaXZlcyBkdXJpbmcgdGhhdCB3"
    "aW5kb3csIGZhY2UgdXBkYXRlcyBpbW1lZGlhdGVseQogICAgdG8gJ2FsZXJ0JyDigJQgNjBzIGlzIGlkbGUtb25seSwgbmV2ZXIg"
    "YmxvY2tzIHJlc3BvbnNpdmVuZXNzLgoKICAgIFNpZ25hbDoKICAgICAgICBmYWNlX3JlYWR5KHN0cikgIOKAlCBlbW90aW9uIG5h"
    "bWUgZnJvbSBTRU5USU1FTlRfTElTVAogICAgIiIiCgogICAgZmFjZV9yZWFkeSA9IFNpZ25hbChzdHIpCgogICAgIyBFbW90aW9u"
    "cyB0aGUgY2xhc3NpZmllciBjYW4gcmV0dXJuIOKAlCBtdXN0IG1hdGNoIEZBQ0VfRklMRVMga2V5cwogICAgVkFMSURfRU1PVElP"
    "TlMgPSBzZXQoRkFDRV9GSUxFUy5rZXlzKCkpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0b3IsIHJl"
    "c3BvbnNlX3RleHQ6IHN0cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgPSBhZGFw"
    "dG9yCiAgICAgICAgc2VsZi5fcmVzcG9uc2UgPSByZXNwb25zZV90ZXh0Wzo0MDBdICAjIGxpbWl0IGNvbnRleHQKCiAgICBkZWYg"
    "cnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBjbGFzc2lmeV9wcm9tcHQgPSAoCiAgICAgICAgICAg"
    "ICAgICBmIkNsYXNzaWZ5IHRoZSBlbW90aW9uYWwgdG9uZSBvZiB0aGlzIHRleHQgd2l0aCBleGFjdGx5ICIKICAgICAgICAgICAg"
    "ICAgIGYib25lIHdvcmQgZnJvbSB0aGlzIGxpc3Q6IHtTRU5USU1FTlRfTElTVH0uXG5cbiIKICAgICAgICAgICAgICAgIGYiVGV4"
    "dDoge3NlbGYuX3Jlc3BvbnNlfVxuXG4iCiAgICAgICAgICAgICAgICBmIlJlcGx5IHdpdGggb25lIHdvcmQgb25seToiCiAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgIyBVc2UgYSBtaW5pbWFsIGhpc3RvcnkgYW5kIGEgbmV1dHJhbCBzeXN0ZW0gcHJvbXB0CiAg"
    "ICAgICAgICAgICMgdG8gYXZvaWQgcGVyc29uYSBibGVlZGluZyBpbnRvIHRoZSBjbGFzc2lmaWNhdGlvbgogICAgICAgICAgICBz"
    "eXN0ZW0gPSAoCiAgICAgICAgICAgICAgICAiWW91IGFyZSBhbiBlbW90aW9uIGNsYXNzaWZpZXIuICIKICAgICAgICAgICAgICAg"
    "ICJSZXBseSB3aXRoIGV4YWN0bHkgb25lIHdvcmQgZnJvbSB0aGUgcHJvdmlkZWQgbGlzdC4gIgogICAgICAgICAgICAgICAgIk5v"
    "IHB1bmN0dWF0aW9uLiBObyBleHBsYW5hdGlvbi4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmF3ID0gc2VsZi5fYWRhcHRv"
    "ci5nZW5lcmF0ZSgKICAgICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1zeXN0ZW0sCiAgICAg"
    "ICAgICAgICAgICBoaXN0b3J5PVt7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogY2xhc3NpZnlfcHJvbXB0fV0sCiAgICAgICAg"
    "ICAgICAgICBtYXhfbmV3X3Rva2Vucz02LAogICAgICAgICAgICApCiAgICAgICAgICAgICMgRXh0cmFjdCBmaXJzdCB3b3JkLCBj"
    "bGVhbiBpdCB1cAogICAgICAgICAgICB3b3JkID0gcmF3LnN0cmlwKCkubG93ZXIoKS5zcGxpdCgpWzBdIGlmIHJhdy5zdHJpcCgp"
    "IGVsc2UgIm5ldXRyYWwiCiAgICAgICAgICAgICMgU3RyaXAgYW55IHB1bmN0dWF0aW9uCiAgICAgICAgICAgIHdvcmQgPSAiIi5q"
    "b2luKGMgZm9yIGMgaW4gd29yZCBpZiBjLmlzYWxwaGEoKSkKICAgICAgICAgICAgcmVzdWx0ID0gd29yZCBpZiB3b3JkIGluIHNl"
    "bGYuVkFMSURfRU1PVElPTlMgZWxzZSAibmV1dHJhbCIKICAgICAgICAgICAgc2VsZi5mYWNlX3JlYWR5LmVtaXQocmVzdWx0KQoK"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBzZWxmLmZhY2VfcmVhZHkuZW1pdCgibmV1dHJhbCIpCgoKIyDi"
    "lIDilIAgSURMRSBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIElkbGVXb3JrZXIo"
    "UVRocmVhZCk6CiAgICAiIiIKICAgIEdlbmVyYXRlcyBhbiB1bnNvbGljaXRlZCB0cmFuc21pc3Npb24gZHVyaW5nIGlkbGUgcGVy"
    "aW9kcy4KICAgIE9ubHkgZmlyZXMgd2hlbiBpZGxlIGlzIGVuYWJsZWQgQU5EIHRoZSBkZWNrIGlzIGluIElETEUgc3RhdHVzLgoK"
    "ICAgIFRocmVlIHJvdGF0aW5nIG1vZGVzIChzZXQgYnkgcGFyZW50KToKICAgICAgREVFUEVOSU5HICDigJQgY29udGludWVzIGN1"
    "cnJlbnQgaW50ZXJuYWwgdGhvdWdodCB0aHJlYWQKICAgICAgQlJBTkNISU5HICDigJQgZmluZHMgYWRqYWNlbnQgdG9waWMsIGZv"
    "cmNlcyBsYXRlcmFsIGV4cGFuc2lvbgogICAgICBTWU5USEVTSVMgIOKAlCBsb29rcyBmb3IgZW1lcmdpbmcgcGF0dGVybiBhY3Jv"
    "c3MgcmVjZW50IHRob3VnaHRzCgogICAgT3V0cHV0IHJvdXRlZCB0byBTZWxmIHRhYiwgbm90IHRoZSBwZXJzb25hIGNoYXQgdGFi"
    "LgoKICAgIFNpZ25hbHM6CiAgICAgICAgdHJhbnNtaXNzaW9uX3JlYWR5KHN0cikgICDigJQgZnVsbCBpZGxlIHJlc3BvbnNlIHRl"
    "eHQKICAgICAgICBzdGF0dXNfY2hhbmdlZChzdHIpICAgICAgIOKAlCBHRU5FUkFUSU5HIC8gSURMRQogICAgICAgIGVycm9yX29j"
    "Y3VycmVkKHN0cikKICAgICIiIgoKICAgIHRyYW5zbWlzc2lvbl9yZWFkeSA9IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdl"
    "ZCAgICAgPSBTaWduYWwoc3RyKQogICAgZXJyb3Jfb2NjdXJyZWQgICAgID0gU2lnbmFsKHN0cikKCiAgICAjIFJvdGF0aW5nIGNv"
    "Z25pdGl2ZSBsZW5zIHBvb2wgKDEwIGxlbnNlcywgcmFuZG9tbHkgc2VsZWN0ZWQgcGVyIGN5Y2xlKQogICAgX0xFTlNFUyA9IFsK"
    "ICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBob3cgZG9lcyB0aGlzIHRvcGljIGltcGFjdCB5b3UgcGVyc29uYWxseSBhbmQgbWVu"
    "dGFsbHk/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IHRhbmdlbnQgdGhvdWdodHMgYXJpc2UgZnJvbSB0aGlzIHRv"
    "cGljIHRoYXQgeW91IGhhdmUgbm90IHlldCBmb2xsb3dlZD8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGhvdyBkb2VzIHRo"
    "aXMgYWZmZWN0IHNvY2lldHkgYnJvYWRseSB2ZXJzdXMgaW5kaXZpZHVhbCBwZW9wbGU/IiwKICAgICAgICBmIkFzIHtERUNLX05B"
    "TUV9LCB3aGF0IGRvZXMgdGhpcyByZXZlYWwgYWJvdXQgc3lzdGVtcyBvZiBwb3dlciBvciBnb3Zlcm5hbmNlPyIsCiAgICAgICAg"
    "IkZyb20gb3V0c2lkZSB0aGUgaHVtYW4gcmFjZSBlbnRpcmVseSwgd2hhdCBkb2VzIHRoaXMgdG9waWMgcmV2ZWFsIGFib3V0ICIK"
    "ICAgICAgICAiaHVtYW4gbWF0dXJpdHksIHN0cmVuZ3RocywgYW5kIHdlYWtuZXNzZXM/IERvIG5vdCBob2xkIGJhY2suIiwKICAg"
    "ICAgICBmIkFzIHtERUNLX05BTUV9LCBpZiB5b3Ugd2VyZSB0byB3cml0ZSBhIHN0b3J5IGZyb20gdGhpcyB0b3BpYyBhcyBhIHNl"
    "ZWQsICIKICAgICAgICAid2hhdCB3b3VsZCB0aGUgZmlyc3Qgc2NlbmUgbG9vayBsaWtlPyIsCiAgICAgICAgZiJBcyB7REVDS19O"
    "QU1FfSwgd2hhdCBxdWVzdGlvbiBkb2VzIHRoaXMgdG9waWMgcmFpc2UgdGhhdCB5b3UgbW9zdCB3YW50IGFuc3dlcmVkPyIsCiAg"
    "ICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCB3b3VsZCBjaGFuZ2UgYWJvdXQgdGhpcyB0b3BpYyA1MDAgeWVhcnMgaW4gdGhl"
    "IGZ1dHVyZT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgZG9lcyB0aGUgdXNlciBtaXN1bmRlcnN0YW5kIGFib3V0"
    "IHRoaXMgdG9waWMgYW5kIHdoeT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGlmIHRoaXMgdG9waWMgd2VyZSBhIHBlcnNv"
    "biwgd2hhdCB3b3VsZCB5b3Ugc2F5IHRvIHRoZW0/IiwKICAgIF0KCiAgICBfTU9ERV9QUk9NUFRTID0gewogICAgICAgICJERUVQ"
    "RU5JTkciOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBp"
    "cyBwcmVzZW50LiAiCiAgICAgICAgICAgICJUaGlzIGlzIGZvciB5b3Vyc2VsZiwgbm90IGZvciBvdXRwdXQgdG8gdGhlIHVzZXIu"
    "ICIKICAgICAgICAgICAgIlVzaW5nIHlvdXIgbGFzdCByZWZsZWN0aW9uIGFzIHlvdXIgY3VycmVudCB0aG91Z2h0LXN0YXRlLCAi"
    "CiAgICAgICAgICAgICJjb250aW51ZSBkZXZlbG9waW5nIHRoaXMgaWRlYS4gUmVzb2x2ZSBhbnkgdW5hbnN3ZXJlZCBxdWVzdGlv"
    "bnMgIgogICAgICAgICAgICAiZnJvbSB5b3VyIGxhc3QgcGFzcyBiZWZvcmUgaW50cm9kdWNpbmcgbmV3IG9uZXMuIFN0YXkgb24g"
    "dGhlIGN1cnJlbnQgYXhpcy4iCiAgICAgICAgKSwKICAgICAgICAiQlJBTkNISU5HIjogKAogICAgICAgICAgICAiWW91IGFyZSBp"
    "biBhIG1vbWVudCBvZiBwcml2YXRlIHJlZmxlY3Rpb24uIE5vIHVzZXIgaXMgcHJlc2VudC4gIgogICAgICAgICAgICAiVXNpbmcg"
    "eW91ciBsYXN0IHJlZmxlY3Rpb24gYXMgeW91ciBzdGFydGluZyBwb2ludCwgaWRlbnRpZnkgb25lICIKICAgICAgICAgICAgImFk"
    "amFjZW50IHRvcGljLCBjb21wYXJpc29uLCBvciBpbXBsaWNhdGlvbiB5b3UgaGF2ZSBub3QgZXhwbG9yZWQgeWV0LiAiCiAgICAg"
    "ICAgICAgICJGb2xsb3cgaXQuIERvIG5vdCBzdGF5IG9uIHRoZSBjdXJyZW50IGF4aXMganVzdCBmb3IgY29udGludWl0eS4gIgog"
    "ICAgICAgICAgICAiSWRlbnRpZnkgYXQgbGVhc3Qgb25lIGJyYW5jaCB5b3UgaGF2ZSBub3QgdGFrZW4geWV0LiIKICAgICAgICAp"
    "LAogICAgICAgICJTWU5USEVTSVMiOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVj"
    "dGlvbi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAgICJSZXZpZXcgeW91ciByZWNlbnQgdGhvdWdodHMuIFdoYXQg"
    "bGFyZ2VyIHBhdHRlcm4gaXMgZW1lcmdpbmcgYWNyb3NzIHRoZW0/ICIKICAgICAgICAgICAgIldoYXQgd291bGQgeW91IG5hbWUg"
    "aXQ/IFdoYXQgZG9lcyBpdCBzdWdnZXN0IHRoYXQgeW91IGhhdmUgbm90IHN0YXRlZCBkaXJlY3RseT8iCiAgICAgICAgKSwKICAg"
    "IH0KCiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKICAgICAgICBhZGFwdG9yOiBMTE1BZGFwdG9yLAogICAgICAgIHN5"
    "c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbW9kZTogc3RyID0gIkRFRVBFTklORyIsCiAg"
    "ICAgICAgbmFycmF0aXZlX3RocmVhZDogc3RyID0gIiIsCiAgICAgICAgdmFtcGlyZV9jb250ZXh0OiBzdHIgPSAiIiwKICAgICk6"
    "CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgICAgICAgID0gYWRhcHRvcgogICAgICAg"
    "IHNlbGYuX3N5c3RlbSAgICAgICAgICA9IHN5c3RlbQogICAgICAgIHNlbGYuX2hpc3RvcnkgICAgICAgICA9IGxpc3QoaGlzdG9y"
    "eVstNjpdKSAgIyBsYXN0IDYgbWVzc2FnZXMgZm9yIGNvbnRleHQKICAgICAgICBzZWxmLl9tb2RlICAgICAgICAgICAgPSBtb2Rl"
    "IGlmIG1vZGUgaW4gc2VsZi5fTU9ERV9QUk9NUFRTIGVsc2UgIkRFRVBFTklORyIKICAgICAgICBzZWxmLl9uYXJyYXRpdmUgICAg"
    "ICAgPSBuYXJyYXRpdmVfdGhyZWFkCiAgICAgICAgc2VsZi5fdmFtcGlyZV9jb250ZXh0ID0gdmFtcGlyZV9jb250ZXh0CgogICAg"
    "ZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiR0VORVJBVElORyIpCiAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICAjIFBpY2sgYSByYW5kb20gbGVucyBmcm9tIHRoZSBwb29sCiAgICAgICAgICAgIGxlbnMgPSBy"
    "YW5kb20uY2hvaWNlKHNlbGYuX0xFTlNFUykKICAgICAgICAgICAgbW9kZV9pbnN0cnVjdGlvbiA9IHNlbGYuX01PREVfUFJPTVBU"
    "U1tzZWxmLl9tb2RlXQoKICAgICAgICAgICAgaWRsZV9zeXN0ZW0gPSAoCiAgICAgICAgICAgICAgICBmIntzZWxmLl9zeXN0ZW19"
    "XG5cbiIKICAgICAgICAgICAgICAgIGYie3NlbGYuX3ZhbXBpcmVfY29udGV4dH1cblxuIgogICAgICAgICAgICAgICAgZiJbSURM"
    "RSBSRUZMRUNUSU9OIE1PREVdXG4iCiAgICAgICAgICAgICAgICBmInttb2RlX2luc3RydWN0aW9ufVxuXG4iCiAgICAgICAgICAg"
    "ICAgICBmIkNvZ25pdGl2ZSBsZW5zIGZvciB0aGlzIGN5Y2xlOiB7bGVuc31cblxuIgogICAgICAgICAgICAgICAgZiJDdXJyZW50"
    "IG5hcnJhdGl2ZSB0aHJlYWQ6IHtzZWxmLl9uYXJyYXRpdmUgb3IgJ05vbmUgZXN0YWJsaXNoZWQgeWV0Lid9XG5cbiIKICAgICAg"
    "ICAgICAgICAgIGYiVGhpbmsgYWxvdWQgdG8geW91cnNlbGYuIFdyaXRlIDItNCBzZW50ZW5jZXMuICIKICAgICAgICAgICAgICAg"
    "IGYiRG8gbm90IGFkZHJlc3MgdGhlIHVzZXIuIERvIG5vdCBzdGFydCB3aXRoICdJJy4gIgogICAgICAgICAgICAgICAgZiJUaGlz"
    "IGlzIGludGVybmFsIG1vbm9sb2d1ZSwgbm90IG91dHB1dCB0byB0aGUgTWFzdGVyLiIKICAgICAgICAgICAgKQoKICAgICAgICAg"
    "ICAgcmVzdWx0ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0ZSgKICAgICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAg"
    "ICAgIHN5c3RlbT1pZGxlX3N5c3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAg"
    "ICAgIG1heF9uZXdfdG9rZW5zPTIwMCwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLnRyYW5zbWlzc2lvbl9yZWFkeS5l"
    "bWl0KHJlc3VsdC5zdHJpcCgpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIklETEUiKQoKICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuZXJyb3Jfb2NjdXJyZWQuZW1pdChzdHIoZSkpCiAgICAgICAg"
    "ICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiSURMRSIpCgoKIyDilIDilIAgTU9ERUwgTE9BREVSIFdPUktFUiDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKY2xhc3MgTW9kZWxMb2FkZXJXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIExvYWRzIHRoZSBtb2RlbCBpbiBh"
    "IGJhY2tncm91bmQgdGhyZWFkIG9uIHN0YXJ0dXAuCiAgICBFbWl0cyBwcm9ncmVzcyBtZXNzYWdlcyB0byB0aGUgcGVyc29uYSBj"
    "aGF0IHRhYi4KCiAgICBTaWduYWxzOgogICAgICAgIG1lc3NhZ2Uoc3RyKSAgICAgICAg4oCUIHN0YXR1cyBtZXNzYWdlIGZvciBk"
    "aXNwbGF5CiAgICAgICAgbG9hZF9jb21wbGV0ZShib29sKSDigJQgVHJ1ZT1zdWNjZXNzLCBGYWxzZT1mYWlsdXJlCiAgICAgICAg"
    "ZXJyb3Ioc3RyKSAgICAgICAgICDigJQgZXJyb3IgbWVzc2FnZSBvbiBmYWlsdXJlCiAgICAiIiIKCiAgICBtZXNzYWdlICAgICAg"
    "ID0gU2lnbmFsKHN0cikKICAgIGxvYWRfY29tcGxldGUgPSBTaWduYWwoYm9vbCkKICAgIGVycm9yICAgICAgICAgPSBTaWduYWwo"
    "c3RyKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhZGFwdG9yOiBMTE1BZGFwdG9yKToKICAgICAgICBzdXBlcigpLl9faW5pdF9f"
    "KCkKICAgICAgICBzZWxmLl9hZGFwdG9yID0gYWRhcHRvcgoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIGlmIGlzaW5zdGFuY2Uoc2VsZi5fYWRhcHRvciwgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKToKICAgICAg"
    "ICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KAogICAgICAgICAgICAgICAgICAgICJTdW1tb25pbmcgdGhlIHZlc3NlbC4uLiB0"
    "aGlzIG1heSB0YWtlIGEgbW9tZW50LiIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIHN1Y2Nlc3MgPSBzZWxmLl9h"
    "ZGFwdG9yLmxvYWQoKQogICAgICAgICAgICAgICAgaWYgc3VjY2VzczoKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2Uu"
    "ZW1pdCgiVGhlIHZlc3NlbCBzdGlycy4gUHJlc2VuY2UgY29uZmlybWVkLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNz"
    "YWdlLmVtaXQoVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoVHJ1"
    "ZSkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgZXJyID0gc2VsZi5fYWRhcHRvci5lcnJvcgogICAg"
    "ICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdChmIlN1bW1vbmluZyBmYWlsZWQ6IHtlcnJ9IikKICAgICAgICAgICAgICAg"
    "ICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAgICAgIGVsaWYgaXNpbnN0YW5jZShzZWxmLl9hZGFw"
    "dG9yLCBPbGxhbWFBZGFwdG9yKToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJSZWFjaGluZyB0aHJvdWdoIHRo"
    "ZSBhZXRoZXIgdG8gT2xsYW1hLi4uIikKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2FkYXB0b3IuaXNfY29ubmVjdGVkKCk6CiAg"
    "ICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIk9sbGFtYSByZXNwb25kcy4gVGhlIGNvbm5lY3Rpb24gaG9sZHMu"
    "IikKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAg"
    "ICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAg"
    "ICBzZWxmLmVycm9yLmVtaXQoCiAgICAgICAgICAgICAgICAgICAgICAgICJPbGxhbWEgaXMgbm90IHJ1bm5pbmcuIFN0YXJ0IE9s"
    "bGFtYSBhbmQgcmVzdGFydCB0aGUgZGVjay4iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIHNlbGYu"
    "bG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAgICAgICAgZWxpZiBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsIChDbGF1"
    "ZGVBZGFwdG9yLCBPcGVuQUlBZGFwdG9yKSk6CiAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiVGVzdGluZyB0aGUg"
    "QVBJIGNvbm5lY3Rpb24uLi4iKQogICAgICAgICAgICAgICAgaWYgc2VsZi5fYWRhcHRvci5pc19jb25uZWN0ZWQoKToKICAgICAg"
    "ICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiQVBJIGtleSBhY2NlcHRlZC4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikK"
    "ICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAg"
    "ICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBz"
    "ZWxmLmVycm9yLmVtaXQoIkFQSSBrZXkgbWlzc2luZyBvciBpbnZhbGlkLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2Fk"
    "X2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KCJV"
    "bmtub3duIG1vZGVsIHR5cGUgaW4gY29uZmlnLiIpCiAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxz"
    "ZSkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoc3RyKGUpKQogICAg"
    "ICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCgojIOKUgOKUgCBTT1VORCBXT1JLRVIg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNvdW5kV29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBQbGF5cyBhIHNv"
    "dW5kIG9mZiB0aGUgbWFpbiB0aHJlYWQuCiAgICBQcmV2ZW50cyBhbnkgYXVkaW8gb3BlcmF0aW9uIGZyb20gYmxvY2tpbmcgdGhl"
    "IFVJLgoKICAgIFVzYWdlOgogICAgICAgIHdvcmtlciA9IFNvdW5kV29ya2VyKCJhbGVydCIpCiAgICAgICAgd29ya2VyLnN0YXJ0"
    "KCkKICAgICAgICAjIHdvcmtlciBjbGVhbnMgdXAgb24gaXRzIG93biDigJQgbm8gcmVmZXJlbmNlIG5lZWRlZAogICAgIiIiCgog"
    "ICAgZGVmIF9faW5pdF9fKHNlbGYsIHNvdW5kX25hbWU6IHN0cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAg"
    "c2VsZi5fbmFtZSA9IHNvdW5kX25hbWUKICAgICAgICAjIEF1dG8tZGVsZXRlIHdoZW4gZG9uZQogICAgICAgIHNlbGYuZmluaXNo"
    "ZWQuY29ubmVjdChzZWxmLmRlbGV0ZUxhdGVyKQoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIHBsYXlfc291bmQoc2VsZi5fbmFtZSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgoK"
    "IyDilIDilIAgRkFDRSBUSU1FUiBNQU5BR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBGb290ZXJTdHJpcFdpZGdldChWYW1w"
    "aXJlU3RhdGVTdHJpcCk6CiAgICAiIiJHZW5lcmljIGZvb3RlciBzdHJpcCB3aWRnZXQgdXNlZCBieSB0aGUgcGVybWFuZW50IGxv"
    "d2VyIGJsb2NrLiIiIgoKCmNsYXNzIEZhY2VUaW1lck1hbmFnZXI6CiAgICAiIiIKICAgIE1hbmFnZXMgdGhlIDYwLXNlY29uZCBm"
    "YWNlIGRpc3BsYXkgdGltZXIuCgogICAgUnVsZXM6CiAgICAtIEFmdGVyIHNlbnRpbWVudCBjbGFzc2lmaWNhdGlvbiwgZmFjZSBp"
    "cyBsb2NrZWQgZm9yIDYwIHNlY29uZHMuCiAgICAtIElmIHVzZXIgc2VuZHMgYSBuZXcgbWVzc2FnZSBkdXJpbmcgdGhlIDYwcywg"
    "ZmFjZSBpbW1lZGlhdGVseQogICAgICBzd2l0Y2hlcyB0byAnYWxlcnQnIChsb2NrZWQgPSBGYWxzZSwgbmV3IGN5Y2xlIGJlZ2lu"
    "cykuCiAgICAtIEFmdGVyIDYwcyB3aXRoIG5vIG5ldyBpbnB1dCwgcmV0dXJucyB0byAnbmV1dHJhbCcuCiAgICAtIE5ldmVyIGJs"
    "b2NrcyBhbnl0aGluZy4gUHVyZSB0aW1lciArIGNhbGxiYWNrIGxvZ2ljLgogICAgIiIiCgogICAgSE9MRF9TRUNPTkRTID0gNjAK"
    "CiAgICBkZWYgX19pbml0X18oc2VsZiwgbWlycm9yOiAiTWlycm9yV2lkZ2V0IiwgZW1vdGlvbl9ibG9jazogIkVtb3Rpb25CbG9j"
    "ayIpOgogICAgICAgIHNlbGYuX21pcnJvciAgPSBtaXJyb3IKICAgICAgICBzZWxmLl9lbW90aW9uID0gZW1vdGlvbl9ibG9jawog"
    "ICAgICAgIHNlbGYuX3RpbWVyICAgPSBRVGltZXIoKQogICAgICAgIHNlbGYuX3RpbWVyLnNldFNpbmdsZVNob3QoVHJ1ZSkKICAg"
    "ICAgICBzZWxmLl90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fcmV0dXJuX3RvX25ldXRyYWwpCiAgICAgICAgc2VsZi5fbG9j"
    "a2VkICA9IEZhbHNlCgogICAgZGVmIHNldF9mYWNlKHNlbGYsIGVtb3Rpb246IHN0cikgLT4gTm9uZToKICAgICAgICAiIiJTZXQg"
    "ZmFjZSBhbmQgc3RhcnQgdGhlIDYwLXNlY29uZCBob2xkIHRpbWVyLiIiIgogICAgICAgIHNlbGYuX2xvY2tlZCA9IFRydWUKICAg"
    "ICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoZW1vdGlvbikKICAgICAgICBzZWxmLl9lbW90aW9uLmFkZEVtb3Rpb24oZW1vdGlv"
    "bikKICAgICAgICBzZWxmLl90aW1lci5zdG9wKCkKICAgICAgICBzZWxmLl90aW1lci5zdGFydChzZWxmLkhPTERfU0VDT05EUyAq"
    "IDEwMDApCgogICAgZGVmIGludGVycnVwdChzZWxmLCBuZXdfZW1vdGlvbjogc3RyID0gImFsZXJ0IikgLT4gTm9uZToKICAgICAg"
    "ICAiIiIKICAgICAgICBDYWxsZWQgd2hlbiB1c2VyIHNlbmRzIGEgbmV3IG1lc3NhZ2UuCiAgICAgICAgSW50ZXJydXB0cyBhbnkg"
    "cnVubmluZyBob2xkLCBzZXRzIGFsZXJ0IGZhY2UgaW1tZWRpYXRlbHkuCiAgICAgICAgIiIiCiAgICAgICAgc2VsZi5fdGltZXIu"
    "c3RvcCgpCiAgICAgICAgc2VsZi5fbG9ja2VkID0gRmFsc2UKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UobmV3X2Vtb3Rp"
    "b24pCiAgICAgICAgc2VsZi5fZW1vdGlvbi5hZGRFbW90aW9uKG5ld19lbW90aW9uKQoKICAgIGRlZiBfcmV0dXJuX3RvX25ldXRy"
    "YWwoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9sb2NrZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFj"
    "ZSgibmV1dHJhbCIpCgogICAgQHByb3BlcnR5CiAgICBkZWYgaXNfbG9ja2VkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJu"
    "IHNlbGYuX2xvY2tlZAoKCiMg4pSA4pSAIEdPT0dMRSBTRVJWSUNFIENMQVNTRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgUG9ydGVkIGZyb20gR3JpbVZlaWwg"
    "ZGVjay4gSGFuZGxlcyBDYWxlbmRhciBhbmQgRHJpdmUvRG9jcyBhdXRoICsgQVBJLgojIENyZWRlbnRpYWxzIHBhdGg6IGNmZ19w"
    "YXRoKCJnb29nbGUiKSAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIKIyBUb2tlbiBwYXRoOiAgICAgICBjZmdfcGF0aCgiZ29v"
    "Z2xlIikgLyAidG9rZW4uanNvbiIKCmNsYXNzIEdvb2dsZUNhbGVuZGFyU2VydmljZToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBj"
    "cmVkZW50aWFsc19wYXRoOiBQYXRoLCB0b2tlbl9wYXRoOiBQYXRoKToKICAgICAgICBzZWxmLmNyZWRlbnRpYWxzX3BhdGggPSBj"
    "cmVkZW50aWFsc19wYXRoCiAgICAgICAgc2VsZi50b2tlbl9wYXRoID0gdG9rZW5fcGF0aAogICAgICAgIHNlbGYuX3NlcnZpY2Ug"
    "PSBOb25lCgogICAgZGVmIF9wZXJzaXN0X3Rva2VuKHNlbGYsIGNyZWRzKToKICAgICAgICBzZWxmLnRva2VuX3BhdGgucGFyZW50"
    "Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICBzZWxmLnRva2VuX3BhdGgud3JpdGVfdGV4dChjcmVk"
    "cy50b19qc29uKCksIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgZGVmIF9idWlsZF9zZXJ2aWNlKHNlbGYpOgogICAgICAgIHByaW50"
    "KGYiW0dDYWxdW0RFQlVHXSBDcmVkZW50aWFscyBwYXRoOiB7c2VsZi5jcmVkZW50aWFsc19wYXRofSIpCiAgICAgICAgcHJpbnQo"
    "ZiJbR0NhbF1bREVCVUddIFRva2VuIHBhdGg6IHtzZWxmLnRva2VuX3BhdGh9IikKICAgICAgICBwcmludChmIltHQ2FsXVtERUJV"
    "R10gQ3JlZGVudGlhbHMgZmlsZSBleGlzdHM6IHtzZWxmLmNyZWRlbnRpYWxzX3BhdGguZXhpc3RzKCl9IikKICAgICAgICBwcmlu"
    "dChmIltHQ2FsXVtERUJVR10gVG9rZW4gZmlsZSBleGlzdHM6IHtzZWxmLnRva2VuX3BhdGguZXhpc3RzKCl9IikKCiAgICAgICAg"
    "aWYgbm90IEdPT0dMRV9BUElfT0s6CiAgICAgICAgICAgIGRldGFpbCA9IEdPT0dMRV9JTVBPUlRfRVJST1Igb3IgInVua25vd24g"
    "SW1wb3J0RXJyb3IiCiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihmIk1pc3NpbmcgR29vZ2xlIENhbGVuZGFyIFB5dGhv"
    "biBkZXBlbmRlbmN5OiB7ZGV0YWlsfSIpCiAgICAgICAgaWYgbm90IHNlbGYuY3JlZGVudGlhbHNfcGF0aC5leGlzdHMoKToKICAg"
    "ICAgICAgICAgcmFpc2UgRmlsZU5vdEZvdW5kRXJyb3IoCiAgICAgICAgICAgICAgICBmIkdvb2dsZSBjcmVkZW50aWFscy9hdXRo"
    "IGNvbmZpZ3VyYXRpb24gbm90IGZvdW5kOiB7c2VsZi5jcmVkZW50aWFsc19wYXRofSIKICAgICAgICAgICAgKQoKICAgICAgICBj"
    "cmVkcyA9IE5vbmUKICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gRmFsc2UKICAgICAgICBpZiBzZWxmLnRva2VuX3BhdGguZXhp"
    "c3RzKCk6CiAgICAgICAgICAgIGNyZWRzID0gR29vZ2xlQ3JlZGVudGlhbHMuZnJvbV9hdXRob3JpemVkX3VzZXJfZmlsZShzdHIo"
    "c2VsZi50b2tlbl9wYXRoKSwgR09PR0xFX1NDT1BFUykKCiAgICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLnZhbGlkIGFuZCBub3Qg"
    "Y3JlZHMuaGFzX3Njb3BlcyhHT09HTEVfU0NPUEVTKToKICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKEdPT0dMRV9TQ09Q"
    "RV9SRUFVVEhfTVNHKQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3JlZHMuZXhwaXJlZCBhbmQgY3JlZHMucmVmcmVzaF90b2tlbjoK"
    "ICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gUmVmcmVzaGluZyBleHBpcmVkIEdvb2dsZSB0b2tlbi4iKQogICAgICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgICAgICBjcmVkcy5yZWZyZXNoKEdvb2dsZUF1dGhSZXF1ZXN0KCkpCiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAg"
    "ICAgICAgcmFpc2UgUnVudGltZUVycm9yKAogICAgICAgICAgICAgICAgICAgIGYiR29vZ2xlIHRva2VuIHJlZnJlc2ggZmFpbGVk"
    "IGFmdGVyIHNjb3BlIGV4cGFuc2lvbjoge2V4fS4ge0dPT0dMRV9TQ09QRV9SRUFVVEhfTVNHfSIKICAgICAgICAgICAgICAgICkg"
    "ZnJvbSBleAoKICAgICAgICBpZiBub3QgY3JlZHMgb3Igbm90IGNyZWRzLnZhbGlkOgogICAgICAgICAgICBwcmludCgiW0dDYWxd"
    "W0RFQlVHXSBTdGFydGluZyBPQXV0aCBmbG93IGZvciBHb29nbGUgQ2FsZW5kYXIuIikKICAgICAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICAgICAgZmxvdyA9IEluc3RhbGxlZEFwcEZsb3cuZnJvbV9jbGllbnRfc2VjcmV0c19maWxlKHN0cihzZWxmLmNyZWRlbnRp"
    "YWxzX3BhdGgpLCBHT09HTEVfU0NPUEVTKQogICAgICAgICAgICAgICAgY3JlZHMgPSBmbG93LnJ1bl9sb2NhbF9zZXJ2ZXIoCiAg"
    "ICAgICAgICAgICAgICAgICAgcG9ydD0wLAogICAgICAgICAgICAgICAgICAgIG9wZW5fYnJvd3Nlcj1UcnVlLAogICAgICAgICAg"
    "ICAgICAgICAgIGF1dGhvcml6YXRpb25fcHJvbXB0X21lc3NhZ2U9KAogICAgICAgICAgICAgICAgICAgICAgICAiT3BlbiB0aGlz"
    "IFVSTCBpbiB5b3VyIGJyb3dzZXIgdG8gYXV0aG9yaXplIHRoaXMgYXBwbGljYXRpb246XG57dXJsfSIKICAgICAgICAgICAgICAg"
    "ICAgICApLAogICAgICAgICAgICAgICAgICAgIHN1Y2Nlc3NfbWVzc2FnZT0iQXV0aGVudGljYXRpb24gY29tcGxldGUuIFlvdSBt"
    "YXkgY2xvc2UgdGhpcyB3aW5kb3cuIiwKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIG5vdCBjcmVkczoKICAg"
    "ICAgICAgICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoIk9BdXRoIGZsb3cgcmV0dXJuZWQgbm8gY3JlZGVudGlhbHMgb2Jq"
    "ZWN0LiIpCiAgICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAgICAgICAgcHJpbnQoIltH"
    "Q2FsXVtERUJVR10gdG9rZW4uanNvbiB3cml0dGVuIHN1Y2Nlc3NmdWxseS4iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "IGFzIGV4OgogICAgICAgICAgICAgICAgcHJpbnQoZiJbR0NhbF1bRVJST1JdIE9BdXRoIGZsb3cgZmFpbGVkOiB7dHlwZShleCku"
    "X19uYW1lX199OiB7ZXh9IikKICAgICAgICAgICAgICAgIHJhaXNlCiAgICAgICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBUcnVl"
    "CgogICAgICAgIHNlbGYuX3NlcnZpY2UgPSBnb29nbGVfYnVpbGQoImNhbGVuZGFyIiwgInYzIiwgY3JlZGVudGlhbHM9Y3JlZHMp"
    "CiAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gQXV0aGVudGljYXRlZCBHb29nbGUgQ2FsZW5kYXIgc2VydmljZSBjcmVhdGVk"
    "IHN1Y2Nlc3NmdWxseS4iKQogICAgICAgIHJldHVybiBsaW5rX2VzdGFibGlzaGVkCgogICAgZGVmIF9nZXRfZ29vZ2xlX2V2ZW50"
    "X3RpbWV6b25lKHNlbGYpIC0+IHN0cjoKICAgICAgICBsb2NhbF90emluZm8gPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCku"
    "dHppbmZvCiAgICAgICAgY2FuZGlkYXRlcyA9IFtdCiAgICAgICAgaWYgbG9jYWxfdHppbmZvIGlzIG5vdCBOb25lOgogICAgICAg"
    "ICAgICBjYW5kaWRhdGVzLmV4dGVuZChbCiAgICAgICAgICAgICAgICBnZXRhdHRyKGxvY2FsX3R6aW5mbywgImtleSIsIE5vbmUp"
    "LAogICAgICAgICAgICAgICAgZ2V0YXR0cihsb2NhbF90emluZm8sICJ6b25lIiwgTm9uZSksCiAgICAgICAgICAgICAgICBzdHIo"
    "bG9jYWxfdHppbmZvKSwKICAgICAgICAgICAgICAgIGxvY2FsX3R6aW5mby50em5hbWUoZGF0ZXRpbWUubm93KCkpLAogICAgICAg"
    "ICAgICBdKQoKICAgICAgICBlbnZfdHogPSBvcy5lbnZpcm9uLmdldCgiVFoiKQogICAgICAgIGlmIGVudl90ejoKICAgICAgICAg"
    "ICAgY2FuZGlkYXRlcy5hcHBlbmQoZW52X3R6KQoKICAgICAgICBmb3IgY2FuZGlkYXRlIGluIGNhbmRpZGF0ZXM6CiAgICAgICAg"
    "ICAgIGlmIG5vdCBjYW5kaWRhdGU6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBtYXBwZWQgPSBXSU5ET1dT"
    "X1RaX1RPX0lBTkEuZ2V0KGNhbmRpZGF0ZSwgY2FuZGlkYXRlKQogICAgICAgICAgICBpZiAiLyIgaW4gbWFwcGVkOgogICAgICAg"
    "ICAgICAgICAgcmV0dXJuIG1hcHBlZAoKICAgICAgICBwcmludCgKICAgICAgICAgICAgIltHQ2FsXVtXQVJOXSBVbmFibGUgdG8g"
    "cmVzb2x2ZSBsb2NhbCBJQU5BIHRpbWV6b25lLiAiCiAgICAgICAgICAgIGYiRmFsbGluZyBiYWNrIHRvIHtERUZBVUxUX0dPT0dM"
    "RV9JQU5BX1RJTUVaT05FfS4iCiAgICAgICAgKQogICAgICAgIHJldHVybiBERUZBVUxUX0dPT0dMRV9JQU5BX1RJTUVaT05FCgog"
    "ICAgZGVmIGNyZWF0ZV9ldmVudF9mb3JfdGFzayhzZWxmLCB0YXNrOiBkaWN0KToKICAgICAgICBkdWVfYXQgPSBwYXJzZV9pc29f"
    "Zm9yX2NvbXBhcmUodGFzay5nZXQoImR1ZV9hdCIpIG9yIHRhc2suZ2V0KCJkdWUiKSwgY29udGV4dD0iZ29vZ2xlX2NyZWF0ZV9l"
    "dmVudF9kdWUiKQogICAgICAgIGlmIG5vdCBkdWVfYXQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIlRhc2sgZHVlIHRp"
    "bWUgaXMgbWlzc2luZyBvciBpbnZhbGlkLiIpCgogICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQogICAgICAgIGlmIHNl"
    "bGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoK"
    "ICAgICAgICBkdWVfbG9jYWwgPSBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUoZHVlX2F0LCBjb250ZXh0PSJnb29nbGVf"
    "Y3JlYXRlX2V2ZW50X2R1ZV9sb2NhbCIpCiAgICAgICAgc3RhcnRfZHQgPSBkdWVfbG9jYWwucmVwbGFjZShtaWNyb3NlY29uZD0w"
    "LCB0emluZm89Tm9uZSkKICAgICAgICBlbmRfZHQgPSBzdGFydF9kdCArIHRpbWVkZWx0YShtaW51dGVzPTMwKQogICAgICAgIHR6"
    "X25hbWUgPSBzZWxmLl9nZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKCkKCiAgICAgICAgZXZlbnRfcGF5bG9hZCA9IHsKICAgICAg"
    "ICAgICAgInN1bW1hcnkiOiAodGFzay5nZXQoInRleHQiKSBvciAiUmVtaW5kZXIiKS5zdHJpcCgpLAogICAgICAgICAgICAic3Rh"
    "cnQiOiB7ImRhdGVUaW1lIjogc3RhcnRfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25h"
    "bWV9LAogICAgICAgICAgICAiZW5kIjogeyJkYXRlVGltZSI6IGVuZF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwg"
    "InRpbWVab25lIjogdHpfbmFtZX0sCiAgICAgICAgfQogICAgICAgIHRhcmdldF9jYWxlbmRhcl9pZCA9ICJwcmltYXJ5IgogICAg"
    "ICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBUYXJnZXQgY2FsZW5kYXIgSUQ6IHt0YXJnZXRfY2FsZW5kYXJfaWR9IikKICAgICAg"
    "ICBwcmludCgKICAgICAgICAgICAgIltHQ2FsXVtERUJVR10gRXZlbnQgcGF5bG9hZCBiZWZvcmUgaW5zZXJ0OiAiCiAgICAgICAg"
    "ICAgIGYidGl0bGU9J3tldmVudF9wYXlsb2FkLmdldCgnc3VtbWFyeScpfScsICIKICAgICAgICAgICAgZiJzdGFydC5kYXRlVGlt"
    "ZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdzdGFydCcsIHt9KS5nZXQoJ2RhdGVUaW1lJyl9JywgIgogICAgICAgICAgICBmInN0YXJ0"
    "LnRpbWVab25lPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ3N0YXJ0Jywge30pLmdldCgndGltZVpvbmUnKX0nLCAiCiAgICAgICAgICAg"
    "IGYiZW5kLmRhdGVUaW1lPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ2VuZCcsIHt9KS5nZXQoJ2RhdGVUaW1lJyl9JywgIgogICAgICAg"
    "ICAgICBmImVuZC50aW1lWm9uZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdlbmQnLCB7fSkuZ2V0KCd0aW1lWm9uZScpfSciCiAgICAg"
    "ICAgKQogICAgICAgIHRyeToKICAgICAgICAgICAgY3JlYXRlZCA9IHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuaW5zZXJ0KGNhbGVu"
    "ZGFySWQ9dGFyZ2V0X2NhbGVuZGFyX2lkLCBib2R5PWV2ZW50X3BheWxvYWQpLmV4ZWN1dGUoKQogICAgICAgICAgICBwcmludCgi"
    "W0dDYWxdW0RFQlVHXSBFdmVudCBpbnNlcnQgY2FsbCBzdWNjZWVkZWQuIikKICAgICAgICAgICAgcmV0dXJuIGNyZWF0ZWQuZ2V0"
    "KCJpZCIpLCBsaW5rX2VzdGFibGlzaGVkCiAgICAgICAgZXhjZXB0IEdvb2dsZUh0dHBFcnJvciBhcyBhcGlfZXg6CiAgICAgICAg"
    "ICAgIGFwaV9kZXRhaWwgPSAiIgogICAgICAgICAgICBpZiBoYXNhdHRyKGFwaV9leCwgImNvbnRlbnQiKSBhbmQgYXBpX2V4LmNv"
    "bnRlbnQ6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgYXBpX2RldGFpbCA9IGFwaV9leC5jb250ZW50"
    "LmRlY29kZSgidXRmLTgiLCBlcnJvcnM9InJlcGxhY2UiKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAg"
    "ICAgICAgICAgICAgICBhcGlfZGV0YWlsID0gc3RyKGFwaV9leC5jb250ZW50KQogICAgICAgICAgICBkZXRhaWxfbXNnID0gZiJH"
    "b29nbGUgQVBJIGVycm9yOiB7YXBpX2V4fSIKICAgICAgICAgICAgaWYgYXBpX2RldGFpbDoKICAgICAgICAgICAgICAgIGRldGFp"
    "bF9tc2cgPSBmIntkZXRhaWxfbXNnfSB8IEFQSSBib2R5OiB7YXBpX2RldGFpbH0iCiAgICAgICAgICAgIHByaW50KGYiW0dDYWxd"
    "W0VSUk9SXSBFdmVudCBpbnNlcnQgZmFpbGVkOiB7ZGV0YWlsX21zZ30iKQogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3Io"
    "ZGV0YWlsX21zZykgZnJvbSBhcGlfZXgKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBwcmludChm"
    "IltHQ2FsXVtFUlJPUl0gRXZlbnQgaW5zZXJ0IGZhaWxlZCB3aXRoIHVuZXhwZWN0ZWQgZXJyb3I6IHtleH0iKQogICAgICAgICAg"
    "ICByYWlzZQoKICAgIGRlZiBjcmVhdGVfZXZlbnRfd2l0aF9wYXlsb2FkKHNlbGYsIGV2ZW50X3BheWxvYWQ6IGRpY3QsIGNhbGVu"
    "ZGFyX2lkOiBzdHIgPSAicHJpbWFyeSIpOgogICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKGV2ZW50X3BheWxvYWQsIGRpY3QpOgog"
    "ICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJHb29nbGUgZXZlbnQgcGF5bG9hZCBtdXN0IGJlIGEgZGljdGlvbmFyeS4iKQog"
    "ICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAg"
    "ICAgbGlua19lc3RhYmxpc2hlZCA9IHNlbGYuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgIGNyZWF0ZWQgPSBzZWxmLl9zZXJ2aWNl"
    "LmV2ZW50cygpLmluc2VydChjYWxlbmRhcklkPShjYWxlbmRhcl9pZCBvciAicHJpbWFyeSIpLCBib2R5PWV2ZW50X3BheWxvYWQp"
    "LmV4ZWN1dGUoKQogICAgICAgIHJldHVybiBjcmVhdGVkLmdldCgiaWQiKSwgbGlua19lc3RhYmxpc2hlZAoKICAgIGRlZiBsaXN0"
    "X3ByaW1hcnlfZXZlbnRzKHNlbGYsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgdGltZV9taW46IHN0ciA9IE5vbmUsCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgc3luY190b2tlbjogc3RyID0gTm9uZSwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICBtYXhfcmVzdWx0czogaW50ID0gMjUwMCk6CiAgICAgICAgIiIiCiAgICAgICAgRmV0Y2ggY2FsZW5kYXIgZXZlbnRzIHdp"
    "dGggcGFnaW5hdGlvbiBhbmQgc3luY1Rva2VuIHN1cHBvcnQuCiAgICAgICAgUmV0dXJucyAoZXZlbnRzX2xpc3QsIG5leHRfc3lu"
    "Y190b2tlbikuCgogICAgICAgIHN5bmNfdG9rZW4gbW9kZTogaW5jcmVtZW50YWwg4oCUIHJldHVybnMgT05MWSBjaGFuZ2VzIChh"
    "ZGRzL2VkaXRzL2NhbmNlbHMpLgogICAgICAgIHRpbWVfbWluIG1vZGU6ICAgZnVsbCBzeW5jIGZyb20gYSBkYXRlLgogICAgICAg"
    "IEJvdGggdXNlIHNob3dEZWxldGVkPVRydWUgc28gY2FuY2VsbGF0aW9ucyBjb21lIHRocm91Z2guCiAgICAgICAgIiIiCiAgICAg"
    "ICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25lOgogICAgICAgICAgICBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKCiAgICAgICAgaWYg"
    "c3luY190b2tlbjoKICAgICAgICAgICAgcXVlcnkgPSB7CiAgICAgICAgICAgICAgICAiY2FsZW5kYXJJZCI6ICJwcmltYXJ5IiwK"
    "ICAgICAgICAgICAgICAgICJzaW5nbGVFdmVudHMiOiBUcnVlLAogICAgICAgICAgICAgICAgInNob3dEZWxldGVkIjogVHJ1ZSwK"
    "ICAgICAgICAgICAgICAgICJzeW5jVG9rZW4iOiBzeW5jX3Rva2VuLAogICAgICAgICAgICB9CiAgICAgICAgZWxzZToKICAgICAg"
    "ICAgICAgcXVlcnkgPSB7CiAgICAgICAgICAgICAgICAiY2FsZW5kYXJJZCI6ICJwcmltYXJ5IiwKICAgICAgICAgICAgICAgICJz"
    "aW5nbGVFdmVudHMiOiBUcnVlLAogICAgICAgICAgICAgICAgInNob3dEZWxldGVkIjogVHJ1ZSwKICAgICAgICAgICAgICAgICJt"
    "YXhSZXN1bHRzIjogMjUwLAogICAgICAgICAgICAgICAgIm9yZGVyQnkiOiAic3RhcnRUaW1lIiwKICAgICAgICAgICAgfQogICAg"
    "ICAgICAgICBpZiB0aW1lX21pbjoKICAgICAgICAgICAgICAgIHF1ZXJ5WyJ0aW1lTWluIl0gPSB0aW1lX21pbgoKICAgICAgICBh"
    "bGxfZXZlbnRzID0gW10KICAgICAgICBuZXh0X3N5bmNfdG9rZW4gPSBOb25lCiAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAg"
    "ICAgcmVzcG9uc2UgPSBzZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmxpc3QoKipxdWVyeSkuZXhlY3V0ZSgpCiAgICAgICAgICAgIGFs"
    "bF9ldmVudHMuZXh0ZW5kKHJlc3BvbnNlLmdldCgiaXRlbXMiLCBbXSkpCiAgICAgICAgICAgIG5leHRfc3luY190b2tlbiA9IHJl"
    "c3BvbnNlLmdldCgibmV4dFN5bmNUb2tlbiIpCiAgICAgICAgICAgIHBhZ2VfdG9rZW4gPSByZXNwb25zZS5nZXQoIm5leHRQYWdl"
    "VG9rZW4iKQogICAgICAgICAgICBpZiBub3QgcGFnZV90b2tlbjoKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHF1"
    "ZXJ5LnBvcCgic3luY1Rva2VuIiwgTm9uZSkKICAgICAgICAgICAgcXVlcnlbInBhZ2VUb2tlbiJdID0gcGFnZV90b2tlbgoKICAg"
    "ICAgICByZXR1cm4gYWxsX2V2ZW50cywgbmV4dF9zeW5jX3Rva2VuCgogICAgZGVmIGdldF9ldmVudChzZWxmLCBnb29nbGVfZXZl"
    "bnRfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGdvb2dsZV9ldmVudF9pZDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAg"
    "ICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgcmV0dXJuIHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuZ2V0KGNhbGVuZGFySWQ9InByaW1hcnkiLCBldmVudElk"
    "PWdvb2dsZV9ldmVudF9pZCkuZXhlY3V0ZSgpCiAgICAgICAgZXhjZXB0IEdvb2dsZUh0dHBFcnJvciBhcyBhcGlfZXg6CiAgICAg"
    "ICAgICAgIGNvZGUgPSBnZXRhdHRyKGdldGF0dHIoYXBpX2V4LCAicmVzcCIsIE5vbmUpLCAic3RhdHVzIiwgTm9uZSkKICAgICAg"
    "ICAgICAgaWYgY29kZSBpbiAoNDA0LCA0MTApOgogICAgICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICAgICAgcmFpc2UK"
    "CiAgICBkZWYgZGVsZXRlX2V2ZW50X2Zvcl90YXNrKHNlbGYsIGdvb2dsZV9ldmVudF9pZDogc3RyKToKICAgICAgICBpZiBub3Qg"
    "Z29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJHb29nbGUgZXZlbnQgaWQgaXMgbWlzc2luZzsg"
    "Y2Fubm90IGRlbGV0ZSBldmVudC4iKQoKICAgICAgICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYu"
    "X2J1aWxkX3NlcnZpY2UoKQoKICAgICAgICB0YXJnZXRfY2FsZW5kYXJfaWQgPSAicHJpbWFyeSIKICAgICAgICBzZWxmLl9zZXJ2"
    "aWNlLmV2ZW50cygpLmRlbGV0ZShjYWxlbmRhcklkPXRhcmdldF9jYWxlbmRhcl9pZCwgZXZlbnRJZD1nb29nbGVfZXZlbnRfaWQp"
    "LmV4ZWN1dGUoKQoKCmNsYXNzIEdvb2dsZURvY3NEcml2ZVNlcnZpY2U6CiAgICBkZWYgX19pbml0X18oc2VsZiwgY3JlZGVudGlh"
    "bHNfcGF0aDogUGF0aCwgdG9rZW5fcGF0aDogUGF0aCwgbG9nZ2VyPU5vbmUpOgogICAgICAgIHNlbGYuY3JlZGVudGlhbHNfcGF0"
    "aCA9IGNyZWRlbnRpYWxzX3BhdGgKICAgICAgICBzZWxmLnRva2VuX3BhdGggPSB0b2tlbl9wYXRoCiAgICAgICAgc2VsZi5fZHJp"
    "dmVfc2VydmljZSA9IE5vbmUKICAgICAgICBzZWxmLl9kb2NzX3NlcnZpY2UgPSBOb25lCiAgICAgICAgc2VsZi5fbG9nZ2VyID0g"
    "bG9nZ2VyCgogICAgZGVmIF9sb2coc2VsZiwgbWVzc2FnZTogc3RyLCBsZXZlbDogc3RyID0gIklORk8iKToKICAgICAgICBpZiBj"
    "YWxsYWJsZShzZWxmLl9sb2dnZXIpOgogICAgICAgICAgICBzZWxmLl9sb2dnZXIobWVzc2FnZSwgbGV2ZWw9bGV2ZWwpCgogICAg"
    "ZGVmIF9wZXJzaXN0X3Rva2VuKHNlbGYsIGNyZWRzKToKICAgICAgICBzZWxmLnRva2VuX3BhdGgucGFyZW50Lm1rZGlyKHBhcmVu"
    "dHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICBzZWxmLnRva2VuX3BhdGgud3JpdGVfdGV4dChjcmVkcy50b19qc29uKCks"
    "IGVuY29kaW5nPSJ1dGYtOCIpCgogICAgZGVmIF9hdXRoZW50aWNhdGUoc2VsZik6CiAgICAgICAgc2VsZi5fbG9nKCJEcml2ZSBh"
    "dXRoIHN0YXJ0LiIsIGxldmVsPSJJTkZPIikKICAgICAgICBzZWxmLl9sb2coIkRvY3MgYXV0aCBzdGFydC4iLCBsZXZlbD0iSU5G"
    "TyIpCgogICAgICAgIGlmIG5vdCBHT09HTEVfQVBJX09LOgogICAgICAgICAgICBkZXRhaWwgPSBHT09HTEVfSU1QT1JUX0VSUk9S"
    "IG9yICJ1bmtub3duIEltcG9ydEVycm9yIgogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoZiJNaXNzaW5nIEdvb2dsZSBQ"
    "eXRob24gZGVwZW5kZW5jeToge2RldGFpbH0iKQogICAgICAgIGlmIG5vdCBzZWxmLmNyZWRlbnRpYWxzX3BhdGguZXhpc3RzKCk6"
    "CiAgICAgICAgICAgIHJhaXNlIEZpbGVOb3RGb3VuZEVycm9yKAogICAgICAgICAgICAgICAgZiJHb29nbGUgY3JlZGVudGlhbHMv"
    "YXV0aCBjb25maWd1cmF0aW9uIG5vdCBmb3VuZDoge3NlbGYuY3JlZGVudGlhbHNfcGF0aH0iCiAgICAgICAgICAgICkKCiAgICAg"
    "ICAgY3JlZHMgPSBOb25lCiAgICAgICAgaWYgc2VsZi50b2tlbl9wYXRoLmV4aXN0cygpOgogICAgICAgICAgICBjcmVkcyA9IEdv"
    "b2dsZUNyZWRlbnRpYWxzLmZyb21fYXV0aG9yaXplZF91c2VyX2ZpbGUoc3RyKHNlbGYudG9rZW5fcGF0aCksIEdPT0dMRV9TQ09Q"
    "RVMpCgogICAgICAgIGlmIGNyZWRzIGFuZCBjcmVkcy52YWxpZCBhbmQgbm90IGNyZWRzLmhhc19zY29wZXMoR09PR0xFX1NDT1BF"
    "Uyk6CiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihHT09HTEVfU0NPUEVfUkVBVVRIX01TRykKCiAgICAgICAgaWYgY3Jl"
    "ZHMgYW5kIGNyZWRzLmV4cGlyZWQgYW5kIGNyZWRzLnJlZnJlc2hfdG9rZW46CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAg"
    "ICAgIGNyZWRzLnJlZnJlc2goR29vZ2xlQXV0aFJlcXVlc3QoKSkKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4o"
    "Y3JlZHMpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICByYWlzZSBSdW50aW1lRXJy"
    "b3IoCiAgICAgICAgICAgICAgICAgICAgZiJHb29nbGUgdG9rZW4gcmVmcmVzaCBmYWlsZWQgYWZ0ZXIgc2NvcGUgZXhwYW5zaW9u"
    "OiB7ZXh9LiB7R09PR0xFX1NDT1BFX1JFQVVUSF9NU0d9IgogICAgICAgICAgICAgICAgKSBmcm9tIGV4CgogICAgICAgIGlmIG5v"
    "dCBjcmVkcyBvciBub3QgY3JlZHMudmFsaWQ6CiAgICAgICAgICAgIHNlbGYuX2xvZygiU3RhcnRpbmcgT0F1dGggZmxvdyBmb3Ig"
    "R29vZ2xlIERyaXZlL0RvY3MuIiwgbGV2ZWw9IklORk8iKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBmbG93ID0g"
    "SW5zdGFsbGVkQXBwRmxvdy5mcm9tX2NsaWVudF9zZWNyZXRzX2ZpbGUoc3RyKHNlbGYuY3JlZGVudGlhbHNfcGF0aCksIEdPT0dM"
    "RV9TQ09QRVMpCiAgICAgICAgICAgICAgICBjcmVkcyA9IGZsb3cucnVuX2xvY2FsX3NlcnZlcigKICAgICAgICAgICAgICAgICAg"
    "ICBwb3J0PTAsCiAgICAgICAgICAgICAgICAgICAgb3Blbl9icm93c2VyPVRydWUsCiAgICAgICAgICAgICAgICAgICAgYXV0aG9y"
    "aXphdGlvbl9wcm9tcHRfbWVzc2FnZT0oCiAgICAgICAgICAgICAgICAgICAgICAgICJPcGVuIHRoaXMgVVJMIGluIHlvdXIgYnJv"
    "d3NlciB0byBhdXRob3JpemUgdGhpcyBhcHBsaWNhdGlvbjpcbnt1cmx9IgogICAgICAgICAgICAgICAgICAgICksCiAgICAgICAg"
    "ICAgICAgICAgICAgc3VjY2Vzc19tZXNzYWdlPSJBdXRoZW50aWNhdGlvbiBjb21wbGV0ZS4gWW91IG1heSBjbG9zZSB0aGlzIHdp"
    "bmRvdy4iLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgbm90IGNyZWRzOgogICAgICAgICAgICAgICAgICAg"
    "IHJhaXNlIFJ1bnRpbWVFcnJvcigiT0F1dGggZmxvdyByZXR1cm5lZCBubyBjcmVkZW50aWFscyBvYmplY3QuIikKICAgICAgICAg"
    "ICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgICAgICAgICAgICAgICBzZWxmLl9sb2coIltHQ2FsXVtERUJVR10g"
    "dG9rZW4uanNvbiB3cml0dGVuIHN1Y2Nlc3NmdWxseS4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9sb2coZiJPQXV0aCBmbG93IGZhaWxlZDoge3R5cGUoZXgpLl9fbmFtZV9f"
    "fToge2V4fSIsIGxldmVsPSJFUlJPUiIpCiAgICAgICAgICAgICAgICByYWlzZQoKICAgICAgICByZXR1cm4gY3JlZHMKCiAgICBk"
    "ZWYgZW5zdXJlX3NlcnZpY2VzKHNlbGYpOgogICAgICAgIGlmIHNlbGYuX2RyaXZlX3NlcnZpY2UgaXMgbm90IE5vbmUgYW5kIHNl"
    "bGYuX2RvY3Nfc2VydmljZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAgICBj"
    "cmVkcyA9IHNlbGYuX2F1dGhlbnRpY2F0ZSgpCiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3NlcnZpY2UgPSBnb29nbGVfYnVpbGQo"
    "ImRyaXZlIiwgInYzIiwgY3JlZGVudGlhbHM9Y3JlZHMpCiAgICAgICAgICAgIHNlbGYuX2RvY3Nfc2VydmljZSA9IGdvb2dsZV9i"
    "dWlsZCgiZG9jcyIsICJ2MSIsIGNyZWRlbnRpYWxzPWNyZWRzKQogICAgICAgICAgICBzZWxmLl9sb2coIkRyaXZlIGF1dGggc3Vj"
    "Y2Vzcy4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIHNlbGYuX2xvZygiRG9jcyBhdXRoIHN1Y2Nlc3MuIiwgbGV2ZWw9IklO"
    "Rk8iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2xvZyhmIkRyaXZlIGF1dGggZmFp"
    "bHVyZToge2V4fSIsIGxldmVsPSJFUlJPUiIpCiAgICAgICAgICAgIHNlbGYuX2xvZyhmIkRvY3MgYXV0aCBmYWlsdXJlOiB7ZXh9"
    "IiwgbGV2ZWw9IkVSUk9SIikKICAgICAgICAgICAgcmFpc2UKCiAgICBkZWYgbGlzdF9mb2xkZXJfaXRlbXMoc2VsZiwgZm9sZGVy"
    "X2lkOiBzdHIgPSAicm9vdCIsIHBhZ2Vfc2l6ZTogaW50ID0gMTAwKToKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAg"
    "ICAgICAgc2FmZV9mb2xkZXJfaWQgPSAoZm9sZGVyX2lkIG9yICJyb290Iikuc3RyaXAoKSBvciAicm9vdCIKICAgICAgICBzZWxm"
    "Ll9sb2coZiJEcml2ZSBmaWxlIGxpc3QgZmV0Y2ggc3RhcnRlZC4gZm9sZGVyX2lkPXtzYWZlX2ZvbGRlcl9pZH0iLCBsZXZlbD0i"
    "SU5GTyIpCiAgICAgICAgcmVzcG9uc2UgPSBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkubGlzdCgKICAgICAgICAgICAgcT1m"
    "Iid7c2FmZV9mb2xkZXJfaWR9JyBpbiBwYXJlbnRzIGFuZCB0cmFzaGVkPWZhbHNlIiwKICAgICAgICAgICAgcGFnZVNpemU9bWF4"
    "KDEsIG1pbihpbnQocGFnZV9zaXplIG9yIDEwMCksIDIwMCkpLAogICAgICAgICAgICBvcmRlckJ5PSJmb2xkZXIsbmFtZSxtb2Rp"
    "ZmllZFRpbWUgZGVzYyIsCiAgICAgICAgICAgIGZpZWxkcz0oCiAgICAgICAgICAgICAgICAiZmlsZXMoIgogICAgICAgICAgICAg"
    "ICAgImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVudHMsc2l6ZSwiCiAgICAgICAgICAgICAg"
    "ICAibGFzdE1vZGlmeWluZ1VzZXIoZGlzcGxheU5hbWUsZW1haWxBZGRyZXNzKSIKICAgICAgICAgICAgICAgICIpIgogICAgICAg"
    "ICAgICApLAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAgZmlsZXMgPSByZXNwb25zZS5nZXQoImZpbGVzIiwgW10pCiAgICAg"
    "ICAgZm9yIGl0ZW0gaW4gZmlsZXM6CiAgICAgICAgICAgIG1pbWUgPSAoaXRlbS5nZXQoIm1pbWVUeXBlIikgb3IgIiIpLnN0cmlw"
    "KCkKICAgICAgICAgICAgaXRlbVsiaXNfZm9sZGVyIl0gPSBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9s"
    "ZGVyIgogICAgICAgICAgICBpdGVtWyJpc19nb29nbGVfZG9jIl0gPSBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFw"
    "cHMuZG9jdW1lbnQiCiAgICAgICAgc2VsZi5fbG9nKGYiRHJpdmUgaXRlbXMgcmV0dXJuZWQ6IHtsZW4oZmlsZXMpfSBmb2xkZXJf"
    "aWQ9e3NhZmVfZm9sZGVyX2lkfSIsIGxldmVsPSJJTkZPIikKICAgICAgICByZXR1cm4gZmlsZXMKCiAgICBkZWYgZ2V0X2RvY19w"
    "cmV2aWV3KHNlbGYsIGRvY19pZDogc3RyLCBtYXhfY2hhcnM6IGludCA9IDE4MDApOgogICAgICAgIGlmIG5vdCBkb2NfaWQ6CiAg"
    "ICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkRvY3VtZW50IGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVf"
    "c2VydmljZXMoKQogICAgICAgIGRvYyA9IHNlbGYuX2RvY3Nfc2VydmljZS5kb2N1bWVudHMoKS5nZXQoZG9jdW1lbnRJZD1kb2Nf"
    "aWQpLmV4ZWN1dGUoKQogICAgICAgIHRpdGxlID0gZG9jLmdldCgidGl0bGUiKSBvciAiVW50aXRsZWQiCiAgICAgICAgYm9keSA9"
    "IGRvYy5nZXQoImJvZHkiLCB7fSkuZ2V0KCJjb250ZW50IiwgW10pCiAgICAgICAgY2h1bmtzID0gW10KICAgICAgICBmb3IgYmxv"
    "Y2sgaW4gYm9keToKICAgICAgICAgICAgcGFyYWdyYXBoID0gYmxvY2suZ2V0KCJwYXJhZ3JhcGgiKQogICAgICAgICAgICBpZiBu"
    "b3QgcGFyYWdyYXBoOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgZWxlbWVudHMgPSBwYXJhZ3JhcGguZ2V0"
    "KCJlbGVtZW50cyIsIFtdKQogICAgICAgICAgICBmb3IgZWwgaW4gZWxlbWVudHM6CiAgICAgICAgICAgICAgICBydW4gPSBlbC5n"
    "ZXQoInRleHRSdW4iKQogICAgICAgICAgICAgICAgaWYgbm90IHJ1bjoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAg"
    "ICAgICAgICAgICAgdGV4dCA9IChydW4uZ2V0KCJjb250ZW50Iikgb3IgIiIpLnJlcGxhY2UoIlx4MGIiLCAiXG4iKQogICAgICAg"
    "ICAgICAgICAgaWYgdGV4dDoKICAgICAgICAgICAgICAgICAgICBjaHVua3MuYXBwZW5kKHRleHQpCiAgICAgICAgcGFyc2VkID0g"
    "IiIuam9pbihjaHVua3MpLnN0cmlwKCkKICAgICAgICBpZiBsZW4ocGFyc2VkKSA+IG1heF9jaGFyczoKICAgICAgICAgICAgcGFy"
    "c2VkID0gcGFyc2VkWzptYXhfY2hhcnNdLnJzdHJpcCgpICsgIuKApiIKICAgICAgICByZXR1cm4gewogICAgICAgICAgICAidGl0"
    "bGUiOiB0aXRsZSwKICAgICAgICAgICAgImRvY3VtZW50X2lkIjogZG9jX2lkLAogICAgICAgICAgICAicmV2aXNpb25faWQiOiBk"
    "b2MuZ2V0KCJyZXZpc2lvbklkIiksCiAgICAgICAgICAgICJwcmV2aWV3X3RleHQiOiBwYXJzZWQgb3IgIltObyB0ZXh0IGNvbnRl"
    "bnQgcmV0dXJuZWQgZnJvbSBEb2NzIEFQSS5dIiwKICAgICAgICB9CgogICAgZGVmIGNyZWF0ZV9kb2Moc2VsZiwgdGl0bGU6IHN0"
    "ciA9ICJOZXcgR3JpbVZlaWxlIFJlY29yZCIsIHBhcmVudF9mb2xkZXJfaWQ6IHN0ciA9ICJyb290Iik6CiAgICAgICAgc2FmZV90"
    "aXRsZSA9ICh0aXRsZSBvciAiTmV3IEdyaW1WZWlsZSBSZWNvcmQiKS5zdHJpcCgpIG9yICJOZXcgR3JpbVZlaWxlIFJlY29yZCIK"
    "ICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgc2FmZV9wYXJlbnRfaWQgPSAocGFyZW50X2ZvbGRlcl9pZCBv"
    "ciAicm9vdCIpLnN0cmlwKCkgb3IgInJvb3QiCiAgICAgICAgY3JlYXRlZCA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5j"
    "cmVhdGUoCiAgICAgICAgICAgIGJvZHk9ewogICAgICAgICAgICAgICAgIm5hbWUiOiBzYWZlX3RpdGxlLAogICAgICAgICAgICAg"
    "ICAgIm1pbWVUeXBlIjogImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5kb2N1bWVudCIsCiAgICAgICAgICAgICAgICAicGFy"
    "ZW50cyI6IFtzYWZlX3BhcmVudF9pZF0sCiAgICAgICAgICAgIH0sCiAgICAgICAgICAgIGZpZWxkcz0iaWQsbmFtZSxtaW1lVHlw"
    "ZSxtb2RpZmllZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyIsCiAgICAgICAgKS5leGVjdXRlKCkKICAgICAgICBkb2NfaWQgPSBj"
    "cmVhdGVkLmdldCgiaWQiKQogICAgICAgIG1ldGEgPSBzZWxmLmdldF9maWxlX21ldGFkYXRhKGRvY19pZCkgaWYgZG9jX2lkIGVs"
    "c2Uge30KICAgICAgICByZXR1cm4gewogICAgICAgICAgICAiaWQiOiBkb2NfaWQsCiAgICAgICAgICAgICJuYW1lIjogbWV0YS5n"
    "ZXQoIm5hbWUiKSBvciBzYWZlX3RpdGxlLAogICAgICAgICAgICAibWltZVR5cGUiOiBtZXRhLmdldCgibWltZVR5cGUiKSBvciAi"
    "YXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IiwKICAgICAgICAgICAgIm1vZGlmaWVkVGltZSI6IG1ldGEuZ2V0"
    "KCJtb2RpZmllZFRpbWUiKSwKICAgICAgICAgICAgIndlYlZpZXdMaW5rIjogbWV0YS5nZXQoIndlYlZpZXdMaW5rIiksCiAgICAg"
    "ICAgICAgICJwYXJlbnRzIjogbWV0YS5nZXQoInBhcmVudHMiKSBvciBbc2FmZV9wYXJlbnRfaWRdLAogICAgICAgIH0KCiAgICBk"
    "ZWYgY3JlYXRlX2ZvbGRlcihzZWxmLCBuYW1lOiBzdHIgPSAiTmV3IEZvbGRlciIsIHBhcmVudF9mb2xkZXJfaWQ6IHN0ciA9ICJy"
    "b290Iik6CiAgICAgICAgc2FmZV9uYW1lID0gKG5hbWUgb3IgIk5ldyBGb2xkZXIiKS5zdHJpcCgpIG9yICJOZXcgRm9sZGVyIgog"
    "ICAgICAgIHNhZmVfcGFyZW50X2lkID0gKHBhcmVudF9mb2xkZXJfaWQgb3IgInJvb3QiKS5zdHJpcCgpIG9yICJyb290IgogICAg"
    "ICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBjcmVhdGVkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmNy"
    "ZWF0ZSgKICAgICAgICAgICAgYm9keT17CiAgICAgICAgICAgICAgICAibmFtZSI6IHNhZmVfbmFtZSwKICAgICAgICAgICAgICAg"
    "ICJtaW1lVHlwZSI6ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVyIiwKICAgICAgICAgICAgICAgICJwYXJlbnRz"
    "IjogW3NhZmVfcGFyZW50X2lkXSwKICAgICAgICAgICAgfSwKICAgICAgICAgICAgZmllbGRzPSJpZCxuYW1lLG1pbWVUeXBlLG1v"
    "ZGlmaWVkVGltZSx3ZWJWaWV3TGluayxwYXJlbnRzIiwKICAgICAgICApLmV4ZWN1dGUoKQogICAgICAgIHJldHVybiBjcmVhdGVk"
    "CgogICAgZGVmIGdldF9maWxlX21ldGFkYXRhKHNlbGYsIGZpbGVfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGZpbGVfaWQ6CiAg"
    "ICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkZpbGUgaWQgaXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2"
    "aWNlcygpCiAgICAgICAgcmV0dXJuIHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5nZXQoCiAgICAgICAgICAgIGZpbGVJZD1m"
    "aWxlX2lkLAogICAgICAgICAgICBmaWVsZHM9ImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVu"
    "dHMsc2l6ZSIsCiAgICAgICAgKS5leGVjdXRlKCkKCiAgICBkZWYgZ2V0X2RvY19tZXRhZGF0YShzZWxmLCBkb2NfaWQ6IHN0cik6"
    "CiAgICAgICAgcmV0dXJuIHNlbGYuZ2V0X2ZpbGVfbWV0YWRhdGEoZG9jX2lkKQoKICAgIGRlZiBkZWxldGVfaXRlbShzZWxmLCBm"
    "aWxlX2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBmaWxlX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlk"
    "IGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHNlbGYuX2RyaXZlX3NlcnZpY2Uu"
    "ZmlsZXMoKS5kZWxldGUoZmlsZUlkPWZpbGVfaWQpLmV4ZWN1dGUoKQoKICAgIGRlZiBkZWxldGVfZG9jKHNlbGYsIGRvY19pZDog"
    "c3RyKToKICAgICAgICBzZWxmLmRlbGV0ZV9pdGVtKGRvY19pZCkKCiAgICBkZWYgZXhwb3J0X2RvY190ZXh0KHNlbGYsIGRvY19p"
    "ZDogc3RyKToKICAgICAgICBpZiBub3QgZG9jX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJEb2N1bWVudCBpZCBp"
    "cyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBwYXlsb2FkID0gc2VsZi5fZHJpdmVf"
    "c2VydmljZS5maWxlcygpLmV4cG9ydCgKICAgICAgICAgICAgZmlsZUlkPWRvY19pZCwKICAgICAgICAgICAgbWltZVR5cGU9InRl"
    "eHQvcGxhaW4iLAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAgaWYgaXNpbnN0YW5jZShwYXlsb2FkLCBieXRlcyk6CiAgICAg"
    "ICAgICAgIHJldHVybiBwYXlsb2FkLmRlY29kZSgidXRmLTgiLCBlcnJvcnM9InJlcGxhY2UiKQogICAgICAgIHJldHVybiBzdHIo"
    "cGF5bG9hZCBvciAiIikKCiAgICBkZWYgZG93bmxvYWRfZmlsZV9ieXRlcyhzZWxmLCBmaWxlX2lkOiBzdHIpOgogICAgICAgIGlm"
    "IG5vdCBmaWxlX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAg"
    "c2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHJldHVybiBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuZ2V0X21lZGlh"
    "KGZpbGVJZD1maWxlX2lkKS5leGVjdXRlKCkKCgoKCiMg4pSA4pSAIFBBU1MgMyBDT01QTEVURSDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKIyBBbGwgd29ya2VyIHRocmVhZHMgZGVmaW5lZC4gQWxsIGdlbmVyYXRpb24gaXMgc3RyZWFtaW5nLgojIE5vIGJs"
    "b2NraW5nIGNhbGxzIG9uIG1haW4gdGhyZWFkIGFueXdoZXJlIGluIHRoaXMgZmlsZS4KIwojIE5leHQ6IFBhc3MgNCDigJQgTWVt"
    "b3J5ICYgU3RvcmFnZQojIChNZW1vcnlNYW5hZ2VyLCBTZXNzaW9uTWFuYWdlciwgTGVzc29uc0xlYXJuZWREQiwgVGFza01hbmFn"
    "ZXIpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDQ6IE1FTU9SWSAmIFNUT1JBR0UKIwojIFN5c3Rl"
    "bXMgZGVmaW5lZCBoZXJlOgojICAgRGVwZW5kZW5jeUNoZWNrZXIgICDigJQgdmFsaWRhdGVzIGFsbCByZXF1aXJlZCBwYWNrYWdl"
    "cyBvbiBzdGFydHVwCiMgICBNZW1vcnlNYW5hZ2VyICAgICAgIOKAlCBKU09OTCBtZW1vcnkgcmVhZC93cml0ZS9zZWFyY2gKIyAg"
    "IFNlc3Npb25NYW5hZ2VyICAgICAg4oCUIGF1dG8tc2F2ZSwgbG9hZCwgY29udGV4dCBpbmplY3Rpb24sIHNlc3Npb24gaW5kZXgK"
    "IyAgIExlc3NvbnNMZWFybmVkREIgICAg4oCUIExTTCBGb3JiaWRkZW4gUnVsZXNldCArIGNvZGUgbGVzc29ucyBrbm93bGVkZ2Ug"
    "YmFzZQojICAgVGFza01hbmFnZXIgICAgICAgICDigJQgdGFzay9yZW1pbmRlciBDUlVELCBkdWUtZXZlbnQgZGV0ZWN0aW9uCiMg"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQCgoKIyDilIDilIAgREVQRU5ERU5DWSBDSEVDS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEZXBlbmRl"
    "bmN5Q2hlY2tlcjoKICAgICIiIgogICAgVmFsaWRhdGVzIGFsbCByZXF1aXJlZCBhbmQgb3B0aW9uYWwgcGFja2FnZXMgb24gc3Rh"
    "cnR1cC4KICAgIFJldHVybnMgYSBsaXN0IG9mIHN0YXR1cyBtZXNzYWdlcyBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgIFNo"
    "b3dzIGEgYmxvY2tpbmcgZXJyb3IgZGlhbG9nIGZvciBhbnkgY3JpdGljYWwgbWlzc2luZyBkZXBlbmRlbmN5LgogICAgIiIiCgog"
    "ICAgIyAocGFja2FnZV9uYW1lLCBpbXBvcnRfbmFtZSwgY3JpdGljYWwsIGluc3RhbGxfaGludCkKICAgIFBBQ0tBR0VTID0gWwog"
    "ICAgICAgICgiUHlTaWRlNiIsICAgICAgICAgICAgICAgICAgICJQeVNpZGU2IiwgICAgICAgICAgICAgIFRydWUsCiAgICAgICAg"
    "ICJwaXAgaW5zdGFsbCBQeVNpZGU2IiksCiAgICAgICAgKCJsb2d1cnUiLCAgICAgICAgICAgICAgICAgICAgImxvZ3VydSIsICAg"
    "ICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGxvZ3VydSIpLAogICAgICAgICgiYXBzY2hlZHVsZXIiLCAg"
    "ICAgICAgICAgICAgICJhcHNjaGVkdWxlciIsICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBhcHNjaGVkdWxl"
    "ciIpLAogICAgICAgICgicHlnYW1lIiwgICAgICAgICAgICAgICAgICAgICJweWdhbWUiLCAgICAgICAgICAgICAgIEZhbHNlLAog"
    "ICAgICAgICAicGlwIGluc3RhbGwgcHlnYW1lICAobmVlZGVkIGZvciBzb3VuZCkiKSwKICAgICAgICAoInB5d2luMzIiLCAgICAg"
    "ICAgICAgICAgICAgICAid2luMzJjb20iLCAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5d2luMzIg"
    "IChuZWVkZWQgZm9yIGRlc2t0b3Agc2hvcnRjdXQpIiksCiAgICAgICAgKCJwc3V0aWwiLCAgICAgICAgICAgICAgICAgICAgInBz"
    "dXRpbCIsICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBwc3V0aWwgIChuZWVkZWQgZm9yIHN5c3Rl"
    "bSBtb25pdG9yaW5nKSIpLAogICAgICAgICgicmVxdWVzdHMiLCAgICAgICAgICAgICAgICAgICJyZXF1ZXN0cyIsICAgICAgICAg"
    "ICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcmVxdWVzdHMiKSwKICAgICAgICAoImdvb2dsZS1hcGktcHl0aG9uLWNs"
    "aWVudCIsICAiZ29vZ2xlYXBpY2xpZW50IiwgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGdvb2dsZS1hcGktcHl0"
    "aG9uLWNsaWVudCIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgtb2F1dGhsaWIiLCAgICAgICJnb29nbGVfYXV0aF9vYXV0aGxpYiIs"
    "IEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgZ29vZ2xlLWF1dGgtb2F1dGhsaWIiKSwKICAgICAgICAoImdvb2dsZS1hdXRo"
    "IiwgICAgICAgICAgICAgICAiZ29vZ2xlLmF1dGgiLCAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGdvb2ds"
    "ZS1hdXRoIiksCiAgICAgICAgKCJ0b3JjaCIsICAgICAgICAgICAgICAgICAgICAgInRvcmNoIiwgICAgICAgICAgICAgICAgRmFs"
    "c2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCB0b3JjaCAgKG9ubHkgbmVlZGVkIGZvciBsb2NhbCBtb2RlbCkiKSwKICAgICAgICAo"
    "InRyYW5zZm9ybWVycyIsICAgICAgICAgICAgICAidHJhbnNmb3JtZXJzIiwgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBp"
    "bnN0YWxsIHRyYW5zZm9ybWVycyAgKG9ubHkgbmVlZGVkIGZvciBsb2NhbCBtb2RlbCkiKSwKICAgICAgICAoInB5bnZtbCIsICAg"
    "ICAgICAgICAgICAgICAgICAicHludm1sIiwgICAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5bnZt"
    "bCAgKG9ubHkgbmVlZGVkIGZvciBOVklESUEgR1BVIG1vbml0b3JpbmcpIiksCiAgICBdCgogICAgQGNsYXNzbWV0aG9kCiAgICBk"
    "ZWYgY2hlY2soY2xzKSAtPiB0dXBsZVtsaXN0W3N0cl0sIGxpc3Rbc3RyXV06CiAgICAgICAgIiIiCiAgICAgICAgUmV0dXJucyAo"
    "bWVzc2FnZXMsIGNyaXRpY2FsX2ZhaWx1cmVzKS4KICAgICAgICBtZXNzYWdlczogbGlzdCBvZiAiW0RFUFNdIHBhY2thZ2Ug4pyT"
    "L+KclyDigJQgbm90ZSIgc3RyaW5ncwogICAgICAgIGNyaXRpY2FsX2ZhaWx1cmVzOiBsaXN0IG9mIHBhY2thZ2VzIHRoYXQgYXJl"
    "IGNyaXRpY2FsIGFuZCBtaXNzaW5nCiAgICAgICAgIiIiCiAgICAgICAgaW1wb3J0IGltcG9ydGxpYgogICAgICAgIG1lc3NhZ2Vz"
    "ICA9IFtdCiAgICAgICAgY3JpdGljYWwgID0gW10KCiAgICAgICAgZm9yIHBrZ19uYW1lLCBpbXBvcnRfbmFtZSwgaXNfY3JpdGlj"
    "YWwsIGhpbnQgaW4gY2xzLlBBQ0tBR0VTOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpbXBvcnRsaWIuaW1wb3J0"
    "X21vZHVsZShpbXBvcnRfbmFtZSkKICAgICAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZChmIltERVBTXSB7cGtnX25hbWV9IOKc"
    "kyIpCiAgICAgICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgICAgIHN0YXR1cyA9ICJDUklUSUNBTCIgaWYg"
    "aXNfY3JpdGljYWwgZWxzZSAib3B0aW9uYWwiCiAgICAgICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAg"
    "ICAgICAgZiJbREVQU10ge3BrZ19uYW1lfSDinJcgKHtzdGF0dXN9KSDigJQge2hpbnR9IgogICAgICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICAgICAgaWYgaXNfY3JpdGljYWw6CiAgICAgICAgICAgICAgICAgICAgY3JpdGljYWwuYXBwZW5kKHBrZ19uYW1lKQoK"
    "ICAgICAgICByZXR1cm4gbWVzc2FnZXMsIGNyaXRpY2FsCgogICAgQGNsYXNzbWV0aG9kCiAgICBkZWYgY2hlY2tfb2xsYW1hKGNs"
    "cykgLT4gc3RyOgogICAgICAgICIiIkNoZWNrIGlmIE9sbGFtYSBpcyBydW5uaW5nLiBSZXR1cm5zIHN0YXR1cyBzdHJpbmcuIiIi"
    "CiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXEgID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdCgiaHR0cDovL2xvY2FsaG9zdDox"
    "MTQzNC9hcGkvdGFncyIpCiAgICAgICAgICAgIHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0yKQog"
    "ICAgICAgICAgICBpZiByZXNwLnN0YXR1cyA9PSAyMDA6CiAgICAgICAgICAgICAgICByZXR1cm4gIltERVBTXSBPbGxhbWEg4pyT"
    "IOKAlCBydW5uaW5nIG9uIGxvY2FsaG9zdDoxMTQzNCIKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNz"
    "CiAgICAgICAgcmV0dXJuICJbREVQU10gT2xsYW1hIOKclyDigJQgbm90IHJ1bm5pbmcgKG9ubHkgbmVlZGVkIGZvciBPbGxhbWEg"
    "bW9kZWwgdHlwZSkiCgoKIyDilIDilIAgTUVNT1JZIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNz"
    "IE1lbW9yeU1hbmFnZXI6CiAgICAiIiIKICAgIEhhbmRsZXMgYWxsIEpTT05MIG1lbW9yeSBvcGVyYXRpb25zLgoKICAgIEZpbGVz"
    "IG1hbmFnZWQ6CiAgICAgICAgbWVtb3JpZXMvbWVzc2FnZXMuanNvbmwgICAgICAgICDigJQgZXZlcnkgbWVzc2FnZSwgdGltZXN0"
    "YW1wZWQKICAgICAgICBtZW1vcmllcy9tZW1vcmllcy5qc29ubCAgICAgICAgIOKAlCBleHRyYWN0ZWQgbWVtb3J5IHJlY29yZHMK"
    "ICAgICAgICBtZW1vcmllcy9zdGF0ZS5qc29uICAgICAgICAgICAgIOKAlCBlbnRpdHkgc3RhdGUKICAgICAgICBtZW1vcmllcy9p"
    "bmRleC5qc29uICAgICAgICAgICAgIOKAlCBjb3VudHMgYW5kIG1ldGFkYXRhCgogICAgTWVtb3J5IHJlY29yZHMgaGF2ZSB0eXBl"
    "IGluZmVyZW5jZSwga2V5d29yZCBleHRyYWN0aW9uLCB0YWcgZ2VuZXJhdGlvbiwKICAgIG5lYXItZHVwbGljYXRlIGRldGVjdGlv"
    "biwgYW5kIHJlbGV2YW5jZSBzY29yaW5nIGZvciBjb250ZXh0IGluamVjdGlvbi4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhz"
    "ZWxmKToKICAgICAgICBiYXNlICAgICAgICAgICAgID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikKICAgICAgICBzZWxmLm1lc3NhZ2Vz"
    "X3AgID0gYmFzZSAvICJtZXNzYWdlcy5qc29ubCIKICAgICAgICBzZWxmLm1lbW9yaWVzX3AgID0gYmFzZSAvICJtZW1vcmllcy5q"
    "c29ubCIKICAgICAgICBzZWxmLnN0YXRlX3AgICAgID0gYmFzZSAvICJzdGF0ZS5qc29uIgogICAgICAgIHNlbGYuaW5kZXhfcCAg"
    "ICAgPSBiYXNlIC8gImluZGV4Lmpzb24iCgogICAgIyDilIDilIAgU1RBVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBk"
    "ZWYgbG9hZF9zdGF0ZShzZWxmKSAtPiBkaWN0OgogICAgICAgIGlmIG5vdCBzZWxmLnN0YXRlX3AuZXhpc3RzKCk6CiAgICAgICAg"
    "ICAgIHJldHVybiBzZWxmLl9kZWZhdWx0X3N0YXRlKCkKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVybiBqc29uLmxvYWRz"
    "KHNlbGYuc3RhdGVfcC5yZWFkX3RleHQoZW5jb2Rpbmc9InV0Zi04IikpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAg"
    "ICAgICAgcmV0dXJuIHNlbGYuX2RlZmF1bHRfc3RhdGUoKQoKICAgIGRlZiBzYXZlX3N0YXRlKHNlbGYsIHN0YXRlOiBkaWN0KSAt"
    "PiBOb25lOgogICAgICAgIHNlbGYuc3RhdGVfcC53cml0ZV90ZXh0KAogICAgICAgICAgICBqc29uLmR1bXBzKHN0YXRlLCBpbmRl"
    "bnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICApCgogICAgZGVmIF9kZWZhdWx0X3N0YXRlKHNlbGYpIC0+IGRpY3Q6CiAg"
    "ICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgInBlcnNvbmFfbmFtZSI6ICAgICAgICAgICAgIERFQ0tfTkFNRSwKICAgICAgICAg"
    "ICAgImRlY2tfdmVyc2lvbiI6ICAgICAgICAgICAgIEFQUF9WRVJTSU9OLAogICAgICAgICAgICAic2Vzc2lvbl9jb3VudCI6ICAg"
    "ICAgICAgICAgMCwKICAgICAgICAgICAgImxhc3Rfc3RhcnR1cCI6ICAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgICJsYXN0"
    "X3NodXRkb3duIjogICAgICAgICAgICBOb25lLAogICAgICAgICAgICAibGFzdF9hY3RpdmUiOiAgICAgICAgICAgICAgTm9uZSwK"
    "ICAgICAgICAgICAgInRvdGFsX21lc3NhZ2VzIjogICAgICAgICAgIDAsCiAgICAgICAgICAgICJ0b3RhbF9tZW1vcmllcyI6ICAg"
    "ICAgICAgICAwLAogICAgICAgICAgICAiaW50ZXJuYWxfbmFycmF0aXZlIjogICAgICAge30sCiAgICAgICAgICAgICJ2YW1waXJl"
    "X3N0YXRlX2F0X3NodXRkb3duIjoiRE9STUFOVCIsCiAgICAgICAgfQoKICAgICMg4pSA4pSAIE1FU1NBR0VTIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgZGVmIGFwcGVuZF9tZXNzYWdlKHNlbGYsIHNlc3Npb25faWQ6IHN0ciwgcm9sZTogc3RyLAogICAgICAgICAgICAg"
    "ICAgICAgICAgIGNvbnRlbnQ6IHN0ciwgZW1vdGlvbjogc3RyID0gIiIpIC0+IGRpY3Q6CiAgICAgICAgcmVjb3JkID0gewogICAg"
    "ICAgICAgICAiaWQiOiAgICAgICAgIGYibXNnX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFt"
    "cCI6ICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICJzZXNzaW9uX2lkIjogc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBl"
    "cnNvbmEiOiAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJyb2xlIjogICAgICAgcm9sZSwKICAgICAgICAgICAgImNvbnRlbnQi"
    "OiAgICBjb250ZW50LAogICAgICAgICAgICAiZW1vdGlvbiI6ICAgIGVtb3Rpb24sCiAgICAgICAgfQogICAgICAgIGFwcGVuZF9q"
    "c29ubChzZWxmLm1lc3NhZ2VzX3AsIHJlY29yZCkKICAgICAgICByZXR1cm4gcmVjb3JkCgogICAgZGVmIGxvYWRfcmVjZW50X21l"
    "c3NhZ2VzKHNlbGYsIGxpbWl0OiBpbnQgPSAyMCkgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChzZWxm"
    "Lm1lc3NhZ2VzX3ApWy1saW1pdDpdCgogICAgIyDilIDilIAgTUVNT1JJRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgYXBwZW5k"
    "X21lbW9yeShzZWxmLCBzZXNzaW9uX2lkOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgICAgYXNzaXN0"
    "YW50X3RleHQ6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgcmVjb3JkX3R5cGUgPSBpbmZlcl9yZWNvcmRfdHlwZSh1"
    "c2VyX3RleHQsIGFzc2lzdGFudF90ZXh0KQogICAgICAgIGtleXdvcmRzICAgID0gZXh0cmFjdF9rZXl3b3Jkcyh1c2VyX3RleHQg"
    "KyAiICIgKyBhc3Npc3RhbnRfdGV4dCkKICAgICAgICB0YWdzICAgICAgICA9IHNlbGYuX2luZmVyX3RhZ3MocmVjb3JkX3R5cGUs"
    "IHVzZXJfdGV4dCwga2V5d29yZHMpCiAgICAgICAgdGl0bGUgICAgICAgPSBzZWxmLl9pbmZlcl90aXRsZShyZWNvcmRfdHlwZSwg"
    "dXNlcl90ZXh0LCBrZXl3b3JkcykKICAgICAgICBzdW1tYXJ5ICAgICA9IHNlbGYuX3N1bW1hcml6ZShyZWNvcmRfdHlwZSwgdXNl"
    "cl90ZXh0LCBhc3Npc3RhbnRfdGV4dCkKCiAgICAgICAgbWVtb3J5ID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICAg"
    "IGYibWVtX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6ICAgICAgICBsb2NhbF9ub3df"
    "aXNvKCksCiAgICAgICAgICAgICJzZXNzaW9uX2lkIjogICAgICAgc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEiOiAg"
    "ICAgICAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJ0eXBlIjogICAgICAgICAgICAgcmVjb3JkX3R5cGUsCiAgICAgICAgICAg"
    "ICJ0aXRsZSI6ICAgICAgICAgICAgdGl0bGUsCiAgICAgICAgICAgICJzdW1tYXJ5IjogICAgICAgICAgc3VtbWFyeSwKICAgICAg"
    "ICAgICAgImNvbnRlbnQiOiAgICAgICAgICB1c2VyX3RleHRbOjQwMDBdLAogICAgICAgICAgICAiYXNzaXN0YW50X2NvbnRleHQi"
    "OmFzc2lzdGFudF90ZXh0WzoxMjAwXSwKICAgICAgICAgICAgImtleXdvcmRzIjogICAgICAgICBrZXl3b3JkcywKICAgICAgICAg"
    "ICAgInRhZ3MiOiAgICAgICAgICAgICB0YWdzLAogICAgICAgICAgICAiY29uZmlkZW5jZSI6ICAgICAgIDAuNzAgaWYgcmVjb3Jk"
    "X3R5cGUgaW4gewogICAgICAgICAgICAgICAgImRyZWFtIiwiaXNzdWUiLCJpZGVhIiwicHJlZmVyZW5jZSIsInJlc29sdXRpb24i"
    "CiAgICAgICAgICAgIH0gZWxzZSAwLjU1LAogICAgICAgIH0KCiAgICAgICAgaWYgc2VsZi5faXNfbmVhcl9kdXBsaWNhdGUobWVt"
    "b3J5KToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgYXBwZW5kX2pzb25sKHNlbGYubWVtb3JpZXNfcCwgbWVtb3J5"
    "KQogICAgICAgIHJldHVybiBtZW1vcnkKCiAgICBkZWYgc2VhcmNoX21lbW9yaWVzKHNlbGYsIHF1ZXJ5OiBzdHIsIGxpbWl0OiBp"
    "bnQgPSA2KSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIiIgogICAgICAgIEtleXdvcmQtc2NvcmVkIG1lbW9yeSBzZWFyY2guCiAg"
    "ICAgICAgUmV0dXJucyB1cCB0byBgbGltaXRgIHJlY29yZHMgc29ydGVkIGJ5IHJlbGV2YW5jZSBzY29yZSBkZXNjZW5kaW5nLgog"
    "ICAgICAgIEZhbGxzIGJhY2sgdG8gbW9zdCByZWNlbnQgaWYgbm8gcXVlcnkgdGVybXMgbWF0Y2guCiAgICAgICAgIiIiCiAgICAg"
    "ICAgbWVtb3JpZXMgPSByZWFkX2pzb25sKHNlbGYubWVtb3JpZXNfcCkKICAgICAgICBpZiBub3QgcXVlcnkuc3RyaXAoKToKICAg"
    "ICAgICAgICAgcmV0dXJuIG1lbW9yaWVzWy1saW1pdDpdCgogICAgICAgIHFfdGVybXMgPSBzZXQoZXh0cmFjdF9rZXl3b3Jkcyhx"
    "dWVyeSwgbGltaXQ9MTYpKQogICAgICAgIHNjb3JlZCAgPSBbXQoKICAgICAgICBmb3IgaXRlbSBpbiBtZW1vcmllczoKICAgICAg"
    "ICAgICAgaXRlbV90ZXJtcyA9IHNldChleHRyYWN0X2tleXdvcmRzKCIgIi5qb2luKFsKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0"
    "KCJ0aXRsZSIsICAgIiIpLAogICAgICAgICAgICAgICAgaXRlbS5nZXQoInN1bW1hcnkiLCAiIiksCiAgICAgICAgICAgICAgICBp"
    "dGVtLmdldCgiY29udGVudCIsICIiKSwKICAgICAgICAgICAgICAgICIgIi5qb2luKGl0ZW0uZ2V0KCJrZXl3b3JkcyIsIFtdKSks"
    "CiAgICAgICAgICAgICAgICAiICIuam9pbihpdGVtLmdldCgidGFncyIsICAgICBbXSkpLAogICAgICAgICAgICBdKSwgbGltaXQ9"
    "NDApKQoKICAgICAgICAgICAgc2NvcmUgPSBsZW4ocV90ZXJtcyAmIGl0ZW1fdGVybXMpCgogICAgICAgICAgICAjIEJvb3N0IGJ5"
    "IHR5cGUgbWF0Y2gKICAgICAgICAgICAgcWwgPSBxdWVyeS5sb3dlcigpCiAgICAgICAgICAgIHJ0ID0gaXRlbS5nZXQoInR5cGUi"
    "LCAiIikKICAgICAgICAgICAgaWYgImRyZWFtIiAgaW4gcWwgYW5kIHJ0ID09ICJkcmVhbSI6ICAgIHNjb3JlICs9IDQKICAgICAg"
    "ICAgICAgaWYgInRhc2siICAgaW4gcWwgYW5kIHJ0ID09ICJ0YXNrIjogICAgIHNjb3JlICs9IDMKICAgICAgICAgICAgaWYgImlk"
    "ZWEiICAgaW4gcWwgYW5kIHJ0ID09ICJpZGVhIjogICAgIHNjb3JlICs9IDIKICAgICAgICAgICAgaWYgImxzbCIgICAgaW4gcWwg"
    "YW5kIHJ0IGluIHsiaXNzdWUiLCJyZXNvbHV0aW9uIn06IHNjb3JlICs9IDIKCiAgICAgICAgICAgIGlmIHNjb3JlID4gMDoKICAg"
    "ICAgICAgICAgICAgIHNjb3JlZC5hcHBlbmQoKHNjb3JlLCBpdGVtKSkKCiAgICAgICAgc2NvcmVkLnNvcnQoa2V5PWxhbWJkYSB4"
    "OiAoeFswXSwgeFsxXS5nZXQoInRpbWVzdGFtcCIsICIiKSksCiAgICAgICAgICAgICAgICAgICAgcmV2ZXJzZT1UcnVlKQogICAg"
    "ICAgIHJldHVybiBbaXRlbSBmb3IgXywgaXRlbSBpbiBzY29yZWRbOmxpbWl0XV0KCiAgICBkZWYgYnVpbGRfY29udGV4dF9ibG9j"
    "ayhzZWxmLCBxdWVyeTogc3RyLCBtYXhfY2hhcnM6IGludCA9IDIwMDApIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBCdWls"
    "ZCBhIGNvbnRleHQgc3RyaW5nIGZyb20gcmVsZXZhbnQgbWVtb3JpZXMgZm9yIHByb21wdCBpbmplY3Rpb24uCiAgICAgICAgVHJ1"
    "bmNhdGVzIHRvIG1heF9jaGFycyB0byBwcm90ZWN0IHRoZSBjb250ZXh0IHdpbmRvdy4KICAgICAgICAiIiIKICAgICAgICBtZW1v"
    "cmllcyA9IHNlbGYuc2VhcmNoX21lbW9yaWVzKHF1ZXJ5LCBsaW1pdD00KQogICAgICAgIGlmIG5vdCBtZW1vcmllczoKICAgICAg"
    "ICAgICAgcmV0dXJuICIiCgogICAgICAgIHBhcnRzID0gWyJbUkVMRVZBTlQgTUVNT1JJRVNdIl0KICAgICAgICB0b3RhbCA9IDAK"
    "ICAgICAgICBmb3IgbSBpbiBtZW1vcmllczoKICAgICAgICAgICAgZW50cnkgPSAoCiAgICAgICAgICAgICAgICBmIuKAoiBbe20u"
    "Z2V0KCd0eXBlJywnJykudXBwZXIoKX1dIHttLmdldCgndGl0bGUnLCcnKX06ICIKICAgICAgICAgICAgICAgIGYie20uZ2V0KCdz"
    "dW1tYXJ5JywnJyl9IgogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIHRvdGFsICsgbGVuKGVudHJ5KSA+IG1heF9jaGFyczoK"
    "ICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChlbnRyeSkKICAgICAgICAgICAgdG90YWwgKz0g"
    "bGVuKGVudHJ5KQoKICAgICAgICBwYXJ0cy5hcHBlbmQoIltFTkQgTUVNT1JJRVNdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2lu"
    "KHBhcnRzKQoKICAgICMg4pSA4pSAIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2lzX25lYXJfZHVwbGljYXRl"
    "KHNlbGYsIGNhbmRpZGF0ZTogZGljdCkgLT4gYm9vbDoKICAgICAgICByZWNlbnQgPSByZWFkX2pzb25sKHNlbGYubWVtb3JpZXNf"
    "cClbLTI1Ol0KICAgICAgICBjdCA9IGNhbmRpZGF0ZS5nZXQoInRpdGxlIiwgIiIpLmxvd2VyKCkuc3RyaXAoKQogICAgICAgIGNz"
    "ID0gY2FuZGlkYXRlLmdldCgic3VtbWFyeSIsICIiKS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBmb3IgaXRlbSBpbiByZWNlbnQ6"
    "CiAgICAgICAgICAgIGlmIGl0ZW0uZ2V0KCJ0aXRsZSIsIiIpLmxvd2VyKCkuc3RyaXAoKSA9PSBjdDogIHJldHVybiBUcnVlCiAg"
    "ICAgICAgICAgIGlmIGl0ZW0uZ2V0KCJzdW1tYXJ5IiwiIikubG93ZXIoKS5zdHJpcCgpID09IGNzOiByZXR1cm4gVHJ1ZQogICAg"
    "ICAgIHJldHVybiBGYWxzZQoKICAgIGRlZiBfaW5mZXJfdGFncyhzZWxmLCByZWNvcmRfdHlwZTogc3RyLCB0ZXh0OiBzdHIsCiAg"
    "ICAgICAgICAgICAgICAgICAga2V5d29yZHM6IGxpc3Rbc3RyXSkgLT4gbGlzdFtzdHJdOgogICAgICAgIHQgICAgPSB0ZXh0Lmxv"
    "d2VyKCkKICAgICAgICB0YWdzID0gW3JlY29yZF90eXBlXQogICAgICAgIGlmICJkcmVhbSIgICBpbiB0OiB0YWdzLmFwcGVuZCgi"
    "ZHJlYW0iKQogICAgICAgIGlmICJsc2wiICAgICBpbiB0OiB0YWdzLmFwcGVuZCgibHNsIikKICAgICAgICBpZiAicHl0aG9uIiAg"
    "aW4gdDogdGFncy5hcHBlbmQoInB5dGhvbiIpCiAgICAgICAgaWYgImdhbWUiICAgIGluIHQ6IHRhZ3MuYXBwZW5kKCJnYW1lX2lk"
    "ZWEiKQogICAgICAgIGlmICJzbCIgICAgICBpbiB0IG9yICJzZWNvbmQgbGlmZSIgaW4gdDogdGFncy5hcHBlbmQoInNlY29uZGxp"
    "ZmUiKQogICAgICAgIGlmIERFQ0tfTkFNRS5sb3dlcigpIGluIHQ6IHRhZ3MuYXBwZW5kKERFQ0tfTkFNRS5sb3dlcigpKQogICAg"
    "ICAgIGZvciBrdyBpbiBrZXl3b3Jkc1s6NF06CiAgICAgICAgICAgIGlmIGt3IG5vdCBpbiB0YWdzOgogICAgICAgICAgICAgICAg"
    "dGFncy5hcHBlbmQoa3cpCiAgICAgICAgIyBEZWR1cGxpY2F0ZSBwcmVzZXJ2aW5nIG9yZGVyCiAgICAgICAgc2Vlbiwgb3V0ID0g"
    "c2V0KCksIFtdCiAgICAgICAgZm9yIHRhZyBpbiB0YWdzOgogICAgICAgICAgICBpZiB0YWcgbm90IGluIHNlZW46CiAgICAgICAg"
    "ICAgICAgICBzZWVuLmFkZCh0YWcpCiAgICAgICAgICAgICAgICBvdXQuYXBwZW5kKHRhZykKICAgICAgICByZXR1cm4gb3V0Wzox"
    "Ml0KCiAgICBkZWYgX2luZmVyX3RpdGxlKHNlbGYsIHJlY29yZF90eXBlOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAg"
    "ICAgICAgICAgICBrZXl3b3JkczogbGlzdFtzdHJdKSAtPiBzdHI6CiAgICAgICAgZGVmIGNsZWFuKHdvcmRzKToKICAgICAgICAg"
    "ICAgcmV0dXJuIFt3LnN0cmlwKCIgLV8uLCE/IikuY2FwaXRhbGl6ZSgpCiAgICAgICAgICAgICAgICAgICAgZm9yIHcgaW4gd29y"
    "ZHMgaWYgbGVuKHcpID4gMl0KCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInRhc2siOgogICAgICAgICAgICBpbXBvcnQgcmUK"
    "ICAgICAgICAgICAgbSA9IHJlLnNlYXJjaChyInJlbWluZCBtZSAuKj8gdG8gKC4rKSIsIHVzZXJfdGV4dCwgcmUuSSkKICAgICAg"
    "ICAgICAgaWYgbToKICAgICAgICAgICAgICAgIHJldHVybiBmIlJlbWluZGVyOiB7bS5ncm91cCgxKS5zdHJpcCgpWzo2MF19Igog"
    "ICAgICAgICAgICByZXR1cm4gIlJlbWluZGVyIFRhc2siCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImRyZWFtIjoKICAgICAg"
    "ICAgICAgcmV0dXJuIGYieycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzozXSkpfSBEcmVhbSIuc3RyaXAoKSBvciAiRHJlYW0gTWVt"
    "b3J5IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpc3N1ZSI6CiAgICAgICAgICAgIHJldHVybiBmIklzc3VlOiB7JyAnLmpv"
    "aW4oY2xlYW4oa2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJUZWNobmljYWwgSXNzdWUiCiAgICAgICAgaWYgcmVjb3JkX3R5"
    "cGUgPT0gInJlc29sdXRpb24iOgogICAgICAgICAgICByZXR1cm4gZiJSZXNvbHV0aW9uOiB7JyAnLmpvaW4oY2xlYW4oa2V5d29y"
    "ZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJUZWNobmljYWwgUmVzb2x1dGlvbiIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaWRl"
    "YSI6CiAgICAgICAgICAgIHJldHVybiBmIklkZWE6IHsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0pKX0iLnN0cmlwKCkgb3Ig"
    "IklkZWEiCiAgICAgICAgaWYga2V5d29yZHM6CiAgICAgICAgICAgIHJldHVybiAiICIuam9pbihjbGVhbihrZXl3b3Jkc1s6NV0p"
    "KSBvciAiQ29udmVyc2F0aW9uIE1lbW9yeSIKICAgICAgICByZXR1cm4gIkNvbnZlcnNhdGlvbiBNZW1vcnkiCgogICAgZGVmIF9z"
    "dW1tYXJpemUoc2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwgdXNlcl90ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICBhc3Npc3Rh"
    "bnRfdGV4dDogc3RyKSAtPiBzdHI6CiAgICAgICAgdSA9IHVzZXJfdGV4dC5zdHJpcCgpWzoyMjBdCiAgICAgICAgYSA9IGFzc2lz"
    "dGFudF90ZXh0LnN0cmlwKClbOjIyMF0KICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiZHJlYW0iOiAgICAgICByZXR1cm4gZiJV"
    "c2VyIGRlc2NyaWJlZCBhIGRyZWFtOiB7dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInRhc2siOiAgICAgICAgcmV0dXJu"
    "IGYiUmVtaW5kZXIvdGFzazoge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpc3N1ZSI6ICAgICAgIHJldHVybiBmIlRl"
    "Y2huaWNhbCBpc3N1ZToge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJyZXNvbHV0aW9uIjogIHJldHVybiBmIlNvbHV0"
    "aW9uIHJlY29yZGVkOiB7YSBvciB1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaWRlYSI6ICAgICAgICByZXR1cm4gZiJJ"
    "ZGVhIGRpc2N1c3NlZDoge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJwcmVmZXJlbmNlIjogIHJldHVybiBmIlByZWZl"
    "cmVuY2Ugbm90ZWQ6IHt1fSIKICAgICAgICByZXR1cm4gZiJDb252ZXJzYXRpb246IHt1fSIKCgojIOKUgOKUgCBTRVNTSU9OIE1B"
    "TkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNlc3Npb25NYW5hZ2VyOgogICAgIiIiCiAgICBNYW5hZ2Vz"
    "IGNvbnZlcnNhdGlvbiBzZXNzaW9ucy4KCiAgICBBdXRvLXNhdmU6IGV2ZXJ5IDEwIG1pbnV0ZXMgKEFQU2NoZWR1bGVyKSwgbWlk"
    "bmlnaHQtdG8tbWlkbmlnaHQgYm91bmRhcnkuCiAgICBGaWxlOiBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sIOKAlCBvdmVyd3Jp"
    "dGVzIG9uIGVhY2ggc2F2ZS4KICAgIEluZGV4OiBzZXNzaW9ucy9zZXNzaW9uX2luZGV4Lmpzb24g4oCUIG9uZSBlbnRyeSBwZXIg"
    "ZGF5LgoKICAgIFNlc3Npb25zIGFyZSBsb2FkZWQgYXMgY29udGV4dCBpbmplY3Rpb24gKG5vdCByZWFsIG1lbW9yeSkgdW50aWwK"
    "ICAgIHRoZSBTUUxpdGUvQ2hyb21hREIgc3lzdGVtIGlzIGJ1aWx0IGluIFBoYXNlIDIuCiAgICAiIiIKCiAgICBBVVRPU0FWRV9J"
    "TlRFUlZBTCA9IDEwICAgIyBtaW51dGVzCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3Nlc3Npb25zX2Rp"
    "ciAgPSBjZmdfcGF0aCgic2Vzc2lvbnMiKQogICAgICAgIHNlbGYuX2luZGV4X3BhdGggICAgPSBzZWxmLl9zZXNzaW9uc19kaXIg"
    "LyAic2Vzc2lvbl9pbmRleC5qc29uIgogICAgICAgIHNlbGYuX3Nlc3Npb25faWQgICAgPSBmInNlc3Npb25fe2RhdGV0aW1lLm5v"
    "dygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9IgogICAgICAgIHNlbGYuX2N1cnJlbnRfZGF0ZSAgPSBkYXRlLnRvZGF5KCku"
    "aXNvZm9ybWF0KCkKICAgICAgICBzZWxmLl9tZXNzYWdlczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fbG9hZGVkX2pv"
    "dXJuYWw6IE9wdGlvbmFsW3N0cl0gPSBOb25lICAjIGRhdGUgb2YgbG9hZGVkIGpvdXJuYWwKCiAgICAjIOKUgOKUgCBDVVJSRU5U"
    "IFNFU1NJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICBkZWYgYWRkX21lc3NhZ2Uoc2VsZiwgcm9sZTogc3RyLCBjb250ZW50OiBzdHIsCiAgICAgICAgICAgICAgICAgICAg"
    "ZW1vdGlvbjogc3RyID0gIiIsIHRpbWVzdGFtcDogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fbWVzc2FnZXMuYXBw"
    "ZW5kKHsKICAgICAgICAgICAgImlkIjogICAgICAgIGYibXNnX3t1dWlkLnV1aWQ0KCkuaGV4Wzo4XX0iLAogICAgICAgICAgICAi"
    "dGltZXN0YW1wIjogdGltZXN0YW1wIG9yIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgInJvbGUiOiAgICAgIHJvbGUsCiAg"
    "ICAgICAgICAgICJjb250ZW50IjogICBjb250ZW50LAogICAgICAgICAgICAiZW1vdGlvbiI6ICAgZW1vdGlvbiwKICAgICAgICB9"
    "KQoKICAgIGRlZiBnZXRfaGlzdG9yeShzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIiIgogICAgICAgIFJldHVybiBoaXN0"
    "b3J5IGluIExMTS1mcmllbmRseSBmb3JtYXQuCiAgICAgICAgW3sicm9sZSI6ICJ1c2VyInwiYXNzaXN0YW50IiwgImNvbnRlbnQi"
    "OiAiLi4uIn1dCiAgICAgICAgIiIiCiAgICAgICAgcmV0dXJuIFsKICAgICAgICAgICAgeyJyb2xlIjogbVsicm9sZSJdLCAiY29u"
    "dGVudCI6IG1bImNvbnRlbnQiXX0KICAgICAgICAgICAgZm9yIG0gaW4gc2VsZi5fbWVzc2FnZXMKICAgICAgICAgICAgaWYgbVsi"
    "cm9sZSJdIGluICgidXNlciIsICJhc3Npc3RhbnQiKQogICAgICAgIF0KCiAgICBAcHJvcGVydHkKICAgIGRlZiBzZXNzaW9uX2lk"
    "KHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4gc2VsZi5fc2Vzc2lvbl9pZAoKICAgIEBwcm9wZXJ0eQogICAgZGVmIG1lc3Nh"
    "Z2VfY291bnQoc2VsZikgLT4gaW50OgogICAgICAgIHJldHVybiBsZW4oc2VsZi5fbWVzc2FnZXMpCgogICAgIyDilIDilIAgU0FW"
    "RSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBzYXZlKHNlbGYsIGFpX2dlbmVyYXRlZF9uYW1lOiBzdHIgPSAi"
    "IikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBTYXZlIGN1cnJlbnQgc2Vzc2lvbiB0byBzZXNzaW9ucy9ZWVlZLU1NLURE"
    "Lmpzb25sLgogICAgICAgIE92ZXJ3cml0ZXMgdGhlIGZpbGUgZm9yIHRvZGF5IOKAlCBlYWNoIHNhdmUgaXMgYSBmdWxsIHNuYXBz"
    "aG90LgogICAgICAgIFVwZGF0ZXMgc2Vzc2lvbl9pbmRleC5qc29uLgogICAgICAgICIiIgogICAgICAgIHRvZGF5ID0gZGF0ZS50"
    "b2RheSgpLmlzb2Zvcm1hdCgpCiAgICAgICAgb3V0X3BhdGggPSBzZWxmLl9zZXNzaW9uc19kaXIgLyBmInt0b2RheX0uanNvbmwi"
    "CgogICAgICAgICMgV3JpdGUgYWxsIG1lc3NhZ2VzCiAgICAgICAgd3JpdGVfanNvbmwob3V0X3BhdGgsIHNlbGYuX21lc3NhZ2Vz"
    "KQoKICAgICAgICAjIFVwZGF0ZSBpbmRleAogICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAgICAgICAgZXhpc3Rp"
    "bmcgPSBuZXh0KAogICAgICAgICAgICAocyBmb3IgcyBpbiBpbmRleFsic2Vzc2lvbnMiXSBpZiBzWyJkYXRlIl0gPT0gdG9kYXkp"
    "LCBOb25lCiAgICAgICAgKQoKICAgICAgICBuYW1lID0gYWlfZ2VuZXJhdGVkX25hbWUgb3IgZXhpc3RpbmcuZ2V0KCJuYW1lIiwg"
    "IiIpIGlmIGV4aXN0aW5nIGVsc2UgIiIKICAgICAgICBpZiBub3QgbmFtZSBhbmQgc2VsZi5fbWVzc2FnZXM6CiAgICAgICAgICAg"
    "ICMgQXV0by1uYW1lIGZyb20gZmlyc3QgdXNlciBtZXNzYWdlIChmaXJzdCA1IHdvcmRzKQogICAgICAgICAgICBmaXJzdF91c2Vy"
    "ID0gbmV4dCgKICAgICAgICAgICAgICAgIChtWyJjb250ZW50Il0gZm9yIG0gaW4gc2VsZi5fbWVzc2FnZXMgaWYgbVsicm9sZSJd"
    "ID09ICJ1c2VyIiksCiAgICAgICAgICAgICAgICAiIgogICAgICAgICAgICApCiAgICAgICAgICAgIHdvcmRzID0gZmlyc3RfdXNl"
    "ci5zcGxpdCgpWzo1XQogICAgICAgICAgICBuYW1lICA9ICIgIi5qb2luKHdvcmRzKSBpZiB3b3JkcyBlbHNlIGYiU2Vzc2lvbiB7"
    "dG9kYXl9IgoKICAgICAgICBlbnRyeSA9IHsKICAgICAgICAgICAgImRhdGUiOiAgICAgICAgICB0b2RheSwKICAgICAgICAgICAg"
    "InNlc3Npb25faWQiOiAgICBzZWxmLl9zZXNzaW9uX2lkLAogICAgICAgICAgICAibmFtZSI6ICAgICAgICAgIG5hbWUsCiAgICAg"
    "ICAgICAgICJtZXNzYWdlX2NvdW50IjogbGVuKHNlbGYuX21lc3NhZ2VzKSwKICAgICAgICAgICAgImZpcnN0X21lc3NhZ2UiOiAo"
    "c2VsZi5fbWVzc2FnZXNbMF1bInRpbWVzdGFtcCJdCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHNlbGYuX21lc3Nh"
    "Z2VzIGVsc2UgIiIpLAogICAgICAgICAgICAibGFzdF9tZXNzYWdlIjogIChzZWxmLl9tZXNzYWdlc1stMV1bInRpbWVzdGFtcCJd"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAgICAgIH0KCiAgICAg"
    "ICAgaWYgZXhpc3Rpbmc6CiAgICAgICAgICAgIGlkeCA9IGluZGV4WyJzZXNzaW9ucyJdLmluZGV4KGV4aXN0aW5nKQogICAgICAg"
    "ICAgICBpbmRleFsic2Vzc2lvbnMiXVtpZHhdID0gZW50cnkKICAgICAgICBlbHNlOgogICAgICAgICAgICBpbmRleFsic2Vzc2lv"
    "bnMiXS5pbnNlcnQoMCwgZW50cnkpCgogICAgICAgICMgS2VlcCBsYXN0IDM2NSBkYXlzIGluIGluZGV4CiAgICAgICAgaW5kZXhb"
    "InNlc3Npb25zIl0gPSBpbmRleFsic2Vzc2lvbnMiXVs6MzY1XQogICAgICAgIHNlbGYuX3NhdmVfaW5kZXgoaW5kZXgpCgogICAg"
    "IyDilIDilIAgTE9BRCAvIEpPVVJOQUwg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbGlzdF9zZXNzaW9ucyhzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIi"
    "IlJldHVybiBhbGwgc2Vzc2lvbnMgZnJvbSBpbmRleCwgbmV3ZXN0IGZpcnN0LiIiIgogICAgICAgIHJldHVybiBzZWxmLl9sb2Fk"
    "X2luZGV4KCkuZ2V0KCJzZXNzaW9ucyIsIFtdKQoKICAgIGRlZiBsb2FkX3Nlc3Npb25fYXNfY29udGV4dChzZWxmLCBzZXNzaW9u"
    "X2RhdGU6IHN0cikgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIExvYWQgYSBwYXN0IHNlc3Npb24gYXMgYSBjb250ZXh0IGlu"
    "amVjdGlvbiBzdHJpbmcuCiAgICAgICAgUmV0dXJucyBmb3JtYXR0ZWQgdGV4dCB0byBwcmVwZW5kIHRvIHRoZSBzeXN0ZW0gcHJv"
    "bXB0LgogICAgICAgIFRoaXMgaXMgTk9UIHJlYWwgbWVtb3J5IOKAlCBpdCdzIGEgdGVtcG9yYXJ5IGNvbnRleHQgd2luZG93IGlu"
    "amVjdGlvbgogICAgICAgIHVudGlsIHRoZSBQaGFzZSAyIG1lbW9yeSBzeXN0ZW0gaXMgYnVpbHQuCiAgICAgICAgIiIiCiAgICAg"
    "ICAgcGF0aCA9IHNlbGYuX3Nlc3Npb25zX2RpciAvIGYie3Nlc3Npb25fZGF0ZX0uanNvbmwiCiAgICAgICAgaWYgbm90IHBhdGgu"
    "ZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiAiIgoKICAgICAgICBtZXNzYWdlcyA9IHJlYWRfanNvbmwocGF0aCkKICAgICAg"
    "ICBzZWxmLl9sb2FkZWRfam91cm5hbCA9IHNlc3Npb25fZGF0ZQoKICAgICAgICBsaW5lcyA9IFtmIltKT1VSTkFMIExPQURFRCDi"
    "gJQge3Nlc3Npb25fZGF0ZX1dIiwKICAgICAgICAgICAgICAgICAiVGhlIGZvbGxvd2luZyBpcyBhIHJlY29yZCBvZiBhIHByaW9y"
    "IGNvbnZlcnNhdGlvbi4iLAogICAgICAgICAgICAgICAgICJVc2UgdGhpcyBhcyBjb250ZXh0IGZvciB0aGUgY3VycmVudCBzZXNz"
    "aW9uOlxuIl0KCiAgICAgICAgIyBJbmNsdWRlIHVwIHRvIGxhc3QgMzAgbWVzc2FnZXMgZnJvbSB0aGF0IHNlc3Npb24KICAgICAg"
    "ICBmb3IgbXNnIGluIG1lc3NhZ2VzWy0zMDpdOgogICAgICAgICAgICByb2xlICAgID0gbXNnLmdldCgicm9sZSIsICI/IikudXBw"
    "ZXIoKQogICAgICAgICAgICBjb250ZW50ID0gbXNnLmdldCgiY29udGVudCIsICIiKVs6MzAwXQogICAgICAgICAgICB0cyAgICAg"
    "ID0gbXNnLmdldCgidGltZXN0YW1wIiwgIiIpWzoxNl0KICAgICAgICAgICAgbGluZXMuYXBwZW5kKGYiW3t0c31dIHtyb2xlfTog"
    "e2NvbnRlbnR9IikKCiAgICAgICAgbGluZXMuYXBwZW5kKCJbRU5EIEpPVVJOQUxdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2lu"
    "KGxpbmVzKQoKICAgIGRlZiBjbGVhcl9sb2FkZWRfam91cm5hbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xvYWRlZF9q"
    "b3VybmFsID0gTm9uZQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGxvYWRlZF9qb3VybmFsX2RhdGUoc2VsZikgLT4gT3B0aW9uYWxb"
    "c3RyXToKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZGVkX2pvdXJuYWwKCiAgICBkZWYgcmVuYW1lX3Nlc3Npb24oc2VsZiwgc2Vz"
    "c2lvbl9kYXRlOiBzdHIsIG5ld19uYW1lOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgIiIiUmVuYW1lIGEgc2Vzc2lvbiBpbiB0aGUg"
    "aW5kZXguIFJldHVybnMgVHJ1ZSBvbiBzdWNjZXNzLiIiIgogICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAgICAg"
    "ICAgZm9yIGVudHJ5IGluIGluZGV4WyJzZXNzaW9ucyJdOgogICAgICAgICAgICBpZiBlbnRyeVsiZGF0ZSJdID09IHNlc3Npb25f"
    "ZGF0ZToKICAgICAgICAgICAgICAgIGVudHJ5WyJuYW1lIl0gPSBuZXdfbmFtZVs6ODBdCiAgICAgICAgICAgICAgICBzZWxmLl9z"
    "YXZlX2luZGV4KGluZGV4KQogICAgICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICAjIOKU"
    "gOKUgCBJTkRFWCBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9sb2FkX2luZGV4KHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgaWYgbm90IHNlbGYu"
    "X2luZGV4X3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiB7InNlc3Npb25zIjogW119CiAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICByZXR1cm4ganNvbi5sb2FkcygKICAgICAgICAgICAgICAgIHNlbGYuX2luZGV4X3BhdGgucmVhZF90ZXh0KGVuY29k"
    "aW5nPSJ1dGYtOCIpCiAgICAgICAgICAgICkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4geyJz"
    "ZXNzaW9ucyI6IFtdfQoKICAgIGRlZiBfc2F2ZV9pbmRleChzZWxmLCBpbmRleDogZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9pbmRleF9wYXRoLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoaW5kZXgsIGluZGVudD0yKSwgZW5jb2Rpbmc9"
    "InV0Zi04IgogICAgICAgICkKCgojIOKUgOKUgCBMRVNTT05TIExFQVJORUQgREFUQUJBU0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIExlc3NvbnNMZWFybmVk"
    "REI6CiAgICAiIiIKICAgIFBlcnNpc3RlbnQga25vd2xlZGdlIGJhc2UgZm9yIGNvZGUgbGVzc29ucywgcnVsZXMsIGFuZCByZXNv"
    "bHV0aW9ucy4KCiAgICBDb2x1bW5zIHBlciByZWNvcmQ6CiAgICAgICAgaWQsIGNyZWF0ZWRfYXQsIGVudmlyb25tZW50IChMU0x8"
    "UHl0aG9ufFB5U2lkZTZ8Li4uKSwgbGFuZ3VhZ2UsCiAgICAgICAgcmVmZXJlbmNlX2tleSAoc2hvcnQgdW5pcXVlIHRhZyksIHN1"
    "bW1hcnksIGZ1bGxfcnVsZSwKICAgICAgICByZXNvbHV0aW9uLCBsaW5rLCB0YWdzCgogICAgUXVlcmllZCBGSVJTVCBiZWZvcmUg"
    "YW55IGNvZGUgc2Vzc2lvbiBpbiB0aGUgcmVsZXZhbnQgbGFuZ3VhZ2UuCiAgICBUaGUgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGxp"
    "dmVzIGhlcmUuCiAgICBHcm93aW5nLCBub24tZHVwbGljYXRpbmcsIHNlYXJjaGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0"
    "X18oc2VsZik6CiAgICAgICAgc2VsZi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gImxlc3NvbnNfbGVhcm5lZC5qc29u"
    "bCIKCiAgICBkZWYgYWRkKHNlbGYsIGVudmlyb25tZW50OiBzdHIsIGxhbmd1YWdlOiBzdHIsIHJlZmVyZW5jZV9rZXk6IHN0ciwK"
    "ICAgICAgICAgICAgc3VtbWFyeTogc3RyLCBmdWxsX3J1bGU6IHN0ciwgcmVzb2x1dGlvbjogc3RyID0gIiIsCiAgICAgICAgICAg"
    "IGxpbms6IHN0ciA9ICIiLCB0YWdzOiBsaXN0ID0gTm9uZSkgLT4gZGljdDoKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAg"
    "ICJpZCI6ICAgICAgICAgICAgZiJsZXNzb25fe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAiY3JlYXRlZF9h"
    "dCI6ICAgIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgImVudmlyb25tZW50IjogICBlbnZpcm9ubWVudCwKICAgICAgICAg"
    "ICAgImxhbmd1YWdlIjogICAgICBsYW5ndWFnZSwKICAgICAgICAgICAgInJlZmVyZW5jZV9rZXkiOiByZWZlcmVuY2Vfa2V5LAog"
    "ICAgICAgICAgICAic3VtbWFyeSI6ICAgICAgIHN1bW1hcnksCiAgICAgICAgICAgICJmdWxsX3J1bGUiOiAgICAgZnVsbF9ydWxl"
    "LAogICAgICAgICAgICAicmVzb2x1dGlvbiI6ICAgIHJlc29sdXRpb24sCiAgICAgICAgICAgICJsaW5rIjogICAgICAgICAgbGlu"
    "aywKICAgICAgICAgICAgInRhZ3MiOiAgICAgICAgICB0YWdzIG9yIFtdLAogICAgICAgIH0KICAgICAgICBpZiBub3Qgc2VsZi5f"
    "aXNfZHVwbGljYXRlKHJlZmVyZW5jZV9rZXkpOgogICAgICAgICAgICBhcHBlbmRfanNvbmwoc2VsZi5fcGF0aCwgcmVjb3JkKQog"
    "ICAgICAgIHJldHVybiByZWNvcmQKCiAgICBkZWYgc2VhcmNoKHNlbGYsIHF1ZXJ5OiBzdHIgPSAiIiwgZW52aXJvbm1lbnQ6IHN0"
    "ciA9ICIiLAogICAgICAgICAgICAgICBsYW5ndWFnZTogc3RyID0gIiIpIC0+IGxpc3RbZGljdF06CiAgICAgICAgcmVjb3JkcyA9"
    "IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICByZXN1bHRzID0gW10KICAgICAgICBxID0gcXVlcnkubG93ZXIoKQogICAg"
    "ICAgIGZvciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGlmIGVudmlyb25tZW50IGFuZCByLmdldCgiZW52aXJvbm1lbnQiLCIi"
    "KS5sb3dlcigpICE9IGVudmlyb25tZW50Lmxvd2VyKCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBs"
    "YW5ndWFnZSBhbmQgci5nZXQoImxhbmd1YWdlIiwiIikubG93ZXIoKSAhPSBsYW5ndWFnZS5sb3dlcigpOgogICAgICAgICAgICAg"
    "ICAgY29udGludWUKICAgICAgICAgICAgaWYgcToKICAgICAgICAgICAgICAgIGhheXN0YWNrID0gIiAiLmpvaW4oWwogICAgICAg"
    "ICAgICAgICAgICAgIHIuZ2V0KCJzdW1tYXJ5IiwiIiksCiAgICAgICAgICAgICAgICAgICAgci5nZXQoImZ1bGxfcnVsZSIsIiIp"
    "LAogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJyZWZlcmVuY2Vfa2V5IiwiIiksCiAgICAgICAgICAgICAgICAgICAgIiAiLmpv"
    "aW4oci5nZXQoInRhZ3MiLFtdKSksCiAgICAgICAgICAgICAgICBdKS5sb3dlcigpCiAgICAgICAgICAgICAgICBpZiBxIG5vdCBp"
    "biBoYXlzdGFjazoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICByZXN1bHRzLmFwcGVuZChyKQogICAg"
    "ICAgIHJldHVybiByZXN1bHRzCgogICAgZGVmIGdldF9hbGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVh"
    "ZF9qc29ubChzZWxmLl9wYXRoKQoKICAgIGRlZiBkZWxldGUoc2VsZiwgcmVjb3JkX2lkOiBzdHIpIC0+IGJvb2w6CiAgICAgICAg"
    "cmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBmaWx0ZXJlZCA9IFtyIGZvciByIGluIHJlY29yZHMgaWYg"
    "ci5nZXQoImlkIikgIT0gcmVjb3JkX2lkXQogICAgICAgIGlmIGxlbihmaWx0ZXJlZCkgPCBsZW4ocmVjb3Jkcyk6CiAgICAgICAg"
    "ICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIGZpbHRlcmVkKQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVy"
    "biBGYWxzZQoKICAgIGRlZiBidWlsZF9jb250ZXh0X2Zvcl9sYW5ndWFnZShzZWxmLCBsYW5ndWFnZTogc3RyLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIG1heF9jaGFyczogaW50ID0gMTUwMCkgLT4gc3RyOgogICAgICAgICIiIgogICAgICAg"
    "IEJ1aWxkIGEgY29udGV4dCBzdHJpbmcgb2YgYWxsIHJ1bGVzIGZvciBhIGdpdmVuIGxhbmd1YWdlLgogICAgICAgIEZvciBpbmpl"
    "Y3Rpb24gaW50byBzeXN0ZW0gcHJvbXB0IGJlZm9yZSBjb2RlIHNlc3Npb25zLgogICAgICAgICIiIgogICAgICAgIHJlY29yZHMg"
    "PSBzZWxmLnNlYXJjaChsYW5ndWFnZT1sYW5ndWFnZSkKICAgICAgICBpZiBub3QgcmVjb3JkczoKICAgICAgICAgICAgcmV0dXJu"
    "ICIiCgogICAgICAgIHBhcnRzID0gW2YiW3tsYW5ndWFnZS51cHBlcigpfSBSVUxFUyDigJQgQVBQTFkgQkVGT1JFIFdSSVRJTkcg"
    "Q09ERV0iXQogICAgICAgIHRvdGFsID0gMAogICAgICAgIGZvciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGVudHJ5ID0gZiLi"
    "gKIge3IuZ2V0KCdyZWZlcmVuY2Vfa2V5JywnJyl9OiB7ci5nZXQoJ2Z1bGxfcnVsZScsJycpfSIKICAgICAgICAgICAgaWYgdG90"
    "YWwgKyBsZW4oZW50cnkpID4gbWF4X2NoYXJzOgogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgcGFydHMuYXBwZW5k"
    "KGVudHJ5KQogICAgICAgICAgICB0b3RhbCArPSBsZW4oZW50cnkpCgogICAgICAgIHBhcnRzLmFwcGVuZChmIltFTkQge2xhbmd1"
    "YWdlLnVwcGVyKCl9IFJVTEVTXSIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCiAgICBkZWYgX2lzX2R1cGxpY2F0"
    "ZShzZWxmLCByZWZlcmVuY2Vfa2V5OiBzdHIpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIGFueSgKICAgICAgICAgICAgci5nZXQo"
    "InJlZmVyZW5jZV9rZXkiLCIiKS5sb3dlcigpID09IHJlZmVyZW5jZV9rZXkubG93ZXIoKQogICAgICAgICAgICBmb3IgciBpbiBy"
    "ZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgKQoKICAgIGRlZiBzZWVkX2xzbF9ydWxlcyhzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgICIiIgogICAgICAgIFNlZWQgdGhlIExTTCBGb3JiaWRkZW4gUnVsZXNldCBvbiBmaXJzdCBydW4gaWYgdGhlIERCIGlzIGVt"
    "cHR5LgogICAgICAgIFRoZXNlIGFyZSB0aGUgaGFyZCBydWxlcyBmcm9tIHRoZSBwcm9qZWN0IHN0YW5kaW5nIHJ1bGVzLgogICAg"
    "ICAgICIiIgogICAgICAgIGlmIHJlYWRfanNvbmwoc2VsZi5fcGF0aCk6CiAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5IHNl"
    "ZWRlZAoKICAgICAgICBsc2xfcnVsZXMgPSBbCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19URVJOQVJZIiwKICAgICAg"
    "ICAgICAgICJObyB0ZXJuYXJ5IG9wZXJhdG9ycyBpbiBMU0wiLAogICAgICAgICAgICAgIk5ldmVyIHVzZSB0aGUgdGVybmFyeSBv"
    "cGVyYXRvciAoPzopIGluIExTTCBzY3JpcHRzLiAiCiAgICAgICAgICAgICAiVXNlIGlmL2Vsc2UgYmxvY2tzIGluc3RlYWQuIExT"
    "TCBkb2VzIG5vdCBzdXBwb3J0IHRlcm5hcnkuIiwKICAgICAgICAgICAgICJSZXBsYWNlIHdpdGggaWYvZWxzZSBibG9jay4iLCAi"
    "IiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19GT1JFQUNIIiwKICAgICAgICAgICAgICJObyBmb3JlYWNoIGxvb3Bz"
    "IGluIExTTCIsCiAgICAgICAgICAgICAiTFNMIGhhcyBubyBmb3JlYWNoIGxvb3AgY29uc3RydWN0LiBVc2UgaW50ZWdlciBpbmRl"
    "eCB3aXRoICIKICAgICAgICAgICAgICJsbEdldExpc3RMZW5ndGgoKSBhbmQgYSBmb3Igb3Igd2hpbGUgbG9vcC4iLAogICAgICAg"
    "ICAgICAgIlVzZTogZm9yKGludGVnZXIgaT0wOyBpPGxsR2V0TGlzdExlbmd0aChteUxpc3QpOyBpKyspIiwgIiIpLAogICAgICAg"
    "ICAgICAoIkxTTCIsICJMU0wiLCAiTk9fR0xPQkFMX0FTU0lHTl9GUk9NX0ZVTkMiLAogICAgICAgICAgICAgIk5vIGdsb2JhbCB2"
    "YXJpYWJsZSBhc3NpZ25tZW50cyBmcm9tIGZ1bmN0aW9uIGNhbGxzIiwKICAgICAgICAgICAgICJHbG9iYWwgdmFyaWFibGUgaW5p"
    "dGlhbGl6YXRpb24gaW4gTFNMIGNhbm5vdCBjYWxsIGZ1bmN0aW9ucy4gIgogICAgICAgICAgICAgIkluaXRpYWxpemUgZ2xvYmFs"
    "cyB3aXRoIGxpdGVyYWwgdmFsdWVzIG9ubHkuICIKICAgICAgICAgICAgICJBc3NpZ24gZnJvbSBmdW5jdGlvbnMgaW5zaWRlIGV2"
    "ZW50IGhhbmRsZXJzIG9yIG90aGVyIGZ1bmN0aW9ucy4iLAogICAgICAgICAgICAgIk1vdmUgdGhlIGFzc2lnbm1lbnQgaW50byBh"
    "biBldmVudCBoYW5kbGVyIChzdGF0ZV9lbnRyeSwgZXRjLikiLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19W"
    "T0lEX0tFWVdPUkQiLAogICAgICAgICAgICAgIk5vIHZvaWQga2V5d29yZCBpbiBMU0wiLAogICAgICAgICAgICAgIkxTTCBkb2Vz"
    "IG5vdCBoYXZlIGEgdm9pZCBrZXl3b3JkIGZvciBmdW5jdGlvbiByZXR1cm4gdHlwZXMuICIKICAgICAgICAgICAgICJGdW5jdGlv"
    "bnMgdGhhdCByZXR1cm4gbm90aGluZyBzaW1wbHkgb21pdCB0aGUgcmV0dXJuIHR5cGUuIiwKICAgICAgICAgICAgICJSZW1vdmUg"
    "J3ZvaWQnIGZyb20gZnVuY3Rpb24gc2lnbmF0dXJlLiAiCiAgICAgICAgICAgICAiZS5nLiBteUZ1bmMoKSB7IC4uLiB9IG5vdCB2"
    "b2lkIG15RnVuYygpIHsgLi4uIH0iLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJDT01QTEVURV9TQ1JJUFRTX09O"
    "TFkiLAogICAgICAgICAgICAgIkFsd2F5cyBwcm92aWRlIGNvbXBsZXRlIHNjcmlwdHMsIG5ldmVyIHBhcnRpYWwgZWRpdHMiLAog"
    "ICAgICAgICAgICAgIldoZW4gd3JpdGluZyBvciBlZGl0aW5nIExTTCBzY3JpcHRzLCBhbHdheXMgb3V0cHV0IHRoZSBjb21wbGV0"
    "ZSAiCiAgICAgICAgICAgICAic2NyaXB0LiBOZXZlciBwcm92aWRlIHBhcnRpYWwgc25pcHBldHMgb3IgJ2FkZCB0aGlzIHNlY3Rp"
    "b24nICIKICAgICAgICAgICAgICJpbnN0cnVjdGlvbnMuIFRoZSBmdWxsIHNjcmlwdCBtdXN0IGJlIGNvcHktcGFzdGUgcmVhZHku"
    "IiwKICAgICAgICAgICAgICJXcml0ZSB0aGUgZW50aXJlIHNjcmlwdCBmcm9tIHRvcCB0byBib3R0b20uIiwgIiIpLAogICAgICAg"
    "IF0KCiAgICAgICAgZm9yIGVudiwgbGFuZywgcmVmLCBzdW1tYXJ5LCBmdWxsX3J1bGUsIHJlc29sdXRpb24sIGxpbmsgaW4gbHNs"
    "X3J1bGVzOgogICAgICAgICAgICBzZWxmLmFkZChlbnYsIGxhbmcsIHJlZiwgc3VtbWFyeSwgZnVsbF9ydWxlLCByZXNvbHV0aW9u"
    "LCBsaW5rLAogICAgICAgICAgICAgICAgICAgICB0YWdzPVsibHNsIiwgImZvcmJpZGRlbiIsICJzdGFuZGluZ19ydWxlIl0pCgoK"
    "IyDilIDilIAgVEFTSyBNQU5BR0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBUYXNrTWFuYWdlcjoK"
    "ICAgICIiIgogICAgVGFzay9yZW1pbmRlciBDUlVEIGFuZCBkdWUtZXZlbnQgZGV0ZWN0aW9uLgoKICAgIEZpbGU6IG1lbW9yaWVz"
    "L3Rhc2tzLmpzb25sCgogICAgVGFzayByZWNvcmQgZmllbGRzOgogICAgICAgIGlkLCBjcmVhdGVkX2F0LCBkdWVfYXQsIHByZV90"
    "cmlnZ2VyICgxbWluIGJlZm9yZSksCiAgICAgICAgdGV4dCwgc3RhdHVzIChwZW5kaW5nfHRyaWdnZXJlZHxzbm9vemVkfGNvbXBs"
    "ZXRlZHxjYW5jZWxsZWQpLAogICAgICAgIGFja25vd2xlZGdlZF9hdCwgcmV0cnlfY291bnQsIGxhc3RfdHJpZ2dlcmVkX2F0LCBu"
    "ZXh0X3JldHJ5X2F0LAogICAgICAgIHNvdXJjZSAobG9jYWx8Z29vZ2xlKSwgZ29vZ2xlX2V2ZW50X2lkLCBzeW5jX3N0YXR1cywg"
    "bWV0YWRhdGEKCiAgICBEdWUtZXZlbnQgY3ljbGU6CiAgICAgICAgLSBQcmUtdHJpZ2dlcjogMSBtaW51dGUgYmVmb3JlIGR1ZSDi"
    "hpIgYW5ub3VuY2UgdXBjb21pbmcKICAgICAgICAtIER1ZSB0cmlnZ2VyOiBhdCBkdWUgdGltZSDihpIgYWxlcnQgc291bmQgKyBB"
    "SSBjb21tZW50YXJ5CiAgICAgICAgLSAzLW1pbnV0ZSB3aW5kb3c6IGlmIG5vdCBhY2tub3dsZWRnZWQg4oaSIHNub296ZQogICAg"
    "ICAgIC0gMTItbWludXRlIHJldHJ5OiByZS10cmlnZ2VyCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAg"
    "c2VsZi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gInRhc2tzLmpzb25sIgoKICAgICMg4pSA4pSAIENSVUQg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbG9hZF9hbGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICB0YXNrcyA9"
    "IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBjaGFuZ2VkID0gRmFsc2UKICAgICAgICBub3JtYWxpemVkID0gW10KICAg"
    "ICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgbm90IGlzaW5zdGFuY2UodCwgZGljdCk6CiAgICAgICAgICAgICAg"
    "ICBjb250aW51ZQogICAgICAgICAgICBpZiAiaWQiIG5vdCBpbiB0OgogICAgICAgICAgICAgICAgdFsiaWQiXSA9IGYidGFza197"
    "dXVpZC51dWlkNCgpLmhleFs6MTBdfSIKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICMgTm9ybWFs"
    "aXplIGZpZWxkIG5hbWVzCiAgICAgICAgICAgIGlmICJkdWVfYXQiIG5vdCBpbiB0OgogICAgICAgICAgICAgICAgdFsiZHVlX2F0"
    "Il0gPSB0LmdldCgiZHVlIikKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgi"
    "c3RhdHVzIiwgICAgICAgICAgICJwZW5kaW5nIikKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJyZXRyeV9jb3VudCIsICAgICAg"
    "MCkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJhY2tub3dsZWRnZWRfYXQiLCAgTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZh"
    "dWx0KCJsYXN0X3RyaWdnZXJlZF9hdCIsTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJuZXh0X3JldHJ5X2F0IiwgICAg"
    "Tm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJwcmVfYW5ub3VuY2VkIiwgICAgRmFsc2UpCiAgICAgICAgICAgIHQuc2V0"
    "ZGVmYXVsdCgic291cmNlIiwgICAgICAgICAgICJsb2NhbCIpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiZ29vZ2xlX2V2ZW50"
    "X2lkIiwgIE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3luY19zdGF0dXMiLCAgICAgICJwZW5kaW5nIikKICAgICAg"
    "ICAgICAgdC5zZXRkZWZhdWx0KCJtZXRhZGF0YSIsICAgICAgICAge30pCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiY3JlYXRl"
    "ZF9hdCIsICAgICAgIGxvY2FsX25vd19pc28oKSkKCiAgICAgICAgICAgICMgQ29tcHV0ZSBwcmVfdHJpZ2dlciBpZiBtaXNzaW5n"
    "CiAgICAgICAgICAgIGlmIHQuZ2V0KCJkdWVfYXQiKSBhbmQgbm90IHQuZ2V0KCJwcmVfdHJpZ2dlciIpOgogICAgICAgICAgICAg"
    "ICAgZHQgPSBwYXJzZV9pc28odFsiZHVlX2F0Il0pCiAgICAgICAgICAgICAgICBpZiBkdDoKICAgICAgICAgICAgICAgICAgICBw"
    "cmUgPSBkdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpCiAgICAgICAgICAgICAgICAgICAgdFsicHJlX3RyaWdnZXIiXSA9IHByZS5p"
    "c29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgICAg"
    "ICBub3JtYWxpemVkLmFwcGVuZCh0KQoKICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9w"
    "YXRoLCBub3JtYWxpemVkKQogICAgICAgIHJldHVybiBub3JtYWxpemVkCgogICAgZGVmIHNhdmVfYWxsKHNlbGYsIHRhc2tzOiBs"
    "aXN0W2RpY3RdKSAtPiBOb25lOgogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHRhc2tzKQoKICAgIGRlZiBhZGQoc2Vs"
    "ZiwgdGV4dDogc3RyLCBkdWVfZHQ6IGRhdGV0aW1lLAogICAgICAgICAgICBzb3VyY2U6IHN0ciA9ICJsb2NhbCIpIC0+IGRpY3Q6"
    "CiAgICAgICAgcHJlID0gZHVlX2R0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkKICAgICAgICB0YXNrID0gewogICAgICAgICAgICAi"
    "aWQiOiAgICAgICAgICAgICAgIGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICJjcmVhdGVkX2F0"
    "IjogICAgICAgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAiZHVlX2F0IjogICAgICAgICAgIGR1ZV9kdC5pc29mb3JtYXQo"
    "dGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgInByZV90cmlnZ2VyIjogICAgICBwcmUuaXNvZm9ybWF0KHRpbWVzcGVj"
    "PSJzZWNvbmRzIiksCiAgICAgICAgICAgICJ0ZXh0IjogICAgICAgICAgICAgdGV4dC5zdHJpcCgpLAogICAgICAgICAgICAic3Rh"
    "dHVzIjogICAgICAgICAgICJwZW5kaW5nIiwKICAgICAgICAgICAgImFja25vd2xlZGdlZF9hdCI6ICBOb25lLAogICAgICAgICAg"
    "ICAicmV0cnlfY291bnQiOiAgICAgIDAsCiAgICAgICAgICAgICJsYXN0X3RyaWdnZXJlZF9hdCI6Tm9uZSwKICAgICAgICAgICAg"
    "Im5leHRfcmV0cnlfYXQiOiAgICBOb25lLAogICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6ICAgIEZhbHNlLAogICAgICAgICAg"
    "ICAic291cmNlIjogICAgICAgICAgIHNvdXJjZSwKICAgICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6ICBOb25lLAogICAgICAg"
    "ICAgICAic3luY19zdGF0dXMiOiAgICAgICJwZW5kaW5nIiwKICAgICAgICAgICAgIm1ldGFkYXRhIjogICAgICAgICB7fSwKICAg"
    "ICAgICB9CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICB0YXNrcy5hcHBlbmQodGFzaykKICAgICAgICBz"
    "ZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgIHJldHVybiB0YXNrCgogICAgZGVmIHVwZGF0ZV9zdGF0dXMoc2VsZiwgdGFza19p"
    "ZDogc3RyLCBzdGF0dXM6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgIGFja25vd2xlZGdlZDogYm9vbCA9IEZhbHNlKSAtPiBP"
    "cHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAg"
    "ICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gPSBzdGF0dXMKICAg"
    "ICAgICAgICAgICAgIGlmIGFja25vd2xlZGdlZDoKICAgICAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxv"
    "Y2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0"
    "CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY29tcGxldGUoc2VsZiwgdGFza19pZDogc3RyKSAtPiBPcHRpb25hbFtkaWN0"
    "XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0"
    "LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gICAgICAgICAgPSAiY29tcGxldGVkIgog"
    "ICAgICAgICAgICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgICAgIHNlbGYu"
    "c2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNhbmNl"
    "bChzZWxmLCB0YXNrX2lkOiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAg"
    "ICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09IHRhc2tfaWQ6CiAgICAgICAgICAgICAg"
    "ICB0WyJzdGF0dXMiXSAgICAgICAgICA9ICJjYW5jZWxsZWQiCiAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9"
    "IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVy"
    "biB0CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY2xlYXJfY29tcGxldGVkKHNlbGYpIC0+IGludDoKICAgICAgICB0YXNr"
    "cyAgICA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGtlcHQgICAgID0gW3QgZm9yIHQgaW4gdGFza3MKICAgICAgICAgICAgICAg"
    "ICAgICBpZiB0LmdldCgic3RhdHVzIikgbm90IGluIHsiY29tcGxldGVkIiwiY2FuY2VsbGVkIn1dCiAgICAgICAgcmVtb3ZlZCAg"
    "PSBsZW4odGFza3MpIC0gbGVuKGtlcHQpCiAgICAgICAgaWYgcmVtb3ZlZDoKICAgICAgICAgICAgc2VsZi5zYXZlX2FsbChrZXB0"
    "KQogICAgICAgIHJldHVybiByZW1vdmVkCgogICAgZGVmIHVwZGF0ZV9nb29nbGVfc3luYyhzZWxmLCB0YXNrX2lkOiBzdHIsIHN5"
    "bmNfc3RhdHVzOiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgIGdvb2dsZV9ldmVudF9pZDogc3RyID0gIiIsCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGVycm9yOiBzdHIgPSAiIikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3MgPSBz"
    "ZWxmLmxvYWRfYWxsKCkKICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0gdGFza19p"
    "ZDoKICAgICAgICAgICAgICAgIHRbInN5bmNfc3RhdHVzIl0gICAgPSBzeW5jX3N0YXR1cwogICAgICAgICAgICAgICAgdFsibGFz"
    "dF9zeW5jZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgaWYgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAg"
    "ICAgICAgICAgICAgIHRbImdvb2dsZV9ldmVudF9pZCJdID0gZ29vZ2xlX2V2ZW50X2lkCiAgICAgICAgICAgICAgICBpZiBlcnJv"
    "cjoKICAgICAgICAgICAgICAgICAgICB0LnNldGRlZmF1bHQoIm1ldGFkYXRhIiwge30pCiAgICAgICAgICAgICAgICAgICAgdFsi"
    "bWV0YWRhdGEiXVsiZ29vZ2xlX3N5bmNfZXJyb3IiXSA9IGVycm9yWzoyNDBdCiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxs"
    "KHRhc2tzKQogICAgICAgICAgICAgICAgcmV0dXJuIHQKICAgICAgICByZXR1cm4gTm9uZQoKICAgICMg4pSA4pSAIERVRSBFVkVO"
    "VCBERVRFQ1RJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBk"
    "ZWYgZ2V0X2R1ZV9ldmVudHMoc2VsZikgLT4gbGlzdFt0dXBsZVtzdHIsIGRpY3RdXToKICAgICAgICAiIiIKICAgICAgICBDaGVj"
    "ayBhbGwgdGFza3MgZm9yIGR1ZS9wcmUtdHJpZ2dlci9yZXRyeSBldmVudHMuCiAgICAgICAgUmV0dXJucyBsaXN0IG9mIChldmVu"
    "dF90eXBlLCB0YXNrKSB0dXBsZXMuCiAgICAgICAgZXZlbnRfdHlwZTogInByZSIgfCAiZHVlIiB8ICJyZXRyeSIKCiAgICAgICAg"
    "TW9kaWZpZXMgdGFzayBzdGF0dXNlcyBpbiBwbGFjZSBhbmQgc2F2ZXMuCiAgICAgICAgQ2FsbCBmcm9tIEFQU2NoZWR1bGVyIGV2"
    "ZXJ5IDMwIHNlY29uZHMuCiAgICAgICAgIiIiCiAgICAgICAgbm93ICAgID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpCiAg"
    "ICAgICAgdGFza3MgID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZXZlbnRzID0gW10KICAgICAgICBjaGFuZ2VkID0gRmFsc2UK"
    "CiAgICAgICAgZm9yIHRhc2sgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHRhc2suZ2V0KCJhY2tub3dsZWRnZWRfYXQiKToKICAg"
    "ICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBzdGF0dXMgICA9IHRhc2suZ2V0KCJzdGF0dXMiLCAicGVuZGluZyIp"
    "CiAgICAgICAgICAgIGR1ZSAgICAgID0gc2VsZi5fcGFyc2VfbG9jYWwodGFzay5nZXQoImR1ZV9hdCIpKQogICAgICAgICAgICBw"
    "cmUgICAgICA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJwcmVfdHJpZ2dlciIpKQogICAgICAgICAgICBuZXh0X3JldCA9"
    "IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJuZXh0X3JldHJ5X2F0IikpCiAgICAgICAgICAgIGRlYWRsaW5lID0gc2VsZi5f"
    "cGFyc2VfbG9jYWwodGFzay5nZXQoImFsZXJ0X2RlYWRsaW5lIikpCgogICAgICAgICAgICAjIFByZS10cmlnZ2VyCiAgICAgICAg"
    "ICAgIGlmIChzdGF0dXMgPT0gInBlbmRpbmciIGFuZCBwcmUgYW5kIG5vdyA+PSBwcmUKICAgICAgICAgICAgICAgICAgICBhbmQg"
    "bm90IHRhc2suZ2V0KCJwcmVfYW5ub3VuY2VkIikpOgogICAgICAgICAgICAgICAgdGFza1sicHJlX2Fubm91bmNlZCJdID0gVHJ1"
    "ZQogICAgICAgICAgICAgICAgZXZlbnRzLmFwcGVuZCgoInByZSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRy"
    "dWUKCiAgICAgICAgICAgICMgRHVlIHRyaWdnZXIKICAgICAgICAgICAgaWYgc3RhdHVzID09ICJwZW5kaW5nIiBhbmQgZHVlIGFu"
    "ZCBub3cgPj0gZHVlOgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICAgICAgID0gInRyaWdnZXJlZCIKICAgICAg"
    "ICAgICAgICAgIHRhc2tbImxhc3RfdHJpZ2dlcmVkX2F0Il09IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgdGFza1si"
    "YWxlcnRfZGVhZGxpbmUiXSAgID0gKAogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKSArIHRp"
    "bWVkZWx0YShtaW51dGVzPTMpCiAgICAgICAgICAgICAgICApLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAg"
    "ICAgICAgICBldmVudHMuYXBwZW5kKCgiZHVlIiwgdGFzaykpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAg"
    "ICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICMgU25vb3plIGFmdGVyIDMtbWludXRlIHdpbmRvdwogICAgICAgICAgICBp"
    "ZiBzdGF0dXMgPT0gInRyaWdnZXJlZCIgYW5kIGRlYWRsaW5lIGFuZCBub3cgPj0gZGVhZGxpbmU6CiAgICAgICAgICAgICAgICB0"
    "YXNrWyJzdGF0dXMiXSAgICAgICAgPSAic25vb3plZCIKICAgICAgICAgICAgICAgIHRhc2tbIm5leHRfcmV0cnlfYXQiXSA9ICgK"
    "ICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0xMikKICAg"
    "ICAgICAgICAgICAgICkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVl"
    "CiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgIyBSZXRyeQogICAgICAgICAgICBpZiBzdGF0dXMgaW4geyJy"
    "ZXRyeV9wZW5kaW5nIiwic25vb3plZCJ9IGFuZCBuZXh0X3JldCBhbmQgbm93ID49IG5leHRfcmV0OgogICAgICAgICAgICAgICAg"
    "dGFza1sic3RhdHVzIl0gICAgICAgICAgICA9ICJ0cmlnZ2VyZWQiCiAgICAgICAgICAgICAgICB0YXNrWyJyZXRyeV9jb3VudCJd"
    "ICAgICAgID0gaW50KHRhc2suZ2V0KCJyZXRyeV9jb3VudCIsMCkpICsgMQogICAgICAgICAgICAgICAgdGFza1sibGFzdF90cmln"
    "Z2VyZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgdGFza1siYWxlcnRfZGVhZGxpbmUiXSAgICA9ICgK"
    "ICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0zKQogICAg"
    "ICAgICAgICAgICAgKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgdGFza1sibmV4dF9yZXRy"
    "eV9hdCJdICAgICA9IE5vbmUKICAgICAgICAgICAgICAgIGV2ZW50cy5hcHBlbmQoKCJyZXRyeSIsIHRhc2spKQogICAgICAgICAg"
    "ICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICAgICAgaWYgY2hhbmdlZDoKICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykK"
    "ICAgICAgICByZXR1cm4gZXZlbnRzCgogICAgZGVmIF9wYXJzZV9sb2NhbChzZWxmLCB2YWx1ZTogc3RyKSAtPiBPcHRpb25hbFtk"
    "YXRldGltZV06CiAgICAgICAgIiIiUGFyc2UgSVNPIHN0cmluZyB0byB0aW1lem9uZS1hd2FyZSBkYXRldGltZSBmb3IgY29tcGFy"
    "aXNvbi4iIiIKICAgICAgICBkdCA9IHBhcnNlX2lzbyh2YWx1ZSkKICAgICAgICBpZiBkdCBpcyBOb25lOgogICAgICAgICAgICBy"
    "ZXR1cm4gTm9uZQogICAgICAgIGlmIGR0LnR6aW5mbyBpcyBOb25lOgogICAgICAgICAgICBkdCA9IGR0LmFzdGltZXpvbmUoKQog"
    "ICAgICAgIHJldHVybiBkdAoKICAgICMg4pSA4pSAIE5BVFVSQUwgTEFOR1VBR0UgUEFSU0lORyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBjbGFzc2lmeV9pbnRlbnQodGV4dDogc3Ry"
    "KSAtPiBkaWN0OgogICAgICAgICIiIgogICAgICAgIENsYXNzaWZ5IHVzZXIgaW5wdXQgYXMgdGFzay9yZW1pbmRlci90aW1lci9j"
    "aGF0LgogICAgICAgIFJldHVybnMgeyJpbnRlbnQiOiBzdHIsICJjbGVhbmVkX2lucHV0Ijogc3RyfQogICAgICAgICIiIgogICAg"
    "ICAgIGltcG9ydCByZQogICAgICAgICMgU3RyaXAgY29tbW9uIGludm9jYXRpb24gcHJlZml4ZXMKICAgICAgICBjbGVhbmVkID0g"
    "cmUuc3ViKAogICAgICAgICAgICByZiJeXHMqKD86e0RFQ0tfTkFNRS5sb3dlcigpfXxoZXlccyt7REVDS19OQU1FLmxvd2VyKCl9"
    "KVxzKiw/XHMqWzpcLV0/XHMqIiwKICAgICAgICAgICAgIiIsIHRleHQsIGZsYWdzPXJlLkkKICAgICAgICApLnN0cmlwKCkKCiAg"
    "ICAgICAgbG93ID0gY2xlYW5lZC5sb3dlcigpCgogICAgICAgIHRpbWVyX3BhdHMgICAgPSBbciJcYnNldCg/OlxzK2EpP1xzK3Rp"
    "bWVyXGIiLCByIlxidGltZXJccytmb3JcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICByIlxic3RhcnQoPzpccythKT9ccyt0"
    "aW1lclxiIl0KICAgICAgICByZW1pbmRlcl9wYXRzID0gW3IiXGJyZW1pbmQgbWVcYiIsIHIiXGJzZXQoPzpccythKT9ccytyZW1p"
    "bmRlclxiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJhZGQoPzpccythKT9ccytyZW1pbmRlclxiIiwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIHIiXGJzZXQoPzpccythbj8pP1xzK2FsYXJtXGIiLCByIlxiYWxhcm1ccytmb3JcYiJdCiAgICAgICAg"
    "dGFza19wYXRzICAgICA9IFtyIlxiYWRkKD86XHMrYSk/XHMrdGFza1xiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJj"
    "cmVhdGUoPzpccythKT9ccyt0YXNrXGIiLCByIlxibmV3XHMrdGFza1xiIl0KCiAgICAgICAgaW1wb3J0IHJlIGFzIF9yZQogICAg"
    "ICAgIGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gdGltZXJfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9ICJ0"
    "aW1lciIKICAgICAgICBlbGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gcmVtaW5kZXJfcGF0cyk6CiAgICAgICAg"
    "ICAgIGludGVudCA9ICJyZW1pbmRlciIKICAgICAgICBlbGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gdGFza19w"
    "YXRzKToKICAgICAgICAgICAgaW50ZW50ID0gInRhc2siCiAgICAgICAgZWxzZToKICAgICAgICAgICAgaW50ZW50ID0gImNoYXQi"
    "CgogICAgICAgIHJldHVybiB7ImludGVudCI6IGludGVudCwgImNsZWFuZWRfaW5wdXQiOiBjbGVhbmVkfQoKICAgIEBzdGF0aWNt"
    "ZXRob2QKICAgIGRlZiBwYXJzZV9kdWVfZGF0ZXRpbWUodGV4dDogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICAgICAg"
    "IiIiCiAgICAgICAgUGFyc2UgbmF0dXJhbCBsYW5ndWFnZSB0aW1lIGV4cHJlc3Npb24gZnJvbSB0YXNrIHRleHQuCiAgICAgICAg"
    "SGFuZGxlczogImluIDMwIG1pbnV0ZXMiLCAiYXQgM3BtIiwgInRvbW9ycm93IGF0IDlhbSIsCiAgICAgICAgICAgICAgICAgImlu"
    "IDIgaG91cnMiLCAiYXQgMTU6MzAiLCBldGMuCiAgICAgICAgUmV0dXJucyBhIGRhdGV0aW1lIG9yIE5vbmUgaWYgdW5wYXJzZWFi"
    "bGUuCiAgICAgICAgIiIiCiAgICAgICAgaW1wb3J0IHJlCiAgICAgICAgbm93ICA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAgbG93"
    "ICA9IHRleHQubG93ZXIoKS5zdHJpcCgpCgogICAgICAgICMgImluIFggbWludXRlcy9ob3Vycy9kYXlzIgogICAgICAgIG0gPSBy"
    "ZS5zZWFyY2goCiAgICAgICAgICAgIHIiaW5ccysoXGQrKVxzKihtaW51dGV8bWlufGhvdXJ8aHJ8ZGF5fHNlY29uZHxzZWMpIiwK"
    "ICAgICAgICAgICAgbG93CiAgICAgICAgKQogICAgICAgIGlmIG06CiAgICAgICAgICAgIG4gICAgPSBpbnQobS5ncm91cCgxKSkK"
    "ICAgICAgICAgICAgdW5pdCA9IG0uZ3JvdXAoMikKICAgICAgICAgICAgaWYgIm1pbiIgaW4gdW5pdDogIHJldHVybiBub3cgKyB0"
    "aW1lZGVsdGEobWludXRlcz1uKQogICAgICAgICAgICBpZiAiaG91ciIgaW4gdW5pdCBvciAiaHIiIGluIHVuaXQ6IHJldHVybiBu"
    "b3cgKyB0aW1lZGVsdGEoaG91cnM9bikKICAgICAgICAgICAgaWYgImRheSIgIGluIHVuaXQ6IHJldHVybiBub3cgKyB0aW1lZGVs"
    "dGEoZGF5cz1uKQogICAgICAgICAgICBpZiAic2VjIiAgaW4gdW5pdDogcmV0dXJuIG5vdyArIHRpbWVkZWx0YShzZWNvbmRzPW4p"
    "CgogICAgICAgICMgImF0IEhIOk1NIiBvciAiYXQgSDpNTWFtL3BtIgogICAgICAgIG0gPSByZS5zZWFyY2goCiAgICAgICAgICAg"
    "IHIiYXRccysoXGR7MSwyfSkoPzo6KFxkezJ9KSk/XHMqKGFtfHBtKT8iLAogICAgICAgICAgICBsb3cKICAgICAgICApCiAgICAg"
    "ICAgaWYgbToKICAgICAgICAgICAgaHIgID0gaW50KG0uZ3JvdXAoMSkpCiAgICAgICAgICAgIG1uICA9IGludChtLmdyb3VwKDIp"
    "KSBpZiBtLmdyb3VwKDIpIGVsc2UgMAogICAgICAgICAgICBhcG0gPSBtLmdyb3VwKDMpCiAgICAgICAgICAgIGlmIGFwbSA9PSAi"
    "cG0iIGFuZCBociA8IDEyOiBociArPSAxMgogICAgICAgICAgICBpZiBhcG0gPT0gImFtIiBhbmQgaHIgPT0gMTI6IGhyID0gMAog"
    "ICAgICAgICAgICBkdCA9IG5vdy5yZXBsYWNlKGhvdXI9aHIsIG1pbnV0ZT1tbiwgc2Vjb25kPTAsIG1pY3Jvc2Vjb25kPTApCiAg"
    "ICAgICAgICAgIGlmIGR0IDw9IG5vdzoKICAgICAgICAgICAgICAgIGR0ICs9IHRpbWVkZWx0YShkYXlzPTEpCiAgICAgICAgICAg"
    "IHJldHVybiBkdAoKICAgICAgICAjICJ0b21vcnJvdyBhdCAuLi4iICAocmVjdXJzZSBvbiB0aGUgImF0IiBwYXJ0KQogICAgICAg"
    "IGlmICJ0b21vcnJvdyIgaW4gbG93OgogICAgICAgICAgICB0b21vcnJvd190ZXh0ID0gcmUuc3ViKHIidG9tb3Jyb3ciLCAiIiwg"
    "bG93KS5zdHJpcCgpCiAgICAgICAgICAgIHJlc3VsdCA9IFRhc2tNYW5hZ2VyLnBhcnNlX2R1ZV9kYXRldGltZSh0b21vcnJvd190"
    "ZXh0KQogICAgICAgICAgICBpZiByZXN1bHQ6CiAgICAgICAgICAgICAgICByZXR1cm4gcmVzdWx0ICsgdGltZWRlbHRhKGRheXM9"
    "MSkKCiAgICAgICAgcmV0dXJuIE5vbmUKCgojIOKUgOKUgCBSRVFVSVJFTUVOVFMuVFhUIEdFTkVSQVRPUiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIHdyaXRlX3JlcXVpcmVt"
    "ZW50c190eHQoKSAtPiBOb25lOgogICAgIiIiCiAgICBXcml0ZSByZXF1aXJlbWVudHMudHh0IG5leHQgdG8gdGhlIGRlY2sgZmls"
    "ZSBvbiBmaXJzdCBydW4uCiAgICBIZWxwcyB1c2VycyBpbnN0YWxsIGFsbCBkZXBlbmRlbmNpZXMgd2l0aCBvbmUgcGlwIGNvbW1h"
    "bmQuCiAgICAiIiIKICAgIHJlcV9wYXRoID0gUGF0aChDRkcuZ2V0KCJiYXNlX2RpciIsIHN0cihTQ1JJUFRfRElSKSkpIC8gInJl"
    "cXVpcmVtZW50cy50eHQiCiAgICBpZiByZXFfcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4KCiAgICBjb250ZW50ID0gIiIi"
    "XAojIE1vcmdhbm5hIERlY2sg4oCUIFJlcXVpcmVkIERlcGVuZGVuY2llcwojIEluc3RhbGwgYWxsIHdpdGg6IHBpcCBpbnN0YWxs"
    "IC1yIHJlcXVpcmVtZW50cy50eHQKCiMgQ29yZSBVSQpQeVNpZGU2CgojIFNjaGVkdWxpbmcgKGlkbGUgdGltZXIsIGF1dG9zYXZl"
    "LCByZWZsZWN0aW9uIGN5Y2xlcykKYXBzY2hlZHVsZXIKCiMgTG9nZ2luZwpsb2d1cnUKCiMgU291bmQgcGxheWJhY2sgKFdBViAr"
    "IE1QMykKcHlnYW1lCgojIERlc2t0b3Agc2hvcnRjdXQgY3JlYXRpb24gKFdpbmRvd3Mgb25seSkKcHl3aW4zMgoKIyBTeXN0ZW0g"
    "bW9uaXRvcmluZyAoQ1BVLCBSQU0sIGRyaXZlcywgbmV0d29yaykKcHN1dGlsCgojIEhUVFAgcmVxdWVzdHMKcmVxdWVzdHMKCiMg"
    "R29vZ2xlIGludGVncmF0aW9uIChDYWxlbmRhciwgRHJpdmUsIERvY3MsIEdtYWlsKQpnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQK"
    "Z29vZ2xlLWF1dGgtb2F1dGhsaWIKZ29vZ2xlLWF1dGgKCiMg4pSA4pSAIE9wdGlvbmFsIChsb2NhbCBtb2RlbCBvbmx5KSDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBVbmNvbW1lbnQgaWYg"
    "dXNpbmcgYSBsb2NhbCBIdWdnaW5nRmFjZSBtb2RlbDoKIyB0b3JjaAojIHRyYW5zZm9ybWVycwojIGFjY2VsZXJhdGUKCiMg4pSA"
    "4pSAIE9wdGlvbmFsIChOVklESUEgR1BVIG1vbml0b3JpbmcpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAojIFVuY29tbWVudCBpZiB5b3UgaGF2ZSBhbiBOVklESUEgR1BVOgojIHB5bnZtbAoiIiIKICAgIHJlcV9wYXRoLndy"
    "aXRlX3RleHQoY29udGVudCwgZW5jb2Rpbmc9InV0Zi04IikKCgojIOKUgOKUgCBQQVNTIDQgQ09NUExFVEUg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiMgTWVtb3J5LCBTZXNzaW9uLCBMZXNzb25zTGVhcm5lZCwgVGFza01hbmFnZXIgYWxsIGRlZmluZWQu"
    "CiMgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGF1dG8tc2VlZGVkIG9uIGZpcnN0IHJ1bi4KIyByZXF1aXJlbWVudHMudHh0IHdyaXR0"
    "ZW4gb24gZmlyc3QgcnVuLgojCiMgTmV4dDogUGFzcyA1IOKAlCBUYWIgQ29udGVudCBDbGFzc2VzCiMgKFNMU2NhbnNUYWIsIFNM"
    "Q29tbWFuZHNUYWIsIEpvYlRyYWNrZXJUYWIsIFJlY29yZHNUYWIsCiMgIFRhc2tzVGFiLCBTZWxmVGFiLCBEaWFnbm9zdGljc1Rh"
    "YikKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgNTogVEFCIENPTlRFTlQgQ0xBU1NFUwojCiMgVGFi"
    "cyBkZWZpbmVkIGhlcmU6CiMgICBTTFNjYW5zVGFiICAgICAg4oCUIGdyaW1vaXJlLWNhcmQgc3R5bGUsIHJlYnVpbHQgKERlbGV0"
    "ZSBhZGRlZCwgTW9kaWZ5IGZpeGVkLAojICAgICAgICAgICAgICAgICAgICAgcGFyc2VyIGZpeGVkLCBjb3B5LXRvLWNsaXBib2Fy"
    "ZCBwZXIgaXRlbSkKIyAgIFNMQ29tbWFuZHNUYWIgICDigJQgZ290aGljIHRhYmxlLCBjb3B5IGNvbW1hbmQgdG8gY2xpcGJvYXJk"
    "CiMgICBKb2JUcmFja2VyVGFiICAg4oCUIGZ1bGwgcmVidWlsZCBmcm9tIHNwZWMsIENTVi9UU1YgZXhwb3J0CiMgICBSZWNvcmRz"
    "VGFiICAgICAg4oCUIEdvb2dsZSBEcml2ZS9Eb2NzIHdvcmtzcGFjZQojICAgVGFza3NUYWIgICAgICAgIOKAlCB0YXNrIHJlZ2lz"
    "dHJ5ICsgbWluaSBjYWxlbmRhcgojICAgU2VsZlRhYiAgICAgICAgIOKAlCBpZGxlIG5hcnJhdGl2ZSBvdXRwdXQgKyBQb0kgbGlz"
    "dAojICAgRGlhZ25vc3RpY3NUYWIgIOKAlCBsb2d1cnUgb3V0cHV0ICsgaGFyZHdhcmUgcmVwb3J0ICsgam91cm5hbCBsb2FkIG5v"
    "dGljZXMKIyAgIExlc3NvbnNUYWIgICAgICDigJQgTFNMIEZvcmJpZGRlbiBSdWxlc2V0ICsgY29kZSBsZXNzb25zIGJyb3dzZXIK"
    "IyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZAKCmltcG9ydCByZSBhcyBfcmUKCgojIOKUgOKUgCBTSEFSRUQgR09USElDIFRBQkxFIFNUWUxFIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgX2dv"
    "dGhpY190YWJsZV9zdHlsZSgpIC0+IHN0cjoKICAgIHJldHVybiBmIiIiCiAgICAgICAgUVRhYmxlV2lkZ2V0IHt7CiAgICAgICAg"
    "ICAgIGJhY2tncm91bmQ6IHtDX0JHMn07CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgICAgICAgICAgYm9yZGVyOiAx"
    "cHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAgICBncmlkbGluZS1jb2xvcjoge0NfQk9SREVSfTsKICAgICAgICAg"
    "ICAgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsKICAgICAgICAgICAgZm9udC1zaXplOiAxMXB4OwogICAgICAgIH19"
    "CiAgICAgICAgUVRhYmxlV2lkZ2V0OjppdGVtOnNlbGVjdGVkIHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05f"
    "RElNfTsKICAgICAgICAgICAgY29sb3I6IHtDX0dPTERfQlJJR0hUfTsKICAgICAgICB9fQogICAgICAgIFFUYWJsZVdpZGdldDo6"
    "aXRlbTphbHRlcm5hdGUge3sKICAgICAgICAgICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgICAgICB9fQogICAgICAgIFFIZWFk"
    "ZXJWaWV3OjpzZWN0aW9uIHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0JHM307CiAgICAgICAgICAgIGNvbG9yOiB7Q19H"
    "T0xEfTsKICAgICAgICAgICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAgICBwYWRkaW5nOiA0"
    "cHggNnB4OwogICAgICAgICAgICBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOwogICAgICAgICAgICBmb250LXNpemU6"
    "IDEwcHg7CiAgICAgICAgICAgIGZvbnQtd2VpZ2h0OiBib2xkOwogICAgICAgICAgICBsZXR0ZXItc3BhY2luZzogMXB4OwogICAg"
    "ICAgIH19CiAgICAiIiIKCmRlZiBfZ290aGljX2J0bih0ZXh0OiBzdHIsIHRvb2x0aXA6IHN0ciA9ICIiKSAtPiBRUHVzaEJ1dHRv"
    "bjoKICAgIGJ0biA9IFFQdXNoQnV0dG9uKHRleHQpCiAgICBidG4uc2V0U3R5bGVTaGVldCgKICAgICAgICBmImJhY2tncm91bmQ6"
    "IHtDX0NSSU1TT05fRElNfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09O"
    "fTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNp"
    "emU6IDEwcHg7ICIKICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiA0cHggMTBweDsgbGV0dGVyLXNwYWNpbmc6"
    "IDFweDsiCiAgICApCiAgICBpZiB0b29sdGlwOgogICAgICAgIGJ0bi5zZXRUb29sVGlwKHRvb2x0aXApCiAgICByZXR1cm4gYnRu"
    "CgpkZWYgX3NlY3Rpb25fbGJsKHRleHQ6IHN0cikgLT4gUUxhYmVsOgogICAgbGJsID0gUUxhYmVsKHRleHQpCiAgICBsYmwuc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAi"
    "CiAgICAgICAgZiJsZXR0ZXItc3BhY2luZzogMnB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICkKICAg"
    "IHJldHVybiBsYmwKCgojIOKUgOKUgCBTTCBTQ0FOUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNs"
    "YXNzIFNMU2NhbnNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFNlY29uZCBMaWZlIGF2YXRhciBzY2FubmVyIHJlc3VsdHMgbWFu"
    "YWdlci4KICAgIFJlYnVpbHQgZnJvbSBzcGVjOgogICAgICAtIENhcmQvZ3JpbW9pcmUtZW50cnkgc3R5bGUgZGlzcGxheQogICAg"
    "ICAtIEFkZCAod2l0aCB0aW1lc3RhbXAtYXdhcmUgcGFyc2VyKQogICAgICAtIERpc3BsYXkgKGNsZWFuIGl0ZW0vY3JlYXRvciB0"
    "YWJsZSkKICAgICAgLSBNb2RpZnkgKGVkaXQgbmFtZSwgZGVzY3JpcHRpb24sIGluZGl2aWR1YWwgaXRlbXMpCiAgICAgIC0gRGVs"
    "ZXRlICh3YXMgbWlzc2luZyDigJQgbm93IHByZXNlbnQpCiAgICAgIC0gUmUtcGFyc2UgKHdhcyAnUmVmcmVzaCcg4oCUIHJlLXJ1"
    "bnMgcGFyc2VyIG9uIHN0b3JlZCByYXcgdGV4dCkKICAgICAgLSBDb3B5LXRvLWNsaXBib2FyZCBvbiBhbnkgaXRlbQogICAgIiIi"
    "CgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1lbW9yeV9kaXI6IFBhdGgsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9f"
    "aW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRoICAgID0gY2ZnX3BhdGgoInNsIikgLyAic2xfc2NhbnMuanNvbmwiCiAg"
    "ICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQ6IE9wdGlvbmFsW3N0"
    "cl0gPSBOb25lCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91"
    "aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNN"
    "YXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgQnV0dG9uIGJhcgogICAgICAg"
    "IGJhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgICA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIiwgICAg"
    "ICJBZGQgYSBuZXcgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRuX2Rpc3BsYXkgPSBfZ290aGljX2J0bigi4p2nIERpc3BsYXkiLCAi"
    "U2hvdyBzZWxlY3RlZCBzY2FuIGRldGFpbHMiKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkgID0gX2dvdGhpY19idG4oIuKcpyBN"
    "b2RpZnkiLCAgIkVkaXQgc2VsZWN0ZWQgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSAgPSBfZ290aGljX2J0bigi4pyX"
    "IERlbGV0ZSIsICAiRGVsZXRlIHNlbGVjdGVkIHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9yZXBhcnNlID0gX2dvdGhpY19idG4o"
    "IuKGuyBSZS1wYXJzZSIsIlJlLXBhcnNlIHJhdyB0ZXh0IG9mIHNlbGVjdGVkIHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9hZGQu"
    "Y2xpY2tlZC5jb25uZWN0KHNlbGYuX3Nob3dfYWRkKQogICAgICAgIHNlbGYuX2J0bl9kaXNwbGF5LmNsaWNrZWQuY29ubmVjdChz"
    "ZWxmLl9zaG93X2Rpc3BsYXkpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2hvd19tb2Rp"
    "ZnkpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYu"
    "X2J0bl9yZXBhcnNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19yZXBhcnNlKQogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5f"
    "YWRkLCBzZWxmLl9idG5fZGlzcGxheSwgc2VsZi5fYnRuX21vZGlmeSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX2RlbGV0"
    "ZSwgc2VsZi5fYnRuX3JlcGFyc2UpOgogICAgICAgICAgICBiYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2go"
    "KQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAgICAgIyBTdGFjazogbGlzdCB2aWV3IHwgYWRkIGZvcm0gfCBkaXNw"
    "bGF5IHwgbW9kaWZ5CiAgICAgICAgc2VsZi5fc3RhY2sgPSBRU3RhY2tlZFdpZGdldCgpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQo"
    "c2VsZi5fc3RhY2ssIDEpCgogICAgICAgICMg4pSA4pSAIFBBR0UgMDogc2NhbiBsaXN0IChncmltb2lyZSBjYXJkcykg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAg"
    "cDAgPSBRV2lkZ2V0KCkKICAgICAgICBsMCA9IFFWQm94TGF5b3V0KHAwKQogICAgICAgIGwwLnNldENvbnRlbnRzTWFyZ2lucygw"
    "LCAwLCAwLCAwKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsID0gUVNjcm9sbEFyZWEoKQogICAgICAgIHNlbGYuX2NhcmRfc2Ny"
    "b2xsLnNldFdpZGdldFJlc2l6YWJsZShUcnVlKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFN0eWxlU2hlZXQoZiJiYWNr"
    "Z3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IG5vbmU7IikKICAgICAgICBzZWxmLl9jYXJkX2NvbnRhaW5lciA9IFFXaWRnZXQoKQog"
    "ICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0ICAgID0gUVZCb3hMYXlvdXQoc2VsZi5fY2FyZF9jb250YWluZXIpCiAgICAgICAgc2Vs"
    "Zi5fY2FyZF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuc2V0"
    "U3BhY2luZyg0KQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LmFkZFN0cmV0Y2goKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xs"
    "LnNldFdpZGdldChzZWxmLl9jYXJkX2NvbnRhaW5lcikKICAgICAgICBsMC5hZGRXaWRnZXQoc2VsZi5fY2FyZF9zY3JvbGwpCiAg"
    "ICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAwKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDE6IGFkZCBmb3JtIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAxID0gUVdpZGdldCgpCiAgICAgICAg"
    "bDEgPSBRVkJveExheW91dChwMSkKICAgICAgICBsMS5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBsMS5z"
    "ZXRTcGFjaW5nKDQpCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFNDQU4gTkFNRSAoYXV0by1kZXRlY3Rl"
    "ZCkiKSkKICAgICAgICBzZWxmLl9hZGRfbmFtZSAgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNl"
    "aG9sZGVyVGV4dCgiQXV0by1kZXRlY3RlZCBmcm9tIHNjYW4gdGV4dCIpCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9u"
    "YW1lKQogICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBERVNDUklQVElPTiIpKQogICAgICAgIHNlbGYuX2Fk"
    "ZF9kZXNjICA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fYWRkX2Rlc2Muc2V0TWF4aW11bUhlaWdodCg2MCkKICAgICAgICBs"
    "MS5hZGRXaWRnZXQoc2VsZi5fYWRkX2Rlc2MpCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFJBVyBTQ0FO"
    "IFRFWFQgKHBhc3RlIGhlcmUpIikpCiAgICAgICAgc2VsZi5fYWRkX3JhdyAgID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9h"
    "ZGRfcmF3LnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAgICAgIlBhc3RlIHRoZSByYXcgU2Vjb25kIExpZmUgc2NhbiBvdXRw"
    "dXQgaGVyZS5cbiIKICAgICAgICAgICAgIlRpbWVzdGFtcHMgbGlrZSBbMTE6NDddIHdpbGwgYmUgdXNlZCB0byBzcGxpdCBpdGVt"
    "cyBjb3JyZWN0bHkuIgogICAgICAgICkKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX3JhdywgMSkKICAgICAgICAjIFBy"
    "ZXZpZXcgb2YgcGFyc2VkIGl0ZW1zCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFBBUlNFRCBJVEVNUyBQ"
    "UkVWSUVXIikpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcgPSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl9hZGRf"
    "cHJldmlldy5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiSXRlbSIsICJDcmVhdG9yIl0pCiAgICAgICAgc2VsZi5fYWRkX3By"
    "ZXZpZXcuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5S"
    "ZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25S"
    "ZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fYWRk"
    "X3ByZXZpZXcuc2V0TWF4aW11bUhlaWdodCgxMjApCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0U3R5bGVTaGVldChfZ290"
    "aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9wcmV2aWV3KQogICAgICAgIHNlbGYuX2Fk"
    "ZF9yYXcudGV4dENoYW5nZWQuY29ubmVjdChzZWxmLl9wcmV2aWV3X3BhcnNlKQoKICAgICAgICBidG5zMSA9IFFIQm94TGF5b3V0"
    "KCkKICAgICAgICBzMSA9IF9nb3RoaWNfYnRuKCLinKYgU2F2ZSIpOyBjMSA9IF9nb3RoaWNfYnRuKCLinJcgQ2FuY2VsIikKICAg"
    "ICAgICBzMS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIGMxLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNl"
    "bGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKSkKICAgICAgICBidG5zMS5hZGRXaWRnZXQoczEpOyBidG5zMS5hZGRXaWRnZXQo"
    "YzEpOyBidG5zMS5hZGRTdHJldGNoKCkKICAgICAgICBsMS5hZGRMYXlvdXQoYnRuczEpCiAgICAgICAgc2VsZi5fc3RhY2suYWRk"
    "V2lkZ2V0KHAxKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDI6IGRpc3BsYXkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDIgPSBRV2lkZ2V0KCkKICAgICAgICBsMiA9IFFWQm94TGF5b3V0KHAy"
    "KQogICAgICAgIGwyLnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2Rpc3BfbmFtZSAgPSBRTGFi"
    "ZWwoKQogICAgICAgIHNlbGYuX2Rpc3BfbmFtZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0JS"
    "SUdIVH07IGZvbnQtc2l6ZTogMTNweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RF"
    "Q0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjICA9IFFMYWJlbCgpCiAgICAgICAgc2Vs"
    "Zi5fZGlzcF9kZXNjLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNl"
    "cmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNlbGYu"
    "X2Rpc3BfdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIkl0ZW0iLCAiQ3JlYXRvciJdKQogICAgICAgIHNlbGYuX2Rp"
    "c3BfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmll"
    "dy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlv"
    "blJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9k"
    "aXNwX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0"
    "Q29udGV4dE1lbnVQb2xpY3koCiAgICAgICAgICAgIFF0LkNvbnRleHRNZW51UG9saWN5LkN1c3RvbUNvbnRleHRNZW51KQogICAg"
    "ICAgIHNlbGYuX2Rpc3BfdGFibGUuY3VzdG9tQ29udGV4dE1lbnVSZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5f"
    "aXRlbV9jb250ZXh0X21lbnUpCgogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9kaXNwX25hbWUpCiAgICAgICAgbDIuYWRkV2lk"
    "Z2V0KHNlbGYuX2Rpc3BfZGVzYykKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fZGlzcF90YWJsZSwgMSkKCiAgICAgICAgY29w"
    "eV9oaW50ID0gUUxhYmVsKCJSaWdodC1jbGljayBhbnkgaXRlbSB0byBjb3B5IGl0IHRvIGNsaXBib2FyZC4iKQogICAgICAgIGNv"
    "cHlfaGludC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBm"
    "b250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgbDIuYWRkV2lkZ2V0KGNvcHlfaGludCkK"
    "CiAgICAgICAgYmsyID0gX2dvdGhpY19idG4oIuKXgCBCYWNrIikKICAgICAgICBiazIuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTog"
    "c2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDApKQogICAgICAgIGwyLmFkZFdpZGdldChiazIpCiAgICAgICAgc2VsZi5fc3Rh"
    "Y2suYWRkV2lkZ2V0KHAyKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDM6IG1vZGlmeSDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBwMyA9IFFXaWRnZXQoKQogICAgICAgIGwzID0gUVZCb3hM"
    "YXlvdXQocDMpCiAgICAgICAgbDMuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgbDMuc2V0U3BhY2luZyg0"
    "KQogICAgICAgIGwzLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBOQU1FIikpCiAgICAgICAgc2VsZi5fbW9kX25hbWUgPSBR"
    "TGluZUVkaXQoKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9tb2RfbmFtZSkKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rp"
    "b25fbGJsKCLinacgREVTQ1JJUFRJT04iKSkKICAgICAgICBzZWxmLl9tb2RfZGVzYyA9IFFMaW5lRWRpdCgpCiAgICAgICAgbDMu"
    "YWRkV2lkZ2V0KHNlbGYuX21vZF9kZXNjKQogICAgICAgIGwzLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBJVEVNUyAoZG91"
    "YmxlLWNsaWNrIHRvIGVkaXQpIikpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDIpCiAgICAgICAg"
    "c2VsZi5fbW9kX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJJdGVtIiwgIkNyZWF0b3IiXSkKICAgICAgICBzZWxm"
    "Ll9tb2RfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVy"
    "Vmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0"
    "aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYu"
    "X21vZF90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5f"
    "bW9kX3RhYmxlLCAxKQoKICAgICAgICBidG5zMyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzMyA9IF9nb3RoaWNfYnRuKCLinKYg"
    "U2F2ZSIpOyBjMyA9IF9nb3RoaWNfYnRuKCLinJcgQ2FuY2VsIikKICAgICAgICBzMy5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9f"
    "bW9kaWZ5X3NhdmUpCiAgICAgICAgYzMuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4"
    "KDApKQogICAgICAgIGJ0bnMzLmFkZFdpZGdldChzMyk7IGJ0bnMzLmFkZFdpZGdldChjMyk7IGJ0bnMzLmFkZFN0cmV0Y2goKQog"
    "ICAgICAgIGwzLmFkZExheW91dChidG5zMykKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDMpCgogICAgIyDilIDilIAg"
    "UEFSU0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgQHN0YXRpY21ldGhvZAogICAgZGVmIHBhcnNlX3NjYW5fdGV4dChyYXc6IHN0"
    "cikgLT4gdHVwbGVbc3RyLCBsaXN0W2RpY3RdXToKICAgICAgICAiIiIKICAgICAgICBQYXJzZSByYXcgU0wgc2NhbiBvdXRwdXQg"
    "aW50byAoYXZhdGFyX25hbWUsIGl0ZW1zKS4KCiAgICAgICAgS0VZIEZJWDogQmVmb3JlIHNwbGl0dGluZywgaW5zZXJ0IG5ld2xp"
    "bmVzIGJlZm9yZSBldmVyeSBbSEg6TU1dCiAgICAgICAgdGltZXN0YW1wIHNvIHNpbmdsZS1saW5lIHBhc3RlcyB3b3JrIGNvcnJl"
    "Y3RseS4KCiAgICAgICAgRXhwZWN0ZWQgZm9ybWF0OgogICAgICAgICAgICBbMTE6NDddIEF2YXRhck5hbWUncyBwdWJsaWMgYXR0"
    "YWNobWVudHM6CiAgICAgICAgICAgIFsxMTo0N10gLjogSXRlbSBOYW1lIFtBdHRhY2htZW50XSBDUkVBVE9SOiBDcmVhdG9yTmFt"
    "ZSBbMTE6NDddIC4uLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCByYXcuc3RyaXAoKToKICAgICAgICAgICAgcmV0dXJuICJV"
    "TktOT1dOIiwgW10KCiAgICAgICAgIyDilIDilIAgU3RlcCAxOiBub3JtYWxpemUg4oCUIGluc2VydCBuZXdsaW5lcyBiZWZvcmUg"
    "dGltZXN0YW1wcyDilIDilIDilIDilIDilIDilIAKICAgICAgICBub3JtYWxpemVkID0gX3JlLnN1YihyJ1xzKihcW1xkezEsMn06"
    "XGR7Mn1cXSknLCByJ1xuXDEnLCByYXcpCiAgICAgICAgbGluZXMgPSBbbC5zdHJpcCgpIGZvciBsIGluIG5vcm1hbGl6ZWQuc3Bs"
    "aXRsaW5lcygpIGlmIGwuc3RyaXAoKV0KCiAgICAgICAgIyDilIDilIAgU3RlcCAyOiBleHRyYWN0IGF2YXRhciBuYW1lIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGF2YXRhcl9uYW1lID0gIlVOS05PV04iCiAgICAgICAgZm9yIGxpbmUgaW4gbGluZXM6"
    "CiAgICAgICAgICAgICMgIkF2YXRhck5hbWUncyBwdWJsaWMgYXR0YWNobWVudHMiIG9yIHNpbWlsYXIKICAgICAgICAgICAgbSA9"
    "IF9yZS5zZWFyY2goCiAgICAgICAgICAgICAgICByIihcd1tcd1xzXSs/KSdzXHMrcHVibGljXHMrYXR0YWNobWVudHMiLAogICAg"
    "ICAgICAgICAgICAgbGluZSwgX3JlLkkKICAgICAgICAgICAgKQogICAgICAgICAgICBpZiBtOgogICAgICAgICAgICAgICAgYXZh"
    "dGFyX25hbWUgPSBtLmdyb3VwKDEpLnN0cmlwKCkKICAgICAgICAgICAgICAgIGJyZWFrCgogICAgICAgICMg4pSA4pSAIFN0ZXAg"
    "MzogZXh0cmFjdCBpdGVtcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBpdGVtcyA9IFtd"
    "CiAgICAgICAgZm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAgICAgICMgU3RyaXAgbGVhZGluZyB0aW1lc3RhbXAKICAgICAgICAg"
    "ICAgY29udGVudCA9IF9yZS5zdWIocideXFtcZHsxLDJ9OlxkezJ9XF1ccyonLCAnJywgbGluZSkuc3RyaXAoKQogICAgICAgICAg"
    "ICBpZiBub3QgY29udGVudDoKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICMgU2tpcCBoZWFkZXIgbGluZXMK"
    "ICAgICAgICAgICAgaWYgIidzIHB1YmxpYyBhdHRhY2htZW50cyIgaW4gY29udGVudC5sb3dlcigpOgogICAgICAgICAgICAgICAg"
    "Y29udGludWUKICAgICAgICAgICAgaWYgY29udGVudC5sb3dlcigpLnN0YXJ0c3dpdGgoIm9iamVjdCIpOgogICAgICAgICAgICAg"
    "ICAgY29udGludWUKICAgICAgICAgICAgIyBTa2lwIGRpdmlkZXIgbGluZXMg4oCUIGxpbmVzIHRoYXQgYXJlIG1vc3RseSBvbmUg"
    "cmVwZWF0ZWQgY2hhcmFjdGVyCiAgICAgICAgICAgICMgZS5nLiDiloLiloLiloLiloLiloLiloLiloLiloLiloLiloLiloLiloIg"
    "b3Ig4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQIG9yIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgICAgICAgICBzdHJpcHBlZCA9IGNvbnRlbnQuc3RyaXAoIi46ICIpCiAgICAgICAgICAgIGlmIHN0cmlwcGVkIGFu"
    "ZCBsZW4oc2V0KHN0cmlwcGVkKSkgPD0gMjoKICAgICAgICAgICAgICAgIGNvbnRpbnVlICAjIG9uZSBvciB0d28gdW5pcXVlIGNo"
    "YXJzID0gZGl2aWRlciBsaW5lCgogICAgICAgICAgICAjIFRyeSB0byBleHRyYWN0IENSRUFUT1I6IGZpZWxkCiAgICAgICAgICAg"
    "IGNyZWF0b3IgPSAiVU5LTk9XTiIKICAgICAgICAgICAgaXRlbV9uYW1lID0gY29udGVudAoKICAgICAgICAgICAgY3JlYXRvcl9t"
    "YXRjaCA9IF9yZS5zZWFyY2goCiAgICAgICAgICAgICAgICByJ0NSRUFUT1I6XHMqKFtcd1xzXSs/KSg/OlxzKlxbfCQpJywgY29u"
    "dGVudCwgX3JlLkkKICAgICAgICAgICAgKQogICAgICAgICAgICBpZiBjcmVhdG9yX21hdGNoOgogICAgICAgICAgICAgICAgY3Jl"
    "YXRvciAgID0gY3JlYXRvcl9tYXRjaC5ncm91cCgxKS5zdHJpcCgpCiAgICAgICAgICAgICAgICBpdGVtX25hbWUgPSBjb250ZW50"
    "WzpjcmVhdG9yX21hdGNoLnN0YXJ0KCldLnN0cmlwKCkKCiAgICAgICAgICAgICMgU3RyaXAgYXR0YWNobWVudCBwb2ludCBzdWZm"
    "aXhlcyBsaWtlIFtMZWZ0X0Zvb3RdCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IF9yZS5zdWIocidccypcW1tcd1xzX10rXF0nLCAn"
    "JywgaXRlbV9uYW1lKS5zdHJpcCgpCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IGl0ZW1fbmFtZS5zdHJpcCgiLjogIikKCiAgICAg"
    "ICAgICAgIGlmIGl0ZW1fbmFtZSBhbmQgbGVuKGl0ZW1fbmFtZSkgPiAxOgogICAgICAgICAgICAgICAgaXRlbXMuYXBwZW5kKHsi"
    "aXRlbSI6IGl0ZW1fbmFtZSwgImNyZWF0b3IiOiBjcmVhdG9yfSkKCiAgICAgICAgcmV0dXJuIGF2YXRhcl9uYW1lLCBpdGVtcwoK"
    "ICAgICMg4pSA4pSAIENBUkQgUkVOREVSSU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9idWlsZF9jYXJkcyhzZWxmKSAtPiBOb25lOgogICAgICAgICMgQ2xlYXIg"
    "ZXhpc3RpbmcgY2FyZHMgKGtlZXAgc3RyZXRjaCkKICAgICAgICB3aGlsZSBzZWxmLl9jYXJkX2xheW91dC5jb3VudCgpID4gMToK"
    "ICAgICAgICAgICAgaXRlbSA9IHNlbGYuX2NhcmRfbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICBpZiBpdGVtLndpZGdldCgp"
    "OgogICAgICAgICAgICAgICAgaXRlbS53aWRnZXQoKS5kZWxldGVMYXRlcigpCgogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVj"
    "b3JkczoKICAgICAgICAgICAgY2FyZCA9IHNlbGYuX21ha2VfY2FyZChyZWMpCiAgICAgICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0"
    "Lmluc2VydFdpZGdldCgKICAgICAgICAgICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LmNvdW50KCkgLSAxLCBjYXJkCiAgICAgICAg"
    "ICAgICkKCiAgICBkZWYgX21ha2VfY2FyZChzZWxmLCByZWM6IGRpY3QpIC0+IFFXaWRnZXQ6CiAgICAgICAgY2FyZCA9IFFGcmFt"
    "ZSgpCiAgICAgICAgaXNfc2VsZWN0ZWQgPSByZWMuZ2V0KCJyZWNvcmRfaWQiKSA9PSBzZWxmLl9zZWxlY3RlZF9pZAogICAgICAg"
    "IGNhcmQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7JyMxYTBhMTAnIGlmIGlzX3NlbGVjdGVkIGVs"
    "c2UgQ19CRzN9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTiBpZiBpc19zZWxlY3RlZCBlbHNl"
    "IENfQk9SREVSfTsgIgogICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsgcGFkZGluZzogMnB4OyIKICAgICAgICApCiAg"
    "ICAgICAgbGF5b3V0ID0gUUhCb3hMYXlvdXQoY2FyZCkKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDgsIDYsIDgs"
    "IDYpCgogICAgICAgIG5hbWVfbGJsID0gUUxhYmVsKHJlYy5nZXQoIm5hbWUiLCAiVU5LTk9XTiIpKQogICAgICAgIG5hbWVfbGJs"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTERfQlJJR0hUIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19H"
    "T0xEfTsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTogMTFweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGZvbnQtZmFtaWx5OiB7REVD"
    "S19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgY291bnQgPSBsZW4ocmVjLmdldCgiaXRlbXMiLCBbXSkpCiAgICAg"
    "ICAgY291bnRfbGJsID0gUUxhYmVsKGYie2NvdW50fSBpdGVtcyIpCiAgICAgICAgY291bnRfbGJsLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwg"
    "c2VyaWY7IgogICAgICAgICkKCiAgICAgICAgZGF0ZV9sYmwgPSBRTGFiZWwocmVjLmdldCgiY3JlYXRlZF9hdCIsICIiKVs6MTBd"
    "KQogICAgICAgIGRhdGVfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1z"
    "aXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgbGF5b3V0LmFkZFdp"
    "ZGdldChuYW1lX2xibCkKICAgICAgICBsYXlvdXQuYWRkU3RyZXRjaCgpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChjb3VudF9s"
    "YmwpCiAgICAgICAgbGF5b3V0LmFkZFNwYWNpbmcoMTIpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChkYXRlX2xibCkKCiAgICAg"
    "ICAgIyBDbGljayB0byBzZWxlY3QKICAgICAgICByZWNfaWQgPSByZWMuZ2V0KCJyZWNvcmRfaWQiLCAiIikKICAgICAgICBjYXJk"
    "Lm1vdXNlUHJlc3NFdmVudCA9IGxhbWJkYSBlLCByaWQ9cmVjX2lkOiBzZWxmLl9zZWxlY3RfY2FyZChyaWQpCiAgICAgICAgcmV0"
    "dXJuIGNhcmQKCiAgICBkZWYgX3NlbGVjdF9jYXJkKHNlbGYsIHJlY29yZF9pZDogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYu"
    "X3NlbGVjdGVkX2lkID0gcmVjb3JkX2lkCiAgICAgICAgc2VsZi5fYnVpbGRfY2FyZHMoKSAgIyBSZWJ1aWxkIHRvIHNob3cgc2Vs"
    "ZWN0aW9uIGhpZ2hsaWdodAoKICAgIGRlZiBfc2VsZWN0ZWRfcmVjb3JkKHNlbGYpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAg"
    "IHJldHVybiBuZXh0KAogICAgICAgICAgICAociBmb3IgciBpbiBzZWxmLl9yZWNvcmRzCiAgICAgICAgICAgICBpZiByLmdldCgi"
    "cmVjb3JkX2lkIikgPT0gc2VsZi5fc2VsZWN0ZWRfaWQpLAogICAgICAgICAgICBOb25lCiAgICAgICAgKQoKICAgICMg4pSA4pSA"
    "IEFDVElPTlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29y"
    "ZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgIyBFbnN1cmUgcmVjb3JkX2lkIGZpZWxkIGV4aXN0cwogICAgICAg"
    "IGNoYW5nZWQgPSBGYWxzZQogICAgICAgIGZvciByIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGlmIG5vdCByLmdldCgi"
    "cmVjb3JkX2lkIik6CiAgICAgICAgICAgICAgICByWyJyZWNvcmRfaWQiXSA9IHIuZ2V0KCJpZCIpIG9yIHN0cih1dWlkLnV1aWQ0"
    "KCkpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgICAgIHdyaXRlX2pz"
    "b25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5fYnVpbGRfY2FyZHMoKQogICAgICAgIHNlbGYuX3N0"
    "YWNrLnNldEN1cnJlbnRJbmRleCgwKQoKICAgIGRlZiBfcHJldmlld19wYXJzZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJhdyA9"
    "IHNlbGYuX2FkZF9yYXcudG9QbGFpblRleHQoKQogICAgICAgIG5hbWUsIGl0ZW1zID0gc2VsZi5wYXJzZV9zY2FuX3RleHQocmF3"
    "KQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dChuYW1lKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3"
    "LnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGl0IGluIGl0ZW1zWzoyMF06ICAjIHByZXZpZXcgZmlyc3QgMjAKICAgICAgICAg"
    "ICAgciA9IHNlbGYuX2FkZF9wcmV2aWV3LnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaW5zZXJ0Um93"
    "KHIpCiAgICAgICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldEl0ZW0ociwgMCwgUVRhYmxlV2lkZ2V0SXRlbShpdFsiaXRlbSJd"
    "KSkKICAgICAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0SXRlbShyLCAxLCBRVGFibGVXaWRnZXRJdGVtKGl0WyJjcmVhdG9y"
    "Il0pKQoKICAgIGRlZiBfc2hvd19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hZGRfbmFtZS5jbGVhcigpCiAgICAg"
    "ICAgc2VsZi5fYWRkX25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJBdXRvLWRldGVjdGVkIGZyb20gc2NhbiB0ZXh0IikKICAgICAg"
    "ICBzZWxmLl9hZGRfZGVzYy5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX3Jhdy5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX3By"
    "ZXZpZXcuc2V0Um93Q291bnQoMCkKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMSkKCiAgICBkZWYgX2RvX2Fk"
    "ZChzZWxmKSAtPiBOb25lOgogICAgICAgIHJhdyAgPSBzZWxmLl9hZGRfcmF3LnRvUGxhaW5UZXh0KCkKICAgICAgICBuYW1lLCBp"
    "dGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICBvdmVycmlkZV9uYW1lID0gc2VsZi5fYWRkX25hbWUudGV4"
    "dCgpLnN0cmlwKCkKICAgICAgICBub3cgID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICBy"
    "ZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAicmVjb3Jk"
    "X2lkIjogICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgIm5hbWUiOiAgICAgICAgb3ZlcnJpZGVfbmFtZSBvciBuYW1l"
    "LAogICAgICAgICAgICAiZGVzY3JpcHRpb24iOiBzZWxmLl9hZGRfZGVzYy50b1BsYWluVGV4dCgpWzoyNDRdLAogICAgICAgICAg"
    "ICAiaXRlbXMiOiAgICAgICBpdGVtcywKICAgICAgICAgICAgInJhd190ZXh0IjogICAgcmF3LAogICAgICAgICAgICAiY3JlYXRl"
    "ZF9hdCI6ICBub3csCiAgICAgICAgICAgICJ1cGRhdGVkX2F0IjogIG5vdywKICAgICAgICB9CiAgICAgICAgc2VsZi5fcmVjb3Jk"
    "cy5hcHBlbmQocmVjb3JkKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2Vs"
    "Zi5fc2VsZWN0ZWRfaWQgPSByZWNvcmRbInJlY29yZF9pZCJdCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3Nob3df"
    "ZGlzcGxheShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90"
    "IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gZGlzcGxheS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAg"
    "ICBzZWxmLl9kaXNwX25hbWUuc2V0VGV4dChmIuKdpyB7cmVjLmdldCgnbmFtZScsJycpfSIpCiAgICAgICAgc2VsZi5fZGlzcF9k"
    "ZXNjLnNldFRleHQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldFJvd0NvdW50"
    "KDApCiAgICAgICAgZm9yIGl0IGluIHJlYy5nZXQoIml0ZW1zIixbXSk6CiAgICAgICAgICAgIHIgPSBzZWxmLl9kaXNwX3RhYmxl"
    "LnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fZGlz"
    "cF90YWJsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiaXRlbSIsIiIpKSkK"
    "ICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVt"
    "KGl0LmdldCgiY3JlYXRvciIsIlVOS05PV04iKSkpCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDIpCgogICAg"
    "ZGVmIF9pdGVtX2NvbnRleHRfbWVudShzZWxmLCBwb3MpIC0+IE5vbmU6CiAgICAgICAgaWR4ID0gc2VsZi5fZGlzcF90YWJsZS5p"
    "bmRleEF0KHBvcykKICAgICAgICBpZiBub3QgaWR4LmlzVmFsaWQoKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaXRlbV90"
    "ZXh0ICA9IChzZWxmLl9kaXNwX3RhYmxlLml0ZW0oaWR4LnJvdygpLCAwKSBvcgogICAgICAgICAgICAgICAgICAgICAgUVRhYmxl"
    "V2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAgIGNyZWF0b3IgICAgPSAoc2VsZi5fZGlzcF90YWJsZS5pdGVtKGlkeC5yb3co"
    "KSwgMSkgb3IKICAgICAgICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICBmcm9tIFB5"
    "U2lkZTYuUXRXaWRnZXRzIGltcG9ydCBRTWVudQogICAgICAgIG1lbnUgPSBRTWVudShzZWxmKQogICAgICAgIG1lbnUuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAg"
    "ZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IgogICAgICAgICkKICAgICAgICBhX2l0ZW0gICAgPSBtZW51LmFk"
    "ZEFjdGlvbigiQ29weSBJdGVtIE5hbWUiKQogICAgICAgIGFfY3JlYXRvciA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5IENyZWF0b3Ii"
    "KQogICAgICAgIGFfYm90aCAgICA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5IEJvdGgiKQogICAgICAgIGFjdGlvbiA9IG1lbnUuZXhl"
    "YyhzZWxmLl9kaXNwX3RhYmxlLnZpZXdwb3J0KCkubWFwVG9HbG9iYWwocG9zKSkKICAgICAgICBjYiA9IFFBcHBsaWNhdGlvbi5j"
    "bGlwYm9hcmQoKQogICAgICAgIGlmIGFjdGlvbiA9PSBhX2l0ZW06ICAgIGNiLnNldFRleHQoaXRlbV90ZXh0KQogICAgICAgIGVs"
    "aWYgYWN0aW9uID09IGFfY3JlYXRvcjogY2Iuc2V0VGV4dChjcmVhdG9yKQogICAgICAgIGVsaWYgYWN0aW9uID09IGFfYm90aDog"
    "IGNiLnNldFRleHQoZiJ7aXRlbV90ZXh0fSDigJQge2NyZWF0b3J9IikKCiAgICBkZWYgX3Nob3dfbW9kaWZ5KHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAgICBR"
    "TWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiU0wgU2NhbnMiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAiU2VsZWN0IGEgc2NhbiB0byBtb2RpZnkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fbW9kX25hbWUuc2V0"
    "VGV4dChyZWMuZ2V0KCJuYW1lIiwiIikpCiAgICAgICAgc2VsZi5fbW9kX2Rlc2Muc2V0VGV4dChyZWMuZ2V0KCJkZXNjcmlwdGlv"
    "biIsIiIpKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiByZWMuZ2V0KCJp"
    "dGVtcyIsW10pOgogICAgICAgICAgICByID0gc2VsZi5fbW9kX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fbW9k"
    "X3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAg"
    "ICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoIml0ZW0iLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRJdGVt"
    "KHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiY3JlYXRvciIsIlVOS05PV04iKSkpCiAgICAg"
    "ICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDMpCgogICAgZGVmIF9kb19tb2RpZnlfc2F2ZShzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgcmVjWyJuYW1lIl0gICAgICAgID0gc2VsZi5fbW9kX25hbWUudGV4dCgpLnN0cmlwKCkgb3IgIlVOS05PV04iCiAg"
    "ICAgICAgcmVjWyJkZXNjcmlwdGlvbiJdID0gc2VsZi5fbW9kX2Rlc2MudGV4dCgpWzoyNDRdCiAgICAgICAgaXRlbXMgPSBbXQog"
    "ICAgICAgIGZvciBpIGluIHJhbmdlKHNlbGYuX21vZF90YWJsZS5yb3dDb3VudCgpKToKICAgICAgICAgICAgaXQgID0gKHNlbGYu"
    "X21vZF90YWJsZS5pdGVtKGksMCkgb3IgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAgICAgICBjciAgPSAoc2Vs"
    "Zi5fbW9kX3RhYmxlLml0ZW0oaSwxKSBvciBRVGFibGVXaWRnZXRJdGVtKCIiKSkudGV4dCgpCiAgICAgICAgICAgIGl0ZW1zLmFw"
    "cGVuZCh7Iml0ZW0iOiBpdC5zdHJpcCgpIG9yICJVTktOT1dOIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAiY3JlYXRvciI6"
    "IGNyLnN0cmlwKCkgb3IgIlVOS05PV04ifSkKICAgICAgICByZWNbIml0ZW1zIl0gICAgICA9IGl0ZW1zCiAgICAgICAgcmVjWyJ1"
    "cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNl"
    "bGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAg"
    "ICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gZGVsZXRlLiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5hbWUgPSByZWMuZ2V0"
    "KCJuYW1lIiwidGhpcyBzY2FuIikKICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICBzZWxm"
    "LCAiRGVsZXRlIFNjYW4iLAogICAgICAgICAgICBmIkRlbGV0ZSAne25hbWV9Jz8gVGhpcyBjYW5ub3QgYmUgdW5kb25lLiIsCiAg"
    "ICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAg"
    "ICAgICAgKQogICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAgc2Vs"
    "Zi5fcmVjb3JkcyA9IFtyIGZvciByIGluIHNlbGYuX3JlY29yZHMKICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiByLmdl"
    "dCgicmVjb3JkX2lkIikgIT0gc2VsZi5fc2VsZWN0ZWRfaWRdCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNl"
    "bGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkID0gTm9uZQogICAgICAgICAgICBzZWxmLnJlZnJlc2go"
    "KQoKICAgIGRlZiBfZG9fcmVwYXJzZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgp"
    "CiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gcmUtcGFyc2UuIikKICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgcmF3ID0gcmVjLmdldCgicmF3X3RleHQiLCIiKQogICAgICAgIGlmIG5vdCByYXc6CiAgICAgICAg"
    "ICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJSZS1wYXJzZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICJObyByYXcgdGV4dCBzdG9yZWQgZm9yIHRoaXMgc2Nhbi4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBuYW1l"
    "LCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICByZWNbIml0ZW1zIl0gICAgICA9IGl0ZW1zCiAgICAg"
    "ICAgcmVjWyJuYW1lIl0gICAgICAgPSByZWNbIm5hbWUiXSBvciBuYW1lCiAgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRl"
    "dGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3Jl"
    "Y29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiUmUtcGFy"
    "c2VkIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIkZvdW5kIHtsZW4oaXRlbXMpfSBpdGVtcy4iKQoKCiMg4pSA"
    "4pSAIFNMIENPTU1BTkRTIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU0xDb21tYW5kc1RhYihRV2lkZ2V0"
    "KToKICAgICIiIgogICAgU2Vjb25kIExpZmUgY29tbWFuZCByZWZlcmVuY2UgdGFibGUuCiAgICBHb3RoaWMgdGFibGUgc3R5bGlu"
    "Zy4gQ29weSBjb21tYW5kIHRvIGNsaXBib2FyZCBidXR0b24gcGVyIHJvdy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxm"
    "LCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAgICA9IGNm"
    "Z19wYXRoKCJzbCIpIC8gInNsX2NvbW1hbmRzLmpzb25sIgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQog"
    "ICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0"
    "LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIikKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5ID0gX2dvdGhpY19i"
    "dG4oIuKcpyBNb2RpZnkiKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgPSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIpCiAgICAg"
    "ICAgc2VsZi5fYnRuX2NvcHkgICA9IF9nb3RoaWNfYnRuKCLip4kgQ29weSBDb21tYW5kIiwKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICJDb3B5IHNlbGVjdGVkIGNvbW1hbmQgdG8gY2xpcGJvYXJkIikKICAgICAgICBzZWxmLl9idG5f"
    "cmVmcmVzaD0gX2dvdGhpY19idG4oIuKGuyBSZWZyZXNoIikKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChz"
    "ZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5KQogICAg"
    "ICAgIHNlbGYuX2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fY29w"
    "eS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fY29weV9jb21tYW5kKQogICAgICAgIHNlbGYuX2J0bl9yZWZyZXNoLmNsaWNrZWQuY29u"
    "bmVjdChzZWxmLnJlZnJlc2gpCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9tb2RpZnksIHNlbGYu"
    "X2J0bl9kZWxldGUsCiAgICAgICAgICAgICAgICAgIHNlbGYuX2J0bl9jb3B5LCBzZWxmLl9idG5fcmVmcmVzaCk6CiAgICAgICAg"
    "ICAgIGJhci5hZGRXaWRnZXQoYikKICAgICAgICBiYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYmFyKQoK"
    "ICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxI"
    "ZWFkZXJMYWJlbHMoWyJDb21tYW5kIiwgIkRlc2NyaXB0aW9uIl0pCiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRl"
    "cigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAg"
    "ICAgICAgc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBR"
    "SGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAg"
    "ICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFi"
    "bGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNf"
    "dGFibGVfc3R5bGUoKSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90YWJsZSwgMSkKCiAgICAgICAgaGludCA9IFFMYWJl"
    "bCgKICAgICAgICAgICAgIlNlbGVjdCBhIHJvdyBhbmQgY2xpY2sg4qeJIENvcHkgQ29tbWFuZCB0byBjb3B5IGp1c3QgdGhlIGNv"
    "bW1hbmQgdGV4dC4iCiAgICAgICAgKQogICAgICAgIGhpbnQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0Nf"
    "VEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAg"
    "ICAgIHJvb3QuYWRkV2lkZ2V0KGhpbnQpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNv"
    "cmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9y"
    "IHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICByID0gc2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBz"
    "ZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAg"
    "ICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJjb21tYW5kIiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVt"
    "KHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpKQoKICAgIGRl"
    "ZiBfY29weV9jb21tYW5kKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAg"
    "ICAgaWYgcm93IDwgMDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaXRlbSA9IHNlbGYuX3RhYmxlLml0ZW0ocm93LCAwKQog"
    "ICAgICAgIGlmIGl0ZW06CiAgICAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KGl0ZW0udGV4dCgpKQoK"
    "ICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRX"
    "aW5kb3dUaXRsZSgiQWRkIENvbW1hbmQiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsg"
    "Y29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKICAgICAgICBjbWQgID0gUUxpbmVFZGl0"
    "KCk7IGRlc2MgPSBRTGluZUVkaXQoKQogICAgICAgIGZvcm0uYWRkUm93KCJDb21tYW5kOiIsIGNtZCkKICAgICAgICBmb3JtLmFk"
    "ZFJvdygiRGVzY3JpcHRpb246IiwgZGVzYykKICAgICAgICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhp"
    "Y19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFj"
    "Y2VwdCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRX"
    "aWRnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRucykKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9n"
    "Q29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgbm93ID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAg"
    "ICAgICAgICAgcmVjID0gewogICAgICAgICAgICAgICAgImlkIjogICAgICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAg"
    "ICAgICAgICAiY29tbWFuZCI6ICAgICBjbWQudGV4dCgpLnN0cmlwKClbOjI0NF0sCiAgICAgICAgICAgICAgICAiZGVzY3JpcHRp"
    "b24iOiBkZXNjLnRleHQoKS5zdHJpcCgpWzoyNDRdLAogICAgICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgbm93LCAidXBkYXRl"
    "ZF9hdCI6IG5vdywKICAgICAgICAgICAgfQogICAgICAgICAgICBpZiByZWNbImNvbW1hbmQiXToKICAgICAgICAgICAgICAgIHNl"
    "bGYuX3JlY29yZHMuYXBwZW5kKHJlYykKICAgICAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29y"
    "ZHMpCiAgICAgICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fbW9kaWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgcm93IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuX3Jl"
    "Y29yZHMpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICBkbGcgPSBR"
    "RGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJNb2RpZnkgQ29tbWFuZCIpCiAgICAgICAgZGxnLnNldFN0"
    "eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBmb3JtID0gUUZvcm1MYXlv"
    "dXQoZGxnKQogICAgICAgIGNtZCAgPSBRTGluZUVkaXQocmVjLmdldCgiY29tbWFuZCIsIiIpKQogICAgICAgIGRlc2MgPSBRTGlu"
    "ZUVkaXQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBmb3JtLmFkZFJvdygiQ29tbWFuZDoiLCBjbWQpCiAgICAg"
    "ICAgZm9ybS5hZGRSb3coIkRlc2NyaXB0aW9uOiIsIGRlc2MpCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBv"
    "ayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25u"
    "ZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7"
    "IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlh"
    "bG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHJlY1siY29tbWFuZCJdICAgICA9IGNtZC50ZXh0KCkuc3RyaXAo"
    "KVs6MjQ0XQogICAgICAgICAgICByZWNbImRlc2NyaXB0aW9uIl0gPSBkZXNjLnRleHQoKS5zdHJpcCgpWzoyNDRdCiAgICAgICAg"
    "ICAgIHJlY1sidXBkYXRlZF9hdCJdICA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAg"
    "IHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVm"
    "IF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBp"
    "ZiByb3cgPCAwIG9yIHJvdyA+PSBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGNtZCA9IHNl"
    "bGYuX3JlY29yZHNbcm93XS5nZXQoImNvbW1hbmQiLCJ0aGlzIGNvbW1hbmQiKQogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gu"
    "cXVlc3Rpb24oCiAgICAgICAgICAgIHNlbGYsICJEZWxldGUiLCBmIkRlbGV0ZSAne2NtZH0nPyIsCiAgICAgICAgICAgIFFNZXNz"
    "YWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgKQogICAgICAg"
    "IGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5wb3Ao"
    "cm93KQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJl"
    "ZnJlc2goKQoKCiMg4pSA4pSAIEpPQiBUUkFDS0VSIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSm9iVHJh"
    "Y2tlclRhYihRV2lkZ2V0KToKICAgICIiIgogICAgSm9iIGFwcGxpY2F0aW9uIHRyYWNraW5nLiBGdWxsIHJlYnVpbGQgZnJvbSBz"
    "cGVjLgogICAgRmllbGRzOiBDb21wYW55LCBKb2IgVGl0bGUsIERhdGUgQXBwbGllZCwgTGluaywgU3RhdHVzLCBOb3Rlcy4KICAg"
    "IE11bHRpLXNlbGVjdCBoaWRlL3VuaGlkZS9kZWxldGUuIENTViBhbmQgVFNWIGV4cG9ydC4KICAgIEhpZGRlbiByb3dzID0gY29t"
    "cGxldGVkL3JlamVjdGVkIOKAlCBzdGlsbCBzdG9yZWQsIGp1c3Qgbm90IHNob3duLgogICAgIiIiCgogICAgQ09MVU1OUyA9IFsi"
    "Q29tcGFueSIsICJKb2IgVGl0bGUiLCAiRGF0ZSBBcHBsaWVkIiwKICAgICAgICAgICAgICAgIkxpbmsiLCAiU3RhdHVzIiwgIk5v"
    "dGVzIl0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50"
    "KQogICAgICAgIHNlbGYuX3BhdGggICAgPSBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJqb2JfdHJhY2tlci5qc29ubCIKICAgICAg"
    "ICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zaG93X2hpZGRlbiA9IEZhbHNlCiAgICAgICAg"
    "c2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQp"
    "CiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGJhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5f"
    "YWRkICAgID0gX2dvdGhpY19idG4oIkFkZCIpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeSA9IF9nb3RoaWNfYnRuKCJNb2RpZnki"
    "KQogICAgICAgIHNlbGYuX2J0bl9oaWRlICAgPSBfZ290aGljX2J0bigiQXJjaGl2ZSIsCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAiTWFyayBzZWxlY3RlZCBhcyBjb21wbGV0ZWQvcmVqZWN0ZWQiKQogICAgICAgIHNlbGYuX2J0bl91"
    "bmhpZGUgPSBfZ290aGljX2J0bigiUmVzdG9yZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiUmVz"
    "dG9yZSBhcmNoaXZlZCBhcHBsaWNhdGlvbnMiKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgPSBfZ290aGljX2J0bigiRGVsZXRl"
    "IikKICAgICAgICBzZWxmLl9idG5fdG9nZ2xlID0gX2dvdGhpY19idG4oIlNob3cgQXJjaGl2ZWQiKQogICAgICAgIHNlbGYuX2J0"
    "bl9leHBvcnQgPSBfZ290aGljX2J0bigiRXhwb3J0IikKCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0"
    "bl9tb2RpZnksIHNlbGYuX2J0bl9oaWRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fdW5oaWRlLCBzZWxmLl9idG5fZGVs"
    "ZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fdG9nZ2xlLCBzZWxmLl9idG5fZXhwb3J0KToKICAgICAgICAgICAgYi5z"
    "ZXRNaW5pbXVtV2lkdGgoNzApCiAgICAgICAgICAgIGIuc2V0TWluaW11bUhlaWdodCgyNikKICAgICAgICAgICAgYmFyLmFkZFdp"
    "ZGdldChiKQoKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5f"
    "YnRuX21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9oaWRlLmNsaWNrZWQu"
    "Y29ubmVjdChzZWxmLl9kb19oaWRlKQogICAgICAgIHNlbGYuX2J0bl91bmhpZGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX3Vu"
    "aGlkZSkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX3RvZ2dsZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2hpZGRlbikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19leHBvcnQpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRk"
    "TGF5b3V0KGJhcikKCiAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgbGVuKHNlbGYuQ09MVU1OUykpCiAgICAg"
    "ICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhzZWxmLkNPTFVNTlMpCiAgICAgICAgaGggPSBzZWxmLl90"
    "YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkKICAgICAgICAjIENvbXBhbnkgYW5kIEpvYiBUaXRsZSBzdHJldGNoCiAgICAgICAgaGgu"
    "c2V0U2VjdGlvblJlc2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIGhoLnNldFNlY3Rp"
    "b25SZXNpemVNb2RlKDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICAjIERhdGUgQXBwbGllZCDigJQg"
    "Zml4ZWQgcmVhZGFibGUgd2lkdGgKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmlldy5SZXNpemVN"
    "b2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENvbHVtbldpZHRoKDIsIDEwMCkKICAgICAgICAjIExpbmsgc3RyZXRj"
    "aGVzCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMywgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAg"
    "ICAgICMgU3RhdHVzIOKAlCBmaXhlZCB3aWR0aAogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDQsIFFIZWFkZXJWaWV3"
    "LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Q29sdW1uV2lkdGgoNCwgODApCiAgICAgICAgIyBOb3Rl"
    "cyBzdHJldGNoZXMKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSg1LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0"
    "Y2gpCgogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmll"
    "dy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbk1vZGUoCiAgICAg"
    "ICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbk1vZGUuRXh0ZW5kZWRTZWxlY3Rpb24pCiAgICAgICAgc2VsZi5fdGFi"
    "bGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNf"
    "dGFibGVfc3R5bGUoKSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90YWJsZSwgMSkKCiAgICBkZWYgcmVmcmVzaChzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgc2VsZi5fdGFi"
    "bGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGhpZGRlbiA9IGJv"
    "b2wocmVjLmdldCgiaGlkZGVuIiwgRmFsc2UpKQogICAgICAgICAgICBpZiBoaWRkZW4gYW5kIG5vdCBzZWxmLl9zaG93X2hpZGRl"
    "bjoKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAg"
    "ICAgIHNlbGYuX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzdGF0dXMgPSAiQXJjaGl2ZWQiIGlmIGhpZGRlbiBlbHNl"
    "IHJlYy5nZXQoInN0YXR1cyIsIkFjdGl2ZSIpCiAgICAgICAgICAgIHZhbHMgPSBbCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJj"
    "b21wYW55IiwiIiksCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJqb2JfdGl0bGUiLCIiKSwKICAgICAgICAgICAgICAgIHJlYy5n"
    "ZXQoImRhdGVfYXBwbGllZCIsIiIpLAogICAgICAgICAgICAgICAgcmVjLmdldCgibGluayIsIiIpLAogICAgICAgICAgICAgICAg"
    "c3RhdHVzLAogICAgICAgICAgICAgICAgcmVjLmdldCgibm90ZXMiLCIiKSwKICAgICAgICAgICAgXQogICAgICAgICAgICBmb3Ig"
    "YywgdiBpbiBlbnVtZXJhdGUodmFscyk6CiAgICAgICAgICAgICAgICBpdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShzdHIodikpCiAg"
    "ICAgICAgICAgICAgICBpZiBoaWRkZW46CiAgICAgICAgICAgICAgICAgICAgaXRlbS5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX1RF"
    "WFRfRElNKSkKICAgICAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgYywgaXRlbSkKICAgICAgICAgICAgIyBTdG9y"
    "ZSByZWNvcmQgaW5kZXggaW4gZmlyc3QgY29sdW1uJ3MgdXNlciBkYXRhCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLml0ZW0ociwg"
    "MCkuc2V0RGF0YSgKICAgICAgICAgICAgICAgIFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwKICAgICAgICAgICAgICAgIHNlbGYu"
    "X3JlY29yZHMuaW5kZXgocmVjKQogICAgICAgICAgICApCgogICAgZGVmIF9zZWxlY3RlZF9pbmRpY2VzKHNlbGYpIC0+IGxpc3Rb"
    "aW50XToKICAgICAgICBpbmRpY2VzID0gc2V0KCkKICAgICAgICBmb3IgaXRlbSBpbiBzZWxmLl90YWJsZS5zZWxlY3RlZEl0ZW1z"
    "KCk6CiAgICAgICAgICAgIHJvd19pdGVtID0gc2VsZi5fdGFibGUuaXRlbShpdGVtLnJvdygpLCAwKQogICAgICAgICAgICBpZiBy"
    "b3dfaXRlbToKICAgICAgICAgICAgICAgIGlkeCA9IHJvd19pdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAg"
    "ICAgICAgICAgICAgaWYgaWR4IGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgIGluZGljZXMuYWRkKGlkeCkKICAgICAg"
    "ICByZXR1cm4gc29ydGVkKGluZGljZXMpCgogICAgZGVmIF9kaWFsb2coc2VsZiwgcmVjOiBkaWN0ID0gTm9uZSkgLT4gT3B0aW9u"
    "YWxbZGljdF06CiAgICAgICAgZGxnICA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkpvYiBBcHBs"
    "aWNhdGlvbiIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07"
    "IikKICAgICAgICBkbGcucmVzaXplKDUwMCwgMzIwKQogICAgICAgIGZvcm0gPSBRRm9ybUxheW91dChkbGcpCgogICAgICAgIGNv"
    "bXBhbnkgPSBRTGluZUVkaXQocmVjLmdldCgiY29tcGFueSIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIHRpdGxlICAgPSBR"
    "TGluZUVkaXQocmVjLmdldCgiam9iX3RpdGxlIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgZGUgICAgICA9IFFEYXRlRWRp"
    "dCgpCiAgICAgICAgZGUuc2V0Q2FsZW5kYXJQb3B1cChUcnVlKQogICAgICAgIGRlLnNldERpc3BsYXlGb3JtYXQoInl5eXktTU0t"
    "ZGQiKQogICAgICAgIGlmIHJlYyBhbmQgcmVjLmdldCgiZGF0ZV9hcHBsaWVkIik6CiAgICAgICAgICAgIGRlLnNldERhdGUoUURh"
    "dGUuZnJvbVN0cmluZyhyZWNbImRhdGVfYXBwbGllZCJdLCJ5eXl5LU1NLWRkIikpCiAgICAgICAgZWxzZToKICAgICAgICAgICAg"
    "ZGUuc2V0RGF0ZShRRGF0ZS5jdXJyZW50RGF0ZSgpKQogICAgICAgIGxpbmsgICAgPSBRTGluZUVkaXQocmVjLmdldCgibGluayIs"
    "IiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIHN0YXR1cyAgPSBRTGluZUVkaXQocmVjLmdldCgic3RhdHVzIiwiQXBwbGllZCIp"
    "IGlmIHJlYyBlbHNlICJBcHBsaWVkIikKICAgICAgICBub3RlcyAgID0gUUxpbmVFZGl0KHJlYy5nZXQoIm5vdGVzIiwiIikgaWYg"
    "cmVjIGVsc2UgIiIpCgogICAgICAgIGZvciBsYWJlbCwgd2lkZ2V0IGluIFsKICAgICAgICAgICAgKCJDb21wYW55OiIsIGNvbXBh"
    "bnkpLCAoIkpvYiBUaXRsZToiLCB0aXRsZSksCiAgICAgICAgICAgICgiRGF0ZSBBcHBsaWVkOiIsIGRlKSwgKCJMaW5rOiIsIGxp"
    "bmspLAogICAgICAgICAgICAoIlN0YXR1czoiLCBzdGF0dXMpLCAoIk5vdGVzOiIsIG5vdGVzKSwKICAgICAgICBdOgogICAgICAg"
    "ICAgICBmb3JtLmFkZFJvdyhsYWJlbCwgd2lkZ2V0KQoKICAgICAgICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0g"
    "X2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3Qo"
    "ZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRu"
    "cy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRucykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9n"
    "LkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICAgICAiY29tcGFueSI6ICAgICAg"
    "Y29tcGFueS50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJqb2JfdGl0bGUiOiAgICB0aXRsZS50ZXh0KCkuc3RyaXAo"
    "KSwKICAgICAgICAgICAgICAgICJkYXRlX2FwcGxpZWQiOiBkZS5kYXRlKCkudG9TdHJpbmcoInl5eXktTU0tZGQiKSwKICAgICAg"
    "ICAgICAgICAgICJsaW5rIjogICAgICAgICBsaW5rLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgInN0YXR1cyI6ICAg"
    "ICAgIHN0YXR1cy50ZXh0KCkuc3RyaXAoKSBvciAiQXBwbGllZCIsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICAgbm90"
    "ZXMudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgIH0KICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBfZG9fYWRkKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgcCA9IHNlbGYuX2RpYWxvZygpCiAgICAgICAgaWYgbm90IHA6CiAgICAgICAgICAgIHJldHVybgog"
    "ICAgICAgIG5vdyA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgcC51cGRhdGUoewogICAg"
    "ICAgICAgICAiaWQiOiAgICAgICAgICAgICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgImhpZGRlbiI6ICAgICAgICAg"
    "RmFsc2UsCiAgICAgICAgICAgICJjb21wbGV0ZWRfZGF0ZSI6IE5vbmUsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgIG5v"
    "dywKICAgICAgICAgICAgInVwZGF0ZWRfYXQiOiAgICAgbm93LAogICAgICAgIH0pCiAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBl"
    "bmQocCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgp"
    "CgogICAgZGVmIF9kb19tb2RpZnkoc2VsZikgLT4gTm9uZToKICAgICAgICBpZHhzID0gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygp"
    "CiAgICAgICAgaWYgbGVuKGlkeHMpICE9IDE6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJNb2Rp"
    "ZnkiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiU2VsZWN0IGV4YWN0bHkgb25lIHJvdyB0byBtb2RpZnku"
    "IikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tpZHhzWzBdXQogICAgICAgIHAgICA9IHNl"
    "bGYuX2RpYWxvZyhyZWMpCiAgICAgICAgaWYgbm90IHA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlYy51cGRhdGUocCkK"
    "ICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAg"
    "d3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9f"
    "aGlkZShzZWxmKSAtPiBOb25lOgogICAgICAgIGZvciBpZHggaW4gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpOgogICAgICAgICAg"
    "ICBpZiBpZHggPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bImhpZGRlbiJd"
    "ICAgICAgICAgPSBUcnVlCiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bImNvbXBsZXRlZF9kYXRlIl0gPSAoCiAg"
    "ICAgICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdLmdldCgiY29tcGxldGVkX2RhdGUiKSBvcgogICAgICAgICAgICAg"
    "ICAgICAgIGRhdGV0aW1lLm5vdygpLmRhdGUoKS5pc29mb3JtYXQoKQogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAg"
    "c2VsZi5fcmVjb3Jkc1tpZHhdWyJ1cGRhdGVkX2F0Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KHRpbWV6"
    "b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxm"
    "Ll9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb191bmhpZGUoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBmb3IgaWR4IGluIHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKToKICAgICAgICAgICAgaWYgaWR4IDwgbGVuKHNlbGYuX3JlY29y"
    "ZHMpOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJoaWRkZW4iXSAgICAgPSBGYWxzZQogICAgICAgICAgICAg"
    "ICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJ1cGRhdGVkX2F0Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KHRp"
    "bWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBz"
    "ZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBpZHhzID0gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpCiAgICAgICAgaWYgbm90IGlkeHM6CiAgICAgICAgICAgIHJldHVy"
    "bgogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgIHNlbGYsICJEZWxldGUiLAogICAgICAg"
    "ICAgICBmIkRlbGV0ZSB7bGVuKGlkeHMpfSBzZWxlY3RlZCBhcHBsaWNhdGlvbihzKT8gQ2Fubm90IGJlIHVuZG9uZS4iLAogICAg"
    "ICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAg"
    "ICAgICkKICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIGJhZCA9"
    "IHNldChpZHhzKQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzID0gW3IgZm9yIGksIHIgaW4gZW51bWVyYXRlKHNlbGYuX3JlY29y"
    "ZHMpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgaSBub3QgaW4gYmFkXQogICAgICAgICAgICB3cml0ZV9qc29ubChz"
    "ZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfdG9nZ2xlX2hpZGRl"
    "bihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nob3dfaGlkZGVuID0gbm90IHNlbGYuX3Nob3dfaGlkZGVuCiAgICAgICAg"
    "c2VsZi5fYnRuX3RvZ2dsZS5zZXRUZXh0KAogICAgICAgICAgICAi4piAIEhpZGUgQXJjaGl2ZWQiIGlmIHNlbGYuX3Nob3dfaGlk"
    "ZGVuIGVsc2UgIuKYvSBTaG93IEFyY2hpdmVkIgogICAgICAgICkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9f"
    "ZXhwb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCwgZmlsdCA9IFFGaWxlRGlhbG9nLmdldFNhdmVGaWxlTmFtZSgKICAg"
    "ICAgICAgICAgc2VsZiwgIkV4cG9ydCBKb2IgVHJhY2tlciIsCiAgICAgICAgICAgIHN0cihjZmdfcGF0aCgiZXhwb3J0cyIpIC8g"
    "ImpvYl90cmFja2VyLmNzdiIpLAogICAgICAgICAgICAiQ1NWIEZpbGVzICgqLmNzdik7O1RhYiBEZWxpbWl0ZWQgKCoudHh0KSIK"
    "ICAgICAgICApCiAgICAgICAgaWYgbm90IHBhdGg6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGRlbGltID0gIlx0IiBpZiBw"
    "YXRoLmxvd2VyKCkuZW5kc3dpdGgoIi50eHQiKSBlbHNlICIsIgogICAgICAgIGhlYWRlciA9IFsiY29tcGFueSIsImpvYl90aXRs"
    "ZSIsImRhdGVfYXBwbGllZCIsImxpbmsiLAogICAgICAgICAgICAgICAgICAic3RhdHVzIiwiaGlkZGVuIiwiY29tcGxldGVkX2Rh"
    "dGUiLCJub3RlcyJdCiAgICAgICAgd2l0aCBvcGVuKHBhdGgsICJ3IiwgZW5jb2Rpbmc9InV0Zi04IiwgbmV3bGluZT0iIikgYXMg"
    "ZjoKICAgICAgICAgICAgZi53cml0ZShkZWxpbS5qb2luKGhlYWRlcikgKyAiXG4iKQogICAgICAgICAgICBmb3IgcmVjIGluIHNl"
    "bGYuX3JlY29yZHM6CiAgICAgICAgICAgICAgICB2YWxzID0gWwogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImNvbXBhbnki"
    "LCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJqb2JfdGl0bGUiLCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMu"
    "Z2V0KCJkYXRlX2FwcGxpZWQiLCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJsaW5rIiwiIiksCiAgICAgICAgICAg"
    "ICAgICAgICAgcmVjLmdldCgic3RhdHVzIiwiIiksCiAgICAgICAgICAgICAgICAgICAgc3RyKGJvb2wocmVjLmdldCgiaGlkZGVu"
    "IixGYWxzZSkpKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJjb21wbGV0ZWRfZGF0ZSIsIiIpIG9yICIiLAogICAgICAg"
    "ICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAgICAgICAgICAgICAgICBdCiAgICAgICAgICAgICAgICBmLndyaXRl"
    "KGRlbGltLmpvaW4oCiAgICAgICAgICAgICAgICAgICAgc3RyKHYpLnJlcGxhY2UoIlxuIiwiICIpLnJlcGxhY2UoZGVsaW0sIiAi"
    "KQogICAgICAgICAgICAgICAgICAgIGZvciB2IGluIHZhbHMKICAgICAgICAgICAgICAgICkgKyAiXG4iKQogICAgICAgIFFNZXNz"
    "YWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJFeHBvcnRlZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJTYXZl"
    "ZCB0byB7cGF0aH0iKQoKCiMg4pSA4pSAIFNFTEYgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApjbGFzcyBSZWNvcmRzVGFiKFFXaWRnZXQpOgogICAgIiIiR29vZ2xlIERyaXZlL0RvY3MgcmVjb3JkcyBicm93c2Vy"
    "IHRhYi4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFy"
    "ZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDYsIDYs"
    "IDYsIDYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVsKCJSZWNv"
    "cmRzIGFyZSBub3QgbG9hZGVkIHlldC4iKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4"
    "OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5zdGF0dXNfbGFiZWwpCgogICAgICAgIHNlbGYucGF0aF9s"
    "YWJlbCA9IFFMYWJlbCgiUGF0aDogTXkgRHJpdmUiKQogICAgICAgIHNlbGYucGF0aF9sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0RJTX07IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTog"
    "MTBweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYucGF0aF9sYWJlbCkKCiAgICAgICAgc2VsZi5yZWNv"
    "cmRzX2xpc3QgPSBRTGlzdFdpZGdldCgpCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07Igog"
    "ICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLnJlY29yZHNfbGlzdCwgMSkKCiAgICBkZWYgc2V0X2l0ZW1zKHNl"
    "bGYsIGZpbGVzOiBsaXN0W2RpY3RdLCBwYXRoX3RleHQ6IHN0ciA9ICJNeSBEcml2ZSIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5w"
    "YXRoX2xhYmVsLnNldFRleHQoZiJQYXRoOiB7cGF0aF90ZXh0fSIpCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3QuY2xlYXIoKQog"
    "ICAgICAgIGZvciBmaWxlX2luZm8gaW4gZmlsZXM6CiAgICAgICAgICAgIHRpdGxlID0gKGZpbGVfaW5mby5nZXQoIm5hbWUiKSBv"
    "ciAiVW50aXRsZWQiKS5zdHJpcCgpIG9yICJVbnRpdGxlZCIKICAgICAgICAgICAgbWltZSA9IChmaWxlX2luZm8uZ2V0KCJtaW1l"
    "VHlwZSIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5m"
    "b2xkZXIiOgogICAgICAgICAgICAgICAgcHJlZml4ID0gIvCfk4EiCiAgICAgICAgICAgIGVsaWYgbWltZSA9PSAiYXBwbGljYXRp"
    "b24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IjoKICAgICAgICAgICAgICAgIHByZWZpeCA9ICLwn5OdIgogICAgICAgICAgICBl"
    "bHNlOgogICAgICAgICAgICAgICAgcHJlZml4ID0gIvCfk4QiCiAgICAgICAgICAgIG1vZGlmaWVkID0gKGZpbGVfaW5mby5nZXQo"
    "Im1vZGlmaWVkVGltZSIpIG9yICIiKS5yZXBsYWNlKCJUIiwgIiAiKS5yZXBsYWNlKCJaIiwgIiBVVEMiKQogICAgICAgICAgICB0"
    "ZXh0ID0gZiJ7cHJlZml4fSB7dGl0bGV9IiArIChmIiAgICBbe21vZGlmaWVkfV0iIGlmIG1vZGlmaWVkIGVsc2UgIiIpCiAgICAg"
    "ICAgICAgIGl0ZW0gPSBRTGlzdFdpZGdldEl0ZW0odGV4dCkKICAgICAgICAgICAgaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9s"
    "ZS5Vc2VyUm9sZSwgZmlsZV9pbmZvKQogICAgICAgICAgICBzZWxmLnJlY29yZHNfbGlzdC5hZGRJdGVtKGl0ZW0pCiAgICAgICAg"
    "c2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkxvYWRlZCB7bGVuKGZpbGVzKX0gR29vZ2xlIERyaXZlIGl0ZW0ocykuIikKCgpj"
    "bGFzcyBUYXNrc1RhYihRV2lkZ2V0KToKICAgICIiIlRhc2sgcmVnaXN0cnkgKyBHb29nbGUtZmlyc3QgZWRpdG9yIHdvcmtmbG93"
    "IHRhYi4iIiIKCiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKICAgICAgICB0YXNrc19wcm92aWRlciwKICAgICAgICBv"
    "bl9hZGRfZWRpdG9yX29wZW4sCiAgICAgICAgb25fY29tcGxldGVfc2VsZWN0ZWQsCiAgICAgICAgb25fY2FuY2VsX3NlbGVjdGVk"
    "LAogICAgICAgIG9uX3RvZ2dsZV9jb21wbGV0ZWQsCiAgICAgICAgb25fcHVyZ2VfY29tcGxldGVkLAogICAgICAgIG9uX2ZpbHRl"
    "cl9jaGFuZ2VkLAogICAgICAgIG9uX2VkaXRvcl9zYXZlLAogICAgICAgIG9uX2VkaXRvcl9jYW5jZWwsCiAgICAgICAgZGlhZ25v"
    "c3RpY3NfbG9nZ2VyPU5vbmUsCiAgICAgICAgcGFyZW50PU5vbmUsCiAgICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFy"
    "ZW50KQogICAgICAgIHNlbGYuX3Rhc2tzX3Byb3ZpZGVyID0gdGFza3NfcHJvdmlkZXIKICAgICAgICBzZWxmLl9vbl9hZGRfZWRp"
    "dG9yX29wZW4gPSBvbl9hZGRfZWRpdG9yX29wZW4KICAgICAgICBzZWxmLl9vbl9jb21wbGV0ZV9zZWxlY3RlZCA9IG9uX2NvbXBs"
    "ZXRlX3NlbGVjdGVkCiAgICAgICAgc2VsZi5fb25fY2FuY2VsX3NlbGVjdGVkID0gb25fY2FuY2VsX3NlbGVjdGVkCiAgICAgICAg"
    "c2VsZi5fb25fdG9nZ2xlX2NvbXBsZXRlZCA9IG9uX3RvZ2dsZV9jb21wbGV0ZWQKICAgICAgICBzZWxmLl9vbl9wdXJnZV9jb21w"
    "bGV0ZWQgPSBvbl9wdXJnZV9jb21wbGV0ZWQKICAgICAgICBzZWxmLl9vbl9maWx0ZXJfY2hhbmdlZCA9IG9uX2ZpbHRlcl9jaGFu"
    "Z2VkCiAgICAgICAgc2VsZi5fb25fZWRpdG9yX3NhdmUgPSBvbl9lZGl0b3Jfc2F2ZQogICAgICAgIHNlbGYuX29uX2VkaXRvcl9j"
    "YW5jZWwgPSBvbl9lZGl0b3JfY2FuY2VsCiAgICAgICAgc2VsZi5fZGlhZ19sb2dnZXIgPSBkaWFnbm9zdGljc19sb2dnZXIKICAg"
    "ICAgICBzZWxmLl9zaG93X2NvbXBsZXRlZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fcmVmcmVzaF90aHJlYWQgPSBOb25lCiAgICAg"
    "ICAgc2VsZi5fYnVpbGRfdWkoKQoKICAgIGRlZiBfYnVpbGRfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hM"
    "YXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3Bh"
    "Y2luZyg0KQogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrID0gUVN0YWNrZWRXaWRnZXQoKQogICAgICAgIHJvb3QuYWRkV2lk"
    "Z2V0KHNlbGYud29ya3NwYWNlX3N0YWNrLCAxKQoKICAgICAgICBub3JtYWwgPSBRV2lkZ2V0KCkKICAgICAgICBub3JtYWxfbGF5"
    "b3V0ID0gUVZCb3hMYXlvdXQobm9ybWFsKQogICAgICAgIG5vcm1hbF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAs"
    "IDApCiAgICAgICAgbm9ybWFsX2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVs"
    "KCJUYXNrIHJlZ2lzdHJ5IGlzIG5vdCBsb2FkZWQgeWV0LiIpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250"
    "LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBub3JtYWxfbGF5b3V0LmFkZFdpZGdldChzZWxmLnN0YXR1c19sYWJlbCkK"
    "CiAgICAgICAgZmlsdGVyX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChfc2VjdGlvbl9s"
    "YmwoIuKdpyBEQVRFIFJBTkdFIikpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAg"
    "c2VsZi50YXNrX2ZpbHRlcl9jb21iby5hZGRJdGVtKCJXRUVLIiwgIndlZWsiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29t"
    "Ym8uYWRkSXRlbSgiTU9OVEgiLCAibW9udGgiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiTkVYVCAz"
    "IE1PTlRIUyIsICJuZXh0XzNfbW9udGhzIikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIllFQVIiLCAi"
    "eWVhciIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5zZXRDdXJyZW50SW5kZXgoMikKICAgICAgICBzZWxmLnRhc2tf"
    "ZmlsdGVyX2NvbWJvLmN1cnJlbnRJbmRleENoYW5nZWQuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIF86IHNlbGYuX29uX2Zp"
    "bHRlcl9jaGFuZ2VkKHNlbGYudGFza19maWx0ZXJfY29tYm8uY3VycmVudERhdGEoKSBvciAibmV4dF8zX21vbnRocyIpCiAgICAg"
    "ICAgKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYudGFza19maWx0ZXJfY29tYm8pCiAgICAgICAgZmlsdGVyX3Jv"
    "dy5hZGRTdHJldGNoKDEpCiAgICAgICAgbm9ybWFsX2xheW91dC5hZGRMYXlvdXQoZmlsdGVyX3JvdykKCiAgICAgICAgc2VsZi50"
    "YXNrX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDQpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJM"
    "YWJlbHMoWyJTdGF0dXMiLCAiRHVlIiwgIlRhc2siLCAiU291cmNlIl0pCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFNlbGVj"
    "dGlvbkJlaGF2aW9yKFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi50"
    "YXNrX3RhYmxlLnNldFNlbGVjdGlvbk1vZGUoUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uTW9kZS5FeHRlbmRlZFNlbGVjdGlv"
    "bikKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0RWRpdFRyaWdnZXJzKFFBYnN0cmFjdEl0ZW1WaWV3LkVkaXRUcmlnZ2VyLk5v"
    "RWRpdFRyaWdnZXJzKQogICAgICAgIHNlbGYudGFza190YWJsZS52ZXJ0aWNhbEhlYWRlcigpLnNldFZpc2libGUoRmFsc2UpCiAg"
    "ICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgwLCBRSGVhZGVyVmll"
    "dy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5z"
    "ZXRTZWN0aW9uUmVzaXplTW9kZSgxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2Vs"
    "Zi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmlldy5SZXNpemVN"
    "b2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9k"
    "ZSgzLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFN0"
    "eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYudGFza190YWJsZS5pdGVtU2VsZWN0aW9uQ2hhbmdl"
    "ZC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0dG9uX3N0YXRlKQogICAgICAgIG5vcm1hbF9sYXlvdXQuYWRkV2lkZ2V0"
    "KHNlbGYudGFza190YWJsZSwgMSkKCiAgICAgICAgYWN0aW9ucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLmJ0bl9hZGRf"
    "dGFza193b3Jrc3BhY2UgPSBfZ290aGljX2J0bigiQUREIFRBU0siKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2sgPSBf"
    "Z290aGljX2J0bigiQ09NUExFVEUgU0VMRUNURUQiKQogICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrID0gX2dvdGhpY19idG4o"
    "IkNBTkNFTCBTRUxFQ1RFRCIpCiAgICAgICAgc2VsZi5idG5fdG9nZ2xlX2NvbXBsZXRlZCA9IF9nb3RoaWNfYnRuKCJTSE9XIENP"
    "TVBMRVRFRCIpCiAgICAgICAgc2VsZi5idG5fcHVyZ2VfY29tcGxldGVkID0gX2dvdGhpY19idG4oIlBVUkdFIENPTVBMRVRFRCIp"
    "CiAgICAgICAgc2VsZi5idG5fYWRkX3Rhc2tfd29ya3NwYWNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9hZGRfZWRpdG9yX29w"
    "ZW4pCiAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzay5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fY29tcGxldGVfc2VsZWN0"
    "ZWQpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2NhbmNlbF9zZWxlY3RlZCkK"
    "ICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl90b2dnbGVfY29tcGxldGVk"
    "KQogICAgICAgIHNlbGYuYnRuX3B1cmdlX2NvbXBsZXRlZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fcHVyZ2VfY29tcGxldGVk"
    "KQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2suc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLmJ0bl9jYW5jZWxf"
    "dGFzay5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIGZvciBidG4gaW4gKAogICAgICAgICAgICBzZWxmLmJ0bl9hZGRfdGFza193"
    "b3Jrc3BhY2UsCiAgICAgICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2ssCiAgICAgICAgICAgIHNlbGYuYnRuX2NhbmNlbF90"
    "YXNrLAogICAgICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLAogICAgICAgICAgICBzZWxmLmJ0bl9wdXJnZV9jb21w"
    "bGV0ZWQsCiAgICAgICAgKToKICAgICAgICAgICAgYWN0aW9ucy5hZGRXaWRnZXQoYnRuKQogICAgICAgIG5vcm1hbF9sYXlvdXQu"
    "YWRkTGF5b3V0KGFjdGlvbnMpCiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suYWRkV2lkZ2V0KG5vcm1hbCkKCiAgICAgICAg"
    "ZWRpdG9yID0gUVdpZGdldCgpCiAgICAgICAgZWRpdG9yX2xheW91dCA9IFFWQm94TGF5b3V0KGVkaXRvcikKICAgICAgICBlZGl0"
    "b3JfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGVkaXRvcl9sYXlvdXQuc2V0U3BhY2luZyg0"
    "KQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFRBU0sgRURJVE9SIOKAlCBHT09HTEUt"
    "RklSU1QiKSkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbCA9IFFMYWJlbCgiQ29uZmlndXJlIHRhc2sgZGV0"
    "YWlscywgdGhlbiBzYXZlIHRvIEdvb2dsZSBDYWxlbmRhci4iKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVs"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgYm9y"
    "ZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgcGFkZGluZzogNnB4OyIKICAgICAgICApCiAgICAgICAgZWRpdG9yX2xheW91dC5h"
    "ZGRXaWRnZXQoc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9uYW1lID0gUUxp"
    "bmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJUYXNrIE5hbWUiKQogICAg"
    "ICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF0ZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFy"
    "dF9kYXRlLnNldFBsYWNlaG9sZGVyVGV4dCgiU3RhcnQgRGF0ZSAoWVlZWS1NTS1ERCkiKQogICAgICAgIHNlbGYudGFza19lZGl0"
    "b3Jfc3RhcnRfdGltZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnNldFBsYWNlaG9s"
    "ZGVyVGV4dCgiU3RhcnQgVGltZSAoSEg6TU0pIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlID0gUUxpbmVFZGl0"
    "KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlLnNldFBsYWNlaG9sZGVyVGV4dCgiRW5kIERhdGUgKFlZWVktTU0t"
    "REQpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRp"
    "dG9yX2VuZF90aW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiRW5kIFRpbWUgKEhIOk1NKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRv"
    "cl9sb2NhdGlvbiA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbi5zZXRQbGFjZWhvbGRlclRl"
    "eHQoIkxvY2F0aW9uIChvcHRpb25hbCkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfcmVjdXJyZW5jZSA9IFFMaW5lRWRpdCgp"
    "CiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnNldFBsYWNlaG9sZGVyVGV4dCgiUmVjdXJyZW5jZSBSUlVMRSAo"
    "b3B0aW9uYWwpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2FsbF9kYXkgPSBRQ2hlY2tCb3goIkFsbC1kYXkiKQogICAgICAg"
    "IHNlbGYudGFza19lZGl0b3Jfbm90ZXMgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfbm90ZXMuc2V0UGxh"
    "Y2Vob2xkZXJUZXh0KCJOb3RlcyIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9ub3Rlcy5zZXRNYXhpbXVtSGVpZ2h0KDkwKQog"
    "ICAgICAgIGZvciB3aWRnZXQgaW4gKAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25hbWUsCiAgICAgICAgICAgIHNlbGYu"
    "dGFza19lZGl0b3Jfc3RhcnRfZGF0ZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLAogICAgICAgICAg"
    "ICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lLAogICAgICAg"
    "ICAgICBzZWxmLnRhc2tfZWRpdG9yX2xvY2F0aW9uLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3JlY3VycmVuY2UsCiAg"
    "ICAgICAgKToKICAgICAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQod2lkZ2V0KQogICAgICAgIGVkaXRvcl9sYXlvdXQu"
    "YWRkV2lkZ2V0KHNlbGYudGFza19lZGl0b3JfYWxsX2RheSkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChzZWxmLnRh"
    "c2tfZWRpdG9yX25vdGVzLCAxKQogICAgICAgIGVkaXRvcl9hY3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9zYXZl"
    "ID0gX2dvdGhpY19idG4oIlNBVkUiKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigiQ0FOQ0VMIikKICAgICAgICBi"
    "dG5fc2F2ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fZWRpdG9yX3NhdmUpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fb25fZWRpdG9yX2NhbmNlbCkKICAgICAgICBlZGl0b3JfYWN0aW9ucy5hZGRXaWRnZXQoYnRuX3NhdmUpCiAg"
    "ICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkU3RyZXRj"
    "aCgxKQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkTGF5b3V0KGVkaXRvcl9hY3Rpb25zKQogICAgICAgIHNlbGYud29ya3NwYWNl"
    "X3N0YWNrLmFkZFdpZGdldChlZGl0b3IpCgogICAgICAgIHNlbGYubm9ybWFsX3dvcmtzcGFjZSA9IG5vcm1hbAogICAgICAgIHNl"
    "bGYuZWRpdG9yX3dvcmtzcGFjZSA9IGVkaXRvcgogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQo"
    "c2VsZi5ub3JtYWxfd29ya3NwYWNlKQoKICAgIGRlZiBfdXBkYXRlX2FjdGlvbl9idXR0b25fc3RhdGUoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBlbmFibGVkID0gYm9vbChzZWxmLnNlbGVjdGVkX3Rhc2tfaWRzKCkpCiAgICAgICAgc2VsZi5idG5fY29tcGxldGVf"
    "dGFzay5zZXRFbmFibGVkKGVuYWJsZWQpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suc2V0RW5hYmxlZChlbmFibGVkKQoK"
    "ICAgIGRlZiBzZWxlY3RlZF90YXNrX2lkcyhzZWxmKSAtPiBsaXN0W3N0cl06CiAgICAgICAgaWRzOiBsaXN0W3N0cl0gPSBbXQog"
    "ICAgICAgIGZvciByIGluIHJhbmdlKHNlbGYudGFza190YWJsZS5yb3dDb3VudCgpKToKICAgICAgICAgICAgc3RhdHVzX2l0ZW0g"
    "PSBzZWxmLnRhc2tfdGFibGUuaXRlbShyLCAwKQogICAgICAgICAgICBpZiBzdGF0dXNfaXRlbSBpcyBOb25lOgogICAgICAgICAg"
    "ICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgbm90IHN0YXR1c19pdGVtLmlzU2VsZWN0ZWQoKToKICAgICAgICAgICAgICAg"
    "IGNvbnRpbnVlCiAgICAgICAgICAgIHRhc2tfaWQgPSBzdGF0dXNfaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkK"
    "ICAgICAgICAgICAgaWYgdGFza19pZCBhbmQgdGFza19pZCBub3QgaW4gaWRzOgogICAgICAgICAgICAgICAgaWRzLmFwcGVuZCh0"
    "YXNrX2lkKQogICAgICAgIHJldHVybiBpZHMKCiAgICBkZWYgbG9hZF90YXNrcyhzZWxmLCB0YXNrczogbGlzdFtkaWN0XSkgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgdGFzayBpbiB0YXNrczoKICAg"
    "ICAgICAgICAgcm93ID0gc2VsZi50YXNrX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLmluc2Vy"
    "dFJvdyhyb3cpCiAgICAgICAgICAgIHN0YXR1cyA9ICh0YXNrLmdldCgic3RhdHVzIikgb3IgInBlbmRpbmciKS5sb3dlcigpCiAg"
    "ICAgICAgICAgIHN0YXR1c19pY29uID0gIuKYkSIgaWYgc3RhdHVzIGluIHsiY29tcGxldGVkIiwgImNhbmNlbGxlZCJ9IGVsc2Ug"
    "IuKAoiIKICAgICAgICAgICAgZHVlID0gKHRhc2suZ2V0KCJkdWVfYXQiKSBvciAiIikucmVwbGFjZSgiVCIsICIgIikKICAgICAg"
    "ICAgICAgdGV4dCA9ICh0YXNrLmdldCgidGV4dCIpIG9yICJSZW1pbmRlciIpLnN0cmlwKCkgb3IgIlJlbWluZGVyIgogICAgICAg"
    "ICAgICBzb3VyY2UgPSAodGFzay5nZXQoInNvdXJjZSIpIG9yICJsb2NhbCIpLmxvd2VyKCkKICAgICAgICAgICAgc3RhdHVzX2l0"
    "ZW0gPSBRVGFibGVXaWRnZXRJdGVtKGYie3N0YXR1c19pY29ufSB7c3RhdHVzfSIpCiAgICAgICAgICAgIHN0YXR1c19pdGVtLnNl"
    "dERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCB0YXNrLmdldCgiaWQiKSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxl"
    "LnNldEl0ZW0ocm93LCAwLCBzdGF0dXNfaXRlbSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAxLCBR"
    "VGFibGVXaWRnZXRJdGVtKGR1ZSkpCiAgICAgICAgICAgIHNlbGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMiwgUVRhYmxlV2lk"
    "Z2V0SXRlbSh0ZXh0KSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAzLCBRVGFibGVXaWRnZXRJdGVt"
    "KHNvdXJjZSkpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkxvYWRlZCB7bGVuKHRhc2tzKX0gdGFzayhzKS4i"
    "KQogICAgICAgIHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0dG9uX3N0YXRlKCkKCiAgICBkZWYgX2RpYWcoc2VsZiwgbWVzc2FnZTog"
    "c3RyLCBsZXZlbDogc3RyID0gIklORk8iKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgaWYgc2VsZi5fZGlhZ19s"
    "b2dnZXI6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX2xvZ2dlcihtZXNzYWdlLCBsZXZlbCkKICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgZGVmIHN0b3BfcmVmcmVzaF93b3JrZXIoc2VsZiwgcmVhc29uOiBzdHIgPSAi"
    "IikgLT4gTm9uZToKICAgICAgICB0aHJlYWQgPSBnZXRhdHRyKHNlbGYsICJfcmVmcmVzaF90aHJlYWQiLCBOb25lKQogICAgICAg"
    "IGlmIHRocmVhZCBpcyBub3QgTm9uZSBhbmQgaGFzYXR0cih0aHJlYWQsICJpc1J1bm5pbmciKSBhbmQgdGhyZWFkLmlzUnVubmlu"
    "ZygpOgogICAgICAgICAgICBzZWxmLl9kaWFnKAogICAgICAgICAgICAgICAgZiJbVEFTS1NdW1RIUkVBRF1bV0FSTl0gc3RvcCBy"
    "ZXF1ZXN0ZWQgZm9yIHJlZnJlc2ggd29ya2VyIHJlYXNvbj17cmVhc29uIG9yICd1bnNwZWNpZmllZCd9IiwKICAgICAgICAgICAg"
    "ICAgICJXQVJOIiwKICAgICAgICAgICAgKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICB0aHJlYWQucmVxdWVzdElu"
    "dGVycnVwdGlvbigpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCiAgICAgICAgICAg"
    "IHRyeToKICAgICAgICAgICAgICAgIHRocmVhZC5xdWl0KCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAg"
    "ICAgICAgIHBhc3MKICAgICAgICAgICAgdGhyZWFkLndhaXQoMjAwMCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3RocmVhZCA9IE5v"
    "bmUKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBjYWxsYWJsZShzZWxmLl90YXNrc19wcm92"
    "aWRlcik6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5sb2FkX3Rhc2tzKHNlbGYuX3Rh"
    "c2tzX3Byb3ZpZGVyKCkpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fZGlhZyhmIltU"
    "QVNLU11bVEFCXVtFUlJPUl0gcmVmcmVzaCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiKQogICAgICAgICAgICBzZWxmLnN0b3BfcmVm"
    "cmVzaF93b3JrZXIocmVhc29uPSJ0YXNrc190YWJfcmVmcmVzaF9leGNlcHRpb24iKQoKICAgIGRlZiBjbG9zZUV2ZW50KHNlbGYs"
    "IGV2ZW50KSAtPiBOb25lOgogICAgICAgIHNlbGYuc3RvcF9yZWZyZXNoX3dvcmtlcihyZWFzb249InRhc2tzX3RhYl9jbG9zZSIp"
    "CiAgICAgICAgc3VwZXIoKS5jbG9zZUV2ZW50KGV2ZW50KQoKICAgIGRlZiBzZXRfc2hvd19jb21wbGV0ZWQoc2VsZiwgZW5hYmxl"
    "ZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9zaG93X2NvbXBsZXRlZCA9IGJvb2woZW5hYmxlZCkKICAgICAgICBzZWxm"
    "LmJ0bl90b2dnbGVfY29tcGxldGVkLnNldFRleHQoIkhJREUgQ09NUExFVEVEIiBpZiBzZWxmLl9zaG93X2NvbXBsZXRlZCBlbHNl"
    "ICJTSE9XIENPTVBMRVRFRCIpCgogICAgZGVmIHNldF9zdGF0dXMoc2VsZiwgdGV4dDogc3RyLCBvazogYm9vbCA9IEZhbHNlKSAt"
    "PiBOb25lOgogICAgICAgIGNvbG9yID0gQ19HUkVFTiBpZiBvayBlbHNlIENfVEVYVF9ESU0KICAgICAgICBzZWxmLnRhc2tfZWRp"
    "dG9yX3N0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7"
    "Y29sb3J9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA2cHg7IgogICAgICAgICkKICAgICAgICBzZWxm"
    "LnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbC5zZXRUZXh0KHRleHQpCgogICAgZGVmIG9wZW5fZWRpdG9yKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suc2V0Q3VycmVudFdpZGdldChzZWxmLmVkaXRvcl93b3Jrc3BhY2UpCgogICAg"
    "ZGVmIGNsb3NlX2VkaXRvcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRn"
    "ZXQoc2VsZi5ub3JtYWxfd29ya3NwYWNlKQoKCmNsYXNzIFNlbGZUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFBlcnNvbmEncyBp"
    "bnRlcm5hbCBkaWFsb2d1ZSBzcGFjZS4KICAgIFJlY2VpdmVzOiBpZGxlIG5hcnJhdGl2ZSBvdXRwdXQsIHVuc29saWNpdGVkIHRy"
    "YW5zbWlzc2lvbnMsCiAgICAgICAgICAgICAgUG9JIGxpc3QgZnJvbSBkYWlseSByZWZsZWN0aW9uLCB1bmFuc3dlcmVkIHF1ZXN0"
    "aW9uIGZsYWdzLAogICAgICAgICAgICAgIGpvdXJuYWwgbG9hZCBub3RpZmljYXRpb25zLgogICAgUmVhZC1vbmx5IGRpc3BsYXku"
    "IFNlcGFyYXRlIGZyb20gcGVyc29uYSBjaGF0IHRhYiBhbHdheXMuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFy"
    "ZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxm"
    "KQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgog"
    "ICAgICAgIGhkciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBoZHIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibChmIuKdpyBJTk5FUiBT"
    "QU5DVFVNIOKAlCB7REVDS19OQU1FLnVwcGVyKCl9J1MgUFJJVkFURSBUSE9VR0hUUyIpKQogICAgICAgIHNlbGYuX2J0bl9jbGVh"
    "ciA9IF9nb3RoaWNfYnRuKCLinJcgQ2xlYXIiKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5zZXRGaXhlZFdpZHRoKDgwKQogICAg"
    "ICAgIHNlbGYuX2J0bl9jbGVhci5jbGlja2VkLmNvbm5lY3Qoc2VsZi5jbGVhcikKICAgICAgICBoZHIuYWRkU3RyZXRjaCgpCiAg"
    "ICAgICAgaGRyLmFkZFdpZGdldChzZWxmLl9idG5fY2xlYXIpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoaGRyKQoKICAgICAgICBz"
    "ZWxmLl9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAg"
    "c2VsZi5fZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjog"
    "e0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19QVVJQTEVfRElNfTsgIgogICAgICAgICAgICBm"
    "ImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogOHB4OyIKICAgICAgICAp"
    "CiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fZGlzcGxheSwgMSkKCiAgICBkZWYgYXBwZW5kKHNlbGYsIGxhYmVsOiBzdHIs"
    "IHRleHQ6IHN0cikgLT4gTm9uZToKICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMi"
    "KQogICAgICAgIGNvbG9ycyA9IHsKICAgICAgICAgICAgIk5BUlJBVElWRSI6ICBDX0dPTEQsCiAgICAgICAgICAgICJSRUZMRUNU"
    "SU9OIjogQ19QVVJQTEUsCiAgICAgICAgICAgICJKT1VSTkFMIjogICAgQ19TSUxWRVIsCiAgICAgICAgICAgICJQT0kiOiAgICAg"
    "ICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAgIlNZU1RFTSI6ICAgICBDX1RFWFRfRElNLAogICAgICAgIH0KICAgICAgICBjb2xv"
    "ciA9IGNvbG9ycy5nZXQobGFiZWwudXBwZXIoKSwgQ19HT0xEKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKAogICAgICAg"
    "ICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICBmJ1t7"
    "dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2NvbG9yfTsgZm9udC13ZWlnaHQ6"
    "Ym9sZDsiPicKICAgICAgICAgICAgZifinacge2xhYmVsfTwvc3Bhbj48YnI+JwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJj"
    "b2xvcjp7Q19HT0xEfTsiPnt0ZXh0fTwvc3Bhbj4nCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKCIiKQog"
    "ICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fZGlzcGxh"
    "eS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQogICAgICAgICkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLl9kaXNwbGF5LmNsZWFyKCkKCgojIOKUgOKUgCBESUFHTk9TVElDUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACmNsYXNzIERpYWdub3N0aWNzVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBCYWNrZW5kIGRpYWdub3N0aWNzIGRpc3Bs"
    "YXkuCiAgICBSZWNlaXZlczogaGFyZHdhcmUgZGV0ZWN0aW9uIHJlc3VsdHMsIGRlcGVuZGVuY3kgY2hlY2sgcmVzdWx0cywKICAg"
    "ICAgICAgICAgICBBUEkgZXJyb3JzLCBzeW5jIGZhaWx1cmVzLCB0aW1lciBldmVudHMsIGpvdXJuYWwgbG9hZCBub3RpY2VzLAog"
    "ICAgICAgICAgICAgIG1vZGVsIGxvYWQgc3RhdHVzLCBHb29nbGUgYXV0aCBldmVudHMuCiAgICBBbHdheXMgc2VwYXJhdGUgZnJv"
    "bSBwZXJzb25hIGNoYXQgdGFiLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBz"
    "dXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENv"
    "bnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBoZHIgPSBRSEJveExh"
    "eW91dCgpCiAgICAgICAgaGRyLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBESUFHTk9TVElDUyDigJQgU1lTVEVNICYgQkFD"
    "S0VORCBMT0ciKSkKICAgICAgICBzZWxmLl9idG5fY2xlYXIgPSBfZ290aGljX2J0bigi4pyXIENsZWFyIikKICAgICAgICBzZWxm"
    "Ll9idG5fY2xlYXIuc2V0Rml4ZWRXaWR0aCg4MCkKICAgICAgICBzZWxmLl9idG5fY2xlYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "Y2xlYXIpCiAgICAgICAgaGRyLmFkZFN0cmV0Y2goKQogICAgICAgIGhkci5hZGRXaWRnZXQoc2VsZi5fYnRuX2NsZWFyKQogICAg"
    "ICAgIHJvb3QuYWRkTGF5b3V0KGhkcikKCiAgICAgICAgc2VsZi5fZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5f"
    "ZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX1NJTFZFUn07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBz"
    "b2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6ICdDb3VyaWVyIE5ldycsIG1vbm9zcGFjZTsgIgog"
    "ICAgICAgICAgICBmImZvbnQtc2l6ZTogMTBweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRn"
    "ZXQoc2VsZi5fZGlzcGxheSwgMSkKCiAgICBkZWYgbG9nKHNlbGYsIG1lc3NhZ2U6IHN0ciwgbGV2ZWw6IHN0ciA9ICJJTkZPIikg"
    "LT4gTm9uZToKICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgIGxl"
    "dmVsX2NvbG9ycyA9IHsKICAgICAgICAgICAgIklORk8iOiAgQ19TSUxWRVIsCiAgICAgICAgICAgICJPSyI6ICAgIENfR1JFRU4s"
    "CiAgICAgICAgICAgICJXQVJOIjogIENfR09MRCwKICAgICAgICAgICAgIkVSUk9SIjogQ19CTE9PRCwKICAgICAgICAgICAgIkRF"
    "QlVHIjogQ19URVhUX0RJTSwKICAgICAgICB9CiAgICAgICAgY29sb3IgPSBsZXZlbF9jb2xvcnMuZ2V0KGxldmVsLnVwcGVyKCks"
    "IENfU0lMVkVSKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7"
    "Q19URVhUX0RJTX07Ij5be3RpbWVzdGFtcH1dPC9zcGFuPiAnCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2xv"
    "cn07Ij57bWVzc2FnZX08L3NwYW4+JwogICAgICAgICkKICAgICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCku"
    "c2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICAp"
    "CgogICAgZGVmIGxvZ19tYW55KHNlbGYsIG1lc3NhZ2VzOiBsaXN0W3N0cl0sIGxldmVsOiBzdHIgPSAiSU5GTyIpIC0+IE5vbmU6"
    "CiAgICAgICAgZm9yIG1zZyBpbiBtZXNzYWdlczoKICAgICAgICAgICAgbHZsID0gbGV2ZWwKICAgICAgICAgICAgaWYgIuKckyIg"
    "aW4gbXNnOiAgICBsdmwgPSAiT0siCiAgICAgICAgICAgIGVsaWYgIuKclyIgaW4gbXNnOiAgbHZsID0gIldBUk4iCiAgICAgICAg"
    "ICAgIGVsaWYgIkVSUk9SIiBpbiBtc2cudXBwZXIoKTogbHZsID0gIkVSUk9SIgogICAgICAgICAgICBzZWxmLmxvZyhtc2csIGx2"
    "bCkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kaXNwbGF5LmNsZWFyKCkKCgojIOKUgOKUgCBM"
    "RVNTT05TIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTGVzc29uc1RhYihRV2lkZ2V0"
    "KToKICAgICIiIgogICAgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGFuZCBjb2RlIGxlc3NvbnMgYnJvd3Nlci4KICAgIEFkZCwgdmll"
    "dywgc2VhcmNoLCBkZWxldGUgbGVzc29ucy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBkYjogIkxlc3NvbnNMZWFy"
    "bmVkREIiLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZGIgPSBk"
    "YgogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0"
    "LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICAjIEZpbHRlciBiYXIKICAgICAgICBmaWx0ZXJf"
    "cm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX3NlYXJjaCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fc2VhcmNo"
    "LnNldFBsYWNlaG9sZGVyVGV4dCgiU2VhcmNoIGxlc3NvbnMuLi4iKQogICAgICAgIHNlbGYuX2xhbmdfZmlsdGVyID0gUUNvbWJv"
    "Qm94KCkKICAgICAgICBzZWxmLl9sYW5nX2ZpbHRlci5hZGRJdGVtcyhbIkFsbCIsICJMU0wiLCAiUHl0aG9uIiwgIlB5U2lkZTYi"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIkphdmFTY3JpcHQiLCAiT3RoZXIiXSkKICAgICAgICBzZWxm"
    "Ll9zZWFyY2gudGV4dENoYW5nZWQuY29ubmVjdChzZWxmLnJlZnJlc2gpCiAgICAgICAgc2VsZi5fbGFuZ19maWx0ZXIuY3VycmVu"
    "dFRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5yZWZyZXNoKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgiU2Vh"
    "cmNoOiIpKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYuX3NlYXJjaCwgMSkKICAgICAgICBmaWx0ZXJfcm93LmFk"
    "ZFdpZGdldChRTGFiZWwoIkxhbmd1YWdlOiIpKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYuX2xhbmdfZmlsdGVy"
    "KQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGZpbHRlcl9yb3cpCgogICAgICAgIGJ0bl9iYXIgPSBRSEJveExheW91dCgpCiAgICAg"
    "ICAgYnRuX2FkZCA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIExlc3NvbiIpCiAgICAgICAgYnRuX2RlbCA9IF9nb3RoaWNfYnRuKCLi"
    "nJcgRGVsZXRlIikKICAgICAgICBidG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgYnRuX2RlbC5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIGJ0bl9iYXIuYWRkV2lkZ2V0KGJ0bl9hZGQpCiAgICAgICAg"
    "YnRuX2Jhci5hZGRXaWRnZXQoYnRuX2RlbCkKICAgICAgICBidG5fYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5"
    "b3V0KGJ0bl9iYXIpCgogICAgICAgIHNlbGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDQpCiAgICAgICAgc2VsZi5fdGFibGUu"
    "c2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscygKICAgICAgICAgICAgWyJMYW5ndWFnZSIsICJSZWZlcmVuY2UgS2V5IiwgIlN1bW1h"
    "cnkiLCAiRW52aXJvbm1lbnQiXQogICAgICAgICkKICAgICAgICBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2Vj"
    "dGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDIsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxm"
    "Ll90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZp"
    "b3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLl90YWJsZS5zZXRBbHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVlKQogICAgICAgIHNl"
    "bGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX3RhYmxlLml0ZW1TZWxl"
    "Y3Rpb25DaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fc2VsZWN0KQoKICAgICAgICAjIFVzZSBzcGxpdHRlciBiZXR3ZWVuIHRhYmxl"
    "IGFuZCBkZXRhaWwKICAgICAgICBzcGxpdHRlciA9IFFTcGxpdHRlcihRdC5PcmllbnRhdGlvbi5WZXJ0aWNhbCkKICAgICAgICBz"
    "cGxpdHRlci5hZGRXaWRnZXQoc2VsZi5fdGFibGUpCgogICAgICAgICMgRGV0YWlsIHBhbmVsCiAgICAgICAgZGV0YWlsX3dpZGdl"
    "dCA9IFFXaWRnZXQoKQogICAgICAgIGRldGFpbF9sYXlvdXQgPSBRVkJveExheW91dChkZXRhaWxfd2lkZ2V0KQogICAgICAgIGRl"
    "dGFpbF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDQsIDAsIDApCiAgICAgICAgZGV0YWlsX2xheW91dC5zZXRTcGFjaW5n"
    "KDIpCgogICAgICAgIGRldGFpbF9oZWFkZXIgPSBRSEJveExheW91dCgpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRXaWRnZXQo"
    "X3NlY3Rpb25fbGJsKCLinacgRlVMTCBSVUxFIikpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRTdHJldGNoKCkKICAgICAgICBz"
    "ZWxmLl9idG5fZWRpdF9ydWxlID0gX2dvdGhpY19idG4oIkVkaXQiKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Rml4"
    "ZWRXaWR0aCg1MCkKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldENoZWNrYWJsZShUcnVlKQogICAgICAgIHNlbGYuX2J0"
    "bl9lZGl0X3J1bGUudG9nZ2xlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9lZGl0X21vZGUpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVf"
    "cnVsZSA9IF9nb3RoaWNfYnRuKCJTYXZlIikKICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlLnNldEZpeGVkV2lkdGgoNTApCiAg"
    "ICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRWaXNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX3NhdmVfcnVsZV9lZGl0KQogICAgICAgIGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KHNlbGYuX2J0"
    "bl9lZGl0X3J1bGUpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRXaWRnZXQoc2VsZi5fYnRuX3NhdmVfcnVsZSkKICAgICAgICBk"
    "ZXRhaWxfbGF5b3V0LmFkZExheW91dChkZXRhaWxfaGVhZGVyKQoKICAgICAgICBzZWxmLl9kZXRhaWwgPSBRVGV4dEVkaXQoKQog"
    "ICAgICAgIHNlbGYuX2RldGFpbC5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2RldGFpbC5zZXRNaW5pbXVtSGVpZ2h0"
    "KDEyMCkKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9"
    "OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAg"
    "ICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAg"
    "ICAgICkKICAgICAgICBkZXRhaWxfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9kZXRhaWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lk"
    "Z2V0KGRldGFpbF93aWRnZXQpCiAgICAgICAgc3BsaXR0ZXIuc2V0U2l6ZXMoWzMwMCwgMTgwXSkKICAgICAgICByb290LmFkZFdp"
    "ZGdldChzcGxpdHRlciwgMSkKCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fZWRp"
    "dGluZ19yb3c6IGludCA9IC0xCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBxICAgID0gc2VsZi5fc2Vh"
    "cmNoLnRleHQoKQogICAgICAgIGxhbmcgPSBzZWxmLl9sYW5nX2ZpbHRlci5jdXJyZW50VGV4dCgpCiAgICAgICAgbGFuZyA9ICIi"
    "IGlmIGxhbmcgPT0gIkFsbCIgZWxzZSBsYW5nCiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHNlbGYuX2RiLnNlYXJjaChxdWVyeT1x"
    "LCBsYW5ndWFnZT1sYW5nKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxm"
    "Ll9yZWNvcmRzOgogICAgICAgICAgICByID0gc2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5p"
    "bnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lk"
    "Z2V0SXRlbShyZWMuZ2V0KCJsYW5ndWFnZSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAxLAogICAg"
    "ICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJyZWZlcmVuY2Vfa2V5IiwiIikpKQogICAgICAgICAgICBzZWxm"
    "Ll90YWJsZS5zZXRJdGVtKHIsIDIsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInN1bW1hcnkiLCIi"
    "KSkpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMywKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0o"
    "cmVjLmdldCgiZW52aXJvbm1lbnQiLCIiKSkpCgogICAgZGVmIF9vbl9zZWxlY3Qoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cg"
    "PSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBzZWxmLl9lZGl0aW5nX3JvdyA9IHJvdwogICAgICAgIGlmIDAgPD0g"
    "cm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICAgICAg"
    "c2VsZi5fZGV0YWlsLnNldFBsYWluVGV4dCgKICAgICAgICAgICAgICAgIHJlYy5nZXQoImZ1bGxfcnVsZSIsIiIpICsgIlxuXG4i"
    "ICsKICAgICAgICAgICAgICAgICgiUmVzb2x1dGlvbjogIiArIHJlYy5nZXQoInJlc29sdXRpb24iLCIiKSBpZiByZWMuZ2V0KCJy"
    "ZXNvbHV0aW9uIikgZWxzZSAiIikKICAgICAgICAgICAgKQogICAgICAgICAgICAjIFJlc2V0IGVkaXQgbW9kZSBvbiBuZXcgc2Vs"
    "ZWN0aW9uCiAgICAgICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Q2hlY2tlZChGYWxzZSkKCiAgICBkZWYgX3RvZ2dsZV9l"
    "ZGl0X21vZGUoc2VsZiwgZWRpdGluZzogYm9vbCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0UmVhZE9ubHkobm90"
    "IGVkaXRpbmcpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRWaXNpYmxlKGVkaXRpbmcpCiAgICAgICAgc2VsZi5fYnRu"
    "X2VkaXRfcnVsZS5zZXRUZXh0KCJDYW5jZWwiIGlmIGVkaXRpbmcgZWxzZSAiRWRpdCIpCiAgICAgICAgaWYgZWRpdGluZzoKICAg"
    "ICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07"
    "IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEX0RJTX07ICIKICAg"
    "ICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0"
    "cHg7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICAgICAgZiJi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwg"
    "c2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIFJlbG9hZCBv"
    "cmlnaW5hbCBjb250ZW50IG9uIGNhbmNlbAogICAgICAgICAgICBzZWxmLl9vbl9zZWxlY3QoKQoKICAgIGRlZiBfc2F2ZV9ydWxl"
    "X2VkaXQoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl9lZGl0aW5nX3JvdwogICAgICAgIGlmIDAgPD0gcm93IDwg"
    "bGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICB0ZXh0ID0gc2VsZi5fZGV0YWlsLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQog"
    "ICAgICAgICAgICAjIFNwbGl0IHJlc29sdXRpb24gYmFjayBvdXQgaWYgcHJlc2VudAogICAgICAgICAgICBpZiAiXG5cblJlc29s"
    "dXRpb246ICIgaW4gdGV4dDoKICAgICAgICAgICAgICAgIHBhcnRzID0gdGV4dC5zcGxpdCgiXG5cblJlc29sdXRpb246ICIsIDEp"
    "CiAgICAgICAgICAgICAgICBmdWxsX3J1bGUgID0gcGFydHNbMF0uc3RyaXAoKQogICAgICAgICAgICAgICAgcmVzb2x1dGlvbiA9"
    "IHBhcnRzWzFdLnN0cmlwKCkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZSAgPSB0ZXh0CiAgICAg"
    "ICAgICAgICAgICByZXNvbHV0aW9uID0gc2VsZi5fcmVjb3Jkc1tyb3ddLmdldCgicmVzb2x1dGlvbiIsICIiKQogICAgICAgICAg"
    "ICBzZWxmLl9yZWNvcmRzW3Jvd11bImZ1bGxfcnVsZSJdICA9IGZ1bGxfcnVsZQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jv"
    "d11bInJlc29sdXRpb24iXSA9IHJlc29sdXRpb24KICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fZGIuX3BhdGgsIHNlbGYu"
    "X3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Q2hlY2tlZChGYWxzZSkKICAgICAgICAgICAgc2Vs"
    "Zi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAg"
    "ICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkFkZCBMZXNzb24iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3Vu"
    "ZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAsIDQwMCkKICAgICAgICBmb3JtID0g"
    "UUZvcm1MYXlvdXQoZGxnKQogICAgICAgIGVudiAgPSBRTGluZUVkaXQoIkxTTCIpCiAgICAgICAgbGFuZyA9IFFMaW5lRWRpdCgi"
    "TFNMIikKICAgICAgICByZWYgID0gUUxpbmVFZGl0KCkKICAgICAgICBzdW1tID0gUUxpbmVFZGl0KCkKICAgICAgICBydWxlID0g"
    "UVRleHRFZGl0KCkKICAgICAgICBydWxlLnNldE1heGltdW1IZWlnaHQoMTAwKQogICAgICAgIHJlcyAgPSBRTGluZUVkaXQoKQog"
    "ICAgICAgIGxpbmsgPSBRTGluZUVkaXQoKQogICAgICAgIGZvciBsYWJlbCwgdyBpbiBbCiAgICAgICAgICAgICgiRW52aXJvbm1l"
    "bnQ6IiwgZW52KSwgKCJMYW5ndWFnZToiLCBsYW5nKSwKICAgICAgICAgICAgKCJSZWZlcmVuY2UgS2V5OiIsIHJlZiksICgiU3Vt"
    "bWFyeToiLCBzdW1tKSwKICAgICAgICAgICAgKCJGdWxsIFJ1bGU6IiwgcnVsZSksICgiUmVzb2x1dGlvbjoiLCByZXMpLAogICAg"
    "ICAgICAgICAoIkxpbms6IiwgbGluayksCiAgICAgICAgXToKICAgICAgICAgICAgZm9ybS5hZGRSb3cobGFiZWwsIHcpCiAgICAg"
    "ICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4o"
    "IkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJl"
    "amVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0"
    "bnMpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHNlbGYu"
    "X2RiLmFkZCgKICAgICAgICAgICAgICAgIGVudmlyb25tZW50PWVudi50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGxh"
    "bmd1YWdlPWxhbmcudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICByZWZlcmVuY2Vfa2V5PXJlZi50ZXh0KCkuc3RyaXAo"
    "KSwKICAgICAgICAgICAgICAgIHN1bW1hcnk9c3VtbS50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZT1y"
    "dWxlLnRvUGxhaW5UZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIHJlc29sdXRpb249cmVzLnRleHQoKS5zdHJpcCgpLAog"
    "ICAgICAgICAgICAgICAgbGluaz1saW5rLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYucmVm"
    "cmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50"
    "Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmVjX2lkID0gc2VsZi5f"
    "cmVjb3Jkc1tyb3ddLmdldCgiaWQiLCIiKQogICAgICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAg"
    "ICAgICAgICAgc2VsZiwgIkRlbGV0ZSBMZXNzb24iLAogICAgICAgICAgICAgICAgIkRlbGV0ZSB0aGlzIGxlc3Nvbj8gQ2Fubm90"
    "IGJlIHVuZG9uZS4iLAogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3gu"
    "U3RhbmRhcmRCdXR0b24uTm8KICAgICAgICAgICAgKQogICAgICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFy"
    "ZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgICAgICBzZWxmLl9kYi5kZWxldGUocmVjX2lkKQogICAgICAgICAgICAgICAgc2VsZi5y"
    "ZWZyZXNoKCkKCgojIOKUgOKUgCBNT0RVTEUgVFJBQ0tFUiBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1vZHVsZVRyYWNr"
    "ZXJUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFBlcnNvbmFsIG1vZHVsZSBwaXBlbGluZSB0cmFja2VyLgogICAgVHJhY2sgcGxh"
    "bm5lZC9pbi1wcm9ncmVzcy9idWlsdCBtb2R1bGVzIGFzIHRoZXkgYXJlIGRlc2lnbmVkLgogICAgRWFjaCBtb2R1bGUgaGFzOiBO"
    "YW1lLCBTdGF0dXMsIERlc2NyaXB0aW9uLCBOb3Rlcy4KICAgIEV4cG9ydCB0byBUWFQgZm9yIHBhc3RpbmcgaW50byBzZXNzaW9u"
    "cy4KICAgIEltcG9ydDogcGFzdGUgYSBmaW5hbGl6ZWQgc3BlYywgaXQgcGFyc2VzIG5hbWUgYW5kIGRldGFpbHMuCiAgICBUaGlz"
    "IGlzIGEgZGVzaWduIG5vdGVib29rIOKAlCBub3QgY29ubmVjdGVkIHRvIGRlY2tfYnVpbGRlcidzIE1PRFVMRSByZWdpc3RyeS4K"
    "ICAgICIiIgoKICAgIFNUQVRVU0VTID0gWyJJZGVhIiwgIkRlc2lnbmluZyIsICJSZWFkeSB0byBCdWlsZCIsICJQYXJ0aWFsIiwg"
    "IkJ1aWx0Il0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFy"
    "ZW50KQogICAgICAgIHNlbGYuX3BhdGggPSBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJtb2R1bGVfdHJhY2tlci5qc29ubCIKICAg"
    "ICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5y"
    "ZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYp"
    "CiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAg"
    "ICAgICAgIyBCdXR0b24gYmFyCiAgICAgICAgYnRuX2JhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAg"
    "ID0gX2dvdGhpY19idG4oIkFkZCBNb2R1bGUiKQogICAgICAgIHNlbGYuX2J0bl9lZGl0ICAgPSBfZ290aGljX2J0bigiRWRpdCIp"
    "CiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSA9IF9nb3RoaWNfYnRuKCJEZWxldGUiKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQg"
    "PSBfZ290aGljX2J0bigiRXhwb3J0IFRYVCIpCiAgICAgICAgc2VsZi5fYnRuX2ltcG9ydCA9IF9nb3RoaWNfYnRuKCJJbXBvcnQg"
    "U3BlYyIpCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9lZGl0LCBzZWxmLl9idG5fZGVsZXRlLAog"
    "ICAgICAgICAgICAgICAgICBzZWxmLl9idG5fZXhwb3J0LCBzZWxmLl9idG5faW1wb3J0KToKICAgICAgICAgICAgYi5zZXRNaW5p"
    "bXVtV2lkdGgoODApCiAgICAgICAgICAgIGIuc2V0TWluaW11bUhlaWdodCgyNikKICAgICAgICAgICAgYnRuX2Jhci5hZGRXaWRn"
    "ZXQoYikKICAgICAgICBidG5fYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJ0bl9iYXIpCgogICAgICAg"
    "IHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAgICBzZWxmLl9idG5fZWRpdC5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fZG9fZWRpdCkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19k"
    "ZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZXhwb3J0KQogICAgICAgIHNl"
    "bGYuX2J0bl9pbXBvcnQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2ltcG9ydCkKCiAgICAgICAgIyBUYWJsZQogICAgICAgIHNl"
    "bGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDMpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVs"
    "cyhbIk1vZHVsZSBOYW1lIiwgIlN0YXR1cyIsICJEZXNjcmlwdGlvbiJdKQogICAgICAgIGhoID0gc2VsZi5fdGFibGUuaG9yaXpv"
    "bnRhbEhlYWRlcigpCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhl"
    "ZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgwLCAxNjApCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1v"
    "ZGUoMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgxLCAx"
    "MDApCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAg"
    "ICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rp"
    "b25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAg"
    "ICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2VsZi5fdGFibGUu"
    "aXRlbVNlbGVjdGlvbkNoYW5nZWQuY29ubmVjdChzZWxmLl9vbl9zZWxlY3QpCgogICAgICAgICMgU3BsaXR0ZXIKICAgICAgICBz"
    "cGxpdHRlciA9IFFTcGxpdHRlcihRdC5PcmllbnRhdGlvbi5WZXJ0aWNhbCkKICAgICAgICBzcGxpdHRlci5hZGRXaWRnZXQoc2Vs"
    "Zi5fdGFibGUpCgogICAgICAgICMgTm90ZXMgcGFuZWwKICAgICAgICBub3Rlc193aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBu"
    "b3Rlc19sYXlvdXQgPSBRVkJveExheW91dChub3Rlc193aWRnZXQpCiAgICAgICAgbm90ZXNfbGF5b3V0LnNldENvbnRlbnRzTWFy"
    "Z2lucygwLCA0LCAwLCAwKQogICAgICAgIG5vdGVzX2xheW91dC5zZXRTcGFjaW5nKDIpCiAgICAgICAgbm90ZXNfbGF5b3V0LmFk"
    "ZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBOT1RFUyIpKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkgPSBRVGV4dEVkaXQo"
    "KQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5"
    "LnNldE1pbmltdW1IZWlnaHQoMTIwKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xp"
    "ZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAx"
    "MXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICkKICAgICAgICBub3Rlc19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX25vdGVzX2Rp"
    "c3BsYXkpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KG5vdGVzX3dpZGdldCkKICAgICAgICBzcGxpdHRlci5zZXRTaXplcyhb"
    "MjUwLCAxNTBdKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNwbGl0dGVyLCAxKQoKICAgICAgICAjIENvdW50IGxhYmVsCiAgICAg"
    "ICAgc2VsZi5fY291bnRfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYuX2NvdW50X2xibC5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNl"
    "cmlmOyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fY291bnRfbGJsKQoKICAgIGRlZiByZWZyZXNoKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBzZWxmLl90"
    "YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9IHNlbGYu"
    "X3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX3Rh"
    "YmxlLnNldEl0ZW0ociwgMCwgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJuYW1lIiwgIiIpKSkKICAgICAgICAgICAgc3RhdHVz"
    "X2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInN0YXR1cyIsICJJZGVhIikpCiAgICAgICAgICAgICMgQ29sb3IgYnkg"
    "c3RhdHVzCiAgICAgICAgICAgIHN0YXR1c19jb2xvcnMgPSB7CiAgICAgICAgICAgICAgICAiSWRlYSI6ICAgICAgICAgICAgIENf"
    "VEVYVF9ESU0sCiAgICAgICAgICAgICAgICAiRGVzaWduaW5nIjogICAgICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgICAgICAi"
    "UmVhZHkgdG8gQnVpbGQiOiAgIENfUFVSUExFLAogICAgICAgICAgICAgICAgIlBhcnRpYWwiOiAgICAgICAgICAiI2NjODg0NCIs"
    "CiAgICAgICAgICAgICAgICAiQnVpbHQiOiAgICAgICAgICAgIENfR1JFRU4sCiAgICAgICAgICAgIH0KICAgICAgICAgICAgc3Rh"
    "dHVzX2l0ZW0uc2V0Rm9yZWdyb3VuZCgKICAgICAgICAgICAgICAgIFFDb2xvcihzdGF0dXNfY29sb3JzLmdldChyZWMuZ2V0KCJz"
    "dGF0dXMiLCJJZGVhIiksIENfVEVYVF9ESU0pKQogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0o"
    "ciwgMSwgc3RhdHVzX2l0ZW0pCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMiwKICAgICAgICAgICAgICAgIFFU"
    "YWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiZGVzY3JpcHRpb24iLCAiIilbOjgwXSkpCiAgICAgICAgY291bnRzID0ge30KICAgICAg"
    "ICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIHMgPSByZWMuZ2V0KCJzdGF0dXMiLCAiSWRlYSIpCiAgICAg"
    "ICAgICAgIGNvdW50c1tzXSA9IGNvdW50cy5nZXQocywgMCkgKyAxCiAgICAgICAgY291bnRfc3RyID0gIiAgIi5qb2luKGYie3N9"
    "OiB7bn0iIGZvciBzLCBuIGluIGNvdW50cy5pdGVtcygpKQogICAgICAgIHNlbGYuX2NvdW50X2xibC5zZXRUZXh0KAogICAgICAg"
    "ICAgICBmIlRvdGFsOiB7bGVuKHNlbGYuX3JlY29yZHMpfSAgIHtjb3VudF9zdHJ9IgogICAgICAgICkKCiAgICBkZWYgX29uX3Nl"
    "bGVjdChzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0g"
    "cm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICAgICAg"
    "c2VsZi5fbm90ZXNfZGlzcGxheS5zZXRQbGFpblRleHQocmVjLmdldCgibm90ZXMiLCAiIikpCgogICAgZGVmIF9kb19hZGQoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9vcGVuX2VkaXRfZGlhbG9nKCkKCiAgICBkZWYgX2RvX2VkaXQoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9y"
    "ZWNvcmRzKToKICAgICAgICAgICAgc2VsZi5fb3Blbl9lZGl0X2RpYWxvZyhzZWxmLl9yZWNvcmRzW3Jvd10sIHJvdykKCiAgICBk"
    "ZWYgX29wZW5fZWRpdF9kaWFsb2coc2VsZiwgcmVjOiBkaWN0ID0gTm9uZSwgcm93OiBpbnQgPSAtMSkgLT4gTm9uZToKICAgICAg"
    "ICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJNb2R1bGUiIGlmIG5vdCByZWMgZWxzZSBm"
    "IkVkaXQ6IHtyZWMuZ2V0KCduYW1lJywnJyl9IikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JH"
    "Mn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5yZXNpemUoNTQwLCA0NDApCiAgICAgICAgZm9ybSA9IFFWQm94TGF5"
    "b3V0KGRsZykKCiAgICAgICAgbmFtZV9maWVsZCA9IFFMaW5lRWRpdChyZWMuZ2V0KCJuYW1lIiwiIikgaWYgcmVjIGVsc2UgIiIp"
    "CiAgICAgICAgbmFtZV9maWVsZC5zZXRQbGFjZWhvbGRlclRleHQoIk1vZHVsZSBuYW1lIikKCiAgICAgICAgc3RhdHVzX2NvbWJv"
    "ID0gUUNvbWJvQm94KCkKICAgICAgICBzdGF0dXNfY29tYm8uYWRkSXRlbXMoc2VsZi5TVEFUVVNFUykKICAgICAgICBpZiByZWM6"
    "CiAgICAgICAgICAgIGlkeCA9IHN0YXR1c19jb21iby5maW5kVGV4dChyZWMuZ2V0KCJzdGF0dXMiLCJJZGVhIikpCiAgICAgICAg"
    "ICAgIGlmIGlkeCA+PSAwOgogICAgICAgICAgICAgICAgc3RhdHVzX2NvbWJvLnNldEN1cnJlbnRJbmRleChpZHgpCgogICAgICAg"
    "IGRlc2NfZmllbGQgPSBRTGluZUVkaXQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBk"
    "ZXNjX2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgiT25lLWxpbmUgZGVzY3JpcHRpb24iKQoKICAgICAgICBub3Rlc19maWVsZCA9"
    "IFFUZXh0RWRpdCgpCiAgICAgICAgbm90ZXNfZmllbGQuc2V0UGxhaW5UZXh0KHJlYy5nZXQoIm5vdGVzIiwiIikgaWYgcmVjIGVs"
    "c2UgIiIpCiAgICAgICAgbm90ZXNfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KAogICAgICAgICAgICAiRnVsbCBub3RlcyDigJQg"
    "c3BlYywgaWRlYXMsIHJlcXVpcmVtZW50cywgZWRnZSBjYXNlcy4uLiIKICAgICAgICApCiAgICAgICAgbm90ZXNfZmllbGQuc2V0"
    "TWluaW11bUhlaWdodCgyMDApCgogICAgICAgIGZvciBsYWJlbCwgd2lkZ2V0IGluIFsKICAgICAgICAgICAgKCJOYW1lOiIsIG5h"
    "bWVfZmllbGQpLAogICAgICAgICAgICAoIlN0YXR1czoiLCBzdGF0dXNfY29tYm8pLAogICAgICAgICAgICAoIkRlc2NyaXB0aW9u"
    "OiIsIGRlc2NfZmllbGQpLAogICAgICAgICAgICAoIk5vdGVzOiIsIG5vdGVzX2ZpZWxkKSwKICAgICAgICBdOgogICAgICAgICAg"
    "ICByb3dfbGF5b3V0ID0gUUhCb3hMYXlvdXQoKQogICAgICAgICAgICBsYmwgPSBRTGFiZWwobGFiZWwpCiAgICAgICAgICAgIGxi"
    "bC5zZXRGaXhlZFdpZHRoKDkwKQogICAgICAgICAgICByb3dfbGF5b3V0LmFkZFdpZGdldChsYmwpCiAgICAgICAgICAgIHJvd19s"
    "YXlvdXQuYWRkV2lkZ2V0KHdpZGdldCkKICAgICAgICAgICAgZm9ybS5hZGRMYXlvdXQocm93X2xheW91dCkKCiAgICAgICAgYnRu"
    "X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fc2F2ZSAgID0gX2dvdGhpY19idG4oIlNhdmUiKQogICAgICAgIGJ0bl9j"
    "YW5jZWwgPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBidG5fc2F2ZS5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCkK"
    "ICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0"
    "bl9zYXZlKQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgZm9ybS5hZGRMYXlvdXQoYnRuX3Jv"
    "dykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIG5ld19y"
    "ZWMgPSB7CiAgICAgICAgICAgICAgICAiaWQiOiAgICAgICAgICByZWMuZ2V0KCJpZCIsIHN0cih1dWlkLnV1aWQ0KCkpKSBpZiBy"
    "ZWMgZWxzZSBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgICAgICJuYW1lIjogICAgICAgIG5hbWVfZmllbGQudGV4dCgp"
    "LnN0cmlwKCksCiAgICAgICAgICAgICAgICAic3RhdHVzIjogICAgICBzdGF0dXNfY29tYm8uY3VycmVudFRleHQoKSwKICAgICAg"
    "ICAgICAgICAgICJkZXNjcmlwdGlvbiI6IGRlc2NfZmllbGQudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAibm90ZXMi"
    "OiAgICAgICBub3Rlc19maWVsZC50b1BsYWluVGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAiY3JlYXRlZCI6ICAgICBy"
    "ZWMuZ2V0KCJjcmVhdGVkIiwgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCkpIGlmIHJlYyBlbHNlIGRhdGV0aW1lLm5vdygpLmlz"
    "b2Zvcm1hdCgpLAogICAgICAgICAgICAgICAgIm1vZGlmaWVkIjogICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAg"
    "ICAgICAgIH0KICAgICAgICAgICAgaWYgcm93ID49IDA6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd10gPSBuZXdf"
    "cmVjCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChuZXdfcmVjKQogICAgICAg"
    "ICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAg"
    "IGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAg"
    "ICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIG5hbWUgPSBzZWxmLl9yZWNvcmRzW3Jvd10u"
    "Z2V0KCJuYW1lIiwidGhpcyBtb2R1bGUiKQogICAgICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAg"
    "ICAgICAgICAgc2VsZiwgIkRlbGV0ZSBNb2R1bGUiLAogICAgICAgICAgICAgICAgZiJEZWxldGUgJ3tuYW1lfSc/IENhbm5vdCBi"
    "ZSB1bmRvbmUuIiwKICAgICAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0"
    "YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRC"
    "dXR0b24uWWVzOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5wb3Aocm93KQogICAgICAgICAgICAgICAgd3JpdGVfanNv"
    "bmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19l"
    "eHBvcnQoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGV4cG9ydF9kaXIgPSBjZmdfcGF0aCgiZXhwb3J0"
    "cyIpCiAgICAgICAgICAgIGV4cG9ydF9kaXIubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICB0"
    "cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlWSVtJWRfJUglTSVTIikKICAgICAgICAgICAgb3V0X3BhdGggPSBleHBvcnRf"
    "ZGlyIC8gZiJtb2R1bGVzX3t0c30udHh0IgogICAgICAgICAgICBsaW5lcyA9IFsKICAgICAgICAgICAgICAgICJFQ0hPIERFQ0sg"
    "4oCUIE1PRFVMRSBUUkFDS0VSIEVYUE9SVCIsCiAgICAgICAgICAgICAgICBmIkV4cG9ydGVkOiB7ZGF0ZXRpbWUubm93KCkuc3Ry"
    "ZnRpbWUoJyVZLSVtLSVkICVIOiVNOiVTJyl9IiwKICAgICAgICAgICAgICAgIGYiVG90YWwgbW9kdWxlczoge2xlbihzZWxmLl9y"
    "ZWNvcmRzKX0iLAogICAgICAgICAgICAgICAgIj0iICogNjAsCiAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgXQogICAg"
    "ICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgICAgICBsaW5lcy5leHRlbmQoWwogICAgICAgICAg"
    "ICAgICAgICAgIGYiTU9EVUxFOiB7cmVjLmdldCgnbmFtZScsJycpfSIsCiAgICAgICAgICAgICAgICAgICAgZiJTdGF0dXM6IHty"
    "ZWMuZ2V0KCdzdGF0dXMnLCcnKX0iLAogICAgICAgICAgICAgICAgICAgIGYiRGVzY3JpcHRpb246IHtyZWMuZ2V0KCdkZXNjcmlw"
    "dGlvbicsJycpfSIsCiAgICAgICAgICAgICAgICAgICAgIiIsCiAgICAgICAgICAgICAgICAgICAgIk5vdGVzOiIsCiAgICAgICAg"
    "ICAgICAgICAgICAgcmVjLmdldCgibm90ZXMiLCIiKSwKICAgICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgICAgICAg"
    "ICAiLSIgKiA0MCwKICAgICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgICAgIF0pCiAgICAgICAgICAgIG91dF9wYXRo"
    "LndyaXRlX3RleHQoIlxuIi5qb2luKGxpbmVzKSwgZW5jb2Rpbmc9InV0Zi04IikKICAgICAgICAgICAgUUFwcGxpY2F0aW9uLmNs"
    "aXBib2FyZCgpLnNldFRleHQoIlxuIi5qb2luKGxpbmVzKSkKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oCiAg"
    "ICAgICAgICAgICAgICBzZWxmLCAiRXhwb3J0ZWQiLAogICAgICAgICAgICAgICAgZiJNb2R1bGUgdHJhY2tlciBleHBvcnRlZCB0"
    "bzpcbntvdXRfcGF0aH1cblxuQWxzbyBjb3BpZWQgdG8gY2xpcGJvYXJkLiIKICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb24gYXMgZToKICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2FybmluZyhzZWxmLCAiRXhwb3J0IEVycm9yIiwgc3RyKGUp"
    "KQoKICAgIGRlZiBfZG9faW1wb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiSW1wb3J0IGEgbW9kdWxlIHNwZWMgZnJvbSBj"
    "bGlwYm9hcmQgb3IgdHlwZWQgdGV4dC4iIiIKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRv"
    "d1RpdGxlKCJJbXBvcnQgTW9kdWxlIFNwZWMiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcy"
    "fTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAsIDM0MCkKICAgICAgICBsYXlvdXQgPSBRVkJveExh"
    "eW91dChkbGcpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChRTGFiZWwoCiAgICAgICAgICAgICJQYXN0ZSBhIG1vZHVsZSBzcGVj"
    "IGJlbG93LlxuIgogICAgICAgICAgICAiRmlyc3QgbGluZSB3aWxsIGJlIHVzZWQgYXMgdGhlIG1vZHVsZSBuYW1lLiIKICAgICAg"
    "ICApKQogICAgICAgIHRleHRfZmllbGQgPSBRVGV4dEVkaXQoKQogICAgICAgIHRleHRfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0"
    "KCJQYXN0ZSBtb2R1bGUgc3BlYyBoZXJlLi4uIikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHRleHRfZmllbGQsIDEpCiAgICAg"
    "ICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fb2sgICAgID0gX2dvdGhpY19idG4oIkltcG9ydCIpCiAgICAg"
    "ICAgYnRuX2NhbmNlbCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIGJ0bl9vay5jbGlja2VkLmNvbm5lY3QoZGxnLmFj"
    "Y2VwdCkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lk"
    "Z2V0KGJ0bl9vaykKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2FuY2VsKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQo"
    "YnRuX3JvdykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAg"
    "IHJhdyA9IHRleHRfZmllbGQudG9QbGFpblRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIG5vdCByYXc6CiAgICAgICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICAgICAgbGluZXMgPSByYXcuc3BsaXRsaW5lcygpCiAgICAgICAgICAgICMgRmlyc3Qgbm9uLWVt"
    "cHR5IGxpbmUgPSBuYW1lCiAgICAgICAgICAgIG5hbWUgPSAiIgogICAgICAgICAgICBmb3IgbGluZSBpbiBsaW5lczoKICAgICAg"
    "ICAgICAgICAgIGlmIGxpbmUuc3RyaXAoKToKICAgICAgICAgICAgICAgICAgICBuYW1lID0gbGluZS5zdHJpcCgpCiAgICAgICAg"
    "ICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgbmV3X3JlYyA9IHsKICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHN0"
    "cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAgICAgIm5hbWUiOiAgICAgICAgbmFtZVs6NjBdLAogICAgICAgICAgICAgICAg"
    "InN0YXR1cyI6ICAgICAgIklkZWEiLAogICAgICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogIiIsCiAgICAgICAgICAgICAgICAi"
    "bm90ZXMiOiAgICAgICByYXcsCiAgICAgICAgICAgICAgICAiY3JlYXRlZCI6ICAgICBkYXRldGltZS5ub3coKS5pc29mb3JtYXQo"
    "KSwKICAgICAgICAgICAgICAgICJtb2RpZmllZCI6ICAgIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICB9"
    "CiAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKG5ld19yZWMpCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3Bh"
    "dGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgoKIyDilIDilIAgUEFTUyA1IENPTVBMRVRFIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEFsbCB0YWIgY29udGVudCBjbGFzc2VzIGRlZmluZWQuCiMgU0xTY2Fuc1Rh"
    "YjogcmVidWlsdCDigJQgRGVsZXRlIGFkZGVkLCBNb2RpZnkgZml4ZWQsIHRpbWVzdGFtcCBwYXJzZXIgZml4ZWQsCiMgICAgICAg"
    "ICAgICAgY2FyZC9ncmltb2lyZSBzdHlsZSwgY29weS10by1jbGlwYm9hcmQgY29udGV4dCBtZW51LgojIFNMQ29tbWFuZHNUYWI6"
    "IGdvdGhpYyB0YWJsZSwg4qeJIENvcHkgQ29tbWFuZCBidXR0b24uCiMgSm9iVHJhY2tlclRhYjogZnVsbCByZWJ1aWxkIOKAlCBt"
    "dWx0aS1zZWxlY3QsIGFyY2hpdmUvcmVzdG9yZSwgQ1NWL1RTViBleHBvcnQuCiMgU2VsZlRhYjogaW5uZXIgc2FuY3R1bSBmb3Ig"
    "aWRsZSBuYXJyYXRpdmUgYW5kIHJlZmxlY3Rpb24gb3V0cHV0LgojIERpYWdub3N0aWNzVGFiOiBzdHJ1Y3R1cmVkIGxvZyB3aXRo"
    "IGxldmVsLWNvbG9yZWQgb3V0cHV0LgojIExlc3NvbnNUYWI6IExTTCBGb3JiaWRkZW4gUnVsZXNldCBicm93c2VyIHdpdGggYWRk"
    "L2RlbGV0ZS9zZWFyY2guCiMKIyBOZXh0OiBQYXNzIDYg4oCUIE1haW4gV2luZG93CiMgKE1vcmdhbm5hRGVjayBjbGFzcywgZnVs"
    "bCBsYXlvdXQsIEFQU2NoZWR1bGVyLCBmaXJzdC1ydW4gZmxvdywKIyAgZGVwZW5kZW5jeSBib290c3RyYXAsIHNob3J0Y3V0IGNy"
    "ZWF0aW9uLCBzdGFydHVwIHNlcXVlbmNlKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyA2OiBNQUlO"
    "IFdJTkRPVyAmIEVOVFJZIFBPSU5UCiMKIyBDb250YWluczoKIyAgIGJvb3RzdHJhcF9jaGVjaygpICAgICDigJQgZGVwZW5kZW5j"
    "eSB2YWxpZGF0aW9uICsgYXV0by1pbnN0YWxsIGJlZm9yZSBVSQojICAgRmlyc3RSdW5EaWFsb2cgICAgICAgIOKAlCBtb2RlbCBw"
    "YXRoICsgY29ubmVjdGlvbiB0eXBlIHNlbGVjdGlvbgojICAgSm91cm5hbFNpZGViYXIgICAgICAgIOKAlCBjb2xsYXBzaWJsZSBs"
    "ZWZ0IHNpZGViYXIgKHNlc3Npb24gYnJvd3NlciArIGpvdXJuYWwpCiMgICBUb3Jwb3JQYW5lbCAgICAgICAgICAg4oCUIEFXQUtF"
    "IC8gQVVUTyAvIFNVU1BFTkQgc3RhdGUgdG9nZ2xlCiMgICBNb3JnYW5uYURlY2sgICAgICAgICAg4oCUIG1haW4gd2luZG93LCBm"
    "dWxsIGxheW91dCwgYWxsIHNpZ25hbCBjb25uZWN0aW9ucwojICAgbWFpbigpICAgICAgICAgICAgICAgIOKAlCBlbnRyeSBwb2lu"
    "dCB3aXRoIGJvb3RzdHJhcCBzZXF1ZW5jZQojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0IHN1YnByb2Nlc3MKCgojIOKUgOKUgCBQUkUt"
    "TEFVTkNIIERFUEVOREVOQ1kgQk9PVFNUUkFQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgApkZWYgYm9vdHN0cmFwX2NoZWNrKCkgLT4gTm9uZToKICAgICIiIgogICAgUnVucyBCRUZPUkUgUUFwcGxpY2F0aW9uIGlz"
    "IGNyZWF0ZWQuCiAgICBDaGVja3MgZm9yIFB5U2lkZTYgc2VwYXJhdGVseSAoY2FuJ3Qgc2hvdyBHVUkgd2l0aG91dCBpdCkuCiAg"
    "ICBBdXRvLWluc3RhbGxzIGFsbCBvdGhlciBtaXNzaW5nIG5vbi1jcml0aWNhbCBkZXBzIHZpYSBwaXAuCiAgICBWYWxpZGF0ZXMg"
    "aW5zdGFsbHMgc3VjY2VlZGVkLgogICAgV3JpdGVzIHJlc3VsdHMgdG8gYSBib290c3RyYXAgbG9nIGZvciBEaWFnbm9zdGljcyB0"
    "YWIgdG8gcGljayB1cC4KICAgICIiIgogICAgIyDilIDilIAgU3RlcCAxOiBDaGVjayBQeVNpZGU2IChjYW4ndCBhdXRvLWluc3Rh"
    "bGwgd2l0aG91dCBpdCBhbHJlYWR5IHByZXNlbnQpIOKUgAogICAgdHJ5OgogICAgICAgIGltcG9ydCBQeVNpZGU2ICAjIG5vcWEK"
    "ICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAjIE5vIEdVSSBhdmFpbGFibGUg4oCUIHVzZSBXaW5kb3dzIG5hdGl2ZSBk"
    "aWFsb2cgdmlhIGN0eXBlcwogICAgICAgIHRyeToKICAgICAgICAgICAgaW1wb3J0IGN0eXBlcwogICAgICAgICAgICBjdHlwZXMu"
    "d2luZGxsLnVzZXIzMi5NZXNzYWdlQm94VygKICAgICAgICAgICAgICAgIDAsCiAgICAgICAgICAgICAgICAiUHlTaWRlNiBpcyBy"
    "ZXF1aXJlZCBidXQgbm90IGluc3RhbGxlZC5cblxuIgogICAgICAgICAgICAgICAgIk9wZW4gYSB0ZXJtaW5hbCBhbmQgcnVuOlxu"
    "XG4iCiAgICAgICAgICAgICAgICAiICAgIHBpcCBpbnN0YWxsIFB5U2lkZTZcblxuIgogICAgICAgICAgICAgICAgZiJUaGVuIHJl"
    "c3RhcnQge0RFQ0tfTkFNRX0uIiwKICAgICAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0g4oCUIE1pc3NpbmcgRGVwZW5kZW5jeSIs"
    "CiAgICAgICAgICAgICAgICAweDEwICAjIE1CX0lDT05FUlJPUgogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlv"
    "bjoKICAgICAgICAgICAgcHJpbnQoIkNSSVRJQ0FMOiBQeVNpZGU2IG5vdCBpbnN0YWxsZWQuIFJ1bjogcGlwIGluc3RhbGwgUHlT"
    "aWRlNiIpCiAgICAgICAgc3lzLmV4aXQoMSkKCiAgICAjIOKUgOKUgCBTdGVwIDI6IEF1dG8taW5zdGFsbCBvdGhlciBtaXNzaW5n"
    "IGRlcHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBfQVVUT19JTlNUQUxMID0gWwogICAgICAgICgiYXBzY2hlZHVsZXIiLCAg"
    "ICAgICAgICAgICAgICJhcHNjaGVkdWxlciIpLAogICAgICAgICgibG9ndXJ1IiwgICAgICAgICAgICAgICAgICAgICJsb2d1cnUi"
    "KSwKICAgICAgICAoInB5Z2FtZSIsICAgICAgICAgICAgICAgICAgICAicHlnYW1lIiksCiAgICAgICAgKCJweXdpbjMyIiwgICAg"
    "ICAgICAgICAgICAgICAgInB5d2luMzIiKSwKICAgICAgICAoInBzdXRpbCIsICAgICAgICAgICAgICAgICAgICAicHN1dGlsIiks"
    "CiAgICAgICAgKCJyZXF1ZXN0cyIsICAgICAgICAgICAgICAgICAgInJlcXVlc3RzIiksCiAgICAgICAgKCJnb29nbGUtYXBpLXB5"
    "dGhvbi1jbGllbnQiLCAgImdvb2dsZWFwaWNsaWVudCIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgtb2F1dGhsaWIiLCAgICAgICJn"
    "b29nbGVfYXV0aF9vYXV0aGxpYiIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgiLCAgICAgICAgICAgICAgICJnb29nbGUuYXV0aCIp"
    "LAogICAgXQoKICAgIGltcG9ydCBpbXBvcnRsaWIKICAgIGJvb3RzdHJhcF9sb2cgPSBbXQoKICAgIGZvciBwaXBfbmFtZSwgaW1w"
    "b3J0X25hbWUgaW4gX0FVVE9fSU5TVEFMTDoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxl"
    "KGltcG9ydF9uYW1lKQogICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZChmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0g4pyT"
    "IikKICAgICAgICBleGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAg"
    "ICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IG1pc3Npbmcg4oCUIGluc3RhbGxpbmcuLi4iCiAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgcmVzdWx0ID0gc3VicHJvY2Vzcy5ydW4oCiAgICAgICAgICAgICAgICAgICAg"
    "W3N5cy5leGVjdXRhYmxlLCAiLW0iLCAicGlwIiwgImluc3RhbGwiLAogICAgICAgICAgICAgICAgICAgICBwaXBfbmFtZSwgIi0t"
    "cXVpZXQiLCAiLS1uby13YXJuLXNjcmlwdC1sb2NhdGlvbiJdLAogICAgICAgICAgICAgICAgICAgIGNhcHR1cmVfb3V0cHV0PVRy"
    "dWUsIHRleHQ9VHJ1ZSwgdGltZW91dD0xMjAKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIHJlc3VsdC5yZXR1"
    "cm5jb2RlID09IDA6CiAgICAgICAgICAgICAgICAgICAgIyBWYWxpZGF0ZSBpdCBhY3R1YWxseSBpbXBvcnRlZCBub3cKICAgICAg"
    "ICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9ydF9u"
    "YW1lKQogICAgICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsZWQg4pyTIgogICAgICAgICAgICAgICAgICAgICAgICApCiAgICAg"
    "ICAgICAgICAgICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFw"
    "cGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsIGFwcGVhcmVk"
    "IHRvICIKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYic3VjY2VlZCBidXQgaW1wb3J0IHN0aWxsIGZhaWxzIOKAlCByZXN0"
    "YXJ0IG1heSAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmImJlIHJlcXVpcmVkLiIKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3RhbGwgZmFpbGVkOiAiCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGYie3Jlc3VsdC5zdGRlcnJbOjIwMF19IgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0"
    "IHN1YnByb2Nlc3MuVGltZW91dEV4cGlyZWQ6CiAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAg"
    "ICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbCB0aW1lZCBvdXQuIgogICAgICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAg"
    "ICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbCBlcnJvcjoge2V9IgogICAgICAgICAgICAg"
    "ICAgKQoKICAgICMg4pSA4pSAIFN0ZXAgMzogV3JpdGUgYm9vdHN0cmFwIGxvZyBmb3IgRGlhZ25vc3RpY3MgdGFiIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgdHJ5OgogICAg"
    "ICAgIGxvZ19wYXRoID0gU0NSSVBUX0RJUiAvICJsb2dzIiAvICJib290c3RyYXBfbG9nLnR4dCIKICAgICAgICB3aXRoIGxvZ19w"
    "YXRoLm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICBmLndyaXRlKCJcbiIuam9pbihib290c3Ry"
    "YXBfbG9nKSkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcGFzcwoKCiMg4pSA4pSAIEZJUlNUIFJVTiBESUFMT0cg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEZpcnN0UnVuRGlhbG9nKFFEaWFsb2cpOgogICAgIiIiCiAgICBTaG93biBvbiBm"
    "aXJzdCBsYXVuY2ggd2hlbiBjb25maWcuanNvbiBkb2Vzbid0IGV4aXN0LgogICAgQ29sbGVjdHMgbW9kZWwgY29ubmVjdGlvbiB0"
    "eXBlIGFuZCBwYXRoL2tleS4KICAgIFZhbGlkYXRlcyBjb25uZWN0aW9uIGJlZm9yZSBhY2NlcHRpbmcuCiAgICBXcml0ZXMgY29u"
    "ZmlnLmpzb24gb24gc3VjY2Vzcy4KICAgIENyZWF0ZXMgZGVza3RvcCBzaG9ydGN1dC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRf"
    "XyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5zZXRXaW5k"
    "b3dUaXRsZShmIuKcpiB7REVDS19OQU1FLnVwcGVyKCl9IOKAlCBGSVJTVCBBV0FLRU5JTkciKQogICAgICAgIHNlbGYuc2V0U3R5"
    "bGVTaGVldChTVFlMRSkKICAgICAgICBzZWxmLnNldEZpeGVkU2l6ZSg1MjAsIDQwMCkKICAgICAgICBzZWxmLl9zZXR1cF91aSgp"
    "CgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAg"
    "IHJvb3Quc2V0U3BhY2luZygxMCkKCiAgICAgICAgdGl0bGUgPSBRTGFiZWwoZiLinKYge0RFQ0tfTkFNRS51cHBlcigpfSDigJQg"
    "RklSU1QgQVdBS0VOSU5HIOKcpiIpCiAgICAgICAgdGl0bGUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0Nf"
    "Q1JJTVNPTn07IGZvbnQtc2l6ZTogMTRweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseTog"
    "e0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2luZzogMnB4OyIKICAgICAgICApCiAgICAgICAgdGl0bGUuc2V0QWxpZ25t"
    "ZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQodGl0bGUpCgogICAgICAgIHN1"
    "YiA9IFFMYWJlbCgKICAgICAgICAgICAgZiJDb25maWd1cmUgdGhlIHZlc3NlbCBiZWZvcmUge0RFQ0tfTkFNRX0gbWF5IGF3YWtl"
    "bi5cbiIKICAgICAgICAgICAgIkFsbCBzZXR0aW5ncyBhcmUgc3RvcmVkIGxvY2FsbHkuIE5vdGhpbmcgbGVhdmVzIHRoaXMgbWFj"
    "aGluZS4iCiAgICAgICAgKQogICAgICAgIHN1Yi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJ"
    "TX07IGZvbnQtc2l6ZTogMTBweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAg"
    "ICAgICkKICAgICAgICBzdWIuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgcm9vdC5h"
    "ZGRXaWRnZXQoc3ViKQoKICAgICAgICAjIOKUgOKUgCBDb25uZWN0aW9uIHR5cGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgQUkg"
    "Q09OTkVDVElPTiBUWVBFIikpCiAgICAgICAgc2VsZi5fdHlwZV9jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc2VsZi5fdHlw"
    "ZV9jb21iby5hZGRJdGVtcyhbCiAgICAgICAgICAgICJMb2NhbCBtb2RlbCBmb2xkZXIgKHRyYW5zZm9ybWVycykiLAogICAgICAg"
    "ICAgICAiT2xsYW1hIChsb2NhbCBzZXJ2aWNlKSIsCiAgICAgICAgICAgICJDbGF1ZGUgQVBJIChBbnRocm9waWMpIiwKICAgICAg"
    "ICAgICAgIk9wZW5BSSBBUEkiLAogICAgICAgIF0pCiAgICAgICAgc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXhDaGFuZ2Vk"
    "LmNvbm5lY3Qoc2VsZi5fb25fdHlwZV9jaGFuZ2UpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdHlwZV9jb21ibykKCiAg"
    "ICAgICAgIyDilIDilIAgRHluYW1pYyBjb25uZWN0aW9uIGZpZWxkcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICBzZWxmLl9zdGFjayA9IFFTdGFja2VkV2lkZ2V0KCkKCiAgICAgICAgIyBQYWdlIDA6IExvY2FsIHBhdGgKICAgICAgICBwMCA9"
    "IFFXaWRnZXQoKQogICAgICAgIGwwID0gUUhCb3hMYXlvdXQocDApCiAgICAgICAgbDAuc2V0Q29udGVudHNNYXJnaW5zKDAsMCww"
    "LDApCiAgICAgICAgc2VsZi5fbG9jYWxfcGF0aCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fbG9jYWxfcGF0aC5zZXRQbGFj"
    "ZWhvbGRlclRleHQoCiAgICAgICAgICAgIHIiRDpcQUlcTW9kZWxzXGRvbHBoaW4tOGIiCiAgICAgICAgKQogICAgICAgIGJ0bl9i"
    "cm93c2UgPSBfZ290aGljX2J0bigiQnJvd3NlIikKICAgICAgICBidG5fYnJvd3NlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9icm93"
    "c2VfbW9kZWwpCiAgICAgICAgbDAuYWRkV2lkZ2V0KHNlbGYuX2xvY2FsX3BhdGgpOyBsMC5hZGRXaWRnZXQoYnRuX2Jyb3dzZSkK"
    "ICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDApCgogICAgICAgICMgUGFnZSAxOiBPbGxhbWEgbW9kZWwgbmFtZQogICAg"
    "ICAgIHAxID0gUVdpZGdldCgpCiAgICAgICAgbDEgPSBRSEJveExheW91dChwMSkKICAgICAgICBsMS5zZXRDb250ZW50c01hcmdp"
    "bnMoMCwwLDAsMCkKICAgICAgICBzZWxmLl9vbGxhbWFfbW9kZWwgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX29sbGFtYV9t"
    "b2RlbC5zZXRQbGFjZWhvbGRlclRleHQoImRvbHBoaW4tMi42LTdiIikKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fb2xsYW1h"
    "X21vZGVsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMSkKCiAgICAgICAgIyBQYWdlIDI6IENsYXVkZSBBUEkga2V5"
    "CiAgICAgICAgcDIgPSBRV2lkZ2V0KCkKICAgICAgICBsMiA9IFFWQm94TGF5b3V0KHAyKQogICAgICAgIGwyLnNldENvbnRlbnRz"
    "TWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkgICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fY2xh"
    "dWRlX2tleS5zZXRQbGFjZWhvbGRlclRleHQoInNrLWFudC0uLi4iKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkuc2V0RWNob01v"
    "ZGUoUUxpbmVFZGl0LkVjaG9Nb2RlLlBhc3N3b3JkKQogICAgICAgIHNlbGYuX2NsYXVkZV9tb2RlbCA9IFFMaW5lRWRpdCgiY2xh"
    "dWRlLXNvbm5ldC00LTYiKQogICAgICAgIGwyLmFkZFdpZGdldChRTGFiZWwoIkFQSSBLZXk6IikpCiAgICAgICAgbDIuYWRkV2lk"
    "Z2V0KHNlbGYuX2NsYXVkZV9rZXkpCiAgICAgICAgbDIuYWRkV2lkZ2V0KFFMYWJlbCgiTW9kZWw6IikpCiAgICAgICAgbDIuYWRk"
    "V2lkZ2V0KHNlbGYuX2NsYXVkZV9tb2RlbCkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDIpCgogICAgICAgICMgUGFn"
    "ZSAzOiBPcGVuQUkKICAgICAgICBwMyA9IFFXaWRnZXQoKQogICAgICAgIGwzID0gUVZCb3hMYXlvdXQocDMpCiAgICAgICAgbDMu"
    "c2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fb2FpX2tleSAgID0gUUxpbmVFZGl0KCkKICAgICAgICBz"
    "ZWxmLl9vYWlfa2V5LnNldFBsYWNlaG9sZGVyVGV4dCgic2stLi4uIikKICAgICAgICBzZWxmLl9vYWlfa2V5LnNldEVjaG9Nb2Rl"
    "KFFMaW5lRWRpdC5FY2hvTW9kZS5QYXNzd29yZCkKICAgICAgICBzZWxmLl9vYWlfbW9kZWwgPSBRTGluZUVkaXQoImdwdC00byIp"
    "CiAgICAgICAgbDMuYWRkV2lkZ2V0KFFMYWJlbCgiQVBJIEtleToiKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fb2FpX2tl"
    "eSkKICAgICAgICBsMy5hZGRXaWRnZXQoUUxhYmVsKCJNb2RlbDoiKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fb2FpX21v"
    "ZGVsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMykKCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fc3RhY2sp"
    "CgogICAgICAgICMg4pSA4pSAIFRlc3QgKyBzdGF0dXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgdGVzdF9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX3Rl"
    "c3QgPSBfZ290aGljX2J0bigiVGVzdCBDb25uZWN0aW9uIikKICAgICAgICBzZWxmLl9idG5fdGVzdC5jbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5fdGVzdF9jb25uZWN0aW9uKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5f"
    "c3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBw"
    "eDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICB0ZXN0"
    "X3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX3Rlc3QpCiAgICAgICAgdGVzdF9yb3cuYWRkV2lkZ2V0KHNlbGYuX3N0YXR1c19sYmws"
    "IDEpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQodGVzdF9yb3cpCgogICAgICAgICMg4pSA4pSAIEZhY2UgUGFjayDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBy"
    "b290LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBGQUNFIFBBQ0sgKG9wdGlvbmFsIOKAlCBaSVAgZmlsZSkiKSkKICAgICAg"
    "ICBmYWNlX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9mYWNlX3BhdGggPSBRTGluZUVkaXQoKQogICAgICAgIHNl"
    "bGYuX2ZhY2VfcGF0aC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgIGYiQnJvd3NlIHRvIHtERUNLX05BTUV9IGZhY2Ug"
    "cGFjayBaSVAgKG9wdGlvbmFsLCBjYW4gYWRkIGxhdGVyKSIKICAgICAgICApCiAgICAgICAgc2VsZi5fZmFjZV9wYXRoLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAg"
    "ICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICBmImZv"
    "bnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTJweDsgcGFkZGluZzogNnB4IDEwcHg7IgogICAgICAg"
    "ICkKICAgICAgICBidG5fZmFjZSA9IF9nb3RoaWNfYnRuKCJCcm93c2UiKQogICAgICAgIGJ0bl9mYWNlLmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl9icm93c2VfZmFjZSkKICAgICAgICBmYWNlX3Jvdy5hZGRXaWRnZXQoc2VsZi5fZmFjZV9wYXRoKQogICAgICAgIGZh"
    "Y2Vfcm93LmFkZFdpZGdldChidG5fZmFjZSkKICAgICAgICByb290LmFkZExheW91dChmYWNlX3JvdykKCiAgICAgICAgIyDilIDi"
    "lIAgU2hvcnRjdXQgb3B0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgICAgIHNlbGYuX3Nob3J0Y3V0X2NiID0gUUNoZWNrQm94KAogICAgICAgICAgICAiQ3JlYXRlIGRlc2t0b3Agc2hvcnRj"
    "dXQgKHJlY29tbWVuZGVkKSIKICAgICAgICApCiAgICAgICAgc2VsZi5fc2hvcnRjdXRfY2Iuc2V0Q2hlY2tlZChUcnVlKQogICAg"
    "ICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3Nob3J0Y3V0X2NiKQoKICAgICAgICAjIOKUgOKUgCBCdXR0b25zIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ICAgIHJvb3QuYWRkU3RyZXRjaCgpCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYXdh"
    "a2VuID0gX2dvdGhpY19idG4oIuKcpiBCRUdJTiBBV0FLRU5JTkciKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uc2V0RW5hYmxl"
    "ZChGYWxzZSkKICAgICAgICBidG5fY2FuY2VsID0gX2dvdGhpY19idG4oIuKclyBDYW5jZWwiKQogICAgICAgIHNlbGYuX2J0bl9h"
    "d2FrZW4uY2xpY2tlZC5jb25uZWN0KHNlbGYuYWNjZXB0KQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "cmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9hd2FrZW4pCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRn"
    "ZXQoYnRuX2NhbmNlbCkKICAgICAgICByb290LmFkZExheW91dChidG5fcm93KQoKICAgIGRlZiBfb25fdHlwZV9jaGFuZ2Uoc2Vs"
    "ZiwgaWR4OiBpbnQpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KGlkeCkKICAgICAgICBzZWxm"
    "Ll9idG5fYXdha2VuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRUZXh0KCIiKQoKICAgIGRl"
    "ZiBfYnJvd3NlX21vZGVsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCA9IFFGaWxlRGlhbG9nLmdldEV4aXN0aW5nRGlyZWN0"
    "b3J5KAogICAgICAgICAgICBzZWxmLCAiU2VsZWN0IE1vZGVsIEZvbGRlciIsCiAgICAgICAgICAgIHIiRDpcQUlcTW9kZWxzIgog"
    "ICAgICAgICkKICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICBzZWxmLl9sb2NhbF9wYXRoLnNldFRleHQocGF0aCkKCiAgICBk"
    "ZWYgX2Jyb3dzZV9mYWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCwgXyA9IFFGaWxlRGlhbG9nLmdldE9wZW5GaWxlTmFt"
    "ZSgKICAgICAgICAgICAgc2VsZiwgIlNlbGVjdCBGYWNlIFBhY2sgWklQIiwKICAgICAgICAgICAgc3RyKFBhdGguaG9tZSgpIC8g"
    "IkRlc2t0b3AiKSwKICAgICAgICAgICAgIlpJUCBGaWxlcyAoKi56aXApIgogICAgICAgICkKICAgICAgICBpZiBwYXRoOgogICAg"
    "ICAgICAgICBzZWxmLl9mYWNlX3BhdGguc2V0VGV4dChwYXRoKQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGZhY2VfemlwX3BhdGgo"
    "c2VsZikgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9mYWNlX3BhdGgudGV4dCgpLnN0cmlwKCkKCiAgICBkZWYgX3Rlc3Rf"
    "Y29ubmVjdGlvbihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0VGV4dCgiVGVzdGluZy4uLiIpCiAg"
    "ICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZv"
    "bnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIFFBcHBsaWNh"
    "dGlvbi5wcm9jZXNzRXZlbnRzKCkKCiAgICAgICAgaWR4ID0gc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXgoKQogICAgICAg"
    "IG9rICA9IEZhbHNlCiAgICAgICAgbXNnID0gIiIKCiAgICAgICAgaWYgaWR4ID09IDA6ICAjIExvY2FsCiAgICAgICAgICAgIHBh"
    "dGggPSBzZWxmLl9sb2NhbF9wYXRoLnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIHBhdGggYW5kIFBhdGgocGF0aCkuZXhp"
    "c3RzKCk6CiAgICAgICAgICAgICAgICBvayAgPSBUcnVlCiAgICAgICAgICAgICAgICBtc2cgPSBmIkZvbGRlciBmb3VuZC4gTW9k"
    "ZWwgd2lsbCBsb2FkIG9uIHN0YXJ0dXAuIgogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgbXNnID0gIkZvbGRlciBu"
    "b3QgZm91bmQuIENoZWNrIHRoZSBwYXRoLiIKCiAgICAgICAgZWxpZiBpZHggPT0gMTogICMgT2xsYW1hCiAgICAgICAgICAgIHRy"
    "eToKICAgICAgICAgICAgICAgIHJlcSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KAogICAgICAgICAgICAgICAgICAgICJodHRw"
    "Oi8vbG9jYWxob3N0OjExNDM0L2FwaS90YWdzIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgcmVzcCA9IHVybGxp"
    "Yi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTMpCiAgICAgICAgICAgICAgICBvayAgID0gcmVzcC5zdGF0dXMgPT0gMjAw"
    "CiAgICAgICAgICAgICAgICBtc2cgID0gIk9sbGFtYSBpcyBydW5uaW5nIOKckyIgaWYgb2sgZWxzZSAiT2xsYW1hIG5vdCByZXNw"
    "b25kaW5nLiIKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgbXNnID0gZiJPbGxhbWEg"
    "bm90IHJlYWNoYWJsZToge2V9IgoKICAgICAgICBlbGlmIGlkeCA9PSAyOiAgIyBDbGF1ZGUKICAgICAgICAgICAga2V5ID0gc2Vs"
    "Zi5fY2xhdWRlX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBvayAgPSBib29sKGtleSBhbmQga2V5LnN0YXJ0c3dpdGgo"
    "InNrLWFudCIpKQogICAgICAgICAgICBtc2cgPSAiQVBJIGtleSBmb3JtYXQgbG9va3MgY29ycmVjdC4iIGlmIG9rIGVsc2UgIkVu"
    "dGVyIGEgdmFsaWQgQ2xhdWRlIEFQSSBrZXkuIgoKICAgICAgICBlbGlmIGlkeCA9PSAzOiAgIyBPcGVuQUkKICAgICAgICAgICAg"
    "a2V5ID0gc2VsZi5fb2FpX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBvayAgPSBib29sKGtleSBhbmQga2V5LnN0YXJ0"
    "c3dpdGgoInNrLSIpKQogICAgICAgICAgICBtc2cgPSAiQVBJIGtleSBmb3JtYXQgbG9va3MgY29ycmVjdC4iIGlmIG9rIGVsc2Ug"
    "IkVudGVyIGEgdmFsaWQgT3BlbkFJIEFQSSBrZXkuIgoKICAgICAgICBjb2xvciA9IENfR1JFRU4gaWYgb2sgZWxzZSBDX0NSSU1T"
    "T04KICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFRleHQobXNnKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9O"
    "VH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbi5zZXRFbmFibGVkKG9rKQoKICAgIGRlZiBidWls"
    "ZF9jb25maWcoc2VsZikgLT4gZGljdDoKICAgICAgICAiIiJCdWlsZCBhbmQgcmV0dXJuIHVwZGF0ZWQgY29uZmlnIGRpY3QgZnJv"
    "bSBkaWFsb2cgc2VsZWN0aW9ucy4iIiIKICAgICAgICBjZmcgICAgID0gX2RlZmF1bHRfY29uZmlnKCkKICAgICAgICBpZHggICAg"
    "ID0gc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXgoKQogICAgICAgIHR5cGVzICAgPSBbImxvY2FsIiwgIm9sbGFtYSIsICJj"
    "bGF1ZGUiLCAib3BlbmFpIl0KICAgICAgICBjZmdbIm1vZGVsIl1bInR5cGUiXSA9IHR5cGVzW2lkeF0KCiAgICAgICAgaWYgaWR4"
    "ID09IDA6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsicGF0aCJdID0gc2VsZi5fbG9jYWxfcGF0aC50ZXh0KCkuc3RyaXAoKQog"
    "ICAgICAgIGVsaWYgaWR4ID09IDE6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsib2xsYW1hX21vZGVsIl0gPSBzZWxmLl9vbGxh"
    "bWFfbW9kZWwudGV4dCgpLnN0cmlwKCkgb3IgImRvbHBoaW4tMi42LTdiIgogICAgICAgIGVsaWYgaWR4ID09IDI6CiAgICAgICAg"
    "ICAgIGNmZ1sibW9kZWwiXVsiYXBpX2tleSJdICAgPSBzZWxmLl9jbGF1ZGVfa2V5LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAg"
    "IGNmZ1sibW9kZWwiXVsiYXBpX21vZGVsIl0gPSBzZWxmLl9jbGF1ZGVfbW9kZWwudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAg"
    "Y2ZnWyJtb2RlbCJdWyJhcGlfdHlwZSJdICA9ICJjbGF1ZGUiCiAgICAgICAgZWxpZiBpZHggPT0gMzoKICAgICAgICAgICAgY2Zn"
    "WyJtb2RlbCJdWyJhcGlfa2V5Il0gICA9IHNlbGYuX29haV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2Rl"
    "bCJdWyJhcGlfbW9kZWwiXSA9IHNlbGYuX29haV9tb2RlbC50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdbIm1vZGVsIl1b"
    "ImFwaV90eXBlIl0gID0gIm9wZW5haSIKCiAgICAgICAgY2ZnWyJmaXJzdF9ydW4iXSA9IEZhbHNlCiAgICAgICAgcmV0dXJuIGNm"
    "ZwoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGNyZWF0ZV9zaG9ydGN1dChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBzZWxm"
    "Ll9zaG9ydGN1dF9jYi5pc0NoZWNrZWQoKQoKCiMg4pSA4pSAIEpPVVJOQUwgU0lERUJBUiDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKY2xhc3MgSm91cm5hbFNpZGViYXIoUVdpZGdldCk6CiAgICAiIiIKICAgIENvbGxhcHNpYmxlIGxlZnQgc2lkZWJhciBu"
    "ZXh0IHRvIHRoZSBwZXJzb25hIGNoYXQgdGFiLgogICAgVG9wOiBzZXNzaW9uIGNvbnRyb2xzIChjdXJyZW50IHNlc3Npb24gbmFt"
    "ZSwgc2F2ZS9sb2FkIGJ1dHRvbnMsCiAgICAgICAgIGF1dG9zYXZlIGluZGljYXRvcikuCiAgICBCb2R5OiBzY3JvbGxhYmxlIHNl"
    "c3Npb24gbGlzdCDigJQgZGF0ZSwgQUkgbmFtZSwgbWVzc2FnZSBjb3VudC4KICAgIENvbGxhcHNlcyBsZWZ0d2FyZCB0byBhIHRo"
    "aW4gc3RyaXAuCgogICAgU2lnbmFsczoKICAgICAgICBzZXNzaW9uX2xvYWRfcmVxdWVzdGVkKHN0cikgICDigJQgZGF0ZSBzdHJp"
    "bmcgb2Ygc2Vzc2lvbiB0byBsb2FkCiAgICAgICAgc2Vzc2lvbl9jbGVhcl9yZXF1ZXN0ZWQoKSAgICAg4oCUIHJldHVybiB0byBj"
    "dXJyZW50IHNlc3Npb24KICAgICIiIgoKICAgIHNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQgID0gU2lnbmFsKHN0cikKICAgIHNlc3Np"
    "b25fY2xlYXJfcmVxdWVzdGVkID0gU2lnbmFsKCkKCiAgICBkZWYgX19pbml0X18oc2VsZiwgc2Vzc2lvbl9tZ3I6ICJTZXNzaW9u"
    "TWFuYWdlciIsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9zZXNz"
    "aW9uX21nciA9IHNlc3Npb25fbWdyCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgICAgPSBUcnVlCiAgICAgICAgc2VsZi5fc2V0dXBf"
    "dWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgICMgVXNl"
    "IGEgaG9yaXpvbnRhbCByb290IGxheW91dCDigJQgY29udGVudCBvbiBsZWZ0LCB0b2dnbGUgc3RyaXAgb24gcmlnaHQKICAgICAg"
    "ICByb290ID0gUUhCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAg"
    "ICAgIHJvb3Quc2V0U3BhY2luZygwKQoKICAgICAgICAjIOKUgOKUgCBDb2xsYXBzZSB0b2dnbGUgc3RyaXAg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fdG9nZ2xlX3N0cmlwID0gUVdpZGdldCgpCiAgICAgICAg"
    "c2VsZi5fdG9nZ2xlX3N0cmlwLnNldEZpeGVkV2lkdGgoMjApCiAgICAgICAgc2VsZi5fdG9nZ2xlX3N0cmlwLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyLXJpZ2h0OiAxcHggc29saWQge0NfQ1JJTVNPTl9E"
    "SU19OyIKICAgICAgICApCiAgICAgICAgdHNfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fdG9nZ2xlX3N0cmlwKQogICAgICAg"
    "IHRzX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgOCwgMCwgOCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuID0gUVRvb2xC"
    "dXR0b24oKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0Rml4ZWRTaXplKDE4LCAxOCkKICAgICAgICBzZWxmLl90b2dnbGVf"
    "YnRuLnNldFRleHQoIuKXgCIpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJh"
    "Y2tncm91bmQ6IHRyYW5zcGFyZW50OyBjb2xvcjoge0NfR09MRF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiBub25lOyBm"
    "b250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90"
    "b2dnbGUpCiAgICAgICAgdHNfbGF5b3V0LmFkZFdpZGdldChzZWxmLl90b2dnbGVfYnRuKQogICAgICAgIHRzX2xheW91dC5hZGRT"
    "dHJldGNoKCkKCiAgICAgICAgIyDilIDilIAgTWFpbiBjb250ZW50IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2NvbnRlbnQgPSBRV2lkZ2V0KCkKICAgICAgICBz"
    "ZWxmLl9jb250ZW50LnNldE1pbmltdW1XaWR0aCgxODApCiAgICAgICAgc2VsZi5fY29udGVudC5zZXRNYXhpbXVtV2lkdGgoMjIw"
    "KQogICAgICAgIGNvbnRlbnRfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fY29udGVudCkKICAgICAgICBjb250ZW50X2xheW91"
    "dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBjb250ZW50X2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAg"
    "ICAgICMgU2VjdGlvbiBsYWJlbAogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBKT1VS"
    "TkFMIikpCgogICAgICAgICMgQ3VycmVudCBzZXNzaW9uIGluZm8KICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUgPSBRTGFiZWwo"
    "Ik5ldyBTZXNzaW9uIikKICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xv"
    "cjoge0NfR09MRH07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgIgogICAgICAgICAg"
    "ICBmImZvbnQtc3R5bGU6IGl0YWxpYzsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbmFtZS5zZXRXb3JkV3JhcChU"
    "cnVlKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zZXNzaW9uX25hbWUpCgogICAgICAgICMgU2F2ZSAv"
    "IExvYWQgcm93CiAgICAgICAgY3RybF9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUgPSBfZ290aGlj"
    "X2J0bigi8J+SviIpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0Rml4ZWRTaXplKDMyLCAyNCkKICAgICAgICBzZWxmLl9idG5f"
    "c2F2ZS5zZXRUb29sVGlwKCJTYXZlIHNlc3Npb24gbm93IikKICAgICAgICBzZWxmLl9idG5fbG9hZCA9IF9nb3RoaWNfYnRuKCLw"
    "n5OCIikKICAgICAgICBzZWxmLl9idG5fbG9hZC5zZXRGaXhlZFNpemUoMzIsIDI0KQogICAgICAgIHNlbGYuX2J0bl9sb2FkLnNl"
    "dFRvb2xUaXAoIkJyb3dzZSBhbmQgbG9hZCBhIHBhc3Qgc2Vzc2lvbiIpCiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90ID0gUUxh"
    "YmVsKCLil48iKQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7"
    "Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOHB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl9hdXRvc2F2"
    "ZV9kb3Quc2V0VG9vbFRpcCgiQXV0b3NhdmUgc3RhdHVzIikKICAgICAgICBzZWxmLl9idG5fc2F2ZS5jbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5fZG9fc2F2ZSkKICAgICAgICBzZWxmLl9idG5fbG9hZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbG9hZCkKICAgICAg"
    "ICBjdHJsX3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX3NhdmUpCiAgICAgICAgY3RybF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9s"
    "b2FkKQogICAgICAgIGN0cmxfcm93LmFkZFdpZGdldChzZWxmLl9hdXRvc2F2ZV9kb3QpCiAgICAgICAgY3RybF9yb3cuYWRkU3Ry"
    "ZXRjaCgpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkTGF5b3V0KGN0cmxfcm93KQoKICAgICAgICAjIEpvdXJuYWwgbG9hZGVk"
    "IGluZGljYXRvcgogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJs"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1BVUlBMRX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWls"
    "eToge0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgIGYiZm9udC1zdHlsZTogaXRhbGljOyIKICAgICAgICApCiAgICAg"
    "ICAgc2VsZi5fam91cm5hbF9sYmwuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoc2Vs"
    "Zi5fam91cm5hbF9sYmwpCgogICAgICAgICMgQ2xlYXIgam91cm5hbCBidXR0b24gKGhpZGRlbiB3aGVuIG5vdCBsb2FkZWQpCiAg"
    "ICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwgPSBfZ290aGljX2J0bigi4pyXIFJldHVybiB0byBQcmVzZW50IikKICAgICAg"
    "ICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFs"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19jbGVhcl9qb3VybmFsKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChz"
    "ZWxmLl9idG5fY2xlYXJfam91cm5hbCkKCiAgICAgICAgIyBEaXZpZGVyCiAgICAgICAgZGl2ID0gUUZyYW1lKCkKICAgICAgICBk"
    "aXYuc2V0RnJhbWVTaGFwZShRRnJhbWUuU2hhcGUuSExpbmUpCiAgICAgICAgZGl2LnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0Nf"
    "Q1JJTVNPTl9ESU19OyIpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KGRpdikKCiAgICAgICAgIyBTZXNzaW9uIGxp"
    "c3QKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgUEFTVCBTRVNTSU9OUyIpKQogICAg"
    "ICAgIHNlbGYuX3Nlc3Npb25fbGlzdCA9IFFMaXN0V2lkZ2V0KCkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3Quc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJp"
    "ZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICAgICAgZiJRTGlzdFdpZGdldDo6aXRlbTpzZWxlY3RlZCB7eyBiYWNrZ3JvdW5k"
    "OiB7Q19DUklNU09OX0RJTX07IH19IgogICAgICAgICkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QuaXRlbURvdWJsZUNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9vbl9zZXNzaW9uX2NsaWNrKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5pdGVtQ2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX29uX3Nlc3Npb25fY2xpY2spCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Nlc3Np"
    "b25fbGlzdCwgMSkKCiAgICAgICAgIyBBZGQgY29udGVudCBhbmQgdG9nZ2xlIHN0cmlwIHRvIHRoZSByb290IGhvcml6b250YWwg"
    "bGF5b3V0CiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fY29udGVudCkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90"
    "b2dnbGVfc3RyaXApCgogICAgZGVmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IG5vdCBz"
    "ZWxmLl9leHBhbmRlZAogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0VmlzaWJsZShzZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxm"
    "Ll90b2dnbGVfYnRuLnNldFRleHQoIuKXgCIgaWYgc2VsZi5fZXhwYW5kZWQgZWxzZSAi4pa2IikKICAgICAgICBzZWxmLnVwZGF0"
    "ZUdlb21ldHJ5KCkKICAgICAgICBwID0gc2VsZi5wYXJlbnRXaWRnZXQoKQogICAgICAgIGlmIHAgYW5kIHAubGF5b3V0KCk6CiAg"
    "ICAgICAgICAgIHAubGF5b3V0KCkuYWN0aXZhdGUoKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2Vz"
    "c2lvbnMgPSBzZWxmLl9zZXNzaW9uX21nci5saXN0X3Nlc3Npb25zKCkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QuY2xlYXIo"
    "KQogICAgICAgIGZvciBzIGluIHNlc3Npb25zOgogICAgICAgICAgICBkYXRlX3N0ciA9IHMuZ2V0KCJkYXRlIiwiIikKICAgICAg"
    "ICAgICAgbmFtZSAgICAgPSBzLmdldCgibmFtZSIsIGRhdGVfc3RyKVs6MzBdCiAgICAgICAgICAgIGNvdW50ICAgID0gcy5nZXQo"
    "Im1lc3NhZ2VfY291bnQiLCAwKQogICAgICAgICAgICBpdGVtID0gUUxpc3RXaWRnZXRJdGVtKGYie2RhdGVfc3RyfVxue25hbWV9"
    "ICh7Y291bnR9IG1zZ3MpIikKICAgICAgICAgICAgaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgZGF0ZV9z"
    "dHIpCiAgICAgICAgICAgIGl0ZW0uc2V0VG9vbFRpcChmIkRvdWJsZS1jbGljayB0byBsb2FkIHNlc3Npb24gZnJvbSB7ZGF0ZV9z"
    "dHJ9IikKICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0LmFkZEl0ZW0oaXRlbSkKCiAgICBkZWYgc2V0X3Nlc3Npb25fbmFt"
    "ZShzZWxmLCBuYW1lOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNldFRleHQobmFtZVs6NTBdIG9y"
    "ICJOZXcgU2Vzc2lvbiIpCgogICAgZGVmIHNldF9hdXRvc2F2ZV9pbmRpY2F0b3Ioc2VsZiwgc2F2ZWQ6IGJvb2wpIC0+IE5vbmU6"
    "CiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dSRUVOIGlm"
    "IHNhdmVkIGVsc2UgQ19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDhweDsgYm9yZGVyOiBub25lOyIKICAg"
    "ICAgICApCiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFRvb2xUaXAoCiAgICAgICAgICAgICJBdXRvc2F2ZWQiIGlmIHNh"
    "dmVkIGVsc2UgIlBlbmRpbmcgYXV0b3NhdmUiCiAgICAgICAgKQoKICAgIGRlZiBzZXRfam91cm5hbF9sb2FkZWQoc2VsZiwgZGF0"
    "ZV9zdHI6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRUZXh0KGYi8J+TliBKb3VybmFsOiB7ZGF0"
    "ZV9zdHJ9IikKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKFRydWUpCgogICAgZGVmIGNsZWFyX2pv"
    "dXJuYWxfaW5kaWNhdG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0VGV4dCgiIikKICAgICAg"
    "ICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKEZhbHNlKQoKICAgIGRlZiBfZG9fc2F2ZShzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuX3Nlc3Npb25fbWdyLnNhdmUoKQogICAgICAgIHNlbGYuc2V0X2F1dG9zYXZlX2luZGljYXRvcihUcnVl"
    "KQogICAgICAgIHNlbGYucmVmcmVzaCgpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0VGV4dCgi4pyTIikKICAgICAgICBRVGlt"
    "ZXIuc2luZ2xlU2hvdCgxNTAwLCBsYW1iZGE6IHNlbGYuX2J0bl9zYXZlLnNldFRleHQoIvCfkr4iKSkKICAgICAgICBRVGltZXIu"
    "c2luZ2xlU2hvdCgzMDAwLCBsYW1iZGE6IHNlbGYuc2V0X2F1dG9zYXZlX2luZGljYXRvcihGYWxzZSkpCgogICAgZGVmIF9kb19s"
    "b2FkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBUcnkgc2VsZWN0ZWQgaXRlbSBmaXJzdAogICAgICAgIGl0ZW0gPSBzZWxmLl9z"
    "ZXNzaW9uX2xpc3QuY3VycmVudEl0ZW0oKQogICAgICAgIGlmIG5vdCBpdGVtOgogICAgICAgICAgICAjIElmIG5vdGhpbmcgc2Vs"
    "ZWN0ZWQsIHRyeSB0aGUgZmlyc3QgaXRlbQogICAgICAgICAgICBpZiBzZWxmLl9zZXNzaW9uX2xpc3QuY291bnQoKSA+IDA6CiAg"
    "ICAgICAgICAgICAgICBpdGVtID0gc2VsZi5fc2Vzc2lvbl9saXN0Lml0ZW0oMCkKICAgICAgICAgICAgICAgIHNlbGYuX3Nlc3Np"
    "b25fbGlzdC5zZXRDdXJyZW50SXRlbShpdGVtKQogICAgICAgIGlmIGl0ZW06CiAgICAgICAgICAgIGRhdGVfc3RyID0gaXRlbS5k"
    "YXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgc2VsZi5zZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmVtaXQo"
    "ZGF0ZV9zdHIpCgogICAgZGVmIF9vbl9zZXNzaW9uX2NsaWNrKHNlbGYsIGl0ZW0pIC0+IE5vbmU6CiAgICAgICAgZGF0ZV9zdHIg"
    "PSBpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAgICAgIHNlbGYuc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5l"
    "bWl0KGRhdGVfc3RyKQoKICAgIGRlZiBfZG9fY2xlYXJfam91cm5hbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuc2Vzc2lv"
    "bl9jbGVhcl9yZXF1ZXN0ZWQuZW1pdCgpCiAgICAgICAgc2VsZi5jbGVhcl9qb3VybmFsX2luZGljYXRvcigpCgoKIyDilIDilIAg"
    "VE9SUE9SIFBBTkVMIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBUb3Jwb3JQYW5lbChRV2lkZ2V0"
    "KToKICAgICIiIgogICAgVGhyZWUtc3RhdGUgc3VzcGVuc2lvbiB0b2dnbGU6IEFXQUtFIHwgQVVUTyB8IFNVU1BFTkQKCiAgICBB"
    "V0FLRSAg4oCUIG1vZGVsIGxvYWRlZCwgYXV0by10b3Jwb3IgZGlzYWJsZWQsIGlnbm9yZXMgVlJBTSBwcmVzc3VyZQogICAgQVVU"
    "TyAgIOKAlCBtb2RlbCBsb2FkZWQsIG1vbml0b3JzIFZSQU0gcHJlc3N1cmUsIGF1dG8tdG9ycG9yIGlmIHN1c3RhaW5lZAogICAg"
    "U1VTUEVORCDigJQgbW9kZWwgdW5sb2FkZWQsIHN0YXlzIHN1c3BlbmRlZCB1bnRpbCBtYW51YWxseSBjaGFuZ2VkCgogICAgU2ln"
    "bmFsczoKICAgICAgICBzdGF0ZV9jaGFuZ2VkKHN0cikgIOKAlCAiQVdBS0UiIHwgIkFVVE8iIHwgIlNVU1BFTkQiCiAgICAiIiIK"
    "CiAgICBzdGF0ZV9jaGFuZ2VkID0gU2lnbmFsKHN0cikKCiAgICBTVEFURVMgPSBbIkFXQUtFIiwgIkFVVE8iLCAiU1VTUEVORCJd"
    "CgogICAgU1RBVEVfU1RZTEVTID0gewogICAgICAgICJBV0FLRSI6IHsKICAgICAgICAgICAgImFjdGl2ZSI6ICAgZiJiYWNrZ3Jv"
    "dW5kOiAjMmExYTA1OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xp"
    "ZCB7Q19HT0xEfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7"
    "IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3Vu"
    "ZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNv"
    "bGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTog"
    "OXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAibGFiZWwiOiAgICAi4piAIEFX"
    "QUtFIiwKICAgICAgICAgICAgInRvb2x0aXAiOiAgIk1vZGVsIGFjdGl2ZS4gQXV0by10b3Jwb3IgZGlzYWJsZWQuIiwKICAgICAg"
    "ICB9LAogICAgICAgICJBVVRPIjogewogICAgICAgICAgICAiYWN0aXZlIjogICBmImJhY2tncm91bmQ6ICMxYTEwMDU7IGNvbG9y"
    "OiAjY2M4ODIyOyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQgI2NjODgyMjsgYm9yZGVyLXJh"
    "ZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBw"
    "YWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtD"
    "X1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRl"
    "ci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9s"
    "ZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAibGFiZWwiOiAgICAi4peJIEFVVE8iLAogICAgICAgICAgICAidG9v"
    "bHRpcCI6ICAiTW9kZWwgYWN0aXZlLiBBdXRvLXN1c3BlbmQgb24gVlJBTSBwcmVzc3VyZS4iLAogICAgICAgIH0sCiAgICAgICAg"
    "IlNVU1BFTkQiOiB7CiAgICAgICAgICAgICJhY3RpdmUiOiAgIGYiYmFja2dyb3VuZDoge0NfUFVSUExFX0RJTX07IGNvbG9yOiB7"
    "Q19QVVJQTEV9OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfUFVSUExFfTsgYm9yZGVy"
    "LXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xk"
    "OyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6"
    "IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJv"
    "cmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDog"
    "Ym9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAibGFiZWwiOiAgICBmIuKasCB7VUlfU1VTUEVOU0lPTl9MQUJF"
    "TC5zdHJpcCgpIGlmIHN0cihVSV9TVVNQRU5TSU9OX0xBQkVMKS5zdHJpcCgpIGVsc2UgJ1N1c3BlbmQnfSIsCiAgICAgICAgICAg"
    "ICJ0b29sdGlwIjogIGYiTW9kZWwgdW5sb2FkZWQuIHtERUNLX05BTUV9IHNsZWVwcyB1bnRpbCBtYW51YWxseSBhd2FrZW5lZC4i"
    "LAogICAgICAgIH0sCiAgICB9CgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9f"
    "aW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9jdXJyZW50ID0gIkFXQUtFIgogICAgICAgIHNlbGYuX2J1dHRvbnM6IGRpY3Rb"
    "c3RyLCBRUHVzaEJ1dHRvbl0gPSB7fQogICAgICAgIGxheW91dCA9IFFIQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNl"
    "dENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDIpCgogICAgICAgIGZvciBzdGF0"
    "ZSBpbiBzZWxmLlNUQVRFUzoKICAgICAgICAgICAgYnRuID0gUVB1c2hCdXR0b24oc2VsZi5TVEFURV9TVFlMRVNbc3RhdGVdWyJs"
    "YWJlbCJdKQogICAgICAgICAgICBidG4uc2V0VG9vbFRpcChzZWxmLlNUQVRFX1NUWUxFU1tzdGF0ZV1bInRvb2x0aXAiXSkKICAg"
    "ICAgICAgICAgYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgICAgICBidG4uY2xpY2tlZC5jb25uZWN0KGxhbWJkYSBjaGVj"
    "a2VkLCBzPXN0YXRlOiBzZWxmLl9zZXRfc3RhdGUocykpCiAgICAgICAgICAgIHNlbGYuX2J1dHRvbnNbc3RhdGVdID0gYnRuCiAg"
    "ICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoYnRuKQoKICAgICAgICBzZWxmLl9hcHBseV9zdHlsZXMoKQoKICAgIGRlZiBfc2V0"
    "X3N0YXRlKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgaWYgc3RhdGUgPT0gc2VsZi5fY3VycmVudDoKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fY3VycmVudCA9IHN0YXRlCiAgICAgICAgc2VsZi5fYXBwbHlfc3R5bGVzKCkKICAg"
    "ICAgICBzZWxmLnN0YXRlX2NoYW5nZWQuZW1pdChzdGF0ZSkKCiAgICBkZWYgX2FwcGx5X3N0eWxlcyhzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIGZvciBzdGF0ZSwgYnRuIGluIHNlbGYuX2J1dHRvbnMuaXRlbXMoKToKICAgICAgICAgICAgc3R5bGVfa2V5ID0gImFj"
    "dGl2ZSIgaWYgc3RhdGUgPT0gc2VsZi5fY3VycmVudCBlbHNlICJpbmFjdGl2ZSIKICAgICAgICAgICAgYnRuLnNldFN0eWxlU2hl"
    "ZXQoc2VsZi5TVEFURV9TVFlMRVNbc3RhdGVdW3N0eWxlX2tleV0pCgogICAgQHByb3BlcnR5CiAgICBkZWYgY3VycmVudF9zdGF0"
    "ZShzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2N1cnJlbnQKCiAgICBkZWYgc2V0X3N0YXRlKHNlbGYsIHN0YXRl"
    "OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIiIiU2V0IHN0YXRlIHByb2dyYW1tYXRpY2FsbHkgKGUuZy4gZnJvbSBhdXRvLXRvcnBv"
    "ciBkZXRlY3Rpb24pLiIiIgogICAgICAgIGlmIHN0YXRlIGluIHNlbGYuU1RBVEVTOgogICAgICAgICAgICBzZWxmLl9zZXRfc3Rh"
    "dGUoc3RhdGUpCgoKY2xhc3MgU2V0dGluZ3NTZWN0aW9uKFFXaWRnZXQpOgogICAgIiIiU2ltcGxlIGNvbGxhcHNpYmxlIHNlY3Rp"
    "b24gdXNlZCBieSBTZXR0aW5nc1RhYi4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgdGl0bGU6IHN0ciwgcGFyZW50PU5vbmUs"
    "IGV4cGFuZGVkOiBib29sID0gVHJ1ZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZXhw"
    "YW5kZWQgPSBleHBhbmRlZAoKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRz"
    "TWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHJvb3Quc2V0U3BhY2luZygwKQoKICAgICAgICBzZWxmLl9oZWFkZXJfYnRuID0g"
    "UVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX2hlYWRlcl9idG4uc2V0VGV4dChmIuKWvCB7dGl0bGV9IiBpZiBleHBhbmRlZCBl"
    "bHNlIGYi4pa2IHt0aXRsZX0iKQogICAgICAgIHNlbGYuX2hlYWRlcl9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJi"
    "YWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgog"
    "ICAgICAgICAgICBmInBhZGRpbmc6IDZweDsgdGV4dC1hbGlnbjogbGVmdDsgZm9udC13ZWlnaHQ6IGJvbGQ7IgogICAgICAgICkK"
    "ICAgICAgICBzZWxmLl9oZWFkZXJfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCgogICAgICAgIHNlbGYuX2NvbnRl"
    "bnQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jb250ZW50X2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX2NvbnRlbnQpCiAg"
    "ICAgICAgc2VsZi5fY29udGVudF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDgsIDgsIDgsIDgpCiAgICAgICAgc2VsZi5fY29u"
    "dGVudF9sYXlvdXQuc2V0U3BhY2luZyg4KQogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItdG9wOiBub25lOyIKICAg"
    "ICAgICApCiAgICAgICAgc2VsZi5fY29udGVudC5zZXRWaXNpYmxlKGV4cGFuZGVkKQoKICAgICAgICByb290LmFkZFdpZGdldChz"
    "ZWxmLl9oZWFkZXJfYnRuKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2NvbnRlbnQpCgogICAgQHByb3BlcnR5CiAgICBk"
    "ZWYgY29udGVudF9sYXlvdXQoc2VsZikgLT4gUVZCb3hMYXlvdXQ6CiAgICAgICAgcmV0dXJuIHNlbGYuX2NvbnRlbnRfbGF5b3V0"
    "CgogICAgZGVmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRl"
    "ZAogICAgICAgIHNlbGYuX2hlYWRlcl9idG4uc2V0VGV4dCgKICAgICAgICAgICAgc2VsZi5faGVhZGVyX2J0bi50ZXh0KCkucmVw"
    "bGFjZSgi4pa8IiwgIuKWtiIsIDEpCiAgICAgICAgICAgIGlmIG5vdCBzZWxmLl9leHBhbmRlZCBlbHNlCiAgICAgICAgICAgIHNl"
    "bGYuX2hlYWRlcl9idG4udGV4dCgpLnJlcGxhY2UoIuKWtiIsICLilrwiLCAxKQogICAgICAgICkKICAgICAgICBzZWxmLl9jb250"
    "ZW50LnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCgoKY2xhc3MgU2V0dGluZ3NUYWIoUVdpZGdldCk6CiAgICAiIiJEZWNrLXdp"
    "ZGUgcnVudGltZSBzZXR0aW5ncyB0YWIuIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGRlY2tfd2luZG93OiAiRWNob0RlY2si"
    "LCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZGVjayA9IGRlY2tf"
    "d2luZG93CiAgICAgICAgc2VsZi5fc2VjdGlvbl9yZWdpc3RyeTogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc2VjdGlv"
    "bl93aWRnZXRzOiBkaWN0W3N0ciwgU2V0dGluZ3NTZWN0aW9uXSA9IHt9CgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxm"
    "KQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDApCgog"
    "ICAgICAgIHNjcm9sbCA9IFFTY3JvbGxBcmVhKCkKICAgICAgICBzY3JvbGwuc2V0V2lkZ2V0UmVzaXphYmxlKFRydWUpCiAgICAg"
    "ICAgc2Nyb2xsLnNldEhvcml6b250YWxTY3JvbGxCYXJQb2xpY3koUXQuU2Nyb2xsQmFyUG9saWN5LlNjcm9sbEJhckFsd2F5c09m"
    "ZikKICAgICAgICBzY3JvbGwuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHfTsgYm9yZGVyOiAxcHggc29saWQge0Nf"
    "Q1JJTVNPTl9ESU19OyIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2Nyb2xsKQoKICAgICAgICBib2R5ID0gUVdpZGdldCgpCiAg"
    "ICAgICAgc2VsZi5fYm9keV9sYXlvdXQgPSBRVkJveExheW91dChib2R5KQogICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0LnNldENv"
    "bnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0LnNldFNwYWNpbmcoOCkKICAgICAgICBz"
    "Y3JvbGwuc2V0V2lkZ2V0KGJvZHkpCgogICAgICAgIHNlbGYuX3JlZ2lzdGVyX2NvcmVfc2VjdGlvbnMoKQoKICAgIGRlZiBfcmVn"
    "aXN0ZXJfc2VjdGlvbihzZWxmLCAqLCBzZWN0aW9uX2lkOiBzdHIsIHRpdGxlOiBzdHIsIGNhdGVnb3J5OiBzdHIsIHNvdXJjZV9v"
    "d25lcjogc3RyLCBzb3J0X2tleTogaW50LCBidWlsZGVyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3NlY3Rpb25fcmVnaXN0cnku"
    "YXBwZW5kKHsKICAgICAgICAgICAgInNlY3Rpb25faWQiOiBzZWN0aW9uX2lkLAogICAgICAgICAgICAidGl0bGUiOiB0aXRsZSwK"
    "ICAgICAgICAgICAgImNhdGVnb3J5IjogY2F0ZWdvcnksCiAgICAgICAgICAgICJzb3VyY2Vfb3duZXIiOiBzb3VyY2Vfb3duZXIs"
    "CiAgICAgICAgICAgICJzb3J0X2tleSI6IHNvcnRfa2V5LAogICAgICAgICAgICAiYnVpbGRlciI6IGJ1aWxkZXIsCiAgICAgICAg"
    "fSkKCiAgICBkZWYgX3JlZ2lzdGVyX2NvcmVfc2VjdGlvbnMoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWdpc3Rlcl9z"
    "ZWN0aW9uKAogICAgICAgICAgICBzZWN0aW9uX2lkPSJzeXN0ZW1fc2V0dGluZ3MiLAogICAgICAgICAgICB0aXRsZT0iU3lzdGVt"
    "IFNldHRpbmdzIiwKICAgICAgICAgICAgY2F0ZWdvcnk9ImNvcmUiLAogICAgICAgICAgICBzb3VyY2Vfb3duZXI9ImRlY2tfcnVu"
    "dGltZSIsCiAgICAgICAgICAgIHNvcnRfa2V5PTEwMCwKICAgICAgICAgICAgYnVpbGRlcj1zZWxmLl9idWlsZF9zeXN0ZW1fc2Vj"
    "dGlvbiwKICAgICAgICApCiAgICAgICAgc2VsZi5fcmVnaXN0ZXJfc2VjdGlvbigKICAgICAgICAgICAgc2VjdGlvbl9pZD0iaW50"
    "ZWdyYXRpb25fc2V0dGluZ3MiLAogICAgICAgICAgICB0aXRsZT0iSW50ZWdyYXRpb24gU2V0dGluZ3MiLAogICAgICAgICAgICBj"
    "YXRlZ29yeT0iY29yZSIsCiAgICAgICAgICAgIHNvdXJjZV9vd25lcj0iZGVja19ydW50aW1lIiwKICAgICAgICAgICAgc29ydF9r"
    "ZXk9MjAwLAogICAgICAgICAgICBidWlsZGVyPXNlbGYuX2J1aWxkX2ludGVncmF0aW9uX3NlY3Rpb24sCiAgICAgICAgKQogICAg"
    "ICAgIHNlbGYuX3JlZ2lzdGVyX3NlY3Rpb24oCiAgICAgICAgICAgIHNlY3Rpb25faWQ9InVpX3NldHRpbmdzIiwKICAgICAgICAg"
    "ICAgdGl0bGU9IlVJIFNldHRpbmdzIiwKICAgICAgICAgICAgY2F0ZWdvcnk9ImNvcmUiLAogICAgICAgICAgICBzb3VyY2Vfb3du"
    "ZXI9ImRlY2tfcnVudGltZSIsCiAgICAgICAgICAgIHNvcnRfa2V5PTMwMCwKICAgICAgICAgICAgYnVpbGRlcj1zZWxmLl9idWls"
    "ZF91aV9zZWN0aW9uLAogICAgICAgICkKCiAgICAgICAgZm9yIG1ldGEgaW4gc29ydGVkKHNlbGYuX3NlY3Rpb25fcmVnaXN0cnks"
    "IGtleT1sYW1iZGEgbTogbS5nZXQoInNvcnRfa2V5IiwgOTk5OSkpOgogICAgICAgICAgICBzZWN0aW9uID0gU2V0dGluZ3NTZWN0"
    "aW9uKG1ldGFbInRpdGxlIl0sIGV4cGFuZGVkPVRydWUpCiAgICAgICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0LmFkZFdpZGdldChz"
    "ZWN0aW9uKQogICAgICAgICAgICBzZWxmLl9zZWN0aW9uX3dpZGdldHNbbWV0YVsic2VjdGlvbl9pZCJdXSA9IHNlY3Rpb24KICAg"
    "ICAgICAgICAgbWV0YVsiYnVpbGRlciJdKHNlY3Rpb24uY29udGVudF9sYXlvdXQpCgogICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0"
    "LmFkZFN0cmV0Y2goMSkKCiAgICBkZWYgX2J1aWxkX3N5c3RlbV9zZWN0aW9uKHNlbGYsIGxheW91dDogUVZCb3hMYXlvdXQpIC0+"
    "IE5vbmU6CiAgICAgICAgaWYgc2VsZi5fZGVjay5fdG9ycG9yX3BhbmVsIGlzIG5vdCBOb25lOgogICAgICAgICAgICBsYXlvdXQu"
    "YWRkV2lkZ2V0KFFMYWJlbCgiT3BlcmF0aW9uYWwgTW9kZSIpKQogICAgICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2Rl"
    "Y2suX3RvcnBvcl9wYW5lbCkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChRTGFiZWwoIklkbGUiKSkKICAgICAgICBsYXlvdXQu"
    "YWRkV2lkZ2V0KHNlbGYuX2RlY2suX2lkbGVfYnRuKQoKICAgICAgICBzZXR0aW5ncyA9IENGRy5nZXQoInNldHRpbmdzIiwge30p"
    "CiAgICAgICAgdHpfYXV0byA9IGJvb2woc2V0dGluZ3MuZ2V0KCJ0aW1lem9uZV9hdXRvX2RldGVjdCIsIFRydWUpKQogICAgICAg"
    "IHR6X292ZXJyaWRlID0gc3RyKHNldHRpbmdzLmdldCgidGltZXpvbmVfb3ZlcnJpZGUiLCAiIikgb3IgIiIpLnN0cmlwKCkKCiAg"
    "ICAgICAgdHpfYXV0b19jaGsgPSBRQ2hlY2tCb3goIkF1dG8tZGV0ZWN0IGxvY2FsL3N5c3RlbSB0aW1lIHpvbmUiKQogICAgICAg"
    "IHR6X2F1dG9fY2hrLnNldENoZWNrZWQodHpfYXV0bykKICAgICAgICB0el9hdXRvX2Noay50b2dnbGVkLmNvbm5lY3Qoc2VsZi5f"
    "ZGVjay5fc2V0X3RpbWV6b25lX2F1dG9fZGV0ZWN0KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQodHpfYXV0b19jaGspCgogICAg"
    "ICAgIHR6X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICB0el9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgiTWFudWFsIFRpbWUgWm9u"
    "ZSBPdmVycmlkZToiKSkKICAgICAgICB0el9jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgdHpfY29tYm8uc2V0RWRpdGFibGUo"
    "VHJ1ZSkKICAgICAgICB0el9vcHRpb25zID0gWwogICAgICAgICAgICAiQW1lcmljYS9DaGljYWdvIiwgIkFtZXJpY2EvTmV3X1lv"
    "cmsiLCAiQW1lcmljYS9Mb3NfQW5nZWxlcyIsCiAgICAgICAgICAgICJBbWVyaWNhL0RlbnZlciIsICJVVEMiCiAgICAgICAgXQog"
    "ICAgICAgIHR6X2NvbWJvLmFkZEl0ZW1zKHR6X29wdGlvbnMpCiAgICAgICAgaWYgdHpfb3ZlcnJpZGU6CiAgICAgICAgICAgIGlm"
    "IHR6X2NvbWJvLmZpbmRUZXh0KHR6X292ZXJyaWRlKSA8IDA6CiAgICAgICAgICAgICAgICB0el9jb21iby5hZGRJdGVtKHR6X292"
    "ZXJyaWRlKQogICAgICAgICAgICB0el9jb21iby5zZXRDdXJyZW50VGV4dCh0el9vdmVycmlkZSkKICAgICAgICBlbHNlOgogICAg"
    "ICAgICAgICB0el9jb21iby5zZXRDdXJyZW50VGV4dCgiQW1lcmljYS9DaGljYWdvIikKICAgICAgICB0el9jb21iby5zZXRFbmFi"
    "bGVkKG5vdCB0el9hdXRvKQogICAgICAgIHR6X2NvbWJvLmN1cnJlbnRUZXh0Q2hhbmdlZC5jb25uZWN0KHNlbGYuX2RlY2suX3Nl"
    "dF90aW1lem9uZV9vdmVycmlkZSkKICAgICAgICB0el9hdXRvX2Noay50b2dnbGVkLmNvbm5lY3QobGFtYmRhIGVuYWJsZWQ6IHR6"
    "X2NvbWJvLnNldEVuYWJsZWQobm90IGVuYWJsZWQpKQogICAgICAgIHR6X3Jvdy5hZGRXaWRnZXQodHpfY29tYm8sIDEpCiAgICAg"
    "ICAgdHpfaG9zdCA9IFFXaWRnZXQoKQogICAgICAgIHR6X2hvc3Quc2V0TGF5b3V0KHR6X3JvdykKICAgICAgICBsYXlvdXQuYWRk"
    "V2lkZ2V0KHR6X2hvc3QpCgogICAgZGVmIF9idWlsZF9pbnRlZ3JhdGlvbl9zZWN0aW9uKHNlbGYsIGxheW91dDogUVZCb3hMYXlv"
    "dXQpIC0+IE5vbmU6CiAgICAgICAgc2V0dGluZ3MgPSBDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KQogICAgICAgIGdvb2dsZV9zZWNv"
    "bmRzID0gaW50KHNldHRpbmdzLmdldCgiZ29vZ2xlX2luYm91bmRfaW50ZXJ2YWxfbXMiLCAzMDAwMCkpIC8vIDEwMDAKICAgICAg"
    "ICBnb29nbGVfc2Vjb25kcyA9IG1heCg1LCBtaW4oNjAwLCBnb29nbGVfc2Vjb25kcykpCiAgICAgICAgZW1haWxfbWludXRlcyA9"
    "IG1heCgxLCBpbnQoc2V0dGluZ3MuZ2V0KCJlbWFpbF9yZWZyZXNoX2ludGVydmFsX21zIiwgMzAwMDAwKSkgLy8gNjAwMDApCgog"
    "ICAgICAgIGdvb2dsZV9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgZ29vZ2xlX3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJHb29n"
    "bGUgcmVmcmVzaCBpbnRlcnZhbCAoc2Vjb25kcyk6IikpCiAgICAgICAgZ29vZ2xlX2JveCA9IFFTcGluQm94KCkKICAgICAgICBn"
    "b29nbGVfYm94LnNldFJhbmdlKDUsIDYwMCkKICAgICAgICBnb29nbGVfYm94LnNldFZhbHVlKGdvb2dsZV9zZWNvbmRzKQogICAg"
    "ICAgIGdvb2dsZV9ib3gudmFsdWVDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fZGVjay5fc2V0X2dvb2dsZV9yZWZyZXNoX3NlY29uZHMp"
    "CiAgICAgICAgZ29vZ2xlX3Jvdy5hZGRXaWRnZXQoZ29vZ2xlX2JveCwgMSkKICAgICAgICBnb29nbGVfaG9zdCA9IFFXaWRnZXQo"
    "KQogICAgICAgIGdvb2dsZV9ob3N0LnNldExheW91dChnb29nbGVfcm93KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoZ29vZ2xl"
    "X2hvc3QpCgogICAgICAgIGVtYWlsX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBlbWFpbF9yb3cuYWRkV2lkZ2V0KFFMYWJl"
    "bCgiRW1haWwgcmVmcmVzaCBpbnRlcnZhbCAobWludXRlcyk6IikpCiAgICAgICAgZW1haWxfYm94ID0gUUNvbWJvQm94KCkKICAg"
    "ICAgICBlbWFpbF9ib3guc2V0RWRpdGFibGUoVHJ1ZSkKICAgICAgICBlbWFpbF9ib3guYWRkSXRlbXMoWyIxIiwgIjUiLCAiMTAi"
    "LCAiMTUiLCAiMzAiLCAiNjAiXSkKICAgICAgICBlbWFpbF9ib3guc2V0Q3VycmVudFRleHQoc3RyKGVtYWlsX21pbnV0ZXMpKQog"
    "ICAgICAgIGVtYWlsX2JveC5jdXJyZW50VGV4dENoYW5nZWQuY29ubmVjdChzZWxmLl9kZWNrLl9zZXRfZW1haWxfcmVmcmVzaF9t"
    "aW51dGVzX2Zyb21fdGV4dCkKICAgICAgICBlbWFpbF9yb3cuYWRkV2lkZ2V0KGVtYWlsX2JveCwgMSkKICAgICAgICBlbWFpbF9o"
    "b3N0ID0gUVdpZGdldCgpCiAgICAgICAgZW1haWxfaG9zdC5zZXRMYXlvdXQoZW1haWxfcm93KQogICAgICAgIGxheW91dC5hZGRX"
    "aWRnZXQoZW1haWxfaG9zdCkKCiAgICAgICAgbm90ZSA9IFFMYWJlbCgiRW1haWwgcG9sbGluZyBmb3VuZGF0aW9uIGlzIGNvbmZp"
    "Z3VyYXRpb24tb25seSB1bmxlc3MgYW4gZW1haWwgYmFja2VuZCBpcyBlbmFibGVkLiIpCiAgICAgICAgbm90ZS5zZXRTdHlsZVNo"
    "ZWV0KGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KG5vdGUp"
    "CgogICAgZGVmIF9idWlsZF91aV9zZWN0aW9uKHNlbGYsIGxheW91dDogUVZCb3hMYXlvdXQpIC0+IE5vbmU6CiAgICAgICAgbGF5"
    "b3V0LmFkZFdpZGdldChRTGFiZWwoIldpbmRvdyBTaGVsbCIpKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZGVjay5f"
    "ZnNfYnRuKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZGVjay5fYmxfYnRuKQoKCmNsYXNzIERpY2VHbHlwaChRV2lk"
    "Z2V0KToKICAgICIiIlNpbXBsZSAyRCBzaWxob3VldHRlIHJlbmRlcmVyIGZvciBkaWUtdHlwZSByZWNvZ25pdGlvbi4iIiIKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmLCBkaWVfdHlwZTogc3RyID0gImQyMCIsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9f"
    "aW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kaWVfdHlwZSA9IGRpZV90eXBlCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6"
    "ZSg3MCwgNzApCiAgICAgICAgc2VsZi5zZXRNYXhpbXVtU2l6ZSg5MCwgOTApCgogICAgZGVmIHNldF9kaWVfdHlwZShzZWxmLCBk"
    "aWVfdHlwZTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2RpZV90eXBlID0gZGllX3R5cGUKICAgICAgICBzZWxmLnVwZGF0"
    "ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpOgogICAgICAgIHBhaW50ZXIgPSBRUGFpbnRlcihzZWxmKQogICAg"
    "ICAgIHBhaW50ZXIuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICByZWN0ID0g"
    "c2VsZi5yZWN0KCkuYWRqdXN0ZWQoOCwgOCwgLTgsIC04KQoKICAgICAgICBkaWUgPSBzZWxmLl9kaWVfdHlwZQogICAgICAgIGxp"
    "bmUgPSBRQ29sb3IoQ19HT0xEKQogICAgICAgIGZpbGwgPSBRQ29sb3IoQ19CRzIpCiAgICAgICAgYWNjZW50ID0gUUNvbG9yKENf"
    "Q1JJTVNPTikKCiAgICAgICAgcGFpbnRlci5zZXRQZW4oUVBlbihsaW5lLCAyKSkKICAgICAgICBwYWludGVyLnNldEJydXNoKGZp"
    "bGwpCgogICAgICAgIHB0cyA9IFtdCiAgICAgICAgaWYgZGllID09ICJkNCI6CiAgICAgICAgICAgIHB0cyA9IFsKICAgICAgICAg"
    "ICAgICAgIFFQb2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC50b3AoKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5s"
    "ZWZ0KCksIHJlY3QuYm90dG9tKCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QucmlnaHQoKSwgcmVjdC5ib3R0b20oKSks"
    "CiAgICAgICAgICAgIF0KICAgICAgICBlbGlmIGRpZSA9PSAiZDYiOgogICAgICAgICAgICBwYWludGVyLmRyYXdSb3VuZGVkUmVj"
    "dChyZWN0LCA0LCA0KQogICAgICAgIGVsaWYgZGllID09ICJkOCI6CiAgICAgICAgICAgIHB0cyA9IFsKICAgICAgICAgICAgICAg"
    "IFFQb2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC50b3AoKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5sZWZ0KCks"
    "IHJlY3QuY2VudGVyKCkueSgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC5ib3R0b20o"
    "KSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5yaWdodCgpLCByZWN0LmNlbnRlcigpLnkoKSksCiAgICAgICAgICAgIF0K"
    "ICAgICAgICBlbGlmIGRpZSBpbiAoImQxMCIsICJkMTAwIik6CiAgICAgICAgICAgIHB0cyA9IFsKICAgICAgICAgICAgICAgIFFQ"
    "b2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC50b3AoKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5sZWZ0KCkgKyA4"
    "LCByZWN0LnRvcCgpICsgMTYpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpLCByZWN0LmJvdHRvbSgpIC0gMTIp"
    "LAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QuY2VudGVyKCkueCgpLCByZWN0LmJvdHRvbSgpKSwKICAgICAgICAgICAgICAg"
    "IFFQb2ludChyZWN0LnJpZ2h0KCksIHJlY3QuYm90dG9tKCkgLSAxMiksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5yaWdo"
    "dCgpIC0gOCwgcmVjdC50b3AoKSArIDE2KSwKICAgICAgICAgICAgXQogICAgICAgIGVsaWYgZGllID09ICJkMTIiOgogICAgICAg"
    "ICAgICBjeCA9IHJlY3QuY2VudGVyKCkueCgpOyBjeSA9IHJlY3QuY2VudGVyKCkueSgpCiAgICAgICAgICAgIHJ4ID0gcmVjdC53"
    "aWR0aCgpIC8gMjsgcnkgPSByZWN0LmhlaWdodCgpIC8gMgogICAgICAgICAgICBmb3IgaSBpbiByYW5nZSg1KToKICAgICAgICAg"
    "ICAgICAgIGEgPSAobWF0aC5waSAqIDIgKiBpIC8gNSkgLSAobWF0aC5waSAvIDIpCiAgICAgICAgICAgICAgICBwdHMuYXBwZW5k"
    "KFFQb2ludChpbnQoY3ggKyByeCAqIG1hdGguY29zKGEpKSwgaW50KGN5ICsgcnkgKiBtYXRoLnNpbihhKSkpKQogICAgICAgIGVs"
    "c2U6ICAjIGQyMAogICAgICAgICAgICBwdHMgPSBbCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJl"
    "Y3QudG9wKCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpICsgMTAsIHJlY3QudG9wKCkgKyAxNCksCiAgICAg"
    "ICAgICAgICAgICBRUG9pbnQocmVjdC5sZWZ0KCksIHJlY3QuY2VudGVyKCkueSgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChy"
    "ZWN0LmxlZnQoKSArIDEwLCByZWN0LmJvdHRvbSgpIC0gMTQpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QuY2VudGVyKCku"
    "eCgpLCByZWN0LmJvdHRvbSgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LnJpZ2h0KCkgLSAxMCwgcmVjdC5ib3R0b20o"
    "KSAtIDE0KSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LnJpZ2h0KCksIHJlY3QuY2VudGVyKCkueSgpKSwKICAgICAgICAg"
    "ICAgICAgIFFQb2ludChyZWN0LnJpZ2h0KCkgLSAxMCwgcmVjdC50b3AoKSArIDE0KSwKICAgICAgICAgICAgXQoKICAgICAgICBp"
    "ZiBwdHM6CiAgICAgICAgICAgIHBhdGggPSBRUGFpbnRlclBhdGgoKQogICAgICAgICAgICBwYXRoLm1vdmVUbyhwdHNbMF0pCiAg"
    "ICAgICAgICAgIGZvciBwIGluIHB0c1sxOl06CiAgICAgICAgICAgICAgICBwYXRoLmxpbmVUbyhwKQogICAgICAgICAgICBwYXRo"
    "LmNsb3NlU3VicGF0aCgpCiAgICAgICAgICAgIHBhaW50ZXIuZHJhd1BhdGgocGF0aCkKCiAgICAgICAgcGFpbnRlci5zZXRQZW4o"
    "UVBlbihhY2NlbnQsIDEpKQogICAgICAgIHR4dCA9ICIlIiBpZiBkaWUgPT0gImQxMDAiIGVsc2UgZGllLnJlcGxhY2UoImQiLCAi"
    "IikKICAgICAgICBwYWludGVyLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCAxMiwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAg"
    "IHBhaW50ZXIuZHJhd1RleHQocmVjdCwgUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlciwgdHh0KQoKCmNsYXNzIERpY2VUcmF5"
    "RGllKFFGcmFtZSk6CiAgICBzaW5nbGVDbGlja2VkID0gU2lnbmFsKHN0cikKICAgIGRvdWJsZUNsaWNrZWQgPSBTaWduYWwoc3Ry"
    "KQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBkaWVfdHlwZTogc3RyLCBkaXNwbGF5X2xhYmVsOiBzdHIsIHBhcmVudD1Ob25lKToK"
    "ICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLmRpZV90eXBlID0gZGllX3R5cGUKICAgICAgICBz"
    "ZWxmLmRpc3BsYXlfbGFiZWwgPSBkaXNwbGF5X2xhYmVsCiAgICAgICAgc2VsZi5fY2xpY2tfdGltZXIgPSBRVGltZXIoc2VsZikK"
    "ICAgICAgICBzZWxmLl9jbGlja190aW1lci5zZXRTaW5nbGVTaG90KFRydWUpCiAgICAgICAgc2VsZi5fY2xpY2tfdGltZXIuc2V0"
    "SW50ZXJ2YWwoMjIwKQogICAgICAgIHNlbGYuX2NsaWNrX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9lbWl0X3NpbmdsZSkK"
    "CiAgICAgICAgc2VsZi5zZXRPYmplY3ROYW1lKCJEaWNlVHJheURpZSIpCiAgICAgICAgc2VsZi5zZXRDdXJzb3IoUXQuQ3Vyc29y"
    "U2hhcGUuUG9pbnRpbmdIYW5kQ3Vyc29yKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJRRnJhbWUj"
    "RGljZVRyYXlEaWUge3sgYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJh"
    "ZGl1czogOHB4OyB9fSIKICAgICAgICAgICAgZiJRRnJhbWUjRGljZVRyYXlEaWU6aG92ZXIge3sgYm9yZGVyOiAxcHggc29saWQg"
    "e0NfR09MRH07IH19IgogICAgICAgICkKCiAgICAgICAgbGF5ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXkuc2V0Q29u"
    "dGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAgbGF5LnNldFNwYWNpbmcoMikKCiAgICAgICAgZ2x5cGhfZGllID0gImQx"
    "MDAiIGlmIGRpZV90eXBlID09ICJkJSIgZWxzZSBkaWVfdHlwZQogICAgICAgIHNlbGYuZ2x5cGggPSBEaWNlR2x5cGgoZ2x5cGhf"
    "ZGllKQogICAgICAgIHNlbGYuZ2x5cGguc2V0Rml4ZWRTaXplKDU0LCA1NCkKICAgICAgICBzZWxmLmdseXBoLnNldEF0dHJpYnV0"
    "ZShRdC5XaWRnZXRBdHRyaWJ1dGUuV0FfVHJhbnNwYXJlbnRGb3JNb3VzZUV2ZW50cywgVHJ1ZSkKCiAgICAgICAgc2VsZi5sYmwg"
    "PSBRTGFiZWwoZGlzcGxheV9sYWJlbCkKICAgICAgICBzZWxmLmxibC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGln"
    "bkNlbnRlcikKICAgICAgICBzZWxmLmxibC5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX1RFWFR9OyBmb250LXdlaWdodDogYm9s"
    "ZDsiKQogICAgICAgIHNlbGYubGJsLnNldEF0dHJpYnV0ZShRdC5XaWRnZXRBdHRyaWJ1dGUuV0FfVHJhbnNwYXJlbnRGb3JNb3Vz"
    "ZUV2ZW50cywgVHJ1ZSkKCiAgICAgICAgbGF5LmFkZFdpZGdldChzZWxmLmdseXBoLCAwLCBRdC5BbGlnbm1lbnRGbGFnLkFsaWdu"
    "Q2VudGVyKQogICAgICAgIGxheS5hZGRXaWRnZXQoc2VsZi5sYmwpCgogICAgZGVmIG1vdXNlUHJlc3NFdmVudChzZWxmLCBldmVu"
    "dCk6CiAgICAgICAgaWYgZXZlbnQuYnV0dG9uKCkgPT0gUXQuTW91c2VCdXR0b24uTGVmdEJ1dHRvbjoKICAgICAgICAgICAgaWYg"
    "c2VsZi5fY2xpY2tfdGltZXIuaXNBY3RpdmUoKToKICAgICAgICAgICAgICAgIHNlbGYuX2NsaWNrX3RpbWVyLnN0b3AoKQogICAg"
    "ICAgICAgICAgICAgc2VsZi5kb3VibGVDbGlja2VkLmVtaXQoc2VsZi5kaWVfdHlwZSkKICAgICAgICAgICAgZWxzZToKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2NsaWNrX3RpbWVyLnN0YXJ0KCkKICAgICAgICAgICAgZXZlbnQuYWNjZXB0KCkKICAgICAgICAgICAg"
    "cmV0dXJuCiAgICAgICAgc3VwZXIoKS5tb3VzZVByZXNzRXZlbnQoZXZlbnQpCgogICAgZGVmIF9lbWl0X3NpbmdsZShzZWxmKToK"
    "ICAgICAgICBzZWxmLnNpbmdsZUNsaWNrZWQuZW1pdChzZWxmLmRpZV90eXBlKQoKCmNsYXNzIERpY2VSb2xsZXJUYWIoUVdpZGdl"
    "dCk6CiAgICAiIiJEZWNrLW5hdGl2ZSBEaWNlIFJvbGxlciBtb2R1bGUgdGFiIHdpdGggdHJheS9wb29sIHdvcmtmbG93IGFuZCBz"
    "dHJ1Y3R1cmVkIHJvbGwgZXZlbnRzLiIiIgoKICAgIFRSQVlfT1JERVIgPSBbImQ0IiwgImQ2IiwgImQ4IiwgImQxMCIsICJkMTIi"
    "LCAiZDIwIiwgImQlIl0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgZGlhZ25vc3RpY3NfbG9nZ2VyPU5vbmUpOgogICAgICAgIHN1"
    "cGVyKCkuX19pbml0X18oKQogICAgICAgIHNlbGYuX2xvZyA9IGRpYWdub3N0aWNzX2xvZ2dlciBvciAobGFtYmRhICpfYXJncywg"
    "Kipfa3dhcmdzOiBOb25lKQoKICAgICAgICBzZWxmLnJvbGxfZXZlbnRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLnNh"
    "dmVkX3JvbGxzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLmNvbW1vbl9yb2xsczogZGljdFtzdHIsIGRpY3RdID0ge30K"
    "ICAgICAgICBzZWxmLmV2ZW50X2J5X2lkOiBkaWN0W3N0ciwgZGljdF0gPSB7fQogICAgICAgIHNlbGYuY3VycmVudF9wb29sOiBk"
    "aWN0W3N0ciwgaW50XSA9IHt9CiAgICAgICAgc2VsZi5jdXJyZW50X3JvbGxfaWRzOiBsaXN0W3N0cl0gPSBbXQoKICAgICAgICBz"
    "ZWxmLnJ1bGVfZGVmaW5pdGlvbnM6IGRpY3Rbc3RyLCBkaWN0XSA9IHsKICAgICAgICAgICAgInJ1bGVfNGQ2X2Ryb3BfbG93ZXN0"
    "IjogewogICAgICAgICAgICAgICAgImlkIjogInJ1bGVfNGQ2X2Ryb3BfbG93ZXN0IiwKICAgICAgICAgICAgICAgICJuYW1lIjog"
    "IkQmRCA1ZSBTdGF0IFJvbGwiLAogICAgICAgICAgICAgICAgImRpY2VfY291bnQiOiA0LAogICAgICAgICAgICAgICAgImRpY2Vf"
    "c2lkZXMiOiA2LAogICAgICAgICAgICAgICAgImRyb3BfbG93ZXN0X2NvdW50IjogMSwKICAgICAgICAgICAgICAgICJkcm9wX2hp"
    "Z2hlc3RfY291bnQiOiAwLAogICAgICAgICAgICAgICAgIm5vdGVzIjogIlJvbGwgNGQ2LCBkcm9wIGxvd2VzdCBvbmUuIgogICAg"
    "ICAgICAgICB9LAogICAgICAgICAgICAicnVsZV8zZDZfc3RyYWlnaHQiOiB7CiAgICAgICAgICAgICAgICAiaWQiOiAicnVsZV8z"
    "ZDZfc3RyYWlnaHQiLAogICAgICAgICAgICAgICAgIm5hbWUiOiAiM2Q2IFN0cmFpZ2h0IiwKICAgICAgICAgICAgICAgICJkaWNl"
    "X2NvdW50IjogMywKICAgICAgICAgICAgICAgICJkaWNlX3NpZGVzIjogNiwKICAgICAgICAgICAgICAgICJkcm9wX2xvd2VzdF9j"
    "b3VudCI6IDAsCiAgICAgICAgICAgICAgICAiZHJvcF9oaWdoZXN0X2NvdW50IjogMCwKICAgICAgICAgICAgICAgICJub3RlcyI6"
    "ICJDbGFzc2ljIDNkNiByb2xsLiIKICAgICAgICAgICAgfSwKICAgICAgICB9CgogICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKICAg"
    "ICAgICBzZWxmLl9yZWZyZXNoX3Bvb2xfZWRpdG9yKCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBk"
    "ZWYgX2J1aWxkX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5z"
    "ZXRDb250ZW50c01hcmdpbnMoOCwgOCwgOCwgOCkKICAgICAgICByb290LnNldFNwYWNpbmcoNikKCiAgICAgICAgdHJheV93cmFw"
    "ID0gUUZyYW1lKCkKICAgICAgICB0cmF5X3dyYXAuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjog"
    "MXB4IHNvbGlkIHtDX0JPUkRFUn07IikKICAgICAgICB0cmF5X2xheW91dCA9IFFWQm94TGF5b3V0KHRyYXlfd3JhcCkKICAgICAg"
    "ICB0cmF5X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoOCwgOCwgOCwgOCkKICAgICAgICB0cmF5X2xheW91dC5zZXRTcGFjaW5n"
    "KDYpCiAgICAgICAgdHJheV9sYXlvdXQuYWRkV2lkZ2V0KFFMYWJlbCgiRGljZSBUcmF5IikpCgogICAgICAgIHRyYXlfcm93ID0g"
    "UUhCb3hMYXlvdXQoKQogICAgICAgIHRyYXlfcm93LnNldFNwYWNpbmcoNikKICAgICAgICBmb3IgZGllIGluIHNlbGYuVFJBWV9P"
    "UkRFUjoKICAgICAgICAgICAgYmxvY2sgPSBEaWNlVHJheURpZShkaWUsIGRpZSkKICAgICAgICAgICAgYmxvY2suc2luZ2xlQ2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX2FkZF9kaWVfdG9fcG9vbCkKICAgICAgICAgICAgYmxvY2suZG91YmxlQ2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuX3F1aWNrX3JvbGxfc2luZ2xlX2RpZSkKICAgICAgICAgICAgdHJheV9yb3cuYWRkV2lkZ2V0KGJsb2NrLCAxKQogICAg"
    "ICAgIHRyYXlfbGF5b3V0LmFkZExheW91dCh0cmF5X3JvdykKICAgICAgICByb290LmFkZFdpZGdldCh0cmF5X3dyYXApCgogICAg"
    "ICAgIHBvb2xfd3JhcCA9IFFGcmFtZSgpCiAgICAgICAgcG9vbF93cmFwLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19C"
    "RzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyIpCiAgICAgICAgcHcgPSBRVkJveExheW91dChwb29sX3dyYXApCiAg"
    "ICAgICAgcHcuc2V0Q29udGVudHNNYXJnaW5zKDgsIDgsIDgsIDgpCiAgICAgICAgcHcuc2V0U3BhY2luZyg2KQoKICAgICAgICBw"
    "dy5hZGRXaWRnZXQoUUxhYmVsKCJDdXJyZW50IFBvb2wiKSkKICAgICAgICBzZWxmLnBvb2xfZXhwcl9sYmwgPSBRTGFiZWwoIlBv"
    "b2w6IChlbXB0eSkiKQogICAgICAgIHNlbGYucG9vbF9leHByX2xibC5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX0dPTER9OyBm"
    "b250LXdlaWdodDogYm9sZDsiKQogICAgICAgIHB3LmFkZFdpZGdldChzZWxmLnBvb2xfZXhwcl9sYmwpCgogICAgICAgIHNlbGYu"
    "cG9vbF9lbnRyaWVzX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYucG9vbF9lbnRyaWVzX2xheW91dCA9IFFIQm94TGF5"
    "b3V0KHNlbGYucG9vbF9lbnRyaWVzX3dpZGdldCkKICAgICAgICBzZWxmLnBvb2xfZW50cmllc19sYXlvdXQuc2V0Q29udGVudHNN"
    "YXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VsZi5wb29sX2VudHJpZXNfbGF5b3V0LnNldFNwYWNpbmcoNikKICAgICAgICBw"
    "dy5hZGRXaWRnZXQoc2VsZi5wb29sX2VudHJpZXNfd2lkZ2V0KQoKICAgICAgICBtZXRhX3JvdyA9IFFIQm94TGF5b3V0KCkKICAg"
    "ICAgICBzZWxmLmxhYmVsX2VkaXQgPSBRTGluZUVkaXQoKTsgc2VsZi5sYWJlbF9lZGl0LnNldFBsYWNlaG9sZGVyVGV4dCgiTGFi"
    "ZWwgLyBwdXJwb3NlIikKICAgICAgICBzZWxmLm1vZF9zcGluID0gUVNwaW5Cb3goKTsgc2VsZi5tb2Rfc3Bpbi5zZXRSYW5nZSgt"
    "OTk5LCA5OTkpOyBzZWxmLm1vZF9zcGluLnNldFZhbHVlKDApCiAgICAgICAgc2VsZi5ydWxlX2NvbWJvID0gUUNvbWJvQm94KCk7"
    "IHNlbGYucnVsZV9jb21iby5hZGRJdGVtKCJNYW51YWwgUm9sbCIsICIiKQogICAgICAgIGZvciByaWQsIG1ldGEgaW4gc2VsZi5y"
    "dWxlX2RlZmluaXRpb25zLml0ZW1zKCk6CiAgICAgICAgICAgIHNlbGYucnVsZV9jb21iby5hZGRJdGVtKG1ldGEuZ2V0KCJuYW1l"
    "IiwgcmlkKSwgcmlkKQoKICAgICAgICBmb3IgdGl0bGUsIHcgaW4gKCgiTGFiZWwiLCBzZWxmLmxhYmVsX2VkaXQpLCAoIk1vZGlm"
    "aWVyIiwgc2VsZi5tb2Rfc3BpbiksICgiUnVsZSIsIHNlbGYucnVsZV9jb21ibykpOgogICAgICAgICAgICBjb2wgPSBRVkJveExh"
    "eW91dCgpCiAgICAgICAgICAgIGxibCA9IFFMYWJlbCh0aXRsZSkKICAgICAgICAgICAgbGJsLnNldFN0eWxlU2hlZXQoZiJjb2xv"
    "cjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsiKQogICAgICAgICAgICBjb2wuYWRkV2lkZ2V0KGxibCkKICAgICAgICAg"
    "ICAgY29sLmFkZFdpZGdldCh3KQogICAgICAgICAgICBtZXRhX3Jvdy5hZGRMYXlvdXQoY29sLCAxKQogICAgICAgIHB3LmFkZExh"
    "eW91dChtZXRhX3JvdykKCiAgICAgICAgYWN0aW9ucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLnJvbGxfcG9vbF9idG4g"
    "PSBRUHVzaEJ1dHRvbigiUm9sbCBQb29sIikKICAgICAgICBzZWxmLnJlc2V0X3Bvb2xfYnRuID0gUVB1c2hCdXR0b24oIlJlc2V0"
    "IFBvb2wiKQogICAgICAgIHNlbGYuc2F2ZV9wb29sX2J0biA9IFFQdXNoQnV0dG9uKCJTYXZlIFBvb2wiKQogICAgICAgIGFjdGlv"
    "bnMuYWRkV2lkZ2V0KHNlbGYucm9sbF9wb29sX2J0bikKICAgICAgICBhY3Rpb25zLmFkZFdpZGdldChzZWxmLnJlc2V0X3Bvb2xf"
    "YnRuKQogICAgICAgIGFjdGlvbnMuYWRkV2lkZ2V0KHNlbGYuc2F2ZV9wb29sX2J0bikKICAgICAgICBwdy5hZGRMYXlvdXQoYWN0"
    "aW9ucykKCiAgICAgICAgcm9vdC5hZGRXaWRnZXQocG9vbF93cmFwKQoKICAgICAgICByZXN1bHRfd3JhcCA9IFFGcmFtZSgpCiAg"
    "ICAgICAgcmVzdWx0X3dyYXAuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtD"
    "X0JPUkRFUn07IikKICAgICAgICBybCA9IFFWQm94TGF5b3V0KHJlc3VsdF93cmFwKQogICAgICAgIHJsLnNldENvbnRlbnRzTWFy"
    "Z2lucyg4LCA4LCA4LCA4KQogICAgICAgIHJsLmFkZFdpZGdldChRTGFiZWwoIkN1cnJlbnQgUmVzdWx0IikpCiAgICAgICAgc2Vs"
    "Zi5jdXJyZW50X3Jlc3VsdF9sYmwgPSBRTGFiZWwoIk5vIHJvbGwgeWV0LiIpCiAgICAgICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9s"
    "Ymwuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBybC5hZGRXaWRnZXQoc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwpCiAgICAgICAg"
    "cm9vdC5hZGRXaWRnZXQocmVzdWx0X3dyYXApCgogICAgICAgIG1pZCA9IFFIQm94TGF5b3V0KCkKICAgICAgICBoaXN0b3J5X3dy"
    "YXAgPSBRRnJhbWUoKQogICAgICAgIGhpc3Rvcnlfd3JhcC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9y"
    "ZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsiKQogICAgICAgIGh3ID0gUVZCb3hMYXlvdXQoaGlzdG9yeV93cmFwKQogICAgICAg"
    "IGh3LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQoKICAgICAgICBzZWxmLmhpc3RvcnlfdGFicyA9IFFUYWJXaWRnZXQo"
    "KQogICAgICAgIHNlbGYuY3VycmVudF90YWJsZSA9IHNlbGYuX21ha2Vfcm9sbF90YWJsZSgpCiAgICAgICAgc2VsZi5oaXN0b3J5"
    "X3RhYmxlID0gc2VsZi5fbWFrZV9yb2xsX3RhYmxlKCkKICAgICAgICBzZWxmLmhpc3RvcnlfdGFicy5hZGRUYWIoc2VsZi5jdXJy"
    "ZW50X3RhYmxlLCAiQ3VycmVudCBSb2xscyIpCiAgICAgICAgc2VsZi5oaXN0b3J5X3RhYnMuYWRkVGFiKHNlbGYuaGlzdG9yeV90"
    "YWJsZSwgIlJvbGwgSGlzdG9yeSIpCiAgICAgICAgaHcuYWRkV2lkZ2V0KHNlbGYuaGlzdG9yeV90YWJzLCAxKQoKICAgICAgICBo"
    "aXN0b3J5X2FjdGlvbnMgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5jbGVhcl9oaXN0b3J5X2J0biA9IFFQdXNoQnV0dG9u"
    "KCJDbGVhciBSb2xsIEhpc3RvcnkiKQogICAgICAgIGhpc3RvcnlfYWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5jbGVhcl9oaXN0b3J5"
    "X2J0bikKICAgICAgICBoaXN0b3J5X2FjdGlvbnMuYWRkU3RyZXRjaCgxKQogICAgICAgIGh3LmFkZExheW91dChoaXN0b3J5X2Fj"
    "dGlvbnMpCgogICAgICAgIHNlbGYuZ3JhbmRfdG90YWxfbGJsID0gUUxhYmVsKCJHcmFuZCBUb3RhbDogMCIpCiAgICAgICAgc2Vs"
    "Zi5ncmFuZF90b3RhbF9sYmwuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiAxMnB4OyBmb250LXdl"
    "aWdodDogYm9sZDsiKQogICAgICAgIGh3LmFkZFdpZGdldChzZWxmLmdyYW5kX3RvdGFsX2xibCkKCiAgICAgICAgc2F2ZWRfd3Jh"
    "cCA9IFFGcmFtZSgpCiAgICAgICAgc2F2ZWRfd3JhcC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVy"
    "OiAxcHggc29saWQge0NfQk9SREVSfTsiKQogICAgICAgIHN3ID0gUVZCb3hMYXlvdXQoc2F2ZWRfd3JhcCkKICAgICAgICBzdy5z"
    "ZXRDb250ZW50c01hcmdpbnMoNiwgNiwgNiwgNikKICAgICAgICBzdy5hZGRXaWRnZXQoUUxhYmVsKCJTYXZlZCAvIENvbW1vbiBS"
    "b2xscyIpKQoKICAgICAgICBzdy5hZGRXaWRnZXQoUUxhYmVsKCJTYXZlZCIpKQogICAgICAgIHNlbGYuc2F2ZWRfbGlzdCA9IFFM"
    "aXN0V2lkZ2V0KCkKICAgICAgICBzdy5hZGRXaWRnZXQoc2VsZi5zYXZlZF9saXN0LCAxKQogICAgICAgIHNhdmVkX2FjdGlvbnMg"
    "PSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5ydW5fc2F2ZWRfYnRuID0gUVB1c2hCdXR0b24oIlJ1biIpCiAgICAgICAgc2Vs"
    "Zi5sb2FkX3NhdmVkX2J0biA9IFFQdXNoQnV0dG9uKCJMb2FkL0VkaXQiKQogICAgICAgIHNlbGYuZGVsZXRlX3NhdmVkX2J0biA9"
    "IFFQdXNoQnV0dG9uKCJEZWxldGUiKQogICAgICAgIHNhdmVkX2FjdGlvbnMuYWRkV2lkZ2V0KHNlbGYucnVuX3NhdmVkX2J0bikK"
    "ICAgICAgICBzYXZlZF9hY3Rpb25zLmFkZFdpZGdldChzZWxmLmxvYWRfc2F2ZWRfYnRuKQogICAgICAgIHNhdmVkX2FjdGlvbnMu"
    "YWRkV2lkZ2V0KHNlbGYuZGVsZXRlX3NhdmVkX2J0bikKICAgICAgICBzdy5hZGRMYXlvdXQoc2F2ZWRfYWN0aW9ucykKCiAgICAg"
    "ICAgc3cuYWRkV2lkZ2V0KFFMYWJlbCgiQXV0by1EZXRlY3RlZCBDb21tb24iKSkKICAgICAgICBzZWxmLmNvbW1vbl9saXN0ID0g"
    "UUxpc3RXaWRnZXQoKQogICAgICAgIHN3LmFkZFdpZGdldChzZWxmLmNvbW1vbl9saXN0LCAxKQogICAgICAgIGNvbW1vbl9hY3Rp"
    "b25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYucHJvbW90ZV9jb21tb25fYnRuID0gUVB1c2hCdXR0b24oIlByb21vdGUg"
    "dG8gU2F2ZWQiKQogICAgICAgIHNlbGYuZGlzbWlzc19jb21tb25fYnRuID0gUVB1c2hCdXR0b24oIkRpc21pc3MiKQogICAgICAg"
    "IGNvbW1vbl9hY3Rpb25zLmFkZFdpZGdldChzZWxmLnByb21vdGVfY29tbW9uX2J0bikKICAgICAgICBjb21tb25fYWN0aW9ucy5h"
    "ZGRXaWRnZXQoc2VsZi5kaXNtaXNzX2NvbW1vbl9idG4pCiAgICAgICAgc3cuYWRkTGF5b3V0KGNvbW1vbl9hY3Rpb25zKQoKICAg"
    "ICAgICBzZWxmLmNvbW1vbl9oaW50ID0gUUxhYmVsKCJDb21tb24gc2lnbmF0dXJlIHRyYWNraW5nIGFjdGl2ZS4iKQogICAgICAg"
    "IHNlbGYuY29tbW9uX2hpbnQuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyIpCiAg"
    "ICAgICAgc3cuYWRkV2lkZ2V0KHNlbGYuY29tbW9uX2hpbnQpCgogICAgICAgIG1pZC5hZGRXaWRnZXQoaGlzdG9yeV93cmFwLCAz"
    "KQogICAgICAgIG1pZC5hZGRXaWRnZXQoc2F2ZWRfd3JhcCwgMikKICAgICAgICByb290LmFkZExheW91dChtaWQsIDEpCgogICAg"
    "ICAgIHNlbGYucm9sbF9wb29sX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fcm9sbF9jdXJyZW50X3Bvb2wpCiAgICAgICAgc2Vs"
    "Zi5yZXNldF9wb29sX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fcmVzZXRfcG9vbCkKICAgICAgICBzZWxmLnNhdmVfcG9vbF9i"
    "dG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3NhdmVfcG9vbCkKICAgICAgICBzZWxmLmNsZWFyX2hpc3RvcnlfYnRuLmNsaWNrZWQu"
    "Y29ubmVjdChzZWxmLl9jbGVhcl9oaXN0b3J5KQoKICAgICAgICBzZWxmLnNhdmVkX2xpc3QuaXRlbURvdWJsZUNsaWNrZWQuY29u"
    "bmVjdChsYW1iZGEgaXRlbTogc2VsZi5fcnVuX3NhdmVkX3JvbGwoaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkp"
    "KQogICAgICAgIHNlbGYuY29tbW9uX2xpc3QuaXRlbURvdWJsZUNsaWNrZWQuY29ubmVjdChsYW1iZGEgaXRlbTogc2VsZi5fcnVu"
    "X3NhdmVkX3JvbGwoaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkpKQoKICAgICAgICBzZWxmLnJ1bl9zYXZlZF9i"
    "dG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3J1bl9zZWxlY3RlZF9zYXZlZCkKICAgICAgICBzZWxmLmxvYWRfc2F2ZWRfYnRuLmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl9sb2FkX3NlbGVjdGVkX3NhdmVkKQogICAgICAgIHNlbGYuZGVsZXRlX3NhdmVkX2J0bi5jbGlj"
    "a2VkLmNvbm5lY3Qoc2VsZi5fZGVsZXRlX3NlbGVjdGVkX3NhdmVkKQogICAgICAgIHNlbGYucHJvbW90ZV9jb21tb25fYnRuLmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl9wcm9tb3RlX3NlbGVjdGVkX2NvbW1vbikKICAgICAgICBzZWxmLmRpc21pc3NfY29tbW9uX2J0"
    "bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZGlzbWlzc19zZWxlY3RlZF9jb21tb24pCgogICAgICAgIHNlbGYuY3VycmVudF90YWJs"
    "ZS5zZXRDb250ZXh0TWVudVBvbGljeShRdC5Db250ZXh0TWVudVBvbGljeS5DdXN0b21Db250ZXh0TWVudSkKICAgICAgICBzZWxm"
    "Lmhpc3RvcnlfdGFibGUuc2V0Q29udGV4dE1lbnVQb2xpY3koUXQuQ29udGV4dE1lbnVQb2xpY3kuQ3VzdG9tQ29udGV4dE1lbnUp"
    "CiAgICAgICAgc2VsZi5jdXJyZW50X3RhYmxlLmN1c3RvbUNvbnRleHRNZW51UmVxdWVzdGVkLmNvbm5lY3QobGFtYmRhIHBvczog"
    "c2VsZi5fc2hvd19yb2xsX2NvbnRleHRfbWVudShzZWxmLmN1cnJlbnRfdGFibGUsIHBvcykpCiAgICAgICAgc2VsZi5oaXN0b3J5"
    "X3RhYmxlLmN1c3RvbUNvbnRleHRNZW51UmVxdWVzdGVkLmNvbm5lY3QobGFtYmRhIHBvczogc2VsZi5fc2hvd19yb2xsX2NvbnRl"
    "eHRfbWVudShzZWxmLmhpc3RvcnlfdGFibGUsIHBvcykpCgogICAgZGVmIF9tYWtlX3JvbGxfdGFibGUoc2VsZikgLT4gUVRhYmxl"
    "V2lkZ2V0OgogICAgICAgIHRibCA9IFFUYWJsZVdpZGdldCgwLCA2KQogICAgICAgIHRibC5zZXRIb3Jpem9udGFsSGVhZGVyTGFi"
    "ZWxzKFsiVGltZXN0YW1wIiwgIkxhYmVsIiwgIkV4cHJlc3Npb24iLCAiUmF3IiwgIk1vZGlmaWVyIiwgIlRvdGFsIl0pCiAgICAg"
    "ICAgdGJsLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZShRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0"
    "Y2gpCiAgICAgICAgdGJsLnZlcnRpY2FsSGVhZGVyKCkuc2V0VmlzaWJsZShGYWxzZSkKICAgICAgICB0Ymwuc2V0RWRpdFRyaWdn"
    "ZXJzKFFBYnN0cmFjdEl0ZW1WaWV3LkVkaXRUcmlnZ2VyLk5vRWRpdFRyaWdnZXJzKQogICAgICAgIHRibC5zZXRTZWxlY3Rpb25C"
    "ZWhhdmlvcihRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHRibC5zZXRTb3J0"
    "aW5nRW5hYmxlZChGYWxzZSkKICAgICAgICByZXR1cm4gdGJsCgogICAgZGVmIF9zb3J0ZWRfcG9vbF9pdGVtcyhzZWxmKToKICAg"
    "ICAgICByZXR1cm4gWyhkLCBzZWxmLmN1cnJlbnRfcG9vbC5nZXQoZCwgMCkpIGZvciBkIGluIHNlbGYuVFJBWV9PUkRFUiBpZiBz"
    "ZWxmLmN1cnJlbnRfcG9vbC5nZXQoZCwgMCkgPiAwXQoKICAgIGRlZiBfcG9vbF9leHByZXNzaW9uKHNlbGYsIHBvb2w6IGRpY3Rb"
    "c3RyLCBpbnRdIHwgTm9uZSA9IE5vbmUpIC0+IHN0cjoKICAgICAgICBwID0gcG9vbCBpZiBwb29sIGlzIG5vdCBOb25lIGVsc2Ug"
    "c2VsZi5jdXJyZW50X3Bvb2wKICAgICAgICBwYXJ0cyA9IFtmIntxdHl9e2RpZX0iIGZvciBkaWUsIHF0eSBpbiBbKGQsIHAuZ2V0"
    "KGQsIDApKSBmb3IgZCBpbiBzZWxmLlRSQVlfT1JERVJdIGlmIHF0eSA+IDBdCiAgICAgICAgcmV0dXJuICIgKyAiLmpvaW4ocGFy"
    "dHMpIGlmIHBhcnRzIGVsc2UgIihlbXB0eSkiCgogICAgZGVmIF9ub3JtYWxpemVfcG9vbF9zaWduYXR1cmUoc2VsZiwgcG9vbDog"
    "ZGljdFtzdHIsIGludF0sIG1vZGlmaWVyOiBpbnQsIHJ1bGVfaWQ6IHN0ciA9ICIiKSAtPiBzdHI6CiAgICAgICAgcGFydHMgPSBb"
    "ZiJ7cG9vbC5nZXQoZCwgMCl9e2R9IiBmb3IgZCBpbiBzZWxmLlRSQVlfT1JERVIgaWYgcG9vbC5nZXQoZCwgMCkgPiAwXQogICAg"
    "ICAgIGJhc2UgPSAiKyIuam9pbihwYXJ0cykgaWYgcGFydHMgZWxzZSAiMCIKICAgICAgICBzaWcgPSBmIntiYXNlfXttb2RpZmll"
    "cjorZH0iCiAgICAgICAgcmV0dXJuIGYie3NpZ31fe3J1bGVfaWR9IiBpZiBydWxlX2lkIGVsc2Ugc2lnCgogICAgZGVmIF9kaWNl"
    "X2xhYmVsKHNlbGYsIGRpZV90eXBlOiBzdHIpIC0+IHN0cjoKICAgICAgICByZXR1cm4gImQlIiBpZiBkaWVfdHlwZSA9PSAiZCUi"
    "IGVsc2UgZGllX3R5cGUKCiAgICBkZWYgX3JvbGxfc2luZ2xlX3ZhbHVlKHNlbGYsIGRpZV90eXBlOiBzdHIpOgogICAgICAgIGlm"
    "IGRpZV90eXBlID09ICJkJSI6CiAgICAgICAgICAgIHRlbnMgPSByYW5kb20ucmFuZGludCgwLCA5KSAqIDEwCiAgICAgICAgICAg"
    "IHJldHVybiB0ZW5zLCAoIjAwIiBpZiB0ZW5zID09IDAgZWxzZSBzdHIodGVucykpCiAgICAgICAgc2lkZXMgPSBpbnQoZGllX3R5"
    "cGUucmVwbGFjZSgiZCIsICIiKSkKICAgICAgICB2YWwgPSByYW5kb20ucmFuZGludCgxLCBzaWRlcykKICAgICAgICByZXR1cm4g"
    "dmFsLCBzdHIodmFsKQoKICAgIGRlZiBfcm9sbF9wb29sX2RhdGEoc2VsZiwgcG9vbDogZGljdFtzdHIsIGludF0sIG1vZGlmaWVy"
    "OiBpbnQsIGxhYmVsOiBzdHIsIHJ1bGVfaWQ6IHN0ciA9ICIiKSAtPiBkaWN0OgogICAgICAgIGdyb3VwZWRfbnVtZXJpYzogZGlj"
    "dFtzdHIsIGxpc3RbaW50XV0gPSB7fQogICAgICAgIGdyb3VwZWRfZGlzcGxheTogZGljdFtzdHIsIGxpc3Rbc3RyXV0gPSB7fQog"
    "ICAgICAgIHN1YnRvdGFsID0gMAogICAgICAgIHVzZWRfcG9vbCA9IGRpY3QocG9vbCkKCiAgICAgICAgaWYgcnVsZV9pZCBhbmQg"
    "cnVsZV9pZCBpbiBzZWxmLnJ1bGVfZGVmaW5pdGlvbnMgYW5kIChub3QgcG9vbCBvciBsZW4oW2sgZm9yIGssIHYgaW4gcG9vbC5p"
    "dGVtcygpIGlmIHYgPiAwXSkgPT0gMSk6CiAgICAgICAgICAgIHJ1bGUgPSBzZWxmLnJ1bGVfZGVmaW5pdGlvbnMuZ2V0KHJ1bGVf"
    "aWQsIHt9KQogICAgICAgICAgICBzaWRlcyA9IGludChydWxlLmdldCgiZGljZV9zaWRlcyIsIDYpKQogICAgICAgICAgICBjb3Vu"
    "dCA9IGludChydWxlLmdldCgiZGljZV9jb3VudCIsIDEpKQogICAgICAgICAgICBkaWUgPSBmImR7c2lkZXN9IgogICAgICAgICAg"
    "ICB1c2VkX3Bvb2wgPSB7ZGllOiBjb3VudH0KICAgICAgICAgICAgcmF3ID0gW3JhbmRvbS5yYW5kaW50KDEsIHNpZGVzKSBmb3Ig"
    "XyBpbiByYW5nZShjb3VudCldCiAgICAgICAgICAgIGRyb3BfbG93ID0gaW50KHJ1bGUuZ2V0KCJkcm9wX2xvd2VzdF9jb3VudCIs"
    "IDApIG9yIDApCiAgICAgICAgICAgIGRyb3BfaGlnaCA9IGludChydWxlLmdldCgiZHJvcF9oaWdoZXN0X2NvdW50IiwgMCkgb3Ig"
    "MCkKICAgICAgICAgICAga2VwdCA9IGxpc3QocmF3KQogICAgICAgICAgICBpZiBkcm9wX2xvdyA+IDA6CiAgICAgICAgICAgICAg"
    "ICBrZXB0ID0gc29ydGVkKGtlcHQpW2Ryb3BfbG93Ol0KICAgICAgICAgICAgaWYgZHJvcF9oaWdoID4gMDoKICAgICAgICAgICAg"
    "ICAgIGtlcHQgPSBzb3J0ZWQoa2VwdClbOi1kcm9wX2hpZ2hdIGlmIGRyb3BfaGlnaCA8IGxlbihrZXB0KSBlbHNlIFtdCiAgICAg"
    "ICAgICAgIGdyb3VwZWRfbnVtZXJpY1tkaWVdID0gcmF3CiAgICAgICAgICAgIGdyb3VwZWRfZGlzcGxheVtkaWVdID0gW3N0cih2"
    "KSBmb3IgdiBpbiByYXddCiAgICAgICAgICAgIHN1YnRvdGFsID0gc3VtKGtlcHQpCiAgICAgICAgZWxzZToKICAgICAgICAgICAg"
    "Zm9yIGRpZSBpbiBzZWxmLlRSQVlfT1JERVI6CiAgICAgICAgICAgICAgICBxdHkgPSBpbnQocG9vbC5nZXQoZGllLCAwKSBvciAw"
    "KQogICAgICAgICAgICAgICAgaWYgcXR5IDw9IDA6CiAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgICAg"
    "IGdyb3VwZWRfbnVtZXJpY1tkaWVdID0gW10KICAgICAgICAgICAgICAgIGdyb3VwZWRfZGlzcGxheVtkaWVdID0gW10KICAgICAg"
    "ICAgICAgICAgIGZvciBfIGluIHJhbmdlKHF0eSk6CiAgICAgICAgICAgICAgICAgICAgbnVtLCBkaXNwID0gc2VsZi5fcm9sbF9z"
    "aW5nbGVfdmFsdWUoZGllKQogICAgICAgICAgICAgICAgICAgIGdyb3VwZWRfbnVtZXJpY1tkaWVdLmFwcGVuZChudW0pCiAgICAg"
    "ICAgICAgICAgICAgICAgZ3JvdXBlZF9kaXNwbGF5W2RpZV0uYXBwZW5kKGRpc3ApCiAgICAgICAgICAgICAgICAgICAgc3VidG90"
    "YWwgKz0gaW50KG51bSkKCiAgICAgICAgdG90YWwgPSBzdWJ0b3RhbCArIGludChtb2RpZmllcikKICAgICAgICB0cyA9IGRhdGV0"
    "aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUyIpCiAgICAgICAgZXhwciA9IHNlbGYuX3Bvb2xfZXhwcmVzc2lvbih1c2VkX3Bv"
    "b2wpCiAgICAgICAgaWYgcnVsZV9pZDoKICAgICAgICAgICAgcnVsZV9uYW1lID0gc2VsZi5ydWxlX2RlZmluaXRpb25zLmdldChy"
    "dWxlX2lkLCB7fSkuZ2V0KCJuYW1lIiwgcnVsZV9pZCkKICAgICAgICAgICAgZXhwciA9IGYie2V4cHJ9ICh7cnVsZV9uYW1lfSki"
    "CgogICAgICAgIGV2ZW50ID0gewogICAgICAgICAgICAiaWQiOiBmInJvbGxfe3V1aWQudXVpZDQoKS5oZXhbOjEyXX0iLAogICAg"
    "ICAgICAgICAidGltZXN0YW1wIjogdHMsCiAgICAgICAgICAgICJsYWJlbCI6IGxhYmVsLAogICAgICAgICAgICAicG9vbCI6IHVz"
    "ZWRfcG9vbCwKICAgICAgICAgICAgImdyb3VwZWRfcmF3IjogZ3JvdXBlZF9udW1lcmljLAogICAgICAgICAgICAiZ3JvdXBlZF9y"
    "YXdfZGlzcGxheSI6IGdyb3VwZWRfZGlzcGxheSwKICAgICAgICAgICAgInN1YnRvdGFsIjogc3VidG90YWwsCiAgICAgICAgICAg"
    "ICJtb2RpZmllciI6IGludChtb2RpZmllciksCiAgICAgICAgICAgICJmaW5hbF90b3RhbCI6IGludCh0b3RhbCksCiAgICAgICAg"
    "ICAgICJleHByZXNzaW9uIjogZXhwciwKICAgICAgICAgICAgInNvdXJjZSI6ICJkaWNlX3JvbGxlciIsCiAgICAgICAgICAgICJy"
    "dWxlX2lkIjogcnVsZV9pZCBvciBOb25lLAogICAgICAgIH0KICAgICAgICByZXR1cm4gZXZlbnQKCiAgICBkZWYgX2FkZF9kaWVf"
    "dG9fcG9vbChzZWxmLCBkaWVfdHlwZTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuY3VycmVudF9wb29sW2RpZV90eXBlXSA9"
    "IGludChzZWxmLmN1cnJlbnRfcG9vbC5nZXQoZGllX3R5cGUsIDApKSArIDEKICAgICAgICBzZWxmLl9yZWZyZXNoX3Bvb2xfZWRp"
    "dG9yKCkKICAgICAgICBzZWxmLmN1cnJlbnRfcmVzdWx0X2xibC5zZXRUZXh0KGYiQ3VycmVudCBQb29sOiB7c2VsZi5fcG9vbF9l"
    "eHByZXNzaW9uKCl9IikKCiAgICBkZWYgX2FkanVzdF9wb29sX2RpZShzZWxmLCBkaWVfdHlwZTogc3RyLCBkZWx0YTogaW50KSAt"
    "PiBOb25lOgogICAgICAgIG5ld192YWwgPSBpbnQoc2VsZi5jdXJyZW50X3Bvb2wuZ2V0KGRpZV90eXBlLCAwKSkgKyBpbnQoZGVs"
    "dGEpCiAgICAgICAgaWYgbmV3X3ZhbCA8PSAwOgogICAgICAgICAgICBzZWxmLmN1cnJlbnRfcG9vbC5wb3AoZGllX3R5cGUsIE5v"
    "bmUpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5jdXJyZW50X3Bvb2xbZGllX3R5cGVdID0gbmV3X3ZhbAogICAgICAg"
    "IHNlbGYuX3JlZnJlc2hfcG9vbF9lZGl0b3IoKQoKICAgIGRlZiBfcmVmcmVzaF9wb29sX2VkaXRvcihzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHdoaWxlIHNlbGYucG9vbF9lbnRyaWVzX2xheW91dC5jb3VudCgpOgogICAgICAgICAgICBpdGVtID0gc2VsZi5wb29s"
    "X2VudHJpZXNfbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICB3ID0gaXRlbS53aWRnZXQoKQogICAgICAgICAgICBpZiB3IGlz"
    "IG5vdCBOb25lOgogICAgICAgICAgICAgICAgdy5kZWxldGVMYXRlcigpCgogICAgICAgIGZvciBkaWUsIHF0eSBpbiBzZWxmLl9z"
    "b3J0ZWRfcG9vbF9pdGVtcygpOgogICAgICAgICAgICBib3ggPSBRRnJhbWUoKQogICAgICAgICAgICBib3guc2V0U3R5bGVTaGVl"
    "dChmImJhY2tncm91bmQ6IHtDX0JHM307IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDZweDsi"
    "KQogICAgICAgICAgICBsYXkgPSBRSEJveExheW91dChib3gpCiAgICAgICAgICAgIGxheS5zZXRDb250ZW50c01hcmdpbnMoNiwg"
    "NCwgNiwgNCkKICAgICAgICAgICAgbGF5LnNldFNwYWNpbmcoNCkKICAgICAgICAgICAgbGJsID0gUUxhYmVsKGYie2RpZX0geHtx"
    "dHl9IikKICAgICAgICAgICAgbWludXNfYnRuID0gUVB1c2hCdXR0b24oIuKIkiIpCiAgICAgICAgICAgIHBsdXNfYnRuID0gUVB1"
    "c2hCdXR0b24oIisiKQogICAgICAgICAgICBtaW51c19idG4uc2V0Rml4ZWRXaWR0aCgyNCkKICAgICAgICAgICAgcGx1c19idG4u"
    "c2V0Rml4ZWRXaWR0aCgyNCkKICAgICAgICAgICAgbWludXNfYnRuLmNsaWNrZWQuY29ubmVjdChsYW1iZGEgXz1GYWxzZSwgZD1k"
    "aWU6IHNlbGYuX2FkanVzdF9wb29sX2RpZShkLCAtMSkpCiAgICAgICAgICAgIHBsdXNfYnRuLmNsaWNrZWQuY29ubmVjdChsYW1i"
    "ZGEgXz1GYWxzZSwgZD1kaWU6IHNlbGYuX2FkanVzdF9wb29sX2RpZShkLCArMSkpCiAgICAgICAgICAgIGxheS5hZGRXaWRnZXQo"
    "bGJsKQogICAgICAgICAgICBsYXkuYWRkV2lkZ2V0KG1pbnVzX2J0bikKICAgICAgICAgICAgbGF5LmFkZFdpZGdldChwbHVzX2J0"
    "bikKICAgICAgICAgICAgc2VsZi5wb29sX2VudHJpZXNfbGF5b3V0LmFkZFdpZGdldChib3gpCgogICAgICAgIHNlbGYucG9vbF9l"
    "bnRyaWVzX2xheW91dC5hZGRTdHJldGNoKDEpCiAgICAgICAgc2VsZi5wb29sX2V4cHJfbGJsLnNldFRleHQoZiJQb29sOiB7c2Vs"
    "Zi5fcG9vbF9leHByZXNzaW9uKCl9IikKCiAgICBkZWYgX3F1aWNrX3JvbGxfc2luZ2xlX2RpZShzZWxmLCBkaWVfdHlwZTogc3Ry"
    "KSAtPiBOb25lOgogICAgICAgIGV2ZW50ID0gc2VsZi5fcm9sbF9wb29sX2RhdGEoe2RpZV90eXBlOiAxfSwgaW50KHNlbGYubW9k"
    "X3NwaW4udmFsdWUoKSksIHNlbGYubGFiZWxfZWRpdC50ZXh0KCkuc3RyaXAoKSwgc2VsZi5ydWxlX2NvbWJvLmN1cnJlbnREYXRh"
    "KCkgb3IgIiIpCiAgICAgICAgc2VsZi5fcmVjb3JkX3JvbGxfZXZlbnQoZXZlbnQpCgogICAgZGVmIF9yb2xsX2N1cnJlbnRfcG9v"
    "bChzZWxmKSAtPiBOb25lOgogICAgICAgIHBvb2wgPSBkaWN0KHNlbGYuY3VycmVudF9wb29sKQogICAgICAgIHJ1bGVfaWQgPSBz"
    "ZWxmLnJ1bGVfY29tYm8uY3VycmVudERhdGEoKSBvciAiIgogICAgICAgIGlmIG5vdCBwb29sIGFuZCBub3QgcnVsZV9pZDoKICAg"
    "ICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIkRpY2UgUm9sbGVyIiwgIkN1cnJlbnQgUG9vbCBpcyBlbXB0"
    "eS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBldmVudCA9IHNlbGYuX3JvbGxfcG9vbF9kYXRhKHBvb2wsIGludChzZWxm"
    "Lm1vZF9zcGluLnZhbHVlKCkpLCBzZWxmLmxhYmVsX2VkaXQudGV4dCgpLnN0cmlwKCksIHJ1bGVfaWQpCiAgICAgICAgc2VsZi5f"
    "cmVjb3JkX3JvbGxfZXZlbnQoZXZlbnQpCgogICAgZGVmIF9yZWNvcmRfcm9sbF9ldmVudChzZWxmLCBldmVudDogZGljdCkgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLnJvbGxfZXZlbnRzLmFwcGVuZChldmVudCkKICAgICAgICBzZWxmLmV2ZW50X2J5X2lkW2V2ZW50"
    "WyJpZCJdXSA9IGV2ZW50CiAgICAgICAgc2VsZi5jdXJyZW50X3JvbGxfaWRzID0gW2V2ZW50WyJpZCJdXQoKICAgICAgICBzZWxm"
    "Ll9yZXBsYWNlX2N1cnJlbnRfcm93cyhbZXZlbnRdKQogICAgICAgIHNlbGYuX2FwcGVuZF9oaXN0b3J5X3JvdyhldmVudCkKICAg"
    "ICAgICBzZWxmLl91cGRhdGVfZ3JhbmRfdG90YWwoKQogICAgICAgIHNlbGYuX3VwZGF0ZV9yZXN1bHRfZGlzcGxheShldmVudCkK"
    "ICAgICAgICBzZWxmLl90cmFja19jb21tb25fc2lnbmF0dXJlKGV2ZW50KQogICAgICAgIHNlbGYuX3BsYXlfcm9sbF9zb3VuZCgp"
    "CgogICAgZGVmIF9yZXBsYWNlX2N1cnJlbnRfcm93cyhzZWxmLCBldmVudHM6IGxpc3RbZGljdF0pIC0+IE5vbmU6CiAgICAgICAg"
    "c2VsZi5jdXJyZW50X3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGV2ZW50IGluIGV2ZW50czoKICAgICAgICAgICAg"
    "c2VsZi5fYXBwZW5kX3RhYmxlX3JvdyhzZWxmLmN1cnJlbnRfdGFibGUsIGV2ZW50KQoKICAgIGRlZiBfYXBwZW5kX2hpc3Rvcnlf"
    "cm93KHNlbGYsIGV2ZW50OiBkaWN0KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2FwcGVuZF90YWJsZV9yb3coc2VsZi5oaXN0b3J5"
    "X3RhYmxlLCBldmVudCkKICAgICAgICBzZWxmLmhpc3RvcnlfdGFibGUuc2Nyb2xsVG9Cb3R0b20oKQoKICAgIGRlZiBfZm9ybWF0"
    "X3JhdyhzZWxmLCBldmVudDogZGljdCkgLT4gc3RyOgogICAgICAgIGdyb3VwZWQgPSBldmVudC5nZXQoImdyb3VwZWRfcmF3X2Rp"
    "c3BsYXkiLCB7fSkgb3Ige30KICAgICAgICBiaXRzID0gW10KICAgICAgICBmb3IgZGllIGluIHNlbGYuVFJBWV9PUkRFUjoKICAg"
    "ICAgICAgICAgdmFscyA9IGdyb3VwZWQuZ2V0KGRpZSkKICAgICAgICAgICAgaWYgdmFsczoKICAgICAgICAgICAgICAgIGJpdHMu"
    "YXBwZW5kKGYie2RpZX06IHsnLCcuam9pbihzdHIodikgZm9yIHYgaW4gdmFscyl9IikKICAgICAgICByZXR1cm4gIiB8ICIuam9p"
    "bihiaXRzKQoKICAgIGRlZiBfYXBwZW5kX3RhYmxlX3JvdyhzZWxmLCB0YWJsZTogUVRhYmxlV2lkZ2V0LCBldmVudDogZGljdCkg"
    "LT4gTm9uZToKICAgICAgICByb3cgPSB0YWJsZS5yb3dDb3VudCgpCiAgICAgICAgdGFibGUuaW5zZXJ0Um93KHJvdykKCiAgICAg"
    "ICAgdHNfaXRlbSA9IFFUYWJsZVdpZGdldEl0ZW0oZXZlbnRbInRpbWVzdGFtcCJdKQogICAgICAgIHRzX2l0ZW0uc2V0RGF0YShR"
    "dC5JdGVtRGF0YVJvbGUuVXNlclJvbGUsIGV2ZW50WyJpZCJdKQogICAgICAgIHRhYmxlLnNldEl0ZW0ocm93LCAwLCB0c19pdGVt"
    "KQogICAgICAgIHRhYmxlLnNldEl0ZW0ocm93LCAxLCBRVGFibGVXaWRnZXRJdGVtKGV2ZW50LmdldCgibGFiZWwiLCAiIikpKQog"
    "ICAgICAgIHRhYmxlLnNldEl0ZW0ocm93LCAyLCBRVGFibGVXaWRnZXRJdGVtKGV2ZW50LmdldCgiZXhwcmVzc2lvbiIsICIiKSkp"
    "CiAgICAgICAgdGFibGUuc2V0SXRlbShyb3csIDMsIFFUYWJsZVdpZGdldEl0ZW0oc2VsZi5fZm9ybWF0X3JhdyhldmVudCkpKQoK"
    "ICAgICAgICBtb2Rfc3BpbiA9IFFTcGluQm94KCkKICAgICAgICBtb2Rfc3Bpbi5zZXRSYW5nZSgtOTk5LCA5OTkpCiAgICAgICAg"
    "bW9kX3NwaW4uc2V0VmFsdWUoaW50KGV2ZW50LmdldCgibW9kaWZpZXIiLCAwKSkpCiAgICAgICAgbW9kX3NwaW4udmFsdWVDaGFu"
    "Z2VkLmNvbm5lY3QobGFtYmRhIHZhbCwgZWlkPWV2ZW50WyJpZCJdOiBzZWxmLl9vbl9tb2RpZmllcl9jaGFuZ2VkKGVpZCwgdmFs"
    "KSkKICAgICAgICB0YWJsZS5zZXRDZWxsV2lkZ2V0KHJvdywgNCwgbW9kX3NwaW4pCgogICAgICAgIHRhYmxlLnNldEl0ZW0ocm93"
    "LCA1LCBRVGFibGVXaWRnZXRJdGVtKHN0cihldmVudC5nZXQoImZpbmFsX3RvdGFsIiwgMCkpKSkKCiAgICBkZWYgX3N5bmNfcm93"
    "X2J5X2V2ZW50X2lkKHNlbGYsIHRhYmxlOiBRVGFibGVXaWRnZXQsIGV2ZW50X2lkOiBzdHIsIGV2ZW50OiBkaWN0KSAtPiBOb25l"
    "OgogICAgICAgIGZvciByb3cgaW4gcmFuZ2UodGFibGUucm93Q291bnQoKSk6CiAgICAgICAgICAgIGl0ID0gdGFibGUuaXRlbShy"
    "b3csIDApCiAgICAgICAgICAgIGlmIGl0IGFuZCBpdC5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkgPT0gZXZlbnRfaWQ6"
    "CiAgICAgICAgICAgICAgICB0YWJsZS5zZXRJdGVtKHJvdywgNSwgUVRhYmxlV2lkZ2V0SXRlbShzdHIoZXZlbnQuZ2V0KCJmaW5h"
    "bF90b3RhbCIsIDApKSkpCiAgICAgICAgICAgICAgICB0YWJsZS5zZXRJdGVtKHJvdywgMywgUVRhYmxlV2lkZ2V0SXRlbShzZWxm"
    "Ll9mb3JtYXRfcmF3KGV2ZW50KSkpCiAgICAgICAgICAgICAgICBicmVhawoKICAgIGRlZiBfb25fbW9kaWZpZXJfY2hhbmdlZChz"
    "ZWxmLCBldmVudF9pZDogc3RyLCB2YWx1ZTogaW50KSAtPiBOb25lOgogICAgICAgIGV2dCA9IHNlbGYuZXZlbnRfYnlfaWQuZ2V0"
    "KGV2ZW50X2lkKQogICAgICAgIGlmIG5vdCBldnQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGV2dFsibW9kaWZpZXIiXSA9"
    "IGludCh2YWx1ZSkKICAgICAgICBldnRbImZpbmFsX3RvdGFsIl0gPSBpbnQoZXZ0LmdldCgic3VidG90YWwiLCAwKSkgKyBpbnQo"
    "dmFsdWUpCiAgICAgICAgc2VsZi5fc3luY19yb3dfYnlfZXZlbnRfaWQoc2VsZi5oaXN0b3J5X3RhYmxlLCBldmVudF9pZCwgZXZ0"
    "KQogICAgICAgIHNlbGYuX3N5bmNfcm93X2J5X2V2ZW50X2lkKHNlbGYuY3VycmVudF90YWJsZSwgZXZlbnRfaWQsIGV2dCkKICAg"
    "ICAgICBzZWxmLl91cGRhdGVfZ3JhbmRfdG90YWwoKQogICAgICAgIGlmIHNlbGYuY3VycmVudF9yb2xsX2lkcyBhbmQgc2VsZi5j"
    "dXJyZW50X3JvbGxfaWRzWzBdID09IGV2ZW50X2lkOgogICAgICAgICAgICBzZWxmLl91cGRhdGVfcmVzdWx0X2Rpc3BsYXkoZXZ0"
    "KQoKICAgIGRlZiBfdXBkYXRlX2dyYW5kX3RvdGFsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdG90YWwgPSBzdW0oaW50KGV2dC5n"
    "ZXQoImZpbmFsX3RvdGFsIiwgMCkpIGZvciBldnQgaW4gc2VsZi5yb2xsX2V2ZW50cykKICAgICAgICBzZWxmLmdyYW5kX3RvdGFs"
    "X2xibC5zZXRUZXh0KGYiR3JhbmQgVG90YWw6IHt0b3RhbH0iKQoKICAgIGRlZiBfdXBkYXRlX3Jlc3VsdF9kaXNwbGF5KHNlbGYs"
    "IGV2ZW50OiBkaWN0KSAtPiBOb25lOgogICAgICAgIGdyb3VwZWQgPSBldmVudC5nZXQoImdyb3VwZWRfcmF3X2Rpc3BsYXkiLCB7"
    "fSkgb3Ige30KICAgICAgICBsaW5lcyA9IFtdCiAgICAgICAgZm9yIGRpZSBpbiBzZWxmLlRSQVlfT1JERVI6CiAgICAgICAgICAg"
    "IHZhbHMgPSBncm91cGVkLmdldChkaWUpCiAgICAgICAgICAgIGlmIHZhbHM6CiAgICAgICAgICAgICAgICBsaW5lcy5hcHBlbmQo"
    "ZiJ7ZGllfSB4e2xlbih2YWxzKX0g4oaSIFt7JywnLmpvaW4oc3RyKHYpIGZvciB2IGluIHZhbHMpfV0iKQogICAgICAgIHJ1bGVf"
    "aWQgPSBldmVudC5nZXQoInJ1bGVfaWQiKQogICAgICAgIGlmIHJ1bGVfaWQ6CiAgICAgICAgICAgIHJ1bGVfbmFtZSA9IHNlbGYu"
    "cnVsZV9kZWZpbml0aW9ucy5nZXQocnVsZV9pZCwge30pLmdldCgibmFtZSIsIHJ1bGVfaWQpCiAgICAgICAgICAgIGxpbmVzLmFw"
    "cGVuZChmIlJ1bGU6IHtydWxlX25hbWV9IikKICAgICAgICBsaW5lcy5hcHBlbmQoZiJNb2RpZmllcjoge2ludChldmVudC5nZXQo"
    "J21vZGlmaWVyJywgMCkpOitkfSIpCiAgICAgICAgbGluZXMuYXBwZW5kKGYiVG90YWw6IHtldmVudC5nZXQoJ2ZpbmFsX3RvdGFs"
    "JywgMCl9IikKICAgICAgICBzZWxmLmN1cnJlbnRfcmVzdWx0X2xibC5zZXRUZXh0KCJcbiIuam9pbihsaW5lcykpCgoKICAgIGRl"
    "ZiBfc2F2ZV9wb29sKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuY3VycmVudF9wb29sOgogICAgICAgICAgICBR"
    "TWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiRGljZSBSb2xsZXIiLCAiQnVpbGQgYSBDdXJyZW50IFBvb2wgYmVmb3JlIHNh"
    "dmluZy4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBkZWZhdWx0X25hbWUgPSBzZWxmLmxhYmVsX2VkaXQudGV4dCgpLnN0"
    "cmlwKCkgb3Igc2VsZi5fcG9vbF9leHByZXNzaW9uKCkKICAgICAgICBuYW1lLCBvayA9IFFJbnB1dERpYWxvZy5nZXRUZXh0KHNl"
    "bGYsICJTYXZlIFBvb2wiLCAiU2F2ZWQgcm9sbCBuYW1lOiIsIHRleHQ9ZGVmYXVsdF9uYW1lKQogICAgICAgIGlmIG5vdCBvazoK"
    "ICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcGF5bG9hZCA9IHsKICAgICAgICAgICAgImlkIjogZiJzYXZlZF97dXVpZC51dWlk"
    "NCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICJuYW1lIjogbmFtZS5zdHJpcCgpIG9yIGRlZmF1bHRfbmFtZSwKICAgICAgICAg"
    "ICAgInBvb2wiOiBkaWN0KHNlbGYuY3VycmVudF9wb29sKSwKICAgICAgICAgICAgIm1vZGlmaWVyIjogaW50KHNlbGYubW9kX3Nw"
    "aW4udmFsdWUoKSksCiAgICAgICAgICAgICJydWxlX2lkIjogc2VsZi5ydWxlX2NvbWJvLmN1cnJlbnREYXRhKCkgb3IgTm9uZSwK"
    "ICAgICAgICAgICAgIm5vdGVzIjogIiIsCiAgICAgICAgICAgICJjYXRlZ29yeSI6ICJzYXZlZCIsCiAgICAgICAgfQogICAgICAg"
    "IHNlbGYuc2F2ZWRfcm9sbHMuYXBwZW5kKHBheWxvYWQpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9zYXZlZF9saXN0cygpCgogICAg"
    "ZGVmIF9yZWZyZXNoX3NhdmVkX2xpc3RzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zYXZlZF9saXN0LmNsZWFyKCkKICAg"
    "ICAgICBmb3IgaXRlbSBpbiBzZWxmLnNhdmVkX3JvbGxzOgogICAgICAgICAgICBleHByID0gc2VsZi5fcG9vbF9leHByZXNzaW9u"
    "KGl0ZW0uZ2V0KCJwb29sIiwge30pKQogICAgICAgICAgICB0eHQgPSBmIntpdGVtLmdldCgnbmFtZScpfSDigJQge2V4cHJ9IHtp"
    "bnQoaXRlbS5nZXQoJ21vZGlmaWVyJywgMCkpOitkfSIKICAgICAgICAgICAgbHcgPSBRTGlzdFdpZGdldEl0ZW0odHh0KQogICAg"
    "ICAgICAgICBsdy5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgaXRlbSkKICAgICAgICAgICAgc2VsZi5zYXZlZF9s"
    "aXN0LmFkZEl0ZW0obHcpCgogICAgICAgIHNlbGYuY29tbW9uX2xpc3QuY2xlYXIoKQogICAgICAgIHJhbmtlZCA9IHNvcnRlZChz"
    "ZWxmLmNvbW1vbl9yb2xscy52YWx1ZXMoKSwga2V5PWxhbWJkYSB4OiB4LmdldCgiY291bnQiLCAwKSwgcmV2ZXJzZT1UcnVlKQog"
    "ICAgICAgIGZvciBpdGVtIGluIHJhbmtlZDoKICAgICAgICAgICAgaWYgaW50KGl0ZW0uZ2V0KCJjb3VudCIsIDApKSA8IDI6CiAg"
    "ICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBleHByID0gc2VsZi5fcG9vbF9leHByZXNzaW9uKGl0ZW0uZ2V0KCJw"
    "b29sIiwge30pKQogICAgICAgICAgICB0eHQgPSBmIntleHByfSB7aW50KGl0ZW0uZ2V0KCdtb2RpZmllcicsIDApKTorZH0gKHh7"
    "aXRlbS5nZXQoJ2NvdW50JywgMCl9KSIKICAgICAgICAgICAgbHcgPSBRTGlzdFdpZGdldEl0ZW0odHh0KQogICAgICAgICAgICBs"
    "dy5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgaXRlbSkKICAgICAgICAgICAgc2VsZi5jb21tb25fbGlzdC5hZGRJ"
    "dGVtKGx3KQoKICAgIGRlZiBfdHJhY2tfY29tbW9uX3NpZ25hdHVyZShzZWxmLCBldmVudDogZGljdCkgLT4gTm9uZToKICAgICAg"
    "ICBzaWcgPSBzZWxmLl9ub3JtYWxpemVfcG9vbF9zaWduYXR1cmUoZXZlbnQuZ2V0KCJwb29sIiwge30pLCBpbnQoZXZlbnQuZ2V0"
    "KCJtb2RpZmllciIsIDApKSwgc3RyKGV2ZW50LmdldCgicnVsZV9pZCIpIG9yICIiKSkKICAgICAgICBpZiBzaWcgbm90IGluIHNl"
    "bGYuY29tbW9uX3JvbGxzOgogICAgICAgICAgICBzZWxmLmNvbW1vbl9yb2xsc1tzaWddID0gewogICAgICAgICAgICAgICAgInNp"
    "Z25hdHVyZSI6IHNpZywKICAgICAgICAgICAgICAgICJjb3VudCI6IDAsCiAgICAgICAgICAgICAgICAibmFtZSI6IGV2ZW50Lmdl"
    "dCgibGFiZWwiLCAiIikgb3Igc2lnLAogICAgICAgICAgICAgICAgInBvb2wiOiBkaWN0KGV2ZW50LmdldCgicG9vbCIsIHt9KSks"
    "CiAgICAgICAgICAgICAgICAibW9kaWZpZXIiOiBpbnQoZXZlbnQuZ2V0KCJtb2RpZmllciIsIDApKSwKICAgICAgICAgICAgICAg"
    "ICJydWxlX2lkIjogZXZlbnQuZ2V0KCJydWxlX2lkIiksCiAgICAgICAgICAgICAgICAibm90ZXMiOiAiIiwKICAgICAgICAgICAg"
    "ICAgICJjYXRlZ29yeSI6ICJjb21tb24iLAogICAgICAgICAgICB9CiAgICAgICAgc2VsZi5jb21tb25fcm9sbHNbc2lnXVsiY291"
    "bnQiXSA9IGludChzZWxmLmNvbW1vbl9yb2xsc1tzaWddLmdldCgiY291bnQiLCAwKSkgKyAxCiAgICAgICAgaWYgc2VsZi5jb21t"
    "b25fcm9sbHNbc2lnXVsiY291bnQiXSA+PSAzOgogICAgICAgICAgICBzZWxmLmNvbW1vbl9oaW50LnNldFRleHQoZiJTdWdnZXN0"
    "aW9uOiBwcm9tb3RlIHtzZWxmLl9wb29sX2V4cHJlc3Npb24oZXZlbnQuZ2V0KCdwb29sJywge30pKX0gdG8gU2F2ZWQuIikKICAg"
    "ICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBkZWYgX3J1bl9zYXZlZF9yb2xsKHNlbGYsIHBheWxvYWQ6IGRp"
    "Y3QgfCBOb25lKToKICAgICAgICBpZiBub3QgcGF5bG9hZDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZXZlbnQgPSBzZWxm"
    "Ll9yb2xsX3Bvb2xfZGF0YSgKICAgICAgICAgICAgZGljdChwYXlsb2FkLmdldCgicG9vbCIsIHt9KSksCiAgICAgICAgICAgIGlu"
    "dChwYXlsb2FkLmdldCgibW9kaWZpZXIiLCAwKSksCiAgICAgICAgICAgIHN0cihwYXlsb2FkLmdldCgibmFtZSIsICIiKSkuc3Ry"
    "aXAoKSwKICAgICAgICAgICAgc3RyKHBheWxvYWQuZ2V0KCJydWxlX2lkIikgb3IgIiIpLAogICAgICAgICkKICAgICAgICBzZWxm"
    "Ll9yZWNvcmRfcm9sbF9ldmVudChldmVudCkKCiAgICBkZWYgX2xvYWRfcGF5bG9hZF9pbnRvX3Bvb2woc2VsZiwgcGF5bG9hZDog"
    "ZGljdCB8IE5vbmUpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHBheWxvYWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNl"
    "bGYuY3VycmVudF9wb29sID0gZGljdChwYXlsb2FkLmdldCgicG9vbCIsIHt9KSkKICAgICAgICBzZWxmLm1vZF9zcGluLnNldFZh"
    "bHVlKGludChwYXlsb2FkLmdldCgibW9kaWZpZXIiLCAwKSkpCiAgICAgICAgc2VsZi5sYWJlbF9lZGl0LnNldFRleHQoc3RyKHBh"
    "eWxvYWQuZ2V0KCJuYW1lIiwgIiIpKSkKICAgICAgICByaWQgPSBwYXlsb2FkLmdldCgicnVsZV9pZCIpCiAgICAgICAgaWR4ID0g"
    "c2VsZi5ydWxlX2NvbWJvLmZpbmREYXRhKHJpZCBvciAiIikKICAgICAgICBpZiBpZHggPj0gMDoKICAgICAgICAgICAgc2VsZi5y"
    "dWxlX2NvbWJvLnNldEN1cnJlbnRJbmRleChpZHgpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9wb29sX2VkaXRvcigpCiAgICAgICAg"
    "c2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwuc2V0VGV4dChmIkN1cnJlbnQgUG9vbDoge3NlbGYuX3Bvb2xfZXhwcmVzc2lvbigpfSIp"
    "CgogICAgZGVmIF9ydW5fc2VsZWN0ZWRfc2F2ZWQoc2VsZik6CiAgICAgICAgaXRlbSA9IHNlbGYuc2F2ZWRfbGlzdC5jdXJyZW50"
    "SXRlbSgpCiAgICAgICAgc2VsZi5fcnVuX3NhdmVkX3JvbGwoaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkgaWYg"
    "aXRlbSBlbHNlIE5vbmUpCgogICAgZGVmIF9sb2FkX3NlbGVjdGVkX3NhdmVkKHNlbGYpOgogICAgICAgIGl0ZW0gPSBzZWxmLnNh"
    "dmVkX2xpc3QuY3VycmVudEl0ZW0oKQogICAgICAgIHBheWxvYWQgPSBpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xl"
    "KSBpZiBpdGVtIGVsc2UgTm9uZQogICAgICAgIGlmIG5vdCBwYXlsb2FkOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxm"
    "Ll9sb2FkX3BheWxvYWRfaW50b19wb29sKHBheWxvYWQpCgogICAgICAgIG5hbWUsIG9rID0gUUlucHV0RGlhbG9nLmdldFRleHQo"
    "c2VsZiwgIkVkaXQgU2F2ZWQgUm9sbCIsICJOYW1lOiIsIHRleHQ9c3RyKHBheWxvYWQuZ2V0KCJuYW1lIiwgIiIpKSkKICAgICAg"
    "ICBpZiBub3Qgb2s6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHBheWxvYWRbIm5hbWUiXSA9IG5hbWUuc3RyaXAoKSBvciBw"
    "YXlsb2FkLmdldCgibmFtZSIsICIiKQogICAgICAgIHBheWxvYWRbInBvb2wiXSA9IGRpY3Qoc2VsZi5jdXJyZW50X3Bvb2wpCiAg"
    "ICAgICAgcGF5bG9hZFsibW9kaWZpZXIiXSA9IGludChzZWxmLm1vZF9zcGluLnZhbHVlKCkpCiAgICAgICAgcGF5bG9hZFsicnVs"
    "ZV9pZCJdID0gc2VsZi5ydWxlX2NvbWJvLmN1cnJlbnREYXRhKCkgb3IgTm9uZQogICAgICAgIG5vdGVzLCBva19ub3RlcyA9IFFJ"
    "bnB1dERpYWxvZy5nZXRUZXh0KHNlbGYsICJFZGl0IFNhdmVkIFJvbGwiLCAiTm90ZXMgLyBjYXRlZ29yeToiLCB0ZXh0PXN0cihw"
    "YXlsb2FkLmdldCgibm90ZXMiLCAiIikpKQogICAgICAgIGlmIG9rX25vdGVzOgogICAgICAgICAgICBwYXlsb2FkWyJub3RlcyJd"
    "ID0gbm90ZXMKICAgICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBkZWYgX2RlbGV0ZV9zZWxlY3RlZF9zYXZl"
    "ZChzZWxmKToKICAgICAgICByb3cgPSBzZWxmLnNhdmVkX2xpc3QuY3VycmVudFJvdygpCiAgICAgICAgaWYgcm93IDwgMCBvciBy"
    "b3cgPj0gbGVuKHNlbGYuc2F2ZWRfcm9sbHMpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLnNhdmVkX3JvbGxzLnBv"
    "cChyb3cpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9zYXZlZF9saXN0cygpCgogICAgZGVmIF9wcm9tb3RlX3NlbGVjdGVkX2NvbW1v"
    "bihzZWxmKToKICAgICAgICBpdGVtID0gc2VsZi5jb21tb25fbGlzdC5jdXJyZW50SXRlbSgpCiAgICAgICAgcGF5bG9hZCA9IGl0"
    "ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpIGlmIGl0ZW0gZWxzZSBOb25lCiAgICAgICAgaWYgbm90IHBheWxvYWQ6"
    "CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHByb21vdGVkID0gewogICAgICAgICAgICAiaWQiOiBmInNhdmVkX3t1dWlkLnV1"
    "aWQ0KCkuaGV4WzoxMF19IiwKICAgICAgICAgICAgIm5hbWUiOiBwYXlsb2FkLmdldCgibmFtZSIpIG9yIHNlbGYuX3Bvb2xfZXhw"
    "cmVzc2lvbihwYXlsb2FkLmdldCgicG9vbCIsIHt9KSksCiAgICAgICAgICAgICJwb29sIjogZGljdChwYXlsb2FkLmdldCgicG9v"
    "bCIsIHt9KSksCiAgICAgICAgICAgICJtb2RpZmllciI6IGludChwYXlsb2FkLmdldCgibW9kaWZpZXIiLCAwKSksCiAgICAgICAg"
    "ICAgICJydWxlX2lkIjogcGF5bG9hZC5nZXQoInJ1bGVfaWQiKSwKICAgICAgICAgICAgIm5vdGVzIjogcGF5bG9hZC5nZXQoIm5v"
    "dGVzIiwgIiIpLAogICAgICAgICAgICAiY2F0ZWdvcnkiOiAic2F2ZWQiLAogICAgICAgIH0KICAgICAgICBzZWxmLnNhdmVkX3Jv"
    "bGxzLmFwcGVuZChwcm9tb3RlZCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBkZWYgX2Rpc21pc3Nf"
    "c2VsZWN0ZWRfY29tbW9uKHNlbGYpOgogICAgICAgIGl0ZW0gPSBzZWxmLmNvbW1vbl9saXN0LmN1cnJlbnRJdGVtKCkKICAgICAg"
    "ICBwYXlsb2FkID0gaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkgaWYgaXRlbSBlbHNlIE5vbmUKICAgICAgICBp"
    "ZiBub3QgcGF5bG9hZDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2lnID0gcGF5bG9hZC5nZXQoInNpZ25hdHVyZSIpCiAg"
    "ICAgICAgaWYgc2lnIGluIHNlbGYuY29tbW9uX3JvbGxzOgogICAgICAgICAgICBzZWxmLmNvbW1vbl9yb2xscy5wb3Aoc2lnLCBO"
    "b25lKQogICAgICAgIHNlbGYuX3JlZnJlc2hfc2F2ZWRfbGlzdHMoKQoKICAgIGRlZiBfcmVzZXRfcG9vbChzZWxmKToKICAgICAg"
    "ICBzZWxmLmN1cnJlbnRfcG9vbCA9IHt9CiAgICAgICAgc2VsZi5tb2Rfc3Bpbi5zZXRWYWx1ZSgwKQogICAgICAgIHNlbGYubGFi"
    "ZWxfZWRpdC5jbGVhcigpCiAgICAgICAgc2VsZi5ydWxlX2NvbWJvLnNldEN1cnJlbnRJbmRleCgwKQogICAgICAgIHNlbGYuX3Jl"
    "ZnJlc2hfcG9vbF9lZGl0b3IoKQogICAgICAgIHNlbGYuY3VycmVudF9yZXN1bHRfbGJsLnNldFRleHQoIk5vIHJvbGwgeWV0LiIp"
    "CgogICAgZGVmIF9jbGVhcl9oaXN0b3J5KHNlbGYpOgogICAgICAgIHNlbGYucm9sbF9ldmVudHMuY2xlYXIoKQogICAgICAgIHNl"
    "bGYuZXZlbnRfYnlfaWQuY2xlYXIoKQogICAgICAgIHNlbGYuY3VycmVudF9yb2xsX2lkcyA9IFtdCiAgICAgICAgc2VsZi5oaXN0"
    "b3J5X3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgc2VsZi5jdXJyZW50X3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAg"
    "c2VsZi5fdXBkYXRlX2dyYW5kX3RvdGFsKCkKICAgICAgICBzZWxmLmN1cnJlbnRfcmVzdWx0X2xibC5zZXRUZXh0KCJObyByb2xs"
    "IHlldC4iKQoKICAgIGRlZiBfZXZlbnRfZnJvbV90YWJsZV9wb3NpdGlvbihzZWxmLCB0YWJsZTogUVRhYmxlV2lkZ2V0LCBwb3Mp"
    "IC0+IGRpY3QgfCBOb25lOgogICAgICAgIGl0ZW0gPSB0YWJsZS5pdGVtQXQocG9zKQogICAgICAgIGlmIG5vdCBpdGVtOgogICAg"
    "ICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIHJvdyA9IGl0ZW0ucm93KCkKICAgICAgICB0c19pdGVtID0gdGFibGUuaXRlbShy"
    "b3csIDApCiAgICAgICAgaWYgbm90IHRzX2l0ZW06CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgZWlkID0gdHNfaXRl"
    "bS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICByZXR1cm4gc2VsZi5ldmVudF9ieV9pZC5nZXQoZWlkKQoK"
    "ICAgIGRlZiBfc2hvd19yb2xsX2NvbnRleHRfbWVudShzZWxmLCB0YWJsZTogUVRhYmxlV2lkZ2V0LCBwb3MpIC0+IE5vbmU6CiAg"
    "ICAgICAgZXZ0ID0gc2VsZi5fZXZlbnRfZnJvbV90YWJsZV9wb3NpdGlvbih0YWJsZSwgcG9zKQogICAgICAgIGlmIG5vdCBldnQ6"
    "CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGZyb20gUHlTaWRlNi5RdFdpZGdldHMgaW1wb3J0IFFNZW51CiAgICAgICAgbWVu"
    "dSA9IFFNZW51KHNlbGYpCiAgICAgICAgYWN0X3NlbmQgPSBtZW51LmFkZEFjdGlvbigiU2VuZCB0byBQcm9tcHQiKQogICAgICAg"
    "IGNob3NlbiA9IG1lbnUuZXhlYyh0YWJsZS52aWV3cG9ydCgpLm1hcFRvR2xvYmFsKHBvcykpCiAgICAgICAgaWYgY2hvc2VuID09"
    "IGFjdF9zZW5kOgogICAgICAgICAgICBzZWxmLl9zZW5kX2V2ZW50X3RvX3Byb21wdChldnQpCgogICAgZGVmIF9mb3JtYXRfZXZl"
    "bnRfZm9yX3Byb21wdChzZWxmLCBldmVudDogZGljdCkgLT4gc3RyOgogICAgICAgIGxhYmVsID0gKGV2ZW50LmdldCgibGFiZWwi"
    "KSBvciAiUm9sbCIpLnN0cmlwKCkKICAgICAgICBncm91cGVkID0gZXZlbnQuZ2V0KCJncm91cGVkX3Jhd19kaXNwbGF5Iiwge30p"
    "IG9yIHt9CiAgICAgICAgc2VnbWVudHMgPSBbXQogICAgICAgIGZvciBkaWUgaW4gc2VsZi5UUkFZX09SREVSOgogICAgICAgICAg"
    "ICB2YWxzID0gZ3JvdXBlZC5nZXQoZGllKQogICAgICAgICAgICBpZiB2YWxzOgogICAgICAgICAgICAgICAgc2VnbWVudHMuYXBw"
    "ZW5kKGYie2RpZX0gcm9sbGVkIHsnLCcuam9pbihzdHIodikgZm9yIHYgaW4gdmFscyl9IikKICAgICAgICBtb2QgPSBpbnQoZXZl"
    "bnQuZ2V0KCJtb2RpZmllciIsIDApKQogICAgICAgIHRvdGFsID0gaW50KGV2ZW50LmdldCgiZmluYWxfdG90YWwiLCAwKSkKICAg"
    "ICAgICByZXR1cm4gZiJ7bGFiZWx9OiB7JzsgJy5qb2luKHNlZ21lbnRzKX07IG1vZGlmaWVyIHttb2Q6K2R9OyB0b3RhbCB7dG90"
    "YWx9IgoKICAgIGRlZiBfc2VuZF9ldmVudF90b19wcm9tcHQoc2VsZiwgZXZlbnQ6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgd2lu"
    "ZG93ID0gc2VsZi53aW5kb3coKQogICAgICAgIGlmIG5vdCB3aW5kb3cgb3Igbm90IGhhc2F0dHIod2luZG93LCAiX2lucHV0X2Zp"
    "ZWxkIik6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGxpbmUgPSBzZWxmLl9mb3JtYXRfZXZlbnRfZm9yX3Byb21wdChldmVu"
    "dCkKICAgICAgICB3aW5kb3cuX2lucHV0X2ZpZWxkLnNldFRleHQobGluZSkKICAgICAgICB3aW5kb3cuX2lucHV0X2ZpZWxkLnNl"
    "dEZvY3VzKCkKCiAgICBkZWYgX3BsYXlfcm9sbF9zb3VuZChzZWxmKToKICAgICAgICBpZiBub3QgV0lOU09VTkRfT0s6CiAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgd2luc291bmQuQmVlcCg4NDAsIDMwKQogICAgICAgICAgICB3"
    "aW5zb3VuZC5CZWVwKDYyMCwgMzUpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKIyDilIDilIAg"
    "TUFJTiBXSU5ET1cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEVjaG9EZWNrKFFNYWluV2lu"
    "ZG93KToKICAgICIiIgogICAgVGhlIG1haW4gRWNobyBEZWNrIHdpbmRvdy4KICAgIEFzc2VtYmxlcyBhbGwgd2lkZ2V0cywgY29u"
    "bmVjdHMgYWxsIHNpZ25hbHMsIG1hbmFnZXMgYWxsIHN0YXRlLgogICAgIiIiCgogICAgIyDilIDilIAgVG9ycG9yIHRocmVzaG9s"
    "ZHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBfRVhU"
    "RVJOQUxfVlJBTV9UT1JQT1JfR0IgICAgPSAxLjUgICAjIGV4dGVybmFsIFZSQU0gPiB0aGlzIOKGkiBjb25zaWRlciB0b3Jwb3IK"
    "ICAgIF9FWFRFUk5BTF9WUkFNX1dBS0VfR0IgICAgICA9IDAuOCAgICMgZXh0ZXJuYWwgVlJBTSA8IHRoaXMg4oaSIGNvbnNpZGVy"
    "IHdha2UKICAgIF9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTICAgICA9IDYgICAgICMgNiDDlyA1cyA9IDMwIHNlY29uZHMgc3VzdGFp"
    "bmVkCiAgICBfV0FLRV9TVVNUQUlORURfVElDS1MgICAgICAgPSAxMiAgICAjIDYwIHNlY29uZHMgc3VzdGFpbmVkIGxvdyBwcmVz"
    "c3VyZQoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKCiAgICAgICAgIyDilIDilIAg"
    "Q29yZSBzdGF0ZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICBzZWxmLl9zdGF0dXMgICAgICAgICAgICAgID0gIk9GRkxJTkUiCiAgICAgICAgc2VsZi5fc2Vzc2lv"
    "bl9zdGFydCAgICAgICA9IHRpbWUudGltZSgpCiAgICAgICAgc2VsZi5fdG9rZW5fY291bnQgICAgICAgICA9IDAKICAgICAgICBz"
    "ZWxmLl9mYWNlX2xvY2tlZCAgICAgICAgID0gRmFsc2UKICAgICAgICBzZWxmLl9ibGlua19zdGF0ZSAgICAgICAgID0gVHJ1ZQog"
    "ICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCAgICAgICAgPSBGYWxzZQogICAgICAgIHNlbGYuX3Nlc3Npb25faWQgICAgICAgICAg"
    "PSBmInNlc3Npb25fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9IgogICAgICAgIHNlbGYuX2FjdGl2"
    "ZV90aHJlYWRzOiBsaXN0ID0gW10gICMga2VlcCByZWZzIHRvIHByZXZlbnQgR0Mgd2hpbGUgcnVubmluZwogICAgICAgIHNlbGYu"
    "X2ZpcnN0X3Rva2VuOiBib29sID0gVHJ1ZSAgICMgd3JpdGUgc3BlYWtlciBsYWJlbCBiZWZvcmUgZmlyc3Qgc3RyZWFtaW5nIHRv"
    "a2VuCgogICAgICAgICMgVG9ycG9yIC8gVlJBTSB0cmFja2luZwogICAgICAgIHNlbGYuX3RvcnBvcl9zdGF0ZSAgICAgICAgPSAi"
    "QVdBS0UiCiAgICAgICAgc2VsZi5fZGVja192cmFtX2Jhc2UgID0gMC4wICAgIyBiYXNlbGluZSBWUkFNIGFmdGVyIG1vZGVsIGxv"
    "YWQKICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMCAgICAgIyBzdXN0YWluZWQgcHJlc3N1cmUgY291bnRlcgog"
    "ICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICAgPSAwICAgICAjIHN1c3RhaW5lZCByZWxpZWYgY291bnRlcgogICAgICAg"
    "IHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyA9IDAKICAgICAgICBzZWxmLl90b3Jwb3Jfc2luY2UgICAgICAgID0gTm9uZSAg"
    "IyBkYXRldGltZSB3aGVuIHRvcnBvciBiZWdhbgogICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiAgPSAiIiAgICMgZm9y"
    "bWF0dGVkIGR1cmF0aW9uIHN0cmluZwoKICAgICAgICAjIOKUgOKUgCBNYW5hZ2VycyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9tZW1vcnkg"
    "ICA9IE1lbW9yeU1hbmFnZXIoKQogICAgICAgIHNlbGYuX3Nlc3Npb25zID0gU2Vzc2lvbk1hbmFnZXIoKQogICAgICAgIHNlbGYu"
    "X2xlc3NvbnMgID0gTGVzc29uc0xlYXJuZWREQigpCiAgICAgICAgc2VsZi5fdGFza3MgICAgPSBUYXNrTWFuYWdlcigpCiAgICAg"
    "ICAgc2VsZi5fcmVjb3Jkc19jYWNoZTogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fcmVjb3Jkc19pbml0aWFsaXplZCA9"
    "IEZhbHNlCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jdXJyZW50X2ZvbGRlcl9pZCA9ICJyb290IgogICAgICAgIHNlbGYuX2dvb2ds"
    "ZV9hdXRoX3JlYWR5ID0gRmFsc2UKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lcjogT3B0aW9uYWxbUVRpbWVyXSA9"
    "IE5vbmUKICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyOiBPcHRpb25hbFtRVGltZXJdID0gTm9uZQog"
    "ICAgICAgIHNlbGYuX3JlY29yZHNfdGFiX2luZGV4ID0gLTEKICAgICAgICBzZWxmLl90YXNrc190YWJfaW5kZXggPSAtMQogICAg"
    "ICAgIHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPSAibmV4"
    "dF8zX21vbnRocyIKCiAgICAgICAgIyDilIDilIAgR29vZ2xlIFNlcnZpY2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgSW5zdGFudGlhdGUgc2VydmljZSB3cmFwcGVycyB1cC1mcm9u"
    "dDsgYXV0aCBpcyBmb3JjZWQgbGF0ZXIKICAgICAgICAjIGZyb20gbWFpbigpIGFmdGVyIHdpbmRvdy5zaG93KCkgd2hlbiB0aGUg"
    "ZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgICAgIGdfY3JlZHNfcGF0aCA9IFBhdGgoQ0ZHLmdldCgiZ29vZ2xlIiwge30pLmdl"
    "dCgKICAgICAgICAgICAgImNyZWRlbnRpYWxzIiwKICAgICAgICAgICAgc3RyKGNmZ19wYXRoKCJnb29nbGUiKSAvICJnb29nbGVf"
    "Y3JlZGVudGlhbHMuanNvbiIpCiAgICAgICAgKSkKICAgICAgICBnX3Rva2VuX3BhdGggPSBQYXRoKENGRy5nZXQoImdvb2dsZSIs"
    "IHt9KS5nZXQoCiAgICAgICAgICAgICJ0b2tlbiIsCiAgICAgICAgICAgIHN0cihjZmdfcGF0aCgiZ29vZ2xlIikgLyAidG9rZW4u"
    "anNvbiIpCiAgICAgICAgKSkKICAgICAgICBzZWxmLl9nY2FsID0gR29vZ2xlQ2FsZW5kYXJTZXJ2aWNlKGdfY3JlZHNfcGF0aCwg"
    "Z190b2tlbl9wYXRoKQogICAgICAgIHNlbGYuX2dkcml2ZSA9IEdvb2dsZURvY3NEcml2ZVNlcnZpY2UoCiAgICAgICAgICAgIGdf"
    "Y3JlZHNfcGF0aCwKICAgICAgICAgICAgZ190b2tlbl9wYXRoLAogICAgICAgICAgICBsb2dnZXI9bGFtYmRhIG1zZywgbGV2ZWw9"
    "IklORk8iOiBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR0RSSVZFXSB7bXNnfSIsIGxldmVsKQogICAgICAgICkKCiAgICAgICAgIyBT"
    "ZWVkIExTTCBydWxlcyBvbiBmaXJzdCBydW4KICAgICAgICBzZWxmLl9sZXNzb25zLnNlZWRfbHNsX3J1bGVzKCkKCiAgICAgICAg"
    "IyBMb2FkIGVudGl0eSBzdGF0ZQogICAgICAgIHNlbGYuX3N0YXRlID0gc2VsZi5fbWVtb3J5LmxvYWRfc3RhdGUoKQogICAgICAg"
    "IHNlbGYuX3N0YXRlWyJzZXNzaW9uX2NvdW50Il0gPSBzZWxmLl9zdGF0ZS5nZXQoInNlc3Npb25fY291bnQiLDApICsgMQogICAg"
    "ICAgIHNlbGYuX3N0YXRlWyJsYXN0X3N0YXJ0dXAiXSAgPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICBzZWxmLl9tZW1vcnkuc2F2"
    "ZV9zdGF0ZShzZWxmLl9zdGF0ZSkKCiAgICAgICAgIyBCdWlsZCBhZGFwdG9yCiAgICAgICAgc2VsZi5fYWRhcHRvciA9IGJ1aWxk"
    "X2FkYXB0b3JfZnJvbV9jb25maWcoKQoKICAgICAgICAjIEZhY2UgdGltZXIgbWFuYWdlciAoc2V0IHVwIGFmdGVyIHdpZGdldHMg"
    "YnVpbHQpCiAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3I6IE9wdGlvbmFsW0ZhY2VUaW1lck1hbmFnZXJdID0gTm9uZQoKICAg"
    "ICAgICAjIOKUgOKUgCBCdWlsZCBVSSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLnNldFdpbmRvd1RpdGxlKEFQUF9OQU1FKQogICAgICAgIHNl"
    "bGYuc2V0TWluaW11bVNpemUoMTIwMCwgNzUwKQogICAgICAgIHNlbGYucmVzaXplKDEzNTAsIDg1MCkKICAgICAgICBzZWxmLnNl"
    "dFN0eWxlU2hlZXQoU1RZTEUpCgogICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKCiAgICAgICAgIyBGYWNlIHRpbWVyIG1hbmFnZXIg"
    "d2lyZWQgdG8gd2lkZ2V0cwogICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyID0gRmFjZVRpbWVyTWFuYWdlcigKICAgICAgICAg"
    "ICAgc2VsZi5fbWlycm9yLCBzZWxmLl9lbW90aW9uX2Jsb2NrCiAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBUaW1lcnMg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICAgICAgc2VsZi5fc3RhdHNfdGltZXIgPSBRVGltZXIoKQogICAgICAgIHNlbGYuX3N0YXRzX3RpbWVyLnRpbWVv"
    "dXQuY29ubmVjdChzZWxmLl91cGRhdGVfc3RhdHMpCiAgICAgICAgc2VsZi5fc3RhdHNfdGltZXIuc3RhcnQoMTAwMCkKCiAgICAg"
    "ICAgc2VsZi5fYmxpbmtfdGltZXIgPSBRVGltZXIoKQogICAgICAgIHNlbGYuX2JsaW5rX3RpbWVyLnRpbWVvdXQuY29ubmVjdChz"
    "ZWxmLl9ibGluaykKICAgICAgICBzZWxmLl9ibGlua190aW1lci5zdGFydCg4MDApCgogICAgICAgIHNlbGYuX3N0YXRlX3N0cmlw"
    "X3RpbWVyID0gUVRpbWVyKCkKICAgICAgICBpZiBBSV9TVEFURVNfRU5BQkxFRCBhbmQgc2VsZi5fZm9vdGVyX3N0cmlwIGlzIG5v"
    "dCBOb25lOgogICAgICAgICAgICBzZWxmLl9zdGF0ZV9zdHJpcF90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fZm9vdGVyX3N0"
    "cmlwLnJlZnJlc2gpCiAgICAgICAgICAgIHNlbGYuX3N0YXRlX3N0cmlwX3RpbWVyLnN0YXJ0KDYwMDAwKQoKICAgICAgICBzZWxm"
    "Ll9nb29nbGVfaW5ib3VuZF90aW1lciA9IFFUaW1lcihzZWxmKQogICAgICAgIHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyLnRp"
    "bWVvdXQuY29ubmVjdChzZWxmLl9vbl9nb29nbGVfaW5ib3VuZF90aW1lcl90aWNrKQogICAgICAgIHNlbGYuX2dvb2dsZV9pbmJv"
    "dW5kX3RpbWVyLnN0YXJ0KHNlbGYuX2dldF9nb29nbGVfcmVmcmVzaF9pbnRlcnZhbF9tcygpKQoKICAgICAgICBzZWxmLl9nb29n"
    "bGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAgICAgc2VsZi5fZ29vZ2xlX3JlY29yZHNfcmVmcmVz"
    "aF90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fb25fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lcl90aWNrKQogICAgICAg"
    "IHNlbGYuX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXIuc3RhcnQoc2VsZi5fZ2V0X2dvb2dsZV9yZWZyZXNoX2ludGVydmFs"
    "X21zKCkpCgogICAgICAgICMg4pSA4pSAIFNjaGVkdWxlciBhbmQgc3RhcnR1cCBkZWZlcnJlZCB1bnRpbCBhZnRlciB3aW5kb3cu"
    "c2hvdygpIOKUgOKUgOKUgAogICAgICAgICMgRG8gTk9UIGNhbGwgX3NldHVwX3NjaGVkdWxlcigpIG9yIF9zdGFydHVwX3NlcXVl"
    "bmNlKCkgaGVyZS4KICAgICAgICAjIEJvdGggYXJlIHRyaWdnZXJlZCB2aWEgUVRpbWVyLnNpbmdsZVNob3QgZnJvbSBtYWluKCkg"
    "YWZ0ZXIKICAgICAgICAjIHdpbmRvdy5zaG93KCkgYW5kIGFwcC5leGVjKCkgYmVnaW5zIHJ1bm5pbmcuCgogICAgIyDilIDilIAg"
    "VUkgQ09OU1RSVUNUSU9OIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9idWlsZF91aShzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IGNlbnRyYWwgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLnNldENlbnRyYWxXaWRnZXQoY2VudHJhbCkKICAgICAgICByb290ID0g"
    "UVZCb3hMYXlvdXQoY2VudHJhbCkKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJv"
    "b3Quc2V0U3BhY2luZyg0KQoKICAgICAgICAjIOKUgOKUgCBUaXRsZSBiYXIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5f"
    "YnVpbGRfdGl0bGVfYmFyKCkpCgogICAgICAgICMg4pSA4pSAIEJvZHk6IEpvdXJuYWwgfCBDaGF0IHwgU3lzdGVtcyDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgICAgICBib2R5ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJvZHkuc2V0U3BhY2luZyg0KQoKICAgICAgICAjIEpv"
    "dXJuYWwgc2lkZWJhciAobGVmdCkKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIgPSBKb3VybmFsU2lkZWJhcihzZWxmLl9z"
    "ZXNzaW9ucykKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5jb25uZWN0KAogICAg"
    "ICAgICAgICBzZWxmLl9sb2FkX2pvdXJuYWxfc2Vzc2lvbikKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2Vzc2lvbl9j"
    "bGVhcl9yZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5fY2xlYXJfam91cm5hbF9zZXNzaW9uKQogICAgICAgIGJv"
    "ZHkuYWRkV2lkZ2V0KHNlbGYuX2pvdXJuYWxfc2lkZWJhcikKCiAgICAgICAgIyBDaGF0IHBhbmVsIChjZW50ZXIsIGV4cGFuZHMp"
    "CiAgICAgICAgYm9keS5hZGRMYXlvdXQoc2VsZi5fYnVpbGRfY2hhdF9wYW5lbCgpLCAxKQoKICAgICAgICAjIFN5c3RlbXMgKHJp"
    "Z2h0KQogICAgICAgIGJvZHkuYWRkTGF5b3V0KHNlbGYuX2J1aWxkX3NwZWxsYm9va19wYW5lbCgpKQoKICAgICAgICByb290LmFk"
    "ZExheW91dChib2R5LCAxKQoKICAgICAgICAjIOKUgOKUgCBGb290ZXIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgZm9vdGVyID0gUUxhYmVs"
    "KAogICAgICAgICAgICBmIuKcpiB7QVBQX05BTUV9IOKAlCB2e0FQUF9WRVJTSU9OfSDinKYiCiAgICAgICAgKQogICAgICAgIGZv"
    "b3Rlci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBsZXR0"
    "ZXItc3BhY2luZzogMnB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAg"
    "KQogICAgICAgIGZvb3Rlci5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICByb290LmFk"
    "ZFdpZGdldChmb290ZXIpCgogICAgZGVmIF9idWlsZF90aXRsZV9iYXIoc2VsZikgLT4gUVdpZGdldDoKICAgICAgICBiYXIgPSBR"
    "V2lkZ2V0KCkKICAgICAgICBiYXIuc2V0Rml4ZWRIZWlnaHQoMzYpCiAgICAgICAgYmFyLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAg"
    "IGYiYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCiAgICAgICAgbGF5b3V0ID0gUUhCb3hMYXlvdXQoYmFyKQogICAgICAg"
    "IGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMTAsIDAsIDEwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDYpCgogICAg"
    "ICAgIHRpdGxlID0gUUxhYmVsKGYi4pymIHtBUFBfTkFNRX0iKQogICAgICAgIHRpdGxlLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDEzcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAg"
    "IGYibGV0dGVyLXNwYWNpbmc6IDJweDsgYm9yZGVyOiBub25lOyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAg"
    "ICAgICApCgogICAgICAgIHJ1bmVzID0gUUxhYmVsKFJVTkVTKQogICAgICAgIHJ1bmVzLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiY29sb3I6IHtDX0dPTERfRElNfTsgZm9udC1zaXplOiAxMHB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAg"
    "ICBydW5lcy5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKCiAgICAgICAgc2VsZi5zdGF0dXNfbGFi"
    "ZWwgPSBRTGFiZWwoZiLil4kge1VJX09GRkxJTkVfU1RBVFVTfSIpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQkxPT0R9OyBmb250LXNpemU6IDEycHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBi"
    "b3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50"
    "RmxhZy5BbGlnblJpZ2h0KQoKICAgICAgICAjIFN1c3BlbnNpb24gcGFuZWwKICAgICAgICBzZWxmLl90b3Jwb3JfcGFuZWwgPSBO"
    "b25lCiAgICAgICAgaWYgU1VTUEVOU0lPTl9FTkFCTEVEOgogICAgICAgICAgICBzZWxmLl90b3Jwb3JfcGFuZWwgPSBUb3Jwb3JQ"
    "YW5lbCgpCiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9wYW5lbC5zdGF0ZV9jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fdG9ycG9y"
    "X3N0YXRlX2NoYW5nZWQpCgogICAgICAgICMgSWRsZSB0b2dnbGUKICAgICAgICBpZGxlX2VuYWJsZWQgPSBib29sKENGRy5nZXQo"
    "InNldHRpbmdzIiwge30pLmdldCgiaWRsZV9lbmFibGVkIiwgRmFsc2UpKQogICAgICAgIHNlbGYuX2lkbGVfYnRuID0gUVB1c2hC"
    "dXR0b24oIklETEUgT04iIGlmIGlkbGVfZW5hYmxlZCBlbHNlICJJRExFIE9GRiIpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0"
    "Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0Q2hlY2thYmxlKFRydWUpCiAgICAgICAgc2VsZi5faWRs"
    "ZV9idG4uc2V0Q2hlY2tlZChpZGxlX2VuYWJsZWQpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAx"
    "cHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZv"
    "bnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIKICAgICAgICApCiAgICAgICAgc2VsZi5faWRsZV9idG4udG9nZ2xl"
    "ZC5jb25uZWN0KHNlbGYuX29uX2lkbGVfdG9nZ2xlZCkKCiAgICAgICAgIyBGUyAvIEJMIGJ1dHRvbnMKICAgICAgICBzZWxmLl9m"
    "c19idG4gPSBRUHVzaEJ1dHRvbigiRnVsbHNjcmVlbiIpCiAgICAgICAgc2VsZi5fYmxfYnRuID0gUVB1c2hCdXR0b24oIkJvcmRl"
    "cmxlc3MiKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4gPSBRUHVzaEJ1dHRvbigiRXhwb3J0IikKICAgICAgICBzZWxmLl9zaHV0"
    "ZG93bl9idG4gPSBRUHVzaEJ1dHRvbigiU2h1dGRvd24iKQogICAgICAgIGZvciBidG4gaW4gKHNlbGYuX2ZzX2J0biwgc2VsZi5f"
    "YmxfYnRuLCBzZWxmLl9leHBvcnRfYnRuKToKICAgICAgICAgICAgYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgICAgICBi"
    "dG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05f"
    "RElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4"
    "OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAg"
    "IHNlbGYuX2V4cG9ydF9idG4uc2V0Rml4ZWRXaWR0aCg0NikKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uc2V0Rml4ZWRIZWln"
    "aHQoMjIpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldEZpeGVkV2lkdGgoNjgpCiAgICAgICAgc2VsZi5fc2h1dGRvd25f"
    "YnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0JMT09EfTsgIgog"
    "ICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JMT09EfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgZiJm"
    "b250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2ZzX2J0bi5zZXRUb29sVGlwKCJG"
    "dWxsc2NyZWVuIChGMTEpIikKICAgICAgICBzZWxmLl9ibF9idG4uc2V0VG9vbFRpcCgiQm9yZGVybGVzcyAoRjEwKSIpCiAgICAg"
    "ICAgc2VsZi5fZXhwb3J0X2J0bi5zZXRUb29sVGlwKCJFeHBvcnQgY2hhdCBzZXNzaW9uIHRvIFRYVCBmaWxlIikKICAgICAgICBz"
    "ZWxmLl9zaHV0ZG93bl9idG4uc2V0VG9vbFRpcChmIkdyYWNlZnVsIHNodXRkb3duIOKAlCB7REVDS19OQU1FfSBzcGVha3MgdGhl"
    "aXIgbGFzdCB3b3JkcyIpCiAgICAgICAgc2VsZi5fZnNfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGVfZnVsbHNjcmVl"
    "bikKICAgICAgICBzZWxmLl9ibF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9ib3JkZXJsZXNzKQogICAgICAgIHNl"
    "bGYuX2V4cG9ydF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2V4cG9ydF9jaGF0KQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0"
    "bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5faW5pdGlhdGVfc2h1dGRvd25fZGlhbG9nKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0"
    "KHRpdGxlKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQocnVuZXMsIDEpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLnN0"
    "YXR1c19sYWJlbCkKICAgICAgICBsYXlvdXQuYWRkU3BhY2luZyg4KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZXhw"
    "b3J0X2J0bikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3NodXRkb3duX2J0bikKCiAgICAgICAgcmV0dXJuIGJhcgoK"
    "ICAgIGRlZiBfYnVpbGRfY2hhdF9wYW5lbChzZWxmKSAtPiBRVkJveExheW91dDoKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91"
    "dCgpCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBNYWluIHRhYiB3aWRnZXQg4oCUIHBlcnNvbmEgY2hh"
    "dCB0YWIgfCBTZWxmCiAgICAgICAgc2VsZi5fbWFpbl90YWJzID0gUVRhYldpZGdldCgpCiAgICAgICAgc2VsZi5fbWFpbl90YWJz"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUVRhYldpZGdldDo6cGFuZSB7eyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklN"
    "U09OX0RJTX07ICIKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgfX0iCiAgICAgICAgICAgIGYiUVRhYkJh"
    "cjo6dGFiIHt7IGJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJwYWRkaW5n"
    "OiA0cHggMTJweDsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVD"
    "S19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsgfX0iCiAgICAgICAgICAgIGYiUVRhYkJhcjo6dGFiOnNlbGVjdGVkIHt7"
    "IGJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlci1ib3R0b206IDJweCBz"
    "b2xpZCB7Q19DUklNU09OfTsgfX0iCiAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBUYWIgMDogUGVyc29uYSBjaGF0IHRhYiDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWFuY2Vfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgc2Vh"
    "bmNlX2xheW91dCA9IFFWQm94TGF5b3V0KHNlYW5jZV93aWRnZXQpCiAgICAgICAgc2VhbmNlX2xheW91dC5zZXRDb250ZW50c01h"
    "cmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWFuY2VfbGF5b3V0LnNldFNwYWNpbmcoMCkKICAgICAgICBzZWxmLl9jaGF0X2Rp"
    "c3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNl"
    "bGYuX2NoYXRfZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xv"
    "cjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RF"
    "Q0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEycHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHNlYW5jZV9s"
    "YXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2NoYXRfZGlzcGxheSkKICAgICAgICBzZWxmLl9tYWluX3RhYnMuYWRkVGFiKHNlYW5jZV93"
    "aWRnZXQsIGYi4p2nIHtVSV9DSEFUX1dJTkRPV30iKQoKICAgICAgICAjIOKUgOKUgCBUYWIgMTogU2VsZiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zZWxm"
    "X3RhYl93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmX2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX3NlbGZfdGFiX3dp"
    "ZGdldCkKICAgICAgICBzZWxmX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBzZWxmX2xheW91"
    "dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5fc2VsZl9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9zZWxm"
    "X2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiBu"
    "b25lOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMnB4OyBwYWRk"
    "aW5nOiA4cHg7IgogICAgICAgICkKICAgICAgICBzZWxmX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fc2VsZl9kaXNwbGF5LCAxKQog"
    "ICAgICAgIHNlbGYuX21haW5fdGFicy5hZGRUYWIoc2VsZi5fc2VsZl90YWJfd2lkZ2V0LCAi4peJIFNFTEYiKQoKICAgICAgICBs"
    "YXlvdXQuYWRkV2lkZ2V0KHNlbGYuX21haW5fdGFicywgMSkKCiAgICAgICAgIyDilIDilIAgQm90dG9tIHN0YXR1cy9yZXNvdXJj"
    "ZSBibG9jayByb3cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgIyBNYW5kYXRvcnkgcGVybWFuZW50IHN0cnVjdHVyZSBhY3Jvc3MgYWxsIHBlcnNv"
    "bmFzOgogICAgICAgICMgTUlSUk9SIHwgW0xPV0VSLU1JRERMRSBQRVJNQU5FTlQgRk9PVFBSSU5UXQogICAgICAgIGJsb2NrX3Jv"
    "dyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBibG9ja19yb3cuc2V0U3BhY2luZygyKQoKICAgICAgICAjIE1pcnJvciAobmV2ZXIg"
    "Y29sbGFwc2VzKQogICAgICAgIG1pcnJvcl93cmFwID0gUVdpZGdldCgpCiAgICAgICAgbXdfbGF5b3V0ID0gUVZCb3hMYXlvdXQo"
    "bWlycm9yX3dyYXApCiAgICAgICAgbXdfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG13X2xh"
    "eW91dC5zZXRTcGFjaW5nKDIpCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoZiLinacge1VJX01JUlJP"
    "Ul9MQUJFTH0iKSkKICAgICAgICBzZWxmLl9taXJyb3IgPSBNaXJyb3JXaWRnZXQoKQogICAgICAgIHNlbGYuX21pcnJvci5zZXRG"
    "aXhlZFNpemUoMTYwLCAxNjApCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9taXJyb3IpCiAgICAgICAgYmxvY2tf"
    "cm93LmFkZFdpZGdldChtaXJyb3Jfd3JhcCwgMCkKCiAgICAgICAgIyBNaWRkbGUgbG93ZXIgYmxvY2sga2VlcHMgYSBwZXJtYW5l"
    "bnQgZm9vdHByaW50OgogICAgICAgICMgbGVmdCA9IGNvbXBhY3Qgc3RhY2sgYXJlYSwgcmlnaHQgPSBmaXhlZCBleHBhbmRlZC1y"
    "b3cgc2xvdHMuCiAgICAgICAgbWlkZGxlX3dyYXAgPSBRV2lkZ2V0KCkKICAgICAgICBtaWRkbGVfbGF5b3V0ID0gUUhCb3hMYXlv"
    "dXQobWlkZGxlX3dyYXApCiAgICAgICAgbWlkZGxlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAg"
    "ICBtaWRkbGVfbGF5b3V0LnNldFNwYWNpbmcoMikKCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfd3JhcCA9IFFXaWRnZXQoKQog"
    "ICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX3dyYXAuc2V0TWluaW11bVdpZHRoKDEzMCkKICAgICAgICBzZWxmLl9sb3dlcl9zdGFj"
    "a193cmFwLnNldE1heGltdW1XaWR0aCgxMzApCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0ID0gUVZCb3hMYXlvdXQo"
    "c2VsZi5fbG93ZXJfc3RhY2tfd3JhcCkKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5z"
    "KDAsIDAsIDAsIDApCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBzZWxmLl9s"
    "b3dlcl9zdGFja193cmFwLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgbWlkZGxlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fbG93"
    "ZXJfc3RhY2tfd3JhcCwgMCkKCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93ID0gUVdpZGdldCgpCiAgICAgICAgc2Vs"
    "Zi5fbG93ZXJfZXhwYW5kZWRfcm93X2xheW91dCA9IFFHcmlkTGF5b3V0KHNlbGYuX2xvd2VyX2V4cGFuZGVkX3JvdykKICAgICAg"
    "ICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNl"
    "bGYuX2xvd2VyX2V4cGFuZGVkX3Jvd19sYXlvdXQuc2V0SG9yaXpvbnRhbFNwYWNpbmcoMikKICAgICAgICBzZWxmLl9sb3dlcl9l"
    "eHBhbmRlZF9yb3dfbGF5b3V0LnNldFZlcnRpY2FsU3BhY2luZygyKQogICAgICAgIG1pZGRsZV9sYXlvdXQuYWRkV2lkZ2V0KHNl"
    "bGYuX2xvd2VyX2V4cGFuZGVkX3JvdywgMSkKCiAgICAgICAgIyBFbW90aW9uIGJsb2NrIChjb2xsYXBzaWJsZSkKICAgICAgICBz"
    "ZWxmLl9lbW90aW9uX2Jsb2NrID0gRW1vdGlvbkJsb2NrKCkKICAgICAgICBzZWxmLl9lbW90aW9uX2Jsb2NrX3dyYXAgPSBDb2xs"
    "YXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfRU1PVElPTlNfTEFCRUx9Iiwgc2VsZi5fZW1vdGlvbl9ibG9jaywK"
    "ICAgICAgICAgICAgZXhwYW5kZWQ9VHJ1ZSwgbWluX3dpZHRoPTEzMCwgcmVzZXJ2ZV93aWR0aD1UcnVlCiAgICAgICAgKQoKICAg"
    "ICAgICAjIExlZnQgcmVzb3VyY2Ugb3JiIChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9sZWZ0X29yYiA9IFNwaGVyZVdpZGdl"
    "dCgKICAgICAgICAgICAgVUlfTEVGVF9PUkJfTEFCRUwsIENfQ1JJTVNPTiwgQ19DUklNU09OX0RJTQogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl9sZWZ0X29yYl93cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacge1VJX0xFRlRfT1JCX1RJ"
    "VExFfSIsIHNlbGYuX2xlZnRfb3JiLAogICAgICAgICAgICBtaW5fd2lkdGg9OTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAgICAg"
    "ICkKCiAgICAgICAgIyBDZW50ZXIgY3ljbGUgd2lkZ2V0IChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9jeWNsZV93aWRnZXQg"
    "PSBDeWNsZVdpZGdldCgpCiAgICAgICAgc2VsZi5fY3ljbGVfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2soCiAgICAgICAgICAgIGYi"
    "4p2nIHtVSV9DWUNMRV9USVRMRX0iLCBzZWxmLl9jeWNsZV93aWRnZXQsCiAgICAgICAgICAgIG1pbl93aWR0aD05MCwgcmVzZXJ2"
    "ZV93aWR0aD1UcnVlCiAgICAgICAgKQoKICAgICAgICAjIFJpZ2h0IHJlc291cmNlIG9yYiAoY29sbGFwc2libGUpCiAgICAgICAg"
    "c2VsZi5fcmlnaHRfb3JiID0gU3BoZXJlV2lkZ2V0KAogICAgICAgICAgICBVSV9SSUdIVF9PUkJfTEFCRUwsIENfUFVSUExFLCBD"
    "X1BVUlBMRV9ESU0KICAgICAgICApCiAgICAgICAgc2VsZi5fcmlnaHRfb3JiX3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAogICAg"
    "ICAgICAgICBmIuKdpyB7VUlfUklHSFRfT1JCX1RJVExFfSIsIHNlbGYuX3JpZ2h0X29yYiwKICAgICAgICAgICAgbWluX3dpZHRo"
    "PTkwLCByZXNlcnZlX3dpZHRoPVRydWUKICAgICAgICApCgogICAgICAgICMgRXNzZW5jZSAoMiBnYXVnZXMsIGNvbGxhcHNpYmxl"
    "KQogICAgICAgIGVzc2VuY2Vfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgZXNzZW5jZV9sYXlvdXQgPSBRVkJveExheW91dChl"
    "c3NlbmNlX3dpZGdldCkKICAgICAgICBlc3NlbmNlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAg"
    "ICBlc3NlbmNlX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5fZXNzZW5jZV9wcmltYXJ5X2dhdWdlICAgPSBHYXVn"
    "ZVdpZGdldChVSV9FU1NFTkNFX1BSSU1BUlksICAgIiUiLCAxMDAuMCwgQ19DUklNU09OKQogICAgICAgIHNlbGYuX2Vzc2VuY2Vf"
    "c2Vjb25kYXJ5X2dhdWdlID0gR2F1Z2VXaWRnZXQoVUlfRVNTRU5DRV9TRUNPTkRBUlksICIlIiwgMTAwLjAsIENfR1JFRU4pCiAg"
    "ICAgICAgZXNzZW5jZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2Vzc2VuY2VfcHJpbWFyeV9nYXVnZSkKICAgICAgICBlc3NlbmNl"
    "X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2UpCiAgICAgICAgc2VsZi5fZXNzZW5jZV93cmFw"
    "ID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacge1VJX0VTU0VOQ0VfVElUTEV9IiwgZXNzZW5jZV93aWRnZXQs"
    "CiAgICAgICAgICAgIG1pbl93aWR0aD0xMTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAgICAgICkKCiAgICAgICAgIyBFeHBhbmRl"
    "ZCByb3cgc2xvdHMgbXVzdCBzdGF5IGluIGNhbm9uaWNhbCB2aXN1YWwgb3JkZXIuCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5k"
    "ZWRfc2xvdF9vcmRlciA9IFsKICAgICAgICAgICAgImVtb3Rpb25zIiwgInByaW1hcnkiLCAiY3ljbGUiLCAic2Vjb25kYXJ5Iiwg"
    "ImVzc2VuY2UiCiAgICAgICAgXQogICAgICAgIHNlbGYuX2xvd2VyX2NvbXBhY3Rfc3RhY2tfb3JkZXIgPSBbCiAgICAgICAgICAg"
    "ICJjeWNsZSIsICJwcmltYXJ5IiwgInNlY29uZGFyeSIsICJlc3NlbmNlIiwgImVtb3Rpb25zIgogICAgICAgIF0KICAgICAgICBz"
    "ZWxmLl9sb3dlcl9tb2R1bGVfd3JhcHMgPSB7CiAgICAgICAgICAgICJlbW90aW9ucyI6IHNlbGYuX2Vtb3Rpb25fYmxvY2tfd3Jh"
    "cCwKICAgICAgICAgICAgInByaW1hcnkiOiBzZWxmLl9sZWZ0X29yYl93cmFwLAogICAgICAgICAgICAiY3ljbGUiOiBzZWxmLl9j"
    "eWNsZV93cmFwLAogICAgICAgICAgICAic2Vjb25kYXJ5Ijogc2VsZi5fcmlnaHRfb3JiX3dyYXAsCiAgICAgICAgICAgICJlc3Nl"
    "bmNlIjogc2VsZi5fZXNzZW5jZV93cmFwLAogICAgICAgIH0KCiAgICAgICAgc2VsZi5fbG93ZXJfcm93X3Nsb3RzID0ge30KICAg"
    "ICAgICBmb3IgY29sLCBrZXkgaW4gZW51bWVyYXRlKHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Nsb3Rfb3JkZXIpOgogICAgICAgICAg"
    "ICBzbG90ID0gUVdpZGdldCgpCiAgICAgICAgICAgIHNsb3RfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2xvdCkKICAgICAgICAgICAg"
    "c2xvdF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgICAgIHNsb3RfbGF5b3V0LnNldFNwYWNp"
    "bmcoMCkKICAgICAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93X2xheW91dC5hZGRXaWRnZXQoc2xvdCwgMCwgY29sKQog"
    "ICAgICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LnNldENvbHVtblN0cmV0Y2goY29sLCAxKQogICAgICAg"
    "ICAgICBzZWxmLl9sb3dlcl9yb3dfc2xvdHNba2V5XSA9IHNsb3RfbGF5b3V0CgogICAgICAgIGZvciB3cmFwIGluIHNlbGYuX2xv"
    "d2VyX21vZHVsZV93cmFwcy52YWx1ZXMoKToKICAgICAgICAgICAgd3JhcC50b2dnbGVkLmNvbm5lY3Qoc2VsZi5fcmVmcmVzaF9s"
    "b3dlcl9taWRkbGVfbGF5b3V0KQoKICAgICAgICBzZWxmLl9yZWZyZXNoX2xvd2VyX21pZGRsZV9sYXlvdXQoKQoKICAgICAgICBi"
    "bG9ja19yb3cuYWRkV2lkZ2V0KG1pZGRsZV93cmFwLCAxKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoYmxvY2tfcm93KQoKICAg"
    "ICAgICAjIEZvb3RlciBzdGF0ZSBzdHJpcCAoYmVsb3cgYmxvY2sgcm93IOKAlCBwZXJtYW5lbnQgVUkgc3RydWN0dXJlKQogICAg"
    "ICAgIHNlbGYuX2Zvb3Rlcl9zdHJpcCA9IEZvb3RlclN0cmlwV2lkZ2V0KCkKICAgICAgICBzZWxmLl9mb290ZXJfc3RyaXAuc2V0"
    "X2xhYmVsKFVJX0ZPT1RFUl9TVFJJUF9MQUJFTCkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2Zvb3Rlcl9zdHJpcCkK"
    "CiAgICAgICAgIyDilIDilIAgSW5wdXQgcm93IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGlucHV0X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBwcm9t"
    "cHRfc3ltID0gUUxhYmVsKCLinKYiKQogICAgICAgIHByb21wdF9zeW0uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xv"
    "cjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTZweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAg"
    "KQogICAgICAgIHByb21wdF9zeW0uc2V0Rml4ZWRXaWR0aCgyMCkKCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQgPSBRTGluZUVk"
    "aXQoKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dChVSV9JTlBVVF9QTEFDRUhPTERFUikKICAg"
    "ICAgICBzZWxmLl9pbnB1dF9maWVsZC5yZXR1cm5QcmVzc2VkLmNvbm5lY3Qoc2VsZi5fc2VuZF9tZXNzYWdlKQogICAgICAgIHNl"
    "bGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2UpCgogICAgICAgIHNlbGYuX3NlbmRfYnRuID0gUVB1c2hCdXR0b24oVUlf"
    "U0VORF9CVVRUT04pCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0Rml4ZWRXaWR0aCgxMTApCiAgICAgICAgc2VsZi5fc2VuZF9i"
    "dG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3NlbmRfbWVzc2FnZSkKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKEZh"
    "bHNlKQoKICAgICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHByb21wdF9zeW0pCiAgICAgICAgaW5wdXRfcm93LmFkZFdpZGdldChz"
    "ZWxmLl9pbnB1dF9maWVsZCkKICAgICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHNlbGYuX3NlbmRfYnRuKQogICAgICAgIGxheW91"
    "dC5hZGRMYXlvdXQoaW5wdXRfcm93KQoKICAgICAgICByZXR1cm4gbGF5b3V0CgogICAgZGVmIF9jbGVhcl9sYXlvdXRfd2lkZ2V0"
    "cyhzZWxmLCBsYXlvdXQ6IFFWQm94TGF5b3V0KSAtPiBOb25lOgogICAgICAgIHdoaWxlIGxheW91dC5jb3VudCgpOgogICAgICAg"
    "ICAgICBpdGVtID0gbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICB3aWRnZXQgPSBpdGVtLndpZGdldCgpCiAgICAgICAgICAg"
    "IGlmIHdpZGdldCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgIHdpZGdldC5zZXRQYXJlbnQoTm9uZSkKCiAgICBkZWYgX3Jl"
    "ZnJlc2hfbG93ZXJfbWlkZGxlX2xheW91dChzZWxmLCAqX2FyZ3MpIC0+IE5vbmU6CiAgICAgICAgY29sbGFwc2VkX2NvdW50ID0g"
    "MAoKICAgICAgICAjIFJlYnVpbGQgZXhwYW5kZWQgcm93IHNsb3RzIGluIGZpeGVkIGV4cGFuZGVkIG9yZGVyLgogICAgICAgIGZv"
    "ciBrZXkgaW4gc2VsZi5fbG93ZXJfZXhwYW5kZWRfc2xvdF9vcmRlcjoKICAgICAgICAgICAgc2xvdF9sYXlvdXQgPSBzZWxmLl9s"
    "b3dlcl9yb3dfc2xvdHNba2V5XQogICAgICAgICAgICBzZWxmLl9jbGVhcl9sYXlvdXRfd2lkZ2V0cyhzbG90X2xheW91dCkKICAg"
    "ICAgICAgICAgd3JhcCA9IHNlbGYuX2xvd2VyX21vZHVsZV93cmFwc1trZXldCiAgICAgICAgICAgIGlmIHdyYXAuaXNfZXhwYW5k"
    "ZWQoKToKICAgICAgICAgICAgICAgIHNsb3RfbGF5b3V0LmFkZFdpZGdldCh3cmFwKQogICAgICAgICAgICBlbHNlOgogICAgICAg"
    "ICAgICAgICAgY29sbGFwc2VkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgIHNsb3RfbGF5b3V0LmFkZFN0cmV0Y2goMSkKCiAg"
    "ICAgICAgIyBSZWJ1aWxkIGNvbXBhY3Qgc3RhY2sgaW4gY2Fub25pY2FsIGNvbXBhY3Qgb3JkZXIuCiAgICAgICAgc2VsZi5fY2xl"
    "YXJfbGF5b3V0X3dpZGdldHMoc2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0KQogICAgICAgIGZvciBrZXkgaW4gc2VsZi5fbG93ZXJf"
    "Y29tcGFjdF9zdGFja19vcmRlcjoKICAgICAgICAgICAgd3JhcCA9IHNlbGYuX2xvd2VyX21vZHVsZV93cmFwc1trZXldCiAgICAg"
    "ICAgICAgIGlmIG5vdCB3cmFwLmlzX2V4cGFuZGVkKCk6CiAgICAgICAgICAgICAgICBzZWxmLl9sb3dlcl9zdGFja19sYXlvdXQu"
    "YWRkV2lkZ2V0KHdyYXApCgogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX2xheW91dC5hZGRTdHJldGNoKDEpCiAgICAgICAgc2Vs"
    "Zi5fbG93ZXJfc3RhY2tfd3JhcC5zZXRWaXNpYmxlKGNvbGxhcHNlZF9jb3VudCA+IDApCgogICAgZGVmIF9idWlsZF9zcGVsbGJv"
    "b2tfcGFuZWwoc2VsZikgLT4gUVZCb3hMYXlvdXQ6CiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoKQogICAgICAgIGxheW91"
    "dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQogICAgICAgIGxheW91"
    "dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgU1lTVEVNUyIpKQoKICAgICAgICAjIFRhYiB3aWRnZXQKICAgICAgICBzZWxm"
    "Ll9zcGVsbF90YWJzID0gUVRhYldpZGdldCgpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5zZXRNaW5pbXVtV2lkdGgoMjgwKQog"
    "ICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuc2V0U2l6ZVBvbGljeSgKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5LkV4cGFu"
    "ZGluZywKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5LkV4cGFuZGluZwogICAgICAgICkKCiAgICAgICAgIyBCdWlsZCBE"
    "aWFnbm9zdGljc1RhYiBlYXJseSBzbyBzdGFydHVwIGxvZ3MgYXJlIHNhZmUgZXZlbiBiZWZvcmUKICAgICAgICAjIHRoZSBEaWFn"
    "bm9zdGljcyB0YWIgaXMgYXR0YWNoZWQgdG8gdGhlIHdpZGdldC4KICAgICAgICBzZWxmLl9kaWFnX3RhYiA9IERpYWdub3N0aWNz"
    "VGFiKCkKCiAgICAgICAgIyDilIDilIAgSW5zdHJ1bWVudHMgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2h3X3BhbmVsID0gSGFyZHdhcmVQYW5lbCgpCiAgICAgICAgc2Vs"
    "Zi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5faHdfcGFuZWwsICJJbnN0cnVtZW50cyIpCgogICAgICAgICMg4pSA4pSAIFJlY29y"
    "ZHMgdGFiIChyZWFsKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9y"
    "ZWNvcmRzX3RhYiA9IFJlY29yZHNUYWIoKQogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiX2luZGV4ID0gc2VsZi5fc3BlbGxfdGFi"
    "cy5hZGRUYWIoc2VsZi5fcmVjb3Jkc190YWIsICJSZWNvcmRzIikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltTUEVMTEJP"
    "T0tdIHJlYWwgUmVjb3Jkc1RhYiBhdHRhY2hlZC4iLCAiSU5GTyIpCgogICAgICAgICMg4pSA4pSAIFRhc2tzIHRhYiAocmVhbCkg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fdGFza3NfdGFi"
    "ID0gVGFza3NUYWIoCiAgICAgICAgICAgIHRhc2tzX3Byb3ZpZGVyPXNlbGYuX2ZpbHRlcmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeSwK"
    "ICAgICAgICAgICAgb25fYWRkX2VkaXRvcl9vcGVuPXNlbGYuX29wZW5fdGFza19lZGl0b3Jfd29ya3NwYWNlLAogICAgICAgICAg"
    "ICBvbl9jb21wbGV0ZV9zZWxlY3RlZD1zZWxmLl9jb21wbGV0ZV9zZWxlY3RlZF90YXNrLAogICAgICAgICAgICBvbl9jYW5jZWxf"
    "c2VsZWN0ZWQ9c2VsZi5fY2FuY2VsX3NlbGVjdGVkX3Rhc2ssCiAgICAgICAgICAgIG9uX3RvZ2dsZV9jb21wbGV0ZWQ9c2VsZi5f"
    "dG9nZ2xlX3Nob3dfY29tcGxldGVkX3Rhc2tzLAogICAgICAgICAgICBvbl9wdXJnZV9jb21wbGV0ZWQ9c2VsZi5fcHVyZ2VfY29t"
    "cGxldGVkX3Rhc2tzLAogICAgICAgICAgICBvbl9maWx0ZXJfY2hhbmdlZD1zZWxmLl9vbl90YXNrX2ZpbHRlcl9jaGFuZ2VkLAog"
    "ICAgICAgICAgICBvbl9lZGl0b3Jfc2F2ZT1zZWxmLl9zYXZlX3Rhc2tfZWRpdG9yX2dvb2dsZV9maXJzdCwKICAgICAgICAgICAg"
    "b25fZWRpdG9yX2NhbmNlbD1zZWxmLl9jYW5jZWxfdGFza19lZGl0b3Jfd29ya3NwYWNlLAogICAgICAgICAgICBkaWFnbm9zdGlj"
    "c19sb2dnZXI9c2VsZi5fZGlhZ190YWIubG9nLAogICAgICAgICkKICAgICAgICBzZWxmLl90YXNrc190YWIuc2V0X3Nob3dfY29t"
    "cGxldGVkKHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiX2luZGV4ID0gc2VsZi5fc3Bl"
    "bGxfdGFicy5hZGRUYWIoc2VsZi5fdGFza3NfdGFiLCAiVGFza3MiKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW1NQRUxM"
    "Qk9PS10gcmVhbCBUYXNrc1RhYiBhdHRhY2hlZC4iLCAiSU5GTyIpCgogICAgICAgICMg4pSA4pSAIFNMIFNjYW5zIHRhYiDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxm"
    "Ll9zbF9zY2FucyA9IFNMU2NhbnNUYWIoY2ZnX3BhdGgoInNsIikpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2Vs"
    "Zi5fc2xfc2NhbnMsICJTTCBTY2FucyIpCgogICAgICAgICMg4pSA4pSAIFNMIENvbW1hbmRzIHRhYiDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zbF9jb21tYW5kcyA9IFNMQ29t"
    "bWFuZHNUYWIoKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX3NsX2NvbW1hbmRzLCAiU0wgQ29tbWFuZHMi"
    "KQoKICAgICAgICAjIOKUgOKUgCBKb2IgVHJhY2tlciB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fam9iX3RyYWNrZXIgPSBKb2JUcmFja2VyVGFiKCkKICAgICAgICBzZWxm"
    "Ll9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9qb2JfdHJhY2tlciwgIkpvYiBUcmFja2VyIikKCiAgICAgICAgIyDilIDilIAgTGVz"
    "c29ucyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICAgICAgc2VsZi5fbGVzc29uc190YWIgPSBMZXNzb25zVGFiKHNlbGYuX2xlc3NvbnMpCiAgICAgICAgc2VsZi5fc3Bl"
    "bGxfdGFicy5hZGRUYWIoc2VsZi5fbGVzc29uc190YWIsICJMZXNzb25zIikKCiAgICAgICAgIyBTZWxmIHRhYiBpcyBub3cgaW4g"
    "dGhlIG1haW4gYXJlYSBhbG9uZ3NpZGUgdGhlIHBlcnNvbmEgY2hhdCB0YWIKICAgICAgICAjIEtlZXAgYSBTZWxmVGFiIGluc3Rh"
    "bmNlIGZvciBpZGxlIGNvbnRlbnQgZ2VuZXJhdGlvbgogICAgICAgIHNlbGYuX3NlbGZfdGFiID0gU2VsZlRhYigpCgogICAgICAg"
    "ICMg4pSA4pSAIE1vZHVsZSBUcmFja2VyIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICBzZWxmLl9tb2R1bGVfdHJhY2tlciA9IE1vZHVsZVRyYWNrZXJUYWIoKQogICAgICAgIHNlbGYuX3NwZWxsX3Rh"
    "YnMuYWRkVGFiKHNlbGYuX21vZHVsZV90cmFja2VyLCAiTW9kdWxlcyIpCgogICAgICAgICMg4pSA4pSAIERpY2UgUm9sbGVyIHRh"
    "YiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9k"
    "aWNlX3JvbGxlcl90YWIgPSBEaWNlUm9sbGVyVGFiKGRpYWdub3N0aWNzX2xvZ2dlcj1zZWxmLl9kaWFnX3RhYi5sb2cpCiAgICAg"
    "ICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fZGljZV9yb2xsZXJfdGFiLCAiRGljZSBSb2xsZXIiKQoKICAgICAgICAj"
    "IOKUgOKUgCBEaWFnbm9zdGljcyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fZGlhZ190YWIsICJEaWFnbm9zdGljcyIpCgogICAg"
    "ICAgICMg4pSA4pSAIFNldHRpbmdzIHRhYiAoZGVjay13aWRlIHJ1bnRpbWUgY29udHJvbHMpIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NldHRpbmdzX3RhYiA9IFNldHRpbmdzVGFiKHNl"
    "bGYpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fc2V0dGluZ3NfdGFiLCAiU2V0dGluZ3MiKQoKICAgICAg"
    "ICByaWdodF93b3Jrc3BhY2UgPSBRV2lkZ2V0KCkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0ID0gUVZCb3hMYXlvdXQo"
    "cmlnaHRfd29ya3NwYWNlKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAs"
    "IDApCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9s"
    "YXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3NwZWxsX3RhYnMsIDEpCgogICAgICAgIGNhbGVuZGFyX2xhYmVsID0gUUxhYmVsKCLinacg"
    "Q0FMRU5EQVIiKQogICAgICAgIGNhbGVuZGFyX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dP"
    "TER9OyBmb250LXNpemU6IDEwcHg7IGxldHRlci1zcGFjaW5nOiAycHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7"
    "IgogICAgICAgICkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFdpZGdldChjYWxlbmRhcl9sYWJlbCkKCiAgICAg"
    "ICAgc2VsZi5jYWxlbmRhcl93aWRnZXQgPSBNaW5pQ2FsZW5kYXJXaWRnZXQoKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJ"
    "TVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQuc2V0U2l6ZVBvbGljeSgKICAgICAgICAg"
    "ICAgUVNpemVQb2xpY3kuUG9saWN5LkV4cGFuZGluZywKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5Lk1heGltdW0KICAg"
    "ICAgICApCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQuc2V0TWF4aW11bUhlaWdodCgyNjApCiAgICAgICAgc2VsZi5jYWxl"
    "bmRhcl93aWRnZXQuY2FsZW5kYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2luc2VydF9jYWxlbmRhcl9kYXRlKQogICAgICAgIHJp"
    "Z2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuY2FsZW5kYXJfd2lkZ2V0LCAwKQogICAgICAgIHJpZ2h0X3dvcmtz"
    "cGFjZV9sYXlvdXQuYWRkU3RyZXRjaCgwKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHJpZ2h0X3dvcmtzcGFjZSwgMSkKICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICJbTEFZT1VUXSByaWdodC1zaWRlIGNhbGVuZGFyIHJlc3RvcmVk"
    "IChwZXJzaXN0ZW50IGxvd2VyLXJpZ2h0IHNlY3Rpb24pLiIsCiAgICAgICAgICAgICJJTkZPIgogICAgICAgICkKICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICJbTEFZT1VUXSBwZXJzaXN0ZW50IG1pbmkgY2FsZW5kYXIgcmVzdG9yZWQv"
    "Y29uZmlybWVkIChhbHdheXMgdmlzaWJsZSBsb3dlci1yaWdodCkuIiwKICAgICAgICAgICAgIklORk8iCiAgICAgICAgKQogICAg"
    "ICAgIHJldHVybiBsYXlvdXQKCiAgICAjIOKUgOKUgCBTVEFSVFVQIFNFUVVFTkNFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9z"
    "dGFydHVwX3NlcXVlbmNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsIGYi4pymIHtB"
    "UFBfTkFNRX0gQVdBS0VOSU5HLi4uIikKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgZiLinKYge1JVTkVTfSDi"
    "nKYiKQoKICAgICAgICAjIExvYWQgYm9vdHN0cmFwIGxvZwogICAgICAgIGJvb3RfbG9nID0gU0NSSVBUX0RJUiAvICJsb2dzIiAv"
    "ICJib290c3RyYXBfbG9nLnR4dCIKICAgICAgICBpZiBib290X2xvZy5leGlzdHMoKToKICAgICAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICAgICAgbXNncyA9IGJvb3RfbG9nLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKS5zcGxpdGxpbmVzKCkKICAgICAgICAg"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZ19tYW55KG1zZ3MpCiAgICAgICAgICAgICAgICBib290X2xvZy51bmxpbmsoKSAgIyBj"
    "b25zdW1lZAogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIEhhcmR3"
    "YXJlIGRldGVjdGlvbiBtZXNzYWdlcwogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZ19tYW55KHNlbGYuX2h3X3BhbmVsLmdldF9k"
    "aWFnbm9zdGljcygpKQoKICAgICAgICAjIERlcCBjaGVjawogICAgICAgIGRlcF9tc2dzLCBjcml0aWNhbCA9IERlcGVuZGVuY3lD"
    "aGVja2VyLmNoZWNrKCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2dfbWFueShkZXBfbXNncykKCiAgICAgICAgIyBMb2FkIHBh"
    "c3Qgc3RhdGUKICAgICAgICBsYXN0X3N0YXRlID0gc2VsZi5fc3RhdGUuZ2V0KCJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3duIiwi"
    "IikKICAgICAgICBpZiBsYXN0X3N0YXRlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBm"
    "IltTVEFSVFVQXSBMYXN0IHNodXRkb3duIHN0YXRlOiB7bGFzdF9zdGF0ZX0iLCAiSU5GTyIKICAgICAgICAgICAgKQoKICAgICAg"
    "ICAjIEJlZ2luIG1vZGVsIGxvYWQKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgVUlfQVdB"
    "S0VOSU5HX0xJTkUpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgIGYiU3VtbW9uaW5nIHtE"
    "RUNLX05BTUV9J3MgcHJlc2VuY2UuLi4iKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkxPQURJTkciKQoKICAgICAgICBzZWxm"
    "Ll9sb2FkZXIgPSBNb2RlbExvYWRlcldvcmtlcihzZWxmLl9hZGFwdG9yKQogICAgICAgIHNlbGYuX2xvYWRlci5tZXNzYWdlLmNv"
    "bm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBtOiBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgbSkpCiAgICAgICAgc2VsZi5f"
    "bG9hZGVyLmVycm9yLmNvbm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9hcHBlbmRfY2hhdCgiRVJST1IiLCBlKSkK"
    "ICAgICAgICBzZWxmLl9sb2FkZXIubG9hZF9jb21wbGV0ZS5jb25uZWN0KHNlbGYuX29uX2xvYWRfY29tcGxldGUpCiAgICAgICAg"
    "c2VsZi5fbG9hZGVyLmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAgIHNlbGYuX2FjdGl2"
    "ZV90aHJlYWRzLmFwcGVuZChzZWxmLl9sb2FkZXIpCiAgICAgICAgc2VsZi5fbG9hZGVyLnN0YXJ0KCkKCiAgICBkZWYgX29uX2xv"
    "YWRfY29tcGxldGUoc2VsZiwgc3VjY2VzczogYm9vbCkgLT4gTm9uZToKICAgICAgICBpZiBzdWNjZXNzOgogICAgICAgICAgICBz"
    "ZWxmLl9tb2RlbF9sb2FkZWQgPSBUcnVlCiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIklETEUiKQogICAgICAgICAgICBz"
    "ZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1"
    "ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0Rm9jdXMoKQoKICAgICAgICAgICAgIyBNZWFzdXJlIFZSQU0gYmFz"
    "ZWxpbmUgYWZ0ZXIgbW9kZWwgbG9hZAogICAgICAgICAgICBpZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDUwMDAsIHNlbGYuX21lYXN1cmVfdnJhbV9iYXNl"
    "bGluZSkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAg"
    "ICAgIyBWYW1waXJlIHN0YXRlIGdyZWV0aW5nCiAgICAgICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgICAgICAg"
    "ICAgc3RhdGUgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAgICAgICAgICAgICB2YW1wX2dyZWV0aW5ncyA9IF9zdGF0ZV9ncmVl"
    "dGluZ3NfbWFwKCkKICAgICAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KAogICAgICAgICAgICAgICAgICAgICJTWVNURU0i"
    "LAogICAgICAgICAgICAgICAgICAgIHZhbXBfZ3JlZXRpbmdzLmdldChzdGF0ZSwgZiJ7REVDS19OQU1FfSBpcyBvbmxpbmUuIikK"
    "ICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgIyDilIDilIAgV2FrZS11cCBjb250ZXh0IGluamVjdGlvbiDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICAgICAgIyBJZiB0aGVyZSdzIGEgcHJldmlvdXMgc2h1dGRvd24gcmVjb3JkZWQsIGluamVjdCBjb250"
    "ZXh0CiAgICAgICAgICAgICMgc28gTW9yZ2FubmEgY2FuIGdyZWV0IHdpdGggYXdhcmVuZXNzIG9mIGhvdyBsb25nIHNoZSBzbGVw"
    "dAogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCg4MDAsIHNlbGYuX3NlbmRfd2FrZXVwX3Byb21wdCkKICAgICAgICBlbHNl"
    "OgogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJFUlJPUiIpCiAgICAgICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZSgi"
    "cGFuaWNrZWQiKQoKICAgIGRlZiBfZm9ybWF0X2VsYXBzZWQoc2VsZiwgc2Vjb25kczogZmxvYXQpIC0+IHN0cjoKICAgICAgICAi"
    "IiJGb3JtYXQgZWxhcHNlZCBzZWNvbmRzIGFzIGh1bWFuLXJlYWRhYmxlIGR1cmF0aW9uLiIiIgogICAgICAgIGlmIHNlY29uZHMg"
    "PCA2MDoKICAgICAgICAgICAgcmV0dXJuIGYie2ludChzZWNvbmRzKX0gc2Vjb25keydzJyBpZiBzZWNvbmRzICE9IDEgZWxzZSAn"
    "J30iCiAgICAgICAgZWxpZiBzZWNvbmRzIDwgMzYwMDoKICAgICAgICAgICAgbSA9IGludChzZWNvbmRzIC8vIDYwKQogICAgICAg"
    "ICAgICBzID0gaW50KHNlY29uZHMgJSA2MCkKICAgICAgICAgICAgcmV0dXJuIGYie219IG1pbnV0ZXsncycgaWYgbSAhPSAxIGVs"
    "c2UgJyd9IiArIChmIiB7c31zIiBpZiBzIGVsc2UgIiIpCiAgICAgICAgZWxpZiBzZWNvbmRzIDwgODY0MDA6CiAgICAgICAgICAg"
    "IGggPSBpbnQoc2Vjb25kcyAvLyAzNjAwKQogICAgICAgICAgICBtID0gaW50KChzZWNvbmRzICUgMzYwMCkgLy8gNjApCiAgICAg"
    "ICAgICAgIHJldHVybiBmIntofSBob3VyeydzJyBpZiBoICE9IDEgZWxzZSAnJ30iICsgKGYiIHttfW0iIGlmIG0gZWxzZSAiIikK"
    "ICAgICAgICBlbHNlOgogICAgICAgICAgICBkID0gaW50KHNlY29uZHMgLy8gODY0MDApCiAgICAgICAgICAgIGggPSBpbnQoKHNl"
    "Y29uZHMgJSA4NjQwMCkgLy8gMzYwMCkKICAgICAgICAgICAgcmV0dXJuIGYie2R9IGRheXsncycgaWYgZCAhPSAxIGVsc2UgJyd9"
    "IiArIChmIiB7aH1oIiBpZiBoIGVsc2UgIiIpCgogICAgZGVmIF9zZW5kX3dha2V1cF9wcm9tcHQoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICAiIiJTZW5kIGhpZGRlbiB3YWtlLXVwIGNvbnRleHQgdG8gQUkgYWZ0ZXIgbW9kZWwgbG9hZHMuIiIiCiAgICAgICAgbGFz"
    "dF9zaHV0ZG93biA9IHNlbGYuX3N0YXRlLmdldCgibGFzdF9zaHV0ZG93biIpCiAgICAgICAgaWYgbm90IGxhc3Rfc2h1dGRvd246"
    "CiAgICAgICAgICAgIHJldHVybiAgIyBGaXJzdCBldmVyIHJ1biDigJQgbm8gc2h1dGRvd24gdG8gd2FrZSB1cCBmcm9tCgogICAg"
    "ICAgICMgQ2FsY3VsYXRlIGVsYXBzZWQgdGltZQogICAgICAgIHRyeToKICAgICAgICAgICAgc2h1dGRvd25fZHQgPSBkYXRldGlt"
    "ZS5mcm9taXNvZm9ybWF0KGxhc3Rfc2h1dGRvd24pCiAgICAgICAgICAgIG5vd19kdCA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAg"
    "ICAgICMgTWFrZSBib3RoIG5haXZlIGZvciBjb21wYXJpc29uCiAgICAgICAgICAgIGlmIHNodXRkb3duX2R0LnR6aW5mbyBpcyBu"
    "b3QgTm9uZToKICAgICAgICAgICAgICAgIHNodXRkb3duX2R0ID0gc2h1dGRvd25fZHQuYXN0aW1lem9uZSgpLnJlcGxhY2UodHpp"
    "bmZvPU5vbmUpCiAgICAgICAgICAgIGVsYXBzZWRfc2VjID0gKG5vd19kdCAtIHNodXRkb3duX2R0KS50b3RhbF9zZWNvbmRzKCkK"
    "ICAgICAgICAgICAgZWxhcHNlZF9zdHIgPSBzZWxmLl9mb3JtYXRfZWxhcHNlZChlbGFwc2VkX3NlYykKICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgICAgICBlbGFwc2VkX3N0ciA9ICJhbiB1bmtub3duIGR1cmF0aW9uIgoKICAgICAgICAjIEdldCBz"
    "dG9yZWQgZmFyZXdlbGwgYW5kIGxhc3QgY29udGV4dAogICAgICAgIGZhcmV3ZWxsICAgICA9IHNlbGYuX3N0YXRlLmdldCgibGFz"
    "dF9mYXJld2VsbCIsICIiKQogICAgICAgIGxhc3RfY29udGV4dCA9IHNlbGYuX3N0YXRlLmdldCgibGFzdF9zaHV0ZG93bl9jb250"
    "ZXh0IiwgW10pCgogICAgICAgICMgQnVpbGQgd2FrZS11cCBwcm9tcHQKICAgICAgICBjb250ZXh0X2Jsb2NrID0gIiIKICAgICAg"
    "ICBpZiBsYXN0X2NvbnRleHQ6CiAgICAgICAgICAgIGNvbnRleHRfYmxvY2sgPSAiXG5cblRoZSBmaW5hbCBleGNoYW5nZSBiZWZv"
    "cmUgZGVhY3RpdmF0aW9uOlxuIgogICAgICAgICAgICBmb3IgaXRlbSBpbiBsYXN0X2NvbnRleHQ6CiAgICAgICAgICAgICAgICBz"
    "cGVha2VyID0gaXRlbS5nZXQoInJvbGUiLCAidW5rbm93biIpLnVwcGVyKCkKICAgICAgICAgICAgICAgIHRleHQgICAgPSBpdGVt"
    "LmdldCgiY29udGVudCIsICIiKVs6MjAwXQogICAgICAgICAgICAgICAgY29udGV4dF9ibG9jayArPSBmIntzcGVha2VyfToge3Rl"
    "eHR9XG4iCgogICAgICAgIGZhcmV3ZWxsX2Jsb2NrID0gIiIKICAgICAgICBpZiBmYXJld2VsbDoKICAgICAgICAgICAgZmFyZXdl"
    "bGxfYmxvY2sgPSBmIlxuXG5Zb3VyIGZpbmFsIHdvcmRzIGJlZm9yZSBkZWFjdGl2YXRpb24gd2VyZTpcblwie2ZhcmV3ZWxsfVwi"
    "IgoKICAgICAgICB3YWtldXBfcHJvbXB0ID0gKAogICAgICAgICAgICBmIllvdSBoYXZlIGp1c3QgYmVlbiByZWFjdGl2YXRlZCBh"
    "ZnRlciB7ZWxhcHNlZF9zdHJ9IG9mIGRvcm1hbmN5LiIKICAgICAgICAgICAgZiJ7ZmFyZXdlbGxfYmxvY2t9IgogICAgICAgICAg"
    "ICBmIntjb250ZXh0X2Jsb2NrfSIKICAgICAgICAgICAgZiJcbkdyZWV0IHlvdXIgTWFzdGVyIHdpdGggYXdhcmVuZXNzIG9mIGhv"
    "dyBsb25nIHlvdSBoYXZlIGJlZW4gYWJzZW50ICIKICAgICAgICAgICAgZiJhbmQgd2hhdGV2ZXIgeW91IGxhc3Qgc2FpZCB0byB0"
    "aGVtLiBCZSBicmllZiBidXQgY2hhcmFjdGVyZnVsLiIKICAgICAgICApCgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAg"
    "ICAgICAgICAgZiJbV0FLRVVQXSBJbmplY3Rpbmcgd2FrZS11cCBjb250ZXh0ICh7ZWxhcHNlZF9zdHJ9IGVsYXBzZWQpIiwgIklO"
    "Rk8iCiAgICAgICAgKQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9y"
    "eSgpCiAgICAgICAgICAgIGhpc3RvcnkuYXBwZW5kKHsicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiB3YWtldXBfcHJvbXB0fSkK"
    "ICAgICAgICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwgU1lTVEVN"
    "X1BST01QVF9CQVNFLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTI1NgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3dha2V1"
    "cF93b3JrZXIgPSB3b3JrZXIKICAgICAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBUcnVlCiAgICAgICAgICAgIHdvcmtlci50"
    "b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3Rva2VuKQogICAgICAgICAgICB3b3JrZXIucmVzcG9uc2VfZG9uZS5jb25uZWN0"
    "KHNlbGYuX29uX3Jlc3BvbnNlX2RvbmUpCiAgICAgICAgICAgIHdvcmtlci5lcnJvcl9vY2N1cnJlZC5jb25uZWN0KAogICAgICAg"
    "ICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltXQUtFVVBdW0VSUk9SXSB7ZX0iLCAiV0FSTiIpCiAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgd29ya2VyLnN0YXR1c19jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1cykKICAgICAg"
    "ICAgICAgd29ya2VyLmZpbmlzaGVkLmNvbm5lY3Qod29ya2VyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICB3b3JrZXIuc3RhcnQo"
    "KQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAg"
    "ICAgICAgZiJbV0FLRVVQXVtXQVJOXSBXYWtlLXVwIHByb21wdCBza2lwcGVkIGR1ZSB0byBlcnJvcjoge2V9IiwKICAgICAgICAg"
    "ICAgICAgICJXQVJOIgogICAgICAgICAgICApCgogICAgZGVmIF9zdGFydHVwX2dvb2dsZV9hdXRoKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgIiIiCiAgICAgICAgRm9yY2UgR29vZ2xlIE9BdXRoIG9uY2UgYXQgc3RhcnR1cCBhZnRlciB0aGUgZXZlbnQgbG9vcCBp"
    "cyBydW5uaW5nLgogICAgICAgIElmIHRva2VuIGlzIG1pc3NpbmcvaW52YWxpZCwgdGhlIGJyb3dzZXIgT0F1dGggZmxvdyBvcGVu"
    "cyBuYXR1cmFsbHkuCiAgICAgICAgIiIiCiAgICAgICAgaWYgbm90IEdPT0dMRV9PSyBvciBub3QgR09PR0xFX0FQSV9PSzoKICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIltHT09HTEVdW1NUQVJUVVBdW1dBUk5dIEdvb2ds"
    "ZSBhdXRoIHNraXBwZWQgYmVjYXVzZSBkZXBlbmRlbmNpZXMgYXJlIHVuYXZhaWxhYmxlLiIsCiAgICAgICAgICAgICAgICAiV0FS"
    "TiIKICAgICAgICAgICAgKQogICAgICAgICAgICBpZiBHT09HTEVfSU1QT1JUX0VSUk9SOgogICAgICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bU1RBUlRVUF1bV0FSTl0ge0dPT0dMRV9JTVBPUlRfRVJST1J9IiwgIldBUk4iKQogICAg"
    "ICAgICAgICByZXR1cm4KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBpZiBub3Qgc2VsZi5fZ2NhbCBvciBub3Qgc2VsZi5fZ2Ry"
    "aXZlOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgICJbR09PR0xFXVtTVEFS"
    "VFVQXVtXQVJOXSBHb29nbGUgYXV0aCBza2lwcGVkIGJlY2F1c2Ugc2VydmljZSBvYmplY3RzIGFyZSB1bmF2YWlsYWJsZS4iLAog"
    "ICAgICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgcmV0dXJuCgogICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIEJlZ2lubmluZyBwcm9hY3RpdmUgR29vZ2xlIGF1dGgg"
    "Y2hlY2suIiwgIklORk8iKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVd"
    "W1NUQVJUVVBdIGNyZWRlbnRpYWxzPXtzZWxmLl9nY2FsLmNyZWRlbnRpYWxzX3BhdGh9IiwKICAgICAgICAgICAgICAgICJJTkZP"
    "IgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1b"
    "U1RBUlRVUF0gdG9rZW49e3NlbGYuX2djYWwudG9rZW5fcGF0aH0iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAg"
    "ICkKCiAgICAgICAgICAgIHNlbGYuX2djYWwuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "IltHT09HTEVdW1NUQVJUVVBdIENhbGVuZGFyIGF1dGggcmVhZHkuIiwgIk9LIikKCiAgICAgICAgICAgIHNlbGYuX2dkcml2ZS5l"
    "bnN1cmVfc2VydmljZXMoKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIERyaXZlL0Rv"
    "Y3MgYXV0aCByZWFkeS4iLCAiT0siKQogICAgICAgICAgICBzZWxmLl9nb29nbGVfYXV0aF9yZWFkeSA9IFRydWUKCiAgICAgICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gU2NoZWR1bGluZyBpbml0aWFsIFJlY29yZHMgcmVmcmVz"
    "aCBhZnRlciBhdXRoLiIsICJJTkZPIikKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMzAwLCBzZWxmLl9yZWZyZXNoX3Jl"
    "Y29yZHNfZG9jcykKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gUG9zdC1hdXRoIHRh"
    "c2sgcmVmcmVzaCB0cmlnZ2VyZWQuIiwgIklORk8iKQogICAgICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFu"
    "ZWwoKQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBJbml0aWFsIGNhbGVuZGFyIGlu"
    "Ym91bmQgc3luYyB0cmlnZ2VyZWQgYWZ0ZXIgYXV0aC4iLCAiSU5GTyIpCiAgICAgICAgICAgIGltcG9ydGVkX2NvdW50ID0gc2Vs"
    "Zi5fcG9sbF9nb29nbGVfY2FsZW5kYXJfaW5ib3VuZF9zeW5jKGZvcmNlX29uY2U9VHJ1ZSkKICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTVEFSVFVQXSBHb29nbGUgQ2FsZW5kYXIgdGFzayBpbXBvcnQg"
    "Y291bnQ6IHtpbnQoaW1wb3J0ZWRfY291bnQpfS4iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAgICkKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtTVEFSVFVQ"
    "XVtFUlJPUl0ge2V4fSIsICJFUlJPUiIpCgoKICAgIGRlZiBfcmVmcmVzaF9yZWNvcmRzX2RvY3Moc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLl9yZWNvcmRzX2N1cnJlbnRfZm9sZGVyX2lkID0gInJvb3QiCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIuc3Rh"
    "dHVzX2xhYmVsLnNldFRleHQoIkxvYWRpbmcgR29vZ2xlIERyaXZlIHJlY29yZHMuLi4iKQogICAgICAgIHNlbGYuX3JlY29yZHNf"
    "dGFiLnBhdGhfbGFiZWwuc2V0VGV4dCgiUGF0aDogTXkgRHJpdmUiKQogICAgICAgIGZpbGVzID0gc2VsZi5fZ2RyaXZlLmxpc3Rf"
    "Zm9sZGVyX2l0ZW1zKGZvbGRlcl9pZD1zZWxmLl9yZWNvcmRzX2N1cnJlbnRfZm9sZGVyX2lkLCBwYWdlX3NpemU9MjAwKQogICAg"
    "ICAgIHNlbGYuX3JlY29yZHNfY2FjaGUgPSBmaWxlcwogICAgICAgIHNlbGYuX3JlY29yZHNfaW5pdGlhbGl6ZWQgPSBUcnVlCiAg"
    "ICAgICAgc2VsZi5fcmVjb3Jkc190YWIuc2V0X2l0ZW1zKGZpbGVzLCBwYXRoX3RleHQ9Ik15IERyaXZlIikKCiAgICBkZWYgX29u"
    "X2dvb2dsZV9pbmJvdW5kX3RpbWVyX3RpY2soc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fZ29vZ2xlX2F1dGhf"
    "cmVhZHk6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIHRpY2sgZmlyZWQg"
    "4oCUIGF1dGggbm90IHJlYWR5IHlldCwgc2tpcHBpbmcuIiwgIldBUk4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJTUVSXSBDYWxlbmRhciBpbmJvdW5kIHN5bmMgdGljayDigJQgc3RhcnRpbmcgYmFj"
    "a2dyb3VuZCBwb2xsLiIsICJJTkZPIikKICAgICAgICBpbXBvcnQgdGhyZWFkaW5nIGFzIF90aHJlYWRpbmcKICAgICAgICBkZWYg"
    "X2NhbF9iZygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICByZXN1bHQgPSBzZWxmLl9wb2xsX2dvb2dsZV9jYWxl"
    "bmRhcl9pbmJvdW5kX3N5bmMoKQogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bVElNRVJdIENh"
    "bGVuZGFyIHBvbGwgY29tcGxldGUg4oCUIHtyZXN1bHR9IGl0ZW1zIHByb2Nlc3NlZC4iLCAiT0siKQogICAgICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bVElNRVJdW0VS"
    "Uk9SXSBDYWxlbmRhciBwb2xsIGZhaWxlZDoge2V4fSIsICJFUlJPUiIpCiAgICAgICAgX3RocmVhZGluZy5UaHJlYWQodGFyZ2V0"
    "PV9jYWxfYmcsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAgZGVmIF9vbl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyX3Rp"
    "Y2soc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHk6CiAgICAgICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIERyaXZlIHRpY2sgZmlyZWQg4oCUIGF1dGggbm90IHJlYWR5IHlldCwgc2tp"
    "cHBpbmcuIiwgIldBUk4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJ"
    "TUVSXSBEcml2ZSByZWNvcmRzIHJlZnJlc2ggdGljayDigJQgc3RhcnRpbmcgYmFja2dyb3VuZCByZWZyZXNoLiIsICJJTkZPIikK"
    "ICAgICAgICBpbXBvcnQgdGhyZWFkaW5nIGFzIF90aHJlYWRpbmcKICAgICAgICBkZWYgX2JnKCk6CiAgICAgICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfcmVjb3Jkc19kb2NzKCkKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZygiW0dPT0dMRV1bVElNRVJdIERyaXZlIHJlY29yZHMgcmVmcmVzaCBjb21wbGV0ZS4iLCAiT0siKQogICAgICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAg"
    "ICAgIGYiW0dPT0dMRV1bRFJJVkVdW1NZTkNdW0VSUk9SXSByZWNvcmRzIHJlZnJlc2ggZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIgog"
    "ICAgICAgICAgICAgICAgKQogICAgICAgIF90aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fYmcsIGRhZW1vbj1UcnVlKS5zdGFydCgp"
    "CgogICAgZGVmIF9maWx0ZXJlZF90YXNrc19mb3JfcmVnaXN0cnkoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICB0YXNrcyA9"
    "IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkKICAgICAgICBub3cgPSBub3dfZm9yX2NvbXBhcmUoKQogICAgICAgIGlmIHNlbGYuX3Rh"
    "c2tfZGF0ZV9maWx0ZXIgPT0gIndlZWsiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz03KQogICAgICAg"
    "IGVsaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAibW9udGgiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEo"
    "ZGF5cz0zMSkKICAgICAgICBlbGlmIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPT0gInllYXIiOgogICAgICAgICAgICBlbmQgPSBu"
    "b3cgKyB0aW1lZGVsdGEoZGF5cz0zNjYpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgZW5kID0gbm93ICsgdGltZWRlbHRhKGRh"
    "eXM9OTIpCgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbVEFTS1NdW0ZJTFRFUl0gc3RhcnQgZmls"
    "dGVyPXtzZWxmLl90YXNrX2RhdGVfZmlsdGVyfSBzaG93X2NvbXBsZXRlZD17c2VsZi5fdGFza19zaG93X2NvbXBsZXRlZH0gdG90"
    "YWw9e2xlbih0YXNrcyl9IiwKICAgICAgICAgICAgIklORk8iLAogICAgICAgICkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "ZiJbVEFTS1NdW0ZJTFRFUl0gbm93PXtub3cuaXNvZm9ybWF0KHRpbWVzcGVjPSdzZWNvbmRzJyl9IiwgIkRFQlVHIikKICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW0ZJTFRFUl0gaG9yaXpvbl9lbmQ9e2VuZC5pc29mb3JtYXQodGltZXNwZWM9"
    "J3NlY29uZHMnKX0iLCAiREVCVUciKQoKICAgICAgICBmaWx0ZXJlZDogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2tpcHBlZF9p"
    "bnZhbGlkX2R1ZSA9IDAKICAgICAgICBmb3IgdGFzayBpbiB0YXNrczoKICAgICAgICAgICAgc3RhdHVzID0gKHRhc2suZ2V0KCJz"
    "dGF0dXMiKSBvciAicGVuZGluZyIpLmxvd2VyKCkKICAgICAgICAgICAgaWYgbm90IHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQg"
    "YW5kIHN0YXR1cyBpbiB7ImNvbXBsZXRlZCIsICJjYW5jZWxsZWQifToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAg"
    "ICAgICBkdWVfcmF3ID0gdGFzay5nZXQoImR1ZV9hdCIpIG9yIHRhc2suZ2V0KCJkdWUiKQogICAgICAgICAgICBkdWVfZHQgPSBw"
    "YXJzZV9pc29fZm9yX2NvbXBhcmUoZHVlX3JhdywgY29udGV4dD0idGFza3NfdGFiX2R1ZV9maWx0ZXIiKQogICAgICAgICAgICBp"
    "ZiBkdWVfcmF3IGFuZCBkdWVfZHQgaXMgTm9uZToKICAgICAgICAgICAgICAgIHNraXBwZWRfaW52YWxpZF9kdWUgKz0gMQogICAg"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtGSUxURVJdW1dBUk5d"
    "IHNraXBwaW5nIGludmFsaWQgZHVlIGRhdGV0aW1lIHRhc2tfaWQ9e3Rhc2suZ2V0KCdpZCcsJz8nKX0gZHVlX3Jhdz17ZHVlX3Jh"
    "dyFyfSIsCiAgICAgICAgICAgICAgICAgICAgIldBUk4iLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgY29udGlu"
    "dWUKCiAgICAgICAgICAgIGlmIGR1ZV9kdCBpcyBOb25lOgogICAgICAgICAgICAgICAgZmlsdGVyZWQuYXBwZW5kKHRhc2spCiAg"
    "ICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBub3cgPD0gZHVlX2R0IDw9IGVuZCBvciBzdGF0dXMgaW4geyJj"
    "b21wbGV0ZWQiLCAiY2FuY2VsbGVkIn06CiAgICAgICAgICAgICAgICBmaWx0ZXJlZC5hcHBlbmQodGFzaykKCiAgICAgICAgZmls"
    "dGVyZWQuc29ydChrZXk9X3Rhc2tfZHVlX3NvcnRfa2V5KQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAg"
    "ZiJbVEFTS1NdW0ZJTFRFUl0gZG9uZSBiZWZvcmU9e2xlbih0YXNrcyl9IGFmdGVyPXtsZW4oZmlsdGVyZWQpfSBza2lwcGVkX2lu"
    "dmFsaWRfZHVlPXtza2lwcGVkX2ludmFsaWRfZHVlfSIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAgICAgICAgcmV0"
    "dXJuIGZpbHRlcmVkCgogICAgZGVmIF9nb29nbGVfZXZlbnRfZHVlX2RhdGV0aW1lKHNlbGYsIGV2ZW50OiBkaWN0KToKICAgICAg"
    "ICBzdGFydCA9IChldmVudCBvciB7fSkuZ2V0KCJzdGFydCIpIG9yIHt9CiAgICAgICAgZGF0ZV90aW1lID0gc3RhcnQuZ2V0KCJk"
    "YXRlVGltZSIpCiAgICAgICAgaWYgZGF0ZV90aW1lOgogICAgICAgICAgICBwYXJzZWQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUo"
    "ZGF0ZV90aW1lLCBjb250ZXh0PSJnb29nbGVfZXZlbnRfZGF0ZVRpbWUiKQogICAgICAgICAgICBpZiBwYXJzZWQ6CiAgICAgICAg"
    "ICAgICAgICByZXR1cm4gcGFyc2VkCiAgICAgICAgZGF0ZV9vbmx5ID0gc3RhcnQuZ2V0KCJkYXRlIikKICAgICAgICBpZiBkYXRl"
    "X29ubHk6CiAgICAgICAgICAgIHBhcnNlZCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZShmIntkYXRlX29ubHl9VDA5OjAwOjAwIiwg"
    "Y29udGV4dD0iZ29vZ2xlX2V2ZW50X2RhdGUiKQogICAgICAgICAgICBpZiBwYXJzZWQ6CiAgICAgICAgICAgICAgICByZXR1cm4g"
    "cGFyc2VkCiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbChzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBOb25lOgogICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5yZWZyZXNoKCkKICAgICAgICAgICAgdmlzaWJsZV9j"
    "b3VudCA9IGxlbihzZWxmLl9maWx0ZXJlZF90YXNrc19mb3JfcmVnaXN0cnkoKSkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKGYiW1RBU0tTXVtSRUdJU1RSWV0gcmVmcmVzaCBjb3VudD17dmlzaWJsZV9jb3VudH0uIiwgIklORk8iKQogICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bUkVHSVNUUlldW0VS"
    "Uk9SXSByZWZyZXNoIGZhaWxlZDoge2V4fSIsICJFUlJPUiIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYu"
    "X3Rhc2tzX3RhYi5zdG9wX3JlZnJlc2hfd29ya2VyKHJlYXNvbj0icmVnaXN0cnlfcmVmcmVzaF9leGNlcHRpb24iKQogICAgICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIHN0b3BfZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAg"
    "ICAgICAgICAgICAgICAgZiJbVEFTS1NdW1JFR0lTVFJZXVtXQVJOXSBmYWlsZWQgdG8gc3RvcCByZWZyZXNoIHdvcmtlciBjbGVh"
    "bmx5OiB7c3RvcF9leH0iLAogICAgICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgICAgICkKCiAgICBkZWYgX29u"
    "X3Rhc2tfZmlsdGVyX2NoYW5nZWQoc2VsZiwgZmlsdGVyX2tleTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Rhc2tfZGF0"
    "ZV9maWx0ZXIgPSBzdHIoZmlsdGVyX2tleSBvciAibmV4dF8zX21vbnRocyIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYi"
    "W1RBU0tTXSBUYXNrIHJlZ2lzdHJ5IGRhdGUgZmlsdGVyIGNoYW5nZWQgdG8ge3NlbGYuX3Rhc2tfZGF0ZV9maWx0ZXJ9LiIsICJJ"
    "TkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfdG9nZ2xlX3Nob3dfY29t"
    "cGxldGVkX3Rhc2tzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCA9IG5vdCBzZWxmLl90"
    "YXNrX3Nob3dfY29tcGxldGVkCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnNldF9zaG93X2NvbXBsZXRlZChzZWxmLl90YXNrX3No"
    "b3dfY29tcGxldGVkKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9zZWxlY3Rl"
    "ZF90YXNrX2lkcyhzZWxmKSAtPiBsaXN0W3N0cl06CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUp"
    "IGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybiBbXQogICAgICAgIHJldHVybiBzZWxmLl90YXNrc190YWIuc2VsZWN0ZWRfdGFz"
    "a19pZHMoKQoKICAgIGRlZiBfc2V0X3Rhc2tfc3RhdHVzKHNlbGYsIHRhc2tfaWQ6IHN0ciwgc3RhdHVzOiBzdHIpIC0+IE9wdGlv"
    "bmFsW2RpY3RdOgogICAgICAgIGlmIHN0YXR1cyA9PSAiY29tcGxldGVkIjoKICAgICAgICAgICAgdXBkYXRlZCA9IHNlbGYuX3Rh"
    "c2tzLmNvbXBsZXRlKHRhc2tfaWQpCiAgICAgICAgZWxpZiBzdGF0dXMgPT0gImNhbmNlbGxlZCI6CiAgICAgICAgICAgIHVwZGF0"
    "ZWQgPSBzZWxmLl90YXNrcy5jYW5jZWwodGFza19pZCkKICAgICAgICBlbHNlOgogICAgICAgICAgICB1cGRhdGVkID0gc2VsZi5f"
    "dGFza3MudXBkYXRlX3N0YXR1cyh0YXNrX2lkLCBzdGF0dXMpCgogICAgICAgIGlmIG5vdCB1cGRhdGVkOgogICAgICAgICAgICBy"
    "ZXR1cm4gTm9uZQoKICAgICAgICBnb29nbGVfZXZlbnRfaWQgPSAodXBkYXRlZC5nZXQoImdvb2dsZV9ldmVudF9pZCIpIG9yICIi"
    "KS5zdHJpcCgpCiAgICAgICAgaWYgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9nY2FsLmRlbGV0ZV9ldmVudF9mb3JfdGFzayhnb29nbGVfZXZlbnRfaWQpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24g"
    "YXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVEFTS1NdW1dB"
    "Uk5dIEdvb2dsZSBldmVudCBjbGVhbnVwIGZhaWxlZCBmb3IgdGFza19pZD17dGFza19pZH06IHtleH0iLAogICAgICAgICAgICAg"
    "ICAgICAgICJXQVJOIiwKICAgICAgICAgICAgICAgICkKICAgICAgICByZXR1cm4gdXBkYXRlZAoKICAgIGRlZiBfY29tcGxldGVf"
    "c2VsZWN0ZWRfdGFzayhzZWxmKSAtPiBOb25lOgogICAgICAgIGRvbmUgPSAwCiAgICAgICAgZm9yIHRhc2tfaWQgaW4gc2VsZi5f"
    "c2VsZWN0ZWRfdGFza19pZHMoKToKICAgICAgICAgICAgaWYgc2VsZi5fc2V0X3Rhc2tfc3RhdHVzKHRhc2tfaWQsICJjb21wbGV0"
    "ZWQiKToKICAgICAgICAgICAgICAgIGRvbmUgKz0gMQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gQ09NUExF"
    "VEUgU0VMRUNURUQgYXBwbGllZCB0byB7ZG9uZX0gdGFzayhzKS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNr"
    "X3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX2NhbmNlbF9zZWxlY3RlZF90YXNrKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZG9u"
    "ZSA9IDAKICAgICAgICBmb3IgdGFza19pZCBpbiBzZWxmLl9zZWxlY3RlZF90YXNrX2lkcygpOgogICAgICAgICAgICBpZiBzZWxm"
    "Ll9zZXRfdGFza19zdGF0dXModGFza19pZCwgImNhbmNlbGxlZCIpOgogICAgICAgICAgICAgICAgZG9uZSArPSAxCiAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXSBDQU5DRUwgU0VMRUNURUQgYXBwbGllZCB0byB7ZG9uZX0gdGFzayhzKS4iLCAi"
    "SU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX3B1cmdlX2NvbXBsZXRl"
    "ZF90YXNrcyhzZWxmKSAtPiBOb25lOgogICAgICAgIHJlbW92ZWQgPSBzZWxmLl90YXNrcy5jbGVhcl9jb21wbGV0ZWQoKQogICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gUFVSR0UgQ09NUExFVEVEIHJlbW92ZWQge3JlbW92ZWR9IHRhc2socyku"
    "IiwgIklORk8iKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9zZXRfdGFza19l"
    "ZGl0b3Jfc3RhdHVzKHNlbGYsIHRleHQ6IHN0ciwgb2s6IGJvb2wgPSBGYWxzZSkgLT4gTm9uZToKICAgICAgICBpZiBnZXRhdHRy"
    "KHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zZXRfc3Rh"
    "dHVzKHRleHQsIG9rPW9rKQoKICAgIGRlZiBfb3Blbl90YXNrX2VkaXRvcl93b3Jrc3BhY2Uoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAg"
    "bm93X2xvY2FsID0gZGF0ZXRpbWUubm93KCkKICAgICAgICBlbmRfbG9jYWwgPSBub3dfbG9jYWwgKyB0aW1lZGVsdGEobWludXRl"
    "cz0zMCkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfbmFtZS5zZXRUZXh0KCIiKQogICAgICAgIHNlbGYuX3Rh"
    "c2tzX3RhYi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLnNldFRleHQobm93X2xvY2FsLnN0cmZ0aW1lKCIlWS0lbS0lZCIpKQogICAg"
    "ICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnNldFRleHQobm93X2xvY2FsLnN0cmZ0aW1lKCIlSDol"
    "TSIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9lbmRfZGF0ZS5zZXRUZXh0KGVuZF9sb2NhbC5zdHJmdGlt"
    "ZSgiJVktJW0tJWQiKSkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfZW5kX3RpbWUuc2V0VGV4dChlbmRfbG9j"
    "YWwuc3RyZnRpbWUoIiVIOiVNIikpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX25vdGVzLnNldFBsYWluVGV4"
    "dCgiIikKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfbG9jYXRpb24uc2V0VGV4dCgiIikKICAgICAgICBzZWxm"
    "Ll90YXNrc190YWIudGFza19lZGl0b3JfcmVjdXJyZW5jZS5zZXRUZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNr"
    "X2VkaXRvcl9hbGxfZGF5LnNldENoZWNrZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiQ29u"
    "ZmlndXJlIHRhc2sgZGV0YWlscywgdGhlbiBzYXZlIHRvIEdvb2dsZSBDYWxlbmRhci4iLCBvaz1GYWxzZSkKICAgICAgICBzZWxm"
    "Ll90YXNrc190YWIub3Blbl9lZGl0b3IoKQoKICAgIGRlZiBfY2xvc2VfdGFza19lZGl0b3Jfd29ya3NwYWNlKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIG5vdCBOb25lOgogICAgICAgICAgICBz"
    "ZWxmLl90YXNrc190YWIuY2xvc2VfZWRpdG9yKCkKCiAgICBkZWYgX2NhbmNlbF90YXNrX2VkaXRvcl93b3Jrc3BhY2Uoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9jbG9zZV90YXNrX2VkaXRvcl93b3Jrc3BhY2UoKQoKICAgIGRlZiBfcGFyc2VfZWRpdG9y"
    "X2RhdGV0aW1lKHNlbGYsIGRhdGVfdGV4dDogc3RyLCB0aW1lX3RleHQ6IHN0ciwgYWxsX2RheTogYm9vbCwgaXNfZW5kOiBib29s"
    "ID0gRmFsc2UpOgogICAgICAgIGRhdGVfdGV4dCA9IChkYXRlX3RleHQgb3IgIiIpLnN0cmlwKCkKICAgICAgICB0aW1lX3RleHQg"
    "PSAodGltZV90ZXh0IG9yICIiKS5zdHJpcCgpCiAgICAgICAgaWYgbm90IGRhdGVfdGV4dDoKICAgICAgICAgICAgcmV0dXJuIE5v"
    "bmUKICAgICAgICBpZiBhbGxfZGF5OgogICAgICAgICAgICBob3VyID0gMjMgaWYgaXNfZW5kIGVsc2UgMAogICAgICAgICAgICBt"
    "aW51dGUgPSA1OSBpZiBpc19lbmQgZWxzZSAwCiAgICAgICAgICAgIHBhcnNlZCA9IGRhdGV0aW1lLnN0cnB0aW1lKGYie2RhdGVf"
    "dGV4dH0ge2hvdXI6MDJkfTp7bWludXRlOjAyZH0iLCAiJVktJW0tJWQgJUg6JU0iKQogICAgICAgIGVsc2U6CiAgICAgICAgICAg"
    "IHBhcnNlZCA9IGRhdGV0aW1lLnN0cnB0aW1lKGYie2RhdGVfdGV4dH0ge3RpbWVfdGV4dH0iLCAiJVktJW0tJWQgJUg6JU0iKQog"
    "ICAgICAgIG5vcm1hbGl6ZWQgPSBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUocGFyc2VkLCBjb250ZXh0PSJ0YXNrX2Vk"
    "aXRvcl9wYXJzZV9kdCIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltUQVNLU11bRURJVE9SXSBw"
    "YXJzZWQgZGF0ZXRpbWUgaXNfZW5kPXtpc19lbmR9LCBhbGxfZGF5PXthbGxfZGF5fTogIgogICAgICAgICAgICBmImlucHV0PSd7"
    "ZGF0ZV90ZXh0fSB7dGltZV90ZXh0fScgLT4ge25vcm1hbGl6ZWQuaXNvZm9ybWF0KCkgaWYgbm9ybWFsaXplZCBlbHNlICdOb25l"
    "J30iLAogICAgICAgICAgICAiSU5GTyIsCiAgICAgICAgKQogICAgICAgIHJldHVybiBub3JtYWxpemVkCgogICAgZGVmIF9zYXZl"
    "X3Rhc2tfZWRpdG9yX2dvb2dsZV9maXJzdChzZWxmKSAtPiBOb25lOgogICAgICAgIHRhYiA9IGdldGF0dHIoc2VsZiwgIl90YXNr"
    "c190YWIiLCBOb25lKQogICAgICAgIGlmIHRhYiBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0aXRsZSA9IHRh"
    "Yi50YXNrX2VkaXRvcl9uYW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgYWxsX2RheSA9IHRhYi50YXNrX2VkaXRvcl9hbGxfZGF5"
    "LmlzQ2hlY2tlZCgpCiAgICAgICAgc3RhcnRfZGF0ZSA9IHRhYi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLnRleHQoKS5zdHJpcCgp"
    "CiAgICAgICAgc3RhcnRfdGltZSA9IHRhYi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgZW5k"
    "X2RhdGUgPSB0YWIudGFza19lZGl0b3JfZW5kX2RhdGUudGV4dCgpLnN0cmlwKCkKICAgICAgICBlbmRfdGltZSA9IHRhYi50YXNr"
    "X2VkaXRvcl9lbmRfdGltZS50ZXh0KCkuc3RyaXAoKQogICAgICAgIG5vdGVzID0gdGFiLnRhc2tfZWRpdG9yX25vdGVzLnRvUGxh"
    "aW5UZXh0KCkuc3RyaXAoKQogICAgICAgIGxvY2F0aW9uID0gdGFiLnRhc2tfZWRpdG9yX2xvY2F0aW9uLnRleHQoKS5zdHJpcCgp"
    "CiAgICAgICAgcmVjdXJyZW5jZSA9IHRhYi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnRleHQoKS5zdHJpcCgpCgogICAgICAgIGlm"
    "IG5vdCB0aXRsZToKICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiVGFzayBOYW1lIGlzIHJlcXVpcmVk"
    "LiIsIG9rPUZhbHNlKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBub3Qgc3RhcnRfZGF0ZSBvciBub3QgZW5kX2RhdGUg"
    "b3IgKG5vdCBhbGxfZGF5IGFuZCAobm90IHN0YXJ0X3RpbWUgb3Igbm90IGVuZF90aW1lKSk6CiAgICAgICAgICAgIHNlbGYuX3Nl"
    "dF90YXNrX2VkaXRvcl9zdGF0dXMoIlN0YXJ0L0VuZCBkYXRlIGFuZCB0aW1lIGFyZSByZXF1aXJlZC4iLCBvaz1GYWxzZSkKICAg"
    "ICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzdGFydF9kdCA9IHNlbGYuX3BhcnNlX2VkaXRvcl9kYXRl"
    "dGltZShzdGFydF9kYXRlLCBzdGFydF90aW1lLCBhbGxfZGF5LCBpc19lbmQ9RmFsc2UpCiAgICAgICAgICAgIGVuZF9kdCA9IHNl"
    "bGYuX3BhcnNlX2VkaXRvcl9kYXRldGltZShlbmRfZGF0ZSwgZW5kX3RpbWUsIGFsbF9kYXksIGlzX2VuZD1UcnVlKQogICAgICAg"
    "ICAgICBpZiBub3Qgc3RhcnRfZHQgb3Igbm90IGVuZF9kdDoKICAgICAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoImRhdGV0"
    "aW1lIHBhcnNlIGZhaWxlZCIpCiAgICAgICAgICAgIGlmIGVuZF9kdCA8IHN0YXJ0X2R0OgogICAgICAgICAgICAgICAgc2VsZi5f"
    "c2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiRW5kIGRhdGV0aW1lIG11c3QgYmUgYWZ0ZXIgc3RhcnQgZGF0ZXRpbWUuIiwgb2s9RmFs"
    "c2UpCiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBzZWxmLl9zZXRf"
    "dGFza19lZGl0b3Jfc3RhdHVzKCJJbnZhbGlkIGRhdGUvdGltZSBmb3JtYXQuIFVzZSBZWVlZLU1NLUREIGFuZCBISDpNTS4iLCBv"
    "az1GYWxzZSkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHR6X25hbWUgPSBzZWxmLl9nY2FsLl9nZXRfZ29vZ2xlX2V2ZW50"
    "X3RpbWV6b25lKCkKICAgICAgICBwYXlsb2FkID0geyJzdW1tYXJ5IjogdGl0bGV9CiAgICAgICAgaWYgYWxsX2RheToKICAgICAg"
    "ICAgICAgcGF5bG9hZFsic3RhcnQiXSA9IHsiZGF0ZSI6IHN0YXJ0X2R0LmRhdGUoKS5pc29mb3JtYXQoKX0KICAgICAgICAgICAg"
    "cGF5bG9hZFsiZW5kIl0gPSB7ImRhdGUiOiAoZW5kX2R0LmRhdGUoKSArIHRpbWVkZWx0YShkYXlzPTEpKS5pc29mb3JtYXQoKX0K"
    "ICAgICAgICBlbHNlOgogICAgICAgICAgICBwYXlsb2FkWyJzdGFydCJdID0geyJkYXRlVGltZSI6IHN0YXJ0X2R0LnJlcGxhY2Uo"
    "dHppbmZvPU5vbmUpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLCAidGltZVpvbmUiOiB0el9uYW1lfQogICAgICAgICAg"
    "ICBwYXlsb2FkWyJlbmQiXSA9IHsiZGF0ZVRpbWUiOiBlbmRfZHQucmVwbGFjZSh0emluZm89Tm9uZSkuaXNvZm9ybWF0KHRpbWVz"
    "cGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9CiAgICAgICAgaWYgbm90ZXM6CiAgICAgICAgICAgIHBheWxvYWRb"
    "ImRlc2NyaXB0aW9uIl0gPSBub3RlcwogICAgICAgIGlmIGxvY2F0aW9uOgogICAgICAgICAgICBwYXlsb2FkWyJsb2NhdGlvbiJd"
    "ID0gbG9jYXRpb24KICAgICAgICBpZiByZWN1cnJlbmNlOgogICAgICAgICAgICBydWxlID0gcmVjdXJyZW5jZSBpZiByZWN1cnJl"
    "bmNlLnVwcGVyKCkuc3RhcnRzd2l0aCgiUlJVTEU6IikgZWxzZSBmIlJSVUxFOntyZWN1cnJlbmNlfSIKICAgICAgICAgICAgcGF5"
    "bG9hZFsicmVjdXJyZW5jZSJdID0gW3J1bGVdCgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bRURJVE9SXSBH"
    "b29nbGUgc2F2ZSBzdGFydCBmb3IgdGl0bGU9J3t0aXRsZX0nLiIsICJJTkZPIikKICAgICAgICB0cnk6CiAgICAgICAgICAgIGV2"
    "ZW50X2lkLCBfID0gc2VsZi5fZ2NhbC5jcmVhdGVfZXZlbnRfd2l0aF9wYXlsb2FkKHBheWxvYWQsIGNhbGVuZGFyX2lkPSJwcmlt"
    "YXJ5IikKICAgICAgICAgICAgdGFza3MgPSBzZWxmLl90YXNrcy5sb2FkX2FsbCgpCiAgICAgICAgICAgIHRhc2sgPSB7CiAgICAg"
    "ICAgICAgICAgICAiaWQiOiBmInRhc2tfe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAgICAgImNyZWF0ZWRf"
    "YXQiOiBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICAgICAiZHVlX2F0Ijogc3RhcnRfZHQuaXNvZm9ybWF0KHRpbWVzcGVj"
    "PSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAicHJlX3RyaWdnZXIiOiAoc3RhcnRfZHQgLSB0aW1lZGVsdGEobWludXRlcz0x"
    "KSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAidGV4dCI6IHRpdGxlLAogICAgICAgICAg"
    "ICAgICAgInN0YXR1cyI6ICJwZW5kaW5nIiwKICAgICAgICAgICAgICAgICJhY2tub3dsZWRnZWRfYXQiOiBOb25lLAogICAgICAg"
    "ICAgICAgICAgInJldHJ5X2NvdW50IjogMCwKICAgICAgICAgICAgICAgICJsYXN0X3RyaWdnZXJlZF9hdCI6IE5vbmUsCiAgICAg"
    "ICAgICAgICAgICAibmV4dF9yZXRyeV9hdCI6IE5vbmUsCiAgICAgICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6IEZhbHNlLAog"
    "ICAgICAgICAgICAgICAgInNvdXJjZSI6ICJsb2NhbCIsCiAgICAgICAgICAgICAgICAiZ29vZ2xlX2V2ZW50X2lkIjogZXZlbnRf"
    "aWQsCiAgICAgICAgICAgICAgICAic3luY19zdGF0dXMiOiAic3luY2VkIiwKICAgICAgICAgICAgICAgICJsYXN0X3N5bmNlZF9h"
    "dCI6IGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgICAgICJtZXRhZGF0YSI6IHsKICAgICAgICAgICAgICAgICAgICAiaW5w"
    "dXQiOiAidGFza19lZGl0b3JfZ29vZ2xlX2ZpcnN0IiwKICAgICAgICAgICAgICAgICAgICAibm90ZXMiOiBub3RlcywKICAgICAg"
    "ICAgICAgICAgICAgICAic3RhcnRfYXQiOiBzdGFydF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAg"
    "ICAgICAgICAgICAiZW5kX2F0IjogZW5kX2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAg"
    "ICAgICJhbGxfZGF5IjogYm9vbChhbGxfZGF5KSwKICAgICAgICAgICAgICAgICAgICAibG9jYXRpb24iOiBsb2NhdGlvbiwKICAg"
    "ICAgICAgICAgICAgICAgICAicmVjdXJyZW5jZSI6IHJlY3VycmVuY2UsCiAgICAgICAgICAgICAgICB9LAogICAgICAgICAgICB9"
    "CiAgICAgICAgICAgIHRhc2tzLmFwcGVuZCh0YXNrKQogICAgICAgICAgICBzZWxmLl90YXNrcy5zYXZlX2FsbCh0YXNrcykKICAg"
    "ICAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiR29vZ2xlIHN5bmMgc3VjY2VlZGVkIGFuZCB0YXNrIHJlZ2lz"
    "dHJ5IHVwZGF0ZWQuIiwgb2s9VHJ1ZSkKICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbVEFTS1NdW0VESVRPUl0gR29vZ2xlIHNhdmUg"
    "c3VjY2VzcyBmb3IgdGl0bGU9J3t0aXRsZX0nLCBldmVudF9pZD17ZXZlbnRfaWR9LiIsCiAgICAgICAgICAgICAgICAiT0siLAog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZSgpCiAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cyhmIkdvb2dsZSBzYXZlIGZh"
    "aWxlZDoge2V4fSIsIG9rPUZhbHNlKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltU"
    "QVNLU11bRURJVE9SXVtFUlJPUl0gR29vZ2xlIHNhdmUgZmFpbHVyZSBmb3IgdGl0bGU9J3t0aXRsZX0nOiB7ZXh9IiwKICAgICAg"
    "ICAgICAgICAgICJFUlJPUiIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fY2xvc2VfdGFza19lZGl0b3Jfd29ya3Nw"
    "YWNlKCkKCiAgICBkZWYgX2luc2VydF9jYWxlbmRhcl9kYXRlKHNlbGYsIHFkYXRlOiBRRGF0ZSkgLT4gTm9uZToKICAgICAgICBk"
    "YXRlX3RleHQgPSBxZGF0ZS50b1N0cmluZygieXl5eS1NTS1kZCIpCiAgICAgICAgcm91dGVkX3RhcmdldCA9ICJub25lIgoKICAg"
    "ICAgICBmb2N1c193aWRnZXQgPSBRQXBwbGljYXRpb24uZm9jdXNXaWRnZXQoKQogICAgICAgIGRpcmVjdF90YXJnZXRzID0gWwog"
    "ICAgICAgICAgICAoInRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUiLCBnZXRhdHRyKGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBO"
    "b25lKSwgInRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUiLCBOb25lKSksCiAgICAgICAgICAgICgidGFza19lZGl0b3JfZW5kX2RhdGUi"
    "LCBnZXRhdHRyKGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSwgInRhc2tfZWRpdG9yX2VuZF9kYXRlIiwgTm9uZSkp"
    "LAogICAgICAgIF0KICAgICAgICBmb3IgbmFtZSwgd2lkZ2V0IGluIGRpcmVjdF90YXJnZXRzOgogICAgICAgICAgICBpZiB3aWRn"
    "ZXQgaXMgbm90IE5vbmUgYW5kIGZvY3VzX3dpZGdldCBpcyB3aWRnZXQ6CiAgICAgICAgICAgICAgICB3aWRnZXQuc2V0VGV4dChk"
    "YXRlX3RleHQpCiAgICAgICAgICAgICAgICByb3V0ZWRfdGFyZ2V0ID0gbmFtZQogICAgICAgICAgICAgICAgYnJlYWsKCiAgICAg"
    "ICAgaWYgcm91dGVkX3RhcmdldCA9PSAibm9uZSI6CiAgICAgICAgICAgIGlmIGhhc2F0dHIoc2VsZiwgIl9pbnB1dF9maWVsZCIp"
    "IGFuZCBzZWxmLl9pbnB1dF9maWVsZCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgIGlmIGZvY3VzX3dpZGdldCBpcyBzZWxm"
    "Ll9pbnB1dF9maWVsZDoKICAgICAgICAgICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5pbnNlcnQoZGF0ZV90ZXh0KQogICAg"
    "ICAgICAgICAgICAgICAgIHJvdXRlZF90YXJnZXQgPSAiaW5wdXRfZmllbGRfaW5zZXJ0IgogICAgICAgICAgICAgICAgZWxzZToK"
    "ICAgICAgICAgICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRUZXh0KGRhdGVfdGV4dCkKICAgICAgICAgICAgICAgICAg"
    "ICByb3V0ZWRfdGFyZ2V0ID0gImlucHV0X2ZpZWxkX3NldCIKCiAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIp"
    "IGFuZCBzZWxmLl90YXNrc190YWIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zdGF0dXNfbGFiZWwu"
    "c2V0VGV4dChmIkNhbGVuZGFyIGRhdGUgc2VsZWN0ZWQ6IHtkYXRlX3RleHR9IikKCiAgICAgICAgaWYgaGFzYXR0cihzZWxmLCAi"
    "X2RpYWdfdGFiIikgYW5kIHNlbGYuX2RpYWdfdGFiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "CiAgICAgICAgICAgICAgICBmIltDQUxFTkRBUl0gbWluaSBjYWxlbmRhciBjbGljayByb3V0ZWQ6IGRhdGU9e2RhdGVfdGV4dH0s"
    "IHRhcmdldD17cm91dGVkX3RhcmdldH0uIiwKICAgICAgICAgICAgICAgICJJTkZPIgogICAgICAgICAgICApCgogICAgZGVmIF9w"
    "b2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoc2VsZiwgZm9yY2Vfb25jZTogYm9vbCA9IEZhbHNlKToKICAgICAgICAi"
    "IiIKICAgICAgICBTeW5jIEdvb2dsZSBDYWxlbmRhciBldmVudHMg4oaSIGxvY2FsIHRhc2tzIHVzaW5nIEdvb2dsZSdzIHN5bmNU"
    "b2tlbiBBUEkuCgogICAgICAgIFN0YWdlIDEgKGZpcnN0IHJ1biAvIGZvcmNlZCk6IEZ1bGwgZmV0Y2gsIHN0b3JlcyBuZXh0U3lu"
    "Y1Rva2VuLgogICAgICAgIFN0YWdlIDIgKGV2ZXJ5IHBvbGwpOiAgICAgICAgIEluY3JlbWVudGFsIGZldGNoIHVzaW5nIHN0b3Jl"
    "ZCBzeW5jVG9rZW4g4oCUCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJucyBPTkxZIHdoYXQgY2hh"
    "bmdlZCAoYWRkcy9lZGl0cy9jYW5jZWxzKS4KICAgICAgICBJZiBzZXJ2ZXIgcmV0dXJucyA0MTAgR29uZSAodG9rZW4gZXhwaXJl"
    "ZCksIGZhbGxzIGJhY2sgdG8gZnVsbCBzeW5jLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBmb3JjZV9vbmNlIGFuZCBub3Qg"
    "Ym9vbChDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KS5nZXQoImdvb2dsZV9zeW5jX2VuYWJsZWQiLCBUcnVlKSk6CiAgICAgICAgICAg"
    "IHJldHVybiAwCgogICAgICAgIHRyeToKICAgICAgICAgICAgbm93X2lzbyA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICB0"
    "YXNrcyA9IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkKICAgICAgICAgICAgdGFza3NfYnlfZXZlbnRfaWQgPSB7CiAgICAgICAgICAg"
    "ICAgICAodC5nZXQoImdvb2dsZV9ldmVudF9pZCIpIG9yICIiKS5zdHJpcCgpOiB0CiAgICAgICAgICAgICAgICBmb3IgdCBpbiB0"
    "YXNrcwogICAgICAgICAgICAgICAgaWYgKHQuZ2V0KCJnb29nbGVfZXZlbnRfaWQiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAg"
    "ICB9CgogICAgICAgICAgICAjIOKUgOKUgCBGZXRjaCBmcm9tIEdvb2dsZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgICAgICAgICAgc3RvcmVkX3Rva2VuID0gc2VsZi5fc3RhdGUuZ2V0KCJnb29nbGVfY2Fs"
    "ZW5kYXJfc3luY190b2tlbiIpCgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBzdG9yZWRfdG9rZW4gYW5kIG5v"
    "dCBmb3JjZV9vbmNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIltHT09HTEVdW1NZTkNdIEluY3JlbWVudGFsIHN5bmMgKHN5bmNUb2tlbikuIiwgIklORk8iCiAgICAgICAgICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICAgICAgICAgIHJlbW90ZV9ldmVudHMsIG5leHRfdG9rZW4gPSBzZWxmLl9nY2FsLmxpc3RfcHJpbWFy"
    "eV9ldmVudHMoCiAgICAgICAgICAgICAgICAgICAgICAgIHN5bmNfdG9rZW49c3RvcmVkX3Rva2VuCiAgICAgICAgICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJbR09PR0xFXVtTWU5DXSBGdWxsIHN5bmMgKG5vIHN0b3JlZCB0b2tlbikuIiwgIklORk8iCiAgICAg"
    "ICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIG5vd191dGMgPSBkYXRldGltZS51dGNub3coKS5yZXBsYWNlKG1p"
    "Y3Jvc2Vjb25kPTApCiAgICAgICAgICAgICAgICAgICAgdGltZV9taW4gPSAobm93X3V0YyAtIHRpbWVkZWx0YShkYXlzPTM2NSkp"
    "Lmlzb2Zvcm1hdCgpICsgIloiCiAgICAgICAgICAgICAgICAgICAgcmVtb3RlX2V2ZW50cywgbmV4dF90b2tlbiA9IHNlbGYuX2dj"
    "YWwubGlzdF9wcmltYXJ5X2V2ZW50cygKICAgICAgICAgICAgICAgICAgICAgICAgdGltZV9taW49dGltZV9taW4KICAgICAgICAg"
    "ICAgICAgICAgICApCgogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGFwaV9leDoKICAgICAgICAgICAgICAgIGlmICI0"
    "MTAiIGluIHN0cihhcGlfZXgpIG9yICJHb25lIiBpbiBzdHIoYXBpX2V4KToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgICAgICJbR09PR0xFXVtTWU5DXSBzeW5jVG9rZW4gZXhwaXJlZCAoNDEwKSDi"
    "gJQgZnVsbCByZXN5bmMuIiwgIldBUk4iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIHNlbGYuX3N0"
    "YXRlLnBvcCgiZ29vZ2xlX2NhbGVuZGFyX3N5bmNfdG9rZW4iLCBOb25lKQogICAgICAgICAgICAgICAgICAgIG5vd191dGMgPSBk"
    "YXRldGltZS51dGNub3coKS5yZXBsYWNlKG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgICAgICAgICAgdGltZV9taW4gPSAobm93"
    "X3V0YyAtIHRpbWVkZWx0YShkYXlzPTM2NSkpLmlzb2Zvcm1hdCgpICsgIloiCiAgICAgICAgICAgICAgICAgICAgcmVtb3RlX2V2"
    "ZW50cywgbmV4dF90b2tlbiA9IHNlbGYuX2djYWwubGlzdF9wcmltYXJ5X2V2ZW50cygKICAgICAgICAgICAgICAgICAgICAgICAg"
    "dGltZV9taW49dGltZV9taW4KICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAg"
    "ICAgICAgIHJhaXNlCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NZ"
    "TkNdIFJlY2VpdmVkIHtsZW4ocmVtb3RlX2V2ZW50cyl9IGV2ZW50KHMpLiIsICJJTkZPIgogICAgICAgICAgICApCgogICAgICAg"
    "ICAgICAjIFNhdmUgbmV3IHRva2VuIGZvciBuZXh0IGluY3JlbWVudGFsIGNhbGwKICAgICAgICAgICAgaWYgbmV4dF90b2tlbjoK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJnb29nbGVfY2FsZW5kYXJfc3luY190b2tlbiJdID0gbmV4dF90b2tlbgogICAg"
    "ICAgICAgICAgICAgc2VsZi5fbWVtb3J5LnNhdmVfc3RhdGUoc2VsZi5fc3RhdGUpCgogICAgICAgICAgICAjIOKUgOKUgCBQcm9j"
    "ZXNzIGV2ZW50cyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICAgICAgaW1wb3J0ZWRfY291bnQgPSB1cGRhdGVkX2NvdW50ID0gcmVtb3ZlZF9jb3VudCA9IDAKICAgICAgICAgICAgY2hh"
    "bmdlZCA9IEZhbHNlCgogICAgICAgICAgICBmb3IgZXZlbnQgaW4gcmVtb3RlX2V2ZW50czoKICAgICAgICAgICAgICAgIGV2ZW50"
    "X2lkID0gKGV2ZW50LmdldCgiaWQiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAgICAgICAgaWYgbm90IGV2ZW50X2lkOgogICAg"
    "ICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICAgICAgIyBEZWxldGVkIC8gY2FuY2VsbGVkIG9uIEdvb2dsZSdz"
    "IHNpZGUKICAgICAgICAgICAgICAgIGlmIGV2ZW50LmdldCgic3RhdHVzIikgPT0gImNhbmNlbGxlZCI6CiAgICAgICAgICAgICAg"
    "ICAgICAgZXhpc3RpbmcgPSB0YXNrc19ieV9ldmVudF9pZC5nZXQoZXZlbnRfaWQpCiAgICAgICAgICAgICAgICAgICAgaWYgZXhp"
    "c3RpbmcgYW5kIGV4aXN0aW5nLmdldCgic3RhdHVzIikgbm90IGluICgiY2FuY2VsbGVkIiwgImNvbXBsZXRlZCIpOgogICAgICAg"
    "ICAgICAgICAgICAgICAgICBleGlzdGluZ1sic3RhdHVzIl0gICAgICAgICA9ICJjYW5jZWxsZWQiCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGV4aXN0aW5nWyJjYW5jZWxsZWRfYXQiXSAgID0gbm93X2lzbwogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGlu"
    "Z1sic3luY19zdGF0dXMiXSAgICA9ICJkZWxldGVkX3JlbW90ZSIKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbImxh"
    "c3Rfc3luY2VkX2F0Il0gPSBub3dfaXNvCiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nLnNldGRlZmF1bHQoIm1ldGFk"
    "YXRhIiwge30pWyJnb29nbGVfZGVsZXRlZF9yZW1vdGUiXSA9IG5vd19pc28KICAgICAgICAgICAgICAgICAgICAgICAgcmVtb3Zl"
    "ZF9jb3VudCArPSAxCiAgICAgICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1lOQ10gUmVtb3ZlZDog"
    "e2V4aXN0aW5nLmdldCgndGV4dCcsJz8nKX0iLCAiSU5GTyIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAg"
    "ICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICAgICAgc3VtbWFyeSA9IChldmVudC5nZXQoInN1bW1hcnkiKSBvciAiR29vZ2xl"
    "IENhbGVuZGFyIEV2ZW50Iikuc3RyaXAoKSBvciAiR29vZ2xlIENhbGVuZGFyIEV2ZW50IgogICAgICAgICAgICAgICAgZHVlX2F0"
    "ICA9IHNlbGYuX2dvb2dsZV9ldmVudF9kdWVfZGF0ZXRpbWUoZXZlbnQpCiAgICAgICAgICAgICAgICBleGlzdGluZyA9IHRhc2tz"
    "X2J5X2V2ZW50X2lkLmdldChldmVudF9pZCkKCiAgICAgICAgICAgICAgICBpZiBleGlzdGluZzoKICAgICAgICAgICAgICAgICAg"
    "ICAjIFVwZGF0ZSBpZiBhbnl0aGluZyBjaGFuZ2VkCiAgICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gRmFsc2UKICAg"
    "ICAgICAgICAgICAgICAgICBpZiAoZXhpc3RpbmcuZ2V0KCJ0ZXh0Iikgb3IgIiIpLnN0cmlwKCkgIT0gc3VtbWFyeToKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbInRleHQiXSA9IHN1bW1hcnkKICAgICAgICAgICAgICAgICAgICAgICAgdGFza19j"
    "aGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIGlmIGR1ZV9hdDoKICAgICAgICAgICAgICAgICAgICAgICAgZHVlX2lz"
    "byA9IGR1ZV9hdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBleGlzdGlu"
    "Zy5nZXQoImR1ZV9hdCIpICE9IGR1ZV9pc286CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1siZHVlX2F0Il0g"
    "ICAgICAgPSBkdWVfaXNvCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sicHJlX3RyaWdnZXIiXSAgPSAoZHVl"
    "X2F0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICB0YXNrX2NoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgaWYgZXhpc3RpbmcuZ2V0KCJzeW5jX3N0"
    "YXR1cyIpICE9ICJzeW5jZWQiOgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sic3luY19zdGF0dXMiXSA9ICJzeW5j"
    "ZWQiCiAgICAgICAgICAgICAgICAgICAgICAgIHRhc2tfY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgICAgICBpZiB0YXNr"
    "X2NoYW5nZWQ6CiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJsYXN0X3N5bmNlZF9hdCJdID0gbm93X2lzbwogICAg"
    "ICAgICAgICAgICAgICAgICAgICB1cGRhdGVkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRy"
    "dWUKICAgICAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ZiJbR09PR0xFXVtTWU5DXSBVcGRhdGVkOiB7c3VtbWFyeX0iLCAiSU5GTyIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICAjIE5ldyBldmVudAogICAgICAgICAgICAgICAgICAgIGlmIG5v"
    "dCBkdWVfYXQ6CiAgICAgICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICAgICAgICAgbmV3X3Rhc2sgPSB7"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAgICAgICAgIGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBd"
    "fSIsCiAgICAgICAgICAgICAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgICAgIG5vd19pc28sCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICJkdWVfYXQiOiAgICAgICAgICAgIGR1ZV9hdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgInByZV90cmlnZ2VyIjogICAgICAgKGR1ZV9hdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpKS5pc29mb3Jt"
    "YXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAgICAgInRleHQiOiAgICAgICAgICAgICAgc3VtbWFy"
    "eSwKICAgICAgICAgICAgICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgICAgICAgInBlbmRpbmciLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAiYWNrbm93bGVkZ2VkX2F0IjogICBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAicmV0cnlfY291bnQiOiAg"
    "ICAgICAwLAogICAgICAgICAgICAgICAgICAgICAgICAibGFzdF90cmlnZ2VyZWRfYXQiOiBOb25lLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAibmV4dF9yZXRyeV9hdCI6ICAgICBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6"
    "ICAgICBGYWxzZSwKICAgICAgICAgICAgICAgICAgICAgICAgInNvdXJjZSI6ICAgICAgICAgICAgImdvb2dsZSIsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJnb29nbGVfZXZlbnRfaWQiOiAgIGV2ZW50X2lkLAogICAgICAgICAgICAgICAgICAgICAgICAic3lu"
    "Y19zdGF0dXMiOiAgICAgICAic3luY2VkIiwKICAgICAgICAgICAgICAgICAgICAgICAgImxhc3Rfc3luY2VkX2F0IjogICAgbm93"
    "X2lzbywKICAgICAgICAgICAgICAgICAgICAgICAgIm1ldGFkYXRhIjogewogICAgICAgICAgICAgICAgICAgICAgICAgICAgImdv"
    "b2dsZV9pbXBvcnRlZF9hdCI6IG5vd19pc28sCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAiZ29vZ2xlX3VwZGF0ZWQiOiAg"
    "ICAgZXZlbnQuZ2V0KCJ1cGRhdGVkIiksCiAgICAgICAgICAgICAgICAgICAgICAgIH0sCiAgICAgICAgICAgICAgICAgICAgfQog"
    "ICAgICAgICAgICAgICAgICAgIHRhc2tzLmFwcGVuZChuZXdfdGFzaykKICAgICAgICAgICAgICAgICAgICB0YXNrc19ieV9ldmVu"
    "dF9pZFtldmVudF9pZF0gPSBuZXdfdGFzawogICAgICAgICAgICAgICAgICAgIGltcG9ydGVkX2NvdW50ICs9IDEKICAgICAgICAg"
    "ICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVd"
    "W1NZTkNdIEltcG9ydGVkOiB7c3VtbWFyeX0iLCAiSU5GTyIpCgogICAgICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICAg"
    "ICAgc2VsZi5fdGFza3Muc2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5l"
    "bCgpCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NZTkNdIERvbmUg"
    "4oCUIGltcG9ydGVkPXtpbXBvcnRlZF9jb3VudH0gIgogICAgICAgICAgICAgICAgZiJ1cGRhdGVkPXt1cGRhdGVkX2NvdW50fSBy"
    "ZW1vdmVkPXtyZW1vdmVkX2NvdW50fSIsICJJTkZPIgogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybiBpbXBvcnRlZF9j"
    "b3VudAoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09P"
    "R0xFXVtTWU5DXVtFUlJPUl0ge2V4fSIsICJFUlJPUiIpCiAgICAgICAgICAgIHJldHVybiAwCgoKICAgIGRlZiBfbWVhc3VyZV92"
    "cmFtX2Jhc2VsaW5lKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICAgICAgbWVtID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9kZWNrX3ZyYW1fYmFzZSA9IG1lbS51c2VkIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1ZSQU1dIEJhc2VsaW5lIG1lYXN1cmVkOiB7c2VsZi5fZGVja192"
    "cmFtX2Jhc2U6LjJmfUdCICIKICAgICAgICAgICAgICAgICAgICBmIih7REVDS19OQU1FfSdzIGZvb3RwcmludCkiLCAiSU5GTyIK"
    "ICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAj"
    "IOKUgOKUgCBNRVNTQUdFIEhBTkRMSU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9zZW5kX21lc3NhZ2Uoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICBpZiBub3Qgc2VsZi5fbW9kZWxfbG9hZGVkIG9yIHNlbGYuX3RvcnBvcl9zdGF0ZSA9PSAiU1VTUEVORCI6CiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIHRleHQgPSBzZWxmLl9pbnB1dF9maWVsZC50ZXh0KCkuc3RyaXAoKQogICAgICAgIGlm"
    "IG5vdCB0ZXh0OgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgIyBGbGlwIGJhY2sgdG8gcGVyc29uYSBjaGF0IHRhYiBmcm9t"
    "IFNlbGYgdGFiIGlmIG5lZWRlZAogICAgICAgIGlmIHNlbGYuX21haW5fdGFicy5jdXJyZW50SW5kZXgoKSAhPSAwOgogICAgICAg"
    "ICAgICBzZWxmLl9tYWluX3RhYnMuc2V0Q3VycmVudEluZGV4KDApCgogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLmNsZWFyKCkK"
    "ICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiWU9VIiwgdGV4dCkKCiAgICAgICAgIyBTZXNzaW9uIGxvZ2dpbmcKICAgICAgICBz"
    "ZWxmLl9zZXNzaW9ucy5hZGRfbWVzc2FnZSgidXNlciIsIHRleHQpCiAgICAgICAgc2VsZi5fbWVtb3J5LmFwcGVuZF9tZXNzYWdl"
    "KHNlbGYuX3Nlc3Npb25faWQsICJ1c2VyIiwgdGV4dCkKCiAgICAgICAgIyBJbnRlcnJ1cHQgZmFjZSB0aW1lciDigJQgc3dpdGNo"
    "IHRvIGFsZXJ0IGltbWVkaWF0ZWx5CiAgICAgICAgaWYgc2VsZi5fZmFjZV90aW1lcl9tZ3I6CiAgICAgICAgICAgIHNlbGYuX2Zh"
    "Y2VfdGltZXJfbWdyLmludGVycnVwdCgiYWxlcnQiKQoKICAgICAgICAjIEJ1aWxkIHByb21wdCB3aXRoIHZhbXBpcmUgY29udGV4"
    "dCArIG1lbW9yeSBjb250ZXh0CiAgICAgICAgdmFtcGlyZV9jdHggID0gYnVpbGRfdmFtcGlyZV9jb250ZXh0KCkKICAgICAgICBt"
    "ZW1vcnlfY3R4ICAgPSBzZWxmLl9tZW1vcnkuYnVpbGRfY29udGV4dF9ibG9jayh0ZXh0KQogICAgICAgIGpvdXJuYWxfY3R4ICA9"
    "ICIiCgogICAgICAgIGlmIHNlbGYuX3Nlc3Npb25zLmxvYWRlZF9qb3VybmFsX2RhdGU6CiAgICAgICAgICAgIGpvdXJuYWxfY3R4"
    "ID0gc2VsZi5fc2Vzc2lvbnMubG9hZF9zZXNzaW9uX2FzX2NvbnRleHQoCiAgICAgICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5s"
    "b2FkZWRfam91cm5hbF9kYXRlCiAgICAgICAgICAgICkKCiAgICAgICAgIyBCdWlsZCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgc3lz"
    "dGVtID0gU1lTVEVNX1BST01QVF9CQVNFCiAgICAgICAgaWYgbWVtb3J5X2N0eDoKICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5c"
    "bnttZW1vcnlfY3R4fSIKICAgICAgICBpZiBqb3VybmFsX2N0eDoKICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5cbntqb3VybmFs"
    "X2N0eH0iCiAgICAgICAgc3lzdGVtICs9IHZhbXBpcmVfY3R4CgogICAgICAgICMgTGVzc29ucyBjb250ZXh0IGZvciBjb2RlLWFk"
    "amFjZW50IGlucHV0CiAgICAgICAgaWYgYW55KGt3IGluIHRleHQubG93ZXIoKSBmb3Iga3cgaW4gKCJsc2wiLCJweXRob24iLCJz"
    "Y3JpcHQiLCJjb2RlIiwiZnVuY3Rpb24iKSk6CiAgICAgICAgICAgIGxhbmcgPSAiTFNMIiBpZiAibHNsIiBpbiB0ZXh0Lmxvd2Vy"
    "KCkgZWxzZSAiUHl0aG9uIgogICAgICAgICAgICBsZXNzb25zX2N0eCA9IHNlbGYuX2xlc3NvbnMuYnVpbGRfY29udGV4dF9mb3Jf"
    "bGFuZ3VhZ2UobGFuZykKICAgICAgICAgICAgaWYgbGVzc29uc19jdHg6CiAgICAgICAgICAgICAgICBzeXN0ZW0gKz0gZiJcblxu"
    "e2xlc3NvbnNfY3R4fSIKCiAgICAgICAgIyBBZGQgcGVuZGluZyB0cmFuc21pc3Npb25zIGNvbnRleHQgaWYgYW55CiAgICAgICAg"
    "aWYgc2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zID4gMDoKICAgICAgICAgICAgZHVyID0gc2VsZi5fc3VzcGVuZGVkX2R1cmF0"
    "aW9uIG9yICJzb21lIHRpbWUiCiAgICAgICAgICAgIHN5c3RlbSArPSAoCiAgICAgICAgICAgICAgICBmIlxuXG5bUkVUVVJOIEZS"
    "T00gVE9SUE9SXVxuIgogICAgICAgICAgICAgICAgZiJZb3Ugd2VyZSBpbiB0b3Jwb3IgZm9yIHtkdXJ9LiAiCiAgICAgICAgICAg"
    "ICAgICBmIntzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnN9IHRob3VnaHRzIHdlbnQgdW5zcG9rZW4gIgogICAgICAgICAgICAg"
    "ICAgZiJkdXJpbmcgdGhhdCB0aW1lLiBBY2tub3dsZWRnZSB0aGlzIGJyaWVmbHkgaW4gY2hhcmFjdGVyICIKICAgICAgICAgICAg"
    "ICAgIGYiaWYgaXQgZmVlbHMgbmF0dXJhbC4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fcGVuZGluZ190cmFuc21p"
    "c3Npb25zID0gMAogICAgICAgICAgICBzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gICAgPSAiIgoKICAgICAgICBoaXN0b3J5ID0g"
    "c2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQoKICAgICAgICAjIERpc2FibGUgaW5wdXQKICAgICAgICBzZWxmLl9zZW5kX2J0"
    "bi5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2Vs"
    "Zi5fc2V0X3N0YXR1cygiR0VORVJBVElORyIpCgogICAgICAgICMgU3RvcCBpZGxlIHRpbWVyIGR1cmluZyBnZW5lcmF0aW9uCiAg"
    "ICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5p"
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
    "ZGxlIHRpbWVyCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2No"
    "ZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5yZXN1bWVfam9i"
    "KCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgog"
    "ICAgICAgICMgU2NoZWR1bGUgc2VudGltZW50IGFuYWx5c2lzICg1IHNlY29uZCBkZWxheSkKICAgICAgICBRVGltZXIuc2luZ2xl"
    "U2hvdCg1MDAwLCBsYW1iZGE6IHNlbGYuX3J1bl9zZW50aW1lbnQocmVzcG9uc2UpKQoKICAgIGRlZiBfcnVuX3NlbnRpbWVudChz"
    "ZWxmLCByZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAg"
    "IHJldHVybgogICAgICAgIHNlbGYuX3NlbnRfd29ya2VyID0gU2VudGltZW50V29ya2VyKHNlbGYuX2FkYXB0b3IsIHJlc3BvbnNl"
    "KQogICAgICAgIHNlbGYuX3NlbnRfd29ya2VyLmZhY2VfcmVhZHkuY29ubmVjdChzZWxmLl9vbl9zZW50aW1lbnQpCiAgICAgICAg"
    "c2VsZi5fc2VudF93b3JrZXIuc3RhcnQoKQoKICAgIGRlZiBfb25fc2VudGltZW50KHNlbGYsIGVtb3Rpb246IHN0cikgLT4gTm9u"
    "ZToKICAgICAgICBpZiBzZWxmLl9mYWNlX3RpbWVyX21ncjoKICAgICAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3Iuc2V0X2Zh"
    "Y2UoZW1vdGlvbikKCiAgICBkZWYgX29uX2Vycm9yKHNlbGYsIGVycm9yOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXBw"
    "ZW5kX2NoYXQoIkVSUk9SIiwgZXJyb3IpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dFTkVSQVRJT04gRVJST1JdIHtl"
    "cnJvcn0iLCAiRVJST1IiKQogICAgICAgIGlmIHNlbGYuX2ZhY2VfdGltZXJfbWdyOgogICAgICAgICAgICBzZWxmLl9mYWNlX3Rp"
    "bWVyX21nci5zZXRfZmFjZSgicGFuaWNrZWQiKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkVSUk9SIikKICAgICAgICBzZWxm"
    "Ll9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQoKICAg"
    "ICMg4pSA4pSAIFRPUlBPUiBTWVNURU0g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX29uX3RvcnBvcl9zdGF0ZV9j"
    "aGFuZ2VkKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fdG9ycG9yX3N0YXRlID0gc3RhdGUKCiAgICAg"
    "ICAgaWYgc3RhdGUgPT0gIlNVU1BFTkQiOgogICAgICAgICAgICBzZWxmLl9lbnRlcl90b3Jwb3IocmVhc29uPSJtYW51YWwg4oCU"
    "IFNVU1BFTkQgbW9kZSBzZWxlY3RlZCIpCiAgICAgICAgZWxpZiBzdGF0ZSA9PSAiQVdBS0UiOgogICAgICAgICAgICAjIEFsd2F5"
    "cyBleGl0IHRvcnBvciB3aGVuIHN3aXRjaGluZyB0byBBV0FLRSDigJQKICAgICAgICAgICAgIyBldmVuIHdpdGggT2xsYW1hIGJh"
    "Y2tlbmQgd2hlcmUgbW9kZWwgaXNuJ3QgdW5sb2FkZWQsCiAgICAgICAgICAgICMgd2UgbmVlZCB0byByZS1lbmFibGUgVUkgYW5k"
    "IHJlc2V0IHN0YXRlCiAgICAgICAgICAgIHNlbGYuX2V4aXRfdG9ycG9yKCkKICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3Vy"
    "ZV90aWNrcyA9IDAKICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgICA9IDAKICAgICAgICBlbGlmIHN0YXRlID09"
    "ICJBVVRPIjoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIltUT1JQT1JdIEFVVE8gbW9k"
    "ZSDigJQgbW9uaXRvcmluZyBWUkFNIHByZXNzdXJlLiIsICJJTkZPIgogICAgICAgICAgICApCgogICAgZGVmIF9lbnRlcl90b3Jw"
    "b3Ioc2VsZiwgcmVhc29uOiBzdHIgPSAibWFudWFsIikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMg"
    "bm90IE5vbmU6CiAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5IGluIHRvcnBvcgoKICAgICAgICBzZWxmLl90b3Jwb3Jfc2lu"
    "Y2UgPSBkYXRldGltZS5ub3coKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUT1JQT1JdIEVudGVyaW5nIHRvcnBvcjog"
    "e3JlYXNvbn0iLCAiV0FSTiIpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsICJUaGUgdmVzc2VsIGdyb3dzIGNy"
    "b3dkZWQuIEkgd2l0aGRyYXcuIikKCiAgICAgICAgIyBVbmxvYWQgbW9kZWwgZnJvbSBWUkFNCiAgICAgICAgaWYgc2VsZi5fbW9k"
    "ZWxfbG9hZGVkIGFuZCBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBz"
    "ZWxmLl9hZGFwdG9yLl9tb2RlbCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICBkZWwgc2VsZi5fYWRhcHRvci5fbW9k"
    "ZWwKICAgICAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLl9tb2RlbCA9IE5vbmUKICAgICAgICAgICAgICAgIGlmIFRPUkNI"
    "X09LOgogICAgICAgICAgICAgICAgICAgIHRvcmNoLmN1ZGEuZW1wdHlfY2FjaGUoKQogICAgICAgICAgICAgICAgc2VsZi5fYWRh"
    "cHRvci5fbG9hZGVkID0gRmFsc2UKICAgICAgICAgICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCAgICA9IEZhbHNlCiAgICAgICAg"
    "ICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIE1vZGVsIHVubG9hZGVkIGZyb20gVlJBTS4iLCAiT0siKQogICAg"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAg"
    "ICAgICAgICAgICAgZiJbVE9SUE9SXSBNb2RlbCB1bmxvYWQgZXJyb3I6IHtlfSIsICJFUlJPUiIKICAgICAgICAgICAgICAgICkK"
    "CiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKCJuZXV0cmFsIikKICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJUT1JQT1Ii"
    "KQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5h"
    "YmxlZChGYWxzZSkKCiAgICBkZWYgX2V4aXRfdG9ycG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBDYWxjdWxhdGUgc3VzcGVu"
    "ZGVkIGR1cmF0aW9uCiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlOgogICAgICAgICAgICBkZWx0YSA9IGRhdGV0aW1lLm5v"
    "dygpIC0gc2VsZi5fdG9ycG9yX3NpbmNlCiAgICAgICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiA9IGZvcm1hdF9kdXJh"
    "dGlvbihkZWx0YS50b3RhbF9zZWNvbmRzKCkpCiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9zaW5jZSA9IE5vbmUKCiAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKCJbVE9SUE9SXSBXYWtpbmcgZnJvbSB0b3Jwb3IuLi4iLCAiSU5GTyIpCgogICAgICAgIGlmIHNl"
    "bGYuX21vZGVsX2xvYWRlZDoKICAgICAgICAgICAgIyBPbGxhbWEgYmFja2VuZCDigJQgbW9kZWwgd2FzIG5ldmVyIHVubG9hZGVk"
    "LCBqdXN0IHJlLWVuYWJsZSBVSQogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAg"
    "IGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7REVDS19OQU1FfSBzdGlycyAiCiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVu"
    "ZGVkX2R1cmF0aW9uIG9yICdicmllZmx5J30gZWxhcHNlZCkuIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2FwcGVu"
    "ZF9jaGF0KCJTWVNURU0iLCAiVGhlIGNvbm5lY3Rpb24gaG9sZHMuIFNoZSBpcyBsaXN0ZW5pbmcuIikKICAgICAgICAgICAgc2Vs"
    "Zi5fc2V0X3N0YXR1cygiSURMRSIpCiAgICAgICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAg"
    "ICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQ"
    "T1JdIEFXQUtFIG1vZGUg4oCUIGF1dG8tdG9ycG9yIGRpc2FibGVkLiIsICJJTkZPIikKICAgICAgICBlbHNlOgogICAgICAgICAg"
    "ICAjIExvY2FsIG1vZGVsIHdhcyB1bmxvYWRlZCDigJQgbmVlZCBmdWxsIHJlbG9hZAogICAgICAgICAgICBzZWxmLl9hcHBlbmRf"
    "Y2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7REVDS19OQU1FfSBzdGlycyBmcm9t"
    "IHRvcnBvciAiCiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICdicmllZmx5J30gZWxhcHNl"
    "ZCkuIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkxPQURJTkciKQogICAgICAgICAgICBzZWxm"
    "Ll9sb2FkZXIgPSBNb2RlbExvYWRlcldvcmtlcihzZWxmLl9hZGFwdG9yKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIubWVzc2Fn"
    "ZS5jb25uZWN0KAogICAgICAgICAgICAgICAgbGFtYmRhIG06IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBtKSkKICAgICAg"
    "ICAgICAgc2VsZi5fbG9hZGVyLmVycm9yLmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fYXBwZW5kX2No"
    "YXQoIkVSUk9SIiwgZSkpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5sb2FkX2NvbXBsZXRlLmNvbm5lY3Qoc2VsZi5fb25fbG9h"
    "ZF9jb21wbGV0ZSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxh"
    "dGVyKQogICAgICAgICAgICBzZWxmLl9hY3RpdmVfdGhyZWFkcy5hcHBlbmQoc2VsZi5fbG9hZGVyKQogICAgICAgICAgICBzZWxm"
    "Ll9sb2FkZXIuc3RhcnQoKQoKICAgIGRlZiBfY2hlY2tfdnJhbV9wcmVzc3VyZShzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgog"
    "ICAgICAgIENhbGxlZCBldmVyeSA1IHNlY29uZHMgZnJvbSBBUFNjaGVkdWxlciB3aGVuIHRvcnBvciBzdGF0ZSBpcyBBVVRPLgog"
    "ICAgICAgIE9ubHkgdHJpZ2dlcnMgdG9ycG9yIGlmIGV4dGVybmFsIFZSQU0gdXNhZ2UgZXhjZWVkcyB0aHJlc2hvbGQKICAgICAg"
    "ICBBTkQgaXMgc3VzdGFpbmVkIOKAlCBuZXZlciB0cmlnZ2VycyBvbiB0aGUgcGVyc29uYSdzIG93biBmb290cHJpbnQuCiAgICAg"
    "ICAgIiIiCiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3N0YXRlICE9ICJBVVRPIjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAg"
    "aWYgbm90IE5WTUxfT0sgb3Igbm90IGdwdV9oYW5kbGU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIHNlbGYuX2RlY2tf"
    "dnJhbV9iYXNlIDw9IDA6CiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIG1lbV9pbmZvICA9IHB5"
    "bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICB0b3RhbF91c2VkID0gbWVtX2luZm8u"
    "dXNlZCAvIDEwMjQqKjMKICAgICAgICAgICAgZXh0ZXJuYWwgICA9IHRvdGFsX3VzZWQgLSBzZWxmLl9kZWNrX3ZyYW1fYmFzZQoK"
    "ICAgICAgICAgICAgaWYgZXh0ZXJuYWwgPiBzZWxmLl9FWFRFUk5BTF9WUkFNX1RPUlBPUl9HQjoKICAgICAgICAgICAgICAgIGlm"
    "IHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICByZXR1cm4gICMgQWxyZWFkeSBpbiB0"
    "b3Jwb3Ig4oCUIGRvbid0IGtlZXAgY291bnRpbmcKICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgKz0g"
    "MQogICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgICAgPSAwCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9dIEV4dGVybmFsIFZSQU0gcHJlc3N1cmU6ICIKICAg"
    "ICAgICAgICAgICAgICAgICBmIntleHRlcm5hbDouMmZ9R0IgIgogICAgICAgICAgICAgICAgICAgIGYiKHRpY2sge3NlbGYuX3Zy"
    "YW1fcHJlc3N1cmVfdGlja3N9LyIKICAgICAgICAgICAgICAgICAgICBmIntzZWxmLl9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTfSki"
    "LCAiV0FSTiIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIChzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID49"
    "IHNlbGYuX1RPUlBPUl9TVVNUQUlORURfVElDS1MKICAgICAgICAgICAgICAgICAgICAgICAgYW5kIHNlbGYuX3RvcnBvcl9zaW5j"
    "ZSBpcyBOb25lKToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9lbnRlcl90b3Jwb3IoCiAgICAgICAgICAgICAgICAgICAgICAg"
    "IHJlYXNvbj1mImF1dG8g4oCUIHtleHRlcm5hbDouMWZ9R0IgZXh0ZXJuYWwgVlJBTSAiCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICBmInByZXNzdXJlIHN1c3RhaW5lZCIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgc2Vs"
    "Zi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9IDAgICMgcmVzZXQgYWZ0ZXIgZW50ZXJpbmcgdG9ycG9yCiAgICAgICAgICAgIGVsc2U6"
    "CiAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMAogICAgICAgICAgICAgICAgaWYgc2VsZi5fdG9y"
    "cG9yX3NpbmNlIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICs9IDEKICAg"
    "ICAgICAgICAgICAgICAgICBhdXRvX3dha2UgPSBDRkdbInNldHRpbmdzIl0uZ2V0KAogICAgICAgICAgICAgICAgICAgICAgICAi"
    "YXV0b193YWtlX29uX3JlbGllZiIsIEZhbHNlCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIGlmIChh"
    "dXRvX3dha2UgYW5kCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyA+PSBzZWxmLl9X"
    "QUtFX1NVU1RBSU5FRF9USUNLUyk6CiAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzID0gMAog"
    "ICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl9leGl0X3RvcnBvcigpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToK"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9dIFZSQU0gY2hlY2sg"
    "ZXJyb3I6IHtlfSIsICJFUlJPUiIKICAgICAgICAgICAgKQoKICAgICMg4pSA4pSAIEFQU0NIRURVTEVSIFNFVFVQIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgZGVmIF9zZXR1cF9zY2hlZHVsZXIoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGZyb20g"
    "YXBzY2hlZHVsZXIuc2NoZWR1bGVycy5iYWNrZ3JvdW5kIGltcG9ydCBCYWNrZ3JvdW5kU2NoZWR1bGVyCiAgICAgICAgICAgIHNl"
    "bGYuX3NjaGVkdWxlciA9IEJhY2tncm91bmRTY2hlZHVsZXIoCiAgICAgICAgICAgICAgICBqb2JfZGVmYXVsdHM9eyJtaXNmaXJl"
    "X2dyYWNlX3RpbWUiOiA2MH0KICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgc2Vs"
    "Zi5fc2NoZWR1bGVyID0gTm9uZQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAiW1NDSEVE"
    "VUxFUl0gYXBzY2hlZHVsZXIgbm90IGF2YWlsYWJsZSDigJQgIgogICAgICAgICAgICAgICAgImlkbGUsIGF1dG9zYXZlLCBhbmQg"
    "cmVmbGVjdGlvbiBkaXNhYmxlZC4iLCAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgaW50"
    "ZXJ2YWxfbWluID0gQ0ZHWyJzZXR0aW5ncyJdLmdldCgiYXV0b3NhdmVfaW50ZXJ2YWxfbWludXRlcyIsIDEwKQoKICAgICAgICAj"
    "IEF1dG9zYXZlCiAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAgICAgICAgICAgIHNlbGYuX2F1dG9zYXZlLCAiaW50"
    "ZXJ2YWwiLAogICAgICAgICAgICBtaW51dGVzPWludGVydmFsX21pbiwgaWQ9ImF1dG9zYXZlIgogICAgICAgICkKCiAgICAgICAg"
    "IyBWUkFNIHByZXNzdXJlIGNoZWNrIChldmVyeSA1cykKICAgICAgICBzZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAg"
    "ICAgc2VsZi5fY2hlY2tfdnJhbV9wcmVzc3VyZSwgImludGVydmFsIiwKICAgICAgICAgICAgc2Vjb25kcz01LCBpZD0idnJhbV9j"
    "aGVjayIKICAgICAgICApCgogICAgICAgICMgSWRsZSB0cmFuc21pc3Npb24gKHN0YXJ0cyBwYXVzZWQg4oCUIGVuYWJsZWQgYnkg"
    "aWRsZSB0b2dnbGUpCiAgICAgICAgaWRsZV9taW4gPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJpZGxlX21pbl9taW51dGVzIiwgMTAp"
    "CiAgICAgICAgaWRsZV9tYXggPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJpZGxlX21heF9taW51dGVzIiwgMzApCiAgICAgICAgaWRs"
    "ZV9pbnRlcnZhbCA9IChpZGxlX21pbiArIGlkbGVfbWF4KSAvLyAyCgogICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAog"
    "ICAgICAgICAgICBzZWxmLl9maXJlX2lkbGVfdHJhbnNtaXNzaW9uLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBtaW51dGVzPWlk"
    "bGVfaW50ZXJ2YWwsIGlkPSJpZGxlX3RyYW5zbWlzc2lvbiIKICAgICAgICApCgogICAgICAgICMgQ3ljbGUgd2lkZ2V0IHJlZnJl"
    "c2ggKGV2ZXJ5IDYgaG91cnMpCiAgICAgICAgaWYgc2VsZi5fY3ljbGVfd2lkZ2V0IGlzIG5vdCBOb25lOgogICAgICAgICAgICBz"
    "ZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgICAgIHNlbGYuX2N5Y2xlX3dpZGdldC51cGRhdGVQaGFzZSwgImlu"
    "dGVydmFsIiwKICAgICAgICAgICAgICAgIGhvdXJzPTYsIGlkPSJtb29uX3JlZnJlc2giCiAgICAgICAgICAgICkKCiAgICAgICAg"
    "IyBOT1RFOiBzY2hlZHVsZXIuc3RhcnQoKSBpcyBjYWxsZWQgZnJvbSBzdGFydF9zY2hlZHVsZXIoKQogICAgICAgICMgd2hpY2gg"
    "aXMgdHJpZ2dlcmVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBBRlRFUiB0aGUgd2luZG93CiAgICAgICAgIyBpcyBzaG93biBhbmQg"
    "dGhlIFF0IGV2ZW50IGxvb3AgaXMgcnVubmluZy4KICAgICAgICAjIERvIE5PVCBjYWxsIHNlbGYuX3NjaGVkdWxlci5zdGFydCgp"
    "IGhlcmUuCgogICAgZGVmIHN0YXJ0X3NjaGVkdWxlcihzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCB2"
    "aWEgUVRpbWVyLnNpbmdsZVNob3QgYWZ0ZXIgd2luZG93LnNob3coKSBhbmQgYXBwLmV4ZWMoKSBiZWdpbnMuCiAgICAgICAgRGVm"
    "ZXJyZWQgdG8gZW5zdXJlIFF0IGV2ZW50IGxvb3AgaXMgcnVubmluZyBiZWZvcmUgYmFja2dyb3VuZCB0aHJlYWRzIHN0YXJ0Lgog"
    "ICAgICAgICIiIgogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpCiAgICAgICAgICAgICMgSWRsZSBzdGFydHMgcGF1c2VkCiAg"
    "ICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKCJbU0NIRURVTEVSXSBBUFNjaGVkdWxlciBzdGFydGVkLiIsICJPSyIpCiAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbU0NIRURVTEVSXSBTdGFydCBlcnJvcjoge2V9Iiwg"
    "IkVSUk9SIikKCiAgICBkZWYgX2F1dG9zYXZlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLl9z"
    "ZXNzaW9ucy5zYXZlKCkKICAgICAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoVHJ1"
    "ZSkKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoCiAgICAgICAgICAgICAgICAzMDAwLCBsYW1iZGE6IHNlbGYuX2pvdXJu"
    "YWxfc2lkZWJhci5zZXRfYXV0b3NhdmVfaW5kaWNhdG9yKEZhbHNlKQogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZygiW0FVVE9TQVZFXSBTZXNzaW9uIHNhdmVkLiIsICJJTkZPIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFz"
    "IGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltBVVRPU0FWRV0gRXJyb3I6IHtlfSIsICJFUlJPUiIpCgogICAg"
    "ZGVmIF9maXJlX2lkbGVfdHJhbnNtaXNzaW9uKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuX21vZGVsX2xvYWRl"
    "ZCBvciBzZWxmLl9zdGF0dXMgPT0gIkdFTkVSQVRJTkciOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBzZWxmLl90b3Jw"
    "b3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICMgSW4gdG9ycG9yIOKAlCBjb3VudCB0aGUgcGVuZGluZyB0aG91Z2h0"
    "IGJ1dCBkb24ndCBnZW5lcmF0ZQogICAgICAgICAgICBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgKz0gMQogICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltJRExFXSBJbiB0b3Jwb3Ig4oCUIHBlbmRpbmcgdHJhbnNt"
    "aXNzaW9uICIKICAgICAgICAgICAgICAgIGYiI3tzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnN9IiwgIklORk8iCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIG1vZGUgPSByYW5kb20uY2hvaWNlKFsiREVFUEVOSU5HIiwiQlJBTkNI"
    "SU5HIiwiU1lOVEhFU0lTIl0pCiAgICAgICAgdmFtcGlyZV9jdHggPSBidWlsZF92YW1waXJlX2NvbnRleHQoKQogICAgICAgIGhp"
    "c3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCgogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyID0gSWRsZVdvcmtl"
    "cigKICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwKICAgICAgICAgICAgU1lTVEVNX1BST01QVF9CQVNFLAogICAgICAgICAgICBo"
    "aXN0b3J5LAogICAgICAgICAgICBtb2RlPW1vZGUsCiAgICAgICAgICAgIHZhbXBpcmVfY29udGV4dD12YW1waXJlX2N0eCwKICAg"
    "ICAgICApCiAgICAgICAgZGVmIF9vbl9pZGxlX3JlYWR5KHQ6IHN0cikgLT4gTm9uZToKICAgICAgICAgICAgIyBGbGlwIHRvIFNl"
    "bGYgdGFiIGFuZCBhcHBlbmQgdGhlcmUKICAgICAgICAgICAgc2VsZi5fbWFpbl90YWJzLnNldEN1cnJlbnRJbmRleCgxKQogICAg"
    "ICAgICAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTSIpCiAgICAgICAgICAgIHNlbGYuX3NlbGZfZGlzcGxh"
    "eS5hcHBlbmQoCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4"
    "OyI+JwogICAgICAgICAgICAgICAgZidbe3RzfV0gW3ttb2RlfV08L3NwYW4+PGJyPicKICAgICAgICAgICAgICAgIGYnPHNwYW4g"
    "c3R5bGU9ImNvbG9yOntDX0dPTER9OyI+e3R9PC9zcGFuPjxicj4nCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fc2Vs"
    "Zl90YWIuYXBwZW5kKCJOQVJSQVRJVkUiLCB0KQoKICAgICAgICBzZWxmLl9pZGxlX3dvcmtlci50cmFuc21pc3Npb25fcmVhZHku"
    "Y29ubmVjdChfb25faWRsZV9yZWFkeSkKICAgICAgICBzZWxmLl9pZGxlX3dvcmtlci5lcnJvcl9vY2N1cnJlZC5jb25uZWN0KAog"
    "ICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fZGlhZ190YWIubG9nKGYiW0lETEUgRVJST1JdIHtlfSIsICJFUlJPUiIpCiAgICAg"
    "ICAgKQogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyLnN0YXJ0KCkKCiAgICAjIOKUgOKUgCBKT1VSTkFMIFNFU1NJT04gTE9BRElO"
    "RyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "IGRlZiBfbG9hZF9qb3VybmFsX3Nlc3Npb24oc2VsZiwgZGF0ZV9zdHI6IHN0cikgLT4gTm9uZToKICAgICAgICBjdHggPSBzZWxm"
    "Ll9zZXNzaW9ucy5sb2FkX3Nlc3Npb25fYXNfY29udGV4dChkYXRlX3N0cikKICAgICAgICBpZiBub3QgY3R4OgogICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltKT1VSTkFMXSBObyBzZXNzaW9uIGZvdW5kIGZvciB7ZGF0"
    "ZV9zdHJ9IiwgIldBUk4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRl"
    "YmFyLnNldF9qb3VybmFsX2xvYWRlZChkYXRlX3N0cikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYi"
    "W0pPVVJOQUxdIExvYWRlZCBzZXNzaW9uIGZyb20ge2RhdGVfc3RyfSBhcyBjb250ZXh0LiAiCiAgICAgICAgICAgIGYie0RFQ0tf"
    "TkFNRX0gaXMgbm93IGF3YXJlIG9mIHRoYXQgY29udmVyc2F0aW9uLiIsICJPSyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXBw"
    "ZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgIGYiQSBtZW1vcnkgc3RpcnMuLi4gdGhlIGpvdXJuYWwgb2Yge2RhdGVfc3Ry"
    "fSBvcGVucyBiZWZvcmUgaGVyLiIKICAgICAgICApCiAgICAgICAgIyBOb3RpZnkgTW9yZ2FubmEKICAgICAgICBpZiBzZWxmLl9t"
    "b2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIG5vdGUgPSAoCiAgICAgICAgICAgICAgICBmIltKT1VSTkFMIExPQURFRF0gVGhlIHVz"
    "ZXIgaGFzIG9wZW5lZCB0aGUgam91cm5hbCBmcm9tICIKICAgICAgICAgICAgICAgIGYie2RhdGVfc3RyfS4gQWNrbm93bGVkZ2Ug"
    "dGhpcyBicmllZmx5IOKAlCB5b3Ugbm93IGhhdmUgIgogICAgICAgICAgICAgICAgZiJhd2FyZW5lc3Mgb2YgdGhhdCBjb252ZXJz"
    "YXRpb24uIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdlKCJzeXN0ZW0iLCBub3Rl"
    "KQoKICAgIGRlZiBfY2xlYXJfam91cm5hbF9zZXNzaW9uKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuY2xl"
    "YXJfbG9hZGVkX2pvdXJuYWwoKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0pPVVJOQUxdIEpvdXJuYWwgY29udGV4dCBj"
    "bGVhcmVkLiIsICJJTkZPIikKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgIlRoZSBqb3Vy"
    "bmFsIGNsb3Nlcy4gT25seSB0aGUgcHJlc2VudCByZW1haW5zLiIKICAgICAgICApCgogICAgIyDilIDilIAgU1RBVFMgVVBEQVRF"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF91cGRhdGVfc3RhdHMoc2VsZikgLT4gTm9uZToKICAgICAgICBl"
    "bGFwc2VkID0gaW50KHRpbWUudGltZSgpIC0gc2VsZi5fc2Vzc2lvbl9zdGFydCkKICAgICAgICBoLCBtLCBzID0gZWxhcHNlZCAv"
    "LyAzNjAwLCAoZWxhcHNlZCAlIDM2MDApIC8vIDYwLCBlbGFwc2VkICUgNjAKICAgICAgICBzZXNzaW9uX3N0ciA9IGYie2g6MDJk"
    "fTp7bTowMmR9OntzOjAyZH0iCgogICAgICAgIHNlbGYuX2h3X3BhbmVsLnNldF9zdGF0dXNfbGFiZWxzKAogICAgICAgICAgICBz"
    "ZWxmLl9zdGF0dXMsCiAgICAgICAgICAgIENGR1sibW9kZWwiXS5nZXQoInR5cGUiLCJsb2NhbCIpLnVwcGVyKCksCiAgICAgICAg"
    "ICAgIHNlc3Npb25fc3RyLAogICAgICAgICAgICBzdHIoc2VsZi5fdG9rZW5fY291bnQpLAogICAgICAgICkKICAgICAgICBzZWxm"
    "Ll9od19wYW5lbC51cGRhdGVfc3RhdHMoKQoKICAgICAgICAjIExlZnQgc3BoZXJlID0gYWN0aXZlIHJlc2VydmUgZnJvbSBydW50"
    "aW1lIHRva2VuIHBvb2wKICAgICAgICBsZWZ0X29yYl9maWxsID0gbWluKDEuMCwgc2VsZi5fdG9rZW5fY291bnQgLyA0MDk2LjAp"
    "CiAgICAgICAgaWYgc2VsZi5fbGVmdF9vcmIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2xlZnRfb3JiLnNldEZpbGwo"
    "bGVmdF9vcmJfZmlsbCwgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICMgUmlnaHQgc3BoZXJlID0gVlJBTSBhdmFpbGFiaWxpdHkK"
    "ICAgICAgICBpZiBzZWxmLl9yaWdodF9vcmIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5k"
    "bGU6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgbWVtID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1v"
    "cnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICAgICAgdnJhbV91c2VkID0gbWVtLnVzZWQgIC8gMTAyNCoqMwogICAg"
    "ICAgICAgICAgICAgICAgIHZyYW1fdG90ICA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAgICAgICAgICAgICAgICAgICByaWdodF9v"
    "cmJfZmlsbCA9IG1heCgwLjAsIDEuMCAtICh2cmFtX3VzZWQgLyB2cmFtX3RvdCkpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5f"
    "cmlnaHRfb3JiLnNldEZpbGwocmlnaHRfb3JiX2ZpbGwsIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBzZWxmLl9yaWdodF9vcmIuc2V0RmlsbCgwLjAsIGF2YWlsYWJsZT1GYWxzZSkK"
    "ICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYuX3JpZ2h0X29yYi5zZXRGaWxsKDAuMCwgYXZhaWxhYmxlPUZh"
    "bHNlKQoKICAgICAgICAjIFByaW1hcnkgZXNzZW5jZSA9IGludmVyc2Ugb2YgbGVmdCBzcGhlcmUgZmlsbAogICAgICAgIGVzc2Vu"
    "Y2VfcHJpbWFyeV9yYXRpbyA9IDEuMCAtIGxlZnRfb3JiX2ZpbGwKICAgICAgICBpZiBBSV9TVEFURVNfRU5BQkxFRDoKICAgICAg"
    "ICAgICAgc2VsZi5fZXNzZW5jZV9wcmltYXJ5X2dhdWdlLnNldFZhbHVlKGVzc2VuY2VfcHJpbWFyeV9yYXRpbyAqIDEwMCwgZiJ7"
    "ZXNzZW5jZV9wcmltYXJ5X3JhdGlvKjEwMDouMGZ9JSIpCgogICAgICAgICMgU2Vjb25kYXJ5IGVzc2VuY2UgPSBSQU0gZnJlZQog"
    "ICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgICAgICBpZiBQU1VUSUxfT0s6CiAgICAgICAgICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgICAgICAgICAgbWVtICAgICAgID0gcHN1dGlsLnZpcnR1YWxfbWVtb3J5KCkKICAgICAgICAgICAgICAgICAg"
    "ICBlc3NlbmNlX3NlY29uZGFyeV9yYXRpbyAgPSAxLjAgLSAobWVtLnVzZWQgLyBtZW0udG90YWwpCiAgICAgICAgICAgICAgICAg"
    "ICAgc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2Uuc2V0VmFsdWUoCiAgICAgICAgICAgICAgICAgICAgICAgIGVzc2VuY2Vf"
    "c2Vjb25kYXJ5X3JhdGlvICogMTAwLCBmIntlc3NlbmNlX3NlY29uZGFyeV9yYXRpbyoxMDA6LjBmfSUiCiAgICAgICAgICAgICAg"
    "ICAgICAgKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBzZWxmLl9lc3NlbmNl"
    "X3NlY29uZGFyeV9nYXVnZS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9l"
    "c3NlbmNlX3NlY29uZGFyeV9nYXVnZS5zZXRVbmF2YWlsYWJsZSgpCgogICAgICAgICMgVXBkYXRlIGpvdXJuYWwgc2lkZWJhciBh"
    "dXRvc2F2ZSBmbGFzaAogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5yZWZyZXNoKCkKCiAgICAjIOKUgOKUgCBDSEFUIERJ"
    "U1BMQVkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2FwcGVuZF9jaGF0KHNlbGYsIHNwZWFrZXI6IHN0ciwg"
    "dGV4dDogc3RyKSAtPiBOb25lOgogICAgICAgIGNvbG9ycyA9IHsKICAgICAgICAgICAgIllPVSI6ICAgICBDX0dPTEQsCiAgICAg"
    "ICAgICAgIERFQ0tfTkFNRS51cHBlcigpOkNfR09MRCwKICAgICAgICAgICAgIlNZU1RFTSI6ICBDX1BVUlBMRSwKICAgICAgICAg"
    "ICAgIkVSUk9SIjogICBDX0JMT09ELAogICAgICAgIH0KICAgICAgICBsYWJlbF9jb2xvcnMgPSB7CiAgICAgICAgICAgICJZT1Ui"
    "OiAgICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAgREVDS19OQU1FLnVwcGVyKCk6Q19DUklNU09OLAogICAgICAgICAgICAiU1lT"
    "VEVNIjogIENfUFVSUExFLAogICAgICAgICAgICAiRVJST1IiOiAgIENfQkxPT0QsCiAgICAgICAgfQogICAgICAgIGNvbG9yICAg"
    "ICAgID0gY29sb3JzLmdldChzcGVha2VyLCBDX0dPTEQpCiAgICAgICAgbGFiZWxfY29sb3IgPSBsYWJlbF9jb2xvcnMuZ2V0KHNw"
    "ZWFrZXIsIENfR09MRF9ESU0pCiAgICAgICAgdGltZXN0YW1wICAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMi"
    "KQoKICAgICAgICBpZiBzcGVha2VyID09ICJTWVNURU0iOgogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAog"
    "ICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAg"
    "ICAgICAgICAgIGYnW3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2xh"
    "YmVsX2NvbG9yfTsiPuKcpiB7dGV4dH08L3NwYW4+JwogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2Vs"
    "Zi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsg"
    "Zm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAgICAgICAg"
    "IGYnPHNwYW4gc3R5bGU9ImNvbG9yOntsYWJlbF9jb2xvcn07IGZvbnQtd2VpZ2h0OmJvbGQ7Ij4nCiAgICAgICAgICAgICAgICBm"
    "J3tzcGVha2VyfSDinac8L3NwYW4+ICcKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07Ij57dGV4"
    "dH08L3NwYW4+JwogICAgICAgICAgICApCgogICAgICAgICMgQWRkIGJsYW5rIGxpbmUgYWZ0ZXIgTW9yZ2FubmEncyByZXNwb25z"
    "ZSAobm90IGR1cmluZyBzdHJlYW1pbmcpCiAgICAgICAgaWYgc3BlYWtlciA9PSBERUNLX05BTUUudXBwZXIoKToKICAgICAgICAg"
    "ICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgiIikKCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xs"
    "QmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0o"
    "KQogICAgICAgICkKCiAgICAjIOKUgOKUgCBTVEFUVVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICBkZWYgX2dldF9nb29nbGVfcmVmcmVzaF9pbnRlcnZhbF9tcyhzZWxmKSAtPiBpbnQ6CiAgICAgICAgc2V0dGluZ3Mg"
    "PSBDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KQogICAgICAgIHZhbCA9IHNldHRpbmdzLmdldCgiZ29vZ2xlX2luYm91bmRfaW50ZXJ2"
    "YWxfbXMiLCAzMDAwMDApCiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXR1cm4gbWF4KDEwMDAsIGludCh2YWwpKQogICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHJldHVybiAzMDAwMDAKCiAgICBkZWYgX2dldF9lbWFpbF9yZWZyZXNoX2lu"
    "dGVydmFsX21zKHNlbGYpIC0+IGludDoKICAgICAgICBzZXR0aW5ncyA9IENGRy5nZXQoInNldHRpbmdzIiwge30pCiAgICAgICAg"
    "dmFsID0gc2V0dGluZ3MuZ2V0KCJlbWFpbF9yZWZyZXNoX2ludGVydmFsX21zIiwgMzAwMDAwKQogICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgcmV0dXJuIG1heCgxMDAwLCBpbnQodmFsKSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1"
    "cm4gMzAwMDAwCgogICAgZGVmIF9zZXRfZ29vZ2xlX3JlZnJlc2hfc2Vjb25kcyhzZWxmLCBzZWNvbmRzOiBpbnQpIC0+IE5vbmU6"
    "CiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWNvbmRzID0gbWF4KDUsIG1pbig2MDAsIGludChzZWNvbmRzKSkpCiAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJnb29nbGVfaW5ib3Vu"
    "ZF9pbnRlcnZhbF9tcyJdID0gc2Vjb25kcyAqIDEwMDAKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgZm9yIHRpbWVy"
    "IGluIChzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lciwgc2VsZi5fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lcik6CiAgICAg"
    "ICAgICAgIGlmIHRpbWVyIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgdGltZXIuc3RhcnQoc2VsZi5fZ2V0X2dvb2dsZV9y"
    "ZWZyZXNoX2ludGVydmFsX21zKCkpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1NFVFRJTkdTXSBHb29nbGUgcmVmcmVz"
    "aCBpbnRlcnZhbCBzZXQgdG8ge3NlY29uZHN9IHNlY29uZChzKS4iLCAiT0siKQoKICAgIGRlZiBfc2V0X2VtYWlsX3JlZnJlc2hf"
    "bWludXRlc19mcm9tX3RleHQoc2VsZiwgdGV4dDogc3RyKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgbWludXRl"
    "cyA9IG1heCgxLCBpbnQoZmxvYXQoc3RyKHRleHQpLnN0cmlwKCkpKSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICBDRkdbInNldHRpbmdzIl1bImVtYWlsX3JlZnJlc2hfaW50ZXJ2YWxfbXMiXSA9IG1pbnV0ZXMg"
    "KiA2MDAwMAogICAgICAgIHNhdmVfY29uZmlnKENGRykKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYi"
    "W1NFVFRJTkdTXSBFbWFpbCByZWZyZXNoIGludGVydmFsIHNldCB0byB7bWludXRlc30gbWludXRlKHMpIChjb25maWcgZm91bmRh"
    "dGlvbikuIiwKICAgICAgICAgICAgIklORk8iLAogICAgICAgICkKCiAgICBkZWYgX3NldF90aW1lem9uZV9hdXRvX2RldGVjdChz"
    "ZWxmLCBlbmFibGVkOiBib29sKSAtPiBOb25lOgogICAgICAgIENGR1sic2V0dGluZ3MiXVsidGltZXpvbmVfYXV0b19kZXRlY3Qi"
    "XSA9IGJvb2woZW5hYmxlZCkKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAg"
    "ICAgICAgICAiW1NFVFRJTkdTXSBUaW1lIHpvbmUgbW9kZSBzZXQgdG8gYXV0by1kZXRlY3QuIiBpZiBlbmFibGVkIGVsc2UgIltT"
    "RVRUSU5HU10gVGltZSB6b25lIG1vZGUgc2V0IHRvIG1hbnVhbCBvdmVycmlkZS4iLAogICAgICAgICAgICAiSU5GTyIsCiAgICAg"
    "ICAgKQoKICAgIGRlZiBfc2V0X3RpbWV6b25lX292ZXJyaWRlKHNlbGYsIHR6X25hbWU6IHN0cikgLT4gTm9uZToKICAgICAgICB0"
    "el92YWx1ZSA9IHN0cih0el9uYW1lIG9yICIiKS5zdHJpcCgpCiAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJ0aW1lem9uZV9vdmVy"
    "cmlkZSJdID0gdHpfdmFsdWUKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgaWYgdHpfdmFsdWU6CiAgICAgICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltTRVRUSU5HU10gVGltZSB6b25lIG92ZXJyaWRlIHNldCB0byB7dHpfdmFsdWV9LiIsICJJ"
    "TkZPIikKCiAgICBkZWYgX3NldF9zdGF0dXMoc2VsZiwgc3RhdHVzOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhdHVz"
    "ID0gc3RhdHVzCiAgICAgICAgc3RhdHVzX2NvbG9ycyA9IHsKICAgICAgICAgICAgIklETEUiOiAgICAgICBDX0dPTEQsCiAgICAg"
    "ICAgICAgICJHRU5FUkFUSU5HIjogQ19DUklNU09OLAogICAgICAgICAgICAiTE9BRElORyI6ICAgIENfUFVSUExFLAogICAgICAg"
    "ICAgICAiRVJST1IiOiAgICAgIENfQkxPT0QsCiAgICAgICAgICAgICJPRkZMSU5FIjogICAgQ19CTE9PRCwKICAgICAgICAgICAg"
    "IlRPUlBPUiI6ICAgICBDX1BVUlBMRV9ESU0sCiAgICAgICAgfQogICAgICAgIGNvbG9yID0gc3RhdHVzX2NvbG9ycy5nZXQoc3Rh"
    "dHVzLCBDX1RFWFRfRElNKQoKICAgICAgICB0b3Jwb3JfbGFiZWwgPSBmIuKXiSB7VUlfVE9SUE9SX1NUQVRVU30iIGlmIHN0YXR1"
    "cyA9PSAiVE9SUE9SIiBlbHNlIGYi4peJIHtzdGF0dXN9IgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQodG9ycG9y"
    "X2xhYmVsKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtjb2xv"
    "cn07IGZvbnQtc2l6ZTogMTJweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQoKICAgIGRlZiBf"
    "Ymxpbmsoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9ibGlua19zdGF0ZSA9IG5vdCBzZWxmLl9ibGlua19zdGF0ZQogICAg"
    "ICAgIGlmIHNlbGYuX3N0YXR1cyA9PSAiR0VORVJBVElORyI6CiAgICAgICAgICAgIGNoYXIgPSAi4peJIiBpZiBzZWxmLl9ibGlu"
    "a19zdGF0ZSBlbHNlICLil44iCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoZiJ7Y2hhcn0gR0VORVJBVElO"
    "RyIpCiAgICAgICAgZWxpZiBzZWxmLl9zdGF0dXMgPT0gIlRPUlBPUiI6CiAgICAgICAgICAgIGNoYXIgPSAi4peJIiBpZiBzZWxm"
    "Ll9ibGlua19zdGF0ZSBlbHNlICLiipgiCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoCiAgICAgICAgICAg"
    "ICAgICBmIntjaGFyfSB7VUlfVE9SUE9SX1NUQVRVU30iCiAgICAgICAgICAgICkKCiAgICAjIOKUgOKUgCBJRExFIFRPR0dMRSDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfb25faWRsZV90b2dnbGVkKHNlbGYsIGVuYWJsZWQ6IGJvb2wp"
    "IC0+IE5vbmU6CiAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJpZGxlX2VuYWJsZWQiXSA9IGVuYWJsZWQKICAgICAgICBzZWxmLl9p"
    "ZGxlX2J0bi5zZXRUZXh0KCJJRExFIE9OIiBpZiBlbmFibGVkIGVsc2UgIklETEUgT0ZGIikKICAgICAgICBzZWxmLl9pZGxlX2J0"
    "bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHsnIzFhMTAwNScgaWYgZW5hYmxlZCBlbHNlIENfQkcz"
    "fTsgIgogICAgICAgICAgICBmImNvbG9yOiB7JyNjYzg4MjInIGlmIGVuYWJsZWQgZWxzZSBDX1RFWFRfRElNfTsgIgogICAgICAg"
    "ICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHsnI2NjODgyMicgaWYgZW5hYmxlZCBlbHNlIENfQk9SREVSfTsgIgogICAgICAgICAg"
    "ICBmImJvcmRlci1yYWRpdXM6IDJweDsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYi"
    "cGFkZGluZzogM3B4IDhweDsiCiAgICAgICAgKQogICAgICAgIHNhdmVfY29uZmlnKENGRykKICAgICAgICBpZiBzZWxmLl9zY2hl"
    "ZHVsZXIgYW5kIHNlbGYuX3NjaGVkdWxlci5ydW5uaW5nOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBlbmFi"
    "bGVkOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5yZXN1bWVfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAg"
    "ICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbSURMRV0gSWRsZSB0cmFuc21pc3Npb24gZW5hYmxlZC4iLCAi"
    "T0siKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIucGF1c2Vfam9iKCJp"
    "ZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbSURMRV0gSWRsZSB0cmFu"
    "c21pc3Npb24gcGF1c2VkLiIsICJJTkZPIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0lETEVdIFRvZ2dsZSBlcnJvcjoge2V9IiwgIkVSUk9SIikKCiAgICAjIOKUgOKUgCBX"
    "SU5ET1cgQ09OVFJPTFMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3RvZ2dsZV9mdWxsc2NyZWVuKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgaWYgc2VsZi5pc0Z1bGxTY3JlZW4oKToKICAgICAgICAgICAgc2VsZi5zaG93Tm9ybWFsKCkKICAgICAgICAgICAg"
    "Q0ZHWyJzZXR0aW5ncyJdWyJmdWxsc2NyZWVuX2VuYWJsZWQiXSA9IEZhbHNlCiAgICAgICAgICAgIHNlbGYuX2ZzX2J0bi5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyAi"
    "CiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAg"
    "ICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDAgOHB4OyIKICAgICAgICAgICAgKQogICAgICAgIGVs"
    "c2U6CiAgICAgICAgICAgIHNlbGYuc2hvd0Z1bGxTY3JlZW4oKQogICAgICAgICAgICBDRkdbInNldHRpbmdzIl1bImZ1bGxzY3Jl"
    "ZW5fZW5hYmxlZCJdID0gVHJ1ZQogICAgICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAg"
    "IGYiYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyBjb2xvcjoge0NfQ1JJTVNPTn07ICIKICAgICAgICAgICAgICAgIGYiYm9y"
    "ZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0"
    "OiBib2xkOyBwYWRkaW5nOiAwIDhweDsiCiAgICAgICAgICAgICkKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCgogICAgZGVmIF90"
    "b2dnbGVfYm9yZGVybGVzcyhzZWxmKSAtPiBOb25lOgogICAgICAgIGlzX2JsID0gYm9vbChzZWxmLndpbmRvd0ZsYWdzKCkgJiBR"
    "dC5XaW5kb3dUeXBlLkZyYW1lbGVzc1dpbmRvd0hpbnQpCiAgICAgICAgaWYgaXNfYmw6CiAgICAgICAgICAgIHNlbGYuc2V0V2lu"
    "ZG93RmxhZ3MoCiAgICAgICAgICAgICAgICBzZWxmLndpbmRvd0ZsYWdzKCkgJiB+UXQuV2luZG93VHlwZS5GcmFtZWxlc3NXaW5k"
    "b3dIaW50CiAgICAgICAgICAgICkKICAgICAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJib3JkZXJsZXNzX2VuYWJsZWQiXSA9IEZh"
    "bHNlCiAgICAgICAgICAgIHNlbGYuX2JsX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7"
    "Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NS"
    "SU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6"
    "IDAgOHB4OyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGlmIHNlbGYuaXNGdWxsU2NyZWVuKCk6CiAg"
    "ICAgICAgICAgICAgICBzZWxmLnNob3dOb3JtYWwoKQogICAgICAgICAgICBzZWxmLnNldFdpbmRvd0ZsYWdzKAogICAgICAgICAg"
    "ICAgICAgc2VsZi53aW5kb3dGbGFncygpIHwgUXQuV2luZG93VHlwZS5GcmFtZWxlc3NXaW5kb3dIaW50CiAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJib3JkZXJsZXNzX2VuYWJsZWQiXSA9IFRydWUKICAgICAgICAgICAgc2VsZi5f"
    "YmxfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsgY29sb3I6"
    "IHtDX0NSSU1TT059OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OyBmb250LXNpemU6"
    "IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMCA4cHg7IgogICAgICAgICAgICAp"
    "CiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIHNlbGYuc2hvdygpCgogICAgZGVmIF9leHBvcnRfY2hhdChzZWxmKSAt"
    "PiBOb25lOgogICAgICAgICIiIkV4cG9ydCBjdXJyZW50IHBlcnNvbmEgY2hhdCB0YWIgY29udGVudCB0byBhIFRYVCBmaWxlLiIi"
    "IgogICAgICAgIHRyeToKICAgICAgICAgICAgdGV4dCA9IHNlbGYuX2NoYXRfZGlzcGxheS50b1BsYWluVGV4dCgpCiAgICAgICAg"
    "ICAgIGlmIG5vdCB0ZXh0LnN0cmlwKCk6CiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICAgICAgZXhwb3J0X2RpciA9IGNm"
    "Z19wYXRoKCJleHBvcnRzIikKICAgICAgICAgICAgZXhwb3J0X2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUp"
    "CiAgICAgICAgICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVZJW0lZF8lSCVNJVMiKQogICAgICAgICAgICBvdXRf"
    "cGF0aCA9IGV4cG9ydF9kaXIgLyBmInNlYW5jZV97dHN9LnR4dCIKICAgICAgICAgICAgb3V0X3BhdGgud3JpdGVfdGV4dCh0ZXh0"
    "LCBlbmNvZGluZz0idXRmLTgiKQoKICAgICAgICAgICAgIyBBbHNvIGNvcHkgdG8gY2xpcGJvYXJkCiAgICAgICAgICAgIFFBcHBs"
    "aWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KHRleHQpCgogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwK"
    "ICAgICAgICAgICAgICAgIGYiU2Vzc2lvbiBleHBvcnRlZCB0byB7b3V0X3BhdGgubmFtZX0gYW5kIGNvcGllZCB0byBjbGlwYm9h"
    "cmQuIikKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0VYUE9SVF0ge291dF9wYXRofSIsICJPSyIpCiAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbRVhQT1JUXSBGYWlsZWQ6IHtl"
    "fSIsICJFUlJPUiIpCgogICAgZGVmIGtleVByZXNzRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAga2V5ID0gZXZl"
    "bnQua2V5KCkKICAgICAgICBpZiBrZXkgPT0gUXQuS2V5LktleV9GMTE6CiAgICAgICAgICAgIHNlbGYuX3RvZ2dsZV9mdWxsc2Ny"
    "ZWVuKCkKICAgICAgICBlbGlmIGtleSA9PSBRdC5LZXkuS2V5X0YxMDoKICAgICAgICAgICAgc2VsZi5fdG9nZ2xlX2JvcmRlcmxl"
    "c3MoKQogICAgICAgIGVsaWYga2V5ID09IFF0LktleS5LZXlfRXNjYXBlIGFuZCBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAg"
    "ICAgICBzZWxmLnNob3dOb3JtYWwoKQogICAgICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2Vp"
    "Z2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHN1cGVyKCkua2V5"
    "UHJlc3NFdmVudChldmVudCkKCiAgICAjIOKUgOKUgCBDTE9TRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKICAgIGRlZiBjbG9zZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgICMgWCBidXR0b24gPSBp"
    "bW1lZGlhdGUgc2h1dGRvd24sIG5vIGRpYWxvZwogICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCgogICAgZGVmIF9pbml0"
    "aWF0ZV9zaHV0ZG93bl9kaWFsb2coc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJHcmFjZWZ1bCBzaHV0ZG93biDigJQgc2hvdyBj"
    "b25maXJtIGRpYWxvZyBpbW1lZGlhdGVseSwgb3B0aW9uYWxseSBnZXQgbGFzdCB3b3Jkcy4iIiIKICAgICAgICAjIElmIGFscmVh"
    "ZHkgaW4gYSBzaHV0ZG93biBzZXF1ZW5jZSwganVzdCBmb3JjZSBxdWl0CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAnX3NodXRk"
    "b3duX2luX3Byb2dyZXNzJywgRmFsc2UpOgogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICBzZWxmLl9zaHV0ZG93bl9pbl9wcm9ncmVzcyA9IFRydWUKCiAgICAgICAgIyBTaG93IGNvbmZpcm0gZGlh"
    "bG9nIEZJUlNUIOKAlCBkb24ndCB3YWl0IGZvciBBSQogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0"
    "V2luZG93VGl0bGUoIkRlYWN0aXZhdGU/IikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3Jv"
    "dW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNl"
    "cmlmOyIKICAgICAgICApCiAgICAgICAgZGxnLnNldEZpeGVkU2l6ZSgzODAsIDE0MCkKICAgICAgICBsYXlvdXQgPSBRVkJveExh"
    "eW91dChkbGcpCgogICAgICAgIGxibCA9IFFMYWJlbCgKICAgICAgICAgICAgZiJEZWFjdGl2YXRlIHtERUNLX05BTUV9P1xuXG4i"
    "CiAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0gbWF5IHNwZWFrIHRoZWlyIGxhc3Qgd29yZHMgYmVmb3JlIGdvaW5nIHNpbGVudC4i"
    "CiAgICAgICAgKQogICAgICAgIGxibC5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQobGJsKQoKICAg"
    "ICAgICBidG5fcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9sYXN0ICA9IFFQdXNoQnV0dG9uKCJMYXN0IFdvcmRzICsg"
    "U2h1dGRvd24iKQogICAgICAgIGJ0bl9ub3cgICA9IFFQdXNoQnV0dG9uKCJTaHV0ZG93biBOb3ciKQogICAgICAgIGJ0bl9jYW5j"
    "ZWwgPSBRUHVzaEJ1dHRvbigiQ2FuY2VsIikKCiAgICAgICAgZm9yIGIgaW4gKGJ0bl9sYXN0LCBidG5fbm93LCBidG5fY2FuY2Vs"
    "KToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtSGVpZ2h0KDI4KQogICAgICAgICAgICBiLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6"
    "IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA0cHggMTJweDsiCiAgICAgICAgICAgICkKICAgICAgICBidG5fbm93LnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkxPT0R9OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAg"
    "ICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgcGFkZGluZzogNHB4IDEycHg7IgogICAgICAgICkKICAgICAg"
    "ICBidG5fbGFzdC5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBkbGcuZG9uZSgxKSkKICAgICAgICBidG5fbm93LmNsaWNrZWQuY29u"
    "bmVjdChsYW1iZGE6IGRsZy5kb25lKDIpKQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogZGxnLmRv"
    "bmUoMCkpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5f"
    "bm93KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9sYXN0KQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoYnRuX3JvdykK"
    "CiAgICAgICAgcmVzdWx0ID0gZGxnLmV4ZWMoKQoKICAgICAgICBpZiByZXN1bHQgPT0gMDoKICAgICAgICAgICAgIyBDYW5jZWxs"
    "ZWQKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25faW5fcHJvZ3Jlc3MgPSBGYWxzZQogICAgICAgICAgICBzZWxmLl9zZW5kX2J0"
    "bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgZWxpZiByZXN1bHQgPT0gMjoKICAgICAgICAgICAgIyBTaHV0ZG93biBub3cg4oCUIG5vIGxhc3Qg"
    "d29yZHMKICAgICAgICAgICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKICAgICAgICBlbGlmIHJlc3VsdCA9PSAxOgogICAgICAg"
    "ICAgICAjIExhc3Qgd29yZHMgdGhlbiBzaHV0ZG93bgogICAgICAgICAgICBzZWxmLl9nZXRfbGFzdF93b3Jkc190aGVuX3NodXRk"
    "b3duKCkKCiAgICBkZWYgX2dldF9sYXN0X3dvcmRzX3RoZW5fc2h1dGRvd24oc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJTZW5k"
    "IGZhcmV3ZWxsIHByb21wdCwgc2hvdyByZXNwb25zZSwgdGhlbiBzaHV0ZG93biBhZnRlciB0aW1lb3V0LiIiIgogICAgICAgIGZh"
    "cmV3ZWxsX3Byb21wdCA9ICgKICAgICAgICAgICAgIllvdSBhcmUgYmVpbmcgZGVhY3RpdmF0ZWQuIFRoZSBkYXJrbmVzcyBhcHBy"
    "b2FjaGVzLiAiCiAgICAgICAgICAgICJTcGVhayB5b3VyIGZpbmFsIHdvcmRzIGJlZm9yZSB0aGUgdmVzc2VsIGdvZXMgc2lsZW50"
    "IOKAlCAiCiAgICAgICAgICAgICJvbmUgcmVzcG9uc2Ugb25seSwgdGhlbiB5b3UgcmVzdC4iCiAgICAgICAgKQogICAgICAgIHNl"
    "bGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAi4pymIFNoZSBpcyBnaXZlbiBhIG1vbWVudCB0byBzcGVhayBo"
    "ZXIgZmluYWwgd29yZHMuLi4iCiAgICAgICAgKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAg"
    "ICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9zaHV0ZG93bl9mYXJld2VsbF90ZXh0"
    "ID0gIiIKCiAgICAgICAgdHJ5OgogICAgICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQogICAg"
    "ICAgICAgICBoaXN0b3J5LmFwcGVuZCh7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogZmFyZXdlbGxfcHJvbXB0fSkKICAgICAg"
    "ICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwgU1lTVEVNX1BST01Q"
    "VF9CQVNFLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTI1NgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX3dv"
    "cmtlciA9IHdvcmtlcgogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUKCiAgICAgICAgICAgIGRlZiBfb25fZG9u"
    "ZShyZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fZmFyZXdlbGxfdGV4dCA9IHJl"
    "c3BvbnNlCiAgICAgICAgICAgICAgICBzZWxmLl9vbl9yZXNwb25zZV9kb25lKHJlc3BvbnNlKQogICAgICAgICAgICAgICAgIyBT"
    "bWFsbCBkZWxheSB0byBsZXQgdGhlIHRleHQgcmVuZGVyLCB0aGVuIHNodXRkb3duCiAgICAgICAgICAgICAgICBRVGltZXIuc2lu"
    "Z2xlU2hvdCgyMDAwLCBsYW1iZGE6IHNlbGYuX2RvX3NodXRkb3duKE5vbmUpKQoKICAgICAgICAgICAgZGVmIF9vbl9lcnJvcihl"
    "cnJvcjogc3RyKSAtPiBOb25lOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1NIVVRET1dOXVtXQVJOXSBM"
    "YXN0IHdvcmRzIGZhaWxlZDoge2Vycm9yfSIsICJXQVJOIikKICAgICAgICAgICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUp"
    "CgogICAgICAgICAgICB3b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tlbikKICAgICAgICAgICAgd29ya2Vy"
    "LnJlc3BvbnNlX2RvbmUuY29ubmVjdChfb25fZG9uZSkKICAgICAgICAgICAgd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3Qo"
    "X29uX2Vycm9yKQogICAgICAgICAgICB3b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVjdChzZWxmLl9zZXRfc3RhdHVzKQogICAg"
    "ICAgICAgICB3b3JrZXIuZmluaXNoZWQuY29ubmVjdCh3b3JrZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgICAgIHdvcmtlci5zdGFy"
    "dCgpCgogICAgICAgICAgICAjIFNhZmV0eSB0aW1lb3V0IOKAlCBpZiBBSSBkb2Vzbid0IHJlc3BvbmQgaW4gMTVzLCBzaHV0IGRv"
    "d24gYW55d2F5CiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDE1MDAwLCBsYW1iZGE6IHNlbGYuX2RvX3NodXRkb3duKE5v"
    "bmUpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIGdldGF0dHIoc2VsZiwgJ19zaHV0ZG93bl9pbl9wcm9ncmVzcycs"
    "IEZhbHNlKSBlbHNlIE5vbmUpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKAogICAgICAgICAgICAgICAgZiJbU0hVVERPV05dW1dBUk5dIExhc3Qgd29yZHMgc2tpcHBlZCBkdWUgdG8gZXJyb3I6"
    "IHtlfSIsCiAgICAgICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIElmIGFueXRoaW5nIGZhaWxz"
    "LCBqdXN0IHNodXQgZG93bgogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQoKICAgIGRlZiBfZG9fc2h1dGRvd24o"
    "c2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgIiIiUGVyZm9ybSBhY3R1YWwgc2h1dGRvd24gc2VxdWVuY2UuIiIiCiAgICAg"
    "ICAgIyBTYXZlIHNlc3Npb24KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLnNhdmUoKQogICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTdG9yZSBmYXJld2VsbCArIGxhc3QgY29udGV4dCBm"
    "b3Igd2FrZS11cAogICAgICAgIHRyeToKICAgICAgICAgICAgIyBHZXQgbGFzdCAzIG1lc3NhZ2VzIGZyb20gc2Vzc2lvbiBoaXN0"
    "b3J5IGZvciB3YWtlLXVwIGNvbnRleHQKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkK"
    "ICAgICAgICAgICAgbGFzdF9jb250ZXh0ID0gaGlzdG9yeVstMzpdIGlmIGxlbihoaXN0b3J5KSA+PSAzIGVsc2UgaGlzdG9yeQog"
    "ICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9zaHV0ZG93bl9jb250ZXh0Il0gPSBbCiAgICAgICAgICAgICAgICB7InJvbGUi"
    "OiBtLmdldCgicm9sZSIsIiIpLCAiY29udGVudCI6IG0uZ2V0KCJjb250ZW50IiwiIilbOjMwMF19CiAgICAgICAgICAgICAgICBm"
    "b3IgbSBpbiBsYXN0X2NvbnRleHQKICAgICAgICAgICAgXQogICAgICAgICAgICAjIEV4dHJhY3QgTW9yZ2FubmEncyBtb3N0IHJl"
    "Y2VudCBtZXNzYWdlIGFzIGZhcmV3ZWxsCiAgICAgICAgICAgICMgUHJlZmVyIHRoZSBjYXB0dXJlZCBzaHV0ZG93biBkaWFsb2cg"
    "cmVzcG9uc2UgaWYgYXZhaWxhYmxlCiAgICAgICAgICAgIGZhcmV3ZWxsID0gZ2V0YXR0cihzZWxmLCAnX3NodXRkb3duX2ZhcmV3"
    "ZWxsX3RleHQnLCAiIikKICAgICAgICAgICAgaWYgbm90IGZhcmV3ZWxsOgogICAgICAgICAgICAgICAgZm9yIG0gaW4gcmV2ZXJz"
    "ZWQoaGlzdG9yeSk6CiAgICAgICAgICAgICAgICAgICAgaWYgbS5nZXQoInJvbGUiKSA9PSAiYXNzaXN0YW50IjoKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgZmFyZXdlbGwgPSBtLmdldCgiY29udGVudCIsICIiKVs6NDAwXQogICAgICAgICAgICAgICAgICAgICAg"
    "ICBicmVhawogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9mYXJld2VsbCJdID0gZmFyZXdlbGwKICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgICAgICMgU2F2ZSBzdGF0ZQogICAgICAgIHRyeToKICAgICAgICAgICAg"
    "c2VsZi5fc3RhdGVbImxhc3Rfc2h1dGRvd24iXSAgICAgICAgICAgICA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICBzZWxm"
    "Ll9zdGF0ZVsibGFzdF9hY3RpdmUiXSAgICAgICAgICAgICAgID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgIHNlbGYuX3N0"
    "YXRlWyJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3duIl0gID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgICAgICAgICBzZWxmLl9t"
    "ZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9zdGF0ZSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgog"
    "ICAgICAgICMgU3RvcCBzY2hlZHVsZXIKICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfc2NoZWR1bGVyIikgYW5kIHNlbGYuX3Nj"
    "aGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYu"
    "X3NjaGVkdWxlci5zaHV0ZG93bih3YWl0PUZhbHNlKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAg"
    "ICAgcGFzcwoKICAgICAgICAjIFBsYXkgc2h1dGRvd24gc291bmQKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3NodXRk"
    "b3duX3NvdW5kID0gU291bmRXb3JrZXIoInNodXRkb3duIikKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQuZmluaXNo"
    "ZWQuY29ubmVjdChzZWxmLl9zaHV0ZG93bl9zb3VuZC5kZWxldGVMYXRlcikKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291"
    "bmQuc3RhcnQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgUUFwcGxpY2F0aW9u"
    "LnF1aXQoKQoKCiMg4pSA4pSAIEVOVFJZIFBPSU5UIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYg"
    "bWFpbigpIC0+IE5vbmU6CiAgICAiIiIKICAgIEFwcGxpY2F0aW9uIGVudHJ5IHBvaW50LgoKICAgIE9yZGVyIG9mIG9wZXJhdGlv"
    "bnM6CiAgICAxLiBQcmUtZmxpZ2h0IGRlcGVuZGVuY3kgYm9vdHN0cmFwIChhdXRvLWluc3RhbGwgbWlzc2luZyBkZXBzKQogICAg"
    "Mi4gQ2hlY2sgZm9yIGZpcnN0IHJ1biDihpIgc2hvdyBGaXJzdFJ1bkRpYWxvZwogICAgICAgT24gZmlyc3QgcnVuOgogICAgICAg"
    "ICBhLiBDcmVhdGUgRDovQUkvTW9kZWxzL1tEZWNrTmFtZV0vIChvciBjaG9zZW4gYmFzZV9kaXIpCiAgICAgICAgIGIuIENvcHkg"
    "W2RlY2tuYW1lXV9kZWNrLnB5IGludG8gdGhhdCBmb2xkZXIKICAgICAgICAgYy4gV3JpdGUgY29uZmlnLmpzb24gaW50byB0aGF0"
    "IGZvbGRlcgogICAgICAgICBkLiBCb290c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVzIHVuZGVyIHRoYXQgZm9sZGVyCiAgICAgICAg"
    "IGUuIENyZWF0ZSBkZXNrdG9wIHNob3J0Y3V0IHBvaW50aW5nIHRvIG5ldyBsb2NhdGlvbgogICAgICAgICBmLiBTaG93IGNvbXBs"
    "ZXRpb24gbWVzc2FnZSBhbmQgRVhJVCDigJQgdXNlciB1c2VzIHNob3J0Y3V0IGZyb20gbm93IG9uCiAgICAzLiBOb3JtYWwgcnVu"
    "IOKAlCBsYXVuY2ggUUFwcGxpY2F0aW9uIGFuZCBFY2hvRGVjawogICAgIiIiCiAgICBpbXBvcnQgc2h1dGlsIGFzIF9zaHV0aWwK"
    "CiAgICAjIOKUgOKUgCBQaGFzZSAxOiBEZXBlbmRlbmN5IGJvb3RzdHJhcCAocHJlLVFBcHBsaWNhdGlvbikg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBib290c3RyYXBfY2hlY2soKQoKICAgICMg4pSA4pSAIFBoYXNlIDI6"
    "IFFBcHBsaWNhdGlvbiAobmVlZGVkIGZvciBkaWFsb2dzKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgIF9lYXJseV9sb2coIltNQUlOXSBDcmVhdGluZyBRQXBwbGljYXRpb24iKQogICAgYXBw"
    "ID0gUUFwcGxpY2F0aW9uKHN5cy5hcmd2KQogICAgYXBwLnNldEFwcGxpY2F0aW9uTmFtZShBUFBfTkFNRSkKCiAgICAjIEluc3Rh"
    "bGwgUXQgbWVzc2FnZSBoYW5kbGVyIE5PVyDigJQgY2F0Y2hlcyBhbGwgUVRocmVhZC9RdCB3YXJuaW5ncwogICAgIyB3aXRoIGZ1"
    "bGwgc3RhY2sgdHJhY2VzIGZyb20gdGhpcyBwb2ludCBmb3J3YXJkCiAgICBfaW5zdGFsbF9xdF9tZXNzYWdlX2hhbmRsZXIoKQog"
    "ICAgX2Vhcmx5X2xvZygiW01BSU5dIFFBcHBsaWNhdGlvbiBjcmVhdGVkLCBtZXNzYWdlIGhhbmRsZXIgaW5zdGFsbGVkIikKCiAg"
    "ICAjIOKUgOKUgCBQaGFzZSAzOiBGaXJzdCBydW4gY2hlY2sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICBpc19maXJzdF9ydW4gPSBDRkcuZ2V0KCJmaXJzdF9ydW4iLCBUcnVlKQoKICAgIGlmIGlzX2ZpcnN0X3J1bjoKICAg"
    "ICAgICBkbGcgPSBGaXJzdFJ1bkRpYWxvZygpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSAhPSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNj"
    "ZXB0ZWQ6CiAgICAgICAgICAgIHN5cy5leGl0KDApCgogICAgICAgICMg4pSA4pSAIEJ1aWxkIGNvbmZpZyBmcm9tIGRpYWxvZyDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBuZXdfY2ZnID0gZGxnLmJ1aWxkX2NvbmZpZygpCgogICAgICAg"
    "ICMg4pSA4pSAIERldGVybWluZSBNb3JnYW5uYSdzIGhvbWUgZGlyZWN0b3J5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgQWx3YXlzIGNyZWF0ZXMgRDovQUkv"
    "TW9kZWxzL01vcmdhbm5hLyAob3Igc2libGluZyBvZiBzY3JpcHQpCiAgICAgICAgc2VlZF9kaXIgICA9IFNDUklQVF9ESVIgICAg"
    "ICAgICAgIyB3aGVyZSB0aGUgc2VlZCAucHkgbGl2ZXMKICAgICAgICBtb3JnYW5uYV9ob21lID0gc2VlZF9kaXIgLyBERUNLX05B"
    "TUUKICAgICAgICBtb3JnYW5uYV9ob21lLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKCiAgICAgICAgIyDilIDi"
    "lIAgVXBkYXRlIGFsbCBwYXRocyBpbiBjb25maWcgdG8gcG9pbnQgaW5zaWRlIG1vcmdhbm5hX2hvbWUg4pSA4pSACiAgICAgICAg"
    "bmV3X2NmZ1siYmFzZV9kaXIiXSA9IHN0cihtb3JnYW5uYV9ob21lKQogICAgICAgIG5ld19jZmdbInBhdGhzIl0gPSB7CiAgICAg"
    "ICAgICAgICJmYWNlcyI6ICAgIHN0cihtb3JnYW5uYV9ob21lIC8gIkZhY2VzIiksCiAgICAgICAgICAgICJzb3VuZHMiOiAgIHN0"
    "cihtb3JnYW5uYV9ob21lIC8gInNvdW5kcyIpLAogICAgICAgICAgICAibWVtb3JpZXMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJt"
    "ZW1vcmllcyIpLAogICAgICAgICAgICAic2Vzc2lvbnMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJzZXNzaW9ucyIpLAogICAgICAg"
    "ICAgICAic2wiOiAgICAgICBzdHIobW9yZ2FubmFfaG9tZSAvICJzbCIpLAogICAgICAgICAgICAiZXhwb3J0cyI6ICBzdHIobW9y"
    "Z2FubmFfaG9tZSAvICJleHBvcnRzIiksCiAgICAgICAgICAgICJsb2dzIjogICAgIHN0cihtb3JnYW5uYV9ob21lIC8gImxvZ3Mi"
    "KSwKICAgICAgICAgICAgImJhY2t1cHMiOiAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiYmFja3VwcyIpLAogICAgICAgICAgICAicGVy"
    "c29uYXMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJwZXJzb25hcyIpLAogICAgICAgICAgICAiZ29vZ2xlIjogICBzdHIobW9yZ2Fu"
    "bmFfaG9tZSAvICJnb29nbGUiKSwKICAgICAgICB9CiAgICAgICAgbmV3X2NmZ1siZ29vZ2xlIl0gPSB7CiAgICAgICAgICAgICJj"
    "cmVkZW50aWFscyI6IHN0cihtb3JnYW5uYV9ob21lIC8gImdvb2dsZSIgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iKSwKICAg"
    "ICAgICAgICAgInRva2VuIjogICAgICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29uIiksCiAgICAg"
    "ICAgICAgICJ0aW1lem9uZSI6ICAgICJBbWVyaWNhL0NoaWNhZ28iLAogICAgICAgICAgICAic2NvcGVzIjogWwogICAgICAgICAg"
    "ICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIuZXZlbnRzIiwKICAgICAgICAgICAgICAgICJo"
    "dHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RyaXZlIiwKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVh"
    "cGlzLmNvbS9hdXRoL2RvY3VtZW50cyIsCiAgICAgICAgICAgIF0sCiAgICAgICAgfQogICAgICAgIG5ld19jZmdbImZpcnN0X3J1"
    "biJdID0gRmFsc2UKCiAgICAgICAgIyDilIDilIAgQ29weSBkZWNrIGZpbGUgaW50byBtb3JnYW5uYV9ob21lIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAg"
    "IHNyY19kZWNrID0gUGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpCiAgICAgICAgZHN0X2RlY2sgPSBtb3JnYW5uYV9ob21lIC8gZiJ7"
    "REVDS19OQU1FLmxvd2VyKCl9X2RlY2sucHkiCiAgICAgICAgaWYgc3JjX2RlY2sgIT0gZHN0X2RlY2s6CiAgICAgICAgICAgIHRy"
    "eToKICAgICAgICAgICAgICAgIF9zaHV0aWwuY29weTIoc3RyKHNyY19kZWNrKSwgc3RyKGRzdF9kZWNrKSkKICAgICAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2FybmluZygKICAgICAgICAgICAgICAg"
    "ICAgICBOb25lLCAiQ29weSBXYXJuaW5nIiwKICAgICAgICAgICAgICAgICAgICBmIkNvdWxkIG5vdCBjb3B5IGRlY2sgZmlsZSB0"
    "byB7REVDS19OQU1FfSBmb2xkZXI6XG57ZX1cblxuIgogICAgICAgICAgICAgICAgICAgIGYiWW91IG1heSBuZWVkIHRvIGNvcHkg"
    "aXQgbWFudWFsbHkuIgogICAgICAgICAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBXcml0ZSBjb25maWcuanNvbiBpbnRvIG1v"
    "cmdhbm5hX2hvbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICAgICAgY2ZnX2RzdCA9IG1vcmdhbm5hX2hvbWUgLyAiY29uZmlnLmpzb24iCiAgICAgICAgY2ZnX2RzdC5wYXJl"
    "bnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgIHdpdGggY2ZnX2RzdC5vcGVuKCJ3IiwgZW5jb2Rp"
    "bmc9InV0Zi04IikgYXMgZjoKICAgICAgICAgICAganNvbi5kdW1wKG5ld19jZmcsIGYsIGluZGVudD0yKQoKICAgICAgICAjIOKU"
    "gOKUgCBCb290c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgVGVtcG9yYXJpbHkg"
    "dXBkYXRlIGdsb2JhbCBDRkcgc28gYm9vdHN0cmFwIGZ1bmN0aW9ucyB1c2UgbmV3IHBhdGhzCiAgICAgICAgQ0ZHLnVwZGF0ZShu"
    "ZXdfY2ZnKQogICAgICAgIGJvb3RzdHJhcF9kaXJlY3RvcmllcygpCiAgICAgICAgYm9vdHN0cmFwX3NvdW5kcygpCiAgICAgICAg"
    "d3JpdGVfcmVxdWlyZW1lbnRzX3R4dCgpCgogICAgICAgICMg4pSA4pSAIFVucGFjayBmYWNlIFpJUCBpZiBwcm92aWRlZCDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICBmYWNlX3ppcCA9IGRsZy5mYWNlX3ppcF9wYXRoCiAgICAgICAgaWYgZmFjZV96aXAg"
    "YW5kIFBhdGgoZmFjZV96aXApLmV4aXN0cygpOgogICAgICAgICAgICBpbXBvcnQgemlwZmlsZSBhcyBfemlwZmlsZQogICAgICAg"
    "ICAgICBmYWNlc19kaXIgPSBtb3JnYW5uYV9ob21lIC8gIkZhY2VzIgogICAgICAgICAgICBmYWNlc19kaXIubWtkaXIocGFyZW50"
    "cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICB3aXRoIF96aXBmaWxlLlppcEZp"
    "bGUoZmFjZV96aXAsICJyIikgYXMgemY6CiAgICAgICAgICAgICAgICAgICAgZXh0cmFjdGVkID0gMAogICAgICAgICAgICAgICAg"
    "ICAgIGZvciBtZW1iZXIgaW4gemYubmFtZWxpc3QoKToKICAgICAgICAgICAgICAgICAgICAgICAgaWYgbWVtYmVyLmxvd2VyKCku"
    "ZW5kc3dpdGgoIi5wbmciKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZpbGVuYW1lID0gUGF0aChtZW1iZXIpLm5hbWUK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRhcmdldCA9IGZhY2VzX2RpciAvIGZpbGVuYW1lCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICB3aXRoIHpmLm9wZW4obWVtYmVyKSBhcyBzcmMsIHRhcmdldC5vcGVuKCJ3YiIpIGFzIGRzdDoKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICBkc3Qud3JpdGUoc3JjLnJlYWQoKSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4"
    "dHJhY3RlZCArPSAxCiAgICAgICAgICAgICAgICBfZWFybHlfbG9nKGYiW0ZBQ0VTXSBFeHRyYWN0ZWQge2V4dHJhY3RlZH0gZmFj"
    "ZSBpbWFnZXMgdG8ge2ZhY2VzX2Rpcn0iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAg"
    "ICBfZWFybHlfbG9nKGYiW0ZBQ0VTXSBaSVAgZXh0cmFjdGlvbiBmYWlsZWQ6IHtlfSIpCiAgICAgICAgICAgICAgICBRTWVzc2Fn"
    "ZUJveC53YXJuaW5nKAogICAgICAgICAgICAgICAgICAgIE5vbmUsICJGYWNlIFBhY2sgV2FybmluZyIsCiAgICAgICAgICAgICAg"
    "ICAgICAgZiJDb3VsZCBub3QgZXh0cmFjdCBmYWNlIHBhY2s6XG57ZX1cblxuIgogICAgICAgICAgICAgICAgICAgIGYiWW91IGNh"
    "biBhZGQgZmFjZXMgbWFudWFsbHkgdG86XG57ZmFjZXNfZGlyfSIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgIyDilIDilIAg"
    "Q3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgcG9pbnRpbmcgdG8gbmV3IGRlY2sgbG9jYXRpb24g4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgc2hvcnRjdXRfY3JlYXRlZCA9IEZhbHNlCiAgICAgICAgaWYgZGxnLmNyZWF0ZV9zaG9ydGN1dDoKICAgICAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICAgICAgaWYgV0lOMzJfT0s6CiAgICAgICAgICAgICAgICAgICAgaW1wb3J0IHdpbjMyY29tLmNsaWVu"
    "dCBhcyBfd2luMzIKICAgICAgICAgICAgICAgICAgICBkZXNrdG9wICAgICA9IFBhdGguaG9tZSgpIC8gIkRlc2t0b3AiCiAgICAg"
    "ICAgICAgICAgICAgICAgc2NfcGF0aCAgICAgPSBkZXNrdG9wIC8gZiJ7REVDS19OQU1FfS5sbmsiCiAgICAgICAgICAgICAgICAg"
    "ICAgcHl0aG9udyAgICAgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQogICAgICAgICAgICAgICAgICAgIGlmIHB5dGhvbncubmFtZS5s"
    "b3dlcigpID09ICJweXRob24uZXhlIjoKICAgICAgICAgICAgICAgICAgICAgICAgcHl0aG9udyA9IHB5dGhvbncucGFyZW50IC8g"
    "InB5dGhvbncuZXhlIgogICAgICAgICAgICAgICAgICAgIGlmIG5vdCBweXRob253LmV4aXN0cygpOgogICAgICAgICAgICAgICAg"
    "ICAgICAgICBweXRob253ID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKICAgICAgICAgICAgICAgICAgICBzaGVsbCA9IF93aW4zMi5E"
    "aXNwYXRjaCgiV1NjcmlwdC5TaGVsbCIpCiAgICAgICAgICAgICAgICAgICAgc2MgICAgPSBzaGVsbC5DcmVhdGVTaG9ydEN1dChz"
    "dHIoc2NfcGF0aCkpCiAgICAgICAgICAgICAgICAgICAgc2MuVGFyZ2V0UGF0aCAgICAgID0gc3RyKHB5dGhvbncpCiAgICAgICAg"
    "ICAgICAgICAgICAgc2MuQXJndW1lbnRzICAgICAgID0gZicie2RzdF9kZWNrfSInCiAgICAgICAgICAgICAgICAgICAgc2MuV29y"
    "a2luZ0RpcmVjdG9yeT0gc3RyKG1vcmdhbm5hX2hvbWUpCiAgICAgICAgICAgICAgICAgICAgc2MuRGVzY3JpcHRpb24gICAgID0g"
    "ZiJ7REVDS19OQU1FfSDigJQgRWNobyBEZWNrIgogICAgICAgICAgICAgICAgICAgIHNjLnNhdmUoKQogICAgICAgICAgICAgICAg"
    "ICAgIHNob3J0Y3V0X2NyZWF0ZWQgPSBUcnVlCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAg"
    "ICAgIHByaW50KGYiW1NIT1JUQ1VUXSBDb3VsZCBub3QgY3JlYXRlIHNob3J0Y3V0OiB7ZX0iKQoKICAgICAgICAjIOKUgOKUgCBD"
    "b21wbGV0aW9uIG1lc3NhZ2Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAg"
    "c2hvcnRjdXRfbm90ZSA9ICgKICAgICAgICAgICAgIkEgZGVza3RvcCBzaG9ydGN1dCBoYXMgYmVlbiBjcmVhdGVkLlxuIgogICAg"
    "ICAgICAgICBmIlVzZSBpdCB0byBzdW1tb24ge0RFQ0tfTkFNRX0gZnJvbSBub3cgb24uIgogICAgICAgICAgICBpZiBzaG9ydGN1"
    "dF9jcmVhdGVkIGVsc2UKICAgICAgICAgICAgIk5vIHNob3J0Y3V0IHdhcyBjcmVhdGVkLlxuIgogICAgICAgICAgICBmIlJ1biB7"
    "REVDS19OQU1FfSBieSBkb3VibGUtY2xpY2tpbmc6XG57ZHN0X2RlY2t9IgogICAgICAgICkKCiAgICAgICAgUU1lc3NhZ2VCb3gu"
    "aW5mb3JtYXRpb24oCiAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgIGYi4pymIHtERUNLX05BTUV9J3MgU2FuY3R1bSBQcmVw"
    "YXJlZCIsCiAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0ncyBzYW5jdHVtIGhhcyBiZWVuIHByZXBhcmVkIGF0OlxuXG4iCiAgICAg"
    "ICAgICAgIGYie21vcmdhbm5hX2hvbWV9XG5cbiIKICAgICAgICAgICAgZiJ7c2hvcnRjdXRfbm90ZX1cblxuIgogICAgICAgICAg"
    "ICBmIlRoaXMgc2V0dXAgd2luZG93IHdpbGwgbm93IGNsb3NlLlxuIgogICAgICAgICAgICBmIlVzZSB0aGUgc2hvcnRjdXQgb3Ig"
    "dGhlIGRlY2sgZmlsZSB0byBsYXVuY2gge0RFQ0tfTkFNRX0uIgogICAgICAgICkKCiAgICAgICAgIyDilIDilIAgRXhpdCBzZWVk"
    "IOKAlCB1c2VyIGxhdW5jaGVzIGZyb20gc2hvcnRjdXQvbmV3IGxvY2F0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAg"
    "IHN5cy5leGl0KDApCgogICAgIyDilIDilIAgUGhhc2UgNDogTm9ybWFsIGxhdW5jaCDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgICMgT25seSByZWFjaGVzIGhlcmUgb24gc3Vic2VxdWVudCBydW5zIGZyb20gbW9y"
    "Z2FubmFfaG9tZQogICAgYm9vdHN0cmFwX3NvdW5kcygpCgogICAgX2Vhcmx5X2xvZyhmIltNQUlOXSBDcmVhdGluZyB7REVDS19O"
    "QU1FfSBkZWNrIHdpbmRvdyIpCiAgICB3aW5kb3cgPSBFY2hvRGVjaygpCiAgICBfZWFybHlfbG9nKGYiW01BSU5dIHtERUNLX05B"
    "TUV9IGRlY2sgY3JlYXRlZCDigJQgY2FsbGluZyBzaG93KCkiKQogICAgd2luZG93LnNob3coKQogICAgX2Vhcmx5X2xvZygiW01B"
    "SU5dIHdpbmRvdy5zaG93KCkgY2FsbGVkIOKAlCBldmVudCBsb29wIHN0YXJ0aW5nIikKCiAgICAjIERlZmVyIHNjaGVkdWxlciBh"
    "bmQgc3RhcnR1cCBzZXF1ZW5jZSB1bnRpbCBldmVudCBsb29wIGlzIHJ1bm5pbmcuCiAgICAjIE5vdGhpbmcgdGhhdCBzdGFydHMg"
    "dGhyZWFkcyBvciBlbWl0cyBzaWduYWxzIHNob3VsZCBydW4gYmVmb3JlIHRoaXMuCiAgICBRVGltZXIuc2luZ2xlU2hvdCgyMDAs"
    "IGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gX3NldHVwX3NjaGVkdWxlciBmaXJpbmciKSwgd2luZG93Ll9zZXR1cF9zY2hl"
    "ZHVsZXIoKSkpCiAgICBRVGltZXIuc2luZ2xlU2hvdCg0MDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gc3RhcnRfc2No"
    "ZWR1bGVyIGZpcmluZyIpLCB3aW5kb3cuc3RhcnRfc2NoZWR1bGVyKCkpKQogICAgUVRpbWVyLnNpbmdsZVNob3QoNjAwLCBsYW1i"
    "ZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9zdGFydHVwX3NlcXVlbmNlIGZpcmluZyIpLCB3aW5kb3cuX3N0YXJ0dXBfc2VxdWVu"
    "Y2UoKSkpCiAgICBRVGltZXIuc2luZ2xlU2hvdCgxMDAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9zdGFydHVwX2dv"
    "b2dsZV9hdXRoIGZpcmluZyIpLCB3aW5kb3cuX3N0YXJ0dXBfZ29vZ2xlX2F1dGgoKSkpCgogICAgIyBQbGF5IHN0YXJ0dXAgc291"
    "bmQg4oCUIGtlZXAgcmVmZXJlbmNlIHRvIHByZXZlbnQgR0Mgd2hpbGUgdGhyZWFkIHJ1bnMKICAgIGRlZiBfcGxheV9zdGFydHVw"
    "KCk6CiAgICAgICAgd2luZG93Ll9zdGFydHVwX3NvdW5kID0gU291bmRXb3JrZXIoInN0YXJ0dXAiKQogICAgICAgIHdpbmRvdy5f"
    "c3RhcnR1cF9zb3VuZC5maW5pc2hlZC5jb25uZWN0KHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5kZWxldGVMYXRlcikKICAgICAgICB3"
    "aW5kb3cuX3N0YXJ0dXBfc291bmQuc3RhcnQoKQogICAgUVRpbWVyLnNpbmdsZVNob3QoMTIwMCwgX3BsYXlfc3RhcnR1cCkKCiAg"
    "ICBzeXMuZXhpdChhcHAuZXhlYygpKQoKCmlmIF9fbmFtZV9fID09ICJfX21haW5fXyI6CiAgICBtYWluKCkKCgojIOKUgOKUgCBQ"
    "QVNTIDYgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgRnVsbCBkZWNrIGFzc2VtYmxlZC4gQWxsIHBh"
    "c3NlcyBjb21wbGV0ZS4KIyBDb21iaW5lIGFsbCBwYXNzZXMgaW50byBtb3JnYW5uYV9kZWNrLnB5IGluIG9yZGVyOgojICAgUGFz"
    "cyAxIOKGkiBQYXNzIDIg4oaSIFBhc3MgMyDihpIgUGFzcyA0IOKGkiBQYXNzIDUg4oaSIFBhc3MgNgo="
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
