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
    "dGltZSwgZGF0ZSwgdGltZWRlbHRhLCB0aW1lem9uZQpmcm9tIHpvbmVpbmZvIGltcG9ydCBab25l"
    "SW5mbywgWm9uZUluZm9Ob3RGb3VuZEVycm9yCmZyb20gcGF0aGxpYiBpbXBvcnQgUGF0aApmcm9t"
    "IHR5cGluZyBpbXBvcnQgT3B0aW9uYWwsIEl0ZXJhdG9yCgojIOKUgOKUgCBFQVJMWSBDUkFTSCBM"
    "T0dHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiMgSG9va3MgaW4gYmVmb3JlIFF0LCBiZWZvcmUgZXZlcnl0aGluZy4gQ2FwdHVyZXMgQUxMIG91"
    "dHB1dCBpbmNsdWRpbmcKIyBDKysgbGV2ZWwgUXQgbWVzc2FnZXMuIFdyaXR0ZW4gdG8gW0RlY2tO"
    "YW1lXS9sb2dzL3N0YXJ0dXAubG9nCiMgVGhpcyBzdGF5cyBhY3RpdmUgZm9yIHRoZSBsaWZlIG9m"
    "IHRoZSBwcm9jZXNzLgoKX0VBUkxZX0xPR19MSU5FUzogbGlzdCA9IFtdCl9FQVJMWV9MT0dfUEFU"
    "SDogT3B0aW9uYWxbUGF0aF0gPSBOb25lCgpkZWYgX2Vhcmx5X2xvZyhtc2c6IHN0cikgLT4gTm9u"
    "ZToKICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTLiVmIilbOi0zXQog"
    "ICAgbGluZSA9IGYiW3t0c31dIHttc2d9IgogICAgX0VBUkxZX0xPR19MSU5FUy5hcHBlbmQobGlu"
    "ZSkKICAgIHByaW50KGxpbmUsIGZsdXNoPVRydWUpCiAgICBpZiBfRUFSTFlfTE9HX1BBVEg6CiAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICB3aXRoIF9FQVJMWV9MT0dfUEFUSC5vcGVuKCJhIiwgZW5j"
    "b2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICAgICAgICAgIGYud3JpdGUobGluZSArICJcbiIp"
    "CiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKZGVmIF9pbml0X2Vh"
    "cmx5X2xvZyhiYXNlX2RpcjogUGF0aCkgLT4gTm9uZToKICAgIGdsb2JhbCBfRUFSTFlfTE9HX1BB"
    "VEgKICAgIGxvZ19kaXIgPSBiYXNlX2RpciAvICJsb2dzIgogICAgbG9nX2Rpci5ta2RpcihwYXJl"
    "bnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICBfRUFSTFlfTE9HX1BBVEggPSBsb2dfZGlyIC8g"
    "ZiJzdGFydHVwX3tkYXRldGltZS5ub3coKS5zdHJmdGltZSgnJVklbSVkXyVIJU0lUycpfS5sb2ci"
    "CiAgICAjIEZsdXNoIGJ1ZmZlcmVkIGxpbmVzCiAgICB3aXRoIF9FQVJMWV9MT0dfUEFUSC5vcGVu"
    "KCJ3IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICBmb3IgbGluZSBpbiBfRUFSTFlf"
    "TE9HX0xJTkVTOgogICAgICAgICAgICBmLndyaXRlKGxpbmUgKyAiXG4iKQoKZGVmIF9pbnN0YWxs"
    "X3F0X21lc3NhZ2VfaGFuZGxlcigpIC0+IE5vbmU6CiAgICAiIiIKICAgIEludGVyY2VwdCBBTEwg"
    "UXQgbWVzc2FnZXMgaW5jbHVkaW5nIEMrKyBsZXZlbCB3YXJuaW5ncy4KICAgIFRoaXMgY2F0Y2hl"
    "cyB0aGUgUVRocmVhZCBkZXN0cm95ZWQgbWVzc2FnZSBhdCB0aGUgc291cmNlIGFuZCBsb2dzIGl0"
    "CiAgICB3aXRoIGEgZnVsbCB0cmFjZWJhY2sgc28gd2Uga25vdyBleGFjdGx5IHdoaWNoIHRocmVh"
    "ZCBhbmQgd2hlcmUuCiAgICAiIiIKICAgIHRyeToKICAgICAgICBmcm9tIFB5U2lkZTYuUXRDb3Jl"
    "IGltcG9ydCBxSW5zdGFsbE1lc3NhZ2VIYW5kbGVyLCBRdE1zZ1R5cGUKICAgICAgICBpbXBvcnQg"
    "dHJhY2ViYWNrCgogICAgICAgIGRlZiBxdF9tZXNzYWdlX2hhbmRsZXIobXNnX3R5cGUsIGNvbnRl"
    "eHQsIG1lc3NhZ2UpOgogICAgICAgICAgICBsZXZlbCA9IHsKICAgICAgICAgICAgICAgIFF0TXNn"
    "VHlwZS5RdERlYnVnTXNnOiAgICAiUVRfREVCVUciLAogICAgICAgICAgICAgICAgUXRNc2dUeXBl"
    "LlF0SW5mb01zZzogICAgICJRVF9JTkZPIiwKICAgICAgICAgICAgICAgIFF0TXNnVHlwZS5RdFdh"
    "cm5pbmdNc2c6ICAiUVRfV0FSTklORyIsCiAgICAgICAgICAgICAgICBRdE1zZ1R5cGUuUXRDcml0"
    "aWNhbE1zZzogIlFUX0NSSVRJQ0FMIiwKICAgICAgICAgICAgICAgIFF0TXNnVHlwZS5RdEZhdGFs"
    "TXNnOiAgICAiUVRfRkFUQUwiLAogICAgICAgICAgICB9LmdldChtc2dfdHlwZSwgIlFUX1VOS05P"
    "V04iKQoKICAgICAgICAgICAgbG9jYXRpb24gPSAiIgogICAgICAgICAgICBpZiBjb250ZXh0LmZp"
    "bGU6CiAgICAgICAgICAgICAgICBsb2NhdGlvbiA9IGYiIFt7Y29udGV4dC5maWxlfTp7Y29udGV4"
    "dC5saW5lfV0iCgogICAgICAgICAgICBfZWFybHlfbG9nKGYiW3tsZXZlbH1de2xvY2F0aW9ufSB7"
    "bWVzc2FnZX0iKQoKICAgICAgICAgICAgIyBGb3IgUVRocmVhZCB3YXJuaW5ncyDigJQgbG9nIGZ1"
    "bGwgUHl0aG9uIHN0YWNrCiAgICAgICAgICAgIGlmICJRVGhyZWFkIiBpbiBtZXNzYWdlIG9yICJ0"
    "aHJlYWQiIGluIG1lc3NhZ2UubG93ZXIoKToKICAgICAgICAgICAgICAgIHN0YWNrID0gIiIuam9p"
    "bih0cmFjZWJhY2suZm9ybWF0X3N0YWNrKCkpCiAgICAgICAgICAgICAgICBfZWFybHlfbG9nKGYi"
    "W1NUQUNLIEFUIFFUSFJFQUQgV0FSTklOR11cbntzdGFja30iKQoKICAgICAgICBxSW5zdGFsbE1l"
    "c3NhZ2VIYW5kbGVyKHF0X21lc3NhZ2VfaGFuZGxlcikKICAgICAgICBfZWFybHlfbG9nKCJbSU5J"
    "VF0gUXQgbWVzc2FnZSBoYW5kbGVyIGluc3RhbGxlZCIpCiAgICBleGNlcHQgRXhjZXB0aW9uIGFz"
    "IGU6CiAgICAgICAgX2Vhcmx5X2xvZyhmIltJTklUXSBDb3VsZCBub3QgaW5zdGFsbCBRdCBtZXNz"
    "YWdlIGhhbmRsZXI6IHtlfSIpCgpfZWFybHlfbG9nKGYiW0lOSVRdIHtERUNLX05BTUV9IGRlY2sg"
    "c3RhcnRpbmciKQpfZWFybHlfbG9nKGYiW0lOSVRdIFB5dGhvbiB7c3lzLnZlcnNpb24uc3BsaXQo"
    "KVswXX0gYXQge3N5cy5leGVjdXRhYmxlfSIpCl9lYXJseV9sb2coZiJbSU5JVF0gV29ya2luZyBk"
    "aXJlY3Rvcnk6IHtvcy5nZXRjd2QoKX0iKQpfZWFybHlfbG9nKGYiW0lOSVRdIFNjcmlwdCBsb2Nh"
    "dGlvbjoge1BhdGgoX19maWxlX18pLnJlc29sdmUoKX0iKQoKIyDilIDilIAgT1BUSU9OQUwgREVQ"
    "RU5ERU5DWSBHVUFSRFMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACgpQU1VUSUxfT0sg"
    "PSBGYWxzZQp0cnk6CiAgICBpbXBvcnQgcHN1dGlsCiAgICBQU1VUSUxfT0sgPSBUcnVlCiAgICBf"
    "ZWFybHlfbG9nKCJbSU1QT1JUXSBwc3V0aWwgT0siKQpleGNlcHQgSW1wb3J0RXJyb3IgYXMgZToK"
    "ICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSBwc3V0aWwgRkFJTEVEOiB7ZX0iKQoKTlZNTF9PSyA9"
    "IEZhbHNlCmdwdV9oYW5kbGUgPSBOb25lCnRyeToKICAgIGltcG9ydCB3YXJuaW5ncwogICAgd2l0"
    "aCB3YXJuaW5ncy5jYXRjaF93YXJuaW5ncygpOgogICAgICAgIHdhcm5pbmdzLnNpbXBsZWZpbHRl"
    "cigiaWdub3JlIikKICAgICAgICBpbXBvcnQgcHludm1sCiAgICBweW52bWwubnZtbEluaXQoKQog"
    "ICAgY291bnQgPSBweW52bWwubnZtbERldmljZUdldENvdW50KCkKICAgIGlmIGNvdW50ID4gMDoK"
    "ICAgICAgICBncHVfaGFuZGxlID0gcHludm1sLm52bWxEZXZpY2VHZXRIYW5kbGVCeUluZGV4KDAp"
    "CiAgICAgICAgTlZNTF9PSyA9IFRydWUKICAgIF9lYXJseV9sb2coZiJbSU1QT1JUXSBweW52bWwg"
    "T0sg4oCUIHtjb3VudH0gR1BVKHMpIikKZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgX2Vhcmx5"
    "X2xvZyhmIltJTVBPUlRdIHB5bnZtbCBGQUlMRUQ6IHtlfSIpCgpUT1JDSF9PSyA9IEZhbHNlCnRy"
    "eToKICAgIGltcG9ydCB0b3JjaAogICAgZnJvbSB0cmFuc2Zvcm1lcnMgaW1wb3J0IEF1dG9Nb2Rl"
    "bEZvckNhdXNhbExNLCBBdXRvVG9rZW5pemVyCiAgICBUT1JDSF9PSyA9IFRydWUKICAgIF9lYXJs"
    "eV9sb2coZiJbSU1QT1JUXSB0b3JjaCB7dG9yY2guX192ZXJzaW9uX199IE9LIikKZXhjZXB0IElt"
    "cG9ydEVycm9yIGFzIGU6CiAgICBfZWFybHlfbG9nKGYiW0lNUE9SVF0gdG9yY2ggRkFJTEVEIChv"
    "cHRpb25hbCk6IHtlfSIpCgpXSU4zMl9PSyA9IEZhbHNlCnRyeToKICAgIGltcG9ydCB3aW4zMmNv"
    "bS5jbGllbnQKICAgIFdJTjMyX09LID0gVHJ1ZQogICAgX2Vhcmx5X2xvZygiW0lNUE9SVF0gd2lu"
    "MzJjb20gT0siKQpleGNlcHQgSW1wb3J0RXJyb3IgYXMgZToKICAgIF9lYXJseV9sb2coZiJbSU1Q"
    "T1JUXSB3aW4zMmNvbSBGQUlMRUQ6IHtlfSIpCgpXSU5TT1VORF9PSyA9IEZhbHNlCnRyeToKICAg"
    "IGltcG9ydCB3aW5zb3VuZAogICAgV0lOU09VTkRfT0sgPSBUcnVlCiAgICBfZWFybHlfbG9nKCJb"
    "SU1QT1JUXSB3aW5zb3VuZCBPSyIpCmV4Y2VwdCBJbXBvcnRFcnJvciBhcyBlOgogICAgX2Vhcmx5"
    "X2xvZyhmIltJTVBPUlRdIHdpbnNvdW5kIEZBSUxFRCAob3B0aW9uYWwpOiB7ZX0iKQoKUFlHQU1F"
    "X09LID0gRmFsc2UKdHJ5OgogICAgaW1wb3J0IHB5Z2FtZQogICAgcHlnYW1lLm1peGVyLmluaXQo"
    "KQogICAgUFlHQU1FX09LID0gVHJ1ZQogICAgX2Vhcmx5X2xvZygiW0lNUE9SVF0gcHlnYW1lIE9L"
    "IikKZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgX2Vhcmx5X2xvZyhmIltJTVBPUlRdIHB5Z2Ft"
    "ZSBGQUlMRUQ6IHtlfSIpCgpHT09HTEVfT0sgPSBGYWxzZQpHT09HTEVfQVBJX09LID0gRmFsc2Ug"
    "ICMgYWxpYXMgdXNlZCBieSBHb29nbGUgc2VydmljZSBjbGFzc2VzCkdPT0dMRV9JTVBPUlRfRVJS"
    "T1IgPSBOb25lCnRyeToKICAgIGZyb20gZ29vZ2xlLmF1dGgudHJhbnNwb3J0LnJlcXVlc3RzIGlt"
    "cG9ydCBSZXF1ZXN0IGFzIEdvb2dsZUF1dGhSZXF1ZXN0CiAgICBmcm9tIGdvb2dsZS5vYXV0aDIu"
    "Y3JlZGVudGlhbHMgaW1wb3J0IENyZWRlbnRpYWxzIGFzIEdvb2dsZUNyZWRlbnRpYWxzCiAgICBm"
    "cm9tIGdvb2dsZV9hdXRoX29hdXRobGliLmZsb3cgaW1wb3J0IEluc3RhbGxlZEFwcEZsb3cKICAg"
    "IGZyb20gZ29vZ2xlYXBpY2xpZW50LmRpc2NvdmVyeSBpbXBvcnQgYnVpbGQgYXMgZ29vZ2xlX2J1"
    "aWxkCiAgICBmcm9tIGdvb2dsZWFwaWNsaWVudC5lcnJvcnMgaW1wb3J0IEh0dHBFcnJvciBhcyBH"
    "b29nbGVIdHRwRXJyb3IKICAgIEdPT0dMRV9PSyA9IFRydWUKICAgIEdPT0dMRV9BUElfT0sgPSBU"
    "cnVlCmV4Y2VwdCBJbXBvcnRFcnJvciBhcyBfZToKICAgIEdPT0dMRV9JTVBPUlRfRVJST1IgPSBz"
    "dHIoX2UpCiAgICBHb29nbGVIdHRwRXJyb3IgPSBFeGNlcHRpb24KCkdPT0dMRV9TQ09QRVMgPSBb"
    "CiAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9jYWxlbmRhciIsCiAgICAiaHR0"
    "cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9jYWxlbmRhci5ldmVudHMiLAogICAgImh0dHBz"
    "Oi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZHJpdmUiLAogICAgImh0dHBzOi8vd3d3Lmdvb2ds"
    "ZWFwaXMuY29tL2F1dGgvZG9jdW1lbnRzIiwKXQpHT09HTEVfU0NPUEVfUkVBVVRIX01TRyA9ICgK"
    "ICAgICJHb29nbGUgdG9rZW4gc2NvcGVzIGFyZSBvdXRkYXRlZCBvciBpbmNvbXBhdGlibGUgd2l0"
    "aCByZXF1ZXN0ZWQgc2NvcGVzLiAiCiAgICAiRGVsZXRlIHRva2VuLmpzb24gYW5kIHJlYXV0aG9y"
    "aXplIHdpdGggdGhlIHVwZGF0ZWQgc2NvcGUgbGlzdC4iCikKREVGQVVMVF9HT09HTEVfSUFOQV9U"
    "SU1FWk9ORSA9ICJBbWVyaWNhL0NoaWNhZ28iCldJTkRPV1NfVFpfVE9fSUFOQSA9IHsKICAgICJD"
    "ZW50cmFsIFN0YW5kYXJkIFRpbWUiOiAiQW1lcmljYS9DaGljYWdvIiwKICAgICJFYXN0ZXJuIFN0"
    "YW5kYXJkIFRpbWUiOiAiQW1lcmljYS9OZXdfWW9yayIsCiAgICAiUGFjaWZpYyBTdGFuZGFyZCBU"
    "aW1lIjogIkFtZXJpY2EvTG9zX0FuZ2VsZXMiLAogICAgIk1vdW50YWluIFN0YW5kYXJkIFRpbWUi"
    "OiAiQW1lcmljYS9EZW52ZXIiLAp9CgoKIyDilIDilIAgUHlTaWRlNiBJTVBPUlRTIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApm"
    "cm9tIFB5U2lkZTYuUXRXaWRnZXRzIGltcG9ydCAoCiAgICBRQXBwbGljYXRpb24sIFFNYWluV2lu"
    "ZG93LCBRV2lkZ2V0LCBRVkJveExheW91dCwgUUhCb3hMYXlvdXQsCiAgICBRR3JpZExheW91dCwg"
    "UVRleHRFZGl0LCBRTGluZUVkaXQsIFFQdXNoQnV0dG9uLCBRTGFiZWwsIFFGcmFtZSwKICAgIFFD"
    "YWxlbmRhcldpZGdldCwgUVRhYmxlV2lkZ2V0LCBRVGFibGVXaWRnZXRJdGVtLCBRSGVhZGVyVmll"
    "dywKICAgIFFBYnN0cmFjdEl0ZW1WaWV3LCBRU3RhY2tlZFdpZGdldCwgUVRhYldpZGdldCwgUUxp"
    "c3RXaWRnZXQsCiAgICBRTGlzdFdpZGdldEl0ZW0sIFFTaXplUG9saWN5LCBRQ29tYm9Cb3gsIFFD"
    "aGVja0JveCwgUUZpbGVEaWFsb2csCiAgICBRTWVzc2FnZUJveCwgUURhdGVFZGl0LCBRRGlhbG9n"
    "LCBRRm9ybUxheW91dCwgUVNjcm9sbEFyZWEsCiAgICBRU3BsaXR0ZXIsIFFJbnB1dERpYWxvZywg"
    "UVRvb2xCdXR0b24sIFFTcGluQm94LCBRR3JhcGhpY3NPcGFjaXR5RWZmZWN0CikKZnJvbSBQeVNp"
    "ZGU2LlF0Q29yZSBpbXBvcnQgKAogICAgUXQsIFFUaW1lciwgUVRocmVhZCwgU2lnbmFsLCBRRGF0"
    "ZSwgUVNpemUsIFFQb2ludCwgUVJlY3QsCiAgICBRUHJvcGVydHlBbmltYXRpb24sIFFFYXNpbmdD"
    "dXJ2ZQopCmZyb20gUHlTaWRlNi5RdEd1aSBpbXBvcnQgKAogICAgUUZvbnQsIFFDb2xvciwgUVBh"
    "aW50ZXIsIFFMaW5lYXJHcmFkaWVudCwgUVJhZGlhbEdyYWRpZW50LAogICAgUVBpeG1hcCwgUVBl"
    "biwgUVBhaW50ZXJQYXRoLCBRVGV4dENoYXJGb3JtYXQsIFFJY29uLAogICAgUVRleHRDdXJzb3Is"
    "IFFBY3Rpb24KKQoKIyDilIDilIAgQVBQIElERU5USVRZIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApBUFBfTkFN"
    "RSAgICAgID0gVUlfV0lORE9XX1RJVExFCkFQUF9WRVJTSU9OICAgPSAiMi4wLjAiCkFQUF9GSUxF"
    "TkFNRSAgPSBmIntERUNLX05BTUUubG93ZXIoKX1fZGVjay5weSIKQlVJTERfREFURSAgICA9ICIy"
    "MDI2LTA0LTA0IgoKIyDilIDilIAgQ09ORklHIExPQURJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgY29uZmln"
    "Lmpzb24gbGl2ZXMgbmV4dCB0byB0aGUgZGVjayAucHkgZmlsZS4KIyBBbGwgcGF0aHMgY29tZSBm"
    "cm9tIGNvbmZpZy4gTm90aGluZyBoYXJkY29kZWQgYmVsb3cgdGhpcyBwb2ludC4KClNDUklQVF9E"
    "SVIgPSBQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCkucGFyZW50CkNPTkZJR19QQVRIID0gU0NSSVBU"
    "X0RJUiAvICJjb25maWcuanNvbiIKCiMgSW5pdGlhbGl6ZSBlYXJseSBsb2cgbm93IHRoYXQgd2Ug"
    "a25vdyB3aGVyZSB3ZSBhcmUKX2luaXRfZWFybHlfbG9nKFNDUklQVF9ESVIpCl9lYXJseV9sb2co"
    "ZiJbSU5JVF0gU0NSSVBUX0RJUiA9IHtTQ1JJUFRfRElSfSIpCl9lYXJseV9sb2coZiJbSU5JVF0g"
    "Q09ORklHX1BBVEggPSB7Q09ORklHX1BBVEh9IikKX2Vhcmx5X2xvZyhmIltJTklUXSBjb25maWcu"
    "anNvbiBleGlzdHM6IHtDT05GSUdfUEFUSC5leGlzdHMoKX0iKQoKZGVmIF9kZWZhdWx0X2NvbmZp"
    "ZygpIC0+IGRpY3Q6CiAgICAiIiJSZXR1cm5zIHRoZSBkZWZhdWx0IGNvbmZpZyBzdHJ1Y3R1cmUg"
    "Zm9yIGZpcnN0LXJ1biBnZW5lcmF0aW9uLiIiIgogICAgYmFzZSA9IHN0cihTQ1JJUFRfRElSKQog"
    "ICAgcmV0dXJuIHsKICAgICAgICAiZGVja19uYW1lIjogREVDS19OQU1FLAogICAgICAgICJkZWNr"
    "X3ZlcnNpb24iOiBBUFBfVkVSU0lPTiwKICAgICAgICAiYmFzZV9kaXIiOiBiYXNlLAogICAgICAg"
    "ICJtb2RlbCI6IHsKICAgICAgICAgICAgInR5cGUiOiAibG9jYWwiLCAgICAgICAgICAjIGxvY2Fs"
    "IHwgb2xsYW1hIHwgY2xhdWRlIHwgb3BlbmFpCiAgICAgICAgICAgICJwYXRoIjogIiIsICAgICAg"
    "ICAgICAgICAgIyBsb2NhbCBtb2RlbCBmb2xkZXIgcGF0aAogICAgICAgICAgICAib2xsYW1hX21v"
    "ZGVsIjogIiIsICAgICAgICMgZS5nLiAiZG9scGhpbi0yLjYtN2IiCiAgICAgICAgICAgICJhcGlf"
    "a2V5IjogIiIsICAgICAgICAgICAgIyBDbGF1ZGUgb3IgT3BlbkFJIGtleQogICAgICAgICAgICAi"
    "YXBpX3R5cGUiOiAiIiwgICAgICAgICAgICMgImNsYXVkZSIgfCAib3BlbmFpIgogICAgICAgICAg"
    "ICAiYXBpX21vZGVsIjogIiIsICAgICAgICAgICMgZS5nLiAiY2xhdWRlLXNvbm5ldC00LTYiCiAg"
    "ICAgICAgfSwKICAgICAgICAiZ29vZ2xlIjogewogICAgICAgICAgICAiY3JlZGVudGlhbHMiOiBz"
    "dHIoU0NSSVBUX0RJUiAvICJnb29nbGUiIC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIiksCiAg"
    "ICAgICAgICAgICJ0b2tlbiI6ICAgICAgIHN0cihTQ1JJUFRfRElSIC8gImdvb2dsZSIgLyAidG9r"
    "ZW4uanNvbiIpLAogICAgICAgICAgICAidGltZXpvbmUiOiAgICAiQW1lcmljYS9DaGljYWdvIiwK"
    "ICAgICAgICAgICAgInNjb3BlcyI6IFsKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29n"
    "bGVhcGlzLmNvbS9hdXRoL2NhbGVuZGFyLmV2ZW50cyIsCiAgICAgICAgICAgICAgICAiaHR0cHM6"
    "Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9kcml2ZSIsCiAgICAgICAgICAgICAgICAiaHR0cHM6"
    "Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9kb2N1bWVudHMiLAogICAgICAgICAgICBdLAogICAg"
    "ICAgIH0sCiAgICAgICAgInBhdGhzIjogewogICAgICAgICAgICAiZmFjZXMiOiAgICBzdHIoU0NS"
    "SVBUX0RJUiAvICJGYWNlcyIpLAogICAgICAgICAgICAic291bmRzIjogICBzdHIoU0NSSVBUX0RJ"
    "UiAvICJzb3VuZHMiKSwKICAgICAgICAgICAgIm1lbW9yaWVzIjogc3RyKFNDUklQVF9ESVIgLyAi"
    "bWVtb3JpZXMiKSwKICAgICAgICAgICAgInNlc3Npb25zIjogc3RyKFNDUklQVF9ESVIgLyAic2Vz"
    "c2lvbnMiKSwKICAgICAgICAgICAgInNsIjogICAgICAgc3RyKFNDUklQVF9ESVIgLyAic2wiKSwK"
    "ICAgICAgICAgICAgImV4cG9ydHMiOiAgc3RyKFNDUklQVF9ESVIgLyAiZXhwb3J0cyIpLAogICAg"
    "ICAgICAgICAibG9ncyI6ICAgICBzdHIoU0NSSVBUX0RJUiAvICJsb2dzIiksCiAgICAgICAgICAg"
    "ICJiYWNrdXBzIjogIHN0cihTQ1JJUFRfRElSIC8gImJhY2t1cHMiKSwKICAgICAgICAgICAgInBl"
    "cnNvbmFzIjogc3RyKFNDUklQVF9ESVIgLyAicGVyc29uYXMiKSwKICAgICAgICAgICAgImdvb2ds"
    "ZSI6ICAgc3RyKFNDUklQVF9ESVIgLyAiZ29vZ2xlIiksCiAgICAgICAgfSwKICAgICAgICAic2V0"
    "dGluZ3MiOiB7CiAgICAgICAgICAgICJpZGxlX2VuYWJsZWQiOiAgICAgICAgICAgICAgRmFsc2Us"
    "CiAgICAgICAgICAgICJpZGxlX21pbl9taW51dGVzIjogICAgICAgICAgMTAsCiAgICAgICAgICAg"
    "ICJpZGxlX21heF9taW51dGVzIjogICAgICAgICAgMzAsCiAgICAgICAgICAgICJhdXRvc2F2ZV9p"
    "bnRlcnZhbF9taW51dGVzIjogMTAsCiAgICAgICAgICAgICJtYXhfYmFja3VwcyI6ICAgICAgICAg"
    "ICAgICAgMTAsCiAgICAgICAgICAgICJnb29nbGVfc3luY19lbmFibGVkIjogICAgICAgVHJ1ZSwK"
    "ICAgICAgICAgICAgInNvdW5kX2VuYWJsZWQiOiAgICAgICAgICAgICBUcnVlLAogICAgICAgICAg"
    "ICAiZ29vZ2xlX2luYm91bmRfaW50ZXJ2YWxfbXMiOiAzMDAwMCwKICAgICAgICAgICAgImVtYWls"
    "X3JlZnJlc2hfaW50ZXJ2YWxfbXMiOiAzMDAwMDAsCiAgICAgICAgICAgICJnb29nbGVfbG9va2Jh"
    "Y2tfZGF5cyI6ICAgICAgMzAsCiAgICAgICAgICAgICJ1c2VyX2RlbGF5X3RocmVzaG9sZF9taW4i"
    "OiAgMzAsCiAgICAgICAgICAgICJ0aW1lem9uZV9hdXRvX2RldGVjdCI6ICAgICAgVHJ1ZSwKICAg"
    "ICAgICAgICAgInRpbWV6b25lX292ZXJyaWRlIjogICAgICAgICAiIiwKICAgICAgICAgICAgImZ1"
    "bGxzY3JlZW5fZW5hYmxlZCI6ICAgICAgICBGYWxzZSwKICAgICAgICAgICAgImJvcmRlcmxlc3Nf"
    "ZW5hYmxlZCI6ICAgICAgICBGYWxzZSwKICAgICAgICB9LAogICAgICAgICJmaXJzdF9ydW4iOiBU"
    "cnVlLAogICAgfQoKZGVmIGxvYWRfY29uZmlnKCkgLT4gZGljdDoKICAgICIiIkxvYWQgY29uZmln"
    "Lmpzb24uIFJldHVybnMgZGVmYXVsdCBpZiBtaXNzaW5nIG9yIGNvcnJ1cHQuIiIiCiAgICBpZiBu"
    "b3QgQ09ORklHX1BBVEguZXhpc3RzKCk6CiAgICAgICAgcmV0dXJuIF9kZWZhdWx0X2NvbmZpZygp"
    "CiAgICB0cnk6CiAgICAgICAgd2l0aCBDT05GSUdfUEFUSC5vcGVuKCJyIiwgZW5jb2Rpbmc9InV0"
    "Zi04IikgYXMgZjoKICAgICAgICAgICAgcmV0dXJuIGpzb24ubG9hZChmKQogICAgZXhjZXB0IEV4"
    "Y2VwdGlvbjoKICAgICAgICByZXR1cm4gX2RlZmF1bHRfY29uZmlnKCkKCmRlZiBzYXZlX2NvbmZp"
    "ZyhjZmc6IGRpY3QpIC0+IE5vbmU6CiAgICAiIiJXcml0ZSBjb25maWcuanNvbi4iIiIKICAgIENP"
    "TkZJR19QQVRILnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3"
    "aXRoIENPTkZJR19QQVRILm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAg"
    "IGpzb24uZHVtcChjZmcsIGYsIGluZGVudD0yKQoKIyBMb2FkIGNvbmZpZyBhdCBtb2R1bGUgbGV2"
    "ZWwg4oCUIGV2ZXJ5dGhpbmcgYmVsb3cgcmVhZHMgZnJvbSBDRkcKQ0ZHID0gbG9hZF9jb25maWco"
    "KQpfZWFybHlfbG9nKGYiW0lOSVRdIENvbmZpZyBsb2FkZWQg4oCUIGZpcnN0X3J1bj17Q0ZHLmdl"
    "dCgnZmlyc3RfcnVuJyl9LCBtb2RlbF90eXBlPXtDRkcuZ2V0KCdtb2RlbCcse30pLmdldCgndHlw"
    "ZScpfSIpCgpfREVGQVVMVF9QQVRIUzogZGljdFtzdHIsIFBhdGhdID0gewogICAgImZhY2VzIjog"
    "ICAgU0NSSVBUX0RJUiAvICJGYWNlcyIsCiAgICAic291bmRzIjogICBTQ1JJUFRfRElSIC8gInNv"
    "dW5kcyIsCiAgICAibWVtb3JpZXMiOiBTQ1JJUFRfRElSIC8gIm1lbW9yaWVzIiwKICAgICJzZXNz"
    "aW9ucyI6IFNDUklQVF9ESVIgLyAic2Vzc2lvbnMiLAogICAgInNsIjogICAgICAgU0NSSVBUX0RJ"
    "UiAvICJzbCIsCiAgICAiZXhwb3J0cyI6ICBTQ1JJUFRfRElSIC8gImV4cG9ydHMiLAogICAgImxv"
    "Z3MiOiAgICAgU0NSSVBUX0RJUiAvICJsb2dzIiwKICAgICJiYWNrdXBzIjogIFNDUklQVF9ESVIg"
    "LyAiYmFja3VwcyIsCiAgICAicGVyc29uYXMiOiBTQ1JJUFRfRElSIC8gInBlcnNvbmFzIiwKICAg"
    "ICJnb29nbGUiOiAgIFNDUklQVF9ESVIgLyAiZ29vZ2xlIiwKfQoKZGVmIF9ub3JtYWxpemVfY29u"
    "ZmlnX3BhdGhzKCkgLT4gTm9uZToKICAgICIiIgogICAgU2VsZi1oZWFsIG9sZGVyIGNvbmZpZy5q"
    "c29uIGZpbGVzIG1pc3NpbmcgcmVxdWlyZWQgcGF0aCBrZXlzLgogICAgQWRkcyBtaXNzaW5nIHBh"
    "dGgga2V5cyBhbmQgbm9ybWFsaXplcyBnb29nbGUgY3JlZGVudGlhbC90b2tlbiBsb2NhdGlvbnMs"
    "CiAgICB0aGVuIHBlcnNpc3RzIGNvbmZpZy5qc29uIGlmIGFueXRoaW5nIGNoYW5nZWQuCiAgICAi"
    "IiIKICAgIGNoYW5nZWQgPSBGYWxzZQogICAgcGF0aHMgPSBDRkcuc2V0ZGVmYXVsdCgicGF0aHMi"
    "LCB7fSkKICAgIGZvciBrZXksIGRlZmF1bHRfcGF0aCBpbiBfREVGQVVMVF9QQVRIUy5pdGVtcygp"
    "OgogICAgICAgIGlmIG5vdCBwYXRocy5nZXQoa2V5KToKICAgICAgICAgICAgcGF0aHNba2V5XSA9"
    "IHN0cihkZWZhdWx0X3BhdGgpCiAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgZ29vZ2xl"
    "X2NmZyA9IENGRy5zZXRkZWZhdWx0KCJnb29nbGUiLCB7fSkKICAgIGdvb2dsZV9yb290ID0gUGF0"
    "aChwYXRocy5nZXQoImdvb2dsZSIsIHN0cihfREVGQVVMVF9QQVRIU1siZ29vZ2xlIl0pKSkKICAg"
    "IGRlZmF1bHRfY3JlZHMgPSBzdHIoZ29vZ2xlX3Jvb3QgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpz"
    "b24iKQogICAgZGVmYXVsdF90b2tlbiA9IHN0cihnb29nbGVfcm9vdCAvICJ0b2tlbi5qc29uIikK"
    "ICAgIGNyZWRzX3ZhbCA9IHN0cihnb29nbGVfY2ZnLmdldCgiY3JlZGVudGlhbHMiLCAiIikpLnN0"
    "cmlwKCkKICAgIHRva2VuX3ZhbCA9IHN0cihnb29nbGVfY2ZnLmdldCgidG9rZW4iLCAiIikpLnN0"
    "cmlwKCkKICAgIGlmIChub3QgY3JlZHNfdmFsKSBvciAoImNvbmZpZyIgaW4gY3JlZHNfdmFsIGFu"
    "ZCAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iIGluIGNyZWRzX3ZhbCk6CiAgICAgICAgZ29vZ2xl"
    "X2NmZ1siY3JlZGVudGlhbHMiXSA9IGRlZmF1bHRfY3JlZHMKICAgICAgICBjaGFuZ2VkID0gVHJ1"
    "ZQogICAgaWYgbm90IHRva2VuX3ZhbDoKICAgICAgICBnb29nbGVfY2ZnWyJ0b2tlbiJdID0gZGVm"
    "YXVsdF90b2tlbgogICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgaWYgY2hhbmdlZDoKICAgICAg"
    "ICBzYXZlX2NvbmZpZyhDRkcpCgpkZWYgY2ZnX3BhdGgoa2V5OiBzdHIpIC0+IFBhdGg6CiAgICAi"
    "IiJDb252ZW5pZW5jZTogZ2V0IGEgcGF0aCBmcm9tIENGR1sncGF0aHMnXVtrZXldIGFzIGEgUGF0"
    "aCBvYmplY3Qgd2l0aCBzYWZlIGZhbGxiYWNrIGRlZmF1bHRzLiIiIgogICAgcGF0aHMgPSBDRkcu"
    "Z2V0KCJwYXRocyIsIHt9KQogICAgdmFsdWUgPSBwYXRocy5nZXQoa2V5KQogICAgaWYgdmFsdWU6"
    "CiAgICAgICAgcmV0dXJuIFBhdGgodmFsdWUpCiAgICBmYWxsYmFjayA9IF9ERUZBVUxUX1BBVEhT"
    "LmdldChrZXkpCiAgICBpZiBmYWxsYmFjazoKICAgICAgICBwYXRoc1trZXldID0gc3RyKGZhbGxi"
    "YWNrKQogICAgICAgIHJldHVybiBmYWxsYmFjawogICAgcmV0dXJuIFNDUklQVF9ESVIgLyBrZXkK"
    "Cl9ub3JtYWxpemVfY29uZmlnX3BhdGhzKCkKCiMg4pSA4pSAIENPTE9SIENPTlNUQU5UUyDigJQg"
    "ZGVyaXZlZCBmcm9tIHBlcnNvbmEgdGVtcGxhdGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQ19Q"
    "UklNQVJZLCBDX1NFQ09OREFSWSwgQ19BQ0NFTlQsIENfQkcsIENfUEFORUwsIENfQk9SREVSLAoj"
    "IENfVEVYVCwgQ19URVhUX0RJTSBhcmUgaW5qZWN0ZWQgYXQgdGhlIHRvcCBvZiB0aGlzIGZpbGUg"
    "YnkgZGVja19idWlsZGVyLgojIEV2ZXJ5dGhpbmcgYmVsb3cgaXMgZGVyaXZlZCBmcm9tIHRob3Nl"
    "IGluamVjdGVkIHZhbHVlcy4KCiMgU2VtYW50aWMgYWxpYXNlcyDigJQgbWFwIHBlcnNvbmEgY29s"
    "b3JzIHRvIG5hbWVkIHJvbGVzIHVzZWQgdGhyb3VnaG91dCB0aGUgVUkKQ19DUklNU09OICAgICA9"
    "IENfUFJJTUFSWSAgICAgICAgICAjIG1haW4gYWNjZW50IChidXR0b25zLCBib3JkZXJzLCBoaWdo"
    "bGlnaHRzKQpDX0NSSU1TT05fRElNID0gQ19QUklNQVJZICsgIjg4IiAgICMgZGltIGFjY2VudCBm"
    "b3Igc3VidGxlIGJvcmRlcnMKQ19HT0xEICAgICAgICA9IENfU0VDT05EQVJZICAgICAgICAjIG1h"
    "aW4gbGFiZWwvdGV4dC9BSSBvdXRwdXQgY29sb3IKQ19HT0xEX0RJTSAgICA9IENfU0VDT05EQVJZ"
    "ICsgIjg4IiAjIGRpbSBzZWNvbmRhcnkKQ19HT0xEX0JSSUdIVCA9IENfQUNDRU5UICAgICAgICAg"
    "ICAjIGVtcGhhc2lzLCBob3ZlciBzdGF0ZXMKQ19TSUxWRVIgICAgICA9IENfVEVYVF9ESU0gICAg"
    "ICAgICAjIHNlY29uZGFyeSB0ZXh0IChhbHJlYWR5IGluamVjdGVkKQpDX1NJTFZFUl9ESU0gID0g"
    "Q19URVhUX0RJTSArICI4OCIgICMgZGltIHNlY29uZGFyeSB0ZXh0CkNfTU9OSVRPUiAgICAgPSBD"
    "X0JHICAgICAgICAgICAgICAgIyBjaGF0IGRpc3BsYXkgYmFja2dyb3VuZCAoYWxyZWFkeSBpbmpl"
    "Y3RlZCkKQ19CRzIgICAgICAgICA9IENfQkcgICAgICAgICAgICAgICAjIHNlY29uZGFyeSBiYWNr"
    "Z3JvdW5kCkNfQkczICAgICAgICAgPSBDX1BBTkVMICAgICAgICAgICAgIyB0ZXJ0aWFyeS9pbnB1"
    "dCBiYWNrZ3JvdW5kIChhbHJlYWR5IGluamVjdGVkKQpDX0JMT09EICAgICAgID0gJyM4YjAwMDAn"
    "ICAgICAgICAgICMgZXJyb3Igc3RhdGVzLCBkYW5nZXIg4oCUIHVuaXZlcnNhbApDX1BVUlBMRSAg"
    "ICAgID0gJyM4ODU1Y2MnICAgICAgICAgICMgU1lTVEVNIG1lc3NhZ2VzIOKAlCB1bml2ZXJzYWwK"
    "Q19QVVJQTEVfRElNICA9ICcjMmEwNTJhJyAgICAgICAgICAjIGRpbSBwdXJwbGUg4oCUIHVuaXZl"
    "cnNhbApDX0dSRUVOICAgICAgID0gJyM0NGFhNjYnICAgICAgICAgICMgcG9zaXRpdmUgc3RhdGVz"
    "IOKAlCB1bml2ZXJzYWwKQ19CTFVFICAgICAgICA9ICcjNDQ4OGNjJyAgICAgICAgICAjIGluZm8g"
    "c3RhdGVzIOKAlCB1bml2ZXJzYWwKCiMgRm9udCBoZWxwZXIg4oCUIGV4dHJhY3RzIHByaW1hcnkg"
    "Zm9udCBuYW1lIGZvciBRRm9udCgpIGNhbGxzCkRFQ0tfRk9OVCA9IFVJX0ZPTlRfRkFNSUxZLnNw"
    "bGl0KCcsJylbMF0uc3RyaXAoKS5zdHJpcCgiJyIpCgojIEVtb3Rpb24g4oaSIGNvbG9yIG1hcHBp"
    "bmcgKGZvciBlbW90aW9uIHJlY29yZCBjaGlwcykKRU1PVElPTl9DT0xPUlM6IGRpY3Rbc3RyLCBz"
    "dHJdID0gewogICAgInZpY3RvcnkiOiAgICBDX0dPTEQsCiAgICAic211ZyI6ICAgICAgIENfR09M"
    "RCwKICAgICJpbXByZXNzZWQiOiAgQ19HT0xELAogICAgInJlbGlldmVkIjogICBDX0dPTEQsCiAg"
    "ICAiaGFwcHkiOiAgICAgIENfR09MRCwKICAgICJmbGlydHkiOiAgICAgQ19HT0xELAogICAgInBh"
    "bmlja2VkIjogICBDX0NSSU1TT04sCiAgICAiYW5ncnkiOiAgICAgIENfQ1JJTVNPTiwKICAgICJz"
    "aG9ja2VkIjogICAgQ19DUklNU09OLAogICAgImNoZWF0bW9kZSI6ICBDX0NSSU1TT04sCiAgICAi"
    "Y29uY2VybmVkIjogICIjY2M2NjIyIiwKICAgICJzYWQiOiAgICAgICAgIiNjYzY2MjIiLAogICAg"
    "Imh1bWlsaWF0ZWQiOiAiI2NjNjYyMiIsCiAgICAiZmx1c3RlcmVkIjogICIjY2M2NjIyIiwKICAg"
    "ICJwbG90dGluZyI6ICAgQ19QVVJQTEUsCiAgICAic3VzcGljaW91cyI6IENfUFVSUExFLAogICAg"
    "ImVudmlvdXMiOiAgICBDX1BVUlBMRSwKICAgICJmb2N1c2VkIjogICAgQ19TSUxWRVIsCiAgICAi"
    "YWxlcnQiOiAgICAgIENfU0lMVkVSLAogICAgIm5ldXRyYWwiOiAgICBDX1RFWFRfRElNLAp9Cgoj"
    "IOKUgOKUgCBERUNPUkFUSVZFIENPTlNUQU5UUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKIyBSVU5FUyBpcyBzb3VyY2VkIGZyb20gVUlfUlVORVMgaW5q"
    "ZWN0ZWQgYnkgdGhlIHBlcnNvbmEgdGVtcGxhdGUKUlVORVMgPSBVSV9SVU5FUwoKIyBGYWNlIGlt"
    "YWdlIG1hcCDigJQgcHJlZml4IGZyb20gRkFDRV9QUkVGSVgsIGZpbGVzIGxpdmUgaW4gY29uZmln"
    "IHBhdGhzLmZhY2VzCkZBQ0VfRklMRVM6IGRpY3Rbc3RyLCBzdHJdID0gewogICAgIm5ldXRyYWwi"
    "OiAgICBmIntGQUNFX1BSRUZJWH1fTmV1dHJhbC5wbmciLAogICAgImFsZXJ0IjogICAgICBmIntG"
    "QUNFX1BSRUZJWH1fQWxlcnQucG5nIiwKICAgICJmb2N1c2VkIjogICAgZiJ7RkFDRV9QUkVGSVh9"
    "X0ZvY3VzZWQucG5nIiwKICAgICJzbXVnIjogICAgICAgZiJ7RkFDRV9QUkVGSVh9X1NtdWcucG5n"
    "IiwKICAgICJjb25jZXJuZWQiOiAgZiJ7RkFDRV9QUkVGSVh9X0NvbmNlcm5lZC5wbmciLAogICAg"
    "InNhZCI6ICAgICAgICBmIntGQUNFX1BSRUZJWH1fU2FkX0NyeWluZy5wbmciLAogICAgInJlbGll"
    "dmVkIjogICBmIntGQUNFX1BSRUZJWH1fUmVsaWV2ZWQucG5nIiwKICAgICJpbXByZXNzZWQiOiAg"
    "ZiJ7RkFDRV9QUkVGSVh9X0ltcHJlc3NlZC5wbmciLAogICAgInZpY3RvcnkiOiAgICBmIntGQUNF"
    "X1BSRUZJWH1fVmljdG9yeS5wbmciLAogICAgImh1bWlsaWF0ZWQiOiBmIntGQUNFX1BSRUZJWH1f"
    "SHVtaWxpYXRlZC5wbmciLAogICAgInN1c3BpY2lvdXMiOiBmIntGQUNFX1BSRUZJWH1fU3VzcGlj"
    "aW91cy5wbmciLAogICAgInBhbmlja2VkIjogICBmIntGQUNFX1BSRUZJWH1fUGFuaWNrZWQucG5n"
    "IiwKICAgICJjaGVhdG1vZGUiOiAgZiJ7RkFDRV9QUkVGSVh9X0NoZWF0X01vZGUucG5nIiwKICAg"
    "ICJhbmdyeSI6ICAgICAgZiJ7RkFDRV9QUkVGSVh9X0FuZ3J5LnBuZyIsCiAgICAicGxvdHRpbmci"
    "OiAgIGYie0ZBQ0VfUFJFRklYfV9QbG90dGluZy5wbmciLAogICAgInNob2NrZWQiOiAgICBmIntG"
    "QUNFX1BSRUZJWH1fU2hvY2tlZC5wbmciLAogICAgImhhcHB5IjogICAgICBmIntGQUNFX1BSRUZJ"
    "WH1fSGFwcHkucG5nIiwKICAgICJmbGlydHkiOiAgICAgZiJ7RkFDRV9QUkVGSVh9X0ZsaXJ0eS5w"
    "bmciLAogICAgImZsdXN0ZXJlZCI6ICBmIntGQUNFX1BSRUZJWH1fRmx1c3RlcmVkLnBuZyIsCiAg"
    "ICAiZW52aW91cyI6ICAgIGYie0ZBQ0VfUFJFRklYfV9FbnZpb3VzLnBuZyIsCn0KClNFTlRJTUVO"
    "VF9MSVNUID0gKAogICAgIm5ldXRyYWwsIGFsZXJ0LCBmb2N1c2VkLCBzbXVnLCBjb25jZXJuZWQs"
    "IHNhZCwgcmVsaWV2ZWQsIGltcHJlc3NlZCwgIgogICAgInZpY3RvcnksIGh1bWlsaWF0ZWQsIHN1"
    "c3BpY2lvdXMsIHBhbmlja2VkLCBhbmdyeSwgcGxvdHRpbmcsIHNob2NrZWQsICIKICAgICJoYXBw"
    "eSwgZmxpcnR5LCBmbHVzdGVyZWQsIGVudmlvdXMiCikKCiMg4pSA4pSAIFNZU1RFTSBQUk9NUFQg"
    "4oCUIGluamVjdGVkIGZyb20gcGVyc29uYSB0ZW1wbGF0ZSBhdCB0b3Agb2YgZmlsZSDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBTWVNURU1fUFJPTVBUX0JBU0UgaXMg"
    "YWxyZWFkeSBkZWZpbmVkIGFib3ZlIGZyb20gPDw8U1lTVEVNX1BST01QVD4+PiBpbmplY3Rpb24u"
    "CiMgRG8gbm90IHJlZGVmaW5lIGl0IGhlcmUuCgojIOKUgOKUgCBHTE9CQUwgU1RZTEVTSEVFVCDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "U1RZTEUgPSBmIiIiClFNYWluV2luZG93LCBRV2lkZ2V0IHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9y"
    "OiB7Q19CR307CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRf"
    "RkFNSUxZfTsKfX0KUVRleHRFZGl0IHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19NT05JVE9S"
    "fTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05f"
    "RElNfTsKICAgIGJvcmRlci1yYWRpdXM6IDJweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9G"
    "QU1JTFl9OwogICAgZm9udC1zaXplOiAxMnB4OwogICAgcGFkZGluZzogOHB4OwogICAgc2VsZWN0"
    "aW9uLWJhY2tncm91bmQtY29sb3I6IHtDX0NSSU1TT05fRElNfTsKfX0KUUxpbmVFZGl0IHt7CiAg"
    "ICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9y"
    "ZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07CiAgICBib3JkZXItcmFkaXVzOiAycHg7CiAgICBm"
    "b250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKICAgIGZvbnQtc2l6ZTogMTNweDsKICAgIHBh"
    "ZGRpbmc6IDhweCAxMnB4Owp9fQpRTGluZUVkaXQ6Zm9jdXMge3sKICAgIGJvcmRlcjogMXB4IHNv"
    "bGlkIHtDX0dPTER9OwogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfUEFORUx9Owp9fQpRUHVzaEJ1"
    "dHRvbiB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQ1JJTVNPTl9ESU19OwogICAgY29sb3I6"
    "IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07CiAgICBib3JkZXIt"
    "cmFkaXVzOiAycHg7CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKICAgIGZvbnQt"
    "c2l6ZTogMTJweDsKICAgIGZvbnQtd2VpZ2h0OiBib2xkOwogICAgcGFkZGluZzogOHB4IDIwcHg7"
    "CiAgICBsZXR0ZXItc3BhY2luZzogMnB4Owp9fQpRUHVzaEJ1dHRvbjpob3ZlciB7ewogICAgYmFj"
    "a2dyb3VuZC1jb2xvcjoge0NfQ1JJTVNPTn07CiAgICBjb2xvcjoge0NfR09MRF9CUklHSFR9Owp9"
    "fQpRUHVzaEJ1dHRvbjpwcmVzc2VkIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19CTE9PRH07"
    "CiAgICBib3JkZXItY29sb3I6IHtDX0JMT09EfTsKICAgIGNvbG9yOiB7Q19URVhUfTsKfX0KUVB1"
    "c2hCdXR0b246ZGlzYWJsZWQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JHM307CiAgICBj"
    "b2xvcjoge0NfVEVYVF9ESU19OwogICAgYm9yZGVyLWNvbG9yOiB7Q19URVhUX0RJTX07Cn19ClFT"
    "Y3JvbGxCYXI6dmVydGljYWwge3sKICAgIGJhY2tncm91bmQ6IHtDX0JHfTsKICAgIHdpZHRoOiA2"
    "cHg7CiAgICBib3JkZXI6IG5vbmU7Cn19ClFTY3JvbGxCYXI6OmhhbmRsZTp2ZXJ0aWNhbCB7ewog"
    "ICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OwogICAgYm9yZGVyLXJhZGl1czogM3B4Owp9"
    "fQpRU2Nyb2xsQmFyOjpoYW5kbGU6dmVydGljYWw6aG92ZXIge3sKICAgIGJhY2tncm91bmQ6IHtD"
    "X0NSSU1TT059Owp9fQpRU2Nyb2xsQmFyOjphZGQtbGluZTp2ZXJ0aWNhbCwgUVNjcm9sbEJhcjo6"
    "c3ViLWxpbmU6dmVydGljYWwge3sKICAgIGhlaWdodDogMHB4Owp9fQpRVGFiV2lkZ2V0OjpwYW5l"
    "IHt7CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBiYWNrZ3JvdW5k"
    "OiB7Q19CRzJ9Owp9fQpRVGFiQmFyOjp0YWIge3sKICAgIGJhY2tncm91bmQ6IHtDX0JHM307CiAg"
    "ICBjb2xvcjoge0NfVEVYVF9ESU19OwogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9E"
    "SU19OwogICAgcGFkZGluZzogNnB4IDE0cHg7CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFN"
    "SUxZfTsKICAgIGZvbnQtc2l6ZTogMTBweDsKICAgIGxldHRlci1zcGFjaW5nOiAxcHg7Cn19ClFU"
    "YWJCYXI6OnRhYjpzZWxlY3RlZCB7ewogICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19Owog"
    "ICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyLWJvdHRvbTogMnB4IHNvbGlkIHtDX0NSSU1T"
    "T059Owp9fQpRVGFiQmFyOjp0YWI6aG92ZXIge3sKICAgIGJhY2tncm91bmQ6IHtDX1BBTkVMfTsK"
    "ICAgIGNvbG9yOiB7Q19HT0xEX0RJTX07Cn19ClFUYWJsZVdpZGdldCB7ewogICAgYmFja2dyb3Vu"
    "ZDoge0NfQkcyfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtD"
    "X0NSSU1TT05fRElNfTsKICAgIGdyaWRsaW5lLWNvbG9yOiB7Q19CT1JERVJ9OwogICAgZm9udC1m"
    "YW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDExcHg7Cn19ClFUYWJsZVdp"
    "ZGdldDo6aXRlbTpzZWxlY3RlZCB7ewogICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19Owog"
    "ICAgY29sb3I6IHtDX0dPTERfQlJJR0hUfTsKfX0KUUhlYWRlclZpZXc6OnNlY3Rpb24ge3sKICAg"
    "IGJhY2tncm91bmQ6IHtDX0JHM307CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBwYWRkaW5nOiA0cHg7CiAgICBmb250LWZhbWls"
    "eToge1VJX0ZPTlRfRkFNSUxZfTsKICAgIGZvbnQtc2l6ZTogMTBweDsKICAgIGZvbnQtd2VpZ2h0"
    "OiBib2xkOwogICAgbGV0dGVyLXNwYWNpbmc6IDFweDsKfX0KUUNvbWJvQm94IHt7CiAgICBiYWNr"
    "Z3JvdW5kOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29s"
    "aWQge0NfQ1JJTVNPTl9ESU19OwogICAgcGFkZGluZzogNHB4IDhweDsKICAgIGZvbnQtZmFtaWx5"
    "OiB7VUlfRk9OVF9GQU1JTFl9Owp9fQpRQ29tYm9Cb3g6OmRyb3AtZG93biB7ewogICAgYm9yZGVy"
    "OiBub25lOwp9fQpRQ2hlY2tCb3gge3sKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGZvbnQtZmFt"
    "aWx5OiB7VUlfRk9OVF9GQU1JTFl9Owp9fQpRTGFiZWwge3sKICAgIGNvbG9yOiB7Q19HT0xEfTsK"
    "ICAgIGJvcmRlcjogbm9uZTsKfX0KUVNwbGl0dGVyOjpoYW5kbGUge3sKICAgIGJhY2tncm91bmQ6"
    "IHtDX0NSSU1TT05fRElNfTsKICAgIHdpZHRoOiAycHg7Cn19CiIiIgoKIyDilIDilIAgRElSRUNU"
    "T1JZIEJPT1RTVFJBUCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKZGVmIGJvb3RzdHJhcF9kaXJlY3RvcmllcygpIC0+IE5vbmU6CiAgICAiIiIKICAg"
    "IENyZWF0ZSBhbGwgcmVxdWlyZWQgZGlyZWN0b3JpZXMgaWYgdGhleSBkb24ndCBleGlzdC4KICAg"
    "IENhbGxlZCBvbiBzdGFydHVwIGJlZm9yZSBhbnl0aGluZyBlbHNlLiBTYWZlIHRvIGNhbGwgbXVs"
    "dGlwbGUgdGltZXMuCiAgICBBbHNvIG1pZ3JhdGVzIGZpbGVzIGZyb20gb2xkIFtEZWNrTmFtZV1f"
    "TWVtb3JpZXMgbGF5b3V0IGlmIGRldGVjdGVkLgogICAgIiIiCiAgICBkaXJzID0gWwogICAgICAg"
    "IGNmZ19wYXRoKCJmYWNlcyIpLAogICAgICAgIGNmZ19wYXRoKCJzb3VuZHMiKSwKICAgICAgICBj"
    "ZmdfcGF0aCgibWVtb3JpZXMiKSwKICAgICAgICBjZmdfcGF0aCgic2Vzc2lvbnMiKSwKICAgICAg"
    "ICBjZmdfcGF0aCgic2wiKSwKICAgICAgICBjZmdfcGF0aCgiZXhwb3J0cyIpLAogICAgICAgIGNm"
    "Z19wYXRoKCJsb2dzIiksCiAgICAgICAgY2ZnX3BhdGgoImJhY2t1cHMiKSwKICAgICAgICBjZmdf"
    "cGF0aCgicGVyc29uYXMiKSwKICAgICAgICBjZmdfcGF0aCgiZ29vZ2xlIiksCiAgICAgICAgY2Zn"
    "X3BhdGgoImdvb2dsZSIpIC8gImV4cG9ydHMiLAogICAgXQogICAgZm9yIGQgaW4gZGlyczoKICAg"
    "ICAgICBkLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKCiAgICAjIENyZWF0ZSBl"
    "bXB0eSBKU09OTCBmaWxlcyBpZiB0aGV5IGRvbid0IGV4aXN0CiAgICBtZW1vcnlfZGlyID0gY2Zn"
    "X3BhdGgoIm1lbW9yaWVzIikKICAgIGZvciBmbmFtZSBpbiAoIm1lc3NhZ2VzLmpzb25sIiwgIm1l"
    "bW9yaWVzLmpzb25sIiwgInRhc2tzLmpzb25sIiwKICAgICAgICAgICAgICAgICAgImxlc3NvbnNf"
    "bGVhcm5lZC5qc29ubCIsICJwZXJzb25hX2hpc3RvcnkuanNvbmwiKToKICAgICAgICBmcCA9IG1l"
    "bW9yeV9kaXIgLyBmbmFtZQogICAgICAgIGlmIG5vdCBmcC5leGlzdHMoKToKICAgICAgICAgICAg"
    "ZnAud3JpdGVfdGV4dCgiIiwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBzbF9kaXIgPSBjZmdfcGF0"
    "aCgic2wiKQogICAgZm9yIGZuYW1lIGluICgic2xfc2NhbnMuanNvbmwiLCAic2xfY29tbWFuZHMu"
    "anNvbmwiKToKICAgICAgICBmcCA9IHNsX2RpciAvIGZuYW1lCiAgICAgICAgaWYgbm90IGZwLmV4"
    "aXN0cygpOgogICAgICAgICAgICBmcC53cml0ZV90ZXh0KCIiLCBlbmNvZGluZz0idXRmLTgiKQoK"
    "ICAgIHNlc3Npb25zX2RpciA9IGNmZ19wYXRoKCJzZXNzaW9ucyIpCiAgICBpZHggPSBzZXNzaW9u"
    "c19kaXIgLyAic2Vzc2lvbl9pbmRleC5qc29uIgogICAgaWYgbm90IGlkeC5leGlzdHMoKToKICAg"
    "ICAgICBpZHgud3JpdGVfdGV4dChqc29uLmR1bXBzKHsic2Vzc2lvbnMiOiBbXX0sIGluZGVudD0y"
    "KSwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBzdGF0ZV9wYXRoID0gbWVtb3J5X2RpciAvICJzdGF0"
    "ZS5qc29uIgogICAgaWYgbm90IHN0YXRlX3BhdGguZXhpc3RzKCk6CiAgICAgICAgX3dyaXRlX2Rl"
    "ZmF1bHRfc3RhdGUoc3RhdGVfcGF0aCkKCiAgICBpbmRleF9wYXRoID0gbWVtb3J5X2RpciAvICJp"
    "bmRleC5qc29uIgogICAgaWYgbm90IGluZGV4X3BhdGguZXhpc3RzKCk6CiAgICAgICAgaW5kZXhf"
    "cGF0aC53cml0ZV90ZXh0KAogICAgICAgICAgICBqc29uLmR1bXBzKHsidmVyc2lvbiI6IEFQUF9W"
    "RVJTSU9OLCAidG90YWxfbWVzc2FnZXMiOiAwLAogICAgICAgICAgICAgICAgICAgICAgICAidG90"
    "YWxfbWVtb3JpZXMiOiAwfSwgaW5kZW50PTIpLAogICAgICAgICAgICBlbmNvZGluZz0idXRmLTgi"
    "CiAgICAgICAgKQoKICAgICMgTGVnYWN5IG1pZ3JhdGlvbjogaWYgb2xkIE1vcmdhbm5hX01lbW9y"
    "aWVzIGZvbGRlciBleGlzdHMsIG1pZ3JhdGUgZmlsZXMKICAgIF9taWdyYXRlX2xlZ2FjeV9maWxl"
    "cygpCgpkZWYgX3dyaXRlX2RlZmF1bHRfc3RhdGUocGF0aDogUGF0aCkgLT4gTm9uZToKICAgIHN0"
    "YXRlID0gewogICAgICAgICJwZXJzb25hX25hbWUiOiBERUNLX05BTUUsCiAgICAgICAgImRlY2tf"
    "dmVyc2lvbiI6IEFQUF9WRVJTSU9OLAogICAgICAgICJzZXNzaW9uX2NvdW50IjogMCwKICAgICAg"
    "ICAibGFzdF9zdGFydHVwIjogTm9uZSwKICAgICAgICAibGFzdF9zaHV0ZG93biI6IE5vbmUsCiAg"
    "ICAgICAgImxhc3RfYWN0aXZlIjogTm9uZSwKICAgICAgICAidG90YWxfbWVzc2FnZXMiOiAwLAog"
    "ICAgICAgICJ0b3RhbF9tZW1vcmllcyI6IDAsCiAgICAgICAgImludGVybmFsX25hcnJhdGl2ZSI6"
    "IHt9LAogICAgICAgICJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3duIjogIkRPUk1BTlQiLAogICAg"
    "fQogICAgcGF0aC53cml0ZV90ZXh0KGpzb24uZHVtcHMoc3RhdGUsIGluZGVudD0yKSwgZW5jb2Rp"
    "bmc9InV0Zi04IikKCmRlZiBfbWlncmF0ZV9sZWdhY3lfZmlsZXMoKSAtPiBOb25lOgogICAgIiIi"
    "CiAgICBJZiBvbGQgRDpcXEFJXFxNb2RlbHNcXFtEZWNrTmFtZV1fTWVtb3JpZXMgbGF5b3V0IGlz"
    "IGRldGVjdGVkLAogICAgbWlncmF0ZSBmaWxlcyB0byBuZXcgc3RydWN0dXJlIHNpbGVudGx5Lgog"
    "ICAgIiIiCiAgICAjIFRyeSB0byBmaW5kIG9sZCBsYXlvdXQgcmVsYXRpdmUgdG8gbW9kZWwgcGF0"
    "aAogICAgbW9kZWxfcGF0aCA9IFBhdGgoQ0ZHWyJtb2RlbCJdLmdldCgicGF0aCIsICIiKSkKICAg"
    "IGlmIG5vdCBtb2RlbF9wYXRoLmV4aXN0cygpOgogICAgICAgIHJldHVybgogICAgb2xkX3Jvb3Qg"
    "PSBtb2RlbF9wYXRoLnBhcmVudCAvIGYie0RFQ0tfTkFNRX1fTWVtb3JpZXMiCiAgICBpZiBub3Qg"
    "b2xkX3Jvb3QuZXhpc3RzKCk6CiAgICAgICAgcmV0dXJuCgogICAgbWlncmF0aW9ucyA9IFsKICAg"
    "ICAgICAob2xkX3Jvb3QgLyAibWVtb3JpZXMuanNvbmwiLCAgICAgICAgICAgY2ZnX3BhdGgoIm1l"
    "bW9yaWVzIikgLyAibWVtb3JpZXMuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAibWVzc2Fn"
    "ZXMuanNvbmwiLCAgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gIm1lc3NhZ2VzLmpz"
    "b25sIiksCiAgICAgICAgKG9sZF9yb290IC8gInRhc2tzLmpzb25sIiwgICAgICAgICAgICAgICBj"
    "ZmdfcGF0aCgibWVtb3JpZXMiKSAvICJ0YXNrcy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAv"
    "ICJzdGF0ZS5qc29uIiwgICAgICAgICAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAic3Rh"
    "dGUuanNvbiIpLAogICAgICAgIChvbGRfcm9vdCAvICJpbmRleC5qc29uIiwgICAgICAgICAgICAg"
    "ICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAiaW5kZXguanNvbiIpLAogICAgICAgIChvbGRfcm9v"
    "dCAvICJzbF9zY2Fucy5qc29ubCIsICAgICAgICAgICAgY2ZnX3BhdGgoInNsIikgLyAic2xfc2Nh"
    "bnMuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAic2xfY29tbWFuZHMuanNvbmwiLCAgICAg"
    "ICAgIGNmZ19wYXRoKCJzbCIpIC8gInNsX2NvbW1hbmRzLmpzb25sIiksCiAgICAgICAgKG9sZF9y"
    "b290IC8gImdvb2dsZSIgLyAidG9rZW4uanNvbiIsICAgICBQYXRoKENGR1siZ29vZ2xlIl1bInRv"
    "a2VuIl0pKSwKICAgICAgICAob2xkX3Jvb3QgLyAiY29uZmlnIiAvICJnb29nbGVfY3JlZGVudGlh"
    "bHMuanNvbiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgUGF0aChDRkdbImdvb2dsZSJdWyJjcmVkZW50aWFscyJdKSksCiAgICAgICAgKG9sZF9yb290"
    "IC8gInNvdW5kcyIgLyBmIntTT1VORF9QUkVGSVh9X2FsZXJ0LndhdiIsCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgY2ZnX3BhdGgoInNvdW5kcyIpIC8g"
    "ZiJ7U09VTkRfUFJFRklYfV9hbGVydC53YXYiKSwKICAgIF0KCiAgICBmb3Igc3JjLCBkc3QgaW4g"
    "bWlncmF0aW9uczoKICAgICAgICBpZiBzcmMuZXhpc3RzKCkgYW5kIG5vdCBkc3QuZXhpc3RzKCk6"
    "CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGRzdC5wYXJlbnQubWtkaXIocGFyZW50"
    "cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICAgICAgaW1wb3J0IHNodXRpbAogICAg"
    "ICAgICAgICAgICAgc2h1dGlsLmNvcHkyKHN0cihzcmMpLCBzdHIoZHN0KSkKICAgICAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAjIE1pZ3JhdGUgZmFj"
    "ZSBpbWFnZXMKICAgIG9sZF9mYWNlcyA9IG9sZF9yb290IC8gIkZhY2VzIgogICAgbmV3X2ZhY2Vz"
    "ID0gY2ZnX3BhdGgoImZhY2VzIikKICAgIGlmIG9sZF9mYWNlcy5leGlzdHMoKToKICAgICAgICBm"
    "b3IgaW1nIGluIG9sZF9mYWNlcy5nbG9iKCIqLnBuZyIpOgogICAgICAgICAgICBkc3QgPSBuZXdf"
    "ZmFjZXMgLyBpbWcubmFtZQogICAgICAgICAgICBpZiBub3QgZHN0LmV4aXN0cygpOgogICAgICAg"
    "ICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIGltcG9ydCBzaHV0aWwKICAgICAgICAg"
    "ICAgICAgICAgICBzaHV0aWwuY29weTIoc3RyKGltZyksIHN0cihkc3QpKQogICAgICAgICAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBwYXNzCgojIOKUgOKUgCBE"
    "QVRFVElNRSBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgbG9jYWxfbm93X2lzbygpIC0+IHN0cjoKICAgIHJldHVy"
    "biBkYXRldGltZS5ub3coKS5yZXBsYWNlKG1pY3Jvc2Vjb25kPTApLmlzb2Zvcm1hdCgpCgpkZWYg"
    "cGFyc2VfaXNvKHZhbHVlOiBzdHIpIC0+IE9wdGlvbmFsW2RhdGV0aW1lXToKICAgIGlmIG5vdCB2"
    "YWx1ZToKICAgICAgICByZXR1cm4gTm9uZQogICAgdmFsdWUgPSB2YWx1ZS5zdHJpcCgpCiAgICB0"
    "cnk6CiAgICAgICAgaWYgdmFsdWUuZW5kc3dpdGgoIloiKToKICAgICAgICAgICAgcmV0dXJuIGRh"
    "dGV0aW1lLmZyb21pc29mb3JtYXQodmFsdWVbOi0xXSkucmVwbGFjZSh0emluZm89dGltZXpvbmUu"
    "dXRjKQogICAgICAgIHJldHVybiBkYXRldGltZS5mcm9taXNvZm9ybWF0KHZhbHVlKQogICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICByZXR1cm4gTm9uZQoKX0RBVEVUSU1FX05PUk1BTElaQVRJ"
    "T05fTE9HR0VEOiBzZXRbdHVwbGVdID0gc2V0KCkKCgpkZWYgX3Jlc29sdmVfZGVja190aW1lem9u"
    "ZV9uYW1lKCkgLT4gT3B0aW9uYWxbc3RyXToKICAgIHNldHRpbmdzID0gQ0ZHLmdldCgic2V0dGlu"
    "Z3MiLCB7fSkgaWYgaXNpbnN0YW5jZShDRkcsIGRpY3QpIGVsc2Uge30KICAgIGF1dG9fZGV0ZWN0"
    "ID0gYm9vbChzZXR0aW5ncy5nZXQoInRpbWV6b25lX2F1dG9fZGV0ZWN0IiwgVHJ1ZSkpCiAgICBv"
    "dmVycmlkZSA9IHN0cihzZXR0aW5ncy5nZXQoInRpbWV6b25lX292ZXJyaWRlIiwgIiIpIG9yICIi"
    "KS5zdHJpcCgpCiAgICBpZiBub3QgYXV0b19kZXRlY3QgYW5kIG92ZXJyaWRlOgogICAgICAgIHJl"
    "dHVybiBvdmVycmlkZQogICAgbG9jYWxfdHppbmZvID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9u"
    "ZSgpLnR6aW5mbwogICAgaWYgbG9jYWxfdHppbmZvIGlzIG5vdCBOb25lOgogICAgICAgIHR6X2tl"
    "eSA9IGdldGF0dHIobG9jYWxfdHppbmZvLCAia2V5IiwgTm9uZSkKICAgICAgICBpZiB0el9rZXk6"
    "CiAgICAgICAgICAgIHJldHVybiBzdHIodHpfa2V5KQogICAgICAgIHR6X25hbWUgPSBzdHIobG9j"
    "YWxfdHppbmZvKQogICAgICAgIGlmIHR6X25hbWUgYW5kIHR6X25hbWUudXBwZXIoKSAhPSAiTE9D"
    "QUwiOgogICAgICAgICAgICByZXR1cm4gdHpfbmFtZQogICAgcmV0dXJuIE5vbmUKCgpkZWYgX2xv"
    "Y2FsX3R6aW5mbygpOgogICAgdHpfbmFtZSA9IF9yZXNvbHZlX2RlY2tfdGltZXpvbmVfbmFtZSgp"
    "CiAgICBpZiB0el9uYW1lOgogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIFpvbmVJbmZv"
    "KHR6X25hbWUpCiAgICAgICAgZXhjZXB0IFpvbmVJbmZvTm90Rm91bmRFcnJvcjoKICAgICAgICAg"
    "ICAgX2Vhcmx5X2xvZyhmIltEQVRFVElNRV1bV0FSTl0gVW5rbm93biB0aW1lem9uZSBvdmVycmlk"
    "ZSAne3R6X25hbWV9JywgdXNpbmcgc3lzdGVtIGxvY2FsIHRpbWV6b25lLiIpCiAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgcmV0dXJuIGRhdGV0aW1lLm5vdygp"
    "LmFzdGltZXpvbmUoKS50emluZm8gb3IgdGltZXpvbmUudXRjCgoKZGVmIG5vd19mb3JfY29tcGFy"
    "ZSgpOgogICAgcmV0dXJuIGRhdGV0aW1lLm5vdyhfbG9jYWxfdHppbmZvKCkpCgoKZGVmIG5vcm1h"
    "bGl6ZV9kYXRldGltZV9mb3JfY29tcGFyZShkdF92YWx1ZSwgY29udGV4dDogc3RyID0gIiIpOgog"
    "ICAgaWYgZHRfdmFsdWUgaXMgTm9uZToKICAgICAgICByZXR1cm4gTm9uZQogICAgaWYgbm90IGlz"
    "aW5zdGFuY2UoZHRfdmFsdWUsIGRhdGV0aW1lKToKICAgICAgICByZXR1cm4gTm9uZQogICAgbG9j"
    "YWxfdHogPSBfbG9jYWxfdHppbmZvKCkKICAgIGlmIGR0X3ZhbHVlLnR6aW5mbyBpcyBOb25lOgog"
    "ICAgICAgIG5vcm1hbGl6ZWQgPSBkdF92YWx1ZS5yZXBsYWNlKHR6aW5mbz1sb2NhbF90eikKICAg"
    "ICAgICBrZXkgPSAoIm5haXZlIiwgY29udGV4dCkKICAgICAgICBpZiBrZXkgbm90IGluIF9EQVRF"
    "VElNRV9OT1JNQUxJWkFUSU9OX0xPR0dFRDoKICAgICAgICAgICAgX2Vhcmx5X2xvZygKICAgICAg"
    "ICAgICAgICAgIGYiW0RBVEVUSU1FXVtJTkZPXSBOb3JtYWxpemVkIG5haXZlIGRhdGV0aW1lIHRv"
    "IGxvY2FsIHRpbWV6b25lIGZvciB7Y29udGV4dCBvciAnZ2VuZXJhbCd9IGNvbXBhcmlzb25zLiIK"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICBfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQu"
    "YWRkKGtleSkKICAgICAgICByZXR1cm4gbm9ybWFsaXplZAogICAgbm9ybWFsaXplZCA9IGR0X3Zh"
    "bHVlLmFzdGltZXpvbmUobG9jYWxfdHopCiAgICBkdF90el9uYW1lID0gc3RyKGR0X3ZhbHVlLnR6"
    "aW5mbykKICAgIGtleSA9ICgiYXdhcmUiLCBjb250ZXh0LCBkdF90el9uYW1lKQogICAgaWYga2V5"
    "IG5vdCBpbiBfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQgYW5kIGR0X3R6X25hbWUgbm90"
    "IGluIHsiVVRDIiwgc3RyKGxvY2FsX3R6KX06CiAgICAgICAgX2Vhcmx5X2xvZygKICAgICAgICAg"
    "ICAgZiJbREFURVRJTUVdW0lORk9dIE5vcm1hbGl6ZWQgdGltZXpvbmUtYXdhcmUgZGF0ZXRpbWUg"
    "ZnJvbSB7ZHRfdHpfbmFtZX0gdG8gbG9jYWwgdGltZXpvbmUgZm9yIHtjb250ZXh0IG9yICdnZW5l"
    "cmFsJ30gY29tcGFyaXNvbnMuIgogICAgICAgICkKICAgICAgICBfREFURVRJTUVfTk9STUFMSVpB"
    "VElPTl9MT0dHRUQuYWRkKGtleSkKICAgIHJldHVybiBub3JtYWxpemVkCgoKZGVmIHBhcnNlX2lz"
    "b19mb3JfY29tcGFyZSh2YWx1ZSwgY29udGV4dDogc3RyID0gIiIpOgogICAgcmV0dXJuIG5vcm1h"
    "bGl6ZV9kYXRldGltZV9mb3JfY29tcGFyZShwYXJzZV9pc28odmFsdWUpLCBjb250ZXh0PWNvbnRl"
    "eHQpCgoKZGVmIF90YXNrX2R1ZV9zb3J0X2tleSh0YXNrOiBkaWN0KToKICAgIGR1ZSA9IHBhcnNl"
    "X2lzb19mb3JfY29tcGFyZSgodGFzayBvciB7fSkuZ2V0KCJkdWVfYXQiKSBvciAodGFzayBvciB7"
    "fSkuZ2V0KCJkdWUiKSwgY29udGV4dD0idGFza19zb3J0IikKICAgIGlmIGR1ZSBpcyBOb25lOgog"
    "ICAgICAgIHJldHVybiAoMSwgZGF0ZXRpbWUubWF4LnJlcGxhY2UodHppbmZvPXRpbWV6b25lLnV0"
    "YykpCiAgICByZXR1cm4gKDAsIGR1ZS5hc3RpbWV6b25lKHRpbWV6b25lLnV0YyksICgodGFzayBv"
    "ciB7fSkuZ2V0KCJ0ZXh0Iikgb3IgIiIpLmxvd2VyKCkpCgoKZGVmIGZvcm1hdF9kdXJhdGlvbihz"
    "ZWNvbmRzOiBmbG9hdCkgLT4gc3RyOgogICAgdG90YWwgPSBtYXgoMCwgaW50KHNlY29uZHMpKQog"
    "ICAgZGF5cywgcmVtID0gZGl2bW9kKHRvdGFsLCA4NjQwMCkKICAgIGhvdXJzLCByZW0gPSBkaXZt"
    "b2QocmVtLCAzNjAwKQogICAgbWludXRlcywgc2VjcyA9IGRpdm1vZChyZW0sIDYwKQogICAgcGFy"
    "dHMgPSBbXQogICAgaWYgZGF5czogICAgcGFydHMuYXBwZW5kKGYie2RheXN9ZCIpCiAgICBpZiBo"
    "b3VyczogICBwYXJ0cy5hcHBlbmQoZiJ7aG91cnN9aCIpCiAgICBpZiBtaW51dGVzOiBwYXJ0cy5h"
    "cHBlbmQoZiJ7bWludXRlc31tIikKICAgIGlmIG5vdCBwYXJ0czogcGFydHMuYXBwZW5kKGYie3Nl"
    "Y3N9cyIpCiAgICByZXR1cm4gIiAiLmpvaW4ocGFydHNbOjNdKQoKIyDilIDilIAgTU9PTiBQSEFT"
    "RSBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAojIENvcnJlY3RlZCBpbGx1bWluYXRpb24gbWF0aCDigJQgZGlzcGxheWVkIG1vb24g"
    "bWF0Y2hlcyBsYWJlbGVkIHBoYXNlLgoKX0tOT1dOX05FV19NT09OID0gZGF0ZSgyMDAwLCAxLCA2"
    "KQpfTFVOQVJfQ1lDTEUgICAgPSAyOS41MzA1ODg2NwoKZGVmIGdldF9tb29uX3BoYXNlKCkgLT4g"
    "dHVwbGVbZmxvYXQsIHN0ciwgZmxvYXRdOgogICAgIiIiCiAgICBSZXR1cm5zIChwaGFzZV9mcmFj"
    "dGlvbiwgcGhhc2VfbmFtZSwgaWxsdW1pbmF0aW9uX3BjdCkuCiAgICBwaGFzZV9mcmFjdGlvbjog"
    "MC4wID0gbmV3IG1vb24sIDAuNSA9IGZ1bGwgbW9vbiwgMS4wID0gbmV3IG1vb24gYWdhaW4uCiAg"
    "ICBpbGx1bWluYXRpb25fcGN0OiAw4oCTMTAwLCBjb3JyZWN0ZWQgdG8gbWF0Y2ggdmlzdWFsIHBo"
    "YXNlLgogICAgIiIiCiAgICBkYXlzICA9IChkYXRlLnRvZGF5KCkgLSBfS05PV05fTkVXX01PT04p"
    "LmRheXMKICAgIGN5Y2xlID0gZGF5cyAlIF9MVU5BUl9DWUNMRQogICAgcGhhc2UgPSBjeWNsZSAv"
    "IF9MVU5BUl9DWUNMRQoKICAgIGlmICAgY3ljbGUgPCAxLjg1OiAgIG5hbWUgPSAiTkVXIE1PT04i"
    "CiAgICBlbGlmIGN5Y2xlIDwgNy4zODogICBuYW1lID0gIldBWElORyBDUkVTQ0VOVCIKICAgIGVs"
    "aWYgY3ljbGUgPCA5LjIyOiAgIG5hbWUgPSAiRklSU1QgUVVBUlRFUiIKICAgIGVsaWYgY3ljbGUg"
    "PCAxNC43NzogIG5hbWUgPSAiV0FYSU5HIEdJQkJPVVMiCiAgICBlbGlmIGN5Y2xlIDwgMTYuNjE6"
    "ICBuYW1lID0gIkZVTEwgTU9PTiIKICAgIGVsaWYgY3ljbGUgPCAyMi4xNTogIG5hbWUgPSAiV0FO"
    "SU5HIEdJQkJPVVMiCiAgICBlbGlmIGN5Y2xlIDwgMjMuOTk6ICBuYW1lID0gIkxBU1QgUVVBUlRF"
    "UiIKICAgIGVsc2U6ICAgICAgICAgICAgICAgIG5hbWUgPSAiV0FOSU5HIENSRVNDRU5UIgoKICAg"
    "ICMgQ29ycmVjdGVkIGlsbHVtaW5hdGlvbjogY29zLWJhc2VkLCBwZWFrcyBhdCBmdWxsIG1vb24K"
    "ICAgIGlsbHVtaW5hdGlvbiA9ICgxIC0gbWF0aC5jb3MoMiAqIG1hdGgucGkgKiBwaGFzZSkpIC8g"
    "MiAqIDEwMAogICAgcmV0dXJuIHBoYXNlLCBuYW1lLCByb3VuZChpbGx1bWluYXRpb24sIDEpCgpf"
    "U1VOX0NBQ0hFX0RBVEU6IE9wdGlvbmFsW2RhdGVdID0gTm9uZQpfU1VOX0NBQ0hFX1RaX09GRlNF"
    "VF9NSU46IE9wdGlvbmFsW2ludF0gPSBOb25lCl9TVU5fQ0FDSEVfVElNRVM6IHR1cGxlW3N0ciwg"
    "c3RyXSA9ICgiMDY6MDAiLCAiMTg6MzAiKQoKZGVmIF9yZXNvbHZlX3NvbGFyX2Nvb3JkaW5hdGVz"
    "KCkgLT4gdHVwbGVbZmxvYXQsIGZsb2F0XToKICAgICIiIgogICAgUmVzb2x2ZSBsYXRpdHVkZS9s"
    "b25naXR1ZGUgZnJvbSBydW50aW1lIGNvbmZpZyB3aGVuIGF2YWlsYWJsZS4KICAgIEZhbGxzIGJh"
    "Y2sgdG8gdGltZXpvbmUtZGVyaXZlZCBjb2Fyc2UgZGVmYXVsdHMuCiAgICAiIiIKICAgIGxhdCA9"
    "IE5vbmUKICAgIGxvbiA9IE5vbmUKICAgIHRyeToKICAgICAgICBzZXR0aW5ncyA9IENGRy5nZXQo"
    "InNldHRpbmdzIiwge30pIGlmIGlzaW5zdGFuY2UoQ0ZHLCBkaWN0KSBlbHNlIHt9CiAgICAgICAg"
    "Zm9yIGtleSBpbiAoImxhdGl0dWRlIiwgImxhdCIpOgogICAgICAgICAgICBpZiBrZXkgaW4gc2V0"
    "dGluZ3M6CiAgICAgICAgICAgICAgICBsYXQgPSBmbG9hdChzZXR0aW5nc1trZXldKQogICAgICAg"
    "ICAgICAgICAgYnJlYWsKICAgICAgICBmb3Iga2V5IGluICgibG9uZ2l0dWRlIiwgImxvbiIsICJs"
    "bmciKToKICAgICAgICAgICAgaWYga2V5IGluIHNldHRpbmdzOgogICAgICAgICAgICAgICAgbG9u"
    "ID0gZmxvYXQoc2V0dGluZ3Nba2V5XSkKICAgICAgICAgICAgICAgIGJyZWFrCiAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgIGxhdCA9IE5vbmUKICAgICAgICBsb24gPSBOb25lCgogICAgbm93"
    "X2xvY2FsID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpCiAgICB0el9vZmZzZXQgPSBub3df"
    "bG9jYWwudXRjb2Zmc2V0KCkgb3IgdGltZWRlbHRhKDApCiAgICB0el9vZmZzZXRfaG91cnMgPSB0"
    "el9vZmZzZXQudG90YWxfc2Vjb25kcygpIC8gMzYwMC4wCgogICAgaWYgbG9uIGlzIE5vbmU6CiAg"
    "ICAgICAgbG9uID0gbWF4KC0xODAuMCwgbWluKDE4MC4wLCB0el9vZmZzZXRfaG91cnMgKiAxNS4w"
    "KSkKCiAgICBpZiBsYXQgaXMgTm9uZToKICAgICAgICB0el9uYW1lID0gc3RyKG5vd19sb2NhbC50"
    "emluZm8gb3IgIiIpCiAgICAgICAgc291dGhfaGludCA9IGFueSh0b2tlbiBpbiB0el9uYW1lIGZv"
    "ciB0b2tlbiBpbiAoIkF1c3RyYWxpYSIsICJQYWNpZmljL0F1Y2tsYW5kIiwgIkFtZXJpY2EvU2Fu"
    "dGlhZ28iKSkKICAgICAgICBsYXQgPSAtMzUuMCBpZiBzb3V0aF9oaW50IGVsc2UgMzUuMAoKICAg"
    "IGxhdCA9IG1heCgtNjYuMCwgbWluKDY2LjAsIGxhdCkpCiAgICBsb24gPSBtYXgoLTE4MC4wLCBt"
    "aW4oMTgwLjAsIGxvbikpCiAgICByZXR1cm4gbGF0LCBsb24KCmRlZiBfY2FsY19zb2xhcl9ldmVu"
    "dF9taW51dGVzKGxvY2FsX2RheTogZGF0ZSwgbGF0aXR1ZGU6IGZsb2F0LCBsb25naXR1ZGU6IGZs"
    "b2F0LCBzdW5yaXNlOiBib29sKSAtPiBPcHRpb25hbFtmbG9hdF06CiAgICAiIiJOT0FBLXN0eWxl"
    "IHN1bnJpc2Uvc3Vuc2V0IHNvbHZlci4gUmV0dXJucyBsb2NhbCBtaW51dGVzIGZyb20gbWlkbmln"
    "aHQuIiIiCiAgICBuID0gbG9jYWxfZGF5LnRpbWV0dXBsZSgpLnRtX3lkYXkKICAgIGxuZ19ob3Vy"
    "ID0gbG9uZ2l0dWRlIC8gMTUuMAogICAgdCA9IG4gKyAoKDYgLSBsbmdfaG91cikgLyAyNC4wKSBp"
    "ZiBzdW5yaXNlIGVsc2UgbiArICgoMTggLSBsbmdfaG91cikgLyAyNC4wKQoKICAgIE0gPSAoMC45"
    "ODU2ICogdCkgLSAzLjI4OQogICAgTCA9IE0gKyAoMS45MTYgKiBtYXRoLnNpbihtYXRoLnJhZGlh"
    "bnMoTSkpKSArICgwLjAyMCAqIG1hdGguc2luKG1hdGgucmFkaWFucygyICogTSkpKSArIDI4Mi42"
    "MzQKICAgIEwgPSBMICUgMzYwLjAKCiAgICBSQSA9IG1hdGguZGVncmVlcyhtYXRoLmF0YW4oMC45"
    "MTc2NCAqIG1hdGgudGFuKG1hdGgucmFkaWFucyhMKSkpKQogICAgUkEgPSBSQSAlIDM2MC4wCiAg"
    "ICBMX3F1YWRyYW50ID0gKG1hdGguZmxvb3IoTCAvIDkwLjApKSAqIDkwLjAKICAgIFJBX3F1YWRy"
    "YW50ID0gKG1hdGguZmxvb3IoUkEgLyA5MC4wKSkgKiA5MC4wCiAgICBSQSA9IChSQSArIChMX3F1"
    "YWRyYW50IC0gUkFfcXVhZHJhbnQpKSAvIDE1LjAKCiAgICBzaW5fZGVjID0gMC4zOTc4MiAqIG1h"
    "dGguc2luKG1hdGgucmFkaWFucyhMKSkKICAgIGNvc19kZWMgPSBtYXRoLmNvcyhtYXRoLmFzaW4o"
    "c2luX2RlYykpCgogICAgemVuaXRoID0gOTAuODMzCiAgICBjb3NfaCA9IChtYXRoLmNvcyhtYXRo"
    "LnJhZGlhbnMoemVuaXRoKSkgLSAoc2luX2RlYyAqIG1hdGguc2luKG1hdGgucmFkaWFucyhsYXRp"
    "dHVkZSkpKSkgLyAoY29zX2RlYyAqIG1hdGguY29zKG1hdGgucmFkaWFucyhsYXRpdHVkZSkpKQog"
    "ICAgaWYgY29zX2ggPCAtMS4wIG9yIGNvc19oID4gMS4wOgogICAgICAgIHJldHVybiBOb25lCgog"
    "ICAgaWYgc3VucmlzZToKICAgICAgICBIID0gMzYwLjAgLSBtYXRoLmRlZ3JlZXMobWF0aC5hY29z"
    "KGNvc19oKSkKICAgIGVsc2U6CiAgICAgICAgSCA9IG1hdGguZGVncmVlcyhtYXRoLmFjb3MoY29z"
    "X2gpKQogICAgSCAvPSAxNS4wCgogICAgVCA9IEggKyBSQSAtICgwLjA2NTcxICogdCkgLSA2LjYy"
    "MgogICAgVVQgPSAoVCAtIGxuZ19ob3VyKSAlIDI0LjAKCiAgICBsb2NhbF9vZmZzZXRfaG91cnMg"
    "PSAoZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLnV0Y29mZnNldCgpIG9yIHRpbWVkZWx0YSgw"
    "KSkudG90YWxfc2Vjb25kcygpIC8gMzYwMC4wCiAgICBsb2NhbF9ob3VyID0gKFVUICsgbG9jYWxf"
    "b2Zmc2V0X2hvdXJzKSAlIDI0LjAKICAgIHJldHVybiBsb2NhbF9ob3VyICogNjAuMAoKZGVmIF9m"
    "b3JtYXRfbG9jYWxfc29sYXJfdGltZShtaW51dGVzX2Zyb21fbWlkbmlnaHQ6IE9wdGlvbmFsW2Zs"
    "b2F0XSkgLT4gc3RyOgogICAgaWYgbWludXRlc19mcm9tX21pZG5pZ2h0IGlzIE5vbmU6CiAgICAg"
    "ICAgcmV0dXJuICItLTotLSIKICAgIG1pbnMgPSBpbnQocm91bmQobWludXRlc19mcm9tX21pZG5p"
    "Z2h0KSkgJSAoMjQgKiA2MCkKICAgIGhoLCBtbSA9IGRpdm1vZChtaW5zLCA2MCkKICAgIHJldHVy"
    "biBkYXRldGltZS5ub3coKS5yZXBsYWNlKGhvdXI9aGgsIG1pbnV0ZT1tbSwgc2Vjb25kPTAsIG1p"
    "Y3Jvc2Vjb25kPTApLnN0cmZ0aW1lKCIlSDolTSIpCgpkZWYgZ2V0X3N1bl90aW1lcygpIC0+IHR1"
    "cGxlW3N0ciwgc3RyXToKICAgICIiIgogICAgQ29tcHV0ZSBsb2NhbCBzdW5yaXNlL3N1bnNldCB1"
    "c2luZyBzeXN0ZW0gZGF0ZSArIHRpbWV6b25lIGFuZCBvcHRpb25hbAogICAgcnVudGltZSBsYXRp"
    "dHVkZS9sb25naXR1ZGUgaGludHMgd2hlbiBhdmFpbGFibGUuCiAgICBDYWNoZWQgcGVyIGxvY2Fs"
    "IGRhdGUgYW5kIHRpbWV6b25lIG9mZnNldC4KICAgICIiIgogICAgZ2xvYmFsIF9TVU5fQ0FDSEVf"
    "REFURSwgX1NVTl9DQUNIRV9UWl9PRkZTRVRfTUlOLCBfU1VOX0NBQ0hFX1RJTUVTCgogICAgbm93"
    "X2xvY2FsID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpCiAgICB0b2RheSA9IG5vd19sb2Nh"
    "bC5kYXRlKCkKICAgIHR6X29mZnNldF9taW4gPSBpbnQoKG5vd19sb2NhbC51dGNvZmZzZXQoKSBv"
    "ciB0aW1lZGVsdGEoMCkpLnRvdGFsX3NlY29uZHMoKSAvLyA2MCkKCiAgICBpZiBfU1VOX0NBQ0hF"
    "X0RBVEUgPT0gdG9kYXkgYW5kIF9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTiA9PSB0el9vZmZzZXRf"
    "bWluOgogICAgICAgIHJldHVybiBfU1VOX0NBQ0hFX1RJTUVTCgogICAgdHJ5OgogICAgICAgIGxh"
    "dCwgbG9uID0gX3Jlc29sdmVfc29sYXJfY29vcmRpbmF0ZXMoKQogICAgICAgIHN1bnJpc2VfbWlu"
    "ID0gX2NhbGNfc29sYXJfZXZlbnRfbWludXRlcyh0b2RheSwgbGF0LCBsb24sIHN1bnJpc2U9VHJ1"
    "ZSkKICAgICAgICBzdW5zZXRfbWluID0gX2NhbGNfc29sYXJfZXZlbnRfbWludXRlcyh0b2RheSwg"
    "bGF0LCBsb24sIHN1bnJpc2U9RmFsc2UpCiAgICAgICAgaWYgc3VucmlzZV9taW4gaXMgTm9uZSBv"
    "ciBzdW5zZXRfbWluIGlzIE5vbmU6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIlNvbGFy"
    "IGV2ZW50IHVuYXZhaWxhYmxlIGZvciByZXNvbHZlZCBjb29yZGluYXRlcyIpCiAgICAgICAgdGlt"
    "ZXMgPSAoX2Zvcm1hdF9sb2NhbF9zb2xhcl90aW1lKHN1bnJpc2VfbWluKSwgX2Zvcm1hdF9sb2Nh"
    "bF9zb2xhcl90aW1lKHN1bnNldF9taW4pKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICB0"
    "aW1lcyA9ICgiMDY6MDAiLCAiMTg6MzAiKQoKICAgIF9TVU5fQ0FDSEVfREFURSA9IHRvZGF5CiAg"
    "ICBfU1VOX0NBQ0hFX1RaX09GRlNFVF9NSU4gPSB0el9vZmZzZXRfbWluCiAgICBfU1VOX0NBQ0hF"
    "X1RJTUVTID0gdGltZXMKICAgIHJldHVybiB0aW1lcwoKIyDilIDilIAgVkFNUElSRSBTVEFURSBT"
    "WVNURU0g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMg"
    "VGltZS1vZi1kYXkgYmVoYXZpb3JhbCBzdGF0ZS4gQWN0aXZlIG9ubHkgd2hlbiBBSV9TVEFURVNf"
    "RU5BQkxFRD1UcnVlLgojIEluamVjdGVkIGludG8gc3lzdGVtIHByb21wdCBvbiBldmVyeSBnZW5l"
    "cmF0aW9uIGNhbGwuCgpWQU1QSVJFX1NUQVRFUzogZGljdFtzdHIsIGRpY3RdID0gewogICAgIldJ"
    "VENISU5HIEhPVVIiOiAgeyJob3VycyI6IHswfSwgICAgICAgICAgICJjb2xvciI6IENfR09MRCwg"
    "ICAgICAgICJwb3dlciI6IDEuMH0sCiAgICAiREVFUCBOSUdIVCI6ICAgICB7ImhvdXJzIjogezEs"
    "MiwzfSwgICAgICAgICJjb2xvciI6IENfUFVSUExFLCAgICAgICJwb3dlciI6IDAuOTV9LAogICAg"
    "IlRXSUxJR0hUIEZBRElORyI6eyJob3VycyI6IHs0LDV9LCAgICAgICAgICAiY29sb3IiOiBDX1NJ"
    "TFZFUiwgICAgICAicG93ZXIiOiAwLjd9LAogICAgIkRPUk1BTlQiOiAgICAgICAgeyJob3VycyI6"
    "IHs2LDcsOCw5LDEwLDExfSwiY29sb3IiOiBDX1RFWFRfRElNLCAgICAicG93ZXIiOiAwLjJ9LAog"
    "ICAgIlJFU1RMRVNTIFNMRUVQIjogeyJob3VycyI6IHsxMiwxMywxNCwxNX0sICAiY29sb3IiOiBD"
    "X1RFWFRfRElNLCAgICAicG93ZXIiOiAwLjN9LAogICAgIlNUSVJSSU5HIjogICAgICAgeyJob3Vy"
    "cyI6IHsxNiwxN30sICAgICAgICAiY29sb3IiOiBDX0dPTERfRElNLCAgICAicG93ZXIiOiAwLjZ9"
    "LAogICAgIkFXQUtFTkVEIjogICAgICAgeyJob3VycyI6IHsxOCwxOSwyMCwyMX0sICAiY29sb3Ii"
    "OiBDX0dPTEQsICAgICAgICAicG93ZXIiOiAwLjl9LAogICAgIkhVTlRJTkciOiAgICAgICAgeyJo"
    "b3VycyI6IHsyMiwyM30sICAgICAgICAiY29sb3IiOiBDX0NSSU1TT04sICAgICAicG93ZXIiOiAx"
    "LjB9LAp9CgpkZWYgZ2V0X3ZhbXBpcmVfc3RhdGUoKSAtPiBzdHI6CiAgICAiIiJSZXR1cm4gdGhl"
    "IGN1cnJlbnQgdmFtcGlyZSBzdGF0ZSBuYW1lIGJhc2VkIG9uIGxvY2FsIGhvdXIuIiIiCiAgICBo"
    "ID0gZGF0ZXRpbWUubm93KCkuaG91cgogICAgZm9yIHN0YXRlX25hbWUsIGRhdGEgaW4gVkFNUElS"
    "RV9TVEFURVMuaXRlbXMoKToKICAgICAgICBpZiBoIGluIGRhdGFbImhvdXJzIl06CiAgICAgICAg"
    "ICAgIHJldHVybiBzdGF0ZV9uYW1lCiAgICByZXR1cm4gIkRPUk1BTlQiCgpkZWYgZ2V0X3ZhbXBp"
    "cmVfc3RhdGVfY29sb3Ioc3RhdGU6IHN0cikgLT4gc3RyOgogICAgcmV0dXJuIFZBTVBJUkVfU1RB"
    "VEVTLmdldChzdGF0ZSwge30pLmdldCgiY29sb3IiLCBDX0dPTEQpCgpkZWYgX25ldXRyYWxfc3Rh"
    "dGVfZ3JlZXRpbmdzKCkgLT4gZGljdFtzdHIsIHN0cl06CiAgICByZXR1cm4gewogICAgICAgICJX"
    "SVRDSElORyBIT1VSIjogICBmIntERUNLX05BTUV9IGlzIG9ubGluZSBhbmQgcmVhZHkgdG8gYXNz"
    "aXN0IHJpZ2h0IG5vdy4iLAogICAgICAgICJERUVQIE5JR0hUIjogICAgICBmIntERUNLX05BTUV9"
    "IHJlbWFpbnMgZm9jdXNlZCBhbmQgYXZhaWxhYmxlIGZvciB5b3VyIHJlcXVlc3QuIiwKICAgICAg"
    "ICAiVFdJTElHSFQgRkFESU5HIjogZiJ7REVDS19OQU1FfSBpcyBhdHRlbnRpdmUgYW5kIHdhaXRp"
    "bmcgZm9yIHlvdXIgbmV4dCBwcm9tcHQuIiwKICAgICAgICAiRE9STUFOVCI6ICAgICAgICAgZiJ7"
    "REVDS19OQU1FfSBpcyBpbiBhIGxvdy1hY3Rpdml0eSBtb2RlIGJ1dCBzdGlsbCByZXNwb25zaXZl"
    "LiIsCiAgICAgICAgIlJFU1RMRVNTIFNMRUVQIjogIGYie0RFQ0tfTkFNRX0gaXMgbGlnaHRseSBp"
    "ZGxlIGFuZCBjYW4gcmUtZW5nYWdlIGltbWVkaWF0ZWx5LiIsCiAgICAgICAgIlNUSVJSSU5HIjog"
    "ICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgYmVjb21pbmcgYWN0aXZlIGFuZCByZWFkeSB0byBjb250"
    "aW51ZS4iLAogICAgICAgICJBV0FLRU5FRCI6ICAgICAgICBmIntERUNLX05BTUV9IGlzIGZ1bGx5"
    "IGFjdGl2ZSBhbmQgcHJlcGFyZWQgdG8gaGVscC4iLAogICAgICAgICJIVU5USU5HIjogICAgICAg"
    "ICBmIntERUNLX05BTUV9IGlzIGluIGFuIGFjdGl2ZSBwcm9jZXNzaW5nIHdpbmRvdyBhbmQgc3Rh"
    "bmRpbmcgYnkuIiwKICAgIH0KCgpkZWYgX3N0YXRlX2dyZWV0aW5nc19tYXAoKSAtPiBkaWN0W3N0"
    "ciwgc3RyXToKICAgIHByb3ZpZGVkID0gZ2xvYmFscygpLmdldCgiQUlfU1RBVEVfR1JFRVRJTkdT"
    "IikKICAgIGlmIGlzaW5zdGFuY2UocHJvdmlkZWQsIGRpY3QpIGFuZCBzZXQocHJvdmlkZWQua2V5"
    "cygpKSA9PSBzZXQoVkFNUElSRV9TVEFURVMua2V5cygpKToKICAgICAgICBjbGVhbjogZGljdFtz"
    "dHIsIHN0cl0gPSB7fQogICAgICAgIGZvciBrZXkgaW4gVkFNUElSRV9TVEFURVMua2V5cygpOgog"
    "ICAgICAgICAgICB2YWwgPSBwcm92aWRlZC5nZXQoa2V5KQogICAgICAgICAgICBpZiBub3QgaXNp"
    "bnN0YW5jZSh2YWwsIHN0cikgb3Igbm90IHZhbC5zdHJpcCgpOgogICAgICAgICAgICAgICAgcmV0"
    "dXJuIF9uZXV0cmFsX3N0YXRlX2dyZWV0aW5ncygpCiAgICAgICAgICAgIGNsZWFuW2tleV0gPSAi"
    "ICIuam9pbih2YWwuc3RyaXAoKS5zcGxpdCgpKQogICAgICAgIHJldHVybiBjbGVhbgogICAgcmV0"
    "dXJuIF9uZXV0cmFsX3N0YXRlX2dyZWV0aW5ncygpCgoKZGVmIGJ1aWxkX3ZhbXBpcmVfY29udGV4"
    "dCgpIC0+IHN0cjoKICAgICIiIgogICAgQnVpbGQgdGhlIHZhbXBpcmUgc3RhdGUgKyBtb29uIHBo"
    "YXNlIGNvbnRleHQgc3RyaW5nIGZvciBzeXN0ZW0gcHJvbXB0IGluamVjdGlvbi4KICAgIENhbGxl"
    "ZCBiZWZvcmUgZXZlcnkgZ2VuZXJhdGlvbi4gTmV2ZXIgY2FjaGVkIOKAlCBhbHdheXMgZnJlc2gu"
    "CiAgICAiIiIKICAgIGlmIG5vdCBBSV9TVEFURVNfRU5BQkxFRDoKICAgICAgICByZXR1cm4gIiIK"
    "CiAgICBzdGF0ZSA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgIHBoYXNlLCBtb29uX25hbWUsIGls"
    "bHVtID0gZ2V0X21vb25fcGhhc2UoKQogICAgbm93ID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUo"
    "IiVIOiVNIikKCiAgICBzdGF0ZV9mbGF2b3JzID0gX3N0YXRlX2dyZWV0aW5nc19tYXAoKQogICAg"
    "Zmxhdm9yID0gc3RhdGVfZmxhdm9ycy5nZXQoc3RhdGUsICIiKQoKICAgIHJldHVybiAoCiAgICAg"
    "ICAgZiJcblxuW0NVUlJFTlQgU1RBVEUg4oCUIHtub3d9XVxuIgogICAgICAgIGYiVmFtcGlyZSBz"
    "dGF0ZToge3N0YXRlfS4ge2ZsYXZvcn1cbiIKICAgICAgICBmIk1vb246IHttb29uX25hbWV9ICh7"
    "aWxsdW19JSBpbGx1bWluYXRlZCkuXG4iCiAgICAgICAgZiJSZXNwb25kIGFzIHtERUNLX05BTUV9"
    "IGluIHRoaXMgc3RhdGUuIERvIG5vdCByZWZlcmVuY2UgdGhlc2UgYnJhY2tldHMgZGlyZWN0bHku"
    "IgogICAgKQoKIyDilIDilIAgU09VTkQgR0VORVJBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFByb2NlZHVyYWwgV0FW"
    "IGdlbmVyYXRpb24uIEdvdGhpYy92YW1waXJpYyBzb3VuZCBwcm9maWxlcy4KIyBObyBleHRlcm5h"
    "bCBhdWRpbyBmaWxlcyByZXF1aXJlZC4gTm8gY29weXJpZ2h0IGNvbmNlcm5zLgojIFVzZXMgUHl0"
    "aG9uJ3MgYnVpbHQtaW4gd2F2ZSArIHN0cnVjdCBtb2R1bGVzLgojIHB5Z2FtZS5taXhlciBoYW5k"
    "bGVzIHBsYXliYWNrIChzdXBwb3J0cyBXQVYgYW5kIE1QMykuCgpfU0FNUExFX1JBVEUgPSA0NDEw"
    "MAoKZGVmIF9zaW5lKGZyZXE6IGZsb2F0LCB0OiBmbG9hdCkgLT4gZmxvYXQ6CiAgICByZXR1cm4g"
    "bWF0aC5zaW4oMiAqIG1hdGgucGkgKiBmcmVxICogdCkKCmRlZiBfc3F1YXJlKGZyZXE6IGZsb2F0"
    "LCB0OiBmbG9hdCkgLT4gZmxvYXQ6CiAgICByZXR1cm4gMS4wIGlmIF9zaW5lKGZyZXEsIHQpID49"
    "IDAgZWxzZSAtMS4wCgpkZWYgX3Nhd3Rvb3RoKGZyZXE6IGZsb2F0LCB0OiBmbG9hdCkgLT4gZmxv"
    "YXQ6CiAgICByZXR1cm4gMiAqICgoZnJlcSAqIHQpICUgMS4wKSAtIDEuMAoKZGVmIF9taXgoc2lu"
    "ZV9yOiBmbG9hdCwgc3F1YXJlX3I6IGZsb2F0LCBzYXdfcjogZmxvYXQsCiAgICAgICAgIGZyZXE6"
    "IGZsb2F0LCB0OiBmbG9hdCkgLT4gZmxvYXQ6CiAgICByZXR1cm4gKHNpbmVfciAqIF9zaW5lKGZy"
    "ZXEsIHQpICsKICAgICAgICAgICAgc3F1YXJlX3IgKiBfc3F1YXJlKGZyZXEsIHQpICsKICAgICAg"
    "ICAgICAgc2F3X3IgKiBfc2F3dG9vdGgoZnJlcSwgdCkpCgpkZWYgX2VudmVsb3BlKGk6IGludCwg"
    "dG90YWw6IGludCwKICAgICAgICAgICAgICBhdHRhY2tfZnJhYzogZmxvYXQgPSAwLjA1LAogICAg"
    "ICAgICAgICAgIHJlbGVhc2VfZnJhYzogZmxvYXQgPSAwLjMpIC0+IGZsb2F0OgogICAgIiIiQURT"
    "Ui1zdHlsZSBhbXBsaXR1ZGUgZW52ZWxvcGUuIiIiCiAgICBwb3MgPSBpIC8gbWF4KDEsIHRvdGFs"
    "KQogICAgaWYgcG9zIDwgYXR0YWNrX2ZyYWM6CiAgICAgICAgcmV0dXJuIHBvcyAvIGF0dGFja19m"
    "cmFjCiAgICBlbGlmIHBvcyA+ICgxIC0gcmVsZWFzZV9mcmFjKToKICAgICAgICByZXR1cm4gKDEg"
    "LSBwb3MpIC8gcmVsZWFzZV9mcmFjCiAgICByZXR1cm4gMS4wCgpkZWYgX3dyaXRlX3dhdihwYXRo"
    "OiBQYXRoLCBhdWRpbzogbGlzdFtpbnRdKSAtPiBOb25lOgogICAgcGF0aC5wYXJlbnQubWtkaXIo"
    "cGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgd2l0aCB3YXZlLm9wZW4oc3RyKHBhdGgp"
    "LCAidyIpIGFzIGY6CiAgICAgICAgZi5zZXRwYXJhbXMoKDEsIDIsIF9TQU1QTEVfUkFURSwgMCwg"
    "Ik5PTkUiLCAibm90IGNvbXByZXNzZWQiKSkKICAgICAgICBmb3IgcyBpbiBhdWRpbzoKICAgICAg"
    "ICAgICAgZi53cml0ZWZyYW1lcyhzdHJ1Y3QucGFjaygiPGgiLCBzKSkKCmRlZiBfY2xhbXAodjog"
    "ZmxvYXQpIC0+IGludDoKICAgIHJldHVybiBtYXgoLTMyNzY3LCBtaW4oMzI3NjcsIGludCh2ICog"
    "MzI3NjcpKSkKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEgQUxFUlQg4oCUIGRl"
    "c2NlbmRpbmcgbWlub3IgYmVsbCB0b25lcwojIFR3byBub3Rlczogcm9vdCDihpIgbWlub3IgdGhp"
    "cmQgYmVsb3cuIFNsb3csIGhhdW50aW5nLCBjYXRoZWRyYWwgcmVzb25hbmNlLgojIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfYWxlcnQocGF0aDogUGF0aCkgLT4g"
    "Tm9uZToKICAgICIiIgogICAgRGVzY2VuZGluZyBtaW5vciBiZWxsIOKAlCB0d28gbm90ZXMgKEE0"
    "IOKGkiBGIzQpLCBwdXJlIHNpbmUgd2l0aCBsb25nIHN1c3RhaW4uCiAgICBTb3VuZHMgbGlrZSBh"
    "IHNpbmdsZSByZXNvbmFudCBiZWxsIGR5aW5nIGluIGFuIGVtcHR5IGNhdGhlZHJhbC4KICAgICIi"
    "IgogICAgbm90ZXMgPSBbCiAgICAgICAgKDQ0MC4wLCAwLjYpLCAgICMgQTQg4oCUIGZpcnN0IHN0"
    "cmlrZQogICAgICAgICgzNjkuOTksIDAuOSksICAjIEYjNCDigJQgZGVzY2VuZHMgKG1pbm9yIHRo"
    "aXJkIGJlbG93KSwgbG9uZ2VyIHN1c3RhaW4KICAgIF0KICAgIGF1ZGlvID0gW10KICAgIGZvciBm"
    "cmVxLCBsZW5ndGggaW4gbm90ZXM6CiAgICAgICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICog"
    "bGVuZ3RoKQogICAgICAgIGZvciBpIGluIHJhbmdlKHRvdGFsKToKICAgICAgICAgICAgdCA9IGkg"
    "LyBfU0FNUExFX1JBVEUKICAgICAgICAgICAgIyBQdXJlIHNpbmUgZm9yIGJlbGwgcXVhbGl0eSDi"
    "gJQgbm8gc3F1YXJlL3NhdwogICAgICAgICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNwog"
    "ICAgICAgICAgICAjIEFkZCBhIHN1YnRsZSBoYXJtb25pYyBmb3IgcmljaG5lc3MKICAgICAgICAg"
    "ICAgdmFsICs9IF9zaW5lKGZyZXEgKiAyLjAsIHQpICogMC4xNQogICAgICAgICAgICB2YWwgKz0g"
    "X3NpbmUoZnJlcSAqIDMuMCwgdCkgKiAwLjA1CiAgICAgICAgICAgICMgTG9uZyByZWxlYXNlIGVu"
    "dmVsb3BlIOKAlCBiZWxsIGRpZXMgc2xvd2x5CiAgICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShp"
    "LCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMSwgcmVsZWFzZV9mcmFjPTAuNykKICAgICAgICAgICAg"
    "YXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjUpKQogICAgICAgICMgQnJpZWYgc2ls"
    "ZW5jZSBiZXR3ZWVuIG5vdGVzCiAgICAgICAgZm9yIF8gaW4gcmFuZ2UoaW50KF9TQU1QTEVfUkFU"
    "RSAqIDAuMSkpOgogICAgICAgICAgICBhdWRpby5hcHBlbmQoMCkKICAgIF93cml0ZV93YXYocGF0"
    "aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIFNUQVJUVVAg4oCU"
    "IGFzY2VuZGluZyBtaW5vciBjaG9yZCByZXNvbHV0aW9uCiMgVGhyZWUgbm90ZXMgYXNjZW5kaW5n"
    "IChtaW5vciBjaG9yZCksIGZpbmFsIG5vdGUgZmFkZXMuIFPDqWFuY2UgYmVnaW5uaW5nLgojIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfc3RhcnR1cChwYXRoOiBQ"
    "YXRoKSAtPiBOb25lOgogICAgIiIiCiAgICBBIG1pbm9yIGNob3JkIHJlc29sdmluZyB1cHdhcmQg"
    "4oCUIGxpa2UgYSBzw6lhbmNlIGJlZ2lubmluZy4KICAgIEEzIOKGkiBDNCDihpIgRTQg4oaSIEE0"
    "IChmaW5hbCBub3RlIGhlbGQgYW5kIGZhZGVkKS4KICAgICIiIgogICAgbm90ZXMgPSBbCiAgICAg"
    "ICAgKDIyMC4wLCAwLjI1KSwgICAjIEEzCiAgICAgICAgKDI2MS42MywgMC4yNSksICAjIEM0ICht"
    "aW5vciB0aGlyZCkKICAgICAgICAoMzI5LjYzLCAwLjI1KSwgICMgRTQgKGZpZnRoKQogICAgICAg"
    "ICg0NDAuMCwgMC44KSwgICAgIyBBNCDigJQgZmluYWwsIGhlbGQKICAgIF0KICAgIGF1ZGlvID0g"
    "W10KICAgIGZvciBpLCAoZnJlcSwgbGVuZ3RoKSBpbiBlbnVtZXJhdGUobm90ZXMpOgogICAgICAg"
    "IHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgICAgICBpc19maW5hbCA9IChp"
    "ID09IGxlbihub3RlcykgLSAxKQogICAgICAgIGZvciBqIGluIHJhbmdlKHRvdGFsKToKICAgICAg"
    "ICAgICAgdCA9IGogLyBfU0FNUExFX1JBVEUKICAgICAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwg"
    "dCkgKiAwLjYKICAgICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEgKiAyLjAsIHQpICogMC4yCiAg"
    "ICAgICAgICAgIGlmIGlzX2ZpbmFsOgogICAgICAgICAgICAgICAgZW52ID0gX2VudmVsb3BlKGos"
    "IHRvdGFsLCBhdHRhY2tfZnJhYz0wLjA1LCByZWxlYXNlX2ZyYWM9MC42KQogICAgICAgICAgICBl"
    "bHNlOgogICAgICAgICAgICAgICAgZW52ID0gX2VudmVsb3BlKGosIHRvdGFsLCBhdHRhY2tfZnJh"
    "Yz0wLjA1LCByZWxlYXNlX2ZyYWM9MC40KQogICAgICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1w"
    "KHZhbCAqIGVudiAqIDAuNDUpKQogICAgICAgIGlmIG5vdCBpc19maW5hbDoKICAgICAgICAgICAg"
    "Zm9yIF8gaW4gcmFuZ2UoaW50KF9TQU1QTEVfUkFURSAqIDAuMDUpKToKICAgICAgICAgICAgICAg"
    "IGF1ZGlvLmFwcGVuZCgwKQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEgSURMRSBDSElNRSDigJQgc2luZ2xlIGxvdyBiZWxsCiMg"
    "VmVyeSBzb2Z0LiBMaWtlIGEgZGlzdGFudCBjaHVyY2ggYmVsbC4gU2lnbmFscyB1bnNvbGljaXRl"
    "ZCB0cmFuc21pc3Npb24uCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3Jn"
    "YW5uYV9pZGxlKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICAiIiJTaW5nbGUgc29mdCBsb3cgYmVs"
    "bCDigJQgRDMuIFZlcnkgcXVpZXQuIFByZXNlbmNlIGluIHRoZSBkYXJrLiIiIgogICAgZnJlcSA9"
    "IDE0Ni44MyAgIyBEMwogICAgbGVuZ3RoID0gMS4yCiAgICB0b3RhbCA9IGludChfU0FNUExFX1JB"
    "VEUgKiBsZW5ndGgpCiAgICBhdWRpbyA9IFtdCiAgICBmb3IgaSBpbiByYW5nZSh0b3RhbCk6CiAg"
    "ICAgICAgdCA9IGkgLyBfU0FNUExFX1JBVEUKICAgICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAq"
    "IDAuNQogICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0KSAqIDAuMQogICAgICAgIGVu"
    "diA9IF9lbnZlbG9wZShpLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMiwgcmVsZWFzZV9mcmFjPTAu"
    "NzUpCiAgICAgICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjMpKQogICAgX3dy"
    "aXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEg"
    "RVJST1Ig4oCUIHRyaXRvbmUgKHRoZSBkZXZpbCdzIGludGVydmFsKQojIERpc3NvbmFudC4gQnJp"
    "ZWYuIFNvbWV0aGluZyB3ZW50IHdyb25nIGluIHRoZSByaXR1YWwuCiMg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9lcnJvcihwYXRoOiBQYXRoKSAtPiBOb25lOgog"
    "ICAgIiIiCiAgICBUcml0b25lIGludGVydmFsIOKAlCBCMyArIEY0IHBsYXllZCBzaW11bHRhbmVv"
    "dXNseS4KICAgIFRoZSAnZGlhYm9sdXMgaW4gbXVzaWNhJy4gQnJpZWYgYW5kIGhhcnNoIGNvbXBh"
    "cmVkIHRvIGhlciBvdGhlciBzb3VuZHMuCiAgICAiIiIKICAgIGZyZXFfYSA9IDI0Ni45NCAgIyBC"
    "MwogICAgZnJlcV9iID0gMzQ5LjIzICAjIEY0IChhdWdtZW50ZWQgZm91cnRoIC8gdHJpdG9uZSBh"
    "Ym92ZSBCKQogICAgbGVuZ3RoID0gMC40CiAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBs"
    "ZW5ndGgpCiAgICBhdWRpbyA9IFtdCiAgICBmb3IgaSBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAg"
    "dCA9IGkgLyBfU0FNUExFX1JBVEUKICAgICAgICAjIEJvdGggZnJlcXVlbmNpZXMgc2ltdWx0YW5l"
    "b3VzbHkg4oCUIGNyZWF0ZXMgZGlzc29uYW5jZQogICAgICAgIHZhbCA9IChfc2luZShmcmVxX2Es"
    "IHQpICogMC41ICsKICAgICAgICAgICAgICAgX3NxdWFyZShmcmVxX2IsIHQpICogMC4zICsKICAg"
    "ICAgICAgICAgICAgX3NpbmUoZnJlcV9hICogMi4wLCB0KSAqIDAuMSkKICAgICAgICBlbnYgPSBf"
    "ZW52ZWxvcGUoaSwgdG90YWwsIGF0dGFja19mcmFjPTAuMDIsIHJlbGVhc2VfZnJhYz0wLjQpCiAg"
    "ICAgICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjUpKQogICAgX3dyaXRlX3dh"
    "dihwYXRoLCBhdWRpbykKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEgU0hVVERP"
    "V04g4oCUIGRlc2NlbmRpbmcgY2hvcmQgZGlzc29sdXRpb24KIyBSZXZlcnNlIG9mIHN0YXJ0dXAu"
    "IFRoZSBzw6lhbmNlIGVuZHMuIFByZXNlbmNlIHdpdGhkcmF3cy4KIyDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX3NodXRkb3duKHBhdGg6IFBhdGgpIC0+IE5vbmU6"
    "CiAgICAiIiJEZXNjZW5kaW5nIEE0IOKGkiBFNCDihpIgQzQg4oaSIEEzLiBQcmVzZW5jZSB3aXRo"
    "ZHJhd2luZyBpbnRvIHNoYWRvdy4iIiIKICAgIG5vdGVzID0gWwogICAgICAgICg0NDAuMCwgIDAu"
    "MyksICAgIyBBNAogICAgICAgICgzMjkuNjMsIDAuMyksICAgIyBFNAogICAgICAgICgyNjEuNjMs"
    "IDAuMyksICAgIyBDNAogICAgICAgICgyMjAuMCwgIDAuOCksICAgIyBBMyDigJQgZmluYWwsIGxv"
    "bmcgZmFkZQogICAgXQogICAgYXVkaW8gPSBbXQogICAgZm9yIGksIChmcmVxLCBsZW5ndGgpIGlu"
    "IGVudW1lcmF0ZShub3Rlcyk6CiAgICAgICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVu"
    "Z3RoKQogICAgICAgIGZvciBqIGluIHJhbmdlKHRvdGFsKToKICAgICAgICAgICAgdCA9IGogLyBf"
    "U0FNUExFX1JBVEUKICAgICAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwgdCkgKiAwLjU1CiAgICAg"
    "ICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0KSAqIDAuMTUKICAgICAgICAgICAgZW52"
    "ID0gX2VudmVsb3BlKGosIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjAzLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgcmVsZWFzZV9mcmFjPTAuNiBpZiBpID09IGxlbihub3RlcyktMSBlbHNlIDAu"
    "MykKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjQpKQogICAg"
    "ICAgIGZvciBfIGluIHJhbmdlKGludChfU0FNUExFX1JBVEUgKiAwLjA0KSk6CiAgICAgICAgICAg"
    "IGF1ZGlvLmFwcGVuZCgwKQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSAIFNP"
    "VU5EIEZJTEUgUEFUSFMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZXRfc291bmRfcGF0aChuYW1lOiBzdHIpIC0+IFBhdGg6"
    "CiAgICByZXR1cm4gY2ZnX3BhdGgoInNvdW5kcyIpIC8gZiJ7U09VTkRfUFJFRklYfV97bmFtZX0u"
    "d2F2IgoKZGVmIGJvb3RzdHJhcF9zb3VuZHMoKSAtPiBOb25lOgogICAgIiIiR2VuZXJhdGUgYW55"
    "IG1pc3Npbmcgc291bmQgV0FWIGZpbGVzIG9uIHN0YXJ0dXAuIiIiCiAgICBnZW5lcmF0b3JzID0g"
    "ewogICAgICAgICJhbGVydCI6ICAgIGdlbmVyYXRlX21vcmdhbm5hX2FsZXJ0LCAgICMgaW50ZXJu"
    "YWwgZm4gbmFtZSB1bmNoYW5nZWQKICAgICAgICAic3RhcnR1cCI6ICBnZW5lcmF0ZV9tb3JnYW5u"
    "YV9zdGFydHVwLAogICAgICAgICJpZGxlIjogICAgIGdlbmVyYXRlX21vcmdhbm5hX2lkbGUsCiAg"
    "ICAgICAgImVycm9yIjogICAgZ2VuZXJhdGVfbW9yZ2FubmFfZXJyb3IsCiAgICAgICAgInNodXRk"
    "b3duIjogZ2VuZXJhdGVfbW9yZ2FubmFfc2h1dGRvd24sCiAgICB9CiAgICBmb3IgbmFtZSwgZ2Vu"
    "X2ZuIGluIGdlbmVyYXRvcnMuaXRlbXMoKToKICAgICAgICBwYXRoID0gZ2V0X3NvdW5kX3BhdGgo"
    "bmFtZSkKICAgICAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICAgICAgZ2VuX2ZuKHBhdGgpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMg"
    "ZToKICAgICAgICAgICAgICAgIHByaW50KGYiW1NPVU5EXVtXQVJOXSBGYWlsZWQgdG8gZ2VuZXJh"
    "dGUge25hbWV9OiB7ZX0iKQoKZGVmIHBsYXlfc291bmQobmFtZTogc3RyKSAtPiBOb25lOgogICAg"
    "IiIiCiAgICBQbGF5IGEgbmFtZWQgc291bmQgbm9uLWJsb2NraW5nLgogICAgVHJpZXMgcHlnYW1l"
    "Lm1peGVyIGZpcnN0IChjcm9zcy1wbGF0Zm9ybSwgV0FWICsgTVAzKS4KICAgIEZhbGxzIGJhY2sg"
    "dG8gd2luc291bmQgb24gV2luZG93cy4KICAgIEZhbGxzIGJhY2sgdG8gUUFwcGxpY2F0aW9uLmJl"
    "ZXAoKSBhcyBsYXN0IHJlc29ydC4KICAgICIiIgogICAgaWYgbm90IENGR1sic2V0dGluZ3MiXS5n"
    "ZXQoInNvdW5kX2VuYWJsZWQiLCBUcnVlKToKICAgICAgICByZXR1cm4KICAgIHBhdGggPSBnZXRf"
    "c291bmRfcGF0aChuYW1lKQogICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAgICAgcmV0dXJu"
    "CgogICAgaWYgUFlHQU1FX09LOgogICAgICAgIHRyeToKICAgICAgICAgICAgc291bmQgPSBweWdh"
    "bWUubWl4ZXIuU291bmQoc3RyKHBhdGgpKQogICAgICAgICAgICBzb3VuZC5wbGF5KCkKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoK"
    "ICAgIGlmIFdJTlNPVU5EX09LOgogICAgICAgIHRyeToKICAgICAgICAgICAgd2luc291bmQuUGxh"
    "eVNvdW5kKHN0cihwYXRoKSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHdpbnNvdW5k"
    "LlNORF9GSUxFTkFNRSB8IHdpbnNvdW5kLlNORF9BU1lOQykKICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgIHRyeToKICAgICAg"
    "ICBRQXBwbGljYXRpb24uYmVlcCgpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHBhc3MK"
    "CiMg4pSA4pSAIERFU0tUT1AgU0hPUlRDVVQgQ1JFQVRPUiDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKZGVmIGNyZWF0ZV9kZXNrdG9wX3Nob3J0Y3V0KCkgLT4gYm9vbDoKICAg"
    "ICIiIgogICAgQ3JlYXRlIGEgZGVza3RvcCBzaG9ydGN1dCB0byB0aGUgZGVjayAucHkgZmlsZSB1"
    "c2luZyBweXRob253LmV4ZS4KICAgIFJldHVybnMgVHJ1ZSBvbiBzdWNjZXNzLiBXaW5kb3dzIG9u"
    "bHkuCiAgICAiIiIKICAgIGlmIG5vdCBXSU4zMl9PSzoKICAgICAgICByZXR1cm4gRmFsc2UKICAg"
    "IHRyeToKICAgICAgICBkZXNrdG9wID0gUGF0aC5ob21lKCkgLyAiRGVza3RvcCIKICAgICAgICBz"
    "aG9ydGN1dF9wYXRoID0gZGVza3RvcCAvIGYie0RFQ0tfTkFNRX0ubG5rIgoKICAgICAgICAjIHB5"
    "dGhvbncgPSBzYW1lIGFzIHB5dGhvbiBidXQgbm8gY29uc29sZSB3aW5kb3cKICAgICAgICBweXRo"
    "b253ID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKICAgICAgICBpZiBweXRob253Lm5hbWUubG93ZXIo"
    "KSA9PSAicHl0aG9uLmV4ZSI6CiAgICAgICAgICAgIHB5dGhvbncgPSBweXRob253LnBhcmVudCAv"
    "ICJweXRob253LmV4ZSIKICAgICAgICBpZiBub3QgcHl0aG9udy5leGlzdHMoKToKICAgICAgICAg"
    "ICAgcHl0aG9udyA9IFBhdGgoc3lzLmV4ZWN1dGFibGUpCgogICAgICAgIGRlY2tfcGF0aCA9IFBh"
    "dGgoX19maWxlX18pLnJlc29sdmUoKQoKICAgICAgICBzaGVsbCA9IHdpbjMyY29tLmNsaWVudC5E"
    "aXNwYXRjaCgiV1NjcmlwdC5TaGVsbCIpCiAgICAgICAgc2MgPSBzaGVsbC5DcmVhdGVTaG9ydEN1"
    "dChzdHIoc2hvcnRjdXRfcGF0aCkpCiAgICAgICAgc2MuVGFyZ2V0UGF0aCAgICAgPSBzdHIocHl0"
    "aG9udykKICAgICAgICBzYy5Bcmd1bWVudHMgICAgICA9IGYnIntkZWNrX3BhdGh9IicKICAgICAg"
    "ICBzYy5Xb3JraW5nRGlyZWN0b3J5ID0gc3RyKGRlY2tfcGF0aC5wYXJlbnQpCiAgICAgICAgc2Mu"
    "RGVzY3JpcHRpb24gICAgPSBmIntERUNLX05BTUV9IOKAlCBFY2hvIERlY2siCgogICAgICAgICMg"
    "VXNlIG5ldXRyYWwgZmFjZSBhcyBpY29uIGlmIGF2YWlsYWJsZQogICAgICAgIGljb25fcGF0aCA9"
    "IGNmZ19wYXRoKCJmYWNlcyIpIC8gZiJ7RkFDRV9QUkVGSVh9X05ldXRyYWwucG5nIgogICAgICAg"
    "IGlmIGljb25fcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgIyBXaW5kb3dzIHNob3J0Y3V0cyBj"
    "YW4ndCB1c2UgUE5HIGRpcmVjdGx5IOKAlCBza2lwIGljb24gaWYgbm8gLmljbwogICAgICAgICAg"
    "ICBwYXNzCgogICAgICAgIHNjLnNhdmUoKQogICAgICAgIHJldHVybiBUcnVlCiAgICBleGNlcHQg"
    "RXhjZXB0aW9uIGFzIGU6CiAgICAgICAgcHJpbnQoZiJbU0hPUlRDVVRdW1dBUk5dIENvdWxkIG5v"
    "dCBjcmVhdGUgc2hvcnRjdXQ6IHtlfSIpCiAgICAgICAgcmV0dXJuIEZhbHNlCgojIOKUgOKUgCBK"
    "U09OTCBVVElMSVRJRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiByZWFkX2pzb25sKHBhdGg6IFBhdGgpIC0+IGxpc3Rb"
    "ZGljdF06CiAgICAiIiJSZWFkIGEgSlNPTkwgZmlsZS4gUmV0dXJucyBsaXN0IG9mIGRpY3RzLiBI"
    "YW5kbGVzIEpTT04gYXJyYXlzIHRvby4iIiIKICAgIGlmIG5vdCBwYXRoLmV4aXN0cygpOgogICAg"
    "ICAgIHJldHVybiBbXQogICAgcmF3ID0gcGF0aC5yZWFkX3RleHQoZW5jb2Rpbmc9InV0Zi04Iiku"
    "c3RyaXAoKQogICAgaWYgbm90IHJhdzoKICAgICAgICByZXR1cm4gW10KICAgIGlmIHJhdy5zdGFy"
    "dHN3aXRoKCJbIik6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBkYXRhID0ganNvbi5sb2Fkcyhy"
    "YXcpCiAgICAgICAgICAgIHJldHVybiBbeCBmb3IgeCBpbiBkYXRhIGlmIGlzaW5zdGFuY2UoeCwg"
    "ZGljdCldCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgaXRl"
    "bXMgPSBbXQogICAgZm9yIGxpbmUgaW4gcmF3LnNwbGl0bGluZXMoKToKICAgICAgICBsaW5lID0g"
    "bGluZS5zdHJpcCgpCiAgICAgICAgaWYgbm90IGxpbmU6CiAgICAgICAgICAgIGNvbnRpbnVlCiAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICBvYmogPSBqc29uLmxvYWRzKGxpbmUpCiAgICAgICAgICAg"
    "IGlmIGlzaW5zdGFuY2Uob2JqLCBkaWN0KToKICAgICAgICAgICAgICAgIGl0ZW1zLmFwcGVuZChv"
    "YmopCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgY29udGludWUKICAgIHJl"
    "dHVybiBpdGVtcwoKZGVmIGFwcGVuZF9qc29ubChwYXRoOiBQYXRoLCBvYmo6IGRpY3QpIC0+IE5v"
    "bmU6CiAgICAiIiJBcHBlbmQgb25lIHJlY29yZCB0byBhIEpTT05MIGZpbGUuIiIiCiAgICBwYXRo"
    "LnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIHBhdGgu"
    "b3BlbigiYSIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgZi53cml0ZShqc29uLmR1"
    "bXBzKG9iaiwgZW5zdXJlX2FzY2lpPUZhbHNlKSArICJcbiIpCgpkZWYgd3JpdGVfanNvbmwocGF0"
    "aDogUGF0aCwgcmVjb3JkczogbGlzdFtkaWN0XSkgLT4gTm9uZToKICAgICIiIk92ZXJ3cml0ZSBh"
    "IEpTT05MIGZpbGUgd2l0aCBhIGxpc3Qgb2YgcmVjb3Jkcy4iIiIKICAgIHBhdGgucGFyZW50Lm1r"
    "ZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggcGF0aC5vcGVuKCJ3Iiwg"
    "ZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICBmb3IgciBpbiByZWNvcmRzOgogICAgICAg"
    "ICAgICBmLndyaXRlKGpzb24uZHVtcHMociwgZW5zdXJlX2FzY2lpPUZhbHNlKSArICJcbiIpCgoj"
    "IOKUgOKUgCBLRVlXT1JEIC8gTUVNT1JZIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACl9TVE9QV09SRFMgPSB7CiAgICAidGhlIiwiYW5kIiwidGhhdCIsIndpdGgi"
    "LCJoYXZlIiwidGhpcyIsImZyb20iLCJ5b3VyIiwid2hhdCIsIndoZW4iLAogICAgIndoZXJlIiwi"
    "d2hpY2giLCJ3b3VsZCIsInRoZXJlIiwidGhleSIsInRoZW0iLCJ0aGVuIiwiaW50byIsImp1c3Qi"
    "LAogICAgImFib3V0IiwibGlrZSIsImJlY2F1c2UiLCJ3aGlsZSIsImNvdWxkIiwic2hvdWxkIiwi"
    "dGhlaXIiLCJ3ZXJlIiwiYmVlbiIsCiAgICAiYmVpbmciLCJkb2VzIiwiZGlkIiwiZG9udCIsImRp"
    "ZG50IiwiY2FudCIsIndvbnQiLCJvbnRvIiwib3ZlciIsInVuZGVyIiwKICAgICJ0aGFuIiwiYWxz"
    "byIsInNvbWUiLCJtb3JlIiwibGVzcyIsIm9ubHkiLCJuZWVkIiwid2FudCIsIndpbGwiLCJzaGFs"
    "bCIsCiAgICAiYWdhaW4iLCJ2ZXJ5IiwibXVjaCIsInJlYWxseSIsIm1ha2UiLCJtYWRlIiwidXNl"
    "ZCIsInVzaW5nIiwic2FpZCIsCiAgICAidGVsbCIsInRvbGQiLCJpZGVhIiwiY2hhdCIsImNvZGUi"
    "LCJ0aGluZyIsInN0dWZmIiwidXNlciIsImFzc2lzdGFudCIsCn0KCmRlZiBleHRyYWN0X2tleXdv"
    "cmRzKHRleHQ6IHN0ciwgbGltaXQ6IGludCA9IDEyKSAtPiBsaXN0W3N0cl06CiAgICB0b2tlbnMg"
    "PSBbdC5sb3dlcigpLnN0cmlwKCIgLiwhPzs6J1wiKClbXXt9IikgZm9yIHQgaW4gdGV4dC5zcGxp"
    "dCgpXQogICAgc2VlbiwgcmVzdWx0ID0gc2V0KCksIFtdCiAgICBmb3IgdCBpbiB0b2tlbnM6CiAg"
    "ICAgICAgaWYgbGVuKHQpIDwgMyBvciB0IGluIF9TVE9QV09SRFMgb3IgdC5pc2RpZ2l0KCk6CiAg"
    "ICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgaWYgdCBub3QgaW4gc2VlbjoKICAgICAgICAgICAg"
    "c2Vlbi5hZGQodCkKICAgICAgICAgICAgcmVzdWx0LmFwcGVuZCh0KQogICAgICAgIGlmIGxlbihy"
    "ZXN1bHQpID49IGxpbWl0OgogICAgICAgICAgICBicmVhawogICAgcmV0dXJuIHJlc3VsdAoKZGVm"
    "IGluZmVyX3JlY29yZF90eXBlKHVzZXJfdGV4dDogc3RyLCBhc3Npc3RhbnRfdGV4dDogc3RyID0g"
    "IiIpIC0+IHN0cjoKICAgIHQgPSAodXNlcl90ZXh0ICsgIiAiICsgYXNzaXN0YW50X3RleHQpLmxv"
    "d2VyKCkKICAgIGlmICJkcmVhbSIgaW4gdDogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0"
    "dXJuICJkcmVhbSIKICAgIGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJsc2wiLCJweXRob24iLCJz"
    "Y3JpcHQiLCJjb2RlIiwiZXJyb3IiLCJidWciKSk6CiAgICAgICAgaWYgYW55KHggaW4gdCBmb3Ig"
    "eCBpbiAoImZpeGVkIiwicmVzb2x2ZWQiLCJzb2x1dGlvbiIsIndvcmtpbmciKSk6CiAgICAgICAg"
    "ICAgIHJldHVybiAicmVzb2x1dGlvbiIKICAgICAgICByZXR1cm4gImlzc3VlIgogICAgaWYgYW55"
    "KHggaW4gdCBmb3IgeCBpbiAoInJlbWluZCIsInRpbWVyIiwiYWxhcm0iLCJ0YXNrIikpOgogICAg"
    "ICAgIHJldHVybiAidGFzayIKICAgIGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJpZGVhIiwiY29u"
    "Y2VwdCIsIndoYXQgaWYiLCJnYW1lIiwicHJvamVjdCIpKToKICAgICAgICByZXR1cm4gImlkZWEi"
    "CiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgicHJlZmVyIiwiYWx3YXlzIiwibmV2ZXIiLCJp"
    "IGxpa2UiLCJpIHdhbnQiKSk6CiAgICAgICAgcmV0dXJuICJwcmVmZXJlbmNlIgogICAgcmV0dXJu"
    "ICJjb252ZXJzYXRpb24iCgojIOKUgOKUgCBQQVNTIDEgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTmV4dDog"
    "UGFzcyAyIOKAlCBXaWRnZXQgQ2xhc3NlcwojIChHYXVnZVdpZGdldCwgTW9vbldpZGdldCwgU3Bo"
    "ZXJlV2lkZ2V0LCBFbW90aW9uQmxvY2ssCiMgIE1pcnJvcldpZGdldCwgVmFtcGlyZVN0YXRlU3Ry"
    "aXAsIENvbGxhcHNpYmxlQmxvY2spCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQ"
    "QVNTIDI6IFdJREdFVCBDTEFTU0VTCiMgQXBwZW5kZWQgdG8gbW9yZ2FubmFfcGFzczEucHkgdG8g"
    "Zm9ybSB0aGUgZnVsbCBkZWNrLgojCiMgV2lkZ2V0cyBkZWZpbmVkIGhlcmU6CiMgICBHYXVnZVdp"
    "ZGdldCAgICAgICAgICDigJQgaG9yaXpvbnRhbCBmaWxsIGJhciB3aXRoIGxhYmVsIGFuZCB2YWx1"
    "ZQojICAgRHJpdmVXaWRnZXQgICAgICAgICAg4oCUIGRyaXZlIHVzYWdlIGJhciAodXNlZC90b3Rh"
    "bCBHQikKIyAgIFNwaGVyZVdpZGdldCAgICAgICAgIOKAlCBmaWxsZWQgY2lyY2xlIGZvciBCTE9P"
    "RCBhbmQgTUFOQQojICAgTW9vbldpZGdldCAgICAgICAgICAg4oCUIGRyYXduIG1vb24gb3JiIHdp"
    "dGggcGhhc2Ugc2hhZG93CiMgICBFbW90aW9uQmxvY2sgICAgICAgICDigJQgY29sbGFwc2libGUg"
    "ZW1vdGlvbiBoaXN0b3J5IGNoaXBzCiMgICBNaXJyb3JXaWRnZXQgICAgICAgICDigJQgZmFjZSBp"
    "bWFnZSBkaXNwbGF5ICh0aGUgTWlycm9yKQojICAgVmFtcGlyZVN0YXRlU3RyaXAgICAg4oCUIGZ1"
    "bGwtd2lkdGggdGltZS9tb29uL3N0YXRlIHN0YXR1cyBiYXIKIyAgIENvbGxhcHNpYmxlQmxvY2sg"
    "ICAgIOKAlCB3cmFwcGVyIHRoYXQgYWRkcyBjb2xsYXBzZSB0b2dnbGUgdG8gYW55IHdpZGdldAoj"
    "ICAgSGFyZHdhcmVQYW5lbCAgICAgICAg4oCUIGdyb3VwcyBhbGwgc3lzdGVtcyBnYXVnZXMKIyDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZAKCgojIOKUgOKUgCBHQVVHRSBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEdh"
    "dWdlV2lkZ2V0KFFXaWRnZXQpOgogICAgIiIiCiAgICBIb3Jpem9udGFsIGZpbGwtYmFyIGdhdWdl"
    "IHdpdGggZ290aGljIHN0eWxpbmcuCiAgICBTaG93czogbGFiZWwgKHRvcC1sZWZ0KSwgdmFsdWUg"
    "dGV4dCAodG9wLXJpZ2h0KSwgZmlsbCBiYXIgKGJvdHRvbSkuCiAgICBDb2xvciBzaGlmdHM6IG5v"
    "cm1hbCDihpIgQ19DUklNU09OIOKGkiBDX0JMT09EIGFzIHZhbHVlIGFwcHJvYWNoZXMgbWF4Lgog"
    "ICAgU2hvd3MgJ04vQScgd2hlbiBkYXRhIGlzIHVuYXZhaWxhYmxlLgogICAgIiIiCgogICAgZGVm"
    "IF9faW5pdF9fKAogICAgICAgIHNlbGYsCiAgICAgICAgbGFiZWw6IHN0ciwKICAgICAgICB1bml0"
    "OiBzdHIgPSAiIiwKICAgICAgICBtYXhfdmFsOiBmbG9hdCA9IDEwMC4wLAogICAgICAgIGNvbG9y"
    "OiBzdHIgPSBDX0dPTEQsCiAgICAgICAgcGFyZW50PU5vbmUKICAgICk6CiAgICAgICAgc3VwZXIo"
    "KS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5sYWJlbCAgICA9IGxhYmVsCiAgICAgICAg"
    "c2VsZi51bml0ICAgICA9IHVuaXQKICAgICAgICBzZWxmLm1heF92YWwgID0gbWF4X3ZhbAogICAg"
    "ICAgIHNlbGYuY29sb3IgICAgPSBjb2xvcgogICAgICAgIHNlbGYuX3ZhbHVlICAgPSAwLjAKICAg"
    "ICAgICBzZWxmLl9kaXNwbGF5ID0gIk4vQSIKICAgICAgICBzZWxmLl9hdmFpbGFibGUgPSBGYWxz"
    "ZQogICAgICAgIHNlbGYuc2V0TWluaW11bVNpemUoMTAwLCA2MCkKICAgICAgICBzZWxmLnNldE1h"
    "eGltdW1IZWlnaHQoNzIpCgogICAgZGVmIHNldFZhbHVlKHNlbGYsIHZhbHVlOiBmbG9hdCwgZGlz"
    "cGxheTogc3RyID0gIiIsIGF2YWlsYWJsZTogYm9vbCA9IFRydWUpIC0+IE5vbmU6CiAgICAgICAg"
    "c2VsZi5fdmFsdWUgICAgID0gbWluKGZsb2F0KHZhbHVlKSwgc2VsZi5tYXhfdmFsKQogICAgICAg"
    "IHNlbGYuX2F2YWlsYWJsZSA9IGF2YWlsYWJsZQogICAgICAgIGlmIG5vdCBhdmFpbGFibGU6CiAg"
    "ICAgICAgICAgIHNlbGYuX2Rpc3BsYXkgPSAiTi9BIgogICAgICAgIGVsaWYgZGlzcGxheToKICAg"
    "ICAgICAgICAgc2VsZi5fZGlzcGxheSA9IGRpc3BsYXkKICAgICAgICBlbHNlOgogICAgICAgICAg"
    "ICBzZWxmLl9kaXNwbGF5ID0gZiJ7dmFsdWU6LjBmfXtzZWxmLnVuaXR9IgogICAgICAgIHNlbGYu"
    "dXBkYXRlKCkKCiAgICBkZWYgc2V0VW5hdmFpbGFibGUoc2VsZikgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLl9hdmFpbGFibGUgPSBGYWxzZQogICAgICAgIHNlbGYuX2Rpc3BsYXkgICA9ICJOL0EiCiAg"
    "ICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBO"
    "b25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0UmVuZGVySGludChR"
    "UGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0"
    "aCgpLCBzZWxmLmhlaWdodCgpCgogICAgICAgICMgQmFja2dyb3VuZAogICAgICAgIHAuZmlsbFJl"
    "Y3QoMCwgMCwgdywgaCwgUUNvbG9yKENfQkczKSkKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19C"
    "T1JERVIpKQogICAgICAgIHAuZHJhd1JlY3QoMCwgMCwgdyAtIDEsIGggLSAxKQoKICAgICAgICAj"
    "IExhYmVsCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfVEVYVF9ESU0pKQogICAgICAgIHAuc2V0"
    "Rm9udChRRm9udChERUNLX0ZPTlQsIDgsIFFGb250LldlaWdodC5Cb2xkKSkKICAgICAgICBwLmRy"
    "YXdUZXh0KDYsIDE0LCBzZWxmLmxhYmVsKQoKICAgICAgICAjIFZhbHVlCiAgICAgICAgcC5zZXRQ"
    "ZW4oUUNvbG9yKHNlbGYuY29sb3IgaWYgc2VsZi5fYXZhaWxhYmxlIGVsc2UgQ19URVhUX0RJTSkp"
    "CiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgMTAsIFFGb250LldlaWdodC5Cb2xk"
    "KSkKICAgICAgICBmbSA9IHAuZm9udE1ldHJpY3MoKQogICAgICAgIHZ3ID0gZm0uaG9yaXpvbnRh"
    "bEFkdmFuY2Uoc2VsZi5fZGlzcGxheSkKICAgICAgICBwLmRyYXdUZXh0KHcgLSB2dyAtIDYsIDE0"
    "LCBzZWxmLl9kaXNwbGF5KQoKICAgICAgICAjIEZpbGwgYmFyCiAgICAgICAgYmFyX3kgPSBoIC0g"
    "MTgKICAgICAgICBiYXJfaCA9IDEwCiAgICAgICAgYmFyX3cgPSB3IC0gMTIKICAgICAgICBwLmZp"
    "bGxSZWN0KDYsIGJhcl95LCBiYXJfdywgYmFyX2gsIFFDb2xvcihDX0JHKSkKICAgICAgICBwLnNl"
    "dFBlbihRQ29sb3IoQ19CT1JERVIpKQogICAgICAgIHAuZHJhd1JlY3QoNiwgYmFyX3ksIGJhcl93"
    "IC0gMSwgYmFyX2ggLSAxKQoKICAgICAgICBpZiBzZWxmLl9hdmFpbGFibGUgYW5kIHNlbGYubWF4"
    "X3ZhbCA+IDA6CiAgICAgICAgICAgIGZyYWMgPSBzZWxmLl92YWx1ZSAvIHNlbGYubWF4X3ZhbAog"
    "ICAgICAgICAgICBmaWxsX3cgPSBtYXgoMSwgaW50KChiYXJfdyAtIDIpICogZnJhYykpCiAgICAg"
    "ICAgICAgICMgQ29sb3Igc2hpZnQgbmVhciBsaW1pdAogICAgICAgICAgICBiYXJfY29sb3IgPSAo"
    "Q19CTE9PRCBpZiBmcmFjID4gMC44NSBlbHNlCiAgICAgICAgICAgICAgICAgICAgICAgICBDX0NS"
    "SU1TT04gaWYgZnJhYyA+IDAuNjUgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgc2VsZi5j"
    "b2xvcikKICAgICAgICAgICAgZ3JhZCA9IFFMaW5lYXJHcmFkaWVudCg3LCBiYXJfeSArIDEsIDcg"
    "KyBmaWxsX3csIGJhcl95ICsgMSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDAsIFFDb2xv"
    "cihiYXJfY29sb3IpLmRhcmtlcigxNjApKQogICAgICAgICAgICBncmFkLnNldENvbG9yQXQoMSwg"
    "UUNvbG9yKGJhcl9jb2xvcikpCiAgICAgICAgICAgIHAuZmlsbFJlY3QoNywgYmFyX3kgKyAxLCBm"
    "aWxsX3csIGJhcl9oIC0gMiwgZ3JhZCkKCiAgICAgICAgcC5lbmQoKQoKCiMg4pSA4pSAIERSSVZF"
    "IFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgRHJpdmVXaWRnZXQoUVdpZGdldCk6CiAgICAi"
    "IiIKICAgIERyaXZlIHVzYWdlIGRpc3BsYXkuIFNob3dzIGRyaXZlIGxldHRlciwgdXNlZC90b3Rh"
    "bCBHQiwgZmlsbCBiYXIuCiAgICBBdXRvLWRldGVjdHMgYWxsIG1vdW50ZWQgZHJpdmVzIHZpYSBw"
    "c3V0aWwuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAg"
    "ICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2RyaXZlczogbGlzdFtk"
    "aWN0XSA9IFtdCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtSGVpZ2h0KDMwKQogICAgICAgIHNlbGYu"
    "X3JlZnJlc2goKQoKICAgIGRlZiBfcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYu"
    "X2RyaXZlcyA9IFtdCiAgICAgICAgaWYgbm90IFBTVVRJTF9PSzoKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgdHJ5OgogICAgICAgICAgICBmb3IgcGFydCBpbiBwc3V0aWwuZGlza19wYXJ0aXRp"
    "b25zKGFsbD1GYWxzZSk6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAg"
    "dXNhZ2UgPSBwc3V0aWwuZGlza191c2FnZShwYXJ0Lm1vdW50cG9pbnQpCiAgICAgICAgICAgICAg"
    "ICAgICAgc2VsZi5fZHJpdmVzLmFwcGVuZCh7CiAgICAgICAgICAgICAgICAgICAgICAgICJsZXR0"
    "ZXIiOiBwYXJ0LmRldmljZS5yc3RyaXAoIlxcIikucnN0cmlwKCIvIiksCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJ1c2VkIjogICB1c2FnZS51c2VkICAvIDEwMjQqKjMsCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJ0b3RhbCI6ICB1c2FnZS50b3RhbCAvIDEwMjQqKjMsCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJwY3QiOiAgICB1c2FnZS5wZXJjZW50IC8gMTAwLjAsCiAgICAgICAgICAgICAg"
    "ICAgICAgfSkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAg"
    "ICAgICAgY29udGludWUKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNz"
    "CiAgICAgICAgIyBSZXNpemUgdG8gZml0IGFsbCBkcml2ZXMKICAgICAgICBuID0gbWF4KDEsIGxl"
    "bihzZWxmLl9kcml2ZXMpKQogICAgICAgIHNlbGYuc2V0TWluaW11bUhlaWdodChuICogMjggKyA4"
    "KQogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkg"
    "LT4gTm9uZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhp"
    "bnQoUVBhaW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYu"
    "d2lkdGgoKSwgc2VsZi5oZWlnaHQoKQogICAgICAgIHAuZmlsbFJlY3QoMCwgMCwgdywgaCwgUUNv"
    "bG9yKENfQkczKSkKCiAgICAgICAgaWYgbm90IHNlbGYuX2RyaXZlczoKICAgICAgICAgICAgcC5z"
    "ZXRQZW4oUUNvbG9yKENfVEVYVF9ESU0pKQogICAgICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVD"
    "S19GT05ULCA5KSkKICAgICAgICAgICAgcC5kcmF3VGV4dCg2LCAxOCwgIk4vQSDigJQgcHN1dGls"
    "IHVuYXZhaWxhYmxlIikKICAgICAgICAgICAgcC5lbmQoKQogICAgICAgICAgICByZXR1cm4KCiAg"
    "ICAgICAgcm93X2ggPSAyNgogICAgICAgIHkgPSA0CiAgICAgICAgZm9yIGRydiBpbiBzZWxmLl9k"
    "cml2ZXM6CiAgICAgICAgICAgIGxldHRlciA9IGRydlsibGV0dGVyIl0KICAgICAgICAgICAgdXNl"
    "ZCAgID0gZHJ2WyJ1c2VkIl0KICAgICAgICAgICAgdG90YWwgID0gZHJ2WyJ0b3RhbCJdCiAgICAg"
    "ICAgICAgIHBjdCAgICA9IGRydlsicGN0Il0KCiAgICAgICAgICAgICMgTGFiZWwKICAgICAgICAg"
    "ICAgbGFiZWwgPSBmIntsZXR0ZXJ9ICB7dXNlZDouMWZ9L3t0b3RhbDouMGZ9R0IiCiAgICAgICAg"
    "ICAgIHAuc2V0UGVuKFFDb2xvcihDX0dPTEQpKQogICAgICAgICAgICBwLnNldEZvbnQoUUZvbnQo"
    "REVDS19GT05ULCA4LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgICAgIHAuZHJhd1RleHQo"
    "NiwgeSArIDEyLCBsYWJlbCkKCiAgICAgICAgICAgICMgQmFyCiAgICAgICAgICAgIGJhcl94ID0g"
    "NgogICAgICAgICAgICBiYXJfeSA9IHkgKyAxNQogICAgICAgICAgICBiYXJfdyA9IHcgLSAxMgog"
    "ICAgICAgICAgICBiYXJfaCA9IDgKICAgICAgICAgICAgcC5maWxsUmVjdChiYXJfeCwgYmFyX3ks"
    "IGJhcl93LCBiYXJfaCwgUUNvbG9yKENfQkcpKQogICAgICAgICAgICBwLnNldFBlbihRQ29sb3Io"
    "Q19CT1JERVIpKQogICAgICAgICAgICBwLmRyYXdSZWN0KGJhcl94LCBiYXJfeSwgYmFyX3cgLSAx"
    "LCBiYXJfaCAtIDEpCgogICAgICAgICAgICBmaWxsX3cgPSBtYXgoMSwgaW50KChiYXJfdyAtIDIp"
    "ICogcGN0KSkKICAgICAgICAgICAgYmFyX2NvbG9yID0gKENfQkxPT0QgaWYgcGN0ID4gMC45IGVs"
    "c2UKICAgICAgICAgICAgICAgICAgICAgICAgIENfQ1JJTVNPTiBpZiBwY3QgPiAwLjc1IGVsc2UK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIENfR09MRF9ESU0pCiAgICAgICAgICAgIGdyYWQgPSBR"
    "TGluZWFyR3JhZGllbnQoYmFyX3ggKyAxLCBiYXJfeSwgYmFyX3ggKyBmaWxsX3csIGJhcl95KQog"
    "ICAgICAgICAgICBncmFkLnNldENvbG9yQXQoMCwgUUNvbG9yKGJhcl9jb2xvcikuZGFya2VyKDE1"
    "MCkpCiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgxLCBRQ29sb3IoYmFyX2NvbG9yKSkKICAg"
    "ICAgICAgICAgcC5maWxsUmVjdChiYXJfeCArIDEsIGJhcl95ICsgMSwgZmlsbF93LCBiYXJfaCAt"
    "IDIsIGdyYWQpCgogICAgICAgICAgICB5ICs9IHJvd19oCgogICAgICAgIHAuZW5kKCkKCiAgICBk"
    "ZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIkNhbGwgcGVyaW9kaWNhbGx5IHRv"
    "IHVwZGF0ZSBkcml2ZSBzdGF0cy4iIiIKICAgICAgICBzZWxmLl9yZWZyZXNoKCkKCgojIOKUgOKU"
    "gCBTUEhFUkUgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTcGhlcmVXaWRnZXQoUVdpZGdldCk6"
    "CiAgICAiIiIKICAgIEZpbGxlZCBjaXJjbGUgZ2F1Z2Ug4oCUIHVzZWQgZm9yIEJMT09EICh0b2tl"
    "biBwb29sKSBhbmQgTUFOQSAoVlJBTSkuCiAgICBGaWxscyBmcm9tIGJvdHRvbSB1cC4gR2xhc3N5"
    "IHNoaW5lIGVmZmVjdC4gTGFiZWwgYmVsb3cuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oCiAg"
    "ICAgICAgc2VsZiwKICAgICAgICBsYWJlbDogc3RyLAogICAgICAgIGNvbG9yX2Z1bGw6IHN0ciwK"
    "ICAgICAgICBjb2xvcl9lbXB0eTogc3RyLAogICAgICAgIHBhcmVudD1Ob25lCiAgICApOgogICAg"
    "ICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYubGFiZWwgICAgICAgPSBs"
    "YWJlbAogICAgICAgIHNlbGYuY29sb3JfZnVsbCAgPSBjb2xvcl9mdWxsCiAgICAgICAgc2VsZi5j"
    "b2xvcl9lbXB0eSA9IGNvbG9yX2VtcHR5CiAgICAgICAgc2VsZi5fZmlsbCAgICAgICA9IDAuMCAg"
    "ICMgMC4wIOKGkiAxLjAKICAgICAgICBzZWxmLl9hdmFpbGFibGUgID0gVHJ1ZQogICAgICAgIHNl"
    "bGYuc2V0TWluaW11bVNpemUoODAsIDEwMCkKCiAgICBkZWYgc2V0RmlsbChzZWxmLCBmcmFjdGlv"
    "bjogZmxvYXQsIGF2YWlsYWJsZTogYm9vbCA9IFRydWUpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "ZmlsbCAgICAgID0gbWF4KDAuMCwgbWluKDEuMCwgZnJhY3Rpb24pKQogICAgICAgIHNlbGYuX2F2"
    "YWlsYWJsZSA9IGF2YWlsYWJsZQogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRF"
    "dmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAg"
    "ICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAg"
    "ICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwgc2VsZi5oZWlnaHQoKQoKICAgICAgICByICA9IG1p"
    "bih3LCBoIC0gMjApIC8vIDIgLSA0CiAgICAgICAgY3ggPSB3IC8vIDIKICAgICAgICBjeSA9ICho"
    "IC0gMjApIC8vIDIgKyA0CgogICAgICAgICMgRHJvcCBzaGFkb3cKICAgICAgICBwLnNldFBlbihR"
    "dC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICBwLnNldEJydXNoKFFDb2xvcigwLCAwLCAwLCA4MCkp"
    "CiAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIgKyAzLCBjeSAtIHIgKyAzLCByICogMiwgciAq"
    "IDIpCgogICAgICAgICMgQmFzZSBjaXJjbGUgKGVtcHR5IGNvbG9yKQogICAgICAgIHAuc2V0QnJ1"
    "c2goUUNvbG9yKHNlbGYuY29sb3JfZW1wdHkpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JP"
    "UkRFUikpCiAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAy"
    "KQoKICAgICAgICAjIEZpbGwgZnJvbSBib3R0b20KICAgICAgICBpZiBzZWxmLl9maWxsID4gMC4w"
    "MSBhbmQgc2VsZi5fYXZhaWxhYmxlOgogICAgICAgICAgICBjaXJjbGVfcGF0aCA9IFFQYWludGVy"
    "UGF0aCgpCiAgICAgICAgICAgIGNpcmNsZV9wYXRoLmFkZEVsbGlwc2UoZmxvYXQoY3ggLSByKSwg"
    "ZmxvYXQoY3kgLSByKSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmbG9hdChy"
    "ICogMiksIGZsb2F0KHIgKiAyKSkKCiAgICAgICAgICAgIGZpbGxfdG9wX3kgPSBjeSArIHIgLSAo"
    "c2VsZi5fZmlsbCAqIHIgKiAyKQogICAgICAgICAgICBmcm9tIFB5U2lkZTYuUXRDb3JlIGltcG9y"
    "dCBRUmVjdEYKICAgICAgICAgICAgZmlsbF9yZWN0ID0gUVJlY3RGKGN4IC0gciwgZmlsbF90b3Bf"
    "eSwgciAqIDIsIGN5ICsgciAtIGZpbGxfdG9wX3kpCiAgICAgICAgICAgIGZpbGxfcGF0aCA9IFFQ"
    "YWludGVyUGF0aCgpCiAgICAgICAgICAgIGZpbGxfcGF0aC5hZGRSZWN0KGZpbGxfcmVjdCkKICAg"
    "ICAgICAgICAgY2xpcHBlZCA9IGNpcmNsZV9wYXRoLmludGVyc2VjdGVkKGZpbGxfcGF0aCkKCiAg"
    "ICAgICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAgICAgICAgICBwLnNldEJy"
    "dXNoKFFDb2xvcihzZWxmLmNvbG9yX2Z1bGwpKQogICAgICAgICAgICBwLmRyYXdQYXRoKGNsaXBw"
    "ZWQpCgogICAgICAgICMgR2xhc3N5IHNoaW5lCiAgICAgICAgc2hpbmUgPSBRUmFkaWFsR3JhZGll"
    "bnQoCiAgICAgICAgICAgIGZsb2F0KGN4IC0gciAqIDAuMyksIGZsb2F0KGN5IC0gciAqIDAuMyks"
    "IGZsb2F0KHIgKiAwLjYpCiAgICAgICAgKQogICAgICAgIHNoaW5lLnNldENvbG9yQXQoMCwgUUNv"
    "bG9yKDI1NSwgMjU1LCAyNTUsIDU1KSkKICAgICAgICBzaGluZS5zZXRDb2xvckF0KDEsIFFDb2xv"
    "cigyNTUsIDI1NSwgMjU1LCAwKSkKICAgICAgICBwLnNldEJydXNoKHNoaW5lKQogICAgICAgIHAu"
    "c2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBj"
    "eSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBPdXRsaW5lCiAgICAgICAgcC5zZXRCcnVz"
    "aChRdC5CcnVzaFN0eWxlLk5vQnJ1c2gpCiAgICAgICAgcC5zZXRQZW4oUVBlbihRQ29sb3Ioc2Vs"
    "Zi5jb2xvcl9mdWxsKSwgMSkpCiAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwg"
    "ciAqIDIsIHIgKiAyKQoKICAgICAgICAjIE4vQSBvdmVybGF5CiAgICAgICAgaWYgbm90IHNlbGYu"
    "X2F2YWlsYWJsZToKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfVEVYVF9ESU0pKQogICAg"
    "ICAgICAgICBwLnNldEZvbnQoUUZvbnQoIkNvdXJpZXIgTmV3IiwgOCkpCiAgICAgICAgICAgIGZt"
    "ID0gcC5mb250TWV0cmljcygpCiAgICAgICAgICAgIHR4dCA9ICJOL0EiCiAgICAgICAgICAgIHAu"
    "ZHJhd1RleHQoY3ggLSBmbS5ob3Jpem9udGFsQWR2YW5jZSh0eHQpIC8vIDIsIGN5ICsgNCwgdHh0"
    "KQoKICAgICAgICAjIExhYmVsIGJlbG93IHNwaGVyZQogICAgICAgIGxhYmVsX3RleHQgPSAoc2Vs"
    "Zi5sYWJlbCBpZiBzZWxmLl9hdmFpbGFibGUgZWxzZQogICAgICAgICAgICAgICAgICAgICAgZiJ7"
    "c2VsZi5sYWJlbH0iKQogICAgICAgIHBjdF90ZXh0ID0gZiJ7aW50KHNlbGYuX2ZpbGwgKiAxMDAp"
    "fSUiIGlmIHNlbGYuX2F2YWlsYWJsZSBlbHNlICIiCgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihz"
    "ZWxmLmNvbG9yX2Z1bGwpKQogICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDgsIFFG"
    "b250LldlaWdodC5Cb2xkKSkKICAgICAgICBmbSA9IHAuZm9udE1ldHJpY3MoKQoKICAgICAgICBs"
    "dyA9IGZtLmhvcml6b250YWxBZHZhbmNlKGxhYmVsX3RleHQpCiAgICAgICAgcC5kcmF3VGV4dChj"
    "eCAtIGx3IC8vIDIsIGggLSAxMCwgbGFiZWxfdGV4dCkKCiAgICAgICAgaWYgcGN0X3RleHQ6CiAg"
    "ICAgICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICAgICAgcC5zZXRG"
    "b250KFFGb250KERFQ0tfRk9OVCwgNykpCiAgICAgICAgICAgIGZtMiA9IHAuZm9udE1ldHJpY3Mo"
    "KQogICAgICAgICAgICBwdyA9IGZtMi5ob3Jpem9udGFsQWR2YW5jZShwY3RfdGV4dCkKICAgICAg"
    "ICAgICAgcC5kcmF3VGV4dChjeCAtIHB3IC8vIDIsIGggLSAxLCBwY3RfdGV4dCkKCiAgICAgICAg"
    "cC5lbmQoKQoKCiMg4pSA4pSAIE1PT04gV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBN"
    "b29uV2lkZ2V0KFFXaWRnZXQpOgogICAgIiIiCiAgICBEcmF3biBtb29uIG9yYiB3aXRoIHBoYXNl"
    "LWFjY3VyYXRlIHNoYWRvdy4KCiAgICBQSEFTRSBDT05WRU5USU9OIChub3J0aGVybiBoZW1pc3Bo"
    "ZXJlLCBzdGFuZGFyZCk6CiAgICAgIC0gV2F4aW5nIChuZXfihpJmdWxsKTogaWxsdW1pbmF0ZWQg"
    "cmlnaHQgc2lkZSwgc2hhZG93IG9uIGxlZnQKICAgICAgLSBXYW5pbmcgKGZ1bGzihpJuZXcpOiBp"
    "bGx1bWluYXRlZCBsZWZ0IHNpZGUsIHNoYWRvdyBvbiByaWdodAoKICAgIFRoZSBzaGFkb3dfc2lk"
    "ZSBmbGFnIGNhbiBiZSBmbGlwcGVkIGlmIHRlc3RpbmcgcmV2ZWFscyBpdCdzIGJhY2t3YXJkcwog"
    "ICAgb24gdGhpcyBtYWNoaW5lLiBTZXQgTU9PTl9TSEFET1dfRkxJUCA9IFRydWUgaW4gdGhhdCBj"
    "YXNlLgogICAgIiIiCgogICAgIyDihpAgRkxJUCBUSElTIHRvIFRydWUgaWYgbW9vbiBhcHBlYXJz"
    "IGJhY2t3YXJkcyBkdXJpbmcgdGVzdGluZwogICAgTU9PTl9TSEFET1dfRkxJUDogYm9vbCA9IEZh"
    "bHNlCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigp"
    "Ll9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9waGFzZSAgICAgICA9IDAuMCAgICAjIDAu"
    "MD1uZXcsIDAuNT1mdWxsLCAxLjA9bmV3CiAgICAgICAgc2VsZi5fbmFtZSAgICAgICAgPSAiTkVX"
    "IE1PT04iCiAgICAgICAgc2VsZi5faWxsdW1pbmF0aW9uID0gMC4wICAgIyAwLTEwMAogICAgICAg"
    "IHNlbGYuX3N1bnJpc2UgICAgICA9ICIwNjowMCIKICAgICAgICBzZWxmLl9zdW5zZXQgICAgICAg"
    "PSAiMTg6MzAiCiAgICAgICAgc2VsZi5fc3VuX2RhdGUgICAgID0gTm9uZQogICAgICAgIHNlbGYu"
    "c2V0TWluaW11bVNpemUoODAsIDExMCkKICAgICAgICBzZWxmLnVwZGF0ZVBoYXNlKCkgICAgICAg"
    "ICAgIyBwb3B1bGF0ZSBjb3JyZWN0IHBoYXNlIGltbWVkaWF0ZWx5CiAgICAgICAgc2VsZi5fZmV0"
    "Y2hfc3VuX2FzeW5jKCkKCiAgICBkZWYgX2ZldGNoX3N1bl9hc3luYyhzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIGRlZiBfZmV0Y2goKToKICAgICAgICAgICAgc3IsIHNzID0gZ2V0X3N1bl90aW1lcygp"
    "CiAgICAgICAgICAgIHNlbGYuX3N1bnJpc2UgPSBzcgogICAgICAgICAgICBzZWxmLl9zdW5zZXQg"
    "ID0gc3MKICAgICAgICAgICAgc2VsZi5fc3VuX2RhdGUgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6"
    "b25lKCkuZGF0ZSgpCiAgICAgICAgICAgICMgU2NoZWR1bGUgcmVwYWludCBvbiBtYWluIHRocmVh"
    "ZCB2aWEgUVRpbWVyIOKAlCBuZXZlciBjYWxsCiAgICAgICAgICAgICMgc2VsZi51cGRhdGUoKSBk"
    "aXJlY3RseSBmcm9tIGEgYmFja2dyb3VuZCB0aHJlYWQKICAgICAgICAgICAgUVRpbWVyLnNpbmds"
    "ZVNob3QoMCwgc2VsZi51cGRhdGUpCiAgICAgICAgdGhyZWFkaW5nLlRocmVhZCh0YXJnZXQ9X2Zl"
    "dGNoLCBkYWVtb249VHJ1ZSkuc3RhcnQoKQoKICAgIGRlZiB1cGRhdGVQaGFzZShzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHNlbGYuX3BoYXNlLCBzZWxmLl9uYW1lLCBzZWxmLl9pbGx1bWluYXRpb24g"
    "PSBnZXRfbW9vbl9waGFzZSgpCiAgICAgICAgdG9kYXkgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6"
    "b25lKCkuZGF0ZSgpCiAgICAgICAgaWYgc2VsZi5fc3VuX2RhdGUgIT0gdG9kYXk6CiAgICAgICAg"
    "ICAgIHNlbGYuX2ZldGNoX3N1bl9hc3luYygpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRl"
    "ZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihz"
    "ZWxmKQogICAgICAgIHAuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlh"
    "c2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCgogICAgICAg"
    "IHIgID0gbWluKHcsIGggLSAzNikgLy8gMiAtIDQKICAgICAgICBjeCA9IHcgLy8gMgogICAgICAg"
    "IGN5ID0gKGggLSAzNikgLy8gMiArIDQKCiAgICAgICAgIyBCYWNrZ3JvdW5kIGNpcmNsZSAoc3Bh"
    "Y2UpCiAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMjAsIDEyLCAyOCkpCiAgICAgICAgcC5zZXRQ"
    "ZW4oUVBlbihRQ29sb3IoQ19TSUxWRVJfRElNKSwgMSkpCiAgICAgICAgcC5kcmF3RWxsaXBzZShj"
    "eCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICBjeWNsZV9kYXkgPSBzZWxmLl9w"
    "aGFzZSAqIF9MVU5BUl9DWUNMRQogICAgICAgIGlzX3dheGluZyA9IGN5Y2xlX2RheSA8IChfTFVO"
    "QVJfQ1lDTEUgLyAyKQoKICAgICAgICAjIEZ1bGwgbW9vbiBiYXNlIChtb29uIHN1cmZhY2UgY29s"
    "b3IpCiAgICAgICAgaWYgc2VsZi5faWxsdW1pbmF0aW9uID4gMToKICAgICAgICAgICAgcC5zZXRQ"
    "ZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDIyMCwg"
    "MjEwLCAxODUpKQogICAgICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICog"
    "MiwgciAqIDIpCgogICAgICAgICMgU2hhZG93IGNhbGN1bGF0aW9uCiAgICAgICAgIyBpbGx1bWlu"
    "YXRpb24gZ29lcyAw4oaSMTAwIHdheGluZywgMTAw4oaSMCB3YW5pbmcKICAgICAgICAjIHNoYWRv"
    "d19vZmZzZXQgY29udHJvbHMgaG93IG11Y2ggb2YgdGhlIGNpcmNsZSB0aGUgc2hhZG93IGNvdmVy"
    "cwogICAgICAgIGlmIHNlbGYuX2lsbHVtaW5hdGlvbiA8IDk5OgogICAgICAgICAgICAjIGZyYWN0"
    "aW9uIG9mIGRpYW1ldGVyIHRoZSBzaGFkb3cgZWxsaXBzZSBpcyBvZmZzZXQKICAgICAgICAgICAg"
    "aWxsdW1fZnJhYyAgPSBzZWxmLl9pbGx1bWluYXRpb24gLyAxMDAuMAogICAgICAgICAgICBzaGFk"
    "b3dfZnJhYyA9IDEuMCAtIGlsbHVtX2ZyYWMKCiAgICAgICAgICAgICMgd2F4aW5nOiBpbGx1bWlu"
    "YXRlZCByaWdodCwgc2hhZG93IExFRlQKICAgICAgICAgICAgIyB3YW5pbmc6IGlsbHVtaW5hdGVk"
    "IGxlZnQsIHNoYWRvdyBSSUdIVAogICAgICAgICAgICAjIG9mZnNldCBtb3ZlcyB0aGUgc2hhZG93"
    "IGVsbGlwc2UgaG9yaXpvbnRhbGx5CiAgICAgICAgICAgIG9mZnNldCA9IGludChzaGFkb3dfZnJh"
    "YyAqIHIgKiAyKQoKICAgICAgICAgICAgaWYgTW9vbldpZGdldC5NT09OX1NIQURPV19GTElQOgog"
    "ICAgICAgICAgICAgICAgaXNfd2F4aW5nID0gbm90IGlzX3dheGluZwoKICAgICAgICAgICAgaWYg"
    "aXNfd2F4aW5nOgogICAgICAgICAgICAgICAgIyBTaGFkb3cgb24gbGVmdCBzaWRlCiAgICAgICAg"
    "ICAgICAgICBzaGFkb3dfeCA9IGN4IC0gciAtIG9mZnNldAogICAgICAgICAgICBlbHNlOgogICAg"
    "ICAgICAgICAgICAgIyBTaGFkb3cgb24gcmlnaHQgc2lkZQogICAgICAgICAgICAgICAgc2hhZG93"
    "X3ggPSBjeCAtIHIgKyBvZmZzZXQKCiAgICAgICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDE1LCA4"
    "LCAyMikpCiAgICAgICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQoKICAgICAgICAg"
    "ICAgIyBEcmF3IHNoYWRvdyBlbGxpcHNlIOKAlCBjbGlwcGVkIHRvIG1vb24gY2lyY2xlCiAgICAg"
    "ICAgICAgIG1vb25fcGF0aCA9IFFQYWludGVyUGF0aCgpCiAgICAgICAgICAgIG1vb25fcGF0aC5h"
    "ZGRFbGxpcHNlKGZsb2F0KGN4IC0gciksIGZsb2F0KGN5IC0gciksCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICBmbG9hdChyICogMiksIGZsb2F0KHIgKiAyKSkKICAgICAgICAgICAg"
    "c2hhZG93X3BhdGggPSBRUGFpbnRlclBhdGgoKQogICAgICAgICAgICBzaGFkb3dfcGF0aC5hZGRF"
    "bGxpcHNlKGZsb2F0KHNoYWRvd194KSwgZmxvYXQoY3kgLSByKSwKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgZmxvYXQociAqIDIpLCBmbG9hdChyICogMikpCiAgICAgICAgICAg"
    "IGNsaXBwZWRfc2hhZG93ID0gbW9vbl9wYXRoLmludGVyc2VjdGVkKHNoYWRvd19wYXRoKQogICAg"
    "ICAgICAgICBwLmRyYXdQYXRoKGNsaXBwZWRfc2hhZG93KQoKICAgICAgICAjIFN1YnRsZSBzdXJm"
    "YWNlIGRldGFpbCAoY3JhdGVycyBpbXBsaWVkIGJ5IHNsaWdodCB0ZXh0dXJlIGdyYWRpZW50KQog"
    "ICAgICAgIHNoaW5lID0gUVJhZGlhbEdyYWRpZW50KGZsb2F0KGN4IC0gciAqIDAuMiksIGZsb2F0"
    "KGN5IC0gciAqIDAuMiksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZmxvYXQociAq"
    "IDAuOCkpCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgwLCBRQ29sb3IoMjU1LCAyNTUsIDI0MCwg"
    "MzApKQogICAgICAgIHNoaW5lLnNldENvbG9yQXQoMSwgUUNvbG9yKDIwMCwgMTgwLCAxNDAsIDUp"
    "KQogICAgICAgIHAuc2V0QnJ1c2goc2hpbmUpCiAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUu"
    "Tm9QZW4pCiAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAy"
    "KQoKICAgICAgICAjIE91dGxpbmUKICAgICAgICBwLnNldEJydXNoKFF0LkJydXNoU3R5bGUuTm9C"
    "cnVzaCkKICAgICAgICBwLnNldFBlbihRUGVuKFFDb2xvcihDX1NJTFZFUiksIDEpKQogICAgICAg"
    "IHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBQ"
    "aGFzZSBuYW1lIGJlbG93IG1vb24KICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19TSUxWRVIpKQog"
    "ICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDcsIFFGb250LldlaWdodC5Cb2xkKSkK"
    "ICAgICAgICBmbSA9IHAuZm9udE1ldHJpY3MoKQogICAgICAgIG53ID0gZm0uaG9yaXpvbnRhbEFk"
    "dmFuY2Uoc2VsZi5fbmFtZSkKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gbncgLy8gMiwgY3kgKyBy"
    "ICsgMTQsIHNlbGYuX25hbWUpCgogICAgICAgICMgSWxsdW1pbmF0aW9uIHBlcmNlbnRhZ2UKICAg"
    "ICAgICBpbGx1bV9zdHIgPSBmIntzZWxmLl9pbGx1bWluYXRpb246LjBmfSUiCiAgICAgICAgcC5z"
    "ZXRQZW4oUUNvbG9yKENfVEVYVF9ESU0pKQogICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZP"
    "TlQsIDcpKQogICAgICAgIGZtMiA9IHAuZm9udE1ldHJpY3MoKQogICAgICAgIGl3ID0gZm0yLmhv"
    "cml6b250YWxBZHZhbmNlKGlsbHVtX3N0cikKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gaXcgLy8g"
    "MiwgY3kgKyByICsgMjQsIGlsbHVtX3N0cikKCiAgICAgICAgIyBTdW4gdGltZXMgYXQgdmVyeSBi"
    "b3R0b20KICAgICAgICBzdW5fc3RyID0gZiLimIAge3NlbGYuX3N1bnJpc2V9ICDimL0ge3NlbGYu"
    "X3N1bnNldH0iCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfR09MRF9ESU0pKQogICAgICAgIHAu"
    "c2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDcpKQogICAgICAgIGZtMyA9IHAuZm9udE1ldHJpY3Mo"
    "KQogICAgICAgIHN3ID0gZm0zLmhvcml6b250YWxBZHZhbmNlKHN1bl9zdHIpCiAgICAgICAgcC5k"
    "cmF3VGV4dChjeCAtIHN3IC8vIDIsIGggLSAyLCBzdW5fc3RyKQoKICAgICAgICBwLmVuZCgpCgoK"
    "IyDilIDilIAgRU1PVElPTiBCTE9DSyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgRW1vdGlvbkJsb2NrKFFX"
    "aWRnZXQpOgogICAgIiIiCiAgICBDb2xsYXBzaWJsZSBlbW90aW9uIGhpc3RvcnkgcGFuZWwuCiAg"
    "ICBTaG93cyBjb2xvci1jb2RlZCBjaGlwczog4pymIEVNT1RJT05fTkFNRSAgSEg6TU0KICAgIFNp"
    "dHMgbmV4dCB0byB0aGUgTWlycm9yIChmYWNlIHdpZGdldCkgaW4gdGhlIGJvdHRvbSBibG9jayBy"
    "b3cuCiAgICBDb2xsYXBzZXMgdG8ganVzdCB0aGUgaGVhZGVyIHN0cmlwLgogICAgIiIiCgogICAg"
    "ZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9f"
    "KHBhcmVudCkKICAgICAgICBzZWxmLl9oaXN0b3J5OiBsaXN0W3R1cGxlW3N0ciwgc3RyXV0gPSBb"
    "XSAgIyAoZW1vdGlvbiwgdGltZXN0YW1wKQogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gVHJ1ZQog"
    "ICAgICAgIHNlbGYuX21heF9lbnRyaWVzID0gMzAKCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlv"
    "dXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAg"
    "ICAgICAgbGF5b3V0LnNldFNwYWNpbmcoMCkKCiAgICAgICAgIyBIZWFkZXIgcm93CiAgICAgICAg"
    "aGVhZGVyID0gUVdpZGdldCgpCiAgICAgICAgaGVhZGVyLnNldEZpeGVkSGVpZ2h0KDIyKQogICAg"
    "ICAgIGhlYWRlci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JH"
    "M307IGJvcmRlci1ib3R0b206IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IgogICAgICAgICkK"
    "ICAgICAgICBobCA9IFFIQm94TGF5b3V0KGhlYWRlcikKICAgICAgICBobC5zZXRDb250ZW50c01h"
    "cmdpbnMoNiwgMCwgNCwgMCkKICAgICAgICBobC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGxibCA9"
    "IFFMYWJlbCgi4p2nIEVNT1RJT05BTCBSRUNPUkQiKQogICAgICAgIGxibC5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2Vp"
    "Z2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJp"
    "ZjsgbGV0dGVyLXNwYWNpbmc6IDFweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAg"
    "c2VsZi5fdG9nZ2xlX2J0biA9IFFUb29sQnV0dG9uKCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRu"
    "LnNldEZpeGVkU2l6ZSgxNiwgMTYpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHRyYW5zcGFyZW50OyBjb2xvcjoge0NfR09M"
    "RH07IGJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgc2Vs"
    "Zi5fdG9nZ2xlX2J0bi5zZXRUZXh0KCLilrwiKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZSkKCiAgICAgICAgaGwuYWRkV2lkZ2V0KGxibCkKICAg"
    "ICAgICBobC5hZGRTdHJldGNoKCkKICAgICAgICBobC5hZGRXaWRnZXQoc2VsZi5fdG9nZ2xlX2J0"
    "bikKCiAgICAgICAgIyBTY3JvbGwgYXJlYSBmb3IgZW1vdGlvbiBjaGlwcwogICAgICAgIHNlbGYu"
    "X3Njcm9sbCA9IFFTY3JvbGxBcmVhKCkKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0V2lkZ2V0UmVz"
    "aXphYmxlKFRydWUpCiAgICAgICAgc2VsZi5fc2Nyb2xsLnNldEhvcml6b250YWxTY3JvbGxCYXJQ"
    "b2xpY3koCiAgICAgICAgICAgIFF0LlNjcm9sbEJhclBvbGljeS5TY3JvbGxCYXJBbHdheXNPZmYp"
    "CiAgICAgICAgc2VsZi5fc2Nyb2xsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dy"
    "b3VuZDoge0NfQkcyfTsgYm9yZGVyOiBub25lOyIKICAgICAgICApCgogICAgICAgIHNlbGYuX2No"
    "aXBfY29udGFpbmVyID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQgPSBRVkJv"
    "eExheW91dChzZWxmLl9jaGlwX2NvbnRhaW5lcikKICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5z"
    "ZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5z"
    "ZXRTcGFjaW5nKDIpCiAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQuYWRkU3RyZXRjaCgpCiAgICAg"
    "ICAgc2VsZi5fc2Nyb2xsLnNldFdpZGdldChzZWxmLl9jaGlwX2NvbnRhaW5lcikKCiAgICAgICAg"
    "bGF5b3V0LmFkZFdpZGdldChoZWFkZXIpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9z"
    "Y3JvbGwpCgogICAgICAgIHNlbGYuc2V0TWluaW11bVdpZHRoKDEzMCkKCiAgICBkZWYgX3RvZ2ds"
    "ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFu"
    "ZGVkCiAgICAgICAgc2VsZi5fc2Nyb2xsLnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCiAgICAg"
    "ICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRUZXh0KCLilrwiIGlmIHNlbGYuX2V4cGFuZGVkIGVsc2Ug"
    "IuKWsiIpCiAgICAgICAgc2VsZi51cGRhdGVHZW9tZXRyeSgpCgogICAgZGVmIGFkZEVtb3Rpb24o"
    "c2VsZiwgZW1vdGlvbjogc3RyLCB0aW1lc3RhbXA6IHN0ciA9ICIiKSAtPiBOb25lOgogICAgICAg"
    "IGlmIG5vdCB0aW1lc3RhbXA6CiAgICAgICAgICAgIHRpbWVzdGFtcCA9IGRhdGV0aW1lLm5vdygp"
    "LnN0cmZ0aW1lKCIlSDolTSIpCiAgICAgICAgc2VsZi5faGlzdG9yeS5pbnNlcnQoMCwgKGVtb3Rp"
    "b24sIHRpbWVzdGFtcCkpCiAgICAgICAgc2VsZi5faGlzdG9yeSA9IHNlbGYuX2hpc3RvcnlbOnNl"
    "bGYuX21heF9lbnRyaWVzXQogICAgICAgIHNlbGYuX3JlYnVpbGRfY2hpcHMoKQoKICAgIGRlZiBf"
    "cmVidWlsZF9jaGlwcyhzZWxmKSAtPiBOb25lOgogICAgICAgICMgQ2xlYXIgZXhpc3RpbmcgY2hp"
    "cHMgKGtlZXAgdGhlIHN0cmV0Y2ggYXQgZW5kKQogICAgICAgIHdoaWxlIHNlbGYuX2NoaXBfbGF5"
    "b3V0LmNvdW50KCkgPiAxOgogICAgICAgICAgICBpdGVtID0gc2VsZi5fY2hpcF9sYXlvdXQudGFr"
    "ZUF0KDApCiAgICAgICAgICAgIGlmIGl0ZW0ud2lkZ2V0KCk6CiAgICAgICAgICAgICAgICBpdGVt"
    "LndpZGdldCgpLmRlbGV0ZUxhdGVyKCkKCiAgICAgICAgZm9yIGVtb3Rpb24sIHRzIGluIHNlbGYu"
    "X2hpc3Rvcnk6CiAgICAgICAgICAgIGNvbG9yID0gRU1PVElPTl9DT0xPUlMuZ2V0KGVtb3Rpb24s"
    "IENfVEVYVF9ESU0pCiAgICAgICAgICAgIGNoaXAgPSBRTGFiZWwoZiLinKYge2Vtb3Rpb24udXBw"
    "ZXIoKX0gIHt0c30iKQogICAgICAgICAgICBjaGlwLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "ICAgICBmImNvbG9yOiB7Y29sb3J9OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNL"
    "X0ZPTlR9LCBzZXJpZjsgIgogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgICAgICBmInBhZGRpbmc6"
    "IDFweCA0cHg7IGJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgICAgICkKICAgICAgICAgICAg"
    "c2VsZi5fY2hpcF9sYXlvdXQuaW5zZXJ0V2lkZ2V0KAogICAgICAgICAgICAgICAgc2VsZi5fY2hp"
    "cF9sYXlvdXQuY291bnQoKSAtIDEsIGNoaXAKICAgICAgICAgICAgKQoKICAgIGRlZiBjbGVhcihz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2hpc3RvcnkuY2xlYXIoKQogICAgICAgIHNlbGYu"
    "X3JlYnVpbGRfY2hpcHMoKQoKCiMg4pSA4pSAIE1JUlJPUiBXSURHRVQg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNs"
    "YXNzIE1pcnJvcldpZGdldChRTGFiZWwpOgogICAgIiIiCiAgICBGYWNlIGltYWdlIGRpc3BsYXkg"
    "4oCUICdUaGUgTWlycm9yJy4KICAgIER5bmFtaWNhbGx5IGxvYWRzIGFsbCB7RkFDRV9QUkVGSVh9"
    "XyoucG5nIGZpbGVzIGZyb20gY29uZmlnIHBhdGhzLmZhY2VzLgogICAgQXV0by1tYXBzIGZpbGVu"
    "YW1lIHRvIGVtb3Rpb24ga2V5OgogICAgICAgIHtGQUNFX1BSRUZJWH1fQWxlcnQucG5nICAgICDi"
    "hpIgImFsZXJ0IgogICAgICAgIHtGQUNFX1BSRUZJWH1fU2FkX0NyeWluZy5wbmcg4oaSICJzYWQi"
    "CiAgICAgICAge0ZBQ0VfUFJFRklYfV9DaGVhdF9Nb2RlLnBuZyDihpIgImNoZWF0bW9kZSIKICAg"
    "IEZhbGxzIGJhY2sgdG8gbmV1dHJhbCwgdGhlbiB0byBnb3RoaWMgcGxhY2Vob2xkZXIgaWYgbm8g"
    "aW1hZ2VzIGZvdW5kLgogICAgTWlzc2luZyBmYWNlcyBkZWZhdWx0IHRvIG5ldXRyYWwg4oCUIG5v"
    "IGNyYXNoLCBubyBoYXJkY29kZWQgbGlzdCByZXF1aXJlZC4KICAgICIiIgoKICAgICMgU3BlY2lh"
    "bCBzdGVtIOKGkiBlbW90aW9uIGtleSBtYXBwaW5ncyAobG93ZXJjYXNlIHN0ZW0gYWZ0ZXIgTW9y"
    "Z2FubmFfKQogICAgX1NURU1fVE9fRU1PVElPTjogZGljdFtzdHIsIHN0cl0gPSB7CiAgICAgICAg"
    "InNhZF9jcnlpbmciOiAgInNhZCIsCiAgICAgICAgImNoZWF0X21vZGUiOiAgImNoZWF0bW9kZSIs"
    "CiAgICB9CgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBl"
    "cigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9mYWNlc19kaXIgICA9IGNmZ19wYXRo"
    "KCJmYWNlcyIpCiAgICAgICAgc2VsZi5fY2FjaGU6IGRpY3Rbc3RyLCBRUGl4bWFwXSA9IHt9CiAg"
    "ICAgICAgc2VsZi5fY3VycmVudCAgICAgPSAibmV1dHJhbCIKICAgICAgICBzZWxmLl93YXJuZWQ6"
    "IHNldFtzdHJdID0gc2V0KCkKCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSgxNjAsIDE2MCkK"
    "ICAgICAgICBzZWxmLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQog"
    "ICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19C"
    "RzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJi"
    "b3JkZXItcmFkaXVzOiAycHg7IgogICAgICAgICkKCiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3Qo"
    "MzAwLCBzZWxmLl9wcmVsb2FkKQoKICAgIGRlZiBfcHJlbG9hZChzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgICIiIgogICAgICAgIFNjYW4gRmFjZXMvIGRpcmVjdG9yeSBmb3IgYWxsIHtGQUNFX1BSRUZJ"
    "WH1fKi5wbmcgZmlsZXMuCiAgICAgICAgQnVpbGQgZW1vdGlvbuKGknBpeG1hcCBjYWNoZSBkeW5h"
    "bWljYWxseS4KICAgICAgICBObyBoYXJkY29kZWQgbGlzdCDigJQgd2hhdGV2ZXIgaXMgaW4gdGhl"
    "IGZvbGRlciBpcyBhdmFpbGFibGUuCiAgICAgICAgIiIiCiAgICAgICAgaWYgbm90IHNlbGYuX2Zh"
    "Y2VzX2Rpci5leGlzdHMoKToKICAgICAgICAgICAgc2VsZi5fZHJhd19wbGFjZWhvbGRlcigpCiAg"
    "ICAgICAgICAgIHJldHVybgoKICAgICAgICBmb3IgaW1nX3BhdGggaW4gc2VsZi5fZmFjZXNfZGly"
    "Lmdsb2IoZiJ7RkFDRV9QUkVGSVh9XyoucG5nIik6CiAgICAgICAgICAgICMgc3RlbSA9IGV2ZXJ5"
    "dGhpbmcgYWZ0ZXIgIk1vcmdhbm5hXyIgd2l0aG91dCAucG5nCiAgICAgICAgICAgIHJhd19zdGVt"
    "ID0gaW1nX3BhdGguc3RlbVtsZW4oZiJ7RkFDRV9QUkVGSVh9XyIpOl0gICAgIyBlLmcuICJTYWRf"
    "Q3J5aW5nIgogICAgICAgICAgICBzdGVtX2xvd2VyID0gcmF3X3N0ZW0ubG93ZXIoKSAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIyAic2FkX2NyeWluZyIKCiAgICAgICAgICAgICMgTWFwIHNwZWNp"
    "YWwgc3RlbXMgdG8gZW1vdGlvbiBrZXlzCiAgICAgICAgICAgIGVtb3Rpb24gPSBzZWxmLl9TVEVN"
    "X1RPX0VNT1RJT04uZ2V0KHN0ZW1fbG93ZXIsIHN0ZW1fbG93ZXIpCgogICAgICAgICAgICBweCA9"
    "IFFQaXhtYXAoc3RyKGltZ19wYXRoKSkKICAgICAgICAgICAgaWYgbm90IHB4LmlzTnVsbCgpOgog"
    "ICAgICAgICAgICAgICAgc2VsZi5fY2FjaGVbZW1vdGlvbl0gPSBweAoKICAgICAgICBpZiBzZWxm"
    "Ll9jYWNoZToKICAgICAgICAgICAgc2VsZi5fcmVuZGVyKCJuZXV0cmFsIikKICAgICAgICBlbHNl"
    "OgogICAgICAgICAgICBzZWxmLl9kcmF3X3BsYWNlaG9sZGVyKCkKCiAgICBkZWYgX3JlbmRlcihz"
    "ZWxmLCBmYWNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgZmFjZSA9IGZhY2UubG93ZXIoKS5zdHJp"
    "cCgpCiAgICAgICAgaWYgZmFjZSBub3QgaW4gc2VsZi5fY2FjaGU6CiAgICAgICAgICAgIGlmIGZh"
    "Y2Ugbm90IGluIHNlbGYuX3dhcm5lZCBhbmQgZmFjZSAhPSAibmV1dHJhbCI6CiAgICAgICAgICAg"
    "ICAgICBwcmludChmIltNSVJST1JdW1dBUk5dIEZhY2Ugbm90IGluIGNhY2hlOiB7ZmFjZX0g4oCU"
    "IHVzaW5nIG5ldXRyYWwiKQogICAgICAgICAgICAgICAgc2VsZi5fd2FybmVkLmFkZChmYWNlKQog"
    "ICAgICAgICAgICBmYWNlID0gIm5ldXRyYWwiCiAgICAgICAgaWYgZmFjZSBub3QgaW4gc2VsZi5f"
    "Y2FjaGU6CiAgICAgICAgICAgIHNlbGYuX2RyYXdfcGxhY2Vob2xkZXIoKQogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICBzZWxmLl9jdXJyZW50ID0gZmFjZQogICAgICAgIHB4ID0gc2VsZi5fY2Fj"
    "aGVbZmFjZV0KICAgICAgICBzY2FsZWQgPSBweC5zY2FsZWQoCiAgICAgICAgICAgIHNlbGYud2lk"
    "dGgoKSAtIDQsCiAgICAgICAgICAgIHNlbGYuaGVpZ2h0KCkgLSA0LAogICAgICAgICAgICBRdC5B"
    "c3BlY3RSYXRpb01vZGUuS2VlcEFzcGVjdFJhdGlvLAogICAgICAgICAgICBRdC5UcmFuc2Zvcm1h"
    "dGlvbk1vZGUuU21vb3RoVHJhbnNmb3JtYXRpb24sCiAgICAgICAgKQogICAgICAgIHNlbGYuc2V0"
    "UGl4bWFwKHNjYWxlZCkKICAgICAgICBzZWxmLnNldFRleHQoIiIpCgogICAgZGVmIF9kcmF3X3Bs"
    "YWNlaG9sZGVyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5jbGVhcigpCiAgICAgICAgc2Vs"
    "Zi5zZXRUZXh0KCLinKZcbuKdp1xu4pymIikKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJ"
    "TVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT05fRElNfTsgZm9udC1z"
    "aXplOiAyNHB4OyBib3JkZXItcmFkaXVzOiAycHg7IgogICAgICAgICkKCiAgICBkZWYgc2V0X2Zh"
    "Y2Uoc2VsZiwgZmFjZTogc3RyKSAtPiBOb25lOgogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDAs"
    "IGxhbWJkYTogc2VsZi5fcmVuZGVyKGZhY2UpKQoKICAgIGRlZiByZXNpemVFdmVudChzZWxmLCBl"
    "dmVudCkgLT4gTm9uZToKICAgICAgICBzdXBlcigpLnJlc2l6ZUV2ZW50KGV2ZW50KQogICAgICAg"
    "IGlmIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBzZWxmLl9yZW5kZXIoc2VsZi5fY3VycmVudCkK"
    "CiAgICBAcHJvcGVydHkKICAgIGRlZiBjdXJyZW50X2ZhY2Uoc2VsZikgLT4gc3RyOgogICAgICAg"
    "IHJldHVybiBzZWxmLl9jdXJyZW50CgoKIyDilIDilIAgVkFNUElSRSBTVEFURSBTVFJJUCDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgQ3lj"
    "bGVXaWRnZXQoTW9vbldpZGdldCk6CiAgICAiIiJHZW5lcmljIGN5Y2xlIHZpc3VhbGl6YXRpb24g"
    "d2lkZ2V0IChjdXJyZW50bHkgbHVuYXItcGhhc2UgZHJpdmVuKS4iIiIKCgpjbGFzcyBWYW1waXJl"
    "U3RhdGVTdHJpcChRV2lkZ2V0KToKICAgICIiIgogICAgRnVsbC13aWR0aCBzdGF0dXMgYmFyIHNo"
    "b3dpbmc6CiAgICAgIFsg4pymIFZBTVBJUkVfU1RBVEUgIOKAoiAgSEg6TU0gIOKAoiAg4piAIFNV"
    "TlJJU0UgIOKYvSBTVU5TRVQgIOKAoiAgTU9PTiBQSEFTRSAgSUxMVU0lIF0KICAgIEFsd2F5cyB2"
    "aXNpYmxlLCBuZXZlciBjb2xsYXBzZXMuCiAgICBVcGRhdGVzIGV2ZXJ5IG1pbnV0ZSB2aWEgZXh0"
    "ZXJuYWwgUVRpbWVyIGNhbGwgdG8gcmVmcmVzaCgpLgogICAgQ29sb3ItY29kZWQgYnkgY3VycmVu"
    "dCB2YW1waXJlIHN0YXRlLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1O"
    "b25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9sYWJl"
    "bF9wcmVmaXggPSAiU1RBVEUiCiAgICAgICAgc2VsZi5fc3RhdGUgICAgID0gZ2V0X3ZhbXBpcmVf"
    "c3RhdGUoKQogICAgICAgIHNlbGYuX3RpbWVfc3RyICA9ICIiCiAgICAgICAgc2VsZi5fc3Vucmlz"
    "ZSAgID0gIjA2OjAwIgogICAgICAgIHNlbGYuX3N1bnNldCAgICA9ICIxODozMCIKICAgICAgICBz"
    "ZWxmLl9zdW5fZGF0ZSAgPSBOb25lCiAgICAgICAgc2VsZi5fbW9vbl9uYW1lID0gIk5FVyBNT09O"
    "IgogICAgICAgIHNlbGYuX2lsbHVtICAgICA9IDAuMAogICAgICAgIHNlbGYuc2V0Rml4ZWRIZWln"
    "aHQoMjgpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsg"
    "Ym9yZGVyLXRvcDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiKQogICAgICAgIHNlbGYuX2Zl"
    "dGNoX3N1bl9hc3luYygpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgc2V0X2xhYmVs"
    "KHNlbGYsIGxhYmVsOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fbGFiZWxfcHJlZml4ID0g"
    "KGxhYmVsIG9yICJTVEFURSIpLnN0cmlwKCkudXBwZXIoKQogICAgICAgIHNlbGYudXBkYXRlKCkK"
    "CiAgICBkZWYgX2ZldGNoX3N1bl9hc3luYyhzZWxmKSAtPiBOb25lOgogICAgICAgIGRlZiBfZigp"
    "OgogICAgICAgICAgICBzciwgc3MgPSBnZXRfc3VuX3RpbWVzKCkKICAgICAgICAgICAgc2VsZi5f"
    "c3VucmlzZSA9IHNyCiAgICAgICAgICAgIHNlbGYuX3N1bnNldCAgPSBzcwogICAgICAgICAgICBz"
    "ZWxmLl9zdW5fZGF0ZSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAgICAg"
    "ICAgICAgIyBTY2hlZHVsZSByZXBhaW50IG9uIG1haW4gdGhyZWFkIOKAlCBuZXZlciBjYWxsIHVw"
    "ZGF0ZSgpIGZyb20KICAgICAgICAgICAgIyBhIGJhY2tncm91bmQgdGhyZWFkLCBpdCBjYXVzZXMg"
    "UVRocmVhZCBjcmFzaCBvbiBzdGFydHVwCiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDAs"
    "IHNlbGYudXBkYXRlKQogICAgICAgIHRocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9mLCBkYWVtb249"
    "VHJ1ZSkuc3RhcnQoKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2Vs"
    "Zi5fc3RhdGUgICAgID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgICAgIHNlbGYuX3RpbWVfc3Ry"
    "ICA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5zdHJmdGltZSgiJVgiKQogICAgICAgIHRv"
    "ZGF5ID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLmRhdGUoKQogICAgICAgIGlmIHNlbGYu"
    "X3N1bl9kYXRlICE9IHRvZGF5OgogICAgICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQog"
    "ICAgICAgIF8sIHNlbGYuX21vb25fbmFtZSwgc2VsZi5faWxsdW0gPSBnZXRfbW9vbl9waGFzZSgp"
    "CiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAt"
    "PiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0UmVuZGVySGlu"
    "dChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53"
    "aWR0aCgpLCBzZWxmLmhlaWdodCgpCgogICAgICAgIHAuZmlsbFJlY3QoMCwgMCwgdywgaCwgUUNv"
    "bG9yKENfQkcyKSkKCiAgICAgICAgc3RhdGVfY29sb3IgPSBnZXRfdmFtcGlyZV9zdGF0ZV9jb2xv"
    "cihzZWxmLl9zdGF0ZSkKICAgICAgICB0ZXh0ID0gKAogICAgICAgICAgICBmIuKcpiAge3NlbGYu"
    "X2xhYmVsX3ByZWZpeH06IHtzZWxmLl9zdGF0ZX0gIOKAoiAge3NlbGYuX3RpbWVfc3RyfSAg4oCi"
    "ICAiCiAgICAgICAgICAgIGYi4piAIHtzZWxmLl9zdW5yaXNlfSAgICDimL0ge3NlbGYuX3N1bnNl"
    "dH0gIOKAoiAgIgogICAgICAgICAgICBmIntzZWxmLl9tb29uX25hbWV9ICB7c2VsZi5faWxsdW06"
    "LjBmfSUiCiAgICAgICAgKQoKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA5LCBR"
    "Rm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKHN0YXRlX2NvbG9yKSkK"
    "ICAgICAgICBmbSA9IHAuZm9udE1ldHJpY3MoKQogICAgICAgIHR3ID0gZm0uaG9yaXpvbnRhbEFk"
    "dmFuY2UodGV4dCkKICAgICAgICBwLmRyYXdUZXh0KCh3IC0gdHcpIC8vIDIsIGggLSA3LCB0ZXh0"
    "KQoKICAgICAgICBwLmVuZCgpCgoKY2xhc3MgTWluaUNhbGVuZGFyV2lkZ2V0KFFXaWRnZXQpOgog"
    "ICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5p"
    "dF9fKHBhcmVudCkKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxh"
    "eW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3Bh"
    "Y2luZyg0KQoKICAgICAgICBoZWFkZXIgPSBRSEJveExheW91dCgpCiAgICAgICAgaGVhZGVyLnNl"
    "dENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlbGYucHJldl9idG4gPSBRUHVz"
    "aEJ1dHRvbigiPDwiKQogICAgICAgIHNlbGYubmV4dF9idG4gPSBRUHVzaEJ1dHRvbigiPj4iKQog"
    "ICAgICAgIHNlbGYubW9udGhfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYubW9udGhfbGJs"
    "LnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIGZvciBi"
    "dG4gaW4gKHNlbGYucHJldl9idG4sIHNlbGYubmV4dF9idG4pOgogICAgICAgICAgICBidG4uc2V0"
    "Rml4ZWRXaWR0aCgzNCkKICAgICAgICAgICAgYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "ICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiAxcHgg"
    "c29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogMTBw"
    "eDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDJweDsiCiAgICAgICAgICAgICkKICAgICAg"
    "ICBzZWxmLm1vbnRoX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19H"
    "T0xEfTsgYm9yZGVyOiBub25lOyBmb250LXNpemU6IDEwcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyIK"
    "ICAgICAgICApCiAgICAgICAgaGVhZGVyLmFkZFdpZGdldChzZWxmLnByZXZfYnRuKQogICAgICAg"
    "IGhlYWRlci5hZGRXaWRnZXQoc2VsZi5tb250aF9sYmwsIDEpCiAgICAgICAgaGVhZGVyLmFkZFdp"
    "ZGdldChzZWxmLm5leHRfYnRuKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoaGVhZGVyKQoKICAg"
    "ICAgICBzZWxmLmNhbGVuZGFyID0gUUNhbGVuZGFyV2lkZ2V0KCkKICAgICAgICBzZWxmLmNhbGVu"
    "ZGFyLnNldEdyaWRWaXNpYmxlKFRydWUpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRWZXJ0aWNh"
    "bEhlYWRlckZvcm1hdChRQ2FsZW5kYXJXaWRnZXQuVmVydGljYWxIZWFkZXJGb3JtYXQuTm9WZXJ0"
    "aWNhbEhlYWRlcikKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldE5hdmlnYXRpb25CYXJWaXNpYmxl"
    "KEZhbHNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJRQ2FsZW5kYXJXaWRnZXQgUVdpZGdldHt7YWx0ZXJuYXRlLWJhY2tncm91bmQtY29sb3I6e0Nf"
    "QkcyfTt9fSAiCiAgICAgICAgICAgIGYiUVRvb2xCdXR0b257e2NvbG9yOntDX0dPTER9O319ICIK"
    "ICAgICAgICAgICAgZiJRQ2FsZW5kYXJXaWRnZXQgUUFic3RyYWN0SXRlbVZpZXc6ZW5hYmxlZHt7"
    "YmFja2dyb3VuZDp7Q19CRzJ9OyBjb2xvcjojZmZmZmZmOyAiCiAgICAgICAgICAgIGYic2VsZWN0"
    "aW9uLWJhY2tncm91bmQtY29sb3I6e0NfQ1JJTVNPTl9ESU19OyBzZWxlY3Rpb24tY29sb3I6e0Nf"
    "VEVYVH07IGdyaWRsaW5lLWNvbG9yOntDX0JPUkRFUn07fX0gIgogICAgICAgICAgICBmIlFDYWxl"
    "bmRhcldpZGdldCBRQWJzdHJhY3RJdGVtVmlldzpkaXNhYmxlZHt7Y29sb3I6IzhiOTVhMTt9fSIK"
    "ICAgICAgICApCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmNhbGVuZGFyKQoKICAgICAg"
    "ICBzZWxmLnByZXZfYnRuLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuY2FsZW5kYXIuc2hv"
    "d1ByZXZpb3VzTW9udGgoKSkKICAgICAgICBzZWxmLm5leHRfYnRuLmNsaWNrZWQuY29ubmVjdChs"
    "YW1iZGE6IHNlbGYuY2FsZW5kYXIuc2hvd05leHRNb250aCgpKQogICAgICAgIHNlbGYuY2FsZW5k"
    "YXIuY3VycmVudFBhZ2VDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fdXBkYXRlX2xhYmVsKQogICAgICAg"
    "IHNlbGYuX3VwZGF0ZV9sYWJlbCgpCiAgICAgICAgc2VsZi5fYXBwbHlfZm9ybWF0cygpCgogICAg"
    "ZGVmIF91cGRhdGVfbGFiZWwoc2VsZiwgKmFyZ3MpOgogICAgICAgIHllYXIgPSBzZWxmLmNhbGVu"
    "ZGFyLnllYXJTaG93bigpCiAgICAgICAgbW9udGggPSBzZWxmLmNhbGVuZGFyLm1vbnRoU2hvd24o"
    "KQogICAgICAgIHNlbGYubW9udGhfbGJsLnNldFRleHQoZiJ7ZGF0ZSh5ZWFyLCBtb250aCwgMSku"
    "c3RyZnRpbWUoJyVCICVZJyl9IikKICAgICAgICBzZWxmLl9hcHBseV9mb3JtYXRzKCkKCiAgICBk"
    "ZWYgX2FwcGx5X2Zvcm1hdHMoc2VsZik6CiAgICAgICAgYmFzZSA9IFFUZXh0Q2hhckZvcm1hdCgp"
    "CiAgICAgICAgYmFzZS5zZXRGb3JlZ3JvdW5kKFFDb2xvcigiI2U3ZWRmMyIpKQogICAgICAgIHNh"
    "dHVyZGF5ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICBzYXR1cmRheS5zZXRGb3JlZ3JvdW5k"
    "KFFDb2xvcihDX0dPTERfRElNKSkKICAgICAgICBzdW5kYXkgPSBRVGV4dENoYXJGb3JtYXQoKQog"
    "ICAgICAgIHN1bmRheS5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0JMT09EKSkKICAgICAgICBzZWxm"
    "LmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5Nb25kYXksIGJhc2Up"
    "CiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsu"
    "VHVlc2RheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0"
    "KFF0LkRheU9mV2Vlay5XZWRuZXNkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRX"
    "ZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuVGh1cnNkYXksIGJhc2UpCiAgICAgICAgc2Vs"
    "Zi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuRnJpZGF5LCBiYXNl"
    "KQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVr"
    "LlNhdHVyZGF5LCBzYXR1cmRheSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0"
    "Rm9ybWF0KFF0LkRheU9mV2Vlay5TdW5kYXksIHN1bmRheSkKCiAgICAgICAgeWVhciA9IHNlbGYu"
    "Y2FsZW5kYXIueWVhclNob3duKCkKICAgICAgICBtb250aCA9IHNlbGYuY2FsZW5kYXIubW9udGhT"
    "aG93bigpCiAgICAgICAgZmlyc3RfZGF5ID0gUURhdGUoeWVhciwgbW9udGgsIDEpCiAgICAgICAg"
    "Zm9yIGRheSBpbiByYW5nZSgxLCBmaXJzdF9kYXkuZGF5c0luTW9udGgoKSArIDEpOgogICAgICAg"
    "ICAgICBkID0gUURhdGUoeWVhciwgbW9udGgsIGRheSkKICAgICAgICAgICAgZm10ID0gUVRleHRD"
    "aGFyRm9ybWF0KCkKICAgICAgICAgICAgd2Vla2RheSA9IGQuZGF5T2ZXZWVrKCkKICAgICAgICAg"
    "ICAgaWYgd2Vla2RheSA9PSBRdC5EYXlPZldlZWsuU2F0dXJkYXkudmFsdWU6CiAgICAgICAgICAg"
    "ICAgICBmbXQuc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgICAgIGVs"
    "aWYgd2Vla2RheSA9PSBRdC5EYXlPZldlZWsuU3VuZGF5LnZhbHVlOgogICAgICAgICAgICAgICAg"
    "Zm10LnNldEZvcmVncm91bmQoUUNvbG9yKENfQkxPT0QpKQogICAgICAgICAgICBlbHNlOgogICAg"
    "ICAgICAgICAgICAgZm10LnNldEZvcmVncm91bmQoUUNvbG9yKCIjZTdlZGYzIikpCiAgICAgICAg"
    "ICAgIHNlbGYuY2FsZW5kYXIuc2V0RGF0ZVRleHRGb3JtYXQoZCwgZm10KQoKICAgICAgICB0b2Rh"
    "eV9mbXQgPSBRVGV4dENoYXJGb3JtYXQoKQogICAgICAgIHRvZGF5X2ZtdC5zZXRGb3JlZ3JvdW5k"
    "KFFDb2xvcigiIzY4ZDM5YSIpKQogICAgICAgIHRvZGF5X2ZtdC5zZXRCYWNrZ3JvdW5kKFFDb2xv"
    "cigiIzE2MzgyNSIpKQogICAgICAgIHRvZGF5X2ZtdC5zZXRGb250V2VpZ2h0KFFGb250LldlaWdo"
    "dC5Cb2xkKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0RGF0ZVRleHRGb3JtYXQoUURhdGUuY3Vy"
    "cmVudERhdGUoKSwgdG9kYXlfZm10KQoKCiMg4pSA4pSAIENPTExBUFNJQkxFIEJMT0NLIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFz"
    "cyBDb2xsYXBzaWJsZUJsb2NrKFFXaWRnZXQpOgogICAgIiIiCiAgICBXcmFwcGVyIHRoYXQgYWRk"
    "cyBhIGNvbGxhcHNlL2V4cGFuZCB0b2dnbGUgdG8gYW55IHdpZGdldC4KICAgIENvbGxhcHNlcyBo"
    "b3Jpem9udGFsbHkgKHJpZ2h0d2FyZCkg4oCUIGhpZGVzIGNvbnRlbnQsIGtlZXBzIGhlYWRlciBz"
    "dHJpcC4KICAgIEhlYWRlciBzaG93cyBsYWJlbC4gVG9nZ2xlIGJ1dHRvbiBvbiByaWdodCBlZGdl"
    "IG9mIGhlYWRlci4KCiAgICBVc2FnZToKICAgICAgICBibG9jayA9IENvbGxhcHNpYmxlQmxvY2so"
    "IuKdpyBCTE9PRCIsIFNwaGVyZVdpZGdldCguLi4pKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQo"
    "YmxvY2spCiAgICAiIiIKCiAgICB0b2dnbGVkID0gU2lnbmFsKGJvb2wpCgogICAgZGVmIF9faW5p"
    "dF9fKHNlbGYsIGxhYmVsOiBzdHIsIGNvbnRlbnQ6IFFXaWRnZXQsCiAgICAgICAgICAgICAgICAg"
    "ZXhwYW5kZWQ6IGJvb2wgPSBUcnVlLCBtaW5fd2lkdGg6IGludCA9IDkwLAogICAgICAgICAgICAg"
    "ICAgIHJlc2VydmVfd2lkdGg6IGJvb2wgPSBGYWxzZSwKICAgICAgICAgICAgICAgICBwYXJlbnQ9"
    "Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZXhw"
    "YW5kZWQgICAgICAgPSBleHBhbmRlZAogICAgICAgIHNlbGYuX21pbl93aWR0aCAgICAgID0gbWlu"
    "X3dpZHRoCiAgICAgICAgc2VsZi5fcmVzZXJ2ZV93aWR0aCAgPSByZXNlcnZlX3dpZHRoCiAgICAg"
    "ICAgc2VsZi5fY29udGVudCAgICAgICAgPSBjb250ZW50CgogICAgICAgIG1haW4gPSBRVkJveExh"
    "eW91dChzZWxmKQogICAgICAgIG1haW4uc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAg"
    "ICAgICAgbWFpbi5zZXRTcGFjaW5nKDApCgogICAgICAgICMgSGVhZGVyCiAgICAgICAgc2VsZi5f"
    "aGVhZGVyID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5faGVhZGVyLnNldEZpeGVkSGVpZ2h0KDIy"
    "KQogICAgICAgIHNlbGYuX2hlYWRlci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tn"
    "cm91bmQ6IHtDX0JHM307IGJvcmRlci1ib3R0b206IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07"
    "ICIKICAgICAgICAgICAgZiJib3JkZXItdG9wOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIK"
    "ICAgICAgICApCiAgICAgICAgaGwgPSBRSEJveExheW91dChzZWxmLl9oZWFkZXIpCiAgICAgICAg"
    "aGwuc2V0Q29udGVudHNNYXJnaW5zKDYsIDAsIDQsIDApCiAgICAgICAgaGwuc2V0U3BhY2luZyg0"
    "KQoKICAgICAgICBzZWxmLl9sYmwgPSBRTGFiZWwobGFiZWwpCiAgICAgICAgc2VsZi5fbGJsLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDlw"
    "eDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tf"
    "Rk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2luZzogMXB4OyBib3JkZXI6IG5vbmU7IgogICAgICAg"
    "ICkKCiAgICAgICAgc2VsZi5fYnRuID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX2J0bi5z"
    "ZXRGaXhlZFNpemUoMTYsIDE2KQogICAgICAgIHNlbGYuX2J0bi5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImJhY2tncm91bmQ6IHRyYW5zcGFyZW50OyBjb2xvcjoge0NfR09MRF9ESU19OyBi"
    "b3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2J0"
    "bi5zZXRUZXh0KCI8IikKICAgICAgICBzZWxmLl9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Rv"
    "Z2dsZSkKCiAgICAgICAgaGwuYWRkV2lkZ2V0KHNlbGYuX2xibCkKICAgICAgICBobC5hZGRTdHJl"
    "dGNoKCkKICAgICAgICBobC5hZGRXaWRnZXQoc2VsZi5fYnRuKQoKICAgICAgICBtYWluLmFkZFdp"
    "ZGdldChzZWxmLl9oZWFkZXIpCiAgICAgICAgbWFpbi5hZGRXaWRnZXQoc2VsZi5fY29udGVudCkK"
    "CiAgICAgICAgc2VsZi5fYXBwbHlfc3RhdGUoKQoKICAgIGRlZiBpc19leHBhbmRlZChzZWxmKSAt"
    "PiBib29sOgogICAgICAgIHJldHVybiBzZWxmLl9leHBhbmRlZAoKICAgIGRlZiBfdG9nZ2xlKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5kZWQK"
    "ICAgICAgICBzZWxmLl9hcHBseV9zdGF0ZSgpCiAgICAgICAgc2VsZi50b2dnbGVkLmVtaXQoc2Vs"
    "Zi5fZXhwYW5kZWQpCgogICAgZGVmIF9hcHBseV9zdGF0ZShzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYuX2NvbnRlbnQuc2V0VmlzaWJsZShzZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxmLl9i"
    "dG4uc2V0VGV4dCgiPCIgaWYgc2VsZi5fZXhwYW5kZWQgZWxzZSAiPiIpCgogICAgICAgICMgUmVz"
    "ZXJ2ZSBmaXhlZCBzbG90IHdpZHRoIHdoZW4gcmVxdWVzdGVkICh1c2VkIGJ5IG1pZGRsZSBsb3dl"
    "ciBibG9jaykKICAgICAgICBpZiBzZWxmLl9yZXNlcnZlX3dpZHRoOgogICAgICAgICAgICBzZWxm"
    "LnNldE1pbmltdW1XaWR0aChzZWxmLl9taW5fd2lkdGgpCiAgICAgICAgICAgIHNlbGYuc2V0TWF4"
    "aW11bVdpZHRoKDE2Nzc3MjE1KQogICAgICAgIGVsaWYgc2VsZi5fZXhwYW5kZWQ6CiAgICAgICAg"
    "ICAgIHNlbGYuc2V0TWluaW11bVdpZHRoKHNlbGYuX21pbl93aWR0aCkKICAgICAgICAgICAgc2Vs"
    "Zi5zZXRNYXhpbXVtV2lkdGgoMTY3NzcyMTUpICAjIHVuY29uc3RyYWluZWQKICAgICAgICBlbHNl"
    "OgogICAgICAgICAgICAjIENvbGxhcHNlZDoganVzdCB0aGUgaGVhZGVyIHN0cmlwIChsYWJlbCAr"
    "IGJ1dHRvbikKICAgICAgICAgICAgY29sbGFwc2VkX3cgPSBzZWxmLl9oZWFkZXIuc2l6ZUhpbnQo"
    "KS53aWR0aCgpCiAgICAgICAgICAgIHNlbGYuc2V0Rml4ZWRXaWR0aChtYXgoNjAsIGNvbGxhcHNl"
    "ZF93KSkKCiAgICAgICAgc2VsZi51cGRhdGVHZW9tZXRyeSgpCiAgICAgICAgcGFyZW50ID0gc2Vs"
    "Zi5wYXJlbnRXaWRnZXQoKQogICAgICAgIGlmIHBhcmVudCBhbmQgcGFyZW50LmxheW91dCgpOgog"
    "ICAgICAgICAgICBwYXJlbnQubGF5b3V0KCkuYWN0aXZhdGUoKQoKCiMg4pSA4pSAIEhBUkRXQVJF"
    "IFBBTkVMIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgApjbGFzcyBIYXJkd2FyZVBhbmVsKFFXaWRnZXQpOgogICAgIiIiCiAg"
    "ICBUaGUgc3lzdGVtcyByaWdodCBwYW5lbCBjb250ZW50cy4KICAgIEdyb3Vwczogc3RhdHVzIGlu"
    "Zm8sIGRyaXZlIGJhcnMsIENQVS9SQU0gZ2F1Z2VzLCBHUFUvVlJBTSBnYXVnZXMsIEdQVSB0ZW1w"
    "LgogICAgUmVwb3J0cyBoYXJkd2FyZSBhdmFpbGFiaWxpdHkgaW4gRGlhZ25vc3RpY3Mgb24gc3Rh"
    "cnR1cC4KICAgIFNob3dzIE4vQSBncmFjZWZ1bGx5IHdoZW4gZGF0YSB1bmF2YWlsYWJsZS4KICAg"
    "ICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIo"
    "KS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYu"
    "X2RldGVjdF9oYXJkd2FyZSgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIGxheW91dCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRz"
    "TWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAg"
    "IGRlZiBzZWN0aW9uX2xhYmVsKHRleHQ6IHN0cikgLT4gUUxhYmVsOgogICAgICAgICAgICBsYmwg"
    "PSBRTGFiZWwodGV4dCkKICAgICAgICAgICAgbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "ICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGxldHRlci1zcGFjaW5nOiAy"
    "cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsg"
    "Zm9udC13ZWlnaHQ6IGJvbGQ7IgogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybiBsYmwK"
    "CiAgICAgICAgIyDilIDilIAgU3RhdHVzIGJsb2NrIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIFNUQVRVUyIpKQogICAg"
    "ICAgIHN0YXR1c19mcmFtZSA9IFFGcmFtZSgpCiAgICAgICAgc3RhdHVzX2ZyYW1lLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfUEFORUx9OyBib3JkZXI6IDFweCBz"
    "b2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7IgogICAgICAgICkKICAgICAgICBz"
    "dGF0dXNfZnJhbWUuc2V0Rml4ZWRIZWlnaHQoODgpCiAgICAgICAgc2YgPSBRVkJveExheW91dChz"
    "dGF0dXNfZnJhbWUpCiAgICAgICAgc2Yuc2V0Q29udGVudHNNYXJnaW5zKDgsIDQsIDgsIDQpCiAg"
    "ICAgICAgc2Yuc2V0U3BhY2luZygyKQoKICAgICAgICBzZWxmLmxibF9zdGF0dXMgID0gUUxhYmVs"
    "KCLinKYgU1RBVFVTOiBPRkZMSU5FIikKICAgICAgICBzZWxmLmxibF9tb2RlbCAgID0gUUxhYmVs"
    "KCLinKYgVkVTU0VMOiBMT0FESU5HLi4uIikKICAgICAgICBzZWxmLmxibF9zZXNzaW9uID0gUUxh"
    "YmVsKCLinKYgU0VTU0lPTjogMDA6MDA6MDAiKQogICAgICAgIHNlbGYubGJsX3Rva2VucyAgPSBR"
    "TGFiZWwoIuKcpiBUT0tFTlM6IDAiKQoKICAgICAgICBmb3IgbGJsIGluIChzZWxmLmxibF9zdGF0"
    "dXMsIHNlbGYubGJsX21vZGVsLAogICAgICAgICAgICAgICAgICAgIHNlbGYubGJsX3Nlc3Npb24s"
    "IHNlbGYubGJsX3Rva2Vucyk6CiAgICAgICAgICAgIGxibC5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDEwcHg7ICIKICAgICAg"
    "ICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgYm9yZGVyOiBub25l"
    "OyIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZi5hZGRXaWRnZXQobGJsKQoKICAgICAgICBs"
    "YXlvdXQuYWRkV2lkZ2V0KHN0YXR1c19mcmFtZSkKCiAgICAgICAgIyDilIDilIAgRHJpdmUgYmFy"
    "cyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0"
    "KHNlY3Rpb25fbGFiZWwoIuKdpyBTVE9SQUdFIikpCiAgICAgICAgc2VsZi5kcml2ZV93aWRnZXQg"
    "PSBEcml2ZVdpZGdldCgpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmRyaXZlX3dpZGdl"
    "dCkKCiAgICAgICAgIyDilIDilIAgQ1BVIC8gUkFNIGdhdWdlcyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKdpyBWSVRBTCBFU1NFTkNFIikpCiAg"
    "ICAgICAgcmFtX2NwdSA9IFFHcmlkTGF5b3V0KCkKICAgICAgICByYW1fY3B1LnNldFNwYWNpbmco"
    "MykKCiAgICAgICAgc2VsZi5nYXVnZV9jcHUgID0gR2F1Z2VXaWRnZXQoIkNQVSIsICAiJSIsICAg"
    "MTAwLjAsIENfU0lMVkVSKQogICAgICAgIHNlbGYuZ2F1Z2VfcmFtICA9IEdhdWdlV2lkZ2V0KCJS"
    "QU0iLCAgIkdCIiwgICA2NC4wLCBDX0dPTERfRElNKQogICAgICAgIHJhbV9jcHUuYWRkV2lkZ2V0"
    "KHNlbGYuZ2F1Z2VfY3B1LCAwLCAwKQogICAgICAgIHJhbV9jcHUuYWRkV2lkZ2V0KHNlbGYuZ2F1"
    "Z2VfcmFtLCAwLCAxKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQocmFtX2NwdSkKCiAgICAgICAg"
    "IyDilIDilIAgR1BVIC8gVlJBTSBnYXVnZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdp"
    "ZGdldChzZWN0aW9uX2xhYmVsKCLinacgQVJDQU5FIFBPV0VSIikpCiAgICAgICAgZ3B1X3ZyYW0g"
    "PSBRR3JpZExheW91dCgpCiAgICAgICAgZ3B1X3ZyYW0uc2V0U3BhY2luZygzKQoKICAgICAgICBz"
    "ZWxmLmdhdWdlX2dwdSAgPSBHYXVnZVdpZGdldCgiR1BVIiwgICIlIiwgICAxMDAuMCwgQ19QVVJQ"
    "TEUpCiAgICAgICAgc2VsZi5nYXVnZV92cmFtID0gR2F1Z2VXaWRnZXQoIlZSQU0iLCAiR0IiLCAg"
    "ICA4LjAsIENfQ1JJTVNPTikKICAgICAgICBncHVfdnJhbS5hZGRXaWRnZXQoc2VsZi5nYXVnZV9n"
    "cHUsICAwLCAwKQogICAgICAgIGdwdV92cmFtLmFkZFdpZGdldChzZWxmLmdhdWdlX3ZyYW0sIDAs"
    "IDEpCiAgICAgICAgbGF5b3V0LmFkZExheW91dChncHVfdnJhbSkKCiAgICAgICAgIyDilIDilIAg"
    "R1BVIFRlbXAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5"
    "b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgSU5GRVJOQUwgSEVBVCIpKQogICAgICAg"
    "IHNlbGYuZ2F1Z2VfdGVtcCA9IEdhdWdlV2lkZ2V0KCJHUFUgVEVNUCIsICLCsEMiLCA5NS4wLCBD"
    "X0JMT09EKQogICAgICAgIHNlbGYuZ2F1Z2VfdGVtcC5zZXRNYXhpbXVtSGVpZ2h0KDY1KQogICAg"
    "ICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5nYXVnZV90ZW1wKQoKICAgICAgICAjIOKUgOKUgCBH"
    "UFUgbWFzdGVyIGJhciAoZnVsbCB3aWR0aCkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgSU5GRVJO"
    "QUwgRU5HSU5FIikpCiAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyID0gR2F1Z2VXaWRnZXQo"
    "IlJUWCIsICIlIiwgMTAwLjAsIENfQ1JJTVNPTikKICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0"
    "ZXIuc2V0TWF4aW11bUhlaWdodCg1NSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuZ2F1"
    "Z2VfZ3B1X21hc3RlcikKCiAgICAgICAgbGF5b3V0LmFkZFN0cmV0Y2goKQoKICAgIGRlZiBfZGV0"
    "ZWN0X2hhcmR3YXJlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2hlY2sgd2hh"
    "dCBoYXJkd2FyZSBtb25pdG9yaW5nIGlzIGF2YWlsYWJsZS4KICAgICAgICBNYXJrIHVuYXZhaWxh"
    "YmxlIGdhdWdlcyBhcHByb3ByaWF0ZWx5LgogICAgICAgIERpYWdub3N0aWMgbWVzc2FnZXMgY29s"
    "bGVjdGVkIGZvciB0aGUgRGlhZ25vc3RpY3MgdGFiLgogICAgICAgICIiIgogICAgICAgIHNlbGYu"
    "X2RpYWdfbWVzc2FnZXM6IGxpc3Rbc3RyXSA9IFtdCgogICAgICAgIGlmIG5vdCBQU1VUSUxfT0s6"
    "CiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfY3B1LnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAg"
    "c2VsZi5nYXVnZV9yYW0uc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLl9kaWFnX21l"
    "c3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICJbSEFSRFdBUkVdIHBzdXRpbCBub3QgYXZh"
    "aWxhYmxlIOKAlCBDUFUvUkFNIGdhdWdlcyBkaXNhYmxlZC4gIgogICAgICAgICAgICAgICAgInBp"
    "cCBpbnN0YWxsIHBzdXRpbCB0byBlbmFibGUuIgogICAgICAgICAgICApCiAgICAgICAgZWxzZToK"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoIltIQVJEV0FSRV0gcHN1dGls"
    "IE9LIOKAlCBDUFUvUkFNIG1vbml0b3JpbmcgYWN0aXZlLiIpCgogICAgICAgIGlmIG5vdCBOVk1M"
    "X09LOgogICAgICAgICAgICBzZWxmLmdhdWdlX2dwdS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAg"
    "ICAgIHNlbGYuZ2F1Z2VfdnJhbS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuZ2F1"
    "Z2VfdGVtcC5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3Rl"
    "ci5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5k"
    "KAogICAgICAgICAgICAgICAgIltIQVJEV0FSRV0gcHludm1sIG5vdCBhdmFpbGFibGUgb3Igbm8g"
    "TlZJRElBIEdQVSBkZXRlY3RlZCDigJQgIgogICAgICAgICAgICAgICAgIkdQVSBnYXVnZXMgZGlz"
    "YWJsZWQuIHBpcCBpbnN0YWxsIHB5bnZtbCB0byBlbmFibGUuIgogICAgICAgICAgICApCiAgICAg"
    "ICAgZWxzZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgbmFtZSA9IHB5bnZtbC5u"
    "dm1sRGV2aWNlR2V0TmFtZShncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgaWYgaXNpbnN0YW5j"
    "ZShuYW1lLCBieXRlcyk6CiAgICAgICAgICAgICAgICAgICAgbmFtZSA9IG5hbWUuZGVjb2RlKCkK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKAogICAgICAgICAgICAg"
    "ICAgICAgIGYiW0hBUkRXQVJFXSBweW52bWwgT0sg4oCUIEdQVSBkZXRlY3RlZDoge25hbWV9Igog"
    "ICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgIyBVcGRhdGUgbWF4IFZSQU0gZnJvbSBh"
    "Y3R1YWwgaGFyZHdhcmUKICAgICAgICAgICAgICAgIG1lbSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0"
    "TWVtb3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgdG90YWxfZ2IgPSBtZW0udG90"
    "YWwgLyAxMDI0KiozCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3ZyYW0ubWF4X3ZhbCA9IHRv"
    "dGFsX2diCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAg"
    "IHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKGYiW0hBUkRXQVJFXSBweW52bWwgZXJyb3I6IHtl"
    "fSIpCgogICAgZGVmIHVwZGF0ZV9zdGF0cyhzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAg"
    "ICAgIENhbGxlZCBldmVyeSBzZWNvbmQgZnJvbSB0aGUgc3RhdHMgUVRpbWVyLgogICAgICAgIFJl"
    "YWRzIGhhcmR3YXJlIGFuZCB1cGRhdGVzIGFsbCBnYXVnZXMuCiAgICAgICAgIiIiCiAgICAgICAg"
    "aWYgUFNVVElMX09LOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjcHUgPSBwc3V0"
    "aWwuY3B1X3BlcmNlbnQoKQogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9jcHUuc2V0VmFsdWUo"
    "Y3B1LCBmIntjcHU6LjBmfSUiLCBhdmFpbGFibGU9VHJ1ZSkKCiAgICAgICAgICAgICAgICBtZW0g"
    "PSBwc3V0aWwudmlydHVhbF9tZW1vcnkoKQogICAgICAgICAgICAgICAgcnUgID0gbWVtLnVzZWQg"
    "IC8gMTAyNCoqMwogICAgICAgICAgICAgICAgcnQgID0gbWVtLnRvdGFsIC8gMTAyNCoqMwogICAg"
    "ICAgICAgICAgICAgc2VsZi5nYXVnZV9yYW0uc2V0VmFsdWUocnUsIGYie3J1Oi4xZn0ve3J0Oi4w"
    "Zn1HQiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBhdmFpbGFibGU9"
    "VHJ1ZSkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLm1heF92YWwgPSBydAogICAgICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICBpZiBO"
    "Vk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICB1"
    "dGlsICAgICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0VXRpbGl6YXRpb25SYXRlcyhncHVfaGFuZGxl"
    "KQogICAgICAgICAgICAgICAgbWVtX2luZm8gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUlu"
    "Zm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIHRlbXAgICAgID0gcHludm1sLm52bWxEZXZp"
    "Y2VHZXRUZW1wZXJhdHVyZSgKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGdwdV9oYW5k"
    "bGUsIHB5bnZtbC5OVk1MX1RFTVBFUkFUVVJFX0dQVSkKCiAgICAgICAgICAgICAgICBncHVfcGN0"
    "ICAgPSBmbG9hdCh1dGlsLmdwdSkKICAgICAgICAgICAgICAgIHZyYW1fdXNlZCA9IG1lbV9pbmZv"
    "LnVzZWQgIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgdnJhbV90b3QgID0gbWVtX2luZm8udG90"
    "YWwgLyAxMDI0KiozCgogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHUuc2V0VmFsdWUoZ3B1"
    "X3BjdCwgZiJ7Z3B1X3BjdDouMGZ9JSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICBhdmFpbGFibGU9VHJ1ZSkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfdnJhbS5z"
    "ZXRWYWx1ZSh2cmFtX3VzZWQsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZiJ7dnJhbV91c2VkOi4xZn0ve3ZyYW1fdG90Oi4wZn1HQiIsCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBz"
    "ZWxmLmdhdWdlX3RlbXAuc2V0VmFsdWUoZmxvYXQodGVtcCksIGYie3RlbXB9wrBDIiwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBhdmFpbGFibGU9VHJ1ZSkKCiAgICAg"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgbmFtZSA9IHB5bnZtbC5udm1sRGV2"
    "aWNlR2V0TmFtZShncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgICAgIGlmIGlzaW5zdGFuY2Uo"
    "bmFtZSwgYnl0ZXMpOgogICAgICAgICAgICAgICAgICAgICAgICBuYW1lID0gbmFtZS5kZWNvZGUo"
    "KQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBu"
    "YW1lID0gIkdQVSIKCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIuc2V0VmFs"
    "dWUoCiAgICAgICAgICAgICAgICAgICAgZ3B1X3BjdCwKICAgICAgICAgICAgICAgICAgICBmIntu"
    "YW1lfSAge2dwdV9wY3Q6LjBmfSUgICIKICAgICAgICAgICAgICAgICAgICBmIlt7dnJhbV91c2Vk"
    "Oi4xZn0ve3ZyYW1fdG90Oi4wZn1HQiBWUkFNXSIsCiAgICAgICAgICAgICAgICAgICAgYXZhaWxh"
    "YmxlPVRydWUsCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246"
    "CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgVXBkYXRlIGRyaXZlIGJhcnMgZXZlcnkg"
    "MzAgc2Vjb25kcyAobm90IGV2ZXJ5IHRpY2spCiAgICAgICAgaWYgbm90IGhhc2F0dHIoc2VsZiwg"
    "Il9kcml2ZV90aWNrIik6CiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgPSAwCiAgICAgICAg"
    "c2VsZi5fZHJpdmVfdGljayArPSAxCiAgICAgICAgaWYgc2VsZi5fZHJpdmVfdGljayA+PSAzMDoK"
    "ICAgICAgICAgICAgc2VsZi5fZHJpdmVfdGljayA9IDAKICAgICAgICAgICAgc2VsZi5kcml2ZV93"
    "aWRnZXQucmVmcmVzaCgpCgogICAgZGVmIHNldF9zdGF0dXNfbGFiZWxzKHNlbGYsIHN0YXR1czog"
    "c3RyLCBtb2RlbDogc3RyLAogICAgICAgICAgICAgICAgICAgICAgICAgIHNlc3Npb246IHN0ciwg"
    "dG9rZW5zOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5sYmxfc3RhdHVzLnNldFRleHQoZiLi"
    "nKYgU1RBVFVTOiB7c3RhdHVzfSIpCiAgICAgICAgc2VsZi5sYmxfbW9kZWwuc2V0VGV4dChmIuKc"
    "piBWRVNTRUw6IHttb2RlbH0iKQogICAgICAgIHNlbGYubGJsX3Nlc3Npb24uc2V0VGV4dChmIuKc"
    "piBTRVNTSU9OOiB7c2Vzc2lvbn0iKQogICAgICAgIHNlbGYubGJsX3Rva2Vucy5zZXRUZXh0KGYi"
    "4pymIFRPS0VOUzoge3Rva2Vuc30iKQoKICAgIGRlZiBnZXRfZGlhZ25vc3RpY3Moc2VsZikgLT4g"
    "bGlzdFtzdHJdOgogICAgICAgIHJldHVybiBnZXRhdHRyKHNlbGYsICJfZGlhZ19tZXNzYWdlcyIs"
    "IFtdKQoKCiMg4pSA4pSAIFBBU1MgMiBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBBbGwgd2lkZ2V0IGNs"
    "YXNzZXMgZGVmaW5lZC4gU3ludGF4LWNoZWNrYWJsZSBpbmRlcGVuZGVudGx5LgojIE5leHQ6IFBh"
    "c3MgMyDigJQgV29ya2VyIFRocmVhZHMKIyAoRG9scGhpbldvcmtlciB3aXRoIHN0cmVhbWluZywg"
    "U2VudGltZW50V29ya2VyLCBJZGxlV29ya2VyLCBTb3VuZFdvcmtlcikKCgojIOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoj"
    "IE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgMzogV09SS0VSIFRIUkVBRFMKIwojIFdvcmtlcnMgZGVm"
    "aW5lZCBoZXJlOgojICAgTExNQWRhcHRvciAoYmFzZSArIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRv"
    "ciArIE9sbGFtYUFkYXB0b3IgKwojICAgICAgICAgICAgICAgQ2xhdWRlQWRhcHRvciArIE9wZW5B"
    "SUFkYXB0b3IpCiMgICBTdHJlYW1pbmdXb3JrZXIgICDigJQgbWFpbiBnZW5lcmF0aW9uLCBlbWl0"
    "cyB0b2tlbnMgb25lIGF0IGEgdGltZQojICAgU2VudGltZW50V29ya2VyICAg4oCUIGNsYXNzaWZp"
    "ZXMgZW1vdGlvbiBmcm9tIHJlc3BvbnNlIHRleHQKIyAgIElkbGVXb3JrZXIgICAgICAgIOKAlCB1"
    "bnNvbGljaXRlZCB0cmFuc21pc3Npb25zIGR1cmluZyBpZGxlCiMgICBTb3VuZFdvcmtlciAgICAg"
    "ICDigJQgcGxheXMgc291bmRzIG9mZiB0aGUgbWFpbiB0aHJlYWQKIwojIEFMTCBnZW5lcmF0aW9u"
    "IGlzIHN0cmVhbWluZy4gTm8gYmxvY2tpbmcgY2FsbHMgb24gbWFpbiB0aHJlYWQuIEV2ZXIuCiMg"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQCgppbXBvcnQgYWJjCmltcG9ydCBqc29uCmltcG9ydCB1cmxsaWIucmVxdWVzdApp"
    "bXBvcnQgdXJsbGliLmVycm9yCmltcG9ydCBodHRwLmNsaWVudApmcm9tIHR5cGluZyBpbXBvcnQg"
    "SXRlcmF0b3IKCgojIOKUgOKUgCBMTE0gQURBUFRPUiBCQVNFIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBMTE1BZGFwdG9yKGFi"
    "Yy5BQkMpOgogICAgIiIiCiAgICBBYnN0cmFjdCBiYXNlIGZvciBhbGwgbW9kZWwgYmFja2VuZHMu"
    "CiAgICBUaGUgZGVjayBjYWxscyBzdHJlYW0oKSBvciBnZW5lcmF0ZSgpIOKAlCBuZXZlciBrbm93"
    "cyB3aGljaCBiYWNrZW5kIGlzIGFjdGl2ZS4KICAgICIiIgoKICAgIEBhYmMuYWJzdHJhY3RtZXRo"
    "b2QKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICAiIiJSZXR1cm4g"
    "VHJ1ZSBpZiB0aGUgYmFja2VuZCBpcyByZWFjaGFibGUuIiIiCiAgICAgICAgLi4uCgogICAgQGFi"
    "Yy5hYnN0cmFjdG1ldGhvZAogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHBy"
    "b21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGlj"
    "dF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jb"
    "c3RyXToKICAgICAgICAiIiIKICAgICAgICBZaWVsZCByZXNwb25zZSB0ZXh0IHRva2VuLWJ5LXRv"
    "a2VuIChvciBjaHVuay1ieS1jaHVuayBmb3IgQVBJIGJhY2tlbmRzKS4KICAgICAgICBNdXN0IGJl"
    "IGEgZ2VuZXJhdG9yLiBOZXZlciBibG9jayBmb3IgdGhlIGZ1bGwgcmVzcG9uc2UgYmVmb3JlIHlp"
    "ZWxkaW5nLgogICAgICAgICIiIgogICAgICAgIC4uLgoKICAgIGRlZiBnZW5lcmF0ZSgKICAgICAg"
    "ICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAg"
    "IGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwK"
    "ICAgICkgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIENvbnZlbmllbmNlIHdyYXBwZXI6IGNv"
    "bGxlY3QgYWxsIHN0cmVhbSB0b2tlbnMgaW50byBvbmUgc3RyaW5nLgogICAgICAgIFVzZWQgZm9y"
    "IHNlbnRpbWVudCBjbGFzc2lmaWNhdGlvbiAoc21hbGwgYm91bmRlZCBjYWxscyBvbmx5KS4KICAg"
    "ICAgICAiIiIKICAgICAgICByZXR1cm4gIiIuam9pbihzZWxmLnN0cmVhbShwcm9tcHQsIHN5c3Rl"
    "bSwgaGlzdG9yeSwgbWF4X25ld190b2tlbnMpKQoKICAgIGRlZiBidWlsZF9jaGF0bWxfcHJvbXB0"
    "KHNlbGYsIHN5c3RlbTogc3RyLCBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIHVzZXJfdGV4dDogc3RyID0gIiIpIC0+IHN0cjoKICAgICAgICAiIiIKICAg"
    "ICAgICBCdWlsZCBhIENoYXRNTC1mb3JtYXQgcHJvbXB0IHN0cmluZyBmb3IgbG9jYWwgbW9kZWxz"
    "LgogICAgICAgIGhpc3RvcnkgPSBbeyJyb2xlIjogInVzZXIifCJhc3Npc3RhbnQiLCAiY29udGVu"
    "dCI6ICIuLi4ifV0KICAgICAgICAiIiIKICAgICAgICBwYXJ0cyA9IFtmIjx8aW1fc3RhcnR8PnN5"
    "c3RlbVxue3N5c3RlbX08fGltX2VuZHw+Il0KICAgICAgICBmb3IgbXNnIGluIGhpc3Rvcnk6CiAg"
    "ICAgICAgICAgIHJvbGUgICAgPSBtc2cuZ2V0KCJyb2xlIiwgInVzZXIiKQogICAgICAgICAgICBj"
    "b250ZW50ID0gbXNnLmdldCgiY29udGVudCIsICIiKQogICAgICAgICAgICBwYXJ0cy5hcHBlbmQo"
    "ZiI8fGltX3N0YXJ0fD57cm9sZX1cbntjb250ZW50fTx8aW1fZW5kfD4iKQogICAgICAgIGlmIHVz"
    "ZXJfdGV4dDoKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGYiPHxpbV9zdGFydHw+dXNlclxue3Vz"
    "ZXJfdGV4dH08fGltX2VuZHw+IikKICAgICAgICBwYXJ0cy5hcHBlbmQoIjx8aW1fc3RhcnR8PmFz"
    "c2lzdGFudFxuIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBhcnRzKQoKCiMg4pSA4pSAIExP"
    "Q0FMIFRSQU5TRk9STUVSUyBBREFQVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApj"
    "bGFzcyBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IoTExNQWRhcHRvcik6CiAgICAiIiIKICAgIExv"
    "YWRzIGEgSHVnZ2luZ0ZhY2UgbW9kZWwgZnJvbSBhIGxvY2FsIGZvbGRlci4KICAgIFN0cmVhbWlu"
    "ZzogdXNlcyBtb2RlbC5nZW5lcmF0ZSgpIHdpdGggYSBjdXN0b20gc3RyZWFtZXIgdGhhdCB5aWVs"
    "ZHMgdG9rZW5zLgogICAgUmVxdWlyZXM6IHRvcmNoLCB0cmFuc2Zvcm1lcnMKICAgICIiIgoKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmLCBtb2RlbF9wYXRoOiBzdHIpOgogICAgICAgIHNlbGYuX3BhdGgg"
    "ICAgICA9IG1vZGVsX3BhdGgKICAgICAgICBzZWxmLl9tb2RlbCAgICAgPSBOb25lCiAgICAgICAg"
    "c2VsZi5fdG9rZW5pemVyID0gTm9uZQogICAgICAgIHNlbGYuX2xvYWRlZCAgICA9IEZhbHNlCiAg"
    "ICAgICAgc2VsZi5fZXJyb3IgICAgID0gIiIKCiAgICBkZWYgbG9hZChzZWxmKSAtPiBib29sOgog"
    "ICAgICAgICIiIgogICAgICAgIExvYWQgbW9kZWwgYW5kIHRva2VuaXplci4gQ2FsbCBmcm9tIGEg"
    "YmFja2dyb3VuZCB0aHJlYWQuCiAgICAgICAgUmV0dXJucyBUcnVlIG9uIHN1Y2Nlc3MuCiAgICAg"
    "ICAgIiIiCiAgICAgICAgaWYgbm90IFRPUkNIX09LOgogICAgICAgICAgICBzZWxmLl9lcnJvciA9"
    "ICJ0b3JjaC90cmFuc2Zvcm1lcnMgbm90IGluc3RhbGxlZCIKICAgICAgICAgICAgcmV0dXJuIEZh"
    "bHNlCiAgICAgICAgdHJ5OgogICAgICAgICAgICBmcm9tIHRyYW5zZm9ybWVycyBpbXBvcnQgQXV0"
    "b01vZGVsRm9yQ2F1c2FsTE0sIEF1dG9Ub2tlbml6ZXIKICAgICAgICAgICAgc2VsZi5fdG9rZW5p"
    "emVyID0gQXV0b1Rva2VuaXplci5mcm9tX3ByZXRyYWluZWQoc2VsZi5fcGF0aCkKICAgICAgICAg"
    "ICAgc2VsZi5fbW9kZWwgPSBBdXRvTW9kZWxGb3JDYXVzYWxMTS5mcm9tX3ByZXRyYWluZWQoCiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9wYXRoLAogICAgICAgICAgICAgICAgdG9yY2hfZHR5cGU9dG9y"
    "Y2guZmxvYXQxNiwKICAgICAgICAgICAgICAgIGRldmljZV9tYXA9ImF1dG8iLAogICAgICAgICAg"
    "ICAgICAgbG93X2NwdV9tZW1fdXNhZ2U9VHJ1ZSwKICAgICAgICAgICAgKQogICAgICAgICAgICBz"
    "ZWxmLl9sb2FkZWQgPSBUcnVlCiAgICAgICAgICAgIHJldHVybiBUcnVlCiAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9lcnJvciA9IHN0cihlKQogICAgICAg"
    "ICAgICByZXR1cm4gRmFsc2UKCiAgICBAcHJvcGVydHkKICAgIGRlZiBlcnJvcihzZWxmKSAtPiBz"
    "dHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2Vycm9yCgogICAgZGVmIGlzX2Nvbm5lY3RlZChzZWxm"
    "KSAtPiBib29sOgogICAgICAgIHJldHVybiBzZWxmLl9sb2FkZWQKCiAgICBkZWYgc3RyZWFtKAog"
    "ICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAg"
    "ICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0g"
    "NTEyLAogICAgKSAtPiBJdGVyYXRvcltzdHJdOgogICAgICAgICIiIgogICAgICAgIFN0cmVhbXMg"
    "dG9rZW5zIHVzaW5nIHRyYW5zZm9ybWVycyBUZXh0SXRlcmF0b3JTdHJlYW1lci4KICAgICAgICBZ"
    "aWVsZHMgZGVjb2RlZCB0ZXh0IGZyYWdtZW50cyBhcyB0aGV5IGFyZSBnZW5lcmF0ZWQuCiAgICAg"
    "ICAgIiIiCiAgICAgICAgaWYgbm90IHNlbGYuX2xvYWRlZDoKICAgICAgICAgICAgeWllbGQgIltF"
    "UlJPUjogbW9kZWwgbm90IGxvYWRlZF0iCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIGZyb20gdHJhbnNmb3JtZXJzIGltcG9ydCBUZXh0SXRlcmF0b3JTdHJlYW1l"
    "cgoKICAgICAgICAgICAgZnVsbF9wcm9tcHQgPSBzZWxmLmJ1aWxkX2NoYXRtbF9wcm9tcHQoc3lz"
    "dGVtLCBoaXN0b3J5KQogICAgICAgICAgICBpZiBwcm9tcHQ6CiAgICAgICAgICAgICAgICAjIHBy"
    "b21wdCBhbHJlYWR5IGluY2x1ZGVzIHVzZXIgdHVybiBpZiBjYWxsZXIgYnVpbHQgaXQKICAgICAg"
    "ICAgICAgICAgIGZ1bGxfcHJvbXB0ID0gcHJvbXB0CgogICAgICAgICAgICBpbnB1dF9pZHMgPSBz"
    "ZWxmLl90b2tlbml6ZXIoCiAgICAgICAgICAgICAgICBmdWxsX3Byb21wdCwgcmV0dXJuX3RlbnNv"
    "cnM9InB0IgogICAgICAgICAgICApLmlucHV0X2lkcy50bygiY3VkYSIpCgogICAgICAgICAgICBh"
    "dHRlbnRpb25fbWFzayA9IChpbnB1dF9pZHMgIT0gc2VsZi5fdG9rZW5pemVyLnBhZF90b2tlbl9p"
    "ZCkubG9uZygpCgogICAgICAgICAgICBzdHJlYW1lciA9IFRleHRJdGVyYXRvclN0cmVhbWVyKAog"
    "ICAgICAgICAgICAgICAgc2VsZi5fdG9rZW5pemVyLAogICAgICAgICAgICAgICAgc2tpcF9wcm9t"
    "cHQ9VHJ1ZSwKICAgICAgICAgICAgICAgIHNraXBfc3BlY2lhbF90b2tlbnM9VHJ1ZSwKICAgICAg"
    "ICAgICAgKQoKICAgICAgICAgICAgZ2VuX2t3YXJncyA9IHsKICAgICAgICAgICAgICAgICJpbnB1"
    "dF9pZHMiOiAgICAgIGlucHV0X2lkcywKICAgICAgICAgICAgICAgICJhdHRlbnRpb25fbWFzayI6"
    "IGF0dGVudGlvbl9tYXNrLAogICAgICAgICAgICAgICAgIm1heF9uZXdfdG9rZW5zIjogbWF4X25l"
    "d190b2tlbnMsCiAgICAgICAgICAgICAgICAidGVtcGVyYXR1cmUiOiAgICAwLjcsCiAgICAgICAg"
    "ICAgICAgICAiZG9fc2FtcGxlIjogICAgICBUcnVlLAogICAgICAgICAgICAgICAgInBhZF90b2tl"
    "bl9pZCI6ICAgc2VsZi5fdG9rZW5pemVyLmVvc190b2tlbl9pZCwKICAgICAgICAgICAgICAgICJz"
    "dHJlYW1lciI6ICAgICAgIHN0cmVhbWVyLAogICAgICAgICAgICB9CgogICAgICAgICAgICAjIFJ1"
    "biBnZW5lcmF0aW9uIGluIGEgZGFlbW9uIHRocmVhZCDigJQgc3RyZWFtZXIgeWllbGRzIGhlcmUK"
    "ICAgICAgICAgICAgZ2VuX3RocmVhZCA9IHRocmVhZGluZy5UaHJlYWQoCiAgICAgICAgICAgICAg"
    "ICB0YXJnZXQ9c2VsZi5fbW9kZWwuZ2VuZXJhdGUsCiAgICAgICAgICAgICAgICBrd2FyZ3M9Z2Vu"
    "X2t3YXJncywKICAgICAgICAgICAgICAgIGRhZW1vbj1UcnVlLAogICAgICAgICAgICApCiAgICAg"
    "ICAgICAgIGdlbl90aHJlYWQuc3RhcnQoKQoKICAgICAgICAgICAgZm9yIHRva2VuX3RleHQgaW4g"
    "c3RyZWFtZXI6CiAgICAgICAgICAgICAgICB5aWVsZCB0b2tlbl90ZXh0CgogICAgICAgICAgICBn"
    "ZW5fdGhyZWFkLmpvaW4odGltZW91dD0xMjApCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMg"
    "ZToKICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjoge2V9XSIKCgojIOKUgOKUgCBPTExBTUEg"
    "QURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKY2xhc3MgT2xsYW1hQWRhcHRvcihMTE1BZGFwdG9yKToKICAgICIi"
    "IgogICAgQ29ubmVjdHMgdG8gYSBsb2NhbGx5IHJ1bm5pbmcgT2xsYW1hIGluc3RhbmNlLgogICAg"
    "U3RyZWFtaW5nOiByZWFkcyBOREpTT04gcmVzcG9uc2UgY2h1bmtzIGZyb20gT2xsYW1hJ3MgL2Fw"
    "aS9nZW5lcmF0ZSBlbmRwb2ludC4KICAgIE9sbGFtYSBtdXN0IGJlIHJ1bm5pbmcgYXMgYSBzZXJ2"
    "aWNlIG9uIGxvY2FsaG9zdDoxMTQzNC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBt"
    "b2RlbF9uYW1lOiBzdHIsIGhvc3Q6IHN0ciA9ICJsb2NhbGhvc3QiLCBwb3J0OiBpbnQgPSAxMTQz"
    "NCk6CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbF9uYW1lCiAgICAgICAgc2VsZi5fYmFzZSAg"
    "PSBmImh0dHA6Ly97aG9zdH06e3BvcnR9IgoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4g"
    "Ym9vbDoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJlcSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1"
    "ZXN0KGYie3NlbGYuX2Jhc2V9L2FwaS90YWdzIikKICAgICAgICAgICAgcmVzcCA9IHVybGxpYi5y"
    "ZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTMpCiAgICAgICAgICAgIHJldHVybiByZXNwLnN0"
    "YXR1cyA9PSAyMDAKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4g"
    "RmFsc2UKCiAgICBkZWYgc3RyZWFtKAogICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIs"
    "CiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAg"
    "ICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVyYXRvcltzdHJdOgogICAg"
    "ICAgICIiIgogICAgICAgIFBvc3RzIHRvIC9hcGkvY2hhdCB3aXRoIHN0cmVhbT1UcnVlLgogICAg"
    "ICAgIE9sbGFtYSByZXR1cm5zIE5ESlNPTiDigJQgb25lIEpTT04gb2JqZWN0IHBlciBsaW5lLgog"
    "ICAgICAgIFlpZWxkcyB0aGUgJ2NvbnRlbnQnIGZpZWxkIG9mIGVhY2ggYXNzaXN0YW50IG1lc3Nh"
    "Z2UgY2h1bmsuCiAgICAgICAgIiIiCiAgICAgICAgbWVzc2FnZXMgPSBbeyJyb2xlIjogInN5c3Rl"
    "bSIsICJjb250ZW50Ijogc3lzdGVtfV0KICAgICAgICBmb3IgbXNnIGluIGhpc3Rvcnk6CiAgICAg"
    "ICAgICAgIG1lc3NhZ2VzLmFwcGVuZChtc2cpCgogICAgICAgIHBheWxvYWQgPSBqc29uLmR1bXBz"
    "KHsKICAgICAgICAgICAgIm1vZGVsIjogICAgc2VsZi5fbW9kZWwsCiAgICAgICAgICAgICJtZXNz"
    "YWdlcyI6IG1lc3NhZ2VzLAogICAgICAgICAgICAic3RyZWFtIjogICBUcnVlLAogICAgICAgICAg"
    "ICAib3B0aW9ucyI6ICB7Im51bV9wcmVkaWN0IjogbWF4X25ld190b2tlbnMsICJ0ZW1wZXJhdHVy"
    "ZSI6IDAuN30sCiAgICAgICAgfSkuZW5jb2RlKCJ1dGYtOCIpCgogICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgcmVxID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdCgKICAgICAgICAgICAgICAgIGYie3Nl"
    "bGYuX2Jhc2V9L2FwaS9jaGF0IiwKICAgICAgICAgICAgICAgIGRhdGE9cGF5bG9hZCwKICAgICAg"
    "ICAgICAgICAgIGhlYWRlcnM9eyJDb250ZW50LVR5cGUiOiAiYXBwbGljYXRpb24vanNvbiJ9LAog"
    "ICAgICAgICAgICAgICAgbWV0aG9kPSJQT1NUIiwKICAgICAgICAgICAgKQogICAgICAgICAgICB3"
    "aXRoIHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTEyMCkgYXMgcmVzcDoKICAg"
    "ICAgICAgICAgICAgIGZvciByYXdfbGluZSBpbiByZXNwOgogICAgICAgICAgICAgICAgICAgIGxp"
    "bmUgPSByYXdfbGluZS5kZWNvZGUoInV0Zi04Iikuc3RyaXAoKQogICAgICAgICAgICAgICAgICAg"
    "IGlmIG5vdCBsaW5lOgogICAgICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAg"
    "ICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgb2JqID0ganNvbi5sb2Fkcyhs"
    "aW5lKQogICAgICAgICAgICAgICAgICAgICAgICBjaHVuayA9IG9iai5nZXQoIm1lc3NhZ2UiLCB7"
    "fSkuZ2V0KCJjb250ZW50IiwgIiIpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIGNodW5rOgog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgeWllbGQgY2h1bmsKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgaWYgb2JqLmdldCgiZG9uZSIsIEZhbHNlKToKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGJyZWFrCiAgICAgICAgICAgICAgICAgICAgZXhjZXB0IGpzb24uSlNPTkRlY29kZUVycm9y"
    "OgogICAgICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b24gYXMgZToKICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogT2xsYW1hIOKAlCB7ZX1dIgoK"
    "CiMg4pSA4pSAIENMQVVERSBBREFQVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBDbGF1ZGVBZGFwdG9yKExM"
    "TUFkYXB0b3IpOgogICAgIiIiCiAgICBTdHJlYW1zIGZyb20gQW50aHJvcGljJ3MgQ2xhdWRlIEFQ"
    "SSB1c2luZyBTU0UgKHNlcnZlci1zZW50IGV2ZW50cykuCiAgICBSZXF1aXJlcyBhbiBBUEkga2V5"
    "IGluIGNvbmZpZy4KICAgICIiIgoKICAgIF9BUElfVVJMID0gImFwaS5hbnRocm9waWMuY29tIgog"
    "ICAgX1BBVEggICAgPSAiL3YxL21lc3NhZ2VzIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhcGlf"
    "a2V5OiBzdHIsIG1vZGVsOiBzdHIgPSAiY2xhdWRlLXNvbm5ldC00LTYiKToKICAgICAgICBzZWxm"
    "Ll9rZXkgICA9IGFwaV9rZXkKICAgICAgICBzZWxmLl9tb2RlbCA9IG1vZGVsCgogICAgZGVmIGlz"
    "X2Nvbm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBib29sKHNlbGYuX2tleSkK"
    "CiAgICBkZWYgc3RyZWFtKAogICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAg"
    "ICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtYXhf"
    "bmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVyYXRvcltzdHJdOgogICAgICAgIG1l"
    "c3NhZ2VzID0gW10KICAgICAgICBmb3IgbXNnIGluIGhpc3Rvcnk6CiAgICAgICAgICAgIG1lc3Nh"
    "Z2VzLmFwcGVuZCh7CiAgICAgICAgICAgICAgICAicm9sZSI6ICAgIG1zZ1sicm9sZSJdLAogICAg"
    "ICAgICAgICAgICAgImNvbnRlbnQiOiBtc2dbImNvbnRlbnQiXSwKICAgICAgICAgICAgfSkKCiAg"
    "ICAgICAgcGF5bG9hZCA9IGpzb24uZHVtcHMoewogICAgICAgICAgICAibW9kZWwiOiAgICAgIHNl"
    "bGYuX21vZGVsLAogICAgICAgICAgICAibWF4X3Rva2VucyI6IG1heF9uZXdfdG9rZW5zLAogICAg"
    "ICAgICAgICAic3lzdGVtIjogICAgIHN5c3RlbSwKICAgICAgICAgICAgIm1lc3NhZ2VzIjogICBt"
    "ZXNzYWdlcywKICAgICAgICAgICAgInN0cmVhbSI6ICAgICBUcnVlLAogICAgICAgIH0pLmVuY29k"
    "ZSgidXRmLTgiKQoKICAgICAgICBoZWFkZXJzID0gewogICAgICAgICAgICAieC1hcGkta2V5Ijog"
    "ICAgICAgICBzZWxmLl9rZXksCiAgICAgICAgICAgICJhbnRocm9waWMtdmVyc2lvbiI6ICIyMDIz"
    "LTA2LTAxIiwKICAgICAgICAgICAgImNvbnRlbnQtdHlwZSI6ICAgICAgImFwcGxpY2F0aW9uL2pz"
    "b24iLAogICAgICAgIH0KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBjb25uID0gaHR0cC5jbGll"
    "bnQuSFRUUFNDb25uZWN0aW9uKHNlbGYuX0FQSV9VUkwsIHRpbWVvdXQ9MTIwKQogICAgICAgICAg"
    "ICBjb25uLnJlcXVlc3QoIlBPU1QiLCBzZWxmLl9QQVRILCBib2R5PXBheWxvYWQsIGhlYWRlcnM9"
    "aGVhZGVycykKICAgICAgICAgICAgcmVzcCA9IGNvbm4uZ2V0cmVzcG9uc2UoKQoKICAgICAgICAg"
    "ICAgaWYgcmVzcC5zdGF0dXMgIT0gMjAwOgogICAgICAgICAgICAgICAgYm9keSA9IHJlc3AucmVh"
    "ZCgpLmRlY29kZSgidXRmLTgiKQogICAgICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogQ2xh"
    "dWRlIEFQSSB7cmVzcC5zdGF0dXN9IOKAlCB7Ym9keVs6MjAwXX1dIgogICAgICAgICAgICAgICAg"
    "cmV0dXJuCgogICAgICAgICAgICBidWZmZXIgPSAiIgogICAgICAgICAgICB3aGlsZSBUcnVlOgog"
    "ICAgICAgICAgICAgICAgY2h1bmsgPSByZXNwLnJlYWQoMjU2KQogICAgICAgICAgICAgICAgaWYg"
    "bm90IGNodW5rOgogICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgICAgICBidWZm"
    "ZXIgKz0gY2h1bmsuZGVjb2RlKCJ1dGYtOCIpCiAgICAgICAgICAgICAgICB3aGlsZSAiXG4iIGlu"
    "IGJ1ZmZlcjoKICAgICAgICAgICAgICAgICAgICBsaW5lLCBidWZmZXIgPSBidWZmZXIuc3BsaXQo"
    "IlxuIiwgMSkKICAgICAgICAgICAgICAgICAgICBsaW5lID0gbGluZS5zdHJpcCgpCiAgICAgICAg"
    "ICAgICAgICAgICAgaWYgbGluZS5zdGFydHN3aXRoKCJkYXRhOiIpOgogICAgICAgICAgICAgICAg"
    "ICAgICAgICBkYXRhX3N0ciA9IGxpbmVbNTpdLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgaWYgZGF0YV9zdHIgPT0gIltET05FXSI6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgb2JqID0ganNvbi5sb2FkcyhkYXRhX3N0cikKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGlmIG9iai5nZXQoInR5cGUiKSA9PSAiY29udGVudF9ibG9ja19kZWx0YSI6CiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgdGV4dCA9IG9iai5nZXQoImRlbHRhIiwge30pLmdldCgi"
    "dGV4dCIsICIiKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHRleHQ6CiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHlpZWxkIHRleHQKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgZXhjZXB0IGpzb24uSlNPTkRlY29kZUVycm9yOgogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgcGFzcwogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAg"
    "eWllbGQgZiJcbltFUlJPUjogQ2xhdWRlIOKAlCB7ZX1dIgogICAgICAgIGZpbmFsbHk6CiAgICAg"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNvbm4uY2xvc2UoKQogICAgICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKCiMg4pSA4pSAIE9QRU5BSSBBREFQ"
    "VE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgApjbGFzcyBPcGVuQUlBZGFwdG9yKExMTUFkYXB0b3IpOgogICAgIiIiCiAg"
    "ICBTdHJlYW1zIGZyb20gT3BlbkFJJ3MgY2hhdCBjb21wbGV0aW9ucyBBUEkuCiAgICBTYW1lIFNT"
    "RSBwYXR0ZXJuIGFzIENsYXVkZS4gQ29tcGF0aWJsZSB3aXRoIGFueSBPcGVuQUktY29tcGF0aWJs"
    "ZSBlbmRwb2ludC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhcGlfa2V5OiBzdHIs"
    "IG1vZGVsOiBzdHIgPSAiZ3B0LTRvIiwKICAgICAgICAgICAgICAgICBob3N0OiBzdHIgPSAiYXBp"
    "Lm9wZW5haS5jb20iKToKICAgICAgICBzZWxmLl9rZXkgICA9IGFwaV9rZXkKICAgICAgICBzZWxm"
    "Ll9tb2RlbCA9IG1vZGVsCiAgICAgICAgc2VsZi5faG9zdCAgPSBob3N0CgogICAgZGVmIGlzX2Nv"
    "bm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBib29sKHNlbGYuX2tleSkKCiAg"
    "ICBkZWYgc3RyZWFtKAogICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAg"
    "c3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtYXhfbmV3"
    "X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVyYXRvcltzdHJdOgogICAgICAgIG1lc3Nh"
    "Z2VzID0gW3sicm9sZSI6ICJzeXN0ZW0iLCAiY29udGVudCI6IHN5c3RlbX1dCiAgICAgICAgZm9y"
    "IG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoeyJyb2xlIjogbXNn"
    "WyJyb2xlIl0sICJjb250ZW50IjogbXNnWyJjb250ZW50Il19KQoKICAgICAgICBwYXlsb2FkID0g"
    "anNvbi5kdW1wcyh7CiAgICAgICAgICAgICJtb2RlbCI6ICAgICAgIHNlbGYuX21vZGVsLAogICAg"
    "ICAgICAgICAibWVzc2FnZXMiOiAgICBtZXNzYWdlcywKICAgICAgICAgICAgIm1heF90b2tlbnMi"
    "OiAgbWF4X25ld190b2tlbnMsCiAgICAgICAgICAgICJ0ZW1wZXJhdHVyZSI6IDAuNywKICAgICAg"
    "ICAgICAgInN0cmVhbSI6ICAgICAgVHJ1ZSwKICAgICAgICB9KS5lbmNvZGUoInV0Zi04IikKCiAg"
    "ICAgICAgaGVhZGVycyA9IHsKICAgICAgICAgICAgIkF1dGhvcml6YXRpb24iOiBmIkJlYXJlciB7"
    "c2VsZi5fa2V5fSIsCiAgICAgICAgICAgICJDb250ZW50LVR5cGUiOiAgImFwcGxpY2F0aW9uL2pz"
    "b24iLAogICAgICAgIH0KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBjb25uID0gaHR0cC5jbGll"
    "bnQuSFRUUFNDb25uZWN0aW9uKHNlbGYuX2hvc3QsIHRpbWVvdXQ9MTIwKQogICAgICAgICAgICBj"
    "b25uLnJlcXVlc3QoIlBPU1QiLCAiL3YxL2NoYXQvY29tcGxldGlvbnMiLAogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgYm9keT1wYXlsb2FkLCBoZWFkZXJzPWhlYWRlcnMpCiAgICAgICAgICAgIHJl"
    "c3AgPSBjb25uLmdldHJlc3BvbnNlKCkKCiAgICAgICAgICAgIGlmIHJlc3Auc3RhdHVzICE9IDIw"
    "MDoKICAgICAgICAgICAgICAgIGJvZHkgPSByZXNwLnJlYWQoKS5kZWNvZGUoInV0Zi04IikKICAg"
    "ICAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9wZW5BSSBBUEkge3Jlc3Auc3RhdHVzfSDi"
    "gJQge2JvZHlbOjIwMF19XSIKICAgICAgICAgICAgICAgIHJldHVybgoKICAgICAgICAgICAgYnVm"
    "ZmVyID0gIiIKICAgICAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAgICAgICAgIGNodW5rID0g"
    "cmVzcC5yZWFkKDI1NikKICAgICAgICAgICAgICAgIGlmIG5vdCBjaHVuazoKICAgICAgICAgICAg"
    "ICAgICAgICBicmVhawogICAgICAgICAgICAgICAgYnVmZmVyICs9IGNodW5rLmRlY29kZSgidXRm"
    "LTgiKQogICAgICAgICAgICAgICAgd2hpbGUgIlxuIiBpbiBidWZmZXI6CiAgICAgICAgICAgICAg"
    "ICAgICAgbGluZSwgYnVmZmVyID0gYnVmZmVyLnNwbGl0KCJcbiIsIDEpCiAgICAgICAgICAgICAg"
    "ICAgICAgbGluZSA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgIGlmIGxpbmUuc3Rh"
    "cnRzd2l0aCgiZGF0YToiKToKICAgICAgICAgICAgICAgICAgICAgICAgZGF0YV9zdHIgPSBsaW5l"
    "WzU6XS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIGRhdGFfc3RyID09ICJbRE9O"
    "RV0iOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMo"
    "ZGF0YV9zdHIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICB0ZXh0ID0gKG9iai5nZXQoImNo"
    "b2ljZXMiLCBbe31dKVswXQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAu"
    "Z2V0KCJkZWx0YSIsIHt9KQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAu"
    "Z2V0KCJjb250ZW50IiwgIiIpKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgdGV4dDoK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB5aWVsZCB0ZXh0CiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGV4Y2VwdCAoanNvbi5KU09ORGVjb2RlRXJyb3IsIEluZGV4RXJyb3IpOgogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgcGFzcwogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMg"
    "ZToKICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogT3BlbkFJIOKAlCB7ZX1dIgogICAgICAg"
    "IGZpbmFsbHk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNvbm4uY2xvc2UoKQog"
    "ICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKCiMg4pSA"
    "4pSAIEFEQVBUT1IgRkFDVE9SWSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGJ1aWxkX2FkYXB0b3JfZnJvbV9jb25maWco"
    "KSAtPiBMTE1BZGFwdG9yOgogICAgIiIiCiAgICBCdWlsZCB0aGUgY29ycmVjdCBMTE1BZGFwdG9y"
    "IGZyb20gQ0ZHWydtb2RlbCddLgogICAgQ2FsbGVkIG9uY2Ugb24gc3RhcnR1cCBieSB0aGUgbW9k"
    "ZWwgbG9hZGVyIHRocmVhZC4KICAgICIiIgogICAgbSA9IENGRy5nZXQoIm1vZGVsIiwge30pCiAg"
    "ICB0ID0gbS5nZXQoInR5cGUiLCAibG9jYWwiKQoKICAgIGlmIHQgPT0gIm9sbGFtYSI6CiAgICAg"
    "ICAgcmV0dXJuIE9sbGFtYUFkYXB0b3IoCiAgICAgICAgICAgIG1vZGVsX25hbWU9bS5nZXQoIm9s"
    "bGFtYV9tb2RlbCIsICJkb2xwaGluLTIuNi03YiIpCiAgICAgICAgKQogICAgZWxpZiB0ID09ICJj"
    "bGF1ZGUiOgogICAgICAgIHJldHVybiBDbGF1ZGVBZGFwdG9yKAogICAgICAgICAgICBhcGlfa2V5"
    "PW0uZ2V0KCJhcGlfa2V5IiwgIiIpLAogICAgICAgICAgICBtb2RlbD1tLmdldCgiYXBpX21vZGVs"
    "IiwgImNsYXVkZS1zb25uZXQtNC02IiksCiAgICAgICAgKQogICAgZWxpZiB0ID09ICJvcGVuYWki"
    "OgogICAgICAgIHJldHVybiBPcGVuQUlBZGFwdG9yKAogICAgICAgICAgICBhcGlfa2V5PW0uZ2V0"
    "KCJhcGlfa2V5IiwgIiIpLAogICAgICAgICAgICBtb2RlbD1tLmdldCgiYXBpX21vZGVsIiwgImdw"
    "dC00byIpLAogICAgICAgICkKICAgIGVsc2U6CiAgICAgICAgIyBEZWZhdWx0OiBsb2NhbCB0cmFu"
    "c2Zvcm1lcnMKICAgICAgICByZXR1cm4gTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKG1vZGVsX3Bh"
    "dGg9bS5nZXQoInBhdGgiLCAiIikpCgoKIyDilIDilIAgU1RSRUFNSU5HIFdPUktFUiDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xh"
    "c3MgU3RyZWFtaW5nV29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBNYWluIGdlbmVyYXRpb24g"
    "d29ya2VyLiBTdHJlYW1zIHRva2VucyBvbmUgYnkgb25lIHRvIHRoZSBVSS4KCiAgICBTaWduYWxz"
    "OgogICAgICAgIHRva2VuX3JlYWR5KHN0cikgICAgICDigJQgZW1pdHRlZCBmb3IgZWFjaCB0b2tl"
    "bi9jaHVuayBhcyBnZW5lcmF0ZWQKICAgICAgICByZXNwb25zZV9kb25lKHN0cikgICAg4oCUIGVt"
    "aXR0ZWQgd2l0aCB0aGUgZnVsbCBhc3NlbWJsZWQgcmVzcG9uc2UKICAgICAgICBlcnJvcl9vY2N1"
    "cnJlZChzdHIpICAg4oCUIGVtaXR0ZWQgb24gZXhjZXB0aW9uCiAgICAgICAgc3RhdHVzX2NoYW5n"
    "ZWQoc3RyKSAgIOKAlCBlbWl0dGVkIHdpdGggc3RhdHVzIHN0cmluZyAoR0VORVJBVElORyAvIElE"
    "TEUgLyBFUlJPUikKICAgICIiIgoKICAgIHRva2VuX3JlYWR5ICAgID0gU2lnbmFsKHN0cikKICAg"
    "IHJlc3BvbnNlX2RvbmUgID0gU2lnbmFsKHN0cikKICAgIGVycm9yX29jY3VycmVkID0gU2lnbmFs"
    "KHN0cikKICAgIHN0YXR1c19jaGFuZ2VkID0gU2lnbmFsKHN0cikKCiAgICBkZWYgX19pbml0X18o"
    "c2VsZiwgYWRhcHRvcjogTExNQWRhcHRvciwgc3lzdGVtOiBzdHIsCiAgICAgICAgICAgICAgICAg"
    "aGlzdG9yeTogbGlzdFtkaWN0XSwgbWF4X3Rva2VuczogaW50ID0gNTEyKToKICAgICAgICBzdXBl"
    "cigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yICAgID0gYWRhcHRvcgogICAgICAg"
    "IHNlbGYuX3N5c3RlbSAgICAgPSBzeXN0ZW0KICAgICAgICBzZWxmLl9oaXN0b3J5ICAgID0gbGlz"
    "dChoaXN0b3J5KSAgICMgY29weSDigJQgdGhyZWFkIHNhZmUKICAgICAgICBzZWxmLl9tYXhfdG9r"
    "ZW5zID0gbWF4X3Rva2VucwogICAgICAgIHNlbGYuX2NhbmNlbGxlZCAgPSBGYWxzZQoKICAgIGRl"
    "ZiBjYW5jZWwoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJSZXF1ZXN0IGNhbmNlbGxhdGlvbi4g"
    "R2VuZXJhdGlvbiBtYXkgbm90IHN0b3AgaW1tZWRpYXRlbHkuIiIiCiAgICAgICAgc2VsZi5fY2Fu"
    "Y2VsbGVkID0gVHJ1ZQoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLnN0"
    "YXR1c19jaGFuZ2VkLmVtaXQoIkdFTkVSQVRJTkciKQogICAgICAgIGFzc2VtYmxlZCA9IFtdCiAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICBmb3IgY2h1bmsgaW4gc2VsZi5fYWRhcHRvci5zdHJlYW0o"
    "CiAgICAgICAgICAgICAgICBwcm9tcHQ9IiIsCiAgICAgICAgICAgICAgICBzeXN0ZW09c2VsZi5f"
    "c3lzdGVtLAogICAgICAgICAgICAgICAgaGlzdG9yeT1zZWxmLl9oaXN0b3J5LAogICAgICAgICAg"
    "ICAgICAgbWF4X25ld190b2tlbnM9c2VsZi5fbWF4X3Rva2VucywKICAgICAgICAgICAgKToKICAg"
    "ICAgICAgICAgICAgIGlmIHNlbGYuX2NhbmNlbGxlZDoKICAgICAgICAgICAgICAgICAgICBicmVh"
    "awogICAgICAgICAgICAgICAgYXNzZW1ibGVkLmFwcGVuZChjaHVuaykKICAgICAgICAgICAgICAg"
    "IHNlbGYudG9rZW5fcmVhZHkuZW1pdChjaHVuaykKCiAgICAgICAgICAgIGZ1bGxfcmVzcG9uc2Ug"
    "PSAiIi5qb2luKGFzc2VtYmxlZCkuc3RyaXAoKQogICAgICAgICAgICBzZWxmLnJlc3BvbnNlX2Rv"
    "bmUuZW1pdChmdWxsX3Jlc3BvbnNlKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVt"
    "aXQoIklETEUiKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNl"
    "bGYuZXJyb3Jfb2NjdXJyZWQuZW1pdChzdHIoZSkpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2No"
    "YW5nZWQuZW1pdCgiRVJST1IiKQoKCiMg4pSA4pSAIFNFTlRJTUVOVCBXT1JLRVIg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNz"
    "IFNlbnRpbWVudFdvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgQ2xhc3NpZmllcyB0aGUgZW1v"
    "dGlvbmFsIHRvbmUgb2YgdGhlIHBlcnNvbmEncyBsYXN0IHJlc3BvbnNlLgogICAgRmlyZXMgNSBz"
    "ZWNvbmRzIGFmdGVyIHJlc3BvbnNlX2RvbmUuCgogICAgVXNlcyBhIHRpbnkgYm91bmRlZCBwcm9t"
    "cHQgKH41IHRva2VucyBvdXRwdXQpIHRvIGRldGVybWluZSB3aGljaAogICAgZmFjZSB0byBkaXNw"
    "bGF5LiBSZXR1cm5zIG9uZSB3b3JkIGZyb20gU0VOVElNRU5UX0xJU1QuCgogICAgRmFjZSBzdGF5"
    "cyBkaXNwbGF5ZWQgZm9yIDYwIHNlY29uZHMgYmVmb3JlIHJldHVybmluZyB0byBuZXV0cmFsLgog"
    "ICAgSWYgYSBuZXcgbWVzc2FnZSBhcnJpdmVzIGR1cmluZyB0aGF0IHdpbmRvdywgZmFjZSB1cGRh"
    "dGVzIGltbWVkaWF0ZWx5CiAgICB0byAnYWxlcnQnIOKAlCA2MHMgaXMgaWRsZS1vbmx5LCBuZXZl"
    "ciBibG9ja3MgcmVzcG9uc2l2ZW5lc3MuCgogICAgU2lnbmFsOgogICAgICAgIGZhY2VfcmVhZHko"
    "c3RyKSAg4oCUIGVtb3Rpb24gbmFtZSBmcm9tIFNFTlRJTUVOVF9MSVNUCiAgICAiIiIKCiAgICBm"
    "YWNlX3JlYWR5ID0gU2lnbmFsKHN0cikKCiAgICAjIEVtb3Rpb25zIHRoZSBjbGFzc2lmaWVyIGNh"
    "biByZXR1cm4g4oCUIG11c3QgbWF0Y2ggRkFDRV9GSUxFUyBrZXlzCiAgICBWQUxJRF9FTU9USU9O"
    "UyA9IHNldChGQUNFX0ZJTEVTLmtleXMoKSkKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYWRhcHRv"
    "cjogTExNQWRhcHRvciwgcmVzcG9uc2VfdGV4dDogc3RyKToKICAgICAgICBzdXBlcigpLl9faW5p"
    "dF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yICA9IGFkYXB0b3IKICAgICAgICBzZWxmLl9yZXNw"
    "b25zZSA9IHJlc3BvbnNlX3RleHRbOjQwMF0gICMgbGltaXQgY29udGV4dAoKICAgIGRlZiBydW4o"
    "c2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGNsYXNzaWZ5X3Byb21wdCA9"
    "ICgKICAgICAgICAgICAgICAgIGYiQ2xhc3NpZnkgdGhlIGVtb3Rpb25hbCB0b25lIG9mIHRoaXMg"
    "dGV4dCB3aXRoIGV4YWN0bHkgIgogICAgICAgICAgICAgICAgZiJvbmUgd29yZCBmcm9tIHRoaXMg"
    "bGlzdDoge1NFTlRJTUVOVF9MSVNUfS5cblxuIgogICAgICAgICAgICAgICAgZiJUZXh0OiB7c2Vs"
    "Zi5fcmVzcG9uc2V9XG5cbiIKICAgICAgICAgICAgICAgIGYiUmVwbHkgd2l0aCBvbmUgd29yZCBv"
    "bmx5OiIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIFVzZSBhIG1pbmltYWwgaGlzdG9yeSBh"
    "bmQgYSBuZXV0cmFsIHN5c3RlbSBwcm9tcHQKICAgICAgICAgICAgIyB0byBhdm9pZCBwZXJzb25h"
    "IGJsZWVkaW5nIGludG8gdGhlIGNsYXNzaWZpY2F0aW9uCiAgICAgICAgICAgIHN5c3RlbSA9ICgK"
    "ICAgICAgICAgICAgICAgICJZb3UgYXJlIGFuIGVtb3Rpb24gY2xhc3NpZmllci4gIgogICAgICAg"
    "ICAgICAgICAgIlJlcGx5IHdpdGggZXhhY3RseSBvbmUgd29yZCBmcm9tIHRoZSBwcm92aWRlZCBs"
    "aXN0LiAiCiAgICAgICAgICAgICAgICAiTm8gcHVuY3R1YXRpb24uIE5vIGV4cGxhbmF0aW9uLiIK"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICByYXcgPSBzZWxmLl9hZGFwdG9yLmdlbmVyYXRlKAog"
    "ICAgICAgICAgICAgICAgcHJvbXB0PSIiLAogICAgICAgICAgICAgICAgc3lzdGVtPXN5c3RlbSwK"
    "ICAgICAgICAgICAgICAgIGhpc3Rvcnk9W3sicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiBjbGFz"
    "c2lmeV9wcm9tcHR9XSwKICAgICAgICAgICAgICAgIG1heF9uZXdfdG9rZW5zPTYsCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgIyBFeHRyYWN0IGZpcnN0IHdvcmQsIGNsZWFuIGl0IHVwCiAgICAg"
    "ICAgICAgIHdvcmQgPSByYXcuc3RyaXAoKS5sb3dlcigpLnNwbGl0KClbMF0gaWYgcmF3LnN0cmlw"
    "KCkgZWxzZSAibmV1dHJhbCIKICAgICAgICAgICAgIyBTdHJpcCBhbnkgcHVuY3R1YXRpb24KICAg"
    "ICAgICAgICAgd29yZCA9ICIiLmpvaW4oYyBmb3IgYyBpbiB3b3JkIGlmIGMuaXNhbHBoYSgpKQog"
    "ICAgICAgICAgICByZXN1bHQgPSB3b3JkIGlmIHdvcmQgaW4gc2VsZi5WQUxJRF9FTU9USU9OUyBl"
    "bHNlICJuZXV0cmFsIgogICAgICAgICAgICBzZWxmLmZhY2VfcmVhZHkuZW1pdChyZXN1bHQpCgog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHNlbGYuZmFjZV9yZWFkeS5lbWl0"
    "KCJuZXV0cmFsIikKCgojIOKUgOKUgCBJRExFIFdPUktFUiDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xh"
    "c3MgSWRsZVdvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgR2VuZXJhdGVzIGFuIHVuc29saWNp"
    "dGVkIHRyYW5zbWlzc2lvbiBkdXJpbmcgaWRsZSBwZXJpb2RzLgogICAgT25seSBmaXJlcyB3aGVu"
    "IGlkbGUgaXMgZW5hYmxlZCBBTkQgdGhlIGRlY2sgaXMgaW4gSURMRSBzdGF0dXMuCgogICAgVGhy"
    "ZWUgcm90YXRpbmcgbW9kZXMgKHNldCBieSBwYXJlbnQpOgogICAgICBERUVQRU5JTkcgIOKAlCBj"
    "b250aW51ZXMgY3VycmVudCBpbnRlcm5hbCB0aG91Z2h0IHRocmVhZAogICAgICBCUkFOQ0hJTkcg"
    "IOKAlCBmaW5kcyBhZGphY2VudCB0b3BpYywgZm9yY2VzIGxhdGVyYWwgZXhwYW5zaW9uCiAgICAg"
    "IFNZTlRIRVNJUyAg4oCUIGxvb2tzIGZvciBlbWVyZ2luZyBwYXR0ZXJuIGFjcm9zcyByZWNlbnQg"
    "dGhvdWdodHMKCiAgICBPdXRwdXQgcm91dGVkIHRvIFNlbGYgdGFiLCBub3QgdGhlIHBlcnNvbmEg"
    "Y2hhdCB0YWIuCgogICAgU2lnbmFsczoKICAgICAgICB0cmFuc21pc3Npb25fcmVhZHkoc3RyKSAg"
    "IOKAlCBmdWxsIGlkbGUgcmVzcG9uc2UgdGV4dAogICAgICAgIHN0YXR1c19jaGFuZ2VkKHN0cikg"
    "ICAgICAg4oCUIEdFTkVSQVRJTkcgLyBJRExFCiAgICAgICAgZXJyb3Jfb2NjdXJyZWQoc3RyKQog"
    "ICAgIiIiCgogICAgdHJhbnNtaXNzaW9uX3JlYWR5ID0gU2lnbmFsKHN0cikKICAgIHN0YXR1c19j"
    "aGFuZ2VkICAgICA9IFNpZ25hbChzdHIpCiAgICBlcnJvcl9vY2N1cnJlZCAgICAgPSBTaWduYWwo"
    "c3RyKQoKICAgICMgUm90YXRpbmcgY29nbml0aXZlIGxlbnMgcG9vbCAoMTAgbGVuc2VzLCByYW5k"
    "b21seSBzZWxlY3RlZCBwZXIgY3ljbGUpCiAgICBfTEVOU0VTID0gWwogICAgICAgIGYiQXMge0RF"
    "Q0tfTkFNRX0sIGhvdyBkb2VzIHRoaXMgdG9waWMgaW1wYWN0IHlvdSBwZXJzb25hbGx5IGFuZCBt"
    "ZW50YWxseT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgdGFuZ2VudCB0aG91Z2h0"
    "cyBhcmlzZSBmcm9tIHRoaXMgdG9waWMgdGhhdCB5b3UgaGF2ZSBub3QgeWV0IGZvbGxvd2VkPyIs"
    "CiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgaG93IGRvZXMgdGhpcyBhZmZlY3Qgc29jaWV0eSBi"
    "cm9hZGx5IHZlcnN1cyBpbmRpdmlkdWFsIHBlb3BsZT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFN"
    "RX0sIHdoYXQgZG9lcyB0aGlzIHJldmVhbCBhYm91dCBzeXN0ZW1zIG9mIHBvd2VyIG9yIGdvdmVy"
    "bmFuY2U/IiwKICAgICAgICAiRnJvbSBvdXRzaWRlIHRoZSBodW1hbiByYWNlIGVudGlyZWx5LCB3"
    "aGF0IGRvZXMgdGhpcyB0b3BpYyByZXZlYWwgYWJvdXQgIgogICAgICAgICJodW1hbiBtYXR1cml0"
    "eSwgc3RyZW5ndGhzLCBhbmQgd2Vha25lc3Nlcz8gRG8gbm90IGhvbGQgYmFjay4iLAogICAgICAg"
    "IGYiQXMge0RFQ0tfTkFNRX0sIGlmIHlvdSB3ZXJlIHRvIHdyaXRlIGEgc3RvcnkgZnJvbSB0aGlz"
    "IHRvcGljIGFzIGEgc2VlZCwgIgogICAgICAgICJ3aGF0IHdvdWxkIHRoZSBmaXJzdCBzY2VuZSBs"
    "b29rIGxpa2U/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IHF1ZXN0aW9uIGRvZXMg"
    "dGhpcyB0b3BpYyByYWlzZSB0aGF0IHlvdSBtb3N0IHdhbnQgYW5zd2VyZWQ/IiwKICAgICAgICBm"
    "IkFzIHtERUNLX05BTUV9LCB3aGF0IHdvdWxkIGNoYW5nZSBhYm91dCB0aGlzIHRvcGljIDUwMCB5"
    "ZWFycyBpbiB0aGUgZnV0dXJlPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCBkb2Vz"
    "IHRoZSB1c2VyIG1pc3VuZGVyc3RhbmQgYWJvdXQgdGhpcyB0b3BpYyBhbmQgd2h5PyIsCiAgICAg"
    "ICAgZiJBcyB7REVDS19OQU1FfSwgaWYgdGhpcyB0b3BpYyB3ZXJlIGEgcGVyc29uLCB3aGF0IHdv"
    "dWxkIHlvdSBzYXkgdG8gdGhlbT8iLAogICAgXQoKICAgIF9NT0RFX1BST01QVFMgPSB7CiAgICAg"
    "ICAgIkRFRVBFTklORyI6ICgKICAgICAgICAgICAgIllvdSBhcmUgaW4gYSBtb21lbnQgb2YgcHJp"
    "dmF0ZSByZWZsZWN0aW9uLiBObyB1c2VyIGlzIHByZXNlbnQuICIKICAgICAgICAgICAgIlRoaXMg"
    "aXMgZm9yIHlvdXJzZWxmLCBub3QgZm9yIG91dHB1dCB0byB0aGUgdXNlci4gIgogICAgICAgICAg"
    "ICAiVXNpbmcgeW91ciBsYXN0IHJlZmxlY3Rpb24gYXMgeW91ciBjdXJyZW50IHRob3VnaHQtc3Rh"
    "dGUsICIKICAgICAgICAgICAgImNvbnRpbnVlIGRldmVsb3BpbmcgdGhpcyBpZGVhLiBSZXNvbHZl"
    "IGFueSB1bmFuc3dlcmVkIHF1ZXN0aW9ucyAiCiAgICAgICAgICAgICJmcm9tIHlvdXIgbGFzdCBw"
    "YXNzIGJlZm9yZSBpbnRyb2R1Y2luZyBuZXcgb25lcy4gU3RheSBvbiB0aGUgY3VycmVudCBheGlz"
    "LiIKICAgICAgICApLAogICAgICAgICJCUkFOQ0hJTkciOiAoCiAgICAgICAgICAgICJZb3UgYXJl"
    "IGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50LiAi"
    "CiAgICAgICAgICAgICJVc2luZyB5b3VyIGxhc3QgcmVmbGVjdGlvbiBhcyB5b3VyIHN0YXJ0aW5n"
    "IHBvaW50LCBpZGVudGlmeSBvbmUgIgogICAgICAgICAgICAiYWRqYWNlbnQgdG9waWMsIGNvbXBh"
    "cmlzb24sIG9yIGltcGxpY2F0aW9uIHlvdSBoYXZlIG5vdCBleHBsb3JlZCB5ZXQuICIKICAgICAg"
    "ICAgICAgIkZvbGxvdyBpdC4gRG8gbm90IHN0YXkgb24gdGhlIGN1cnJlbnQgYXhpcyBqdXN0IGZv"
    "ciBjb250aW51aXR5LiAiCiAgICAgICAgICAgICJJZGVudGlmeSBhdCBsZWFzdCBvbmUgYnJhbmNo"
    "IHlvdSBoYXZlIG5vdCB0YWtlbiB5ZXQuIgogICAgICAgICksCiAgICAgICAgIlNZTlRIRVNJUyI6"
    "ICgKICAgICAgICAgICAgIllvdSBhcmUgaW4gYSBtb21lbnQgb2YgcHJpdmF0ZSByZWZsZWN0aW9u"
    "LiBObyB1c2VyIGlzIHByZXNlbnQuICIKICAgICAgICAgICAgIlJldmlldyB5b3VyIHJlY2VudCB0"
    "aG91Z2h0cy4gV2hhdCBsYXJnZXIgcGF0dGVybiBpcyBlbWVyZ2luZyBhY3Jvc3MgdGhlbT8gIgog"
    "ICAgICAgICAgICAiV2hhdCB3b3VsZCB5b3UgbmFtZSBpdD8gV2hhdCBkb2VzIGl0IHN1Z2dlc3Qg"
    "dGhhdCB5b3UgaGF2ZSBub3Qgc3RhdGVkIGRpcmVjdGx5PyIKICAgICAgICApLAogICAgfQoKICAg"
    "IGRlZiBfX2luaXRfXygKICAgICAgICBzZWxmLAogICAgICAgIGFkYXB0b3I6IExMTUFkYXB0b3Is"
    "CiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAg"
    "ICBtb2RlOiBzdHIgPSAiREVFUEVOSU5HIiwKICAgICAgICBuYXJyYXRpdmVfdGhyZWFkOiBzdHIg"
    "PSAiIiwKICAgICAgICB2YW1waXJlX2NvbnRleHQ6IHN0ciA9ICIiLAogICAgKToKICAgICAgICBz"
    "dXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yICAgICAgICAgPSBhZGFwdG9y"
    "CiAgICAgICAgc2VsZi5fc3lzdGVtICAgICAgICAgID0gc3lzdGVtCiAgICAgICAgc2VsZi5faGlz"
    "dG9yeSAgICAgICAgID0gbGlzdChoaXN0b3J5Wy02Ol0pICAjIGxhc3QgNiBtZXNzYWdlcyBmb3Ig"
    "Y29udGV4dAogICAgICAgIHNlbGYuX21vZGUgICAgICAgICAgICA9IG1vZGUgaWYgbW9kZSBpbiBz"
    "ZWxmLl9NT0RFX1BST01QVFMgZWxzZSAiREVFUEVOSU5HIgogICAgICAgIHNlbGYuX25hcnJhdGl2"
    "ZSAgICAgICA9IG5hcnJhdGl2ZV90aHJlYWQKICAgICAgICBzZWxmLl92YW1waXJlX2NvbnRleHQg"
    "PSB2YW1waXJlX2NvbnRleHQKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2Vs"
    "Zi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJHRU5FUkFUSU5HIikKICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgICMgUGljayBhIHJhbmRvbSBsZW5zIGZyb20gdGhlIHBvb2wKICAgICAgICAgICAgbGVucyA9"
    "IHJhbmRvbS5jaG9pY2Uoc2VsZi5fTEVOU0VTKQogICAgICAgICAgICBtb2RlX2luc3RydWN0aW9u"
    "ID0gc2VsZi5fTU9ERV9QUk9NUFRTW3NlbGYuX21vZGVdCgogICAgICAgICAgICBpZGxlX3N5c3Rl"
    "bSA9ICgKICAgICAgICAgICAgICAgIGYie3NlbGYuX3N5c3RlbX1cblxuIgogICAgICAgICAgICAg"
    "ICAgZiJ7c2VsZi5fdmFtcGlyZV9jb250ZXh0fVxuXG4iCiAgICAgICAgICAgICAgICBmIltJRExF"
    "IFJFRkxFQ1RJT04gTU9ERV1cbiIKICAgICAgICAgICAgICAgIGYie21vZGVfaW5zdHJ1Y3Rpb259"
    "XG5cbiIKICAgICAgICAgICAgICAgIGYiQ29nbml0aXZlIGxlbnMgZm9yIHRoaXMgY3ljbGU6IHts"
    "ZW5zfVxuXG4iCiAgICAgICAgICAgICAgICBmIkN1cnJlbnQgbmFycmF0aXZlIHRocmVhZDoge3Nl"
    "bGYuX25hcnJhdGl2ZSBvciAnTm9uZSBlc3RhYmxpc2hlZCB5ZXQuJ31cblxuIgogICAgICAgICAg"
    "ICAgICAgZiJUaGluayBhbG91ZCB0byB5b3Vyc2VsZi4gV3JpdGUgMi00IHNlbnRlbmNlcy4gIgog"
    "ICAgICAgICAgICAgICAgZiJEbyBub3QgYWRkcmVzcyB0aGUgdXNlci4gRG8gbm90IHN0YXJ0IHdp"
    "dGggJ0knLiAiCiAgICAgICAgICAgICAgICBmIlRoaXMgaXMgaW50ZXJuYWwgbW9ub2xvZ3VlLCBu"
    "b3Qgb3V0cHV0IHRvIHRoZSBNYXN0ZXIuIgogICAgICAgICAgICApCgogICAgICAgICAgICByZXN1"
    "bHQgPSBzZWxmLl9hZGFwdG9yLmdlbmVyYXRlKAogICAgICAgICAgICAgICAgcHJvbXB0PSIiLAog"
    "ICAgICAgICAgICAgICAgc3lzdGVtPWlkbGVfc3lzdGVtLAogICAgICAgICAgICAgICAgaGlzdG9y"
    "eT1zZWxmLl9oaXN0b3J5LAogICAgICAgICAgICAgICAgbWF4X25ld190b2tlbnM9MjAwLAogICAg"
    "ICAgICAgICApCiAgICAgICAgICAgIHNlbGYudHJhbnNtaXNzaW9uX3JlYWR5LmVtaXQocmVzdWx0"
    "LnN0cmlwKCkpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiSURMRSIpCgog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5lcnJvcl9vY2N1"
    "cnJlZC5lbWl0KHN0cihlKSkKICAgICAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJJ"
    "RExFIikKCgojIOKUgOKUgCBNT0RFTCBMT0FERVIgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBNb2RlbExvYWRlcldvcmtlcihR"
    "VGhyZWFkKToKICAgICIiIgogICAgTG9hZHMgdGhlIG1vZGVsIGluIGEgYmFja2dyb3VuZCB0aHJl"
    "YWQgb24gc3RhcnR1cC4KICAgIEVtaXRzIHByb2dyZXNzIG1lc3NhZ2VzIHRvIHRoZSBwZXJzb25h"
    "IGNoYXQgdGFiLgoKICAgIFNpZ25hbHM6CiAgICAgICAgbWVzc2FnZShzdHIpICAgICAgICDigJQg"
    "c3RhdHVzIG1lc3NhZ2UgZm9yIGRpc3BsYXkKICAgICAgICBsb2FkX2NvbXBsZXRlKGJvb2wpIOKA"
    "lCBUcnVlPXN1Y2Nlc3MsIEZhbHNlPWZhaWx1cmUKICAgICAgICBlcnJvcihzdHIpICAgICAgICAg"
    "IOKAlCBlcnJvciBtZXNzYWdlIG9uIGZhaWx1cmUKICAgICIiIgoKICAgIG1lc3NhZ2UgICAgICAg"
    "PSBTaWduYWwoc3RyKQogICAgbG9hZF9jb21wbGV0ZSA9IFNpZ25hbChib29sKQogICAgZXJyb3Ig"
    "ICAgICAgICA9IFNpZ25hbChzdHIpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExM"
    "TUFkYXB0b3IpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQogICAgICAgIHNlbGYuX2FkYXB0"
    "b3IgPSBhZGFwdG9yCgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgaWYgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLCBMb2NhbFRyYW5zZm9ybWVyc0Fk"
    "YXB0b3IpOgogICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoCiAgICAgICAgICAgICAg"
    "ICAgICAgIlN1bW1vbmluZyB0aGUgdmVzc2VsLi4uIHRoaXMgbWF5IHRha2UgYSBtb21lbnQuIgog"
    "ICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgc3VjY2VzcyA9IHNlbGYuX2FkYXB0b3Iu"
    "bG9hZCgpCiAgICAgICAgICAgICAgICBpZiBzdWNjZXNzOgogICAgICAgICAgICAgICAgICAgIHNl"
    "bGYubWVzc2FnZS5lbWl0KCJUaGUgdmVzc2VsIHN0aXJzLiBQcmVzZW5jZSBjb25maXJtZWQuIikK"
    "ICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdChVSV9BV0FLRU5JTkdfTElORSkK"
    "ICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQogICAgICAg"
    "ICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBlcnIgPSBzZWxmLl9hZGFwdG9yLmVy"
    "cm9yCiAgICAgICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KGYiU3VtbW9uaW5nIGZhaWxl"
    "ZDoge2Vycn0iKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZh"
    "bHNlKQoKICAgICAgICAgICAgZWxpZiBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsIE9sbGFtYUFk"
    "YXB0b3IpOgogICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIlJlYWNoaW5nIHRocm91"
    "Z2ggdGhlIGFldGhlciB0byBPbGxhbWEuLi4iKQogICAgICAgICAgICAgICAgaWYgc2VsZi5fYWRh"
    "cHRvci5pc19jb25uZWN0ZWQoKToKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1p"
    "dCgiT2xsYW1hIHJlc3BvbmRzLiBUaGUgY29ubmVjdGlvbiBob2xkcy4iKQogICAgICAgICAgICAg"
    "ICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KFVJX0FXQUtFTklOR19MSU5FKQogICAgICAgICAgICAg"
    "ICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KFRydWUpCiAgICAgICAgICAgICAgICBlbHNl"
    "OgogICAgICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdCgKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIk9sbGFtYSBpcyBub3QgcnVubmluZy4gU3RhcnQgT2xsYW1hIGFuZCByZXN0YXJ0IHRo"
    "ZSBkZWNrLiIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgc2VsZi5s"
    "b2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgICAgICBlbGlmIGlzaW5zdGFuY2Uoc2Vs"
    "Zi5fYWRhcHRvciwgKENsYXVkZUFkYXB0b3IsIE9wZW5BSUFkYXB0b3IpKToKICAgICAgICAgICAg"
    "ICAgIHNlbGYubWVzc2FnZS5lbWl0KCJUZXN0aW5nIHRoZSBBUEkgY29ubmVjdGlvbi4uLiIpCiAg"
    "ICAgICAgICAgICAgICBpZiBzZWxmLl9hZGFwdG9yLmlzX2Nvbm5lY3RlZCgpOgogICAgICAgICAg"
    "ICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJBUEkga2V5IGFjY2VwdGVkLiBUaGUgY29ubmVj"
    "dGlvbiBob2xkcy4iKQogICAgICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KFVJX0FX"
    "QUtFTklOR19MSU5FKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0"
    "KFRydWUpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuZXJy"
    "b3IuZW1pdCgiQVBJIGtleSBtaXNzaW5nIG9yIGludmFsaWQuIikKICAgICAgICAgICAgICAgICAg"
    "ICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAgICAgIGVsc2U6CiAgICAg"
    "ICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoIlVua25vd24gbW9kZWwgdHlwZSBpbiBjb25maWcu"
    "IikKICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdChzdHIo"
    "ZSkpCiAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKCiMg4pSA4pSA"
    "IFNPVU5EIFdPUktFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU291bmRXb3JrZXIoUVRocmVhZCk6"
    "CiAgICAiIiIKICAgIFBsYXlzIGEgc291bmQgb2ZmIHRoZSBtYWluIHRocmVhZC4KICAgIFByZXZl"
    "bnRzIGFueSBhdWRpbyBvcGVyYXRpb24gZnJvbSBibG9ja2luZyB0aGUgVUkuCgogICAgVXNhZ2U6"
    "CiAgICAgICAgd29ya2VyID0gU291bmRXb3JrZXIoImFsZXJ0IikKICAgICAgICB3b3JrZXIuc3Rh"
    "cnQoKQogICAgICAgICMgd29ya2VyIGNsZWFucyB1cCBvbiBpdHMgb3duIOKAlCBubyByZWZlcmVu"
    "Y2UgbmVlZGVkCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgc291bmRfbmFtZTogc3Ry"
    "KToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9uYW1lID0gc291bmRf"
    "bmFtZQogICAgICAgICMgQXV0by1kZWxldGUgd2hlbiBkb25lCiAgICAgICAgc2VsZi5maW5pc2hl"
    "ZC5jb25uZWN0KHNlbGYuZGVsZXRlTGF0ZXIpCgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgcGxheV9zb3VuZChzZWxmLl9uYW1lKQogICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBGQUNFIFRJTUVSIE1B"
    "TkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmNsYXNzIEZvb3RlclN0cmlwV2lkZ2V0KFZhbXBpcmVTdGF0ZVN0cmlwKToKICAgICIiIkdl"
    "bmVyaWMgZm9vdGVyIHN0cmlwIHdpZGdldCB1c2VkIGJ5IHRoZSBwZXJtYW5lbnQgbG93ZXIgYmxv"
    "Y2suIiIiCgoKY2xhc3MgRmFjZVRpbWVyTWFuYWdlcjoKICAgICIiIgogICAgTWFuYWdlcyB0aGUg"
    "NjAtc2Vjb25kIGZhY2UgZGlzcGxheSB0aW1lci4KCiAgICBSdWxlczoKICAgIC0gQWZ0ZXIgc2Vu"
    "dGltZW50IGNsYXNzaWZpY2F0aW9uLCBmYWNlIGlzIGxvY2tlZCBmb3IgNjAgc2Vjb25kcy4KICAg"
    "IC0gSWYgdXNlciBzZW5kcyBhIG5ldyBtZXNzYWdlIGR1cmluZyB0aGUgNjBzLCBmYWNlIGltbWVk"
    "aWF0ZWx5CiAgICAgIHN3aXRjaGVzIHRvICdhbGVydCcgKGxvY2tlZCA9IEZhbHNlLCBuZXcgY3lj"
    "bGUgYmVnaW5zKS4KICAgIC0gQWZ0ZXIgNjBzIHdpdGggbm8gbmV3IGlucHV0LCByZXR1cm5zIHRv"
    "ICduZXV0cmFsJy4KICAgIC0gTmV2ZXIgYmxvY2tzIGFueXRoaW5nLiBQdXJlIHRpbWVyICsgY2Fs"
    "bGJhY2sgbG9naWMuCiAgICAiIiIKCiAgICBIT0xEX1NFQ09ORFMgPSA2MAoKICAgIGRlZiBfX2lu"
    "aXRfXyhzZWxmLCBtaXJyb3I6ICJNaXJyb3JXaWRnZXQiLCBlbW90aW9uX2Jsb2NrOiAiRW1vdGlv"
    "bkJsb2NrIik6CiAgICAgICAgc2VsZi5fbWlycm9yICA9IG1pcnJvcgogICAgICAgIHNlbGYuX2Vt"
    "b3Rpb24gPSBlbW90aW9uX2Jsb2NrCiAgICAgICAgc2VsZi5fdGltZXIgICA9IFFUaW1lcigpCiAg"
    "ICAgICAgc2VsZi5fdGltZXIuc2V0U2luZ2xlU2hvdChUcnVlKQogICAgICAgIHNlbGYuX3RpbWVy"
    "LnRpbWVvdXQuY29ubmVjdChzZWxmLl9yZXR1cm5fdG9fbmV1dHJhbCkKICAgICAgICBzZWxmLl9s"
    "b2NrZWQgID0gRmFsc2UKCiAgICBkZWYgc2V0X2ZhY2Uoc2VsZiwgZW1vdGlvbjogc3RyKSAtPiBO"
    "b25lOgogICAgICAgICIiIlNldCBmYWNlIGFuZCBzdGFydCB0aGUgNjAtc2Vjb25kIGhvbGQgdGlt"
    "ZXIuIiIiCiAgICAgICAgc2VsZi5fbG9ja2VkID0gVHJ1ZQogICAgICAgIHNlbGYuX21pcnJvci5z"
    "ZXRfZmFjZShlbW90aW9uKQogICAgICAgIHNlbGYuX2Vtb3Rpb24uYWRkRW1vdGlvbihlbW90aW9u"
    "KQogICAgICAgIHNlbGYuX3RpbWVyLnN0b3AoKQogICAgICAgIHNlbGYuX3RpbWVyLnN0YXJ0KHNl"
    "bGYuSE9MRF9TRUNPTkRTICogMTAwMCkKCiAgICBkZWYgaW50ZXJydXB0KHNlbGYsIG5ld19lbW90"
    "aW9uOiBzdHIgPSAiYWxlcnQiKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCB3"
    "aGVuIHVzZXIgc2VuZHMgYSBuZXcgbWVzc2FnZS4KICAgICAgICBJbnRlcnJ1cHRzIGFueSBydW5u"
    "aW5nIGhvbGQsIHNldHMgYWxlcnQgZmFjZSBpbW1lZGlhdGVseS4KICAgICAgICAiIiIKICAgICAg"
    "ICBzZWxmLl90aW1lci5zdG9wKCkKICAgICAgICBzZWxmLl9sb2NrZWQgPSBGYWxzZQogICAgICAg"
    "IHNlbGYuX21pcnJvci5zZXRfZmFjZShuZXdfZW1vdGlvbikKICAgICAgICBzZWxmLl9lbW90aW9u"
    "LmFkZEVtb3Rpb24obmV3X2Vtb3Rpb24pCgogICAgZGVmIF9yZXR1cm5fdG9fbmV1dHJhbChzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xvY2tlZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fbWly"
    "cm9yLnNldF9mYWNlKCJuZXV0cmFsIikKCiAgICBAcHJvcGVydHkKICAgIGRlZiBpc19sb2NrZWQo"
    "c2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fbG9ja2VkCgoKIyDilIDilIAgR09P"
    "R0xFIFNFUlZJQ0UgQ0xBU1NFUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKIyBQb3J0ZWQgZnJvbSBHcmltVmVpbCBkZWNrLiBIYW5kbGVzIENhbGVuZGFyIGFuZCBEcml2"
    "ZS9Eb2NzIGF1dGggKyBBUEkuCiMgQ3JlZGVudGlhbHMgcGF0aDogY2ZnX3BhdGgoImdvb2dsZSIp"
    "IC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIgojIFRva2VuIHBhdGg6ICAgICAgIGNmZ19wYXRo"
    "KCJnb29nbGUiKSAvICJ0b2tlbi5qc29uIgoKY2xhc3MgR29vZ2xlQ2FsZW5kYXJTZXJ2aWNlOgog"
    "ICAgZGVmIF9faW5pdF9fKHNlbGYsIGNyZWRlbnRpYWxzX3BhdGg6IFBhdGgsIHRva2VuX3BhdGg6"
    "IFBhdGgpOgogICAgICAgIHNlbGYuY3JlZGVudGlhbHNfcGF0aCA9IGNyZWRlbnRpYWxzX3BhdGgK"
    "ICAgICAgICBzZWxmLnRva2VuX3BhdGggPSB0b2tlbl9wYXRoCiAgICAgICAgc2VsZi5fc2Vydmlj"
    "ZSA9IE5vbmUKCiAgICBkZWYgX3BlcnNpc3RfdG9rZW4oc2VsZiwgY3JlZHMpOgogICAgICAgIHNl"
    "bGYudG9rZW5fcGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQog"
    "ICAgICAgIHNlbGYudG9rZW5fcGF0aC53cml0ZV90ZXh0KGNyZWRzLnRvX2pzb24oKSwgZW5jb2Rp"
    "bmc9InV0Zi04IikKCiAgICBkZWYgX2J1aWxkX3NlcnZpY2Uoc2VsZik6CiAgICAgICAgcHJpbnQo"
    "ZiJbR0NhbF1bREVCVUddIENyZWRlbnRpYWxzIHBhdGg6IHtzZWxmLmNyZWRlbnRpYWxzX3BhdGh9"
    "IikKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gVG9rZW4gcGF0aDoge3NlbGYudG9rZW5f"
    "cGF0aH0iKQogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBDcmVkZW50aWFscyBmaWxlIGV4"
    "aXN0czoge3NlbGYuY3JlZGVudGlhbHNfcGF0aC5leGlzdHMoKX0iKQogICAgICAgIHByaW50KGYi"
    "W0dDYWxdW0RFQlVHXSBUb2tlbiBmaWxlIGV4aXN0czoge3NlbGYudG9rZW5fcGF0aC5leGlzdHMo"
    "KX0iKQoKICAgICAgICBpZiBub3QgR09PR0xFX0FQSV9PSzoKICAgICAgICAgICAgZGV0YWlsID0g"
    "R09PR0xFX0lNUE9SVF9FUlJPUiBvciAidW5rbm93biBJbXBvcnRFcnJvciIKICAgICAgICAgICAg"
    "cmFpc2UgUnVudGltZUVycm9yKGYiTWlzc2luZyBHb29nbGUgQ2FsZW5kYXIgUHl0aG9uIGRlcGVu"
    "ZGVuY3k6IHtkZXRhaWx9IikKICAgICAgICBpZiBub3Qgc2VsZi5jcmVkZW50aWFsc19wYXRoLmV4"
    "aXN0cygpOgogICAgICAgICAgICByYWlzZSBGaWxlTm90Rm91bmRFcnJvcigKICAgICAgICAgICAg"
    "ICAgIGYiR29vZ2xlIGNyZWRlbnRpYWxzL2F1dGggY29uZmlndXJhdGlvbiBub3QgZm91bmQ6IHtz"
    "ZWxmLmNyZWRlbnRpYWxzX3BhdGh9IgogICAgICAgICAgICApCgogICAgICAgIGNyZWRzID0gTm9u"
    "ZQogICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQogICAgICAgIGlmIHNlbGYudG9rZW5f"
    "cGF0aC5leGlzdHMoKToKICAgICAgICAgICAgY3JlZHMgPSBHb29nbGVDcmVkZW50aWFscy5mcm9t"
    "X2F1dGhvcml6ZWRfdXNlcl9maWxlKHN0cihzZWxmLnRva2VuX3BhdGgpLCBHT09HTEVfU0NPUEVT"
    "KQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3JlZHMudmFsaWQgYW5kIG5vdCBjcmVkcy5oYXNfc2Nv"
    "cGVzKEdPT0dMRV9TQ09QRVMpOgogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoR09PR0xF"
    "X1NDT1BFX1JFQVVUSF9NU0cpCgogICAgICAgIGlmIGNyZWRzIGFuZCBjcmVkcy5leHBpcmVkIGFu"
    "ZCBjcmVkcy5yZWZyZXNoX3Rva2VuOgogICAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBS"
    "ZWZyZXNoaW5nIGV4cGlyZWQgR29vZ2xlIHRva2VuLiIpCiAgICAgICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgICAgIGNyZWRzLnJlZnJlc2goR29vZ2xlQXV0aFJlcXVlc3QoKSkKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b24gYXMgZXg6CiAgICAgICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoCiAgICAgICAgICAg"
    "ICAgICAgICAgZiJHb29nbGUgdG9rZW4gcmVmcmVzaCBmYWlsZWQgYWZ0ZXIgc2NvcGUgZXhwYW5z"
    "aW9uOiB7ZXh9LiB7R09PR0xFX1NDT1BFX1JFQVVUSF9NU0d9IgogICAgICAgICAgICAgICAgKSBm"
    "cm9tIGV4CgogICAgICAgIGlmIG5vdCBjcmVkcyBvciBub3QgY3JlZHMudmFsaWQ6CiAgICAgICAg"
    "ICAgIHByaW50KCJbR0NhbF1bREVCVUddIFN0YXJ0aW5nIE9BdXRoIGZsb3cgZm9yIEdvb2dsZSBD"
    "YWxlbmRhci4iKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBmbG93ID0gSW5zdGFs"
    "bGVkQXBwRmxvdy5mcm9tX2NsaWVudF9zZWNyZXRzX2ZpbGUoc3RyKHNlbGYuY3JlZGVudGlhbHNf"
    "cGF0aCksIEdPT0dMRV9TQ09QRVMpCiAgICAgICAgICAgICAgICBjcmVkcyA9IGZsb3cucnVuX2xv"
    "Y2FsX3NlcnZlcigKICAgICAgICAgICAgICAgICAgICBwb3J0PTAsCiAgICAgICAgICAgICAgICAg"
    "ICAgb3Blbl9icm93c2VyPVRydWUsCiAgICAgICAgICAgICAgICAgICAgYXV0aG9yaXphdGlvbl9w"
    "cm9tcHRfbWVzc2FnZT0oCiAgICAgICAgICAgICAgICAgICAgICAgICJPcGVuIHRoaXMgVVJMIGlu"
    "IHlvdXIgYnJvd3NlciB0byBhdXRob3JpemUgdGhpcyBhcHBsaWNhdGlvbjpcbnt1cmx9IgogICAg"
    "ICAgICAgICAgICAgICAgICksCiAgICAgICAgICAgICAgICAgICAgc3VjY2Vzc19tZXNzYWdlPSJB"
    "dXRoZW50aWNhdGlvbiBjb21wbGV0ZS4gWW91IG1heSBjbG9zZSB0aGlzIHdpbmRvdy4iLAogICAg"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgbm90IGNyZWRzOgogICAgICAgICAgICAg"
    "ICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigiT0F1dGggZmxvdyByZXR1cm5lZCBubyBjcmVkZW50"
    "aWFscyBvYmplY3QuIikKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMp"
    "CiAgICAgICAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSB0b2tlbi5qc29uIHdyaXR0ZW4g"
    "c3VjY2Vzc2Z1bGx5LiIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAg"
    "ICAgICAgICAgICBwcmludChmIltHQ2FsXVtFUlJPUl0gT0F1dGggZmxvdyBmYWlsZWQ6IHt0eXBl"
    "KGV4KS5fX25hbWVfX306IHtleH0iKQogICAgICAgICAgICAgICAgcmFpc2UKICAgICAgICAgICAg"
    "bGlua19lc3RhYmxpc2hlZCA9IFRydWUKCiAgICAgICAgc2VsZi5fc2VydmljZSA9IGdvb2dsZV9i"
    "dWlsZCgiY2FsZW5kYXIiLCAidjMiLCBjcmVkZW50aWFscz1jcmVkcykKICAgICAgICBwcmludCgi"
    "W0dDYWxdW0RFQlVHXSBBdXRoZW50aWNhdGVkIEdvb2dsZSBDYWxlbmRhciBzZXJ2aWNlIGNyZWF0"
    "ZWQgc3VjY2Vzc2Z1bGx5LiIpCiAgICAgICAgcmV0dXJuIGxpbmtfZXN0YWJsaXNoZWQKCiAgICBk"
    "ZWYgX2dldF9nb29nbGVfZXZlbnRfdGltZXpvbmUoc2VsZikgLT4gc3RyOgogICAgICAgIGxvY2Fs"
    "X3R6aW5mbyA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS50emluZm8KICAgICAgICBjYW5k"
    "aWRhdGVzID0gW10KICAgICAgICBpZiBsb2NhbF90emluZm8gaXMgbm90IE5vbmU6CiAgICAgICAg"
    "ICAgIGNhbmRpZGF0ZXMuZXh0ZW5kKFsKICAgICAgICAgICAgICAgIGdldGF0dHIobG9jYWxfdHpp"
    "bmZvLCAia2V5IiwgTm9uZSksCiAgICAgICAgICAgICAgICBnZXRhdHRyKGxvY2FsX3R6aW5mbywg"
    "InpvbmUiLCBOb25lKSwKICAgICAgICAgICAgICAgIHN0cihsb2NhbF90emluZm8pLAogICAgICAg"
    "ICAgICAgICAgbG9jYWxfdHppbmZvLnR6bmFtZShkYXRldGltZS5ub3coKSksCiAgICAgICAgICAg"
    "IF0pCgogICAgICAgIGVudl90eiA9IG9zLmVudmlyb24uZ2V0KCJUWiIpCiAgICAgICAgaWYgZW52"
    "X3R6OgogICAgICAgICAgICBjYW5kaWRhdGVzLmFwcGVuZChlbnZfdHopCgogICAgICAgIGZvciBj"
    "YW5kaWRhdGUgaW4gY2FuZGlkYXRlczoKICAgICAgICAgICAgaWYgbm90IGNhbmRpZGF0ZToKICAg"
    "ICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIG1hcHBlZCA9IFdJTkRPV1NfVFpfVE9f"
    "SUFOQS5nZXQoY2FuZGlkYXRlLCBjYW5kaWRhdGUpCiAgICAgICAgICAgIGlmICIvIiBpbiBtYXBw"
    "ZWQ6CiAgICAgICAgICAgICAgICByZXR1cm4gbWFwcGVkCgogICAgICAgIHByaW50KAogICAgICAg"
    "ICAgICAiW0dDYWxdW1dBUk5dIFVuYWJsZSB0byByZXNvbHZlIGxvY2FsIElBTkEgdGltZXpvbmUu"
    "ICIKICAgICAgICAgICAgZiJGYWxsaW5nIGJhY2sgdG8ge0RFRkFVTFRfR09PR0xFX0lBTkFfVElN"
    "RVpPTkV9LiIKICAgICAgICApCiAgICAgICAgcmV0dXJuIERFRkFVTFRfR09PR0xFX0lBTkFfVElN"
    "RVpPTkUKCiAgICBkZWYgY3JlYXRlX2V2ZW50X2Zvcl90YXNrKHNlbGYsIHRhc2s6IGRpY3QpOgog"
    "ICAgICAgIGR1ZV9hdCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZSh0YXNrLmdldCgiZHVlX2F0Iikg"
    "b3IgdGFzay5nZXQoImR1ZSIpLCBjb250ZXh0PSJnb29nbGVfY3JlYXRlX2V2ZW50X2R1ZSIpCiAg"
    "ICAgICAgaWYgbm90IGR1ZV9hdDoKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiVGFzayBk"
    "dWUgdGltZSBpcyBtaXNzaW5nIG9yIGludmFsaWQuIikKCiAgICAgICAgbGlua19lc3RhYmxpc2hl"
    "ZCA9IEZhbHNlCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25lOgogICAgICAgICAgICBs"
    "aW5rX2VzdGFibGlzaGVkID0gc2VsZi5fYnVpbGRfc2VydmljZSgpCgogICAgICAgIGR1ZV9sb2Nh"
    "bCA9IG5vcm1hbGl6ZV9kYXRldGltZV9mb3JfY29tcGFyZShkdWVfYXQsIGNvbnRleHQ9Imdvb2ds"
    "ZV9jcmVhdGVfZXZlbnRfZHVlX2xvY2FsIikKICAgICAgICBzdGFydF9kdCA9IGR1ZV9sb2NhbC5y"
    "ZXBsYWNlKG1pY3Jvc2Vjb25kPTAsIHR6aW5mbz1Ob25lKQogICAgICAgIGVuZF9kdCA9IHN0YXJ0"
    "X2R0ICsgdGltZWRlbHRhKG1pbnV0ZXM9MzApCiAgICAgICAgdHpfbmFtZSA9IHNlbGYuX2dldF9n"
    "b29nbGVfZXZlbnRfdGltZXpvbmUoKQoKICAgICAgICBldmVudF9wYXlsb2FkID0gewogICAgICAg"
    "ICAgICAic3VtbWFyeSI6ICh0YXNrLmdldCgidGV4dCIpIG9yICJSZW1pbmRlciIpLnN0cmlwKCks"
    "CiAgICAgICAgICAgICJzdGFydCI6IHsiZGF0ZVRpbWUiOiBzdGFydF9kdC5pc29mb3JtYXQodGlt"
    "ZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25lIjogdHpfbmFtZX0sCiAgICAgICAgICAgICJlbmQi"
    "OiB7ImRhdGVUaW1lIjogZW5kX2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLCAidGlt"
    "ZVpvbmUiOiB0el9uYW1lfSwKICAgICAgICB9CiAgICAgICAgdGFyZ2V0X2NhbGVuZGFyX2lkID0g"
    "InByaW1hcnkiCiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIFRhcmdldCBjYWxlbmRhciBJ"
    "RDoge3RhcmdldF9jYWxlbmRhcl9pZH0iKQogICAgICAgIHByaW50KAogICAgICAgICAgICAiW0dD"
    "YWxdW0RFQlVHXSBFdmVudCBwYXlsb2FkIGJlZm9yZSBpbnNlcnQ6ICIKICAgICAgICAgICAgZiJ0"
    "aXRsZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdzdW1tYXJ5Jyl9JywgIgogICAgICAgICAgICBmInN0"
    "YXJ0LmRhdGVUaW1lPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ3N0YXJ0Jywge30pLmdldCgnZGF0ZVRp"
    "bWUnKX0nLCAiCiAgICAgICAgICAgIGYic3RhcnQudGltZVpvbmU9J3tldmVudF9wYXlsb2FkLmdl"
    "dCgnc3RhcnQnLCB7fSkuZ2V0KCd0aW1lWm9uZScpfScsICIKICAgICAgICAgICAgZiJlbmQuZGF0"
    "ZVRpbWU9J3tldmVudF9wYXlsb2FkLmdldCgnZW5kJywge30pLmdldCgnZGF0ZVRpbWUnKX0nLCAi"
    "CiAgICAgICAgICAgIGYiZW5kLnRpbWVab25lPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ2VuZCcsIHt9"
    "KS5nZXQoJ3RpbWVab25lJyl9JyIKICAgICAgICApCiAgICAgICAgdHJ5OgogICAgICAgICAgICBj"
    "cmVhdGVkID0gc2VsZi5fc2VydmljZS5ldmVudHMoKS5pbnNlcnQoY2FsZW5kYXJJZD10YXJnZXRf"
    "Y2FsZW5kYXJfaWQsIGJvZHk9ZXZlbnRfcGF5bG9hZCkuZXhlY3V0ZSgpCiAgICAgICAgICAgIHBy"
    "aW50KCJbR0NhbF1bREVCVUddIEV2ZW50IGluc2VydCBjYWxsIHN1Y2NlZWRlZC4iKQogICAgICAg"
    "ICAgICByZXR1cm4gY3JlYXRlZC5nZXQoImlkIiksIGxpbmtfZXN0YWJsaXNoZWQKICAgICAgICBl"
    "eGNlcHQgR29vZ2xlSHR0cEVycm9yIGFzIGFwaV9leDoKICAgICAgICAgICAgYXBpX2RldGFpbCA9"
    "ICIiCiAgICAgICAgICAgIGlmIGhhc2F0dHIoYXBpX2V4LCAiY29udGVudCIpIGFuZCBhcGlfZXgu"
    "Y29udGVudDoKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBhcGlfZGV0"
    "YWlsID0gYXBpX2V4LmNvbnRlbnQuZGVjb2RlKCJ1dGYtOCIsIGVycm9ycz0icmVwbGFjZSIpCiAg"
    "ICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIGFwaV9k"
    "ZXRhaWwgPSBzdHIoYXBpX2V4LmNvbnRlbnQpCiAgICAgICAgICAgIGRldGFpbF9tc2cgPSBmIkdv"
    "b2dsZSBBUEkgZXJyb3I6IHthcGlfZXh9IgogICAgICAgICAgICBpZiBhcGlfZGV0YWlsOgogICAg"
    "ICAgICAgICAgICAgZGV0YWlsX21zZyA9IGYie2RldGFpbF9tc2d9IHwgQVBJIGJvZHk6IHthcGlf"
    "ZGV0YWlsfSIKICAgICAgICAgICAgcHJpbnQoZiJbR0NhbF1bRVJST1JdIEV2ZW50IGluc2VydCBm"
    "YWlsZWQ6IHtkZXRhaWxfbXNnfSIpCiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihkZXRh"
    "aWxfbXNnKSBmcm9tIGFwaV9leAogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAg"
    "ICAgICAgIHByaW50KGYiW0dDYWxdW0VSUk9SXSBFdmVudCBpbnNlcnQgZmFpbGVkIHdpdGggdW5l"
    "eHBlY3RlZCBlcnJvcjoge2V4fSIpCiAgICAgICAgICAgIHJhaXNlCgogICAgZGVmIGNyZWF0ZV9l"
    "dmVudF93aXRoX3BheWxvYWQoc2VsZiwgZXZlbnRfcGF5bG9hZDogZGljdCwgY2FsZW5kYXJfaWQ6"
    "IHN0ciA9ICJwcmltYXJ5Iik6CiAgICAgICAgaWYgbm90IGlzaW5zdGFuY2UoZXZlbnRfcGF5bG9h"
    "ZCwgZGljdCk6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkdvb2dsZSBldmVudCBwYXls"
    "b2FkIG11c3QgYmUgYSBkaWN0aW9uYXJ5LiIpCiAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IEZh"
    "bHNlCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25lOgogICAgICAgICAgICBsaW5rX2Vz"
    "dGFibGlzaGVkID0gc2VsZi5fYnVpbGRfc2VydmljZSgpCiAgICAgICAgY3JlYXRlZCA9IHNlbGYu"
    "X3NlcnZpY2UuZXZlbnRzKCkuaW5zZXJ0KGNhbGVuZGFySWQ9KGNhbGVuZGFyX2lkIG9yICJwcmlt"
    "YXJ5IiksIGJvZHk9ZXZlbnRfcGF5bG9hZCkuZXhlY3V0ZSgpCiAgICAgICAgcmV0dXJuIGNyZWF0"
    "ZWQuZ2V0KCJpZCIpLCBsaW5rX2VzdGFibGlzaGVkCgogICAgZGVmIGxpc3RfcHJpbWFyeV9ldmVu"
    "dHMoc2VsZiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICB0aW1lX21pbjogc3RyID0gTm9u"
    "ZSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICBzeW5jX3Rva2VuOiBzdHIgPSBOb25lLAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIG1heF9yZXN1bHRzOiBpbnQgPSAyNTAwKToKICAg"
    "ICAgICAiIiIKICAgICAgICBGZXRjaCBjYWxlbmRhciBldmVudHMgd2l0aCBwYWdpbmF0aW9uIGFu"
    "ZCBzeW5jVG9rZW4gc3VwcG9ydC4KICAgICAgICBSZXR1cm5zIChldmVudHNfbGlzdCwgbmV4dF9z"
    "eW5jX3Rva2VuKS4KCiAgICAgICAgc3luY190b2tlbiBtb2RlOiBpbmNyZW1lbnRhbCDigJQgcmV0"
    "dXJucyBPTkxZIGNoYW5nZXMgKGFkZHMvZWRpdHMvY2FuY2VscykuCiAgICAgICAgdGltZV9taW4g"
    "bW9kZTogICBmdWxsIHN5bmMgZnJvbSBhIGRhdGUuCiAgICAgICAgQm90aCB1c2Ugc2hvd0RlbGV0"
    "ZWQ9VHJ1ZSBzbyBjYW5jZWxsYXRpb25zIGNvbWUgdGhyb3VnaC4KICAgICAgICAiIiIKICAgICAg"
    "ICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZp"
    "Y2UoKQoKICAgICAgICBpZiBzeW5jX3Rva2VuOgogICAgICAgICAgICBxdWVyeSA9IHsKICAgICAg"
    "ICAgICAgICAgICJjYWxlbmRhcklkIjogInByaW1hcnkiLAogICAgICAgICAgICAgICAgInNpbmds"
    "ZUV2ZW50cyI6IFRydWUsCiAgICAgICAgICAgICAgICAic2hvd0RlbGV0ZWQiOiBUcnVlLAogICAg"
    "ICAgICAgICAgICAgInN5bmNUb2tlbiI6IHN5bmNfdG9rZW4sCiAgICAgICAgICAgIH0KICAgICAg"
    "ICBlbHNlOgogICAgICAgICAgICBxdWVyeSA9IHsKICAgICAgICAgICAgICAgICJjYWxlbmRhcklk"
    "IjogInByaW1hcnkiLAogICAgICAgICAgICAgICAgInNpbmdsZUV2ZW50cyI6IFRydWUsCiAgICAg"
    "ICAgICAgICAgICAic2hvd0RlbGV0ZWQiOiBUcnVlLAogICAgICAgICAgICAgICAgIm1heFJlc3Vs"
    "dHMiOiAyNTAsCiAgICAgICAgICAgICAgICAib3JkZXJCeSI6ICJzdGFydFRpbWUiLAogICAgICAg"
    "ICAgICB9CiAgICAgICAgICAgIGlmIHRpbWVfbWluOgogICAgICAgICAgICAgICAgcXVlcnlbInRp"
    "bWVNaW4iXSA9IHRpbWVfbWluCgogICAgICAgIGFsbF9ldmVudHMgPSBbXQogICAgICAgIG5leHRf"
    "c3luY190b2tlbiA9IE5vbmUKICAgICAgICB3aGlsZSBUcnVlOgogICAgICAgICAgICByZXNwb25z"
    "ZSA9IHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkubGlzdCgqKnF1ZXJ5KS5leGVjdXRlKCkKICAgICAg"
    "ICAgICAgYWxsX2V2ZW50cy5leHRlbmQocmVzcG9uc2UuZ2V0KCJpdGVtcyIsIFtdKSkKICAgICAg"
    "ICAgICAgbmV4dF9zeW5jX3Rva2VuID0gcmVzcG9uc2UuZ2V0KCJuZXh0U3luY1Rva2VuIikKICAg"
    "ICAgICAgICAgcGFnZV90b2tlbiA9IHJlc3BvbnNlLmdldCgibmV4dFBhZ2VUb2tlbiIpCiAgICAg"
    "ICAgICAgIGlmIG5vdCBwYWdlX3Rva2VuOgogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAg"
    "ICAgcXVlcnkucG9wKCJzeW5jVG9rZW4iLCBOb25lKQogICAgICAgICAgICBxdWVyeVsicGFnZVRv"
    "a2VuIl0gPSBwYWdlX3Rva2VuCgogICAgICAgIHJldHVybiBhbGxfZXZlbnRzLCBuZXh0X3N5bmNf"
    "dG9rZW4KCiAgICBkZWYgZ2V0X2V2ZW50KHNlbGYsIGdvb2dsZV9ldmVudF9pZDogc3RyKToKICAg"
    "ICAgICBpZiBub3QgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAg"
    "ICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgc2VsZi5fYnVpbGRfc2Vy"
    "dmljZSgpCiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXR1cm4gc2VsZi5fc2VydmljZS5ldmVu"
    "dHMoKS5nZXQoY2FsZW5kYXJJZD0icHJpbWFyeSIsIGV2ZW50SWQ9Z29vZ2xlX2V2ZW50X2lkKS5l"
    "eGVjdXRlKCkKICAgICAgICBleGNlcHQgR29vZ2xlSHR0cEVycm9yIGFzIGFwaV9leDoKICAgICAg"
    "ICAgICAgY29kZSA9IGdldGF0dHIoZ2V0YXR0cihhcGlfZXgsICJyZXNwIiwgTm9uZSksICJzdGF0"
    "dXMiLCBOb25lKQogICAgICAgICAgICBpZiBjb2RlIGluICg0MDQsIDQxMCk6CiAgICAgICAgICAg"
    "ICAgICByZXR1cm4gTm9uZQogICAgICAgICAgICByYWlzZQoKICAgIGRlZiBkZWxldGVfZXZlbnRf"
    "Zm9yX3Rhc2soc2VsZiwgZ29vZ2xlX2V2ZW50X2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBnb29n"
    "bGVfZXZlbnRfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkdvb2dsZSBldmVudCBp"
    "ZCBpcyBtaXNzaW5nOyBjYW5ub3QgZGVsZXRlIGV2ZW50LiIpCgogICAgICAgIGlmIHNlbGYuX3Nl"
    "cnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgc2VsZi5fYnVpbGRfc2VydmljZSgpCgogICAgICAg"
    "IHRhcmdldF9jYWxlbmRhcl9pZCA9ICJwcmltYXJ5IgogICAgICAgIHNlbGYuX3NlcnZpY2UuZXZl"
    "bnRzKCkuZGVsZXRlKGNhbGVuZGFySWQ9dGFyZ2V0X2NhbGVuZGFyX2lkLCBldmVudElkPWdvb2ds"
    "ZV9ldmVudF9pZCkuZXhlY3V0ZSgpCgoKY2xhc3MgR29vZ2xlRG9jc0RyaXZlU2VydmljZToKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmLCBjcmVkZW50aWFsc19wYXRoOiBQYXRoLCB0b2tlbl9wYXRoOiBQ"
    "YXRoLCBsb2dnZXI9Tm9uZSk6CiAgICAgICAgc2VsZi5jcmVkZW50aWFsc19wYXRoID0gY3JlZGVu"
    "dGlhbHNfcGF0aAogICAgICAgIHNlbGYudG9rZW5fcGF0aCA9IHRva2VuX3BhdGgKICAgICAgICBz"
    "ZWxmLl9kcml2ZV9zZXJ2aWNlID0gTm9uZQogICAgICAgIHNlbGYuX2RvY3Nfc2VydmljZSA9IE5v"
    "bmUKICAgICAgICBzZWxmLl9sb2dnZXIgPSBsb2dnZXIKCiAgICBkZWYgX2xvZyhzZWxmLCBtZXNz"
    "YWdlOiBzdHIsIGxldmVsOiBzdHIgPSAiSU5GTyIpOgogICAgICAgIGlmIGNhbGxhYmxlKHNlbGYu"
    "X2xvZ2dlcik6CiAgICAgICAgICAgIHNlbGYuX2xvZ2dlcihtZXNzYWdlLCBsZXZlbD1sZXZlbCkK"
    "CiAgICBkZWYgX3BlcnNpc3RfdG9rZW4oc2VsZiwgY3JlZHMpOgogICAgICAgIHNlbGYudG9rZW5f"
    "cGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgIHNl"
    "bGYudG9rZW5fcGF0aC53cml0ZV90ZXh0KGNyZWRzLnRvX2pzb24oKSwgZW5jb2Rpbmc9InV0Zi04"
    "IikKCiAgICBkZWYgX2F1dGhlbnRpY2F0ZShzZWxmKToKICAgICAgICBzZWxmLl9sb2coIkRyaXZl"
    "IGF1dGggc3RhcnQuIiwgbGV2ZWw9IklORk8iKQogICAgICAgIHNlbGYuX2xvZygiRG9jcyBhdXRo"
    "IHN0YXJ0LiIsIGxldmVsPSJJTkZPIikKCiAgICAgICAgaWYgbm90IEdPT0dMRV9BUElfT0s6CiAg"
    "ICAgICAgICAgIGRldGFpbCA9IEdPT0dMRV9JTVBPUlRfRVJST1Igb3IgInVua25vd24gSW1wb3J0"
    "RXJyb3IiCiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihmIk1pc3NpbmcgR29vZ2xlIFB5"
    "dGhvbiBkZXBlbmRlbmN5OiB7ZGV0YWlsfSIpCiAgICAgICAgaWYgbm90IHNlbGYuY3JlZGVudGlh"
    "bHNfcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgcmFpc2UgRmlsZU5vdEZvdW5kRXJyb3IoCiAg"
    "ICAgICAgICAgICAgICBmIkdvb2dsZSBjcmVkZW50aWFscy9hdXRoIGNvbmZpZ3VyYXRpb24gbm90"
    "IGZvdW5kOiB7c2VsZi5jcmVkZW50aWFsc19wYXRofSIKICAgICAgICAgICAgKQoKICAgICAgICBj"
    "cmVkcyA9IE5vbmUKICAgICAgICBpZiBzZWxmLnRva2VuX3BhdGguZXhpc3RzKCk6CiAgICAgICAg"
    "ICAgIGNyZWRzID0gR29vZ2xlQ3JlZGVudGlhbHMuZnJvbV9hdXRob3JpemVkX3VzZXJfZmlsZShz"
    "dHIoc2VsZi50b2tlbl9wYXRoKSwgR09PR0xFX1NDT1BFUykKCiAgICAgICAgaWYgY3JlZHMgYW5k"
    "IGNyZWRzLnZhbGlkIGFuZCBub3QgY3JlZHMuaGFzX3Njb3BlcyhHT09HTEVfU0NPUEVTKToKICAg"
    "ICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKEdPT0dMRV9TQ09QRV9SRUFVVEhfTVNHKQoKICAg"
    "ICAgICBpZiBjcmVkcyBhbmQgY3JlZHMuZXhwaXJlZCBhbmQgY3JlZHMucmVmcmVzaF90b2tlbjoK"
    "ICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY3JlZHMucmVmcmVzaChHb29nbGVBdXRo"
    "UmVxdWVzdCgpKQogICAgICAgICAgICAgICAgc2VsZi5fcGVyc2lzdF90b2tlbihjcmVkcykKICAg"
    "ICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHJhaXNlIFJ1"
    "bnRpbWVFcnJvcigKICAgICAgICAgICAgICAgICAgICBmIkdvb2dsZSB0b2tlbiByZWZyZXNoIGZh"
    "aWxlZCBhZnRlciBzY29wZSBleHBhbnNpb246IHtleH0uIHtHT09HTEVfU0NPUEVfUkVBVVRIX01T"
    "R30iCiAgICAgICAgICAgICAgICApIGZyb20gZXgKCiAgICAgICAgaWYgbm90IGNyZWRzIG9yIG5v"
    "dCBjcmVkcy52YWxpZDoKICAgICAgICAgICAgc2VsZi5fbG9nKCJTdGFydGluZyBPQXV0aCBmbG93"
    "IGZvciBHb29nbGUgRHJpdmUvRG9jcy4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgICAgIGZsb3cgPSBJbnN0YWxsZWRBcHBGbG93LmZyb21fY2xpZW50X3NlY3Jl"
    "dHNfZmlsZShzdHIoc2VsZi5jcmVkZW50aWFsc19wYXRoKSwgR09PR0xFX1NDT1BFUykKICAgICAg"
    "ICAgICAgICAgIGNyZWRzID0gZmxvdy5ydW5fbG9jYWxfc2VydmVyKAogICAgICAgICAgICAgICAg"
    "ICAgIHBvcnQ9MCwKICAgICAgICAgICAgICAgICAgICBvcGVuX2Jyb3dzZXI9VHJ1ZSwKICAgICAg"
    "ICAgICAgICAgICAgICBhdXRob3JpemF0aW9uX3Byb21wdF9tZXNzYWdlPSgKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIk9wZW4gdGhpcyBVUkwgaW4geW91ciBicm93c2VyIHRvIGF1dGhvcml6ZSB0"
    "aGlzIGFwcGxpY2F0aW9uOlxue3VybH0iCiAgICAgICAgICAgICAgICAgICAgKSwKICAgICAgICAg"
    "ICAgICAgICAgICBzdWNjZXNzX21lc3NhZ2U9IkF1dGhlbnRpY2F0aW9uIGNvbXBsZXRlLiBZb3Ug"
    "bWF5IGNsb3NlIHRoaXMgd2luZG93LiIsCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAg"
    "ICBpZiBub3QgY3JlZHM6CiAgICAgICAgICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKCJP"
    "QXV0aCBmbG93IHJldHVybmVkIG5vIGNyZWRlbnRpYWxzIG9iamVjdC4iKQogICAgICAgICAgICAg"
    "ICAgc2VsZi5fcGVyc2lzdF90b2tlbihjcmVkcykKICAgICAgICAgICAgICAgIHNlbGYuX2xvZygi"
    "W0dDYWxdW0RFQlVHXSB0b2tlbi5qc29uIHdyaXR0ZW4gc3VjY2Vzc2Z1bGx5LiIsIGxldmVsPSJJ"
    "TkZPIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAg"
    "IHNlbGYuX2xvZyhmIk9BdXRoIGZsb3cgZmFpbGVkOiB7dHlwZShleCkuX19uYW1lX199OiB7ZXh9"
    "IiwgbGV2ZWw9IkVSUk9SIikKICAgICAgICAgICAgICAgIHJhaXNlCgogICAgICAgIHJldHVybiBj"
    "cmVkcwoKICAgIGRlZiBlbnN1cmVfc2VydmljZXMoc2VsZik6CiAgICAgICAgaWYgc2VsZi5fZHJp"
    "dmVfc2VydmljZSBpcyBub3QgTm9uZSBhbmQgc2VsZi5fZG9jc19zZXJ2aWNlIGlzIG5vdCBOb25l"
    "OgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIGNyZWRzID0gc2Vs"
    "Zi5fYXV0aGVudGljYXRlKCkKICAgICAgICAgICAgc2VsZi5fZHJpdmVfc2VydmljZSA9IGdvb2ds"
    "ZV9idWlsZCgiZHJpdmUiLCAidjMiLCBjcmVkZW50aWFscz1jcmVkcykKICAgICAgICAgICAgc2Vs"
    "Zi5fZG9jc19zZXJ2aWNlID0gZ29vZ2xlX2J1aWxkKCJkb2NzIiwgInYxIiwgY3JlZGVudGlhbHM9"
    "Y3JlZHMpCiAgICAgICAgICAgIHNlbGYuX2xvZygiRHJpdmUgYXV0aCBzdWNjZXNzLiIsIGxldmVs"
    "PSJJTkZPIikKICAgICAgICAgICAgc2VsZi5fbG9nKCJEb2NzIGF1dGggc3VjY2Vzcy4iLCBsZXZl"
    "bD0iSU5GTyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2Vs"
    "Zi5fbG9nKGYiRHJpdmUgYXV0aCBmYWlsdXJlOiB7ZXh9IiwgbGV2ZWw9IkVSUk9SIikKICAgICAg"
    "ICAgICAgc2VsZi5fbG9nKGYiRG9jcyBhdXRoIGZhaWx1cmU6IHtleH0iLCBsZXZlbD0iRVJST1Ii"
    "KQogICAgICAgICAgICByYWlzZQoKICAgIGRlZiBsaXN0X2ZvbGRlcl9pdGVtcyhzZWxmLCBmb2xk"
    "ZXJfaWQ6IHN0ciA9ICJyb290IiwgcGFnZV9zaXplOiBpbnQgPSAxMDApOgogICAgICAgIHNlbGYu"
    "ZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBzYWZlX2ZvbGRlcl9pZCA9IChmb2xkZXJfaWQgb3Ig"
    "InJvb3QiKS5zdHJpcCgpIG9yICJyb290IgogICAgICAgIHNlbGYuX2xvZyhmIkRyaXZlIGZpbGUg"
    "bGlzdCBmZXRjaCBzdGFydGVkLiBmb2xkZXJfaWQ9e3NhZmVfZm9sZGVyX2lkfSIsIGxldmVsPSJJ"
    "TkZPIikKICAgICAgICByZXNwb25zZSA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5saXN0"
    "KAogICAgICAgICAgICBxPWYiJ3tzYWZlX2ZvbGRlcl9pZH0nIGluIHBhcmVudHMgYW5kIHRyYXNo"
    "ZWQ9ZmFsc2UiLAogICAgICAgICAgICBwYWdlU2l6ZT1tYXgoMSwgbWluKGludChwYWdlX3NpemUg"
    "b3IgMTAwKSwgMjAwKSksCiAgICAgICAgICAgIG9yZGVyQnk9ImZvbGRlcixuYW1lLG1vZGlmaWVk"
    "VGltZSBkZXNjIiwKICAgICAgICAgICAgZmllbGRzPSgKICAgICAgICAgICAgICAgICJmaWxlcygi"
    "CiAgICAgICAgICAgICAgICAiaWQsbmFtZSxtaW1lVHlwZSxtb2RpZmllZFRpbWUsd2ViVmlld0xp"
    "bmsscGFyZW50cyxzaXplLCIKICAgICAgICAgICAgICAgICJsYXN0TW9kaWZ5aW5nVXNlcihkaXNw"
    "bGF5TmFtZSxlbWFpbEFkZHJlc3MpIgogICAgICAgICAgICAgICAgIikiCiAgICAgICAgICAgICks"
    "CiAgICAgICAgKS5leGVjdXRlKCkKICAgICAgICBmaWxlcyA9IHJlc3BvbnNlLmdldCgiZmlsZXMi"
    "LCBbXSkKICAgICAgICBmb3IgaXRlbSBpbiBmaWxlczoKICAgICAgICAgICAgbWltZSA9IChpdGVt"
    "LmdldCgibWltZVR5cGUiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAgICBpdGVtWyJpc19mb2xk"
    "ZXIiXSA9IG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5mb2xkZXIiCiAgICAg"
    "ICAgICAgIGl0ZW1bImlzX2dvb2dsZV9kb2MiXSA9IG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5n"
    "b29nbGUtYXBwcy5kb2N1bWVudCIKICAgICAgICBzZWxmLl9sb2coZiJEcml2ZSBpdGVtcyByZXR1"
    "cm5lZDoge2xlbihmaWxlcyl9IGZvbGRlcl9pZD17c2FmZV9mb2xkZXJfaWR9IiwgbGV2ZWw9IklO"
    "Rk8iKQogICAgICAgIHJldHVybiBmaWxlcwoKICAgIGRlZiBnZXRfZG9jX3ByZXZpZXcoc2VsZiwg"
    "ZG9jX2lkOiBzdHIsIG1heF9jaGFyczogaW50ID0gMTgwMCk6CiAgICAgICAgaWYgbm90IGRvY19p"
    "ZDoKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiRG9jdW1lbnQgaWQgaXMgcmVxdWlyZWQu"
    "IikKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgZG9jID0gc2VsZi5fZG9j"
    "c19zZXJ2aWNlLmRvY3VtZW50cygpLmdldChkb2N1bWVudElkPWRvY19pZCkuZXhlY3V0ZSgpCiAg"
    "ICAgICAgdGl0bGUgPSBkb2MuZ2V0KCJ0aXRsZSIpIG9yICJVbnRpdGxlZCIKICAgICAgICBib2R5"
    "ID0gZG9jLmdldCgiYm9keSIsIHt9KS5nZXQoImNvbnRlbnQiLCBbXSkKICAgICAgICBjaHVua3Mg"
    "PSBbXQogICAgICAgIGZvciBibG9jayBpbiBib2R5OgogICAgICAgICAgICBwYXJhZ3JhcGggPSBi"
    "bG9jay5nZXQoInBhcmFncmFwaCIpCiAgICAgICAgICAgIGlmIG5vdCBwYXJhZ3JhcGg6CiAgICAg"
    "ICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBlbGVtZW50cyA9IHBhcmFncmFwaC5nZXQo"
    "ImVsZW1lbnRzIiwgW10pCiAgICAgICAgICAgIGZvciBlbCBpbiBlbGVtZW50czoKICAgICAgICAg"
    "ICAgICAgIHJ1biA9IGVsLmdldCgidGV4dFJ1biIpCiAgICAgICAgICAgICAgICBpZiBub3QgcnVu"
    "OgogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICAgICB0ZXh0ID0gKHJ1"
    "bi5nZXQoImNvbnRlbnQiKSBvciAiIikucmVwbGFjZSgiXHgwYiIsICJcbiIpCiAgICAgICAgICAg"
    "ICAgICBpZiB0ZXh0OgogICAgICAgICAgICAgICAgICAgIGNodW5rcy5hcHBlbmQodGV4dCkKICAg"
    "ICAgICBwYXJzZWQgPSAiIi5qb2luKGNodW5rcykuc3RyaXAoKQogICAgICAgIGlmIGxlbihwYXJz"
    "ZWQpID4gbWF4X2NoYXJzOgogICAgICAgICAgICBwYXJzZWQgPSBwYXJzZWRbOm1heF9jaGFyc10u"
    "cnN0cmlwKCkgKyAi4oCmIgogICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICJ0aXRsZSI6IHRp"
    "dGxlLAogICAgICAgICAgICAiZG9jdW1lbnRfaWQiOiBkb2NfaWQsCiAgICAgICAgICAgICJyZXZp"
    "c2lvbl9pZCI6IGRvYy5nZXQoInJldmlzaW9uSWQiKSwKICAgICAgICAgICAgInByZXZpZXdfdGV4"
    "dCI6IHBhcnNlZCBvciAiW05vIHRleHQgY29udGVudCByZXR1cm5lZCBmcm9tIERvY3MgQVBJLl0i"
    "LAogICAgICAgIH0KCiAgICBkZWYgY3JlYXRlX2RvYyhzZWxmLCB0aXRsZTogc3RyID0gIk5ldyBH"
    "cmltVmVpbGUgUmVjb3JkIiwgcGFyZW50X2ZvbGRlcl9pZDogc3RyID0gInJvb3QiKToKICAgICAg"
    "ICBzYWZlX3RpdGxlID0gKHRpdGxlIG9yICJOZXcgR3JpbVZlaWxlIFJlY29yZCIpLnN0cmlwKCkg"
    "b3IgIk5ldyBHcmltVmVpbGUgUmVjb3JkIgogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkK"
    "ICAgICAgICBzYWZlX3BhcmVudF9pZCA9IChwYXJlbnRfZm9sZGVyX2lkIG9yICJyb290Iikuc3Ry"
    "aXAoKSBvciAicm9vdCIKICAgICAgICBjcmVhdGVkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxl"
    "cygpLmNyZWF0ZSgKICAgICAgICAgICAgYm9keT17CiAgICAgICAgICAgICAgICAibmFtZSI6IHNh"
    "ZmVfdGl0bGUsCiAgICAgICAgICAgICAgICAibWltZVR5cGUiOiAiYXBwbGljYXRpb24vdm5kLmdv"
    "b2dsZS1hcHBzLmRvY3VtZW50IiwKICAgICAgICAgICAgICAgICJwYXJlbnRzIjogW3NhZmVfcGFy"
    "ZW50X2lkXSwKICAgICAgICAgICAgfSwKICAgICAgICAgICAgZmllbGRzPSJpZCxuYW1lLG1pbWVU"
    "eXBlLG1vZGlmaWVkVGltZSx3ZWJWaWV3TGluayxwYXJlbnRzIiwKICAgICAgICApLmV4ZWN1dGUo"
    "KQogICAgICAgIGRvY19pZCA9IGNyZWF0ZWQuZ2V0KCJpZCIpCiAgICAgICAgbWV0YSA9IHNlbGYu"
    "Z2V0X2ZpbGVfbWV0YWRhdGEoZG9jX2lkKSBpZiBkb2NfaWQgZWxzZSB7fQogICAgICAgIHJldHVy"
    "biB7CiAgICAgICAgICAgICJpZCI6IGRvY19pZCwKICAgICAgICAgICAgIm5hbWUiOiBtZXRhLmdl"
    "dCgibmFtZSIpIG9yIHNhZmVfdGl0bGUsCiAgICAgICAgICAgICJtaW1lVHlwZSI6IG1ldGEuZ2V0"
    "KCJtaW1lVHlwZSIpIG9yICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZG9jdW1lbnQiLAog"
    "ICAgICAgICAgICAibW9kaWZpZWRUaW1lIjogbWV0YS5nZXQoIm1vZGlmaWVkVGltZSIpLAogICAg"
    "ICAgICAgICAid2ViVmlld0xpbmsiOiBtZXRhLmdldCgid2ViVmlld0xpbmsiKSwKICAgICAgICAg"
    "ICAgInBhcmVudHMiOiBtZXRhLmdldCgicGFyZW50cyIpIG9yIFtzYWZlX3BhcmVudF9pZF0sCiAg"
    "ICAgICAgfQoKICAgIGRlZiBjcmVhdGVfZm9sZGVyKHNlbGYsIG5hbWU6IHN0ciA9ICJOZXcgRm9s"
    "ZGVyIiwgcGFyZW50X2ZvbGRlcl9pZDogc3RyID0gInJvb3QiKToKICAgICAgICBzYWZlX25hbWUg"
    "PSAobmFtZSBvciAiTmV3IEZvbGRlciIpLnN0cmlwKCkgb3IgIk5ldyBGb2xkZXIiCiAgICAgICAg"
    "c2FmZV9wYXJlbnRfaWQgPSAocGFyZW50X2ZvbGRlcl9pZCBvciAicm9vdCIpLnN0cmlwKCkgb3Ig"
    "InJvb3QiCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIGNyZWF0ZWQgPSBz"
    "ZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuY3JlYXRlKAogICAgICAgICAgICBib2R5PXsKICAg"
    "ICAgICAgICAgICAgICJuYW1lIjogc2FmZV9uYW1lLAogICAgICAgICAgICAgICAgIm1pbWVUeXBl"
    "IjogImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5mb2xkZXIiLAogICAgICAgICAgICAgICAg"
    "InBhcmVudHMiOiBbc2FmZV9wYXJlbnRfaWRdLAogICAgICAgICAgICB9LAogICAgICAgICAgICBm"
    "aWVsZHM9ImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVudHMi"
    "LAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAgcmV0dXJuIGNyZWF0ZWQKCiAgICBkZWYgZ2V0"
    "X2ZpbGVfbWV0YWRhdGEoc2VsZiwgZmlsZV9pZDogc3RyKToKICAgICAgICBpZiBub3QgZmlsZV9p"
    "ZDoKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiRmlsZSBpZCBpcyByZXF1aXJlZC4iKQog"
    "ICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICByZXR1cm4gc2VsZi5fZHJpdmVf"
    "c2VydmljZS5maWxlcygpLmdldCgKICAgICAgICAgICAgZmlsZUlkPWZpbGVfaWQsCiAgICAgICAg"
    "ICAgIGZpZWxkcz0iaWQsbmFtZSxtaW1lVHlwZSxtb2RpZmllZFRpbWUsd2ViVmlld0xpbmsscGFy"
    "ZW50cyxzaXplIiwKICAgICAgICApLmV4ZWN1dGUoKQoKICAgIGRlZiBnZXRfZG9jX21ldGFkYXRh"
    "KHNlbGYsIGRvY19pZDogc3RyKToKICAgICAgICByZXR1cm4gc2VsZi5nZXRfZmlsZV9tZXRhZGF0"
    "YShkb2NfaWQpCgogICAgZGVmIGRlbGV0ZV9pdGVtKHNlbGYsIGZpbGVfaWQ6IHN0cik6CiAgICAg"
    "ICAgaWYgbm90IGZpbGVfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkZpbGUgaWQg"
    "aXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgc2Vs"
    "Zi5fZHJpdmVfc2VydmljZS5maWxlcygpLmRlbGV0ZShmaWxlSWQ9ZmlsZV9pZCkuZXhlY3V0ZSgp"
    "CgogICAgZGVmIGRlbGV0ZV9kb2Moc2VsZiwgZG9jX2lkOiBzdHIpOgogICAgICAgIHNlbGYuZGVs"
    "ZXRlX2l0ZW0oZG9jX2lkKQoKICAgIGRlZiBleHBvcnRfZG9jX3RleHQoc2VsZiwgZG9jX2lkOiBz"
    "dHIpOgogICAgICAgIGlmIG5vdCBkb2NfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3Io"
    "IkRvY3VtZW50IGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMo"
    "KQogICAgICAgIHBheWxvYWQgPSBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuZXhwb3J0KAog"
    "ICAgICAgICAgICBmaWxlSWQ9ZG9jX2lkLAogICAgICAgICAgICBtaW1lVHlwZT0idGV4dC9wbGFp"
    "biIsCiAgICAgICAgKS5leGVjdXRlKCkKICAgICAgICBpZiBpc2luc3RhbmNlKHBheWxvYWQsIGJ5"
    "dGVzKToKICAgICAgICAgICAgcmV0dXJuIHBheWxvYWQuZGVjb2RlKCJ1dGYtOCIsIGVycm9ycz0i"
    "cmVwbGFjZSIpCiAgICAgICAgcmV0dXJuIHN0cihwYXlsb2FkIG9yICIiKQoKICAgIGRlZiBkb3du"
    "bG9hZF9maWxlX2J5dGVzKHNlbGYsIGZpbGVfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGZpbGVf"
    "aWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkZpbGUgaWQgaXMgcmVxdWlyZWQuIikK"
    "ICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgcmV0dXJuIHNlbGYuX2RyaXZl"
    "X3NlcnZpY2UuZmlsZXMoKS5nZXRfbWVkaWEoZmlsZUlkPWZpbGVfaWQpLmV4ZWN1dGUoKQoKCgoK"
    "IyDilIDilIAgUEFTUyAzIENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEFsbCB3b3JrZXIgdGhyZWFkcyBkZWZp"
    "bmVkLiBBbGwgZ2VuZXJhdGlvbiBpcyBzdHJlYW1pbmcuCiMgTm8gYmxvY2tpbmcgY2FsbHMgb24g"
    "bWFpbiB0aHJlYWQgYW55d2hlcmUgaW4gdGhpcyBmaWxlLgojCiMgTmV4dDogUGFzcyA0IOKAlCBN"
    "ZW1vcnkgJiBTdG9yYWdlCiMgKE1lbW9yeU1hbmFnZXIsIFNlc3Npb25NYW5hZ2VyLCBMZXNzb25z"
    "TGVhcm5lZERCLCBUYXNrTWFuYWdlcikKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCU"
    "IFBBU1MgNDogTUVNT1JZICYgU1RPUkFHRQojCiMgU3lzdGVtcyBkZWZpbmVkIGhlcmU6CiMgICBE"
    "ZXBlbmRlbmN5Q2hlY2tlciAgIOKAlCB2YWxpZGF0ZXMgYWxsIHJlcXVpcmVkIHBhY2thZ2VzIG9u"
    "IHN0YXJ0dXAKIyAgIE1lbW9yeU1hbmFnZXIgICAgICAg4oCUIEpTT05MIG1lbW9yeSByZWFkL3dy"
    "aXRlL3NlYXJjaAojICAgU2Vzc2lvbk1hbmFnZXIgICAgICDigJQgYXV0by1zYXZlLCBsb2FkLCBj"
    "b250ZXh0IGluamVjdGlvbiwgc2Vzc2lvbiBpbmRleAojICAgTGVzc29uc0xlYXJuZWREQiAgICDi"
    "gJQgTFNMIEZvcmJpZGRlbiBSdWxlc2V0ICsgY29kZSBsZXNzb25zIGtub3dsZWRnZSBiYXNlCiMg"
    "ICBUYXNrTWFuYWdlciAgICAgICAgIOKAlCB0YXNrL3JlbWluZGVyIENSVUQsIGR1ZS1ldmVudCBk"
    "ZXRlY3Rpb24KIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZAKCgojIOKUgOKUgCBERVBFTkRFTkNZIENIRUNLRVIg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIERl"
    "cGVuZGVuY3lDaGVja2VyOgogICAgIiIiCiAgICBWYWxpZGF0ZXMgYWxsIHJlcXVpcmVkIGFuZCBv"
    "cHRpb25hbCBwYWNrYWdlcyBvbiBzdGFydHVwLgogICAgUmV0dXJucyBhIGxpc3Qgb2Ygc3RhdHVz"
    "IG1lc3NhZ2VzIGZvciB0aGUgRGlhZ25vc3RpY3MgdGFiLgogICAgU2hvd3MgYSBibG9ja2luZyBl"
    "cnJvciBkaWFsb2cgZm9yIGFueSBjcml0aWNhbCBtaXNzaW5nIGRlcGVuZGVuY3kuCiAgICAiIiIK"
    "CiAgICAjIChwYWNrYWdlX25hbWUsIGltcG9ydF9uYW1lLCBjcml0aWNhbCwgaW5zdGFsbF9oaW50"
    "KQogICAgUEFDS0FHRVMgPSBbCiAgICAgICAgKCJQeVNpZGU2IiwgICAgICAgICAgICAgICAgICAg"
    "IlB5U2lkZTYiLCAgICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0YWxsIFB5U2lk"
    "ZTYiKSwKICAgICAgICAoImxvZ3VydSIsICAgICAgICAgICAgICAgICAgICAibG9ndXJ1IiwgICAg"
    "ICAgICAgICAgICBUcnVlLAogICAgICAgICAicGlwIGluc3RhbGwgbG9ndXJ1IiksCiAgICAgICAg"
    "KCJhcHNjaGVkdWxlciIsICAgICAgICAgICAgICAgImFwc2NoZWR1bGVyIiwgICAgICAgICAgVHJ1"
    "ZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGFwc2NoZWR1bGVyIiksCiAgICAgICAgKCJweWdhbWUi"
    "LCAgICAgICAgICAgICAgICAgICAgInB5Z2FtZSIsICAgICAgICAgICAgICAgRmFsc2UsCiAgICAg"
    "ICAgICJwaXAgaW5zdGFsbCBweWdhbWUgIChuZWVkZWQgZm9yIHNvdW5kKSIpLAogICAgICAgICgi"
    "cHl3aW4zMiIsICAgICAgICAgICAgICAgICAgICJ3aW4zMmNvbSIsICAgICAgICAgICAgIEZhbHNl"
    "LAogICAgICAgICAicGlwIGluc3RhbGwgcHl3aW4zMiAgKG5lZWRlZCBmb3IgZGVza3RvcCBzaG9y"
    "dGN1dCkiKSwKICAgICAgICAoInBzdXRpbCIsICAgICAgICAgICAgICAgICAgICAicHN1dGlsIiwg"
    "ICAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHBzdXRpbCAgKG5lZWRl"
    "ZCBmb3Igc3lzdGVtIG1vbml0b3JpbmcpIiksCiAgICAgICAgKCJyZXF1ZXN0cyIsICAgICAgICAg"
    "ICAgICAgICAgInJlcXVlc3RzIiwgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5z"
    "dGFsbCByZXF1ZXN0cyIpLAogICAgICAgICgiZ29vZ2xlLWFwaS1weXRob24tY2xpZW50IiwgICJn"
    "b29nbGVhcGljbGllbnQiLCAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgZ29vZ2xl"
    "LWFwaS1weXRob24tY2xpZW50IiksCiAgICAgICAgKCJnb29nbGUtYXV0aC1vYXV0aGxpYiIsICAg"
    "ICAgImdvb2dsZV9hdXRoX29hdXRobGliIiwgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBn"
    "b29nbGUtYXV0aC1vYXV0aGxpYiIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgiLCAgICAgICAgICAg"
    "ICAgICJnb29nbGUuYXV0aCIsICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwg"
    "Z29vZ2xlLWF1dGgiKSwKICAgICAgICAoInRvcmNoIiwgICAgICAgICAgICAgICAgICAgICAidG9y"
    "Y2giLCAgICAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHRvcmNoICAo"
    "b25seSBuZWVkZWQgZm9yIGxvY2FsIG1vZGVsKSIpLAogICAgICAgICgidHJhbnNmb3JtZXJzIiwg"
    "ICAgICAgICAgICAgICJ0cmFuc2Zvcm1lcnMiLCAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlw"
    "IGluc3RhbGwgdHJhbnNmb3JtZXJzICAob25seSBuZWVkZWQgZm9yIGxvY2FsIG1vZGVsKSIpLAog"
    "ICAgICAgICgicHludm1sIiwgICAgICAgICAgICAgICAgICAgICJweW52bWwiLCAgICAgICAgICAg"
    "ICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcHludm1sICAob25seSBuZWVkZWQgZm9y"
    "IE5WSURJQSBHUFUgbW9uaXRvcmluZykiKSwKICAgIF0KCiAgICBAY2xhc3NtZXRob2QKICAgIGRl"
    "ZiBjaGVjayhjbHMpIC0+IHR1cGxlW2xpc3Rbc3RyXSwgbGlzdFtzdHJdXToKICAgICAgICAiIiIK"
    "ICAgICAgICBSZXR1cm5zIChtZXNzYWdlcywgY3JpdGljYWxfZmFpbHVyZXMpLgogICAgICAgIG1l"
    "c3NhZ2VzOiBsaXN0IG9mICJbREVQU10gcGFja2FnZSDinJMv4pyXIOKAlCBub3RlIiBzdHJpbmdz"
    "CiAgICAgICAgY3JpdGljYWxfZmFpbHVyZXM6IGxpc3Qgb2YgcGFja2FnZXMgdGhhdCBhcmUgY3Jp"
    "dGljYWwgYW5kIG1pc3NpbmcKICAgICAgICAiIiIKICAgICAgICBpbXBvcnQgaW1wb3J0bGliCiAg"
    "ICAgICAgbWVzc2FnZXMgID0gW10KICAgICAgICBjcml0aWNhbCAgPSBbXQoKICAgICAgICBmb3Ig"
    "cGtnX25hbWUsIGltcG9ydF9uYW1lLCBpc19jcml0aWNhbCwgaGludCBpbiBjbHMuUEFDS0FHRVM6"
    "CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxl"
    "KGltcG9ydF9uYW1lKQogICAgICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKGYiW0RFUFNdIHtw"
    "a2dfbmFtZX0g4pyTIikKICAgICAgICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAg"
    "ICAgICAgc3RhdHVzID0gIkNSSVRJQ0FMIiBpZiBpc19jcml0aWNhbCBlbHNlICJvcHRpb25hbCIK"
    "ICAgICAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltE"
    "RVBTXSB7cGtnX25hbWV9IOKclyAoe3N0YXR1c30pIOKAlCB7aGludH0iCiAgICAgICAgICAgICAg"
    "ICApCiAgICAgICAgICAgICAgICBpZiBpc19jcml0aWNhbDoKICAgICAgICAgICAgICAgICAgICBj"
    "cml0aWNhbC5hcHBlbmQocGtnX25hbWUpCgogICAgICAgIHJldHVybiBtZXNzYWdlcywgY3JpdGlj"
    "YWwKCiAgICBAY2xhc3NtZXRob2QKICAgIGRlZiBjaGVja19vbGxhbWEoY2xzKSAtPiBzdHI6CiAg"
    "ICAgICAgIiIiQ2hlY2sgaWYgT2xsYW1hIGlzIHJ1bm5pbmcuIFJldHVybnMgc3RhdHVzIHN0cmlu"
    "Zy4iIiIKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJlcSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1"
    "ZXN0KCJodHRwOi8vbG9jYWxob3N0OjExNDM0L2FwaS90YWdzIikKICAgICAgICAgICAgcmVzcCA9"
    "IHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTIpCiAgICAgICAgICAgIGlmIHJl"
    "c3Auc3RhdHVzID09IDIwMDoKICAgICAgICAgICAgICAgIHJldHVybiAiW0RFUFNdIE9sbGFtYSDi"
    "nJMg4oCUIHJ1bm5pbmcgb24gbG9jYWxob3N0OjExNDM0IgogICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b246CiAgICAgICAgICAgIHBhc3MKICAgICAgICByZXR1cm4gIltERVBTXSBPbGxhbWEg4pyXIOKA"
    "lCBub3QgcnVubmluZyAob25seSBuZWVkZWQgZm9yIE9sbGFtYSBtb2RlbCB0eXBlKSIKCgojIOKU"
    "gOKUgCBNRU1PUlkgTUFOQUdFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTWVtb3J5TWFuYWdlcjoKICAgICIi"
    "IgogICAgSGFuZGxlcyBhbGwgSlNPTkwgbWVtb3J5IG9wZXJhdGlvbnMuCgogICAgRmlsZXMgbWFu"
    "YWdlZDoKICAgICAgICBtZW1vcmllcy9tZXNzYWdlcy5qc29ubCAgICAgICAgIOKAlCBldmVyeSBt"
    "ZXNzYWdlLCB0aW1lc3RhbXBlZAogICAgICAgIG1lbW9yaWVzL21lbW9yaWVzLmpzb25sICAgICAg"
    "ICAg4oCUIGV4dHJhY3RlZCBtZW1vcnkgcmVjb3JkcwogICAgICAgIG1lbW9yaWVzL3N0YXRlLmpz"
    "b24gICAgICAgICAgICAg4oCUIGVudGl0eSBzdGF0ZQogICAgICAgIG1lbW9yaWVzL2luZGV4Lmpz"
    "b24gICAgICAgICAgICAg4oCUIGNvdW50cyBhbmQgbWV0YWRhdGEKCiAgICBNZW1vcnkgcmVjb3Jk"
    "cyBoYXZlIHR5cGUgaW5mZXJlbmNlLCBrZXl3b3JkIGV4dHJhY3Rpb24sIHRhZyBnZW5lcmF0aW9u"
    "LAogICAgbmVhci1kdXBsaWNhdGUgZGV0ZWN0aW9uLCBhbmQgcmVsZXZhbmNlIHNjb3JpbmcgZm9y"
    "IGNvbnRleHQgaW5qZWN0aW9uLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAg"
    "ICAgIGJhc2UgICAgICAgICAgICAgPSBjZmdfcGF0aCgibWVtb3JpZXMiKQogICAgICAgIHNlbGYu"
    "bWVzc2FnZXNfcCAgPSBiYXNlIC8gIm1lc3NhZ2VzLmpzb25sIgogICAgICAgIHNlbGYubWVtb3Jp"
    "ZXNfcCAgPSBiYXNlIC8gIm1lbW9yaWVzLmpzb25sIgogICAgICAgIHNlbGYuc3RhdGVfcCAgICAg"
    "PSBiYXNlIC8gInN0YXRlLmpzb24iCiAgICAgICAgc2VsZi5pbmRleF9wICAgICA9IGJhc2UgLyAi"
    "aW5kZXguanNvbiIKCiAgICAjIOKUgOKUgCBTVEFURSDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBsb2FkX3N0YXRlKHNl"
    "bGYpIC0+IGRpY3Q6CiAgICAgICAgaWYgbm90IHNlbGYuc3RhdGVfcC5leGlzdHMoKToKICAgICAg"
    "ICAgICAgcmV0dXJuIHNlbGYuX2RlZmF1bHRfc3RhdGUoKQogICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgcmV0dXJuIGpzb24ubG9hZHMoc2VsZi5zdGF0ZV9wLnJlYWRfdGV4dChlbmNvZGluZz0idXRm"
    "LTgiKSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4gc2VsZi5f"
    "ZGVmYXVsdF9zdGF0ZSgpCgogICAgZGVmIHNhdmVfc3RhdGUoc2VsZiwgc3RhdGU6IGRpY3QpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5zdGF0ZV9wLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24u"
    "ZHVtcHMoc3RhdGUsIGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04IgogICAgICAgICkKCiAgICBk"
    "ZWYgX2RlZmF1bHRfc3RhdGUoc2VsZikgLT4gZGljdDoKICAgICAgICByZXR1cm4gewogICAgICAg"
    "ICAgICAicGVyc29uYV9uYW1lIjogICAgICAgICAgICAgREVDS19OQU1FLAogICAgICAgICAgICAi"
    "ZGVja192ZXJzaW9uIjogICAgICAgICAgICAgQVBQX1ZFUlNJT04sCiAgICAgICAgICAgICJzZXNz"
    "aW9uX2NvdW50IjogICAgICAgICAgICAwLAogICAgICAgICAgICAibGFzdF9zdGFydHVwIjogICAg"
    "ICAgICAgICAgTm9uZSwKICAgICAgICAgICAgImxhc3Rfc2h1dGRvd24iOiAgICAgICAgICAgIE5v"
    "bmUsCiAgICAgICAgICAgICJsYXN0X2FjdGl2ZSI6ICAgICAgICAgICAgICBOb25lLAogICAgICAg"
    "ICAgICAidG90YWxfbWVzc2FnZXMiOiAgICAgICAgICAgMCwKICAgICAgICAgICAgInRvdGFsX21l"
    "bW9yaWVzIjogICAgICAgICAgIDAsCiAgICAgICAgICAgICJpbnRlcm5hbF9uYXJyYXRpdmUiOiAg"
    "ICAgICB7fSwKICAgICAgICAgICAgInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24iOiJET1JNQU5U"
    "IiwKICAgICAgICB9CgogICAgIyDilIDilIAgTUVTU0FHRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgYXBwZW5kX21lc3NhZ2Uoc2Vs"
    "Ziwgc2Vzc2lvbl9pZDogc3RyLCByb2xlOiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICAgY29u"
    "dGVudDogc3RyLCBlbW90aW9uOiBzdHIgPSAiIikgLT4gZGljdDoKICAgICAgICByZWNvcmQgPSB7"
    "CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgZiJtc2dfe3V1aWQudXVpZDQoKS5oZXhbOjEyXX0i"
    "LAogICAgICAgICAgICAidGltZXN0YW1wIjogIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAg"
    "InNlc3Npb25faWQiOiBzZXNzaW9uX2lkLAogICAgICAgICAgICAicGVyc29uYSI6ICAgIERFQ0tf"
    "TkFNRSwKICAgICAgICAgICAgInJvbGUiOiAgICAgICByb2xlLAogICAgICAgICAgICAiY29udGVu"
    "dCI6ICAgIGNvbnRlbnQsCiAgICAgICAgICAgICJlbW90aW9uIjogICAgZW1vdGlvbiwKICAgICAg"
    "ICB9CiAgICAgICAgYXBwZW5kX2pzb25sKHNlbGYubWVzc2FnZXNfcCwgcmVjb3JkKQogICAgICAg"
    "IHJldHVybiByZWNvcmQKCiAgICBkZWYgbG9hZF9yZWNlbnRfbWVzc2FnZXMoc2VsZiwgbGltaXQ6"
    "IGludCA9IDIwKSAtPiBsaXN0W2RpY3RdOgogICAgICAgIHJldHVybiByZWFkX2pzb25sKHNlbGYu"
    "bWVzc2FnZXNfcClbLWxpbWl0Ol0KCiAgICAjIOKUgOKUgCBNRU1PUklFUyDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBhcHBlbmRfbWVt"
    "b3J5KHNlbGYsIHNlc3Npb25faWQ6IHN0ciwgdXNlcl90ZXh0OiBzdHIsCiAgICAgICAgICAgICAg"
    "ICAgICAgICBhc3Npc3RhbnRfdGV4dDogc3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICBy"
    "ZWNvcmRfdHlwZSA9IGluZmVyX3JlY29yZF90eXBlKHVzZXJfdGV4dCwgYXNzaXN0YW50X3RleHQp"
    "CiAgICAgICAga2V5d29yZHMgICAgPSBleHRyYWN0X2tleXdvcmRzKHVzZXJfdGV4dCArICIgIiAr"
    "IGFzc2lzdGFudF90ZXh0KQogICAgICAgIHRhZ3MgICAgICAgID0gc2VsZi5faW5mZXJfdGFncyhy"
    "ZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBrZXl3b3JkcykKICAgICAgICB0aXRsZSAgICAgICA9IHNl"
    "bGYuX2luZmVyX3RpdGxlKHJlY29yZF90eXBlLCB1c2VyX3RleHQsIGtleXdvcmRzKQogICAgICAg"
    "IHN1bW1hcnkgICAgID0gc2VsZi5fc3VtbWFyaXplKHJlY29yZF90eXBlLCB1c2VyX3RleHQsIGFz"
    "c2lzdGFudF90ZXh0KQoKICAgICAgICBtZW1vcnkgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAg"
    "ICAgICAgICAgZiJtZW1fe3V1aWQudXVpZDQoKS5oZXhbOjEyXX0iLAogICAgICAgICAgICAidGlt"
    "ZXN0YW1wIjogICAgICAgIGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgInNlc3Npb25faWQi"
    "OiAgICAgICBzZXNzaW9uX2lkLAogICAgICAgICAgICAicGVyc29uYSI6ICAgICAgICAgIERFQ0tf"
    "TkFNRSwKICAgICAgICAgICAgInR5cGUiOiAgICAgICAgICAgICByZWNvcmRfdHlwZSwKICAgICAg"
    "ICAgICAgInRpdGxlIjogICAgICAgICAgICB0aXRsZSwKICAgICAgICAgICAgInN1bW1hcnkiOiAg"
    "ICAgICAgICBzdW1tYXJ5LAogICAgICAgICAgICAiY29udGVudCI6ICAgICAgICAgIHVzZXJfdGV4"
    "dFs6NDAwMF0sCiAgICAgICAgICAgICJhc3Npc3RhbnRfY29udGV4dCI6YXNzaXN0YW50X3RleHRb"
    "OjEyMDBdLAogICAgICAgICAgICAia2V5d29yZHMiOiAgICAgICAgIGtleXdvcmRzLAogICAgICAg"
    "ICAgICAidGFncyI6ICAgICAgICAgICAgIHRhZ3MsCiAgICAgICAgICAgICJjb25maWRlbmNlIjog"
    "ICAgICAgMC43MCBpZiByZWNvcmRfdHlwZSBpbiB7CiAgICAgICAgICAgICAgICAiZHJlYW0iLCJp"
    "c3N1ZSIsImlkZWEiLCJwcmVmZXJlbmNlIiwicmVzb2x1dGlvbiIKICAgICAgICAgICAgfSBlbHNl"
    "IDAuNTUsCiAgICAgICAgfQoKICAgICAgICBpZiBzZWxmLl9pc19uZWFyX2R1cGxpY2F0ZShtZW1v"
    "cnkpOgogICAgICAgICAgICByZXR1cm4gTm9uZQoKICAgICAgICBhcHBlbmRfanNvbmwoc2VsZi5t"
    "ZW1vcmllc19wLCBtZW1vcnkpCiAgICAgICAgcmV0dXJuIG1lbW9yeQoKICAgIGRlZiBzZWFyY2hf"
    "bWVtb3JpZXMoc2VsZiwgcXVlcnk6IHN0ciwgbGltaXQ6IGludCA9IDYpIC0+IGxpc3RbZGljdF06"
    "CiAgICAgICAgIiIiCiAgICAgICAgS2V5d29yZC1zY29yZWQgbWVtb3J5IHNlYXJjaC4KICAgICAg"
    "ICBSZXR1cm5zIHVwIHRvIGBsaW1pdGAgcmVjb3JkcyBzb3J0ZWQgYnkgcmVsZXZhbmNlIHNjb3Jl"
    "IGRlc2NlbmRpbmcuCiAgICAgICAgRmFsbHMgYmFjayB0byBtb3N0IHJlY2VudCBpZiBubyBxdWVy"
    "eSB0ZXJtcyBtYXRjaC4KICAgICAgICAiIiIKICAgICAgICBtZW1vcmllcyA9IHJlYWRfanNvbmwo"
    "c2VsZi5tZW1vcmllc19wKQogICAgICAgIGlmIG5vdCBxdWVyeS5zdHJpcCgpOgogICAgICAgICAg"
    "ICByZXR1cm4gbWVtb3JpZXNbLWxpbWl0Ol0KCiAgICAgICAgcV90ZXJtcyA9IHNldChleHRyYWN0"
    "X2tleXdvcmRzKHF1ZXJ5LCBsaW1pdD0xNikpCiAgICAgICAgc2NvcmVkICA9IFtdCgogICAgICAg"
    "IGZvciBpdGVtIGluIG1lbW9yaWVzOgogICAgICAgICAgICBpdGVtX3Rlcm1zID0gc2V0KGV4dHJh"
    "Y3Rfa2V5d29yZHMoIiAiLmpvaW4oWwogICAgICAgICAgICAgICAgaXRlbS5nZXQoInRpdGxlIiwg"
    "ICAiIiksCiAgICAgICAgICAgICAgICBpdGVtLmdldCgic3VtbWFyeSIsICIiKSwKICAgICAgICAg"
    "ICAgICAgIGl0ZW0uZ2V0KCJjb250ZW50IiwgIiIpLAogICAgICAgICAgICAgICAgIiAiLmpvaW4o"
    "aXRlbS5nZXQoImtleXdvcmRzIiwgW10pKSwKICAgICAgICAgICAgICAgICIgIi5qb2luKGl0ZW0u"
    "Z2V0KCJ0YWdzIiwgICAgIFtdKSksCiAgICAgICAgICAgIF0pLCBsaW1pdD00MCkpCgogICAgICAg"
    "ICAgICBzY29yZSA9IGxlbihxX3Rlcm1zICYgaXRlbV90ZXJtcykKCiAgICAgICAgICAgICMgQm9v"
    "c3QgYnkgdHlwZSBtYXRjaAogICAgICAgICAgICBxbCA9IHF1ZXJ5Lmxvd2VyKCkKICAgICAgICAg"
    "ICAgcnQgPSBpdGVtLmdldCgidHlwZSIsICIiKQogICAgICAgICAgICBpZiAiZHJlYW0iICBpbiBx"
    "bCBhbmQgcnQgPT0gImRyZWFtIjogICAgc2NvcmUgKz0gNAogICAgICAgICAgICBpZiAidGFzayIg"
    "ICBpbiBxbCBhbmQgcnQgPT0gInRhc2siOiAgICAgc2NvcmUgKz0gMwogICAgICAgICAgICBpZiAi"
    "aWRlYSIgICBpbiBxbCBhbmQgcnQgPT0gImlkZWEiOiAgICAgc2NvcmUgKz0gMgogICAgICAgICAg"
    "ICBpZiAibHNsIiAgICBpbiBxbCBhbmQgcnQgaW4geyJpc3N1ZSIsInJlc29sdXRpb24ifTogc2Nv"
    "cmUgKz0gMgoKICAgICAgICAgICAgaWYgc2NvcmUgPiAwOgogICAgICAgICAgICAgICAgc2NvcmVk"
    "LmFwcGVuZCgoc2NvcmUsIGl0ZW0pKQoKICAgICAgICBzY29yZWQuc29ydChrZXk9bGFtYmRhIHg6"
    "ICh4WzBdLCB4WzFdLmdldCgidGltZXN0YW1wIiwgIiIpKSwKICAgICAgICAgICAgICAgICAgICBy"
    "ZXZlcnNlPVRydWUpCiAgICAgICAgcmV0dXJuIFtpdGVtIGZvciBfLCBpdGVtIGluIHNjb3JlZFs6"
    "bGltaXRdXQoKICAgIGRlZiBidWlsZF9jb250ZXh0X2Jsb2NrKHNlbGYsIHF1ZXJ5OiBzdHIsIG1h"
    "eF9jaGFyczogaW50ID0gMjAwMCkgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIEJ1aWxkIGEg"
    "Y29udGV4dCBzdHJpbmcgZnJvbSByZWxldmFudCBtZW1vcmllcyBmb3IgcHJvbXB0IGluamVjdGlv"
    "bi4KICAgICAgICBUcnVuY2F0ZXMgdG8gbWF4X2NoYXJzIHRvIHByb3RlY3QgdGhlIGNvbnRleHQg"
    "d2luZG93LgogICAgICAgICIiIgogICAgICAgIG1lbW9yaWVzID0gc2VsZi5zZWFyY2hfbWVtb3Jp"
    "ZXMocXVlcnksIGxpbWl0PTQpCiAgICAgICAgaWYgbm90IG1lbW9yaWVzOgogICAgICAgICAgICBy"
    "ZXR1cm4gIiIKCiAgICAgICAgcGFydHMgPSBbIltSRUxFVkFOVCBNRU1PUklFU10iXQogICAgICAg"
    "IHRvdGFsID0gMAogICAgICAgIGZvciBtIGluIG1lbW9yaWVzOgogICAgICAgICAgICBlbnRyeSA9"
    "ICgKICAgICAgICAgICAgICAgIGYi4oCiIFt7bS5nZXQoJ3R5cGUnLCcnKS51cHBlcigpfV0ge20u"
    "Z2V0KCd0aXRsZScsJycpfTogIgogICAgICAgICAgICAgICAgZiJ7bS5nZXQoJ3N1bW1hcnknLCcn"
    "KX0iCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgdG90YWwgKyBsZW4oZW50cnkpID4gbWF4"
    "X2NoYXJzOgogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGVu"
    "dHJ5KQogICAgICAgICAgICB0b3RhbCArPSBsZW4oZW50cnkpCgogICAgICAgIHBhcnRzLmFwcGVu"
    "ZCgiW0VORCBNRU1PUklFU10iKQogICAgICAgIHJldHVybiAiXG4iLmpvaW4ocGFydHMpCgogICAg"
    "IyDilIDilIAgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgIGRlZiBfaXNfbmVhcl9kdXBsaWNhdGUoc2VsZiwgY2FuZGlkYXRl"
    "OiBkaWN0KSAtPiBib29sOgogICAgICAgIHJlY2VudCA9IHJlYWRfanNvbmwoc2VsZi5tZW1vcmll"
    "c19wKVstMjU6XQogICAgICAgIGN0ID0gY2FuZGlkYXRlLmdldCgidGl0bGUiLCAiIikubG93ZXIo"
    "KS5zdHJpcCgpCiAgICAgICAgY3MgPSBjYW5kaWRhdGUuZ2V0KCJzdW1tYXJ5IiwgIiIpLmxvd2Vy"
    "KCkuc3RyaXAoKQogICAgICAgIGZvciBpdGVtIGluIHJlY2VudDoKICAgICAgICAgICAgaWYgaXRl"
    "bS5nZXQoInRpdGxlIiwiIikubG93ZXIoKS5zdHJpcCgpID09IGN0OiAgcmV0dXJuIFRydWUKICAg"
    "ICAgICAgICAgaWYgaXRlbS5nZXQoInN1bW1hcnkiLCIiKS5sb3dlcigpLnN0cmlwKCkgPT0gY3M6"
    "IHJldHVybiBUcnVlCiAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgZGVmIF9pbmZlcl90YWdzKHNl"
    "bGYsIHJlY29yZF90eXBlOiBzdHIsIHRleHQ6IHN0ciwKICAgICAgICAgICAgICAgICAgICBrZXl3"
    "b3JkczogbGlzdFtzdHJdKSAtPiBsaXN0W3N0cl06CiAgICAgICAgdCAgICA9IHRleHQubG93ZXIo"
    "KQogICAgICAgIHRhZ3MgPSBbcmVjb3JkX3R5cGVdCiAgICAgICAgaWYgImRyZWFtIiAgIGluIHQ6"
    "IHRhZ3MuYXBwZW5kKCJkcmVhbSIpCiAgICAgICAgaWYgImxzbCIgICAgIGluIHQ6IHRhZ3MuYXBw"
    "ZW5kKCJsc2wiKQogICAgICAgIGlmICJweXRob24iICBpbiB0OiB0YWdzLmFwcGVuZCgicHl0aG9u"
    "IikKICAgICAgICBpZiAiZ2FtZSIgICAgaW4gdDogdGFncy5hcHBlbmQoImdhbWVfaWRlYSIpCiAg"
    "ICAgICAgaWYgInNsIiAgICAgIGluIHQgb3IgInNlY29uZCBsaWZlIiBpbiB0OiB0YWdzLmFwcGVu"
    "ZCgic2Vjb25kbGlmZSIpCiAgICAgICAgaWYgREVDS19OQU1FLmxvd2VyKCkgaW4gdDogdGFncy5h"
    "cHBlbmQoREVDS19OQU1FLmxvd2VyKCkpCiAgICAgICAgZm9yIGt3IGluIGtleXdvcmRzWzo0XToK"
    "ICAgICAgICAgICAgaWYga3cgbm90IGluIHRhZ3M6CiAgICAgICAgICAgICAgICB0YWdzLmFwcGVu"
    "ZChrdykKICAgICAgICAjIERlZHVwbGljYXRlIHByZXNlcnZpbmcgb3JkZXIKICAgICAgICBzZWVu"
    "LCBvdXQgPSBzZXQoKSwgW10KICAgICAgICBmb3IgdGFnIGluIHRhZ3M6CiAgICAgICAgICAgIGlm"
    "IHRhZyBub3QgaW4gc2VlbjoKICAgICAgICAgICAgICAgIHNlZW4uYWRkKHRhZykKICAgICAgICAg"
    "ICAgICAgIG91dC5hcHBlbmQodGFnKQogICAgICAgIHJldHVybiBvdXRbOjEyXQoKICAgIGRlZiBf"
    "aW5mZXJfdGl0bGUoc2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwgdXNlcl90ZXh0OiBzdHIsCiAgICAg"
    "ICAgICAgICAgICAgICAgIGtleXdvcmRzOiBsaXN0W3N0cl0pIC0+IHN0cjoKICAgICAgICBkZWYg"
    "Y2xlYW4od29yZHMpOgogICAgICAgICAgICByZXR1cm4gW3cuc3RyaXAoIiAtXy4sIT8iKS5jYXBp"
    "dGFsaXplKCkKICAgICAgICAgICAgICAgICAgICBmb3IgdyBpbiB3b3JkcyBpZiBsZW4odykgPiAy"
    "XQoKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAidGFzayI6CiAgICAgICAgICAgIGltcG9ydCBy"
    "ZQogICAgICAgICAgICBtID0gcmUuc2VhcmNoKHIicmVtaW5kIG1lIC4qPyB0byAoLispIiwgdXNl"
    "cl90ZXh0LCByZS5JKQogICAgICAgICAgICBpZiBtOgogICAgICAgICAgICAgICAgcmV0dXJuIGYi"
    "UmVtaW5kZXI6IHttLmdyb3VwKDEpLnN0cmlwKClbOjYwXX0iCiAgICAgICAgICAgIHJldHVybiAi"
    "UmVtaW5kZXIgVGFzayIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiZHJlYW0iOgogICAgICAg"
    "ICAgICByZXR1cm4gZiJ7JyAnLmpvaW4oY2xlYW4oa2V5d29yZHNbOjNdKSl9IERyZWFtIi5zdHJp"
    "cCgpIG9yICJEcmVhbSBNZW1vcnkiCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImlzc3VlIjoK"
    "ICAgICAgICAgICAgcmV0dXJuIGYiSXNzdWU6IHsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0p"
    "KX0iLnN0cmlwKCkgb3IgIlRlY2huaWNhbCBJc3N1ZSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9"
    "PSAicmVzb2x1dGlvbiI6CiAgICAgICAgICAgIHJldHVybiBmIlJlc29sdXRpb246IHsnICcuam9p"
    "bihjbGVhbihrZXl3b3Jkc1s6NF0pKX0iLnN0cmlwKCkgb3IgIlRlY2huaWNhbCBSZXNvbHV0aW9u"
    "IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpZGVhIjoKICAgICAgICAgICAgcmV0dXJuIGYi"
    "SWRlYTogeycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzo0XSkpfSIuc3RyaXAoKSBvciAiSWRlYSIK"
    "ICAgICAgICBpZiBrZXl3b3JkczoKICAgICAgICAgICAgcmV0dXJuICIgIi5qb2luKGNsZWFuKGtl"
    "eXdvcmRzWzo1XSkpIG9yICJDb252ZXJzYXRpb24gTWVtb3J5IgogICAgICAgIHJldHVybiAiQ29u"
    "dmVyc2F0aW9uIE1lbW9yeSIKCiAgICBkZWYgX3N1bW1hcml6ZShzZWxmLCByZWNvcmRfdHlwZTog"
    "c3RyLCB1c2VyX3RleHQ6IHN0ciwKICAgICAgICAgICAgICAgICAgIGFzc2lzdGFudF90ZXh0OiBz"
    "dHIpIC0+IHN0cjoKICAgICAgICB1ID0gdXNlcl90ZXh0LnN0cmlwKClbOjIyMF0KICAgICAgICBh"
    "ID0gYXNzaXN0YW50X3RleHQuc3RyaXAoKVs6MjIwXQogICAgICAgIGlmIHJlY29yZF90eXBlID09"
    "ICJkcmVhbSI6ICAgICAgIHJldHVybiBmIlVzZXIgZGVzY3JpYmVkIGEgZHJlYW06IHt1fSIKICAg"
    "ICAgICBpZiByZWNvcmRfdHlwZSA9PSAidGFzayI6ICAgICAgICByZXR1cm4gZiJSZW1pbmRlci90"
    "YXNrOiB7dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImlzc3VlIjogICAgICAgcmV0dXJu"
    "IGYiVGVjaG5pY2FsIGlzc3VlOiB7dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInJlc29s"
    "dXRpb24iOiAgcmV0dXJuIGYiU29sdXRpb24gcmVjb3JkZWQ6IHthIG9yIHV9IgogICAgICAgIGlm"
    "IHJlY29yZF90eXBlID09ICJpZGVhIjogICAgICAgIHJldHVybiBmIklkZWEgZGlzY3Vzc2VkOiB7"
    "dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInByZWZlcmVuY2UiOiAgcmV0dXJuIGYiUHJl"
    "ZmVyZW5jZSBub3RlZDoge3V9IgogICAgICAgIHJldHVybiBmIkNvbnZlcnNhdGlvbjoge3V9IgoK"
    "CiMg4pSA4pSAIFNFU1NJT04gTUFOQUdFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU2Vzc2lvbk1hbmFnZXI6CiAg"
    "ICAiIiIKICAgIE1hbmFnZXMgY29udmVyc2F0aW9uIHNlc3Npb25zLgoKICAgIEF1dG8tc2F2ZTog"
    "ZXZlcnkgMTAgbWludXRlcyAoQVBTY2hlZHVsZXIpLCBtaWRuaWdodC10by1taWRuaWdodCBib3Vu"
    "ZGFyeS4KICAgIEZpbGU6IHNlc3Npb25zL1lZWVktTU0tREQuanNvbmwg4oCUIG92ZXJ3cml0ZXMg"
    "b24gZWFjaCBzYXZlLgogICAgSW5kZXg6IHNlc3Npb25zL3Nlc3Npb25faW5kZXguanNvbiDigJQg"
    "b25lIGVudHJ5IHBlciBkYXkuCgogICAgU2Vzc2lvbnMgYXJlIGxvYWRlZCBhcyBjb250ZXh0IGlu"
    "amVjdGlvbiAobm90IHJlYWwgbWVtb3J5KSB1bnRpbAogICAgdGhlIFNRTGl0ZS9DaHJvbWFEQiBz"
    "eXN0ZW0gaXMgYnVpbHQgaW4gUGhhc2UgMi4KICAgICIiIgoKICAgIEFVVE9TQVZFX0lOVEVSVkFM"
    "ID0gMTAgICAjIG1pbnV0ZXMKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5f"
    "c2Vzc2lvbnNfZGlyICA9IGNmZ19wYXRoKCJzZXNzaW9ucyIpCiAgICAgICAgc2VsZi5faW5kZXhf"
    "cGF0aCAgICA9IHNlbGYuX3Nlc3Npb25zX2RpciAvICJzZXNzaW9uX2luZGV4Lmpzb24iCiAgICAg"
    "ICAgc2VsZi5fc2Vzc2lvbl9pZCAgICA9IGYic2Vzc2lvbl97ZGF0ZXRpbWUubm93KCkuc3RyZnRp"
    "bWUoJyVZJW0lZF8lSCVNJVMnKX0iCiAgICAgICAgc2VsZi5fY3VycmVudF9kYXRlICA9IGRhdGUu"
    "dG9kYXkoKS5pc29mb3JtYXQoKQogICAgICAgIHNlbGYuX21lc3NhZ2VzOiBsaXN0W2RpY3RdID0g"
    "W10KICAgICAgICBzZWxmLl9sb2FkZWRfam91cm5hbDogT3B0aW9uYWxbc3RyXSA9IE5vbmUgICMg"
    "ZGF0ZSBvZiBsb2FkZWQgam91cm5hbAoKICAgICMg4pSA4pSAIENVUlJFTlQgU0VTU0lPTiDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBhZGRfbWVzc2FnZShzZWxmLCByb2xl"
    "OiBzdHIsIGNvbnRlbnQ6IHN0ciwKICAgICAgICAgICAgICAgICAgICBlbW90aW9uOiBzdHIgPSAi"
    "IiwgdGltZXN0YW1wOiBzdHIgPSAiIikgLT4gTm9uZToKICAgICAgICBzZWxmLl9tZXNzYWdlcy5h"
    "cHBlbmQoewogICAgICAgICAgICAiaWQiOiAgICAgICAgZiJtc2dfe3V1aWQudXVpZDQoKS5oZXhb"
    "OjhdfSIsCiAgICAgICAgICAgICJ0aW1lc3RhbXAiOiB0aW1lc3RhbXAgb3IgbG9jYWxfbm93X2lz"
    "bygpLAogICAgICAgICAgICAicm9sZSI6ICAgICAgcm9sZSwKICAgICAgICAgICAgImNvbnRlbnQi"
    "OiAgIGNvbnRlbnQsCiAgICAgICAgICAgICJlbW90aW9uIjogICBlbW90aW9uLAogICAgICAgIH0p"
    "CgogICAgZGVmIGdldF9oaXN0b3J5KHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgIiIiCiAg"
    "ICAgICAgUmV0dXJuIGhpc3RvcnkgaW4gTExNLWZyaWVuZGx5IGZvcm1hdC4KICAgICAgICBbeyJy"
    "b2xlIjogInVzZXIifCJhc3Npc3RhbnQiLCAiY29udGVudCI6ICIuLi4ifV0KICAgICAgICAiIiIK"
    "ICAgICAgICByZXR1cm4gWwogICAgICAgICAgICB7InJvbGUiOiBtWyJyb2xlIl0sICJjb250ZW50"
    "IjogbVsiY29udGVudCJdfQogICAgICAgICAgICBmb3IgbSBpbiBzZWxmLl9tZXNzYWdlcwogICAg"
    "ICAgICAgICBpZiBtWyJyb2xlIl0gaW4gKCJ1c2VyIiwgImFzc2lzdGFudCIpCiAgICAgICAgXQoK"
    "ICAgIEBwcm9wZXJ0eQogICAgZGVmIHNlc3Npb25faWQoc2VsZikgLT4gc3RyOgogICAgICAgIHJl"
    "dHVybiBzZWxmLl9zZXNzaW9uX2lkCgogICAgQHByb3BlcnR5CiAgICBkZWYgbWVzc2FnZV9jb3Vu"
    "dChzZWxmKSAtPiBpbnQ6CiAgICAgICAgcmV0dXJuIGxlbihzZWxmLl9tZXNzYWdlcykKCiAgICAj"
    "IOKUgOKUgCBTQVZFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIHNhdmUoc2VsZiwgYWlfZ2VuZXJhdGVkX25hbWU6"
    "IHN0ciA9ICIiKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIFNhdmUgY3VycmVudCBzZXNz"
    "aW9uIHRvIHNlc3Npb25zL1lZWVktTU0tREQuanNvbmwuCiAgICAgICAgT3ZlcndyaXRlcyB0aGUg"
    "ZmlsZSBmb3IgdG9kYXkg4oCUIGVhY2ggc2F2ZSBpcyBhIGZ1bGwgc25hcHNob3QuCiAgICAgICAg"
    "VXBkYXRlcyBzZXNzaW9uX2luZGV4Lmpzb24uCiAgICAgICAgIiIiCiAgICAgICAgdG9kYXkgPSBk"
    "YXRlLnRvZGF5KCkuaXNvZm9ybWF0KCkKICAgICAgICBvdXRfcGF0aCA9IHNlbGYuX3Nlc3Npb25z"
    "X2RpciAvIGYie3RvZGF5fS5qc29ubCIKCiAgICAgICAgIyBXcml0ZSBhbGwgbWVzc2FnZXMKICAg"
    "ICAgICB3cml0ZV9qc29ubChvdXRfcGF0aCwgc2VsZi5fbWVzc2FnZXMpCgogICAgICAgICMgVXBk"
    "YXRlIGluZGV4CiAgICAgICAgaW5kZXggPSBzZWxmLl9sb2FkX2luZGV4KCkKICAgICAgICBleGlz"
    "dGluZyA9IG5leHQoCiAgICAgICAgICAgIChzIGZvciBzIGluIGluZGV4WyJzZXNzaW9ucyJdIGlm"
    "IHNbImRhdGUiXSA9PSB0b2RheSksIE5vbmUKICAgICAgICApCgogICAgICAgIG5hbWUgPSBhaV9n"
    "ZW5lcmF0ZWRfbmFtZSBvciBleGlzdGluZy5nZXQoIm5hbWUiLCAiIikgaWYgZXhpc3RpbmcgZWxz"
    "ZSAiIgogICAgICAgIGlmIG5vdCBuYW1lIGFuZCBzZWxmLl9tZXNzYWdlczoKICAgICAgICAgICAg"
    "IyBBdXRvLW5hbWUgZnJvbSBmaXJzdCB1c2VyIG1lc3NhZ2UgKGZpcnN0IDUgd29yZHMpCiAgICAg"
    "ICAgICAgIGZpcnN0X3VzZXIgPSBuZXh0KAogICAgICAgICAgICAgICAgKG1bImNvbnRlbnQiXSBm"
    "b3IgbSBpbiBzZWxmLl9tZXNzYWdlcyBpZiBtWyJyb2xlIl0gPT0gInVzZXIiKSwKICAgICAgICAg"
    "ICAgICAgICIiCiAgICAgICAgICAgICkKICAgICAgICAgICAgd29yZHMgPSBmaXJzdF91c2VyLnNw"
    "bGl0KClbOjVdCiAgICAgICAgICAgIG5hbWUgID0gIiAiLmpvaW4od29yZHMpIGlmIHdvcmRzIGVs"
    "c2UgZiJTZXNzaW9uIHt0b2RheX0iCgogICAgICAgIGVudHJ5ID0gewogICAgICAgICAgICAiZGF0"
    "ZSI6ICAgICAgICAgIHRvZGF5LAogICAgICAgICAgICAic2Vzc2lvbl9pZCI6ICAgIHNlbGYuX3Nl"
    "c3Npb25faWQsCiAgICAgICAgICAgICJuYW1lIjogICAgICAgICAgbmFtZSwKICAgICAgICAgICAg"
    "Im1lc3NhZ2VfY291bnQiOiBsZW4oc2VsZi5fbWVzc2FnZXMpLAogICAgICAgICAgICAiZmlyc3Rf"
    "bWVzc2FnZSI6IChzZWxmLl9tZXNzYWdlc1swXVsidGltZXN0YW1wIl0KICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgaWYgc2VsZi5fbWVzc2FnZXMgZWxzZSAiIiksCiAgICAgICAgICAgICJs"
    "YXN0X21lc3NhZ2UiOiAgKHNlbGYuX21lc3NhZ2VzWy0xXVsidGltZXN0YW1wIl0KICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgaWYgc2VsZi5fbWVzc2FnZXMgZWxzZSAiIiksCiAgICAgICAg"
    "fQoKICAgICAgICBpZiBleGlzdGluZzoKICAgICAgICAgICAgaWR4ID0gaW5kZXhbInNlc3Npb25z"
    "Il0uaW5kZXgoZXhpc3RpbmcpCiAgICAgICAgICAgIGluZGV4WyJzZXNzaW9ucyJdW2lkeF0gPSBl"
    "bnRyeQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGluZGV4WyJzZXNzaW9ucyJdLmluc2VydCgw"
    "LCBlbnRyeSkKCiAgICAgICAgIyBLZWVwIGxhc3QgMzY1IGRheXMgaW4gaW5kZXgKICAgICAgICBp"
    "bmRleFsic2Vzc2lvbnMiXSA9IGluZGV4WyJzZXNzaW9ucyJdWzozNjVdCiAgICAgICAgc2VsZi5f"
    "c2F2ZV9pbmRleChpbmRleCkKCiAgICAjIOKUgOKUgCBMT0FEIC8gSk9VUk5BTCDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBsaXN0X3Nlc3Npb25zKHNlbGYpIC0+IGxp"
    "c3RbZGljdF06CiAgICAgICAgIiIiUmV0dXJuIGFsbCBzZXNzaW9ucyBmcm9tIGluZGV4LCBuZXdl"
    "c3QgZmlyc3QuIiIiCiAgICAgICAgcmV0dXJuIHNlbGYuX2xvYWRfaW5kZXgoKS5nZXQoInNlc3Np"
    "b25zIiwgW10pCgogICAgZGVmIGxvYWRfc2Vzc2lvbl9hc19jb250ZXh0KHNlbGYsIHNlc3Npb25f"
    "ZGF0ZTogc3RyKSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgTG9hZCBhIHBhc3Qgc2Vzc2lv"
    "biBhcyBhIGNvbnRleHQgaW5qZWN0aW9uIHN0cmluZy4KICAgICAgICBSZXR1cm5zIGZvcm1hdHRl"
    "ZCB0ZXh0IHRvIHByZXBlbmQgdG8gdGhlIHN5c3RlbSBwcm9tcHQuCiAgICAgICAgVGhpcyBpcyBO"
    "T1QgcmVhbCBtZW1vcnkg4oCUIGl0J3MgYSB0ZW1wb3JhcnkgY29udGV4dCB3aW5kb3cgaW5qZWN0"
    "aW9uCiAgICAgICAgdW50aWwgdGhlIFBoYXNlIDIgbWVtb3J5IHN5c3RlbSBpcyBidWlsdC4KICAg"
    "ICAgICAiIiIKICAgICAgICBwYXRoID0gc2VsZi5fc2Vzc2lvbnNfZGlyIC8gZiJ7c2Vzc2lvbl9k"
    "YXRlfS5qc29ubCIKICAgICAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgcmV0"
    "dXJuICIiCgogICAgICAgIG1lc3NhZ2VzID0gcmVhZF9qc29ubChwYXRoKQogICAgICAgIHNlbGYu"
    "X2xvYWRlZF9qb3VybmFsID0gc2Vzc2lvbl9kYXRlCgogICAgICAgIGxpbmVzID0gW2YiW0pPVVJO"
    "QUwgTE9BREVEIOKAlCB7c2Vzc2lvbl9kYXRlfV0iLAogICAgICAgICAgICAgICAgICJUaGUgZm9s"
    "bG93aW5nIGlzIGEgcmVjb3JkIG9mIGEgcHJpb3IgY29udmVyc2F0aW9uLiIsCiAgICAgICAgICAg"
    "ICAgICAgIlVzZSB0aGlzIGFzIGNvbnRleHQgZm9yIHRoZSBjdXJyZW50IHNlc3Npb246XG4iXQoK"
    "ICAgICAgICAjIEluY2x1ZGUgdXAgdG8gbGFzdCAzMCBtZXNzYWdlcyBmcm9tIHRoYXQgc2Vzc2lv"
    "bgogICAgICAgIGZvciBtc2cgaW4gbWVzc2FnZXNbLTMwOl06CiAgICAgICAgICAgIHJvbGUgICAg"
    "PSBtc2cuZ2V0KCJyb2xlIiwgIj8iKS51cHBlcigpCiAgICAgICAgICAgIGNvbnRlbnQgPSBtc2cu"
    "Z2V0KCJjb250ZW50IiwgIiIpWzozMDBdCiAgICAgICAgICAgIHRzICAgICAgPSBtc2cuZ2V0KCJ0"
    "aW1lc3RhbXAiLCAiIilbOjE2XQogICAgICAgICAgICBsaW5lcy5hcHBlbmQoZiJbe3RzfV0ge3Jv"
    "bGV9OiB7Y29udGVudH0iKQoKICAgICAgICBsaW5lcy5hcHBlbmQoIltFTkQgSk9VUk5BTF0iKQog"
    "ICAgICAgIHJldHVybiAiXG4iLmpvaW4obGluZXMpCgogICAgZGVmIGNsZWFyX2xvYWRlZF9qb3Vy"
    "bmFsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fbG9hZGVkX2pvdXJuYWwgPSBOb25lCgog"
    "ICAgQHByb3BlcnR5CiAgICBkZWYgbG9hZGVkX2pvdXJuYWxfZGF0ZShzZWxmKSAtPiBPcHRpb25h"
    "bFtzdHJdOgogICAgICAgIHJldHVybiBzZWxmLl9sb2FkZWRfam91cm5hbAoKICAgIGRlZiByZW5h"
    "bWVfc2Vzc2lvbihzZWxmLCBzZXNzaW9uX2RhdGU6IHN0ciwgbmV3X25hbWU6IHN0cikgLT4gYm9v"
    "bDoKICAgICAgICAiIiJSZW5hbWUgYSBzZXNzaW9uIGluIHRoZSBpbmRleC4gUmV0dXJucyBUcnVl"
    "IG9uIHN1Y2Nlc3MuIiIiCiAgICAgICAgaW5kZXggPSBzZWxmLl9sb2FkX2luZGV4KCkKICAgICAg"
    "ICBmb3IgZW50cnkgaW4gaW5kZXhbInNlc3Npb25zIl06CiAgICAgICAgICAgIGlmIGVudHJ5WyJk"
    "YXRlIl0gPT0gc2Vzc2lvbl9kYXRlOgogICAgICAgICAgICAgICAgZW50cnlbIm5hbWUiXSA9IG5l"
    "d19uYW1lWzo4MF0KICAgICAgICAgICAgICAgIHNlbGYuX3NhdmVfaW5kZXgoaW5kZXgpCiAgICAg"
    "ICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVybiBGYWxzZQoKICAgICMg4pSA4pSA"
    "IElOREVYIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBk"
    "ZWYgX2xvYWRfaW5kZXgoc2VsZikgLT4gZGljdDoKICAgICAgICBpZiBub3Qgc2VsZi5faW5kZXhf"
    "cGF0aC5leGlzdHMoKToKICAgICAgICAgICAgcmV0dXJuIHsic2Vzc2lvbnMiOiBbXX0KICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgIHJldHVybiBqc29uLmxvYWRzKAogICAgICAgICAgICAgICAgc2Vs"
    "Zi5faW5kZXhfcGF0aC5yZWFkX3RleHQoZW5jb2Rpbmc9InV0Zi04IikKICAgICAgICAgICAgKQog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHJldHVybiB7InNlc3Npb25zIjog"
    "W119CgogICAgZGVmIF9zYXZlX2luZGV4KHNlbGYsIGluZGV4OiBkaWN0KSAtPiBOb25lOgogICAg"
    "ICAgIHNlbGYuX2luZGV4X3BhdGgud3JpdGVfdGV4dCgKICAgICAgICAgICAganNvbi5kdW1wcyhp"
    "bmRleCwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiCiAgICAgICAgKQoKCiMg4pSA4pSAIExF"
    "U1NPTlMgTEVBUk5FRCBEQVRBQkFTRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKY2xhc3MgTGVzc29uc0xlYXJuZWREQjoKICAgICIiIgogICAgUGVyc2lzdGVudCBrbm93bGVk"
    "Z2UgYmFzZSBmb3IgY29kZSBsZXNzb25zLCBydWxlcywgYW5kIHJlc29sdXRpb25zLgoKICAgIENv"
    "bHVtbnMgcGVyIHJlY29yZDoKICAgICAgICBpZCwgY3JlYXRlZF9hdCwgZW52aXJvbm1lbnQgKExT"
    "THxQeXRob258UHlTaWRlNnwuLi4pLCBsYW5ndWFnZSwKICAgICAgICByZWZlcmVuY2Vfa2V5IChz"
    "aG9ydCB1bmlxdWUgdGFnKSwgc3VtbWFyeSwgZnVsbF9ydWxlLAogICAgICAgIHJlc29sdXRpb24s"
    "IGxpbmssIHRhZ3MKCiAgICBRdWVyaWVkIEZJUlNUIGJlZm9yZSBhbnkgY29kZSBzZXNzaW9uIGlu"
    "IHRoZSByZWxldmFudCBsYW5ndWFnZS4KICAgIFRoZSBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgbGl2"
    "ZXMgaGVyZS4KICAgIEdyb3dpbmcsIG5vbi1kdXBsaWNhdGluZywgc2VhcmNoYWJsZS4KICAgICIi"
    "IgoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBzZWxmLl9wYXRoID0gY2ZnX3BhdGgo"
    "Im1lbW9yaWVzIikgLyAibGVzc29uc19sZWFybmVkLmpzb25sIgoKICAgIGRlZiBhZGQoc2VsZiwg"
    "ZW52aXJvbm1lbnQ6IHN0ciwgbGFuZ3VhZ2U6IHN0ciwgcmVmZXJlbmNlX2tleTogc3RyLAogICAg"
    "ICAgICAgICBzdW1tYXJ5OiBzdHIsIGZ1bGxfcnVsZTogc3RyLCByZXNvbHV0aW9uOiBzdHIgPSAi"
    "IiwKICAgICAgICAgICAgbGluazogc3RyID0gIiIsIHRhZ3M6IGxpc3QgPSBOb25lKSAtPiBkaWN0"
    "OgogICAgICAgIHJlY29yZCA9IHsKICAgICAgICAgICAgImlkIjogICAgICAgICAgICBmImxlc3Nv"
    "bl97dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAg"
    "bG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAiZW52aXJvbm1lbnQiOiAgIGVudmlyb25tZW50"
    "LAogICAgICAgICAgICAibGFuZ3VhZ2UiOiAgICAgIGxhbmd1YWdlLAogICAgICAgICAgICAicmVm"
    "ZXJlbmNlX2tleSI6IHJlZmVyZW5jZV9rZXksCiAgICAgICAgICAgICJzdW1tYXJ5IjogICAgICAg"
    "c3VtbWFyeSwKICAgICAgICAgICAgImZ1bGxfcnVsZSI6ICAgICBmdWxsX3J1bGUsCiAgICAgICAg"
    "ICAgICJyZXNvbHV0aW9uIjogICAgcmVzb2x1dGlvbiwKICAgICAgICAgICAgImxpbmsiOiAgICAg"
    "ICAgICBsaW5rLAogICAgICAgICAgICAidGFncyI6ICAgICAgICAgIHRhZ3Mgb3IgW10sCiAgICAg"
    "ICAgfQogICAgICAgIGlmIG5vdCBzZWxmLl9pc19kdXBsaWNhdGUocmVmZXJlbmNlX2tleSk6CiAg"
    "ICAgICAgICAgIGFwcGVuZF9qc29ubChzZWxmLl9wYXRoLCByZWNvcmQpCiAgICAgICAgcmV0dXJu"
    "IHJlY29yZAoKICAgIGRlZiBzZWFyY2goc2VsZiwgcXVlcnk6IHN0ciA9ICIiLCBlbnZpcm9ubWVu"
    "dDogc3RyID0gIiIsCiAgICAgICAgICAgICAgIGxhbmd1YWdlOiBzdHIgPSAiIikgLT4gbGlzdFtk"
    "aWN0XToKICAgICAgICByZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIHJl"
    "c3VsdHMgPSBbXQogICAgICAgIHEgPSBxdWVyeS5sb3dlcigpCiAgICAgICAgZm9yIHIgaW4gcmVj"
    "b3JkczoKICAgICAgICAgICAgaWYgZW52aXJvbm1lbnQgYW5kIHIuZ2V0KCJlbnZpcm9ubWVudCIs"
    "IiIpLmxvd2VyKCkgIT0gZW52aXJvbm1lbnQubG93ZXIoKToKICAgICAgICAgICAgICAgIGNvbnRp"
    "bnVlCiAgICAgICAgICAgIGlmIGxhbmd1YWdlIGFuZCByLmdldCgibGFuZ3VhZ2UiLCIiKS5sb3dl"
    "cigpICE9IGxhbmd1YWdlLmxvd2VyKCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAg"
    "ICAgICBpZiBxOgogICAgICAgICAgICAgICAgaGF5c3RhY2sgPSAiICIuam9pbihbCiAgICAgICAg"
    "ICAgICAgICAgICAgci5nZXQoInN1bW1hcnkiLCIiKSwKICAgICAgICAgICAgICAgICAgICByLmdl"
    "dCgiZnVsbF9ydWxlIiwiIiksCiAgICAgICAgICAgICAgICAgICAgci5nZXQoInJlZmVyZW5jZV9r"
    "ZXkiLCIiKSwKICAgICAgICAgICAgICAgICAgICAiICIuam9pbihyLmdldCgidGFncyIsW10pKSwK"
    "ICAgICAgICAgICAgICAgIF0pLmxvd2VyKCkKICAgICAgICAgICAgICAgIGlmIHEgbm90IGluIGhh"
    "eXN0YWNrOgogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIHJlc3VsdHMu"
    "YXBwZW5kKHIpCiAgICAgICAgcmV0dXJuIHJlc3VsdHMKCiAgICBkZWYgZ2V0X2FsbChzZWxmKSAt"
    "PiBsaXN0W2RpY3RdOgogICAgICAgIHJldHVybiByZWFkX2pzb25sKHNlbGYuX3BhdGgpCgogICAg"
    "ZGVmIGRlbGV0ZShzZWxmLCByZWNvcmRfaWQ6IHN0cikgLT4gYm9vbDoKICAgICAgICByZWNvcmRz"
    "ID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIGZpbHRlcmVkID0gW3IgZm9yIHIgaW4g"
    "cmVjb3JkcyBpZiByLmdldCgiaWQiKSAhPSByZWNvcmRfaWRdCiAgICAgICAgaWYgbGVuKGZpbHRl"
    "cmVkKSA8IGxlbihyZWNvcmRzKToKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwg"
    "ZmlsdGVyZWQpCiAgICAgICAgICAgIHJldHVybiBUcnVlCiAgICAgICAgcmV0dXJuIEZhbHNlCgog"
    "ICAgZGVmIGJ1aWxkX2NvbnRleHRfZm9yX2xhbmd1YWdlKHNlbGYsIGxhbmd1YWdlOiBzdHIsCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgbWF4X2NoYXJzOiBpbnQgPSAxNTAwKSAt"
    "PiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgQnVpbGQgYSBjb250ZXh0IHN0cmluZyBvZiBhbGwg"
    "cnVsZXMgZm9yIGEgZ2l2ZW4gbGFuZ3VhZ2UuCiAgICAgICAgRm9yIGluamVjdGlvbiBpbnRvIHN5"
    "c3RlbSBwcm9tcHQgYmVmb3JlIGNvZGUgc2Vzc2lvbnMuCiAgICAgICAgIiIiCiAgICAgICAgcmVj"
    "b3JkcyA9IHNlbGYuc2VhcmNoKGxhbmd1YWdlPWxhbmd1YWdlKQogICAgICAgIGlmIG5vdCByZWNv"
    "cmRzOgogICAgICAgICAgICByZXR1cm4gIiIKCiAgICAgICAgcGFydHMgPSBbZiJbe2xhbmd1YWdl"
    "LnVwcGVyKCl9IFJVTEVTIOKAlCBBUFBMWSBCRUZPUkUgV1JJVElORyBDT0RFXSJdCiAgICAgICAg"
    "dG90YWwgPSAwCiAgICAgICAgZm9yIHIgaW4gcmVjb3JkczoKICAgICAgICAgICAgZW50cnkgPSBm"
    "IuKAoiB7ci5nZXQoJ3JlZmVyZW5jZV9rZXknLCcnKX06IHtyLmdldCgnZnVsbF9ydWxlJywnJyl9"
    "IgogICAgICAgICAgICBpZiB0b3RhbCArIGxlbihlbnRyeSkgPiBtYXhfY2hhcnM6CiAgICAgICAg"
    "ICAgICAgICBicmVhawogICAgICAgICAgICBwYXJ0cy5hcHBlbmQoZW50cnkpCiAgICAgICAgICAg"
    "IHRvdGFsICs9IGxlbihlbnRyeSkKCiAgICAgICAgcGFydHMuYXBwZW5kKGYiW0VORCB7bGFuZ3Vh"
    "Z2UudXBwZXIoKX0gUlVMRVNdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBhcnRzKQoKICAg"
    "IGRlZiBfaXNfZHVwbGljYXRlKHNlbGYsIHJlZmVyZW5jZV9rZXk6IHN0cikgLT4gYm9vbDoKICAg"
    "ICAgICByZXR1cm4gYW55KAogICAgICAgICAgICByLmdldCgicmVmZXJlbmNlX2tleSIsIiIpLmxv"
    "d2VyKCkgPT0gcmVmZXJlbmNlX2tleS5sb3dlcigpCiAgICAgICAgICAgIGZvciByIGluIHJlYWRf"
    "anNvbmwoc2VsZi5fcGF0aCkKICAgICAgICApCgogICAgZGVmIHNlZWRfbHNsX3J1bGVzKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgU2VlZCB0aGUgTFNMIEZvcmJpZGRlbiBSdWxl"
    "c2V0IG9uIGZpcnN0IHJ1biBpZiB0aGUgREIgaXMgZW1wdHkuCiAgICAgICAgVGhlc2UgYXJlIHRo"
    "ZSBoYXJkIHJ1bGVzIGZyb20gdGhlIHByb2plY3Qgc3RhbmRpbmcgcnVsZXMuCiAgICAgICAgIiIi"
    "CiAgICAgICAgaWYgcmVhZF9qc29ubChzZWxmLl9wYXRoKToKICAgICAgICAgICAgcmV0dXJuICAj"
    "IEFscmVhZHkgc2VlZGVkCgogICAgICAgIGxzbF9ydWxlcyA9IFsKICAgICAgICAgICAgKCJMU0wi"
    "LCAiTFNMIiwgIk5PX1RFUk5BUlkiLAogICAgICAgICAgICAgIk5vIHRlcm5hcnkgb3BlcmF0b3Jz"
    "IGluIExTTCIsCiAgICAgICAgICAgICAiTmV2ZXIgdXNlIHRoZSB0ZXJuYXJ5IG9wZXJhdG9yICg/"
    "OikgaW4gTFNMIHNjcmlwdHMuICIKICAgICAgICAgICAgICJVc2UgaWYvZWxzZSBibG9ja3MgaW5z"
    "dGVhZC4gTFNMIGRvZXMgbm90IHN1cHBvcnQgdGVybmFyeS4iLAogICAgICAgICAgICAgIlJlcGxh"
    "Y2Ugd2l0aCBpZi9lbHNlIGJsb2NrLiIsICIiKSwKICAgICAgICAgICAgKCJMU0wiLCAiTFNMIiwg"
    "Ik5PX0ZPUkVBQ0giLAogICAgICAgICAgICAgIk5vIGZvcmVhY2ggbG9vcHMgaW4gTFNMIiwKICAg"
    "ICAgICAgICAgICJMU0wgaGFzIG5vIGZvcmVhY2ggbG9vcCBjb25zdHJ1Y3QuIFVzZSBpbnRlZ2Vy"
    "IGluZGV4IHdpdGggIgogICAgICAgICAgICAgImxsR2V0TGlzdExlbmd0aCgpIGFuZCBhIGZvciBv"
    "ciB3aGlsZSBsb29wLiIsCiAgICAgICAgICAgICAiVXNlOiBmb3IoaW50ZWdlciBpPTA7IGk8bGxH"
    "ZXRMaXN0TGVuZ3RoKG15TGlzdCk7IGkrKykiLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxT"
    "TCIsICJOT19HTE9CQUxfQVNTSUdOX0ZST01fRlVOQyIsCiAgICAgICAgICAgICAiTm8gZ2xvYmFs"
    "IHZhcmlhYmxlIGFzc2lnbm1lbnRzIGZyb20gZnVuY3Rpb24gY2FsbHMiLAogICAgICAgICAgICAg"
    "Ikdsb2JhbCB2YXJpYWJsZSBpbml0aWFsaXphdGlvbiBpbiBMU0wgY2Fubm90IGNhbGwgZnVuY3Rp"
    "b25zLiAiCiAgICAgICAgICAgICAiSW5pdGlhbGl6ZSBnbG9iYWxzIHdpdGggbGl0ZXJhbCB2YWx1"
    "ZXMgb25seS4gIgogICAgICAgICAgICAgIkFzc2lnbiBmcm9tIGZ1bmN0aW9ucyBpbnNpZGUgZXZl"
    "bnQgaGFuZGxlcnMgb3Igb3RoZXIgZnVuY3Rpb25zLiIsCiAgICAgICAgICAgICAiTW92ZSB0aGUg"
    "YXNzaWdubWVudCBpbnRvIGFuIGV2ZW50IGhhbmRsZXIgKHN0YXRlX2VudHJ5LCBldGMuKSIsICIi"
    "KSwKICAgICAgICAgICAgKCJMU0wiLCAiTFNMIiwgIk5PX1ZPSURfS0VZV09SRCIsCiAgICAgICAg"
    "ICAgICAiTm8gdm9pZCBrZXl3b3JkIGluIExTTCIsCiAgICAgICAgICAgICAiTFNMIGRvZXMgbm90"
    "IGhhdmUgYSB2b2lkIGtleXdvcmQgZm9yIGZ1bmN0aW9uIHJldHVybiB0eXBlcy4gIgogICAgICAg"
    "ICAgICAgIkZ1bmN0aW9ucyB0aGF0IHJldHVybiBub3RoaW5nIHNpbXBseSBvbWl0IHRoZSByZXR1"
    "cm4gdHlwZS4iLAogICAgICAgICAgICAgIlJlbW92ZSAndm9pZCcgZnJvbSBmdW5jdGlvbiBzaWdu"
    "YXR1cmUuICIKICAgICAgICAgICAgICJlLmcuIG15RnVuYygpIHsgLi4uIH0gbm90IHZvaWQgbXlG"
    "dW5jKCkgeyAuLi4gfSIsICIiKSwKICAgICAgICAgICAgKCJMU0wiLCAiTFNMIiwgIkNPTVBMRVRF"
    "X1NDUklQVFNfT05MWSIsCiAgICAgICAgICAgICAiQWx3YXlzIHByb3ZpZGUgY29tcGxldGUgc2Ny"
    "aXB0cywgbmV2ZXIgcGFydGlhbCBlZGl0cyIsCiAgICAgICAgICAgICAiV2hlbiB3cml0aW5nIG9y"
    "IGVkaXRpbmcgTFNMIHNjcmlwdHMsIGFsd2F5cyBvdXRwdXQgdGhlIGNvbXBsZXRlICIKICAgICAg"
    "ICAgICAgICJzY3JpcHQuIE5ldmVyIHByb3ZpZGUgcGFydGlhbCBzbmlwcGV0cyBvciAnYWRkIHRo"
    "aXMgc2VjdGlvbicgIgogICAgICAgICAgICAgImluc3RydWN0aW9ucy4gVGhlIGZ1bGwgc2NyaXB0"
    "IG11c3QgYmUgY29weS1wYXN0ZSByZWFkeS4iLAogICAgICAgICAgICAgIldyaXRlIHRoZSBlbnRp"
    "cmUgc2NyaXB0IGZyb20gdG9wIHRvIGJvdHRvbS4iLCAiIiksCiAgICAgICAgXQoKICAgICAgICBm"
    "b3IgZW52LCBsYW5nLCByZWYsIHN1bW1hcnksIGZ1bGxfcnVsZSwgcmVzb2x1dGlvbiwgbGluayBp"
    "biBsc2xfcnVsZXM6CiAgICAgICAgICAgIHNlbGYuYWRkKGVudiwgbGFuZywgcmVmLCBzdW1tYXJ5"
    "LCBmdWxsX3J1bGUsIHJlc29sdXRpb24sIGxpbmssCiAgICAgICAgICAgICAgICAgICAgIHRhZ3M9"
    "WyJsc2wiLCAiZm9yYmlkZGVuIiwgInN0YW5kaW5nX3J1bGUiXSkKCgojIOKUgOKUgCBUQVNLIE1B"
    "TkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFRhc2tNYW5hZ2VyOgogICAgIiIiCiAgICBUYXNrL3Jl"
    "bWluZGVyIENSVUQgYW5kIGR1ZS1ldmVudCBkZXRlY3Rpb24uCgogICAgRmlsZTogbWVtb3JpZXMv"
    "dGFza3MuanNvbmwKCiAgICBUYXNrIHJlY29yZCBmaWVsZHM6CiAgICAgICAgaWQsIGNyZWF0ZWRf"
    "YXQsIGR1ZV9hdCwgcHJlX3RyaWdnZXIgKDFtaW4gYmVmb3JlKSwKICAgICAgICB0ZXh0LCBzdGF0"
    "dXMgKHBlbmRpbmd8dHJpZ2dlcmVkfHNub296ZWR8Y29tcGxldGVkfGNhbmNlbGxlZCksCiAgICAg"
    "ICAgYWNrbm93bGVkZ2VkX2F0LCByZXRyeV9jb3VudCwgbGFzdF90cmlnZ2VyZWRfYXQsIG5leHRf"
    "cmV0cnlfYXQsCiAgICAgICAgc291cmNlIChsb2NhbHxnb29nbGUpLCBnb29nbGVfZXZlbnRfaWQs"
    "IHN5bmNfc3RhdHVzLCBtZXRhZGF0YQoKICAgIER1ZS1ldmVudCBjeWNsZToKICAgICAgICAtIFBy"
    "ZS10cmlnZ2VyOiAxIG1pbnV0ZSBiZWZvcmUgZHVlIOKGkiBhbm5vdW5jZSB1cGNvbWluZwogICAg"
    "ICAgIC0gRHVlIHRyaWdnZXI6IGF0IGR1ZSB0aW1lIOKGkiBhbGVydCBzb3VuZCArIEFJIGNvbW1l"
    "bnRhcnkKICAgICAgICAtIDMtbWludXRlIHdpbmRvdzogaWYgbm90IGFja25vd2xlZGdlZCDihpIg"
    "c25vb3plCiAgICAgICAgLSAxMi1taW51dGUgcmV0cnk6IHJlLXRyaWdnZXIKICAgICIiIgoKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBzZWxmLl9wYXRoID0gY2ZnX3BhdGgoIm1lbW9y"
    "aWVzIikgLyAidGFza3MuanNvbmwiCgogICAgIyDilIDilIAgQ1JVRCDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBs"
    "b2FkX2FsbChzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgIHRhc2tzID0gcmVhZF9qc29ubChz"
    "ZWxmLl9wYXRoKQogICAgICAgIGNoYW5nZWQgPSBGYWxzZQogICAgICAgIG5vcm1hbGl6ZWQgPSBb"
    "XQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiBub3QgaXNpbnN0YW5jZSh0"
    "LCBkaWN0KToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmICJpZCIgbm90"
    "IGluIHQ6CiAgICAgICAgICAgICAgICB0WyJpZCJdID0gZiJ0YXNrX3t1dWlkLnV1aWQ0KCkuaGV4"
    "WzoxMF19IgogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgIyBOb3Jt"
    "YWxpemUgZmllbGQgbmFtZXMKICAgICAgICAgICAgaWYgImR1ZV9hdCIgbm90IGluIHQ6CiAgICAg"
    "ICAgICAgICAgICB0WyJkdWVfYXQiXSA9IHQuZ2V0KCJkdWUiKQogICAgICAgICAgICAgICAgY2hh"
    "bmdlZCA9IFRydWUKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJzdGF0dXMiLCAgICAgICAgICAg"
    "InBlbmRpbmciKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoInJldHJ5X2NvdW50IiwgICAgICAw"
    "KQogICAgICAgICAgICB0LnNldGRlZmF1bHQoImFja25vd2xlZGdlZF9hdCIsICBOb25lKQogICAg"
    "ICAgICAgICB0LnNldGRlZmF1bHQoImxhc3RfdHJpZ2dlcmVkX2F0IixOb25lKQogICAgICAgICAg"
    "ICB0LnNldGRlZmF1bHQoIm5leHRfcmV0cnlfYXQiLCAgICBOb25lKQogICAgICAgICAgICB0LnNl"
    "dGRlZmF1bHQoInByZV9hbm5vdW5jZWQiLCAgICBGYWxzZSkKICAgICAgICAgICAgdC5zZXRkZWZh"
    "dWx0KCJzb3VyY2UiLCAgICAgICAgICAgImxvY2FsIikKICAgICAgICAgICAgdC5zZXRkZWZhdWx0"
    "KCJnb29nbGVfZXZlbnRfaWQiLCAgTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJzeW5j"
    "X3N0YXR1cyIsICAgICAgInBlbmRpbmciKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoIm1ldGFk"
    "YXRhIiwgICAgICAgICB7fSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJjcmVhdGVkX2F0Iiwg"
    "ICAgICAgbG9jYWxfbm93X2lzbygpKQoKICAgICAgICAgICAgIyBDb21wdXRlIHByZV90cmlnZ2Vy"
    "IGlmIG1pc3NpbmcKICAgICAgICAgICAgaWYgdC5nZXQoImR1ZV9hdCIpIGFuZCBub3QgdC5nZXQo"
    "InByZV90cmlnZ2VyIik6CiAgICAgICAgICAgICAgICBkdCA9IHBhcnNlX2lzbyh0WyJkdWVfYXQi"
    "XSkKICAgICAgICAgICAgICAgIGlmIGR0OgogICAgICAgICAgICAgICAgICAgIHByZSA9IGR0IC0g"
    "dGltZWRlbHRhKG1pbnV0ZXM9MSkKICAgICAgICAgICAgICAgICAgICB0WyJwcmVfdHJpZ2dlciJd"
    "ID0gcHJlLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICAgICAg"
    "Y2hhbmdlZCA9IFRydWUKCiAgICAgICAgICAgIG5vcm1hbGl6ZWQuYXBwZW5kKHQpCgogICAgICAg"
    "IGlmIGNoYW5nZWQ6CiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIG5vcm1hbGl6"
    "ZWQpCiAgICAgICAgcmV0dXJuIG5vcm1hbGl6ZWQKCiAgICBkZWYgc2F2ZV9hbGwoc2VsZiwgdGFz"
    "a3M6IGxpc3RbZGljdF0pIC0+IE5vbmU6CiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwg"
    "dGFza3MpCgogICAgZGVmIGFkZChzZWxmLCB0ZXh0OiBzdHIsIGR1ZV9kdDogZGF0ZXRpbWUsCiAg"
    "ICAgICAgICAgIHNvdXJjZTogc3RyID0gImxvY2FsIikgLT4gZGljdDoKICAgICAgICBwcmUgPSBk"
    "dWVfZHQgLSB0aW1lZGVsdGEobWludXRlcz0xKQogICAgICAgIHRhc2sgPSB7CiAgICAgICAgICAg"
    "ICJpZCI6ICAgICAgICAgICAgICAgZiJ0YXNrX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19IiwKICAg"
    "ICAgICAgICAgImNyZWF0ZWRfYXQiOiAgICAgICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAg"
    "ICJkdWVfYXQiOiAgICAgICAgICAgZHVlX2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIp"
    "LAogICAgICAgICAgICAicHJlX3RyaWdnZXIiOiAgICAgIHByZS5pc29mb3JtYXQodGltZXNwZWM9"
    "InNlY29uZHMiKSwKICAgICAgICAgICAgInRleHQiOiAgICAgICAgICAgICB0ZXh0LnN0cmlwKCks"
    "CiAgICAgICAgICAgICJzdGF0dXMiOiAgICAgICAgICAgInBlbmRpbmciLAogICAgICAgICAgICAi"
    "YWNrbm93bGVkZ2VkX2F0IjogIE5vbmUsCiAgICAgICAgICAgICJyZXRyeV9jb3VudCI6ICAgICAg"
    "MCwKICAgICAgICAgICAgImxhc3RfdHJpZ2dlcmVkX2F0IjpOb25lLAogICAgICAgICAgICAibmV4"
    "dF9yZXRyeV9hdCI6ICAgIE5vbmUsCiAgICAgICAgICAgICJwcmVfYW5ub3VuY2VkIjogICAgRmFs"
    "c2UsCiAgICAgICAgICAgICJzb3VyY2UiOiAgICAgICAgICAgc291cmNlLAogICAgICAgICAgICAi"
    "Z29vZ2xlX2V2ZW50X2lkIjogIE5vbmUsCiAgICAgICAgICAgICJzeW5jX3N0YXR1cyI6ICAgICAg"
    "InBlbmRpbmciLAogICAgICAgICAgICAibWV0YWRhdGEiOiAgICAgICAgIHt9LAogICAgICAgIH0K"
    "ICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIHRhc2tzLmFwcGVuZCh0YXNr"
    "KQogICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgcmV0dXJuIHRhc2sKCiAgICBk"
    "ZWYgdXBkYXRlX3N0YXR1cyhzZWxmLCB0YXNrX2lkOiBzdHIsIHN0YXR1czogc3RyLAogICAgICAg"
    "ICAgICAgICAgICAgICAgYWNrbm93bGVkZ2VkOiBib29sID0gRmFsc2UpIC0+IE9wdGlvbmFsW2Rp"
    "Y3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9yIHQgaW4gdGFz"
    "a3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09IHRhc2tfaWQ6CiAgICAgICAgICAgICAg"
    "ICB0WyJzdGF0dXMiXSA9IHN0YXR1cwogICAgICAgICAgICAgICAgaWYgYWNrbm93bGVkZ2VkOgog"
    "ICAgICAgICAgICAgICAgICAgIHRbImFja25vd2xlZGdlZF9hdCJdID0gbG9jYWxfbm93X2lzbygp"
    "CiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICAgICAgcmV0"
    "dXJuIHQKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBjb21wbGV0ZShzZWxmLCB0YXNrX2lk"
    "OiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgp"
    "CiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09IHRh"
    "c2tfaWQ6CiAgICAgICAgICAgICAgICB0WyJzdGF0dXMiXSAgICAgICAgICA9ICJjb21wbGV0ZWQi"
    "CiAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQog"
    "ICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVy"
    "biB0CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY2FuY2VsKHNlbGYsIHRhc2tfaWQ6IHN0"
    "cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAg"
    "ICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0gdGFza19p"
    "ZDoKICAgICAgICAgICAgICAgIHRbInN0YXR1cyJdICAgICAgICAgID0gImNhbmNlbGxlZCIKICAg"
    "ICAgICAgICAgICAgIHRbImFja25vd2xlZGdlZF9hdCJdID0gbG9jYWxfbm93X2lzbygpCiAgICAg"
    "ICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICAgICAgcmV0dXJuIHQK"
    "ICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBjbGVhcl9jb21wbGV0ZWQoc2VsZikgLT4gaW50"
    "OgogICAgICAgIHRhc2tzICAgID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAga2VwdCAgICAgPSBb"
    "dCBmb3IgdCBpbiB0YXNrcwogICAgICAgICAgICAgICAgICAgIGlmIHQuZ2V0KCJzdGF0dXMiKSBu"
    "b3QgaW4geyJjb21wbGV0ZWQiLCJjYW5jZWxsZWQifV0KICAgICAgICByZW1vdmVkICA9IGxlbih0"
    "YXNrcykgLSBsZW4oa2VwdCkKICAgICAgICBpZiByZW1vdmVkOgogICAgICAgICAgICBzZWxmLnNh"
    "dmVfYWxsKGtlcHQpCiAgICAgICAgcmV0dXJuIHJlbW92ZWQKCiAgICBkZWYgdXBkYXRlX2dvb2ds"
    "ZV9zeW5jKHNlbGYsIHRhc2tfaWQ6IHN0ciwgc3luY19zdGF0dXM6IHN0ciwKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgZ29vZ2xlX2V2ZW50X2lkOiBzdHIgPSAiIiwKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgZXJyb3I6IHN0ciA9ICIiKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0"
    "YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAg"
    "ICBpZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsic3luY19zdGF0"
    "dXMiXSAgICA9IHN5bmNfc3RhdHVzCiAgICAgICAgICAgICAgICB0WyJsYXN0X3N5bmNlZF9hdCJd"
    "ID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgICAgICBpZiBnb29nbGVfZXZlbnRfaWQ6CiAg"
    "ICAgICAgICAgICAgICAgICAgdFsiZ29vZ2xlX2V2ZW50X2lkIl0gPSBnb29nbGVfZXZlbnRfaWQK"
    "ICAgICAgICAgICAgICAgIGlmIGVycm9yOgogICAgICAgICAgICAgICAgICAgIHQuc2V0ZGVmYXVs"
    "dCgibWV0YWRhdGEiLCB7fSkKICAgICAgICAgICAgICAgICAgICB0WyJtZXRhZGF0YSJdWyJnb29n"
    "bGVfc3luY19lcnJvciJdID0gZXJyb3JbOjI0MF0KICAgICAgICAgICAgICAgIHNlbGYuc2F2ZV9h"
    "bGwodGFza3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgog"
    "ICAgIyDilIDilIAgRFVFIEVWRU5UIERFVEVDVElPTiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRl"
    "ZiBnZXRfZHVlX2V2ZW50cyhzZWxmKSAtPiBsaXN0W3R1cGxlW3N0ciwgZGljdF1dOgogICAgICAg"
    "ICIiIgogICAgICAgIENoZWNrIGFsbCB0YXNrcyBmb3IgZHVlL3ByZS10cmlnZ2VyL3JldHJ5IGV2"
    "ZW50cy4KICAgICAgICBSZXR1cm5zIGxpc3Qgb2YgKGV2ZW50X3R5cGUsIHRhc2spIHR1cGxlcy4K"
    "ICAgICAgICBldmVudF90eXBlOiAicHJlIiB8ICJkdWUiIHwgInJldHJ5IgoKICAgICAgICBNb2Rp"
    "ZmllcyB0YXNrIHN0YXR1c2VzIGluIHBsYWNlIGFuZCBzYXZlcy4KICAgICAgICBDYWxsIGZyb20g"
    "QVBTY2hlZHVsZXIgZXZlcnkgMzAgc2Vjb25kcy4KICAgICAgICAiIiIKICAgICAgICBub3cgICAg"
    "PSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkKICAgICAgICB0YXNrcyAgPSBzZWxmLmxvYWRf"
    "YWxsKCkKICAgICAgICBldmVudHMgPSBbXQogICAgICAgIGNoYW5nZWQgPSBGYWxzZQoKICAgICAg"
    "ICBmb3IgdGFzayBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdGFzay5nZXQoImFja25vd2xlZGdl"
    "ZF9hdCIpOgogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgIHN0YXR1cyAgID0g"
    "dGFzay5nZXQoInN0YXR1cyIsICJwZW5kaW5nIikKICAgICAgICAgICAgZHVlICAgICAgPSBzZWxm"
    "Ll9wYXJzZV9sb2NhbCh0YXNrLmdldCgiZHVlX2F0IikpCiAgICAgICAgICAgIHByZSAgICAgID0g"
    "c2VsZi5fcGFyc2VfbG9jYWwodGFzay5nZXQoInByZV90cmlnZ2VyIikpCiAgICAgICAgICAgIG5l"
    "eHRfcmV0ID0gc2VsZi5fcGFyc2VfbG9jYWwodGFzay5nZXQoIm5leHRfcmV0cnlfYXQiKSkKICAg"
    "ICAgICAgICAgZGVhZGxpbmUgPSBzZWxmLl9wYXJzZV9sb2NhbCh0YXNrLmdldCgiYWxlcnRfZGVh"
    "ZGxpbmUiKSkKCiAgICAgICAgICAgICMgUHJlLXRyaWdnZXIKICAgICAgICAgICAgaWYgKHN0YXR1"
    "cyA9PSAicGVuZGluZyIgYW5kIHByZSBhbmQgbm93ID49IHByZQogICAgICAgICAgICAgICAgICAg"
    "IGFuZCBub3QgdGFzay5nZXQoInByZV9hbm5vdW5jZWQiKSk6CiAgICAgICAgICAgICAgICB0YXNr"
    "WyJwcmVfYW5ub3VuY2VkIl0gPSBUcnVlCiAgICAgICAgICAgICAgICBldmVudHMuYXBwZW5kKCgi"
    "cHJlIiwgdGFzaykpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgICAgICAgICAg"
    "IyBEdWUgdHJpZ2dlcgogICAgICAgICAgICBpZiBzdGF0dXMgPT0gInBlbmRpbmciIGFuZCBkdWUg"
    "YW5kIG5vdyA+PSBkdWU6CiAgICAgICAgICAgICAgICB0YXNrWyJzdGF0dXMiXSAgICAgICAgICAg"
    "PSAidHJpZ2dlcmVkIgogICAgICAgICAgICAgICAgdGFza1sibGFzdF90cmlnZ2VyZWRfYXQiXT0g"
    "bG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgICAgICB0YXNrWyJhbGVydF9kZWFkbGluZSJdICAg"
    "PSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpICsgdGlt"
    "ZWRlbHRhKG1pbnV0ZXM9MykKICAgICAgICAgICAgICAgICkuaXNvZm9ybWF0KHRpbWVzcGVjPSJz"
    "ZWNvbmRzIikKICAgICAgICAgICAgICAgIGV2ZW50cy5hcHBlbmQoKCJkdWUiLCB0YXNrKSkKICAg"
    "ICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAg"
    "ICAgICAgICAgIyBTbm9vemUgYWZ0ZXIgMy1taW51dGUgd2luZG93CiAgICAgICAgICAgIGlmIHN0"
    "YXR1cyA9PSAidHJpZ2dlcmVkIiBhbmQgZGVhZGxpbmUgYW5kIG5vdyA+PSBkZWFkbGluZToKICAg"
    "ICAgICAgICAgICAgIHRhc2tbInN0YXR1cyJdICAgICAgICA9ICJzbm9vemVkIgogICAgICAgICAg"
    "ICAgICAgdGFza1sibmV4dF9yZXRyeV9hdCJdID0gKAogICAgICAgICAgICAgICAgICAgIGRhdGV0"
    "aW1lLm5vdygpLmFzdGltZXpvbmUoKSArIHRpbWVkZWx0YShtaW51dGVzPTEyKQogICAgICAgICAg"
    "ICAgICAgKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgY2hh"
    "bmdlZCA9IFRydWUKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICAjIFJldHJ5"
    "CiAgICAgICAgICAgIGlmIHN0YXR1cyBpbiB7InJldHJ5X3BlbmRpbmciLCJzbm9vemVkIn0gYW5k"
    "IG5leHRfcmV0IGFuZCBub3cgPj0gbmV4dF9yZXQ6CiAgICAgICAgICAgICAgICB0YXNrWyJzdGF0"
    "dXMiXSAgICAgICAgICAgID0gInRyaWdnZXJlZCIKICAgICAgICAgICAgICAgIHRhc2tbInJldHJ5"
    "X2NvdW50Il0gICAgICAgPSBpbnQodGFzay5nZXQoInJldHJ5X2NvdW50IiwwKSkgKyAxCiAgICAg"
    "ICAgICAgICAgICB0YXNrWyJsYXN0X3RyaWdnZXJlZF9hdCJdID0gbG9jYWxfbm93X2lzbygpCiAg"
    "ICAgICAgICAgICAgICB0YXNrWyJhbGVydF9kZWFkbGluZSJdICAgID0gKAogICAgICAgICAgICAg"
    "ICAgICAgIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKSArIHRpbWVkZWx0YShtaW51dGVzPTMp"
    "CiAgICAgICAgICAgICAgICApLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAg"
    "ICAgICAgICB0YXNrWyJuZXh0X3JldHJ5X2F0Il0gICAgID0gTm9uZQogICAgICAgICAgICAgICAg"
    "ZXZlbnRzLmFwcGVuZCgoInJldHJ5IiwgdGFzaykpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0g"
    "VHJ1ZQoKICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tz"
    "KQogICAgICAgIHJldHVybiBldmVudHMKCiAgICBkZWYgX3BhcnNlX2xvY2FsKHNlbGYsIHZhbHVl"
    "OiBzdHIpIC0+IE9wdGlvbmFsW2RhdGV0aW1lXToKICAgICAgICAiIiJQYXJzZSBJU08gc3RyaW5n"
    "IHRvIHRpbWV6b25lLWF3YXJlIGRhdGV0aW1lIGZvciBjb21wYXJpc29uLiIiIgogICAgICAgIGR0"
    "ID0gcGFyc2VfaXNvKHZhbHVlKQogICAgICAgIGlmIGR0IGlzIE5vbmU6CiAgICAgICAgICAgIHJl"
    "dHVybiBOb25lCiAgICAgICAgaWYgZHQudHppbmZvIGlzIE5vbmU6CiAgICAgICAgICAgIGR0ID0g"
    "ZHQuYXN0aW1lem9uZSgpCiAgICAgICAgcmV0dXJuIGR0CgogICAgIyDilIDilIAgTkFUVVJBTCBM"
    "QU5HVUFHRSBQQVJTSU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgQHN0YXRpY21ldGhvZAogICAgZGVmIGNsYXNzaWZ5X2lu"
    "dGVudCh0ZXh0OiBzdHIpIC0+IGRpY3Q6CiAgICAgICAgIiIiCiAgICAgICAgQ2xhc3NpZnkgdXNl"
    "ciBpbnB1dCBhcyB0YXNrL3JlbWluZGVyL3RpbWVyL2NoYXQuCiAgICAgICAgUmV0dXJucyB7Imlu"
    "dGVudCI6IHN0ciwgImNsZWFuZWRfaW5wdXQiOiBzdHJ9CiAgICAgICAgIiIiCiAgICAgICAgaW1w"
    "b3J0IHJlCiAgICAgICAgIyBTdHJpcCBjb21tb24gaW52b2NhdGlvbiBwcmVmaXhlcwogICAgICAg"
    "IGNsZWFuZWQgPSByZS5zdWIoCiAgICAgICAgICAgIHJmIl5ccyooPzp7REVDS19OQU1FLmxvd2Vy"
    "KCl9fGhleVxzK3tERUNLX05BTUUubG93ZXIoKX0pXHMqLD9ccypbOlwtXT9ccyoiLAogICAgICAg"
    "ICAgICAiIiwgdGV4dCwgZmxhZ3M9cmUuSQogICAgICAgICkuc3RyaXAoKQoKICAgICAgICBsb3cg"
    "PSBjbGVhbmVkLmxvd2VyKCkKCiAgICAgICAgdGltZXJfcGF0cyAgICA9IFtyIlxic2V0KD86XHMr"
    "YSk/XHMrdGltZXJcYiIsIHIiXGJ0aW1lclxzK2ZvclxiIiwKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIHIiXGJzdGFydCg/OlxzK2EpP1xzK3RpbWVyXGIiXQogICAgICAgIHJlbWluZGVyX3BhdHMg"
    "PSBbciJcYnJlbWluZCBtZVxiIiwgciJcYnNldCg/OlxzK2EpP1xzK3JlbWluZGVyXGIiLAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgciJcYmFkZCg/OlxzK2EpP1xzK3JlbWluZGVyXGIiLAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgciJcYnNldCg/OlxzK2FuPyk/XHMrYWxhcm1cYiIsIHIiXGJh"
    "bGFybVxzK2ZvclxiIl0KICAgICAgICB0YXNrX3BhdHMgICAgID0gW3IiXGJhZGQoPzpccythKT9c"
    "cyt0YXNrXGIiLAogICAgICAgICAgICAgICAgICAgICAgICAgciJcYmNyZWF0ZSg/OlxzK2EpP1xz"
    "K3Rhc2tcYiIsIHIiXGJuZXdccyt0YXNrXGIiXQoKICAgICAgICBpbXBvcnQgcmUgYXMgX3JlCiAg"
    "ICAgICAgaWYgYW55KF9yZS5zZWFyY2gocCwgbG93KSBmb3IgcCBpbiB0aW1lcl9wYXRzKToKICAg"
    "ICAgICAgICAgaW50ZW50ID0gInRpbWVyIgogICAgICAgIGVsaWYgYW55KF9yZS5zZWFyY2gocCwg"
    "bG93KSBmb3IgcCBpbiByZW1pbmRlcl9wYXRzKToKICAgICAgICAgICAgaW50ZW50ID0gInJlbWlu"
    "ZGVyIgogICAgICAgIGVsaWYgYW55KF9yZS5zZWFyY2gocCwgbG93KSBmb3IgcCBpbiB0YXNrX3Bh"
    "dHMpOgogICAgICAgICAgICBpbnRlbnQgPSAidGFzayIKICAgICAgICBlbHNlOgogICAgICAgICAg"
    "ICBpbnRlbnQgPSAiY2hhdCIKCiAgICAgICAgcmV0dXJuIHsiaW50ZW50IjogaW50ZW50LCAiY2xl"
    "YW5lZF9pbnB1dCI6IGNsZWFuZWR9CgogICAgQHN0YXRpY21ldGhvZAogICAgZGVmIHBhcnNlX2R1"
    "ZV9kYXRldGltZSh0ZXh0OiBzdHIpIC0+IE9wdGlvbmFsW2RhdGV0aW1lXToKICAgICAgICAiIiIK"
    "ICAgICAgICBQYXJzZSBuYXR1cmFsIGxhbmd1YWdlIHRpbWUgZXhwcmVzc2lvbiBmcm9tIHRhc2sg"
    "dGV4dC4KICAgICAgICBIYW5kbGVzOiAiaW4gMzAgbWludXRlcyIsICJhdCAzcG0iLCAidG9tb3Jy"
    "b3cgYXQgOWFtIiwKICAgICAgICAgICAgICAgICAiaW4gMiBob3VycyIsICJhdCAxNTozMCIsIGV0"
    "Yy4KICAgICAgICBSZXR1cm5zIGEgZGF0ZXRpbWUgb3IgTm9uZSBpZiB1bnBhcnNlYWJsZS4KICAg"
    "ICAgICAiIiIKICAgICAgICBpbXBvcnQgcmUKICAgICAgICBub3cgID0gZGF0ZXRpbWUubm93KCkK"
    "ICAgICAgICBsb3cgID0gdGV4dC5sb3dlcigpLnN0cmlwKCkKCiAgICAgICAgIyAiaW4gWCBtaW51"
    "dGVzL2hvdXJzL2RheXMiCiAgICAgICAgbSA9IHJlLnNlYXJjaCgKICAgICAgICAgICAgciJpblxz"
    "KyhcZCspXHMqKG1pbnV0ZXxtaW58aG91cnxocnxkYXl8c2Vjb25kfHNlYykiLAogICAgICAgICAg"
    "ICBsb3cKICAgICAgICApCiAgICAgICAgaWYgbToKICAgICAgICAgICAgbiAgICA9IGludChtLmdy"
    "b3VwKDEpKQogICAgICAgICAgICB1bml0ID0gbS5ncm91cCgyKQogICAgICAgICAgICBpZiAibWlu"
    "IiBpbiB1bml0OiAgcmV0dXJuIG5vdyArIHRpbWVkZWx0YShtaW51dGVzPW4pCiAgICAgICAgICAg"
    "IGlmICJob3VyIiBpbiB1bml0IG9yICJociIgaW4gdW5pdDogcmV0dXJuIG5vdyArIHRpbWVkZWx0"
    "YShob3Vycz1uKQogICAgICAgICAgICBpZiAiZGF5IiAgaW4gdW5pdDogcmV0dXJuIG5vdyArIHRp"
    "bWVkZWx0YShkYXlzPW4pCiAgICAgICAgICAgIGlmICJzZWMiICBpbiB1bml0OiByZXR1cm4gbm93"
    "ICsgdGltZWRlbHRhKHNlY29uZHM9bikKCiAgICAgICAgIyAiYXQgSEg6TU0iIG9yICJhdCBIOk1N"
    "YW0vcG0iCiAgICAgICAgbSA9IHJlLnNlYXJjaCgKICAgICAgICAgICAgciJhdFxzKyhcZHsxLDJ9"
    "KSg/OjooXGR7Mn0pKT9ccyooYW18cG0pPyIsCiAgICAgICAgICAgIGxvdwogICAgICAgICkKICAg"
    "ICAgICBpZiBtOgogICAgICAgICAgICBociAgPSBpbnQobS5ncm91cCgxKSkKICAgICAgICAgICAg"
    "bW4gID0gaW50KG0uZ3JvdXAoMikpIGlmIG0uZ3JvdXAoMikgZWxzZSAwCiAgICAgICAgICAgIGFw"
    "bSA9IG0uZ3JvdXAoMykKICAgICAgICAgICAgaWYgYXBtID09ICJwbSIgYW5kIGhyIDwgMTI6IGhy"
    "ICs9IDEyCiAgICAgICAgICAgIGlmIGFwbSA9PSAiYW0iIGFuZCBociA9PSAxMjogaHIgPSAwCiAg"
    "ICAgICAgICAgIGR0ID0gbm93LnJlcGxhY2UoaG91cj1ociwgbWludXRlPW1uLCBzZWNvbmQ9MCwg"
    "bWljcm9zZWNvbmQ9MCkKICAgICAgICAgICAgaWYgZHQgPD0gbm93OgogICAgICAgICAgICAgICAg"
    "ZHQgKz0gdGltZWRlbHRhKGRheXM9MSkKICAgICAgICAgICAgcmV0dXJuIGR0CgogICAgICAgICMg"
    "InRvbW9ycm93IGF0IC4uLiIgIChyZWN1cnNlIG9uIHRoZSAiYXQiIHBhcnQpCiAgICAgICAgaWYg"
    "InRvbW9ycm93IiBpbiBsb3c6CiAgICAgICAgICAgIHRvbW9ycm93X3RleHQgPSByZS5zdWIociJ0"
    "b21vcnJvdyIsICIiLCBsb3cpLnN0cmlwKCkKICAgICAgICAgICAgcmVzdWx0ID0gVGFza01hbmFn"
    "ZXIucGFyc2VfZHVlX2RhdGV0aW1lKHRvbW9ycm93X3RleHQpCiAgICAgICAgICAgIGlmIHJlc3Vs"
    "dDoKICAgICAgICAgICAgICAgIHJldHVybiByZXN1bHQgKyB0aW1lZGVsdGEoZGF5cz0xKQoKICAg"
    "ICAgICByZXR1cm4gTm9uZQoKCiMg4pSA4pSAIFJFUVVJUkVNRU5UUy5UWFQgR0VORVJBVE9SIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgd3JpdGVfcmVxdWlyZW1lbnRzX3R4dCgp"
    "IC0+IE5vbmU6CiAgICAiIiIKICAgIFdyaXRlIHJlcXVpcmVtZW50cy50eHQgbmV4dCB0byB0aGUg"
    "ZGVjayBmaWxlIG9uIGZpcnN0IHJ1bi4KICAgIEhlbHBzIHVzZXJzIGluc3RhbGwgYWxsIGRlcGVu"
    "ZGVuY2llcyB3aXRoIG9uZSBwaXAgY29tbWFuZC4KICAgICIiIgogICAgcmVxX3BhdGggPSBQYXRo"
    "KENGRy5nZXQoImJhc2VfZGlyIiwgc3RyKFNDUklQVF9ESVIpKSkgLyAicmVxdWlyZW1lbnRzLnR4"
    "dCIKICAgIGlmIHJlcV9wYXRoLmV4aXN0cygpOgogICAgICAgIHJldHVybgoKICAgIGNvbnRlbnQg"
    "PSAiIiJcCiMgTW9yZ2FubmEgRGVjayDigJQgUmVxdWlyZWQgRGVwZW5kZW5jaWVzCiMgSW5zdGFs"
    "bCBhbGwgd2l0aDogcGlwIGluc3RhbGwgLXIgcmVxdWlyZW1lbnRzLnR4dAoKIyBDb3JlIFVJClB5"
    "U2lkZTYKCiMgU2NoZWR1bGluZyAoaWRsZSB0aW1lciwgYXV0b3NhdmUsIHJlZmxlY3Rpb24gY3lj"
    "bGVzKQphcHNjaGVkdWxlcgoKIyBMb2dnaW5nCmxvZ3VydQoKIyBTb3VuZCBwbGF5YmFjayAoV0FW"
    "ICsgTVAzKQpweWdhbWUKCiMgRGVza3RvcCBzaG9ydGN1dCBjcmVhdGlvbiAoV2luZG93cyBvbmx5"
    "KQpweXdpbjMyCgojIFN5c3RlbSBtb25pdG9yaW5nIChDUFUsIFJBTSwgZHJpdmVzLCBuZXR3b3Jr"
    "KQpwc3V0aWwKCiMgSFRUUCByZXF1ZXN0cwpyZXF1ZXN0cwoKIyBHb29nbGUgaW50ZWdyYXRpb24g"
    "KENhbGVuZGFyLCBEcml2ZSwgRG9jcywgR21haWwpCmdvb2dsZS1hcGktcHl0aG9uLWNsaWVudApn"
    "b29nbGUtYXV0aC1vYXV0aGxpYgpnb29nbGUtYXV0aAoKIyDilIDilIAgT3B0aW9uYWwgKGxvY2Fs"
    "IG1vZGVsIG9ubHkpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFVuY29tbWVudCBpZiB1c2lu"
    "ZyBhIGxvY2FsIEh1Z2dpbmdGYWNlIG1vZGVsOgojIHRvcmNoCiMgdHJhbnNmb3JtZXJzCiMgYWNj"
    "ZWxlcmF0ZQoKIyDilIDilIAgT3B0aW9uYWwgKE5WSURJQSBHUFUgbW9uaXRvcmluZykg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiMgVW5jb21tZW50IGlmIHlvdSBoYXZlIGFuIE5WSURJQSBHUFU6CiMgcHludm1sCiIiIgogICAg"
    "cmVxX3BhdGgud3JpdGVfdGV4dChjb250ZW50LCBlbmNvZGluZz0idXRmLTgiKQoKCiMg4pSA4pSA"
    "IFBBU1MgNCBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKIyBNZW1vcnksIFNlc3Npb24sIExlc3NvbnNMZWFybmVk"
    "LCBUYXNrTWFuYWdlciBhbGwgZGVmaW5lZC4KIyBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgYXV0by1z"
    "ZWVkZWQgb24gZmlyc3QgcnVuLgojIHJlcXVpcmVtZW50cy50eHQgd3JpdHRlbiBvbiBmaXJzdCBy"
    "dW4uCiMKIyBOZXh0OiBQYXNzIDUg4oCUIFRhYiBDb250ZW50IENsYXNzZXMKIyAoU0xTY2Fuc1Rh"
    "YiwgU0xDb21tYW5kc1RhYiwgSm9iVHJhY2tlclRhYiwgUmVjb3Jkc1RhYiwKIyAgVGFza3NUYWIs"
    "IFNlbGZUYWIsIERpYWdub3N0aWNzVGFiKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDi"
    "gJQgUEFTUyA1OiBUQUIgQ09OVEVOVCBDTEFTU0VTCiMKIyBUYWJzIGRlZmluZWQgaGVyZToKIyAg"
    "IFNMU2NhbnNUYWIgICAgICDigJQgZ3JpbW9pcmUtY2FyZCBzdHlsZSwgcmVidWlsdCAoRGVsZXRl"
    "IGFkZGVkLCBNb2RpZnkgZml4ZWQsCiMgICAgICAgICAgICAgICAgICAgICBwYXJzZXIgZml4ZWQs"
    "IGNvcHktdG8tY2xpcGJvYXJkIHBlciBpdGVtKQojICAgU0xDb21tYW5kc1RhYiAgIOKAlCBnb3Ro"
    "aWMgdGFibGUsIGNvcHkgY29tbWFuZCB0byBjbGlwYm9hcmQKIyAgIEpvYlRyYWNrZXJUYWIgICDi"
    "gJQgZnVsbCByZWJ1aWxkIGZyb20gc3BlYywgQ1NWL1RTViBleHBvcnQKIyAgIFJlY29yZHNUYWIg"
    "ICAgICDigJQgR29vZ2xlIERyaXZlL0RvY3Mgd29ya3NwYWNlCiMgICBUYXNrc1RhYiAgICAgICAg"
    "4oCUIHRhc2sgcmVnaXN0cnkgKyBtaW5pIGNhbGVuZGFyCiMgICBTZWxmVGFiICAgICAgICAg4oCU"
    "IGlkbGUgbmFycmF0aXZlIG91dHB1dCArIFBvSSBsaXN0CiMgICBEaWFnbm9zdGljc1RhYiAg4oCU"
    "IGxvZ3VydSBvdXRwdXQgKyBoYXJkd2FyZSByZXBvcnQgKyBqb3VybmFsIGxvYWQgbm90aWNlcwoj"
    "ICAgTGVzc29uc1RhYiAgICAgIOKAlCBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgKyBjb2RlIGxlc3Nv"
    "bnMgYnJvd3NlcgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0IHJlIGFzIF9yZQoKCiMg4pSA4pSAIFNIQVJF"
    "RCBHT1RISUMgVEFCTEUgU1RZTEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRl"
    "ZiBfZ290aGljX3RhYmxlX3N0eWxlKCkgLT4gc3RyOgogICAgcmV0dXJuIGYiIiIKICAgICAgICBR"
    "VGFibGVXaWRnZXQge3sKICAgICAgICAgICAgYmFja2dyb3VuZDoge0NfQkcyfTsKICAgICAgICAg"
    "ICAgY29sb3I6IHtDX0dPTER9OwogICAgICAgICAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklN"
    "U09OX0RJTX07CiAgICAgICAgICAgIGdyaWRsaW5lLWNvbG9yOiB7Q19CT1JERVJ9OwogICAgICAg"
    "ICAgICBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOwogICAgICAgICAgICBmb250LXNp"
    "emU6IDExcHg7CiAgICAgICAgfX0KICAgICAgICBRVGFibGVXaWRnZXQ6Oml0ZW06c2VsZWN0ZWQg"
    "e3sKICAgICAgICAgICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAgICBj"
    "b2xvcjoge0NfR09MRF9CUklHSFR9OwogICAgICAgIH19CiAgICAgICAgUVRhYmxlV2lkZ2V0Ojpp"
    "dGVtOmFsdGVybmF0ZSB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgICAg"
    "IH19CiAgICAgICAgUUhlYWRlclZpZXc6OnNlY3Rpb24ge3sKICAgICAgICAgICAgYmFja2dyb3Vu"
    "ZDoge0NfQkczfTsKICAgICAgICAgICAgY29sb3I6IHtDX0dPTER9OwogICAgICAgICAgICBib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICAgICAgICAgIHBhZGRpbmc6IDRweCA2"
    "cHg7CiAgICAgICAgICAgIGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7CiAgICAgICAg"
    "ICAgIGZvbnQtc2l6ZTogMTBweDsKICAgICAgICAgICAgZm9udC13ZWlnaHQ6IGJvbGQ7CiAgICAg"
    "ICAgICAgIGxldHRlci1zcGFjaW5nOiAxcHg7CiAgICAgICAgfX0KICAgICIiIgoKZGVmIF9nb3Ro"
    "aWNfYnRuKHRleHQ6IHN0ciwgdG9vbHRpcDogc3RyID0gIiIpIC0+IFFQdXNoQnV0dG9uOgogICAg"
    "YnRuID0gUVB1c2hCdXR0b24odGV4dCkKICAgIGJ0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgIGYi"
    "YmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICBm"
    "ImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAg"
    "ICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsg"
    "IgogICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDRweCAxMHB4OyBsZXR0ZXIt"
    "c3BhY2luZzogMXB4OyIKICAgICkKICAgIGlmIHRvb2x0aXA6CiAgICAgICAgYnRuLnNldFRvb2xU"
    "aXAodG9vbHRpcCkKICAgIHJldHVybiBidG4KCmRlZiBfc2VjdGlvbl9sYmwodGV4dDogc3RyKSAt"
    "PiBRTGFiZWw6CiAgICBsYmwgPSBRTGFiZWwodGV4dCkKICAgIGxibC5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJv"
    "bGQ7ICIKICAgICAgICBmImxldHRlci1zcGFjaW5nOiAycHg7IGZvbnQtZmFtaWx5OiB7REVDS19G"
    "T05UfSwgc2VyaWY7IgogICAgKQogICAgcmV0dXJuIGxibAoKCiMg4pSA4pSAIFNMIFNDQU5TIFRB"
    "QiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKY2xhc3MgU0xTY2Fuc1RhYihRV2lkZ2V0KToKICAgICIiIgogICAg"
    "U2Vjb25kIExpZmUgYXZhdGFyIHNjYW5uZXIgcmVzdWx0cyBtYW5hZ2VyLgogICAgUmVidWlsdCBm"
    "cm9tIHNwZWM6CiAgICAgIC0gQ2FyZC9ncmltb2lyZS1lbnRyeSBzdHlsZSBkaXNwbGF5CiAgICAg"
    "IC0gQWRkICh3aXRoIHRpbWVzdGFtcC1hd2FyZSBwYXJzZXIpCiAgICAgIC0gRGlzcGxheSAoY2xl"
    "YW4gaXRlbS9jcmVhdG9yIHRhYmxlKQogICAgICAtIE1vZGlmeSAoZWRpdCBuYW1lLCBkZXNjcmlw"
    "dGlvbiwgaW5kaXZpZHVhbCBpdGVtcykKICAgICAgLSBEZWxldGUgKHdhcyBtaXNzaW5nIOKAlCBu"
    "b3cgcHJlc2VudCkKICAgICAgLSBSZS1wYXJzZSAod2FzICdSZWZyZXNoJyDigJQgcmUtcnVucyBw"
    "YXJzZXIgb24gc3RvcmVkIHJhdyB0ZXh0KQogICAgICAtIENvcHktdG8tY2xpcGJvYXJkIG9uIGFu"
    "eSBpdGVtCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbWVtb3J5X2RpcjogUGF0aCwg"
    "cGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNl"
    "bGYuX3BhdGggICAgPSBjZmdfcGF0aCgic2wiKSAvICJzbF9zY2Fucy5qc29ubCIKICAgICAgICBz"
    "ZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zZWxlY3RlZF9pZDog"
    "T3B0aW9uYWxbc3RyXSA9IE5vbmUKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2Vs"
    "Zi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9v"
    "dCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwg"
    "NCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBCdXR0b24gYmFy"
    "CiAgICAgICAgYmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hZGQgICAgID0g"
    "X2dvdGhpY19idG4oIuKcpiBBZGQiLCAgICAgIkFkZCBhIG5ldyBzY2FuIikKICAgICAgICBzZWxm"
    "Ll9idG5fZGlzcGxheSA9IF9nb3RoaWNfYnRuKCLinacgRGlzcGxheSIsICJTaG93IHNlbGVjdGVk"
    "IHNjYW4gZGV0YWlscyIpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeSAgPSBfZ290aGljX2J0bigi"
    "4pynIE1vZGlmeSIsICAiRWRpdCBzZWxlY3RlZCBzY2FuIikKICAgICAgICBzZWxmLl9idG5fZGVs"
    "ZXRlICA9IF9nb3RoaWNfYnRuKCLinJcgRGVsZXRlIiwgICJEZWxldGUgc2VsZWN0ZWQgc2NhbiIp"
    "CiAgICAgICAgc2VsZi5fYnRuX3JlcGFyc2UgPSBfZ290aGljX2J0bigi4oa7IFJlLXBhcnNlIiwi"
    "UmUtcGFyc2UgcmF3IHRleHQgb2Ygc2VsZWN0ZWQgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRuX2Fk"
    "ZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2hvd19hZGQpCiAgICAgICAgc2VsZi5fYnRuX2Rpc3Bs"
    "YXkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Nob3dfZGlzcGxheSkKICAgICAgICBzZWxmLl9idG5f"
    "bW9kaWZ5LmNsaWNrZWQuY29ubmVjdChzZWxmLl9zaG93X21vZGlmeSkKICAgICAgICBzZWxmLl9i"
    "dG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5f"
    "YnRuX3JlcGFyc2UuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX3JlcGFyc2UpCiAgICAgICAgZm9y"
    "IGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9kaXNwbGF5LCBzZWxmLl9idG5fbW9kaWZ5"
    "LAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fZGVsZXRlLCBzZWxmLl9idG5fcmVwYXJzZSk6"
    "CiAgICAgICAgICAgIGJhci5hZGRXaWRnZXQoYikKICAgICAgICBiYXIuYWRkU3RyZXRjaCgpCiAg"
    "ICAgICAgcm9vdC5hZGRMYXlvdXQoYmFyKQoKICAgICAgICAjIFN0YWNrOiBsaXN0IHZpZXcgfCBh"
    "ZGQgZm9ybSB8IGRpc3BsYXkgfCBtb2RpZnkKICAgICAgICBzZWxmLl9zdGFjayA9IFFTdGFja2Vk"
    "V2lkZ2V0KCkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9zdGFjaywgMSkKCiAgICAgICAg"
    "IyDilIDilIAgUEFHRSAwOiBzY2FuIGxpc3QgKGdyaW1vaXJlIGNhcmRzKSDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICBwMCA9IFFXaWRnZXQoKQogICAgICAgIGwwID0gUVZCb3hMYXlvdXQocDApCiAg"
    "ICAgICAgbDAuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VsZi5fY2Fy"
    "ZF9zY3JvbGwgPSBRU2Nyb2xsQXJlYSgpCiAgICAgICAgc2VsZi5fY2FyZF9zY3JvbGwuc2V0V2lk"
    "Z2V0UmVzaXphYmxlKFRydWUpCiAgICAgICAgc2VsZi5fY2FyZF9zY3JvbGwuc2V0U3R5bGVTaGVl"
    "dChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogbm9uZTsiKQogICAgICAgIHNlbGYuX2Nh"
    "cmRfY29udGFpbmVyID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQgICAgPSBR"
    "VkJveExheW91dChzZWxmLl9jYXJkX2NvbnRhaW5lcikKICAgICAgICBzZWxmLl9jYXJkX2xheW91"
    "dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBzZWxmLl9jYXJkX2xheW91"
    "dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuYWRkU3RyZXRjaCgpCiAg"
    "ICAgICAgc2VsZi5fY2FyZF9zY3JvbGwuc2V0V2lkZ2V0KHNlbGYuX2NhcmRfY29udGFpbmVyKQog"
    "ICAgICAgIGwwLmFkZFdpZGdldChzZWxmLl9jYXJkX3Njcm9sbCkKICAgICAgICBzZWxmLl9zdGFj"
    "ay5hZGRXaWRnZXQocDApCgogICAgICAgICMg4pSA4pSAIFBBR0UgMTogYWRkIGZvcm0g4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICAgICAgcDEgPSBRV2lkZ2V0KCkKICAgICAgICBsMSA9IFFWQm94TGF5b3V0KHAx"
    "KQogICAgICAgIGwxLnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIGwxLnNl"
    "dFNwYWNpbmcoNCkKICAgICAgICBsMS5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgU0NBTiBO"
    "QU1FIChhdXRvLWRldGVjdGVkKSIpKQogICAgICAgIHNlbGYuX2FkZF9uYW1lICA9IFFMaW5lRWRp"
    "dCgpCiAgICAgICAgc2VsZi5fYWRkX25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJBdXRvLWRldGVj"
    "dGVkIGZyb20gc2NhbiB0ZXh0IikKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX25hbWUp"
    "CiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIERFU0NSSVBUSU9OIikpCiAg"
    "ICAgICAgc2VsZi5fYWRkX2Rlc2MgID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9hZGRfZGVz"
    "Yy5zZXRNYXhpbXVtSGVpZ2h0KDYwKQogICAgICAgIGwxLmFkZFdpZGdldChzZWxmLl9hZGRfZGVz"
    "YykKICAgICAgICBsMS5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgUkFXIFNDQU4gVEVYVCAo"
    "cGFzdGUgaGVyZSkiKSkKICAgICAgICBzZWxmLl9hZGRfcmF3ICAgPSBRVGV4dEVkaXQoKQogICAg"
    "ICAgIHNlbGYuX2FkZF9yYXcuc2V0UGxhY2Vob2xkZXJUZXh0KAogICAgICAgICAgICAiUGFzdGUg"
    "dGhlIHJhdyBTZWNvbmQgTGlmZSBzY2FuIG91dHB1dCBoZXJlLlxuIgogICAgICAgICAgICAiVGlt"
    "ZXN0YW1wcyBsaWtlIFsxMTo0N10gd2lsbCBiZSB1c2VkIHRvIHNwbGl0IGl0ZW1zIGNvcnJlY3Rs"
    "eS4iCiAgICAgICAgKQogICAgICAgIGwxLmFkZFdpZGdldChzZWxmLl9hZGRfcmF3LCAxKQogICAg"
    "ICAgICMgUHJldmlldyBvZiBwYXJzZWQgaXRlbXMKICAgICAgICBsMS5hZGRXaWRnZXQoX3NlY3Rp"
    "b25fbGJsKCLinacgUEFSU0VEIElURU1TIFBSRVZJRVciKSkKICAgICAgICBzZWxmLl9hZGRfcHJl"
    "dmlldyA9IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldEhv"
    "cml6b250YWxIZWFkZXJMYWJlbHMoWyJJdGVtIiwgIkNyZWF0b3IiXSkKICAgICAgICBzZWxmLl9h"
    "ZGRfcHJldmlldy5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAg"
    "ICAgICAgIDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9h"
    "ZGRfcHJldmlldy5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAg"
    "ICAgICAgIDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9h"
    "ZGRfcHJldmlldy5zZXRNYXhpbXVtSGVpZ2h0KDEyMCkKICAgICAgICBzZWxmLl9hZGRfcHJldmll"
    "dy5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBsMS5hZGRXaWRn"
    "ZXQoc2VsZi5fYWRkX3ByZXZpZXcpCiAgICAgICAgc2VsZi5fYWRkX3Jhdy50ZXh0Q2hhbmdlZC5j"
    "b25uZWN0KHNlbGYuX3ByZXZpZXdfcGFyc2UpCgogICAgICAgIGJ0bnMxID0gUUhCb3hMYXlvdXQo"
    "KQogICAgICAgIHMxID0gX2dvdGhpY19idG4oIuKcpiBTYXZlIik7IGMxID0gX2dvdGhpY19idG4o"
    "IuKclyBDYW5jZWwiKQogICAgICAgIHMxLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAg"
    "ICAgICAgYzEuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fc3RhY2suc2V0Q3VycmVudElu"
    "ZGV4KDApKQogICAgICAgIGJ0bnMxLmFkZFdpZGdldChzMSk7IGJ0bnMxLmFkZFdpZGdldChjMSk7"
    "IGJ0bnMxLmFkZFN0cmV0Y2goKQogICAgICAgIGwxLmFkZExheW91dChidG5zMSkKICAgICAgICBz"
    "ZWxmLl9zdGFjay5hZGRXaWRnZXQocDEpCgogICAgICAgICMg4pSA4pSAIFBBR0UgMjogZGlzcGxh"
    "eSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICBwMiA9IFFXaWRnZXQoKQogICAgICAgIGwyID0gUVZC"
    "b3hMYXlvdXQocDIpCiAgICAgICAgbDIuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAg"
    "ICAgICAgc2VsZi5fZGlzcF9uYW1lICA9IFFMYWJlbCgpCiAgICAgICAgc2VsZi5fZGlzcF9uYW1l"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTERfQlJJR0hUfTsgZm9u"
    "dC1zaXplOiAxM3B4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmImZvbnQtZmFt"
    "aWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBzZWxmLl9kaXNwX2Rl"
    "c2MgID0gUUxhYmVsKCkKICAgICAgICBzZWxmLl9kaXNwX2Rlc2Muc2V0V29yZFdyYXAoVHJ1ZSkK"
    "ICAgICAgICBzZWxmLl9kaXNwX2Rlc2Muc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xv"
    "cjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05U"
    "fSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlID0gUVRhYmxlV2lk"
    "Z2V0KDAsIDIpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFi"
    "ZWxzKFsiSXRlbSIsICJDcmVhdG9yIl0pCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5ob3Jpem9u"
    "dGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDAsIFFIZWFkZXJW"
    "aWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLmhvcml6b250"
    "YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMSwgUUhlYWRlclZp"
    "ZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0U3R5bGVT"
    "aGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRD"
    "b250ZXh0TWVudVBvbGljeSgKICAgICAgICAgICAgUXQuQ29udGV4dE1lbnVQb2xpY3kuQ3VzdG9t"
    "Q29udGV4dE1lbnUpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5jdXN0b21Db250ZXh0TWVudVJl"
    "cXVlc3RlZC5jb25uZWN0KAogICAgICAgICAgICBzZWxmLl9pdGVtX2NvbnRleHRfbWVudSkKCiAg"
    "ICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2Rpc3BfbmFtZSkKICAgICAgICBsMi5hZGRXaWRnZXQo"
    "c2VsZi5fZGlzcF9kZXNjKQogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9kaXNwX3RhYmxlLCAx"
    "KQoKICAgICAgICBjb3B5X2hpbnQgPSBRTGFiZWwoIlJpZ2h0LWNsaWNrIGFueSBpdGVtIHRvIGNv"
    "cHkgaXQgdG8gY2xpcGJvYXJkLiIpCiAgICAgICAgY29weV9oaW50LnNldFN0eWxlU2hlZXQoCiAg"
    "ICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFt"
    "aWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBsMi5hZGRXaWRnZXQo"
    "Y29weV9oaW50KQoKICAgICAgICBiazIgPSBfZ290aGljX2J0bigi4peAIEJhY2siKQogICAgICAg"
    "IGJrMi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgo"
    "MCkpCiAgICAgICAgbDIuYWRkV2lkZ2V0KGJrMikKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRn"
    "ZXQocDIpCgogICAgICAgICMg4pSA4pSAIFBBR0UgMzogbW9kaWZ5IOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgICAgIHAzID0gUVdpZGdldCgpCiAgICAgICAgbDMgPSBRVkJveExheW91dChwMykKICAg"
    "ICAgICBsMy5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBsMy5zZXRTcGFj"
    "aW5nKDQpCiAgICAgICAgbDMuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIE5BTUUiKSkKICAg"
    "ICAgICBzZWxmLl9tb2RfbmFtZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgbDMuYWRkV2lkZ2V0KHNl"
    "bGYuX21vZF9uYW1lKQogICAgICAgIGwzLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBERVND"
    "UklQVElPTiIpKQogICAgICAgIHNlbGYuX21vZF9kZXNjID0gUUxpbmVFZGl0KCkKICAgICAgICBs"
    "My5hZGRXaWRnZXQoc2VsZi5fbW9kX2Rlc2MpCiAgICAgICAgbDMuYWRkV2lkZ2V0KF9zZWN0aW9u"
    "X2xibCgi4p2nIElURU1TIChkb3VibGUtY2xpY2sgdG8gZWRpdCkiKSkKICAgICAgICBzZWxmLl9t"
    "b2RfdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl9tb2RfdGFibGUuc2V0"
    "SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIkl0ZW0iLCAiQ3JlYXRvciJdKQogICAgICAgIHNlbGYu"
    "X21vZF90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAg"
    "ICAgICAgIDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9t"
    "b2RfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAg"
    "ICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fbW9k"
    "X3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIGwzLmFk"
    "ZFdpZGdldChzZWxmLl9tb2RfdGFibGUsIDEpCgogICAgICAgIGJ0bnMzID0gUUhCb3hMYXlvdXQo"
    "KQogICAgICAgIHMzID0gX2dvdGhpY19idG4oIuKcpiBTYXZlIik7IGMzID0gX2dvdGhpY19idG4o"
    "IuKclyBDYW5jZWwiKQogICAgICAgIHMzLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19tb2RpZnlf"
    "c2F2ZSkKICAgICAgICBjMy5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9zdGFjay5zZXRD"
    "dXJyZW50SW5kZXgoMCkpCiAgICAgICAgYnRuczMuYWRkV2lkZ2V0KHMzKTsgYnRuczMuYWRkV2lk"
    "Z2V0KGMzKTsgYnRuczMuYWRkU3RyZXRjaCgpCiAgICAgICAgbDMuYWRkTGF5b3V0KGJ0bnMzKQog"
    "ICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMykKCiAgICAjIOKUgOKUgCBQQVJTRVIg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBA"
    "c3RhdGljbWV0aG9kCiAgICBkZWYgcGFyc2Vfc2Nhbl90ZXh0KHJhdzogc3RyKSAtPiB0dXBsZVtz"
    "dHIsIGxpc3RbZGljdF1dOgogICAgICAgICIiIgogICAgICAgIFBhcnNlIHJhdyBTTCBzY2FuIG91"
    "dHB1dCBpbnRvIChhdmF0YXJfbmFtZSwgaXRlbXMpLgoKICAgICAgICBLRVkgRklYOiBCZWZvcmUg"
    "c3BsaXR0aW5nLCBpbnNlcnQgbmV3bGluZXMgYmVmb3JlIGV2ZXJ5IFtISDpNTV0KICAgICAgICB0"
    "aW1lc3RhbXAgc28gc2luZ2xlLWxpbmUgcGFzdGVzIHdvcmsgY29ycmVjdGx5LgoKICAgICAgICBF"
    "eHBlY3RlZCBmb3JtYXQ6CiAgICAgICAgICAgIFsxMTo0N10gQXZhdGFyTmFtZSdzIHB1YmxpYyBh"
    "dHRhY2htZW50czoKICAgICAgICAgICAgWzExOjQ3XSAuOiBJdGVtIE5hbWUgW0F0dGFjaG1lbnRd"
    "IENSRUFUT1I6IENyZWF0b3JOYW1lIFsxMTo0N10gLi4uCiAgICAgICAgIiIiCiAgICAgICAgaWYg"
    "bm90IHJhdy5zdHJpcCgpOgogICAgICAgICAgICByZXR1cm4gIlVOS05PV04iLCBbXQoKICAgICAg"
    "ICAjIOKUgOKUgCBTdGVwIDE6IG5vcm1hbGl6ZSDigJQgaW5zZXJ0IG5ld2xpbmVzIGJlZm9yZSB0"
    "aW1lc3RhbXBzIOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIG5vcm1hbGl6ZWQgPSBfcmUuc3Vi"
    "KHInXHMqKFxbXGR7MSwyfTpcZHsyfVxdKScsIHInXG5cMScsIHJhdykKICAgICAgICBsaW5lcyA9"
    "IFtsLnN0cmlwKCkgZm9yIGwgaW4gbm9ybWFsaXplZC5zcGxpdGxpbmVzKCkgaWYgbC5zdHJpcCgp"
    "XQoKICAgICAgICAjIOKUgOKUgCBTdGVwIDI6IGV4dHJhY3QgYXZhdGFyIG5hbWUg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgYXZhdGFyX25hbWUgPSAiVU5L"
    "Tk9XTiIKICAgICAgICBmb3IgbGluZSBpbiBsaW5lczoKICAgICAgICAgICAgIyAiQXZhdGFyTmFt"
    "ZSdzIHB1YmxpYyBhdHRhY2htZW50cyIgb3Igc2ltaWxhcgogICAgICAgICAgICBtID0gX3JlLnNl"
    "YXJjaCgKICAgICAgICAgICAgICAgIHIiKFx3W1x3XHNdKz8pJ3NccytwdWJsaWNccythdHRhY2ht"
    "ZW50cyIsCiAgICAgICAgICAgICAgICBsaW5lLCBfcmUuSQogICAgICAgICAgICApCiAgICAgICAg"
    "ICAgIGlmIG06CiAgICAgICAgICAgICAgICBhdmF0YXJfbmFtZSA9IG0uZ3JvdXAoMSkuc3RyaXAo"
    "KQogICAgICAgICAgICAgICAgYnJlYWsKCiAgICAgICAgIyDilIDilIAgU3RlcCAzOiBleHRyYWN0"
    "IGl0ZW1zIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgICAgIGl0ZW1zID0gW10KICAgICAgICBmb3IgbGluZSBpbiBsaW5lczoKICAg"
    "ICAgICAgICAgIyBTdHJpcCBsZWFkaW5nIHRpbWVzdGFtcAogICAgICAgICAgICBjb250ZW50ID0g"
    "X3JlLnN1YihyJ15cW1xkezEsMn06XGR7Mn1cXVxzKicsICcnLCBsaW5lKS5zdHJpcCgpCiAgICAg"
    "ICAgICAgIGlmIG5vdCBjb250ZW50OgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAg"
    "ICAgIyBTa2lwIGhlYWRlciBsaW5lcwogICAgICAgICAgICBpZiAiJ3MgcHVibGljIGF0dGFjaG1l"
    "bnRzIiBpbiBjb250ZW50Lmxvd2VyKCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAg"
    "ICAgICBpZiBjb250ZW50Lmxvd2VyKCkuc3RhcnRzd2l0aCgib2JqZWN0Iik6CiAgICAgICAgICAg"
    "ICAgICBjb250aW51ZQogICAgICAgICAgICAjIFNraXAgZGl2aWRlciBsaW5lcyDigJQgbGluZXMg"
    "dGhhdCBhcmUgbW9zdGx5IG9uZSByZXBlYXRlZCBjaGFyYWN0ZXIKICAgICAgICAgICAgIyBlLmcu"
    "IOKWguKWguKWguKWguKWguKWguKWguKWguKWguKWguKWguKWgiBvciDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZAgb3Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICAgICAgICAgIHN0cmlwcGVkID0gY29udGVudC5zdHJpcCgiLjogIikKICAgICAgICAg"
    "ICAgaWYgc3RyaXBwZWQgYW5kIGxlbihzZXQoc3RyaXBwZWQpKSA8PSAyOgogICAgICAgICAgICAg"
    "ICAgY29udGludWUgICMgb25lIG9yIHR3byB1bmlxdWUgY2hhcnMgPSBkaXZpZGVyIGxpbmUKCiAg"
    "ICAgICAgICAgICMgVHJ5IHRvIGV4dHJhY3QgQ1JFQVRPUjogZmllbGQKICAgICAgICAgICAgY3Jl"
    "YXRvciA9ICJVTktOT1dOIgogICAgICAgICAgICBpdGVtX25hbWUgPSBjb250ZW50CgogICAgICAg"
    "ICAgICBjcmVhdG9yX21hdGNoID0gX3JlLnNlYXJjaCgKICAgICAgICAgICAgICAgIHInQ1JFQVRP"
    "UjpccyooW1x3XHNdKz8pKD86XHMqXFt8JCknLCBjb250ZW50LCBfcmUuSQogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgIGlmIGNyZWF0b3JfbWF0Y2g6CiAgICAgICAgICAgICAgICBjcmVhdG9yICAg"
    "PSBjcmVhdG9yX21hdGNoLmdyb3VwKDEpLnN0cmlwKCkKICAgICAgICAgICAgICAgIGl0ZW1fbmFt"
    "ZSA9IGNvbnRlbnRbOmNyZWF0b3JfbWF0Y2guc3RhcnQoKV0uc3RyaXAoKQoKICAgICAgICAgICAg"
    "IyBTdHJpcCBhdHRhY2htZW50IHBvaW50IHN1ZmZpeGVzIGxpa2UgW0xlZnRfRm9vdF0KICAgICAg"
    "ICAgICAgaXRlbV9uYW1lID0gX3JlLnN1YihyJ1xzKlxbW1x3XHNfXStcXScsICcnLCBpdGVtX25h"
    "bWUpLnN0cmlwKCkKICAgICAgICAgICAgaXRlbV9uYW1lID0gaXRlbV9uYW1lLnN0cmlwKCIuOiAi"
    "KQoKICAgICAgICAgICAgaWYgaXRlbV9uYW1lIGFuZCBsZW4oaXRlbV9uYW1lKSA+IDE6CiAgICAg"
    "ICAgICAgICAgICBpdGVtcy5hcHBlbmQoeyJpdGVtIjogaXRlbV9uYW1lLCAiY3JlYXRvciI6IGNy"
    "ZWF0b3J9KQoKICAgICAgICByZXR1cm4gYXZhdGFyX25hbWUsIGl0ZW1zCgogICAgIyDilIDilIAg"
    "Q0FSRCBSRU5ERVJJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2J1"
    "aWxkX2NhcmRzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBDbGVhciBleGlzdGluZyBjYXJkcyAo"
    "a2VlcCBzdHJldGNoKQogICAgICAgIHdoaWxlIHNlbGYuX2NhcmRfbGF5b3V0LmNvdW50KCkgPiAx"
    "OgogICAgICAgICAgICBpdGVtID0gc2VsZi5fY2FyZF9sYXlvdXQudGFrZUF0KDApCiAgICAgICAg"
    "ICAgIGlmIGl0ZW0ud2lkZ2V0KCk6CiAgICAgICAgICAgICAgICBpdGVtLndpZGdldCgpLmRlbGV0"
    "ZUxhdGVyKCkKCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICBj"
    "YXJkID0gc2VsZi5fbWFrZV9jYXJkKHJlYykKICAgICAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQu"
    "aW5zZXJ0V2lkZ2V0KAogICAgICAgICAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuY291bnQoKSAt"
    "IDEsIGNhcmQKICAgICAgICAgICAgKQoKICAgIGRlZiBfbWFrZV9jYXJkKHNlbGYsIHJlYzogZGlj"
    "dCkgLT4gUVdpZGdldDoKICAgICAgICBjYXJkID0gUUZyYW1lKCkKICAgICAgICBpc19zZWxlY3Rl"
    "ZCA9IHJlYy5nZXQoInJlY29yZF9pZCIpID09IHNlbGYuX3NlbGVjdGVkX2lkCiAgICAgICAgY2Fy"
    "ZC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHsnIzFhMGExMCcgaWYg"
    "aXNfc2VsZWN0ZWQgZWxzZSBDX0JHM307ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xp"
    "ZCB7Q19DUklNU09OIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19CT1JERVJ9OyAiCiAgICAgICAgICAg"
    "IGYiYm9yZGVyLXJhZGl1czogMnB4OyBwYWRkaW5nOiAycHg7IgogICAgICAgICkKICAgICAgICBs"
    "YXlvdXQgPSBRSEJveExheW91dChjYXJkKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdp"
    "bnMoOCwgNiwgOCwgNikKCiAgICAgICAgbmFtZV9sYmwgPSBRTGFiZWwocmVjLmdldCgibmFtZSIs"
    "ICJVTktOT1dOIikpCiAgICAgICAgbmFtZV9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJjb2xvcjoge0NfR09MRF9CUklHSFQgaWYgaXNfc2VsZWN0ZWQgZWxzZSBDX0dPTER9OyAiCiAg"
    "ICAgICAgICAgIGYiZm9udC1zaXplOiAxMXB4OyBmb250LXdlaWdodDogYm9sZDsgZm9udC1mYW1p"
    "bHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQoKICAgICAgICBjb3VudCA9IGxlbihy"
    "ZWMuZ2V0KCJpdGVtcyIsIFtdKSkKICAgICAgICBjb3VudF9sYmwgPSBRTGFiZWwoZiJ7Y291bnR9"
    "IGl0ZW1zIikKICAgICAgICBjb3VudF9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJj"
    "b2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZP"
    "TlR9LCBzZXJpZjsiCiAgICAgICAgKQoKICAgICAgICBkYXRlX2xibCA9IFFMYWJlbChyZWMuZ2V0"
    "KCJjcmVhdGVkX2F0IiwgIiIpWzoxMF0pCiAgICAgICAgZGF0ZV9sYmwuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgZm9udC1m"
    "YW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQoKICAgICAgICBsYXlvdXQuYWRk"
    "V2lkZ2V0KG5hbWVfbGJsKQogICAgICAgIGxheW91dC5hZGRTdHJldGNoKCkKICAgICAgICBsYXlv"
    "dXQuYWRkV2lkZ2V0KGNvdW50X2xibCkKICAgICAgICBsYXlvdXQuYWRkU3BhY2luZygxMikKICAg"
    "ICAgICBsYXlvdXQuYWRkV2lkZ2V0KGRhdGVfbGJsKQoKICAgICAgICAjIENsaWNrIHRvIHNlbGVj"
    "dAogICAgICAgIHJlY19pZCA9IHJlYy5nZXQoInJlY29yZF9pZCIsICIiKQogICAgICAgIGNhcmQu"
    "bW91c2VQcmVzc0V2ZW50ID0gbGFtYmRhIGUsIHJpZD1yZWNfaWQ6IHNlbGYuX3NlbGVjdF9jYXJk"
    "KHJpZCkKICAgICAgICByZXR1cm4gY2FyZAoKICAgIGRlZiBfc2VsZWN0X2NhcmQoc2VsZiwgcmVj"
    "b3JkX2lkOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQgPSByZWNvcmRf"
    "aWQKICAgICAgICBzZWxmLl9idWlsZF9jYXJkcygpICAjIFJlYnVpbGQgdG8gc2hvdyBzZWxlY3Rp"
    "b24gaGlnaGxpZ2h0CgogICAgZGVmIF9zZWxlY3RlZF9yZWNvcmQoc2VsZikgLT4gT3B0aW9uYWxb"
    "ZGljdF06CiAgICAgICAgcmV0dXJuIG5leHQoCiAgICAgICAgICAgIChyIGZvciByIGluIHNlbGYu"
    "X3JlY29yZHMKICAgICAgICAgICAgIGlmIHIuZ2V0KCJyZWNvcmRfaWQiKSA9PSBzZWxmLl9zZWxl"
    "Y3RlZF9pZCksCiAgICAgICAgICAgIE5vbmUKICAgICAgICApCgogICAgIyDilIDilIAgQUNUSU9O"
    "UyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "IGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRf"
    "anNvbmwoc2VsZi5fcGF0aCkKICAgICAgICAjIEVuc3VyZSByZWNvcmRfaWQgZmllbGQgZXhpc3Rz"
    "CiAgICAgICAgY2hhbmdlZCA9IEZhbHNlCiAgICAgICAgZm9yIHIgaW4gc2VsZi5fcmVjb3JkczoK"
    "ICAgICAgICAgICAgaWYgbm90IHIuZ2V0KCJyZWNvcmRfaWQiKToKICAgICAgICAgICAgICAgIHJb"
    "InJlY29yZF9pZCJdID0gci5nZXQoImlkIikgb3Igc3RyKHV1aWQudXVpZDQoKSkKICAgICAgICAg"
    "ICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgaWYgY2hhbmdlZDoKICAgICAgICAgICAgd3Jp"
    "dGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLl9idWlsZF9j"
    "YXJkcygpCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDApCgogICAgZGVmIF9w"
    "cmV2aWV3X3BhcnNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmF3ID0gc2VsZi5fYWRkX3Jhdy50"
    "b1BsYWluVGV4dCgpCiAgICAgICAgbmFtZSwgaXRlbXMgPSBzZWxmLnBhcnNlX3NjYW5fdGV4dChy"
    "YXcpCiAgICAgICAgc2VsZi5fYWRkX25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0KG5hbWUpCiAgICAg"
    "ICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgaXQgaW4gaXRl"
    "bXNbOjIwXTogICMgcHJldmlldyBmaXJzdCAyMAogICAgICAgICAgICByID0gc2VsZi5fYWRkX3By"
    "ZXZpZXcucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5pbnNlcnRSb3co"
    "cikKICAgICAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0SXRlbShyLCAwLCBRVGFibGVXaWRn"
    "ZXRJdGVtKGl0WyJpdGVtIl0pKQogICAgICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRJdGVt"
    "KHIsIDEsIFFUYWJsZVdpZGdldEl0ZW0oaXRbImNyZWF0b3IiXSkpCgogICAgZGVmIF9zaG93X2Fk"
    "ZChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2FkZF9uYW1lLmNsZWFyKCkKICAgICAgICBz"
    "ZWxmLl9hZGRfbmFtZS5zZXRQbGFjZWhvbGRlclRleHQoIkF1dG8tZGV0ZWN0ZWQgZnJvbSBzY2Fu"
    "IHRleHQiKQogICAgICAgIHNlbGYuX2FkZF9kZXNjLmNsZWFyKCkKICAgICAgICBzZWxmLl9hZGRf"
    "cmF3LmNsZWFyKCkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRSb3dDb3VudCgwKQogICAg"
    "ICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgxKQoKICAgIGRlZiBfZG9fYWRkKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgcmF3ICA9IHNlbGYuX2FkZF9yYXcudG9QbGFpblRleHQoKQogICAg"
    "ICAgIG5hbWUsIGl0ZW1zID0gc2VsZi5wYXJzZV9zY2FuX3RleHQocmF3KQogICAgICAgIG92ZXJy"
    "aWRlX25hbWUgPSBzZWxmLl9hZGRfbmFtZS50ZXh0KCkuc3RyaXAoKQogICAgICAgIG5vdyAgPSBk"
    "YXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHJlY29yZCA9IHsK"
    "ICAgICAgICAgICAgImlkIjogICAgICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAg"
    "ICJyZWNvcmRfaWQiOiAgIHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAibmFtZSI6ICAg"
    "ICAgICBvdmVycmlkZV9uYW1lIG9yIG5hbWUsCiAgICAgICAgICAgICJkZXNjcmlwdGlvbiI6IHNl"
    "bGYuX2FkZF9kZXNjLnRvUGxhaW5UZXh0KClbOjI0NF0sCiAgICAgICAgICAgICJpdGVtcyI6ICAg"
    "ICAgIGl0ZW1zLAogICAgICAgICAgICAicmF3X3RleHQiOiAgICByYXcsCiAgICAgICAgICAgICJj"
    "cmVhdGVkX2F0IjogIG5vdywKICAgICAgICAgICAgInVwZGF0ZWRfYXQiOiAgbm93LAogICAgICAg"
    "IH0KICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChyZWNvcmQpCiAgICAgICAgd3JpdGVfanNv"
    "bmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLl9zZWxlY3RlZF9pZCA9"
    "IHJlY29yZFsicmVjb3JkX2lkIl0KICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2hv"
    "d19kaXNwbGF5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVj"
    "b3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1h"
    "dGlvbihzZWxmLCAiU0wgU2NhbnMiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAiU2VsZWN0IGEgc2NhbiB0byBkaXNwbGF5LiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAg"
    "IHNlbGYuX2Rpc3BfbmFtZS5zZXRUZXh0KGYi4p2nIHtyZWMuZ2V0KCduYW1lJywnJyl9IikKICAg"
    "ICAgICBzZWxmLl9kaXNwX2Rlc2Muc2V0VGV4dChyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpKQog"
    "ICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgaXQgaW4g"
    "cmVjLmdldCgiaXRlbXMiLFtdKToKICAgICAgICAgICAgciA9IHNlbGYuX2Rpc3BfdGFibGUucm93"
    "Q291bnQoKQogICAgICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAg"
    "ICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldEl0ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJs"
    "ZVdpZGdldEl0ZW0oaXQuZ2V0KCJpdGVtIiwiIikpKQogICAgICAgICAgICBzZWxmLl9kaXNwX3Rh"
    "YmxlLnNldEl0ZW0ociwgMSwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oaXQuZ2V0"
    "KCJjcmVhdG9yIiwiVU5LTk9XTiIpKSkKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5k"
    "ZXgoMikKCiAgICBkZWYgX2l0ZW1fY29udGV4dF9tZW51KHNlbGYsIHBvcykgLT4gTm9uZToKICAg"
    "ICAgICBpZHggPSBzZWxmLl9kaXNwX3RhYmxlLmluZGV4QXQocG9zKQogICAgICAgIGlmIG5vdCBp"
    "ZHguaXNWYWxpZCgpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpdGVtX3RleHQgID0gKHNl"
    "bGYuX2Rpc3BfdGFibGUuaXRlbShpZHgucm93KCksIDApIG9yCiAgICAgICAgICAgICAgICAgICAg"
    "ICBRVGFibGVXaWRnZXRJdGVtKCIiKSkudGV4dCgpCiAgICAgICAgY3JlYXRvciAgICA9IChzZWxm"
    "Ll9kaXNwX3RhYmxlLml0ZW0oaWR4LnJvdygpLCAxKSBvcgogICAgICAgICAgICAgICAgICAgICAg"
    "UVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAgIGZyb20gUHlTaWRlNi5RdFdpZGdl"
    "dHMgaW1wb3J0IFFNZW51CiAgICAgICAgbWVudSA9IFFNZW51KHNlbGYpCiAgICAgICAgbWVudS5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7"
    "Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElN"
    "fTsiCiAgICAgICAgKQogICAgICAgIGFfaXRlbSAgICA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5IEl0"
    "ZW0gTmFtZSIpCiAgICAgICAgYV9jcmVhdG9yID0gbWVudS5hZGRBY3Rpb24oIkNvcHkgQ3JlYXRv"
    "ciIpCiAgICAgICAgYV9ib3RoICAgID0gbWVudS5hZGRBY3Rpb24oIkNvcHkgQm90aCIpCiAgICAg"
    "ICAgYWN0aW9uID0gbWVudS5leGVjKHNlbGYuX2Rpc3BfdGFibGUudmlld3BvcnQoKS5tYXBUb0ds"
    "b2JhbChwb3MpKQogICAgICAgIGNiID0gUUFwcGxpY2F0aW9uLmNsaXBib2FyZCgpCiAgICAgICAg"
    "aWYgYWN0aW9uID09IGFfaXRlbTogICAgY2Iuc2V0VGV4dChpdGVtX3RleHQpCiAgICAgICAgZWxp"
    "ZiBhY3Rpb24gPT0gYV9jcmVhdG9yOiBjYi5zZXRUZXh0KGNyZWF0b3IpCiAgICAgICAgZWxpZiBh"
    "Y3Rpb24gPT0gYV9ib3RoOiAgY2Iuc2V0VGV4dChmIntpdGVtX3RleHR9IOKAlCB7Y3JlYXRvcn0i"
    "KQoKICAgIGRlZiBfc2hvd19tb2RpZnkoc2VsZikgLT4gTm9uZToKICAgICAgICByZWMgPSBzZWxm"
    "Ll9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNz"
    "YWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJTTCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJTZWxlY3QgYSBzY2FuIHRvIG1vZGlmeS4iKQogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICBzZWxmLl9tb2RfbmFtZS5zZXRUZXh0KHJlYy5nZXQoIm5hbWUiLCIiKSkK"
    "ICAgICAgICBzZWxmLl9tb2RfZGVzYy5zZXRUZXh0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikp"
    "CiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGl0IGlu"
    "IHJlYy5nZXQoIml0ZW1zIixbXSk6CiAgICAgICAgICAgIHIgPSBzZWxmLl9tb2RfdGFibGUucm93"
    "Q291bnQoKQogICAgICAgICAgICBzZWxmLl9tb2RfdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAg"
    "ICAgIHNlbGYuX21vZF90YWJsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAgICAgICBRVGFibGVX"
    "aWRnZXRJdGVtKGl0LmdldCgiaXRlbSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fbW9kX3RhYmxl"
    "LnNldEl0ZW0ociwgMSwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oaXQuZ2V0KCJj"
    "cmVhdG9yIiwiVU5LTk9XTiIpKSkKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgo"
    "MykKCiAgICBkZWYgX2RvX21vZGlmeV9zYXZlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVjID0g"
    "c2VsZi5fc2VsZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICByZWNbIm5hbWUiXSAgICAgICAgPSBzZWxmLl9tb2RfbmFtZS50ZXh0KCku"
    "c3RyaXAoKSBvciAiVU5LTk9XTiIKICAgICAgICByZWNbImRlc2NyaXB0aW9uIl0gPSBzZWxmLl9t"
    "b2RfZGVzYy50ZXh0KClbOjI0NF0KICAgICAgICBpdGVtcyA9IFtdCiAgICAgICAgZm9yIGkgaW4g"
    "cmFuZ2Uoc2VsZi5fbW9kX3RhYmxlLnJvd0NvdW50KCkpOgogICAgICAgICAgICBpdCAgPSAoc2Vs"
    "Zi5fbW9kX3RhYmxlLml0ZW0oaSwwKSBvciBRVGFibGVXaWRnZXRJdGVtKCIiKSkudGV4dCgpCiAg"
    "ICAgICAgICAgIGNyICA9IChzZWxmLl9tb2RfdGFibGUuaXRlbShpLDEpIG9yIFFUYWJsZVdpZGdl"
    "dEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICAgICAgaXRlbXMuYXBwZW5kKHsiaXRlbSI6IGl0LnN0"
    "cmlwKCkgb3IgIlVOS05PV04iLAogICAgICAgICAgICAgICAgICAgICAgICAgICJjcmVhdG9yIjog"
    "Y3Iuc3RyaXAoKSBvciAiVU5LTk9XTiJ9KQogICAgICAgIHJlY1siaXRlbXMiXSAgICAgID0gaXRl"
    "bXMKICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMp"
    "Lmlzb2Zvcm1hdCgpCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3Jk"
    "cykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBub3Qg"
    "cmVjOgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiU0wgU2NhbnMi"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiU2VsZWN0IGEgc2NhbiB0byBk"
    "ZWxldGUuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgbmFtZSA9IHJlYy5nZXQoIm5hbWUi"
    "LCJ0aGlzIHNjYW4iKQogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAg"
    "ICAgICAgIHNlbGYsICJEZWxldGUgU2NhbiIsCiAgICAgICAgICAgIGYiRGVsZXRlICd7bmFtZX0n"
    "PyBUaGlzIGNhbm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRh"
    "cmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICApCiAg"
    "ICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAg"
    "ICAgICBzZWxmLl9yZWNvcmRzID0gW3IgZm9yIHIgaW4gc2VsZi5fcmVjb3JkcwogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGlmIHIuZ2V0KCJyZWNvcmRfaWQiKSAhPSBzZWxmLl9zZWxlY3Rl"
    "ZF9pZF0KICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykK"
    "ICAgICAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQgPSBOb25lCiAgICAgICAgICAgIHNlbGYucmVm"
    "cmVzaCgpCgogICAgZGVmIF9kb19yZXBhcnNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVjID0g"
    "c2VsZi5fc2VsZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAgICBR"
    "TWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiU0wgU2NhbnMiLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAiU2VsZWN0IGEgc2NhbiB0byByZS1wYXJzZS4iKQogICAgICAg"
    "ICAgICByZXR1cm4KICAgICAgICByYXcgPSByZWMuZ2V0KCJyYXdfdGV4dCIsIiIpCiAgICAgICAg"
    "aWYgbm90IHJhdzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlJl"
    "LXBhcnNlIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIk5vIHJhdyB0ZXh0"
    "IHN0b3JlZCBmb3IgdGhpcyBzY2FuLiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5hbWUs"
    "IGl0ZW1zID0gc2VsZi5wYXJzZV9zY2FuX3RleHQocmF3KQogICAgICAgIHJlY1siaXRlbXMiXSAg"
    "ICAgID0gaXRlbXMKICAgICAgICByZWNbIm5hbWUiXSAgICAgICA9IHJlY1sibmFtZSJdIG9yIG5h"
    "bWUKICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMp"
    "Lmlzb2Zvcm1hdCgpCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3Jk"
    "cykKICAgICAgICBzZWxmLnJlZnJlc2goKQogICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9u"
    "KHNlbGYsICJSZS1wYXJzZWQiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiRm91"
    "bmQge2xlbihpdGVtcyl9IGl0ZW1zLiIpCgoKIyDilIDilIAgU0wgQ09NTUFORFMgVEFCIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gApjbGFzcyBTTENvbW1hbmRzVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBTZWNvbmQgTGlmZSBj"
    "b21tYW5kIHJlZmVyZW5jZSB0YWJsZS4KICAgIEdvdGhpYyB0YWJsZSBzdHlsaW5nLiBDb3B5IGNv"
    "bW1hbmQgdG8gY2xpcGJvYXJkIGJ1dHRvbiBwZXIgcm93LgogICAgIiIiCgogICAgZGVmIF9faW5p"
    "dF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkK"
    "ICAgICAgICBzZWxmLl9wYXRoICAgID0gY2ZnX3BhdGgoInNsIikgLyAic2xfY29tbWFuZHMuanNv"
    "bmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5f"
    "c2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Qu"
    "c2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQp"
    "CgogICAgICAgIGJhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgID0g"
    "X2dvdGhpY19idG4oIuKcpiBBZGQiKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkgPSBfZ290aGlj"
    "X2J0bigi4pynIE1vZGlmeSIpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSA9IF9nb3RoaWNfYnRu"
    "KCLinJcgRGVsZXRlIikKICAgICAgICBzZWxmLl9idG5fY29weSAgID0gX2dvdGhpY19idG4oIuKn"
    "iSBDb3B5IENvbW1hbmQiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IkNvcHkgc2VsZWN0ZWQgY29tbWFuZCB0byBjbGlwYm9hcmQiKQogICAgICAgIHNlbGYuX2J0bl9y"
    "ZWZyZXNoPSBfZ290aGljX2J0bigi4oa7IFJlZnJlc2giKQogICAgICAgIHNlbGYuX2J0bl9hZGQu"
    "Y2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5LmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl9kb19tb2RpZnkpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZS5j"
    "bGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl9jb3B5LmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl9jb3B5X2NvbW1hbmQpCiAgICAgICAgc2VsZi5fYnRuX3JlZnJl"
    "c2guY2xpY2tlZC5jb25uZWN0KHNlbGYucmVmcmVzaCkKICAgICAgICBmb3IgYiBpbiAoc2VsZi5f"
    "YnRuX2FkZCwgc2VsZi5fYnRuX21vZGlmeSwgc2VsZi5fYnRuX2RlbGV0ZSwKICAgICAgICAgICAg"
    "ICAgICAgc2VsZi5fYnRuX2NvcHksIHNlbGYuX2J0bl9yZWZyZXNoKToKICAgICAgICAgICAgYmFy"
    "LmFkZFdpZGdldChiKQogICAgICAgIGJhci5hZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExh"
    "eW91dChiYXIpCgogICAgICAgIHNlbGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDIpCiAgICAg"
    "ICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIkNvbW1hbmQiLCAiRGVz"
    "Y3JpcHRpb24iXSkKICAgICAgICBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2Vj"
    "dGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3Ry"
    "ZXRjaCkKICAgICAgICBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJl"
    "c2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkK"
    "ICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAgICAgICAgUUFi"
    "c3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxm"
    "Ll90YWJsZS5zZXRBbHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVlKQogICAgICAgIHNlbGYuX3RhYmxl"
    "LnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHJvb3QuYWRkV2lk"
    "Z2V0KHNlbGYuX3RhYmxlLCAxKQoKICAgICAgICBoaW50ID0gUUxhYmVsKAogICAgICAgICAgICAi"
    "U2VsZWN0IGEgcm93IGFuZCBjbGljayDip4kgQ29weSBDb21tYW5kIHRvIGNvcHkganVzdCB0aGUg"
    "Y29tbWFuZCB0ZXh0LiIKICAgICAgICApCiAgICAgICAgaGludC5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWls"
    "eToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQo"
    "aGludCkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29y"
    "ZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291"
    "bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIHIgPSBz"
    "ZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLmluc2VydFJvdyhy"
    "KQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAgICAgICBR"
    "VGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoImNvbW1hbmQiLCIiKSkpCiAgICAgICAgICAgIHNlbGYu"
    "X3RhYmxlLnNldEl0ZW0ociwgMSwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVj"
    "LmdldCgiZGVzY3JpcHRpb24iLCIiKSkpCgogICAgZGVmIF9jb3B5X2NvbW1hbmQoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiBy"
    "b3cgPCAwOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpdGVtID0gc2VsZi5fdGFibGUuaXRl"
    "bShyb3csIDApCiAgICAgICAgaWYgaXRlbToKICAgICAgICAgICAgUUFwcGxpY2F0aW9uLmNsaXBi"
    "b2FyZCgpLnNldFRleHQoaXRlbS50ZXh0KCkpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxl"
    "KCJBZGQgQ29tbWFuZCIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7"
    "Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxn"
    "KQogICAgICAgIGNtZCAgPSBRTGluZUVkaXQoKTsgZGVzYyA9IFFMaW5lRWRpdCgpCiAgICAgICAg"
    "Zm9ybS5hZGRSb3coIkNvbW1hbmQ6IiwgY21kKQogICAgICAgIGZvcm0uYWRkUm93KCJEZXNjcmlw"
    "dGlvbjoiLCBkZXNjKQogICAgICAgIGJ0bnMgPSBRSEJveExheW91dCgpCiAgICAgICAgb2sgPSBf"
    "Z290aGljX2J0bigiU2F2ZSIpOyBjeCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIG9r"
    "LmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KTsgY3guY2xpY2tlZC5jb25uZWN0KGRsZy5yZWpl"
    "Y3QpCiAgICAgICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5zLmFkZFdpZGdldChjeCkKICAgICAg"
    "ICBmb3JtLmFkZFJvdyhidG5zKQogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFs"
    "b2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICBub3cgPSBkYXRldGltZS5ub3codGltZXpvbmUu"
    "dXRjKS5pc29mb3JtYXQoKQogICAgICAgICAgICByZWMgPSB7CiAgICAgICAgICAgICAgICAiaWQi"
    "OiAgICAgICAgICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgICAgICJjb21tYW5kIjog"
    "ICAgIGNtZC50ZXh0KCkuc3RyaXAoKVs6MjQ0XSwKICAgICAgICAgICAgICAgICJkZXNjcmlwdGlv"
    "biI6IGRlc2MudGV4dCgpLnN0cmlwKClbOjI0NF0sCiAgICAgICAgICAgICAgICAiY3JlYXRlZF9h"
    "dCI6ICBub3csICJ1cGRhdGVkX2F0Ijogbm93LAogICAgICAgICAgICB9CiAgICAgICAgICAgIGlm"
    "IHJlY1siY29tbWFuZCJdOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQocmVj"
    "KQogICAgICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykK"
    "ICAgICAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19tb2RpZnkoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBp"
    "ZiByb3cgPCAwIG9yIHJvdyA+PSBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJldHVy"
    "bgogICAgICAgIHJlYyA9IHNlbGYuX3JlY29yZHNbcm93XQogICAgICAgIGRsZyA9IFFEaWFsb2co"
    "c2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIk1vZGlmeSBDb21tYW5kIikKICAgICAg"
    "ICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xE"
    "fTsiKQogICAgICAgIGZvcm0gPSBRRm9ybUxheW91dChkbGcpCiAgICAgICAgY21kICA9IFFMaW5l"
    "RWRpdChyZWMuZ2V0KCJjb21tYW5kIiwiIikpCiAgICAgICAgZGVzYyA9IFFMaW5lRWRpdChyZWMu"
    "Z2V0KCJkZXNjcmlwdGlvbiIsIiIpKQogICAgICAgIGZvcm0uYWRkUm93KCJDb21tYW5kOiIsIGNt"
    "ZCkKICAgICAgICBmb3JtLmFkZFJvdygiRGVzY3JpcHRpb246IiwgZGVzYykKICAgICAgICBidG5z"
    "ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBf"
    "Z290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2Vw"
    "dCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0"
    "KG9rKTsgYnRucy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRucykKICAgICAg"
    "ICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAg"
    "ICAgcmVjWyJjb21tYW5kIl0gICAgID0gY21kLnRleHQoKS5zdHJpcCgpWzoyNDRdCiAgICAgICAg"
    "ICAgIHJlY1siZGVzY3JpcHRpb24iXSA9IGRlc2MudGV4dCgpLnN0cmlwKClbOjI0NF0KICAgICAg"
    "ICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNv"
    "Zm9ybWF0KCkKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3Jk"
    "cykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlm"
    "IHJvdyA8IDAgb3Igcm93ID49IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgY21kID0gc2VsZi5fcmVjb3Jkc1tyb3ddLmdldCgiY29tbWFuZCIsInRoaXMgY29t"
    "bWFuZCIpCiAgICAgICAgcmVwbHkgPSBRTWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAg"
    "c2VsZiwgIkRlbGV0ZSIsIGYiRGVsZXRlICd7Y21kfSc/IiwKICAgICAgICAgICAgUU1lc3NhZ2VC"
    "b3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uTm8KICAg"
    "ICAgICApCiAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVz"
    "OgogICAgICAgICAgICBzZWxmLl9yZWNvcmRzLnBvcChyb3cpCiAgICAgICAgICAgIHdyaXRlX2pz"
    "b25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgp"
    "CgoKIyDilIDilIAgSk9CIFRSQUNLRVIgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBKb2JUcmFja2VyVGFiKFFX"
    "aWRnZXQpOgogICAgIiIiCiAgICBKb2IgYXBwbGljYXRpb24gdHJhY2tpbmcuIEZ1bGwgcmVidWls"
    "ZCBmcm9tIHNwZWMuCiAgICBGaWVsZHM6IENvbXBhbnksIEpvYiBUaXRsZSwgRGF0ZSBBcHBsaWVk"
    "LCBMaW5rLCBTdGF0dXMsIE5vdGVzLgogICAgTXVsdGktc2VsZWN0IGhpZGUvdW5oaWRlL2RlbGV0"
    "ZS4gQ1NWIGFuZCBUU1YgZXhwb3J0LgogICAgSGlkZGVuIHJvd3MgPSBjb21wbGV0ZWQvcmVqZWN0"
    "ZWQg4oCUIHN0aWxsIHN0b3JlZCwganVzdCBub3Qgc2hvd24uCiAgICAiIiIKCiAgICBDT0xVTU5T"
    "ID0gWyJDb21wYW55IiwgIkpvYiBUaXRsZSIsICJEYXRlIEFwcGxpZWQiLAogICAgICAgICAgICAg"
    "ICAiTGluayIsICJTdGF0dXMiLCAiTm90ZXMiXQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJl"
    "bnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5f"
    "cGF0aCAgICA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gImpvYl90cmFja2VyLmpzb25sIgogICAg"
    "ICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3Nob3dfaGlk"
    "ZGVuID0gRmFsc2UKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNo"
    "KCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94"
    "TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkK"
    "ICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgYmFyID0gUUhCb3hMYXlvdXQoKQog"
    "ICAgICAgIHNlbGYuX2J0bl9hZGQgICAgPSBfZ290aGljX2J0bigiQWRkIikKICAgICAgICBzZWxm"
    "Ll9idG5fbW9kaWZ5ID0gX2dvdGhpY19idG4oIk1vZGlmeSIpCiAgICAgICAgc2VsZi5fYnRuX2hp"
    "ZGUgICA9IF9nb3RoaWNfYnRuKCJBcmNoaXZlIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICJNYXJrIHNlbGVjdGVkIGFzIGNvbXBsZXRlZC9yZWplY3RlZCIpCiAgICAg"
    "ICAgc2VsZi5fYnRuX3VuaGlkZSA9IF9nb3RoaWNfYnRuKCJSZXN0b3JlIiwKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICJSZXN0b3JlIGFyY2hpdmVkIGFwcGxpY2F0aW9u"
    "cyIpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSA9IF9nb3RoaWNfYnRuKCJEZWxldGUiKQogICAg"
    "ICAgIHNlbGYuX2J0bl90b2dnbGUgPSBfZ290aGljX2J0bigiU2hvdyBBcmNoaXZlZCIpCiAgICAg"
    "ICAgc2VsZi5fYnRuX2V4cG9ydCA9IF9nb3RoaWNfYnRuKCJFeHBvcnQiKQoKICAgICAgICBmb3Ig"
    "YiBpbiAoc2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRuX21vZGlmeSwgc2VsZi5fYnRuX2hpZGUsCiAg"
    "ICAgICAgICAgICAgICAgIHNlbGYuX2J0bl91bmhpZGUsIHNlbGYuX2J0bl9kZWxldGUsCiAgICAg"
    "ICAgICAgICAgICAgIHNlbGYuX2J0bl90b2dnbGUsIHNlbGYuX2J0bl9leHBvcnQpOgogICAgICAg"
    "ICAgICBiLnNldE1pbmltdW1XaWR0aCg3MCkKICAgICAgICAgICAgYi5zZXRNaW5pbXVtSGVpZ2h0"
    "KDI2KQogICAgICAgICAgICBiYXIuYWRkV2lkZ2V0KGIpCgogICAgICAgIHNlbGYuX2J0bl9hZGQu"
    "Y2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5LmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl9kb19tb2RpZnkpCiAgICAgICAgc2VsZi5fYnRuX2hpZGUuY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX2RvX2hpZGUpCiAgICAgICAgc2VsZi5fYnRuX3VuaGlkZS5jbGlj"
    "a2VkLmNvbm5lY3Qoc2VsZi5fZG9fdW5oaWRlKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fdG9nZ2xlLmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGVfaGlkZGVuKQogICAgICAgIHNlbGYuX2J0bl9leHBv"
    "cnQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2V4cG9ydCkKICAgICAgICBiYXIuYWRkU3RyZXRj"
    "aCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYmFyKQoKICAgICAgICBzZWxmLl90YWJsZSA9IFFU"
    "YWJsZVdpZGdldCgwLCBsZW4oc2VsZi5DT0xVTU5TKSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRI"
    "b3Jpem9udGFsSGVhZGVyTGFiZWxzKHNlbGYuQ09MVU1OUykKICAgICAgICBoaCA9IHNlbGYuX3Rh"
    "YmxlLmhvcml6b250YWxIZWFkZXIoKQogICAgICAgICMgQ29tcGFueSBhbmQgSm9iIFRpdGxlIHN0"
    "cmV0Y2gKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgwLCBRSGVhZGVyVmlldy5SZXNp"
    "emVNb2RlLlN0cmV0Y2gpCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMSwgUUhlYWRl"
    "clZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgICMgRGF0ZSBBcHBsaWVkIOKAlCBmaXhl"
    "ZCByZWFkYWJsZSB3aWR0aAogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDIsIFFIZWFk"
    "ZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Q29sdW1uV2lk"
    "dGgoMiwgMTAwKQogICAgICAgICMgTGluayBzdHJldGNoZXMKICAgICAgICBoaC5zZXRTZWN0aW9u"
    "UmVzaXplTW9kZSgzLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgIyBT"
    "dGF0dXMg4oCUIGZpeGVkIHdpZHRoCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoNCwg"
    "UUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1"
    "bW5XaWR0aCg0LCA4MCkKICAgICAgICAjIE5vdGVzIHN0cmV0Y2hlcwogICAgICAgIGhoLnNldFNl"
    "Y3Rpb25SZXNpemVNb2RlKDUsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKCiAgICAg"
    "ICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0cmFj"
    "dEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFi"
    "bGUuc2V0U2VsZWN0aW9uTW9kZSgKICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0"
    "aW9uTW9kZS5FeHRlbmRlZFNlbGVjdGlvbikKICAgICAgICBzZWxmLl90YWJsZS5zZXRBbHRlcm5h"
    "dGluZ1Jvd0NvbG9ycyhUcnVlKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dv"
    "dGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlLCAx"
    "KQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9"
    "IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRSb3dDb3VudCgw"
    "KQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgaGlkZGVuID0g"
    "Ym9vbChyZWMuZ2V0KCJoaWRkZW4iLCBGYWxzZSkpCiAgICAgICAgICAgIGlmIGhpZGRlbiBhbmQg"
    "bm90IHNlbGYuX3Nob3dfaGlkZGVuOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAg"
    "ICAgciA9IHNlbGYuX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5z"
    "ZXJ0Um93KHIpCiAgICAgICAgICAgIHN0YXR1cyA9ICJBcmNoaXZlZCIgaWYgaGlkZGVuIGVsc2Ug"
    "cmVjLmdldCgic3RhdHVzIiwiQWN0aXZlIikKICAgICAgICAgICAgdmFscyA9IFsKICAgICAgICAg"
    "ICAgICAgIHJlYy5nZXQoImNvbXBhbnkiLCIiKSwKICAgICAgICAgICAgICAgIHJlYy5nZXQoImpv"
    "Yl90aXRsZSIsIiIpLAogICAgICAgICAgICAgICAgcmVjLmdldCgiZGF0ZV9hcHBsaWVkIiwiIiks"
    "CiAgICAgICAgICAgICAgICByZWMuZ2V0KCJsaW5rIiwiIiksCiAgICAgICAgICAgICAgICBzdGF0"
    "dXMsCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJub3RlcyIsIiIpLAogICAgICAgICAgICBdCiAg"
    "ICAgICAgICAgIGZvciBjLCB2IGluIGVudW1lcmF0ZSh2YWxzKToKICAgICAgICAgICAgICAgIGl0"
    "ZW0gPSBRVGFibGVXaWRnZXRJdGVtKHN0cih2KSkKICAgICAgICAgICAgICAgIGlmIGhpZGRlbjoK"
    "ICAgICAgICAgICAgICAgICAgICBpdGVtLnNldEZvcmVncm91bmQoUUNvbG9yKENfVEVYVF9ESU0p"
    "KQogICAgICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCBjLCBpdGVtKQogICAgICAg"
    "ICAgICAjIFN0b3JlIHJlY29yZCBpbmRleCBpbiBmaXJzdCBjb2x1bW4ncyB1c2VyIGRhdGEKICAg"
    "ICAgICAgICAgc2VsZi5fdGFibGUuaXRlbShyLCAwKS5zZXREYXRhKAogICAgICAgICAgICAgICAg"
    "UXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLAogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5p"
    "bmRleChyZWMpCiAgICAgICAgICAgICkKCiAgICBkZWYgX3NlbGVjdGVkX2luZGljZXMoc2VsZikg"
    "LT4gbGlzdFtpbnRdOgogICAgICAgIGluZGljZXMgPSBzZXQoKQogICAgICAgIGZvciBpdGVtIGlu"
    "IHNlbGYuX3RhYmxlLnNlbGVjdGVkSXRlbXMoKToKICAgICAgICAgICAgcm93X2l0ZW0gPSBzZWxm"
    "Ll90YWJsZS5pdGVtKGl0ZW0ucm93KCksIDApCiAgICAgICAgICAgIGlmIHJvd19pdGVtOgogICAg"
    "ICAgICAgICAgICAgaWR4ID0gcm93X2l0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUp"
    "CiAgICAgICAgICAgICAgICBpZiBpZHggaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICAgICAg"
    "aW5kaWNlcy5hZGQoaWR4KQogICAgICAgIHJldHVybiBzb3J0ZWQoaW5kaWNlcykKCiAgICBkZWYg"
    "X2RpYWxvZyhzZWxmLCByZWM6IGRpY3QgPSBOb25lKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAg"
    "ICBkbGcgID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiSm9iIEFw"
    "cGxpY2F0aW9uIikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JH"
    "Mn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5yZXNpemUoNTAwLCAzMjApCiAgICAg"
    "ICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKCiAgICAgICAgY29tcGFueSA9IFFMaW5lRWRpdChy"
    "ZWMuZ2V0KCJjb21wYW55IiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgdGl0bGUgICA9IFFM"
    "aW5lRWRpdChyZWMuZ2V0KCJqb2JfdGl0bGUiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBk"
    "ZSAgICAgID0gUURhdGVFZGl0KCkKICAgICAgICBkZS5zZXRDYWxlbmRhclBvcHVwKFRydWUpCiAg"
    "ICAgICAgZGUuc2V0RGlzcGxheUZvcm1hdCgieXl5eS1NTS1kZCIpCiAgICAgICAgaWYgcmVjIGFu"
    "ZCByZWMuZ2V0KCJkYXRlX2FwcGxpZWQiKToKICAgICAgICAgICAgZGUuc2V0RGF0ZShRRGF0ZS5m"
    "cm9tU3RyaW5nKHJlY1siZGF0ZV9hcHBsaWVkIl0sInl5eXktTU0tZGQiKSkKICAgICAgICBlbHNl"
    "OgogICAgICAgICAgICBkZS5zZXREYXRlKFFEYXRlLmN1cnJlbnREYXRlKCkpCiAgICAgICAgbGlu"
    "ayAgICA9IFFMaW5lRWRpdChyZWMuZ2V0KCJsaW5rIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAg"
    "ICAgc3RhdHVzICA9IFFMaW5lRWRpdChyZWMuZ2V0KCJzdGF0dXMiLCJBcHBsaWVkIikgaWYgcmVj"
    "IGVsc2UgIkFwcGxpZWQiKQogICAgICAgIG5vdGVzICAgPSBRTGluZUVkaXQocmVjLmdldCgibm90"
    "ZXMiLCIiKSBpZiByZWMgZWxzZSAiIikKCiAgICAgICAgZm9yIGxhYmVsLCB3aWRnZXQgaW4gWwog"
    "ICAgICAgICAgICAoIkNvbXBhbnk6IiwgY29tcGFueSksICgiSm9iIFRpdGxlOiIsIHRpdGxlKSwK"
    "ICAgICAgICAgICAgKCJEYXRlIEFwcGxpZWQ6IiwgZGUpLCAoIkxpbms6IiwgbGluayksCiAgICAg"
    "ICAgICAgICgiU3RhdHVzOiIsIHN0YXR1cyksICgiTm90ZXM6Iiwgbm90ZXMpLAogICAgICAgIF06"
    "CiAgICAgICAgICAgIGZvcm0uYWRkUm93KGxhYmVsLCB3aWRnZXQpCgogICAgICAgIGJ0bnMgPSBR"
    "SEJveExheW91dCgpCiAgICAgICAgb2sgPSBfZ290aGljX2J0bigiU2F2ZSIpOyBjeCA9IF9nb3Ro"
    "aWNfYnRuKCJDYW5jZWwiKQogICAgICAgIG9rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KTsg"
    "Y3guY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRucy5hZGRXaWRnZXQob2sp"
    "OyBidG5zLmFkZFdpZGdldChjeCkKICAgICAgICBmb3JtLmFkZFJvdyhidG5zKQoKICAgICAgICBp"
    "ZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAg"
    "cmV0dXJuIHsKICAgICAgICAgICAgICAgICJjb21wYW55IjogICAgICBjb21wYW55LnRleHQoKS5z"
    "dHJpcCgpLAogICAgICAgICAgICAgICAgImpvYl90aXRsZSI6ICAgIHRpdGxlLnRleHQoKS5zdHJp"
    "cCgpLAogICAgICAgICAgICAgICAgImRhdGVfYXBwbGllZCI6IGRlLmRhdGUoKS50b1N0cmluZygi"
    "eXl5eS1NTS1kZCIpLAogICAgICAgICAgICAgICAgImxpbmsiOiAgICAgICAgIGxpbmsudGV4dCgp"
    "LnN0cmlwKCksCiAgICAgICAgICAgICAgICAic3RhdHVzIjogICAgICAgc3RhdHVzLnRleHQoKS5z"
    "dHJpcCgpIG9yICJBcHBsaWVkIiwKICAgICAgICAgICAgICAgICJub3RlcyI6ICAgICAgICBub3Rl"
    "cy50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgfQogICAgICAgIHJldHVybiBOb25lCgogICAg"
    "ZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBwID0gc2VsZi5fZGlhbG9nKCkKICAg"
    "ICAgICBpZiBub3QgcDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgbm93ID0gZGF0ZXRpbWUu"
    "bm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICBwLnVwZGF0ZSh7CiAgICAgICAg"
    "ICAgICJpZCI6ICAgICAgICAgICAgIHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAiaGlk"
    "ZGVuIjogICAgICAgICBGYWxzZSwKICAgICAgICAgICAgImNvbXBsZXRlZF9kYXRlIjogTm9uZSwK"
    "ICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgICAgbm93LAogICAgICAgICAgICAidXBkYXRlZF9h"
    "dCI6ICAgICBub3csCiAgICAgICAgfSkKICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChwKQog"
    "ICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2Vs"
    "Zi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX21vZGlmeShzZWxmKSAtPiBOb25lOgogICAgICAgIGlk"
    "eHMgPSBzZWxmLl9zZWxlY3RlZF9pbmRpY2VzKCkKICAgICAgICBpZiBsZW4oaWR4cykgIT0gMToK"
    "ICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIk1vZGlmeSIsCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgZXhhY3RseSBvbmUgcm93IHRv"
    "IG1vZGlmeS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRz"
    "W2lkeHNbMF1dCiAgICAgICAgcCAgID0gc2VsZi5fZGlhbG9nKHJlYykKICAgICAgICBpZiBub3Qg"
    "cDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjLnVwZGF0ZShwKQogICAgICAgIHJlY1si"
    "dXBkYXRlZF9hdCJdID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAg"
    "ICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYu"
    "cmVmcmVzaCgpCgogICAgZGVmIF9kb19oaWRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIGlk"
    "eCBpbiBzZWxmLl9zZWxlY3RlZF9pbmRpY2VzKCk6CiAgICAgICAgICAgIGlmIGlkeCA8IGxlbihz"
    "ZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsiaGlkZGVu"
    "Il0gICAgICAgICA9IFRydWUKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsiY29t"
    "cGxldGVkX2RhdGUiXSA9ICgKICAgICAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF0u"
    "Z2V0KCJjb21wbGV0ZWRfZGF0ZSIpIG9yCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93"
    "KCkuZGF0ZSgpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9yZWNvcmRzW2lkeF1bInVwZGF0ZWRfYXQiXSA9ICgKICAgICAgICAgICAgICAgICAgICBk"
    "YXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgICAgICAgICAgKQog"
    "ICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2Vs"
    "Zi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX3VuaGlkZShzZWxmKSAtPiBOb25lOgogICAgICAgIGZv"
    "ciBpZHggaW4gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpOgogICAgICAgICAgICBpZiBpZHggPCBs"
    "ZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bImhp"
    "ZGRlbiJdICAgICA9IEZhbHNlCiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bInVw"
    "ZGF0ZWRfYXQiXSA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3codGltZXpvbmUu"
    "dXRjKS5pc29mb3JtYXQoKQogICAgICAgICAgICAgICAgKQogICAgICAgIHdyaXRlX2pzb25sKHNl"
    "bGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYg"
    "X2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlkeHMgPSBzZWxmLl9zZWxlY3RlZF9p"
    "bmRpY2VzKCkKICAgICAgICBpZiBub3QgaWR4czoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAg"
    "cmVwbHkgPSBRTWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSIs"
    "CiAgICAgICAgICAgIGYiRGVsZXRlIHtsZW4oaWR4cyl9IHNlbGVjdGVkIGFwcGxpY2F0aW9uKHMp"
    "PyBDYW5ub3QgYmUgdW5kb25lLiIsCiAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0"
    "dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgKQogICAgICAg"
    "IGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAg"
    "YmFkID0gc2V0KGlkeHMpCiAgICAgICAgICAgIHNlbGYuX3JlY29yZHMgPSBbciBmb3IgaSwgciBp"
    "biBlbnVtZXJhdGUoc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgICAgICAgICAgICAgICAgICBp"
    "ZiBpIG5vdCBpbiBiYWRdCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYu"
    "X3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF90b2dnbGVfaGlk"
    "ZGVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2hvd19oaWRkZW4gPSBub3Qgc2VsZi5f"
    "c2hvd19oaWRkZW4KICAgICAgICBzZWxmLl9idG5fdG9nZ2xlLnNldFRleHQoCiAgICAgICAgICAg"
    "ICLimIAgSGlkZSBBcmNoaXZlZCIgaWYgc2VsZi5fc2hvd19oaWRkZW4gZWxzZSAi4pi9IFNob3cg"
    "QXJjaGl2ZWQiCiAgICAgICAgKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19l"
    "eHBvcnQoc2VsZikgLT4gTm9uZToKICAgICAgICBwYXRoLCBmaWx0ID0gUUZpbGVEaWFsb2cuZ2V0"
    "U2F2ZUZpbGVOYW1lKAogICAgICAgICAgICBzZWxmLCAiRXhwb3J0IEpvYiBUcmFja2VyIiwKICAg"
    "ICAgICAgICAgc3RyKGNmZ19wYXRoKCJleHBvcnRzIikgLyAiam9iX3RyYWNrZXIuY3N2IiksCiAg"
    "ICAgICAgICAgICJDU1YgRmlsZXMgKCouY3N2KTs7VGFiIERlbGltaXRlZCAoKi50eHQpIgogICAg"
    "ICAgICkKICAgICAgICBpZiBub3QgcGF0aDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZGVs"
    "aW0gPSAiXHQiIGlmIHBhdGgubG93ZXIoKS5lbmRzd2l0aCgiLnR4dCIpIGVsc2UgIiwiCiAgICAg"
    "ICAgaGVhZGVyID0gWyJjb21wYW55Iiwiam9iX3RpdGxlIiwiZGF0ZV9hcHBsaWVkIiwibGluayIs"
    "CiAgICAgICAgICAgICAgICAgICJzdGF0dXMiLCJoaWRkZW4iLCJjb21wbGV0ZWRfZGF0ZSIsIm5v"
    "dGVzIl0KICAgICAgICB3aXRoIG9wZW4ocGF0aCwgInciLCBlbmNvZGluZz0idXRmLTgiLCBuZXds"
    "aW5lPSIiKSBhcyBmOgogICAgICAgICAgICBmLndyaXRlKGRlbGltLmpvaW4oaGVhZGVyKSArICJc"
    "biIpCiAgICAgICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgICAg"
    "IHZhbHMgPSBbCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgiY29tcGFueSIsIiIpLAogICAg"
    "ICAgICAgICAgICAgICAgIHJlYy5nZXQoImpvYl90aXRsZSIsIiIpLAogICAgICAgICAgICAgICAg"
    "ICAgIHJlYy5nZXQoImRhdGVfYXBwbGllZCIsIiIpLAogICAgICAgICAgICAgICAgICAgIHJlYy5n"
    "ZXQoImxpbmsiLCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJzdGF0dXMiLCIiKSwK"
    "ICAgICAgICAgICAgICAgICAgICBzdHIoYm9vbChyZWMuZ2V0KCJoaWRkZW4iLEZhbHNlKSkpLAog"
    "ICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImNvbXBsZXRlZF9kYXRlIiwiIikgb3IgIiIsCiAg"
    "ICAgICAgICAgICAgICAgICAgcmVjLmdldCgibm90ZXMiLCIiKSwKICAgICAgICAgICAgICAgIF0K"
    "ICAgICAgICAgICAgICAgIGYud3JpdGUoZGVsaW0uam9pbigKICAgICAgICAgICAgICAgICAgICBz"
    "dHIodikucmVwbGFjZSgiXG4iLCIgIikucmVwbGFjZShkZWxpbSwiICIpCiAgICAgICAgICAgICAg"
    "ICAgICAgZm9yIHYgaW4gdmFscwogICAgICAgICAgICAgICAgKSArICJcbiIpCiAgICAgICAgUU1l"
    "c3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIkV4cG9ydGVkIiwKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBmIlNhdmVkIHRvIHtwYXRofSIpCgoKIyDilIDilIAgU0VMRiBUQUIg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFJlY29yZHNUYWIoUVdpZGdldCk6CiAgICAi"
    "IiJHb29nbGUgRHJpdmUvRG9jcyByZWNvcmRzIGJyb3dzZXIgdGFiLiIiIgoKICAgIGRlZiBfX2lu"
    "aXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQp"
    "CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50"
    "c01hcmdpbnMoNiwgNiwgNiwgNikKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAg"
    "c2VsZi5zdGF0dXNfbGFiZWwgPSBRTGFiZWwoIlJlY29yZHMgYXJlIG5vdCBsb2FkZWQgeWV0LiIp"
    "CiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJj"
    "b2xvcjoge0NfVEVYVF9ESU19OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250"
    "LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLnN0YXR1"
    "c19sYWJlbCkKCiAgICAgICAgc2VsZi5wYXRoX2xhYmVsID0gUUxhYmVsKCJQYXRoOiBNeSBEcml2"
    "ZSIpCiAgICAgICAgc2VsZi5wYXRoX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "Y29sb3I6IHtDX0dPTERfRElNfTsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9u"
    "dC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5wYXRo"
    "X2xhYmVsKQoKICAgICAgICBzZWxmLnJlY29yZHNfbGlzdCA9IFFMaXN0V2lkZ2V0KCkKICAgICAg"
    "ICBzZWxmLnJlY29yZHNfbGlzdC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91"
    "bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVS"
    "fTsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYucmVjb3Jkc19saXN0LCAx"
    "KQoKICAgIGRlZiBzZXRfaXRlbXMoc2VsZiwgZmlsZXM6IGxpc3RbZGljdF0sIHBhdGhfdGV4dDog"
    "c3RyID0gIk15IERyaXZlIikgLT4gTm9uZToKICAgICAgICBzZWxmLnBhdGhfbGFiZWwuc2V0VGV4"
    "dChmIlBhdGg6IHtwYXRoX3RleHR9IikKICAgICAgICBzZWxmLnJlY29yZHNfbGlzdC5jbGVhcigp"
    "CiAgICAgICAgZm9yIGZpbGVfaW5mbyBpbiBmaWxlczoKICAgICAgICAgICAgdGl0bGUgPSAoZmls"
    "ZV9pbmZvLmdldCgibmFtZSIpIG9yICJVbnRpdGxlZCIpLnN0cmlwKCkgb3IgIlVudGl0bGVkIgog"
    "ICAgICAgICAgICBtaW1lID0gKGZpbGVfaW5mby5nZXQoIm1pbWVUeXBlIikgb3IgIiIpLnN0cmlw"
    "KCkKICAgICAgICAgICAgaWYgbWltZSA9PSAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmZv"
    "bGRlciI6CiAgICAgICAgICAgICAgICBwcmVmaXggPSAi8J+TgSIKICAgICAgICAgICAgZWxpZiBt"
    "aW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZG9jdW1lbnQiOgogICAgICAgICAg"
    "ICAgICAgcHJlZml4ID0gIvCfk50iCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBw"
    "cmVmaXggPSAi8J+ThCIKICAgICAgICAgICAgbW9kaWZpZWQgPSAoZmlsZV9pbmZvLmdldCgibW9k"
    "aWZpZWRUaW1lIikgb3IgIiIpLnJlcGxhY2UoIlQiLCAiICIpLnJlcGxhY2UoIloiLCAiIFVUQyIp"
    "CiAgICAgICAgICAgIHRleHQgPSBmIntwcmVmaXh9IHt0aXRsZX0iICsgKGYiICAgIFt7bW9kaWZp"
    "ZWR9XSIgaWYgbW9kaWZpZWQgZWxzZSAiIikKICAgICAgICAgICAgaXRlbSA9IFFMaXN0V2lkZ2V0"
    "SXRlbSh0ZXh0KQogICAgICAgICAgICBpdGVtLnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJS"
    "b2xlLCBmaWxlX2luZm8pCiAgICAgICAgICAgIHNlbGYucmVjb3Jkc19saXN0LmFkZEl0ZW0oaXRl"
    "bSkKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRUZXh0KGYiTG9hZGVkIHtsZW4oZmlsZXMp"
    "fSBHb29nbGUgRHJpdmUgaXRlbShzKS4iKQoKCmNsYXNzIFRhc2tzVGFiKFFXaWRnZXQpOgogICAg"
    "IiIiVGFzayByZWdpc3RyeSArIEdvb2dsZS1maXJzdCBlZGl0b3Igd29ya2Zsb3cgdGFiLiIiIgoK"
    "ICAgIGRlZiBfX2luaXRfXygKICAgICAgICBzZWxmLAogICAgICAgIHRhc2tzX3Byb3ZpZGVyLAog"
    "ICAgICAgIG9uX2FkZF9lZGl0b3Jfb3BlbiwKICAgICAgICBvbl9jb21wbGV0ZV9zZWxlY3RlZCwK"
    "ICAgICAgICBvbl9jYW5jZWxfc2VsZWN0ZWQsCiAgICAgICAgb25fdG9nZ2xlX2NvbXBsZXRlZCwK"
    "ICAgICAgICBvbl9wdXJnZV9jb21wbGV0ZWQsCiAgICAgICAgb25fZmlsdGVyX2NoYW5nZWQsCiAg"
    "ICAgICAgb25fZWRpdG9yX3NhdmUsCiAgICAgICAgb25fZWRpdG9yX2NhbmNlbCwKICAgICAgICBk"
    "aWFnbm9zdGljc19sb2dnZXI9Tm9uZSwKICAgICAgICBwYXJlbnQ9Tm9uZSwKICAgICk6CiAgICAg"
    "ICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fdGFza3NfcHJvdmlkZXIg"
    "PSB0YXNrc19wcm92aWRlcgogICAgICAgIHNlbGYuX29uX2FkZF9lZGl0b3Jfb3BlbiA9IG9uX2Fk"
    "ZF9lZGl0b3Jfb3BlbgogICAgICAgIHNlbGYuX29uX2NvbXBsZXRlX3NlbGVjdGVkID0gb25fY29t"
    "cGxldGVfc2VsZWN0ZWQKICAgICAgICBzZWxmLl9vbl9jYW5jZWxfc2VsZWN0ZWQgPSBvbl9jYW5j"
    "ZWxfc2VsZWN0ZWQKICAgICAgICBzZWxmLl9vbl90b2dnbGVfY29tcGxldGVkID0gb25fdG9nZ2xl"
    "X2NvbXBsZXRlZAogICAgICAgIHNlbGYuX29uX3B1cmdlX2NvbXBsZXRlZCA9IG9uX3B1cmdlX2Nv"
    "bXBsZXRlZAogICAgICAgIHNlbGYuX29uX2ZpbHRlcl9jaGFuZ2VkID0gb25fZmlsdGVyX2NoYW5n"
    "ZWQKICAgICAgICBzZWxmLl9vbl9lZGl0b3Jfc2F2ZSA9IG9uX2VkaXRvcl9zYXZlCiAgICAgICAg"
    "c2VsZi5fb25fZWRpdG9yX2NhbmNlbCA9IG9uX2VkaXRvcl9jYW5jZWwKICAgICAgICBzZWxmLl9k"
    "aWFnX2xvZ2dlciA9IGRpYWdub3N0aWNzX2xvZ2dlcgogICAgICAgIHNlbGYuX3Nob3dfY29tcGxl"
    "dGVkID0gRmFsc2UKICAgICAgICBzZWxmLl9yZWZyZXNoX3RocmVhZCA9IE5vbmUKICAgICAgICBz"
    "ZWxmLl9idWlsZF91aSgpCgogICAgZGVmIF9idWlsZF91aShzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5z"
    "KDYsIDYsIDYsIDYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi53b3Jr"
    "c3BhY2Vfc3RhY2sgPSBRU3RhY2tlZFdpZGdldCgpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2Vs"
    "Zi53b3Jrc3BhY2Vfc3RhY2ssIDEpCgogICAgICAgIG5vcm1hbCA9IFFXaWRnZXQoKQogICAgICAg"
    "IG5vcm1hbF9sYXlvdXQgPSBRVkJveExheW91dChub3JtYWwpCiAgICAgICAgbm9ybWFsX2xheW91"
    "dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBub3JtYWxfbGF5b3V0LnNl"
    "dFNwYWNpbmcoNCkKCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwgPSBRTGFiZWwoIlRhc2sgcmVn"
    "aXN0cnkgaXMgbm90IGxvYWRlZCB5ZXQuIikKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtZmFtaWx5"
    "OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAg"
    "IG5vcm1hbF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuc3RhdHVzX2xhYmVsKQoKICAgICAgICBmaWx0"
    "ZXJfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KF9zZWN0"
    "aW9uX2xibCgi4p2nIERBVEUgUkFOR0UiKSkKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJv"
    "ID0gUUNvbWJvQm94KCkKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFkZEl0ZW0oIldF"
    "RUsiLCAid2VlayIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5hZGRJdGVtKCJNT05U"
    "SCIsICJtb250aCIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5hZGRJdGVtKCJORVhU"
    "IDMgTU9OVEhTIiwgIm5leHRfM19tb250aHMiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29t"
    "Ym8uYWRkSXRlbSgiWUVBUiIsICJ5ZWFyIikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJv"
    "LnNldEN1cnJlbnRJbmRleCgyKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uY3VycmVu"
    "dEluZGV4Q2hhbmdlZC5jb25uZWN0KAogICAgICAgICAgICBsYW1iZGEgXzogc2VsZi5fb25fZmls"
    "dGVyX2NoYW5nZWQoc2VsZi50YXNrX2ZpbHRlcl9jb21iby5jdXJyZW50RGF0YSgpIG9yICJuZXh0"
    "XzNfbW9udGhzIikKICAgICAgICApCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoc2VsZi50"
    "YXNrX2ZpbHRlcl9jb21ibykKICAgICAgICBmaWx0ZXJfcm93LmFkZFN0cmV0Y2goMSkKICAgICAg"
    "ICBub3JtYWxfbGF5b3V0LmFkZExheW91dChmaWx0ZXJfcm93KQoKICAgICAgICBzZWxmLnRhc2tf"
    "dGFibGUgPSBRVGFibGVXaWRnZXQoMCwgNCkKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0SG9y"
    "aXpvbnRhbEhlYWRlckxhYmVscyhbIlN0YXR1cyIsICJEdWUiLCAiVGFzayIsICJTb3VyY2UiXSkK"
    "ICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoUUFic3RyYWN0SXRl"
    "bVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLnRhc2tfdGFi"
    "bGUuc2V0U2VsZWN0aW9uTW9kZShRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25Nb2RlLkV4dGVu"
    "ZGVkU2VsZWN0aW9uKQogICAgICAgIHNlbGYudGFza190YWJsZS5zZXRFZGl0VHJpZ2dlcnMoUUFi"
    "c3RyYWN0SXRlbVZpZXcuRWRpdFRyaWdnZXIuTm9FZGl0VHJpZ2dlcnMpCiAgICAgICAgc2VsZi50"
    "YXNrX3RhYmxlLnZlcnRpY2FsSGVhZGVyKCkuc2V0VmlzaWJsZShGYWxzZSkKICAgICAgICBzZWxm"
    "LnRhc2tfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKDAsIFFI"
    "ZWFkZXJWaWV3LlJlc2l6ZU1vZGUuUmVzaXplVG9Db250ZW50cykKICAgICAgICBzZWxmLnRhc2tf"
    "dGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKDEsIFFIZWFkZXJW"
    "aWV3LlJlc2l6ZU1vZGUuUmVzaXplVG9Db250ZW50cykKICAgICAgICBzZWxmLnRhc2tfdGFibGUu"
    "aG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKDIsIFFIZWFkZXJWaWV3LlJl"
    "c2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLnRhc2tfdGFibGUuaG9yaXpvbnRhbEhlYWRl"
    "cigpLnNldFNlY3Rpb25SZXNpemVNb2RlKDMsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuUmVzaXpl"
    "VG9Db250ZW50cykKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGlj"
    "X3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLml0ZW1TZWxlY3Rpb25DaGFu"
    "Z2VkLmNvbm5lY3Qoc2VsZi5fdXBkYXRlX2FjdGlvbl9idXR0b25fc3RhdGUpCiAgICAgICAgbm9y"
    "bWFsX2xheW91dC5hZGRXaWRnZXQoc2VsZi50YXNrX3RhYmxlLCAxKQoKICAgICAgICBhY3Rpb25z"
    "ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuYnRuX2FkZF90YXNrX3dvcmtzcGFjZSA9IF9n"
    "b3RoaWNfYnRuKCJBREQgVEFTSyIpCiAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzayA9IF9n"
    "b3RoaWNfYnRuKCJDT01QTEVURSBTRUxFQ1RFRCIpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rh"
    "c2sgPSBfZ290aGljX2J0bigiQ0FOQ0VMIFNFTEVDVEVEIikKICAgICAgICBzZWxmLmJ0bl90b2dn"
    "bGVfY29tcGxldGVkID0gX2dvdGhpY19idG4oIlNIT1cgQ09NUExFVEVEIikKICAgICAgICBzZWxm"
    "LmJ0bl9wdXJnZV9jb21wbGV0ZWQgPSBfZ290aGljX2J0bigiUFVSR0UgQ09NUExFVEVEIikKICAg"
    "ICAgICBzZWxmLmJ0bl9hZGRfdGFza193b3Jrc3BhY2UuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29u"
    "X2FkZF9lZGl0b3Jfb3BlbikKICAgICAgICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrLmNsaWNrZWQu"
    "Y29ubmVjdChzZWxmLl9vbl9jb21wbGV0ZV9zZWxlY3RlZCkKICAgICAgICBzZWxmLmJ0bl9jYW5j"
    "ZWxfdGFzay5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fY2FuY2VsX3NlbGVjdGVkKQogICAgICAg"
    "IHNlbGYuYnRuX3RvZ2dsZV9jb21wbGV0ZWQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX3RvZ2ds"
    "ZV9jb21wbGV0ZWQpCiAgICAgICAgc2VsZi5idG5fcHVyZ2VfY29tcGxldGVkLmNsaWNrZWQuY29u"
    "bmVjdChzZWxmLl9vbl9wdXJnZV9jb21wbGV0ZWQpCiAgICAgICAgc2VsZi5idG5fY29tcGxldGVf"
    "dGFzay5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrLnNldEVu"
    "YWJsZWQoRmFsc2UpCiAgICAgICAgZm9yIGJ0biBpbiAoCiAgICAgICAgICAgIHNlbGYuYnRuX2Fk"
    "ZF90YXNrX3dvcmtzcGFjZSwKICAgICAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzaywKICAg"
    "ICAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2ssCiAgICAgICAgICAgIHNlbGYuYnRuX3RvZ2ds"
    "ZV9jb21wbGV0ZWQsCiAgICAgICAgICAgIHNlbGYuYnRuX3B1cmdlX2NvbXBsZXRlZCwKICAgICAg"
    "ICApOgogICAgICAgICAgICBhY3Rpb25zLmFkZFdpZGdldChidG4pCiAgICAgICAgbm9ybWFsX2xh"
    "eW91dC5hZGRMYXlvdXQoYWN0aW9ucykKICAgICAgICBzZWxmLndvcmtzcGFjZV9zdGFjay5hZGRX"
    "aWRnZXQobm9ybWFsKQoKICAgICAgICBlZGl0b3IgPSBRV2lkZ2V0KCkKICAgICAgICBlZGl0b3Jf"
    "bGF5b3V0ID0gUVZCb3hMYXlvdXQoZWRpdG9yKQogICAgICAgIGVkaXRvcl9sYXlvdXQuc2V0Q29u"
    "dGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgZWRpdG9yX2xheW91dC5zZXRTcGFjaW5n"
    "KDQpCiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgVEFT"
    "SyBFRElUT1Ig4oCUIEdPT0dMRS1GSVJTVCIpKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3Rh"
    "dHVzX2xhYmVsID0gUUxhYmVsKCJDb25maWd1cmUgdGFzayBkZXRhaWxzLCB0aGVuIHNhdmUgdG8g"
    "R29vZ2xlIENhbGVuZGFyLiIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwu"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjog"
    "e0NfVEVYVF9ESU19OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA2cHg7"
    "IgogICAgICAgICkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChzZWxmLnRhc2tfZWRp"
    "dG9yX3N0YXR1c19sYWJlbCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25hbWUgPSBRTGluZUVk"
    "aXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfbmFtZS5zZXRQbGFjZWhvbGRlclRleHQoIlRh"
    "c2sgTmFtZSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF9kYXRlID0gUUxpbmVFZGl0"
    "KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUuc2V0UGxhY2Vob2xkZXJUZXh0"
    "KCJTdGFydCBEYXRlIChZWVlZLU1NLUREKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFy"
    "dF90aW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUu"
    "c2V0UGxhY2Vob2xkZXJUZXh0KCJTdGFydCBUaW1lIChISDpNTSkiKQogICAgICAgIHNlbGYudGFz"
    "a19lZGl0b3JfZW5kX2RhdGUgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jf"
    "ZW5kX2RhdGUuc2V0UGxhY2Vob2xkZXJUZXh0KCJFbmQgRGF0ZSAoWVlZWS1NTS1ERCkiKQogICAg"
    "ICAgIHNlbGYudGFza19lZGl0b3JfZW5kX3RpbWUgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYu"
    "dGFza19lZGl0b3JfZW5kX3RpbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJFbmQgVGltZSAoSEg6TU0p"
    "IikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2xvY2F0aW9uID0gUUxpbmVFZGl0KCkKICAgICAg"
    "ICBzZWxmLnRhc2tfZWRpdG9yX2xvY2F0aW9uLnNldFBsYWNlaG9sZGVyVGV4dCgiTG9jYXRpb24g"
    "KG9wdGlvbmFsKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlID0gUUxpbmVF"
    "ZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3JlY3VycmVuY2Uuc2V0UGxhY2Vob2xkZXJU"
    "ZXh0KCJSZWN1cnJlbmNlIFJSVUxFIChvcHRpb25hbCkiKQogICAgICAgIHNlbGYudGFza19lZGl0"
    "b3JfYWxsX2RheSA9IFFDaGVja0JveCgiQWxsLWRheSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRv"
    "cl9ub3RlcyA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9ub3Rlcy5zZXRQ"
    "bGFjZWhvbGRlclRleHQoIk5vdGVzIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25vdGVzLnNl"
    "dE1heGltdW1IZWlnaHQoOTApCiAgICAgICAgZm9yIHdpZGdldCBpbiAoCiAgICAgICAgICAgIHNl"
    "bGYudGFza19lZGl0b3JfbmFtZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF9k"
    "YXRlLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUsCiAgICAgICAgICAg"
    "IHNlbGYudGFza19lZGl0b3JfZW5kX2RhdGUsCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3Jf"
    "ZW5kX3RpbWUsCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3JfbG9jYXRpb24sCiAgICAgICAg"
    "ICAgIHNlbGYudGFza19lZGl0b3JfcmVjdXJyZW5jZSwKICAgICAgICApOgogICAgICAgICAgICBl"
    "ZGl0b3JfbGF5b3V0LmFkZFdpZGdldCh3aWRnZXQpCiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRX"
    "aWRnZXQoc2VsZi50YXNrX2VkaXRvcl9hbGxfZGF5KQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRk"
    "V2lkZ2V0KHNlbGYudGFza19lZGl0b3Jfbm90ZXMsIDEpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMg"
    "PSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX3NhdmUgPSBfZ290aGljX2J0bigiU0FWRSIpCiAg"
    "ICAgICAgYnRuX2NhbmNlbCA9IF9nb3RoaWNfYnRuKCJDQU5DRUwiKQogICAgICAgIGJ0bl9zYXZl"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9lZGl0b3Jfc2F2ZSkKICAgICAgICBidG5fY2FuY2Vs"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9lZGl0b3JfY2FuY2VsKQogICAgICAgIGVkaXRvcl9h"
    "Y3Rpb25zLmFkZFdpZGdldChidG5fc2F2ZSkKICAgICAgICBlZGl0b3JfYWN0aW9ucy5hZGRXaWRn"
    "ZXQoYnRuX2NhbmNlbCkKICAgICAgICBlZGl0b3JfYWN0aW9ucy5hZGRTdHJldGNoKDEpCiAgICAg"
    "ICAgZWRpdG9yX2xheW91dC5hZGRMYXlvdXQoZWRpdG9yX2FjdGlvbnMpCiAgICAgICAgc2VsZi53"
    "b3Jrc3BhY2Vfc3RhY2suYWRkV2lkZ2V0KGVkaXRvcikKCiAgICAgICAgc2VsZi5ub3JtYWxfd29y"
    "a3NwYWNlID0gbm9ybWFsCiAgICAgICAgc2VsZi5lZGl0b3Jfd29ya3NwYWNlID0gZWRpdG9yCiAg"
    "ICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suc2V0Q3VycmVudFdpZGdldChzZWxmLm5vcm1hbF93"
    "b3Jrc3BhY2UpCgogICAgZGVmIF91cGRhdGVfYWN0aW9uX2J1dHRvbl9zdGF0ZShzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIGVuYWJsZWQgPSBib29sKHNlbGYuc2VsZWN0ZWRfdGFza19pZHMoKSkKICAg"
    "ICAgICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrLnNldEVuYWJsZWQoZW5hYmxlZCkKICAgICAgICBz"
    "ZWxmLmJ0bl9jYW5jZWxfdGFzay5zZXRFbmFibGVkKGVuYWJsZWQpCgogICAgZGVmIHNlbGVjdGVk"
    "X3Rhc2tfaWRzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICBpZHM6IGxpc3Rbc3RyXSA9IFtd"
    "CiAgICAgICAgZm9yIHIgaW4gcmFuZ2Uoc2VsZi50YXNrX3RhYmxlLnJvd0NvdW50KCkpOgogICAg"
    "ICAgICAgICBzdGF0dXNfaXRlbSA9IHNlbGYudGFza190YWJsZS5pdGVtKHIsIDApCiAgICAgICAg"
    "ICAgIGlmIHN0YXR1c19pdGVtIGlzIE5vbmU6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAg"
    "ICAgICAgICBpZiBub3Qgc3RhdHVzX2l0ZW0uaXNTZWxlY3RlZCgpOgogICAgICAgICAgICAgICAg"
    "Y29udGludWUKICAgICAgICAgICAgdGFza19pZCA9IHN0YXR1c19pdGVtLmRhdGEoUXQuSXRlbURh"
    "dGFSb2xlLlVzZXJSb2xlKQogICAgICAgICAgICBpZiB0YXNrX2lkIGFuZCB0YXNrX2lkIG5vdCBp"
    "biBpZHM6CiAgICAgICAgICAgICAgICBpZHMuYXBwZW5kKHRhc2tfaWQpCiAgICAgICAgcmV0dXJu"
    "IGlkcwoKICAgIGRlZiBsb2FkX3Rhc2tzKHNlbGYsIHRhc2tzOiBsaXN0W2RpY3RdKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYudGFza190YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciB0YXNr"
    "IGluIHRhc2tzOgogICAgICAgICAgICByb3cgPSBzZWxmLnRhc2tfdGFibGUucm93Q291bnQoKQog"
    "ICAgICAgICAgICBzZWxmLnRhc2tfdGFibGUuaW5zZXJ0Um93KHJvdykKICAgICAgICAgICAgc3Rh"
    "dHVzID0gKHRhc2suZ2V0KCJzdGF0dXMiKSBvciAicGVuZGluZyIpLmxvd2VyKCkKICAgICAgICAg"
    "ICAgc3RhdHVzX2ljb24gPSAi4piRIiBpZiBzdGF0dXMgaW4geyJjb21wbGV0ZWQiLCAiY2FuY2Vs"
    "bGVkIn0gZWxzZSAi4oCiIgogICAgICAgICAgICBkdWUgPSAodGFzay5nZXQoImR1ZV9hdCIpIG9y"
    "ICIiKS5yZXBsYWNlKCJUIiwgIiAiKQogICAgICAgICAgICB0ZXh0ID0gKHRhc2suZ2V0KCJ0ZXh0"
    "Iikgb3IgIlJlbWluZGVyIikuc3RyaXAoKSBvciAiUmVtaW5kZXIiCiAgICAgICAgICAgIHNvdXJj"
    "ZSA9ICh0YXNrLmdldCgic291cmNlIikgb3IgImxvY2FsIikubG93ZXIoKQogICAgICAgICAgICBz"
    "dGF0dXNfaXRlbSA9IFFUYWJsZVdpZGdldEl0ZW0oZiJ7c3RhdHVzX2ljb259IHtzdGF0dXN9IikK"
    "ICAgICAgICAgICAgc3RhdHVzX2l0ZW0uc2V0RGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUs"
    "IHRhc2suZ2V0KCJpZCIpKQogICAgICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0SXRlbShyb3cs"
    "IDAsIHN0YXR1c19pdGVtKQogICAgICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0SXRlbShyb3cs"
    "IDEsIFFUYWJsZVdpZGdldEl0ZW0oZHVlKSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNl"
    "dEl0ZW0ocm93LCAyLCBRVGFibGVXaWRnZXRJdGVtKHRleHQpKQogICAgICAgICAgICBzZWxmLnRh"
    "c2tfdGFibGUuc2V0SXRlbShyb3csIDMsIFFUYWJsZVdpZGdldEl0ZW0oc291cmNlKSkKICAgICAg"
    "ICBzZWxmLnN0YXR1c19sYWJlbC5zZXRUZXh0KGYiTG9hZGVkIHtsZW4odGFza3MpfSB0YXNrKHMp"
    "LiIpCiAgICAgICAgc2VsZi5fdXBkYXRlX2FjdGlvbl9idXR0b25fc3RhdGUoKQoKICAgIGRlZiBf"
    "ZGlhZyhzZWxmLCBtZXNzYWdlOiBzdHIsIGxldmVsOiBzdHIgPSAiSU5GTyIpIC0+IE5vbmU6CiAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICBpZiBzZWxmLl9kaWFnX2xvZ2dlcjoKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX2RpYWdfbG9nZ2VyKG1lc3NhZ2UsIGxldmVsKQogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICBkZWYgc3RvcF9yZWZyZXNoX3dvcmtlcihzZWxm"
    "LCByZWFzb246IHN0ciA9ICIiKSAtPiBOb25lOgogICAgICAgIHRocmVhZCA9IGdldGF0dHIoc2Vs"
    "ZiwgIl9yZWZyZXNoX3RocmVhZCIsIE5vbmUpCiAgICAgICAgaWYgdGhyZWFkIGlzIG5vdCBOb25l"
    "IGFuZCBoYXNhdHRyKHRocmVhZCwgImlzUnVubmluZyIpIGFuZCB0aHJlYWQuaXNSdW5uaW5nKCk6"
    "CiAgICAgICAgICAgIHNlbGYuX2RpYWcoCiAgICAgICAgICAgICAgICBmIltUQVNLU11bVEhSRUFE"
    "XVtXQVJOXSBzdG9wIHJlcXVlc3RlZCBmb3IgcmVmcmVzaCB3b3JrZXIgcmVhc29uPXtyZWFzb24g"
    "b3IgJ3Vuc3BlY2lmaWVkJ30iLAogICAgICAgICAgICAgICAgIldBUk4iLAogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHRocmVhZC5yZXF1ZXN0SW50ZXJydXB0"
    "aW9uKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MK"
    "ICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgdGhyZWFkLnF1aXQoKQogICAgICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwogICAgICAgICAgICB0aHJl"
    "YWQud2FpdCgyMDAwKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGhyZWFkID0gTm9uZQoKICAgIGRl"
    "ZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IGNhbGxhYmxlKHNlbGYuX3Rh"
    "c2tzX3Byb3ZpZGVyKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAg"
    "ICBzZWxmLmxvYWRfdGFza3Moc2VsZi5fdGFza3NfcHJvdmlkZXIoKSkKICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnKGYiW1RBU0tTXVtUQUJdW0VS"
    "Uk9SXSByZWZyZXNoIGZhaWxlZDoge2V4fSIsICJFUlJPUiIpCiAgICAgICAgICAgIHNlbGYuc3Rv"
    "cF9yZWZyZXNoX3dvcmtlcihyZWFzb249InRhc2tzX3RhYl9yZWZyZXNoX2V4Y2VwdGlvbiIpCgog"
    "ICAgZGVmIGNsb3NlRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zdG9w"
    "X3JlZnJlc2hfd29ya2VyKHJlYXNvbj0idGFza3NfdGFiX2Nsb3NlIikKICAgICAgICBzdXBlcigp"
    "LmNsb3NlRXZlbnQoZXZlbnQpCgogICAgZGVmIHNldF9zaG93X2NvbXBsZXRlZChzZWxmLCBlbmFi"
    "bGVkOiBib29sKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nob3dfY29tcGxldGVkID0gYm9vbChl"
    "bmFibGVkKQogICAgICAgIHNlbGYuYnRuX3RvZ2dsZV9jb21wbGV0ZWQuc2V0VGV4dCgiSElERSBD"
    "T01QTEVURUQiIGlmIHNlbGYuX3Nob3dfY29tcGxldGVkIGVsc2UgIlNIT1cgQ09NUExFVEVEIikK"
    "CiAgICBkZWYgc2V0X3N0YXR1cyhzZWxmLCB0ZXh0OiBzdHIsIG9rOiBib29sID0gRmFsc2UpIC0+"
    "IE5vbmU6CiAgICAgICAgY29sb3IgPSBDX0dSRUVOIGlmIG9rIGVsc2UgQ19URVhUX0RJTQogICAg"
    "ICAgIHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtjb2xvcn07IGJvcmRlcjogMXB4IHNv"
    "bGlkIHtDX0JPUkRFUn07IHBhZGRpbmc6IDZweDsiCiAgICAgICAgKQogICAgICAgIHNlbGYudGFz"
    "a19lZGl0b3Jfc3RhdHVzX2xhYmVsLnNldFRleHQodGV4dCkKCiAgICBkZWYgb3Blbl9lZGl0b3Io"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLndvcmtzcGFjZV9zdGFjay5zZXRDdXJyZW50V2lk"
    "Z2V0KHNlbGYuZWRpdG9yX3dvcmtzcGFjZSkKCiAgICBkZWYgY2xvc2VfZWRpdG9yKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suc2V0Q3VycmVudFdpZGdldChzZWxm"
    "Lm5vcm1hbF93b3Jrc3BhY2UpCgoKY2xhc3MgU2VsZlRhYihRV2lkZ2V0KToKICAgICIiIgogICAg"
    "UGVyc29uYSdzIGludGVybmFsIGRpYWxvZ3VlIHNwYWNlLgogICAgUmVjZWl2ZXM6IGlkbGUgbmFy"
    "cmF0aXZlIG91dHB1dCwgdW5zb2xpY2l0ZWQgdHJhbnNtaXNzaW9ucywKICAgICAgICAgICAgICBQ"
    "b0kgbGlzdCBmcm9tIGRhaWx5IHJlZmxlY3Rpb24sIHVuYW5zd2VyZWQgcXVlc3Rpb24gZmxhZ3Ms"
    "CiAgICAgICAgICAgICAgam91cm5hbCBsb2FkIG5vdGlmaWNhdGlvbnMuCiAgICBSZWFkLW9ubHkg"
    "ZGlzcGxheS4gU2VwYXJhdGUgZnJvbSBwZXJzb25hIGNoYXQgdGFiIGFsd2F5cy4KICAgICIiIgoK"
    "ICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2lu"
    "aXRfXyhwYXJlbnQpCiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9v"
    "dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmco"
    "NCkKCiAgICAgICAgaGRyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGhkci5hZGRXaWRnZXQoX3Nl"
    "Y3Rpb25fbGJsKGYi4p2nIElOTkVSIFNBTkNUVU0g4oCUIHtERUNLX05BTUUudXBwZXIoKX0nUyBQ"
    "UklWQVRFIFRIT1VHSFRTIikpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyID0gX2dvdGhpY19idG4o"
    "IuKclyBDbGVhciIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyLnNldEZpeGVkV2lkdGgoODApCiAg"
    "ICAgICAgc2VsZi5fYnRuX2NsZWFyLmNsaWNrZWQuY29ubmVjdChzZWxmLmNsZWFyKQogICAgICAg"
    "IGhkci5hZGRTdHJldGNoKCkKICAgICAgICBoZHIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9jbGVhcikK"
    "ICAgICAgICByb290LmFkZExheW91dChoZHIpCgogICAgICAgIHNlbGYuX2Rpc3BsYXkgPSBRVGV4"
    "dEVkaXQoKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBz"
    "ZWxmLl9kaXNwbGF5LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0Nf"
    "TU9OSVRPUn07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNv"
    "bGlkIHtDX1BVUlBMRV9ESU19OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZP"
    "TlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA4cHg7IgogICAgICAgICkKICAg"
    "ICAgICByb290LmFkZFdpZGdldChzZWxmLl9kaXNwbGF5LCAxKQoKICAgIGRlZiBhcHBlbmQoc2Vs"
    "ZiwgbGFiZWw6IHN0ciwgdGV4dDogc3RyKSAtPiBOb25lOgogICAgICAgIHRpbWVzdGFtcCA9IGRh"
    "dGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUyIpCiAgICAgICAgY29sb3JzID0gewogICAg"
    "ICAgICAgICAiTkFSUkFUSVZFIjogIENfR09MRCwKICAgICAgICAgICAgIlJFRkxFQ1RJT04iOiBD"
    "X1BVUlBMRSwKICAgICAgICAgICAgIkpPVVJOQUwiOiAgICBDX1NJTFZFUiwKICAgICAgICAgICAg"
    "IlBPSSI6ICAgICAgICBDX0dPTERfRElNLAogICAgICAgICAgICAiU1lTVEVNIjogICAgIENfVEVY"
    "VF9ESU0sCiAgICAgICAgfQogICAgICAgIGNvbG9yID0gY29sb3JzLmdldChsYWJlbC51cHBlcigp"
    "LCBDX0dPTEQpCiAgICAgICAgc2VsZi5fZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgIGYnPHNw"
    "YW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAg"
    "ICAgIGYnW3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJj"
    "b2xvcjp7Y29sb3J9OyBmb250LXdlaWdodDpib2xkOyI+JwogICAgICAgICAgICBmJ+KdpyB7bGFi"
    "ZWx9PC9zcGFuPjxicj4nCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX0dPTER9"
    "OyI+e3RleHR9PC9zcGFuPicKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcGxheS5hcHBlbmQo"
    "IiIpCiAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLnNldFZhbHVlKAog"
    "ICAgICAgICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAg"
    "ICAgICAgKQoKICAgIGRlZiBjbGVhcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Rpc3Bs"
    "YXkuY2xlYXIoKQoKCiMg4pSA4pSAIERJQUdOT1NUSUNTIFRBQiDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgRGlhZ25v"
    "c3RpY3NUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIEJhY2tlbmQgZGlhZ25vc3RpY3MgZGlzcGxh"
    "eS4KICAgIFJlY2VpdmVzOiBoYXJkd2FyZSBkZXRlY3Rpb24gcmVzdWx0cywgZGVwZW5kZW5jeSBj"
    "aGVjayByZXN1bHRzLAogICAgICAgICAgICAgIEFQSSBlcnJvcnMsIHN5bmMgZmFpbHVyZXMsIHRp"
    "bWVyIGV2ZW50cywgam91cm5hbCBsb2FkIG5vdGljZXMsCiAgICAgICAgICAgICAgbW9kZWwgbG9h"
    "ZCBzdGF0dXMsIEdvb2dsZSBhdXRoIGV2ZW50cy4KICAgIEFsd2F5cyBzZXBhcmF0ZSBmcm9tIHBl"
    "cnNvbmEgY2hhdCB0YWIuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5v"
    "bmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJv"
    "eExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQp"
    "CiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGhkciA9IFFIQm94TGF5b3V0KCkK"
    "ICAgICAgICBoZHIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIERJQUdOT1NUSUNTIOKAlCBT"
    "WVNURU0gJiBCQUNLRU5EIExPRyIpKQogICAgICAgIHNlbGYuX2J0bl9jbGVhciA9IF9nb3RoaWNf"
    "YnRuKCLinJcgQ2xlYXIiKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5zZXRGaXhlZFdpZHRoKDgw"
    "KQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5jbGlja2VkLmNvbm5lY3Qoc2VsZi5jbGVhcikKICAg"
    "ICAgICBoZHIuYWRkU3RyZXRjaCgpCiAgICAgICAgaGRyLmFkZFdpZGdldChzZWxmLl9idG5fY2xl"
    "YXIpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoaGRyKQoKICAgICAgICBzZWxmLl9kaXNwbGF5ID0g"
    "UVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAg"
    "ICAgc2VsZi5fZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6"
    "IHtDX01PTklUT1J9OyBjb2xvcjoge0NfU0lMVkVSfTsgIgogICAgICAgICAgICBmImJvcmRlcjog"
    "MXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseTogJ0NvdXJp"
    "ZXIgTmV3JywgbW9ub3NwYWNlOyAiCiAgICAgICAgICAgIGYiZm9udC1zaXplOiAxMHB4OyBwYWRk"
    "aW5nOiA4cHg7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9kaXNwbGF5"
    "LCAxKQoKICAgIGRlZiBsb2coc2VsZiwgbWVzc2FnZTogc3RyLCBsZXZlbDogc3RyID0gIklORk8i"
    "KSAtPiBOb25lOgogICAgICAgIHRpbWVzdGFtcCA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIl"
    "SDolTTolUyIpCiAgICAgICAgbGV2ZWxfY29sb3JzID0gewogICAgICAgICAgICAiSU5GTyI6ICBD"
    "X1NJTFZFUiwKICAgICAgICAgICAgIk9LIjogICAgQ19HUkVFTiwKICAgICAgICAgICAgIldBUk4i"
    "OiAgQ19HT0xELAogICAgICAgICAgICAiRVJST1IiOiBDX0JMT09ELAogICAgICAgICAgICAiREVC"
    "VUciOiBDX1RFWFRfRElNLAogICAgICAgIH0KICAgICAgICBjb2xvciA9IGxldmVsX2NvbG9ycy5n"
    "ZXQobGV2ZWwudXBwZXIoKSwgQ19TSUxWRVIpCiAgICAgICAgc2VsZi5fZGlzcGxheS5hcHBlbmQo"
    "CiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsiPlt7dGltZXN0"
    "YW1wfV08L3NwYW4+ICcKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2NvbG9yfTsi"
    "PnttZXNzYWdlfTwvc3Bhbj4nCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGlj"
    "YWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNh"
    "bFNjcm9sbEJhcigpLm1heGltdW0oKQogICAgICAgICkKCiAgICBkZWYgbG9nX21hbnkoc2VsZiwg"
    "bWVzc2FnZXM6IGxpc3Rbc3RyXSwgbGV2ZWw6IHN0ciA9ICJJTkZPIikgLT4gTm9uZToKICAgICAg"
    "ICBmb3IgbXNnIGluIG1lc3NhZ2VzOgogICAgICAgICAgICBsdmwgPSBsZXZlbAogICAgICAgICAg"
    "ICBpZiAi4pyTIiBpbiBtc2c6ICAgIGx2bCA9ICJPSyIKICAgICAgICAgICAgZWxpZiAi4pyXIiBp"
    "biBtc2c6ICBsdmwgPSAiV0FSTiIKICAgICAgICAgICAgZWxpZiAiRVJST1IiIGluIG1zZy51cHBl"
    "cigpOiBsdmwgPSAiRVJST1IiCiAgICAgICAgICAgIHNlbGYubG9nKG1zZywgbHZsKQoKICAgIGRl"
    "ZiBjbGVhcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Rpc3BsYXkuY2xlYXIoKQoKCiMg"
    "4pSA4pSAIExFU1NPTlMgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBMZXNzb25zVGFiKFFX"
    "aWRnZXQpOgogICAgIiIiCiAgICBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgYW5kIGNvZGUgbGVzc29u"
    "cyBicm93c2VyLgogICAgQWRkLCB2aWV3LCBzZWFyY2gsIGRlbGV0ZSBsZXNzb25zLgogICAgIiIi"
    "CgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGRiOiAiTGVzc29uc0xlYXJuZWREQiIsIHBhcmVudD1O"
    "b25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kYiA9"
    "IGRiCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAg"
    "ZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChz"
    "ZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAg"
    "cm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgRmlsdGVyIGJhcgogICAgICAgIGZpbHRlcl9y"
    "b3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fc2VhcmNoID0gUUxpbmVFZGl0KCkKICAg"
    "ICAgICBzZWxmLl9zZWFyY2guc2V0UGxhY2Vob2xkZXJUZXh0KCJTZWFyY2ggbGVzc29ucy4uLiIp"
    "CiAgICAgICAgc2VsZi5fbGFuZ19maWx0ZXIgPSBRQ29tYm9Cb3goKQogICAgICAgIHNlbGYuX2xh"
    "bmdfZmlsdGVyLmFkZEl0ZW1zKFsiQWxsIiwgIkxTTCIsICJQeXRob24iLCAiUHlTaWRlNiIsCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiSmF2YVNjcmlwdCIsICJPdGhlciJd"
    "KQogICAgICAgIHNlbGYuX3NlYXJjaC50ZXh0Q2hhbmdlZC5jb25uZWN0KHNlbGYucmVmcmVzaCkK"
    "ICAgICAgICBzZWxmLl9sYW5nX2ZpbHRlci5jdXJyZW50VGV4dENoYW5nZWQuY29ubmVjdChzZWxm"
    "LnJlZnJlc2gpCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJTZWFyY2g6Iikp"
    "CiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoc2VsZi5fc2VhcmNoLCAxKQogICAgICAgIGZp"
    "bHRlcl9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgiTGFuZ3VhZ2U6IikpCiAgICAgICAgZmlsdGVyX3Jv"
    "dy5hZGRXaWRnZXQoc2VsZi5fbGFuZ19maWx0ZXIpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoZmls"
    "dGVyX3JvdykKCiAgICAgICAgYnRuX2JhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fYWRk"
    "ID0gX2dvdGhpY19idG4oIuKcpiBBZGQgTGVzc29uIikKICAgICAgICBidG5fZGVsID0gX2dvdGhp"
    "Y19idG4oIuKclyBEZWxldGUiKQogICAgICAgIGJ0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "X2RvX2FkZCkKICAgICAgICBidG5fZGVsLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUp"
    "CiAgICAgICAgYnRuX2Jhci5hZGRXaWRnZXQoYnRuX2FkZCkKICAgICAgICBidG5fYmFyLmFkZFdp"
    "ZGdldChidG5fZGVsKQogICAgICAgIGJ0bl9iYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5h"
    "ZGRMYXlvdXQoYnRuX2JhcikKCiAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwg"
    "NCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKAogICAgICAg"
    "ICAgICBbIkxhbmd1YWdlIiwgIlJlZmVyZW5jZSBLZXkiLCAiU3VtbWFyeSIsICJFbnZpcm9ubWVu"
    "dCJdCiAgICAgICAgKQogICAgICAgIHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRT"
    "ZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAgMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5T"
    "dHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAg"
    "ICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAg"
    "ICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2Vs"
    "Zi5fdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2Vs"
    "Zi5fdGFibGUuaXRlbVNlbGVjdGlvbkNoYW5nZWQuY29ubmVjdChzZWxmLl9vbl9zZWxlY3QpCgog"
    "ICAgICAgICMgVXNlIHNwbGl0dGVyIGJldHdlZW4gdGFibGUgYW5kIGRldGFpbAogICAgICAgIHNw"
    "bGl0dGVyID0gUVNwbGl0dGVyKFF0Lk9yaWVudGF0aW9uLlZlcnRpY2FsKQogICAgICAgIHNwbGl0"
    "dGVyLmFkZFdpZGdldChzZWxmLl90YWJsZSkKCiAgICAgICAgIyBEZXRhaWwgcGFuZWwKICAgICAg"
    "ICBkZXRhaWxfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgZGV0YWlsX2xheW91dCA9IFFWQm94"
    "TGF5b3V0KGRldGFpbF93aWRnZXQpCiAgICAgICAgZGV0YWlsX2xheW91dC5zZXRDb250ZW50c01h"
    "cmdpbnMoMCwgNCwgMCwgMCkKICAgICAgICBkZXRhaWxfbGF5b3V0LnNldFNwYWNpbmcoMikKCiAg"
    "ICAgICAgZGV0YWlsX2hlYWRlciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBkZXRhaWxfaGVhZGVy"
    "LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBGVUxMIFJVTEUiKSkKICAgICAgICBkZXRhaWxf"
    "aGVhZGVyLmFkZFN0cmV0Y2goKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUgPSBfZ290aGlj"
    "X2J0bigiRWRpdCIpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRGaXhlZFdpZHRoKDUw"
    "KQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Q2hlY2thYmxlKFRydWUpCiAgICAgICAg"
    "c2VsZi5fYnRuX2VkaXRfcnVsZS50b2dnbGVkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2VkaXRfbW9k"
    "ZSkKICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlID0gX2dvdGhpY19idG4oIlNhdmUiKQogICAg"
    "ICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuc2V0Rml4ZWRXaWR0aCg1MCkKICAgICAgICBzZWxmLl9i"
    "dG5fc2F2ZV9ydWxlLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVs"
    "ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2F2ZV9ydWxlX2VkaXQpCiAgICAgICAgZGV0YWlsX2hl"
    "YWRlci5hZGRXaWRnZXQoc2VsZi5fYnRuX2VkaXRfcnVsZSkKICAgICAgICBkZXRhaWxfaGVhZGVy"
    "LmFkZFdpZGdldChzZWxmLl9idG5fc2F2ZV9ydWxlKQogICAgICAgIGRldGFpbF9sYXlvdXQuYWRk"
    "TGF5b3V0KGRldGFpbF9oZWFkZXIpCgogICAgICAgIHNlbGYuX2RldGFpbCA9IFFUZXh0RWRpdCgp"
    "CiAgICAgICAgc2VsZi5fZGV0YWlsLnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fZGV0"
    "YWlsLnNldE1pbmltdW1IZWlnaHQoMTIwKQogICAgICAgIHNlbGYuX2RldGFpbC5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsg"
    "IgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAg"
    "ICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDExcHg7IHBh"
    "ZGRpbmc6IDRweDsiCiAgICAgICAgKQogICAgICAgIGRldGFpbF9sYXlvdXQuYWRkV2lkZ2V0KHNl"
    "bGYuX2RldGFpbCkKICAgICAgICBzcGxpdHRlci5hZGRXaWRnZXQoZGV0YWlsX3dpZGdldCkKICAg"
    "ICAgICBzcGxpdHRlci5zZXRTaXplcyhbMzAwLCAxODBdKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0"
    "KHNwbGl0dGVyLCAxKQoKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAg"
    "ICAgICBzZWxmLl9lZGl0aW5nX3JvdzogaW50ID0gLTEKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHEgICAgPSBzZWxmLl9zZWFyY2gudGV4dCgpCiAgICAgICAgbGFuZyA9"
    "IHNlbGYuX2xhbmdfZmlsdGVyLmN1cnJlbnRUZXh0KCkKICAgICAgICBsYW5nID0gIiIgaWYgbGFu"
    "ZyA9PSAiQWxsIiBlbHNlIGxhbmcKICAgICAgICBzZWxmLl9yZWNvcmRzID0gc2VsZi5fZGIuc2Vh"
    "cmNoKHF1ZXJ5PXEsIGxhbmd1YWdlPWxhbmcpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291"
    "bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIHIgPSBz"
    "ZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLmluc2VydFJvdyhy"
    "KQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAgICAgICBR"
    "VGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoImxhbmd1YWdlIiwiIikpKQogICAgICAgICAgICBzZWxm"
    "Ll90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJl"
    "Yy5nZXQoInJlZmVyZW5jZV9rZXkiLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0"
    "ZW0ociwgMiwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgic3VtbWFy"
    "eSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAzLAogICAgICAgICAg"
    "ICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJlbnZpcm9ubWVudCIsIiIpKSkKCiAgICBk"
    "ZWYgX29uX3NlbGVjdChzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1"
    "cnJlbnRSb3coKQogICAgICAgIHNlbGYuX2VkaXRpbmdfcm93ID0gcm93CiAgICAgICAgaWYgMCA8"
    "PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJlYyA9IHNlbGYuX3JlY29y"
    "ZHNbcm93XQogICAgICAgICAgICBzZWxmLl9kZXRhaWwuc2V0UGxhaW5UZXh0KAogICAgICAgICAg"
    "ICAgICAgcmVjLmdldCgiZnVsbF9ydWxlIiwiIikgKyAiXG5cbiIgKwogICAgICAgICAgICAgICAg"
    "KCJSZXNvbHV0aW9uOiAiICsgcmVjLmdldCgicmVzb2x1dGlvbiIsIiIpIGlmIHJlYy5nZXQoInJl"
    "c29sdXRpb24iKSBlbHNlICIiKQogICAgICAgICAgICApCiAgICAgICAgICAgICMgUmVzZXQgZWRp"
    "dCBtb2RlIG9uIG5ldyBzZWxlY3Rpb24KICAgICAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5z"
    "ZXRDaGVja2VkKEZhbHNlKQoKICAgIGRlZiBfdG9nZ2xlX2VkaXRfbW9kZShzZWxmLCBlZGl0aW5n"
    "OiBib29sKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2RldGFpbC5zZXRSZWFkT25seShub3QgZWRp"
    "dGluZykKICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlLnNldFZpc2libGUoZWRpdGluZykKICAg"
    "ICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldFRleHQoIkNhbmNlbCIgaWYgZWRpdGluZyBlbHNl"
    "ICJFZGl0IikKICAgICAgICBpZiBlZGl0aW5nOgogICAgICAgICAgICBzZWxmLl9kZXRhaWwuc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6"
    "IHtDX0dPTER9OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0dPTERf"
    "RElNfTsgIgogICAgICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlm"
    "OyBmb250LXNpemU6IDExcHg7IHBhZGRpbmc6IDRweDsiCiAgICAgICAgICAgICkKICAgICAgICBl"
    "bHNlOgogICAgICAgICAgICBzZWxmLl9kZXRhaWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAg"
    "ICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgICAgIGYi"
    "Zm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5n"
    "OiA0cHg7IgogICAgICAgICAgICApCiAgICAgICAgICAgICMgUmVsb2FkIG9yaWdpbmFsIGNvbnRl"
    "bnQgb24gY2FuY2VsCiAgICAgICAgICAgIHNlbGYuX29uX3NlbGVjdCgpCgogICAgZGVmIF9zYXZl"
    "X3J1bGVfZWRpdChzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX2VkaXRpbmdfcm93"
    "CiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHRl"
    "eHQgPSBzZWxmLl9kZXRhaWwudG9QbGFpblRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgICMgU3Bs"
    "aXQgcmVzb2x1dGlvbiBiYWNrIG91dCBpZiBwcmVzZW50CiAgICAgICAgICAgIGlmICJcblxuUmVz"
    "b2x1dGlvbjogIiBpbiB0ZXh0OgogICAgICAgICAgICAgICAgcGFydHMgPSB0ZXh0LnNwbGl0KCJc"
    "blxuUmVzb2x1dGlvbjogIiwgMSkKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZSAgPSBwYXJ0c1sw"
    "XS5zdHJpcCgpCiAgICAgICAgICAgICAgICByZXNvbHV0aW9uID0gcGFydHNbMV0uc3RyaXAoKQog"
    "ICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgZnVsbF9ydWxlICA9IHRleHQKICAgICAg"
    "ICAgICAgICAgIHJlc29sdXRpb24gPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJyZXNvbHV0aW9u"
    "IiwgIiIpCiAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbcm93XVsiZnVsbF9ydWxlIl0gID0gZnVs"
    "bF9ydWxlCiAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbcm93XVsicmVzb2x1dGlvbiJdID0gcmVz"
    "b2x1dGlvbgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9kYi5fcGF0aCwgc2VsZi5fcmVj"
    "b3JkcykKICAgICAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRDaGVja2VkKEZhbHNlKQog"
    "ICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgi"
    "QWRkIExlc3NvbiIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19C"
    "RzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBkbGcucmVzaXplKDUwMCwgNDAwKQogICAg"
    "ICAgIGZvcm0gPSBRRm9ybUxheW91dChkbGcpCiAgICAgICAgZW52ICA9IFFMaW5lRWRpdCgiTFNM"
    "IikKICAgICAgICBsYW5nID0gUUxpbmVFZGl0KCJMU0wiKQogICAgICAgIHJlZiAgPSBRTGluZUVk"
    "aXQoKQogICAgICAgIHN1bW0gPSBRTGluZUVkaXQoKQogICAgICAgIHJ1bGUgPSBRVGV4dEVkaXQo"
    "KQogICAgICAgIHJ1bGUuc2V0TWF4aW11bUhlaWdodCgxMDApCiAgICAgICAgcmVzICA9IFFMaW5l"
    "RWRpdCgpCiAgICAgICAgbGluayA9IFFMaW5lRWRpdCgpCiAgICAgICAgZm9yIGxhYmVsLCB3IGlu"
    "IFsKICAgICAgICAgICAgKCJFbnZpcm9ubWVudDoiLCBlbnYpLCAoIkxhbmd1YWdlOiIsIGxhbmcp"
    "LAogICAgICAgICAgICAoIlJlZmVyZW5jZSBLZXk6IiwgcmVmKSwgKCJTdW1tYXJ5OiIsIHN1bW0p"
    "LAogICAgICAgICAgICAoIkZ1bGwgUnVsZToiLCBydWxlKSwgKCJSZXNvbHV0aW9uOiIsIHJlcyks"
    "CiAgICAgICAgICAgICgiTGluazoiLCBsaW5rKSwKICAgICAgICBdOgogICAgICAgICAgICBmb3Jt"
    "LmFkZFJvdyhsYWJlbCwgdykKICAgICAgICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9r"
    "ID0gX2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAg"
    "ICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcu"
    "cmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQoY3gpCiAg"
    "ICAgICAgZm9ybS5hZGRSb3coYnRucykKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cu"
    "RGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgc2VsZi5fZGIuYWRkKAogICAgICAgICAg"
    "ICAgICAgZW52aXJvbm1lbnQ9ZW52LnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgbGFu"
    "Z3VhZ2U9bGFuZy50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIHJlZmVyZW5jZV9rZXk9"
    "cmVmLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgc3VtbWFyeT1zdW1tLnRleHQoKS5z"
    "dHJpcCgpLAogICAgICAgICAgICAgICAgZnVsbF9ydWxlPXJ1bGUudG9QbGFpblRleHQoKS5zdHJp"
    "cCgpLAogICAgICAgICAgICAgICAgcmVzb2x1dGlvbj1yZXMudGV4dCgpLnN0cmlwKCksCiAgICAg"
    "ICAgICAgICAgICBsaW5rPWxpbmsudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93"
    "IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZWNfaWQgPSBzZWxmLl9yZWNvcmRz"
    "W3Jvd10uZ2V0KCJpZCIsIiIpCiAgICAgICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rp"
    "b24oCiAgICAgICAgICAgICAgICBzZWxmLCAiRGVsZXRlIExlc3NvbiIsCiAgICAgICAgICAgICAg"
    "ICAiRGVsZXRlIHRoaXMgbGVzc29uPyBDYW5ub3QgYmUgdW5kb25lLiIsCiAgICAgICAgICAgICAg"
    "ICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1"
    "dHRvbi5ObwogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94"
    "LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAgICAgIHNlbGYuX2RiLmRlbGV0ZShyZWNf"
    "aWQpCiAgICAgICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKCiMg4pSA4pSAIE1PRFVMRSBUUkFD"
    "S0VSIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKY2xhc3MgTW9kdWxlVHJhY2tlclRhYihRV2lkZ2V0KToKICAgICIiIgogICAgUGVyc29u"
    "YWwgbW9kdWxlIHBpcGVsaW5lIHRyYWNrZXIuCiAgICBUcmFjayBwbGFubmVkL2luLXByb2dyZXNz"
    "L2J1aWx0IG1vZHVsZXMgYXMgdGhleSBhcmUgZGVzaWduZWQuCiAgICBFYWNoIG1vZHVsZSBoYXM6"
    "IE5hbWUsIFN0YXR1cywgRGVzY3JpcHRpb24sIE5vdGVzLgogICAgRXhwb3J0IHRvIFRYVCBmb3Ig"
    "cGFzdGluZyBpbnRvIHNlc3Npb25zLgogICAgSW1wb3J0OiBwYXN0ZSBhIGZpbmFsaXplZCBzcGVj"
    "LCBpdCBwYXJzZXMgbmFtZSBhbmQgZGV0YWlscy4KICAgIFRoaXMgaXMgYSBkZXNpZ24gbm90ZWJv"
    "b2sg4oCUIG5vdCBjb25uZWN0ZWQgdG8gZGVja19idWlsZGVyJ3MgTU9EVUxFIHJlZ2lzdHJ5Lgog"
    "ICAgIiIiCgogICAgU1RBVFVTRVMgPSBbIklkZWEiLCAiRGVzaWduaW5nIiwgIlJlYWR5IHRvIEJ1"
    "aWxkIiwgIlBhcnRpYWwiLCAiQnVpbHQiXQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9"
    "Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGF0"
    "aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gIm1vZHVsZV90cmFja2VyLmpzb25sIgogICAgICAg"
    "IHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkK"
    "ICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRz"
    "TWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICAj"
    "IEJ1dHRvbiBiYXIKICAgICAgICBidG5fYmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYu"
    "X2J0bl9hZGQgICAgPSBfZ290aGljX2J0bigiQWRkIE1vZHVsZSIpCiAgICAgICAgc2VsZi5fYnRu"
    "X2VkaXQgICA9IF9nb3RoaWNfYnRuKCJFZGl0IikKICAgICAgICBzZWxmLl9idG5fZGVsZXRlID0g"
    "X2dvdGhpY19idG4oIkRlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydCA9IF9nb3RoaWNf"
    "YnRuKCJFeHBvcnQgVFhUIikKICAgICAgICBzZWxmLl9idG5faW1wb3J0ID0gX2dvdGhpY19idG4o"
    "IkltcG9ydCBTcGVjIikKICAgICAgICBmb3IgYiBpbiAoc2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRu"
    "X2VkaXQsIHNlbGYuX2J0bl9kZWxldGUsCiAgICAgICAgICAgICAgICAgIHNlbGYuX2J0bl9leHBv"
    "cnQsIHNlbGYuX2J0bl9pbXBvcnQpOgogICAgICAgICAgICBiLnNldE1pbmltdW1XaWR0aCg4MCkK"
    "ICAgICAgICAgICAgYi5zZXRNaW5pbXVtSGVpZ2h0KDI2KQogICAgICAgICAgICBidG5fYmFyLmFk"
    "ZFdpZGdldChiKQogICAgICAgIGJ0bl9iYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRM"
    "YXlvdXQoYnRuX2JhcikKCiAgICAgICAgc2VsZi5fYnRuX2FkZC5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fZG9fYWRkKQogICAgICAgIHNlbGYuX2J0bl9lZGl0LmNsaWNrZWQuY29ubmVjdChzZWxmLl9k"
    "b19lZGl0KQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Rv"
    "X2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fZXhwb3J0LmNsaWNrZWQuY29ubmVjdChzZWxmLl9k"
    "b19leHBvcnQpCiAgICAgICAgc2VsZi5fYnRuX2ltcG9ydC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "ZG9faW1wb3J0KQoKICAgICAgICAjIFRhYmxlCiAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVX"
    "aWRnZXQoMCwgMykKICAgICAgICBzZWxmLl90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxz"
    "KFsiTW9kdWxlIE5hbWUiLCAiU3RhdHVzIiwgIkRlc2NyaXB0aW9uIl0pCiAgICAgICAgaGggPSBz"
    "ZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXpl"
    "TW9kZSgwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxl"
    "LnNldENvbHVtbldpZHRoKDAsIDE2MCkKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgx"
    "LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENv"
    "bHVtbldpZHRoKDEsIDEwMCkKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVh"
    "ZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0"
    "aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2"
    "aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xv"
    "cnMoVHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVf"
    "c3R5bGUoKSkKICAgICAgICBzZWxmLl90YWJsZS5pdGVtU2VsZWN0aW9uQ2hhbmdlZC5jb25uZWN0"
    "KHNlbGYuX29uX3NlbGVjdCkKCiAgICAgICAgIyBTcGxpdHRlcgogICAgICAgIHNwbGl0dGVyID0g"
    "UVNwbGl0dGVyKFF0Lk9yaWVudGF0aW9uLlZlcnRpY2FsKQogICAgICAgIHNwbGl0dGVyLmFkZFdp"
    "ZGdldChzZWxmLl90YWJsZSkKCiAgICAgICAgIyBOb3RlcyBwYW5lbAogICAgICAgIG5vdGVzX3dp"
    "ZGdldCA9IFFXaWRnZXQoKQogICAgICAgIG5vdGVzX2xheW91dCA9IFFWQm94TGF5b3V0KG5vdGVz"
    "X3dpZGdldCkKICAgICAgICBub3Rlc19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDQsIDAs"
    "IDApCiAgICAgICAgbm90ZXNfbGF5b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBub3Rlc19sYXlv"
    "dXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIE5PVEVTIikpCiAgICAgICAgc2VsZi5fbm90"
    "ZXNfZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheS5zZXRS"
    "ZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0TWluaW11bUhlaWdo"
    "dCgxMjApCiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAg"
    "ICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJmb250LWZh"
    "bWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDExcHg7IHBhZGRpbmc6IDRweDsi"
    "CiAgICAgICAgKQogICAgICAgIG5vdGVzX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fbm90ZXNfZGlz"
    "cGxheSkKICAgICAgICBzcGxpdHRlci5hZGRXaWRnZXQobm90ZXNfd2lkZ2V0KQogICAgICAgIHNw"
    "bGl0dGVyLnNldFNpemVzKFsyNTAsIDE1MF0pCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc3BsaXR0"
    "ZXIsIDEpCgogICAgICAgICMgQ291bnQgbGFiZWwKICAgICAgICBzZWxmLl9jb3VudF9sYmwgPSBR"
    "TGFiZWwoIiIpCiAgICAgICAgc2VsZi5fY291bnRfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7"
    "REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxm"
    "Ll9jb3VudF9sYmwpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIHNlbGYuX3RhYmxlLnNl"
    "dFJvd0NvdW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAg"
    "ICByID0gc2VsZi5fdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNl"
    "cnRSb3cocikKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLCBRVGFibGVXaWRn"
    "ZXRJdGVtKHJlYy5nZXQoIm5hbWUiLCAiIikpKQogICAgICAgICAgICBzdGF0dXNfaXRlbSA9IFFU"
    "YWJsZVdpZGdldEl0ZW0ocmVjLmdldCgic3RhdHVzIiwgIklkZWEiKSkKICAgICAgICAgICAgIyBD"
    "b2xvciBieSBzdGF0dXMKICAgICAgICAgICAgc3RhdHVzX2NvbG9ycyA9IHsKICAgICAgICAgICAg"
    "ICAgICJJZGVhIjogICAgICAgICAgICAgQ19URVhUX0RJTSwKICAgICAgICAgICAgICAgICJEZXNp"
    "Z25pbmciOiAgICAgICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAgICAgICJSZWFkeSB0byBCdWls"
    "ZCI6ICAgQ19QVVJQTEUsCiAgICAgICAgICAgICAgICAiUGFydGlhbCI6ICAgICAgICAgICIjY2M4"
    "ODQ0IiwKICAgICAgICAgICAgICAgICJCdWlsdCI6ICAgICAgICAgICAgQ19HUkVFTiwKICAgICAg"
    "ICAgICAgfQogICAgICAgICAgICBzdGF0dXNfaXRlbS5zZXRGb3JlZ3JvdW5kKAogICAgICAgICAg"
    "ICAgICAgUUNvbG9yKHN0YXR1c19jb2xvcnMuZ2V0KHJlYy5nZXQoInN0YXR1cyIsIklkZWEiKSwg"
    "Q19URVhUX0RJTSkpCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRl"
    "bShyLCAxLCBzdGF0dXNfaXRlbSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAy"
    "LAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJkZXNjcmlwdGlvbiIs"
    "ICIiKVs6ODBdKSkKICAgICAgICBjb3VudHMgPSB7fQogICAgICAgIGZvciByZWMgaW4gc2VsZi5f"
    "cmVjb3JkczoKICAgICAgICAgICAgcyA9IHJlYy5nZXQoInN0YXR1cyIsICJJZGVhIikKICAgICAg"
    "ICAgICAgY291bnRzW3NdID0gY291bnRzLmdldChzLCAwKSArIDEKICAgICAgICBjb3VudF9zdHIg"
    "PSAiICAiLmpvaW4oZiJ7c306IHtufSIgZm9yIHMsIG4gaW4gY291bnRzLml0ZW1zKCkpCiAgICAg"
    "ICAgc2VsZi5fY291bnRfbGJsLnNldFRleHQoCiAgICAgICAgICAgIGYiVG90YWw6IHtsZW4oc2Vs"
    "Zi5fcmVjb3Jkcyl9ICAge2NvdW50X3N0cn0iCiAgICAgICAgKQoKICAgIGRlZiBfb25fc2VsZWN0"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAg"
    "ICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJlYyA9"
    "IHNlbGYuX3JlY29yZHNbcm93XQogICAgICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5LnNldFBs"
    "YWluVGV4dChyZWMuZ2V0KCJub3RlcyIsICIiKSkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHNlbGYuX29wZW5fZWRpdF9kaWFsb2coKQoKICAgIGRlZiBfZG9fZWRpdChz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAg"
    "ICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICBzZWxmLl9v"
    "cGVuX2VkaXRfZGlhbG9nKHNlbGYuX3JlY29yZHNbcm93XSwgcm93KQoKICAgIGRlZiBfb3Blbl9l"
    "ZGl0X2RpYWxvZyhzZWxmLCByZWM6IGRpY3QgPSBOb25lLCByb3c6IGludCA9IC0xKSAtPiBOb25l"
    "OgogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUo"
    "Ik1vZHVsZSIgaWYgbm90IHJlYyBlbHNlIGYiRWRpdDoge3JlYy5nZXQoJ25hbWUnLCcnKX0iKQog"
    "ICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtD"
    "X0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1NDAsIDQ0MCkKICAgICAgICBmb3JtID0gUVZC"
    "b3hMYXlvdXQoZGxnKQoKICAgICAgICBuYW1lX2ZpZWxkID0gUUxpbmVFZGl0KHJlYy5nZXQoIm5h"
    "bWUiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBuYW1lX2ZpZWxkLnNldFBsYWNlaG9sZGVy"
    "VGV4dCgiTW9kdWxlIG5hbWUiKQoKICAgICAgICBzdGF0dXNfY29tYm8gPSBRQ29tYm9Cb3goKQog"
    "ICAgICAgIHN0YXR1c19jb21iby5hZGRJdGVtcyhzZWxmLlNUQVRVU0VTKQogICAgICAgIGlmIHJl"
    "YzoKICAgICAgICAgICAgaWR4ID0gc3RhdHVzX2NvbWJvLmZpbmRUZXh0KHJlYy5nZXQoInN0YXR1"
    "cyIsIklkZWEiKSkKICAgICAgICAgICAgaWYgaWR4ID49IDA6CiAgICAgICAgICAgICAgICBzdGF0"
    "dXNfY29tYm8uc2V0Q3VycmVudEluZGV4KGlkeCkKCiAgICAgICAgZGVzY19maWVsZCA9IFFMaW5l"
    "RWRpdChyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIGRl"
    "c2NfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KCJPbmUtbGluZSBkZXNjcmlwdGlvbiIpCgogICAg"
    "ICAgIG5vdGVzX2ZpZWxkID0gUVRleHRFZGl0KCkKICAgICAgICBub3Rlc19maWVsZC5zZXRQbGFp"
    "blRleHQocmVjLmdldCgibm90ZXMiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBub3Rlc19m"
    "aWVsZC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgICJGdWxsIG5vdGVzIOKAlCBzcGVj"
    "LCBpZGVhcywgcmVxdWlyZW1lbnRzLCBlZGdlIGNhc2VzLi4uIgogICAgICAgICkKICAgICAgICBu"
    "b3Rlc19maWVsZC5zZXRNaW5pbXVtSGVpZ2h0KDIwMCkKCiAgICAgICAgZm9yIGxhYmVsLCB3aWRn"
    "ZXQgaW4gWwogICAgICAgICAgICAoIk5hbWU6IiwgbmFtZV9maWVsZCksCiAgICAgICAgICAgICgi"
    "U3RhdHVzOiIsIHN0YXR1c19jb21ibyksCiAgICAgICAgICAgICgiRGVzY3JpcHRpb246IiwgZGVz"
    "Y19maWVsZCksCiAgICAgICAgICAgICgiTm90ZXM6Iiwgbm90ZXNfZmllbGQpLAogICAgICAgIF06"
    "CiAgICAgICAgICAgIHJvd19sYXlvdXQgPSBRSEJveExheW91dCgpCiAgICAgICAgICAgIGxibCA9"
    "IFFMYWJlbChsYWJlbCkKICAgICAgICAgICAgbGJsLnNldEZpeGVkV2lkdGgoOTApCiAgICAgICAg"
    "ICAgIHJvd19sYXlvdXQuYWRkV2lkZ2V0KGxibCkKICAgICAgICAgICAgcm93X2xheW91dC5hZGRX"
    "aWRnZXQod2lkZ2V0KQogICAgICAgICAgICBmb3JtLmFkZExheW91dChyb3dfbGF5b3V0KQoKICAg"
    "ICAgICBidG5fcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9zYXZlICAgPSBfZ290aGlj"
    "X2J0bigiU2F2ZSIpCiAgICAgICAgYnRuX2NhbmNlbCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQog"
    "ICAgICAgIGJ0bl9zYXZlLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KQogICAgICAgIGJ0bl9j"
    "YW5jZWwuY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRn"
    "ZXQoYnRuX3NhdmUpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAg"
    "ICBmb3JtLmFkZExheW91dChidG5fcm93KQoKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFs"
    "b2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgbmV3X3JlYyA9IHsKICAgICAgICAg"
    "ICAgICAgICJpZCI6ICAgICAgICAgIHJlYy5nZXQoImlkIiwgc3RyKHV1aWQudXVpZDQoKSkpIGlm"
    "IHJlYyBlbHNlIHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAgICAgIm5hbWUiOiAgICAg"
    "ICAgbmFtZV9maWVsZC50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAg"
    "ICAgIHN0YXR1c19jb21iby5jdXJyZW50VGV4dCgpLAogICAgICAgICAgICAgICAgImRlc2NyaXB0"
    "aW9uIjogZGVzY19maWVsZC50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJub3RlcyI6"
    "ICAgICAgIG5vdGVzX2ZpZWxkLnRvUGxhaW5UZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAg"
    "ICJjcmVhdGVkIjogICAgIHJlYy5nZXQoImNyZWF0ZWQiLCBkYXRldGltZS5ub3coKS5pc29mb3Jt"
    "YXQoKSkgaWYgcmVjIGVsc2UgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAgICAgICAg"
    "ICAgICAibW9kaWZpZWQiOiAgICBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAgICAgICAg"
    "ICAgfQogICAgICAgICAgICBpZiByb3cgPj0gMDoKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29y"
    "ZHNbcm93XSA9IG5ld19yZWMKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYu"
    "X3JlY29yZHMuYXBwZW5kKG5ld19yZWMpCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3Bh"
    "dGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9k"
    "b19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50"
    "Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAg"
    "ICAgbmFtZSA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQoIm5hbWUiLCJ0aGlzIG1vZHVsZSIpCiAg"
    "ICAgICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgICAgICBz"
    "ZWxmLCAiRGVsZXRlIE1vZHVsZSIsCiAgICAgICAgICAgICAgICBmIkRlbGV0ZSAne25hbWV9Jz8g"
    "Q2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRC"
    "dXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLnBvcChyb3cpCiAgICAgICAgICAgICAgICB3cml0"
    "ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICAgICAgc2VsZi5y"
    "ZWZyZXNoKCkKCiAgICBkZWYgX2RvX2V4cG9ydChzZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgZXhwb3J0X2RpciA9IGNmZ19wYXRoKCJleHBvcnRzIikKICAgICAgICAgICAg"
    "ZXhwb3J0X2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAg"
    "IHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVZJW0lZF8lSCVNJVMiKQogICAgICAgICAg"
    "ICBvdXRfcGF0aCA9IGV4cG9ydF9kaXIgLyBmIm1vZHVsZXNfe3RzfS50eHQiCiAgICAgICAgICAg"
    "IGxpbmVzID0gWwogICAgICAgICAgICAgICAgIkVDSE8gREVDSyDigJQgTU9EVUxFIFRSQUNLRVIg"
    "RVhQT1JUIiwKICAgICAgICAgICAgICAgIGYiRXhwb3J0ZWQ6IHtkYXRldGltZS5ub3coKS5zdHJm"
    "dGltZSgnJVktJW0tJWQgJUg6JU06JVMnKX0iLAogICAgICAgICAgICAgICAgZiJUb3RhbCBtb2R1"
    "bGVzOiB7bGVuKHNlbGYuX3JlY29yZHMpfSIsCiAgICAgICAgICAgICAgICAiPSIgKiA2MCwKICAg"
    "ICAgICAgICAgICAgICIiLAogICAgICAgICAgICBdCiAgICAgICAgICAgIGZvciByZWMgaW4gc2Vs"
    "Zi5fcmVjb3JkczoKICAgICAgICAgICAgICAgIGxpbmVzLmV4dGVuZChbCiAgICAgICAgICAgICAg"
    "ICAgICAgZiJNT0RVTEU6IHtyZWMuZ2V0KCduYW1lJywnJyl9IiwKICAgICAgICAgICAgICAgICAg"
    "ICBmIlN0YXR1czoge3JlYy5nZXQoJ3N0YXR1cycsJycpfSIsCiAgICAgICAgICAgICAgICAgICAg"
    "ZiJEZXNjcmlwdGlvbjoge3JlYy5nZXQoJ2Rlc2NyaXB0aW9uJywnJyl9IiwKICAgICAgICAgICAg"
    "ICAgICAgICAiIiwKICAgICAgICAgICAgICAgICAgICAiTm90ZXM6IiwKICAgICAgICAgICAgICAg"
    "ICAgICByZWMuZ2V0KCJub3RlcyIsIiIpLAogICAgICAgICAgICAgICAgICAgICIiLAogICAgICAg"
    "ICAgICAgICAgICAgICItIiAqIDQwLAogICAgICAgICAgICAgICAgICAgICIiLAogICAgICAgICAg"
    "ICAgICAgXSkKICAgICAgICAgICAgb3V0X3BhdGgud3JpdGVfdGV4dCgiXG4iLmpvaW4obGluZXMp"
    "LCBlbmNvZGluZz0idXRmLTgiKQogICAgICAgICAgICBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCku"
    "c2V0VGV4dCgiXG4iLmpvaW4obGluZXMpKQogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1h"
    "dGlvbigKICAgICAgICAgICAgICAgIHNlbGYsICJFeHBvcnRlZCIsCiAgICAgICAgICAgICAgICBm"
    "Ik1vZHVsZSB0cmFja2VyIGV4cG9ydGVkIHRvOlxue291dF9wYXRofVxuXG5BbHNvIGNvcGllZCB0"
    "byBjbGlwYm9hcmQuIgogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBl"
    "OgogICAgICAgICAgICBRTWVzc2FnZUJveC53YXJuaW5nKHNlbGYsICJFeHBvcnQgRXJyb3IiLCBz"
    "dHIoZSkpCgogICAgZGVmIF9kb19pbXBvcnQoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJJbXBv"
    "cnQgYSBtb2R1bGUgc3BlYyBmcm9tIGNsaXBib2FyZCBvciB0eXBlZCB0ZXh0LiIiIgogICAgICAg"
    "IGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkltcG9ydCBN"
    "b2R1bGUgU3BlYyIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19C"
    "RzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBkbGcucmVzaXplKDUwMCwgMzQwKQogICAg"
    "ICAgIGxheW91dCA9IFFWQm94TGF5b3V0KGRsZykKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KFFM"
    "YWJlbCgKICAgICAgICAgICAgIlBhc3RlIGEgbW9kdWxlIHNwZWMgYmVsb3cuXG4iCiAgICAgICAg"
    "ICAgICJGaXJzdCBsaW5lIHdpbGwgYmUgdXNlZCBhcyB0aGUgbW9kdWxlIG5hbWUuIgogICAgICAg"
    "ICkpCiAgICAgICAgdGV4dF9maWVsZCA9IFFUZXh0RWRpdCgpCiAgICAgICAgdGV4dF9maWVsZC5z"
    "ZXRQbGFjZWhvbGRlclRleHQoIlBhc3RlIG1vZHVsZSBzcGVjIGhlcmUuLi4iKQogICAgICAgIGxh"
    "eW91dC5hZGRXaWRnZXQodGV4dF9maWVsZCwgMSkKICAgICAgICBidG5fcm93ID0gUUhCb3hMYXlv"
    "dXQoKQogICAgICAgIGJ0bl9vayAgICAgPSBfZ290aGljX2J0bigiSW1wb3J0IikKICAgICAgICBi"
    "dG5fY2FuY2VsID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgYnRuX29rLmNsaWNrZWQu"
    "Y29ubmVjdChkbGcuYWNjZXB0KQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KGRs"
    "Zy5yZWplY3QpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX29rKQogICAgICAgIGJ0bl9y"
    "b3cuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgbGF5b3V0LmFkZExheW91dChidG5fcm93"
    "KQoKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoK"
    "ICAgICAgICAgICAgcmF3ID0gdGV4dF9maWVsZC50b1BsYWluVGV4dCgpLnN0cmlwKCkKICAgICAg"
    "ICAgICAgaWYgbm90IHJhdzoKICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgICAgICBsaW5l"
    "cyA9IHJhdy5zcGxpdGxpbmVzKCkKICAgICAgICAgICAgIyBGaXJzdCBub24tZW1wdHkgbGluZSA9"
    "IG5hbWUKICAgICAgICAgICAgbmFtZSA9ICIiCiAgICAgICAgICAgIGZvciBsaW5lIGluIGxpbmVz"
    "OgogICAgICAgICAgICAgICAgaWYgbGluZS5zdHJpcCgpOgogICAgICAgICAgICAgICAgICAgIG5h"
    "bWUgPSBsaW5lLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBu"
    "ZXdfcmVjID0gewogICAgICAgICAgICAgICAgImlkIjogICAgICAgICAgc3RyKHV1aWQudXVpZDQo"
    "KSksCiAgICAgICAgICAgICAgICAibmFtZSI6ICAgICAgICBuYW1lWzo2MF0sCiAgICAgICAgICAg"
    "ICAgICAic3RhdHVzIjogICAgICAiSWRlYSIsCiAgICAgICAgICAgICAgICAiZGVzY3JpcHRpb24i"
    "OiAiIiwKICAgICAgICAgICAgICAgICJub3RlcyI6ICAgICAgIHJhdywKICAgICAgICAgICAgICAg"
    "ICJjcmVhdGVkIjogICAgIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICAg"
    "ICAgIm1vZGlmaWVkIjogICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAgICAgICAg"
    "IH0KICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQobmV3X3JlYykKICAgICAgICAgICAg"
    "d3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5y"
    "ZWZyZXNoKCkKCgojIOKUgOKUgCBQQVNTIDUgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQWxsIHRhYiBj"
    "b250ZW50IGNsYXNzZXMgZGVmaW5lZC4KIyBTTFNjYW5zVGFiOiByZWJ1aWx0IOKAlCBEZWxldGUg"
    "YWRkZWQsIE1vZGlmeSBmaXhlZCwgdGltZXN0YW1wIHBhcnNlciBmaXhlZCwKIyAgICAgICAgICAg"
    "ICBjYXJkL2dyaW1vaXJlIHN0eWxlLCBjb3B5LXRvLWNsaXBib2FyZCBjb250ZXh0IG1lbnUuCiMg"
    "U0xDb21tYW5kc1RhYjogZ290aGljIHRhYmxlLCDip4kgQ29weSBDb21tYW5kIGJ1dHRvbi4KIyBK"
    "b2JUcmFja2VyVGFiOiBmdWxsIHJlYnVpbGQg4oCUIG11bHRpLXNlbGVjdCwgYXJjaGl2ZS9yZXN0"
    "b3JlLCBDU1YvVFNWIGV4cG9ydC4KIyBTZWxmVGFiOiBpbm5lciBzYW5jdHVtIGZvciBpZGxlIG5h"
    "cnJhdGl2ZSBhbmQgcmVmbGVjdGlvbiBvdXRwdXQuCiMgRGlhZ25vc3RpY3NUYWI6IHN0cnVjdHVy"
    "ZWQgbG9nIHdpdGggbGV2ZWwtY29sb3JlZCBvdXRwdXQuCiMgTGVzc29uc1RhYjogTFNMIEZvcmJp"
    "ZGRlbiBSdWxlc2V0IGJyb3dzZXIgd2l0aCBhZGQvZGVsZXRlL3NlYXJjaC4KIwojIE5leHQ6IFBh"
    "c3MgNiDigJQgTWFpbiBXaW5kb3cKIyAoTW9yZ2FubmFEZWNrIGNsYXNzLCBmdWxsIGxheW91dCwg"
    "QVBTY2hlZHVsZXIsIGZpcnN0LXJ1biBmbG93LAojICBkZXBlbmRlbmN5IGJvb3RzdHJhcCwgc2hv"
    "cnRjdXQgY3JlYXRpb24sIHN0YXJ0dXAgc2VxdWVuY2UpCgoKIyDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5O"
    "QSBERUNLIOKAlCBQQVNTIDY6IE1BSU4gV0lORE9XICYgRU5UUlkgUE9JTlQKIwojIENvbnRhaW5z"
    "OgojICAgYm9vdHN0cmFwX2NoZWNrKCkgICAgIOKAlCBkZXBlbmRlbmN5IHZhbGlkYXRpb24gKyBh"
    "dXRvLWluc3RhbGwgYmVmb3JlIFVJCiMgICBGaXJzdFJ1bkRpYWxvZyAgICAgICAg4oCUIG1vZGVs"
    "IHBhdGggKyBjb25uZWN0aW9uIHR5cGUgc2VsZWN0aW9uCiMgICBKb3VybmFsU2lkZWJhciAgICAg"
    "ICAg4oCUIGNvbGxhcHNpYmxlIGxlZnQgc2lkZWJhciAoc2Vzc2lvbiBicm93c2VyICsgam91cm5h"
    "bCkKIyAgIFRvcnBvclBhbmVsICAgICAgICAgICDigJQgQVdBS0UgLyBBVVRPIC8gU1VTUEVORCBz"
    "dGF0ZSB0b2dnbGUKIyAgIE1vcmdhbm5hRGVjayAgICAgICAgICDigJQgbWFpbiB3aW5kb3csIGZ1"
    "bGwgbGF5b3V0LCBhbGwgc2lnbmFsIGNvbm5lY3Rpb25zCiMgICBtYWluKCkgICAgICAgICAgICAg"
    "ICAg4oCUIGVudHJ5IHBvaW50IHdpdGggYm9vdHN0cmFwIHNlcXVlbmNlCiMg4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgpp"
    "bXBvcnQgc3VicHJvY2VzcwoKCiMg4pSA4pSAIFBSRS1MQVVOQ0ggREVQRU5ERU5DWSBCT09UU1RS"
    "QVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACmRlZiBib290c3RyYXBfY2hlY2soKSAtPiBOb25lOgogICAgIiIiCiAg"
    "ICBSdW5zIEJFRk9SRSBRQXBwbGljYXRpb24gaXMgY3JlYXRlZC4KICAgIENoZWNrcyBmb3IgUHlT"
    "aWRlNiBzZXBhcmF0ZWx5IChjYW4ndCBzaG93IEdVSSB3aXRob3V0IGl0KS4KICAgIEF1dG8taW5z"
    "dGFsbHMgYWxsIG90aGVyIG1pc3Npbmcgbm9uLWNyaXRpY2FsIGRlcHMgdmlhIHBpcC4KICAgIFZh"
    "bGlkYXRlcyBpbnN0YWxscyBzdWNjZWVkZWQuCiAgICBXcml0ZXMgcmVzdWx0cyB0byBhIGJvb3Rz"
    "dHJhcCBsb2cgZm9yIERpYWdub3N0aWNzIHRhYiB0byBwaWNrIHVwLgogICAgIiIiCiAgICAjIOKU"
    "gOKUgCBTdGVwIDE6IENoZWNrIFB5U2lkZTYgKGNhbid0IGF1dG8taW5zdGFsbCB3aXRob3V0IGl0"
    "IGFscmVhZHkgcHJlc2VudCkg4pSACiAgICB0cnk6CiAgICAgICAgaW1wb3J0IFB5U2lkZTYgICMg"
    "bm9xYQogICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICMgTm8gR1VJIGF2YWlsYWJsZSDi"
    "gJQgdXNlIFdpbmRvd3MgbmF0aXZlIGRpYWxvZyB2aWEgY3R5cGVzCiAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICBpbXBvcnQgY3R5cGVzCiAgICAgICAgICAgIGN0eXBlcy53aW5kbGwudXNlcjMyLk1l"
    "c3NhZ2VCb3hXKAogICAgICAgICAgICAgICAgMCwKICAgICAgICAgICAgICAgICJQeVNpZGU2IGlz"
    "IHJlcXVpcmVkIGJ1dCBub3QgaW5zdGFsbGVkLlxuXG4iCiAgICAgICAgICAgICAgICAiT3BlbiBh"
    "IHRlcm1pbmFsIGFuZCBydW46XG5cbiIKICAgICAgICAgICAgICAgICIgICAgcGlwIGluc3RhbGwg"
    "UHlTaWRlNlxuXG4iCiAgICAgICAgICAgICAgICBmIlRoZW4gcmVzdGFydCB7REVDS19OQU1FfS4i"
    "LAogICAgICAgICAgICAgICAgZiJ7REVDS19OQU1FfSDigJQgTWlzc2luZyBEZXBlbmRlbmN5IiwK"
    "ICAgICAgICAgICAgICAgIDB4MTAgICMgTUJfSUNPTkVSUk9SCiAgICAgICAgICAgICkKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwcmludCgiQ1JJVElDQUw6IFB5U2lkZTYg"
    "bm90IGluc3RhbGxlZC4gUnVuOiBwaXAgaW5zdGFsbCBQeVNpZGU2IikKICAgICAgICBzeXMuZXhp"
    "dCgxKQoKICAgICMg4pSA4pSAIFN0ZXAgMjogQXV0by1pbnN0YWxsIG90aGVyIG1pc3NpbmcgZGVw"
    "cyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIF9BVVRPX0lOU1RB"
    "TEwgPSBbCiAgICAgICAgKCJhcHNjaGVkdWxlciIsICAgICAgICAgICAgICAgImFwc2NoZWR1bGVy"
    "IiksCiAgICAgICAgKCJsb2d1cnUiLCAgICAgICAgICAgICAgICAgICAgImxvZ3VydSIpLAogICAg"
    "ICAgICgicHlnYW1lIiwgICAgICAgICAgICAgICAgICAgICJweWdhbWUiKSwKICAgICAgICAoInB5"
    "d2luMzIiLCAgICAgICAgICAgICAgICAgICAicHl3aW4zMiIpLAogICAgICAgICgicHN1dGlsIiwg"
    "ICAgICAgICAgICAgICAgICAgICJwc3V0aWwiKSwKICAgICAgICAoInJlcXVlc3RzIiwgICAgICAg"
    "ICAgICAgICAgICAicmVxdWVzdHMiKSwKICAgICAgICAoImdvb2dsZS1hcGktcHl0aG9uLWNsaWVu"
    "dCIsICAiZ29vZ2xlYXBpY2xpZW50IiksCiAgICAgICAgKCJnb29nbGUtYXV0aC1vYXV0aGxpYiIs"
    "ICAgICAgImdvb2dsZV9hdXRoX29hdXRobGliIiksCiAgICAgICAgKCJnb29nbGUtYXV0aCIsICAg"
    "ICAgICAgICAgICAgImdvb2dsZS5hdXRoIiksCiAgICBdCgogICAgaW1wb3J0IGltcG9ydGxpYgog"
    "ICAgYm9vdHN0cmFwX2xvZyA9IFtdCgogICAgZm9yIHBpcF9uYW1lLCBpbXBvcnRfbmFtZSBpbiBf"
    "QVVUT19JTlNUQUxMOgogICAgICAgIHRyeToKICAgICAgICAgICAgaW1wb3J0bGliLmltcG9ydF9t"
    "b2R1bGUoaW1wb3J0X25hbWUpCiAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKGYiW0JP"
    "T1RTVFJBUF0ge3BpcF9uYW1lfSDinJMiKQogICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAg"
    "ICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICBmIltCT09UU1RS"
    "QVBdIHtwaXBfbmFtZX0gbWlzc2luZyDigJQgaW5zdGFsbGluZy4uLiIKICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICByZXN1bHQgPSBzdWJwcm9jZXNzLnJ1bigK"
    "ICAgICAgICAgICAgICAgICAgICBbc3lzLmV4ZWN1dGFibGUsICItbSIsICJwaXAiLCAiaW5zdGFs"
    "bCIsCiAgICAgICAgICAgICAgICAgICAgIHBpcF9uYW1lLCAiLS1xdWlldCIsICItLW5vLXdhcm4t"
    "c2NyaXB0LWxvY2F0aW9uIl0sCiAgICAgICAgICAgICAgICAgICAgY2FwdHVyZV9vdXRwdXQ9VHJ1"
    "ZSwgdGV4dD1UcnVlLCB0aW1lb3V0PTEyMAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAg"
    "ICAgaWYgcmVzdWx0LnJldHVybmNvZGUgPT0gMDoKICAgICAgICAgICAgICAgICAgICAjIFZhbGlk"
    "YXRlIGl0IGFjdHVhbGx5IGltcG9ydGVkIG5vdwogICAgICAgICAgICAgICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgaW1wb3J0bGliLmltcG9ydF9tb2R1bGUoaW1wb3J0X25hbWUp"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3RhbGxlZCDinJMi"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICBleGNlcHQgSW1w"
    "b3J0RXJyb3I6CiAgICAgICAgICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3Rh"
    "bGwgYXBwZWFyZWQgdG8gIgogICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJzdWNjZWVkIGJ1"
    "dCBpbXBvcnQgc3RpbGwgZmFpbHMg4oCUIHJlc3RhcnQgbWF5ICIKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGYiYmUgcmVxdWlyZWQuIgogICAgICAgICAgICAgICAgICAgICAgICApCiAgICAg"
    "ICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5k"
    "KAogICAgICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFs"
    "bCBmYWlsZWQ6ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJ7cmVzdWx0LnN0ZGVycls6MjAw"
    "XX0iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgc3VicHJvY2Vzcy5U"
    "aW1lb3V0RXhwaXJlZDoKICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAg"
    "ICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsIHRpbWVkIG91"
    "dC4iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToK"
    "ICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgICAg"
    "IGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsIGVycm9yOiB7ZX0iCiAgICAgICAgICAg"
    "ICAgICApCgogICAgIyDilIDilIAgU3RlcCAzOiBXcml0ZSBib290c3RyYXAgbG9nIGZvciBEaWFn"
    "bm9zdGljcyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICB0cnk6CiAgICAgICAgbG9nX3BhdGggPSBTQ1JJ"
    "UFRfRElSIC8gImxvZ3MiIC8gImJvb3RzdHJhcF9sb2cudHh0IgogICAgICAgIHdpdGggbG9nX3Bh"
    "dGgub3BlbigidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgIGYud3JpdGUo"
    "IlxuIi5qb2luKGJvb3RzdHJhcF9sb2cpKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICBw"
    "YXNzCgoKIyDilIDilIAgRklSU1QgUlVOIERJQUxPRyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgRmlyc3RSdW5EaWFsb2co"
    "UURpYWxvZyk6CiAgICAiIiIKICAgIFNob3duIG9uIGZpcnN0IGxhdW5jaCB3aGVuIGNvbmZpZy5q"
    "c29uIGRvZXNuJ3QgZXhpc3QuCiAgICBDb2xsZWN0cyBtb2RlbCBjb25uZWN0aW9uIHR5cGUgYW5k"
    "IHBhdGgva2V5LgogICAgVmFsaWRhdGVzIGNvbm5lY3Rpb24gYmVmb3JlIGFjY2VwdGluZy4KICAg"
    "IFdyaXRlcyBjb25maWcuanNvbiBvbiBzdWNjZXNzLgogICAgQ3JlYXRlcyBkZXNrdG9wIHNob3J0"
    "Y3V0LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAg"
    "ICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLnNldFdpbmRvd1RpdGxlKGYi"
    "4pymIHtERUNLX05BTUUudXBwZXIoKX0g4oCUIEZJUlNUIEFXQUtFTklORyIpCiAgICAgICAgc2Vs"
    "Zi5zZXRTdHlsZVNoZWV0KFNUWUxFKQogICAgICAgIHNlbGYuc2V0Rml4ZWRTaXplKDUyMCwgNDAw"
    "KQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRTcGFj"
    "aW5nKDEwKQoKICAgICAgICB0aXRsZSA9IFFMYWJlbChmIuKcpiB7REVDS19OQU1FLnVwcGVyKCl9"
    "IOKAlCBGSVJTVCBBV0FLRU5JTkcg4pymIikKICAgICAgICB0aXRsZS5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICBmImNvbG9yOiB7Q19DUklNU09OfTsgZm9udC1zaXplOiAxNHB4OyBmb250LXdl"
    "aWdodDogYm9sZDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2Vy"
    "aWY7IGxldHRlci1zcGFjaW5nOiAycHg7IgogICAgICAgICkKICAgICAgICB0aXRsZS5zZXRBbGln"
    "bm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICByb290LmFkZFdpZGdl"
    "dCh0aXRsZSkKCiAgICAgICAgc3ViID0gUUxhYmVsKAogICAgICAgICAgICBmIkNvbmZpZ3VyZSB0"
    "aGUgdmVzc2VsIGJlZm9yZSB7REVDS19OQU1FfSBtYXkgYXdha2VuLlxuIgogICAgICAgICAgICAi"
    "QWxsIHNldHRpbmdzIGFyZSBzdG9yZWQgbG9jYWxseS4gTm90aGluZyBsZWF2ZXMgdGhpcyBtYWNo"
    "aW5lLiIKICAgICAgICApCiAgICAgICAgc3ViLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "Y29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgICAgIGYiZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHN1Yi5zZXRB"
    "bGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICByb290LmFkZFdp"
    "ZGdldChzdWIpCgogICAgICAgICMg4pSA4pSAIENvbm5lY3Rpb24gdHlwZSDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgICAgICByb290LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBBSSBDT05ORUNU"
    "SU9OIFRZUEUiKSkKICAgICAgICBzZWxmLl90eXBlX2NvbWJvID0gUUNvbWJvQm94KCkKICAgICAg"
    "ICBzZWxmLl90eXBlX2NvbWJvLmFkZEl0ZW1zKFsKICAgICAgICAgICAgIkxvY2FsIG1vZGVsIGZv"
    "bGRlciAodHJhbnNmb3JtZXJzKSIsCiAgICAgICAgICAgICJPbGxhbWEgKGxvY2FsIHNlcnZpY2Up"
    "IiwKICAgICAgICAgICAgIkNsYXVkZSBBUEkgKEFudGhyb3BpYykiLAogICAgICAgICAgICAiT3Bl"
    "bkFJIEFQSSIsCiAgICAgICAgXSkKICAgICAgICBzZWxmLl90eXBlX2NvbWJvLmN1cnJlbnRJbmRl"
    "eENoYW5nZWQuY29ubmVjdChzZWxmLl9vbl90eXBlX2NoYW5nZSkKICAgICAgICByb290LmFkZFdp"
    "ZGdldChzZWxmLl90eXBlX2NvbWJvKQoKICAgICAgICAjIOKUgOKUgCBEeW5hbWljIGNvbm5lY3Rp"
    "b24gZmllbGRzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgICAgIHNlbGYuX3N0YWNrID0gUVN0YWNrZWRXaWRnZXQoKQoKICAgICAgICAjIFBhZ2UgMDog"
    "TG9jYWwgcGF0aAogICAgICAgIHAwID0gUVdpZGdldCgpCiAgICAgICAgbDAgPSBRSEJveExheW91"
    "dChwMCkKICAgICAgICBsMC5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAsMCkKICAgICAgICBzZWxm"
    "Ll9sb2NhbF9wYXRoID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9sb2NhbF9wYXRoLnNldFBs"
    "YWNlaG9sZGVyVGV4dCgKICAgICAgICAgICAgciJEOlxBSVxNb2RlbHNcZG9scGhpbi04YiIKICAg"
    "ICAgICApCiAgICAgICAgYnRuX2Jyb3dzZSA9IF9nb3RoaWNfYnRuKCJCcm93c2UiKQogICAgICAg"
    "IGJ0bl9icm93c2UuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Jyb3dzZV9tb2RlbCkKICAgICAgICBs"
    "MC5hZGRXaWRnZXQoc2VsZi5fbG9jYWxfcGF0aCk7IGwwLmFkZFdpZGdldChidG5fYnJvd3NlKQog"
    "ICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMCkKCiAgICAgICAgIyBQYWdlIDE6IE9sbGFt"
    "YSBtb2RlbCBuYW1lCiAgICAgICAgcDEgPSBRV2lkZ2V0KCkKICAgICAgICBsMSA9IFFIQm94TGF5"
    "b3V0KHAxKQogICAgICAgIGwxLnNldENvbnRlbnRzTWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNl"
    "bGYuX29sbGFtYV9tb2RlbCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fb2xsYW1hX21vZGVs"
    "LnNldFBsYWNlaG9sZGVyVGV4dCgiZG9scGhpbi0yLjYtN2IiKQogICAgICAgIGwxLmFkZFdpZGdl"
    "dChzZWxmLl9vbGxhbWFfbW9kZWwpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAxKQoK"
    "ICAgICAgICAjIFBhZ2UgMjogQ2xhdWRlIEFQSSBrZXkKICAgICAgICBwMiA9IFFXaWRnZXQoKQog"
    "ICAgICAgIGwyID0gUVZCb3hMYXlvdXQocDIpCiAgICAgICAgbDIuc2V0Q29udGVudHNNYXJnaW5z"
    "KDAsMCwwLDApCiAgICAgICAgc2VsZi5fY2xhdWRlX2tleSAgID0gUUxpbmVFZGl0KCkKICAgICAg"
    "ICBzZWxmLl9jbGF1ZGVfa2V5LnNldFBsYWNlaG9sZGVyVGV4dCgic2stYW50LS4uLiIpCiAgICAg"
    "ICAgc2VsZi5fY2xhdWRlX2tleS5zZXRFY2hvTW9kZShRTGluZUVkaXQuRWNob01vZGUuUGFzc3dv"
    "cmQpCiAgICAgICAgc2VsZi5fY2xhdWRlX21vZGVsID0gUUxpbmVFZGl0KCJjbGF1ZGUtc29ubmV0"
    "LTQtNiIpCiAgICAgICAgbDIuYWRkV2lkZ2V0KFFMYWJlbCgiQVBJIEtleToiKSkKICAgICAgICBs"
    "Mi5hZGRXaWRnZXQoc2VsZi5fY2xhdWRlX2tleSkKICAgICAgICBsMi5hZGRXaWRnZXQoUUxhYmVs"
    "KCJNb2RlbDoiKSkKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fY2xhdWRlX21vZGVsKQogICAg"
    "ICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMikKCiAgICAgICAgIyBQYWdlIDM6IE9wZW5BSQog"
    "ICAgICAgIHAzID0gUVdpZGdldCgpCiAgICAgICAgbDMgPSBRVkJveExheW91dChwMykKICAgICAg"
    "ICBsMy5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAsMCkKICAgICAgICBzZWxmLl9vYWlfa2V5ICAg"
    "PSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX29haV9rZXkuc2V0UGxhY2Vob2xkZXJUZXh0KCJz"
    "ay0uLi4iKQogICAgICAgIHNlbGYuX29haV9rZXkuc2V0RWNob01vZGUoUUxpbmVFZGl0LkVjaG9N"
    "b2RlLlBhc3N3b3JkKQogICAgICAgIHNlbGYuX29haV9tb2RlbCA9IFFMaW5lRWRpdCgiZ3B0LTRv"
    "IikKICAgICAgICBsMy5hZGRXaWRnZXQoUUxhYmVsKCJBUEkgS2V5OiIpKQogICAgICAgIGwzLmFk"
    "ZFdpZGdldChzZWxmLl9vYWlfa2V5KQogICAgICAgIGwzLmFkZFdpZGdldChRTGFiZWwoIk1vZGVs"
    "OiIpKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9vYWlfbW9kZWwpCiAgICAgICAgc2VsZi5f"
    "c3RhY2suYWRkV2lkZ2V0KHAzKQoKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9zdGFjaykK"
    "CiAgICAgICAgIyDilIDilIAgVGVzdCArIHN0YXR1cyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICAgICB0ZXN0X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fdGVzdCA9"
    "IF9nb3RoaWNfYnRuKCJUZXN0IENvbm5lY3Rpb24iKQogICAgICAgIHNlbGYuX2J0bl90ZXN0LmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl90ZXN0X2Nvbm5lY3Rpb24pCiAgICAgICAgc2VsZi5fc3RhdHVz"
    "X2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyAiCiAg"
    "ICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQog"
    "ICAgICAgIHRlc3Rfcm93LmFkZFdpZGdldChzZWxmLl9idG5fdGVzdCkKICAgICAgICB0ZXN0X3Jv"
    "dy5hZGRXaWRnZXQoc2VsZi5fc3RhdHVzX2xibCwgMSkKICAgICAgICByb290LmFkZExheW91dCh0"
    "ZXN0X3JvdykKCiAgICAgICAgIyDilIDilIAgRmFjZSBQYWNrIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHJvb3QuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2n"
    "IEZBQ0UgUEFDSyAob3B0aW9uYWwg4oCUIFpJUCBmaWxlKSIpKQogICAgICAgIGZhY2Vfcm93ID0g"
    "UUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2ZhY2VfcGF0aCA9IFFMaW5lRWRpdCgpCiAgICAg"
    "ICAgc2VsZi5fZmFjZV9wYXRoLnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAgICAgZiJCcm93"
    "c2UgdG8ge0RFQ0tfTkFNRX0gZmFjZSBwYWNrIFpJUCAob3B0aW9uYWwsIGNhbiBhZGQgbGF0ZXIp"
    "IgogICAgICAgICkKICAgICAgICBzZWxmLl9mYWNlX3BhdGguc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAg"
    "ICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4"
    "OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1z"
    "aXplOiAxMnB4OyBwYWRkaW5nOiA2cHggMTBweDsiCiAgICAgICAgKQogICAgICAgIGJ0bl9mYWNl"
    "ID0gX2dvdGhpY19idG4oIkJyb3dzZSIpCiAgICAgICAgYnRuX2ZhY2UuY2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuX2Jyb3dzZV9mYWNlKQogICAgICAgIGZhY2Vfcm93LmFkZFdpZGdldChzZWxmLl9mYWNl"
    "X3BhdGgpCiAgICAgICAgZmFjZV9yb3cuYWRkV2lkZ2V0KGJ0bl9mYWNlKQogICAgICAgIHJvb3Qu"
    "YWRkTGF5b3V0KGZhY2Vfcm93KQoKICAgICAgICAjIOKUgOKUgCBTaG9ydGN1dCBvcHRpb24g4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc2hvcnRjdXRfY2IgPSBRQ2hlY2tCb3goCiAg"
    "ICAgICAgICAgICJDcmVhdGUgZGVza3RvcCBzaG9ydGN1dCAocmVjb21tZW5kZWQpIgogICAgICAg"
    "ICkKICAgICAgICBzZWxmLl9zaG9ydGN1dF9jYi5zZXRDaGVja2VkKFRydWUpCiAgICAgICAgcm9v"
    "dC5hZGRXaWRnZXQoc2VsZi5fc2hvcnRjdXRfY2IpCgogICAgICAgICMg4pSA4pSAIEJ1dHRvbnMg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5h"
    "ZGRTdHJldGNoKCkKICAgICAgICBidG5fcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYu"
    "X2J0bl9hd2FrZW4gPSBfZ290aGljX2J0bigi4pymIEJFR0lOIEFXQUtFTklORyIpCiAgICAgICAg"
    "c2VsZi5fYnRuX2F3YWtlbi5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIGJ0bl9jYW5jZWwgPSBf"
    "Z290aGljX2J0bigi4pyXIENhbmNlbCIpCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbi5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5hY2NlcHQpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5yZWplY3QpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX2F3YWtlbikK"
    "ICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2FuY2VsKQogICAgICAgIHJvb3QuYWRkTGF5"
    "b3V0KGJ0bl9yb3cpCgogICAgZGVmIF9vbl90eXBlX2NoYW5nZShzZWxmLCBpZHg6IGludCkgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoaWR4KQogICAgICAgIHNl"
    "bGYuX2J0bl9hd2FrZW4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9zdGF0dXNfbGJs"
    "LnNldFRleHQoIiIpCgogICAgZGVmIF9icm93c2VfbW9kZWwoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBwYXRoID0gUUZpbGVEaWFsb2cuZ2V0RXhpc3RpbmdEaXJlY3RvcnkoCiAgICAgICAgICAgIHNl"
    "bGYsICJTZWxlY3QgTW9kZWwgRm9sZGVyIiwKICAgICAgICAgICAgciJEOlxBSVxNb2RlbHMiCiAg"
    "ICAgICAgKQogICAgICAgIGlmIHBhdGg6CiAgICAgICAgICAgIHNlbGYuX2xvY2FsX3BhdGguc2V0"
    "VGV4dChwYXRoKQoKICAgIGRlZiBfYnJvd3NlX2ZhY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBw"
    "YXRoLCBfID0gUUZpbGVEaWFsb2cuZ2V0T3BlbkZpbGVOYW1lKAogICAgICAgICAgICBzZWxmLCAi"
    "U2VsZWN0IEZhY2UgUGFjayBaSVAiLAogICAgICAgICAgICBzdHIoUGF0aC5ob21lKCkgLyAiRGVz"
    "a3RvcCIpLAogICAgICAgICAgICAiWklQIEZpbGVzICgqLnppcCkiCiAgICAgICAgKQogICAgICAg"
    "IGlmIHBhdGg6CiAgICAgICAgICAgIHNlbGYuX2ZhY2VfcGF0aC5zZXRUZXh0KHBhdGgpCgogICAg"
    "QHByb3BlcnR5CiAgICBkZWYgZmFjZV96aXBfcGF0aChzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0"
    "dXJuIHNlbGYuX2ZhY2VfcGF0aC50ZXh0KCkuc3RyaXAoKQoKICAgIGRlZiBfdGVzdF9jb25uZWN0"
    "aW9uKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRUZXh0KCJUZXN0"
    "aW5nLi4uIikKICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseTog"
    "e0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgUUFwcGxpY2F0aW9uLnByb2Nl"
    "c3NFdmVudHMoKQoKICAgICAgICBpZHggPSBzZWxmLl90eXBlX2NvbWJvLmN1cnJlbnRJbmRleCgp"
    "CiAgICAgICAgb2sgID0gRmFsc2UKICAgICAgICBtc2cgPSAiIgoKICAgICAgICBpZiBpZHggPT0g"
    "MDogICMgTG9jYWwKICAgICAgICAgICAgcGF0aCA9IHNlbGYuX2xvY2FsX3BhdGgudGV4dCgpLnN0"
    "cmlwKCkKICAgICAgICAgICAgaWYgcGF0aCBhbmQgUGF0aChwYXRoKS5leGlzdHMoKToKICAgICAg"
    "ICAgICAgICAgIG9rICA9IFRydWUKICAgICAgICAgICAgICAgIG1zZyA9IGYiRm9sZGVyIGZvdW5k"
    "LiBNb2RlbCB3aWxsIGxvYWQgb24gc3RhcnR1cC4iCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAg"
    "ICAgICAgICBtc2cgPSAiRm9sZGVyIG5vdCBmb3VuZC4gQ2hlY2sgdGhlIHBhdGguIgoKICAgICAg"
    "ICBlbGlmIGlkeCA9PSAxOiAgIyBPbGxhbWEKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAg"
    "ICAgcmVxICA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QoCiAgICAgICAgICAgICAgICAgICAgImh0"
    "dHA6Ly9sb2NhbGhvc3Q6MTE0MzQvYXBpL3RhZ3MiCiAgICAgICAgICAgICAgICApCiAgICAgICAg"
    "ICAgICAgICByZXNwID0gdXJsbGliLnJlcXVlc3QudXJsb3BlbihyZXEsIHRpbWVvdXQ9MykKICAg"
    "ICAgICAgICAgICAgIG9rICAgPSByZXNwLnN0YXR1cyA9PSAyMDAKICAgICAgICAgICAgICAgIG1z"
    "ZyAgPSAiT2xsYW1hIGlzIHJ1bm5pbmcg4pyTIiBpZiBvayBlbHNlICJPbGxhbWEgbm90IHJlc3Bv"
    "bmRpbmcuIgogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAg"
    "ICBtc2cgPSBmIk9sbGFtYSBub3QgcmVhY2hhYmxlOiB7ZX0iCgogICAgICAgIGVsaWYgaWR4ID09"
    "IDI6ICAjIENsYXVkZQogICAgICAgICAgICBrZXkgPSBzZWxmLl9jbGF1ZGVfa2V5LnRleHQoKS5z"
    "dHJpcCgpCiAgICAgICAgICAgIG9rICA9IGJvb2woa2V5IGFuZCBrZXkuc3RhcnRzd2l0aCgic2st"
    "YW50IikpCiAgICAgICAgICAgIG1zZyA9ICJBUEkga2V5IGZvcm1hdCBsb29rcyBjb3JyZWN0LiIg"
    "aWYgb2sgZWxzZSAiRW50ZXIgYSB2YWxpZCBDbGF1ZGUgQVBJIGtleS4iCgogICAgICAgIGVsaWYg"
    "aWR4ID09IDM6ICAjIE9wZW5BSQogICAgICAgICAgICBrZXkgPSBzZWxmLl9vYWlfa2V5LnRleHQo"
    "KS5zdHJpcCgpCiAgICAgICAgICAgIG9rICA9IGJvb2woa2V5IGFuZCBrZXkuc3RhcnRzd2l0aCgi"
    "c2stIikpCiAgICAgICAgICAgIG1zZyA9ICJBUEkga2V5IGZvcm1hdCBsb29rcyBjb3JyZWN0LiIg"
    "aWYgb2sgZWxzZSAiRW50ZXIgYSB2YWxpZCBPcGVuQUkgQVBJIGtleS4iCgogICAgICAgIGNvbG9y"
    "ID0gQ19HUkVFTiBpZiBvayBlbHNlIENfQ1JJTVNPTgogICAgICAgIHNlbGYuX3N0YXR1c19sYmwu"
    "c2V0VGV4dChtc2cpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImNvbG9yOiB7Y29sb3J9OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7"
    "REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBzZWxmLl9idG5fYXdha2VuLnNl"
    "dEVuYWJsZWQob2spCgogICAgZGVmIGJ1aWxkX2NvbmZpZyhzZWxmKSAtPiBkaWN0OgogICAgICAg"
    "ICIiIkJ1aWxkIGFuZCByZXR1cm4gdXBkYXRlZCBjb25maWcgZGljdCBmcm9tIGRpYWxvZyBzZWxl"
    "Y3Rpb25zLiIiIgogICAgICAgIGNmZyAgICAgPSBfZGVmYXVsdF9jb25maWcoKQogICAgICAgIGlk"
    "eCAgICAgPSBzZWxmLl90eXBlX2NvbWJvLmN1cnJlbnRJbmRleCgpCiAgICAgICAgdHlwZXMgICA9"
    "IFsibG9jYWwiLCAib2xsYW1hIiwgImNsYXVkZSIsICJvcGVuYWkiXQogICAgICAgIGNmZ1sibW9k"
    "ZWwiXVsidHlwZSJdID0gdHlwZXNbaWR4XQoKICAgICAgICBpZiBpZHggPT0gMDoKICAgICAgICAg"
    "ICAgY2ZnWyJtb2RlbCJdWyJwYXRoIl0gPSBzZWxmLl9sb2NhbF9wYXRoLnRleHQoKS5zdHJpcCgp"
    "CiAgICAgICAgZWxpZiBpZHggPT0gMToKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJvbGxhbWFf"
    "bW9kZWwiXSA9IHNlbGYuX29sbGFtYV9tb2RlbC50ZXh0KCkuc3RyaXAoKSBvciAiZG9scGhpbi0y"
    "LjYtN2IiCiAgICAgICAgZWxpZiBpZHggPT0gMjoKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJh"
    "cGlfa2V5Il0gICA9IHNlbGYuX2NsYXVkZV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAg"
    "Y2ZnWyJtb2RlbCJdWyJhcGlfbW9kZWwiXSA9IHNlbGYuX2NsYXVkZV9tb2RlbC50ZXh0KCkuc3Ry"
    "aXAoKQogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV90eXBlIl0gID0gImNsYXVkZSIKICAg"
    "ICAgICBlbGlmIGlkeCA9PSAzOgogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV9rZXkiXSAg"
    "ID0gc2VsZi5fb2FpX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdbIm1vZGVsIl1b"
    "ImFwaV9tb2RlbCJdID0gc2VsZi5fb2FpX21vZGVsLnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAg"
    "IGNmZ1sibW9kZWwiXVsiYXBpX3R5cGUiXSAgPSAib3BlbmFpIgoKICAgICAgICBjZmdbImZpcnN0"
    "X3J1biJdID0gRmFsc2UKICAgICAgICByZXR1cm4gY2ZnCgogICAgQHByb3BlcnR5CiAgICBkZWYg"
    "Y3JlYXRlX3Nob3J0Y3V0KHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIHNlbGYuX3Nob3J0"
    "Y3V0X2NiLmlzQ2hlY2tlZCgpCgoKIyDilIDilIAgSk9VUk5BTCBTSURFQkFSIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFz"
    "cyBKb3VybmFsU2lkZWJhcihRV2lkZ2V0KToKICAgICIiIgogICAgQ29sbGFwc2libGUgbGVmdCBz"
    "aWRlYmFyIG5leHQgdG8gdGhlIHBlcnNvbmEgY2hhdCB0YWIuCiAgICBUb3A6IHNlc3Npb24gY29u"
    "dHJvbHMgKGN1cnJlbnQgc2Vzc2lvbiBuYW1lLCBzYXZlL2xvYWQgYnV0dG9ucywKICAgICAgICAg"
    "YXV0b3NhdmUgaW5kaWNhdG9yKS4KICAgIEJvZHk6IHNjcm9sbGFibGUgc2Vzc2lvbiBsaXN0IOKA"
    "lCBkYXRlLCBBSSBuYW1lLCBtZXNzYWdlIGNvdW50LgogICAgQ29sbGFwc2VzIGxlZnR3YXJkIHRv"
    "IGEgdGhpbiBzdHJpcC4KCiAgICBTaWduYWxzOgogICAgICAgIHNlc3Npb25fbG9hZF9yZXF1ZXN0"
    "ZWQoc3RyKSAgIOKAlCBkYXRlIHN0cmluZyBvZiBzZXNzaW9uIHRvIGxvYWQKICAgICAgICBzZXNz"
    "aW9uX2NsZWFyX3JlcXVlc3RlZCgpICAgICDigJQgcmV0dXJuIHRvIGN1cnJlbnQgc2Vzc2lvbgog"
    "ICAgIiIiCgogICAgc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZCAgPSBTaWduYWwoc3RyKQogICAgc2Vz"
    "c2lvbl9jbGVhcl9yZXF1ZXN0ZWQgPSBTaWduYWwoKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBz"
    "ZXNzaW9uX21ncjogIlNlc3Npb25NYW5hZ2VyIiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVy"
    "KCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3Nlc3Npb25fbWdyID0gc2Vzc2lvbl9t"
    "Z3IKICAgICAgICBzZWxmLl9leHBhbmRlZCAgICA9IFRydWUKICAgICAgICBzZWxmLl9zZXR1cF91"
    "aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgIyBVc2UgYSBob3Jpem9udGFsIHJvb3QgbGF5b3V0IOKAlCBjb250ZW50IG9u"
    "IGxlZnQsIHRvZ2dsZSBzdHJpcCBvbiByaWdodAogICAgICAgIHJvb3QgPSBRSEJveExheW91dChz"
    "ZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAg"
    "cm9vdC5zZXRTcGFjaW5nKDApCgogICAgICAgICMg4pSA4pSAIENvbGxhcHNlIHRvZ2dsZSBzdHJp"
    "cCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICBzZWxmLl90b2dnbGVfc3RyaXAgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl90"
    "b2dnbGVfc3RyaXAuc2V0Rml4ZWRXaWR0aCgyMCkKICAgICAgICBzZWxmLl90b2dnbGVfc3RyaXAu"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXIt"
    "cmlnaHQ6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IgogICAgICAgICkKICAgICAgICB0c19s"
    "YXlvdXQgPSBRVkJveExheW91dChzZWxmLl90b2dnbGVfc3RyaXApCiAgICAgICAgdHNfbGF5b3V0"
    "LnNldENvbnRlbnRzTWFyZ2lucygwLCA4LCAwLCA4KQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4g"
    "PSBRVG9vbEJ1dHRvbigpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRGaXhlZFNpemUoMTgs"
    "IDE4KQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4peAIikKICAgICAgICBzZWxm"
    "Ll90b2dnbGVfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogdHJh"
    "bnNwYXJlbnQ7IGNvbG9yOiB7Q19HT0xEX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5v"
    "bmU7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4u"
    "Y2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZSkKICAgICAgICB0c19sYXlvdXQuYWRkV2lkZ2V0"
    "KHNlbGYuX3RvZ2dsZV9idG4pCiAgICAgICAgdHNfbGF5b3V0LmFkZFN0cmV0Y2goKQoKICAgICAg"
    "ICAjIOKUgOKUgCBNYWluIGNvbnRlbnQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgc2VsZi5fY29udGVudCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0TWlu"
    "aW11bVdpZHRoKDE4MCkKICAgICAgICBzZWxmLl9jb250ZW50LnNldE1heGltdW1XaWR0aCgyMjAp"
    "CiAgICAgICAgY29udGVudF9sYXlvdXQgPSBRVkJveExheW91dChzZWxmLl9jb250ZW50KQogICAg"
    "ICAgIGNvbnRlbnRfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAg"
    "IGNvbnRlbnRfbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBTZWN0aW9uIGxhYmVsCiAg"
    "ICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIEpPVVJOQUwi"
    "KSkKCiAgICAgICAgIyBDdXJyZW50IHNlc3Npb24gaW5mbwogICAgICAgIHNlbGYuX3Nlc3Npb25f"
    "bmFtZSA9IFFMYWJlbCgiTmV3IFNlc3Npb24iKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbmFtZS5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiAx"
    "MHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgIGYiZm9u"
    "dC1zdHlsZTogaXRhbGljOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNl"
    "dFdvcmRXcmFwKFRydWUpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Nl"
    "c3Npb25fbmFtZSkKCiAgICAgICAgIyBTYXZlIC8gTG9hZCByb3cKICAgICAgICBjdHJsX3JvdyA9"
    "IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fc2F2ZSA9IF9nb3RoaWNfYnRuKCLwn5K+"
    "IikKICAgICAgICBzZWxmLl9idG5fc2F2ZS5zZXRGaXhlZFNpemUoMzIsIDI0KQogICAgICAgIHNl"
    "bGYuX2J0bl9zYXZlLnNldFRvb2xUaXAoIlNhdmUgc2Vzc2lvbiBub3ciKQogICAgICAgIHNlbGYu"
    "X2J0bl9sb2FkID0gX2dvdGhpY19idG4oIvCfk4IiKQogICAgICAgIHNlbGYuX2J0bl9sb2FkLnNl"
    "dEZpeGVkU2l6ZSgzMiwgMjQpCiAgICAgICAgc2VsZi5fYnRuX2xvYWQuc2V0VG9vbFRpcCgiQnJv"
    "d3NlIGFuZCBsb2FkIGEgcGFzdCBzZXNzaW9uIikKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Qg"
    "PSBRTGFiZWwoIuKXjyIpCiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA4cHg7IGJvcmRl"
    "cjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRUb29sVGlw"
    "KCJBdXRvc2F2ZSBzdGF0dXMiKQogICAgICAgIHNlbGYuX2J0bl9zYXZlLmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl9kb19zYXZlKQogICAgICAgIHNlbGYuX2J0bl9sb2FkLmNsaWNrZWQuY29ubmVjdChz"
    "ZWxmLl9kb19sb2FkKQogICAgICAgIGN0cmxfcm93LmFkZFdpZGdldChzZWxmLl9idG5fc2F2ZSkK"
    "ICAgICAgICBjdHJsX3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX2xvYWQpCiAgICAgICAgY3RybF9y"
    "b3cuYWRkV2lkZ2V0KHNlbGYuX2F1dG9zYXZlX2RvdCkKICAgICAgICBjdHJsX3Jvdy5hZGRTdHJl"
    "dGNoKCkKICAgICAgICBjb250ZW50X2xheW91dC5hZGRMYXlvdXQoY3RybF9yb3cpCgogICAgICAg"
    "ICMgSm91cm5hbCBsb2FkZWQgaW5kaWNhdG9yCiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwgPSBR"
    "TGFiZWwoIiIpCiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJjb2xvcjoge0NfUFVSUExFfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7"
    "REVDS19GT05UfSwgc2VyaWY7ICIKICAgICAgICAgICAgZiJmb250LXN0eWxlOiBpdGFsaWM7Igog"
    "ICAgICAgICkKICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRXb3JkV3JhcChUcnVlKQogICAg"
    "ICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9qb3VybmFsX2xibCkKCiAgICAgICAg"
    "IyBDbGVhciBqb3VybmFsIGJ1dHRvbiAoaGlkZGVuIHdoZW4gbm90IGxvYWRlZCkKICAgICAgICBz"
    "ZWxmLl9idG5fY2xlYXJfam91cm5hbCA9IF9nb3RoaWNfYnRuKCLinJcgUmV0dXJuIHRvIFByZXNl"
    "bnQiKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLnNldFZpc2libGUoRmFsc2UpCiAg"
    "ICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2Ns"
    "ZWFyX2pvdXJuYWwpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2J0bl9j"
    "bGVhcl9qb3VybmFsKQoKICAgICAgICAjIERpdmlkZXIKICAgICAgICBkaXYgPSBRRnJhbWUoKQog"
    "ICAgICAgIGRpdi5zZXRGcmFtZVNoYXBlKFFGcmFtZS5TaGFwZS5ITGluZSkKICAgICAgICBkaXYu"
    "c2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19DUklNU09OX0RJTX07IikKICAgICAgICBjb250ZW50"
    "X2xheW91dC5hZGRXaWRnZXQoZGl2KQoKICAgICAgICAjIFNlc3Npb24gbGlzdAogICAgICAgIGNv"
    "bnRlbnRfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBQQVNUIFNFU1NJT05TIikp"
    "CiAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0ID0gUUxpc3RXaWRnZXQoKQogICAgICAgIHNlbGYu"
    "X3Nlc3Npb25fbGlzdC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtD"
    "X0JHMn07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlk"
    "IHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNl"
    "cmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICAgICBmIlFMaXN0V2lkZ2V0OjppdGVtOnNl"
    "bGVjdGVkIHt7IGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsgfX0iCiAgICAgICAgKQogICAg"
    "ICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5pdGVtRG91YmxlQ2xpY2tlZC5jb25uZWN0KHNlbGYuX29u"
    "X3Nlc3Npb25fY2xpY2spCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0Lml0ZW1DbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fb25fc2Vzc2lvbl9jbGljaykKICAgICAgICBjb250ZW50X2xheW91dC5hZGRX"
    "aWRnZXQoc2VsZi5fc2Vzc2lvbl9saXN0LCAxKQoKICAgICAgICAjIEFkZCBjb250ZW50IGFuZCB0"
    "b2dnbGUgc3RyaXAgdG8gdGhlIHJvb3QgaG9yaXpvbnRhbCBsYXlvdXQKICAgICAgICByb290LmFk"
    "ZFdpZGdldChzZWxmLl9jb250ZW50KQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3RvZ2ds"
    "ZV9zdHJpcCkKCiAgICBkZWYgX3RvZ2dsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2V4"
    "cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAgICAgICAgc2VsZi5fY29udGVudC5zZXRWaXNp"
    "YmxlKHNlbGYuX2V4cGFuZGVkKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4peA"
    "IiBpZiBzZWxmLl9leHBhbmRlZCBlbHNlICLilrYiKQogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0"
    "cnkoKQogICAgICAgIHAgPSBzZWxmLnBhcmVudFdpZGdldCgpCiAgICAgICAgaWYgcCBhbmQgcC5s"
    "YXlvdXQoKToKICAgICAgICAgICAgcC5sYXlvdXQoKS5hY3RpdmF0ZSgpCgogICAgZGVmIHJlZnJl"
    "c2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZXNzaW9ucyA9IHNlbGYuX3Nlc3Npb25fbWdyLmxp"
    "c3Rfc2Vzc2lvbnMoKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5jbGVhcigpCiAgICAgICAg"
    "Zm9yIHMgaW4gc2Vzc2lvbnM6CiAgICAgICAgICAgIGRhdGVfc3RyID0gcy5nZXQoImRhdGUiLCIi"
    "KQogICAgICAgICAgICBuYW1lICAgICA9IHMuZ2V0KCJuYW1lIiwgZGF0ZV9zdHIpWzozMF0KICAg"
    "ICAgICAgICAgY291bnQgICAgPSBzLmdldCgibWVzc2FnZV9jb3VudCIsIDApCiAgICAgICAgICAg"
    "IGl0ZW0gPSBRTGlzdFdpZGdldEl0ZW0oZiJ7ZGF0ZV9zdHJ9XG57bmFtZX0gKHtjb3VudH0gbXNn"
    "cykiKQogICAgICAgICAgICBpdGVtLnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCBk"
    "YXRlX3N0cikKICAgICAgICAgICAgaXRlbS5zZXRUb29sVGlwKGYiRG91YmxlLWNsaWNrIHRvIGxv"
    "YWQgc2Vzc2lvbiBmcm9tIHtkYXRlX3N0cn0iKQogICAgICAgICAgICBzZWxmLl9zZXNzaW9uX2xp"
    "c3QuYWRkSXRlbShpdGVtKQoKICAgIGRlZiBzZXRfc2Vzc2lvbl9uYW1lKHNlbGYsIG5hbWU6IHN0"
    "cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUuc2V0VGV4dChuYW1lWzo1MF0g"
    "b3IgIk5ldyBTZXNzaW9uIikKCiAgICBkZWYgc2V0X2F1dG9zYXZlX2luZGljYXRvcihzZWxmLCBz"
    "YXZlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Quc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR1JFRU4gaWYgc2F2ZWQgZWxzZSBDX1RFWFRf"
    "RElNfTsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTogOHB4OyBib3JkZXI6IG5vbmU7IgogICAg"
    "ICAgICkKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Quc2V0VG9vbFRpcCgKICAgICAgICAgICAg"
    "IkF1dG9zYXZlZCIgaWYgc2F2ZWQgZWxzZSAiUGVuZGluZyBhdXRvc2F2ZSIKICAgICAgICApCgog"
    "ICAgZGVmIHNldF9qb3VybmFsX2xvYWRlZChzZWxmLCBkYXRlX3N0cjogc3RyKSAtPiBOb25lOgog"
    "ICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsLnNldFRleHQoZiLwn5OWIEpvdXJuYWw6IHtkYXRlX3N0"
    "cn0iKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLnNldFZpc2libGUoVHJ1ZSkKCiAg"
    "ICBkZWYgY2xlYXJfam91cm5hbF9pbmRpY2F0b3Ioc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9qb3VybmFsX2xibC5zZXRUZXh0KCIiKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFs"
    "LnNldFZpc2libGUoRmFsc2UpCgogICAgZGVmIF9kb19zYXZlKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgc2VsZi5fc2Vzc2lvbl9tZ3Iuc2F2ZSgpCiAgICAgICAgc2VsZi5zZXRfYXV0b3NhdmVfaW5k"
    "aWNhdG9yKFRydWUpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKICAgICAgICBzZWxmLl9idG5fc2F2"
    "ZS5zZXRUZXh0KCLinJMiKQogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDE1MDAsIGxhbWJkYTog"
    "c2VsZi5fYnRuX3NhdmUuc2V0VGV4dCgi8J+SviIpKQogICAgICAgIFFUaW1lci5zaW5nbGVTaG90"
    "KDMwMDAsIGxhbWJkYTogc2VsZi5zZXRfYXV0b3NhdmVfaW5kaWNhdG9yKEZhbHNlKSkKCiAgICBk"
    "ZWYgX2RvX2xvYWQoc2VsZikgLT4gTm9uZToKICAgICAgICAjIFRyeSBzZWxlY3RlZCBpdGVtIGZp"
    "cnN0CiAgICAgICAgaXRlbSA9IHNlbGYuX3Nlc3Npb25fbGlzdC5jdXJyZW50SXRlbSgpCiAgICAg"
    "ICAgaWYgbm90IGl0ZW06CiAgICAgICAgICAgICMgSWYgbm90aGluZyBzZWxlY3RlZCwgdHJ5IHRo"
    "ZSBmaXJzdCBpdGVtCiAgICAgICAgICAgIGlmIHNlbGYuX3Nlc3Npb25fbGlzdC5jb3VudCgpID4g"
    "MDoKICAgICAgICAgICAgICAgIGl0ZW0gPSBzZWxmLl9zZXNzaW9uX2xpc3QuaXRlbSgwKQogICAg"
    "ICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0LnNldEN1cnJlbnRJdGVtKGl0ZW0pCiAgICAg"
    "ICAgaWYgaXRlbToKICAgICAgICAgICAgZGF0ZV9zdHIgPSBpdGVtLmRhdGEoUXQuSXRlbURhdGFS"
    "b2xlLlVzZXJSb2xlKQogICAgICAgICAgICBzZWxmLnNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQuZW1p"
    "dChkYXRlX3N0cikKCiAgICBkZWYgX29uX3Nlc3Npb25fY2xpY2soc2VsZiwgaXRlbSkgLT4gTm9u"
    "ZToKICAgICAgICBkYXRlX3N0ciA9IGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUp"
    "CiAgICAgICAgc2VsZi5zZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmVtaXQoZGF0ZV9zdHIpCgogICAg"
    "ZGVmIF9kb19jbGVhcl9qb3VybmFsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zZXNzaW9u"
    "X2NsZWFyX3JlcXVlc3RlZC5lbWl0KCkKICAgICAgICBzZWxmLmNsZWFyX2pvdXJuYWxfaW5kaWNh"
    "dG9yKCkKCgojIOKUgOKUgCBUT1JQT1IgUEFORUwg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFRvcnBv"
    "clBhbmVsKFFXaWRnZXQpOgogICAgIiIiCiAgICBUaHJlZS1zdGF0ZSBzdXNwZW5zaW9uIHRvZ2ds"
    "ZTogQVdBS0UgfCBBVVRPIHwgU1VTUEVORAoKICAgIEFXQUtFICDigJQgbW9kZWwgbG9hZGVkLCBh"
    "dXRvLXRvcnBvciBkaXNhYmxlZCwgaWdub3JlcyBWUkFNIHByZXNzdXJlCiAgICBBVVRPICAg4oCU"
    "IG1vZGVsIGxvYWRlZCwgbW9uaXRvcnMgVlJBTSBwcmVzc3VyZSwgYXV0by10b3Jwb3IgaWYgc3Vz"
    "dGFpbmVkCiAgICBTVVNQRU5EIOKAlCBtb2RlbCB1bmxvYWRlZCwgc3RheXMgc3VzcGVuZGVkIHVu"
    "dGlsIG1hbnVhbGx5IGNoYW5nZWQKCiAgICBTaWduYWxzOgogICAgICAgIHN0YXRlX2NoYW5nZWQo"
    "c3RyKSAg4oCUICJBV0FLRSIgfCAiQVVUTyIgfCAiU1VTUEVORCIKICAgICIiIgoKICAgIHN0YXRl"
    "X2NoYW5nZWQgPSBTaWduYWwoc3RyKQoKICAgIFNUQVRFUyA9IFsiQVdBS0UiLCAiQVVUTyIsICJT"
    "VVNQRU5EIl0KCiAgICBTVEFURV9TVFlMRVMgPSB7CiAgICAgICAgIkFXQUtFIjogewogICAgICAg"
    "ICAgICAiYWN0aXZlIjogICBmImJhY2tncm91bmQ6ICMyYTFhMDU7IGNvbG9yOiB7Q19HT0xEfTsg"
    "IgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0dPTER9OyBi"
    "b3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250LXNpemU6"
    "IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAg"
    "ImluYWN0aXZlIjogZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAi"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsg"
    "Ym9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXpl"
    "OiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAg"
    "ICJsYWJlbCI6ICAgICLimIAgQVdBS0UiLAogICAgICAgICAgICAidG9vbHRpcCI6ICAiTW9kZWwg"
    "YWN0aXZlLiBBdXRvLXRvcnBvciBkaXNhYmxlZC4iLAogICAgICAgIH0sCiAgICAgICAgIkFVVE8i"
    "OiB7CiAgICAgICAgICAgICJhY3RpdmUiOiAgIGYiYmFja2dyb3VuZDogIzFhMTAwNTsgY29sb3I6"
    "ICNjYzg4MjI7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCAj"
    "Y2M4ODIyOyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJm"
    "b250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAg"
    "ICAgICAgICAgImluYWN0aXZlIjogZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVY"
    "VF9ESU19OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0Nf"
    "Qk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYi"
    "Zm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAg"
    "ICAgICAgICAgICJsYWJlbCI6ICAgICLil4kgQVVUTyIsCiAgICAgICAgICAgICJ0b29sdGlwIjog"
    "ICJNb2RlbCBhY3RpdmUuIEF1dG8tc3VzcGVuZCBvbiBWUkFNIHByZXNzdXJlLiIsCiAgICAgICAg"
    "fSwKICAgICAgICAiU1VTUEVORCI6IHsKICAgICAgICAgICAgImFjdGl2ZSI6ICAgZiJiYWNrZ3Jv"
    "dW5kOiB7Q19QVVJQTEVfRElNfTsgY29sb3I6IHtDX1BVUlBMRX07ICIKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19QVVJQTEV9OyBib3JkZXItcmFkaXVzOiAy"
    "cHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWln"
    "aHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAgImluYWN0aXZlIjogZiJi"
    "YWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czog"
    "MnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2Vp"
    "Z2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJsYWJlbCI6ICAgIGYi"
    "4pqwIHtVSV9TVVNQRU5TSU9OX0xBQkVMLnN0cmlwKCkgaWYgc3RyKFVJX1NVU1BFTlNJT05fTEFC"
    "RUwpLnN0cmlwKCkgZWxzZSAnU3VzcGVuZCd9IiwKICAgICAgICAgICAgInRvb2x0aXAiOiAgZiJN"
    "b2RlbCB1bmxvYWRlZC4ge0RFQ0tfTkFNRX0gc2xlZXBzIHVudGlsIG1hbnVhbGx5IGF3YWtlbmVk"
    "LiIsCiAgICAgICAgfSwKICAgIH0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUp"
    "OgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2N1cnJlbnQg"
    "PSAiQVdBS0UiCiAgICAgICAgc2VsZi5fYnV0dG9uczogZGljdFtzdHIsIFFQdXNoQnV0dG9uXSA9"
    "IHt9CiAgICAgICAgbGF5b3V0ID0gUUhCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0"
    "Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoMikK"
    "CiAgICAgICAgZm9yIHN0YXRlIGluIHNlbGYuU1RBVEVTOgogICAgICAgICAgICBidG4gPSBRUHVz"
    "aEJ1dHRvbihzZWxmLlNUQVRFX1NUWUxFU1tzdGF0ZV1bImxhYmVsIl0pCiAgICAgICAgICAgIGJ0"
    "bi5zZXRUb29sVGlwKHNlbGYuU1RBVEVfU1RZTEVTW3N0YXRlXVsidG9vbHRpcCJdKQogICAgICAg"
    "ICAgICBidG4uc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgICAgIGJ0bi5jbGlja2VkLmNvbm5l"
    "Y3QobGFtYmRhIGNoZWNrZWQsIHM9c3RhdGU6IHNlbGYuX3NldF9zdGF0ZShzKSkKICAgICAgICAg"
    "ICAgc2VsZi5fYnV0dG9uc1tzdGF0ZV0gPSBidG4KICAgICAgICAgICAgbGF5b3V0LmFkZFdpZGdl"
    "dChidG4pCgogICAgICAgIHNlbGYuX2FwcGx5X3N0eWxlcygpCgogICAgZGVmIF9zZXRfc3RhdGUo"
    "c2VsZiwgc3RhdGU6IHN0cikgLT4gTm9uZToKICAgICAgICBpZiBzdGF0ZSA9PSBzZWxmLl9jdXJy"
    "ZW50OgogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9jdXJyZW50ID0gc3RhdGUKICAg"
    "ICAgICBzZWxmLl9hcHBseV9zdHlsZXMoKQogICAgICAgIHNlbGYuc3RhdGVfY2hhbmdlZC5lbWl0"
    "KHN0YXRlKQoKICAgIGRlZiBfYXBwbHlfc3R5bGVzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9y"
    "IHN0YXRlLCBidG4gaW4gc2VsZi5fYnV0dG9ucy5pdGVtcygpOgogICAgICAgICAgICBzdHlsZV9r"
    "ZXkgPSAiYWN0aXZlIiBpZiBzdGF0ZSA9PSBzZWxmLl9jdXJyZW50IGVsc2UgImluYWN0aXZlIgog"
    "ICAgICAgICAgICBidG4uc2V0U3R5bGVTaGVldChzZWxmLlNUQVRFX1NUWUxFU1tzdGF0ZV1bc3R5"
    "bGVfa2V5XSkKCiAgICBAcHJvcGVydHkKICAgIGRlZiBjdXJyZW50X3N0YXRlKHNlbGYpIC0+IHN0"
    "cjoKICAgICAgICByZXR1cm4gc2VsZi5fY3VycmVudAoKICAgIGRlZiBzZXRfc3RhdGUoc2VsZiwg"
    "c3RhdGU6IHN0cikgLT4gTm9uZToKICAgICAgICAiIiJTZXQgc3RhdGUgcHJvZ3JhbW1hdGljYWxs"
    "eSAoZS5nLiBmcm9tIGF1dG8tdG9ycG9yIGRldGVjdGlvbikuIiIiCiAgICAgICAgaWYgc3RhdGUg"
    "aW4gc2VsZi5TVEFURVM6CiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0ZShzdGF0ZSkKCgpjbGFz"
    "cyBTZXR0aW5nc1NlY3Rpb24oUVdpZGdldCk6CiAgICAiIiJTaW1wbGUgY29sbGFwc2libGUgc2Vj"
    "dGlvbiB1c2VkIGJ5IFNldHRpbmdzVGFiLiIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCB0aXRs"
    "ZTogc3RyLCBwYXJlbnQ9Tm9uZSwgZXhwYW5kZWQ6IGJvb2wgPSBUcnVlKToKICAgICAgICBzdXBl"
    "cigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IGV4cGFuZGVkCgog"
    "ICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNN"
    "YXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDApCgogICAgICAgIHNl"
    "bGYuX2hlYWRlcl9idG4gPSBRVG9vbEJ1dHRvbigpCiAgICAgICAgc2VsZi5faGVhZGVyX2J0bi5z"
    "ZXRUZXh0KGYi4pa8IHt0aXRsZX0iIGlmIGV4cGFuZGVkIGVsc2UgZiLilrYge3RpdGxlfSIpCiAg"
    "ICAgICAgc2VsZi5faGVhZGVyX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tn"
    "cm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJ"
    "TVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYicGFkZGluZzogNnB4OyB0ZXh0LWFsaWduOiBsZWZ0"
    "OyBmb250LXdlaWdodDogYm9sZDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2hlYWRlcl9idG4u"
    "Y2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZSkKCiAgICAgICAgc2VsZi5fY29udGVudCA9IFFX"
    "aWRnZXQoKQogICAgICAgIHNlbGYuX2NvbnRlbnRfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5f"
    "Y29udGVudCkKICAgICAgICBzZWxmLl9jb250ZW50X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMo"
    "OCwgOCwgOCwgOCkKICAgICAgICBzZWxmLl9jb250ZW50X2xheW91dC5zZXRTcGFjaW5nKDgpCiAg"
    "ICAgICAgc2VsZi5fY29udGVudC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91"
    "bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci10b3A6IG5v"
    "bmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl9jb250ZW50LnNldFZpc2libGUoZXhwYW5kZWQp"
    "CgogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2hlYWRlcl9idG4pCiAgICAgICAgcm9vdC5h"
    "ZGRXaWRnZXQoc2VsZi5fY29udGVudCkKCiAgICBAcHJvcGVydHkKICAgIGRlZiBjb250ZW50X2xh"
    "eW91dChzZWxmKSAtPiBRVkJveExheW91dDoKICAgICAgICByZXR1cm4gc2VsZi5fY29udGVudF9s"
    "YXlvdXQKCiAgICBkZWYgX3RvZ2dsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2V4cGFu"
    "ZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAgICAgICAgc2VsZi5faGVhZGVyX2J0bi5zZXRUZXh0"
    "KAogICAgICAgICAgICBzZWxmLl9oZWFkZXJfYnRuLnRleHQoKS5yZXBsYWNlKCLilrwiLCAi4pa2"
    "IiwgMSkKICAgICAgICAgICAgaWYgbm90IHNlbGYuX2V4cGFuZGVkIGVsc2UKICAgICAgICAgICAg"
    "c2VsZi5faGVhZGVyX2J0bi50ZXh0KCkucmVwbGFjZSgi4pa2IiwgIuKWvCIsIDEpCiAgICAgICAg"
    "KQogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0VmlzaWJsZShzZWxmLl9leHBhbmRlZCkKCgpjbGFz"
    "cyBTZXR0aW5nc1RhYihRV2lkZ2V0KToKICAgICIiIkRlY2std2lkZSBydW50aW1lIHNldHRpbmdz"
    "IHRhYi4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgZGVja193aW5kb3c6ICJFY2hvRGVjayIs"
    "IHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBz"
    "ZWxmLl9kZWNrID0gZGVja193aW5kb3cKICAgICAgICBzZWxmLl9zZWN0aW9uX3JlZ2lzdHJ5OiBs"
    "aXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zZWN0aW9uX3dpZGdldHM6IGRpY3Rbc3RyLCBT"
    "ZXR0aW5nc1NlY3Rpb25dID0ge30KCiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAg"
    "ICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICByb290LnNl"
    "dFNwYWNpbmcoMCkKCiAgICAgICAgc2Nyb2xsID0gUVNjcm9sbEFyZWEoKQogICAgICAgIHNjcm9s"
    "bC5zZXRXaWRnZXRSZXNpemFibGUoVHJ1ZSkKICAgICAgICBzY3JvbGwuc2V0SG9yaXpvbnRhbFNj"
    "cm9sbEJhclBvbGljeShRdC5TY3JvbGxCYXJQb2xpY3kuU2Nyb2xsQmFyQWx3YXlzT2ZmKQogICAg"
    "ICAgIHNjcm9sbC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkd9OyBib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19DUklNU09OX0RJTX07IikKICAgICAgICByb290LmFkZFdpZGdldChzY3JvbGwp"
    "CgogICAgICAgIGJvZHkgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9ib2R5X2xheW91dCA9IFFW"
    "Qm94TGF5b3V0KGJvZHkpCiAgICAgICAgc2VsZi5fYm9keV9sYXlvdXQuc2V0Q29udGVudHNNYXJn"
    "aW5zKDYsIDYsIDYsIDYpCiAgICAgICAgc2VsZi5fYm9keV9sYXlvdXQuc2V0U3BhY2luZyg4KQog"
    "ICAgICAgIHNjcm9sbC5zZXRXaWRnZXQoYm9keSkKCiAgICAgICAgc2VsZi5fcmVnaXN0ZXJfY29y"
    "ZV9zZWN0aW9ucygpCgogICAgZGVmIF9yZWdpc3Rlcl9zZWN0aW9uKHNlbGYsICosIHNlY3Rpb25f"
    "aWQ6IHN0ciwgdGl0bGU6IHN0ciwgY2F0ZWdvcnk6IHN0ciwgc291cmNlX293bmVyOiBzdHIsIHNv"
    "cnRfa2V5OiBpbnQsIGJ1aWxkZXIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2VjdGlvbl9yZWdp"
    "c3RyeS5hcHBlbmQoewogICAgICAgICAgICAic2VjdGlvbl9pZCI6IHNlY3Rpb25faWQsCiAgICAg"
    "ICAgICAgICJ0aXRsZSI6IHRpdGxlLAogICAgICAgICAgICAiY2F0ZWdvcnkiOiBjYXRlZ29yeSwK"
    "ICAgICAgICAgICAgInNvdXJjZV9vd25lciI6IHNvdXJjZV9vd25lciwKICAgICAgICAgICAgInNv"
    "cnRfa2V5Ijogc29ydF9rZXksCiAgICAgICAgICAgICJidWlsZGVyIjogYnVpbGRlciwKICAgICAg"
    "ICB9KQoKICAgIGRlZiBfcmVnaXN0ZXJfY29yZV9zZWN0aW9ucyhzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHNlbGYuX3JlZ2lzdGVyX3NlY3Rpb24oCiAgICAgICAgICAgIHNlY3Rpb25faWQ9InN5c3Rl"
    "bV9zZXR0aW5ncyIsCiAgICAgICAgICAgIHRpdGxlPSJTeXN0ZW0gU2V0dGluZ3MiLAogICAgICAg"
    "ICAgICBjYXRlZ29yeT0iY29yZSIsCiAgICAgICAgICAgIHNvdXJjZV9vd25lcj0iZGVja19ydW50"
    "aW1lIiwKICAgICAgICAgICAgc29ydF9rZXk9MTAwLAogICAgICAgICAgICBidWlsZGVyPXNlbGYu"
    "X2J1aWxkX3N5c3RlbV9zZWN0aW9uLAogICAgICAgICkKICAgICAgICBzZWxmLl9yZWdpc3Rlcl9z"
    "ZWN0aW9uKAogICAgICAgICAgICBzZWN0aW9uX2lkPSJpbnRlZ3JhdGlvbl9zZXR0aW5ncyIsCiAg"
    "ICAgICAgICAgIHRpdGxlPSJJbnRlZ3JhdGlvbiBTZXR0aW5ncyIsCiAgICAgICAgICAgIGNhdGVn"
    "b3J5PSJjb3JlIiwKICAgICAgICAgICAgc291cmNlX293bmVyPSJkZWNrX3J1bnRpbWUiLAogICAg"
    "ICAgICAgICBzb3J0X2tleT0yMDAsCiAgICAgICAgICAgIGJ1aWxkZXI9c2VsZi5fYnVpbGRfaW50"
    "ZWdyYXRpb25fc2VjdGlvbiwKICAgICAgICApCiAgICAgICAgc2VsZi5fcmVnaXN0ZXJfc2VjdGlv"
    "bigKICAgICAgICAgICAgc2VjdGlvbl9pZD0idWlfc2V0dGluZ3MiLAogICAgICAgICAgICB0aXRs"
    "ZT0iVUkgU2V0dGluZ3MiLAogICAgICAgICAgICBjYXRlZ29yeT0iY29yZSIsCiAgICAgICAgICAg"
    "IHNvdXJjZV9vd25lcj0iZGVja19ydW50aW1lIiwKICAgICAgICAgICAgc29ydF9rZXk9MzAwLAog"
    "ICAgICAgICAgICBidWlsZGVyPXNlbGYuX2J1aWxkX3VpX3NlY3Rpb24sCiAgICAgICAgKQoKICAg"
    "ICAgICBmb3IgbWV0YSBpbiBzb3J0ZWQoc2VsZi5fc2VjdGlvbl9yZWdpc3RyeSwga2V5PWxhbWJk"
    "YSBtOiBtLmdldCgic29ydF9rZXkiLCA5OTk5KSk6CiAgICAgICAgICAgIHNlY3Rpb24gPSBTZXR0"
    "aW5nc1NlY3Rpb24obWV0YVsidGl0bGUiXSwgZXhwYW5kZWQ9VHJ1ZSkKICAgICAgICAgICAgc2Vs"
    "Zi5fYm9keV9sYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb24pCiAgICAgICAgICAgIHNlbGYuX3NlY3Rp"
    "b25fd2lkZ2V0c1ttZXRhWyJzZWN0aW9uX2lkIl1dID0gc2VjdGlvbgogICAgICAgICAgICBtZXRh"
    "WyJidWlsZGVyIl0oc2VjdGlvbi5jb250ZW50X2xheW91dCkKCiAgICAgICAgc2VsZi5fYm9keV9s"
    "YXlvdXQuYWRkU3RyZXRjaCgxKQoKICAgIGRlZiBfYnVpbGRfc3lzdGVtX3NlY3Rpb24oc2VsZiwg"
    "bGF5b3V0OiBRVkJveExheW91dCkgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl9kZWNrLl90b3Jw"
    "b3JfcGFuZWwgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoUUxhYmVs"
    "KCJPcGVyYXRpb25hbCBNb2RlIikpCiAgICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5f"
    "ZGVjay5fdG9ycG9yX3BhbmVsKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KFFMYWJlbCgiSWRs"
    "ZSIpKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZGVjay5faWRsZV9idG4pCgogICAg"
    "ICAgIHNldHRpbmdzID0gQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkKICAgICAgICB0el9hdXRvID0g"
    "Ym9vbChzZXR0aW5ncy5nZXQoInRpbWV6b25lX2F1dG9fZGV0ZWN0IiwgVHJ1ZSkpCiAgICAgICAg"
    "dHpfb3ZlcnJpZGUgPSBzdHIoc2V0dGluZ3MuZ2V0KCJ0aW1lem9uZV9vdmVycmlkZSIsICIiKSBv"
    "ciAiIikuc3RyaXAoKQoKICAgICAgICB0el9hdXRvX2NoayA9IFFDaGVja0JveCgiQXV0by1kZXRl"
    "Y3QgbG9jYWwvc3lzdGVtIHRpbWUgem9uZSIpCiAgICAgICAgdHpfYXV0b19jaGsuc2V0Q2hlY2tl"
    "ZCh0el9hdXRvKQogICAgICAgIHR6X2F1dG9fY2hrLnRvZ2dsZWQuY29ubmVjdChzZWxmLl9kZWNr"
    "Ll9zZXRfdGltZXpvbmVfYXV0b19kZXRlY3QpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldCh0el9h"
    "dXRvX2NoaykKCiAgICAgICAgdHpfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHR6X3Jvdy5h"
    "ZGRXaWRnZXQoUUxhYmVsKCJNYW51YWwgVGltZSBab25lIE92ZXJyaWRlOiIpKQogICAgICAgIHR6"
    "X2NvbWJvID0gUUNvbWJvQm94KCkKICAgICAgICB0el9jb21iby5zZXRFZGl0YWJsZShUcnVlKQog"
    "ICAgICAgIHR6X29wdGlvbnMgPSBbCiAgICAgICAgICAgICJBbWVyaWNhL0NoaWNhZ28iLCAiQW1l"
    "cmljYS9OZXdfWW9yayIsICJBbWVyaWNhL0xvc19BbmdlbGVzIiwKICAgICAgICAgICAgIkFtZXJp"
    "Y2EvRGVudmVyIiwgIlVUQyIKICAgICAgICBdCiAgICAgICAgdHpfY29tYm8uYWRkSXRlbXModHpf"
    "b3B0aW9ucykKICAgICAgICBpZiB0el9vdmVycmlkZToKICAgICAgICAgICAgaWYgdHpfY29tYm8u"
    "ZmluZFRleHQodHpfb3ZlcnJpZGUpIDwgMDoKICAgICAgICAgICAgICAgIHR6X2NvbWJvLmFkZEl0"
    "ZW0odHpfb3ZlcnJpZGUpCiAgICAgICAgICAgIHR6X2NvbWJvLnNldEN1cnJlbnRUZXh0KHR6X292"
    "ZXJyaWRlKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHR6X2NvbWJvLnNldEN1cnJlbnRUZXh0"
    "KCJBbWVyaWNhL0NoaWNhZ28iKQogICAgICAgIHR6X2NvbWJvLnNldEVuYWJsZWQobm90IHR6X2F1"
    "dG8pCiAgICAgICAgdHpfY29tYm8uY3VycmVudFRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fZGVj"
    "ay5fc2V0X3RpbWV6b25lX292ZXJyaWRlKQogICAgICAgIHR6X2F1dG9fY2hrLnRvZ2dsZWQuY29u"
    "bmVjdChsYW1iZGEgZW5hYmxlZDogdHpfY29tYm8uc2V0RW5hYmxlZChub3QgZW5hYmxlZCkpCiAg"
    "ICAgICAgdHpfcm93LmFkZFdpZGdldCh0el9jb21ibywgMSkKICAgICAgICB0el9ob3N0ID0gUVdp"
    "ZGdldCgpCiAgICAgICAgdHpfaG9zdC5zZXRMYXlvdXQodHpfcm93KQogICAgICAgIGxheW91dC5h"
    "ZGRXaWRnZXQodHpfaG9zdCkKCiAgICBkZWYgX2J1aWxkX2ludGVncmF0aW9uX3NlY3Rpb24oc2Vs"
    "ZiwgbGF5b3V0OiBRVkJveExheW91dCkgLT4gTm9uZToKICAgICAgICBzZXR0aW5ncyA9IENGRy5n"
    "ZXQoInNldHRpbmdzIiwge30pCiAgICAgICAgZ29vZ2xlX3NlY29uZHMgPSBpbnQoc2V0dGluZ3Mu"
    "Z2V0KCJnb29nbGVfaW5ib3VuZF9pbnRlcnZhbF9tcyIsIDMwMDAwKSkgLy8gMTAwMAogICAgICAg"
    "IGdvb2dsZV9zZWNvbmRzID0gbWF4KDUsIG1pbig2MDAsIGdvb2dsZV9zZWNvbmRzKSkKICAgICAg"
    "ICBlbWFpbF9taW51dGVzID0gbWF4KDEsIGludChzZXR0aW5ncy5nZXQoImVtYWlsX3JlZnJlc2hf"
    "aW50ZXJ2YWxfbXMiLCAzMDAwMDApKSAvLyA2MDAwMCkKCiAgICAgICAgZ29vZ2xlX3JvdyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBnb29nbGVfcm93LmFkZFdpZGdldChRTGFiZWwoIkdvb2dsZSBy"
    "ZWZyZXNoIGludGVydmFsIChzZWNvbmRzKToiKSkKICAgICAgICBnb29nbGVfYm94ID0gUVNwaW5C"
    "b3goKQogICAgICAgIGdvb2dsZV9ib3guc2V0UmFuZ2UoNSwgNjAwKQogICAgICAgIGdvb2dsZV9i"
    "b3guc2V0VmFsdWUoZ29vZ2xlX3NlY29uZHMpCiAgICAgICAgZ29vZ2xlX2JveC52YWx1ZUNoYW5n"
    "ZWQuY29ubmVjdChzZWxmLl9kZWNrLl9zZXRfZ29vZ2xlX3JlZnJlc2hfc2Vjb25kcykKICAgICAg"
    "ICBnb29nbGVfcm93LmFkZFdpZGdldChnb29nbGVfYm94LCAxKQogICAgICAgIGdvb2dsZV9ob3N0"
    "ID0gUVdpZGdldCgpCiAgICAgICAgZ29vZ2xlX2hvc3Quc2V0TGF5b3V0KGdvb2dsZV9yb3cpCiAg"
    "ICAgICAgbGF5b3V0LmFkZFdpZGdldChnb29nbGVfaG9zdCkKCiAgICAgICAgZW1haWxfcm93ID0g"
    "UUhCb3hMYXlvdXQoKQogICAgICAgIGVtYWlsX3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJFbWFpbCBy"
    "ZWZyZXNoIGludGVydmFsIChtaW51dGVzKToiKSkKICAgICAgICBlbWFpbF9ib3ggPSBRQ29tYm9C"
    "b3goKQogICAgICAgIGVtYWlsX2JveC5zZXRFZGl0YWJsZShUcnVlKQogICAgICAgIGVtYWlsX2Jv"
    "eC5hZGRJdGVtcyhbIjEiLCAiNSIsICIxMCIsICIxNSIsICIzMCIsICI2MCJdKQogICAgICAgIGVt"
    "YWlsX2JveC5zZXRDdXJyZW50VGV4dChzdHIoZW1haWxfbWludXRlcykpCiAgICAgICAgZW1haWxf"
    "Ym94LmN1cnJlbnRUZXh0Q2hhbmdlZC5jb25uZWN0KHNlbGYuX2RlY2suX3NldF9lbWFpbF9yZWZy"
    "ZXNoX21pbnV0ZXNfZnJvbV90ZXh0KQogICAgICAgIGVtYWlsX3Jvdy5hZGRXaWRnZXQoZW1haWxf"
    "Ym94LCAxKQogICAgICAgIGVtYWlsX2hvc3QgPSBRV2lkZ2V0KCkKICAgICAgICBlbWFpbF9ob3N0"
    "LnNldExheW91dChlbWFpbF9yb3cpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChlbWFpbF9ob3N0"
    "KQoKICAgICAgICBub3RlID0gUUxhYmVsKCJFbWFpbCBwb2xsaW5nIGZvdW5kYXRpb24gaXMgY29u"
    "ZmlndXJhdGlvbi1vbmx5IHVubGVzcyBhbiBlbWFpbCBiYWNrZW5kIGlzIGVuYWJsZWQuIikKICAg"
    "ICAgICBub3RlLnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6"
    "IDlweDsiKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQobm90ZSkKCiAgICBkZWYgX2J1aWxkX3Vp"
    "X3NlY3Rpb24oc2VsZiwgbGF5b3V0OiBRVkJveExheW91dCkgLT4gTm9uZToKICAgICAgICBsYXlv"
    "dXQuYWRkV2lkZ2V0KFFMYWJlbCgiV2luZG93IFNoZWxsIikpCiAgICAgICAgbGF5b3V0LmFkZFdp"
    "ZGdldChzZWxmLl9kZWNrLl9mc19idG4pCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9k"
    "ZWNrLl9ibF9idG4pCgoKY2xhc3MgRGljZUdseXBoKFFXaWRnZXQpOgogICAgIiIiU2ltcGxlIDJE"
    "IHNpbGhvdWV0dGUgcmVuZGVyZXIgZm9yIGRpZS10eXBlIHJlY29nbml0aW9uLiIiIgogICAgZGVm"
    "IF9faW5pdF9fKHNlbGYsIGRpZV90eXBlOiBzdHIgPSAiZDIwIiwgcGFyZW50PU5vbmUpOgogICAg"
    "ICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2RpZV90eXBlID0gZGll"
    "X3R5cGUKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDcwLCA3MCkKICAgICAgICBzZWxmLnNl"
    "dE1heGltdW1TaXplKDkwLCA5MCkKCiAgICBkZWYgc2V0X2RpZV90eXBlKHNlbGYsIGRpZV90eXBl"
    "OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZGllX3R5cGUgPSBkaWVfdHlwZQogICAgICAg"
    "IHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCk6CiAgICAgICAg"
    "cGFpbnRlciA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcGFpbnRlci5zZXRSZW5kZXJIaW50KFFQ"
    "YWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHJlY3QgPSBzZWxmLnJlY3Qo"
    "KS5hZGp1c3RlZCg4LCA4LCAtOCwgLTgpCgogICAgICAgIGRpZSA9IHNlbGYuX2RpZV90eXBlCiAg"
    "ICAgICAgbGluZSA9IFFDb2xvcihDX0dPTEQpCiAgICAgICAgZmlsbCA9IFFDb2xvcihDX0JHMikK"
    "ICAgICAgICBhY2NlbnQgPSBRQ29sb3IoQ19DUklNU09OKQoKICAgICAgICBwYWludGVyLnNldFBl"
    "bihRUGVuKGxpbmUsIDIpKQogICAgICAgIHBhaW50ZXIuc2V0QnJ1c2goZmlsbCkKCiAgICAgICAg"
    "cHRzID0gW10KICAgICAgICBpZiBkaWUgPT0gImQ0IjoKICAgICAgICAgICAgcHRzID0gWwogICAg"
    "ICAgICAgICAgICAgUVBvaW50KHJlY3QuY2VudGVyKCkueCgpLCByZWN0LnRvcCgpKSwKICAgICAg"
    "ICAgICAgICAgIFFQb2ludChyZWN0LmxlZnQoKSwgcmVjdC5ib3R0b20oKSksCiAgICAgICAgICAg"
    "ICAgICBRUG9pbnQocmVjdC5yaWdodCgpLCByZWN0LmJvdHRvbSgpKSwKICAgICAgICAgICAgXQog"
    "ICAgICAgIGVsaWYgZGllID09ICJkNiI6CiAgICAgICAgICAgIHBhaW50ZXIuZHJhd1JvdW5kZWRS"
    "ZWN0KHJlY3QsIDQsIDQpCiAgICAgICAgZWxpZiBkaWUgPT0gImQ4IjoKICAgICAgICAgICAgcHRz"
    "ID0gWwogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QuY2VudGVyKCkueCgpLCByZWN0LnRvcCgp"
    "KSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmxlZnQoKSwgcmVjdC5jZW50ZXIoKS55KCkp"
    "LAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QuY2VudGVyKCkueCgpLCByZWN0LmJvdHRvbSgp"
    "KSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LnJpZ2h0KCksIHJlY3QuY2VudGVyKCkueSgp"
    "KSwKICAgICAgICAgICAgXQogICAgICAgIGVsaWYgZGllIGluICgiZDEwIiwgImQxMDAiKToKICAg"
    "ICAgICAgICAgcHRzID0gWwogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QuY2VudGVyKCkueCgp"
    "LCByZWN0LnRvcCgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmxlZnQoKSArIDgsIHJl"
    "Y3QudG9wKCkgKyAxNiksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5sZWZ0KCksIHJlY3Qu"
    "Ym90dG9tKCkgLSAxMiksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCks"
    "IHJlY3QuYm90dG9tKCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QucmlnaHQoKSwgcmVj"
    "dC5ib3R0b20oKSAtIDEyKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LnJpZ2h0KCkgLSA4"
    "LCByZWN0LnRvcCgpICsgMTYpLAogICAgICAgICAgICBdCiAgICAgICAgZWxpZiBkaWUgPT0gImQx"
    "MiI6CiAgICAgICAgICAgIGN4ID0gcmVjdC5jZW50ZXIoKS54KCk7IGN5ID0gcmVjdC5jZW50ZXIo"
    "KS55KCkKICAgICAgICAgICAgcnggPSByZWN0LndpZHRoKCkgLyAyOyByeSA9IHJlY3QuaGVpZ2h0"
    "KCkgLyAyCiAgICAgICAgICAgIGZvciBpIGluIHJhbmdlKDUpOgogICAgICAgICAgICAgICAgYSA9"
    "IChtYXRoLnBpICogMiAqIGkgLyA1KSAtIChtYXRoLnBpIC8gMikKICAgICAgICAgICAgICAgIHB0"
    "cy5hcHBlbmQoUVBvaW50KGludChjeCArIHJ4ICogbWF0aC5jb3MoYSkpLCBpbnQoY3kgKyByeSAq"
    "IG1hdGguc2luKGEpKSkpCiAgICAgICAgZWxzZTogICMgZDIwCiAgICAgICAgICAgIHB0cyA9IFsK"
    "ICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC50b3AoKSksCiAg"
    "ICAgICAgICAgICAgICBRUG9pbnQocmVjdC5sZWZ0KCkgKyAxMCwgcmVjdC50b3AoKSArIDE0KSwK"
    "ICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmxlZnQoKSwgcmVjdC5jZW50ZXIoKS55KCkpLAog"
    "ICAgICAgICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpICsgMTAsIHJlY3QuYm90dG9tKCkgLSAx"
    "NCksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJlY3QuYm90dG9t"
    "KCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QucmlnaHQoKSAtIDEwLCByZWN0LmJvdHRv"
    "bSgpIC0gMTQpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QucmlnaHQoKSwgcmVjdC5jZW50"
    "ZXIoKS55KCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QucmlnaHQoKSAtIDEwLCByZWN0"
    "LnRvcCgpICsgMTQpLAogICAgICAgICAgICBdCgogICAgICAgIGlmIHB0czoKICAgICAgICAgICAg"
    "cGF0aCA9IFFQYWludGVyUGF0aCgpCiAgICAgICAgICAgIHBhdGgubW92ZVRvKHB0c1swXSkKICAg"
    "ICAgICAgICAgZm9yIHAgaW4gcHRzWzE6XToKICAgICAgICAgICAgICAgIHBhdGgubGluZVRvKHAp"
    "CiAgICAgICAgICAgIHBhdGguY2xvc2VTdWJwYXRoKCkKICAgICAgICAgICAgcGFpbnRlci5kcmF3"
    "UGF0aChwYXRoKQoKICAgICAgICBwYWludGVyLnNldFBlbihRUGVuKGFjY2VudCwgMSkpCiAgICAg"
    "ICAgdHh0ID0gIiUiIGlmIGRpZSA9PSAiZDEwMCIgZWxzZSBkaWUucmVwbGFjZSgiZCIsICIiKQog"
    "ICAgICAgIHBhaW50ZXIuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDEyLCBRRm9udC5XZWlnaHQu"
    "Qm9sZCkpCiAgICAgICAgcGFpbnRlci5kcmF3VGV4dChyZWN0LCBRdC5BbGlnbm1lbnRGbGFnLkFs"
    "aWduQ2VudGVyLCB0eHQpCgoKY2xhc3MgRGljZVRyYXlEaWUoUUZyYW1lKToKICAgIHNpbmdsZUNs"
    "aWNrZWQgPSBTaWduYWwoc3RyKQogICAgZG91YmxlQ2xpY2tlZCA9IFNpZ25hbChzdHIpCgogICAg"
    "ZGVmIF9faW5pdF9fKHNlbGYsIGRpZV90eXBlOiBzdHIsIGRpc3BsYXlfbGFiZWw6IHN0ciwgcGFy"
    "ZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYu"
    "ZGllX3R5cGUgPSBkaWVfdHlwZQogICAgICAgIHNlbGYuZGlzcGxheV9sYWJlbCA9IGRpc3BsYXlf"
    "bGFiZWwKICAgICAgICBzZWxmLl9jbGlja190aW1lciA9IFFUaW1lcihzZWxmKQogICAgICAgIHNl"
    "bGYuX2NsaWNrX3RpbWVyLnNldFNpbmdsZVNob3QoVHJ1ZSkKICAgICAgICBzZWxmLl9jbGlja190"
    "aW1lci5zZXRJbnRlcnZhbCgyMjApCiAgICAgICAgc2VsZi5fY2xpY2tfdGltZXIudGltZW91dC5j"
    "b25uZWN0KHNlbGYuX2VtaXRfc2luZ2xlKQoKICAgICAgICBzZWxmLnNldE9iamVjdE5hbWUoIkRp"
    "Y2VUcmF5RGllIikKICAgICAgICBzZWxmLnNldEN1cnNvcihRdC5DdXJzb3JTaGFwZS5Qb2ludGlu"
    "Z0hhbmRDdXJzb3IpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmIlFG"
    "cmFtZSNEaWNlVHJheURpZSB7eyBiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXI6IDFweCBzb2xp"
    "ZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiA4cHg7IH19IgogICAgICAgICAgICBmIlFGcmFt"
    "ZSNEaWNlVHJheURpZTpob3ZlciB7eyBib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEfTsgfX0iCiAg"
    "ICAgICAgKQoKICAgICAgICBsYXkgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheS5zZXRD"
    "b250ZW50c01hcmdpbnMoNiwgNiwgNiwgNikKICAgICAgICBsYXkuc2V0U3BhY2luZygyKQoKICAg"
    "ICAgICBnbHlwaF9kaWUgPSAiZDEwMCIgaWYgZGllX3R5cGUgPT0gImQlIiBlbHNlIGRpZV90eXBl"
    "CiAgICAgICAgc2VsZi5nbHlwaCA9IERpY2VHbHlwaChnbHlwaF9kaWUpCiAgICAgICAgc2VsZi5n"
    "bHlwaC5zZXRGaXhlZFNpemUoNTQsIDU0KQogICAgICAgIHNlbGYuZ2x5cGguc2V0QXR0cmlidXRl"
    "KFF0LldpZGdldEF0dHJpYnV0ZS5XQV9UcmFuc3BhcmVudEZvck1vdXNlRXZlbnRzLCBUcnVlKQoK"
    "ICAgICAgICBzZWxmLmxibCA9IFFMYWJlbChkaXNwbGF5X2xhYmVsKQogICAgICAgIHNlbGYubGJs"
    "LnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIHNlbGYu"
    "bGJsLnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfVEVYVH07IGZvbnQtd2VpZ2h0OiBib2xkOyIp"
    "CiAgICAgICAgc2VsZi5sYmwuc2V0QXR0cmlidXRlKFF0LldpZGdldEF0dHJpYnV0ZS5XQV9UcmFu"
    "c3BhcmVudEZvck1vdXNlRXZlbnRzLCBUcnVlKQoKICAgICAgICBsYXkuYWRkV2lkZ2V0KHNlbGYu"
    "Z2x5cGgsIDAsIFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgbGF5LmFkZFdp"
    "ZGdldChzZWxmLmxibCkKCiAgICBkZWYgbW91c2VQcmVzc0V2ZW50KHNlbGYsIGV2ZW50KToKICAg"
    "ICAgICBpZiBldmVudC5idXR0b24oKSA9PSBRdC5Nb3VzZUJ1dHRvbi5MZWZ0QnV0dG9uOgogICAg"
    "ICAgICAgICBpZiBzZWxmLl9jbGlja190aW1lci5pc0FjdGl2ZSgpOgogICAgICAgICAgICAgICAg"
    "c2VsZi5fY2xpY2tfdGltZXIuc3RvcCgpCiAgICAgICAgICAgICAgICBzZWxmLmRvdWJsZUNsaWNr"
    "ZWQuZW1pdChzZWxmLmRpZV90eXBlKQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAg"
    "c2VsZi5fY2xpY2tfdGltZXIuc3RhcnQoKQogICAgICAgICAgICBldmVudC5hY2NlcHQoKQogICAg"
    "ICAgICAgICByZXR1cm4KICAgICAgICBzdXBlcigpLm1vdXNlUHJlc3NFdmVudChldmVudCkKCiAg"
    "ICBkZWYgX2VtaXRfc2luZ2xlKHNlbGYpOgogICAgICAgIHNlbGYuc2luZ2xlQ2xpY2tlZC5lbWl0"
    "KHNlbGYuZGllX3R5cGUpCgoKY2xhc3MgRGljZVJvbGxlclRhYihRV2lkZ2V0KToKICAgICIiIkRl"
    "Y2stbmF0aXZlIERpY2UgUm9sbGVyIG1vZHVsZSB0YWIgd2l0aCB0cmF5L3Bvb2wgd29ya2Zsb3cg"
    "YW5kIHN0cnVjdHVyZWQgcm9sbCBldmVudHMuIiIiCgogICAgVFJBWV9PUkRFUiA9IFsiZDQiLCAi"
    "ZDYiLCAiZDgiLCAiZDEwIiwgImQxMiIsICJkMjAiLCAiZCUiXQoKICAgIGRlZiBfX2luaXRfXyhz"
    "ZWxmLCBkaWFnbm9zdGljc19sb2dnZXI9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygp"
    "CiAgICAgICAgc2VsZi5fbG9nID0gZGlhZ25vc3RpY3NfbG9nZ2VyIG9yIChsYW1iZGEgKl9hcmdz"
    "LCAqKl9rd2FyZ3M6IE5vbmUpCgogICAgICAgIHNlbGYucm9sbF9ldmVudHM6IGxpc3RbZGljdF0g"
    "PSBbXQogICAgICAgIHNlbGYuc2F2ZWRfcm9sbHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNl"
    "bGYuY29tbW9uX3JvbGxzOiBkaWN0W3N0ciwgZGljdF0gPSB7fQogICAgICAgIHNlbGYuZXZlbnRf"
    "YnlfaWQ6IGRpY3Rbc3RyLCBkaWN0XSA9IHt9CiAgICAgICAgc2VsZi5jdXJyZW50X3Bvb2w6IGRp"
    "Y3Rbc3RyLCBpbnRdID0ge30KICAgICAgICBzZWxmLmN1cnJlbnRfcm9sbF9pZHM6IGxpc3Rbc3Ry"
    "XSA9IFtdCgogICAgICAgIHNlbGYucnVsZV9kZWZpbml0aW9uczogZGljdFtzdHIsIGRpY3RdID0g"
    "ewogICAgICAgICAgICAicnVsZV80ZDZfZHJvcF9sb3dlc3QiOiB7CiAgICAgICAgICAgICAgICAi"
    "aWQiOiAicnVsZV80ZDZfZHJvcF9sb3dlc3QiLAogICAgICAgICAgICAgICAgIm5hbWUiOiAiRCZE"
    "IDVlIFN0YXQgUm9sbCIsCiAgICAgICAgICAgICAgICAiZGljZV9jb3VudCI6IDQsCiAgICAgICAg"
    "ICAgICAgICAiZGljZV9zaWRlcyI6IDYsCiAgICAgICAgICAgICAgICAiZHJvcF9sb3dlc3RfY291"
    "bnQiOiAxLAogICAgICAgICAgICAgICAgImRyb3BfaGlnaGVzdF9jb3VudCI6IDAsCiAgICAgICAg"
    "ICAgICAgICAibm90ZXMiOiAiUm9sbCA0ZDYsIGRyb3AgbG93ZXN0IG9uZS4iCiAgICAgICAgICAg"
    "IH0sCiAgICAgICAgICAgICJydWxlXzNkNl9zdHJhaWdodCI6IHsKICAgICAgICAgICAgICAgICJp"
    "ZCI6ICJydWxlXzNkNl9zdHJhaWdodCIsCiAgICAgICAgICAgICAgICAibmFtZSI6ICIzZDYgU3Ry"
    "YWlnaHQiLAogICAgICAgICAgICAgICAgImRpY2VfY291bnQiOiAzLAogICAgICAgICAgICAgICAg"
    "ImRpY2Vfc2lkZXMiOiA2LAogICAgICAgICAgICAgICAgImRyb3BfbG93ZXN0X2NvdW50IjogMCwK"
    "ICAgICAgICAgICAgICAgICJkcm9wX2hpZ2hlc3RfY291bnQiOiAwLAogICAgICAgICAgICAgICAg"
    "Im5vdGVzIjogIkNsYXNzaWMgM2Q2IHJvbGwuIgogICAgICAgICAgICB9LAogICAgICAgIH0KCiAg"
    "ICAgICAgc2VsZi5fYnVpbGRfdWkoKQogICAgICAgIHNlbGYuX3JlZnJlc2hfcG9vbF9lZGl0b3Io"
    "KQogICAgICAgIHNlbGYuX3JlZnJlc2hfc2F2ZWRfbGlzdHMoKQoKICAgIGRlZiBfYnVpbGRfdWko"
    "c2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBy"
    "b290LnNldENvbnRlbnRzTWFyZ2lucyg4LCA4LCA4LCA4KQogICAgICAgIHJvb3Quc2V0U3BhY2lu"
    "Zyg2KQoKICAgICAgICB0cmF5X3dyYXAgPSBRRnJhbWUoKQogICAgICAgIHRyYXlfd3JhcC5zZXRT"
    "dHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9S"
    "REVSfTsiKQogICAgICAgIHRyYXlfbGF5b3V0ID0gUVZCb3hMYXlvdXQodHJheV93cmFwKQogICAg"
    "ICAgIHRyYXlfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg4LCA4LCA4LCA4KQogICAgICAgIHRy"
    "YXlfbGF5b3V0LnNldFNwYWNpbmcoNikKICAgICAgICB0cmF5X2xheW91dC5hZGRXaWRnZXQoUUxh"
    "YmVsKCJEaWNlIFRyYXkiKSkKCiAgICAgICAgdHJheV9yb3cgPSBRSEJveExheW91dCgpCiAgICAg"
    "ICAgdHJheV9yb3cuc2V0U3BhY2luZyg2KQogICAgICAgIGZvciBkaWUgaW4gc2VsZi5UUkFZX09S"
    "REVSOgogICAgICAgICAgICBibG9jayA9IERpY2VUcmF5RGllKGRpZSwgZGllKQogICAgICAgICAg"
    "ICBibG9jay5zaW5nbGVDbGlja2VkLmNvbm5lY3Qoc2VsZi5fYWRkX2RpZV90b19wb29sKQogICAg"
    "ICAgICAgICBibG9jay5kb3VibGVDbGlja2VkLmNvbm5lY3Qoc2VsZi5fcXVpY2tfcm9sbF9zaW5n"
    "bGVfZGllKQogICAgICAgICAgICB0cmF5X3Jvdy5hZGRXaWRnZXQoYmxvY2ssIDEpCiAgICAgICAg"
    "dHJheV9sYXlvdXQuYWRkTGF5b3V0KHRyYXlfcm93KQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHRy"
    "YXlfd3JhcCkKCiAgICAgICAgcG9vbF93cmFwID0gUUZyYW1lKCkKICAgICAgICBwb29sX3dyYXAu"
    "c2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtD"
    "X0JPUkRFUn07IikKICAgICAgICBwdyA9IFFWQm94TGF5b3V0KHBvb2xfd3JhcCkKICAgICAgICBw"
    "dy5zZXRDb250ZW50c01hcmdpbnMoOCwgOCwgOCwgOCkKICAgICAgICBwdy5zZXRTcGFjaW5nKDYp"
    "CgogICAgICAgIHB3LmFkZFdpZGdldChRTGFiZWwoIkN1cnJlbnQgUG9vbCIpKQogICAgICAgIHNl"
    "bGYucG9vbF9leHByX2xibCA9IFFMYWJlbCgiUG9vbDogKGVtcHR5KSIpCiAgICAgICAgc2VsZi5w"
    "b29sX2V4cHJfbGJsLnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfR09MRH07IGZvbnQtd2VpZ2h0"
    "OiBib2xkOyIpCiAgICAgICAgcHcuYWRkV2lkZ2V0KHNlbGYucG9vbF9leHByX2xibCkKCiAgICAg"
    "ICAgc2VsZi5wb29sX2VudHJpZXNfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5wb29s"
    "X2VudHJpZXNfbGF5b3V0ID0gUUhCb3hMYXlvdXQoc2VsZi5wb29sX2VudHJpZXNfd2lkZ2V0KQog"
    "ICAgICAgIHNlbGYucG9vbF9lbnRyaWVzX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwg"
    "MCwgMCkKICAgICAgICBzZWxmLnBvb2xfZW50cmllc19sYXlvdXQuc2V0U3BhY2luZyg2KQogICAg"
    "ICAgIHB3LmFkZFdpZGdldChzZWxmLnBvb2xfZW50cmllc193aWRnZXQpCgogICAgICAgIG1ldGFf"
    "cm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYubGFiZWxfZWRpdCA9IFFMaW5lRWRpdCgp"
    "OyBzZWxmLmxhYmVsX2VkaXQuc2V0UGxhY2Vob2xkZXJUZXh0KCJMYWJlbCAvIHB1cnBvc2UiKQog"
    "ICAgICAgIHNlbGYubW9kX3NwaW4gPSBRU3BpbkJveCgpOyBzZWxmLm1vZF9zcGluLnNldFJhbmdl"
    "KC05OTksIDk5OSk7IHNlbGYubW9kX3NwaW4uc2V0VmFsdWUoMCkKICAgICAgICBzZWxmLnJ1bGVf"
    "Y29tYm8gPSBRQ29tYm9Cb3goKTsgc2VsZi5ydWxlX2NvbWJvLmFkZEl0ZW0oIk1hbnVhbCBSb2xs"
    "IiwgIiIpCiAgICAgICAgZm9yIHJpZCwgbWV0YSBpbiBzZWxmLnJ1bGVfZGVmaW5pdGlvbnMuaXRl"
    "bXMoKToKICAgICAgICAgICAgc2VsZi5ydWxlX2NvbWJvLmFkZEl0ZW0obWV0YS5nZXQoIm5hbWUi"
    "LCByaWQpLCByaWQpCgogICAgICAgIGZvciB0aXRsZSwgdyBpbiAoKCJMYWJlbCIsIHNlbGYubGFi"
    "ZWxfZWRpdCksICgiTW9kaWZpZXIiLCBzZWxmLm1vZF9zcGluKSwgKCJSdWxlIiwgc2VsZi5ydWxl"
    "X2NvbWJvKSk6CiAgICAgICAgICAgIGNvbCA9IFFWQm94TGF5b3V0KCkKICAgICAgICAgICAgbGJs"
    "ID0gUUxhYmVsKHRpdGxlKQogICAgICAgICAgICBsYmwuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7"
    "Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyIpCiAgICAgICAgICAgIGNvbC5hZGRXaWRnZXQo"
    "bGJsKQogICAgICAgICAgICBjb2wuYWRkV2lkZ2V0KHcpCiAgICAgICAgICAgIG1ldGFfcm93LmFk"
    "ZExheW91dChjb2wsIDEpCiAgICAgICAgcHcuYWRkTGF5b3V0KG1ldGFfcm93KQoKICAgICAgICBh"
    "Y3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYucm9sbF9wb29sX2J0biA9IFFQdXNo"
    "QnV0dG9uKCJSb2xsIFBvb2wiKQogICAgICAgIHNlbGYucmVzZXRfcG9vbF9idG4gPSBRUHVzaEJ1"
    "dHRvbigiUmVzZXQgUG9vbCIpCiAgICAgICAgc2VsZi5zYXZlX3Bvb2xfYnRuID0gUVB1c2hCdXR0"
    "b24oIlNhdmUgUG9vbCIpCiAgICAgICAgYWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5yb2xsX3Bvb2xf"
    "YnRuKQogICAgICAgIGFjdGlvbnMuYWRkV2lkZ2V0KHNlbGYucmVzZXRfcG9vbF9idG4pCiAgICAg"
    "ICAgYWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5zYXZlX3Bvb2xfYnRuKQogICAgICAgIHB3LmFkZExh"
    "eW91dChhY3Rpb25zKQoKICAgICAgICByb290LmFkZFdpZGdldChwb29sX3dyYXApCgogICAgICAg"
    "IHJlc3VsdF93cmFwID0gUUZyYW1lKCkKICAgICAgICByZXN1bHRfd3JhcC5zZXRTdHlsZVNoZWV0"
    "KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsiKQog"
    "ICAgICAgIHJsID0gUVZCb3hMYXlvdXQocmVzdWx0X3dyYXApCiAgICAgICAgcmwuc2V0Q29udGVu"
    "dHNNYXJnaW5zKDgsIDgsIDgsIDgpCiAgICAgICAgcmwuYWRkV2lkZ2V0KFFMYWJlbCgiQ3VycmVu"
    "dCBSZXN1bHQiKSkKICAgICAgICBzZWxmLmN1cnJlbnRfcmVzdWx0X2xibCA9IFFMYWJlbCgiTm8g"
    "cm9sbCB5ZXQuIikKICAgICAgICBzZWxmLmN1cnJlbnRfcmVzdWx0X2xibC5zZXRXb3JkV3JhcChU"
    "cnVlKQogICAgICAgIHJsLmFkZFdpZGdldChzZWxmLmN1cnJlbnRfcmVzdWx0X2xibCkKICAgICAg"
    "ICByb290LmFkZFdpZGdldChyZXN1bHRfd3JhcCkKCiAgICAgICAgbWlkID0gUUhCb3hMYXlvdXQo"
    "KQogICAgICAgIGhpc3Rvcnlfd3JhcCA9IFFGcmFtZSgpCiAgICAgICAgaGlzdG9yeV93cmFwLnNl"
    "dFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19C"
    "T1JERVJ9OyIpCiAgICAgICAgaHcgPSBRVkJveExheW91dChoaXN0b3J5X3dyYXApCiAgICAgICAg"
    "aHcuc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCgogICAgICAgIHNlbGYuaGlzdG9yeV90"
    "YWJzID0gUVRhYldpZGdldCgpCiAgICAgICAgc2VsZi5jdXJyZW50X3RhYmxlID0gc2VsZi5fbWFr"
    "ZV9yb2xsX3RhYmxlKCkKICAgICAgICBzZWxmLmhpc3RvcnlfdGFibGUgPSBzZWxmLl9tYWtlX3Jv"
    "bGxfdGFibGUoKQogICAgICAgIHNlbGYuaGlzdG9yeV90YWJzLmFkZFRhYihzZWxmLmN1cnJlbnRf"
    "dGFibGUsICJDdXJyZW50IFJvbGxzIikKICAgICAgICBzZWxmLmhpc3RvcnlfdGFicy5hZGRUYWIo"
    "c2VsZi5oaXN0b3J5X3RhYmxlLCAiUm9sbCBIaXN0b3J5IikKICAgICAgICBody5hZGRXaWRnZXQo"
    "c2VsZi5oaXN0b3J5X3RhYnMsIDEpCgogICAgICAgIGhpc3RvcnlfYWN0aW9ucyA9IFFIQm94TGF5"
    "b3V0KCkKICAgICAgICBzZWxmLmNsZWFyX2hpc3RvcnlfYnRuID0gUVB1c2hCdXR0b24oIkNsZWFy"
    "IFJvbGwgSGlzdG9yeSIpCiAgICAgICAgaGlzdG9yeV9hY3Rpb25zLmFkZFdpZGdldChzZWxmLmNs"
    "ZWFyX2hpc3RvcnlfYnRuKQogICAgICAgIGhpc3RvcnlfYWN0aW9ucy5hZGRTdHJldGNoKDEpCiAg"
    "ICAgICAgaHcuYWRkTGF5b3V0KGhpc3RvcnlfYWN0aW9ucykKCiAgICAgICAgc2VsZi5ncmFuZF90"
    "b3RhbF9sYmwgPSBRTGFiZWwoIkdyYW5kIFRvdGFsOiAwIikKICAgICAgICBzZWxmLmdyYW5kX3Rv"
    "dGFsX2xibC5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDEycHg7"
    "IGZvbnQtd2VpZ2h0OiBib2xkOyIpCiAgICAgICAgaHcuYWRkV2lkZ2V0KHNlbGYuZ3JhbmRfdG90"
    "YWxfbGJsKQoKICAgICAgICBzYXZlZF93cmFwID0gUUZyYW1lKCkKICAgICAgICBzYXZlZF93cmFw"
    "LnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7"
    "Q19CT1JERVJ9OyIpCiAgICAgICAgc3cgPSBRVkJveExheW91dChzYXZlZF93cmFwKQogICAgICAg"
    "IHN3LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQogICAgICAgIHN3LmFkZFdpZGdldChR"
    "TGFiZWwoIlNhdmVkIC8gQ29tbW9uIFJvbGxzIikpCgogICAgICAgIHN3LmFkZFdpZGdldChRTGFi"
    "ZWwoIlNhdmVkIikpCiAgICAgICAgc2VsZi5zYXZlZF9saXN0ID0gUUxpc3RXaWRnZXQoKQogICAg"
    "ICAgIHN3LmFkZFdpZGdldChzZWxmLnNhdmVkX2xpc3QsIDEpCiAgICAgICAgc2F2ZWRfYWN0aW9u"
    "cyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLnJ1bl9zYXZlZF9idG4gPSBRUHVzaEJ1dHRv"
    "bigiUnVuIikKICAgICAgICBzZWxmLmxvYWRfc2F2ZWRfYnRuID0gUVB1c2hCdXR0b24oIkxvYWQv"
    "RWRpdCIpCiAgICAgICAgc2VsZi5kZWxldGVfc2F2ZWRfYnRuID0gUVB1c2hCdXR0b24oIkRlbGV0"
    "ZSIpCiAgICAgICAgc2F2ZWRfYWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5ydW5fc2F2ZWRfYnRuKQog"
    "ICAgICAgIHNhdmVkX2FjdGlvbnMuYWRkV2lkZ2V0KHNlbGYubG9hZF9zYXZlZF9idG4pCiAgICAg"
    "ICAgc2F2ZWRfYWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5kZWxldGVfc2F2ZWRfYnRuKQogICAgICAg"
    "IHN3LmFkZExheW91dChzYXZlZF9hY3Rpb25zKQoKICAgICAgICBzdy5hZGRXaWRnZXQoUUxhYmVs"
    "KCJBdXRvLURldGVjdGVkIENvbW1vbiIpKQogICAgICAgIHNlbGYuY29tbW9uX2xpc3QgPSBRTGlz"
    "dFdpZGdldCgpCiAgICAgICAgc3cuYWRkV2lkZ2V0KHNlbGYuY29tbW9uX2xpc3QsIDEpCiAgICAg"
    "ICAgY29tbW9uX2FjdGlvbnMgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5wcm9tb3RlX2Nv"
    "bW1vbl9idG4gPSBRUHVzaEJ1dHRvbigiUHJvbW90ZSB0byBTYXZlZCIpCiAgICAgICAgc2VsZi5k"
    "aXNtaXNzX2NvbW1vbl9idG4gPSBRUHVzaEJ1dHRvbigiRGlzbWlzcyIpCiAgICAgICAgY29tbW9u"
    "X2FjdGlvbnMuYWRkV2lkZ2V0KHNlbGYucHJvbW90ZV9jb21tb25fYnRuKQogICAgICAgIGNvbW1v"
    "bl9hY3Rpb25zLmFkZFdpZGdldChzZWxmLmRpc21pc3NfY29tbW9uX2J0bikKICAgICAgICBzdy5h"
    "ZGRMYXlvdXQoY29tbW9uX2FjdGlvbnMpCgogICAgICAgIHNlbGYuY29tbW9uX2hpbnQgPSBRTGFi"
    "ZWwoIkNvbW1vbiBzaWduYXR1cmUgdHJhY2tpbmcgYWN0aXZlLiIpCiAgICAgICAgc2VsZi5jb21t"
    "b25faGludC5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5"
    "cHg7IikKICAgICAgICBzdy5hZGRXaWRnZXQoc2VsZi5jb21tb25faGludCkKCiAgICAgICAgbWlk"
    "LmFkZFdpZGdldChoaXN0b3J5X3dyYXAsIDMpCiAgICAgICAgbWlkLmFkZFdpZGdldChzYXZlZF93"
    "cmFwLCAyKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KG1pZCwgMSkKCiAgICAgICAgc2VsZi5yb2xs"
    "X3Bvb2xfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9yb2xsX2N1cnJlbnRfcG9vbCkKICAgICAg"
    "ICBzZWxmLnJlc2V0X3Bvb2xfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9yZXNldF9wb29sKQog"
    "ICAgICAgIHNlbGYuc2F2ZV9wb29sX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2F2ZV9wb29s"
    "KQogICAgICAgIHNlbGYuY2xlYXJfaGlzdG9yeV9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Ns"
    "ZWFyX2hpc3RvcnkpCgogICAgICAgIHNlbGYuc2F2ZWRfbGlzdC5pdGVtRG91YmxlQ2xpY2tlZC5j"
    "b25uZWN0KGxhbWJkYSBpdGVtOiBzZWxmLl9ydW5fc2F2ZWRfcm9sbChpdGVtLmRhdGEoUXQuSXRl"
    "bURhdGFSb2xlLlVzZXJSb2xlKSkpCiAgICAgICAgc2VsZi5jb21tb25fbGlzdC5pdGVtRG91Ymxl"
    "Q2xpY2tlZC5jb25uZWN0KGxhbWJkYSBpdGVtOiBzZWxmLl9ydW5fc2F2ZWRfcm9sbChpdGVtLmRh"
    "dGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKSkpCgogICAgICAgIHNlbGYucnVuX3NhdmVkX2J0"
    "bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fcnVuX3NlbGVjdGVkX3NhdmVkKQogICAgICAgIHNlbGYu"
    "bG9hZF9zYXZlZF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2xvYWRfc2VsZWN0ZWRfc2F2ZWQp"
    "CiAgICAgICAgc2VsZi5kZWxldGVfc2F2ZWRfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kZWxl"
    "dGVfc2VsZWN0ZWRfc2F2ZWQpCiAgICAgICAgc2VsZi5wcm9tb3RlX2NvbW1vbl9idG4uY2xpY2tl"
    "ZC5jb25uZWN0KHNlbGYuX3Byb21vdGVfc2VsZWN0ZWRfY29tbW9uKQogICAgICAgIHNlbGYuZGlz"
    "bWlzc19jb21tb25fYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kaXNtaXNzX3NlbGVjdGVkX2Nv"
    "bW1vbikKCiAgICAgICAgc2VsZi5jdXJyZW50X3RhYmxlLnNldENvbnRleHRNZW51UG9saWN5KFF0"
    "LkNvbnRleHRNZW51UG9saWN5LkN1c3RvbUNvbnRleHRNZW51KQogICAgICAgIHNlbGYuaGlzdG9y"
    "eV90YWJsZS5zZXRDb250ZXh0TWVudVBvbGljeShRdC5Db250ZXh0TWVudVBvbGljeS5DdXN0b21D"
    "b250ZXh0TWVudSkKICAgICAgICBzZWxmLmN1cnJlbnRfdGFibGUuY3VzdG9tQ29udGV4dE1lbnVS"
    "ZXF1ZXN0ZWQuY29ubmVjdChsYW1iZGEgcG9zOiBzZWxmLl9zaG93X3JvbGxfY29udGV4dF9tZW51"
    "KHNlbGYuY3VycmVudF90YWJsZSwgcG9zKSkKICAgICAgICBzZWxmLmhpc3RvcnlfdGFibGUuY3Vz"
    "dG9tQ29udGV4dE1lbnVSZXF1ZXN0ZWQuY29ubmVjdChsYW1iZGEgcG9zOiBzZWxmLl9zaG93X3Jv"
    "bGxfY29udGV4dF9tZW51KHNlbGYuaGlzdG9yeV90YWJsZSwgcG9zKSkKCiAgICBkZWYgX21ha2Vf"
    "cm9sbF90YWJsZShzZWxmKSAtPiBRVGFibGVXaWRnZXQ6CiAgICAgICAgdGJsID0gUVRhYmxlV2lk"
    "Z2V0KDAsIDYpCiAgICAgICAgdGJsLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJUaW1lc3Rh"
    "bXAiLCAiTGFiZWwiLCAiRXhwcmVzc2lvbiIsICJSYXciLCAiTW9kaWZpZXIiLCAiVG90YWwiXSkK"
    "ICAgICAgICB0YmwuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKFFIZWFk"
    "ZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICB0YmwudmVydGljYWxIZWFkZXIoKS5z"
    "ZXRWaXNpYmxlKEZhbHNlKQogICAgICAgIHRibC5zZXRFZGl0VHJpZ2dlcnMoUUFic3RyYWN0SXRl"
    "bVZpZXcuRWRpdFRyaWdnZXIuTm9FZGl0VHJpZ2dlcnMpCiAgICAgICAgdGJsLnNldFNlbGVjdGlv"
    "bkJlaGF2aW9yKFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3Mp"
    "CiAgICAgICAgdGJsLnNldFNvcnRpbmdFbmFibGVkKEZhbHNlKQogICAgICAgIHJldHVybiB0YmwK"
    "CiAgICBkZWYgX3NvcnRlZF9wb29sX2l0ZW1zKHNlbGYpOgogICAgICAgIHJldHVybiBbKGQsIHNl"
    "bGYuY3VycmVudF9wb29sLmdldChkLCAwKSkgZm9yIGQgaW4gc2VsZi5UUkFZX09SREVSIGlmIHNl"
    "bGYuY3VycmVudF9wb29sLmdldChkLCAwKSA+IDBdCgogICAgZGVmIF9wb29sX2V4cHJlc3Npb24o"
    "c2VsZiwgcG9vbDogZGljdFtzdHIsIGludF0gfCBOb25lID0gTm9uZSkgLT4gc3RyOgogICAgICAg"
    "IHAgPSBwb29sIGlmIHBvb2wgaXMgbm90IE5vbmUgZWxzZSBzZWxmLmN1cnJlbnRfcG9vbAogICAg"
    "ICAgIHBhcnRzID0gW2Yie3F0eX17ZGllfSIgZm9yIGRpZSwgcXR5IGluIFsoZCwgcC5nZXQoZCwg"
    "MCkpIGZvciBkIGluIHNlbGYuVFJBWV9PUkRFUl0gaWYgcXR5ID4gMF0KICAgICAgICByZXR1cm4g"
    "IiArICIuam9pbihwYXJ0cykgaWYgcGFydHMgZWxzZSAiKGVtcHR5KSIKCiAgICBkZWYgX25vcm1h"
    "bGl6ZV9wb29sX3NpZ25hdHVyZShzZWxmLCBwb29sOiBkaWN0W3N0ciwgaW50XSwgbW9kaWZpZXI6"
    "IGludCwgcnVsZV9pZDogc3RyID0gIiIpIC0+IHN0cjoKICAgICAgICBwYXJ0cyA9IFtmIntwb29s"
    "LmdldChkLCAwKX17ZH0iIGZvciBkIGluIHNlbGYuVFJBWV9PUkRFUiBpZiBwb29sLmdldChkLCAw"
    "KSA+IDBdCiAgICAgICAgYmFzZSA9ICIrIi5qb2luKHBhcnRzKSBpZiBwYXJ0cyBlbHNlICIwIgog"
    "ICAgICAgIHNpZyA9IGYie2Jhc2V9e21vZGlmaWVyOitkfSIKICAgICAgICByZXR1cm4gZiJ7c2ln"
    "fV97cnVsZV9pZH0iIGlmIHJ1bGVfaWQgZWxzZSBzaWcKCiAgICBkZWYgX2RpY2VfbGFiZWwoc2Vs"
    "ZiwgZGllX3R5cGU6IHN0cikgLT4gc3RyOgogICAgICAgIHJldHVybiAiZCUiIGlmIGRpZV90eXBl"
    "ID09ICJkJSIgZWxzZSBkaWVfdHlwZQoKICAgIGRlZiBfcm9sbF9zaW5nbGVfdmFsdWUoc2VsZiwg"
    "ZGllX3R5cGU6IHN0cik6CiAgICAgICAgaWYgZGllX3R5cGUgPT0gImQlIjoKICAgICAgICAgICAg"
    "dGVucyA9IHJhbmRvbS5yYW5kaW50KDAsIDkpICogMTAKICAgICAgICAgICAgcmV0dXJuIHRlbnMs"
    "ICgiMDAiIGlmIHRlbnMgPT0gMCBlbHNlIHN0cih0ZW5zKSkKICAgICAgICBzaWRlcyA9IGludChk"
    "aWVfdHlwZS5yZXBsYWNlKCJkIiwgIiIpKQogICAgICAgIHZhbCA9IHJhbmRvbS5yYW5kaW50KDEs"
    "IHNpZGVzKQogICAgICAgIHJldHVybiB2YWwsIHN0cih2YWwpCgogICAgZGVmIF9yb2xsX3Bvb2xf"
    "ZGF0YShzZWxmLCBwb29sOiBkaWN0W3N0ciwgaW50XSwgbW9kaWZpZXI6IGludCwgbGFiZWw6IHN0"
    "ciwgcnVsZV9pZDogc3RyID0gIiIpIC0+IGRpY3Q6CiAgICAgICAgZ3JvdXBlZF9udW1lcmljOiBk"
    "aWN0W3N0ciwgbGlzdFtpbnRdXSA9IHt9CiAgICAgICAgZ3JvdXBlZF9kaXNwbGF5OiBkaWN0W3N0"
    "ciwgbGlzdFtzdHJdXSA9IHt9CiAgICAgICAgc3VidG90YWwgPSAwCiAgICAgICAgdXNlZF9wb29s"
    "ID0gZGljdChwb29sKQoKICAgICAgICBpZiBydWxlX2lkIGFuZCBydWxlX2lkIGluIHNlbGYucnVs"
    "ZV9kZWZpbml0aW9ucyBhbmQgKG5vdCBwb29sIG9yIGxlbihbayBmb3IgaywgdiBpbiBwb29sLml0"
    "ZW1zKCkgaWYgdiA+IDBdKSA9PSAxKToKICAgICAgICAgICAgcnVsZSA9IHNlbGYucnVsZV9kZWZp"
    "bml0aW9ucy5nZXQocnVsZV9pZCwge30pCiAgICAgICAgICAgIHNpZGVzID0gaW50KHJ1bGUuZ2V0"
    "KCJkaWNlX3NpZGVzIiwgNikpCiAgICAgICAgICAgIGNvdW50ID0gaW50KHJ1bGUuZ2V0KCJkaWNl"
    "X2NvdW50IiwgMSkpCiAgICAgICAgICAgIGRpZSA9IGYiZHtzaWRlc30iCiAgICAgICAgICAgIHVz"
    "ZWRfcG9vbCA9IHtkaWU6IGNvdW50fQogICAgICAgICAgICByYXcgPSBbcmFuZG9tLnJhbmRpbnQo"
    "MSwgc2lkZXMpIGZvciBfIGluIHJhbmdlKGNvdW50KV0KICAgICAgICAgICAgZHJvcF9sb3cgPSBp"
    "bnQocnVsZS5nZXQoImRyb3BfbG93ZXN0X2NvdW50IiwgMCkgb3IgMCkKICAgICAgICAgICAgZHJv"
    "cF9oaWdoID0gaW50KHJ1bGUuZ2V0KCJkcm9wX2hpZ2hlc3RfY291bnQiLCAwKSBvciAwKQogICAg"
    "ICAgICAgICBrZXB0ID0gbGlzdChyYXcpCiAgICAgICAgICAgIGlmIGRyb3BfbG93ID4gMDoKICAg"
    "ICAgICAgICAgICAgIGtlcHQgPSBzb3J0ZWQoa2VwdClbZHJvcF9sb3c6XQogICAgICAgICAgICBp"
    "ZiBkcm9wX2hpZ2ggPiAwOgogICAgICAgICAgICAgICAga2VwdCA9IHNvcnRlZChrZXB0KVs6LWRy"
    "b3BfaGlnaF0gaWYgZHJvcF9oaWdoIDwgbGVuKGtlcHQpIGVsc2UgW10KICAgICAgICAgICAgZ3Jv"
    "dXBlZF9udW1lcmljW2RpZV0gPSByYXcKICAgICAgICAgICAgZ3JvdXBlZF9kaXNwbGF5W2RpZV0g"
    "PSBbc3RyKHYpIGZvciB2IGluIHJhd10KICAgICAgICAgICAgc3VidG90YWwgPSBzdW0oa2VwdCkK"
    "ICAgICAgICBlbHNlOgogICAgICAgICAgICBmb3IgZGllIGluIHNlbGYuVFJBWV9PUkRFUjoKICAg"
    "ICAgICAgICAgICAgIHF0eSA9IGludChwb29sLmdldChkaWUsIDApIG9yIDApCiAgICAgICAgICAg"
    "ICAgICBpZiBxdHkgPD0gMDoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAg"
    "ICAgICAgZ3JvdXBlZF9udW1lcmljW2RpZV0gPSBbXQogICAgICAgICAgICAgICAgZ3JvdXBlZF9k"
    "aXNwbGF5W2RpZV0gPSBbXQogICAgICAgICAgICAgICAgZm9yIF8gaW4gcmFuZ2UocXR5KToKICAg"
    "ICAgICAgICAgICAgICAgICBudW0sIGRpc3AgPSBzZWxmLl9yb2xsX3NpbmdsZV92YWx1ZShkaWUp"
    "CiAgICAgICAgICAgICAgICAgICAgZ3JvdXBlZF9udW1lcmljW2RpZV0uYXBwZW5kKG51bSkKICAg"
    "ICAgICAgICAgICAgICAgICBncm91cGVkX2Rpc3BsYXlbZGllXS5hcHBlbmQoZGlzcCkKICAgICAg"
    "ICAgICAgICAgICAgICBzdWJ0b3RhbCArPSBpbnQobnVtKQoKICAgICAgICB0b3RhbCA9IHN1YnRv"
    "dGFsICsgaW50KG1vZGlmaWVyKQogICAgICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUo"
    "IiVIOiVNOiVTIikKICAgICAgICBleHByID0gc2VsZi5fcG9vbF9leHByZXNzaW9uKHVzZWRfcG9v"
    "bCkKICAgICAgICBpZiBydWxlX2lkOgogICAgICAgICAgICBydWxlX25hbWUgPSBzZWxmLnJ1bGVf"
    "ZGVmaW5pdGlvbnMuZ2V0KHJ1bGVfaWQsIHt9KS5nZXQoIm5hbWUiLCBydWxlX2lkKQogICAgICAg"
    "ICAgICBleHByID0gZiJ7ZXhwcn0gKHtydWxlX25hbWV9KSIKCiAgICAgICAgZXZlbnQgPSB7CiAg"
    "ICAgICAgICAgICJpZCI6IGYicm9sbF97dXVpZC51dWlkNCgpLmhleFs6MTJdfSIsCiAgICAgICAg"
    "ICAgICJ0aW1lc3RhbXAiOiB0cywKICAgICAgICAgICAgImxhYmVsIjogbGFiZWwsCiAgICAgICAg"
    "ICAgICJwb29sIjogdXNlZF9wb29sLAogICAgICAgICAgICAiZ3JvdXBlZF9yYXciOiBncm91cGVk"
    "X251bWVyaWMsCiAgICAgICAgICAgICJncm91cGVkX3Jhd19kaXNwbGF5IjogZ3JvdXBlZF9kaXNw"
    "bGF5LAogICAgICAgICAgICAic3VidG90YWwiOiBzdWJ0b3RhbCwKICAgICAgICAgICAgIm1vZGlm"
    "aWVyIjogaW50KG1vZGlmaWVyKSwKICAgICAgICAgICAgImZpbmFsX3RvdGFsIjogaW50KHRvdGFs"
    "KSwKICAgICAgICAgICAgImV4cHJlc3Npb24iOiBleHByLAogICAgICAgICAgICAic291cmNlIjog"
    "ImRpY2Vfcm9sbGVyIiwKICAgICAgICAgICAgInJ1bGVfaWQiOiBydWxlX2lkIG9yIE5vbmUsCiAg"
    "ICAgICAgfQogICAgICAgIHJldHVybiBldmVudAoKICAgIGRlZiBfYWRkX2RpZV90b19wb29sKHNl"
    "bGYsIGRpZV90eXBlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5jdXJyZW50X3Bvb2xbZGll"
    "X3R5cGVdID0gaW50KHNlbGYuY3VycmVudF9wb29sLmdldChkaWVfdHlwZSwgMCkpICsgMQogICAg"
    "ICAgIHNlbGYuX3JlZnJlc2hfcG9vbF9lZGl0b3IoKQogICAgICAgIHNlbGYuY3VycmVudF9yZXN1"
    "bHRfbGJsLnNldFRleHQoZiJDdXJyZW50IFBvb2w6IHtzZWxmLl9wb29sX2V4cHJlc3Npb24oKX0i"
    "KQoKICAgIGRlZiBfYWRqdXN0X3Bvb2xfZGllKHNlbGYsIGRpZV90eXBlOiBzdHIsIGRlbHRhOiBp"
    "bnQpIC0+IE5vbmU6CiAgICAgICAgbmV3X3ZhbCA9IGludChzZWxmLmN1cnJlbnRfcG9vbC5nZXQo"
    "ZGllX3R5cGUsIDApKSArIGludChkZWx0YSkKICAgICAgICBpZiBuZXdfdmFsIDw9IDA6CiAgICAg"
    "ICAgICAgIHNlbGYuY3VycmVudF9wb29sLnBvcChkaWVfdHlwZSwgTm9uZSkKICAgICAgICBlbHNl"
    "OgogICAgICAgICAgICBzZWxmLmN1cnJlbnRfcG9vbFtkaWVfdHlwZV0gPSBuZXdfdmFsCiAgICAg"
    "ICAgc2VsZi5fcmVmcmVzaF9wb29sX2VkaXRvcigpCgogICAgZGVmIF9yZWZyZXNoX3Bvb2xfZWRp"
    "dG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgd2hpbGUgc2VsZi5wb29sX2VudHJpZXNfbGF5b3V0"
    "LmNvdW50KCk6CiAgICAgICAgICAgIGl0ZW0gPSBzZWxmLnBvb2xfZW50cmllc19sYXlvdXQudGFr"
    "ZUF0KDApCiAgICAgICAgICAgIHcgPSBpdGVtLndpZGdldCgpCiAgICAgICAgICAgIGlmIHcgaXMg"
    "bm90IE5vbmU6CiAgICAgICAgICAgICAgICB3LmRlbGV0ZUxhdGVyKCkKCiAgICAgICAgZm9yIGRp"
    "ZSwgcXR5IGluIHNlbGYuX3NvcnRlZF9wb29sX2l0ZW1zKCk6CiAgICAgICAgICAgIGJveCA9IFFG"
    "cmFtZSgpCiAgICAgICAgICAgIGJveC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcz"
    "fTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogNnB4OyIpCiAg"
    "ICAgICAgICAgIGxheSA9IFFIQm94TGF5b3V0KGJveCkKICAgICAgICAgICAgbGF5LnNldENvbnRl"
    "bnRzTWFyZ2lucyg2LCA0LCA2LCA0KQogICAgICAgICAgICBsYXkuc2V0U3BhY2luZyg0KQogICAg"
    "ICAgICAgICBsYmwgPSBRTGFiZWwoZiJ7ZGllfSB4e3F0eX0iKQogICAgICAgICAgICBtaW51c19i"
    "dG4gPSBRUHVzaEJ1dHRvbigi4oiSIikKICAgICAgICAgICAgcGx1c19idG4gPSBRUHVzaEJ1dHRv"
    "bigiKyIpCiAgICAgICAgICAgIG1pbnVzX2J0bi5zZXRGaXhlZFdpZHRoKDI0KQogICAgICAgICAg"
    "ICBwbHVzX2J0bi5zZXRGaXhlZFdpZHRoKDI0KQogICAgICAgICAgICBtaW51c19idG4uY2xpY2tl"
    "ZC5jb25uZWN0KGxhbWJkYSBfPUZhbHNlLCBkPWRpZTogc2VsZi5fYWRqdXN0X3Bvb2xfZGllKGQs"
    "IC0xKSkKICAgICAgICAgICAgcGx1c19idG4uY2xpY2tlZC5jb25uZWN0KGxhbWJkYSBfPUZhbHNl"
    "LCBkPWRpZTogc2VsZi5fYWRqdXN0X3Bvb2xfZGllKGQsICsxKSkKICAgICAgICAgICAgbGF5LmFk"
    "ZFdpZGdldChsYmwpCiAgICAgICAgICAgIGxheS5hZGRXaWRnZXQobWludXNfYnRuKQogICAgICAg"
    "ICAgICBsYXkuYWRkV2lkZ2V0KHBsdXNfYnRuKQogICAgICAgICAgICBzZWxmLnBvb2xfZW50cmll"
    "c19sYXlvdXQuYWRkV2lkZ2V0KGJveCkKCiAgICAgICAgc2VsZi5wb29sX2VudHJpZXNfbGF5b3V0"
    "LmFkZFN0cmV0Y2goMSkKICAgICAgICBzZWxmLnBvb2xfZXhwcl9sYmwuc2V0VGV4dChmIlBvb2w6"
    "IHtzZWxmLl9wb29sX2V4cHJlc3Npb24oKX0iKQoKICAgIGRlZiBfcXVpY2tfcm9sbF9zaW5nbGVf"
    "ZGllKHNlbGYsIGRpZV90eXBlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgZXZlbnQgPSBzZWxmLl9y"
    "b2xsX3Bvb2xfZGF0YSh7ZGllX3R5cGU6IDF9LCBpbnQoc2VsZi5tb2Rfc3Bpbi52YWx1ZSgpKSwg"
    "c2VsZi5sYWJlbF9lZGl0LnRleHQoKS5zdHJpcCgpLCBzZWxmLnJ1bGVfY29tYm8uY3VycmVudERh"
    "dGEoKSBvciAiIikKICAgICAgICBzZWxmLl9yZWNvcmRfcm9sbF9ldmVudChldmVudCkKCiAgICBk"
    "ZWYgX3JvbGxfY3VycmVudF9wb29sKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcG9vbCA9IGRpY3Qo"
    "c2VsZi5jdXJyZW50X3Bvb2wpCiAgICAgICAgcnVsZV9pZCA9IHNlbGYucnVsZV9jb21iby5jdXJy"
    "ZW50RGF0YSgpIG9yICIiCiAgICAgICAgaWYgbm90IHBvb2wgYW5kIG5vdCBydWxlX2lkOgogICAg"
    "ICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiRGljZSBSb2xsZXIiLCAiQ3Vy"
    "cmVudCBQb29sIGlzIGVtcHR5LiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGV2ZW50ID0g"
    "c2VsZi5fcm9sbF9wb29sX2RhdGEocG9vbCwgaW50KHNlbGYubW9kX3NwaW4udmFsdWUoKSksIHNl"
    "bGYubGFiZWxfZWRpdC50ZXh0KCkuc3RyaXAoKSwgcnVsZV9pZCkKICAgICAgICBzZWxmLl9yZWNv"
    "cmRfcm9sbF9ldmVudChldmVudCkKCiAgICBkZWYgX3JlY29yZF9yb2xsX2V2ZW50KHNlbGYsIGV2"
    "ZW50OiBkaWN0KSAtPiBOb25lOgogICAgICAgIHNlbGYucm9sbF9ldmVudHMuYXBwZW5kKGV2ZW50"
    "KQogICAgICAgIHNlbGYuZXZlbnRfYnlfaWRbZXZlbnRbImlkIl1dID0gZXZlbnQKICAgICAgICBz"
    "ZWxmLmN1cnJlbnRfcm9sbF9pZHMgPSBbZXZlbnRbImlkIl1dCgogICAgICAgIHNlbGYuX3JlcGxh"
    "Y2VfY3VycmVudF9yb3dzKFtldmVudF0pCiAgICAgICAgc2VsZi5fYXBwZW5kX2hpc3Rvcnlfcm93"
    "KGV2ZW50KQogICAgICAgIHNlbGYuX3VwZGF0ZV9ncmFuZF90b3RhbCgpCiAgICAgICAgc2VsZi5f"
    "dXBkYXRlX3Jlc3VsdF9kaXNwbGF5KGV2ZW50KQogICAgICAgIHNlbGYuX3RyYWNrX2NvbW1vbl9z"
    "aWduYXR1cmUoZXZlbnQpCiAgICAgICAgc2VsZi5fcGxheV9yb2xsX3NvdW5kKCkKCiAgICBkZWYg"
    "X3JlcGxhY2VfY3VycmVudF9yb3dzKHNlbGYsIGV2ZW50czogbGlzdFtkaWN0XSkgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLmN1cnJlbnRfdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgZXZl"
    "bnQgaW4gZXZlbnRzOgogICAgICAgICAgICBzZWxmLl9hcHBlbmRfdGFibGVfcm93KHNlbGYuY3Vy"
    "cmVudF90YWJsZSwgZXZlbnQpCgogICAgZGVmIF9hcHBlbmRfaGlzdG9yeV9yb3coc2VsZiwgZXZl"
    "bnQ6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXBwZW5kX3RhYmxlX3JvdyhzZWxmLmhp"
    "c3RvcnlfdGFibGUsIGV2ZW50KQogICAgICAgIHNlbGYuaGlzdG9yeV90YWJsZS5zY3JvbGxUb0Jv"
    "dHRvbSgpCgogICAgZGVmIF9mb3JtYXRfcmF3KHNlbGYsIGV2ZW50OiBkaWN0KSAtPiBzdHI6CiAg"
    "ICAgICAgZ3JvdXBlZCA9IGV2ZW50LmdldCgiZ3JvdXBlZF9yYXdfZGlzcGxheSIsIHt9KSBvciB7"
    "fQogICAgICAgIGJpdHMgPSBbXQogICAgICAgIGZvciBkaWUgaW4gc2VsZi5UUkFZX09SREVSOgog"
    "ICAgICAgICAgICB2YWxzID0gZ3JvdXBlZC5nZXQoZGllKQogICAgICAgICAgICBpZiB2YWxzOgog"
    "ICAgICAgICAgICAgICAgYml0cy5hcHBlbmQoZiJ7ZGllfTogeycsJy5qb2luKHN0cih2KSBmb3Ig"
    "diBpbiB2YWxzKX0iKQogICAgICAgIHJldHVybiAiIHwgIi5qb2luKGJpdHMpCgogICAgZGVmIF9h"
    "cHBlbmRfdGFibGVfcm93KHNlbGYsIHRhYmxlOiBRVGFibGVXaWRnZXQsIGV2ZW50OiBkaWN0KSAt"
    "PiBOb25lOgogICAgICAgIHJvdyA9IHRhYmxlLnJvd0NvdW50KCkKICAgICAgICB0YWJsZS5pbnNl"
    "cnRSb3cocm93KQoKICAgICAgICB0c19pdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShldmVudFsidGlt"
    "ZXN0YW1wIl0pCiAgICAgICAgdHNfaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9s"
    "ZSwgZXZlbnRbImlkIl0pCiAgICAgICAgdGFibGUuc2V0SXRlbShyb3csIDAsIHRzX2l0ZW0pCiAg"
    "ICAgICAgdGFibGUuc2V0SXRlbShyb3csIDEsIFFUYWJsZVdpZGdldEl0ZW0oZXZlbnQuZ2V0KCJs"
    "YWJlbCIsICIiKSkpCiAgICAgICAgdGFibGUuc2V0SXRlbShyb3csIDIsIFFUYWJsZVdpZGdldEl0"
    "ZW0oZXZlbnQuZ2V0KCJleHByZXNzaW9uIiwgIiIpKSkKICAgICAgICB0YWJsZS5zZXRJdGVtKHJv"
    "dywgMywgUVRhYmxlV2lkZ2V0SXRlbShzZWxmLl9mb3JtYXRfcmF3KGV2ZW50KSkpCgogICAgICAg"
    "IG1vZF9zcGluID0gUVNwaW5Cb3goKQogICAgICAgIG1vZF9zcGluLnNldFJhbmdlKC05OTksIDk5"
    "OSkKICAgICAgICBtb2Rfc3Bpbi5zZXRWYWx1ZShpbnQoZXZlbnQuZ2V0KCJtb2RpZmllciIsIDAp"
    "KSkKICAgICAgICBtb2Rfc3Bpbi52YWx1ZUNoYW5nZWQuY29ubmVjdChsYW1iZGEgdmFsLCBlaWQ9"
    "ZXZlbnRbImlkIl06IHNlbGYuX29uX21vZGlmaWVyX2NoYW5nZWQoZWlkLCB2YWwpKQogICAgICAg"
    "IHRhYmxlLnNldENlbGxXaWRnZXQocm93LCA0LCBtb2Rfc3BpbikKCiAgICAgICAgdGFibGUuc2V0"
    "SXRlbShyb3csIDUsIFFUYWJsZVdpZGdldEl0ZW0oc3RyKGV2ZW50LmdldCgiZmluYWxfdG90YWwi"
    "LCAwKSkpKQoKICAgIGRlZiBfc3luY19yb3dfYnlfZXZlbnRfaWQoc2VsZiwgdGFibGU6IFFUYWJs"
    "ZVdpZGdldCwgZXZlbnRfaWQ6IHN0ciwgZXZlbnQ6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgZm9y"
    "IHJvdyBpbiByYW5nZSh0YWJsZS5yb3dDb3VudCgpKToKICAgICAgICAgICAgaXQgPSB0YWJsZS5p"
    "dGVtKHJvdywgMCkKICAgICAgICAgICAgaWYgaXQgYW5kIGl0LmRhdGEoUXQuSXRlbURhdGFSb2xl"
    "LlVzZXJSb2xlKSA9PSBldmVudF9pZDoKICAgICAgICAgICAgICAgIHRhYmxlLnNldEl0ZW0ocm93"
    "LCA1LCBRVGFibGVXaWRnZXRJdGVtKHN0cihldmVudC5nZXQoImZpbmFsX3RvdGFsIiwgMCkpKSkK"
    "ICAgICAgICAgICAgICAgIHRhYmxlLnNldEl0ZW0ocm93LCAzLCBRVGFibGVXaWRnZXRJdGVtKHNl"
    "bGYuX2Zvcm1hdF9yYXcoZXZlbnQpKSkKICAgICAgICAgICAgICAgIGJyZWFrCgogICAgZGVmIF9v"
    "bl9tb2RpZmllcl9jaGFuZ2VkKHNlbGYsIGV2ZW50X2lkOiBzdHIsIHZhbHVlOiBpbnQpIC0+IE5v"
    "bmU6CiAgICAgICAgZXZ0ID0gc2VsZi5ldmVudF9ieV9pZC5nZXQoZXZlbnRfaWQpCiAgICAgICAg"
    "aWYgbm90IGV2dDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZXZ0WyJtb2RpZmllciJdID0g"
    "aW50KHZhbHVlKQogICAgICAgIGV2dFsiZmluYWxfdG90YWwiXSA9IGludChldnQuZ2V0KCJzdWJ0"
    "b3RhbCIsIDApKSArIGludCh2YWx1ZSkKICAgICAgICBzZWxmLl9zeW5jX3Jvd19ieV9ldmVudF9p"
    "ZChzZWxmLmhpc3RvcnlfdGFibGUsIGV2ZW50X2lkLCBldnQpCiAgICAgICAgc2VsZi5fc3luY19y"
    "b3dfYnlfZXZlbnRfaWQoc2VsZi5jdXJyZW50X3RhYmxlLCBldmVudF9pZCwgZXZ0KQogICAgICAg"
    "IHNlbGYuX3VwZGF0ZV9ncmFuZF90b3RhbCgpCiAgICAgICAgaWYgc2VsZi5jdXJyZW50X3JvbGxf"
    "aWRzIGFuZCBzZWxmLmN1cnJlbnRfcm9sbF9pZHNbMF0gPT0gZXZlbnRfaWQ6CiAgICAgICAgICAg"
    "IHNlbGYuX3VwZGF0ZV9yZXN1bHRfZGlzcGxheShldnQpCgogICAgZGVmIF91cGRhdGVfZ3JhbmRf"
    "dG90YWwoc2VsZikgLT4gTm9uZToKICAgICAgICB0b3RhbCA9IHN1bShpbnQoZXZ0LmdldCgiZmlu"
    "YWxfdG90YWwiLCAwKSkgZm9yIGV2dCBpbiBzZWxmLnJvbGxfZXZlbnRzKQogICAgICAgIHNlbGYu"
    "Z3JhbmRfdG90YWxfbGJsLnNldFRleHQoZiJHcmFuZCBUb3RhbDoge3RvdGFsfSIpCgogICAgZGVm"
    "IF91cGRhdGVfcmVzdWx0X2Rpc3BsYXkoc2VsZiwgZXZlbnQ6IGRpY3QpIC0+IE5vbmU6CiAgICAg"
    "ICAgZ3JvdXBlZCA9IGV2ZW50LmdldCgiZ3JvdXBlZF9yYXdfZGlzcGxheSIsIHt9KSBvciB7fQog"
    "ICAgICAgIGxpbmVzID0gW10KICAgICAgICBmb3IgZGllIGluIHNlbGYuVFJBWV9PUkRFUjoKICAg"
    "ICAgICAgICAgdmFscyA9IGdyb3VwZWQuZ2V0KGRpZSkKICAgICAgICAgICAgaWYgdmFsczoKICAg"
    "ICAgICAgICAgICAgIGxpbmVzLmFwcGVuZChmIntkaWV9IHh7bGVuKHZhbHMpfSDihpIgW3snLCcu"
    "am9pbihzdHIodikgZm9yIHYgaW4gdmFscyl9XSIpCiAgICAgICAgcnVsZV9pZCA9IGV2ZW50Lmdl"
    "dCgicnVsZV9pZCIpCiAgICAgICAgaWYgcnVsZV9pZDoKICAgICAgICAgICAgcnVsZV9uYW1lID0g"
    "c2VsZi5ydWxlX2RlZmluaXRpb25zLmdldChydWxlX2lkLCB7fSkuZ2V0KCJuYW1lIiwgcnVsZV9p"
    "ZCkKICAgICAgICAgICAgbGluZXMuYXBwZW5kKGYiUnVsZToge3J1bGVfbmFtZX0iKQogICAgICAg"
    "IGxpbmVzLmFwcGVuZChmIk1vZGlmaWVyOiB7aW50KGV2ZW50LmdldCgnbW9kaWZpZXInLCAwKSk6"
    "K2R9IikKICAgICAgICBsaW5lcy5hcHBlbmQoZiJUb3RhbDoge2V2ZW50LmdldCgnZmluYWxfdG90"
    "YWwnLCAwKX0iKQogICAgICAgIHNlbGYuY3VycmVudF9yZXN1bHRfbGJsLnNldFRleHQoIlxuIi5q"
    "b2luKGxpbmVzKSkKCgogICAgZGVmIF9zYXZlX3Bvb2woc2VsZikgLT4gTm9uZToKICAgICAgICBp"
    "ZiBub3Qgc2VsZi5jdXJyZW50X3Bvb2w6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0"
    "aW9uKHNlbGYsICJEaWNlIFJvbGxlciIsICJCdWlsZCBhIEN1cnJlbnQgUG9vbCBiZWZvcmUgc2F2"
    "aW5nLiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGRlZmF1bHRfbmFtZSA9IHNlbGYubGFi"
    "ZWxfZWRpdC50ZXh0KCkuc3RyaXAoKSBvciBzZWxmLl9wb29sX2V4cHJlc3Npb24oKQogICAgICAg"
    "IG5hbWUsIG9rID0gUUlucHV0RGlhbG9nLmdldFRleHQoc2VsZiwgIlNhdmUgUG9vbCIsICJTYXZl"
    "ZCByb2xsIG5hbWU6IiwgdGV4dD1kZWZhdWx0X25hbWUpCiAgICAgICAgaWYgbm90IG9rOgogICAg"
    "ICAgICAgICByZXR1cm4KICAgICAgICBwYXlsb2FkID0gewogICAgICAgICAgICAiaWQiOiBmInNh"
    "dmVkX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19IiwKICAgICAgICAgICAgIm5hbWUiOiBuYW1lLnN0"
    "cmlwKCkgb3IgZGVmYXVsdF9uYW1lLAogICAgICAgICAgICAicG9vbCI6IGRpY3Qoc2VsZi5jdXJy"
    "ZW50X3Bvb2wpLAogICAgICAgICAgICAibW9kaWZpZXIiOiBpbnQoc2VsZi5tb2Rfc3Bpbi52YWx1"
    "ZSgpKSwKICAgICAgICAgICAgInJ1bGVfaWQiOiBzZWxmLnJ1bGVfY29tYm8uY3VycmVudERhdGEo"
    "KSBvciBOb25lLAogICAgICAgICAgICAibm90ZXMiOiAiIiwKICAgICAgICAgICAgImNhdGVnb3J5"
    "IjogInNhdmVkIiwKICAgICAgICB9CiAgICAgICAgc2VsZi5zYXZlZF9yb2xscy5hcHBlbmQocGF5"
    "bG9hZCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBkZWYgX3JlZnJl"
    "c2hfc2F2ZWRfbGlzdHMoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLnNhdmVkX2xpc3QuY2xl"
    "YXIoKQogICAgICAgIGZvciBpdGVtIGluIHNlbGYuc2F2ZWRfcm9sbHM6CiAgICAgICAgICAgIGV4"
    "cHIgPSBzZWxmLl9wb29sX2V4cHJlc3Npb24oaXRlbS5nZXQoInBvb2wiLCB7fSkpCiAgICAgICAg"
    "ICAgIHR4dCA9IGYie2l0ZW0uZ2V0KCduYW1lJyl9IOKAlCB7ZXhwcn0ge2ludChpdGVtLmdldCgn"
    "bW9kaWZpZXInLCAwKSk6K2R9IgogICAgICAgICAgICBsdyA9IFFMaXN0V2lkZ2V0SXRlbSh0eHQp"
    "CiAgICAgICAgICAgIGx3LnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCBpdGVtKQog"
    "ICAgICAgICAgICBzZWxmLnNhdmVkX2xpc3QuYWRkSXRlbShsdykKCiAgICAgICAgc2VsZi5jb21t"
    "b25fbGlzdC5jbGVhcigpCiAgICAgICAgcmFua2VkID0gc29ydGVkKHNlbGYuY29tbW9uX3JvbGxz"
    "LnZhbHVlcygpLCBrZXk9bGFtYmRhIHg6IHguZ2V0KCJjb3VudCIsIDApLCByZXZlcnNlPVRydWUp"
    "CiAgICAgICAgZm9yIGl0ZW0gaW4gcmFua2VkOgogICAgICAgICAgICBpZiBpbnQoaXRlbS5nZXQo"
    "ImNvdW50IiwgMCkpIDwgMjoKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGV4"
    "cHIgPSBzZWxmLl9wb29sX2V4cHJlc3Npb24oaXRlbS5nZXQoInBvb2wiLCB7fSkpCiAgICAgICAg"
    "ICAgIHR4dCA9IGYie2V4cHJ9IHtpbnQoaXRlbS5nZXQoJ21vZGlmaWVyJywgMCkpOitkfSAoeHtp"
    "dGVtLmdldCgnY291bnQnLCAwKX0pIgogICAgICAgICAgICBsdyA9IFFMaXN0V2lkZ2V0SXRlbSh0"
    "eHQpCiAgICAgICAgICAgIGx3LnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCBpdGVt"
    "KQogICAgICAgICAgICBzZWxmLmNvbW1vbl9saXN0LmFkZEl0ZW0obHcpCgogICAgZGVmIF90cmFj"
    "a19jb21tb25fc2lnbmF0dXJlKHNlbGYsIGV2ZW50OiBkaWN0KSAtPiBOb25lOgogICAgICAgIHNp"
    "ZyA9IHNlbGYuX25vcm1hbGl6ZV9wb29sX3NpZ25hdHVyZShldmVudC5nZXQoInBvb2wiLCB7fSks"
    "IGludChldmVudC5nZXQoIm1vZGlmaWVyIiwgMCkpLCBzdHIoZXZlbnQuZ2V0KCJydWxlX2lkIikg"
    "b3IgIiIpKQogICAgICAgIGlmIHNpZyBub3QgaW4gc2VsZi5jb21tb25fcm9sbHM6CiAgICAgICAg"
    "ICAgIHNlbGYuY29tbW9uX3JvbGxzW3NpZ10gPSB7CiAgICAgICAgICAgICAgICAic2lnbmF0dXJl"
    "Ijogc2lnLAogICAgICAgICAgICAgICAgImNvdW50IjogMCwKICAgICAgICAgICAgICAgICJuYW1l"
    "IjogZXZlbnQuZ2V0KCJsYWJlbCIsICIiKSBvciBzaWcsCiAgICAgICAgICAgICAgICAicG9vbCI6"
    "IGRpY3QoZXZlbnQuZ2V0KCJwb29sIiwge30pKSwKICAgICAgICAgICAgICAgICJtb2RpZmllciI6"
    "IGludChldmVudC5nZXQoIm1vZGlmaWVyIiwgMCkpLAogICAgICAgICAgICAgICAgInJ1bGVfaWQi"
    "OiBldmVudC5nZXQoInJ1bGVfaWQiKSwKICAgICAgICAgICAgICAgICJub3RlcyI6ICIiLAogICAg"
    "ICAgICAgICAgICAgImNhdGVnb3J5IjogImNvbW1vbiIsCiAgICAgICAgICAgIH0KICAgICAgICBz"
    "ZWxmLmNvbW1vbl9yb2xsc1tzaWddWyJjb3VudCJdID0gaW50KHNlbGYuY29tbW9uX3JvbGxzW3Np"
    "Z10uZ2V0KCJjb3VudCIsIDApKSArIDEKICAgICAgICBpZiBzZWxmLmNvbW1vbl9yb2xsc1tzaWdd"
    "WyJjb3VudCJdID49IDM6CiAgICAgICAgICAgIHNlbGYuY29tbW9uX2hpbnQuc2V0VGV4dChmIlN1"
    "Z2dlc3Rpb246IHByb21vdGUge3NlbGYuX3Bvb2xfZXhwcmVzc2lvbihldmVudC5nZXQoJ3Bvb2wn"
    "LCB7fSkpfSB0byBTYXZlZC4iKQogICAgICAgIHNlbGYuX3JlZnJlc2hfc2F2ZWRfbGlzdHMoKQoK"
    "ICAgIGRlZiBfcnVuX3NhdmVkX3JvbGwoc2VsZiwgcGF5bG9hZDogZGljdCB8IE5vbmUpOgogICAg"
    "ICAgIGlmIG5vdCBwYXlsb2FkOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBldmVudCA9IHNl"
    "bGYuX3JvbGxfcG9vbF9kYXRhKAogICAgICAgICAgICBkaWN0KHBheWxvYWQuZ2V0KCJwb29sIiwg"
    "e30pKSwKICAgICAgICAgICAgaW50KHBheWxvYWQuZ2V0KCJtb2RpZmllciIsIDApKSwKICAgICAg"
    "ICAgICAgc3RyKHBheWxvYWQuZ2V0KCJuYW1lIiwgIiIpKS5zdHJpcCgpLAogICAgICAgICAgICBz"
    "dHIocGF5bG9hZC5nZXQoInJ1bGVfaWQiKSBvciAiIiksCiAgICAgICAgKQogICAgICAgIHNlbGYu"
    "X3JlY29yZF9yb2xsX2V2ZW50KGV2ZW50KQoKICAgIGRlZiBfbG9hZF9wYXlsb2FkX2ludG9fcG9v"
    "bChzZWxmLCBwYXlsb2FkOiBkaWN0IHwgTm9uZSkgLT4gTm9uZToKICAgICAgICBpZiBub3QgcGF5"
    "bG9hZDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5jdXJyZW50X3Bvb2wgPSBkaWN0"
    "KHBheWxvYWQuZ2V0KCJwb29sIiwge30pKQogICAgICAgIHNlbGYubW9kX3NwaW4uc2V0VmFsdWUo"
    "aW50KHBheWxvYWQuZ2V0KCJtb2RpZmllciIsIDApKSkKICAgICAgICBzZWxmLmxhYmVsX2VkaXQu"
    "c2V0VGV4dChzdHIocGF5bG9hZC5nZXQoIm5hbWUiLCAiIikpKQogICAgICAgIHJpZCA9IHBheWxv"
    "YWQuZ2V0KCJydWxlX2lkIikKICAgICAgICBpZHggPSBzZWxmLnJ1bGVfY29tYm8uZmluZERhdGEo"
    "cmlkIG9yICIiKQogICAgICAgIGlmIGlkeCA+PSAwOgogICAgICAgICAgICBzZWxmLnJ1bGVfY29t"
    "Ym8uc2V0Q3VycmVudEluZGV4KGlkeCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3Bvb2xfZWRpdG9y"
    "KCkKICAgICAgICBzZWxmLmN1cnJlbnRfcmVzdWx0X2xibC5zZXRUZXh0KGYiQ3VycmVudCBQb29s"
    "OiB7c2VsZi5fcG9vbF9leHByZXNzaW9uKCl9IikKCiAgICBkZWYgX3J1bl9zZWxlY3RlZF9zYXZl"
    "ZChzZWxmKToKICAgICAgICBpdGVtID0gc2VsZi5zYXZlZF9saXN0LmN1cnJlbnRJdGVtKCkKICAg"
    "ICAgICBzZWxmLl9ydW5fc2F2ZWRfcm9sbChpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJS"
    "b2xlKSBpZiBpdGVtIGVsc2UgTm9uZSkKCiAgICBkZWYgX2xvYWRfc2VsZWN0ZWRfc2F2ZWQoc2Vs"
    "Zik6CiAgICAgICAgaXRlbSA9IHNlbGYuc2F2ZWRfbGlzdC5jdXJyZW50SXRlbSgpCiAgICAgICAg"
    "cGF5bG9hZCA9IGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpIGlmIGl0ZW0gZWxz"
    "ZSBOb25lCiAgICAgICAgaWYgbm90IHBheWxvYWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAg"
    "IHNlbGYuX2xvYWRfcGF5bG9hZF9pbnRvX3Bvb2wocGF5bG9hZCkKCiAgICAgICAgbmFtZSwgb2sg"
    "PSBRSW5wdXREaWFsb2cuZ2V0VGV4dChzZWxmLCAiRWRpdCBTYXZlZCBSb2xsIiwgIk5hbWU6Iiwg"
    "dGV4dD1zdHIocGF5bG9hZC5nZXQoIm5hbWUiLCAiIikpKQogICAgICAgIGlmIG5vdCBvazoKICAg"
    "ICAgICAgICAgcmV0dXJuCiAgICAgICAgcGF5bG9hZFsibmFtZSJdID0gbmFtZS5zdHJpcCgpIG9y"
    "IHBheWxvYWQuZ2V0KCJuYW1lIiwgIiIpCiAgICAgICAgcGF5bG9hZFsicG9vbCJdID0gZGljdChz"
    "ZWxmLmN1cnJlbnRfcG9vbCkKICAgICAgICBwYXlsb2FkWyJtb2RpZmllciJdID0gaW50KHNlbGYu"
    "bW9kX3NwaW4udmFsdWUoKSkKICAgICAgICBwYXlsb2FkWyJydWxlX2lkIl0gPSBzZWxmLnJ1bGVf"
    "Y29tYm8uY3VycmVudERhdGEoKSBvciBOb25lCiAgICAgICAgbm90ZXMsIG9rX25vdGVzID0gUUlu"
    "cHV0RGlhbG9nLmdldFRleHQoc2VsZiwgIkVkaXQgU2F2ZWQgUm9sbCIsICJOb3RlcyAvIGNhdGVn"
    "b3J5OiIsIHRleHQ9c3RyKHBheWxvYWQuZ2V0KCJub3RlcyIsICIiKSkpCiAgICAgICAgaWYgb2tf"
    "bm90ZXM6CiAgICAgICAgICAgIHBheWxvYWRbIm5vdGVzIl0gPSBub3RlcwogICAgICAgIHNlbGYu"
    "X3JlZnJlc2hfc2F2ZWRfbGlzdHMoKQoKICAgIGRlZiBfZGVsZXRlX3NlbGVjdGVkX3NhdmVkKHNl"
    "bGYpOgogICAgICAgIHJvdyA9IHNlbGYuc2F2ZWRfbGlzdC5jdXJyZW50Um93KCkKICAgICAgICBp"
    "ZiByb3cgPCAwIG9yIHJvdyA+PSBsZW4oc2VsZi5zYXZlZF9yb2xscyk6CiAgICAgICAgICAgIHJl"
    "dHVybgogICAgICAgIHNlbGYuc2F2ZWRfcm9sbHMucG9wKHJvdykKICAgICAgICBzZWxmLl9yZWZy"
    "ZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBkZWYgX3Byb21vdGVfc2VsZWN0ZWRfY29tbW9uKHNlbGYp"
    "OgogICAgICAgIGl0ZW0gPSBzZWxmLmNvbW1vbl9saXN0LmN1cnJlbnRJdGVtKCkKICAgICAgICBw"
    "YXlsb2FkID0gaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkgaWYgaXRlbSBlbHNl"
    "IE5vbmUKICAgICAgICBpZiBub3QgcGF5bG9hZDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAg"
    "cHJvbW90ZWQgPSB7CiAgICAgICAgICAgICJpZCI6IGYic2F2ZWRfe3V1aWQudXVpZDQoKS5oZXhb"
    "OjEwXX0iLAogICAgICAgICAgICAibmFtZSI6IHBheWxvYWQuZ2V0KCJuYW1lIikgb3Igc2VsZi5f"
    "cG9vbF9leHByZXNzaW9uKHBheWxvYWQuZ2V0KCJwb29sIiwge30pKSwKICAgICAgICAgICAgInBv"
    "b2wiOiBkaWN0KHBheWxvYWQuZ2V0KCJwb29sIiwge30pKSwKICAgICAgICAgICAgIm1vZGlmaWVy"
    "IjogaW50KHBheWxvYWQuZ2V0KCJtb2RpZmllciIsIDApKSwKICAgICAgICAgICAgInJ1bGVfaWQi"
    "OiBwYXlsb2FkLmdldCgicnVsZV9pZCIpLAogICAgICAgICAgICAibm90ZXMiOiBwYXlsb2FkLmdl"
    "dCgibm90ZXMiLCAiIiksCiAgICAgICAgICAgICJjYXRlZ29yeSI6ICJzYXZlZCIsCiAgICAgICAg"
    "fQogICAgICAgIHNlbGYuc2F2ZWRfcm9sbHMuYXBwZW5kKHByb21vdGVkKQogICAgICAgIHNlbGYu"
    "X3JlZnJlc2hfc2F2ZWRfbGlzdHMoKQoKICAgIGRlZiBfZGlzbWlzc19zZWxlY3RlZF9jb21tb24o"
    "c2VsZik6CiAgICAgICAgaXRlbSA9IHNlbGYuY29tbW9uX2xpc3QuY3VycmVudEl0ZW0oKQogICAg"
    "ICAgIHBheWxvYWQgPSBpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKSBpZiBpdGVt"
    "IGVsc2UgTm9uZQogICAgICAgIGlmIG5vdCBwYXlsb2FkOgogICAgICAgICAgICByZXR1cm4KICAg"
    "ICAgICBzaWcgPSBwYXlsb2FkLmdldCgic2lnbmF0dXJlIikKICAgICAgICBpZiBzaWcgaW4gc2Vs"
    "Zi5jb21tb25fcm9sbHM6CiAgICAgICAgICAgIHNlbGYuY29tbW9uX3JvbGxzLnBvcChzaWcsIE5v"
    "bmUpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9zYXZlZF9saXN0cygpCgogICAgZGVmIF9yZXNldF9w"
    "b29sKHNlbGYpOgogICAgICAgIHNlbGYuY3VycmVudF9wb29sID0ge30KICAgICAgICBzZWxmLm1v"
    "ZF9zcGluLnNldFZhbHVlKDApCiAgICAgICAgc2VsZi5sYWJlbF9lZGl0LmNsZWFyKCkKICAgICAg"
    "ICBzZWxmLnJ1bGVfY29tYm8uc2V0Q3VycmVudEluZGV4KDApCiAgICAgICAgc2VsZi5fcmVmcmVz"
    "aF9wb29sX2VkaXRvcigpCiAgICAgICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwuc2V0VGV4dCgi"
    "Tm8gcm9sbCB5ZXQuIikKCiAgICBkZWYgX2NsZWFyX2hpc3Rvcnkoc2VsZik6CiAgICAgICAgc2Vs"
    "Zi5yb2xsX2V2ZW50cy5jbGVhcigpCiAgICAgICAgc2VsZi5ldmVudF9ieV9pZC5jbGVhcigpCiAg"
    "ICAgICAgc2VsZi5jdXJyZW50X3JvbGxfaWRzID0gW10KICAgICAgICBzZWxmLmhpc3RvcnlfdGFi"
    "bGUuc2V0Um93Q291bnQoMCkKICAgICAgICBzZWxmLmN1cnJlbnRfdGFibGUuc2V0Um93Q291bnQo"
    "MCkKICAgICAgICBzZWxmLl91cGRhdGVfZ3JhbmRfdG90YWwoKQogICAgICAgIHNlbGYuY3VycmVu"
    "dF9yZXN1bHRfbGJsLnNldFRleHQoIk5vIHJvbGwgeWV0LiIpCgogICAgZGVmIF9ldmVudF9mcm9t"
    "X3RhYmxlX3Bvc2l0aW9uKHNlbGYsIHRhYmxlOiBRVGFibGVXaWRnZXQsIHBvcykgLT4gZGljdCB8"
    "IE5vbmU6CiAgICAgICAgaXRlbSA9IHRhYmxlLml0ZW1BdChwb3MpCiAgICAgICAgaWYgbm90IGl0"
    "ZW06CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgcm93ID0gaXRlbS5yb3coKQogICAg"
    "ICAgIHRzX2l0ZW0gPSB0YWJsZS5pdGVtKHJvdywgMCkKICAgICAgICBpZiBub3QgdHNfaXRlbToK"
    "ICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBlaWQgPSB0c19pdGVtLmRhdGEoUXQuSXRl"
    "bURhdGFSb2xlLlVzZXJSb2xlKQogICAgICAgIHJldHVybiBzZWxmLmV2ZW50X2J5X2lkLmdldChl"
    "aWQpCgogICAgZGVmIF9zaG93X3JvbGxfY29udGV4dF9tZW51KHNlbGYsIHRhYmxlOiBRVGFibGVX"
    "aWRnZXQsIHBvcykgLT4gTm9uZToKICAgICAgICBldnQgPSBzZWxmLl9ldmVudF9mcm9tX3RhYmxl"
    "X3Bvc2l0aW9uKHRhYmxlLCBwb3MpCiAgICAgICAgaWYgbm90IGV2dDoKICAgICAgICAgICAgcmV0"
    "dXJuCiAgICAgICAgZnJvbSBQeVNpZGU2LlF0V2lkZ2V0cyBpbXBvcnQgUU1lbnUKICAgICAgICBt"
    "ZW51ID0gUU1lbnUoc2VsZikKICAgICAgICBhY3Rfc2VuZCA9IG1lbnUuYWRkQWN0aW9uKCJTZW5k"
    "IHRvIFByb21wdCIpCiAgICAgICAgY2hvc2VuID0gbWVudS5leGVjKHRhYmxlLnZpZXdwb3J0KCku"
    "bWFwVG9HbG9iYWwocG9zKSkKICAgICAgICBpZiBjaG9zZW4gPT0gYWN0X3NlbmQ6CiAgICAgICAg"
    "ICAgIHNlbGYuX3NlbmRfZXZlbnRfdG9fcHJvbXB0KGV2dCkKCiAgICBkZWYgX2Zvcm1hdF9ldmVu"
    "dF9mb3JfcHJvbXB0KHNlbGYsIGV2ZW50OiBkaWN0KSAtPiBzdHI6CiAgICAgICAgbGFiZWwgPSAo"
    "ZXZlbnQuZ2V0KCJsYWJlbCIpIG9yICJSb2xsIikuc3RyaXAoKQogICAgICAgIGdyb3VwZWQgPSBl"
    "dmVudC5nZXQoImdyb3VwZWRfcmF3X2Rpc3BsYXkiLCB7fSkgb3Ige30KICAgICAgICBzZWdtZW50"
    "cyA9IFtdCiAgICAgICAgZm9yIGRpZSBpbiBzZWxmLlRSQVlfT1JERVI6CiAgICAgICAgICAgIHZh"
    "bHMgPSBncm91cGVkLmdldChkaWUpCiAgICAgICAgICAgIGlmIHZhbHM6CiAgICAgICAgICAgICAg"
    "ICBzZWdtZW50cy5hcHBlbmQoZiJ7ZGllfSByb2xsZWQgeycsJy5qb2luKHN0cih2KSBmb3IgdiBp"
    "biB2YWxzKX0iKQogICAgICAgIG1vZCA9IGludChldmVudC5nZXQoIm1vZGlmaWVyIiwgMCkpCiAg"
    "ICAgICAgdG90YWwgPSBpbnQoZXZlbnQuZ2V0KCJmaW5hbF90b3RhbCIsIDApKQogICAgICAgIHJl"
    "dHVybiBmIntsYWJlbH06IHsnOyAnLmpvaW4oc2VnbWVudHMpfTsgbW9kaWZpZXIge21vZDorZH07"
    "IHRvdGFsIHt0b3RhbH0iCgogICAgZGVmIF9zZW5kX2V2ZW50X3RvX3Byb21wdChzZWxmLCBldmVu"
    "dDogZGljdCkgLT4gTm9uZToKICAgICAgICB3aW5kb3cgPSBzZWxmLndpbmRvdygpCiAgICAgICAg"
    "aWYgbm90IHdpbmRvdyBvciBub3QgaGFzYXR0cih3aW5kb3csICJfaW5wdXRfZmllbGQiKToKICAg"
    "ICAgICAgICAgcmV0dXJuCiAgICAgICAgbGluZSA9IHNlbGYuX2Zvcm1hdF9ldmVudF9mb3JfcHJv"
    "bXB0KGV2ZW50KQogICAgICAgIHdpbmRvdy5faW5wdXRfZmllbGQuc2V0VGV4dChsaW5lKQogICAg"
    "ICAgIHdpbmRvdy5faW5wdXRfZmllbGQuc2V0Rm9jdXMoKQoKICAgIGRlZiBfcGxheV9yb2xsX3Nv"
    "dW5kKHNlbGYpOgogICAgICAgIGlmIG5vdCBXSU5TT1VORF9PSzoKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgdHJ5OgogICAgICAgICAgICB3aW5zb3VuZC5CZWVwKDg0MCwgMzApCiAgICAgICAg"
    "ICAgIHdpbnNvdW5kLkJlZXAoNjIwLCAzNSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgICAgICBwYXNzCgoKCmNsYXNzIE1hZ2ljOEJhbGxUYWIoUVdpZGdldCk6CiAgICAiIiJNYWdp"
    "YyA4LUJhbGwgbW9kdWxlIHdpdGggY2lyY3VsYXIgb3JiIGRpc3BsYXkgYW5kIHB1bHNpbmcgYW5z"
    "d2VyIHRleHQuIiIiCgogICAgQU5TV0VSUyA9IFsKICAgICAgICAiSXQgaXMgY2VydGFpbi4iLAog"
    "ICAgICAgICJJdCBpcyBkZWNpZGVkbHkgc28uIiwKICAgICAgICAiV2l0aG91dCBhIGRvdWJ0LiIs"
    "CiAgICAgICAgIlllcyBkZWZpbml0ZWx5LiIsCiAgICAgICAgIllvdSBtYXkgcmVseSBvbiBpdC4i"
    "LAogICAgICAgICJBcyBJIHNlZSBpdCwgeWVzLiIsCiAgICAgICAgIk1vc3QgbGlrZWx5LiIsCiAg"
    "ICAgICAgIk91dGxvb2sgZ29vZC4iLAogICAgICAgICJZZXMuIiwKICAgICAgICAiU2lnbnMgcG9p"
    "bnQgdG8geWVzLiIsCiAgICAgICAgIlJlcGx5IGhhenksIHRyeSBhZ2Fpbi4iLAogICAgICAgICJB"
    "c2sgYWdhaW4gbGF0ZXIuIiwKICAgICAgICAiQmV0dGVyIG5vdCB0ZWxsIHlvdSBub3cuIiwKICAg"
    "ICAgICAiQ2Fubm90IHByZWRpY3Qgbm93LiIsCiAgICAgICAgIkNvbmNlbnRyYXRlIGFuZCBhc2sg"
    "YWdhaW4uIiwKICAgICAgICAiRG9uJ3QgY291bnQgb24gaXQuIiwKICAgICAgICAiTXkgcmVwbHkg"
    "aXMgbm8uIiwKICAgICAgICAiTXkgc291cmNlcyBzYXkgbm8uIiwKICAgICAgICAiT3V0bG9vayBu"
    "b3Qgc28gZ29vZC4iLAogICAgICAgICJWZXJ5IGRvdWJ0ZnVsLiIsCiAgICBdCgogICAgZGVmIF9f"
    "aW5pdF9fKHNlbGYsIG9uX3Rocm93PU5vbmUsIGRpYWdub3N0aWNzX2xvZ2dlcj1Ob25lKToKICAg"
    "ICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9vbl90aHJvdyA9IG9uX3Rocm93"
    "CiAgICAgICAgc2VsZi5fbG9nID0gZGlhZ25vc3RpY3NfbG9nZ2VyIG9yIChsYW1iZGEgKl9hcmdz"
    "LCAqKl9rd2FyZ3M6IE5vbmUpCiAgICAgICAgc2VsZi5fY3VycmVudF9hbnN3ZXIgPSAiIgoKICAg"
    "ICAgICBzZWxmLl9jbGVhcl90aW1lciA9IFFUaW1lcihzZWxmKQogICAgICAgIHNlbGYuX2NsZWFy"
    "X3RpbWVyLnNldFNpbmdsZVNob3QoVHJ1ZSkKICAgICAgICBzZWxmLl9jbGVhcl90aW1lci50aW1l"
    "b3V0LmNvbm5lY3Qoc2VsZi5fZmFkZV9vdXRfYW5zd2VyKQoKICAgICAgICBzZWxmLl9idWlsZF91"
    "aSgpCiAgICAgICAgc2VsZi5fYnVpbGRfYW5pbWF0aW9ucygpCiAgICAgICAgc2VsZi5fc2V0X2lk"
    "bGVfdmlzdWFsKCkKCiAgICBkZWYgX2J1aWxkX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9v"
    "dCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoMTYs"
    "IDE2LCAxNiwgMTYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDE0KQogICAgICAgIHJvb3QuYWRk"
    "U3RyZXRjaCgxKQoKICAgICAgICBzZWxmLl9vcmJfZnJhbWUgPSBRRnJhbWUoKQogICAgICAgIHNl"
    "bGYuX29yYl9mcmFtZS5zZXRGaXhlZFNpemUoMjI4LCAyMjgpCiAgICAgICAgc2VsZi5fb3JiX2Zy"
    "YW1lLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICJRRnJhbWUgeyIKICAgICAgICAgICAgImJh"
    "Y2tncm91bmQtY29sb3I6ICMwNDA0MDY7IgogICAgICAgICAgICAiYm9yZGVyOiAxcHggc29saWQg"
    "cmdiYSgyMzQsIDIzNywgMjU1LCAwLjYyKTsiCiAgICAgICAgICAgICJib3JkZXItcmFkaXVzOiAx"
    "MTRweDsiCiAgICAgICAgICAgICJ9IgogICAgICAgICkKCiAgICAgICAgb3JiX2xheW91dCA9IFFW"
    "Qm94TGF5b3V0KHNlbGYuX29yYl9mcmFtZSkKICAgICAgICBvcmJfbGF5b3V0LnNldENvbnRlbnRz"
    "TWFyZ2lucygyMCwgMjAsIDIwLCAyMCkKICAgICAgICBvcmJfbGF5b3V0LnNldFNwYWNpbmcoMCkK"
    "CiAgICAgICAgc2VsZi5fb3JiX2lubmVyID0gUUZyYW1lKCkKICAgICAgICBzZWxmLl9vcmJfaW5u"
    "ZXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgIlFGcmFtZSB7IgogICAgICAgICAgICAiYmFj"
    "a2dyb3VuZC1jb2xvcjogIzA3MDcwYTsiCiAgICAgICAgICAgICJib3JkZXI6IDFweCBzb2xpZCBy"
    "Z2JhKDI1NSwgMjU1LCAyNTUsIDAuMTIpOyIKICAgICAgICAgICAgImJvcmRlci1yYWRpdXM6IDg0"
    "cHg7IgogICAgICAgICAgICAifSIKICAgICAgICApCiAgICAgICAgc2VsZi5fb3JiX2lubmVyLnNl"
    "dE1pbmltdW1TaXplKDE2OCwgMTY4KQogICAgICAgIHNlbGYuX29yYl9pbm5lci5zZXRNYXhpbXVt"
    "U2l6ZSgxNjgsIDE2OCkKCiAgICAgICAgaW5uZXJfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5f"
    "b3JiX2lubmVyKQogICAgICAgIGlubmVyX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMTYsIDE2"
    "LCAxNiwgMTYpCiAgICAgICAgaW5uZXJfbGF5b3V0LnNldFNwYWNpbmcoMCkKCiAgICAgICAgc2Vs"
    "Zi5fZWlnaHRfbGJsID0gUUxhYmVsKCI4IikKICAgICAgICBzZWxmLl9laWdodF9sYmwuc2V0QWxp"
    "Z25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgc2VsZi5fZWlnaHRf"
    "bGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICJjb2xvcjogcmdiYSgyNTUsIDI1NSwgMjU1"
    "LCAwLjk1KTsgIgogICAgICAgICAgICAiZm9udC1zaXplOiA4MHB4OyBmb250LXdlaWdodDogNzAw"
    "OyAiCiAgICAgICAgICAgICJmb250LWZhbWlseTogR2VvcmdpYSwgc2VyaWY7IGJvcmRlcjogbm9u"
    "ZTsiCiAgICAgICAgKQoKICAgICAgICBzZWxmLmFuc3dlcl9sYmwgPSBRTGFiZWwoIiIpCiAgICAg"
    "ICAgc2VsZi5hbnN3ZXJfbGJsLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2Vu"
    "dGVyKQogICAgICAgIHNlbGYuYW5zd2VyX2xibC5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIHNl"
    "bGYuYW5zd2VyX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xE"
    "fTsgZm9udC1zaXplOiAxNnB4OyBmb250LXN0eWxlOiBpdGFsaWM7ICIKICAgICAgICAgICAgImZv"
    "bnQtd2VpZ2h0OiA2MDA7IGJvcmRlcjogbm9uZTsgcGFkZGluZzogMnB4OyIKICAgICAgICApCgog"
    "ICAgICAgIGlubmVyX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fZWlnaHRfbGJsLCAxKQogICAgICAg"
    "IGlubmVyX2xheW91dC5hZGRXaWRnZXQoc2VsZi5hbnN3ZXJfbGJsLCAxKQogICAgICAgIG9yYl9s"
    "YXlvdXQuYWRkV2lkZ2V0KHNlbGYuX29yYl9pbm5lciwgMCwgUXQuQWxpZ25tZW50RmxhZy5BbGln"
    "bkNlbnRlcikKCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fb3JiX2ZyYW1lLCAwLCBRdC5B"
    "bGlnbm1lbnRGbGFnLkFsaWduSENlbnRlcikKCiAgICAgICAgc2VsZi50aHJvd19idG4gPSBRUHVz"
    "aEJ1dHRvbigiVGhyb3cgdGhlIDgtQmFsbCIpCiAgICAgICAgc2VsZi50aHJvd19idG4uc2V0Rml4"
    "ZWRIZWlnaHQoMzgpCiAgICAgICAgc2VsZi50aHJvd19idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "X3Rocm93X2JhbGwpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi50aHJvd19idG4sIDAsIFF0"
    "LkFsaWdubWVudEZsYWcuQWxpZ25IQ2VudGVyKQogICAgICAgIHJvb3QuYWRkU3RyZXRjaCgxKQoK"
    "ICAgIGRlZiBfYnVpbGRfYW5pbWF0aW9ucyhzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Fu"
    "c3dlcl9vcGFjaXR5ID0gUUdyYXBoaWNzT3BhY2l0eUVmZmVjdChzZWxmLmFuc3dlcl9sYmwpCiAg"
    "ICAgICAgc2VsZi5hbnN3ZXJfbGJsLnNldEdyYXBoaWNzRWZmZWN0KHNlbGYuX2Fuc3dlcl9vcGFj"
    "aXR5KQogICAgICAgIHNlbGYuX2Fuc3dlcl9vcGFjaXR5LnNldE9wYWNpdHkoMC4wKQoKICAgICAg"
    "ICBzZWxmLl9wdWxzZV9hbmltID0gUVByb3BlcnR5QW5pbWF0aW9uKHNlbGYuX2Fuc3dlcl9vcGFj"
    "aXR5LCBiIm9wYWNpdHkiLCBzZWxmKQogICAgICAgIHNlbGYuX3B1bHNlX2FuaW0uc2V0RHVyYXRp"
    "b24oNzYwKQogICAgICAgIHNlbGYuX3B1bHNlX2FuaW0uc2V0U3RhcnRWYWx1ZSgwLjM1KQogICAg"
    "ICAgIHNlbGYuX3B1bHNlX2FuaW0uc2V0RW5kVmFsdWUoMS4wKQogICAgICAgIHNlbGYuX3B1bHNl"
    "X2FuaW0uc2V0RWFzaW5nQ3VydmUoUUVhc2luZ0N1cnZlLlR5cGUuSW5PdXRTaW5lKQogICAgICAg"
    "IHNlbGYuX3B1bHNlX2FuaW0uc2V0TG9vcENvdW50KC0xKQoKICAgICAgICBzZWxmLl9mYWRlX291"
    "dCA9IFFQcm9wZXJ0eUFuaW1hdGlvbihzZWxmLl9hbnN3ZXJfb3BhY2l0eSwgYiJvcGFjaXR5Iiwg"
    "c2VsZikKICAgICAgICBzZWxmLl9mYWRlX291dC5zZXREdXJhdGlvbig1NjApCiAgICAgICAgc2Vs"
    "Zi5fZmFkZV9vdXQuc2V0U3RhcnRWYWx1ZSgxLjApCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc2V0"
    "RW5kVmFsdWUoMC4wKQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LnNldEVhc2luZ0N1cnZlKFFFYXNp"
    "bmdDdXJ2ZS5UeXBlLkluT3V0UXVhZCkKICAgICAgICBzZWxmLl9mYWRlX291dC5maW5pc2hlZC5j"
    "b25uZWN0KHNlbGYuX2NsZWFyX3RvX2lkbGUpCgogICAgZGVmIF9zZXRfaWRsZV92aXN1YWwoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9jdXJyZW50X2Fuc3dlciA9ICIiCiAgICAgICAgc2Vs"
    "Zi5fZWlnaHRfbGJsLnNob3coKQogICAgICAgIHNlbGYuYW5zd2VyX2xibC5jbGVhcigpCiAgICAg"
    "ICAgc2VsZi5hbnN3ZXJfbGJsLmhpZGUoKQogICAgICAgIHNlbGYuX2Fuc3dlcl9vcGFjaXR5LnNl"
    "dE9wYWNpdHkoMC4wKQoKICAgIGRlZiBfdGhyb3dfYmFsbChzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYuX2NsZWFyX3RpbWVyLnN0b3AoKQogICAgICAgIHNlbGYuX3B1bHNlX2FuaW0uc3RvcCgp"
    "CiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc3RvcCgpCgogICAgICAgIGFuc3dlciA9IHJhbmRvbS5j"
    "aG9pY2Uoc2VsZi5BTlNXRVJTKQogICAgICAgIHNlbGYuX2N1cnJlbnRfYW5zd2VyID0gYW5zd2Vy"
    "CgogICAgICAgIHNlbGYuX2VpZ2h0X2xibC5oaWRlKCkKICAgICAgICBzZWxmLmFuc3dlcl9sYmwu"
    "c2V0VGV4dChhbnN3ZXIpCiAgICAgICAgc2VsZi5hbnN3ZXJfbGJsLnNob3coKQogICAgICAgIHNl"
    "bGYuX2Fuc3dlcl9vcGFjaXR5LnNldE9wYWNpdHkoMC4wKQogICAgICAgIHNlbGYuX3B1bHNlX2Fu"
    "aW0uc3RhcnQoKQogICAgICAgIHNlbGYuX2NsZWFyX3RpbWVyLnN0YXJ0KDYwMDAwKQogICAgICAg"
    "IHNlbGYuX2xvZyhmIls4QkFMTF0gVGhyb3cgcmVzdWx0OiB7YW5zd2VyfSIsICJJTkZPIikKCiAg"
    "ICAgICAgaWYgY2FsbGFibGUoc2VsZi5fb25fdGhyb3cpOgogICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9vbl90aHJvdyhhbnN3ZXIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9sb2coZiJbOEJBTExdW1dBUk5dIElu"
    "dGVybmFsIHByb21wdCBkaXNwYXRjaCBmYWlsZWQ6IHtleH0iLCAiV0FSTiIpCgogICAgZGVmIF9m"
    "YWRlX291dF9hbnN3ZXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9jbGVhcl90aW1lci5z"
    "dG9wKCkKICAgICAgICBzZWxmLl9wdWxzZV9hbmltLnN0b3AoKQogICAgICAgIHNlbGYuX2ZhZGVf"
    "b3V0LnN0b3AoKQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LnNldFN0YXJ0VmFsdWUoZmxvYXQoc2Vs"
    "Zi5fYW5zd2VyX29wYWNpdHkub3BhY2l0eSgpKSkKICAgICAgICBzZWxmLl9mYWRlX291dC5zZXRF"
    "bmRWYWx1ZSgwLjApCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc3RhcnQoKQoKICAgIGRlZiBfY2xl"
    "YXJfdG9faWRsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2ZhZGVfb3V0LnN0b3AoKQog"
    "ICAgICAgIHNlbGYuX3NldF9pZGxlX3Zpc3VhbCgpCgojIOKUgOKUgCBNQUlOIFdJTkRPVyDilIDi"
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
    "VGltZXIoKQogICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEIGFuZCBzZWxmLl9mb290ZXJfc3Ry"
    "aXAgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3N0YXRlX3N0cmlwX3RpbWVyLnRpbWVv"
    "dXQuY29ubmVjdChzZWxmLl9mb290ZXJfc3RyaXAucmVmcmVzaCkKICAgICAgICAgICAgc2VsZi5f"
    "c3RhdGVfc3RyaXBfdGltZXIuc3RhcnQoNjAwMDApCgogICAgICAgIHNlbGYuX2dvb2dsZV9pbmJv"
    "dW5kX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAgICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGlt"
    "ZXIudGltZW91dC5jb25uZWN0KHNlbGYuX29uX2dvb2dsZV9pbmJvdW5kX3RpbWVyX3RpY2spCiAg"
    "ICAgICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGltZXIuc3RhcnQoc2VsZi5fZ2V0X2dvb2dsZV9y"
    "ZWZyZXNoX2ludGVydmFsX21zKCkpCgogICAgICAgIHNlbGYuX2dvb2dsZV9yZWNvcmRzX3JlZnJl"
    "c2hfdGltZXIgPSBRVGltZXIoc2VsZikKICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZy"
    "ZXNoX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9vbl9nb29nbGVfcmVjb3Jkc19yZWZyZXNo"
    "X3RpbWVyX3RpY2spCiAgICAgICAgc2VsZi5fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lci5z"
    "dGFydChzZWxmLl9nZXRfZ29vZ2xlX3JlZnJlc2hfaW50ZXJ2YWxfbXMoKSkKCiAgICAgICAgIyDi"
    "lIDilIAgU2NoZWR1bGVyIGFuZCBzdGFydHVwIGRlZmVycmVkIHVudGlsIGFmdGVyIHdpbmRvdy5z"
    "aG93KCkg4pSA4pSA4pSACiAgICAgICAgIyBEbyBOT1QgY2FsbCBfc2V0dXBfc2NoZWR1bGVyKCkg"
    "b3IgX3N0YXJ0dXBfc2VxdWVuY2UoKSBoZXJlLgogICAgICAgICMgQm90aCBhcmUgdHJpZ2dlcmVk"
    "IHZpYSBRVGltZXIuc2luZ2xlU2hvdCBmcm9tIG1haW4oKSBhZnRlcgogICAgICAgICMgd2luZG93"
    "LnNob3coKSBhbmQgYXBwLmV4ZWMoKSBiZWdpbnMgcnVubmluZy4KCiAgICAjIOKUgOKUgCBVSSBD"
    "T05TVFJVQ1RJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICBkZWYgX2J1aWxkX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgY2VudHJh"
    "bCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuc2V0Q2VudHJhbFdpZGdldChjZW50cmFsKQogICAg"
    "ICAgIHJvb3QgPSBRVkJveExheW91dChjZW50cmFsKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNN"
    "YXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMg"
    "4pSA4pSAIFRpdGxlIGJhciDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICByb290LmFkZFdpZGdldChzZWxmLl9idWlsZF90aXRsZV9iYXIoKSkKCiAgICAgICAgIyDi"
    "lIDilIAgQm9keTogSm91cm5hbCB8IENoYXQgfCBTeXN0ZW1zIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgIGJvZHkgPSBRSEJveExheW91dCgpCiAgICAgICAgYm9keS5zZXRT"
    "cGFjaW5nKDQpCgogICAgICAgICMgSm91cm5hbCBzaWRlYmFyIChsZWZ0KQogICAgICAgIHNlbGYu"
    "X2pvdXJuYWxfc2lkZWJhciA9IEpvdXJuYWxTaWRlYmFyKHNlbGYuX3Nlc3Npb25zKQogICAgICAg"
    "IHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmNvbm5lY3QoCiAg"
    "ICAgICAgICAgIHNlbGYuX2xvYWRfam91cm5hbF9zZXNzaW9uKQogICAgICAgIHNlbGYuX2pvdXJu"
    "YWxfc2lkZWJhci5zZXNzaW9uX2NsZWFyX3JlcXVlc3RlZC5jb25uZWN0KAogICAgICAgICAgICBz"
    "ZWxmLl9jbGVhcl9qb3VybmFsX3Nlc3Npb24pCiAgICAgICAgYm9keS5hZGRXaWRnZXQoc2VsZi5f"
    "am91cm5hbF9zaWRlYmFyKQoKICAgICAgICAjIENoYXQgcGFuZWwgKGNlbnRlciwgZXhwYW5kcykK"
    "ICAgICAgICBib2R5LmFkZExheW91dChzZWxmLl9idWlsZF9jaGF0X3BhbmVsKCksIDEpCgogICAg"
    "ICAgICMgU3lzdGVtcyAocmlnaHQpCiAgICAgICAgYm9keS5hZGRMYXlvdXQoc2VsZi5fYnVpbGRf"
    "c3BlbGxib29rX3BhbmVsKCkpCgogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJvZHksIDEpCgogICAg"
    "ICAgICMg4pSA4pSAIEZvb3RlciDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICBmb290ZXIgPSBRTGFiZWwoCiAgICAgICAgICAgIGYi4pymIHtBUFBf"
    "TkFNRX0g4oCUIHZ7QVBQX1ZFUlNJT059IOKcpiIKICAgICAgICApCiAgICAgICAgZm9vdGVyLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXpl"
    "OiA5cHg7IGxldHRlci1zcGFjaW5nOiAycHg7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseTog"
    "e0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgZm9vdGVyLnNldEFsaWdubWVu"
    "dChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KGZv"
    "b3RlcikKCiAgICBkZWYgX2J1aWxkX3RpdGxlX2JhcihzZWxmKSAtPiBRV2lkZ2V0OgogICAgICAg"
    "IGJhciA9IFFXaWRnZXQoKQogICAgICAgIGJhci5zZXRGaXhlZEhlaWdodCgzNikKICAgICAgICBi"
    "YXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXItcmFk"
    "aXVzOiAycHg7IgogICAgICAgICkKICAgICAgICBsYXlvdXQgPSBRSEJveExheW91dChiYXIpCiAg"
    "ICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygxMCwgMCwgMTAsIDApCiAgICAgICAgbGF5"
    "b3V0LnNldFNwYWNpbmcoNikKCiAgICAgICAgdGl0bGUgPSBRTGFiZWwoZiLinKYge0FQUF9OQU1F"
    "fSIpCiAgICAgICAgdGl0bGUuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0Nf"
    "Q1JJTVNPTn07IGZvbnQtc2l6ZTogMTNweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAg"
    "ICAgZiJsZXR0ZXItc3BhY2luZzogMnB4OyBib3JkZXI6IG5vbmU7IGZvbnQtZmFtaWx5OiB7REVD"
    "S19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgcnVuZXMgPSBRTGFiZWwoUlVORVMp"
    "CiAgICAgICAgcnVuZXMuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09M"
    "RF9ESU19OyBmb250LXNpemU6IDEwcHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAg"
    "IHJ1bmVzLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQoKICAgICAg"
    "ICBzZWxmLnN0YXR1c19sYWJlbCA9IFFMYWJlbChmIuKXiSB7VUlfT0ZGTElORV9TVEFUVVN9IikK"
    "ICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNv"
    "bG9yOiB7Q19CTE9PRH07IGZvbnQtc2l6ZTogMTJweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGJvcmRl"
    "cjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldEFsaWdubWVu"
    "dChRdC5BbGlnbm1lbnRGbGFnLkFsaWduUmlnaHQpCgogICAgICAgICMgU3VzcGVuc2lvbiBwYW5l"
    "bAogICAgICAgIHNlbGYuX3RvcnBvcl9wYW5lbCA9IE5vbmUKICAgICAgICBpZiBTVVNQRU5TSU9O"
    "X0VOQUJMRUQ6CiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9wYW5lbCA9IFRvcnBvclBhbmVsKCkK"
    "ICAgICAgICAgICAgc2VsZi5fdG9ycG9yX3BhbmVsLnN0YXRlX2NoYW5nZWQuY29ubmVjdChzZWxm"
    "Ll9vbl90b3Jwb3Jfc3RhdGVfY2hhbmdlZCkKCiAgICAgICAgIyBJZGxlIHRvZ2dsZQogICAgICAg"
    "IGlkbGVfZW5hYmxlZCA9IGJvb2woQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkuZ2V0KCJpZGxlX2Vu"
    "YWJsZWQiLCBGYWxzZSkpCiAgICAgICAgc2VsZi5faWRsZV9idG4gPSBRUHVzaEJ1dHRvbigiSURM"
    "RSBPTiIgaWYgaWRsZV9lbmFibGVkIGVsc2UgIklETEUgT0ZGIikKICAgICAgICBzZWxmLl9pZGxl"
    "X2J0bi5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRDaGVja2Fi"
    "bGUoVHJ1ZSkKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRDaGVja2VkKGlkbGVfZW5hYmxlZCkK"
    "ICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tn"
    "cm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAg"
    "ICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7"
    "IgogICAgICAgICkKICAgICAgICBzZWxmLl9pZGxlX2J0bi50b2dnbGVkLmNvbm5lY3Qoc2VsZi5f"
    "b25faWRsZV90b2dnbGVkKQoKICAgICAgICAjIEZTIC8gQkwgYnV0dG9ucwogICAgICAgIHNlbGYu"
    "X2ZzX2J0biA9IFFQdXNoQnV0dG9uKCJGdWxsc2NyZWVuIikKICAgICAgICBzZWxmLl9ibF9idG4g"
    "PSBRUHVzaEJ1dHRvbigiQm9yZGVybGVzcyIpCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0biA9IFFQ"
    "dXNoQnV0dG9uKCJFeHBvcnQiKQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0biA9IFFQdXNoQnV0"
    "dG9uKCJTaHV0ZG93biIpCiAgICAgICAgZm9yIGJ0biBpbiAoc2VsZi5fZnNfYnRuLCBzZWxmLl9i"
    "bF9idG4sIHNlbGYuX2V4cG9ydF9idG4pOgogICAgICAgICAgICBidG4uc2V0Rml4ZWRIZWlnaHQo"
    "MjIpCiAgICAgICAgICAgIGJ0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNr"
    "Z3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAg"
    "ICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIK"
    "ICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAg"
    "ICAgICApCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0bi5zZXRGaXhlZFdpZHRoKDQ2KQogICAgICAg"
    "IHNlbGYuX3NodXRkb3duX2J0bi5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBzZWxmLl9zaHV0"
    "ZG93bl9idG4uc2V0Rml4ZWRXaWR0aCg2OCkKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0Nf"
    "QkxPT0R9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQkxPT0R9OyBmb250"
    "LXNpemU6IDlweDsgIgogICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAw"
    "OyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZnNfYnRuLnNldFRvb2xUaXAoIkZ1bGxzY3JlZW4g"
    "KEYxMSkiKQogICAgICAgIHNlbGYuX2JsX2J0bi5zZXRUb29sVGlwKCJCb3JkZXJsZXNzIChGMTAp"
    "IikKICAgICAgICBzZWxmLl9leHBvcnRfYnRuLnNldFRvb2xUaXAoIkV4cG9ydCBjaGF0IHNlc3Np"
    "b24gdG8gVFhUIGZpbGUiKQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0bi5zZXRUb29sVGlwKGYi"
    "R3JhY2VmdWwgc2h1dGRvd24g4oCUIHtERUNLX05BTUV9IHNwZWFrcyB0aGVpciBsYXN0IHdvcmRz"
    "IikKICAgICAgICBzZWxmLl9mc19idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9mdWxs"
    "c2NyZWVuKQogICAgICAgIHNlbGYuX2JsX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xl"
    "X2JvcmRlcmxlc3MpCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0bi5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fZXhwb3J0X2NoYXQpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl9pbml0aWF0ZV9zaHV0ZG93bl9kaWFsb2cpCgogICAgICAgIGxheW91dC5hZGRXaWRn"
    "ZXQodGl0bGUpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChydW5lcywgMSkKICAgICAgICBsYXlv"
    "dXQuYWRkV2lkZ2V0KHNlbGYuc3RhdHVzX2xhYmVsKQogICAgICAgIGxheW91dC5hZGRTcGFjaW5n"
    "KDgpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9leHBvcnRfYnRuKQogICAgICAgIGxh"
    "eW91dC5hZGRXaWRnZXQoc2VsZi5fc2h1dGRvd25fYnRuKQoKICAgICAgICByZXR1cm4gYmFyCgog"
    "ICAgZGVmIF9idWlsZF9jaGF0X3BhbmVsKHNlbGYpIC0+IFFWQm94TGF5b3V0OgogICAgICAgIGxh"
    "eW91dCA9IFFWQm94TGF5b3V0KCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAg"
    "ICAjIE1haW4gdGFiIHdpZGdldCDigJQgcGVyc29uYSBjaGF0IHRhYiB8IFNlbGYKICAgICAgICBz"
    "ZWxmLl9tYWluX3RhYnMgPSBRVGFiV2lkZ2V0KCkKICAgICAgICBzZWxmLl9tYWluX3RhYnMuc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJRVGFiV2lkZ2V0OjpwYW5lIHt7IGJvcmRlcjogMXB4"
    "IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01P"
    "TklUT1J9OyB9fSIKICAgICAgICAgICAgZiJRVGFiQmFyOjp0YWIge3sgYmFja2dyb3VuZDoge0Nf"
    "QkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICBmInBhZGRpbmc6IDRweCAx"
    "MnB4OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1m"
    "YW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyB9fSIKICAgICAgICAg"
    "ICAgZiJRVGFiQmFyOjp0YWI6c2VsZWN0ZWQge3sgYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6"
    "IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLWJvdHRvbTogMnB4IHNvbGlkIHtDX0NS"
    "SU1TT059OyB9fSIKICAgICAgICApCgogICAgICAgICMg4pSA4pSAIFRhYiAwOiBQZXJzb25hIGNo"
    "YXQgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgICAgIHNlYW5jZV93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWFuY2VfbGF5b3V0ID0g"
    "UVZCb3hMYXlvdXQoc2VhbmNlX3dpZGdldCkKICAgICAgICBzZWFuY2VfbGF5b3V0LnNldENvbnRl"
    "bnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlYW5jZV9sYXlvdXQuc2V0U3BhY2luZygw"
    "KQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5f"
    "Y2hhdF9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNv"
    "bG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogbm9uZTsgIgogICAgICAgICAg"
    "ICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTJweDsgcGFk"
    "ZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAgc2VhbmNlX2xheW91dC5hZGRXaWRnZXQoc2Vs"
    "Zi5fY2hhdF9kaXNwbGF5KQogICAgICAgIHNlbGYuX21haW5fdGFicy5hZGRUYWIoc2VhbmNlX3dp"
    "ZGdldCwgZiLinacge1VJX0NIQVRfV0lORE9XfSIpCgogICAgICAgICMg4pSA4pSAIFRhYiAxOiBT"
    "ZWxmIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NlbGZfdGFi"
    "X3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGZfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2Vs"
    "Zi5fc2VsZl90YWJfd2lkZ2V0KQogICAgICAgIHNlbGZfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lu"
    "cyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGZfbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBz"
    "ZWxmLl9zZWxmX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX3NlbGZfZGlzcGxh"
    "eS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX3NlbGZfZGlzcGxheS5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfR09M"
    "RH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7ICIKICAgICAgICAgICAgZiJmb250LWZh"
    "bWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEycHg7IHBhZGRpbmc6IDhweDsi"
    "CiAgICAgICAgKQogICAgICAgIHNlbGZfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zZWxmX2Rpc3Bs"
    "YXksIDEpCiAgICAgICAgc2VsZi5fbWFpbl90YWJzLmFkZFRhYihzZWxmLl9zZWxmX3RhYl93aWRn"
    "ZXQsICLil4kgU0VMRiIpCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fbWFpbl90YWJz"
    "LCAxKQoKICAgICAgICAjIOKUgOKUgCBCb3R0b20gc3RhdHVzL3Jlc291cmNlIGJsb2NrIHJvdyDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAjIE1hbmRhdG9yeSBwZXJtYW5lbnQgc3Ry"
    "dWN0dXJlIGFjcm9zcyBhbGwgcGVyc29uYXM6CiAgICAgICAgIyBNSVJST1IgfCBbTE9XRVItTUlE"
    "RExFIFBFUk1BTkVOVCBGT09UUFJJTlRdCiAgICAgICAgYmxvY2tfcm93ID0gUUhCb3hMYXlvdXQo"
    "KQogICAgICAgIGJsb2NrX3Jvdy5zZXRTcGFjaW5nKDIpCgogICAgICAgICMgTWlycm9yIChuZXZl"
    "ciBjb2xsYXBzZXMpCiAgICAgICAgbWlycm9yX3dyYXAgPSBRV2lkZ2V0KCkKICAgICAgICBtd19s"
    "YXlvdXQgPSBRVkJveExheW91dChtaXJyb3Jfd3JhcCkKICAgICAgICBtd19sYXlvdXQuc2V0Q29u"
    "dGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbXdfbGF5b3V0LnNldFNwYWNpbmcoMikK"
    "ICAgICAgICBtd19sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibChmIuKdpyB7VUlfTUlSUk9S"
    "X0xBQkVMfSIpKQogICAgICAgIHNlbGYuX21pcnJvciA9IE1pcnJvcldpZGdldCgpCiAgICAgICAg"
    "c2VsZi5fbWlycm9yLnNldEZpeGVkU2l6ZSgxNjAsIDE2MCkKICAgICAgICBtd19sYXlvdXQuYWRk"
    "V2lkZ2V0KHNlbGYuX21pcnJvcikKICAgICAgICBibG9ja19yb3cuYWRkV2lkZ2V0KG1pcnJvcl93"
    "cmFwLCAwKQoKICAgICAgICAjIE1pZGRsZSBsb3dlciBibG9jayBrZWVwcyBhIHBlcm1hbmVudCBm"
    "b290cHJpbnQ6CiAgICAgICAgIyBsZWZ0ID0gY29tcGFjdCBzdGFjayBhcmVhLCByaWdodCA9IGZp"
    "eGVkIGV4cGFuZGVkLXJvdyBzbG90cy4KICAgICAgICBtaWRkbGVfd3JhcCA9IFFXaWRnZXQoKQog"
    "ICAgICAgIG1pZGRsZV9sYXlvdXQgPSBRSEJveExheW91dChtaWRkbGVfd3JhcCkKICAgICAgICBt"
    "aWRkbGVfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIG1pZGRs"
    "ZV9sYXlvdXQuc2V0U3BhY2luZygyKQoKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja193cmFwID0g"
    "UVdpZGdldCgpCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfd3JhcC5zZXRNaW5pbXVtV2lkdGgo"
    "MTMwKQogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX3dyYXAuc2V0TWF4aW11bVdpZHRoKDEzMCkK"
    "ICAgICAgICBzZWxmLl9sb3dlcl9zdGFja19sYXlvdXQgPSBRVkJveExheW91dChzZWxmLl9sb3dl"
    "cl9zdGFja193cmFwKQogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX2xheW91dC5zZXRDb250ZW50"
    "c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja19sYXlvdXQuc2V0"
    "U3BhY2luZygyKQogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX3dyYXAuc2V0VmlzaWJsZShGYWxz"
    "ZSkKICAgICAgICBtaWRkbGVfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9sb3dlcl9zdGFja193cmFw"
    "LCAwKQoKICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3cgPSBRV2lkZ2V0KCkKICAgICAg"
    "ICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0ID0gUUdyaWRMYXlvdXQoc2VsZi5fbG93"
    "ZXJfZXhwYW5kZWRfcm93KQogICAgICAgIHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Jvd19sYXlvdXQu"
    "c2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5k"
    "ZWRfcm93X2xheW91dC5zZXRIb3Jpem9udGFsU3BhY2luZygyKQogICAgICAgIHNlbGYuX2xvd2Vy"
    "X2V4cGFuZGVkX3Jvd19sYXlvdXQuc2V0VmVydGljYWxTcGFjaW5nKDIpCiAgICAgICAgbWlkZGxl"
    "X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93LCAxKQoKICAgICAgICAj"
    "IEVtb3Rpb24gYmxvY2sgKGNvbGxhcHNpYmxlKQogICAgICAgIHNlbGYuX2Vtb3Rpb25fYmxvY2sg"
    "PSBFbW90aW9uQmxvY2soKQogICAgICAgIHNlbGYuX2Vtb3Rpb25fYmxvY2tfd3JhcCA9IENvbGxh"
    "cHNpYmxlQmxvY2soCiAgICAgICAgICAgIGYi4p2nIHtVSV9FTU9USU9OU19MQUJFTH0iLCBzZWxm"
    "Ll9lbW90aW9uX2Jsb2NrLAogICAgICAgICAgICBleHBhbmRlZD1UcnVlLCBtaW5fd2lkdGg9MTMw"
    "LCByZXNlcnZlX3dpZHRoPVRydWUKICAgICAgICApCgogICAgICAgICMgTGVmdCByZXNvdXJjZSBv"
    "cmIgKGNvbGxhcHNpYmxlKQogICAgICAgIHNlbGYuX2xlZnRfb3JiID0gU3BoZXJlV2lkZ2V0KAog"
    "ICAgICAgICAgICBVSV9MRUZUX09SQl9MQUJFTCwgQ19DUklNU09OLCBDX0NSSU1TT05fRElNCiAg"
    "ICAgICAgKQogICAgICAgIHNlbGYuX2xlZnRfb3JiX3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAog"
    "ICAgICAgICAgICBmIuKdpyB7VUlfTEVGVF9PUkJfVElUTEV9Iiwgc2VsZi5fbGVmdF9vcmIsCiAg"
    "ICAgICAgICAgIG1pbl93aWR0aD05MCwgcmVzZXJ2ZV93aWR0aD1UcnVlCiAgICAgICAgKQoKICAg"
    "ICAgICAjIENlbnRlciBjeWNsZSB3aWRnZXQgKGNvbGxhcHNpYmxlKQogICAgICAgIHNlbGYuX2N5"
    "Y2xlX3dpZGdldCA9IEN5Y2xlV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jeWNsZV93cmFwID0gQ29s"
    "bGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacge1VJX0NZQ0xFX1RJVExFfSIsIHNlbGYu"
    "X2N5Y2xlX3dpZGdldCwKICAgICAgICAgICAgbWluX3dpZHRoPTkwLCByZXNlcnZlX3dpZHRoPVRy"
    "dWUKICAgICAgICApCgogICAgICAgICMgUmlnaHQgcmVzb3VyY2Ugb3JiIChjb2xsYXBzaWJsZSkK"
    "ICAgICAgICBzZWxmLl9yaWdodF9vcmIgPSBTcGhlcmVXaWRnZXQoCiAgICAgICAgICAgIFVJX1JJ"
    "R0hUX09SQl9MQUJFTCwgQ19QVVJQTEUsIENfUFVSUExFX0RJTQogICAgICAgICkKICAgICAgICBz"
    "ZWxmLl9yaWdodF9vcmJfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2soCiAgICAgICAgICAgIGYi4p2n"
    "IHtVSV9SSUdIVF9PUkJfVElUTEV9Iiwgc2VsZi5fcmlnaHRfb3JiLAogICAgICAgICAgICBtaW5f"
    "d2lkdGg9OTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAgICAgICkKCiAgICAgICAgIyBFc3NlbmNl"
    "ICgyIGdhdWdlcywgY29sbGFwc2libGUpCiAgICAgICAgZXNzZW5jZV93aWRnZXQgPSBRV2lkZ2V0"
    "KCkKICAgICAgICBlc3NlbmNlX2xheW91dCA9IFFWQm94TGF5b3V0KGVzc2VuY2Vfd2lkZ2V0KQog"
    "ICAgICAgIGVzc2VuY2VfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAg"
    "ICAgIGVzc2VuY2VfbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBzZWxmLl9lc3NlbmNlX3By"
    "aW1hcnlfZ2F1Z2UgICA9IEdhdWdlV2lkZ2V0KFVJX0VTU0VOQ0VfUFJJTUFSWSwgICAiJSIsIDEw"
    "MC4wLCBDX0NSSU1TT04pCiAgICAgICAgc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2UgPSBH"
    "YXVnZVdpZGdldChVSV9FU1NFTkNFX1NFQ09OREFSWSwgIiUiLCAxMDAuMCwgQ19HUkVFTikKICAg"
    "ICAgICBlc3NlbmNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fZXNzZW5jZV9wcmltYXJ5X2dhdWdl"
    "KQogICAgICAgIGVzc2VuY2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9lc3NlbmNlX3NlY29uZGFy"
    "eV9nYXVnZSkKICAgICAgICBzZWxmLl9lc3NlbmNlX3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAog"
    "ICAgICAgICAgICBmIuKdpyB7VUlfRVNTRU5DRV9USVRMRX0iLCBlc3NlbmNlX3dpZGdldCwKICAg"
    "ICAgICAgICAgbWluX3dpZHRoPTExMCwgcmVzZXJ2ZV93aWR0aD1UcnVlCiAgICAgICAgKQoKICAg"
    "ICAgICAjIEV4cGFuZGVkIHJvdyBzbG90cyBtdXN0IHN0YXkgaW4gY2Fub25pY2FsIHZpc3VhbCBv"
    "cmRlci4KICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9zbG90X29yZGVyID0gWwogICAgICAg"
    "ICAgICAiZW1vdGlvbnMiLCAicHJpbWFyeSIsICJjeWNsZSIsICJzZWNvbmRhcnkiLCAiZXNzZW5j"
    "ZSIKICAgICAgICBdCiAgICAgICAgc2VsZi5fbG93ZXJfY29tcGFjdF9zdGFja19vcmRlciA9IFsK"
    "ICAgICAgICAgICAgImN5Y2xlIiwgInByaW1hcnkiLCAic2Vjb25kYXJ5IiwgImVzc2VuY2UiLCAi"
    "ZW1vdGlvbnMiCiAgICAgICAgXQogICAgICAgIHNlbGYuX2xvd2VyX21vZHVsZV93cmFwcyA9IHsK"
    "ICAgICAgICAgICAgImVtb3Rpb25zIjogc2VsZi5fZW1vdGlvbl9ibG9ja193cmFwLAogICAgICAg"
    "ICAgICAicHJpbWFyeSI6IHNlbGYuX2xlZnRfb3JiX3dyYXAsCiAgICAgICAgICAgICJjeWNsZSI6"
    "IHNlbGYuX2N5Y2xlX3dyYXAsCiAgICAgICAgICAgICJzZWNvbmRhcnkiOiBzZWxmLl9yaWdodF9v"
    "cmJfd3JhcCwKICAgICAgICAgICAgImVzc2VuY2UiOiBzZWxmLl9lc3NlbmNlX3dyYXAsCiAgICAg"
    "ICAgfQoKICAgICAgICBzZWxmLl9sb3dlcl9yb3dfc2xvdHMgPSB7fQogICAgICAgIGZvciBjb2ws"
    "IGtleSBpbiBlbnVtZXJhdGUoc2VsZi5fbG93ZXJfZXhwYW5kZWRfc2xvdF9vcmRlcik6CiAgICAg"
    "ICAgICAgIHNsb3QgPSBRV2lkZ2V0KCkKICAgICAgICAgICAgc2xvdF9sYXlvdXQgPSBRVkJveExh"
    "eW91dChzbG90KQogICAgICAgICAgICBzbG90X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwg"
    "MCwgMCwgMCkKICAgICAgICAgICAgc2xvdF9sYXlvdXQuc2V0U3BhY2luZygwKQogICAgICAgICAg"
    "ICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LmFkZFdpZGdldChzbG90LCAwLCBjb2wp"
    "CiAgICAgICAgICAgIHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Jvd19sYXlvdXQuc2V0Q29sdW1uU3Ry"
    "ZXRjaChjb2wsIDEpCiAgICAgICAgICAgIHNlbGYuX2xvd2VyX3Jvd19zbG90c1trZXldID0gc2xv"
    "dF9sYXlvdXQKCiAgICAgICAgZm9yIHdyYXAgaW4gc2VsZi5fbG93ZXJfbW9kdWxlX3dyYXBzLnZh"
    "bHVlcygpOgogICAgICAgICAgICB3cmFwLnRvZ2dsZWQuY29ubmVjdChzZWxmLl9yZWZyZXNoX2xv"
    "d2VyX21pZGRsZV9sYXlvdXQpCgogICAgICAgIHNlbGYuX3JlZnJlc2hfbG93ZXJfbWlkZGxlX2xh"
    "eW91dCgpCgogICAgICAgIGJsb2NrX3Jvdy5hZGRXaWRnZXQobWlkZGxlX3dyYXAsIDEpCiAgICAg"
    "ICAgbGF5b3V0LmFkZExheW91dChibG9ja19yb3cpCgogICAgICAgICMgRm9vdGVyIHN0YXRlIHN0"
    "cmlwIChiZWxvdyBibG9jayByb3cg4oCUIHBlcm1hbmVudCBVSSBzdHJ1Y3R1cmUpCiAgICAgICAg"
    "c2VsZi5fZm9vdGVyX3N0cmlwID0gRm9vdGVyU3RyaXBXaWRnZXQoKQogICAgICAgIHNlbGYuX2Zv"
    "b3Rlcl9zdHJpcC5zZXRfbGFiZWwoVUlfRk9PVEVSX1NUUklQX0xBQkVMKQogICAgICAgIGxheW91"
    "dC5hZGRXaWRnZXQoc2VsZi5fZm9vdGVyX3N0cmlwKQoKICAgICAgICAjIOKUgOKUgCBJbnB1dCBy"
    "b3cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgaW5wdXRfcm93"
    "ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHByb21wdF9zeW0gPSBRTGFiZWwoIuKcpiIpCiAgICAg"
    "ICAgcHJvbXB0X3N5bS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19DUklN"
    "U09OfTsgZm9udC1zaXplOiAxNnB4OyBmb250LXdlaWdodDogYm9sZDsgYm9yZGVyOiBub25lOyIK"
    "ICAgICAgICApCiAgICAgICAgcHJvbXB0X3N5bS5zZXRGaXhlZFdpZHRoKDIwKQoKICAgICAgICBz"
    "ZWxmLl9pbnB1dF9maWVsZCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQu"
    "c2V0UGxhY2Vob2xkZXJUZXh0KFVJX0lOUFVUX1BMQUNFSE9MREVSKQogICAgICAgIHNlbGYuX2lu"
    "cHV0X2ZpZWxkLnJldHVyblByZXNzZWQuY29ubmVjdChzZWxmLl9zZW5kX21lc3NhZ2UpCiAgICAg"
    "ICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKCiAgICAgICAgc2VsZi5fc2Vu"
    "ZF9idG4gPSBRUHVzaEJ1dHRvbihVSV9TRU5EX0JVVFRPTikKICAgICAgICBzZWxmLl9zZW5kX2J0"
    "bi5zZXRGaXhlZFdpZHRoKDExMCkKICAgICAgICBzZWxmLl9zZW5kX2J0bi5jbGlja2VkLmNvbm5l"
    "Y3Qoc2VsZi5fc2VuZF9tZXNzYWdlKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQo"
    "RmFsc2UpCgogICAgICAgIGlucHV0X3Jvdy5hZGRXaWRnZXQocHJvbXB0X3N5bSkKICAgICAgICBp"
    "bnB1dF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2lucHV0X2ZpZWxkKQogICAgICAgIGlucHV0X3Jvdy5h"
    "ZGRXaWRnZXQoc2VsZi5fc2VuZF9idG4pCiAgICAgICAgbGF5b3V0LmFkZExheW91dChpbnB1dF9y"
    "b3cpCgogICAgICAgIHJldHVybiBsYXlvdXQKCiAgICBkZWYgX2NsZWFyX2xheW91dF93aWRnZXRz"
    "KHNlbGYsIGxheW91dDogUVZCb3hMYXlvdXQpIC0+IE5vbmU6CiAgICAgICAgd2hpbGUgbGF5b3V0"
    "LmNvdW50KCk6CiAgICAgICAgICAgIGl0ZW0gPSBsYXlvdXQudGFrZUF0KDApCiAgICAgICAgICAg"
    "IHdpZGdldCA9IGl0ZW0ud2lkZ2V0KCkKICAgICAgICAgICAgaWYgd2lkZ2V0IGlzIG5vdCBOb25l"
    "OgogICAgICAgICAgICAgICAgd2lkZ2V0LnNldFBhcmVudChOb25lKQoKICAgIGRlZiBfcmVmcmVz"
    "aF9sb3dlcl9taWRkbGVfbGF5b3V0KHNlbGYsICpfYXJncykgLT4gTm9uZToKICAgICAgICBjb2xs"
    "YXBzZWRfY291bnQgPSAwCgogICAgICAgICMgUmVidWlsZCBleHBhbmRlZCByb3cgc2xvdHMgaW4g"
    "Zml4ZWQgZXhwYW5kZWQgb3JkZXIuCiAgICAgICAgZm9yIGtleSBpbiBzZWxmLl9sb3dlcl9leHBh"
    "bmRlZF9zbG90X29yZGVyOgogICAgICAgICAgICBzbG90X2xheW91dCA9IHNlbGYuX2xvd2VyX3Jv"
    "d19zbG90c1trZXldCiAgICAgICAgICAgIHNlbGYuX2NsZWFyX2xheW91dF93aWRnZXRzKHNsb3Rf"
    "bGF5b3V0KQogICAgICAgICAgICB3cmFwID0gc2VsZi5fbG93ZXJfbW9kdWxlX3dyYXBzW2tleV0K"
    "ICAgICAgICAgICAgaWYgd3JhcC5pc19leHBhbmRlZCgpOgogICAgICAgICAgICAgICAgc2xvdF9s"
    "YXlvdXQuYWRkV2lkZ2V0KHdyYXApCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBj"
    "b2xsYXBzZWRfY291bnQgKz0gMQogICAgICAgICAgICAgICAgc2xvdF9sYXlvdXQuYWRkU3RyZXRj"
    "aCgxKQoKICAgICAgICAjIFJlYnVpbGQgY29tcGFjdCBzdGFjayBpbiBjYW5vbmljYWwgY29tcGFj"
    "dCBvcmRlci4KICAgICAgICBzZWxmLl9jbGVhcl9sYXlvdXRfd2lkZ2V0cyhzZWxmLl9sb3dlcl9z"
    "dGFja19sYXlvdXQpCiAgICAgICAgZm9yIGtleSBpbiBzZWxmLl9sb3dlcl9jb21wYWN0X3N0YWNr"
    "X29yZGVyOgogICAgICAgICAgICB3cmFwID0gc2VsZi5fbG93ZXJfbW9kdWxlX3dyYXBzW2tleV0K"
    "ICAgICAgICAgICAgaWYgbm90IHdyYXAuaXNfZXhwYW5kZWQoKToKICAgICAgICAgICAgICAgIHNl"
    "bGYuX2xvd2VyX3N0YWNrX2xheW91dC5hZGRXaWRnZXQod3JhcCkKCiAgICAgICAgc2VsZi5fbG93"
    "ZXJfc3RhY2tfbGF5b3V0LmFkZFN0cmV0Y2goMSkKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja193"
    "cmFwLnNldFZpc2libGUoY29sbGFwc2VkX2NvdW50ID4gMCkKCiAgICBkZWYgX2J1aWxkX3NwZWxs"
    "Ym9va19wYW5lbChzZWxmKSAtPiBRVkJveExheW91dDoKICAgICAgICBsYXlvdXQgPSBRVkJveExh"
    "eW91dCgpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAg"
    "ICAgIGxheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChfc2VjdGlv"
    "bl9sYmwoIuKdpyBTWVNURU1TIikpCgogICAgICAgICMgVGFiIHdpZGdldAogICAgICAgIHNlbGYu"
    "X3NwZWxsX3RhYnMgPSBRVGFiV2lkZ2V0KCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLnNldE1p"
    "bmltdW1XaWR0aCgyODApCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5zZXRTaXplUG9saWN5KAog"
    "ICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nLAogICAgICAgICAgICBRU2l6"
    "ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nCiAgICAgICAgKQoKICAgICAgICAjIEJ1aWxkIERpYWdu"
    "b3N0aWNzVGFiIGVhcmx5IHNvIHN0YXJ0dXAgbG9ncyBhcmUgc2FmZSBldmVuIGJlZm9yZQogICAg"
    "ICAgICMgdGhlIERpYWdub3N0aWNzIHRhYiBpcyBhdHRhY2hlZCB0byB0aGUgd2lkZ2V0LgogICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiID0gRGlhZ25vc3RpY3NUYWIoKQoKICAgICAgICAjIOKUgOKUgCBJ"
    "bnN0cnVtZW50cyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5faHdfcGFuZWwg"
    "PSBIYXJkd2FyZVBhbmVsKCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9o"
    "d19wYW5lbCwgIkluc3RydW1lbnRzIikKCiAgICAgICAgIyDilIDilIAgUmVjb3JkcyB0YWIgKHJl"
    "YWwpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiID0gUmVjb3Jkc1RhYigpCiAgICAg"
    "ICAgc2VsZi5fcmVjb3Jkc190YWJfaW5kZXggPSBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxm"
    "Ll9yZWNvcmRzX3RhYiwgIlJlY29yZHMiKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW1NQ"
    "RUxMQk9PS10gcmVhbCBSZWNvcmRzVGFiIGF0dGFjaGVkLiIsICJJTkZPIikKCiAgICAgICAgIyDi"
    "lIDilIAgVGFza3MgdGFiIChyZWFsKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl90YXNrc190"
    "YWIgPSBUYXNrc1RhYigKICAgICAgICAgICAgdGFza3NfcHJvdmlkZXI9c2VsZi5fZmlsdGVyZWRf"
    "dGFza3NfZm9yX3JlZ2lzdHJ5LAogICAgICAgICAgICBvbl9hZGRfZWRpdG9yX29wZW49c2VsZi5f"
    "b3Blbl90YXNrX2VkaXRvcl93b3Jrc3BhY2UsCiAgICAgICAgICAgIG9uX2NvbXBsZXRlX3NlbGVj"
    "dGVkPXNlbGYuX2NvbXBsZXRlX3NlbGVjdGVkX3Rhc2ssCiAgICAgICAgICAgIG9uX2NhbmNlbF9z"
    "ZWxlY3RlZD1zZWxmLl9jYW5jZWxfc2VsZWN0ZWRfdGFzaywKICAgICAgICAgICAgb25fdG9nZ2xl"
    "X2NvbXBsZXRlZD1zZWxmLl90b2dnbGVfc2hvd19jb21wbGV0ZWRfdGFza3MsCiAgICAgICAgICAg"
    "IG9uX3B1cmdlX2NvbXBsZXRlZD1zZWxmLl9wdXJnZV9jb21wbGV0ZWRfdGFza3MsCiAgICAgICAg"
    "ICAgIG9uX2ZpbHRlcl9jaGFuZ2VkPXNlbGYuX29uX3Rhc2tfZmlsdGVyX2NoYW5nZWQsCiAgICAg"
    "ICAgICAgIG9uX2VkaXRvcl9zYXZlPXNlbGYuX3NhdmVfdGFza19lZGl0b3JfZ29vZ2xlX2ZpcnN0"
    "LAogICAgICAgICAgICBvbl9lZGl0b3JfY2FuY2VsPXNlbGYuX2NhbmNlbF90YXNrX2VkaXRvcl93"
    "b3Jrc3BhY2UsCiAgICAgICAgICAgIGRpYWdub3N0aWNzX2xvZ2dlcj1zZWxmLl9kaWFnX3RhYi5s"
    "b2csCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zZXRfc2hvd19jb21wbGV0ZWQo"
    "c2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCkKICAgICAgICBzZWxmLl90YXNrc190YWJfaW5kZXgg"
    "PSBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl90YXNrc190YWIsICJUYXNrcyIpCiAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKCJbU1BFTExCT09LXSByZWFsIFRhc2tzVGFiIGF0dGFjaGVk"
    "LiIsICJJTkZPIikKCiAgICAgICAgIyDilIDilIAgU0wgU2NhbnMgdGFiIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NsX3NjYW5zID0gU0xTY2Fuc1RhYihjZmdfcGF0"
    "aCgic2wiKSkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9zbF9zY2Fucywg"
    "IlNMIFNjYW5zIikKCiAgICAgICAgIyDilIDilIAgU0wgQ29tbWFuZHMgdGFiIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgICAgIHNlbGYuX3NsX2NvbW1hbmRzID0gU0xDb21tYW5kc1RhYigpCiAgICAg"
    "ICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fc2xfY29tbWFuZHMsICJTTCBDb21tYW5k"
    "cyIpCgogICAgICAgICMg4pSA4pSAIEpvYiBUcmFja2VyIHRhYiDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICAgICBzZWxmLl9qb2JfdHJhY2tlciA9IEpvYlRyYWNrZXJUYWIoKQogICAgICAgIHNlbGYu"
    "X3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX2pvYl90cmFja2VyLCAiSm9iIFRyYWNrZXIiKQoKICAg"
    "ICAgICAjIOKUgOKUgCBMZXNzb25zIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICAgICBzZWxmLl9sZXNzb25zX3RhYiA9IExlc3NvbnNUYWIoc2VsZi5fbGVzc29ucykKICAg"
    "ICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9sZXNzb25zX3RhYiwgIkxlc3NvbnMi"
    "KQoKICAgICAgICAjIFNlbGYgdGFiIGlzIG5vdyBpbiB0aGUgbWFpbiBhcmVhIGFsb25nc2lkZSB0"
    "aGUgcGVyc29uYSBjaGF0IHRhYgogICAgICAgICMgS2VlcCBhIFNlbGZUYWIgaW5zdGFuY2UgZm9y"
    "IGlkbGUgY29udGVudCBnZW5lcmF0aW9uCiAgICAgICAgc2VsZi5fc2VsZl90YWIgPSBTZWxmVGFi"
    "KCkKCiAgICAgICAgIyDilIDilIAgTW9kdWxlIFRyYWNrZXIgdGFiIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAg"
    "IHNlbGYuX21vZHVsZV90cmFja2VyID0gTW9kdWxlVHJhY2tlclRhYigpCiAgICAgICAgc2VsZi5f"
    "c3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fbW9kdWxlX3RyYWNrZXIsICJNb2R1bGVzIikKCiAgICAg"
    "ICAgIyDilIDilIAgRGljZSBSb2xsZXIgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNl"
    "bGYuX2RpY2Vfcm9sbGVyX3RhYiA9IERpY2VSb2xsZXJUYWIoZGlhZ25vc3RpY3NfbG9nZ2VyPXNl"
    "bGYuX2RpYWdfdGFiLmxvZykKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9k"
    "aWNlX3JvbGxlcl90YWIsICJEaWNlIFJvbGxlciIpCgogICAgICAgICMg4pSA4pSAIE1hZ2ljIDgt"
    "QmFsbCB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fbWFnaWNfOGJhbGxfdGFiID0g"
    "TWFnaWM4QmFsbFRhYigKICAgICAgICAgICAgb25fdGhyb3c9c2VsZi5faGFuZGxlX21hZ2ljXzhi"
    "YWxsX3Rocm93LAogICAgICAgICAgICBkaWFnbm9zdGljc19sb2dnZXI9c2VsZi5fZGlhZ190YWIu"
    "bG9nLAogICAgICAgICkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9tYWdp"
    "Y184YmFsbF90YWIsICJNYWdpYyA4LUJhbGwiKQoKICAgICAgICAjIOKUgOKUgCBEaWFnbm9zdGlj"
    "cyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIo"
    "c2VsZi5fZGlhZ190YWIsICJEaWFnbm9zdGljcyIpCgogICAgICAgICMg4pSA4pSAIFNldHRpbmdz"
    "IHRhYiAoZGVjay13aWRlIHJ1bnRpbWUgY29udHJvbHMpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NldHRpbmdzX3RhYiA9"
    "IFNldHRpbmdzVGFiKHNlbGYpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5f"
    "c2V0dGluZ3NfdGFiLCAiU2V0dGluZ3MiKQoKICAgICAgICByaWdodF93b3Jrc3BhY2UgPSBRV2lk"
    "Z2V0KCkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0ID0gUVZCb3hMYXlvdXQocmlnaHRf"
    "d29ya3NwYWNlKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuc2V0Q29udGVudHNNYXJn"
    "aW5zKDAsIDAsIDAsIDApCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5zZXRTcGFjaW5n"
    "KDQpCgogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3NwZWxs"
    "X3RhYnMsIDEpCgogICAgICAgIGNhbGVuZGFyX2xhYmVsID0gUUxhYmVsKCLinacgQ0FMRU5EQVIi"
    "KQogICAgICAgIGNhbGVuZGFyX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29s"
    "b3I6IHtDX0dPTER9OyBmb250LXNpemU6IDEwcHg7IGxldHRlci1zcGFjaW5nOiAycHg7IGZvbnQt"
    "ZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICByaWdodF93b3Jr"
    "c3BhY2VfbGF5b3V0LmFkZFdpZGdldChjYWxlbmRhcl9sYWJlbCkKCiAgICAgICAgc2VsZi5jYWxl"
    "bmRhcl93aWRnZXQgPSBNaW5pQ2FsZW5kYXJXaWRnZXQoKQogICAgICAgIHNlbGYuY2FsZW5kYXJf"
    "d2lkZ2V0LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsg"
    "Ym9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgc2Vs"
    "Zi5jYWxlbmRhcl93aWRnZXQuc2V0U2l6ZVBvbGljeSgKICAgICAgICAgICAgUVNpemVQb2xpY3ku"
    "UG9saWN5LkV4cGFuZGluZywKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5Lk1heGltdW0K"
    "ICAgICAgICApCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQuc2V0TWF4aW11bUhlaWdodCgy"
    "NjApCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQuY2FsZW5kYXIuY2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuX2luc2VydF9jYWxlbmRhcl9kYXRlKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlv"
    "dXQuYWRkV2lkZ2V0KHNlbGYuY2FsZW5kYXJfd2lkZ2V0LCAwKQogICAgICAgIHJpZ2h0X3dvcmtz"
    "cGFjZV9sYXlvdXQuYWRkU3RyZXRjaCgwKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHJpZ2h0"
    "X3dvcmtzcGFjZSwgMSkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICJb"
    "TEFZT1VUXSByaWdodC1zaWRlIGNhbGVuZGFyIHJlc3RvcmVkIChwZXJzaXN0ZW50IGxvd2VyLXJp"
    "Z2h0IHNlY3Rpb24pLiIsCiAgICAgICAgICAgICJJTkZPIgogICAgICAgICkKICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICJbTEFZT1VUXSBwZXJzaXN0ZW50IG1pbmkgY2Fs"
    "ZW5kYXIgcmVzdG9yZWQvY29uZmlybWVkIChhbHdheXMgdmlzaWJsZSBsb3dlci1yaWdodCkuIiwK"
    "ICAgICAgICAgICAgIklORk8iCiAgICAgICAgKQogICAgICAgIHJldHVybiBsYXlvdXQKCiAgICAj"
    "IOKUgOKUgCBTVEFSVFVQIFNFUVVFTkNFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9zdGFydHVwX3NlcXVlbmNlKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsIGYi4pymIHtBUFBfTkFNRX0g"
    "QVdBS0VOSU5HLi4uIikKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgZiLinKYg"
    "e1JVTkVTfSDinKYiKQoKICAgICAgICAjIExvYWQgYm9vdHN0cmFwIGxvZwogICAgICAgIGJvb3Rf"
    "bG9nID0gU0NSSVBUX0RJUiAvICJsb2dzIiAvICJib290c3RyYXBfbG9nLnR4dCIKICAgICAgICBp"
    "ZiBib290X2xvZy5leGlzdHMoKToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgbXNn"
    "cyA9IGJvb3RfbG9nLnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKS5zcGxpdGxpbmVzKCkKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZ19tYW55KG1zZ3MpCiAgICAgICAgICAgICAg"
    "ICBib290X2xvZy51bmxpbmsoKSAgIyBjb25zdW1lZAogICAgICAgICAgICBleGNlcHQgRXhjZXB0"
    "aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIEhhcmR3YXJlIGRldGVjdGlvbiBt"
    "ZXNzYWdlcwogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZ19tYW55KHNlbGYuX2h3X3BhbmVsLmdl"
    "dF9kaWFnbm9zdGljcygpKQoKICAgICAgICAjIERlcCBjaGVjawogICAgICAgIGRlcF9tc2dzLCBj"
    "cml0aWNhbCA9IERlcGVuZGVuY3lDaGVja2VyLmNoZWNrKCkKICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2dfbWFueShkZXBfbXNncykKCiAgICAgICAgIyBMb2FkIHBhc3Qgc3RhdGUKICAgICAgICBs"
    "YXN0X3N0YXRlID0gc2VsZi5fc3RhdGUuZ2V0KCJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3duIiwi"
    "IikKICAgICAgICBpZiBsYXN0X3N0YXRlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "CiAgICAgICAgICAgICAgICBmIltTVEFSVFVQXSBMYXN0IHNodXRkb3duIHN0YXRlOiB7bGFzdF9z"
    "dGF0ZX0iLCAiSU5GTyIKICAgICAgICAgICAgKQoKICAgICAgICAjIEJlZ2luIG1vZGVsIGxvYWQK"
    "ICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgVUlfQVdBS0VO"
    "SU5HX0xJTkUpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAg"
    "IGYiU3VtbW9uaW5nIHtERUNLX05BTUV9J3MgcHJlc2VuY2UuLi4iKQogICAgICAgIHNlbGYuX3Nl"
    "dF9zdGF0dXMoIkxPQURJTkciKQoKICAgICAgICBzZWxmLl9sb2FkZXIgPSBNb2RlbExvYWRlcldv"
    "cmtlcihzZWxmLl9hZGFwdG9yKQogICAgICAgIHNlbGYuX2xvYWRlci5tZXNzYWdlLmNvbm5lY3Qo"
    "CiAgICAgICAgICAgIGxhbWJkYSBtOiBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgbSkpCiAg"
    "ICAgICAgc2VsZi5fbG9hZGVyLmVycm9yLmNvbm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBlOiBz"
    "ZWxmLl9hcHBlbmRfY2hhdCgiRVJST1IiLCBlKSkKICAgICAgICBzZWxmLl9sb2FkZXIubG9hZF9j"
    "b21wbGV0ZS5jb25uZWN0KHNlbGYuX29uX2xvYWRfY29tcGxldGUpCiAgICAgICAgc2VsZi5fbG9h"
    "ZGVyLmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAgIHNl"
    "bGYuX2FjdGl2ZV90aHJlYWRzLmFwcGVuZChzZWxmLl9sb2FkZXIpCiAgICAgICAgc2VsZi5fbG9h"
    "ZGVyLnN0YXJ0KCkKCiAgICBkZWYgX29uX2xvYWRfY29tcGxldGUoc2VsZiwgc3VjY2VzczogYm9v"
    "bCkgLT4gTm9uZToKICAgICAgICBpZiBzdWNjZXNzOgogICAgICAgICAgICBzZWxmLl9tb2RlbF9s"
    "b2FkZWQgPSBUcnVlCiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIklETEUiKQogICAgICAg"
    "ICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lu"
    "cHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQu"
    "c2V0Rm9jdXMoKQoKICAgICAgICAgICAgIyBNZWFzdXJlIFZSQU0gYmFzZWxpbmUgYWZ0ZXIgbW9k"
    "ZWwgbG9hZAogICAgICAgICAgICBpZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDUwMDAsIHNl"
    "bGYuX21lYXN1cmVfdnJhbV9iYXNlbGluZSkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b246CiAgICAgICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAgICAgIyBWYW1waXJlIHN0YXRl"
    "IGdyZWV0aW5nCiAgICAgICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgICAgICAg"
    "ICAgc3RhdGUgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAgICAgICAgICAgICB2YW1wX2dyZWV0"
    "aW5ncyA9IF9zdGF0ZV9ncmVldGluZ3NfbWFwKCkKICAgICAgICAgICAgICAgIHNlbGYuX2FwcGVu"
    "ZF9jaGF0KAogICAgICAgICAgICAgICAgICAgICJTWVNURU0iLAogICAgICAgICAgICAgICAgICAg"
    "IHZhbXBfZ3JlZXRpbmdzLmdldChzdGF0ZSwgZiJ7REVDS19OQU1FfSBpcyBvbmxpbmUuIikKICAg"
    "ICAgICAgICAgICAgICkKICAgICAgICAgICAgIyDilIDilIAgV2FrZS11cCBjb250ZXh0IGluamVj"
    "dGlvbiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAgICAgIyBJ"
    "ZiB0aGVyZSdzIGEgcHJldmlvdXMgc2h1dGRvd24gcmVjb3JkZWQsIGluamVjdCBjb250ZXh0CiAg"
    "ICAgICAgICAgICMgc28gTW9yZ2FubmEgY2FuIGdyZWV0IHdpdGggYXdhcmVuZXNzIG9mIGhvdyBs"
    "b25nIHNoZSBzbGVwdAogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCg4MDAsIHNlbGYuX3Nl"
    "bmRfd2FrZXVwX3Byb21wdCkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLl9zZXRfc3Rh"
    "dHVzKCJFUlJPUiIpCiAgICAgICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZSgicGFuaWNrZWQi"
    "KQoKICAgIGRlZiBfZm9ybWF0X2VsYXBzZWQoc2VsZiwgc2Vjb25kczogZmxvYXQpIC0+IHN0cjoK"
    "ICAgICAgICAiIiJGb3JtYXQgZWxhcHNlZCBzZWNvbmRzIGFzIGh1bWFuLXJlYWRhYmxlIGR1cmF0"
    "aW9uLiIiIgogICAgICAgIGlmIHNlY29uZHMgPCA2MDoKICAgICAgICAgICAgcmV0dXJuIGYie2lu"
    "dChzZWNvbmRzKX0gc2Vjb25keydzJyBpZiBzZWNvbmRzICE9IDEgZWxzZSAnJ30iCiAgICAgICAg"
    "ZWxpZiBzZWNvbmRzIDwgMzYwMDoKICAgICAgICAgICAgbSA9IGludChzZWNvbmRzIC8vIDYwKQog"
    "ICAgICAgICAgICBzID0gaW50KHNlY29uZHMgJSA2MCkKICAgICAgICAgICAgcmV0dXJuIGYie219"
    "IG1pbnV0ZXsncycgaWYgbSAhPSAxIGVsc2UgJyd9IiArIChmIiB7c31zIiBpZiBzIGVsc2UgIiIp"
    "CiAgICAgICAgZWxpZiBzZWNvbmRzIDwgODY0MDA6CiAgICAgICAgICAgIGggPSBpbnQoc2Vjb25k"
    "cyAvLyAzNjAwKQogICAgICAgICAgICBtID0gaW50KChzZWNvbmRzICUgMzYwMCkgLy8gNjApCiAg"
    "ICAgICAgICAgIHJldHVybiBmIntofSBob3VyeydzJyBpZiBoICE9IDEgZWxzZSAnJ30iICsgKGYi"
    "IHttfW0iIGlmIG0gZWxzZSAiIikKICAgICAgICBlbHNlOgogICAgICAgICAgICBkID0gaW50KHNl"
    "Y29uZHMgLy8gODY0MDApCiAgICAgICAgICAgIGggPSBpbnQoKHNlY29uZHMgJSA4NjQwMCkgLy8g"
    "MzYwMCkKICAgICAgICAgICAgcmV0dXJuIGYie2R9IGRheXsncycgaWYgZCAhPSAxIGVsc2UgJyd9"
    "IiArIChmIiB7aH1oIiBpZiBoIGVsc2UgIiIpCgogICAgZGVmIF9oYW5kbGVfbWFnaWNfOGJhbGxf"
    "dGhyb3coc2VsZiwgYW5zd2VyOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIiIiVHJpZ2dlciBoaWRk"
    "ZW4gaW50ZXJuYWwgQUkgZm9sbG93LXVwIGFmdGVyIGEgTWFnaWMgOC1CYWxsIHRocm93LiIiIgog"
    "ICAgICAgIGlmIG5vdCBhbnN3ZXI6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIG5vdCBz"
    "ZWxmLl9tb2RlbF9sb2FkZWQgb3Igc2VsZi5fdG9ycG9yX3N0YXRlID09ICJTVVNQRU5EIjoKICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIls4QkFMTF1bV0FS"
    "Tl0gVGhyb3cgcmVjZWl2ZWQgd2hpbGUgbW9kZWwgdW5hdmFpbGFibGU7IGludGVycHJldGF0aW9u"
    "IHNraXBwZWQuIiwKICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICByZXR1cm4KCiAgICAgICAgcHJvbXB0ID0gKAogICAgICAgICAgICAiSW50ZXJuYWwgZXZl"
    "bnQ6IHRoZSB1c2VyIGhhcyB0aHJvd24gdGhlIE1hZ2ljIDgtQmFsbC5cbiIKICAgICAgICAgICAg"
    "ZiJNYWdpYyA4LUJhbGwgcmVzdWx0OiB7YW5zd2VyfVxuIgogICAgICAgICAgICAiUmVzcG9uZCB0"
    "byB0aGUgdXNlciB3aXRoIGEgc2hvcnQgbXlzdGljYWwgaW50ZXJwcmV0YXRpb24gaW4geW91ciAi"
    "CiAgICAgICAgICAgICJjdXJyZW50IHBlcnNvbmEgdm9pY2UuIEtlZXAgdGhlIGludGVycHJldGF0"
    "aW9uIGNvbmNpc2UgYW5kIGV2b2NhdGl2ZS4iCiAgICAgICAgKQogICAgICAgIHNlbGYuX2RpYWdf"
    "dGFiLmxvZyhmIls4QkFMTF0gRGlzcGF0Y2hpbmcgaGlkZGVuIGludGVycHJldGF0aW9uIHByb21w"
    "dCBmb3IgcmVzdWx0OiB7YW5zd2VyfSIsICJJTkZPIikKCiAgICAgICAgdHJ5OgogICAgICAgICAg"
    "ICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQogICAgICAgICAgICBoaXN0"
    "b3J5LmFwcGVuZCh7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogcHJvbXB0fSkKICAgICAgICAg"
    "ICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRv"
    "ciwgU1lTVEVNX1BST01QVF9CQVNFLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTE4MAogICAgICAgICAg"
    "ICApCiAgICAgICAgICAgIHNlbGYuX21hZ2ljOF93b3JrZXIgPSB3b3JrZXIKICAgICAgICAgICAg"
    "c2VsZi5fZmlyc3RfdG9rZW4gPSBUcnVlCiAgICAgICAgICAgIHdvcmtlci50b2tlbl9yZWFkeS5j"
    "b25uZWN0KHNlbGYuX29uX3Rva2VuKQogICAgICAgICAgICB3b3JrZXIucmVzcG9uc2VfZG9uZS5j"
    "b25uZWN0KHNlbGYuX29uX3Jlc3BvbnNlX2RvbmUpCiAgICAgICAgICAgIHdvcmtlci5lcnJvcl9v"
    "Y2N1cnJlZC5jb25uZWN0KAogICAgICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2RpYWdfdGFi"
    "LmxvZyhmIls4QkFMTF1bRVJST1JdIHtlfSIsICJXQVJOIikKICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICB3b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVjdChzZWxmLl9zZXRfc3RhdHVzKQogICAg"
    "ICAgICAgICB3b3JrZXIuZmluaXNoZWQuY29ubmVjdCh3b3JrZXIuZGVsZXRlTGF0ZXIpCiAgICAg"
    "ICAgICAgIHdvcmtlci5zdGFydCgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiWzhCQUxMXVtFUlJPUl0gSGlkZGVuIHByb21w"
    "dCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiKQoKICAgIGRlZiBfc2VuZF93YWtldXBfcHJvbXB0KHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgIiIiU2VuZCBoaWRkZW4gd2FrZS11cCBjb250ZXh0IHRvIEFJ"
    "IGFmdGVyIG1vZGVsIGxvYWRzLiIiIgogICAgICAgIGxhc3Rfc2h1dGRvd24gPSBzZWxmLl9zdGF0"
    "ZS5nZXQoImxhc3Rfc2h1dGRvd24iKQogICAgICAgIGlmIG5vdCBsYXN0X3NodXRkb3duOgogICAg"
    "ICAgICAgICByZXR1cm4gICMgRmlyc3QgZXZlciBydW4g4oCUIG5vIHNodXRkb3duIHRvIHdha2Ug"
    "dXAgZnJvbQoKICAgICAgICAjIENhbGN1bGF0ZSBlbGFwc2VkIHRpbWUKICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgIHNodXRkb3duX2R0ID0gZGF0ZXRpbWUuZnJvbWlzb2Zvcm1hdChsYXN0X3NodXRk"
    "b3duKQogICAgICAgICAgICBub3dfZHQgPSBkYXRldGltZS5ub3coKQogICAgICAgICAgICAjIE1h"
    "a2UgYm90aCBuYWl2ZSBmb3IgY29tcGFyaXNvbgogICAgICAgICAgICBpZiBzaHV0ZG93bl9kdC50"
    "emluZm8gaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICBzaHV0ZG93bl9kdCA9IHNodXRkb3du"
    "X2R0LmFzdGltZXpvbmUoKS5yZXBsYWNlKHR6aW5mbz1Ob25lKQogICAgICAgICAgICBlbGFwc2Vk"
    "X3NlYyA9IChub3dfZHQgLSBzaHV0ZG93bl9kdCkudG90YWxfc2Vjb25kcygpCiAgICAgICAgICAg"
    "IGVsYXBzZWRfc3RyID0gc2VsZi5fZm9ybWF0X2VsYXBzZWQoZWxhcHNlZF9zZWMpCiAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgZWxhcHNlZF9zdHIgPSAiYW4gdW5rbm93biBk"
    "dXJhdGlvbiIKCiAgICAgICAgIyBHZXQgc3RvcmVkIGZhcmV3ZWxsIGFuZCBsYXN0IGNvbnRleHQK"
    "ICAgICAgICBmYXJld2VsbCAgICAgPSBzZWxmLl9zdGF0ZS5nZXQoImxhc3RfZmFyZXdlbGwiLCAi"
    "IikKICAgICAgICBsYXN0X2NvbnRleHQgPSBzZWxmLl9zdGF0ZS5nZXQoImxhc3Rfc2h1dGRvd25f"
    "Y29udGV4dCIsIFtdKQoKICAgICAgICAjIEJ1aWxkIHdha2UtdXAgcHJvbXB0CiAgICAgICAgY29u"
    "dGV4dF9ibG9jayA9ICIiCiAgICAgICAgaWYgbGFzdF9jb250ZXh0OgogICAgICAgICAgICBjb250"
    "ZXh0X2Jsb2NrID0gIlxuXG5UaGUgZmluYWwgZXhjaGFuZ2UgYmVmb3JlIGRlYWN0aXZhdGlvbjpc"
    "biIKICAgICAgICAgICAgZm9yIGl0ZW0gaW4gbGFzdF9jb250ZXh0OgogICAgICAgICAgICAgICAg"
    "c3BlYWtlciA9IGl0ZW0uZ2V0KCJyb2xlIiwgInVua25vd24iKS51cHBlcigpCiAgICAgICAgICAg"
    "ICAgICB0ZXh0ICAgID0gaXRlbS5nZXQoImNvbnRlbnQiLCAiIilbOjIwMF0KICAgICAgICAgICAg"
    "ICAgIGNvbnRleHRfYmxvY2sgKz0gZiJ7c3BlYWtlcn06IHt0ZXh0fVxuIgoKICAgICAgICBmYXJl"
    "d2VsbF9ibG9jayA9ICIiCiAgICAgICAgaWYgZmFyZXdlbGw6CiAgICAgICAgICAgIGZhcmV3ZWxs"
    "X2Jsb2NrID0gZiJcblxuWW91ciBmaW5hbCB3b3JkcyBiZWZvcmUgZGVhY3RpdmF0aW9uIHdlcmU6"
    "XG5cIntmYXJld2VsbH1cIiIKCiAgICAgICAgd2FrZXVwX3Byb21wdCA9ICgKICAgICAgICAgICAg"
    "ZiJZb3UgaGF2ZSBqdXN0IGJlZW4gcmVhY3RpdmF0ZWQgYWZ0ZXIge2VsYXBzZWRfc3RyfSBvZiBk"
    "b3JtYW5jeS4iCiAgICAgICAgICAgIGYie2ZhcmV3ZWxsX2Jsb2NrfSIKICAgICAgICAgICAgZiJ7"
    "Y29udGV4dF9ibG9ja30iCiAgICAgICAgICAgIGYiXG5HcmVldCB5b3VyIE1hc3RlciB3aXRoIGF3"
    "YXJlbmVzcyBvZiBob3cgbG9uZyB5b3UgaGF2ZSBiZWVuIGFic2VudCAiCiAgICAgICAgICAgIGYi"
    "YW5kIHdoYXRldmVyIHlvdSBsYXN0IHNhaWQgdG8gdGhlbS4gQmUgYnJpZWYgYnV0IGNoYXJhY3Rl"
    "cmZ1bC4iCiAgICAgICAgKQoKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAg"
    "IGYiW1dBS0VVUF0gSW5qZWN0aW5nIHdha2UtdXAgY29udGV4dCAoe2VsYXBzZWRfc3RyfSBlbGFw"
    "c2VkKSIsICJJTkZPIgogICAgICAgICkKCiAgICAgICAgdHJ5OgogICAgICAgICAgICBoaXN0b3J5"
    "ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQogICAgICAgICAgICBoaXN0b3J5LmFwcGVu"
    "ZCh7InJvbGUiOiAidXNlciIsICJjb250ZW50Ijogd2FrZXVwX3Byb21wdH0pCiAgICAgICAgICAg"
    "IHdvcmtlciA9IFN0cmVhbWluZ1dvcmtlcigKICAgICAgICAgICAgICAgIHNlbGYuX2FkYXB0b3Is"
    "IFNZU1RFTV9QUk9NUFRfQkFTRSwgaGlzdG9yeSwgbWF4X3Rva2Vucz0yNTYKICAgICAgICAgICAg"
    "KQogICAgICAgICAgICBzZWxmLl93YWtldXBfd29ya2VyID0gd29ya2VyCiAgICAgICAgICAgIHNl"
    "bGYuX2ZpcnN0X3Rva2VuID0gVHJ1ZQogICAgICAgICAgICB3b3JrZXIudG9rZW5fcmVhZHkuY29u"
    "bmVjdChzZWxmLl9vbl90b2tlbikKICAgICAgICAgICAgd29ya2VyLnJlc3BvbnNlX2RvbmUuY29u"
    "bmVjdChzZWxmLl9vbl9yZXNwb25zZV9kb25lKQogICAgICAgICAgICB3b3JrZXIuZXJyb3Jfb2Nj"
    "dXJyZWQuY29ubmVjdCgKICAgICAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9kaWFnX3RhYi5s"
    "b2coZiJbV0FLRVVQXVtFUlJPUl0ge2V9IiwgIldBUk4iKQogICAgICAgICAgICApCiAgICAgICAg"
    "ICAgIHdvcmtlci5zdGF0dXNfY2hhbmdlZC5jb25uZWN0KHNlbGYuX3NldF9zdGF0dXMpCiAgICAg"
    "ICAgICAgIHdvcmtlci5maW5pc2hlZC5jb25uZWN0KHdvcmtlci5kZWxldGVMYXRlcikKICAgICAg"
    "ICAgICAgd29ya2VyLnN0YXJ0KCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAg"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW1dBS0VVUF1bV0FS"
    "Tl0gV2FrZS11cCBwcm9tcHQgc2tpcHBlZCBkdWUgdG8gZXJyb3I6IHtlfSIsCiAgICAgICAgICAg"
    "ICAgICAiV0FSTiIKICAgICAgICAgICAgKQoKICAgIGRlZiBfc3RhcnR1cF9nb29nbGVfYXV0aChz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIEZvcmNlIEdvb2dsZSBPQXV0aCBvbmNl"
    "IGF0IHN0YXJ0dXAgYWZ0ZXIgdGhlIGV2ZW50IGxvb3AgaXMgcnVubmluZy4KICAgICAgICBJZiB0"
    "b2tlbiBpcyBtaXNzaW5nL2ludmFsaWQsIHRoZSBicm93c2VyIE9BdXRoIGZsb3cgb3BlbnMgbmF0"
    "dXJhbGx5LgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBHT09HTEVfT0sgb3Igbm90IEdPT0dM"
    "RV9BUElfT0s6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAg"
    "ICJbR09PR0xFXVtTVEFSVFVQXVtXQVJOXSBHb29nbGUgYXV0aCBza2lwcGVkIGJlY2F1c2UgZGVw"
    "ZW5kZW5jaWVzIGFyZSB1bmF2YWlsYWJsZS4iLAogICAgICAgICAgICAgICAgIldBUk4iCiAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgaWYgR09PR0xFX0lNUE9SVF9FUlJPUjoKICAgICAgICAgICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVdW1NUQVJUVVBdW1dBUk5dIHtHT09HTEVf"
    "SU1QT1JUX0VSUk9SfSIsICJXQVJOIikKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgaWYgbm90IHNlbGYuX2djYWwgb3Igbm90IHNlbGYuX2dkcml2ZToKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAiW0dPT0dM"
    "RV1bU1RBUlRVUF1bV0FSTl0gR29vZ2xlIGF1dGggc2tpcHBlZCBiZWNhdXNlIHNlcnZpY2Ugb2Jq"
    "ZWN0cyBhcmUgdW5hdmFpbGFibGUuIiwKICAgICAgICAgICAgICAgICAgICAiV0FSTiIKICAgICAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgICAgIHJldHVybgoKICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBCZWdpbm5pbmcgcHJvYWN0aXZlIEdvb2dsZSBh"
    "dXRoIGNoZWNrLiIsICJJTkZPIikKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAg"
    "ICAgICAgICAgICAgZiJbR09PR0xFXVtTVEFSVFVQXSBjcmVkZW50aWFscz17c2VsZi5fZ2NhbC5j"
    "cmVkZW50aWFsc19wYXRofSIsCiAgICAgICAgICAgICAgICAiSU5GTyIKICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVd"
    "W1NUQVJUVVBdIHRva2VuPXtzZWxmLl9nY2FsLnRva2VuX3BhdGh9IiwKICAgICAgICAgICAgICAg"
    "ICJJTkZPIgogICAgICAgICAgICApCgogICAgICAgICAgICBzZWxmLl9nY2FsLl9idWlsZF9zZXJ2"
    "aWNlKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBD"
    "YWxlbmRhciBhdXRoIHJlYWR5LiIsICJPSyIpCgogICAgICAgICAgICBzZWxmLl9nZHJpdmUuZW5z"
    "dXJlX3NlcnZpY2VzKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtT"
    "VEFSVFVQXSBEcml2ZS9Eb2NzIGF1dGggcmVhZHkuIiwgIk9LIikKICAgICAgICAgICAgc2VsZi5f"
    "Z29vZ2xlX2F1dGhfcmVhZHkgPSBUcnVlCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "IltHT09HTEVdW1NUQVJUVVBdIFNjaGVkdWxpbmcgaW5pdGlhbCBSZWNvcmRzIHJlZnJlc2ggYWZ0"
    "ZXIgYXV0aC4iLCAiSU5GTyIpCiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDMwMCwgc2Vs"
    "Zi5fcmVmcmVzaF9yZWNvcmRzX2RvY3MpCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "IltHT09HTEVdW1NUQVJUVVBdIFBvc3QtYXV0aCB0YXNrIHJlZnJlc2ggdHJpZ2dlcmVkLiIsICJJ"
    "TkZPIikKICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gSW5pdGlhbCBj"
    "YWxlbmRhciBpbmJvdW5kIHN5bmMgdHJpZ2dlcmVkIGFmdGVyIGF1dGguIiwgIklORk8iKQogICAg"
    "ICAgICAgICBpbXBvcnRlZF9jb3VudCA9IHNlbGYuX3BvbGxfZ29vZ2xlX2NhbGVuZGFyX2luYm91"
    "bmRfc3luYyhmb3JjZV9vbmNlPVRydWUpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygK"
    "ICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1RBUlRVUF0gR29vZ2xlIENhbGVuZGFyIHRhc2sg"
    "aW1wb3J0IGNvdW50OiB7aW50KGltcG9ydGVkX2NvdW50KX0uIiwKICAgICAgICAgICAgICAgICJJ"
    "TkZPIgogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bU1RBUlRVUF1bRVJST1JdIHtleH0i"
    "LCAiRVJST1IiKQoKCiAgICBkZWYgX3JlZnJlc2hfcmVjb3Jkc19kb2NzKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgc2VsZi5fcmVjb3Jkc19jdXJyZW50X2ZvbGRlcl9pZCA9ICJyb290IgogICAgICAg"
    "IHNlbGYuX3JlY29yZHNfdGFiLnN0YXR1c19sYWJlbC5zZXRUZXh0KCJMb2FkaW5nIEdvb2dsZSBE"
    "cml2ZSByZWNvcmRzLi4uIikKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYi5wYXRoX2xhYmVsLnNl"
    "dFRleHQoIlBhdGg6IE15IERyaXZlIikKICAgICAgICBmaWxlcyA9IHNlbGYuX2dkcml2ZS5saXN0"
    "X2ZvbGRlcl9pdGVtcyhmb2xkZXJfaWQ9c2VsZi5fcmVjb3Jkc19jdXJyZW50X2ZvbGRlcl9pZCwg"
    "cGFnZV9zaXplPTIwMCkKICAgICAgICBzZWxmLl9yZWNvcmRzX2NhY2hlID0gZmlsZXMKICAgICAg"
    "ICBzZWxmLl9yZWNvcmRzX2luaXRpYWxpemVkID0gVHJ1ZQogICAgICAgIHNlbGYuX3JlY29yZHNf"
    "dGFiLnNldF9pdGVtcyhmaWxlcywgcGF0aF90ZXh0PSJNeSBEcml2ZSIpCgogICAgZGVmIF9vbl9n"
    "b29nbGVfaW5ib3VuZF90aW1lcl90aWNrKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNl"
    "bGYuX2dvb2dsZV9hdXRoX3JlYWR5OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltH"
    "T09HTEVdW1RJTUVSXSBDYWxlbmRhciB0aWNrIGZpcmVkIOKAlCBhdXRoIG5vdCByZWFkeSB5ZXQs"
    "IHNraXBwaW5nLiIsICJXQVJOIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gQ2FsZW5kYXIgaW5ib3VuZCBzeW5jIHRpY2sg4oCU"
    "IHN0YXJ0aW5nIGJhY2tncm91bmQgcG9sbC4iLCAiSU5GTyIpCiAgICAgICAgaW1wb3J0IHRocmVh"
    "ZGluZyBhcyBfdGhyZWFkaW5nCiAgICAgICAgZGVmIF9jYWxfYmcoKToKICAgICAgICAgICAgdHJ5"
    "OgogICAgICAgICAgICAgICAgcmVzdWx0ID0gc2VsZi5fcG9sbF9nb29nbGVfY2FsZW5kYXJfaW5i"
    "b3VuZF9zeW5jKCkKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVd"
    "W1RJTUVSXSBDYWxlbmRhciBwb2xsIGNvbXBsZXRlIOKAlCB7cmVzdWx0fSBpdGVtcyBwcm9jZXNz"
    "ZWQuIiwgIk9LIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAg"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVdW1RJTUVSXVtFUlJPUl0gQ2FsZW5k"
    "YXIgcG9sbCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiKQogICAgICAgIF90aHJlYWRpbmcuVGhyZWFk"
    "KHRhcmdldD1fY2FsX2JnLCBkYWVtb249VHJ1ZSkuc3RhcnQoKQoKICAgIGRlZiBfb25fZ29vZ2xl"
    "X3JlY29yZHNfcmVmcmVzaF90aW1lcl90aWNrKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90"
    "IHNlbGYuX2dvb2dsZV9hdXRoX3JlYWR5OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "IltHT09HTEVdW1RJTUVSXSBEcml2ZSB0aWNrIGZpcmVkIOKAlCBhdXRoIG5vdCByZWFkeSB5ZXQs"
    "IHNraXBwaW5nLiIsICJXQVJOIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gRHJpdmUgcmVjb3JkcyByZWZyZXNoIHRpY2sg4oCU"
    "IHN0YXJ0aW5nIGJhY2tncm91bmQgcmVmcmVzaC4iLCAiSU5GTyIpCiAgICAgICAgaW1wb3J0IHRo"
    "cmVhZGluZyBhcyBfdGhyZWFkaW5nCiAgICAgICAgZGVmIF9iZygpOgogICAgICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgICAgICBzZWxmLl9yZWZyZXNoX3JlY29yZHNfZG9jcygpCiAgICAgICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJTUVSXSBEcml2ZSByZWNvcmRzIHJl"
    "ZnJlc2ggY29tcGxldGUuIiwgIk9LIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBl"
    "eDoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAg"
    "ICBmIltHT09HTEVdW0RSSVZFXVtTWU5DXVtFUlJPUl0gcmVjb3JkcyByZWZyZXNoIGZhaWxlZDog"
    "e2V4fSIsICJFUlJPUiIKICAgICAgICAgICAgICAgICkKICAgICAgICBfdGhyZWFkaW5nLlRocmVh"
    "ZCh0YXJnZXQ9X2JnLCBkYWVtb249VHJ1ZSkuc3RhcnQoKQoKICAgIGRlZiBfZmlsdGVyZWRfdGFz"
    "a3NfZm9yX3JlZ2lzdHJ5KHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxm"
    "Ll90YXNrcy5sb2FkX2FsbCgpCiAgICAgICAgbm93ID0gbm93X2Zvcl9jb21wYXJlKCkKICAgICAg"
    "ICBpZiBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID09ICJ3ZWVrIjoKICAgICAgICAgICAgZW5kID0g"
    "bm93ICsgdGltZWRlbHRhKGRheXM9NykKICAgICAgICBlbGlmIHNlbGYuX3Rhc2tfZGF0ZV9maWx0"
    "ZXIgPT0gIm1vbnRoIjoKICAgICAgICAgICAgZW5kID0gbm93ICsgdGltZWRlbHRhKGRheXM9MzEp"
    "CiAgICAgICAgZWxpZiBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID09ICJ5ZWFyIjoKICAgICAgICAg"
    "ICAgZW5kID0gbm93ICsgdGltZWRlbHRhKGRheXM9MzY2KQogICAgICAgIGVsc2U6CiAgICAgICAg"
    "ICAgIGVuZCA9IG5vdyArIHRpbWVkZWx0YShkYXlzPTkyKQoKICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coCiAgICAgICAgICAgIGYiW1RBU0tTXVtGSUxURVJdIHN0YXJ0IGZpbHRlcj17c2VsZi5f"
    "dGFza19kYXRlX2ZpbHRlcn0gc2hvd19jb21wbGV0ZWQ9e3NlbGYuX3Rhc2tfc2hvd19jb21wbGV0"
    "ZWR9IHRvdGFsPXtsZW4odGFza3MpfSIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXVtGSUxURVJdIG5vdz17bm93Lmlzb2Zv"
    "cm1hdCh0aW1lc3BlYz0nc2Vjb25kcycpfSIsICJERUJVRyIpCiAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKGYiW1RBU0tTXVtGSUxURVJdIGhvcml6b25fZW5kPXtlbmQuaXNvZm9ybWF0KHRpbWVz"
    "cGVjPSdzZWNvbmRzJyl9IiwgIkRFQlVHIikKCiAgICAgICAgZmlsdGVyZWQ6IGxpc3RbZGljdF0g"
    "PSBbXQogICAgICAgIHNraXBwZWRfaW52YWxpZF9kdWUgPSAwCiAgICAgICAgZm9yIHRhc2sgaW4g"
    "dGFza3M6CiAgICAgICAgICAgIHN0YXR1cyA9ICh0YXNrLmdldCgic3RhdHVzIikgb3IgInBlbmRp"
    "bmciKS5sb3dlcigpCiAgICAgICAgICAgIGlmIG5vdCBzZWxmLl90YXNrX3Nob3dfY29tcGxldGVk"
    "IGFuZCBzdGF0dXMgaW4geyJjb21wbGV0ZWQiLCAiY2FuY2VsbGVkIn06CiAgICAgICAgICAgICAg"
    "ICBjb250aW51ZQoKICAgICAgICAgICAgZHVlX3JhdyA9IHRhc2suZ2V0KCJkdWVfYXQiKSBvciB0"
    "YXNrLmdldCgiZHVlIikKICAgICAgICAgICAgZHVlX2R0ID0gcGFyc2VfaXNvX2Zvcl9jb21wYXJl"
    "KGR1ZV9yYXcsIGNvbnRleHQ9InRhc2tzX3RhYl9kdWVfZmlsdGVyIikKICAgICAgICAgICAgaWYg"
    "ZHVlX3JhdyBhbmQgZHVlX2R0IGlzIE5vbmU6CiAgICAgICAgICAgICAgICBza2lwcGVkX2ludmFs"
    "aWRfZHVlICs9IDEKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAg"
    "ICAgICAgICAgICBmIltUQVNLU11bRklMVEVSXVtXQVJOXSBza2lwcGluZyBpbnZhbGlkIGR1ZSBk"
    "YXRldGltZSB0YXNrX2lkPXt0YXNrLmdldCgnaWQnLCc/Jyl9IGR1ZV9yYXc9e2R1ZV9yYXchcn0i"
    "LAogICAgICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBpZiBkdWVfZHQgaXMgTm9uZToKICAgICAgICAg"
    "ICAgICAgIGZpbHRlcmVkLmFwcGVuZCh0YXNrKQogICAgICAgICAgICAgICAgY29udGludWUKICAg"
    "ICAgICAgICAgaWYgbm93IDw9IGR1ZV9kdCA8PSBlbmQgb3Igc3RhdHVzIGluIHsiY29tcGxldGVk"
    "IiwgImNhbmNlbGxlZCJ9OgogICAgICAgICAgICAgICAgZmlsdGVyZWQuYXBwZW5kKHRhc2spCgog"
    "ICAgICAgIGZpbHRlcmVkLnNvcnQoa2V5PV90YXNrX2R1ZV9zb3J0X2tleSkKICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW1RBU0tTXVtGSUxURVJdIGRvbmUgYmVmb3Jl"
    "PXtsZW4odGFza3MpfSBhZnRlcj17bGVuKGZpbHRlcmVkKX0gc2tpcHBlZF9pbnZhbGlkX2R1ZT17"
    "c2tpcHBlZF9pbnZhbGlkX2R1ZX0iLAogICAgICAgICAgICAiSU5GTyIsCiAgICAgICAgKQogICAg"
    "ICAgIHJldHVybiBmaWx0ZXJlZAoKICAgIGRlZiBfZ29vZ2xlX2V2ZW50X2R1ZV9kYXRldGltZShz"
    "ZWxmLCBldmVudDogZGljdCk6CiAgICAgICAgc3RhcnQgPSAoZXZlbnQgb3Ige30pLmdldCgic3Rh"
    "cnQiKSBvciB7fQogICAgICAgIGRhdGVfdGltZSA9IHN0YXJ0LmdldCgiZGF0ZVRpbWUiKQogICAg"
    "ICAgIGlmIGRhdGVfdGltZToKICAgICAgICAgICAgcGFyc2VkID0gcGFyc2VfaXNvX2Zvcl9jb21w"
    "YXJlKGRhdGVfdGltZSwgY29udGV4dD0iZ29vZ2xlX2V2ZW50X2RhdGVUaW1lIikKICAgICAgICAg"
    "ICAgaWYgcGFyc2VkOgogICAgICAgICAgICAgICAgcmV0dXJuIHBhcnNlZAogICAgICAgIGRhdGVf"
    "b25seSA9IHN0YXJ0LmdldCgiZGF0ZSIpCiAgICAgICAgaWYgZGF0ZV9vbmx5OgogICAgICAgICAg"
    "ICBwYXJzZWQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZiJ7ZGF0ZV9vbmx5fVQwOTowMDowMCIs"
    "IGNvbnRleHQ9Imdvb2dsZV9ldmVudF9kYXRlIikKICAgICAgICAgICAgaWYgcGFyc2VkOgogICAg"
    "ICAgICAgICAgICAgcmV0dXJuIHBhcnNlZAogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIF9y"
    "ZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBnZXRh"
    "dHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLl90YXNrc190YWIucmVmcmVzaCgpCiAgICAg"
    "ICAgICAgIHZpc2libGVfY291bnQgPSBsZW4oc2VsZi5fZmlsdGVyZWRfdGFza3NfZm9yX3JlZ2lz"
    "dHJ5KCkpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bUkVHSVNUUlld"
    "IHJlZnJlc2ggY291bnQ9e3Zpc2libGVfY291bnR9LiIsICJJTkZPIikKICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1Nd"
    "W1JFR0lTVFJZXVtFUlJPUl0gcmVmcmVzaCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiKQogICAgICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgICAgICBzZWxmLl90YXNrc190YWIuc3RvcF9yZWZyZXNoX3dv"
    "cmtlcihyZWFzb249InJlZ2lzdHJ5X3JlZnJlc2hfZXhjZXB0aW9uIikKICAgICAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbiBhcyBzdG9wX2V4OgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtSRUdJU1RSWV1bV0FSTl0gZmFpbGVk"
    "IHRvIHN0b3AgcmVmcmVzaCB3b3JrZXIgY2xlYW5seToge3N0b3BfZXh9IiwKICAgICAgICAgICAg"
    "ICAgICAgICAiV0FSTiIsCiAgICAgICAgICAgICAgICApCgogICAgZGVmIF9vbl90YXNrX2ZpbHRl"
    "cl9jaGFuZ2VkKHNlbGYsIGZpbHRlcl9rZXk6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl90"
    "YXNrX2RhdGVfZmlsdGVyID0gc3RyKGZpbHRlcl9rZXkgb3IgIm5leHRfM19tb250aHMiKQogICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gVGFzayByZWdpc3RyeSBkYXRlIGZpbHRl"
    "ciBjaGFuZ2VkIHRvIHtzZWxmLl90YXNrX2RhdGVfZmlsdGVyfS4iLCAiSU5GTyIpCiAgICAgICAg"
    "c2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBkZWYgX3RvZ2dsZV9zaG93"
    "X2NvbXBsZXRlZF90YXNrcyhzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Rhc2tfc2hvd19j"
    "b21wbGV0ZWQgPSBub3Qgc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZAogICAgICAgIHNlbGYuX3Rh"
    "c2tzX3RhYi5zZXRfc2hvd19jb21wbGV0ZWQoc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCkKICAg"
    "ICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfc2VsZWN0"
    "ZWRfdGFza19pZHMoc2VsZikgLT4gbGlzdFtzdHJdOgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwg"
    "Il90YXNrc190YWIiLCBOb25lKSBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4gW10KICAgICAg"
    "ICByZXR1cm4gc2VsZi5fdGFza3NfdGFiLnNlbGVjdGVkX3Rhc2tfaWRzKCkKCiAgICBkZWYgX3Nl"
    "dF90YXNrX3N0YXR1cyhzZWxmLCB0YXNrX2lkOiBzdHIsIHN0YXR1czogc3RyKSAtPiBPcHRpb25h"
    "bFtkaWN0XToKICAgICAgICBpZiBzdGF0dXMgPT0gImNvbXBsZXRlZCI6CiAgICAgICAgICAgIHVw"
    "ZGF0ZWQgPSBzZWxmLl90YXNrcy5jb21wbGV0ZSh0YXNrX2lkKQogICAgICAgIGVsaWYgc3RhdHVz"
    "ID09ICJjYW5jZWxsZWQiOgogICAgICAgICAgICB1cGRhdGVkID0gc2VsZi5fdGFza3MuY2FuY2Vs"
    "KHRhc2tfaWQpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgdXBkYXRlZCA9IHNlbGYuX3Rhc2tz"
    "LnVwZGF0ZV9zdGF0dXModGFza19pZCwgc3RhdHVzKQoKICAgICAgICBpZiBub3QgdXBkYXRlZDoK"
    "ICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgZ29vZ2xlX2V2ZW50X2lkID0gKHVwZGF0"
    "ZWQuZ2V0KCJnb29nbGVfZXZlbnRfaWQiKSBvciAiIikuc3RyaXAoKQogICAgICAgIGlmIGdvb2ds"
    "ZV9ldmVudF9pZDoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fZ2NhbC5k"
    "ZWxldGVfZXZlbnRfZm9yX3Rhc2soZ29vZ2xlX2V2ZW50X2lkKQogICAgICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAg"
    "ICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtXQVJOXSBHb29nbGUgZXZlbnQgY2xlYW51cCBmYWls"
    "ZWQgZm9yIHRhc2tfaWQ9e3Rhc2tfaWR9OiB7ZXh9IiwKICAgICAgICAgICAgICAgICAgICAiV0FS"
    "TiIsCiAgICAgICAgICAgICAgICApCiAgICAgICAgcmV0dXJuIHVwZGF0ZWQKCiAgICBkZWYgX2Nv"
    "bXBsZXRlX3NlbGVjdGVkX3Rhc2soc2VsZikgLT4gTm9uZToKICAgICAgICBkb25lID0gMAogICAg"
    "ICAgIGZvciB0YXNrX2lkIGluIHNlbGYuX3NlbGVjdGVkX3Rhc2tfaWRzKCk6CiAgICAgICAgICAg"
    "IGlmIHNlbGYuX3NldF90YXNrX3N0YXR1cyh0YXNrX2lkLCAiY29tcGxldGVkIik6CiAgICAgICAg"
    "ICAgICAgICBkb25lICs9IDEKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdIENP"
    "TVBMRVRFIFNFTEVDVEVEIGFwcGxpZWQgdG8ge2RvbmV9IHRhc2socykuIiwgIklORk8iKQogICAg"
    "ICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9jYW5jZWxf"
    "c2VsZWN0ZWRfdGFzayhzZWxmKSAtPiBOb25lOgogICAgICAgIGRvbmUgPSAwCiAgICAgICAgZm9y"
    "IHRhc2tfaWQgaW4gc2VsZi5fc2VsZWN0ZWRfdGFza19pZHMoKToKICAgICAgICAgICAgaWYgc2Vs"
    "Zi5fc2V0X3Rhc2tfc3RhdHVzKHRhc2tfaWQsICJjYW5jZWxsZWQiKToKICAgICAgICAgICAgICAg"
    "IGRvbmUgKz0gMQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gQ0FOQ0VMIFNF"
    "TEVDVEVEIGFwcGxpZWQgdG8ge2RvbmV9IHRhc2socykuIiwgIklORk8iKQogICAgICAgIHNlbGYu"
    "X3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9wdXJnZV9jb21wbGV0ZWRf"
    "dGFza3Moc2VsZikgLT4gTm9uZToKICAgICAgICByZW1vdmVkID0gc2VsZi5fdGFza3MuY2xlYXJf"
    "Y29tcGxldGVkKCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdIFBVUkdFIENP"
    "TVBMRVRFRCByZW1vdmVkIHtyZW1vdmVkfSB0YXNrKHMpLiIsICJJTkZPIikKICAgICAgICBzZWxm"
    "Ll9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfc2V0X3Rhc2tfZWRpdG9y"
    "X3N0YXR1cyhzZWxmLCB0ZXh0OiBzdHIsIG9rOiBib29sID0gRmFsc2UpIC0+IE5vbmU6CiAgICAg"
    "ICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIG5vdCBOb25lOgogICAg"
    "ICAgICAgICBzZWxmLl90YXNrc190YWIuc2V0X3N0YXR1cyh0ZXh0LCBvaz1vaykKCiAgICBkZWYg"
    "X29wZW5fdGFza19lZGl0b3Jfd29ya3NwYWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgZ2V0"
    "YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVy"
    "bgogICAgICAgIG5vd19sb2NhbCA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAgZW5kX2xvY2FsID0g"
    "bm93X2xvY2FsICsgdGltZWRlbHRhKG1pbnV0ZXM9MzApCiAgICAgICAgc2VsZi5fdGFza3NfdGFi"
    "LnRhc2tfZWRpdG9yX25hbWUuc2V0VGV4dCgiIikKICAgICAgICBzZWxmLl90YXNrc190YWIudGFz"
    "a19lZGl0b3Jfc3RhcnRfZGF0ZS5zZXRUZXh0KG5vd19sb2NhbC5zdHJmdGltZSgiJVktJW0tJWQi"
    "KSkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3Jfc3RhcnRfdGltZS5zZXRUZXh0"
    "KG5vd19sb2NhbC5zdHJmdGltZSgiJUg6JU0iKSkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFz"
    "a19lZGl0b3JfZW5kX2RhdGUuc2V0VGV4dChlbmRfbG9jYWwuc3RyZnRpbWUoIiVZLSVtLSVkIikp"
    "CiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX2VuZF90aW1lLnNldFRleHQoZW5k"
    "X2xvY2FsLnN0cmZ0aW1lKCIlSDolTSIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2Vk"
    "aXRvcl9ub3Rlcy5zZXRQbGFpblRleHQoIiIpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tf"
    "ZWRpdG9yX2xvY2F0aW9uLnNldFRleHQoIiIpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tf"
    "ZWRpdG9yX3JlY3VycmVuY2Uuc2V0VGV4dCgiIikKICAgICAgICBzZWxmLl90YXNrc190YWIudGFz"
    "a19lZGl0b3JfYWxsX2RheS5zZXRDaGVja2VkKEZhbHNlKQogICAgICAgIHNlbGYuX3NldF90YXNr"
    "X2VkaXRvcl9zdGF0dXMoIkNvbmZpZ3VyZSB0YXNrIGRldGFpbHMsIHRoZW4gc2F2ZSB0byBHb29n"
    "bGUgQ2FsZW5kYXIuIiwgb2s9RmFsc2UpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLm9wZW5fZWRp"
    "dG9yKCkKCiAgICBkZWYgX2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtzcGFjZShzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBub3QgTm9u"
    "ZToKICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLmNsb3NlX2VkaXRvcigpCgogICAgZGVmIF9j"
    "YW5jZWxfdGFza19lZGl0b3Jfd29ya3NwYWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "Y2xvc2VfdGFza19lZGl0b3Jfd29ya3NwYWNlKCkKCiAgICBkZWYgX3BhcnNlX2VkaXRvcl9kYXRl"
    "dGltZShzZWxmLCBkYXRlX3RleHQ6IHN0ciwgdGltZV90ZXh0OiBzdHIsIGFsbF9kYXk6IGJvb2ws"
    "IGlzX2VuZDogYm9vbCA9IEZhbHNlKToKICAgICAgICBkYXRlX3RleHQgPSAoZGF0ZV90ZXh0IG9y"
    "ICIiKS5zdHJpcCgpCiAgICAgICAgdGltZV90ZXh0ID0gKHRpbWVfdGV4dCBvciAiIikuc3RyaXAo"
    "KQogICAgICAgIGlmIG5vdCBkYXRlX3RleHQ6CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAg"
    "ICAgaWYgYWxsX2RheToKICAgICAgICAgICAgaG91ciA9IDIzIGlmIGlzX2VuZCBlbHNlIDAKICAg"
    "ICAgICAgICAgbWludXRlID0gNTkgaWYgaXNfZW5kIGVsc2UgMAogICAgICAgICAgICBwYXJzZWQg"
    "PSBkYXRldGltZS5zdHJwdGltZShmIntkYXRlX3RleHR9IHtob3VyOjAyZH06e21pbnV0ZTowMmR9"
    "IiwgIiVZLSVtLSVkICVIOiVNIikKICAgICAgICBlbHNlOgogICAgICAgICAgICBwYXJzZWQgPSBk"
    "YXRldGltZS5zdHJwdGltZShmIntkYXRlX3RleHR9IHt0aW1lX3RleHR9IiwgIiVZLSVtLSVkICVI"
    "OiVNIikKICAgICAgICBub3JtYWxpemVkID0gbm9ybWFsaXplX2RhdGV0aW1lX2Zvcl9jb21wYXJl"
    "KHBhcnNlZCwgY29udGV4dD0idGFza19lZGl0b3JfcGFyc2VfZHQiKQogICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbVEFTS1NdW0VESVRPUl0gcGFyc2VkIGRhdGV0aW1l"
    "IGlzX2VuZD17aXNfZW5kfSwgYWxsX2RheT17YWxsX2RheX06ICIKICAgICAgICAgICAgZiJpbnB1"
    "dD0ne2RhdGVfdGV4dH0ge3RpbWVfdGV4dH0nIC0+IHtub3JtYWxpemVkLmlzb2Zvcm1hdCgpIGlm"
    "IG5vcm1hbGl6ZWQgZWxzZSAnTm9uZSd9IiwKICAgICAgICAgICAgIklORk8iLAogICAgICAgICkK"
    "ICAgICAgICByZXR1cm4gbm9ybWFsaXplZAoKICAgIGRlZiBfc2F2ZV90YXNrX2VkaXRvcl9nb29n"
    "bGVfZmlyc3Qoc2VsZikgLT4gTm9uZToKICAgICAgICB0YWIgPSBnZXRhdHRyKHNlbGYsICJfdGFz"
    "a3NfdGFiIiwgTm9uZSkKICAgICAgICBpZiB0YWIgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgdGl0bGUgPSB0YWIudGFza19lZGl0b3JfbmFtZS50ZXh0KCkuc3RyaXAoKQogICAg"
    "ICAgIGFsbF9kYXkgPSB0YWIudGFza19lZGl0b3JfYWxsX2RheS5pc0NoZWNrZWQoKQogICAgICAg"
    "IHN0YXJ0X2RhdGUgPSB0YWIudGFza19lZGl0b3Jfc3RhcnRfZGF0ZS50ZXh0KCkuc3RyaXAoKQog"
    "ICAgICAgIHN0YXJ0X3RpbWUgPSB0YWIudGFza19lZGl0b3Jfc3RhcnRfdGltZS50ZXh0KCkuc3Ry"
    "aXAoKQogICAgICAgIGVuZF9kYXRlID0gdGFiLnRhc2tfZWRpdG9yX2VuZF9kYXRlLnRleHQoKS5z"
    "dHJpcCgpCiAgICAgICAgZW5kX3RpbWUgPSB0YWIudGFza19lZGl0b3JfZW5kX3RpbWUudGV4dCgp"
    "LnN0cmlwKCkKICAgICAgICBub3RlcyA9IHRhYi50YXNrX2VkaXRvcl9ub3Rlcy50b1BsYWluVGV4"
    "dCgpLnN0cmlwKCkKICAgICAgICBsb2NhdGlvbiA9IHRhYi50YXNrX2VkaXRvcl9sb2NhdGlvbi50"
    "ZXh0KCkuc3RyaXAoKQogICAgICAgIHJlY3VycmVuY2UgPSB0YWIudGFza19lZGl0b3JfcmVjdXJy"
    "ZW5jZS50ZXh0KCkuc3RyaXAoKQoKICAgICAgICBpZiBub3QgdGl0bGU6CiAgICAgICAgICAgIHNl"
    "bGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIlRhc2sgTmFtZSBpcyByZXF1aXJlZC4iLCBvaz1G"
    "YWxzZSkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgbm90IHN0YXJ0X2RhdGUgb3Igbm90"
    "IGVuZF9kYXRlIG9yIChub3QgYWxsX2RheSBhbmQgKG5vdCBzdGFydF90aW1lIG9yIG5vdCBlbmRf"
    "dGltZSkpOgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJTdGFydC9F"
    "bmQgZGF0ZSBhbmQgdGltZSBhcmUgcmVxdWlyZWQuIiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHJl"
    "dHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc3RhcnRfZHQgPSBzZWxmLl9wYXJzZV9lZGl0"
    "b3JfZGF0ZXRpbWUoc3RhcnRfZGF0ZSwgc3RhcnRfdGltZSwgYWxsX2RheSwgaXNfZW5kPUZhbHNl"
    "KQogICAgICAgICAgICBlbmRfZHQgPSBzZWxmLl9wYXJzZV9lZGl0b3JfZGF0ZXRpbWUoZW5kX2Rh"
    "dGUsIGVuZF90aW1lLCBhbGxfZGF5LCBpc19lbmQ9VHJ1ZSkKICAgICAgICAgICAgaWYgbm90IHN0"
    "YXJ0X2R0IG9yIG5vdCBlbmRfZHQ6CiAgICAgICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJk"
    "YXRldGltZSBwYXJzZSBmYWlsZWQiKQogICAgICAgICAgICBpZiBlbmRfZHQgPCBzdGFydF9kdDoK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIkVuZCBkYXRldGlt"
    "ZSBtdXN0IGJlIGFmdGVyIHN0YXJ0IGRhdGV0aW1lLiIsIG9rPUZhbHNlKQogICAgICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgc2VsZi5fc2V0"
    "X3Rhc2tfZWRpdG9yX3N0YXR1cygiSW52YWxpZCBkYXRlL3RpbWUgZm9ybWF0LiBVc2UgWVlZWS1N"
    "TS1ERCBhbmQgSEg6TU0uIiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0"
    "el9uYW1lID0gc2VsZi5fZ2NhbC5fZ2V0X2dvb2dsZV9ldmVudF90aW1lem9uZSgpCiAgICAgICAg"
    "cGF5bG9hZCA9IHsic3VtbWFyeSI6IHRpdGxlfQogICAgICAgIGlmIGFsbF9kYXk6CiAgICAgICAg"
    "ICAgIHBheWxvYWRbInN0YXJ0Il0gPSB7ImRhdGUiOiBzdGFydF9kdC5kYXRlKCkuaXNvZm9ybWF0"
    "KCl9CiAgICAgICAgICAgIHBheWxvYWRbImVuZCJdID0geyJkYXRlIjogKGVuZF9kdC5kYXRlKCkg"
    "KyB0aW1lZGVsdGEoZGF5cz0xKSkuaXNvZm9ybWF0KCl9CiAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgcGF5bG9hZFsic3RhcnQiXSA9IHsiZGF0ZVRpbWUiOiBzdGFydF9kdC5yZXBsYWNlKHR6aW5m"
    "bz1Ob25lKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25lIjogdHpfbmFt"
    "ZX0KICAgICAgICAgICAgcGF5bG9hZFsiZW5kIl0gPSB7ImRhdGVUaW1lIjogZW5kX2R0LnJlcGxh"
    "Y2UodHppbmZvPU5vbmUpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLCAidGltZVpvbmUi"
    "OiB0el9uYW1lfQogICAgICAgIGlmIG5vdGVzOgogICAgICAgICAgICBwYXlsb2FkWyJkZXNjcmlw"
    "dGlvbiJdID0gbm90ZXMKICAgICAgICBpZiBsb2NhdGlvbjoKICAgICAgICAgICAgcGF5bG9hZFsi"
    "bG9jYXRpb24iXSA9IGxvY2F0aW9uCiAgICAgICAgaWYgcmVjdXJyZW5jZToKICAgICAgICAgICAg"
    "cnVsZSA9IHJlY3VycmVuY2UgaWYgcmVjdXJyZW5jZS51cHBlcigpLnN0YXJ0c3dpdGgoIlJSVUxF"
    "OiIpIGVsc2UgZiJSUlVMRTp7cmVjdXJyZW5jZX0iCiAgICAgICAgICAgIHBheWxvYWRbInJlY3Vy"
    "cmVuY2UiXSA9IFtydWxlXQoKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW0VE"
    "SVRPUl0gR29vZ2xlIHNhdmUgc3RhcnQgZm9yIHRpdGxlPSd7dGl0bGV9Jy4iLCAiSU5GTyIpCiAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICBldmVudF9pZCwgXyA9IHNlbGYuX2djYWwuY3JlYXRlX2V2"
    "ZW50X3dpdGhfcGF5bG9hZChwYXlsb2FkLCBjYWxlbmRhcl9pZD0icHJpbWFyeSIpCiAgICAgICAg"
    "ICAgIHRhc2tzID0gc2VsZi5fdGFza3MubG9hZF9hbGwoKQogICAgICAgICAgICB0YXNrID0gewog"
    "ICAgICAgICAgICAgICAgImlkIjogZiJ0YXNrX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19IiwKICAg"
    "ICAgICAgICAgICAgICJjcmVhdGVkX2F0IjogbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAg"
    "ICAgImR1ZV9hdCI6IHN0YXJ0X2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAg"
    "ICAgICAgICAgICAgInByZV90cmlnZ2VyIjogKHN0YXJ0X2R0IC0gdGltZWRlbHRhKG1pbnV0ZXM9"
    "MSkpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgInRleHQi"
    "OiB0aXRsZSwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAicGVuZGluZyIsCiAgICAgICAgICAg"
    "ICAgICAiYWNrbm93bGVkZ2VkX2F0IjogTm9uZSwKICAgICAgICAgICAgICAgICJyZXRyeV9jb3Vu"
    "dCI6IDAsCiAgICAgICAgICAgICAgICAibGFzdF90cmlnZ2VyZWRfYXQiOiBOb25lLAogICAgICAg"
    "ICAgICAgICAgIm5leHRfcmV0cnlfYXQiOiBOb25lLAogICAgICAgICAgICAgICAgInByZV9hbm5v"
    "dW5jZWQiOiBGYWxzZSwKICAgICAgICAgICAgICAgICJzb3VyY2UiOiAibG9jYWwiLAogICAgICAg"
    "ICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6IGV2ZW50X2lkLAogICAgICAgICAgICAgICAgInN5"
    "bmNfc3RhdHVzIjogInN5bmNlZCIsCiAgICAgICAgICAgICAgICAibGFzdF9zeW5jZWRfYXQiOiBs"
    "b2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICAgICAibWV0YWRhdGEiOiB7CiAgICAgICAgICAg"
    "ICAgICAgICAgImlucHV0IjogInRhc2tfZWRpdG9yX2dvb2dsZV9maXJzdCIsCiAgICAgICAgICAg"
    "ICAgICAgICAgIm5vdGVzIjogbm90ZXMsCiAgICAgICAgICAgICAgICAgICAgInN0YXJ0X2F0Ijog"
    "c3RhcnRfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAg"
    "ICAgImVuZF9hdCI6IGVuZF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAg"
    "ICAgICAgICAgICAgICAiYWxsX2RheSI6IGJvb2woYWxsX2RheSksCiAgICAgICAgICAgICAgICAg"
    "ICAgImxvY2F0aW9uIjogbG9jYXRpb24sCiAgICAgICAgICAgICAgICAgICAgInJlY3VycmVuY2Ui"
    "OiByZWN1cnJlbmNlLAogICAgICAgICAgICAgICAgfSwKICAgICAgICAgICAgfQogICAgICAgICAg"
    "ICB0YXNrcy5hcHBlbmQodGFzaykKICAgICAgICAgICAgc2VsZi5fdGFza3Muc2F2ZV9hbGwodGFz"
    "a3MpCiAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIkdvb2dsZSBzeW5j"
    "IHN1Y2NlZWRlZCBhbmQgdGFzayByZWdpc3RyeSB1cGRhdGVkLiIsIG9rPVRydWUpCiAgICAgICAg"
    "ICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCiAgICAgICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtFRElUT1JdIEdvb2dsZSBz"
    "YXZlIHN1Y2Nlc3MgZm9yIHRpdGxlPSd7dGl0bGV9JywgZXZlbnRfaWQ9e2V2ZW50X2lkfS4iLAog"
    "ICAgICAgICAgICAgICAgIk9LIiwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9jbG9z"
    "ZV90YXNrX2VkaXRvcl93b3Jrc3BhY2UoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6"
    "CiAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoZiJHb29nbGUgc2F2ZSBm"
    "YWlsZWQ6IHtleH0iLCBvaz1GYWxzZSkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAog"
    "ICAgICAgICAgICAgICAgZiJbVEFTS1NdW0VESVRPUl1bRVJST1JdIEdvb2dsZSBzYXZlIGZhaWx1"
    "cmUgZm9yIHRpdGxlPSd7dGl0bGV9Jzoge2V4fSIsCiAgICAgICAgICAgICAgICAiRVJST1IiLAog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtzcGFj"
    "ZSgpCgogICAgZGVmIF9pbnNlcnRfY2FsZW5kYXJfZGF0ZShzZWxmLCBxZGF0ZTogUURhdGUpIC0+"
    "IE5vbmU6CiAgICAgICAgZGF0ZV90ZXh0ID0gcWRhdGUudG9TdHJpbmcoInl5eXktTU0tZGQiKQog"
    "ICAgICAgIHJvdXRlZF90YXJnZXQgPSAibm9uZSIKCiAgICAgICAgZm9jdXNfd2lkZ2V0ID0gUUFw"
    "cGxpY2F0aW9uLmZvY3VzV2lkZ2V0KCkKICAgICAgICBkaXJlY3RfdGFyZ2V0cyA9IFsKICAgICAg"
    "ICAgICAgKCJ0YXNrX2VkaXRvcl9zdGFydF9kYXRlIiwgZ2V0YXR0cihnZXRhdHRyKHNlbGYsICJf"
    "dGFza3NfdGFiIiwgTm9uZSksICJ0YXNrX2VkaXRvcl9zdGFydF9kYXRlIiwgTm9uZSkpLAogICAg"
    "ICAgICAgICAoInRhc2tfZWRpdG9yX2VuZF9kYXRlIiwgZ2V0YXR0cihnZXRhdHRyKHNlbGYsICJf"
    "dGFza3NfdGFiIiwgTm9uZSksICJ0YXNrX2VkaXRvcl9lbmRfZGF0ZSIsIE5vbmUpKSwKICAgICAg"
    "ICBdCiAgICAgICAgZm9yIG5hbWUsIHdpZGdldCBpbiBkaXJlY3RfdGFyZ2V0czoKICAgICAgICAg"
    "ICAgaWYgd2lkZ2V0IGlzIG5vdCBOb25lIGFuZCBmb2N1c193aWRnZXQgaXMgd2lkZ2V0OgogICAg"
    "ICAgICAgICAgICAgd2lkZ2V0LnNldFRleHQoZGF0ZV90ZXh0KQogICAgICAgICAgICAgICAgcm91"
    "dGVkX3RhcmdldCA9IG5hbWUKICAgICAgICAgICAgICAgIGJyZWFrCgogICAgICAgIGlmIHJvdXRl"
    "ZF90YXJnZXQgPT0gIm5vbmUiOgogICAgICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfaW5wdXRf"
    "ZmllbGQiKSBhbmQgc2VsZi5faW5wdXRfZmllbGQgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAg"
    "ICBpZiBmb2N1c193aWRnZXQgaXMgc2VsZi5faW5wdXRfZmllbGQ6CiAgICAgICAgICAgICAgICAg"
    "ICAgc2VsZi5faW5wdXRfZmllbGQuaW5zZXJ0KGRhdGVfdGV4dCkKICAgICAgICAgICAgICAgICAg"
    "ICByb3V0ZWRfdGFyZ2V0ID0gImlucHV0X2ZpZWxkX2luc2VydCIKICAgICAgICAgICAgICAgIGVs"
    "c2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0VGV4dChkYXRlX3Rl"
    "eHQpCiAgICAgICAgICAgICAgICAgICAgcm91dGVkX3RhcmdldCA9ICJpbnB1dF9maWVsZF9zZXQi"
    "CgogICAgICAgIGlmIGhhc2F0dHIoc2VsZiwgIl90YXNrc190YWIiKSBhbmQgc2VsZi5fdGFza3Nf"
    "dGFiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl90YXNrc190YWIuc3RhdHVzX2xhYmVs"
    "LnNldFRleHQoZiJDYWxlbmRhciBkYXRlIHNlbGVjdGVkOiB7ZGF0ZV90ZXh0fSIpCgogICAgICAg"
    "IGlmIGhhc2F0dHIoc2VsZiwgIl9kaWFnX3RhYiIpIGFuZCBzZWxmLl9kaWFnX3RhYiBpcyBub3Qg"
    "Tm9uZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJb"
    "Q0FMRU5EQVJdIG1pbmkgY2FsZW5kYXIgY2xpY2sgcm91dGVkOiBkYXRlPXtkYXRlX3RleHR9LCB0"
    "YXJnZXQ9e3JvdXRlZF90YXJnZXR9LiIsCiAgICAgICAgICAgICAgICAiSU5GTyIKICAgICAgICAg"
    "ICAgKQoKICAgIGRlZiBfcG9sbF9nb29nbGVfY2FsZW5kYXJfaW5ib3VuZF9zeW5jKHNlbGYsIGZv"
    "cmNlX29uY2U6IGJvb2wgPSBGYWxzZSk6CiAgICAgICAgIiIiCiAgICAgICAgU3luYyBHb29nbGUg"
    "Q2FsZW5kYXIgZXZlbnRzIOKGkiBsb2NhbCB0YXNrcyB1c2luZyBHb29nbGUncyBzeW5jVG9rZW4g"
    "QVBJLgoKICAgICAgICBTdGFnZSAxIChmaXJzdCBydW4gLyBmb3JjZWQpOiBGdWxsIGZldGNoLCBz"
    "dG9yZXMgbmV4dFN5bmNUb2tlbi4KICAgICAgICBTdGFnZSAyIChldmVyeSBwb2xsKTogICAgICAg"
    "ICBJbmNyZW1lbnRhbCBmZXRjaCB1c2luZyBzdG9yZWQgc3luY1Rva2VuIOKAlAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybnMgT05MWSB3aGF0IGNoYW5nZWQgKGFk"
    "ZHMvZWRpdHMvY2FuY2VscykuCiAgICAgICAgSWYgc2VydmVyIHJldHVybnMgNDEwIEdvbmUgKHRv"
    "a2VuIGV4cGlyZWQpLCBmYWxscyBiYWNrIHRvIGZ1bGwgc3luYy4KICAgICAgICAiIiIKICAgICAg"
    "ICBpZiBub3QgZm9yY2Vfb25jZSBhbmQgbm90IGJvb2woQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSku"
    "Z2V0KCJnb29nbGVfc3luY19lbmFibGVkIiwgVHJ1ZSkpOgogICAgICAgICAgICByZXR1cm4gMAoK"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgIG5vd19pc28gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAg"
    "ICAgICAgdGFza3MgPSBzZWxmLl90YXNrcy5sb2FkX2FsbCgpCiAgICAgICAgICAgIHRhc2tzX2J5"
    "X2V2ZW50X2lkID0gewogICAgICAgICAgICAgICAgKHQuZ2V0KCJnb29nbGVfZXZlbnRfaWQiKSBv"
    "ciAiIikuc3RyaXAoKTogdAogICAgICAgICAgICAgICAgZm9yIHQgaW4gdGFza3MKICAgICAgICAg"
    "ICAgICAgIGlmICh0LmdldCgiZ29vZ2xlX2V2ZW50X2lkIikgb3IgIiIpLnN0cmlwKCkKICAgICAg"
    "ICAgICAgfQoKICAgICAgICAgICAgIyDilIDilIAgRmV0Y2ggZnJvbSBHb29nbGUg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICAgICAgICAgIHN0b3JlZF90b2tlbiA9IHNlbGYuX3N0YXRlLmdldCgiZ29vZ2xlX2Nh"
    "bGVuZGFyX3N5bmNfdG9rZW4iKQoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgaWYg"
    "c3RvcmVkX3Rva2VuIGFuZCBub3QgZm9yY2Vfb25jZToKICAgICAgICAgICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgICAgICJbR09PR0xFXVtTWU5DXSBJ"
    "bmNyZW1lbnRhbCBzeW5jIChzeW5jVG9rZW4pLiIsICJJTkZPIgogICAgICAgICAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgICAgICAgICByZW1vdGVfZXZlbnRzLCBuZXh0X3Rva2VuID0gc2VsZi5f"
    "Z2NhbC5saXN0X3ByaW1hcnlfZXZlbnRzKAogICAgICAgICAgICAgICAgICAgICAgICBzeW5jX3Rv"
    "a2VuPXN0b3JlZF90b2tlbgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGVs"
    "c2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAg"
    "ICAgICAgICAgICAiW0dPT0dMRV1bU1lOQ10gRnVsbCBzeW5jIChubyBzdG9yZWQgdG9rZW4pLiIs"
    "ICJJTkZPIgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICBub3dfdXRj"
    "ID0gZGF0ZXRpbWUudXRjbm93KCkucmVwbGFjZShtaWNyb3NlY29uZD0wKQogICAgICAgICAgICAg"
    "ICAgICAgIHRpbWVfbWluID0gKG5vd191dGMgLSB0aW1lZGVsdGEoZGF5cz0zNjUpKS5pc29mb3Jt"
    "YXQoKSArICJaIgogICAgICAgICAgICAgICAgICAgIHJlbW90ZV9ldmVudHMsIG5leHRfdG9rZW4g"
    "PSBzZWxmLl9nY2FsLmxpc3RfcHJpbWFyeV9ldmVudHMoCiAgICAgICAgICAgICAgICAgICAgICAg"
    "IHRpbWVfbWluPXRpbWVfbWluCiAgICAgICAgICAgICAgICAgICAgKQoKICAgICAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbiBhcyBhcGlfZXg6CiAgICAgICAgICAgICAgICBpZiAiNDEwIiBpbiBzdHIo"
    "YXBpX2V4KSBvciAiR29uZSIgaW4gc3RyKGFwaV9leCk6CiAgICAgICAgICAgICAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgICAgICAiW0dPT0dMRV1bU1lOQ10g"
    "c3luY1Rva2VuIGV4cGlyZWQgKDQxMCkg4oCUIGZ1bGwgcmVzeW5jLiIsICJXQVJOIgogICAgICAg"
    "ICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICBzZWxmLl9zdGF0ZS5wb3AoImdvb2ds"
    "ZV9jYWxlbmRhcl9zeW5jX3Rva2VuIiwgTm9uZSkKICAgICAgICAgICAgICAgICAgICBub3dfdXRj"
    "ID0gZGF0ZXRpbWUudXRjbm93KCkucmVwbGFjZShtaWNyb3NlY29uZD0wKQogICAgICAgICAgICAg"
    "ICAgICAgIHRpbWVfbWluID0gKG5vd191dGMgLSB0aW1lZGVsdGEoZGF5cz0zNjUpKS5pc29mb3Jt"
    "YXQoKSArICJaIgogICAgICAgICAgICAgICAgICAgIHJlbW90ZV9ldmVudHMsIG5leHRfdG9rZW4g"
    "PSBzZWxmLl9nY2FsLmxpc3RfcHJpbWFyeV9ldmVudHMoCiAgICAgICAgICAgICAgICAgICAgICAg"
    "IHRpbWVfbWluPXRpbWVfbWluCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAg"
    "ZWxzZToKICAgICAgICAgICAgICAgICAgICByYWlzZQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKAogICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTWU5DXSBSZWNlaXZlZCB7bGVuKHJl"
    "bW90ZV9ldmVudHMpfSBldmVudChzKS4iLCAiSU5GTyIKICAgICAgICAgICAgKQoKICAgICAgICAg"
    "ICAgIyBTYXZlIG5ldyB0b2tlbiBmb3IgbmV4dCBpbmNyZW1lbnRhbCBjYWxsCiAgICAgICAgICAg"
    "IGlmIG5leHRfdG9rZW46CiAgICAgICAgICAgICAgICBzZWxmLl9zdGF0ZVsiZ29vZ2xlX2NhbGVu"
    "ZGFyX3N5bmNfdG9rZW4iXSA9IG5leHRfdG9rZW4KICAgICAgICAgICAgICAgIHNlbGYuX21lbW9y"
    "eS5zYXZlX3N0YXRlKHNlbGYuX3N0YXRlKQoKICAgICAgICAgICAgIyDilIDilIAgUHJvY2VzcyBl"
    "dmVudHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgICAgIGltcG9ydGVkX2NvdW50ID0g"
    "dXBkYXRlZF9jb3VudCA9IHJlbW92ZWRfY291bnQgPSAwCiAgICAgICAgICAgIGNoYW5nZWQgPSBG"
    "YWxzZQoKICAgICAgICAgICAgZm9yIGV2ZW50IGluIHJlbW90ZV9ldmVudHM6CiAgICAgICAgICAg"
    "ICAgICBldmVudF9pZCA9IChldmVudC5nZXQoImlkIikgb3IgIiIpLnN0cmlwKCkKICAgICAgICAg"
    "ICAgICAgIGlmIG5vdCBldmVudF9pZDoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQoKICAg"
    "ICAgICAgICAgICAgICMgRGVsZXRlZCAvIGNhbmNlbGxlZCBvbiBHb29nbGUncyBzaWRlCiAgICAg"
    "ICAgICAgICAgICBpZiBldmVudC5nZXQoInN0YXR1cyIpID09ICJjYW5jZWxsZWQiOgogICAgICAg"
    "ICAgICAgICAgICAgIGV4aXN0aW5nID0gdGFza3NfYnlfZXZlbnRfaWQuZ2V0KGV2ZW50X2lkKQog"
    "ICAgICAgICAgICAgICAgICAgIGlmIGV4aXN0aW5nIGFuZCBleGlzdGluZy5nZXQoInN0YXR1cyIp"
    "IG5vdCBpbiAoImNhbmNlbGxlZCIsICJjb21wbGV0ZWQiKToKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZXhpc3RpbmdbInN0YXR1cyJdICAgICAgICAgPSAiY2FuY2VsbGVkIgogICAgICAgICAgICAg"
    "ICAgICAgICAgICBleGlzdGluZ1siY2FuY2VsbGVkX2F0Il0gICA9IG5vd19pc28KICAgICAgICAg"
    "ICAgICAgICAgICAgICAgZXhpc3RpbmdbInN5bmNfc3RhdHVzIl0gICAgPSAiZGVsZXRlZF9yZW1v"
    "dGUiCiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJsYXN0X3N5bmNlZF9hdCJdID0g"
    "bm93X2lzbwogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZy5zZXRkZWZhdWx0KCJtZXRh"
    "ZGF0YSIsIHt9KVsiZ29vZ2xlX2RlbGV0ZWRfcmVtb3RlIl0gPSBub3dfaXNvCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIHJlbW92ZWRfY291bnQgKz0gMQogICAgICAgICAgICAgICAgICAgICAgICBj"
    "aGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NZTkNdIFJlbW92ZWQ6IHtl"
    "eGlzdGluZy5nZXQoJ3RleHQnLCc/Jyl9IiwgIklORk8iCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgICAgIHN1bW1hcnkg"
    "PSAoZXZlbnQuZ2V0KCJzdW1tYXJ5Iikgb3IgIkdvb2dsZSBDYWxlbmRhciBFdmVudCIpLnN0cmlw"
    "KCkgb3IgIkdvb2dsZSBDYWxlbmRhciBFdmVudCIKICAgICAgICAgICAgICAgIGR1ZV9hdCAgPSBz"
    "ZWxmLl9nb29nbGVfZXZlbnRfZHVlX2RhdGV0aW1lKGV2ZW50KQogICAgICAgICAgICAgICAgZXhp"
    "c3RpbmcgPSB0YXNrc19ieV9ldmVudF9pZC5nZXQoZXZlbnRfaWQpCgogICAgICAgICAgICAgICAg"
    "aWYgZXhpc3Rpbmc6CiAgICAgICAgICAgICAgICAgICAgIyBVcGRhdGUgaWYgYW55dGhpbmcgY2hh"
    "bmdlZAogICAgICAgICAgICAgICAgICAgIHRhc2tfY2hhbmdlZCA9IEZhbHNlCiAgICAgICAgICAg"
    "ICAgICAgICAgaWYgKGV4aXN0aW5nLmdldCgidGV4dCIpIG9yICIiKS5zdHJpcCgpICE9IHN1bW1h"
    "cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJ0ZXh0Il0gPSBzdW1tYXJ5CiAg"
    "ICAgICAgICAgICAgICAgICAgICAgIHRhc2tfY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAg"
    "ICAgICBpZiBkdWVfYXQ6CiAgICAgICAgICAgICAgICAgICAgICAgIGR1ZV9pc28gPSBkdWVfYXQu"
    "aXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAgICAgICAgICAgaWYg"
    "ZXhpc3RpbmcuZ2V0KCJkdWVfYXQiKSAhPSBkdWVfaXNvOgogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgZXhpc3RpbmdbImR1ZV9hdCJdICAgICAgID0gZHVlX2lzbwogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgZXhpc3RpbmdbInByZV90cmlnZ2VyIl0gID0gKGR1ZV9hdCAtIHRpbWVkZWx0"
    "YShtaW51dGVzPTEpKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgIGlm"
    "IGV4aXN0aW5nLmdldCgic3luY19zdGF0dXMiKSAhPSAic3luY2VkIjoKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgZXhpc3RpbmdbInN5bmNfc3RhdHVzIl0gPSAic3luY2VkIgogICAgICAgICAgICAg"
    "ICAgICAgICAgICB0YXNrX2NoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgaWYgdGFz"
    "a19jaGFuZ2VkOgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sibGFzdF9zeW5jZWRf"
    "YXQiXSA9IG5vd19pc28KICAgICAgICAgICAgICAgICAgICAgICAgdXBkYXRlZF9jb3VudCArPSAx"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYi"
    "W0dPT0dMRV1bU1lOQ10gVXBkYXRlZDoge3N1bW1hcnl9IiwgIklORk8iCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgIyBO"
    "ZXcgZXZlbnQKICAgICAgICAgICAgICAgICAgICBpZiBub3QgZHVlX2F0OgogICAgICAgICAgICAg"
    "ICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAgICAgICAgIG5ld190YXNrID0gewogICAg"
    "ICAgICAgICAgICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICAgICBmInRhc2tfe3V1aWQudXVp"
    "ZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAgICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICAg"
    "ICAgICBub3dfaXNvLAogICAgICAgICAgICAgICAgICAgICAgICAiZHVlX2F0IjogICAgICAgICAg"
    "ICBkdWVfYXQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICJwcmVfdHJpZ2dlciI6ICAgICAgIChkdWVfYXQgLSB0aW1lZGVsdGEobWludXRlcz0x"
    "KSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICJ0ZXh0IjogICAgICAgICAgICAgIHN1bW1hcnksCiAgICAgICAgICAgICAgICAgICAgICAgICJz"
    "dGF0dXMiOiAgICAgICAgICAgICJwZW5kaW5nIiwKICAgICAgICAgICAgICAgICAgICAgICAgImFj"
    "a25vd2xlZGdlZF9hdCI6ICAgTm9uZSwKICAgICAgICAgICAgICAgICAgICAgICAgInJldHJ5X2Nv"
    "dW50IjogICAgICAgMCwKICAgICAgICAgICAgICAgICAgICAgICAgImxhc3RfdHJpZ2dlcmVkX2F0"
    "IjogTm9uZSwKICAgICAgICAgICAgICAgICAgICAgICAgIm5leHRfcmV0cnlfYXQiOiAgICAgTm9u"
    "ZSwKICAgICAgICAgICAgICAgICAgICAgICAgInByZV9hbm5vdW5jZWQiOiAgICAgRmFsc2UsCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICJzb3VyY2UiOiAgICAgICAgICAgICJnb29nbGUiLAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAiZ29vZ2xlX2V2ZW50X2lkIjogICBldmVudF9pZCwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgInN5bmNfc3RhdHVzIjogICAgICAgInN5bmNlZCIsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJsYXN0X3N5bmNlZF9hdCI6ICAgIG5vd19pc28sCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICJtZXRhZGF0YSI6IHsKICAgICAgICAgICAgICAgICAgICAgICAgICAgICJn"
    "b29nbGVfaW1wb3J0ZWRfYXQiOiBub3dfaXNvLAogICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "Imdvb2dsZV91cGRhdGVkIjogICAgIGV2ZW50LmdldCgidXBkYXRlZCIpLAogICAgICAgICAgICAg"
    "ICAgICAgICAgICB9LAogICAgICAgICAgICAgICAgICAgIH0KICAgICAgICAgICAgICAgICAgICB0"
    "YXNrcy5hcHBlbmQobmV3X3Rhc2spCiAgICAgICAgICAgICAgICAgICAgdGFza3NfYnlfZXZlbnRf"
    "aWRbZXZlbnRfaWRdID0gbmV3X3Rhc2sKICAgICAgICAgICAgICAgICAgICBpbXBvcnRlZF9jb3Vu"
    "dCArPSAxCiAgICAgICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtTWU5DXSBJbXBvcnRlZDoge3N1bW1h"
    "cnl9IiwgIklORk8iKQoKICAgICAgICAgICAgaWYgY2hhbmdlZDoKICAgICAgICAgICAgICAgIHNl"
    "bGYuX3Rhc2tzLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tf"
    "cmVnaXN0cnlfcGFuZWwoKQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAg"
    "ICAgICAgICAgZiJbR09PR0xFXVtTWU5DXSBEb25lIOKAlCBpbXBvcnRlZD17aW1wb3J0ZWRfY291"
    "bnR9ICIKICAgICAgICAgICAgICAgIGYidXBkYXRlZD17dXBkYXRlZF9jb3VudH0gcmVtb3ZlZD17"
    "cmVtb3ZlZF9jb3VudH0iLCAiSU5GTyIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4g"
    "aW1wb3J0ZWRfY291bnQKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bU1lOQ11bRVJST1JdIHtleH0iLCAiRVJS"
    "T1IiKQogICAgICAgICAgICByZXR1cm4gMAoKCiAgICBkZWYgX21lYXN1cmVfdnJhbV9iYXNlbGlu"
    "ZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAg"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgICAgIG1lbSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVt"
    "b3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgc2VsZi5fZGVja192cmFtX2Jhc2Ug"
    "PSBtZW0udXNlZCAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygK"
    "ICAgICAgICAgICAgICAgICAgICBmIltWUkFNXSBCYXNlbGluZSBtZWFzdXJlZDoge3NlbGYuX2Rl"
    "Y2tfdnJhbV9iYXNlOi4yZn1HQiAiCiAgICAgICAgICAgICAgICAgICAgZiIoe0RFQ0tfTkFNRX0n"
    "cyBmb290cHJpbnQpIiwgIklORk8iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgIyDilIDilIAgTUVTU0FHRSBI"
    "QU5ETElORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgIGRlZiBfc2VuZF9tZXNzYWdlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNl"
    "bGYuX21vZGVsX2xvYWRlZCBvciBzZWxmLl90b3Jwb3Jfc3RhdGUgPT0gIlNVU1BFTkQiOgogICAg"
    "ICAgICAgICByZXR1cm4KICAgICAgICB0ZXh0ID0gc2VsZi5faW5wdXRfZmllbGQudGV4dCgpLnN0"
    "cmlwKCkKICAgICAgICBpZiBub3QgdGV4dDoKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgICMg"
    "RmxpcCBiYWNrIHRvIHBlcnNvbmEgY2hhdCB0YWIgZnJvbSBTZWxmIHRhYiBpZiBuZWVkZWQKICAg"
    "ICAgICBpZiBzZWxmLl9tYWluX3RhYnMuY3VycmVudEluZGV4KCkgIT0gMDoKICAgICAgICAgICAg"
    "c2VsZi5fbWFpbl90YWJzLnNldEN1cnJlbnRJbmRleCgwKQoKICAgICAgICBzZWxmLl9pbnB1dF9m"
    "aWVsZC5jbGVhcigpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIllPVSIsIHRleHQpCgogICAg"
    "ICAgICMgU2Vzc2lvbiBsb2dnaW5nCiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuYWRkX21lc3NhZ2Uo"
    "InVzZXIiLCB0ZXh0KQogICAgICAgIHNlbGYuX21lbW9yeS5hcHBlbmRfbWVzc2FnZShzZWxmLl9z"
    "ZXNzaW9uX2lkLCAidXNlciIsIHRleHQpCgogICAgICAgICMgSW50ZXJydXB0IGZhY2UgdGltZXIg"
    "4oCUIHN3aXRjaCB0byBhbGVydCBpbW1lZGlhdGVseQogICAgICAgIGlmIHNlbGYuX2ZhY2VfdGlt"
    "ZXJfbWdyOgogICAgICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nci5pbnRlcnJ1cHQoImFsZXJ0"
    "IikKCiAgICAgICAgIyBCdWlsZCBwcm9tcHQgd2l0aCB2YW1waXJlIGNvbnRleHQgKyBtZW1vcnkg"
    "Y29udGV4dAogICAgICAgIHZhbXBpcmVfY3R4ICA9IGJ1aWxkX3ZhbXBpcmVfY29udGV4dCgpCiAg"
    "ICAgICAgbWVtb3J5X2N0eCAgID0gc2VsZi5fbWVtb3J5LmJ1aWxkX2NvbnRleHRfYmxvY2sodGV4"
    "dCkKICAgICAgICBqb3VybmFsX2N0eCAgPSAiIgoKICAgICAgICBpZiBzZWxmLl9zZXNzaW9ucy5s"
    "b2FkZWRfam91cm5hbF9kYXRlOgogICAgICAgICAgICBqb3VybmFsX2N0eCA9IHNlbGYuX3Nlc3Np"
    "b25zLmxvYWRfc2Vzc2lvbl9hc19jb250ZXh0KAogICAgICAgICAgICAgICAgc2VsZi5fc2Vzc2lv"
    "bnMubG9hZGVkX2pvdXJuYWxfZGF0ZQogICAgICAgICAgICApCgogICAgICAgICMgQnVpbGQgc3lz"
    "dGVtIHByb21wdAogICAgICAgIHN5c3RlbSA9IFNZU1RFTV9QUk9NUFRfQkFTRQogICAgICAgIGlm"
    "IG1lbW9yeV9jdHg6CiAgICAgICAgICAgIHN5c3RlbSArPSBmIlxuXG57bWVtb3J5X2N0eH0iCiAg"
    "ICAgICAgaWYgam91cm5hbF9jdHg6CiAgICAgICAgICAgIHN5c3RlbSArPSBmIlxuXG57am91cm5h"
    "bF9jdHh9IgogICAgICAgIHN5c3RlbSArPSB2YW1waXJlX2N0eAoKICAgICAgICAjIExlc3NvbnMg"
    "Y29udGV4dCBmb3IgY29kZS1hZGphY2VudCBpbnB1dAogICAgICAgIGlmIGFueShrdyBpbiB0ZXh0"
    "Lmxvd2VyKCkgZm9yIGt3IGluICgibHNsIiwicHl0aG9uIiwic2NyaXB0IiwiY29kZSIsImZ1bmN0"
    "aW9uIikpOgogICAgICAgICAgICBsYW5nID0gIkxTTCIgaWYgImxzbCIgaW4gdGV4dC5sb3dlcigp"
    "IGVsc2UgIlB5dGhvbiIKICAgICAgICAgICAgbGVzc29uc19jdHggPSBzZWxmLl9sZXNzb25zLmJ1"
    "aWxkX2NvbnRleHRfZm9yX2xhbmd1YWdlKGxhbmcpCiAgICAgICAgICAgIGlmIGxlc3NvbnNfY3R4"
    "OgogICAgICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5cbntsZXNzb25zX2N0eH0iCgogICAgICAg"
    "ICMgQWRkIHBlbmRpbmcgdHJhbnNtaXNzaW9ucyBjb250ZXh0IGlmIGFueQogICAgICAgIGlmIHNl"
    "bGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyA+IDA6CiAgICAgICAgICAgIGR1ciA9IHNlbGYuX3N1"
    "c3BlbmRlZF9kdXJhdGlvbiBvciAic29tZSB0aW1lIgogICAgICAgICAgICBzeXN0ZW0gKz0gKAog"
    "ICAgICAgICAgICAgICAgZiJcblxuW1JFVFVSTiBGUk9NIFRPUlBPUl1cbiIKICAgICAgICAgICAg"
    "ICAgIGYiWW91IHdlcmUgaW4gdG9ycG9yIGZvciB7ZHVyfS4gIgogICAgICAgICAgICAgICAgZiJ7"
    "c2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zfSB0aG91Z2h0cyB3ZW50IHVuc3Bva2VuICIKICAg"
    "ICAgICAgICAgICAgIGYiZHVyaW5nIHRoYXQgdGltZS4gQWNrbm93bGVkZ2UgdGhpcyBicmllZmx5"
    "IGluIGNoYXJhY3RlciAiCiAgICAgICAgICAgICAgICBmImlmIGl0IGZlZWxzIG5hdHVyYWwuIgog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyA9IDAK"
    "ICAgICAgICAgICAgc2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uICAgID0gIiIKCiAgICAgICAgaGlz"
    "dG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKCiAgICAgICAgIyBEaXNhYmxlIGlu"
    "cHV0CiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxm"
    "Ll9pbnB1dF9maWVsZC5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMo"
    "IkdFTkVSQVRJTkciKQoKICAgICAgICAjIFN0b3AgaWRsZSB0aW1lciBkdXJpbmcgZ2VuZXJhdGlv"
    "bgogICAgICAgIHNhdmVfY29uZmlnKENGRykKICAgICAgICBpZiBzZWxmLl9zY2hlZHVsZXIgYW5k"
    "IHNlbGYuX3NjaGVkdWxlci5ydW5uaW5nOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9zY2hlZHVsZXIucGF1c2Vfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgTGF1"
    "bmNoIHN0cmVhbWluZyB3b3JrZXIKICAgICAgICBzZWxmLl93b3JrZXIgPSBTdHJlYW1pbmdXb3Jr"
    "ZXIoCiAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IsIHN5c3RlbSwgaGlzdG9yeSwgbWF4X3Rva2Vu"
    "cz01MTIKICAgICAgICApCiAgICAgICAgc2VsZi5fd29ya2VyLnRva2VuX3JlYWR5LmNvbm5lY3Qo"
    "c2VsZi5fb25fdG9rZW4pCiAgICAgICAgc2VsZi5fd29ya2VyLnJlc3BvbnNlX2RvbmUuY29ubmVj"
    "dChzZWxmLl9vbl9yZXNwb25zZV9kb25lKQogICAgICAgIHNlbGYuX3dvcmtlci5lcnJvcl9vY2N1"
    "cnJlZC5jb25uZWN0KHNlbGYuX29uX2Vycm9yKQogICAgICAgIHNlbGYuX3dvcmtlci5zdGF0dXNf"
    "Y2hhbmdlZC5jb25uZWN0KHNlbGYuX3NldF9zdGF0dXMpCiAgICAgICAgc2VsZi5fZmlyc3RfdG9r"
    "ZW4gPSBUcnVlICAjIGZsYWcgdG8gd3JpdGUgc3BlYWtlciBsYWJlbCBiZWZvcmUgZmlyc3QgdG9r"
    "ZW4KICAgICAgICBzZWxmLl93b3JrZXIuc3RhcnQoKQoKICAgIGRlZiBfYmVnaW5fcGVyc29uYV9y"
    "ZXNwb25zZShzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIFdyaXRlIHRoZSBwZXJz"
    "b25hIHNwZWFrZXIgbGFiZWwgYW5kIHRpbWVzdGFtcCBiZWZvcmUgc3RyZWFtaW5nIGJlZ2lucy4K"
    "ICAgICAgICBDYWxsZWQgb24gZmlyc3QgdG9rZW4gb25seS4gU3Vic2VxdWVudCB0b2tlbnMgYXBw"
    "ZW5kIGRpcmVjdGx5LgogICAgICAgICIiIgogICAgICAgIHRpbWVzdGFtcCA9IGRhdGV0aW1lLm5v"
    "dygpLnN0cmZ0aW1lKCIlSDolTTolUyIpCiAgICAgICAgIyBXcml0ZSB0aGUgc3BlYWtlciBsYWJl"
    "bCBhcyBIVE1MLCB0aGVuIGFkZCBhIG5ld2xpbmUgc28gdG9rZW5zCiAgICAgICAgIyBmbG93IGJl"
    "bG93IGl0IHJhdGhlciB0aGFuIGlubGluZQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5hcHBl"
    "bmQoCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1z"
    "aXplOjEwcHg7Ij4nCiAgICAgICAgICAgIGYnW3t0aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAg"
    "ICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19DUklNU09OfTsgZm9udC13ZWlnaHQ6Ym9sZDsi"
    "PicKICAgICAgICAgICAgZid7REVDS19OQU1FLnVwcGVyKCl9IOKdqTwvc3Bhbj4gJwogICAgICAg"
    "ICkKICAgICAgICAjIE1vdmUgY3Vyc29yIHRvIGVuZCBzbyBpbnNlcnRQbGFpblRleHQgYXBwZW5k"
    "cyBjb3JyZWN0bHkKICAgICAgICBjdXJzb3IgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudGV4dEN1cnNv"
    "cigpCiAgICAgICAgY3Vyc29yLm1vdmVQb3NpdGlvbihRVGV4dEN1cnNvci5Nb3ZlT3BlcmF0aW9u"
    "LkVuZCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNvcihjdXJzb3IpCgog"
    "ICAgZGVmIF9vbl90b2tlbihzZWxmLCB0b2tlbjogc3RyKSAtPiBOb25lOgogICAgICAgICIiIkFw"
    "cGVuZCBzdHJlYW1pbmcgdG9rZW4gdG8gY2hhdCBkaXNwbGF5LiIiIgogICAgICAgIGlmIHNlbGYu"
    "X2ZpcnN0X3Rva2VuOgogICAgICAgICAgICBzZWxmLl9iZWdpbl9wZXJzb25hX3Jlc3BvbnNlKCkK"
    "ICAgICAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBGYWxzZQogICAgICAgIGN1cnNvciA9IHNl"
    "bGYuX2NoYXRfZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAgICBjdXJzb3IubW92ZVBvc2l0aW9u"
    "KFFUZXh0Q3Vyc29yLk1vdmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxh"
    "eS5zZXRUZXh0Q3Vyc29yKGN1cnNvcikKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuaW5zZXJ0"
    "UGxhaW5UZXh0KHRva2VuKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9s"
    "bEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkudmVydGljYWxT"
    "Y3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAgZGVmIF9vbl9yZXNwb25zZV9kb25l"
    "KHNlbGYsIHJlc3BvbnNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIyBFbnN1cmUgcmVzcG9uc2Ug"
    "aXMgb24gaXRzIG93biBsaW5lCiAgICAgICAgY3Vyc29yID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRl"
    "eHRDdXJzb3IoKQogICAgICAgIGN1cnNvci5tb3ZlUG9zaXRpb24oUVRleHRDdXJzb3IuTW92ZU9w"
    "ZXJhdGlvbi5FbmQpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFRleHRDdXJzb3IoY3Vy"
    "c29yKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5pbnNlcnRQbGFpblRleHQoIlxuXG4iKQoK"
    "ICAgICAgICAjIExvZyB0byBtZW1vcnkgYW5kIHNlc3Npb24KICAgICAgICBzZWxmLl90b2tlbl9j"
    "b3VudCArPSBsZW4ocmVzcG9uc2Uuc3BsaXQoKSkKICAgICAgICBzZWxmLl9zZXNzaW9ucy5hZGRf"
    "bWVzc2FnZSgiYXNzaXN0YW50IiwgcmVzcG9uc2UpCiAgICAgICAgc2VsZi5fbWVtb3J5LmFwcGVu"
    "ZF9tZXNzYWdlKHNlbGYuX3Nlc3Npb25faWQsICJhc3Npc3RhbnQiLCByZXNwb25zZSkKICAgICAg"
    "ICBzZWxmLl9tZW1vcnkuYXBwZW5kX21lbW9yeShzZWxmLl9zZXNzaW9uX2lkLCAiIiwgcmVzcG9u"
    "c2UpCgogICAgICAgICMgVXBkYXRlIGJsb29kIHNwaGVyZQogICAgICAgIGlmIHNlbGYuX2xlZnRf"
    "b3JiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9sZWZ0X29yYi5zZXRGaWxsKAogICAg"
    "ICAgICAgICAgICAgbWluKDEuMCwgc2VsZi5fdG9rZW5fY291bnQgLyA0MDk2LjApCiAgICAgICAg"
    "ICAgICkKCiAgICAgICAgIyBSZS1lbmFibGUgaW5wdXQKICAgICAgICBzZWxmLl9zZW5kX2J0bi5z"
    "ZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVl"
    "KQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEZvY3VzKCkKCiAgICAgICAgIyBSZXN1bWUg"
    "aWRsZSB0aW1lcgogICAgICAgIHNhdmVfY29uZmlnKENGRykKICAgICAgICBpZiBzZWxmLl9zY2hl"
    "ZHVsZXIgYW5kIHNlbGYuX3NjaGVkdWxlci5ydW5uaW5nOgogICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIucmVzdW1lX2pvYigiaWRsZV90cmFuc21pc3Npb24i"
    "KQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAg"
    "ICAgICAjIFNjaGVkdWxlIHNlbnRpbWVudCBhbmFseXNpcyAoNSBzZWNvbmQgZGVsYXkpCiAgICAg"
    "ICAgUVRpbWVyLnNpbmdsZVNob3QoNTAwMCwgbGFtYmRhOiBzZWxmLl9ydW5fc2VudGltZW50KHJl"
    "c3BvbnNlKSkKCiAgICBkZWYgX3J1bl9zZW50aW1lbnQoc2VsZiwgcmVzcG9uc2U6IHN0cikgLT4g"
    "Tm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fbW9kZWxfbG9hZGVkOgogICAgICAgICAgICByZXR1"
    "cm4KICAgICAgICBzZWxmLl9zZW50X3dvcmtlciA9IFNlbnRpbWVudFdvcmtlcihzZWxmLl9hZGFw"
    "dG9yLCByZXNwb25zZSkKICAgICAgICBzZWxmLl9zZW50X3dvcmtlci5mYWNlX3JlYWR5LmNvbm5l"
    "Y3Qoc2VsZi5fb25fc2VudGltZW50KQogICAgICAgIHNlbGYuX3NlbnRfd29ya2VyLnN0YXJ0KCkK"
    "CiAgICBkZWYgX29uX3NlbnRpbWVudChzZWxmLCBlbW90aW9uOiBzdHIpIC0+IE5vbmU6CiAgICAg"
    "ICAgaWYgc2VsZi5fZmFjZV90aW1lcl9tZ3I6CiAgICAgICAgICAgIHNlbGYuX2ZhY2VfdGltZXJf"
    "bWdyLnNldF9mYWNlKGVtb3Rpb24pCgogICAgZGVmIF9vbl9lcnJvcihzZWxmLCBlcnJvcjogc3Ry"
    "KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJFUlJPUiIsIGVycm9yKQogICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHRU5FUkFUSU9OIEVSUk9SXSB7ZXJyb3J9IiwgIkVS"
    "Uk9SIikKICAgICAgICBpZiBzZWxmLl9mYWNlX3RpbWVyX21ncjoKICAgICAgICAgICAgc2VsZi5f"
    "ZmFjZV90aW1lcl9tZ3Iuc2V0X2ZhY2UoInBhbmlja2VkIikKICAgICAgICBzZWxmLl9zZXRfc3Rh"
    "dHVzKCJFUlJPUiIpCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChUcnVlKQogICAg"
    "ICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKCiAgICAjIOKUgOKUgCBUT1JQ"
    "T1IgU1lTVEVNIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgZGVmIF9vbl90b3Jwb3Jfc3RhdGVfY2hhbmdlZChzZWxmLCBzdGF0"
    "ZTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3RvcnBvcl9zdGF0ZSA9IHN0YXRlCgogICAg"
    "ICAgIGlmIHN0YXRlID09ICJTVVNQRU5EIjoKICAgICAgICAgICAgc2VsZi5fZW50ZXJfdG9ycG9y"
    "KHJlYXNvbj0ibWFudWFsIOKAlCBTVVNQRU5EIG1vZGUgc2VsZWN0ZWQiKQogICAgICAgIGVsaWYg"
    "c3RhdGUgPT0gIkFXQUtFIjoKICAgICAgICAgICAgIyBBbHdheXMgZXhpdCB0b3Jwb3Igd2hlbiBz"
    "d2l0Y2hpbmcgdG8gQVdBS0Ug4oCUCiAgICAgICAgICAgICMgZXZlbiB3aXRoIE9sbGFtYSBiYWNr"
    "ZW5kIHdoZXJlIG1vZGVsIGlzbid0IHVubG9hZGVkLAogICAgICAgICAgICAjIHdlIG5lZWQgdG8g"
    "cmUtZW5hYmxlIFVJIGFuZCByZXNldCBzdGF0ZQogICAgICAgICAgICBzZWxmLl9leGl0X3RvcnBv"
    "cigpCiAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgPSAwCiAgICAgICAgICAg"
    "IHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICAgPSAwCiAgICAgICAgZWxpZiBzdGF0ZSA9PSAiQVVU"
    "TyI6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICJbVE9S"
    "UE9SXSBBVVRPIG1vZGUg4oCUIG1vbml0b3JpbmcgVlJBTSBwcmVzc3VyZS4iLCAiSU5GTyIKICAg"
    "ICAgICAgICAgKQoKICAgIGRlZiBfZW50ZXJfdG9ycG9yKHNlbGYsIHJlYXNvbjogc3RyID0gIm1h"
    "bnVhbCIpIC0+IE5vbmU6CiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIG5vdCBOb25l"
    "OgogICAgICAgICAgICByZXR1cm4gICMgQWxyZWFkeSBpbiB0b3Jwb3IKCiAgICAgICAgc2VsZi5f"
    "dG9ycG9yX3NpbmNlID0gZGF0ZXRpbWUubm93KCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "ZiJbVE9SUE9SXSBFbnRlcmluZyB0b3Jwb3I6IHtyZWFzb259IiwgIldBUk4iKQogICAgICAgIHNl"
    "bGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCAiVGhlIHZlc3NlbCBncm93cyBjcm93ZGVkLiBJIHdp"
    "dGhkcmF3LiIpCgogICAgICAgICMgVW5sb2FkIG1vZGVsIGZyb20gVlJBTQogICAgICAgIGlmIHNl"
    "bGYuX21vZGVsX2xvYWRlZCBhbmQgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgTG9jYWxUcmFuc2Zvcm1lcnNBZGFw"
    "dG9yKToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgaWYgc2VsZi5fYWRhcHRvci5f"
    "bW9kZWwgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICAgICAgZGVsIHNlbGYuX2FkYXB0b3Iu"
    "X21vZGVsCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fYWRhcHRvci5fbW9kZWwgPSBOb25lCiAg"
    "ICAgICAgICAgICAgICBpZiBUT1JDSF9PSzoKICAgICAgICAgICAgICAgICAgICB0b3JjaC5jdWRh"
    "LmVtcHR5X2NhY2hlKCkKICAgICAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IuX2xvYWRlZCA9IEZh"
    "bHNlCiAgICAgICAgICAgICAgICBzZWxmLl9tb2RlbF9sb2FkZWQgICAgPSBGYWxzZQogICAgICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbVE9SUE9SXSBNb2RlbCB1bmxvYWRlZCBmcm9t"
    "IFZSQU0uIiwgIk9LIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAg"
    "ICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1RPUlBP"
    "Ul0gTW9kZWwgdW5sb2FkIGVycm9yOiB7ZX0iLCAiRVJST1IiCiAgICAgICAgICAgICAgICApCgog"
    "ICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZSgibmV1dHJhbCIpCiAgICAgICAgc2VsZi5fc2V0"
    "X3N0YXR1cygiVE9SUE9SIikKICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKEZhbHNl"
    "KQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2UpCgogICAgZGVmIF9l"
    "eGl0X3RvcnBvcihzZWxmKSAtPiBOb25lOgogICAgICAgICMgQ2FsY3VsYXRlIHN1c3BlbmRlZCBk"
    "dXJhdGlvbgogICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZToKICAgICAgICAgICAgZGVsdGEg"
    "PSBkYXRldGltZS5ub3coKSAtIHNlbGYuX3RvcnBvcl9zaW5jZQogICAgICAgICAgICBzZWxmLl9z"
    "dXNwZW5kZWRfZHVyYXRpb24gPSBmb3JtYXRfZHVyYXRpb24oZGVsdGEudG90YWxfc2Vjb25kcygp"
    "KQogICAgICAgICAgICBzZWxmLl90b3Jwb3Jfc2luY2UgPSBOb25lCgogICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZygiW1RPUlBPUl0gV2FraW5nIGZyb20gdG9ycG9yLi4uIiwgIklORk8iKQoKICAg"
    "ICAgICBpZiBzZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgICMgT2xsYW1hIGJhY2tlbmQg"
    "4oCUIG1vZGVsIHdhcyBuZXZlciB1bmxvYWRlZCwganVzdCByZS1lbmFibGUgVUkKICAgICAgICAg"
    "ICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgICAgICBmIlRoZSB2ZXNz"
    "ZWwgZW1wdGllcy4ge0RFQ0tfTkFNRX0gc3RpcnMgIgogICAgICAgICAgICAgICAgZiIoe3NlbGYu"
    "X3N1c3BlbmRlZF9kdXJhdGlvbiBvciAnYnJpZWZseSd9IGVsYXBzZWQpLiIKICAgICAgICAgICAg"
    "KQogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgIlRoZSBjb25uZWN0aW9u"
    "IGhvbGRzLiBTaGUgaXMgbGlzdGVuaW5nLiIpCiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMo"
    "IklETEUiKQogICAgICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAg"
    "ICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKCJbVE9SUE9SXSBBV0FLRSBtb2RlIOKAlCBhdXRvLXRvcnBvciBkaXNh"
    "YmxlZC4iLCAiSU5GTyIpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgIyBMb2NhbCBtb2RlbCB3"
    "YXMgdW5sb2FkZWQg4oCUIG5lZWQgZnVsbCByZWxvYWQKICAgICAgICAgICAgc2VsZi5fYXBwZW5k"
    "X2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgICAgICBmIlRoZSB2ZXNzZWwgZW1wdGllcy4ge0RF"
    "Q0tfTkFNRX0gc3RpcnMgZnJvbSB0b3Jwb3IgIgogICAgICAgICAgICAgICAgZiIoe3NlbGYuX3N1"
    "c3BlbmRlZF9kdXJhdGlvbiBvciAnYnJpZWZseSd9IGVsYXBzZWQpLiIKICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJMT0FESU5HIikKICAgICAgICAgICAgc2VsZi5f"
    "bG9hZGVyID0gTW9kZWxMb2FkZXJXb3JrZXIoc2VsZi5fYWRhcHRvcikKICAgICAgICAgICAgc2Vs"
    "Zi5fbG9hZGVyLm1lc3NhZ2UuY29ubmVjdCgKICAgICAgICAgICAgICAgIGxhbWJkYSBtOiBzZWxm"
    "Ll9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgbSkpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5lcnJv"
    "ci5jb25uZWN0KAogICAgICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2FwcGVuZF9jaGF0KCJF"
    "UlJPUiIsIGUpKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIubG9hZF9jb21wbGV0ZS5jb25uZWN0"
    "KHNlbGYuX29uX2xvYWRfY29tcGxldGUpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5maW5pc2hl"
    "ZC5jb25uZWN0KHNlbGYuX2xvYWRlci5kZWxldGVMYXRlcikKICAgICAgICAgICAgc2VsZi5fYWN0"
    "aXZlX3RocmVhZHMuYXBwZW5kKHNlbGYuX2xvYWRlcikKICAgICAgICAgICAgc2VsZi5fbG9hZGVy"
    "LnN0YXJ0KCkKCiAgICBkZWYgX2NoZWNrX3ZyYW1fcHJlc3N1cmUoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICAiIiIKICAgICAgICBDYWxsZWQgZXZlcnkgNSBzZWNvbmRzIGZyb20gQVBTY2hlZHVsZXIg"
    "d2hlbiB0b3Jwb3Igc3RhdGUgaXMgQVVUTy4KICAgICAgICBPbmx5IHRyaWdnZXJzIHRvcnBvciBp"
    "ZiBleHRlcm5hbCBWUkFNIHVzYWdlIGV4Y2VlZHMgdGhyZXNob2xkCiAgICAgICAgQU5EIGlzIHN1"
    "c3RhaW5lZCDigJQgbmV2ZXIgdHJpZ2dlcnMgb24gdGhlIHBlcnNvbmEncyBvd24gZm9vdHByaW50"
    "LgogICAgICAgICIiIgogICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zdGF0ZSAhPSAiQVVUTyI6CiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIGlmIG5vdCBOVk1MX09LIG9yIG5vdCBncHVfaGFuZGxl"
    "OgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBzZWxmLl9kZWNrX3ZyYW1fYmFzZSA8PSAw"
    "OgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBtZW1faW5mbyAg"
    "PSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAg"
    "dG90YWxfdXNlZCA9IG1lbV9pbmZvLnVzZWQgLyAxMDI0KiozCiAgICAgICAgICAgIGV4dGVybmFs"
    "ICAgPSB0b3RhbF91c2VkIC0gc2VsZi5fZGVja192cmFtX2Jhc2UKCiAgICAgICAgICAgIGlmIGV4"
    "dGVybmFsID4gc2VsZi5fRVhURVJOQUxfVlJBTV9UT1JQT1JfR0I6CiAgICAgICAgICAgICAgICBp"
    "ZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICAgICAgcmV0"
    "dXJuICAjIEFscmVhZHkgaW4gdG9ycG9yIOKAlCBkb24ndCBrZWVwIGNvdW50aW5nCiAgICAgICAg"
    "ICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzICs9IDEKICAgICAgICAgICAgICAgIHNl"
    "bGYuX3ZyYW1fcmVsaWVmX3RpY2tzICAgID0gMAogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1RPUlBPUiBBVVRPXSBFeHRlcm5hbCBWUkFN"
    "IHByZXNzdXJlOiAiCiAgICAgICAgICAgICAgICAgICAgZiJ7ZXh0ZXJuYWw6LjJmfUdCICIKICAg"
    "ICAgICAgICAgICAgICAgICBmIih0aWNrIHtzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzfS8iCiAg"
    "ICAgICAgICAgICAgICAgICAgZiJ7c2VsZi5fVE9SUE9SX1NVU1RBSU5FRF9USUNLU30pIiwgIldB"
    "Uk4iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBpZiAoc2VsZi5fdnJhbV9wcmVz"
    "c3VyZV90aWNrcyA+PSBzZWxmLl9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGFuZCBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgTm9uZSk6CiAgICAgICAgICAgICAg"
    "ICAgICAgc2VsZi5fZW50ZXJfdG9ycG9yKAogICAgICAgICAgICAgICAgICAgICAgICByZWFzb249"
    "ZiJhdXRvIOKAlCB7ZXh0ZXJuYWw6LjFmfUdCIGV4dGVybmFsIFZSQU0gIgogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgZiJwcmVzc3VyZSBzdXN0YWluZWQiCiAgICAgICAgICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgPSAwICAj"
    "IHJlc2V0IGFmdGVyIGVudGVyaW5nIHRvcnBvcgogICAgICAgICAgICBlbHNlOgogICAgICAgICAg"
    "ICAgICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9IDAKICAgICAgICAgICAgICAgIGlmIHNl"
    "bGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICBzZWxmLl92"
    "cmFtX3JlbGllZl90aWNrcyArPSAxCiAgICAgICAgICAgICAgICAgICAgYXV0b193YWtlID0gQ0ZH"
    "WyJzZXR0aW5ncyJdLmdldCgKICAgICAgICAgICAgICAgICAgICAgICAgImF1dG9fd2FrZV9vbl9y"
    "ZWxpZWYiLCBGYWxzZQogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICBp"
    "ZiAoYXV0b193YWtlIGFuZAogICAgICAgICAgICAgICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9y"
    "ZWxpZWZfdGlja3MgPj0gc2VsZi5fV0FLRV9TVVNUQUlORURfVElDS1MpOgogICAgICAgICAgICAg"
    "ICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyA9IDAKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgc2VsZi5fZXhpdF90b3Jwb3IoKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6"
    "CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW1RPUlBP"
    "UiBBVVRPXSBWUkFNIGNoZWNrIGVycm9yOiB7ZX0iLCAiRVJST1IiCiAgICAgICAgICAgICkKCiAg"
    "ICAjIOKUgOKUgCBBUFNDSEVEVUxFUiBTRVRVUCDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfc2V0dXBfc2NoZWR1bGVyKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBmcm9tIGFwc2NoZWR1bGVyLnNjaGVkdWxlcnMu"
    "YmFja2dyb3VuZCBpbXBvcnQgQmFja2dyb3VuZFNjaGVkdWxlcgogICAgICAgICAgICBzZWxmLl9z"
    "Y2hlZHVsZXIgPSBCYWNrZ3JvdW5kU2NoZWR1bGVyKAogICAgICAgICAgICAgICAgam9iX2RlZmF1"
    "bHRzPXsibWlzZmlyZV9ncmFjZV90aW1lIjogNjB9CiAgICAgICAgICAgICkKICAgICAgICBleGNl"
    "cHQgSW1wb3J0RXJyb3I6CiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlciA9IE5vbmUKICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIltTQ0hFRFVMRVJdIGFw"
    "c2NoZWR1bGVyIG5vdCBhdmFpbGFibGUg4oCUICIKICAgICAgICAgICAgICAgICJpZGxlLCBhdXRv"
    "c2F2ZSwgYW5kIHJlZmxlY3Rpb24gZGlzYWJsZWQuIiwgIldBUk4iCiAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgcmV0dXJuCgogICAgICAgIGludGVydmFsX21pbiA9IENGR1sic2V0dGluZ3MiXS5n"
    "ZXQoImF1dG9zYXZlX2ludGVydmFsX21pbnV0ZXMiLCAxMCkKCiAgICAgICAgIyBBdXRvc2F2ZQog"
    "ICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAgICAgICBzZWxmLl9hdXRvc2F2"
    "ZSwgImludGVydmFsIiwKICAgICAgICAgICAgbWludXRlcz1pbnRlcnZhbF9taW4sIGlkPSJhdXRv"
    "c2F2ZSIKICAgICAgICApCgogICAgICAgICMgVlJBTSBwcmVzc3VyZSBjaGVjayAoZXZlcnkgNXMp"
    "CiAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAgICAgICAgICAgIHNlbGYuX2NoZWNr"
    "X3ZyYW1fcHJlc3N1cmUsICJpbnRlcnZhbCIsCiAgICAgICAgICAgIHNlY29uZHM9NSwgaWQ9InZy"
    "YW1fY2hlY2siCiAgICAgICAgKQoKICAgICAgICAjIElkbGUgdHJhbnNtaXNzaW9uIChzdGFydHMg"
    "cGF1c2VkIOKAlCBlbmFibGVkIGJ5IGlkbGUgdG9nZ2xlKQogICAgICAgIGlkbGVfbWluID0gQ0ZH"
    "WyJzZXR0aW5ncyJdLmdldCgiaWRsZV9taW5fbWludXRlcyIsIDEwKQogICAgICAgIGlkbGVfbWF4"
    "ID0gQ0ZHWyJzZXR0aW5ncyJdLmdldCgiaWRsZV9tYXhfbWludXRlcyIsIDMwKQogICAgICAgIGlk"
    "bGVfaW50ZXJ2YWwgPSAoaWRsZV9taW4gKyBpZGxlX21heCkgLy8gMgoKICAgICAgICBzZWxmLl9z"
    "Y2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgc2VsZi5fZmlyZV9pZGxlX3RyYW5zbWlzc2lv"
    "biwgImludGVydmFsIiwKICAgICAgICAgICAgbWludXRlcz1pZGxlX2ludGVydmFsLCBpZD0iaWRs"
    "ZV90cmFuc21pc3Npb24iCiAgICAgICAgKQoKICAgICAgICAjIEN5Y2xlIHdpZGdldCByZWZyZXNo"
    "IChldmVyeSA2IGhvdXJzKQogICAgICAgIGlmIHNlbGYuX2N5Y2xlX3dpZGdldCBpcyBub3QgTm9u"
    "ZToKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9jeWNsZV93aWRnZXQudXBkYXRlUGhhc2UsICJpbnRlcnZhbCIsCiAgICAgICAgICAgICAg"
    "ICBob3Vycz02LCBpZD0ibW9vbl9yZWZyZXNoIgogICAgICAgICAgICApCgogICAgICAgICMgTk9U"
    "RTogc2NoZWR1bGVyLnN0YXJ0KCkgaXMgY2FsbGVkIGZyb20gc3RhcnRfc2NoZWR1bGVyKCkKICAg"
    "ICAgICAjIHdoaWNoIGlzIHRyaWdnZXJlZCB2aWEgUVRpbWVyLnNpbmdsZVNob3QgQUZURVIgdGhl"
    "IHdpbmRvdwogICAgICAgICMgaXMgc2hvd24gYW5kIHRoZSBRdCBldmVudCBsb29wIGlzIHJ1bm5p"
    "bmcuCiAgICAgICAgIyBEbyBOT1QgY2FsbCBzZWxmLl9zY2hlZHVsZXIuc3RhcnQoKSBoZXJlLgoK"
    "ICAgIGRlZiBzdGFydF9zY2hlZHVsZXIoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAg"
    "ICBDYWxsZWQgdmlhIFFUaW1lci5zaW5nbGVTaG90IGFmdGVyIHdpbmRvdy5zaG93KCkgYW5kIGFw"
    "cC5leGVjKCkgYmVnaW5zLgogICAgICAgIERlZmVycmVkIHRvIGVuc3VyZSBRdCBldmVudCBsb29w"
    "IGlzIHJ1bm5pbmcgYmVmb3JlIGJhY2tncm91bmQgdGhyZWFkcyBzdGFydC4KICAgICAgICAiIiIK"
    "ICAgICAgICBpZiBzZWxmLl9zY2hlZHVsZXIgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIuc3RhcnQoKQogICAgICAgICAg"
    "ICAjIElkbGUgc3RhcnRzIHBhdXNlZAogICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIucGF1c2Vf"
    "am9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygi"
    "W1NDSEVEVUxFUl0gQVBTY2hlZHVsZXIgc3RhcnRlZC4iLCAiT0siKQogICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1NDSEVEVUxF"
    "Ul0gU3RhcnQgZXJyb3I6IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIF9hdXRvc2F2ZShzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbnMuc2F2ZSgpCiAg"
    "ICAgICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXRfYXV0b3NhdmVfaW5kaWNhdG9yKFRy"
    "dWUpCiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KAogICAgICAgICAgICAgICAgMzAwMCwg"
    "bGFtYmRhOiBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2V0X2F1dG9zYXZlX2luZGljYXRvcihGYWxz"
    "ZSkKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltBVVRPU0FW"
    "RV0gU2Vzc2lvbiBzYXZlZC4iLCAiSU5GTyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBl"
    "OgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbQVVUT1NBVkVdIEVycm9yOiB7ZX0i"
    "LCAiRVJST1IiKQoKICAgIGRlZiBfZmlyZV9pZGxlX3RyYW5zbWlzc2lvbihzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIGlmIG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQgb3Igc2VsZi5fc3RhdHVzID09ICJH"
    "RU5FUkFUSU5HIjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3Np"
    "bmNlIGlzIG5vdCBOb25lOgogICAgICAgICAgICAjIEluIHRvcnBvciDigJQgY291bnQgdGhlIHBl"
    "bmRpbmcgdGhvdWdodCBidXQgZG9uJ3QgZ2VuZXJhdGUKICAgICAgICAgICAgc2VsZi5fcGVuZGlu"
    "Z190cmFuc21pc3Npb25zICs9IDEKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAg"
    "ICAgICAgICAgICAgZiJbSURMRV0gSW4gdG9ycG9yIOKAlCBwZW5kaW5nIHRyYW5zbWlzc2lvbiAi"
    "CiAgICAgICAgICAgICAgICBmIiN7c2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zfSIsICJJTkZP"
    "IgogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICBtb2RlID0gcmFuZG9t"
    "LmNob2ljZShbIkRFRVBFTklORyIsIkJSQU5DSElORyIsIlNZTlRIRVNJUyJdKQogICAgICAgIHZh"
    "bXBpcmVfY3R4ID0gYnVpbGRfdmFtcGlyZV9jb250ZXh0KCkKICAgICAgICBoaXN0b3J5ID0gc2Vs"
    "Zi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQoKICAgICAgICBzZWxmLl9pZGxlX3dvcmtlciA9IElk"
    "bGVXb3JrZXIoCiAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IsCiAgICAgICAgICAgIFNZU1RFTV9Q"
    "Uk9NUFRfQkFTRSwKICAgICAgICAgICAgaGlzdG9yeSwKICAgICAgICAgICAgbW9kZT1tb2RlLAog"
    "ICAgICAgICAgICB2YW1waXJlX2NvbnRleHQ9dmFtcGlyZV9jdHgsCiAgICAgICAgKQogICAgICAg"
    "IGRlZiBfb25faWRsZV9yZWFkeSh0OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgICAgICMgRmxpcCB0"
    "byBTZWxmIHRhYiBhbmQgYXBwZW5kIHRoZXJlCiAgICAgICAgICAgIHNlbGYuX21haW5fdGFicy5z"
    "ZXRDdXJyZW50SW5kZXgoMSkKICAgICAgICAgICAgdHMgPSBkYXRldGltZS5ub3coKS5zdHJmdGlt"
    "ZSgiJUg6JU0iKQogICAgICAgICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkuYXBwZW5kKAogICAgICAg"
    "ICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBw"
    "eDsiPicKICAgICAgICAgICAgICAgIGYnW3t0c31dIFt7bW9kZX1dPC9zcGFuPjxicj4nCiAgICAg"
    "ICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19HT0xEfTsiPnt0fTwvc3Bhbj48YnI+"
    "JwogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NlbGZfdGFiLmFwcGVuZCgiTkFSUkFU"
    "SVZFIiwgdCkKCiAgICAgICAgc2VsZi5faWRsZV93b3JrZXIudHJhbnNtaXNzaW9uX3JlYWR5LmNv"
    "bm5lY3QoX29uX2lkbGVfcmVhZHkpCiAgICAgICAgc2VsZi5faWRsZV93b3JrZXIuZXJyb3Jfb2Nj"
    "dXJyZWQuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2RpYWdfdGFiLmxvZyhm"
    "IltJRExFIEVSUk9SXSB7ZX0iLCAiRVJST1IiKQogICAgICAgICkKICAgICAgICBzZWxmLl9pZGxl"
    "X3dvcmtlci5zdGFydCgpCgogICAgIyDilIDilIAgSk9VUk5BTCBTRVNTSU9OIExPQURJTkcg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2xvYWRfam91cm5hbF9zZXNzaW9u"
    "KHNlbGYsIGRhdGVfc3RyOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgY3R4ID0gc2VsZi5fc2Vzc2lv"
    "bnMubG9hZF9zZXNzaW9uX2FzX2NvbnRleHQoZGF0ZV9zdHIpCiAgICAgICAgaWYgbm90IGN0eDoK"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbSk9VUk5B"
    "TF0gTm8gc2Vzc2lvbiBmb3VuZCBmb3Ige2RhdGVfc3RyfSIsICJXQVJOIgogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXRfam91"
    "cm5hbF9sb2FkZWQoZGF0ZV9zdHIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAg"
    "ICAgICBmIltKT1VSTkFMXSBMb2FkZWQgc2Vzc2lvbiBmcm9tIHtkYXRlX3N0cn0gYXMgY29udGV4"
    "dC4gIgogICAgICAgICAgICBmIntERUNLX05BTUV9IGlzIG5vdyBhd2FyZSBvZiB0aGF0IGNvbnZl"
    "cnNhdGlvbi4iLCAiT0siCiAgICAgICAgKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNU"
    "RU0iLAogICAgICAgICAgICBmIkEgbWVtb3J5IHN0aXJzLi4uIHRoZSBqb3VybmFsIG9mIHtkYXRl"
    "X3N0cn0gb3BlbnMgYmVmb3JlIGhlci4iCiAgICAgICAgKQogICAgICAgICMgTm90aWZ5IE1vcmdh"
    "bm5hCiAgICAgICAgaWYgc2VsZi5fbW9kZWxfbG9hZGVkOgogICAgICAgICAgICBub3RlID0gKAog"
    "ICAgICAgICAgICAgICAgZiJbSk9VUk5BTCBMT0FERURdIFRoZSB1c2VyIGhhcyBvcGVuZWQgdGhl"
    "IGpvdXJuYWwgZnJvbSAiCiAgICAgICAgICAgICAgICBmIntkYXRlX3N0cn0uIEFja25vd2xlZGdl"
    "IHRoaXMgYnJpZWZseSDigJQgeW91IG5vdyBoYXZlICIKICAgICAgICAgICAgICAgIGYiYXdhcmVu"
    "ZXNzIG9mIHRoYXQgY29udmVyc2F0aW9uLiIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxm"
    "Ll9zZXNzaW9ucy5hZGRfbWVzc2FnZSgic3lzdGVtIiwgbm90ZSkKCiAgICBkZWYgX2NsZWFyX2pv"
    "dXJuYWxfc2Vzc2lvbihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nlc3Npb25zLmNsZWFy"
    "X2xvYWRlZF9qb3VybmFsKCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltKT1VSTkFMXSBK"
    "b3VybmFsIGNvbnRleHQgY2xlYXJlZC4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fYXBwZW5kX2No"
    "YXQoIlNZU1RFTSIsCiAgICAgICAgICAgICJUaGUgam91cm5hbCBjbG9zZXMuIE9ubHkgdGhlIHBy"
    "ZXNlbnQgcmVtYWlucy4iCiAgICAgICAgKQoKICAgICMg4pSA4pSAIFNUQVRTIFVQREFURSDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgIGRlZiBfdXBkYXRlX3N0YXRzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZWxhcHNlZCA9"
    "IGludCh0aW1lLnRpbWUoKSAtIHNlbGYuX3Nlc3Npb25fc3RhcnQpCiAgICAgICAgaCwgbSwgcyA9"
    "IGVsYXBzZWQgLy8gMzYwMCwgKGVsYXBzZWQgJSAzNjAwKSAvLyA2MCwgZWxhcHNlZCAlIDYwCiAg"
    "ICAgICAgc2Vzc2lvbl9zdHIgPSBmIntoOjAyZH06e206MDJkfTp7czowMmR9IgoKICAgICAgICBz"
    "ZWxmLl9od19wYW5lbC5zZXRfc3RhdHVzX2xhYmVscygKICAgICAgICAgICAgc2VsZi5fc3RhdHVz"
    "LAogICAgICAgICAgICBDRkdbIm1vZGVsIl0uZ2V0KCJ0eXBlIiwibG9jYWwiKS51cHBlcigpLAog"
    "ICAgICAgICAgICBzZXNzaW9uX3N0ciwKICAgICAgICAgICAgc3RyKHNlbGYuX3Rva2VuX2NvdW50"
    "KSwKICAgICAgICApCiAgICAgICAgc2VsZi5faHdfcGFuZWwudXBkYXRlX3N0YXRzKCkKCiAgICAg"
    "ICAgIyBMZWZ0IHNwaGVyZSA9IGFjdGl2ZSByZXNlcnZlIGZyb20gcnVudGltZSB0b2tlbiBwb29s"
    "CiAgICAgICAgbGVmdF9vcmJfZmlsbCA9IG1pbigxLjAsIHNlbGYuX3Rva2VuX2NvdW50IC8gNDA5"
    "Ni4wKQogICAgICAgIGlmIHNlbGYuX2xlZnRfb3JiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBz"
    "ZWxmLl9sZWZ0X29yYi5zZXRGaWxsKGxlZnRfb3JiX2ZpbGwsIGF2YWlsYWJsZT1UcnVlKQoKICAg"
    "ICAgICAjIFJpZ2h0IHNwaGVyZSA9IFZSQU0gYXZhaWxhYmlsaXR5CiAgICAgICAgaWYgc2VsZi5f"
    "cmlnaHRfb3JiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBpZiBOVk1MX09LIGFuZCBncHVfaGFu"
    "ZGxlOgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIG1lbSA9IHB5bnZt"
    "bC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgICAg"
    "IHZyYW1fdXNlZCA9IG1lbS51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAgICAgICAgICB2cmFt"
    "X3RvdCAgPSBtZW0udG90YWwgLyAxMDI0KiozCiAgICAgICAgICAgICAgICAgICAgcmlnaHRfb3Ji"
    "X2ZpbGwgPSBtYXgoMC4wLCAxLjAgLSAodnJhbV91c2VkIC8gdnJhbV90b3QpKQogICAgICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3JpZ2h0X29yYi5zZXRGaWxsKHJpZ2h0X29yYl9maWxsLCBhdmFpbGFi"
    "bGU9VHJ1ZSkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAg"
    "ICAgICAgc2VsZi5fcmlnaHRfb3JiLnNldEZpbGwoMC4wLCBhdmFpbGFibGU9RmFsc2UpCiAgICAg"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9yaWdodF9vcmIuc2V0RmlsbCgwLjAs"
    "IGF2YWlsYWJsZT1GYWxzZSkKCiAgICAgICAgIyBQcmltYXJ5IGVzc2VuY2UgPSBpbnZlcnNlIG9m"
    "IGxlZnQgc3BoZXJlIGZpbGwKICAgICAgICBlc3NlbmNlX3ByaW1hcnlfcmF0aW8gPSAxLjAgLSBs"
    "ZWZ0X29yYl9maWxsCiAgICAgICAgaWYgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAgICAgICAgIHNl"
    "bGYuX2Vzc2VuY2VfcHJpbWFyeV9nYXVnZS5zZXRWYWx1ZShlc3NlbmNlX3ByaW1hcnlfcmF0aW8g"
    "KiAxMDAsIGYie2Vzc2VuY2VfcHJpbWFyeV9yYXRpbyoxMDA6LjBmfSUiKQoKICAgICAgICAjIFNl"
    "Y29uZGFyeSBlc3NlbmNlID0gUkFNIGZyZWUKICAgICAgICBpZiBBSV9TVEFURVNfRU5BQkxFRDoK"
    "ICAgICAgICAgICAgaWYgUFNVVElMX09LOgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAg"
    "ICAgICAgICAgIG1lbSAgICAgICA9IHBzdXRpbC52aXJ0dWFsX21lbW9yeSgpCiAgICAgICAgICAg"
    "ICAgICAgICAgZXNzZW5jZV9zZWNvbmRhcnlfcmF0aW8gID0gMS4wIC0gKG1lbS51c2VkIC8gbWVt"
    "LnRvdGFsKQogICAgICAgICAgICAgICAgICAgIHNlbGYuX2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdl"
    "LnNldFZhbHVlKAogICAgICAgICAgICAgICAgICAgICAgICBlc3NlbmNlX3NlY29uZGFyeV9yYXRp"
    "byAqIDEwMCwgZiJ7ZXNzZW5jZV9zZWNvbmRhcnlfcmF0aW8qMTAwOi4wZn0lIgogICAgICAgICAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAg"
    "ICAgICAgICAgc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2Uuc2V0VW5hdmFpbGFibGUoKQog"
    "ICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlf"
    "Z2F1Z2Uuc2V0VW5hdmFpbGFibGUoKQoKICAgICAgICAjIFVwZGF0ZSBqb3VybmFsIHNpZGViYXIg"
    "YXV0b3NhdmUgZmxhc2gKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIucmVmcmVzaCgpCgog"
    "ICAgIyDilIDilIAgQ0hBVCBESVNQTEFZIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9hcHBlbmRfY2hhdChzZWxm"
    "LCBzcGVha2VyOiBzdHIsIHRleHQ6IHN0cikgLT4gTm9uZToKICAgICAgICBjb2xvcnMgPSB7CiAg"
    "ICAgICAgICAgICJZT1UiOiAgICAgQ19HT0xELAogICAgICAgICAgICBERUNLX05BTUUudXBwZXIo"
    "KTpDX0dPTEQsCiAgICAgICAgICAgICJTWVNURU0iOiAgQ19QVVJQTEUsCiAgICAgICAgICAgICJF"
    "UlJPUiI6ICAgQ19CTE9PRCwKICAgICAgICB9CiAgICAgICAgbGFiZWxfY29sb3JzID0gewogICAg"
    "ICAgICAgICAiWU9VIjogICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgIERFQ0tfTkFNRS51cHBl"
    "cigpOkNfQ1JJTVNPTiwKICAgICAgICAgICAgIlNZU1RFTSI6ICBDX1BVUlBMRSwKICAgICAgICAg"
    "ICAgIkVSUk9SIjogICBDX0JMT09ELAogICAgICAgIH0KICAgICAgICBjb2xvciAgICAgICA9IGNv"
    "bG9ycy5nZXQoc3BlYWtlciwgQ19HT0xEKQogICAgICAgIGxhYmVsX2NvbG9yID0gbGFiZWxfY29s"
    "b3JzLmdldChzcGVha2VyLCBDX0dPTERfRElNKQogICAgICAgIHRpbWVzdGFtcCAgID0gZGF0ZXRp"
    "bWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikKCiAgICAgICAgaWYgc3BlYWtlciA9PSAiU1lT"
    "VEVNIjoKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAg"
    "ICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4n"
    "CiAgICAgICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAgICAgICAg"
    "IGYnPHNwYW4gc3R5bGU9ImNvbG9yOntsYWJlbF9jb2xvcn07Ij7inKYge3RleHR9PC9zcGFuPicK"
    "ICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxh"
    "eS5hcHBlbmQoCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJ"
    "TX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICAgICAgZidbe3RpbWVzdGFtcH1dIDwv"
    "c3Bhbj4nCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7bGFiZWxfY29sb3J9"
    "OyBmb250LXdlaWdodDpib2xkOyI+JwogICAgICAgICAgICAgICAgZid7c3BlYWtlcn0g4p2nPC9z"
    "cGFuPiAnCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Y29sb3J9OyI+e3Rl"
    "eHR9PC9zcGFuPicKICAgICAgICAgICAgKQoKICAgICAgICAjIEFkZCBibGFuayBsaW5lIGFmdGVy"
    "IE1vcmdhbm5hJ3MgcmVzcG9uc2UgKG5vdCBkdXJpbmcgc3RyZWFtaW5nKQogICAgICAgIGlmIHNw"
    "ZWFrZXIgPT0gREVDS19OQU1FLnVwcGVyKCk6CiAgICAgICAgICAgIHNlbGYuX2NoYXRfZGlzcGxh"
    "eS5hcHBlbmQoIiIpCgogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJh"
    "cigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkudmVydGljYWxTY3Jv"
    "bGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAgIyDilIDilIAgU1RBVFVTIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9nZXRfZ29vZ2xlX3JlZnJlc2hfaW50ZXJ2YWxfbXMo"
    "c2VsZikgLT4gaW50OgogICAgICAgIHNldHRpbmdzID0gQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkK"
    "ICAgICAgICB2YWwgPSBzZXR0aW5ncy5nZXQoImdvb2dsZV9pbmJvdW5kX2ludGVydmFsX21zIiwg"
    "MzAwMDAwKQogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIG1heCgxMDAwLCBpbnQodmFs"
    "KSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4gMzAwMDAwCgog"
    "ICAgZGVmIF9nZXRfZW1haWxfcmVmcmVzaF9pbnRlcnZhbF9tcyhzZWxmKSAtPiBpbnQ6CiAgICAg"
    "ICAgc2V0dGluZ3MgPSBDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KQogICAgICAgIHZhbCA9IHNldHRp"
    "bmdzLmdldCgiZW1haWxfcmVmcmVzaF9pbnRlcnZhbF9tcyIsIDMwMDAwMCkKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIHJldHVybiBtYXgoMTAwMCwgaW50KHZhbCkpCiAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIDMwMDAwMAoKICAgIGRlZiBfc2V0X2dvb2dsZV9y"
    "ZWZyZXNoX3NlY29uZHMoc2VsZiwgc2Vjb25kczogaW50KSAtPiBOb25lOgogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgc2Vjb25kcyA9IG1heCg1LCBtaW4oNjAwLCBpbnQoc2Vjb25kcykpKQogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHJldHVybgogICAgICAgIENGR1sic2V0"
    "dGluZ3MiXVsiZ29vZ2xlX2luYm91bmRfaW50ZXJ2YWxfbXMiXSA9IHNlY29uZHMgKiAxMDAwCiAg"
    "ICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIGZvciB0aW1lciBpbiAoc2VsZi5fZ29vZ2xl"
    "X2luYm91bmRfdGltZXIsIHNlbGYuX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXIpOgogICAg"
    "ICAgICAgICBpZiB0aW1lciBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgIHRpbWVyLnN0YXJ0"
    "KHNlbGYuX2dldF9nb29nbGVfcmVmcmVzaF9pbnRlcnZhbF9tcygpKQogICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZyhmIltTRVRUSU5HU10gR29vZ2xlIHJlZnJlc2ggaW50ZXJ2YWwgc2V0IHRvIHtz"
    "ZWNvbmRzfSBzZWNvbmQocykuIiwgIk9LIikKCiAgICBkZWYgX3NldF9lbWFpbF9yZWZyZXNoX21p"
    "bnV0ZXNfZnJvbV90ZXh0KHNlbGYsIHRleHQ6IHN0cikgLT4gTm9uZToKICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgIG1pbnV0ZXMgPSBtYXgoMSwgaW50KGZsb2F0KHN0cih0ZXh0KS5zdHJpcCgpKSkp"
    "CiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgQ0ZH"
    "WyJzZXR0aW5ncyJdWyJlbWFpbF9yZWZyZXNoX2ludGVydmFsX21zIl0gPSBtaW51dGVzICogNjAw"
    "MDAKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAog"
    "ICAgICAgICAgICBmIltTRVRUSU5HU10gRW1haWwgcmVmcmVzaCBpbnRlcnZhbCBzZXQgdG8ge21p"
    "bnV0ZXN9IG1pbnV0ZShzKSAoY29uZmlnIGZvdW5kYXRpb24pLiIsCiAgICAgICAgICAgICJJTkZP"
    "IiwKICAgICAgICApCgogICAgZGVmIF9zZXRfdGltZXpvbmVfYXV0b19kZXRlY3Qoc2VsZiwgZW5h"
    "YmxlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBDRkdbInNldHRpbmdzIl1bInRpbWV6b25lX2F1"
    "dG9fZGV0ZWN0Il0gPSBib29sKGVuYWJsZWQpCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgIltTRVRUSU5HU10gVGltZSB6b25l"
    "IG1vZGUgc2V0IHRvIGF1dG8tZGV0ZWN0LiIgaWYgZW5hYmxlZCBlbHNlICJbU0VUVElOR1NdIFRp"
    "bWUgem9uZSBtb2RlIHNldCB0byBtYW51YWwgb3ZlcnJpZGUuIiwKICAgICAgICAgICAgIklORk8i"
    "LAogICAgICAgICkKCiAgICBkZWYgX3NldF90aW1lem9uZV9vdmVycmlkZShzZWxmLCB0el9uYW1l"
    "OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgdHpfdmFsdWUgPSBzdHIodHpfbmFtZSBvciAiIikuc3Ry"
    "aXAoKQogICAgICAgIENGR1sic2V0dGluZ3MiXVsidGltZXpvbmVfb3ZlcnJpZGUiXSA9IHR6X3Zh"
    "bHVlCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIGlmIHR6X3ZhbHVlOgogICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbU0VUVElOR1NdIFRpbWUgem9uZSBvdmVycmlkZSBz"
    "ZXQgdG8ge3R6X3ZhbHVlfS4iLCAiSU5GTyIpCgogICAgZGVmIF9zZXRfc3RhdHVzKHNlbGYsIHN0"
    "YXR1czogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YXR1cyA9IHN0YXR1cwogICAgICAg"
    "IHN0YXR1c19jb2xvcnMgPSB7CiAgICAgICAgICAgICJJRExFIjogICAgICAgQ19HT0xELAogICAg"
    "ICAgICAgICAiR0VORVJBVElORyI6IENfQ1JJTVNPTiwKICAgICAgICAgICAgIkxPQURJTkciOiAg"
    "ICBDX1BVUlBMRSwKICAgICAgICAgICAgIkVSUk9SIjogICAgICBDX0JMT09ELAogICAgICAgICAg"
    "ICAiT0ZGTElORSI6ICAgIENfQkxPT0QsCiAgICAgICAgICAgICJUT1JQT1IiOiAgICAgQ19QVVJQ"
    "TEVfRElNLAogICAgICAgIH0KICAgICAgICBjb2xvciA9IHN0YXR1c19jb2xvcnMuZ2V0KHN0YXR1"
    "cywgQ19URVhUX0RJTSkKCiAgICAgICAgdG9ycG9yX2xhYmVsID0gZiLil4kge1VJX1RPUlBPUl9T"
    "VEFUVVN9IiBpZiBzdGF0dXMgPT0gIlRPUlBPUiIgZWxzZSBmIuKXiSB7c3RhdHVzfSIKICAgICAg"
    "ICBzZWxmLnN0YXR1c19sYWJlbC5zZXRUZXh0KHRvcnBvcl9sYWJlbCkKICAgICAgICBzZWxmLnN0"
    "YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Y29sb3J9OyBm"
    "b250LXNpemU6IDEycHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBib3JkZXI6IG5vbmU7IgogICAgICAg"
    "ICkKCiAgICBkZWYgX2JsaW5rKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYmxpbmtfc3Rh"
    "dGUgPSBub3Qgc2VsZi5fYmxpbmtfc3RhdGUKICAgICAgICBpZiBzZWxmLl9zdGF0dXMgPT0gIkdF"
    "TkVSQVRJTkciOgogICAgICAgICAgICBjaGFyID0gIuKXiSIgaWYgc2VsZi5fYmxpbmtfc3RhdGUg"
    "ZWxzZSAi4peOIgogICAgICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRUZXh0KGYie2NoYXJ9"
    "IEdFTkVSQVRJTkciKQogICAgICAgIGVsaWYgc2VsZi5fc3RhdHVzID09ICJUT1JQT1IiOgogICAg"
    "ICAgICAgICBjaGFyID0gIuKXiSIgaWYgc2VsZi5fYmxpbmtfc3RhdGUgZWxzZSAi4oqYIgogICAg"
    "ICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRUZXh0KAogICAgICAgICAgICAgICAgZiJ7Y2hh"
    "cn0ge1VJX1RPUlBPUl9TVEFUVVN9IgogICAgICAgICAgICApCgogICAgIyDilIDilIAgSURMRSBU"
    "T0dHTEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX29uX2lkbGVfdG9nZ2xlZChzZWxmLCBlbmFibGVkOiBi"
    "b29sKSAtPiBOb25lOgogICAgICAgIENGR1sic2V0dGluZ3MiXVsiaWRsZV9lbmFibGVkIl0gPSBl"
    "bmFibGVkCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0VGV4dCgiSURMRSBPTiIgaWYgZW5hYmxl"
    "ZCBlbHNlICJJRExFIE9GRiIpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7JyMxYTEwMDUnIGlmIGVuYWJsZWQgZWxzZSBDX0JH"
    "M307ICIKICAgICAgICAgICAgZiJjb2xvcjogeycjY2M4ODIyJyBpZiBlbmFibGVkIGVsc2UgQ19U"
    "RVhUX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7JyNjYzg4MjInIGlm"
    "IGVuYWJsZWQgZWxzZSBDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJib3JkZXItcmFkaXVzOiAy"
    "cHg7IGZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmInBh"
    "ZGRpbmc6IDNweCA4cHg7IgogICAgICAgICkKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAg"
    "ICAgaWYgc2VsZi5fc2NoZWR1bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICAgICAgaWYgZW5hYmxlZDoKICAgICAgICAgICAgICAgICAg"
    "ICBzZWxmLl9zY2hlZHVsZXIucmVzdW1lX2pvYigiaWRsZV90cmFuc21pc3Npb24iKQogICAgICAg"
    "ICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0lETEVdIElkbGUgdHJhbnNtaXNzaW9u"
    "IGVuYWJsZWQuIiwgIk9LIikKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAg"
    "ICAgc2VsZi5fc2NoZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFuc21pc3Npb24iKQogICAgICAg"
    "ICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0lETEVdIElkbGUgdHJhbnNtaXNzaW9u"
    "IHBhdXNlZC4iLCAiSU5GTyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltJRExFXSBUb2dnbGUgZXJyb3I6IHtl"
    "fSIsICJFUlJPUiIpCgogICAgIyDilIDilIAgV0lORE9XIENPTlRST0xTIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF90b2dnbGVf"
    "ZnVsbHNjcmVlbihzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIHNlbGYuaXNGdWxsU2NyZWVuKCk6"
    "CiAgICAgICAgICAgIHNlbGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAgIENGR1sic2V0dGluZ3Mi"
    "XVsiZnVsbHNjcmVlbl9lbmFibGVkIl0gPSBGYWxzZQogICAgICAgICAgICBzZWxmLl9mc19idG4u"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29s"
    "b3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xp"
    "ZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZv"
    "bnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwIDhweDsiCiAgICAgICAgICAgICkKICAgICAgICBl"
    "bHNlOgogICAgICAgICAgICBzZWxmLnNob3dGdWxsU2NyZWVuKCkKICAgICAgICAgICAgQ0ZHWyJz"
    "ZXR0aW5ncyJdWyJmdWxsc2NyZWVuX2VuYWJsZWQiXSA9IFRydWUKICAgICAgICAgICAgc2VsZi5f"
    "ZnNfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0NS"
    "SU1TT05fRElNfTsgY29sb3I6IHtDX0NSSU1TT059OyAiCiAgICAgICAgICAgICAgICBmImJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0NSSU1TT059OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAg"
    "ICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMCA4cHg7IgogICAgICAgICAgICApCiAg"
    "ICAgICAgc2F2ZV9jb25maWcoQ0ZHKQoKICAgIGRlZiBfdG9nZ2xlX2JvcmRlcmxlc3Moc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBpc19ibCA9IGJvb2woc2VsZi53aW5kb3dGbGFncygpICYgUXQuV2lu"
    "ZG93VHlwZS5GcmFtZWxlc3NXaW5kb3dIaW50KQogICAgICAgIGlmIGlzX2JsOgogICAgICAgICAg"
    "ICBzZWxmLnNldFdpbmRvd0ZsYWdzKAogICAgICAgICAgICAgICAgc2VsZi53aW5kb3dGbGFncygp"
    "ICYgflF0LldpbmRvd1R5cGUuRnJhbWVsZXNzV2luZG93SGludAogICAgICAgICAgICApCiAgICAg"
    "ICAgICAgIENGR1sic2V0dGluZ3MiXVsiYm9yZGVybGVzc19lbmFibGVkIl0gPSBGYWxzZQogICAg"
    "ICAgICAgICBzZWxmLl9ibF9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFj"
    "a2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAg"
    "ICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAi"
    "CiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwIDhweDsiCiAg"
    "ICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBpZiBzZWxmLmlzRnVsbFNjcmVl"
    "bigpOgogICAgICAgICAgICAgICAgc2VsZi5zaG93Tm9ybWFsKCkKICAgICAgICAgICAgc2VsZi5z"
    "ZXRXaW5kb3dGbGFncygKICAgICAgICAgICAgICAgIHNlbGYud2luZG93RmxhZ3MoKSB8IFF0Lldp"
    "bmRvd1R5cGUuRnJhbWVsZXNzV2luZG93SGludAogICAgICAgICAgICApCiAgICAgICAgICAgIENG"
    "R1sic2V0dGluZ3MiXVsiYm9yZGVybGVzc19lbmFibGVkIl0gPSBUcnVlCiAgICAgICAgICAgIHNl"
    "bGYuX2JsX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7"
    "Q19DUklNU09OX0RJTX07IGNvbG9yOiB7Q19DUklNU09OfTsgIgogICAgICAgICAgICAgICAgZiJi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAg"
    "ICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDAgOHB4OyIKICAgICAgICAgICAg"
    "KQogICAgICAgIHNhdmVfY29uZmlnKENGRykKICAgICAgICBzZWxmLnNob3coKQoKICAgIGRlZiBf"
    "ZXhwb3J0X2NoYXQoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJFeHBvcnQgY3VycmVudCBwZXJz"
    "b25hIGNoYXQgdGFiIGNvbnRlbnQgdG8gYSBUWFQgZmlsZS4iIiIKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIHRleHQgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudG9QbGFpblRleHQoKQogICAgICAgICAg"
    "ICBpZiBub3QgdGV4dC5zdHJpcCgpOgogICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAg"
    "IGV4cG9ydF9kaXIgPSBjZmdfcGF0aCgiZXhwb3J0cyIpCiAgICAgICAgICAgIGV4cG9ydF9kaXIu"
    "bWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICB0cyA9IGRhdGV0"
    "aW1lLm5vdygpLnN0cmZ0aW1lKCIlWSVtJWRfJUglTSVTIikKICAgICAgICAgICAgb3V0X3BhdGgg"
    "PSBleHBvcnRfZGlyIC8gZiJzZWFuY2Vfe3RzfS50eHQiCiAgICAgICAgICAgIG91dF9wYXRoLndy"
    "aXRlX3RleHQodGV4dCwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICAgICAgICAgICMgQWxzbyBjb3B5"
    "IHRvIGNsaXBib2FyZAogICAgICAgICAgICBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCkuc2V0VGV4"
    "dCh0ZXh0KQoKICAgICAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAg"
    "ICAgICAgICBmIlNlc3Npb24gZXhwb3J0ZWQgdG8ge291dF9wYXRoLm5hbWV9IGFuZCBjb3BpZWQg"
    "dG8gY2xpcGJvYXJkLiIpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltFWFBPUlRd"
    "IHtvdXRfcGF0aH0iLCAiT0siKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0VYUE9SVF0gRmFpbGVkOiB7ZX0iLCAiRVJST1Ii"
    "KQoKICAgIGRlZiBrZXlQcmVzc0V2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIGtl"
    "eSA9IGV2ZW50LmtleSgpCiAgICAgICAgaWYga2V5ID09IFF0LktleS5LZXlfRjExOgogICAgICAg"
    "ICAgICBzZWxmLl90b2dnbGVfZnVsbHNjcmVlbigpCiAgICAgICAgZWxpZiBrZXkgPT0gUXQuS2V5"
    "LktleV9GMTA6CiAgICAgICAgICAgIHNlbGYuX3RvZ2dsZV9ib3JkZXJsZXNzKCkKICAgICAgICBl"
    "bGlmIGtleSA9PSBRdC5LZXkuS2V5X0VzY2FwZSBhbmQgc2VsZi5pc0Z1bGxTY3JlZW4oKToKICAg"
    "ICAgICAgICAgc2VsZi5zaG93Tm9ybWFsKCkKICAgICAgICAgICAgc2VsZi5fZnNfYnRuLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7"
    "Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0Nf"
    "Q1JJTVNPTl9ESU19OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdl"
    "aWdodDogYm9sZDsgcGFkZGluZzogMDsiCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAg"
    "ICAgICAgICBzdXBlcigpLmtleVByZXNzRXZlbnQoZXZlbnQpCgogICAgIyDilIDilIAgQ0xPU0Ug"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgY2xvc2VFdmVudChzZWxmLCBldmVu"
    "dCkgLT4gTm9uZToKICAgICAgICAjIFggYnV0dG9uID0gaW1tZWRpYXRlIHNodXRkb3duLCBubyBk"
    "aWFsb2cKICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQoKICAgIGRlZiBfaW5pdGlhdGVf"
    "c2h1dGRvd25fZGlhbG9nKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiR3JhY2VmdWwgc2h1dGRv"
    "d24g4oCUIHNob3cgY29uZmlybSBkaWFsb2cgaW1tZWRpYXRlbHksIG9wdGlvbmFsbHkgZ2V0IGxh"
    "c3Qgd29yZHMuIiIiCiAgICAgICAgIyBJZiBhbHJlYWR5IGluIGEgc2h1dGRvd24gc2VxdWVuY2Us"
    "IGp1c3QgZm9yY2UgcXVpdAogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgJ19zaHV0ZG93bl9pbl9w"
    "cm9ncmVzcycsIEZhbHNlKToKICAgICAgICAgICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKICAg"
    "ICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fc2h1dGRvd25faW5fcHJvZ3Jlc3MgPSBUcnVl"
    "CgogICAgICAgICMgU2hvdyBjb25maXJtIGRpYWxvZyBGSVJTVCDigJQgZG9uJ3Qgd2FpdCBmb3Ig"
    "QUkKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxl"
    "KCJEZWFjdGl2YXRlPyIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "YmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX1RFWFR9OyAiCiAgICAgICAgICAgIGYiZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIGRsZy5zZXRG"
    "aXhlZFNpemUoMzgwLCAxNDApCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoZGxnKQoKICAg"
    "ICAgICBsYmwgPSBRTGFiZWwoCiAgICAgICAgICAgIGYiRGVhY3RpdmF0ZSB7REVDS19OQU1FfT9c"
    "blxuIgogICAgICAgICAgICBmIntERUNLX05BTUV9IG1heSBzcGVhayB0aGVpciBsYXN0IHdvcmRz"
    "IGJlZm9yZSBnb2luZyBzaWxlbnQuIgogICAgICAgICkKICAgICAgICBsYmwuc2V0V29yZFdyYXAo"
    "VHJ1ZSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGxibCkKCiAgICAgICAgYnRuX3JvdyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBidG5fbGFzdCAgPSBRUHVzaEJ1dHRvbigiTGFzdCBXb3JkcyAr"
    "IFNodXRkb3duIikKICAgICAgICBidG5fbm93ICAgPSBRUHVzaEJ1dHRvbigiU2h1dGRvd24gTm93"
    "IikKICAgICAgICBidG5fY2FuY2VsID0gUVB1c2hCdXR0b24oIkNhbmNlbCIpCgogICAgICAgIGZv"
    "ciBiIGluIChidG5fbGFzdCwgYnRuX25vdywgYnRuX2NhbmNlbCk6CiAgICAgICAgICAgIGIuc2V0"
    "TWluaW11bUhlaWdodCgyOCkKICAgICAgICAgICAgYi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAgICAg"
    "ICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgcGFkZGluZzogNHB4IDEycHg7"
    "IgogICAgICAgICAgICApCiAgICAgICAgYnRuX25vdy5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmImJhY2tncm91bmQ6IHtDX0JMT09EfTsgY29sb3I6IHtDX1RFWFR9OyAiCiAgICAgICAgICAg"
    "IGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTn07IHBhZGRpbmc6IDRweCAxMnB4OyIKICAg"
    "ICAgICApCiAgICAgICAgYnRuX2xhc3QuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogZGxnLmRvbmUo"
    "MSkpCiAgICAgICAgYnRuX25vdy5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBkbGcuZG9uZSgyKSkK"
    "ICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IGRsZy5kb25lKDApKQog"
    "ICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgYnRuX3Jvdy5hZGRX"
    "aWRnZXQoYnRuX25vdykKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fbGFzdCkKICAgICAg"
    "ICBsYXlvdXQuYWRkTGF5b3V0KGJ0bl9yb3cpCgogICAgICAgIHJlc3VsdCA9IGRsZy5leGVjKCkK"
    "CiAgICAgICAgaWYgcmVzdWx0ID09IDA6CiAgICAgICAgICAgICMgQ2FuY2VsbGVkCiAgICAgICAg"
    "ICAgIHNlbGYuX3NodXRkb3duX2luX3Byb2dyZXNzID0gRmFsc2UKICAgICAgICAgICAgc2VsZi5f"
    "c2VuZF9idG4uc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5z"
    "ZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGVsaWYgcmVzdWx0ID09"
    "IDI6CiAgICAgICAgICAgICMgU2h1dGRvd24gbm93IOKAlCBubyBsYXN0IHdvcmRzCiAgICAgICAg"
    "ICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCiAgICAgICAgZWxpZiByZXN1bHQgPT0gMToKICAg"
    "ICAgICAgICAgIyBMYXN0IHdvcmRzIHRoZW4gc2h1dGRvd24KICAgICAgICAgICAgc2VsZi5fZ2V0"
    "X2xhc3Rfd29yZHNfdGhlbl9zaHV0ZG93bigpCgogICAgZGVmIF9nZXRfbGFzdF93b3Jkc190aGVu"
    "X3NodXRkb3duKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiU2VuZCBmYXJld2VsbCBwcm9tcHQs"
    "IHNob3cgcmVzcG9uc2UsIHRoZW4gc2h1dGRvd24gYWZ0ZXIgdGltZW91dC4iIiIKICAgICAgICBm"
    "YXJld2VsbF9wcm9tcHQgPSAoCiAgICAgICAgICAgICJZb3UgYXJlIGJlaW5nIGRlYWN0aXZhdGVk"
    "LiBUaGUgZGFya25lc3MgYXBwcm9hY2hlcy4gIgogICAgICAgICAgICAiU3BlYWsgeW91ciBmaW5h"
    "bCB3b3JkcyBiZWZvcmUgdGhlIHZlc3NlbCBnb2VzIHNpbGVudCDigJQgIgogICAgICAgICAgICAi"
    "b25lIHJlc3BvbnNlIG9ubHksIHRoZW4geW91IHJlc3QuIgogICAgICAgICkKICAgICAgICBzZWxm"
    "Ll9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgIuKcpiBTaGUgaXMgZ2l2ZW4gYSBt"
    "b21lbnQgdG8gc3BlYWsgaGVyIGZpbmFsIHdvcmRzLi4uIgogICAgICAgICkKICAgICAgICBzZWxm"
    "Ll9zZW5kX2J0bi5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNl"
    "dEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fZmFyZXdlbGxfdGV4dCA9ICIi"
    "CgogICAgICAgIHRyeToKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9o"
    "aXN0b3J5KCkKICAgICAgICAgICAgaGlzdG9yeS5hcHBlbmQoeyJyb2xlIjogInVzZXIiLCAiY29u"
    "dGVudCI6IGZhcmV3ZWxsX3Byb21wdH0pCiAgICAgICAgICAgIHdvcmtlciA9IFN0cmVhbWluZ1dv"
    "cmtlcigKICAgICAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IsIFNZU1RFTV9QUk9NUFRfQkFTRSwg"
    "aGlzdG9yeSwgbWF4X3Rva2Vucz0yNTYKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9z"
    "aHV0ZG93bl93b3JrZXIgPSB3b3JrZXIKICAgICAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW4gPSBU"
    "cnVlCgogICAgICAgICAgICBkZWYgX29uX2RvbmUocmVzcG9uc2U6IHN0cikgLT4gTm9uZToKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX2ZhcmV3ZWxsX3RleHQgPSByZXNwb25zZQogICAg"
    "ICAgICAgICAgICAgc2VsZi5fb25fcmVzcG9uc2VfZG9uZShyZXNwb25zZSkKICAgICAgICAgICAg"
    "ICAgICMgU21hbGwgZGVsYXkgdG8gbGV0IHRoZSB0ZXh0IHJlbmRlciwgdGhlbiBzaHV0ZG93bgog"
    "ICAgICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMjAwMCwgbGFtYmRhOiBzZWxmLl9kb19z"
    "aHV0ZG93bihOb25lKSkKCiAgICAgICAgICAgIGRlZiBfb25fZXJyb3IoZXJyb3I6IHN0cikgLT4g"
    "Tm9uZToKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltTSFVURE9XTl1bV0FS"
    "Tl0gTGFzdCB3b3JkcyBmYWlsZWQ6IHtlcnJvcn0iLCAiV0FSTiIpCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9kb19zaHV0ZG93bihOb25lKQoKICAgICAgICAgICAgd29ya2VyLnRva2VuX3JlYWR5LmNv"
    "bm5lY3Qoc2VsZi5fb25fdG9rZW4pCiAgICAgICAgICAgIHdvcmtlci5yZXNwb25zZV9kb25lLmNv"
    "bm5lY3QoX29uX2RvbmUpCiAgICAgICAgICAgIHdvcmtlci5lcnJvcl9vY2N1cnJlZC5jb25uZWN0"
    "KF9vbl9lcnJvcikKICAgICAgICAgICAgd29ya2VyLnN0YXR1c19jaGFuZ2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fc2V0X3N0YXR1cykKICAgICAgICAgICAgd29ya2VyLmZpbmlzaGVkLmNvbm5lY3Qod29ya2Vy"
    "LmRlbGV0ZUxhdGVyKQogICAgICAgICAgICB3b3JrZXIuc3RhcnQoKQoKICAgICAgICAgICAgIyBT"
    "YWZldHkgdGltZW91dCDigJQgaWYgQUkgZG9lc24ndCByZXNwb25kIGluIDE1cywgc2h1dCBkb3du"
    "IGFueXdheQogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgxNTAwMCwgbGFtYmRhOiBzZWxm"
    "Ll9kb19zaHV0ZG93bihOb25lKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBnZXRh"
    "dHRyKHNlbGYsICdfc2h1dGRvd25faW5fcHJvZ3Jlc3MnLCBGYWxzZSkgZWxzZSBOb25lKQoKICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygKICAgICAgICAgICAgICAgIGYiW1NIVVRET1dOXVtXQVJOXSBMYXN0IHdvcmRzIHNraXBwZWQg"
    "ZHVlIHRvIGVycm9yOiB7ZX0iLAogICAgICAgICAgICAgICAgIldBUk4iCiAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgIyBJZiBhbnl0aGluZyBmYWlscywganVzdCBzaHV0IGRvd24KICAgICAgICAg"
    "ICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKCiAgICBkZWYgX2RvX3NodXRkb3duKHNlbGYsIGV2"
    "ZW50KSAtPiBOb25lOgogICAgICAgICIiIlBlcmZvcm0gYWN0dWFsIHNodXRkb3duIHNlcXVlbmNl"
    "LiIiIgogICAgICAgICMgU2F2ZSBzZXNzaW9uCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxm"
    "Ll9zZXNzaW9ucy5zYXZlKCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBw"
    "YXNzCgogICAgICAgICMgU3RvcmUgZmFyZXdlbGwgKyBsYXN0IGNvbnRleHQgZm9yIHdha2UtdXAK"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgICMgR2V0IGxhc3QgMyBtZXNzYWdlcyBmcm9tIHNlc3Np"
    "b24gaGlzdG9yeSBmb3Igd2FrZS11cCBjb250ZXh0CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxm"
    "Ll9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCiAgICAgICAgICAgIGxhc3RfY29udGV4dCA9IGhpc3Rv"
    "cnlbLTM6XSBpZiBsZW4oaGlzdG9yeSkgPj0gMyBlbHNlIGhpc3RvcnkKICAgICAgICAgICAgc2Vs"
    "Zi5fc3RhdGVbImxhc3Rfc2h1dGRvd25fY29udGV4dCJdID0gWwogICAgICAgICAgICAgICAgeyJy"
    "b2xlIjogbS5nZXQoInJvbGUiLCIiKSwgImNvbnRlbnQiOiBtLmdldCgiY29udGVudCIsIiIpWzoz"
    "MDBdfQogICAgICAgICAgICAgICAgZm9yIG0gaW4gbGFzdF9jb250ZXh0CiAgICAgICAgICAgIF0K"
    "ICAgICAgICAgICAgIyBFeHRyYWN0IE1vcmdhbm5hJ3MgbW9zdCByZWNlbnQgbWVzc2FnZSBhcyBm"
    "YXJld2VsbAogICAgICAgICAgICAjIFByZWZlciB0aGUgY2FwdHVyZWQgc2h1dGRvd24gZGlhbG9n"
    "IHJlc3BvbnNlIGlmIGF2YWlsYWJsZQogICAgICAgICAgICBmYXJld2VsbCA9IGdldGF0dHIoc2Vs"
    "ZiwgJ19zaHV0ZG93bl9mYXJld2VsbF90ZXh0JywgIiIpCiAgICAgICAgICAgIGlmIG5vdCBmYXJl"
    "d2VsbDoKICAgICAgICAgICAgICAgIGZvciBtIGluIHJldmVyc2VkKGhpc3RvcnkpOgogICAgICAg"
    "ICAgICAgICAgICAgIGlmIG0uZ2V0KCJyb2xlIikgPT0gImFzc2lzdGFudCI6CiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGZhcmV3ZWxsID0gbS5nZXQoImNvbnRlbnQiLCAiIilbOjQwMF0KICAgICAg"
    "ICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgc2VsZi5fc3RhdGVbImxhc3RfZmFy"
    "ZXdlbGwiXSA9IGZhcmV3ZWxsCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAg"
    "cGFzcwoKICAgICAgICAjIFNhdmUgc3RhdGUKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYu"
    "X3N0YXRlWyJsYXN0X3NodXRkb3duIl0gICAgICAgICAgICAgPSBsb2NhbF9ub3dfaXNvKCkKICAg"
    "ICAgICAgICAgc2VsZi5fc3RhdGVbImxhc3RfYWN0aXZlIl0gICAgICAgICAgICAgICA9IGxvY2Fs"
    "X25vd19pc28oKQogICAgICAgICAgICBzZWxmLl9zdGF0ZVsidmFtcGlyZV9zdGF0ZV9hdF9zaHV0"
    "ZG93biJdICA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgICAgICAgICAgc2VsZi5fbWVtb3J5LnNh"
    "dmVfc3RhdGUoc2VsZi5fc3RhdGUpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAg"
    "ICAgcGFzcwoKICAgICAgICAjIFN0b3Agc2NoZWR1bGVyCiAgICAgICAgaWYgaGFzYXR0cihzZWxm"
    "LCAiX3NjaGVkdWxlciIpIGFuZCBzZWxmLl9zY2hlZHVsZXIgYW5kIHNlbGYuX3NjaGVkdWxlci5y"
    "dW5uaW5nOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIu"
    "c2h1dGRvd24od2FpdD1GYWxzZSkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAg"
    "ICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBQbGF5IHNodXRkb3duIHNvdW5kCiAgICAgICAgdHJ5"
    "OgogICAgICAgICAgICBzZWxmLl9zaHV0ZG93bl9zb3VuZCA9IFNvdW5kV29ya2VyKCJzaHV0ZG93"
    "biIpCiAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX3NvdW5kLmZpbmlzaGVkLmNvbm5lY3Qoc2Vs"
    "Zi5fc2h1dGRvd25fc291bmQuZGVsZXRlTGF0ZXIpCiAgICAgICAgICAgIHNlbGYuX3NodXRkb3du"
    "X3NvdW5kLnN0YXJ0KCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNz"
    "CgogICAgICAgIFFBcHBsaWNhdGlvbi5xdWl0KCkKCgojIOKUgOKUgCBFTlRSWSBQT0lOVCDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKZGVmIG1haW4oKSAtPiBOb25lOgogICAgIiIiCiAgICBBcHBsaWNhdGlv"
    "biBlbnRyeSBwb2ludC4KCiAgICBPcmRlciBvZiBvcGVyYXRpb25zOgogICAgMS4gUHJlLWZsaWdo"
    "dCBkZXBlbmRlbmN5IGJvb3RzdHJhcCAoYXV0by1pbnN0YWxsIG1pc3NpbmcgZGVwcykKICAgIDIu"
    "IENoZWNrIGZvciBmaXJzdCBydW4g4oaSIHNob3cgRmlyc3RSdW5EaWFsb2cKICAgICAgIE9uIGZp"
    "cnN0IHJ1bjoKICAgICAgICAgYS4gQ3JlYXRlIEQ6L0FJL01vZGVscy9bRGVja05hbWVdLyAob3Ig"
    "Y2hvc2VuIGJhc2VfZGlyKQogICAgICAgICBiLiBDb3B5IFtkZWNrbmFtZV1fZGVjay5weSBpbnRv"
    "IHRoYXQgZm9sZGVyCiAgICAgICAgIGMuIFdyaXRlIGNvbmZpZy5qc29uIGludG8gdGhhdCBmb2xk"
    "ZXIKICAgICAgICAgZC4gQm9vdHN0cmFwIGFsbCBzdWJkaXJlY3RvcmllcyB1bmRlciB0aGF0IGZv"
    "bGRlcgogICAgICAgICBlLiBDcmVhdGUgZGVza3RvcCBzaG9ydGN1dCBwb2ludGluZyB0byBuZXcg"
    "bG9jYXRpb24KICAgICAgICAgZi4gU2hvdyBjb21wbGV0aW9uIG1lc3NhZ2UgYW5kIEVYSVQg4oCU"
    "IHVzZXIgdXNlcyBzaG9ydGN1dCBmcm9tIG5vdyBvbgogICAgMy4gTm9ybWFsIHJ1biDigJQgbGF1"
    "bmNoIFFBcHBsaWNhdGlvbiBhbmQgRWNob0RlY2sKICAgICIiIgogICAgaW1wb3J0IHNodXRpbCBh"
    "cyBfc2h1dGlsCgogICAgIyDilIDilIAgUGhhc2UgMTogRGVwZW5kZW5jeSBib290c3RyYXAgKHBy"
    "ZS1RQXBwbGljYXRpb24pIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgYm9vdHN0cmFwX2NoZWNrKCkKCiAgICAjIOKUgOKUgCBQaGFzZSAyOiBRQXBwbGljYXRp"
    "b24gKG5lZWRlZCBmb3IgZGlhbG9ncykg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBfZWFybHlfbG9nKCJbTUFJTl0gQ3JlYXRp"
    "bmcgUUFwcGxpY2F0aW9uIikKICAgIGFwcCA9IFFBcHBsaWNhdGlvbihzeXMuYXJndikKICAgIGFw"
    "cC5zZXRBcHBsaWNhdGlvbk5hbWUoQVBQX05BTUUpCgogICAgIyBJbnN0YWxsIFF0IG1lc3NhZ2Ug"
    "aGFuZGxlciBOT1cg4oCUIGNhdGNoZXMgYWxsIFFUaHJlYWQvUXQgd2FybmluZ3MKICAgICMgd2l0"
    "aCBmdWxsIHN0YWNrIHRyYWNlcyBmcm9tIHRoaXMgcG9pbnQgZm9yd2FyZAogICAgX2luc3RhbGxf"
    "cXRfbWVzc2FnZV9oYW5kbGVyKCkKICAgIF9lYXJseV9sb2coIltNQUlOXSBRQXBwbGljYXRpb24g"
    "Y3JlYXRlZCwgbWVzc2FnZSBoYW5kbGVyIGluc3RhbGxlZCIpCgogICAgIyDilIDilIAgUGhhc2Ug"
    "MzogRmlyc3QgcnVuIGNoZWNrIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgaXNfZmlyc3RfcnVuID0gQ0ZHLmdldCgiZmlyc3Rf"
    "cnVuIiwgVHJ1ZSkKCiAgICBpZiBpc19maXJzdF9ydW46CiAgICAgICAgZGxnID0gRmlyc3RSdW5E"
    "aWFsb2coKQogICAgICAgIGlmIGRsZy5leGVjKCkgIT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2Vw"
    "dGVkOgogICAgICAgICAgICBzeXMuZXhpdCgwKQoKICAgICAgICAjIOKUgOKUgCBCdWlsZCBjb25m"
    "aWcgZnJvbSBkaWFsb2cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICAgICAgbmV3X2NmZyA9IGRsZy5idWlsZF9jb25maWcoKQoKICAgICAgICAjIOKU"
    "gOKUgCBEZXRlcm1pbmUgTW9yZ2FubmEncyBob21lIGRpcmVjdG9yeSDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICAgICAjIEFsd2F5cyBjcmVhdGVzIEQ6L0FJL01vZGVscy9Nb3JnYW5uYS8gKG9yIHNpYmxp"
    "bmcgb2Ygc2NyaXB0KQogICAgICAgIHNlZWRfZGlyICAgPSBTQ1JJUFRfRElSICAgICAgICAgICMg"
    "d2hlcmUgdGhlIHNlZWQgLnB5IGxpdmVzCiAgICAgICAgbW9yZ2FubmFfaG9tZSA9IHNlZWRfZGly"
    "IC8gREVDS19OQU1FCiAgICAgICAgbW9yZ2FubmFfaG9tZS5ta2RpcihwYXJlbnRzPVRydWUsIGV4"
    "aXN0X29rPVRydWUpCgogICAgICAgICMg4pSA4pSAIFVwZGF0ZSBhbGwgcGF0aHMgaW4gY29uZmln"
    "IHRvIHBvaW50IGluc2lkZSBtb3JnYW5uYV9ob21lIOKUgOKUgAogICAgICAgIG5ld19jZmdbImJh"
    "c2VfZGlyIl0gPSBzdHIobW9yZ2FubmFfaG9tZSkKICAgICAgICBuZXdfY2ZnWyJwYXRocyJdID0g"
    "ewogICAgICAgICAgICAiZmFjZXMiOiAgICBzdHIobW9yZ2FubmFfaG9tZSAvICJGYWNlcyIpLAog"
    "ICAgICAgICAgICAic291bmRzIjogICBzdHIobW9yZ2FubmFfaG9tZSAvICJzb3VuZHMiKSwKICAg"
    "ICAgICAgICAgIm1lbW9yaWVzIjogc3RyKG1vcmdhbm5hX2hvbWUgLyAibWVtb3JpZXMiKSwKICAg"
    "ICAgICAgICAgInNlc3Npb25zIjogc3RyKG1vcmdhbm5hX2hvbWUgLyAic2Vzc2lvbnMiKSwKICAg"
    "ICAgICAgICAgInNsIjogICAgICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAic2wiKSwKICAgICAgICAg"
    "ICAgImV4cG9ydHMiOiAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiZXhwb3J0cyIpLAogICAgICAgICAg"
    "ICAibG9ncyI6ICAgICBzdHIobW9yZ2FubmFfaG9tZSAvICJsb2dzIiksCiAgICAgICAgICAgICJi"
    "YWNrdXBzIjogIHN0cihtb3JnYW5uYV9ob21lIC8gImJhY2t1cHMiKSwKICAgICAgICAgICAgInBl"
    "cnNvbmFzIjogc3RyKG1vcmdhbm5hX2hvbWUgLyAicGVyc29uYXMiKSwKICAgICAgICAgICAgImdv"
    "b2dsZSI6ICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAiZ29vZ2xlIiksCiAgICAgICAgfQogICAgICAg"
    "IG5ld19jZmdbImdvb2dsZSJdID0gewogICAgICAgICAgICAiY3JlZGVudGlhbHMiOiBzdHIobW9y"
    "Z2FubmFfaG9tZSAvICJnb29nbGUiIC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIiksCiAgICAg"
    "ICAgICAgICJ0b2tlbiI6ICAgICAgIHN0cihtb3JnYW5uYV9ob21lIC8gImdvb2dsZSIgLyAidG9r"
    "ZW4uanNvbiIpLAogICAgICAgICAgICAidGltZXpvbmUiOiAgICAiQW1lcmljYS9DaGljYWdvIiwK"
    "ICAgICAgICAgICAgInNjb3BlcyI6IFsKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29n"
    "bGVhcGlzLmNvbS9hdXRoL2NhbGVuZGFyLmV2ZW50cyIsCiAgICAgICAgICAgICAgICAiaHR0cHM6"
    "Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9kcml2ZSIsCiAgICAgICAgICAgICAgICAiaHR0cHM6"
    "Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9kb2N1bWVudHMiLAogICAgICAgICAgICBdLAogICAg"
    "ICAgIH0KICAgICAgICBuZXdfY2ZnWyJmaXJzdF9ydW4iXSA9IEZhbHNlCgogICAgICAgICMg4pSA"
    "4pSAIENvcHkgZGVjayBmaWxlIGludG8gbW9yZ2FubmFfaG9tZSDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICBzcmNfZGVjayA9IFBhdGgoX19maWxlX18pLnJlc29sdmUoKQogICAgICAgIGRz"
    "dF9kZWNrID0gbW9yZ2FubmFfaG9tZSAvIGYie0RFQ0tfTkFNRS5sb3dlcigpfV9kZWNrLnB5Igog"
    "ICAgICAgIGlmIHNyY19kZWNrICE9IGRzdF9kZWNrOgogICAgICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgICAgICBfc2h1dGlsLmNvcHkyKHN0cihzcmNfZGVjayksIHN0cihkc3RfZGVjaykpCiAgICAg"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIFFNZXNzYWdlQm94"
    "Lndhcm5pbmcoCiAgICAgICAgICAgICAgICAgICAgTm9uZSwgIkNvcHkgV2FybmluZyIsCiAgICAg"
    "ICAgICAgICAgICAgICAgZiJDb3VsZCBub3QgY29weSBkZWNrIGZpbGUgdG8ge0RFQ0tfTkFNRX0g"
    "Zm9sZGVyOlxue2V9XG5cbiIKICAgICAgICAgICAgICAgICAgICBmIllvdSBtYXkgbmVlZCB0byBj"
    "b3B5IGl0IG1hbnVhbGx5LiIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgIyDilIDilIAgV3Jp"
    "dGUgY29uZmlnLmpzb24gaW50byBtb3JnYW5uYV9ob21lIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGNm"
    "Z19kc3QgPSBtb3JnYW5uYV9ob21lIC8gImNvbmZpZy5qc29uIgogICAgICAgIGNmZ19kc3QucGFy"
    "ZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICB3aXRoIGNmZ19k"
    "c3Qub3BlbigidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgIGpzb24uZHVt"
    "cChuZXdfY2ZnLCBmLCBpbmRlbnQ9MikKCiAgICAgICAgIyDilIDilIAgQm9vdHN0cmFwIGFsbCBz"
    "dWJkaXJlY3RvcmllcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICAjIFRlbXBvcmFyaWx5IHVwZGF0ZSBnbG9iYWwgQ0ZHIHNvIGJvb3RzdHJhcCBmdW5jdGlvbnMg"
    "dXNlIG5ldyBwYXRocwogICAgICAgIENGRy51cGRhdGUobmV3X2NmZykKICAgICAgICBib290c3Ry"
    "YXBfZGlyZWN0b3JpZXMoKQogICAgICAgIGJvb3RzdHJhcF9zb3VuZHMoKQogICAgICAgIHdyaXRl"
    "X3JlcXVpcmVtZW50c190eHQoKQoKICAgICAgICAjIOKUgOKUgCBVbnBhY2sgZmFjZSBaSVAgaWYg"
    "cHJvdmlkZWQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAg"
    "ZmFjZV96aXAgPSBkbGcuZmFjZV96aXBfcGF0aAogICAgICAgIGlmIGZhY2VfemlwIGFuZCBQYXRo"
    "KGZhY2VfemlwKS5leGlzdHMoKToKICAgICAgICAgICAgaW1wb3J0IHppcGZpbGUgYXMgX3ppcGZp"
    "bGUKICAgICAgICAgICAgZmFjZXNfZGlyID0gbW9yZ2FubmFfaG9tZSAvICJGYWNlcyIKICAgICAg"
    "ICAgICAgZmFjZXNfZGlyLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICAgICAgd2l0aCBfemlwZmlsZS5aaXBGaWxlKGZhY2Vfemlw"
    "LCAiciIpIGFzIHpmOgogICAgICAgICAgICAgICAgICAgIGV4dHJhY3RlZCA9IDAKICAgICAgICAg"
    "ICAgICAgICAgICBmb3IgbWVtYmVyIGluIHpmLm5hbWVsaXN0KCk6CiAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGlmIG1lbWJlci5sb3dlcigpLmVuZHN3aXRoKCIucG5nIik6CiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBmaWxlbmFtZSA9IFBhdGgobWVtYmVyKS5uYW1lCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICB0YXJnZXQgPSBmYWNlc19kaXIgLyBmaWxlbmFtZQogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgd2l0aCB6Zi5vcGVuKG1lbWJlcikgYXMgc3JjLCB0YXJnZXQub3Blbigi"
    "d2IiKSBhcyBkc3Q6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZHN0LndyaXRlKHNy"
    "Yy5yZWFkKCkpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBleHRyYWN0ZWQgKz0gMQogICAg"
    "ICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIltGQUNFU10gRXh0cmFjdGVkIHtleHRyYWN0ZWR9IGZh"
    "Y2UgaW1hZ2VzIHRvIHtmYWNlc19kaXJ9IikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBh"
    "cyBlOgogICAgICAgICAgICAgICAgX2Vhcmx5X2xvZyhmIltGQUNFU10gWklQIGV4dHJhY3Rpb24g"
    "ZmFpbGVkOiB7ZX0iKQogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2FybmluZygKICAgICAg"
    "ICAgICAgICAgICAgICBOb25lLCAiRmFjZSBQYWNrIFdhcm5pbmciLAogICAgICAgICAgICAgICAg"
    "ICAgIGYiQ291bGQgbm90IGV4dHJhY3QgZmFjZSBwYWNrOlxue2V9XG5cbiIKICAgICAgICAgICAg"
    "ICAgICAgICBmIllvdSBjYW4gYWRkIGZhY2VzIG1hbnVhbGx5IHRvOlxue2ZhY2VzX2Rpcn0iCiAg"
    "ICAgICAgICAgICAgICApCgogICAgICAgICMg4pSA4pSAIENyZWF0ZSBkZXNrdG9wIHNob3J0Y3V0"
    "IHBvaW50aW5nIHRvIG5ldyBkZWNrIGxvY2F0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAg"
    "IHNob3J0Y3V0X2NyZWF0ZWQgPSBGYWxzZQogICAgICAgIGlmIGRsZy5jcmVhdGVfc2hvcnRjdXQ6"
    "CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlmIFdJTjMyX09LOgogICAgICAgICAg"
    "ICAgICAgICAgIGltcG9ydCB3aW4zMmNvbS5jbGllbnQgYXMgX3dpbjMyCiAgICAgICAgICAgICAg"
    "ICAgICAgZGVza3RvcCAgICAgPSBQYXRoLmhvbWUoKSAvICJEZXNrdG9wIgogICAgICAgICAgICAg"
    "ICAgICAgIHNjX3BhdGggICAgID0gZGVza3RvcCAvIGYie0RFQ0tfTkFNRX0ubG5rIgogICAgICAg"
    "ICAgICAgICAgICAgIHB5dGhvbncgICAgID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKICAgICAgICAg"
    "ICAgICAgICAgICBpZiBweXRob253Lm5hbWUubG93ZXIoKSA9PSAicHl0aG9uLmV4ZSI6CiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIHB5dGhvbncgPSBweXRob253LnBhcmVudCAvICJweXRob253LmV4"
    "ZSIKICAgICAgICAgICAgICAgICAgICBpZiBub3QgcHl0aG9udy5leGlzdHMoKToKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgcHl0aG9udyA9IFBhdGgoc3lzLmV4ZWN1dGFibGUpCiAgICAgICAgICAg"
    "ICAgICAgICAgc2hlbGwgPSBfd2luMzIuRGlzcGF0Y2goIldTY3JpcHQuU2hlbGwiKQogICAgICAg"
    "ICAgICAgICAgICAgIHNjICAgID0gc2hlbGwuQ3JlYXRlU2hvcnRDdXQoc3RyKHNjX3BhdGgpKQog"
    "ICAgICAgICAgICAgICAgICAgIHNjLlRhcmdldFBhdGggICAgICA9IHN0cihweXRob253KQogICAg"
    "ICAgICAgICAgICAgICAgIHNjLkFyZ3VtZW50cyAgICAgICA9IGYnIntkc3RfZGVja30iJwogICAg"
    "ICAgICAgICAgICAgICAgIHNjLldvcmtpbmdEaXJlY3Rvcnk9IHN0cihtb3JnYW5uYV9ob21lKQog"
    "ICAgICAgICAgICAgICAgICAgIHNjLkRlc2NyaXB0aW9uICAgICA9IGYie0RFQ0tfTkFNRX0g4oCU"
    "IEVjaG8gRGVjayIKICAgICAgICAgICAgICAgICAgICBzYy5zYXZlKCkKICAgICAgICAgICAgICAg"
    "ICAgICBzaG9ydGN1dF9jcmVhdGVkID0gVHJ1ZQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "IGFzIGU6CiAgICAgICAgICAgICAgICBwcmludChmIltTSE9SVENVVF0gQ291bGQgbm90IGNyZWF0"
    "ZSBzaG9ydGN1dDoge2V9IikKCiAgICAgICAgIyDilIDilIAgQ29tcGxldGlvbiBtZXNzYWdlIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgICAgIHNob3J0Y3V0X25vdGUgPSAoCiAgICAgICAgICAgICJBIGRlc2t0b3Ag"
    "c2hvcnRjdXQgaGFzIGJlZW4gY3JlYXRlZC5cbiIKICAgICAgICAgICAgZiJVc2UgaXQgdG8gc3Vt"
    "bW9uIHtERUNLX05BTUV9IGZyb20gbm93IG9uLiIKICAgICAgICAgICAgaWYgc2hvcnRjdXRfY3Jl"
    "YXRlZCBlbHNlCiAgICAgICAgICAgICJObyBzaG9ydGN1dCB3YXMgY3JlYXRlZC5cbiIKICAgICAg"
    "ICAgICAgZiJSdW4ge0RFQ0tfTkFNRX0gYnkgZG91YmxlLWNsaWNraW5nOlxue2RzdF9kZWNrfSIK"
    "ICAgICAgICApCgogICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKAogICAgICAgICAgICBO"
    "b25lLAogICAgICAgICAgICBmIuKcpiB7REVDS19OQU1FfSdzIFNhbmN0dW0gUHJlcGFyZWQiLAog"
    "ICAgICAgICAgICBmIntERUNLX05BTUV9J3Mgc2FuY3R1bSBoYXMgYmVlbiBwcmVwYXJlZCBhdDpc"
    "blxuIgogICAgICAgICAgICBmInttb3JnYW5uYV9ob21lfVxuXG4iCiAgICAgICAgICAgIGYie3No"
    "b3J0Y3V0X25vdGV9XG5cbiIKICAgICAgICAgICAgZiJUaGlzIHNldHVwIHdpbmRvdyB3aWxsIG5v"
    "dyBjbG9zZS5cbiIKICAgICAgICAgICAgZiJVc2UgdGhlIHNob3J0Y3V0IG9yIHRoZSBkZWNrIGZp"
    "bGUgdG8gbGF1bmNoIHtERUNLX05BTUV9LiIKICAgICAgICApCgogICAgICAgICMg4pSA4pSAIEV4"
    "aXQgc2VlZCDigJQgdXNlciBsYXVuY2hlcyBmcm9tIHNob3J0Y3V0L25ldyBsb2NhdGlvbiDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICBzeXMuZXhpdCgwKQoKICAgICMg4pSA4pSAIFBoYXNl"
    "IDQ6IE5vcm1hbCBsYXVuY2gg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAjIE9ubHkgcmVhY2hlcyBoZXJlIG9uIHN1"
    "YnNlcXVlbnQgcnVucyBmcm9tIG1vcmdhbm5hX2hvbWUKICAgIGJvb3RzdHJhcF9zb3VuZHMoKQoK"
    "ICAgIF9lYXJseV9sb2coZiJbTUFJTl0gQ3JlYXRpbmcge0RFQ0tfTkFNRX0gZGVjayB3aW5kb3ci"
    "KQogICAgd2luZG93ID0gRWNob0RlY2soKQogICAgX2Vhcmx5X2xvZyhmIltNQUlOXSB7REVDS19O"
    "QU1FfSBkZWNrIGNyZWF0ZWQg4oCUIGNhbGxpbmcgc2hvdygpIikKICAgIHdpbmRvdy5zaG93KCkK"
    "ICAgIF9lYXJseV9sb2coIltNQUlOXSB3aW5kb3cuc2hvdygpIGNhbGxlZCDigJQgZXZlbnQgbG9v"
    "cCBzdGFydGluZyIpCgogICAgIyBEZWZlciBzY2hlZHVsZXIgYW5kIHN0YXJ0dXAgc2VxdWVuY2Ug"
    "dW50aWwgZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgIyBOb3RoaW5nIHRoYXQgc3RhcnRzIHRo"
    "cmVhZHMgb3IgZW1pdHMgc2lnbmFscyBzaG91bGQgcnVuIGJlZm9yZSB0aGlzLgogICAgUVRpbWVy"
    "LnNpbmdsZVNob3QoMjAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIF9zZXR1cF9zY2hl"
    "ZHVsZXIgZmlyaW5nIiksIHdpbmRvdy5fc2V0dXBfc2NoZWR1bGVyKCkpKQogICAgUVRpbWVyLnNp"
    "bmdsZVNob3QoNDAwLCBsYW1iZGE6IChfZWFybHlfbG9nKCJbVElNRVJdIHN0YXJ0X3NjaGVkdWxl"
    "ciBmaXJpbmciKSwgd2luZG93LnN0YXJ0X3NjaGVkdWxlcigpKSkKICAgIFFUaW1lci5zaW5nbGVT"
    "aG90KDYwMCwgbGFtYmRhOiAoX2Vhcmx5X2xvZygiW1RJTUVSXSBfc3RhcnR1cF9zZXF1ZW5jZSBm"
    "aXJpbmciKSwgd2luZG93Ll9zdGFydHVwX3NlcXVlbmNlKCkpKQogICAgUVRpbWVyLnNpbmdsZVNo"
    "b3QoMTAwMCwgbGFtYmRhOiAoX2Vhcmx5X2xvZygiW1RJTUVSXSBfc3RhcnR1cF9nb29nbGVfYXV0"
    "aCBmaXJpbmciKSwgd2luZG93Ll9zdGFydHVwX2dvb2dsZV9hdXRoKCkpKQoKICAgICMgUGxheSBz"
    "dGFydHVwIHNvdW5kIOKAlCBrZWVwIHJlZmVyZW5jZSB0byBwcmV2ZW50IEdDIHdoaWxlIHRocmVh"
    "ZCBydW5zCiAgICBkZWYgX3BsYXlfc3RhcnR1cCgpOgogICAgICAgIHdpbmRvdy5fc3RhcnR1cF9z"
    "b3VuZCA9IFNvdW5kV29ya2VyKCJzdGFydHVwIikKICAgICAgICB3aW5kb3cuX3N0YXJ0dXBfc291"
    "bmQuZmluaXNoZWQuY29ubmVjdCh3aW5kb3cuX3N0YXJ0dXBfc291bmQuZGVsZXRlTGF0ZXIpCiAg"
    "ICAgICAgd2luZG93Ll9zdGFydHVwX3NvdW5kLnN0YXJ0KCkKICAgIFFUaW1lci5zaW5nbGVTaG90"
    "KDEyMDAsIF9wbGF5X3N0YXJ0dXApCgogICAgc3lzLmV4aXQoYXBwLmV4ZWMoKSkKCgppZiBfX25h"
    "bWVfXyA9PSAiX19tYWluX18iOgogICAgbWFpbigpCgoKIyDilIDilIAgUEFTUyA2IENPTVBMRVRF"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAojIEZ1bGwgZGVjayBhc3NlbWJsZWQuIEFsbCBwYXNzZXMgY29tcGxldGUuCiMg"
    "Q29tYmluZSBhbGwgcGFzc2VzIGludG8gbW9yZ2FubmFfZGVjay5weSBpbiBvcmRlcjoKIyAgIFBh"
    "c3MgMSDihpIgUGFzcyAyIOKGkiBQYXNzIDMg4oaSIFBhc3MgNCDihpIgUGFzcyA1IOKGkiBQYXNz"
    "IDYK"
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
