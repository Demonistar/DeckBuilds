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
        "status":       "built",
        "description":  "Classic Magic 8-Ball panel. Standard answers + hidden persona interpretation.",
        "tab_name":     "Magic 8-Ball",
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
    "magic_8ball":        "# [MODULE: magic_8ball — BUILT — see Magic8BallTab class]",
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
    "IyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKCiMg"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pW"
    "Q4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4p"
    "WQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4"
    "pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "CiMgRUNITyBERUNLIOKAlCBVTklWRVJTQUwgSU1QTEVNRU5UQVRJT04KIyBHZW5lcmF0ZWQgYnkgZGV"
    "ja19idWlsZGVyLnB5CiMgQWxsIHBlcnNvbmEgdmFsdWVzIGluamVjdGVkIGZyb20gREVDS19URU1QTE"
    "FURSBoZWFkZXIuCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4"
    "pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pW"
    "Q4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4p"
    "WQ4pWQ4pWQ4pWQ4pWQCgojIOKUgOKUgCBQQVNTIDE6IEZPVU5EQVRJT04sIENPTlNUQU5UUywgSEVMU"
    "EVSUywgU09VTkQgR0VORVJBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAoKCmltcG9ydCBzeXMKaW1wb3J0IG9zCmltcG9ydCBqc29uCmltcG9ydCB"
    "tYXRoCmltcG9ydCB0aW1lCmltcG9ydCB3YXZlCmltcG9ydCBzdHJ1Y3QKaW1wb3J0IHJhbmRvbQppbX"
    "BvcnQgdGhyZWFkaW5nCmltcG9ydCB1cmxsaWIucmVxdWVzdAppbXBvcnQgdXVpZApmcm9tIGRhdGV0a"
    "W1lIGltcG9ydCBkYXRldGltZSwgZGF0ZSwgdGltZWRlbHRhLCB0aW1lem9uZQpmcm9tIHpvbmVpbmZv"
    "IGltcG9ydCBab25lSW5mbywgWm9uZUluZm9Ob3RGb3VuZEVycm9yCmZyb20gcGF0aGxpYiBpbXBvcnQ"
    "gUGF0aApmcm9tIHR5cGluZyBpbXBvcnQgT3B0aW9uYWwsIEl0ZXJhdG9yCgojIOKUgOKUgCBFQVJMWS"
    "BDUkFTSCBMT0dHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "ACiMgSG9va3MgaW4gYmVmb3JlIFF0LCBiZWZvcmUgZXZlcnl0aGluZy4gQ2FwdHVyZXMgQUxMIG91dH"
    "B1dCBpbmNsdWRpbmcKIyBDKysgbGV2ZWwgUXQgbWVzc2FnZXMuIFdyaXR0ZW4gdG8gW0RlY2tOYW1lX"
    "S9sb2dzL3N0YXJ0dXAubG9nCiMgVGhpcyBzdGF5cyBhY3RpdmUgZm9yIHRoZSBsaWZlIG9mIHRoZSBw"
    "cm9jZXNzLgoKX0VBUkxZX0xPR19MSU5FUzogbGlzdCA9IFtdCl9FQVJMWV9MT0dfUEFUSDogT3B0aW9"
    "uYWxbUGF0aF0gPSBOb25lCgpkZWYgX2Vhcmx5X2xvZyhtc2c6IHN0cikgLT4gTm9uZToKICAgIHRzID"
    "0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTLiVmIilbOi0zXQogICAgbGluZSA9IGYiW"
    "3t0c31dIHttc2d9IgogICAgX0VBUkxZX0xPR19MSU5FUy5hcHBlbmQobGluZSkKICAgIHByaW50KGxp"
    "bmUsIGZsdXNoPVRydWUpCiAgICBpZiBfRUFSTFlfTE9HX1BBVEg6CiAgICAgICAgdHJ5OgogICAgICA"
    "gICAgICB3aXRoIF9FQVJMWV9MT0dfUEFUSC5vcGVuKCJhIiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZj"
    "oKICAgICAgICAgICAgICAgIGYud3JpdGUobGluZSArICJcbiIpCiAgICAgICAgZXhjZXB0IEV4Y2Vwd"
    "GlvbjoKICAgICAgICAgICAgcGFzcwoKZGVmIF9pbml0X2Vhcmx5X2xvZyhiYXNlX2RpcjogUGF0aCkg"
    "LT4gTm9uZToKICAgIGdsb2JhbCBfRUFSTFlfTE9HX1BBVEgKICAgIGxvZ19kaXIgPSBiYXNlX2RpciA"
    "vICJsb2dzIgogICAgbG9nX2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgIC"
    "BfRUFSTFlfTE9HX1BBVEggPSBsb2dfZGlyIC8gZiJzdGFydHVwX3tkYXRldGltZS5ub3coKS5zdHJmd"
    "GltZSgnJVklbSVkXyVIJU0lUycpfS5sb2ciCiAgICAjIEZsdXNoIGJ1ZmZlcmVkIGxpbmVzCiAgICB3"
    "aXRoIF9FQVJMWV9MT0dfUEFUSC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICA"
    "gICBmb3IgbGluZSBpbiBfRUFSTFlfTE9HX0xJTkVTOgogICAgICAgICAgICBmLndyaXRlKGxpbmUgKy"
    "AiXG4iKQoKZGVmIF9pbnN0YWxsX3F0X21lc3NhZ2VfaGFuZGxlcigpIC0+IE5vbmU6CiAgICAiIiIKI"
    "CAgIEludGVyY2VwdCBBTEwgUXQgbWVzc2FnZXMgaW5jbHVkaW5nIEMrKyBsZXZlbCB3YXJuaW5ncy4K"
    "ICAgIFRoaXMgY2F0Y2hlcyB0aGUgUVRocmVhZCBkZXN0cm95ZWQgbWVzc2FnZSBhdCB0aGUgc291cmN"
    "lIGFuZCBsb2dzIGl0CiAgICB3aXRoIGEgZnVsbCB0cmFjZWJhY2sgc28gd2Uga25vdyBleGFjdGx5IH"
    "doaWNoIHRocmVhZCBhbmQgd2hlcmUuCiAgICAiIiIKICAgIHRyeToKICAgICAgICBmcm9tIFB5U2lkZ"
    "TYuUXRDb3JlIGltcG9ydCBxSW5zdGFsbE1lc3NhZ2VIYW5kbGVyLCBRdE1zZ1R5cGUKICAgICAgICBp"
    "bXBvcnQgdHJhY2ViYWNrCgogICAgICAgIGRlZiBxdF9tZXNzYWdlX2hhbmRsZXIobXNnX3R5cGUsIGN"
    "vbnRleHQsIG1lc3NhZ2UpOgogICAgICAgICAgICBsZXZlbCA9IHsKICAgICAgICAgICAgICAgIFF0TX"
    "NnVHlwZS5RdERlYnVnTXNnOiAgICAiUVRfREVCVUciLAogICAgICAgICAgICAgICAgUXRNc2dUeXBlL"
    "lF0SW5mb01zZzogICAgICJRVF9JTkZPIiwKICAgICAgICAgICAgICAgIFF0TXNnVHlwZS5RdFdhcm5p"
    "bmdNc2c6ICAiUVRfV0FSTklORyIsCiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXRDcml0aWNhbE1"
    "zZzogIlFUX0NSSVRJQ0FMIiwKICAgICAgICAgICAgICAgIFF0TXNnVHlwZS5RdEZhdGFsTXNnOiAgIC"
    "AiUVRfRkFUQUwiLAogICAgICAgICAgICB9LmdldChtc2dfdHlwZSwgIlFUX1VOS05PV04iKQoKICAgI"
    "CAgICAgICAgbG9jYXRpb24gPSAiIgogICAgICAgICAgICBpZiBjb250ZXh0LmZpbGU6CiAgICAgICAg"
    "ICAgICAgICBsb2NhdGlvbiA9IGYiIFt7Y29udGV4dC5maWxlfTp7Y29udGV4dC5saW5lfV0iCgogICA"
    "gICAgICAgICBfZWFybHlfbG9nKGYiW3tsZXZlbH1de2xvY2F0aW9ufSB7bWVzc2FnZX0iKQoKICAgIC"
    "AgICAgICAgIyBGb3IgUVRocmVhZCB3YXJuaW5ncyDigJQgbG9nIGZ1bGwgUHl0aG9uIHN0YWNrCiAgI"
    "CAgICAgICAgIGlmICJRVGhyZWFkIiBpbiBtZXNzYWdlIG9yICJ0aHJlYWQiIGluIG1lc3NhZ2UubG93"
    "ZXIoKToKICAgICAgICAgICAgICAgIHN0YWNrID0gIiIuam9pbih0cmFjZWJhY2suZm9ybWF0X3N0YWN"
    "rKCkpCiAgICAgICAgICAgICAgICBfZWFybHlfbG9nKGYiW1NUQUNLIEFUIFFUSFJFQUQgV0FSTklOR1"
    "1cbntzdGFja30iKQoKICAgICAgICBxSW5zdGFsbE1lc3NhZ2VIYW5kbGVyKHF0X21lc3NhZ2VfaGFuZ"
    "GxlcikKICAgICAgICBfZWFybHlfbG9nKCJbSU5JVF0gUXQgbWVzc2FnZSBoYW5kbGVyIGluc3RhbGxl"
    "ZCIpCiAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgX2Vhcmx5X2xvZyhmIltJTklUXSB"
    "Db3VsZCBub3QgaW5zdGFsbCBRdCBtZXNzYWdlIGhhbmRsZXI6IHtlfSIpCgpfZWFybHlfbG9nKGYiW0"
    "lOSVRdIHtERUNLX05BTUV9IGRlY2sgc3RhcnRpbmciKQpfZWFybHlfbG9nKGYiW0lOSVRdIFB5dGhvb"
    "iB7c3lzLnZlcnNpb24uc3BsaXQoKVswXX0gYXQge3N5cy5leGVjdXRhYmxlfSIpCl9lYXJseV9sb2co"
    "ZiJbSU5JVF0gV29ya2luZyBkaXJlY3Rvcnk6IHtvcy5nZXRjd2QoKX0iKQpfZWFybHlfbG9nKGYiW0l"
    "OSVRdIFNjcmlwdCBsb2NhdGlvbjoge1BhdGgoX19maWxlX18pLnJlc29sdmUoKX0iKQoKIyDilIDilI"
    "AgT1BUSU9OQUwgREVQRU5ERU5DWSBHVUFSRFMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACgpQU1V"
    "USUxfT0sgPSBGYWxzZQp0cnk6CiAgICBpbXBvcnQgcHN1dGlsCiAgICBQU1VUSUxfT0sgPSBUcnVlCi"
    "AgICBfZWFybHlfbG9nKCJbSU1QT1JUXSBwc3V0aWwgT0siKQpleGNlcHQgSW1wb3J0RXJyb3IgYXMgZ"
    "ToKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSBwc3V0aWwgRkFJTEVEOiB7ZX0iKQoKTlZNTF9PSyA9"
    "IEZhbHNlCmdwdV9oYW5kbGUgPSBOb25lCnRyeToKICAgIGltcG9ydCB3YXJuaW5ncwogICAgd2l0aCB"
    "3YXJuaW5ncy5jYXRjaF93YXJuaW5ncygpOgogICAgICAgIHdhcm5pbmdzLnNpbXBsZWZpbHRlcigiaW"
    "dub3JlIikKICAgICAgICBpbXBvcnQgcHludm1sCiAgICBweW52bWwubnZtbEluaXQoKQogICAgY291b"
    "nQgPSBweW52bWwubnZtbERldmljZUdldENvdW50KCkKICAgIGlmIGNvdW50ID4gMDoKICAgICAgICBn"
    "cHVfaGFuZGxlID0gcHludm1sLm52bWxEZXZpY2VHZXRIYW5kbGVCeUluZGV4KDApCiAgICAgICAgTlZ"
    "NTF9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSBweW52bWwgT0sg4oCUIHtjb3VudH"
    "0gR1BVKHMpIikKZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgX2Vhcmx5X2xvZyhmIltJTVBPUlRdI"
    "HB5bnZtbCBGQUlMRUQ6IHtlfSIpCgpUT1JDSF9PSyA9IEZhbHNlCnRyeToKICAgIGltcG9ydCB0b3Jj"
    "aAogICAgZnJvbSB0cmFuc2Zvcm1lcnMgaW1wb3J0IEF1dG9Nb2RlbEZvckNhdXNhbExNLCBBdXRvVG9"
    "rZW5pemVyCiAgICBUT1JDSF9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSB0b3JjaC"
    "B7dG9yY2guX192ZXJzaW9uX199IE9LIikKZXhjZXB0IEltcG9ydEVycm9yIGFzIGU6CiAgICBfZWFyb"
    "HlfbG9nKGYiW0lNUE9SVF0gdG9yY2ggRkFJTEVEIChvcHRpb25hbCk6IHtlfSIpCgpXSU4zMl9PSyA9"
    "IEZhbHNlCnRyeToKICAgIGltcG9ydCB3aW4zMmNvbS5jbGllbnQKICAgIFdJTjMyX09LID0gVHJ1ZQo"
    "gICAgX2Vhcmx5X2xvZygiW0lNUE9SVF0gd2luMzJjb20gT0siKQpleGNlcHQgSW1wb3J0RXJyb3IgYX"
    "MgZToKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSB3aW4zMmNvbSBGQUlMRUQ6IHtlfSIpCgpXSU5TT"
    "1VORF9PSyA9IEZhbHNlCnRyeToKICAgIGltcG9ydCB3aW5zb3VuZAogICAgV0lOU09VTkRfT0sgPSBU"
    "cnVlCiAgICBfZWFybHlfbG9nKCJbSU1QT1JUXSB3aW5zb3VuZCBPSyIpCmV4Y2VwdCBJbXBvcnRFcnJ"
    "vciBhcyBlOgogICAgX2Vhcmx5X2xvZyhmIltJTVBPUlRdIHdpbnNvdW5kIEZBSUxFRCAob3B0aW9uYW"
    "wpOiB7ZX0iKQoKUFlHQU1FX09LID0gRmFsc2UKdHJ5OgogICAgaW1wb3J0IHB5Z2FtZQogICAgcHlnY"
    "W1lLm1peGVyLmluaXQoKQogICAgUFlHQU1FX09LID0gVHJ1ZQogICAgX2Vhcmx5X2xvZygiW0lNUE9S"
    "VF0gcHlnYW1lIE9LIikKZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgX2Vhcmx5X2xvZyhmIltJTVB"
    "PUlRdIHB5Z2FtZSBGQUlMRUQ6IHtlfSIpCgpHT09HTEVfT0sgPSBGYWxzZQpHT09HTEVfQVBJX09LID"
    "0gRmFsc2UgICMgYWxpYXMgdXNlZCBieSBHb29nbGUgc2VydmljZSBjbGFzc2VzCkdPT0dMRV9JTVBPU"
    "lRfRVJST1IgPSBOb25lCnRyeToKICAgIGZyb20gZ29vZ2xlLmF1dGgudHJhbnNwb3J0LnJlcXVlc3Rz"
    "IGltcG9ydCBSZXF1ZXN0IGFzIEdvb2dsZUF1dGhSZXF1ZXN0CiAgICBmcm9tIGdvb2dsZS5vYXV0aDI"
    "uY3JlZGVudGlhbHMgaW1wb3J0IENyZWRlbnRpYWxzIGFzIEdvb2dsZUNyZWRlbnRpYWxzCiAgICBmcm"
    "9tIGdvb2dsZV9hdXRoX29hdXRobGliLmZsb3cgaW1wb3J0IEluc3RhbGxlZEFwcEZsb3cKICAgIGZyb"
    "20gZ29vZ2xlYXBpY2xpZW50LmRpc2NvdmVyeSBpbXBvcnQgYnVpbGQgYXMgZ29vZ2xlX2J1aWxkCiAg"
    "ICBmcm9tIGdvb2dsZWFwaWNsaWVudC5lcnJvcnMgaW1wb3J0IEh0dHBFcnJvciBhcyBHb29nbGVIdHR"
    "wRXJyb3IKICAgIEdPT0dMRV9PSyA9IFRydWUKICAgIEdPT0dMRV9BUElfT0sgPSBUcnVlCmV4Y2VwdC"
    "BJbXBvcnRFcnJvciBhcyBfZToKICAgIEdPT0dMRV9JTVBPUlRfRVJST1IgPSBzdHIoX2UpCiAgICBHb"
    "29nbGVIdHRwRXJyb3IgPSBFeGNlcHRpb24KCkdPT0dMRV9TQ09QRVMgPSBbCiAgICAiaHR0cHM6Ly93"
    "d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9jYWxlbmRhciIsCiAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXB"
    "pcy5jb20vYXV0aC9jYWxlbmRhci5ldmVudHMiLAogICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY2"
    "9tL2F1dGgvZHJpdmUiLAogICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZG9jdW1lb"
    "nRzIiwKXQpHT09HTEVfU0NPUEVfUkVBVVRIX01TRyA9ICgKICAgICJHb29nbGUgdG9rZW4gc2NvcGVz"
    "IGFyZSBvdXRkYXRlZCBvciBpbmNvbXBhdGlibGUgd2l0aCByZXF1ZXN0ZWQgc2NvcGVzLiAiCiAgICA"
    "iRGVsZXRlIHRva2VuLmpzb24gYW5kIHJlYXV0aG9yaXplIHdpdGggdGhlIHVwZGF0ZWQgc2NvcGUgbG"
    "lzdC4iCikKREVGQVVMVF9HT09HTEVfSUFOQV9USU1FWk9ORSA9ICJBbWVyaWNhL0NoaWNhZ28iCldJT"
    "kRPV1NfVFpfVE9fSUFOQSA9IHsKICAgICJDZW50cmFsIFN0YW5kYXJkIFRpbWUiOiAiQW1lcmljYS9D"
    "aGljYWdvIiwKICAgICJFYXN0ZXJuIFN0YW5kYXJkIFRpbWUiOiAiQW1lcmljYS9OZXdfWW9yayIsCiA"
    "gICAiUGFjaWZpYyBTdGFuZGFyZCBUaW1lIjogIkFtZXJpY2EvTG9zX0FuZ2VsZXMiLAogICAgIk1vdW"
    "50YWluIFN0YW5kYXJkIFRpbWUiOiAiQW1lcmljYS9EZW52ZXIiLAp9CgoKIyDilIDilIAgUHlTaWRlN"
    "iBJTVBPUlRTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgApmcm9tIFB5U2lkZTYuUXRXaWRnZXRzIGltcG9ydCAoCiAgICBRQXBwbGljYXRpb24sI"
    "FFNYWluV2luZG93LCBRV2lkZ2V0LCBRVkJveExheW91dCwgUUhCb3hMYXlvdXQsCiAgICBRR3JpZExh"
    "eW91dCwgUVRleHRFZGl0LCBRTGluZUVkaXQsIFFQdXNoQnV0dG9uLCBRTGFiZWwsIFFGcmFtZSwKICA"
    "gIFFDYWxlbmRhcldpZGdldCwgUVRhYmxlV2lkZ2V0LCBRVGFibGVXaWRnZXRJdGVtLCBRSGVhZGVyVm"
    "lldywKICAgIFFBYnN0cmFjdEl0ZW1WaWV3LCBRU3RhY2tlZFdpZGdldCwgUVRhYldpZGdldCwgUUxpc"
    "3RXaWRnZXQsCiAgICBRTGlzdFdpZGdldEl0ZW0sIFFTaXplUG9saWN5LCBRQ29tYm9Cb3gsIFFDaGVj"
    "a0JveCwgUUZpbGVEaWFsb2csCiAgICBRTWVzc2FnZUJveCwgUURhdGVFZGl0LCBRRGlhbG9nLCBRRm9"
    "ybUxheW91dCwgUVNjcm9sbEFyZWEsCiAgICBRU3BsaXR0ZXIsIFFJbnB1dERpYWxvZywgUVRvb2xCdX"
    "R0b24sIFFTcGluQm94LCBRR3JhcGhpY3NPcGFjaXR5RWZmZWN0LAogICAgUU1lbnUsIFFUYWJCYXIKK"
    "Qpmcm9tIFB5U2lkZTYuUXRDb3JlIGltcG9ydCAoCiAgICBRdCwgUVRpbWVyLCBRVGhyZWFkLCBTaWdu"
    "YWwsIFFEYXRlLCBRU2l6ZSwgUVBvaW50LCBRUmVjdCwKICAgIFFQcm9wZXJ0eUFuaW1hdGlvbiwgUUV"
    "hc2luZ0N1cnZlCikKZnJvbSBQeVNpZGU2LlF0R3VpIGltcG9ydCAoCiAgICBRRm9udCwgUUNvbG9yLC"
    "BRUGFpbnRlciwgUUxpbmVhckdyYWRpZW50LCBRUmFkaWFsR3JhZGllbnQsCiAgICBRUGl4bWFwLCBRU"
    "GVuLCBRUGFpbnRlclBhdGgsIFFUZXh0Q2hhckZvcm1hdCwgUUljb24sCiAgICBRVGV4dEN1cnNvciwg"
    "UUFjdGlvbgopCgojIOKUgOKUgCBBUFAgSURFTlRJVFkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACkFQUF9OQU1FICAgICAgPSBV"
    "SV9XSU5ET1dfVElUTEUKQVBQX1ZFUlNJT04gICA9ICIyLjAuMCIKQVBQX0ZJTEVOQU1FICA9IGYie0R"
    "FQ0tfTkFNRS5sb3dlcigpfV9kZWNrLnB5IgpCVUlMRF9EQVRFICAgID0gIjIwMjYtMDQtMDQiCgojIO"
    "KUgOKUgCBDT05GSUcgTE9BRElORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBjb25maWcuanNvbiBsaXZlcyBuZXh0IHRvIHRoZS"
    "BkZWNrIC5weSBmaWxlLgojIEFsbCBwYXRocyBjb21lIGZyb20gY29uZmlnLiBOb3RoaW5nIGhhcmRjb"
    "2RlZCBiZWxvdyB0aGlzIHBvaW50LgoKU0NSSVBUX0RJUiA9IFBhdGgoX19maWxlX18pLnJlc29sdmUo"
    "KS5wYXJlbnQKQ09ORklHX1BBVEggPSBTQ1JJUFRfRElSIC8gImNvbmZpZy5qc29uIgoKIyBJbml0aWF"
    "saXplIGVhcmx5IGxvZyBub3cgdGhhdCB3ZSBrbm93IHdoZXJlIHdlIGFyZQpfaW5pdF9lYXJseV9sb2"
    "coU0NSSVBUX0RJUikKX2Vhcmx5X2xvZyhmIltJTklUXSBTQ1JJUFRfRElSID0ge1NDUklQVF9ESVJ9I"
    "ikKX2Vhcmx5X2xvZyhmIltJTklUXSBDT05GSUdfUEFUSCA9IHtDT05GSUdfUEFUSH0iKQpfZWFybHlf"
    "bG9nKGYiW0lOSVRdIGNvbmZpZy5qc29uIGV4aXN0czoge0NPTkZJR19QQVRILmV4aXN0cygpfSIpCgp"
    "kZWYgX2RlZmF1bHRfY29uZmlnKCkgLT4gZGljdDoKICAgICIiIlJldHVybnMgdGhlIGRlZmF1bHQgY2"
    "9uZmlnIHN0cnVjdHVyZSBmb3IgZmlyc3QtcnVuIGdlbmVyYXRpb24uIiIiCiAgICBiYXNlID0gc3RyK"
    "FNDUklQVF9ESVIpCiAgICByZXR1cm4gewogICAgICAgICJkZWNrX25hbWUiOiBERUNLX05BTUUsCiAg"
    "ICAgICAgImRlY2tfdmVyc2lvbiI6IEFQUF9WRVJTSU9OLAogICAgICAgICJiYXNlX2RpciI6IGJhc2U"
    "sCiAgICAgICAgIm1vZGVsIjogewogICAgICAgICAgICAidHlwZSI6ICJsb2NhbCIsICAgICAgICAgIC"
    "MgbG9jYWwgfCBvbGxhbWEgfCBjbGF1ZGUgfCBvcGVuYWkKICAgICAgICAgICAgInBhdGgiOiAiIiwgI"
    "CAgICAgICAgICAgICAjIGxvY2FsIG1vZGVsIGZvbGRlciBwYXRoCiAgICAgICAgICAgICJvbGxhbWFf"
    "bW9kZWwiOiAiIiwgICAgICAgIyBlLmcuICJkb2xwaGluLTIuNi03YiIKICAgICAgICAgICAgImFwaV9"
    "rZXkiOiAiIiwgICAgICAgICAgICAjIENsYXVkZSBvciBPcGVuQUkga2V5CiAgICAgICAgICAgICJhcG"
    "lfdHlwZSI6ICIiLCAgICAgICAgICAgIyAiY2xhdWRlIiB8ICJvcGVuYWkiCiAgICAgICAgICAgICJhc"
    "GlfbW9kZWwiOiAiIiwgICAgICAgICAgIyBlLmcuICJjbGF1ZGUtc29ubmV0LTQtNiIKICAgICAgICB9"
    "LAogICAgICAgICJnb29nbGUiOiB7CiAgICAgICAgICAgICJjcmVkZW50aWFscyI6IHN0cihTQ1JJUFR"
    "fRElSIC8gImdvb2dsZSIgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iKSwKICAgICAgICAgICAgIn"
    "Rva2VuIjogICAgICAgc3RyKFNDUklQVF9ESVIgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29uIiksCiAgI"
    "CAgICAgICAgICJ0aW1lem9uZSI6ICAgICJBbWVyaWNhL0NoaWNhZ28iLAogICAgICAgICAgICAic2Nv"
    "cGVzIjogWwogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2F"
    "sZW5kYXIuZXZlbnRzIiwKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS"
    "9hdXRoL2RyaXZlIiwKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hd"
    "XRoL2RvY3VtZW50cyIsCiAgICAgICAgICAgIF0sCiAgICAgICAgfSwKICAgICAgICAicGF0aHMiOiB7"
    "CiAgICAgICAgICAgICJmYWNlcyI6ICAgIHN0cihTQ1JJUFRfRElSIC8gIkZhY2VzIiksCiAgICAgICA"
    "gICAgICJzb3VuZHMiOiAgIHN0cihTQ1JJUFRfRElSIC8gInNvdW5kcyIpLAogICAgICAgICAgICAibW"
    "Vtb3JpZXMiOiBzdHIoU0NSSVBUX0RJUiAvICJtZW1vcmllcyIpLAogICAgICAgICAgICAic2Vzc2lvb"
    "nMiOiBzdHIoU0NSSVBUX0RJUiAvICJzZXNzaW9ucyIpLAogICAgICAgICAgICAic2wiOiAgICAgICBz"
    "dHIoU0NSSVBUX0RJUiAvICJzbCIpLAogICAgICAgICAgICAiZXhwb3J0cyI6ICBzdHIoU0NSSVBUX0R"
    "JUiAvICJleHBvcnRzIiksCiAgICAgICAgICAgICJsb2dzIjogICAgIHN0cihTQ1JJUFRfRElSIC8gIm"
    "xvZ3MiKSwKICAgICAgICAgICAgImJhY2t1cHMiOiAgc3RyKFNDUklQVF9ESVIgLyAiYmFja3VwcyIpL"
    "AogICAgICAgICAgICAicGVyc29uYXMiOiBzdHIoU0NSSVBUX0RJUiAvICJwZXJzb25hcyIpLAogICAg"
    "ICAgICAgICAiZ29vZ2xlIjogICBzdHIoU0NSSVBUX0RJUiAvICJnb29nbGUiKSwKICAgICAgICB9LAo"
    "gICAgICAgICJzZXR0aW5ncyI6IHsKICAgICAgICAgICAgImlkbGVfZW5hYmxlZCI6ICAgICAgICAgIC"
    "AgICBGYWxzZSwKICAgICAgICAgICAgImlkbGVfbWluX21pbnV0ZXMiOiAgICAgICAgICAxMCwKICAgI"
    "CAgICAgICAgImlkbGVfbWF4X21pbnV0ZXMiOiAgICAgICAgICAzMCwKICAgICAgICAgICAgImF1dG9z"
    "YXZlX2ludGVydmFsX21pbnV0ZXMiOiAxMCwKICAgICAgICAgICAgIm1heF9iYWNrdXBzIjogICAgICA"
    "gICAgICAgICAxMCwKICAgICAgICAgICAgImdvb2dsZV9zeW5jX2VuYWJsZWQiOiAgICAgICBUcnVlLA"
    "ogICAgICAgICAgICAic291bmRfZW5hYmxlZCI6ICAgICAgICAgICAgIFRydWUsCiAgICAgICAgICAgI"
    "CJnb29nbGVfaW5ib3VuZF9pbnRlcnZhbF9tcyI6IDMwMDAwLAogICAgICAgICAgICAiZW1haWxfcmVm"
    "cmVzaF9pbnRlcnZhbF9tcyI6IDMwMDAwMCwKICAgICAgICAgICAgImdvb2dsZV9sb29rYmFja19kYXl"
    "zIjogICAgICAzMCwKICAgICAgICAgICAgInVzZXJfZGVsYXlfdGhyZXNob2xkX21pbiI6ICAzMCwKIC"
    "AgICAgICAgICAgInRpbWV6b25lX2F1dG9fZGV0ZWN0IjogICAgICBUcnVlLAogICAgICAgICAgICAid"
    "GltZXpvbmVfb3ZlcnJpZGUiOiAgICAgICAgICIiLAogICAgICAgICAgICAiZnVsbHNjcmVlbl9lbmFi"
    "bGVkIjogICAgICAgIEZhbHNlLAogICAgICAgICAgICAiYm9yZGVybGVzc19lbmFibGVkIjogICAgICA"
    "gIEZhbHNlLAogICAgICAgIH0sCiAgICAgICAgIm1vZHVsZV90YWJfb3JkZXIiOiBbXSwKICAgICAgIC"
    "AiZmlyc3RfcnVuIjogVHJ1ZSwKICAgIH0KCmRlZiBsb2FkX2NvbmZpZygpIC0+IGRpY3Q6CiAgICAiI"
    "iJMb2FkIGNvbmZpZy5qc29uLiBSZXR1cm5zIGRlZmF1bHQgaWYgbWlzc2luZyBvciBjb3JydXB0LiIi"
    "IgogICAgaWYgbm90IENPTkZJR19QQVRILmV4aXN0cygpOgogICAgICAgIHJldHVybiBfZGVmYXVsdF9"
    "jb25maWcoKQogICAgdHJ5OgogICAgICAgIHdpdGggQ09ORklHX1BBVEgub3BlbigiciIsIGVuY29kaW"
    "5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgIHJldHVybiBqc29uLmxvYWQoZikKICAgIGV4Y2Vwd"
    "CBFeGNlcHRpb246CiAgICAgICAgcmV0dXJuIF9kZWZhdWx0X2NvbmZpZygpCgpkZWYgc2F2ZV9jb25m"
    "aWcoY2ZnOiBkaWN0KSAtPiBOb25lOgogICAgIiIiV3JpdGUgY29uZmlnLmpzb24uIiIiCiAgICBDT05"
    "GSUdfUEFUSC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgd2l0aC"
    "BDT05GSUdfUEFUSC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICBqc29uL"
    "mR1bXAoY2ZnLCBmLCBpbmRlbnQ9MikKCiMgTG9hZCBjb25maWcgYXQgbW9kdWxlIGxldmVsIOKAlCBl"
    "dmVyeXRoaW5nIGJlbG93IHJlYWRzIGZyb20gQ0ZHCkNGRyA9IGxvYWRfY29uZmlnKCkKX2Vhcmx5X2x"
    "vZyhmIltJTklUXSBDb25maWcgbG9hZGVkIOKAlCBmaXJzdF9ydW49e0NGRy5nZXQoJ2ZpcnN0X3J1bi"
    "cpfSwgbW9kZWxfdHlwZT17Q0ZHLmdldCgnbW9kZWwnLHt9KS5nZXQoJ3R5cGUnKX0iKQoKX0RFRkFVT"
    "FRfUEFUSFM6IGRpY3Rbc3RyLCBQYXRoXSA9IHsKICAgICJmYWNlcyI6ICAgIFNDUklQVF9ESVIgLyAi"
    "RmFjZXMiLAogICAgInNvdW5kcyI6ICAgU0NSSVBUX0RJUiAvICJzb3VuZHMiLAogICAgIm1lbW9yaWV"
    "zIjogU0NSSVBUX0RJUiAvICJtZW1vcmllcyIsCiAgICAic2Vzc2lvbnMiOiBTQ1JJUFRfRElSIC8gIn"
    "Nlc3Npb25zIiwKICAgICJzbCI6ICAgICAgIFNDUklQVF9ESVIgLyAic2wiLAogICAgImV4cG9ydHMiO"
    "iAgU0NSSVBUX0RJUiAvICJleHBvcnRzIiwKICAgICJsb2dzIjogICAgIFNDUklQVF9ESVIgLyAibG9n"
    "cyIsCiAgICAiYmFja3VwcyI6ICBTQ1JJUFRfRElSIC8gImJhY2t1cHMiLAogICAgInBlcnNvbmFzIjo"
    "gU0NSSVBUX0RJUiAvICJwZXJzb25hcyIsCiAgICAiZ29vZ2xlIjogICBTQ1JJUFRfRElSIC8gImdvb2"
    "dsZSIsCn0KCmRlZiBfbm9ybWFsaXplX2NvbmZpZ19wYXRocygpIC0+IE5vbmU6CiAgICAiIiIKICAgI"
    "FNlbGYtaGVhbCBvbGRlciBjb25maWcuanNvbiBmaWxlcyBtaXNzaW5nIHJlcXVpcmVkIHBhdGgga2V5"
    "cy4KICAgIEFkZHMgbWlzc2luZyBwYXRoIGtleXMgYW5kIG5vcm1hbGl6ZXMgZ29vZ2xlIGNyZWRlbnR"
    "pYWwvdG9rZW4gbG9jYXRpb25zLAogICAgdGhlbiBwZXJzaXN0cyBjb25maWcuanNvbiBpZiBhbnl0aG"
    "luZyBjaGFuZ2VkLgogICAgIiIiCiAgICBjaGFuZ2VkID0gRmFsc2UKICAgIHBhdGhzID0gQ0ZHLnNld"
    "GRlZmF1bHQoInBhdGhzIiwge30pCiAgICBmb3Iga2V5LCBkZWZhdWx0X3BhdGggaW4gX0RFRkFVTFRf"
    "UEFUSFMuaXRlbXMoKToKICAgICAgICBpZiBub3QgcGF0aHMuZ2V0KGtleSk6CiAgICAgICAgICAgIHB"
    "hdGhzW2tleV0gPSBzdHIoZGVmYXVsdF9wYXRoKQogICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKIC"
    "AgIGdvb2dsZV9jZmcgPSBDRkcuc2V0ZGVmYXVsdCgiZ29vZ2xlIiwge30pCiAgICBnb29nbGVfcm9vd"
    "CA9IFBhdGgocGF0aHMuZ2V0KCJnb29nbGUiLCBzdHIoX0RFRkFVTFRfUEFUSFNbImdvb2dsZSJdKSkp"
    "CiAgICBkZWZhdWx0X2NyZWRzID0gc3RyKGdvb2dsZV9yb290IC8gImdvb2dsZV9jcmVkZW50aWFscy5"
    "qc29uIikKICAgIGRlZmF1bHRfdG9rZW4gPSBzdHIoZ29vZ2xlX3Jvb3QgLyAidG9rZW4uanNvbiIpCi"
    "AgICBjcmVkc192YWwgPSBzdHIoZ29vZ2xlX2NmZy5nZXQoImNyZWRlbnRpYWxzIiwgIiIpKS5zdHJpc"
    "CgpCiAgICB0b2tlbl92YWwgPSBzdHIoZ29vZ2xlX2NmZy5nZXQoInRva2VuIiwgIiIpKS5zdHJpcCgp"
    "CiAgICBpZiAobm90IGNyZWRzX3ZhbCkgb3IgKCJjb25maWciIGluIGNyZWRzX3ZhbCBhbmQgImdvb2d"
    "sZV9jcmVkZW50aWFscy5qc29uIiBpbiBjcmVkc192YWwpOgogICAgICAgIGdvb2dsZV9jZmdbImNyZW"
    "RlbnRpYWxzIl0gPSBkZWZhdWx0X2NyZWRzCiAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgIGlmIG5vd"
    "CB0b2tlbl92YWw6CiAgICAgICAgZ29vZ2xlX2NmZ1sidG9rZW4iXSA9IGRlZmF1bHRfdG9rZW4KICAg"
    "ICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgc2F2ZV9jb25maWcoQ0Z"
    "HKQoKZGVmIGNmZ19wYXRoKGtleTogc3RyKSAtPiBQYXRoOgogICAgIiIiQ29udmVuaWVuY2U6IGdldC"
    "BhIHBhdGggZnJvbSBDRkdbJ3BhdGhzJ11ba2V5XSBhcyBhIFBhdGggb2JqZWN0IHdpdGggc2FmZSBmY"
    "WxsYmFjayBkZWZhdWx0cy4iIiIKICAgIHBhdGhzID0gQ0ZHLmdldCgicGF0aHMiLCB7fSkKICAgIHZh"
    "bHVlID0gcGF0aHMuZ2V0KGtleSkKICAgIGlmIHZhbHVlOgogICAgICAgIHJldHVybiBQYXRoKHZhbHV"
    "lKQogICAgZmFsbGJhY2sgPSBfREVGQVVMVF9QQVRIUy5nZXQoa2V5KQogICAgaWYgZmFsbGJhY2s6Ci"
    "AgICAgICAgcGF0aHNba2V5XSA9IHN0cihmYWxsYmFjaykKICAgICAgICByZXR1cm4gZmFsbGJhY2sKI"
    "CAgIHJldHVybiBTQ1JJUFRfRElSIC8ga2V5Cgpfbm9ybWFsaXplX2NvbmZpZ19wYXRocygpCgojIOKU"
    "gOKUgCBDT0xPUiBDT05TVEFOVFMg4oCUIGRlcml2ZWQgZnJvbSBwZXJzb25hIHRlbXBsYXRlIOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgAojIENfUFJJTUFSWSwgQ19TRUNPTkRBUlksIENfQUNDRU5ULCBDX0JHLCBDX"
    "1BBTkVMLCBDX0JPUkRFUiwKIyBDX1RFWFQsIENfVEVYVF9ESU0gYXJlIGluamVjdGVkIGF0IHRoZSB0"
    "b3Agb2YgdGhpcyBmaWxlIGJ5IGRlY2tfYnVpbGRlci4KIyBFdmVyeXRoaW5nIGJlbG93IGlzIGRlcml"
    "2ZWQgZnJvbSB0aG9zZSBpbmplY3RlZCB2YWx1ZXMuCgojIFNlbWFudGljIGFsaWFzZXMg4oCUIG1hcC"
    "BwZXJzb25hIGNvbG9ycyB0byBuYW1lZCByb2xlcyB1c2VkIHRocm91Z2hvdXQgdGhlIFVJCkNfQ1JJT"
    "VNPTiAgICAgPSBDX1BSSU1BUlkgICAgICAgICAgIyBtYWluIGFjY2VudCAoYnV0dG9ucywgYm9yZGVy"
    "cywgaGlnaGxpZ2h0cykKQ19DUklNU09OX0RJTSA9IENfUFJJTUFSWSArICI4OCIgICAjIGRpbSBhY2N"
    "lbnQgZm9yIHN1YnRsZSBib3JkZXJzCkNfR09MRCAgICAgICAgPSBDX1NFQ09OREFSWSAgICAgICAgIy"
    "BtYWluIGxhYmVsL3RleHQvQUkgb3V0cHV0IGNvbG9yCkNfR09MRF9ESU0gICAgPSBDX1NFQ09OREFSW"
    "SArICI4OCIgIyBkaW0gc2Vjb25kYXJ5CkNfR09MRF9CUklHSFQgPSBDX0FDQ0VOVCAgICAgICAgICAg"
    "IyBlbXBoYXNpcywgaG92ZXIgc3RhdGVzCkNfU0lMVkVSICAgICAgPSBDX1RFWFRfRElNICAgICAgICA"
    "gIyBzZWNvbmRhcnkgdGV4dCAoYWxyZWFkeSBpbmplY3RlZCkKQ19TSUxWRVJfRElNICA9IENfVEVYVF"
    "9ESU0gKyAiODgiICAjIGRpbSBzZWNvbmRhcnkgdGV4dApDX01PTklUT1IgICAgID0gQ19CRyAgICAgI"
    "CAgICAgICAgICMgY2hhdCBkaXNwbGF5IGJhY2tncm91bmQgKGFscmVhZHkgaW5qZWN0ZWQpCkNfQkcy"
    "ICAgICAgICAgPSBDX0JHICAgICAgICAgICAgICAgIyBzZWNvbmRhcnkgYmFja2dyb3VuZApDX0JHMyA"
    "gICAgICAgID0gQ19QQU5FTCAgICAgICAgICAgICMgdGVydGlhcnkvaW5wdXQgYmFja2dyb3VuZCAoYW"
    "xyZWFkeSBpbmplY3RlZCkKQ19CTE9PRCAgICAgICA9ICcjOGIwMDAwJyAgICAgICAgICAjIGVycm9yI"
    "HN0YXRlcywgZGFuZ2VyIOKAlCB1bml2ZXJzYWwKQ19QVVJQTEUgICAgICA9ICcjODg1NWNjJyAgICAg"
    "ICAgICAjIFNZU1RFTSBtZXNzYWdlcyDigJQgdW5pdmVyc2FsCkNfUFVSUExFX0RJTSAgPSAnIzJhMDU"
    "yYScgICAgICAgICAgIyBkaW0gcHVycGxlIOKAlCB1bml2ZXJzYWwKQ19HUkVFTiAgICAgICA9ICcjND"
    "RhYTY2JyAgICAgICAgICAjIHBvc2l0aXZlIHN0YXRlcyDigJQgdW5pdmVyc2FsCkNfQkxVRSAgICAgI"
    "CAgPSAnIzQ0ODhjYycgICAgICAgICAgIyBpbmZvIHN0YXRlcyDigJQgdW5pdmVyc2FsCgojIEZvbnQg"
    "aGVscGVyIOKAlCBleHRyYWN0cyBwcmltYXJ5IGZvbnQgbmFtZSBmb3IgUUZvbnQoKSBjYWxscwpERUN"
    "LX0ZPTlQgPSBVSV9GT05UX0ZBTUlMWS5zcGxpdCgnLCcpWzBdLnN0cmlwKCkuc3RyaXAoIiciKQoKIy"
    "BFbW90aW9uIOKGkiBjb2xvciBtYXBwaW5nIChmb3IgZW1vdGlvbiByZWNvcmQgY2hpcHMpCkVNT1RJT"
    "05fQ09MT1JTOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICJ2aWN0b3J5IjogICAgQ19HT0xELAogICAg"
    "InNtdWciOiAgICAgICBDX0dPTEQsCiAgICAiaW1wcmVzc2VkIjogIENfR09MRCwKICAgICJyZWxpZXZ"
    "lZCI6ICAgQ19HT0xELAogICAgImhhcHB5IjogICAgICBDX0dPTEQsCiAgICAiZmxpcnR5IjogICAgIE"
    "NfR09MRCwKICAgICJwYW5pY2tlZCI6ICAgQ19DUklNU09OLAogICAgImFuZ3J5IjogICAgICBDX0NSS"
    "U1TT04sCiAgICAic2hvY2tlZCI6ICAgIENfQ1JJTVNPTiwKICAgICJjaGVhdG1vZGUiOiAgQ19DUklN"
    "U09OLAogICAgImNvbmNlcm5lZCI6ICAiI2NjNjYyMiIsCiAgICAic2FkIjogICAgICAgICIjY2M2NjI"
    "yIiwKICAgICJodW1pbGlhdGVkIjogIiNjYzY2MjIiLAogICAgImZsdXN0ZXJlZCI6ICAiI2NjNjYyMi"
    "IsCiAgICAicGxvdHRpbmciOiAgIENfUFVSUExFLAogICAgInN1c3BpY2lvdXMiOiBDX1BVUlBMRSwKI"
    "CAgICJlbnZpb3VzIjogICAgQ19QVVJQTEUsCiAgICAiZm9jdXNlZCI6ICAgIENfU0lMVkVSLAogICAg"
    "ImFsZXJ0IjogICAgICBDX1NJTFZFUiwKICAgICJuZXV0cmFsIjogICAgQ19URVhUX0RJTSwKfQoKIyD"
    "ilIDilIAgREVDT1JBVElWRSBDT05TVEFOVFMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiMgUlVORVMgaXMgc291cmNlZCBmcm9tIFVJX1JVTkVTIGluamVjdGVkIGJ5IHR"
    "oZSBwZXJzb25hIHRlbXBsYXRlClJVTkVTID0gVUlfUlVORVMKCiMgRmFjZSBpbWFnZSBtYXAg4oCUIH"
    "ByZWZpeCBmcm9tIEZBQ0VfUFJFRklYLCBmaWxlcyBsaXZlIGluIGNvbmZpZyBwYXRocy5mYWNlcwpGQ"
    "UNFX0ZJTEVTOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICJuZXV0cmFsIjogICAgZiJ7RkFDRV9QUkVG"
    "SVh9X05ldXRyYWwucG5nIiwKICAgICJhbGVydCI6ICAgICAgZiJ7RkFDRV9QUkVGSVh9X0FsZXJ0LnB"
    "uZyIsCiAgICAiZm9jdXNlZCI6ICAgIGYie0ZBQ0VfUFJFRklYfV9Gb2N1c2VkLnBuZyIsCiAgICAic2"
    "11ZyI6ICAgICAgIGYie0ZBQ0VfUFJFRklYfV9TbXVnLnBuZyIsCiAgICAiY29uY2VybmVkIjogIGYie"
    "0ZBQ0VfUFJFRklYfV9Db25jZXJuZWQucG5nIiwKICAgICJzYWQiOiAgICAgICAgZiJ7RkFDRV9QUkVG"
    "SVh9X1NhZF9DcnlpbmcucG5nIiwKICAgICJyZWxpZXZlZCI6ICAgZiJ7RkFDRV9QUkVGSVh9X1JlbGl"
    "ldmVkLnBuZyIsCiAgICAiaW1wcmVzc2VkIjogIGYie0ZBQ0VfUFJFRklYfV9JbXByZXNzZWQucG5nIi"
    "wKICAgICJ2aWN0b3J5IjogICAgZiJ7RkFDRV9QUkVGSVh9X1ZpY3RvcnkucG5nIiwKICAgICJodW1pb"
    "GlhdGVkIjogZiJ7RkFDRV9QUkVGSVh9X0h1bWlsaWF0ZWQucG5nIiwKICAgICJzdXNwaWNpb3VzIjog"
    "ZiJ7RkFDRV9QUkVGSVh9X1N1c3BpY2lvdXMucG5nIiwKICAgICJwYW5pY2tlZCI6ICAgZiJ7RkFDRV9"
    "QUkVGSVh9X1Bhbmlja2VkLnBuZyIsCiAgICAiY2hlYXRtb2RlIjogIGYie0ZBQ0VfUFJFRklYfV9DaG"
    "VhdF9Nb2RlLnBuZyIsCiAgICAiYW5ncnkiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9BbmdyeS5wbmciL"
    "AogICAgInBsb3R0aW5nIjogICBmIntGQUNFX1BSRUZJWH1fUGxvdHRpbmcucG5nIiwKICAgICJzaG9j"
    "a2VkIjogICAgZiJ7RkFDRV9QUkVGSVh9X1Nob2NrZWQucG5nIiwKICAgICJoYXBweSI6ICAgICAgZiJ"
    "7RkFDRV9QUkVGSVh9X0hhcHB5LnBuZyIsCiAgICAiZmxpcnR5IjogICAgIGYie0ZBQ0VfUFJFRklYfV"
    "9GbGlydHkucG5nIiwKICAgICJmbHVzdGVyZWQiOiAgZiJ7RkFDRV9QUkVGSVh9X0ZsdXN0ZXJlZC5wb"
    "mciLAogICAgImVudmlvdXMiOiAgICBmIntGQUNFX1BSRUZJWH1fRW52aW91cy5wbmciLAp9CgpTRU5U"
    "SU1FTlRfTElTVCA9ICgKICAgICJuZXV0cmFsLCBhbGVydCwgZm9jdXNlZCwgc211ZywgY29uY2VybmV"
    "kLCBzYWQsIHJlbGlldmVkLCBpbXByZXNzZWQsICIKICAgICJ2aWN0b3J5LCBodW1pbGlhdGVkLCBzdX"
    "NwaWNpb3VzLCBwYW5pY2tlZCwgYW5ncnksIHBsb3R0aW5nLCBzaG9ja2VkLCAiCiAgICAiaGFwcHksI"
    "GZsaXJ0eSwgZmx1c3RlcmVkLCBlbnZpb3VzIgopCgojIOKUgOKUgCBTWVNURU0gUFJPTVBUIOKAlCBp"
    "bmplY3RlZCBmcm9tIHBlcnNvbmEgdGVtcGxhdGUgYXQgdG9wIG9mIGZpbGUg4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgU1lTVEVNX1BST01QVF9CQVNFIGlzIGFscmVhZHkgZG"
    "VmaW5lZCBhYm92ZSBmcm9tIDw8PFNZU1RFTV9QUk9NUFQ+Pj4gaW5qZWN0aW9uLgojIERvIG5vdCByZ"
    "WRlZmluZSBpdCBoZXJlLgoKIyDilIDilIAgR0xPQkFMIFNUWUxFU0hFRVQg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSAClNUWUxFID0gZiIiIgpRTWFpbldpb"
    "mRvdywgUVdpZGdldCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkd9OwogICAgY29sb3I6IHtD"
    "X0dPTER9OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07Cn19ClFUZXh0RWRpdCB7ewo"
    "gICAgYmFja2dyb3VuZC1jb2xvcjoge0NfTU9OSVRPUn07CiAgICBjb2xvcjoge0NfR09MRH07CiAgIC"
    "Bib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBib3JkZXItcmFkaXVzOiAycHg7C"
    "iAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKICAgIGZvbnQtc2l6ZTogMTJweDsKICAg"
    "IHBhZGRpbmc6IDhweDsKICAgIHNlbGVjdGlvbi1iYWNrZ3JvdW5kLWNvbG9yOiB7Q19DUklNU09OX0R"
    "JTX07Cn19ClFMaW5lRWRpdCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkczfTsKICAgIGNvbG"
    "9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OwogICAgYm9yZGVyL"
    "XJhZGl1czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNp"
    "emU6IDEzcHg7CiAgICBwYWRkaW5nOiA4cHggMTJweDsKfX0KUUxpbmVFZGl0OmZvY3VzIHt7CiAgICB"
    "ib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEfTsKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX1BBTkVMfT"
    "sKfX0KUVB1c2hCdXR0b24ge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0NSSU1TT05fRElNfTsKI"
    "CAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OwogICAg"
    "Ym9yZGVyLXJhZGl1czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICB"
    "mb250LXNpemU6IDEycHg7CiAgICBmb250LXdlaWdodDogYm9sZDsKICAgIHBhZGRpbmc6IDhweCAyMH"
    "B4OwogICAgbGV0dGVyLXNwYWNpbmc6IDJweDsKfX0KUVB1c2hCdXR0b246aG92ZXIge3sKICAgIGJhY"
    "2tncm91bmQtY29sb3I6IHtDX0NSSU1TT059OwogICAgY29sb3I6IHtDX0dPTERfQlJJR0hUfTsKfX0K"
    "UVB1c2hCdXR0b246cHJlc3NlZCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkxPT0R9OwogICA"
    "gYm9yZGVyLWNvbG9yOiB7Q19CTE9PRH07CiAgICBjb2xvcjoge0NfVEVYVH07Cn19ClFQdXNoQnV0dG"
    "9uOmRpc2FibGVkIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX"
    "1RFWFRfRElNfTsKICAgIGJvcmRlci1jb2xvcjoge0NfVEVYVF9ESU19Owp9fQpRU2Nyb2xsQmFyOnZl"
    "cnRpY2FsIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CR307CiAgICB3aWR0aDogNnB4OwogICAgYm9yZGV"
    "yOiBub25lOwp9fQpRU2Nyb2xsQmFyOjpoYW5kbGU6dmVydGljYWwge3sKICAgIGJhY2tncm91bmQ6IH"
    "tDX0NSSU1TT05fRElNfTsKICAgIGJvcmRlci1yYWRpdXM6IDNweDsKfX0KUVNjcm9sbEJhcjo6aGFuZ"
    "GxlOnZlcnRpY2FsOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OfTsKfX0KUVNjcm9s"
    "bEJhcjo6YWRkLWxpbmU6dmVydGljYWwsIFFTY3JvbGxCYXI6OnN1Yi1saW5lOnZlcnRpY2FsIHt7CiA"
    "gICBoZWlnaHQ6IDBweDsKfX0KUVRhYldpZGdldDo6cGFuZSB7ewogICAgYm9yZGVyOiAxcHggc29saW"
    "Qge0NfQ1JJTVNPTl9ESU19OwogICAgYmFja2dyb3VuZDoge0NfQkcyfTsKfX0KUVRhYkJhcjo6dGFiI"
    "Ht7CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX1RFWFRfRElNfTsKICAgIGJv"
    "cmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIHBhZGRpbmc6IDZweCAxNHB4OwogICA"
    "gZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEwcHg7CiAgICBsZX"
    "R0ZXItc3BhY2luZzogMXB4Owp9fQpRVGFiQmFyOjp0YWI6c2VsZWN0ZWQge3sKICAgIGJhY2tncm91b"
    "mQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlci1ib3R0b206"
    "IDJweCBzb2xpZCB7Q19DUklNU09OfTsKfX0KUVRhYkJhcjo6dGFiOmhvdmVyIHt7CiAgICBiYWNrZ3J"
    "vdW5kOiB7Q19QQU5FTH07CiAgICBjb2xvcjoge0NfR09MRF9ESU19Owp9fQpRVGFibGVXaWRnZXQge3"
    "sKICAgIGJhY2tncm91bmQ6IHtDX0JHMn07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6I"
    "DFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBncmlkbGluZS1jb2xvcjoge0NfQk9SREVSfTsK"
    "ICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMXB4Owp9fQp"
    "RVGFibGVXaWRnZXQ6Oml0ZW06c2VsZWN0ZWQge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRE"
    "lNfTsKICAgIGNvbG9yOiB7Q19HT0xEX0JSSUdIVH07Cn19ClFIZWFkZXJWaWV3OjpzZWN0aW9uIHt7C"
    "iAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAx"
    "cHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgcGFkZGluZzogNHB4OwogICAgZm9udC1mYW1pbHk"
    "6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEwcHg7CiAgICBmb250LXdlaWdodDogYm"
    "9sZDsKICAgIGxldHRlci1zcGFjaW5nOiAxcHg7Cn19ClFDb21ib0JveCB7ewogICAgYmFja2dyb3VuZ"
    "Doge0NfQkczfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NS"
    "SU1TT05fRElNfTsKICAgIHBhZGRpbmc6IDRweCA4cHg7CiAgICBmb250LWZhbWlseToge1VJX0ZPTlR"
    "fRkFNSUxZfTsKfX0KUUNvbWJvQm94Ojpkcm9wLWRvd24ge3sKICAgIGJvcmRlcjogbm9uZTsKfX0KUU"
    "NoZWNrQm94IHt7CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfR"
    "kFNSUxZfTsKfX0KUUxhYmVsIHt7CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IG5vbmU7"
    "Cn19ClFTcGxpdHRlcjo6aGFuZGxlIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07CiA"
    "gICB3aWR0aDogMnB4Owp9fQoiIiIKCiMg4pSA4pSAIERJUkVDVE9SWSBCT09UU1RSQVAg4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBib290c3RyYXBfZGlyZWN"
    "0b3JpZXMoKSAtPiBOb25lOgogICAgIiIiCiAgICBDcmVhdGUgYWxsIHJlcXVpcmVkIGRpcmVjdG9yaW"
    "VzIGlmIHRoZXkgZG9uJ3QgZXhpc3QuCiAgICBDYWxsZWQgb24gc3RhcnR1cCBiZWZvcmUgYW55dGhpb"
    "mcgZWxzZS4gU2FmZSB0byBjYWxsIG11bHRpcGxlIHRpbWVzLgogICAgQWxzbyBtaWdyYXRlcyBmaWxl"
    "cyBmcm9tIG9sZCBbRGVja05hbWVdX01lbW9yaWVzIGxheW91dCBpZiBkZXRlY3RlZC4KICAgICIiIgo"
    "gICAgZGlycyA9IFsKICAgICAgICBjZmdfcGF0aCgiZmFjZXMiKSwKICAgICAgICBjZmdfcGF0aCgic2"
    "91bmRzIiksCiAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIiksCiAgICAgICAgY2ZnX3BhdGgoInNlc"
    "3Npb25zIiksCiAgICAgICAgY2ZnX3BhdGgoInNsIiksCiAgICAgICAgY2ZnX3BhdGgoImV4cG9ydHMi"
    "KSwKICAgICAgICBjZmdfcGF0aCgibG9ncyIpLAogICAgICAgIGNmZ19wYXRoKCJiYWNrdXBzIiksCiA"
    "gICAgICAgY2ZnX3BhdGgoInBlcnNvbmFzIiksCiAgICAgICAgY2ZnX3BhdGgoImdvb2dsZSIpLAogIC"
    "AgICAgIGNmZ19wYXRoKCJnb29nbGUiKSAvICJleHBvcnRzIiwKICAgIF0KICAgIGZvciBkIGluIGRpc"
    "nM6CiAgICAgICAgZC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCgogICAgIyBDcmVh"
    "dGUgZW1wdHkgSlNPTkwgZmlsZXMgaWYgdGhleSBkb24ndCBleGlzdAogICAgbWVtb3J5X2RpciA9IGN"
    "mZ19wYXRoKCJtZW1vcmllcyIpCiAgICBmb3IgZm5hbWUgaW4gKCJtZXNzYWdlcy5qc29ubCIsICJtZW"
    "1vcmllcy5qc29ubCIsICJ0YXNrcy5qc29ubCIsCiAgICAgICAgICAgICAgICAgICJsZXNzb25zX2xlY"
    "XJuZWQuanNvbmwiLCAicGVyc29uYV9oaXN0b3J5Lmpzb25sIik6CiAgICAgICAgZnAgPSBtZW1vcnlf"
    "ZGlyIC8gZm5hbWUKICAgICAgICBpZiBub3QgZnAuZXhpc3RzKCk6CiAgICAgICAgICAgIGZwLndyaXR"
    "lX3RleHQoIiIsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgc2xfZGlyID0gY2ZnX3BhdGgoInNsIikKIC"
    "AgIGZvciBmbmFtZSBpbiAoInNsX3NjYW5zLmpzb25sIiwgInNsX2NvbW1hbmRzLmpzb25sIik6CiAgI"
    "CAgICAgZnAgPSBzbF9kaXIgLyBmbmFtZQogICAgICAgIGlmIG5vdCBmcC5leGlzdHMoKToKICAgICAg"
    "ICAgICAgZnAud3JpdGVfdGV4dCgiIiwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBzZXNzaW9uc19kaXI"
    "gPSBjZmdfcGF0aCgic2Vzc2lvbnMiKQogICAgaWR4ID0gc2Vzc2lvbnNfZGlyIC8gInNlc3Npb25faW"
    "5kZXguanNvbiIKICAgIGlmIG5vdCBpZHguZXhpc3RzKCk6CiAgICAgICAgaWR4LndyaXRlX3RleHQoa"
    "nNvbi5kdW1wcyh7InNlc3Npb25zIjogW119LCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIpCgog"
    "ICAgc3RhdGVfcGF0aCA9IG1lbW9yeV9kaXIgLyAic3RhdGUuanNvbiIKICAgIGlmIG5vdCBzdGF0ZV9"
    "wYXRoLmV4aXN0cygpOgogICAgICAgIF93cml0ZV9kZWZhdWx0X3N0YXRlKHN0YXRlX3BhdGgpCgogIC"
    "AgaW5kZXhfcGF0aCA9IG1lbW9yeV9kaXIgLyAiaW5kZXguanNvbiIKICAgIGlmIG5vdCBpbmRleF9wY"
    "XRoLmV4aXN0cygpOgogICAgICAgIGluZGV4X3BhdGgud3JpdGVfdGV4dCgKICAgICAgICAgICAganNv"
    "bi5kdW1wcyh7InZlcnNpb24iOiBBUFBfVkVSU0lPTiwgInRvdGFsX21lc3NhZ2VzIjogMCwKICAgICA"
    "gICAgICAgICAgICAgICAgICAgInRvdGFsX21lbW9yaWVzIjogMH0sIGluZGVudD0yKSwKICAgICAgIC"
    "AgICAgZW5jb2Rpbmc9InV0Zi04IgogICAgICAgICkKCiAgICAjIExlZ2FjeSBtaWdyYXRpb246IGlmI"
    "G9sZCBNb3JnYW5uYV9NZW1vcmllcyBmb2xkZXIgZXhpc3RzLCBtaWdyYXRlIGZpbGVzCiAgICBfbWln"
    "cmF0ZV9sZWdhY3lfZmlsZXMoKQoKZGVmIF93cml0ZV9kZWZhdWx0X3N0YXRlKHBhdGg6IFBhdGgpIC0"
    "+IE5vbmU6CiAgICBzdGF0ZSA9IHsKICAgICAgICAicGVyc29uYV9uYW1lIjogREVDS19OQU1FLAogIC"
    "AgICAgICJkZWNrX3ZlcnNpb24iOiBBUFBfVkVSU0lPTiwKICAgICAgICAic2Vzc2lvbl9jb3VudCI6I"
    "DAsCiAgICAgICAgImxhc3Rfc3RhcnR1cCI6IE5vbmUsCiAgICAgICAgImxhc3Rfc2h1dGRvd24iOiBO"
    "b25lLAogICAgICAgICJsYXN0X2FjdGl2ZSI6IE5vbmUsCiAgICAgICAgInRvdGFsX21lc3NhZ2VzIjo"
    "gMCwKICAgICAgICAidG90YWxfbWVtb3JpZXMiOiAwLAogICAgICAgICJpbnRlcm5hbF9uYXJyYXRpdm"
    "UiOiB7fSwKICAgICAgICAidmFtcGlyZV9zdGF0ZV9hdF9zaHV0ZG93biI6ICJET1JNQU5UIiwKICAgI"
    "H0KICAgIHBhdGgud3JpdGVfdGV4dChqc29uLmR1bXBzKHN0YXRlLCBpbmRlbnQ9MiksIGVuY29kaW5n"
    "PSJ1dGYtOCIpCgpkZWYgX21pZ3JhdGVfbGVnYWN5X2ZpbGVzKCkgLT4gTm9uZToKICAgICIiIgogICA"
    "gSWYgb2xkIEQ6XFxBSVxcTW9kZWxzXFxbRGVja05hbWVdX01lbW9yaWVzIGxheW91dCBpcyBkZXRlY3"
    "RlZCwKICAgIG1pZ3JhdGUgZmlsZXMgdG8gbmV3IHN0cnVjdHVyZSBzaWxlbnRseS4KICAgICIiIgogI"
    "CAgIyBUcnkgdG8gZmluZCBvbGQgbGF5b3V0IHJlbGF0aXZlIHRvIG1vZGVsIHBhdGgKICAgIG1vZGVs"
    "X3BhdGggPSBQYXRoKENGR1sibW9kZWwiXS5nZXQoInBhdGgiLCAiIikpCiAgICBpZiBub3QgbW9kZWx"
    "fcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4KICAgIG9sZF9yb290ID0gbW9kZWxfcGF0aC5wYX"
    "JlbnQgLyBmIntERUNLX05BTUV9X01lbW9yaWVzIgogICAgaWYgbm90IG9sZF9yb290LmV4aXN0cygpO"
    "gogICAgICAgIHJldHVybgoKICAgIG1pZ3JhdGlvbnMgPSBbCiAgICAgICAgKG9sZF9yb290IC8gIm1l"
    "bW9yaWVzLmpzb25sIiwgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gIm1lbW9yaWVzLmp"
    "zb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gIm1lc3NhZ2VzLmpzb25sIiwgICAgICAgICAgICBjZm"
    "dfcGF0aCgibWVtb3JpZXMiKSAvICJtZXNzYWdlcy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAvI"
    "CJ0YXNrcy5qc29ubCIsICAgICAgICAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAidGFza3Mu"
    "anNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAic3RhdGUuanNvbiIsICAgICAgICAgICAgICAgIGN"
    "mZ19wYXRoKCJtZW1vcmllcyIpIC8gInN0YXRlLmpzb24iKSwKICAgICAgICAob2xkX3Jvb3QgLyAiaW"
    "5kZXguanNvbiIsICAgICAgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gImluZGV4Lmpzb"
    "24iKSwKICAgICAgICAob2xkX3Jvb3QgLyAic2xfc2NhbnMuanNvbmwiLCAgICAgICAgICAgIGNmZ19w"
    "YXRoKCJzbCIpIC8gInNsX3NjYW5zLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gInNsX2NvbW1"
    "hbmRzLmpzb25sIiwgICAgICAgICBjZmdfcGF0aCgic2wiKSAvICJzbF9jb21tYW5kcy5qc29ubCIpLA"
    "ogICAgICAgIChvbGRfcm9vdCAvICJnb29nbGUiIC8gInRva2VuLmpzb24iLCAgICAgUGF0aChDRkdbI"
    "mdvb2dsZSJdWyJ0b2tlbiJdKSksCiAgICAgICAgKG9sZF9yb290IC8gImNvbmZpZyIgLyAiZ29vZ2xl"
    "X2NyZWRlbnRpYWxzLmpzb24iLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA"
    "gICAgICAgICAgIFBhdGgoQ0ZHWyJnb29nbGUiXVsiY3JlZGVudGlhbHMiXSkpLAogICAgICAgIChvbG"
    "Rfcm9vdCAvICJzb3VuZHMiIC8gZiJ7U09VTkRfUFJFRklYfV9hbGVydC53YXYiLAogICAgICAgICAgI"
    "CAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGNmZ19wYXRoKCJzb3VuZHMiKSAv"
    "IGYie1NPVU5EX1BSRUZJWH1fYWxlcnQud2F2IiksCiAgICBdCgogICAgZm9yIHNyYywgZHN0IGluIG1"
    "pZ3JhdGlvbnM6CiAgICAgICAgaWYgc3JjLmV4aXN0cygpIGFuZCBub3QgZHN0LmV4aXN0cygpOgogIC"
    "AgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBkc3QucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1Z"
    "SwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAgICAgICAgIGltcG9ydCBzaHV0aWwKICAgICAgICAgICAg"
    "ICAgIHNodXRpbC5jb3B5MihzdHIoc3JjKSwgc3RyKGRzdCkpCiAgICAgICAgICAgIGV4Y2VwdCBFeGN"
    "lcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgIyBNaWdyYXRlIGZhY2UgaW1hZ2VzCiAgIC"
    "BvbGRfZmFjZXMgPSBvbGRfcm9vdCAvICJGYWNlcyIKICAgIG5ld19mYWNlcyA9IGNmZ19wYXRoKCJmY"
    "WNlcyIpCiAgICBpZiBvbGRfZmFjZXMuZXhpc3RzKCk6CiAgICAgICAgZm9yIGltZyBpbiBvbGRfZmFj"
    "ZXMuZ2xvYigiKi5wbmciKToKICAgICAgICAgICAgZHN0ID0gbmV3X2ZhY2VzIC8gaW1nLm5hbWUKICA"
    "gICAgICAgICAgaWYgbm90IGRzdC5leGlzdHMoKToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgIC"
    "AgICAgICAgICAgICBpbXBvcnQgc2h1dGlsCiAgICAgICAgICAgICAgICAgICAgc2h1dGlsLmNvcHkyK"
    "HN0cihpbWcpLCBzdHIoZHN0KSkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAg"
    "ICAgICAgICAgICAgICAgcGFzcwoKIyDilIDilIAgREFURVRJTUUgSEVMUEVSUyDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGxvY2FsX25vd19p"
    "c28oKSAtPiBzdHI6CiAgICByZXR1cm4gZGF0ZXRpbWUubm93KCkucmVwbGFjZShtaWNyb3NlY29uZD0"
    "wKS5pc29mb3JtYXQoKQoKZGVmIHBhcnNlX2lzbyh2YWx1ZTogc3RyKSAtPiBPcHRpb25hbFtkYXRldG"
    "ltZV06CiAgICBpZiBub3QgdmFsdWU6CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIHZhbHVlID0gdmFsd"
    "WUuc3RyaXAoKQogICAgdHJ5OgogICAgICAgIGlmIHZhbHVlLmVuZHN3aXRoKCJaIik6CiAgICAgICAg"
    "ICAgIHJldHVybiBkYXRldGltZS5mcm9taXNvZm9ybWF0KHZhbHVlWzotMV0pLnJlcGxhY2UodHppbmZ"
    "vPXRpbWV6b25lLnV0YykKICAgICAgICByZXR1cm4gZGF0ZXRpbWUuZnJvbWlzb2Zvcm1hdCh2YWx1ZS"
    "kKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcmV0dXJuIE5vbmUKCl9EQVRFVElNRV9OT1JNQ"
    "UxJWkFUSU9OX0xPR0dFRDogc2V0W3R1cGxlXSA9IHNldCgpCgoKZGVmIF9yZXNvbHZlX2RlY2tfdGlt"
    "ZXpvbmVfbmFtZSgpIC0+IE9wdGlvbmFsW3N0cl06CiAgICBzZXR0aW5ncyA9IENGRy5nZXQoInNldHR"
    "pbmdzIiwge30pIGlmIGlzaW5zdGFuY2UoQ0ZHLCBkaWN0KSBlbHNlIHt9CiAgICBhdXRvX2RldGVjdC"
    "A9IGJvb2woc2V0dGluZ3MuZ2V0KCJ0aW1lem9uZV9hdXRvX2RldGVjdCIsIFRydWUpKQogICAgb3Zlc"
    "nJpZGUgPSBzdHIoc2V0dGluZ3MuZ2V0KCJ0aW1lem9uZV9vdmVycmlkZSIsICIiKSBvciAiIikuc3Ry"
    "aXAoKQogICAgaWYgbm90IGF1dG9fZGV0ZWN0IGFuZCBvdmVycmlkZToKICAgICAgICByZXR1cm4gb3Z"
    "lcnJpZGUKICAgIGxvY2FsX3R6aW5mbyA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS50emluZm"
    "8KICAgIGlmIGxvY2FsX3R6aW5mbyBpcyBub3QgTm9uZToKICAgICAgICB0el9rZXkgPSBnZXRhdHRyK"
    "GxvY2FsX3R6aW5mbywgImtleSIsIE5vbmUpCiAgICAgICAgaWYgdHpfa2V5OgogICAgICAgICAgICBy"
    "ZXR1cm4gc3RyKHR6X2tleSkKICAgICAgICB0el9uYW1lID0gc3RyKGxvY2FsX3R6aW5mbykKICAgICA"
    "gICBpZiB0el9uYW1lIGFuZCB0el9uYW1lLnVwcGVyKCkgIT0gIkxPQ0FMIjoKICAgICAgICAgICAgcm"
    "V0dXJuIHR6X25hbWUKICAgIHJldHVybiBOb25lCgoKZGVmIF9sb2NhbF90emluZm8oKToKICAgIHR6X"
    "25hbWUgPSBfcmVzb2x2ZV9kZWNrX3RpbWV6b25lX25hbWUoKQogICAgaWYgdHpfbmFtZToKICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgIHJldHVybiBab25lSW5mbyh0el9uYW1lKQogICAgICAgIGV4Y2VwdCB"
    "ab25lSW5mb05vdEZvdW5kRXJyb3I6CiAgICAgICAgICAgIF9lYXJseV9sb2coZiJbREFURVRJTUVdW1"
    "dBUk5dIFVua25vd24gdGltZXpvbmUgb3ZlcnJpZGUgJ3t0el9uYW1lfScsIHVzaW5nIHN5c3RlbSBsb"
    "2NhbCB0aW1lem9uZS4iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MK"
    "ICAgIHJldHVybiBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudHppbmZvIG9yIHRpbWV6b25lLnV"
    "0YwoKCmRlZiBub3dfZm9yX2NvbXBhcmUoKToKICAgIHJldHVybiBkYXRldGltZS5ub3coX2xvY2FsX3"
    "R6aW5mbygpKQoKCmRlZiBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUoZHRfdmFsdWUsIGNvb"
    "nRleHQ6IHN0ciA9ICIiKToKICAgIGlmIGR0X3ZhbHVlIGlzIE5vbmU6CiAgICAgICAgcmV0dXJuIE5v"
    "bmUKICAgIGlmIG5vdCBpc2luc3RhbmNlKGR0X3ZhbHVlLCBkYXRldGltZSk6CiAgICAgICAgcmV0dXJ"
    "uIE5vbmUKICAgIGxvY2FsX3R6ID0gX2xvY2FsX3R6aW5mbygpCiAgICBpZiBkdF92YWx1ZS50emluZm"
    "8gaXMgTm9uZToKICAgICAgICBub3JtYWxpemVkID0gZHRfdmFsdWUucmVwbGFjZSh0emluZm89bG9jY"
    "WxfdHopCiAgICAgICAga2V5ID0gKCJuYWl2ZSIsIGNvbnRleHQpCiAgICAgICAgaWYga2V5IG5vdCBp"
    "biBfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQ6CiAgICAgICAgICAgIF9lYXJseV9sb2coCiA"
    "gICAgICAgICAgICAgICBmIltEQVRFVElNRV1bSU5GT10gTm9ybWFsaXplZCBuYWl2ZSBkYXRldGltZS"
    "B0byBsb2NhbCB0aW1lem9uZSBmb3Ige2NvbnRleHQgb3IgJ2dlbmVyYWwnfSBjb21wYXJpc29ucy4iC"
    "iAgICAgICAgICAgICkKICAgICAgICAgICAgX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VELmFk"
    "ZChrZXkpCiAgICAgICAgcmV0dXJuIG5vcm1hbGl6ZWQKICAgIG5vcm1hbGl6ZWQgPSBkdF92YWx1ZS5"
    "hc3RpbWV6b25lKGxvY2FsX3R6KQogICAgZHRfdHpfbmFtZSA9IHN0cihkdF92YWx1ZS50emluZm8pCi"
    "AgICBrZXkgPSAoImF3YXJlIiwgY29udGV4dCwgZHRfdHpfbmFtZSkKICAgIGlmIGtleSBub3QgaW4gX"
    "0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VEIGFuZCBkdF90el9uYW1lIG5vdCBpbiB7IlVUQyIs"
    "IHN0cihsb2NhbF90eil9OgogICAgICAgIF9lYXJseV9sb2coCiAgICAgICAgICAgIGYiW0RBVEVUSU1"
    "FXVtJTkZPXSBOb3JtYWxpemVkIHRpbWV6b25lLWF3YXJlIGRhdGV0aW1lIGZyb20ge2R0X3R6X25hbW"
    "V9IHRvIGxvY2FsIHRpbWV6b25lIGZvciB7Y29udGV4dCBvciAnZ2VuZXJhbCd9IGNvbXBhcmlzb25zL"
    "iIKICAgICAgICApCiAgICAgICAgX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VELmFkZChrZXkp"
    "CiAgICByZXR1cm4gbm9ybWFsaXplZAoKCmRlZiBwYXJzZV9pc29fZm9yX2NvbXBhcmUodmFsdWUsIGN"
    "vbnRleHQ6IHN0ciA9ICIiKToKICAgIHJldHVybiBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcm"
    "UocGFyc2VfaXNvKHZhbHVlKSwgY29udGV4dD1jb250ZXh0KQoKCmRlZiBfdGFza19kdWVfc29ydF9rZ"
    "XkodGFzazogZGljdCk6CiAgICBkdWUgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoKHRhc2sgb3Ige30p"
    "LmdldCgiZHVlX2F0Iikgb3IgKHRhc2sgb3Ige30pLmdldCgiZHVlIiksIGNvbnRleHQ9InRhc2tfc29"
    "ydCIpCiAgICBpZiBkdWUgaXMgTm9uZToKICAgICAgICByZXR1cm4gKDEsIGRhdGV0aW1lLm1heC5yZX"
    "BsYWNlKHR6aW5mbz10aW1lem9uZS51dGMpKQogICAgcmV0dXJuICgwLCBkdWUuYXN0aW1lem9uZSh0a"
    "W1lem9uZS51dGMpLCAoKHRhc2sgb3Ige30pLmdldCgidGV4dCIpIG9yICIiKS5sb3dlcigpKQoKCmRl"
    "ZiBmb3JtYXRfZHVyYXRpb24oc2Vjb25kczogZmxvYXQpIC0+IHN0cjoKICAgIHRvdGFsID0gbWF4KDA"
    "sIGludChzZWNvbmRzKSkKICAgIGRheXMsIHJlbSA9IGRpdm1vZCh0b3RhbCwgODY0MDApCiAgICBob3"
    "VycywgcmVtID0gZGl2bW9kKHJlbSwgMzYwMCkKICAgIG1pbnV0ZXMsIHNlY3MgPSBkaXZtb2QocmVtL"
    "CA2MCkKICAgIHBhcnRzID0gW10KICAgIGlmIGRheXM6ICAgIHBhcnRzLmFwcGVuZChmIntkYXlzfWQi"
    "KQogICAgaWYgaG91cnM6ICAgcGFydHMuYXBwZW5kKGYie2hvdXJzfWgiKQogICAgaWYgbWludXRlczo"
    "gcGFydHMuYXBwZW5kKGYie21pbnV0ZXN9bSIpCiAgICBpZiBub3QgcGFydHM6IHBhcnRzLmFwcGVuZC"
    "hmIntzZWNzfXMiKQogICAgcmV0dXJuICIgIi5qb2luKHBhcnRzWzozXSkKCiMg4pSA4pSAIE1PT04gU"
    "EhBU0UgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIAKIyBDb3JyZWN0ZWQgaWxsdW1pbmF0aW9uIG1hdGgg4oCUIGRpc3BsYXllZCBtb29uIG1hdGNoZ"
    "XMgbGFiZWxlZCBwaGFzZS4KCl9LTk9XTl9ORVdfTU9PTiA9IGRhdGUoMjAwMCwgMSwgNikKX0xVTkFS"
    "X0NZQ0xFICAgID0gMjkuNTMwNTg4NjcKCmRlZiBnZXRfbW9vbl9waGFzZSgpIC0+IHR1cGxlW2Zsb2F"
    "0LCBzdHIsIGZsb2F0XToKICAgICIiIgogICAgUmV0dXJucyAocGhhc2VfZnJhY3Rpb24sIHBoYXNlX2"
    "5hbWUsIGlsbHVtaW5hdGlvbl9wY3QpLgogICAgcGhhc2VfZnJhY3Rpb246IDAuMCA9IG5ldyBtb29uL"
    "CAwLjUgPSBmdWxsIG1vb24sIDEuMCA9IG5ldyBtb29uIGFnYWluLgogICAgaWxsdW1pbmF0aW9uX3Bj"
    "dDogMOKAkzEwMCwgY29ycmVjdGVkIHRvIG1hdGNoIHZpc3VhbCBwaGFzZS4KICAgICIiIgogICAgZGF"
    "5cyAgPSAoZGF0ZS50b2RheSgpIC0gX0tOT1dOX05FV19NT09OKS5kYXlzCiAgICBjeWNsZSA9IGRheX"
    "MgJSBfTFVOQVJfQ1lDTEUKICAgIHBoYXNlID0gY3ljbGUgLyBfTFVOQVJfQ1lDTEUKCiAgICBpZiAgI"
    "GN5Y2xlIDwgMS44NTogICBuYW1lID0gIk5FVyBNT09OIgogICAgZWxpZiBjeWNsZSA8IDcuMzg6ICAg"
    "bmFtZSA9ICJXQVhJTkcgQ1JFU0NFTlQiCiAgICBlbGlmIGN5Y2xlIDwgOS4yMjogICBuYW1lID0gIkZ"
    "JUlNUIFFVQVJURVIiCiAgICBlbGlmIGN5Y2xlIDwgMTQuNzc6ICBuYW1lID0gIldBWElORyBHSUJCT1"
    "VTIgogICAgZWxpZiBjeWNsZSA8IDE2LjYxOiAgbmFtZSA9ICJGVUxMIE1PT04iCiAgICBlbGlmIGN5Y"
    "2xlIDwgMjIuMTU6ICBuYW1lID0gIldBTklORyBHSUJCT1VTIgogICAgZWxpZiBjeWNsZSA8IDIzLjk5"
    "OiAgbmFtZSA9ICJMQVNUIFFVQVJURVIiCiAgICBlbHNlOiAgICAgICAgICAgICAgICBuYW1lID0gIld"
    "BTklORyBDUkVTQ0VOVCIKCiAgICAjIENvcnJlY3RlZCBpbGx1bWluYXRpb246IGNvcy1iYXNlZCwgcG"
    "Vha3MgYXQgZnVsbCBtb29uCiAgICBpbGx1bWluYXRpb24gPSAoMSAtIG1hdGguY29zKDIgKiBtYXRoL"
    "nBpICogcGhhc2UpKSAvIDIgKiAxMDAKICAgIHJldHVybiBwaGFzZSwgbmFtZSwgcm91bmQoaWxsdW1p"
    "bmF0aW9uLCAxKQoKX1NVTl9DQUNIRV9EQVRFOiBPcHRpb25hbFtkYXRlXSA9IE5vbmUKX1NVTl9DQUN"
    "IRV9UWl9PRkZTRVRfTUlOOiBPcHRpb25hbFtpbnRdID0gTm9uZQpfU1VOX0NBQ0hFX1RJTUVTOiB0dX"
    "BsZVtzdHIsIHN0cl0gPSAoIjA2OjAwIiwgIjE4OjMwIikKCmRlZiBfcmVzb2x2ZV9zb2xhcl9jb29yZ"
    "GluYXRlcygpIC0+IHR1cGxlW2Zsb2F0LCBmbG9hdF06CiAgICAiIiIKICAgIFJlc29sdmUgbGF0aXR1"
    "ZGUvbG9uZ2l0dWRlIGZyb20gcnVudGltZSBjb25maWcgd2hlbiBhdmFpbGFibGUuCiAgICBGYWxscyB"
    "iYWNrIHRvIHRpbWV6b25lLWRlcml2ZWQgY29hcnNlIGRlZmF1bHRzLgogICAgIiIiCiAgICBsYXQgPS"
    "BOb25lCiAgICBsb24gPSBOb25lCiAgICB0cnk6CiAgICAgICAgc2V0dGluZ3MgPSBDRkcuZ2V0KCJzZ"
    "XR0aW5ncyIsIHt9KSBpZiBpc2luc3RhbmNlKENGRywgZGljdCkgZWxzZSB7fQogICAgICAgIGZvciBr"
    "ZXkgaW4gKCJsYXRpdHVkZSIsICJsYXQiKToKICAgICAgICAgICAgaWYga2V5IGluIHNldHRpbmdzOgo"
    "gICAgICAgICAgICAgICAgbGF0ID0gZmxvYXQoc2V0dGluZ3Nba2V5XSkKICAgICAgICAgICAgICAgIG"
    "JyZWFrCiAgICAgICAgZm9yIGtleSBpbiAoImxvbmdpdHVkZSIsICJsb24iLCAibG5nIik6CiAgICAgI"
    "CAgICAgIGlmIGtleSBpbiBzZXR0aW5nczoKICAgICAgICAgICAgICAgIGxvbiA9IGZsb2F0KHNldHRp"
    "bmdzW2tleV0pCiAgICAgICAgICAgICAgICBicmVhawogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICA"
    "gICBsYXQgPSBOb25lCiAgICAgICAgbG9uID0gTm9uZQoKICAgIG5vd19sb2NhbCA9IGRhdGV0aW1lLm"
    "5vdygpLmFzdGltZXpvbmUoKQogICAgdHpfb2Zmc2V0ID0gbm93X2xvY2FsLnV0Y29mZnNldCgpIG9yI"
    "HRpbWVkZWx0YSgwKQogICAgdHpfb2Zmc2V0X2hvdXJzID0gdHpfb2Zmc2V0LnRvdGFsX3NlY29uZHMo"
    "KSAvIDM2MDAuMAoKICAgIGlmIGxvbiBpcyBOb25lOgogICAgICAgIGxvbiA9IG1heCgtMTgwLjAsIG1"
    "pbigxODAuMCwgdHpfb2Zmc2V0X2hvdXJzICogMTUuMCkpCgogICAgaWYgbGF0IGlzIE5vbmU6CiAgIC"
    "AgICAgdHpfbmFtZSA9IHN0cihub3dfbG9jYWwudHppbmZvIG9yICIiKQogICAgICAgIHNvdXRoX2hpb"
    "nQgPSBhbnkodG9rZW4gaW4gdHpfbmFtZSBmb3IgdG9rZW4gaW4gKCJBdXN0cmFsaWEiLCAiUGFjaWZp"
    "Yy9BdWNrbGFuZCIsICJBbWVyaWNhL1NhbnRpYWdvIikpCiAgICAgICAgbGF0ID0gLTM1LjAgaWYgc29"
    "1dGhfaGludCBlbHNlIDM1LjAKCiAgICBsYXQgPSBtYXgoLTY2LjAsIG1pbig2Ni4wLCBsYXQpKQogIC"
    "AgbG9uID0gbWF4KC0xODAuMCwgbWluKDE4MC4wLCBsb24pKQogICAgcmV0dXJuIGxhdCwgbG9uCgpkZ"
    "WYgX2NhbGNfc29sYXJfZXZlbnRfbWludXRlcyhsb2NhbF9kYXk6IGRhdGUsIGxhdGl0dWRlOiBmbG9h"
    "dCwgbG9uZ2l0dWRlOiBmbG9hdCwgc3VucmlzZTogYm9vbCkgLT4gT3B0aW9uYWxbZmxvYXRdOgogICA"
    "gIiIiTk9BQS1zdHlsZSBzdW5yaXNlL3N1bnNldCBzb2x2ZXIuIFJldHVybnMgbG9jYWwgbWludXRlcy"
    "Bmcm9tIG1pZG5pZ2h0LiIiIgogICAgbiA9IGxvY2FsX2RheS50aW1ldHVwbGUoKS50bV95ZGF5CiAgI"
    "CBsbmdfaG91ciA9IGxvbmdpdHVkZSAvIDE1LjAKICAgIHQgPSBuICsgKCg2IC0gbG5nX2hvdXIpIC8g"
    "MjQuMCkgaWYgc3VucmlzZSBlbHNlIG4gKyAoKDE4IC0gbG5nX2hvdXIpIC8gMjQuMCkKCiAgICBNID0"
    "gKDAuOTg1NiAqIHQpIC0gMy4yODkKICAgIEwgPSBNICsgKDEuOTE2ICogbWF0aC5zaW4obWF0aC5yYW"
    "RpYW5zKE0pKSkgKyAoMC4wMjAgKiBtYXRoLnNpbihtYXRoLnJhZGlhbnMoMiAqIE0pKSkgKyAyODIuN"
    "jM0CiAgICBMID0gTCAlIDM2MC4wCgogICAgUkEgPSBtYXRoLmRlZ3JlZXMobWF0aC5hdGFuKDAuOTE3"
    "NjQgKiBtYXRoLnRhbihtYXRoLnJhZGlhbnMoTCkpKSkKICAgIFJBID0gUkEgJSAzNjAuMAogICAgTF9"
    "xdWFkcmFudCA9IChtYXRoLmZsb29yKEwgLyA5MC4wKSkgKiA5MC4wCiAgICBSQV9xdWFkcmFudCA9IC"
    "htYXRoLmZsb29yKFJBIC8gOTAuMCkpICogOTAuMAogICAgUkEgPSAoUkEgKyAoTF9xdWFkcmFudCAtI"
    "FJBX3F1YWRyYW50KSkgLyAxNS4wCgogICAgc2luX2RlYyA9IDAuMzk3ODIgKiBtYXRoLnNpbihtYXRo"
    "LnJhZGlhbnMoTCkpCiAgICBjb3NfZGVjID0gbWF0aC5jb3MobWF0aC5hc2luKHNpbl9kZWMpKQoKICA"
    "gIHplbml0aCA9IDkwLjgzMwogICAgY29zX2ggPSAobWF0aC5jb3MobWF0aC5yYWRpYW5zKHplbml0aC"
    "kpIC0gKHNpbl9kZWMgKiBtYXRoLnNpbihtYXRoLnJhZGlhbnMobGF0aXR1ZGUpKSkpIC8gKGNvc19kZ"
    "WMgKiBtYXRoLmNvcyhtYXRoLnJhZGlhbnMobGF0aXR1ZGUpKSkKICAgIGlmIGNvc19oIDwgLTEuMCBv"
    "ciBjb3NfaCA+IDEuMDoKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGlmIHN1bnJpc2U6CiAgICAgICA"
    "gSCA9IDM2MC4wIC0gbWF0aC5kZWdyZWVzKG1hdGguYWNvcyhjb3NfaCkpCiAgICBlbHNlOgogICAgIC"
    "AgIEggPSBtYXRoLmRlZ3JlZXMobWF0aC5hY29zKGNvc19oKSkKICAgIEggLz0gMTUuMAoKICAgIFQgP"
    "SBIICsgUkEgLSAoMC4wNjU3MSAqIHQpIC0gNi42MjIKICAgIFVUID0gKFQgLSBsbmdfaG91cikgJSAy"
    "NC4wCgogICAgbG9jYWxfb2Zmc2V0X2hvdXJzID0gKGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5"
    "1dGNvZmZzZXQoKSBvciB0aW1lZGVsdGEoMCkpLnRvdGFsX3NlY29uZHMoKSAvIDM2MDAuMAogICAgbG"
    "9jYWxfaG91ciA9IChVVCArIGxvY2FsX29mZnNldF9ob3VycykgJSAyNC4wCiAgICByZXR1cm4gbG9jY"
    "WxfaG91ciAqIDYwLjAKCmRlZiBfZm9ybWF0X2xvY2FsX3NvbGFyX3RpbWUobWludXRlc19mcm9tX21p"
    "ZG5pZ2h0OiBPcHRpb25hbFtmbG9hdF0pIC0+IHN0cjoKICAgIGlmIG1pbnV0ZXNfZnJvbV9taWRuaWd"
    "odCBpcyBOb25lOgogICAgICAgIHJldHVybiAiLS06LS0iCiAgICBtaW5zID0gaW50KHJvdW5kKG1pbn"
    "V0ZXNfZnJvbV9taWRuaWdodCkpICUgKDI0ICogNjApCiAgICBoaCwgbW0gPSBkaXZtb2QobWlucywgN"
    "jApCiAgICByZXR1cm4gZGF0ZXRpbWUubm93KCkucmVwbGFjZShob3VyPWhoLCBtaW51dGU9bW0sIHNl"
    "Y29uZD0wLCBtaWNyb3NlY29uZD0wKS5zdHJmdGltZSgiJUg6JU0iKQoKZGVmIGdldF9zdW5fdGltZXM"
    "oKSAtPiB0dXBsZVtzdHIsIHN0cl06CiAgICAiIiIKICAgIENvbXB1dGUgbG9jYWwgc3VucmlzZS9zdW"
    "5zZXQgdXNpbmcgc3lzdGVtIGRhdGUgKyB0aW1lem9uZSBhbmQgb3B0aW9uYWwKICAgIHJ1bnRpbWUgb"
    "GF0aXR1ZGUvbG9uZ2l0dWRlIGhpbnRzIHdoZW4gYXZhaWxhYmxlLgogICAgQ2FjaGVkIHBlciBsb2Nh"
    "bCBkYXRlIGFuZCB0aW1lem9uZSBvZmZzZXQuCiAgICAiIiIKICAgIGdsb2JhbCBfU1VOX0NBQ0hFX0R"
    "BVEUsIF9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTiwgX1NVTl9DQUNIRV9USU1FUwoKICAgIG5vd19sb2"
    "NhbCA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKQogICAgdG9kYXkgPSBub3dfbG9jYWwuZGF0Z"
    "SgpCiAgICB0el9vZmZzZXRfbWluID0gaW50KChub3dfbG9jYWwudXRjb2Zmc2V0KCkgb3IgdGltZWRl"
    "bHRhKDApKS50b3RhbF9zZWNvbmRzKCkgLy8gNjApCgogICAgaWYgX1NVTl9DQUNIRV9EQVRFID09IHR"
    "vZGF5IGFuZCBfU1VOX0NBQ0hFX1RaX09GRlNFVF9NSU4gPT0gdHpfb2Zmc2V0X21pbjoKICAgICAgIC"
    "ByZXR1cm4gX1NVTl9DQUNIRV9USU1FUwoKICAgIHRyeToKICAgICAgICBsYXQsIGxvbiA9IF9yZXNvb"
    "HZlX3NvbGFyX2Nvb3JkaW5hdGVzKCkKICAgICAgICBzdW5yaXNlX21pbiA9IF9jYWxjX3NvbGFyX2V2"
    "ZW50X21pbnV0ZXModG9kYXksIGxhdCwgbG9uLCBzdW5yaXNlPVRydWUpCiAgICAgICAgc3Vuc2V0X21"
    "pbiA9IF9jYWxjX3NvbGFyX2V2ZW50X21pbnV0ZXModG9kYXksIGxhdCwgbG9uLCBzdW5yaXNlPUZhbH"
    "NlKQogICAgICAgIGlmIHN1bnJpc2VfbWluIGlzIE5vbmUgb3Igc3Vuc2V0X21pbiBpcyBOb25lOgogI"
    "CAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJTb2xhciBldmVudCB1bmF2YWlsYWJsZSBmb3IgcmVz"
    "b2x2ZWQgY29vcmRpbmF0ZXMiKQogICAgICAgIHRpbWVzID0gKF9mb3JtYXRfbG9jYWxfc29sYXJfdGl"
    "tZShzdW5yaXNlX21pbiksIF9mb3JtYXRfbG9jYWxfc29sYXJfdGltZShzdW5zZXRfbWluKSkKICAgIG"
    "V4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgdGltZXMgPSAoIjA2OjAwIiwgIjE4OjMwIikKCiAgICBfU"
    "1VOX0NBQ0hFX0RBVEUgPSB0b2RheQogICAgX1NVTl9DQUNIRV9UWl9PRkZTRVRfTUlOID0gdHpfb2Zm"
    "c2V0X21pbgogICAgX1NVTl9DQUNIRV9USU1FUyA9IHRpbWVzCiAgICByZXR1cm4gdGltZXMKCiMg4pS"
    "A4pSAIFZBTVBJUkUgU1RBVEUgU1lTVEVNIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAojIFRpbWUtb2YtZGF5IGJlaGF2aW9yYWwgc3RhdGUuIEFjdGl2ZSBvbmx5IHdoZW4"
    "gQUlfU1RBVEVTX0VOQUJMRUQ9VHJ1ZS4KIyBJbmplY3RlZCBpbnRvIHN5c3RlbSBwcm9tcHQgb24gZX"
    "ZlcnkgZ2VuZXJhdGlvbiBjYWxsLgoKVkFNUElSRV9TVEFURVM6IGRpY3Rbc3RyLCBkaWN0XSA9IHsKI"
    "CAgICJXSVRDSElORyBIT1VSIjogIHsiaG91cnMiOiB7MH0sICAgICAgICAgICAiY29sb3IiOiBDX0dP"
    "TEQsICAgICAgICAicG93ZXIiOiAxLjB9LAogICAgIkRFRVAgTklHSFQiOiAgICAgeyJob3VycyI6IHs"
    "xLDIsM30sICAgICAgICAiY29sb3IiOiBDX1BVUlBMRSwgICAgICAicG93ZXIiOiAwLjk1fSwKICAgIC"
    "JUV0lMSUdIVCBGQURJTkciOnsiaG91cnMiOiB7NCw1fSwgICAgICAgICAgImNvbG9yIjogQ19TSUxWR"
    "VIsICAgICAgInBvd2VyIjogMC43fSwKICAgICJET1JNQU5UIjogICAgICAgIHsiaG91cnMiOiB7Niw3"
    "LDgsOSwxMCwxMX0sImNvbG9yIjogQ19URVhUX0RJTSwgICAgInBvd2VyIjogMC4yfSwKICAgICJSRVN"
    "UTEVTUyBTTEVFUCI6IHsiaG91cnMiOiB7MTIsMTMsMTQsMTV9LCAgImNvbG9yIjogQ19URVhUX0RJTS"
    "wgICAgInBvd2VyIjogMC4zfSwKICAgICJTVElSUklORyI6ICAgICAgIHsiaG91cnMiOiB7MTYsMTd9L"
    "CAgICAgICAgImNvbG9yIjogQ19HT0xEX0RJTSwgICAgInBvd2VyIjogMC42fSwKICAgICJBV0FLRU5F"
    "RCI6ICAgICAgIHsiaG91cnMiOiB7MTgsMTksMjAsMjF9LCAgImNvbG9yIjogQ19HT0xELCAgICAgICA"
    "gInBvd2VyIjogMC45fSwKICAgICJIVU5USU5HIjogICAgICAgIHsiaG91cnMiOiB7MjIsMjN9LCAgIC"
    "AgICAgImNvbG9yIjogQ19DUklNU09OLCAgICAgInBvd2VyIjogMS4wfSwKfQoKZGVmIGdldF92YW1wa"
    "XJlX3N0YXRlKCkgLT4gc3RyOgogICAgIiIiUmV0dXJuIHRoZSBjdXJyZW50IHZhbXBpcmUgc3RhdGUg"
    "bmFtZSBiYXNlZCBvbiBsb2NhbCBob3VyLiIiIgogICAgaCA9IGRhdGV0aW1lLm5vdygpLmhvdXIKICA"
    "gIGZvciBzdGF0ZV9uYW1lLCBkYXRhIGluIFZBTVBJUkVfU1RBVEVTLml0ZW1zKCk6CiAgICAgICAgaW"
    "YgaCBpbiBkYXRhWyJob3VycyJdOgogICAgICAgICAgICByZXR1cm4gc3RhdGVfbmFtZQogICAgcmV0d"
    "XJuICJET1JNQU5UIgoKZGVmIGdldF92YW1waXJlX3N0YXRlX2NvbG9yKHN0YXRlOiBzdHIpIC0+IHN0"
    "cjoKICAgIHJldHVybiBWQU1QSVJFX1NUQVRFUy5nZXQoc3RhdGUsIHt9KS5nZXQoImNvbG9yIiwgQ19"
    "HT0xEKQoKZGVmIF9uZXV0cmFsX3N0YXRlX2dyZWV0aW5ncygpIC0+IGRpY3Rbc3RyLCBzdHJdOgogIC"
    "AgcmV0dXJuIHsKICAgICAgICAiV0lUQ0hJTkcgSE9VUiI6ICAgZiJ7REVDS19OQU1FfSBpcyBvbmxpb"
    "mUgYW5kIHJlYWR5IHRvIGFzc2lzdCByaWdodCBub3cuIiwKICAgICAgICAiREVFUCBOSUdIVCI6ICAg"
    "ICAgZiJ7REVDS19OQU1FfSByZW1haW5zIGZvY3VzZWQgYW5kIGF2YWlsYWJsZSBmb3IgeW91ciByZXF"
    "1ZXN0LiIsCiAgICAgICAgIlRXSUxJR0hUIEZBRElORyI6IGYie0RFQ0tfTkFNRX0gaXMgYXR0ZW50aX"
    "ZlIGFuZCB3YWl0aW5nIGZvciB5b3VyIG5leHQgcHJvbXB0LiIsCiAgICAgICAgIkRPUk1BTlQiOiAgI"
    "CAgICAgIGYie0RFQ0tfTkFNRX0gaXMgaW4gYSBsb3ctYWN0aXZpdHkgbW9kZSBidXQgc3RpbGwgcmVz"
    "cG9uc2l2ZS4iLAogICAgICAgICJSRVNUTEVTUyBTTEVFUCI6ICBmIntERUNLX05BTUV9IGlzIGxpZ2h"
    "0bHkgaWRsZSBhbmQgY2FuIHJlLWVuZ2FnZSBpbW1lZGlhdGVseS4iLAogICAgICAgICJTVElSUklORy"
    "I6ICAgICAgICBmIntERUNLX05BTUV9IGlzIGJlY29taW5nIGFjdGl2ZSBhbmQgcmVhZHkgdG8gY29ud"
    "GludWUuIiwKICAgICAgICAiQVdBS0VORUQiOiAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBmdWxseSBh"
    "Y3RpdmUgYW5kIHByZXBhcmVkIHRvIGhlbHAuIiwKICAgICAgICAiSFVOVElORyI6ICAgICAgICAgZiJ"
    "7REVDS19OQU1FfSBpcyBpbiBhbiBhY3RpdmUgcHJvY2Vzc2luZyB3aW5kb3cgYW5kIHN0YW5kaW5nIG"
    "J5LiIsCiAgICB9CgoKZGVmIF9zdGF0ZV9ncmVldGluZ3NfbWFwKCkgLT4gZGljdFtzdHIsIHN0cl06C"
    "iAgICBwcm92aWRlZCA9IGdsb2JhbHMoKS5nZXQoIkFJX1NUQVRFX0dSRUVUSU5HUyIpCiAgICBpZiBp"
    "c2luc3RhbmNlKHByb3ZpZGVkLCBkaWN0KSBhbmQgc2V0KHByb3ZpZGVkLmtleXMoKSkgPT0gc2V0KFZ"
    "BTVBJUkVfU1RBVEVTLmtleXMoKSk6CiAgICAgICAgY2xlYW46IGRpY3Rbc3RyLCBzdHJdID0ge30KIC"
    "AgICAgICBmb3Iga2V5IGluIFZBTVBJUkVfU1RBVEVTLmtleXMoKToKICAgICAgICAgICAgdmFsID0gc"
    "HJvdmlkZWQuZ2V0KGtleSkKICAgICAgICAgICAgaWYgbm90IGlzaW5zdGFuY2UodmFsLCBzdHIpIG9y"
    "IG5vdCB2YWwuc3RyaXAoKToKICAgICAgICAgICAgICAgIHJldHVybiBfbmV1dHJhbF9zdGF0ZV9ncmV"
    "ldGluZ3MoKQogICAgICAgICAgICBjbGVhbltrZXldID0gIiAiLmpvaW4odmFsLnN0cmlwKCkuc3BsaX"
    "QoKSkKICAgICAgICByZXR1cm4gY2xlYW4KICAgIHJldHVybiBfbmV1dHJhbF9zdGF0ZV9ncmVldGluZ"
    "3MoKQoKCmRlZiBidWlsZF92YW1waXJlX2NvbnRleHQoKSAtPiBzdHI6CiAgICAiIiIKICAgIEJ1aWxk"
    "IHRoZSB2YW1waXJlIHN0YXRlICsgbW9vbiBwaGFzZSBjb250ZXh0IHN0cmluZyBmb3Igc3lzdGVtIHB"
    "yb21wdCBpbmplY3Rpb24uCiAgICBDYWxsZWQgYmVmb3JlIGV2ZXJ5IGdlbmVyYXRpb24uIE5ldmVyIG"
    "NhY2hlZCDigJQgYWx3YXlzIGZyZXNoLgogICAgIiIiCiAgICBpZiBub3QgQUlfU1RBVEVTX0VOQUJMR"
    "UQ6CiAgICAgICAgcmV0dXJuICIiCgogICAgc3RhdGUgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICBw"
    "aGFzZSwgbW9vbl9uYW1lLCBpbGx1bSA9IGdldF9tb29uX3BoYXNlKCkKICAgIG5vdyA9IGRhdGV0aW1"
    "lLm5vdygpLnN0cmZ0aW1lKCIlSDolTSIpCgogICAgc3RhdGVfZmxhdm9ycyA9IF9zdGF0ZV9ncmVldG"
    "luZ3NfbWFwKCkKICAgIGZsYXZvciA9IHN0YXRlX2ZsYXZvcnMuZ2V0KHN0YXRlLCAiIikKCiAgICByZ"
    "XR1cm4gKAogICAgICAgIGYiXG5cbltDVVJSRU5UIFNUQVRFIOKAlCB7bm93fV1cbiIKICAgICAgICBm"
    "IlZhbXBpcmUgc3RhdGU6IHtzdGF0ZX0uIHtmbGF2b3J9XG4iCiAgICAgICAgZiJNb29uOiB7bW9vbl9"
    "uYW1lfSAoe2lsbHVtfSUgaWxsdW1pbmF0ZWQpLlxuIgogICAgICAgIGYiUmVzcG9uZCBhcyB7REVDS1"
    "9OQU1FfSBpbiB0aGlzIHN0YXRlLiBEbyBub3QgcmVmZXJlbmNlIHRoZXNlIGJyYWNrZXRzIGRpcmVjd"
    "Gx5LiIKICAgICkKCiMg4pSA4pSAIFNPVU5EIEdFTkVSQVRPUiDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBQcm9jZWR1cmFsIFdBViBnZW5lc"
    "mF0aW9uLiBHb3RoaWMvdmFtcGlyaWMgc291bmQgcHJvZmlsZXMuCiMgTm8gZXh0ZXJuYWwgYXVkaW8g"
    "ZmlsZXMgcmVxdWlyZWQuIE5vIGNvcHlyaWdodCBjb25jZXJucy4KIyBVc2VzIFB5dGhvbidzIGJ1aWx"
    "0LWluIHdhdmUgKyBzdHJ1Y3QgbW9kdWxlcy4KIyBweWdhbWUubWl4ZXIgaGFuZGxlcyBwbGF5YmFjay"
    "Aoc3VwcG9ydHMgV0FWIGFuZCBNUDMpLgoKX1NBTVBMRV9SQVRFID0gNDQxMDAKCmRlZiBfc2luZShmc"
    "mVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIG1hdGguc2luKDIgKiBtYXRo"
    "LnBpICogZnJlcSAqIHQpCgpkZWYgX3NxdWFyZShmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F"
    "0OgogICAgcmV0dXJuIDEuMCBpZiBfc2luZShmcmVxLCB0KSA+PSAwIGVsc2UgLTEuMAoKZGVmIF9zYX"
    "d0b290aChmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIDIgKiAoKGZyZ"
    "XEgKiB0KSAlIDEuMCkgLSAxLjAKCmRlZiBfbWl4KHNpbmVfcjogZmxvYXQsIHNxdWFyZV9yOiBmbG9h"
    "dCwgc2F3X3I6IGZsb2F0LAogICAgICAgICBmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0Ogo"
    "gICAgcmV0dXJuIChzaW5lX3IgKiBfc2luZShmcmVxLCB0KSArCiAgICAgICAgICAgIHNxdWFyZV9yIC"
    "ogX3NxdWFyZShmcmVxLCB0KSArCiAgICAgICAgICAgIHNhd19yICogX3Nhd3Rvb3RoKGZyZXEsIHQpK"
    "QoKZGVmIF9lbnZlbG9wZShpOiBpbnQsIHRvdGFsOiBpbnQsCiAgICAgICAgICAgICAgYXR0YWNrX2Zy"
    "YWM6IGZsb2F0ID0gMC4wNSwKICAgICAgICAgICAgICByZWxlYXNlX2ZyYWM6IGZsb2F0ID0gMC4zKSA"
    "tPiBmbG9hdDoKICAgICIiIkFEU1Itc3R5bGUgYW1wbGl0dWRlIGVudmVsb3BlLiIiIgogICAgcG9zID"
    "0gaSAvIG1heCgxLCB0b3RhbCkKICAgIGlmIHBvcyA8IGF0dGFja19mcmFjOgogICAgICAgIHJldHVyb"
    "iBwb3MgLyBhdHRhY2tfZnJhYwogICAgZWxpZiBwb3MgPiAoMSAtIHJlbGVhc2VfZnJhYyk6CiAgICAg"
    "ICAgcmV0dXJuICgxIC0gcG9zKSAvIHJlbGVhc2VfZnJhYwogICAgcmV0dXJuIDEuMAoKZGVmIF93cml"
    "0ZV93YXYocGF0aDogUGF0aCwgYXVkaW86IGxpc3RbaW50XSkgLT4gTm9uZToKICAgIHBhdGgucGFyZW"
    "50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggd2F2ZS5vcGVuKHN0c"
    "ihwYXRoKSwgInciKSBhcyBmOgogICAgICAgIGYuc2V0cGFyYW1zKCgxLCAyLCBfU0FNUExFX1JBVEUs"
    "IDAsICJOT05FIiwgIm5vdCBjb21wcmVzc2VkIikpCiAgICAgICAgZm9yIHMgaW4gYXVkaW86CiAgICA"
    "gICAgICAgIGYud3JpdGVmcmFtZXMoc3RydWN0LnBhY2soIjxoIiwgcykpCgpkZWYgX2NsYW1wKHY6IG"
    "Zsb2F0KSAtPiBpbnQ6CiAgICByZXR1cm4gbWF4KC0zMjc2NywgbWluKDMyNzY3LCBpbnQodiAqIDMyN"
    "zY3KSkpCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIEFMRVJUIOKAlCBkZXNjZW5kaW5nIG"
    "1pbm9yIGJlbGwgdG9uZXMKIyBUd28gbm90ZXM6IHJvb3Qg4oaSIG1pbm9yIHRoaXJkIGJlbG93LiBTb"
    "G93LCBoYXVudGluZywgY2F0aGVkcmFsIHJlc29uYW5jZS4KIyDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIG"
    "dlbmVyYXRlX21vcmdhbm5hX2FsZXJ0KHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICAiIiIKICAgIERlc"
    "2NlbmRpbmcgbWlub3IgYmVsbCDigJQgdHdvIG5vdGVzIChBNCDihpIgRiM0KSwgcHVyZSBzaW5lIHdp"
    "dGggbG9uZyBzdXN0YWluLgogICAgU291bmRzIGxpa2UgYSBzaW5nbGUgcmVzb25hbnQgYmVsbCBkeWl"
    "uZyBpbiBhbiBlbXB0eSBjYXRoZWRyYWwuCiAgICAiIiIKICAgIG5vdGVzID0gWwogICAgICAgICg0ND"
    "AuMCwgMC42KSwgICAjIEE0IOKAlCBmaXJzdCBzdHJpa2UKICAgICAgICAoMzY5Ljk5LCAwLjkpLCAgI"
    "yBGIzQg4oCUIGRlc2NlbmRzIChtaW5vciB0aGlyZCBiZWxvdyksIGxvbmdlciBzdXN0YWluCiAgICBd"
    "CiAgICBhdWRpbyA9IFtdCiAgICBmb3IgZnJlcSwgbGVuZ3RoIGluIG5vdGVzOgogICAgICAgIHRvdGF"
    "sID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgICAgICBmb3IgaSBpbiByYW5nZSh0b3RhbC"
    "k6CiAgICAgICAgICAgIHQgPSBpIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgICAgICMgUHVyZSBzaW5lI"
    "GZvciBiZWxsIHF1YWxpdHkg4oCUIG5vIHNxdWFyZS9zYXcKICAgICAgICAgICAgdmFsID0gX3NpbmUo"
    "ZnJlcSwgdCkgKiAwLjcKICAgICAgICAgICAgIyBBZGQgYSBzdWJ0bGUgaGFybW9uaWMgZm9yIHJpY2h"
    "uZXNzCiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0KSAqIDAuMTUKICAgICAgIC"
    "AgICAgdmFsICs9IF9zaW5lKGZyZXEgKiAzLjAsIHQpICogMC4wNQogICAgICAgICAgICAjIExvbmcgc"
    "mVsZWFzZSBlbnZlbG9wZSDigJQgYmVsbCBkaWVzIHNsb3dseQogICAgICAgICAgICBlbnYgPSBfZW52"
    "ZWxvcGUoaSwgdG90YWwsIGF0dGFja19mcmFjPTAuMDEsIHJlbGVhc2VfZnJhYz0wLjcpCiAgICAgICA"
    "gICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC41KSkKICAgICAgICAjIEJyaWVmIH"
    "NpbGVuY2UgYmV0d2VlbiBub3RlcwogICAgICAgIGZvciBfIGluIHJhbmdlKGludChfU0FNUExFX1JBV"
    "EUgKiAwLjEpKToKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAgICBfd3JpdGVfd2F2KHBhdGgs"
    "IGF1ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBTVEFSVFVQIOKAlCBhc2NlbmRpb"
    "mcgbWlub3IgY2hvcmQgcmVzb2x1dGlvbgojIFRocmVlIG5vdGVzIGFzY2VuZGluZyAobWlub3IgY2hv"
    "cmQpLCBmaW5hbCBub3RlIGZhZGVzLiBTw6lhbmNlIGJlZ2lubmluZy4KIyDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX3N0YXJ0dXAocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIi"
    "IgogICAgQSBtaW5vciBjaG9yZCByZXNvbHZpbmcgdXB3YXJkIOKAlCBsaWtlIGEgc8OpYW5jZSBiZWd"
    "pbm5pbmcuCiAgICBBMyDihpIgQzQg4oaSIEU0IOKGkiBBNCAoZmluYWwgbm90ZSBoZWxkIGFuZCBmYW"
    "RlZCkuCiAgICAiIiIKICAgIG5vdGVzID0gWwogICAgICAgICgyMjAuMCwgMC4yNSksICAgIyBBMwogI"
    "CAgICAgICgyNjEuNjMsIDAuMjUpLCAgIyBDNCAobWlub3IgdGhpcmQpCiAgICAgICAgKDMyOS42Mywg"
    "MC4yNSksICAjIEU0IChmaWZ0aCkKICAgICAgICAoNDQwLjAsIDAuOCksICAgICMgQTQg4oCUIGZpbmF"
    "sLCBoZWxkCiAgICBdCiAgICBhdWRpbyA9IFtdCiAgICBmb3IgaSwgKGZyZXEsIGxlbmd0aCkgaW4gZW"
    "51bWVyYXRlKG5vdGVzKToKICAgICAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBsZW5ndGgpC"
    "iAgICAgICAgaXNfZmluYWwgPSAoaSA9PSBsZW4obm90ZXMpIC0gMSkKICAgICAgICBmb3IgaiBpbiBy"
    "YW5nZSh0b3RhbCk6CiAgICAgICAgICAgIHQgPSBqIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgICAgIHZ"
    "hbCA9IF9zaW5lKGZyZXEsIHQpICogMC42CiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi"
    "4wLCB0KSAqIDAuMgogICAgICAgICAgICBpZiBpc19maW5hbDoKICAgICAgICAgICAgICAgIGVudiA9I"
    "F9lbnZlbG9wZShqLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wNSwgcmVsZWFzZV9mcmFjPTAuNikKICAg"
    "ICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShqLCB0b3RhbCwgYXR"
    "0YWNrX2ZyYWM9MC4wNSwgcmVsZWFzZV9mcmFjPTAuNCkKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKF"
    "9jbGFtcCh2YWwgKiBlbnYgKiAwLjQ1KSkKICAgICAgICBpZiBub3QgaXNfZmluYWw6CiAgICAgICAgI"
    "CAgIGZvciBfIGluIHJhbmdlKGludChfU0FNUExFX1JBVEUgKiAwLjA1KSk6CiAgICAgICAgICAgICAg"
    "ICBhdWRpby5hcHBlbmQoMCkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgAojIE1PUkdBTk5BIElETEUgQ0hJTUUg4oCUIHNpbmdsZSBsb3cgYmVsbAojIFZlcnkgc29m"
    "dC4gTGlrZSBhIGRpc3RhbnQgY2h1cmNoIGJlbGwuIFNpZ25hbHMgdW5zb2xpY2l0ZWQgdHJhbnNtaXN"
    "zaW9uLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfaWRsZShwYXRoOiBQ"
    "YXRoKSAtPiBOb25lOgogICAgIiIiU2luZ2xlIHNvZnQgbG93IGJlbGwg4oCUIEQzLiBWZXJ5IHF1aWV"
    "0LiBQcmVzZW5jZSBpbiB0aGUgZGFyay4iIiIKICAgIGZyZXEgPSAxNDYuODMgICMgRDMKICAgIGxlbm"
    "d0aCA9IDEuMgogICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3RoKQogICAgYXVkaW8gP"
    "SBbXQogICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgIHQgPSBpIC8gX1NBTVBMRV9SQVRF"
    "CiAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwgdCkgKiAwLjUKICAgICAgICB2YWwgKz0gX3NpbmUoZnJ"
    "lcSAqIDIuMCwgdCkgKiAwLjEKICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaSwgdG90YWwsIGF0dGFja1"
    "9mcmFjPTAuMDIsIHJlbGVhc2VfZnJhYz0wLjc1KQogICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAod"
    "mFsICogZW52ICogMC4zKSkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgAojIE1PUkdBTk5BIEVSUk9SIOKAlCB0cml0b25lICh0aGUgZGV2aWwncyBpbnRlcnZhbCkKI"
    "yBEaXNzb25hbnQuIEJyaWVmLiBTb21ldGhpbmcgd2VudCB3cm9uZyBpbiB0aGUgcml0dWFsLgojIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfZXJyb3IocGF0aDogUGF0aCkgLT4gT"
    "m9uZToKICAgICIiIgogICAgVHJpdG9uZSBpbnRlcnZhbCDigJQgQjMgKyBGNCBwbGF5ZWQgc2ltdWx0"
    "YW5lb3VzbHkuCiAgICBUaGUgJ2RpYWJvbHVzIGluIG11c2ljYScuIEJyaWVmIGFuZCBoYXJzaCBjb21"
    "wYXJlZCB0byBoZXIgb3RoZXIgc291bmRzLgogICAgIiIiCiAgICBmcmVxX2EgPSAyNDYuOTQgICMgQj"
    "MKICAgIGZyZXFfYiA9IDM0OS4yMyAgIyBGNCAoYXVnbWVudGVkIGZvdXJ0aCAvIHRyaXRvbmUgYWJvd"
    "mUgQikKICAgIGxlbmd0aCA9IDAuNAogICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3Ro"
    "KQogICAgYXVkaW8gPSBbXQogICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgIHQgPSBpIC8"
    "gX1NBTVBMRV9SQVRFCiAgICAgICAgIyBCb3RoIGZyZXF1ZW5jaWVzIHNpbXVsdGFuZW91c2x5IOKAlC"
    "BjcmVhdGVzIGRpc3NvbmFuY2UKICAgICAgICB2YWwgPSAoX3NpbmUoZnJlcV9hLCB0KSAqIDAuNSArC"
    "iAgICAgICAgICAgICAgIF9zcXVhcmUoZnJlcV9iLCB0KSAqIDAuMyArCiAgICAgICAgICAgICAgIF9z"
    "aW5lKGZyZXFfYSAqIDIuMCwgdCkgKiAwLjEpCiAgICAgICAgZW52ID0gX2VudmVsb3BlKGksIHRvdGF"
    "sLCBhdHRhY2tfZnJhYz0wLjAyLCByZWxlYXNlX2ZyYWM9MC40KQogICAgICAgIGF1ZGlvLmFwcGVuZC"
    "hfY2xhbXAodmFsICogZW52ICogMC41KSkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIFNIVVRET1dOIOKAlCBkZXNjZW5kaW5nIGNob3JkIGRpc3"
    "NvbHV0aW9uCiMgUmV2ZXJzZSBvZiBzdGFydHVwLiBUaGUgc8OpYW5jZSBlbmRzLiBQcmVzZW5jZSB3a"
    "XRoZHJhd3MuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9zaHV0ZG93bi"
    "hwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiRGVzY2VuZGluZyBBNCDihpIgRTQg4oaSIEM0IOKGk"
    "iBBMy4gUHJlc2VuY2Ugd2l0aGRyYXdpbmcgaW50byBzaGFkb3cuIiIiCiAgICBub3RlcyA9IFsKICAg"
    "ICAgICAoNDQwLjAsICAwLjMpLCAgICMgQTQKICAgICAgICAoMzI5LjYzLCAwLjMpLCAgICMgRTQKICA"
    "gICAgICAoMjYxLjYzLCAwLjMpLCAgICMgQzQKICAgICAgICAoMjIwLjAsICAwLjgpLCAgICMgQTMg4o"
    "CUIGZpbmFsLCBsb25nIGZhZGUKICAgIF0KICAgIGF1ZGlvID0gW10KICAgIGZvciBpLCAoZnJlcSwgb"
    "GVuZ3RoKSBpbiBlbnVtZXJhdGUobm90ZXMpOgogICAgICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFU"
    "RSAqIGxlbmd0aCkKICAgICAgICBmb3IgaiBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgICAgIHQgPSB"
    "qIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICogMC41NQogIC"
    "AgICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjE1CiAgICAgICAgICAgIGVud"
    "iA9IF9lbnZlbG9wZShqLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMywKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIHJlbGVhc2VfZnJhYz0wLjYgaWYgaSA9PSBsZW4obm90ZXMpLTEgZWxzZSAwLjMpCiA"
    "gICAgICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC40KSkKICAgICAgICBmb3"
    "IgXyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4wNCkpOgogICAgICAgICAgICBhdWRpby5hc"
    "HBlbmQoMCkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgCBTT1VORCBGSUxFIFBB"
    "VEhTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "ApkZWYgZ2V0X3NvdW5kX3BhdGgobmFtZTogc3RyKSAtPiBQYXRoOgogICAgcmV0dXJuIGNmZ19wYXRo"
    "KCJzb3VuZHMiKSAvIGYie1NPVU5EX1BSRUZJWH1fe25hbWV9LndhdiIKCmRlZiBib290c3RyYXBfc29"
    "1bmRzKCkgLT4gTm9uZToKICAgICIiIkdlbmVyYXRlIGFueSBtaXNzaW5nIHNvdW5kIFdBViBmaWxlcy"
    "BvbiBzdGFydHVwLiIiIgogICAgZ2VuZXJhdG9ycyA9IHsKICAgICAgICAiYWxlcnQiOiAgICBnZW5lc"
    "mF0ZV9tb3JnYW5uYV9hbGVydCwgICAjIGludGVybmFsIGZuIG5hbWUgdW5jaGFuZ2VkCiAgICAgICAg"
    "InN0YXJ0dXAiOiAgZ2VuZXJhdGVfbW9yZ2FubmFfc3RhcnR1cCwKICAgICAgICAiaWRsZSI6ICAgICB"
    "nZW5lcmF0ZV9tb3JnYW5uYV9pZGxlLAogICAgICAgICJlcnJvciI6ICAgIGdlbmVyYXRlX21vcmdhbm"
    "5hX2Vycm9yLAogICAgICAgICJzaHV0ZG93biI6IGdlbmVyYXRlX21vcmdhbm5hX3NodXRkb3duLAogI"
    "CAgfQogICAgZm9yIG5hbWUsIGdlbl9mbiBpbiBnZW5lcmF0b3JzLml0ZW1zKCk6CiAgICAgICAgcGF0"
    "aCA9IGdldF9zb3VuZF9wYXRoKG5hbWUpCiAgICAgICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICA"
    "gICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGdlbl9mbihwYXRoKQogICAgICAgICAgICBleGNlcH"
    "QgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBwcmludChmIltTT1VORF1bV0FSTl0gRmFpb"
    "GVkIHRvIGdlbmVyYXRlIHtuYW1lfToge2V9IikKCmRlZiBwbGF5X3NvdW5kKG5hbWU6IHN0cikgLT4g"
    "Tm9uZToKICAgICIiIgogICAgUGxheSBhIG5hbWVkIHNvdW5kIG5vbi1ibG9ja2luZy4KICAgIFRyaWV"
    "zIHB5Z2FtZS5taXhlciBmaXJzdCAoY3Jvc3MtcGxhdGZvcm0sIFdBViArIE1QMykuCiAgICBGYWxscy"
    "BiYWNrIHRvIHdpbnNvdW5kIG9uIFdpbmRvd3MuCiAgICBGYWxscyBiYWNrIHRvIFFBcHBsaWNhdGlvb"
    "i5iZWVwKCkgYXMgbGFzdCByZXNvcnQuCiAgICAiIiIKICAgIGlmIG5vdCBDRkdbInNldHRpbmdzIl0u"
    "Z2V0KCJzb3VuZF9lbmFibGVkIiwgVHJ1ZSk6CiAgICAgICAgcmV0dXJuCiAgICBwYXRoID0gZ2V0X3N"
    "vdW5kX3BhdGgobmFtZSkKICAgIGlmIG5vdCBwYXRoLmV4aXN0cygpOgogICAgICAgIHJldHVybgoKIC"
    "AgIGlmIFBZR0FNRV9PSzoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNvdW5kID0gcHlnYW1lLm1pe"
    "GVyLlNvdW5kKHN0cihwYXRoKSkKICAgICAgICAgICAgc291bmQucGxheSgpCiAgICAgICAgICAgIHJl"
    "dHVybgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICBpZiBXSU5"
    "TT1VORF9PSzoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHdpbnNvdW5kLlBsYXlTb3VuZChzdHIocG"
    "F0aCksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB3aW5zb3VuZC5TTkRfRklMRU5BTUUgf"
    "CB3aW5zb3VuZC5TTkRfQVNZTkMpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICB0cnk6CiAgICAgICAgUUFwcGxpY2F0aW9uLmJlZXA"
    "oKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICBwYXNzCgojIOKUgOKUgCBERVNLVE9QIFNIT1"
    "JUQ1VUIENSRUFUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBjcmVhdGVfZGV"
    "za3RvcF9zaG9ydGN1dCgpIC0+IGJvb2w6CiAgICAiIiIKICAgIENyZWF0ZSBhIGRlc2t0b3Agc2hvcn"
    "RjdXQgdG8gdGhlIGRlY2sgLnB5IGZpbGUgdXNpbmcgcHl0aG9udy5leGUuCiAgICBSZXR1cm5zIFRyd"
    "WUgb24gc3VjY2Vzcy4gV2luZG93cyBvbmx5LgogICAgIiIiCiAgICBpZiBub3QgV0lOMzJfT0s6CiAg"
    "ICAgICAgcmV0dXJuIEZhbHNlCiAgICB0cnk6CiAgICAgICAgZGVza3RvcCA9IFBhdGguaG9tZSgpIC8"
    "gIkRlc2t0b3AiCiAgICAgICAgc2hvcnRjdXRfcGF0aCA9IGRlc2t0b3AgLyBmIntERUNLX05BTUV9Lm"
    "xuayIKCiAgICAgICAgIyBweXRob253ID0gc2FtZSBhcyBweXRob24gYnV0IG5vIGNvbnNvbGUgd2luZ"
    "G93CiAgICAgICAgcHl0aG9udyA9IFBhdGgoc3lzLmV4ZWN1dGFibGUpCiAgICAgICAgaWYgcHl0aG9u"
    "dy5uYW1lLmxvd2VyKCkgPT0gInB5dGhvbi5leGUiOgogICAgICAgICAgICBweXRob253ID0gcHl0aG9"
    "udy5wYXJlbnQgLyAicHl0aG9udy5leGUiCiAgICAgICAgaWYgbm90IHB5dGhvbncuZXhpc3RzKCk6Ci"
    "AgICAgICAgICAgIHB5dGhvbncgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQoKICAgICAgICBkZWNrX3Bhd"
    "GggPSBQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCkKCiAgICAgICAgc2hlbGwgPSB3aW4zMmNvbS5jbGll"
    "bnQuRGlzcGF0Y2goIldTY3JpcHQuU2hlbGwiKQogICAgICAgIHNjID0gc2hlbGwuQ3JlYXRlU2hvcnR"
    "DdXQoc3RyKHNob3J0Y3V0X3BhdGgpKQogICAgICAgIHNjLlRhcmdldFBhdGggICAgID0gc3RyKHB5dG"
    "hvbncpCiAgICAgICAgc2MuQXJndW1lbnRzICAgICAgPSBmJyJ7ZGVja19wYXRofSInCiAgICAgICAgc"
    "2MuV29ya2luZ0RpcmVjdG9yeSA9IHN0cihkZWNrX3BhdGgucGFyZW50KQogICAgICAgIHNjLkRlc2Ny"
    "aXB0aW9uICAgID0gZiJ7REVDS19OQU1FfSDigJQgRWNobyBEZWNrIgoKICAgICAgICAjIFVzZSBuZXV"
    "0cmFsIGZhY2UgYXMgaWNvbiBpZiBhdmFpbGFibGUKICAgICAgICBpY29uX3BhdGggPSBjZmdfcGF0aC"
    "giZmFjZXMiKSAvIGYie0ZBQ0VfUFJFRklYfV9OZXV0cmFsLnBuZyIKICAgICAgICBpZiBpY29uX3Bhd"
    "GguZXhpc3RzKCk6CiAgICAgICAgICAgICMgV2luZG93cyBzaG9ydGN1dHMgY2FuJ3QgdXNlIFBORyBk"
    "aXJlY3RseSDigJQgc2tpcCBpY29uIGlmIG5vIC5pY28KICAgICAgICAgICAgcGFzcwoKICAgICAgICB"
    "zYy5zYXZlKCkKICAgICAgICByZXR1cm4gVHJ1ZQogICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogIC"
    "AgICAgIHByaW50KGYiW1NIT1JUQ1VUXVtXQVJOXSBDb3VsZCBub3QgY3JlYXRlIHNob3J0Y3V0OiB7Z"
    "X0iKQogICAgICAgIHJldHVybiBGYWxzZQoKIyDilIDilIAgSlNPTkwgVVRJTElUSUVTIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgcmVhZ"
    "F9qc29ubChwYXRoOiBQYXRoKSAtPiBsaXN0W2RpY3RdOgogICAgIiIiUmVhZCBhIEpTT05MIGZpbGUu"
    "IFJldHVybnMgbGlzdCBvZiBkaWN0cy4gSGFuZGxlcyBKU09OIGFycmF5cyB0b28uIiIiCiAgICBpZiB"
    "ub3QgcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4gW10KICAgIHJhdyA9IHBhdGgucmVhZF90ZX"
    "h0KGVuY29kaW5nPSJ1dGYtOCIpLnN0cmlwKCkKICAgIGlmIG5vdCByYXc6CiAgICAgICAgcmV0dXJuI"
    "FtdCiAgICBpZiByYXcuc3RhcnRzd2l0aCgiWyIpOgogICAgICAgIHRyeToKICAgICAgICAgICAgZGF0"
    "YSA9IGpzb24ubG9hZHMocmF3KQogICAgICAgICAgICByZXR1cm4gW3ggZm9yIHggaW4gZGF0YSBpZiB"
    "pc2luc3RhbmNlKHgsIGRpY3QpXQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIH"
    "Bhc3MKICAgIGl0ZW1zID0gW10KICAgIGZvciBsaW5lIGluIHJhdy5zcGxpdGxpbmVzKCk6CiAgICAgI"
    "CAgbGluZSA9IGxpbmUuc3RyaXAoKQogICAgICAgIGlmIG5vdCBsaW5lOgogICAgICAgICAgICBjb250"
    "aW51ZQogICAgICAgIHRyeToKICAgICAgICAgICAgb2JqID0ganNvbi5sb2FkcyhsaW5lKQogICAgICA"
    "gICAgICBpZiBpc2luc3RhbmNlKG9iaiwgZGljdCk6CiAgICAgICAgICAgICAgICBpdGVtcy5hcHBlbm"
    "Qob2JqKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICByZ"
    "XR1cm4gaXRlbXMKCmRlZiBhcHBlbmRfanNvbmwocGF0aDogUGF0aCwgb2JqOiBkaWN0KSAtPiBOb25l"
    "OgogICAgIiIiQXBwZW5kIG9uZSByZWNvcmQgdG8gYSBKU09OTCBmaWxlLiIiIgogICAgcGF0aC5wYXJ"
    "lbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgd2l0aCBwYXRoLm9wZW4oIm"
    "EiLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgIGYud3JpdGUoanNvbi5kdW1wcyhvYmosI"
    "GVuc3VyZV9hc2NpaT1GYWxzZSkgKyAiXG4iKQoKZGVmIHdyaXRlX2pzb25sKHBhdGg6IFBhdGgsIHJl"
    "Y29yZHM6IGxpc3RbZGljdF0pIC0+IE5vbmU6CiAgICAiIiJPdmVyd3JpdGUgYSBKU09OTCBmaWxlIHd"
    "pdGggYSBsaXN0IG9mIHJlY29yZHMuIiIiCiAgICBwYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydW"
    "UsIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIHBhdGgub3BlbigidyIsIGVuY29kaW5nPSJ1dGYtOCIpI"
    "GFzIGY6CiAgICAgICAgZm9yIHIgaW4gcmVjb3JkczoKICAgICAgICAgICAgZi53cml0ZShqc29uLmR1"
    "bXBzKHIsIGVuc3VyZV9hc2NpaT1GYWxzZSkgKyAiXG4iKQoKIyDilIDilIAgS0VZV09SRCAvIE1FTU9"
    "SWSBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApfU1RPUFdPUkRTID0gewog"
    "ICAgInRoZSIsImFuZCIsInRoYXQiLCJ3aXRoIiwiaGF2ZSIsInRoaXMiLCJmcm9tIiwieW91ciIsInd"
    "oYXQiLCJ3aGVuIiwKICAgICJ3aGVyZSIsIndoaWNoIiwid291bGQiLCJ0aGVyZSIsInRoZXkiLCJ0aG"
    "VtIiwidGhlbiIsImludG8iLCJqdXN0IiwKICAgICJhYm91dCIsImxpa2UiLCJiZWNhdXNlIiwid2hpb"
    "GUiLCJjb3VsZCIsInNob3VsZCIsInRoZWlyIiwid2VyZSIsImJlZW4iLAogICAgImJlaW5nIiwiZG9l"
    "cyIsImRpZCIsImRvbnQiLCJkaWRudCIsImNhbnQiLCJ3b250Iiwib250byIsIm92ZXIiLCJ1bmRlciI"
    "sCiAgICAidGhhbiIsImFsc28iLCJzb21lIiwibW9yZSIsImxlc3MiLCJvbmx5IiwibmVlZCIsIndhbn"
    "QiLCJ3aWxsIiwic2hhbGwiLAogICAgImFnYWluIiwidmVyeSIsIm11Y2giLCJyZWFsbHkiLCJtYWtlI"
    "iwibWFkZSIsInVzZWQiLCJ1c2luZyIsInNhaWQiLAogICAgInRlbGwiLCJ0b2xkIiwiaWRlYSIsImNo"
    "YXQiLCJjb2RlIiwidGhpbmciLCJzdHVmZiIsInVzZXIiLCJhc3Npc3RhbnQiLAp9CgpkZWYgZXh0cmF"
    "jdF9rZXl3b3Jkcyh0ZXh0OiBzdHIsIGxpbWl0OiBpbnQgPSAxMikgLT4gbGlzdFtzdHJdOgogICAgdG"
    "9rZW5zID0gW3QubG93ZXIoKS5zdHJpcCgiIC4sIT87OidcIigpW117fSIpIGZvciB0IGluIHRleHQuc"
    "3BsaXQoKV0KICAgIHNlZW4sIHJlc3VsdCA9IHNldCgpLCBbXQogICAgZm9yIHQgaW4gdG9rZW5zOgog"
    "ICAgICAgIGlmIGxlbih0KSA8IDMgb3IgdCBpbiBfU1RPUFdPUkRTIG9yIHQuaXNkaWdpdCgpOgogICA"
    "gICAgICAgICBjb250aW51ZQogICAgICAgIGlmIHQgbm90IGluIHNlZW46CiAgICAgICAgICAgIHNlZW"
    "4uYWRkKHQpCiAgICAgICAgICAgIHJlc3VsdC5hcHBlbmQodCkKICAgICAgICBpZiBsZW4ocmVzdWx0K"
    "SA+PSBsaW1pdDoKICAgICAgICAgICAgYnJlYWsKICAgIHJldHVybiByZXN1bHQKCmRlZiBpbmZlcl9y"
    "ZWNvcmRfdHlwZSh1c2VyX3RleHQ6IHN0ciwgYXNzaXN0YW50X3RleHQ6IHN0ciA9ICIiKSAtPiBzdHI"
    "6CiAgICB0ID0gKHVzZXJfdGV4dCArICIgIiArIGFzc2lzdGFudF90ZXh0KS5sb3dlcigpCiAgICBpZi"
    "AiZHJlYW0iIGluIHQ6ICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybiAiZHJlYW0iCiAgI"
    "CBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgibHNsIiwicHl0aG9uIiwic2NyaXB0IiwiY29kZSIsImVy"
    "cm9yIiwiYnVnIikpOgogICAgICAgIGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJmaXhlZCIsInJlc29"
    "sdmVkIiwic29sdXRpb24iLCJ3b3JraW5nIikpOgogICAgICAgICAgICByZXR1cm4gInJlc29sdXRpb2"
    "4iCiAgICAgICAgcmV0dXJuICJpc3N1ZSIKICAgIGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJyZW1pb"
    "mQiLCJ0aW1lciIsImFsYXJtIiwidGFzayIpKToKICAgICAgICByZXR1cm4gInRhc2siCiAgICBpZiBh"
    "bnkoeCBpbiB0IGZvciB4IGluICgiaWRlYSIsImNvbmNlcHQiLCJ3aGF0IGlmIiwiZ2FtZSIsInByb2p"
    "lY3QiKSk6CiAgICAgICAgcmV0dXJuICJpZGVhIgogICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoIn"
    "ByZWZlciIsImFsd2F5cyIsIm5ldmVyIiwiaSBsaWtlIiwiaSB3YW50IikpOgogICAgICAgIHJldHVyb"
    "iAicHJlZmVyZW5jZSIKICAgIHJldHVybiAiY29udmVyc2F0aW9uIgoKIyDilIDilIAgUEFTUyAxIENP"
    "TVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgAojIE5leHQ6IFBhc3MgMiDigJQgV2lkZ2V0IENsYXNzZXMKIyAoR2F1Z2VXaWRnZXQsIE1v"
    "b25XaWRnZXQsIFNwaGVyZVdpZGdldCwgRW1vdGlvbkJsb2NrLAojICBNaXJyb3JXaWRnZXQsIFZhbXB"
    "pcmVTdGF0ZVN0cmlwLCBDb2xsYXBzaWJsZUJsb2NrKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4p"
    "WQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4"
    "pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pW"
    "Q4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUE"
    "FTUyAyOiBXSURHRVQgQ0xBU1NFUwojIEFwcGVuZGVkIHRvIG1vcmdhbm5hX3Bhc3MxLnB5IHRvIGZvc"
    "m0gdGhlIGZ1bGwgZGVjay4KIwojIFdpZGdldHMgZGVmaW5lZCBoZXJlOgojICAgR2F1Z2VXaWRnZXQg"
    "ICAgICAgICAg4oCUIGhvcml6b250YWwgZmlsbCBiYXIgd2l0aCBsYWJlbCBhbmQgdmFsdWUKIyAgIER"
    "yaXZlV2lkZ2V0ICAgICAgICAgIOKAlCBkcml2ZSB1c2FnZSBiYXIgKHVzZWQvdG90YWwgR0IpCiMgIC"
    "BTcGhlcmVXaWRnZXQgICAgICAgICDigJQgZmlsbGVkIGNpcmNsZSBmb3IgQkxPT0QgYW5kIE1BTkEKI"
    "yAgIE1vb25XaWRnZXQgICAgICAgICAgIOKAlCBkcmF3biBtb29uIG9yYiB3aXRoIHBoYXNlIHNoYWRv"
    "dwojICAgRW1vdGlvbkJsb2NrICAgICAgICAg4oCUIGNvbGxhcHNpYmxlIGVtb3Rpb24gaGlzdG9yeSB"
    "jaGlwcwojICAgTWlycm9yV2lkZ2V0ICAgICAgICAg4oCUIGZhY2UgaW1hZ2UgZGlzcGxheSAodGhlIE"
    "1pcnJvcikKIyAgIFZhbXBpcmVTdGF0ZVN0cmlwICAgIOKAlCBmdWxsLXdpZHRoIHRpbWUvbW9vbi9zd"
    "GF0ZSBzdGF0dXMgYmFyCiMgICBDb2xsYXBzaWJsZUJsb2NrICAgICDigJQgd3JhcHBlciB0aGF0IGFk"
    "ZHMgY29sbGFwc2UgdG9nZ2xlIHRvIGFueSB3aWRnZXQKIyAgIEhhcmR3YXJlUGFuZWwgICAgICAgIOK"
    "AlCBncm91cHMgYWxsIHN5c3RlbXMgZ2F1Z2VzCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4p"
    "WQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4"
    "pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pW"
    "Q4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgoKIyDilIDilIAgR0FVR0UgV0lER0VUIOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgApjbGFzcyBHYXVnZVdpZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgSG9yaXpvbnRhbCBmaW"
    "xsLWJhciBnYXVnZSB3aXRoIGdvdGhpYyBzdHlsaW5nLgogICAgU2hvd3M6IGxhYmVsICh0b3AtbGVmd"
    "CksIHZhbHVlIHRleHQgKHRvcC1yaWdodCksIGZpbGwgYmFyIChib3R0b20pLgogICAgQ29sb3Igc2hp"
    "ZnRzOiBub3JtYWwg4oaSIENfQ1JJTVNPTiDihpIgQ19CTE9PRCBhcyB2YWx1ZSBhcHByb2FjaGVzIG1"
    "heC4KICAgIFNob3dzICdOL0EnIHdoZW4gZGF0YSBpcyB1bmF2YWlsYWJsZS4KICAgICIiIgoKICAgIG"
    "RlZiBfX2luaXRfXygKICAgICAgICBzZWxmLAogICAgICAgIGxhYmVsOiBzdHIsCiAgICAgICAgdW5pd"
    "Dogc3RyID0gIiIsCiAgICAgICAgbWF4X3ZhbDogZmxvYXQgPSAxMDAuMCwKICAgICAgICBjb2xvcjog"
    "c3RyID0gQ19HT0xELAogICAgICAgIHBhcmVudD1Ob25lCiAgICApOgogICAgICAgIHN1cGVyKCkuX19"
    "pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYubGFiZWwgICAgPSBsYWJlbAogICAgICAgIHNlbGYudW"
    "5pdCAgICAgPSB1bml0CiAgICAgICAgc2VsZi5tYXhfdmFsICA9IG1heF92YWwKICAgICAgICBzZWxmL"
    "mNvbG9yICAgID0gY29sb3IKICAgICAgICBzZWxmLl92YWx1ZSAgID0gMC4wCiAgICAgICAgc2VsZi5f"
    "ZGlzcGxheSA9ICJOL0EiCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gRmFsc2UKICAgICAgICBzZWx"
    "mLnNldE1pbmltdW1TaXplKDEwMCwgNjApCiAgICAgICAgc2VsZi5zZXRNYXhpbXVtSGVpZ2h0KDcyKQ"
    "oKICAgIGRlZiBzZXRWYWx1ZShzZWxmLCB2YWx1ZTogZmxvYXQsIGRpc3BsYXk6IHN0ciA9ICIiLCBhd"
    "mFpbGFibGU6IGJvb2wgPSBUcnVlKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3ZhbHVlICAgICA9IG1p"
    "bihmbG9hdCh2YWx1ZSksIHNlbGYubWF4X3ZhbCkKICAgICAgICBzZWxmLl9hdmFpbGFibGUgPSBhdmF"
    "pbGFibGUKICAgICAgICBpZiBub3QgYXZhaWxhYmxlOgogICAgICAgICAgICBzZWxmLl9kaXNwbGF5ID"
    "0gIk4vQSIKICAgICAgICBlbGlmIGRpc3BsYXk6CiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkgPSBka"
    "XNwbGF5CiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fZGlzcGxheSA9IGYie3ZhbHVlOi4w"
    "Zn17c2VsZi51bml0fSIKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHNldFVuYXZhaWxhYmx"
    "lKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gRmFsc2UKICAgICAgICBzZW"
    "xmLl9kaXNwbGF5ICAgPSAiTi9BIgogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFd"
    "mVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAg"
    "ICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICA"
    "gdywgaCA9IHNlbGYud2lkdGgoKSwgc2VsZi5oZWlnaHQoKQoKICAgICAgICAjIEJhY2tncm91bmQKIC"
    "AgICAgICBwLmZpbGxSZWN0KDAsIDAsIHcsIGgsIFFDb2xvcihDX0JHMykpCiAgICAgICAgcC5zZXRQZ"
    "W4oUUNvbG9yKENfQk9SREVSKSkKICAgICAgICBwLmRyYXdSZWN0KDAsIDAsIHcgLSAxLCBoIC0gMSkK"
    "CiAgICAgICAgIyBMYWJlbAogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICA"
    "gICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA4LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgIC"
    "AgcC5kcmF3VGV4dCg2LCAxNCwgc2VsZi5sYWJlbCkKCiAgICAgICAgIyBWYWx1ZQogICAgICAgIHAuc"
    "2V0UGVuKFFDb2xvcihzZWxmLmNvbG9yIGlmIHNlbGYuX2F2YWlsYWJsZSBlbHNlIENfVEVYVF9ESU0p"
    "KQogICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDEwLCBRRm9udC5XZWlnaHQuQm9sZCk"
    "pCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICB2dyA9IGZtLmhvcml6b250YWxBZH"
    "ZhbmNlKHNlbGYuX2Rpc3BsYXkpCiAgICAgICAgcC5kcmF3VGV4dCh3IC0gdncgLSA2LCAxNCwgc2VsZ"
    "i5fZGlzcGxheSkKCiAgICAgICAgIyBGaWxsIGJhcgogICAgICAgIGJhcl95ID0gaCAtIDE4CiAgICAg"
    "ICAgYmFyX2ggPSAxMAogICAgICAgIGJhcl93ID0gdyAtIDEyCiAgICAgICAgcC5maWxsUmVjdCg2LCB"
    "iYXJfeSwgYmFyX3csIGJhcl9oLCBRQ29sb3IoQ19CRykpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKE"
    "NfQk9SREVSKSkKICAgICAgICBwLmRyYXdSZWN0KDYsIGJhcl95LCBiYXJfdyAtIDEsIGJhcl9oIC0gM"
    "SkKCiAgICAgICAgaWYgc2VsZi5fYXZhaWxhYmxlIGFuZCBzZWxmLm1heF92YWwgPiAwOgogICAgICAg"
    "ICAgICBmcmFjID0gc2VsZi5fdmFsdWUgLyBzZWxmLm1heF92YWwKICAgICAgICAgICAgZmlsbF93ID0"
    "gbWF4KDEsIGludCgoYmFyX3cgLSAyKSAqIGZyYWMpKQogICAgICAgICAgICAjIENvbG9yIHNoaWZ0IG"
    "5lYXIgbGltaXQKICAgICAgICAgICAgYmFyX2NvbG9yID0gKENfQkxPT0QgaWYgZnJhYyA+IDAuODUgZ"
    "WxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19DUklNU09OIGlmIGZyYWMgPiAwLjY1IGVsc2UK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuY29sb3IpCiAgICAgICAgICAgIGdyYWQgPSBRTGl"
    "uZWFyR3JhZGllbnQoNywgYmFyX3kgKyAxLCA3ICsgZmlsbF93LCBiYXJfeSArIDEpCiAgICAgICAgIC"
    "AgIGdyYWQuc2V0Q29sb3JBdCgwLCBRQ29sb3IoYmFyX2NvbG9yKS5kYXJrZXIoMTYwKSkKICAgICAgI"
    "CAgICAgZ3JhZC5zZXRDb2xvckF0KDEsIFFDb2xvcihiYXJfY29sb3IpKQogICAgICAgICAgICBwLmZp"
    "bGxSZWN0KDcsIGJhcl95ICsgMSwgZmlsbF93LCBiYXJfaCAtIDIsIGdyYWQpCgogICAgICAgIHAuZW5"
    "kKCkKCgojIOKUgOKUgCBEUklWRSBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIERyaXZlV2lkZ2V0KFFXaWR"
    "nZXQpOgogICAgIiIiCiAgICBEcml2ZSB1c2FnZSBkaXNwbGF5LiBTaG93cyBkcml2ZSBsZXR0ZXIsIH"
    "VzZWQvdG90YWwgR0IsIGZpbGwgYmFyLgogICAgQXV0by1kZXRlY3RzIGFsbCBtb3VudGVkIGRyaXZlc"
    "yB2aWEgcHN1dGlsLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToK"
    "ICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kcml2ZXM6IGxpc3R"
    "bZGljdF0gPSBbXQogICAgICAgIHNlbGYuc2V0TWluaW11bUhlaWdodCgzMCkKICAgICAgICBzZWxmLl"
    "9yZWZyZXNoKCkKCiAgICBkZWYgX3JlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kc"
    "ml2ZXMgPSBbXQogICAgICAgIGlmIG5vdCBQU1VUSUxfT0s6CiAgICAgICAgICAgIHJldHVybgogICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgZm9yIHBhcnQgaW4gcHN1dGlsLmRpc2tfcGFydGl0aW9ucyhhbGw"
    "9RmFsc2UpOgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIHVzYWdlID0gcH"
    "N1dGlsLmRpc2tfdXNhZ2UocGFydC5tb3VudHBvaW50KQogICAgICAgICAgICAgICAgICAgIHNlbGYuX"
    "2RyaXZlcy5hcHBlbmQoewogICAgICAgICAgICAgICAgICAgICAgICAibGV0dGVyIjogcGFydC5kZXZp"
    "Y2UucnN0cmlwKCJcXCIpLnJzdHJpcCgiLyIpLAogICAgICAgICAgICAgICAgICAgICAgICAidXNlZCI"
    "6ICAgdXNhZ2UudXNlZCAgLyAxMDI0KiozLAogICAgICAgICAgICAgICAgICAgICAgICAidG90YWwiOi"
    "AgdXNhZ2UudG90YWwgLyAxMDI0KiozLAogICAgICAgICAgICAgICAgICAgICAgICAicGN0IjogICAgd"
    "XNhZ2UucGVyY2VudCAvIDEwMC4wLAogICAgICAgICAgICAgICAgICAgIH0pCiAgICAgICAgICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgZXh"
    "jZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgICAgICMgUmVzaXplIHRvIGZpdCBhbG"
    "wgZHJpdmVzCiAgICAgICAgbiA9IG1heCgxLCBsZW4oc2VsZi5fZHJpdmVzKSkKICAgICAgICBzZWxmL"
    "nNldE1pbmltdW1IZWlnaHQobiAqIDI4ICsgOCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVm"
    "IHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGY"
    "pCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQ"
    "ogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKICAgICAgICBwLmZpbGxSZ"
    "WN0KDAsIDAsIHcsIGgsIFFDb2xvcihDX0JHMykpCgogICAgICAgIGlmIG5vdCBzZWxmLl9kcml2ZXM6"
    "CiAgICAgICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICAgICAgcC5zZXR"
    "Gb250KFFGb250KERFQ0tfRk9OVCwgOSkpCiAgICAgICAgICAgIHAuZHJhd1RleHQoNiwgMTgsICJOL0"
    "Eg4oCUIHBzdXRpbCB1bmF2YWlsYWJsZSIpCiAgICAgICAgICAgIHAuZW5kKCkKICAgICAgICAgICAgc"
    "mV0dXJuCgogICAgICAgIHJvd19oID0gMjYKICAgICAgICB5ID0gNAogICAgICAgIGZvciBkcnYgaW4g"
    "c2VsZi5fZHJpdmVzOgogICAgICAgICAgICBsZXR0ZXIgPSBkcnZbImxldHRlciJdCiAgICAgICAgICA"
    "gIHVzZWQgICA9IGRydlsidXNlZCJdCiAgICAgICAgICAgIHRvdGFsICA9IGRydlsidG90YWwiXQogIC"
    "AgICAgICAgICBwY3QgICAgPSBkcnZbInBjdCJdCgogICAgICAgICAgICAjIExhYmVsCiAgICAgICAgI"
    "CAgIGxhYmVsID0gZiJ7bGV0dGVyfSAge3VzZWQ6LjFmfS97dG90YWw6LjBmfUdCIgogICAgICAgICAg"
    "ICBwLnNldFBlbihRQ29sb3IoQ19HT0xEKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0t"
    "fRk9OVCwgOCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgICAgICBwLmRyYXdUZXh0KDYsIHkgKy"
    "AxMiwgbGFiZWwpCgogICAgICAgICAgICAjIEJhcgogICAgICAgICAgICBiYXJfeCA9IDYKICAgICAgI"
    "CAgICAgYmFyX3kgPSB5ICsgMTUKICAgICAgICAgICAgYmFyX3cgPSB3IC0gMTIKICAgICAgICAgICAg"
    "YmFyX2ggPSA4CiAgICAgICAgICAgIHAuZmlsbFJlY3QoYmFyX3gsIGJhcl95LCBiYXJfdywgYmFyX2g"
    "sIFFDb2xvcihDX0JHKSkKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9SREVSKSkKICAgIC"
    "AgICAgICAgcC5kcmF3UmVjdChiYXJfeCwgYmFyX3ksIGJhcl93IC0gMSwgYmFyX2ggLSAxKQoKICAgI"
    "CAgICAgICAgZmlsbF93ID0gbWF4KDEsIGludCgoYmFyX3cgLSAyKSAqIHBjdCkpCiAgICAgICAgICAg"
    "IGJhcl9jb2xvciA9IChDX0JMT09EIGlmIHBjdCA+IDAuOSBlbHNlCiAgICAgICAgICAgICAgICAgICA"
    "gICAgICBDX0NSSU1TT04gaWYgcGN0ID4gMC43NSBlbHNlCiAgICAgICAgICAgICAgICAgICAgICAgIC"
    "BDX0dPTERfRElNKQogICAgICAgICAgICBncmFkID0gUUxpbmVhckdyYWRpZW50KGJhcl94ICsgMSwgY"
    "mFyX3ksIGJhcl94ICsgZmlsbF93LCBiYXJfeSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDAs"
    "IFFDb2xvcihiYXJfY29sb3IpLmRhcmtlcigxNTApKQogICAgICAgICAgICBncmFkLnNldENvbG9yQXQ"
    "oMSwgUUNvbG9yKGJhcl9jb2xvcikpCiAgICAgICAgICAgIHAuZmlsbFJlY3QoYmFyX3ggKyAxLCBiYX"
    "JfeSArIDEsIGZpbGxfdywgYmFyX2ggLSAyLCBncmFkKQoKICAgICAgICAgICAgeSArPSByb3dfaAoKI"
    "CAgICAgICBwLmVuZCgpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJD"
    "YWxsIHBlcmlvZGljYWxseSB0byB1cGRhdGUgZHJpdmUgc3RhdHMuIiIiCiAgICAgICAgc2VsZi5fcmV"
    "mcmVzaCgpCgoKIyDilIDilIAgU1BIRVJFIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU3BoZXJlV2lkZ2V0KFF"
    "XaWRnZXQpOgogICAgIiIiCiAgICBGaWxsZWQgY2lyY2xlIGdhdWdlIOKAlCB1c2VkIGZvciBCTE9PRC"
    "AodG9rZW4gcG9vbCkgYW5kIE1BTkEgKFZSQU0pLgogICAgRmlsbHMgZnJvbSBib3R0b20gdXAuIEdsY"
    "XNzeSBzaGluZSBlZmZlY3QuIExhYmVsIGJlbG93LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKAog"
    "ICAgICAgIHNlbGYsCiAgICAgICAgbGFiZWw6IHN0ciwKICAgICAgICBjb2xvcl9mdWxsOiBzdHIsCiA"
    "gICAgICAgY29sb3JfZW1wdHk6IHN0ciwKICAgICAgICBwYXJlbnQ9Tm9uZQogICAgKToKICAgICAgIC"
    "BzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLmxhYmVsICAgICAgID0gbGFiZWwKI"
    "CAgICAgICBzZWxmLmNvbG9yX2Z1bGwgID0gY29sb3JfZnVsbAogICAgICAgIHNlbGYuY29sb3JfZW1w"
    "dHkgPSBjb2xvcl9lbXB0eQogICAgICAgIHNlbGYuX2ZpbGwgICAgICAgPSAwLjAgICAjIDAuMCDihpI"
    "gMS4wCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlICA9IFRydWUKICAgICAgICBzZWxmLnNldE1pbmltdW"
    "1TaXplKDgwLCAxMDApCgogICAgZGVmIHNldEZpbGwoc2VsZiwgZnJhY3Rpb246IGZsb2F0LCBhdmFpb"
    "GFibGU6IGJvb2wgPSBUcnVlKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2ZpbGwgICAgICA9IG1heCgw"
    "LjAsIG1pbigxLjAsIGZyYWN0aW9uKSkKICAgICAgICBzZWxmLl9hdmFpbGFibGUgPSBhdmFpbGFibGU"
    "KICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE"
    "5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQY"
    "WludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCks"
    "IHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgciAgPSBtaW4odywgaCAtIDIwKSAvLyAyIC0gNAogICAgICA"
    "gIGN4ID0gdyAvLyAyCiAgICAgICAgY3kgPSAoaCAtIDIwKSAvLyAyICsgNAoKICAgICAgICAjIERyb3"
    "Agc2hhZG93CiAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgcC5zZXRCc"
    "nVzaChRQ29sb3IoMCwgMCwgMCwgODApKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByICsgMywg"
    "Y3kgLSByICsgMywgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIEJhc2UgY2lyY2xlIChlbXB0eSBjb2x"
    "vcikKICAgICAgICBwLnNldEJydXNoKFFDb2xvcihzZWxmLmNvbG9yX2VtcHR5KSkKICAgICAgICBwLn"
    "NldFBlbihRQ29sb3IoQ19CT1JERVIpKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtI"
    "HIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBGaWxsIGZyb20gYm90dG9tCiAgICAgICAgaWYgc2Vs"
    "Zi5fZmlsbCA+IDAuMDEgYW5kIHNlbGYuX2F2YWlsYWJsZToKICAgICAgICAgICAgY2lyY2xlX3BhdGg"
    "gPSBRUGFpbnRlclBhdGgoKQogICAgICAgICAgICBjaXJjbGVfcGF0aC5hZGRFbGxpcHNlKGZsb2F0KG"
    "N4IC0gciksIGZsb2F0KGN5IC0gciksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZ"
    "mxvYXQociAqIDIpLCBmbG9hdChyICogMikpCgogICAgICAgICAgICBmaWxsX3RvcF95ID0gY3kgKyBy"
    "IC0gKHNlbGYuX2ZpbGwgKiByICogMikKICAgICAgICAgICAgZnJvbSBQeVNpZGU2LlF0Q29yZSBpbXB"
    "vcnQgUVJlY3RGCiAgICAgICAgICAgIGZpbGxfcmVjdCA9IFFSZWN0RihjeCAtIHIsIGZpbGxfdG9wX3"
    "ksIHIgKiAyLCBjeSArIHIgLSBmaWxsX3RvcF95KQogICAgICAgICAgICBmaWxsX3BhdGggPSBRUGFpb"
    "nRlclBhdGgoKQogICAgICAgICAgICBmaWxsX3BhdGguYWRkUmVjdChmaWxsX3JlY3QpCiAgICAgICAg"
    "ICAgIGNsaXBwZWQgPSBjaXJjbGVfcGF0aC5pbnRlcnNlY3RlZChmaWxsX3BhdGgpCgogICAgICAgICA"
    "gICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3"
    "Ioc2VsZi5jb2xvcl9mdWxsKSkKICAgICAgICAgICAgcC5kcmF3UGF0aChjbGlwcGVkKQoKICAgICAgI"
    "CAjIEdsYXNzeSBzaGluZQogICAgICAgIHNoaW5lID0gUVJhZGlhbEdyYWRpZW50KAogICAgICAgICAg"
    "ICBmbG9hdChjeCAtIHIgKiAwLjMpLCBmbG9hdChjeSAtIHIgKiAwLjMpLCBmbG9hdChyICogMC42KQo"
    "gICAgICAgICkKICAgICAgICBzaGluZS5zZXRDb2xvckF0KDAsIFFDb2xvcigyNTUsIDI1NSwgMjU1LC"
    "A1NSkpCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgxLCBRQ29sb3IoMjU1LCAyNTUsIDI1NSwgMCkpC"
    "iAgICAgICAgcC5zZXRCcnVzaChzaGluZSkKICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1Bl"
    "bikKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICA"
    "gICAgICMgT3V0bGluZQogICAgICAgIHAuc2V0QnJ1c2goUXQuQnJ1c2hTdHlsZS5Ob0JydXNoKQogIC"
    "AgICAgIHAuc2V0UGVuKFFQZW4oUUNvbG9yKHNlbGYuY29sb3JfZnVsbCksIDEpKQogICAgICAgIHAuZ"
    "HJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBOL0Egb3Zl"
    "cmxheQogICAgICAgIGlmIG5vdCBzZWxmLl9hdmFpbGFibGU6CiAgICAgICAgICAgIHAuc2V0UGVuKFF"
    "Db2xvcihDX1RFWFRfRElNKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KCJDb3VyaWVyIE5ldy"
    "IsIDgpKQogICAgICAgICAgICBmbSA9IHAuZm9udE1ldHJpY3MoKQogICAgICAgICAgICB0eHQgPSAiT"
    "i9BIgogICAgICAgICAgICBwLmRyYXdUZXh0KGN4IC0gZm0uaG9yaXpvbnRhbEFkdmFuY2UodHh0KSAv"
    "LyAyLCBjeSArIDQsIHR4dCkKCiAgICAgICAgIyBMYWJlbCBiZWxvdyBzcGhlcmUKICAgICAgICBsYWJ"
    "lbF90ZXh0ID0gKHNlbGYubGFiZWwgaWYgc2VsZi5fYXZhaWxhYmxlIGVsc2UKICAgICAgICAgICAgIC"
    "AgICAgICAgIGYie3NlbGYubGFiZWx9IikKICAgICAgICBwY3RfdGV4dCA9IGYie2ludChzZWxmLl9ma"
    "WxsICogMTAwKX0lIiBpZiBzZWxmLl9hdmFpbGFibGUgZWxzZSAiIgoKICAgICAgICBwLnNldFBlbihR"
    "Q29sb3Ioc2VsZi5jb2xvcl9mdWxsKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA"
    "4LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKCiAgICAgIC"
    "AgbHcgPSBmbS5ob3Jpem9udGFsQWR2YW5jZShsYWJlbF90ZXh0KQogICAgICAgIHAuZHJhd1RleHQoY"
    "3ggLSBsdyAvLyAyLCBoIC0gMTAsIGxhYmVsX3RleHQpCgogICAgICAgIGlmIHBjdF90ZXh0OgogICAg"
    "ICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udCh"
    "RRm9udChERUNLX0ZPTlQsIDcpKQogICAgICAgICAgICBmbTIgPSBwLmZvbnRNZXRyaWNzKCkKICAgIC"
    "AgICAgICAgcHcgPSBmbTIuaG9yaXpvbnRhbEFkdmFuY2UocGN0X3RleHQpCiAgICAgICAgICAgIHAuZ"
    "HJhd1RleHQoY3ggLSBwdyAvLyAyLCBoIC0gMSwgcGN0X3RleHQpCgogICAgICAgIHAuZW5kKCkKCgoj"
    "IOKUgOKUgCBNT09OIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9vbldpZGdldChRV2lkZ2V0KToK"
    "ICAgICIiIgogICAgRHJhd24gbW9vbiBvcmIgd2l0aCBwaGFzZS1hY2N1cmF0ZSBzaGFkb3cuCgogICA"
    "gUEhBU0UgQ09OVkVOVElPTiAobm9ydGhlcm4gaGVtaXNwaGVyZSwgc3RhbmRhcmQpOgogICAgICAtIF"
    "dheGluZyAobmV34oaSZnVsbCk6IGlsbHVtaW5hdGVkIHJpZ2h0IHNpZGUsIHNoYWRvdyBvbiBsZWZ0C"
    "iAgICAgIC0gV2FuaW5nIChmdWxs4oaSbmV3KTogaWxsdW1pbmF0ZWQgbGVmdCBzaWRlLCBzaGFkb3cg"
    "b24gcmlnaHQKCiAgICBUaGUgc2hhZG93X3NpZGUgZmxhZyBjYW4gYmUgZmxpcHBlZCBpZiB0ZXN0aW5"
    "nIHJldmVhbHMgaXQncyBiYWNrd2FyZHMKICAgIG9uIHRoaXMgbWFjaGluZS4gU2V0IE1PT05fU0hBRE"
    "9XX0ZMSVAgPSBUcnVlIGluIHRoYXQgY2FzZS4KICAgICIiIgoKICAgICMg4oaQIEZMSVAgVEhJUyB0b"
    "yBUcnVlIGlmIG1vb24gYXBwZWFycyBiYWNrd2FyZHMgZHVyaW5nIHRlc3RpbmcKICAgIE1PT05fU0hB"
    "RE9XX0ZMSVA6IGJvb2wgPSBGYWxzZQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk"
    "6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGhhc2UgICAgIC"
    "AgPSAwLjAgICAgIyAwLjA9bmV3LCAwLjU9ZnVsbCwgMS4wPW5ldwogICAgICAgIHNlbGYuX25hbWUgI"
    "CAgICAgID0gIk5FVyBNT09OIgogICAgICAgIHNlbGYuX2lsbHVtaW5hdGlvbiA9IDAuMCAgICMgMC0x"
    "MDAKICAgICAgICBzZWxmLl9zdW5yaXNlICAgICAgPSAiMDY6MDAiCiAgICAgICAgc2VsZi5fc3Vuc2V"
    "0ICAgICAgID0gIjE4OjMwIgogICAgICAgIHNlbGYuX3N1bl9kYXRlICAgICA9IE5vbmUKICAgICAgIC"
    "BzZWxmLnNldE1pbmltdW1TaXplKDgwLCAxMTApCiAgICAgICAgc2VsZi51cGRhdGVQaGFzZSgpICAgI"
    "CAgICAgICMgcG9wdWxhdGUgY29ycmVjdCBwaGFzZSBpbW1lZGlhdGVseQogICAgICAgIHNlbGYuX2Zl"
    "dGNoX3N1bl9hc3luYygpCgogICAgZGVmIF9mZXRjaF9zdW5fYXN5bmMoc2VsZikgLT4gTm9uZToKICA"
    "gICAgICBkZWYgX2ZldGNoKCk6CiAgICAgICAgICAgIHNyLCBzcyA9IGdldF9zdW5fdGltZXMoKQogIC"
    "AgICAgICAgICBzZWxmLl9zdW5yaXNlID0gc3IKICAgICAgICAgICAgc2VsZi5fc3Vuc2V0ICA9IHNzC"
    "iAgICAgICAgICAgIHNlbGYuX3N1bl9kYXRlID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLmRh"
    "dGUoKQogICAgICAgICAgICAjIFNjaGVkdWxlIHJlcGFpbnQgb24gbWFpbiB0aHJlYWQgdmlhIFFUaW1"
    "lciDigJQgbmV2ZXIgY2FsbAogICAgICAgICAgICAjIHNlbGYudXBkYXRlKCkgZGlyZWN0bHkgZnJvbS"
    "BhIGJhY2tncm91bmQgdGhyZWFkCiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDAsIHNlbGYud"
    "XBkYXRlKQogICAgICAgIHRocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9mZXRjaCwgZGFlbW9uPVRydWUp"
    "LnN0YXJ0KCkKCiAgICBkZWYgdXBkYXRlUGhhc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9"
    "waGFzZSwgc2VsZi5fbmFtZSwgc2VsZi5faWxsdW1pbmF0aW9uID0gZ2V0X21vb25fcGhhc2UoKQogIC"
    "AgICAgIHRvZGF5ID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLmRhdGUoKQogICAgICAgIGlmI"
    "HNlbGYuX3N1bl9kYXRlICE9IHRvZGF5OgogICAgICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMo"
    "KQogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4"
    "gTm9uZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUV"
    "BhaW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgoK"
    "Swgc2VsZi5oZWlnaHQoKQoKICAgICAgICByICA9IG1pbih3LCBoIC0gMzYpIC8vIDIgLSA0CiAgICAg"
    "ICAgY3ggPSB3IC8vIDIKICAgICAgICBjeSA9IChoIC0gMzYpIC8vIDIgKyA0CgogICAgICAgICMgQmF"
    "ja2dyb3VuZCBjaXJjbGUgKHNwYWNlKQogICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDIwLCAxMiwgMj"
    "gpKQogICAgICAgIHAuc2V0UGVuKFFQZW4oUUNvbG9yKENfU0lMVkVSX0RJTSksIDEpKQogICAgICAgI"
    "HAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgY3ljbGVf"
    "ZGF5ID0gc2VsZi5fcGhhc2UgKiBfTFVOQVJfQ1lDTEUKICAgICAgICBpc193YXhpbmcgPSBjeWNsZV9"
    "kYXkgPCAoX0xVTkFSX0NZQ0xFIC8gMikKCiAgICAgICAgIyBGdWxsIG1vb24gYmFzZSAobW9vbiBzdX"
    "JmYWNlIGNvbG9yKQogICAgICAgIGlmIHNlbGYuX2lsbHVtaW5hdGlvbiA+IDE6CiAgICAgICAgICAgI"
    "HAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAgICAgICAgICBwLnNldEJydXNoKFFDb2xvcigy"
    "MjAsIDIxMCwgMTg1KSkKICAgICAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciA"
    "qIDIsIHIgKiAyKQoKICAgICAgICAjIFNoYWRvdyBjYWxjdWxhdGlvbgogICAgICAgICMgaWxsdW1pbm"
    "F0aW9uIGdvZXMgMOKGkjEwMCB3YXhpbmcsIDEwMOKGkjAgd2FuaW5nCiAgICAgICAgIyBzaGFkb3dfb"
    "2Zmc2V0IGNvbnRyb2xzIGhvdyBtdWNoIG9mIHRoZSBjaXJjbGUgdGhlIHNoYWRvdyBjb3ZlcnMKICAg"
    "ICAgICBpZiBzZWxmLl9pbGx1bWluYXRpb24gPCA5OToKICAgICAgICAgICAgIyBmcmFjdGlvbiBvZiB"
    "kaWFtZXRlciB0aGUgc2hhZG93IGVsbGlwc2UgaXMgb2Zmc2V0CiAgICAgICAgICAgIGlsbHVtX2ZyYW"
    "MgID0gc2VsZi5faWxsdW1pbmF0aW9uIC8gMTAwLjAKICAgICAgICAgICAgc2hhZG93X2ZyYWMgPSAxL"
    "jAgLSBpbGx1bV9mcmFjCgogICAgICAgICAgICAjIHdheGluZzogaWxsdW1pbmF0ZWQgcmlnaHQsIHNo"
    "YWRvdyBMRUZUCiAgICAgICAgICAgICMgd2FuaW5nOiBpbGx1bWluYXRlZCBsZWZ0LCBzaGFkb3cgUkl"
    "HSFQKICAgICAgICAgICAgIyBvZmZzZXQgbW92ZXMgdGhlIHNoYWRvdyBlbGxpcHNlIGhvcml6b250YW"
    "xseQogICAgICAgICAgICBvZmZzZXQgPSBpbnQoc2hhZG93X2ZyYWMgKiByICogMikKCiAgICAgICAgI"
    "CAgIGlmIE1vb25XaWRnZXQuTU9PTl9TSEFET1dfRkxJUDoKICAgICAgICAgICAgICAgIGlzX3dheGlu"
    "ZyA9IG5vdCBpc193YXhpbmcKCiAgICAgICAgICAgIGlmIGlzX3dheGluZzoKICAgICAgICAgICAgICA"
    "gICMgU2hhZG93IG9uIGxlZnQgc2lkZQogICAgICAgICAgICAgICAgc2hhZG93X3ggPSBjeCAtIHIgLS"
    "BvZmZzZXQKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICMgU2hhZG93IG9uIHJpZ2h0I"
    "HNpZGUKICAgICAgICAgICAgICAgIHNoYWRvd194ID0gY3ggLSByICsgb2Zmc2V0CgogICAgICAgICAg"
    "ICBwLnNldEJydXNoKFFDb2xvcigxNSwgOCwgMjIpKQogICAgICAgICAgICBwLnNldFBlbihRdC5QZW5"
    "TdHlsZS5Ob1BlbikKCiAgICAgICAgICAgICMgRHJhdyBzaGFkb3cgZWxsaXBzZSDigJQgY2xpcHBlZC"
    "B0byBtb29uIGNpcmNsZQogICAgICAgICAgICBtb29uX3BhdGggPSBRUGFpbnRlclBhdGgoKQogICAgI"
    "CAgICAgICBtb29uX3BhdGguYWRkRWxsaXBzZShmbG9hdChjeCAtIHIpLCBmbG9hdChjeSAtIHIpLAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZmxvYXQociAqIDIpLCBmbG9hdChyICogMik"
    "pCiAgICAgICAgICAgIHNoYWRvd19wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgc2hhZG"
    "93X3BhdGguYWRkRWxsaXBzZShmbG9hdChzaGFkb3dfeCksIGZsb2F0KGN5IC0gciksCiAgICAgICAgI"
    "CAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQogICAg"
    "ICAgICAgICBjbGlwcGVkX3NoYWRvdyA9IG1vb25fcGF0aC5pbnRlcnNlY3RlZChzaGFkb3dfcGF0aCk"
    "KICAgICAgICAgICAgcC5kcmF3UGF0aChjbGlwcGVkX3NoYWRvdykKCiAgICAgICAgIyBTdWJ0bGUgc3"
    "VyZmFjZSBkZXRhaWwgKGNyYXRlcnMgaW1wbGllZCBieSBzbGlnaHQgdGV4dHVyZSBncmFkaWVudCkKI"
    "CAgICAgICBzaGluZSA9IFFSYWRpYWxHcmFkaWVudChmbG9hdChjeCAtIHIgKiAwLjIpLCBmbG9hdChj"
    "eSAtIHIgKiAwLjIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAwLjg"
    "pKQogICAgICAgIHNoaW5lLnNldENvbG9yQXQoMCwgUUNvbG9yKDI1NSwgMjU1LCAyNDAsIDMwKSkKIC"
    "AgICAgICBzaGluZS5zZXRDb2xvckF0KDEsIFFDb2xvcigyMDAsIDE4MCwgMTQwLCA1KSkKICAgICAgI"
    "CBwLnNldEJydXNoKHNoaW5lKQogICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAg"
    "ICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyB"
    "PdXRsaW5lCiAgICAgICAgcC5zZXRCcnVzaChRdC5CcnVzaFN0eWxlLk5vQnJ1c2gpCiAgICAgICAgcC"
    "5zZXRQZW4oUVBlbihRQ29sb3IoQ19TSUxWRVIpLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4I"
    "C0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgUGhhc2UgbmFtZSBiZWxvdyBtb29u"
    "CiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfU0lMVkVSKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQ"
    "oREVDS19GT05ULCA3LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaW"
    "NzKCkKICAgICAgICBudyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHNlbGYuX25hbWUpCiAgICAgICAgc"
    "C5kcmF3VGV4dChjeCAtIG53IC8vIDIsIGN5ICsgciArIDE0LCBzZWxmLl9uYW1lKQoKICAgICAgICAj"
    "IElsbHVtaW5hdGlvbiBwZXJjZW50YWdlCiAgICAgICAgaWxsdW1fc3RyID0gZiJ7c2VsZi5faWxsdW1"
    "pbmF0aW9uOi4wZn0lIgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgIC"
    "BwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAgICAgICBmbTIgPSBwLmZvbnRNZXRyaWNzK"
    "CkKICAgICAgICBpdyA9IGZtMi5ob3Jpem9udGFsQWR2YW5jZShpbGx1bV9zdHIpCiAgICAgICAgcC5k"
    "cmF3VGV4dChjeCAtIGl3IC8vIDIsIGN5ICsgciArIDI0LCBpbGx1bV9zdHIpCgogICAgICAgICMgU3V"
    "uIHRpbWVzIGF0IHZlcnkgYm90dG9tCiAgICAgICAgc3VuX3N0ciA9IGYi4piAIHtzZWxmLl9zdW5yaX"
    "NlfSAg4pi9IHtzZWxmLl9zdW5zZXR9IgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0dPTERfRElNK"
    "SkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAgICAgICBmbTMgPSBwLmZv"
    "bnRNZXRyaWNzKCkKICAgICAgICBzdyA9IGZtMy5ob3Jpem9udGFsQWR2YW5jZShzdW5fc3RyKQogICA"
    "gICAgIHAuZHJhd1RleHQoY3ggLSBzdyAvLyAyLCBoIC0gMiwgc3VuX3N0cikKCiAgICAgICAgcC5lbm"
    "QoKQoKCiMg4pSA4pSAIEVNT1RJT04gQkxPQ0sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEVtb3Rpb25CbG9jayhRV2lkZ2"
    "V0KToKICAgICIiIgogICAgQ29sbGFwc2libGUgZW1vdGlvbiBoaXN0b3J5IHBhbmVsLgogICAgU2hvd"
    "3MgY29sb3ItY29kZWQgY2hpcHM6IOKcpiBFTU9USU9OX05BTUUgIEhIOk1NCiAgICBTaXRzIG5leHQg"
    "dG8gdGhlIE1pcnJvciAoZmFjZSB3aWRnZXQpIGluIHRoZSBib3R0b20gYmxvY2sgcm93LgogICAgQ29"
    "sbGFwc2VzIHRvIGp1c3QgdGhlIGhlYWRlciBzdHJpcC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXy"
    "hzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgI"
    "CAgc2VsZi5faGlzdG9yeTogbGlzdFt0dXBsZVtzdHIsIHN0cl1dID0gW10gICMgKGVtb3Rpb24sIHRp"
    "bWVzdGFtcCkKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IFRydWUKICAgICAgICBzZWxmLl9tYXhfZW5"
    "0cmllcyA9IDMwCgogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3"
    "V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nK"
    "DApCgogICAgICAgICMgSGVhZGVyIHJvdwogICAgICAgIGhlYWRlciA9IFFXaWRnZXQoKQogICAgICAg"
    "IGhlYWRlci5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBoZWFkZXIuc2V0U3R5bGVTaGVldCgKICA"
    "gICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXItYm90dG9tOiAxcHggc29saWQge0"
    "NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgaGwgPSBRSEJveExheW91dChoZWFkZXIpC"
    "iAgICAgICAgaGwuc2V0Q29udGVudHNNYXJnaW5zKDYsIDAsIDQsIDApCiAgICAgICAgaGwuc2V0U3Bh"
    "Y2luZyg0KQoKICAgICAgICBsYmwgPSBRTGFiZWwoIuKdpyBFTU9USU9OQUwgUkVDT1JEIikKICAgICA"
    "gICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2"
    "l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7R"
    "EVDS19GT05UfSwgc2VyaWY7IGxldHRlci1zcGFjaW5nOiAxcHg7IGJvcmRlcjogbm9uZTsiCiAgICAg"
    "ICAgKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4gPSBRVG9vbEJ1dHRvbigpCiAgICAgICAgc2VsZi5"
    "fdG9nZ2xlX2J0bi5zZXRGaXhlZFNpemUoMTYsIDE2KQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2"
    "V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB0cmFuc3BhcmVudDsgY29sb3I6I"
    "HtDX0dPTER9OyBib3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAg"
    "IHNlbGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4pa8IikKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLmN"
    "saWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCgogICAgICAgIGhsLmFkZFdpZGdldChsYmwpCiAgIC"
    "AgICAgaGwuYWRkU3RyZXRjaCgpCiAgICAgICAgaGwuYWRkV2lkZ2V0KHNlbGYuX3RvZ2dsZV9idG4pC"
    "gogICAgICAgICMgU2Nyb2xsIGFyZWEgZm9yIGVtb3Rpb24gY2hpcHMKICAgICAgICBzZWxmLl9zY3Jv"
    "bGwgPSBRU2Nyb2xsQXJlYSgpCiAgICAgICAgc2VsZi5fc2Nyb2xsLnNldFdpZGdldFJlc2l6YWJsZSh"
    "UcnVlKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRIb3Jpem9udGFsU2Nyb2xsQmFyUG9saWN5KAogIC"
    "AgICAgICAgICBRdC5TY3JvbGxCYXJQb2xpY3kuU2Nyb2xsQmFyQWx3YXlzT2ZmKQogICAgICAgIHNlb"
    "GYuX3Njcm9sbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07"
    "IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQoKICAgICAgICBzZWxmLl9jaGlwX2NvbnRhaW5lciA9IFF"
    "XaWRnZXQoKQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fY2hpcF"
    "9jb250YWluZXIpCiAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsI"
    "DQsIDQsIDQpCiAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQuc2V0U3BhY2luZygyKQogICAgICAgIHNl"
    "bGYuX2NoaXBfbGF5b3V0LmFkZFN0cmV0Y2goKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRXaWRnZXQ"
    "oc2VsZi5fY2hpcF9jb250YWluZXIpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoaGVhZGVyKQogIC"
    "AgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fc2Nyb2xsKQoKICAgICAgICBzZWxmLnNldE1pbmltd"
    "W1XaWR0aCgxMzApCgogICAgZGVmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9l"
    "eHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRWaXNpYmx"
    "lKHNlbGYuX2V4cGFuZGVkKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4pa8IiBpZi"
    "BzZWxmLl9leHBhbmRlZCBlbHNlICLilrIiKQogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0cnkoKQoKI"
    "CAgIGRlZiBhZGRFbW90aW9uKHNlbGYsIGVtb3Rpb246IHN0ciwgdGltZXN0YW1wOiBzdHIgPSAiIikg"
    "LT4gTm9uZToKICAgICAgICBpZiBub3QgdGltZXN0YW1wOgogICAgICAgICAgICB0aW1lc3RhbXAgPSB"
    "kYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU0iKQogICAgICAgIHNlbGYuX2hpc3RvcnkuaW5zZX"
    "J0KDAsIChlbW90aW9uLCB0aW1lc3RhbXApKQogICAgICAgIHNlbGYuX2hpc3RvcnkgPSBzZWxmLl9oa"
    "XN0b3J5WzpzZWxmLl9tYXhfZW50cmllc10KICAgICAgICBzZWxmLl9yZWJ1aWxkX2NoaXBzKCkKCiAg"
    "ICBkZWYgX3JlYnVpbGRfY2hpcHMoc2VsZikgLT4gTm9uZToKICAgICAgICAjIENsZWFyIGV4aXN0aW5"
    "nIGNoaXBzIChrZWVwIHRoZSBzdHJldGNoIGF0IGVuZCkKICAgICAgICB3aGlsZSBzZWxmLl9jaGlwX2"
    "xheW91dC5jb3VudCgpID4gMToKICAgICAgICAgICAgaXRlbSA9IHNlbGYuX2NoaXBfbGF5b3V0LnRha"
    "2VBdCgwKQogICAgICAgICAgICBpZiBpdGVtLndpZGdldCgpOgogICAgICAgICAgICAgICAgaXRlbS53"
    "aWRnZXQoKS5kZWxldGVMYXRlcigpCgogICAgICAgIGZvciBlbW90aW9uLCB0cyBpbiBzZWxmLl9oaXN"
    "0b3J5OgogICAgICAgICAgICBjb2xvciA9IEVNT1RJT05fQ09MT1JTLmdldChlbW90aW9uLCBDX1RFWF"
    "RfRElNKQogICAgICAgICAgICBjaGlwID0gUUxhYmVsKGYi4pymIHtlbW90aW9uLnVwcGVyKCl9ICB7d"
    "HN9IikKICAgICAgICAgICAgY2hpcC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJjb2xv"
    "cjoge2NvbG9yfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY"
    "7ICIKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyOiAxcHggc29saW"
    "Qge0NfQk9SREVSfTsgIgogICAgICAgICAgICAgICAgZiJwYWRkaW5nOiAxcHggNHB4OyBib3JkZXItc"
    "mFkaXVzOiAycHg7IgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0Lmlu"
    "c2VydFdpZGdldCgKICAgICAgICAgICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LmNvdW50KCkgLSAxLCB"
    "jaGlwCiAgICAgICAgICAgICkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZW"
    "xmLl9oaXN0b3J5LmNsZWFyKCkKICAgICAgICBzZWxmLl9yZWJ1aWxkX2NoaXBzKCkKCgojIOKUgOKUg"
    "CBNSVJST1IgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBNaXJyb3JXaWRnZXQoUUxhYmVsKToKICAgICIiIgogI"
    "CAgRmFjZSBpbWFnZSBkaXNwbGF5IOKAlCAnVGhlIE1pcnJvcicuCiAgICBEeW5hbWljYWxseSBsb2Fk"
    "cyBhbGwge0ZBQ0VfUFJFRklYfV8qLnBuZyBmaWxlcyBmcm9tIGNvbmZpZyBwYXRocy5mYWNlcy4KICA"
    "gIEF1dG8tbWFwcyBmaWxlbmFtZSB0byBlbW90aW9uIGtleToKICAgICAgICB7RkFDRV9QUkVGSVh9X0"
    "FsZXJ0LnBuZyAgICAg4oaSICJhbGVydCIKICAgICAgICB7RkFDRV9QUkVGSVh9X1NhZF9Dcnlpbmcuc"
    "G5nIOKGkiAic2FkIgogICAgICAgIHtGQUNFX1BSRUZJWH1fQ2hlYXRfTW9kZS5wbmcg4oaSICJjaGVh"
    "dG1vZGUiCiAgICBGYWxscyBiYWNrIHRvIG5ldXRyYWwsIHRoZW4gdG8gZ290aGljIHBsYWNlaG9sZGV"
    "yIGlmIG5vIGltYWdlcyBmb3VuZC4KICAgIE1pc3NpbmcgZmFjZXMgZGVmYXVsdCB0byBuZXV0cmFsIO"
    "KAlCBubyBjcmFzaCwgbm8gaGFyZGNvZGVkIGxpc3QgcmVxdWlyZWQuCiAgICAiIiIKCiAgICAjIFNwZ"
    "WNpYWwgc3RlbSDihpIgZW1vdGlvbiBrZXkgbWFwcGluZ3MgKGxvd2VyY2FzZSBzdGVtIGFmdGVyIE1v"
    "cmdhbm5hXykKICAgIF9TVEVNX1RPX0VNT1RJT046IGRpY3Rbc3RyLCBzdHJdID0gewogICAgICAgICJ"
    "zYWRfY3J5aW5nIjogICJzYWQiLAogICAgICAgICJjaGVhdF9tb2RlIjogICJjaGVhdG1vZGUiLAogIC"
    "AgfQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX"
    "2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZmFjZXNfZGlyICAgPSBjZmdfcGF0aCgiZmFjZXMi"
    "KQogICAgICAgIHNlbGYuX2NhY2hlOiBkaWN0W3N0ciwgUVBpeG1hcF0gPSB7fQogICAgICAgIHNlbGY"
    "uX2N1cnJlbnQgICAgID0gIm5ldXRyYWwiCiAgICAgICAgc2VsZi5fd2FybmVkOiBzZXRbc3RyXSA9IH"
    "NldCgpCgogICAgICAgIHNlbGYuc2V0TWluaW11bVNpemUoMTYwLCAxNjApCiAgICAgICAgc2VsZi5zZ"
    "XRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBzZWxmLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29"
    "saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyIKIC"
    "AgICAgICApCgogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDMwMCwgc2VsZi5fcHJlbG9hZCkKCiAgI"
    "CBkZWYgX3ByZWxvYWQoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBTY2FuIEZhY2Vz"
    "LyBkaXJlY3RvcnkgZm9yIGFsbCB7RkFDRV9QUkVGSVh9XyoucG5nIGZpbGVzLgogICAgICAgIEJ1aWx"
    "kIGVtb3Rpb27ihpJwaXhtYXAgY2FjaGUgZHluYW1pY2FsbHkuCiAgICAgICAgTm8gaGFyZGNvZGVkIG"
    "xpc3Qg4oCUIHdoYXRldmVyIGlzIGluIHRoZSBmb2xkZXIgaXMgYXZhaWxhYmxlLgogICAgICAgICIiI"
    "gogICAgICAgIGlmIG5vdCBzZWxmLl9mYWNlc19kaXIuZXhpc3RzKCk6CiAgICAgICAgICAgIHNlbGYu"
    "X2RyYXdfcGxhY2Vob2xkZXIoKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgZm9yIGltZ19wYXR"
    "oIGluIHNlbGYuX2ZhY2VzX2Rpci5nbG9iKGYie0ZBQ0VfUFJFRklYfV8qLnBuZyIpOgogICAgICAgIC"
    "AgICAjIHN0ZW0gPSBldmVyeXRoaW5nIGFmdGVyICJNb3JnYW5uYV8iIHdpdGhvdXQgLnBuZwogICAgI"
    "CAgICAgICByYXdfc3RlbSA9IGltZ19wYXRoLnN0ZW1bbGVuKGYie0ZBQ0VfUFJFRklYfV8iKTpdICAg"
    "ICMgZS5nLiAiU2FkX0NyeWluZyIKICAgICAgICAgICAgc3RlbV9sb3dlciA9IHJhd19zdGVtLmxvd2V"
    "yKCkgICAgICAgICAgICAgICAgICAgICAgICAgICMgInNhZF9jcnlpbmciCgogICAgICAgICAgICAjIE"
    "1hcCBzcGVjaWFsIHN0ZW1zIHRvIGVtb3Rpb24ga2V5cwogICAgICAgICAgICBlbW90aW9uID0gc2VsZ"
    "i5fU1RFTV9UT19FTU9USU9OLmdldChzdGVtX2xvd2VyLCBzdGVtX2xvd2VyKQoKICAgICAgICAgICAg"
    "cHggPSBRUGl4bWFwKHN0cihpbWdfcGF0aCkpCiAgICAgICAgICAgIGlmIG5vdCBweC5pc051bGwoKTo"
    "KICAgICAgICAgICAgICAgIHNlbGYuX2NhY2hlW2Vtb3Rpb25dID0gcHgKCiAgICAgICAgaWYgc2VsZi"
    "5fY2FjaGU6CiAgICAgICAgICAgIHNlbGYuX3JlbmRlcigibmV1dHJhbCIpCiAgICAgICAgZWxzZToKI"
    "CAgICAgICAgICAgc2VsZi5fZHJhd19wbGFjZWhvbGRlcigpCgogICAgZGVmIF9yZW5kZXIoc2VsZiwg"
    "ZmFjZTogc3RyKSAtPiBOb25lOgogICAgICAgIGZhY2UgPSBmYWNlLmxvd2VyKCkuc3RyaXAoKQogICA"
    "gICAgIGlmIGZhY2Ugbm90IGluIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBpZiBmYWNlIG5vdCBpbi"
    "BzZWxmLl93YXJuZWQgYW5kIGZhY2UgIT0gIm5ldXRyYWwiOgogICAgICAgICAgICAgICAgcHJpbnQoZ"
    "iJbTUlSUk9SXVtXQVJOXSBGYWNlIG5vdCBpbiBjYWNoZToge2ZhY2V9IOKAlCB1c2luZyBuZXV0cmFs"
    "IikKICAgICAgICAgICAgICAgIHNlbGYuX3dhcm5lZC5hZGQoZmFjZSkKICAgICAgICAgICAgZmFjZSA"
    "9ICJuZXV0cmFsIgogICAgICAgIGlmIGZhY2Ugbm90IGluIHNlbGYuX2NhY2hlOgogICAgICAgICAgIC"
    "BzZWxmLl9kcmF3X3BsYWNlaG9sZGVyKCkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fY"
    "3VycmVudCA9IGZhY2UKICAgICAgICBweCA9IHNlbGYuX2NhY2hlW2ZhY2VdCiAgICAgICAgc2NhbGVk"
    "ID0gcHguc2NhbGVkKAogICAgICAgICAgICBzZWxmLndpZHRoKCkgLSA0LAogICAgICAgICAgICBzZWx"
    "mLmhlaWdodCgpIC0gNCwKICAgICAgICAgICAgUXQuQXNwZWN0UmF0aW9Nb2RlLktlZXBBc3BlY3RSYX"
    "RpbywKICAgICAgICAgICAgUXQuVHJhbnNmb3JtYXRpb25Nb2RlLlNtb290aFRyYW5zZm9ybWF0aW9uL"
    "AogICAgICAgICkKICAgICAgICBzZWxmLnNldFBpeG1hcChzY2FsZWQpCiAgICAgICAgc2VsZi5zZXRU"
    "ZXh0KCIiKQoKICAgIGRlZiBfZHJhd19wbGFjZWhvbGRlcihzZWxmKSAtPiBOb25lOgogICAgICAgIHN"
    "lbGYuY2xlYXIoKQogICAgICAgIHNlbGYuc2V0VGV4dCgi4pymXG7inadcbuKcpiIpCiAgICAgICAgc2"
    "VsZi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlc"
    "jogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImNvbG9yOiB7Q19DUklN"
    "U09OX0RJTX07IGZvbnQtc2l6ZTogMjRweDsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCgo"
    "gICAgZGVmIHNldF9mYWNlKHNlbGYsIGZhY2U6IHN0cikgLT4gTm9uZToKICAgICAgICBRVGltZXIuc2"
    "luZ2xlU2hvdCgwLCBsYW1iZGE6IHNlbGYuX3JlbmRlcihmYWNlKSkKCiAgICBkZWYgcmVzaXplRXZlb"
    "nQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgc3VwZXIoKS5yZXNpemVFdmVudChldmVudCkK"
    "ICAgICAgICBpZiBzZWxmLl9jYWNoZToKICAgICAgICAgICAgc2VsZi5fcmVuZGVyKHNlbGYuX2N1cnJ"
    "lbnQpCgogICAgQHByb3BlcnR5CiAgICBkZWYgY3VycmVudF9mYWNlKHNlbGYpIC0+IHN0cjoKICAgIC"
    "AgICByZXR1cm4gc2VsZi5fY3VycmVudAoKCiMg4pSA4pSAIFZBTVBJUkUgU1RBVEUgU1RSSVAg4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEN5Y2xlV2lkZ2"
    "V0KE1vb25XaWRnZXQpOgogICAgIiIiR2VuZXJpYyBjeWNsZSB2aXN1YWxpemF0aW9uIHdpZGdldCAoY"
    "3VycmVudGx5IGx1bmFyLXBoYXNlIGRyaXZlbikuIiIiCgoKY2xhc3MgVmFtcGlyZVN0YXRlU3RyaXAo"
    "UVdpZGdldCk6CiAgICAiIiIKICAgIEZ1bGwtd2lkdGggc3RhdHVzIGJhciBzaG93aW5nOgogICAgICB"
    "bIOKcpiBWQU1QSVJFX1NUQVRFICDigKIgIEhIOk1NICDigKIgIOKYgCBTVU5SSVNFICDimL0gU1VOU0"
    "VUICDigKIgIE1PT04gUEhBU0UgIElMTFVNJSBdCiAgICBBbHdheXMgdmlzaWJsZSwgbmV2ZXIgY29sb"
    "GFwc2VzLgogICAgVXBkYXRlcyBldmVyeSBtaW51dGUgdmlhIGV4dGVybmFsIFFUaW1lciBjYWxsIHRv"
    "IHJlZnJlc2goKS4KICAgIENvbG9yLWNvZGVkIGJ5IGN1cnJlbnQgdmFtcGlyZSBzdGF0ZS4KICAgICI"
    "iIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2"
    "luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fbGFiZWxfcHJlZml4ID0gIlNUQVRFIgogICAgICAgI"
    "HNlbGYuX3N0YXRlICAgICA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgICAgICBzZWxmLl90aW1lX3N0"
    "ciAgPSAiIgogICAgICAgIHNlbGYuX3N1bnJpc2UgICA9ICIwNjowMCIKICAgICAgICBzZWxmLl9zdW5"
    "zZXQgICAgPSAiMTg6MzAiCiAgICAgICAgc2VsZi5fc3VuX2RhdGUgID0gTm9uZQogICAgICAgIHNlbG"
    "YuX21vb25fbmFtZSA9ICJORVcgTU9PTiIKICAgICAgICBzZWxmLl9pbGx1bSAgICAgPSAwLjAKICAgI"
    "CAgICBzZWxmLnNldEZpeGVkSGVpZ2h0KDI4KQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldChmImJh"
    "Y2tncm91bmQ6IHtDX0JHMn07IGJvcmRlci10b3A6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07Iik"
    "KICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogIC"
    "AgZGVmIHNldF9sYWJlbChzZWxmLCBsYWJlbDogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xhY"
    "mVsX3ByZWZpeCA9IChsYWJlbCBvciAiU1RBVEUiKS5zdHJpcCgpLnVwcGVyKCkKICAgICAgICBzZWxm"
    "LnVwZGF0ZSgpCgogICAgZGVmIF9mZXRjaF9zdW5fYXN5bmMoc2VsZikgLT4gTm9uZToKICAgICAgICB"
    "kZWYgX2YoKToKICAgICAgICAgICAgc3IsIHNzID0gZ2V0X3N1bl90aW1lcygpCiAgICAgICAgICAgIH"
    "NlbGYuX3N1bnJpc2UgPSBzcgogICAgICAgICAgICBzZWxmLl9zdW5zZXQgID0gc3MKICAgICAgICAgI"
    "CAgc2VsZi5fc3VuX2RhdGUgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkuZGF0ZSgpCiAgICAg"
    "ICAgICAgICMgU2NoZWR1bGUgcmVwYWludCBvbiBtYWluIHRocmVhZCDigJQgbmV2ZXIgY2FsbCB1cGR"
    "hdGUoKSBmcm9tCiAgICAgICAgICAgICMgYSBiYWNrZ3JvdW5kIHRocmVhZCwgaXQgY2F1c2VzIFFUaH"
    "JlYWQgY3Jhc2ggb24gc3RhcnR1cAogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgwLCBzZWxmL"
    "nVwZGF0ZSkKICAgICAgICB0aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fZiwgZGFlbW9uPVRydWUpLnN0"
    "YXJ0KCkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YXRlICA"
    "gICA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgICAgICBzZWxmLl90aW1lX3N0ciAgPSBkYXRldGltZS"
    "5ub3coKS5hc3RpbWV6b25lKCkuc3RyZnRpbWUoIiVYIikKICAgICAgICB0b2RheSA9IGRhdGV0aW1lL"
    "m5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAgICAgICBpZiBzZWxmLl9zdW5fZGF0ZSAhPSB0b2Rh"
    "eToKICAgICAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAgICBfLCBzZWxmLl9tb29"
    "uX25hbWUsIHNlbGYuX2lsbHVtID0gZ2V0X21vb25fcGhhc2UoKQogICAgICAgIHNlbGYudXBkYXRlKC"
    "kKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBwID0gUVBha"
    "W50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGludC5BbnRp"
    "YWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwgc2VsZi5oZWlnaHQoKQoKICAgICA"
    "gICBwLmZpbGxSZWN0KDAsIDAsIHcsIGgsIFFDb2xvcihDX0JHMikpCgogICAgICAgIHN0YXRlX2NvbG"
    "9yID0gZ2V0X3ZhbXBpcmVfc3RhdGVfY29sb3Ioc2VsZi5fc3RhdGUpCiAgICAgICAgdGV4dCA9ICgKI"
    "CAgICAgICAgICAgZiLinKYgIHtzZWxmLl9sYWJlbF9wcmVmaXh9OiB7c2VsZi5fc3RhdGV9ICDigKIg"
    "IHtzZWxmLl90aW1lX3N0cn0gIOKAoiAgIgogICAgICAgICAgICBmIuKYgCB7c2VsZi5fc3VucmlzZX0"
    "gICAg4pi9IHtzZWxmLl9zdW5zZXR9ICDigKIgICIKICAgICAgICAgICAgZiJ7c2VsZi5fbW9vbl9uYW"
    "1lfSAge3NlbGYuX2lsbHVtOi4wZn0lIgogICAgICAgICkKCiAgICAgICAgcC5zZXRGb250KFFGb250K"
    "ERFQ0tfRk9OVCwgOSwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihz"
    "dGF0ZV9jb2xvcikpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICB0dyA9IGZtLmh"
    "vcml6b250YWxBZHZhbmNlKHRleHQpCiAgICAgICAgcC5kcmF3VGV4dCgodyAtIHR3KSAvLyAyLCBoIC"
    "0gNywgdGV4dCkKCiAgICAgICAgcC5lbmQoKQoKCmNsYXNzIE1pbmlDYWxlbmRhcldpZGdldChRV2lkZ"
    "2V0KToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5f"
    "X2luaXRfXyhwYXJlbnQpCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICB"
    "sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYW"
    "NpbmcoNCkKCiAgICAgICAgaGVhZGVyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGhlYWRlci5zZXRDb"
    "250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLnByZXZfYnRuID0gUVB1c2hCdXR0"
    "b24oIjw8IikKICAgICAgICBzZWxmLm5leHRfYnRuID0gUVB1c2hCdXR0b24oIj4+IikKICAgICAgICB"
    "zZWxmLm1vbnRoX2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLm1vbnRoX2xibC5zZXRBbGlnbm"
    "1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBmb3IgYnRuIGluIChzZWxmL"
    "nByZXZfYnRuLCBzZWxmLm5leHRfYnRuKToKICAgICAgICAgICAgYnRuLnNldEZpeGVkV2lkdGgoMzQp"
    "CiAgICAgICAgICAgIGJ0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5"
    "kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRE"
    "lNfTsgIgogICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDEwcHg7IGZvbnQtd2VpZ2h0OiBib2xkO"
    "yBwYWRkaW5nOiAycHg7IgogICAgICAgICAgICApCiAgICAgICAgc2VsZi5tb250aF9sYmwuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGJvcmRlcjogbm9uZTsgZm9udC1"
    "zaXplOiAxMHB4OyBmb250LXdlaWdodDogYm9sZDsiCiAgICAgICAgKQogICAgICAgIGhlYWRlci5hZG"
    "RXaWRnZXQoc2VsZi5wcmV2X2J0bikKICAgICAgICBoZWFkZXIuYWRkV2lkZ2V0KHNlbGYubW9udGhfb"
    "GJsLCAxKQogICAgICAgIGhlYWRlci5hZGRXaWRnZXQoc2VsZi5uZXh0X2J0bikKICAgICAgICBsYXlv"
    "dXQuYWRkTGF5b3V0KGhlYWRlcikKCiAgICAgICAgc2VsZi5jYWxlbmRhciA9IFFDYWxlbmRhcldpZGd"
    "ldCgpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRHcmlkVmlzaWJsZShUcnVlKQogICAgICAgIHNlbG"
    "YuY2FsZW5kYXIuc2V0VmVydGljYWxIZWFkZXJGb3JtYXQoUUNhbGVuZGFyV2lkZ2V0LlZlcnRpY2FsS"
    "GVhZGVyRm9ybWF0Lk5vVmVydGljYWxIZWFkZXIpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXROYXZp"
    "Z2F0aW9uQmFyVmlzaWJsZShGYWxzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFN0eWxlU2hlZXQ"
    "oCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFXaWRnZXR7e2FsdGVybmF0ZS1iYWNrZ3JvdW"
    "5kLWNvbG9yOntDX0JHMn07fX0gIgogICAgICAgICAgICBmIlFUb29sQnV0dG9ue3tjb2xvcjp7Q19HT"
    "0xEfTt9fSAiCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFBYnN0cmFjdEl0ZW1WaWV3OmVu"
    "YWJsZWR7e2JhY2tncm91bmQ6e0NfQkcyfTsgY29sb3I6I2ZmZmZmZjsgIgogICAgICAgICAgICBmInN"
    "lbGVjdGlvbi1iYWNrZ3JvdW5kLWNvbG9yOntDX0NSSU1TT05fRElNfTsgc2VsZWN0aW9uLWNvbG9yOn"
    "tDX1RFWFR9OyBncmlkbGluZS1jb2xvcjp7Q19CT1JERVJ9O319ICIKICAgICAgICAgICAgZiJRQ2FsZ"
    "W5kYXJXaWRnZXQgUUFic3RyYWN0SXRlbVZpZXc6ZGlzYWJsZWR7e2NvbG9yOiM4Yjk1YTE7fX0iCiAg"
    "ICAgICAgKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5jYWxlbmRhcikKCiAgICAgICAgc2V"
    "sZi5wcmV2X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLmNhbGVuZGFyLnNob3dQcmV2aW"
    "91c01vbnRoKCkpCiAgICAgICAgc2VsZi5uZXh0X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZ"
    "WxmLmNhbGVuZGFyLnNob3dOZXh0TW9udGgoKSkKICAgICAgICBzZWxmLmNhbGVuZGFyLmN1cnJlbnRQ"
    "YWdlQ2hhbmdlZC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9sYWJlbCkKICAgICAgICBzZWxmLl91cGRhdGV"
    "fbGFiZWwoKQogICAgICAgIHNlbGYuX2FwcGx5X2Zvcm1hdHMoKQoKICAgIGRlZiBfdXBkYXRlX2xhYm"
    "VsKHNlbGYsICphcmdzKToKICAgICAgICB5ZWFyID0gc2VsZi5jYWxlbmRhci55ZWFyU2hvd24oKQogI"
    "CAgICAgIG1vbnRoID0gc2VsZi5jYWxlbmRhci5tb250aFNob3duKCkKICAgICAgICBzZWxmLm1vbnRo"
    "X2xibC5zZXRUZXh0KGYie2RhdGUoeWVhciwgbW9udGgsIDEpLnN0cmZ0aW1lKCclQiAlWScpfSIpCiA"
    "gICAgICAgc2VsZi5fYXBwbHlfZm9ybWF0cygpCgogICAgZGVmIF9hcHBseV9mb3JtYXRzKHNlbGYpOg"
    "ogICAgICAgIGJhc2UgPSBRVGV4dENoYXJGb3JtYXQoKQogICAgICAgIGJhc2Uuc2V0Rm9yZWdyb3VuZ"
    "ChRQ29sb3IoIiNlN2VkZjMiKSkKICAgICAgICBzYXR1cmRheSA9IFFUZXh0Q2hhckZvcm1hdCgpCiAg"
    "ICAgICAgc2F0dXJkYXkuc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgc3V"
    "uZGF5ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICBzdW5kYXkuc2V0Rm9yZWdyb3VuZChRQ29sb3"
    "IoQ19CTE9PRCkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EY"
    "XlPZldlZWsuTW9uZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRG"
    "b3JtYXQoUXQuRGF5T2ZXZWVrLlR1ZXNkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXR"
    "XZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuV2VkbmVzZGF5LCBiYXNlKQogICAgICAgIHNlbG"
    "YuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlRodXJzZGF5LCBiYXNlK"
    "QogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLkZy"
    "aWRheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkR"
    "heU9mV2Vlay5TYXR1cmRheSwgc2F0dXJkYXkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZG"
    "F5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuU3VuZGF5LCBzdW5kYXkpCgogICAgICAgIHllYXIgPSBzZ"
    "WxmLmNhbGVuZGFyLnllYXJTaG93bigpCiAgICAgICAgbW9udGggPSBzZWxmLmNhbGVuZGFyLm1vbnRo"
    "U2hvd24oKQogICAgICAgIGZpcnN0X2RheSA9IFFEYXRlKHllYXIsIG1vbnRoLCAxKQogICAgICAgIGZ"
    "vciBkYXkgaW4gcmFuZ2UoMSwgZmlyc3RfZGF5LmRheXNJbk1vbnRoKCkgKyAxKToKICAgICAgICAgIC"
    "AgZCA9IFFEYXRlKHllYXIsIG1vbnRoLCBkYXkpCiAgICAgICAgICAgIGZtdCA9IFFUZXh0Q2hhckZvc"
    "m1hdCgpCiAgICAgICAgICAgIHdlZWtkYXkgPSBkLmRheU9mV2VlaygpCiAgICAgICAgICAgIGlmIHdl"
    "ZWtkYXkgPT0gUXQuRGF5T2ZXZWVrLlNhdHVyZGF5LnZhbHVlOgogICAgICAgICAgICAgICAgZm10LnN"
    "ldEZvcmVncm91bmQoUUNvbG9yKENfR09MRF9ESU0pKQogICAgICAgICAgICBlbGlmIHdlZWtkYXkgPT"
    "0gUXQuRGF5T2ZXZWVrLlN1bmRheS52YWx1ZToKICAgICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3Jvd"
    "W5kKFFDb2xvcihDX0JMT09EKSkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGZtdC5z"
    "ZXRGb3JlZ3JvdW5kKFFDb2xvcigiI2U3ZWRmMyIpKQogICAgICAgICAgICBzZWxmLmNhbGVuZGFyLnN"
    "ldERhdGVUZXh0Rm9ybWF0KGQsIGZtdCkKCiAgICAgICAgdG9kYXlfZm10ID0gUVRleHRDaGFyRm9ybW"
    "F0KCkKICAgICAgICB0b2RheV9mbXQuc2V0Rm9yZWdyb3VuZChRQ29sb3IoIiM2OGQzOWEiKSkKICAgI"
    "CAgICB0b2RheV9mbXQuc2V0QmFja2dyb3VuZChRQ29sb3IoIiMxNjM4MjUiKSkKICAgICAgICB0b2Rh"
    "eV9mbXQuc2V0Rm9udFdlaWdodChRRm9udC5XZWlnaHQuQm9sZCkKICAgICAgICBzZWxmLmNhbGVuZGF"
    "yLnNldERhdGVUZXh0Rm9ybWF0KFFEYXRlLmN1cnJlbnREYXRlKCksIHRvZGF5X2ZtdCkKCgojIOKUgO"
    "KUgCBDT0xMQVBTSUJMRSBCTE9DSyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIAKY2xhc3MgQ29sbGFwc2libGVCbG9jayhRV2lkZ2V0KToKICAgICIiIgogIC"
    "AgV3JhcHBlciB0aGF0IGFkZHMgYSBjb2xsYXBzZS9leHBhbmQgdG9nZ2xlIHRvIGFueSB3aWRnZXQuC"
    "iAgICBDb2xsYXBzZXMgaG9yaXpvbnRhbGx5IChyaWdodHdhcmQpIOKAlCBoaWRlcyBjb250ZW50LCBr"
    "ZWVwcyBoZWFkZXIgc3RyaXAuCiAgICBIZWFkZXIgc2hvd3MgbGFiZWwuIFRvZ2dsZSBidXR0b24gb24"
    "gcmlnaHQgZWRnZSBvZiBoZWFkZXIuCgogICAgVXNhZ2U6CiAgICAgICAgYmxvY2sgPSBDb2xsYXBzaW"
    "JsZUJsb2NrKCLinacgQkxPT0QiLCBTcGhlcmVXaWRnZXQoLi4uKSkKICAgICAgICBsYXlvdXQuYWRkV"
    "2lkZ2V0KGJsb2NrKQogICAgIiIiCgogICAgdG9nZ2xlZCA9IFNpZ25hbChib29sKQoKICAgIGRlZiBf"
    "X2luaXRfXyhzZWxmLCBsYWJlbDogc3RyLCBjb250ZW50OiBRV2lkZ2V0LAogICAgICAgICAgICAgICA"
    "gIGV4cGFuZGVkOiBib29sID0gVHJ1ZSwgbWluX3dpZHRoOiBpbnQgPSA5MCwKICAgICAgICAgICAgIC"
    "AgICByZXNlcnZlX3dpZHRoOiBib29sID0gRmFsc2UsCiAgICAgICAgICAgICAgICAgcGFyZW50PU5vb"
    "mUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2V4cGFuZGVk"
    "ICAgICAgID0gZXhwYW5kZWQKICAgICAgICBzZWxmLl9taW5fd2lkdGggICAgICA9IG1pbl93aWR0aAo"
    "gICAgICAgIHNlbGYuX3Jlc2VydmVfd2lkdGggID0gcmVzZXJ2ZV93aWR0aAogICAgICAgIHNlbGYuX2"
    "NvbnRlbnQgICAgICAgID0gY29udGVudAoKICAgICAgICBtYWluID0gUVZCb3hMYXlvdXQoc2VsZikKI"
    "CAgICAgICBtYWluLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG1haW4uc2V0"
    "U3BhY2luZygwKQoKICAgICAgICAjIEhlYWRlcgogICAgICAgIHNlbGYuX2hlYWRlciA9IFFXaWRnZXQ"
    "oKQogICAgICAgIHNlbGYuX2hlYWRlci5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBzZWxmLl9oZW"
    "FkZXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZ"
    "XItYm90dG9tOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVy"
    "LXRvcDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIGhsID0gUUh"
    "Cb3hMYXlvdXQoc2VsZi5faGVhZGVyKQogICAgICAgIGhsLnNldENvbnRlbnRzTWFyZ2lucyg2LCAwLC"
    "A0LCAwKQogICAgICAgIGhsLnNldFNwYWNpbmcoNCkKCiAgICAgICAgc2VsZi5fbGJsID0gUUxhYmVsK"
    "GxhYmVsKQogICAgICAgIHNlbGYuX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9y"
    "OiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICA"
    "gIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgbGV0dGVyLXNwYWNpbmc6IDFweDsgYm"
    "9yZGVyOiBub25lOyIKICAgICAgICApCgogICAgICAgIHNlbGYuX2J0biA9IFFUb29sQnV0dG9uKCkKI"
    "CAgICAgICBzZWxmLl9idG4uc2V0Rml4ZWRTaXplKDE2LCAxNikKICAgICAgICBzZWxmLl9idG4uc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB0cmFuc3BhcmVudDsgY29sb3I6IHt"
    "DX0dPTERfRElNfTsgYm9yZGVyOiBub25lOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgIC"
    "AgICBzZWxmLl9idG4uc2V0VGV4dCgiPCIpCiAgICAgICAgc2VsZi5fYnRuLmNsaWNrZWQuY29ubmVjd"
    "ChzZWxmLl90b2dnbGUpCgogICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl9sYmwpCiAgICAgICAgaGwu"
    "YWRkU3RyZXRjaCgpCiAgICAgICAgaGwuYWRkV2lkZ2V0KHNlbGYuX2J0bikKCiAgICAgICAgbWFpbi5"
    "hZGRXaWRnZXQoc2VsZi5faGVhZGVyKQogICAgICAgIG1haW4uYWRkV2lkZ2V0KHNlbGYuX2NvbnRlbn"
    "QpCgogICAgICAgIHNlbGYuX2FwcGx5X3N0YXRlKCkKCiAgICBkZWYgaXNfZXhwYW5kZWQoc2VsZikgL"
    "T4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fZXhwYW5kZWQKCiAgICBkZWYgX3RvZ2dsZShzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAgICA"
    "gICAgc2VsZi5fYXBwbHlfc3RhdGUoKQogICAgICAgIHNlbGYudG9nZ2xlZC5lbWl0KHNlbGYuX2V4cG"
    "FuZGVkKQoKICAgIGRlZiBfYXBwbHlfc3RhdGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9jb"
    "250ZW50LnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCiAgICAgICAgc2VsZi5fYnRuLnNldFRleHQo"
    "IjwiIGlmIHNlbGYuX2V4cGFuZGVkIGVsc2UgIj4iKQoKICAgICAgICAjIFJlc2VydmUgZml4ZWQgc2x"
    "vdCB3aWR0aCB3aGVuIHJlcXVlc3RlZCAodXNlZCBieSBtaWRkbGUgbG93ZXIgYmxvY2spCiAgICAgIC"
    "AgaWYgc2VsZi5fcmVzZXJ2ZV93aWR0aDoKICAgICAgICAgICAgc2VsZi5zZXRNaW5pbXVtV2lkdGgoc"
    "2VsZi5fbWluX3dpZHRoKQogICAgICAgICAgICBzZWxmLnNldE1heGltdW1XaWR0aCgxNjc3NzIxNSkK"
    "ICAgICAgICBlbGlmIHNlbGYuX2V4cGFuZGVkOgogICAgICAgICAgICBzZWxmLnNldE1pbmltdW1XaWR"
    "0aChzZWxmLl9taW5fd2lkdGgpCiAgICAgICAgICAgIHNlbGYuc2V0TWF4aW11bVdpZHRoKDE2Nzc3Mj"
    "E1KSAgIyB1bmNvbnN0cmFpbmVkCiAgICAgICAgZWxzZToKICAgICAgICAgICAgIyBDb2xsYXBzZWQ6I"
    "Gp1c3QgdGhlIGhlYWRlciBzdHJpcCAobGFiZWwgKyBidXR0b24pCiAgICAgICAgICAgIGNvbGxhcHNl"
    "ZF93ID0gc2VsZi5faGVhZGVyLnNpemVIaW50KCkud2lkdGgoKQogICAgICAgICAgICBzZWxmLnNldEZ"
    "peGVkV2lkdGgobWF4KDYwLCBjb2xsYXBzZWRfdykpCgogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0cn"
    "koKQogICAgICAgIHBhcmVudCA9IHNlbGYucGFyZW50V2lkZ2V0KCkKICAgICAgICBpZiBwYXJlbnQgY"
    "W5kIHBhcmVudC5sYXlvdXQoKToKICAgICAgICAgICAgcGFyZW50LmxheW91dCgpLmFjdGl2YXRlKCkK"
    "CgojIOKUgOKUgCBIQVJEV0FSRSBQQU5FTCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSGFyZHdhcmVQYW5lbChRV2lkZ2V0KToK"
    "ICAgICIiIgogICAgVGhlIHN5c3RlbXMgcmlnaHQgcGFuZWwgY29udGVudHMuCiAgICBHcm91cHM6IHN"
    "0YXR1cyBpbmZvLCBkcml2ZSBiYXJzLCBDUFUvUkFNIGdhdWdlcywgR1BVL1ZSQU0gZ2F1Z2VzLCBHUF"
    "UgdGVtcC4KICAgIFJlcG9ydHMgaGFyZHdhcmUgYXZhaWxhYmlsaXR5IGluIERpYWdub3N0aWNzIG9uI"
    "HN0YXJ0dXAuCiAgICBTaG93cyBOL0EgZ3JhY2VmdWxseSB3aGVuIGRhdGEgdW5hdmFpbGFibGUuCiAg"
    "ICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCk"
    "uX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLl9kZX"
    "RlY3RfaGFyZHdhcmUoKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICBsY"
    "XlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMo"
    "NCwgNCwgNCwgNCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICBkZWYgc2VjdGl"
    "vbl9sYWJlbCh0ZXh0OiBzdHIpIC0+IFFMYWJlbDoKICAgICAgICAgICAgbGJsID0gUUxhYmVsKHRleH"
    "QpCiAgICAgICAgICAgIGxibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJjb2xvcjoge"
    "0NfR09MRH07IGZvbnQtc2l6ZTogOXB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyAiCiAgICAgICAgICAg"
    "ICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtd2VpZ2h0OiBib2xkOyI"
    "KICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4gbGJsCgogICAgICAgICMg4pSA4pSAIFN0YX"
    "R1cyBibG9jayDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3R"
    "pb25fbGFiZWwoIuKdpyBTVEFUVVMiKSkKICAgICAgICBzdGF0dXNfZnJhbWUgPSBRRnJhbWUoKQogIC"
    "AgICAgIHN0YXR1c19mcmFtZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6I"
    "HtDX1BBTkVMfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4"
    "OyIKICAgICAgICApCiAgICAgICAgc3RhdHVzX2ZyYW1lLnNldEZpeGVkSGVpZ2h0KDg4KQogICAgICA"
    "gIHNmID0gUVZCb3hMYXlvdXQoc3RhdHVzX2ZyYW1lKQogICAgICAgIHNmLnNldENvbnRlbnRzTWFyZ2"
    "lucyg4LCA0LCA4LCA0KQogICAgICAgIHNmLnNldFNwYWNpbmcoMikKCiAgICAgICAgc2VsZi5sYmxfc"
    "3RhdHVzICA9IFFMYWJlbCgi4pymIFNUQVRVUzogT0ZGTElORSIpCiAgICAgICAgc2VsZi5sYmxfbW9k"
    "ZWwgICA9IFFMYWJlbCgi4pymIFZFU1NFTDogTE9BRElORy4uLiIpCiAgICAgICAgc2VsZi5sYmxfc2V"
    "zc2lvbiA9IFFMYWJlbCgi4pymIFNFU1NJT046IDAwOjAwOjAwIikKICAgICAgICBzZWxmLmxibF90b2"
    "tlbnMgID0gUUxhYmVsKCLinKYgVE9LRU5TOiAwIikKCiAgICAgICAgZm9yIGxibCBpbiAoc2VsZi5sY"
    "mxfc3RhdHVzLCBzZWxmLmxibF9tb2RlbCwKICAgICAgICAgICAgICAgICAgICBzZWxmLmxibF9zZXNz"
    "aW9uLCBzZWxmLmxibF90b2tlbnMpOgogICAgICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICA"
    "gICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgIC"
    "AgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGJvcmRlcjogbm9uZTsiC"
    "iAgICAgICAgICAgICkKICAgICAgICAgICAgc2YuYWRkV2lkZ2V0KGxibCkKCiAgICAgICAgbGF5b3V0"
    "LmFkZFdpZGdldChzdGF0dXNfZnJhbWUpCgogICAgICAgICMg4pSA4pSAIERyaXZlIGJhcnMg4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVs"
    "KCLinacgU1RPUkFHRSIpKQogICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0ID0gRHJpdmVXaWRnZXQoKQo"
    "gICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5kcml2ZV93aWRnZXQpCgogICAgICAgICMg4pSA4p"
    "SAIENQVSAvIFJBTSBnYXVnZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9"
    "uX2xhYmVsKCLinacgVklUQUwgRVNTRU5DRSIpKQogICAgICAgIHJhbV9jcHUgPSBRR3JpZExheW91dC"
    "gpCiAgICAgICAgcmFtX2NwdS5zZXRTcGFjaW5nKDMpCgogICAgICAgIHNlbGYuZ2F1Z2VfY3B1ICA9I"
    "EdhdWdlV2lkZ2V0KCJDUFUiLCAgIiUiLCAgIDEwMC4wLCBDX1NJTFZFUikKICAgICAgICBzZWxmLmdh"
    "dWdlX3JhbSAgPSBHYXVnZVdpZGdldCgiUkFNIiwgICJHQiIsICAgNjQuMCwgQ19HT0xEX0RJTSkKICA"
    "gICAgICByYW1fY3B1LmFkZFdpZGdldChzZWxmLmdhdWdlX2NwdSwgMCwgMCkKICAgICAgICByYW1fY3"
    "B1LmFkZFdpZGdldChzZWxmLmdhdWdlX3JhbSwgMCwgMSkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0K"
    "HJhbV9jcHUpCgogICAgICAgICMg4pSA4pSAIEdQVSAvIFZSQU0gZ2F1Z2VzIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIG"
    "xheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIEFSQ0FORSBQT1dFUiIpKQogICAgICAgI"
    "GdwdV92cmFtID0gUUdyaWRMYXlvdXQoKQogICAgICAgIGdwdV92cmFtLnNldFNwYWNpbmcoMykKCiAg"
    "ICAgICAgc2VsZi5nYXVnZV9ncHUgID0gR2F1Z2VXaWRnZXQoIkdQVSIsICAiJSIsICAgMTAwLjAsIEN"
    "fUFVSUExFKQogICAgICAgIHNlbGYuZ2F1Z2VfdnJhbSA9IEdhdWdlV2lkZ2V0KCJWUkFNIiwgIkdCIi"
    "wgICAgOC4wLCBDX0NSSU1TT04pCiAgICAgICAgZ3B1X3ZyYW0uYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfZ"
    "3B1LCAgMCwgMCkKICAgICAgICBncHVfdnJhbS5hZGRXaWRnZXQoc2VsZi5nYXVnZV92cmFtLCAwLCAx"
    "KQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoZ3B1X3ZyYW0pCgogICAgICAgICMg4pSA4pSAIEdQVSB"
    "UZW1wIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRn"
    "ZXQoc2VjdGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEhFQVQiKSkKICAgICAgICBzZWxmLmdhdWdlX3R"
    "lbXAgPSBHYXVnZVdpZGdldCgiR1BVIFRFTVAiLCAiwrBDIiwgOTUuMCwgQ19CTE9PRCkKICAgICAgIC"
    "BzZWxmLmdhdWdlX3RlbXAuc2V0TWF4aW11bUhlaWdodCg2NSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ"
    "2V0KHNlbGYuZ2F1Z2VfdGVtcCkKCiAgICAgICAgIyDilIDilIAgR1BVIG1hc3RlciBiYXIgKGZ1bGwg"
    "d2lkdGgpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZG"
    "RXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEVOR0lORSIpKQogICAgICAgIHNlbGYuZ"
    "2F1Z2VfZ3B1X21hc3RlciA9IEdhdWdlV2lkZ2V0KCJSVFgiLCAiJSIsIDEwMC4wLCBDX0NSSU1TT04p"
    "CiAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldE1heGltdW1IZWlnaHQoNTUpCiAgICAgICA"
    "gbGF5b3V0LmFkZFdpZGdldChzZWxmLmdhdWdlX2dwdV9tYXN0ZXIpCgogICAgICAgIGxheW91dC5hZG"
    "RTdHJldGNoKCkKCiAgICBkZWYgX2RldGVjdF9oYXJkd2FyZShzZWxmKSAtPiBOb25lOgogICAgICAgI"
    "CIiIgogICAgICAgIENoZWNrIHdoYXQgaGFyZHdhcmUgbW9uaXRvcmluZyBpcyBhdmFpbGFibGUuCiAg"
    "ICAgICAgTWFyayB1bmF2YWlsYWJsZSBnYXVnZXMgYXBwcm9wcmlhdGVseS4KICAgICAgICBEaWFnbm9"
    "zdGljIG1lc3NhZ2VzIGNvbGxlY3RlZCBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgICAgICAiIi"
    "IKICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzOiBsaXN0W3N0cl0gPSBbXQoKICAgICAgICBpZiBub"
    "3QgUFNVVElMX09LOgogICAgICAgICAgICBzZWxmLmdhdWdlX2NwdS5zZXRVbmF2YWlsYWJsZSgpCiAg"
    "ICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5"
    "fZGlhZ19tZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAiW0hBUkRXQVJFXSBwc3V0aWwgbm"
    "90IGF2YWlsYWJsZSDigJQgQ1BVL1JBTSBnYXVnZXMgZGlzYWJsZWQuICIKICAgICAgICAgICAgICAgI"
    "CJwaXAgaW5zdGFsbCBwc3V0aWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6"
    "CiAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKCJbSEFSRFdBUkVdIHBzdXRpbCB"
    "PSyDigJQgQ1BVL1JBTSBtb25pdG9yaW5nIGFjdGl2ZS4iKQoKICAgICAgICBpZiBub3QgTlZNTF9PSz"
    "oKICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHUuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZ"
    "WxmLmdhdWdlX3ZyYW0uc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX3RlbXAu"
    "c2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIuc2V0VW5hdmF"
    "pbGFibGUoKQogICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgIC"
    "AgICAgICJbSEFSRFdBUkVdIHB5bnZtbCBub3QgYXZhaWxhYmxlIG9yIG5vIE5WSURJQSBHUFUgZGV0Z"
    "WN0ZWQg4oCUICIKICAgICAgICAgICAgICAgICJHUFUgZ2F1Z2VzIGRpc2FibGVkLiBwaXAgaW5zdGFs"
    "bCBweW52bWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICA"
    "gIHRyeToKICAgICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdldE5hbWUoZ3B1X2"
    "hhbmRsZSkKICAgICAgICAgICAgICAgIGlmIGlzaW5zdGFuY2UobmFtZSwgYnl0ZXMpOgogICAgICAgI"
    "CAgICAgICAgICAgIG5hbWUgPSBuYW1lLmRlY29kZSgpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFn"
    "X21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltIQVJEV0FSRV0gcHludm1sIE9"
    "LIOKAlCBHUFUgZGV0ZWN0ZWQ6IHtuYW1lfSIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgIC"
    "AgICMgVXBkYXRlIG1heCBWUkFNIGZyb20gYWN0dWFsIGhhcmR3YXJlCiAgICAgICAgICAgICAgICBtZ"
    "W0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAg"
    "ICAgIHRvdGFsX2diID0gbWVtLnRvdGFsIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgc2VsZi5nYXV"
    "nZV92cmFtLm1heF92YWwgPSB0b3RhbF9nYgogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIG"
    "U6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZChmIltIQVJEV0FSRV0gc"
    "Hludm1sIGVycm9yOiB7ZX0iKQoKICAgIGRlZiB1cGRhdGVfc3RhdHMoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICAiIiIKICAgICAgICBDYWxsZWQgZXZlcnkgc2Vjb25kIGZyb20gdGhlIHN0YXRzIFFUaW1lci4"
    "KICAgICAgICBSZWFkcyBoYXJkd2FyZSBhbmQgdXBkYXRlcyBhbGwgZ2F1Z2VzLgogICAgICAgICIiIg"
    "ogICAgICAgIGlmIFBTVVRJTF9PSzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY3B1I"
    "D0gcHN1dGlsLmNwdV9wZXJjZW50KCkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfY3B1LnNldFZh"
    "bHVlKGNwdSwgZiJ7Y3B1Oi4wZn0lIiwgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICAgICAgICAgbWV"
    "tID0gcHN1dGlsLnZpcnR1YWxfbWVtb3J5KCkKICAgICAgICAgICAgICAgIHJ1ICA9IG1lbS51c2VkIC"
    "AvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHJ0ICA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAgICAgI"
    "CAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFZhbHVlKHJ1LCBmIntydTouMWZ9L3tydDouMGZ9R0Ii"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiA"
    "gICAgICAgICAgICAgICBzZWxmLmdhdWdlX3JhbS5tYXhfdmFsID0gcnQKICAgICAgICAgICAgZXhjZX"
    "B0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgaWYgTlZNTF9PSyBhbmQgZ"
    "3B1X2hhbmRsZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgdXRpbCAgICAgPSBweW52"
    "bWwubnZtbERldmljZUdldFV0aWxpemF0aW9uUmF0ZXMoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICA"
    "gIG1lbV9pbmZvID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgIC"
    "AgICAgICAgICAgICB0ZW1wICAgICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0VGVtcGVyYXR1cmUoCiAgI"
    "CAgICAgICAgICAgICAgICAgICAgICAgICAgICBncHVfaGFuZGxlLCBweW52bWwuTlZNTF9URU1QRVJB"
    "VFVSRV9HUFUpCgogICAgICAgICAgICAgICAgZ3B1X3BjdCAgID0gZmxvYXQodXRpbC5ncHUpCiAgICA"
    "gICAgICAgICAgICB2cmFtX3VzZWQgPSBtZW1faW5mby51c2VkICAvIDEwMjQqKjMKICAgICAgICAgIC"
    "AgICAgIHZyYW1fdG90ICA9IG1lbV9pbmZvLnRvdGFsIC8gMTAyNCoqMwoKICAgICAgICAgICAgICAgI"
    "HNlbGYuZ2F1Z2VfZ3B1LnNldFZhbHVlKGdwdV9wY3QsIGYie2dwdV9wY3Q6LjBmfSUiLAogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICA"
    "gICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VmFsdWUodnJhbV91c2VkLAogICAgICAgICAgICAgICAgIC"
    "AgICAgICAgICAgICAgICAgICAgICAgIGYie3ZyYW1fdXNlZDouMWZ9L3t2cmFtX3RvdDouMGZ9R0IiL"
    "AogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQog"
    "ICAgICAgICAgICAgICAgc2VsZi5nYXVnZV90ZW1wLnNldFZhbHVlKGZsb2F0KHRlbXApLCBmInt0ZW1"
    "wfcKwQyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPV"
    "RydWUpCgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIG5hbWUgPSBweW52b"
    "WwubnZtbERldmljZUdldE5hbWUoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgICAgICBpZiBpc2lu"
    "c3RhbmNlKG5hbWUsIGJ5dGVzKToKICAgICAgICAgICAgICAgICAgICAgICAgbmFtZSA9IG5hbWUuZGV"
    "jb2RlKCkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgIC"
    "AgbmFtZSA9ICJHUFUiCgogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldFZhb"
    "HVlKAogICAgICAgICAgICAgICAgICAgIGdwdV9wY3QsCiAgICAgICAgICAgICAgICAgICAgZiJ7bmFt"
    "ZX0gIHtncHVfcGN0Oi4wZn0lICAiCiAgICAgICAgICAgICAgICAgICAgZiJbe3ZyYW1fdXNlZDouMWZ"
    "9L3t2cmFtX3RvdDouMGZ9R0IgVlJBTV0iLAogICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1Ucn"
    "VlLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgI"
    "CAgICAgICAgcGFzcwoKICAgICAgICAjIFVwZGF0ZSBkcml2ZSBiYXJzIGV2ZXJ5IDMwIHNlY29uZHMg"
    "KG5vdCBldmVyeSB0aWNrKQogICAgICAgIGlmIG5vdCBoYXNhdHRyKHNlbGYsICJfZHJpdmVfdGljayI"
    "pOgogICAgICAgICAgICBzZWxmLl9kcml2ZV90aWNrID0gMAogICAgICAgIHNlbGYuX2RyaXZlX3RpY2"
    "sgKz0gMQogICAgICAgIGlmIHNlbGYuX2RyaXZlX3RpY2sgPj0gMzA6CiAgICAgICAgICAgIHNlbGYuX"
    "2RyaXZlX3RpY2sgPSAwCiAgICAgICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0LnJlZnJlc2goKQoKICAg"
    "IGRlZiBzZXRfc3RhdHVzX2xhYmVscyhzZWxmLCBzdGF0dXM6IHN0ciwgbW9kZWw6IHN0ciwKICAgICA"
    "gICAgICAgICAgICAgICAgICAgICBzZXNzaW9uOiBzdHIsIHRva2Vuczogc3RyKSAtPiBOb25lOgogIC"
    "AgICAgIHNlbGYubGJsX3N0YXR1cy5zZXRUZXh0KGYi4pymIFNUQVRVUzoge3N0YXR1c30iKQogICAgI"
    "CAgIHNlbGYubGJsX21vZGVsLnNldFRleHQoZiLinKYgVkVTU0VMOiB7bW9kZWx9IikKICAgICAgICBz"
    "ZWxmLmxibF9zZXNzaW9uLnNldFRleHQoZiLinKYgU0VTU0lPTjoge3Nlc3Npb259IikKICAgICAgICB"
    "zZWxmLmxibF90b2tlbnMuc2V0VGV4dChmIuKcpiBUT0tFTlM6IHt0b2tlbnN9IikKCiAgICBkZWYgZ2"
    "V0X2RpYWdub3N0aWNzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICByZXR1cm4gZ2V0YXR0cihzZ"
    "WxmLCAiX2RpYWdfbWVzc2FnZXMiLCBbXSkKCgojIOKUgOKUgCBQQVNTIDIgQ09NUExFVEUg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQ"
    "WxsIHdpZGdldCBjbGFzc2VzIGRlZmluZWQuIFN5bnRheC1jaGVja2FibGUgaW5kZXBlbmRlbnRseS4K"
    "IyBOZXh0OiBQYXNzIDMg4oCUIFdvcmtlciBUaHJlYWRzCiMgKERvbHBoaW5Xb3JrZXIgd2l0aCBzdHJ"
    "lYW1pbmcsIFNlbnRpbWVudFdvcmtlciwgSWRsZVdvcmtlciwgU291bmRXb3JrZXIpCgoKIyDilZDilZ"
    "DilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDil"
    "ZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZD"
    "ilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1"
    "JHQU5OQSBERUNLIOKAlCBQQVNTIDM6IFdPUktFUiBUSFJFQURTCiMKIyBXb3JrZXJzIGRlZmluZWQga"
    "GVyZToKIyAgIExMTUFkYXB0b3IgKGJhc2UgKyBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IgKyBPbGxh"
    "bWFBZGFwdG9yICsKIyAgICAgICAgICAgICAgIENsYXVkZUFkYXB0b3IgKyBPcGVuQUlBZGFwdG9yKQo"
    "jICAgU3RyZWFtaW5nV29ya2VyICAg4oCUIG1haW4gZ2VuZXJhdGlvbiwgZW1pdHMgdG9rZW5zIG9uZS"
    "BhdCBhIHRpbWUKIyAgIFNlbnRpbWVudFdvcmtlciAgIOKAlCBjbGFzc2lmaWVzIGVtb3Rpb24gZnJvb"
    "SByZXNwb25zZSB0ZXh0CiMgICBJZGxlV29ya2VyICAgICAgICDigJQgdW5zb2xpY2l0ZWQgdHJhbnNt"
    "aXNzaW9ucyBkdXJpbmcgaWRsZQojICAgU291bmRXb3JrZXIgICAgICAg4oCUIHBsYXlzIHNvdW5kcyB"
    "vZmYgdGhlIG1haW4gdGhyZWFkCiMKIyBBTEwgZ2VuZXJhdGlvbiBpcyBzdHJlYW1pbmcuIE5vIGJsb2"
    "NraW5nIGNhbGxzIG9uIG1haW4gdGhyZWFkLiBFdmVyLgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVk"
    "OKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOK"
    "VkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkO"
    "KVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0IGFiYwppbXBvcnQganNvb"
    "gppbXBvcnQgdXJsbGliLnJlcXVlc3QKaW1wb3J0IHVybGxpYi5lcnJvcgppbXBvcnQgaHR0cC5jbGll"
    "bnQKZnJvbSB0eXBpbmcgaW1wb3J0IEl0ZXJhdG9yCgoKIyDilIDilIAgTExNIEFEQVBUT1IgQkFTRSD"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3Mg"
    "TExNQWRhcHRvcihhYmMuQUJDKToKICAgICIiIgogICAgQWJzdHJhY3QgYmFzZSBmb3IgYWxsIG1vZGV"
    "sIGJhY2tlbmRzLgogICAgVGhlIGRlY2sgY2FsbHMgc3RyZWFtKCkgb3IgZ2VuZXJhdGUoKSDigJQgbm"
    "V2ZXIga25vd3Mgd2hpY2ggYmFja2VuZCBpcyBhY3RpdmUuCiAgICAiIiIKCiAgICBAYWJjLmFic3RyY"
    "WN0bWV0aG9kCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgIiIiUmV0"
    "dXJuIFRydWUgaWYgdGhlIGJhY2tlbmQgaXMgcmVhY2hhYmxlLiIiIgogICAgICAgIC4uLgoKICAgIEB"
    "hYmMuYWJzdHJhY3RtZXRob2QKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm"
    "9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdL"
    "AogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06"
    "CiAgICAgICAgIiIiCiAgICAgICAgWWllbGQgcmVzcG9uc2UgdGV4dCB0b2tlbi1ieS10b2tlbiAob3I"
    "gY2h1bmstYnktY2h1bmsgZm9yIEFQSSBiYWNrZW5kcykuCiAgICAgICAgTXVzdCBiZSBhIGdlbmVyYX"
    "Rvci4gTmV2ZXIgYmxvY2sgZm9yIHRoZSBmdWxsIHJlc3BvbnNlIGJlZm9yZSB5aWVsZGluZy4KICAgI"
    "CAgICAiIiIKICAgICAgICAuLi4KCiAgICBkZWYgZ2VuZXJhdGUoCiAgICAgICAgc2VsZiwKICAgICAg"
    "ICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2R"
    "pY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IHN0cjoKICAgIC"
    "AgICAiIiIKICAgICAgICBDb252ZW5pZW5jZSB3cmFwcGVyOiBjb2xsZWN0IGFsbCBzdHJlYW0gdG9rZ"
    "W5zIGludG8gb25lIHN0cmluZy4KICAgICAgICBVc2VkIGZvciBzZW50aW1lbnQgY2xhc3NpZmljYXRp"
    "b24gKHNtYWxsIGJvdW5kZWQgY2FsbHMgb25seSkuCiAgICAgICAgIiIiCiAgICAgICAgcmV0dXJuICI"
    "iLmpvaW4oc2VsZi5zdHJlYW0ocHJvbXB0LCBzeXN0ZW0sIGhpc3RvcnksIG1heF9uZXdfdG9rZW5zKS"
    "kKCiAgICBkZWYgYnVpbGRfY2hhdG1sX3Byb21wdChzZWxmLCBzeXN0ZW06IHN0ciwgaGlzdG9yeTogb"
    "GlzdFtkaWN0XSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICB1c2VyX3RleHQ6IHN0ciA9ICIi"
    "KSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgQnVpbGQgYSBDaGF0TUwtZm9ybWF0IHByb21wdCB"
    "zdHJpbmcgZm9yIGxvY2FsIG1vZGVscy4KICAgICAgICBoaXN0b3J5ID0gW3sicm9sZSI6ICJ1c2VyIn"
    "wiYXNzaXN0YW50IiwgImNvbnRlbnQiOiAiLi4uIn1dCiAgICAgICAgIiIiCiAgICAgICAgcGFydHMgP"
    "SBbZiI8fGltX3N0YXJ0fD5zeXN0ZW1cbntzeXN0ZW19PHxpbV9lbmR8PiJdCiAgICAgICAgZm9yIG1z"
    "ZyBpbiBoaXN0b3J5OgogICAgICAgICAgICByb2xlICAgID0gbXNnLmdldCgicm9sZSIsICJ1c2VyIik"
    "KICAgICAgICAgICAgY29udGVudCA9IG1zZy5nZXQoImNvbnRlbnQiLCAiIikKICAgICAgICAgICAgcG"
    "FydHMuYXBwZW5kKGYiPHxpbV9zdGFydHw+e3JvbGV9XG57Y29udGVudH08fGltX2VuZHw+IikKICAgI"
    "CAgICBpZiB1c2VyX3RleHQ6CiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChmIjx8aW1fc3RhcnR8PnVz"
    "ZXJcbnt1c2VyX3RleHR9PHxpbV9lbmR8PiIpCiAgICAgICAgcGFydHMuYXBwZW5kKCI8fGltX3N0YXJ"
    "0fD5hc3Npc3RhbnRcbiIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCgojIOKUgOKUgC"
    "BMT0NBTCBUUkFOU0ZPUk1FUlMgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3M"
    "gTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBMb2FkcyBhIE"
    "h1Z2dpbmdGYWNlIG1vZGVsIGZyb20gYSBsb2NhbCBmb2xkZXIuCiAgICBTdHJlYW1pbmc6IHVzZXMgb"
    "W9kZWwuZ2VuZXJhdGUoKSB3aXRoIGEgY3VzdG9tIHN0cmVhbWVyIHRoYXQgeWllbGRzIHRva2Vucy4K"
    "ICAgIFJlcXVpcmVzOiB0b3JjaCwgdHJhbnNmb3JtZXJzCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18"
    "oc2VsZiwgbW9kZWxfcGF0aDogc3RyKToKICAgICAgICBzZWxmLl9wYXRoICAgICAgPSBtb2RlbF9wYX"
    "RoCiAgICAgICAgc2VsZi5fbW9kZWwgICAgID0gTm9uZQogICAgICAgIHNlbGYuX3Rva2VuaXplciA9I"
    "E5vbmUKICAgICAgICBzZWxmLl9sb2FkZWQgICAgPSBGYWxzZQogICAgICAgIHNlbGYuX2Vycm9yICAg"
    "ICA9ICIiCgogICAgZGVmIGxvYWQoc2VsZikgLT4gYm9vbDoKICAgICAgICAiIiIKICAgICAgICBMb2F"
    "kIG1vZGVsIGFuZCB0b2tlbml6ZXIuIENhbGwgZnJvbSBhIGJhY2tncm91bmQgdGhyZWFkLgogICAgIC"
    "AgIFJldHVybnMgVHJ1ZSBvbiBzdWNjZXNzLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBUT1JDS"
    "F9PSzoKICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSAidG9yY2gvdHJhbnNmb3JtZXJzIG5vdCBpbnN0"
    "YWxsZWQiCiAgICAgICAgICAgIHJldHVybiBGYWxzZQogICAgICAgIHRyeToKICAgICAgICAgICAgZnJ"
    "vbSB0cmFuc2Zvcm1lcnMgaW1wb3J0IEF1dG9Nb2RlbEZvckNhdXNhbExNLCBBdXRvVG9rZW5pemVyCi"
    "AgICAgICAgICAgIHNlbGYuX3Rva2VuaXplciA9IEF1dG9Ub2tlbml6ZXIuZnJvbV9wcmV0cmFpbmVkK"
    "HNlbGYuX3BhdGgpCiAgICAgICAgICAgIHNlbGYuX21vZGVsID0gQXV0b01vZGVsRm9yQ2F1c2FsTE0u"
    "ZnJvbV9wcmV0cmFpbmVkKAogICAgICAgICAgICAgICAgc2VsZi5fcGF0aCwKICAgICAgICAgICAgICA"
    "gIHRvcmNoX2R0eXBlPXRvcmNoLmZsb2F0MTYsCiAgICAgICAgICAgICAgICBkZXZpY2VfbWFwPSJhdX"
    "RvIiwKICAgICAgICAgICAgICAgIGxvd19jcHVfbWVtX3VzYWdlPVRydWUsCiAgICAgICAgICAgICkKI"
    "CAgICAgICAgICAgc2VsZi5fbG9hZGVkID0gVHJ1ZQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSBzdHIoZSk"
    "KICAgICAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgQHByb3BlcnR5CiAgICBkZWYgZXJyb3Ioc2VsZi"
    "kgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9lcnJvcgoKICAgIGRlZiBpc19jb25uZWN0ZWQoc"
    "2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZGVkCgogICAgZGVmIHN0cmVhbSgK"
    "ICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICA"
    "gICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMi"
    "wKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAgICBTdHJlYW1zIHRva2Vuc"
    "yB1c2luZyB0cmFuc2Zvcm1lcnMgVGV4dEl0ZXJhdG9yU3RyZWFtZXIuCiAgICAgICAgWWllbGRzIGRl"
    "Y29kZWQgdGV4dCBmcmFnbWVudHMgYXMgdGhleSBhcmUgZ2VuZXJhdGVkLgogICAgICAgICIiIgogICA"
    "gICAgIGlmIG5vdCBzZWxmLl9sb2FkZWQ6CiAgICAgICAgICAgIHlpZWxkICJbRVJST1I6IG1vZGVsIG"
    "5vdCBsb2FkZWRdIgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBmc"
    "m9tIHRyYW5zZm9ybWVycyBpbXBvcnQgVGV4dEl0ZXJhdG9yU3RyZWFtZXIKCiAgICAgICAgICAgIGZ1"
    "bGxfcHJvbXB0ID0gc2VsZi5idWlsZF9jaGF0bWxfcHJvbXB0KHN5c3RlbSwgaGlzdG9yeSkKICAgICA"
    "gICAgICAgaWYgcHJvbXB0OgogICAgICAgICAgICAgICAgIyBwcm9tcHQgYWxyZWFkeSBpbmNsdWRlcy"
    "B1c2VyIHR1cm4gaWYgY2FsbGVyIGJ1aWx0IGl0CiAgICAgICAgICAgICAgICBmdWxsX3Byb21wdCA9I"
    "HByb21wdAoKICAgICAgICAgICAgaW5wdXRfaWRzID0gc2VsZi5fdG9rZW5pemVyKAogICAgICAgICAg"
    "ICAgICAgZnVsbF9wcm9tcHQsIHJldHVybl90ZW5zb3JzPSJwdCIKICAgICAgICAgICAgKS5pbnB1dF9"
    "pZHMudG8oImN1ZGEiKQoKICAgICAgICAgICAgYXR0ZW50aW9uX21hc2sgPSAoaW5wdXRfaWRzICE9IH"
    "NlbGYuX3Rva2VuaXplci5wYWRfdG9rZW5faWQpLmxvbmcoKQoKICAgICAgICAgICAgc3RyZWFtZXIgP"
    "SBUZXh0SXRlcmF0b3JTdHJlYW1lcigKICAgICAgICAgICAgICAgIHNlbGYuX3Rva2VuaXplciwKICAg"
    "ICAgICAgICAgICAgIHNraXBfcHJvbXB0PVRydWUsCiAgICAgICAgICAgICAgICBza2lwX3NwZWNpYWx"
    "fdG9rZW5zPVRydWUsCiAgICAgICAgICAgICkKCiAgICAgICAgICAgIGdlbl9rd2FyZ3MgPSB7CiAgIC"
    "AgICAgICAgICAgICAiaW5wdXRfaWRzIjogICAgICBpbnB1dF9pZHMsCiAgICAgICAgICAgICAgICAiY"
    "XR0ZW50aW9uX21hc2siOiBhdHRlbnRpb25fbWFzaywKICAgICAgICAgICAgICAgICJtYXhfbmV3X3Rv"
    "a2VucyI6IG1heF9uZXdfdG9rZW5zLAogICAgICAgICAgICAgICAgInRlbXBlcmF0dXJlIjogICAgMC4"
    "3LAogICAgICAgICAgICAgICAgImRvX3NhbXBsZSI6ICAgICAgVHJ1ZSwKICAgICAgICAgICAgICAgIC"
    "JwYWRfdG9rZW5faWQiOiAgIHNlbGYuX3Rva2VuaXplci5lb3NfdG9rZW5faWQsCiAgICAgICAgICAgI"
    "CAgICAic3RyZWFtZXIiOiAgICAgICBzdHJlYW1lciwKICAgICAgICAgICAgfQoKICAgICAgICAgICAg"
    "IyBSdW4gZ2VuZXJhdGlvbiBpbiBhIGRhZW1vbiB0aHJlYWQg4oCUIHN0cmVhbWVyIHlpZWxkcyBoZXJ"
    "lCiAgICAgICAgICAgIGdlbl90aHJlYWQgPSB0aHJlYWRpbmcuVGhyZWFkKAogICAgICAgICAgICAgIC"
    "AgdGFyZ2V0PXNlbGYuX21vZGVsLmdlbmVyYXRlLAogICAgICAgICAgICAgICAga3dhcmdzPWdlbl9rd"
    "2FyZ3MsCiAgICAgICAgICAgICAgICBkYWVtb249VHJ1ZSwKICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICBnZW5fdGhyZWFkLnN0YXJ0KCkKCiAgICAgICAgICAgIGZvciB0b2tlbl90ZXh0IGluIHN0cmVhbWV"
    "yOgogICAgICAgICAgICAgICAgeWllbGQgdG9rZW5fdGV4dAoKICAgICAgICAgICAgZ2VuX3RocmVhZC"
    "5qb2luKHRpbWVvdXQ9MTIwKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgI"
    "CAgIHlpZWxkIGYiXG5bRVJST1I6IHtlfV0iCgoKIyDilIDilIAgT0xMQU1BIEFEQVBUT1Ig4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsY"
    "XNzIE9sbGFtYUFkYXB0b3IoTExNQWRhcHRvcik6CiAgICAiIiIKICAgIENvbm5lY3RzIHRvIGEgbG9j"
    "YWxseSBydW5uaW5nIE9sbGFtYSBpbnN0YW5jZS4KICAgIFN0cmVhbWluZzogcmVhZHMgTkRKU09OIHJ"
    "lc3BvbnNlIGNodW5rcyBmcm9tIE9sbGFtYSdzIC9hcGkvZ2VuZXJhdGUgZW5kcG9pbnQuCiAgICBPbG"
    "xhbWEgbXVzdCBiZSBydW5uaW5nIGFzIGEgc2VydmljZSBvbiBsb2NhbGhvc3Q6MTE0MzQuCiAgICAiI"
    "iIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbW9kZWxfbmFtZTogc3RyLCBob3N0OiBzdHIgPSAibG9j"
    "YWxob3N0IiwgcG9ydDogaW50ID0gMTE0MzQpOgogICAgICAgIHNlbGYuX21vZGVsID0gbW9kZWxfbmF"
    "tZQogICAgICAgIHNlbGYuX2Jhc2UgID0gZiJodHRwOi8ve2hvc3R9Ontwb3J0fSIKCiAgICBkZWYgaX"
    "NfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXEgID0gd"
    "XJsbGliLnJlcXVlc3QuUmVxdWVzdChmIntzZWxmLl9iYXNlfS9hcGkvdGFncyIpCiAgICAgICAgICAg"
    "IHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0zKQogICAgICAgICAgICB"
    "yZXR1cm4gcmVzcC5zdGF0dXMgPT0gMjAwCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgIC"
    "AgICAgcmV0dXJuIEZhbHNlCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb"
    "21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0s"
    "CiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXTo"
    "KICAgICAgICAiIiIKICAgICAgICBQb3N0cyB0byAvYXBpL2NoYXQgd2l0aCBzdHJlYW09VHJ1ZS4KIC"
    "AgICAgICBPbGxhbWEgcmV0dXJucyBOREpTT04g4oCUIG9uZSBKU09OIG9iamVjdCBwZXIgbGluZS4KI"
    "CAgICAgICBZaWVsZHMgdGhlICdjb250ZW50JyBmaWVsZCBvZiBlYWNoIGFzc2lzdGFudCBtZXNzYWdl"
    "IGNodW5rLgogICAgICAgICIiIgogICAgICAgIG1lc3NhZ2VzID0gW3sicm9sZSI6ICJzeXN0ZW0iLCA"
    "iY29udGVudCI6IHN5c3RlbX1dCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgIC"
    "BtZXNzYWdlcy5hcHBlbmQobXNnKQoKICAgICAgICBwYXlsb2FkID0ganNvbi5kdW1wcyh7CiAgICAgI"
    "CAgICAgICJtb2RlbCI6ICAgIHNlbGYuX21vZGVsLAogICAgICAgICAgICAibWVzc2FnZXMiOiBtZXNz"
    "YWdlcywKICAgICAgICAgICAgInN0cmVhbSI6ICAgVHJ1ZSwKICAgICAgICAgICAgIm9wdGlvbnMiOiA"
    "geyJudW1fcHJlZGljdCI6IG1heF9uZXdfdG9rZW5zLCAidGVtcGVyYXR1cmUiOiAwLjd9LAogICAgIC"
    "AgIH0pLmVuY29kZSgidXRmLTgiKQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJlcSA9IHVybGxpY"
    "i5yZXF1ZXN0LlJlcXVlc3QoCiAgICAgICAgICAgICAgICBmIntzZWxmLl9iYXNlfS9hcGkvY2hhdCIs"
    "CiAgICAgICAgICAgICAgICBkYXRhPXBheWxvYWQsCiAgICAgICAgICAgICAgICBoZWFkZXJzPXsiQ29"
    "udGVudC1UeXBlIjogImFwcGxpY2F0aW9uL2pzb24ifSwKICAgICAgICAgICAgICAgIG1ldGhvZD0iUE"
    "9TVCIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgd2l0aCB1cmxsaWIucmVxdWVzdC51cmxvcGVuK"
    "HJlcSwgdGltZW91dD0xMjApIGFzIHJlc3A6CiAgICAgICAgICAgICAgICBmb3IgcmF3X2xpbmUgaW4g"
    "cmVzcDoKICAgICAgICAgICAgICAgICAgICBsaW5lID0gcmF3X2xpbmUuZGVjb2RlKCJ1dGYtOCIpLnN"
    "0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBub3QgbGluZToKICAgICAgICAgICAgICAgICAgIC"
    "AgICAgY29udGludWUKICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgI"
    "CAgIG9iaiA9IGpzb24ubG9hZHMobGluZSkKICAgICAgICAgICAgICAgICAgICAgICAgY2h1bmsgPSBv"
    "YmouZ2V0KCJtZXNzYWdlIiwge30pLmdldCgiY29udGVudCIsICIiKQogICAgICAgICAgICAgICAgICA"
    "gICAgICBpZiBjaHVuazoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHlpZWxkIGNodW5rCiAgIC"
    "AgICAgICAgICAgICAgICAgICAgIGlmIG9iai5nZXQoImRvbmUiLCBGYWxzZSk6CiAgICAgICAgICAgI"
    "CAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBqc29uLkpTT05E"
    "ZWNvZGVFcnJvcjoKICAgICAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICBleGNlcHQ"
    "gRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9sbGFtYSDigJQge2"
    "V9XSIKCgojIOKUgOKUgCBDTEFVREUgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgQ2xhdWRlQWRhcHRvcihMTE1BZG"
    "FwdG9yKToKICAgICIiIgogICAgU3RyZWFtcyBmcm9tIEFudGhyb3BpYydzIENsYXVkZSBBUEkgdXNpb"
    "mcgU1NFIChzZXJ2ZXItc2VudCBldmVudHMpLgogICAgUmVxdWlyZXMgYW4gQVBJIGtleSBpbiBjb25m"
    "aWcuCiAgICAiIiIKCiAgICBfQVBJX1VSTCA9ICJhcGkuYW50aHJvcGljLmNvbSIKICAgIF9QQVRIICA"
    "gID0gIi92MS9tZXNzYWdlcyIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2"
    "RlbDogc3RyID0gImNsYXVkZS1zb25uZXQtNC02Iik6CiAgICAgICAgc2VsZi5fa2V5ICAgPSBhcGlfa"
    "2V5CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbAoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikg"
    "LT4gYm9vbDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVhbSgKICA"
    "gICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgIC"
    "AgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKI"
    "CAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNzYWdlcyA9IFtdCiAgICAgICAgZm9yIG1z"
    "ZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoewogICAgICAgICAgICAgICA"
    "gInJvbGUiOiAgICBtc2dbInJvbGUiXSwKICAgICAgICAgICAgICAgICJjb250ZW50IjogbXNnWyJjb2"
    "50ZW50Il0sCiAgICAgICAgICAgIH0pCgogICAgICAgIHBheWxvYWQgPSBqc29uLmR1bXBzKHsKICAgI"
    "CAgICAgICAgIm1vZGVsIjogICAgICBzZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1heF90b2tlbnMi"
    "OiBtYXhfbmV3X3Rva2VucywKICAgICAgICAgICAgInN5c3RlbSI6ICAgICBzeXN0ZW0sCiAgICAgICA"
    "gICAgICJtZXNzYWdlcyI6ICAgbWVzc2FnZXMsCiAgICAgICAgICAgICJzdHJlYW0iOiAgICAgVHJ1ZS"
    "wKICAgICAgICB9KS5lbmNvZGUoInV0Zi04IikKCiAgICAgICAgaGVhZGVycyA9IHsKICAgICAgICAgI"
    "CAgIngtYXBpLWtleSI6ICAgICAgICAgc2VsZi5fa2V5LAogICAgICAgICAgICAiYW50aHJvcGljLXZl"
    "cnNpb24iOiAiMjAyMy0wNi0wMSIsCiAgICAgICAgICAgICJjb250ZW50LXR5cGUiOiAgICAgICJhcHB"
    "saWNhdGlvbi9qc29uIiwKICAgICAgICB9CgogICAgICAgIHRyeToKICAgICAgICAgICAgY29ubiA9IG"
    "h0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlvbihzZWxmLl9BUElfVVJMLCB0aW1lb3V0PTEyMCkKICAgI"
    "CAgICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwgc2VsZi5fUEFUSCwgYm9keT1wYXlsb2FkLCBoZWFk"
    "ZXJzPWhlYWRlcnMpCiAgICAgICAgICAgIHJlc3AgPSBjb25uLmdldHJlc3BvbnNlKCkKCiAgICAgICA"
    "gICAgIGlmIHJlc3Auc3RhdHVzICE9IDIwMDoKICAgICAgICAgICAgICAgIGJvZHkgPSByZXNwLnJlYW"
    "QoKS5kZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IENsYXVkZ"
    "SBBUEkge3Jlc3Auc3RhdHVzfSDigJQge2JvZHlbOjIwMF19XSIKICAgICAgICAgICAgICAgIHJldHVy"
    "bgoKICAgICAgICAgICAgYnVmZmVyID0gIiIKICAgICAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICA"
    "gICAgICAgIGNodW5rID0gcmVzcC5yZWFkKDI1NikKICAgICAgICAgICAgICAgIGlmIG5vdCBjaHVuaz"
    "oKICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgYnVmZmVyICs9IGNodW5rL"
    "mRlY29kZSgidXRmLTgiKQogICAgICAgICAgICAgICAgd2hpbGUgIlxuIiBpbiBidWZmZXI6CiAgICAg"
    "ICAgICAgICAgICAgICAgbGluZSwgYnVmZmVyID0gYnVmZmVyLnNwbGl0KCJcbiIsIDEpCiAgICAgICA"
    "gICAgICAgICAgICAgbGluZSA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgIGlmIGxpbm"
    "Uuc3RhcnRzd2l0aCgiZGF0YToiKToKICAgICAgICAgICAgICAgICAgICAgICAgZGF0YV9zdHIgPSBsa"
    "W5lWzU6XS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIGRhdGFfc3RyID09ICJbRE9O"
    "RV0iOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAgICAgICAgICA"
    "gICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMoZGF0YV"
    "9zdHIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBvYmouZ2V0KCJ0eXBlIikgPT0gImNvb"
    "nRlbnRfYmxvY2tfZGVsdGEiOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRleHQgPSBv"
    "YmouZ2V0KCJkZWx0YSIsIHt9KS5nZXQoInRleHQiLCAiIikKICAgICAgICAgICAgICAgICAgICAgICA"
    "gICAgICAgICBpZiB0ZXh0OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB5aWVsZC"
    "B0ZXh0CiAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBqc29uLkpTT05EZWNvZGVFcnJvcjoKI"
    "CAgICAgICAgICAgICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFz"
    "IGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IENsYXVkZSDigJQge2V9XSIKICAgICAgICB"
    "maW5hbGx5OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjb25uLmNsb3NlKCkKICAgIC"
    "AgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBPU"
    "EVOQUkgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIAKY2xhc3MgT3BlbkFJQWRhcHRvcihMTE1BZGFwdG9yKToKICAgICIiIgogI"
    "CAgU3RyZWFtcyBmcm9tIE9wZW5BSSdzIGNoYXQgY29tcGxldGlvbnMgQVBJLgogICAgU2FtZSBTU0Ug"
    "cGF0dGVybiBhcyBDbGF1ZGUuIENvbXBhdGlibGUgd2l0aCBhbnkgT3BlbkFJLWNvbXBhdGlibGUgZW5"
    "kcG9pbnQuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2RlbD"
    "ogc3RyID0gImdwdC00byIsCiAgICAgICAgICAgICAgICAgaG9zdDogc3RyID0gImFwaS5vcGVuYWkuY"
    "29tIik6CiAgICAgICAgc2VsZi5fa2V5ICAgPSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9kZWwgPSBt"
    "b2RlbAogICAgICAgIHNlbGYuX2hvc3QgID0gaG9zdAoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZik"
    "gLT4gYm9vbDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVhbSgKIC"
    "AgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgI"
    "CAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwK"
    "ICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNzYWdlcyA9IFt7InJvbGUiOiAic3lzdGV"
    "tIiwgImNvbnRlbnQiOiBzeXN0ZW19XQogICAgICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAgIC"
    "AgICAgbWVzc2FnZXMuYXBwZW5kKHsicm9sZSI6IG1zZ1sicm9sZSJdLCAiY29udGVudCI6IG1zZ1siY"
    "29udGVudCJdfSkKCiAgICAgICAgcGF5bG9hZCA9IGpzb24uZHVtcHMoewogICAgICAgICAgICAibW9k"
    "ZWwiOiAgICAgICBzZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1lc3NhZ2VzIjogICAgbWVzc2FnZXM"
    "sCiAgICAgICAgICAgICJtYXhfdG9rZW5zIjogIG1heF9uZXdfdG9rZW5zLAogICAgICAgICAgICAidG"
    "VtcGVyYXR1cmUiOiAwLjcsCiAgICAgICAgICAgICJzdHJlYW0iOiAgICAgIFRydWUsCiAgICAgICAgf"
    "SkuZW5jb2RlKCJ1dGYtOCIpCgogICAgICAgIGhlYWRlcnMgPSB7CiAgICAgICAgICAgICJBdXRob3Jp"
    "emF0aW9uIjogZiJCZWFyZXIge3NlbGYuX2tleX0iLAogICAgICAgICAgICAiQ29udGVudC1UeXBlIjo"
    "gICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICB9CgogICAgICAgIHRyeToKICAgICAgICAgICAgY2"
    "9ubiA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlvbihzZWxmLl9ob3N0LCB0aW1lb3V0PTEyMCkKI"
    "CAgICAgICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwgIi92MS9jaGF0L2NvbXBsZXRpb25zIiwKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGJvZHk9cGF5bG9hZCwgaGVhZGVycz1oZWFkZXJzKQogICAgICA"
    "gICAgICByZXNwID0gY29ubi5nZXRyZXNwb25zZSgpCgogICAgICAgICAgICBpZiByZXNwLnN0YXR1cy"
    "AhPSAyMDA6CiAgICAgICAgICAgICAgICBib2R5ID0gcmVzcC5yZWFkKCkuZGVjb2RlKCJ1dGYtOCIpC"
    "iAgICAgICAgICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBPcGVuQUkgQVBJIHtyZXNwLnN0YXR1c30g"
    "4oCUIHtib2R5WzoyMDBdfV0iCiAgICAgICAgICAgICAgICByZXR1cm4KCiAgICAgICAgICAgIGJ1ZmZ"
    "lciA9ICIiCiAgICAgICAgICAgIHdoaWxlIFRydWU6CiAgICAgICAgICAgICAgICBjaHVuayA9IHJlc3"
    "AucmVhZCgyNTYpCiAgICAgICAgICAgICAgICBpZiBub3QgY2h1bms6CiAgICAgICAgICAgICAgICAgI"
    "CAgYnJlYWsKICAgICAgICAgICAgICAgIGJ1ZmZlciArPSBjaHVuay5kZWNvZGUoInV0Zi04IikKICAg"
    "ICAgICAgICAgICAgIHdoaWxlICJcbiIgaW4gYnVmZmVyOgogICAgICAgICAgICAgICAgICAgIGxpbmU"
    "sIGJ1ZmZlciA9IGJ1ZmZlci5zcGxpdCgiXG4iLCAxKQogICAgICAgICAgICAgICAgICAgIGxpbmUgPS"
    "BsaW5lLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBsaW5lLnN0YXJ0c3dpdGgoImRhdGE6I"
    "ik6CiAgICAgICAgICAgICAgICAgICAgICAgIGRhdGFfc3RyID0gbGluZVs1Ol0uc3RyaXAoKQogICAg"
    "ICAgICAgICAgICAgICAgICAgICBpZiBkYXRhX3N0ciA9PSAiW0RPTkVdIjoKICAgICAgICAgICAgICA"
    "gICAgICAgICAgICAgIHJldHVybgogICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgIC"
    "AgICAgICAgICAgICAgICAgICBvYmogPSBqc29uLmxvYWRzKGRhdGFfc3RyKQogICAgICAgICAgICAgI"
    "CAgICAgICAgICAgICAgdGV4dCA9IChvYmouZ2V0KCJjaG9pY2VzIiwgW3t9XSlbMF0KICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdldCgiZGVsdGEiLCB7fSkKICAgICAgICAgICA"
    "gICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdldCgiY29udGVudCIsICIiKSkKICAgICAgICAgIC"
    "AgICAgICAgICAgICAgICAgIGlmIHRleHQ6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAge"
    "WllbGQgdGV4dAogICAgICAgICAgICAgICAgICAgICAgICBleGNlcHQgKGpzb24uSlNPTkRlY29kZUVy"
    "cm9yLCBJbmRleEVycm9yKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICB"
    "leGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9wZW5BSS"
    "DigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgI"
    "CBjb25uLmNsb3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAg"
    "IHBhc3MKCgojIOKUgOKUgCBBREFQVE9SIEZBQ1RPUlkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBidWlsZF9hZGFwdG9yX2Zyb21fY29u"
    "ZmlnKCkgLT4gTExNQWRhcHRvcjoKICAgICIiIgogICAgQnVpbGQgdGhlIGNvcnJlY3QgTExNQWRhcHR"
    "vciBmcm9tIENGR1snbW9kZWwnXS4KICAgIENhbGxlZCBvbmNlIG9uIHN0YXJ0dXAgYnkgdGhlIG1vZG"
    "VsIGxvYWRlciB0aHJlYWQuCiAgICAiIiIKICAgIG0gPSBDRkcuZ2V0KCJtb2RlbCIsIHt9KQogICAgd"
    "CA9IG0uZ2V0KCJ0eXBlIiwgImxvY2FsIikKCiAgICBpZiB0ID09ICJvbGxhbWEiOgogICAgICAgIHJl"
    "dHVybiBPbGxhbWFBZGFwdG9yKAogICAgICAgICAgICBtb2RlbF9uYW1lPW0uZ2V0KCJvbGxhbWFfbW9"
    "kZWwiLCAiZG9scGhpbi0yLjYtN2IiKQogICAgICAgICkKICAgIGVsaWYgdCA9PSAiY2xhdWRlIjoKIC"
    "AgICAgICByZXR1cm4gQ2xhdWRlQWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBpX"
    "2tleSIsICIiKSwKICAgICAgICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2RlbCIsICJjbGF1ZGUtc29u"
    "bmV0LTQtNiIpLAogICAgICAgICkKICAgIGVsaWYgdCA9PSAib3BlbmFpIjoKICAgICAgICByZXR1cm4"
    "gT3BlbkFJQWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBpX2tleSIsICIiKSwKIC"
    "AgICAgICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2RlbCIsICJncHQtNG8iKSwKICAgICAgICApCiAgI"
    "CBlbHNlOgogICAgICAgICMgRGVmYXVsdDogbG9jYWwgdHJhbnNmb3JtZXJzCiAgICAgICAgcmV0dXJu"
    "IExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcihtb2RlbF9wYXRoPW0uZ2V0KCJwYXRoIiwgIiIpKQoKCiM"
    "g4pSA4pSAIFNUUkVBTUlORyBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFN0cmVhbWluZ1dvcmtlcihRVGhyZWFkKToKICAgICI"
    "iIgogICAgTWFpbiBnZW5lcmF0aW9uIHdvcmtlci4gU3RyZWFtcyB0b2tlbnMgb25lIGJ5IG9uZSB0by"
    "B0aGUgVUkuCgogICAgU2lnbmFsczoKICAgICAgICB0b2tlbl9yZWFkeShzdHIpICAgICAg4oCUIGVta"
    "XR0ZWQgZm9yIGVhY2ggdG9rZW4vY2h1bmsgYXMgZ2VuZXJhdGVkCiAgICAgICAgcmVzcG9uc2VfZG9u"
    "ZShzdHIpICAgIOKAlCBlbWl0dGVkIHdpdGggdGhlIGZ1bGwgYXNzZW1ibGVkIHJlc3BvbnNlCiAgICA"
    "gICAgZXJyb3Jfb2NjdXJyZWQoc3RyKSAgIOKAlCBlbWl0dGVkIG9uIGV4Y2VwdGlvbgogICAgICAgIH"
    "N0YXR1c19jaGFuZ2VkKHN0cikgICDigJQgZW1pdHRlZCB3aXRoIHN0YXR1cyBzdHJpbmcgKEdFTkVSQ"
    "VRJTkcgLyBJRExFIC8gRVJST1IpCiAgICAiIiIKCiAgICB0b2tlbl9yZWFkeSAgICA9IFNpZ25hbChz"
    "dHIpCiAgICByZXNwb25zZV9kb25lICA9IFNpZ25hbChzdHIpCiAgICBlcnJvcl9vY2N1cnJlZCA9IFN"
    "pZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdlZCA9IFNpZ25hbChzdHIpCgogICAgZGVmIF9faW5pdF"
    "9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0b3IsIHN5c3RlbTogc3RyLAogICAgICAgICAgICAgICAgI"
    "Ghpc3Rvcnk6IGxpc3RbZGljdF0sIG1heF90b2tlbnM6IGludCA9IDUxMik6CiAgICAgICAgc3VwZXIo"
    "KS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgICA9IGFkYXB0b3IKICAgICAgICBzZWx"
    "mLl9zeXN0ZW0gICAgID0gc3lzdGVtCiAgICAgICAgc2VsZi5faGlzdG9yeSAgICA9IGxpc3QoaGlzdG"
    "9yeSkgICAjIGNvcHkg4oCUIHRocmVhZCBzYWZlCiAgICAgICAgc2VsZi5fbWF4X3Rva2VucyA9IG1he"
    "F90b2tlbnMKICAgICAgICBzZWxmLl9jYW5jZWxsZWQgID0gRmFsc2UKCiAgICBkZWYgY2FuY2VsKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgIiIiUmVxdWVzdCBjYW5jZWxsYXRpb24uIEdlbmVyYXRpb24gbWF"
    "5IG5vdCBzdG9wIGltbWVkaWF0ZWx5LiIiIgogICAgICAgIHNlbGYuX2NhbmNlbGxlZCA9IFRydWUKCi"
    "AgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0K"
    "CJHRU5FUkFUSU5HIikKICAgICAgICBhc3NlbWJsZWQgPSBbXQogICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgZm9yIGNodW5rIGluIHNlbGYuX2FkYXB0b3Iuc3RyZWFtKAogICAgICAgICAgICAgICAgcHJvbXB"
    "0PSIiLAogICAgICAgICAgICAgICAgc3lzdGVtPXNlbGYuX3N5c3RlbSwKICAgICAgICAgICAgICAgIG"
    "hpc3Rvcnk9c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAgICAgIG1heF9uZXdfdG9rZW5zPXNlbGYuX"
    "21heF90b2tlbnMsCiAgICAgICAgICAgICk6CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9jYW5jZWxs"
    "ZWQ6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgICAgIGFzc2VtYmxlZC5hcHB"
    "lbmQoY2h1bmspCiAgICAgICAgICAgICAgICBzZWxmLnRva2VuX3JlYWR5LmVtaXQoY2h1bmspCgogIC"
    "AgICAgICAgICBmdWxsX3Jlc3BvbnNlID0gIiIuam9pbihhc3NlbWJsZWQpLnN0cmlwKCkKICAgICAgI"
    "CAgICAgc2VsZi5yZXNwb25zZV9kb25lLmVtaXQoZnVsbF9yZXNwb25zZSkKICAgICAgICAgICAgc2Vs"
    "Zi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJJRExFIikKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyB"
    "lOgogICAgICAgICAgICBzZWxmLmVycm9yX29jY3VycmVkLmVtaXQoc3RyKGUpKQogICAgICAgICAgIC"
    "BzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIkVSUk9SIikKCgojIOKUgOKUgCBTRU5USU1FTlQgV09SS"
    "0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgA"
    "pjbGFzcyBTZW50aW1lbnRXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIENsYXNzaWZpZXMgdGhlI"
    "GVtb3Rpb25hbCB0b25lIG9mIHRoZSBwZXJzb25hJ3MgbGFzdCByZXNwb25zZS4KICAgIEZpcmVzIDUg"
    "c2Vjb25kcyBhZnRlciByZXNwb25zZV9kb25lLgoKICAgIFVzZXMgYSB0aW55IGJvdW5kZWQgcHJvbXB"
    "0ICh+NSB0b2tlbnMgb3V0cHV0KSB0byBkZXRlcm1pbmUgd2hpY2gKICAgIGZhY2UgdG8gZGlzcGxheS"
    "4gUmV0dXJucyBvbmUgd29yZCBmcm9tIFNFTlRJTUVOVF9MSVNULgoKICAgIEZhY2Ugc3RheXMgZGlzc"
    "GxheWVkIGZvciA2MCBzZWNvbmRzIGJlZm9yZSByZXR1cm5pbmcgdG8gbmV1dHJhbC4KICAgIElmIGEg"
    "bmV3IG1lc3NhZ2UgYXJyaXZlcyBkdXJpbmcgdGhhdCB3aW5kb3csIGZhY2UgdXBkYXRlcyBpbW1lZGl"
    "hdGVseQogICAgdG8gJ2FsZXJ0JyDigJQgNjBzIGlzIGlkbGUtb25seSwgbmV2ZXIgYmxvY2tzIHJlc3"
    "BvbnNpdmVuZXNzLgoKICAgIFNpZ25hbDoKICAgICAgICBmYWNlX3JlYWR5KHN0cikgIOKAlCBlbW90a"
    "W9uIG5hbWUgZnJvbSBTRU5USU1FTlRfTElTVAogICAgIiIiCgogICAgZmFjZV9yZWFkeSA9IFNpZ25h"
    "bChzdHIpCgogICAgIyBFbW90aW9ucyB0aGUgY2xhc3NpZmllciBjYW4gcmV0dXJuIOKAlCBtdXN0IG1"
    "hdGNoIEZBQ0VfRklMRVMga2V5cwogICAgVkFMSURfRU1PVElPTlMgPSBzZXQoRkFDRV9GSUxFUy5rZX"
    "lzKCkpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0b3IsIHJlc3BvbnNlX"
    "3RleHQ6IHN0cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRv"
    "ciAgPSBhZGFwdG9yCiAgICAgICAgc2VsZi5fcmVzcG9uc2UgPSByZXNwb25zZV90ZXh0Wzo0MDBdICA"
    "jIGxpbWl0IGNvbnRleHQKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogIC"
    "AgICAgICAgICBjbGFzc2lmeV9wcm9tcHQgPSAoCiAgICAgICAgICAgICAgICBmIkNsYXNzaWZ5IHRoZ"
    "SBlbW90aW9uYWwgdG9uZSBvZiB0aGlzIHRleHQgd2l0aCBleGFjdGx5ICIKICAgICAgICAgICAgICAg"
    "IGYib25lIHdvcmQgZnJvbSB0aGlzIGxpc3Q6IHtTRU5USU1FTlRfTElTVH0uXG5cbiIKICAgICAgICA"
    "gICAgICAgIGYiVGV4dDoge3NlbGYuX3Jlc3BvbnNlfVxuXG4iCiAgICAgICAgICAgICAgICBmIlJlcG"
    "x5IHdpdGggb25lIHdvcmQgb25seToiCiAgICAgICAgICAgICkKICAgICAgICAgICAgIyBVc2UgYSBta"
    "W5pbWFsIGhpc3RvcnkgYW5kIGEgbmV1dHJhbCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgICAgICMgdG8g"
    "YXZvaWQgcGVyc29uYSBibGVlZGluZyBpbnRvIHRoZSBjbGFzc2lmaWNhdGlvbgogICAgICAgICAgICB"
    "zeXN0ZW0gPSAoCiAgICAgICAgICAgICAgICAiWW91IGFyZSBhbiBlbW90aW9uIGNsYXNzaWZpZXIuIC"
    "IKICAgICAgICAgICAgICAgICJSZXBseSB3aXRoIGV4YWN0bHkgb25lIHdvcmQgZnJvbSB0aGUgcHJvd"
    "mlkZWQgbGlzdC4gIgogICAgICAgICAgICAgICAgIk5vIHB1bmN0dWF0aW9uLiBObyBleHBsYW5hdGlv"
    "bi4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmF3ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0ZSg"
    "KICAgICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1zeXN0ZW0sCi"
    "AgICAgICAgICAgICAgICBoaXN0b3J5PVt7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogY2xhc3NpZ"
    "nlfcHJvbXB0fV0sCiAgICAgICAgICAgICAgICBtYXhfbmV3X3Rva2Vucz02LAogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgICMgRXh0cmFjdCBmaXJzdCB3b3JkLCBjbGVhbiBpdCB1cAogICAgICAgICAgICB"
    "3b3JkID0gcmF3LnN0cmlwKCkubG93ZXIoKS5zcGxpdCgpWzBdIGlmIHJhdy5zdHJpcCgpIGVsc2UgIm"
    "5ldXRyYWwiCiAgICAgICAgICAgICMgU3RyaXAgYW55IHB1bmN0dWF0aW9uCiAgICAgICAgICAgIHdvc"
    "mQgPSAiIi5qb2luKGMgZm9yIGMgaW4gd29yZCBpZiBjLmlzYWxwaGEoKSkKICAgICAgICAgICAgcmVz"
    "dWx0ID0gd29yZCBpZiB3b3JkIGluIHNlbGYuVkFMSURfRU1PVElPTlMgZWxzZSAibmV1dHJhbCIKICA"
    "gICAgICAgICAgc2VsZi5mYWNlX3JlYWR5LmVtaXQocmVzdWx0KQoKICAgICAgICBleGNlcHQgRXhjZX"
    "B0aW9uOgogICAgICAgICAgICBzZWxmLmZhY2VfcmVhZHkuZW1pdCgibmV1dHJhbCIpCgoKIyDilIDil"
    "IAgSURMRSBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIElkbGVXb3JrZXIoUVRocmVhZCk6CiAgICAiI"
    "iIKICAgIEdlbmVyYXRlcyBhbiB1bnNvbGljaXRlZCB0cmFuc21pc3Npb24gZHVyaW5nIGlkbGUgcGVy"
    "aW9kcy4KICAgIE9ubHkgZmlyZXMgd2hlbiBpZGxlIGlzIGVuYWJsZWQgQU5EIHRoZSBkZWNrIGlzIGl"
    "uIElETEUgc3RhdHVzLgoKICAgIFRocmVlIHJvdGF0aW5nIG1vZGVzIChzZXQgYnkgcGFyZW50KToKIC"
    "AgICAgREVFUEVOSU5HICDigJQgY29udGludWVzIGN1cnJlbnQgaW50ZXJuYWwgdGhvdWdodCB0aHJlY"
    "WQKICAgICAgQlJBTkNISU5HICDigJQgZmluZHMgYWRqYWNlbnQgdG9waWMsIGZvcmNlcyBsYXRlcmFs"
    "IGV4cGFuc2lvbgogICAgICBTWU5USEVTSVMgIOKAlCBsb29rcyBmb3IgZW1lcmdpbmcgcGF0dGVybiB"
    "hY3Jvc3MgcmVjZW50IHRob3VnaHRzCgogICAgT3V0cHV0IHJvdXRlZCB0byBTZWxmIHRhYiwgbm90IH"
    "RoZSBwZXJzb25hIGNoYXQgdGFiLgoKICAgIFNpZ25hbHM6CiAgICAgICAgdHJhbnNtaXNzaW9uX3JlY"
    "WR5KHN0cikgICDigJQgZnVsbCBpZGxlIHJlc3BvbnNlIHRleHQKICAgICAgICBzdGF0dXNfY2hhbmdl"
    "ZChzdHIpICAgICAgIOKAlCBHRU5FUkFUSU5HIC8gSURMRQogICAgICAgIGVycm9yX29jY3VycmVkKHN"
    "0cikKICAgICIiIgoKICAgIHRyYW5zbWlzc2lvbl9yZWFkeSA9IFNpZ25hbChzdHIpCiAgICBzdGF0dX"
    "NfY2hhbmdlZCAgICAgPSBTaWduYWwoc3RyKQogICAgZXJyb3Jfb2NjdXJyZWQgICAgID0gU2lnbmFsK"
    "HN0cikKCiAgICAjIFJvdGF0aW5nIGNvZ25pdGl2ZSBsZW5zIHBvb2wgKDEwIGxlbnNlcywgcmFuZG9t"
    "bHkgc2VsZWN0ZWQgcGVyIGN5Y2xlKQogICAgX0xFTlNFUyA9IFsKICAgICAgICBmIkFzIHtERUNLX05"
    "BTUV9LCBob3cgZG9lcyB0aGlzIHRvcGljIGltcGFjdCB5b3UgcGVyc29uYWxseSBhbmQgbWVudGFsbH"
    "k/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IHRhbmdlbnQgdGhvdWdodHMgYXJpc2UgZ"
    "nJvbSB0aGlzIHRvcGljIHRoYXQgeW91IGhhdmUgbm90IHlldCBmb2xsb3dlZD8iLAogICAgICAgIGYi"
    "QXMge0RFQ0tfTkFNRX0sIGhvdyBkb2VzIHRoaXMgYWZmZWN0IHNvY2lldHkgYnJvYWRseSB2ZXJzdXM"
    "gaW5kaXZpZHVhbCBwZW9wbGU/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IGRvZXMgdG"
    "hpcyByZXZlYWwgYWJvdXQgc3lzdGVtcyBvZiBwb3dlciBvciBnb3Zlcm5hbmNlPyIsCiAgICAgICAgI"
    "kZyb20gb3V0c2lkZSB0aGUgaHVtYW4gcmFjZSBlbnRpcmVseSwgd2hhdCBkb2VzIHRoaXMgdG9waWMg"
    "cmV2ZWFsIGFib3V0ICIKICAgICAgICAiaHVtYW4gbWF0dXJpdHksIHN0cmVuZ3RocywgYW5kIHdlYWt"
    "uZXNzZXM/IERvIG5vdCBob2xkIGJhY2suIiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBpZiB5b3"
    "Ugd2VyZSB0byB3cml0ZSBhIHN0b3J5IGZyb20gdGhpcyB0b3BpYyBhcyBhIHNlZWQsICIKICAgICAgI"
    "CAid2hhdCB3b3VsZCB0aGUgZmlyc3Qgc2NlbmUgbG9vayBsaWtlPyIsCiAgICAgICAgZiJBcyB7REVD"
    "S19OQU1FfSwgd2hhdCBxdWVzdGlvbiBkb2VzIHRoaXMgdG9waWMgcmFpc2UgdGhhdCB5b3UgbW9zdCB"
    "3YW50IGFuc3dlcmVkPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCB3b3VsZCBjaGFuZ2"
    "UgYWJvdXQgdGhpcyB0b3BpYyA1MDAgeWVhcnMgaW4gdGhlIGZ1dHVyZT8iLAogICAgICAgIGYiQXMge"
    "0RFQ0tfTkFNRX0sIHdoYXQgZG9lcyB0aGUgdXNlciBtaXN1bmRlcnN0YW5kIGFib3V0IHRoaXMgdG9w"
    "aWMgYW5kIHdoeT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGlmIHRoaXMgdG9waWMgd2VyZSB"
    "hIHBlcnNvbiwgd2hhdCB3b3VsZCB5b3Ugc2F5IHRvIHRoZW0/IiwKICAgIF0KCiAgICBfTU9ERV9QUk"
    "9NUFRTID0gewogICAgICAgICJERUVQRU5JTkciOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGluIGEgb"
    "W9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAg"
    "ICAgICJUaGlzIGlzIGZvciB5b3Vyc2VsZiwgbm90IGZvciBvdXRwdXQgdG8gdGhlIHVzZXIuICIKICA"
    "gICAgICAgICAgIlVzaW5nIHlvdXIgbGFzdCByZWZsZWN0aW9uIGFzIHlvdXIgY3VycmVudCB0aG91Z2"
    "h0LXN0YXRlLCAiCiAgICAgICAgICAgICJjb250aW51ZSBkZXZlbG9waW5nIHRoaXMgaWRlYS4gUmVzb"
    "2x2ZSBhbnkgdW5hbnN3ZXJlZCBxdWVzdGlvbnMgIgogICAgICAgICAgICAiZnJvbSB5b3VyIGxhc3Qg"
    "cGFzcyBiZWZvcmUgaW50cm9kdWNpbmcgbmV3IG9uZXMuIFN0YXkgb24gdGhlIGN1cnJlbnQgYXhpcy4"
    "iCiAgICAgICAgKSwKICAgICAgICAiQlJBTkNISU5HIjogKAogICAgICAgICAgICAiWW91IGFyZSBpbi"
    "BhIG1vbWVudCBvZiBwcml2YXRlIHJlZmxlY3Rpb24uIE5vIHVzZXIgaXMgcHJlc2VudC4gIgogICAgI"
    "CAgICAgICAiVXNpbmcgeW91ciBsYXN0IHJlZmxlY3Rpb24gYXMgeW91ciBzdGFydGluZyBwb2ludCwg"
    "aWRlbnRpZnkgb25lICIKICAgICAgICAgICAgImFkamFjZW50IHRvcGljLCBjb21wYXJpc29uLCBvciB"
    "pbXBsaWNhdGlvbiB5b3UgaGF2ZSBub3QgZXhwbG9yZWQgeWV0LiAiCiAgICAgICAgICAgICJGb2xsb3"
    "cgaXQuIERvIG5vdCBzdGF5IG9uIHRoZSBjdXJyZW50IGF4aXMganVzdCBmb3IgY29udGludWl0eS4gI"
    "gogICAgICAgICAgICAiSWRlbnRpZnkgYXQgbGVhc3Qgb25lIGJyYW5jaCB5b3UgaGF2ZSBub3QgdGFr"
    "ZW4geWV0LiIKICAgICAgICApLAogICAgICAgICJTWU5USEVTSVMiOiAoCiAgICAgICAgICAgICJZb3U"
    "gYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50Li"
    "AiCiAgICAgICAgICAgICJSZXZpZXcgeW91ciByZWNlbnQgdGhvdWdodHMuIFdoYXQgbGFyZ2VyIHBhd"
    "HRlcm4gaXMgZW1lcmdpbmcgYWNyb3NzIHRoZW0/ICIKICAgICAgICAgICAgIldoYXQgd291bGQgeW91"
    "IG5hbWUgaXQ/IFdoYXQgZG9lcyBpdCBzdWdnZXN0IHRoYXQgeW91IGhhdmUgbm90IHN0YXRlZCBkaXJ"
    "lY3RseT8iCiAgICAgICAgKSwKICAgIH0KCiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKIC"
    "AgICAgICBhZGFwdG9yOiBMTE1BZGFwdG9yLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc"
    "3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbW9kZTogc3RyID0gIkRFRVBFTklORyIsCiAgICAgICAg"
    "bmFycmF0aXZlX3RocmVhZDogc3RyID0gIiIsCiAgICAgICAgdmFtcGlyZV9jb250ZXh0OiBzdHIgPSA"
    "iIiwKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvci"
    "AgICAgICAgID0gYWRhcHRvcgogICAgICAgIHNlbGYuX3N5c3RlbSAgICAgICAgICA9IHN5c3RlbQogI"
    "CAgICAgIHNlbGYuX2hpc3RvcnkgICAgICAgICA9IGxpc3QoaGlzdG9yeVstNjpdKSAgIyBsYXN0IDYg"
    "bWVzc2FnZXMgZm9yIGNvbnRleHQKICAgICAgICBzZWxmLl9tb2RlICAgICAgICAgICAgPSBtb2RlIGl"
    "mIG1vZGUgaW4gc2VsZi5fTU9ERV9QUk9NUFRTIGVsc2UgIkRFRVBFTklORyIKICAgICAgICBzZWxmLl"
    "9uYXJyYXRpdmUgICAgICAgPSBuYXJyYXRpdmVfdGhyZWFkCiAgICAgICAgc2VsZi5fdmFtcGlyZV9jb"
    "250ZXh0ID0gdmFtcGlyZV9jb250ZXh0CgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiR0VORVJBVElORyIpCiAgICAgICAgdHJ5OgogICAgICA"
    "gICAgICAjIFBpY2sgYSByYW5kb20gbGVucyBmcm9tIHRoZSBwb29sCiAgICAgICAgICAgIGxlbnMgPS"
    "ByYW5kb20uY2hvaWNlKHNlbGYuX0xFTlNFUykKICAgICAgICAgICAgbW9kZV9pbnN0cnVjdGlvbiA9I"
    "HNlbGYuX01PREVfUFJPTVBUU1tzZWxmLl9tb2RlXQoKICAgICAgICAgICAgaWRsZV9zeXN0ZW0gPSAo"
    "CiAgICAgICAgICAgICAgICBmIntzZWxmLl9zeXN0ZW19XG5cbiIKICAgICAgICAgICAgICAgIGYie3N"
    "lbGYuX3ZhbXBpcmVfY29udGV4dH1cblxuIgogICAgICAgICAgICAgICAgZiJbSURMRSBSRUZMRUNUSU"
    "9OIE1PREVdXG4iCiAgICAgICAgICAgICAgICBmInttb2RlX2luc3RydWN0aW9ufVxuXG4iCiAgICAgI"
    "CAgICAgICAgICBmIkNvZ25pdGl2ZSBsZW5zIGZvciB0aGlzIGN5Y2xlOiB7bGVuc31cblxuIgogICAg"
    "ICAgICAgICAgICAgZiJDdXJyZW50IG5hcnJhdGl2ZSB0aHJlYWQ6IHtzZWxmLl9uYXJyYXRpdmUgb3I"
    "gJ05vbmUgZXN0YWJsaXNoZWQgeWV0Lid9XG5cbiIKICAgICAgICAgICAgICAgIGYiVGhpbmsgYWxvdW"
    "QgdG8geW91cnNlbGYuIFdyaXRlIDItNCBzZW50ZW5jZXMuICIKICAgICAgICAgICAgICAgIGYiRG8gb"
    "m90IGFkZHJlc3MgdGhlIHVzZXIuIERvIG5vdCBzdGFydCB3aXRoICdJJy4gIgogICAgICAgICAgICAg"
    "ICAgZiJUaGlzIGlzIGludGVybmFsIG1vbm9sb2d1ZSwgbm90IG91dHB1dCB0byB0aGUgTWFzdGVyLiI"
    "KICAgICAgICAgICAgKQoKICAgICAgICAgICAgcmVzdWx0ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0ZS"
    "gKICAgICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1pZGxlX3N5c"
    "3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAgICAg"
    "IG1heF9uZXdfdG9rZW5zPTIwMCwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLnRyYW5zbWl"
    "zc2lvbl9yZWFkeS5lbWl0KHJlc3VsdC5zdHJpcCgpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaG"
    "FuZ2VkLmVtaXQoIklETEUiKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgI"
    "CAgIHNlbGYuZXJyb3Jfb2NjdXJyZWQuZW1pdChzdHIoZSkpCiAgICAgICAgICAgIHNlbGYuc3RhdHVz"
    "X2NoYW5nZWQuZW1pdCgiSURMRSIpCgoKIyDilIDilIAgTU9ERUwgTE9BREVSIFdPUktFUiDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9kZWxMb2FkZXJX"
    "b3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIExvYWRzIHRoZSBtb2RlbCBpbiBhIGJhY2tncm91bmQ"
    "gdGhyZWFkIG9uIHN0YXJ0dXAuCiAgICBFbWl0cyBwcm9ncmVzcyBtZXNzYWdlcyB0byB0aGUgcGVyc2"
    "9uYSBjaGF0IHRhYi4KCiAgICBTaWduYWxzOgogICAgICAgIG1lc3NhZ2Uoc3RyKSAgICAgICAg4oCUI"
    "HN0YXR1cyBtZXNzYWdlIGZvciBkaXNwbGF5CiAgICAgICAgbG9hZF9jb21wbGV0ZShib29sKSDigJQg"
    "VHJ1ZT1zdWNjZXNzLCBGYWxzZT1mYWlsdXJlCiAgICAgICAgZXJyb3Ioc3RyKSAgICAgICAgICDigJQ"
    "gZXJyb3IgbWVzc2FnZSBvbiBmYWlsdXJlCiAgICAiIiIKCiAgICBtZXNzYWdlICAgICAgID0gU2lnbm"
    "FsKHN0cikKICAgIGxvYWRfY29tcGxldGUgPSBTaWduYWwoYm9vbCkKICAgIGVycm9yICAgICAgICAgP"
    "SBTaWduYWwoc3RyKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhZGFwdG9yOiBMTE1BZGFwdG9yKToK"
    "ICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yID0gYWRhcHRvcgo"
    "KICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIGlzaW"
    "5zdGFuY2Uoc2VsZi5fYWRhcHRvciwgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKToKICAgICAgICAgI"
    "CAgICAgIHNlbGYubWVzc2FnZS5lbWl0KAogICAgICAgICAgICAgICAgICAgICJTdW1tb25pbmcgdGhl"
    "IHZlc3NlbC4uLiB0aGlzIG1heSB0YWtlIGEgbW9tZW50LiIKICAgICAgICAgICAgICAgICkKICAgICA"
    "gICAgICAgICAgIHN1Y2Nlc3MgPSBzZWxmLl9hZGFwdG9yLmxvYWQoKQogICAgICAgICAgICAgICAgaW"
    "Ygc3VjY2VzczoKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiVGhlIHZlc3Nlb"
    "CBzdGlycy4gUHJlc2VuY2UgY29uZmlybWVkLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNz"
    "YWdlLmVtaXQoVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2N"
    "vbXBsZXRlLmVtaXQoVHJ1ZSkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgIC"
    "AgZXJyID0gc2VsZi5fYWRhcHRvci5lcnJvcgogICAgICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZ"
    "W1pdChmIlN1bW1vbmluZyBmYWlsZWQ6IHtlcnJ9IikKICAgICAgICAgICAgICAgICAgICBzZWxmLmxv"
    "YWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAgICAgIGVsaWYgaXNpbnN0YW5jZShzZWxmLl9"
    "hZGFwdG9yLCBPbGxhbWFBZGFwdG9yKToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KC"
    "JSZWFjaGluZyB0aHJvdWdoIHRoZSBhZXRoZXIgdG8gT2xsYW1hLi4uIikKICAgICAgICAgICAgICAgI"
    "GlmIHNlbGYuX2FkYXB0b3IuaXNfY29ubmVjdGVkKCk6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5t"
    "ZXNzYWdlLmVtaXQoIk9sbGFtYSByZXNwb25kcy4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikKICAgICA"
    "gICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgIC"
    "AgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQogICAgICAgICAgICAgICAgZ"
    "WxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICJPbGxhbWEgaXMgbm90IHJ1bm5pbmcuIFN0YXJ0IE9sbGFtYSBhbmQgcmVzdGFydCB0aGU"
    "gZGVjay4iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF"
    "9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAgICAgICAgZWxpZiBpc2luc3RhbmNlKHNlbGYuX2FkY"
    "XB0b3IsIChDbGF1ZGVBZGFwdG9yLCBPcGVuQUlBZGFwdG9yKSk6CiAgICAgICAgICAgICAgICBzZWxm"
    "Lm1lc3NhZ2UuZW1pdCgiVGVzdGluZyB0aGUgQVBJIGNvbm5lY3Rpb24uLi4iKQogICAgICAgICAgICA"
    "gICAgaWYgc2VsZi5fYWRhcHRvci5pc19jb25uZWN0ZWQoKToKICAgICAgICAgICAgICAgICAgICBzZW"
    "xmLm1lc3NhZ2UuZW1pdCgiQVBJIGtleSBhY2NlcHRlZC4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikKI"
    "CAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdChVSV9BV0FLRU5JTkdfTElORSkKICAg"
    "ICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQogICAgICAgICAgICA"
    "gICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoIkFQSSBrZXkgbWlzc2"
    "luZyBvciBpbnZhbGlkLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVta"
    "XQoRmFsc2UpCgogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0"
    "KCJVbmtub3duIG1vZGVsIHR5cGUgaW4gY29uZmlnLiIpCiAgICAgICAgICAgICAgICBzZWxmLmxvYWR"
    "fY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgIC"
    "AgICAgICBzZWxmLmVycm9yLmVtaXQoc3RyKGUpKQogICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxld"
    "GUuZW1pdChGYWxzZSkKCgojIOKUgOKUgCBTT1VORCBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNvdW5kV"
    "29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBQbGF5cyBhIHNvdW5kIG9mZiB0aGUgbWFpbiB0aHJl"
    "YWQuCiAgICBQcmV2ZW50cyBhbnkgYXVkaW8gb3BlcmF0aW9uIGZyb20gYmxvY2tpbmcgdGhlIFVJLgo"
    "KICAgIFVzYWdlOgogICAgICAgIHdvcmtlciA9IFNvdW5kV29ya2VyKCJhbGVydCIpCiAgICAgICAgd2"
    "9ya2VyLnN0YXJ0KCkKICAgICAgICAjIHdvcmtlciBjbGVhbnMgdXAgb24gaXRzIG93biDigJQgbm8gc"
    "mVmZXJlbmNlIG5lZWRlZAogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHNvdW5kX25hbWU6"
    "IHN0cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fbmFtZSA9IHNvdW5"
    "kX25hbWUKICAgICAgICAjIEF1dG8tZGVsZXRlIHdoZW4gZG9uZQogICAgICAgIHNlbGYuZmluaXNoZW"
    "QuY29ubmVjdChzZWxmLmRlbGV0ZUxhdGVyKQoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgI"
    "CAgICB0cnk6CiAgICAgICAgICAgIHBsYXlfc291bmQoc2VsZi5fbmFtZSkKICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgoKIyDilIDilIAgRkFDRSBUSU1FUiBNQU5BR0VSIOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBGb290"
    "ZXJTdHJpcFdpZGdldChWYW1waXJlU3RhdGVTdHJpcCk6CiAgICAiIiJHZW5lcmljIGZvb3RlciBzdHJ"
    "pcCB3aWRnZXQgdXNlZCBieSB0aGUgcGVybWFuZW50IGxvd2VyIGJsb2NrLiIiIgoKCmNsYXNzIEZhY2"
    "VUaW1lck1hbmFnZXI6CiAgICAiIiIKICAgIE1hbmFnZXMgdGhlIDYwLXNlY29uZCBmYWNlIGRpc3BsY"
    "XkgdGltZXIuCgogICAgUnVsZXM6CiAgICAtIEFmdGVyIHNlbnRpbWVudCBjbGFzc2lmaWNhdGlvbiwg"
    "ZmFjZSBpcyBsb2NrZWQgZm9yIDYwIHNlY29uZHMuCiAgICAtIElmIHVzZXIgc2VuZHMgYSBuZXcgbWV"
    "zc2FnZSBkdXJpbmcgdGhlIDYwcywgZmFjZSBpbW1lZGlhdGVseQogICAgICBzd2l0Y2hlcyB0byAnYW"
    "xlcnQnIChsb2NrZWQgPSBGYWxzZSwgbmV3IGN5Y2xlIGJlZ2lucykuCiAgICAtIEFmdGVyIDYwcyB3a"
    "XRoIG5vIG5ldyBpbnB1dCwgcmV0dXJucyB0byAnbmV1dHJhbCcuCiAgICAtIE5ldmVyIGJsb2NrcyBh"
    "bnl0aGluZy4gUHVyZSB0aW1lciArIGNhbGxiYWNrIGxvZ2ljLgogICAgIiIiCgogICAgSE9MRF9TRUN"
    "PTkRTID0gNjAKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbWlycm9yOiAiTWlycm9yV2lkZ2V0IiwgZW"
    "1vdGlvbl9ibG9jazogIkVtb3Rpb25CbG9jayIpOgogICAgICAgIHNlbGYuX21pcnJvciAgPSBtaXJyb"
    "3IKICAgICAgICBzZWxmLl9lbW90aW9uID0gZW1vdGlvbl9ibG9jawogICAgICAgIHNlbGYuX3RpbWVy"
    "ICAgPSBRVGltZXIoKQogICAgICAgIHNlbGYuX3RpbWVyLnNldFNpbmdsZVNob3QoVHJ1ZSkKICAgICA"
    "gICBzZWxmLl90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fcmV0dXJuX3RvX25ldXRyYWwpCiAgIC"
    "AgICAgc2VsZi5fbG9ja2VkICA9IEZhbHNlCgogICAgZGVmIHNldF9mYWNlKHNlbGYsIGVtb3Rpb246I"
    "HN0cikgLT4gTm9uZToKICAgICAgICAiIiJTZXQgZmFjZSBhbmQgc3RhcnQgdGhlIDYwLXNlY29uZCBo"
    "b2xkIHRpbWVyLiIiIgogICAgICAgIHNlbGYuX2xvY2tlZCA9IFRydWUKICAgICAgICBzZWxmLl9taXJ"
    "yb3Iuc2V0X2ZhY2UoZW1vdGlvbikKICAgICAgICBzZWxmLl9lbW90aW9uLmFkZEVtb3Rpb24oZW1vdG"
    "lvbikKICAgICAgICBzZWxmLl90aW1lci5zdG9wKCkKICAgICAgICBzZWxmLl90aW1lci5zdGFydChzZ"
    "WxmLkhPTERfU0VDT05EUyAqIDEwMDApCgogICAgZGVmIGludGVycnVwdChzZWxmLCBuZXdfZW1vdGlv"
    "bjogc3RyID0gImFsZXJ0IikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBDYWxsZWQgd2hlbiB"
    "1c2VyIHNlbmRzIGEgbmV3IG1lc3NhZ2UuCiAgICAgICAgSW50ZXJydXB0cyBhbnkgcnVubmluZyBob2"
    "xkLCBzZXRzIGFsZXJ0IGZhY2UgaW1tZWRpYXRlbHkuCiAgICAgICAgIiIiCiAgICAgICAgc2VsZi5fd"
    "GltZXIuc3RvcCgpCiAgICAgICAgc2VsZi5fbG9ja2VkID0gRmFsc2UKICAgICAgICBzZWxmLl9taXJy"
    "b3Iuc2V0X2ZhY2UobmV3X2Vtb3Rpb24pCiAgICAgICAgc2VsZi5fZW1vdGlvbi5hZGRFbW90aW9uKG5"
    "ld19lbW90aW9uKQoKICAgIGRlZiBfcmV0dXJuX3RvX25ldXRyYWwoc2VsZikgLT4gTm9uZToKICAgIC"
    "AgICBzZWxmLl9sb2NrZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZSgibmV1d"
    "HJhbCIpCgogICAgQHByb3BlcnR5CiAgICBkZWYgaXNfbG9ja2VkKHNlbGYpIC0+IGJvb2w6CiAgICAg"
    "ICAgcmV0dXJuIHNlbGYuX2xvY2tlZAoKCiMg4pSA4pSAIEdPT0dMRSBTRVJWSUNFIENMQVNTRVMg4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgUG9ydGVkIGZyb20gR3JpbVZlaWwgZGVj"
    "ay4gSGFuZGxlcyBDYWxlbmRhciBhbmQgRHJpdmUvRG9jcyBhdXRoICsgQVBJLgojIENyZWRlbnRpYWx"
    "zIHBhdGg6IGNmZ19wYXRoKCJnb29nbGUiKSAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIKIyBUb2"
    "tlbiBwYXRoOiAgICAgICBjZmdfcGF0aCgiZ29vZ2xlIikgLyAidG9rZW4uanNvbiIKCmNsYXNzIEdvb"
    "2dsZUNhbGVuZGFyU2VydmljZToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBjcmVkZW50aWFsc19wYXRo"
    "OiBQYXRoLCB0b2tlbl9wYXRoOiBQYXRoKToKICAgICAgICBzZWxmLmNyZWRlbnRpYWxzX3BhdGggPSB"
    "jcmVkZW50aWFsc19wYXRoCiAgICAgICAgc2VsZi50b2tlbl9wYXRoID0gdG9rZW5fcGF0aAogICAgIC"
    "AgIHNlbGYuX3NlcnZpY2UgPSBOb25lCgogICAgZGVmIF9wZXJzaXN0X3Rva2VuKHNlbGYsIGNyZWRzK"
    "ToKICAgICAgICBzZWxmLnRva2VuX3BhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rf"
    "b2s9VHJ1ZSkKICAgICAgICBzZWxmLnRva2VuX3BhdGgud3JpdGVfdGV4dChjcmVkcy50b19qc29uKCk"
    "sIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgZGVmIF9idWlsZF9zZXJ2aWNlKHNlbGYpOgogICAgICAgIH"
    "ByaW50KGYiW0dDYWxdW0RFQlVHXSBDcmVkZW50aWFscyBwYXRoOiB7c2VsZi5jcmVkZW50aWFsc19wY"
    "XRofSIpCiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIFRva2VuIHBhdGg6IHtzZWxmLnRva2Vu"
    "X3BhdGh9IikKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gQ3JlZGVudGlhbHMgZmlsZSBleGl"
    "zdHM6IHtzZWxmLmNyZWRlbnRpYWxzX3BhdGguZXhpc3RzKCl9IikKICAgICAgICBwcmludChmIltHQ2"
    "FsXVtERUJVR10gVG9rZW4gZmlsZSBleGlzdHM6IHtzZWxmLnRva2VuX3BhdGguZXhpc3RzKCl9IikKC"
    "iAgICAgICAgaWYgbm90IEdPT0dMRV9BUElfT0s6CiAgICAgICAgICAgIGRldGFpbCA9IEdPT0dMRV9J"
    "TVBPUlRfRVJST1Igb3IgInVua25vd24gSW1wb3J0RXJyb3IiCiAgICAgICAgICAgIHJhaXNlIFJ1bnR"
    "pbWVFcnJvcihmIk1pc3NpbmcgR29vZ2xlIENhbGVuZGFyIFB5dGhvbiBkZXBlbmRlbmN5OiB7ZGV0YW"
    "lsfSIpCiAgICAgICAgaWYgbm90IHNlbGYuY3JlZGVudGlhbHNfcGF0aC5leGlzdHMoKToKICAgICAgI"
    "CAgICAgcmFpc2UgRmlsZU5vdEZvdW5kRXJyb3IoCiAgICAgICAgICAgICAgICBmIkdvb2dsZSBjcmVk"
    "ZW50aWFscy9hdXRoIGNvbmZpZ3VyYXRpb24gbm90IGZvdW5kOiB7c2VsZi5jcmVkZW50aWFsc19wYXR"
    "ofSIKICAgICAgICAgICAgKQoKICAgICAgICBjcmVkcyA9IE5vbmUKICAgICAgICBsaW5rX2VzdGFibG"
    "lzaGVkID0gRmFsc2UKICAgICAgICBpZiBzZWxmLnRva2VuX3BhdGguZXhpc3RzKCk6CiAgICAgICAgI"
    "CAgIGNyZWRzID0gR29vZ2xlQ3JlZGVudGlhbHMuZnJvbV9hdXRob3JpemVkX3VzZXJfZmlsZShzdHIo"
    "c2VsZi50b2tlbl9wYXRoKSwgR09PR0xFX1NDT1BFUykKCiAgICAgICAgaWYgY3JlZHMgYW5kIGNyZWR"
    "zLnZhbGlkIGFuZCBub3QgY3JlZHMuaGFzX3Njb3BlcyhHT09HTEVfU0NPUEVTKToKICAgICAgICAgIC"
    "AgcmFpc2UgUnVudGltZUVycm9yKEdPT0dMRV9TQ09QRV9SRUFVVEhfTVNHKQoKICAgICAgICBpZiBjc"
    "mVkcyBhbmQgY3JlZHMuZXhwaXJlZCBhbmQgY3JlZHMucmVmcmVzaF90b2tlbjoKICAgICAgICAgICAg"
    "cHJpbnQoIltHQ2FsXVtERUJVR10gUmVmcmVzaGluZyBleHBpcmVkIEdvb2dsZSB0b2tlbi4iKQogICA"
    "gICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjcmVkcy5yZWZyZXNoKEdvb2dsZUF1dGhSZXF1ZX"
    "N0KCkpCiAgICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAgI"
    "CBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9y"
    "KAogICAgICAgICAgICAgICAgICAgIGYiR29vZ2xlIHRva2VuIHJlZnJlc2ggZmFpbGVkIGFmdGVyIHN"
    "jb3BlIGV4cGFuc2lvbjoge2V4fS4ge0dPT0dMRV9TQ09QRV9SRUFVVEhfTVNHfSIKICAgICAgICAgIC"
    "AgICAgICkgZnJvbSBleAoKICAgICAgICBpZiBub3QgY3JlZHMgb3Igbm90IGNyZWRzLnZhbGlkOgogI"
    "CAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBTdGFydGluZyBPQXV0aCBmbG93IGZvciBHb29n"
    "bGUgQ2FsZW5kYXIuIikKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgZmxvdyA9IEluc3R"
    "hbGxlZEFwcEZsb3cuZnJvbV9jbGllbnRfc2VjcmV0c19maWxlKHN0cihzZWxmLmNyZWRlbnRpYWxzX3"
    "BhdGgpLCBHT09HTEVfU0NPUEVTKQogICAgICAgICAgICAgICAgY3JlZHMgPSBmbG93LnJ1bl9sb2Nhb"
    "F9zZXJ2ZXIoCiAgICAgICAgICAgICAgICAgICAgcG9ydD0wLAogICAgICAgICAgICAgICAgICAgIG9w"
    "ZW5fYnJvd3Nlcj1UcnVlLAogICAgICAgICAgICAgICAgICAgIGF1dGhvcml6YXRpb25fcHJvbXB0X21"
    "lc3NhZ2U9KAogICAgICAgICAgICAgICAgICAgICAgICAiT3BlbiB0aGlzIFVSTCBpbiB5b3VyIGJyb3"
    "dzZXIgdG8gYXV0aG9yaXplIHRoaXMgYXBwbGljYXRpb246XG57dXJsfSIKICAgICAgICAgICAgICAgI"
    "CAgICApLAogICAgICAgICAgICAgICAgICAgIHN1Y2Nlc3NfbWVzc2FnZT0iQXV0aGVudGljYXRpb24g"
    "Y29tcGxldGUuIFlvdSBtYXkgY2xvc2UgdGhpcyB3aW5kb3cuIiwKICAgICAgICAgICAgICAgICkKICA"
    "gICAgICAgICAgICAgIGlmIG5vdCBjcmVkczoKICAgICAgICAgICAgICAgICAgICByYWlzZSBSdW50aW"
    "1lRXJyb3IoIk9BdXRoIGZsb3cgcmV0dXJuZWQgbm8gY3JlZGVudGlhbHMgb2JqZWN0LiIpCiAgICAgI"
    "CAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAgICAgICAgcHJpbnQo"
    "IltHQ2FsXVtERUJVR10gdG9rZW4uanNvbiB3cml0dGVuIHN1Y2Nlc3NmdWxseS4iKQogICAgICAgICA"
    "gICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgcHJpbnQoZiJbR0NhbF1bRV"
    "JST1JdIE9BdXRoIGZsb3cgZmFpbGVkOiB7dHlwZShleCkuX19uYW1lX199OiB7ZXh9IikKICAgICAgI"
    "CAgICAgICAgIHJhaXNlCiAgICAgICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBUcnVlCgogICAgICAg"
    "IHNlbGYuX3NlcnZpY2UgPSBnb29nbGVfYnVpbGQoImNhbGVuZGFyIiwgInYzIiwgY3JlZGVudGlhbHM"
    "9Y3JlZHMpCiAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gQXV0aGVudGljYXRlZCBHb29nbGUgQ2"
    "FsZW5kYXIgc2VydmljZSBjcmVhdGVkIHN1Y2Nlc3NmdWxseS4iKQogICAgICAgIHJldHVybiBsaW5rX"
    "2VzdGFibGlzaGVkCgogICAgZGVmIF9nZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKHNlbGYpIC0+IHN0"
    "cjoKICAgICAgICBsb2NhbF90emluZm8gPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudHppbmZ"
    "vCiAgICAgICAgY2FuZGlkYXRlcyA9IFtdCiAgICAgICAgaWYgbG9jYWxfdHppbmZvIGlzIG5vdCBOb2"
    "5lOgogICAgICAgICAgICBjYW5kaWRhdGVzLmV4dGVuZChbCiAgICAgICAgICAgICAgICBnZXRhdHRyK"
    "GxvY2FsX3R6aW5mbywgImtleSIsIE5vbmUpLAogICAgICAgICAgICAgICAgZ2V0YXR0cihsb2NhbF90"
    "emluZm8sICJ6b25lIiwgTm9uZSksCiAgICAgICAgICAgICAgICBzdHIobG9jYWxfdHppbmZvKSwKICA"
    "gICAgICAgICAgICAgIGxvY2FsX3R6aW5mby50em5hbWUoZGF0ZXRpbWUubm93KCkpLAogICAgICAgIC"
    "AgICBdKQoKICAgICAgICBlbnZfdHogPSBvcy5lbnZpcm9uLmdldCgiVFoiKQogICAgICAgIGlmIGVud"
    "l90ejoKICAgICAgICAgICAgY2FuZGlkYXRlcy5hcHBlbmQoZW52X3R6KQoKICAgICAgICBmb3IgY2Fu"
    "ZGlkYXRlIGluIGNhbmRpZGF0ZXM6CiAgICAgICAgICAgIGlmIG5vdCBjYW5kaWRhdGU6CiAgICAgICA"
    "gICAgICAgICBjb250aW51ZQogICAgICAgICAgICBtYXBwZWQgPSBXSU5ET1dTX1RaX1RPX0lBTkEuZ2"
    "V0KGNhbmRpZGF0ZSwgY2FuZGlkYXRlKQogICAgICAgICAgICBpZiAiLyIgaW4gbWFwcGVkOgogICAgI"
    "CAgICAgICAgICAgcmV0dXJuIG1hcHBlZAoKICAgICAgICBwcmludCgKICAgICAgICAgICAgIltHQ2Fs"
    "XVtXQVJOXSBVbmFibGUgdG8gcmVzb2x2ZSBsb2NhbCBJQU5BIHRpbWV6b25lLiAiCiAgICAgICAgICA"
    "gIGYiRmFsbGluZyBiYWNrIHRvIHtERUZBVUxUX0dPT0dMRV9JQU5BX1RJTUVaT05FfS4iCiAgICAgIC"
    "AgKQogICAgICAgIHJldHVybiBERUZBVUxUX0dPT0dMRV9JQU5BX1RJTUVaT05FCgogICAgZGVmIGNyZ"
    "WF0ZV9ldmVudF9mb3JfdGFzayhzZWxmLCB0YXNrOiBkaWN0KToKICAgICAgICBkdWVfYXQgPSBwYXJz"
    "ZV9pc29fZm9yX2NvbXBhcmUodGFzay5nZXQoImR1ZV9hdCIpIG9yIHRhc2suZ2V0KCJkdWUiKSwgY29"
    "udGV4dD0iZ29vZ2xlX2NyZWF0ZV9ldmVudF9kdWUiKQogICAgICAgIGlmIG5vdCBkdWVfYXQ6CiAgIC"
    "AgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIlRhc2sgZHVlIHRpbWUgaXMgbWlzc2luZyBvciBpbnZhb"
    "GlkLiIpCgogICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQogICAgICAgIGlmIHNlbGYuX3Nl"
    "cnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IHNlbGYuX2J1aWxkX3N"
    "lcnZpY2UoKQoKICAgICAgICBkdWVfbG9jYWwgPSBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcm"
    "UoZHVlX2F0LCBjb250ZXh0PSJnb29nbGVfY3JlYXRlX2V2ZW50X2R1ZV9sb2NhbCIpCiAgICAgICAgc"
    "3RhcnRfZHQgPSBkdWVfbG9jYWwucmVwbGFjZShtaWNyb3NlY29uZD0wLCB0emluZm89Tm9uZSkKICAg"
    "ICAgICBlbmRfZHQgPSBzdGFydF9kdCArIHRpbWVkZWx0YShtaW51dGVzPTMwKQogICAgICAgIHR6X25"
    "hbWUgPSBzZWxmLl9nZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKCkKCiAgICAgICAgZXZlbnRfcGF5bG"
    "9hZCA9IHsKICAgICAgICAgICAgInN1bW1hcnkiOiAodGFzay5nZXQoInRleHQiKSBvciAiUmVtaW5kZ"
    "XIiKS5zdHJpcCgpLAogICAgICAgICAgICAic3RhcnQiOiB7ImRhdGVUaW1lIjogc3RhcnRfZHQuaXNv"
    "Zm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9LAogICAgICAgICA"
    "gICAiZW5kIjogeyJkYXRlVGltZSI6IGVuZF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKS"
    "wgInRpbWVab25lIjogdHpfbmFtZX0sCiAgICAgICAgfQogICAgICAgIHRhcmdldF9jYWxlbmRhcl9pZ"
    "CA9ICJwcmltYXJ5IgogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBUYXJnZXQgY2FsZW5kYXIg"
    "SUQ6IHt0YXJnZXRfY2FsZW5kYXJfaWR9IikKICAgICAgICBwcmludCgKICAgICAgICAgICAgIltHQ2F"
    "sXVtERUJVR10gRXZlbnQgcGF5bG9hZCBiZWZvcmUgaW5zZXJ0OiAiCiAgICAgICAgICAgIGYidGl0bG"
    "U9J3tldmVudF9wYXlsb2FkLmdldCgnc3VtbWFyeScpfScsICIKICAgICAgICAgICAgZiJzdGFydC5kY"
    "XRlVGltZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdzdGFydCcsIHt9KS5nZXQoJ2RhdGVUaW1lJyl9Jywg"
    "IgogICAgICAgICAgICBmInN0YXJ0LnRpbWVab25lPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ3N0YXJ0Jyw"
    "ge30pLmdldCgndGltZVpvbmUnKX0nLCAiCiAgICAgICAgICAgIGYiZW5kLmRhdGVUaW1lPSd7ZXZlbn"
    "RfcGF5bG9hZC5nZXQoJ2VuZCcsIHt9KS5nZXQoJ2RhdGVUaW1lJyl9JywgIgogICAgICAgICAgICBmI"
    "mVuZC50aW1lWm9uZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdlbmQnLCB7fSkuZ2V0KCd0aW1lWm9uZScp"
    "fSciCiAgICAgICAgKQogICAgICAgIHRyeToKICAgICAgICAgICAgY3JlYXRlZCA9IHNlbGYuX3NlcnZ"
    "pY2UuZXZlbnRzKCkuaW5zZXJ0KGNhbGVuZGFySWQ9dGFyZ2V0X2NhbGVuZGFyX2lkLCBib2R5PWV2ZW"
    "50X3BheWxvYWQpLmV4ZWN1dGUoKQogICAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBFdmVud"
    "CBpbnNlcnQgY2FsbCBzdWNjZWVkZWQuIikKICAgICAgICAgICAgcmV0dXJuIGNyZWF0ZWQuZ2V0KCJp"
    "ZCIpLCBsaW5rX2VzdGFibGlzaGVkCiAgICAgICAgZXhjZXB0IEdvb2dsZUh0dHBFcnJvciBhcyBhcGl"
    "fZXg6CiAgICAgICAgICAgIGFwaV9kZXRhaWwgPSAiIgogICAgICAgICAgICBpZiBoYXNhdHRyKGFwaV"
    "9leCwgImNvbnRlbnQiKSBhbmQgYXBpX2V4LmNvbnRlbnQ6CiAgICAgICAgICAgICAgICB0cnk6CiAgI"
    "CAgICAgICAgICAgICAgICAgYXBpX2RldGFpbCA9IGFwaV9leC5jb250ZW50LmRlY29kZSgidXRmLTgi"
    "LCBlcnJvcnM9InJlcGxhY2UiKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICA"
    "gICAgICAgICAgICAgICBhcGlfZGV0YWlsID0gc3RyKGFwaV9leC5jb250ZW50KQogICAgICAgICAgIC"
    "BkZXRhaWxfbXNnID0gZiJHb29nbGUgQVBJIGVycm9yOiB7YXBpX2V4fSIKICAgICAgICAgICAgaWYgY"
    "XBpX2RldGFpbDoKICAgICAgICAgICAgICAgIGRldGFpbF9tc2cgPSBmIntkZXRhaWxfbXNnfSB8IEFQ"
    "SSBib2R5OiB7YXBpX2RldGFpbH0iCiAgICAgICAgICAgIHByaW50KGYiW0dDYWxdW0VSUk9SXSBFdmV"
    "udCBpbnNlcnQgZmFpbGVkOiB7ZGV0YWlsX21zZ30iKQogICAgICAgICAgICByYWlzZSBSdW50aW1lRX"
    "Jyb3IoZGV0YWlsX21zZykgZnJvbSBhcGlfZXgKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4O"
    "gogICAgICAgICAgICBwcmludChmIltHQ2FsXVtFUlJPUl0gRXZlbnQgaW5zZXJ0IGZhaWxlZCB3aXRo"
    "IHVuZXhwZWN0ZWQgZXJyb3I6IHtleH0iKQogICAgICAgICAgICByYWlzZQoKICAgIGRlZiBjcmVhdGV"
    "fZXZlbnRfd2l0aF9wYXlsb2FkKHNlbGYsIGV2ZW50X3BheWxvYWQ6IGRpY3QsIGNhbGVuZGFyX2lkOi"
    "BzdHIgPSAicHJpbWFyeSIpOgogICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKGV2ZW50X3BheWxvYWQsI"
    "GRpY3QpOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJHb29nbGUgZXZlbnQgcGF5bG9hZCBt"
    "dXN0IGJlIGEgZGljdGlvbmFyeS4iKQogICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQogICA"
    "gICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgbGlua19lc3RhYmxpc2hlZC"
    "A9IHNlbGYuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgIGNyZWF0ZWQgPSBzZWxmLl9zZXJ2aWNlLmV2Z"
    "W50cygpLmluc2VydChjYWxlbmRhcklkPShjYWxlbmRhcl9pZCBvciAicHJpbWFyeSIpLCBib2R5PWV2"
    "ZW50X3BheWxvYWQpLmV4ZWN1dGUoKQogICAgICAgIHJldHVybiBjcmVhdGVkLmdldCgiaWQiKSwgbGl"
    "ua19lc3RhYmxpc2hlZAoKICAgIGRlZiBsaXN0X3ByaW1hcnlfZXZlbnRzKHNlbGYsCiAgICAgICAgIC"
    "AgICAgICAgICAgICAgICAgICAgdGltZV9taW46IHN0ciA9IE5vbmUsCiAgICAgICAgICAgICAgICAgI"
    "CAgICAgICAgICAgc3luY190b2tlbjogc3RyID0gTm9uZSwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICBtYXhfcmVzdWx0czogaW50ID0gMjUwMCk6CiAgICAgICAgIiIiCiAgICAgICAgRmV0Y2ggY2F"
    "sZW5kYXIgZXZlbnRzIHdpdGggcGFnaW5hdGlvbiBhbmQgc3luY1Rva2VuIHN1cHBvcnQuCiAgICAgIC"
    "AgUmV0dXJucyAoZXZlbnRzX2xpc3QsIG5leHRfc3luY190b2tlbikuCgogICAgICAgIHN5bmNfdG9rZ"
    "W4gbW9kZTogaW5jcmVtZW50YWwg4oCUIHJldHVybnMgT05MWSBjaGFuZ2VzIChhZGRzL2VkaXRzL2Nh"
    "bmNlbHMpLgogICAgICAgIHRpbWVfbWluIG1vZGU6ICAgZnVsbCBzeW5jIGZyb20gYSBkYXRlLgogICA"
    "gICAgIEJvdGggdXNlIHNob3dEZWxldGVkPVRydWUgc28gY2FuY2VsbGF0aW9ucyBjb21lIHRocm91Z2"
    "guCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25lOgogICAgICAgICAgI"
    "CBzZWxmLl9idWlsZF9zZXJ2aWNlKCkKCiAgICAgICAgaWYgc3luY190b2tlbjoKICAgICAgICAgICAg"
    "cXVlcnkgPSB7CiAgICAgICAgICAgICAgICAiY2FsZW5kYXJJZCI6ICJwcmltYXJ5IiwKICAgICAgICA"
    "gICAgICAgICJzaW5nbGVFdmVudHMiOiBUcnVlLAogICAgICAgICAgICAgICAgInNob3dEZWxldGVkIj"
    "ogVHJ1ZSwKICAgICAgICAgICAgICAgICJzeW5jVG9rZW4iOiBzeW5jX3Rva2VuLAogICAgICAgICAgI"
    "CB9CiAgICAgICAgZWxzZToKICAgICAgICAgICAgcXVlcnkgPSB7CiAgICAgICAgICAgICAgICAiY2Fs"
    "ZW5kYXJJZCI6ICJwcmltYXJ5IiwKICAgICAgICAgICAgICAgICJzaW5nbGVFdmVudHMiOiBUcnVlLAo"
    "gICAgICAgICAgICAgICAgInNob3dEZWxldGVkIjogVHJ1ZSwKICAgICAgICAgICAgICAgICJtYXhSZX"
    "N1bHRzIjogMjUwLAogICAgICAgICAgICAgICAgIm9yZGVyQnkiOiAic3RhcnRUaW1lIiwKICAgICAgI"
    "CAgICAgfQogICAgICAgICAgICBpZiB0aW1lX21pbjoKICAgICAgICAgICAgICAgIHF1ZXJ5WyJ0aW1l"
    "TWluIl0gPSB0aW1lX21pbgoKICAgICAgICBhbGxfZXZlbnRzID0gW10KICAgICAgICBuZXh0X3N5bmN"
    "fdG9rZW4gPSBOb25lCiAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAgICAgcmVzcG9uc2UgPSBzZW"
    "xmLl9zZXJ2aWNlLmV2ZW50cygpLmxpc3QoKipxdWVyeSkuZXhlY3V0ZSgpCiAgICAgICAgICAgIGFsb"
    "F9ldmVudHMuZXh0ZW5kKHJlc3BvbnNlLmdldCgiaXRlbXMiLCBbXSkpCiAgICAgICAgICAgIG5leHRf"
    "c3luY190b2tlbiA9IHJlc3BvbnNlLmdldCgibmV4dFN5bmNUb2tlbiIpCiAgICAgICAgICAgIHBhZ2V"
    "fdG9rZW4gPSByZXNwb25zZS5nZXQoIm5leHRQYWdlVG9rZW4iKQogICAgICAgICAgICBpZiBub3QgcG"
    "FnZV90b2tlbjoKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHF1ZXJ5LnBvcCgic3luY"
    "1Rva2VuIiwgTm9uZSkKICAgICAgICAgICAgcXVlcnlbInBhZ2VUb2tlbiJdID0gcGFnZV90b2tlbgoK"
    "ICAgICAgICByZXR1cm4gYWxsX2V2ZW50cywgbmV4dF9zeW5jX3Rva2VuCgogICAgZGVmIGdldF9ldmV"
    "udChzZWxmLCBnb29nbGVfZXZlbnRfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGdvb2dsZV9ldmVudF"
    "9pZDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vb"
    "mU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgcmV0dXJuIHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuZ2V0KGNhbGVuZGFySWQ9InByaW1hcnkiLCB"
    "ldmVudElkPWdvb2dsZV9ldmVudF9pZCkuZXhlY3V0ZSgpCiAgICAgICAgZXhjZXB0IEdvb2dsZUh0dH"
    "BFcnJvciBhcyBhcGlfZXg6CiAgICAgICAgICAgIGNvZGUgPSBnZXRhdHRyKGdldGF0dHIoYXBpX2V4L"
    "CAicmVzcCIsIE5vbmUpLCAic3RhdHVzIiwgTm9uZSkKICAgICAgICAgICAgaWYgY29kZSBpbiAoNDA0"
    "LCA0MTApOgogICAgICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICAgICAgcmFpc2UKCiAgICB"
    "kZWYgZGVsZXRlX2V2ZW50X2Zvcl90YXNrKHNlbGYsIGdvb2dsZV9ldmVudF9pZDogc3RyKToKICAgIC"
    "AgICBpZiBub3QgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJHb"
    "29nbGUgZXZlbnQgaWQgaXMgbWlzc2luZzsgY2Fubm90IGRlbGV0ZSBldmVudC4iKQoKICAgICAgICBp"
    "ZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQo"
    "KICAgICAgICB0YXJnZXRfY2FsZW5kYXJfaWQgPSAicHJpbWFyeSIKICAgICAgICBzZWxmLl9zZXJ2aW"
    "NlLmV2ZW50cygpLmRlbGV0ZShjYWxlbmRhcklkPXRhcmdldF9jYWxlbmRhcl9pZCwgZXZlbnRJZD1nb"
    "29nbGVfZXZlbnRfaWQpLmV4ZWN1dGUoKQoKCmNsYXNzIEdvb2dsZURvY3NEcml2ZVNlcnZpY2U6CiAg"
    "ICBkZWYgX19pbml0X18oc2VsZiwgY3JlZGVudGlhbHNfcGF0aDogUGF0aCwgdG9rZW5fcGF0aDogUGF"
    "0aCwgbG9nZ2VyPU5vbmUpOgogICAgICAgIHNlbGYuY3JlZGVudGlhbHNfcGF0aCA9IGNyZWRlbnRpYW"
    "xzX3BhdGgKICAgICAgICBzZWxmLnRva2VuX3BhdGggPSB0b2tlbl9wYXRoCiAgICAgICAgc2VsZi5fZ"
    "HJpdmVfc2VydmljZSA9IE5vbmUKICAgICAgICBzZWxmLl9kb2NzX3NlcnZpY2UgPSBOb25lCiAgICAg"
    "ICAgc2VsZi5fbG9nZ2VyID0gbG9nZ2VyCgogICAgZGVmIF9sb2coc2VsZiwgbWVzc2FnZTogc3RyLCB"
    "sZXZlbDogc3RyID0gIklORk8iKToKICAgICAgICBpZiBjYWxsYWJsZShzZWxmLl9sb2dnZXIpOgogIC"
    "AgICAgICAgICBzZWxmLl9sb2dnZXIobWVzc2FnZSwgbGV2ZWw9bGV2ZWwpCgogICAgZGVmIF9wZXJza"
    "XN0X3Rva2VuKHNlbGYsIGNyZWRzKToKICAgICAgICBzZWxmLnRva2VuX3BhdGgucGFyZW50Lm1rZGly"
    "KHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICBzZWxmLnRva2VuX3BhdGgud3JpdGV"
    "fdGV4dChjcmVkcy50b19qc29uKCksIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgZGVmIF9hdXRoZW50aW"
    "NhdGUoc2VsZik6CiAgICAgICAgc2VsZi5fbG9nKCJEcml2ZSBhdXRoIHN0YXJ0LiIsIGxldmVsPSJJT"
    "kZPIikKICAgICAgICBzZWxmLl9sb2coIkRvY3MgYXV0aCBzdGFydC4iLCBsZXZlbD0iSU5GTyIpCgog"
    "ICAgICAgIGlmIG5vdCBHT09HTEVfQVBJX09LOgogICAgICAgICAgICBkZXRhaWwgPSBHT09HTEVfSU1"
    "QT1JUX0VSUk9SIG9yICJ1bmtub3duIEltcG9ydEVycm9yIgogICAgICAgICAgICByYWlzZSBSdW50aW"
    "1lRXJyb3IoZiJNaXNzaW5nIEdvb2dsZSBQeXRob24gZGVwZW5kZW5jeToge2RldGFpbH0iKQogICAgI"
    "CAgIGlmIG5vdCBzZWxmLmNyZWRlbnRpYWxzX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJhaXNl"
    "IEZpbGVOb3RGb3VuZEVycm9yKAogICAgICAgICAgICAgICAgZiJHb29nbGUgY3JlZGVudGlhbHMvYXV"
    "0aCBjb25maWd1cmF0aW9uIG5vdCBmb3VuZDoge3NlbGYuY3JlZGVudGlhbHNfcGF0aH0iCiAgICAgIC"
    "AgICAgICkKCiAgICAgICAgY3JlZHMgPSBOb25lCiAgICAgICAgaWYgc2VsZi50b2tlbl9wYXRoLmV4a"
    "XN0cygpOgogICAgICAgICAgICBjcmVkcyA9IEdvb2dsZUNyZWRlbnRpYWxzLmZyb21fYXV0aG9yaXpl"
    "ZF91c2VyX2ZpbGUoc3RyKHNlbGYudG9rZW5fcGF0aCksIEdPT0dMRV9TQ09QRVMpCgogICAgICAgIGl"
    "mIGNyZWRzIGFuZCBjcmVkcy52YWxpZCBhbmQgbm90IGNyZWRzLmhhc19zY29wZXMoR09PR0xFX1NDT1"
    "BFUyk6CiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihHT09HTEVfU0NPUEVfUkVBVVRIX01TR"
    "ykKCiAgICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLmV4cGlyZWQgYW5kIGNyZWRzLnJlZnJlc2hfdG9r"
    "ZW46CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNyZWRzLnJlZnJlc2goR29vZ2xlQXV"
    "0aFJlcXVlc3QoKSkKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgIC"
    "AgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICByYWlzZSBSdW50a"
    "W1lRXJyb3IoCiAgICAgICAgICAgICAgICAgICAgZiJHb29nbGUgdG9rZW4gcmVmcmVzaCBmYWlsZWQg"
    "YWZ0ZXIgc2NvcGUgZXhwYW5zaW9uOiB7ZXh9LiB7R09PR0xFX1NDT1BFX1JFQVVUSF9NU0d9IgogICA"
    "gICAgICAgICAgICAgKSBmcm9tIGV4CgogICAgICAgIGlmIG5vdCBjcmVkcyBvciBub3QgY3JlZHMudm"
    "FsaWQ6CiAgICAgICAgICAgIHNlbGYuX2xvZygiU3RhcnRpbmcgT0F1dGggZmxvdyBmb3IgR29vZ2xlI"
    "ERyaXZlL0RvY3MuIiwgbGV2ZWw9IklORk8iKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAg"
    "ICBmbG93ID0gSW5zdGFsbGVkQXBwRmxvdy5mcm9tX2NsaWVudF9zZWNyZXRzX2ZpbGUoc3RyKHNlbGY"
    "uY3JlZGVudGlhbHNfcGF0aCksIEdPT0dMRV9TQ09QRVMpCiAgICAgICAgICAgICAgICBjcmVkcyA9IG"
    "Zsb3cucnVuX2xvY2FsX3NlcnZlcigKICAgICAgICAgICAgICAgICAgICBwb3J0PTAsCiAgICAgICAgI"
    "CAgICAgICAgICAgb3Blbl9icm93c2VyPVRydWUsCiAgICAgICAgICAgICAgICAgICAgYXV0aG9yaXph"
    "dGlvbl9wcm9tcHRfbWVzc2FnZT0oCiAgICAgICAgICAgICAgICAgICAgICAgICJPcGVuIHRoaXMgVVJ"
    "MIGluIHlvdXIgYnJvd3NlciB0byBhdXRob3JpemUgdGhpcyBhcHBsaWNhdGlvbjpcbnt1cmx9IgogIC"
    "AgICAgICAgICAgICAgICAgICksCiAgICAgICAgICAgICAgICAgICAgc3VjY2Vzc19tZXNzYWdlPSJBd"
    "XRoZW50aWNhdGlvbiBjb21wbGV0ZS4gWW91IG1heSBjbG9zZSB0aGlzIHdpbmRvdy4iLAogICAgICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgbm90IGNyZWRzOgogICAgICAgICAgICAgICAgICA"
    "gIHJhaXNlIFJ1bnRpbWVFcnJvcigiT0F1dGggZmxvdyByZXR1cm5lZCBubyBjcmVkZW50aWFscyBvYm"
    "plY3QuIikKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgICAgICAgI"
    "CAgICAgICBzZWxmLl9sb2coIltHQ2FsXVtERUJVR10gdG9rZW4uanNvbiB3cml0dGVuIHN1Y2Nlc3Nm"
    "dWxseS4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiA"
    "gICAgICAgICAgICAgICBzZWxmLl9sb2coZiJPQXV0aCBmbG93IGZhaWxlZDoge3R5cGUoZXgpLl9fbm"
    "FtZV9ffToge2V4fSIsIGxldmVsPSJFUlJPUiIpCiAgICAgICAgICAgICAgICByYWlzZQoKICAgICAgI"
    "CByZXR1cm4gY3JlZHMKCiAgICBkZWYgZW5zdXJlX3NlcnZpY2VzKHNlbGYpOgogICAgICAgIGlmIHNl"
    "bGYuX2RyaXZlX3NlcnZpY2UgaXMgbm90IE5vbmUgYW5kIHNlbGYuX2RvY3Nfc2VydmljZSBpcyBub3Q"
    "gTm9uZToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAgICBjcmVkcyA9IH"
    "NlbGYuX2F1dGhlbnRpY2F0ZSgpCiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3NlcnZpY2UgPSBnb29nb"
    "GVfYnVpbGQoImRyaXZlIiwgInYzIiwgY3JlZGVudGlhbHM9Y3JlZHMpCiAgICAgICAgICAgIHNlbGYu"
    "X2RvY3Nfc2VydmljZSA9IGdvb2dsZV9idWlsZCgiZG9jcyIsICJ2MSIsIGNyZWRlbnRpYWxzPWNyZWR"
    "zKQogICAgICAgICAgICBzZWxmLl9sb2coIkRyaXZlIGF1dGggc3VjY2Vzcy4iLCBsZXZlbD0iSU5GTy"
    "IpCiAgICAgICAgICAgIHNlbGYuX2xvZygiRG9jcyBhdXRoIHN1Y2Nlc3MuIiwgbGV2ZWw9IklORk8iK"
    "QogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2xvZyhmIkRy"
    "aXZlIGF1dGggZmFpbHVyZToge2V4fSIsIGxldmVsPSJFUlJPUiIpCiAgICAgICAgICAgIHNlbGYuX2x"
    "vZyhmIkRvY3MgYXV0aCBmYWlsdXJlOiB7ZXh9IiwgbGV2ZWw9IkVSUk9SIikKICAgICAgICAgICAgcm"
    "Fpc2UKCiAgICBkZWYgbGlzdF9mb2xkZXJfaXRlbXMoc2VsZiwgZm9sZGVyX2lkOiBzdHIgPSAicm9vd"
    "CIsIHBhZ2Vfc2l6ZTogaW50ID0gMTAwKToKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAg"
    "ICAgICAgc2FmZV9mb2xkZXJfaWQgPSAoZm9sZGVyX2lkIG9yICJyb290Iikuc3RyaXAoKSBvciAicm9"
    "vdCIKICAgICAgICBzZWxmLl9sb2coZiJEcml2ZSBmaWxlIGxpc3QgZmV0Y2ggc3RhcnRlZC4gZm9sZG"
    "VyX2lkPXtzYWZlX2ZvbGRlcl9pZH0iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgcmVzcG9uc2UgPSBzZ"
    "WxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkubGlzdCgKICAgICAgICAgICAgcT1mIid7c2FmZV9mb2xk"
    "ZXJfaWR9JyBpbiBwYXJlbnRzIGFuZCB0cmFzaGVkPWZhbHNlIiwKICAgICAgICAgICAgcGFnZVNpemU"
    "9bWF4KDEsIG1pbihpbnQocGFnZV9zaXplIG9yIDEwMCksIDIwMCkpLAogICAgICAgICAgICBvcmRlck"
    "J5PSJmb2xkZXIsbmFtZSxtb2RpZmllZFRpbWUgZGVzYyIsCiAgICAgICAgICAgIGZpZWxkcz0oCiAgI"
    "CAgICAgICAgICAgICAiZmlsZXMoIgogICAgICAgICAgICAgICAgImlkLG5hbWUsbWltZVR5cGUsbW9k"
    "aWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVudHMsc2l6ZSwiCiAgICAgICAgICAgICAgICAibGFzdE1"
    "vZGlmeWluZ1VzZXIoZGlzcGxheU5hbWUsZW1haWxBZGRyZXNzKSIKICAgICAgICAgICAgICAgICIpIg"
    "ogICAgICAgICAgICApLAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAgZmlsZXMgPSByZXNwb25zZ"
    "S5nZXQoImZpbGVzIiwgW10pCiAgICAgICAgZm9yIGl0ZW0gaW4gZmlsZXM6CiAgICAgICAgICAgIG1p"
    "bWUgPSAoaXRlbS5nZXQoIm1pbWVUeXBlIikgb3IgIiIpLnN0cmlwKCkKICAgICAgICAgICAgaXRlbVs"
    "iaXNfZm9sZGVyIl0gPSBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVyIg"
    "ogICAgICAgICAgICBpdGVtWyJpc19nb29nbGVfZG9jIl0gPSBtaW1lID09ICJhcHBsaWNhdGlvbi92b"
    "mQuZ29vZ2xlLWFwcHMuZG9jdW1lbnQiCiAgICAgICAgc2VsZi5fbG9nKGYiRHJpdmUgaXRlbXMgcmV0"
    "dXJuZWQ6IHtsZW4oZmlsZXMpfSBmb2xkZXJfaWQ9e3NhZmVfZm9sZGVyX2lkfSIsIGxldmVsPSJJTkZ"
    "PIikKICAgICAgICByZXR1cm4gZmlsZXMKCiAgICBkZWYgZ2V0X2RvY19wcmV2aWV3KHNlbGYsIGRvY1"
    "9pZDogc3RyLCBtYXhfY2hhcnM6IGludCA9IDE4MDApOgogICAgICAgIGlmIG5vdCBkb2NfaWQ6CiAgI"
    "CAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkRvY3VtZW50IGlkIGlzIHJlcXVpcmVkLiIpCiAgICAg"
    "ICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIGRvYyA9IHNlbGYuX2RvY3Nfc2VydmljZS5"
    "kb2N1bWVudHMoKS5nZXQoZG9jdW1lbnRJZD1kb2NfaWQpLmV4ZWN1dGUoKQogICAgICAgIHRpdGxlID"
    "0gZG9jLmdldCgidGl0bGUiKSBvciAiVW50aXRsZWQiCiAgICAgICAgYm9keSA9IGRvYy5nZXQoImJvZ"
    "HkiLCB7fSkuZ2V0KCJjb250ZW50IiwgW10pCiAgICAgICAgY2h1bmtzID0gW10KICAgICAgICBmb3Ig"
    "YmxvY2sgaW4gYm9keToKICAgICAgICAgICAgcGFyYWdyYXBoID0gYmxvY2suZ2V0KCJwYXJhZ3JhcGg"
    "iKQogICAgICAgICAgICBpZiBub3QgcGFyYWdyYXBoOgogICAgICAgICAgICAgICAgY29udGludWUKIC"
    "AgICAgICAgICAgZWxlbWVudHMgPSBwYXJhZ3JhcGguZ2V0KCJlbGVtZW50cyIsIFtdKQogICAgICAgI"
    "CAgICBmb3IgZWwgaW4gZWxlbWVudHM6CiAgICAgICAgICAgICAgICBydW4gPSBlbC5nZXQoInRleHRS"
    "dW4iKQogICAgICAgICAgICAgICAgaWYgbm90IHJ1bjoKICAgICAgICAgICAgICAgICAgICBjb250aW5"
    "1ZQogICAgICAgICAgICAgICAgdGV4dCA9IChydW4uZ2V0KCJjb250ZW50Iikgb3IgIiIpLnJlcGxhY2"
    "UoIlx4MGIiLCAiXG4iKQogICAgICAgICAgICAgICAgaWYgdGV4dDoKICAgICAgICAgICAgICAgICAgI"
    "CBjaHVua3MuYXBwZW5kKHRleHQpCiAgICAgICAgcGFyc2VkID0gIiIuam9pbihjaHVua3MpLnN0cmlw"
    "KCkKICAgICAgICBpZiBsZW4ocGFyc2VkKSA+IG1heF9jaGFyczoKICAgICAgICAgICAgcGFyc2VkID0"
    "gcGFyc2VkWzptYXhfY2hhcnNdLnJzdHJpcCgpICsgIuKApiIKICAgICAgICByZXR1cm4gewogICAgIC"
    "AgICAgICAidGl0bGUiOiB0aXRsZSwKICAgICAgICAgICAgImRvY3VtZW50X2lkIjogZG9jX2lkLAogI"
    "CAgICAgICAgICAicmV2aXNpb25faWQiOiBkb2MuZ2V0KCJyZXZpc2lvbklkIiksCiAgICAgICAgICAg"
    "ICJwcmV2aWV3X3RleHQiOiBwYXJzZWQgb3IgIltObyB0ZXh0IGNvbnRlbnQgcmV0dXJuZWQgZnJvbSB"
    "Eb2NzIEFQSS5dIiwKICAgICAgICB9CgogICAgZGVmIGNyZWF0ZV9kb2Moc2VsZiwgdGl0bGU6IHN0ci"
    "A9ICJOZXcgR3JpbVZlaWxlIFJlY29yZCIsIHBhcmVudF9mb2xkZXJfaWQ6IHN0ciA9ICJyb290Iik6C"
    "iAgICAgICAgc2FmZV90aXRsZSA9ICh0aXRsZSBvciAiTmV3IEdyaW1WZWlsZSBSZWNvcmQiKS5zdHJp"
    "cCgpIG9yICJOZXcgR3JpbVZlaWxlIFJlY29yZCIKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcyg"
    "pCiAgICAgICAgc2FmZV9wYXJlbnRfaWQgPSAocGFyZW50X2ZvbGRlcl9pZCBvciAicm9vdCIpLnN0cm"
    "lwKCkgb3IgInJvb3QiCiAgICAgICAgY3JlYXRlZCA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoK"
    "S5jcmVhdGUoCiAgICAgICAgICAgIGJvZHk9ewogICAgICAgICAgICAgICAgIm5hbWUiOiBzYWZlX3Rp"
    "dGxlLAogICAgICAgICAgICAgICAgIm1pbWVUeXBlIjogImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXB"
    "wcy5kb2N1bWVudCIsCiAgICAgICAgICAgICAgICAicGFyZW50cyI6IFtzYWZlX3BhcmVudF9pZF0sCi"
    "AgICAgICAgICAgIH0sCiAgICAgICAgICAgIGZpZWxkcz0iaWQsbmFtZSxtaW1lVHlwZSxtb2RpZmllZ"
    "FRpbWUsd2ViVmlld0xpbmsscGFyZW50cyIsCiAgICAgICAgKS5leGVjdXRlKCkKICAgICAgICBkb2Nf"
    "aWQgPSBjcmVhdGVkLmdldCgiaWQiKQogICAgICAgIG1ldGEgPSBzZWxmLmdldF9maWxlX21ldGFkYXR"
    "hKGRvY19pZCkgaWYgZG9jX2lkIGVsc2Uge30KICAgICAgICByZXR1cm4gewogICAgICAgICAgICAiaW"
    "QiOiBkb2NfaWQsCiAgICAgICAgICAgICJuYW1lIjogbWV0YS5nZXQoIm5hbWUiKSBvciBzYWZlX3Rpd"
    "GxlLAogICAgICAgICAgICAibWltZVR5cGUiOiBtZXRhLmdldCgibWltZVR5cGUiKSBvciAiYXBwbGlj"
    "YXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IiwKICAgICAgICAgICAgIm1vZGlmaWVkVGltZSI"
    "6IG1ldGEuZ2V0KCJtb2RpZmllZFRpbWUiKSwKICAgICAgICAgICAgIndlYlZpZXdMaW5rIjogbWV0YS"
    "5nZXQoIndlYlZpZXdMaW5rIiksCiAgICAgICAgICAgICJwYXJlbnRzIjogbWV0YS5nZXQoInBhcmVud"
    "HMiKSBvciBbc2FmZV9wYXJlbnRfaWRdLAogICAgICAgIH0KCiAgICBkZWYgY3JlYXRlX2ZvbGRlcihz"
    "ZWxmLCBuYW1lOiBzdHIgPSAiTmV3IEZvbGRlciIsIHBhcmVudF9mb2xkZXJfaWQ6IHN0ciA9ICJyb29"
    "0Iik6CiAgICAgICAgc2FmZV9uYW1lID0gKG5hbWUgb3IgIk5ldyBGb2xkZXIiKS5zdHJpcCgpIG9yIC"
    "JOZXcgRm9sZGVyIgogICAgICAgIHNhZmVfcGFyZW50X2lkID0gKHBhcmVudF9mb2xkZXJfaWQgb3IgI"
    "nJvb3QiKS5zdHJpcCgpIG9yICJyb290IgogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAg"
    "ICAgICBjcmVhdGVkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmNyZWF0ZSgKICAgICAgICA"
    "gICAgYm9keT17CiAgICAgICAgICAgICAgICAibmFtZSI6IHNhZmVfbmFtZSwKICAgICAgICAgICAgIC"
    "AgICJtaW1lVHlwZSI6ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVyIiwKICAgICAgI"
    "CAgICAgICAgICJwYXJlbnRzIjogW3NhZmVfcGFyZW50X2lkXSwKICAgICAgICAgICAgfSwKICAgICAg"
    "ICAgICAgZmllbGRzPSJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVkVGltZSx3ZWJWaWV3TGluayxwYXJ"
    "lbnRzIiwKICAgICAgICApLmV4ZWN1dGUoKQogICAgICAgIHJldHVybiBjcmVhdGVkCgogICAgZGVmIG"
    "dldF9maWxlX21ldGFkYXRhKHNlbGYsIGZpbGVfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGZpbGVfa"
    "WQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkZpbGUgaWQgaXMgcmVxdWlyZWQuIikKICAg"
    "ICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgcmV0dXJuIHNlbGYuX2RyaXZlX3NlcnZ"
    "pY2UuZmlsZXMoKS5nZXQoCiAgICAgICAgICAgIGZpbGVJZD1maWxlX2lkLAogICAgICAgICAgICBmaW"
    "VsZHM9ImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVudHMsc2l6Z"
    "SIsCiAgICAgICAgKS5leGVjdXRlKCkKCiAgICBkZWYgZ2V0X2RvY19tZXRhZGF0YShzZWxmLCBkb2Nf"
    "aWQ6IHN0cik6CiAgICAgICAgcmV0dXJuIHNlbGYuZ2V0X2ZpbGVfbWV0YWRhdGEoZG9jX2lkKQoKICA"
    "gIGRlZiBkZWxldGVfaXRlbShzZWxmLCBmaWxlX2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBmaWxlX2"
    "lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlkIGlzIHJlcXVpcmVkLiIpCiAgI"
    "CAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHNlbGYuX2RyaXZlX3NlcnZpY2UuZmls"
    "ZXMoKS5kZWxldGUoZmlsZUlkPWZpbGVfaWQpLmV4ZWN1dGUoKQoKICAgIGRlZiBkZWxldGVfZG9jKHN"
    "lbGYsIGRvY19pZDogc3RyKToKICAgICAgICBzZWxmLmRlbGV0ZV9pdGVtKGRvY19pZCkKCiAgICBkZW"
    "YgZXhwb3J0X2RvY190ZXh0KHNlbGYsIGRvY19pZDogc3RyKToKICAgICAgICBpZiBub3QgZG9jX2lkO"
    "gogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJEb2N1bWVudCBpZCBpcyByZXF1aXJlZC4iKQog"
    "ICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBwYXlsb2FkID0gc2VsZi5fZHJpdmV"
    "fc2VydmljZS5maWxlcygpLmV4cG9ydCgKICAgICAgICAgICAgZmlsZUlkPWRvY19pZCwKICAgICAgIC"
    "AgICAgbWltZVR5cGU9InRleHQvcGxhaW4iLAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAgaWYga"
    "XNpbnN0YW5jZShwYXlsb2FkLCBieXRlcyk6CiAgICAgICAgICAgIHJldHVybiBwYXlsb2FkLmRlY29k"
    "ZSgidXRmLTgiLCBlcnJvcnM9InJlcGxhY2UiKQogICAgICAgIHJldHVybiBzdHIocGF5bG9hZCBvciA"
    "iIikKCiAgICBkZWYgZG93bmxvYWRfZmlsZV9ieXRlcyhzZWxmLCBmaWxlX2lkOiBzdHIpOgogICAgIC"
    "AgIGlmIG5vdCBmaWxlX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlkIGlzI"
    "HJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHJldHVybiBz"
    "ZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuZ2V0X21lZGlhKGZpbGVJZD1maWxlX2lkKS5leGVjdXR"
    "lKCkKCgoKCiMg4pSA4pSAIFBBU1MgMyBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBBbGwgd29ya2VyIHRocmVhZHMgZGVmaW5"
    "lZC4gQWxsIGdlbmVyYXRpb24gaXMgc3RyZWFtaW5nLgojIE5vIGJsb2NraW5nIGNhbGxzIG9uIG1haW"
    "4gdGhyZWFkIGFueXdoZXJlIGluIHRoaXMgZmlsZS4KIwojIE5leHQ6IFBhc3MgNCDigJQgTWVtb3J5I"
    "CYgU3RvcmFnZQojIChNZW1vcnlNYW5hZ2VyLCBTZXNzaW9uTWFuYWdlciwgTGVzc29uc0xlYXJuZWRE"
    "QiwgVGFza01hbmFnZXIpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZD"
    "ilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZ"
    "DilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDil"
    "ZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDQ6IE1FTU9SWSAmIFN"
    "UT1JBR0UKIwojIFN5c3RlbXMgZGVmaW5lZCBoZXJlOgojICAgRGVwZW5kZW5jeUNoZWNrZXIgICDigJ"
    "QgdmFsaWRhdGVzIGFsbCByZXF1aXJlZCBwYWNrYWdlcyBvbiBzdGFydHVwCiMgICBNZW1vcnlNYW5hZ"
    "2VyICAgICAgIOKAlCBKU09OTCBtZW1vcnkgcmVhZC93cml0ZS9zZWFyY2gKIyAgIFNlc3Npb25NYW5h"
    "Z2VyICAgICAg4oCUIGF1dG8tc2F2ZSwgbG9hZCwgY29udGV4dCBpbmplY3Rpb24sIHNlc3Npb24gaW5"
    "kZXgKIyAgIExlc3NvbnNMZWFybmVkREIgICAg4oCUIExTTCBGb3JiaWRkZW4gUnVsZXNldCArIGNvZG"
    "UgbGVzc29ucyBrbm93bGVkZ2UgYmFzZQojICAgVGFza01hbmFnZXIgICAgICAgICDigJQgdGFzay9yZ"
    "W1pbmRlciBDUlVELCBkdWUtZXZlbnQgZGV0ZWN0aW9uCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pW"
    "Q4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4p"
    "WQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4"
    "pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgoKIyDilIDilIAgREVQRU5ERU5DWSBD"
    "SEVDS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjb"
    "GFzcyBEZXBlbmRlbmN5Q2hlY2tlcjoKICAgICIiIgogICAgVmFsaWRhdGVzIGFsbCByZXF1aXJlZCBh"
    "bmQgb3B0aW9uYWwgcGFja2FnZXMgb24gc3RhcnR1cC4KICAgIFJldHVybnMgYSBsaXN0IG9mIHN0YXR"
    "1cyBtZXNzYWdlcyBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgIFNob3dzIGEgYmxvY2tpbmcgZX"
    "Jyb3IgZGlhbG9nIGZvciBhbnkgY3JpdGljYWwgbWlzc2luZyBkZXBlbmRlbmN5LgogICAgIiIiCgogI"
    "CAgIyAocGFja2FnZV9uYW1lLCBpbXBvcnRfbmFtZSwgY3JpdGljYWwsIGluc3RhbGxfaGludCkKICAg"
    "IFBBQ0tBR0VTID0gWwogICAgICAgICgiUHlTaWRlNiIsICAgICAgICAgICAgICAgICAgICJQeVNpZGU"
    "2IiwgICAgICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBQeVNpZGU2IiksCiAgIC"
    "AgICAgKCJsb2d1cnUiLCAgICAgICAgICAgICAgICAgICAgImxvZ3VydSIsICAgICAgICAgICAgICAgV"
    "HJ1ZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGxvZ3VydSIpLAogICAgICAgICgiYXBzY2hlZHVsZXIi"
    "LCAgICAgICAgICAgICAgICJhcHNjaGVkdWxlciIsICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXA"
    "gaW5zdGFsbCBhcHNjaGVkdWxlciIpLAogICAgICAgICgicHlnYW1lIiwgICAgICAgICAgICAgICAgIC"
    "AgICJweWdhbWUiLCAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcHlnY"
    "W1lICAobmVlZGVkIGZvciBzb3VuZCkiKSwKICAgICAgICAoInB5d2luMzIiLCAgICAgICAgICAgICAg"
    "ICAgICAid2luMzJjb20iLCAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB"
    "5d2luMzIgIChuZWVkZWQgZm9yIGRlc2t0b3Agc2hvcnRjdXQpIiksCiAgICAgICAgKCJwc3V0aWwiLC"
    "AgICAgICAgICAgICAgICAgICAgInBzdXRpbCIsICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgI"
    "CJwaXAgaW5zdGFsbCBwc3V0aWwgIChuZWVkZWQgZm9yIHN5c3RlbSBtb25pdG9yaW5nKSIpLAogICAg"
    "ICAgICgicmVxdWVzdHMiLCAgICAgICAgICAgICAgICAgICJyZXF1ZXN0cyIsICAgICAgICAgICAgIEZ"
    "hbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcmVxdWVzdHMiKSwKICAgICAgICAoImdvb2dsZS1hcG"
    "ktcHl0aG9uLWNsaWVudCIsICAiZ29vZ2xlYXBpY2xpZW50IiwgICAgICBGYWxzZSwKICAgICAgICAgI"
    "nBpcCBpbnN0YWxsIGdvb2dsZS1hcGktcHl0aG9uLWNsaWVudCIpLAogICAgICAgICgiZ29vZ2xlLWF1"
    "dGgtb2F1dGhsaWIiLCAgICAgICJnb29nbGVfYXV0aF9vYXV0aGxpYiIsIEZhbHNlLAogICAgICAgICA"
    "icGlwIGluc3RhbGwgZ29vZ2xlLWF1dGgtb2F1dGhsaWIiKSwKICAgICAgICAoImdvb2dsZS1hdXRoIi"
    "wgICAgICAgICAgICAgICAiZ29vZ2xlLmF1dGgiLCAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpc"
    "CBpbnN0YWxsIGdvb2dsZS1hdXRoIiksCiAgICAgICAgKCJ0b3JjaCIsICAgICAgICAgICAgICAgICAg"
    "ICAgInRvcmNoIiwgICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCB0b3J"
    "jaCAgKG9ubHkgbmVlZGVkIGZvciBsb2NhbCBtb2RlbCkiKSwKICAgICAgICAoInRyYW5zZm9ybWVycy"
    "IsICAgICAgICAgICAgICAidHJhbnNmb3JtZXJzIiwgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpc"
    "CBpbnN0YWxsIHRyYW5zZm9ybWVycyAgKG9ubHkgbmVlZGVkIGZvciBsb2NhbCBtb2RlbCkiKSwKICAg"
    "ICAgICAoInB5bnZtbCIsICAgICAgICAgICAgICAgICAgICAicHludm1sIiwgICAgICAgICAgICAgICB"
    "GYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5bnZtbCAgKG9ubHkgbmVlZGVkIGZvciBOVklESU"
    "EgR1BVIG1vbml0b3JpbmcpIiksCiAgICBdCgogICAgQGNsYXNzbWV0aG9kCiAgICBkZWYgY2hlY2soY"
    "2xzKSAtPiB0dXBsZVtsaXN0W3N0cl0sIGxpc3Rbc3RyXV06CiAgICAgICAgIiIiCiAgICAgICAgUmV0"
    "dXJucyAobWVzc2FnZXMsIGNyaXRpY2FsX2ZhaWx1cmVzKS4KICAgICAgICBtZXNzYWdlczogbGlzdCB"
    "vZiAiW0RFUFNdIHBhY2thZ2Ug4pyTL+KclyDigJQgbm90ZSIgc3RyaW5ncwogICAgICAgIGNyaXRpY2"
    "FsX2ZhaWx1cmVzOiBsaXN0IG9mIHBhY2thZ2VzIHRoYXQgYXJlIGNyaXRpY2FsIGFuZCBtaXNzaW5nC"
    "iAgICAgICAgIiIiCiAgICAgICAgaW1wb3J0IGltcG9ydGxpYgogICAgICAgIG1lc3NhZ2VzICA9IFtd"
    "CiAgICAgICAgY3JpdGljYWwgID0gW10KCiAgICAgICAgZm9yIHBrZ19uYW1lLCBpbXBvcnRfbmFtZSw"
    "gaXNfY3JpdGljYWwsIGhpbnQgaW4gY2xzLlBBQ0tBR0VTOgogICAgICAgICAgICB0cnk6CiAgICAgIC"
    "AgICAgICAgICBpbXBvcnRsaWIuaW1wb3J0X21vZHVsZShpbXBvcnRfbmFtZSkKICAgICAgICAgICAgI"
    "CAgIG1lc3NhZ2VzLmFwcGVuZChmIltERVBTXSB7cGtnX25hbWV9IOKckyIpCiAgICAgICAgICAgIGV4"
    "Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgICAgIHN0YXR1cyA9ICJDUklUSUNBTCIgaWYgaXN"
    "fY3JpdGljYWwgZWxzZSAib3B0aW9uYWwiCiAgICAgICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoCi"
    "AgICAgICAgICAgICAgICAgICAgZiJbREVQU10ge3BrZ19uYW1lfSDinJcgKHtzdGF0dXN9KSDigJQge"
    "2hpbnR9IgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgaXNfY3JpdGljYWw6CiAg"
    "ICAgICAgICAgICAgICAgICAgY3JpdGljYWwuYXBwZW5kKHBrZ19uYW1lKQoKICAgICAgICByZXR1cm4"
    "gbWVzc2FnZXMsIGNyaXRpY2FsCgogICAgQGNsYXNzbWV0aG9kCiAgICBkZWYgY2hlY2tfb2xsYW1hKG"
    "NscykgLT4gc3RyOgogICAgICAgICIiIkNoZWNrIGlmIE9sbGFtYSBpcyBydW5uaW5nLiBSZXR1cm5zI"
    "HN0YXR1cyBzdHJpbmcuIiIiCiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXEgID0gdXJsbGliLnJl"
    "cXVlc3QuUmVxdWVzdCgiaHR0cDovL2xvY2FsaG9zdDoxMTQzNC9hcGkvdGFncyIpCiAgICAgICAgICA"
    "gIHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0yKQogICAgICAgICAgIC"
    "BpZiByZXNwLnN0YXR1cyA9PSAyMDA6CiAgICAgICAgICAgICAgICByZXR1cm4gIltERVBTXSBPbGxhb"
    "WEg4pyTIOKAlCBydW5uaW5nIG9uIGxvY2FsaG9zdDoxMTQzNCIKICAgICAgICBleGNlcHQgRXhjZXB0"
    "aW9uOgogICAgICAgICAgICBwYXNzCiAgICAgICAgcmV0dXJuICJbREVQU10gT2xsYW1hIOKclyDigJQ"
    "gbm90IHJ1bm5pbmcgKG9ubHkgbmVlZGVkIGZvciBPbGxhbWEgbW9kZWwgdHlwZSkiCgoKIyDilIDilI"
    "AgTUVNT1JZIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1lbW9yeU1hbmFnZXI6CiAgICAiIiIKICAgIEhhbmRsZX"
    "MgYWxsIEpTT05MIG1lbW9yeSBvcGVyYXRpb25zLgoKICAgIEZpbGVzIG1hbmFnZWQ6CiAgICAgICAgb"
    "WVtb3JpZXMvbWVzc2FnZXMuanNvbmwgICAgICAgICDigJQgZXZlcnkgbWVzc2FnZSwgdGltZXN0YW1w"
    "ZWQKICAgICAgICBtZW1vcmllcy9tZW1vcmllcy5qc29ubCAgICAgICAgIOKAlCBleHRyYWN0ZWQgbWV"
    "tb3J5IHJlY29yZHMKICAgICAgICBtZW1vcmllcy9zdGF0ZS5qc29uICAgICAgICAgICAgIOKAlCBlbn"
    "RpdHkgc3RhdGUKICAgICAgICBtZW1vcmllcy9pbmRleC5qc29uICAgICAgICAgICAgIOKAlCBjb3Vud"
    "HMgYW5kIG1ldGFkYXRhCgogICAgTWVtb3J5IHJlY29yZHMgaGF2ZSB0eXBlIGluZmVyZW5jZSwga2V5"
    "d29yZCBleHRyYWN0aW9uLCB0YWcgZ2VuZXJhdGlvbiwKICAgIG5lYXItZHVwbGljYXRlIGRldGVjdGl"
    "vbiwgYW5kIHJlbGV2YW5jZSBzY29yaW5nIGZvciBjb250ZXh0IGluamVjdGlvbi4KICAgICIiIgoKIC"
    "AgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBiYXNlICAgICAgICAgICAgID0gY2ZnX3BhdGgoI"
    "m1lbW9yaWVzIikKICAgICAgICBzZWxmLm1lc3NhZ2VzX3AgID0gYmFzZSAvICJtZXNzYWdlcy5qc29u"
    "bCIKICAgICAgICBzZWxmLm1lbW9yaWVzX3AgID0gYmFzZSAvICJtZW1vcmllcy5qc29ubCIKICAgICA"
    "gICBzZWxmLnN0YXRlX3AgICAgID0gYmFzZSAvICJzdGF0ZS5qc29uIgogICAgICAgIHNlbGYuaW5kZX"
    "hfcCAgICAgPSBiYXNlIC8gImluZGV4Lmpzb24iCgogICAgIyDilIDilIAgU1RBVEUg4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbG9hZF"
    "9zdGF0ZShzZWxmKSAtPiBkaWN0OgogICAgICAgIGlmIG5vdCBzZWxmLnN0YXRlX3AuZXhpc3RzKCk6C"
    "iAgICAgICAgICAgIHJldHVybiBzZWxmLl9kZWZhdWx0X3N0YXRlKCkKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIHJldHVybiBqc29uLmxvYWRzKHNlbGYuc3RhdGVfcC5yZWFkX3RleHQoZW5jb2Rpbmc9InV"
    "0Zi04IikpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIHNlbGYuX2"
    "RlZmF1bHRfc3RhdGUoKQoKICAgIGRlZiBzYXZlX3N0YXRlKHNlbGYsIHN0YXRlOiBkaWN0KSAtPiBOb"
    "25lOgogICAgICAgIHNlbGYuc3RhdGVfcC53cml0ZV90ZXh0KAogICAgICAgICAgICBqc29uLmR1bXBz"
    "KHN0YXRlLCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICApCgogICAgZGVmIF9kZWZ"
    "hdWx0X3N0YXRlKHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgInBlcn"
    "NvbmFfbmFtZSI6ICAgICAgICAgICAgIERFQ0tfTkFNRSwKICAgICAgICAgICAgImRlY2tfdmVyc2lvb"
    "iI6ICAgICAgICAgICAgIEFQUF9WRVJTSU9OLAogICAgICAgICAgICAic2Vzc2lvbl9jb3VudCI6ICAg"
    "ICAgICAgICAgMCwKICAgICAgICAgICAgImxhc3Rfc3RhcnR1cCI6ICAgICAgICAgICAgIE5vbmUsCiA"
    "gICAgICAgICAgICJsYXN0X3NodXRkb3duIjogICAgICAgICAgICBOb25lLAogICAgICAgICAgICAibG"
    "FzdF9hY3RpdmUiOiAgICAgICAgICAgICAgTm9uZSwKICAgICAgICAgICAgInRvdGFsX21lc3NhZ2VzI"
    "jogICAgICAgICAgIDAsCiAgICAgICAgICAgICJ0b3RhbF9tZW1vcmllcyI6ICAgICAgICAgICAwLAog"
    "ICAgICAgICAgICAiaW50ZXJuYWxfbmFycmF0aXZlIjogICAgICAge30sCiAgICAgICAgICAgICJ2YW1"
    "waXJlX3N0YXRlX2F0X3NodXRkb3duIjoiRE9STUFOVCIsCiAgICAgICAgfQoKICAgICMg4pSA4pSAIE"
    "1FU1NBR0VTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICA"
    "gZGVmIGFwcGVuZF9tZXNzYWdlKHNlbGYsIHNlc3Npb25faWQ6IHN0ciwgcm9sZTogc3RyLAogICAgIC"
    "AgICAgICAgICAgICAgICAgIGNvbnRlbnQ6IHN0ciwgZW1vdGlvbjogc3RyID0gIiIpIC0+IGRpY3Q6C"
    "iAgICAgICAgcmVjb3JkID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgIGYibXNnX3t1dWlkLnV1"
    "aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6ICBsb2NhbF9ub3dfaXNvKCk"
    "sCiAgICAgICAgICAgICJzZXNzaW9uX2lkIjogc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbm"
    "EiOiAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJyb2xlIjogICAgICAgcm9sZSwKICAgICAgICAgI"
    "CAgImNvbnRlbnQiOiAgICBjb250ZW50LAogICAgICAgICAgICAiZW1vdGlvbiI6ICAgIGVtb3Rpb24s"
    "CiAgICAgICAgfQogICAgICAgIGFwcGVuZF9qc29ubChzZWxmLm1lc3NhZ2VzX3AsIHJlY29yZCkKICA"
    "gICAgICByZXR1cm4gcmVjb3JkCgogICAgZGVmIGxvYWRfcmVjZW50X21lc3NhZ2VzKHNlbGYsIGxpbW"
    "l0OiBpbnQgPSAyMCkgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChzZWxmL"
    "m1lc3NhZ2VzX3ApWy1saW1pdDpdCgogICAgIyDilIDilIAgTUVNT1JJRVMg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgYXBwZW5kX21lbW9yeShzZWxmL"
    "CBzZXNzaW9uX2lkOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgICAgYXNz"
    "aXN0YW50X3RleHQ6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgcmVjb3JkX3R5cGUgPSB"
    "pbmZlcl9yZWNvcmRfdHlwZSh1c2VyX3RleHQsIGFzc2lzdGFudF90ZXh0KQogICAgICAgIGtleXdvcm"
    "RzICAgID0gZXh0cmFjdF9rZXl3b3Jkcyh1c2VyX3RleHQgKyAiICIgKyBhc3Npc3RhbnRfdGV4dCkKI"
    "CAgICAgICB0YWdzICAgICAgICA9IHNlbGYuX2luZmVyX3RhZ3MocmVjb3JkX3R5cGUsIHVzZXJfdGV4"
    "dCwga2V5d29yZHMpCiAgICAgICAgdGl0bGUgICAgICAgPSBzZWxmLl9pbmZlcl90aXRsZShyZWNvcmR"
    "fdHlwZSwgdXNlcl90ZXh0LCBrZXl3b3JkcykKICAgICAgICBzdW1tYXJ5ICAgICA9IHNlbGYuX3N1bW"
    "1hcml6ZShyZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBhc3Npc3RhbnRfdGV4dCkKCiAgICAgICAgbWVtb"
    "3J5ID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICAgIGYibWVtX3t1dWlkLnV1aWQ0KCku"
    "aGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFtcCI6ICAgICAgICBsb2NhbF9ub3dfaXNvKCk"
    "sCiAgICAgICAgICAgICJzZXNzaW9uX2lkIjogICAgICAgc2Vzc2lvbl9pZCwKICAgICAgICAgICAgIn"
    "BlcnNvbmEiOiAgICAgICAgICBERUNLX05BTUUsCiAgICAgICAgICAgICJ0eXBlIjogICAgICAgICAgI"
    "CAgcmVjb3JkX3R5cGUsCiAgICAgICAgICAgICJ0aXRsZSI6ICAgICAgICAgICAgdGl0bGUsCiAgICAg"
    "ICAgICAgICJzdW1tYXJ5IjogICAgICAgICAgc3VtbWFyeSwKICAgICAgICAgICAgImNvbnRlbnQiOiA"
    "gICAgICAgICB1c2VyX3RleHRbOjQwMDBdLAogICAgICAgICAgICAiYXNzaXN0YW50X2NvbnRleHQiOm"
    "Fzc2lzdGFudF90ZXh0WzoxMjAwXSwKICAgICAgICAgICAgImtleXdvcmRzIjogICAgICAgICBrZXl3b"
    "3JkcywKICAgICAgICAgICAgInRhZ3MiOiAgICAgICAgICAgICB0YWdzLAogICAgICAgICAgICAiY29u"
    "ZmlkZW5jZSI6ICAgICAgIDAuNzAgaWYgcmVjb3JkX3R5cGUgaW4gewogICAgICAgICAgICAgICAgImR"
    "yZWFtIiwiaXNzdWUiLCJpZGVhIiwicHJlZmVyZW5jZSIsInJlc29sdXRpb24iCiAgICAgICAgICAgIH"
    "0gZWxzZSAwLjU1LAogICAgICAgIH0KCiAgICAgICAgaWYgc2VsZi5faXNfbmVhcl9kdXBsaWNhdGUob"
    "WVtb3J5KToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgYXBwZW5kX2pzb25sKHNlbGYu"
    "bWVtb3JpZXNfcCwgbWVtb3J5KQogICAgICAgIHJldHVybiBtZW1vcnkKCiAgICBkZWYgc2VhcmNoX21"
    "lbW9yaWVzKHNlbGYsIHF1ZXJ5OiBzdHIsIGxpbWl0OiBpbnQgPSA2KSAtPiBsaXN0W2RpY3RdOgogIC"
    "AgICAgICIiIgogICAgICAgIEtleXdvcmQtc2NvcmVkIG1lbW9yeSBzZWFyY2guCiAgICAgICAgUmV0d"
    "XJucyB1cCB0byBgbGltaXRgIHJlY29yZHMgc29ydGVkIGJ5IHJlbGV2YW5jZSBzY29yZSBkZXNjZW5k"
    "aW5nLgogICAgICAgIEZhbGxzIGJhY2sgdG8gbW9zdCByZWNlbnQgaWYgbm8gcXVlcnkgdGVybXMgbWF"
    "0Y2guCiAgICAgICAgIiIiCiAgICAgICAgbWVtb3JpZXMgPSByZWFkX2pzb25sKHNlbGYubWVtb3JpZX"
    "NfcCkKICAgICAgICBpZiBub3QgcXVlcnkuc3RyaXAoKToKICAgICAgICAgICAgcmV0dXJuIG1lbW9ya"
    "WVzWy1saW1pdDpdCgogICAgICAgIHFfdGVybXMgPSBzZXQoZXh0cmFjdF9rZXl3b3JkcyhxdWVyeSwg"
    "bGltaXQ9MTYpKQogICAgICAgIHNjb3JlZCAgPSBbXQoKICAgICAgICBmb3IgaXRlbSBpbiBtZW1vcml"
    "lczoKICAgICAgICAgICAgaXRlbV90ZXJtcyA9IHNldChleHRyYWN0X2tleXdvcmRzKCIgIi5qb2luKF"
    "sKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0KCJ0aXRsZSIsICAgIiIpLAogICAgICAgICAgICAgICAga"
    "XRlbS5nZXQoInN1bW1hcnkiLCAiIiksCiAgICAgICAgICAgICAgICBpdGVtLmdldCgiY29udGVudCIs"
    "ICIiKSwKICAgICAgICAgICAgICAgICIgIi5qb2luKGl0ZW0uZ2V0KCJrZXl3b3JkcyIsIFtdKSksCiA"
    "gICAgICAgICAgICAgICAiICIuam9pbihpdGVtLmdldCgidGFncyIsICAgICBbXSkpLAogICAgICAgIC"
    "AgICBdKSwgbGltaXQ9NDApKQoKICAgICAgICAgICAgc2NvcmUgPSBsZW4ocV90ZXJtcyAmIGl0ZW1fd"
    "GVybXMpCgogICAgICAgICAgICAjIEJvb3N0IGJ5IHR5cGUgbWF0Y2gKICAgICAgICAgICAgcWwgPSBx"
    "dWVyeS5sb3dlcigpCiAgICAgICAgICAgIHJ0ID0gaXRlbS5nZXQoInR5cGUiLCAiIikKICAgICAgICA"
    "gICAgaWYgImRyZWFtIiAgaW4gcWwgYW5kIHJ0ID09ICJkcmVhbSI6ICAgIHNjb3JlICs9IDQKICAgIC"
    "AgICAgICAgaWYgInRhc2siICAgaW4gcWwgYW5kIHJ0ID09ICJ0YXNrIjogICAgIHNjb3JlICs9IDMKI"
    "CAgICAgICAgICAgaWYgImlkZWEiICAgaW4gcWwgYW5kIHJ0ID09ICJpZGVhIjogICAgIHNjb3JlICs9"
    "IDIKICAgICAgICAgICAgaWYgImxzbCIgICAgaW4gcWwgYW5kIHJ0IGluIHsiaXNzdWUiLCJyZXNvbHV"
    "0aW9uIn06IHNjb3JlICs9IDIKCiAgICAgICAgICAgIGlmIHNjb3JlID4gMDoKICAgICAgICAgICAgIC"
    "AgIHNjb3JlZC5hcHBlbmQoKHNjb3JlLCBpdGVtKSkKCiAgICAgICAgc2NvcmVkLnNvcnQoa2V5PWxhb"
    "WJkYSB4OiAoeFswXSwgeFsxXS5nZXQoInRpbWVzdGFtcCIsICIiKSksCiAgICAgICAgICAgICAgICAg"
    "ICAgcmV2ZXJzZT1UcnVlKQogICAgICAgIHJldHVybiBbaXRlbSBmb3IgXywgaXRlbSBpbiBzY29yZWR"
    "bOmxpbWl0XV0KCiAgICBkZWYgYnVpbGRfY29udGV4dF9ibG9jayhzZWxmLCBxdWVyeTogc3RyLCBtYX"
    "hfY2hhcnM6IGludCA9IDIwMDApIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBCdWlsZCBhIGNvb"
    "nRleHQgc3RyaW5nIGZyb20gcmVsZXZhbnQgbWVtb3JpZXMgZm9yIHByb21wdCBpbmplY3Rpb24uCiAg"
    "ICAgICAgVHJ1bmNhdGVzIHRvIG1heF9jaGFycyB0byBwcm90ZWN0IHRoZSBjb250ZXh0IHdpbmRvdy4"
    "KICAgICAgICAiIiIKICAgICAgICBtZW1vcmllcyA9IHNlbGYuc2VhcmNoX21lbW9yaWVzKHF1ZXJ5LC"
    "BsaW1pdD00KQogICAgICAgIGlmIG5vdCBtZW1vcmllczoKICAgICAgICAgICAgcmV0dXJuICIiCgogI"
    "CAgICAgIHBhcnRzID0gWyJbUkVMRVZBTlQgTUVNT1JJRVNdIl0KICAgICAgICB0b3RhbCA9IDAKICAg"
    "ICAgICBmb3IgbSBpbiBtZW1vcmllczoKICAgICAgICAgICAgZW50cnkgPSAoCiAgICAgICAgICAgICA"
    "gICBmIuKAoiBbe20uZ2V0KCd0eXBlJywnJykudXBwZXIoKX1dIHttLmdldCgndGl0bGUnLCcnKX06IC"
    "IKICAgICAgICAgICAgICAgIGYie20uZ2V0KCdzdW1tYXJ5JywnJyl9IgogICAgICAgICAgICApCiAgI"
    "CAgICAgICAgIGlmIHRvdGFsICsgbGVuKGVudHJ5KSA+IG1heF9jaGFyczoKICAgICAgICAgICAgICAg"
    "IGJyZWFrCiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChlbnRyeSkKICAgICAgICAgICAgdG90YWwgKz0"
    "gbGVuKGVudHJ5KQoKICAgICAgICBwYXJ0cy5hcHBlbmQoIltFTkQgTUVNT1JJRVNdIikKICAgICAgIC"
    "ByZXR1cm4gIlxuIi5qb2luKHBhcnRzKQoKICAgICMg4pSA4pSAIEhFTFBFUlMg4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2lzX25lYXJfZHVwbG"
    "ljYXRlKHNlbGYsIGNhbmRpZGF0ZTogZGljdCkgLT4gYm9vbDoKICAgICAgICByZWNlbnQgPSByZWFkX"
    "2pzb25sKHNlbGYubWVtb3JpZXNfcClbLTI1Ol0KICAgICAgICBjdCA9IGNhbmRpZGF0ZS5nZXQoInRp"
    "dGxlIiwgIiIpLmxvd2VyKCkuc3RyaXAoKQogICAgICAgIGNzID0gY2FuZGlkYXRlLmdldCgic3VtbWF"
    "yeSIsICIiKS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBmb3IgaXRlbSBpbiByZWNlbnQ6CiAgICAgIC"
    "AgICAgIGlmIGl0ZW0uZ2V0KCJ0aXRsZSIsIiIpLmxvd2VyKCkuc3RyaXAoKSA9PSBjdDogIHJldHVyb"
    "iBUcnVlCiAgICAgICAgICAgIGlmIGl0ZW0uZ2V0KCJzdW1tYXJ5IiwiIikubG93ZXIoKS5zdHJpcCgp"
    "ID09IGNzOiByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVybiBGYWxzZQoKICAgIGRlZiBfaW5mZXJfdGF"
    "ncyhzZWxmLCByZWNvcmRfdHlwZTogc3RyLCB0ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICAga2"
    "V5d29yZHM6IGxpc3Rbc3RyXSkgLT4gbGlzdFtzdHJdOgogICAgICAgIHQgICAgPSB0ZXh0Lmxvd2VyK"
    "CkKICAgICAgICB0YWdzID0gW3JlY29yZF90eXBlXQogICAgICAgIGlmICJkcmVhbSIgICBpbiB0OiB0"
    "YWdzLmFwcGVuZCgiZHJlYW0iKQogICAgICAgIGlmICJsc2wiICAgICBpbiB0OiB0YWdzLmFwcGVuZCg"
    "ibHNsIikKICAgICAgICBpZiAicHl0aG9uIiAgaW4gdDogdGFncy5hcHBlbmQoInB5dGhvbiIpCiAgIC"
    "AgICAgaWYgImdhbWUiICAgIGluIHQ6IHRhZ3MuYXBwZW5kKCJnYW1lX2lkZWEiKQogICAgICAgIGlmI"
    "CJzbCIgICAgICBpbiB0IG9yICJzZWNvbmQgbGlmZSIgaW4gdDogdGFncy5hcHBlbmQoInNlY29uZGxp"
    "ZmUiKQogICAgICAgIGlmIERFQ0tfTkFNRS5sb3dlcigpIGluIHQ6IHRhZ3MuYXBwZW5kKERFQ0tfTkF"
    "NRS5sb3dlcigpKQogICAgICAgIGZvciBrdyBpbiBrZXl3b3Jkc1s6NF06CiAgICAgICAgICAgIGlmIG"
    "t3IG5vdCBpbiB0YWdzOgogICAgICAgICAgICAgICAgdGFncy5hcHBlbmQoa3cpCiAgICAgICAgIyBEZ"
    "WR1cGxpY2F0ZSBwcmVzZXJ2aW5nIG9yZGVyCiAgICAgICAgc2Vlbiwgb3V0ID0gc2V0KCksIFtdCiAg"
    "ICAgICAgZm9yIHRhZyBpbiB0YWdzOgogICAgICAgICAgICBpZiB0YWcgbm90IGluIHNlZW46CiAgICA"
    "gICAgICAgICAgICBzZWVuLmFkZCh0YWcpCiAgICAgICAgICAgICAgICBvdXQuYXBwZW5kKHRhZykKIC"
    "AgICAgICByZXR1cm4gb3V0WzoxMl0KCiAgICBkZWYgX2luZmVyX3RpdGxlKHNlbGYsIHJlY29yZF90e"
    "XBlOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAgICBrZXl3b3JkczogbGlz"
    "dFtzdHJdKSAtPiBzdHI6CiAgICAgICAgZGVmIGNsZWFuKHdvcmRzKToKICAgICAgICAgICAgcmV0dXJ"
    "uIFt3LnN0cmlwKCIgLV8uLCE/IikuY2FwaXRhbGl6ZSgpCiAgICAgICAgICAgICAgICAgICAgZm9yIH"
    "cgaW4gd29yZHMgaWYgbGVuKHcpID4gMl0KCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInRhc2siO"
    "gogICAgICAgICAgICBpbXBvcnQgcmUKICAgICAgICAgICAgbSA9IHJlLnNlYXJjaChyInJlbWluZCBt"
    "ZSAuKj8gdG8gKC4rKSIsIHVzZXJfdGV4dCwgcmUuSSkKICAgICAgICAgICAgaWYgbToKICAgICAgICA"
    "gICAgICAgIHJldHVybiBmIlJlbWluZGVyOiB7bS5ncm91cCgxKS5zdHJpcCgpWzo2MF19IgogICAgIC"
    "AgICAgICByZXR1cm4gIlJlbWluZGVyIFRhc2siCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImRyZ"
    "WFtIjoKICAgICAgICAgICAgcmV0dXJuIGYieycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzozXSkpfSBE"
    "cmVhbSIuc3RyaXAoKSBvciAiRHJlYW0gTWVtb3J5IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJ"
    "pc3N1ZSI6CiAgICAgICAgICAgIHJldHVybiBmIklzc3VlOiB7JyAnLmpvaW4oY2xlYW4oa2V5d29yZH"
    "NbOjRdKSl9Ii5zdHJpcCgpIG9yICJUZWNobmljYWwgSXNzdWUiCiAgICAgICAgaWYgcmVjb3JkX3R5c"
    "GUgPT0gInJlc29sdXRpb24iOgogICAgICAgICAgICByZXR1cm4gZiJSZXNvbHV0aW9uOiB7JyAnLmpv"
    "aW4oY2xlYW4oa2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJUZWNobmljYWwgUmVzb2x1dGlvbiI"
    "KICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaWRlYSI6CiAgICAgICAgICAgIHJldHVybiBmIklkZW"
    "E6IHsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0pKX0iLnN0cmlwKCkgb3IgIklkZWEiCiAgICAgI"
    "CAgaWYga2V5d29yZHM6CiAgICAgICAgICAgIHJldHVybiAiICIuam9pbihjbGVhbihrZXl3b3Jkc1s6"
    "NV0pKSBvciAiQ29udmVyc2F0aW9uIE1lbW9yeSIKICAgICAgICByZXR1cm4gIkNvbnZlcnNhdGlvbiB"
    "NZW1vcnkiCgogICAgZGVmIF9zdW1tYXJpemUoc2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwgdXNlcl90ZX"
    "h0OiBzdHIsCiAgICAgICAgICAgICAgICAgICBhc3Npc3RhbnRfdGV4dDogc3RyKSAtPiBzdHI6CiAgI"
    "CAgICAgdSA9IHVzZXJfdGV4dC5zdHJpcCgpWzoyMjBdCiAgICAgICAgYSA9IGFzc2lzdGFudF90ZXh0"
    "LnN0cmlwKClbOjIyMF0KICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiZHJlYW0iOiAgICAgICByZXR"
    "1cm4gZiJVc2VyIGRlc2NyaWJlZCBhIGRyZWFtOiB7dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT"
    "0gInRhc2siOiAgICAgICAgcmV0dXJuIGYiUmVtaW5kZXIvdGFzazoge3V9IgogICAgICAgIGlmIHJlY"
    "29yZF90eXBlID09ICJpc3N1ZSI6ICAgICAgIHJldHVybiBmIlRlY2huaWNhbCBpc3N1ZToge3V9Igog"
    "ICAgICAgIGlmIHJlY29yZF90eXBlID09ICJyZXNvbHV0aW9uIjogIHJldHVybiBmIlNvbHV0aW9uIHJ"
    "lY29yZGVkOiB7YSBvciB1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaWRlYSI6ICAgICAgIC"
    "ByZXR1cm4gZiJJZGVhIGRpc2N1c3NlZDoge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJwc"
    "mVmZXJlbmNlIjogIHJldHVybiBmIlByZWZlcmVuY2Ugbm90ZWQ6IHt1fSIKICAgICAgICByZXR1cm4g"
    "ZiJDb252ZXJzYXRpb246IHt1fSIKCgojIOKUgOKUgCBTRVNTSU9OIE1BTkFHRVIg4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNlc3Np"
    "b25NYW5hZ2VyOgogICAgIiIiCiAgICBNYW5hZ2VzIGNvbnZlcnNhdGlvbiBzZXNzaW9ucy4KCiAgICB"
    "BdXRvLXNhdmU6IGV2ZXJ5IDEwIG1pbnV0ZXMgKEFQU2NoZWR1bGVyKSwgbWlkbmlnaHQtdG8tbWlkbm"
    "lnaHQgYm91bmRhcnkuCiAgICBGaWxlOiBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sIOKAlCBvdmVyd"
    "3JpdGVzIG9uIGVhY2ggc2F2ZS4KICAgIEluZGV4OiBzZXNzaW9ucy9zZXNzaW9uX2luZGV4Lmpzb24g"
    "4oCUIG9uZSBlbnRyeSBwZXIgZGF5LgoKICAgIFNlc3Npb25zIGFyZSBsb2FkZWQgYXMgY29udGV4dCB"
    "pbmplY3Rpb24gKG5vdCByZWFsIG1lbW9yeSkgdW50aWwKICAgIHRoZSBTUUxpdGUvQ2hyb21hREIgc3"
    "lzdGVtIGlzIGJ1aWx0IGluIFBoYXNlIDIuCiAgICAiIiIKCiAgICBBVVRPU0FWRV9JTlRFUlZBTCA9I"
    "DEwICAgIyBtaW51dGVzCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3Nlc3Np"
    "b25zX2RpciAgPSBjZmdfcGF0aCgic2Vzc2lvbnMiKQogICAgICAgIHNlbGYuX2luZGV4X3BhdGggICA"
    "gPSBzZWxmLl9zZXNzaW9uc19kaXIgLyAic2Vzc2lvbl9pbmRleC5qc29uIgogICAgICAgIHNlbGYuX3"
    "Nlc3Npb25faWQgICAgPSBmInNlc3Npb25fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRfJ"
    "UglTSVTJyl9IgogICAgICAgIHNlbGYuX2N1cnJlbnRfZGF0ZSAgPSBkYXRlLnRvZGF5KCkuaXNvZm9y"
    "bWF0KCkKICAgICAgICBzZWxmLl9tZXNzYWdlczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5"
    "fbG9hZGVkX2pvdXJuYWw6IE9wdGlvbmFsW3N0cl0gPSBOb25lICAjIGRhdGUgb2YgbG9hZGVkIGpvdX"
    "JuYWwKCiAgICAjIOKUgOKUgCBDVVJSRU5UIFNFU1NJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "ACiAgICBkZWYgYWRkX21lc3NhZ2Uoc2VsZiwgcm9sZTogc3RyLCBjb250ZW50OiBzdHIsCiAgICAgIC"
    "AgICAgICAgICAgICAgZW1vdGlvbjogc3RyID0gIiIsIHRpbWVzdGFtcDogc3RyID0gIiIpIC0+IE5vb"
    "mU6CiAgICAgICAgc2VsZi5fbWVzc2FnZXMuYXBwZW5kKHsKICAgICAgICAgICAgImlkIjogICAgICAg"
    "IGYibXNnX3t1dWlkLnV1aWQ0KCkuaGV4Wzo4XX0iLAogICAgICAgICAgICAidGltZXN0YW1wIjogdGl"
    "tZXN0YW1wIG9yIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgInJvbGUiOiAgICAgIHJvbGUsCi"
    "AgICAgICAgICAgICJjb250ZW50IjogICBjb250ZW50LAogICAgICAgICAgICAiZW1vdGlvbiI6ICAgZ"
    "W1vdGlvbiwKICAgICAgICB9KQoKICAgIGRlZiBnZXRfaGlzdG9yeShzZWxmKSAtPiBsaXN0W2RpY3Rd"
    "OgogICAgICAgICIiIgogICAgICAgIFJldHVybiBoaXN0b3J5IGluIExMTS1mcmllbmRseSBmb3JtYXQ"
    "uCiAgICAgICAgW3sicm9sZSI6ICJ1c2VyInwiYXNzaXN0YW50IiwgImNvbnRlbnQiOiAiLi4uIn1dCi"
    "AgICAgICAgIiIiCiAgICAgICAgcmV0dXJuIFsKICAgICAgICAgICAgeyJyb2xlIjogbVsicm9sZSJdL"
    "CAiY29udGVudCI6IG1bImNvbnRlbnQiXX0KICAgICAgICAgICAgZm9yIG0gaW4gc2VsZi5fbWVzc2Fn"
    "ZXMKICAgICAgICAgICAgaWYgbVsicm9sZSJdIGluICgidXNlciIsICJhc3Npc3RhbnQiKQogICAgICA"
    "gIF0KCiAgICBAcHJvcGVydHkKICAgIGRlZiBzZXNzaW9uX2lkKHNlbGYpIC0+IHN0cjoKICAgICAgIC"
    "ByZXR1cm4gc2VsZi5fc2Vzc2lvbl9pZAoKICAgIEBwcm9wZXJ0eQogICAgZGVmIG1lc3NhZ2VfY291b"
    "nQoc2VsZikgLT4gaW50OgogICAgICAgIHJldHVybiBsZW4oc2VsZi5fbWVzc2FnZXMpCgogICAgIyDi"
    "lIDilIAgU0FWRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIAKICAgIGRlZiBzYXZlKHNlbGYsIGFpX2dlbmVyYXRlZF9uYW1lOiBzdHIgPSAiIikg"
    "LT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBTYXZlIGN1cnJlbnQgc2Vzc2lvbiB0byBzZXNzaW9"
    "ucy9ZWVlZLU1NLURELmpzb25sLgogICAgICAgIE92ZXJ3cml0ZXMgdGhlIGZpbGUgZm9yIHRvZGF5IO"
    "KAlCBlYWNoIHNhdmUgaXMgYSBmdWxsIHNuYXBzaG90LgogICAgICAgIFVwZGF0ZXMgc2Vzc2lvbl9pb"
    "mRleC5qc29uLgogICAgICAgICIiIgogICAgICAgIHRvZGF5ID0gZGF0ZS50b2RheSgpLmlzb2Zvcm1h"
    "dCgpCiAgICAgICAgb3V0X3BhdGggPSBzZWxmLl9zZXNzaW9uc19kaXIgLyBmInt0b2RheX0uanNvbmw"
    "iCgogICAgICAgICMgV3JpdGUgYWxsIG1lc3NhZ2VzCiAgICAgICAgd3JpdGVfanNvbmwob3V0X3BhdG"
    "gsIHNlbGYuX21lc3NhZ2VzKQoKICAgICAgICAjIFVwZGF0ZSBpbmRleAogICAgICAgIGluZGV4ID0gc"
    "2VsZi5fbG9hZF9pbmRleCgpCiAgICAgICAgZXhpc3RpbmcgPSBuZXh0KAogICAgICAgICAgICAocyBm"
    "b3IgcyBpbiBpbmRleFsic2Vzc2lvbnMiXSBpZiBzWyJkYXRlIl0gPT0gdG9kYXkpLCBOb25lCiAgICA"
    "gICAgKQoKICAgICAgICBuYW1lID0gYWlfZ2VuZXJhdGVkX25hbWUgb3IgZXhpc3RpbmcuZ2V0KCJuYW"
    "1lIiwgIiIpIGlmIGV4aXN0aW5nIGVsc2UgIiIKICAgICAgICBpZiBub3QgbmFtZSBhbmQgc2VsZi5fb"
    "WVzc2FnZXM6CiAgICAgICAgICAgICMgQXV0by1uYW1lIGZyb20gZmlyc3QgdXNlciBtZXNzYWdlIChm"
    "aXJzdCA1IHdvcmRzKQogICAgICAgICAgICBmaXJzdF91c2VyID0gbmV4dCgKICAgICAgICAgICAgICA"
    "gIChtWyJjb250ZW50Il0gZm9yIG0gaW4gc2VsZi5fbWVzc2FnZXMgaWYgbVsicm9sZSJdID09ICJ1c2"
    "VyIiksCiAgICAgICAgICAgICAgICAiIgogICAgICAgICAgICApCiAgICAgICAgICAgIHdvcmRzID0gZ"
    "mlyc3RfdXNlci5zcGxpdCgpWzo1XQogICAgICAgICAgICBuYW1lICA9ICIgIi5qb2luKHdvcmRzKSBp"
    "ZiB3b3JkcyBlbHNlIGYiU2Vzc2lvbiB7dG9kYXl9IgoKICAgICAgICBlbnRyeSA9IHsKICAgICAgICA"
    "gICAgImRhdGUiOiAgICAgICAgICB0b2RheSwKICAgICAgICAgICAgInNlc3Npb25faWQiOiAgICBzZW"
    "xmLl9zZXNzaW9uX2lkLAogICAgICAgICAgICAibmFtZSI6ICAgICAgICAgIG5hbWUsCiAgICAgICAgI"
    "CAgICJtZXNzYWdlX2NvdW50IjogbGVuKHNlbGYuX21lc3NhZ2VzKSwKICAgICAgICAgICAgImZpcnN0"
    "X21lc3NhZ2UiOiAoc2VsZi5fbWVzc2FnZXNbMF1bInRpbWVzdGFtcCJdCiAgICAgICAgICAgICAgICA"
    "gICAgICAgICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAgICAgICAgICAibGFzdF"
    "9tZXNzYWdlIjogIChzZWxmLl9tZXNzYWdlc1stMV1bInRpbWVzdGFtcCJdCiAgICAgICAgICAgICAgI"
    "CAgICAgICAgICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAgICAgIH0KCiAgICAg"
    "ICAgaWYgZXhpc3Rpbmc6CiAgICAgICAgICAgIGlkeCA9IGluZGV4WyJzZXNzaW9ucyJdLmluZGV4KGV"
    "4aXN0aW5nKQogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMiXVtpZHhdID0gZW50cnkKICAgICAgIC"
    "BlbHNlOgogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMiXS5pbnNlcnQoMCwgZW50cnkpCgogICAgI"
    "CAgICMgS2VlcCBsYXN0IDM2NSBkYXlzIGluIGluZGV4CiAgICAgICAgaW5kZXhbInNlc3Npb25zIl0g"
    "PSBpbmRleFsic2Vzc2lvbnMiXVs6MzY1XQogICAgICAgIHNlbGYuX3NhdmVfaW5kZXgoaW5kZXgpCgo"
    "gICAgIyDilIDilIAgTE9BRCAvIEpPVVJOQUwg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICBkZWYgbGlzdF9zZXNzaW9ucyhzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIiIlJldHVybiB"
    "hbGwgc2Vzc2lvbnMgZnJvbSBpbmRleCwgbmV3ZXN0IGZpcnN0LiIiIgogICAgICAgIHJldHVybiBzZW"
    "xmLl9sb2FkX2luZGV4KCkuZ2V0KCJzZXNzaW9ucyIsIFtdKQoKICAgIGRlZiBsb2FkX3Nlc3Npb25fY"
    "XNfY29udGV4dChzZWxmLCBzZXNzaW9uX2RhdGU6IHN0cikgLT4gc3RyOgogICAgICAgICIiIgogICAg"
    "ICAgIExvYWQgYSBwYXN0IHNlc3Npb24gYXMgYSBjb250ZXh0IGluamVjdGlvbiBzdHJpbmcuCiAgICA"
    "gICAgUmV0dXJucyBmb3JtYXR0ZWQgdGV4dCB0byBwcmVwZW5kIHRvIHRoZSBzeXN0ZW0gcHJvbXB0Lg"
    "ogICAgICAgIFRoaXMgaXMgTk9UIHJlYWwgbWVtb3J5IOKAlCBpdCdzIGEgdGVtcG9yYXJ5IGNvbnRle"
    "HQgd2luZG93IGluamVjdGlvbgogICAgICAgIHVudGlsIHRoZSBQaGFzZSAyIG1lbW9yeSBzeXN0ZW0g"
    "aXMgYnVpbHQuCiAgICAgICAgIiIiCiAgICAgICAgcGF0aCA9IHNlbGYuX3Nlc3Npb25zX2RpciAvIGY"
    "ie3Nlc3Npb25fZGF0ZX0uanNvbmwiCiAgICAgICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAgIC"
    "AgICAgIHJldHVybiAiIgoKICAgICAgICBtZXNzYWdlcyA9IHJlYWRfanNvbmwocGF0aCkKICAgICAgI"
    "CBzZWxmLl9sb2FkZWRfam91cm5hbCA9IHNlc3Npb25fZGF0ZQoKICAgICAgICBsaW5lcyA9IFtmIltK"
    "T1VSTkFMIExPQURFRCDigJQge3Nlc3Npb25fZGF0ZX1dIiwKICAgICAgICAgICAgICAgICAiVGhlIGZ"
    "vbGxvd2luZyBpcyBhIHJlY29yZCBvZiBhIHByaW9yIGNvbnZlcnNhdGlvbi4iLAogICAgICAgICAgIC"
    "AgICAgICJVc2UgdGhpcyBhcyBjb250ZXh0IGZvciB0aGUgY3VycmVudCBzZXNzaW9uOlxuIl0KCiAgI"
    "CAgICAgIyBJbmNsdWRlIHVwIHRvIGxhc3QgMzAgbWVzc2FnZXMgZnJvbSB0aGF0IHNlc3Npb24KICAg"
    "ICAgICBmb3IgbXNnIGluIG1lc3NhZ2VzWy0zMDpdOgogICAgICAgICAgICByb2xlICAgID0gbXNnLmd"
    "ldCgicm9sZSIsICI/IikudXBwZXIoKQogICAgICAgICAgICBjb250ZW50ID0gbXNnLmdldCgiY29udG"
    "VudCIsICIiKVs6MzAwXQogICAgICAgICAgICB0cyAgICAgID0gbXNnLmdldCgidGltZXN0YW1wIiwgI"
    "iIpWzoxNl0KICAgICAgICAgICAgbGluZXMuYXBwZW5kKGYiW3t0c31dIHtyb2xlfToge2NvbnRlbnR9"
    "IikKCiAgICAgICAgbGluZXMuYXBwZW5kKCJbRU5EIEpPVVJOQUxdIikKICAgICAgICByZXR1cm4gIlx"
    "uIi5qb2luKGxpbmVzKQoKICAgIGRlZiBjbGVhcl9sb2FkZWRfam91cm5hbChzZWxmKSAtPiBOb25lOg"
    "ogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFsID0gTm9uZQoKICAgIEBwcm9wZXJ0eQogICAgZGVmI"
    "GxvYWRlZF9qb3VybmFsX2RhdGUoc2VsZikgLT4gT3B0aW9uYWxbc3RyXToKICAgICAgICByZXR1cm4g"
    "c2VsZi5fbG9hZGVkX2pvdXJuYWwKCiAgICBkZWYgcmVuYW1lX3Nlc3Npb24oc2VsZiwgc2Vzc2lvbl9"
    "kYXRlOiBzdHIsIG5ld19uYW1lOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgIiIiUmVuYW1lIGEgc2Vzc2"
    "lvbiBpbiB0aGUgaW5kZXguIFJldHVybnMgVHJ1ZSBvbiBzdWNjZXNzLiIiIgogICAgICAgIGluZGV4I"
    "D0gc2VsZi5fbG9hZF9pbmRleCgpCiAgICAgICAgZm9yIGVudHJ5IGluIGluZGV4WyJzZXNzaW9ucyJd"
    "OgogICAgICAgICAgICBpZiBlbnRyeVsiZGF0ZSJdID09IHNlc3Npb25fZGF0ZToKICAgICAgICAgICA"
    "gICAgIGVudHJ5WyJuYW1lIl0gPSBuZXdfbmFtZVs6ODBdCiAgICAgICAgICAgICAgICBzZWxmLl9zYX"
    "ZlX2luZGV4KGluZGV4KQogICAgICAgICAgICAgICAgcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gR"
    "mFsc2UKCiAgICAjIOKUgOKUgCBJTkRFWCBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgAogICAgZGVmIF9sb2FkX2luZGV4KHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgaWYgbm90IHNlb"
    "GYuX2luZGV4X3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiB7InNlc3Npb25zIjogW119"
    "CiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXR1cm4ganNvbi5sb2FkcygKICAgICAgICAgICAgICA"
    "gIHNlbGYuX2luZGV4X3BhdGgucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpCiAgICAgICAgICAgIC"
    "kKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4geyJzZXNzaW9ucyI6I"
    "FtdfQoKICAgIGRlZiBfc2F2ZV9pbmRleChzZWxmLCBpbmRleDogZGljdCkgLT4gTm9uZToKICAgICAg"
    "ICBzZWxmLl9pbmRleF9wYXRoLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoaW5kZXg"
    "sIGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04IgogICAgICAgICkKCgojIOKUgOKUgCBMRVNTT05TIE"
    "xFQVJORUQgREFUQUJBU0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIExlc3N"
    "vbnNMZWFybmVkREI6CiAgICAiIiIKICAgIFBlcnNpc3RlbnQga25vd2xlZGdlIGJhc2UgZm9yIGNvZG"
    "UgbGVzc29ucywgcnVsZXMsIGFuZCByZXNvbHV0aW9ucy4KCiAgICBDb2x1bW5zIHBlciByZWNvcmQ6C"
    "iAgICAgICAgaWQsIGNyZWF0ZWRfYXQsIGVudmlyb25tZW50IChMU0x8UHl0aG9ufFB5U2lkZTZ8Li4u"
    "KSwgbGFuZ3VhZ2UsCiAgICAgICAgcmVmZXJlbmNlX2tleSAoc2hvcnQgdW5pcXVlIHRhZyksIHN1bW1"
    "hcnksIGZ1bGxfcnVsZSwKICAgICAgICByZXNvbHV0aW9uLCBsaW5rLCB0YWdzCgogICAgUXVlcmllZC"
    "BGSVJTVCBiZWZvcmUgYW55IGNvZGUgc2Vzc2lvbiBpbiB0aGUgcmVsZXZhbnQgbGFuZ3VhZ2UuCiAgI"
    "CBUaGUgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGxpdmVzIGhlcmUuCiAgICBHcm93aW5nLCBub24tZHVw"
    "bGljYXRpbmcsIHNlYXJjaGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICA"
    "gICAgc2VsZi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gImxlc3NvbnNfbGVhcm5lZC5qc2"
    "9ubCIKCiAgICBkZWYgYWRkKHNlbGYsIGVudmlyb25tZW50OiBzdHIsIGxhbmd1YWdlOiBzdHIsIHJlZ"
    "mVyZW5jZV9rZXk6IHN0ciwKICAgICAgICAgICAgc3VtbWFyeTogc3RyLCBmdWxsX3J1bGU6IHN0ciwg"
    "cmVzb2x1dGlvbjogc3RyID0gIiIsCiAgICAgICAgICAgIGxpbms6IHN0ciA9ICIiLCB0YWdzOiBsaXN"
    "0ID0gTm9uZSkgLT4gZGljdDoKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAgIC"
    "AgICAgICAgZiJsZXNzb25fe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAiY3JlY"
    "XRlZF9hdCI6ICAgIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgImVudmlyb25tZW50IjogICBl"
    "bnZpcm9ubWVudCwKICAgICAgICAgICAgImxhbmd1YWdlIjogICAgICBsYW5ndWFnZSwKICAgICAgICA"
    "gICAgInJlZmVyZW5jZV9rZXkiOiByZWZlcmVuY2Vfa2V5LAogICAgICAgICAgICAic3VtbWFyeSI6IC"
    "AgICAgIHN1bW1hcnksCiAgICAgICAgICAgICJmdWxsX3J1bGUiOiAgICAgZnVsbF9ydWxlLAogICAgI"
    "CAgICAgICAicmVzb2x1dGlvbiI6ICAgIHJlc29sdXRpb24sCiAgICAgICAgICAgICJsaW5rIjogICAg"
    "ICAgICAgbGluaywKICAgICAgICAgICAgInRhZ3MiOiAgICAgICAgICB0YWdzIG9yIFtdLAogICAgICA"
    "gIH0KICAgICAgICBpZiBub3Qgc2VsZi5faXNfZHVwbGljYXRlKHJlZmVyZW5jZV9rZXkpOgogICAgIC"
    "AgICAgICBhcHBlbmRfanNvbmwoc2VsZi5fcGF0aCwgcmVjb3JkKQogICAgICAgIHJldHVybiByZWNvc"
    "mQKCiAgICBkZWYgc2VhcmNoKHNlbGYsIHF1ZXJ5OiBzdHIgPSAiIiwgZW52aXJvbm1lbnQ6IHN0ciA9"
    "ICIiLAogICAgICAgICAgICAgICBsYW5ndWFnZTogc3RyID0gIiIpIC0+IGxpc3RbZGljdF06CiAgICA"
    "gICAgcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICByZXN1bHRzID0gW10KIC"
    "AgICAgICBxID0gcXVlcnkubG93ZXIoKQogICAgICAgIGZvciByIGluIHJlY29yZHM6CiAgICAgICAgI"
    "CAgIGlmIGVudmlyb25tZW50IGFuZCByLmdldCgiZW52aXJvbm1lbnQiLCIiKS5sb3dlcigpICE9IGVu"
    "dmlyb25tZW50Lmxvd2VyKCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiB"
    "sYW5ndWFnZSBhbmQgci5nZXQoImxhbmd1YWdlIiwiIikubG93ZXIoKSAhPSBsYW5ndWFnZS5sb3dlci"
    "gpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYgcToKICAgICAgICAgICAgI"
    "CAgIGhheXN0YWNrID0gIiAiLmpvaW4oWwogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJzdW1tYXJ5"
    "IiwiIiksCiAgICAgICAgICAgICAgICAgICAgci5nZXQoImZ1bGxfcnVsZSIsIiIpLAogICAgICAgICA"
    "gICAgICAgICAgIHIuZ2V0KCJyZWZlcmVuY2Vfa2V5IiwiIiksCiAgICAgICAgICAgICAgICAgICAgIi"
    "AiLmpvaW4oci5nZXQoInRhZ3MiLFtdKSksCiAgICAgICAgICAgICAgICBdKS5sb3dlcigpCiAgICAgI"
    "CAgICAgICAgICBpZiBxIG5vdCBpbiBoYXlzdGFjazoKICAgICAgICAgICAgICAgICAgICBjb250aW51"
    "ZQogICAgICAgICAgICByZXN1bHRzLmFwcGVuZChyKQogICAgICAgIHJldHVybiByZXN1bHRzCgogICA"
    "gZGVmIGdldF9hbGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubC"
    "hzZWxmLl9wYXRoKQoKICAgIGRlZiBkZWxldGUoc2VsZiwgcmVjb3JkX2lkOiBzdHIpIC0+IGJvb2w6C"
    "iAgICAgICAgcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBmaWx0ZXJlZCA9"
    "IFtyIGZvciByIGluIHJlY29yZHMgaWYgci5nZXQoImlkIikgIT0gcmVjb3JkX2lkXQogICAgICAgIGl"
    "mIGxlbihmaWx0ZXJlZCkgPCBsZW4ocmVjb3Jkcyk6CiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbG"
    "YuX3BhdGgsIGZpbHRlcmVkKQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVybiBGY"
    "WxzZQoKICAgIGRlZiBidWlsZF9jb250ZXh0X2Zvcl9sYW5ndWFnZShzZWxmLCBsYW5ndWFnZTogc3Ry"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIG1heF9jaGFyczogaW50ID0gMTUwMCk"
    "gLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIEJ1aWxkIGEgY29udGV4dCBzdHJpbmcgb2YgYWxsIH"
    "J1bGVzIGZvciBhIGdpdmVuIGxhbmd1YWdlLgogICAgICAgIEZvciBpbmplY3Rpb24gaW50byBzeXN0Z"
    "W0gcHJvbXB0IGJlZm9yZSBjb2RlIHNlc3Npb25zLgogICAgICAgICIiIgogICAgICAgIHJlY29yZHMg"
    "PSBzZWxmLnNlYXJjaChsYW5ndWFnZT1sYW5ndWFnZSkKICAgICAgICBpZiBub3QgcmVjb3JkczoKICA"
    "gICAgICAgICAgcmV0dXJuICIiCgogICAgICAgIHBhcnRzID0gW2YiW3tsYW5ndWFnZS51cHBlcigpfS"
    "BSVUxFUyDigJQgQVBQTFkgQkVGT1JFIFdSSVRJTkcgQ09ERV0iXQogICAgICAgIHRvdGFsID0gMAogI"
    "CAgICAgIGZvciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGVudHJ5ID0gZiLigKIge3IuZ2V0KCdy"
    "ZWZlcmVuY2Vfa2V5JywnJyl9OiB7ci5nZXQoJ2Z1bGxfcnVsZScsJycpfSIKICAgICAgICAgICAgaWY"
    "gdG90YWwgKyBsZW4oZW50cnkpID4gbWF4X2NoYXJzOgogICAgICAgICAgICAgICAgYnJlYWsKICAgIC"
    "AgICAgICAgcGFydHMuYXBwZW5kKGVudHJ5KQogICAgICAgICAgICB0b3RhbCArPSBsZW4oZW50cnkpC"
    "gogICAgICAgIHBhcnRzLmFwcGVuZChmIltFTkQge2xhbmd1YWdlLnVwcGVyKCl9IFJVTEVTXSIpCiAg"
    "ICAgICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCiAgICBkZWYgX2lzX2R1cGxpY2F0ZShzZWxmLCB"
    "yZWZlcmVuY2Vfa2V5OiBzdHIpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIGFueSgKICAgICAgICAgIC"
    "Agci5nZXQoInJlZmVyZW5jZV9rZXkiLCIiKS5sb3dlcigpID09IHJlZmVyZW5jZV9rZXkubG93ZXIoK"
    "QogICAgICAgICAgICBmb3IgciBpbiByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgKQoKICAg"
    "IGRlZiBzZWVkX2xzbF9ydWxlcyhzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIFNlZWQ"
    "gdGhlIExTTCBGb3JiaWRkZW4gUnVsZXNldCBvbiBmaXJzdCBydW4gaWYgdGhlIERCIGlzIGVtcHR5Lg"
    "ogICAgICAgIFRoZXNlIGFyZSB0aGUgaGFyZCBydWxlcyBmcm9tIHRoZSBwcm9qZWN0IHN0YW5kaW5nI"
    "HJ1bGVzLgogICAgICAgICIiIgogICAgICAgIGlmIHJlYWRfanNvbmwoc2VsZi5fcGF0aCk6CiAgICAg"
    "ICAgICAgIHJldHVybiAgIyBBbHJlYWR5IHNlZWRlZAoKICAgICAgICBsc2xfcnVsZXMgPSBbCiAgICA"
    "gICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19URVJOQVJZIiwKICAgICAgICAgICAgICJObyB0ZXJuYX"
    "J5IG9wZXJhdG9ycyBpbiBMU0wiLAogICAgICAgICAgICAgIk5ldmVyIHVzZSB0aGUgdGVybmFyeSBvc"
    "GVyYXRvciAoPzopIGluIExTTCBzY3JpcHRzLiAiCiAgICAgICAgICAgICAiVXNlIGlmL2Vsc2UgYmxv"
    "Y2tzIGluc3RlYWQuIExTTCBkb2VzIG5vdCBzdXBwb3J0IHRlcm5hcnkuIiwKICAgICAgICAgICAgICJ"
    "SZXBsYWNlIHdpdGggaWYvZWxzZSBibG9jay4iLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTC"
    "IsICJOT19GT1JFQUNIIiwKICAgICAgICAgICAgICJObyBmb3JlYWNoIGxvb3BzIGluIExTTCIsCiAgI"
    "CAgICAgICAgICAiTFNMIGhhcyBubyBmb3JlYWNoIGxvb3AgY29uc3RydWN0LiBVc2UgaW50ZWdlciBp"
    "bmRleCB3aXRoICIKICAgICAgICAgICAgICJsbEdldExpc3RMZW5ndGgoKSBhbmQgYSBmb3Igb3Igd2h"
    "pbGUgbG9vcC4iLAogICAgICAgICAgICAgIlVzZTogZm9yKGludGVnZXIgaT0wOyBpPGxsR2V0TGlzdE"
    "xlbmd0aChteUxpc3QpOyBpKyspIiwgIiIpLAogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAiTk9fR"
    "0xPQkFMX0FTU0lHTl9GUk9NX0ZVTkMiLAogICAgICAgICAgICAgIk5vIGdsb2JhbCB2YXJpYWJsZSBh"
    "c3NpZ25tZW50cyBmcm9tIGZ1bmN0aW9uIGNhbGxzIiwKICAgICAgICAgICAgICJHbG9iYWwgdmFyaWF"
    "ibGUgaW5pdGlhbGl6YXRpb24gaW4gTFNMIGNhbm5vdCBjYWxsIGZ1bmN0aW9ucy4gIgogICAgICAgIC"
    "AgICAgIkluaXRpYWxpemUgZ2xvYmFscyB3aXRoIGxpdGVyYWwgdmFsdWVzIG9ubHkuICIKICAgICAgI"
    "CAgICAgICJBc3NpZ24gZnJvbSBmdW5jdGlvbnMgaW5zaWRlIGV2ZW50IGhhbmRsZXJzIG9yIG90aGVy"
    "IGZ1bmN0aW9ucy4iLAogICAgICAgICAgICAgIk1vdmUgdGhlIGFzc2lnbm1lbnQgaW50byBhbiBldmV"
    "udCBoYW5kbGVyIChzdGF0ZV9lbnRyeSwgZXRjLikiLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIk"
    "xTTCIsICJOT19WT0lEX0tFWVdPUkQiLAogICAgICAgICAgICAgIk5vIHZvaWQga2V5d29yZCBpbiBMU"
    "0wiLAogICAgICAgICAgICAgIkxTTCBkb2VzIG5vdCBoYXZlIGEgdm9pZCBrZXl3b3JkIGZvciBmdW5j"
    "dGlvbiByZXR1cm4gdHlwZXMuICIKICAgICAgICAgICAgICJGdW5jdGlvbnMgdGhhdCByZXR1cm4gbm9"
    "0aGluZyBzaW1wbHkgb21pdCB0aGUgcmV0dXJuIHR5cGUuIiwKICAgICAgICAgICAgICJSZW1vdmUgJ3"
    "ZvaWQnIGZyb20gZnVuY3Rpb24gc2lnbmF0dXJlLiAiCiAgICAgICAgICAgICAiZS5nLiBteUZ1bmMoK"
    "SB7IC4uLiB9IG5vdCB2b2lkIG15RnVuYygpIHsgLi4uIH0iLCAiIiksCiAgICAgICAgICAgICgiTFNM"
    "IiwgIkxTTCIsICJDT01QTEVURV9TQ1JJUFRTX09OTFkiLAogICAgICAgICAgICAgIkFsd2F5cyBwcm9"
    "2aWRlIGNvbXBsZXRlIHNjcmlwdHMsIG5ldmVyIHBhcnRpYWwgZWRpdHMiLAogICAgICAgICAgICAgIl"
    "doZW4gd3JpdGluZyBvciBlZGl0aW5nIExTTCBzY3JpcHRzLCBhbHdheXMgb3V0cHV0IHRoZSBjb21wb"
    "GV0ZSAiCiAgICAgICAgICAgICAic2NyaXB0LiBOZXZlciBwcm92aWRlIHBhcnRpYWwgc25pcHBldHMg"
    "b3IgJ2FkZCB0aGlzIHNlY3Rpb24nICIKICAgICAgICAgICAgICJpbnN0cnVjdGlvbnMuIFRoZSBmdWx"
    "sIHNjcmlwdCBtdXN0IGJlIGNvcHktcGFzdGUgcmVhZHkuIiwKICAgICAgICAgICAgICJXcml0ZSB0aG"
    "UgZW50aXJlIHNjcmlwdCBmcm9tIHRvcCB0byBib3R0b20uIiwgIiIpLAogICAgICAgIF0KCiAgICAgI"
    "CAgZm9yIGVudiwgbGFuZywgcmVmLCBzdW1tYXJ5LCBmdWxsX3J1bGUsIHJlc29sdXRpb24sIGxpbmsg"
    "aW4gbHNsX3J1bGVzOgogICAgICAgICAgICBzZWxmLmFkZChlbnYsIGxhbmcsIHJlZiwgc3VtbWFyeSw"
    "gZnVsbF9ydWxlLCByZXNvbHV0aW9uLCBsaW5rLAogICAgICAgICAgICAgICAgICAgICB0YWdzPVsibH"
    "NsIiwgImZvcmJpZGRlbiIsICJzdGFuZGluZ19ydWxlIl0pCgoKIyDilIDilIAgVEFTSyBNQU5BR0VSI"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgApjbGFzcyBUYXNrTWFuYWdlcjoKICAgICIiIgogICAgVGFzay9yZW1pbmRlciBDUlVEIGFuZ"
    "CBkdWUtZXZlbnQgZGV0ZWN0aW9uLgoKICAgIEZpbGU6IG1lbW9yaWVzL3Rhc2tzLmpzb25sCgogICAg"
    "VGFzayByZWNvcmQgZmllbGRzOgogICAgICAgIGlkLCBjcmVhdGVkX2F0LCBkdWVfYXQsIHByZV90cml"
    "nZ2VyICgxbWluIGJlZm9yZSksCiAgICAgICAgdGV4dCwgc3RhdHVzIChwZW5kaW5nfHRyaWdnZXJlZH"
    "xzbm9vemVkfGNvbXBsZXRlZHxjYW5jZWxsZWQpLAogICAgICAgIGFja25vd2xlZGdlZF9hdCwgcmV0c"
    "nlfY291bnQsIGxhc3RfdHJpZ2dlcmVkX2F0LCBuZXh0X3JldHJ5X2F0LAogICAgICAgIHNvdXJjZSAo"
    "bG9jYWx8Z29vZ2xlKSwgZ29vZ2xlX2V2ZW50X2lkLCBzeW5jX3N0YXR1cywgbWV0YWRhdGEKCiAgICB"
    "EdWUtZXZlbnQgY3ljbGU6CiAgICAgICAgLSBQcmUtdHJpZ2dlcjogMSBtaW51dGUgYmVmb3JlIGR1ZS"
    "DihpIgYW5ub3VuY2UgdXBjb21pbmcKICAgICAgICAtIER1ZSB0cmlnZ2VyOiBhdCBkdWUgdGltZSDih"
    "pIgYWxlcnQgc291bmQgKyBBSSBjb21tZW50YXJ5CiAgICAgICAgLSAzLW1pbnV0ZSB3aW5kb3c6IGlm"
    "IG5vdCBhY2tub3dsZWRnZWQg4oaSIHNub296ZQogICAgICAgIC0gMTItbWludXRlIHJldHJ5OiByZS1"
    "0cmlnZ2VyCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fcGF0aC"
    "A9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gInRhc2tzLmpzb25sIgoKICAgICMg4pSA4pSAIENSVUQg4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACi"
    "AgICBkZWYgbG9hZF9hbGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICB0YXNrcyA9IHJlYWRfa"
    "nNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBjaGFuZ2VkID0gRmFsc2UKICAgICAgICBub3JtYWxpemVk"
    "ID0gW10KICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgbm90IGlzaW5zdGFuY2U"
    "odCwgZGljdCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiAiaWQiIG5vdC"
    "BpbiB0OgogICAgICAgICAgICAgICAgdFsiaWQiXSA9IGYidGFza197dXVpZC51dWlkNCgpLmhleFs6M"
    "TBdfSIKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICMgTm9ybWFsaXpl"
    "IGZpZWxkIG5hbWVzCiAgICAgICAgICAgIGlmICJkdWVfYXQiIG5vdCBpbiB0OgogICAgICAgICAgICA"
    "gICAgdFsiZHVlX2F0Il0gPSB0LmdldCgiZHVlIikKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcn"
    "VlCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3RhdHVzIiwgICAgICAgICAgICJwZW5kaW5nIikKI"
    "CAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJyZXRyeV9jb3VudCIsICAgICAgMCkKICAgICAgICAgICAg"
    "dC5zZXRkZWZhdWx0KCJhY2tub3dsZWRnZWRfYXQiLCAgTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZ"
    "hdWx0KCJsYXN0X3RyaWdnZXJlZF9hdCIsTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJuZX"
    "h0X3JldHJ5X2F0IiwgICAgTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJwcmVfYW5ub3VuY"
    "2VkIiwgICAgRmFsc2UpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic291cmNlIiwgICAgICAgICAg"
    "ICJsb2NhbCIpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiZ29vZ2xlX2V2ZW50X2lkIiwgIE5vbmU"
    "pCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3luY19zdGF0dXMiLCAgICAgICJwZW5kaW5nIikKIC"
    "AgICAgICAgICAgdC5zZXRkZWZhdWx0KCJtZXRhZGF0YSIsICAgICAgICAge30pCiAgICAgICAgICAgI"
    "HQuc2V0ZGVmYXVsdCgiY3JlYXRlZF9hdCIsICAgICAgIGxvY2FsX25vd19pc28oKSkKCiAgICAgICAg"
    "ICAgICMgQ29tcHV0ZSBwcmVfdHJpZ2dlciBpZiBtaXNzaW5nCiAgICAgICAgICAgIGlmIHQuZ2V0KCJ"
    "kdWVfYXQiKSBhbmQgbm90IHQuZ2V0KCJwcmVfdHJpZ2dlciIpOgogICAgICAgICAgICAgICAgZHQgPS"
    "BwYXJzZV9pc28odFsiZHVlX2F0Il0pCiAgICAgICAgICAgICAgICBpZiBkdDoKICAgICAgICAgICAgI"
    "CAgICAgICBwcmUgPSBkdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpCiAgICAgICAgICAgICAgICAgICAg"
    "dFsicHJlX3RyaWdnZXIiXSA9IHByZS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICA"
    "gICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgICAgICAgICBub3JtYWxpemVkLmFwcGVuZC"
    "h0KQoKICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoL"
    "CBub3JtYWxpemVkKQogICAgICAgIHJldHVybiBub3JtYWxpemVkCgogICAgZGVmIHNhdmVfYWxsKHNl"
    "bGYsIHRhc2tzOiBsaXN0W2RpY3RdKSAtPiBOb25lOgogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3B"
    "hdGgsIHRhc2tzKQoKICAgIGRlZiBhZGQoc2VsZiwgdGV4dDogc3RyLCBkdWVfZHQ6IGRhdGV0aW1lLA"
    "ogICAgICAgICAgICBzb3VyY2U6IHN0ciA9ICJsb2NhbCIpIC0+IGRpY3Q6CiAgICAgICAgcHJlID0gZ"
    "HVlX2R0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkKICAgICAgICB0YXNrID0gewogICAgICAgICAgICAi"
    "aWQiOiAgICAgICAgICAgICAgIGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICA"
    "gICAgICJjcmVhdGVkX2F0IjogICAgICAgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAiZHVlX2"
    "F0IjogICAgICAgICAgIGR1ZV9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgI"
    "CAgICAgInByZV90cmlnZ2VyIjogICAgICBwcmUuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiks"
    "CiAgICAgICAgICAgICJ0ZXh0IjogICAgICAgICAgICAgdGV4dC5zdHJpcCgpLAogICAgICAgICAgICA"
    "ic3RhdHVzIjogICAgICAgICAgICJwZW5kaW5nIiwKICAgICAgICAgICAgImFja25vd2xlZGdlZF9hdC"
    "I6ICBOb25lLAogICAgICAgICAgICAicmV0cnlfY291bnQiOiAgICAgIDAsCiAgICAgICAgICAgICJsY"
    "XN0X3RyaWdnZXJlZF9hdCI6Tm9uZSwKICAgICAgICAgICAgIm5leHRfcmV0cnlfYXQiOiAgICBOb25l"
    "LAogICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6ICAgIEZhbHNlLAogICAgICAgICAgICAic291cmN"
    "lIjogICAgICAgICAgIHNvdXJjZSwKICAgICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6ICBOb25lLA"
    "ogICAgICAgICAgICAic3luY19zdGF0dXMiOiAgICAgICJwZW5kaW5nIiwKICAgICAgICAgICAgIm1ld"
    "GFkYXRhIjogICAgICAgICB7fSwKICAgICAgICB9CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxs"
    "KCkKICAgICAgICB0YXNrcy5hcHBlbmQodGFzaykKICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQo"
    "gICAgICAgIHJldHVybiB0YXNrCgogICAgZGVmIHVwZGF0ZV9zdGF0dXMoc2VsZiwgdGFza19pZDogc3"
    "RyLCBzdGF0dXM6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgIGFja25vd2xlZGdlZDogYm9vbCA9I"
    "EZhbHNlKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQog"
    "ICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0YXNrX2l"
    "kOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gPSBzdGF0dXMKICAgICAgICAgICAgICAgIGlmIG"
    "Fja25vd2xlZGdlZDoKICAgICAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY"
    "2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAg"
    "ICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY29tcGxldGUoc2VsZiw"
    "gdGFza19pZDogc3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF"
    "9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQiKSA9P"
    "SB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gICAgICAgICAgPSAiY29tcGxldGVk"
    "IgogICAgICAgICAgICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICA"
    "gICAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdA"
    "ogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNhbmNlbChzZWxmLCB0YXNrX2lkOiBzdHIpIC0+I"
    "E9wdGlvbmFsW2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9y"
    "IHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09IHRhc2tfaWQ6CiAgICAgICA"
    "gICAgICAgICB0WyJzdGF0dXMiXSAgICAgICAgICA9ICJjYW5jZWxsZWQiCiAgICAgICAgICAgICAgIC"
    "B0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgc2VsZ"
    "i5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5v"
    "bmUKCiAgICBkZWYgY2xlYXJfY29tcGxldGVkKHNlbGYpIC0+IGludDoKICAgICAgICB0YXNrcyAgICA"
    "9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGtlcHQgICAgID0gW3QgZm9yIHQgaW4gdGFza3MKICAgIC"
    "AgICAgICAgICAgICAgICBpZiB0LmdldCgic3RhdHVzIikgbm90IGluIHsiY29tcGxldGVkIiwiY2FuY"
    "2VsbGVkIn1dCiAgICAgICAgcmVtb3ZlZCAgPSBsZW4odGFza3MpIC0gbGVuKGtlcHQpCiAgICAgICAg"
    "aWYgcmVtb3ZlZDoKICAgICAgICAgICAgc2VsZi5zYXZlX2FsbChrZXB0KQogICAgICAgIHJldHVybiB"
    "yZW1vdmVkCgogICAgZGVmIHVwZGF0ZV9nb29nbGVfc3luYyhzZWxmLCB0YXNrX2lkOiBzdHIsIHN5bm"
    "Nfc3RhdHVzOiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgIGdvb2dsZV9ldmVudF9pZDogc"
    "3RyID0gIiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgIGVycm9yOiBzdHIgPSAiIikgLT4gT3B0"
    "aW9uYWxbZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBmb3IgdCB"
    "pbiB0YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0gdGFza19pZDoKICAgICAgICAgIC"
    "AgICAgIHRbInN5bmNfc3RhdHVzIl0gICAgPSBzeW5jX3N0YXR1cwogICAgICAgICAgICAgICAgdFsib"
    "GFzdF9zeW5jZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgaWYgZ29vZ2xl"
    "X2V2ZW50X2lkOgogICAgICAgICAgICAgICAgICAgIHRbImdvb2dsZV9ldmVudF9pZCJdID0gZ29vZ2x"
    "lX2V2ZW50X2lkCiAgICAgICAgICAgICAgICBpZiBlcnJvcjoKICAgICAgICAgICAgICAgICAgICB0Ln"
    "NldGRlZmF1bHQoIm1ldGFkYXRhIiwge30pCiAgICAgICAgICAgICAgICAgICAgdFsibWV0YWRhdGEiX"
    "VsiZ29vZ2xlX3N5bmNfZXJyb3IiXSA9IGVycm9yWzoyNDBdCiAgICAgICAgICAgICAgICBzZWxmLnNh"
    "dmVfYWxsKHRhc2tzKQogICAgICAgICAgICAgICAgcmV0dXJuIHQKICAgICAgICByZXR1cm4gTm9uZQo"
    "KICAgICMg4pSA4pSAIERVRSBFVkVOVCBERVRFQ1RJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgZ2V0"
    "X2R1ZV9ldmVudHMoc2VsZikgLT4gbGlzdFt0dXBsZVtzdHIsIGRpY3RdXToKICAgICAgICAiIiIKICA"
    "gICAgICBDaGVjayBhbGwgdGFza3MgZm9yIGR1ZS9wcmUtdHJpZ2dlci9yZXRyeSBldmVudHMuCiAgIC"
    "AgICAgUmV0dXJucyBsaXN0IG9mIChldmVudF90eXBlLCB0YXNrKSB0dXBsZXMuCiAgICAgICAgZXZlb"
    "nRfdHlwZTogInByZSIgfCAiZHVlIiB8ICJyZXRyeSIKCiAgICAgICAgTW9kaWZpZXMgdGFzayBzdGF0"
    "dXNlcyBpbiBwbGFjZSBhbmQgc2F2ZXMuCiAgICAgICAgQ2FsbCBmcm9tIEFQU2NoZWR1bGVyIGV2ZXJ"
    "5IDMwIHNlY29uZHMuCiAgICAgICAgIiIiCiAgICAgICAgbm93ICAgID0gZGF0ZXRpbWUubm93KCkuYX"
    "N0aW1lem9uZSgpCiAgICAgICAgdGFza3MgID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZXZlbnRzI"
    "D0gW10KICAgICAgICBjaGFuZ2VkID0gRmFsc2UKCiAgICAgICAgZm9yIHRhc2sgaW4gdGFza3M6CiAg"
    "ICAgICAgICAgIGlmIHRhc2suZ2V0KCJhY2tub3dsZWRnZWRfYXQiKToKICAgICAgICAgICAgICAgIGN"
    "vbnRpbnVlCgogICAgICAgICAgICBzdGF0dXMgICA9IHRhc2suZ2V0KCJzdGF0dXMiLCAicGVuZGluZy"
    "IpCiAgICAgICAgICAgIGR1ZSAgICAgID0gc2VsZi5fcGFyc2VfbG9jYWwodGFzay5nZXQoImR1ZV9hd"
    "CIpKQogICAgICAgICAgICBwcmUgICAgICA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJwcmVf"
    "dHJpZ2dlciIpKQogICAgICAgICAgICBuZXh0X3JldCA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V"
    "0KCJuZXh0X3JldHJ5X2F0IikpCiAgICAgICAgICAgIGRlYWRsaW5lID0gc2VsZi5fcGFyc2VfbG9jYW"
    "wodGFzay5nZXQoImFsZXJ0X2RlYWRsaW5lIikpCgogICAgICAgICAgICAjIFByZS10cmlnZ2VyCiAgI"
    "CAgICAgICAgIGlmIChzdGF0dXMgPT0gInBlbmRpbmciIGFuZCBwcmUgYW5kIG5vdyA+PSBwcmUKICAg"
    "ICAgICAgICAgICAgICAgICBhbmQgbm90IHRhc2suZ2V0KCJwcmVfYW5ub3VuY2VkIikpOgogICAgICA"
    "gICAgICAgICAgdGFza1sicHJlX2Fubm91bmNlZCJdID0gVHJ1ZQogICAgICAgICAgICAgICAgZXZlbn"
    "RzLmFwcGVuZCgoInByZSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgI"
    "CAgICAgICAgICMgRHVlIHRyaWdnZXIKICAgICAgICAgICAgaWYgc3RhdHVzID09ICJwZW5kaW5nIiBh"
    "bmQgZHVlIGFuZCBub3cgPj0gZHVlOgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICA"
    "gICAgID0gInRyaWdnZXJlZCIKICAgICAgICAgICAgICAgIHRhc2tbImxhc3RfdHJpZ2dlcmVkX2F0Il"
    "09IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgdGFza1siYWxlcnRfZGVhZGxpbmUiXSAgI"
    "D0gKAogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKSArIHRpbWVk"
    "ZWx0YShtaW51dGVzPTMpCiAgICAgICAgICAgICAgICApLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25"
    "kcyIpCiAgICAgICAgICAgICAgICBldmVudHMuYXBwZW5kKCgiZHVlIiwgdGFzaykpCiAgICAgICAgIC"
    "AgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgI"
    "CMgU25vb3plIGFmdGVyIDMtbWludXRlIHdpbmRvdwogICAgICAgICAgICBpZiBzdGF0dXMgPT0gInRy"
    "aWdnZXJlZCIgYW5kIGRlYWRsaW5lIGFuZCBub3cgPj0gZGVhZGxpbmU6CiAgICAgICAgICAgICAgICB"
    "0YXNrWyJzdGF0dXMiXSAgICAgICAgPSAic25vb3plZCIKICAgICAgICAgICAgICAgIHRhc2tbIm5leH"
    "RfcmV0cnlfYXQiXSA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5hc3RpbWV6b"
    "25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0xMikKICAgICAgICAgICAgICAgICkuaXNvZm9ybWF0KHRp"
    "bWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICA"
    "gICAgICBjb250aW51ZQoKICAgICAgICAgICAgIyBSZXRyeQogICAgICAgICAgICBpZiBzdGF0dXMgaW"
    "4geyJyZXRyeV9wZW5kaW5nIiwic25vb3plZCJ9IGFuZCBuZXh0X3JldCBhbmQgbm93ID49IG5leHRfc"
    "mV0OgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICAgICAgICA9ICJ0cmlnZ2VyZWQi"
    "CiAgICAgICAgICAgICAgICB0YXNrWyJyZXRyeV9jb3VudCJdICAgICAgID0gaW50KHRhc2suZ2V0KCJ"
    "yZXRyeV9jb3VudCIsMCkpICsgMQogICAgICAgICAgICAgICAgdGFza1sibGFzdF90cmlnZ2VyZWRfYX"
    "QiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgdGFza1siYWxlcnRfZGVhZGxpbmUiX"
    "SAgICA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkgKyB0"
    "aW1lZGVsdGEobWludXRlcz0zKQogICAgICAgICAgICAgICAgKS5pc29mb3JtYXQodGltZXNwZWM9InN"
    "lY29uZHMiKQogICAgICAgICAgICAgICAgdGFza1sibmV4dF9yZXRyeV9hdCJdICAgICA9IE5vbmUKIC"
    "AgICAgICAgICAgICAgIGV2ZW50cy5hcHBlbmQoKCJyZXRyeSIsIHRhc2spKQogICAgICAgICAgICAgI"
    "CAgY2hhbmdlZCA9IFRydWUKCiAgICAgICAgaWYgY2hhbmdlZDoKICAgICAgICAgICAgc2VsZi5zYXZl"
    "X2FsbCh0YXNrcykKICAgICAgICByZXR1cm4gZXZlbnRzCgogICAgZGVmIF9wYXJzZV9sb2NhbChzZWx"
    "mLCB2YWx1ZTogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICAgICAgIiIiUGFyc2UgSVNPIH"
    "N0cmluZyB0byB0aW1lem9uZS1hd2FyZSBkYXRldGltZSBmb3IgY29tcGFyaXNvbi4iIiIKICAgICAgI"
    "CBkdCA9IHBhcnNlX2lzbyh2YWx1ZSkKICAgICAgICBpZiBkdCBpcyBOb25lOgogICAgICAgICAgICBy"
    "ZXR1cm4gTm9uZQogICAgICAgIGlmIGR0LnR6aW5mbyBpcyBOb25lOgogICAgICAgICAgICBkdCA9IGR"
    "0LmFzdGltZXpvbmUoKQogICAgICAgIHJldHVybiBkdAoKICAgICMg4pSA4pSAIE5BVFVSQUwgTEFOR1"
    "VBR0UgUEFSU0lORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBjbGFzc2lmeV9pbnRlbnQodGV4dDo"
    "gc3RyKSAtPiBkaWN0OgogICAgICAgICIiIgogICAgICAgIENsYXNzaWZ5IHVzZXIgaW5wdXQgYXMgdG"
    "Fzay9yZW1pbmRlci90aW1lci9jaGF0LgogICAgICAgIFJldHVybnMgeyJpbnRlbnQiOiBzdHIsICJjb"
    "GVhbmVkX2lucHV0Ijogc3RyfQogICAgICAgICIiIgogICAgICAgIGltcG9ydCByZQogICAgICAgICMg"
    "U3RyaXAgY29tbW9uIGludm9jYXRpb24gcHJlZml4ZXMKICAgICAgICBjbGVhbmVkID0gcmUuc3ViKAo"
    "gICAgICAgICAgICByZiJeXHMqKD86e0RFQ0tfTkFNRS5sb3dlcigpfXxoZXlccyt7REVDS19OQU1FLm"
    "xvd2VyKCl9KVxzKiw/XHMqWzpcLV0/XHMqIiwKICAgICAgICAgICAgIiIsIHRleHQsIGZsYWdzPXJlL"
    "kkKICAgICAgICApLnN0cmlwKCkKCiAgICAgICAgbG93ID0gY2xlYW5lZC5sb3dlcigpCgogICAgICAg"
    "IHRpbWVyX3BhdHMgICAgPSBbciJcYnNldCg/OlxzK2EpP1xzK3RpbWVyXGIiLCByIlxidGltZXJccyt"
    "mb3JcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICByIlxic3RhcnQoPzpccythKT9ccyt0aW1lcl"
    "xiIl0KICAgICAgICByZW1pbmRlcl9wYXRzID0gW3IiXGJyZW1pbmQgbWVcYiIsIHIiXGJzZXQoPzpcc"
    "ythKT9ccytyZW1pbmRlclxiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJhZGQoPzpccyth"
    "KT9ccytyZW1pbmRlclxiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJzZXQoPzpccythbj8"
    "pP1xzK2FsYXJtXGIiLCByIlxiYWxhcm1ccytmb3JcYiJdCiAgICAgICAgdGFza19wYXRzICAgICA9IF"
    "tyIlxiYWRkKD86XHMrYSk/XHMrdGFza1xiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJjc"
    "mVhdGUoPzpccythKT9ccyt0YXNrXGIiLCByIlxibmV3XHMrdGFza1xiIl0KCiAgICAgICAgaW1wb3J0"
    "IHJlIGFzIF9yZQogICAgICAgIGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gdGltZXJ"
    "fcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9ICJ0aW1lciIKICAgICAgICBlbGlmIGFueShfcmUuc2"
    "VhcmNoKHAsIGxvdykgZm9yIHAgaW4gcmVtaW5kZXJfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9I"
    "CJyZW1pbmRlciIKICAgICAgICBlbGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gdGFz"
    "a19wYXRzKToKICAgICAgICAgICAgaW50ZW50ID0gInRhc2siCiAgICAgICAgZWxzZToKICAgICAgICA"
    "gICAgaW50ZW50ID0gImNoYXQiCgogICAgICAgIHJldHVybiB7ImludGVudCI6IGludGVudCwgImNsZW"
    "FuZWRfaW5wdXQiOiBjbGVhbmVkfQoKICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBwYXJzZV9kdWVfZ"
    "GF0ZXRpbWUodGV4dDogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICAgICAgIiIiCiAgICAg"
    "ICAgUGFyc2UgbmF0dXJhbCBsYW5ndWFnZSB0aW1lIGV4cHJlc3Npb24gZnJvbSB0YXNrIHRleHQuCiA"
    "gICAgICAgSGFuZGxlczogImluIDMwIG1pbnV0ZXMiLCAiYXQgM3BtIiwgInRvbW9ycm93IGF0IDlhbS"
    "IsCiAgICAgICAgICAgICAgICAgImluIDIgaG91cnMiLCAiYXQgMTU6MzAiLCBldGMuCiAgICAgICAgU"
    "mV0dXJucyBhIGRhdGV0aW1lIG9yIE5vbmUgaWYgdW5wYXJzZWFibGUuCiAgICAgICAgIiIiCiAgICAg"
    "ICAgaW1wb3J0IHJlCiAgICAgICAgbm93ICA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAgbG93ICA9IHR"
    "leHQubG93ZXIoKS5zdHJpcCgpCgogICAgICAgICMgImluIFggbWludXRlcy9ob3Vycy9kYXlzIgogIC"
    "AgICAgIG0gPSByZS5zZWFyY2goCiAgICAgICAgICAgIHIiaW5ccysoXGQrKVxzKihtaW51dGV8bWluf"
    "GhvdXJ8aHJ8ZGF5fHNlY29uZHxzZWMpIiwKICAgICAgICAgICAgbG93CiAgICAgICAgKQogICAgICAg"
    "IGlmIG06CiAgICAgICAgICAgIG4gICAgPSBpbnQobS5ncm91cCgxKSkKICAgICAgICAgICAgdW5pdCA"
    "9IG0uZ3JvdXAoMikKICAgICAgICAgICAgaWYgIm1pbiIgaW4gdW5pdDogIHJldHVybiBub3cgKyB0aW"
    "1lZGVsdGEobWludXRlcz1uKQogICAgICAgICAgICBpZiAiaG91ciIgaW4gdW5pdCBvciAiaHIiIGluI"
    "HVuaXQ6IHJldHVybiBub3cgKyB0aW1lZGVsdGEoaG91cnM9bikKICAgICAgICAgICAgaWYgImRheSIg"
    "IGluIHVuaXQ6IHJldHVybiBub3cgKyB0aW1lZGVsdGEoZGF5cz1uKQogICAgICAgICAgICBpZiAic2V"
    "jIiAgaW4gdW5pdDogcmV0dXJuIG5vdyArIHRpbWVkZWx0YShzZWNvbmRzPW4pCgogICAgICAgICMgIm"
    "F0IEhIOk1NIiBvciAiYXQgSDpNTWFtL3BtIgogICAgICAgIG0gPSByZS5zZWFyY2goCiAgICAgICAgI"
    "CAgIHIiYXRccysoXGR7MSwyfSkoPzo6KFxkezJ9KSk/XHMqKGFtfHBtKT8iLAogICAgICAgICAgICBs"
    "b3cKICAgICAgICApCiAgICAgICAgaWYgbToKICAgICAgICAgICAgaHIgID0gaW50KG0uZ3JvdXAoMSk"
    "pCiAgICAgICAgICAgIG1uICA9IGludChtLmdyb3VwKDIpKSBpZiBtLmdyb3VwKDIpIGVsc2UgMAogIC"
    "AgICAgICAgICBhcG0gPSBtLmdyb3VwKDMpCiAgICAgICAgICAgIGlmIGFwbSA9PSAicG0iIGFuZCBoc"
    "iA8IDEyOiBociArPSAxMgogICAgICAgICAgICBpZiBhcG0gPT0gImFtIiBhbmQgaHIgPT0gMTI6IGhy"
    "ID0gMAogICAgICAgICAgICBkdCA9IG5vdy5yZXBsYWNlKGhvdXI9aHIsIG1pbnV0ZT1tbiwgc2Vjb25"
    "kPTAsIG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgIGlmIGR0IDw9IG5vdzoKICAgICAgICAgICAgIC"
    "AgIGR0ICs9IHRpbWVkZWx0YShkYXlzPTEpCiAgICAgICAgICAgIHJldHVybiBkdAoKICAgICAgICAjI"
    "CJ0b21vcnJvdyBhdCAuLi4iICAocmVjdXJzZSBvbiB0aGUgImF0IiBwYXJ0KQogICAgICAgIGlmICJ0"
    "b21vcnJvdyIgaW4gbG93OgogICAgICAgICAgICB0b21vcnJvd190ZXh0ID0gcmUuc3ViKHIidG9tb3J"
    "yb3ciLCAiIiwgbG93KS5zdHJpcCgpCiAgICAgICAgICAgIHJlc3VsdCA9IFRhc2tNYW5hZ2VyLnBhcn"
    "NlX2R1ZV9kYXRldGltZSh0b21vcnJvd190ZXh0KQogICAgICAgICAgICBpZiByZXN1bHQ6CiAgICAgI"
    "CAgICAgICAgICByZXR1cm4gcmVzdWx0ICsgdGltZWRlbHRhKGRheXM9MSkKCiAgICAgICAgcmV0dXJu"
    "IE5vbmUKCgojIOKUgOKUgCBSRVFVSVJFTUVOVFMuVFhUIEdFTkVSQVRPUiDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIAKZGVmIHdyaXRlX3JlcXVpcmVtZW50c190eHQoKSAtPiBOb25lOgogICAgIiIiCiAg"
    "ICBXcml0ZSByZXF1aXJlbWVudHMudHh0IG5leHQgdG8gdGhlIGRlY2sgZmlsZSBvbiBmaXJzdCBydW4"
    "uCiAgICBIZWxwcyB1c2VycyBpbnN0YWxsIGFsbCBkZXBlbmRlbmNpZXMgd2l0aCBvbmUgcGlwIGNvbW"
    "1hbmQuCiAgICAiIiIKICAgIHJlcV9wYXRoID0gUGF0aChDRkcuZ2V0KCJiYXNlX2RpciIsIHN0cihTQ"
    "1JJUFRfRElSKSkpIC8gInJlcXVpcmVtZW50cy50eHQiCiAgICBpZiByZXFfcGF0aC5leGlzdHMoKToK"
    "ICAgICAgICByZXR1cm4KCiAgICBjb250ZW50ID0gIiIiXAojIE1vcmdhbm5hIERlY2sg4oCUIFJlcXV"
    "pcmVkIERlcGVuZGVuY2llcwojIEluc3RhbGwgYWxsIHdpdGg6IHBpcCBpbnN0YWxsIC1yIHJlcXVpcm"
    "VtZW50cy50eHQKCiMgQ29yZSBVSQpQeVNpZGU2CgojIFNjaGVkdWxpbmcgKGlkbGUgdGltZXIsIGF1d"
    "G9zYXZlLCByZWZsZWN0aW9uIGN5Y2xlcykKYXBzY2hlZHVsZXIKCiMgTG9nZ2luZwpsb2d1cnUKCiMg"
    "U291bmQgcGxheWJhY2sgKFdBViArIE1QMykKcHlnYW1lCgojIERlc2t0b3Agc2hvcnRjdXQgY3JlYXR"
    "pb24gKFdpbmRvd3Mgb25seSkKcHl3aW4zMgoKIyBTeXN0ZW0gbW9uaXRvcmluZyAoQ1BVLCBSQU0sIG"
    "RyaXZlcywgbmV0d29yaykKcHN1dGlsCgojIEhUVFAgcmVxdWVzdHMKcmVxdWVzdHMKCiMgR29vZ2xlI"
    "GludGVncmF0aW9uIChDYWxlbmRhciwgRHJpdmUsIERvY3MsIEdtYWlsKQpnb29nbGUtYXBpLXB5dGhv"
    "bi1jbGllbnQKZ29vZ2xlLWF1dGgtb2F1dGhsaWIKZ29vZ2xlLWF1dGgKCiMg4pSA4pSAIE9wdGlvbmF"
    "sIChsb2NhbCBtb2RlbCBvbmx5KSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBVbmNvbW1lbnQgaWYgdXNp"
    "bmcgYSBsb2NhbCBIdWdnaW5nRmFjZSBtb2RlbDoKIyB0b3JjaAojIHRyYW5zZm9ybWVycwojIGFjY2V"
    "sZXJhdGUKCiMg4pSA4pSAIE9wdGlvbmFsIChOVklESUEgR1BVIG1vbml0b3JpbmcpIOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFVuY29t"
    "bWVudCBpZiB5b3UgaGF2ZSBhbiBOVklESUEgR1BVOgojIHB5bnZtbAoiIiIKICAgIHJlcV9wYXRoLnd"
    "yaXRlX3RleHQoY29udGVudCwgZW5jb2Rpbmc9InV0Zi04IikKCgojIOKUgOKUgCBQQVNTIDQgQ09NUE"
    "xFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSACiMgTWVtb3J5LCBTZXNzaW9uLCBMZXNzb25zTGVhcm5lZCwgVGFza01hbmFnZXIgYWxsIGRlZm"
    "luZWQuCiMgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGF1dG8tc2VlZGVkIG9uIGZpcnN0IHJ1bi4KIyByZ"
    "XF1aXJlbWVudHMudHh0IHdyaXR0ZW4gb24gZmlyc3QgcnVuLgojCiMgTmV4dDogUGFzcyA1IOKAlCBU"
    "YWIgQ29udGVudCBDbGFzc2VzCiMgKFNMU2NhbnNUYWIsIFNMQ29tbWFuZHNUYWIsIEpvYlRyYWNrZXJ"
    "UYWIsIFJlY29yZHNUYWIsCiMgIFRhc2tzVGFiLCBTZWxmVGFiLCBEaWFnbm9zdGljc1RhYikKCgojIO"
    "KVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVk"
    "OKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOK"
    "VkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkA"
    "ojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgNTogVEFCIENPTlRFTlQgQ0xBU1NFUwojCiMgVGFicyBkZ"
    "WZpbmVkIGhlcmU6CiMgICBTTFNjYW5zVGFiICAgICAg4oCUIGdyaW1vaXJlLWNhcmQgc3R5bGUsIHJl"
    "YnVpbHQgKERlbGV0ZSBhZGRlZCwgTW9kaWZ5IGZpeGVkLAojICAgICAgICAgICAgICAgICAgICAgcGF"
    "yc2VyIGZpeGVkLCBjb3B5LXRvLWNsaXBib2FyZCBwZXIgaXRlbSkKIyAgIFNMQ29tbWFuZHNUYWIgIC"
    "DigJQgZ290aGljIHRhYmxlLCBjb3B5IGNvbW1hbmQgdG8gY2xpcGJvYXJkCiMgICBKb2JUcmFja2VyV"
    "GFiICAg4oCUIGZ1bGwgcmVidWlsZCBmcm9tIHNwZWMsIENTVi9UU1YgZXhwb3J0CiMgICBSZWNvcmRz"
    "VGFiICAgICAg4oCUIEdvb2dsZSBEcml2ZS9Eb2NzIHdvcmtzcGFjZQojICAgVGFza3NUYWIgICAgICA"
    "gIOKAlCB0YXNrIHJlZ2lzdHJ5ICsgbWluaSBjYWxlbmRhcgojICAgU2VsZlRhYiAgICAgICAgIOKAlC"
    "BpZGxlIG5hcnJhdGl2ZSBvdXRwdXQgKyBQb0kgbGlzdAojICAgRGlhZ25vc3RpY3NUYWIgIOKAlCBsb"
    "2d1cnUgb3V0cHV0ICsgaGFyZHdhcmUgcmVwb3J0ICsgam91cm5hbCBsb2FkIG5vdGljZXMKIyAgIExl"
    "c3NvbnNUYWIgICAgICDigJQgTFNMIEZvcmJpZGRlbiBSdWxlc2V0ICsgY29kZSBsZXNzb25zIGJyb3d"
    "zZXIKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZ"
    "DilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDil"
    "ZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZD"
    "ilZDilZAKCmltcG9ydCByZSBhcyBfcmUKCgojIOKUgOKUgCBTSEFSRUQgR09USElDIFRBQkxFIFNUWU"
    "xFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgX2dvdGhpY190YWJsZV9zdHlsZSgpIC0"
    "+IHN0cjoKICAgIHJldHVybiBmIiIiCiAgICAgICAgUVRhYmxlV2lkZ2V0IHt7CiAgICAgICAgICAgIG"
    "JhY2tncm91bmQ6IHtDX0JHMn07CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgICAgICAgI"
    "CAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAgICBncmlkbGluZS1j"
    "b2xvcjoge0NfQk9SREVSfTsKICAgICAgICAgICAgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJ"
    "pZjsKICAgICAgICAgICAgZm9udC1zaXplOiAxMXB4OwogICAgICAgIH19CiAgICAgICAgUVRhYmxlV2"
    "lkZ2V0OjppdGVtOnNlbGVjdGVkIHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fR"
    "ElNfTsKICAgICAgICAgICAgY29sb3I6IHtDX0dPTERfQlJJR0hUfTsKICAgICAgICB9fQogICAgICAg"
    "IFFUYWJsZVdpZGdldDo6aXRlbTphbHRlcm5hdGUge3sKICAgICAgICAgICAgYmFja2dyb3VuZDoge0N"
    "fQkczfTsKICAgICAgICB9fQogICAgICAgIFFIZWFkZXJWaWV3OjpzZWN0aW9uIHt7CiAgICAgICAgIC"
    "AgIGJhY2tncm91bmQ6IHtDX0JHM307CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgICAgI"
    "CAgICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAgICBwYWRkaW5n"
    "OiA0cHggNnB4OwogICAgICAgICAgICBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOwogICA"
    "gICAgICAgICBmb250LXNpemU6IDEwcHg7CiAgICAgICAgICAgIGZvbnQtd2VpZ2h0OiBib2xkOwogIC"
    "AgICAgICAgICBsZXR0ZXItc3BhY2luZzogMXB4OwogICAgICAgIH19CiAgICAiIiIKCmRlZiBfZ290a"
    "GljX2J0bih0ZXh0OiBzdHIsIHRvb2x0aXA6IHN0ciA9ICIiKSAtPiBRUHVzaEJ1dHRvbjoKICAgIGJ0"
    "biA9IFFQdXNoQnV0dG9uKHRleHQpCiAgICBidG4uc2V0U3R5bGVTaGVldCgKICAgICAgICBmImJhY2t"
    "ncm91bmQ6IHtDX0NSSU1TT05fRElNfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgZiJib3JkZX"
    "I6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgZiJmb"
    "250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7ICIKICAgICAgICBm"
    "ImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiA0cHggMTBweDsgbGV0dGVyLXNwYWNpbmc6IDFweDs"
    "iCiAgICApCiAgICBpZiB0b29sdGlwOgogICAgICAgIGJ0bi5zZXRUb29sVGlwKHRvb2x0aXApCiAgIC"
    "ByZXR1cm4gYnRuCgpkZWYgX3NlY3Rpb25fbGJsKHRleHQ6IHN0cikgLT4gUUxhYmVsOgogICAgbGJsI"
    "D0gUUxhYmVsKHRleHQpCiAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICBmImNvbG9yOiB7Q19H"
    "T0xEfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgZiJsZXR0ZXI"
    "tc3BhY2luZzogMnB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICkKICAgIH"
    "JldHVybiBsYmwKCgojIOKUgOKUgCBTTCBTQ0FOUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNMU2NhbnNUYW"
    "IoUVdpZGdldCk6CiAgICAiIiIKICAgIFNlY29uZCBMaWZlIGF2YXRhciBzY2FubmVyIHJlc3VsdHMgb"
    "WFuYWdlci4KICAgIFJlYnVpbHQgZnJvbSBzcGVjOgogICAgICAtIENhcmQvZ3JpbW9pcmUtZW50cnkg"
    "c3R5bGUgZGlzcGxheQogICAgICAtIEFkZCAod2l0aCB0aW1lc3RhbXAtYXdhcmUgcGFyc2VyKQogICA"
    "gICAtIERpc3BsYXkgKGNsZWFuIGl0ZW0vY3JlYXRvciB0YWJsZSkKICAgICAgLSBNb2RpZnkgKGVkaX"
    "QgbmFtZSwgZGVzY3JpcHRpb24sIGluZGl2aWR1YWwgaXRlbXMpCiAgICAgIC0gRGVsZXRlICh3YXMgb"
    "Wlzc2luZyDigJQgbm93IHByZXNlbnQpCiAgICAgIC0gUmUtcGFyc2UgKHdhcyAnUmVmcmVzaCcg4oCU"
    "IHJlLXJ1bnMgcGFyc2VyIG9uIHN0b3JlZCByYXcgdGV4dCkKICAgICAgLSBDb3B5LXRvLWNsaXBib2F"
    "yZCBvbiBhbnkgaXRlbQogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1lbW9yeV9kaXI6IF"
    "BhdGgsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgI"
    "CBzZWxmLl9wYXRoICAgID0gY2ZnX3BhdGgoInNsIikgLyAic2xfc2NhbnMuanNvbmwiCiAgICAgICAg"
    "c2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQ6IE9"
    "wdGlvbmFsW3N0cl0gPSBOb25lCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucm"
    "VmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRV"
    "kJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQp"
    "CiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgQnV0dG9uIGJhcgogICAgICAgIGJ"
    "hciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgICA9IF9nb3RoaWNfYnRuKC"
    "LinKYgQWRkIiwgICAgICJBZGQgYSBuZXcgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRuX2Rpc3BsYXkgP"
    "SBfZ290aGljX2J0bigi4p2nIERpc3BsYXkiLCAiU2hvdyBzZWxlY3RlZCBzY2FuIGRldGFpbHMiKQog"
    "ICAgICAgIHNlbGYuX2J0bl9tb2RpZnkgID0gX2dvdGhpY19idG4oIuKcpyBNb2RpZnkiLCAgIkVkaXQ"
    "gc2VsZWN0ZWQgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSAgPSBfZ290aGljX2J0bigi4p"
    "yXIERlbGV0ZSIsICAiRGVsZXRlIHNlbGVjdGVkIHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9yZXBhc"
    "nNlID0gX2dvdGhpY19idG4oIuKGuyBSZS1wYXJzZSIsIlJlLXBhcnNlIHJhdyB0ZXh0IG9mIHNlbGVj"
    "dGVkIHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Nob3d"
    "fYWRkKQogICAgICAgIHNlbGYuX2J0bl9kaXNwbGF5LmNsaWNrZWQuY29ubmVjdChzZWxmLl9zaG93X2"
    "Rpc3BsYXkpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2hvd"
    "19tb2RpZnkpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9f"
    "ZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl9yZXBhcnNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19"
    "yZXBhcnNlKQogICAgICAgIGZvciBiIGluIChzZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fZGlzcGxheS"
    "wgc2VsZi5fYnRuX21vZGlmeSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSwgc2VsZ"
    "i5fYnRuX3JlcGFyc2UpOgogICAgICAgICAgICBiYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYmFyLmFk"
    "ZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAgICAgIyBTdGFjazogbGl"
    "zdCB2aWV3IHwgYWRkIGZvcm0gfCBkaXNwbGF5IHwgbW9kaWZ5CiAgICAgICAgc2VsZi5fc3RhY2sgPS"
    "BRU3RhY2tlZFdpZGdldCgpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fc3RhY2ssIDEpCgogI"
    "CAgICAgICMg4pSA4pSAIFBBR0UgMDogc2NhbiBsaXN0IChncmltb2lyZSBjYXJkcykg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSACiAgICAgICAgcDAgPSBRV2lkZ2V0KCkKICAgICAgICBsMCA9IFFWQm94TGF5b3V0KHAwKQogIC"
    "AgICAgIGwwLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlbGYuX2NhcmRfc"
    "2Nyb2xsID0gUVNjcm9sbEFyZWEoKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFdpZGdldFJl"
    "c2l6YWJsZShUcnVlKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFN0eWxlU2hlZXQoZiJiYWN"
    "rZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IG5vbmU7IikKICAgICAgICBzZWxmLl9jYXJkX2NvbnRhaW"
    "5lciA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0ICAgID0gUVZCb3hMYXlvdXQoc"
    "2VsZi5fY2FyZF9jb250YWluZXIpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuc2V0Q29udGVudHNN"
    "YXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuc2V0U3BhY2luZyg0KQo"
    "gICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LmFkZFN0cmV0Y2goKQogICAgICAgIHNlbGYuX2NhcmRfc2"
    "Nyb2xsLnNldFdpZGdldChzZWxmLl9jYXJkX2NvbnRhaW5lcikKICAgICAgICBsMC5hZGRXaWRnZXQoc"
    "2VsZi5fY2FyZF9zY3JvbGwpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAwKQoKICAgICAg"
    "ICAjIOKUgOKUgCBQQUdFIDE6IGFkZCBmb3JtIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAxID0gUVdpZGdldCgpC"
    "iAgICAgICAgbDEgPSBRVkJveExheW91dChwMSkKICAgICAgICBsMS5zZXRDb250ZW50c01hcmdpbnMo"
    "NCwgNCwgNCwgNCkKICAgICAgICBsMS5zZXRTcGFjaW5nKDQpCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9"
    "zZWN0aW9uX2xibCgi4p2nIFNDQU4gTkFNRSAoYXV0by1kZXRlY3RlZCkiKSkKICAgICAgICBzZWxmLl"
    "9hZGRfbmFtZSAgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZ"
    "GVyVGV4dCgiQXV0by1kZXRlY3RlZCBmcm9tIHNjYW4gdGV4dCIpCiAgICAgICAgbDEuYWRkV2lkZ2V0"
    "KHNlbGYuX2FkZF9uYW1lKQogICAgICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBERVN"
    "DUklQVElPTiIpKQogICAgICAgIHNlbGYuX2FkZF9kZXNjICA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2"
    "VsZi5fYWRkX2Rlc2Muc2V0TWF4aW11bUhlaWdodCg2MCkKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZ"
    "i5fYWRkX2Rlc2MpCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFJBVyBTQ0FO"
    "IFRFWFQgKHBhc3RlIGhlcmUpIikpCiAgICAgICAgc2VsZi5fYWRkX3JhdyAgID0gUVRleHRFZGl0KCk"
    "KICAgICAgICBzZWxmLl9hZGRfcmF3LnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAgICAgIlBhc3"
    "RlIHRoZSByYXcgU2Vjb25kIExpZmUgc2NhbiBvdXRwdXQgaGVyZS5cbiIKICAgICAgICAgICAgIlRpb"
    "WVzdGFtcHMgbGlrZSBbMTE6NDddIHdpbGwgYmUgdXNlZCB0byBzcGxpdCBpdGVtcyBjb3JyZWN0bHku"
    "IgogICAgICAgICkKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX3JhdywgMSkKICAgICAgICA"
    "jIFByZXZpZXcgb2YgcGFyc2VkIGl0ZW1zCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibC"
    "gi4p2nIFBBUlNFRCBJVEVNUyBQUkVWSUVXIikpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcgPSBRV"
    "GFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRIb3Jpem9udGFsSGVh"
    "ZGVyTGFiZWxzKFsiSXRlbSIsICJDcmVhdG9yIl0pCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaG9"
    "yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZG"
    "VyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaG9yaXpvb"
    "nRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmll"
    "dy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0TWF4aW11bUh"
    "laWdodCgxMjApCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0U3R5bGVTaGVldChfZ290aGljX3"
    "RhYmxlX3N0eWxlKCkpCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9wcmV2aWV3KQogICAgI"
    "CAgIHNlbGYuX2FkZF9yYXcudGV4dENoYW5nZWQuY29ubmVjdChzZWxmLl9wcmV2aWV3X3BhcnNlKQoK"
    "ICAgICAgICBidG5zMSA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzMSA9IF9nb3RoaWNfYnRuKCLinKY"
    "gU2F2ZSIpOyBjMSA9IF9nb3RoaWNfYnRuKCLinJcgQ2FuY2VsIikKICAgICAgICBzMS5jbGlja2VkLm"
    "Nvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIGMxLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlb"
    "GYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKSkKICAgICAgICBidG5zMS5hZGRXaWRnZXQoczEpOyBi"
    "dG5zMS5hZGRXaWRnZXQoYzEpOyBidG5zMS5hZGRTdHJldGNoKCkKICAgICAgICBsMS5hZGRMYXlvdXQ"
    "oYnRuczEpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAxKQoKICAgICAgICAjIOKUgOKUgC"
    "BQQUdFIDI6IGRpc3BsYXkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDIgPSBRV2lkZ2V0KCkKICAgICAgICB"
    "sMiA9IFFWQm94TGF5b3V0KHAyKQogICAgICAgIGwyLnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LC"
    "A0KQogICAgICAgIHNlbGYuX2Rpc3BfbmFtZSAgPSBRTGFiZWwoKQogICAgICAgIHNlbGYuX2Rpc3Bfb"
    "mFtZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0JSSUdIVH07IGZv"
    "bnQtc2l6ZTogMTNweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWl"
    "seToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjIC"
    "A9IFFMYWJlbCgpCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFdvcmRXcmFwKFRydWUpCiAgICAgI"
    "CAgc2VsZi5fZGlzcF9kZXNjLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RF"
    "WFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyI"
    "KICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAyKQogIC"
    "AgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIkl0ZW0iLCAiQ"
    "3JlYXRvciJdKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNl"
    "Y3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV"
    "0Y2gpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvbl"
    "Jlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKI"
    "CAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgp"
    "KQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0Q29udGV4dE1lbnVQb2xpY3koCiAgICAgICAgICA"
    "gIFF0LkNvbnRleHRNZW51UG9saWN5LkN1c3RvbUNvbnRleHRNZW51KQogICAgICAgIHNlbGYuX2Rpc3"
    "BfdGFibGUuY3VzdG9tQ29udGV4dE1lbnVSZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZ"
    "i5faXRlbV9jb250ZXh0X21lbnUpCgogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9kaXNwX25hbWUp"
    "CiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2Rpc3BfZGVzYykKICAgICAgICBsMi5hZGRXaWRnZXQ"
    "oc2VsZi5fZGlzcF90YWJsZSwgMSkKCiAgICAgICAgY29weV9oaW50ID0gUUxhYmVsKCJSaWdodC1jbG"
    "ljayBhbnkgaXRlbSB0byBjb3B5IGl0IHRvIGNsaXBib2FyZC4iKQogICAgICAgIGNvcHlfaGludC5zZ"
    "XRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTog"
    "OXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgbDI"
    "uYWRkV2lkZ2V0KGNvcHlfaGludCkKCiAgICAgICAgYmsyID0gX2dvdGhpY19idG4oIuKXgCBCYWNrIi"
    "kKICAgICAgICBiazIuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fc3RhY2suc2V0Q3VycmVud"
    "EluZGV4KDApKQogICAgICAgIGwyLmFkZFdpZGdldChiazIpCiAgICAgICAgc2VsZi5fc3RhY2suYWRk"
    "V2lkZ2V0KHAyKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDM6IG1vZGlmeSDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKI"
    "CAgICAgICBwMyA9IFFXaWRnZXQoKQogICAgICAgIGwzID0gUVZCb3hMYXlvdXQocDMpCiAgICAgICAg"
    "bDMuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgbDMuc2V0U3BhY2luZyg0KQo"
    "gICAgICAgIGwzLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBOQU1FIikpCiAgICAgICAgc2VsZi"
    "5fbW9kX25hbWUgPSBRTGluZUVkaXQoKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9tb2RfbmFtZ"
    "SkKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgREVTQ1JJUFRJT04iKSkKICAg"
    "ICAgICBzZWxmLl9tb2RfZGVzYyA9IFFMaW5lRWRpdCgpCiAgICAgICAgbDMuYWRkV2lkZ2V0KHNlbGY"
    "uX21vZF9kZXNjKQogICAgICAgIGwzLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBJVEVNUyAoZG"
    "91YmxlLWNsaWNrIHRvIGVkaXQpIikpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlID0gUVRhYmxlV2lkZ"
    "2V0KDAsIDIpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMo"
    "WyJJdGVtIiwgIkNyZWF0b3IiXSkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuaG9yaXpvbnRhbEhlYWR"
    "lcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpem"
    "VNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZ"
    "XRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5T"
    "dHJldGNoKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGV"
    "fc3R5bGUoKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fbW9kX3RhYmxlLCAxKQoKICAgICAgIC"
    "BidG5zMyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzMyA9IF9nb3RoaWNfYnRuKCLinKYgU2F2ZSIpO"
    "yBjMyA9IF9nb3RoaWNfYnRuKCLinJcgQ2FuY2VsIikKICAgICAgICBzMy5jbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5fZG9fbW9kaWZ5X3NhdmUpCiAgICAgICAgYzMuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2V"
    "sZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDApKQogICAgICAgIGJ0bnMzLmFkZFdpZGdldChzMyk7IG"
    "J0bnMzLmFkZFdpZGdldChjMyk7IGJ0bnMzLmFkZFN0cmV0Y2goKQogICAgICAgIGwzLmFkZExheW91d"
    "ChidG5zMykKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDMpCgogICAgIyDilIDilIAgUEFS"
    "U0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgQ"
    "HN0YXRpY21ldGhvZAogICAgZGVmIHBhcnNlX3NjYW5fdGV4dChyYXc6IHN0cikgLT4gdHVwbGVbc3Ry"
    "LCBsaXN0W2RpY3RdXToKICAgICAgICAiIiIKICAgICAgICBQYXJzZSByYXcgU0wgc2NhbiBvdXRwdXQ"
    "gaW50byAoYXZhdGFyX25hbWUsIGl0ZW1zKS4KCiAgICAgICAgS0VZIEZJWDogQmVmb3JlIHNwbGl0dG"
    "luZywgaW5zZXJ0IG5ld2xpbmVzIGJlZm9yZSBldmVyeSBbSEg6TU1dCiAgICAgICAgdGltZXN0YW1wI"
    "HNvIHNpbmdsZS1saW5lIHBhc3RlcyB3b3JrIGNvcnJlY3RseS4KCiAgICAgICAgRXhwZWN0ZWQgZm9y"
    "bWF0OgogICAgICAgICAgICBbMTE6NDddIEF2YXRhck5hbWUncyBwdWJsaWMgYXR0YWNobWVudHM6CiA"
    "gICAgICAgICAgIFsxMTo0N10gLjogSXRlbSBOYW1lIFtBdHRhY2htZW50XSBDUkVBVE9SOiBDcmVhdG"
    "9yTmFtZSBbMTE6NDddIC4uLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCByYXcuc3RyaXAoKToKI"
    "CAgICAgICAgICAgcmV0dXJuICJVTktOT1dOIiwgW10KCiAgICAgICAgIyDilIDilIAgU3RlcCAxOiBu"
    "b3JtYWxpemUg4oCUIGluc2VydCBuZXdsaW5lcyBiZWZvcmUgdGltZXN0YW1wcyDilIDilIDilIDilID"
    "ilIDilIAKICAgICAgICBub3JtYWxpemVkID0gX3JlLnN1YihyJ1xzKihcW1xkezEsMn06XGR7Mn1cXS"
    "knLCByJ1xuXDEnLCByYXcpCiAgICAgICAgbGluZXMgPSBbbC5zdHJpcCgpIGZvciBsIGluIG5vcm1hb"
    "Gl6ZWQuc3BsaXRsaW5lcygpIGlmIGwuc3RyaXAoKV0KCiAgICAgICAgIyDilIDilIAgU3RlcCAyOiBl"
    "eHRyYWN0IGF2YXRhciBuYW1lIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogIC"
    "AgICAgIGF2YXRhcl9uYW1lID0gIlVOS05PV04iCiAgICAgICAgZm9yIGxpbmUgaW4gbGluZXM6CiAgI"
    "CAgICAgICAgICMgIkF2YXRhck5hbWUncyBwdWJsaWMgYXR0YWNobWVudHMiIG9yIHNpbWlsYXIKICAg"
    "ICAgICAgICAgbSA9IF9yZS5zZWFyY2goCiAgICAgICAgICAgICAgICByIihcd1tcd1xzXSs/KSdzXHM"
    "rcHVibGljXHMrYXR0YWNobWVudHMiLAogICAgICAgICAgICAgICAgbGluZSwgX3JlLkkKICAgICAgIC"
    "AgICAgKQogICAgICAgICAgICBpZiBtOgogICAgICAgICAgICAgICAgYXZhdGFyX25hbWUgPSBtLmdyb"
    "3VwKDEpLnN0cmlwKCkKICAgICAgICAgICAgICAgIGJyZWFrCgogICAgICAgICMg4pSA4pSAIFN0ZXAg"
    "MzogZXh0cmFjdCBpdGVtcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIAKICAgICAgICBpdGVtcyA9IFtdCiAgICAgICAgZm9yIGxpbmUgaW4gbGluZXM6C"
    "iAgICAgICAgICAgICMgU3RyaXAgbGVhZGluZyB0aW1lc3RhbXAKICAgICAgICAgICAgY29udGVudCA9"
    "IF9yZS5zdWIocideXFtcZHsxLDJ9OlxkezJ9XF1ccyonLCAnJywgbGluZSkuc3RyaXAoKQogICAgICA"
    "gICAgICBpZiBub3QgY29udGVudDoKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIC"
    "MgU2tpcCBoZWFkZXIgbGluZXMKICAgICAgICAgICAgaWYgIidzIHB1YmxpYyBhdHRhY2htZW50cyIga"
    "W4gY29udGVudC5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgaWYg"
    "Y29udGVudC5sb3dlcigpLnN0YXJ0c3dpdGgoIm9iamVjdCIpOgogICAgICAgICAgICAgICAgY29udGl"
    "udWUKICAgICAgICAgICAgIyBTa2lwIGRpdmlkZXIgbGluZXMg4oCUIGxpbmVzIHRoYXQgYXJlIG1vc3"
    "RseSBvbmUgcmVwZWF0ZWQgY2hhcmFjdGVyCiAgICAgICAgICAgICMgZS5nLiDiloLiloLiloLiloLil"
    "oLiloLiloLiloLiloLiloLiloLiloIgb3Ig4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQIG9yIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBzdHJ"
    "pcHBlZCA9IGNvbnRlbnQuc3RyaXAoIi46ICIpCiAgICAgICAgICAgIGlmIHN0cmlwcGVkIGFuZCBsZW"
    "4oc2V0KHN0cmlwcGVkKSkgPD0gMjoKICAgICAgICAgICAgICAgIGNvbnRpbnVlICAjIG9uZSBvciB0d"
    "28gdW5pcXVlIGNoYXJzID0gZGl2aWRlciBsaW5lCgogICAgICAgICAgICAjIFRyeSB0byBleHRyYWN0"
    "IENSRUFUT1I6IGZpZWxkCiAgICAgICAgICAgIGNyZWF0b3IgPSAiVU5LTk9XTiIKICAgICAgICAgICA"
    "gaXRlbV9uYW1lID0gY29udGVudAoKICAgICAgICAgICAgY3JlYXRvcl9tYXRjaCA9IF9yZS5zZWFyY2"
    "goCiAgICAgICAgICAgICAgICByJ0NSRUFUT1I6XHMqKFtcd1xzXSs/KSg/OlxzKlxbfCQpJywgY29ud"
    "GVudCwgX3JlLkkKICAgICAgICAgICAgKQogICAgICAgICAgICBpZiBjcmVhdG9yX21hdGNoOgogICAg"
    "ICAgICAgICAgICAgY3JlYXRvciAgID0gY3JlYXRvcl9tYXRjaC5ncm91cCgxKS5zdHJpcCgpCiAgICA"
    "gICAgICAgICAgICBpdGVtX25hbWUgPSBjb250ZW50WzpjcmVhdG9yX21hdGNoLnN0YXJ0KCldLnN0cm"
    "lwKCkKCiAgICAgICAgICAgICMgU3RyaXAgYXR0YWNobWVudCBwb2ludCBzdWZmaXhlcyBsaWtlIFtMZ"
    "WZ0X0Zvb3RdCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IF9yZS5zdWIocidccypcW1tcd1xzX10rXF0n"
    "LCAnJywgaXRlbV9uYW1lKS5zdHJpcCgpCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IGl0ZW1fbmFtZS5"
    "zdHJpcCgiLjogIikKCiAgICAgICAgICAgIGlmIGl0ZW1fbmFtZSBhbmQgbGVuKGl0ZW1fbmFtZSkgPi"
    "AxOgogICAgICAgICAgICAgICAgaXRlbXMuYXBwZW5kKHsiaXRlbSI6IGl0ZW1fbmFtZSwgImNyZWF0b"
    "3IiOiBjcmVhdG9yfSkKCiAgICAgICAgcmV0dXJuIGF2YXRhcl9uYW1lLCBpdGVtcwoKICAgICMg4pSA"
    "4pSAIENBUkQgUkVOREVSSU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9idWlsZ"
    "F9jYXJkcyhzZWxmKSAtPiBOb25lOgogICAgICAgICMgQ2xlYXIgZXhpc3RpbmcgY2FyZHMgKGtlZXAg"
    "c3RyZXRjaCkKICAgICAgICB3aGlsZSBzZWxmLl9jYXJkX2xheW91dC5jb3VudCgpID4gMToKICAgICA"
    "gICAgICAgaXRlbSA9IHNlbGYuX2NhcmRfbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICBpZiBpdG"
    "VtLndpZGdldCgpOgogICAgICAgICAgICAgICAgaXRlbS53aWRnZXQoKS5kZWxldGVMYXRlcigpCgogI"
    "CAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgY2FyZCA9IHNlbGYuX21h"
    "a2VfY2FyZChyZWMpCiAgICAgICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0Lmluc2VydFdpZGdldCgKICA"
    "gICAgICAgICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LmNvdW50KCkgLSAxLCBjYXJkCiAgICAgICAgIC"
    "AgICkKCiAgICBkZWYgX21ha2VfY2FyZChzZWxmLCByZWM6IGRpY3QpIC0+IFFXaWRnZXQ6CiAgICAgI"
    "CAgY2FyZCA9IFFGcmFtZSgpCiAgICAgICAgaXNfc2VsZWN0ZWQgPSByZWMuZ2V0KCJyZWNvcmRfaWQi"
    "KSA9PSBzZWxmLl9zZWxlY3RlZF9pZAogICAgICAgIGNhcmQuc2V0U3R5bGVTaGVldCgKICAgICAgICA"
    "gICAgZiJiYWNrZ3JvdW5kOiB7JyMxYTBhMTAnIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19CRzN9OyAiCi"
    "AgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTiBpZiBpc19zZWxlY3RlZCBlb"
    "HNlIENfQk9SREVSfTsgIgogICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsgcGFkZGluZzog"
    "MnB4OyIKICAgICAgICApCiAgICAgICAgbGF5b3V0ID0gUUhCb3hMYXlvdXQoY2FyZCkKICAgICAgICB"
    "sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDgsIDYsIDgsIDYpCgogICAgICAgIG5hbWVfbGJsID0gUU"
    "xhYmVsKHJlYy5nZXQoIm5hbWUiLCAiVU5LTk9XTiIpKQogICAgICAgIG5hbWVfbGJsLnNldFN0eWxlU"
    "2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTERfQlJJR0hUIGlmIGlzX3NlbGVjdGVkIGVs"
    "c2UgQ19HT0xEfTsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTogMTFweDsgZm9udC13ZWlnaHQ6IGJ"
    "vbGQ7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgY2"
    "91bnQgPSBsZW4ocmVjLmdldCgiaXRlbXMiLCBbXSkpCiAgICAgICAgY291bnRfbGJsID0gUUxhYmVsK"
    "GYie2NvdW50fSBpdGVtcyIpCiAgICAgICAgY291bnRfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REV"
    "DS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgZGF0ZV9sYmwgPSBRTGFiZWwocmVjLm"
    "dldCgiY3JlYXRlZF9hdCIsICIiKVs6MTBdKQogICAgICAgIGRhdGVfbGJsLnNldFN0eWxlU2hlZXQoC"
    "iAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFt"
    "aWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGd"
    "ldChuYW1lX2xibCkKICAgICAgICBsYXlvdXQuYWRkU3RyZXRjaCgpCiAgICAgICAgbGF5b3V0LmFkZF"
    "dpZGdldChjb3VudF9sYmwpCiAgICAgICAgbGF5b3V0LmFkZFNwYWNpbmcoMTIpCiAgICAgICAgbGF5b"
    "3V0LmFkZFdpZGdldChkYXRlX2xibCkKCiAgICAgICAgIyBDbGljayB0byBzZWxlY3QKICAgICAgICBy"
    "ZWNfaWQgPSByZWMuZ2V0KCJyZWNvcmRfaWQiLCAiIikKICAgICAgICBjYXJkLm1vdXNlUHJlc3NFdmV"
    "udCA9IGxhbWJkYSBlLCByaWQ9cmVjX2lkOiBzZWxmLl9zZWxlY3RfY2FyZChyaWQpCiAgICAgICAgcm"
    "V0dXJuIGNhcmQKCiAgICBkZWYgX3NlbGVjdF9jYXJkKHNlbGYsIHJlY29yZF9pZDogc3RyKSAtPiBOb"
    "25lOgogICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkID0gcmVjb3JkX2lkCiAgICAgICAgc2VsZi5fYnVp"
    "bGRfY2FyZHMoKSAgIyBSZWJ1aWxkIHRvIHNob3cgc2VsZWN0aW9uIGhpZ2hsaWdodAoKICAgIGRlZiB"
    "fc2VsZWN0ZWRfcmVjb3JkKHNlbGYpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHJldHVybiBuZX"
    "h0KAogICAgICAgICAgICAociBmb3IgciBpbiBzZWxmLl9yZWNvcmRzCiAgICAgICAgICAgICBpZiByL"
    "mdldCgicmVjb3JkX2lkIikgPT0gc2VsZi5fc2VsZWN0ZWRfaWQpLAogICAgICAgICAgICBOb25lCiAg"
    "ICAgICAgKQoKICAgICMg4pSA4pSAIEFDVElPTlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNl"
    "bGYuX3JlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgIyBFbnN1cmUgcmVjb3J"
    "kX2lkIGZpZWxkIGV4aXN0cwogICAgICAgIGNoYW5nZWQgPSBGYWxzZQogICAgICAgIGZvciByIGluIH"
    "NlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGlmIG5vdCByLmdldCgicmVjb3JkX2lkIik6CiAgICAgI"
    "CAgICAgICAgICByWyJyZWNvcmRfaWQiXSA9IHIuZ2V0KCJpZCIpIG9yIHN0cih1dWlkLnV1aWQ0KCkp"
    "CiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgIGlmIGNoYW5nZWQ6CiAgICAgICA"
    "gICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5fYn"
    "VpbGRfY2FyZHMoKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKQoKICAgIGRlZ"
    "iBfcHJldmlld19wYXJzZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJhdyA9IHNlbGYuX2FkZF9yYXcu"
    "dG9QbGFpblRleHQoKQogICAgICAgIG5hbWUsIGl0ZW1zID0gc2VsZi5wYXJzZV9zY2FuX3RleHQocmF"
    "3KQogICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dChuYW1lKQogICAgICAgIH"
    "NlbGYuX2FkZF9wcmV2aWV3LnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGl0IGluIGl0ZW1zWzoyM"
    "F06ICAjIHByZXZpZXcgZmlyc3QgMjAKICAgICAgICAgICAgciA9IHNlbGYuX2FkZF9wcmV2aWV3LnJv"
    "d0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaW5zZXJ0Um93KHIpCiAgICAgICA"
    "gICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldEl0ZW0ociwgMCwgUVRhYmxlV2lkZ2V0SXRlbShpdFsiaX"
    "RlbSJdKSkKICAgICAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0SXRlbShyLCAxLCBRVGFibGVXa"
    "WRnZXRJdGVtKGl0WyJjcmVhdG9yIl0pKQoKICAgIGRlZiBfc2hvd19hZGQoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9hZGRfbmFtZS5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX25hbWUuc2V0UGx"
    "hY2Vob2xkZXJUZXh0KCJBdXRvLWRldGVjdGVkIGZyb20gc2NhbiB0ZXh0IikKICAgICAgICBzZWxmLl"
    "9hZGRfZGVzYy5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX3Jhdy5jbGVhcigpCiAgICAgICAgc2VsZ"
    "i5fYWRkX3ByZXZpZXcuc2V0Um93Q291bnQoMCkKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50"
    "SW5kZXgoMSkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIHJhdyAgPSBzZWx"
    "mLl9hZGRfcmF3LnRvUGxhaW5UZXh0KCkKICAgICAgICBuYW1lLCBpdGVtcyA9IHNlbGYucGFyc2Vfc2"
    "Nhbl90ZXh0KHJhdykKICAgICAgICBvdmVycmlkZV9uYW1lID0gc2VsZi5fYWRkX25hbWUudGV4dCgpL"
    "nN0cmlwKCkKICAgICAgICBub3cgID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0"
    "KCkKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHN0cih1dWlkLnV"
    "1aWQ0KCkpLAogICAgICAgICAgICAicmVjb3JkX2lkIjogICBzdHIodXVpZC51dWlkNCgpKSwKICAgIC"
    "AgICAgICAgIm5hbWUiOiAgICAgICAgb3ZlcnJpZGVfbmFtZSBvciBuYW1lLAogICAgICAgICAgICAiZ"
    "GVzY3JpcHRpb24iOiBzZWxmLl9hZGRfZGVzYy50b1BsYWluVGV4dCgpWzoyNDRdLAogICAgICAgICAg"
    "ICAiaXRlbXMiOiAgICAgICBpdGVtcywKICAgICAgICAgICAgInJhd190ZXh0IjogICAgcmF3LAogICA"
    "gICAgICAgICAiY3JlYXRlZF9hdCI6ICBub3csCiAgICAgICAgICAgICJ1cGRhdGVkX2F0IjogIG5vdy"
    "wKICAgICAgICB9CiAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQocmVjb3JkKQogICAgICAgIHdya"
    "XRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5fc2VsZWN0ZWRf"
    "aWQgPSByZWNvcmRbInJlY29yZF9pZCJdCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3N"
    "ob3dfZGlzcGxheShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY2"
    "9yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb"
    "24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNl"
    "bGVjdCBhIHNjYW4gdG8gZGlzcGxheS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9"
    "kaXNwX25hbWUuc2V0VGV4dChmIuKdpyB7cmVjLmdldCgnbmFtZScsJycpfSIpCiAgICAgICAgc2VsZi"
    "5fZGlzcF9kZXNjLnNldFRleHQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBzZWxmL"
    "l9kaXNwX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGl0IGluIHJlYy5nZXQoIml0ZW1z"
    "IixbXSk6CiAgICAgICAgICAgIHIgPSBzZWxmLl9kaXNwX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICA"
    "gICAgc2VsZi5fZGlzcF90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fZGlzcF90YW"
    "JsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgia"
    "XRlbSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAg"
    "ICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiY3JlYXRvciIsIlVOS05PV04iKSkpCiA"
    "gICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDIpCgogICAgZGVmIF9pdGVtX2NvbnRleH"
    "RfbWVudShzZWxmLCBwb3MpIC0+IE5vbmU6CiAgICAgICAgaWR4ID0gc2VsZi5fZGlzcF90YWJsZS5pb"
    "mRleEF0KHBvcykKICAgICAgICBpZiBub3QgaWR4LmlzVmFsaWQoKToKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgaXRlbV90ZXh0ICA9IChzZWxmLl9kaXNwX3RhYmxlLml0ZW0oaWR4LnJvdygpLCAwKSB"
    "vcgogICAgICAgICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgIC"
    "AgIGNyZWF0b3IgICAgPSAoc2VsZi5fZGlzcF90YWJsZS5pdGVtKGlkeC5yb3coKSwgMSkgb3IKICAgI"
    "CAgICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICBmcm9t"
    "IFB5U2lkZTYuUXRXaWRnZXRzIGltcG9ydCBRTWVudQogICAgICAgIG1lbnUgPSBRTWVudShzZWxmKQo"
    "gICAgICAgIG1lbnUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRz"
    "N9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DU"
    "klNU09OX0RJTX07IgogICAgICAgICkKICAgICAgICBhX2l0ZW0gICAgPSBtZW51LmFkZEFjdGlvbigi"
    "Q29weSBJdGVtIE5hbWUiKQogICAgICAgIGFfY3JlYXRvciA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5IEN"
    "yZWF0b3IiKQogICAgICAgIGFfYm90aCAgICA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5IEJvdGgiKQogIC"
    "AgICAgIGFjdGlvbiA9IG1lbnUuZXhlYyhzZWxmLl9kaXNwX3RhYmxlLnZpZXdwb3J0KCkubWFwVG9Hb"
    "G9iYWwocG9zKSkKICAgICAgICBjYiA9IFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKQogICAgICAgIGlm"
    "IGFjdGlvbiA9PSBhX2l0ZW06ICAgIGNiLnNldFRleHQoaXRlbV90ZXh0KQogICAgICAgIGVsaWYgYWN"
    "0aW9uID09IGFfY3JlYXRvcjogY2Iuc2V0VGV4dChjcmVhdG9yKQogICAgICAgIGVsaWYgYWN0aW9uID"
    "09IGFfYm90aDogIGNiLnNldFRleHQoZiJ7aXRlbV90ZXh0fSDigJQge2NyZWF0b3J9IikKCiAgICBkZ"
    "WYgX3Nob3dfbW9kaWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRf"
    "cmVjb3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1"
    "hdGlvbihzZWxmLCAiU0wgU2NhbnMiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIC"
    "AiU2VsZWN0IGEgc2NhbiB0byBtb2RpZnkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZ"
    "i5fbW9kX25hbWUuc2V0VGV4dChyZWMuZ2V0KCJuYW1lIiwiIikpCiAgICAgICAgc2VsZi5fbW9kX2Rl"
    "c2Muc2V0VGV4dChyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpKQogICAgICAgIHNlbGYuX21vZF90YWJ"
    "sZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiByZWMuZ2V0KCJpdGVtcyIsW10pOgogIC"
    "AgICAgICAgICByID0gc2VsZi5fbW9kX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fb"
    "W9kX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0SXRlbShy"
    "LCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShpdC5nZXQoIml0ZW0iLCIiKSkpCiA"
    "gICAgICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVG"
    "FibGVXaWRnZXRJdGVtKGl0LmdldCgiY3JlYXRvciIsIlVOS05PV04iKSkpCiAgICAgICAgc2VsZi5fc"
    "3RhY2suc2V0Q3VycmVudEluZGV4KDMpCgogICAgZGVmIF9kb19tb2RpZnlfc2F2ZShzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJ"
    "lYzoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjWyJuYW1lIl0gICAgICAgID0gc2VsZi5fbW"
    "9kX25hbWUudGV4dCgpLnN0cmlwKCkgb3IgIlVOS05PV04iCiAgICAgICAgcmVjWyJkZXNjcmlwdGlvb"
    "iJdID0gc2VsZi5fbW9kX2Rlc2MudGV4dCgpWzoyNDRdCiAgICAgICAgaXRlbXMgPSBbXQogICAgICAg"
    "IGZvciBpIGluIHJhbmdlKHNlbGYuX21vZF90YWJsZS5yb3dDb3VudCgpKToKICAgICAgICAgICAgaXQ"
    "gID0gKHNlbGYuX21vZF90YWJsZS5pdGVtKGksMCkgb3IgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleH"
    "QoKQogICAgICAgICAgICBjciAgPSAoc2VsZi5fbW9kX3RhYmxlLml0ZW0oaSwxKSBvciBRVGFibGVXa"
    "WRnZXRJdGVtKCIiKSkudGV4dCgpCiAgICAgICAgICAgIGl0ZW1zLmFwcGVuZCh7Iml0ZW0iOiBpdC5z"
    "dHJpcCgpIG9yICJVTktOT1dOIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAiY3JlYXRvciI6IGN"
    "yLnN0cmlwKCkgb3IgIlVOS05PV04ifSkKICAgICAgICByZWNbIml0ZW1zIl0gICAgICA9IGl0ZW1zCi"
    "AgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb"
    "3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAg"
    "ICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAgICA"
    "gIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgIC"
    "AgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgI"
    "CAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gZGVsZXRlLiIpCiAgICAgICAg"
    "ICAgIHJldHVybgogICAgICAgIG5hbWUgPSByZWMuZ2V0KCJuYW1lIiwidGhpcyBzY2FuIikKICAgICA"
    "gICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICBzZWxmLCAiRGVsZXRlIF"
    "NjYW4iLAogICAgICAgICAgICBmIkRlbGV0ZSAne25hbWV9Jz8gVGhpcyBjYW5ub3QgYmUgdW5kb25lL"
    "iIsCiAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94"
    "LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgKQogICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm9"
    "4LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAgc2VsZi5fcmVjb3JkcyA9IFtyIGZvciByIG"
    "luIHNlbGYuX3JlY29yZHMKICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiByLmdldCgicmVjb"
    "3JkX2lkIikgIT0gc2VsZi5fc2VsZWN0ZWRfaWRdCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYu"
    "X3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkID0gTm9uZQo"
    "gICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fcmVwYXJzZShzZWxmKSAtPiBOb2"
    "5lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlY"
    "zoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gcmUtcGFyc2U"
    "uIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmF3ID0gcmVjLmdldCgicmF3X3RleHQiLCIiKQ"
    "ogICAgICAgIGlmIG5vdCByYXc6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlb"
    "GYsICJSZS1wYXJzZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJObyByYXcg"
    "dGV4dCBzdG9yZWQgZm9yIHRoaXMgc2Nhbi4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBuYW1"
    "lLCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICByZWNbIml0ZW1zIl0gIC"
    "AgICA9IGl0ZW1zCiAgICAgICAgcmVjWyJuYW1lIl0gICAgICAgPSByZWNbIm5hbWUiXSBvciBuYW1lC"
    "iAgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29m"
    "b3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICA"
    "gICAgc2VsZi5yZWZyZXNoKCkKICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiUm"
    "UtcGFyc2VkIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIkZvdW5kIHtsZW4oaXRlb"
    "XMpfSBpdGVtcy4iKQoKCiMg4pSA4pSAIFNMIENPTU1BTkRTIFRBQiDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU0xDb21tYW5kc1RhY"
    "ihRV2lkZ2V0KToKICAgICIiIgogICAgU2Vjb25kIExpZmUgY29tbWFuZCByZWZlcmVuY2UgdGFibGUu"
    "CiAgICBHb3RoaWMgdGFibGUgc3R5bGluZy4gQ29weSBjb21tYW5kIHRvIGNsaXBib2FyZCBidXR0b24"
    "gcGVyIHJvdy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgIC"
    "AgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAgICA9IGNmZ19wY"
    "XRoKCJzbCIpIC8gInNsX2NvbW1hbmRzLmpzb25sIgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3Rb"
    "ZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQo"
    "KICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdX"
    "Qoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgI"
    "HJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCLinKYgQWRkIikKICAgICAgICBzZWxmLl9idG5fbW9"
    "kaWZ5ID0gX2dvdGhpY19idG4oIuKcpyBNb2RpZnkiKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgPS"
    "BfZ290aGljX2J0bigi4pyXIERlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX2NvcHkgICA9IF9nb3Roa"
    "WNfYnRuKCLip4kgQ29weSBDb21tYW5kIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICJDb3B5IHNlbGVjdGVkIGNvbW1hbmQgdG8gY2xpcGJvYXJkIikKICAgICAgICBzZWxmLl9"
    "idG5fcmVmcmVzaD0gX2dvdGhpY19idG4oIuKGuyBSZWZyZXNoIikKICAgICAgICBzZWxmLl9idG5fYW"
    "RkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeS5jb"
    "Glja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fY29weS5jbGlja2V"
    "kLmNvbm5lY3Qoc2VsZi5fY29weV9jb21tYW5kKQogICAgICAgIHNlbGYuX2J0bl9yZWZyZXNoLmNsaW"
    "NrZWQuY29ubmVjdChzZWxmLnJlZnJlc2gpCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsI"
    "HNlbGYuX2J0bl9tb2RpZnksIHNlbGYuX2J0bl9kZWxldGUsCiAgICAgICAgICAgICAgICAgIHNlbGYu"
    "X2J0bl9jb3B5LCBzZWxmLl9idG5fcmVmcmVzaCk6CiAgICAgICAgICAgIGJhci5hZGRXaWRnZXQoYik"
    "KICAgICAgICBiYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYmFyKQoKICAgIC"
    "AgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNlbGYuX3RhYmxlLnNld"
    "Ehvcml6b250YWxIZWFkZXJMYWJlbHMoWyJDb21tYW5kIiwgIkRlc2NyaXB0aW9uIl0pCiAgICAgICAg"
    "c2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICA"
    "gICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibG"
    "UuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRS"
    "GVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0"
    "aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9"
    "yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVH"
    "J1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoK"
    "SkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90YWJsZSwgMSkKCiAgICAgICAgaGludCA9IFFM"
    "YWJlbCgKICAgICAgICAgICAgIlNlbGVjdCBhIHJvdyBhbmQgY2xpY2sg4qeJIENvcHkgQ29tbWFuZCB"
    "0byBjb3B5IGp1c3QgdGhlIGNvbW1hbmQgdGV4dC4iCiAgICAgICAgKQogICAgICAgIGhpbnQuc2V0U3"
    "R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlwe"
    "DsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJvb3Qu"
    "YWRkV2lkZ2V0KGhpbnQpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWx"
    "mLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldF"
    "Jvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICByI"
    "D0gc2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3co"
    "cikKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVR"
    "hYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJjb21tYW5kIiwiIikpKQogICAgICAgICAgICBzZWxmLl90YW"
    "JsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoI"
    "mRlc2NyaXB0aW9uIiwiIikpKQoKICAgIGRlZiBfY29weV9jb21tYW5kKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgcm93IDwgMDoKICA"
    "gICAgICAgICAgcmV0dXJuCiAgICAgICAgaXRlbSA9IHNlbGYuX3RhYmxlLml0ZW0ocm93LCAwKQogIC"
    "AgICAgIGlmIGl0ZW06CiAgICAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0K"
    "Gl0ZW0udGV4dCgpKQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGxnID0g"
    "UURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiQWRkIENvbW1hbmQiKQogICA"
    "gICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTE"
    "R9OyIpCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKICAgICAgICBjbWQgID0gUUxpbmVFZ"
    "Gl0KCk7IGRlc2MgPSBRTGluZUVkaXQoKQogICAgICAgIGZvcm0uYWRkUm93KCJDb21tYW5kOiIsIGNt"
    "ZCkKICAgICAgICBmb3JtLmFkZFJvdygiRGVzY3JpcHRpb246IiwgZGVzYykKICAgICAgICBidG5zID0"
    "gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aG"
    "ljX2J0bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4L"
    "mNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRu"
    "cy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRucykKICAgICAgICBpZiBkbGcuZXh"
    "lYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgbm93ID0gZGF0ZX"
    "RpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAgcmVjID0gewogICAgI"
    "CAgICAgICAgICAgImlkIjogICAgICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICAg"
    "ICAiY29tbWFuZCI6ICAgICBjbWQudGV4dCgpLnN0cmlwKClbOjI0NF0sCiAgICAgICAgICAgICAgICA"
    "iZGVzY3JpcHRpb24iOiBkZXNjLnRleHQoKS5zdHJpcCgpWzoyNDRdLAogICAgICAgICAgICAgICAgIm"
    "NyZWF0ZWRfYXQiOiAgbm93LCAidXBkYXRlZF9hdCI6IG5vdywKICAgICAgICAgICAgfQogICAgICAgI"
    "CAgICBpZiByZWNbImNvbW1hbmQiXToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5k"
    "KHJlYykKICAgICAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHM"
    "pCiAgICAgICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fbW9kaWZ5KHNlbGYpIC"
    "0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgc"
    "m93IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZXR1cm4KICAg"
    "ICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiA"
    "gICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJNb2RpZnkgQ29tbWFuZCIpCiAgICAgICAgZGxnLnNldF"
    "N0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgI"
    "CBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAgIGNtZCAgPSBRTGluZUVkaXQocmVjLmdldCgi"
    "Y29tbWFuZCIsIiIpKQogICAgICAgIGRlc2MgPSBRTGluZUVkaXQocmVjLmdldCgiZGVzY3JpcHRpb24"
    "iLCIiKSkKICAgICAgICBmb3JtLmFkZFJvdygiQ29tbWFuZDoiLCBjbWQpCiAgICAgICAgZm9ybS5hZG"
    "RSb3coIkRlc2NyaXB0aW9uOiIsIGRlc2MpCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgI"
    "CAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAg"
    "ICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGx"
    "nLnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogIC"
    "AgICAgIGZvcm0uYWRkUm93KGJ0bnMpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpY"
    "WxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHJlY1siY29tbWFuZCJdICAgICA9IGNtZC50ZXh0"
    "KCkuc3RyaXAoKVs6MjQ0XQogICAgICAgICAgICByZWNbImRlc2NyaXB0aW9uIl0gPSBkZXNjLnRleHQ"
    "oKS5zdHJpcCgpWzoyNDRdCiAgICAgICAgICAgIHJlY1sidXBkYXRlZF9hdCJdICA9IGRhdGV0aW1lLm"
    "5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX"
    "3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9k"
    "b19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um9"
    "3KCkKICAgICAgICBpZiByb3cgPCAwIG9yIHJvdyA+PSBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgIC"
    "AgICAgIHJldHVybgogICAgICAgIGNtZCA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQoImNvbW1hbmQiL"
    "CJ0aGlzIGNvbW1hbmQiKQogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAg"
    "ICAgICAgIHNlbGYsICJEZWxldGUiLCBmIkRlbGV0ZSAne2NtZH0nPyIsCiAgICAgICAgICAgIFFNZXN"
    "zYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCi"
    "AgICAgICAgKQogICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllc"
    "zoKICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5wb3Aocm93KQogICAgICAgICAgICB3cml0ZV9qc29u"
    "bChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKCiM"
    "g4pSA4pSAIEpPQiBUUkFDS0VSIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSm9iVHJhY2tlclRhYihRV2lkZ2V0KToKICAgICI"
    "iIgogICAgSm9iIGFwcGxpY2F0aW9uIHRyYWNraW5nLiBGdWxsIHJlYnVpbGQgZnJvbSBzcGVjLgogIC"
    "AgRmllbGRzOiBDb21wYW55LCBKb2IgVGl0bGUsIERhdGUgQXBwbGllZCwgTGluaywgU3RhdHVzLCBOb"
    "3Rlcy4KICAgIE11bHRpLXNlbGVjdCBoaWRlL3VuaGlkZS9kZWxldGUuIENTViBhbmQgVFNWIGV4cG9y"
    "dC4KICAgIEhpZGRlbiByb3dzID0gY29tcGxldGVkL3JlamVjdGVkIOKAlCBzdGlsbCBzdG9yZWQsIGp"
    "1c3Qgbm90IHNob3duLgogICAgIiIiCgogICAgQ09MVU1OUyA9IFsiQ29tcGFueSIsICJKb2IgVGl0bG"
    "UiLCAiRGF0ZSBBcHBsaWVkIiwKICAgICAgICAgICAgICAgIkxpbmsiLCAiU3RhdHVzIiwgIk5vdGVzI"
    "l0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19p"
    "bml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BhdGggICAgPSBjZmdfcGF0aCgibWVtb3JpZXMiKSA"
    "vICJqb2JfdHJhY2tlci5qc29ubCIKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW1"
    "0KICAgICAgICBzZWxmLl9zaG93X2hpZGRlbiA9IEZhbHNlCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoK"
    "QogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJ"
    "naW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGJhciA9IF"
    "FIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgID0gX2dvdGhpY19idG4oIkFkZCIpC"
    "iAgICAgICAgc2VsZi5fYnRuX21vZGlmeSA9IF9nb3RoaWNfYnRuKCJNb2RpZnkiKQogICAgICAgIHNl"
    "bGYuX2J0bl9oaWRlICAgPSBfZ290aGljX2J0bigiQXJjaGl2ZSIsCiAgICAgICAgICAgICAgICAgICA"
    "gICAgICAgICAgICAgICAgICAgICAiTWFyayBzZWxlY3RlZCBhcyBjb21wbGV0ZWQvcmVqZWN0ZWQiKQ"
    "ogICAgICAgIHNlbGYuX2J0bl91bmhpZGUgPSBfZ290aGljX2J0bigiUmVzdG9yZSIsCiAgICAgICAgI"
    "CAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiUmVzdG9yZSBhcmNoaXZlZCBhcHBsaWNhdGlv"
    "bnMiKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgPSBfZ290aGljX2J0bigiRGVsZXRlIikKICAgICA"
    "gICBzZWxmLl9idG5fdG9nZ2xlID0gX2dvdGhpY19idG4oIlNob3cgQXJjaGl2ZWQiKQogICAgICAgIH"
    "NlbGYuX2J0bl9leHBvcnQgPSBfZ290aGljX2J0bigiRXhwb3J0IikKCiAgICAgICAgZm9yIGIgaW4gK"
    "HNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9tb2RpZnksIHNlbGYuX2J0bl9oaWRlLAogICAgICAgICAg"
    "ICAgICAgICBzZWxmLl9idG5fdW5oaWRlLCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICA"
    "gICBzZWxmLl9idG5fdG9nZ2xlLCBzZWxmLl9idG5fZXhwb3J0KToKICAgICAgICAgICAgYi5zZXRNaW"
    "5pbXVtV2lkdGgoNzApCiAgICAgICAgICAgIGIuc2V0TWluaW11bUhlaWdodCgyNikKICAgICAgICAgI"
    "CAgYmFyLmFkZFdpZGdldChiKQoKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNrZWQuY29ubmVjdChz"
    "ZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5"
    "fZG9fbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9oaWRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb1"
    "9oaWRlKQogICAgICAgIHNlbGYuX2J0bl91bmhpZGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX3Vua"
    "GlkZSkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxl"
    "dGUpCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2h"
    "pZGRlbikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19leH"
    "BvcnQpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKC"
    "iAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgbGVuKHNlbGYuQ09MVU1OUykpCiAg"
    "ICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhzZWxmLkNPTFVNTlMpCiA"
    "gICAgICAgaGggPSBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkKICAgICAgICAjIENvbXBhbn"
    "kgYW5kIEpvYiBUaXRsZSBzdHJldGNoCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMCwgU"
    "UhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVN"
    "b2RlKDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICAjIERhdGUgQXBwbGl"
    "lZCDigJQgZml4ZWQgcmVhZGFibGUgd2lkdGgKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZS"
    "gyLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENvb"
    "HVtbldpZHRoKDIsIDEwMCkKICAgICAgICAjIExpbmsgc3RyZXRjaGVzCiAgICAgICAgaGguc2V0U2Vj"
    "dGlvblJlc2l6ZU1vZGUoMywgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgICM"
    "gU3RhdHVzIOKAlCBmaXhlZCB3aWR0aAogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDQsIF"
    "FIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Q29sdW1uV"
    "2lkdGgoNCwgODApCiAgICAgICAgIyBOb3RlcyBzdHJldGNoZXMKICAgICAgICBoaC5zZXRTZWN0aW9u"
    "UmVzaXplTW9kZSg1LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCgogICAgICAgIHNlbGY"
    "uX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy"
    "5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjd"
    "Glvbk1vZGUoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbk1vZGUuRXh0ZW5k"
    "ZWRTZWxlY3Rpb24pCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ"
    "1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKS"
    "kKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90YWJsZSwgMSkKCiAgICBkZWYgcmVmcmVzaChzZ"
    "WxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgp"
    "CiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNlbGY"
    "uX3JlY29yZHM6CiAgICAgICAgICAgIGhpZGRlbiA9IGJvb2wocmVjLmdldCgiaGlkZGVuIiwgRmFsc2"
    "UpKQogICAgICAgICAgICBpZiBoaWRkZW4gYW5kIG5vdCBzZWxmLl9zaG93X2hpZGRlbjoKICAgICAgI"
    "CAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAg"
    "ICAgICAgICAgIHNlbGYuX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzdGF0dXMgPSAiQXJ"
    "jaGl2ZWQiIGlmIGhpZGRlbiBlbHNlIHJlYy5nZXQoInN0YXR1cyIsIkFjdGl2ZSIpCiAgICAgICAgIC"
    "AgIHZhbHMgPSBbCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJjb21wYW55IiwiIiksCiAgICAgICAgI"
    "CAgICAgICByZWMuZ2V0KCJqb2JfdGl0bGUiLCIiKSwKICAgICAgICAgICAgICAgIHJlYy5nZXQoImRh"
    "dGVfYXBwbGllZCIsIiIpLAogICAgICAgICAgICAgICAgcmVjLmdldCgibGluayIsIiIpLAogICAgICA"
    "gICAgICAgICAgc3RhdHVzLAogICAgICAgICAgICAgICAgcmVjLmdldCgibm90ZXMiLCIiKSwKICAgIC"
    "AgICAgICAgXQogICAgICAgICAgICBmb3IgYywgdiBpbiBlbnVtZXJhdGUodmFscyk6CiAgICAgICAgI"
    "CAgICAgICBpdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShzdHIodikpCiAgICAgICAgICAgICAgICBpZiBo"
    "aWRkZW46CiAgICAgICAgICAgICAgICAgICAgaXRlbS5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX1RFWFR"
    "fRElNKSkKICAgICAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgYywgaXRlbSkKICAgIC"
    "AgICAgICAgIyBTdG9yZSByZWNvcmQgaW5kZXggaW4gZmlyc3QgY29sdW1uJ3MgdXNlciBkYXRhCiAgI"
    "CAgICAgICAgIHNlbGYuX3RhYmxlLml0ZW0ociwgMCkuc2V0RGF0YSgKICAgICAgICAgICAgICAgIFF0"
    "Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuaW5kZXg"
    "ocmVjKQogICAgICAgICAgICApCgogICAgZGVmIF9zZWxlY3RlZF9pbmRpY2VzKHNlbGYpIC0+IGxpc3"
    "RbaW50XToKICAgICAgICBpbmRpY2VzID0gc2V0KCkKICAgICAgICBmb3IgaXRlbSBpbiBzZWxmLl90Y"
    "WJsZS5zZWxlY3RlZEl0ZW1zKCk6CiAgICAgICAgICAgIHJvd19pdGVtID0gc2VsZi5fdGFibGUuaXRl"
    "bShpdGVtLnJvdygpLCAwKQogICAgICAgICAgICBpZiByb3dfaXRlbToKICAgICAgICAgICAgICAgIGl"
    "keCA9IHJvd19pdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAgICAgICAgICAgIC"
    "AgaWYgaWR4IGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgIGluZGljZXMuYWRkKGlkeCkKI"
    "CAgICAgICByZXR1cm4gc29ydGVkKGluZGljZXMpCgogICAgZGVmIF9kaWFsb2coc2VsZiwgcmVjOiBk"
    "aWN0ID0gTm9uZSkgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgZGxnICA9IFFEaWFsb2coc2VsZik"
    "KICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkpvYiBBcHBsaWNhdGlvbiIpCiAgICAgICAgZGxnLn"
    "NldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgI"
    "CAgICBkbGcucmVzaXplKDUwMCwgMzIwKQogICAgICAgIGZvcm0gPSBRRm9ybUxheW91dChkbGcpCgog"
    "ICAgICAgIGNvbXBhbnkgPSBRTGluZUVkaXQocmVjLmdldCgiY29tcGFueSIsIiIpIGlmIHJlYyBlbHN"
    "lICIiKQogICAgICAgIHRpdGxlICAgPSBRTGluZUVkaXQocmVjLmdldCgiam9iX3RpdGxlIiwiIikgaW"
    "YgcmVjIGVsc2UgIiIpCiAgICAgICAgZGUgICAgICA9IFFEYXRlRWRpdCgpCiAgICAgICAgZGUuc2V0Q"
    "2FsZW5kYXJQb3B1cChUcnVlKQogICAgICAgIGRlLnNldERpc3BsYXlGb3JtYXQoInl5eXktTU0tZGQi"
    "KQogICAgICAgIGlmIHJlYyBhbmQgcmVjLmdldCgiZGF0ZV9hcHBsaWVkIik6CiAgICAgICAgICAgIGR"
    "lLnNldERhdGUoUURhdGUuZnJvbVN0cmluZyhyZWNbImRhdGVfYXBwbGllZCJdLCJ5eXl5LU1NLWRkIi"
    "kpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgZGUuc2V0RGF0ZShRRGF0ZS5jdXJyZW50RGF0ZSgpK"
    "QogICAgICAgIGxpbmsgICAgPSBRTGluZUVkaXQocmVjLmdldCgibGluayIsIiIpIGlmIHJlYyBlbHNl"
    "ICIiKQogICAgICAgIHN0YXR1cyAgPSBRTGluZUVkaXQocmVjLmdldCgic3RhdHVzIiwiQXBwbGllZCI"
    "pIGlmIHJlYyBlbHNlICJBcHBsaWVkIikKICAgICAgICBub3RlcyAgID0gUUxpbmVFZGl0KHJlYy5nZX"
    "QoIm5vdGVzIiwiIikgaWYgcmVjIGVsc2UgIiIpCgogICAgICAgIGZvciBsYWJlbCwgd2lkZ2V0IGluI"
    "FsKICAgICAgICAgICAgKCJDb21wYW55OiIsIGNvbXBhbnkpLCAoIkpvYiBUaXRsZToiLCB0aXRsZSks"
    "CiAgICAgICAgICAgICgiRGF0ZSBBcHBsaWVkOiIsIGRlKSwgKCJMaW5rOiIsIGxpbmspLAogICAgICA"
    "gICAgICAoIlN0YXR1czoiLCBzdGF0dXMpLCAoIk5vdGVzOiIsIG5vdGVzKSwKICAgICAgICBdOgogIC"
    "AgICAgICAgICBmb3JtLmFkZFJvdyhsYWJlbCwgd2lkZ2V0KQoKICAgICAgICBidG5zID0gUUhCb3hMY"
    "XlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0bigi"
    "Q2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQ"
    "uY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaW"
    "RnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRucykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9P"
    "SBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHJldHVybiB7CiAgICAgICAg"
    "ICAgICAgICAiY29tcGFueSI6ICAgICAgY29tcGFueS50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICA"
    "gICAgICJqb2JfdGl0bGUiOiAgICB0aXRsZS50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIC"
    "JkYXRlX2FwcGxpZWQiOiBkZS5kYXRlKCkudG9TdHJpbmcoInl5eXktTU0tZGQiKSwKICAgICAgICAgI"
    "CAgICAgICJsaW5rIjogICAgICAgICBsaW5rLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAg"
    "InN0YXR1cyI6ICAgICAgIHN0YXR1cy50ZXh0KCkuc3RyaXAoKSBvciAiQXBwbGllZCIsCiAgICAgICA"
    "gICAgICAgICAibm90ZXMiOiAgICAgICAgbm90ZXMudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgIH"
    "0KICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgI"
    "CAgcCA9IHNlbGYuX2RpYWxvZygpCiAgICAgICAgaWYgbm90IHA6CiAgICAgICAgICAgIHJldHVybgog"
    "ICAgICAgIG5vdyA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICA"
    "gcC51cGRhdGUoewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICBzdHIodXVpZC51dWlkNCgpKS"
    "wKICAgICAgICAgICAgImhpZGRlbiI6ICAgICAgICAgRmFsc2UsCiAgICAgICAgICAgICJjb21wbGV0Z"
    "WRfZGF0ZSI6IE5vbmUsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgIG5vdywKICAgICAgICAg"
    "ICAgInVwZGF0ZWRfYXQiOiAgICAgbm93LAogICAgICAgIH0pCiAgICAgICAgc2VsZi5fcmVjb3Jkcy5"
    "hcHBlbmQocCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogIC"
    "AgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19tb2RpZnkoc2VsZikgLT4gTm9uZToKICAgI"
    "CAgICBpZHhzID0gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpCiAgICAgICAgaWYgbGVuKGlkeHMpICE9"
    "IDE6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJNb2RpZnkiLAogICA"
    "gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiU2VsZWN0IGV4YWN0bHkgb25lIHJvdyB0by"
    "Btb2RpZnkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tpZ"
    "HhzWzBdXQogICAgICAgIHAgICA9IHNlbGYuX2RpYWxvZyhyZWMpCiAgICAgICAgaWYgbm90IHA6CiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIHJlYy51cGRhdGUocCkKICAgICAgICByZWNbInVwZGF0ZWR"
    "fYXQiXSA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgd3JpdG"
    "VfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKI"
    "CAgIGRlZiBfZG9faGlkZShzZWxmKSAtPiBOb25lOgogICAgICAgIGZvciBpZHggaW4gc2VsZi5fc2Vs"
    "ZWN0ZWRfaW5kaWNlcygpOgogICAgICAgICAgICBpZiBpZHggPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiA"
    "gICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bImhpZGRlbiJdICAgICAgICAgPSBUcnVlCi"
    "AgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bImNvbXBsZXRlZF9kYXRlIl0gPSAoCiAgI"
    "CAgICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdLmdldCgiY29tcGxldGVkX2RhdGUiKSBv"
    "cgogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmRhdGUoKS5pc29mb3JtYXQoKQogICA"
    "gICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJ1cGRhdGVkX2"
    "F0Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZ"
    "m9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBz"
    "ZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb191bmhpZGUoc2V"
    "sZikgLT4gTm9uZToKICAgICAgICBmb3IgaWR4IGluIHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKToKIC"
    "AgICAgICAgICAgaWYgaWR4IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICAgICAgc2VsZ"
    "i5fcmVjb3Jkc1tpZHhdWyJoaWRkZW4iXSAgICAgPSBGYWxzZQogICAgICAgICAgICAgICAgc2VsZi5f"
    "cmVjb3Jkc1tpZHhdWyJ1cGRhdGVkX2F0Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWU"
    "ubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICB3cm"
    "l0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpC"
    "gogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICBpZHhzID0gc2VsZi5fc2Vs"
    "ZWN0ZWRfaW5kaWNlcygpCiAgICAgICAgaWYgbm90IGlkeHM6CiAgICAgICAgICAgIHJldHVybgogICA"
    "gICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgIHNlbGYsICJEZWxldG"
    "UiLAogICAgICAgICAgICBmIkRlbGV0ZSB7bGVuKGlkeHMpfSBzZWxlY3RlZCBhcHBsaWNhdGlvbihzK"
    "T8gQ2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRv"
    "bi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICkKICAgICAgICBpZiB"
    "yZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIGJhZCA9IH"
    "NldChpZHhzKQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzID0gW3IgZm9yIGksIHIgaW4gZW51bWVyY"
    "XRlKHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgaSBub3QgaW4g"
    "YmFkXQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICA"
    "gICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfdG9nZ2xlX2hpZGRlbihzZWxmKSAtPiBOb2"
    "5lOgogICAgICAgIHNlbGYuX3Nob3dfaGlkZGVuID0gbm90IHNlbGYuX3Nob3dfaGlkZGVuCiAgICAgI"
    "CAgc2VsZi5fYnRuX3RvZ2dsZS5zZXRUZXh0KAogICAgICAgICAgICAi4piAIEhpZGUgQXJjaGl2ZWQi"
    "IGlmIHNlbGYuX3Nob3dfaGlkZGVuIGVsc2UgIuKYvSBTaG93IEFyY2hpdmVkIgogICAgICAgICkKICA"
    "gICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZXhwb3J0KHNlbGYpIC0+IE5vbmU6CiAgIC"
    "AgICAgcGF0aCwgZmlsdCA9IFFGaWxlRGlhbG9nLmdldFNhdmVGaWxlTmFtZSgKICAgICAgICAgICAgc"
    "2VsZiwgIkV4cG9ydCBKb2IgVHJhY2tlciIsCiAgICAgICAgICAgIHN0cihjZmdfcGF0aCgiZXhwb3J0"
    "cyIpIC8gImpvYl90cmFja2VyLmNzdiIpLAogICAgICAgICAgICAiQ1NWIEZpbGVzICgqLmNzdik7O1R"
    "hYiBEZWxpbWl0ZWQgKCoudHh0KSIKICAgICAgICApCiAgICAgICAgaWYgbm90IHBhdGg6CiAgICAgIC"
    "AgICAgIHJldHVybgogICAgICAgIGRlbGltID0gIlx0IiBpZiBwYXRoLmxvd2VyKCkuZW5kc3dpdGgoI"
    "i50eHQiKSBlbHNlICIsIgogICAgICAgIGhlYWRlciA9IFsiY29tcGFueSIsImpvYl90aXRsZSIsImRh"
    "dGVfYXBwbGllZCIsImxpbmsiLAogICAgICAgICAgICAgICAgICAic3RhdHVzIiwiaGlkZGVuIiwiY29"
    "tcGxldGVkX2RhdGUiLCJub3RlcyJdCiAgICAgICAgd2l0aCBvcGVuKHBhdGgsICJ3IiwgZW5jb2Rpbm"
    "c9InV0Zi04IiwgbmV3bGluZT0iIikgYXMgZjoKICAgICAgICAgICAgZi53cml0ZShkZWxpbS5qb2luK"
    "GhlYWRlcikgKyAiXG4iKQogICAgICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAg"
    "ICAgICAgICAgICB2YWxzID0gWwogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImNvbXBhbnkiLCI"
    "iKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJqb2JfdGl0bGUiLCIiKSwKICAgICAgICAgIC"
    "AgICAgICAgICByZWMuZ2V0KCJkYXRlX2FwcGxpZWQiLCIiKSwKICAgICAgICAgICAgICAgICAgICByZ"
    "WMuZ2V0KCJsaW5rIiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgic3RhdHVzIiwiIiks"
    "CiAgICAgICAgICAgICAgICAgICAgc3RyKGJvb2wocmVjLmdldCgiaGlkZGVuIixGYWxzZSkpKSwKICA"
    "gICAgICAgICAgICAgICAgICByZWMuZ2V0KCJjb21wbGV0ZWRfZGF0ZSIsIiIpIG9yICIiLAogICAgIC"
    "AgICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAgICAgICAgICAgICAgICBdCiAgICAgI"
    "CAgICAgICAgICBmLndyaXRlKGRlbGltLmpvaW4oCiAgICAgICAgICAgICAgICAgICAgc3RyKHYpLnJl"
    "cGxhY2UoIlxuIiwiICIpLnJlcGxhY2UoZGVsaW0sIiAiKQogICAgICAgICAgICAgICAgICAgIGZvciB"
    "2IGluIHZhbHMKICAgICAgICAgICAgICAgICkgKyAiXG4iKQogICAgICAgIFFNZXNzYWdlQm94LmluZm"
    "9ybWF0aW9uKHNlbGYsICJFeHBvcnRlZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZ"
    "iJTYXZlZCB0byB7cGF0aH0iKQoKCiMg4pSA4pSAIFNFTEYgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "ApjbGFzcyBSZWNvcmRzVGFiKFFXaWRnZXQpOgogICAgIiIiR29vZ2xlIERyaXZlL0RvY3MgcmVjb3Jk"
    "cyBicm93c2VyIHRhYi4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICA"
    "gICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZW"
    "xmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAgcm9vd"
    "C5zZXRTcGFjaW5nKDQpCgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVsKCJSZWNvcmRz"
    "IGFyZSBub3QgbG9hZGVkIHlldC4iKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2h"
    "lZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1mYW1pbHk6IHtERUNLX0"
    "ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXa"
    "WRnZXQoc2VsZi5zdGF0dXNfbGFiZWwpCgogICAgICAgIHNlbGYucGF0aF9sYWJlbCA9IFFMYWJlbCgi"
    "UGF0aDogTXkgRHJpdmUiKQogICAgICAgIHNlbGYucGF0aF9sYWJlbC5zZXRTdHlsZVNoZWV0KAogICA"
    "gICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0RJTX07IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2"
    "VyaWY7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlb"
    "GYucGF0aF9sYWJlbCkKCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3QgPSBRTGlzdFdpZGdldCgpCiAg"
    "ICAgICAgc2VsZi5yZWNvcmRzX2xpc3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3J"
    "vdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn"
    "07IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLnJlY29yZHNfbGlzdCwgMSkKC"
    "iAgICBkZWYgc2V0X2l0ZW1zKHNlbGYsIGZpbGVzOiBsaXN0W2RpY3RdLCBwYXRoX3RleHQ6IHN0ciA9"
    "ICJNeSBEcml2ZSIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5wYXRoX2xhYmVsLnNldFRleHQoZiJQYXR"
    "oOiB7cGF0aF90ZXh0fSIpCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3QuY2xlYXIoKQogICAgICAgIG"
    "ZvciBmaWxlX2luZm8gaW4gZmlsZXM6CiAgICAgICAgICAgIHRpdGxlID0gKGZpbGVfaW5mby5nZXQoI"
    "m5hbWUiKSBvciAiVW50aXRsZWQiKS5zdHJpcCgpIG9yICJVbnRpdGxlZCIKICAgICAgICAgICAgbWlt"
    "ZSA9IChmaWxlX2luZm8uZ2V0KCJtaW1lVHlwZSIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgICAgIGl"
    "mIG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5mb2xkZXIiOgogICAgICAgICAgIC"
    "AgICAgcHJlZml4ID0gIvCfk4EiCiAgICAgICAgICAgIGVsaWYgbWltZSA9PSAiYXBwbGljYXRpb24vd"
    "m5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IjoKICAgICAgICAgICAgICAgIHByZWZpeCA9ICLwn5OdIgog"
    "ICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgcHJlZml4ID0gIvCfk4QiCiAgICAgICAgICA"
    "gIG1vZGlmaWVkID0gKGZpbGVfaW5mby5nZXQoIm1vZGlmaWVkVGltZSIpIG9yICIiKS5yZXBsYWNlKC"
    "JUIiwgIiAiKS5yZXBsYWNlKCJaIiwgIiBVVEMiKQogICAgICAgICAgICB0ZXh0ID0gZiJ7cHJlZml4f"
    "SB7dGl0bGV9IiArIChmIiAgICBbe21vZGlmaWVkfV0iIGlmIG1vZGlmaWVkIGVsc2UgIiIpCiAgICAg"
    "ICAgICAgIGl0ZW0gPSBRTGlzdFdpZGdldEl0ZW0odGV4dCkKICAgICAgICAgICAgaXRlbS5zZXREYXR"
    "hKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgZmlsZV9pbmZvKQogICAgICAgICAgICBzZWxmLnJlY2"
    "9yZHNfbGlzdC5hZGRJdGVtKGl0ZW0pCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmI"
    "kxvYWRlZCB7bGVuKGZpbGVzKX0gR29vZ2xlIERyaXZlIGl0ZW0ocykuIikKCgpjbGFzcyBUYXNrc1Rh"
    "YihRV2lkZ2V0KToKICAgICIiIlRhc2sgcmVnaXN0cnkgKyBHb29nbGUtZmlyc3QgZWRpdG9yIHdvcmt"
    "mbG93IHRhYi4iIiIKCiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKICAgICAgICB0YXNrc1"
    "9wcm92aWRlciwKICAgICAgICBvbl9hZGRfZWRpdG9yX29wZW4sCiAgICAgICAgb25fY29tcGxldGVfc"
    "2VsZWN0ZWQsCiAgICAgICAgb25fY2FuY2VsX3NlbGVjdGVkLAogICAgICAgIG9uX3RvZ2dsZV9jb21w"
    "bGV0ZWQsCiAgICAgICAgb25fcHVyZ2VfY29tcGxldGVkLAogICAgICAgIG9uX2ZpbHRlcl9jaGFuZ2V"
    "kLAogICAgICAgIG9uX2VkaXRvcl9zYXZlLAogICAgICAgIG9uX2VkaXRvcl9jYW5jZWwsCiAgICAgIC"
    "AgZGlhZ25vc3RpY3NfbG9nZ2VyPU5vbmUsCiAgICAgICAgcGFyZW50PU5vbmUsCiAgICApOgogICAgI"
    "CAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3Rhc2tzX3Byb3ZpZGVyID0g"
    "dGFza3NfcHJvdmlkZXIKICAgICAgICBzZWxmLl9vbl9hZGRfZWRpdG9yX29wZW4gPSBvbl9hZGRfZWR"
    "pdG9yX29wZW4KICAgICAgICBzZWxmLl9vbl9jb21wbGV0ZV9zZWxlY3RlZCA9IG9uX2NvbXBsZXRlX3"
    "NlbGVjdGVkCiAgICAgICAgc2VsZi5fb25fY2FuY2VsX3NlbGVjdGVkID0gb25fY2FuY2VsX3NlbGVjd"
    "GVkCiAgICAgICAgc2VsZi5fb25fdG9nZ2xlX2NvbXBsZXRlZCA9IG9uX3RvZ2dsZV9jb21wbGV0ZWQK"
    "ICAgICAgICBzZWxmLl9vbl9wdXJnZV9jb21wbGV0ZWQgPSBvbl9wdXJnZV9jb21wbGV0ZWQKICAgICA"
    "gICBzZWxmLl9vbl9maWx0ZXJfY2hhbmdlZCA9IG9uX2ZpbHRlcl9jaGFuZ2VkCiAgICAgICAgc2VsZi"
    "5fb25fZWRpdG9yX3NhdmUgPSBvbl9lZGl0b3Jfc2F2ZQogICAgICAgIHNlbGYuX29uX2VkaXRvcl9jY"
    "W5jZWwgPSBvbl9lZGl0b3JfY2FuY2VsCiAgICAgICAgc2VsZi5fZGlhZ19sb2dnZXIgPSBkaWFnbm9z"
    "dGljc19sb2dnZXIKICAgICAgICBzZWxmLl9zaG93X2NvbXBsZXRlZCA9IEZhbHNlCiAgICAgICAgc2V"
    "sZi5fcmVmcmVzaF90aHJlYWQgPSBOb25lCiAgICAgICAgc2VsZi5fYnVpbGRfdWkoKQoKICAgIGRlZi"
    "BfYnVpbGRfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKI"
    "CAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0"
    "U3BhY2luZyg0KQogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrID0gUVN0YWNrZWRXaWRnZXQoKQo"
    "gICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYud29ya3NwYWNlX3N0YWNrLCAxKQoKICAgICAgICBub3"
    "JtYWwgPSBRV2lkZ2V0KCkKICAgICAgICBub3JtYWxfbGF5b3V0ID0gUVZCb3hMYXlvdXQobm9ybWFsK"
    "QogICAgICAgIG5vcm1hbF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAg"
    "ICAgbm9ybWFsX2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0"
    "gUUxhYmVsKCJUYXNrIHJlZ2lzdHJ5IGlzIG5vdCBsb2FkZWQgeWV0LiIpCiAgICAgICAgc2VsZi5zdG"
    "F0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19O"
    "yBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAg"
    "ICkKICAgICAgICBub3JtYWxfbGF5b3V0LmFkZFdpZGdldChzZWxmLnN0YXR1c19sYWJlbCkKCiAgICA"
    "gICAgZmlsdGVyX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldC"
    "hfc2VjdGlvbl9sYmwoIuKdpyBEQVRFIFJBTkdFIikpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb"
    "21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5hZGRJdGVtKCJX"
    "RUVLIiwgIndlZWsiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiTU9OVEg"
    "iLCAibW9udGgiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiTkVYVCAzIE"
    "1PTlRIUyIsICJuZXh0XzNfbW9udGhzIikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZ"
    "El0ZW0oIllFQVIiLCAieWVhciIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5zZXRDdXJy"
    "ZW50SW5kZXgoMikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmN1cnJlbnRJbmRleENoYW5"
    "nZWQuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIF86IHNlbGYuX29uX2ZpbHRlcl9jaGFuZ2VkKH"
    "NlbGYudGFza19maWx0ZXJfY29tYm8uY3VycmVudERhdGEoKSBvciAibmV4dF8zX21vbnRocyIpCiAgI"
    "CAgICAgKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYudGFza19maWx0ZXJfY29tYm8p"
    "CiAgICAgICAgZmlsdGVyX3Jvdy5hZGRTdHJldGNoKDEpCiAgICAgICAgbm9ybWFsX2xheW91dC5hZGR"
    "MYXlvdXQoZmlsdGVyX3JvdykKCiAgICAgICAgc2VsZi50YXNrX3RhYmxlID0gUVRhYmxlV2lkZ2V0KD"
    "AsIDQpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJTd"
    "GF0dXMiLCAiRHVlIiwgIlRhc2siLCAiU291cmNlIl0pCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNl"
    "dFNlbGVjdGlvbkJlaGF2aW9yKFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGV"
    "jdFJvd3MpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFNlbGVjdGlvbk1vZGUoUUFic3RyYWN0SX"
    "RlbVZpZXcuU2VsZWN0aW9uTW9kZS5FeHRlbmRlZFNlbGVjdGlvbikKICAgICAgICBzZWxmLnRhc2tfd"
    "GFibGUuc2V0RWRpdFRyaWdnZXJzKFFBYnN0cmFjdEl0ZW1WaWV3LkVkaXRUcmlnZ2VyLk5vRWRpdFRy"
    "aWdnZXJzKQogICAgICAgIHNlbGYudGFza190YWJsZS52ZXJ0aWNhbEhlYWRlcigpLnNldFZpc2libGU"
    "oRmFsc2UpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW"
    "9uUmVzaXplTW9kZSgwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgI"
    "CAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9k"
    "ZSgxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi5"
    "0YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZG"
    "VyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250Y"
    "WxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgzLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJl"
    "c2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGh"
    "pY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYudGFza190YWJsZS5pdGVtU2VsZWN0aW9uQ2hhbm"
    "dlZC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0dG9uX3N0YXRlKQogICAgICAgIG5vcm1hb"
    "F9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza190YWJsZSwgMSkKCiAgICAgICAgYWN0aW9ucyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBzZWxmLmJ0bl9hZGRfdGFza193b3Jrc3BhY2UgPSBfZ290aGljX2J"
    "0bigiQUREIFRBU0siKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2sgPSBfZ290aGljX2J0bi"
    "giQ09NUExFVEUgU0VMRUNURUQiKQogICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrID0gX2dvdGhpY"
    "19idG4oIkNBTkNFTCBTRUxFQ1RFRCIpCiAgICAgICAgc2VsZi5idG5fdG9nZ2xlX2NvbXBsZXRlZCA9"
    "IF9nb3RoaWNfYnRuKCJTSE9XIENPTVBMRVRFRCIpCiAgICAgICAgc2VsZi5idG5fcHVyZ2VfY29tcGx"
    "ldGVkID0gX2dvdGhpY19idG4oIlBVUkdFIENPTVBMRVRFRCIpCiAgICAgICAgc2VsZi5idG5fYWRkX3"
    "Rhc2tfd29ya3NwYWNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9hZGRfZWRpdG9yX29wZW4pCiAgI"
    "CAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzay5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fY29tcGxl"
    "dGVfc2VsZWN0ZWQpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suY2xpY2tlZC5jb25uZWN0KHN"
    "lbGYuX29uX2NhbmNlbF9zZWxlY3RlZCkKICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLm"
    "NsaWNrZWQuY29ubmVjdChzZWxmLl9vbl90b2dnbGVfY29tcGxldGVkKQogICAgICAgIHNlbGYuYnRuX"
    "3B1cmdlX2NvbXBsZXRlZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fcHVyZ2VfY29tcGxldGVkKQog"
    "ICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2suc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWx"
    "mLmJ0bl9jYW5jZWxfdGFzay5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIGZvciBidG4gaW4gKAogIC"
    "AgICAgICAgICBzZWxmLmJ0bl9hZGRfdGFza193b3Jrc3BhY2UsCiAgICAgICAgICAgIHNlbGYuYnRuX"
    "2NvbXBsZXRlX3Rhc2ssCiAgICAgICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrLAogICAgICAgICAg"
    "ICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLAogICAgICAgICAgICBzZWxmLmJ0bl9wdXJnZV9jb21"
    "wbGV0ZWQsCiAgICAgICAgKToKICAgICAgICAgICAgYWN0aW9ucy5hZGRXaWRnZXQoYnRuKQogICAgIC"
    "AgIG5vcm1hbF9sYXlvdXQuYWRkTGF5b3V0KGFjdGlvbnMpCiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc"
    "3RhY2suYWRkV2lkZ2V0KG5vcm1hbCkKCiAgICAgICAgZWRpdG9yID0gUVdpZGdldCgpCiAgICAgICAg"
    "ZWRpdG9yX2xheW91dCA9IFFWQm94TGF5b3V0KGVkaXRvcikKICAgICAgICBlZGl0b3JfbGF5b3V0LnN"
    "ldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGVkaXRvcl9sYXlvdXQuc2V0U3BhY2"
    "luZyg0KQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFRBU"
    "0sgRURJVE9SIOKAlCBHT09HTEUtRklSU1QiKSkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1"
    "c19sYWJlbCA9IFFMYWJlbCgiQ29uZmlndXJlIHRhc2sgZGV0YWlscywgdGhlbiBzYXZlIHRvIEdvb2d"
    "sZSBDYWxlbmRhci4iKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVsLnNldFN0eW"
    "xlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfR"
    "ElNfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgcGFkZGluZzogNnB4OyIKICAgICAgICAp"
    "CiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQoc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGF"
    "iZWwpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9uYW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBzZW"
    "xmLnRhc2tfZWRpdG9yX25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJUYXNrIE5hbWUiKQogICAgICAgI"
    "HNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF0ZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNr"
    "X2VkaXRvcl9zdGFydF9kYXRlLnNldFBsYWNlaG9sZGVyVGV4dCgiU3RhcnQgRGF0ZSAoWVlZWS1NTS1"
    "ERCkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfdGltZSA9IFFMaW5lRWRpdCgpCiAgIC"
    "AgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiU3RhcnQgV"
    "GltZSAoSEg6TU0pIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlID0gUUxpbmVFZGl0"
    "KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9kYXRlLnNldFBsYWNlaG9sZGVyVGV4dCgiRW5"
    "kIERhdGUgKFlZWVktTU0tREQpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lID0gUU"
    "xpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lLnNldFBsYWNlaG9sZGVyV"
    "GV4dCgiRW5kIFRpbWUgKEhIOk1NKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbiA9"
    "IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbi5zZXRQbGFjZWhvbGR"
    "lclRleHQoIkxvY2F0aW9uIChvcHRpb25hbCkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfcmVjdX"
    "JyZW5jZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnNld"
    "FBsYWNlaG9sZGVyVGV4dCgiUmVjdXJyZW5jZSBSUlVMRSAob3B0aW9uYWwpIikKICAgICAgICBzZWxm"
    "LnRhc2tfZWRpdG9yX2FsbF9kYXkgPSBRQ2hlY2tCb3goIkFsbC1kYXkiKQogICAgICAgIHNlbGYudGF"
    "za19lZGl0b3Jfbm90ZXMgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfbm90ZX"
    "Muc2V0UGxhY2Vob2xkZXJUZXh0KCJOb3RlcyIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9ub3Rlc"
    "y5zZXRNYXhpbXVtSGVpZ2h0KDkwKQogICAgICAgIGZvciB3aWRnZXQgaW4gKAogICAgICAgICAgICBz"
    "ZWxmLnRhc2tfZWRpdG9yX25hbWUsCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF"
    "0ZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLAogICAgICAgICAgICBzZW"
    "xmLnRhc2tfZWRpdG9yX2VuZF9kYXRlLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90a"
    "W1lLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2xvY2F0aW9uLAogICAgICAgICAgICBzZWxm"
    "LnRhc2tfZWRpdG9yX3JlY3VycmVuY2UsCiAgICAgICAgKToKICAgICAgICAgICAgZWRpdG9yX2xheW9"
    "1dC5hZGRXaWRnZXQod2lkZ2V0KQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudG"
    "Fza19lZGl0b3JfYWxsX2RheSkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChzZWxmLnRhc"
    "2tfZWRpdG9yX25vdGVzLCAxKQogICAgICAgIGVkaXRvcl9hY3Rpb25zID0gUUhCb3hMYXlvdXQoKQog"
    "ICAgICAgIGJ0bl9zYXZlID0gX2dvdGhpY19idG4oIlNBVkUiKQogICAgICAgIGJ0bl9jYW5jZWwgPSB"
    "fZ290aGljX2J0bigiQ0FOQ0VMIikKICAgICAgICBidG5fc2F2ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi"
    "5fb25fZWRpdG9yX3NhdmUpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb"
    "25fZWRpdG9yX2NhbmNlbCkKICAgICAgICBlZGl0b3JfYWN0aW9ucy5hZGRXaWRnZXQoYnRuX3NhdmUp"
    "CiAgICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgZWRpdG9"
    "yX2FjdGlvbnMuYWRkU3RyZXRjaCgxKQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkTGF5b3V0KGVkaX"
    "Rvcl9hY3Rpb25zKQogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLmFkZFdpZGdldChlZGl0b3IpC"
    "gogICAgICAgIHNlbGYubm9ybWFsX3dvcmtzcGFjZSA9IG5vcm1hbAogICAgICAgIHNlbGYuZWRpdG9y"
    "X3dvcmtzcGFjZSA9IGVkaXRvcgogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnR"
    "XaWRnZXQoc2VsZi5ub3JtYWxfd29ya3NwYWNlKQoKICAgIGRlZiBfdXBkYXRlX2FjdGlvbl9idXR0b2"
    "5fc3RhdGUoc2VsZikgLT4gTm9uZToKICAgICAgICBlbmFibGVkID0gYm9vbChzZWxmLnNlbGVjdGVkX"
    "3Rhc2tfaWRzKCkpCiAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzay5zZXRFbmFibGVkKGVuYWJs"
    "ZWQpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2suc2V0RW5hYmxlZChlbmFibGVkKQoKICAgIGR"
    "lZiBzZWxlY3RlZF90YXNrX2lkcyhzZWxmKSAtPiBsaXN0W3N0cl06CiAgICAgICAgaWRzOiBsaXN0W3"
    "N0cl0gPSBbXQogICAgICAgIGZvciByIGluIHJhbmdlKHNlbGYudGFza190YWJsZS5yb3dDb3VudCgpK"
    "ToKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBzZWxmLnRhc2tfdGFibGUuaXRlbShyLCAwKQogICAg"
    "ICAgICAgICBpZiBzdGF0dXNfaXRlbSBpcyBOb25lOgogICAgICAgICAgICAgICAgY29udGludWUKICA"
    "gICAgICAgICAgaWYgbm90IHN0YXR1c19pdGVtLmlzU2VsZWN0ZWQoKToKICAgICAgICAgICAgICAgIG"
    "NvbnRpbnVlCiAgICAgICAgICAgIHRhc2tfaWQgPSBzdGF0dXNfaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhU"
    "m9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgaWYgdGFza19pZCBhbmQgdGFza19pZCBub3QgaW4gaWRz"
    "OgogICAgICAgICAgICAgICAgaWRzLmFwcGVuZCh0YXNrX2lkKQogICAgICAgIHJldHVybiBpZHMKCiA"
    "gICBkZWYgbG9hZF90YXNrcyhzZWxmLCB0YXNrczogbGlzdFtkaWN0XSkgLT4gTm9uZToKICAgICAgIC"
    "BzZWxmLnRhc2tfdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgdGFzayBpbiB0YXNrczoKI"
    "CAgICAgICAgICAgcm93ID0gc2VsZi50YXNrX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2Vs"
    "Zi50YXNrX3RhYmxlLmluc2VydFJvdyhyb3cpCiAgICAgICAgICAgIHN0YXR1cyA9ICh0YXNrLmdldCg"
    "ic3RhdHVzIikgb3IgInBlbmRpbmciKS5sb3dlcigpCiAgICAgICAgICAgIHN0YXR1c19pY29uID0gIu"
    "KYkSIgaWYgc3RhdHVzIGluIHsiY29tcGxldGVkIiwgImNhbmNlbGxlZCJ9IGVsc2UgIuKAoiIKICAgI"
    "CAgICAgICAgZHVlID0gKHRhc2suZ2V0KCJkdWVfYXQiKSBvciAiIikucmVwbGFjZSgiVCIsICIgIikK"
    "ICAgICAgICAgICAgdGV4dCA9ICh0YXNrLmdldCgidGV4dCIpIG9yICJSZW1pbmRlciIpLnN0cmlwKCk"
    "gb3IgIlJlbWluZGVyIgogICAgICAgICAgICBzb3VyY2UgPSAodGFzay5nZXQoInNvdXJjZSIpIG9yIC"
    "Jsb2NhbCIpLmxvd2VyKCkKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtK"
    "GYie3N0YXR1c19pY29ufSB7c3RhdHVzfSIpCiAgICAgICAgICAgIHN0YXR1c19pdGVtLnNldERhdGEo"
    "UXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCB0YXNrLmdldCgiaWQiKSkKICAgICAgICAgICAgc2VsZi5"
    "0YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAwLCBzdGF0dXNfaXRlbSkKICAgICAgICAgICAgc2VsZi50YX"
    "NrX3RhYmxlLnNldEl0ZW0ocm93LCAxLCBRVGFibGVXaWRnZXRJdGVtKGR1ZSkpCiAgICAgICAgICAgI"
    "HNlbGYudGFza190YWJsZS5zZXRJdGVtKHJvdywgMiwgUVRhYmxlV2lkZ2V0SXRlbSh0ZXh0KSkKICAg"
    "ICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAzLCBRVGFibGVXaWRnZXRJdGVtKHN"
    "vdXJjZSkpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkxvYWRlZCB7bGVuKHRhc2"
    "tzKX0gdGFzayhzKS4iKQogICAgICAgIHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0dG9uX3N0YXRlKCkKC"
    "iAgICBkZWYgX2RpYWcoc2VsZiwgbWVzc2FnZTogc3RyLCBsZXZlbDogc3RyID0gIklORk8iKSAtPiBO"
    "b25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgaWYgc2VsZi5fZGlhZ19sb2dnZXI6CiAgICAgICA"
    "gICAgICAgICBzZWxmLl9kaWFnX2xvZ2dlcihtZXNzYWdlLCBsZXZlbCkKICAgICAgICBleGNlcHQgRX"
    "hjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgZGVmIHN0b3BfcmVmcmVzaF93b3JrZXIoc2VsZ"
    "iwgcmVhc29uOiBzdHIgPSAiIikgLT4gTm9uZToKICAgICAgICB0aHJlYWQgPSBnZXRhdHRyKHNlbGYs"
    "ICJfcmVmcmVzaF90aHJlYWQiLCBOb25lKQogICAgICAgIGlmIHRocmVhZCBpcyBub3QgTm9uZSBhbmQ"
    "gaGFzYXR0cih0aHJlYWQsICJpc1J1bm5pbmciKSBhbmQgdGhyZWFkLmlzUnVubmluZygpOgogICAgIC"
    "AgICAgICBzZWxmLl9kaWFnKAogICAgICAgICAgICAgICAgZiJbVEFTS1NdW1RIUkVBRF1bV0FSTl0gc"
    "3RvcCByZXF1ZXN0ZWQgZm9yIHJlZnJlc2ggd29ya2VyIHJlYXNvbj17cmVhc29uIG9yICd1bnNwZWNp"
    "ZmllZCd9IiwKICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgKQogICAgICAgICAgICB"
    "0cnk6CiAgICAgICAgICAgICAgICB0aHJlYWQucmVxdWVzdEludGVycnVwdGlvbigpCiAgICAgICAgIC"
    "AgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCiAgICAgICAgICAgIHRyeToKI"
    "CAgICAgICAgICAgICAgIHRocmVhZC5xdWl0KCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoK"
    "ICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICAgICAgdGhyZWFkLndhaXQoMjAwMCkKICAgICAgICB"
    "zZWxmLl9yZWZyZXNoX3RocmVhZCA9IE5vbmUKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOg"
    "ogICAgICAgIGlmIG5vdCBjYWxsYWJsZShzZWxmLl90YXNrc19wcm92aWRlcik6CiAgICAgICAgICAgI"
    "HJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5sb2FkX3Rhc2tzKHNlbGYuX3Rhc2tz"
    "X3Byb3ZpZGVyKCkpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2V"
    "sZi5fZGlhZyhmIltUQVNLU11bVEFCXVtFUlJPUl0gcmVmcmVzaCBmYWlsZWQ6IHtleH0iLCAiRVJST1"
    "IiKQogICAgICAgICAgICBzZWxmLnN0b3BfcmVmcmVzaF93b3JrZXIocmVhc29uPSJ0YXNrc190YWJfc"
    "mVmcmVzaF9leGNlcHRpb24iKQoKICAgIGRlZiBjbG9zZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuc3RvcF9yZWZyZXNoX3dvcmtlcihyZWFzb249InRhc2tzX3RhYl9jbG9zZSI"
    "pCiAgICAgICAgc3VwZXIoKS5jbG9zZUV2ZW50KGV2ZW50KQoKICAgIGRlZiBzZXRfc2hvd19jb21wbG"
    "V0ZWQoc2VsZiwgZW5hYmxlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9zaG93X2NvbXBsZ"
    "XRlZCA9IGJvb2woZW5hYmxlZCkKICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLnNldFRl"
    "eHQoIkhJREUgQ09NUExFVEVEIiBpZiBzZWxmLl9zaG93X2NvbXBsZXRlZCBlbHNlICJTSE9XIENPTVB"
    "MRVRFRCIpCgogICAgZGVmIHNldF9zdGF0dXMoc2VsZiwgdGV4dDogc3RyLCBvazogYm9vbCA9IEZhbH"
    "NlKSAtPiBOb25lOgogICAgICAgIGNvbG9yID0gQ19HUkVFTiBpZiBvayBlbHNlIENfVEVYVF9ESU0KI"
    "CAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Y29sb3J9OyBib3JkZXI6IDFweCBzb2x"
    "pZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA2cHg7IgogICAgICAgICkKICAgICAgICBzZWxmLnRhc2tfZW"
    "RpdG9yX3N0YXR1c19sYWJlbC5zZXRUZXh0KHRleHQpCgogICAgZGVmIG9wZW5fZWRpdG9yKHNlbGYpI"
    "C0+IE5vbmU6CiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suc2V0Q3VycmVudFdpZGdldChzZWxm"
    "LmVkaXRvcl93b3Jrc3BhY2UpCgogICAgZGVmIGNsb3NlX2VkaXRvcihzZWxmKSAtPiBOb25lOgogICA"
    "gICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQoc2VsZi5ub3JtYWxfd29ya3"
    "NwYWNlKQoKCmNsYXNzIFNlbGZUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFBlcnNvbmEncyBpbnRlc"
    "m5hbCBkaWFsb2d1ZSBzcGFjZS4KICAgIFJlY2VpdmVzOiBpZGxlIG5hcnJhdGl2ZSBvdXRwdXQsIHVu"
    "c29saWNpdGVkIHRyYW5zbWlzc2lvbnMsCiAgICAgICAgICAgICAgUG9JIGxpc3QgZnJvbSBkYWlseSB"
    "yZWZsZWN0aW9uLCB1bmFuc3dlcmVkIHF1ZXN0aW9uIGZsYWdzLAogICAgICAgICAgICAgIGpvdXJuYW"
    "wgbG9hZCBub3RpZmljYXRpb25zLgogICAgUmVhZC1vbmx5IGRpc3BsYXkuIFNlcGFyYXRlIGZyb20gc"
    "GVyc29uYSBjaGF0IHRhYiBhbHdheXMuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFy"
    "ZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHJvb3QgPSB"
    "RVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsID"
    "QpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGhkciA9IFFIQm94TGF5b3V0KCkKI"
    "CAgICAgICBoZHIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibChmIuKdpyBJTk5FUiBTQU5DVFVNIOKAlCB7"
    "REVDS19OQU1FLnVwcGVyKCl9J1MgUFJJVkFURSBUSE9VR0hUUyIpKQogICAgICAgIHNlbGYuX2J0bl9"
    "jbGVhciA9IF9nb3RoaWNfYnRuKCLinJcgQ2xlYXIiKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5zZX"
    "RGaXhlZFdpZHRoKDgwKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5jbGlja2VkLmNvbm5lY3Qoc2VsZ"
    "i5jbGVhcikKICAgICAgICBoZHIuYWRkU3RyZXRjaCgpCiAgICAgICAgaGRyLmFkZFdpZGdldChzZWxm"
    "Ll9idG5fY2xlYXIpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoaGRyKQoKICAgICAgICBzZWxmLl9kaXN"
    "wbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCi"
    "AgICAgICAgc2VsZi5fZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91b"
    "mQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19QVVJQTEVfRElNfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19"
    "GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgIC"
    "AgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fZGlzcGxheSwgMSkKCiAgICBkZWYgYXBwZW5kKHNlbGYsI"
    "GxhYmVsOiBzdHIsIHRleHQ6IHN0cikgLT4gTm9uZToKICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGlt"
    "ZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgIGNvbG9ycyA9IHsKICAgICAgICAgICA"
    "gIk5BUlJBVElWRSI6ICBDX0dPTEQsCiAgICAgICAgICAgICJSRUZMRUNUSU9OIjogQ19QVVJQTEUsCi"
    "AgICAgICAgICAgICJKT1VSTkFMIjogICAgQ19TSUxWRVIsCiAgICAgICAgICAgICJQT0kiOiAgICAgI"
    "CAgQ19HT0xEX0RJTSwKICAgICAgICAgICAgIlNZU1RFTSI6ICAgICBDX1RFWFRfRElNLAogICAgICAg"
    "IH0KICAgICAgICBjb2xvciA9IGNvbG9ycy5nZXQobGFiZWwudXBwZXIoKSwgQ19HT0xEKQogICAgICA"
    "gIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q1"
    "9URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gP"
    "C9zcGFuPicKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2NvbG9yfTsgZm9udC13ZWln"
    "aHQ6Ym9sZDsiPicKICAgICAgICAgICAgZifinacge2xhYmVsfTwvc3Bhbj48YnI+JwogICAgICAgICA"
    "gICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19HT0xEfTsiPnt0ZXh0fTwvc3Bhbj4nCiAgICAgICAgKQ"
    "ogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKCIiKQogICAgICAgIHNlbGYuX2Rpc3BsYXkudmVyd"
    "GljYWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNh"
    "bFNjcm9sbEJhcigpLm1heGltdW0oKQogICAgICAgICkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9"
    "uZToKICAgICAgICBzZWxmLl9kaXNwbGF5LmNsZWFyKCkKCgojIOKUgOKUgCBESUFHTk9TVElDUyBUQU"
    "Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "ACmNsYXNzIERpYWdub3N0aWNzVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBCYWNrZW5kIGRpYWdub3"
    "N0aWNzIGRpc3BsYXkuCiAgICBSZWNlaXZlczogaGFyZHdhcmUgZGV0ZWN0aW9uIHJlc3VsdHMsIGRlc"
    "GVuZGVuY3kgY2hlY2sgcmVzdWx0cywKICAgICAgICAgICAgICBBUEkgZXJyb3JzLCBzeW5jIGZhaWx1"
    "cmVzLCB0aW1lciBldmVudHMsIGpvdXJuYWwgbG9hZCBub3RpY2VzLAogICAgICAgICAgICAgIG1vZGV"
    "sIGxvYWQgc3RhdHVzLCBHb29nbGUgYXV0aCBldmVudHMuCiAgICBBbHdheXMgc2VwYXJhdGUgZnJvbS"
    "BwZXJzb25hIGNoYXQgdGFiLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob"
    "25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICByb290ID0gUVZCb3hM"
    "YXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICA"
    "gICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBoZHIgPSBRSEJveExheW91dCgpCiAgICAgIC"
    "AgaGRyLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBESUFHTk9TVElDUyDigJQgU1lTVEVNICYgQ"
    "kFDS0VORCBMT0ciKSkKICAgICAgICBzZWxmLl9idG5fY2xlYXIgPSBfZ290aGljX2J0bigi4pyXIENs"
    "ZWFyIikKICAgICAgICBzZWxmLl9idG5fY2xlYXIuc2V0Rml4ZWRXaWR0aCg4MCkKICAgICAgICBzZWx"
    "mLl9idG5fY2xlYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYuY2xlYXIpCiAgICAgICAgaGRyLmFkZFN0cm"
    "V0Y2goKQogICAgICAgIGhkci5hZGRXaWRnZXQoc2VsZi5fYnRuX2NsZWFyKQogICAgICAgIHJvb3QuY"
    "WRkTGF5b3V0KGhkcikKCiAgICAgICAgc2VsZi5fZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAg"
    "c2VsZi5fZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0U3R"
    "5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX1"
    "NJTFZFUn07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgI"
    "CAgICAgICAgIGYiZm9udC1mYW1pbHk6ICdDb3VyaWVyIE5ldycsIG1vbm9zcGFjZTsgIgogICAgICAg"
    "ICAgICBmImZvbnQtc2l6ZTogMTBweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAgcm9"
    "vdC5hZGRXaWRnZXQoc2VsZi5fZGlzcGxheSwgMSkKCiAgICBkZWYgbG9nKHNlbGYsIG1lc3NhZ2U6IH"
    "N0ciwgbGV2ZWw6IHN0ciA9ICJJTkZPIikgLT4gTm9uZToKICAgICAgICB0aW1lc3RhbXAgPSBkYXRld"
    "GltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgIGxldmVsX2NvbG9ycyA9IHsKICAg"
    "ICAgICAgICAgIklORk8iOiAgQ19TSUxWRVIsCiAgICAgICAgICAgICJPSyI6ICAgIENfR1JFRU4sCiA"
    "gICAgICAgICAgICJXQVJOIjogIENfR09MRCwKICAgICAgICAgICAgIkVSUk9SIjogQ19CTE9PRCwKIC"
    "AgICAgICAgICAgIkRFQlVHIjogQ19URVhUX0RJTSwKICAgICAgICB9CiAgICAgICAgY29sb3IgPSBsZ"
    "XZlbF9jb2xvcnMuZ2V0KGxldmVsLnVwcGVyKCksIENfU0lMVkVSKQogICAgICAgIHNlbGYuX2Rpc3Bs"
    "YXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07Ij5"
    "be3RpbWVzdGFtcH1dPC9zcGFuPiAnCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2"
    "xvcn07Ij57bWVzc2FnZX08L3NwYW4+JwogICAgICAgICkKICAgICAgICBzZWxmLl9kaXNwbGF5LnZlc"
    "nRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGlj"
    "YWxTY3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAgZGVmIGxvZ19tYW55KHNlbGYsIG1"
    "lc3NhZ2VzOiBsaXN0W3N0cl0sIGxldmVsOiBzdHIgPSAiSU5GTyIpIC0+IE5vbmU6CiAgICAgICAgZm"
    "9yIG1zZyBpbiBtZXNzYWdlczoKICAgICAgICAgICAgbHZsID0gbGV2ZWwKICAgICAgICAgICAgaWYgI"
    "uKckyIgaW4gbXNnOiAgICBsdmwgPSAiT0siCiAgICAgICAgICAgIGVsaWYgIuKclyIgaW4gbXNnOiAg"
    "bHZsID0gIldBUk4iCiAgICAgICAgICAgIGVsaWYgIkVSUk9SIiBpbiBtc2cudXBwZXIoKTogbHZsID0"
    "gIkVSUk9SIgogICAgICAgICAgICBzZWxmLmxvZyhtc2csIGx2bCkKCiAgICBkZWYgY2xlYXIoc2VsZi"
    "kgLT4gTm9uZToKICAgICAgICBzZWxmLl9kaXNwbGF5LmNsZWFyKCkKCgojIOKUgOKUgCBMRVNTT05TI"
    "FRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIAKY2xhc3MgTGVzc29uc1RhYihRV2lkZ2V0KToKICAgICIiIgogICAgTFNMI"
    "EZvcmJpZGRlbiBSdWxlc2V0IGFuZCBjb2RlIGxlc3NvbnMgYnJvd3Nlci4KICAgIEFkZCwgdmlldywg"
    "c2VhcmNoLCBkZWxldGUgbGVzc29ucy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBkYjo"
    "gIkxlc3NvbnNMZWFybmVkREIiLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXy"
    "hwYXJlbnQpCiAgICAgICAgc2VsZi5fZGIgPSBkYgogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgI"
    "CAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg"
    "0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICAjIEZpbHRlciBiYX"
    "IKICAgICAgICBmaWx0ZXJfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX3NlYXJjaCA9I"
    "FFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fc2VhcmNoLnNldFBsYWNlaG9sZGVyVGV4dCgiU2VhcmNo"
    "IGxlc3NvbnMuLi4iKQogICAgICAgIHNlbGYuX2xhbmdfZmlsdGVyID0gUUNvbWJvQm94KCkKICAgICA"
    "gICBzZWxmLl9sYW5nX2ZpbHRlci5hZGRJdGVtcyhbIkFsbCIsICJMU0wiLCAiUHl0aG9uIiwgIlB5U2"
    "lkZTYiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIkphdmFTY3JpcHQiLCAiT"
    "3RoZXIiXSkKICAgICAgICBzZWxmLl9zZWFyY2gudGV4dENoYW5nZWQuY29ubmVjdChzZWxmLnJlZnJl"
    "c2gpCiAgICAgICAgc2VsZi5fbGFuZ19maWx0ZXIuY3VycmVudFRleHRDaGFuZ2VkLmNvbm5lY3Qoc2V"
    "sZi5yZWZyZXNoKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgiU2VhcmNoOiIpKQ"
    "ogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYuX3NlYXJjaCwgMSkKICAgICAgICBmaWx0Z"
    "XJfcm93LmFkZFdpZGdldChRTGFiZWwoIkxhbmd1YWdlOiIpKQogICAgICAgIGZpbHRlcl9yb3cuYWRk"
    "V2lkZ2V0KHNlbGYuX2xhbmdfZmlsdGVyKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGZpbHRlcl9yb3c"
    "pCgogICAgICAgIGJ0bl9iYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX2FkZCA9IF9nb3RoaW"
    "NfYnRuKCLinKYgQWRkIExlc3NvbiIpCiAgICAgICAgYnRuX2RlbCA9IF9nb3RoaWNfYnRuKCLinJcgR"
    "GVsZXRlIikKICAgICAgICBidG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAg"
    "ICAgYnRuX2RlbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIGJ0bl9iYXI"
    "uYWRkV2lkZ2V0KGJ0bl9hZGQpCiAgICAgICAgYnRuX2Jhci5hZGRXaWRnZXQoYnRuX2RlbCkKICAgIC"
    "AgICBidG5fYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJ0bl9iYXIpCgogI"
    "CAgICAgIHNlbGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDQpCiAgICAgICAgc2VsZi5fdGFibGUu"
    "c2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscygKICAgICAgICAgICAgWyJMYW5ndWFnZSIsICJSZWZlcmV"
    "uY2UgS2V5IiwgIlN1bW1hcnkiLCAiRW52aXJvbm1lbnQiXQogICAgICAgICkKICAgICAgICBzZWxmLl"
    "90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgI"
    "DIsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRT"
    "ZWxlY3Rpb25CZWhhdmlvcigKICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmV"
    "oYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLl90YWJsZS5zZXRBbHRlcm5hdGluZ1Jvd0NvbG"
    "9ycyhUcnVlKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zd"
    "HlsZSgpKQogICAgICAgIHNlbGYuX3RhYmxlLml0ZW1TZWxlY3Rpb25DaGFuZ2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fb25fc2VsZWN0KQoKICAgICAgICAjIFVzZSBzcGxpdHRlciBiZXR3ZWVuIHRhYmxlIGFuZCBkZXR"
    "haWwKICAgICAgICBzcGxpdHRlciA9IFFTcGxpdHRlcihRdC5PcmllbnRhdGlvbi5WZXJ0aWNhbCkKIC"
    "AgICAgICBzcGxpdHRlci5hZGRXaWRnZXQoc2VsZi5fdGFibGUpCgogICAgICAgICMgRGV0YWlsIHBhb"
    "mVsCiAgICAgICAgZGV0YWlsX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIGRldGFpbF9sYXlvdXQg"
    "PSBRVkJveExheW91dChkZXRhaWxfd2lkZ2V0KQogICAgICAgIGRldGFpbF9sYXlvdXQuc2V0Q29udGV"
    "udHNNYXJnaW5zKDAsIDQsIDAsIDApCiAgICAgICAgZGV0YWlsX2xheW91dC5zZXRTcGFjaW5nKDIpCg"
    "ogICAgICAgIGRldGFpbF9oZWFkZXIgPSBRSEJveExheW91dCgpCiAgICAgICAgZGV0YWlsX2hlYWRlc"
    "i5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgRlVMTCBSVUxFIikpCiAgICAgICAgZGV0YWlsX2hl"
    "YWRlci5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlID0gX2dvdGhpY19idG4"
    "oIkVkaXQiKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Rml4ZWRXaWR0aCg1MCkKICAgIC"
    "AgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldENoZWNrYWJsZShUcnVlKQogICAgICAgIHNlbGYuX2J0b"
    "l9lZGl0X3J1bGUudG9nZ2xlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9lZGl0X21vZGUpCiAgICAgICAg"
    "c2VsZi5fYnRuX3NhdmVfcnVsZSA9IF9nb3RoaWNfYnRuKCJTYXZlIikKICAgICAgICBzZWxmLl9idG5"
    "fc2F2ZV9ydWxlLnNldEZpeGVkV2lkdGgoNTApCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZX"
    "RWaXNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuY2xpY2tlZC5jb25uZWN0K"
    "HNlbGYuX3NhdmVfcnVsZV9lZGl0KQogICAgICAgIGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KHNlbGYu"
    "X2J0bl9lZGl0X3J1bGUpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRXaWRnZXQoc2VsZi5fYnRuX3N"
    "hdmVfcnVsZSkKICAgICAgICBkZXRhaWxfbGF5b3V0LmFkZExheW91dChkZXRhaWxfaGVhZGVyKQoKIC"
    "AgICAgICBzZWxmLl9kZXRhaWwgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2RldGFpbC5zZXRSZ"
    "WFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2RldGFpbC5zZXRNaW5pbXVtSGVpZ2h0KDEyMCkKICAg"
    "ICAgICBzZWxmLl9kZXRhaWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB"
    "7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZC"
    "B7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZ"
    "jsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICkKICAgICAgICBkZXRhaWxf"
    "bGF5b3V0LmFkZFdpZGdldChzZWxmLl9kZXRhaWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KGR"
    "ldGFpbF93aWRnZXQpCiAgICAgICAgc3BsaXR0ZXIuc2V0U2l6ZXMoWzMwMCwgMTgwXSkKICAgICAgIC"
    "Byb290LmFkZFdpZGdldChzcGxpdHRlciwgMSkKCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtka"
    "WN0XSA9IFtdCiAgICAgICAgc2VsZi5fZWRpdGluZ19yb3c6IGludCA9IC0xCgogICAgZGVmIHJlZnJl"
    "c2goc2VsZikgLT4gTm9uZToKICAgICAgICBxICAgID0gc2VsZi5fc2VhcmNoLnRleHQoKQogICAgICA"
    "gIGxhbmcgPSBzZWxmLl9sYW5nX2ZpbHRlci5jdXJyZW50VGV4dCgpCiAgICAgICAgbGFuZyA9ICIiIG"
    "lmIGxhbmcgPT0gIkFsbCIgZWxzZSBsYW5nCiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHNlbGYuX2RiL"
    "nNlYXJjaChxdWVyeT1xLCBsYW5ndWFnZT1sYW5nKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0Nv"
    "dW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICByID0gc2V"
    "sZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKIC"
    "AgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV"
    "2lkZ2V0SXRlbShyZWMuZ2V0KCJsYW5ndWFnZSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUu"
    "c2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJyZWZ"
    "lcmVuY2Vfa2V5IiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDIsCiAgIC"
    "AgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInN1bW1hcnkiLCIiKSkpCiAgICAgI"
    "CAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMywKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdl"
    "dEl0ZW0ocmVjLmdldCgiZW52aXJvbm1lbnQiLCIiKSkpCgogICAgZGVmIF9vbl9zZWxlY3Qoc2VsZik"
    "gLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBzZW"
    "xmLl9lZGl0aW5nX3JvdyA9IHJvdwogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZ"
    "HMpOgogICAgICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICAgICAgc2VsZi5f"
    "ZGV0YWlsLnNldFBsYWluVGV4dCgKICAgICAgICAgICAgICAgIHJlYy5nZXQoImZ1bGxfcnVsZSIsIiI"
    "pICsgIlxuXG4iICsKICAgICAgICAgICAgICAgICgiUmVzb2x1dGlvbjogIiArIHJlYy5nZXQoInJlc2"
    "9sdXRpb24iLCIiKSBpZiByZWMuZ2V0KCJyZXNvbHV0aW9uIikgZWxzZSAiIikKICAgICAgICAgICAgK"
    "QogICAgICAgICAgICAjIFJlc2V0IGVkaXQgbW9kZSBvbiBuZXcgc2VsZWN0aW9uCiAgICAgICAgICAg"
    "IHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Q2hlY2tlZChGYWxzZSkKCiAgICBkZWYgX3RvZ2dsZV9lZGl"
    "0X21vZGUoc2VsZiwgZWRpdGluZzogYm9vbCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9kZXRhaWwuc2"
    "V0UmVhZE9ubHkobm90IGVkaXRpbmcpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRWaXNpY"
    "mxlKGVkaXRpbmcpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRUZXh0KCJDYW5jZWwiIGlm"
    "IGVkaXRpbmcgZWxzZSAiRWRpdCIpCiAgICAgICAgaWYgZWRpdGluZzoKICAgICAgICAgICAgc2VsZi5"
    "fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn"
    "07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q"
    "19HT0xEX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBz"
    "ZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICAgICApCiAgICAgICA"
    "gZWxzZToKICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIC"
    "AgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICAgI"
    "CAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgICAgICBmImZvbnQt"
    "ZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyI"
    "KICAgICAgICAgICAgKQogICAgICAgICAgICAjIFJlbG9hZCBvcmlnaW5hbCBjb250ZW50IG9uIGNhbm"
    "NlbAogICAgICAgICAgICBzZWxmLl9vbl9zZWxlY3QoKQoKICAgIGRlZiBfc2F2ZV9ydWxlX2VkaXQoc"
    "2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl9lZGl0aW5nX3JvdwogICAgICAgIGlmIDAg"
    "PD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICB0ZXh0ID0gc2VsZi5fZGV0YWl"
    "sLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQogICAgICAgICAgICAjIFNwbGl0IHJlc29sdXRpb24gYmFjay"
    "BvdXQgaWYgcHJlc2VudAogICAgICAgICAgICBpZiAiXG5cblJlc29sdXRpb246ICIgaW4gdGV4dDoKI"
    "CAgICAgICAgICAgICAgIHBhcnRzID0gdGV4dC5zcGxpdCgiXG5cblJlc29sdXRpb246ICIsIDEpCiAg"
    "ICAgICAgICAgICAgICBmdWxsX3J1bGUgID0gcGFydHNbMF0uc3RyaXAoKQogICAgICAgICAgICAgICA"
    "gcmVzb2x1dGlvbiA9IHBhcnRzWzFdLnN0cmlwKCkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgIC"
    "AgICAgIGZ1bGxfcnVsZSAgPSB0ZXh0CiAgICAgICAgICAgICAgICByZXNvbHV0aW9uID0gc2VsZi5fc"
    "mVjb3Jkc1tyb3ddLmdldCgicmVzb2x1dGlvbiIsICIiKQogICAgICAgICAgICBzZWxmLl9yZWNvcmRz"
    "W3Jvd11bImZ1bGxfcnVsZSJdICA9IGZ1bGxfcnVsZQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3J"
    "vd11bInJlc29sdXRpb24iXSA9IHJlc29sdXRpb24KICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi"
    "5fZGIuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc"
    "2V0Q2hlY2tlZChGYWxzZSkKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2Fk"
    "ZChzZWxmKSAtPiBOb25lOgogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V"
    "0V2luZG93VGl0bGUoIkFkZCBMZXNzb24iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2"
    "dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAsI"
    "DQwMCkKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAgIGVudiAgPSBRTGluZUVk"
    "aXQoIkxTTCIpCiAgICAgICAgbGFuZyA9IFFMaW5lRWRpdCgiTFNMIikKICAgICAgICByZWYgID0gUUx"
    "pbmVFZGl0KCkKICAgICAgICBzdW1tID0gUUxpbmVFZGl0KCkKICAgICAgICBydWxlID0gUVRleHRFZG"
    "l0KCkKICAgICAgICBydWxlLnNldE1heGltdW1IZWlnaHQoMTAwKQogICAgICAgIHJlcyAgPSBRTGluZ"
    "UVkaXQoKQogICAgICAgIGxpbmsgPSBRTGluZUVkaXQoKQogICAgICAgIGZvciBsYWJlbCwgdyBpbiBb"
    "CiAgICAgICAgICAgICgiRW52aXJvbm1lbnQ6IiwgZW52KSwgKCJMYW5ndWFnZToiLCBsYW5nKSwKICA"
    "gICAgICAgICAgKCJSZWZlcmVuY2UgS2V5OiIsIHJlZiksICgiU3VtbWFyeToiLCBzdW1tKSwKICAgIC"
    "AgICAgICAgKCJGdWxsIFJ1bGU6IiwgcnVsZSksICgiUmVzb2x1dGlvbjoiLCByZXMpLAogICAgICAgI"
    "CAgICAoIkxpbms6IiwgbGluayksCiAgICAgICAgXToKICAgICAgICAgICAgZm9ybS5hZGRSb3cobGFi"
    "ZWwsIHcpCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnR"
    "uKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb2"
    "5uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBid"
    "G5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0"
    "bnMpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiA"
    "gICAgICAgICAgIHNlbGYuX2RiLmFkZCgKICAgICAgICAgICAgICAgIGVudmlyb25tZW50PWVudi50ZX"
    "h0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGxhbmd1YWdlPWxhbmcudGV4dCgpLnN0cmlwKCksC"
    "iAgICAgICAgICAgICAgICByZWZlcmVuY2Vfa2V5PXJlZi50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAg"
    "ICAgICAgIHN1bW1hcnk9c3VtbS50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGZ1bGxfcnV"
    "sZT1ydWxlLnRvUGxhaW5UZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIHJlc29sdXRpb249cm"
    "VzLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgbGluaz1saW5rLnRleHQoKS5zdHJpcCgpL"
    "AogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxl"
    "dGUoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICA"
    "gICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmVjX2lkID"
    "0gc2VsZi5fcmVjb3Jkc1tyb3ddLmdldCgiaWQiLCIiKQogICAgICAgICAgICByZXBseSA9IFFNZXNzY"
    "WdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBMZXNzb24iLAogICAg"
    "ICAgICAgICAgICAgIkRlbGV0ZSB0aGlzIGxlc3Nvbj8gQ2Fubm90IGJlIHVuZG9uZS4iLAogICAgICA"
    "gICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3Rhbm"
    "RhcmRCdXR0b24uTm8KICAgICAgICAgICAgKQogICAgICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZ"
    "UJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgICAgICBzZWxmLl9kYi5kZWxldGUocmVj"
    "X2lkKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCgojIOKUgOKUgCBNT0RVTEUgVFJBQ0t"
    "FUiBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNs"
    "YXNzIE1vZHVsZVRyYWNrZXJUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFBlcnNvbmFsIG1vZHVsZSB"
    "waXBlbGluZSB0cmFja2VyLgogICAgVHJhY2sgcGxhbm5lZC9pbi1wcm9ncmVzcy9idWlsdCBtb2R1bG"
    "VzIGFzIHRoZXkgYXJlIGRlc2lnbmVkLgogICAgRWFjaCBtb2R1bGUgaGFzOiBOYW1lLCBTdGF0dXMsI"
    "ERlc2NyaXB0aW9uLCBOb3Rlcy4KICAgIEV4cG9ydCB0byBUWFQgZm9yIHBhc3RpbmcgaW50byBzZXNz"
    "aW9ucy4KICAgIEltcG9ydDogcGFzdGUgYSBmaW5hbGl6ZWQgc3BlYywgaXQgcGFyc2VzIG5hbWUgYW5"
    "kIGRldGFpbHMuCiAgICBUaGlzIGlzIGEgZGVzaWduIG5vdGVib29rIOKAlCBub3QgY29ubmVjdGVkIH"
    "RvIGRlY2tfYnVpbGRlcidzIE1PRFVMRSByZWdpc3RyeS4KICAgICIiIgoKICAgIFNUQVRVU0VTID0gW"
    "yJJZGVhIiwgIkRlc2lnbmluZyIsICJSZWFkeSB0byBCdWlsZCIsICJQYXJ0aWFsIiwgIkJ1aWx0Il0K"
    "CiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml"
    "0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BhdGggPSBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJtb2"
    "R1bGVfdHJhY2tlci5qc29ubCIKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KI"
    "CAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3Nl"
    "dHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICA"
    "gICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYW"
    "NpbmcoNCkKCiAgICAgICAgIyBCdXR0b24gYmFyCiAgICAgICAgYnRuX2JhciA9IFFIQm94TGF5b3V0K"
    "CkKICAgICAgICBzZWxmLl9idG5fYWRkICAgID0gX2dvdGhpY19idG4oIkFkZCBNb2R1bGUiKQogICAg"
    "ICAgIHNlbGYuX2J0bl9lZGl0ICAgPSBfZ290aGljX2J0bigiRWRpdCIpCiAgICAgICAgc2VsZi5fYnR"
    "uX2RlbGV0ZSA9IF9nb3RoaWNfYnRuKCJEZWxldGUiKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQgPS"
    "BfZ290aGljX2J0bigiRXhwb3J0IFRYVCIpCiAgICAgICAgc2VsZi5fYnRuX2ltcG9ydCA9IF9nb3Roa"
    "WNfYnRuKCJJbXBvcnQgU3BlYyIpCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYu"
    "X2J0bl9lZGl0LCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fZXh"
    "wb3J0LCBzZWxmLl9idG5faW1wb3J0KToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtV2lkdGgoODApCi"
    "AgICAgICAgICAgIGIuc2V0TWluaW11bUhlaWdodCgyNikKICAgICAgICAgICAgYnRuX2Jhci5hZGRXa"
    "WRnZXQoYikKICAgICAgICBidG5fYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0"
    "KGJ0bl9iYXIpCgogICAgICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2F"
    "kZCkKICAgICAgICBzZWxmLl9idG5fZWRpdC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZWRpdCkKIC"
    "AgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgI"
    "CAgICAgc2VsZi5fYnRuX2V4cG9ydC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZXhwb3J0KQogICAg"
    "ICAgIHNlbGYuX2J0bl9pbXBvcnQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2ltcG9ydCkKCiAgICA"
    "gICAgIyBUYWJsZQogICAgICAgIHNlbGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDMpCiAgICAgIC"
    "Agc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIk1vZHVsZSBOYW1lIiwgIlN0Y"
    "XR1cyIsICJEZXNjcmlwdGlvbiJdKQogICAgICAgIGhoID0gc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhl"
    "YWRlcigpCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcuUmVzaXp"
    "lTW9kZS5GaXhlZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgwLCAxNjApCiAgIC"
    "AgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZ"
    "CkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCgxLCAxMDApCiAgICAgICAgaGguc2V0"
    "U2VjdGlvblJlc2l6ZU1vZGUoMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICA"
    "gIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdG"
    "VtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNld"
    "EFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVTaGVl"
    "dChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2VsZi5fdGFibGUuaXRlbVNlbGVjdGlvbkN"
    "oYW5nZWQuY29ubmVjdChzZWxmLl9vbl9zZWxlY3QpCgogICAgICAgICMgU3BsaXR0ZXIKICAgICAgIC"
    "BzcGxpdHRlciA9IFFTcGxpdHRlcihRdC5PcmllbnRhdGlvbi5WZXJ0aWNhbCkKICAgICAgICBzcGxpd"
    "HRlci5hZGRXaWRnZXQoc2VsZi5fdGFibGUpCgogICAgICAgICMgTm90ZXMgcGFuZWwKICAgICAgICBu"
    "b3Rlc193aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBub3Rlc19sYXlvdXQgPSBRVkJveExheW91dCh"
    "ub3Rlc193aWRnZXQpCiAgICAgICAgbm90ZXNfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCA0LC"
    "AwLCAwKQogICAgICAgIG5vdGVzX2xheW91dC5zZXRTcGFjaW5nKDIpCiAgICAgICAgbm90ZXNfbGF5b"
    "3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBOT1RFUyIpKQogICAgICAgIHNlbGYuX25vdGVz"
    "X2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0UmVhZE9"
    "ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5LnNldE1pbmltdW1IZWlnaHQoMTIwKQ"
    "ogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiY"
    "WNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6"
    "IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0Z"
    "PTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICkKICAgIC"
    "AgICBub3Rlc19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX25vdGVzX2Rpc3BsYXkpCiAgICAgICAgc3Bsa"
    "XR0ZXIuYWRkV2lkZ2V0KG5vdGVzX3dpZGdldCkKICAgICAgICBzcGxpdHRlci5zZXRTaXplcyhbMjUw"
    "LCAxNTBdKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNwbGl0dGVyLCAxKQoKICAgICAgICAjIENvdW5"
    "0IGxhYmVsCiAgICAgICAgc2VsZi5fY291bnRfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYuX2"
    "NvdW50X2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07I"
    "GZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICAp"
    "CiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fY291bnRfbGJsKQoKICAgIGRlZiByZWZyZXNoKHN"
    "lbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aC"
    "kKICAgICAgICBzZWxmLl90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZ"
    "i5fcmVjb3JkczoKICAgICAgICAgICAgciA9IHNlbGYuX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAg"
    "ICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0"
    "ociwgMCwgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJuYW1lIiwgIiIpKSkKICAgICAgICAgICAgc3"
    "RhdHVzX2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInN0YXR1cyIsICJJZGVhIikpCiAgI"
    "CAgICAgICAgICMgQ29sb3IgYnkgc3RhdHVzCiAgICAgICAgICAgIHN0YXR1c19jb2xvcnMgPSB7CiAg"
    "ICAgICAgICAgICAgICAiSWRlYSI6ICAgICAgICAgICAgIENfVEVYVF9ESU0sCiAgICAgICAgICAgICA"
    "gICAiRGVzaWduaW5nIjogICAgICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgICAgICAiUmVhZHkgdG"
    "8gQnVpbGQiOiAgIENfUFVSUExFLAogICAgICAgICAgICAgICAgIlBhcnRpYWwiOiAgICAgICAgICAiI"
    "2NjODg0NCIsCiAgICAgICAgICAgICAgICAiQnVpbHQiOiAgICAgICAgICAgIENfR1JFRU4sCiAgICAg"
    "ICAgICAgIH0KICAgICAgICAgICAgc3RhdHVzX2l0ZW0uc2V0Rm9yZWdyb3VuZCgKICAgICAgICAgICA"
    "gICAgIFFDb2xvcihzdGF0dXNfY29sb3JzLmdldChyZWMuZ2V0KCJzdGF0dXMiLCJJZGVhIiksIENfVE"
    "VYVF9ESU0pKQogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgM"
    "Swgc3RhdHVzX2l0ZW0pCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMiwKICAgICAg"
    "ICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiZGVzY3JpcHRpb24iLCAiIilbOjgwXSk"
    "pCiAgICAgICAgY291bnRzID0ge30KICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgIC"
    "AgICAgICAgIHMgPSByZWMuZ2V0KCJzdGF0dXMiLCAiSWRlYSIpCiAgICAgICAgICAgIGNvdW50c1tzX"
    "SA9IGNvdW50cy5nZXQocywgMCkgKyAxCiAgICAgICAgY291bnRfc3RyID0gIiAgIi5qb2luKGYie3N9"
    "OiB7bn0iIGZvciBzLCBuIGluIGNvdW50cy5pdGVtcygpKQogICAgICAgIHNlbGYuX2NvdW50X2xibC5"
    "zZXRUZXh0KAogICAgICAgICAgICBmIlRvdGFsOiB7bGVuKHNlbGYuX3JlY29yZHMpfSAgIHtjb3VudF"
    "9zdHJ9IgogICAgICAgICkKCiAgICBkZWYgX29uX3NlbGVjdChzZWxmKSAtPiBOb25lOgogICAgICAgI"
    "HJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNl"
    "bGYuX3JlY29yZHMpOgogICAgICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICA"
    "gICAgc2VsZi5fbm90ZXNfZGlzcGxheS5zZXRQbGFpblRleHQocmVjLmdldCgibm90ZXMiLCAiIikpCg"
    "ogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9vcGVuX2VkaXRfZGlhb"
    "G9nKCkKCiAgICBkZWYgX2RvX2VkaXQoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90"
    "YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKTo"
    "KICAgICAgICAgICAgc2VsZi5fb3Blbl9lZGl0X2RpYWxvZyhzZWxmLl9yZWNvcmRzW3Jvd10sIHJvdy"
    "kKCiAgICBkZWYgX29wZW5fZWRpdF9kaWFsb2coc2VsZiwgcmVjOiBkaWN0ID0gTm9uZSwgcm93OiBpb"
    "nQgPSAtMSkgLT4gTm9uZToKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNl"
    "dFdpbmRvd1RpdGxlKCJNb2R1bGUiIGlmIG5vdCByZWMgZWxzZSBmIkVkaXQ6IHtyZWMuZ2V0KCduYW1"
    "lJywnJyl9IikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IG"
    "NvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5yZXNpemUoNTQwLCA0NDApCiAgICAgICAgZm9yb"
    "SA9IFFWQm94TGF5b3V0KGRsZykKCiAgICAgICAgbmFtZV9maWVsZCA9IFFMaW5lRWRpdChyZWMuZ2V0"
    "KCJuYW1lIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgbmFtZV9maWVsZC5zZXRQbGFjZWhvbGR"
    "lclRleHQoIk1vZHVsZSBuYW1lIikKCiAgICAgICAgc3RhdHVzX2NvbWJvID0gUUNvbWJvQm94KCkKIC"
    "AgICAgICBzdGF0dXNfY29tYm8uYWRkSXRlbXMoc2VsZi5TVEFUVVNFUykKICAgICAgICBpZiByZWM6C"
    "iAgICAgICAgICAgIGlkeCA9IHN0YXR1c19jb21iby5maW5kVGV4dChyZWMuZ2V0KCJzdGF0dXMiLCJJ"
    "ZGVhIikpCiAgICAgICAgICAgIGlmIGlkeCA+PSAwOgogICAgICAgICAgICAgICAgc3RhdHVzX2NvbWJ"
    "vLnNldEN1cnJlbnRJbmRleChpZHgpCgogICAgICAgIGRlc2NfZmllbGQgPSBRTGluZUVkaXQocmVjLm"
    "dldCgiZGVzY3JpcHRpb24iLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBkZXNjX2ZpZWxkLnNld"
    "FBsYWNlaG9sZGVyVGV4dCgiT25lLWxpbmUgZGVzY3JpcHRpb24iKQoKICAgICAgICBub3Rlc19maWVs"
    "ZCA9IFFUZXh0RWRpdCgpCiAgICAgICAgbm90ZXNfZmllbGQuc2V0UGxhaW5UZXh0KHJlYy5nZXQoIm5"
    "vdGVzIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgbm90ZXNfZmllbGQuc2V0UGxhY2Vob2xkZX"
    "JUZXh0KAogICAgICAgICAgICAiRnVsbCBub3RlcyDigJQgc3BlYywgaWRlYXMsIHJlcXVpcmVtZW50c"
    "ywgZWRnZSBjYXNlcy4uLiIKICAgICAgICApCiAgICAgICAgbm90ZXNfZmllbGQuc2V0TWluaW11bUhl"
    "aWdodCgyMDApCgogICAgICAgIGZvciBsYWJlbCwgd2lkZ2V0IGluIFsKICAgICAgICAgICAgKCJOYW1"
    "lOiIsIG5hbWVfZmllbGQpLAogICAgICAgICAgICAoIlN0YXR1czoiLCBzdGF0dXNfY29tYm8pLAogIC"
    "AgICAgICAgICAoIkRlc2NyaXB0aW9uOiIsIGRlc2NfZmllbGQpLAogICAgICAgICAgICAoIk5vdGVzO"
    "iIsIG5vdGVzX2ZpZWxkKSwKICAgICAgICBdOgogICAgICAgICAgICByb3dfbGF5b3V0ID0gUUhCb3hM"
    "YXlvdXQoKQogICAgICAgICAgICBsYmwgPSBRTGFiZWwobGFiZWwpCiAgICAgICAgICAgIGxibC5zZXR"
    "GaXhlZFdpZHRoKDkwKQogICAgICAgICAgICByb3dfbGF5b3V0LmFkZFdpZGdldChsYmwpCiAgICAgIC"
    "AgICAgIHJvd19sYXlvdXQuYWRkV2lkZ2V0KHdpZGdldCkKICAgICAgICAgICAgZm9ybS5hZGRMYXlvd"
    "XQocm93X2xheW91dCkKCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5f"
    "c2F2ZSAgID0gX2dvdGhpY19idG4oIlNhdmUiKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J"
    "0bigiQ2FuY2VsIikKICAgICAgICBidG5fc2F2ZS5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCkKIC"
    "AgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bl9yb"
    "3cuYWRkV2lkZ2V0KGJ0bl9zYXZlKQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwp"
    "CiAgICAgICAgZm9ybS5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSB"
    "RRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIG5ld19yZWMgPSB7CiAgICAgIC"
    "AgICAgICAgICAiaWQiOiAgICAgICAgICByZWMuZ2V0KCJpZCIsIHN0cih1dWlkLnV1aWQ0KCkpKSBpZ"
    "iByZWMgZWxzZSBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgICAgICJuYW1lIjogICAgICAg"
    "IG5hbWVfZmllbGQudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAic3RhdHVzIjogICAgICB"
    "zdGF0dXNfY29tYm8uY3VycmVudFRleHQoKSwKICAgICAgICAgICAgICAgICJkZXNjcmlwdGlvbiI6IG"
    "Rlc2NfZmllbGQudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICBub"
    "3Rlc19maWVsZC50b1BsYWluVGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAiY3JlYXRlZCI6"
    "ICAgICByZWMuZ2V0KCJjcmVhdGVkIiwgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCkpIGlmIHJlYyB"
    "lbHNlIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICAgICAgIm1vZGlmaWVkIj"
    "ogICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAgICAgICAgIH0KICAgICAgICAgICAga"
    "WYgcm93ID49IDA6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd10gPSBuZXdfcmVjCiAg"
    "ICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChuZXdfcmV"
    "jKQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgIC"
    "AgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgI"
    "CAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBs"
    "ZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIG5hbWUgPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V"
    "0KCJuYW1lIiwidGhpcyBtb2R1bGUiKQogICAgICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZX"
    "N0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBNb2R1bGUiLAogICAgICAgICAgICAgI"
    "CAgZiJEZWxldGUgJ3tuYW1lfSc/IENhbm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAgICAgIFFN"
    "ZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5"
    "vCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcm"
    "RCdXR0b24uWWVzOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5wb3Aocm93KQogICAgICAgI"
    "CAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAg"
    "ICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19leHBvcnQoc2VsZikgLT4gTm9uZToKICAgICA"
    "gICB0cnk6CiAgICAgICAgICAgIGV4cG9ydF9kaXIgPSBjZmdfcGF0aCgiZXhwb3J0cyIpCiAgICAgIC"
    "AgICAgIGV4cG9ydF9kaXIubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgI"
    "CAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlWSVtJWRfJUglTSVTIikKICAgICAgICAg"
    "ICAgb3V0X3BhdGggPSBleHBvcnRfZGlyIC8gZiJtb2R1bGVzX3t0c30udHh0IgogICAgICAgICAgICB"
    "saW5lcyA9IFsKICAgICAgICAgICAgICAgICJFQ0hPIERFQ0sg4oCUIE1PRFVMRSBUUkFDS0VSIEVYUE"
    "9SVCIsCiAgICAgICAgICAgICAgICBmIkV4cG9ydGVkOiB7ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJ"
    "yVZLSVtLSVkICVIOiVNOiVTJyl9IiwKICAgICAgICAgICAgICAgIGYiVG90YWwgbW9kdWxlczoge2xl"
    "bihzZWxmLl9yZWNvcmRzKX0iLAogICAgICAgICAgICAgICAgIj0iICogNjAsCiAgICAgICAgICAgICA"
    "gICAiIiwKICAgICAgICAgICAgXQogICAgICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6Ci"
    "AgICAgICAgICAgICAgICBsaW5lcy5leHRlbmQoWwogICAgICAgICAgICAgICAgICAgIGYiTU9EVUxFO"
    "iB7cmVjLmdldCgnbmFtZScsJycpfSIsCiAgICAgICAgICAgICAgICAgICAgZiJTdGF0dXM6IHtyZWMu"
    "Z2V0KCdzdGF0dXMnLCcnKX0iLAogICAgICAgICAgICAgICAgICAgIGYiRGVzY3JpcHRpb246IHtyZWM"
    "uZ2V0KCdkZXNjcmlwdGlvbicsJycpfSIsCiAgICAgICAgICAgICAgICAgICAgIiIsCiAgICAgICAgIC"
    "AgICAgICAgICAgIk5vdGVzOiIsCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgibm90ZXMiLCIiK"
    "SwKICAgICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgICAgICAgICAiLSIgKiA0MCwKICAg"
    "ICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgICAgIF0pCiAgICAgICAgICAgIG91dF9wYXR"
    "oLndyaXRlX3RleHQoIlxuIi5qb2luKGxpbmVzKSwgZW5jb2Rpbmc9InV0Zi04IikKICAgICAgICAgIC"
    "AgUUFwcGxpY2F0aW9uLmNsaXBib2FyZCgpLnNldFRleHQoIlxuIi5qb2luKGxpbmVzKSkKICAgICAgI"
    "CAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oCiAgICAgICAgICAgICAgICBzZWxmLCAiRXhwb3J0"
    "ZWQiLAogICAgICAgICAgICAgICAgZiJNb2R1bGUgdHJhY2tlciBleHBvcnRlZCB0bzpcbntvdXRfcGF"
    "0aH1cblxuQWxzbyBjb3BpZWQgdG8gY2xpcGJvYXJkLiIKICAgICAgICAgICAgKQogICAgICAgIGV4Y2"
    "VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2FybmluZyhzZWxmLCAiR"
    "Xhwb3J0IEVycm9yIiwgc3RyKGUpKQoKICAgIGRlZiBfZG9faW1wb3J0KHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgIiIiSW1wb3J0IGEgbW9kdWxlIHNwZWMgZnJvbSBjbGlwYm9hcmQgb3IgdHlwZWQgdGV4dC4"
    "iIiIKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKC"
    "JJbXBvcnQgTW9kdWxlIFNwZWMiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZ"
    "Doge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAsIDM0MCkK"
    "ICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChkbGcpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldCh"
    "RTGFiZWwoCiAgICAgICAgICAgICJQYXN0ZSBhIG1vZHVsZSBzcGVjIGJlbG93LlxuIgogICAgICAgIC"
    "AgICAiRmlyc3QgbGluZSB3aWxsIGJlIHVzZWQgYXMgdGhlIG1vZHVsZSBuYW1lLiIKICAgICAgICApK"
    "QogICAgICAgIHRleHRfZmllbGQgPSBRVGV4dEVkaXQoKQogICAgICAgIHRleHRfZmllbGQuc2V0UGxh"
    "Y2Vob2xkZXJUZXh0KCJQYXN0ZSBtb2R1bGUgc3BlYyBoZXJlLi4uIikKICAgICAgICBsYXlvdXQuYWR"
    "kV2lkZ2V0KHRleHRfZmllbGQsIDEpCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgIC"
    "AgICBidG5fb2sgICAgID0gX2dvdGhpY19idG4oIkltcG9ydCIpCiAgICAgICAgYnRuX2NhbmNlbCA9I"
    "F9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIGJ0bl9vay5jbGlja2VkLmNvbm5lY3QoZGxnLmFj"
    "Y2VwdCkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICA"
    "gIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9vaykKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2"
    "FuY2VsKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICAgICAgaWYgZGxnLmV4Z"
    "WMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHJhdyA9IHRleHRf"
    "ZmllbGQudG9QbGFpblRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIG5vdCByYXc6CiAgICAgICA"
    "gICAgICAgICByZXR1cm4KCiAgICAgICAgICAgIGxhYmVsX21hcCA9IHsKICAgICAgICAgICAgICAgIC"
    "Jtb2R1bGUiOiAibmFtZSIsCiAgICAgICAgICAgICAgICAic3RhdHVzIjogInN0YXR1cyIsCiAgICAgI"
    "CAgICAgICAgICAiZGVzY3JpcHRpb24iOiAiZGVzY3JpcHRpb24iLAogICAgICAgICAgICAgICAgImZ1"
    "bGwgc3VtbWFyeSI6ICJub3RlcyIsCiAgICAgICAgICAgIH0KICAgICAgICAgICAgcGFyc2VkID0gewo"
    "gICAgICAgICAgICAgICAgIm5hbWUiOiAiIiwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAiSWRlYS"
    "IsCiAgICAgICAgICAgICAgICAiZGVzY3JpcHRpb24iOiAiIiwKICAgICAgICAgICAgICAgICJub3Rlc"
    "yI6ICIiLAogICAgICAgICAgICB9CiAgICAgICAgICAgIGN1cnJlbnRfZmllbGQgPSBOb25lCgogICAg"
    "ICAgICAgICBmb3IgbGluZSBpbiByYXcuc3BsaXRsaW5lcygpOgogICAgICAgICAgICAgICAgc3RyaXB"
    "wZWQgPSBsaW5lLnN0cmlwKCkKICAgICAgICAgICAgICAgIGlmIG5vdCBzdHJpcHBlZDoKICAgICAgIC"
    "AgICAgICAgICAgICBpZiBjdXJyZW50X2ZpZWxkIGFuZCBwYXJzZWRbY3VycmVudF9maWVsZF06CiAgI"
    "CAgICAgICAgICAgICAgICAgICAgIHBhcnNlZFtjdXJyZW50X2ZpZWxkXSArPSAiXG4iCiAgICAgICAg"
    "ICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICAgICBpZiAiOiIgaW4gbGluZToKICAgICA"
    "gICAgICAgICAgICAgICBtYXliZV9sYWJlbCwgbWF5YmVfdmFsdWUgPSBsaW5lLnNwbGl0KCI6IiwgMS"
    "kKICAgICAgICAgICAgICAgICAgICBrZXkgPSBtYXliZV9sYWJlbC5zdHJpcCgpLmxvd2VyKCkKICAgI"
    "CAgICAgICAgICAgICAgICBpZiBrZXkgaW4gbGFiZWxfbWFwOgogICAgICAgICAgICAgICAgICAgICAg"
    "ICBjdXJyZW50X2ZpZWxkID0gbGFiZWxfbWFwW2tleV0KICAgICAgICAgICAgICAgICAgICAgICAgcGF"
    "yc2VkW2N1cnJlbnRfZmllbGRdID0gbWF5YmVfdmFsdWUuc3RyaXAoKQogICAgICAgICAgICAgICAgIC"
    "AgICAgICBjb250aW51ZQoKICAgICAgICAgICAgICAgIGlmIGN1cnJlbnRfZmllbGQ6CiAgICAgICAgI"
    "CAgICAgICAgICAgaWYgcGFyc2VkW2N1cnJlbnRfZmllbGRdOgogICAgICAgICAgICAgICAgICAgICAg"
    "ICBwYXJzZWRbY3VycmVudF9maWVsZF0gKz0gIlxuIiArIHN0cmlwcGVkCiAgICAgICAgICAgICAgICA"
    "gICAgZWxzZToKICAgICAgICAgICAgICAgICAgICAgICAgcGFyc2VkW2N1cnJlbnRfZmllbGRdID0gc3"
    "RyaXBwZWQKCiAgICAgICAgICAgIHBhcnNlZFsibmFtZSJdID0gcGFyc2VkWyJuYW1lIl0uc3RyaXAoK"
    "QogICAgICAgICAgICBwYXJzZWRbInN0YXR1cyJdID0gcGFyc2VkWyJzdGF0dXMiXS5zdHJpcCgpIG9y"
    "ICJJZGVhIgogICAgICAgICAgICBwYXJzZWRbImRlc2NyaXB0aW9uIl0gPSBwYXJzZWRbImRlc2NyaXB"
    "0aW9uIl0uc3RyaXAoKQogICAgICAgICAgICBwYXJzZWRbIm5vdGVzIl0gPSBwYXJzZWRbIm5vdGVzIl"
    "0uc3RyaXAoKQoKICAgICAgICAgICAgaWYgbm90IHBhcnNlZFsibmFtZSJdOgogICAgICAgICAgICAgI"
    "CAgUU1lc3NhZ2VCb3gud2FybmluZygKICAgICAgICAgICAgICAgICAgICBzZWxmLAogICAgICAgICAg"
    "ICAgICAgICAgICJJbXBvcnQgRXJyb3IiLAogICAgICAgICAgICAgICAgICAgICJNb2R1bGUgaXMgcmV"
    "xdWlyZWQuIFBsZWFzZSBpbmNsdWRlIGEgJ01vZHVsZTonIGxpbmUuIiwKICAgICAgICAgICAgICAgIC"
    "kKICAgICAgICAgICAgICAgIHJldHVybgoKICAgICAgICAgICAgbmV3X3JlYyA9IHsKICAgICAgICAgI"
    "CAgICAgICJpZCI6ICAgICAgICAgIHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAgICAgIm5h"
    "bWUiOiAgICAgICAgcGFyc2VkWyJuYW1lIl1bOjYwXSwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiA"
    "gICAgIHBhcnNlZFsic3RhdHVzIl0sCiAgICAgICAgICAgICAgICAiZGVzY3JpcHRpb24iOiBwYXJzZW"
    "RbImRlc2NyaXB0aW9uIl0sCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICBwYXJzZWRbIm5vd"
    "GVzIl0sCiAgICAgICAgICAgICAgICAiY3JlYXRlZCI6ICAgICBkYXRldGltZS5ub3coKS5pc29mb3Jt"
    "YXQoKSwKICAgICAgICAgICAgICAgICJtb2RpZmllZCI6ICAgIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1"
    "hdCgpLAogICAgICAgICAgICB9CiAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKG5ld19yZW"
    "MpCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgI"
    "CAgICAgIHNlbGYucmVmcmVzaCgpCgoKIyDilIDilIAgUEFTUyA1IENPTVBMRVRFIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEFsbCB0Y"
    "WIgY29udGVudCBjbGFzc2VzIGRlZmluZWQuCiMgU0xTY2Fuc1RhYjogcmVidWlsdCDigJQgRGVsZXRl"
    "IGFkZGVkLCBNb2RpZnkgZml4ZWQsIHRpbWVzdGFtcCBwYXJzZXIgZml4ZWQsCiMgICAgICAgICAgICA"
    "gY2FyZC9ncmltb2lyZSBzdHlsZSwgY29weS10by1jbGlwYm9hcmQgY29udGV4dCBtZW51LgojIFNMQ2"
    "9tbWFuZHNUYWI6IGdvdGhpYyB0YWJsZSwg4qeJIENvcHkgQ29tbWFuZCBidXR0b24uCiMgSm9iVHJhY"
    "2tlclRhYjogZnVsbCByZWJ1aWxkIOKAlCBtdWx0aS1zZWxlY3QsIGFyY2hpdmUvcmVzdG9yZSwgQ1NW"
    "L1RTViBleHBvcnQuCiMgU2VsZlRhYjogaW5uZXIgc2FuY3R1bSBmb3IgaWRsZSBuYXJyYXRpdmUgYW5"
    "kIHJlZmxlY3Rpb24gb3V0cHV0LgojIERpYWdub3N0aWNzVGFiOiBzdHJ1Y3R1cmVkIGxvZyB3aXRoIG"
    "xldmVsLWNvbG9yZWQgb3V0cHV0LgojIExlc3NvbnNUYWI6IExTTCBGb3JiaWRkZW4gUnVsZXNldCBic"
    "m93c2VyIHdpdGggYWRkL2RlbGV0ZS9zZWFyY2guCiMKIyBOZXh0OiBQYXNzIDYg4oCUIE1haW4gV2lu"
    "ZG93CiMgKE1vcmdhbm5hRGVjayBjbGFzcywgZnVsbCBsYXlvdXQsIEFQU2NoZWR1bGVyLCBmaXJzdC1"
    "ydW4gZmxvdywKIyAgZGVwZW5kZW5jeSBib290c3RyYXAsIHNob3J0Y3V0IGNyZWF0aW9uLCBzdGFydH"
    "VwIHNlcXVlbmNlKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4"
    "pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pW"
    "Q4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4p"
    "WQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyA2OiBNQUlOIFdJTkRPVyAmI"
    "EVOVFJZIFBPSU5UCiMKIyBDb250YWluczoKIyAgIGJvb3RzdHJhcF9jaGVjaygpICAgICDigJQgZGVw"
    "ZW5kZW5jeSB2YWxpZGF0aW9uICsgYXV0by1pbnN0YWxsIGJlZm9yZSBVSQojICAgRmlyc3RSdW5EaWF"
    "sb2cgICAgICAgIOKAlCBtb2RlbCBwYXRoICsgY29ubmVjdGlvbiB0eXBlIHNlbGVjdGlvbgojICAgSm"
    "91cm5hbFNpZGViYXIgICAgICAgIOKAlCBjb2xsYXBzaWJsZSBsZWZ0IHNpZGViYXIgKHNlc3Npb24gY"
    "nJvd3NlciArIGpvdXJuYWwpCiMgICBUb3Jwb3JQYW5lbCAgICAgICAgICAg4oCUIEFXQUtFIC8gQVVU"
    "TyAvIFNVU1BFTkQgc3RhdGUgdG9nZ2xlCiMgICBNb3JnYW5uYURlY2sgICAgICAgICAg4oCUIG1haW4"
    "gd2luZG93LCBmdWxsIGxheW91dCwgYWxsIHNpZ25hbCBjb25uZWN0aW9ucwojICAgbWFpbigpICAgIC"
    "AgICAgICAgICAgIOKAlCBlbnRyeSBwb2ludCB3aXRoIGJvb3RzdHJhcCBzZXF1ZW5jZQojIOKVkOKVk"
    "OKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOK"
    "VkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkO"
    "KVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb"
    "3J0IHN1YnByb2Nlc3MKCgojIOKUgOKUgCBQUkUtTEFVTkNIIERFUEVOREVOQ1kgQk9PVFNUUkFQIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgApkZWYgYm9vdHN0cmFwX2NoZWNrKCkgLT4gTm9uZToKICAgICIiIgogICAgUnVucyBCRUZPU"
    "kUgUUFwcGxpY2F0aW9uIGlzIGNyZWF0ZWQuCiAgICBDaGVja3MgZm9yIFB5U2lkZTYgc2VwYXJhdGVs"
    "eSAoY2FuJ3Qgc2hvdyBHVUkgd2l0aG91dCBpdCkuCiAgICBBdXRvLWluc3RhbGxzIGFsbCBvdGhlciB"
    "taXNzaW5nIG5vbi1jcml0aWNhbCBkZXBzIHZpYSBwaXAuCiAgICBWYWxpZGF0ZXMgaW5zdGFsbHMgc3"
    "VjY2VlZGVkLgogICAgV3JpdGVzIHJlc3VsdHMgdG8gYSBib290c3RyYXAgbG9nIGZvciBEaWFnbm9zd"
    "GljcyB0YWIgdG8gcGljayB1cC4KICAgICIiIgogICAgIyDilIDilIAgU3RlcCAxOiBDaGVjayBQeVNp"
    "ZGU2IChjYW4ndCBhdXRvLWluc3RhbGwgd2l0aG91dCBpdCBhbHJlYWR5IHByZXNlbnQpIOKUgAogICA"
    "gdHJ5OgogICAgICAgIGltcG9ydCBQeVNpZGU2ICAjIG5vcWEKICAgIGV4Y2VwdCBJbXBvcnRFcnJvcj"
    "oKICAgICAgICAjIE5vIEdVSSBhdmFpbGFibGUg4oCUIHVzZSBXaW5kb3dzIG5hdGl2ZSBkaWFsb2cgd"
    "mlhIGN0eXBlcwogICAgICAgIHRyeToKICAgICAgICAgICAgaW1wb3J0IGN0eXBlcwogICAgICAgICAg"
    "ICBjdHlwZXMud2luZGxsLnVzZXIzMi5NZXNzYWdlQm94VygKICAgICAgICAgICAgICAgIDAsCiAgICA"
    "gICAgICAgICAgICAiUHlTaWRlNiBpcyByZXF1aXJlZCBidXQgbm90IGluc3RhbGxlZC5cblxuIgogIC"
    "AgICAgICAgICAgICAgIk9wZW4gYSB0ZXJtaW5hbCBhbmQgcnVuOlxuXG4iCiAgICAgICAgICAgICAgI"
    "CAiICAgIHBpcCBpbnN0YWxsIFB5U2lkZTZcblxuIgogICAgICAgICAgICAgICAgZiJUaGVuIHJlc3Rh"
    "cnQge0RFQ0tfTkFNRX0uIiwKICAgICAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0g4oCUIE1pc3Npbmc"
    "gRGVwZW5kZW5jeSIsCiAgICAgICAgICAgICAgICAweDEwICAjIE1CX0lDT05FUlJPUgogICAgICAgIC"
    "AgICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcHJpbnQoIkNSSVRJQ0FMO"
    "iBQeVNpZGU2IG5vdCBpbnN0YWxsZWQuIFJ1bjogcGlwIGluc3RhbGwgUHlTaWRlNiIpCiAgICAgICAg"
    "c3lzLmV4aXQoMSkKCiAgICAjIOKUgOKUgCBTdGVwIDI6IEF1dG8taW5zdGFsbCBvdGhlciBtaXNzaW5"
    "nIGRlcHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBfQVVUT19JTlNUQ"
    "UxMID0gWwogICAgICAgICgiYXBzY2hlZHVsZXIiLCAgICAgICAgICAgICAgICJhcHNjaGVkdWxlciIp"
    "LAogICAgICAgICgibG9ndXJ1IiwgICAgICAgICAgICAgICAgICAgICJsb2d1cnUiKSwKICAgICAgICA"
    "oInB5Z2FtZSIsICAgICAgICAgICAgICAgICAgICAicHlnYW1lIiksCiAgICAgICAgKCJweXdpbjMyIi"
    "wgICAgICAgICAgICAgICAgICAgInB5d2luMzIiKSwKICAgICAgICAoInBzdXRpbCIsICAgICAgICAgI"
    "CAgICAgICAgICAicHN1dGlsIiksCiAgICAgICAgKCJyZXF1ZXN0cyIsICAgICAgICAgICAgICAgICAg"
    "InJlcXVlc3RzIiksCiAgICAgICAgKCJnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQiLCAgImdvb2dsZWF"
    "waWNsaWVudCIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgtb2F1dGhsaWIiLCAgICAgICJnb29nbGVfYX"
    "V0aF9vYXV0aGxpYiIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgiLCAgICAgICAgICAgICAgICJnb29nb"
    "GUuYXV0aCIpLAogICAgXQoKICAgIGltcG9ydCBpbXBvcnRsaWIKICAgIGJvb3RzdHJhcF9sb2cgPSBb"
    "XQoKICAgIGZvciBwaXBfbmFtZSwgaW1wb3J0X25hbWUgaW4gX0FVVE9fSU5TVEFMTDoKICAgICAgICB"
    "0cnk6CiAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9ydF9uYW1lKQogICAgIC"
    "AgICAgICBib290c3RyYXBfbG9nLmFwcGVuZChmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0g4pyTIikKI"
    "CAgICAgICBleGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5k"
    "KAogICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IG1pc3Npbmcg4oCUIGluc3R"
    "hbGxpbmcuLi4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgcm"
    "VzdWx0ID0gc3VicHJvY2Vzcy5ydW4oCiAgICAgICAgICAgICAgICAgICAgW3N5cy5leGVjdXRhYmxlL"
    "CAiLW0iLCAicGlwIiwgImluc3RhbGwiLAogICAgICAgICAgICAgICAgICAgICBwaXBfbmFtZSwgIi0t"
    "cXVpZXQiLCAiLS1uby13YXJuLXNjcmlwdC1sb2NhdGlvbiJdLAogICAgICAgICAgICAgICAgICAgIGN"
    "hcHR1cmVfb3V0cHV0PVRydWUsIHRleHQ9VHJ1ZSwgdGltZW91dD0xMjAKICAgICAgICAgICAgICAgIC"
    "kKICAgICAgICAgICAgICAgIGlmIHJlc3VsdC5yZXR1cm5jb2RlID09IDA6CiAgICAgICAgICAgICAgI"
    "CAgICAgIyBWYWxpZGF0ZSBpdCBhY3R1YWxseSBpbXBvcnRlZCBub3cKICAgICAgICAgICAgICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9"
    "ydF9uYW1lKQogICAgICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgIC"
    "AgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsZWQg4"
    "pyTIgogICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgZXhjZXB0IElt"
    "cG9ydEVycm9yOgogICAgICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICA"
    "gICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsIG"
    "FwcGVhcmVkIHRvICIKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYic3VjY2VlZCBidXQgaW1wb"
    "3J0IHN0aWxsIGZhaWxzIOKAlCByZXN0YXJ0IG1heSAiCiAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICBmImJlIHJlcXVpcmVkLiIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICA"
    "gZWxzZToKICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgIC"
    "AgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3RhbGwgZmFpbGVkOiAiCiAgI"
    "CAgICAgICAgICAgICAgICAgICAgIGYie3Jlc3VsdC5zdGRlcnJbOjIwMF19IgogICAgICAgICAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IHN1YnByb2Nlc3MuVGltZW91dEV4cGlyZWQ6CiAgICA"
    "gICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltCT0"
    "9UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbCB0aW1lZCBvdXQuIgogICAgICAgICAgICAgICAgKQogI"
    "CAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBib290c3RyYXBf"
    "bG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5"
    "zdGFsbCBlcnJvcjoge2V9IgogICAgICAgICAgICAgICAgKQoKICAgICMg4pSA4pSAIFN0ZXAgMzogV3"
    "JpdGUgYm9vdHN0cmFwIGxvZyBmb3IgRGlhZ25vc3RpY3MgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgdHJ5Ogog"
    "ICAgICAgIGxvZ19wYXRoID0gU0NSSVBUX0RJUiAvICJsb2dzIiAvICJib290c3RyYXBfbG9nLnR4dCI"
    "KICAgICAgICB3aXRoIGxvZ19wYXRoLm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogIC"
    "AgICAgICAgICBmLndyaXRlKCJcbiIuam9pbihib290c3RyYXBfbG9nKSkKICAgIGV4Y2VwdCBFeGNlc"
    "HRpb246CiAgICAgICAgcGFzcwoKCiMg4pSA4pSAIEZJUlNUIFJVTiBESUFMT0cg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEZpcnN0UnVuR"
    "GlhbG9nKFFEaWFsb2cpOgogICAgIiIiCiAgICBTaG93biBvbiBmaXJzdCBsYXVuY2ggd2hlbiBjb25m"
    "aWcuanNvbiBkb2Vzbid0IGV4aXN0LgogICAgQ29sbGVjdHMgbW9kZWwgY29ubmVjdGlvbiB0eXBlIGF"
    "uZCBwYXRoL2tleS4KICAgIFZhbGlkYXRlcyBjb25uZWN0aW9uIGJlZm9yZSBhY2NlcHRpbmcuCiAgIC"
    "BXcml0ZXMgY29uZmlnLmpzb24gb24gc3VjY2Vzcy4KICAgIENyZWF0ZXMgZGVza3RvcCBzaG9ydGN1d"
    "C4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3Vw"
    "ZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5zZXRXaW5kb3dUaXRsZShmIuKcpiB7REV"
    "DS19OQU1FLnVwcGVyKCl9IOKAlCBGSVJTVCBBV0FLRU5JTkciKQogICAgICAgIHNlbGYuc2V0U3R5bG"
    "VTaGVldChTVFlMRSkKICAgICAgICBzZWxmLnNldEZpeGVkU2l6ZSg1MjAsIDQwMCkKICAgICAgICBzZ"
    "WxmLl9zZXR1cF91aSgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJv"
    "b3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0U3BhY2luZygxMCkKCiAgICAgICA"
    "gdGl0bGUgPSBRTGFiZWwoZiLinKYge0RFQ0tfTkFNRS51cHBlcigpfSDigJQgRklSU1QgQVdBS0VOSU"
    "5HIOKcpiIpCiAgICAgICAgdGl0bGUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge"
    "0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTRweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAg"
    "ICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2luZzogMnB4OyI"
    "KICAgICAgICApCiAgICAgICAgdGl0bGUuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ2"
    "5DZW50ZXIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQodGl0bGUpCgogICAgICAgIHN1YiA9IFFMYWJlb"
    "CgKICAgICAgICAgICAgZiJDb25maWd1cmUgdGhlIHZlc3NlbCBiZWZvcmUge0RFQ0tfTkFNRX0gbWF5"
    "IGF3YWtlbi5cbiIKICAgICAgICAgICAgIkFsbCBzZXR0aW5ncyBhcmUgc3RvcmVkIGxvY2FsbHkuIE5"
    "vdGhpbmcgbGVhdmVzIHRoaXMgbWFjaGluZS4iCiAgICAgICAgKQogICAgICAgIHN1Yi5zZXRTdHlsZV"
    "NoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgI"
    "gogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkK"
    "ICAgICAgICBzdWIuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICA"
    "gICAgcm9vdC5hZGRXaWRnZXQoc3ViKQoKICAgICAgICAjIOKUgOKUgCBDb25uZWN0aW9uIHR5cGUg4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgQUkgQ09"
    "OTkVDVElPTiBUWVBFIikpCiAgICAgICAgc2VsZi5fdHlwZV9jb21ibyA9IFFDb21ib0JveCgpCiAgIC"
    "AgICAgc2VsZi5fdHlwZV9jb21iby5hZGRJdGVtcyhbCiAgICAgICAgICAgICJMb2NhbCBtb2RlbCBmb"
    "2xkZXIgKHRyYW5zZm9ybWVycykiLAogICAgICAgICAgICAiT2xsYW1hIChsb2NhbCBzZXJ2aWNlKSIs"
    "CiAgICAgICAgICAgICJDbGF1ZGUgQVBJIChBbnRocm9waWMpIiwKICAgICAgICAgICAgIk9wZW5BSSB"
    "BUEkiLAogICAgICAgIF0pCiAgICAgICAgc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXhDaGFuZ2"
    "VkLmNvbm5lY3Qoc2VsZi5fb25fdHlwZV9jaGFuZ2UpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZ"
    "i5fdHlwZV9jb21ibykKCiAgICAgICAgIyDilIDilIAgRHluYW1pYyBjb25uZWN0aW9uIGZpZWxkcyDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zdG"
    "FjayA9IFFTdGFja2VkV2lkZ2V0KCkKCiAgICAgICAgIyBQYWdlIDA6IExvY2FsIHBhdGgKICAgICAgI"
    "CBwMCA9IFFXaWRnZXQoKQogICAgICAgIGwwID0gUUhCb3hMYXlvdXQocDApCiAgICAgICAgbDAuc2V0"
    "Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fbG9jYWxfcGF0aCA9IFFMaW5lRWR"
    "pdCgpCiAgICAgICAgc2VsZi5fbG9jYWxfcGF0aC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgIC"
    "AgIHIiRDpcQUlcTW9kZWxzXGRvbHBoaW4tOGIiCiAgICAgICAgKQogICAgICAgIGJ0bl9icm93c2UgP"
    "SBfZ290aGljX2J0bigiQnJvd3NlIikKICAgICAgICBidG5fYnJvd3NlLmNsaWNrZWQuY29ubmVjdChz"
    "ZWxmLl9icm93c2VfbW9kZWwpCiAgICAgICAgbDAuYWRkV2lkZ2V0KHNlbGYuX2xvY2FsX3BhdGgpOyB"
    "sMC5hZGRXaWRnZXQoYnRuX2Jyb3dzZSkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDApCg"
    "ogICAgICAgICMgUGFnZSAxOiBPbGxhbWEgbW9kZWwgbmFtZQogICAgICAgIHAxID0gUVdpZGdldCgpC"
    "iAgICAgICAgbDEgPSBRSEJveExheW91dChwMSkKICAgICAgICBsMS5zZXRDb250ZW50c01hcmdpbnMo"
    "MCwwLDAsMCkKICAgICAgICBzZWxmLl9vbGxhbWFfbW9kZWwgPSBRTGluZUVkaXQoKQogICAgICAgIHN"
    "lbGYuX29sbGFtYV9tb2RlbC5zZXRQbGFjZWhvbGRlclRleHQoImRvbHBoaW4tMi42LTdiIikKICAgIC"
    "AgICBsMS5hZGRXaWRnZXQoc2VsZi5fb2xsYW1hX21vZGVsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZ"
    "FdpZGdldChwMSkKCiAgICAgICAgIyBQYWdlIDI6IENsYXVkZSBBUEkga2V5CiAgICAgICAgcDIgPSBR"
    "V2lkZ2V0KCkKICAgICAgICBsMiA9IFFWQm94TGF5b3V0KHAyKQogICAgICAgIGwyLnNldENvbnRlbnR"
    "zTWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkgICA9IFFMaW5lRWRpdCgpCi"
    "AgICAgICAgc2VsZi5fY2xhdWRlX2tleS5zZXRQbGFjZWhvbGRlclRleHQoInNrLWFudC0uLi4iKQogI"
    "CAgICAgIHNlbGYuX2NsYXVkZV9rZXkuc2V0RWNob01vZGUoUUxpbmVFZGl0LkVjaG9Nb2RlLlBhc3N3"
    "b3JkKQogICAgICAgIHNlbGYuX2NsYXVkZV9tb2RlbCA9IFFMaW5lRWRpdCgiY2xhdWRlLXNvbm5ldC0"
    "0LTYiKQogICAgICAgIGwyLmFkZFdpZGdldChRTGFiZWwoIkFQSSBLZXk6IikpCiAgICAgICAgbDIuYW"
    "RkV2lkZ2V0KHNlbGYuX2NsYXVkZV9rZXkpCiAgICAgICAgbDIuYWRkV2lkZ2V0KFFMYWJlbCgiTW9kZ"
    "Ww6IikpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2NsYXVkZV9tb2RlbCkKICAgICAgICBzZWxm"
    "Ll9zdGFjay5hZGRXaWRnZXQocDIpCgogICAgICAgICMgUGFnZSAzOiBPcGVuQUkKICAgICAgICBwMyA"
    "9IFFXaWRnZXQoKQogICAgICAgIGwzID0gUVZCb3hMYXlvdXQocDMpCiAgICAgICAgbDMuc2V0Q29udG"
    "VudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fb2FpX2tleSAgID0gUUxpbmVFZGl0KCkKI"
    "CAgICAgICBzZWxmLl9vYWlfa2V5LnNldFBsYWNlaG9sZGVyVGV4dCgic2stLi4uIikKICAgICAgICBz"
    "ZWxmLl9vYWlfa2V5LnNldEVjaG9Nb2RlKFFMaW5lRWRpdC5FY2hvTW9kZS5QYXNzd29yZCkKICAgICA"
    "gICBzZWxmLl9vYWlfbW9kZWwgPSBRTGluZUVkaXQoImdwdC00byIpCiAgICAgICAgbDMuYWRkV2lkZ2"
    "V0KFFMYWJlbCgiQVBJIEtleToiKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fb2FpX2tleSkKI"
    "CAgICAgICBsMy5hZGRXaWRnZXQoUUxhYmVsKCJNb2RlbDoiKSkKICAgICAgICBsMy5hZGRXaWRnZXQo"
    "c2VsZi5fb2FpX21vZGVsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMykKCiAgICAgICA"
    "gcm9vdC5hZGRXaWRnZXQoc2VsZi5fc3RhY2spCgogICAgICAgICMg4pSA4pSAIFRlc3QgKyBzdGF0dX"
    "Mg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgdGVzdF9yb3cgPSBRSEJveExheW91dCgpCiAgICA"
    "gICAgc2VsZi5fYnRuX3Rlc3QgPSBfZ290aGljX2J0bigiVGVzdCBDb25uZWN0aW9uIikKICAgICAgIC"
    "BzZWxmLl9idG5fdGVzdC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdGVzdF9jb25uZWN0aW9uKQogICAgI"
    "CAgIHNlbGYuX3N0YXR1c19sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTo"
    "gMTBweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogIC"
    "AgICAgICkKICAgICAgICB0ZXN0X3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX3Rlc3QpCiAgICAgICAgd"
    "GVzdF9yb3cuYWRkV2lkZ2V0KHNlbGYuX3N0YXR1c19sYmwsIDEpCiAgICAgICAgcm9vdC5hZGRMYXlv"
    "dXQodGVzdF9yb3cpCgogICAgICAgICMg4pSA4pSAIEZhY2UgUGFjayDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIAKICAgICAgICByb290LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBGQUNF"
    "IFBBQ0sgKG9wdGlvbmFsIOKAlCBaSVAgZmlsZSkiKSkKICAgICAgICBmYWNlX3JvdyA9IFFIQm94TGF"
    "5b3V0KCkKICAgICAgICBzZWxmLl9mYWNlX3BhdGggPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2"
    "ZhY2VfcGF0aC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgIGYiQnJvd3NlIHRvIHtERUNLX"
    "05BTUV9IGZhY2UgcGFjayBaSVAgKG9wdGlvbmFsLCBjYW4gYWRkIGxhdGVyKSIKICAgICAgICApCiAg"
    "ICAgICAgc2VsZi5fZmFjZV9wYXRoLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3V"
    "uZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMX"
    "B4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICBmImZvb"
    "nQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTJweDsgcGFkZGluZzogNnB4"
    "IDEwcHg7IgogICAgICAgICkKICAgICAgICBidG5fZmFjZSA9IF9nb3RoaWNfYnRuKCJCcm93c2UiKQo"
    "gICAgICAgIGJ0bl9mYWNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9icm93c2VfZmFjZSkKICAgICAgIC"
    "BmYWNlX3Jvdy5hZGRXaWRnZXQoc2VsZi5fZmFjZV9wYXRoKQogICAgICAgIGZhY2Vfcm93LmFkZFdpZ"
    "GdldChidG5fZmFjZSkKICAgICAgICByb290LmFkZExheW91dChmYWNlX3JvdykKCiAgICAgICAgIyDi"
    "lIDilIAgU2hvcnRjdXQgb3B0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3Nob3J0Y3V0X"
    "2NiID0gUUNoZWNrQm94KAogICAgICAgICAgICAiQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgKHJlY29t"
    "bWVuZGVkKSIKICAgICAgICApCiAgICAgICAgc2VsZi5fc2hvcnRjdXRfY2Iuc2V0Q2hlY2tlZChUcnV"
    "lKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3Nob3J0Y3V0X2NiKQoKICAgICAgICAjIOKUgO"
    "KUgCBCdXR0b25zIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHJ"
    "vb3QuYWRkU3RyZXRjaCgpCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZW"
    "xmLl9idG5fYXdha2VuID0gX2dvdGhpY19idG4oIuKcpiBCRUdJTiBBV0FLRU5JTkciKQogICAgICAgI"
    "HNlbGYuX2J0bl9hd2FrZW4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBidG5fY2FuY2VsID0gX2dv"
    "dGhpY19idG4oIuKclyBDYW5jZWwiKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uY2xpY2tlZC5jb25"
    "uZWN0KHNlbGYuYWNjZXB0KQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYucm"
    "VqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9hd2FrZW4pCiAgICAgICAgY"
    "nRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICByb290LmFkZExheW91dChidG5fcm93"
    "KQoKICAgIGRlZiBfb25fdHlwZV9jaGFuZ2Uoc2VsZiwgaWR4OiBpbnQpIC0+IE5vbmU6CiAgICAgICA"
    "gc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KGlkeCkKICAgICAgICBzZWxmLl9idG5fYXdha2VuLn"
    "NldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRUZXh0KCIiKQoKICAgI"
    "GRlZiBfYnJvd3NlX21vZGVsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCA9IFFGaWxlRGlhbG9n"
    "LmdldEV4aXN0aW5nRGlyZWN0b3J5KAogICAgICAgICAgICBzZWxmLCAiU2VsZWN0IE1vZGVsIEZvbGR"
    "lciIsCiAgICAgICAgICAgIHIiRDpcQUlcTW9kZWxzIgogICAgICAgICkKICAgICAgICBpZiBwYXRoOg"
    "ogICAgICAgICAgICBzZWxmLl9sb2NhbF9wYXRoLnNldFRleHQocGF0aCkKCiAgICBkZWYgX2Jyb3dzZ"
    "V9mYWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCwgXyA9IFFGaWxlRGlhbG9nLmdldE9wZW5G"
    "aWxlTmFtZSgKICAgICAgICAgICAgc2VsZiwgIlNlbGVjdCBGYWNlIFBhY2sgWklQIiwKICAgICAgICA"
    "gICAgc3RyKFBhdGguaG9tZSgpIC8gIkRlc2t0b3AiKSwKICAgICAgICAgICAgIlpJUCBGaWxlcyAoKi"
    "56aXApIgogICAgICAgICkKICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICBzZWxmLl9mYWNlX3Bhd"
    "Gguc2V0VGV4dChwYXRoKQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGZhY2VfemlwX3BhdGgoc2VsZikg"
    "LT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9mYWNlX3BhdGgudGV4dCgpLnN0cmlwKCkKCiAgICB"
    "kZWYgX3Rlc3RfY29ubmVjdGlvbihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YXR1c19sYm"
    "wuc2V0VGV4dCgiVGVzdGluZy4uLiIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZ"
    "WV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIFFBcHBsaWNhdGl"
    "vbi5wcm9jZXNzRXZlbnRzKCkKCiAgICAgICAgaWR4ID0gc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW"
    "5kZXgoKQogICAgICAgIG9rICA9IEZhbHNlCiAgICAgICAgbXNnID0gIiIKCiAgICAgICAgaWYgaWR4I"
    "D09IDA6ICAjIExvY2FsCiAgICAgICAgICAgIHBhdGggPSBzZWxmLl9sb2NhbF9wYXRoLnRleHQoKS5z"
    "dHJpcCgpCiAgICAgICAgICAgIGlmIHBhdGggYW5kIFBhdGgocGF0aCkuZXhpc3RzKCk6CiAgICAgICA"
    "gICAgICAgICBvayAgPSBUcnVlCiAgICAgICAgICAgICAgICBtc2cgPSBmIkZvbGRlciBmb3VuZC4gTW"
    "9kZWwgd2lsbCBsb2FkIG9uIHN0YXJ0dXAuIgogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgI"
    "CAgbXNnID0gIkZvbGRlciBub3QgZm91bmQuIENoZWNrIHRoZSBwYXRoLiIKCiAgICAgICAgZWxpZiBp"
    "ZHggPT0gMTogICMgT2xsYW1hCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJlcSAgPSB"
    "1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KAogICAgICAgICAgICAgICAgICAgICJodHRwOi8vbG9jYWxob3"
    "N0OjExNDM0L2FwaS90YWdzIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgcmVzcCA9I"
    "HVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTMpCiAgICAgICAgICAgICAgICBvayAg"
    "ID0gcmVzcC5zdGF0dXMgPT0gMjAwCiAgICAgICAgICAgICAgICBtc2cgID0gIk9sbGFtYSBpcyBydW5"
    "uaW5nIOKckyIgaWYgb2sgZWxzZSAiT2xsYW1hIG5vdCByZXNwb25kaW5nLiIKICAgICAgICAgICAgZX"
    "hjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgbXNnID0gZiJPbGxhbWEgbm90IHJlY"
    "WNoYWJsZToge2V9IgoKICAgICAgICBlbGlmIGlkeCA9PSAyOiAgIyBDbGF1ZGUKICAgICAgICAgICAg"
    "a2V5ID0gc2VsZi5fY2xhdWRlX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBvayAgPSBib29"
    "sKGtleSBhbmQga2V5LnN0YXJ0c3dpdGgoInNrLWFudCIpKQogICAgICAgICAgICBtc2cgPSAiQVBJIG"
    "tleSBmb3JtYXQgbG9va3MgY29ycmVjdC4iIGlmIG9rIGVsc2UgIkVudGVyIGEgdmFsaWQgQ2xhdWRlI"
    "EFQSSBrZXkuIgoKICAgICAgICBlbGlmIGlkeCA9PSAzOiAgIyBPcGVuQUkKICAgICAgICAgICAga2V5"
    "ID0gc2VsZi5fb2FpX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBvayAgPSBib29sKGtleSB"
    "hbmQga2V5LnN0YXJ0c3dpdGgoInNrLSIpKQogICAgICAgICAgICBtc2cgPSAiQVBJIGtleSBmb3JtYX"
    "QgbG9va3MgY29ycmVjdC4iIGlmIG9rIGVsc2UgIkVudGVyIGEgdmFsaWQgT3BlbkFJIEFQSSBrZXkuI"
    "goKICAgICAgICBjb2xvciA9IENfR1JFRU4gaWYgb2sgZWxzZSBDX0NSSU1TT04KICAgICAgICBzZWxm"
    "Ll9zdGF0dXNfbGJsLnNldFRleHQobXNnKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0U3R5bGV"
    "TaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiAxMHB4OyBmb250LW"
    "ZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYnRuX2F3Y"
    "Wtlbi5zZXRFbmFibGVkKG9rKQoKICAgIGRlZiBidWlsZF9jb25maWcoc2VsZikgLT4gZGljdDoKICAg"
    "ICAgICAiIiJCdWlsZCBhbmQgcmV0dXJuIHVwZGF0ZWQgY29uZmlnIGRpY3QgZnJvbSBkaWFsb2cgc2V"
    "sZWN0aW9ucy4iIiIKICAgICAgICBjZmcgICAgID0gX2RlZmF1bHRfY29uZmlnKCkKICAgICAgICBpZH"
    "ggICAgID0gc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXgoKQogICAgICAgIHR5cGVzICAgPSBbI"
    "mxvY2FsIiwgIm9sbGFtYSIsICJjbGF1ZGUiLCAib3BlbmFpIl0KICAgICAgICBjZmdbIm1vZGVsIl1b"
    "InR5cGUiXSA9IHR5cGVzW2lkeF0KCiAgICAgICAgaWYgaWR4ID09IDA6CiAgICAgICAgICAgIGNmZ1s"
    "ibW9kZWwiXVsicGF0aCJdID0gc2VsZi5fbG9jYWxfcGF0aC50ZXh0KCkuc3RyaXAoKQogICAgICAgIG"
    "VsaWYgaWR4ID09IDE6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsib2xsYW1hX21vZGVsIl0gPSBzZ"
    "WxmLl9vbGxhbWFfbW9kZWwudGV4dCgpLnN0cmlwKCkgb3IgImRvbHBoaW4tMi42LTdiIgogICAgICAg"
    "IGVsaWYgaWR4ID09IDI6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX2tleSJdICAgPSBzZWx"
    "mLl9jbGF1ZGVfa2V5LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX2"
    "1vZGVsIl0gPSBzZWxmLl9jbGF1ZGVfbW9kZWwudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnW"
    "yJtb2RlbCJdWyJhcGlfdHlwZSJdICA9ICJjbGF1ZGUiCiAgICAgICAgZWxpZiBpZHggPT0gMzoKICAg"
    "ICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfa2V5Il0gICA9IHNlbGYuX29haV9rZXkudGV4dCgpLnN"
    "0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfbW9kZWwiXSA9IHNlbGYuX29haV9tb2"
    "RlbC50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV90eXBlIl0gID0gI"
    "m9wZW5haSIKCiAgICAgICAgY2ZnWyJmaXJzdF9ydW4iXSA9IEZhbHNlCiAgICAgICAgcmV0dXJuIGNm"
    "ZwoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGNyZWF0ZV9zaG9ydGN1dChzZWxmKSAtPiBib29sOgogICA"
    "gICAgIHJldHVybiBzZWxmLl9zaG9ydGN1dF9jYi5pc0NoZWNrZWQoKQoKCiMg4pSA4pSAIEpPVVJOQU"
    "wgU0lERUJBUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIAKY2xhc3MgSm91cm5hbFNpZGViYXIoUVdpZGdldCk6CiAgICAiIiIKICAgIENvbGxhcH"
    "NpYmxlIGxlZnQgc2lkZWJhciBuZXh0IHRvIHRoZSBwZXJzb25hIGNoYXQgdGFiLgogICAgVG9wOiBzZ"
    "XNzaW9uIGNvbnRyb2xzIChjdXJyZW50IHNlc3Npb24gbmFtZSwgc2F2ZS9sb2FkIGJ1dHRvbnMsCiAg"
    "ICAgICAgIGF1dG9zYXZlIGluZGljYXRvcikuCiAgICBCb2R5OiBzY3JvbGxhYmxlIHNlc3Npb24gbGl"
    "zdCDigJQgZGF0ZSwgQUkgbmFtZSwgbWVzc2FnZSBjb3VudC4KICAgIENvbGxhcHNlcyBsZWZ0d2FyZC"
    "B0byBhIHRoaW4gc3RyaXAuCgogICAgU2lnbmFsczoKICAgICAgICBzZXNzaW9uX2xvYWRfcmVxdWVzd"
    "GVkKHN0cikgICDigJQgZGF0ZSBzdHJpbmcgb2Ygc2Vzc2lvbiB0byBsb2FkCiAgICAgICAgc2Vzc2lv"
    "bl9jbGVhcl9yZXF1ZXN0ZWQoKSAgICAg4oCUIHJldHVybiB0byBjdXJyZW50IHNlc3Npb24KICAgICI"
    "iIgoKICAgIHNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQgID0gU2lnbmFsKHN0cikKICAgIHNlc3Npb25fY2"
    "xlYXJfcmVxdWVzdGVkID0gU2lnbmFsKCkKCiAgICBkZWYgX19pbml0X18oc2VsZiwgc2Vzc2lvbl9tZ"
    "3I6ICJTZXNzaW9uTWFuYWdlciIsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9f"
    "KHBhcmVudCkKICAgICAgICBzZWxmLl9zZXNzaW9uX21nciA9IHNlc3Npb25fbWdyCiAgICAgICAgc2V"
    "sZi5fZXhwYW5kZWQgICAgPSBUcnVlCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbG"
    "YucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgICMgVXNlI"
    "GEgaG9yaXpvbnRhbCByb290IGxheW91dCDigJQgY29udGVudCBvbiBsZWZ0LCB0b2dnbGUgc3RyaXAg"
    "b24gcmlnaHQKICAgICAgICByb290ID0gUUhCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldEN"
    "vbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHJvb3Quc2V0U3BhY2luZygwKQoKICAgIC"
    "AgICAjIOKUgOKUgCBDb2xsYXBzZSB0b2dnbGUgc3RyaXAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fdG9nZ2xlX3N0cmlwID0"
    "gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fdG9nZ2xlX3N0cmlwLnNldEZpeGVkV2lkdGgoMjApCiAgIC"
    "AgICAgc2VsZi5fdG9nZ2xlX3N0cmlwLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb"
    "3VuZDoge0NfQkczfTsgYm9yZGVyLXJpZ2h0OiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAg"
    "ICAgICApCiAgICAgICAgdHNfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fdG9nZ2xlX3N0cmlwKQo"
    "gICAgICAgIHRzX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgOCwgMCwgOCkKICAgICAgICBzZW"
    "xmLl90b2dnbGVfYnRuID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0R"
    "ml4ZWRTaXplKDE4LCAxOCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKXgCIpCiAg"
    "ICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm9"
    "1bmQ6IHRyYW5zcGFyZW50OyBjb2xvcjoge0NfR09MRF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZG"
    "VyOiBub25lOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfY"
    "nRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCiAgICAgICAgdHNfbGF5b3V0LmFkZFdpZGdl"
    "dChzZWxmLl90b2dnbGVfYnRuKQogICAgICAgIHRzX2xheW91dC5hZGRTdHJldGNoKCkKCiAgICAgICA"
    "gIyDilIDilIAgTWFpbiBjb250ZW50IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYu"
    "X2NvbnRlbnQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jb250ZW50LnNldE1pbmltdW1XaWR0aCg"
    "xODApCiAgICAgICAgc2VsZi5fY29udGVudC5zZXRNYXhpbXVtV2lkdGgoMjIwKQogICAgICAgIGNvbn"
    "RlbnRfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fY29udGVudCkKICAgICAgICBjb250ZW50X2xhe"
    "W91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBjb250ZW50X2xheW91dC5z"
    "ZXRTcGFjaW5nKDQpCgogICAgICAgICMgU2VjdGlvbiBsYWJlbAogICAgICAgIGNvbnRlbnRfbGF5b3V"
    "0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBKT1VSTkFMIikpCgogICAgICAgICMgQ3VycmVudC"
    "BzZXNzaW9uIGluZm8KICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUgPSBRTGFiZWwoIk5ldyBTZXNza"
    "W9uIikKICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR"
    "9LCBzZXJpZjsgIgogICAgICAgICAgICBmImZvbnQtc3R5bGU6IGl0YWxpYzsiCiAgICAgICAgKQogIC"
    "AgICAgIHNlbGYuX3Nlc3Npb25fbmFtZS5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGNvbnRlbnRfb"
    "GF5b3V0LmFkZFdpZGdldChzZWxmLl9zZXNzaW9uX25hbWUpCgogICAgICAgICMgU2F2ZSAvIExvYWQg"
    "cm93CiAgICAgICAgY3RybF9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX3NhdmU"
    "gPSBfZ290aGljX2J0bigi8J+SviIpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0Rml4ZWRTaXplKD"
    "MyLCAyNCkKICAgICAgICBzZWxmLl9idG5fc2F2ZS5zZXRUb29sVGlwKCJTYXZlIHNlc3Npb24gbm93I"
    "ikKICAgICAgICBzZWxmLl9idG5fbG9hZCA9IF9nb3RoaWNfYnRuKCLwn5OCIikKICAgICAgICBzZWxm"
    "Ll9idG5fbG9hZC5zZXRGaXhlZFNpemUoMzIsIDI0KQogICAgICAgIHNlbGYuX2J0bl9sb2FkLnNldFR"
    "vb2xUaXAoIkJyb3dzZSBhbmQgbG9hZCBhIHBhc3Qgc2Vzc2lvbiIpCiAgICAgICAgc2VsZi5fYXV0b3"
    "NhdmVfZG90ID0gUUxhYmVsKCLil48iKQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRTdHlsZ"
    "VNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOHB4OyBi"
    "b3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Quc2V0VG9vbFR"
    "pcCgiQXV0b3NhdmUgc3RhdHVzIikKICAgICAgICBzZWxmLl9idG5fc2F2ZS5jbGlja2VkLmNvbm5lY3"
    "Qoc2VsZi5fZG9fc2F2ZSkKICAgICAgICBzZWxmLl9idG5fbG9hZC5jbGlja2VkLmNvbm5lY3Qoc2VsZ"
    "i5fZG9fbG9hZCkKICAgICAgICBjdHJsX3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX3NhdmUpCiAgICAg"
    "ICAgY3RybF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9sb2FkKQogICAgICAgIGN0cmxfcm93LmFkZFd"
    "pZGdldChzZWxmLl9hdXRvc2F2ZV9kb3QpCiAgICAgICAgY3RybF9yb3cuYWRkU3RyZXRjaCgpCiAgIC"
    "AgICAgY29udGVudF9sYXlvdXQuYWRkTGF5b3V0KGN0cmxfcm93KQoKICAgICAgICAjIEpvdXJuYWwgb"
    "G9hZGVkIGluZGljYXRvcgogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsID0gUUxhYmVsKCIiKQogICAg"
    "ICAgIHNlbGYuX2pvdXJuYWxfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHt"
    "DX1BVUlBMRX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOy"
    "AiCiAgICAgICAgICAgIGYiZm9udC1zdHlsZTogaXRhbGljOyIKICAgICAgICApCiAgICAgICAgc2VsZ"
    "i5fam91cm5hbF9sYmwuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBjb250ZW50X2xheW91dC5hZGRX"
    "aWRnZXQoc2VsZi5fam91cm5hbF9sYmwpCgogICAgICAgICMgQ2xlYXIgam91cm5hbCBidXR0b24gKGh"
    "pZGRlbiB3aGVuIG5vdCBsb2FkZWQpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwgPSBfZ2"
    "90aGljX2J0bigi4pyXIFJldHVybiB0byBQcmVzZW50IikKICAgICAgICBzZWxmLl9idG5fY2xlYXJfa"
    "m91cm5hbC5zZXRWaXNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl9kb19jbGVhcl9qb3VybmFsKQogICAgICAgIGNvbnRlbnRfbGF5b3V"
    "0LmFkZFdpZGdldChzZWxmLl9idG5fY2xlYXJfam91cm5hbCkKCiAgICAgICAgIyBEaXZpZGVyCiAgIC"
    "AgICAgZGl2ID0gUUZyYW1lKCkKICAgICAgICBkaXYuc2V0RnJhbWVTaGFwZShRRnJhbWUuU2hhcGUuS"
    "ExpbmUpCiAgICAgICAgZGl2LnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyIp"
    "CiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KGRpdikKCiAgICAgICAgIyBTZXNzaW9uIGx"
    "pc3QKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgUEFTVC"
    "BTRVNTSU9OUyIpKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdCA9IFFMaXN0V2lkZ2V0KCkKICAgI"
    "CAgICBzZWxmLl9zZXNzaW9uX2xpc3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3Jv"
    "dW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCB"
    "zb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LC"
    "BzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICAgICAgZiJRTGlzdFdpZGdldDo6aXRlbTpzZ"
    "WxlY3RlZCB7eyBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IH19IgogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl9zZXNzaW9uX2xpc3QuaXRlbURvdWJsZUNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9zZXN"
    "zaW9uX2NsaWNrKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5pdGVtQ2xpY2tlZC5jb25uZWN0KH"
    "NlbGYuX29uX3Nlc3Npb25fY2xpY2spCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlb"
    "GYuX3Nlc3Npb25fbGlzdCwgMSkKCiAgICAgICAgIyBBZGQgY29udGVudCBhbmQgdG9nZ2xlIHN0cmlw"
    "IHRvIHRoZSByb290IGhvcml6b250YWwgbGF5b3V0CiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5"
    "fY29udGVudCkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90b2dnbGVfc3RyaXApCgogICAgZG"
    "VmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmL"
    "l9leHBhbmRlZAogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0VmlzaWJsZShzZWxmLl9leHBhbmRlZCkK"
    "ICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKXgCIgaWYgc2VsZi5fZXhwYW5kZWQgZWx"
    "zZSAi4pa2IikKICAgICAgICBzZWxmLnVwZGF0ZUdlb21ldHJ5KCkKICAgICAgICBwID0gc2VsZi5wYX"
    "JlbnRXaWRnZXQoKQogICAgICAgIGlmIHAgYW5kIHAubGF5b3V0KCk6CiAgICAgICAgICAgIHAubGF5b"
    "3V0KCkuYWN0aXZhdGUoKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2Vz"
    "c2lvbnMgPSBzZWxmLl9zZXNzaW9uX21nci5saXN0X3Nlc3Npb25zKCkKICAgICAgICBzZWxmLl9zZXN"
    "zaW9uX2xpc3QuY2xlYXIoKQogICAgICAgIGZvciBzIGluIHNlc3Npb25zOgogICAgICAgICAgICBkYX"
    "RlX3N0ciA9IHMuZ2V0KCJkYXRlIiwiIikKICAgICAgICAgICAgbmFtZSAgICAgPSBzLmdldCgibmFtZ"
    "SIsIGRhdGVfc3RyKVs6MzBdCiAgICAgICAgICAgIGNvdW50ICAgID0gcy5nZXQoIm1lc3NhZ2VfY291"
    "bnQiLCAwKQogICAgICAgICAgICBpdGVtID0gUUxpc3RXaWRnZXRJdGVtKGYie2RhdGVfc3RyfVxue25"
    "hbWV9ICh7Y291bnR9IG1zZ3MpIikKICAgICAgICAgICAgaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm"
    "9sZS5Vc2VyUm9sZSwgZGF0ZV9zdHIpCiAgICAgICAgICAgIGl0ZW0uc2V0VG9vbFRpcChmIkRvdWJsZ"
    "S1jbGljayB0byBsb2FkIHNlc3Npb24gZnJvbSB7ZGF0ZV9zdHJ9IikKICAgICAgICAgICAgc2VsZi5f"
    "c2Vzc2lvbl9saXN0LmFkZEl0ZW0oaXRlbSkKCiAgICBkZWYgc2V0X3Nlc3Npb25fbmFtZShzZWxmLCB"
    "uYW1lOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNldFRleHQobmFtZV"
    "s6NTBdIG9yICJOZXcgU2Vzc2lvbiIpCgogICAgZGVmIHNldF9hdXRvc2F2ZV9pbmRpY2F0b3Ioc2VsZ"
    "iwgc2F2ZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dSRUVOIGlmIHNhdmVkIGVsc2UgQ19URVhUX0R"
    "JTX07ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDhweDsgYm9yZGVyOiBub25lOyIKICAgICAgIC"
    "ApCiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFRvb2xUaXAoCiAgICAgICAgICAgICJBdXRvc"
    "2F2ZWQiIGlmIHNhdmVkIGVsc2UgIlBlbmRpbmcgYXV0b3NhdmUiCiAgICAgICAgKQoKICAgIGRlZiBz"
    "ZXRfam91cm5hbF9sb2FkZWQoc2VsZiwgZGF0ZV9zdHI6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWx"
    "mLl9qb3VybmFsX2xibC5zZXRUZXh0KGYi8J+TliBKb3VybmFsOiB7ZGF0ZV9zdHJ9IikKICAgICAgIC"
    "BzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKFRydWUpCgogICAgZGVmIGNsZWFyX2pvd"
    "XJuYWxfaW5kaWNhdG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0"
    "VGV4dCgiIikKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKEZhbHNlKQo"
    "KICAgIGRlZiBfZG9fc2F2ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nlc3Npb25fbWdyLn"
    "NhdmUoKQogICAgICAgIHNlbGYuc2V0X2F1dG9zYXZlX2luZGljYXRvcihUcnVlKQogICAgICAgIHNlb"
    "GYucmVmcmVzaCgpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0VGV4dCgi4pyTIikKICAgICAgICBR"
    "VGltZXIuc2luZ2xlU2hvdCgxNTAwLCBsYW1iZGE6IHNlbGYuX2J0bl9zYXZlLnNldFRleHQoIvCfkr4"
    "iKSkKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgzMDAwLCBsYW1iZGE6IHNlbGYuc2V0X2F1dG9zYX"
    "ZlX2luZGljYXRvcihGYWxzZSkpCgogICAgZGVmIF9kb19sb2FkKHNlbGYpIC0+IE5vbmU6CiAgICAgI"
    "CAgIyBUcnkgc2VsZWN0ZWQgaXRlbSBmaXJzdAogICAgICAgIGl0ZW0gPSBzZWxmLl9zZXNzaW9uX2xp"
    "c3QuY3VycmVudEl0ZW0oKQogICAgICAgIGlmIG5vdCBpdGVtOgogICAgICAgICAgICAjIElmIG5vdGh"
    "pbmcgc2VsZWN0ZWQsIHRyeSB0aGUgZmlyc3QgaXRlbQogICAgICAgICAgICBpZiBzZWxmLl9zZXNzaW"
    "9uX2xpc3QuY291bnQoKSA+IDA6CiAgICAgICAgICAgICAgICBpdGVtID0gc2VsZi5fc2Vzc2lvbl9sa"
    "XN0Lml0ZW0oMCkKICAgICAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5zZXRDdXJyZW50SXRl"
    "bShpdGVtKQogICAgICAgIGlmIGl0ZW06CiAgICAgICAgICAgIGRhdGVfc3RyID0gaXRlbS5kYXRhKFF"
    "0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkKICAgICAgICAgICAgc2VsZi5zZXNzaW9uX2xvYWRfcmVxdW"
    "VzdGVkLmVtaXQoZGF0ZV9zdHIpCgogICAgZGVmIF9vbl9zZXNzaW9uX2NsaWNrKHNlbGYsIGl0ZW0pI"
    "C0+IE5vbmU6CiAgICAgICAgZGF0ZV9zdHIgPSBpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJS"
    "b2xlKQogICAgICAgIHNlbGYuc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5lbWl0KGRhdGVfc3RyKQoKICA"
    "gIGRlZiBfZG9fY2xlYXJfam91cm5hbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuc2Vzc2lvbl"
    "9jbGVhcl9yZXF1ZXN0ZWQuZW1pdCgpCiAgICAgICAgc2VsZi5jbGVhcl9qb3VybmFsX2luZGljYXRvc"
    "igpCgoKIyDilIDilIAgVE9SUE9SIFBBTkVMIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBUb3Jwb3JQYW5lbChRV2lkZ"
    "2V0KToKICAgICIiIgogICAgVGhyZWUtc3RhdGUgc3VzcGVuc2lvbiB0b2dnbGU6IEFXQUtFIHwgQVVU"
    "TyB8IFNVU1BFTkQKCiAgICBBV0FLRSAg4oCUIG1vZGVsIGxvYWRlZCwgYXV0by10b3Jwb3IgZGlzYWJ"
    "sZWQsIGlnbm9yZXMgVlJBTSBwcmVzc3VyZQogICAgQVVUTyAgIOKAlCBtb2RlbCBsb2FkZWQsIG1vbm"
    "l0b3JzIFZSQU0gcHJlc3N1cmUsIGF1dG8tdG9ycG9yIGlmIHN1c3RhaW5lZAogICAgU1VTUEVORCDig"
    "JQgbW9kZWwgdW5sb2FkZWQsIHN0YXlzIHN1c3BlbmRlZCB1bnRpbCBtYW51YWxseSBjaGFuZ2VkCgog"
    "ICAgU2lnbmFsczoKICAgICAgICBzdGF0ZV9jaGFuZ2VkKHN0cikgIOKAlCAiQVdBS0UiIHwgIkFVVE8"
    "iIHwgIlNVU1BFTkQiCiAgICAiIiIKCiAgICBzdGF0ZV9jaGFuZ2VkID0gU2lnbmFsKHN0cikKCiAgIC"
    "BTVEFURVMgPSBbIkFXQUtFIiwgIkFVVE8iLCAiU1VTUEVORCJdCgogICAgU1RBVEVfU1RZTEVTID0ge"
    "wogICAgICAgICJBV0FLRSI6IHsKICAgICAgICAgICAgImFjdGl2ZSI6ICAgZiJiYWNrZ3JvdW5kOiAj"
    "MmExYTA1OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI"
    "6IDFweCBzb2xpZCB7Q19HT0xEfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgIC"
    "AgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggO"
    "HB4OyIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6"
    "IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGl"
    "kIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgIC"
    "BmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogI"
    "CAgICAgICAgICAibGFiZWwiOiAgICAi4piAIEFXQUtFIiwKICAgICAgICAgICAgInRvb2x0aXAiOiAg"
    "Ik1vZGVsIGFjdGl2ZS4gQXV0by10b3Jwb3IgZGlzYWJsZWQuIiwKICAgICAgICB9LAogICAgICAgICJ"
    "BVVRPIjogewogICAgICAgICAgICAiYWN0aXZlIjogICBmImJhY2tncm91bmQ6ICMxYTEwMDU7IGNvbG"
    "9yOiAjY2M4ODIyOyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQgI"
    "2NjODgyMjsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9u"
    "dC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICA"
    "gICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfT"
    "sgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07I"
    "GJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTog"
    "OXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAibGF"
    "iZWwiOiAgICAi4peJIEFVVE8iLAogICAgICAgICAgICAidG9vbHRpcCI6ICAiTW9kZWwgYWN0aXZlLi"
    "BBdXRvLXN1c3BlbmQgb24gVlJBTSBwcmVzc3VyZS4iLAogICAgICAgIH0sCiAgICAgICAgIlNVU1BFT"
    "kQiOiB7CiAgICAgICAgICAgICJhY3RpdmUiOiAgIGYiYmFja2dyb3VuZDoge0NfUFVSUExFX0RJTX07"
    "IGNvbG9yOiB7Q19QVVJQTEV9OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHg"
    "gc29saWQge0NfUFVSUExFfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgIC"
    "AgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4O"
    "yIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtD"
    "X1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHt"
    "DX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmIm"
    "ZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgI"
    "CAgICAgICAibGFiZWwiOiAgICBmIuKasCB7VUlfU1VTUEVOU0lPTl9MQUJFTC5zdHJpcCgpIGlmIHN0"
    "cihVSV9TVVNQRU5TSU9OX0xBQkVMKS5zdHJpcCgpIGVsc2UgJ1N1c3BlbmQnfSIsCiAgICAgICAgICA"
    "gICJ0b29sdGlwIjogIGYiTW9kZWwgdW5sb2FkZWQuIHtERUNLX05BTUV9IHNsZWVwcyB1bnRpbCBtYW"
    "51YWxseSBhd2FrZW5lZC4iLAogICAgICAgIH0sCiAgICB9CgogICAgZGVmIF9faW5pdF9fKHNlbGYsI"
    "HBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxm"
    "Ll9jdXJyZW50ID0gIkFXQUtFIgogICAgICAgIHNlbGYuX2J1dHRvbnM6IGRpY3Rbc3RyLCBRUHVzaEJ"
    "1dHRvbl0gPSB7fQogICAgICAgIGxheW91dCA9IFFIQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3"
    "V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nK"
    "DIpCgogICAgICAgIGZvciBzdGF0ZSBpbiBzZWxmLlNUQVRFUzoKICAgICAgICAgICAgYnRuID0gUVB1"
    "c2hCdXR0b24oc2VsZi5TVEFURV9TVFlMRVNbc3RhdGVdWyJsYWJlbCJdKQogICAgICAgICAgICBidG4"
    "uc2V0VG9vbFRpcChzZWxmLlNUQVRFX1NUWUxFU1tzdGF0ZV1bInRvb2x0aXAiXSkKICAgICAgICAgIC"
    "AgYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgICAgICBidG4uY2xpY2tlZC5jb25uZWN0KGxhb"
    "WJkYSBjaGVja2VkLCBzPXN0YXRlOiBzZWxmLl9zZXRfc3RhdGUocykpCiAgICAgICAgICAgIHNlbGYu"
    "X2J1dHRvbnNbc3RhdGVdID0gYnRuCiAgICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoYnRuKQoKICA"
    "gICAgICBzZWxmLl9hcHBseV9zdHlsZXMoKQoKICAgIGRlZiBfc2V0X3N0YXRlKHNlbGYsIHN0YXRlOi"
    "BzdHIpIC0+IE5vbmU6CiAgICAgICAgaWYgc3RhdGUgPT0gc2VsZi5fY3VycmVudDoKICAgICAgICAgI"
    "CAgcmV0dXJuCiAgICAgICAgc2VsZi5fY3VycmVudCA9IHN0YXRlCiAgICAgICAgc2VsZi5fYXBwbHlf"
    "c3R5bGVzKCkKICAgICAgICBzZWxmLnN0YXRlX2NoYW5nZWQuZW1pdChzdGF0ZSkKCiAgICBkZWYgX2F"
    "wcGx5X3N0eWxlcyhzZWxmKSAtPiBOb25lOgogICAgICAgIGZvciBzdGF0ZSwgYnRuIGluIHNlbGYuX2"
    "J1dHRvbnMuaXRlbXMoKToKICAgICAgICAgICAgc3R5bGVfa2V5ID0gImFjdGl2ZSIgaWYgc3RhdGUgP"
    "T0gc2VsZi5fY3VycmVudCBlbHNlICJpbmFjdGl2ZSIKICAgICAgICAgICAgYnRuLnNldFN0eWxlU2hl"
    "ZXQoc2VsZi5TVEFURV9TVFlMRVNbc3RhdGVdW3N0eWxlX2tleV0pCgogICAgQHByb3BlcnR5CiAgICB"
    "kZWYgY3VycmVudF9zdGF0ZShzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2N1cnJlbn"
    "QKCiAgICBkZWYgc2V0X3N0YXRlKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIiIiU"
    "2V0IHN0YXRlIHByb2dyYW1tYXRpY2FsbHkgKGUuZy4gZnJvbSBhdXRvLXRvcnBvciBkZXRlY3Rpb24p"
    "LiIiIgogICAgICAgIGlmIHN0YXRlIGluIHNlbGYuU1RBVEVTOgogICAgICAgICAgICBzZWxmLl9zZXR"
    "fc3RhdGUoc3RhdGUpCgoKY2xhc3MgU2V0dGluZ3NTZWN0aW9uKFFXaWRnZXQpOgogICAgIiIiU2ltcG"
    "xlIGNvbGxhcHNpYmxlIHNlY3Rpb24gdXNlZCBieSBTZXR0aW5nc1RhYi4iIiIKCiAgICBkZWYgX19pb"
    "ml0X18oc2VsZiwgdGl0bGU6IHN0ciwgcGFyZW50PU5vbmUsIGV4cGFuZGVkOiBib29sID0gVHJ1ZSk6"
    "CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSB"
    "leHBhbmRlZAoKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldE"
    "NvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHJvb3Quc2V0U3BhY2luZygwKQoKICAgI"
    "CAgICBzZWxmLl9oZWFkZXJfYnRuID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX2hlYWRlcl9i"
    "dG4uc2V0VGV4dChmIuKWvCB7dGl0bGV9IiBpZiBleHBhbmRlZCBlbHNlIGYi4pa2IHt0aXRsZX0iKQo"
    "gICAgICAgIHNlbGYuX2hlYWRlcl9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3"
    "JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT"
    "05fRElNfTsgIgogICAgICAgICAgICBmInBhZGRpbmc6IDZweDsgdGV4dC1hbGlnbjogbGVmdDsgZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7IgogICAgICAgICkKICAgICAgICBzZWxmLl9oZWFkZXJfYnRuLmNsaWNrZWQ"
    "uY29ubmVjdChzZWxmLl90b2dnbGUpCgogICAgICAgIHNlbGYuX2NvbnRlbnQgPSBRV2lkZ2V0KCkKIC"
    "AgICAgICBzZWxmLl9jb250ZW50X2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX2NvbnRlbnQpCiAgI"
    "CAgICAgc2VsZi5fY29udGVudF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDgsIDgsIDgsIDgpCiAg"
    "ICAgICAgc2VsZi5fY29udGVudF9sYXlvdXQuc2V0U3BhY2luZyg4KQogICAgICAgIHNlbGYuX2NvbnR"
    "lbnQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZX"
    "I6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItdG9wOiBub25lOyIKICAgICAgICApCiAgICAgI"
    "CAgc2VsZi5fY29udGVudC5zZXRWaXNpYmxlKGV4cGFuZGVkKQoKICAgICAgICByb290LmFkZFdpZGdl"
    "dChzZWxmLl9oZWFkZXJfYnRuKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2NvbnRlbnQpCgo"
    "gICAgQHByb3BlcnR5CiAgICBkZWYgY29udGVudF9sYXlvdXQoc2VsZikgLT4gUVZCb3hMYXlvdXQ6Ci"
    "AgICAgICAgcmV0dXJuIHNlbGYuX2NvbnRlbnRfbGF5b3V0CgogICAgZGVmIF90b2dnbGUoc2VsZikgL"
    "T4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAg"
    "IHNlbGYuX2hlYWRlcl9idG4uc2V0VGV4dCgKICAgICAgICAgICAgc2VsZi5faGVhZGVyX2J0bi50ZXh"
    "0KCkucmVwbGFjZSgi4pa8IiwgIuKWtiIsIDEpCiAgICAgICAgICAgIGlmIG5vdCBzZWxmLl9leHBhbm"
    "RlZCBlbHNlCiAgICAgICAgICAgIHNlbGYuX2hlYWRlcl9idG4udGV4dCgpLnJlcGxhY2UoIuKWtiIsI"
    "CLilrwiLCAxKQogICAgICAgICkKICAgICAgICBzZWxmLl9jb250ZW50LnNldFZpc2libGUoc2VsZi5f"
    "ZXhwYW5kZWQpCgoKY2xhc3MgU2V0dGluZ3NUYWIoUVdpZGdldCk6CiAgICAiIiJEZWNrLXdpZGUgcnV"
    "udGltZSBzZXR0aW5ncyB0YWIuIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGRlY2tfd2luZG93Oi"
    "AiRWNob0RlY2siLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpC"
    "iAgICAgICAgc2VsZi5fZGVjayA9IGRlY2tfd2luZG93CiAgICAgICAgc2VsZi5fc2VjdGlvbl9yZWdp"
    "c3RyeTogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc2VjdGlvbl93aWRnZXRzOiBkaWN0W3N"
    "0ciwgU2V0dGluZ3NTZWN0aW9uXSA9IHt9CgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQ"
    "ogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgcm9vdC5zZ"
    "XRTcGFjaW5nKDApCgogICAgICAgIHNjcm9sbCA9IFFTY3JvbGxBcmVhKCkKICAgICAgICBzY3JvbGwu"
    "c2V0V2lkZ2V0UmVzaXphYmxlKFRydWUpCiAgICAgICAgc2Nyb2xsLnNldEhvcml6b250YWxTY3JvbGx"
    "CYXJQb2xpY3koUXQuU2Nyb2xsQmFyUG9saWN5LlNjcm9sbEJhckFsd2F5c09mZikKICAgICAgICBzY3"
    "JvbGwuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHfTsgYm9yZGVyOiAxcHggc29saWQge"
    "0NfQ1JJTVNPTl9ESU19OyIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2Nyb2xsKQoKICAgICAgICBi"
    "b2R5ID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fYm9keV9sYXlvdXQgPSBRVkJveExheW91dChib2R"
    "5KQogICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQ"
    "ogICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0LnNldFNwYWNpbmcoOCkKICAgICAgICBzY3JvbGwuc2V0V"
    "2lkZ2V0KGJvZHkpCgogICAgICAgIHNlbGYuX3JlZ2lzdGVyX2NvcmVfc2VjdGlvbnMoKQoKICAgIGRl"
    "ZiBfcmVnaXN0ZXJfc2VjdGlvbihzZWxmLCAqLCBzZWN0aW9uX2lkOiBzdHIsIHRpdGxlOiBzdHIsIGN"
    "hdGVnb3J5OiBzdHIsIHNvdXJjZV9vd25lcjogc3RyLCBzb3J0X2tleTogaW50LCBidWlsZGVyKSAtPi"
    "BOb25lOgogICAgICAgIHNlbGYuX3NlY3Rpb25fcmVnaXN0cnkuYXBwZW5kKHsKICAgICAgICAgICAgI"
    "nNlY3Rpb25faWQiOiBzZWN0aW9uX2lkLAogICAgICAgICAgICAidGl0bGUiOiB0aXRsZSwKICAgICAg"
    "ICAgICAgImNhdGVnb3J5IjogY2F0ZWdvcnksCiAgICAgICAgICAgICJzb3VyY2Vfb3duZXIiOiBzb3V"
    "yY2Vfb3duZXIsCiAgICAgICAgICAgICJzb3J0X2tleSI6IHNvcnRfa2V5LAogICAgICAgICAgICAiYn"
    "VpbGRlciI6IGJ1aWxkZXIsCiAgICAgICAgfSkKCiAgICBkZWYgX3JlZ2lzdGVyX2NvcmVfc2VjdGlvb"
    "nMoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWdpc3Rlcl9zZWN0aW9uKAogICAgICAgICAg"
    "ICBzZWN0aW9uX2lkPSJzeXN0ZW1fc2V0dGluZ3MiLAogICAgICAgICAgICB0aXRsZT0iU3lzdGVtIFN"
    "ldHRpbmdzIiwKICAgICAgICAgICAgY2F0ZWdvcnk9ImNvcmUiLAogICAgICAgICAgICBzb3VyY2Vfb3"
    "duZXI9ImRlY2tfcnVudGltZSIsCiAgICAgICAgICAgIHNvcnRfa2V5PTEwMCwKICAgICAgICAgICAgY"
    "nVpbGRlcj1zZWxmLl9idWlsZF9zeXN0ZW1fc2VjdGlvbiwKICAgICAgICApCiAgICAgICAgc2VsZi5f"
    "cmVnaXN0ZXJfc2VjdGlvbigKICAgICAgICAgICAgc2VjdGlvbl9pZD0iaW50ZWdyYXRpb25fc2V0dGl"
    "uZ3MiLAogICAgICAgICAgICB0aXRsZT0iSW50ZWdyYXRpb24gU2V0dGluZ3MiLAogICAgICAgICAgIC"
    "BjYXRlZ29yeT0iY29yZSIsCiAgICAgICAgICAgIHNvdXJjZV9vd25lcj0iZGVja19ydW50aW1lIiwKI"
    "CAgICAgICAgICAgc29ydF9rZXk9MjAwLAogICAgICAgICAgICBidWlsZGVyPXNlbGYuX2J1aWxkX2lu"
    "dGVncmF0aW9uX3NlY3Rpb24sCiAgICAgICAgKQogICAgICAgIHNlbGYuX3JlZ2lzdGVyX3NlY3Rpb24"
    "oCiAgICAgICAgICAgIHNlY3Rpb25faWQ9InVpX3NldHRpbmdzIiwKICAgICAgICAgICAgdGl0bGU9Il"
    "VJIFNldHRpbmdzIiwKICAgICAgICAgICAgY2F0ZWdvcnk9ImNvcmUiLAogICAgICAgICAgICBzb3VyY"
    "2Vfb3duZXI9ImRlY2tfcnVudGltZSIsCiAgICAgICAgICAgIHNvcnRfa2V5PTMwMCwKICAgICAgICAg"
    "ICAgYnVpbGRlcj1zZWxmLl9idWlsZF91aV9zZWN0aW9uLAogICAgICAgICkKCiAgICAgICAgZm9yIG1"
    "ldGEgaW4gc29ydGVkKHNlbGYuX3NlY3Rpb25fcmVnaXN0cnksIGtleT1sYW1iZGEgbTogbS5nZXQoIn"
    "NvcnRfa2V5IiwgOTk5OSkpOgogICAgICAgICAgICBzZWN0aW9uID0gU2V0dGluZ3NTZWN0aW9uKG1ld"
    "GFbInRpdGxlIl0sIGV4cGFuZGVkPVRydWUpCiAgICAgICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0LmFk"
    "ZFdpZGdldChzZWN0aW9uKQogICAgICAgICAgICBzZWxmLl9zZWN0aW9uX3dpZGdldHNbbWV0YVsic2V"
    "jdGlvbl9pZCJdXSA9IHNlY3Rpb24KICAgICAgICAgICAgbWV0YVsiYnVpbGRlciJdKHNlY3Rpb24uY2"
    "9udGVudF9sYXlvdXQpCgogICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0LmFkZFN0cmV0Y2goMSkKCiAgI"
    "CBkZWYgX2J1aWxkX3N5c3RlbV9zZWN0aW9uKHNlbGYsIGxheW91dDogUVZCb3hMYXlvdXQpIC0+IE5v"
    "bmU6CiAgICAgICAgaWYgc2VsZi5fZGVjay5fdG9ycG9yX3BhbmVsIGlzIG5vdCBOb25lOgogICAgICA"
    "gICAgICBsYXlvdXQuYWRkV2lkZ2V0KFFMYWJlbCgiT3BlcmF0aW9uYWwgTW9kZSIpKQogICAgICAgIC"
    "AgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2RlY2suX3RvcnBvcl9wYW5lbCkKCiAgICAgICAgbGF5b"
    "3V0LmFkZFdpZGdldChRTGFiZWwoIklkbGUiKSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYu"
    "X2RlY2suX2lkbGVfYnRuKQoKICAgICAgICBzZXR0aW5ncyA9IENGRy5nZXQoInNldHRpbmdzIiwge30"
    "pCiAgICAgICAgdHpfYXV0byA9IGJvb2woc2V0dGluZ3MuZ2V0KCJ0aW1lem9uZV9hdXRvX2RldGVjdC"
    "IsIFRydWUpKQogICAgICAgIHR6X292ZXJyaWRlID0gc3RyKHNldHRpbmdzLmdldCgidGltZXpvbmVfb"
    "3ZlcnJpZGUiLCAiIikgb3IgIiIpLnN0cmlwKCkKCiAgICAgICAgdHpfYXV0b19jaGsgPSBRQ2hlY2tC"
    "b3goIkF1dG8tZGV0ZWN0IGxvY2FsL3N5c3RlbSB0aW1lIHpvbmUiKQogICAgICAgIHR6X2F1dG9fY2h"
    "rLnNldENoZWNrZWQodHpfYXV0bykKICAgICAgICB0el9hdXRvX2Noay50b2dnbGVkLmNvbm5lY3Qoc2"
    "VsZi5fZGVjay5fc2V0X3RpbWV6b25lX2F1dG9fZGV0ZWN0KQogICAgICAgIGxheW91dC5hZGRXaWRnZ"
    "XQodHpfYXV0b19jaGspCgogICAgICAgIHR6X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICB0el9y"
    "b3cuYWRkV2lkZ2V0KFFMYWJlbCgiTWFudWFsIFRpbWUgWm9uZSBPdmVycmlkZToiKSkKICAgICAgICB"
    "0el9jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgdHpfY29tYm8uc2V0RWRpdGFibGUoVHJ1ZSkKIC"
    "AgICAgICB0el9vcHRpb25zID0gWwogICAgICAgICAgICAiQW1lcmljYS9DaGljYWdvIiwgIkFtZXJpY"
    "2EvTmV3X1lvcmsiLCAiQW1lcmljYS9Mb3NfQW5nZWxlcyIsCiAgICAgICAgICAgICJBbWVyaWNhL0Rl"
    "bnZlciIsICJVVEMiCiAgICAgICAgXQogICAgICAgIHR6X2NvbWJvLmFkZEl0ZW1zKHR6X29wdGlvbnM"
    "pCiAgICAgICAgaWYgdHpfb3ZlcnJpZGU6CiAgICAgICAgICAgIGlmIHR6X2NvbWJvLmZpbmRUZXh0KH"
    "R6X292ZXJyaWRlKSA8IDA6CiAgICAgICAgICAgICAgICB0el9jb21iby5hZGRJdGVtKHR6X292ZXJya"
    "WRlKQogICAgICAgICAgICB0el9jb21iby5zZXRDdXJyZW50VGV4dCh0el9vdmVycmlkZSkKICAgICAg"
    "ICBlbHNlOgogICAgICAgICAgICB0el9jb21iby5zZXRDdXJyZW50VGV4dCgiQW1lcmljYS9DaGljYWd"
    "vIikKICAgICAgICB0el9jb21iby5zZXRFbmFibGVkKG5vdCB0el9hdXRvKQogICAgICAgIHR6X2NvbW"
    "JvLmN1cnJlbnRUZXh0Q2hhbmdlZC5jb25uZWN0KHNlbGYuX2RlY2suX3NldF90aW1lem9uZV9vdmVyc"
    "mlkZSkKICAgICAgICB0el9hdXRvX2Noay50b2dnbGVkLmNvbm5lY3QobGFtYmRhIGVuYWJsZWQ6IHR6"
    "X2NvbWJvLnNldEVuYWJsZWQobm90IGVuYWJsZWQpKQogICAgICAgIHR6X3Jvdy5hZGRXaWRnZXQodHp"
    "fY29tYm8sIDEpCiAgICAgICAgdHpfaG9zdCA9IFFXaWRnZXQoKQogICAgICAgIHR6X2hvc3Quc2V0TG"
    "F5b3V0KHR6X3JvdykKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHR6X2hvc3QpCgogICAgZGVmIF9id"
    "WlsZF9pbnRlZ3JhdGlvbl9zZWN0aW9uKHNlbGYsIGxheW91dDogUVZCb3hMYXlvdXQpIC0+IE5vbmU6"
    "CiAgICAgICAgc2V0dGluZ3MgPSBDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KQogICAgICAgIGdvb2dsZV9"
    "zZWNvbmRzID0gaW50KHNldHRpbmdzLmdldCgiZ29vZ2xlX2luYm91bmRfaW50ZXJ2YWxfbXMiLCAzMD"
    "AwMCkpIC8vIDEwMDAKICAgICAgICBnb29nbGVfc2Vjb25kcyA9IG1heCg1LCBtaW4oNjAwLCBnb29nb"
    "GVfc2Vjb25kcykpCiAgICAgICAgZW1haWxfbWludXRlcyA9IG1heCgxLCBpbnQoc2V0dGluZ3MuZ2V0"
    "KCJlbWFpbF9yZWZyZXNoX2ludGVydmFsX21zIiwgMzAwMDAwKSkgLy8gNjAwMDApCgogICAgICAgIGd"
    "vb2dsZV9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgZ29vZ2xlX3Jvdy5hZGRXaWRnZXQoUUxhYm"
    "VsKCJHb29nbGUgcmVmcmVzaCBpbnRlcnZhbCAoc2Vjb25kcyk6IikpCiAgICAgICAgZ29vZ2xlX2Jve"
    "CA9IFFTcGluQm94KCkKICAgICAgICBnb29nbGVfYm94LnNldFJhbmdlKDUsIDYwMCkKICAgICAgICBn"
    "b29nbGVfYm94LnNldFZhbHVlKGdvb2dsZV9zZWNvbmRzKQogICAgICAgIGdvb2dsZV9ib3gudmFsdWV"
    "DaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fZGVjay5fc2V0X2dvb2dsZV9yZWZyZXNoX3NlY29uZHMpCiAgIC"
    "AgICAgZ29vZ2xlX3Jvdy5hZGRXaWRnZXQoZ29vZ2xlX2JveCwgMSkKICAgICAgICBnb29nbGVfaG9zd"
    "CA9IFFXaWRnZXQoKQogICAgICAgIGdvb2dsZV9ob3N0LnNldExheW91dChnb29nbGVfcm93KQogICAg"
    "ICAgIGxheW91dC5hZGRXaWRnZXQoZ29vZ2xlX2hvc3QpCgogICAgICAgIGVtYWlsX3JvdyA9IFFIQm9"
    "4TGF5b3V0KCkKICAgICAgICBlbWFpbF9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgiRW1haWwgcmVmcmVzaC"
    "BpbnRlcnZhbCAobWludXRlcyk6IikpCiAgICAgICAgZW1haWxfYm94ID0gUUNvbWJvQm94KCkKICAgI"
    "CAgICBlbWFpbF9ib3guc2V0RWRpdGFibGUoVHJ1ZSkKICAgICAgICBlbWFpbF9ib3guYWRkSXRlbXMo"
    "WyIxIiwgIjUiLCAiMTAiLCAiMTUiLCAiMzAiLCAiNjAiXSkKICAgICAgICBlbWFpbF9ib3guc2V0Q3V"
    "ycmVudFRleHQoc3RyKGVtYWlsX21pbnV0ZXMpKQogICAgICAgIGVtYWlsX2JveC5jdXJyZW50VGV4dE"
    "NoYW5nZWQuY29ubmVjdChzZWxmLl9kZWNrLl9zZXRfZW1haWxfcmVmcmVzaF9taW51dGVzX2Zyb21fd"
    "GV4dCkKICAgICAgICBlbWFpbF9yb3cuYWRkV2lkZ2V0KGVtYWlsX2JveCwgMSkKICAgICAgICBlbWFp"
    "bF9ob3N0ID0gUVdpZGdldCgpCiAgICAgICAgZW1haWxfaG9zdC5zZXRMYXlvdXQoZW1haWxfcm93KQo"
    "gICAgICAgIGxheW91dC5hZGRXaWRnZXQoZW1haWxfaG9zdCkKCiAgICAgICAgbm90ZSA9IFFMYWJlbC"
    "giRW1haWwgcG9sbGluZyBmb3VuZGF0aW9uIGlzIGNvbmZpZ3VyYXRpb24tb25seSB1bmxlc3MgYW4gZ"
    "W1haWwgYmFja2VuZCBpcyBlbmFibGVkLiIpCiAgICAgICAgbm90ZS5zZXRTdHlsZVNoZWV0KGYiY29s"
    "b3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V"
    "0KG5vdGUpCgogICAgZGVmIF9idWlsZF91aV9zZWN0aW9uKHNlbGYsIGxheW91dDogUVZCb3hMYXlvdX"
    "QpIC0+IE5vbmU6CiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChRTGFiZWwoIldpbmRvdyBTaGVsbCIpK"
    "QogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZGVjay5fZnNfYnRuKQogICAgICAgIGxheW91"
    "dC5hZGRXaWRnZXQoc2VsZi5fZGVjay5fYmxfYnRuKQoKCmNsYXNzIERpY2VHbHlwaChRV2lkZ2V0KTo"
    "KICAgICIiIlNpbXBsZSAyRCBzaWxob3VldHRlIHJlbmRlcmVyIGZvciBkaWUtdHlwZSByZWNvZ25pdG"
    "lvbi4iIiIKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBkaWVfdHlwZTogc3RyID0gImQyMCIsIHBhcmVud"
    "D1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kaWVf"
    "dHlwZSA9IGRpZV90eXBlCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSg3MCwgNzApCiAgICAgICA"
    "gc2VsZi5zZXRNYXhpbXVtU2l6ZSg5MCwgOTApCgogICAgZGVmIHNldF9kaWVfdHlwZShzZWxmLCBkaW"
    "VfdHlwZTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2RpZV90eXBlID0gZGllX3R5cGUKICAgI"
    "CAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpOgogICAgICAg"
    "IHBhaW50ZXIgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHBhaW50ZXIuc2V0UmVuZGVySGludChRUGF"
    "pbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICByZWN0ID0gc2VsZi5yZWN0KCkuYW"
    "RqdXN0ZWQoOCwgOCwgLTgsIC04KQoKICAgICAgICBkaWUgPSBzZWxmLl9kaWVfdHlwZQogICAgICAgI"
    "GxpbmUgPSBRQ29sb3IoQ19HT0xEKQogICAgICAgIGZpbGwgPSBRQ29sb3IoQ19CRzIpCiAgICAgICAg"
    "YWNjZW50ID0gUUNvbG9yKENfQ1JJTVNPTikKCiAgICAgICAgcGFpbnRlci5zZXRQZW4oUVBlbihsaW5"
    "lLCAyKSkKICAgICAgICBwYWludGVyLnNldEJydXNoKGZpbGwpCgogICAgICAgIHB0cyA9IFtdCiAgIC"
    "AgICAgaWYgZGllID09ICJkNCI6CiAgICAgICAgICAgIHB0cyA9IFsKICAgICAgICAgICAgICAgIFFQb"
    "2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC50b3AoKSksCiAgICAgICAgICAgICAgICBRUG9pbnQo"
    "cmVjdC5sZWZ0KCksIHJlY3QuYm90dG9tKCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3Qucml"
    "naHQoKSwgcmVjdC5ib3R0b20oKSksCiAgICAgICAgICAgIF0KICAgICAgICBlbGlmIGRpZSA9PSAiZD"
    "YiOgogICAgICAgICAgICBwYWludGVyLmRyYXdSb3VuZGVkUmVjdChyZWN0LCA0LCA0KQogICAgICAgI"
    "GVsaWYgZGllID09ICJkOCI6CiAgICAgICAgICAgIHB0cyA9IFsKICAgICAgICAgICAgICAgIFFQb2lu"
    "dChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC50b3AoKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmV"
    "jdC5sZWZ0KCksIHJlY3QuY2VudGVyKCkueSgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0Lm"
    "NlbnRlcigpLngoKSwgcmVjdC5ib3R0b20oKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5ya"
    "WdodCgpLCByZWN0LmNlbnRlcigpLnkoKSksCiAgICAgICAgICAgIF0KICAgICAgICBlbGlmIGRpZSBp"
    "biAoImQxMCIsICJkMTAwIik6CiAgICAgICAgICAgIHB0cyA9IFsKICAgICAgICAgICAgICAgIFFQb2l"
    "udChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC50b3AoKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocm"
    "VjdC5sZWZ0KCkgKyA4LCByZWN0LnRvcCgpICsgMTYpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY"
    "3QubGVmdCgpLCByZWN0LmJvdHRvbSgpIC0gMTIpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3Qu"
    "Y2VudGVyKCkueCgpLCByZWN0LmJvdHRvbSgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LnJ"
    "pZ2h0KCksIHJlY3QuYm90dG9tKCkgLSAxMiksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5yaW"
    "dodCgpIC0gOCwgcmVjdC50b3AoKSArIDE2KSwKICAgICAgICAgICAgXQogICAgICAgIGVsaWYgZGllI"
    "D09ICJkMTIiOgogICAgICAgICAgICBjeCA9IHJlY3QuY2VudGVyKCkueCgpOyBjeSA9IHJlY3QuY2Vu"
    "dGVyKCkueSgpCiAgICAgICAgICAgIHJ4ID0gcmVjdC53aWR0aCgpIC8gMjsgcnkgPSByZWN0LmhlaWd"
    "odCgpIC8gMgogICAgICAgICAgICBmb3IgaSBpbiByYW5nZSg1KToKICAgICAgICAgICAgICAgIGEgPS"
    "AobWF0aC5waSAqIDIgKiBpIC8gNSkgLSAobWF0aC5waSAvIDIpCiAgICAgICAgICAgICAgICBwdHMuY"
    "XBwZW5kKFFQb2ludChpbnQoY3ggKyByeCAqIG1hdGguY29zKGEpKSwgaW50KGN5ICsgcnkgKiBtYXRo"
    "LnNpbihhKSkpKQogICAgICAgIGVsc2U6ICAjIGQyMAogICAgICAgICAgICBwdHMgPSBbCiAgICAgICA"
    "gICAgICAgICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJlY3QudG9wKCkpLAogICAgICAgICAgIC"
    "AgICAgUVBvaW50KHJlY3QubGVmdCgpICsgMTAsIHJlY3QudG9wKCkgKyAxNCksCiAgICAgICAgICAgI"
    "CAgICBRUG9pbnQocmVjdC5sZWZ0KCksIHJlY3QuY2VudGVyKCkueSgpKSwKICAgICAgICAgICAgICAg"
    "IFFQb2ludChyZWN0LmxlZnQoKSArIDEwLCByZWN0LmJvdHRvbSgpIC0gMTQpLAogICAgICAgICAgICA"
    "gICAgUVBvaW50KHJlY3QuY2VudGVyKCkueCgpLCByZWN0LmJvdHRvbSgpKSwKICAgICAgICAgICAgIC"
    "AgIFFQb2ludChyZWN0LnJpZ2h0KCkgLSAxMCwgcmVjdC5ib3R0b20oKSAtIDE0KSwKICAgICAgICAgI"
    "CAgICAgIFFQb2ludChyZWN0LnJpZ2h0KCksIHJlY3QuY2VudGVyKCkueSgpKSwKICAgICAgICAgICAg"
    "ICAgIFFQb2ludChyZWN0LnJpZ2h0KCkgLSAxMCwgcmVjdC50b3AoKSArIDE0KSwKICAgICAgICAgICA"
    "gXQoKICAgICAgICBpZiBwdHM6CiAgICAgICAgICAgIHBhdGggPSBRUGFpbnRlclBhdGgoKQogICAgIC"
    "AgICAgICBwYXRoLm1vdmVUbyhwdHNbMF0pCiAgICAgICAgICAgIGZvciBwIGluIHB0c1sxOl06CiAgI"
    "CAgICAgICAgICAgICBwYXRoLmxpbmVUbyhwKQogICAgICAgICAgICBwYXRoLmNsb3NlU3VicGF0aCgp"
    "CiAgICAgICAgICAgIHBhaW50ZXIuZHJhd1BhdGgocGF0aCkKCiAgICAgICAgcGFpbnRlci5zZXRQZW4"
    "oUVBlbihhY2NlbnQsIDEpKQogICAgICAgIHR4dCA9ICIlIiBpZiBkaWUgPT0gImQxMDAiIGVsc2UgZG"
    "llLnJlcGxhY2UoImQiLCAiIikKICAgICAgICBwYWludGVyLnNldEZvbnQoUUZvbnQoREVDS19GT05UL"
    "CAxMiwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIHBhaW50ZXIuZHJhd1RleHQocmVjdCwgUXQu"
    "QWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlciwgdHh0KQoKCmNsYXNzIERpY2VUcmF5RGllKFFGcmFtZSk"
    "6CiAgICBzaW5nbGVDbGlja2VkID0gU2lnbmFsKHN0cikKICAgIGRvdWJsZUNsaWNrZWQgPSBTaWduYW"
    "woc3RyKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBkaWVfdHlwZTogc3RyLCBkaXNwbGF5X2xhYmVsO"
    "iBzdHIsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAg"
    "ICBzZWxmLmRpZV90eXBlID0gZGllX3R5cGUKICAgICAgICBzZWxmLmRpc3BsYXlfbGFiZWwgPSBkaXN"
    "wbGF5X2xhYmVsCiAgICAgICAgc2VsZi5fY2xpY2tfdGltZXIgPSBRVGltZXIoc2VsZikKICAgICAgIC"
    "BzZWxmLl9jbGlja190aW1lci5zZXRTaW5nbGVTaG90KFRydWUpCiAgICAgICAgc2VsZi5fY2xpY2tfd"
    "GltZXIuc2V0SW50ZXJ2YWwoMjIwKQogICAgICAgIHNlbGYuX2NsaWNrX3RpbWVyLnRpbWVvdXQuY29u"
    "bmVjdChzZWxmLl9lbWl0X3NpbmdsZSkKCiAgICAgICAgc2VsZi5zZXRPYmplY3ROYW1lKCJEaWNlVHJ"
    "heURpZSIpCiAgICAgICAgc2VsZi5zZXRDdXJzb3IoUXQuQ3Vyc29yU2hhcGUuUG9pbnRpbmdIYW5kQ3"
    "Vyc29yKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJRRnJhbWUjRGljZ"
    "VRyYXlEaWUge3sgYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVS"
    "fTsgYm9yZGVyLXJhZGl1czogOHB4OyB9fSIKICAgICAgICAgICAgZiJRRnJhbWUjRGljZVRyYXlEaWU"
    "6aG92ZXIge3sgYm9yZGVyOiAxcHggc29saWQge0NfR09MRH07IH19IgogICAgICAgICkKCiAgICAgIC"
    "AgbGF5ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXkuc2V0Q29udGVudHNNYXJnaW5zKDYsI"
    "DYsIDYsIDYpCiAgICAgICAgbGF5LnNldFNwYWNpbmcoMikKCiAgICAgICAgZ2x5cGhfZGllID0gImQx"
    "MDAiIGlmIGRpZV90eXBlID09ICJkJSIgZWxzZSBkaWVfdHlwZQogICAgICAgIHNlbGYuZ2x5cGggPSB"
    "EaWNlR2x5cGgoZ2x5cGhfZGllKQogICAgICAgIHNlbGYuZ2x5cGguc2V0Rml4ZWRTaXplKDU0LCA1NC"
    "kKICAgICAgICBzZWxmLmdseXBoLnNldEF0dHJpYnV0ZShRdC5XaWRnZXRBdHRyaWJ1dGUuV0FfVHJhb"
    "nNwYXJlbnRGb3JNb3VzZUV2ZW50cywgVHJ1ZSkKCiAgICAgICAgc2VsZi5sYmwgPSBRTGFiZWwoZGlz"
    "cGxheV9sYWJlbCkKICAgICAgICBzZWxmLmxibC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5"
    "BbGlnbkNlbnRlcikKICAgICAgICBzZWxmLmxibC5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX1RFWF"
    "R9OyBmb250LXdlaWdodDogYm9sZDsiKQogICAgICAgIHNlbGYubGJsLnNldEF0dHJpYnV0ZShRdC5Xa"
    "WRnZXRBdHRyaWJ1dGUuV0FfVHJhbnNwYXJlbnRGb3JNb3VzZUV2ZW50cywgVHJ1ZSkKCiAgICAgICAg"
    "bGF5LmFkZFdpZGdldChzZWxmLmdseXBoLCAwLCBRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQo"
    "gICAgICAgIGxheS5hZGRXaWRnZXQoc2VsZi5sYmwpCgogICAgZGVmIG1vdXNlUHJlc3NFdmVudChzZW"
    "xmLCBldmVudCk6CiAgICAgICAgaWYgZXZlbnQuYnV0dG9uKCkgPT0gUXQuTW91c2VCdXR0b24uTGVmd"
    "EJ1dHRvbjoKICAgICAgICAgICAgaWYgc2VsZi5fY2xpY2tfdGltZXIuaXNBY3RpdmUoKToKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2NsaWNrX3RpbWVyLnN0b3AoKQogICAgICAgICAgICAgICAgc2VsZi5kb3V"
    "ibGVDbGlja2VkLmVtaXQoc2VsZi5kaWVfdHlwZSkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgIC"
    "AgICAgIHNlbGYuX2NsaWNrX3RpbWVyLnN0YXJ0KCkKICAgICAgICAgICAgZXZlbnQuYWNjZXB0KCkKI"
    "CAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc3VwZXIoKS5tb3VzZVByZXNzRXZlbnQoZXZlbnQpCgog"
    "ICAgZGVmIF9lbWl0X3NpbmdsZShzZWxmKToKICAgICAgICBzZWxmLnNpbmdsZUNsaWNrZWQuZW1pdCh"
    "zZWxmLmRpZV90eXBlKQoKCmNsYXNzIERpY2VSb2xsZXJUYWIoUVdpZGdldCk6CiAgICAiIiJEZWNrLW"
    "5hdGl2ZSBEaWNlIFJvbGxlciBtb2R1bGUgdGFiIHdpdGggdHJheS9wb29sIHdvcmtmbG93IGFuZCBzd"
    "HJ1Y3R1cmVkIHJvbGwgZXZlbnRzLiIiIgoKICAgIFRSQVlfT1JERVIgPSBbImQ0IiwgImQ2IiwgImQ4"
    "IiwgImQxMCIsICJkMTIiLCAiZDIwIiwgImQlIl0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgZGlhZ25"
    "vc3RpY3NfbG9nZ2VyPU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQogICAgICAgIHNlbG"
    "YuX2xvZyA9IGRpYWdub3N0aWNzX2xvZ2dlciBvciAobGFtYmRhICpfYXJncywgKipfa3dhcmdzOiBOb"
    "25lKQoKICAgICAgICBzZWxmLnJvbGxfZXZlbnRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxm"
    "LnNhdmVkX3JvbGxzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLmNvbW1vbl9yb2xsczogZGl"
    "jdFtzdHIsIGRpY3RdID0ge30KICAgICAgICBzZWxmLmV2ZW50X2J5X2lkOiBkaWN0W3N0ciwgZGljdF"
    "0gPSB7fQogICAgICAgIHNlbGYuY3VycmVudF9wb29sOiBkaWN0W3N0ciwgaW50XSA9IHt9CiAgICAgI"
    "CAgc2VsZi5jdXJyZW50X3JvbGxfaWRzOiBsaXN0W3N0cl0gPSBbXQoKICAgICAgICBzZWxmLnJ1bGVf"
    "ZGVmaW5pdGlvbnM6IGRpY3Rbc3RyLCBkaWN0XSA9IHsKICAgICAgICAgICAgInJ1bGVfNGQ2X2Ryb3B"
    "fbG93ZXN0IjogewogICAgICAgICAgICAgICAgImlkIjogInJ1bGVfNGQ2X2Ryb3BfbG93ZXN0IiwKIC"
    "AgICAgICAgICAgICAgICJuYW1lIjogIkQmRCA1ZSBTdGF0IFJvbGwiLAogICAgICAgICAgICAgICAgI"
    "mRpY2VfY291bnQiOiA0LAogICAgICAgICAgICAgICAgImRpY2Vfc2lkZXMiOiA2LAogICAgICAgICAg"
    "ICAgICAgImRyb3BfbG93ZXN0X2NvdW50IjogMSwKICAgICAgICAgICAgICAgICJkcm9wX2hpZ2hlc3R"
    "fY291bnQiOiAwLAogICAgICAgICAgICAgICAgIm5vdGVzIjogIlJvbGwgNGQ2LCBkcm9wIGxvd2VzdC"
    "BvbmUuIgogICAgICAgICAgICB9LAogICAgICAgICAgICAicnVsZV8zZDZfc3RyYWlnaHQiOiB7CiAgI"
    "CAgICAgICAgICAgICAiaWQiOiAicnVsZV8zZDZfc3RyYWlnaHQiLAogICAgICAgICAgICAgICAgIm5h"
    "bWUiOiAiM2Q2IFN0cmFpZ2h0IiwKICAgICAgICAgICAgICAgICJkaWNlX2NvdW50IjogMywKICAgICA"
    "gICAgICAgICAgICJkaWNlX3NpZGVzIjogNiwKICAgICAgICAgICAgICAgICJkcm9wX2xvd2VzdF9jb3"
    "VudCI6IDAsCiAgICAgICAgICAgICAgICAiZHJvcF9oaWdoZXN0X2NvdW50IjogMCwKICAgICAgICAgI"
    "CAgICAgICJub3RlcyI6ICJDbGFzc2ljIDNkNiByb2xsLiIKICAgICAgICAgICAgfSwKICAgICAgICB9"
    "CgogICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3Bvb2xfZWRpdG9"
    "yKCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBkZWYgX2J1aWxkX3VpKH"
    "NlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vd"
    "C5zZXRDb250ZW50c01hcmdpbnMoOCwgOCwgOCwgOCkKICAgICAgICByb290LnNldFNwYWNpbmcoNikK"
    "CiAgICAgICAgdHJheV93cmFwID0gUUZyYW1lKCkKICAgICAgICB0cmF5X3dyYXAuc2V0U3R5bGVTaGV"
    "ldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IikKIC"
    "AgICAgICB0cmF5X2xheW91dCA9IFFWQm94TGF5b3V0KHRyYXlfd3JhcCkKICAgICAgICB0cmF5X2xhe"
    "W91dC5zZXRDb250ZW50c01hcmdpbnMoOCwgOCwgOCwgOCkKICAgICAgICB0cmF5X2xheW91dC5zZXRT"
    "cGFjaW5nKDYpCiAgICAgICAgdHJheV9sYXlvdXQuYWRkV2lkZ2V0KFFMYWJlbCgiRGljZSBUcmF5Iik"
    "pCgogICAgICAgIHRyYXlfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHRyYXlfcm93LnNldFNwYW"
    "NpbmcoNikKICAgICAgICBmb3IgZGllIGluIHNlbGYuVFJBWV9PUkRFUjoKICAgICAgICAgICAgYmxvY"
    "2sgPSBEaWNlVHJheURpZShkaWUsIGRpZSkKICAgICAgICAgICAgYmxvY2suc2luZ2xlQ2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX2FkZF9kaWVfdG9fcG9vbCkKICAgICAgICAgICAgYmxvY2suZG91YmxlQ2xpY2t"
    "lZC5jb25uZWN0KHNlbGYuX3F1aWNrX3JvbGxfc2luZ2xlX2RpZSkKICAgICAgICAgICAgdHJheV9yb3"
    "cuYWRkV2lkZ2V0KGJsb2NrLCAxKQogICAgICAgIHRyYXlfbGF5b3V0LmFkZExheW91dCh0cmF5X3Jvd"
    "ykKICAgICAgICByb290LmFkZFdpZGdldCh0cmF5X3dyYXApCgogICAgICAgIHBvb2xfd3JhcCA9IFFG"
    "cmFtZSgpCiAgICAgICAgcG9vbF93cmFwLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ"
    "9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyIpCiAgICAgICAgcHcgPSBRVkJveExheW91dC"
    "hwb29sX3dyYXApCiAgICAgICAgcHcuc2V0Q29udGVudHNNYXJnaW5zKDgsIDgsIDgsIDgpCiAgICAgI"
    "CAgcHcuc2V0U3BhY2luZyg2KQoKICAgICAgICBwdy5hZGRXaWRnZXQoUUxhYmVsKCJDdXJyZW50IFBv"
    "b2wiKSkKICAgICAgICBzZWxmLnBvb2xfZXhwcl9sYmwgPSBRTGFiZWwoIlBvb2w6IChlbXB0eSkiKQo"
    "gICAgICAgIHNlbGYucG9vbF9leHByX2xibC5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX0dPTER9Oy"
    "Bmb250LXdlaWdodDogYm9sZDsiKQogICAgICAgIHB3LmFkZFdpZGdldChzZWxmLnBvb2xfZXhwcl9sY"
    "mwpCgogICAgICAgIHNlbGYucG9vbF9lbnRyaWVzX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIHNl"
    "bGYucG9vbF9lbnRyaWVzX2xheW91dCA9IFFIQm94TGF5b3V0KHNlbGYucG9vbF9lbnRyaWVzX3dpZGd"
    "ldCkKICAgICAgICBzZWxmLnBvb2xfZW50cmllc19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsID"
    "AsIDAsIDApCiAgICAgICAgc2VsZi5wb29sX2VudHJpZXNfbGF5b3V0LnNldFNwYWNpbmcoNikKICAgI"
    "CAgICBwdy5hZGRXaWRnZXQoc2VsZi5wb29sX2VudHJpZXNfd2lkZ2V0KQoKICAgICAgICBtZXRhX3Jv"
    "dyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLmxhYmVsX2VkaXQgPSBRTGluZUVkaXQoKTsgc2V"
    "sZi5sYWJlbF9lZGl0LnNldFBsYWNlaG9sZGVyVGV4dCgiTGFiZWwgLyBwdXJwb3NlIikKICAgICAgIC"
    "BzZWxmLm1vZF9zcGluID0gUVNwaW5Cb3goKTsgc2VsZi5tb2Rfc3Bpbi5zZXRSYW5nZSgtOTk5LCA5O"
    "TkpOyBzZWxmLm1vZF9zcGluLnNldFZhbHVlKDApCiAgICAgICAgc2VsZi5ydWxlX2NvbWJvID0gUUNv"
    "bWJvQm94KCk7IHNlbGYucnVsZV9jb21iby5hZGRJdGVtKCJNYW51YWwgUm9sbCIsICIiKQogICAgICA"
    "gIGZvciByaWQsIG1ldGEgaW4gc2VsZi5ydWxlX2RlZmluaXRpb25zLml0ZW1zKCk6CiAgICAgICAgIC"
    "AgIHNlbGYucnVsZV9jb21iby5hZGRJdGVtKG1ldGEuZ2V0KCJuYW1lIiwgcmlkKSwgcmlkKQoKICAgI"
    "CAgICBmb3IgdGl0bGUsIHcgaW4gKCgiTGFiZWwiLCBzZWxmLmxhYmVsX2VkaXQpLCAoIk1vZGlmaWVy"
    "Iiwgc2VsZi5tb2Rfc3BpbiksICgiUnVsZSIsIHNlbGYucnVsZV9jb21ibykpOgogICAgICAgICAgICB"
    "jb2wgPSBRVkJveExheW91dCgpCiAgICAgICAgICAgIGxibCA9IFFMYWJlbCh0aXRsZSkKICAgICAgIC"
    "AgICAgbGJsLnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlwe"
    "DsiKQogICAgICAgICAgICBjb2wuYWRkV2lkZ2V0KGxibCkKICAgICAgICAgICAgY29sLmFkZFdpZGdl"
    "dCh3KQogICAgICAgICAgICBtZXRhX3Jvdy5hZGRMYXlvdXQoY29sLCAxKQogICAgICAgIHB3LmFkZEx"
    "heW91dChtZXRhX3JvdykKCiAgICAgICAgYWN0aW9ucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZW"
    "xmLnJvbGxfcG9vbF9idG4gPSBRUHVzaEJ1dHRvbigiUm9sbCBQb29sIikKICAgICAgICBzZWxmLnJlc"
    "2V0X3Bvb2xfYnRuID0gUVB1c2hCdXR0b24oIlJlc2V0IFBvb2wiKQogICAgICAgIHNlbGYuc2F2ZV9w"
    "b29sX2J0biA9IFFQdXNoQnV0dG9uKCJTYXZlIFBvb2wiKQogICAgICAgIGFjdGlvbnMuYWRkV2lkZ2V"
    "0KHNlbGYucm9sbF9wb29sX2J0bikKICAgICAgICBhY3Rpb25zLmFkZFdpZGdldChzZWxmLnJlc2V0X3"
    "Bvb2xfYnRuKQogICAgICAgIGFjdGlvbnMuYWRkV2lkZ2V0KHNlbGYuc2F2ZV9wb29sX2J0bikKICAgI"
    "CAgICBwdy5hZGRMYXlvdXQoYWN0aW9ucykKCiAgICAgICAgcm9vdC5hZGRXaWRnZXQocG9vbF93cmFw"
    "KQoKICAgICAgICByZXN1bHRfd3JhcCA9IFFGcmFtZSgpCiAgICAgICAgcmVzdWx0X3dyYXAuc2V0U3R"
    "5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn"
    "07IikKICAgICAgICBybCA9IFFWQm94TGF5b3V0KHJlc3VsdF93cmFwKQogICAgICAgIHJsLnNldENvb"
    "nRlbnRzTWFyZ2lucyg4LCA4LCA4LCA4KQogICAgICAgIHJsLmFkZFdpZGdldChRTGFiZWwoIkN1cnJl"
    "bnQgUmVzdWx0IikpCiAgICAgICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwgPSBRTGFiZWwoIk5vIHJ"
    "vbGwgeWV0LiIpCiAgICAgICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwuc2V0V29yZFdyYXAoVHJ1ZS"
    "kKICAgICAgICBybC5hZGRXaWRnZXQoc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwpCiAgICAgICAgcm9vd"
    "C5hZGRXaWRnZXQocmVzdWx0X3dyYXApCgogICAgICAgIG1pZCA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBoaXN0b3J5X3dyYXAgPSBRRnJhbWUoKQogICAgICAgIGhpc3Rvcnlfd3JhcC5zZXRTdHlsZVNoZWV"
    "0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsiKQogIC"
    "AgICAgIGh3ID0gUVZCb3hMYXlvdXQoaGlzdG9yeV93cmFwKQogICAgICAgIGh3LnNldENvbnRlbnRzT"
    "WFyZ2lucyg2LCA2LCA2LCA2KQoKICAgICAgICBzZWxmLmhpc3RvcnlfdGFicyA9IFFUYWJXaWRnZXQo"
    "KQogICAgICAgIHNlbGYuY3VycmVudF90YWJsZSA9IHNlbGYuX21ha2Vfcm9sbF90YWJsZSgpCiAgICA"
    "gICAgc2VsZi5oaXN0b3J5X3RhYmxlID0gc2VsZi5fbWFrZV9yb2xsX3RhYmxlKCkKICAgICAgICBzZW"
    "xmLmhpc3RvcnlfdGFicy5hZGRUYWIoc2VsZi5jdXJyZW50X3RhYmxlLCAiQ3VycmVudCBSb2xscyIpC"
    "iAgICAgICAgc2VsZi5oaXN0b3J5X3RhYnMuYWRkVGFiKHNlbGYuaGlzdG9yeV90YWJsZSwgIlJvbGwg"
    "SGlzdG9yeSIpCiAgICAgICAgaHcuYWRkV2lkZ2V0KHNlbGYuaGlzdG9yeV90YWJzLCAxKQoKICAgICA"
    "gICBoaXN0b3J5X2FjdGlvbnMgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5jbGVhcl9oaXN0b3"
    "J5X2J0biA9IFFQdXNoQnV0dG9uKCJDbGVhciBSb2xsIEhpc3RvcnkiKQogICAgICAgIGhpc3RvcnlfY"
    "WN0aW9ucy5hZGRXaWRnZXQoc2VsZi5jbGVhcl9oaXN0b3J5X2J0bikKICAgICAgICBoaXN0b3J5X2Fj"
    "dGlvbnMuYWRkU3RyZXRjaCgxKQogICAgICAgIGh3LmFkZExheW91dChoaXN0b3J5X2FjdGlvbnMpCgo"
    "gICAgICAgIHNlbGYuZ3JhbmRfdG90YWxfbGJsID0gUUxhYmVsKCJHcmFuZCBUb3RhbDogMCIpCiAgIC"
    "AgICAgc2VsZi5ncmFuZF90b3RhbF9sYmwuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19HT0xEfTsgZ"
    "m9udC1zaXplOiAxMnB4OyBmb250LXdlaWdodDogYm9sZDsiKQogICAgICAgIGh3LmFkZFdpZGdldChz"
    "ZWxmLmdyYW5kX3RvdGFsX2xibCkKCiAgICAgICAgc2F2ZWRfd3JhcCA9IFFGcmFtZSgpCiAgICAgICA"
    "gc2F2ZWRfd3JhcC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcH"
    "ggc29saWQge0NfQk9SREVSfTsiKQogICAgICAgIHN3ID0gUVZCb3hMYXlvdXQoc2F2ZWRfd3JhcCkKI"
    "CAgICAgICBzdy5zZXRDb250ZW50c01hcmdpbnMoNiwgNiwgNiwgNikKICAgICAgICBzdy5hZGRXaWRn"
    "ZXQoUUxhYmVsKCJTYXZlZCAvIENvbW1vbiBSb2xscyIpKQoKICAgICAgICBzdy5hZGRXaWRnZXQoUUx"
    "hYmVsKCJTYXZlZCIpKQogICAgICAgIHNlbGYuc2F2ZWRfbGlzdCA9IFFMaXN0V2lkZ2V0KCkKICAgIC"
    "AgICBzdy5hZGRXaWRnZXQoc2VsZi5zYXZlZF9saXN0LCAxKQogICAgICAgIHNhdmVkX2FjdGlvbnMgP"
    "SBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5ydW5fc2F2ZWRfYnRuID0gUVB1c2hCdXR0b24oIlJ1"
    "biIpCiAgICAgICAgc2VsZi5sb2FkX3NhdmVkX2J0biA9IFFQdXNoQnV0dG9uKCJMb2FkL0VkaXQiKQo"
    "gICAgICAgIHNlbGYuZGVsZXRlX3NhdmVkX2J0biA9IFFQdXNoQnV0dG9uKCJEZWxldGUiKQogICAgIC"
    "AgIHNhdmVkX2FjdGlvbnMuYWRkV2lkZ2V0KHNlbGYucnVuX3NhdmVkX2J0bikKICAgICAgICBzYXZlZ"
    "F9hY3Rpb25zLmFkZFdpZGdldChzZWxmLmxvYWRfc2F2ZWRfYnRuKQogICAgICAgIHNhdmVkX2FjdGlv"
    "bnMuYWRkV2lkZ2V0KHNlbGYuZGVsZXRlX3NhdmVkX2J0bikKICAgICAgICBzdy5hZGRMYXlvdXQoc2F"
    "2ZWRfYWN0aW9ucykKCiAgICAgICAgc3cuYWRkV2lkZ2V0KFFMYWJlbCgiQXV0by1EZXRlY3RlZCBDb2"
    "1tb24iKSkKICAgICAgICBzZWxmLmNvbW1vbl9saXN0ID0gUUxpc3RXaWRnZXQoKQogICAgICAgIHN3L"
    "mFkZFdpZGdldChzZWxmLmNvbW1vbl9saXN0LCAxKQogICAgICAgIGNvbW1vbl9hY3Rpb25zID0gUUhC"
    "b3hMYXlvdXQoKQogICAgICAgIHNlbGYucHJvbW90ZV9jb21tb25fYnRuID0gUVB1c2hCdXR0b24oIlB"
    "yb21vdGUgdG8gU2F2ZWQiKQogICAgICAgIHNlbGYuZGlzbWlzc19jb21tb25fYnRuID0gUVB1c2hCdX"
    "R0b24oIkRpc21pc3MiKQogICAgICAgIGNvbW1vbl9hY3Rpb25zLmFkZFdpZGdldChzZWxmLnByb21vd"
    "GVfY29tbW9uX2J0bikKICAgICAgICBjb21tb25fYWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5kaXNtaXNz"
    "X2NvbW1vbl9idG4pCiAgICAgICAgc3cuYWRkTGF5b3V0KGNvbW1vbl9hY3Rpb25zKQoKICAgICAgICB"
    "zZWxmLmNvbW1vbl9oaW50ID0gUUxhYmVsKCJDb21tb24gc2lnbmF0dXJlIHRyYWNraW5nIGFjdGl2ZS"
    "4iKQogICAgICAgIHNlbGYuY29tbW9uX2hpbnQuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19URVhUX"
    "0RJTX07IGZvbnQtc2l6ZTogOXB4OyIpCiAgICAgICAgc3cuYWRkV2lkZ2V0KHNlbGYuY29tbW9uX2hp"
    "bnQpCgogICAgICAgIG1pZC5hZGRXaWRnZXQoaGlzdG9yeV93cmFwLCAzKQogICAgICAgIG1pZC5hZGR"
    "XaWRnZXQoc2F2ZWRfd3JhcCwgMikKICAgICAgICByb290LmFkZExheW91dChtaWQsIDEpCgogICAgIC"
    "AgIHNlbGYucm9sbF9wb29sX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fcm9sbF9jdXJyZW50X3Bvb"
    "2wpCiAgICAgICAgc2VsZi5yZXNldF9wb29sX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fcmVzZXRf"
    "cG9vbCkKICAgICAgICBzZWxmLnNhdmVfcG9vbF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3NhdmV"
    "fcG9vbCkKICAgICAgICBzZWxmLmNsZWFyX2hpc3RvcnlfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl"
    "9jbGVhcl9oaXN0b3J5KQoKICAgICAgICBzZWxmLnNhdmVkX2xpc3QuaXRlbURvdWJsZUNsaWNrZWQuY"
    "29ubmVjdChsYW1iZGEgaXRlbTogc2VsZi5fcnVuX3NhdmVkX3JvbGwoaXRlbS5kYXRhKFF0Lkl0ZW1E"
    "YXRhUm9sZS5Vc2VyUm9sZSkpKQogICAgICAgIHNlbGYuY29tbW9uX2xpc3QuaXRlbURvdWJsZUNsaWN"
    "rZWQuY29ubmVjdChsYW1iZGEgaXRlbTogc2VsZi5fcnVuX3NhdmVkX3JvbGwoaXRlbS5kYXRhKFF0Lk"
    "l0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkpKQoKICAgICAgICBzZWxmLnJ1bl9zYXZlZF9idG4uY2xpY2tlZ"
    "C5jb25uZWN0KHNlbGYuX3J1bl9zZWxlY3RlZF9zYXZlZCkKICAgICAgICBzZWxmLmxvYWRfc2F2ZWRf"
    "YnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9sb2FkX3NlbGVjdGVkX3NhdmVkKQogICAgICAgIHNlbGY"
    "uZGVsZXRlX3NhdmVkX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZGVsZXRlX3NlbGVjdGVkX3Nhdm"
    "VkKQogICAgICAgIHNlbGYucHJvbW90ZV9jb21tb25fYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9wc"
    "m9tb3RlX3NlbGVjdGVkX2NvbW1vbikKICAgICAgICBzZWxmLmRpc21pc3NfY29tbW9uX2J0bi5jbGlj"
    "a2VkLmNvbm5lY3Qoc2VsZi5fZGlzbWlzc19zZWxlY3RlZF9jb21tb24pCgogICAgICAgIHNlbGYuY3V"
    "ycmVudF90YWJsZS5zZXRDb250ZXh0TWVudVBvbGljeShRdC5Db250ZXh0TWVudVBvbGljeS5DdXN0b2"
    "1Db250ZXh0TWVudSkKICAgICAgICBzZWxmLmhpc3RvcnlfdGFibGUuc2V0Q29udGV4dE1lbnVQb2xpY"
    "3koUXQuQ29udGV4dE1lbnVQb2xpY3kuQ3VzdG9tQ29udGV4dE1lbnUpCiAgICAgICAgc2VsZi5jdXJy"
    "ZW50X3RhYmxlLmN1c3RvbUNvbnRleHRNZW51UmVxdWVzdGVkLmNvbm5lY3QobGFtYmRhIHBvczogc2V"
    "sZi5fc2hvd19yb2xsX2NvbnRleHRfbWVudShzZWxmLmN1cnJlbnRfdGFibGUsIHBvcykpCiAgICAgIC"
    "Agc2VsZi5oaXN0b3J5X3RhYmxlLmN1c3RvbUNvbnRleHRNZW51UmVxdWVzdGVkLmNvbm5lY3QobGFtY"
    "mRhIHBvczogc2VsZi5fc2hvd19yb2xsX2NvbnRleHRfbWVudShzZWxmLmhpc3RvcnlfdGFibGUsIHBv"
    "cykpCgogICAgZGVmIF9tYWtlX3JvbGxfdGFibGUoc2VsZikgLT4gUVRhYmxlV2lkZ2V0OgogICAgICA"
    "gIHRibCA9IFFUYWJsZVdpZGdldCgwLCA2KQogICAgICAgIHRibC5zZXRIb3Jpem9udGFsSGVhZGVyTG"
    "FiZWxzKFsiVGltZXN0YW1wIiwgIkxhYmVsIiwgIkV4cHJlc3Npb24iLCAiUmF3IiwgIk1vZGlmaWVyI"
    "iwgIlRvdGFsIl0pCiAgICAgICAgdGJsLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXpl"
    "TW9kZShRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgdGJsLnZlcnRpY2FsSGV"
    "hZGVyKCkuc2V0VmlzaWJsZShGYWxzZSkKICAgICAgICB0Ymwuc2V0RWRpdFRyaWdnZXJzKFFBYnN0cm"
    "FjdEl0ZW1WaWV3LkVkaXRUcmlnZ2VyLk5vRWRpdFRyaWdnZXJzKQogICAgICAgIHRibC5zZXRTZWxlY"
    "3Rpb25CZWhhdmlvcihRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dz"
    "KQogICAgICAgIHRibC5zZXRTb3J0aW5nRW5hYmxlZChGYWxzZSkKICAgICAgICByZXR1cm4gdGJsCgo"
    "gICAgZGVmIF9zb3J0ZWRfcG9vbF9pdGVtcyhzZWxmKToKICAgICAgICByZXR1cm4gWyhkLCBzZWxmLm"
    "N1cnJlbnRfcG9vbC5nZXQoZCwgMCkpIGZvciBkIGluIHNlbGYuVFJBWV9PUkRFUiBpZiBzZWxmLmN1c"
    "nJlbnRfcG9vbC5nZXQoZCwgMCkgPiAwXQoKICAgIGRlZiBfcG9vbF9leHByZXNzaW9uKHNlbGYsIHBv"
    "b2w6IGRpY3Rbc3RyLCBpbnRdIHwgTm9uZSA9IE5vbmUpIC0+IHN0cjoKICAgICAgICBwID0gcG9vbCB"
    "pZiBwb29sIGlzIG5vdCBOb25lIGVsc2Ugc2VsZi5jdXJyZW50X3Bvb2wKICAgICAgICBwYXJ0cyA9IF"
    "tmIntxdHl9e2RpZX0iIGZvciBkaWUsIHF0eSBpbiBbKGQsIHAuZ2V0KGQsIDApKSBmb3IgZCBpbiBzZ"
    "WxmLlRSQVlfT1JERVJdIGlmIHF0eSA+IDBdCiAgICAgICAgcmV0dXJuICIgKyAiLmpvaW4ocGFydHMp"
    "IGlmIHBhcnRzIGVsc2UgIihlbXB0eSkiCgogICAgZGVmIF9ub3JtYWxpemVfcG9vbF9zaWduYXR1cmU"
    "oc2VsZiwgcG9vbDogZGljdFtzdHIsIGludF0sIG1vZGlmaWVyOiBpbnQsIHJ1bGVfaWQ6IHN0ciA9IC"
    "IiKSAtPiBzdHI6CiAgICAgICAgcGFydHMgPSBbZiJ7cG9vbC5nZXQoZCwgMCl9e2R9IiBmb3IgZCBpb"
    "iBzZWxmLlRSQVlfT1JERVIgaWYgcG9vbC5nZXQoZCwgMCkgPiAwXQogICAgICAgIGJhc2UgPSAiKyIu"
    "am9pbihwYXJ0cykgaWYgcGFydHMgZWxzZSAiMCIKICAgICAgICBzaWcgPSBmIntiYXNlfXttb2RpZml"
    "lcjorZH0iCiAgICAgICAgcmV0dXJuIGYie3NpZ31fe3J1bGVfaWR9IiBpZiBydWxlX2lkIGVsc2Ugc2"
    "lnCgogICAgZGVmIF9kaWNlX2xhYmVsKHNlbGYsIGRpZV90eXBlOiBzdHIpIC0+IHN0cjoKICAgICAgI"
    "CByZXR1cm4gImQlIiBpZiBkaWVfdHlwZSA9PSAiZCUiIGVsc2UgZGllX3R5cGUKCiAgICBkZWYgX3Jv"
    "bGxfc2luZ2xlX3ZhbHVlKHNlbGYsIGRpZV90eXBlOiBzdHIpOgogICAgICAgIGlmIGRpZV90eXBlID0"
    "9ICJkJSI6CiAgICAgICAgICAgIHRlbnMgPSByYW5kb20ucmFuZGludCgwLCA5KSAqIDEwCiAgICAgIC"
    "AgICAgIHJldHVybiB0ZW5zLCAoIjAwIiBpZiB0ZW5zID09IDAgZWxzZSBzdHIodGVucykpCiAgICAgI"
    "CAgc2lkZXMgPSBpbnQoZGllX3R5cGUucmVwbGFjZSgiZCIsICIiKSkKICAgICAgICB2YWwgPSByYW5k"
    "b20ucmFuZGludCgxLCBzaWRlcykKICAgICAgICByZXR1cm4gdmFsLCBzdHIodmFsKQoKICAgIGRlZiB"
    "fcm9sbF9wb29sX2RhdGEoc2VsZiwgcG9vbDogZGljdFtzdHIsIGludF0sIG1vZGlmaWVyOiBpbnQsIG"
    "xhYmVsOiBzdHIsIHJ1bGVfaWQ6IHN0ciA9ICIiKSAtPiBkaWN0OgogICAgICAgIGdyb3VwZWRfbnVtZ"
    "XJpYzogZGljdFtzdHIsIGxpc3RbaW50XV0gPSB7fQogICAgICAgIGdyb3VwZWRfZGlzcGxheTogZGlj"
    "dFtzdHIsIGxpc3Rbc3RyXV0gPSB7fQogICAgICAgIHN1YnRvdGFsID0gMAogICAgICAgIHVzZWRfcG9"
    "vbCA9IGRpY3QocG9vbCkKCiAgICAgICAgaWYgcnVsZV9pZCBhbmQgcnVsZV9pZCBpbiBzZWxmLnJ1bG"
    "VfZGVmaW5pdGlvbnMgYW5kIChub3QgcG9vbCBvciBsZW4oW2sgZm9yIGssIHYgaW4gcG9vbC5pdGVtc"
    "ygpIGlmIHYgPiAwXSkgPT0gMSk6CiAgICAgICAgICAgIHJ1bGUgPSBzZWxmLnJ1bGVfZGVmaW5pdGlv"
    "bnMuZ2V0KHJ1bGVfaWQsIHt9KQogICAgICAgICAgICBzaWRlcyA9IGludChydWxlLmdldCgiZGljZV9"
    "zaWRlcyIsIDYpKQogICAgICAgICAgICBjb3VudCA9IGludChydWxlLmdldCgiZGljZV9jb3VudCIsID"
    "EpKQogICAgICAgICAgICBkaWUgPSBmImR7c2lkZXN9IgogICAgICAgICAgICB1c2VkX3Bvb2wgPSB7Z"
    "GllOiBjb3VudH0KICAgICAgICAgICAgcmF3ID0gW3JhbmRvbS5yYW5kaW50KDEsIHNpZGVzKSBmb3Ig"
    "XyBpbiByYW5nZShjb3VudCldCiAgICAgICAgICAgIGRyb3BfbG93ID0gaW50KHJ1bGUuZ2V0KCJkcm9"
    "wX2xvd2VzdF9jb3VudCIsIDApIG9yIDApCiAgICAgICAgICAgIGRyb3BfaGlnaCA9IGludChydWxlLm"
    "dldCgiZHJvcF9oaWdoZXN0X2NvdW50IiwgMCkgb3IgMCkKICAgICAgICAgICAga2VwdCA9IGxpc3Qoc"
    "mF3KQogICAgICAgICAgICBpZiBkcm9wX2xvdyA+IDA6CiAgICAgICAgICAgICAgICBrZXB0ID0gc29y"
    "dGVkKGtlcHQpW2Ryb3BfbG93Ol0KICAgICAgICAgICAgaWYgZHJvcF9oaWdoID4gMDoKICAgICAgICA"
    "gICAgICAgIGtlcHQgPSBzb3J0ZWQoa2VwdClbOi1kcm9wX2hpZ2hdIGlmIGRyb3BfaGlnaCA8IGxlbi"
    "hrZXB0KSBlbHNlIFtdCiAgICAgICAgICAgIGdyb3VwZWRfbnVtZXJpY1tkaWVdID0gcmF3CiAgICAgI"
    "CAgICAgIGdyb3VwZWRfZGlzcGxheVtkaWVdID0gW3N0cih2KSBmb3IgdiBpbiByYXddCiAgICAgICAg"
    "ICAgIHN1YnRvdGFsID0gc3VtKGtlcHQpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgZm9yIGRpZSB"
    "pbiBzZWxmLlRSQVlfT1JERVI6CiAgICAgICAgICAgICAgICBxdHkgPSBpbnQocG9vbC5nZXQoZGllLC"
    "AwKSBvciAwKQogICAgICAgICAgICAgICAgaWYgcXR5IDw9IDA6CiAgICAgICAgICAgICAgICAgICAgY"
    "29udGludWUKICAgICAgICAgICAgICAgIGdyb3VwZWRfbnVtZXJpY1tkaWVdID0gW10KICAgICAgICAg"
    "ICAgICAgIGdyb3VwZWRfZGlzcGxheVtkaWVdID0gW10KICAgICAgICAgICAgICAgIGZvciBfIGluIHJ"
    "hbmdlKHF0eSk6CiAgICAgICAgICAgICAgICAgICAgbnVtLCBkaXNwID0gc2VsZi5fcm9sbF9zaW5nbG"
    "VfdmFsdWUoZGllKQogICAgICAgICAgICAgICAgICAgIGdyb3VwZWRfbnVtZXJpY1tkaWVdLmFwcGVuZ"
    "ChudW0pCiAgICAgICAgICAgICAgICAgICAgZ3JvdXBlZF9kaXNwbGF5W2RpZV0uYXBwZW5kKGRpc3Ap"
    "CiAgICAgICAgICAgICAgICAgICAgc3VidG90YWwgKz0gaW50KG51bSkKCiAgICAgICAgdG90YWwgPSB"
    "zdWJ0b3RhbCArIGludChtb2RpZmllcikKICAgICAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW"
    "1lKCIlSDolTTolUyIpCiAgICAgICAgZXhwciA9IHNlbGYuX3Bvb2xfZXhwcmVzc2lvbih1c2VkX3Bvb"
    "2wpCiAgICAgICAgaWYgcnVsZV9pZDoKICAgICAgICAgICAgcnVsZV9uYW1lID0gc2VsZi5ydWxlX2Rl"
    "ZmluaXRpb25zLmdldChydWxlX2lkLCB7fSkuZ2V0KCJuYW1lIiwgcnVsZV9pZCkKICAgICAgICAgICA"
    "gZXhwciA9IGYie2V4cHJ9ICh7cnVsZV9uYW1lfSkiCgogICAgICAgIGV2ZW50ID0gewogICAgICAgIC"
    "AgICAiaWQiOiBmInJvbGxfe3V1aWQudXVpZDQoKS5oZXhbOjEyXX0iLAogICAgICAgICAgICAidGltZ"
    "XN0YW1wIjogdHMsCiAgICAgICAgICAgICJsYWJlbCI6IGxhYmVsLAogICAgICAgICAgICAicG9vbCI6"
    "IHVzZWRfcG9vbCwKICAgICAgICAgICAgImdyb3VwZWRfcmF3IjogZ3JvdXBlZF9udW1lcmljLAogICA"
    "gICAgICAgICAiZ3JvdXBlZF9yYXdfZGlzcGxheSI6IGdyb3VwZWRfZGlzcGxheSwKICAgICAgICAgIC"
    "AgInN1YnRvdGFsIjogc3VidG90YWwsCiAgICAgICAgICAgICJtb2RpZmllciI6IGludChtb2RpZmllc"
    "iksCiAgICAgICAgICAgICJmaW5hbF90b3RhbCI6IGludCh0b3RhbCksCiAgICAgICAgICAgICJleHBy"
    "ZXNzaW9uIjogZXhwciwKICAgICAgICAgICAgInNvdXJjZSI6ICJkaWNlX3JvbGxlciIsCiAgICAgICA"
    "gICAgICJydWxlX2lkIjogcnVsZV9pZCBvciBOb25lLAogICAgICAgIH0KICAgICAgICByZXR1cm4gZX"
    "ZlbnQKCiAgICBkZWYgX2FkZF9kaWVfdG9fcG9vbChzZWxmLCBkaWVfdHlwZTogc3RyKSAtPiBOb25lO"
    "gogICAgICAgIHNlbGYuY3VycmVudF9wb29sW2RpZV90eXBlXSA9IGludChzZWxmLmN1cnJlbnRfcG9v"
    "bC5nZXQoZGllX3R5cGUsIDApKSArIDEKICAgICAgICBzZWxmLl9yZWZyZXNoX3Bvb2xfZWRpdG9yKCk"
    "KICAgICAgICBzZWxmLmN1cnJlbnRfcmVzdWx0X2xibC5zZXRUZXh0KGYiQ3VycmVudCBQb29sOiB7c2"
    "VsZi5fcG9vbF9leHByZXNzaW9uKCl9IikKCiAgICBkZWYgX2FkanVzdF9wb29sX2RpZShzZWxmLCBka"
    "WVfdHlwZTogc3RyLCBkZWx0YTogaW50KSAtPiBOb25lOgogICAgICAgIG5ld192YWwgPSBpbnQoc2Vs"
    "Zi5jdXJyZW50X3Bvb2wuZ2V0KGRpZV90eXBlLCAwKSkgKyBpbnQoZGVsdGEpCiAgICAgICAgaWYgbmV"
    "3X3ZhbCA8PSAwOgogICAgICAgICAgICBzZWxmLmN1cnJlbnRfcG9vbC5wb3AoZGllX3R5cGUsIE5vbm"
    "UpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5jdXJyZW50X3Bvb2xbZGllX3R5cGVdID0gb"
    "mV3X3ZhbAogICAgICAgIHNlbGYuX3JlZnJlc2hfcG9vbF9lZGl0b3IoKQoKICAgIGRlZiBfcmVmcmVz"
    "aF9wb29sX2VkaXRvcihzZWxmKSAtPiBOb25lOgogICAgICAgIHdoaWxlIHNlbGYucG9vbF9lbnRyaWV"
    "zX2xheW91dC5jb3VudCgpOgogICAgICAgICAgICBpdGVtID0gc2VsZi5wb29sX2VudHJpZXNfbGF5b3"
    "V0LnRha2VBdCgwKQogICAgICAgICAgICB3ID0gaXRlbS53aWRnZXQoKQogICAgICAgICAgICBpZiB3I"
    "GlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgdy5kZWxldGVMYXRlcigpCgogICAgICAgIGZvciBk"
    "aWUsIHF0eSBpbiBzZWxmLl9zb3J0ZWRfcG9vbF9pdGVtcygpOgogICAgICAgICAgICBib3ggPSBRRnJ"
    "hbWUoKQogICAgICAgICAgICBib3guc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHM307IG"
    "JvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDZweDsiKQogICAgICAgI"
    "CAgICBsYXkgPSBRSEJveExheW91dChib3gpCiAgICAgICAgICAgIGxheS5zZXRDb250ZW50c01hcmdp"
    "bnMoNiwgNCwgNiwgNCkKICAgICAgICAgICAgbGF5LnNldFNwYWNpbmcoNCkKICAgICAgICAgICAgbGJ"
    "sID0gUUxhYmVsKGYie2RpZX0geHtxdHl9IikKICAgICAgICAgICAgbWludXNfYnRuID0gUVB1c2hCdX"
    "R0b24oIuKIkiIpCiAgICAgICAgICAgIHBsdXNfYnRuID0gUVB1c2hCdXR0b24oIisiKQogICAgICAgI"
    "CAgICBtaW51c19idG4uc2V0Rml4ZWRXaWR0aCgyNCkKICAgICAgICAgICAgcGx1c19idG4uc2V0Rml4"
    "ZWRXaWR0aCgyNCkKICAgICAgICAgICAgbWludXNfYnRuLmNsaWNrZWQuY29ubmVjdChsYW1iZGEgXz1"
    "GYWxzZSwgZD1kaWU6IHNlbGYuX2FkanVzdF9wb29sX2RpZShkLCAtMSkpCiAgICAgICAgICAgIHBsdX"
    "NfYnRuLmNsaWNrZWQuY29ubmVjdChsYW1iZGEgXz1GYWxzZSwgZD1kaWU6IHNlbGYuX2FkanVzdF9wb"
    "29sX2RpZShkLCArMSkpCiAgICAgICAgICAgIGxheS5hZGRXaWRnZXQobGJsKQogICAgICAgICAgICBs"
    "YXkuYWRkV2lkZ2V0KG1pbnVzX2J0bikKICAgICAgICAgICAgbGF5LmFkZFdpZGdldChwbHVzX2J0bik"
    "KICAgICAgICAgICAgc2VsZi5wb29sX2VudHJpZXNfbGF5b3V0LmFkZFdpZGdldChib3gpCgogICAgIC"
    "AgIHNlbGYucG9vbF9lbnRyaWVzX2xheW91dC5hZGRTdHJldGNoKDEpCiAgICAgICAgc2VsZi5wb29sX"
    "2V4cHJfbGJsLnNldFRleHQoZiJQb29sOiB7c2VsZi5fcG9vbF9leHByZXNzaW9uKCl9IikKCiAgICBk"
    "ZWYgX3F1aWNrX3JvbGxfc2luZ2xlX2RpZShzZWxmLCBkaWVfdHlwZTogc3RyKSAtPiBOb25lOgogICA"
    "gICAgIGV2ZW50ID0gc2VsZi5fcm9sbF9wb29sX2RhdGEoe2RpZV90eXBlOiAxfSwgaW50KHNlbGYubW"
    "9kX3NwaW4udmFsdWUoKSksIHNlbGYubGFiZWxfZWRpdC50ZXh0KCkuc3RyaXAoKSwgc2VsZi5ydWxlX"
    "2NvbWJvLmN1cnJlbnREYXRhKCkgb3IgIiIpCiAgICAgICAgc2VsZi5fcmVjb3JkX3JvbGxfZXZlbnQo"
    "ZXZlbnQpCgogICAgZGVmIF9yb2xsX2N1cnJlbnRfcG9vbChzZWxmKSAtPiBOb25lOgogICAgICAgIHB"
    "vb2wgPSBkaWN0KHNlbGYuY3VycmVudF9wb29sKQogICAgICAgIHJ1bGVfaWQgPSBzZWxmLnJ1bGVfY2"
    "9tYm8uY3VycmVudERhdGEoKSBvciAiIgogICAgICAgIGlmIG5vdCBwb29sIGFuZCBub3QgcnVsZV9pZ"
    "DoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIkRpY2UgUm9sbGVyIiwg"
    "IkN1cnJlbnQgUG9vbCBpcyBlbXB0eS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBldmVudCA"
    "9IHNlbGYuX3JvbGxfcG9vbF9kYXRhKHBvb2wsIGludChzZWxmLm1vZF9zcGluLnZhbHVlKCkpLCBzZW"
    "xmLmxhYmVsX2VkaXQudGV4dCgpLnN0cmlwKCksIHJ1bGVfaWQpCiAgICAgICAgc2VsZi5fcmVjb3JkX"
    "3JvbGxfZXZlbnQoZXZlbnQpCgogICAgZGVmIF9yZWNvcmRfcm9sbF9ldmVudChzZWxmLCBldmVudDog"
    "ZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxmLnJvbGxfZXZlbnRzLmFwcGVuZChldmVudCkKICAgICA"
    "gICBzZWxmLmV2ZW50X2J5X2lkW2V2ZW50WyJpZCJdXSA9IGV2ZW50CiAgICAgICAgc2VsZi5jdXJyZW"
    "50X3JvbGxfaWRzID0gW2V2ZW50WyJpZCJdXQoKICAgICAgICBzZWxmLl9yZXBsYWNlX2N1cnJlbnRfc"
    "m93cyhbZXZlbnRdKQogICAgICAgIHNlbGYuX2FwcGVuZF9oaXN0b3J5X3JvdyhldmVudCkKICAgICAg"
    "ICBzZWxmLl91cGRhdGVfZ3JhbmRfdG90YWwoKQogICAgICAgIHNlbGYuX3VwZGF0ZV9yZXN1bHRfZGl"
    "zcGxheShldmVudCkKICAgICAgICBzZWxmLl90cmFja19jb21tb25fc2lnbmF0dXJlKGV2ZW50KQogIC"
    "AgICAgIHNlbGYuX3BsYXlfcm9sbF9zb3VuZCgpCgogICAgZGVmIF9yZXBsYWNlX2N1cnJlbnRfcm93c"
    "yhzZWxmLCBldmVudHM6IGxpc3RbZGljdF0pIC0+IE5vbmU6CiAgICAgICAgc2VsZi5jdXJyZW50X3Rh"
    "YmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGV2ZW50IGluIGV2ZW50czoKICAgICAgICAgICA"
    "gc2VsZi5fYXBwZW5kX3RhYmxlX3JvdyhzZWxmLmN1cnJlbnRfdGFibGUsIGV2ZW50KQoKICAgIGRlZi"
    "BfYXBwZW5kX2hpc3Rvcnlfcm93KHNlbGYsIGV2ZW50OiBkaWN0KSAtPiBOb25lOgogICAgICAgIHNlb"
    "GYuX2FwcGVuZF90YWJsZV9yb3coc2VsZi5oaXN0b3J5X3RhYmxlLCBldmVudCkKICAgICAgICBzZWxm"
    "Lmhpc3RvcnlfdGFibGUuc2Nyb2xsVG9Cb3R0b20oKQoKICAgIGRlZiBfZm9ybWF0X3JhdyhzZWxmLCB"
    "ldmVudDogZGljdCkgLT4gc3RyOgogICAgICAgIGdyb3VwZWQgPSBldmVudC5nZXQoImdyb3VwZWRfcm"
    "F3X2Rpc3BsYXkiLCB7fSkgb3Ige30KICAgICAgICBiaXRzID0gW10KICAgICAgICBmb3IgZGllIGluI"
    "HNlbGYuVFJBWV9PUkRFUjoKICAgICAgICAgICAgdmFscyA9IGdyb3VwZWQuZ2V0KGRpZSkKICAgICAg"
    "ICAgICAgaWYgdmFsczoKICAgICAgICAgICAgICAgIGJpdHMuYXBwZW5kKGYie2RpZX06IHsnLCcuam9"
    "pbihzdHIodikgZm9yIHYgaW4gdmFscyl9IikKICAgICAgICByZXR1cm4gIiB8ICIuam9pbihiaXRzKQ"
    "oKICAgIGRlZiBfYXBwZW5kX3RhYmxlX3JvdyhzZWxmLCB0YWJsZTogUVRhYmxlV2lkZ2V0LCBldmVud"
    "DogZGljdCkgLT4gTm9uZToKICAgICAgICByb3cgPSB0YWJsZS5yb3dDb3VudCgpCiAgICAgICAgdGFi"
    "bGUuaW5zZXJ0Um93KHJvdykKCiAgICAgICAgdHNfaXRlbSA9IFFUYWJsZVdpZGdldEl0ZW0oZXZlbnR"
    "bInRpbWVzdGFtcCJdKQogICAgICAgIHRzX2l0ZW0uc2V0RGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlcl"
    "JvbGUsIGV2ZW50WyJpZCJdKQogICAgICAgIHRhYmxlLnNldEl0ZW0ocm93LCAwLCB0c19pdGVtKQogI"
    "CAgICAgIHRhYmxlLnNldEl0ZW0ocm93LCAxLCBRVGFibGVXaWRnZXRJdGVtKGV2ZW50LmdldCgibGFi"
    "ZWwiLCAiIikpKQogICAgICAgIHRhYmxlLnNldEl0ZW0ocm93LCAyLCBRVGFibGVXaWRnZXRJdGVtKGV"
    "2ZW50LmdldCgiZXhwcmVzc2lvbiIsICIiKSkpCiAgICAgICAgdGFibGUuc2V0SXRlbShyb3csIDMsIF"
    "FUYWJsZVdpZGdldEl0ZW0oc2VsZi5fZm9ybWF0X3JhdyhldmVudCkpKQoKICAgICAgICBtb2Rfc3Bpb"
    "iA9IFFTcGluQm94KCkKICAgICAgICBtb2Rfc3Bpbi5zZXRSYW5nZSgtOTk5LCA5OTkpCiAgICAgICAg"
    "bW9kX3NwaW4uc2V0VmFsdWUoaW50KGV2ZW50LmdldCgibW9kaWZpZXIiLCAwKSkpCiAgICAgICAgbW9"
    "kX3NwaW4udmFsdWVDaGFuZ2VkLmNvbm5lY3QobGFtYmRhIHZhbCwgZWlkPWV2ZW50WyJpZCJdOiBzZW"
    "xmLl9vbl9tb2RpZmllcl9jaGFuZ2VkKGVpZCwgdmFsKSkKICAgICAgICB0YWJsZS5zZXRDZWxsV2lkZ"
    "2V0KHJvdywgNCwgbW9kX3NwaW4pCgogICAgICAgIHRhYmxlLnNldEl0ZW0ocm93LCA1LCBRVGFibGVX"
    "aWRnZXRJdGVtKHN0cihldmVudC5nZXQoImZpbmFsX3RvdGFsIiwgMCkpKSkKCiAgICBkZWYgX3N5bmN"
    "fcm93X2J5X2V2ZW50X2lkKHNlbGYsIHRhYmxlOiBRVGFibGVXaWRnZXQsIGV2ZW50X2lkOiBzdHIsIG"
    "V2ZW50OiBkaWN0KSAtPiBOb25lOgogICAgICAgIGZvciByb3cgaW4gcmFuZ2UodGFibGUucm93Q291b"
    "nQoKSk6CiAgICAgICAgICAgIGl0ID0gdGFibGUuaXRlbShyb3csIDApCiAgICAgICAgICAgIGlmIGl0"
    "IGFuZCBpdC5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkgPT0gZXZlbnRfaWQ6CiAgICAgICA"
    "gICAgICAgICB0YWJsZS5zZXRJdGVtKHJvdywgNSwgUVRhYmxlV2lkZ2V0SXRlbShzdHIoZXZlbnQuZ2"
    "V0KCJmaW5hbF90b3RhbCIsIDApKSkpCiAgICAgICAgICAgICAgICB0YWJsZS5zZXRJdGVtKHJvdywgM"
    "ywgUVRhYmxlV2lkZ2V0SXRlbShzZWxmLl9mb3JtYXRfcmF3KGV2ZW50KSkpCiAgICAgICAgICAgICAg"
    "ICBicmVhawoKICAgIGRlZiBfb25fbW9kaWZpZXJfY2hhbmdlZChzZWxmLCBldmVudF9pZDogc3RyLCB"
    "2YWx1ZTogaW50KSAtPiBOb25lOgogICAgICAgIGV2dCA9IHNlbGYuZXZlbnRfYnlfaWQuZ2V0KGV2ZW"
    "50X2lkKQogICAgICAgIGlmIG5vdCBldnQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGV2dFsib"
    "W9kaWZpZXIiXSA9IGludCh2YWx1ZSkKICAgICAgICBldnRbImZpbmFsX3RvdGFsIl0gPSBpbnQoZXZ0"
    "LmdldCgic3VidG90YWwiLCAwKSkgKyBpbnQodmFsdWUpCiAgICAgICAgc2VsZi5fc3luY19yb3dfYnl"
    "fZXZlbnRfaWQoc2VsZi5oaXN0b3J5X3RhYmxlLCBldmVudF9pZCwgZXZ0KQogICAgICAgIHNlbGYuX3"
    "N5bmNfcm93X2J5X2V2ZW50X2lkKHNlbGYuY3VycmVudF90YWJsZSwgZXZlbnRfaWQsIGV2dCkKICAgI"
    "CAgICBzZWxmLl91cGRhdGVfZ3JhbmRfdG90YWwoKQogICAgICAgIGlmIHNlbGYuY3VycmVudF9yb2xs"
    "X2lkcyBhbmQgc2VsZi5jdXJyZW50X3JvbGxfaWRzWzBdID09IGV2ZW50X2lkOgogICAgICAgICAgICB"
    "zZWxmLl91cGRhdGVfcmVzdWx0X2Rpc3BsYXkoZXZ0KQoKICAgIGRlZiBfdXBkYXRlX2dyYW5kX3RvdG"
    "FsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdG90YWwgPSBzdW0oaW50KGV2dC5nZXQoImZpbmFsX3Rvd"
    "GFsIiwgMCkpIGZvciBldnQgaW4gc2VsZi5yb2xsX2V2ZW50cykKICAgICAgICBzZWxmLmdyYW5kX3Rv"
    "dGFsX2xibC5zZXRUZXh0KGYiR3JhbmQgVG90YWw6IHt0b3RhbH0iKQoKICAgIGRlZiBfdXBkYXRlX3J"
    "lc3VsdF9kaXNwbGF5KHNlbGYsIGV2ZW50OiBkaWN0KSAtPiBOb25lOgogICAgICAgIGdyb3VwZWQgPS"
    "BldmVudC5nZXQoImdyb3VwZWRfcmF3X2Rpc3BsYXkiLCB7fSkgb3Ige30KICAgICAgICBsaW5lcyA9I"
    "FtdCiAgICAgICAgZm9yIGRpZSBpbiBzZWxmLlRSQVlfT1JERVI6CiAgICAgICAgICAgIHZhbHMgPSBn"
    "cm91cGVkLmdldChkaWUpCiAgICAgICAgICAgIGlmIHZhbHM6CiAgICAgICAgICAgICAgICBsaW5lcy5"
    "hcHBlbmQoZiJ7ZGllfSB4e2xlbih2YWxzKX0g4oaSIFt7JywnLmpvaW4oc3RyKHYpIGZvciB2IGluIH"
    "ZhbHMpfV0iKQogICAgICAgIHJ1bGVfaWQgPSBldmVudC5nZXQoInJ1bGVfaWQiKQogICAgICAgIGlmI"
    "HJ1bGVfaWQ6CiAgICAgICAgICAgIHJ1bGVfbmFtZSA9IHNlbGYucnVsZV9kZWZpbml0aW9ucy5nZXQo"
    "cnVsZV9pZCwge30pLmdldCgibmFtZSIsIHJ1bGVfaWQpCiAgICAgICAgICAgIGxpbmVzLmFwcGVuZCh"
    "mIlJ1bGU6IHtydWxlX25hbWV9IikKICAgICAgICBsaW5lcy5hcHBlbmQoZiJNb2RpZmllcjoge2ludC"
    "hldmVudC5nZXQoJ21vZGlmaWVyJywgMCkpOitkfSIpCiAgICAgICAgbGluZXMuYXBwZW5kKGYiVG90Y"
    "Ww6IHtldmVudC5nZXQoJ2ZpbmFsX3RvdGFsJywgMCl9IikKICAgICAgICBzZWxmLmN1cnJlbnRfcmVz"
    "dWx0X2xibC5zZXRUZXh0KCJcbiIuam9pbihsaW5lcykpCgoKICAgIGRlZiBfc2F2ZV9wb29sKHNlbGY"
    "pIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuY3VycmVudF9wb29sOgogICAgICAgICAgICBRTW"
    "Vzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiRGljZSBSb2xsZXIiLCAiQnVpbGQgYSBDdXJyZW50I"
    "FBvb2wgYmVmb3JlIHNhdmluZy4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBkZWZhdWx0X25h"
    "bWUgPSBzZWxmLmxhYmVsX2VkaXQudGV4dCgpLnN0cmlwKCkgb3Igc2VsZi5fcG9vbF9leHByZXNzaW9"
    "uKCkKICAgICAgICBuYW1lLCBvayA9IFFJbnB1dERpYWxvZy5nZXRUZXh0KHNlbGYsICJTYXZlIFBvb2"
    "wiLCAiU2F2ZWQgcm9sbCBuYW1lOiIsIHRleHQ9ZGVmYXVsdF9uYW1lKQogICAgICAgIGlmIG5vdCBva"
    "zoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcGF5bG9hZCA9IHsKICAgICAgICAgICAgImlkIjog"
    "ZiJzYXZlZF97dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICJuYW1lIjogbmFtZS5"
    "zdHJpcCgpIG9yIGRlZmF1bHRfbmFtZSwKICAgICAgICAgICAgInBvb2wiOiBkaWN0KHNlbGYuY3Vycm"
    "VudF9wb29sKSwKICAgICAgICAgICAgIm1vZGlmaWVyIjogaW50KHNlbGYubW9kX3NwaW4udmFsdWUoK"
    "SksCiAgICAgICAgICAgICJydWxlX2lkIjogc2VsZi5ydWxlX2NvbWJvLmN1cnJlbnREYXRhKCkgb3Ig"
    "Tm9uZSwKICAgICAgICAgICAgIm5vdGVzIjogIiIsCiAgICAgICAgICAgICJjYXRlZ29yeSI6ICJzYXZ"
    "lZCIsCiAgICAgICAgfQogICAgICAgIHNlbGYuc2F2ZWRfcm9sbHMuYXBwZW5kKHBheWxvYWQpCiAgIC"
    "AgICAgc2VsZi5fcmVmcmVzaF9zYXZlZF9saXN0cygpCgogICAgZGVmIF9yZWZyZXNoX3NhdmVkX2xpc"
    "3RzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zYXZlZF9saXN0LmNsZWFyKCkKICAgICAgICBm"
    "b3IgaXRlbSBpbiBzZWxmLnNhdmVkX3JvbGxzOgogICAgICAgICAgICBleHByID0gc2VsZi5fcG9vbF9"
    "leHByZXNzaW9uKGl0ZW0uZ2V0KCJwb29sIiwge30pKQogICAgICAgICAgICB0eHQgPSBmIntpdGVtLm"
    "dldCgnbmFtZScpfSDigJQge2V4cHJ9IHtpbnQoaXRlbS5nZXQoJ21vZGlmaWVyJywgMCkpOitkfSIKI"
    "CAgICAgICAgICAgbHcgPSBRTGlzdFdpZGdldEl0ZW0odHh0KQogICAgICAgICAgICBsdy5zZXREYXRh"
    "KFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgaXRlbSkKICAgICAgICAgICAgc2VsZi5zYXZlZF9saXN"
    "0LmFkZEl0ZW0obHcpCgogICAgICAgIHNlbGYuY29tbW9uX2xpc3QuY2xlYXIoKQogICAgICAgIHJhbm"
    "tlZCA9IHNvcnRlZChzZWxmLmNvbW1vbl9yb2xscy52YWx1ZXMoKSwga2V5PWxhbWJkYSB4OiB4Lmdld"
    "CgiY291bnQiLCAwKSwgcmV2ZXJzZT1UcnVlKQogICAgICAgIGZvciBpdGVtIGluIHJhbmtlZDoKICAg"
    "ICAgICAgICAgaWYgaW50KGl0ZW0uZ2V0KCJjb3VudCIsIDApKSA8IDI6CiAgICAgICAgICAgICAgICB"
    "jb250aW51ZQogICAgICAgICAgICBleHByID0gc2VsZi5fcG9vbF9leHByZXNzaW9uKGl0ZW0uZ2V0KC"
    "Jwb29sIiwge30pKQogICAgICAgICAgICB0eHQgPSBmIntleHByfSB7aW50KGl0ZW0uZ2V0KCdtb2RpZ"
    "mllcicsIDApKTorZH0gKHh7aXRlbS5nZXQoJ2NvdW50JywgMCl9KSIKICAgICAgICAgICAgbHcgPSBR"
    "TGlzdFdpZGdldEl0ZW0odHh0KQogICAgICAgICAgICBsdy5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5"
    "Vc2VyUm9sZSwgaXRlbSkKICAgICAgICAgICAgc2VsZi5jb21tb25fbGlzdC5hZGRJdGVtKGx3KQoKIC"
    "AgIGRlZiBfdHJhY2tfY29tbW9uX3NpZ25hdHVyZShzZWxmLCBldmVudDogZGljdCkgLT4gTm9uZToKI"
    "CAgICAgICBzaWcgPSBzZWxmLl9ub3JtYWxpemVfcG9vbF9zaWduYXR1cmUoZXZlbnQuZ2V0KCJwb29s"
    "Iiwge30pLCBpbnQoZXZlbnQuZ2V0KCJtb2RpZmllciIsIDApKSwgc3RyKGV2ZW50LmdldCgicnVsZV9"
    "pZCIpIG9yICIiKSkKICAgICAgICBpZiBzaWcgbm90IGluIHNlbGYuY29tbW9uX3JvbGxzOgogICAgIC"
    "AgICAgICBzZWxmLmNvbW1vbl9yb2xsc1tzaWddID0gewogICAgICAgICAgICAgICAgInNpZ25hdHVyZ"
    "SI6IHNpZywKICAgICAgICAgICAgICAgICJjb3VudCI6IDAsCiAgICAgICAgICAgICAgICAibmFtZSI6"
    "IGV2ZW50LmdldCgibGFiZWwiLCAiIikgb3Igc2lnLAogICAgICAgICAgICAgICAgInBvb2wiOiBkaWN"
    "0KGV2ZW50LmdldCgicG9vbCIsIHt9KSksCiAgICAgICAgICAgICAgICAibW9kaWZpZXIiOiBpbnQoZX"
    "ZlbnQuZ2V0KCJtb2RpZmllciIsIDApKSwKICAgICAgICAgICAgICAgICJydWxlX2lkIjogZXZlbnQuZ"
    "2V0KCJydWxlX2lkIiksCiAgICAgICAgICAgICAgICAibm90ZXMiOiAiIiwKICAgICAgICAgICAgICAg"
    "ICJjYXRlZ29yeSI6ICJjb21tb24iLAogICAgICAgICAgICB9CiAgICAgICAgc2VsZi5jb21tb25fcm9"
    "sbHNbc2lnXVsiY291bnQiXSA9IGludChzZWxmLmNvbW1vbl9yb2xsc1tzaWddLmdldCgiY291bnQiLC"
    "AwKSkgKyAxCiAgICAgICAgaWYgc2VsZi5jb21tb25fcm9sbHNbc2lnXVsiY291bnQiXSA+PSAzOgogI"
    "CAgICAgICAgICBzZWxmLmNvbW1vbl9oaW50LnNldFRleHQoZiJTdWdnZXN0aW9uOiBwcm9tb3RlIHtz"
    "ZWxmLl9wb29sX2V4cHJlc3Npb24oZXZlbnQuZ2V0KCdwb29sJywge30pKX0gdG8gU2F2ZWQuIikKICA"
    "gICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBkZWYgX3J1bl9zYXZlZF9yb2xsKH"
    "NlbGYsIHBheWxvYWQ6IGRpY3QgfCBOb25lKToKICAgICAgICBpZiBub3QgcGF5bG9hZDoKICAgICAgI"
    "CAgICAgcmV0dXJuCiAgICAgICAgZXZlbnQgPSBzZWxmLl9yb2xsX3Bvb2xfZGF0YSgKICAgICAgICAg"
    "ICAgZGljdChwYXlsb2FkLmdldCgicG9vbCIsIHt9KSksCiAgICAgICAgICAgIGludChwYXlsb2FkLmd"
    "ldCgibW9kaWZpZXIiLCAwKSksCiAgICAgICAgICAgIHN0cihwYXlsb2FkLmdldCgibmFtZSIsICIiKS"
    "kuc3RyaXAoKSwKICAgICAgICAgICAgc3RyKHBheWxvYWQuZ2V0KCJydWxlX2lkIikgb3IgIiIpLAogI"
    "CAgICAgICkKICAgICAgICBzZWxmLl9yZWNvcmRfcm9sbF9ldmVudChldmVudCkKCiAgICBkZWYgX2xv"
    "YWRfcGF5bG9hZF9pbnRvX3Bvb2woc2VsZiwgcGF5bG9hZDogZGljdCB8IE5vbmUpIC0+IE5vbmU6CiA"
    "gICAgICAgaWYgbm90IHBheWxvYWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuY3Vycm"
    "VudF9wb29sID0gZGljdChwYXlsb2FkLmdldCgicG9vbCIsIHt9KSkKICAgICAgICBzZWxmLm1vZF9zc"
    "GluLnNldFZhbHVlKGludChwYXlsb2FkLmdldCgibW9kaWZpZXIiLCAwKSkpCiAgICAgICAgc2VsZi5s"
    "YWJlbF9lZGl0LnNldFRleHQoc3RyKHBheWxvYWQuZ2V0KCJuYW1lIiwgIiIpKSkKICAgICAgICByaWQ"
    "gPSBwYXlsb2FkLmdldCgicnVsZV9pZCIpCiAgICAgICAgaWR4ID0gc2VsZi5ydWxlX2NvbWJvLmZpbm"
    "REYXRhKHJpZCBvciAiIikKICAgICAgICBpZiBpZHggPj0gMDoKICAgICAgICAgICAgc2VsZi5ydWxlX"
    "2NvbWJvLnNldEN1cnJlbnRJbmRleChpZHgpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9wb29sX2VkaXRv"
    "cigpCiAgICAgICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwuc2V0VGV4dChmIkN1cnJlbnQgUG9vbDo"
    "ge3NlbGYuX3Bvb2xfZXhwcmVzc2lvbigpfSIpCgogICAgZGVmIF9ydW5fc2VsZWN0ZWRfc2F2ZWQoc2"
    "VsZik6CiAgICAgICAgaXRlbSA9IHNlbGYuc2F2ZWRfbGlzdC5jdXJyZW50SXRlbSgpCiAgICAgICAgc"
    "2VsZi5fcnVuX3NhdmVkX3JvbGwoaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkgaWYg"
    "aXRlbSBlbHNlIE5vbmUpCgogICAgZGVmIF9sb2FkX3NlbGVjdGVkX3NhdmVkKHNlbGYpOgogICAgICA"
    "gIGl0ZW0gPSBzZWxmLnNhdmVkX2xpc3QuY3VycmVudEl0ZW0oKQogICAgICAgIHBheWxvYWQgPSBpdG"
    "VtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKSBpZiBpdGVtIGVsc2UgTm9uZQogICAgICAgI"
    "GlmIG5vdCBwYXlsb2FkOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9sb2FkX3BheWxv"
    "YWRfaW50b19wb29sKHBheWxvYWQpCgogICAgICAgIG5hbWUsIG9rID0gUUlucHV0RGlhbG9nLmdldFR"
    "leHQoc2VsZiwgIkVkaXQgU2F2ZWQgUm9sbCIsICJOYW1lOiIsIHRleHQ9c3RyKHBheWxvYWQuZ2V0KC"
    "JuYW1lIiwgIiIpKSkKICAgICAgICBpZiBub3Qgb2s6CiAgICAgICAgICAgIHJldHVybgogICAgICAgI"
    "HBheWxvYWRbIm5hbWUiXSA9IG5hbWUuc3RyaXAoKSBvciBwYXlsb2FkLmdldCgibmFtZSIsICIiKQog"
    "ICAgICAgIHBheWxvYWRbInBvb2wiXSA9IGRpY3Qoc2VsZi5jdXJyZW50X3Bvb2wpCiAgICAgICAgcGF"
    "5bG9hZFsibW9kaWZpZXIiXSA9IGludChzZWxmLm1vZF9zcGluLnZhbHVlKCkpCiAgICAgICAgcGF5bG"
    "9hZFsicnVsZV9pZCJdID0gc2VsZi5ydWxlX2NvbWJvLmN1cnJlbnREYXRhKCkgb3IgTm9uZQogICAgI"
    "CAgIG5vdGVzLCBva19ub3RlcyA9IFFJbnB1dERpYWxvZy5nZXRUZXh0KHNlbGYsICJFZGl0IFNhdmVk"
    "IFJvbGwiLCAiTm90ZXMgLyBjYXRlZ29yeToiLCB0ZXh0PXN0cihwYXlsb2FkLmdldCgibm90ZXMiLCA"
    "iIikpKQogICAgICAgIGlmIG9rX25vdGVzOgogICAgICAgICAgICBwYXlsb2FkWyJub3RlcyJdID0gbm"
    "90ZXMKICAgICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBkZWYgX2RlbGV0ZV9zZ"
    "WxlY3RlZF9zYXZlZChzZWxmKToKICAgICAgICByb3cgPSBzZWxmLnNhdmVkX2xpc3QuY3VycmVudFJv"
    "dygpCiAgICAgICAgaWYgcm93IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuc2F2ZWRfcm9sbHMpOgogICA"
    "gICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLnNhdmVkX3JvbGxzLnBvcChyb3cpCiAgICAgICAgc2"
    "VsZi5fcmVmcmVzaF9zYXZlZF9saXN0cygpCgogICAgZGVmIF9wcm9tb3RlX3NlbGVjdGVkX2NvbW1vb"
    "ihzZWxmKToKICAgICAgICBpdGVtID0gc2VsZi5jb21tb25fbGlzdC5jdXJyZW50SXRlbSgpCiAgICAg"
    "ICAgcGF5bG9hZCA9IGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpIGlmIGl0ZW0gZWx"
    "zZSBOb25lCiAgICAgICAgaWYgbm90IHBheWxvYWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIH"
    "Byb21vdGVkID0gewogICAgICAgICAgICAiaWQiOiBmInNhdmVkX3t1dWlkLnV1aWQ0KCkuaGV4WzoxM"
    "F19IiwKICAgICAgICAgICAgIm5hbWUiOiBwYXlsb2FkLmdldCgibmFtZSIpIG9yIHNlbGYuX3Bvb2xf"
    "ZXhwcmVzc2lvbihwYXlsb2FkLmdldCgicG9vbCIsIHt9KSksCiAgICAgICAgICAgICJwb29sIjogZGl"
    "jdChwYXlsb2FkLmdldCgicG9vbCIsIHt9KSksCiAgICAgICAgICAgICJtb2RpZmllciI6IGludChwYX"
    "lsb2FkLmdldCgibW9kaWZpZXIiLCAwKSksCiAgICAgICAgICAgICJydWxlX2lkIjogcGF5bG9hZC5nZ"
    "XQoInJ1bGVfaWQiKSwKICAgICAgICAgICAgIm5vdGVzIjogcGF5bG9hZC5nZXQoIm5vdGVzIiwgIiIp"
    "LAogICAgICAgICAgICAiY2F0ZWdvcnkiOiAic2F2ZWQiLAogICAgICAgIH0KICAgICAgICBzZWxmLnN"
    "hdmVkX3JvbGxzLmFwcGVuZChwcm9tb3RlZCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3"
    "RzKCkKCiAgICBkZWYgX2Rpc21pc3Nfc2VsZWN0ZWRfY29tbW9uKHNlbGYpOgogICAgICAgIGl0ZW0gP"
    "SBzZWxmLmNvbW1vbl9saXN0LmN1cnJlbnRJdGVtKCkKICAgICAgICBwYXlsb2FkID0gaXRlbS5kYXRh"
    "KFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkgaWYgaXRlbSBlbHNlIE5vbmUKICAgICAgICBpZiBub3Q"
    "gcGF5bG9hZDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2lnID0gcGF5bG9hZC5nZXQoInNpZ2"
    "5hdHVyZSIpCiAgICAgICAgaWYgc2lnIGluIHNlbGYuY29tbW9uX3JvbGxzOgogICAgICAgICAgICBzZ"
    "WxmLmNvbW1vbl9yb2xscy5wb3Aoc2lnLCBOb25lKQogICAgICAgIHNlbGYuX3JlZnJlc2hfc2F2ZWRf"
    "bGlzdHMoKQoKICAgIGRlZiBfcmVzZXRfcG9vbChzZWxmKToKICAgICAgICBzZWxmLmN1cnJlbnRfcG9"
    "vbCA9IHt9CiAgICAgICAgc2VsZi5tb2Rfc3Bpbi5zZXRWYWx1ZSgwKQogICAgICAgIHNlbGYubGFiZW"
    "xfZWRpdC5jbGVhcigpCiAgICAgICAgc2VsZi5ydWxlX2NvbWJvLnNldEN1cnJlbnRJbmRleCgwKQogI"
    "CAgICAgIHNlbGYuX3JlZnJlc2hfcG9vbF9lZGl0b3IoKQogICAgICAgIHNlbGYuY3VycmVudF9yZXN1"
    "bHRfbGJsLnNldFRleHQoIk5vIHJvbGwgeWV0LiIpCgogICAgZGVmIF9jbGVhcl9oaXN0b3J5KHNlbGY"
    "pOgogICAgICAgIHNlbGYucm9sbF9ldmVudHMuY2xlYXIoKQogICAgICAgIHNlbGYuZXZlbnRfYnlfaW"
    "QuY2xlYXIoKQogICAgICAgIHNlbGYuY3VycmVudF9yb2xsX2lkcyA9IFtdCiAgICAgICAgc2VsZi5oa"
    "XN0b3J5X3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgc2VsZi5jdXJyZW50X3RhYmxlLnNldFJv"
    "d0NvdW50KDApCiAgICAgICAgc2VsZi5fdXBkYXRlX2dyYW5kX3RvdGFsKCkKICAgICAgICBzZWxmLmN"
    "1cnJlbnRfcmVzdWx0X2xibC5zZXRUZXh0KCJObyByb2xsIHlldC4iKQoKICAgIGRlZiBfZXZlbnRfZn"
    "JvbV90YWJsZV9wb3NpdGlvbihzZWxmLCB0YWJsZTogUVRhYmxlV2lkZ2V0LCBwb3MpIC0+IGRpY3Qgf"
    "CBOb25lOgogICAgICAgIGl0ZW0gPSB0YWJsZS5pdGVtQXQocG9zKQogICAgICAgIGlmIG5vdCBpdGVt"
    "OgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIHJvdyA9IGl0ZW0ucm93KCkKICAgICAgICB"
    "0c19pdGVtID0gdGFibGUuaXRlbShyb3csIDApCiAgICAgICAgaWYgbm90IHRzX2l0ZW06CiAgICAgIC"
    "AgICAgIHJldHVybiBOb25lCiAgICAgICAgZWlkID0gdHNfaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZ"
    "S5Vc2VyUm9sZSkKICAgICAgICByZXR1cm4gc2VsZi5ldmVudF9ieV9pZC5nZXQoZWlkKQoKICAgIGRl"
    "ZiBfc2hvd19yb2xsX2NvbnRleHRfbWVudShzZWxmLCB0YWJsZTogUVRhYmxlV2lkZ2V0LCBwb3MpIC0"
    "+IE5vbmU6CiAgICAgICAgZXZ0ID0gc2VsZi5fZXZlbnRfZnJvbV90YWJsZV9wb3NpdGlvbih0YWJsZS"
    "wgcG9zKQogICAgICAgIGlmIG5vdCBldnQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGZyb20gU"
    "HlTaWRlNi5RdFdpZGdldHMgaW1wb3J0IFFNZW51CiAgICAgICAgbWVudSA9IFFNZW51KHNlbGYpCiAg"
    "ICAgICAgYWN0X3NlbmQgPSBtZW51LmFkZEFjdGlvbigiU2VuZCB0byBQcm9tcHQiKQogICAgICAgIGN"
    "ob3NlbiA9IG1lbnUuZXhlYyh0YWJsZS52aWV3cG9ydCgpLm1hcFRvR2xvYmFsKHBvcykpCiAgICAgIC"
    "AgaWYgY2hvc2VuID09IGFjdF9zZW5kOgogICAgICAgICAgICBzZWxmLl9zZW5kX2V2ZW50X3RvX3Byb"
    "21wdChldnQpCgogICAgZGVmIF9mb3JtYXRfZXZlbnRfZm9yX3Byb21wdChzZWxmLCBldmVudDogZGlj"
    "dCkgLT4gc3RyOgogICAgICAgIGxhYmVsID0gKGV2ZW50LmdldCgibGFiZWwiKSBvciAiUm9sbCIpLnN"
    "0cmlwKCkKICAgICAgICBncm91cGVkID0gZXZlbnQuZ2V0KCJncm91cGVkX3Jhd19kaXNwbGF5Iiwge3"
    "0pIG9yIHt9CiAgICAgICAgc2VnbWVudHMgPSBbXQogICAgICAgIGZvciBkaWUgaW4gc2VsZi5UUkFZX"
    "09SREVSOgogICAgICAgICAgICB2YWxzID0gZ3JvdXBlZC5nZXQoZGllKQogICAgICAgICAgICBpZiB2"
    "YWxzOgogICAgICAgICAgICAgICAgc2VnbWVudHMuYXBwZW5kKGYie2RpZX0gcm9sbGVkIHsnLCcuam9"
    "pbihzdHIodikgZm9yIHYgaW4gdmFscyl9IikKICAgICAgICBtb2QgPSBpbnQoZXZlbnQuZ2V0KCJtb2"
    "RpZmllciIsIDApKQogICAgICAgIHRvdGFsID0gaW50KGV2ZW50LmdldCgiZmluYWxfdG90YWwiLCAwK"
    "SkKICAgICAgICByZXR1cm4gZiJ7bGFiZWx9OiB7JzsgJy5qb2luKHNlZ21lbnRzKX07IG1vZGlmaWVy"
    "IHttb2Q6K2R9OyB0b3RhbCB7dG90YWx9IgoKICAgIGRlZiBfc2VuZF9ldmVudF90b19wcm9tcHQoc2V"
    "sZiwgZXZlbnQ6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgd2luZG93ID0gc2VsZi53aW5kb3coKQogIC"
    "AgICAgIGlmIG5vdCB3aW5kb3cgb3Igbm90IGhhc2F0dHIod2luZG93LCAiX2lucHV0X2ZpZWxkIik6C"
    "iAgICAgICAgICAgIHJldHVybgogICAgICAgIGxpbmUgPSBzZWxmLl9mb3JtYXRfZXZlbnRfZm9yX3By"
    "b21wdChldmVudCkKICAgICAgICB3aW5kb3cuX2lucHV0X2ZpZWxkLnNldFRleHQobGluZSkKICAgICA"
    "gICB3aW5kb3cuX2lucHV0X2ZpZWxkLnNldEZvY3VzKCkKCiAgICBkZWYgX3BsYXlfcm9sbF9zb3VuZC"
    "hzZWxmKToKICAgICAgICBpZiBub3QgV0lOU09VTkRfT0s6CiAgICAgICAgICAgIHJldHVybgogICAgI"
    "CAgIHRyeToKICAgICAgICAgICAgd2luc291bmQuQmVlcCg4NDAsIDMwKQogICAgICAgICAgICB3aW5z"
    "b3VuZC5CZWVwKDYyMCwgMzUpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGF"
    "zcwoKCgpjbGFzcyBNYWdpYzhCYWxsVGFiKFFXaWRnZXQpOgogICAgIiIiTWFnaWMgOC1CYWxsIG1vZH"
    "VsZSB3aXRoIGNpcmN1bGFyIG9yYiBkaXNwbGF5IGFuZCBwdWxzaW5nIGFuc3dlciB0ZXh0LiIiIgoKI"
    "CAgIEFOU1dFUlMgPSBbCiAgICAgICAgIkl0IGlzIGNlcnRhaW4uIiwKICAgICAgICAiSXQgaXMgZGVj"
    "aWRlZGx5IHNvLiIsCiAgICAgICAgIldpdGhvdXQgYSBkb3VidC4iLAogICAgICAgICJZZXMgZGVmaW5"
    "pdGVseS4iLAogICAgICAgICJZb3UgbWF5IHJlbHkgb24gaXQuIiwKICAgICAgICAiQXMgSSBzZWUgaX"
    "QsIHllcy4iLAogICAgICAgICJNb3N0IGxpa2VseS4iLAogICAgICAgICJPdXRsb29rIGdvb2QuIiwKI"
    "CAgICAgICAiWWVzLiIsCiAgICAgICAgIlNpZ25zIHBvaW50IHRvIHllcy4iLAogICAgICAgICJSZXBs"
    "eSBoYXp5LCB0cnkgYWdhaW4uIiwKICAgICAgICAiQXNrIGFnYWluIGxhdGVyLiIsCiAgICAgICAgIkJ"
    "ldHRlciBub3QgdGVsbCB5b3Ugbm93LiIsCiAgICAgICAgIkNhbm5vdCBwcmVkaWN0IG5vdy4iLAogIC"
    "AgICAgICJDb25jZW50cmF0ZSBhbmQgYXNrIGFnYWluLiIsCiAgICAgICAgIkRvbid0IGNvdW50IG9uI"
    "Gl0LiIsCiAgICAgICAgIk15IHJlcGx5IGlzIG5vLiIsCiAgICAgICAgIk15IHNvdXJjZXMgc2F5IG5v"
    "LiIsCiAgICAgICAgIk91dGxvb2sgbm90IHNvIGdvb2QuIiwKICAgICAgICAiVmVyeSBkb3VidGZ1bC4"
    "iLAogICAgXQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBvbl90aHJvdz1Ob25lLCBkaWFnbm9zdGljc1"
    "9sb2dnZXI9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fb25fd"
    "Ghyb3cgPSBvbl90aHJvdwogICAgICAgIHNlbGYuX2xvZyA9IGRpYWdub3N0aWNzX2xvZ2dlciBvciAo"
    "bGFtYmRhICpfYXJncywgKipfa3dhcmdzOiBOb25lKQogICAgICAgIHNlbGYuX2N1cnJlbnRfYW5zd2V"
    "yID0gIiIKCiAgICAgICAgc2VsZi5fY2xlYXJfdGltZXIgPSBRVGltZXIoc2VsZikKICAgICAgICBzZW"
    "xmLl9jbGVhcl90aW1lci5zZXRTaW5nbGVTaG90KFRydWUpCiAgICAgICAgc2VsZi5fY2xlYXJfdGltZ"
    "XIudGltZW91dC5jb25uZWN0KHNlbGYuX2ZhZGVfb3V0X2Fuc3dlcikKCiAgICAgICAgc2VsZi5fYnVp"
    "bGRfdWkoKQogICAgICAgIHNlbGYuX2J1aWxkX2FuaW1hdGlvbnMoKQogICAgICAgIHNlbGYuX3NldF9"
    "pZGxlX3Zpc3VhbCgpCgogICAgZGVmIF9idWlsZF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3"
    "QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDE2LCAxN"
    "iwgMTYsIDE2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZygxNCkKICAgICAgICByb290LmFkZFN0cmV0"
    "Y2goMSkKCiAgICAgICAgc2VsZi5fb3JiX2ZyYW1lID0gUUZyYW1lKCkKICAgICAgICBzZWxmLl9vcmJ"
    "fZnJhbWUuc2V0Rml4ZWRTaXplKDIyOCwgMjI4KQogICAgICAgIHNlbGYuX29yYl9mcmFtZS5zZXRTdH"
    "lsZVNoZWV0KAogICAgICAgICAgICAiUUZyYW1lIHsiCiAgICAgICAgICAgICJiYWNrZ3JvdW5kLWNvb"
    "G9yOiAjMDQwNDA2OyIKICAgICAgICAgICAgImJvcmRlcjogMXB4IHNvbGlkIHJnYmEoMjM0LCAyMzcs"
    "IDI1NSwgMC42Mik7IgogICAgICAgICAgICAiYm9yZGVyLXJhZGl1czogMTE0cHg7IgogICAgICAgICA"
    "gICAifSIKICAgICAgICApCgogICAgICAgIG9yYl9sYXlvdXQgPSBRVkJveExheW91dChzZWxmLl9vcm"
    "JfZnJhbWUpCiAgICAgICAgb3JiX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMjAsIDIwLCAyMCwgM"
    "jApCiAgICAgICAgb3JiX2xheW91dC5zZXRTcGFjaW5nKDApCgogICAgICAgIHNlbGYuX29yYl9pbm5l"
    "ciA9IFFGcmFtZSgpCiAgICAgICAgc2VsZi5fb3JiX2lubmVyLnNldFN0eWxlU2hlZXQoCiAgICAgICA"
    "gICAgICJRRnJhbWUgeyIKICAgICAgICAgICAgImJhY2tncm91bmQtY29sb3I6ICMwNzA3MGE7IgogIC"
    "AgICAgICAgICAiYm9yZGVyOiAxcHggc29saWQgcmdiYSgyNTUsIDI1NSwgMjU1LCAwLjEyKTsiCiAgI"
    "CAgICAgICAgICJib3JkZXItcmFkaXVzOiA4NHB4OyIKICAgICAgICAgICAgIn0iCiAgICAgICAgKQog"
    "ICAgICAgIHNlbGYuX29yYl9pbm5lci5zZXRNaW5pbXVtU2l6ZSgxNjgsIDE2OCkKICAgICAgICBzZWx"
    "mLl9vcmJfaW5uZXIuc2V0TWF4aW11bVNpemUoMTY4LCAxNjgpCgogICAgICAgIGlubmVyX2xheW91dC"
    "A9IFFWQm94TGF5b3V0KHNlbGYuX29yYl9pbm5lcikKICAgICAgICBpbm5lcl9sYXlvdXQuc2V0Q29ud"
    "GVudHNNYXJnaW5zKDE2LCAxNiwgMTYsIDE2KQogICAgICAgIGlubmVyX2xheW91dC5zZXRTcGFjaW5n"
    "KDApCgogICAgICAgIHNlbGYuX2VpZ2h0X2xibCA9IFFMYWJlbCgiOCIpCiAgICAgICAgc2VsZi5fZWl"
    "naHRfbGJsLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIH"
    "NlbGYuX2VpZ2h0X2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAiY29sb3I6IHJnYmEoMjU1L"
    "CAyNTUsIDI1NSwgMC45NSk7ICIKICAgICAgICAgICAgImZvbnQtc2l6ZTogODBweDsgZm9udC13ZWln"
    "aHQ6IDcwMDsgIgogICAgICAgICAgICAiZm9udC1mYW1pbHk6IEdlb3JnaWEsIHNlcmlmOyBib3JkZXI"
    "6IG5vbmU7IgogICAgICAgICkKCiAgICAgICAgc2VsZi5hbnN3ZXJfbGJsID0gUUxhYmVsKCIiKQogIC"
    "AgICAgIHNlbGYuYW5zd2VyX2xibC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlb"
    "nRlcikKICAgICAgICBzZWxmLmFuc3dlcl9sYmwuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBzZWxm"
    "LmFuc3dlcl9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZ"
    "vbnQtc2l6ZTogMTZweDsgZm9udC1zdHlsZTogaXRhbGljOyAiCiAgICAgICAgICAgICJmb250LXdlaW"
    "dodDogNjAwOyBib3JkZXI6IG5vbmU7IHBhZGRpbmc6IDJweDsiCiAgICAgICAgKQoKICAgICAgICBpb"
    "m5lcl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2VpZ2h0X2xibCwgMSkKICAgICAgICBpbm5lcl9sYXlv"
    "dXQuYWRkV2lkZ2V0KHNlbGYuYW5zd2VyX2xibCwgMSkKICAgICAgICBvcmJfbGF5b3V0LmFkZFdpZGd"
    "ldChzZWxmLl9vcmJfaW5uZXIsIDAsIFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCgogICAgIC"
    "AgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX29yYl9mcmFtZSwgMCwgUXQuQWxpZ25tZW50RmxhZy5BbGlnb"
    "khDZW50ZXIpCgogICAgICAgIHNlbGYudGhyb3dfYnRuID0gUVB1c2hCdXR0b24oIlRocm93IHRoZSA4"
    "LUJhbGwiKQogICAgICAgIHNlbGYudGhyb3dfYnRuLnNldEZpeGVkSGVpZ2h0KDM4KQogICAgICAgIHN"
    "lbGYudGhyb3dfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90aHJvd19iYWxsKQogICAgICAgIHJvb3"
    "QuYWRkV2lkZ2V0KHNlbGYudGhyb3dfYnRuLCAwLCBRdC5BbGlnbm1lbnRGbGFnLkFsaWduSENlbnRlc"
    "ikKICAgICAgICByb290LmFkZFN0cmV0Y2goMSkKCiAgICBkZWYgX2J1aWxkX2FuaW1hdGlvbnMoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hbnN3ZXJfb3BhY2l0eSA9IFFHcmFwaGljc09wYWNpdHl"
    "FZmZlY3Qoc2VsZi5hbnN3ZXJfbGJsKQogICAgICAgIHNlbGYuYW5zd2VyX2xibC5zZXRHcmFwaGljc0"
    "VmZmVjdChzZWxmLl9hbnN3ZXJfb3BhY2l0eSkKICAgICAgICBzZWxmLl9hbnN3ZXJfb3BhY2l0eS5zZ"
    "XRPcGFjaXR5KDAuMCkKCiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbSA9IFFQcm9wZXJ0eUFuaW1hdGlv"
    "bihzZWxmLl9hbnN3ZXJfb3BhY2l0eSwgYiJvcGFjaXR5Iiwgc2VsZikKICAgICAgICBzZWxmLl9wdWx"
    "zZV9hbmltLnNldER1cmF0aW9uKDc2MCkKICAgICAgICBzZWxmLl9wdWxzZV9hbmltLnNldFN0YXJ0Vm"
    "FsdWUoMC4zNSkKICAgICAgICBzZWxmLl9wdWxzZV9hbmltLnNldEVuZFZhbHVlKDEuMCkKICAgICAgI"
    "CBzZWxmLl9wdWxzZV9hbmltLnNldEVhc2luZ0N1cnZlKFFFYXNpbmdDdXJ2ZS5UeXBlLkluT3V0U2lu"
    "ZSkKICAgICAgICBzZWxmLl9wdWxzZV9hbmltLnNldExvb3BDb3VudCgtMSkKCiAgICAgICAgc2VsZi5"
    "fZmFkZV9vdXQgPSBRUHJvcGVydHlBbmltYXRpb24oc2VsZi5fYW5zd2VyX29wYWNpdHksIGIib3BhY2"
    "l0eSIsIHNlbGYpCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc2V0RHVyYXRpb24oNTYwKQogICAgICAgI"
    "HNlbGYuX2ZhZGVfb3V0LnNldFN0YXJ0VmFsdWUoMS4wKQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LnNl"
    "dEVuZFZhbHVlKDAuMCkKICAgICAgICBzZWxmLl9mYWRlX291dC5zZXRFYXNpbmdDdXJ2ZShRRWFzaW5"
    "nQ3VydmUuVHlwZS5Jbk91dFF1YWQpCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuZmluaXNoZWQuY29ubm"
    "VjdChzZWxmLl9jbGVhcl90b19pZGxlKQoKICAgIGRlZiBfc2V0X2lkbGVfdmlzdWFsKHNlbGYpIC0+I"
    "E5vbmU6CiAgICAgICAgc2VsZi5fY3VycmVudF9hbnN3ZXIgPSAiIgogICAgICAgIHNlbGYuX2VpZ2h0"
    "X2xibC5zaG93KCkKICAgICAgICBzZWxmLmFuc3dlcl9sYmwuY2xlYXIoKQogICAgICAgIHNlbGYuYW5"
    "zd2VyX2xibC5oaWRlKCkKICAgICAgICBzZWxmLl9hbnN3ZXJfb3BhY2l0eS5zZXRPcGFjaXR5KDAuMC"
    "kKCiAgICBkZWYgX3Rocm93X2JhbGwoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9jbGVhcl90a"
    "W1lci5zdG9wKCkKICAgICAgICBzZWxmLl9wdWxzZV9hbmltLnN0b3AoKQogICAgICAgIHNlbGYuX2Zh"
    "ZGVfb3V0LnN0b3AoKQoKICAgICAgICBhbnN3ZXIgPSByYW5kb20uY2hvaWNlKHNlbGYuQU5TV0VSUyk"
    "KICAgICAgICBzZWxmLl9jdXJyZW50X2Fuc3dlciA9IGFuc3dlcgoKICAgICAgICBzZWxmLl9laWdodF"
    "9sYmwuaGlkZSgpCiAgICAgICAgc2VsZi5hbnN3ZXJfbGJsLnNldFRleHQoYW5zd2VyKQogICAgICAgI"
    "HNlbGYuYW5zd2VyX2xibC5zaG93KCkKICAgICAgICBzZWxmLl9hbnN3ZXJfb3BhY2l0eS5zZXRPcGFj"
    "aXR5KDAuMCkKICAgICAgICBzZWxmLl9wdWxzZV9hbmltLnN0YXJ0KCkKICAgICAgICBzZWxmLl9jbGV"
    "hcl90aW1lci5zdGFydCg2MDAwMCkKICAgICAgICBzZWxmLl9sb2coZiJbOEJBTExdIFRocm93IHJlc3"
    "VsdDoge2Fuc3dlcn0iLCAiSU5GTyIpCgogICAgICAgIGlmIGNhbGxhYmxlKHNlbGYuX29uX3Rocm93K"
    "ToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fb25fdGhyb3coYW5zd2VyKQog"
    "ICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fbG9"
    "nKGYiWzhCQUxMXVtXQVJOXSBJbnRlcm5hbCBwcm9tcHQgZGlzcGF0Y2ggZmFpbGVkOiB7ZXh9IiwgIl"
    "dBUk4iKQoKICAgIGRlZiBfZmFkZV9vdXRfYW5zd2VyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZ"
    "i5fY2xlYXJfdGltZXIuc3RvcCgpCiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbS5zdG9wKCkKICAgICAg"
    "ICBzZWxmLl9mYWRlX291dC5zdG9wKCkKICAgICAgICBzZWxmLl9mYWRlX291dC5zZXRTdGFydFZhbHV"
    "lKGZsb2F0KHNlbGYuX2Fuc3dlcl9vcGFjaXR5Lm9wYWNpdHkoKSkpCiAgICAgICAgc2VsZi5fZmFkZV"
    "9vdXQuc2V0RW5kVmFsdWUoMC4wKQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LnN0YXJ0KCkKCiAgICBkZ"
    "WYgX2NsZWFyX3RvX2lkbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9mYWRlX291dC5zdG9w"
    "KCkKICAgICAgICBzZWxmLl9zZXRfaWRsZV92aXN1YWwoKQoKIyDilIDilIAgTUFJTiBXSU5ET1cg4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACmNsYXNzIExvY2tBd2FyZVRhYkJhcihRVGFiQmFyKToKICAgICIiIlRhYiBiYXIgdGh"
    "hdCBibG9ja3MgZHJhZyBpbml0aWF0aW9uIGZvciBsb2NrZWQgdGFicy4iIiIKCiAgICBkZWYgX19pbm"
    "l0X18oc2VsZiwgaXNfbG9ja2VkX2J5X2lkLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX"
    "2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5faXNfbG9ja2VkX2J5X2lkID0gaXNfbG9ja2VkX2J5"
    "X2lkCiAgICAgICAgc2VsZi5fcHJlc3NlZF9pbmRleCA9IC0xCgogICAgZGVmIF90YWJfaWQoc2VsZiw"
    "gaW5kZXg6IGludCk6CiAgICAgICAgaWYgaW5kZXggPCAwOgogICAgICAgICAgICByZXR1cm4gTm9uZQ"
    "ogICAgICAgIHJldHVybiBzZWxmLnRhYkRhdGEoaW5kZXgpCgogICAgZGVmIG1vdXNlUHJlc3NFdmVud"
    "ChzZWxmLCBldmVudCk6CiAgICAgICAgc2VsZi5fcHJlc3NlZF9pbmRleCA9IHNlbGYudGFiQXQoZXZl"
    "bnQucG9zKCkpCiAgICAgICAgaWYgKGV2ZW50LmJ1dHRvbigpID09IFF0Lk1vdXNlQnV0dG9uLkxlZnR"
    "CdXR0b24gYW5kIHNlbGYuX3ByZXNzZWRfaW5kZXggPj0gMCk6CiAgICAgICAgICAgIHRhYl9pZCA9IH"
    "NlbGYuX3RhYl9pZChzZWxmLl9wcmVzc2VkX2luZGV4KQogICAgICAgICAgICBpZiB0YWJfaWQgYW5kI"
    "HNlbGYuX2lzX2xvY2tlZF9ieV9pZCh0YWJfaWQpOgogICAgICAgICAgICAgICAgc2VsZi5zZXRDdXJy"
    "ZW50SW5kZXgoc2VsZi5fcHJlc3NlZF9pbmRleCkKICAgICAgICAgICAgICAgIGV2ZW50LmFjY2VwdCg"
    "pCiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICBzdXBlcigpLm1vdXNlUHJlc3NFdmVudChldm"
    "VudCkKCiAgICBkZWYgbW91c2VNb3ZlRXZlbnQoc2VsZiwgZXZlbnQpOgogICAgICAgIGlmIHNlbGYuX"
    "3ByZXNzZWRfaW5kZXggPj0gMDoKICAgICAgICAgICAgdGFiX2lkID0gc2VsZi5fdGFiX2lkKHNlbGYu"
    "X3ByZXNzZWRfaW5kZXgpCiAgICAgICAgICAgIGlmIHRhYl9pZCBhbmQgc2VsZi5faXNfbG9ja2VkX2J"
    "5X2lkKHRhYl9pZCk6CiAgICAgICAgICAgICAgICBldmVudC5hY2NlcHQoKQogICAgICAgICAgICAgIC"
    "AgcmV0dXJuCiAgICAgICAgc3VwZXIoKS5tb3VzZU1vdmVFdmVudChldmVudCkKCiAgICBkZWYgbW91c"
    "2VSZWxlYXNlRXZlbnQoc2VsZiwgZXZlbnQpOgogICAgICAgIHNlbGYuX3ByZXNzZWRfaW5kZXggPSAt"
    "MQogICAgICAgIHN1cGVyKCkubW91c2VSZWxlYXNlRXZlbnQoZXZlbnQpCgoKY2xhc3MgRWNob0RlY2s"
    "oUU1haW5XaW5kb3cpOgogICAgIiIiCiAgICBUaGUgbWFpbiBFY2hvIERlY2sgd2luZG93LgogICAgQX"
    "NzZW1ibGVzIGFsbCB3aWRnZXRzLCBjb25uZWN0cyBhbGwgc2lnbmFscywgbWFuYWdlcyBhbGwgc3Rhd"
    "GUuCiAgICAiIiIKCiAgICAjIOKUgOKUgCBUb3Jwb3IgdGhyZXNob2xkcyDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIAKICAgIF9FWFRFUk5BTF9WUkFNX1RPUlBPUl9HQiAgICA9IDEuNSAgICMgZXh0ZXJuYWwgVlJBT"
    "SA+IHRoaXMg4oaSIGNvbnNpZGVyIHRvcnBvcgogICAgX0VYVEVSTkFMX1ZSQU1fV0FLRV9HQiAgICAg"
    "ID0gMC44ICAgIyBleHRlcm5hbCBWUkFNIDwgdGhpcyDihpIgY29uc2lkZXIgd2FrZQogICAgX1RPUlB"
    "PUl9TVVNUQUlORURfVElDS1MgICAgID0gNiAgICAgIyA2IMOXIDVzID0gMzAgc2Vjb25kcyBzdXN0YW"
    "luZWQKICAgIF9XQUtFX1NVU1RBSU5FRF9USUNLUyAgICAgICA9IDEyICAgICMgNjAgc2Vjb25kcyBzd"
    "XN0YWluZWQgbG93IHByZXNzdXJlCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHN1cGVy"
    "KCkuX19pbml0X18oKQoKICAgICAgICAjIOKUgOKUgCBDb3JlIHN0YXRlIOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3N0YXR1cyAgICAgICAgICAgICAgPSAiT0ZGTElORSIK"
    "ICAgICAgICBzZWxmLl9zZXNzaW9uX3N0YXJ0ICAgICAgID0gdGltZS50aW1lKCkKICAgICAgICBzZWx"
    "mLl90b2tlbl9jb3VudCAgICAgICAgID0gMAogICAgICAgIHNlbGYuX2ZhY2VfbG9ja2VkICAgICAgIC"
    "AgPSBGYWxzZQogICAgICAgIHNlbGYuX2JsaW5rX3N0YXRlICAgICAgICAgPSBUcnVlCiAgICAgICAgc"
    "2VsZi5fbW9kZWxfbG9hZGVkICAgICAgICA9IEZhbHNlCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9pZCAg"
    "ICAgICAgICA9IGYic2Vzc2lvbl97ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVZJW0lZF8lSCVNJVM"
    "nKX0iCiAgICAgICAgc2VsZi5fYWN0aXZlX3RocmVhZHM6IGxpc3QgPSBbXSAgIyBrZWVwIHJlZnMgdG"
    "8gcHJldmVudCBHQyB3aGlsZSBydW5uaW5nCiAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW46IGJvb2wgP"
    "SBUcnVlICAgIyB3cml0ZSBzcGVha2VyIGxhYmVsIGJlZm9yZSBmaXJzdCBzdHJlYW1pbmcgdG9rZW4K"
    "CiAgICAgICAgIyBUb3Jwb3IgLyBWUkFNIHRyYWNraW5nCiAgICAgICAgc2VsZi5fdG9ycG9yX3N0YXR"
    "lICAgICAgICA9ICJBV0FLRSIKICAgICAgICBzZWxmLl9kZWNrX3ZyYW1fYmFzZSAgPSAwLjAgICAjIG"
    "Jhc2VsaW5lIFZSQU0gYWZ0ZXIgbW9kZWwgbG9hZAogICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfd"
    "Glja3MgPSAwICAgICAjIHN1c3RhaW5lZCBwcmVzc3VyZSBjb3VudGVyCiAgICAgICAgc2VsZi5fdnJh"
    "bV9yZWxpZWZfdGlja3MgICA9IDAgICAgICMgc3VzdGFpbmVkIHJlbGllZiBjb3VudGVyCiAgICAgICA"
    "gc2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zID0gMAogICAgICAgIHNlbGYuX3RvcnBvcl9zaW5jZS"
    "AgICAgICAgPSBOb25lICAjIGRhdGV0aW1lIHdoZW4gdG9ycG9yIGJlZ2FuCiAgICAgICAgc2VsZi5fc"
    "3VzcGVuZGVkX2R1cmF0aW9uICA9ICIiICAgIyBmb3JtYXR0ZWQgZHVyYXRpb24gc3RyaW5nCgogICAg"
    "ICAgICMg4pSA4pSAIE1hbmFnZXJzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogI"
    "CAgICAgIHNlbGYuX21lbW9yeSAgID0gTWVtb3J5TWFuYWdlcigpCiAgICAgICAgc2VsZi5fc2Vzc2lv"
    "bnMgPSBTZXNzaW9uTWFuYWdlcigpCiAgICAgICAgc2VsZi5fbGVzc29ucyAgPSBMZXNzb25zTGVhcm5"
    "lZERCKCkKICAgICAgICBzZWxmLl90YXNrcyAgICA9IFRhc2tNYW5hZ2VyKCkKICAgICAgICBzZWxmLl"
    "9yZWNvcmRzX2NhY2hlOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9yZWNvcmRzX2luaXRpY"
    "WxpemVkID0gRmFsc2UKICAgICAgICBzZWxmLl9yZWNvcmRzX2N1cnJlbnRfZm9sZGVyX2lkID0gInJv"
    "b3QiCiAgICAgICAgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHkgPSBGYWxzZQogICAgICAgIHNlbGYuX2d"
    "vb2dsZV9pbmJvdW5kX3RpbWVyOiBPcHRpb25hbFtRVGltZXJdID0gTm9uZQogICAgICAgIHNlbGYuX2"
    "dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXI6IE9wdGlvbmFsW1FUaW1lcl0gPSBOb25lCiAgICAgI"
    "CAgc2VsZi5fcmVjb3Jkc190YWJfaW5kZXggPSAtMQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYl9pbmRl"
    "eCA9IC0xCiAgICAgICAgc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCA9IEZhbHNlCiAgICAgICAgc2V"
    "sZi5fdGFza19kYXRlX2ZpbHRlciA9ICJuZXh0XzNfbW9udGhzIgoKICAgICAgICAjIFJpZ2h0IHN5c3"
    "RlbXMgdGFiLXN0cmlwIHByZXNlbnRhdGlvbiBzdGF0ZSAoc3RhYmxlIElEcyArIHZpc3VhbCBvcmRlc"
    "ikKICAgICAgICBzZWxmLl9zcGVsbF90YWJfZGVmczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2Vs"
    "Zi5fc3BlbGxfdGFiX3N0YXRlOiBkaWN0W3N0ciwgZGljdF0gPSB7fQogICAgICAgIHNlbGYuX3NwZWx"
    "sX3RhYl9tb3ZlX21vZGVfaWQ6IE9wdGlvbmFsW3N0cl0gPSBOb25lCiAgICAgICAgc2VsZi5fc3VwcH"
    "Jlc3Nfc3BlbGxfdGFiX21vdmVfc2lnbmFsID0gRmFsc2UKICAgICAgICBzZWxmLl9mb2N1c19ob29rZ"
    "WRfZm9yX3NwZWxsX3RhYnMgPSBGYWxzZQoKICAgICAgICAjIOKUgOKUgCBHb29nbGUgU2VydmljZXMg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSACiAgICAgICAgIyBJbnN0YW50aWF0ZSBzZXJ2aWNlIHdyYXBwZXJzIHVwLWZyb"
    "250OyBhdXRoIGlzIGZvcmNlZCBsYXRlcgogICAgICAgICMgZnJvbSBtYWluKCkgYWZ0ZXIgd2luZG93"
    "LnNob3coKSB3aGVuIHRoZSBldmVudCBsb29wIGlzIHJ1bm5pbmcuCiAgICAgICAgZ19jcmVkc19wYXR"
    "oID0gUGF0aChDRkcuZ2V0KCJnb29nbGUiLCB7fSkuZ2V0KAogICAgICAgICAgICAiY3JlZGVudGlhbH"
    "MiLAogICAgICAgICAgICBzdHIoY2ZnX3BhdGgoImdvb2dsZSIpIC8gImdvb2dsZV9jcmVkZW50aWFsc"
    "y5qc29uIikKICAgICAgICApKQogICAgICAgIGdfdG9rZW5fcGF0aCA9IFBhdGgoQ0ZHLmdldCgiZ29v"
    "Z2xlIiwge30pLmdldCgKICAgICAgICAgICAgInRva2VuIiwKICAgICAgICAgICAgc3RyKGNmZ19wYXR"
    "oKCJnb29nbGUiKSAvICJ0b2tlbi5qc29uIikKICAgICAgICApKQogICAgICAgIHNlbGYuX2djYWwgPS"
    "BHb29nbGVDYWxlbmRhclNlcnZpY2UoZ19jcmVkc19wYXRoLCBnX3Rva2VuX3BhdGgpCiAgICAgICAgc"
    "2VsZi5fZ2RyaXZlID0gR29vZ2xlRG9jc0RyaXZlU2VydmljZSgKICAgICAgICAgICAgZ19jcmVkc19w"
    "YXRoLAogICAgICAgICAgICBnX3Rva2VuX3BhdGgsCiAgICAgICAgICAgIGxvZ2dlcj1sYW1iZGEgbXN"
    "nLCBsZXZlbD0iSU5GTyI6IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHRFJJVkVdIHttc2d9IiwgbGV2ZW"
    "wpCiAgICAgICAgKQoKICAgICAgICAjIFNlZWQgTFNMIHJ1bGVzIG9uIGZpcnN0IHJ1bgogICAgICAgI"
    "HNlbGYuX2xlc3NvbnMuc2VlZF9sc2xfcnVsZXMoKQoKICAgICAgICAjIExvYWQgZW50aXR5IHN0YXRl"
    "CiAgICAgICAgc2VsZi5fc3RhdGUgPSBzZWxmLl9tZW1vcnkubG9hZF9zdGF0ZSgpCiAgICAgICAgc2V"
    "sZi5fc3RhdGVbInNlc3Npb25fY291bnQiXSA9IHNlbGYuX3N0YXRlLmdldCgic2Vzc2lvbl9jb3VudC"
    "IsMCkgKyAxCiAgICAgICAgc2VsZi5fc3RhdGVbImxhc3Rfc3RhcnR1cCJdICA9IGxvY2FsX25vd19pc"
    "28oKQogICAgICAgIHNlbGYuX21lbW9yeS5zYXZlX3N0YXRlKHNlbGYuX3N0YXRlKQoKICAgICAgICAj"
    "IEJ1aWxkIGFkYXB0b3IKICAgICAgICBzZWxmLl9hZGFwdG9yID0gYnVpbGRfYWRhcHRvcl9mcm9tX2N"
    "vbmZpZygpCgogICAgICAgICMgRmFjZSB0aW1lciBtYW5hZ2VyIChzZXQgdXAgYWZ0ZXIgd2lkZ2V0cy"
    "BidWlsdCkKICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21ncjogT3B0aW9uYWxbRmFjZVRpbWVyTWFuY"
    "Wdlcl0gPSBOb25lCgogICAgICAgICMg4pSA4pSAIEJ1aWxkIFVJIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuc2V0V2luZG93VGl0bGUoQVBQX05BTUUpCiAgICAgI"
    "CAgc2VsZi5zZXRNaW5pbXVtU2l6ZSgxMjAwLCA3NTApCiAgICAgICAgc2VsZi5yZXNpemUoMTM1MCwg"
    "ODUwKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldChTVFlMRSkKCiAgICAgICAgc2VsZi5fYnVpbGR"
    "fdWkoKQoKICAgICAgICAjIEZhY2UgdGltZXIgbWFuYWdlciB3aXJlZCB0byB3aWRnZXRzCiAgICAgIC"
    "Agc2VsZi5fZmFjZV90aW1lcl9tZ3IgPSBGYWNlVGltZXJNYW5hZ2VyKAogICAgICAgICAgICBzZWxmL"
    "l9taXJyb3IsIHNlbGYuX2Vtb3Rpb25fYmxvY2sKICAgICAgICApCgogICAgICAgICMg4pSA4pSAIFRp"
    "bWVycyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmL"
    "l9zdGF0c190aW1lciA9IFFUaW1lcigpCiAgICAgICAgc2VsZi5fc3RhdHNfdGltZXIudGltZW91dC5j"
    "b25uZWN0KHNlbGYuX3VwZGF0ZV9zdGF0cykKICAgICAgICBzZWxmLl9zdGF0c190aW1lci5zdGFydCg"
    "xMDAwKQoKICAgICAgICBzZWxmLl9ibGlua190aW1lciA9IFFUaW1lcigpCiAgICAgICAgc2VsZi5fYm"
    "xpbmtfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX2JsaW5rKQogICAgICAgIHNlbGYuX2JsaW5rX"
    "3RpbWVyLnN0YXJ0KDgwMCkKCiAgICAgICAgc2VsZi5fc3RhdGVfc3RyaXBfdGltZXIgPSBRVGltZXIo"
    "KQogICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEIGFuZCBzZWxmLl9mb290ZXJfc3RyaXAgaXMgbm9"
    "0IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3N0YXRlX3N0cmlwX3RpbWVyLnRpbWVvdXQuY29ubmVjdC"
    "hzZWxmLl9mb290ZXJfc3RyaXAucmVmcmVzaCkKICAgICAgICAgICAgc2VsZi5fc3RhdGVfc3RyaXBfd"
    "GltZXIuc3RhcnQoNjAwMDApCgogICAgICAgIHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyID0gUVRp"
    "bWVyKHNlbGYpCiAgICAgICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGltZXIudGltZW91dC5jb25uZWN"
    "0KHNlbGYuX29uX2dvb2dsZV9pbmJvdW5kX3RpbWVyX3RpY2spCiAgICAgICAgc2VsZi5fZ29vZ2xlX2"
    "luYm91bmRfdGltZXIuc3RhcnQoc2VsZi5fZ2V0X2dvb2dsZV9yZWZyZXNoX2ludGVydmFsX21zKCkpC"
    "gogICAgICAgIHNlbGYuX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXIgPSBRVGltZXIoc2VsZikK"
    "ICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyLnRpbWVvdXQuY29ubmVjdCh"
    "zZWxmLl9vbl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyX3RpY2spCiAgICAgICAgc2VsZi5fZ2"
    "9vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lci5zdGFydChzZWxmLl9nZXRfZ29vZ2xlX3JlZnJlc2hfa"
    "W50ZXJ2YWxfbXMoKSkKCiAgICAgICAgIyDilIDilIAgU2NoZWR1bGVyIGFuZCBzdGFydHVwIGRlZmVy"
    "cmVkIHVudGlsIGFmdGVyIHdpbmRvdy5zaG93KCkg4pSA4pSA4pSACiAgICAgICAgIyBEbyBOT1QgY2F"
    "sbCBfc2V0dXBfc2NoZWR1bGVyKCkgb3IgX3N0YXJ0dXBfc2VxdWVuY2UoKSBoZXJlLgogICAgICAgIC"
    "MgQm90aCBhcmUgdHJpZ2dlcmVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBmcm9tIG1haW4oKSBhZnRlc"
    "gogICAgICAgICMgd2luZG93LnNob3coKSBhbmQgYXBwLmV4ZWMoKSBiZWdpbnMgcnVubmluZy4KCiAg"
    "ICAjIOKUgOKUgCBVSSBDT05TVFJVQ1RJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2J1aWxkX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "Y2VudHJhbCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuc2V0Q2VudHJhbFdpZGdldChjZW50cmFsKQo"
    "gICAgICAgIHJvb3QgPSBRVkJveExheW91dChjZW50cmFsKQogICAgICAgIHJvb3Quc2V0Q29udGVudH"
    "NNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMg4"
    "pSA4pSAIFRpdGxlIGJhciDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICByb2"
    "90LmFkZFdpZGdldChzZWxmLl9idWlsZF90aXRsZV9iYXIoKSkKCiAgICAgICAgIyDilIDilIAgQm9ke"
    "TogSm91cm5hbCB8IENoYXQgfCBTeXN0ZW1zIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICA"
    "gICAgIGJvZHkgPSBRSEJveExheW91dCgpCiAgICAgICAgYm9keS5zZXRTcGFjaW5nKDQpCgogICAgIC"
    "AgICMgSm91cm5hbCBzaWRlYmFyIChsZWZ0KQogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhciA9I"
    "EpvdXJuYWxTaWRlYmFyKHNlbGYuX3Nlc3Npb25zKQogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJh"
    "ci5zZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmNvbm5lY3QoCiAgICAgICAgICAgIHNlbGYuX2xvYWRfam9"
    "1cm5hbF9zZXNzaW9uKQogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXNzaW9uX2NsZWFyX3"
    "JlcXVlc3RlZC5jb25uZWN0KAogICAgICAgICAgICBzZWxmLl9jbGVhcl9qb3VybmFsX3Nlc3Npb24pC"
    "iAgICAgICAgYm9keS5hZGRXaWRnZXQoc2VsZi5fam91cm5hbF9zaWRlYmFyKQoKICAgICAgICAjIENo"
    "YXQgcGFuZWwgKGNlbnRlciwgZXhwYW5kcykKICAgICAgICBib2R5LmFkZExheW91dChzZWxmLl9idWl"
    "sZF9jaGF0X3BhbmVsKCksIDEpCgogICAgICAgICMgU3lzdGVtcyAocmlnaHQpCiAgICAgICAgYm9keS"
    "5hZGRMYXlvdXQoc2VsZi5fYnVpbGRfc3BlbGxib29rX3BhbmVsKCkpCgogICAgICAgIHJvb3QuYWRkT"
    "GF5b3V0KGJvZHksIDEpCgogICAgICAgICMg4pSA4pSAIEZvb3RlciDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBmb290ZXIgPSBRTGFiZWwoCiAgICAgICAgICAgI"
    "GYi4pymIHtBUFBfTkFNRX0g4oCUIHZ7QVBQX1ZFUlNJT059IOKcpiIKICAgICAgICApCiAgICAgICAg"
    "Zm9vdGVyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9"
    "udC1zaXplOiA5cHg7IGxldHRlci1zcGFjaW5nOiAycHg7ICIKICAgICAgICAgICAgZiJmb250LWZhbW"
    "lseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgZm9vdGVyLnNldEFsaWdub"
    "WVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KGZv"
    "b3RlcikKCiAgICBkZWYgX2J1aWxkX3RpdGxlX2JhcihzZWxmKSAtPiBRV2lkZ2V0OgogICAgICAgIGJ"
    "hciA9IFFXaWRnZXQoKQogICAgICAgIGJhci5zZXRGaXhlZEhlaWdodCgzNikKICAgICAgICBiYXIuc2"
    "V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFwe"
    "CBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXItcmFkaXVzOiAycHg7"
    "IgogICAgICAgICkKICAgICAgICBsYXlvdXQgPSBRSEJveExheW91dChiYXIpCiAgICAgICAgbGF5b3V"
    "0LnNldENvbnRlbnRzTWFyZ2lucygxMCwgMCwgMTAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbm"
    "coNikKCiAgICAgICAgdGl0bGUgPSBRTGFiZWwoZiLinKYge0FQUF9OQU1FfSIpCiAgICAgICAgdGl0b"
    "GUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6"
    "ZTogMTNweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJsZXR0ZXItc3BhY2luZzo"
    "gMnB4OyBib3JkZXI6IG5vbmU7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgIC"
    "AgICkKCiAgICAgICAgcnVuZXMgPSBRTGFiZWwoUlVORVMpCiAgICAgICAgcnVuZXMuc2V0U3R5bGVTa"
    "GVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRF9ESU19OyBmb250LXNpemU6IDEwcHg7IGJv"
    "cmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHJ1bmVzLnNldEFsaWdubWVudChRdC5BbGlnbm1"
    "lbnRGbGFnLkFsaWduQ2VudGVyKQoKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbCA9IFFMYWJlbChmIu"
    "KXiSB7VUlfT0ZGTElORV9TVEFUVVN9IikKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRTdHlsZ"
    "VNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19CTE9PRH07IGZvbnQtc2l6ZTogMTJweDsgZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuc3RhdHV"
    "zX2xhYmVsLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduUmlnaHQpCgogICAgICAgIC"
    "MgU3VzcGVuc2lvbiBwYW5lbAogICAgICAgIHNlbGYuX3RvcnBvcl9wYW5lbCA9IE5vbmUKICAgICAgI"
    "CBpZiBTVVNQRU5TSU9OX0VOQUJMRUQ6CiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9wYW5lbCA9IFRv"
    "cnBvclBhbmVsKCkKICAgICAgICAgICAgc2VsZi5fdG9ycG9yX3BhbmVsLnN0YXRlX2NoYW5nZWQuY29"
    "ubmVjdChzZWxmLl9vbl90b3Jwb3Jfc3RhdGVfY2hhbmdlZCkKCiAgICAgICAgIyBJZGxlIHRvZ2dsZQ"
    "ogICAgICAgIGlkbGVfZW5hYmxlZCA9IGJvb2woQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkuZ2V0KCJpZ"
    "GxlX2VuYWJsZWQiLCBGYWxzZSkpCiAgICAgICAgc2VsZi5faWRsZV9idG4gPSBRUHVzaEJ1dHRvbigi"
    "SURMRSBPTiIgaWYgaWRsZV9lbmFibGVkIGVsc2UgIklETEUgT0ZGIikKICAgICAgICBzZWxmLl9pZGx"
    "lX2J0bi5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRDaGVja2FibG"
    "UoVHJ1ZSkKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRDaGVja2VkKGlkbGVfZW5hYmxlZCkKICAgI"
    "CAgICBzZWxmLl9pZGxlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6"
    "IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCB"
    "zb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgZiJmb250LX"
    "NpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IgogICAgICAgICkKI"
    "CAgICAgICBzZWxmLl9pZGxlX2J0bi50b2dnbGVkLmNvbm5lY3Qoc2VsZi5fb25faWRsZV90b2dnbGVk"
    "KQoKICAgICAgICAjIEZTIC8gQkwgYnV0dG9ucwogICAgICAgIHNlbGYuX2ZzX2J0biA9IFFQdXNoQnV"
    "0dG9uKCJGdWxsc2NyZWVuIikKICAgICAgICBzZWxmLl9ibF9idG4gPSBRUHVzaEJ1dHRvbigiQm9yZG"
    "VybGVzcyIpCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0biA9IFFQdXNoQnV0dG9uKCJFeHBvcnQiKQogI"
    "CAgICAgIHNlbGYuX3NodXRkb3duX2J0biA9IFFQdXNoQnV0dG9uKCJTaHV0ZG93biIpCiAgICAgICAg"
    "Zm9yIGJ0biBpbiAoc2VsZi5fZnNfYnRuLCBzZWxmLl9ibF9idG4sIHNlbGYuX2V4cG9ydF9idG4pOgo"
    "gICAgICAgICAgICBidG4uc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgICAgIGJ0bi5zZXRTdHlsZV"
    "NoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJT"
    "VNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05f"
    "RElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ"
    "7IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0bi5zZXRGaX"
    "hlZFdpZHRoKDQ2KQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5zZXRGaXhlZEhlaWdodCgyMikKI"
    "CAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uc2V0Rml4ZWRXaWR0aCg2OCkKICAgICAgICBzZWxmLl9z"
    "aHV0ZG93bl9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN"
    "9OyBjb2xvcjoge0NfQkxPT0R9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk"
    "xPT0R9OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwY"
    "WRkaW5nOiAwOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZnNfYnRuLnNldFRvb2xUaXAoIkZ1bGxz"
    "Y3JlZW4gKEYxMSkiKQogICAgICAgIHNlbGYuX2JsX2J0bi5zZXRUb29sVGlwKCJCb3JkZXJsZXNzICh"
    "GMTApIikKICAgICAgICBzZWxmLl9leHBvcnRfYnRuLnNldFRvb2xUaXAoIkV4cG9ydCBjaGF0IHNlc3"
    "Npb24gdG8gVFhUIGZpbGUiKQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5zZXRUb29sVGlwKGYiR"
    "3JhY2VmdWwgc2h1dGRvd24g4oCUIHtERUNLX05BTUV9IHNwZWFrcyB0aGVpciBsYXN0IHdvcmRzIikK"
    "ICAgICAgICBzZWxmLl9mc19idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9mdWxsc2NyZWV"
    "uKQogICAgICAgIHNlbGYuX2JsX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2JvcmRlcm"
    "xlc3MpCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZXhwb3J0X"
    "2NoYXQpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9pbml0"
    "aWF0ZV9zaHV0ZG93bl9kaWFsb2cpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQodGl0bGUpCiAgICA"
    "gICAgbGF5b3V0LmFkZFdpZGdldChydW5lcywgMSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbG"
    "Yuc3RhdHVzX2xhYmVsKQogICAgICAgIGxheW91dC5hZGRTcGFjaW5nKDgpCiAgICAgICAgbGF5b3V0L"
    "mFkZFdpZGdldChzZWxmLl9leHBvcnRfYnRuKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5f"
    "c2h1dGRvd25fYnRuKQoKICAgICAgICByZXR1cm4gYmFyCgogICAgZGVmIF9idWlsZF9jaGF0X3BhbmV"
    "sKHNlbGYpIC0+IFFWQm94TGF5b3V0OgogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KCkKICAgIC"
    "AgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICAjIE1haW4gdGFiIHdpZGdldCDigJQgcGVyc"
    "29uYSBjaGF0IHRhYiB8IFNlbGYKICAgICAgICBzZWxmLl9tYWluX3RhYnMgPSBRVGFiV2lkZ2V0KCkK"
    "ICAgICAgICBzZWxmLl9tYWluX3RhYnMuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJRVGFiV2l"
    "kZ2V0OjpwYW5lIHt7IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgIC"
    "AgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyB9fSIKICAgICAgICAgICAgZiJRVGFiQmFyOjp0Y"
    "WIge3sgYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAg"
    "ICBmInBhZGRpbmc6IDRweCAxMnB4OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICA"
    "gICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4Oy"
    "B9fSIKICAgICAgICAgICAgZiJRVGFiQmFyOjp0YWI6c2VsZWN0ZWQge3sgYmFja2dyb3VuZDoge0NfQ"
    "kcyfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLWJvdHRvbTogMnB4IHNv"
    "bGlkIHtDX0NSSU1TT059OyB9fSIKICAgICAgICApCgogICAgICAgICMg4pSA4pSAIFRhYiAwOiBQZXJ"
    "zb25hIGNoYXQgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "AogICAgICAgIHNlYW5jZV93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWFuY2VfbGF5b3V0ID0g"
    "UVZCb3hMYXlvdXQoc2VhbmNlX3dpZGdldCkKICAgICAgICBzZWFuY2VfbGF5b3V0LnNldENvbnRlbnR"
    "zTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlYW5jZV9sYXlvdXQuc2V0U3BhY2luZygwKQogIC"
    "AgICAgIHNlbGYuX2NoYXRfZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fY2hhdF9ka"
    "XNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9yOiB7Q19HT0x"
    "EfTsgIgogICAgICAgICAgICBmImJvcmRlcjogbm9uZTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaW"
    "x5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTJweDsgcGFkZGluZzogOHB4OyIKICAgI"
    "CAgICApCiAgICAgICAgc2VhbmNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fY2hhdF9kaXNwbGF5KQog"
    "ICAgICAgIHNlbGYuX21haW5fdGFicy5hZGRUYWIoc2VhbmNlX3dpZGdldCwgZiLinacge1VJX0NIQVR"
    "fV0lORE9XfSIpCgogICAgICAgICMg4pSA4pSAIFRhYiAxOiBTZWxmIOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgICAgIHNlbGYuX3NlbGZfdGFiX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIHN"
    "lbGZfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fc2VsZl90YWJfd2lkZ2V0KQogICAgICAgIHNlbG"
    "ZfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGZfbGF5b3V0L"
    "nNldFNwYWNpbmcoNCkKICAgICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAg"
    "ICAgIHNlbGYuX3NlbGZfZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX3NlbGZ"
    "fZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1"
    "J9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7ICIKICAgICAgI"
    "CAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEycHg7IHBh"
    "ZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHNlbGZfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9"
    "zZWxmX2Rpc3BsYXksIDEpCiAgICAgICAgc2VsZi5fbWFpbl90YWJzLmFkZFRhYihzZWxmLl9zZWxmX3"
    "RhYl93aWRnZXQsICLil4kgU0VMRiIpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fbWFpb"
    "l90YWJzLCAxKQoKICAgICAgICAjIOKUgOKUgCBCb3R0b20gc3RhdHVzL3Jlc291cmNlIGJsb2NrIHJv"
    "dyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAjIE1hbmRhdG9yeSBwZXJtYW5lbnQgc3RydW"
    "N0dXJlIGFjcm9zcyBhbGwgcGVyc29uYXM6CiAgICAgICAgIyBNSVJST1IgfCBbTE9XRVItTUlERExFI"
    "FBFUk1BTkVOVCBGT09UUFJJTlRdCiAgICAgICAgYmxvY2tfcm93ID0gUUhCb3hMYXlvdXQoKQogICAg"
    "ICAgIGJsb2NrX3Jvdy5zZXRTcGFjaW5nKDIpCgogICAgICAgICMgTWlycm9yIChuZXZlciBjb2xsYXB"
    "zZXMpCiAgICAgICAgbWlycm9yX3dyYXAgPSBRV2lkZ2V0KCkKICAgICAgICBtd19sYXlvdXQgPSBRVk"
    "JveExheW91dChtaXJyb3Jfd3JhcCkKICAgICAgICBtd19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zK"
    "DAsIDAsIDAsIDApCiAgICAgICAgbXdfbGF5b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBtd19sYXlv"
    "dXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibChmIuKdpyB7VUlfTUlSUk9SX0xBQkVMfSIpKQogICAgICA"
    "gIHNlbGYuX21pcnJvciA9IE1pcnJvcldpZGdldCgpCiAgICAgICAgc2VsZi5fbWlycm9yLnNldEZpeG"
    "VkU2l6ZSgxNjAsIDE2MCkKICAgICAgICBtd19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX21pcnJvcikKI"
    "CAgICAgICBibG9ja19yb3cuYWRkV2lkZ2V0KG1pcnJvcl93cmFwLCAwKQoKICAgICAgICAjIE1pZGRs"
    "ZSBsb3dlciBibG9jayBrZWVwcyBhIHBlcm1hbmVudCBmb290cHJpbnQ6CiAgICAgICAgIyBsZWZ0ID0"
    "gY29tcGFjdCBzdGFjayBhcmVhLCByaWdodCA9IGZpeGVkIGV4cGFuZGVkLXJvdyBzbG90cy4KICAgIC"
    "AgICBtaWRkbGVfd3JhcCA9IFFXaWRnZXQoKQogICAgICAgIG1pZGRsZV9sYXlvdXQgPSBRSEJveExhe"
    "W91dChtaWRkbGVfd3JhcCkKICAgICAgICBtaWRkbGVfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygw"
    "LCAwLCAwLCAwKQogICAgICAgIG1pZGRsZV9sYXlvdXQuc2V0U3BhY2luZygyKQoKICAgICAgICBzZWx"
    "mLl9sb3dlcl9zdGFja193cmFwID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfd3"
    "JhcC5zZXRNaW5pbXVtV2lkdGgoMTMwKQogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX3dyYXAuc2V0T"
    "WF4aW11bVdpZHRoKDEzMCkKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja19sYXlvdXQgPSBRVkJveExh"
    "eW91dChzZWxmLl9sb3dlcl9zdGFja193cmFwKQogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX2xheW9"
    "1dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja1"
    "9sYXlvdXQuc2V0U3BhY2luZygyKQogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX3dyYXAuc2V0Vmlza"
    "WJsZShGYWxzZSkKICAgICAgICBtaWRkbGVfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9sb3dlcl9zdGFj"
    "a193cmFwLCAwKQoKICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3cgPSBRV2lkZ2V0KCkKICA"
    "gICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0ID0gUUdyaWRMYXlvdXQoc2VsZi5fbG"
    "93ZXJfZXhwYW5kZWRfcm93KQogICAgICAgIHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Jvd19sYXlvdXQuc"
    "2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRf"
    "cm93X2xheW91dC5zZXRIb3Jpem9udGFsU3BhY2luZygyKQogICAgICAgIHNlbGYuX2xvd2VyX2V4cGF"
    "uZGVkX3Jvd19sYXlvdXQuc2V0VmVydGljYWxTcGFjaW5nKDIpCiAgICAgICAgbWlkZGxlX2xheW91dC"
    "5hZGRXaWRnZXQoc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93LCAxKQoKICAgICAgICAjIEVtb3Rpb24gY"
    "mxvY2sgKGNvbGxhcHNpYmxlKQogICAgICAgIHNlbGYuX2Vtb3Rpb25fYmxvY2sgPSBFbW90aW9uQmxv"
    "Y2soKQogICAgICAgIHNlbGYuX2Vtb3Rpb25fYmxvY2tfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2soCiA"
    "gICAgICAgICAgIGYi4p2nIHtVSV9FTU9USU9OU19MQUJFTH0iLCBzZWxmLl9lbW90aW9uX2Jsb2NrLA"
    "ogICAgICAgICAgICBleHBhbmRlZD1UcnVlLCBtaW5fd2lkdGg9MTMwLCByZXNlcnZlX3dpZHRoPVRyd"
    "WUKICAgICAgICApCgogICAgICAgICMgTGVmdCByZXNvdXJjZSBvcmIgKGNvbGxhcHNpYmxlKQogICAg"
    "ICAgIHNlbGYuX2xlZnRfb3JiID0gU3BoZXJlV2lkZ2V0KAogICAgICAgICAgICBVSV9MRUZUX09SQl9"
    "MQUJFTCwgQ19DUklNU09OLCBDX0NSSU1TT05fRElNCiAgICAgICAgKQogICAgICAgIHNlbGYuX2xlZn"
    "Rfb3JiX3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfTEVGVF9PU"
    "kJfVElUTEV9Iiwgc2VsZi5fbGVmdF9vcmIsCiAgICAgICAgICAgIG1pbl93aWR0aD05MCwgcmVzZXJ2"
    "ZV93aWR0aD1UcnVlCiAgICAgICAgKQoKICAgICAgICAjIENlbnRlciBjeWNsZSB3aWRnZXQgKGNvbGx"
    "hcHNpYmxlKQogICAgICAgIHNlbGYuX2N5Y2xlX3dpZGdldCA9IEN5Y2xlV2lkZ2V0KCkKICAgICAgIC"
    "BzZWxmLl9jeWNsZV93cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacge1VJX"
    "0NZQ0xFX1RJVExFfSIsIHNlbGYuX2N5Y2xlX3dpZGdldCwKICAgICAgICAgICAgbWluX3dpZHRoPTkw"
    "LCByZXNlcnZlX3dpZHRoPVRydWUKICAgICAgICApCgogICAgICAgICMgUmlnaHQgcmVzb3VyY2Ugb3J"
    "iIChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9yaWdodF9vcmIgPSBTcGhlcmVXaWRnZXQoCiAgIC"
    "AgICAgICAgIFVJX1JJR0hUX09SQl9MQUJFTCwgQ19QVVJQTEUsIENfUFVSUExFX0RJTQogICAgICAgI"
    "CkKICAgICAgICBzZWxmLl9yaWdodF9vcmJfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2soCiAgICAgICAg"
    "ICAgIGYi4p2nIHtVSV9SSUdIVF9PUkJfVElUTEV9Iiwgc2VsZi5fcmlnaHRfb3JiLAogICAgICAgICA"
    "gICBtaW5fd2lkdGg9OTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAgICAgICkKCiAgICAgICAgIyBFc3"
    "NlbmNlICgyIGdhdWdlcywgY29sbGFwc2libGUpCiAgICAgICAgZXNzZW5jZV93aWRnZXQgPSBRV2lkZ"
    "2V0KCkKICAgICAgICBlc3NlbmNlX2xheW91dCA9IFFWQm94TGF5b3V0KGVzc2VuY2Vfd2lkZ2V0KQog"
    "ICAgICAgIGVzc2VuY2VfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICA"
    "gIGVzc2VuY2VfbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBzZWxmLl9lc3NlbmNlX3ByaW1hcn"
    "lfZ2F1Z2UgICA9IEdhdWdlV2lkZ2V0KFVJX0VTU0VOQ0VfUFJJTUFSWSwgICAiJSIsIDEwMC4wLCBDX"
    "0NSSU1TT04pCiAgICAgICAgc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2UgPSBHYXVnZVdpZGdl"
    "dChVSV9FU1NFTkNFX1NFQ09OREFSWSwgIiUiLCAxMDAuMCwgQ19HUkVFTikKICAgICAgICBlc3NlbmN"
    "lX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fZXNzZW5jZV9wcmltYXJ5X2dhdWdlKQogICAgICAgIGVzc2"
    "VuY2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZSkKICAgICAgI"
    "CBzZWxmLl9lc3NlbmNlX3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7"
    "VUlfRVNTRU5DRV9USVRMRX0iLCBlc3NlbmNlX3dpZGdldCwKICAgICAgICAgICAgbWluX3dpZHRoPTE"
    "xMCwgcmVzZXJ2ZV93aWR0aD1UcnVlCiAgICAgICAgKQoKICAgICAgICAjIEV4cGFuZGVkIHJvdyBzbG"
    "90cyBtdXN0IHN0YXkgaW4gY2Fub25pY2FsIHZpc3VhbCBvcmRlci4KICAgICAgICBzZWxmLl9sb3dlc"
    "l9leHBhbmRlZF9zbG90X29yZGVyID0gWwogICAgICAgICAgICAiZW1vdGlvbnMiLCAicHJpbWFyeSIs"
    "ICJjeWNsZSIsICJzZWNvbmRhcnkiLCAiZXNzZW5jZSIKICAgICAgICBdCiAgICAgICAgc2VsZi5fbG9"
    "3ZXJfY29tcGFjdF9zdGFja19vcmRlciA9IFsKICAgICAgICAgICAgImN5Y2xlIiwgInByaW1hcnkiLC"
    "Aic2Vjb25kYXJ5IiwgImVzc2VuY2UiLCAiZW1vdGlvbnMiCiAgICAgICAgXQogICAgICAgIHNlbGYuX"
    "2xvd2VyX21vZHVsZV93cmFwcyA9IHsKICAgICAgICAgICAgImVtb3Rpb25zIjogc2VsZi5fZW1vdGlv"
    "bl9ibG9ja193cmFwLAogICAgICAgICAgICAicHJpbWFyeSI6IHNlbGYuX2xlZnRfb3JiX3dyYXAsCiA"
    "gICAgICAgICAgICJjeWNsZSI6IHNlbGYuX2N5Y2xlX3dyYXAsCiAgICAgICAgICAgICJzZWNvbmRhcn"
    "kiOiBzZWxmLl9yaWdodF9vcmJfd3JhcCwKICAgICAgICAgICAgImVzc2VuY2UiOiBzZWxmLl9lc3Nlb"
    "mNlX3dyYXAsCiAgICAgICAgfQoKICAgICAgICBzZWxmLl9sb3dlcl9yb3dfc2xvdHMgPSB7fQogICAg"
    "ICAgIGZvciBjb2wsIGtleSBpbiBlbnVtZXJhdGUoc2VsZi5fbG93ZXJfZXhwYW5kZWRfc2xvdF9vcmR"
    "lcik6CiAgICAgICAgICAgIHNsb3QgPSBRV2lkZ2V0KCkKICAgICAgICAgICAgc2xvdF9sYXlvdXQgPS"
    "BRVkJveExheW91dChzbG90KQogICAgICAgICAgICBzbG90X2xheW91dC5zZXRDb250ZW50c01hcmdpb"
    "nMoMCwgMCwgMCwgMCkKICAgICAgICAgICAgc2xvdF9sYXlvdXQuc2V0U3BhY2luZygwKQogICAgICAg"
    "ICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LmFkZFdpZGdldChzbG90LCAwLCBjb2w"
    "pCiAgICAgICAgICAgIHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Jvd19sYXlvdXQuc2V0Q29sdW1uU3RyZX"
    "RjaChjb2wsIDEpCiAgICAgICAgICAgIHNlbGYuX2xvd2VyX3Jvd19zbG90c1trZXldID0gc2xvdF9sY"
    "XlvdXQKCiAgICAgICAgZm9yIHdyYXAgaW4gc2VsZi5fbG93ZXJfbW9kdWxlX3dyYXBzLnZhbHVlcygp"
    "OgogICAgICAgICAgICB3cmFwLnRvZ2dsZWQuY29ubmVjdChzZWxmLl9yZWZyZXNoX2xvd2VyX21pZGR"
    "sZV9sYXlvdXQpCgogICAgICAgIHNlbGYuX3JlZnJlc2hfbG93ZXJfbWlkZGxlX2xheW91dCgpCgogIC"
    "AgICAgIGJsb2NrX3Jvdy5hZGRXaWRnZXQobWlkZGxlX3dyYXAsIDEpCiAgICAgICAgbGF5b3V0LmFkZ"
    "ExheW91dChibG9ja19yb3cpCgogICAgICAgICMgRm9vdGVyIHN0YXRlIHN0cmlwIChiZWxvdyBibG9j"
    "ayByb3cg4oCUIHBlcm1hbmVudCBVSSBzdHJ1Y3R1cmUpCiAgICAgICAgc2VsZi5fZm9vdGVyX3N0cml"
    "wID0gRm9vdGVyU3RyaXBXaWRnZXQoKQogICAgICAgIHNlbGYuX2Zvb3Rlcl9zdHJpcC5zZXRfbGFiZW"
    "woVUlfRk9PVEVSX1NUUklQX0xBQkVMKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZm9vd"
    "GVyX3N0cmlwKQoKICAgICAgICAjIOKUgOKUgCBJbnB1dCByb3cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSACiAgICAgICAgaW5wdXRfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHByb21wd"
    "F9zeW0gPSBRTGFiZWwoIuKcpiIpCiAgICAgICAgcHJvbXB0X3N5bS5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImNvbG9yOiB7Q19DUklNU09OfTsgZm9udC1zaXplOiAxNnB4OyBmb250LXdlaWdodDo"
    "gYm9sZDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAgcHJvbXB0X3N5bS5zZXRGaXhlZF"
    "dpZHRoKDIwKQoKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc"
    "2VsZi5faW5wdXRfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KFVJX0lOUFVUX1BMQUNFSE9MREVSKQog"
    "ICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnJldHVyblByZXNzZWQuY29ubmVjdChzZWxmLl9zZW5kX21"
    "lc3NhZ2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKCiAgICAgIC"
    "Agc2VsZi5fc2VuZF9idG4gPSBRUHVzaEJ1dHRvbihVSV9TRU5EX0JVVFRPTikKICAgICAgICBzZWxmL"
    "l9zZW5kX2J0bi5zZXRGaXhlZFdpZHRoKDExMCkKICAgICAgICBzZWxmLl9zZW5kX2J0bi5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fc2VuZF9tZXNzYWdlKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJ"
    "sZWQoRmFsc2UpCgogICAgICAgIGlucHV0X3Jvdy5hZGRXaWRnZXQocHJvbXB0X3N5bSkKICAgICAgIC"
    "BpbnB1dF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2lucHV0X2ZpZWxkKQogICAgICAgIGlucHV0X3Jvdy5hZ"
    "GRXaWRnZXQoc2VsZi5fc2VuZF9idG4pCiAgICAgICAgbGF5b3V0LmFkZExheW91dChpbnB1dF9yb3cp"
    "CgogICAgICAgIHJldHVybiBsYXlvdXQKCiAgICBkZWYgX2NsZWFyX2xheW91dF93aWRnZXRzKHNlbGY"
    "sIGxheW91dDogUVZCb3hMYXlvdXQpIC0+IE5vbmU6CiAgICAgICAgd2hpbGUgbGF5b3V0LmNvdW50KC"
    "k6CiAgICAgICAgICAgIGl0ZW0gPSBsYXlvdXQudGFrZUF0KDApCiAgICAgICAgICAgIHdpZGdldCA9I"
    "Gl0ZW0ud2lkZ2V0KCkKICAgICAgICAgICAgaWYgd2lkZ2V0IGlzIG5vdCBOb25lOgogICAgICAgICAg"
    "ICAgICAgd2lkZ2V0LnNldFBhcmVudChOb25lKQoKICAgIGRlZiBfcmVmcmVzaF9sb3dlcl9taWRkbGV"
    "fbGF5b3V0KHNlbGYsICpfYXJncykgLT4gTm9uZToKICAgICAgICBjb2xsYXBzZWRfY291bnQgPSAwCg"
    "ogICAgICAgICMgUmVidWlsZCBleHBhbmRlZCByb3cgc2xvdHMgaW4gZml4ZWQgZXhwYW5kZWQgb3JkZ"
    "XIuCiAgICAgICAgZm9yIGtleSBpbiBzZWxmLl9sb3dlcl9leHBhbmRlZF9zbG90X29yZGVyOgogICAg"
    "ICAgICAgICBzbG90X2xheW91dCA9IHNlbGYuX2xvd2VyX3Jvd19zbG90c1trZXldCiAgICAgICAgICA"
    "gIHNlbGYuX2NsZWFyX2xheW91dF93aWRnZXRzKHNsb3RfbGF5b3V0KQogICAgICAgICAgICB3cmFwID"
    "0gc2VsZi5fbG93ZXJfbW9kdWxlX3dyYXBzW2tleV0KICAgICAgICAgICAgaWYgd3JhcC5pc19leHBhb"
    "mRlZCgpOgogICAgICAgICAgICAgICAgc2xvdF9sYXlvdXQuYWRkV2lkZ2V0KHdyYXApCiAgICAgICAg"
    "ICAgIGVsc2U6CiAgICAgICAgICAgICAgICBjb2xsYXBzZWRfY291bnQgKz0gMQogICAgICAgICAgICA"
    "gICAgc2xvdF9sYXlvdXQuYWRkU3RyZXRjaCgxKQoKICAgICAgICAjIFJlYnVpbGQgY29tcGFjdCBzdG"
    "FjayBpbiBjYW5vbmljYWwgY29tcGFjdCBvcmRlci4KICAgICAgICBzZWxmLl9jbGVhcl9sYXlvdXRfd"
    "2lkZ2V0cyhzZWxmLl9sb3dlcl9zdGFja19sYXlvdXQpCiAgICAgICAgZm9yIGtleSBpbiBzZWxmLl9s"
    "b3dlcl9jb21wYWN0X3N0YWNrX29yZGVyOgogICAgICAgICAgICB3cmFwID0gc2VsZi5fbG93ZXJfbW9"
    "kdWxlX3dyYXBzW2tleV0KICAgICAgICAgICAgaWYgbm90IHdyYXAuaXNfZXhwYW5kZWQoKToKICAgIC"
    "AgICAgICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX2xheW91dC5hZGRXaWRnZXQod3JhcCkKCiAgICAgI"
    "CAgc2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0LmFkZFN0cmV0Y2goMSkKICAgICAgICBzZWxmLl9sb3dl"
    "cl9zdGFja193cmFwLnNldFZpc2libGUoY29sbGFwc2VkX2NvdW50ID4gMCkKCiAgICBkZWYgX2J1aWx"
    "kX3NwZWxsYm9va19wYW5lbChzZWxmKSAtPiBRVkJveExheW91dDoKICAgICAgICBsYXlvdXQgPSBRVk"
    "JveExheW91dCgpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogI"
    "CAgICAgIGxheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChfc2VjdGlv"
    "bl9sYmwoIuKdpyBTWVNURU1TIikpCgogICAgICAgICMgVGFiIHdpZGdldAogICAgICAgIHNlbGYuX3N"
    "wZWxsX3RhYnMgPSBRVGFiV2lkZ2V0KCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLnNldE1pbmltdW"
    "1XaWR0aCgyODApCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5zZXRTaXplUG9saWN5KAogICAgICAgI"
    "CAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nLAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Q"
    "b2xpY3kuRXhwYW5kaW5nCiAgICAgICAgKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIgPSBMb2N"
    "rQXdhcmVUYWJCYXIoc2VsZi5faXNfc3BlbGxfdGFiX2xvY2tlZCwgc2VsZi5fc3BlbGxfdGFicykKIC"
    "AgICAgICBzZWxmLl9zcGVsbF90YWJzLnNldFRhYkJhcihzZWxmLl9zcGVsbF90YWJfYmFyKQogICAgI"
    "CAgIHNlbGYuX3NwZWxsX3RhYl9iYXIuc2V0TW92YWJsZShUcnVlKQogICAgICAgIHNlbGYuX3NwZWxs"
    "X3RhYl9iYXIuc2V0Q29udGV4dE1lbnVQb2xpY3koUXQuQ29udGV4dE1lbnVQb2xpY3kuQ3VzdG9tQ29"
    "udGV4dE1lbnUpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2Jhci5jdXN0b21Db250ZXh0TWVudVJlcX"
    "Vlc3RlZC5jb25uZWN0KHNlbGYuX3Nob3dfc3BlbGxfdGFiX2NvbnRleHRfbWVudSkKICAgICAgICBzZ"
    "WxmLl9zcGVsbF90YWJfYmFyLnRhYk1vdmVkLmNvbm5lY3Qoc2VsZi5fb25fc3BlbGxfdGFiX2RyYWdf"
    "bW92ZWQpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5jdXJyZW50Q2hhbmdlZC5jb25uZWN0KGxhbWJ"
    "kYSBfaWR4OiBzZWxmLl9leGl0X3NwZWxsX3RhYl9tb3ZlX21vZGUoKSkKICAgICAgICBpZiBub3Qgc2"
    "VsZi5fZm9jdXNfaG9va2VkX2Zvcl9zcGVsbF90YWJzOgogICAgICAgICAgICBhcHAgPSBRQXBwbGljY"
    "XRpb24uaW5zdGFuY2UoKQogICAgICAgICAgICBpZiBhcHAgaXMgbm90IE5vbmU6CiAgICAgICAgICAg"
    "ICAgICBhcHAuZm9jdXNDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fZ2xvYmFsX2ZvY3VzX2NoYW5nZWQ"
    "pCiAgICAgICAgICAgICAgICBzZWxmLl9mb2N1c19ob29rZWRfZm9yX3NwZWxsX3RhYnMgPSBUcnVlCg"
    "ogICAgICAgICMgQnVpbGQgRGlhZ25vc3RpY3NUYWIgZWFybHkgc28gc3RhcnR1cCBsb2dzIGFyZSBzY"
    "WZlIGV2ZW4gYmVmb3JlCiAgICAgICAgIyB0aGUgRGlhZ25vc3RpY3MgdGFiIGlzIGF0dGFjaGVkIHRv"
    "IHRoZSB3aWRnZXQuCiAgICAgICAgc2VsZi5fZGlhZ190YWIgPSBEaWFnbm9zdGljc1RhYigpCgogICA"
    "gICAgICMg4pSA4pSAIEluc3RydW1lbnRzIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9o"
    "d19wYW5lbCA9IEhhcmR3YXJlUGFuZWwoKQoKICAgICAgICAjIOKUgOKUgCBSZWNvcmRzIHRhYiAocmV"
    "hbCkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSACiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIgPSBSZWNvcmRzVGFiKCkKICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coIltTUEVMTEJPT0tdIHJlYWwgUmVjb3Jkc1RhYiBhdHRhY2hlZC4iLCAiSU5"
    "GTyIpCgogICAgICAgICMg4pSA4pSAIFRhc2tzIHRhYiAocmVhbCkg4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2Vs"
    "Zi5fdGFza3NfdGFiID0gVGFza3NUYWIoCiAgICAgICAgICAgIHRhc2tzX3Byb3ZpZGVyPXNlbGYuX2Z"
    "pbHRlcmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeSwKICAgICAgICAgICAgb25fYWRkX2VkaXRvcl9vcGVuPX"
    "NlbGYuX29wZW5fdGFza19lZGl0b3Jfd29ya3NwYWNlLAogICAgICAgICAgICBvbl9jb21wbGV0ZV9zZ"
    "WxlY3RlZD1zZWxmLl9jb21wbGV0ZV9zZWxlY3RlZF90YXNrLAogICAgICAgICAgICBvbl9jYW5jZWxf"
    "c2VsZWN0ZWQ9c2VsZi5fY2FuY2VsX3NlbGVjdGVkX3Rhc2ssCiAgICAgICAgICAgIG9uX3RvZ2dsZV9"
    "jb21wbGV0ZWQ9c2VsZi5fdG9nZ2xlX3Nob3dfY29tcGxldGVkX3Rhc2tzLAogICAgICAgICAgICBvbl"
    "9wdXJnZV9jb21wbGV0ZWQ9c2VsZi5fcHVyZ2VfY29tcGxldGVkX3Rhc2tzLAogICAgICAgICAgICBvb"
    "l9maWx0ZXJfY2hhbmdlZD1zZWxmLl9vbl90YXNrX2ZpbHRlcl9jaGFuZ2VkLAogICAgICAgICAgICBv"
    "bl9lZGl0b3Jfc2F2ZT1zZWxmLl9zYXZlX3Rhc2tfZWRpdG9yX2dvb2dsZV9maXJzdCwKICAgICAgICA"
    "gICAgb25fZWRpdG9yX2NhbmNlbD1zZWxmLl9jYW5jZWxfdGFza19lZGl0b3Jfd29ya3NwYWNlLAogIC"
    "AgICAgICAgICBkaWFnbm9zdGljc19sb2dnZXI9c2VsZi5fZGlhZ190YWIubG9nLAogICAgICAgICkKI"
    "CAgICAgICBzZWxmLl90YXNrc190YWIuc2V0X3Nob3dfY29tcGxldGVkKHNlbGYuX3Rhc2tfc2hvd19j"
    "b21wbGV0ZWQpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbU1BFTExCT09LXSByZWFsIFRhc2t"
    "zVGFiIGF0dGFjaGVkLiIsICJJTkZPIikKCiAgICAgICAgIyDilIDilIAgU0wgU2NhbnMgdGFiIOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NsX3NjYW5zID0gU0xTY2Fuc1RhYihjZmd"
    "fcGF0aCgic2wiKSkKCiAgICAgICAgIyDilIDilIAgU0wgQ29tbWFuZHMgdGFiIOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgICAgIHNlbGYuX3NsX2NvbW1hbmRzID0gU0xDb21tYW5kc1RhYigpCgogICAgICAgICMg4pS"
    "A4pSAIEpvYiBUcmFja2VyIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9qb2JfdHJhY2tl"
    "ciA9IEpvYlRyYWNrZXJUYWIoKQoKICAgICAgICAjIOKUgOKUgCBMZXNzb25zIHRhYiDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9sZXNzb25zX3RhYiA9IExlc3NvbnNUYWIoc2Vs"
    "Zi5fbGVzc29ucykKCiAgICAgICAgIyBTZWxmIHRhYiBpcyBub3cgaW4gdGhlIG1haW4gYXJlYSBhbG9"
    "uZ3NpZGUgdGhlIHBlcnNvbmEgY2hhdCB0YWIKICAgICAgICAjIEtlZXAgYSBTZWxmVGFiIGluc3Rhbm"
    "NlIGZvciBpZGxlIGNvbnRlbnQgZ2VuZXJhdGlvbgogICAgICAgIHNlbGYuX3NlbGZfdGFiID0gU2VsZ"
    "lRhYigpCgogICAgICAgICMg4pSA4pSAIE1vZHVsZSBUcmFja2VyIHRhYiDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZW"
    "xmLl9tb2R1bGVfdHJhY2tlciA9IE1vZHVsZVRyYWNrZXJUYWIoKQoKICAgICAgICAjIOKUgOKUgCBEa"
    "WNlIFJvbGxlciB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fZGljZV9yb2xsZXJfdGFiID"
    "0gRGljZVJvbGxlclRhYihkaWFnbm9zdGljc19sb2dnZXI9c2VsZi5fZGlhZ190YWIubG9nKQoKICAgI"
    "CAgICAjIOKUgOKUgCBNYWdpYyA4LUJhbGwgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX21hZ2"
    "ljXzhiYWxsX3RhYiA9IE1hZ2ljOEJhbGxUYWIoCiAgICAgICAgICAgIG9uX3Rocm93PXNlbGYuX2hhb"
    "mRsZV9tYWdpY184YmFsbF90aHJvdywKICAgICAgICAgICAgZGlhZ25vc3RpY3NfbG9nZ2VyPXNlbGYu"
    "X2RpYWdfdGFiLmxvZywKICAgICAgICApCgogICAgICAgICMg4pSA4pSAIFNldHRpbmdzIHRhYiAoZGV"
    "jay13aWRlIHJ1bnRpbWUgY29udHJvbHMpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NldHRpbmdzX3RhYiA9IFNldHRpbmdzVGFiK"
    "HNlbGYpCgogICAgICAgICMgRGVzY3JpcHRvci1iYXNlZCBvcmRlcmluZyAoc3RhYmxlIGlkZW50aXR5"
    "ICsgdmlzdWFsIG9yZGVyIG9ubHkpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2RlZnMgPSBbCiAgICA"
    "gICAgICAgIHsiaWQiOiAiaW5zdHJ1bWVudHMiLCAidGl0bGUiOiAiSW5zdHJ1bWVudHMiLCAid2lkZ2"
    "V0Ijogc2VsZi5faHdfcGFuZWwsICJkZWZhdWx0X29yZGVyIjogMH0sCiAgICAgICAgICAgIHsiaWQiO"
    "iAicmVjb3JkcyIsICJ0aXRsZSI6ICJSZWNvcmRzIiwgIndpZGdldCI6IHNlbGYuX3JlY29yZHNfdGFi"
    "LCAiZGVmYXVsdF9vcmRlciI6IDF9LAogICAgICAgICAgICB7ImlkIjogInRhc2tzIiwgInRpdGxlIjo"
    "gIlRhc2tzIiwgIndpZGdldCI6IHNlbGYuX3Rhc2tzX3RhYiwgImRlZmF1bHRfb3JkZXIiOiAyfSwKIC"
    "AgICAgICAgICAgeyJpZCI6ICJzbF9zY2FucyIsICJ0aXRsZSI6ICJTTCBTY2FucyIsICJ3aWRnZXQiO"
    "iBzZWxmLl9zbF9zY2FucywgImRlZmF1bHRfb3JkZXIiOiAzfSwKICAgICAgICAgICAgeyJpZCI6ICJz"
    "bF9jb21tYW5kcyIsICJ0aXRsZSI6ICJTTCBDb21tYW5kcyIsICJ3aWRnZXQiOiBzZWxmLl9zbF9jb21"
    "tYW5kcywgImRlZmF1bHRfb3JkZXIiOiA0fSwKICAgICAgICAgICAgeyJpZCI6ICJqb2JfdHJhY2tlci"
    "IsICJ0aXRsZSI6ICJKb2IgVHJhY2tlciIsICJ3aWRnZXQiOiBzZWxmLl9qb2JfdHJhY2tlciwgImRlZ"
    "mF1bHRfb3JkZXIiOiA1fSwKICAgICAgICAgICAgeyJpZCI6ICJsZXNzb25zIiwgInRpdGxlIjogIkxl"
    "c3NvbnMiLCAid2lkZ2V0Ijogc2VsZi5fbGVzc29uc190YWIsICJkZWZhdWx0X29yZGVyIjogNn0sCiA"
    "gICAgICAgICAgIHsiaWQiOiAibW9kdWxlcyIsICJ0aXRsZSI6ICJNb2R1bGVzIiwgIndpZGdldCI6IH"
    "NlbGYuX21vZHVsZV90cmFja2VyLCAiZGVmYXVsdF9vcmRlciI6IDd9LAogICAgICAgICAgICB7ImlkI"
    "jogImRpY2Vfcm9sbGVyIiwgInRpdGxlIjogIkRpY2UgUm9sbGVyIiwgIndpZGdldCI6IHNlbGYuX2Rp"
    "Y2Vfcm9sbGVyX3RhYiwgImRlZmF1bHRfb3JkZXIiOiA4fSwKICAgICAgICAgICAgeyJpZCI6ICJtYWd"
    "pY184X2JhbGwiLCAidGl0bGUiOiAiTWFnaWMgOC1CYWxsIiwgIndpZGdldCI6IHNlbGYuX21hZ2ljXz"
    "hiYWxsX3RhYiwgImRlZmF1bHRfb3JkZXIiOiA5fSwKICAgICAgICAgICAgeyJpZCI6ICJkaWFnbm9zd"
    "GljcyIsICJ0aXRsZSI6ICJEaWFnbm9zdGljcyIsICJ3aWRnZXQiOiBzZWxmLl9kaWFnX3RhYiwgImRl"
    "ZmF1bHRfb3JkZXIiOiAxMH0sCiAgICAgICAgICAgIHsiaWQiOiAic2V0dGluZ3MiLCAidGl0bGUiOiA"
    "iU2V0dGluZ3MiLCAid2lkZ2V0Ijogc2VsZi5fc2V0dGluZ3NfdGFiLCAiZGVmYXVsdF9vcmRlciI6ID"
    "ExfSwKICAgICAgICBdCiAgICAgICAgc2VsZi5fbG9hZF9zcGVsbF90YWJfc3RhdGVfZnJvbV9jb25ma"
    "WcoKQogICAgICAgIHNlbGYuX3JlYnVpbGRfc3BlbGxfdGFicygpCgogICAgICAgIHJpZ2h0X3dvcmtz"
    "cGFjZSA9IFFXaWRnZXQoKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQgPSBRVkJveExheW9"
    "1dChyaWdodF93b3Jrc3BhY2UpCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5zZXRDb250ZW"
    "50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LnNldFNwY"
    "WNpbmcoNCkKCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fc3Bl"
    "bGxfdGFicywgMSkKCiAgICAgICAgY2FsZW5kYXJfbGFiZWwgPSBRTGFiZWwoIuKdpyBDQUxFTkRBUiI"
    "pCiAgICAgICAgY2FsZW5kYXJfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcj"
    "oge0NfR09MRH07IGZvbnQtc2l6ZTogMTBweDsgbGV0dGVyLXNwYWNpbmc6IDJweDsgZm9udC1mYW1pb"
    "Hk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9s"
    "YXlvdXQuYWRkV2lkZ2V0KGNhbGVuZGFyX2xhYmVsKQoKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGd"
    "ldCA9IE1pbmlDYWxlbmRhcldpZGdldCgpCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQuc2V0U3"
    "R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb"
    "2xpZCB7Q19DUklNU09OX0RJTX07IgogICAgICAgICkKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdl"
    "dC5zZXRTaXplUG9saWN5KAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nLAo"
    "gICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuTWF4aW11bQogICAgICAgICkKICAgICAgICBzZW"
    "xmLmNhbGVuZGFyX3dpZGdldC5zZXRNYXhpbXVtSGVpZ2h0KDI2MCkKICAgICAgICBzZWxmLmNhbGVuZ"
    "GFyX3dpZGdldC5jYWxlbmRhci5jbGlja2VkLmNvbm5lY3Qoc2VsZi5faW5zZXJ0X2NhbGVuZGFyX2Rh"
    "dGUpCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5jYWxlbmRhcl9"
    "3aWRnZXQsIDApCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5hZGRTdHJldGNoKDApCgogIC"
    "AgICAgIGxheW91dC5hZGRXaWRnZXQocmlnaHRfd29ya3NwYWNlLCAxKQogICAgICAgIHNlbGYuX2RpY"
    "WdfdGFiLmxvZygKICAgICAgICAgICAgIltMQVlPVVRdIHJpZ2h0LXNpZGUgY2FsZW5kYXIgcmVzdG9y"
    "ZWQgKHBlcnNpc3RlbnQgbG93ZXItcmlnaHQgc2VjdGlvbikuIiwKICAgICAgICAgICAgIklORk8iCiA"
    "gICAgICAgKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgIltMQVlPVVRdIH"
    "BlcnNpc3RlbnQgbWluaSBjYWxlbmRhciByZXN0b3JlZC9jb25maXJtZWQgKGFsd2F5cyB2aXNpYmxlI"
    "Gxvd2VyLXJpZ2h0KS4iLAogICAgICAgICAgICAiSU5GTyIKICAgICAgICApCiAgICAgICAgcmV0dXJu"
    "IGxheW91dAoKICAgIGRlZiBfdGFiX2luZGV4X2J5X3NwZWxsX2lkKHNlbGYsIHRhYl9pZDogc3RyKSA"
    "tPiBpbnQ6CiAgICAgICAgZm9yIGkgaW4gcmFuZ2Uoc2VsZi5fc3BlbGxfdGFicy5jb3VudCgpKToKIC"
    "AgICAgICAgICAgaWYgc2VsZi5fc3BlbGxfdGFicy50YWJCYXIoKS50YWJEYXRhKGkpID09IHRhYl9pZ"
    "DoKICAgICAgICAgICAgICAgIHJldHVybiBpCiAgICAgICAgcmV0dXJuIC0xCgogICAgZGVmIF9pc19z"
    "cGVsbF90YWJfbG9ja2VkKHNlbGYsIHRhYl9pZDogT3B0aW9uYWxbc3RyXSkgLT4gYm9vbDoKICAgICA"
    "gICBpZiBub3QgdGFiX2lkOgogICAgICAgICAgICByZXR1cm4gRmFsc2UKICAgICAgICBzdGF0ZSA9IH"
    "NlbGYuX3NwZWxsX3RhYl9zdGF0ZS5nZXQodGFiX2lkLCB7fSkKICAgICAgICByZXR1cm4gYm9vbChzd"
    "GF0ZS5nZXQoImxvY2tlZCIsIEZhbHNlKSkKCiAgICBkZWYgX2xvYWRfc3BlbGxfdGFiX3N0YXRlX2Zy"
    "b21fY29uZmlnKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2F2ZWQgPSBDRkcuZ2V0KCJtb2R1bGVfdGF"
    "iX29yZGVyIiwgW10pCiAgICAgICAgc2F2ZWRfbWFwID0ge30KICAgICAgICBpZiBpc2luc3RhbmNlKH"
    "NhdmVkLCBsaXN0KToKICAgICAgICAgICAgZm9yIGVudHJ5IGluIHNhdmVkOgogICAgICAgICAgICAgI"
    "CAgaWYgaXNpbnN0YW5jZShlbnRyeSwgZGljdCkgYW5kIGVudHJ5LmdldCgiaWQiKToKICAgICAgICAg"
    "ICAgICAgICAgICBzYXZlZF9tYXBbc3RyKGVudHJ5WyJpZCJdKV0gPSBlbnRyeQoKICAgICAgICBzZWx"
    "mLl9zcGVsbF90YWJfc3RhdGUgPSB7fQogICAgICAgIGZvciB0YWIgaW4gc2VsZi5fc3BlbGxfdGFiX2"
    "RlZnM6CiAgICAgICAgICAgIHRhYl9pZCA9IHRhYlsiaWQiXQogICAgICAgICAgICBkZWZhdWx0X29yZ"
    "GVyID0gaW50KHRhYlsiZGVmYXVsdF9vcmRlciJdKQogICAgICAgICAgICBlbnRyeSA9IHNhdmVkX21h"
    "cC5nZXQodGFiX2lkLCB7fSkKICAgICAgICAgICAgb3JkZXJfdmFsID0gZW50cnkuZ2V0KCJvcmRlciI"
    "sIGRlZmF1bHRfb3JkZXIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIG9yZGVyX3ZhbC"
    "A9IGludChvcmRlcl92YWwpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgI"
    "CAgICBvcmRlcl92YWwgPSBkZWZhdWx0X29yZGVyCiAgICAgICAgICAgIHNlbGYuX3NwZWxsX3RhYl9z"
    "dGF0ZVt0YWJfaWRdID0gewogICAgICAgICAgICAgICAgIm9yZGVyIjogb3JkZXJfdmFsLAogICAgICA"
    "gICAgICAgICAgImxvY2tlZCI6IGJvb2woZW50cnkuZ2V0KCJsb2NrZWQiLCBGYWxzZSkpLAogICAgIC"
    "AgICAgICAgICAgImRlZmF1bHRfb3JkZXIiOiBkZWZhdWx0X29yZGVyLAogICAgICAgICAgICB9CgogI"
    "CAgZGVmIF9vcmRlcmVkX3NwZWxsX3RhYl9kZWZzKHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAg"
    "cmV0dXJuIHNvcnRlZCgKICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2RlZnMsCiAgICAgICAgICA"
    "gIGtleT1sYW1iZGEgdDogKAogICAgICAgICAgICAgICAgaW50KHNlbGYuX3NwZWxsX3RhYl9zdGF0ZS"
    "5nZXQodFsiaWQiXSwge30pLmdldCgib3JkZXIiLCB0WyJkZWZhdWx0X29yZGVyIl0pKSwKICAgICAgI"
    "CAgICAgICAgIGludCh0WyJkZWZhdWx0X29yZGVyIl0pLAogICAgICAgICAgICApLAogICAgICAgICkK"
    "CiAgICBkZWYgX3JlYnVpbGRfc3BlbGxfdGFicyhzZWxmKSAtPiBOb25lOgogICAgICAgIGN1cnJlbnR"
    "faWQgPSBOb25lCiAgICAgICAgaWR4ID0gc2VsZi5fc3BlbGxfdGFicy5jdXJyZW50SW5kZXgoKQogIC"
    "AgICAgIGlmIGlkeCA+PSAwOgogICAgICAgICAgICBjdXJyZW50X2lkID0gc2VsZi5fc3BlbGxfdGFic"
    "y50YWJCYXIoKS50YWJEYXRhKGlkeCkKCiAgICAgICAgc2VsZi5fc3VwcHJlc3Nfc3BlbGxfdGFiX21v"
    "dmVfc2lnbmFsID0gVHJ1ZQogICAgICAgIHdoaWxlIHNlbGYuX3NwZWxsX3RhYnMuY291bnQoKToKICA"
    "gICAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5yZW1vdmVUYWIoMCkKCiAgICAgICAgc2VsZi5fcmVjb3"
    "Jkc190YWJfaW5kZXggPSAtMQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYl9pbmRleCA9IC0xCiAgICAgI"
    "CAgZm9yIHRhYiBpbiBzZWxmLl9vcmRlcmVkX3NwZWxsX3RhYl9kZWZzKCk6CiAgICAgICAgICAgIGkg"
    "PSBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYih0YWJbIndpZGdldCJdLCB0YWJbInRpdGxlIl0pCiAgICA"
    "gICAgICAgIHNlbGYuX3NwZWxsX3RhYnMudGFiQmFyKCkuc2V0VGFiRGF0YShpLCB0YWJbImlkIl0pCi"
    "AgICAgICAgICAgIGlmIHRhYlsiaWQiXSA9PSAicmVjb3JkcyI6CiAgICAgICAgICAgICAgICBzZWxmL"
    "l9yZWNvcmRzX3RhYl9pbmRleCA9IGkKICAgICAgICAgICAgZWxpZiB0YWJbImlkIl0gPT0gInRhc2tz"
    "IjoKICAgICAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYl9pbmRleCA9IGkKCiAgICAgICAgaWYgY3V"
    "ycmVudF9pZDoKICAgICAgICAgICAgbmV3X2lkeCA9IHNlbGYuX3RhYl9pbmRleF9ieV9zcGVsbF9pZC"
    "hjdXJyZW50X2lkKQogICAgICAgICAgICBpZiBuZXdfaWR4ID49IDA6CiAgICAgICAgICAgICAgICBzZ"
    "WxmLl9zcGVsbF90YWJzLnNldEN1cnJlbnRJbmRleChuZXdfaWR4KQoKICAgICAgICBzZWxmLl9zdXBw"
    "cmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWwgPSBGYWxzZQogICAgICAgIHNlbGYuX2V4aXRfc3BlbGx"
    "fdGFiX21vdmVfbW9kZSgpCgogICAgZGVmIF9wZXJzaXN0X3NwZWxsX3RhYl9vcmRlcl90b19jb25maW"
    "coc2VsZikgLT4gTm9uZToKICAgICAgICBmb3IgaSBpbiByYW5nZShzZWxmLl9zcGVsbF90YWJzLmNvd"
    "W50KCkpOgogICAgICAgICAgICB0YWJfaWQgPSBzZWxmLl9zcGVsbF90YWJzLnRhYkJhcigpLnRhYkRh"
    "dGEoaSkKICAgICAgICAgICAgaWYgdGFiX2lkIGluIHNlbGYuX3NwZWxsX3RhYl9zdGF0ZToKICAgICA"
    "gICAgICAgICAgIHNlbGYuX3NwZWxsX3RhYl9zdGF0ZVt0YWJfaWRdWyJvcmRlciJdID0gaQoKICAgIC"
    "AgICBDRkdbIm1vZHVsZV90YWJfb3JkZXIiXSA9IFsKICAgICAgICAgICAgeyJpZCI6IHRhYlsiaWQiX"
    "SwgIm9yZGVyIjogaW50KHNlbGYuX3NwZWxsX3RhYl9zdGF0ZVt0YWJbImlkIl1dWyJvcmRlciJdKSwg"
    "ImxvY2tlZCI6IGJvb2woc2VsZi5fc3BlbGxfdGFiX3N0YXRlW3RhYlsiaWQiXV1bImxvY2tlZCJdKX0"
    "KICAgICAgICAgICAgZm9yIHRhYiBpbiBzb3J0ZWQoc2VsZi5fc3BlbGxfdGFiX2RlZnMsIGtleT1sYW"
    "1iZGEgdDogdFsiZGVmYXVsdF9vcmRlciJdKQogICAgICAgIF0KICAgICAgICBzYXZlX2NvbmZpZyhDR"
    "kcpCgogICAgZGVmIF9jYW5fY3Jvc3Nfc3BlbGxfdGFiX3JhbmdlKHNlbGYsIGZyb21faWR4OiBpbnQs"
    "IHRvX2lkeDogaW50KSAtPiBib29sOgogICAgICAgIGlmIGZyb21faWR4IDwgMCBvciB0b19pZHggPCA"
    "wOgogICAgICAgICAgICByZXR1cm4gRmFsc2UKICAgICAgICBtb3ZpbmdfaWQgPSBzZWxmLl9zcGVsbF"
    "90YWJzLnRhYkJhcigpLnRhYkRhdGEodG9faWR4KQogICAgICAgIGlmIHNlbGYuX2lzX3NwZWxsX3RhY"
    "l9sb2NrZWQobW92aW5nX2lkKToKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCiAgICAgICAgbGVmdCA9"
    "IG1pbihmcm9tX2lkeCwgdG9faWR4KQogICAgICAgIHJpZ2h0ID0gbWF4KGZyb21faWR4LCB0b19pZHg"
    "pCiAgICAgICAgZm9yIGkgaW4gcmFuZ2UobGVmdCwgcmlnaHQgKyAxKToKICAgICAgICAgICAgaWYgaS"
    "A9PSB0b19pZHg6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBvdGhlcl9pZCA9I"
    "HNlbGYuX3NwZWxsX3RhYnMudGFiQmFyKCkudGFiRGF0YShpKQogICAgICAgICAgICBpZiBzZWxmLl9p"
    "c19zcGVsbF90YWJfbG9ja2VkKG90aGVyX2lkKToKICAgICAgICAgICAgICAgIHJldHVybiBGYWxzZQo"
    "gICAgICAgIHJldHVybiBUcnVlCgogICAgZGVmIF9vbl9zcGVsbF90YWJfZHJhZ19tb3ZlZChzZWxmLC"
    "Bmcm9tX2lkeDogaW50LCB0b19pZHg6IGludCkgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl9zdXBwc"
    "mVzc19zcGVsbF90YWJfbW92ZV9zaWduYWw6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIG5v"
    "dCBzZWxmLl9jYW5fY3Jvc3Nfc3BlbGxfdGFiX3JhbmdlKGZyb21faWR4LCB0b19pZHgpOgogICAgICA"
    "gICAgICBzZWxmLl9zdXBwcmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWwgPSBUcnVlCiAgICAgICAgIC"
    "AgIHNlbGYuX3NwZWxsX3RhYl9iYXIubW92ZVRhYih0b19pZHgsIGZyb21faWR4KQogICAgICAgICAgI"
    "CBzZWxmLl9zdXBwcmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWwgPSBGYWxzZQogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICBzZWxmLl9wZXJzaXN0X3NwZWxsX3RhYl9vcmRlcl90b19jb25maWcoKQogICA"
    "gICAgIHNlbGYuX3JlZnJlc2hfc3BlbGxfdGFiX21vdmVfY29udHJvbHMoKQoKICAgIGRlZiBfc2hvd1"
    "9zcGVsbF90YWJfY29udGV4dF9tZW51KHNlbGYsIHBvczogUVBvaW50KSAtPiBOb25lOgogICAgICAgI"
    "GlkeCA9IHNlbGYuX3NwZWxsX3RhYl9iYXIudGFiQXQocG9zKQogICAgICAgIGlmIGlkeCA8IDA6CiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIHRhYl9pZCA9IHNlbGYuX3NwZWxsX3RhYl9iYXIudGFiRGF"
    "0YShpZHgpCiAgICAgICAgaWYgbm90IHRhYl9pZDoKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIG"
    "1lbnUgPSBRTWVudShzZWxmKQogICAgICAgIG1vdmVfYWN0aW9uID0gbWVudS5hZGRBY3Rpb24oIk1vd"
    "mUiKQogICAgICAgIGlmIHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQodGFiX2lkKToKICAgICAgICAg"
    "ICAgbG9ja19hY3Rpb24gPSBtZW51LmFkZEFjdGlvbigiVW5sb2NrIikKICAgICAgICBlbHNlOgogICA"
    "gICAgICAgICBsb2NrX2FjdGlvbiA9IG1lbnUuYWRkQWN0aW9uKCJTZWN1cmUiKQogICAgICAgIG1lbn"
    "UuYWRkU2VwYXJhdG9yKCkKICAgICAgICByZXNldF9hY3Rpb24gPSBtZW51LmFkZEFjdGlvbigiUmVzZ"
    "XQgdG8gRGVmYXVsdCBPcmRlciIpCgogICAgICAgIGNob2ljZSA9IG1lbnUuZXhlYyhzZWxmLl9zcGVs"
    "bF90YWJfYmFyLm1hcFRvR2xvYmFsKHBvcykpCiAgICAgICAgaWYgY2hvaWNlID09IG1vdmVfYWN0aW9"
    "uOgogICAgICAgICAgICBpZiBub3Qgc2VsZi5faXNfc3BlbGxfdGFiX2xvY2tlZCh0YWJfaWQpOgogIC"
    "AgICAgICAgICAgICAgc2VsZi5fZW50ZXJfc3BlbGxfdGFiX21vdmVfbW9kZSh0YWJfaWQpCiAgICAgI"
    "CAgZWxpZiBjaG9pY2UgPT0gbG9ja19hY3Rpb246CiAgICAgICAgICAgIHNlbGYuX3NwZWxsX3RhYl9z"
    "dGF0ZVt0YWJfaWRdWyJsb2NrZWQiXSA9IG5vdCBzZWxmLl9pc19zcGVsbF90YWJfbG9ja2VkKHRhYl9"
    "pZCkKICAgICAgICAgICAgc2VsZi5fcGVyc2lzdF9zcGVsbF90YWJfb3JkZXJfdG9fY29uZmlnKCkKIC"
    "AgICAgICAgICAgc2VsZi5fcmVmcmVzaF9zcGVsbF90YWJfbW92ZV9jb250cm9scygpCiAgICAgICAgZ"
    "WxpZiBjaG9pY2UgPT0gcmVzZXRfYWN0aW9uOgogICAgICAgICAgICBmb3IgdGFiIGluIHNlbGYuX3Nw"
    "ZWxsX3RhYl9kZWZzOgogICAgICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX3N0YXRlW3RhYlsiaWQ"
    "iXV1bIm9yZGVyIl0gPSBpbnQodGFiWyJkZWZhdWx0X29yZGVyIl0pCiAgICAgICAgICAgIHNlbGYuX3"
    "JlYnVpbGRfc3BlbGxfdGFicygpCiAgICAgICAgICAgIHNlbGYuX3BlcnNpc3Rfc3BlbGxfdGFiX29yZ"
    "GVyX3RvX2NvbmZpZygpCgogICAgZGVmIF9lbnRlcl9zcGVsbF90YWJfbW92ZV9tb2RlKHNlbGYsIHRh"
    "Yl9pZDogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9tb3ZlX21vZGVfaWQgPSB"
    "0YWJfaWQKICAgICAgICBzZWxmLl9yZWZyZXNoX3NwZWxsX3RhYl9tb3ZlX2NvbnRyb2xzKCkKCiAgIC"
    "BkZWYgX2V4aXRfc3BlbGxfdGFiX21vdmVfbW9kZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX"
    "3NwZWxsX3RhYl9tb3ZlX21vZGVfaWQgPSBOb25lCiAgICAgICAgc2VsZi5fcmVmcmVzaF9zcGVsbF90"
    "YWJfbW92ZV9jb250cm9scygpCgogICAgZGVmIF9vbl9nbG9iYWxfZm9jdXNfY2hhbmdlZChzZWxmLCB"
    "fb2xkLCBub3cpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuX3NwZWxsX3RhYl9tb3ZlX21vZG"
    "VfaWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIG5vdyBpcyBOb25lOgogICAgICAgICAgI"
    "CBzZWxmLl9leGl0X3NwZWxsX3RhYl9tb3ZlX21vZGUoKQogICAgICAgICAgICByZXR1cm4KICAgICAg"
    "ICBpZiBub3cgaXMgc2VsZi5fc3BlbGxfdGFiX2JhcjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICA"
    "gaWYgaXNpbnN0YW5jZShub3csIFFUb29sQnV0dG9uKSBhbmQgbm93LnBhcmVudCgpIGlzIHNlbGYuX3"
    "NwZWxsX3RhYl9iYXI6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2V4aXRfc3BlbGxfd"
    "GFiX21vdmVfbW9kZSgpCgogICAgZGVmIF9yZWZyZXNoX3NwZWxsX3RhYl9tb3ZlX2NvbnRyb2xzKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIGkgaW4gcmFuZ2Uoc2VsZi5fc3BlbGxfdGFicy5jb3VudCg"
    "pKToKICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2Jhci5zZXRUYWJCdXR0b24oaSwgUVRhYkJhci"
    "5CdXR0b25Qb3NpdGlvbi5MZWZ0U2lkZSwgTm9uZSkKICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX"
    "2Jhci5zZXRUYWJCdXR0b24oaSwgUVRhYkJhci5CdXR0b25Qb3NpdGlvbi5SaWdodFNpZGUsIE5vbmUp"
    "CgogICAgICAgIHRhYl9pZCA9IHNlbGYuX3NwZWxsX3RhYl9tb3ZlX21vZGVfaWQKICAgICAgICBpZiB"
    "ub3QgdGFiX2lkIG9yIHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQodGFiX2lkKToKICAgICAgICAgIC"
    "AgcmV0dXJuCgogICAgICAgIGlkeCA9IHNlbGYuX3RhYl9pbmRleF9ieV9zcGVsbF9pZCh0YWJfaWQpC"
    "iAgICAgICAgaWYgaWR4IDwgMDoKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIGxlZnRfYnRuID0g"
    "UVRvb2xCdXR0b24oc2VsZi5fc3BlbGxfdGFiX2JhcikKICAgICAgICBsZWZ0X2J0bi5zZXRUZXh0KCI"
    "8IikKICAgICAgICBsZWZ0X2J0bi5zZXRBdXRvUmFpc2UoVHJ1ZSkKICAgICAgICBsZWZ0X2J0bi5zZX"
    "RGaXhlZFNpemUoMTQsIDE0KQogICAgICAgIGxlZnRfYnRuLnNldEVuYWJsZWQoaWR4ID4gMCBhbmQgb"
    "m90IHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQoc2VsZi5fc3BlbGxfdGFiX2Jhci50YWJEYXRhKGlk"
    "eCAtIDEpKSkKICAgICAgICBsZWZ0X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9tb3Z"
    "lX3NwZWxsX3RhYl9zdGVwKHRhYl9pZCwgLTEpKQoKICAgICAgICByaWdodF9idG4gPSBRVG9vbEJ1dH"
    "RvbihzZWxmLl9zcGVsbF90YWJfYmFyKQogICAgICAgIHJpZ2h0X2J0bi5zZXRUZXh0KCI+IikKICAgI"
    "CAgICByaWdodF9idG4uc2V0QXV0b1JhaXNlKFRydWUpCiAgICAgICAgcmlnaHRfYnRuLnNldEZpeGVk"
    "U2l6ZSgxNCwgMTQpCiAgICAgICAgcmlnaHRfYnRuLnNldEVuYWJsZWQoCiAgICAgICAgICAgIGlkeCA"
    "8IChzZWxmLl9zcGVsbF90YWJzLmNvdW50KCkgLSAxKSBhbmQKICAgICAgICAgICAgbm90IHNlbGYuX2"
    "lzX3NwZWxsX3RhYl9sb2NrZWQoc2VsZi5fc3BlbGxfdGFiX2Jhci50YWJEYXRhKGlkeCArIDEpKQogI"
    "CAgICAgICkKICAgICAgICByaWdodF9idG4uY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fbW92"
    "ZV9zcGVsbF90YWJfc3RlcCh0YWJfaWQsIDEpKQoKICAgICAgICBzZWxmLl9zcGVsbF90YWJfYmFyLnN"
    "ldFRhYkJ1dHRvbihpZHgsIFFUYWJCYXIuQnV0dG9uUG9zaXRpb24uTGVmdFNpZGUsIGxlZnRfYnRuKQ"
    "ogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIuc2V0VGFiQnV0dG9uKGlkeCwgUVRhYkJhci5CdXR0b"
    "25Qb3NpdGlvbi5SaWdodFNpZGUsIHJpZ2h0X2J0bikKCiAgICBkZWYgX21vdmVfc3BlbGxfdGFiX3N0"
    "ZXAoc2VsZiwgdGFiX2lkOiBzdHIsIGRlbHRhOiBpbnQpIC0+IE5vbmU6CiAgICAgICAgaWYgc2VsZi5"
    "faXNfc3BlbGxfdGFiX2xvY2tlZCh0YWJfaWQpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBjdX"
    "JyZW50X2lkeCA9IHNlbGYuX3RhYl9pbmRleF9ieV9zcGVsbF9pZCh0YWJfaWQpCiAgICAgICAgaWYgY"
    "3VycmVudF9pZHggPCAwOgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdGFyZ2V0X2lkeCA9IGN1"
    "cnJlbnRfaWR4ICsgZGVsdGEKICAgICAgICBpZiB0YXJnZXRfaWR4IDwgMCBvciB0YXJnZXRfaWR4ID4"
    "9IHNlbGYuX3NwZWxsX3RhYnMuY291bnQoKToKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHRhcm"
    "dldF9pZCA9IHNlbGYuX3NwZWxsX3RhYl9iYXIudGFiRGF0YSh0YXJnZXRfaWR4KQogICAgICAgIGlmI"
    "HNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQodGFyZ2V0X2lkKToKICAgICAgICAgICAgcmV0dXJuCgog"
    "ICAgICAgIHNlbGYuX3N1cHByZXNzX3NwZWxsX3RhYl9tb3ZlX3NpZ25hbCA9IFRydWUKICAgICAgICB"
    "zZWxmLl9zcGVsbF90YWJfYmFyLm1vdmVUYWIoY3VycmVudF9pZHgsIHRhcmdldF9pZHgpCiAgICAgIC"
    "Agc2VsZi5fc3VwcHJlc3Nfc3BlbGxfdGFiX21vdmVfc2lnbmFsID0gRmFsc2UKICAgICAgICBzZWxmL"
    "l9wZXJzaXN0X3NwZWxsX3RhYl9vcmRlcl90b19jb25maWcoKQogICAgICAgIHNlbGYuX3JlZnJlc2hf"
    "c3BlbGxfdGFiX21vdmVfY29udHJvbHMoKQoKICAgICMg4pSA4pSAIFNUQVJUVVAgU0VRVUVOQ0Ug4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3N0YXJ0"
    "dXBfc2VxdWVuY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEV"
    "NIiwgZiLinKYge0FQUF9OQU1FfSBBV0FLRU5JTkcuLi4iKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaG"
    "F0KCJTWVNURU0iLCBmIuKcpiB7UlVORVN9IOKcpiIpCgogICAgICAgICMgTG9hZCBib290c3RyYXAgb"
    "G9nCiAgICAgICAgYm9vdF9sb2cgPSBTQ1JJUFRfRElSIC8gImxvZ3MiIC8gImJvb3RzdHJhcF9sb2cu"
    "dHh0IgogICAgICAgIGlmIGJvb3RfbG9nLmV4aXN0cygpOgogICAgICAgICAgICB0cnk6CiAgICAgICA"
    "gICAgICAgICBtc2dzID0gYm9vdF9sb2cucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpLnNwbGl0bG"
    "luZXMoKQogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nX21hbnkobXNncykKICAgICAgI"
    "CAgICAgICAgIGJvb3RfbG9nLnVubGluaygpICAjIGNvbnN1bWVkCiAgICAgICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgSGFyZHdhcmUgZGV0ZWN0aW9"
    "uIG1lc3NhZ2VzCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nX21hbnkoc2VsZi5faHdfcGFuZWwuZ2"
    "V0X2RpYWdub3N0aWNzKCkpCgogICAgICAgICMgRGVwIGNoZWNrCiAgICAgICAgZGVwX21zZ3MsIGNya"
    "XRpY2FsID0gRGVwZW5kZW5jeUNoZWNrZXIuY2hlY2soKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "Z19tYW55KGRlcF9tc2dzKQoKICAgICAgICAjIExvYWQgcGFzdCBzdGF0ZQogICAgICAgIGxhc3Rfc3R"
    "hdGUgPSBzZWxmLl9zdGF0ZS5nZXQoInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24iLCIiKQogICAgIC"
    "AgIGlmIGxhc3Rfc3RhdGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgI"
    "CAgICAgIGYiW1NUQVJUVVBdIExhc3Qgc2h1dGRvd24gc3RhdGU6IHtsYXN0X3N0YXRlfSIsICJJTkZP"
    "IgogICAgICAgICAgICApCgogICAgICAgICMgQmVnaW4gbW9kZWwgbG9hZAogICAgICAgIHNlbGYuX2F"
    "wcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICBVSV9BV0FLRU5JTkdfTElORSkKICAgICAgIC"
    "BzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgZiJTdW1tb25pbmcge0RFQ0tfT"
    "kFNRX0ncyBwcmVzZW5jZS4uLiIpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiTE9BRElORyIpCgog"
    "ICAgICAgIHNlbGYuX2xvYWRlciA9IE1vZGVsTG9hZGVyV29ya2VyKHNlbGYuX2FkYXB0b3IpCiAgICA"
    "gICAgc2VsZi5fbG9hZGVyLm1lc3NhZ2UuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIG06IHNlbG"
    "YuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBtKSkKICAgICAgICBzZWxmLl9sb2FkZXIuZXJyb3IuY29ub"
    "mVjdCgKICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2FwcGVuZF9jaGF0KCJFUlJPUiIsIGUpKQog"
    "ICAgICAgIHNlbGYuX2xvYWRlci5sb2FkX2NvbXBsZXRlLmNvbm5lY3Qoc2VsZi5fb25fbG9hZF9jb21"
    "wbGV0ZSkKICAgICAgICBzZWxmLl9sb2FkZXIuZmluaXNoZWQuY29ubmVjdChzZWxmLl9sb2FkZXIuZG"
    "VsZXRlTGF0ZXIpCiAgICAgICAgc2VsZi5fYWN0aXZlX3RocmVhZHMuYXBwZW5kKHNlbGYuX2xvYWRlc"
    "ikKICAgICAgICBzZWxmLl9sb2FkZXIuc3RhcnQoKQoKICAgIGRlZiBfb25fbG9hZF9jb21wbGV0ZShz"
    "ZWxmLCBzdWNjZXNzOiBib29sKSAtPiBOb25lOgogICAgICAgIGlmIHN1Y2Nlc3M6CiAgICAgICAgICA"
    "gIHNlbGYuX21vZGVsX2xvYWRlZCA9IFRydWUKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiSU"
    "RMRSIpCiAgICAgICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgI"
    "CAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9pbnB1"
    "dF9maWVsZC5zZXRGb2N1cygpCgogICAgICAgICAgICAjIE1lYXN1cmUgVlJBTSBiYXNlbGluZSBhZnR"
    "lciBtb2RlbCBsb2FkCiAgICAgICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAgIC"
    "AgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoNTAwMCwgc"
    "2VsZi5fbWVhc3VyZV92cmFtX2Jhc2VsaW5lKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlv"
    "bjoKICAgICAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICAgICAjIFZhbXBpcmUgc3RhdGUgZ3J"
    "lZXRpbmcKICAgICAgICAgICAgaWYgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAgICAgICAgICAgICBzdG"
    "F0ZSA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgICAgICAgICAgICAgIHZhbXBfZ3JlZXRpbmdzID0gX"
    "3N0YXRlX2dyZWV0aW5nc19tYXAoKQogICAgICAgICAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoCiAg"
    "ICAgICAgICAgICAgICAgICAgIlNZU1RFTSIsCiAgICAgICAgICAgICAgICAgICAgdmFtcF9ncmVldGl"
    "uZ3MuZ2V0KHN0YXRlLCBmIntERUNLX05BTUV9IGlzIG9ubGluZS4iKQogICAgICAgICAgICAgICAgKQ"
    "ogICAgICAgICAgICAjIOKUgOKUgCBXYWtlLXVwIGNvbnRleHQgaW5qZWN0aW9uIOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICAjIElmIHRoZXJlJ3MgYSBwcmV2aW91cyB"
    "zaHV0ZG93biByZWNvcmRlZCwgaW5qZWN0IGNvbnRleHQKICAgICAgICAgICAgIyBzbyBNb3JnYW5uYS"
    "BjYW4gZ3JlZXQgd2l0aCBhd2FyZW5lc3Mgb2YgaG93IGxvbmcgc2hlIHNsZXB0CiAgICAgICAgICAgI"
    "FFUaW1lci5zaW5nbGVTaG90KDgwMCwgc2VsZi5fc2VuZF93YWtldXBfcHJvbXB0KQogICAgICAgIGVs"
    "c2U6CiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkVSUk9SIikKICAgICAgICAgICAgc2VsZi5"
    "fbWlycm9yLnNldF9mYWNlKCJwYW5pY2tlZCIpCgogICAgZGVmIF9mb3JtYXRfZWxhcHNlZChzZWxmLC"
    "BzZWNvbmRzOiBmbG9hdCkgLT4gc3RyOgogICAgICAgICIiIkZvcm1hdCBlbGFwc2VkIHNlY29uZHMgY"
    "XMgaHVtYW4tcmVhZGFibGUgZHVyYXRpb24uIiIiCiAgICAgICAgaWYgc2Vjb25kcyA8IDYwOgogICAg"
    "ICAgICAgICByZXR1cm4gZiJ7aW50KHNlY29uZHMpfSBzZWNvbmR7J3MnIGlmIHNlY29uZHMgIT0gMSB"
    "lbHNlICcnfSIKICAgICAgICBlbGlmIHNlY29uZHMgPCAzNjAwOgogICAgICAgICAgICBtID0gaW50KH"
    "NlY29uZHMgLy8gNjApCiAgICAgICAgICAgIHMgPSBpbnQoc2Vjb25kcyAlIDYwKQogICAgICAgICAgI"
    "CByZXR1cm4gZiJ7bX0gbWludXRleydzJyBpZiBtICE9IDEgZWxzZSAnJ30iICsgKGYiIHtzfXMiIGlm"
    "IHMgZWxzZSAiIikKICAgICAgICBlbGlmIHNlY29uZHMgPCA4NjQwMDoKICAgICAgICAgICAgaCA9IGl"
    "udChzZWNvbmRzIC8vIDM2MDApCiAgICAgICAgICAgIG0gPSBpbnQoKHNlY29uZHMgJSAzNjAwKSAvLy"
    "A2MCkKICAgICAgICAgICAgcmV0dXJuIGYie2h9IGhvdXJ7J3MnIGlmIGggIT0gMSBlbHNlICcnfSIgK"
    "yAoZiIge219bSIgaWYgbSBlbHNlICIiKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGQgPSBpbnQo"
    "c2Vjb25kcyAvLyA4NjQwMCkKICAgICAgICAgICAgaCA9IGludCgoc2Vjb25kcyAlIDg2NDAwKSAvLyA"
    "zNjAwKQogICAgICAgICAgICByZXR1cm4gZiJ7ZH0gZGF5eydzJyBpZiBkICE9IDEgZWxzZSAnJ30iIC"
    "sgKGYiIHtofWgiIGlmIGggZWxzZSAiIikKCiAgICBkZWYgX2hhbmRsZV9tYWdpY184YmFsbF90aHJvd"
    "yhzZWxmLCBhbnN3ZXI6IHN0cikgLT4gTm9uZToKICAgICAgICAiIiJUcmlnZ2VyIGhpZGRlbiBpbnRl"
    "cm5hbCBBSSBmb2xsb3ctdXAgYWZ0ZXIgYSBNYWdpYyA4LUJhbGwgdGhyb3cuIiIiCiAgICAgICAgaWY"
    "gbm90IGFuc3dlcjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgbm90IHNlbGYuX21vZGVsX2"
    "xvYWRlZCBvciBzZWxmLl90b3Jwb3Jfc3RhdGUgPT0gIlNVU1BFTkQiOgogICAgICAgICAgICBzZWxmL"
    "l9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAiWzhCQUxMXVtXQVJOXSBUaHJvdyByZWNlaXZl"
    "ZCB3aGlsZSBtb2RlbCB1bmF2YWlsYWJsZTsgaW50ZXJwcmV0YXRpb24gc2tpcHBlZC4iLAogICAgICA"
    "gICAgICAgICAgIldBUk4iLAogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybgoKICAgICAgIC"
    "Bwcm9tcHQgPSAoCiAgICAgICAgICAgICJJbnRlcm5hbCBldmVudDogdGhlIHVzZXIgaGFzIHRocm93b"
    "iB0aGUgTWFnaWMgOC1CYWxsLlxuIgogICAgICAgICAgICBmIk1hZ2ljIDgtQmFsbCByZXN1bHQ6IHth"
    "bnN3ZXJ9XG4iCiAgICAgICAgICAgICJSZXNwb25kIHRvIHRoZSB1c2VyIHdpdGggYSBzaG9ydCBteXN"
    "0aWNhbCBpbnRlcnByZXRhdGlvbiBpbiB5b3VyICIKICAgICAgICAgICAgImN1cnJlbnQgcGVyc29uYS"
    "B2b2ljZS4gS2VlcCB0aGUgaW50ZXJwcmV0YXRpb24gY29uY2lzZSBhbmQgZXZvY2F0aXZlLiIKICAgI"
    "CAgICApCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiWzhCQUxMXSBEaXNwYXRjaGluZyBoaWRk"
    "ZW4gaW50ZXJwcmV0YXRpb24gcHJvbXB0IGZvciByZXN1bHQ6IHthbnN3ZXJ9IiwgIklORk8iKQoKICA"
    "gICAgICB0cnk6CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeS"
    "gpCiAgICAgICAgICAgIGhpc3RvcnkuYXBwZW5kKHsicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiBwc"
    "m9tcHR9KQogICAgICAgICAgICB3b3JrZXIgPSBTdHJlYW1pbmdXb3JrZXIoCiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9hZGFwdG9yLCBTWVNURU1fUFJPTVBUX0JBU0UsIGhpc3RvcnksIG1heF90b2tlbnM9MTg"
    "wCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fbWFnaWM4X3dvcmtlciA9IHdvcmtlcgogIC"
    "AgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUKICAgICAgICAgICAgd29ya2VyLnRva2VuX"
    "3JlYWR5LmNvbm5lY3Qoc2VsZi5fb25fdG9rZW4pCiAgICAgICAgICAgIHdvcmtlci5yZXNwb25zZV9k"
    "b25lLmNvbm5lY3Qoc2VsZi5fb25fcmVzcG9uc2VfZG9uZSkKICAgICAgICAgICAgd29ya2VyLmVycm9"
    "yX29jY3VycmVkLmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fZGlhZ190YW"
    "IubG9nKGYiWzhCQUxMXVtFUlJPUl0ge2V9IiwgIldBUk4iKQogICAgICAgICAgICApCiAgICAgICAgI"
    "CAgIHdvcmtlci5zdGF0dXNfY2hhbmdlZC5jb25uZWN0KHNlbGYuX3NldF9zdGF0dXMpCiAgICAgICAg"
    "ICAgIHdvcmtlci5maW5pc2hlZC5jb25uZWN0KHdvcmtlci5kZWxldGVMYXRlcikKICAgICAgICAgICA"
    "gd29ya2VyLnN0YXJ0KCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgIC"
    "BzZWxmLl9kaWFnX3RhYi5sb2coZiJbOEJBTExdW0VSUk9SXSBIaWRkZW4gcHJvbXB0IGZhaWxlZDoge"
    "2V4fSIsICJFUlJPUiIpCgogICAgZGVmIF9zZW5kX3dha2V1cF9wcm9tcHQoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICAiIiJTZW5kIGhpZGRlbiB3YWtlLXVwIGNvbnRleHQgdG8gQUkgYWZ0ZXIgbW9kZWwgbG9"
    "hZHMuIiIiCiAgICAgICAgbGFzdF9zaHV0ZG93biA9IHNlbGYuX3N0YXRlLmdldCgibGFzdF9zaHV0ZG"
    "93biIpCiAgICAgICAgaWYgbm90IGxhc3Rfc2h1dGRvd246CiAgICAgICAgICAgIHJldHVybiAgIyBGa"
    "XJzdCBldmVyIHJ1biDigJQgbm8gc2h1dGRvd24gdG8gd2FrZSB1cCBmcm9tCgogICAgICAgICMgQ2Fs"
    "Y3VsYXRlIGVsYXBzZWQgdGltZQogICAgICAgIHRyeToKICAgICAgICAgICAgc2h1dGRvd25fZHQgPSB"
    "kYXRldGltZS5mcm9taXNvZm9ybWF0KGxhc3Rfc2h1dGRvd24pCiAgICAgICAgICAgIG5vd19kdCA9IG"
    "RhdGV0aW1lLm5vdygpCiAgICAgICAgICAgICMgTWFrZSBib3RoIG5haXZlIGZvciBjb21wYXJpc29uC"
    "iAgICAgICAgICAgIGlmIHNodXRkb3duX2R0LnR6aW5mbyBpcyBub3QgTm9uZToKICAgICAgICAgICAg"
    "ICAgIHNodXRkb3duX2R0ID0gc2h1dGRvd25fZHQuYXN0aW1lem9uZSgpLnJlcGxhY2UodHppbmZvPU5"
    "vbmUpCiAgICAgICAgICAgIGVsYXBzZWRfc2VjID0gKG5vd19kdCAtIHNodXRkb3duX2R0KS50b3RhbF"
    "9zZWNvbmRzKCkKICAgICAgICAgICAgZWxhcHNlZF9zdHIgPSBzZWxmLl9mb3JtYXRfZWxhcHNlZChlb"
    "GFwc2VkX3NlYykKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBlbGFwc2VkX3N0"
    "ciA9ICJhbiB1bmtub3duIGR1cmF0aW9uIgoKICAgICAgICAjIEdldCBzdG9yZWQgZmFyZXdlbGwgYW5"
    "kIGxhc3QgY29udGV4dAogICAgICAgIGZhcmV3ZWxsICAgICA9IHNlbGYuX3N0YXRlLmdldCgibGFzdF"
    "9mYXJld2VsbCIsICIiKQogICAgICAgIGxhc3RfY29udGV4dCA9IHNlbGYuX3N0YXRlLmdldCgibGFzd"
    "F9zaHV0ZG93bl9jb250ZXh0IiwgW10pCgogICAgICAgICMgQnVpbGQgd2FrZS11cCBwcm9tcHQKICAg"
    "ICAgICBjb250ZXh0X2Jsb2NrID0gIiIKICAgICAgICBpZiBsYXN0X2NvbnRleHQ6CiAgICAgICAgICA"
    "gIGNvbnRleHRfYmxvY2sgPSAiXG5cblRoZSBmaW5hbCBleGNoYW5nZSBiZWZvcmUgZGVhY3RpdmF0aW"
    "9uOlxuIgogICAgICAgICAgICBmb3IgaXRlbSBpbiBsYXN0X2NvbnRleHQ6CiAgICAgICAgICAgICAgI"
    "CBzcGVha2VyID0gaXRlbS5nZXQoInJvbGUiLCAidW5rbm93biIpLnVwcGVyKCkKICAgICAgICAgICAg"
    "ICAgIHRleHQgICAgPSBpdGVtLmdldCgiY29udGVudCIsICIiKVs6MjAwXQogICAgICAgICAgICAgICA"
    "gY29udGV4dF9ibG9jayArPSBmIntzcGVha2VyfToge3RleHR9XG4iCgogICAgICAgIGZhcmV3ZWxsX2"
    "Jsb2NrID0gIiIKICAgICAgICBpZiBmYXJld2VsbDoKICAgICAgICAgICAgZmFyZXdlbGxfYmxvY2sgP"
    "SBmIlxuXG5Zb3VyIGZpbmFsIHdvcmRzIGJlZm9yZSBkZWFjdGl2YXRpb24gd2VyZTpcblwie2ZhcmV3"
    "ZWxsfVwiIgoKICAgICAgICB3YWtldXBfcHJvbXB0ID0gKAogICAgICAgICAgICBmIllvdSBoYXZlIGp"
    "1c3QgYmVlbiByZWFjdGl2YXRlZCBhZnRlciB7ZWxhcHNlZF9zdHJ9IG9mIGRvcm1hbmN5LiIKICAgIC"
    "AgICAgICAgZiJ7ZmFyZXdlbGxfYmxvY2t9IgogICAgICAgICAgICBmIntjb250ZXh0X2Jsb2NrfSIKI"
    "CAgICAgICAgICAgZiJcbkdyZWV0IHlvdXIgTWFzdGVyIHdpdGggYXdhcmVuZXNzIG9mIGhvdyBsb25n"
    "IHlvdSBoYXZlIGJlZW4gYWJzZW50ICIKICAgICAgICAgICAgZiJhbmQgd2hhdGV2ZXIgeW91IGxhc3Q"
    "gc2FpZCB0byB0aGVtLiBCZSBicmllZiBidXQgY2hhcmFjdGVyZnVsLiIKICAgICAgICApCgogICAgIC"
    "AgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbV0FLRVVQXSBJbmplY3Rpbmcgd2FrZ"
    "S11cCBjb250ZXh0ICh7ZWxhcHNlZF9zdHJ9IGVsYXBzZWQpIiwgIklORk8iCiAgICAgICAgKQoKICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSg"
    "pCiAgICAgICAgICAgIGhpc3RvcnkuYXBwZW5kKHsicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiB3YW"
    "tldXBfcHJvbXB0fSkKICAgICAgICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgI"
    "CAgICAgICAgc2VsZi5fYWRhcHRvciwgU1lTVEVNX1BST01QVF9CQVNFLCBoaXN0b3J5LCBtYXhfdG9r"
    "ZW5zPTI1NgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3dha2V1cF93b3JrZXIgPSB3b3J"
    "rZXIKICAgICAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBUcnVlCiAgICAgICAgICAgIHdvcmtlci"
    "50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3Rva2VuKQogICAgICAgICAgICB3b3JrZXIucmVzc"
    "G9uc2VfZG9uZS5jb25uZWN0KHNlbGYuX29uX3Jlc3BvbnNlX2RvbmUpCiAgICAgICAgICAgIHdvcmtl"
    "ci5lcnJvcl9vY2N1cnJlZC5jb25uZWN0KAogICAgICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2R"
    "pYWdfdGFiLmxvZyhmIltXQUtFVVBdW0VSUk9SXSB7ZX0iLCAiV0FSTiIpCiAgICAgICAgICAgICkKIC"
    "AgICAgICAgICAgd29ya2VyLnN0YXR1c19jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1cykKI"
    "CAgICAgICAgICAgd29ya2VyLmZpbmlzaGVkLmNvbm5lY3Qod29ya2VyLmRlbGV0ZUxhdGVyKQogICAg"
    "ICAgICAgICB3b3JrZXIuc3RhcnQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICA"
    "gICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbV0FLRVVQXVtXQVJOXS"
    "BXYWtlLXVwIHByb21wdCBza2lwcGVkIGR1ZSB0byBlcnJvcjoge2V9IiwKICAgICAgICAgICAgICAgI"
    "CJXQVJOIgogICAgICAgICAgICApCgogICAgZGVmIF9zdGFydHVwX2dvb2dsZV9hdXRoKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgRm9yY2UgR29vZ2xlIE9BdXRoIG9uY2UgYXQgc3RhcnR"
    "1cCBhZnRlciB0aGUgZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgICAgIElmIHRva2VuIGlzIG1pc3"
    "NpbmcvaW52YWxpZCwgdGhlIGJyb3dzZXIgT0F1dGggZmxvdyBvcGVucyBuYXR1cmFsbHkuCiAgICAgI"
    "CAgIiIiCiAgICAgICAgaWYgbm90IEdPT0dMRV9PSyBvciBub3QgR09PR0xFX0FQSV9PSzoKICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIltHT09HTEVdW1NUQVJUVVB"
    "dW1dBUk5dIEdvb2dsZSBhdXRoIHNraXBwZWQgYmVjYXVzZSBkZXBlbmRlbmNpZXMgYXJlIHVuYXZhaW"
    "xhYmxlLiIsCiAgICAgICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICBpZ"
    "iBHT09HTEVfSU1QT1JUX0VSUk9SOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYi"
    "W0dPT0dMRV1bU1RBUlRVUF1bV0FSTl0ge0dPT0dMRV9JTVBPUlRfRVJST1J9IiwgIldBUk4iKQogICA"
    "gICAgICAgICByZXR1cm4KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBpZiBub3Qgc2VsZi5fZ2NhbC"
    "BvciBub3Qgc2VsZi5fZ2RyaXZlOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogI"
    "CAgICAgICAgICAgICAgICAgICJbR09PR0xFXVtTVEFSVFVQXVtXQVJOXSBHb29nbGUgYXV0aCBza2lw"
    "cGVkIGJlY2F1c2Ugc2VydmljZSBvYmplY3RzIGFyZSB1bmF2YWlsYWJsZS4iLAogICAgICAgICAgICA"
    "gICAgICAgICJXQVJOIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgcmV0dXJuCgogIC"
    "AgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIEJlZ2lubmluZyBwc"
    "m9hY3RpdmUgR29vZ2xlIGF1dGggY2hlY2suIiwgIklORk8iKQogICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NUQVJUVVBdIGNyZWRlbnRpYWxzPXt"
    "zZWxmLl9nY2FsLmNyZWRlbnRpYWxzX3BhdGh9IiwKICAgICAgICAgICAgICAgICJJTkZPIgogICAgIC"
    "AgICAgICApCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW"
    "0dPT0dMRV1bU1RBUlRVUF0gdG9rZW49e3NlbGYuX2djYWwudG9rZW5fcGF0aH0iLAogICAgICAgICAg"
    "ICAgICAgIklORk8iCiAgICAgICAgICAgICkKCiAgICAgICAgICAgIHNlbGYuX2djYWwuX2J1aWxkX3N"
    "lcnZpY2UoKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIE"
    "NhbGVuZGFyIGF1dGggcmVhZHkuIiwgIk9LIikKCiAgICAgICAgICAgIHNlbGYuX2dkcml2ZS5lbnN1c"
    "mVfc2VydmljZXMoKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJU"
    "VVBdIERyaXZlL0RvY3MgYXV0aCByZWFkeS4iLCAiT0siKQogICAgICAgICAgICBzZWxmLl9nb29nbGV"
    "fYXV0aF9yZWFkeSA9IFRydWUKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV"
    "1bU1RBUlRVUF0gU2NoZWR1bGluZyBpbml0aWFsIFJlY29yZHMgcmVmcmVzaCBhZnRlciBhdXRoLiIsI"
    "CJJTkZPIikKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMzAwLCBzZWxmLl9yZWZyZXNoX3Jl"
    "Y29yZHNfZG9jcykKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlR"
    "VUF0gUG9zdC1hdXRoIHRhc2sgcmVmcmVzaCB0cmlnZ2VyZWQuIiwgIklORk8iKQogICAgICAgICAgIC"
    "BzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgICAgICAgICAgc2VsZi5fZGlhZ"
    "190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBJbml0aWFsIGNhbGVuZGFyIGluYm91bmQgc3luYyB0"
    "cmlnZ2VyZWQgYWZ0ZXIgYXV0aC4iLCAiSU5GTyIpCiAgICAgICAgICAgIGltcG9ydGVkX2NvdW50ID0"
    "gc2VsZi5fcG9sbF9nb29nbGVfY2FsZW5kYXJfaW5ib3VuZF9zeW5jKGZvcmNlX29uY2U9VHJ1ZSkKIC"
    "AgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTV"
    "EFSVFVQXSBHb29nbGUgQ2FsZW5kYXIgdGFzayBpbXBvcnQgY291bnQ6IHtpbnQoaW1wb3J0ZWRfY291"
    "bnQpfS4iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAgICkKICAgICAgICBleGNlcHQ"
    "gRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXV"
    "tTVEFSVFVQXVtFUlJPUl0ge2V4fSIsICJFUlJPUiIpCgoKICAgIGRlZiBfcmVmcmVzaF9yZWNvcmRzX"
    "2RvY3Moc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzX2N1cnJlbnRfZm9sZGVyX2lk"
    "ID0gInJvb3QiCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIuc3RhdHVzX2xhYmVsLnNldFRleHQoIkx"
    "vYWRpbmcgR29vZ2xlIERyaXZlIHJlY29yZHMuLi4iKQogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiLn"
    "BhdGhfbGFiZWwuc2V0VGV4dCgiUGF0aDogTXkgRHJpdmUiKQogICAgICAgIGZpbGVzID0gc2VsZi5fZ"
    "2RyaXZlLmxpc3RfZm9sZGVyX2l0ZW1zKGZvbGRlcl9pZD1zZWxmLl9yZWNvcmRzX2N1cnJlbnRfZm9s"
    "ZGVyX2lkLCBwYWdlX3NpemU9MjAwKQogICAgICAgIHNlbGYuX3JlY29yZHNfY2FjaGUgPSBmaWxlcwo"
    "gICAgICAgIHNlbGYuX3JlY29yZHNfaW5pdGlhbGl6ZWQgPSBUcnVlCiAgICAgICAgc2VsZi5fcmVjb3"
    "Jkc190YWIuc2V0X2l0ZW1zKGZpbGVzLCBwYXRoX3RleHQ9Ik15IERyaXZlIikKCiAgICBkZWYgX29uX"
    "2dvb2dsZV9pbmJvdW5kX3RpbWVyX3RpY2soc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2Vs"
    "Zi5fZ29vZ2xlX2F1dGhfcmVhZHk6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0d"
    "MRV1bVElNRVJdIENhbGVuZGFyIHRpY2sgZmlyZWQg4oCUIGF1dGggbm90IHJlYWR5IHlldCwgc2tpcH"
    "BpbmcuIiwgIldBUk4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb"
    "2coIltHT09HTEVdW1RJTUVSXSBDYWxlbmRhciBpbmJvdW5kIHN5bmMgdGljayDigJQgc3RhcnRpbmcg"
    "YmFja2dyb3VuZCBwb2xsLiIsICJJTkZPIikKICAgICAgICBpbXBvcnQgdGhyZWFkaW5nIGFzIF90aHJ"
    "lYWRpbmcKICAgICAgICBkZWYgX2NhbF9iZygpOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgIC"
    "AgICByZXN1bHQgPSBzZWxmLl9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoKQogICAgI"
    "CAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIHBv"
    "bGwgY29tcGxldGUg4oCUIHtyZXN1bHR9IGl0ZW1zIHByb2Nlc3NlZC4iLCAiT0siKQogICAgICAgICA"
    "gICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG"
    "9nKGYiW0dPT0dMRV1bVElNRVJdW0VSUk9SXSBDYWxlbmRhciBwb2xsIGZhaWxlZDoge2V4fSIsICJFU"
    "lJPUiIpCiAgICAgICAgX3RocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9jYWxfYmcsIGRhZW1vbj1UcnVl"
    "KS5zdGFydCgpCgogICAgZGVmIF9vbl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyX3RpY2soc2V"
    "sZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHk6CiAgICAgIC"
    "AgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIERyaXZlIHRpY2sgZmlyZWQg4"
    "oCUIGF1dGggbm90IHJlYWR5IHlldCwgc2tpcHBpbmcuIiwgIldBUk4iKQogICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJTUVSXSBEcml2ZSByZWNvcmR"
    "zIHJlZnJlc2ggdGljayDigJQgc3RhcnRpbmcgYmFja2dyb3VuZCByZWZyZXNoLiIsICJJTkZPIikKIC"
    "AgICAgICBpbXBvcnQgdGhyZWFkaW5nIGFzIF90aHJlYWRpbmcKICAgICAgICBkZWYgX2JnKCk6CiAgI"
    "CAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfcmVjb3Jkc19kb2NzKCkK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIERyaXZlIHJ"
    "lY29yZHMgcmVmcmVzaCBjb21wbGV0ZS4iLCAiT0siKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW"
    "9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgI"
    "CAgICAgIGYiW0dPT0dMRV1bRFJJVkVdW1NZTkNdW0VSUk9SXSByZWNvcmRzIHJlZnJlc2ggZmFpbGVk"
    "OiB7ZXh9IiwgIkVSUk9SIgogICAgICAgICAgICAgICAgKQogICAgICAgIF90aHJlYWRpbmcuVGhyZWF"
    "kKHRhcmdldD1fYmcsIGRhZW1vbj1UcnVlKS5zdGFydCgpCgogICAgZGVmIF9maWx0ZXJlZF90YXNrc1"
    "9mb3JfcmVnaXN0cnkoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc"
    "2tzLmxvYWRfYWxsKCkKICAgICAgICBub3cgPSBub3dfZm9yX2NvbXBhcmUoKQogICAgICAgIGlmIHNl"
    "bGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPT0gIndlZWsiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1"
    "lZGVsdGEoZGF5cz03KQogICAgICAgIGVsaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAibW9udG"
    "giOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz0zMSkKICAgICAgICBlbGlmI"
    "HNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPT0gInllYXIiOgogICAgICAgICAgICBlbmQgPSBub3cgKyB0"
    "aW1lZGVsdGEoZGF5cz0zNjYpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgZW5kID0gbm93ICsgdGl"
    "tZWRlbHRhKGRheXM9OTIpCgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZi"
    "JbVEFTS1NdW0ZJTFRFUl0gc3RhcnQgZmlsdGVyPXtzZWxmLl90YXNrX2RhdGVfZmlsdGVyfSBzaG93X"
    "2NvbXBsZXRlZD17c2VsZi5fdGFza19zaG93X2NvbXBsZXRlZH0gdG90YWw9e2xlbih0YXNrcyl9IiwK"
    "ICAgICAgICAgICAgIklORk8iLAogICAgICAgICkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJ"
    "bVEFTS1NdW0ZJTFRFUl0gbm93PXtub3cuaXNvZm9ybWF0KHRpbWVzcGVjPSdzZWNvbmRzJyl9IiwgIk"
    "RFQlVHIikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW0ZJTFRFUl0gaG9yaXpvb"
    "l9lbmQ9e2VuZC5pc29mb3JtYXQodGltZXNwZWM9J3NlY29uZHMnKX0iLCAiREVCVUciKQoKICAgICAg"
    "ICBmaWx0ZXJlZDogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2tpcHBlZF9pbnZhbGlkX2R1ZSA9IDA"
    "KICAgICAgICBmb3IgdGFzayBpbiB0YXNrczoKICAgICAgICAgICAgc3RhdHVzID0gKHRhc2suZ2V0KC"
    "JzdGF0dXMiKSBvciAicGVuZGluZyIpLmxvd2VyKCkKICAgICAgICAgICAgaWYgbm90IHNlbGYuX3Rhc"
    "2tfc2hvd19jb21wbGV0ZWQgYW5kIHN0YXR1cyBpbiB7ImNvbXBsZXRlZCIsICJjYW5jZWxsZWQifToK"
    "ICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBkdWVfcmF3ID0gdGFzay5nZXQoImR"
    "1ZV9hdCIpIG9yIHRhc2suZ2V0KCJkdWUiKQogICAgICAgICAgICBkdWVfZHQgPSBwYXJzZV9pc29fZm"
    "9yX2NvbXBhcmUoZHVlX3JhdywgY29udGV4dD0idGFza3NfdGFiX2R1ZV9maWx0ZXIiKQogICAgICAgI"
    "CAgICBpZiBkdWVfcmF3IGFuZCBkdWVfZHQgaXMgTm9uZToKICAgICAgICAgICAgICAgIHNraXBwZWRf"
    "aW52YWxpZF9kdWUgKz0gMQogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICA"
    "gICAgICAgICAgICAgIGYiW1RBU0tTXVtGSUxURVJdW1dBUk5dIHNraXBwaW5nIGludmFsaWQgZHVlIG"
    "RhdGV0aW1lIHRhc2tfaWQ9e3Rhc2suZ2V0KCdpZCcsJz8nKX0gZHVlX3Jhdz17ZHVlX3JhdyFyfSIsC"
    "iAgICAgICAgICAgICAgICAgICAgIldBUk4iLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAg"
    "ICAgY29udGludWUKCiAgICAgICAgICAgIGlmIGR1ZV9kdCBpcyBOb25lOgogICAgICAgICAgICAgICA"
    "gZmlsdGVyZWQuYXBwZW5kKHRhc2spCiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgIC"
    "BpZiBub3cgPD0gZHVlX2R0IDw9IGVuZCBvciBzdGF0dXMgaW4geyJjb21wbGV0ZWQiLCAiY2FuY2Vsb"
    "GVkIn06CiAgICAgICAgICAgICAgICBmaWx0ZXJlZC5hcHBlbmQodGFzaykKCiAgICAgICAgZmlsdGVy"
    "ZWQuc29ydChrZXk9X3Rhc2tfZHVlX3NvcnRfa2V5KQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyg"
    "KICAgICAgICAgICAgZiJbVEFTS1NdW0ZJTFRFUl0gZG9uZSBiZWZvcmU9e2xlbih0YXNrcyl9IGFmdG"
    "VyPXtsZW4oZmlsdGVyZWQpfSBza2lwcGVkX2ludmFsaWRfZHVlPXtza2lwcGVkX2ludmFsaWRfZHVlf"
    "SIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAgICAgICAgcmV0dXJuIGZpbHRlcmVkCgog"
    "ICAgZGVmIF9nb29nbGVfZXZlbnRfZHVlX2RhdGV0aW1lKHNlbGYsIGV2ZW50OiBkaWN0KToKICAgICA"
    "gICBzdGFydCA9IChldmVudCBvciB7fSkuZ2V0KCJzdGFydCIpIG9yIHt9CiAgICAgICAgZGF0ZV90aW"
    "1lID0gc3RhcnQuZ2V0KCJkYXRlVGltZSIpCiAgICAgICAgaWYgZGF0ZV90aW1lOgogICAgICAgICAgI"
    "CBwYXJzZWQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZGF0ZV90aW1lLCBjb250ZXh0PSJnb29nbGVf"
    "ZXZlbnRfZGF0ZVRpbWUiKQogICAgICAgICAgICBpZiBwYXJzZWQ6CiAgICAgICAgICAgICAgICByZXR"
    "1cm4gcGFyc2VkCiAgICAgICAgZGF0ZV9vbmx5ID0gc3RhcnQuZ2V0KCJkYXRlIikKICAgICAgICBpZi"
    "BkYXRlX29ubHk6CiAgICAgICAgICAgIHBhcnNlZCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZShmIntkY"
    "XRlX29ubHl9VDA5OjAwOjAwIiwgY29udGV4dD0iZ29vZ2xlX2V2ZW50X2RhdGUiKQogICAgICAgICAg"
    "ICBpZiBwYXJzZWQ6CiAgICAgICAgICAgICAgICByZXR1cm4gcGFyc2VkCiAgICAgICAgcmV0dXJuIE5"
    "vbmUKCiAgICBkZWYgX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbChzZWxmKSAtPiBOb25lOgogIC"
    "AgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBOb25lOgogICAgICAgI"
    "CAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5yZWZyZXNo"
    "KCkKICAgICAgICAgICAgdmlzaWJsZV9jb3VudCA9IGxlbihzZWxmLl9maWx0ZXJlZF90YXNrc19mb3J"
    "fcmVnaXN0cnkoKSkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXVtSRUdJU1"
    "RSWV0gcmVmcmVzaCBjb3VudD17dmlzaWJsZV9jb3VudH0uIiwgIklORk8iKQogICAgICAgIGV4Y2Vwd"
    "CBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11b"
    "UkVHSVNUUlldW0VSUk9SXSByZWZyZXNoIGZhaWxlZDoge2V4fSIsICJFUlJPUiIpCiAgICAgICAgICA"
    "gIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zdG9wX3JlZnJlc2hfd29ya2VyKH"
    "JlYXNvbj0icmVnaXN0cnlfcmVmcmVzaF9leGNlcHRpb24iKQogICAgICAgICAgICBleGNlcHQgRXhjZ"
    "XB0aW9uIGFzIHN0b3BfZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAg"
    "ICAgICAgICAgICAgICAgZiJbVEFTS1NdW1JFR0lTVFJZXVtXQVJOXSBmYWlsZWQgdG8gc3RvcCByZWZ"
    "yZXNoIHdvcmtlciBjbGVhbmx5OiB7c3RvcF9leH0iLAogICAgICAgICAgICAgICAgICAgICJXQVJOIi"
    "wKICAgICAgICAgICAgICAgICkKCiAgICBkZWYgX29uX3Rhc2tfZmlsdGVyX2NoYW5nZWQoc2VsZiwgZ"
    "mlsdGVyX2tleTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPSBz"
    "dHIoZmlsdGVyX2tleSBvciAibmV4dF8zX21vbnRocyIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9"
    "nKGYiW1RBU0tTXSBUYXNrIHJlZ2lzdHJ5IGRhdGUgZmlsdGVyIGNoYW5nZWQgdG8ge3NlbGYuX3Rhc2"
    "tfZGF0ZV9maWx0ZXJ9LiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0c"
    "nlfcGFuZWwoKQoKICAgIGRlZiBfdG9nZ2xlX3Nob3dfY29tcGxldGVkX3Rhc2tzKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCA9IG5vdCBzZWxmLl90YXNrX3Nob3d"
    "fY29tcGxldGVkCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnNldF9zaG93X2NvbXBsZXRlZChzZWxmLl"
    "90YXNrX3Nob3dfY29tcGxldGVkKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wY"
    "W5lbCgpCgogICAgZGVmIF9zZWxlY3RlZF90YXNrX2lkcyhzZWxmKSAtPiBsaXN0W3N0cl06CiAgICAg"
    "ICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIE5vbmU6CiAgICAgICAgICA"
    "gIHJldHVybiBbXQogICAgICAgIHJldHVybiBzZWxmLl90YXNrc190YWIuc2VsZWN0ZWRfdGFza19pZH"
    "MoKQoKICAgIGRlZiBfc2V0X3Rhc2tfc3RhdHVzKHNlbGYsIHRhc2tfaWQ6IHN0ciwgc3RhdHVzOiBzd"
    "HIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIGlmIHN0YXR1cyA9PSAiY29tcGxldGVkIjoKICAg"
    "ICAgICAgICAgdXBkYXRlZCA9IHNlbGYuX3Rhc2tzLmNvbXBsZXRlKHRhc2tfaWQpCiAgICAgICAgZWx"
    "pZiBzdGF0dXMgPT0gImNhbmNlbGxlZCI6CiAgICAgICAgICAgIHVwZGF0ZWQgPSBzZWxmLl90YXNrcy"
    "5jYW5jZWwodGFza19pZCkKICAgICAgICBlbHNlOgogICAgICAgICAgICB1cGRhdGVkID0gc2VsZi5fd"
    "GFza3MudXBkYXRlX3N0YXR1cyh0YXNrX2lkLCBzdGF0dXMpCgogICAgICAgIGlmIG5vdCB1cGRhdGVk"
    "OgogICAgICAgICAgICByZXR1cm4gTm9uZQoKICAgICAgICBnb29nbGVfZXZlbnRfaWQgPSAodXBkYXR"
    "lZC5nZXQoImdvb2dsZV9ldmVudF9pZCIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgaWYgZ29vZ2xlX2"
    "V2ZW50X2lkOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBzZWxmLl9nY2FsLmRlbGV0Z"
    "V9ldmVudF9mb3JfdGFzayhnb29nbGVfZXZlbnRfaWQpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICA"
    "gICAgICAgZiJbVEFTS1NdW1dBUk5dIEdvb2dsZSBldmVudCBjbGVhbnVwIGZhaWxlZCBmb3IgdGFza1"
    "9pZD17dGFza19pZH06IHtleH0iLAogICAgICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgI"
    "CAgICAgICkKICAgICAgICByZXR1cm4gdXBkYXRlZAoKICAgIGRlZiBfY29tcGxldGVfc2VsZWN0ZWRf"
    "dGFzayhzZWxmKSAtPiBOb25lOgogICAgICAgIGRvbmUgPSAwCiAgICAgICAgZm9yIHRhc2tfaWQgaW4"
    "gc2VsZi5fc2VsZWN0ZWRfdGFza19pZHMoKToKICAgICAgICAgICAgaWYgc2VsZi5fc2V0X3Rhc2tfc3"
    "RhdHVzKHRhc2tfaWQsICJjb21wbGV0ZWQiKToKICAgICAgICAgICAgICAgIGRvbmUgKz0gMQogICAgI"
    "CAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gQ09NUExFVEUgU0VMRUNURUQgYXBwbGllZCB0"
    "byB7ZG9uZX0gdGFzayhzKS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2l"
    "zdHJ5X3BhbmVsKCkKCiAgICBkZWYgX2NhbmNlbF9zZWxlY3RlZF90YXNrKHNlbGYpIC0+IE5vbmU6Ci"
    "AgICAgICAgZG9uZSA9IDAKICAgICAgICBmb3IgdGFza19pZCBpbiBzZWxmLl9zZWxlY3RlZF90YXNrX"
    "2lkcygpOgogICAgICAgICAgICBpZiBzZWxmLl9zZXRfdGFza19zdGF0dXModGFza19pZCwgImNhbmNl"
    "bGxlZCIpOgogICAgICAgICAgICAgICAgZG9uZSArPSAxCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9"
    "nKGYiW1RBU0tTXSBDQU5DRUwgU0VMRUNURUQgYXBwbGllZCB0byB7ZG9uZX0gdGFzayhzKS4iLCAiSU"
    "5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX"
    "3B1cmdlX2NvbXBsZXRlZF90YXNrcyhzZWxmKSAtPiBOb25lOgogICAgICAgIHJlbW92ZWQgPSBzZWxm"
    "Ll90YXNrcy5jbGVhcl9jb21wbGV0ZWQoKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVN"
    "LU10gUFVSR0UgQ09NUExFVEVEIHJlbW92ZWQge3JlbW92ZWR9IHRhc2socykuIiwgIklORk8iKQogIC"
    "AgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9zZXRfdGFza"
    "19lZGl0b3Jfc3RhdHVzKHNlbGYsIHRleHQ6IHN0ciwgb2s6IGJvb2wgPSBGYWxzZSkgLT4gTm9uZToK"
    "ICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkgaXMgbm90IE5vbmU6CiA"
    "gICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zZXRfc3RhdHVzKHRleHQsIG9rPW9rKQoKICAgIGRlZi"
    "Bfb3Blbl90YXNrX2VkaXRvcl93b3Jrc3BhY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBnZXRhd"
    "HRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgbm93X2xvY2FsID0gZGF0ZXRpbWUubm93KCkKICAgICAgICBlbmRfbG9jYWwgPSBub3dfbG9"
    "jYWwgKyB0aW1lZGVsdGEobWludXRlcz0zMCkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZG"
    "l0b3JfbmFtZS5zZXRUZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9zd"
    "GFydF9kYXRlLnNldFRleHQobm93X2xvY2FsLnN0cmZ0aW1lKCIlWS0lbS0lZCIpKQogICAgICAgIHNl"
    "bGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnNldFRleHQobm93X2xvY2FsLnN0cmZ"
    "0aW1lKCIlSDolTSIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9lbmRfZGF0ZS"
    "5zZXRUZXh0KGVuZF9sb2NhbC5zdHJmdGltZSgiJVktJW0tJWQiKSkKICAgICAgICBzZWxmLl90YXNrc"
    "190YWIudGFza19lZGl0b3JfZW5kX3RpbWUuc2V0VGV4dChlbmRfbG9jYWwuc3RyZnRpbWUoIiVIOiVN"
    "IikpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX25vdGVzLnNldFBsYWluVGV4dCg"
    "iIikKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfbG9jYXRpb24uc2V0VGV4dCgiIi"
    "kKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3JfcmVjdXJyZW5jZS5zZXRUZXh0KCIiK"
    "QogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9hbGxfZGF5LnNldENoZWNrZWQoRmFs"
    "c2UpCiAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiQ29uZmlndXJlIHRhc2sgZGV"
    "0YWlscywgdGhlbiBzYXZlIHRvIEdvb2dsZSBDYWxlbmRhci4iLCBvaz1GYWxzZSkKICAgICAgICBzZW"
    "xmLl90YXNrc190YWIub3Blbl9lZGl0b3IoKQoKICAgIGRlZiBfY2xvc2VfdGFza19lZGl0b3Jfd29ya"
    "3NwYWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIs"
    "IE5vbmUpIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl90YXNrc190YWIuY2xvc2VfZWRpdG9"
    "yKCkKCiAgICBkZWYgX2NhbmNlbF90YXNrX2VkaXRvcl93b3Jrc3BhY2Uoc2VsZikgLT4gTm9uZToKIC"
    "AgICAgICBzZWxmLl9jbG9zZV90YXNrX2VkaXRvcl93b3Jrc3BhY2UoKQoKICAgIGRlZiBfcGFyc2VfZ"
    "WRpdG9yX2RhdGV0aW1lKHNlbGYsIGRhdGVfdGV4dDogc3RyLCB0aW1lX3RleHQ6IHN0ciwgYWxsX2Rh"
    "eTogYm9vbCwgaXNfZW5kOiBib29sID0gRmFsc2UpOgogICAgICAgIGRhdGVfdGV4dCA9IChkYXRlX3R"
    "leHQgb3IgIiIpLnN0cmlwKCkKICAgICAgICB0aW1lX3RleHQgPSAodGltZV90ZXh0IG9yICIiKS5zdH"
    "JpcCgpCiAgICAgICAgaWYgbm90IGRhdGVfdGV4dDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgI"
    "CAgICBpZiBhbGxfZGF5OgogICAgICAgICAgICBob3VyID0gMjMgaWYgaXNfZW5kIGVsc2UgMAogICAg"
    "ICAgICAgICBtaW51dGUgPSA1OSBpZiBpc19lbmQgZWxzZSAwCiAgICAgICAgICAgIHBhcnNlZCA9IGR"
    "hdGV0aW1lLnN0cnB0aW1lKGYie2RhdGVfdGV4dH0ge2hvdXI6MDJkfTp7bWludXRlOjAyZH0iLCAiJV"
    "ktJW0tJWQgJUg6JU0iKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHBhcnNlZCA9IGRhdGV0aW1lL"
    "nN0cnB0aW1lKGYie2RhdGVfdGV4dH0ge3RpbWVfdGV4dH0iLCAiJVktJW0tJWQgJUg6JU0iKQogICAg"
    "ICAgIG5vcm1hbGl6ZWQgPSBub3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUocGFyc2VkLCBjb25"
    "0ZXh0PSJ0YXNrX2VkaXRvcl9wYXJzZV9kdCIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogIC"
    "AgICAgICAgICBmIltUQVNLU11bRURJVE9SXSBwYXJzZWQgZGF0ZXRpbWUgaXNfZW5kPXtpc19lbmR9L"
    "CBhbGxfZGF5PXthbGxfZGF5fTogIgogICAgICAgICAgICBmImlucHV0PSd7ZGF0ZV90ZXh0fSB7dGlt"
    "ZV90ZXh0fScgLT4ge25vcm1hbGl6ZWQuaXNvZm9ybWF0KCkgaWYgbm9ybWFsaXplZCBlbHNlICdOb25"
    "lJ30iLAogICAgICAgICAgICAiSU5GTyIsCiAgICAgICAgKQogICAgICAgIHJldHVybiBub3JtYWxpem"
    "VkCgogICAgZGVmIF9zYXZlX3Rhc2tfZWRpdG9yX2dvb2dsZV9maXJzdChzZWxmKSAtPiBOb25lOgogI"
    "CAgICAgIHRhYiA9IGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKQogICAgICAgIGlmIHRh"
    "YiBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0aXRsZSA9IHRhYi50YXNrX2VkaXR"
    "vcl9uYW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgYWxsX2RheSA9IHRhYi50YXNrX2VkaXRvcl9hbG"
    "xfZGF5LmlzQ2hlY2tlZCgpCiAgICAgICAgc3RhcnRfZGF0ZSA9IHRhYi50YXNrX2VkaXRvcl9zdGFyd"
    "F9kYXRlLnRleHQoKS5zdHJpcCgpCiAgICAgICAgc3RhcnRfdGltZSA9IHRhYi50YXNrX2VkaXRvcl9z"
    "dGFydF90aW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgZW5kX2RhdGUgPSB0YWIudGFza19lZGl0b3J"
    "fZW5kX2RhdGUudGV4dCgpLnN0cmlwKCkKICAgICAgICBlbmRfdGltZSA9IHRhYi50YXNrX2VkaXRvcl"
    "9lbmRfdGltZS50ZXh0KCkuc3RyaXAoKQogICAgICAgIG5vdGVzID0gdGFiLnRhc2tfZWRpdG9yX25vd"
    "GVzLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQogICAgICAgIGxvY2F0aW9uID0gdGFiLnRhc2tfZWRpdG9y"
    "X2xvY2F0aW9uLnRleHQoKS5zdHJpcCgpCiAgICAgICAgcmVjdXJyZW5jZSA9IHRhYi50YXNrX2VkaXR"
    "vcl9yZWN1cnJlbmNlLnRleHQoKS5zdHJpcCgpCgogICAgICAgIGlmIG5vdCB0aXRsZToKICAgICAgIC"
    "AgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiVGFzayBOYW1lIGlzIHJlcXVpcmVkLiIsI"
    "G9rPUZhbHNlKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBub3Qgc3RhcnRfZGF0ZSBvciBu"
    "b3QgZW5kX2RhdGUgb3IgKG5vdCBhbGxfZGF5IGFuZCAobm90IHN0YXJ0X3RpbWUgb3Igbm90IGVuZF9"
    "0aW1lKSk6CiAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIlN0YXJ0L0VuZC"
    "BkYXRlIGFuZCB0aW1lIGFyZSByZXF1aXJlZC4iLCBvaz1GYWxzZSkKICAgICAgICAgICAgcmV0dXJuC"
    "iAgICAgICAgdHJ5OgogICAgICAgICAgICBzdGFydF9kdCA9IHNlbGYuX3BhcnNlX2VkaXRvcl9kYXRl"
    "dGltZShzdGFydF9kYXRlLCBzdGFydF90aW1lLCBhbGxfZGF5LCBpc19lbmQ9RmFsc2UpCiAgICAgICA"
    "gICAgIGVuZF9kdCA9IHNlbGYuX3BhcnNlX2VkaXRvcl9kYXRldGltZShlbmRfZGF0ZSwgZW5kX3RpbW"
    "UsIGFsbF9kYXksIGlzX2VuZD1UcnVlKQogICAgICAgICAgICBpZiBub3Qgc3RhcnRfZHQgb3Igbm90I"
    "GVuZF9kdDoKICAgICAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoImRhdGV0aW1lIHBhcnNlIGZh"
    "aWxlZCIpCiAgICAgICAgICAgIGlmIGVuZF9kdCA8IHN0YXJ0X2R0OgogICAgICAgICAgICAgICAgc2V"
    "sZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiRW5kIGRhdGV0aW1lIG11c3QgYmUgYWZ0ZXIgc3Rhcn"
    "QgZGF0ZXRpbWUuIiwgb2s9RmFsc2UpCiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICBleGNlc"
    "HQgRXhjZXB0aW9uOgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJJbnZh"
    "bGlkIGRhdGUvdGltZSBmb3JtYXQuIFVzZSBZWVlZLU1NLUREIGFuZCBISDpNTS4iLCBvaz1GYWxzZSk"
    "KICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHR6X25hbWUgPSBzZWxmLl9nY2FsLl9nZXRfZ29vZ2"
    "xlX2V2ZW50X3RpbWV6b25lKCkKICAgICAgICBwYXlsb2FkID0geyJzdW1tYXJ5IjogdGl0bGV9CiAgI"
    "CAgICAgaWYgYWxsX2RheToKICAgICAgICAgICAgcGF5bG9hZFsic3RhcnQiXSA9IHsiZGF0ZSI6IHN0"
    "YXJ0X2R0LmRhdGUoKS5pc29mb3JtYXQoKX0KICAgICAgICAgICAgcGF5bG9hZFsiZW5kIl0gPSB7ImR"
    "hdGUiOiAoZW5kX2R0LmRhdGUoKSArIHRpbWVkZWx0YShkYXlzPTEpKS5pc29mb3JtYXQoKX0KICAgIC"
    "AgICBlbHNlOgogICAgICAgICAgICBwYXlsb2FkWyJzdGFydCJdID0geyJkYXRlVGltZSI6IHN0YXJ0X"
    "2R0LnJlcGxhY2UodHppbmZvPU5vbmUpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLCAidGlt"
    "ZVpvbmUiOiB0el9uYW1lfQogICAgICAgICAgICBwYXlsb2FkWyJlbmQiXSA9IHsiZGF0ZVRpbWUiOiB"
    "lbmRfZHQucmVwbGFjZSh0emluZm89Tm9uZSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksIC"
    "J0aW1lWm9uZSI6IHR6X25hbWV9CiAgICAgICAgaWYgbm90ZXM6CiAgICAgICAgICAgIHBheWxvYWRbI"
    "mRlc2NyaXB0aW9uIl0gPSBub3RlcwogICAgICAgIGlmIGxvY2F0aW9uOgogICAgICAgICAgICBwYXls"
    "b2FkWyJsb2NhdGlvbiJdID0gbG9jYXRpb24KICAgICAgICBpZiByZWN1cnJlbmNlOgogICAgICAgICA"
    "gICBydWxlID0gcmVjdXJyZW5jZSBpZiByZWN1cnJlbmNlLnVwcGVyKCkuc3RhcnRzd2l0aCgiUlJVTE"
    "U6IikgZWxzZSBmIlJSVUxFOntyZWN1cnJlbmNlfSIKICAgICAgICAgICAgcGF5bG9hZFsicmVjdXJyZ"
    "W5jZSJdID0gW3J1bGVdCgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bRURJVE9S"
    "XSBHb29nbGUgc2F2ZSBzdGFydCBmb3IgdGl0bGU9J3t0aXRsZX0nLiIsICJJTkZPIikKICAgICAgICB"
    "0cnk6CiAgICAgICAgICAgIGV2ZW50X2lkLCBfID0gc2VsZi5fZ2NhbC5jcmVhdGVfZXZlbnRfd2l0aF"
    "9wYXlsb2FkKHBheWxvYWQsIGNhbGVuZGFyX2lkPSJwcmltYXJ5IikKICAgICAgICAgICAgdGFza3MgP"
    "SBzZWxmLl90YXNrcy5sb2FkX2FsbCgpCiAgICAgICAgICAgIHRhc2sgPSB7CiAgICAgICAgICAgICAg"
    "ICAiaWQiOiBmInRhc2tfe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAgICAgImN"
    "yZWF0ZWRfYXQiOiBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICAgICAiZHVlX2F0Ijogc3Rhcn"
    "RfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAicHJlX3Rya"
    "WdnZXIiOiAoc3RhcnRfZHQgLSB0aW1lZGVsdGEobWludXRlcz0xKSkuaXNvZm9ybWF0KHRpbWVzcGVj"
    "PSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAidGV4dCI6IHRpdGxlLAogICAgICAgICAgICAgICA"
    "gInN0YXR1cyI6ICJwZW5kaW5nIiwKICAgICAgICAgICAgICAgICJhY2tub3dsZWRnZWRfYXQiOiBOb2"
    "5lLAogICAgICAgICAgICAgICAgInJldHJ5X2NvdW50IjogMCwKICAgICAgICAgICAgICAgICJsYXN0X"
    "3RyaWdnZXJlZF9hdCI6IE5vbmUsCiAgICAgICAgICAgICAgICAibmV4dF9yZXRyeV9hdCI6IE5vbmUs"
    "CiAgICAgICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6IEZhbHNlLAogICAgICAgICAgICAgICAgInN"
    "vdXJjZSI6ICJsb2NhbCIsCiAgICAgICAgICAgICAgICAiZ29vZ2xlX2V2ZW50X2lkIjogZXZlbnRfaW"
    "QsCiAgICAgICAgICAgICAgICAic3luY19zdGF0dXMiOiAic3luY2VkIiwKICAgICAgICAgICAgICAgI"
    "CJsYXN0X3N5bmNlZF9hdCI6IGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgICAgICJtZXRhZGF0"
    "YSI6IHsKICAgICAgICAgICAgICAgICAgICAiaW5wdXQiOiAidGFza19lZGl0b3JfZ29vZ2xlX2ZpcnN"
    "0IiwKICAgICAgICAgICAgICAgICAgICAibm90ZXMiOiBub3RlcywKICAgICAgICAgICAgICAgICAgIC"
    "Aic3RhcnRfYXQiOiBzdGFydF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgI"
    "CAgICAgICAgICAgICAiZW5kX2F0IjogZW5kX2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIp"
    "LAogICAgICAgICAgICAgICAgICAgICJhbGxfZGF5IjogYm9vbChhbGxfZGF5KSwKICAgICAgICAgICA"
    "gICAgICAgICAibG9jYXRpb24iOiBsb2NhdGlvbiwKICAgICAgICAgICAgICAgICAgICAicmVjdXJyZW"
    "5jZSI6IHJlY3VycmVuY2UsCiAgICAgICAgICAgICAgICB9LAogICAgICAgICAgICB9CiAgICAgICAgI"
    "CAgIHRhc2tzLmFwcGVuZCh0YXNrKQogICAgICAgICAgICBzZWxmLl90YXNrcy5zYXZlX2FsbCh0YXNr"
    "cykKICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiR29vZ2xlIHN5bmMgc3V"
    "jY2VlZGVkIGFuZCB0YXNrIHJlZ2lzdHJ5IHVwZGF0ZWQuIiwgb2s9VHJ1ZSkKICAgICAgICAgICAgc2"
    "VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ190Y"
    "WIubG9nKAogICAgICAgICAgICAgICAgZiJbVEFTS1NdW0VESVRPUl0gR29vZ2xlIHNhdmUgc3VjY2Vz"
    "cyBmb3IgdGl0bGU9J3t0aXRsZX0nLCBldmVudF9pZD17ZXZlbnRfaWR9LiIsCiAgICAgICAgICAgICA"
    "gICAiT0siLAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2Nsb3NlX3Rhc2tfZWRpdG9yX3"
    "dvcmtzcGFjZSgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZ"
    "i5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cyhmIkdvb2dsZSBzYXZlIGZhaWxlZDoge2V4fSIsIG9rPUZh"
    "bHNlKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltUQVN"
    "LU11bRURJVE9SXVtFUlJPUl0gR29vZ2xlIHNhdmUgZmFpbHVyZSBmb3IgdGl0bGU9J3t0aXRsZX0nOi"
    "B7ZXh9IiwKICAgICAgICAgICAgICAgICJFUlJPUiIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgc"
    "2VsZi5fY2xvc2VfdGFza19lZGl0b3Jfd29ya3NwYWNlKCkKCiAgICBkZWYgX2luc2VydF9jYWxlbmRh"
    "cl9kYXRlKHNlbGYsIHFkYXRlOiBRRGF0ZSkgLT4gTm9uZToKICAgICAgICBkYXRlX3RleHQgPSBxZGF"
    "0ZS50b1N0cmluZygieXl5eS1NTS1kZCIpCiAgICAgICAgcm91dGVkX3RhcmdldCA9ICJub25lIgoKIC"
    "AgICAgICBmb2N1c193aWRnZXQgPSBRQXBwbGljYXRpb24uZm9jdXNXaWRnZXQoKQogICAgICAgIGRpc"
    "mVjdF90YXJnZXRzID0gWwogICAgICAgICAgICAoInRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUiLCBnZXRh"
    "dHRyKGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSwgInRhc2tfZWRpdG9yX3N0YXJ0X2R"
    "hdGUiLCBOb25lKSksCiAgICAgICAgICAgICgidGFza19lZGl0b3JfZW5kX2RhdGUiLCBnZXRhdHRyKG"
    "dldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSwgInRhc2tfZWRpdG9yX2VuZF9kYXRlIiwgT"
    "m9uZSkpLAogICAgICAgIF0KICAgICAgICBmb3IgbmFtZSwgd2lkZ2V0IGluIGRpcmVjdF90YXJnZXRz"
    "OgogICAgICAgICAgICBpZiB3aWRnZXQgaXMgbm90IE5vbmUgYW5kIGZvY3VzX3dpZGdldCBpcyB3aWR"
    "nZXQ6CiAgICAgICAgICAgICAgICB3aWRnZXQuc2V0VGV4dChkYXRlX3RleHQpCiAgICAgICAgICAgIC"
    "AgICByb3V0ZWRfdGFyZ2V0ID0gbmFtZQogICAgICAgICAgICAgICAgYnJlYWsKCiAgICAgICAgaWYgc"
    "m91dGVkX3RhcmdldCA9PSAibm9uZSI6CiAgICAgICAgICAgIGlmIGhhc2F0dHIoc2VsZiwgIl9pbnB1"
    "dF9maWVsZCIpIGFuZCBzZWxmLl9pbnB1dF9maWVsZCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICA"
    "gIGlmIGZvY3VzX3dpZGdldCBpcyBzZWxmLl9pbnB1dF9maWVsZDoKICAgICAgICAgICAgICAgICAgIC"
    "BzZWxmLl9pbnB1dF9maWVsZC5pbnNlcnQoZGF0ZV90ZXh0KQogICAgICAgICAgICAgICAgICAgIHJvd"
    "XRlZF90YXJnZXQgPSAiaW5wdXRfZmllbGRfaW5zZXJ0IgogICAgICAgICAgICAgICAgZWxzZToKICAg"
    "ICAgICAgICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRUZXh0KGRhdGVfdGV4dCkKICAgICA"
    "gICAgICAgICAgICAgICByb3V0ZWRfdGFyZ2V0ID0gImlucHV0X2ZpZWxkX3NldCIKCiAgICAgICAgaW"
    "YgaGFzYXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIpIGFuZCBzZWxmLl90YXNrc190YWIgaXMgbm90IE5vb"
    "mU6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkNhbGVu"
    "ZGFyIGRhdGUgc2VsZWN0ZWQ6IHtkYXRlX3RleHR9IikKCiAgICAgICAgaWYgaGFzYXR0cihzZWxmLCA"
    "iX2RpYWdfdGFiIikgYW5kIHNlbGYuX2RpYWdfdGFiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZW"
    "xmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltDQUxFTkRBUl0gbWluaSBjYWxlbmRhc"
    "iBjbGljayByb3V0ZWQ6IGRhdGU9e2RhdGVfdGV4dH0sIHRhcmdldD17cm91dGVkX3RhcmdldH0uIiwK"
    "ICAgICAgICAgICAgICAgICJJTkZPIgogICAgICAgICAgICApCgogICAgZGVmIF9wb2xsX2dvb2dsZV9"
    "jYWxlbmRhcl9pbmJvdW5kX3N5bmMoc2VsZiwgZm9yY2Vfb25jZTogYm9vbCA9IEZhbHNlKToKICAgIC"
    "AgICAiIiIKICAgICAgICBTeW5jIEdvb2dsZSBDYWxlbmRhciBldmVudHMg4oaSIGxvY2FsIHRhc2tzI"
    "HVzaW5nIEdvb2dsZSdzIHN5bmNUb2tlbiBBUEkuCgogICAgICAgIFN0YWdlIDEgKGZpcnN0IHJ1biAv"
    "IGZvcmNlZCk6IEZ1bGwgZmV0Y2gsIHN0b3JlcyBuZXh0U3luY1Rva2VuLgogICAgICAgIFN0YWdlIDI"
    "gKGV2ZXJ5IHBvbGwpOiAgICAgICAgIEluY3JlbWVudGFsIGZldGNoIHVzaW5nIHN0b3JlZCBzeW5jVG"
    "9rZW4g4oCUCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJucyBPTkxZI"
    "HdoYXQgY2hhbmdlZCAoYWRkcy9lZGl0cy9jYW5jZWxzKS4KICAgICAgICBJZiBzZXJ2ZXIgcmV0dXJu"
    "cyA0MTAgR29uZSAodG9rZW4gZXhwaXJlZCksIGZhbGxzIGJhY2sgdG8gZnVsbCBzeW5jLgogICAgICA"
    "gICIiIgogICAgICAgIGlmIG5vdCBmb3JjZV9vbmNlIGFuZCBub3QgYm9vbChDRkcuZ2V0KCJzZXR0aW"
    "5ncyIsIHt9KS5nZXQoImdvb2dsZV9zeW5jX2VuYWJsZWQiLCBUcnVlKSk6CiAgICAgICAgICAgIHJld"
    "HVybiAwCgogICAgICAgIHRyeToKICAgICAgICAgICAgbm93X2lzbyA9IGxvY2FsX25vd19pc28oKQog"
    "ICAgICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkKICAgICAgICAgICAgdGFza3N"
    "fYnlfZXZlbnRfaWQgPSB7CiAgICAgICAgICAgICAgICAodC5nZXQoImdvb2dsZV9ldmVudF9pZCIpIG"
    "9yICIiKS5zdHJpcCgpOiB0CiAgICAgICAgICAgICAgICBmb3IgdCBpbiB0YXNrcwogICAgICAgICAgI"
    "CAgICAgaWYgKHQuZ2V0KCJnb29nbGVfZXZlbnRfaWQiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAg"
    "ICB9CgogICAgICAgICAgICAjIOKUgOKUgCBGZXRjaCBmcm9tIEdvb2dsZSDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgI"
    "CAgICAgc3RvcmVkX3Rva2VuID0gc2VsZi5fc3RhdGUuZ2V0KCJnb29nbGVfY2FsZW5kYXJfc3luY190"
    "b2tlbiIpCgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBzdG9yZWRfdG9rZW4gYW5"
    "kIG5vdCBmb3JjZV9vbmNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKIC"
    "AgICAgICAgICAgICAgICAgICAgICAgIltHT09HTEVdW1NZTkNdIEluY3JlbWVudGFsIHN5bmMgKHN5b"
    "mNUb2tlbikuIiwgIklORk8iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAg"
    "IHJlbW90ZV9ldmVudHMsIG5leHRfdG9rZW4gPSBzZWxmLl9nY2FsLmxpc3RfcHJpbWFyeV9ldmVudHM"
    "oCiAgICAgICAgICAgICAgICAgICAgICAgIHN5bmNfdG9rZW49c3RvcmVkX3Rva2VuCiAgICAgICAgIC"
    "AgICAgICAgICAgKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmL"
    "l9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgICAgICJbR09PR0xFXVtTWU5DXSBGdWxs"
    "IHN5bmMgKG5vIHN0b3JlZCB0b2tlbikuIiwgIklORk8iCiAgICAgICAgICAgICAgICAgICAgKQogICA"
    "gICAgICAgICAgICAgICAgIG5vd191dGMgPSBkYXRldGltZS51dGNub3coKS5yZXBsYWNlKG1pY3Jvc2"
    "Vjb25kPTApCiAgICAgICAgICAgICAgICAgICAgdGltZV9taW4gPSAobm93X3V0YyAtIHRpbWVkZWx0Y"
    "ShkYXlzPTM2NSkpLmlzb2Zvcm1hdCgpICsgIloiCiAgICAgICAgICAgICAgICAgICAgcmVtb3RlX2V2"
    "ZW50cywgbmV4dF90b2tlbiA9IHNlbGYuX2djYWwubGlzdF9wcmltYXJ5X2V2ZW50cygKICAgICAgICA"
    "gICAgICAgICAgICAgICAgdGltZV9taW49dGltZV9taW4KICAgICAgICAgICAgICAgICAgICApCgogIC"
    "AgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGFwaV9leDoKICAgICAgICAgICAgICAgIGlmICI0M"
    "TAiIGluIHN0cihhcGlfZXgpIG9yICJHb25lIiBpbiBzdHIoYXBpX2V4KToKICAgICAgICAgICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgICAgICJbR09PR0xFXVt"
    "TWU5DXSBzeW5jVG9rZW4gZXhwaXJlZCAoNDEwKSDigJQgZnVsbCByZXN5bmMuIiwgIldBUk4iCiAgIC"
    "AgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIHNlbGYuX3N0YXRlLnBvcCgiZ29vZ"
    "2xlX2NhbGVuZGFyX3N5bmNfdG9rZW4iLCBOb25lKQogICAgICAgICAgICAgICAgICAgIG5vd191dGMg"
    "PSBkYXRldGltZS51dGNub3coKS5yZXBsYWNlKG1pY3Jvc2Vjb25kPTApCiAgICAgICAgICAgICAgICA"
    "gICAgdGltZV9taW4gPSAobm93X3V0YyAtIHRpbWVkZWx0YShkYXlzPTM2NSkpLmlzb2Zvcm1hdCgpIC"
    "sgIloiCiAgICAgICAgICAgICAgICAgICAgcmVtb3RlX2V2ZW50cywgbmV4dF90b2tlbiA9IHNlbGYuX"
    "2djYWwubGlzdF9wcmltYXJ5X2V2ZW50cygKICAgICAgICAgICAgICAgICAgICAgICAgdGltZV9taW49"
    "dGltZV9taW4KICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICA"
    "gICAgICAgICAgICAgIHJhaXNlCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgIC"
    "AgICAgICAgICBmIltHT09HTEVdW1NZTkNdIFJlY2VpdmVkIHtsZW4ocmVtb3RlX2V2ZW50cyl9IGV2Z"
    "W50KHMpLiIsICJJTkZPIgogICAgICAgICAgICApCgogICAgICAgICAgICAjIFNhdmUgbmV3IHRva2Vu"
    "IGZvciBuZXh0IGluY3JlbWVudGFsIGNhbGwKICAgICAgICAgICAgaWYgbmV4dF90b2tlbjoKICAgICA"
    "gICAgICAgICAgIHNlbGYuX3N0YXRlWyJnb29nbGVfY2FsZW5kYXJfc3luY190b2tlbiJdID0gbmV4dF"
    "90b2tlbgogICAgICAgICAgICAgICAgc2VsZi5fbWVtb3J5LnNhdmVfc3RhdGUoc2VsZi5fc3RhdGUpC"
    "gogICAgICAgICAgICAjIOKUgOKUgCBQcm9jZXNzIGV2ZW50cyDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIC"
    "AgICAgICAgaW1wb3J0ZWRfY291bnQgPSB1cGRhdGVkX2NvdW50ID0gcmVtb3ZlZF9jb3VudCA9IDAKI"
    "CAgICAgICAgICAgY2hhbmdlZCA9IEZhbHNlCgogICAgICAgICAgICBmb3IgZXZlbnQgaW4gcmVtb3Rl"
    "X2V2ZW50czoKICAgICAgICAgICAgICAgIGV2ZW50X2lkID0gKGV2ZW50LmdldCgiaWQiKSBvciAiIik"
    "uc3RyaXAoKQogICAgICAgICAgICAgICAgaWYgbm90IGV2ZW50X2lkOgogICAgICAgICAgICAgICAgIC"
    "AgIGNvbnRpbnVlCgogICAgICAgICAgICAgICAgIyBEZWxldGVkIC8gY2FuY2VsbGVkIG9uIEdvb2dsZ"
    "SdzIHNpZGUKICAgICAgICAgICAgICAgIGlmIGV2ZW50LmdldCgic3RhdHVzIikgPT0gImNhbmNlbGxl"
    "ZCI6CiAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmcgPSB0YXNrc19ieV9ldmVudF9pZC5nZXQoZXZ"
    "lbnRfaWQpCiAgICAgICAgICAgICAgICAgICAgaWYgZXhpc3RpbmcgYW5kIGV4aXN0aW5nLmdldCgic3"
    "RhdHVzIikgbm90IGluICgiY2FuY2VsbGVkIiwgImNvbXBsZXRlZCIpOgogICAgICAgICAgICAgICAgI"
    "CAgICAgICBleGlzdGluZ1sic3RhdHVzIl0gICAgICAgICA9ICJjYW5jZWxsZWQiCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGV4aXN0aW5nWyJjYW5jZWxsZWRfYXQiXSAgID0gbm93X2lzbwogICAgICAgICA"
    "gICAgICAgICAgICAgICBleGlzdGluZ1sic3luY19zdGF0dXMiXSAgICA9ICJkZWxldGVkX3JlbW90ZS"
    "IKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbImxhc3Rfc3luY2VkX2F0Il0gPSBub3dfa"
    "XNvCiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nLnNldGRlZmF1bHQoIm1ldGFkYXRhIiwg"
    "e30pWyJnb29nbGVfZGVsZXRlZF9yZW1vdGUiXSA9IG5vd19pc28KICAgICAgICAgICAgICAgICAgICA"
    "gICAgcmVtb3ZlZF9jb3VudCArPSAxCiAgICAgICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcn"
    "VlCiAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgI"
    "CAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1lOQ10gUmVtb3ZlZDoge2V4aXN0aW5nLmdldCgndGV4"
    "dCcsJz8nKX0iLCAiSU5GTyIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICA"
    "gICAgIGNvbnRpbnVlCgogICAgICAgICAgICAgICAgc3VtbWFyeSA9IChldmVudC5nZXQoInN1bW1hcn"
    "kiKSBvciAiR29vZ2xlIENhbGVuZGFyIEV2ZW50Iikuc3RyaXAoKSBvciAiR29vZ2xlIENhbGVuZGFyI"
    "EV2ZW50IgogICAgICAgICAgICAgICAgZHVlX2F0ICA9IHNlbGYuX2dvb2dsZV9ldmVudF9kdWVfZGF0"
    "ZXRpbWUoZXZlbnQpCiAgICAgICAgICAgICAgICBleGlzdGluZyA9IHRhc2tzX2J5X2V2ZW50X2lkLmd"
    "ldChldmVudF9pZCkKCiAgICAgICAgICAgICAgICBpZiBleGlzdGluZzoKICAgICAgICAgICAgICAgIC"
    "AgICAjIFVwZGF0ZSBpZiBhbnl0aGluZyBjaGFuZ2VkCiAgICAgICAgICAgICAgICAgICAgdGFza19ja"
    "GFuZ2VkID0gRmFsc2UKICAgICAgICAgICAgICAgICAgICBpZiAoZXhpc3RpbmcuZ2V0KCJ0ZXh0Iikg"
    "b3IgIiIpLnN0cmlwKCkgIT0gc3VtbWFyeToKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3Rpbmd"
    "bInRleHQiXSA9IHN1bW1hcnkKICAgICAgICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gVH"
    "J1ZQogICAgICAgICAgICAgICAgICAgIGlmIGR1ZV9hdDoKICAgICAgICAgICAgICAgICAgICAgICAgZ"
    "HVlX2lzbyA9IGR1ZV9hdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAg"
    "ICAgICAgICAgICBpZiBleGlzdGluZy5nZXQoImR1ZV9hdCIpICE9IGR1ZV9pc286CiAgICAgICAgICA"
    "gICAgICAgICAgICAgICAgICBleGlzdGluZ1siZHVlX2F0Il0gICAgICAgPSBkdWVfaXNvCiAgICAgIC"
    "AgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sicHJlX3RyaWdnZXIiXSAgPSAoZHVlX2F0IC0gd"
    "GltZWRlbHRhKG1pbnV0ZXM9MSkpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICB0YXNrX2NoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICA"
    "gaWYgZXhpc3RpbmcuZ2V0KCJzeW5jX3N0YXR1cyIpICE9ICJzeW5jZWQiOgogICAgICAgICAgICAgIC"
    "AgICAgICAgICBleGlzdGluZ1sic3luY19zdGF0dXMiXSA9ICJzeW5jZWQiCiAgICAgICAgICAgICAgI"
    "CAgICAgICAgIHRhc2tfY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgICAgICBpZiB0YXNrX2No"
    "YW5nZWQ6CiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJsYXN0X3N5bmNlZF9hdCJdID0"
    "gbm93X2lzbwogICAgICAgICAgICAgICAgICAgICAgICB1cGRhdGVkX2NvdW50ICs9IDEKICAgICAgIC"
    "AgICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgICAgICAgICAgc2VsZ"
    "i5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTWU5D"
    "XSBVcGRhdGVkOiB7c3VtbWFyeX0iLCAiSU5GTyIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICA"
    "gICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICAjIE5ldyBldmVudAogICAgICAgIC"
    "AgICAgICAgICAgIGlmIG5vdCBkdWVfYXQ6CiAgICAgICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlC"
    "iAgICAgICAgICAgICAgICAgICAgbmV3X3Rhc2sgPSB7CiAgICAgICAgICAgICAgICAgICAgICAgICJp"
    "ZCI6ICAgICAgICAgICAgICAgIGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICA"
    "gICAgICAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgICAgIG5vd19pc28sCiAgICAgICAgICAgIC"
    "AgICAgICAgICAgICJkdWVfYXQiOiAgICAgICAgICAgIGR1ZV9hdC5pc29mb3JtYXQodGltZXNwZWM9I"
    "nNlY29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAgICAgInByZV90cmlnZ2VyIjogICAgICAgKGR1"
    "ZV9hdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSw"
    "KICAgICAgICAgICAgICAgICAgICAgICAgInRleHQiOiAgICAgICAgICAgICAgc3VtbWFyeSwKICAgIC"
    "AgICAgICAgICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgICAgICAgInBlbmRpbmciLAogICAgICAgI"
    "CAgICAgICAgICAgICAgICAiYWNrbm93bGVkZ2VkX2F0IjogICBOb25lLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAicmV0cnlfY291bnQiOiAgICAgICAwLAogICAgICAgICAgICAgICAgICAgICAgICAibGF"
    "zdF90cmlnZ2VyZWRfYXQiOiBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAibmV4dF9yZXRyeV"
    "9hdCI6ICAgICBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6ICAgI"
    "CBGYWxzZSwKICAgICAgICAgICAgICAgICAgICAgICAgInNvdXJjZSI6ICAgICAgICAgICAgImdvb2ds"
    "ZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICJnb29nbGVfZXZlbnRfaWQiOiAgIGV2ZW50X2lkLAo"
    "gICAgICAgICAgICAgICAgICAgICAgICAic3luY19zdGF0dXMiOiAgICAgICAic3luY2VkIiwKICAgIC"
    "AgICAgICAgICAgICAgICAgICAgImxhc3Rfc3luY2VkX2F0IjogICAgbm93X2lzbywKICAgICAgICAgI"
    "CAgICAgICAgICAgICAgIm1ldGFkYXRhIjogewogICAgICAgICAgICAgICAgICAgICAgICAgICAgImdv"
    "b2dsZV9pbXBvcnRlZF9hdCI6IG5vd19pc28sCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAiZ29"
    "vZ2xlX3VwZGF0ZWQiOiAgICAgZXZlbnQuZ2V0KCJ1cGRhdGVkIiksCiAgICAgICAgICAgICAgICAgIC"
    "AgICAgIH0sCiAgICAgICAgICAgICAgICAgICAgfQogICAgICAgICAgICAgICAgICAgIHRhc2tzLmFwc"
    "GVuZChuZXdfdGFzaykKICAgICAgICAgICAgICAgICAgICB0YXNrc19ieV9ldmVudF9pZFtldmVudF9p"
    "ZF0gPSBuZXdfdGFzawogICAgICAgICAgICAgICAgICAgIGltcG9ydGVkX2NvdW50ICs9IDEKICAgICA"
    "gICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYW"
    "dfdGFiLmxvZyhmIltHT09HTEVdW1NZTkNdIEltcG9ydGVkOiB7c3VtbWFyeX0iLCAiSU5GTyIpCgogI"
    "CAgICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICAgICAgc2VsZi5fdGFza3Muc2F2ZV9hbGwo"
    "dGFza3MpCiAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICA"
    "gICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NZTk"
    "NdIERvbmUg4oCUIGltcG9ydGVkPXtpbXBvcnRlZF9jb3VudH0gIgogICAgICAgICAgICAgICAgZiJ1c"
    "GRhdGVkPXt1cGRhdGVkX2NvdW50fSByZW1vdmVkPXtyZW1vdmVkX2NvdW50fSIsICJJTkZPIgogICAg"
    "ICAgICAgICApCiAgICAgICAgICAgIHJldHVybiBpbXBvcnRlZF9jb3VudAoKICAgICAgICBleGNlcHQ"
    "gRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXV"
    "tTWU5DXVtFUlJPUl0ge2V4fSIsICJFUlJPUiIpCiAgICAgICAgICAgIHJldHVybiAwCgoKICAgIGRlZ"
    "iBfbWVhc3VyZV92cmFtX2Jhc2VsaW5lKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgTlZNTF9PSyBh"
    "bmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgbWVtID0gcHludm1"
    "sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICBzZWxmLl"
    "9kZWNrX3ZyYW1fYmFzZSA9IG1lbS51c2VkIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgc2VsZi5fZ"
    "GlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1ZSQU1dIEJhc2VsaW5lIG1lYXN1cmVk"
    "OiB7c2VsZi5fZGVja192cmFtX2Jhc2U6LjJmfUdCICIKICAgICAgICAgICAgICAgICAgICBmIih7REV"
    "DS19OQU1FfSdzIGZvb3RwcmludCkiLCAiSU5GTyIKICAgICAgICAgICAgICAgICkKICAgICAgICAgIC"
    "AgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAjIOKUgOKUgCBNRVNTQ"
    "UdFIEhBTkRMSU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgA"
    "ogICAgZGVmIF9zZW5kX21lc3NhZ2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fb"
    "W9kZWxfbG9hZGVkIG9yIHNlbGYuX3RvcnBvcl9zdGF0ZSA9PSAiU1VTUEVORCI6CiAgICAgICAgICAg"
    "IHJldHVybgogICAgICAgIHRleHQgPSBzZWxmLl9pbnB1dF9maWVsZC50ZXh0KCkuc3RyaXAoKQogICA"
    "gICAgIGlmIG5vdCB0ZXh0OgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgIyBGbGlwIGJhY2sgdG"
    "8gcGVyc29uYSBjaGF0IHRhYiBmcm9tIFNlbGYgdGFiIGlmIG5lZWRlZAogICAgICAgIGlmIHNlbGYuX"
    "21haW5fdGFicy5jdXJyZW50SW5kZXgoKSAhPSAwOgogICAgICAgICAgICBzZWxmLl9tYWluX3RhYnMu"
    "c2V0Q3VycmVudEluZGV4KDApCgogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLmNsZWFyKCkKICAgICA"
    "gICBzZWxmLl9hcHBlbmRfY2hhdCgiWU9VIiwgdGV4dCkKCiAgICAgICAgIyBTZXNzaW9uIGxvZ2dpbm"
    "cKICAgICAgICBzZWxmLl9zZXNzaW9ucy5hZGRfbWVzc2FnZSgidXNlciIsIHRleHQpCiAgICAgICAgc"
    "2VsZi5fbWVtb3J5LmFwcGVuZF9tZXNzYWdlKHNlbGYuX3Nlc3Npb25faWQsICJ1c2VyIiwgdGV4dCkK"
    "CiAgICAgICAgIyBJbnRlcnJ1cHQgZmFjZSB0aW1lciDigJQgc3dpdGNoIHRvIGFsZXJ0IGltbWVkaWF"
    "0ZWx5CiAgICAgICAgaWYgc2VsZi5fZmFjZV90aW1lcl9tZ3I6CiAgICAgICAgICAgIHNlbGYuX2ZhY2"
    "VfdGltZXJfbWdyLmludGVycnVwdCgiYWxlcnQiKQoKICAgICAgICAjIEJ1aWxkIHByb21wdCB3aXRoI"
    "HZhbXBpcmUgY29udGV4dCArIG1lbW9yeSBjb250ZXh0CiAgICAgICAgdmFtcGlyZV9jdHggID0gYnVp"
    "bGRfdmFtcGlyZV9jb250ZXh0KCkKICAgICAgICBtZW1vcnlfY3R4ICAgPSBzZWxmLl9tZW1vcnkuYnV"
    "pbGRfY29udGV4dF9ibG9jayh0ZXh0KQogICAgICAgIGpvdXJuYWxfY3R4ICA9ICIiCgogICAgICAgIG"
    "lmIHNlbGYuX3Nlc3Npb25zLmxvYWRlZF9qb3VybmFsX2RhdGU6CiAgICAgICAgICAgIGpvdXJuYWxfY"
    "3R4ID0gc2VsZi5fc2Vzc2lvbnMubG9hZF9zZXNzaW9uX2FzX2NvbnRleHQoCiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9zZXNzaW9ucy5sb2FkZWRfam91cm5hbF9kYXRlCiAgICAgICAgICAgICkKCiAgICAgICA"
    "gIyBCdWlsZCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgc3lzdGVtID0gU1lTVEVNX1BST01QVF9CQVNFCi"
    "AgICAgICAgaWYgbWVtb3J5X2N0eDoKICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5cbnttZW1vcnlfY"
    "3R4fSIKICAgICAgICBpZiBqb3VybmFsX2N0eDoKICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5cbntq"
    "b3VybmFsX2N0eH0iCiAgICAgICAgc3lzdGVtICs9IHZhbXBpcmVfY3R4CgogICAgICAgICMgTGVzc29"
    "ucyBjb250ZXh0IGZvciBjb2RlLWFkamFjZW50IGlucHV0CiAgICAgICAgaWYgYW55KGt3IGluIHRleH"
    "QubG93ZXIoKSBmb3Iga3cgaW4gKCJsc2wiLCJweXRob24iLCJzY3JpcHQiLCJjb2RlIiwiZnVuY3Rpb"
    "24iKSk6CiAgICAgICAgICAgIGxhbmcgPSAiTFNMIiBpZiAibHNsIiBpbiB0ZXh0Lmxvd2VyKCkgZWxz"
    "ZSAiUHl0aG9uIgogICAgICAgICAgICBsZXNzb25zX2N0eCA9IHNlbGYuX2xlc3NvbnMuYnVpbGRfY29"
    "udGV4dF9mb3JfbGFuZ3VhZ2UobGFuZykKICAgICAgICAgICAgaWYgbGVzc29uc19jdHg6CiAgICAgIC"
    "AgICAgICAgICBzeXN0ZW0gKz0gZiJcblxue2xlc3NvbnNfY3R4fSIKCiAgICAgICAgIyBBZGQgcGVuZ"
    "GluZyB0cmFuc21pc3Npb25zIGNvbnRleHQgaWYgYW55CiAgICAgICAgaWYgc2VsZi5fcGVuZGluZ190"
    "cmFuc21pc3Npb25zID4gMDoKICAgICAgICAgICAgZHVyID0gc2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9"
    "uIG9yICJzb21lIHRpbWUiCiAgICAgICAgICAgIHN5c3RlbSArPSAoCiAgICAgICAgICAgICAgICBmIl"
    "xuXG5bUkVUVVJOIEZST00gVE9SUE9SXVxuIgogICAgICAgICAgICAgICAgZiJZb3Ugd2VyZSBpbiB0b"
    "3Jwb3IgZm9yIHtkdXJ9LiAiCiAgICAgICAgICAgICAgICBmIntzZWxmLl9wZW5kaW5nX3RyYW5zbWlz"
    "c2lvbnN9IHRob3VnaHRzIHdlbnQgdW5zcG9rZW4gIgogICAgICAgICAgICAgICAgZiJkdXJpbmcgdGh"
    "hdCB0aW1lLiBBY2tub3dsZWRnZSB0aGlzIGJyaWVmbHkgaW4gY2hhcmFjdGVyICIKICAgICAgICAgIC"
    "AgICAgIGYiaWYgaXQgZmVlbHMgbmF0dXJhbC4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZ"
    "i5fcGVuZGluZ190cmFuc21pc3Npb25zID0gMAogICAgICAgICAgICBzZWxmLl9zdXNwZW5kZWRfZHVy"
    "YXRpb24gICAgPSAiIgoKICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3Rvcnk"
    "oKQoKICAgICAgICAjIERpc2FibGUgaW5wdXQKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibG"
    "VkKEZhbHNlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgI"
    "CAgc2VsZi5fc2V0X3N0YXR1cygiR0VORVJBVElORyIpCgogICAgICAgICMgU3RvcCBpZGxlIHRpbWVy"
    "IGR1cmluZyBnZW5lcmF0aW9uCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIGlmIHNlbGY"
    "uX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKIC"
    "AgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uI"
    "ikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAg"
    "ICAgIyBMYXVuY2ggc3RyZWFtaW5nIHdvcmtlcgogICAgICAgIHNlbGYuX3dvcmtlciA9IFN0cmVhbWl"
    "uZ1dvcmtlcigKICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwgc3lzdGVtLCBoaXN0b3J5LCBtYXhfdG"
    "9rZW5zPTUxMgogICAgICAgICkKICAgICAgICBzZWxmLl93b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjd"
    "ChzZWxmLl9vbl90b2tlbikKICAgICAgICBzZWxmLl93b3JrZXIucmVzcG9uc2VfZG9uZS5jb25uZWN0"
    "KHNlbGYuX29uX3Jlc3BvbnNlX2RvbmUpCiAgICAgICAgc2VsZi5fd29ya2VyLmVycm9yX29jY3VycmV"
    "kLmNvbm5lY3Qoc2VsZi5fb25fZXJyb3IpCiAgICAgICAgc2VsZi5fd29ya2VyLnN0YXR1c19jaGFuZ2"
    "VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1cykKICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRyd"
    "WUgICMgZmxhZyB0byB3cml0ZSBzcGVha2VyIGxhYmVsIGJlZm9yZSBmaXJzdCB0b2tlbgogICAgICAg"
    "IHNlbGYuX3dvcmtlci5zdGFydCgpCgogICAgZGVmIF9iZWdpbl9wZXJzb25hX3Jlc3BvbnNlKHNlbGY"
    "pIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgV3JpdGUgdGhlIHBlcnNvbmEgc3BlYWtlciBsYW"
    "JlbCBhbmQgdGltZXN0YW1wIGJlZm9yZSBzdHJlYW1pbmcgYmVnaW5zLgogICAgICAgIENhbGxlZCBvb"
    "iBmaXJzdCB0b2tlbiBvbmx5LiBTdWJzZXF1ZW50IHRva2VucyBhcHBlbmQgZGlyZWN0bHkuCiAgICAg"
    "ICAgIiIiCiAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiV"
    "TIikKICAgICAgICAjIFdyaXRlIHRoZSBzcGVha2VyIGxhYmVsIGFzIEhUTUwsIHRoZW4gYWRkIGEgbm"
    "V3bGluZSBzbyB0b2tlbnMKICAgICAgICAjIGZsb3cgYmVsb3cgaXQgcmF0aGVyIHRoYW4gaW5saW5lC"
    "iAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgZic8c3BhbiBzdHls"
    "ZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAgICAgICAgZidbe3R"
    "pbWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX0NSSU"
    "1TT059OyBmb250LXdlaWdodDpib2xkOyI+JwogICAgICAgICAgICBmJ3tERUNLX05BTUUudXBwZXIoK"
    "X0g4p2pPC9zcGFuPiAnCiAgICAgICAgKQogICAgICAgICMgTW92ZSBjdXJzb3IgdG8gZW5kIHNvIGlu"
    "c2VydFBsYWluVGV4dCBhcHBlbmRzIGNvcnJlY3RseQogICAgICAgIGN1cnNvciA9IHNlbGYuX2NoYXR"
    "fZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAgICBjdXJzb3IubW92ZVBvc2l0aW9uKFFUZXh0Q3Vyc2"
    "9yLk1vdmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRUZXh0Q3Vyc"
    "29yKGN1cnNvcikKCiAgICBkZWYgX29uX3Rva2VuKHNlbGYsIHRva2VuOiBzdHIpIC0+IE5vbmU6CiAg"
    "ICAgICAgIiIiQXBwZW5kIHN0cmVhbWluZyB0b2tlbiB0byBjaGF0IGRpc3BsYXkuIiIiCiAgICAgICA"
    "gaWYgc2VsZi5fZmlyc3RfdG9rZW46CiAgICAgICAgICAgIHNlbGYuX2JlZ2luX3BlcnNvbmFfcmVzcG"
    "9uc2UoKQogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IEZhbHNlCiAgICAgICAgY3Vyc29yI"
    "D0gc2VsZi5fY2hhdF9kaXNwbGF5LnRleHRDdXJzb3IoKQogICAgICAgIGN1cnNvci5tb3ZlUG9zaXRp"
    "b24oUVRleHRDdXJzb3IuTW92ZU9wZXJhdGlvbi5FbmQpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF"
    "5LnNldFRleHRDdXJzb3IoY3Vyc29yKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5pbnNlcnRQbG"
    "FpblRleHQodG9rZW4pCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyK"
    "Ckuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJh"
    "cigpLm1heGltdW0oKQogICAgICAgICkKCiAgICBkZWYgX29uX3Jlc3BvbnNlX2RvbmUoc2VsZiwgcmV"
    "zcG9uc2U6IHN0cikgLT4gTm9uZToKICAgICAgICAjIEVuc3VyZSByZXNwb25zZSBpcyBvbiBpdHMgb3"
    "duIGxpbmUKICAgICAgICBjdXJzb3IgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudGV4dEN1cnNvcigpCiAgI"
    "CAgICAgY3Vyc29yLm1vdmVQb3NpdGlvbihRVGV4dEN1cnNvci5Nb3ZlT3BlcmF0aW9uLkVuZCkKICAg"
    "ICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNvcihjdXJzb3IpCiAgICAgICAgc2VsZi5"
    "fY2hhdF9kaXNwbGF5Lmluc2VydFBsYWluVGV4dCgiXG5cbiIpCgogICAgICAgICMgTG9nIHRvIG1lbW"
    "9yeSBhbmQgc2Vzc2lvbgogICAgICAgIHNlbGYuX3Rva2VuX2NvdW50ICs9IGxlbihyZXNwb25zZS5zc"
    "GxpdCgpKQogICAgICAgIHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdlKCJhc3Npc3RhbnQiLCByZXNw"
    "b25zZSkKICAgICAgICBzZWxmLl9tZW1vcnkuYXBwZW5kX21lc3NhZ2Uoc2VsZi5fc2Vzc2lvbl9pZCw"
    "gImFzc2lzdGFudCIsIHJlc3BvbnNlKQogICAgICAgIHNlbGYuX21lbW9yeS5hcHBlbmRfbWVtb3J5KH"
    "NlbGYuX3Nlc3Npb25faWQsICIiLCByZXNwb25zZSkKCiAgICAgICAgIyBVcGRhdGUgYmxvb2Qgc3BoZ"
    "XJlCiAgICAgICAgaWYgc2VsZi5fbGVmdF9vcmIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYu"
    "X2xlZnRfb3JiLnNldEZpbGwoCiAgICAgICAgICAgICAgICBtaW4oMS4wLCBzZWxmLl90b2tlbl9jb3V"
    "udCAvIDQwOTYuMCkKICAgICAgICAgICAgKQoKICAgICAgICAjIFJlLWVuYWJsZSBpbnB1dAogICAgIC"
    "AgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZ"
    "C5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0Rm9jdXMoKQoKICAg"
    "ICAgICAjIFJlc3VtZSBpZGxlIHRpbWVyCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIGl"
    "mIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIH"
    "RyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5yZXN1bWVfam9iKCJpZGxlX3RyYW5zb"
    "Wlzc2lvbiIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNz"
    "CgogICAgICAgICMgU2NoZWR1bGUgc2VudGltZW50IGFuYWx5c2lzICg1IHNlY29uZCBkZWxheSkKICA"
    "gICAgICBRVGltZXIuc2luZ2xlU2hvdCg1MDAwLCBsYW1iZGE6IHNlbGYuX3J1bl9zZW50aW1lbnQocm"
    "VzcG9uc2UpKQoKICAgIGRlZiBfcnVuX3NlbnRpbWVudChzZWxmLCByZXNwb25zZTogc3RyKSAtPiBOb"
    "25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIHJldHVybgog"
    "ICAgICAgIHNlbGYuX3NlbnRfd29ya2VyID0gU2VudGltZW50V29ya2VyKHNlbGYuX2FkYXB0b3IsIHJ"
    "lc3BvbnNlKQogICAgICAgIHNlbGYuX3NlbnRfd29ya2VyLmZhY2VfcmVhZHkuY29ubmVjdChzZWxmLl"
    "9vbl9zZW50aW1lbnQpCiAgICAgICAgc2VsZi5fc2VudF93b3JrZXIuc3RhcnQoKQoKICAgIGRlZiBfb"
    "25fc2VudGltZW50KHNlbGYsIGVtb3Rpb246IHN0cikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl9m"
    "YWNlX3RpbWVyX21ncjoKICAgICAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3Iuc2V0X2ZhY2UoZW1"
    "vdGlvbikKCiAgICBkZWYgX29uX2Vycm9yKHNlbGYsIGVycm9yOiBzdHIpIC0+IE5vbmU6CiAgICAgIC"
    "Agc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZXJyb3IpCiAgICAgICAgc2VsZi5fZGlhZ190YWIub"
    "G9nKGYiW0dFTkVSQVRJT04gRVJST1JdIHtlcnJvcn0iLCAiRVJST1IiKQogICAgICAgIGlmIHNlbGYu"
    "X2ZhY2VfdGltZXJfbWdyOgogICAgICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nci5zZXRfZmFjZSg"
    "icGFuaWNrZWQiKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkVSUk9SIikKICAgICAgICBzZWxmLl"
    "9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hY"
    "mxlZChUcnVlKQoKICAgICMg4pSA4pSAIFRPUlBPUiBTWVNURU0g4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX29uX3RvcnBvcl9zdGF0Z"
    "V9jaGFuZ2VkKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fdG9ycG9yX3N0"
    "YXRlID0gc3RhdGUKCiAgICAgICAgaWYgc3RhdGUgPT0gIlNVU1BFTkQiOgogICAgICAgICAgICBzZWx"
    "mLl9lbnRlcl90b3Jwb3IocmVhc29uPSJtYW51YWwg4oCUIFNVU1BFTkQgbW9kZSBzZWxlY3RlZCIpCi"
    "AgICAgICAgZWxpZiBzdGF0ZSA9PSAiQVdBS0UiOgogICAgICAgICAgICAjIEFsd2F5cyBleGl0IHRvc"
    "nBvciB3aGVuIHN3aXRjaGluZyB0byBBV0FLRSDigJQKICAgICAgICAgICAgIyBldmVuIHdpdGggT2xs"
    "YW1hIGJhY2tlbmQgd2hlcmUgbW9kZWwgaXNuJ3QgdW5sb2FkZWQsCiAgICAgICAgICAgICMgd2UgbmV"
    "lZCB0byByZS1lbmFibGUgVUkgYW5kIHJlc2V0IHN0YXRlCiAgICAgICAgICAgIHNlbGYuX2V4aXRfdG"
    "9ycG9yKCkKICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9IDAKICAgICAgICAgI"
    "CAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgICA9IDAKICAgICAgICBlbGlmIHN0YXRlID09ICJBVVRP"
    "IjoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIltUT1JQT1J"
    "dIEFVVE8gbW9kZSDigJQgbW9uaXRvcmluZyBWUkFNIHByZXNzdXJlLiIsICJJTkZPIgogICAgICAgIC"
    "AgICApCgogICAgZGVmIF9lbnRlcl90b3Jwb3Ioc2VsZiwgcmVhc29uOiBzdHIgPSAibWFudWFsIikgL"
    "T4gTm9uZToKICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAg"
    "ICAgIHJldHVybiAgIyBBbHJlYWR5IGluIHRvcnBvcgoKICAgICAgICBzZWxmLl90b3Jwb3Jfc2luY2U"
    "gPSBkYXRldGltZS5ub3coKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUT1JQT1JdIEVudG"
    "VyaW5nIHRvcnBvcjoge3JlYXNvbn0iLCAiV0FSTiIpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoI"
    "lNZU1RFTSIsICJUaGUgdmVzc2VsIGdyb3dzIGNyb3dkZWQuIEkgd2l0aGRyYXcuIikKCiAgICAgICAg"
    "IyBVbmxvYWQgbW9kZWwgZnJvbSBWUkFNCiAgICAgICAgaWYgc2VsZi5fbW9kZWxfbG9hZGVkIGFuZCB"
    "pc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIC"
    "AgICAgICAgICAgICBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IpOgogICAgICAgICAgICB0cnk6CiAgI"
    "CAgICAgICAgICAgICBpZiBzZWxmLl9hZGFwdG9yLl9tb2RlbCBpcyBub3QgTm9uZToKICAgICAgICAg"
    "ICAgICAgICAgICBkZWwgc2VsZi5fYWRhcHRvci5fbW9kZWwKICAgICAgICAgICAgICAgICAgICBzZWx"
    "mLl9hZGFwdG9yLl9tb2RlbCA9IE5vbmUKICAgICAgICAgICAgICAgIGlmIFRPUkNIX09LOgogICAgIC"
    "AgICAgICAgICAgICAgIHRvcmNoLmN1ZGEuZW1wdHlfY2FjaGUoKQogICAgICAgICAgICAgICAgc2VsZ"
    "i5fYWRhcHRvci5fbG9hZGVkID0gRmFsc2UKICAgICAgICAgICAgICAgIHNlbGYuX21vZGVsX2xvYWRl"
    "ZCAgICA9IEZhbHNlCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIE1"
    "vZGVsIHVubG9hZGVkIGZyb20gVlJBTS4iLCAiT0siKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW"
    "9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgI"
    "CAgICAgZiJbVE9SUE9SXSBNb2RlbCB1bmxvYWQgZXJyb3I6IHtlfSIsICJFUlJPUiIKICAgICAgICAg"
    "ICAgICAgICkKCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKCJuZXV0cmFsIikKICAgICAgICB"
    "zZWxmLl9zZXRfc3RhdHVzKCJUT1JQT1IiKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZW"
    "QoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKCiAgICBkZ"
    "WYgX2V4aXRfdG9ycG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBDYWxjdWxhdGUgc3VzcGVuZGVk"
    "IGR1cmF0aW9uCiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlOgogICAgICAgICAgICBkZWx0YSA"
    "9IGRhdGV0aW1lLm5vdygpIC0gc2VsZi5fdG9ycG9yX3NpbmNlCiAgICAgICAgICAgIHNlbGYuX3N1c3"
    "BlbmRlZF9kdXJhdGlvbiA9IGZvcm1hdF9kdXJhdGlvbihkZWx0YS50b3RhbF9zZWNvbmRzKCkpCiAgI"
    "CAgICAgICAgIHNlbGYuX3RvcnBvcl9zaW5jZSA9IE5vbmUKCiAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKCJbVE9SUE9SXSBXYWtpbmcgZnJvbSB0b3Jwb3IuLi4iLCAiSU5GTyIpCgogICAgICAgIGlmIHN"
    "lbGYuX21vZGVsX2xvYWRlZDoKICAgICAgICAgICAgIyBPbGxhbWEgYmFja2VuZCDigJQgbW9kZWwgd2"
    "FzIG5ldmVyIHVubG9hZGVkLCBqdXN0IHJlLWVuYWJsZSBVSQogICAgICAgICAgICBzZWxmLl9hcHBlb"
    "mRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7REVD"
    "S19OQU1FfSBzdGlycyAiCiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9"
    "uIG9yICdicmllZmx5J30gZWxhcHNlZCkuIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2"
    "FwcGVuZF9jaGF0KCJTWVNURU0iLCAiVGhlIGNvbm5lY3Rpb24gaG9sZHMuIFNoZSBpcyBsaXN0ZW5pb"
    "mcuIikKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiSURMRSIpCiAgICAgICAgICAgIHNlbGYu"
    "X3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V"
    "0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIEFXQU"
    "tFIG1vZGUg4oCUIGF1dG8tdG9ycG9yIGRpc2FibGVkLiIsICJJTkZPIikKICAgICAgICBlbHNlOgogI"
    "CAgICAgICAgICAjIExvY2FsIG1vZGVsIHdhcyB1bmxvYWRlZCDigJQgbmVlZCBmdWxsIHJlbG9hZAog"
    "ICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiVGh"
    "lIHZlc3NlbCBlbXB0aWVzLiB7REVDS19OQU1FfSBzdGlycyBmcm9tIHRvcnBvciAiCiAgICAgICAgIC"
    "AgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICdicmllZmx5J30gZWxhcHNlZCkuI"
    "gogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkxPQURJTkciKQogICAg"
    "ICAgICAgICBzZWxmLl9sb2FkZXIgPSBNb2RlbExvYWRlcldvcmtlcihzZWxmLl9hZGFwdG9yKQogICA"
    "gICAgICAgICBzZWxmLl9sb2FkZXIubWVzc2FnZS5jb25uZWN0KAogICAgICAgICAgICAgICAgbGFtYm"
    "RhIG06IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBtKSkKICAgICAgICAgICAgc2VsZi5fbG9hZ"
    "GVyLmVycm9yLmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fYXBwZW5kX2No"
    "YXQoIkVSUk9SIiwgZSkpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5sb2FkX2NvbXBsZXRlLmNvbm5"
    "lY3Qoc2VsZi5fb25fbG9hZF9jb21wbGV0ZSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmZpbmlzaG"
    "VkLmNvbm5lY3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICBzZWxmLl9hY3Rpd"
    "mVfdGhyZWFkcy5hcHBlbmQoc2VsZi5fbG9hZGVyKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuc3Rh"
    "cnQoKQoKICAgIGRlZiBfY2hlY2tfdnJhbV9wcmVzc3VyZShzZWxmKSAtPiBOb25lOgogICAgICAgICI"
    "iIgogICAgICAgIENhbGxlZCBldmVyeSA1IHNlY29uZHMgZnJvbSBBUFNjaGVkdWxlciB3aGVuIHRvcn"
    "BvciBzdGF0ZSBpcyBBVVRPLgogICAgICAgIE9ubHkgdHJpZ2dlcnMgdG9ycG9yIGlmIGV4dGVybmFsI"
    "FZSQU0gdXNhZ2UgZXhjZWVkcyB0aHJlc2hvbGQKICAgICAgICBBTkQgaXMgc3VzdGFpbmVkIOKAlCBu"
    "ZXZlciB0cmlnZ2VycyBvbiB0aGUgcGVyc29uYSdzIG93biBmb290cHJpbnQuCiAgICAgICAgIiIiCiA"
    "gICAgICAgaWYgc2VsZi5fdG9ycG9yX3N0YXRlICE9ICJBVVRPIjoKICAgICAgICAgICAgcmV0dXJuCi"
    "AgICAgICAgaWYgbm90IE5WTUxfT0sgb3Igbm90IGdwdV9oYW5kbGU6CiAgICAgICAgICAgIHJldHVyb"
    "gogICAgICAgIGlmIHNlbGYuX2RlY2tfdnJhbV9iYXNlIDw9IDA6CiAgICAgICAgICAgIHJldHVybgoK"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgIG1lbV9pbmZvICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWV"
    "tb3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICB0b3RhbF91c2VkID0gbWVtX2luZm8udXNlZC"
    "AvIDEwMjQqKjMKICAgICAgICAgICAgZXh0ZXJuYWwgICA9IHRvdGFsX3VzZWQgLSBzZWxmLl9kZWNrX"
    "3ZyYW1fYmFzZQoKICAgICAgICAgICAgaWYgZXh0ZXJuYWwgPiBzZWxmLl9FWFRFUk5BTF9WUkFNX1RP"
    "UlBPUl9HQjoKICAgICAgICAgICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZTo"
    "KICAgICAgICAgICAgICAgICAgICByZXR1cm4gICMgQWxyZWFkeSBpbiB0b3Jwb3Ig4oCUIGRvbid0IG"
    "tlZXAgY291bnRpbmcKICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgKz0gM"
    "QogICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgICAgPSAwCiAgICAgICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9"
    "dIEV4dGVybmFsIFZSQU0gcHJlc3N1cmU6ICIKICAgICAgICAgICAgICAgICAgICBmIntleHRlcm5hbD"
    "ouMmZ9R0IgIgogICAgICAgICAgICAgICAgICAgIGYiKHRpY2sge3NlbGYuX3ZyYW1fcHJlc3N1cmVfd"
    "Glja3N9LyIKICAgICAgICAgICAgICAgICAgICBmIntzZWxmLl9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tT"
    "fSkiLCAiV0FSTiIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlmIChzZWxmLl92cmF"
    "tX3ByZXNzdXJlX3RpY2tzID49IHNlbGYuX1RPUlBPUl9TVVNUQUlORURfVElDS1MKICAgICAgICAgIC"
    "AgICAgICAgICAgICAgYW5kIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBOb25lKToKICAgICAgICAgICAgI"
    "CAgICAgICBzZWxmLl9lbnRlcl90b3Jwb3IoCiAgICAgICAgICAgICAgICAgICAgICAgIHJlYXNvbj1m"
    "ImF1dG8g4oCUIHtleHRlcm5hbDouMWZ9R0IgZXh0ZXJuYWwgVlJBTSAiCiAgICAgICAgICAgICAgICA"
    "gICAgICAgICAgICAgICBmInByZXNzdXJlIHN1c3RhaW5lZCIKICAgICAgICAgICAgICAgICAgICApCi"
    "AgICAgICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9IDAgICMgcmVzZXQgY"
    "WZ0ZXIgZW50ZXJpbmcgdG9ycG9yCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxm"
    "Ll92cmFtX3ByZXNzdXJlX3RpY2tzID0gMAogICAgICAgICAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3N"
    "pbmNlIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2"
    "tzICs9IDEKICAgICAgICAgICAgICAgICAgICBhdXRvX3dha2UgPSBDRkdbInNldHRpbmdzIl0uZ2V0K"
    "AogICAgICAgICAgICAgICAgICAgICAgICAiYXV0b193YWtlX29uX3JlbGllZiIsIEZhbHNlCiAgICAg"
    "ICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIGlmIChhdXRvX3dha2UgYW5kCiAgICA"
    "gICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyA+PSBzZWxmLl9XQU"
    "tFX1NVU1RBSU5FRF9USUNLUyk6CiAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsa"
    "WVmX3RpY2tzID0gMAogICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl9leGl0X3RvcnBvcigpCgog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9"
    "nKAogICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9dIFZSQU0gY2hlY2sgZXJyb3I6IHtlfSIsIC"
    "JFUlJPUiIKICAgICAgICAgICAgKQoKICAgICMg4pSA4pSAIEFQU0NIRURVTEVSIFNFVFVQIOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9zZXR1cF9zY2hlZH"
    "VsZXIoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGZyb20gYXBzY2hlZHVsZ"
    "XIuc2NoZWR1bGVycy5iYWNrZ3JvdW5kIGltcG9ydCBCYWNrZ3JvdW5kU2NoZWR1bGVyCiAgICAgICAg"
    "ICAgIHNlbGYuX3NjaGVkdWxlciA9IEJhY2tncm91bmRTY2hlZHVsZXIoCiAgICAgICAgICAgICAgICB"
    "qb2JfZGVmYXVsdHM9eyJtaXNmaXJlX2dyYWNlX3RpbWUiOiA2MH0KICAgICAgICAgICAgKQogICAgIC"
    "AgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyID0gTm9uZQogI"
    "CAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAiW1NDSEVEVUxFUl0g"
    "YXBzY2hlZHVsZXIgbm90IGF2YWlsYWJsZSDigJQgIgogICAgICAgICAgICAgICAgImlkbGUsIGF1dG9"
    "zYXZlLCBhbmQgcmVmbGVjdGlvbiBkaXNhYmxlZC4iLCAiV0FSTiIKICAgICAgICAgICAgKQogICAgIC"
    "AgICAgICByZXR1cm4KCiAgICAgICAgaW50ZXJ2YWxfbWluID0gQ0ZHWyJzZXR0aW5ncyJdLmdldCgiY"
    "XV0b3NhdmVfaW50ZXJ2YWxfbWludXRlcyIsIDEwKQoKICAgICAgICAjIEF1dG9zYXZlCiAgICAgICAg"
    "c2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAgICAgICAgICAgIHNlbGYuX2F1dG9zYXZlLCAiaW50ZXJ"
    "2YWwiLAogICAgICAgICAgICBtaW51dGVzPWludGVydmFsX21pbiwgaWQ9ImF1dG9zYXZlIgogICAgIC"
    "AgICkKCiAgICAgICAgIyBWUkFNIHByZXNzdXJlIGNoZWNrIChldmVyeSA1cykKICAgICAgICBzZWxmL"
    "l9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgc2VsZi5fY2hlY2tfdnJhbV9wcmVzc3VyZSwg"
    "ImludGVydmFsIiwKICAgICAgICAgICAgc2Vjb25kcz01LCBpZD0idnJhbV9jaGVjayIKICAgICAgICA"
    "pCgogICAgICAgICMgSWRsZSB0cmFuc21pc3Npb24gKHN0YXJ0cyBwYXVzZWQg4oCUIGVuYWJsZWQgYn"
    "kgaWRsZSB0b2dnbGUpCiAgICAgICAgaWRsZV9taW4gPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJpZGxlX"
    "21pbl9taW51dGVzIiwgMTApCiAgICAgICAgaWRsZV9tYXggPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJp"
    "ZGxlX21heF9taW51dGVzIiwgMzApCiAgICAgICAgaWRsZV9pbnRlcnZhbCA9IChpZGxlX21pbiArIGl"
    "kbGVfbWF4KSAvLyAyCgogICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAgICAgIC"
    "BzZWxmLl9maXJlX2lkbGVfdHJhbnNtaXNzaW9uLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBtaW51d"
    "GVzPWlkbGVfaW50ZXJ2YWwsIGlkPSJpZGxlX3RyYW5zbWlzc2lvbiIKICAgICAgICApCgogICAgICAg"
    "ICMgQ3ljbGUgd2lkZ2V0IHJlZnJlc2ggKGV2ZXJ5IDYgaG91cnMpCiAgICAgICAgaWYgc2VsZi5fY3l"
    "jbGVfd2lkZ2V0IGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIuYWRkX2pvYi"
    "gKICAgICAgICAgICAgICAgIHNlbGYuX2N5Y2xlX3dpZGdldC51cGRhdGVQaGFzZSwgImludGVydmFsI"
    "iwKICAgICAgICAgICAgICAgIGhvdXJzPTYsIGlkPSJtb29uX3JlZnJlc2giCiAgICAgICAgICAgICkK"
    "CiAgICAgICAgIyBOT1RFOiBzY2hlZHVsZXIuc3RhcnQoKSBpcyBjYWxsZWQgZnJvbSBzdGFydF9zY2h"
    "lZHVsZXIoKQogICAgICAgICMgd2hpY2ggaXMgdHJpZ2dlcmVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdC"
    "BBRlRFUiB0aGUgd2luZG93CiAgICAgICAgIyBpcyBzaG93biBhbmQgdGhlIFF0IGV2ZW50IGxvb3Aga"
    "XMgcnVubmluZy4KICAgICAgICAjIERvIE5PVCBjYWxsIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpIGhl"
    "cmUuCgogICAgZGVmIHN0YXJ0X3NjaGVkdWxlcihzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICA"
    "gICAgIENhbGxlZCB2aWEgUVRpbWVyLnNpbmdsZVNob3QgYWZ0ZXIgd2luZG93LnNob3coKSBhbmQgYX"
    "BwLmV4ZWMoKSBiZWdpbnMuCiAgICAgICAgRGVmZXJyZWQgdG8gZW5zdXJlIFF0IGV2ZW50IGxvb3Aga"
    "XMgcnVubmluZyBiZWZvcmUgYmFja2dyb3VuZCB0aHJlYWRzIHN0YXJ0LgogICAgICAgICIiIgogICAg"
    "ICAgIGlmIHNlbGYuX3NjaGVkdWxlciBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB"
    "0cnk6CiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpCiAgICAgICAgICAgICMgSWRsZS"
    "BzdGFydHMgcGF1c2VkCiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVfd"
    "HJhbnNtaXNzaW9uIikKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbU0NIRURVTEVSXSBB"
    "UFNjaGVkdWxlciBzdGFydGVkLiIsICJPSyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgo"
    "gICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbU0NIRURVTEVSXSBTdGFydCBlcnJvcjoge2"
    "V9IiwgIkVSUk9SIikKCiAgICBkZWYgX2F1dG9zYXZlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5O"
    "gogICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5zYXZlKCkKICAgICAgICAgICAgc2VsZi5fam91cm5h"
    "bF9zaWRlYmFyLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoVHJ1ZSkKICAgICAgICAgICAgUVRpbWVyLnN"
    "pbmdsZVNob3QoCiAgICAgICAgICAgICAgICAzMDAwLCBsYW1iZGE6IHNlbGYuX2pvdXJuYWxfc2lkZW"
    "Jhci5zZXRfYXV0b3NhdmVfaW5kaWNhdG9yKEZhbHNlKQogICAgICAgICAgICApCiAgICAgICAgICAgI"
    "HNlbGYuX2RpYWdfdGFiLmxvZygiW0FVVE9TQVZFXSBTZXNzaW9uIHNhdmVkLiIsICJJTkZPIikKICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyh"
    "mIltBVVRPU0FWRV0gRXJyb3I6IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIF9maXJlX2lkbGVfdHJhbn"
    "NtaXNzaW9uKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuX21vZGVsX2xvYWRlZCBvc"
    "iBzZWxmLl9zdGF0dXMgPT0gIkdFTkVSQVRJTkciOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBp"
    "ZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICMgSW4gdG9ycG9yIOK"
    "AlCBjb3VudCB0aGUgcGVuZGluZyB0aG91Z2h0IGJ1dCBkb24ndCBnZW5lcmF0ZQogICAgICAgICAgIC"
    "BzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgKz0gMQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhY"
    "i5sb2coCiAgICAgICAgICAgICAgICBmIltJRExFXSBJbiB0b3Jwb3Ig4oCUIHBlbmRpbmcgdHJhbnNt"
    "aXNzaW9uICIKICAgICAgICAgICAgICAgIGYiI3tzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnN9Iiw"
    "gIklORk8iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIG1vZGUgPSByYW"
    "5kb20uY2hvaWNlKFsiREVFUEVOSU5HIiwiQlJBTkNISU5HIiwiU1lOVEhFU0lTIl0pCiAgICAgICAgd"
    "mFtcGlyZV9jdHggPSBidWlsZF92YW1waXJlX2NvbnRleHQoKQogICAgICAgIGhpc3RvcnkgPSBzZWxm"
    "Ll9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCgogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyID0gSWRsZVd"
    "vcmtlcigKICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwKICAgICAgICAgICAgU1lTVEVNX1BST01QVF"
    "9CQVNFLAogICAgICAgICAgICBoaXN0b3J5LAogICAgICAgICAgICBtb2RlPW1vZGUsCiAgICAgICAgI"
    "CAgIHZhbXBpcmVfY29udGV4dD12YW1waXJlX2N0eCwKICAgICAgICApCiAgICAgICAgZGVmIF9vbl9p"
    "ZGxlX3JlYWR5KHQ6IHN0cikgLT4gTm9uZToKICAgICAgICAgICAgIyBGbGlwIHRvIFNlbGYgdGFiIGF"
    "uZCBhcHBlbmQgdGhlcmUKICAgICAgICAgICAgc2VsZi5fbWFpbl90YWJzLnNldEN1cnJlbnRJbmRleC"
    "gxKQogICAgICAgICAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTSIpCiAgICAgI"
    "CAgICAgIHNlbGYuX3NlbGZfZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0"
    "eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICAgICA"
    "gZidbe3RzfV0gW3ttb2RlfV08L3NwYW4+PGJyPicKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bG"
    "U9ImNvbG9yOntDX0dPTER9OyI+e3R9PC9zcGFuPjxicj4nCiAgICAgICAgICAgICkKICAgICAgICAgI"
    "CAgc2VsZi5fc2VsZl90YWIuYXBwZW5kKCJOQVJSQVRJVkUiLCB0KQoKICAgICAgICBzZWxmLl9pZGxl"
    "X3dvcmtlci50cmFuc21pc3Npb25fcmVhZHkuY29ubmVjdChfb25faWRsZV9yZWFkeSkKICAgICAgICB"
    "zZWxmLl9pZGxlX3dvcmtlci5lcnJvcl9vY2N1cnJlZC5jb25uZWN0KAogICAgICAgICAgICBsYW1iZG"
    "EgZTogc2VsZi5fZGlhZ190YWIubG9nKGYiW0lETEUgRVJST1JdIHtlfSIsICJFUlJPUiIpCiAgICAgI"
    "CAgKQogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyLnN0YXJ0KCkKCiAgICAjIOKUgOKUgCBKT1VSTkFM"
    "IFNFU1NJT04gTE9BRElORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfbG9hZF9qb"
    "3VybmFsX3Nlc3Npb24oc2VsZiwgZGF0ZV9zdHI6IHN0cikgLT4gTm9uZToKICAgICAgICBjdHggPSBz"
    "ZWxmLl9zZXNzaW9ucy5sb2FkX3Nlc3Npb25fYXNfY29udGV4dChkYXRlX3N0cikKICAgICAgICBpZiB"
    "ub3QgY3R4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIl"
    "tKT1VSTkFMXSBObyBzZXNzaW9uIGZvdW5kIGZvciB7ZGF0ZV9zdHJ9IiwgIldBUk4iCiAgICAgICAgI"
    "CAgICkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNldF9q"
    "b3VybmFsX2xvYWRlZChkYXRlX3N0cikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICA"
    "gICAgIGYiW0pPVVJOQUxdIExvYWRlZCBzZXNzaW9uIGZyb20ge2RhdGVfc3RyfSBhcyBjb250ZXh0Li"
    "AiCiAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgbm93IGF3YXJlIG9mIHRoYXQgY29udmVyc2F0a"
    "W9uLiIsICJPSyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAg"
    "ICAgICAgICAgIGYiQSBtZW1vcnkgc3RpcnMuLi4gdGhlIGpvdXJuYWwgb2Yge2RhdGVfc3RyfSBvcGV"
    "ucyBiZWZvcmUgaGVyLiIKICAgICAgICApCiAgICAgICAgIyBOb3RpZnkgTW9yZ2FubmEKICAgICAgIC"
    "BpZiBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIG5vdGUgPSAoCiAgICAgICAgICAgICAgI"
    "CBmIltKT1VSTkFMIExPQURFRF0gVGhlIHVzZXIgaGFzIG9wZW5lZCB0aGUgam91cm5hbCBmcm9tICIK"
    "ICAgICAgICAgICAgICAgIGYie2RhdGVfc3RyfS4gQWNrbm93bGVkZ2UgdGhpcyBicmllZmx5IOKAlCB"
    "5b3Ugbm93IGhhdmUgIgogICAgICAgICAgICAgICAgZiJhd2FyZW5lc3Mgb2YgdGhhdCBjb252ZXJzYX"
    "Rpb24uIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdlK"
    "CJzeXN0ZW0iLCBub3RlKQoKICAgIGRlZiBfY2xlYXJfam91cm5hbF9zZXNzaW9uKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuY2xlYXJfbG9hZGVkX2pvdXJuYWwoKQogICAgICAgIHN"
    "lbGYuX2RpYWdfdGFiLmxvZygiW0pPVVJOQUxdIEpvdXJuYWwgY29udGV4dCBjbGVhcmVkLiIsICJJTk"
    "ZPIikKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgIlRoZSBqb"
    "3VybmFsIGNsb3Nlcy4gT25seSB0aGUgcHJlc2VudCByZW1haW5zLiIKICAgICAgICApCgogICAgIyDi"
    "lIDilIAgU1RBVFMgVVBEQVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF91cGRhdGVfc3RhdHMoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBlbGFwc2VkID0gaW50KHRpbWUudGltZSgpIC0gc2VsZi5fc2Vzc2lvbl9zdGFydCkKICAgICA"
    "gICBoLCBtLCBzID0gZWxhcHNlZCAvLyAzNjAwLCAoZWxhcHNlZCAlIDM2MDApIC8vIDYwLCBlbGFwc2"
    "VkICUgNjAKICAgICAgICBzZXNzaW9uX3N0ciA9IGYie2g6MDJkfTp7bTowMmR9OntzOjAyZH0iCgogI"
    "CAgICAgIHNlbGYuX2h3X3BhbmVsLnNldF9zdGF0dXNfbGFiZWxzKAogICAgICAgICAgICBzZWxmLl9z"
    "dGF0dXMsCiAgICAgICAgICAgIENGR1sibW9kZWwiXS5nZXQoInR5cGUiLCJsb2NhbCIpLnVwcGVyKCk"
    "sCiAgICAgICAgICAgIHNlc3Npb25fc3RyLAogICAgICAgICAgICBzdHIoc2VsZi5fdG9rZW5fY291bn"
    "QpLAogICAgICAgICkKICAgICAgICBzZWxmLl9od19wYW5lbC51cGRhdGVfc3RhdHMoKQoKICAgICAgI"
    "CAjIExlZnQgc3BoZXJlID0gYWN0aXZlIHJlc2VydmUgZnJvbSBydW50aW1lIHRva2VuIHBvb2wKICAg"
    "ICAgICBsZWZ0X29yYl9maWxsID0gbWluKDEuMCwgc2VsZi5fdG9rZW5fY291bnQgLyA0MDk2LjApCiA"
    "gICAgICAgaWYgc2VsZi5fbGVmdF9vcmIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2xlZn"
    "Rfb3JiLnNldEZpbGwobGVmdF9vcmJfZmlsbCwgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICMgUmlna"
    "HQgc3BoZXJlID0gVlJBTSBhdmFpbGFiaWxpdHkKICAgICAgICBpZiBzZWxmLl9yaWdodF9vcmIgaXMg"
    "bm90IE5vbmU6CiAgICAgICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAgICAgICA"
    "gICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgbWVtID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW"
    "1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICAgICAgdnJhbV91c2VkID0gbWVtLnVzZ"
    "WQgIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgICAgIHZyYW1fdG90ICA9IG1lbS50b3RhbCAvIDEw"
    "MjQqKjMKICAgICAgICAgICAgICAgICAgICByaWdodF9vcmJfZmlsbCA9IG1heCgwLjAsIDEuMCAtICh"
    "2cmFtX3VzZWQgLyB2cmFtX3RvdCkpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fcmlnaHRfb3JiLn"
    "NldEZpbGwocmlnaHRfb3JiX2ZpbGwsIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAgICAgZXhjZ"
    "XB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBzZWxmLl9yaWdodF9vcmIuc2V0RmlsbCgw"
    "LjAsIGF2YWlsYWJsZT1GYWxzZSkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGY"
    "uX3JpZ2h0X29yYi5zZXRGaWxsKDAuMCwgYXZhaWxhYmxlPUZhbHNlKQoKICAgICAgICAjIFByaW1hcn"
    "kgZXNzZW5jZSA9IGludmVyc2Ugb2YgbGVmdCBzcGhlcmUgZmlsbAogICAgICAgIGVzc2VuY2VfcHJpb"
    "WFyeV9yYXRpbyA9IDEuMCAtIGxlZnRfb3JiX2ZpbGwKICAgICAgICBpZiBBSV9TVEFURVNfRU5BQkxF"
    "RDoKICAgICAgICAgICAgc2VsZi5fZXNzZW5jZV9wcmltYXJ5X2dhdWdlLnNldFZhbHVlKGVzc2VuY2V"
    "fcHJpbWFyeV9yYXRpbyAqIDEwMCwgZiJ7ZXNzZW5jZV9wcmltYXJ5X3JhdGlvKjEwMDouMGZ9JSIpCg"
    "ogICAgICAgICMgU2Vjb25kYXJ5IGVzc2VuY2UgPSBSQU0gZnJlZQogICAgICAgIGlmIEFJX1NUQVRFU"
    "19FTkFCTEVEOgogICAgICAgICAgICBpZiBQU1VUSUxfT0s6CiAgICAgICAgICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgICAgICAgICAgbWVtICAgICAgID0gcHN1dGlsLnZpcnR1YWxfbWVtb3J5KCkKICAgICA"
    "gICAgICAgICAgICAgICBlc3NlbmNlX3NlY29uZGFyeV9yYXRpbyAgPSAxLjAgLSAobWVtLnVzZWQgLy"
    "BtZW0udG90YWwpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z"
    "2Uuc2V0VmFsdWUoCiAgICAgICAgICAgICAgICAgICAgICAgIGVzc2VuY2Vfc2Vjb25kYXJ5X3JhdGlv"
    "ICogMTAwLCBmIntlc3NlbmNlX3NlY29uZGFyeV9yYXRpbyoxMDA6LjBmfSUiCiAgICAgICAgICAgICA"
    "gICAgICAgKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIC"
    "AgICBzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgI"
    "CAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZS5zZXRV"
    "bmF2YWlsYWJsZSgpCgogICAgICAgICMgVXBkYXRlIGpvdXJuYWwgc2lkZWJhciBhdXRvc2F2ZSBmbGF"
    "zaAogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5yZWZyZXNoKCkKCiAgICAjIOKUgOKUgCBDSE"
    "FUIERJU1BMQVkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSACiAgICBkZWYgX2FwcGVuZF9jaGF0KHNlbGYsIHNwZWFrZXI6IHN0ciwgdGV4dDogc3"
    "RyKSAtPiBOb25lOgogICAgICAgIGNvbG9ycyA9IHsKICAgICAgICAgICAgIllPVSI6ICAgICBDX0dPT"
    "EQsCiAgICAgICAgICAgIERFQ0tfTkFNRS51cHBlcigpOkNfR09MRCwKICAgICAgICAgICAgIlNZU1RF"
    "TSI6ICBDX1BVUlBMRSwKICAgICAgICAgICAgIkVSUk9SIjogICBDX0JMT09ELAogICAgICAgIH0KICA"
    "gICAgICBsYWJlbF9jb2xvcnMgPSB7CiAgICAgICAgICAgICJZT1UiOiAgICAgQ19HT0xEX0RJTSwKIC"
    "AgICAgICAgICAgREVDS19OQU1FLnVwcGVyKCk6Q19DUklNU09OLAogICAgICAgICAgICAiU1lTVEVNI"
    "jogIENfUFVSUExFLAogICAgICAgICAgICAiRVJST1IiOiAgIENfQkxPT0QsCiAgICAgICAgfQogICAg"
    "ICAgIGNvbG9yICAgICAgID0gY29sb3JzLmdldChzcGVha2VyLCBDX0dPTEQpCiAgICAgICAgbGFiZWx"
    "fY29sb3IgPSBsYWJlbF9jb2xvcnMuZ2V0KHNwZWFrZXIsIENfR09MRF9ESU0pCiAgICAgICAgdGltZX"
    "N0YW1wICAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQoKICAgICAgICBpZiBzc"
    "GVha2VyID09ICJTWVNURU0iOgogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAog"
    "ICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU"
    "6MTBweDsiPicKICAgICAgICAgICAgICAgIGYnW3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAgIC"
    "AgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2xhYmVsX2NvbG9yfTsiPuKcpiB7dGV4dH08L3NwY"
    "W4+JwogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNw"
    "bGF5LmFwcGVuZCgKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfREl"
    "NfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcG"
    "FuPicKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntsYWJlbF9jb2xvcn07IGZvb"
    "nQtd2VpZ2h0OmJvbGQ7Ij4nCiAgICAgICAgICAgICAgICBmJ3tzcGVha2VyfSDinac8L3NwYW4+ICcK"
    "ICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07Ij57dGV4dH08L3NwYW4"
    "+JwogICAgICAgICAgICApCgogICAgICAgICMgQWRkIGJsYW5rIGxpbmUgYWZ0ZXIgTW9yZ2FubmEncy"
    "ByZXNwb25zZSAobm90IGR1cmluZyBzdHJlYW1pbmcpCiAgICAgICAgaWYgc3BlYWtlciA9PSBERUNLX"
    "05BTUUudXBwZXIoKToKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgiIikKCiAg"
    "ICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICA"
    "gICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQogIC"
    "AgICAgICkKCiAgICAjIOKUgOKUgCBTVEFUVVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2dldF"
    "9nb29nbGVfcmVmcmVzaF9pbnRlcnZhbF9tcyhzZWxmKSAtPiBpbnQ6CiAgICAgICAgc2V0dGluZ3MgP"
    "SBDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KQogICAgICAgIHZhbCA9IHNldHRpbmdzLmdldCgiZ29vZ2xl"
    "X2luYm91bmRfaW50ZXJ2YWxfbXMiLCAzMDAwMDApCiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXR"
    "1cm4gbWF4KDEwMDAsIGludCh2YWwpKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgIC"
    "AgIHJldHVybiAzMDAwMDAKCiAgICBkZWYgX2dldF9lbWFpbF9yZWZyZXNoX2ludGVydmFsX21zKHNlb"
    "GYpIC0+IGludDoKICAgICAgICBzZXR0aW5ncyA9IENGRy5nZXQoInNldHRpbmdzIiwge30pCiAgICAg"
    "ICAgdmFsID0gc2V0dGluZ3MuZ2V0KCJlbWFpbF9yZWZyZXNoX2ludGVydmFsX21zIiwgMzAwMDAwKQo"
    "gICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIG1heCgxMDAwLCBpbnQodmFsKSkKICAgICAgIC"
    "BleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4gMzAwMDAwCgogICAgZGVmIF9zZXRfZ"
    "29vZ2xlX3JlZnJlc2hfc2Vjb25kcyhzZWxmLCBzZWNvbmRzOiBpbnQpIC0+IE5vbmU6CiAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICBzZWNvbmRzID0gbWF4KDUsIG1pbig2MDAsIGludChzZWNvbmRzKSkpCiA"
    "gICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgQ0ZHWyJzZX"
    "R0aW5ncyJdWyJnb29nbGVfaW5ib3VuZF9pbnRlcnZhbF9tcyJdID0gc2Vjb25kcyAqIDEwMDAKICAgI"
    "CAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgZm9yIHRpbWVyIGluIChzZWxmLl9nb29nbGVfaW5i"
    "b3VuZF90aW1lciwgc2VsZi5fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lcik6CiAgICAgICAgICA"
    "gIGlmIHRpbWVyIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgdGltZXIuc3RhcnQoc2VsZi5fZ2"
    "V0X2dvb2dsZV9yZWZyZXNoX2ludGVydmFsX21zKCkpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nK"
    "GYiW1NFVFRJTkdTXSBHb29nbGUgcmVmcmVzaCBpbnRlcnZhbCBzZXQgdG8ge3NlY29uZHN9IHNlY29u"
    "ZChzKS4iLCAiT0siKQoKICAgIGRlZiBfc2V0X2VtYWlsX3JlZnJlc2hfbWludXRlc19mcm9tX3RleHQ"
    "oc2VsZiwgdGV4dDogc3RyKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgbWludXRlcy"
    "A9IG1heCgxLCBpbnQoZmxvYXQoc3RyKHRleHQpLnN0cmlwKCkpKSkKICAgICAgICBleGNlcHQgRXhjZ"
    "XB0aW9uOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBDRkdbInNldHRpbmdzIl1bImVtYWlsX3Jl"
    "ZnJlc2hfaW50ZXJ2YWxfbXMiXSA9IG1pbnV0ZXMgKiA2MDAwMAogICAgICAgIHNhdmVfY29uZmlnKEN"
    "GRykKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW1NFVFRJTkdTXSBFbW"
    "FpbCByZWZyZXNoIGludGVydmFsIHNldCB0byB7bWludXRlc30gbWludXRlKHMpIChjb25maWcgZm91b"
    "mRhdGlvbikuIiwKICAgICAgICAgICAgIklORk8iLAogICAgICAgICkKCiAgICBkZWYgX3NldF90aW1l"
    "em9uZV9hdXRvX2RldGVjdChzZWxmLCBlbmFibGVkOiBib29sKSAtPiBOb25lOgogICAgICAgIENGR1s"
    "ic2V0dGluZ3MiXVsidGltZXpvbmVfYXV0b19kZXRlY3QiXSA9IGJvb2woZW5hYmxlZCkKICAgICAgIC"
    "BzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAiW"
    "1NFVFRJTkdTXSBUaW1lIHpvbmUgbW9kZSBzZXQgdG8gYXV0by1kZXRlY3QuIiBpZiBlbmFibGVkIGVs"
    "c2UgIltTRVRUSU5HU10gVGltZSB6b25lIG1vZGUgc2V0IHRvIG1hbnVhbCBvdmVycmlkZS4iLAogICA"
    "gICAgICAgICAiSU5GTyIsCiAgICAgICAgKQoKICAgIGRlZiBfc2V0X3RpbWV6b25lX292ZXJyaWRlKH"
    "NlbGYsIHR6X25hbWU6IHN0cikgLT4gTm9uZToKICAgICAgICB0el92YWx1ZSA9IHN0cih0el9uYW1lI"
    "G9yICIiKS5zdHJpcCgpCiAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJ0aW1lem9uZV9vdmVycmlkZSJd"
    "ID0gdHpfdmFsdWUKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgaWYgdHpfdmFsdWU6CiA"
    "gICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltTRVRUSU5HU10gVGltZSB6b25lIG92ZXJyaW"
    "RlIHNldCB0byB7dHpfdmFsdWV9LiIsICJJTkZPIikKCiAgICBkZWYgX3NldF9zdGF0dXMoc2VsZiwgc"
    "3RhdHVzOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhdHVzID0gc3RhdHVzCiAgICAgICAg"
    "c3RhdHVzX2NvbG9ycyA9IHsKICAgICAgICAgICAgIklETEUiOiAgICAgICBDX0dPTEQsCiAgICAgICA"
    "gICAgICJHRU5FUkFUSU5HIjogQ19DUklNU09OLAogICAgICAgICAgICAiTE9BRElORyI6ICAgIENfUF"
    "VSUExFLAogICAgICAgICAgICAiRVJST1IiOiAgICAgIENfQkxPT0QsCiAgICAgICAgICAgICJPRkZMS"
    "U5FIjogICAgQ19CTE9PRCwKICAgICAgICAgICAgIlRPUlBPUiI6ICAgICBDX1BVUlBMRV9ESU0sCiAg"
    "ICAgICAgfQogICAgICAgIGNvbG9yID0gc3RhdHVzX2NvbG9ycy5nZXQoc3RhdHVzLCBDX1RFWFRfREl"
    "NKQoKICAgICAgICB0b3Jwb3JfbGFiZWwgPSBmIuKXiSB7VUlfVE9SUE9SX1NUQVRVU30iIGlmIHN0YX"
    "R1cyA9PSAiVE9SUE9SIiBlbHNlIGYi4peJIHtzdGF0dXN9IgogICAgICAgIHNlbGYuc3RhdHVzX2xhY"
    "mVsLnNldFRleHQodG9ycG9yX2xhYmVsKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZvbnQtc2l6ZTogMTJweDsgZm9udC1"
    "3ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQoKICAgIGRlZiBfYmxpbmsoc2VsZi"
    "kgLT4gTm9uZToKICAgICAgICBzZWxmLl9ibGlua19zdGF0ZSA9IG5vdCBzZWxmLl9ibGlua19zdGF0Z"
    "QogICAgICAgIGlmIHNlbGYuX3N0YXR1cyA9PSAiR0VORVJBVElORyI6CiAgICAgICAgICAgIGNoYXIg"
    "PSAi4peJIiBpZiBzZWxmLl9ibGlua19zdGF0ZSBlbHNlICLil44iCiAgICAgICAgICAgIHNlbGYuc3R"
    "hdHVzX2xhYmVsLnNldFRleHQoZiJ7Y2hhcn0gR0VORVJBVElORyIpCiAgICAgICAgZWxpZiBzZWxmLl"
    "9zdGF0dXMgPT0gIlRPUlBPUiI6CiAgICAgICAgICAgIGNoYXIgPSAi4peJIiBpZiBzZWxmLl9ibGlua"
    "19zdGF0ZSBlbHNlICLiipgiCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoCiAg"
    "ICAgICAgICAgICAgICBmIntjaGFyfSB7VUlfVE9SUE9SX1NUQVRVU30iCiAgICAgICAgICAgICkKCiA"
    "gICAjIOKUgOKUgCBJRExFIFRPR0dMRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfb25faWRsZV90b2dnbGVkKHNlbGYsIGV"
    "uYWJsZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJpZGxlX2VuYWJsZW"
    "QiXSA9IGVuYWJsZWQKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRUZXh0KCJJRExFIE9OIiBpZiBlb"
    "mFibGVkIGVsc2UgIklETEUgT0ZGIikKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHsnIzFhMTAwNScgaWYgZW5hYmxlZCBlbHNlIENfQkc"
    "zfTsgIgogICAgICAgICAgICBmImNvbG9yOiB7JyNjYzg4MjInIGlmIGVuYWJsZWQgZWxzZSBDX1RFWF"
    "RfRElNfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHsnI2NjODgyMicgaWYgZW5hY"
    "mxlZCBlbHNlIENfQk9SREVSfTsgIgogICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsgZm9u"
    "dC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYicGFkZGluZzogM3B"
    "4IDhweDsiCiAgICAgICAgKQogICAgICAgIHNhdmVfY29uZmlnKENGRykKICAgICAgICBpZiBzZWxmLl"
    "9zY2hlZHVsZXIgYW5kIHNlbGYuX3NjaGVkdWxlci5ydW5uaW5nOgogICAgICAgICAgICB0cnk6CiAgI"
    "CAgICAgICAgICAgICBpZiBlbmFibGVkOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxl"
    "ci5yZXN1bWVfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5"
    "fZGlhZ190YWIubG9nKCJbSURMRV0gSWRsZSB0cmFuc21pc3Npb24gZW5hYmxlZC4iLCAiT0siKQogIC"
    "AgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIucGF1c"
    "2Vfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKCJbSURMRV0gSWRsZSB0cmFuc21pc3Npb24gcGF1c2VkLiIsICJJTkZPIikKICAgICAgICA"
    "gICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG"
    "9nKGYiW0lETEVdIFRvZ2dsZSBlcnJvcjoge2V9IiwgIkVSUk9SIikKCiAgICAjIOKUgOKUgCBXSU5ET"
    "1cgQ09OVFJPTFMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SACiAgICBkZWYgX3RvZ2dsZV9mdWxsc2NyZWVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgc2VsZ"
    "i5pc0Z1bGxTY3JlZW4oKToKICAgICAgICAgICAgc2VsZi5zaG93Tm9ybWFsKCkKICAgICAgICAgICAg"
    "Q0ZHWyJzZXR0aW5ncyJdWyJmdWxsc2NyZWVuX2VuYWJsZWQiXSA9IEZhbHNlCiAgICAgICAgICAgIHN"
    "lbGYuX2ZzX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q1"
    "9CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogM"
    "XB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAg"
    "IGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDAgOHB4OyIKICAgICAgICAgICAgKQogICAgICA"
    "gIGVsc2U6CiAgICAgICAgICAgIHNlbGYuc2hvd0Z1bGxTY3JlZW4oKQogICAgICAgICAgICBDRkdbIn"
    "NldHRpbmdzIl1bImZ1bGxzY3JlZW5fZW5hYmxlZCJdID0gVHJ1ZQogICAgICAgICAgICBzZWxmLl9mc"
    "19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJTVNP"
    "Tl9ESU19OyBjb2xvcjoge0NfQ1JJTVNPTn07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHg"
    "gc29saWQge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbn"
    "Qtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwIDhweDsiCiAgICAgICAgICAgICkKICAgICAgICBzYXZlX"
    "2NvbmZpZyhDRkcpCgogICAgZGVmIF90b2dnbGVfYm9yZGVybGVzcyhzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIGlzX2JsID0gYm9vbChzZWxmLndpbmRvd0ZsYWdzKCkgJiBRdC5XaW5kb3dUeXBlLkZyYW1lbGV"
    "zc1dpbmRvd0hpbnQpCiAgICAgICAgaWYgaXNfYmw6CiAgICAgICAgICAgIHNlbGYuc2V0V2luZG93Rm"
    "xhZ3MoCiAgICAgICAgICAgICAgICBzZWxmLndpbmRvd0ZsYWdzKCkgJiB+UXQuV2luZG93VHlwZS5Gc"
    "mFtZWxlc3NXaW5kb3dIaW50CiAgICAgICAgICAgICkKICAgICAgICAgICAgQ0ZHWyJzZXR0aW5ncyJd"
    "WyJib3JkZXJsZXNzX2VuYWJsZWQiXSA9IEZhbHNlCiAgICAgICAgICAgIHNlbGYuX2JsX2J0bi5zZXR"
    "TdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0"
    "NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSS"
    "U1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6"
    "IGJvbGQ7IHBhZGRpbmc6IDAgOHB4OyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICA"
    "gICAgIGlmIHNlbGYuaXNGdWxsU2NyZWVuKCk6CiAgICAgICAgICAgICAgICBzZWxmLnNob3dOb3JtYW"
    "woKQogICAgICAgICAgICBzZWxmLnNldFdpbmRvd0ZsYWdzKAogICAgICAgICAgICAgICAgc2VsZi53a"
    "W5kb3dGbGFncygpIHwgUXQuV2luZG93VHlwZS5GcmFtZWxlc3NXaW5kb3dIaW50CiAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJib3JkZXJsZXNzX2VuYWJsZWQiXSA9IFRydWU"
    "KICAgICAgICAgICAgc2VsZi5fYmxfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmIm"
    "JhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsgY29sb3I6IHtDX0NSSU1TT059OyAiCiAgICAgICAgI"
    "CAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OyBmb250LXNpemU6IDlweDsgIgog"
    "ICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMCA4cHg7IgogICAgICA"
    "gICAgICApCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIHNlbGYuc2hvdygpCgogICAgZG"
    "VmIF9leHBvcnRfY2hhdChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIkV4cG9ydCBjdXJyZW50IHBlc"
    "nNvbmEgY2hhdCB0YWIgY29udGVudCB0byBhIFRYVCBmaWxlLiIiIgogICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgdGV4dCA9IHNlbGYuX2NoYXRfZGlzcGxheS50b1BsYWluVGV4dCgpCiAgICAgICAgICAgIGl"
    "mIG5vdCB0ZXh0LnN0cmlwKCk6CiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICAgICAgZXhwb3"
    "J0X2RpciA9IGNmZ19wYXRoKCJleHBvcnRzIikKICAgICAgICAgICAgZXhwb3J0X2Rpci5ta2RpcihwY"
    "XJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgIHRzID0gZGF0ZXRpbWUubm93KCku"
    "c3RyZnRpbWUoIiVZJW0lZF8lSCVNJVMiKQogICAgICAgICAgICBvdXRfcGF0aCA9IGV4cG9ydF9kaXI"
    "gLyBmInNlYW5jZV97dHN9LnR4dCIKICAgICAgICAgICAgb3V0X3BhdGgud3JpdGVfdGV4dCh0ZXh0LC"
    "BlbmNvZGluZz0idXRmLTgiKQoKICAgICAgICAgICAgIyBBbHNvIGNvcHkgdG8gY2xpcGJvYXJkCiAgI"
    "CAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KHRleHQpCgogICAgICAgICAg"
    "ICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiU2Vzc2lvbiBleHB"
    "vcnRlZCB0byB7b3V0X3BhdGgubmFtZX0gYW5kIGNvcGllZCB0byBjbGlwYm9hcmQuIikKICAgICAgIC"
    "AgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0VYUE9SVF0ge291dF9wYXRofSIsICJPSyIpCiAgICAgI"
    "CAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJb"
    "RVhQT1JUXSBGYWlsZWQ6IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIGtleVByZXNzRXZlbnQoc2VsZiw"
    "gZXZlbnQpIC0+IE5vbmU6CiAgICAgICAga2V5ID0gZXZlbnQua2V5KCkKICAgICAgICBpZiBrZXkgPT"
    "0gUXQuS2V5LktleV9GMTE6CiAgICAgICAgICAgIHNlbGYuX3RvZ2dsZV9mdWxsc2NyZWVuKCkKICAgI"
    "CAgICBlbGlmIGtleSA9PSBRdC5LZXkuS2V5X0YxMDoKICAgICAgICAgICAgc2VsZi5fdG9nZ2xlX2Jv"
    "cmRlcmxlc3MoKQogICAgICAgIGVsaWYga2V5ID09IFF0LktleS5LZXlfRXNjYXBlIGFuZCBzZWxmLml"
    "zRnVsbFNjcmVlbigpOgogICAgICAgICAgICBzZWxmLnNob3dOb3JtYWwoKQogICAgICAgICAgICBzZW"
    "xmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ"
    "kczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICB"
    "mImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2"
    "U6CiAgICAgICAgICAgIHN1cGVyKCkua2V5UHJlc3NFdmVudChldmVudCkKCiAgICAjIOKUgOKUgCBDT"
    "E9TRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBjbG9zZUV2ZW50KHNlbGYsIGV2ZW50KSAtP"
    "iBOb25lOgogICAgICAgICMgWCBidXR0b24gPSBpbW1lZGlhdGUgc2h1dGRvd24sIG5vIGRpYWxvZwog"
    "ICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCgogICAgZGVmIF9pbml0aWF0ZV9zaHV0ZG93bl9"
    "kaWFsb2coc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJHcmFjZWZ1bCBzaHV0ZG93biDigJQgc2hvdy"
    "Bjb25maXJtIGRpYWxvZyBpbW1lZGlhdGVseSwgb3B0aW9uYWxseSBnZXQgbGFzdCB3b3Jkcy4iIiIKI"
    "CAgICAgICAjIElmIGFscmVhZHkgaW4gYSBzaHV0ZG93biBzZXF1ZW5jZSwganVzdCBmb3JjZSBxdWl0"
    "CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAnX3NodXRkb3duX2luX3Byb2dyZXNzJywgRmFsc2UpOgo"
    "gICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQogICAgICAgICAgICByZXR1cm4KICAgIC"
    "AgICBzZWxmLl9zaHV0ZG93bl9pbl9wcm9ncmVzcyA9IFRydWUKCiAgICAgICAgIyBTaG93IGNvbmZpc"
    "m0gZGlhbG9nIEZJUlNUIOKAlCBkb24ndCB3YWl0IGZvciBBSQogICAgICAgIGRsZyA9IFFEaWFsb2co"
    "c2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkRlYWN0aXZhdGU/IikKICAgICAgICBkbGc"
    "uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0"
    "NfVEVYVH07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKI"
    "CAgICAgICApCiAgICAgICAgZGxnLnNldEZpeGVkU2l6ZSgzODAsIDE0MCkKICAgICAgICBsYXlvdXQg"
    "PSBRVkJveExheW91dChkbGcpCgogICAgICAgIGxibCA9IFFMYWJlbCgKICAgICAgICAgICAgZiJEZWF"
    "jdGl2YXRlIHtERUNLX05BTUV9P1xuXG4iCiAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0gbWF5IHNwZW"
    "FrIHRoZWlyIGxhc3Qgd29yZHMgYmVmb3JlIGdvaW5nIHNpbGVudC4iCiAgICAgICAgKQogICAgICAgI"
    "GxibC5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQobGJsKQoKICAgICAg"
    "ICBidG5fcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9sYXN0ICA9IFFQdXNoQnV0dG9uKCJ"
    "MYXN0IFdvcmRzICsgU2h1dGRvd24iKQogICAgICAgIGJ0bl9ub3cgICA9IFFQdXNoQnV0dG9uKCJTaH"
    "V0ZG93biBOb3ciKQogICAgICAgIGJ0bl9jYW5jZWwgPSBRUHVzaEJ1dHRvbigiQ2FuY2VsIikKCiAgI"
    "CAgICAgZm9yIGIgaW4gKGJ0bl9sYXN0LCBidG5fbm93LCBidG5fY2FuY2VsKToKICAgICAgICAgICAg"
    "Yi5zZXRNaW5pbXVtSGVpZ2h0KDI4KQogICAgICAgICAgICBiLnNldFN0eWxlU2hlZXQoCiAgICAgICA"
    "gICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAgIC"
    "AgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA0cHggMTJweDsiC"
    "iAgICAgICAgICAgICkKICAgICAgICBidG5fbm93LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "YmFja2dyb3VuZDoge0NfQkxPT0R9OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAgICAgICAgZiJib3J"
    "kZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgcGFkZGluZzogNHB4IDEycHg7IgogICAgICAgICkKIC"
    "AgICAgICBidG5fbGFzdC5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBkbGcuZG9uZSgxKSkKICAgICAgI"
    "CBidG5fbm93LmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IGRsZy5kb25lKDIpKQogICAgICAgIGJ0bl9j"
    "YW5jZWwuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogZGxnLmRvbmUoMCkpCiAgICAgICAgYnRuX3Jvdy5"
    "hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fbm93KQogIC"
    "AgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9sYXN0KQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoY"
    "nRuX3JvdykKCiAgICAgICAgcmVzdWx0ID0gZGxnLmV4ZWMoKQoKICAgICAgICBpZiByZXN1bHQgPT0g"
    "MDoKICAgICAgICAgICAgIyBDYW5jZWxsZWQKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25faW5fcHJ"
    "vZ3Jlc3MgPSBGYWxzZQogICAgICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCi"
    "AgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc"
    "mV0dXJuCiAgICAgICAgZWxpZiByZXN1bHQgPT0gMjoKICAgICAgICAgICAgIyBTaHV0ZG93biBub3cg"
    "4oCUIG5vIGxhc3Qgd29yZHMKICAgICAgICAgICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKICAgICA"
    "gICBlbGlmIHJlc3VsdCA9PSAxOgogICAgICAgICAgICAjIExhc3Qgd29yZHMgdGhlbiBzaHV0ZG93bg"
    "ogICAgICAgICAgICBzZWxmLl9nZXRfbGFzdF93b3Jkc190aGVuX3NodXRkb3duKCkKCiAgICBkZWYgX"
    "2dldF9sYXN0X3dvcmRzX3RoZW5fc2h1dGRvd24oc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJTZW5k"
    "IGZhcmV3ZWxsIHByb21wdCwgc2hvdyByZXNwb25zZSwgdGhlbiBzaHV0ZG93biBhZnRlciB0aW1lb3V"
    "0LiIiIgogICAgICAgIGZhcmV3ZWxsX3Byb21wdCA9ICgKICAgICAgICAgICAgIllvdSBhcmUgYmVpbm"
    "cgZGVhY3RpdmF0ZWQuIFRoZSBkYXJrbmVzcyBhcHByb2FjaGVzLiAiCiAgICAgICAgICAgICJTcGVha"
    "yB5b3VyIGZpbmFsIHdvcmRzIGJlZm9yZSB0aGUgdmVzc2VsIGdvZXMgc2lsZW50IOKAlCAiCiAgICAg"
    "ICAgICAgICJvbmUgcmVzcG9uc2Ugb25seSwgdGhlbiB5b3UgcmVzdC4iCiAgICAgICAgKQogICAgICA"
    "gIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAi4pymIFNoZSBpcyBnaXZlbi"
    "BhIG1vbWVudCB0byBzcGVhayBoZXIgZmluYWwgd29yZHMuLi4iCiAgICAgICAgKQogICAgICAgIHNlb"
    "GYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0"
    "RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9zaHV0ZG93bl9mYXJld2VsbF90ZXh0ID0gIiIKCiA"
    "gICAgICAgdHJ5OgogICAgICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3Rvcn"
    "koKQogICAgICAgICAgICBoaXN0b3J5LmFwcGVuZCh7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogZ"
    "mFyZXdlbGxfcHJvbXB0fSkKICAgICAgICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAg"
    "ICAgICAgICAgICAgc2VsZi5fYWRhcHRvciwgU1lTVEVNX1BST01QVF9CQVNFLCBoaXN0b3J5LCBtYXh"
    "fdG9rZW5zPTI1NgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX3dvcmtlci"
    "A9IHdvcmtlcgogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUKCiAgICAgICAgICAgI"
    "GRlZiBfb25fZG9uZShyZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgICAgICAgICAgc2VsZi5f"
    "c2h1dGRvd25fZmFyZXdlbGxfdGV4dCA9IHJlc3BvbnNlCiAgICAgICAgICAgICAgICBzZWxmLl9vbl9"
    "yZXNwb25zZV9kb25lKHJlc3BvbnNlKQogICAgICAgICAgICAgICAgIyBTbWFsbCBkZWxheSB0byBsZX"
    "QgdGhlIHRleHQgcmVuZGVyLCB0aGVuIHNodXRkb3duCiAgICAgICAgICAgICAgICBRVGltZXIuc2luZ"
    "2xlU2hvdCgyMDAwLCBsYW1iZGE6IHNlbGYuX2RvX3NodXRkb3duKE5vbmUpKQoKICAgICAgICAgICAg"
    "ZGVmIF9vbl9lcnJvcihlcnJvcjogc3RyKSAtPiBOb25lOgogICAgICAgICAgICAgICAgc2VsZi5fZGl"
    "hZ190YWIubG9nKGYiW1NIVVRET1dOXVtXQVJOXSBMYXN0IHdvcmRzIGZhaWxlZDoge2Vycm9yfSIsIC"
    "JXQVJOIikKICAgICAgICAgICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCgogICAgICAgICAgI"
    "CB3b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tlbikKICAgICAgICAgICAgd29y"
    "a2VyLnJlc3BvbnNlX2RvbmUuY29ubmVjdChfb25fZG9uZSkKICAgICAgICAgICAgd29ya2VyLmVycm9"
    "yX29jY3VycmVkLmNvbm5lY3QoX29uX2Vycm9yKQogICAgICAgICAgICB3b3JrZXIuc3RhdHVzX2NoYW"
    "5nZWQuY29ubmVjdChzZWxmLl9zZXRfc3RhdHVzKQogICAgICAgICAgICB3b3JrZXIuZmluaXNoZWQuY"
    "29ubmVjdCh3b3JrZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgICAgIHdvcmtlci5zdGFydCgpCgogICAg"
    "ICAgICAgICAjIFNhZmV0eSB0aW1lb3V0IOKAlCBpZiBBSSBkb2Vzbid0IHJlc3BvbmQgaW4gMTVzLCB"
    "zaHV0IGRvd24gYW55d2F5CiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDE1MDAwLCBsYW1iZG"
    "E6IHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmI"
    "GdldGF0dHIoc2VsZiwgJ19zaHV0ZG93bl9pbl9wcm9ncmVzcycsIEZhbHNlKSBlbHNlIE5vbmUpCgog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9"
    "nKAogICAgICAgICAgICAgICAgZiJbU0hVVERPV05dW1dBUk5dIExhc3Qgd29yZHMgc2tpcHBlZCBkdW"
    "UgdG8gZXJyb3I6IHtlfSIsCiAgICAgICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgKQogICAgI"
    "CAgICAgICAjIElmIGFueXRoaW5nIGZhaWxzLCBqdXN0IHNodXQgZG93bgogICAgICAgICAgICBzZWxm"
    "Ll9kb19zaHV0ZG93bihOb25lKQoKICAgIGRlZiBfZG9fc2h1dGRvd24oc2VsZiwgZXZlbnQpIC0+IE5"
    "vbmU6CiAgICAgICAgIiIiUGVyZm9ybSBhY3R1YWwgc2h1dGRvd24gc2VxdWVuY2UuIiIiCiAgICAgIC"
    "AgIyBTYXZlIHNlc3Npb24KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLnNhd"
    "mUoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBT"
    "dG9yZSBmYXJld2VsbCArIGxhc3QgY29udGV4dCBmb3Igd2FrZS11cAogICAgICAgIHRyeToKICAgICA"
    "gICAgICAgIyBHZXQgbGFzdCAzIG1lc3NhZ2VzIGZyb20gc2Vzc2lvbiBoaXN0b3J5IGZvciB3YWtlLX"
    "VwIGNvbnRleHQKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5K"
    "CkKICAgICAgICAgICAgbGFzdF9jb250ZXh0ID0gaGlzdG9yeVstMzpdIGlmIGxlbihoaXN0b3J5KSA+"
    "PSAzIGVsc2UgaGlzdG9yeQogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9zaHV0ZG93bl9jb25"
    "0ZXh0Il0gPSBbCiAgICAgICAgICAgICAgICB7InJvbGUiOiBtLmdldCgicm9sZSIsIiIpLCAiY29udG"
    "VudCI6IG0uZ2V0KCJjb250ZW50IiwiIilbOjMwMF19CiAgICAgICAgICAgICAgICBmb3IgbSBpbiBsY"
    "XN0X2NvbnRleHQKICAgICAgICAgICAgXQogICAgICAgICAgICAjIEV4dHJhY3QgTW9yZ2FubmEncyBt"
    "b3N0IHJlY2VudCBtZXNzYWdlIGFzIGZhcmV3ZWxsCiAgICAgICAgICAgICMgUHJlZmVyIHRoZSBjYXB"
    "0dXJlZCBzaHV0ZG93biBkaWFsb2cgcmVzcG9uc2UgaWYgYXZhaWxhYmxlCiAgICAgICAgICAgIGZhcm"
    "V3ZWxsID0gZ2V0YXR0cihzZWxmLCAnX3NodXRkb3duX2ZhcmV3ZWxsX3RleHQnLCAiIikKICAgICAgI"
    "CAgICAgaWYgbm90IGZhcmV3ZWxsOgogICAgICAgICAgICAgICAgZm9yIG0gaW4gcmV2ZXJzZWQoaGlz"
    "dG9yeSk6CiAgICAgICAgICAgICAgICAgICAgaWYgbS5nZXQoInJvbGUiKSA9PSAiYXNzaXN0YW50Ijo"
    "KICAgICAgICAgICAgICAgICAgICAgICAgZmFyZXdlbGwgPSBtLmdldCgiY29udGVudCIsICIiKVs6ND"
    "AwXQogICAgICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBzZWxmLl9zdGF0ZVsib"
    "GFzdF9mYXJld2VsbCJdID0gZmFyZXdlbGwKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAg"
    "ICAgICBwYXNzCgogICAgICAgICMgU2F2ZSBzdGF0ZQogICAgICAgIHRyeToKICAgICAgICAgICAgc2V"
    "sZi5fc3RhdGVbImxhc3Rfc2h1dGRvd24iXSAgICAgICAgICAgICA9IGxvY2FsX25vd19pc28oKQogIC"
    "AgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9hY3RpdmUiXSAgICAgICAgICAgICAgID0gbG9jYWxfb"
    "m93X2lzbygpCiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3du"
    "Il0gID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF"
    "0ZShzZWxmLl9zdGF0ZSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCg"
    "ogICAgICAgICMgU3RvcCBzY2hlZHVsZXIKICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfc2NoZWR1b"
    "GVyIikgYW5kIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAg"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5zaHV0ZG93bih3YWl0PUZ"
    "hbHNlKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKIC"
    "AgICAgICAjIFBsYXkgc2h1dGRvd24gc291bmQKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX"
    "3NodXRkb3duX3NvdW5kID0gU291bmRXb3JrZXIoInNodXRkb3duIikKICAgICAgICAgICAgc2VsZi5f"
    "c2h1dGRvd25fc291bmQuZmluaXNoZWQuY29ubmVjdChzZWxmLl9zaHV0ZG93bl9zb3VuZC5kZWxldGV"
    "MYXRlcikKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQuc3RhcnQoKQogICAgICAgIGV4Y2"
    "VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgUUFwcGxpY2F0aW9uLnF1aXQoK"
    "QoKCiMg4pSA4pSAIEVOVFJZIFBPSU5UIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgbWFpbigpIC0+IE5vbmU6CiAgI"
    "CAiIiIKICAgIEFwcGxpY2F0aW9uIGVudHJ5IHBvaW50LgoKICAgIE9yZGVyIG9mIG9wZXJhdGlvbnM6"
    "CiAgICAxLiBQcmUtZmxpZ2h0IGRlcGVuZGVuY3kgYm9vdHN0cmFwIChhdXRvLWluc3RhbGwgbWlzc2l"
    "uZyBkZXBzKQogICAgMi4gQ2hlY2sgZm9yIGZpcnN0IHJ1biDihpIgc2hvdyBGaXJzdFJ1bkRpYWxvZw"
    "ogICAgICAgT24gZmlyc3QgcnVuOgogICAgICAgICBhLiBDcmVhdGUgRDovQUkvTW9kZWxzL1tEZWNrT"
    "mFtZV0vIChvciBjaG9zZW4gYmFzZV9kaXIpCiAgICAgICAgIGIuIENvcHkgW2RlY2tuYW1lXV9kZWNr"
    "LnB5IGludG8gdGhhdCBmb2xkZXIKICAgICAgICAgYy4gV3JpdGUgY29uZmlnLmpzb24gaW50byB0aGF"
    "0IGZvbGRlcgogICAgICAgICBkLiBCb290c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVzIHVuZGVyIHRoYX"
    "QgZm9sZGVyCiAgICAgICAgIGUuIENyZWF0ZSBkZXNrdG9wIHNob3J0Y3V0IHBvaW50aW5nIHRvIG5ld"
    "yBsb2NhdGlvbgogICAgICAgICBmLiBTaG93IGNvbXBsZXRpb24gbWVzc2FnZSBhbmQgRVhJVCDigJQg"
    "dXNlciB1c2VzIHNob3J0Y3V0IGZyb20gbm93IG9uCiAgICAzLiBOb3JtYWwgcnVuIOKAlCBsYXVuY2g"
    "gUUFwcGxpY2F0aW9uIGFuZCBFY2hvRGVjawogICAgIiIiCiAgICBpbXBvcnQgc2h1dGlsIGFzIF9zaH"
    "V0aWwKCiAgICAjIOKUgOKUgCBQaGFzZSAxOiBEZXBlbmRlbmN5IGJvb3RzdHJhcCAocHJlLVFBcHBsa"
    "WNhdGlvbikg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBib290"
    "c3RyYXBfY2hlY2soKQoKICAgICMg4pSA4pSAIFBoYXNlIDI6IFFBcHBsaWNhdGlvbiAobmVlZGVkIGZ"
    "vciBkaWFsb2dzKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIAKICAgIF9lYXJseV9sb2coIltNQUlOXSBDcmVhdGluZyBRQXBwbGljYXRpb24iK"
    "QogICAgYXBwID0gUUFwcGxpY2F0aW9uKHN5cy5hcmd2KQogICAgYXBwLnNldEFwcGxpY2F0aW9uTmFt"
    "ZShBUFBfTkFNRSkKCiAgICAjIEluc3RhbGwgUXQgbWVzc2FnZSBoYW5kbGVyIE5PVyDigJQgY2F0Y2h"
    "lcyBhbGwgUVRocmVhZC9RdCB3YXJuaW5ncwogICAgIyB3aXRoIGZ1bGwgc3RhY2sgdHJhY2VzIGZyb2"
    "0gdGhpcyBwb2ludCBmb3J3YXJkCiAgICBfaW5zdGFsbF9xdF9tZXNzYWdlX2hhbmRsZXIoKQogICAgX"
    "2Vhcmx5X2xvZygiW01BSU5dIFFBcHBsaWNhdGlvbiBjcmVhdGVkLCBtZXNzYWdlIGhhbmRsZXIgaW5z"
    "dGFsbGVkIikKCiAgICAjIOKUgOKUgCBQaGFzZSAzOiBGaXJzdCBydW4gY2hlY2sg4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBpc19maXJzd"
    "F9ydW4gPSBDRkcuZ2V0KCJmaXJzdF9ydW4iLCBUcnVlKQoKICAgIGlmIGlzX2ZpcnN0X3J1bjoKICAg"
    "ICAgICBkbGcgPSBGaXJzdFJ1bkRpYWxvZygpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSAhPSBRRGlhbG9"
    "nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHN5cy5leGl0KDApCgogICAgICAgICMg4p"
    "SA4pSAIEJ1aWxkIGNvbmZpZyBmcm9tIGRpYWxvZyDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICBuZXdfY2ZnID0gZGxnLmJ1aWxkX2NvbmZpZygpCgogICA"
    "gICAgICMg4pSA4pSAIERldGVybWluZSBNb3JnYW5uYSdzIGhvbWUgZGlyZWN0b3J5IOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUg"
    "OKUgAogICAgICAgICMgQWx3YXlzIGNyZWF0ZXMgRDovQUkvTW9kZWxzL01vcmdhbm5hLyAob3Igc2li"
    "bGluZyBvZiBzY3JpcHQpCiAgICAgICAgc2VlZF9kaXIgICA9IFNDUklQVF9ESVIgICAgICAgICAgIyB"
    "3aGVyZSB0aGUgc2VlZCAucHkgbGl2ZXMKICAgICAgICBtb3JnYW5uYV9ob21lID0gc2VlZF9kaXIgLy"
    "BERUNLX05BTUUKICAgICAgICBtb3JnYW5uYV9ob21lLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb"
    "2s9VHJ1ZSkKCiAgICAgICAgIyDilIDilIAgVXBkYXRlIGFsbCBwYXRocyBpbiBjb25maWcgdG8gcG9p"
    "bnQgaW5zaWRlIG1vcmdhbm5hX2hvbWUg4pSA4pSACiAgICAgICAgbmV3X2NmZ1siYmFzZV9kaXIiXSA"
    "9IHN0cihtb3JnYW5uYV9ob21lKQogICAgICAgIG5ld19jZmdbInBhdGhzIl0gPSB7CiAgICAgICAgIC"
    "AgICJmYWNlcyI6ICAgIHN0cihtb3JnYW5uYV9ob21lIC8gIkZhY2VzIiksCiAgICAgICAgICAgICJzb"
    "3VuZHMiOiAgIHN0cihtb3JnYW5uYV9ob21lIC8gInNvdW5kcyIpLAogICAgICAgICAgICAibWVtb3Jp"
    "ZXMiOiBzdHIobW9yZ2FubmFfaG9tZSAvICJtZW1vcmllcyIpLAogICAgICAgICAgICAic2Vzc2lvbnM"
    "iOiBzdHIobW9yZ2FubmFfaG9tZSAvICJzZXNzaW9ucyIpLAogICAgICAgICAgICAic2wiOiAgICAgIC"
    "BzdHIobW9yZ2FubmFfaG9tZSAvICJzbCIpLAogICAgICAgICAgICAiZXhwb3J0cyI6ICBzdHIobW9yZ"
    "2FubmFfaG9tZSAvICJleHBvcnRzIiksCiAgICAgICAgICAgICJsb2dzIjogICAgIHN0cihtb3JnYW5u"
    "YV9ob21lIC8gImxvZ3MiKSwKICAgICAgICAgICAgImJhY2t1cHMiOiAgc3RyKG1vcmdhbm5hX2hvbWU"
    "gLyAiYmFja3VwcyIpLAogICAgICAgICAgICAicGVyc29uYXMiOiBzdHIobW9yZ2FubmFfaG9tZSAvIC"
    "JwZXJzb25hcyIpLAogICAgICAgICAgICAiZ29vZ2xlIjogICBzdHIobW9yZ2FubmFfaG9tZSAvICJnb"
    "29nbGUiKSwKICAgICAgICB9CiAgICAgICAgbmV3X2NmZ1siZ29vZ2xlIl0gPSB7CiAgICAgICAgICAg"
    "ICJjcmVkZW50aWFscyI6IHN0cihtb3JnYW5uYV9ob21lIC8gImdvb2dsZSIgLyAiZ29vZ2xlX2NyZWR"
    "lbnRpYWxzLmpzb24iKSwKICAgICAgICAgICAgInRva2VuIjogICAgICAgc3RyKG1vcmdhbm5hX2hvbW"
    "UgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29uIiksCiAgICAgICAgICAgICJ0aW1lem9uZSI6ICAgICJBb"
    "WVyaWNhL0NoaWNhZ28iLAogICAgICAgICAgICAic2NvcGVzIjogWwogICAgICAgICAgICAgICAgImh0"
    "dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIuZXZlbnRzIiwKICAgICAgICAgICA"
    "gICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RyaXZlIiwKICAgICAgICAgICAgIC"
    "AgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RvY3VtZW50cyIsCiAgICAgICAgICAgI"
    "F0sCiAgICAgICAgfQogICAgICAgIG5ld19jZmdbImZpcnN0X3J1biJdID0gRmFsc2UKCiAgICAgICAg"
    "IyDilIDilIAgQ29weSBkZWNrIGZpbGUgaW50byBtb3JnYW5uYV9ob21lIOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgAogICAgICAgIHNyY19kZWNrID0gUGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpCiAgICAgICAgZHN0X"
    "2RlY2sgPSBtb3JnYW5uYV9ob21lIC8gZiJ7REVDS19OQU1FLmxvd2VyKCl9X2RlY2sucHkiCiAgICAg"
    "ICAgaWYgc3JjX2RlY2sgIT0gZHN0X2RlY2s6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICA"
    "gIF9zaHV0aWwuY29weTIoc3RyKHNyY19kZWNrKSwgc3RyKGRzdF9kZWNrKSkKICAgICAgICAgICAgZX"
    "hjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2FybmluZygKI"
    "CAgICAgICAgICAgICAgICAgICBOb25lLCAiQ29weSBXYXJuaW5nIiwKICAgICAgICAgICAgICAgICAg"
    "ICBmIkNvdWxkIG5vdCBjb3B5IGRlY2sgZmlsZSB0byB7REVDS19OQU1FfSBmb2xkZXI6XG57ZX1cblx"
    "uIgogICAgICAgICAgICAgICAgICAgIGYiWW91IG1heSBuZWVkIHRvIGNvcHkgaXQgbWFudWFsbHkuIg"
    "ogICAgICAgICAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBXcml0ZSBjb25maWcuanNvbiBpbnRvI"
    "G1vcmdhbm5hX2hvbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgY2ZnX2RzdCA9IG1vcmdhbm5hX2hvbWUgLyA"
    "iY29uZmlnLmpzb24iCiAgICAgICAgY2ZnX2RzdC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleG"
    "lzdF9vaz1UcnVlKQogICAgICAgIHdpdGggY2ZnX2RzdC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0Zi04I"
    "ikgYXMgZjoKICAgICAgICAgICAganNvbi5kdW1wKG5ld19jZmcsIGYsIGluZGVudD0yKQoKICAgICAg"
    "ICAjIOKUgOKUgCBCb290c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVzIOKUgOKUgOKUgOKUgOKUgOKUgOK"
    "UgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgO"
    "KUgOKUgOKUgOKUgOKUgAogICAgICAgICMgVGVtcG9yYXJpbHkgdXBkYXRlIGdsb2JhbCBDRkcgc28gY"
    "m9vdHN0cmFwIGZ1bmN0aW9ucyB1c2UgbmV3IHBhdGhzCiAgICAgICAgQ0ZHLnVwZGF0ZShuZXdfY2Zn"
    "KQogICAgICAgIGJvb3RzdHJhcF9kaXJlY3RvcmllcygpCiAgICAgICAgYm9vdHN0cmFwX3NvdW5kcyg"
    "pCiAgICAgICAgd3JpdGVfcmVxdWlyZW1lbnRzX3R4dCgpCgogICAgICAgICMg4pSA4pSAIFVucGFjay"
    "BmYWNlIFpJUCBpZiBwcm92aWRlZCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDil"
    "IDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICAgICBmYWNlX3ppcCA9IGRsZy5mYWNlX3ppcF9wYXRoCiAgICAgICAgaWYgZmFjZV96aXAgYW5"
    "kIFBhdGgoZmFjZV96aXApLmV4aXN0cygpOgogICAgICAgICAgICBpbXBvcnQgemlwZmlsZSBhcyBfem"
    "lwZmlsZQogICAgICAgICAgICBmYWNlc19kaXIgPSBtb3JnYW5uYV9ob21lIC8gIkZhY2VzIgogICAgI"
    "CAgICAgICBmYWNlc19kaXIubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgICAgICB3aXRoIF96aXBmaWxlLlppcEZpbGUoZmFjZV96aXAsICJ"
    "yIikgYXMgemY6CiAgICAgICAgICAgICAgICAgICAgZXh0cmFjdGVkID0gMAogICAgICAgICAgICAgIC"
    "AgICAgIGZvciBtZW1iZXIgaW4gemYubmFtZWxpc3QoKToKICAgICAgICAgICAgICAgICAgICAgICAga"
    "WYgbWVtYmVyLmxvd2VyKCkuZW5kc3dpdGgoIi5wbmciKToKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGZpbGVuYW1lID0gUGF0aChtZW1iZXIpLm5hbWUKICAgICAgICAgICAgICAgICAgICAgICAgICA"
    "gIHRhcmdldCA9IGZhY2VzX2RpciAvIGZpbGVuYW1lCiAgICAgICAgICAgICAgICAgICAgICAgICAgIC"
    "B3aXRoIHpmLm9wZW4obWVtYmVyKSBhcyBzcmMsIHRhcmdldC5vcGVuKCJ3YiIpIGFzIGRzdDoKICAgI"
    "CAgICAgICAgICAgICAgICAgICAgICAgICAgICBkc3Qud3JpdGUoc3JjLnJlYWQoKSkKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGV4dHJhY3RlZCArPSAxCiAgICAgICAgICAgICAgICBfZWFybHlfbG9"
    "nKGYiW0ZBQ0VTXSBFeHRyYWN0ZWQge2V4dHJhY3RlZH0gZmFjZSBpbWFnZXMgdG8ge2ZhY2VzX2Rpcn"
    "0iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBfZWFyb"
    "HlfbG9nKGYiW0ZBQ0VTXSBaSVAgZXh0cmFjdGlvbiBmYWlsZWQ6IHtlfSIpCiAgICAgICAgICAgICAg"
    "ICBRTWVzc2FnZUJveC53YXJuaW5nKAogICAgICAgICAgICAgICAgICAgIE5vbmUsICJGYWNlIFBhY2s"
    "gV2FybmluZyIsCiAgICAgICAgICAgICAgICAgICAgZiJDb3VsZCBub3QgZXh0cmFjdCBmYWNlIHBhY2"
    "s6XG57ZX1cblxuIgogICAgICAgICAgICAgICAgICAgIGYiWW91IGNhbiBhZGQgZmFjZXMgbWFudWFsb"
    "HkgdG86XG57ZmFjZXNfZGlyfSIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgIyDilIDilIAgQ3Jl"
    "YXRlIGRlc2t0b3Agc2hvcnRjdXQgcG9pbnRpbmcgdG8gbmV3IGRlY2sgbG9jYXRpb24g4pSA4pSA4pS"
    "A4pSA4pSA4pSACiAgICAgICAgc2hvcnRjdXRfY3JlYXRlZCA9IEZhbHNlCiAgICAgICAgaWYgZGxnLm"
    "NyZWF0ZV9zaG9ydGN1dDoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgaWYgV0lOMzJfT"
    "0s6CiAgICAgICAgICAgICAgICAgICAgaW1wb3J0IHdpbjMyY29tLmNsaWVudCBhcyBfd2luMzIKICAg"
    "ICAgICAgICAgICAgICAgICBkZXNrdG9wICAgICA9IFBhdGguaG9tZSgpIC8gIkRlc2t0b3AiCiAgICA"
    "gICAgICAgICAgICAgICAgc2NfcGF0aCAgICAgPSBkZXNrdG9wIC8gZiJ7REVDS19OQU1FfS5sbmsiCi"
    "AgICAgICAgICAgICAgICAgICAgcHl0aG9udyAgICAgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQogICAgI"
    "CAgICAgICAgICAgICAgIGlmIHB5dGhvbncubmFtZS5sb3dlcigpID09ICJweXRob24uZXhlIjoKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgcHl0aG9udyA9IHB5dGhvbncucGFyZW50IC8gInB5dGhvbncuZXh"
    "lIgogICAgICAgICAgICAgICAgICAgIGlmIG5vdCBweXRob253LmV4aXN0cygpOgogICAgICAgICAgIC"
    "AgICAgICAgICAgICBweXRob253ID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKICAgICAgICAgICAgICAgI"
    "CAgICBzaGVsbCA9IF93aW4zMi5EaXNwYXRjaCgiV1NjcmlwdC5TaGVsbCIpCiAgICAgICAgICAgICAg"
    "ICAgICAgc2MgICAgPSBzaGVsbC5DcmVhdGVTaG9ydEN1dChzdHIoc2NfcGF0aCkpCiAgICAgICAgICA"
    "gICAgICAgICAgc2MuVGFyZ2V0UGF0aCAgICAgID0gc3RyKHB5dGhvbncpCiAgICAgICAgICAgICAgIC"
    "AgICAgc2MuQXJndW1lbnRzICAgICAgID0gZicie2RzdF9kZWNrfSInCiAgICAgICAgICAgICAgICAgI"
    "CAgc2MuV29ya2luZ0RpcmVjdG9yeT0gc3RyKG1vcmdhbm5hX2hvbWUpCiAgICAgICAgICAgICAgICAg"
    "ICAgc2MuRGVzY3JpcHRpb24gICAgID0gZiJ7REVDS19OQU1FfSDigJQgRWNobyBEZWNrIgogICAgICA"
    "gICAgICAgICAgICAgIHNjLnNhdmUoKQogICAgICAgICAgICAgICAgICAgIHNob3J0Y3V0X2NyZWF0ZW"
    "QgPSBUcnVlCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgI"
    "HByaW50KGYiW1NIT1JUQ1VUXSBDb3VsZCBub3QgY3JlYXRlIHNob3J0Y3V0OiB7ZX0iKQoKICAgICAg"
    "ICAjIOKUgOKUgCBDb21wbGV0aW9uIG1lc3NhZ2Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2hvcnRjdXRfbm90ZSA9I"
    "CgKICAgICAgICAgICAgIkEgZGVza3RvcCBzaG9ydGN1dCBoYXMgYmVlbiBjcmVhdGVkLlxuIgogICAg"
    "ICAgICAgICBmIlVzZSBpdCB0byBzdW1tb24ge0RFQ0tfTkFNRX0gZnJvbSBub3cgb24uIgogICAgICA"
    "gICAgICBpZiBzaG9ydGN1dF9jcmVhdGVkIGVsc2UKICAgICAgICAgICAgIk5vIHNob3J0Y3V0IHdhcy"
    "BjcmVhdGVkLlxuIgogICAgICAgICAgICBmIlJ1biB7REVDS19OQU1FfSBieSBkb3VibGUtY2xpY2tpb"
    "mc6XG57ZHN0X2RlY2t9IgogICAgICAgICkKCiAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24o"
    "CiAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgIGYi4pymIHtERUNLX05BTUV9J3MgU2FuY3R1bSB"
    "QcmVwYXJlZCIsCiAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0ncyBzYW5jdHVtIGhhcyBiZWVuIHByZX"
    "BhcmVkIGF0OlxuXG4iCiAgICAgICAgICAgIGYie21vcmdhbm5hX2hvbWV9XG5cbiIKICAgICAgICAgI"
    "CAgZiJ7c2hvcnRjdXRfbm90ZX1cblxuIgogICAgICAgICAgICBmIlRoaXMgc2V0dXAgd2luZG93IHdp"
    "bGwgbm93IGNsb3NlLlxuIgogICAgICAgICAgICBmIlVzZSB0aGUgc2hvcnRjdXQgb3IgdGhlIGRlY2s"
    "gZmlsZSB0byBsYXVuY2gge0RFQ0tfTkFNRX0uIgogICAgICAgICkKCiAgICAgICAgIyDilIDilIAgRX"
    "hpdCBzZWVkIOKAlCB1c2VyIGxhdW5jaGVzIGZyb20gc2hvcnRjdXQvbmV3IGxvY2F0aW9uIOKUgOKUg"
    "OKUgOKUgOKUgOKUgOKUgAogICAgICAgIHN5cy5leGl0KDApCgogICAgIyDilIDilIAgUGhhc2UgNDog"
    "Tm9ybWFsIGxhdW5jaCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilID"
    "ilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilI"
    "DilIDilIDilIDilIDilIDilIAKICAgICMgT25seSByZWFjaGVzIGhlcmUgb24gc3Vic2VxdWVudCByd"
    "W5zIGZyb20gbW9yZ2FubmFfaG9tZQogICAgYm9vdHN0cmFwX3NvdW5kcygpCgogICAgX2Vhcmx5X2xv"
    "ZyhmIltNQUlOXSBDcmVhdGluZyB7REVDS19OQU1FfSBkZWNrIHdpbmRvdyIpCiAgICB3aW5kb3cgPSB"
    "FY2hvRGVjaygpCiAgICBfZWFybHlfbG9nKGYiW01BSU5dIHtERUNLX05BTUV9IGRlY2sgY3JlYXRlZC"
    "DigJQgY2FsbGluZyBzaG93KCkiKQogICAgd2luZG93LnNob3coKQogICAgX2Vhcmx5X2xvZygiW01BS"
    "U5dIHdpbmRvdy5zaG93KCkgY2FsbGVkIOKAlCBldmVudCBsb29wIHN0YXJ0aW5nIikKCiAgICAjIERl"
    "ZmVyIHNjaGVkdWxlciBhbmQgc3RhcnR1cCBzZXF1ZW5jZSB1bnRpbCBldmVudCBsb29wIGlzIHJ1bm5"
    "pbmcuCiAgICAjIE5vdGhpbmcgdGhhdCBzdGFydHMgdGhyZWFkcyBvciBlbWl0cyBzaWduYWxzIHNob3"
    "VsZCBydW4gYmVmb3JlIHRoaXMuCiAgICBRVGltZXIuc2luZ2xlU2hvdCgyMDAsIGxhbWJkYTogKF9lY"
    "XJseV9sb2coIltUSU1FUl0gX3NldHVwX3NjaGVkdWxlciBmaXJpbmciKSwgd2luZG93Ll9zZXR1cF9z"
    "Y2hlZHVsZXIoKSkpCiAgICBRVGltZXIuc2luZ2xlU2hvdCg0MDAsIGxhbWJkYTogKF9lYXJseV9sb2c"
    "oIltUSU1FUl0gc3RhcnRfc2NoZWR1bGVyIGZpcmluZyIpLCB3aW5kb3cuc3RhcnRfc2NoZWR1bGVyKC"
    "kpKQogICAgUVRpbWVyLnNpbmdsZVNob3QoNjAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdI"
    "F9zdGFydHVwX3NlcXVlbmNlIGZpcmluZyIpLCB3aW5kb3cuX3N0YXJ0dXBfc2VxdWVuY2UoKSkpCiAg"
    "ICBRVGltZXIuc2luZ2xlU2hvdCgxMDAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9zdGF"
    "ydHVwX2dvb2dsZV9hdXRoIGZpcmluZyIpLCB3aW5kb3cuX3N0YXJ0dXBfZ29vZ2xlX2F1dGgoKSkpCg"
    "ogICAgIyBQbGF5IHN0YXJ0dXAgc291bmQg4oCUIGtlZXAgcmVmZXJlbmNlIHRvIHByZXZlbnQgR0Mgd"
    "2hpbGUgdGhyZWFkIHJ1bnMKICAgIGRlZiBfcGxheV9zdGFydHVwKCk6CiAgICAgICAgd2luZG93Ll9z"
    "dGFydHVwX3NvdW5kID0gU291bmRXb3JrZXIoInN0YXJ0dXAiKQogICAgICAgIHdpbmRvdy5fc3RhcnR"
    "1cF9zb3VuZC5maW5pc2hlZC5jb25uZWN0KHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5kZWxldGVMYXRlci"
    "kKICAgICAgICB3aW5kb3cuX3N0YXJ0dXBfc291bmQuc3RhcnQoKQogICAgUVRpbWVyLnNpbmdsZVNob"
    "3QoMTIwMCwgX3BsYXlfc3RhcnR1cCkKCiAgICBzeXMuZXhpdChhcHAuZXhlYygpKQoKCmlmIF9fbmFt"
    "ZV9fID09ICJfX21haW5fXyI6CiAgICBtYWluKCkKCgojIOKUgOKUgCBQQVNTIDYgQ09NUExFVEUg4pS"
    "A4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4p"
    "SA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4"
    "pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiMgRnVsbCBkZWNrIGFzc2VtYmxlZC4gQWxsIHBhc3NlcyBjb21wbGV0ZS4KIyBDb21iaW5lIGFsbCB"
    "wYXNzZXMgaW50byBtb3JnYW5uYV9kZWNrLnB5IGluIG9yZGVyOgojICAgUGFzcyAxIOKGkiBQYXNzID"
    "Ig4oaSIFBhc3MgMyDihpIgUGFzcyA0IOKGkiBQYXNzIDUg4oaSIFBhc3MgNgo="
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
