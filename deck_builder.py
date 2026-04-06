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
    "UVRvb2xCdXR0b24sIFFTcGluQm94LCBRR3JhcGhpY3NPcGFjaXR5RWZmZWN0LAogICAgUU1lbnUs"
    "IFFUYWJCYXIKKQpmcm9tIFB5U2lkZTYuUXRDb3JlIGltcG9ydCAoCiAgICBRdCwgUVRpbWVyLCBR"
    "VGhyZWFkLCBTaWduYWwsIFFEYXRlLCBRU2l6ZSwgUVBvaW50LCBRUmVjdCwKICAgIFFQcm9wZXJ0"
    "eUFuaW1hdGlvbiwgUUVhc2luZ0N1cnZlCikKZnJvbSBQeVNpZGU2LlF0R3VpIGltcG9ydCAoCiAg"
    "ICBRRm9udCwgUUNvbG9yLCBRUGFpbnRlciwgUUxpbmVhckdyYWRpZW50LCBRUmFkaWFsR3JhZGll"
    "bnQsCiAgICBRUGl4bWFwLCBRUGVuLCBRUGFpbnRlclBhdGgsIFFUZXh0Q2hhckZvcm1hdCwgUUlj"
    "b24sCiAgICBRVGV4dEN1cnNvciwgUUFjdGlvbgopCgojIOKUgOKUgCBBUFAgSURFTlRJVFkg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACkFQUF9OQU1FICAgICAgPSBVSV9XSU5ET1dfVElUTEUKQVBQX1ZFUlNJT04g"
    "ICA9ICIyLjAuMCIKQVBQX0ZJTEVOQU1FICA9IGYie0RFQ0tfTkFNRS5sb3dlcigpfV9kZWNrLnB5"
    "IgpCVUlMRF9EQVRFICAgID0gIjIwMjYtMDQtMDQiCgojIOKUgOKUgCBDT05GSUcgTE9BRElORyDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKIyBjb25maWcuanNvbiBsaXZlcyBuZXh0IHRvIHRoZSBkZWNrIC5weSBmaWxl"
    "LgojIEFsbCBwYXRocyBjb21lIGZyb20gY29uZmlnLiBOb3RoaW5nIGhhcmRjb2RlZCBiZWxvdyB0"
    "aGlzIHBvaW50LgoKU0NSSVBUX0RJUiA9IFBhdGgoX19maWxlX18pLnJlc29sdmUoKS5wYXJlbnQK"
    "Q09ORklHX1BBVEggPSBTQ1JJUFRfRElSIC8gImNvbmZpZy5qc29uIgoKIyBJbml0aWFsaXplIGVh"
    "cmx5IGxvZyBub3cgdGhhdCB3ZSBrbm93IHdoZXJlIHdlIGFyZQpfaW5pdF9lYXJseV9sb2coU0NS"
    "SVBUX0RJUikKX2Vhcmx5X2xvZyhmIltJTklUXSBTQ1JJUFRfRElSID0ge1NDUklQVF9ESVJ9IikK"
    "X2Vhcmx5X2xvZyhmIltJTklUXSBDT05GSUdfUEFUSCA9IHtDT05GSUdfUEFUSH0iKQpfZWFybHlf"
    "bG9nKGYiW0lOSVRdIGNvbmZpZy5qc29uIGV4aXN0czoge0NPTkZJR19QQVRILmV4aXN0cygpfSIp"
    "CgpkZWYgX2RlZmF1bHRfY29uZmlnKCkgLT4gZGljdDoKICAgICIiIlJldHVybnMgdGhlIGRlZmF1"
    "bHQgY29uZmlnIHN0cnVjdHVyZSBmb3IgZmlyc3QtcnVuIGdlbmVyYXRpb24uIiIiCiAgICBiYXNl"
    "ID0gc3RyKFNDUklQVF9ESVIpCiAgICByZXR1cm4gewogICAgICAgICJkZWNrX25hbWUiOiBERUNL"
    "X05BTUUsCiAgICAgICAgImRlY2tfdmVyc2lvbiI6IEFQUF9WRVJTSU9OLAogICAgICAgICJiYXNl"
    "X2RpciI6IGJhc2UsCiAgICAgICAgIm1vZGVsIjogewogICAgICAgICAgICAidHlwZSI6ICJsb2Nh"
    "bCIsICAgICAgICAgICMgbG9jYWwgfCBvbGxhbWEgfCBjbGF1ZGUgfCBvcGVuYWkKICAgICAgICAg"
    "ICAgInBhdGgiOiAiIiwgICAgICAgICAgICAgICAjIGxvY2FsIG1vZGVsIGZvbGRlciBwYXRoCiAg"
    "ICAgICAgICAgICJvbGxhbWFfbW9kZWwiOiAiIiwgICAgICAgIyBlLmcuICJkb2xwaGluLTIuNi03"
    "YiIKICAgICAgICAgICAgImFwaV9rZXkiOiAiIiwgICAgICAgICAgICAjIENsYXVkZSBvciBPcGVu"
    "QUkga2V5CiAgICAgICAgICAgICJhcGlfdHlwZSI6ICIiLCAgICAgICAgICAgIyAiY2xhdWRlIiB8"
    "ICJvcGVuYWkiCiAgICAgICAgICAgICJhcGlfbW9kZWwiOiAiIiwgICAgICAgICAgIyBlLmcuICJj"
    "bGF1ZGUtc29ubmV0LTQtNiIKICAgICAgICB9LAogICAgICAgICJnb29nbGUiOiB7CiAgICAgICAg"
    "ICAgICJjcmVkZW50aWFscyI6IHN0cihTQ1JJUFRfRElSIC8gImdvb2dsZSIgLyAiZ29vZ2xlX2Ny"
    "ZWRlbnRpYWxzLmpzb24iKSwKICAgICAgICAgICAgInRva2VuIjogICAgICAgc3RyKFNDUklQVF9E"
    "SVIgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29uIiksCiAgICAgICAgICAgICJ0aW1lem9uZSI6ICAg"
    "ICJBbWVyaWNhL0NoaWNhZ28iLAogICAgICAgICAgICAic2NvcGVzIjogWwogICAgICAgICAgICAg"
    "ICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5kYXIuZXZlbnRzIiwKICAg"
    "ICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RyaXZlIiwKICAg"
    "ICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9hdXRoL2RvY3VtZW50cyIs"
    "CiAgICAgICAgICAgIF0sCiAgICAgICAgfSwKICAgICAgICAicGF0aHMiOiB7CiAgICAgICAgICAg"
    "ICJmYWNlcyI6ICAgIHN0cihTQ1JJUFRfRElSIC8gIkZhY2VzIiksCiAgICAgICAgICAgICJzb3Vu"
    "ZHMiOiAgIHN0cihTQ1JJUFRfRElSIC8gInNvdW5kcyIpLAogICAgICAgICAgICAibWVtb3JpZXMi"
    "OiBzdHIoU0NSSVBUX0RJUiAvICJtZW1vcmllcyIpLAogICAgICAgICAgICAic2Vzc2lvbnMiOiBz"
    "dHIoU0NSSVBUX0RJUiAvICJzZXNzaW9ucyIpLAogICAgICAgICAgICAic2wiOiAgICAgICBzdHIo"
    "U0NSSVBUX0RJUiAvICJzbCIpLAogICAgICAgICAgICAiZXhwb3J0cyI6ICBzdHIoU0NSSVBUX0RJ"
    "UiAvICJleHBvcnRzIiksCiAgICAgICAgICAgICJsb2dzIjogICAgIHN0cihTQ1JJUFRfRElSIC8g"
    "ImxvZ3MiKSwKICAgICAgICAgICAgImJhY2t1cHMiOiAgc3RyKFNDUklQVF9ESVIgLyAiYmFja3Vw"
    "cyIpLAogICAgICAgICAgICAicGVyc29uYXMiOiBzdHIoU0NSSVBUX0RJUiAvICJwZXJzb25hcyIp"
    "LAogICAgICAgICAgICAiZ29vZ2xlIjogICBzdHIoU0NSSVBUX0RJUiAvICJnb29nbGUiKSwKICAg"
    "ICAgICB9LAogICAgICAgICJzZXR0aW5ncyI6IHsKICAgICAgICAgICAgImlkbGVfZW5hYmxlZCI6"
    "ICAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgICAgImlkbGVfbWluX21pbnV0ZXMiOiAgICAg"
    "ICAgICAxMCwKICAgICAgICAgICAgImlkbGVfbWF4X21pbnV0ZXMiOiAgICAgICAgICAzMCwKICAg"
    "ICAgICAgICAgImF1dG9zYXZlX2ludGVydmFsX21pbnV0ZXMiOiAxMCwKICAgICAgICAgICAgIm1h"
    "eF9iYWNrdXBzIjogICAgICAgICAgICAgICAxMCwKICAgICAgICAgICAgImdvb2dsZV9zeW5jX2Vu"
    "YWJsZWQiOiAgICAgICBUcnVlLAogICAgICAgICAgICAic291bmRfZW5hYmxlZCI6ICAgICAgICAg"
    "ICAgIFRydWUsCiAgICAgICAgICAgICJnb29nbGVfaW5ib3VuZF9pbnRlcnZhbF9tcyI6IDMwMDAw"
    "LAogICAgICAgICAgICAiZW1haWxfcmVmcmVzaF9pbnRlcnZhbF9tcyI6IDMwMDAwMCwKICAgICAg"
    "ICAgICAgImdvb2dsZV9sb29rYmFja19kYXlzIjogICAgICAzMCwKICAgICAgICAgICAgInVzZXJf"
    "ZGVsYXlfdGhyZXNob2xkX21pbiI6ICAzMCwKICAgICAgICAgICAgInRpbWV6b25lX2F1dG9fZGV0"
    "ZWN0IjogICAgICBUcnVlLAogICAgICAgICAgICAidGltZXpvbmVfb3ZlcnJpZGUiOiAgICAgICAg"
    "ICIiLAogICAgICAgICAgICAiZnVsbHNjcmVlbl9lbmFibGVkIjogICAgICAgIEZhbHNlLAogICAg"
    "ICAgICAgICAiYm9yZGVybGVzc19lbmFibGVkIjogICAgICAgIEZhbHNlLAogICAgICAgIH0sCiAg"
    "ICAgICAgIm1vZHVsZV90YWJfb3JkZXIiOiBbXSwKICAgICAgICAiZmlyc3RfcnVuIjogVHJ1ZSwK"
    "ICAgIH0KCmRlZiBsb2FkX2NvbmZpZygpIC0+IGRpY3Q6CiAgICAiIiJMb2FkIGNvbmZpZy5qc29u"
    "LiBSZXR1cm5zIGRlZmF1bHQgaWYgbWlzc2luZyBvciBjb3JydXB0LiIiIgogICAgaWYgbm90IENP"
    "TkZJR19QQVRILmV4aXN0cygpOgogICAgICAgIHJldHVybiBfZGVmYXVsdF9jb25maWcoKQogICAg"
    "dHJ5OgogICAgICAgIHdpdGggQ09ORklHX1BBVEgub3BlbigiciIsIGVuY29kaW5nPSJ1dGYtOCIp"
    "IGFzIGY6CiAgICAgICAgICAgIHJldHVybiBqc29uLmxvYWQoZikKICAgIGV4Y2VwdCBFeGNlcHRp"
    "b246CiAgICAgICAgcmV0dXJuIF9kZWZhdWx0X2NvbmZpZygpCgpkZWYgc2F2ZV9jb25maWcoY2Zn"
    "OiBkaWN0KSAtPiBOb25lOgogICAgIiIiV3JpdGUgY29uZmlnLmpzb24uIiIiCiAgICBDT05GSUdf"
    "UEFUSC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgd2l0aCBD"
    "T05GSUdfUEFUSC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICBqc29u"
    "LmR1bXAoY2ZnLCBmLCBpbmRlbnQ9MikKCiMgTG9hZCBjb25maWcgYXQgbW9kdWxlIGxldmVsIOKA"
    "lCBldmVyeXRoaW5nIGJlbG93IHJlYWRzIGZyb20gQ0ZHCkNGRyA9IGxvYWRfY29uZmlnKCkKX2Vh"
    "cmx5X2xvZyhmIltJTklUXSBDb25maWcgbG9hZGVkIOKAlCBmaXJzdF9ydW49e0NGRy5nZXQoJ2Zp"
    "cnN0X3J1bicpfSwgbW9kZWxfdHlwZT17Q0ZHLmdldCgnbW9kZWwnLHt9KS5nZXQoJ3R5cGUnKX0i"
    "KQoKX0RFRkFVTFRfUEFUSFM6IGRpY3Rbc3RyLCBQYXRoXSA9IHsKICAgICJmYWNlcyI6ICAgIFND"
    "UklQVF9ESVIgLyAiRmFjZXMiLAogICAgInNvdW5kcyI6ICAgU0NSSVBUX0RJUiAvICJzb3VuZHMi"
    "LAogICAgIm1lbW9yaWVzIjogU0NSSVBUX0RJUiAvICJtZW1vcmllcyIsCiAgICAic2Vzc2lvbnMi"
    "OiBTQ1JJUFRfRElSIC8gInNlc3Npb25zIiwKICAgICJzbCI6ICAgICAgIFNDUklQVF9ESVIgLyAi"
    "c2wiLAogICAgImV4cG9ydHMiOiAgU0NSSVBUX0RJUiAvICJleHBvcnRzIiwKICAgICJsb2dzIjog"
    "ICAgIFNDUklQVF9ESVIgLyAibG9ncyIsCiAgICAiYmFja3VwcyI6ICBTQ1JJUFRfRElSIC8gImJh"
    "Y2t1cHMiLAogICAgInBlcnNvbmFzIjogU0NSSVBUX0RJUiAvICJwZXJzb25hcyIsCiAgICAiZ29v"
    "Z2xlIjogICBTQ1JJUFRfRElSIC8gImdvb2dsZSIsCn0KCmRlZiBfbm9ybWFsaXplX2NvbmZpZ19w"
    "YXRocygpIC0+IE5vbmU6CiAgICAiIiIKICAgIFNlbGYtaGVhbCBvbGRlciBjb25maWcuanNvbiBm"
    "aWxlcyBtaXNzaW5nIHJlcXVpcmVkIHBhdGgga2V5cy4KICAgIEFkZHMgbWlzc2luZyBwYXRoIGtl"
    "eXMgYW5kIG5vcm1hbGl6ZXMgZ29vZ2xlIGNyZWRlbnRpYWwvdG9rZW4gbG9jYXRpb25zLAogICAg"
    "dGhlbiBwZXJzaXN0cyBjb25maWcuanNvbiBpZiBhbnl0aGluZyBjaGFuZ2VkLgogICAgIiIiCiAg"
    "ICBjaGFuZ2VkID0gRmFsc2UKICAgIHBhdGhzID0gQ0ZHLnNldGRlZmF1bHQoInBhdGhzIiwge30p"
    "CiAgICBmb3Iga2V5LCBkZWZhdWx0X3BhdGggaW4gX0RFRkFVTFRfUEFUSFMuaXRlbXMoKToKICAg"
    "ICAgICBpZiBub3QgcGF0aHMuZ2V0KGtleSk6CiAgICAgICAgICAgIHBhdGhzW2tleV0gPSBzdHIo"
    "ZGVmYXVsdF9wYXRoKQogICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgIGdvb2dsZV9jZmcg"
    "PSBDRkcuc2V0ZGVmYXVsdCgiZ29vZ2xlIiwge30pCiAgICBnb29nbGVfcm9vdCA9IFBhdGgocGF0"
    "aHMuZ2V0KCJnb29nbGUiLCBzdHIoX0RFRkFVTFRfUEFUSFNbImdvb2dsZSJdKSkpCiAgICBkZWZh"
    "dWx0X2NyZWRzID0gc3RyKGdvb2dsZV9yb290IC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIikK"
    "ICAgIGRlZmF1bHRfdG9rZW4gPSBzdHIoZ29vZ2xlX3Jvb3QgLyAidG9rZW4uanNvbiIpCiAgICBj"
    "cmVkc192YWwgPSBzdHIoZ29vZ2xlX2NmZy5nZXQoImNyZWRlbnRpYWxzIiwgIiIpKS5zdHJpcCgp"
    "CiAgICB0b2tlbl92YWwgPSBzdHIoZ29vZ2xlX2NmZy5nZXQoInRva2VuIiwgIiIpKS5zdHJpcCgp"
    "CiAgICBpZiAobm90IGNyZWRzX3ZhbCkgb3IgKCJjb25maWciIGluIGNyZWRzX3ZhbCBhbmQgImdv"
    "b2dsZV9jcmVkZW50aWFscy5qc29uIiBpbiBjcmVkc192YWwpOgogICAgICAgIGdvb2dsZV9jZmdb"
    "ImNyZWRlbnRpYWxzIl0gPSBkZWZhdWx0X2NyZWRzCiAgICAgICAgY2hhbmdlZCA9IFRydWUKICAg"
    "IGlmIG5vdCB0b2tlbl92YWw6CiAgICAgICAgZ29vZ2xlX2NmZ1sidG9rZW4iXSA9IGRlZmF1bHRf"
    "dG9rZW4KICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgc2F2"
    "ZV9jb25maWcoQ0ZHKQoKZGVmIGNmZ19wYXRoKGtleTogc3RyKSAtPiBQYXRoOgogICAgIiIiQ29u"
    "dmVuaWVuY2U6IGdldCBhIHBhdGggZnJvbSBDRkdbJ3BhdGhzJ11ba2V5XSBhcyBhIFBhdGggb2Jq"
    "ZWN0IHdpdGggc2FmZSBmYWxsYmFjayBkZWZhdWx0cy4iIiIKICAgIHBhdGhzID0gQ0ZHLmdldCgi"
    "cGF0aHMiLCB7fSkKICAgIHZhbHVlID0gcGF0aHMuZ2V0KGtleSkKICAgIGlmIHZhbHVlOgogICAg"
    "ICAgIHJldHVybiBQYXRoKHZhbHVlKQogICAgZmFsbGJhY2sgPSBfREVGQVVMVF9QQVRIUy5nZXQo"
    "a2V5KQogICAgaWYgZmFsbGJhY2s6CiAgICAgICAgcGF0aHNba2V5XSA9IHN0cihmYWxsYmFjaykK"
    "ICAgICAgICByZXR1cm4gZmFsbGJhY2sKICAgIHJldHVybiBTQ1JJUFRfRElSIC8ga2V5Cgpfbm9y"
    "bWFsaXplX2NvbmZpZ19wYXRocygpCgojIOKUgOKUgCBDT0xPUiBDT05TVEFOVFMg4oCUIGRlcml2"
    "ZWQgZnJvbSBwZXJzb25hIHRlbXBsYXRlIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIENfUFJJTUFS"
    "WSwgQ19TRUNPTkRBUlksIENfQUNDRU5ULCBDX0JHLCBDX1BBTkVMLCBDX0JPUkRFUiwKIyBDX1RF"
    "WFQsIENfVEVYVF9ESU0gYXJlIGluamVjdGVkIGF0IHRoZSB0b3Agb2YgdGhpcyBmaWxlIGJ5IGRl"
    "Y2tfYnVpbGRlci4KIyBFdmVyeXRoaW5nIGJlbG93IGlzIGRlcml2ZWQgZnJvbSB0aG9zZSBpbmpl"
    "Y3RlZCB2YWx1ZXMuCgojIFNlbWFudGljIGFsaWFzZXMg4oCUIG1hcCBwZXJzb25hIGNvbG9ycyB0"
    "byBuYW1lZCByb2xlcyB1c2VkIHRocm91Z2hvdXQgdGhlIFVJCkNfQ1JJTVNPTiAgICAgPSBDX1BS"
    "SU1BUlkgICAgICAgICAgIyBtYWluIGFjY2VudCAoYnV0dG9ucywgYm9yZGVycywgaGlnaGxpZ2h0"
    "cykKQ19DUklNU09OX0RJTSA9IENfUFJJTUFSWSArICI4OCIgICAjIGRpbSBhY2NlbnQgZm9yIHN1"
    "YnRsZSBib3JkZXJzCkNfR09MRCAgICAgICAgPSBDX1NFQ09OREFSWSAgICAgICAgIyBtYWluIGxh"
    "YmVsL3RleHQvQUkgb3V0cHV0IGNvbG9yCkNfR09MRF9ESU0gICAgPSBDX1NFQ09OREFSWSArICI4"
    "OCIgIyBkaW0gc2Vjb25kYXJ5CkNfR09MRF9CUklHSFQgPSBDX0FDQ0VOVCAgICAgICAgICAgIyBl"
    "bXBoYXNpcywgaG92ZXIgc3RhdGVzCkNfU0lMVkVSICAgICAgPSBDX1RFWFRfRElNICAgICAgICAg"
    "IyBzZWNvbmRhcnkgdGV4dCAoYWxyZWFkeSBpbmplY3RlZCkKQ19TSUxWRVJfRElNICA9IENfVEVY"
    "VF9ESU0gKyAiODgiICAjIGRpbSBzZWNvbmRhcnkgdGV4dApDX01PTklUT1IgICAgID0gQ19CRyAg"
    "ICAgICAgICAgICAgICMgY2hhdCBkaXNwbGF5IGJhY2tncm91bmQgKGFscmVhZHkgaW5qZWN0ZWQp"
    "CkNfQkcyICAgICAgICAgPSBDX0JHICAgICAgICAgICAgICAgIyBzZWNvbmRhcnkgYmFja2dyb3Vu"
    "ZApDX0JHMyAgICAgICAgID0gQ19QQU5FTCAgICAgICAgICAgICMgdGVydGlhcnkvaW5wdXQgYmFj"
    "a2dyb3VuZCAoYWxyZWFkeSBpbmplY3RlZCkKQ19CTE9PRCAgICAgICA9ICcjOGIwMDAwJyAgICAg"
    "ICAgICAjIGVycm9yIHN0YXRlcywgZGFuZ2VyIOKAlCB1bml2ZXJzYWwKQ19QVVJQTEUgICAgICA9"
    "ICcjODg1NWNjJyAgICAgICAgICAjIFNZU1RFTSBtZXNzYWdlcyDigJQgdW5pdmVyc2FsCkNfUFVS"
    "UExFX0RJTSAgPSAnIzJhMDUyYScgICAgICAgICAgIyBkaW0gcHVycGxlIOKAlCB1bml2ZXJzYWwK"
    "Q19HUkVFTiAgICAgICA9ICcjNDRhYTY2JyAgICAgICAgICAjIHBvc2l0aXZlIHN0YXRlcyDigJQg"
    "dW5pdmVyc2FsCkNfQkxVRSAgICAgICAgPSAnIzQ0ODhjYycgICAgICAgICAgIyBpbmZvIHN0YXRl"
    "cyDigJQgdW5pdmVyc2FsCgojIEZvbnQgaGVscGVyIOKAlCBleHRyYWN0cyBwcmltYXJ5IGZvbnQg"
    "bmFtZSBmb3IgUUZvbnQoKSBjYWxscwpERUNLX0ZPTlQgPSBVSV9GT05UX0ZBTUlMWS5zcGxpdCgn"
    "LCcpWzBdLnN0cmlwKCkuc3RyaXAoIiciKQoKIyBFbW90aW9uIOKGkiBjb2xvciBtYXBwaW5nIChm"
    "b3IgZW1vdGlvbiByZWNvcmQgY2hpcHMpCkVNT1RJT05fQ09MT1JTOiBkaWN0W3N0ciwgc3RyXSA9"
    "IHsKICAgICJ2aWN0b3J5IjogICAgQ19HT0xELAogICAgInNtdWciOiAgICAgICBDX0dPTEQsCiAg"
    "ICAiaW1wcmVzc2VkIjogIENfR09MRCwKICAgICJyZWxpZXZlZCI6ICAgQ19HT0xELAogICAgImhh"
    "cHB5IjogICAgICBDX0dPTEQsCiAgICAiZmxpcnR5IjogICAgIENfR09MRCwKICAgICJwYW5pY2tl"
    "ZCI6ICAgQ19DUklNU09OLAogICAgImFuZ3J5IjogICAgICBDX0NSSU1TT04sCiAgICAic2hvY2tl"
    "ZCI6ICAgIENfQ1JJTVNPTiwKICAgICJjaGVhdG1vZGUiOiAgQ19DUklNU09OLAogICAgImNvbmNl"
    "cm5lZCI6ICAiI2NjNjYyMiIsCiAgICAic2FkIjogICAgICAgICIjY2M2NjIyIiwKICAgICJodW1p"
    "bGlhdGVkIjogIiNjYzY2MjIiLAogICAgImZsdXN0ZXJlZCI6ICAiI2NjNjYyMiIsCiAgICAicGxv"
    "dHRpbmciOiAgIENfUFVSUExFLAogICAgInN1c3BpY2lvdXMiOiBDX1BVUlBMRSwKICAgICJlbnZp"
    "b3VzIjogICAgQ19QVVJQTEUsCiAgICAiZm9jdXNlZCI6ICAgIENfU0lMVkVSLAogICAgImFsZXJ0"
    "IjogICAgICBDX1NJTFZFUiwKICAgICJuZXV0cmFsIjogICAgQ19URVhUX0RJTSwKfQoKIyDilIDi"
    "lIAgREVDT1JBVElWRSBDT05TVEFOVFMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiMgUlVORVMgaXMgc291cmNlZCBmcm9tIFVJX1JVTkVTIGluamVjdGVk"
    "IGJ5IHRoZSBwZXJzb25hIHRlbXBsYXRlClJVTkVTID0gVUlfUlVORVMKCiMgRmFjZSBpbWFnZSBt"
    "YXAg4oCUIHByZWZpeCBmcm9tIEZBQ0VfUFJFRklYLCBmaWxlcyBsaXZlIGluIGNvbmZpZyBwYXRo"
    "cy5mYWNlcwpGQUNFX0ZJTEVTOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICJuZXV0cmFsIjogICAg"
    "ZiJ7RkFDRV9QUkVGSVh9X05ldXRyYWwucG5nIiwKICAgICJhbGVydCI6ICAgICAgZiJ7RkFDRV9Q"
    "UkVGSVh9X0FsZXJ0LnBuZyIsCiAgICAiZm9jdXNlZCI6ICAgIGYie0ZBQ0VfUFJFRklYfV9Gb2N1"
    "c2VkLnBuZyIsCiAgICAic211ZyI6ICAgICAgIGYie0ZBQ0VfUFJFRklYfV9TbXVnLnBuZyIsCiAg"
    "ICAiY29uY2VybmVkIjogIGYie0ZBQ0VfUFJFRklYfV9Db25jZXJuZWQucG5nIiwKICAgICJzYWQi"
    "OiAgICAgICAgZiJ7RkFDRV9QUkVGSVh9X1NhZF9DcnlpbmcucG5nIiwKICAgICJyZWxpZXZlZCI6"
    "ICAgZiJ7RkFDRV9QUkVGSVh9X1JlbGlldmVkLnBuZyIsCiAgICAiaW1wcmVzc2VkIjogIGYie0ZB"
    "Q0VfUFJFRklYfV9JbXByZXNzZWQucG5nIiwKICAgICJ2aWN0b3J5IjogICAgZiJ7RkFDRV9QUkVG"
    "SVh9X1ZpY3RvcnkucG5nIiwKICAgICJodW1pbGlhdGVkIjogZiJ7RkFDRV9QUkVGSVh9X0h1bWls"
    "aWF0ZWQucG5nIiwKICAgICJzdXNwaWNpb3VzIjogZiJ7RkFDRV9QUkVGSVh9X1N1c3BpY2lvdXMu"
    "cG5nIiwKICAgICJwYW5pY2tlZCI6ICAgZiJ7RkFDRV9QUkVGSVh9X1Bhbmlja2VkLnBuZyIsCiAg"
    "ICAiY2hlYXRtb2RlIjogIGYie0ZBQ0VfUFJFRklYfV9DaGVhdF9Nb2RlLnBuZyIsCiAgICAiYW5n"
    "cnkiOiAgICAgIGYie0ZBQ0VfUFJFRklYfV9BbmdyeS5wbmciLAogICAgInBsb3R0aW5nIjogICBm"
    "IntGQUNFX1BSRUZJWH1fUGxvdHRpbmcucG5nIiwKICAgICJzaG9ja2VkIjogICAgZiJ7RkFDRV9Q"
    "UkVGSVh9X1Nob2NrZWQucG5nIiwKICAgICJoYXBweSI6ICAgICAgZiJ7RkFDRV9QUkVGSVh9X0hh"
    "cHB5LnBuZyIsCiAgICAiZmxpcnR5IjogICAgIGYie0ZBQ0VfUFJFRklYfV9GbGlydHkucG5nIiwK"
    "ICAgICJmbHVzdGVyZWQiOiAgZiJ7RkFDRV9QUkVGSVh9X0ZsdXN0ZXJlZC5wbmciLAogICAgImVu"
    "dmlvdXMiOiAgICBmIntGQUNFX1BSRUZJWH1fRW52aW91cy5wbmciLAp9CgpTRU5USU1FTlRfTElT"
    "VCA9ICgKICAgICJuZXV0cmFsLCBhbGVydCwgZm9jdXNlZCwgc211ZywgY29uY2VybmVkLCBzYWQs"
    "IHJlbGlldmVkLCBpbXByZXNzZWQsICIKICAgICJ2aWN0b3J5LCBodW1pbGlhdGVkLCBzdXNwaWNp"
    "b3VzLCBwYW5pY2tlZCwgYW5ncnksIHBsb3R0aW5nLCBzaG9ja2VkLCAiCiAgICAiaGFwcHksIGZs"
    "aXJ0eSwgZmx1c3RlcmVkLCBlbnZpb3VzIgopCgojIOKUgOKUgCBTWVNURU0gUFJPTVBUIOKAlCBp"
    "bmplY3RlZCBmcm9tIHBlcnNvbmEgdGVtcGxhdGUgYXQgdG9wIG9mIGZpbGUg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgU1lTVEVNX1BST01QVF9CQVNFIGlzIGFscmVh"
    "ZHkgZGVmaW5lZCBhYm92ZSBmcm9tIDw8PFNZU1RFTV9QUk9NUFQ+Pj4gaW5qZWN0aW9uLgojIERv"
    "IG5vdCByZWRlZmluZSBpdCBoZXJlLgoKIyDilIDilIAgR0xPQkFMIFNUWUxFU0hFRVQg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSAClNUWUxF"
    "ID0gZiIiIgpRTWFpbldpbmRvdywgUVdpZGdldCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0Nf"
    "Qkd9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlM"
    "WX07Cn19ClFUZXh0RWRpdCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfTU9OSVRPUn07CiAg"
    "ICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07"
    "CiAgICBib3JkZXItcmFkaXVzOiAycHg7CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZ"
    "fTsKICAgIGZvbnQtc2l6ZTogMTJweDsKICAgIHBhZGRpbmc6IDhweDsKICAgIHNlbGVjdGlvbi1i"
    "YWNrZ3JvdW5kLWNvbG9yOiB7Q19DUklNU09OX0RJTX07Cn19ClFMaW5lRWRpdCB7ewogICAgYmFj"
    "a2dyb3VuZC1jb2xvcjoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjog"
    "MXB4IHNvbGlkIHtDX0NSSU1TT059OwogICAgYm9yZGVyLXJhZGl1czogMnB4OwogICAgZm9udC1m"
    "YW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEzcHg7CiAgICBwYWRkaW5n"
    "OiA4cHggMTJweDsKfX0KUUxpbmVFZGl0OmZvY3VzIHt7CiAgICBib3JkZXI6IDFweCBzb2xpZCB7"
    "Q19HT0xEfTsKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX1BBTkVMfTsKfX0KUVB1c2hCdXR0b24g"
    "e3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0NSSU1TT05fRElNfTsKICAgIGNvbG9yOiB7Q19H"
    "T0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OwogICAgYm9yZGVyLXJhZGl1"
    "czogMnB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6"
    "IDEycHg7CiAgICBmb250LXdlaWdodDogYm9sZDsKICAgIHBhZGRpbmc6IDhweCAyMHB4OwogICAg"
    "bGV0dGVyLXNwYWNpbmc6IDJweDsKfX0KUVB1c2hCdXR0b246aG92ZXIge3sKICAgIGJhY2tncm91"
    "bmQtY29sb3I6IHtDX0NSSU1TT059OwogICAgY29sb3I6IHtDX0dPTERfQlJJR0hUfTsKfX0KUVB1"
    "c2hCdXR0b246cHJlc3NlZCB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQkxPT0R9OwogICAg"
    "Ym9yZGVyLWNvbG9yOiB7Q19CTE9PRH07CiAgICBjb2xvcjoge0NfVEVYVH07Cn19ClFQdXNoQnV0"
    "dG9uOmRpc2FibGVkIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19CRzN9OwogICAgY29sb3I6"
    "IHtDX1RFWFRfRElNfTsKICAgIGJvcmRlci1jb2xvcjoge0NfVEVYVF9ESU19Owp9fQpRU2Nyb2xs"
    "QmFyOnZlcnRpY2FsIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CR307CiAgICB3aWR0aDogNnB4Owog"
    "ICAgYm9yZGVyOiBub25lOwp9fQpRU2Nyb2xsQmFyOjpoYW5kbGU6dmVydGljYWwge3sKICAgIGJh"
    "Y2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGJvcmRlci1yYWRpdXM6IDNweDsKfX0KUVNj"
    "cm9sbEJhcjo6aGFuZGxlOnZlcnRpY2FsOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19DUklN"
    "U09OfTsKfX0KUVNjcm9sbEJhcjo6YWRkLWxpbmU6dmVydGljYWwsIFFTY3JvbGxCYXI6OnN1Yi1s"
    "aW5lOnZlcnRpY2FsIHt7CiAgICBoZWlnaHQ6IDBweDsKfX0KUVRhYldpZGdldDo6cGFuZSB7ewog"
    "ICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgYmFja2dyb3VuZDoge0Nf"
    "QkcyfTsKfX0KUVRhYkJhcjo6dGFiIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgY29s"
    "b3I6IHtDX1RFWFRfRElNfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsK"
    "ICAgIHBhZGRpbmc6IDZweCAxNHB4OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07"
    "CiAgICBmb250LXNpemU6IDEwcHg7CiAgICBsZXR0ZXItc3BhY2luZzogMXB4Owp9fQpRVGFiQmFy"
    "Ojp0YWI6c2VsZWN0ZWQge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGNv"
    "bG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlci1ib3R0b206IDJweCBzb2xpZCB7Q19DUklNU09OfTsK"
    "fX0KUVRhYkJhcjo6dGFiOmhvdmVyIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19QQU5FTH07CiAgICBj"
    "b2xvcjoge0NfR09MRF9ESU19Owp9fQpRVGFibGVXaWRnZXQge3sKICAgIGJhY2tncm91bmQ6IHtD"
    "X0JHMn07CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklN"
    "U09OX0RJTX07CiAgICBncmlkbGluZS1jb2xvcjoge0NfQk9SREVSfTsKICAgIGZvbnQtZmFtaWx5"
    "OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMXB4Owp9fQpRVGFibGVXaWRnZXQ6"
    "Oml0ZW06c2VsZWN0ZWQge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIGNv"
    "bG9yOiB7Q19HT0xEX0JSSUdIVH07Cn19ClFIZWFkZXJWaWV3OjpzZWN0aW9uIHt7CiAgICBiYWNr"
    "Z3JvdW5kOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29s"
    "aWQge0NfQ1JJTVNPTl9ESU19OwogICAgcGFkZGluZzogNHB4OwogICAgZm9udC1mYW1pbHk6IHtV"
    "SV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDEwcHg7CiAgICBmb250LXdlaWdodDogYm9s"
    "ZDsKICAgIGxldHRlci1zcGFjaW5nOiAxcHg7Cn19ClFDb21ib0JveCB7ewogICAgYmFja2dyb3Vu"
    "ZDoge0NfQkczfTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtD"
    "X0NSSU1TT05fRElNfTsKICAgIHBhZGRpbmc6IDRweCA4cHg7CiAgICBmb250LWZhbWlseToge1VJ"
    "X0ZPTlRfRkFNSUxZfTsKfX0KUUNvbWJvQm94Ojpkcm9wLWRvd24ge3sKICAgIGJvcmRlcjogbm9u"
    "ZTsKfX0KUUNoZWNrQm94IHt7CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBmb250LWZhbWlseTog"
    "e1VJX0ZPTlRfRkFNSUxZfTsKfX0KUUxhYmVsIHt7CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBi"
    "b3JkZXI6IG5vbmU7Cn19ClFTcGxpdHRlcjo6aGFuZGxlIHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19D"
    "UklNU09OX0RJTX07CiAgICB3aWR0aDogMnB4Owp9fQoiIiIKCiMg4pSA4pSAIERJUkVDVE9SWSBC"
    "T09UU1RSQVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmRlZiBib290c3RyYXBfZGlyZWN0b3JpZXMoKSAtPiBOb25lOgogICAgIiIiCiAgICBDcmVh"
    "dGUgYWxsIHJlcXVpcmVkIGRpcmVjdG9yaWVzIGlmIHRoZXkgZG9uJ3QgZXhpc3QuCiAgICBDYWxs"
    "ZWQgb24gc3RhcnR1cCBiZWZvcmUgYW55dGhpbmcgZWxzZS4gU2FmZSB0byBjYWxsIG11bHRpcGxl"
    "IHRpbWVzLgogICAgQWxzbyBtaWdyYXRlcyBmaWxlcyBmcm9tIG9sZCBbRGVja05hbWVdX01lbW9y"
    "aWVzIGxheW91dCBpZiBkZXRlY3RlZC4KICAgICIiIgogICAgZGlycyA9IFsKICAgICAgICBjZmdf"
    "cGF0aCgiZmFjZXMiKSwKICAgICAgICBjZmdfcGF0aCgic291bmRzIiksCiAgICAgICAgY2ZnX3Bh"
    "dGgoIm1lbW9yaWVzIiksCiAgICAgICAgY2ZnX3BhdGgoInNlc3Npb25zIiksCiAgICAgICAgY2Zn"
    "X3BhdGgoInNsIiksCiAgICAgICAgY2ZnX3BhdGgoImV4cG9ydHMiKSwKICAgICAgICBjZmdfcGF0"
    "aCgibG9ncyIpLAogICAgICAgIGNmZ19wYXRoKCJiYWNrdXBzIiksCiAgICAgICAgY2ZnX3BhdGgo"
    "InBlcnNvbmFzIiksCiAgICAgICAgY2ZnX3BhdGgoImdvb2dsZSIpLAogICAgICAgIGNmZ19wYXRo"
    "KCJnb29nbGUiKSAvICJleHBvcnRzIiwKICAgIF0KICAgIGZvciBkIGluIGRpcnM6CiAgICAgICAg"
    "ZC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCgogICAgIyBDcmVhdGUgZW1wdHkg"
    "SlNPTkwgZmlsZXMgaWYgdGhleSBkb24ndCBleGlzdAogICAgbWVtb3J5X2RpciA9IGNmZ19wYXRo"
    "KCJtZW1vcmllcyIpCiAgICBmb3IgZm5hbWUgaW4gKCJtZXNzYWdlcy5qc29ubCIsICJtZW1vcmll"
    "cy5qc29ubCIsICJ0YXNrcy5qc29ubCIsCiAgICAgICAgICAgICAgICAgICJsZXNzb25zX2xlYXJu"
    "ZWQuanNvbmwiLCAicGVyc29uYV9oaXN0b3J5Lmpzb25sIik6CiAgICAgICAgZnAgPSBtZW1vcnlf"
    "ZGlyIC8gZm5hbWUKICAgICAgICBpZiBub3QgZnAuZXhpc3RzKCk6CiAgICAgICAgICAgIGZwLndy"
    "aXRlX3RleHQoIiIsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgc2xfZGlyID0gY2ZnX3BhdGgoInNs"
    "IikKICAgIGZvciBmbmFtZSBpbiAoInNsX3NjYW5zLmpzb25sIiwgInNsX2NvbW1hbmRzLmpzb25s"
    "Iik6CiAgICAgICAgZnAgPSBzbF9kaXIgLyBmbmFtZQogICAgICAgIGlmIG5vdCBmcC5leGlzdHMo"
    "KToKICAgICAgICAgICAgZnAud3JpdGVfdGV4dCgiIiwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBz"
    "ZXNzaW9uc19kaXIgPSBjZmdfcGF0aCgic2Vzc2lvbnMiKQogICAgaWR4ID0gc2Vzc2lvbnNfZGly"
    "IC8gInNlc3Npb25faW5kZXguanNvbiIKICAgIGlmIG5vdCBpZHguZXhpc3RzKCk6CiAgICAgICAg"
    "aWR4LndyaXRlX3RleHQoanNvbi5kdW1wcyh7InNlc3Npb25zIjogW119LCBpbmRlbnQ9MiksIGVu"
    "Y29kaW5nPSJ1dGYtOCIpCgogICAgc3RhdGVfcGF0aCA9IG1lbW9yeV9kaXIgLyAic3RhdGUuanNv"
    "biIKICAgIGlmIG5vdCBzdGF0ZV9wYXRoLmV4aXN0cygpOgogICAgICAgIF93cml0ZV9kZWZhdWx0"
    "X3N0YXRlKHN0YXRlX3BhdGgpCgogICAgaW5kZXhfcGF0aCA9IG1lbW9yeV9kaXIgLyAiaW5kZXgu"
    "anNvbiIKICAgIGlmIG5vdCBpbmRleF9wYXRoLmV4aXN0cygpOgogICAgICAgIGluZGV4X3BhdGgu"
    "d3JpdGVfdGV4dCgKICAgICAgICAgICAganNvbi5kdW1wcyh7InZlcnNpb24iOiBBUFBfVkVSU0lP"
    "TiwgInRvdGFsX21lc3NhZ2VzIjogMCwKICAgICAgICAgICAgICAgICAgICAgICAgInRvdGFsX21l"
    "bW9yaWVzIjogMH0sIGluZGVudD0yKSwKICAgICAgICAgICAgZW5jb2Rpbmc9InV0Zi04IgogICAg"
    "ICAgICkKCiAgICAjIExlZ2FjeSBtaWdyYXRpb246IGlmIG9sZCBNb3JnYW5uYV9NZW1vcmllcyBm"
    "b2xkZXIgZXhpc3RzLCBtaWdyYXRlIGZpbGVzCiAgICBfbWlncmF0ZV9sZWdhY3lfZmlsZXMoKQoK"
    "ZGVmIF93cml0ZV9kZWZhdWx0X3N0YXRlKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICBzdGF0ZSA9"
    "IHsKICAgICAgICAicGVyc29uYV9uYW1lIjogREVDS19OQU1FLAogICAgICAgICJkZWNrX3ZlcnNp"
    "b24iOiBBUFBfVkVSU0lPTiwKICAgICAgICAic2Vzc2lvbl9jb3VudCI6IDAsCiAgICAgICAgImxh"
    "c3Rfc3RhcnR1cCI6IE5vbmUsCiAgICAgICAgImxhc3Rfc2h1dGRvd24iOiBOb25lLAogICAgICAg"
    "ICJsYXN0X2FjdGl2ZSI6IE5vbmUsCiAgICAgICAgInRvdGFsX21lc3NhZ2VzIjogMCwKICAgICAg"
    "ICAidG90YWxfbWVtb3JpZXMiOiAwLAogICAgICAgICJpbnRlcm5hbF9uYXJyYXRpdmUiOiB7fSwK"
    "ICAgICAgICAidmFtcGlyZV9zdGF0ZV9hdF9zaHV0ZG93biI6ICJET1JNQU5UIiwKICAgIH0KICAg"
    "IHBhdGgud3JpdGVfdGV4dChqc29uLmR1bXBzKHN0YXRlLCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1"
    "dGYtOCIpCgpkZWYgX21pZ3JhdGVfbGVnYWN5X2ZpbGVzKCkgLT4gTm9uZToKICAgICIiIgogICAg"
    "SWYgb2xkIEQ6XFxBSVxcTW9kZWxzXFxbRGVja05hbWVdX01lbW9yaWVzIGxheW91dCBpcyBkZXRl"
    "Y3RlZCwKICAgIG1pZ3JhdGUgZmlsZXMgdG8gbmV3IHN0cnVjdHVyZSBzaWxlbnRseS4KICAgICIi"
    "IgogICAgIyBUcnkgdG8gZmluZCBvbGQgbGF5b3V0IHJlbGF0aXZlIHRvIG1vZGVsIHBhdGgKICAg"
    "IG1vZGVsX3BhdGggPSBQYXRoKENGR1sibW9kZWwiXS5nZXQoInBhdGgiLCAiIikpCiAgICBpZiBu"
    "b3QgbW9kZWxfcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4KICAgIG9sZF9yb290ID0gbW9k"
    "ZWxfcGF0aC5wYXJlbnQgLyBmIntERUNLX05BTUV9X01lbW9yaWVzIgogICAgaWYgbm90IG9sZF9y"
    "b290LmV4aXN0cygpOgogICAgICAgIHJldHVybgoKICAgIG1pZ3JhdGlvbnMgPSBbCiAgICAgICAg"
    "KG9sZF9yb290IC8gIm1lbW9yaWVzLmpzb25sIiwgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmll"
    "cyIpIC8gIm1lbW9yaWVzLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gIm1lc3NhZ2VzLmpz"
    "b25sIiwgICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJtZXNzYWdlcy5qc29ubCIp"
    "LAogICAgICAgIChvbGRfcm9vdCAvICJ0YXNrcy5qc29ubCIsICAgICAgICAgICAgICAgY2ZnX3Bh"
    "dGgoIm1lbW9yaWVzIikgLyAidGFza3MuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAic3Rh"
    "dGUuanNvbiIsICAgICAgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gInN0YXRlLmpz"
    "b24iKSwKICAgICAgICAob2xkX3Jvb3QgLyAiaW5kZXguanNvbiIsICAgICAgICAgICAgICAgIGNm"
    "Z19wYXRoKCJtZW1vcmllcyIpIC8gImluZGV4Lmpzb24iKSwKICAgICAgICAob2xkX3Jvb3QgLyAi"
    "c2xfc2NhbnMuanNvbmwiLCAgICAgICAgICAgIGNmZ19wYXRoKCJzbCIpIC8gInNsX3NjYW5zLmpz"
    "b25sIiksCiAgICAgICAgKG9sZF9yb290IC8gInNsX2NvbW1hbmRzLmpzb25sIiwgICAgICAgICBj"
    "ZmdfcGF0aCgic2wiKSAvICJzbF9jb21tYW5kcy5qc29ubCIpLAogICAgICAgIChvbGRfcm9vdCAv"
    "ICJnb29nbGUiIC8gInRva2VuLmpzb24iLCAgICAgUGF0aChDRkdbImdvb2dsZSJdWyJ0b2tlbiJd"
    "KSksCiAgICAgICAgKG9sZF9yb290IC8gImNvbmZpZyIgLyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpz"
    "b24iLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIFBh"
    "dGgoQ0ZHWyJnb29nbGUiXVsiY3JlZGVudGlhbHMiXSkpLAogICAgICAgIChvbGRfcm9vdCAvICJz"
    "b3VuZHMiIC8gZiJ7U09VTkRfUFJFRklYfV9hbGVydC53YXYiLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGNmZ19wYXRoKCJzb3VuZHMiKSAvIGYie1NP"
    "VU5EX1BSRUZJWH1fYWxlcnQud2F2IiksCiAgICBdCgogICAgZm9yIHNyYywgZHN0IGluIG1pZ3Jh"
    "dGlvbnM6CiAgICAgICAgaWYgc3JjLmV4aXN0cygpIGFuZCBub3QgZHN0LmV4aXN0cygpOgogICAg"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBkc3QucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1"
    "ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICAgICAgICAgIGltcG9ydCBzaHV0aWwKICAgICAgICAg"
    "ICAgICAgIHNodXRpbC5jb3B5MihzdHIoc3JjKSwgc3RyKGRzdCkpCiAgICAgICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgIyBNaWdyYXRlIGZhY2UgaW1h"
    "Z2VzCiAgICBvbGRfZmFjZXMgPSBvbGRfcm9vdCAvICJGYWNlcyIKICAgIG5ld19mYWNlcyA9IGNm"
    "Z19wYXRoKCJmYWNlcyIpCiAgICBpZiBvbGRfZmFjZXMuZXhpc3RzKCk6CiAgICAgICAgZm9yIGlt"
    "ZyBpbiBvbGRfZmFjZXMuZ2xvYigiKi5wbmciKToKICAgICAgICAgICAgZHN0ID0gbmV3X2ZhY2Vz"
    "IC8gaW1nLm5hbWUKICAgICAgICAgICAgaWYgbm90IGRzdC5leGlzdHMoKToKICAgICAgICAgICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBpbXBvcnQgc2h1dGlsCiAgICAgICAgICAgICAg"
    "ICAgICAgc2h1dGlsLmNvcHkyKHN0cihpbWcpLCBzdHIoZHN0KSkKICAgICAgICAgICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgcGFzcwoKIyDilIDilIAgREFURVRJ"
    "TUUgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKZGVmIGxvY2FsX25vd19pc28oKSAtPiBzdHI6CiAgICByZXR1cm4gZGF0"
    "ZXRpbWUubm93KCkucmVwbGFjZShtaWNyb3NlY29uZD0wKS5pc29mb3JtYXQoKQoKZGVmIHBhcnNl"
    "X2lzbyh2YWx1ZTogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICBpZiBub3QgdmFsdWU6"
    "CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIHZhbHVlID0gdmFsdWUuc3RyaXAoKQogICAgdHJ5Ogog"
    "ICAgICAgIGlmIHZhbHVlLmVuZHN3aXRoKCJaIik6CiAgICAgICAgICAgIHJldHVybiBkYXRldGlt"
    "ZS5mcm9taXNvZm9ybWF0KHZhbHVlWzotMV0pLnJlcGxhY2UodHppbmZvPXRpbWV6b25lLnV0YykK"
    "ICAgICAgICByZXR1cm4gZGF0ZXRpbWUuZnJvbWlzb2Zvcm1hdCh2YWx1ZSkKICAgIGV4Y2VwdCBF"
    "eGNlcHRpb246CiAgICAgICAgcmV0dXJuIE5vbmUKCl9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xP"
    "R0dFRDogc2V0W3R1cGxlXSA9IHNldCgpCgoKZGVmIF9yZXNvbHZlX2RlY2tfdGltZXpvbmVfbmFt"
    "ZSgpIC0+IE9wdGlvbmFsW3N0cl06CiAgICBzZXR0aW5ncyA9IENGRy5nZXQoInNldHRpbmdzIiwg"
    "e30pIGlmIGlzaW5zdGFuY2UoQ0ZHLCBkaWN0KSBlbHNlIHt9CiAgICBhdXRvX2RldGVjdCA9IGJv"
    "b2woc2V0dGluZ3MuZ2V0KCJ0aW1lem9uZV9hdXRvX2RldGVjdCIsIFRydWUpKQogICAgb3ZlcnJp"
    "ZGUgPSBzdHIoc2V0dGluZ3MuZ2V0KCJ0aW1lem9uZV9vdmVycmlkZSIsICIiKSBvciAiIikuc3Ry"
    "aXAoKQogICAgaWYgbm90IGF1dG9fZGV0ZWN0IGFuZCBvdmVycmlkZToKICAgICAgICByZXR1cm4g"
    "b3ZlcnJpZGUKICAgIGxvY2FsX3R6aW5mbyA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS50"
    "emluZm8KICAgIGlmIGxvY2FsX3R6aW5mbyBpcyBub3QgTm9uZToKICAgICAgICB0el9rZXkgPSBn"
    "ZXRhdHRyKGxvY2FsX3R6aW5mbywgImtleSIsIE5vbmUpCiAgICAgICAgaWYgdHpfa2V5OgogICAg"
    "ICAgICAgICByZXR1cm4gc3RyKHR6X2tleSkKICAgICAgICB0el9uYW1lID0gc3RyKGxvY2FsX3R6"
    "aW5mbykKICAgICAgICBpZiB0el9uYW1lIGFuZCB0el9uYW1lLnVwcGVyKCkgIT0gIkxPQ0FMIjoK"
    "ICAgICAgICAgICAgcmV0dXJuIHR6X25hbWUKICAgIHJldHVybiBOb25lCgoKZGVmIF9sb2NhbF90"
    "emluZm8oKToKICAgIHR6X25hbWUgPSBfcmVzb2x2ZV9kZWNrX3RpbWV6b25lX25hbWUoKQogICAg"
    "aWYgdHpfbmFtZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVybiBab25lSW5mbyh0el9u"
    "YW1lKQogICAgICAgIGV4Y2VwdCBab25lSW5mb05vdEZvdW5kRXJyb3I6CiAgICAgICAgICAgIF9l"
    "YXJseV9sb2coZiJbREFURVRJTUVdW1dBUk5dIFVua25vd24gdGltZXpvbmUgb3ZlcnJpZGUgJ3t0"
    "el9uYW1lfScsIHVzaW5nIHN5c3RlbSBsb2NhbCB0aW1lem9uZS4iKQogICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKICAgIHJldHVybiBkYXRldGltZS5ub3coKS5hc3Rp"
    "bWV6b25lKCkudHppbmZvIG9yIHRpbWV6b25lLnV0YwoKCmRlZiBub3dfZm9yX2NvbXBhcmUoKToK"
    "ICAgIHJldHVybiBkYXRldGltZS5ub3coX2xvY2FsX3R6aW5mbygpKQoKCmRlZiBub3JtYWxpemVf"
    "ZGF0ZXRpbWVfZm9yX2NvbXBhcmUoZHRfdmFsdWUsIGNvbnRleHQ6IHN0ciA9ICIiKToKICAgIGlm"
    "IGR0X3ZhbHVlIGlzIE5vbmU6CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIGlmIG5vdCBpc2luc3Rh"
    "bmNlKGR0X3ZhbHVlLCBkYXRldGltZSk6CiAgICAgICAgcmV0dXJuIE5vbmUKICAgIGxvY2FsX3R6"
    "ID0gX2xvY2FsX3R6aW5mbygpCiAgICBpZiBkdF92YWx1ZS50emluZm8gaXMgTm9uZToKICAgICAg"
    "ICBub3JtYWxpemVkID0gZHRfdmFsdWUucmVwbGFjZSh0emluZm89bG9jYWxfdHopCiAgICAgICAg"
    "a2V5ID0gKCJuYWl2ZSIsIGNvbnRleHQpCiAgICAgICAgaWYga2V5IG5vdCBpbiBfREFURVRJTUVf"
    "Tk9STUFMSVpBVElPTl9MT0dHRUQ6CiAgICAgICAgICAgIF9lYXJseV9sb2coCiAgICAgICAgICAg"
    "ICAgICBmIltEQVRFVElNRV1bSU5GT10gTm9ybWFsaXplZCBuYWl2ZSBkYXRldGltZSB0byBsb2Nh"
    "bCB0aW1lem9uZSBmb3Ige2NvbnRleHQgb3IgJ2dlbmVyYWwnfSBjb21wYXJpc29ucy4iCiAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VELmFkZChr"
    "ZXkpCiAgICAgICAgcmV0dXJuIG5vcm1hbGl6ZWQKICAgIG5vcm1hbGl6ZWQgPSBkdF92YWx1ZS5h"
    "c3RpbWV6b25lKGxvY2FsX3R6KQogICAgZHRfdHpfbmFtZSA9IHN0cihkdF92YWx1ZS50emluZm8p"
    "CiAgICBrZXkgPSAoImF3YXJlIiwgY29udGV4dCwgZHRfdHpfbmFtZSkKICAgIGlmIGtleSBub3Qg"
    "aW4gX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VEIGFuZCBkdF90el9uYW1lIG5vdCBpbiB7"
    "IlVUQyIsIHN0cihsb2NhbF90eil9OgogICAgICAgIF9lYXJseV9sb2coCiAgICAgICAgICAgIGYi"
    "W0RBVEVUSU1FXVtJTkZPXSBOb3JtYWxpemVkIHRpbWV6b25lLWF3YXJlIGRhdGV0aW1lIGZyb20g"
    "e2R0X3R6X25hbWV9IHRvIGxvY2FsIHRpbWV6b25lIGZvciB7Y29udGV4dCBvciAnZ2VuZXJhbCd9"
    "IGNvbXBhcmlzb25zLiIKICAgICAgICApCiAgICAgICAgX0RBVEVUSU1FX05PUk1BTElaQVRJT05f"
    "TE9HR0VELmFkZChrZXkpCiAgICByZXR1cm4gbm9ybWFsaXplZAoKCmRlZiBwYXJzZV9pc29fZm9y"
    "X2NvbXBhcmUodmFsdWUsIGNvbnRleHQ6IHN0ciA9ICIiKToKICAgIHJldHVybiBub3JtYWxpemVf"
    "ZGF0ZXRpbWVfZm9yX2NvbXBhcmUocGFyc2VfaXNvKHZhbHVlKSwgY29udGV4dD1jb250ZXh0KQoK"
    "CmRlZiBfdGFza19kdWVfc29ydF9rZXkodGFzazogZGljdCk6CiAgICBkdWUgPSBwYXJzZV9pc29f"
    "Zm9yX2NvbXBhcmUoKHRhc2sgb3Ige30pLmdldCgiZHVlX2F0Iikgb3IgKHRhc2sgb3Ige30pLmdl"
    "dCgiZHVlIiksIGNvbnRleHQ9InRhc2tfc29ydCIpCiAgICBpZiBkdWUgaXMgTm9uZToKICAgICAg"
    "ICByZXR1cm4gKDEsIGRhdGV0aW1lLm1heC5yZXBsYWNlKHR6aW5mbz10aW1lem9uZS51dGMpKQog"
    "ICAgcmV0dXJuICgwLCBkdWUuYXN0aW1lem9uZSh0aW1lem9uZS51dGMpLCAoKHRhc2sgb3Ige30p"
    "LmdldCgidGV4dCIpIG9yICIiKS5sb3dlcigpKQoKCmRlZiBmb3JtYXRfZHVyYXRpb24oc2Vjb25k"
    "czogZmxvYXQpIC0+IHN0cjoKICAgIHRvdGFsID0gbWF4KDAsIGludChzZWNvbmRzKSkKICAgIGRh"
    "eXMsIHJlbSA9IGRpdm1vZCh0b3RhbCwgODY0MDApCiAgICBob3VycywgcmVtID0gZGl2bW9kKHJl"
    "bSwgMzYwMCkKICAgIG1pbnV0ZXMsIHNlY3MgPSBkaXZtb2QocmVtLCA2MCkKICAgIHBhcnRzID0g"
    "W10KICAgIGlmIGRheXM6ICAgIHBhcnRzLmFwcGVuZChmIntkYXlzfWQiKQogICAgaWYgaG91cnM6"
    "ICAgcGFydHMuYXBwZW5kKGYie2hvdXJzfWgiKQogICAgaWYgbWludXRlczogcGFydHMuYXBwZW5k"
    "KGYie21pbnV0ZXN9bSIpCiAgICBpZiBub3QgcGFydHM6IHBhcnRzLmFwcGVuZChmIntzZWNzfXMi"
    "KQogICAgcmV0dXJuICIgIi5qb2luKHBhcnRzWzozXSkKCiMg4pSA4pSAIE1PT04gUEhBU0UgSEVM"
    "UEVSUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKIyBDb3JyZWN0ZWQgaWxsdW1pbmF0aW9uIG1hdGgg4oCUIGRpc3BsYXllZCBtb29uIG1hdGNo"
    "ZXMgbGFiZWxlZCBwaGFzZS4KCl9LTk9XTl9ORVdfTU9PTiA9IGRhdGUoMjAwMCwgMSwgNikKX0xV"
    "TkFSX0NZQ0xFICAgID0gMjkuNTMwNTg4NjcKCmRlZiBnZXRfbW9vbl9waGFzZSgpIC0+IHR1cGxl"
    "W2Zsb2F0LCBzdHIsIGZsb2F0XToKICAgICIiIgogICAgUmV0dXJucyAocGhhc2VfZnJhY3Rpb24s"
    "IHBoYXNlX25hbWUsIGlsbHVtaW5hdGlvbl9wY3QpLgogICAgcGhhc2VfZnJhY3Rpb246IDAuMCA9"
    "IG5ldyBtb29uLCAwLjUgPSBmdWxsIG1vb24sIDEuMCA9IG5ldyBtb29uIGFnYWluLgogICAgaWxs"
    "dW1pbmF0aW9uX3BjdDogMOKAkzEwMCwgY29ycmVjdGVkIHRvIG1hdGNoIHZpc3VhbCBwaGFzZS4K"
    "ICAgICIiIgogICAgZGF5cyAgPSAoZGF0ZS50b2RheSgpIC0gX0tOT1dOX05FV19NT09OKS5kYXlz"
    "CiAgICBjeWNsZSA9IGRheXMgJSBfTFVOQVJfQ1lDTEUKICAgIHBoYXNlID0gY3ljbGUgLyBfTFVO"
    "QVJfQ1lDTEUKCiAgICBpZiAgIGN5Y2xlIDwgMS44NTogICBuYW1lID0gIk5FVyBNT09OIgogICAg"
    "ZWxpZiBjeWNsZSA8IDcuMzg6ICAgbmFtZSA9ICJXQVhJTkcgQ1JFU0NFTlQiCiAgICBlbGlmIGN5"
    "Y2xlIDwgOS4yMjogICBuYW1lID0gIkZJUlNUIFFVQVJURVIiCiAgICBlbGlmIGN5Y2xlIDwgMTQu"
    "Nzc6ICBuYW1lID0gIldBWElORyBHSUJCT1VTIgogICAgZWxpZiBjeWNsZSA8IDE2LjYxOiAgbmFt"
    "ZSA9ICJGVUxMIE1PT04iCiAgICBlbGlmIGN5Y2xlIDwgMjIuMTU6ICBuYW1lID0gIldBTklORyBH"
    "SUJCT1VTIgogICAgZWxpZiBjeWNsZSA8IDIzLjk5OiAgbmFtZSA9ICJMQVNUIFFVQVJURVIiCiAg"
    "ICBlbHNlOiAgICAgICAgICAgICAgICBuYW1lID0gIldBTklORyBDUkVTQ0VOVCIKCiAgICAjIENv"
    "cnJlY3RlZCBpbGx1bWluYXRpb246IGNvcy1iYXNlZCwgcGVha3MgYXQgZnVsbCBtb29uCiAgICBp"
    "bGx1bWluYXRpb24gPSAoMSAtIG1hdGguY29zKDIgKiBtYXRoLnBpICogcGhhc2UpKSAvIDIgKiAx"
    "MDAKICAgIHJldHVybiBwaGFzZSwgbmFtZSwgcm91bmQoaWxsdW1pbmF0aW9uLCAxKQoKX1NVTl9D"
    "QUNIRV9EQVRFOiBPcHRpb25hbFtkYXRlXSA9IE5vbmUKX1NVTl9DQUNIRV9UWl9PRkZTRVRfTUlO"
    "OiBPcHRpb25hbFtpbnRdID0gTm9uZQpfU1VOX0NBQ0hFX1RJTUVTOiB0dXBsZVtzdHIsIHN0cl0g"
    "PSAoIjA2OjAwIiwgIjE4OjMwIikKCmRlZiBfcmVzb2x2ZV9zb2xhcl9jb29yZGluYXRlcygpIC0+"
    "IHR1cGxlW2Zsb2F0LCBmbG9hdF06CiAgICAiIiIKICAgIFJlc29sdmUgbGF0aXR1ZGUvbG9uZ2l0"
    "dWRlIGZyb20gcnVudGltZSBjb25maWcgd2hlbiBhdmFpbGFibGUuCiAgICBGYWxscyBiYWNrIHRv"
    "IHRpbWV6b25lLWRlcml2ZWQgY29hcnNlIGRlZmF1bHRzLgogICAgIiIiCiAgICBsYXQgPSBOb25l"
    "CiAgICBsb24gPSBOb25lCiAgICB0cnk6CiAgICAgICAgc2V0dGluZ3MgPSBDRkcuZ2V0KCJzZXR0"
    "aW5ncyIsIHt9KSBpZiBpc2luc3RhbmNlKENGRywgZGljdCkgZWxzZSB7fQogICAgICAgIGZvciBr"
    "ZXkgaW4gKCJsYXRpdHVkZSIsICJsYXQiKToKICAgICAgICAgICAgaWYga2V5IGluIHNldHRpbmdz"
    "OgogICAgICAgICAgICAgICAgbGF0ID0gZmxvYXQoc2V0dGluZ3Nba2V5XSkKICAgICAgICAgICAg"
    "ICAgIGJyZWFrCiAgICAgICAgZm9yIGtleSBpbiAoImxvbmdpdHVkZSIsICJsb24iLCAibG5nIik6"
    "CiAgICAgICAgICAgIGlmIGtleSBpbiBzZXR0aW5nczoKICAgICAgICAgICAgICAgIGxvbiA9IGZs"
    "b2F0KHNldHRpbmdzW2tleV0pCiAgICAgICAgICAgICAgICBicmVhawogICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbjoKICAgICAgICBsYXQgPSBOb25lCiAgICAgICAgbG9uID0gTm9uZQoKICAgIG5vd19sb2Nh"
    "bCA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKQogICAgdHpfb2Zmc2V0ID0gbm93X2xvY2Fs"
    "LnV0Y29mZnNldCgpIG9yIHRpbWVkZWx0YSgwKQogICAgdHpfb2Zmc2V0X2hvdXJzID0gdHpfb2Zm"
    "c2V0LnRvdGFsX3NlY29uZHMoKSAvIDM2MDAuMAoKICAgIGlmIGxvbiBpcyBOb25lOgogICAgICAg"
    "IGxvbiA9IG1heCgtMTgwLjAsIG1pbigxODAuMCwgdHpfb2Zmc2V0X2hvdXJzICogMTUuMCkpCgog"
    "ICAgaWYgbGF0IGlzIE5vbmU6CiAgICAgICAgdHpfbmFtZSA9IHN0cihub3dfbG9jYWwudHppbmZv"
    "IG9yICIiKQogICAgICAgIHNvdXRoX2hpbnQgPSBhbnkodG9rZW4gaW4gdHpfbmFtZSBmb3IgdG9r"
    "ZW4gaW4gKCJBdXN0cmFsaWEiLCAiUGFjaWZpYy9BdWNrbGFuZCIsICJBbWVyaWNhL1NhbnRpYWdv"
    "IikpCiAgICAgICAgbGF0ID0gLTM1LjAgaWYgc291dGhfaGludCBlbHNlIDM1LjAKCiAgICBsYXQg"
    "PSBtYXgoLTY2LjAsIG1pbig2Ni4wLCBsYXQpKQogICAgbG9uID0gbWF4KC0xODAuMCwgbWluKDE4"
    "MC4wLCBsb24pKQogICAgcmV0dXJuIGxhdCwgbG9uCgpkZWYgX2NhbGNfc29sYXJfZXZlbnRfbWlu"
    "dXRlcyhsb2NhbF9kYXk6IGRhdGUsIGxhdGl0dWRlOiBmbG9hdCwgbG9uZ2l0dWRlOiBmbG9hdCwg"
    "c3VucmlzZTogYm9vbCkgLT4gT3B0aW9uYWxbZmxvYXRdOgogICAgIiIiTk9BQS1zdHlsZSBzdW5y"
    "aXNlL3N1bnNldCBzb2x2ZXIuIFJldHVybnMgbG9jYWwgbWludXRlcyBmcm9tIG1pZG5pZ2h0LiIi"
    "IgogICAgbiA9IGxvY2FsX2RheS50aW1ldHVwbGUoKS50bV95ZGF5CiAgICBsbmdfaG91ciA9IGxv"
    "bmdpdHVkZSAvIDE1LjAKICAgIHQgPSBuICsgKCg2IC0gbG5nX2hvdXIpIC8gMjQuMCkgaWYgc3Vu"
    "cmlzZSBlbHNlIG4gKyAoKDE4IC0gbG5nX2hvdXIpIC8gMjQuMCkKCiAgICBNID0gKDAuOTg1NiAq"
    "IHQpIC0gMy4yODkKICAgIEwgPSBNICsgKDEuOTE2ICogbWF0aC5zaW4obWF0aC5yYWRpYW5zKE0p"
    "KSkgKyAoMC4wMjAgKiBtYXRoLnNpbihtYXRoLnJhZGlhbnMoMiAqIE0pKSkgKyAyODIuNjM0CiAg"
    "ICBMID0gTCAlIDM2MC4wCgogICAgUkEgPSBtYXRoLmRlZ3JlZXMobWF0aC5hdGFuKDAuOTE3NjQg"
    "KiBtYXRoLnRhbihtYXRoLnJhZGlhbnMoTCkpKSkKICAgIFJBID0gUkEgJSAzNjAuMAogICAgTF9x"
    "dWFkcmFudCA9IChtYXRoLmZsb29yKEwgLyA5MC4wKSkgKiA5MC4wCiAgICBSQV9xdWFkcmFudCA9"
    "IChtYXRoLmZsb29yKFJBIC8gOTAuMCkpICogOTAuMAogICAgUkEgPSAoUkEgKyAoTF9xdWFkcmFu"
    "dCAtIFJBX3F1YWRyYW50KSkgLyAxNS4wCgogICAgc2luX2RlYyA9IDAuMzk3ODIgKiBtYXRoLnNp"
    "bihtYXRoLnJhZGlhbnMoTCkpCiAgICBjb3NfZGVjID0gbWF0aC5jb3MobWF0aC5hc2luKHNpbl9k"
    "ZWMpKQoKICAgIHplbml0aCA9IDkwLjgzMwogICAgY29zX2ggPSAobWF0aC5jb3MobWF0aC5yYWRp"
    "YW5zKHplbml0aCkpIC0gKHNpbl9kZWMgKiBtYXRoLnNpbihtYXRoLnJhZGlhbnMobGF0aXR1ZGUp"
    "KSkpIC8gKGNvc19kZWMgKiBtYXRoLmNvcyhtYXRoLnJhZGlhbnMobGF0aXR1ZGUpKSkKICAgIGlm"
    "IGNvc19oIDwgLTEuMCBvciBjb3NfaCA+IDEuMDoKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGlm"
    "IHN1bnJpc2U6CiAgICAgICAgSCA9IDM2MC4wIC0gbWF0aC5kZWdyZWVzKG1hdGguYWNvcyhjb3Nf"
    "aCkpCiAgICBlbHNlOgogICAgICAgIEggPSBtYXRoLmRlZ3JlZXMobWF0aC5hY29zKGNvc19oKSkK"
    "ICAgIEggLz0gMTUuMAoKICAgIFQgPSBIICsgUkEgLSAoMC4wNjU3MSAqIHQpIC0gNi42MjIKICAg"
    "IFVUID0gKFQgLSBsbmdfaG91cikgJSAyNC4wCgogICAgbG9jYWxfb2Zmc2V0X2hvdXJzID0gKGRh"
    "dGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS51dGNvZmZzZXQoKSBvciB0aW1lZGVsdGEoMCkpLnRv"
    "dGFsX3NlY29uZHMoKSAvIDM2MDAuMAogICAgbG9jYWxfaG91ciA9IChVVCArIGxvY2FsX29mZnNl"
    "dF9ob3VycykgJSAyNC4wCiAgICByZXR1cm4gbG9jYWxfaG91ciAqIDYwLjAKCmRlZiBfZm9ybWF0"
    "X2xvY2FsX3NvbGFyX3RpbWUobWludXRlc19mcm9tX21pZG5pZ2h0OiBPcHRpb25hbFtmbG9hdF0p"
    "IC0+IHN0cjoKICAgIGlmIG1pbnV0ZXNfZnJvbV9taWRuaWdodCBpcyBOb25lOgogICAgICAgIHJl"
    "dHVybiAiLS06LS0iCiAgICBtaW5zID0gaW50KHJvdW5kKG1pbnV0ZXNfZnJvbV9taWRuaWdodCkp"
    "ICUgKDI0ICogNjApCiAgICBoaCwgbW0gPSBkaXZtb2QobWlucywgNjApCiAgICByZXR1cm4gZGF0"
    "ZXRpbWUubm93KCkucmVwbGFjZShob3VyPWhoLCBtaW51dGU9bW0sIHNlY29uZD0wLCBtaWNyb3Nl"
    "Y29uZD0wKS5zdHJmdGltZSgiJUg6JU0iKQoKZGVmIGdldF9zdW5fdGltZXMoKSAtPiB0dXBsZVtz"
    "dHIsIHN0cl06CiAgICAiIiIKICAgIENvbXB1dGUgbG9jYWwgc3VucmlzZS9zdW5zZXQgdXNpbmcg"
    "c3lzdGVtIGRhdGUgKyB0aW1lem9uZSBhbmQgb3B0aW9uYWwKICAgIHJ1bnRpbWUgbGF0aXR1ZGUv"
    "bG9uZ2l0dWRlIGhpbnRzIHdoZW4gYXZhaWxhYmxlLgogICAgQ2FjaGVkIHBlciBsb2NhbCBkYXRl"
    "IGFuZCB0aW1lem9uZSBvZmZzZXQuCiAgICAiIiIKICAgIGdsb2JhbCBfU1VOX0NBQ0hFX0RBVEUs"
    "IF9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTiwgX1NVTl9DQUNIRV9USU1FUwoKICAgIG5vd19sb2Nh"
    "bCA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKQogICAgdG9kYXkgPSBub3dfbG9jYWwuZGF0"
    "ZSgpCiAgICB0el9vZmZzZXRfbWluID0gaW50KChub3dfbG9jYWwudXRjb2Zmc2V0KCkgb3IgdGlt"
    "ZWRlbHRhKDApKS50b3RhbF9zZWNvbmRzKCkgLy8gNjApCgogICAgaWYgX1NVTl9DQUNIRV9EQVRF"
    "ID09IHRvZGF5IGFuZCBfU1VOX0NBQ0hFX1RaX09GRlNFVF9NSU4gPT0gdHpfb2Zmc2V0X21pbjoK"
    "ICAgICAgICByZXR1cm4gX1NVTl9DQUNIRV9USU1FUwoKICAgIHRyeToKICAgICAgICBsYXQsIGxv"
    "biA9IF9yZXNvbHZlX3NvbGFyX2Nvb3JkaW5hdGVzKCkKICAgICAgICBzdW5yaXNlX21pbiA9IF9j"
    "YWxjX3NvbGFyX2V2ZW50X21pbnV0ZXModG9kYXksIGxhdCwgbG9uLCBzdW5yaXNlPVRydWUpCiAg"
    "ICAgICAgc3Vuc2V0X21pbiA9IF9jYWxjX3NvbGFyX2V2ZW50X21pbnV0ZXModG9kYXksIGxhdCwg"
    "bG9uLCBzdW5yaXNlPUZhbHNlKQogICAgICAgIGlmIHN1bnJpc2VfbWluIGlzIE5vbmUgb3Igc3Vu"
    "c2V0X21pbiBpcyBOb25lOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJTb2xhciBldmVu"
    "dCB1bmF2YWlsYWJsZSBmb3IgcmVzb2x2ZWQgY29vcmRpbmF0ZXMiKQogICAgICAgIHRpbWVzID0g"
    "KF9mb3JtYXRfbG9jYWxfc29sYXJfdGltZShzdW5yaXNlX21pbiksIF9mb3JtYXRfbG9jYWxfc29s"
    "YXJfdGltZShzdW5zZXRfbWluKSkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgdGltZXMg"
    "PSAoIjA2OjAwIiwgIjE4OjMwIikKCiAgICBfU1VOX0NBQ0hFX0RBVEUgPSB0b2RheQogICAgX1NV"
    "Tl9DQUNIRV9UWl9PRkZTRVRfTUlOID0gdHpfb2Zmc2V0X21pbgogICAgX1NVTl9DQUNIRV9USU1F"
    "UyA9IHRpbWVzCiAgICByZXR1cm4gdGltZXMKCiMg4pSA4pSAIFZBTVBJUkUgU1RBVEUgU1lTVEVN"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFRpbWUt"
    "b2YtZGF5IGJlaGF2aW9yYWwgc3RhdGUuIEFjdGl2ZSBvbmx5IHdoZW4gQUlfU1RBVEVTX0VOQUJM"
    "RUQ9VHJ1ZS4KIyBJbmplY3RlZCBpbnRvIHN5c3RlbSBwcm9tcHQgb24gZXZlcnkgZ2VuZXJhdGlv"
    "biBjYWxsLgoKVkFNUElSRV9TVEFURVM6IGRpY3Rbc3RyLCBkaWN0XSA9IHsKICAgICJXSVRDSElO"
    "RyBIT1VSIjogIHsiaG91cnMiOiB7MH0sICAgICAgICAgICAiY29sb3IiOiBDX0dPTEQsICAgICAg"
    "ICAicG93ZXIiOiAxLjB9LAogICAgIkRFRVAgTklHSFQiOiAgICAgeyJob3VycyI6IHsxLDIsM30s"
    "ICAgICAgICAiY29sb3IiOiBDX1BVUlBMRSwgICAgICAicG93ZXIiOiAwLjk1fSwKICAgICJUV0lM"
    "SUdIVCBGQURJTkciOnsiaG91cnMiOiB7NCw1fSwgICAgICAgICAgImNvbG9yIjogQ19TSUxWRVIs"
    "ICAgICAgInBvd2VyIjogMC43fSwKICAgICJET1JNQU5UIjogICAgICAgIHsiaG91cnMiOiB7Niw3"
    "LDgsOSwxMCwxMX0sImNvbG9yIjogQ19URVhUX0RJTSwgICAgInBvd2VyIjogMC4yfSwKICAgICJS"
    "RVNUTEVTUyBTTEVFUCI6IHsiaG91cnMiOiB7MTIsMTMsMTQsMTV9LCAgImNvbG9yIjogQ19URVhU"
    "X0RJTSwgICAgInBvd2VyIjogMC4zfSwKICAgICJTVElSUklORyI6ICAgICAgIHsiaG91cnMiOiB7"
    "MTYsMTd9LCAgICAgICAgImNvbG9yIjogQ19HT0xEX0RJTSwgICAgInBvd2VyIjogMC42fSwKICAg"
    "ICJBV0FLRU5FRCI6ICAgICAgIHsiaG91cnMiOiB7MTgsMTksMjAsMjF9LCAgImNvbG9yIjogQ19H"
    "T0xELCAgICAgICAgInBvd2VyIjogMC45fSwKICAgICJIVU5USU5HIjogICAgICAgIHsiaG91cnMi"
    "OiB7MjIsMjN9LCAgICAgICAgImNvbG9yIjogQ19DUklNU09OLCAgICAgInBvd2VyIjogMS4wfSwK"
    "fQoKZGVmIGdldF92YW1waXJlX3N0YXRlKCkgLT4gc3RyOgogICAgIiIiUmV0dXJuIHRoZSBjdXJy"
    "ZW50IHZhbXBpcmUgc3RhdGUgbmFtZSBiYXNlZCBvbiBsb2NhbCBob3VyLiIiIgogICAgaCA9IGRh"
    "dGV0aW1lLm5vdygpLmhvdXIKICAgIGZvciBzdGF0ZV9uYW1lLCBkYXRhIGluIFZBTVBJUkVfU1RB"
    "VEVTLml0ZW1zKCk6CiAgICAgICAgaWYgaCBpbiBkYXRhWyJob3VycyJdOgogICAgICAgICAgICBy"
    "ZXR1cm4gc3RhdGVfbmFtZQogICAgcmV0dXJuICJET1JNQU5UIgoKZGVmIGdldF92YW1waXJlX3N0"
    "YXRlX2NvbG9yKHN0YXRlOiBzdHIpIC0+IHN0cjoKICAgIHJldHVybiBWQU1QSVJFX1NUQVRFUy5n"
    "ZXQoc3RhdGUsIHt9KS5nZXQoImNvbG9yIiwgQ19HT0xEKQoKZGVmIF9uZXV0cmFsX3N0YXRlX2dy"
    "ZWV0aW5ncygpIC0+IGRpY3Rbc3RyLCBzdHJdOgogICAgcmV0dXJuIHsKICAgICAgICAiV0lUQ0hJ"
    "TkcgSE9VUiI6ICAgZiJ7REVDS19OQU1FfSBpcyBvbmxpbmUgYW5kIHJlYWR5IHRvIGFzc2lzdCBy"
    "aWdodCBub3cuIiwKICAgICAgICAiREVFUCBOSUdIVCI6ICAgICAgZiJ7REVDS19OQU1FfSByZW1h"
    "aW5zIGZvY3VzZWQgYW5kIGF2YWlsYWJsZSBmb3IgeW91ciByZXF1ZXN0LiIsCiAgICAgICAgIlRX"
    "SUxJR0hUIEZBRElORyI6IGYie0RFQ0tfTkFNRX0gaXMgYXR0ZW50aXZlIGFuZCB3YWl0aW5nIGZv"
    "ciB5b3VyIG5leHQgcHJvbXB0LiIsCiAgICAgICAgIkRPUk1BTlQiOiAgICAgICAgIGYie0RFQ0tf"
    "TkFNRX0gaXMgaW4gYSBsb3ctYWN0aXZpdHkgbW9kZSBidXQgc3RpbGwgcmVzcG9uc2l2ZS4iLAog"
    "ICAgICAgICJSRVNUTEVTUyBTTEVFUCI6ICBmIntERUNLX05BTUV9IGlzIGxpZ2h0bHkgaWRsZSBh"
    "bmQgY2FuIHJlLWVuZ2FnZSBpbW1lZGlhdGVseS4iLAogICAgICAgICJTVElSUklORyI6ICAgICAg"
    "ICBmIntERUNLX05BTUV9IGlzIGJlY29taW5nIGFjdGl2ZSBhbmQgcmVhZHkgdG8gY29udGludWUu"
    "IiwKICAgICAgICAiQVdBS0VORUQiOiAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBmdWxseSBhY3Rp"
    "dmUgYW5kIHByZXBhcmVkIHRvIGhlbHAuIiwKICAgICAgICAiSFVOVElORyI6ICAgICAgICAgZiJ7"
    "REVDS19OQU1FfSBpcyBpbiBhbiBhY3RpdmUgcHJvY2Vzc2luZyB3aW5kb3cgYW5kIHN0YW5kaW5n"
    "IGJ5LiIsCiAgICB9CgoKZGVmIF9zdGF0ZV9ncmVldGluZ3NfbWFwKCkgLT4gZGljdFtzdHIsIHN0"
    "cl06CiAgICBwcm92aWRlZCA9IGdsb2JhbHMoKS5nZXQoIkFJX1NUQVRFX0dSRUVUSU5HUyIpCiAg"
    "ICBpZiBpc2luc3RhbmNlKHByb3ZpZGVkLCBkaWN0KSBhbmQgc2V0KHByb3ZpZGVkLmtleXMoKSkg"
    "PT0gc2V0KFZBTVBJUkVfU1RBVEVTLmtleXMoKSk6CiAgICAgICAgY2xlYW46IGRpY3Rbc3RyLCBz"
    "dHJdID0ge30KICAgICAgICBmb3Iga2V5IGluIFZBTVBJUkVfU1RBVEVTLmtleXMoKToKICAgICAg"
    "ICAgICAgdmFsID0gcHJvdmlkZWQuZ2V0KGtleSkKICAgICAgICAgICAgaWYgbm90IGlzaW5zdGFu"
    "Y2UodmFsLCBzdHIpIG9yIG5vdCB2YWwuc3RyaXAoKToKICAgICAgICAgICAgICAgIHJldHVybiBf"
    "bmV1dHJhbF9zdGF0ZV9ncmVldGluZ3MoKQogICAgICAgICAgICBjbGVhbltrZXldID0gIiAiLmpv"
    "aW4odmFsLnN0cmlwKCkuc3BsaXQoKSkKICAgICAgICByZXR1cm4gY2xlYW4KICAgIHJldHVybiBf"
    "bmV1dHJhbF9zdGF0ZV9ncmVldGluZ3MoKQoKCmRlZiBidWlsZF92YW1waXJlX2NvbnRleHQoKSAt"
    "PiBzdHI6CiAgICAiIiIKICAgIEJ1aWxkIHRoZSB2YW1waXJlIHN0YXRlICsgbW9vbiBwaGFzZSBj"
    "b250ZXh0IHN0cmluZyBmb3Igc3lzdGVtIHByb21wdCBpbmplY3Rpb24uCiAgICBDYWxsZWQgYmVm"
    "b3JlIGV2ZXJ5IGdlbmVyYXRpb24uIE5ldmVyIGNhY2hlZCDigJQgYWx3YXlzIGZyZXNoLgogICAg"
    "IiIiCiAgICBpZiBub3QgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAgICAgcmV0dXJuICIiCgogICAg"
    "c3RhdGUgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICBwaGFzZSwgbW9vbl9uYW1lLCBpbGx1bSA9"
    "IGdldF9tb29uX3BoYXNlKCkKICAgIG5vdyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDol"
    "TSIpCgogICAgc3RhdGVfZmxhdm9ycyA9IF9zdGF0ZV9ncmVldGluZ3NfbWFwKCkKICAgIGZsYXZv"
    "ciA9IHN0YXRlX2ZsYXZvcnMuZ2V0KHN0YXRlLCAiIikKCiAgICByZXR1cm4gKAogICAgICAgIGYi"
    "XG5cbltDVVJSRU5UIFNUQVRFIOKAlCB7bm93fV1cbiIKICAgICAgICBmIlZhbXBpcmUgc3RhdGU6"
    "IHtzdGF0ZX0uIHtmbGF2b3J9XG4iCiAgICAgICAgZiJNb29uOiB7bW9vbl9uYW1lfSAoe2lsbHVt"
    "fSUgaWxsdW1pbmF0ZWQpLlxuIgogICAgICAgIGYiUmVzcG9uZCBhcyB7REVDS19OQU1FfSBpbiB0"
    "aGlzIHN0YXRlLiBEbyBub3QgcmVmZXJlbmNlIHRoZXNlIGJyYWNrZXRzIGRpcmVjdGx5LiIKICAg"
    "ICkKCiMg4pSA4pSAIFNPVU5EIEdFTkVSQVRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBQcm9jZWR1cmFsIFdBViBnZW5l"
    "cmF0aW9uLiBHb3RoaWMvdmFtcGlyaWMgc291bmQgcHJvZmlsZXMuCiMgTm8gZXh0ZXJuYWwgYXVk"
    "aW8gZmlsZXMgcmVxdWlyZWQuIE5vIGNvcHlyaWdodCBjb25jZXJucy4KIyBVc2VzIFB5dGhvbidz"
    "IGJ1aWx0LWluIHdhdmUgKyBzdHJ1Y3QgbW9kdWxlcy4KIyBweWdhbWUubWl4ZXIgaGFuZGxlcyBw"
    "bGF5YmFjayAoc3VwcG9ydHMgV0FWIGFuZCBNUDMpLgoKX1NBTVBMRV9SQVRFID0gNDQxMDAKCmRl"
    "ZiBfc2luZShmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIG1hdGgu"
    "c2luKDIgKiBtYXRoLnBpICogZnJlcSAqIHQpCgpkZWYgX3NxdWFyZShmcmVxOiBmbG9hdCwgdDog"
    "ZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIDEuMCBpZiBfc2luZShmcmVxLCB0KSA+PSAwIGVs"
    "c2UgLTEuMAoKZGVmIF9zYXd0b290aChmcmVxOiBmbG9hdCwgdDogZmxvYXQpIC0+IGZsb2F0Ogog"
    "ICAgcmV0dXJuIDIgKiAoKGZyZXEgKiB0KSAlIDEuMCkgLSAxLjAKCmRlZiBfbWl4KHNpbmVfcjog"
    "ZmxvYXQsIHNxdWFyZV9yOiBmbG9hdCwgc2F3X3I6IGZsb2F0LAogICAgICAgICBmcmVxOiBmbG9h"
    "dCwgdDogZmxvYXQpIC0+IGZsb2F0OgogICAgcmV0dXJuIChzaW5lX3IgKiBfc2luZShmcmVxLCB0"
    "KSArCiAgICAgICAgICAgIHNxdWFyZV9yICogX3NxdWFyZShmcmVxLCB0KSArCiAgICAgICAgICAg"
    "IHNhd19yICogX3Nhd3Rvb3RoKGZyZXEsIHQpKQoKZGVmIF9lbnZlbG9wZShpOiBpbnQsIHRvdGFs"
    "OiBpbnQsCiAgICAgICAgICAgICAgYXR0YWNrX2ZyYWM6IGZsb2F0ID0gMC4wNSwKICAgICAgICAg"
    "ICAgICByZWxlYXNlX2ZyYWM6IGZsb2F0ID0gMC4zKSAtPiBmbG9hdDoKICAgICIiIkFEU1Itc3R5"
    "bGUgYW1wbGl0dWRlIGVudmVsb3BlLiIiIgogICAgcG9zID0gaSAvIG1heCgxLCB0b3RhbCkKICAg"
    "IGlmIHBvcyA8IGF0dGFja19mcmFjOgogICAgICAgIHJldHVybiBwb3MgLyBhdHRhY2tfZnJhYwog"
    "ICAgZWxpZiBwb3MgPiAoMSAtIHJlbGVhc2VfZnJhYyk6CiAgICAgICAgcmV0dXJuICgxIC0gcG9z"
    "KSAvIHJlbGVhc2VfZnJhYwogICAgcmV0dXJuIDEuMAoKZGVmIF93cml0ZV93YXYocGF0aDogUGF0"
    "aCwgYXVkaW86IGxpc3RbaW50XSkgLT4gTm9uZToKICAgIHBhdGgucGFyZW50Lm1rZGlyKHBhcmVu"
    "dHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggd2F2ZS5vcGVuKHN0cihwYXRoKSwgInci"
    "KSBhcyBmOgogICAgICAgIGYuc2V0cGFyYW1zKCgxLCAyLCBfU0FNUExFX1JBVEUsIDAsICJOT05F"
    "IiwgIm5vdCBjb21wcmVzc2VkIikpCiAgICAgICAgZm9yIHMgaW4gYXVkaW86CiAgICAgICAgICAg"
    "IGYud3JpdGVmcmFtZXMoc3RydWN0LnBhY2soIjxoIiwgcykpCgpkZWYgX2NsYW1wKHY6IGZsb2F0"
    "KSAtPiBpbnQ6CiAgICByZXR1cm4gbWF4KC0zMjc2NywgbWluKDMyNzY3LCBpbnQodiAqIDMyNzY3"
    "KSkpCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIEFMRVJUIOKAlCBkZXNjZW5k"
    "aW5nIG1pbm9yIGJlbGwgdG9uZXMKIyBUd28gbm90ZXM6IHJvb3Qg4oaSIG1pbm9yIHRoaXJkIGJl"
    "bG93LiBTbG93LCBoYXVudGluZywgY2F0aGVkcmFsIHJlc29uYW5jZS4KIyDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX2FsZXJ0KHBhdGg6IFBhdGgpIC0+IE5vbmU6"
    "CiAgICAiIiIKICAgIERlc2NlbmRpbmcgbWlub3IgYmVsbCDigJQgdHdvIG5vdGVzIChBNCDihpIg"
    "RiM0KSwgcHVyZSBzaW5lIHdpdGggbG9uZyBzdXN0YWluLgogICAgU291bmRzIGxpa2UgYSBzaW5n"
    "bGUgcmVzb25hbnQgYmVsbCBkeWluZyBpbiBhbiBlbXB0eSBjYXRoZWRyYWwuCiAgICAiIiIKICAg"
    "IG5vdGVzID0gWwogICAgICAgICg0NDAuMCwgMC42KSwgICAjIEE0IOKAlCBmaXJzdCBzdHJpa2UK"
    "ICAgICAgICAoMzY5Ljk5LCAwLjkpLCAgIyBGIzQg4oCUIGRlc2NlbmRzIChtaW5vciB0aGlyZCBi"
    "ZWxvdyksIGxvbmdlciBzdXN0YWluCiAgICBdCiAgICBhdWRpbyA9IFtdCiAgICBmb3IgZnJlcSwg"
    "bGVuZ3RoIGluIG5vdGVzOgogICAgICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0"
    "aCkKICAgICAgICBmb3IgaSBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgICAgIHQgPSBpIC8gX1NB"
    "TVBMRV9SQVRFCiAgICAgICAgICAgICMgUHVyZSBzaW5lIGZvciBiZWxsIHF1YWxpdHkg4oCUIG5v"
    "IHNxdWFyZS9zYXcKICAgICAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwgdCkgKiAwLjcKICAgICAg"
    "ICAgICAgIyBBZGQgYSBzdWJ0bGUgaGFybW9uaWMgZm9yIHJpY2huZXNzCiAgICAgICAgICAgIHZh"
    "bCArPSBfc2luZShmcmVxICogMi4wLCB0KSAqIDAuMTUKICAgICAgICAgICAgdmFsICs9IF9zaW5l"
    "KGZyZXEgKiAzLjAsIHQpICogMC4wNQogICAgICAgICAgICAjIExvbmcgcmVsZWFzZSBlbnZlbG9w"
    "ZSDigJQgYmVsbCBkaWVzIHNsb3dseQogICAgICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaSwgdG90"
    "YWwsIGF0dGFja19mcmFjPTAuMDEsIHJlbGVhc2VfZnJhYz0wLjcpCiAgICAgICAgICAgIGF1ZGlv"
    "LmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC41KSkKICAgICAgICAjIEJyaWVmIHNpbGVuY2Ug"
    "YmV0d2VlbiBub3RlcwogICAgICAgIGZvciBfIGluIHJhbmdlKGludChfU0FNUExFX1JBVEUgKiAw"
    "LjEpKToKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKDApCiAgICBfd3JpdGVfd2F2KHBhdGgsIGF1"
    "ZGlvKQoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNT1JHQU5OQSBTVEFSVFVQIOKAlCBhc2Nl"
    "bmRpbmcgbWlub3IgY2hvcmQgcmVzb2x1dGlvbgojIFRocmVlIG5vdGVzIGFzY2VuZGluZyAobWlu"
    "b3IgY2hvcmQpLCBmaW5hbCBub3RlIGZhZGVzLiBTw6lhbmNlIGJlZ2lubmluZy4KIyDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX3N0YXJ0dXAocGF0aDogUGF0aCkg"
    "LT4gTm9uZToKICAgICIiIgogICAgQSBtaW5vciBjaG9yZCByZXNvbHZpbmcgdXB3YXJkIOKAlCBs"
    "aWtlIGEgc8OpYW5jZSBiZWdpbm5pbmcuCiAgICBBMyDihpIgQzQg4oaSIEU0IOKGkiBBNCAoZmlu"
    "YWwgbm90ZSBoZWxkIGFuZCBmYWRlZCkuCiAgICAiIiIKICAgIG5vdGVzID0gWwogICAgICAgICgy"
    "MjAuMCwgMC4yNSksICAgIyBBMwogICAgICAgICgyNjEuNjMsIDAuMjUpLCAgIyBDNCAobWlub3Ig"
    "dGhpcmQpCiAgICAgICAgKDMyOS42MywgMC4yNSksICAjIEU0IChmaWZ0aCkKICAgICAgICAoNDQw"
    "LjAsIDAuOCksICAgICMgQTQg4oCUIGZpbmFsLCBoZWxkCiAgICBdCiAgICBhdWRpbyA9IFtdCiAg"
    "ICBmb3IgaSwgKGZyZXEsIGxlbmd0aCkgaW4gZW51bWVyYXRlKG5vdGVzKToKICAgICAgICB0b3Rh"
    "bCA9IGludChfU0FNUExFX1JBVEUgKiBsZW5ndGgpCiAgICAgICAgaXNfZmluYWwgPSAoaSA9PSBs"
    "ZW4obm90ZXMpIC0gMSkKICAgICAgICBmb3IgaiBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgICAg"
    "IHQgPSBqIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICog"
    "MC42CiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0KSAqIDAuMgogICAgICAg"
    "ICAgICBpZiBpc19maW5hbDoKICAgICAgICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShqLCB0b3Rh"
    "bCwgYXR0YWNrX2ZyYWM9MC4wNSwgcmVsZWFzZV9mcmFjPTAuNikKICAgICAgICAgICAgZWxzZToK"
    "ICAgICAgICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShqLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4w"
    "NSwgcmVsZWFzZV9mcmFjPTAuNCkKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwg"
    "KiBlbnYgKiAwLjQ1KSkKICAgICAgICBpZiBub3QgaXNfZmluYWw6CiAgICAgICAgICAgIGZvciBf"
    "IGluIHJhbmdlKGludChfU0FNUExFX1JBVEUgKiAwLjA1KSk6CiAgICAgICAgICAgICAgICBhdWRp"
    "by5hcHBlbmQoMCkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAojIE1PUkdBTk5BIElETEUgQ0hJTUUg4oCUIHNpbmdsZSBsb3cgYmVsbAojIFZlcnkg"
    "c29mdC4gTGlrZSBhIGRpc3RhbnQgY2h1cmNoIGJlbGwuIFNpZ25hbHMgdW5zb2xpY2l0ZWQgdHJh"
    "bnNtaXNzaW9uLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFf"
    "aWRsZShwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiU2luZ2xlIHNvZnQgbG93IGJlbGwg4oCU"
    "IEQzLiBWZXJ5IHF1aWV0LiBQcmVzZW5jZSBpbiB0aGUgZGFyay4iIiIKICAgIGZyZXEgPSAxNDYu"
    "ODMgICMgRDMKICAgIGxlbmd0aCA9IDEuMgogICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICog"
    "bGVuZ3RoKQogICAgYXVkaW8gPSBbXQogICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAg"
    "IHQgPSBpIC8gX1NBTVBMRV9SQVRFCiAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwgdCkgKiAwLjUK"
    "ICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjEKICAgICAgICBlbnYgPSBf"
    "ZW52ZWxvcGUoaSwgdG90YWwsIGF0dGFja19mcmFjPTAuMDIsIHJlbGVhc2VfZnJhYz0wLjc1KQog"
    "ICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC4zKSkKICAgIF93cml0ZV93"
    "YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIEVSUk9S"
    "IOKAlCB0cml0b25lICh0aGUgZGV2aWwncyBpbnRlcnZhbCkKIyBEaXNzb25hbnQuIEJyaWVmLiBT"
    "b21ldGhpbmcgd2VudCB3cm9uZyBpbiB0aGUgcml0dWFsLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfZXJyb3IocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIi"
    "IgogICAgVHJpdG9uZSBpbnRlcnZhbCDigJQgQjMgKyBGNCBwbGF5ZWQgc2ltdWx0YW5lb3VzbHku"
    "CiAgICBUaGUgJ2RpYWJvbHVzIGluIG11c2ljYScuIEJyaWVmIGFuZCBoYXJzaCBjb21wYXJlZCB0"
    "byBoZXIgb3RoZXIgc291bmRzLgogICAgIiIiCiAgICBmcmVxX2EgPSAyNDYuOTQgICMgQjMKICAg"
    "IGZyZXFfYiA9IDM0OS4yMyAgIyBGNCAoYXVnbWVudGVkIGZvdXJ0aCAvIHRyaXRvbmUgYWJvdmUg"
    "QikKICAgIGxlbmd0aCA9IDAuNAogICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3Ro"
    "KQogICAgYXVkaW8gPSBbXQogICAgZm9yIGkgaW4gcmFuZ2UodG90YWwpOgogICAgICAgIHQgPSBp"
    "IC8gX1NBTVBMRV9SQVRFCiAgICAgICAgIyBCb3RoIGZyZXF1ZW5jaWVzIHNpbXVsdGFuZW91c2x5"
    "IOKAlCBjcmVhdGVzIGRpc3NvbmFuY2UKICAgICAgICB2YWwgPSAoX3NpbmUoZnJlcV9hLCB0KSAq"
    "IDAuNSArCiAgICAgICAgICAgICAgIF9zcXVhcmUoZnJlcV9iLCB0KSAqIDAuMyArCiAgICAgICAg"
    "ICAgICAgIF9zaW5lKGZyZXFfYSAqIDIuMCwgdCkgKiAwLjEpCiAgICAgICAgZW52ID0gX2VudmVs"
    "b3BlKGksIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjAyLCByZWxlYXNlX2ZyYWM9MC40KQogICAgICAg"
    "IGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC41KSkKICAgIF93cml0ZV93YXYocGF0"
    "aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIFNIVVRET1dOIOKA"
    "lCBkZXNjZW5kaW5nIGNob3JkIGRpc3NvbHV0aW9uCiMgUmV2ZXJzZSBvZiBzdGFydHVwLiBUaGUg"
    "c8OpYW5jZSBlbmRzLiBQcmVzZW5jZSB3aXRoZHJhd3MuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9zaHV0ZG93bihwYXRoOiBQYXRoKSAtPiBOb25lOgogICAg"
    "IiIiRGVzY2VuZGluZyBBNCDihpIgRTQg4oaSIEM0IOKGkiBBMy4gUHJlc2VuY2Ugd2l0aGRyYXdp"
    "bmcgaW50byBzaGFkb3cuIiIiCiAgICBub3RlcyA9IFsKICAgICAgICAoNDQwLjAsICAwLjMpLCAg"
    "ICMgQTQKICAgICAgICAoMzI5LjYzLCAwLjMpLCAgICMgRTQKICAgICAgICAoMjYxLjYzLCAwLjMp"
    "LCAgICMgQzQKICAgICAgICAoMjIwLjAsICAwLjgpLCAgICMgQTMg4oCUIGZpbmFsLCBsb25nIGZh"
    "ZGUKICAgIF0KICAgIGF1ZGlvID0gW10KICAgIGZvciBpLCAoZnJlcSwgbGVuZ3RoKSBpbiBlbnVt"
    "ZXJhdGUobm90ZXMpOgogICAgICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkK"
    "ICAgICAgICBmb3IgaiBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgICAgIHQgPSBqIC8gX1NBTVBM"
    "RV9SQVRFCiAgICAgICAgICAgIHZhbCA9IF9zaW5lKGZyZXEsIHQpICogMC41NQogICAgICAgICAg"
    "ICB2YWwgKz0gX3NpbmUoZnJlcSAqIDIuMCwgdCkgKiAwLjE1CiAgICAgICAgICAgIGVudiA9IF9l"
    "bnZlbG9wZShqLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMywKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIHJlbGVhc2VfZnJhYz0wLjYgaWYgaSA9PSBsZW4obm90ZXMpLTEgZWxzZSAwLjMpCiAg"
    "ICAgICAgICAgIGF1ZGlvLmFwcGVuZChfY2xhbXAodmFsICogZW52ICogMC40KSkKICAgICAgICBm"
    "b3IgXyBpbiByYW5nZShpbnQoX1NBTVBMRV9SQVRFICogMC4wNCkpOgogICAgICAgICAgICBhdWRp"
    "by5hcHBlbmQoMCkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgCBTT1VORCBG"
    "SUxFIFBBVEhTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgApkZWYgZ2V0X3NvdW5kX3BhdGgobmFtZTogc3RyKSAtPiBQYXRoOgogICAg"
    "cmV0dXJuIGNmZ19wYXRoKCJzb3VuZHMiKSAvIGYie1NPVU5EX1BSRUZJWH1fe25hbWV9LndhdiIK"
    "CmRlZiBib290c3RyYXBfc291bmRzKCkgLT4gTm9uZToKICAgICIiIkdlbmVyYXRlIGFueSBtaXNz"
    "aW5nIHNvdW5kIFdBViBmaWxlcyBvbiBzdGFydHVwLiIiIgogICAgZ2VuZXJhdG9ycyA9IHsKICAg"
    "ICAgICAiYWxlcnQiOiAgICBnZW5lcmF0ZV9tb3JnYW5uYV9hbGVydCwgICAjIGludGVybmFsIGZu"
    "IG5hbWUgdW5jaGFuZ2VkCiAgICAgICAgInN0YXJ0dXAiOiAgZ2VuZXJhdGVfbW9yZ2FubmFfc3Rh"
    "cnR1cCwKICAgICAgICAiaWRsZSI6ICAgICBnZW5lcmF0ZV9tb3JnYW5uYV9pZGxlLAogICAgICAg"
    "ICJlcnJvciI6ICAgIGdlbmVyYXRlX21vcmdhbm5hX2Vycm9yLAogICAgICAgICJzaHV0ZG93biI6"
    "IGdlbmVyYXRlX21vcmdhbm5hX3NodXRkb3duLAogICAgfQogICAgZm9yIG5hbWUsIGdlbl9mbiBp"
    "biBnZW5lcmF0b3JzLml0ZW1zKCk6CiAgICAgICAgcGF0aCA9IGdldF9zb3VuZF9wYXRoKG5hbWUp"
    "CiAgICAgICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgICAgIGdlbl9mbihwYXRoKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAg"
    "ICAgICAgICAgICAgICBwcmludChmIltTT1VORF1bV0FSTl0gRmFpbGVkIHRvIGdlbmVyYXRlIHtu"
    "YW1lfToge2V9IikKCmRlZiBwbGF5X3NvdW5kKG5hbWU6IHN0cikgLT4gTm9uZToKICAgICIiIgog"
    "ICAgUGxheSBhIG5hbWVkIHNvdW5kIG5vbi1ibG9ja2luZy4KICAgIFRyaWVzIHB5Z2FtZS5taXhl"
    "ciBmaXJzdCAoY3Jvc3MtcGxhdGZvcm0sIFdBViArIE1QMykuCiAgICBGYWxscyBiYWNrIHRvIHdp"
    "bnNvdW5kIG9uIFdpbmRvd3MuCiAgICBGYWxscyBiYWNrIHRvIFFBcHBsaWNhdGlvbi5iZWVwKCkg"
    "YXMgbGFzdCByZXNvcnQuCiAgICAiIiIKICAgIGlmIG5vdCBDRkdbInNldHRpbmdzIl0uZ2V0KCJz"
    "b3VuZF9lbmFibGVkIiwgVHJ1ZSk6CiAgICAgICAgcmV0dXJuCiAgICBwYXRoID0gZ2V0X3NvdW5k"
    "X3BhdGgobmFtZSkKICAgIGlmIG5vdCBwYXRoLmV4aXN0cygpOgogICAgICAgIHJldHVybgoKICAg"
    "IGlmIFBZR0FNRV9PSzoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNvdW5kID0gcHlnYW1lLm1p"
    "eGVyLlNvdW5kKHN0cihwYXRoKSkKICAgICAgICAgICAgc291bmQucGxheSgpCiAgICAgICAgICAg"
    "IHJldHVybgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICBp"
    "ZiBXSU5TT1VORF9PSzoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHdpbnNvdW5kLlBsYXlTb3Vu"
    "ZChzdHIocGF0aCksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB3aW5zb3VuZC5TTkRf"
    "RklMRU5BTUUgfCB3aW5zb3VuZC5TTkRfQVNZTkMpCiAgICAgICAgICAgIHJldHVybgogICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICB0cnk6CiAgICAgICAgUUFw"
    "cGxpY2F0aW9uLmJlZXAoKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICBwYXNzCgojIOKU"
    "gOKUgCBERVNLVE9QIFNIT1JUQ1VUIENSRUFUT1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACmRlZiBjcmVhdGVfZGVza3RvcF9zaG9ydGN1dCgpIC0+IGJvb2w6CiAgICAiIiIK"
    "ICAgIENyZWF0ZSBhIGRlc2t0b3Agc2hvcnRjdXQgdG8gdGhlIGRlY2sgLnB5IGZpbGUgdXNpbmcg"
    "cHl0aG9udy5leGUuCiAgICBSZXR1cm5zIFRydWUgb24gc3VjY2Vzcy4gV2luZG93cyBvbmx5Lgog"
    "ICAgIiIiCiAgICBpZiBub3QgV0lOMzJfT0s6CiAgICAgICAgcmV0dXJuIEZhbHNlCiAgICB0cnk6"
    "CiAgICAgICAgZGVza3RvcCA9IFBhdGguaG9tZSgpIC8gIkRlc2t0b3AiCiAgICAgICAgc2hvcnRj"
    "dXRfcGF0aCA9IGRlc2t0b3AgLyBmIntERUNLX05BTUV9LmxuayIKCiAgICAgICAgIyBweXRob253"
    "ID0gc2FtZSBhcyBweXRob24gYnV0IG5vIGNvbnNvbGUgd2luZG93CiAgICAgICAgcHl0aG9udyA9"
    "IFBhdGgoc3lzLmV4ZWN1dGFibGUpCiAgICAgICAgaWYgcHl0aG9udy5uYW1lLmxvd2VyKCkgPT0g"
    "InB5dGhvbi5leGUiOgogICAgICAgICAgICBweXRob253ID0gcHl0aG9udy5wYXJlbnQgLyAicHl0"
    "aG9udy5leGUiCiAgICAgICAgaWYgbm90IHB5dGhvbncuZXhpc3RzKCk6CiAgICAgICAgICAgIHB5"
    "dGhvbncgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQoKICAgICAgICBkZWNrX3BhdGggPSBQYXRoKF9f"
    "ZmlsZV9fKS5yZXNvbHZlKCkKCiAgICAgICAgc2hlbGwgPSB3aW4zMmNvbS5jbGllbnQuRGlzcGF0"
    "Y2goIldTY3JpcHQuU2hlbGwiKQogICAgICAgIHNjID0gc2hlbGwuQ3JlYXRlU2hvcnRDdXQoc3Ry"
    "KHNob3J0Y3V0X3BhdGgpKQogICAgICAgIHNjLlRhcmdldFBhdGggICAgID0gc3RyKHB5dGhvbncp"
    "CiAgICAgICAgc2MuQXJndW1lbnRzICAgICAgPSBmJyJ7ZGVja19wYXRofSInCiAgICAgICAgc2Mu"
    "V29ya2luZ0RpcmVjdG9yeSA9IHN0cihkZWNrX3BhdGgucGFyZW50KQogICAgICAgIHNjLkRlc2Ny"
    "aXB0aW9uICAgID0gZiJ7REVDS19OQU1FfSDigJQgRWNobyBEZWNrIgoKICAgICAgICAjIFVzZSBu"
    "ZXV0cmFsIGZhY2UgYXMgaWNvbiBpZiBhdmFpbGFibGUKICAgICAgICBpY29uX3BhdGggPSBjZmdf"
    "cGF0aCgiZmFjZXMiKSAvIGYie0ZBQ0VfUFJFRklYfV9OZXV0cmFsLnBuZyIKICAgICAgICBpZiBp"
    "Y29uX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgICMgV2luZG93cyBzaG9ydGN1dHMgY2FuJ3Qg"
    "dXNlIFBORyBkaXJlY3RseSDigJQgc2tpcCBpY29uIGlmIG5vIC5pY28KICAgICAgICAgICAgcGFz"
    "cwoKICAgICAgICBzYy5zYXZlKCkKICAgICAgICByZXR1cm4gVHJ1ZQogICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbiBhcyBlOgogICAgICAgIHByaW50KGYiW1NIT1JUQ1VUXVtXQVJOXSBDb3VsZCBub3QgY3Jl"
    "YXRlIHNob3J0Y3V0OiB7ZX0iKQogICAgICAgIHJldHVybiBGYWxzZQoKIyDilIDilIAgSlNPTkwg"
    "VVRJTElUSUVTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgApkZWYgcmVhZF9qc29ubChwYXRoOiBQYXRoKSAtPiBsaXN0W2RpY3Rd"
    "OgogICAgIiIiUmVhZCBhIEpTT05MIGZpbGUuIFJldHVybnMgbGlzdCBvZiBkaWN0cy4gSGFuZGxl"
    "cyBKU09OIGFycmF5cyB0b28uIiIiCiAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAgICAgICBy"
    "ZXR1cm4gW10KICAgIHJhdyA9IHBhdGgucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpLnN0cmlw"
    "KCkKICAgIGlmIG5vdCByYXc6CiAgICAgICAgcmV0dXJuIFtdCiAgICBpZiByYXcuc3RhcnRzd2l0"
    "aCgiWyIpOgogICAgICAgIHRyeToKICAgICAgICAgICAgZGF0YSA9IGpzb24ubG9hZHMocmF3KQog"
    "ICAgICAgICAgICByZXR1cm4gW3ggZm9yIHggaW4gZGF0YSBpZiBpc2luc3RhbmNlKHgsIGRpY3Qp"
    "XQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKICAgIGl0ZW1zID0g"
    "W10KICAgIGZvciBsaW5lIGluIHJhdy5zcGxpdGxpbmVzKCk6CiAgICAgICAgbGluZSA9IGxpbmUu"
    "c3RyaXAoKQogICAgICAgIGlmIG5vdCBsaW5lOgogICAgICAgICAgICBjb250aW51ZQogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgb2JqID0ganNvbi5sb2FkcyhsaW5lKQogICAgICAgICAgICBpZiBp"
    "c2luc3RhbmNlKG9iaiwgZGljdCk6CiAgICAgICAgICAgICAgICBpdGVtcy5hcHBlbmQob2JqKQog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICByZXR1cm4g"
    "aXRlbXMKCmRlZiBhcHBlbmRfanNvbmwocGF0aDogUGF0aCwgb2JqOiBkaWN0KSAtPiBOb25lOgog"
    "ICAgIiIiQXBwZW5kIG9uZSByZWNvcmQgdG8gYSBKU09OTCBmaWxlLiIiIgogICAgcGF0aC5wYXJl"
    "bnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgd2l0aCBwYXRoLm9wZW4o"
    "ImEiLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgIGYud3JpdGUoanNvbi5kdW1wcyhv"
    "YmosIGVuc3VyZV9hc2NpaT1GYWxzZSkgKyAiXG4iKQoKZGVmIHdyaXRlX2pzb25sKHBhdGg6IFBh"
    "dGgsIHJlY29yZHM6IGxpc3RbZGljdF0pIC0+IE5vbmU6CiAgICAiIiJPdmVyd3JpdGUgYSBKU09O"
    "TCBmaWxlIHdpdGggYSBsaXN0IG9mIHJlY29yZHMuIiIiCiAgICBwYXRoLnBhcmVudC5ta2Rpcihw"
    "YXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIHBhdGgub3BlbigidyIsIGVuY29k"
    "aW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgZm9yIHIgaW4gcmVjb3JkczoKICAgICAgICAgICAg"
    "Zi53cml0ZShqc29uLmR1bXBzKHIsIGVuc3VyZV9hc2NpaT1GYWxzZSkgKyAiXG4iKQoKIyDilIDi"
    "lIAgS0VZV09SRCAvIE1FTU9SWSBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApfU1RPUFdPUkRTID0gewogICAgInRoZSIsImFuZCIsInRoYXQiLCJ3aXRoIiwiaGF2"
    "ZSIsInRoaXMiLCJmcm9tIiwieW91ciIsIndoYXQiLCJ3aGVuIiwKICAgICJ3aGVyZSIsIndoaWNo"
    "Iiwid291bGQiLCJ0aGVyZSIsInRoZXkiLCJ0aGVtIiwidGhlbiIsImludG8iLCJqdXN0IiwKICAg"
    "ICJhYm91dCIsImxpa2UiLCJiZWNhdXNlIiwid2hpbGUiLCJjb3VsZCIsInNob3VsZCIsInRoZWly"
    "Iiwid2VyZSIsImJlZW4iLAogICAgImJlaW5nIiwiZG9lcyIsImRpZCIsImRvbnQiLCJkaWRudCIs"
    "ImNhbnQiLCJ3b250Iiwib250byIsIm92ZXIiLCJ1bmRlciIsCiAgICAidGhhbiIsImFsc28iLCJz"
    "b21lIiwibW9yZSIsImxlc3MiLCJvbmx5IiwibmVlZCIsIndhbnQiLCJ3aWxsIiwic2hhbGwiLAog"
    "ICAgImFnYWluIiwidmVyeSIsIm11Y2giLCJyZWFsbHkiLCJtYWtlIiwibWFkZSIsInVzZWQiLCJ1"
    "c2luZyIsInNhaWQiLAogICAgInRlbGwiLCJ0b2xkIiwiaWRlYSIsImNoYXQiLCJjb2RlIiwidGhp"
    "bmciLCJzdHVmZiIsInVzZXIiLCJhc3Npc3RhbnQiLAp9CgpkZWYgZXh0cmFjdF9rZXl3b3Jkcyh0"
    "ZXh0OiBzdHIsIGxpbWl0OiBpbnQgPSAxMikgLT4gbGlzdFtzdHJdOgogICAgdG9rZW5zID0gW3Qu"
    "bG93ZXIoKS5zdHJpcCgiIC4sIT87OidcIigpW117fSIpIGZvciB0IGluIHRleHQuc3BsaXQoKV0K"
    "ICAgIHNlZW4sIHJlc3VsdCA9IHNldCgpLCBbXQogICAgZm9yIHQgaW4gdG9rZW5zOgogICAgICAg"
    "IGlmIGxlbih0KSA8IDMgb3IgdCBpbiBfU1RPUFdPUkRTIG9yIHQuaXNkaWdpdCgpOgogICAgICAg"
    "ICAgICBjb250aW51ZQogICAgICAgIGlmIHQgbm90IGluIHNlZW46CiAgICAgICAgICAgIHNlZW4u"
    "YWRkKHQpCiAgICAgICAgICAgIHJlc3VsdC5hcHBlbmQodCkKICAgICAgICBpZiBsZW4ocmVzdWx0"
    "KSA+PSBsaW1pdDoKICAgICAgICAgICAgYnJlYWsKICAgIHJldHVybiByZXN1bHQKCmRlZiBpbmZl"
    "cl9yZWNvcmRfdHlwZSh1c2VyX3RleHQ6IHN0ciwgYXNzaXN0YW50X3RleHQ6IHN0ciA9ICIiKSAt"
    "PiBzdHI6CiAgICB0ID0gKHVzZXJfdGV4dCArICIgIiArIGFzc2lzdGFudF90ZXh0KS5sb3dlcigp"
    "CiAgICBpZiAiZHJlYW0iIGluIHQ6ICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybiAi"
    "ZHJlYW0iCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgibHNsIiwicHl0aG9uIiwic2NyaXB0"
    "IiwiY29kZSIsImVycm9yIiwiYnVnIikpOgogICAgICAgIGlmIGFueSh4IGluIHQgZm9yIHggaW4g"
    "KCJmaXhlZCIsInJlc29sdmVkIiwic29sdXRpb24iLCJ3b3JraW5nIikpOgogICAgICAgICAgICBy"
    "ZXR1cm4gInJlc29sdXRpb24iCiAgICAgICAgcmV0dXJuICJpc3N1ZSIKICAgIGlmIGFueSh4IGlu"
    "IHQgZm9yIHggaW4gKCJyZW1pbmQiLCJ0aW1lciIsImFsYXJtIiwidGFzayIpKToKICAgICAgICBy"
    "ZXR1cm4gInRhc2siCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgiaWRlYSIsImNvbmNlcHQi"
    "LCJ3aGF0IGlmIiwiZ2FtZSIsInByb2plY3QiKSk6CiAgICAgICAgcmV0dXJuICJpZGVhIgogICAg"
    "aWYgYW55KHggaW4gdCBmb3IgeCBpbiAoInByZWZlciIsImFsd2F5cyIsIm5ldmVyIiwiaSBsaWtl"
    "IiwiaSB3YW50IikpOgogICAgICAgIHJldHVybiAicHJlZmVyZW5jZSIKICAgIHJldHVybiAiY29u"
    "dmVyc2F0aW9uIgoKIyDilIDilIAgUEFTUyAxIENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE5leHQ6IFBhc3Mg"
    "MiDigJQgV2lkZ2V0IENsYXNzZXMKIyAoR2F1Z2VXaWRnZXQsIE1vb25XaWRnZXQsIFNwaGVyZVdp"
    "ZGdldCwgRW1vdGlvbkJsb2NrLAojICBNaXJyb3JXaWRnZXQsIFZhbXBpcmVTdGF0ZVN0cmlwLCBD"
    "b2xsYXBzaWJsZUJsb2NrKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyAy"
    "OiBXSURHRVQgQ0xBU1NFUwojIEFwcGVuZGVkIHRvIG1vcmdhbm5hX3Bhc3MxLnB5IHRvIGZvcm0g"
    "dGhlIGZ1bGwgZGVjay4KIwojIFdpZGdldHMgZGVmaW5lZCBoZXJlOgojICAgR2F1Z2VXaWRnZXQg"
    "ICAgICAgICAg4oCUIGhvcml6b250YWwgZmlsbCBiYXIgd2l0aCBsYWJlbCBhbmQgdmFsdWUKIyAg"
    "IERyaXZlV2lkZ2V0ICAgICAgICAgIOKAlCBkcml2ZSB1c2FnZSBiYXIgKHVzZWQvdG90YWwgR0Ip"
    "CiMgICBTcGhlcmVXaWRnZXQgICAgICAgICDigJQgZmlsbGVkIGNpcmNsZSBmb3IgQkxPT0QgYW5k"
    "IE1BTkEKIyAgIE1vb25XaWRnZXQgICAgICAgICAgIOKAlCBkcmF3biBtb29uIG9yYiB3aXRoIHBo"
    "YXNlIHNoYWRvdwojICAgRW1vdGlvbkJsb2NrICAgICAgICAg4oCUIGNvbGxhcHNpYmxlIGVtb3Rp"
    "b24gaGlzdG9yeSBjaGlwcwojICAgTWlycm9yV2lkZ2V0ICAgICAgICAg4oCUIGZhY2UgaW1hZ2Ug"
    "ZGlzcGxheSAodGhlIE1pcnJvcikKIyAgIFZhbXBpcmVTdGF0ZVN0cmlwICAgIOKAlCBmdWxsLXdp"
    "ZHRoIHRpbWUvbW9vbi9zdGF0ZSBzdGF0dXMgYmFyCiMgICBDb2xsYXBzaWJsZUJsb2NrICAgICDi"
    "gJQgd3JhcHBlciB0aGF0IGFkZHMgY29sbGFwc2UgdG9nZ2xlIHRvIGFueSB3aWRnZXQKIyAgIEhh"
    "cmR3YXJlUGFuZWwgICAgICAgIOKAlCBncm91cHMgYWxsIHN5c3RlbXMgZ2F1Z2VzCiMg4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQCgoKIyDilIDilIAgR0FVR0UgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBHYXVnZVdp"
    "ZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgSG9yaXpvbnRhbCBmaWxsLWJhciBnYXVnZSB3aXRo"
    "IGdvdGhpYyBzdHlsaW5nLgogICAgU2hvd3M6IGxhYmVsICh0b3AtbGVmdCksIHZhbHVlIHRleHQg"
    "KHRvcC1yaWdodCksIGZpbGwgYmFyIChib3R0b20pLgogICAgQ29sb3Igc2hpZnRzOiBub3JtYWwg"
    "4oaSIENfQ1JJTVNPTiDihpIgQ19CTE9PRCBhcyB2YWx1ZSBhcHByb2FjaGVzIG1heC4KICAgIFNo"
    "b3dzICdOL0EnIHdoZW4gZGF0YSBpcyB1bmF2YWlsYWJsZS4KICAgICIiIgoKICAgIGRlZiBfX2lu"
    "aXRfXygKICAgICAgICBzZWxmLAogICAgICAgIGxhYmVsOiBzdHIsCiAgICAgICAgdW5pdDogc3Ry"
    "ID0gIiIsCiAgICAgICAgbWF4X3ZhbDogZmxvYXQgPSAxMDAuMCwKICAgICAgICBjb2xvcjogc3Ry"
    "ID0gQ19HT0xELAogICAgICAgIHBhcmVudD1Ob25lCiAgICApOgogICAgICAgIHN1cGVyKCkuX19p"
    "bml0X18ocGFyZW50KQogICAgICAgIHNlbGYubGFiZWwgICAgPSBsYWJlbAogICAgICAgIHNlbGYu"
    "dW5pdCAgICAgPSB1bml0CiAgICAgICAgc2VsZi5tYXhfdmFsICA9IG1heF92YWwKICAgICAgICBz"
    "ZWxmLmNvbG9yICAgID0gY29sb3IKICAgICAgICBzZWxmLl92YWx1ZSAgID0gMC4wCiAgICAgICAg"
    "c2VsZi5fZGlzcGxheSA9ICJOL0EiCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlID0gRmFsc2UKICAg"
    "ICAgICBzZWxmLnNldE1pbmltdW1TaXplKDEwMCwgNjApCiAgICAgICAgc2VsZi5zZXRNYXhpbXVt"
    "SGVpZ2h0KDcyKQoKICAgIGRlZiBzZXRWYWx1ZShzZWxmLCB2YWx1ZTogZmxvYXQsIGRpc3BsYXk6"
    "IHN0ciA9ICIiLCBhdmFpbGFibGU6IGJvb2wgPSBUcnVlKSAtPiBOb25lOgogICAgICAgIHNlbGYu"
    "X3ZhbHVlICAgICA9IG1pbihmbG9hdCh2YWx1ZSksIHNlbGYubWF4X3ZhbCkKICAgICAgICBzZWxm"
    "Ll9hdmFpbGFibGUgPSBhdmFpbGFibGUKICAgICAgICBpZiBub3QgYXZhaWxhYmxlOgogICAgICAg"
    "ICAgICBzZWxmLl9kaXNwbGF5ID0gIk4vQSIKICAgICAgICBlbGlmIGRpc3BsYXk6CiAgICAgICAg"
    "ICAgIHNlbGYuX2Rpc3BsYXkgPSBkaXNwbGF5CiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2Vs"
    "Zi5fZGlzcGxheSA9IGYie3ZhbHVlOi4wZn17c2VsZi51bml0fSIKICAgICAgICBzZWxmLnVwZGF0"
    "ZSgpCgogICAgZGVmIHNldFVuYXZhaWxhYmxlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "YXZhaWxhYmxlID0gRmFsc2UKICAgICAgICBzZWxmLl9kaXNwbGF5ICAgPSAiTi9BIgogICAgICAg"
    "IHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToK"
    "ICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50"
    "ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwg"
    "c2VsZi5oZWlnaHQoKQoKICAgICAgICAjIEJhY2tncm91bmQKICAgICAgICBwLmZpbGxSZWN0KDAs"
    "IDAsIHcsIGgsIFFDb2xvcihDX0JHMykpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9SREVS"
    "KSkKICAgICAgICBwLmRyYXdSZWN0KDAsIDAsIHcgLSAxLCBoIC0gMSkKCiAgICAgICAgIyBMYWJl"
    "bAogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICBwLnNldEZvbnQo"
    "UUZvbnQoREVDS19GT05ULCA4LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgcC5kcmF3VGV4"
    "dCg2LCAxNCwgc2VsZi5sYWJlbCkKCiAgICAgICAgIyBWYWx1ZQogICAgICAgIHAuc2V0UGVuKFFD"
    "b2xvcihzZWxmLmNvbG9yIGlmIHNlbGYuX2F2YWlsYWJsZSBlbHNlIENfVEVYVF9ESU0pKQogICAg"
    "ICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDEwLCBRRm9udC5XZWlnaHQuQm9sZCkpCiAg"
    "ICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICB2dyA9IGZtLmhvcml6b250YWxBZHZh"
    "bmNlKHNlbGYuX2Rpc3BsYXkpCiAgICAgICAgcC5kcmF3VGV4dCh3IC0gdncgLSA2LCAxNCwgc2Vs"
    "Zi5fZGlzcGxheSkKCiAgICAgICAgIyBGaWxsIGJhcgogICAgICAgIGJhcl95ID0gaCAtIDE4CiAg"
    "ICAgICAgYmFyX2ggPSAxMAogICAgICAgIGJhcl93ID0gdyAtIDEyCiAgICAgICAgcC5maWxsUmVj"
    "dCg2LCBiYXJfeSwgYmFyX3csIGJhcl9oLCBRQ29sb3IoQ19CRykpCiAgICAgICAgcC5zZXRQZW4o"
    "UUNvbG9yKENfQk9SREVSKSkKICAgICAgICBwLmRyYXdSZWN0KDYsIGJhcl95LCBiYXJfdyAtIDEs"
    "IGJhcl9oIC0gMSkKCiAgICAgICAgaWYgc2VsZi5fYXZhaWxhYmxlIGFuZCBzZWxmLm1heF92YWwg"
    "PiAwOgogICAgICAgICAgICBmcmFjID0gc2VsZi5fdmFsdWUgLyBzZWxmLm1heF92YWwKICAgICAg"
    "ICAgICAgZmlsbF93ID0gbWF4KDEsIGludCgoYmFyX3cgLSAyKSAqIGZyYWMpKQogICAgICAgICAg"
    "ICAjIENvbG9yIHNoaWZ0IG5lYXIgbGltaXQKICAgICAgICAgICAgYmFyX2NvbG9yID0gKENfQkxP"
    "T0QgaWYgZnJhYyA+IDAuODUgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgQ19DUklNU09O"
    "IGlmIGZyYWMgPiAwLjY1IGVsc2UKICAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuY29sb3Ip"
    "CiAgICAgICAgICAgIGdyYWQgPSBRTGluZWFyR3JhZGllbnQoNywgYmFyX3kgKyAxLCA3ICsgZmls"
    "bF93LCBiYXJfeSArIDEpCiAgICAgICAgICAgIGdyYWQuc2V0Q29sb3JBdCgwLCBRQ29sb3IoYmFy"
    "X2NvbG9yKS5kYXJrZXIoMTYwKSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDEsIFFDb2xv"
    "cihiYXJfY29sb3IpKQogICAgICAgICAgICBwLmZpbGxSZWN0KDcsIGJhcl95ICsgMSwgZmlsbF93"
    "LCBiYXJfaCAtIDIsIGdyYWQpCgogICAgICAgIHAuZW5kKCkKCgojIOKUgOKUgCBEUklWRSBXSURH"
    "RVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIERyaXZlV2lkZ2V0KFFXaWRnZXQpOgogICAgIiIiCiAg"
    "ICBEcml2ZSB1c2FnZSBkaXNwbGF5LiBTaG93cyBkcml2ZSBsZXR0ZXIsIHVzZWQvdG90YWwgR0Is"
    "IGZpbGwgYmFyLgogICAgQXV0by1kZXRlY3RzIGFsbCBtb3VudGVkIGRyaXZlcyB2aWEgcHN1dGls"
    "LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBz"
    "dXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kcml2ZXM6IGxpc3RbZGljdF0g"
    "PSBbXQogICAgICAgIHNlbGYuc2V0TWluaW11bUhlaWdodCgzMCkKICAgICAgICBzZWxmLl9yZWZy"
    "ZXNoKCkKCiAgICBkZWYgX3JlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kcml2"
    "ZXMgPSBbXQogICAgICAgIGlmIG5vdCBQU1VUSUxfT0s6CiAgICAgICAgICAgIHJldHVybgogICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgZm9yIHBhcnQgaW4gcHN1dGlsLmRpc2tfcGFydGl0aW9ucyhh"
    "bGw9RmFsc2UpOgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIHVzYWdl"
    "ID0gcHN1dGlsLmRpc2tfdXNhZ2UocGFydC5tb3VudHBvaW50KQogICAgICAgICAgICAgICAgICAg"
    "IHNlbGYuX2RyaXZlcy5hcHBlbmQoewogICAgICAgICAgICAgICAgICAgICAgICAibGV0dGVyIjog"
    "cGFydC5kZXZpY2UucnN0cmlwKCJcXCIpLnJzdHJpcCgiLyIpLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAidXNlZCI6ICAgdXNhZ2UudXNlZCAgLyAxMDI0KiozLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAidG90YWwiOiAgdXNhZ2UudG90YWwgLyAxMDI0KiozLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAicGN0IjogICAgdXNhZ2UucGVyY2VudCAvIDEwMC4wLAogICAgICAgICAgICAgICAgICAg"
    "IH0pCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAg"
    "IGNvbnRpbnVlCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAg"
    "ICAgICMgUmVzaXplIHRvIGZpdCBhbGwgZHJpdmVzCiAgICAgICAgbiA9IG1heCgxLCBsZW4oc2Vs"
    "Zi5fZHJpdmVzKSkKICAgICAgICBzZWxmLnNldE1pbmltdW1IZWlnaHQobiAqIDI4ICsgOCkKICAg"
    "ICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5v"
    "bmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQ"
    "YWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRo"
    "KCksIHNlbGYuaGVpZ2h0KCkKICAgICAgICBwLmZpbGxSZWN0KDAsIDAsIHcsIGgsIFFDb2xvcihD"
    "X0JHMykpCgogICAgICAgIGlmIG5vdCBzZWxmLl9kcml2ZXM6CiAgICAgICAgICAgIHAuc2V0UGVu"
    "KFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9O"
    "VCwgOSkpCiAgICAgICAgICAgIHAuZHJhd1RleHQoNiwgMTgsICJOL0Eg4oCUIHBzdXRpbCB1bmF2"
    "YWlsYWJsZSIpCiAgICAgICAgICAgIHAuZW5kKCkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAg"
    "IHJvd19oID0gMjYKICAgICAgICB5ID0gNAogICAgICAgIGZvciBkcnYgaW4gc2VsZi5fZHJpdmVz"
    "OgogICAgICAgICAgICBsZXR0ZXIgPSBkcnZbImxldHRlciJdCiAgICAgICAgICAgIHVzZWQgICA9"
    "IGRydlsidXNlZCJdCiAgICAgICAgICAgIHRvdGFsICA9IGRydlsidG90YWwiXQogICAgICAgICAg"
    "ICBwY3QgICAgPSBkcnZbInBjdCJdCgogICAgICAgICAgICAjIExhYmVsCiAgICAgICAgICAgIGxh"
    "YmVsID0gZiJ7bGV0dGVyfSAge3VzZWQ6LjFmfS97dG90YWw6LjBmfUdCIgogICAgICAgICAgICBw"
    "LnNldFBlbihRQ29sb3IoQ19HT0xEKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tf"
    "Rk9OVCwgOCwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgICAgICBwLmRyYXdUZXh0KDYsIHkg"
    "KyAxMiwgbGFiZWwpCgogICAgICAgICAgICAjIEJhcgogICAgICAgICAgICBiYXJfeCA9IDYKICAg"
    "ICAgICAgICAgYmFyX3kgPSB5ICsgMTUKICAgICAgICAgICAgYmFyX3cgPSB3IC0gMTIKICAgICAg"
    "ICAgICAgYmFyX2ggPSA4CiAgICAgICAgICAgIHAuZmlsbFJlY3QoYmFyX3gsIGJhcl95LCBiYXJf"
    "dywgYmFyX2gsIFFDb2xvcihDX0JHKSkKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfQk9S"
    "REVSKSkKICAgICAgICAgICAgcC5kcmF3UmVjdChiYXJfeCwgYmFyX3ksIGJhcl93IC0gMSwgYmFy"
    "X2ggLSAxKQoKICAgICAgICAgICAgZmlsbF93ID0gbWF4KDEsIGludCgoYmFyX3cgLSAyKSAqIHBj"
    "dCkpCiAgICAgICAgICAgIGJhcl9jb2xvciA9IChDX0JMT09EIGlmIHBjdCA+IDAuOSBlbHNlCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICBDX0NSSU1TT04gaWYgcGN0ID4gMC43NSBlbHNlCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBDX0dPTERfRElNKQogICAgICAgICAgICBncmFkID0gUUxpbmVh"
    "ckdyYWRpZW50KGJhcl94ICsgMSwgYmFyX3ksIGJhcl94ICsgZmlsbF93LCBiYXJfeSkKICAgICAg"
    "ICAgICAgZ3JhZC5zZXRDb2xvckF0KDAsIFFDb2xvcihiYXJfY29sb3IpLmRhcmtlcigxNTApKQog"
    "ICAgICAgICAgICBncmFkLnNldENvbG9yQXQoMSwgUUNvbG9yKGJhcl9jb2xvcikpCiAgICAgICAg"
    "ICAgIHAuZmlsbFJlY3QoYmFyX3ggKyAxLCBiYXJfeSArIDEsIGZpbGxfdywgYmFyX2ggLSAyLCBn"
    "cmFkKQoKICAgICAgICAgICAgeSArPSByb3dfaAoKICAgICAgICBwLmVuZCgpCgogICAgZGVmIHJl"
    "ZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJDYWxsIHBlcmlvZGljYWxseSB0byB1cGRh"
    "dGUgZHJpdmUgc3RhdHMuIiIiCiAgICAgICAgc2VsZi5fcmVmcmVzaCgpCgoKIyDilIDilIAgU1BI"
    "RVJFIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU3BoZXJlV2lkZ2V0KFFXaWRnZXQpOgogICAg"
    "IiIiCiAgICBGaWxsZWQgY2lyY2xlIGdhdWdlIOKAlCB1c2VkIGZvciBCTE9PRCAodG9rZW4gcG9v"
    "bCkgYW5kIE1BTkEgKFZSQU0pLgogICAgRmlsbHMgZnJvbSBib3R0b20gdXAuIEdsYXNzeSBzaGlu"
    "ZSBlZmZlY3QuIExhYmVsIGJlbG93LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKAogICAgICAg"
    "IHNlbGYsCiAgICAgICAgbGFiZWw6IHN0ciwKICAgICAgICBjb2xvcl9mdWxsOiBzdHIsCiAgICAg"
    "ICAgY29sb3JfZW1wdHk6IHN0ciwKICAgICAgICBwYXJlbnQ9Tm9uZQogICAgKToKICAgICAgICBz"
    "dXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLmxhYmVsICAgICAgID0gbGFiZWwK"
    "ICAgICAgICBzZWxmLmNvbG9yX2Z1bGwgID0gY29sb3JfZnVsbAogICAgICAgIHNlbGYuY29sb3Jf"
    "ZW1wdHkgPSBjb2xvcl9lbXB0eQogICAgICAgIHNlbGYuX2ZpbGwgICAgICAgPSAwLjAgICAjIDAu"
    "MCDihpIgMS4wCiAgICAgICAgc2VsZi5fYXZhaWxhYmxlICA9IFRydWUKICAgICAgICBzZWxmLnNl"
    "dE1pbmltdW1TaXplKDgwLCAxMDApCgogICAgZGVmIHNldEZpbGwoc2VsZiwgZnJhY3Rpb246IGZs"
    "b2F0LCBhdmFpbGFibGU6IGJvb2wgPSBUcnVlKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2ZpbGwg"
    "ICAgICA9IG1heCgwLjAsIG1pbigxLjAsIGZyYWN0aW9uKSkKICAgICAgICBzZWxmLl9hdmFpbGFi"
    "bGUgPSBhdmFpbGFibGUKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQo"
    "c2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAg"
    "cC5zZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAg"
    "IHcsIGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgciAgPSBtaW4odywg"
    "aCAtIDIwKSAvLyAyIC0gNAogICAgICAgIGN4ID0gdyAvLyAyCiAgICAgICAgY3kgPSAoaCAtIDIw"
    "KSAvLyAyICsgNAoKICAgICAgICAjIERyb3Agc2hhZG93CiAgICAgICAgcC5zZXRQZW4oUXQuUGVu"
    "U3R5bGUuTm9QZW4pCiAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMCwgMCwgMCwgODApKQogICAg"
    "ICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByICsgMywgY3kgLSByICsgMywgciAqIDIsIHIgKiAyKQoK"
    "ICAgICAgICAjIEJhc2UgY2lyY2xlIChlbXB0eSBjb2xvcikKICAgICAgICBwLnNldEJydXNoKFFD"
    "b2xvcihzZWxmLmNvbG9yX2VtcHR5KSkKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19CT1JERVIp"
    "KQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAg"
    "ICAgICAgIyBGaWxsIGZyb20gYm90dG9tCiAgICAgICAgaWYgc2VsZi5fZmlsbCA+IDAuMDEgYW5k"
    "IHNlbGYuX2F2YWlsYWJsZToKICAgICAgICAgICAgY2lyY2xlX3BhdGggPSBRUGFpbnRlclBhdGgo"
    "KQogICAgICAgICAgICBjaXJjbGVfcGF0aC5hZGRFbGxpcHNlKGZsb2F0KGN4IC0gciksIGZsb2F0"
    "KGN5IC0gciksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZmxvYXQociAqIDIp"
    "LCBmbG9hdChyICogMikpCgogICAgICAgICAgICBmaWxsX3RvcF95ID0gY3kgKyByIC0gKHNlbGYu"
    "X2ZpbGwgKiByICogMikKICAgICAgICAgICAgZnJvbSBQeVNpZGU2LlF0Q29yZSBpbXBvcnQgUVJl"
    "Y3RGCiAgICAgICAgICAgIGZpbGxfcmVjdCA9IFFSZWN0RihjeCAtIHIsIGZpbGxfdG9wX3ksIHIg"
    "KiAyLCBjeSArIHIgLSBmaWxsX3RvcF95KQogICAgICAgICAgICBmaWxsX3BhdGggPSBRUGFpbnRl"
    "clBhdGgoKQogICAgICAgICAgICBmaWxsX3BhdGguYWRkUmVjdChmaWxsX3JlY3QpCiAgICAgICAg"
    "ICAgIGNsaXBwZWQgPSBjaXJjbGVfcGF0aC5pbnRlcnNlY3RlZChmaWxsX3BhdGgpCgogICAgICAg"
    "ICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICAgICAgcC5zZXRCcnVzaChR"
    "Q29sb3Ioc2VsZi5jb2xvcl9mdWxsKSkKICAgICAgICAgICAgcC5kcmF3UGF0aChjbGlwcGVkKQoK"
    "ICAgICAgICAjIEdsYXNzeSBzaGluZQogICAgICAgIHNoaW5lID0gUVJhZGlhbEdyYWRpZW50KAog"
    "ICAgICAgICAgICBmbG9hdChjeCAtIHIgKiAwLjMpLCBmbG9hdChjeSAtIHIgKiAwLjMpLCBmbG9h"
    "dChyICogMC42KQogICAgICAgICkKICAgICAgICBzaGluZS5zZXRDb2xvckF0KDAsIFFDb2xvcigy"
    "NTUsIDI1NSwgMjU1LCA1NSkpCiAgICAgICAgc2hpbmUuc2V0Q29sb3JBdCgxLCBRQ29sb3IoMjU1"
    "LCAyNTUsIDI1NSwgMCkpCiAgICAgICAgcC5zZXRCcnVzaChzaGluZSkKICAgICAgICBwLnNldFBl"
    "bihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSBy"
    "LCByICogMiwgciAqIDIpCgogICAgICAgICMgT3V0bGluZQogICAgICAgIHAuc2V0QnJ1c2goUXQu"
    "QnJ1c2hTdHlsZS5Ob0JydXNoKQogICAgICAgIHAuc2V0UGVuKFFQZW4oUUNvbG9yKHNlbGYuY29s"
    "b3JfZnVsbCksIDEpKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAy"
    "LCByICogMikKCiAgICAgICAgIyBOL0Egb3ZlcmxheQogICAgICAgIGlmIG5vdCBzZWxmLl9hdmFp"
    "bGFibGU6CiAgICAgICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICAg"
    "ICAgcC5zZXRGb250KFFGb250KCJDb3VyaWVyIE5ldyIsIDgpKQogICAgICAgICAgICBmbSA9IHAu"
    "Zm9udE1ldHJpY3MoKQogICAgICAgICAgICB0eHQgPSAiTi9BIgogICAgICAgICAgICBwLmRyYXdU"
    "ZXh0KGN4IC0gZm0uaG9yaXpvbnRhbEFkdmFuY2UodHh0KSAvLyAyLCBjeSArIDQsIHR4dCkKCiAg"
    "ICAgICAgIyBMYWJlbCBiZWxvdyBzcGhlcmUKICAgICAgICBsYWJlbF90ZXh0ID0gKHNlbGYubGFi"
    "ZWwgaWYgc2VsZi5fYXZhaWxhYmxlIGVsc2UKICAgICAgICAgICAgICAgICAgICAgIGYie3NlbGYu"
    "bGFiZWx9IikKICAgICAgICBwY3RfdGV4dCA9IGYie2ludChzZWxmLl9maWxsICogMTAwKX0lIiBp"
    "ZiBzZWxmLl9hdmFpbGFibGUgZWxzZSAiIgoKICAgICAgICBwLnNldFBlbihRQ29sb3Ioc2VsZi5j"
    "b2xvcl9mdWxsKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA4LCBRRm9udC5X"
    "ZWlnaHQuQm9sZCkpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKCiAgICAgICAgbHcgPSBm"
    "bS5ob3Jpem9udGFsQWR2YW5jZShsYWJlbF90ZXh0KQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBs"
    "dyAvLyAyLCBoIC0gMTAsIGxhYmVsX3RleHQpCgogICAgICAgIGlmIHBjdF90ZXh0OgogICAgICAg"
    "ICAgICBwLnNldFBlbihRQ29sb3IoQ19URVhUX0RJTSkpCiAgICAgICAgICAgIHAuc2V0Rm9udChR"
    "Rm9udChERUNLX0ZPTlQsIDcpKQogICAgICAgICAgICBmbTIgPSBwLmZvbnRNZXRyaWNzKCkKICAg"
    "ICAgICAgICAgcHcgPSBmbTIuaG9yaXpvbnRhbEFkdmFuY2UocGN0X3RleHQpCiAgICAgICAgICAg"
    "IHAuZHJhd1RleHQoY3ggLSBwdyAvLyAyLCBoIC0gMSwgcGN0X3RleHQpCgogICAgICAgIHAuZW5k"
    "KCkKCgojIOKUgOKUgCBNT09OIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9vbldp"
    "ZGdldChRV2lkZ2V0KToKICAgICIiIgogICAgRHJhd24gbW9vbiBvcmIgd2l0aCBwaGFzZS1hY2N1"
    "cmF0ZSBzaGFkb3cuCgogICAgUEhBU0UgQ09OVkVOVElPTiAobm9ydGhlcm4gaGVtaXNwaGVyZSwg"
    "c3RhbmRhcmQpOgogICAgICAtIFdheGluZyAobmV34oaSZnVsbCk6IGlsbHVtaW5hdGVkIHJpZ2h0"
    "IHNpZGUsIHNoYWRvdyBvbiBsZWZ0CiAgICAgIC0gV2FuaW5nIChmdWxs4oaSbmV3KTogaWxsdW1p"
    "bmF0ZWQgbGVmdCBzaWRlLCBzaGFkb3cgb24gcmlnaHQKCiAgICBUaGUgc2hhZG93X3NpZGUgZmxh"
    "ZyBjYW4gYmUgZmxpcHBlZCBpZiB0ZXN0aW5nIHJldmVhbHMgaXQncyBiYWNrd2FyZHMKICAgIG9u"
    "IHRoaXMgbWFjaGluZS4gU2V0IE1PT05fU0hBRE9XX0ZMSVAgPSBUcnVlIGluIHRoYXQgY2FzZS4K"
    "ICAgICIiIgoKICAgICMg4oaQIEZMSVAgVEhJUyB0byBUcnVlIGlmIG1vb24gYXBwZWFycyBiYWNr"
    "d2FyZHMgZHVyaW5nIHRlc3RpbmcKICAgIE1PT05fU0hBRE9XX0ZMSVA6IGJvb2wgPSBGYWxzZQoK"
    "ICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2lu"
    "aXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fcGhhc2UgICAgICAgPSAwLjAgICAgIyAwLjA9bmV3"
    "LCAwLjU9ZnVsbCwgMS4wPW5ldwogICAgICAgIHNlbGYuX25hbWUgICAgICAgID0gIk5FVyBNT09O"
    "IgogICAgICAgIHNlbGYuX2lsbHVtaW5hdGlvbiA9IDAuMCAgICMgMC0xMDAKICAgICAgICBzZWxm"
    "Ll9zdW5yaXNlICAgICAgPSAiMDY6MDAiCiAgICAgICAgc2VsZi5fc3Vuc2V0ICAgICAgID0gIjE4"
    "OjMwIgogICAgICAgIHNlbGYuX3N1bl9kYXRlICAgICA9IE5vbmUKICAgICAgICBzZWxmLnNldE1p"
    "bmltdW1TaXplKDgwLCAxMTApCiAgICAgICAgc2VsZi51cGRhdGVQaGFzZSgpICAgICAgICAgICMg"
    "cG9wdWxhdGUgY29ycmVjdCBwaGFzZSBpbW1lZGlhdGVseQogICAgICAgIHNlbGYuX2ZldGNoX3N1"
    "bl9hc3luYygpCgogICAgZGVmIF9mZXRjaF9zdW5fYXN5bmMoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBkZWYgX2ZldGNoKCk6CiAgICAgICAgICAgIHNyLCBzcyA9IGdldF9zdW5fdGltZXMoKQogICAg"
    "ICAgICAgICBzZWxmLl9zdW5yaXNlID0gc3IKICAgICAgICAgICAgc2VsZi5fc3Vuc2V0ICA9IHNz"
    "CiAgICAgICAgICAgIHNlbGYuX3N1bl9kYXRlID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgp"
    "LmRhdGUoKQogICAgICAgICAgICAjIFNjaGVkdWxlIHJlcGFpbnQgb24gbWFpbiB0aHJlYWQgdmlh"
    "IFFUaW1lciDigJQgbmV2ZXIgY2FsbAogICAgICAgICAgICAjIHNlbGYudXBkYXRlKCkgZGlyZWN0"
    "bHkgZnJvbSBhIGJhY2tncm91bmQgdGhyZWFkCiAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90"
    "KDAsIHNlbGYudXBkYXRlKQogICAgICAgIHRocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9mZXRjaCwg"
    "ZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgdXBkYXRlUGhhc2Uoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9waGFzZSwgc2VsZi5fbmFtZSwgc2VsZi5faWxsdW1pbmF0aW9uID0gZ2V0"
    "X21vb25fcGhhc2UoKQogICAgICAgIHRvZGF5ID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgp"
    "LmRhdGUoKQogICAgICAgIGlmIHNlbGYuX3N1bl9kYXRlICE9IHRvZGF5OgogICAgICAgICAgICBz"
    "ZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFp"
    "bnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikK"
    "ICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcp"
    "CiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwgc2VsZi5oZWlnaHQoKQoKICAgICAgICByICA9"
    "IG1pbih3LCBoIC0gMzYpIC8vIDIgLSA0CiAgICAgICAgY3ggPSB3IC8vIDIKICAgICAgICBjeSA9"
    "IChoIC0gMzYpIC8vIDIgKyA0CgogICAgICAgICMgQmFja2dyb3VuZCBjaXJjbGUgKHNwYWNlKQog"
    "ICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDIwLCAxMiwgMjgpKQogICAgICAgIHAuc2V0UGVuKFFQ"
    "ZW4oUUNvbG9yKENfU0lMVkVSX0RJTSksIDEpKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSBy"
    "LCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgY3ljbGVfZGF5ID0gc2VsZi5fcGhhc2Ug"
    "KiBfTFVOQVJfQ1lDTEUKICAgICAgICBpc193YXhpbmcgPSBjeWNsZV9kYXkgPCAoX0xVTkFSX0NZ"
    "Q0xFIC8gMikKCiAgICAgICAgIyBGdWxsIG1vb24gYmFzZSAobW9vbiBzdXJmYWNlIGNvbG9yKQog"
    "ICAgICAgIGlmIHNlbGYuX2lsbHVtaW5hdGlvbiA+IDE6CiAgICAgICAgICAgIHAuc2V0UGVuKFF0"
    "LlBlblN0eWxlLk5vUGVuKQogICAgICAgICAgICBwLnNldEJydXNoKFFDb2xvcigyMjAsIDIxMCwg"
    "MTg1KSkKICAgICAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIg"
    "KiAyKQoKICAgICAgICAjIFNoYWRvdyBjYWxjdWxhdGlvbgogICAgICAgICMgaWxsdW1pbmF0aW9u"
    "IGdvZXMgMOKGkjEwMCB3YXhpbmcsIDEwMOKGkjAgd2FuaW5nCiAgICAgICAgIyBzaGFkb3dfb2Zm"
    "c2V0IGNvbnRyb2xzIGhvdyBtdWNoIG9mIHRoZSBjaXJjbGUgdGhlIHNoYWRvdyBjb3ZlcnMKICAg"
    "ICAgICBpZiBzZWxmLl9pbGx1bWluYXRpb24gPCA5OToKICAgICAgICAgICAgIyBmcmFjdGlvbiBv"
    "ZiBkaWFtZXRlciB0aGUgc2hhZG93IGVsbGlwc2UgaXMgb2Zmc2V0CiAgICAgICAgICAgIGlsbHVt"
    "X2ZyYWMgID0gc2VsZi5faWxsdW1pbmF0aW9uIC8gMTAwLjAKICAgICAgICAgICAgc2hhZG93X2Zy"
    "YWMgPSAxLjAgLSBpbGx1bV9mcmFjCgogICAgICAgICAgICAjIHdheGluZzogaWxsdW1pbmF0ZWQg"
    "cmlnaHQsIHNoYWRvdyBMRUZUCiAgICAgICAgICAgICMgd2FuaW5nOiBpbGx1bWluYXRlZCBsZWZ0"
    "LCBzaGFkb3cgUklHSFQKICAgICAgICAgICAgIyBvZmZzZXQgbW92ZXMgdGhlIHNoYWRvdyBlbGxp"
    "cHNlIGhvcml6b250YWxseQogICAgICAgICAgICBvZmZzZXQgPSBpbnQoc2hhZG93X2ZyYWMgKiBy"
    "ICogMikKCiAgICAgICAgICAgIGlmIE1vb25XaWRnZXQuTU9PTl9TSEFET1dfRkxJUDoKICAgICAg"
    "ICAgICAgICAgIGlzX3dheGluZyA9IG5vdCBpc193YXhpbmcKCiAgICAgICAgICAgIGlmIGlzX3dh"
    "eGluZzoKICAgICAgICAgICAgICAgICMgU2hhZG93IG9uIGxlZnQgc2lkZQogICAgICAgICAgICAg"
    "ICAgc2hhZG93X3ggPSBjeCAtIHIgLSBvZmZzZXQKICAgICAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgICAgICMgU2hhZG93IG9uIHJpZ2h0IHNpZGUKICAgICAgICAgICAgICAgIHNoYWRvd194ID0g"
    "Y3ggLSByICsgb2Zmc2V0CgogICAgICAgICAgICBwLnNldEJydXNoKFFDb2xvcigxNSwgOCwgMjIp"
    "KQogICAgICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKCiAgICAgICAgICAgICMg"
    "RHJhdyBzaGFkb3cgZWxsaXBzZSDigJQgY2xpcHBlZCB0byBtb29uIGNpcmNsZQogICAgICAgICAg"
    "ICBtb29uX3BhdGggPSBRUGFpbnRlclBhdGgoKQogICAgICAgICAgICBtb29uX3BhdGguYWRkRWxs"
    "aXBzZShmbG9hdChjeCAtIHIpLCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgZmxvYXQociAqIDIpLCBmbG9hdChyICogMikpCiAgICAgICAgICAgIHNoYWRv"
    "d19wYXRoID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgc2hhZG93X3BhdGguYWRkRWxsaXBz"
    "ZShmbG9hdChzaGFkb3dfeCksIGZsb2F0KGN5IC0gciksCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQogICAgICAgICAgICBjbGlw"
    "cGVkX3NoYWRvdyA9IG1vb25fcGF0aC5pbnRlcnNlY3RlZChzaGFkb3dfcGF0aCkKICAgICAgICAg"
    "ICAgcC5kcmF3UGF0aChjbGlwcGVkX3NoYWRvdykKCiAgICAgICAgIyBTdWJ0bGUgc3VyZmFjZSBk"
    "ZXRhaWwgKGNyYXRlcnMgaW1wbGllZCBieSBzbGlnaHQgdGV4dHVyZSBncmFkaWVudCkKICAgICAg"
    "ICBzaGluZSA9IFFSYWRpYWxHcmFkaWVudChmbG9hdChjeCAtIHIgKiAwLjIpLCBmbG9hdChjeSAt"
    "IHIgKiAwLjIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZsb2F0KHIgKiAwLjgp"
    "KQogICAgICAgIHNoaW5lLnNldENvbG9yQXQoMCwgUUNvbG9yKDI1NSwgMjU1LCAyNDAsIDMwKSkK"
    "ICAgICAgICBzaGluZS5zZXRDb2xvckF0KDEsIFFDb2xvcigyMDAsIDE4MCwgMTQwLCA1KSkKICAg"
    "ICAgICBwLnNldEJydXNoKHNoaW5lKQogICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5vUGVu"
    "KQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAg"
    "ICAgICAgIyBPdXRsaW5lCiAgICAgICAgcC5zZXRCcnVzaChRdC5CcnVzaFN0eWxlLk5vQnJ1c2gp"
    "CiAgICAgICAgcC5zZXRQZW4oUVBlbihRQ29sb3IoQ19TSUxWRVIpLCAxKSkKICAgICAgICBwLmRy"
    "YXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgUGhhc2Ug"
    "bmFtZSBiZWxvdyBtb29uCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfU0lMVkVSKSkKICAgICAg"
    "ICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAg"
    "ICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICBudyA9IGZtLmhvcml6b250YWxBZHZhbmNl"
    "KHNlbGYuX25hbWUpCiAgICAgICAgcC5kcmF3VGV4dChjeCAtIG53IC8vIDIsIGN5ICsgciArIDE0"
    "LCBzZWxmLl9uYW1lKQoKICAgICAgICAjIElsbHVtaW5hdGlvbiBwZXJjZW50YWdlCiAgICAgICAg"
    "aWxsdW1fc3RyID0gZiJ7c2VsZi5faWxsdW1pbmF0aW9uOi4wZn0lIgogICAgICAgIHAuc2V0UGVu"
    "KFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA3"
    "KSkKICAgICAgICBmbTIgPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICBpdyA9IGZtMi5ob3Jpem9u"
    "dGFsQWR2YW5jZShpbGx1bV9zdHIpCiAgICAgICAgcC5kcmF3VGV4dChjeCAtIGl3IC8vIDIsIGN5"
    "ICsgciArIDI0LCBpbGx1bV9zdHIpCgogICAgICAgICMgU3VuIHRpbWVzIGF0IHZlcnkgYm90dG9t"
    "CiAgICAgICAgc3VuX3N0ciA9IGYi4piAIHtzZWxmLl9zdW5yaXNlfSAg4pi9IHtzZWxmLl9zdW5z"
    "ZXR9IgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0dPTERfRElNKSkKICAgICAgICBwLnNldEZv"
    "bnQoUUZvbnQoREVDS19GT05ULCA3KSkKICAgICAgICBmbTMgPSBwLmZvbnRNZXRyaWNzKCkKICAg"
    "ICAgICBzdyA9IGZtMy5ob3Jpem9udGFsQWR2YW5jZShzdW5fc3RyKQogICAgICAgIHAuZHJhd1Rl"
    "eHQoY3ggLSBzdyAvLyAyLCBoIC0gMiwgc3VuX3N0cikKCiAgICAgICAgcC5lbmQoKQoKCiMg4pSA"
    "4pSAIEVNT1RJT04gQkxPQ0sg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEVtb3Rpb25CbG9jayhRV2lkZ2V0"
    "KToKICAgICIiIgogICAgQ29sbGFwc2libGUgZW1vdGlvbiBoaXN0b3J5IHBhbmVsLgogICAgU2hv"
    "d3MgY29sb3ItY29kZWQgY2hpcHM6IOKcpiBFTU9USU9OX05BTUUgIEhIOk1NCiAgICBTaXRzIG5l"
    "eHQgdG8gdGhlIE1pcnJvciAoZmFjZSB3aWRnZXQpIGluIHRoZSBib3R0b20gYmxvY2sgcm93Lgog"
    "ICAgQ29sbGFwc2VzIHRvIGp1c3QgdGhlIGhlYWRlciBzdHJpcC4KICAgICIiIgoKICAgIGRlZiBf"
    "X2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJl"
    "bnQpCiAgICAgICAgc2VsZi5faGlzdG9yeTogbGlzdFt0dXBsZVtzdHIsIHN0cl1dID0gW10gICMg"
    "KGVtb3Rpb24sIHRpbWVzdGFtcCkKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IFRydWUKICAgICAg"
    "ICBzZWxmLl9tYXhfZW50cmllcyA9IDMwCgogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KHNl"
    "bGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAg"
    "IGxheW91dC5zZXRTcGFjaW5nKDApCgogICAgICAgICMgSGVhZGVyIHJvdwogICAgICAgIGhlYWRl"
    "ciA9IFFXaWRnZXQoKQogICAgICAgIGhlYWRlci5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBo"
    "ZWFkZXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBi"
    "b3JkZXItYm90dG9tOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAg"
    "ICAgaGwgPSBRSEJveExheW91dChoZWFkZXIpCiAgICAgICAgaGwuc2V0Q29udGVudHNNYXJnaW5z"
    "KDYsIDAsIDQsIDApCiAgICAgICAgaGwuc2V0U3BhY2luZyg0KQoKICAgICAgICBsYmwgPSBRTGFi"
    "ZWwoIuKdpyBFTU9USU9OQUwgUkVDT1JEIikKICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDog"
    "Ym9sZDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGxl"
    "dHRlci1zcGFjaW5nOiAxcHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYu"
    "X3RvZ2dsZV9idG4gPSBRVG9vbEJ1dHRvbigpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRG"
    "aXhlZFNpemUoMTYsIDE2KQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB0cmFuc3BhcmVudDsgY29sb3I6IHtDX0dPTER9OyBi"
    "b3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Rv"
    "Z2dsZV9idG4uc2V0VGV4dCgi4pa8IikKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLmNsaWNrZWQu"
    "Y29ubmVjdChzZWxmLl90b2dnbGUpCgogICAgICAgIGhsLmFkZFdpZGdldChsYmwpCiAgICAgICAg"
    "aGwuYWRkU3RyZXRjaCgpCiAgICAgICAgaGwuYWRkV2lkZ2V0KHNlbGYuX3RvZ2dsZV9idG4pCgog"
    "ICAgICAgICMgU2Nyb2xsIGFyZWEgZm9yIGVtb3Rpb24gY2hpcHMKICAgICAgICBzZWxmLl9zY3Jv"
    "bGwgPSBRU2Nyb2xsQXJlYSgpCiAgICAgICAgc2VsZi5fc2Nyb2xsLnNldFdpZGdldFJlc2l6YWJs"
    "ZShUcnVlKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRIb3Jpem9udGFsU2Nyb2xsQmFyUG9saWN5"
    "KAogICAgICAgICAgICBRdC5TY3JvbGxCYXJQb2xpY3kuU2Nyb2xsQmFyQWx3YXlzT2ZmKQogICAg"
    "ICAgIHNlbGYuX3Njcm9sbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6"
    "IHtDX0JHMn07IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQoKICAgICAgICBzZWxmLl9jaGlwX2Nv"
    "bnRhaW5lciA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0ID0gUVZCb3hMYXlv"
    "dXQoc2VsZi5fY2hpcF9jb250YWluZXIpCiAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQuc2V0Q29u"
    "dGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQuc2V0U3Bh"
    "Y2luZygyKQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LmFkZFN0cmV0Y2goKQogICAgICAgIHNl"
    "bGYuX3Njcm9sbC5zZXRXaWRnZXQoc2VsZi5fY2hpcF9jb250YWluZXIpCgogICAgICAgIGxheW91"
    "dC5hZGRXaWRnZXQoaGVhZGVyKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fc2Nyb2xs"
    "KQoKICAgICAgICBzZWxmLnNldE1pbmltdW1XaWR0aCgxMzApCgogICAgZGVmIF90b2dnbGUoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAog"
    "ICAgICAgIHNlbGYuX3Njcm9sbC5zZXRWaXNpYmxlKHNlbGYuX2V4cGFuZGVkKQogICAgICAgIHNl"
    "bGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi4pa8IiBpZiBzZWxmLl9leHBhbmRlZCBlbHNlICLilrIi"
    "KQogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0cnkoKQoKICAgIGRlZiBhZGRFbW90aW9uKHNlbGYs"
    "IGVtb3Rpb246IHN0ciwgdGltZXN0YW1wOiBzdHIgPSAiIikgLT4gTm9uZToKICAgICAgICBpZiBu"
    "b3QgdGltZXN0YW1wOgogICAgICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJm"
    "dGltZSgiJUg6JU0iKQogICAgICAgIHNlbGYuX2hpc3RvcnkuaW5zZXJ0KDAsIChlbW90aW9uLCB0"
    "aW1lc3RhbXApKQogICAgICAgIHNlbGYuX2hpc3RvcnkgPSBzZWxmLl9oaXN0b3J5WzpzZWxmLl9t"
    "YXhfZW50cmllc10KICAgICAgICBzZWxmLl9yZWJ1aWxkX2NoaXBzKCkKCiAgICBkZWYgX3JlYnVp"
    "bGRfY2hpcHMoc2VsZikgLT4gTm9uZToKICAgICAgICAjIENsZWFyIGV4aXN0aW5nIGNoaXBzIChr"
    "ZWVwIHRoZSBzdHJldGNoIGF0IGVuZCkKICAgICAgICB3aGlsZSBzZWxmLl9jaGlwX2xheW91dC5j"
    "b3VudCgpID4gMToKICAgICAgICAgICAgaXRlbSA9IHNlbGYuX2NoaXBfbGF5b3V0LnRha2VBdCgw"
    "KQogICAgICAgICAgICBpZiBpdGVtLndpZGdldCgpOgogICAgICAgICAgICAgICAgaXRlbS53aWRn"
    "ZXQoKS5kZWxldGVMYXRlcigpCgogICAgICAgIGZvciBlbW90aW9uLCB0cyBpbiBzZWxmLl9oaXN0"
    "b3J5OgogICAgICAgICAgICBjb2xvciA9IEVNT1RJT05fQ09MT1JTLmdldChlbW90aW9uLCBDX1RF"
    "WFRfRElNKQogICAgICAgICAgICBjaGlwID0gUUxhYmVsKGYi4pymIHtlbW90aW9uLnVwcGVyKCl9"
    "ICB7dHN9IikKICAgICAgICAgICAgY2hpcC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAg"
    "ZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05U"
    "fSwgc2VyaWY7ICIKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVy"
    "OiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICAgICAgZiJwYWRkaW5nOiAxcHgg"
    "NHB4OyBib3JkZXItcmFkaXVzOiAycHg7IgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYu"
    "X2NoaXBfbGF5b3V0Lmluc2VydFdpZGdldCgKICAgICAgICAgICAgICAgIHNlbGYuX2NoaXBfbGF5"
    "b3V0LmNvdW50KCkgLSAxLCBjaGlwCiAgICAgICAgICAgICkKCiAgICBkZWYgY2xlYXIoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9oaXN0b3J5LmNsZWFyKCkKICAgICAgICBzZWxmLl9yZWJ1"
    "aWxkX2NoaXBzKCkKCgojIOKUgOKUgCBNSVJST1IgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBN"
    "aXJyb3JXaWRnZXQoUUxhYmVsKToKICAgICIiIgogICAgRmFjZSBpbWFnZSBkaXNwbGF5IOKAlCAn"
    "VGhlIE1pcnJvcicuCiAgICBEeW5hbWljYWxseSBsb2FkcyBhbGwge0ZBQ0VfUFJFRklYfV8qLnBu"
    "ZyBmaWxlcyBmcm9tIGNvbmZpZyBwYXRocy5mYWNlcy4KICAgIEF1dG8tbWFwcyBmaWxlbmFtZSB0"
    "byBlbW90aW9uIGtleToKICAgICAgICB7RkFDRV9QUkVGSVh9X0FsZXJ0LnBuZyAgICAg4oaSICJh"
    "bGVydCIKICAgICAgICB7RkFDRV9QUkVGSVh9X1NhZF9DcnlpbmcucG5nIOKGkiAic2FkIgogICAg"
    "ICAgIHtGQUNFX1BSRUZJWH1fQ2hlYXRfTW9kZS5wbmcg4oaSICJjaGVhdG1vZGUiCiAgICBGYWxs"
    "cyBiYWNrIHRvIG5ldXRyYWwsIHRoZW4gdG8gZ290aGljIHBsYWNlaG9sZGVyIGlmIG5vIGltYWdl"
    "cyBmb3VuZC4KICAgIE1pc3NpbmcgZmFjZXMgZGVmYXVsdCB0byBuZXV0cmFsIOKAlCBubyBjcmFz"
    "aCwgbm8gaGFyZGNvZGVkIGxpc3QgcmVxdWlyZWQuCiAgICAiIiIKCiAgICAjIFNwZWNpYWwgc3Rl"
    "bSDihpIgZW1vdGlvbiBrZXkgbWFwcGluZ3MgKGxvd2VyY2FzZSBzdGVtIGFmdGVyIE1vcmdhbm5h"
    "XykKICAgIF9TVEVNX1RPX0VNT1RJT046IGRpY3Rbc3RyLCBzdHJdID0gewogICAgICAgICJzYWRf"
    "Y3J5aW5nIjogICJzYWQiLAogICAgICAgICJjaGVhdF9tb2RlIjogICJjaGVhdG1vZGUiLAogICAg"
    "fQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5f"
    "X2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZmFjZXNfZGlyICAgPSBjZmdfcGF0aCgiZmFj"
    "ZXMiKQogICAgICAgIHNlbGYuX2NhY2hlOiBkaWN0W3N0ciwgUVBpeG1hcF0gPSB7fQogICAgICAg"
    "IHNlbGYuX2N1cnJlbnQgICAgID0gIm5ldXRyYWwiCiAgICAgICAgc2VsZi5fd2FybmVkOiBzZXRb"
    "c3RyXSA9IHNldCgpCgogICAgICAgIHNlbGYuc2V0TWluaW11bVNpemUoMTYwLCAxNjApCiAgICAg"
    "ICAgc2VsZi5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAg"
    "ICBzZWxmLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsg"
    "Ym9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVy"
    "LXJhZGl1czogMnB4OyIKICAgICAgICApCgogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDMwMCwg"
    "c2VsZi5fcHJlbG9hZCkKCiAgICBkZWYgX3ByZWxvYWQoc2VsZikgLT4gTm9uZToKICAgICAgICAi"
    "IiIKICAgICAgICBTY2FuIEZhY2VzLyBkaXJlY3RvcnkgZm9yIGFsbCB7RkFDRV9QUkVGSVh9Xyou"
    "cG5nIGZpbGVzLgogICAgICAgIEJ1aWxkIGVtb3Rpb27ihpJwaXhtYXAgY2FjaGUgZHluYW1pY2Fs"
    "bHkuCiAgICAgICAgTm8gaGFyZGNvZGVkIGxpc3Qg4oCUIHdoYXRldmVyIGlzIGluIHRoZSBmb2xk"
    "ZXIgaXMgYXZhaWxhYmxlLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBzZWxmLl9mYWNlc19k"
    "aXIuZXhpc3RzKCk6CiAgICAgICAgICAgIHNlbGYuX2RyYXdfcGxhY2Vob2xkZXIoKQogICAgICAg"
    "ICAgICByZXR1cm4KCiAgICAgICAgZm9yIGltZ19wYXRoIGluIHNlbGYuX2ZhY2VzX2Rpci5nbG9i"
    "KGYie0ZBQ0VfUFJFRklYfV8qLnBuZyIpOgogICAgICAgICAgICAjIHN0ZW0gPSBldmVyeXRoaW5n"
    "IGFmdGVyICJNb3JnYW5uYV8iIHdpdGhvdXQgLnBuZwogICAgICAgICAgICByYXdfc3RlbSA9IGlt"
    "Z19wYXRoLnN0ZW1bbGVuKGYie0ZBQ0VfUFJFRklYfV8iKTpdICAgICMgZS5nLiAiU2FkX0NyeWlu"
    "ZyIKICAgICAgICAgICAgc3RlbV9sb3dlciA9IHJhd19zdGVtLmxvd2VyKCkgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICMgInNhZF9jcnlpbmciCgogICAgICAgICAgICAjIE1hcCBzcGVjaWFsIHN0"
    "ZW1zIHRvIGVtb3Rpb24ga2V5cwogICAgICAgICAgICBlbW90aW9uID0gc2VsZi5fU1RFTV9UT19F"
    "TU9USU9OLmdldChzdGVtX2xvd2VyLCBzdGVtX2xvd2VyKQoKICAgICAgICAgICAgcHggPSBRUGl4"
    "bWFwKHN0cihpbWdfcGF0aCkpCiAgICAgICAgICAgIGlmIG5vdCBweC5pc051bGwoKToKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2NhY2hlW2Vtb3Rpb25dID0gcHgKCiAgICAgICAgaWYgc2VsZi5fY2Fj"
    "aGU6CiAgICAgICAgICAgIHNlbGYuX3JlbmRlcigibmV1dHJhbCIpCiAgICAgICAgZWxzZToKICAg"
    "ICAgICAgICAgc2VsZi5fZHJhd19wbGFjZWhvbGRlcigpCgogICAgZGVmIF9yZW5kZXIoc2VsZiwg"
    "ZmFjZTogc3RyKSAtPiBOb25lOgogICAgICAgIGZhY2UgPSBmYWNlLmxvd2VyKCkuc3RyaXAoKQog"
    "ICAgICAgIGlmIGZhY2Ugbm90IGluIHNlbGYuX2NhY2hlOgogICAgICAgICAgICBpZiBmYWNlIG5v"
    "dCBpbiBzZWxmLl93YXJuZWQgYW5kIGZhY2UgIT0gIm5ldXRyYWwiOgogICAgICAgICAgICAgICAg"
    "cHJpbnQoZiJbTUlSUk9SXVtXQVJOXSBGYWNlIG5vdCBpbiBjYWNoZToge2ZhY2V9IOKAlCB1c2lu"
    "ZyBuZXV0cmFsIikKICAgICAgICAgICAgICAgIHNlbGYuX3dhcm5lZC5hZGQoZmFjZSkKICAgICAg"
    "ICAgICAgZmFjZSA9ICJuZXV0cmFsIgogICAgICAgIGlmIGZhY2Ugbm90IGluIHNlbGYuX2NhY2hl"
    "OgogICAgICAgICAgICBzZWxmLl9kcmF3X3BsYWNlaG9sZGVyKCkKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgc2VsZi5fY3VycmVudCA9IGZhY2UKICAgICAgICBweCA9IHNlbGYuX2NhY2hlW2Zh"
    "Y2VdCiAgICAgICAgc2NhbGVkID0gcHguc2NhbGVkKAogICAgICAgICAgICBzZWxmLndpZHRoKCkg"
    "LSA0LAogICAgICAgICAgICBzZWxmLmhlaWdodCgpIC0gNCwKICAgICAgICAgICAgUXQuQXNwZWN0"
    "UmF0aW9Nb2RlLktlZXBBc3BlY3RSYXRpbywKICAgICAgICAgICAgUXQuVHJhbnNmb3JtYXRpb25N"
    "b2RlLlNtb290aFRyYW5zZm9ybWF0aW9uLAogICAgICAgICkKICAgICAgICBzZWxmLnNldFBpeG1h"
    "cChzY2FsZWQpCiAgICAgICAgc2VsZi5zZXRUZXh0KCIiKQoKICAgIGRlZiBfZHJhd19wbGFjZWhv"
    "bGRlcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuY2xlYXIoKQogICAgICAgIHNlbGYuc2V0"
    "VGV4dCgi4pymXG7inadcbuKcpiIpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05f"
    "RElNfTsgIgogICAgICAgICAgICBmImNvbG9yOiB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTog"
    "MjRweDsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCgogICAgZGVmIHNldF9mYWNlKHNl"
    "bGYsIGZhY2U6IHN0cikgLT4gTm9uZToKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgwLCBsYW1i"
    "ZGE6IHNlbGYuX3JlbmRlcihmYWNlKSkKCiAgICBkZWYgcmVzaXplRXZlbnQoc2VsZiwgZXZlbnQp"
    "IC0+IE5vbmU6CiAgICAgICAgc3VwZXIoKS5yZXNpemVFdmVudChldmVudCkKICAgICAgICBpZiBz"
    "ZWxmLl9jYWNoZToKICAgICAgICAgICAgc2VsZi5fcmVuZGVyKHNlbGYuX2N1cnJlbnQpCgogICAg"
    "QHByb3BlcnR5CiAgICBkZWYgY3VycmVudF9mYWNlKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1"
    "cm4gc2VsZi5fY3VycmVudAoKCiMg4pSA4pSAIFZBTVBJUkUgU1RBVEUgU1RSSVAg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEN5Y2xlV2lk"
    "Z2V0KE1vb25XaWRnZXQpOgogICAgIiIiR2VuZXJpYyBjeWNsZSB2aXN1YWxpemF0aW9uIHdpZGdl"
    "dCAoY3VycmVudGx5IGx1bmFyLXBoYXNlIGRyaXZlbikuIiIiCgoKY2xhc3MgVmFtcGlyZVN0YXRl"
    "U3RyaXAoUVdpZGdldCk6CiAgICAiIiIKICAgIEZ1bGwtd2lkdGggc3RhdHVzIGJhciBzaG93aW5n"
    "OgogICAgICBbIOKcpiBWQU1QSVJFX1NUQVRFICDigKIgIEhIOk1NICDigKIgIOKYgCBTVU5SSVNF"
    "ICDimL0gU1VOU0VUICDigKIgIE1PT04gUEhBU0UgIElMTFVNJSBdCiAgICBBbHdheXMgdmlzaWJs"
    "ZSwgbmV2ZXIgY29sbGFwc2VzLgogICAgVXBkYXRlcyBldmVyeSBtaW51dGUgdmlhIGV4dGVybmFs"
    "IFFUaW1lciBjYWxsIHRvIHJlZnJlc2goKS4KICAgIENvbG9yLWNvZGVkIGJ5IGN1cnJlbnQgdmFt"
    "cGlyZSBzdGF0ZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6"
    "CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fbGFiZWxfcHJl"
    "Zml4ID0gIlNUQVRFIgogICAgICAgIHNlbGYuX3N0YXRlICAgICA9IGdldF92YW1waXJlX3N0YXRl"
    "KCkKICAgICAgICBzZWxmLl90aW1lX3N0ciAgPSAiIgogICAgICAgIHNlbGYuX3N1bnJpc2UgICA9"
    "ICIwNjowMCIKICAgICAgICBzZWxmLl9zdW5zZXQgICAgPSAiMTg6MzAiCiAgICAgICAgc2VsZi5f"
    "c3VuX2RhdGUgID0gTm9uZQogICAgICAgIHNlbGYuX21vb25fbmFtZSA9ICJORVcgTU9PTiIKICAg"
    "ICAgICBzZWxmLl9pbGx1bSAgICAgPSAwLjAKICAgICAgICBzZWxmLnNldEZpeGVkSGVpZ2h0KDI4"
    "KQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRl"
    "ci10b3A6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IikKICAgICAgICBzZWxmLl9mZXRjaF9z"
    "dW5fYXN5bmMoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIHNldF9sYWJlbChzZWxm"
    "LCBsYWJlbDogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xhYmVsX3ByZWZpeCA9IChsYWJl"
    "bCBvciAiU1RBVEUiKS5zdHJpcCgpLnVwcGVyKCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAg"
    "ZGVmIF9mZXRjaF9zdW5fYXN5bmMoc2VsZikgLT4gTm9uZToKICAgICAgICBkZWYgX2YoKToKICAg"
    "ICAgICAgICAgc3IsIHNzID0gZ2V0X3N1bl90aW1lcygpCiAgICAgICAgICAgIHNlbGYuX3N1bnJp"
    "c2UgPSBzcgogICAgICAgICAgICBzZWxmLl9zdW5zZXQgID0gc3MKICAgICAgICAgICAgc2VsZi5f"
    "c3VuX2RhdGUgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkuZGF0ZSgpCiAgICAgICAgICAg"
    "ICMgU2NoZWR1bGUgcmVwYWludCBvbiBtYWluIHRocmVhZCDigJQgbmV2ZXIgY2FsbCB1cGRhdGUo"
    "KSBmcm9tCiAgICAgICAgICAgICMgYSBiYWNrZ3JvdW5kIHRocmVhZCwgaXQgY2F1c2VzIFFUaHJl"
    "YWQgY3Jhc2ggb24gc3RhcnR1cAogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgwLCBzZWxm"
    "LnVwZGF0ZSkKICAgICAgICB0aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fZiwgZGFlbW9uPVRydWUp"
    "LnN0YXJ0KCkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0"
    "YXRlICAgICA9IGdldF92YW1waXJlX3N0YXRlKCkKICAgICAgICBzZWxmLl90aW1lX3N0ciAgPSBk"
    "YXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkuc3RyZnRpbWUoIiVYIikKICAgICAgICB0b2RheSA9"
    "IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAgICAgICBpZiBzZWxmLl9zdW5f"
    "ZGF0ZSAhPSB0b2RheToKICAgICAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkKICAgICAg"
    "ICBfLCBzZWxmLl9tb29uX25hbWUsIHNlbGYuX2lsbHVtID0gZ2V0X21vb25fcGhhc2UoKQogICAg"
    "ICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9u"
    "ZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBh"
    "aW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgo"
    "KSwgc2VsZi5oZWlnaHQoKQoKICAgICAgICBwLmZpbGxSZWN0KDAsIDAsIHcsIGgsIFFDb2xvcihD"
    "X0JHMikpCgogICAgICAgIHN0YXRlX2NvbG9yID0gZ2V0X3ZhbXBpcmVfc3RhdGVfY29sb3Ioc2Vs"
    "Zi5fc3RhdGUpCiAgICAgICAgdGV4dCA9ICgKICAgICAgICAgICAgZiLinKYgIHtzZWxmLl9sYWJl"
    "bF9wcmVmaXh9OiB7c2VsZi5fc3RhdGV9ICDigKIgIHtzZWxmLl90aW1lX3N0cn0gIOKAoiAgIgog"
    "ICAgICAgICAgICBmIuKYgCB7c2VsZi5fc3VucmlzZX0gICAg4pi9IHtzZWxmLl9zdW5zZXR9ICDi"
    "gKIgICIKICAgICAgICAgICAgZiJ7c2VsZi5fbW9vbl9uYW1lfSAge3NlbGYuX2lsbHVtOi4wZn0l"
    "IgogICAgICAgICkKCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgOSwgUUZvbnQu"
    "V2VpZ2h0LkJvbGQpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihzdGF0ZV9jb2xvcikpCiAgICAg"
    "ICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAgICAgICB0dyA9IGZtLmhvcml6b250YWxBZHZhbmNl"
    "KHRleHQpCiAgICAgICAgcC5kcmF3VGV4dCgodyAtIHR3KSAvLyAyLCBoIC0gNywgdGV4dCkKCiAg"
    "ICAgICAgcC5lbmQoKQoKCmNsYXNzIE1pbmlDYWxlbmRhcldpZGdldChRV2lkZ2V0KToKICAgIGRl"
    "ZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhw"
    "YXJlbnQpCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQu"
    "c2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmco"
    "NCkKCiAgICAgICAgaGVhZGVyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGhlYWRlci5zZXRDb250"
    "ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLnByZXZfYnRuID0gUVB1c2hCdXR0"
    "b24oIjw8IikKICAgICAgICBzZWxmLm5leHRfYnRuID0gUVB1c2hCdXR0b24oIj4+IikKICAgICAg"
    "ICBzZWxmLm1vbnRoX2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLm1vbnRoX2xibC5zZXRB"
    "bGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBmb3IgYnRuIGlu"
    "IChzZWxmLnByZXZfYnRuLCBzZWxmLm5leHRfYnRuKToKICAgICAgICAgICAgYnRuLnNldEZpeGVk"
    "V2lkdGgoMzQpCiAgICAgICAgICAgIGJ0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAg"
    "ZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlk"
    "IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDEwcHg7IGZv"
    "bnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAycHg7IgogICAgICAgICAgICApCiAgICAgICAgc2Vs"
    "Zi5tb250aF9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07"
    "IGJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyBmb250LXdlaWdodDogYm9sZDsiCiAgICAg"
    "ICAgKQogICAgICAgIGhlYWRlci5hZGRXaWRnZXQoc2VsZi5wcmV2X2J0bikKICAgICAgICBoZWFk"
    "ZXIuYWRkV2lkZ2V0KHNlbGYubW9udGhfbGJsLCAxKQogICAgICAgIGhlYWRlci5hZGRXaWRnZXQo"
    "c2VsZi5uZXh0X2J0bikKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGhlYWRlcikKCiAgICAgICAg"
    "c2VsZi5jYWxlbmRhciA9IFFDYWxlbmRhcldpZGdldCgpCiAgICAgICAgc2VsZi5jYWxlbmRhci5z"
    "ZXRHcmlkVmlzaWJsZShUcnVlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0VmVydGljYWxIZWFk"
    "ZXJGb3JtYXQoUUNhbGVuZGFyV2lkZ2V0LlZlcnRpY2FsSGVhZGVyRm9ybWF0Lk5vVmVydGljYWxI"
    "ZWFkZXIpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXROYXZpZ2F0aW9uQmFyVmlzaWJsZShGYWxz"
    "ZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUUNh"
    "bGVuZGFyV2lkZ2V0IFFXaWRnZXR7e2FsdGVybmF0ZS1iYWNrZ3JvdW5kLWNvbG9yOntDX0JHMn07"
    "fX0gIgogICAgICAgICAgICBmIlFUb29sQnV0dG9ue3tjb2xvcjp7Q19HT0xEfTt9fSAiCiAgICAg"
    "ICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFBYnN0cmFjdEl0ZW1WaWV3OmVuYWJsZWR7e2JhY2tn"
    "cm91bmQ6e0NfQkcyfTsgY29sb3I6I2ZmZmZmZjsgIgogICAgICAgICAgICBmInNlbGVjdGlvbi1i"
    "YWNrZ3JvdW5kLWNvbG9yOntDX0NSSU1TT05fRElNfTsgc2VsZWN0aW9uLWNvbG9yOntDX1RFWFR9"
    "OyBncmlkbGluZS1jb2xvcjp7Q19CT1JERVJ9O319ICIKICAgICAgICAgICAgZiJRQ2FsZW5kYXJX"
    "aWRnZXQgUUFic3RyYWN0SXRlbVZpZXc6ZGlzYWJsZWR7e2NvbG9yOiM4Yjk1YTE7fX0iCiAgICAg"
    "ICAgKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5jYWxlbmRhcikKCiAgICAgICAgc2Vs"
    "Zi5wcmV2X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLmNhbGVuZGFyLnNob3dQcmV2"
    "aW91c01vbnRoKCkpCiAgICAgICAgc2VsZi5uZXh0X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRh"
    "OiBzZWxmLmNhbGVuZGFyLnNob3dOZXh0TW9udGgoKSkKICAgICAgICBzZWxmLmNhbGVuZGFyLmN1"
    "cnJlbnRQYWdlQ2hhbmdlZC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9sYWJlbCkKICAgICAgICBzZWxm"
    "Ll91cGRhdGVfbGFiZWwoKQogICAgICAgIHNlbGYuX2FwcGx5X2Zvcm1hdHMoKQoKICAgIGRlZiBf"
    "dXBkYXRlX2xhYmVsKHNlbGYsICphcmdzKToKICAgICAgICB5ZWFyID0gc2VsZi5jYWxlbmRhci55"
    "ZWFyU2hvd24oKQogICAgICAgIG1vbnRoID0gc2VsZi5jYWxlbmRhci5tb250aFNob3duKCkKICAg"
    "ICAgICBzZWxmLm1vbnRoX2xibC5zZXRUZXh0KGYie2RhdGUoeWVhciwgbW9udGgsIDEpLnN0cmZ0"
    "aW1lKCclQiAlWScpfSIpCiAgICAgICAgc2VsZi5fYXBwbHlfZm9ybWF0cygpCgogICAgZGVmIF9h"
    "cHBseV9mb3JtYXRzKHNlbGYpOgogICAgICAgIGJhc2UgPSBRVGV4dENoYXJGb3JtYXQoKQogICAg"
    "ICAgIGJhc2Uuc2V0Rm9yZWdyb3VuZChRQ29sb3IoIiNlN2VkZjMiKSkKICAgICAgICBzYXR1cmRh"
    "eSA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgc2F0dXJkYXkuc2V0Rm9yZWdyb3VuZChRQ29s"
    "b3IoQ19HT0xEX0RJTSkpCiAgICAgICAgc3VuZGF5ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAg"
    "ICBzdW5kYXkuc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19CTE9PRCkpCiAgICAgICAgc2VsZi5jYWxl"
    "bmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuTW9uZGF5LCBiYXNlKQogICAg"
    "ICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlR1ZXNk"
    "YXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5E"
    "YXlPZldlZWsuV2VkbmVzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2Rh"
    "eVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlRodXJzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2Fs"
    "ZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLkZyaWRheSwgYmFzZSkKICAg"
    "ICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5TYXR1"
    "cmRheSwgc2F0dXJkYXkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1h"
    "dChRdC5EYXlPZldlZWsuU3VuZGF5LCBzdW5kYXkpCgogICAgICAgIHllYXIgPSBzZWxmLmNhbGVu"
    "ZGFyLnllYXJTaG93bigpCiAgICAgICAgbW9udGggPSBzZWxmLmNhbGVuZGFyLm1vbnRoU2hvd24o"
    "KQogICAgICAgIGZpcnN0X2RheSA9IFFEYXRlKHllYXIsIG1vbnRoLCAxKQogICAgICAgIGZvciBk"
    "YXkgaW4gcmFuZ2UoMSwgZmlyc3RfZGF5LmRheXNJbk1vbnRoKCkgKyAxKToKICAgICAgICAgICAg"
    "ZCA9IFFEYXRlKHllYXIsIG1vbnRoLCBkYXkpCiAgICAgICAgICAgIGZtdCA9IFFUZXh0Q2hhckZv"
    "cm1hdCgpCiAgICAgICAgICAgIHdlZWtkYXkgPSBkLmRheU9mV2VlaygpCiAgICAgICAgICAgIGlm"
    "IHdlZWtkYXkgPT0gUXQuRGF5T2ZXZWVrLlNhdHVyZGF5LnZhbHVlOgogICAgICAgICAgICAgICAg"
    "Zm10LnNldEZvcmVncm91bmQoUUNvbG9yKENfR09MRF9ESU0pKQogICAgICAgICAgICBlbGlmIHdl"
    "ZWtkYXkgPT0gUXQuRGF5T2ZXZWVrLlN1bmRheS52YWx1ZToKICAgICAgICAgICAgICAgIGZtdC5z"
    "ZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0JMT09EKSkKICAgICAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcigiI2U3ZWRmMyIpKQogICAgICAgICAgICBz"
    "ZWxmLmNhbGVuZGFyLnNldERhdGVUZXh0Rm9ybWF0KGQsIGZtdCkKCiAgICAgICAgdG9kYXlfZm10"
    "ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICB0b2RheV9mbXQuc2V0Rm9yZWdyb3VuZChRQ29s"
    "b3IoIiM2OGQzOWEiKSkKICAgICAgICB0b2RheV9mbXQuc2V0QmFja2dyb3VuZChRQ29sb3IoIiMx"
    "NjM4MjUiKSkKICAgICAgICB0b2RheV9mbXQuc2V0Rm9udFdlaWdodChRRm9udC5XZWlnaHQuQm9s"
    "ZCkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldERhdGVUZXh0Rm9ybWF0KFFEYXRlLmN1cnJlbnRE"
    "YXRlKCksIHRvZGF5X2ZtdCkKCgojIOKUgOKUgCBDT0xMQVBTSUJMRSBCTE9DSyDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgQ29s"
    "bGFwc2libGVCbG9jayhRV2lkZ2V0KToKICAgICIiIgogICAgV3JhcHBlciB0aGF0IGFkZHMgYSBj"
    "b2xsYXBzZS9leHBhbmQgdG9nZ2xlIHRvIGFueSB3aWRnZXQuCiAgICBDb2xsYXBzZXMgaG9yaXpv"
    "bnRhbGx5IChyaWdodHdhcmQpIOKAlCBoaWRlcyBjb250ZW50LCBrZWVwcyBoZWFkZXIgc3RyaXAu"
    "CiAgICBIZWFkZXIgc2hvd3MgbGFiZWwuIFRvZ2dsZSBidXR0b24gb24gcmlnaHQgZWRnZSBvZiBo"
    "ZWFkZXIuCgogICAgVXNhZ2U6CiAgICAgICAgYmxvY2sgPSBDb2xsYXBzaWJsZUJsb2NrKCLinacg"
    "QkxPT0QiLCBTcGhlcmVXaWRnZXQoLi4uKSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGJsb2Nr"
    "KQogICAgIiIiCgogICAgdG9nZ2xlZCA9IFNpZ25hbChib29sKQoKICAgIGRlZiBfX2luaXRfXyhz"
    "ZWxmLCBsYWJlbDogc3RyLCBjb250ZW50OiBRV2lkZ2V0LAogICAgICAgICAgICAgICAgIGV4cGFu"
    "ZGVkOiBib29sID0gVHJ1ZSwgbWluX3dpZHRoOiBpbnQgPSA5MCwKICAgICAgICAgICAgICAgICBy"
    "ZXNlcnZlX3dpZHRoOiBib29sID0gRmFsc2UsCiAgICAgICAgICAgICAgICAgcGFyZW50PU5vbmUp"
    "OgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX2V4cGFuZGVk"
    "ICAgICAgID0gZXhwYW5kZWQKICAgICAgICBzZWxmLl9taW5fd2lkdGggICAgICA9IG1pbl93aWR0"
    "aAogICAgICAgIHNlbGYuX3Jlc2VydmVfd2lkdGggID0gcmVzZXJ2ZV93aWR0aAogICAgICAgIHNl"
    "bGYuX2NvbnRlbnQgICAgICAgID0gY29udGVudAoKICAgICAgICBtYWluID0gUVZCb3hMYXlvdXQo"
    "c2VsZikKICAgICAgICBtYWluLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAg"
    "IG1haW4uc2V0U3BhY2luZygwKQoKICAgICAgICAjIEhlYWRlcgogICAgICAgIHNlbGYuX2hlYWRl"
    "ciA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2hlYWRlci5zZXRGaXhlZEhlaWdodCgyMikKICAg"
    "ICAgICBzZWxmLl9oZWFkZXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5k"
    "OiB7Q19CRzN9OyBib3JkZXItYm90dG9tOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAg"
    "ICAgICAgICAgIGYiYm9yZGVyLXRvcDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAg"
    "ICAgKQogICAgICAgIGhsID0gUUhCb3hMYXlvdXQoc2VsZi5faGVhZGVyKQogICAgICAgIGhsLnNl"
    "dENvbnRlbnRzTWFyZ2lucyg2LCAwLCA0LCAwKQogICAgICAgIGhsLnNldFNwYWNpbmcoNCkKCiAg"
    "ICAgICAgc2VsZi5fbGJsID0gUUxhYmVsKGxhYmVsKQogICAgICAgIHNlbGYuX2xibC5zZXRTdHls"
    "ZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGZv"
    "bnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9"
    "LCBzZXJpZjsgbGV0dGVyLXNwYWNpbmc6IDFweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCgog"
    "ICAgICAgIHNlbGYuX2J0biA9IFFUb29sQnV0dG9uKCkKICAgICAgICBzZWxmLl9idG4uc2V0Rml4"
    "ZWRTaXplKDE2LCAxNikKICAgICAgICBzZWxmLl9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgZiJiYWNrZ3JvdW5kOiB0cmFuc3BhcmVudDsgY29sb3I6IHtDX0dPTERfRElNfTsgYm9yZGVy"
    "OiBub25lOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl9idG4uc2V0"
    "VGV4dCgiPCIpCiAgICAgICAgc2VsZi5fYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGUp"
    "CgogICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl9sYmwpCiAgICAgICAgaGwuYWRkU3RyZXRjaCgp"
    "CiAgICAgICAgaGwuYWRkV2lkZ2V0KHNlbGYuX2J0bikKCiAgICAgICAgbWFpbi5hZGRXaWRnZXQo"
    "c2VsZi5faGVhZGVyKQogICAgICAgIG1haW4uYWRkV2lkZ2V0KHNlbGYuX2NvbnRlbnQpCgogICAg"
    "ICAgIHNlbGYuX2FwcGx5X3N0YXRlKCkKCiAgICBkZWYgaXNfZXhwYW5kZWQoc2VsZikgLT4gYm9v"
    "bDoKICAgICAgICByZXR1cm4gc2VsZi5fZXhwYW5kZWQKCiAgICBkZWYgX3RvZ2dsZShzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAgICAg"
    "ICAgc2VsZi5fYXBwbHlfc3RhdGUoKQogICAgICAgIHNlbGYudG9nZ2xlZC5lbWl0KHNlbGYuX2V4"
    "cGFuZGVkKQoKICAgIGRlZiBfYXBwbHlfc3RhdGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9jb250ZW50LnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCiAgICAgICAgc2VsZi5fYnRuLnNl"
    "dFRleHQoIjwiIGlmIHNlbGYuX2V4cGFuZGVkIGVsc2UgIj4iKQoKICAgICAgICAjIFJlc2VydmUg"
    "Zml4ZWQgc2xvdCB3aWR0aCB3aGVuIHJlcXVlc3RlZCAodXNlZCBieSBtaWRkbGUgbG93ZXIgYmxv"
    "Y2spCiAgICAgICAgaWYgc2VsZi5fcmVzZXJ2ZV93aWR0aDoKICAgICAgICAgICAgc2VsZi5zZXRN"
    "aW5pbXVtV2lkdGgoc2VsZi5fbWluX3dpZHRoKQogICAgICAgICAgICBzZWxmLnNldE1heGltdW1X"
    "aWR0aCgxNjc3NzIxNSkKICAgICAgICBlbGlmIHNlbGYuX2V4cGFuZGVkOgogICAgICAgICAgICBz"
    "ZWxmLnNldE1pbmltdW1XaWR0aChzZWxmLl9taW5fd2lkdGgpCiAgICAgICAgICAgIHNlbGYuc2V0"
    "TWF4aW11bVdpZHRoKDE2Nzc3MjE1KSAgIyB1bmNvbnN0cmFpbmVkCiAgICAgICAgZWxzZToKICAg"
    "ICAgICAgICAgIyBDb2xsYXBzZWQ6IGp1c3QgdGhlIGhlYWRlciBzdHJpcCAobGFiZWwgKyBidXR0"
    "b24pCiAgICAgICAgICAgIGNvbGxhcHNlZF93ID0gc2VsZi5faGVhZGVyLnNpemVIaW50KCkud2lk"
    "dGgoKQogICAgICAgICAgICBzZWxmLnNldEZpeGVkV2lkdGgobWF4KDYwLCBjb2xsYXBzZWRfdykp"
    "CgogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0cnkoKQogICAgICAgIHBhcmVudCA9IHNlbGYucGFy"
    "ZW50V2lkZ2V0KCkKICAgICAgICBpZiBwYXJlbnQgYW5kIHBhcmVudC5sYXlvdXQoKToKICAgICAg"
    "ICAgICAgcGFyZW50LmxheW91dCgpLmFjdGl2YXRlKCkKCgojIOKUgOKUgCBIQVJEV0FSRSBQQU5F"
    "TCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgSGFyZHdhcmVQYW5lbChRV2lkZ2V0KToKICAgICIiIgogICAgVGhl"
    "IHN5c3RlbXMgcmlnaHQgcGFuZWwgY29udGVudHMuCiAgICBHcm91cHM6IHN0YXR1cyBpbmZvLCBk"
    "cml2ZSBiYXJzLCBDUFUvUkFNIGdhdWdlcywgR1BVL1ZSQU0gZ2F1Z2VzLCBHUFUgdGVtcC4KICAg"
    "IFJlcG9ydHMgaGFyZHdhcmUgYXZhaWxhYmlsaXR5IGluIERpYWdub3N0aWNzIG9uIHN0YXJ0dXAu"
    "CiAgICBTaG93cyBOL0EgZ3JhY2VmdWxseSB3aGVuIGRhdGEgdW5hdmFpbGFibGUuCiAgICAiIiIK"
    "CiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19p"
    "bml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLl9kZXRl"
    "Y3RfaGFyZHdhcmUoKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICBs"
    "YXlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdp"
    "bnMoNCwgNCwgNCwgNCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICBkZWYg"
    "c2VjdGlvbl9sYWJlbCh0ZXh0OiBzdHIpIC0+IFFMYWJlbDoKICAgICAgICAgICAgbGJsID0gUUxh"
    "YmVsKHRleHQpCiAgICAgICAgICAgIGxibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAg"
    "ZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogOXB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyAi"
    "CiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQt"
    "d2VpZ2h0OiBib2xkOyIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4gbGJsCgogICAg"
    "ICAgICMg4pSA4pSAIFN0YXR1cyBibG9jayDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICBsYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKdpyBTVEFUVVMiKSkKICAgICAgICBz"
    "dGF0dXNfZnJhbWUgPSBRRnJhbWUoKQogICAgICAgIHN0YXR1c19mcmFtZS5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX1BBTkVMfTsgYm9yZGVyOiAxcHggc29saWQg"
    "e0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCiAgICAgICAgc3RhdHVz"
    "X2ZyYW1lLnNldEZpeGVkSGVpZ2h0KDg4KQogICAgICAgIHNmID0gUVZCb3hMYXlvdXQoc3RhdHVz"
    "X2ZyYW1lKQogICAgICAgIHNmLnNldENvbnRlbnRzTWFyZ2lucyg4LCA0LCA4LCA0KQogICAgICAg"
    "IHNmLnNldFNwYWNpbmcoMikKCiAgICAgICAgc2VsZi5sYmxfc3RhdHVzICA9IFFMYWJlbCgi4pym"
    "IFNUQVRVUzogT0ZGTElORSIpCiAgICAgICAgc2VsZi5sYmxfbW9kZWwgICA9IFFMYWJlbCgi4pym"
    "IFZFU1NFTDogTE9BRElORy4uLiIpCiAgICAgICAgc2VsZi5sYmxfc2Vzc2lvbiA9IFFMYWJlbCgi"
    "4pymIFNFU1NJT046IDAwOjAwOjAwIikKICAgICAgICBzZWxmLmxibF90b2tlbnMgID0gUUxhYmVs"
    "KCLinKYgVE9LRU5TOiAwIikKCiAgICAgICAgZm9yIGxibCBpbiAoc2VsZi5sYmxfc3RhdHVzLCBz"
    "ZWxmLmxibF9tb2RlbCwKICAgICAgICAgICAgICAgICAgICBzZWxmLmxibF9zZXNzaW9uLCBzZWxm"
    "LmxibF90b2tlbnMpOgogICAgICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgICAg"
    "ICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGJvcmRlcjogbm9uZTsiCiAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgc2YuYWRkV2lkZ2V0KGxibCkKCiAgICAgICAgbGF5b3V0"
    "LmFkZFdpZGdldChzdGF0dXNfZnJhbWUpCgogICAgICAgICMg4pSA4pSAIERyaXZlIGJhcnMg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0"
    "aW9uX2xhYmVsKCLinacgU1RPUkFHRSIpKQogICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0ID0gRHJp"
    "dmVXaWRnZXQoKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5kcml2ZV93aWRnZXQpCgog"
    "ICAgICAgICMg4pSA4pSAIENQVSAvIFJBTSBnYXVnZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5"
    "b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgVklUQUwgRVNTRU5DRSIpKQogICAgICAg"
    "IHJhbV9jcHUgPSBRR3JpZExheW91dCgpCiAgICAgICAgcmFtX2NwdS5zZXRTcGFjaW5nKDMpCgog"
    "ICAgICAgIHNlbGYuZ2F1Z2VfY3B1ICA9IEdhdWdlV2lkZ2V0KCJDUFUiLCAgIiUiLCAgIDEwMC4w"
    "LCBDX1NJTFZFUikKICAgICAgICBzZWxmLmdhdWdlX3JhbSAgPSBHYXVnZVdpZGdldCgiUkFNIiwg"
    "ICJHQiIsICAgNjQuMCwgQ19HT0xEX0RJTSkKICAgICAgICByYW1fY3B1LmFkZFdpZGdldChzZWxm"
    "LmdhdWdlX2NwdSwgMCwgMCkKICAgICAgICByYW1fY3B1LmFkZFdpZGdldChzZWxmLmdhdWdlX3Jh"
    "bSwgMCwgMSkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KHJhbV9jcHUpCgogICAgICAgICMg4pSA"
    "4pSAIEdQVSAvIFZSQU0gZ2F1Z2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQo"
    "c2VjdGlvbl9sYWJlbCgi4p2nIEFSQ0FORSBQT1dFUiIpKQogICAgICAgIGdwdV92cmFtID0gUUdy"
    "aWRMYXlvdXQoKQogICAgICAgIGdwdV92cmFtLnNldFNwYWNpbmcoMykKCiAgICAgICAgc2VsZi5n"
    "YXVnZV9ncHUgID0gR2F1Z2VXaWRnZXQoIkdQVSIsICAiJSIsICAgMTAwLjAsIENfUFVSUExFKQog"
    "ICAgICAgIHNlbGYuZ2F1Z2VfdnJhbSA9IEdhdWdlV2lkZ2V0KCJWUkFNIiwgIkdCIiwgICAgOC4w"
    "LCBDX0NSSU1TT04pCiAgICAgICAgZ3B1X3ZyYW0uYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfZ3B1LCAg"
    "MCwgMCkKICAgICAgICBncHVfdnJhbS5hZGRXaWRnZXQoc2VsZi5nYXVnZV92cmFtLCAwLCAxKQog"
    "ICAgICAgIGxheW91dC5hZGRMYXlvdXQoZ3B1X3ZyYW0pCgogICAgICAgICMg4pSA4pSAIEdQVSBU"
    "ZW1wIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5h"
    "ZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEhFQVQiKSkKICAgICAgICBzZWxm"
    "LmdhdWdlX3RlbXAgPSBHYXVnZVdpZGdldCgiR1BVIFRFTVAiLCAiwrBDIiwgOTUuMCwgQ19CTE9P"
    "RCkKICAgICAgICBzZWxmLmdhdWdlX3RlbXAuc2V0TWF4aW11bUhlaWdodCg2NSkKICAgICAgICBs"
    "YXlvdXQuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfdGVtcCkKCiAgICAgICAgIyDilIDilIAgR1BVIG1h"
    "c3RlciBiYXIgKGZ1bGwgd2lkdGgpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEVO"
    "R0lORSIpKQogICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3RlciA9IEdhdWdlV2lkZ2V0KCJSVFgi"
    "LCAiJSIsIDEwMC4wLCBDX0NSSU1TT04pCiAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNl"
    "dE1heGltdW1IZWlnaHQoNTUpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmdhdWdlX2dw"
    "dV9tYXN0ZXIpCgogICAgICAgIGxheW91dC5hZGRTdHJldGNoKCkKCiAgICBkZWYgX2RldGVjdF9o"
    "YXJkd2FyZShzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENoZWNrIHdoYXQgaGFy"
    "ZHdhcmUgbW9uaXRvcmluZyBpcyBhdmFpbGFibGUuCiAgICAgICAgTWFyayB1bmF2YWlsYWJsZSBn"
    "YXVnZXMgYXBwcm9wcmlhdGVseS4KICAgICAgICBEaWFnbm9zdGljIG1lc3NhZ2VzIGNvbGxlY3Rl"
    "ZCBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgICAgICAiIiIKICAgICAgICBzZWxmLl9kaWFn"
    "X21lc3NhZ2VzOiBsaXN0W3N0cl0gPSBbXQoKICAgICAgICBpZiBub3QgUFNVVElMX09LOgogICAg"
    "ICAgICAgICBzZWxmLmdhdWdlX2NwdS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYu"
    "Z2F1Z2VfcmFtLnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdl"
    "cy5hcHBlbmQoCiAgICAgICAgICAgICAgICAiW0hBUkRXQVJFXSBwc3V0aWwgbm90IGF2YWlsYWJs"
    "ZSDigJQgQ1BVL1JBTSBnYXVnZXMgZGlzYWJsZWQuICIKICAgICAgICAgICAgICAgICJwaXAgaW5z"
    "dGFsbCBwc3V0aWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAg"
    "ICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKCJbSEFSRFdBUkVdIHBzdXRpbCBPSyDi"
    "gJQgQ1BVL1JBTSBtb25pdG9yaW5nIGFjdGl2ZS4iKQoKICAgICAgICBpZiBub3QgTlZNTF9PSzoK"
    "ICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHUuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBz"
    "ZWxmLmdhdWdlX3ZyYW0uc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX3Rl"
    "bXAuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIuc2V0"
    "VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAg"
    "ICAgICAgICAgICAgICJbSEFSRFdBUkVdIHB5bnZtbCBub3QgYXZhaWxhYmxlIG9yIG5vIE5WSURJ"
    "QSBHUFUgZGV0ZWN0ZWQg4oCUICIKICAgICAgICAgICAgICAgICJHUFUgZ2F1Z2VzIGRpc2FibGVk"
    "LiBwaXAgaW5zdGFsbCBweW52bWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVs"
    "c2U6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERl"
    "dmljZUdldE5hbWUoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIGlmIGlzaW5zdGFuY2UobmFt"
    "ZSwgYnl0ZXMpOgogICAgICAgICAgICAgICAgICAgIG5hbWUgPSBuYW1lLmRlY29kZSgpCiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICAg"
    "ICBmIltIQVJEV0FSRV0gcHludm1sIE9LIOKAlCBHUFUgZGV0ZWN0ZWQ6IHtuYW1lfSIKICAgICAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgICAgICMgVXBkYXRlIG1heCBWUkFNIGZyb20gYWN0dWFs"
    "IGhhcmR3YXJlCiAgICAgICAgICAgICAgICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9y"
    "eUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIHRvdGFsX2diID0gbWVtLnRvdGFsIC8g"
    "MTAyNCoqMwogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV92cmFtLm1heF92YWwgPSB0b3RhbF9n"
    "YgogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX21lc3NhZ2VzLmFwcGVuZChmIltIQVJEV0FSRV0gcHludm1sIGVycm9yOiB7ZX0iKQoK"
    "ICAgIGRlZiB1cGRhdGVfc3RhdHMoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBD"
    "YWxsZWQgZXZlcnkgc2Vjb25kIGZyb20gdGhlIHN0YXRzIFFUaW1lci4KICAgICAgICBSZWFkcyBo"
    "YXJkd2FyZSBhbmQgdXBkYXRlcyBhbGwgZ2F1Z2VzLgogICAgICAgICIiIgogICAgICAgIGlmIFBT"
    "VVRJTF9PSzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY3B1ID0gcHN1dGlsLmNw"
    "dV9wZXJjZW50KCkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfY3B1LnNldFZhbHVlKGNwdSwg"
    "ZiJ7Y3B1Oi4wZn0lIiwgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICAgICAgICAgbWVtID0gcHN1"
    "dGlsLnZpcnR1YWxfbWVtb3J5KCkKICAgICAgICAgICAgICAgIHJ1ICA9IG1lbS51c2VkICAvIDEw"
    "MjQqKjMKICAgICAgICAgICAgICAgIHJ0ICA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAgICAgICAg"
    "ICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFZhbHVlKHJ1LCBmIntydTouMWZ9L3tydDouMGZ9R0Ii"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUp"
    "CiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3JhbS5tYXhfdmFsID0gcnQKICAgICAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgaWYgTlZNTF9P"
    "SyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgdXRpbCAg"
    "ICAgPSBweW52bWwubnZtbERldmljZUdldFV0aWxpemF0aW9uUmF0ZXMoZ3B1X2hhbmRsZSkKICAg"
    "ICAgICAgICAgICAgIG1lbV9pbmZvID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdw"
    "dV9oYW5kbGUpCiAgICAgICAgICAgICAgICB0ZW1wICAgICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0"
    "VGVtcGVyYXR1cmUoCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBncHVfaGFuZGxlLCBw"
    "eW52bWwuTlZNTF9URU1QRVJBVFVSRV9HUFUpCgogICAgICAgICAgICAgICAgZ3B1X3BjdCAgID0g"
    "ZmxvYXQodXRpbC5ncHUpCiAgICAgICAgICAgICAgICB2cmFtX3VzZWQgPSBtZW1faW5mby51c2Vk"
    "ICAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHZyYW1fdG90ICA9IG1lbV9pbmZvLnRvdGFsIC8g"
    "MTAyNCoqMwoKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1LnNldFZhbHVlKGdwdV9wY3Qs"
    "IGYie2dwdV9wY3Q6LjBmfSUiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VmFs"
    "dWUodnJhbV91c2VkLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYi"
    "e3ZyYW1fdXNlZDouMWZ9L3t2cmFtX3RvdDouMGZ9R0IiLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAgICAgc2VsZi5n"
    "YXVnZV90ZW1wLnNldFZhbHVlKGZsb2F0KHRlbXApLCBmInt0ZW1wfcKwQyIsCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdl"
    "dE5hbWUoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgICAgICBpZiBpc2luc3RhbmNlKG5hbWUs"
    "IGJ5dGVzKToKICAgICAgICAgICAgICAgICAgICAgICAgbmFtZSA9IG5hbWUuZGVjb2RlKCkKICAg"
    "ICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgbmFtZSA9"
    "ICJHUFUiCgogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldFZhbHVlKAog"
    "ICAgICAgICAgICAgICAgICAgIGdwdV9wY3QsCiAgICAgICAgICAgICAgICAgICAgZiJ7bmFtZX0g"
    "IHtncHVfcGN0Oi4wZn0lICAiCiAgICAgICAgICAgICAgICAgICAgZiJbe3ZyYW1fdXNlZDouMWZ9"
    "L3t2cmFtX3RvdDouMGZ9R0IgVlJBTV0iLAogICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1U"
    "cnVlLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFVwZGF0ZSBkcml2ZSBiYXJzIGV2ZXJ5IDMwIHNl"
    "Y29uZHMgKG5vdCBldmVyeSB0aWNrKQogICAgICAgIGlmIG5vdCBoYXNhdHRyKHNlbGYsICJfZHJp"
    "dmVfdGljayIpOgogICAgICAgICAgICBzZWxmLl9kcml2ZV90aWNrID0gMAogICAgICAgIHNlbGYu"
    "X2RyaXZlX3RpY2sgKz0gMQogICAgICAgIGlmIHNlbGYuX2RyaXZlX3RpY2sgPj0gMzA6CiAgICAg"
    "ICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgPSAwCiAgICAgICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0"
    "LnJlZnJlc2goKQoKICAgIGRlZiBzZXRfc3RhdHVzX2xhYmVscyhzZWxmLCBzdGF0dXM6IHN0ciwg"
    "bW9kZWw6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgICAgICBzZXNzaW9uOiBzdHIsIHRva2Vu"
    "czogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYubGJsX3N0YXR1cy5zZXRUZXh0KGYi4pymIFNU"
    "QVRVUzoge3N0YXR1c30iKQogICAgICAgIHNlbGYubGJsX21vZGVsLnNldFRleHQoZiLinKYgVkVT"
    "U0VMOiB7bW9kZWx9IikKICAgICAgICBzZWxmLmxibF9zZXNzaW9uLnNldFRleHQoZiLinKYgU0VT"
    "U0lPTjoge3Nlc3Npb259IikKICAgICAgICBzZWxmLmxibF90b2tlbnMuc2V0VGV4dChmIuKcpiBU"
    "T0tFTlM6IHt0b2tlbnN9IikKCiAgICBkZWYgZ2V0X2RpYWdub3N0aWNzKHNlbGYpIC0+IGxpc3Rb"
    "c3RyXToKICAgICAgICByZXR1cm4gZ2V0YXR0cihzZWxmLCAiX2RpYWdfbWVzc2FnZXMiLCBbXSkK"
    "CgojIOKUgOKUgCBQQVNTIDIgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQWxsIHdpZGdldCBjbGFzc2Vz"
    "IGRlZmluZWQuIFN5bnRheC1jaGVja2FibGUgaW5kZXBlbmRlbnRseS4KIyBOZXh0OiBQYXNzIDMg"
    "4oCUIFdvcmtlciBUaHJlYWRzCiMgKERvbHBoaW5Xb3JrZXIgd2l0aCBzdHJlYW1pbmcsIFNlbnRp"
    "bWVudFdvcmtlciwgSWRsZVdvcmtlciwgU291bmRXb3JrZXIpCgoKIyDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JH"
    "QU5OQSBERUNLIOKAlCBQQVNTIDM6IFdPUktFUiBUSFJFQURTCiMKIyBXb3JrZXJzIGRlZmluZWQg"
    "aGVyZToKIyAgIExMTUFkYXB0b3IgKGJhc2UgKyBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IgKyBP"
    "bGxhbWFBZGFwdG9yICsKIyAgICAgICAgICAgICAgIENsYXVkZUFkYXB0b3IgKyBPcGVuQUlBZGFw"
    "dG9yKQojICAgU3RyZWFtaW5nV29ya2VyICAg4oCUIG1haW4gZ2VuZXJhdGlvbiwgZW1pdHMgdG9r"
    "ZW5zIG9uZSBhdCBhIHRpbWUKIyAgIFNlbnRpbWVudFdvcmtlciAgIOKAlCBjbGFzc2lmaWVzIGVt"
    "b3Rpb24gZnJvbSByZXNwb25zZSB0ZXh0CiMgICBJZGxlV29ya2VyICAgICAgICDigJQgdW5zb2xp"
    "Y2l0ZWQgdHJhbnNtaXNzaW9ucyBkdXJpbmcgaWRsZQojICAgU291bmRXb3JrZXIgICAgICAg4oCU"
    "IHBsYXlzIHNvdW5kcyBvZmYgdGhlIG1haW4gdGhyZWFkCiMKIyBBTEwgZ2VuZXJhdGlvbiBpcyBz"
    "dHJlYW1pbmcuIE5vIGJsb2NraW5nIGNhbGxzIG9uIG1haW4gdGhyZWFkLiBFdmVyLgojIOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkAoKaW1wb3J0IGFiYwppbXBvcnQganNvbgppbXBvcnQgdXJsbGliLnJlcXVlc3QKaW1wb3J0"
    "IHVybGxpYi5lcnJvcgppbXBvcnQgaHR0cC5jbGllbnQKZnJvbSB0eXBpbmcgaW1wb3J0IEl0ZXJh"
    "dG9yCgoKIyDilIDilIAgTExNIEFEQVBUT1IgQkFTRSDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTExNQWRhcHRvcihhYmMuQUJD"
    "KToKICAgICIiIgogICAgQWJzdHJhY3QgYmFzZSBmb3IgYWxsIG1vZGVsIGJhY2tlbmRzLgogICAg"
    "VGhlIGRlY2sgY2FsbHMgc3RyZWFtKCkgb3IgZ2VuZXJhdGUoKSDigJQgbmV2ZXIga25vd3Mgd2hp"
    "Y2ggYmFja2VuZCBpcyBhY3RpdmUuCiAgICAiIiIKCiAgICBAYWJjLmFic3RyYWN0bWV0aG9kCiAg"
    "ICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgIiIiUmV0dXJuIFRydWUg"
    "aWYgdGhlIGJhY2tlbmQgaXMgcmVhY2hhYmxlLiIiIgogICAgICAgIC4uLgoKICAgIEBhYmMuYWJz"
    "dHJhY3RtZXRob2QKICAgIGRlZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6"
    "IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAog"
    "ICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06"
    "CiAgICAgICAgIiIiCiAgICAgICAgWWllbGQgcmVzcG9uc2UgdGV4dCB0b2tlbi1ieS10b2tlbiAo"
    "b3IgY2h1bmstYnktY2h1bmsgZm9yIEFQSSBiYWNrZW5kcykuCiAgICAgICAgTXVzdCBiZSBhIGdl"
    "bmVyYXRvci4gTmV2ZXIgYmxvY2sgZm9yIHRoZSBmdWxsIHJlc3BvbnNlIGJlZm9yZSB5aWVsZGlu"
    "Zy4KICAgICAgICAiIiIKICAgICAgICAuLi4KCiAgICBkZWYgZ2VuZXJhdGUoCiAgICAgICAgc2Vs"
    "ZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0"
    "b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICAp"
    "IC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBDb252ZW5pZW5jZSB3cmFwcGVyOiBjb2xsZWN0"
    "IGFsbCBzdHJlYW0gdG9rZW5zIGludG8gb25lIHN0cmluZy4KICAgICAgICBVc2VkIGZvciBzZW50"
    "aW1lbnQgY2xhc3NpZmljYXRpb24gKHNtYWxsIGJvdW5kZWQgY2FsbHMgb25seSkuCiAgICAgICAg"
    "IiIiCiAgICAgICAgcmV0dXJuICIiLmpvaW4oc2VsZi5zdHJlYW0ocHJvbXB0LCBzeXN0ZW0sIGhp"
    "c3RvcnksIG1heF9uZXdfdG9rZW5zKSkKCiAgICBkZWYgYnVpbGRfY2hhdG1sX3Byb21wdChzZWxm"
    "LCBzeXN0ZW06IHN0ciwgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICB1c2VyX3RleHQ6IHN0ciA9ICIiKSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAg"
    "QnVpbGQgYSBDaGF0TUwtZm9ybWF0IHByb21wdCBzdHJpbmcgZm9yIGxvY2FsIG1vZGVscy4KICAg"
    "ICAgICBoaXN0b3J5ID0gW3sicm9sZSI6ICJ1c2VyInwiYXNzaXN0YW50IiwgImNvbnRlbnQiOiAi"
    "Li4uIn1dCiAgICAgICAgIiIiCiAgICAgICAgcGFydHMgPSBbZiI8fGltX3N0YXJ0fD5zeXN0ZW1c"
    "bntzeXN0ZW19PHxpbV9lbmR8PiJdCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAg"
    "ICAgICByb2xlICAgID0gbXNnLmdldCgicm9sZSIsICJ1c2VyIikKICAgICAgICAgICAgY29udGVu"
    "dCA9IG1zZy5nZXQoImNvbnRlbnQiLCAiIikKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGYiPHxp"
    "bV9zdGFydHw+e3JvbGV9XG57Y29udGVudH08fGltX2VuZHw+IikKICAgICAgICBpZiB1c2VyX3Rl"
    "eHQ6CiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChmIjx8aW1fc3RhcnR8PnVzZXJcbnt1c2VyX3Rl"
    "eHR9PHxpbV9lbmR8PiIpCiAgICAgICAgcGFydHMuYXBwZW5kKCI8fGltX3N0YXJ0fD5hc3Npc3Rh"
    "bnRcbiIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCgojIOKUgOKUgCBMT0NBTCBU"
    "UkFOU0ZPUk1FUlMgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3Mg"
    "TG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBMb2FkcyBh"
    "IEh1Z2dpbmdGYWNlIG1vZGVsIGZyb20gYSBsb2NhbCBmb2xkZXIuCiAgICBTdHJlYW1pbmc6IHVz"
    "ZXMgbW9kZWwuZ2VuZXJhdGUoKSB3aXRoIGEgY3VzdG9tIHN0cmVhbWVyIHRoYXQgeWllbGRzIHRv"
    "a2Vucy4KICAgIFJlcXVpcmVzOiB0b3JjaCwgdHJhbnNmb3JtZXJzCiAgICAiIiIKCiAgICBkZWYg"
    "X19pbml0X18oc2VsZiwgbW9kZWxfcGF0aDogc3RyKToKICAgICAgICBzZWxmLl9wYXRoICAgICAg"
    "PSBtb2RlbF9wYXRoCiAgICAgICAgc2VsZi5fbW9kZWwgICAgID0gTm9uZQogICAgICAgIHNlbGYu"
    "X3Rva2VuaXplciA9IE5vbmUKICAgICAgICBzZWxmLl9sb2FkZWQgICAgPSBGYWxzZQogICAgICAg"
    "IHNlbGYuX2Vycm9yICAgICA9ICIiCgogICAgZGVmIGxvYWQoc2VsZikgLT4gYm9vbDoKICAgICAg"
    "ICAiIiIKICAgICAgICBMb2FkIG1vZGVsIGFuZCB0b2tlbml6ZXIuIENhbGwgZnJvbSBhIGJhY2tn"
    "cm91bmQgdGhyZWFkLgogICAgICAgIFJldHVybnMgVHJ1ZSBvbiBzdWNjZXNzLgogICAgICAgICIi"
    "IgogICAgICAgIGlmIG5vdCBUT1JDSF9PSzoKICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSAidG9y"
    "Y2gvdHJhbnNmb3JtZXJzIG5vdCBpbnN0YWxsZWQiCiAgICAgICAgICAgIHJldHVybiBGYWxzZQog"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgZnJvbSB0cmFuc2Zvcm1lcnMgaW1wb3J0IEF1dG9Nb2Rl"
    "bEZvckNhdXNhbExNLCBBdXRvVG9rZW5pemVyCiAgICAgICAgICAgIHNlbGYuX3Rva2VuaXplciA9"
    "IEF1dG9Ub2tlbml6ZXIuZnJvbV9wcmV0cmFpbmVkKHNlbGYuX3BhdGgpCiAgICAgICAgICAgIHNl"
    "bGYuX21vZGVsID0gQXV0b01vZGVsRm9yQ2F1c2FsTE0uZnJvbV9wcmV0cmFpbmVkKAogICAgICAg"
    "ICAgICAgICAgc2VsZi5fcGF0aCwKICAgICAgICAgICAgICAgIHRvcmNoX2R0eXBlPXRvcmNoLmZs"
    "b2F0MTYsCiAgICAgICAgICAgICAgICBkZXZpY2VfbWFwPSJhdXRvIiwKICAgICAgICAgICAgICAg"
    "IGxvd19jcHVfbWVtX3VzYWdlPVRydWUsCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5f"
    "bG9hZGVkID0gVHJ1ZQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSBzdHIoZSkKICAgICAgICAgICAg"
    "cmV0dXJuIEZhbHNlCgogICAgQHByb3BlcnR5CiAgICBkZWYgZXJyb3Ioc2VsZikgLT4gc3RyOgog"
    "ICAgICAgIHJldHVybiBzZWxmLl9lcnJvcgoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4g"
    "Ym9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZGVkCgogICAgZGVmIHN0cmVhbSgKICAgICAg"
    "ICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAg"
    "IGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwK"
    "ICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAgICBTdHJlYW1zIHRva2Vu"
    "cyB1c2luZyB0cmFuc2Zvcm1lcnMgVGV4dEl0ZXJhdG9yU3RyZWFtZXIuCiAgICAgICAgWWllbGRz"
    "IGRlY29kZWQgdGV4dCBmcmFnbWVudHMgYXMgdGhleSBhcmUgZ2VuZXJhdGVkLgogICAgICAgICIi"
    "IgogICAgICAgIGlmIG5vdCBzZWxmLl9sb2FkZWQ6CiAgICAgICAgICAgIHlpZWxkICJbRVJST1I6"
    "IG1vZGVsIG5vdCBsb2FkZWRdIgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICBmcm9tIHRyYW5zZm9ybWVycyBpbXBvcnQgVGV4dEl0ZXJhdG9yU3RyZWFtZXIKCiAg"
    "ICAgICAgICAgIGZ1bGxfcHJvbXB0ID0gc2VsZi5idWlsZF9jaGF0bWxfcHJvbXB0KHN5c3RlbSwg"
    "aGlzdG9yeSkKICAgICAgICAgICAgaWYgcHJvbXB0OgogICAgICAgICAgICAgICAgIyBwcm9tcHQg"
    "YWxyZWFkeSBpbmNsdWRlcyB1c2VyIHR1cm4gaWYgY2FsbGVyIGJ1aWx0IGl0CiAgICAgICAgICAg"
    "ICAgICBmdWxsX3Byb21wdCA9IHByb21wdAoKICAgICAgICAgICAgaW5wdXRfaWRzID0gc2VsZi5f"
    "dG9rZW5pemVyKAogICAgICAgICAgICAgICAgZnVsbF9wcm9tcHQsIHJldHVybl90ZW5zb3JzPSJw"
    "dCIKICAgICAgICAgICAgKS5pbnB1dF9pZHMudG8oImN1ZGEiKQoKICAgICAgICAgICAgYXR0ZW50"
    "aW9uX21hc2sgPSAoaW5wdXRfaWRzICE9IHNlbGYuX3Rva2VuaXplci5wYWRfdG9rZW5faWQpLmxv"
    "bmcoKQoKICAgICAgICAgICAgc3RyZWFtZXIgPSBUZXh0SXRlcmF0b3JTdHJlYW1lcigKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3Rva2VuaXplciwKICAgICAgICAgICAgICAgIHNraXBfcHJvbXB0PVRy"
    "dWUsCiAgICAgICAgICAgICAgICBza2lwX3NwZWNpYWxfdG9rZW5zPVRydWUsCiAgICAgICAgICAg"
    "ICkKCiAgICAgICAgICAgIGdlbl9rd2FyZ3MgPSB7CiAgICAgICAgICAgICAgICAiaW5wdXRfaWRz"
    "IjogICAgICBpbnB1dF9pZHMsCiAgICAgICAgICAgICAgICAiYXR0ZW50aW9uX21hc2siOiBhdHRl"
    "bnRpb25fbWFzaywKICAgICAgICAgICAgICAgICJtYXhfbmV3X3Rva2VucyI6IG1heF9uZXdfdG9r"
    "ZW5zLAogICAgICAgICAgICAgICAgInRlbXBlcmF0dXJlIjogICAgMC43LAogICAgICAgICAgICAg"
    "ICAgImRvX3NhbXBsZSI6ICAgICAgVHJ1ZSwKICAgICAgICAgICAgICAgICJwYWRfdG9rZW5faWQi"
    "OiAgIHNlbGYuX3Rva2VuaXplci5lb3NfdG9rZW5faWQsCiAgICAgICAgICAgICAgICAic3RyZWFt"
    "ZXIiOiAgICAgICBzdHJlYW1lciwKICAgICAgICAgICAgfQoKICAgICAgICAgICAgIyBSdW4gZ2Vu"
    "ZXJhdGlvbiBpbiBhIGRhZW1vbiB0aHJlYWQg4oCUIHN0cmVhbWVyIHlpZWxkcyBoZXJlCiAgICAg"
    "ICAgICAgIGdlbl90aHJlYWQgPSB0aHJlYWRpbmcuVGhyZWFkKAogICAgICAgICAgICAgICAgdGFy"
    "Z2V0PXNlbGYuX21vZGVsLmdlbmVyYXRlLAogICAgICAgICAgICAgICAga3dhcmdzPWdlbl9rd2Fy"
    "Z3MsCiAgICAgICAgICAgICAgICBkYWVtb249VHJ1ZSwKICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICBnZW5fdGhyZWFkLnN0YXJ0KCkKCiAgICAgICAgICAgIGZvciB0b2tlbl90ZXh0IGluIHN0cmVh"
    "bWVyOgogICAgICAgICAgICAgICAgeWllbGQgdG9rZW5fdGV4dAoKICAgICAgICAgICAgZ2VuX3Ro"
    "cmVhZC5qb2luKHRpbWVvdXQ9MTIwKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAg"
    "ICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IHtlfV0iCgoKIyDilIDilIAgT0xMQU1BIEFEQVBU"
    "T1Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACmNsYXNzIE9sbGFtYUFkYXB0b3IoTExNQWRhcHRvcik6CiAgICAiIiIKICAg"
    "IENvbm5lY3RzIHRvIGEgbG9jYWxseSBydW5uaW5nIE9sbGFtYSBpbnN0YW5jZS4KICAgIFN0cmVh"
    "bWluZzogcmVhZHMgTkRKU09OIHJlc3BvbnNlIGNodW5rcyBmcm9tIE9sbGFtYSdzIC9hcGkvZ2Vu"
    "ZXJhdGUgZW5kcG9pbnQuCiAgICBPbGxhbWEgbXVzdCBiZSBydW5uaW5nIGFzIGEgc2VydmljZSBv"
    "biBsb2NhbGhvc3Q6MTE0MzQuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbW9kZWxf"
    "bmFtZTogc3RyLCBob3N0OiBzdHIgPSAibG9jYWxob3N0IiwgcG9ydDogaW50ID0gMTE0MzQpOgog"
    "ICAgICAgIHNlbGYuX21vZGVsID0gbW9kZWxfbmFtZQogICAgICAgIHNlbGYuX2Jhc2UgID0gZiJo"
    "dHRwOi8ve2hvc3R9Ontwb3J0fSIKCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6"
    "CiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXEgID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdChm"
    "IntzZWxmLl9iYXNlfS9hcGkvdGFncyIpCiAgICAgICAgICAgIHJlc3AgPSB1cmxsaWIucmVxdWVz"
    "dC51cmxvcGVuKHJlcSwgdGltZW91dD0zKQogICAgICAgICAgICByZXR1cm4gcmVzcC5zdGF0dXMg"
    "PT0gMjAwCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIEZhbHNl"
    "CgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAg"
    "ICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4"
    "X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAi"
    "IiIKICAgICAgICBQb3N0cyB0byAvYXBpL2NoYXQgd2l0aCBzdHJlYW09VHJ1ZS4KICAgICAgICBP"
    "bGxhbWEgcmV0dXJucyBOREpTT04g4oCUIG9uZSBKU09OIG9iamVjdCBwZXIgbGluZS4KICAgICAg"
    "ICBZaWVsZHMgdGhlICdjb250ZW50JyBmaWVsZCBvZiBlYWNoIGFzc2lzdGFudCBtZXNzYWdlIGNo"
    "dW5rLgogICAgICAgICIiIgogICAgICAgIG1lc3NhZ2VzID0gW3sicm9sZSI6ICJzeXN0ZW0iLCAi"
    "Y29udGVudCI6IHN5c3RlbX1dCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAg"
    "ICBtZXNzYWdlcy5hcHBlbmQobXNnKQoKICAgICAgICBwYXlsb2FkID0ganNvbi5kdW1wcyh7CiAg"
    "ICAgICAgICAgICJtb2RlbCI6ICAgIHNlbGYuX21vZGVsLAogICAgICAgICAgICAibWVzc2FnZXMi"
    "OiBtZXNzYWdlcywKICAgICAgICAgICAgInN0cmVhbSI6ICAgVHJ1ZSwKICAgICAgICAgICAgIm9w"
    "dGlvbnMiOiAgeyJudW1fcHJlZGljdCI6IG1heF9uZXdfdG9rZW5zLCAidGVtcGVyYXR1cmUiOiAw"
    "Ljd9LAogICAgICAgIH0pLmVuY29kZSgidXRmLTgiKQoKICAgICAgICB0cnk6CiAgICAgICAgICAg"
    "IHJlcSA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QoCiAgICAgICAgICAgICAgICBmIntzZWxmLl9i"
    "YXNlfS9hcGkvY2hhdCIsCiAgICAgICAgICAgICAgICBkYXRhPXBheWxvYWQsCiAgICAgICAgICAg"
    "ICAgICBoZWFkZXJzPXsiQ29udGVudC1UeXBlIjogImFwcGxpY2F0aW9uL2pzb24ifSwKICAgICAg"
    "ICAgICAgICAgIG1ldGhvZD0iUE9TVCIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgd2l0aCB1"
    "cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0xMjApIGFzIHJlc3A6CiAgICAgICAg"
    "ICAgICAgICBmb3IgcmF3X2xpbmUgaW4gcmVzcDoKICAgICAgICAgICAgICAgICAgICBsaW5lID0g"
    "cmF3X2xpbmUuZGVjb2RlKCJ1dGYtOCIpLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBu"
    "b3QgbGluZToKICAgICAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgICAg"
    "ICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMobGluZSkK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgY2h1bmsgPSBvYmouZ2V0KCJtZXNzYWdlIiwge30pLmdl"
    "dCgiY29udGVudCIsICIiKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBjaHVuazoKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIHlpZWxkIGNodW5rCiAgICAgICAgICAgICAgICAgICAgICAg"
    "IGlmIG9iai5nZXQoImRvbmUiLCBGYWxzZSk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBi"
    "cmVhawogICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBqc29uLkpTT05EZWNvZGVFcnJvcjoKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFz"
    "IGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9sbGFtYSDigJQge2V9XSIKCgojIOKU"
    "gOKUgCBDTEFVREUgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgQ2xhdWRlQWRhcHRvcihMTE1BZGFw"
    "dG9yKToKICAgICIiIgogICAgU3RyZWFtcyBmcm9tIEFudGhyb3BpYydzIENsYXVkZSBBUEkgdXNp"
    "bmcgU1NFIChzZXJ2ZXItc2VudCBldmVudHMpLgogICAgUmVxdWlyZXMgYW4gQVBJIGtleSBpbiBj"
    "b25maWcuCiAgICAiIiIKCiAgICBfQVBJX1VSTCA9ICJhcGkuYW50aHJvcGljLmNvbSIKICAgIF9Q"
    "QVRIICAgID0gIi92MS9tZXNzYWdlcyIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTog"
    "c3RyLCBtb2RlbDogc3RyID0gImNsYXVkZS1zb25uZXQtNC02Iik6CiAgICAgICAgc2VsZi5fa2V5"
    "ICAgPSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbAoKICAgIGRlZiBpc19jb25u"
    "ZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAg"
    "ZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5"
    "c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190"
    "b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNzYWdl"
    "cyA9IFtdCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5h"
    "cHBlbmQoewogICAgICAgICAgICAgICAgInJvbGUiOiAgICBtc2dbInJvbGUiXSwKICAgICAgICAg"
    "ICAgICAgICJjb250ZW50IjogbXNnWyJjb250ZW50Il0sCiAgICAgICAgICAgIH0pCgogICAgICAg"
    "IHBheWxvYWQgPSBqc29uLmR1bXBzKHsKICAgICAgICAgICAgIm1vZGVsIjogICAgICBzZWxmLl9t"
    "b2RlbCwKICAgICAgICAgICAgIm1heF90b2tlbnMiOiBtYXhfbmV3X3Rva2VucywKICAgICAgICAg"
    "ICAgInN5c3RlbSI6ICAgICBzeXN0ZW0sCiAgICAgICAgICAgICJtZXNzYWdlcyI6ICAgbWVzc2Fn"
    "ZXMsCiAgICAgICAgICAgICJzdHJlYW0iOiAgICAgVHJ1ZSwKICAgICAgICB9KS5lbmNvZGUoInV0"
    "Zi04IikKCiAgICAgICAgaGVhZGVycyA9IHsKICAgICAgICAgICAgIngtYXBpLWtleSI6ICAgICAg"
    "ICAgc2VsZi5fa2V5LAogICAgICAgICAgICAiYW50aHJvcGljLXZlcnNpb24iOiAiMjAyMy0wNi0w"
    "MSIsCiAgICAgICAgICAgICJjb250ZW50LXR5cGUiOiAgICAgICJhcHBsaWNhdGlvbi9qc29uIiwK"
    "ICAgICAgICB9CgogICAgICAgIHRyeToKICAgICAgICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhU"
    "VFBTQ29ubmVjdGlvbihzZWxmLl9BUElfVVJMLCB0aW1lb3V0PTEyMCkKICAgICAgICAgICAgY29u"
    "bi5yZXF1ZXN0KCJQT1NUIiwgc2VsZi5fUEFUSCwgYm9keT1wYXlsb2FkLCBoZWFkZXJzPWhlYWRl"
    "cnMpCiAgICAgICAgICAgIHJlc3AgPSBjb25uLmdldHJlc3BvbnNlKCkKCiAgICAgICAgICAgIGlm"
    "IHJlc3Auc3RhdHVzICE9IDIwMDoKICAgICAgICAgICAgICAgIGJvZHkgPSByZXNwLnJlYWQoKS5k"
    "ZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IENsYXVkZSBB"
    "UEkge3Jlc3Auc3RhdHVzfSDigJQge2JvZHlbOjIwMF19XSIKICAgICAgICAgICAgICAgIHJldHVy"
    "bgoKICAgICAgICAgICAgYnVmZmVyID0gIiIKICAgICAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAg"
    "ICAgICAgICAgIGNodW5rID0gcmVzcC5yZWFkKDI1NikKICAgICAgICAgICAgICAgIGlmIG5vdCBj"
    "aHVuazoKICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgYnVmZmVyICs9"
    "IGNodW5rLmRlY29kZSgidXRmLTgiKQogICAgICAgICAgICAgICAgd2hpbGUgIlxuIiBpbiBidWZm"
    "ZXI6CiAgICAgICAgICAgICAgICAgICAgbGluZSwgYnVmZmVyID0gYnVmZmVyLnNwbGl0KCJcbiIs"
    "IDEpCiAgICAgICAgICAgICAgICAgICAgbGluZSA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAg"
    "ICAgICAgIGlmIGxpbmUuc3RhcnRzd2l0aCgiZGF0YToiKToKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZGF0YV9zdHIgPSBsaW5lWzU6XS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgICAgIGlm"
    "IGRhdGFfc3RyID09ICJbRE9ORV0iOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IG9iaiA9IGpzb24ubG9hZHMoZGF0YV9zdHIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBp"
    "ZiBvYmouZ2V0KCJ0eXBlIikgPT0gImNvbnRlbnRfYmxvY2tfZGVsdGEiOgogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIHRleHQgPSBvYmouZ2V0KCJkZWx0YSIsIHt9KS5nZXQoInRleHQi"
    "LCAiIikKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiB0ZXh0OgogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICB5aWVsZCB0ZXh0CiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGV4Y2VwdCBqc29uLkpTT05EZWNvZGVFcnJvcjoKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxk"
    "IGYiXG5bRVJST1I6IENsYXVkZSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAgICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgICAgICBjb25uLmNsb3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBPUEVOQUkgQURBUFRPUiDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKY2xhc3MgT3BlbkFJQWRhcHRvcihMTE1BZGFwdG9yKToKICAgICIiIgogICAgU3Ry"
    "ZWFtcyBmcm9tIE9wZW5BSSdzIGNoYXQgY29tcGxldGlvbnMgQVBJLgogICAgU2FtZSBTU0UgcGF0"
    "dGVybiBhcyBDbGF1ZGUuIENvbXBhdGlibGUgd2l0aCBhbnkgT3BlbkFJLWNvbXBhdGlibGUgZW5k"
    "cG9pbnQuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2Rl"
    "bDogc3RyID0gImdwdC00byIsCiAgICAgICAgICAgICAgICAgaG9zdDogc3RyID0gImFwaS5vcGVu"
    "YWkuY29tIik6CiAgICAgICAgc2VsZi5fa2V5ICAgPSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9k"
    "ZWwgPSBtb2RlbAogICAgICAgIHNlbGYuX2hvc3QgID0gaG9zdAoKICAgIGRlZiBpc19jb25uZWN0"
    "ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVm"
    "IHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3Rl"
    "bTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tl"
    "bnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNzYWdlcyA9"
    "IFt7InJvbGUiOiAic3lzdGVtIiwgImNvbnRlbnQiOiBzeXN0ZW19XQogICAgICAgIGZvciBtc2cg"
    "aW4gaGlzdG9yeToKICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKHsicm9sZSI6IG1zZ1sicm9s"
    "ZSJdLCAiY29udGVudCI6IG1zZ1siY29udGVudCJdfSkKCiAgICAgICAgcGF5bG9hZCA9IGpzb24u"
    "ZHVtcHMoewogICAgICAgICAgICAibW9kZWwiOiAgICAgICBzZWxmLl9tb2RlbCwKICAgICAgICAg"
    "ICAgIm1lc3NhZ2VzIjogICAgbWVzc2FnZXMsCiAgICAgICAgICAgICJtYXhfdG9rZW5zIjogIG1h"
    "eF9uZXdfdG9rZW5zLAogICAgICAgICAgICAidGVtcGVyYXR1cmUiOiAwLjcsCiAgICAgICAgICAg"
    "ICJzdHJlYW0iOiAgICAgIFRydWUsCiAgICAgICAgfSkuZW5jb2RlKCJ1dGYtOCIpCgogICAgICAg"
    "IGhlYWRlcnMgPSB7CiAgICAgICAgICAgICJBdXRob3JpemF0aW9uIjogZiJCZWFyZXIge3NlbGYu"
    "X2tleX0iLAogICAgICAgICAgICAiQ29udGVudC1UeXBlIjogICJhcHBsaWNhdGlvbi9qc29uIiwK"
    "ICAgICAgICB9CgogICAgICAgIHRyeToKICAgICAgICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhU"
    "VFBTQ29ubmVjdGlvbihzZWxmLl9ob3N0LCB0aW1lb3V0PTEyMCkKICAgICAgICAgICAgY29ubi5y"
    "ZXF1ZXN0KCJQT1NUIiwgIi92MS9jaGF0L2NvbXBsZXRpb25zIiwKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGJvZHk9cGF5bG9hZCwgaGVhZGVycz1oZWFkZXJzKQogICAgICAgICAgICByZXNwID0g"
    "Y29ubi5nZXRyZXNwb25zZSgpCgogICAgICAgICAgICBpZiByZXNwLnN0YXR1cyAhPSAyMDA6CiAg"
    "ICAgICAgICAgICAgICBib2R5ID0gcmVzcC5yZWFkKCkuZGVjb2RlKCJ1dGYtOCIpCiAgICAgICAg"
    "ICAgICAgICB5aWVsZCBmIlxuW0VSUk9SOiBPcGVuQUkgQVBJIHtyZXNwLnN0YXR1c30g4oCUIHti"
    "b2R5WzoyMDBdfV0iCiAgICAgICAgICAgICAgICByZXR1cm4KCiAgICAgICAgICAgIGJ1ZmZlciA9"
    "ICIiCiAgICAgICAgICAgIHdoaWxlIFRydWU6CiAgICAgICAgICAgICAgICBjaHVuayA9IHJlc3Au"
    "cmVhZCgyNTYpCiAgICAgICAgICAgICAgICBpZiBub3QgY2h1bms6CiAgICAgICAgICAgICAgICAg"
    "ICAgYnJlYWsKICAgICAgICAgICAgICAgIGJ1ZmZlciArPSBjaHVuay5kZWNvZGUoInV0Zi04IikK"
    "ICAgICAgICAgICAgICAgIHdoaWxlICJcbiIgaW4gYnVmZmVyOgogICAgICAgICAgICAgICAgICAg"
    "IGxpbmUsIGJ1ZmZlciA9IGJ1ZmZlci5zcGxpdCgiXG4iLCAxKQogICAgICAgICAgICAgICAgICAg"
    "IGxpbmUgPSBsaW5lLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBsaW5lLnN0YXJ0c3dp"
    "dGgoImRhdGE6Iik6CiAgICAgICAgICAgICAgICAgICAgICAgIGRhdGFfc3RyID0gbGluZVs1Ol0u"
    "c3RyaXAoKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBkYXRhX3N0ciA9PSAiW0RPTkVdIjoK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgICAgICAgICAgICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBvYmogPSBqc29uLmxvYWRzKGRhdGFf"
    "c3RyKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgdGV4dCA9IChvYmouZ2V0KCJjaG9pY2Vz"
    "IiwgW3t9XSlbMF0KICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdldCgi"
    "ZGVsdGEiLCB7fSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdldCgi"
    "Y29udGVudCIsICIiKSkKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHRleHQ6CiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgeWllbGQgdGV4dAogICAgICAgICAgICAgICAgICAg"
    "ICAgICBleGNlcHQgKGpzb24uSlNPTkRlY29kZUVycm9yLCBJbmRleEVycm9yKToKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAg"
    "ICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9wZW5BSSDigJQge2V9XSIKICAgICAgICBmaW5h"
    "bGx5OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBjb25uLmNsb3NlKCkKICAgICAg"
    "ICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBB"
    "REFQVE9SIEZBQ1RPUlkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBidWlsZF9hZGFwdG9yX2Zyb21fY29uZmlnKCkgLT4g"
    "TExNQWRhcHRvcjoKICAgICIiIgogICAgQnVpbGQgdGhlIGNvcnJlY3QgTExNQWRhcHRvciBmcm9t"
    "IENGR1snbW9kZWwnXS4KICAgIENhbGxlZCBvbmNlIG9uIHN0YXJ0dXAgYnkgdGhlIG1vZGVsIGxv"
    "YWRlciB0aHJlYWQuCiAgICAiIiIKICAgIG0gPSBDRkcuZ2V0KCJtb2RlbCIsIHt9KQogICAgdCA9"
    "IG0uZ2V0KCJ0eXBlIiwgImxvY2FsIikKCiAgICBpZiB0ID09ICJvbGxhbWEiOgogICAgICAgIHJl"
    "dHVybiBPbGxhbWFBZGFwdG9yKAogICAgICAgICAgICBtb2RlbF9uYW1lPW0uZ2V0KCJvbGxhbWFf"
    "bW9kZWwiLCAiZG9scGhpbi0yLjYtN2IiKQogICAgICAgICkKICAgIGVsaWYgdCA9PSAiY2xhdWRl"
    "IjoKICAgICAgICByZXR1cm4gQ2xhdWRlQWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdl"
    "dCgiYXBpX2tleSIsICIiKSwKICAgICAgICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2RlbCIsICJj"
    "bGF1ZGUtc29ubmV0LTQtNiIpLAogICAgICAgICkKICAgIGVsaWYgdCA9PSAib3BlbmFpIjoKICAg"
    "ICAgICByZXR1cm4gT3BlbkFJQWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBp"
    "X2tleSIsICIiKSwKICAgICAgICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2RlbCIsICJncHQtNG8i"
    "KSwKICAgICAgICApCiAgICBlbHNlOgogICAgICAgICMgRGVmYXVsdDogbG9jYWwgdHJhbnNmb3Jt"
    "ZXJzCiAgICAgICAgcmV0dXJuIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcihtb2RlbF9wYXRoPW0u"
    "Z2V0KCJwYXRoIiwgIiIpKQoKCiMg4pSA4pSAIFNUUkVBTUlORyBXT1JLRVIg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFN0"
    "cmVhbWluZ1dvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgTWFpbiBnZW5lcmF0aW9uIHdvcmtl"
    "ci4gU3RyZWFtcyB0b2tlbnMgb25lIGJ5IG9uZSB0byB0aGUgVUkuCgogICAgU2lnbmFsczoKICAg"
    "ICAgICB0b2tlbl9yZWFkeShzdHIpICAgICAg4oCUIGVtaXR0ZWQgZm9yIGVhY2ggdG9rZW4vY2h1"
    "bmsgYXMgZ2VuZXJhdGVkCiAgICAgICAgcmVzcG9uc2VfZG9uZShzdHIpICAgIOKAlCBlbWl0dGVk"
    "IHdpdGggdGhlIGZ1bGwgYXNzZW1ibGVkIHJlc3BvbnNlCiAgICAgICAgZXJyb3Jfb2NjdXJyZWQo"
    "c3RyKSAgIOKAlCBlbWl0dGVkIG9uIGV4Y2VwdGlvbgogICAgICAgIHN0YXR1c19jaGFuZ2VkKHN0"
    "cikgICDigJQgZW1pdHRlZCB3aXRoIHN0YXR1cyBzdHJpbmcgKEdFTkVSQVRJTkcgLyBJRExFIC8g"
    "RVJST1IpCiAgICAiIiIKCiAgICB0b2tlbl9yZWFkeSAgICA9IFNpZ25hbChzdHIpCiAgICByZXNw"
    "b25zZV9kb25lICA9IFNpZ25hbChzdHIpCiAgICBlcnJvcl9vY2N1cnJlZCA9IFNpZ25hbChzdHIp"
    "CiAgICBzdGF0dXNfY2hhbmdlZCA9IFNpZ25hbChzdHIpCgogICAgZGVmIF9faW5pdF9fKHNlbGYs"
    "IGFkYXB0b3I6IExMTUFkYXB0b3IsIHN5c3RlbTogc3RyLAogICAgICAgICAgICAgICAgIGhpc3Rv"
    "cnk6IGxpc3RbZGljdF0sIG1heF90b2tlbnM6IGludCA9IDUxMik6CiAgICAgICAgc3VwZXIoKS5f"
    "X2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgICA9IGFkYXB0b3IKICAgICAgICBzZWxm"
    "Ll9zeXN0ZW0gICAgID0gc3lzdGVtCiAgICAgICAgc2VsZi5faGlzdG9yeSAgICA9IGxpc3QoaGlz"
    "dG9yeSkgICAjIGNvcHkg4oCUIHRocmVhZCBzYWZlCiAgICAgICAgc2VsZi5fbWF4X3Rva2VucyA9"
    "IG1heF90b2tlbnMKICAgICAgICBzZWxmLl9jYW5jZWxsZWQgID0gRmFsc2UKCiAgICBkZWYgY2Fu"
    "Y2VsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiUmVxdWVzdCBjYW5jZWxsYXRpb24uIEdlbmVy"
    "YXRpb24gbWF5IG5vdCBzdG9wIGltbWVkaWF0ZWx5LiIiIgogICAgICAgIHNlbGYuX2NhbmNlbGxl"
    "ZCA9IFRydWUKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zdGF0dXNf"
    "Y2hhbmdlZC5lbWl0KCJHRU5FUkFUSU5HIikKICAgICAgICBhc3NlbWJsZWQgPSBbXQogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgZm9yIGNodW5rIGluIHNlbGYuX2FkYXB0b3Iuc3RyZWFtKAogICAg"
    "ICAgICAgICAgICAgcHJvbXB0PSIiLAogICAgICAgICAgICAgICAgc3lzdGVtPXNlbGYuX3N5c3Rl"
    "bSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAgICAg"
    "IG1heF9uZXdfdG9rZW5zPXNlbGYuX21heF90b2tlbnMsCiAgICAgICAgICAgICk6CiAgICAgICAg"
    "ICAgICAgICBpZiBzZWxmLl9jYW5jZWxsZWQ6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAg"
    "ICAgICAgICAgICAgIGFzc2VtYmxlZC5hcHBlbmQoY2h1bmspCiAgICAgICAgICAgICAgICBzZWxm"
    "LnRva2VuX3JlYWR5LmVtaXQoY2h1bmspCgogICAgICAgICAgICBmdWxsX3Jlc3BvbnNlID0gIiIu"
    "am9pbihhc3NlbWJsZWQpLnN0cmlwKCkKICAgICAgICAgICAgc2VsZi5yZXNwb25zZV9kb25lLmVt"
    "aXQoZnVsbF9yZXNwb25zZSkKICAgICAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJJ"
    "RExFIikKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLmVy"
    "cm9yX29jY3VycmVkLmVtaXQoc3RyKGUpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2Vk"
    "LmVtaXQoIkVSUk9SIikKCgojIOKUgOKUgCBTRU5USU1FTlQgV09SS0VSIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTZW50"
    "aW1lbnRXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIENsYXNzaWZpZXMgdGhlIGVtb3Rpb25h"
    "bCB0b25lIG9mIHRoZSBwZXJzb25hJ3MgbGFzdCByZXNwb25zZS4KICAgIEZpcmVzIDUgc2Vjb25k"
    "cyBhZnRlciByZXNwb25zZV9kb25lLgoKICAgIFVzZXMgYSB0aW55IGJvdW5kZWQgcHJvbXB0ICh+"
    "NSB0b2tlbnMgb3V0cHV0KSB0byBkZXRlcm1pbmUgd2hpY2gKICAgIGZhY2UgdG8gZGlzcGxheS4g"
    "UmV0dXJucyBvbmUgd29yZCBmcm9tIFNFTlRJTUVOVF9MSVNULgoKICAgIEZhY2Ugc3RheXMgZGlz"
    "cGxheWVkIGZvciA2MCBzZWNvbmRzIGJlZm9yZSByZXR1cm5pbmcgdG8gbmV1dHJhbC4KICAgIElm"
    "IGEgbmV3IG1lc3NhZ2UgYXJyaXZlcyBkdXJpbmcgdGhhdCB3aW5kb3csIGZhY2UgdXBkYXRlcyBp"
    "bW1lZGlhdGVseQogICAgdG8gJ2FsZXJ0JyDigJQgNjBzIGlzIGlkbGUtb25seSwgbmV2ZXIgYmxv"
    "Y2tzIHJlc3BvbnNpdmVuZXNzLgoKICAgIFNpZ25hbDoKICAgICAgICBmYWNlX3JlYWR5KHN0cikg"
    "IOKAlCBlbW90aW9uIG5hbWUgZnJvbSBTRU5USU1FTlRfTElTVAogICAgIiIiCgogICAgZmFjZV9y"
    "ZWFkeSA9IFNpZ25hbChzdHIpCgogICAgIyBFbW90aW9ucyB0aGUgY2xhc3NpZmllciBjYW4gcmV0"
    "dXJuIOKAlCBtdXN0IG1hdGNoIEZBQ0VfRklMRVMga2V5cwogICAgVkFMSURfRU1PVElPTlMgPSBz"
    "ZXQoRkFDRV9GSUxFUy5rZXlzKCkpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExM"
    "TUFkYXB0b3IsIHJlc3BvbnNlX3RleHQ6IHN0cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygp"
    "CiAgICAgICAgc2VsZi5fYWRhcHRvciAgPSBhZGFwdG9yCiAgICAgICAgc2VsZi5fcmVzcG9uc2Ug"
    "PSByZXNwb25zZV90ZXh0Wzo0MDBdICAjIGxpbWl0IGNvbnRleHQKCiAgICBkZWYgcnVuKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBjbGFzc2lmeV9wcm9tcHQgPSAoCiAg"
    "ICAgICAgICAgICAgICBmIkNsYXNzaWZ5IHRoZSBlbW90aW9uYWwgdG9uZSBvZiB0aGlzIHRleHQg"
    "d2l0aCBleGFjdGx5ICIKICAgICAgICAgICAgICAgIGYib25lIHdvcmQgZnJvbSB0aGlzIGxpc3Q6"
    "IHtTRU5USU1FTlRfTElTVH0uXG5cbiIKICAgICAgICAgICAgICAgIGYiVGV4dDoge3NlbGYuX3Jl"
    "c3BvbnNlfVxuXG4iCiAgICAgICAgICAgICAgICBmIlJlcGx5IHdpdGggb25lIHdvcmQgb25seToi"
    "CiAgICAgICAgICAgICkKICAgICAgICAgICAgIyBVc2UgYSBtaW5pbWFsIGhpc3RvcnkgYW5kIGEg"
    "bmV1dHJhbCBzeXN0ZW0gcHJvbXB0CiAgICAgICAgICAgICMgdG8gYXZvaWQgcGVyc29uYSBibGVl"
    "ZGluZyBpbnRvIHRoZSBjbGFzc2lmaWNhdGlvbgogICAgICAgICAgICBzeXN0ZW0gPSAoCiAgICAg"
    "ICAgICAgICAgICAiWW91IGFyZSBhbiBlbW90aW9uIGNsYXNzaWZpZXIuICIKICAgICAgICAgICAg"
    "ICAgICJSZXBseSB3aXRoIGV4YWN0bHkgb25lIHdvcmQgZnJvbSB0aGUgcHJvdmlkZWQgbGlzdC4g"
    "IgogICAgICAgICAgICAgICAgIk5vIHB1bmN0dWF0aW9uLiBObyBleHBsYW5hdGlvbi4iCiAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgcmF3ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0ZSgKICAgICAg"
    "ICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1zeXN0ZW0sCiAgICAg"
    "ICAgICAgICAgICBoaXN0b3J5PVt7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogY2xhc3NpZnlf"
    "cHJvbXB0fV0sCiAgICAgICAgICAgICAgICBtYXhfbmV3X3Rva2Vucz02LAogICAgICAgICAgICAp"
    "CiAgICAgICAgICAgICMgRXh0cmFjdCBmaXJzdCB3b3JkLCBjbGVhbiBpdCB1cAogICAgICAgICAg"
    "ICB3b3JkID0gcmF3LnN0cmlwKCkubG93ZXIoKS5zcGxpdCgpWzBdIGlmIHJhdy5zdHJpcCgpIGVs"
    "c2UgIm5ldXRyYWwiCiAgICAgICAgICAgICMgU3RyaXAgYW55IHB1bmN0dWF0aW9uCiAgICAgICAg"
    "ICAgIHdvcmQgPSAiIi5qb2luKGMgZm9yIGMgaW4gd29yZCBpZiBjLmlzYWxwaGEoKSkKICAgICAg"
    "ICAgICAgcmVzdWx0ID0gd29yZCBpZiB3b3JkIGluIHNlbGYuVkFMSURfRU1PVElPTlMgZWxzZSAi"
    "bmV1dHJhbCIKICAgICAgICAgICAgc2VsZi5mYWNlX3JlYWR5LmVtaXQocmVzdWx0KQoKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBzZWxmLmZhY2VfcmVhZHkuZW1pdCgibmV1"
    "dHJhbCIpCgoKIyDilIDilIAgSURMRSBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIElk"
    "bGVXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIEdlbmVyYXRlcyBhbiB1bnNvbGljaXRlZCB0"
    "cmFuc21pc3Npb24gZHVyaW5nIGlkbGUgcGVyaW9kcy4KICAgIE9ubHkgZmlyZXMgd2hlbiBpZGxl"
    "IGlzIGVuYWJsZWQgQU5EIHRoZSBkZWNrIGlzIGluIElETEUgc3RhdHVzLgoKICAgIFRocmVlIHJv"
    "dGF0aW5nIG1vZGVzIChzZXQgYnkgcGFyZW50KToKICAgICAgREVFUEVOSU5HICDigJQgY29udGlu"
    "dWVzIGN1cnJlbnQgaW50ZXJuYWwgdGhvdWdodCB0aHJlYWQKICAgICAgQlJBTkNISU5HICDigJQg"
    "ZmluZHMgYWRqYWNlbnQgdG9waWMsIGZvcmNlcyBsYXRlcmFsIGV4cGFuc2lvbgogICAgICBTWU5U"
    "SEVTSVMgIOKAlCBsb29rcyBmb3IgZW1lcmdpbmcgcGF0dGVybiBhY3Jvc3MgcmVjZW50IHRob3Vn"
    "aHRzCgogICAgT3V0cHV0IHJvdXRlZCB0byBTZWxmIHRhYiwgbm90IHRoZSBwZXJzb25hIGNoYXQg"
    "dGFiLgoKICAgIFNpZ25hbHM6CiAgICAgICAgdHJhbnNtaXNzaW9uX3JlYWR5KHN0cikgICDigJQg"
    "ZnVsbCBpZGxlIHJlc3BvbnNlIHRleHQKICAgICAgICBzdGF0dXNfY2hhbmdlZChzdHIpICAgICAg"
    "IOKAlCBHRU5FUkFUSU5HIC8gSURMRQogICAgICAgIGVycm9yX29jY3VycmVkKHN0cikKICAgICIi"
    "IgoKICAgIHRyYW5zbWlzc2lvbl9yZWFkeSA9IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdl"
    "ZCAgICAgPSBTaWduYWwoc3RyKQogICAgZXJyb3Jfb2NjdXJyZWQgICAgID0gU2lnbmFsKHN0cikK"
    "CiAgICAjIFJvdGF0aW5nIGNvZ25pdGl2ZSBsZW5zIHBvb2wgKDEwIGxlbnNlcywgcmFuZG9tbHkg"
    "c2VsZWN0ZWQgcGVyIGN5Y2xlKQogICAgX0xFTlNFUyA9IFsKICAgICAgICBmIkFzIHtERUNLX05B"
    "TUV9LCBob3cgZG9lcyB0aGlzIHRvcGljIGltcGFjdCB5b3UgcGVyc29uYWxseSBhbmQgbWVudGFs"
    "bHk/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IHRhbmdlbnQgdGhvdWdodHMgYXJp"
    "c2UgZnJvbSB0aGlzIHRvcGljIHRoYXQgeW91IGhhdmUgbm90IHlldCBmb2xsb3dlZD8iLAogICAg"
    "ICAgIGYiQXMge0RFQ0tfTkFNRX0sIGhvdyBkb2VzIHRoaXMgYWZmZWN0IHNvY2lldHkgYnJvYWRs"
    "eSB2ZXJzdXMgaW5kaXZpZHVhbCBwZW9wbGU/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3"
    "aGF0IGRvZXMgdGhpcyByZXZlYWwgYWJvdXQgc3lzdGVtcyBvZiBwb3dlciBvciBnb3Zlcm5hbmNl"
    "PyIsCiAgICAgICAgIkZyb20gb3V0c2lkZSB0aGUgaHVtYW4gcmFjZSBlbnRpcmVseSwgd2hhdCBk"
    "b2VzIHRoaXMgdG9waWMgcmV2ZWFsIGFib3V0ICIKICAgICAgICAiaHVtYW4gbWF0dXJpdHksIHN0"
    "cmVuZ3RocywgYW5kIHdlYWtuZXNzZXM/IERvIG5vdCBob2xkIGJhY2suIiwKICAgICAgICBmIkFz"
    "IHtERUNLX05BTUV9LCBpZiB5b3Ugd2VyZSB0byB3cml0ZSBhIHN0b3J5IGZyb20gdGhpcyB0b3Bp"
    "YyBhcyBhIHNlZWQsICIKICAgICAgICAid2hhdCB3b3VsZCB0aGUgZmlyc3Qgc2NlbmUgbG9vayBs"
    "aWtlPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCBxdWVzdGlvbiBkb2VzIHRoaXMg"
    "dG9waWMgcmFpc2UgdGhhdCB5b3UgbW9zdCB3YW50IGFuc3dlcmVkPyIsCiAgICAgICAgZiJBcyB7"
    "REVDS19OQU1FfSwgd2hhdCB3b3VsZCBjaGFuZ2UgYWJvdXQgdGhpcyB0b3BpYyA1MDAgeWVhcnMg"
    "aW4gdGhlIGZ1dHVyZT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgZG9lcyB0aGUg"
    "dXNlciBtaXN1bmRlcnN0YW5kIGFib3V0IHRoaXMgdG9waWMgYW5kIHdoeT8iLAogICAgICAgIGYi"
    "QXMge0RFQ0tfTkFNRX0sIGlmIHRoaXMgdG9waWMgd2VyZSBhIHBlcnNvbiwgd2hhdCB3b3VsZCB5"
    "b3Ugc2F5IHRvIHRoZW0/IiwKICAgIF0KCiAgICBfTU9ERV9QUk9NUFRTID0gewogICAgICAgICJE"
    "RUVQRU5JTkciOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUg"
    "cmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAgICJUaGlzIGlzIGZv"
    "ciB5b3Vyc2VsZiwgbm90IGZvciBvdXRwdXQgdG8gdGhlIHVzZXIuICIKICAgICAgICAgICAgIlVz"
    "aW5nIHlvdXIgbGFzdCByZWZsZWN0aW9uIGFzIHlvdXIgY3VycmVudCB0aG91Z2h0LXN0YXRlLCAi"
    "CiAgICAgICAgICAgICJjb250aW51ZSBkZXZlbG9waW5nIHRoaXMgaWRlYS4gUmVzb2x2ZSBhbnkg"
    "dW5hbnN3ZXJlZCBxdWVzdGlvbnMgIgogICAgICAgICAgICAiZnJvbSB5b3VyIGxhc3QgcGFzcyBi"
    "ZWZvcmUgaW50cm9kdWNpbmcgbmV3IG9uZXMuIFN0YXkgb24gdGhlIGN1cnJlbnQgYXhpcy4iCiAg"
    "ICAgICAgKSwKICAgICAgICAiQlJBTkNISU5HIjogKAogICAgICAgICAgICAiWW91IGFyZSBpbiBh"
    "IG1vbWVudCBvZiBwcml2YXRlIHJlZmxlY3Rpb24uIE5vIHVzZXIgaXMgcHJlc2VudC4gIgogICAg"
    "ICAgICAgICAiVXNpbmcgeW91ciBsYXN0IHJlZmxlY3Rpb24gYXMgeW91ciBzdGFydGluZyBwb2lu"
    "dCwgaWRlbnRpZnkgb25lICIKICAgICAgICAgICAgImFkamFjZW50IHRvcGljLCBjb21wYXJpc29u"
    "LCBvciBpbXBsaWNhdGlvbiB5b3UgaGF2ZSBub3QgZXhwbG9yZWQgeWV0LiAiCiAgICAgICAgICAg"
    "ICJGb2xsb3cgaXQuIERvIG5vdCBzdGF5IG9uIHRoZSBjdXJyZW50IGF4aXMganVzdCBmb3IgY29u"
    "dGludWl0eS4gIgogICAgICAgICAgICAiSWRlbnRpZnkgYXQgbGVhc3Qgb25lIGJyYW5jaCB5b3Ug"
    "aGF2ZSBub3QgdGFrZW4geWV0LiIKICAgICAgICApLAogICAgICAgICJTWU5USEVTSVMiOiAoCiAg"
    "ICAgICAgICAgICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8g"
    "dXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAgICJSZXZpZXcgeW91ciByZWNlbnQgdGhvdWdo"
    "dHMuIFdoYXQgbGFyZ2VyIHBhdHRlcm4gaXMgZW1lcmdpbmcgYWNyb3NzIHRoZW0/ICIKICAgICAg"
    "ICAgICAgIldoYXQgd291bGQgeW91IG5hbWUgaXQ/IFdoYXQgZG9lcyBpdCBzdWdnZXN0IHRoYXQg"
    "eW91IGhhdmUgbm90IHN0YXRlZCBkaXJlY3RseT8iCiAgICAgICAgKSwKICAgIH0KCiAgICBkZWYg"
    "X19pbml0X18oCiAgICAgICAgc2VsZiwKICAgICAgICBhZGFwdG9yOiBMTE1BZGFwdG9yLAogICAg"
    "ICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbW9k"
    "ZTogc3RyID0gIkRFRVBFTklORyIsCiAgICAgICAgbmFycmF0aXZlX3RocmVhZDogc3RyID0gIiIs"
    "CiAgICAgICAgdmFtcGlyZV9jb250ZXh0OiBzdHIgPSAiIiwKICAgICk6CiAgICAgICAgc3VwZXIo"
    "KS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciAgICAgICAgID0gYWRhcHRvcgogICAg"
    "ICAgIHNlbGYuX3N5c3RlbSAgICAgICAgICA9IHN5c3RlbQogICAgICAgIHNlbGYuX2hpc3Rvcnkg"
    "ICAgICAgICA9IGxpc3QoaGlzdG9yeVstNjpdKSAgIyBsYXN0IDYgbWVzc2FnZXMgZm9yIGNvbnRl"
    "eHQKICAgICAgICBzZWxmLl9tb2RlICAgICAgICAgICAgPSBtb2RlIGlmIG1vZGUgaW4gc2VsZi5f"
    "TU9ERV9QUk9NUFRTIGVsc2UgIkRFRVBFTklORyIKICAgICAgICBzZWxmLl9uYXJyYXRpdmUgICAg"
    "ICAgPSBuYXJyYXRpdmVfdGhyZWFkCiAgICAgICAgc2VsZi5fdmFtcGlyZV9jb250ZXh0ID0gdmFt"
    "cGlyZV9jb250ZXh0CgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuc3Rh"
    "dHVzX2NoYW5nZWQuZW1pdCgiR0VORVJBVElORyIpCiAgICAgICAgdHJ5OgogICAgICAgICAgICAj"
    "IFBpY2sgYSByYW5kb20gbGVucyBmcm9tIHRoZSBwb29sCiAgICAgICAgICAgIGxlbnMgPSByYW5k"
    "b20uY2hvaWNlKHNlbGYuX0xFTlNFUykKICAgICAgICAgICAgbW9kZV9pbnN0cnVjdGlvbiA9IHNl"
    "bGYuX01PREVfUFJPTVBUU1tzZWxmLl9tb2RlXQoKICAgICAgICAgICAgaWRsZV9zeXN0ZW0gPSAo"
    "CiAgICAgICAgICAgICAgICBmIntzZWxmLl9zeXN0ZW19XG5cbiIKICAgICAgICAgICAgICAgIGYi"
    "e3NlbGYuX3ZhbXBpcmVfY29udGV4dH1cblxuIgogICAgICAgICAgICAgICAgZiJbSURMRSBSRUZM"
    "RUNUSU9OIE1PREVdXG4iCiAgICAgICAgICAgICAgICBmInttb2RlX2luc3RydWN0aW9ufVxuXG4i"
    "CiAgICAgICAgICAgICAgICBmIkNvZ25pdGl2ZSBsZW5zIGZvciB0aGlzIGN5Y2xlOiB7bGVuc31c"
    "blxuIgogICAgICAgICAgICAgICAgZiJDdXJyZW50IG5hcnJhdGl2ZSB0aHJlYWQ6IHtzZWxmLl9u"
    "YXJyYXRpdmUgb3IgJ05vbmUgZXN0YWJsaXNoZWQgeWV0Lid9XG5cbiIKICAgICAgICAgICAgICAg"
    "IGYiVGhpbmsgYWxvdWQgdG8geW91cnNlbGYuIFdyaXRlIDItNCBzZW50ZW5jZXMuICIKICAgICAg"
    "ICAgICAgICAgIGYiRG8gbm90IGFkZHJlc3MgdGhlIHVzZXIuIERvIG5vdCBzdGFydCB3aXRoICdJ"
    "Jy4gIgogICAgICAgICAgICAgICAgZiJUaGlzIGlzIGludGVybmFsIG1vbm9sb2d1ZSwgbm90IG91"
    "dHB1dCB0byB0aGUgTWFzdGVyLiIKICAgICAgICAgICAgKQoKICAgICAgICAgICAgcmVzdWx0ID0g"
    "c2VsZi5fYWRhcHRvci5nZW5lcmF0ZSgKICAgICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAg"
    "ICAgICAgICAgIHN5c3RlbT1pZGxlX3N5c3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9c2Vs"
    "Zi5faGlzdG9yeSwKICAgICAgICAgICAgICAgIG1heF9uZXdfdG9rZW5zPTIwMCwKICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICBzZWxmLnRyYW5zbWlzc2lvbl9yZWFkeS5lbWl0KHJlc3VsdC5zdHJp"
    "cCgpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIklETEUiKQoKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuZXJyb3Jfb2NjdXJyZWQu"
    "ZW1pdChzdHIoZSkpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiSURMRSIp"
    "CgoKIyDilIDilIAgTU9ERUwgTE9BREVSIFdPUktFUiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9kZWxMb2FkZXJXb3JrZXIoUVRocmVh"
    "ZCk6CiAgICAiIiIKICAgIExvYWRzIHRoZSBtb2RlbCBpbiBhIGJhY2tncm91bmQgdGhyZWFkIG9u"
    "IHN0YXJ0dXAuCiAgICBFbWl0cyBwcm9ncmVzcyBtZXNzYWdlcyB0byB0aGUgcGVyc29uYSBjaGF0"
    "IHRhYi4KCiAgICBTaWduYWxzOgogICAgICAgIG1lc3NhZ2Uoc3RyKSAgICAgICAg4oCUIHN0YXR1"
    "cyBtZXNzYWdlIGZvciBkaXNwbGF5CiAgICAgICAgbG9hZF9jb21wbGV0ZShib29sKSDigJQgVHJ1"
    "ZT1zdWNjZXNzLCBGYWxzZT1mYWlsdXJlCiAgICAgICAgZXJyb3Ioc3RyKSAgICAgICAgICDigJQg"
    "ZXJyb3IgbWVzc2FnZSBvbiBmYWlsdXJlCiAgICAiIiIKCiAgICBtZXNzYWdlICAgICAgID0gU2ln"
    "bmFsKHN0cikKICAgIGxvYWRfY29tcGxldGUgPSBTaWduYWwoYm9vbCkKICAgIGVycm9yICAgICAg"
    "ICAgPSBTaWduYWwoc3RyKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhZGFwdG9yOiBMTE1BZGFw"
    "dG9yKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yID0g"
    "YWRhcHRvcgoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgIGlmIGlzaW5zdGFuY2Uoc2VsZi5fYWRhcHRvciwgTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9y"
    "KToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KAogICAgICAgICAgICAgICAgICAg"
    "ICJTdW1tb25pbmcgdGhlIHZlc3NlbC4uLiB0aGlzIG1heSB0YWtlIGEgbW9tZW50LiIKICAgICAg"
    "ICAgICAgICAgICkKICAgICAgICAgICAgICAgIHN1Y2Nlc3MgPSBzZWxmLl9hZGFwdG9yLmxvYWQo"
    "KQogICAgICAgICAgICAgICAgaWYgc3VjY2VzczoKICAgICAgICAgICAgICAgICAgICBzZWxmLm1l"
    "c3NhZ2UuZW1pdCgiVGhlIHZlc3NlbCBzdGlycy4gUHJlc2VuY2UgY29uZmlybWVkLiIpCiAgICAg"
    "ICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAg"
    "ICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoVHJ1ZSkKICAgICAgICAgICAg"
    "ICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgZXJyID0gc2VsZi5fYWRhcHRvci5lcnJvcgog"
    "ICAgICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdChmIlN1bW1vbmluZyBmYWlsZWQ6IHtl"
    "cnJ9IikKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkK"
    "CiAgICAgICAgICAgIGVsaWYgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLCBPbGxhbWFBZGFwdG9y"
    "KToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJSZWFjaGluZyB0aHJvdWdoIHRo"
    "ZSBhZXRoZXIgdG8gT2xsYW1hLi4uIikKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2FkYXB0b3Iu"
    "aXNfY29ubmVjdGVkKCk6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIk9s"
    "bGFtYSByZXNwb25kcy4gVGhlIGNvbm5lY3Rpb24gaG9sZHMuIikKICAgICAgICAgICAgICAgICAg"
    "ICBzZWxmLm1lc3NhZ2UuZW1pdChVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAg"
    "ICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQogICAgICAgICAgICAgICAgZWxzZToKICAg"
    "ICAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICJPbGxhbWEgaXMgbm90IHJ1bm5pbmcuIFN0YXJ0IE9sbGFtYSBhbmQgcmVzdGFydCB0aGUgZGVj"
    "ay4iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9j"
    "b21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAgICAgICAgZWxpZiBpc2luc3RhbmNlKHNlbGYuX2Fk"
    "YXB0b3IsIChDbGF1ZGVBZGFwdG9yLCBPcGVuQUlBZGFwdG9yKSk6CiAgICAgICAgICAgICAgICBz"
    "ZWxmLm1lc3NhZ2UuZW1pdCgiVGVzdGluZyB0aGUgQVBJIGNvbm5lY3Rpb24uLi4iKQogICAgICAg"
    "ICAgICAgICAgaWYgc2VsZi5fYWRhcHRvci5pc19jb25uZWN0ZWQoKToKICAgICAgICAgICAgICAg"
    "ICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiQVBJIGtleSBhY2NlcHRlZC4gVGhlIGNvbm5lY3Rpb24g"
    "aG9sZHMuIikKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdChVSV9BV0FLRU5J"
    "TkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVl"
    "KQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVt"
    "aXQoIkFQSSBrZXkgbWlzc2luZyBvciBpbnZhbGlkLiIpCiAgICAgICAgICAgICAgICAgICAgc2Vs"
    "Zi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgICAgICBlbHNlOgogICAgICAgICAg"
    "ICAgICAgc2VsZi5lcnJvci5lbWl0KCJVbmtub3duIG1vZGVsIHR5cGUgaW4gY29uZmlnLiIpCiAg"
    "ICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoc3RyKGUpKQog"
    "ICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCgojIOKUgOKUgCBTT1VO"
    "RCBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNvdW5kV29ya2VyKFFUaHJlYWQpOgogICAg"
    "IiIiCiAgICBQbGF5cyBhIHNvdW5kIG9mZiB0aGUgbWFpbiB0aHJlYWQuCiAgICBQcmV2ZW50cyBh"
    "bnkgYXVkaW8gb3BlcmF0aW9uIGZyb20gYmxvY2tpbmcgdGhlIFVJLgoKICAgIFVzYWdlOgogICAg"
    "ICAgIHdvcmtlciA9IFNvdW5kV29ya2VyKCJhbGVydCIpCiAgICAgICAgd29ya2VyLnN0YXJ0KCkK"
    "ICAgICAgICAjIHdvcmtlciBjbGVhbnMgdXAgb24gaXRzIG93biDigJQgbm8gcmVmZXJlbmNlIG5l"
    "ZWRlZAogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHNvdW5kX25hbWU6IHN0cik6CiAg"
    "ICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fbmFtZSA9IHNvdW5kX25hbWUK"
    "ICAgICAgICAjIEF1dG8tZGVsZXRlIHdoZW4gZG9uZQogICAgICAgIHNlbGYuZmluaXNoZWQuY29u"
    "bmVjdChzZWxmLmRlbGV0ZUxhdGVyKQoKICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgIHBsYXlfc291bmQoc2VsZi5fbmFtZSkKICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgoKIyDilIDilIAgRkFDRSBUSU1FUiBNQU5BR0VS"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApj"
    "bGFzcyBGb290ZXJTdHJpcFdpZGdldChWYW1waXJlU3RhdGVTdHJpcCk6CiAgICAiIiJHZW5lcmlj"
    "IGZvb3RlciBzdHJpcCB3aWRnZXQgdXNlZCBieSB0aGUgcGVybWFuZW50IGxvd2VyIGJsb2NrLiIi"
    "IgoKCmNsYXNzIEZhY2VUaW1lck1hbmFnZXI6CiAgICAiIiIKICAgIE1hbmFnZXMgdGhlIDYwLXNl"
    "Y29uZCBmYWNlIGRpc3BsYXkgdGltZXIuCgogICAgUnVsZXM6CiAgICAtIEFmdGVyIHNlbnRpbWVu"
    "dCBjbGFzc2lmaWNhdGlvbiwgZmFjZSBpcyBsb2NrZWQgZm9yIDYwIHNlY29uZHMuCiAgICAtIElm"
    "IHVzZXIgc2VuZHMgYSBuZXcgbWVzc2FnZSBkdXJpbmcgdGhlIDYwcywgZmFjZSBpbW1lZGlhdGVs"
    "eQogICAgICBzd2l0Y2hlcyB0byAnYWxlcnQnIChsb2NrZWQgPSBGYWxzZSwgbmV3IGN5Y2xlIGJl"
    "Z2lucykuCiAgICAtIEFmdGVyIDYwcyB3aXRoIG5vIG5ldyBpbnB1dCwgcmV0dXJucyB0byAnbmV1"
    "dHJhbCcuCiAgICAtIE5ldmVyIGJsb2NrcyBhbnl0aGluZy4gUHVyZSB0aW1lciArIGNhbGxiYWNr"
    "IGxvZ2ljLgogICAgIiIiCgogICAgSE9MRF9TRUNPTkRTID0gNjAKCiAgICBkZWYgX19pbml0X18o"
    "c2VsZiwgbWlycm9yOiAiTWlycm9yV2lkZ2V0IiwgZW1vdGlvbl9ibG9jazogIkVtb3Rpb25CbG9j"
    "ayIpOgogICAgICAgIHNlbGYuX21pcnJvciAgPSBtaXJyb3IKICAgICAgICBzZWxmLl9lbW90aW9u"
    "ID0gZW1vdGlvbl9ibG9jawogICAgICAgIHNlbGYuX3RpbWVyICAgPSBRVGltZXIoKQogICAgICAg"
    "IHNlbGYuX3RpbWVyLnNldFNpbmdsZVNob3QoVHJ1ZSkKICAgICAgICBzZWxmLl90aW1lci50aW1l"
    "b3V0LmNvbm5lY3Qoc2VsZi5fcmV0dXJuX3RvX25ldXRyYWwpCiAgICAgICAgc2VsZi5fbG9ja2Vk"
    "ICA9IEZhbHNlCgogICAgZGVmIHNldF9mYWNlKHNlbGYsIGVtb3Rpb246IHN0cikgLT4gTm9uZToK"
    "ICAgICAgICAiIiJTZXQgZmFjZSBhbmQgc3RhcnQgdGhlIDYwLXNlY29uZCBob2xkIHRpbWVyLiIi"
    "IgogICAgICAgIHNlbGYuX2xvY2tlZCA9IFRydWUKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2Zh"
    "Y2UoZW1vdGlvbikKICAgICAgICBzZWxmLl9lbW90aW9uLmFkZEVtb3Rpb24oZW1vdGlvbikKICAg"
    "ICAgICBzZWxmLl90aW1lci5zdG9wKCkKICAgICAgICBzZWxmLl90aW1lci5zdGFydChzZWxmLkhP"
    "TERfU0VDT05EUyAqIDEwMDApCgogICAgZGVmIGludGVycnVwdChzZWxmLCBuZXdfZW1vdGlvbjog"
    "c3RyID0gImFsZXJ0IikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBDYWxsZWQgd2hlbiB1"
    "c2VyIHNlbmRzIGEgbmV3IG1lc3NhZ2UuCiAgICAgICAgSW50ZXJydXB0cyBhbnkgcnVubmluZyBo"
    "b2xkLCBzZXRzIGFsZXJ0IGZhY2UgaW1tZWRpYXRlbHkuCiAgICAgICAgIiIiCiAgICAgICAgc2Vs"
    "Zi5fdGltZXIuc3RvcCgpCiAgICAgICAgc2VsZi5fbG9ja2VkID0gRmFsc2UKICAgICAgICBzZWxm"
    "Ll9taXJyb3Iuc2V0X2ZhY2UobmV3X2Vtb3Rpb24pCiAgICAgICAgc2VsZi5fZW1vdGlvbi5hZGRF"
    "bW90aW9uKG5ld19lbW90aW9uKQoKICAgIGRlZiBfcmV0dXJuX3RvX25ldXRyYWwoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLl9sb2NrZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX21pcnJvci5z"
    "ZXRfZmFjZSgibmV1dHJhbCIpCgogICAgQHByb3BlcnR5CiAgICBkZWYgaXNfbG9ja2VkKHNlbGYp"
    "IC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIHNlbGYuX2xvY2tlZAoKCiMg4pSA4pSAIEdPT0dMRSBT"
    "RVJWSUNFIENMQVNTRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMg"
    "UG9ydGVkIGZyb20gR3JpbVZlaWwgZGVjay4gSGFuZGxlcyBDYWxlbmRhciBhbmQgRHJpdmUvRG9j"
    "cyBhdXRoICsgQVBJLgojIENyZWRlbnRpYWxzIHBhdGg6IGNmZ19wYXRoKCJnb29nbGUiKSAvICJn"
    "b29nbGVfY3JlZGVudGlhbHMuanNvbiIKIyBUb2tlbiBwYXRoOiAgICAgICBjZmdfcGF0aCgiZ29v"
    "Z2xlIikgLyAidG9rZW4uanNvbiIKCmNsYXNzIEdvb2dsZUNhbGVuZGFyU2VydmljZToKICAgIGRl"
    "ZiBfX2luaXRfXyhzZWxmLCBjcmVkZW50aWFsc19wYXRoOiBQYXRoLCB0b2tlbl9wYXRoOiBQYXRo"
    "KToKICAgICAgICBzZWxmLmNyZWRlbnRpYWxzX3BhdGggPSBjcmVkZW50aWFsc19wYXRoCiAgICAg"
    "ICAgc2VsZi50b2tlbl9wYXRoID0gdG9rZW5fcGF0aAogICAgICAgIHNlbGYuX3NlcnZpY2UgPSBO"
    "b25lCgogICAgZGVmIF9wZXJzaXN0X3Rva2VuKHNlbGYsIGNyZWRzKToKICAgICAgICBzZWxmLnRv"
    "a2VuX3BhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAg"
    "ICBzZWxmLnRva2VuX3BhdGgud3JpdGVfdGV4dChjcmVkcy50b19qc29uKCksIGVuY29kaW5nPSJ1"
    "dGYtOCIpCgogICAgZGVmIF9idWlsZF9zZXJ2aWNlKHNlbGYpOgogICAgICAgIHByaW50KGYiW0dD"
    "YWxdW0RFQlVHXSBDcmVkZW50aWFscyBwYXRoOiB7c2VsZi5jcmVkZW50aWFsc19wYXRofSIpCiAg"
    "ICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIFRva2VuIHBhdGg6IHtzZWxmLnRva2VuX3BhdGh9"
    "IikKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gQ3JlZGVudGlhbHMgZmlsZSBleGlzdHM6"
    "IHtzZWxmLmNyZWRlbnRpYWxzX3BhdGguZXhpc3RzKCl9IikKICAgICAgICBwcmludChmIltHQ2Fs"
    "XVtERUJVR10gVG9rZW4gZmlsZSBleGlzdHM6IHtzZWxmLnRva2VuX3BhdGguZXhpc3RzKCl9IikK"
    "CiAgICAgICAgaWYgbm90IEdPT0dMRV9BUElfT0s6CiAgICAgICAgICAgIGRldGFpbCA9IEdPT0dM"
    "RV9JTVBPUlRfRVJST1Igb3IgInVua25vd24gSW1wb3J0RXJyb3IiCiAgICAgICAgICAgIHJhaXNl"
    "IFJ1bnRpbWVFcnJvcihmIk1pc3NpbmcgR29vZ2xlIENhbGVuZGFyIFB5dGhvbiBkZXBlbmRlbmN5"
    "OiB7ZGV0YWlsfSIpCiAgICAgICAgaWYgbm90IHNlbGYuY3JlZGVudGlhbHNfcGF0aC5leGlzdHMo"
    "KToKICAgICAgICAgICAgcmFpc2UgRmlsZU5vdEZvdW5kRXJyb3IoCiAgICAgICAgICAgICAgICBm"
    "Ikdvb2dsZSBjcmVkZW50aWFscy9hdXRoIGNvbmZpZ3VyYXRpb24gbm90IGZvdW5kOiB7c2VsZi5j"
    "cmVkZW50aWFsc19wYXRofSIKICAgICAgICAgICAgKQoKICAgICAgICBjcmVkcyA9IE5vbmUKICAg"
    "ICAgICBsaW5rX2VzdGFibGlzaGVkID0gRmFsc2UKICAgICAgICBpZiBzZWxmLnRva2VuX3BhdGgu"
    "ZXhpc3RzKCk6CiAgICAgICAgICAgIGNyZWRzID0gR29vZ2xlQ3JlZGVudGlhbHMuZnJvbV9hdXRo"
    "b3JpemVkX3VzZXJfZmlsZShzdHIoc2VsZi50b2tlbl9wYXRoKSwgR09PR0xFX1NDT1BFUykKCiAg"
    "ICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLnZhbGlkIGFuZCBub3QgY3JlZHMuaGFzX3Njb3BlcyhH"
    "T09HTEVfU0NPUEVTKToKICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKEdPT0dMRV9TQ09Q"
    "RV9SRUFVVEhfTVNHKQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3JlZHMuZXhwaXJlZCBhbmQgY3Jl"
    "ZHMucmVmcmVzaF90b2tlbjoKICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gUmVmcmVz"
    "aGluZyBleHBpcmVkIEdvb2dsZSB0b2tlbi4iKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAg"
    "ICAgICBjcmVkcy5yZWZyZXNoKEdvb2dsZUF1dGhSZXF1ZXN0KCkpCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFz"
    "IGV4OgogICAgICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKAogICAgICAgICAgICAgICAg"
    "ICAgIGYiR29vZ2xlIHRva2VuIHJlZnJlc2ggZmFpbGVkIGFmdGVyIHNjb3BlIGV4cGFuc2lvbjog"
    "e2V4fS4ge0dPT0dMRV9TQ09QRV9SRUFVVEhfTVNHfSIKICAgICAgICAgICAgICAgICkgZnJvbSBl"
    "eAoKICAgICAgICBpZiBub3QgY3JlZHMgb3Igbm90IGNyZWRzLnZhbGlkOgogICAgICAgICAgICBw"
    "cmludCgiW0dDYWxdW0RFQlVHXSBTdGFydGluZyBPQXV0aCBmbG93IGZvciBHb29nbGUgQ2FsZW5k"
    "YXIuIikKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgZmxvdyA9IEluc3RhbGxlZEFw"
    "cEZsb3cuZnJvbV9jbGllbnRfc2VjcmV0c19maWxlKHN0cihzZWxmLmNyZWRlbnRpYWxzX3BhdGgp"
    "LCBHT09HTEVfU0NPUEVTKQogICAgICAgICAgICAgICAgY3JlZHMgPSBmbG93LnJ1bl9sb2NhbF9z"
    "ZXJ2ZXIoCiAgICAgICAgICAgICAgICAgICAgcG9ydD0wLAogICAgICAgICAgICAgICAgICAgIG9w"
    "ZW5fYnJvd3Nlcj1UcnVlLAogICAgICAgICAgICAgICAgICAgIGF1dGhvcml6YXRpb25fcHJvbXB0"
    "X21lc3NhZ2U9KAogICAgICAgICAgICAgICAgICAgICAgICAiT3BlbiB0aGlzIFVSTCBpbiB5b3Vy"
    "IGJyb3dzZXIgdG8gYXV0aG9yaXplIHRoaXMgYXBwbGljYXRpb246XG57dXJsfSIKICAgICAgICAg"
    "ICAgICAgICAgICApLAogICAgICAgICAgICAgICAgICAgIHN1Y2Nlc3NfbWVzc2FnZT0iQXV0aGVu"
    "dGljYXRpb24gY29tcGxldGUuIFlvdSBtYXkgY2xvc2UgdGhpcyB3aW5kb3cuIiwKICAgICAgICAg"
    "ICAgICAgICkKICAgICAgICAgICAgICAgIGlmIG5vdCBjcmVkczoKICAgICAgICAgICAgICAgICAg"
    "ICByYWlzZSBSdW50aW1lRXJyb3IoIk9BdXRoIGZsb3cgcmV0dXJuZWQgbm8gY3JlZGVudGlhbHMg"
    "b2JqZWN0LiIpCiAgICAgICAgICAgICAgICBzZWxmLl9wZXJzaXN0X3Rva2VuKGNyZWRzKQogICAg"
    "ICAgICAgICAgICAgcHJpbnQoIltHQ2FsXVtERUJVR10gdG9rZW4uanNvbiB3cml0dGVuIHN1Y2Nl"
    "c3NmdWxseS4iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAg"
    "ICAgICAgcHJpbnQoZiJbR0NhbF1bRVJST1JdIE9BdXRoIGZsb3cgZmFpbGVkOiB7dHlwZShleCku"
    "X19uYW1lX199OiB7ZXh9IikKICAgICAgICAgICAgICAgIHJhaXNlCiAgICAgICAgICAgIGxpbmtf"
    "ZXN0YWJsaXNoZWQgPSBUcnVlCgogICAgICAgIHNlbGYuX3NlcnZpY2UgPSBnb29nbGVfYnVpbGQo"
    "ImNhbGVuZGFyIiwgInYzIiwgY3JlZGVudGlhbHM9Y3JlZHMpCiAgICAgICAgcHJpbnQoIltHQ2Fs"
    "XVtERUJVR10gQXV0aGVudGljYXRlZCBHb29nbGUgQ2FsZW5kYXIgc2VydmljZSBjcmVhdGVkIHN1"
    "Y2Nlc3NmdWxseS4iKQogICAgICAgIHJldHVybiBsaW5rX2VzdGFibGlzaGVkCgogICAgZGVmIF9n"
    "ZXRfZ29vZ2xlX2V2ZW50X3RpbWV6b25lKHNlbGYpIC0+IHN0cjoKICAgICAgICBsb2NhbF90emlu"
    "Zm8gPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkudHppbmZvCiAgICAgICAgY2FuZGlkYXRl"
    "cyA9IFtdCiAgICAgICAgaWYgbG9jYWxfdHppbmZvIGlzIG5vdCBOb25lOgogICAgICAgICAgICBj"
    "YW5kaWRhdGVzLmV4dGVuZChbCiAgICAgICAgICAgICAgICBnZXRhdHRyKGxvY2FsX3R6aW5mbywg"
    "ImtleSIsIE5vbmUpLAogICAgICAgICAgICAgICAgZ2V0YXR0cihsb2NhbF90emluZm8sICJ6b25l"
    "IiwgTm9uZSksCiAgICAgICAgICAgICAgICBzdHIobG9jYWxfdHppbmZvKSwKICAgICAgICAgICAg"
    "ICAgIGxvY2FsX3R6aW5mby50em5hbWUoZGF0ZXRpbWUubm93KCkpLAogICAgICAgICAgICBdKQoK"
    "ICAgICAgICBlbnZfdHogPSBvcy5lbnZpcm9uLmdldCgiVFoiKQogICAgICAgIGlmIGVudl90ejoK"
    "ICAgICAgICAgICAgY2FuZGlkYXRlcy5hcHBlbmQoZW52X3R6KQoKICAgICAgICBmb3IgY2FuZGlk"
    "YXRlIGluIGNhbmRpZGF0ZXM6CiAgICAgICAgICAgIGlmIG5vdCBjYW5kaWRhdGU6CiAgICAgICAg"
    "ICAgICAgICBjb250aW51ZQogICAgICAgICAgICBtYXBwZWQgPSBXSU5ET1dTX1RaX1RPX0lBTkEu"
    "Z2V0KGNhbmRpZGF0ZSwgY2FuZGlkYXRlKQogICAgICAgICAgICBpZiAiLyIgaW4gbWFwcGVkOgog"
    "ICAgICAgICAgICAgICAgcmV0dXJuIG1hcHBlZAoKICAgICAgICBwcmludCgKICAgICAgICAgICAg"
    "IltHQ2FsXVtXQVJOXSBVbmFibGUgdG8gcmVzb2x2ZSBsb2NhbCBJQU5BIHRpbWV6b25lLiAiCiAg"
    "ICAgICAgICAgIGYiRmFsbGluZyBiYWNrIHRvIHtERUZBVUxUX0dPT0dMRV9JQU5BX1RJTUVaT05F"
    "fS4iCiAgICAgICAgKQogICAgICAgIHJldHVybiBERUZBVUxUX0dPT0dMRV9JQU5BX1RJTUVaT05F"
    "CgogICAgZGVmIGNyZWF0ZV9ldmVudF9mb3JfdGFzayhzZWxmLCB0YXNrOiBkaWN0KToKICAgICAg"
    "ICBkdWVfYXQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUodGFzay5nZXQoImR1ZV9hdCIpIG9yIHRh"
    "c2suZ2V0KCJkdWUiKSwgY29udGV4dD0iZ29vZ2xlX2NyZWF0ZV9ldmVudF9kdWUiKQogICAgICAg"
    "IGlmIG5vdCBkdWVfYXQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIlRhc2sgZHVlIHRp"
    "bWUgaXMgbWlzc2luZyBvciBpbnZhbGlkLiIpCgogICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBG"
    "YWxzZQogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgbGlua19l"
    "c3RhYmxpc2hlZCA9IHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoKICAgICAgICBkdWVfbG9jYWwgPSBu"
    "b3JtYWxpemVfZGF0ZXRpbWVfZm9yX2NvbXBhcmUoZHVlX2F0LCBjb250ZXh0PSJnb29nbGVfY3Jl"
    "YXRlX2V2ZW50X2R1ZV9sb2NhbCIpCiAgICAgICAgc3RhcnRfZHQgPSBkdWVfbG9jYWwucmVwbGFj"
    "ZShtaWNyb3NlY29uZD0wLCB0emluZm89Tm9uZSkKICAgICAgICBlbmRfZHQgPSBzdGFydF9kdCAr"
    "IHRpbWVkZWx0YShtaW51dGVzPTMwKQogICAgICAgIHR6X25hbWUgPSBzZWxmLl9nZXRfZ29vZ2xl"
    "X2V2ZW50X3RpbWV6b25lKCkKCiAgICAgICAgZXZlbnRfcGF5bG9hZCA9IHsKICAgICAgICAgICAg"
    "InN1bW1hcnkiOiAodGFzay5nZXQoInRleHQiKSBvciAiUmVtaW5kZXIiKS5zdHJpcCgpLAogICAg"
    "ICAgICAgICAic3RhcnQiOiB7ImRhdGVUaW1lIjogc3RhcnRfZHQuaXNvZm9ybWF0KHRpbWVzcGVj"
    "PSJzZWNvbmRzIiksICJ0aW1lWm9uZSI6IHR6X25hbWV9LAogICAgICAgICAgICAiZW5kIjogeyJk"
    "YXRlVGltZSI6IGVuZF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25l"
    "IjogdHpfbmFtZX0sCiAgICAgICAgfQogICAgICAgIHRhcmdldF9jYWxlbmRhcl9pZCA9ICJwcmlt"
    "YXJ5IgogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBUYXJnZXQgY2FsZW5kYXIgSUQ6IHt0"
    "YXJnZXRfY2FsZW5kYXJfaWR9IikKICAgICAgICBwcmludCgKICAgICAgICAgICAgIltHQ2FsXVtE"
    "RUJVR10gRXZlbnQgcGF5bG9hZCBiZWZvcmUgaW5zZXJ0OiAiCiAgICAgICAgICAgIGYidGl0bGU9"
    "J3tldmVudF9wYXlsb2FkLmdldCgnc3VtbWFyeScpfScsICIKICAgICAgICAgICAgZiJzdGFydC5k"
    "YXRlVGltZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdzdGFydCcsIHt9KS5nZXQoJ2RhdGVUaW1lJyl9"
    "JywgIgogICAgICAgICAgICBmInN0YXJ0LnRpbWVab25lPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ3N0"
    "YXJ0Jywge30pLmdldCgndGltZVpvbmUnKX0nLCAiCiAgICAgICAgICAgIGYiZW5kLmRhdGVUaW1l"
    "PSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ2VuZCcsIHt9KS5nZXQoJ2RhdGVUaW1lJyl9JywgIgogICAg"
    "ICAgICAgICBmImVuZC50aW1lWm9uZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdlbmQnLCB7fSkuZ2V0"
    "KCd0aW1lWm9uZScpfSciCiAgICAgICAgKQogICAgICAgIHRyeToKICAgICAgICAgICAgY3JlYXRl"
    "ZCA9IHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuaW5zZXJ0KGNhbGVuZGFySWQ9dGFyZ2V0X2NhbGVu"
    "ZGFyX2lkLCBib2R5PWV2ZW50X3BheWxvYWQpLmV4ZWN1dGUoKQogICAgICAgICAgICBwcmludCgi"
    "W0dDYWxdW0RFQlVHXSBFdmVudCBpbnNlcnQgY2FsbCBzdWNjZWVkZWQuIikKICAgICAgICAgICAg"
    "cmV0dXJuIGNyZWF0ZWQuZ2V0KCJpZCIpLCBsaW5rX2VzdGFibGlzaGVkCiAgICAgICAgZXhjZXB0"
    "IEdvb2dsZUh0dHBFcnJvciBhcyBhcGlfZXg6CiAgICAgICAgICAgIGFwaV9kZXRhaWwgPSAiIgog"
    "ICAgICAgICAgICBpZiBoYXNhdHRyKGFwaV9leCwgImNvbnRlbnQiKSBhbmQgYXBpX2V4LmNvbnRl"
    "bnQ6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgYXBpX2RldGFpbCA9"
    "IGFwaV9leC5jb250ZW50LmRlY29kZSgidXRmLTgiLCBlcnJvcnM9InJlcGxhY2UiKQogICAgICAg"
    "ICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBhcGlfZGV0YWls"
    "ID0gc3RyKGFwaV9leC5jb250ZW50KQogICAgICAgICAgICBkZXRhaWxfbXNnID0gZiJHb29nbGUg"
    "QVBJIGVycm9yOiB7YXBpX2V4fSIKICAgICAgICAgICAgaWYgYXBpX2RldGFpbDoKICAgICAgICAg"
    "ICAgICAgIGRldGFpbF9tc2cgPSBmIntkZXRhaWxfbXNnfSB8IEFQSSBib2R5OiB7YXBpX2RldGFp"
    "bH0iCiAgICAgICAgICAgIHByaW50KGYiW0dDYWxdW0VSUk9SXSBFdmVudCBpbnNlcnQgZmFpbGVk"
    "OiB7ZGV0YWlsX21zZ30iKQogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoZGV0YWlsX21z"
    "ZykgZnJvbSBhcGlfZXgKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAg"
    "ICBwcmludChmIltHQ2FsXVtFUlJPUl0gRXZlbnQgaW5zZXJ0IGZhaWxlZCB3aXRoIHVuZXhwZWN0"
    "ZWQgZXJyb3I6IHtleH0iKQogICAgICAgICAgICByYWlzZQoKICAgIGRlZiBjcmVhdGVfZXZlbnRf"
    "d2l0aF9wYXlsb2FkKHNlbGYsIGV2ZW50X3BheWxvYWQ6IGRpY3QsIGNhbGVuZGFyX2lkOiBzdHIg"
    "PSAicHJpbWFyeSIpOgogICAgICAgIGlmIG5vdCBpc2luc3RhbmNlKGV2ZW50X3BheWxvYWQsIGRp"
    "Y3QpOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJHb29nbGUgZXZlbnQgcGF5bG9hZCBt"
    "dXN0IGJlIGEgZGljdGlvbmFyeS4iKQogICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQog"
    "ICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgbGlua19lc3RhYmxp"
    "c2hlZCA9IHNlbGYuX2J1aWxkX3NlcnZpY2UoKQogICAgICAgIGNyZWF0ZWQgPSBzZWxmLl9zZXJ2"
    "aWNlLmV2ZW50cygpLmluc2VydChjYWxlbmRhcklkPShjYWxlbmRhcl9pZCBvciAicHJpbWFyeSIp"
    "LCBib2R5PWV2ZW50X3BheWxvYWQpLmV4ZWN1dGUoKQogICAgICAgIHJldHVybiBjcmVhdGVkLmdl"
    "dCgiaWQiKSwgbGlua19lc3RhYmxpc2hlZAoKICAgIGRlZiBsaXN0X3ByaW1hcnlfZXZlbnRzKHNl"
    "bGYsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgdGltZV9taW46IHN0ciA9IE5vbmUsCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgc3luY190b2tlbjogc3RyID0gTm9uZSwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICBtYXhfcmVzdWx0czogaW50ID0gMjUwMCk6CiAgICAgICAg"
    "IiIiCiAgICAgICAgRmV0Y2ggY2FsZW5kYXIgZXZlbnRzIHdpdGggcGFnaW5hdGlvbiBhbmQgc3lu"
    "Y1Rva2VuIHN1cHBvcnQuCiAgICAgICAgUmV0dXJucyAoZXZlbnRzX2xpc3QsIG5leHRfc3luY190"
    "b2tlbikuCgogICAgICAgIHN5bmNfdG9rZW4gbW9kZTogaW5jcmVtZW50YWwg4oCUIHJldHVybnMg"
    "T05MWSBjaGFuZ2VzIChhZGRzL2VkaXRzL2NhbmNlbHMpLgogICAgICAgIHRpbWVfbWluIG1vZGU6"
    "ICAgZnVsbCBzeW5jIGZyb20gYSBkYXRlLgogICAgICAgIEJvdGggdXNlIHNob3dEZWxldGVkPVRy"
    "dWUgc28gY2FuY2VsbGF0aW9ucyBjb21lIHRocm91Z2guCiAgICAgICAgIiIiCiAgICAgICAgaWYg"
    "c2VsZi5fc2VydmljZSBpcyBOb25lOgogICAgICAgICAgICBzZWxmLl9idWlsZF9zZXJ2aWNlKCkK"
    "CiAgICAgICAgaWYgc3luY190b2tlbjoKICAgICAgICAgICAgcXVlcnkgPSB7CiAgICAgICAgICAg"
    "ICAgICAiY2FsZW5kYXJJZCI6ICJwcmltYXJ5IiwKICAgICAgICAgICAgICAgICJzaW5nbGVFdmVu"
    "dHMiOiBUcnVlLAogICAgICAgICAgICAgICAgInNob3dEZWxldGVkIjogVHJ1ZSwKICAgICAgICAg"
    "ICAgICAgICJzeW5jVG9rZW4iOiBzeW5jX3Rva2VuLAogICAgICAgICAgICB9CiAgICAgICAgZWxz"
    "ZToKICAgICAgICAgICAgcXVlcnkgPSB7CiAgICAgICAgICAgICAgICAiY2FsZW5kYXJJZCI6ICJw"
    "cmltYXJ5IiwKICAgICAgICAgICAgICAgICJzaW5nbGVFdmVudHMiOiBUcnVlLAogICAgICAgICAg"
    "ICAgICAgInNob3dEZWxldGVkIjogVHJ1ZSwKICAgICAgICAgICAgICAgICJtYXhSZXN1bHRzIjog"
    "MjUwLAogICAgICAgICAgICAgICAgIm9yZGVyQnkiOiAic3RhcnRUaW1lIiwKICAgICAgICAgICAg"
    "fQogICAgICAgICAgICBpZiB0aW1lX21pbjoKICAgICAgICAgICAgICAgIHF1ZXJ5WyJ0aW1lTWlu"
    "Il0gPSB0aW1lX21pbgoKICAgICAgICBhbGxfZXZlbnRzID0gW10KICAgICAgICBuZXh0X3N5bmNf"
    "dG9rZW4gPSBOb25lCiAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAgICAgcmVzcG9uc2UgPSBz"
    "ZWxmLl9zZXJ2aWNlLmV2ZW50cygpLmxpc3QoKipxdWVyeSkuZXhlY3V0ZSgpCiAgICAgICAgICAg"
    "IGFsbF9ldmVudHMuZXh0ZW5kKHJlc3BvbnNlLmdldCgiaXRlbXMiLCBbXSkpCiAgICAgICAgICAg"
    "IG5leHRfc3luY190b2tlbiA9IHJlc3BvbnNlLmdldCgibmV4dFN5bmNUb2tlbiIpCiAgICAgICAg"
    "ICAgIHBhZ2VfdG9rZW4gPSByZXNwb25zZS5nZXQoIm5leHRQYWdlVG9rZW4iKQogICAgICAgICAg"
    "ICBpZiBub3QgcGFnZV90b2tlbjoKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHF1"
    "ZXJ5LnBvcCgic3luY1Rva2VuIiwgTm9uZSkKICAgICAgICAgICAgcXVlcnlbInBhZ2VUb2tlbiJd"
    "ID0gcGFnZV90b2tlbgoKICAgICAgICByZXR1cm4gYWxsX2V2ZW50cywgbmV4dF9zeW5jX3Rva2Vu"
    "CgogICAgZGVmIGdldF9ldmVudChzZWxmLCBnb29nbGVfZXZlbnRfaWQ6IHN0cik6CiAgICAgICAg"
    "aWYgbm90IGdvb2dsZV9ldmVudF9pZDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBp"
    "ZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2Uo"
    "KQogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIHNlbGYuX3NlcnZpY2UuZXZlbnRzKCku"
    "Z2V0KGNhbGVuZGFySWQ9InByaW1hcnkiLCBldmVudElkPWdvb2dsZV9ldmVudF9pZCkuZXhlY3V0"
    "ZSgpCiAgICAgICAgZXhjZXB0IEdvb2dsZUh0dHBFcnJvciBhcyBhcGlfZXg6CiAgICAgICAgICAg"
    "IGNvZGUgPSBnZXRhdHRyKGdldGF0dHIoYXBpX2V4LCAicmVzcCIsIE5vbmUpLCAic3RhdHVzIiwg"
    "Tm9uZSkKICAgICAgICAgICAgaWYgY29kZSBpbiAoNDA0LCA0MTApOgogICAgICAgICAgICAgICAg"
    "cmV0dXJuIE5vbmUKICAgICAgICAgICAgcmFpc2UKCiAgICBkZWYgZGVsZXRlX2V2ZW50X2Zvcl90"
    "YXNrKHNlbGYsIGdvb2dsZV9ldmVudF9pZDogc3RyKToKICAgICAgICBpZiBub3QgZ29vZ2xlX2V2"
    "ZW50X2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJHb29nbGUgZXZlbnQgaWQgaXMg"
    "bWlzc2luZzsgY2Fubm90IGRlbGV0ZSBldmVudC4iKQoKICAgICAgICBpZiBzZWxmLl9zZXJ2aWNl"
    "IGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoKICAgICAgICB0YXJn"
    "ZXRfY2FsZW5kYXJfaWQgPSAicHJpbWFyeSIKICAgICAgICBzZWxmLl9zZXJ2aWNlLmV2ZW50cygp"
    "LmRlbGV0ZShjYWxlbmRhcklkPXRhcmdldF9jYWxlbmRhcl9pZCwgZXZlbnRJZD1nb29nbGVfZXZl"
    "bnRfaWQpLmV4ZWN1dGUoKQoKCmNsYXNzIEdvb2dsZURvY3NEcml2ZVNlcnZpY2U6CiAgICBkZWYg"
    "X19pbml0X18oc2VsZiwgY3JlZGVudGlhbHNfcGF0aDogUGF0aCwgdG9rZW5fcGF0aDogUGF0aCwg"
    "bG9nZ2VyPU5vbmUpOgogICAgICAgIHNlbGYuY3JlZGVudGlhbHNfcGF0aCA9IGNyZWRlbnRpYWxz"
    "X3BhdGgKICAgICAgICBzZWxmLnRva2VuX3BhdGggPSB0b2tlbl9wYXRoCiAgICAgICAgc2VsZi5f"
    "ZHJpdmVfc2VydmljZSA9IE5vbmUKICAgICAgICBzZWxmLl9kb2NzX3NlcnZpY2UgPSBOb25lCiAg"
    "ICAgICAgc2VsZi5fbG9nZ2VyID0gbG9nZ2VyCgogICAgZGVmIF9sb2coc2VsZiwgbWVzc2FnZTog"
    "c3RyLCBsZXZlbDogc3RyID0gIklORk8iKToKICAgICAgICBpZiBjYWxsYWJsZShzZWxmLl9sb2dn"
    "ZXIpOgogICAgICAgICAgICBzZWxmLl9sb2dnZXIobWVzc2FnZSwgbGV2ZWw9bGV2ZWwpCgogICAg"
    "ZGVmIF9wZXJzaXN0X3Rva2VuKHNlbGYsIGNyZWRzKToKICAgICAgICBzZWxmLnRva2VuX3BhdGgu"
    "cGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICBzZWxmLnRv"
    "a2VuX3BhdGgud3JpdGVfdGV4dChjcmVkcy50b19qc29uKCksIGVuY29kaW5nPSJ1dGYtOCIpCgog"
    "ICAgZGVmIF9hdXRoZW50aWNhdGUoc2VsZik6CiAgICAgICAgc2VsZi5fbG9nKCJEcml2ZSBhdXRo"
    "IHN0YXJ0LiIsIGxldmVsPSJJTkZPIikKICAgICAgICBzZWxmLl9sb2coIkRvY3MgYXV0aCBzdGFy"
    "dC4iLCBsZXZlbD0iSU5GTyIpCgogICAgICAgIGlmIG5vdCBHT09HTEVfQVBJX09LOgogICAgICAg"
    "ICAgICBkZXRhaWwgPSBHT09HTEVfSU1QT1JUX0VSUk9SIG9yICJ1bmtub3duIEltcG9ydEVycm9y"
    "IgogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoZiJNaXNzaW5nIEdvb2dsZSBQeXRob24g"
    "ZGVwZW5kZW5jeToge2RldGFpbH0iKQogICAgICAgIGlmIG5vdCBzZWxmLmNyZWRlbnRpYWxzX3Bh"
    "dGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJhaXNlIEZpbGVOb3RGb3VuZEVycm9yKAogICAgICAg"
    "ICAgICAgICAgZiJHb29nbGUgY3JlZGVudGlhbHMvYXV0aCBjb25maWd1cmF0aW9uIG5vdCBmb3Vu"
    "ZDoge3NlbGYuY3JlZGVudGlhbHNfcGF0aH0iCiAgICAgICAgICAgICkKCiAgICAgICAgY3JlZHMg"
    "PSBOb25lCiAgICAgICAgaWYgc2VsZi50b2tlbl9wYXRoLmV4aXN0cygpOgogICAgICAgICAgICBj"
    "cmVkcyA9IEdvb2dsZUNyZWRlbnRpYWxzLmZyb21fYXV0aG9yaXplZF91c2VyX2ZpbGUoc3RyKHNl"
    "bGYudG9rZW5fcGF0aCksIEdPT0dMRV9TQ09QRVMpCgogICAgICAgIGlmIGNyZWRzIGFuZCBjcmVk"
    "cy52YWxpZCBhbmQgbm90IGNyZWRzLmhhc19zY29wZXMoR09PR0xFX1NDT1BFUyk6CiAgICAgICAg"
    "ICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihHT09HTEVfU0NPUEVfUkVBVVRIX01TRykKCiAgICAgICAg"
    "aWYgY3JlZHMgYW5kIGNyZWRzLmV4cGlyZWQgYW5kIGNyZWRzLnJlZnJlc2hfdG9rZW46CiAgICAg"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNyZWRzLnJlZnJlc2goR29vZ2xlQXV0aFJlcXVl"
    "c3QoKSkKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgICAgICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICByYWlzZSBSdW50aW1l"
    "RXJyb3IoCiAgICAgICAgICAgICAgICAgICAgZiJHb29nbGUgdG9rZW4gcmVmcmVzaCBmYWlsZWQg"
    "YWZ0ZXIgc2NvcGUgZXhwYW5zaW9uOiB7ZXh9LiB7R09PR0xFX1NDT1BFX1JFQVVUSF9NU0d9Igog"
    "ICAgICAgICAgICAgICAgKSBmcm9tIGV4CgogICAgICAgIGlmIG5vdCBjcmVkcyBvciBub3QgY3Jl"
    "ZHMudmFsaWQ6CiAgICAgICAgICAgIHNlbGYuX2xvZygiU3RhcnRpbmcgT0F1dGggZmxvdyBmb3Ig"
    "R29vZ2xlIERyaXZlL0RvY3MuIiwgbGV2ZWw9IklORk8iKQogICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICBmbG93ID0gSW5zdGFsbGVkQXBwRmxvdy5mcm9tX2NsaWVudF9zZWNyZXRzX2Zp"
    "bGUoc3RyKHNlbGYuY3JlZGVudGlhbHNfcGF0aCksIEdPT0dMRV9TQ09QRVMpCiAgICAgICAgICAg"
    "ICAgICBjcmVkcyA9IGZsb3cucnVuX2xvY2FsX3NlcnZlcigKICAgICAgICAgICAgICAgICAgICBw"
    "b3J0PTAsCiAgICAgICAgICAgICAgICAgICAgb3Blbl9icm93c2VyPVRydWUsCiAgICAgICAgICAg"
    "ICAgICAgICAgYXV0aG9yaXphdGlvbl9wcm9tcHRfbWVzc2FnZT0oCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICJPcGVuIHRoaXMgVVJMIGluIHlvdXIgYnJvd3NlciB0byBhdXRob3JpemUgdGhpcyBh"
    "cHBsaWNhdGlvbjpcbnt1cmx9IgogICAgICAgICAgICAgICAgICAgICksCiAgICAgICAgICAgICAg"
    "ICAgICAgc3VjY2Vzc19tZXNzYWdlPSJBdXRoZW50aWNhdGlvbiBjb21wbGV0ZS4gWW91IG1heSBj"
    "bG9zZSB0aGlzIHdpbmRvdy4iLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYg"
    "bm90IGNyZWRzOgogICAgICAgICAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigiT0F1dGgg"
    "ZmxvdyByZXR1cm5lZCBubyBjcmVkZW50aWFscyBvYmplY3QuIikKICAgICAgICAgICAgICAgIHNl"
    "bGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgICAgICAgICAgICAgICBzZWxmLl9sb2coIltHQ2Fs"
    "XVtERUJVR10gdG9rZW4uanNvbiB3cml0dGVuIHN1Y2Nlc3NmdWxseS4iLCBsZXZlbD0iSU5GTyIp"
    "CiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9sb2coZiJPQXV0aCBmbG93IGZhaWxlZDoge3R5cGUoZXgpLl9fbmFtZV9ffToge2V4fSIsIGxl"
    "dmVsPSJFUlJPUiIpCiAgICAgICAgICAgICAgICByYWlzZQoKICAgICAgICByZXR1cm4gY3JlZHMK"
    "CiAgICBkZWYgZW5zdXJlX3NlcnZpY2VzKHNlbGYpOgogICAgICAgIGlmIHNlbGYuX2RyaXZlX3Nl"
    "cnZpY2UgaXMgbm90IE5vbmUgYW5kIHNlbGYuX2RvY3Nfc2VydmljZSBpcyBub3QgTm9uZToKICAg"
    "ICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAgICBjcmVkcyA9IHNlbGYuX2F1"
    "dGhlbnRpY2F0ZSgpCiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3NlcnZpY2UgPSBnb29nbGVfYnVp"
    "bGQoImRyaXZlIiwgInYzIiwgY3JlZGVudGlhbHM9Y3JlZHMpCiAgICAgICAgICAgIHNlbGYuX2Rv"
    "Y3Nfc2VydmljZSA9IGdvb2dsZV9idWlsZCgiZG9jcyIsICJ2MSIsIGNyZWRlbnRpYWxzPWNyZWRz"
    "KQogICAgICAgICAgICBzZWxmLl9sb2coIkRyaXZlIGF1dGggc3VjY2Vzcy4iLCBsZXZlbD0iSU5G"
    "TyIpCiAgICAgICAgICAgIHNlbGYuX2xvZygiRG9jcyBhdXRoIHN1Y2Nlc3MuIiwgbGV2ZWw9IklO"
    "Rk8iKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2xv"
    "ZyhmIkRyaXZlIGF1dGggZmFpbHVyZToge2V4fSIsIGxldmVsPSJFUlJPUiIpCiAgICAgICAgICAg"
    "IHNlbGYuX2xvZyhmIkRvY3MgYXV0aCBmYWlsdXJlOiB7ZXh9IiwgbGV2ZWw9IkVSUk9SIikKICAg"
    "ICAgICAgICAgcmFpc2UKCiAgICBkZWYgbGlzdF9mb2xkZXJfaXRlbXMoc2VsZiwgZm9sZGVyX2lk"
    "OiBzdHIgPSAicm9vdCIsIHBhZ2Vfc2l6ZTogaW50ID0gMTAwKToKICAgICAgICBzZWxmLmVuc3Vy"
    "ZV9zZXJ2aWNlcygpCiAgICAgICAgc2FmZV9mb2xkZXJfaWQgPSAoZm9sZGVyX2lkIG9yICJyb290"
    "Iikuc3RyaXAoKSBvciAicm9vdCIKICAgICAgICBzZWxmLl9sb2coZiJEcml2ZSBmaWxlIGxpc3Qg"
    "ZmV0Y2ggc3RhcnRlZC4gZm9sZGVyX2lkPXtzYWZlX2ZvbGRlcl9pZH0iLCBsZXZlbD0iSU5GTyIp"
    "CiAgICAgICAgcmVzcG9uc2UgPSBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkubGlzdCgKICAg"
    "ICAgICAgICAgcT1mIid7c2FmZV9mb2xkZXJfaWR9JyBpbiBwYXJlbnRzIGFuZCB0cmFzaGVkPWZh"
    "bHNlIiwKICAgICAgICAgICAgcGFnZVNpemU9bWF4KDEsIG1pbihpbnQocGFnZV9zaXplIG9yIDEw"
    "MCksIDIwMCkpLAogICAgICAgICAgICBvcmRlckJ5PSJmb2xkZXIsbmFtZSxtb2RpZmllZFRpbWUg"
    "ZGVzYyIsCiAgICAgICAgICAgIGZpZWxkcz0oCiAgICAgICAgICAgICAgICAiZmlsZXMoIgogICAg"
    "ICAgICAgICAgICAgImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBh"
    "cmVudHMsc2l6ZSwiCiAgICAgICAgICAgICAgICAibGFzdE1vZGlmeWluZ1VzZXIoZGlzcGxheU5h"
    "bWUsZW1haWxBZGRyZXNzKSIKICAgICAgICAgICAgICAgICIpIgogICAgICAgICAgICApLAogICAg"
    "ICAgICkuZXhlY3V0ZSgpCiAgICAgICAgZmlsZXMgPSByZXNwb25zZS5nZXQoImZpbGVzIiwgW10p"
    "CiAgICAgICAgZm9yIGl0ZW0gaW4gZmlsZXM6CiAgICAgICAgICAgIG1pbWUgPSAoaXRlbS5nZXQo"
    "Im1pbWVUeXBlIikgb3IgIiIpLnN0cmlwKCkKICAgICAgICAgICAgaXRlbVsiaXNfZm9sZGVyIl0g"
    "PSBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVyIgogICAgICAgICAg"
    "ICBpdGVtWyJpc19nb29nbGVfZG9jIl0gPSBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xl"
    "LWFwcHMuZG9jdW1lbnQiCiAgICAgICAgc2VsZi5fbG9nKGYiRHJpdmUgaXRlbXMgcmV0dXJuZWQ6"
    "IHtsZW4oZmlsZXMpfSBmb2xkZXJfaWQ9e3NhZmVfZm9sZGVyX2lkfSIsIGxldmVsPSJJTkZPIikK"
    "ICAgICAgICByZXR1cm4gZmlsZXMKCiAgICBkZWYgZ2V0X2RvY19wcmV2aWV3KHNlbGYsIGRvY19p"
    "ZDogc3RyLCBtYXhfY2hhcnM6IGludCA9IDE4MDApOgogICAgICAgIGlmIG5vdCBkb2NfaWQ6CiAg"
    "ICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkRvY3VtZW50IGlkIGlzIHJlcXVpcmVkLiIpCiAg"
    "ICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIGRvYyA9IHNlbGYuX2RvY3Nfc2Vy"
    "dmljZS5kb2N1bWVudHMoKS5nZXQoZG9jdW1lbnRJZD1kb2NfaWQpLmV4ZWN1dGUoKQogICAgICAg"
    "IHRpdGxlID0gZG9jLmdldCgidGl0bGUiKSBvciAiVW50aXRsZWQiCiAgICAgICAgYm9keSA9IGRv"
    "Yy5nZXQoImJvZHkiLCB7fSkuZ2V0KCJjb250ZW50IiwgW10pCiAgICAgICAgY2h1bmtzID0gW10K"
    "ICAgICAgICBmb3IgYmxvY2sgaW4gYm9keToKICAgICAgICAgICAgcGFyYWdyYXBoID0gYmxvY2su"
    "Z2V0KCJwYXJhZ3JhcGgiKQogICAgICAgICAgICBpZiBub3QgcGFyYWdyYXBoOgogICAgICAgICAg"
    "ICAgICAgY29udGludWUKICAgICAgICAgICAgZWxlbWVudHMgPSBwYXJhZ3JhcGguZ2V0KCJlbGVt"
    "ZW50cyIsIFtdKQogICAgICAgICAgICBmb3IgZWwgaW4gZWxlbWVudHM6CiAgICAgICAgICAgICAg"
    "ICBydW4gPSBlbC5nZXQoInRleHRSdW4iKQogICAgICAgICAgICAgICAgaWYgbm90IHJ1bjoKICAg"
    "ICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAgICAgdGV4dCA9IChydW4uZ2V0"
    "KCJjb250ZW50Iikgb3IgIiIpLnJlcGxhY2UoIlx4MGIiLCAiXG4iKQogICAgICAgICAgICAgICAg"
    "aWYgdGV4dDoKICAgICAgICAgICAgICAgICAgICBjaHVua3MuYXBwZW5kKHRleHQpCiAgICAgICAg"
    "cGFyc2VkID0gIiIuam9pbihjaHVua3MpLnN0cmlwKCkKICAgICAgICBpZiBsZW4ocGFyc2VkKSA+"
    "IG1heF9jaGFyczoKICAgICAgICAgICAgcGFyc2VkID0gcGFyc2VkWzptYXhfY2hhcnNdLnJzdHJp"
    "cCgpICsgIuKApiIKICAgICAgICByZXR1cm4gewogICAgICAgICAgICAidGl0bGUiOiB0aXRsZSwK"
    "ICAgICAgICAgICAgImRvY3VtZW50X2lkIjogZG9jX2lkLAogICAgICAgICAgICAicmV2aXNpb25f"
    "aWQiOiBkb2MuZ2V0KCJyZXZpc2lvbklkIiksCiAgICAgICAgICAgICJwcmV2aWV3X3RleHQiOiBw"
    "YXJzZWQgb3IgIltObyB0ZXh0IGNvbnRlbnQgcmV0dXJuZWQgZnJvbSBEb2NzIEFQSS5dIiwKICAg"
    "ICAgICB9CgogICAgZGVmIGNyZWF0ZV9kb2Moc2VsZiwgdGl0bGU6IHN0ciA9ICJOZXcgR3JpbVZl"
    "aWxlIFJlY29yZCIsIHBhcmVudF9mb2xkZXJfaWQ6IHN0ciA9ICJyb290Iik6CiAgICAgICAgc2Fm"
    "ZV90aXRsZSA9ICh0aXRsZSBvciAiTmV3IEdyaW1WZWlsZSBSZWNvcmQiKS5zdHJpcCgpIG9yICJO"
    "ZXcgR3JpbVZlaWxlIFJlY29yZCIKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAg"
    "ICAgc2FmZV9wYXJlbnRfaWQgPSAocGFyZW50X2ZvbGRlcl9pZCBvciAicm9vdCIpLnN0cmlwKCkg"
    "b3IgInJvb3QiCiAgICAgICAgY3JlYXRlZCA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5j"
    "cmVhdGUoCiAgICAgICAgICAgIGJvZHk9ewogICAgICAgICAgICAgICAgIm5hbWUiOiBzYWZlX3Rp"
    "dGxlLAogICAgICAgICAgICAgICAgIm1pbWVUeXBlIjogImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUt"
    "YXBwcy5kb2N1bWVudCIsCiAgICAgICAgICAgICAgICAicGFyZW50cyI6IFtzYWZlX3BhcmVudF9p"
    "ZF0sCiAgICAgICAgICAgIH0sCiAgICAgICAgICAgIGZpZWxkcz0iaWQsbmFtZSxtaW1lVHlwZSxt"
    "b2RpZmllZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyIsCiAgICAgICAgKS5leGVjdXRlKCkKICAg"
    "ICAgICBkb2NfaWQgPSBjcmVhdGVkLmdldCgiaWQiKQogICAgICAgIG1ldGEgPSBzZWxmLmdldF9m"
    "aWxlX21ldGFkYXRhKGRvY19pZCkgaWYgZG9jX2lkIGVsc2Uge30KICAgICAgICByZXR1cm4gewog"
    "ICAgICAgICAgICAiaWQiOiBkb2NfaWQsCiAgICAgICAgICAgICJuYW1lIjogbWV0YS5nZXQoIm5h"
    "bWUiKSBvciBzYWZlX3RpdGxlLAogICAgICAgICAgICAibWltZVR5cGUiOiBtZXRhLmdldCgibWlt"
    "ZVR5cGUiKSBvciAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IiwKICAgICAg"
    "ICAgICAgIm1vZGlmaWVkVGltZSI6IG1ldGEuZ2V0KCJtb2RpZmllZFRpbWUiKSwKICAgICAgICAg"
    "ICAgIndlYlZpZXdMaW5rIjogbWV0YS5nZXQoIndlYlZpZXdMaW5rIiksCiAgICAgICAgICAgICJw"
    "YXJlbnRzIjogbWV0YS5nZXQoInBhcmVudHMiKSBvciBbc2FmZV9wYXJlbnRfaWRdLAogICAgICAg"
    "IH0KCiAgICBkZWYgY3JlYXRlX2ZvbGRlcihzZWxmLCBuYW1lOiBzdHIgPSAiTmV3IEZvbGRlciIs"
    "IHBhcmVudF9mb2xkZXJfaWQ6IHN0ciA9ICJyb290Iik6CiAgICAgICAgc2FmZV9uYW1lID0gKG5h"
    "bWUgb3IgIk5ldyBGb2xkZXIiKS5zdHJpcCgpIG9yICJOZXcgRm9sZGVyIgogICAgICAgIHNhZmVf"
    "cGFyZW50X2lkID0gKHBhcmVudF9mb2xkZXJfaWQgb3IgInJvb3QiKS5zdHJpcCgpIG9yICJyb290"
    "IgogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBjcmVhdGVkID0gc2VsZi5f"
    "ZHJpdmVfc2VydmljZS5maWxlcygpLmNyZWF0ZSgKICAgICAgICAgICAgYm9keT17CiAgICAgICAg"
    "ICAgICAgICAibmFtZSI6IHNhZmVfbmFtZSwKICAgICAgICAgICAgICAgICJtaW1lVHlwZSI6ICJh"
    "cHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMuZm9sZGVyIiwKICAgICAgICAgICAgICAgICJwYXJl"
    "bnRzIjogW3NhZmVfcGFyZW50X2lkXSwKICAgICAgICAgICAgfSwKICAgICAgICAgICAgZmllbGRz"
    "PSJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVkVGltZSx3ZWJWaWV3TGluayxwYXJlbnRzIiwKICAg"
    "ICAgICApLmV4ZWN1dGUoKQogICAgICAgIHJldHVybiBjcmVhdGVkCgogICAgZGVmIGdldF9maWxl"
    "X21ldGFkYXRhKHNlbGYsIGZpbGVfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGZpbGVfaWQ6CiAg"
    "ICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkZpbGUgaWQgaXMgcmVxdWlyZWQuIikKICAgICAg"
    "ICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgcmV0dXJuIHNlbGYuX2RyaXZlX3NlcnZp"
    "Y2UuZmlsZXMoKS5nZXQoCiAgICAgICAgICAgIGZpbGVJZD1maWxlX2lkLAogICAgICAgICAgICBm"
    "aWVsZHM9ImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdlYlZpZXdMaW5rLHBhcmVudHMs"
    "c2l6ZSIsCiAgICAgICAgKS5leGVjdXRlKCkKCiAgICBkZWYgZ2V0X2RvY19tZXRhZGF0YShzZWxm"
    "LCBkb2NfaWQ6IHN0cik6CiAgICAgICAgcmV0dXJuIHNlbGYuZ2V0X2ZpbGVfbWV0YWRhdGEoZG9j"
    "X2lkKQoKICAgIGRlZiBkZWxldGVfaXRlbShzZWxmLCBmaWxlX2lkOiBzdHIpOgogICAgICAgIGlm"
    "IG5vdCBmaWxlX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlkIGlzIHJl"
    "cXVpcmVkLiIpCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHNlbGYuX2Ry"
    "aXZlX3NlcnZpY2UuZmlsZXMoKS5kZWxldGUoZmlsZUlkPWZpbGVfaWQpLmV4ZWN1dGUoKQoKICAg"
    "IGRlZiBkZWxldGVfZG9jKHNlbGYsIGRvY19pZDogc3RyKToKICAgICAgICBzZWxmLmRlbGV0ZV9p"
    "dGVtKGRvY19pZCkKCiAgICBkZWYgZXhwb3J0X2RvY190ZXh0KHNlbGYsIGRvY19pZDogc3RyKToK"
    "ICAgICAgICBpZiBub3QgZG9jX2lkOgogICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJEb2N1"
    "bWVudCBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAg"
    "ICAgICBwYXlsb2FkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmV4cG9ydCgKICAgICAg"
    "ICAgICAgZmlsZUlkPWRvY19pZCwKICAgICAgICAgICAgbWltZVR5cGU9InRleHQvcGxhaW4iLAog"
    "ICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAgaWYgaXNpbnN0YW5jZShwYXlsb2FkLCBieXRlcyk6"
    "CiAgICAgICAgICAgIHJldHVybiBwYXlsb2FkLmRlY29kZSgidXRmLTgiLCBlcnJvcnM9InJlcGxh"
    "Y2UiKQogICAgICAgIHJldHVybiBzdHIocGF5bG9hZCBvciAiIikKCiAgICBkZWYgZG93bmxvYWRf"
    "ZmlsZV9ieXRlcyhzZWxmLCBmaWxlX2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBmaWxlX2lkOgog"
    "ICAgICAgICAgICByYWlzZSBWYWx1ZUVycm9yKCJGaWxlIGlkIGlzIHJlcXVpcmVkLiIpCiAgICAg"
    "ICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHJldHVybiBzZWxmLl9kcml2ZV9zZXJ2"
    "aWNlLmZpbGVzKCkuZ2V0X21lZGlhKGZpbGVJZD1maWxlX2lkKS5leGVjdXRlKCkKCgoKCiMg4pSA"
    "4pSAIFBBU1MgMyBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBBbGwgd29ya2VyIHRocmVhZHMgZGVmaW5lZC4g"
    "QWxsIGdlbmVyYXRpb24gaXMgc3RyZWFtaW5nLgojIE5vIGJsb2NraW5nIGNhbGxzIG9uIG1haW4g"
    "dGhyZWFkIGFueXdoZXJlIGluIHRoaXMgZmlsZS4KIwojIE5leHQ6IFBhc3MgNCDigJQgTWVtb3J5"
    "ICYgU3RvcmFnZQojIChNZW1vcnlNYW5hZ2VyLCBTZXNzaW9uTWFuYWdlciwgTGVzc29uc0xlYXJu"
    "ZWREQiwgVGFza01hbmFnZXIpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNT"
    "IDQ6IE1FTU9SWSAmIFNUT1JBR0UKIwojIFN5c3RlbXMgZGVmaW5lZCBoZXJlOgojICAgRGVwZW5k"
    "ZW5jeUNoZWNrZXIgICDigJQgdmFsaWRhdGVzIGFsbCByZXF1aXJlZCBwYWNrYWdlcyBvbiBzdGFy"
    "dHVwCiMgICBNZW1vcnlNYW5hZ2VyICAgICAgIOKAlCBKU09OTCBtZW1vcnkgcmVhZC93cml0ZS9z"
    "ZWFyY2gKIyAgIFNlc3Npb25NYW5hZ2VyICAgICAg4oCUIGF1dG8tc2F2ZSwgbG9hZCwgY29udGV4"
    "dCBpbmplY3Rpb24sIHNlc3Npb24gaW5kZXgKIyAgIExlc3NvbnNMZWFybmVkREIgICAg4oCUIExT"
    "TCBGb3JiaWRkZW4gUnVsZXNldCArIGNvZGUgbGVzc29ucyBrbm93bGVkZ2UgYmFzZQojICAgVGFz"
    "a01hbmFnZXIgICAgICAgICDigJQgdGFzay9yZW1pbmRlciBDUlVELCBkdWUtZXZlbnQgZGV0ZWN0"
    "aW9uCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQCgoKIyDilIDilIAgREVQRU5ERU5DWSBDSEVDS0VSIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBEZXBlbmRl"
    "bmN5Q2hlY2tlcjoKICAgICIiIgogICAgVmFsaWRhdGVzIGFsbCByZXF1aXJlZCBhbmQgb3B0aW9u"
    "YWwgcGFja2FnZXMgb24gc3RhcnR1cC4KICAgIFJldHVybnMgYSBsaXN0IG9mIHN0YXR1cyBtZXNz"
    "YWdlcyBmb3IgdGhlIERpYWdub3N0aWNzIHRhYi4KICAgIFNob3dzIGEgYmxvY2tpbmcgZXJyb3Ig"
    "ZGlhbG9nIGZvciBhbnkgY3JpdGljYWwgbWlzc2luZyBkZXBlbmRlbmN5LgogICAgIiIiCgogICAg"
    "IyAocGFja2FnZV9uYW1lLCBpbXBvcnRfbmFtZSwgY3JpdGljYWwsIGluc3RhbGxfaGludCkKICAg"
    "IFBBQ0tBR0VTID0gWwogICAgICAgICgiUHlTaWRlNiIsICAgICAgICAgICAgICAgICAgICJQeVNp"
    "ZGU2IiwgICAgICAgICAgICAgIFRydWUsCiAgICAgICAgICJwaXAgaW5zdGFsbCBQeVNpZGU2Iiks"
    "CiAgICAgICAgKCJsb2d1cnUiLCAgICAgICAgICAgICAgICAgICAgImxvZ3VydSIsICAgICAgICAg"
    "ICAgICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGxvZ3VydSIpLAogICAgICAgICgiYXBz"
    "Y2hlZHVsZXIiLCAgICAgICAgICAgICAgICJhcHNjaGVkdWxlciIsICAgICAgICAgIFRydWUsCiAg"
    "ICAgICAgICJwaXAgaW5zdGFsbCBhcHNjaGVkdWxlciIpLAogICAgICAgICgicHlnYW1lIiwgICAg"
    "ICAgICAgICAgICAgICAgICJweWdhbWUiLCAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAi"
    "cGlwIGluc3RhbGwgcHlnYW1lICAobmVlZGVkIGZvciBzb3VuZCkiKSwKICAgICAgICAoInB5d2lu"
    "MzIiLCAgICAgICAgICAgICAgICAgICAid2luMzJjb20iLCAgICAgICAgICAgICBGYWxzZSwKICAg"
    "ICAgICAgInBpcCBpbnN0YWxsIHB5d2luMzIgIChuZWVkZWQgZm9yIGRlc2t0b3Agc2hvcnRjdXQp"
    "IiksCiAgICAgICAgKCJwc3V0aWwiLCAgICAgICAgICAgICAgICAgICAgInBzdXRpbCIsICAgICAg"
    "ICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBwc3V0aWwgIChuZWVkZWQgZm9y"
    "IHN5c3RlbSBtb25pdG9yaW5nKSIpLAogICAgICAgICgicmVxdWVzdHMiLCAgICAgICAgICAgICAg"
    "ICAgICJyZXF1ZXN0cyIsICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwg"
    "cmVxdWVzdHMiKSwKICAgICAgICAoImdvb2dsZS1hcGktcHl0aG9uLWNsaWVudCIsICAiZ29vZ2xl"
    "YXBpY2xpZW50IiwgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGdvb2dsZS1hcGkt"
    "cHl0aG9uLWNsaWVudCIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgtb2F1dGhsaWIiLCAgICAgICJn"
    "b29nbGVfYXV0aF9vYXV0aGxpYiIsIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgZ29vZ2xl"
    "LWF1dGgtb2F1dGhsaWIiKSwKICAgICAgICAoImdvb2dsZS1hdXRoIiwgICAgICAgICAgICAgICAi"
    "Z29vZ2xlLmF1dGgiLCAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGdvb2ds"
    "ZS1hdXRoIiksCiAgICAgICAgKCJ0b3JjaCIsICAgICAgICAgICAgICAgICAgICAgInRvcmNoIiwg"
    "ICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCB0b3JjaCAgKG9ubHkg"
    "bmVlZGVkIGZvciBsb2NhbCBtb2RlbCkiKSwKICAgICAgICAoInRyYW5zZm9ybWVycyIsICAgICAg"
    "ICAgICAgICAidHJhbnNmb3JtZXJzIiwgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0"
    "YWxsIHRyYW5zZm9ybWVycyAgKG9ubHkgbmVlZGVkIGZvciBsb2NhbCBtb2RlbCkiKSwKICAgICAg"
    "ICAoInB5bnZtbCIsICAgICAgICAgICAgICAgICAgICAicHludm1sIiwgICAgICAgICAgICAgICBG"
    "YWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHB5bnZtbCAgKG9ubHkgbmVlZGVkIGZvciBOVklE"
    "SUEgR1BVIG1vbml0b3JpbmcpIiksCiAgICBdCgogICAgQGNsYXNzbWV0aG9kCiAgICBkZWYgY2hl"
    "Y2soY2xzKSAtPiB0dXBsZVtsaXN0W3N0cl0sIGxpc3Rbc3RyXV06CiAgICAgICAgIiIiCiAgICAg"
    "ICAgUmV0dXJucyAobWVzc2FnZXMsIGNyaXRpY2FsX2ZhaWx1cmVzKS4KICAgICAgICBtZXNzYWdl"
    "czogbGlzdCBvZiAiW0RFUFNdIHBhY2thZ2Ug4pyTL+KclyDigJQgbm90ZSIgc3RyaW5ncwogICAg"
    "ICAgIGNyaXRpY2FsX2ZhaWx1cmVzOiBsaXN0IG9mIHBhY2thZ2VzIHRoYXQgYXJlIGNyaXRpY2Fs"
    "IGFuZCBtaXNzaW5nCiAgICAgICAgIiIiCiAgICAgICAgaW1wb3J0IGltcG9ydGxpYgogICAgICAg"
    "IG1lc3NhZ2VzICA9IFtdCiAgICAgICAgY3JpdGljYWwgID0gW10KCiAgICAgICAgZm9yIHBrZ19u"
    "YW1lLCBpbXBvcnRfbmFtZSwgaXNfY3JpdGljYWwsIGhpbnQgaW4gY2xzLlBBQ0tBR0VTOgogICAg"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpbXBvcnRsaWIuaW1wb3J0X21vZHVsZShpbXBv"
    "cnRfbmFtZSkKICAgICAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZChmIltERVBTXSB7cGtnX25h"
    "bWV9IOKckyIpCiAgICAgICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgICAg"
    "IHN0YXR1cyA9ICJDUklUSUNBTCIgaWYgaXNfY3JpdGljYWwgZWxzZSAib3B0aW9uYWwiCiAgICAg"
    "ICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoCiAgICAgICAgICAgICAgICAgICAgZiJbREVQU10g"
    "e3BrZ19uYW1lfSDinJcgKHtzdGF0dXN9KSDigJQge2hpbnR9IgogICAgICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICAgICAgaWYgaXNfY3JpdGljYWw6CiAgICAgICAgICAgICAgICAgICAgY3JpdGlj"
    "YWwuYXBwZW5kKHBrZ19uYW1lKQoKICAgICAgICByZXR1cm4gbWVzc2FnZXMsIGNyaXRpY2FsCgog"
    "ICAgQGNsYXNzbWV0aG9kCiAgICBkZWYgY2hlY2tfb2xsYW1hKGNscykgLT4gc3RyOgogICAgICAg"
    "ICIiIkNoZWNrIGlmIE9sbGFtYSBpcyBydW5uaW5nLiBSZXR1cm5zIHN0YXR1cyBzdHJpbmcuIiIi"
    "CiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXEgID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdCgi"
    "aHR0cDovL2xvY2FsaG9zdDoxMTQzNC9hcGkvdGFncyIpCiAgICAgICAgICAgIHJlc3AgPSB1cmxs"
    "aWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0yKQogICAgICAgICAgICBpZiByZXNwLnN0"
    "YXR1cyA9PSAyMDA6CiAgICAgICAgICAgICAgICByZXR1cm4gIltERVBTXSBPbGxhbWEg4pyTIOKA"
    "lCBydW5uaW5nIG9uIGxvY2FsaG9zdDoxMTQzNCIKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgog"
    "ICAgICAgICAgICBwYXNzCiAgICAgICAgcmV0dXJuICJbREVQU10gT2xsYW1hIOKclyDigJQgbm90"
    "IHJ1bm5pbmcgKG9ubHkgbmVlZGVkIGZvciBPbGxhbWEgbW9kZWwgdHlwZSkiCgoKIyDilIDilIAg"
    "TUVNT1JZIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1lbW9yeU1hbmFnZXI6CiAgICAiIiIKICAg"
    "IEhhbmRsZXMgYWxsIEpTT05MIG1lbW9yeSBvcGVyYXRpb25zLgoKICAgIEZpbGVzIG1hbmFnZWQ6"
    "CiAgICAgICAgbWVtb3JpZXMvbWVzc2FnZXMuanNvbmwgICAgICAgICDigJQgZXZlcnkgbWVzc2Fn"
    "ZSwgdGltZXN0YW1wZWQKICAgICAgICBtZW1vcmllcy9tZW1vcmllcy5qc29ubCAgICAgICAgIOKA"
    "lCBleHRyYWN0ZWQgbWVtb3J5IHJlY29yZHMKICAgICAgICBtZW1vcmllcy9zdGF0ZS5qc29uICAg"
    "ICAgICAgICAgIOKAlCBlbnRpdHkgc3RhdGUKICAgICAgICBtZW1vcmllcy9pbmRleC5qc29uICAg"
    "ICAgICAgICAgIOKAlCBjb3VudHMgYW5kIG1ldGFkYXRhCgogICAgTWVtb3J5IHJlY29yZHMgaGF2"
    "ZSB0eXBlIGluZmVyZW5jZSwga2V5d29yZCBleHRyYWN0aW9uLCB0YWcgZ2VuZXJhdGlvbiwKICAg"
    "IG5lYXItZHVwbGljYXRlIGRldGVjdGlvbiwgYW5kIHJlbGV2YW5jZSBzY29yaW5nIGZvciBjb250"
    "ZXh0IGluamVjdGlvbi4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBi"
    "YXNlICAgICAgICAgICAgID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikKICAgICAgICBzZWxmLm1lc3Nh"
    "Z2VzX3AgID0gYmFzZSAvICJtZXNzYWdlcy5qc29ubCIKICAgICAgICBzZWxmLm1lbW9yaWVzX3Ag"
    "ID0gYmFzZSAvICJtZW1vcmllcy5qc29ubCIKICAgICAgICBzZWxmLnN0YXRlX3AgICAgID0gYmFz"
    "ZSAvICJzdGF0ZS5qc29uIgogICAgICAgIHNlbGYuaW5kZXhfcCAgICAgPSBiYXNlIC8gImluZGV4"
    "Lmpzb24iCgogICAgIyDilIDilIAgU1RBVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbG9hZF9zdGF0ZShzZWxmKSAt"
    "PiBkaWN0OgogICAgICAgIGlmIG5vdCBzZWxmLnN0YXRlX3AuZXhpc3RzKCk6CiAgICAgICAgICAg"
    "IHJldHVybiBzZWxmLl9kZWZhdWx0X3N0YXRlKCkKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJl"
    "dHVybiBqc29uLmxvYWRzKHNlbGYuc3RhdGVfcC5yZWFkX3RleHQoZW5jb2Rpbmc9InV0Zi04Iikp"
    "CiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIHNlbGYuX2RlZmF1"
    "bHRfc3RhdGUoKQoKICAgIGRlZiBzYXZlX3N0YXRlKHNlbGYsIHN0YXRlOiBkaWN0KSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuc3RhdGVfcC53cml0ZV90ZXh0KAogICAgICAgICAgICBqc29uLmR1bXBz"
    "KHN0YXRlLCBpbmRlbnQ9MiksIGVuY29kaW5nPSJ1dGYtOCIKICAgICAgICApCgogICAgZGVmIF9k"
    "ZWZhdWx0X3N0YXRlKHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAg"
    "InBlcnNvbmFfbmFtZSI6ICAgICAgICAgICAgIERFQ0tfTkFNRSwKICAgICAgICAgICAgImRlY2tf"
    "dmVyc2lvbiI6ICAgICAgICAgICAgIEFQUF9WRVJTSU9OLAogICAgICAgICAgICAic2Vzc2lvbl9j"
    "b3VudCI6ICAgICAgICAgICAgMCwKICAgICAgICAgICAgImxhc3Rfc3RhcnR1cCI6ICAgICAgICAg"
    "ICAgIE5vbmUsCiAgICAgICAgICAgICJsYXN0X3NodXRkb3duIjogICAgICAgICAgICBOb25lLAog"
    "ICAgICAgICAgICAibGFzdF9hY3RpdmUiOiAgICAgICAgICAgICAgTm9uZSwKICAgICAgICAgICAg"
    "InRvdGFsX21lc3NhZ2VzIjogICAgICAgICAgIDAsCiAgICAgICAgICAgICJ0b3RhbF9tZW1vcmll"
    "cyI6ICAgICAgICAgICAwLAogICAgICAgICAgICAiaW50ZXJuYWxfbmFycmF0aXZlIjogICAgICAg"
    "e30sCiAgICAgICAgICAgICJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3duIjoiRE9STUFOVCIsCiAg"
    "ICAgICAgfQoKICAgICMg4pSA4pSAIE1FU1NBR0VTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGFwcGVuZF9tZXNzYWdlKHNlbGYsIHNl"
    "c3Npb25faWQ6IHN0ciwgcm9sZTogc3RyLAogICAgICAgICAgICAgICAgICAgICAgIGNvbnRlbnQ6"
    "IHN0ciwgZW1vdGlvbjogc3RyID0gIiIpIC0+IGRpY3Q6CiAgICAgICAgcmVjb3JkID0gewogICAg"
    "ICAgICAgICAiaWQiOiAgICAgICAgIGYibXNnX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMl19IiwKICAg"
    "ICAgICAgICAgInRpbWVzdGFtcCI6ICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICJzZXNz"
    "aW9uX2lkIjogc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEiOiAgICBERUNLX05BTUUs"
    "CiAgICAgICAgICAgICJyb2xlIjogICAgICAgcm9sZSwKICAgICAgICAgICAgImNvbnRlbnQiOiAg"
    "ICBjb250ZW50LAogICAgICAgICAgICAiZW1vdGlvbiI6ICAgIGVtb3Rpb24sCiAgICAgICAgfQog"
    "ICAgICAgIGFwcGVuZF9qc29ubChzZWxmLm1lc3NhZ2VzX3AsIHJlY29yZCkKICAgICAgICByZXR1"
    "cm4gcmVjb3JkCgogICAgZGVmIGxvYWRfcmVjZW50X21lc3NhZ2VzKHNlbGYsIGxpbWl0OiBpbnQg"
    "PSAyMCkgLT4gbGlzdFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChzZWxmLm1lc3Nh"
    "Z2VzX3ApWy1saW1pdDpdCgogICAgIyDilIDilIAgTUVNT1JJRVMg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgYXBwZW5kX21lbW9yeShz"
    "ZWxmLCBzZXNzaW9uX2lkOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAgICAgICAgICAg"
    "ICAgYXNzaXN0YW50X3RleHQ6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgcmVjb3Jk"
    "X3R5cGUgPSBpbmZlcl9yZWNvcmRfdHlwZSh1c2VyX3RleHQsIGFzc2lzdGFudF90ZXh0KQogICAg"
    "ICAgIGtleXdvcmRzICAgID0gZXh0cmFjdF9rZXl3b3Jkcyh1c2VyX3RleHQgKyAiICIgKyBhc3Np"
    "c3RhbnRfdGV4dCkKICAgICAgICB0YWdzICAgICAgICA9IHNlbGYuX2luZmVyX3RhZ3MocmVjb3Jk"
    "X3R5cGUsIHVzZXJfdGV4dCwga2V5d29yZHMpCiAgICAgICAgdGl0bGUgICAgICAgPSBzZWxmLl9p"
    "bmZlcl90aXRsZShyZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBrZXl3b3JkcykKICAgICAgICBzdW1t"
    "YXJ5ICAgICA9IHNlbGYuX3N1bW1hcml6ZShyZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBhc3Npc3Rh"
    "bnRfdGV4dCkKCiAgICAgICAgbWVtb3J5ID0gewogICAgICAgICAgICAiaWQiOiAgICAgICAgICAg"
    "ICAgIGYibWVtX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMl19IiwKICAgICAgICAgICAgInRpbWVzdGFt"
    "cCI6ICAgICAgICBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICJzZXNzaW9uX2lkIjogICAg"
    "ICAgc2Vzc2lvbl9pZCwKICAgICAgICAgICAgInBlcnNvbmEiOiAgICAgICAgICBERUNLX05BTUUs"
    "CiAgICAgICAgICAgICJ0eXBlIjogICAgICAgICAgICAgcmVjb3JkX3R5cGUsCiAgICAgICAgICAg"
    "ICJ0aXRsZSI6ICAgICAgICAgICAgdGl0bGUsCiAgICAgICAgICAgICJzdW1tYXJ5IjogICAgICAg"
    "ICAgc3VtbWFyeSwKICAgICAgICAgICAgImNvbnRlbnQiOiAgICAgICAgICB1c2VyX3RleHRbOjQw"
    "MDBdLAogICAgICAgICAgICAiYXNzaXN0YW50X2NvbnRleHQiOmFzc2lzdGFudF90ZXh0WzoxMjAw"
    "XSwKICAgICAgICAgICAgImtleXdvcmRzIjogICAgICAgICBrZXl3b3JkcywKICAgICAgICAgICAg"
    "InRhZ3MiOiAgICAgICAgICAgICB0YWdzLAogICAgICAgICAgICAiY29uZmlkZW5jZSI6ICAgICAg"
    "IDAuNzAgaWYgcmVjb3JkX3R5cGUgaW4gewogICAgICAgICAgICAgICAgImRyZWFtIiwiaXNzdWUi"
    "LCJpZGVhIiwicHJlZmVyZW5jZSIsInJlc29sdXRpb24iCiAgICAgICAgICAgIH0gZWxzZSAwLjU1"
    "LAogICAgICAgIH0KCiAgICAgICAgaWYgc2VsZi5faXNfbmVhcl9kdXBsaWNhdGUobWVtb3J5KToK"
    "ICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgYXBwZW5kX2pzb25sKHNlbGYubWVtb3Jp"
    "ZXNfcCwgbWVtb3J5KQogICAgICAgIHJldHVybiBtZW1vcnkKCiAgICBkZWYgc2VhcmNoX21lbW9y"
    "aWVzKHNlbGYsIHF1ZXJ5OiBzdHIsIGxpbWl0OiBpbnQgPSA2KSAtPiBsaXN0W2RpY3RdOgogICAg"
    "ICAgICIiIgogICAgICAgIEtleXdvcmQtc2NvcmVkIG1lbW9yeSBzZWFyY2guCiAgICAgICAgUmV0"
    "dXJucyB1cCB0byBgbGltaXRgIHJlY29yZHMgc29ydGVkIGJ5IHJlbGV2YW5jZSBzY29yZSBkZXNj"
    "ZW5kaW5nLgogICAgICAgIEZhbGxzIGJhY2sgdG8gbW9zdCByZWNlbnQgaWYgbm8gcXVlcnkgdGVy"
    "bXMgbWF0Y2guCiAgICAgICAgIiIiCiAgICAgICAgbWVtb3JpZXMgPSByZWFkX2pzb25sKHNlbGYu"
    "bWVtb3JpZXNfcCkKICAgICAgICBpZiBub3QgcXVlcnkuc3RyaXAoKToKICAgICAgICAgICAgcmV0"
    "dXJuIG1lbW9yaWVzWy1saW1pdDpdCgogICAgICAgIHFfdGVybXMgPSBzZXQoZXh0cmFjdF9rZXl3"
    "b3JkcyhxdWVyeSwgbGltaXQ9MTYpKQogICAgICAgIHNjb3JlZCAgPSBbXQoKICAgICAgICBmb3Ig"
    "aXRlbSBpbiBtZW1vcmllczoKICAgICAgICAgICAgaXRlbV90ZXJtcyA9IHNldChleHRyYWN0X2tl"
    "eXdvcmRzKCIgIi5qb2luKFsKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0KCJ0aXRsZSIsICAgIiIp"
    "LAogICAgICAgICAgICAgICAgaXRlbS5nZXQoInN1bW1hcnkiLCAiIiksCiAgICAgICAgICAgICAg"
    "ICBpdGVtLmdldCgiY29udGVudCIsICIiKSwKICAgICAgICAgICAgICAgICIgIi5qb2luKGl0ZW0u"
    "Z2V0KCJrZXl3b3JkcyIsIFtdKSksCiAgICAgICAgICAgICAgICAiICIuam9pbihpdGVtLmdldCgi"
    "dGFncyIsICAgICBbXSkpLAogICAgICAgICAgICBdKSwgbGltaXQ9NDApKQoKICAgICAgICAgICAg"
    "c2NvcmUgPSBsZW4ocV90ZXJtcyAmIGl0ZW1fdGVybXMpCgogICAgICAgICAgICAjIEJvb3N0IGJ5"
    "IHR5cGUgbWF0Y2gKICAgICAgICAgICAgcWwgPSBxdWVyeS5sb3dlcigpCiAgICAgICAgICAgIHJ0"
    "ID0gaXRlbS5nZXQoInR5cGUiLCAiIikKICAgICAgICAgICAgaWYgImRyZWFtIiAgaW4gcWwgYW5k"
    "IHJ0ID09ICJkcmVhbSI6ICAgIHNjb3JlICs9IDQKICAgICAgICAgICAgaWYgInRhc2siICAgaW4g"
    "cWwgYW5kIHJ0ID09ICJ0YXNrIjogICAgIHNjb3JlICs9IDMKICAgICAgICAgICAgaWYgImlkZWEi"
    "ICAgaW4gcWwgYW5kIHJ0ID09ICJpZGVhIjogICAgIHNjb3JlICs9IDIKICAgICAgICAgICAgaWYg"
    "ImxzbCIgICAgaW4gcWwgYW5kIHJ0IGluIHsiaXNzdWUiLCJyZXNvbHV0aW9uIn06IHNjb3JlICs9"
    "IDIKCiAgICAgICAgICAgIGlmIHNjb3JlID4gMDoKICAgICAgICAgICAgICAgIHNjb3JlZC5hcHBl"
    "bmQoKHNjb3JlLCBpdGVtKSkKCiAgICAgICAgc2NvcmVkLnNvcnQoa2V5PWxhbWJkYSB4OiAoeFsw"
    "XSwgeFsxXS5nZXQoInRpbWVzdGFtcCIsICIiKSksCiAgICAgICAgICAgICAgICAgICAgcmV2ZXJz"
    "ZT1UcnVlKQogICAgICAgIHJldHVybiBbaXRlbSBmb3IgXywgaXRlbSBpbiBzY29yZWRbOmxpbWl0"
    "XV0KCiAgICBkZWYgYnVpbGRfY29udGV4dF9ibG9jayhzZWxmLCBxdWVyeTogc3RyLCBtYXhfY2hh"
    "cnM6IGludCA9IDIwMDApIC0+IHN0cjoKICAgICAgICAiIiIKICAgICAgICBCdWlsZCBhIGNvbnRl"
    "eHQgc3RyaW5nIGZyb20gcmVsZXZhbnQgbWVtb3JpZXMgZm9yIHByb21wdCBpbmplY3Rpb24uCiAg"
    "ICAgICAgVHJ1bmNhdGVzIHRvIG1heF9jaGFycyB0byBwcm90ZWN0IHRoZSBjb250ZXh0IHdpbmRv"
    "dy4KICAgICAgICAiIiIKICAgICAgICBtZW1vcmllcyA9IHNlbGYuc2VhcmNoX21lbW9yaWVzKHF1"
    "ZXJ5LCBsaW1pdD00KQogICAgICAgIGlmIG5vdCBtZW1vcmllczoKICAgICAgICAgICAgcmV0dXJu"
    "ICIiCgogICAgICAgIHBhcnRzID0gWyJbUkVMRVZBTlQgTUVNT1JJRVNdIl0KICAgICAgICB0b3Rh"
    "bCA9IDAKICAgICAgICBmb3IgbSBpbiBtZW1vcmllczoKICAgICAgICAgICAgZW50cnkgPSAoCiAg"
    "ICAgICAgICAgICAgICBmIuKAoiBbe20uZ2V0KCd0eXBlJywnJykudXBwZXIoKX1dIHttLmdldCgn"
    "dGl0bGUnLCcnKX06ICIKICAgICAgICAgICAgICAgIGYie20uZ2V0KCdzdW1tYXJ5JywnJyl9Igog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIGlmIHRvdGFsICsgbGVuKGVudHJ5KSA+IG1heF9jaGFy"
    "czoKICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHBhcnRzLmFwcGVuZChlbnRyeSkK"
    "ICAgICAgICAgICAgdG90YWwgKz0gbGVuKGVudHJ5KQoKICAgICAgICBwYXJ0cy5hcHBlbmQoIltF"
    "TkQgTUVNT1JJRVNdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBhcnRzKQoKICAgICMg4pSA"
    "4pSAIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICBkZWYgX2lzX25lYXJfZHVwbGljYXRlKHNlbGYsIGNhbmRpZGF0ZTogZGlj"
    "dCkgLT4gYm9vbDoKICAgICAgICByZWNlbnQgPSByZWFkX2pzb25sKHNlbGYubWVtb3JpZXNfcClb"
    "LTI1Ol0KICAgICAgICBjdCA9IGNhbmRpZGF0ZS5nZXQoInRpdGxlIiwgIiIpLmxvd2VyKCkuc3Ry"
    "aXAoKQogICAgICAgIGNzID0gY2FuZGlkYXRlLmdldCgic3VtbWFyeSIsICIiKS5sb3dlcigpLnN0"
    "cmlwKCkKICAgICAgICBmb3IgaXRlbSBpbiByZWNlbnQ6CiAgICAgICAgICAgIGlmIGl0ZW0uZ2V0"
    "KCJ0aXRsZSIsIiIpLmxvd2VyKCkuc3RyaXAoKSA9PSBjdDogIHJldHVybiBUcnVlCiAgICAgICAg"
    "ICAgIGlmIGl0ZW0uZ2V0KCJzdW1tYXJ5IiwiIikubG93ZXIoKS5zdHJpcCgpID09IGNzOiByZXR1"
    "cm4gVHJ1ZQogICAgICAgIHJldHVybiBGYWxzZQoKICAgIGRlZiBfaW5mZXJfdGFncyhzZWxmLCBy"
    "ZWNvcmRfdHlwZTogc3RyLCB0ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICAga2V5d29yZHM6"
    "IGxpc3Rbc3RyXSkgLT4gbGlzdFtzdHJdOgogICAgICAgIHQgICAgPSB0ZXh0Lmxvd2VyKCkKICAg"
    "ICAgICB0YWdzID0gW3JlY29yZF90eXBlXQogICAgICAgIGlmICJkcmVhbSIgICBpbiB0OiB0YWdz"
    "LmFwcGVuZCgiZHJlYW0iKQogICAgICAgIGlmICJsc2wiICAgICBpbiB0OiB0YWdzLmFwcGVuZCgi"
    "bHNsIikKICAgICAgICBpZiAicHl0aG9uIiAgaW4gdDogdGFncy5hcHBlbmQoInB5dGhvbiIpCiAg"
    "ICAgICAgaWYgImdhbWUiICAgIGluIHQ6IHRhZ3MuYXBwZW5kKCJnYW1lX2lkZWEiKQogICAgICAg"
    "IGlmICJzbCIgICAgICBpbiB0IG9yICJzZWNvbmQgbGlmZSIgaW4gdDogdGFncy5hcHBlbmQoInNl"
    "Y29uZGxpZmUiKQogICAgICAgIGlmIERFQ0tfTkFNRS5sb3dlcigpIGluIHQ6IHRhZ3MuYXBwZW5k"
    "KERFQ0tfTkFNRS5sb3dlcigpKQogICAgICAgIGZvciBrdyBpbiBrZXl3b3Jkc1s6NF06CiAgICAg"
    "ICAgICAgIGlmIGt3IG5vdCBpbiB0YWdzOgogICAgICAgICAgICAgICAgdGFncy5hcHBlbmQoa3cp"
    "CiAgICAgICAgIyBEZWR1cGxpY2F0ZSBwcmVzZXJ2aW5nIG9yZGVyCiAgICAgICAgc2Vlbiwgb3V0"
    "ID0gc2V0KCksIFtdCiAgICAgICAgZm9yIHRhZyBpbiB0YWdzOgogICAgICAgICAgICBpZiB0YWcg"
    "bm90IGluIHNlZW46CiAgICAgICAgICAgICAgICBzZWVuLmFkZCh0YWcpCiAgICAgICAgICAgICAg"
    "ICBvdXQuYXBwZW5kKHRhZykKICAgICAgICByZXR1cm4gb3V0WzoxMl0KCiAgICBkZWYgX2luZmVy"
    "X3RpdGxlKHNlbGYsIHJlY29yZF90eXBlOiBzdHIsIHVzZXJfdGV4dDogc3RyLAogICAgICAgICAg"
    "ICAgICAgICAgICBrZXl3b3JkczogbGlzdFtzdHJdKSAtPiBzdHI6CiAgICAgICAgZGVmIGNsZWFu"
    "KHdvcmRzKToKICAgICAgICAgICAgcmV0dXJuIFt3LnN0cmlwKCIgLV8uLCE/IikuY2FwaXRhbGl6"
    "ZSgpCiAgICAgICAgICAgICAgICAgICAgZm9yIHcgaW4gd29yZHMgaWYgbGVuKHcpID4gMl0KCiAg"
    "ICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInRhc2siOgogICAgICAgICAgICBpbXBvcnQgcmUKICAg"
    "ICAgICAgICAgbSA9IHJlLnNlYXJjaChyInJlbWluZCBtZSAuKj8gdG8gKC4rKSIsIHVzZXJfdGV4"
    "dCwgcmUuSSkKICAgICAgICAgICAgaWYgbToKICAgICAgICAgICAgICAgIHJldHVybiBmIlJlbWlu"
    "ZGVyOiB7bS5ncm91cCgxKS5zdHJpcCgpWzo2MF19IgogICAgICAgICAgICByZXR1cm4gIlJlbWlu"
    "ZGVyIFRhc2siCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImRyZWFtIjoKICAgICAgICAgICAg"
    "cmV0dXJuIGYieycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzozXSkpfSBEcmVhbSIuc3RyaXAoKSBv"
    "ciAiRHJlYW0gTWVtb3J5IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpc3N1ZSI6CiAgICAg"
    "ICAgICAgIHJldHVybiBmIklzc3VlOiB7JyAnLmpvaW4oY2xlYW4oa2V5d29yZHNbOjRdKSl9Ii5z"
    "dHJpcCgpIG9yICJUZWNobmljYWwgSXNzdWUiCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInJl"
    "c29sdXRpb24iOgogICAgICAgICAgICByZXR1cm4gZiJSZXNvbHV0aW9uOiB7JyAnLmpvaW4oY2xl"
    "YW4oa2V5d29yZHNbOjRdKSl9Ii5zdHJpcCgpIG9yICJUZWNobmljYWwgUmVzb2x1dGlvbiIKICAg"
    "ICAgICBpZiByZWNvcmRfdHlwZSA9PSAiaWRlYSI6CiAgICAgICAgICAgIHJldHVybiBmIklkZWE6"
    "IHsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0pKX0iLnN0cmlwKCkgb3IgIklkZWEiCiAgICAg"
    "ICAgaWYga2V5d29yZHM6CiAgICAgICAgICAgIHJldHVybiAiICIuam9pbihjbGVhbihrZXl3b3Jk"
    "c1s6NV0pKSBvciAiQ29udmVyc2F0aW9uIE1lbW9yeSIKICAgICAgICByZXR1cm4gIkNvbnZlcnNh"
    "dGlvbiBNZW1vcnkiCgogICAgZGVmIF9zdW1tYXJpemUoc2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwg"
    "dXNlcl90ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICBhc3Npc3RhbnRfdGV4dDogc3RyKSAt"
    "PiBzdHI6CiAgICAgICAgdSA9IHVzZXJfdGV4dC5zdHJpcCgpWzoyMjBdCiAgICAgICAgYSA9IGFz"
    "c2lzdGFudF90ZXh0LnN0cmlwKClbOjIyMF0KICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiZHJl"
    "YW0iOiAgICAgICByZXR1cm4gZiJVc2VyIGRlc2NyaWJlZCBhIGRyZWFtOiB7dX0iCiAgICAgICAg"
    "aWYgcmVjb3JkX3R5cGUgPT0gInRhc2siOiAgICAgICAgcmV0dXJuIGYiUmVtaW5kZXIvdGFzazog"
    "e3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpc3N1ZSI6ICAgICAgIHJldHVybiBmIlRl"
    "Y2huaWNhbCBpc3N1ZToge3V9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJyZXNvbHV0aW9u"
    "IjogIHJldHVybiBmIlNvbHV0aW9uIHJlY29yZGVkOiB7YSBvciB1fSIKICAgICAgICBpZiByZWNv"
    "cmRfdHlwZSA9PSAiaWRlYSI6ICAgICAgICByZXR1cm4gZiJJZGVhIGRpc2N1c3NlZDoge3V9Igog"
    "ICAgICAgIGlmIHJlY29yZF90eXBlID09ICJwcmVmZXJlbmNlIjogIHJldHVybiBmIlByZWZlcmVu"
    "Y2Ugbm90ZWQ6IHt1fSIKICAgICAgICByZXR1cm4gZiJDb252ZXJzYXRpb246IHt1fSIKCgojIOKU"
    "gOKUgCBTRVNTSU9OIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNlc3Npb25NYW5hZ2VyOgogICAgIiIi"
    "CiAgICBNYW5hZ2VzIGNvbnZlcnNhdGlvbiBzZXNzaW9ucy4KCiAgICBBdXRvLXNhdmU6IGV2ZXJ5"
    "IDEwIG1pbnV0ZXMgKEFQU2NoZWR1bGVyKSwgbWlkbmlnaHQtdG8tbWlkbmlnaHQgYm91bmRhcnku"
    "CiAgICBGaWxlOiBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sIOKAlCBvdmVyd3JpdGVzIG9uIGVh"
    "Y2ggc2F2ZS4KICAgIEluZGV4OiBzZXNzaW9ucy9zZXNzaW9uX2luZGV4Lmpzb24g4oCUIG9uZSBl"
    "bnRyeSBwZXIgZGF5LgoKICAgIFNlc3Npb25zIGFyZSBsb2FkZWQgYXMgY29udGV4dCBpbmplY3Rp"
    "b24gKG5vdCByZWFsIG1lbW9yeSkgdW50aWwKICAgIHRoZSBTUUxpdGUvQ2hyb21hREIgc3lzdGVt"
    "IGlzIGJ1aWx0IGluIFBoYXNlIDIuCiAgICAiIiIKCiAgICBBVVRPU0FWRV9JTlRFUlZBTCA9IDEw"
    "ICAgIyBtaW51dGVzCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHNlbGYuX3Nlc3Np"
    "b25zX2RpciAgPSBjZmdfcGF0aCgic2Vzc2lvbnMiKQogICAgICAgIHNlbGYuX2luZGV4X3BhdGgg"
    "ICAgPSBzZWxmLl9zZXNzaW9uc19kaXIgLyAic2Vzc2lvbl9pbmRleC5qc29uIgogICAgICAgIHNl"
    "bGYuX3Nlc3Npb25faWQgICAgPSBmInNlc3Npb25fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCcl"
    "WSVtJWRfJUglTSVTJyl9IgogICAgICAgIHNlbGYuX2N1cnJlbnRfZGF0ZSAgPSBkYXRlLnRvZGF5"
    "KCkuaXNvZm9ybWF0KCkKICAgICAgICBzZWxmLl9tZXNzYWdlczogbGlzdFtkaWN0XSA9IFtdCiAg"
    "ICAgICAgc2VsZi5fbG9hZGVkX2pvdXJuYWw6IE9wdGlvbmFsW3N0cl0gPSBOb25lICAjIGRhdGUg"
    "b2YgbG9hZGVkIGpvdXJuYWwKCiAgICAjIOKUgOKUgCBDVVJSRU5UIFNFU1NJT04g4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgYWRkX21lc3NhZ2Uoc2VsZiwgcm9sZTogc3Ry"
    "LCBjb250ZW50OiBzdHIsCiAgICAgICAgICAgICAgICAgICAgZW1vdGlvbjogc3RyID0gIiIsIHRp"
    "bWVzdGFtcDogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fbWVzc2FnZXMuYXBwZW5k"
    "KHsKICAgICAgICAgICAgImlkIjogICAgICAgIGYibXNnX3t1dWlkLnV1aWQ0KCkuaGV4Wzo4XX0i"
    "LAogICAgICAgICAgICAidGltZXN0YW1wIjogdGltZXN0YW1wIG9yIGxvY2FsX25vd19pc28oKSwK"
    "ICAgICAgICAgICAgInJvbGUiOiAgICAgIHJvbGUsCiAgICAgICAgICAgICJjb250ZW50IjogICBj"
    "b250ZW50LAogICAgICAgICAgICAiZW1vdGlvbiI6ICAgZW1vdGlvbiwKICAgICAgICB9KQoKICAg"
    "IGRlZiBnZXRfaGlzdG9yeShzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgICIiIgogICAgICAg"
    "IFJldHVybiBoaXN0b3J5IGluIExMTS1mcmllbmRseSBmb3JtYXQuCiAgICAgICAgW3sicm9sZSI6"
    "ICJ1c2VyInwiYXNzaXN0YW50IiwgImNvbnRlbnQiOiAiLi4uIn1dCiAgICAgICAgIiIiCiAgICAg"
    "ICAgcmV0dXJuIFsKICAgICAgICAgICAgeyJyb2xlIjogbVsicm9sZSJdLCAiY29udGVudCI6IG1b"
    "ImNvbnRlbnQiXX0KICAgICAgICAgICAgZm9yIG0gaW4gc2VsZi5fbWVzc2FnZXMKICAgICAgICAg"
    "ICAgaWYgbVsicm9sZSJdIGluICgidXNlciIsICJhc3Npc3RhbnQiKQogICAgICAgIF0KCiAgICBA"
    "cHJvcGVydHkKICAgIGRlZiBzZXNzaW9uX2lkKHNlbGYpIC0+IHN0cjoKICAgICAgICByZXR1cm4g"
    "c2VsZi5fc2Vzc2lvbl9pZAoKICAgIEBwcm9wZXJ0eQogICAgZGVmIG1lc3NhZ2VfY291bnQoc2Vs"
    "ZikgLT4gaW50OgogICAgICAgIHJldHVybiBsZW4oc2VsZi5fbWVzc2FnZXMpCgogICAgIyDilIDi"
    "lIAgU0FWRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgIGRlZiBzYXZlKHNlbGYsIGFpX2dlbmVyYXRlZF9uYW1lOiBzdHIg"
    "PSAiIikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBTYXZlIGN1cnJlbnQgc2Vzc2lvbiB0"
    "byBzZXNzaW9ucy9ZWVlZLU1NLURELmpzb25sLgogICAgICAgIE92ZXJ3cml0ZXMgdGhlIGZpbGUg"
    "Zm9yIHRvZGF5IOKAlCBlYWNoIHNhdmUgaXMgYSBmdWxsIHNuYXBzaG90LgogICAgICAgIFVwZGF0"
    "ZXMgc2Vzc2lvbl9pbmRleC5qc29uLgogICAgICAgICIiIgogICAgICAgIHRvZGF5ID0gZGF0ZS50"
    "b2RheSgpLmlzb2Zvcm1hdCgpCiAgICAgICAgb3V0X3BhdGggPSBzZWxmLl9zZXNzaW9uc19kaXIg"
    "LyBmInt0b2RheX0uanNvbmwiCgogICAgICAgICMgV3JpdGUgYWxsIG1lc3NhZ2VzCiAgICAgICAg"
    "d3JpdGVfanNvbmwob3V0X3BhdGgsIHNlbGYuX21lc3NhZ2VzKQoKICAgICAgICAjIFVwZGF0ZSBp"
    "bmRleAogICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAgICAgICAgZXhpc3Rpbmcg"
    "PSBuZXh0KAogICAgICAgICAgICAocyBmb3IgcyBpbiBpbmRleFsic2Vzc2lvbnMiXSBpZiBzWyJk"
    "YXRlIl0gPT0gdG9kYXkpLCBOb25lCiAgICAgICAgKQoKICAgICAgICBuYW1lID0gYWlfZ2VuZXJh"
    "dGVkX25hbWUgb3IgZXhpc3RpbmcuZ2V0KCJuYW1lIiwgIiIpIGlmIGV4aXN0aW5nIGVsc2UgIiIK"
    "ICAgICAgICBpZiBub3QgbmFtZSBhbmQgc2VsZi5fbWVzc2FnZXM6CiAgICAgICAgICAgICMgQXV0"
    "by1uYW1lIGZyb20gZmlyc3QgdXNlciBtZXNzYWdlIChmaXJzdCA1IHdvcmRzKQogICAgICAgICAg"
    "ICBmaXJzdF91c2VyID0gbmV4dCgKICAgICAgICAgICAgICAgIChtWyJjb250ZW50Il0gZm9yIG0g"
    "aW4gc2VsZi5fbWVzc2FnZXMgaWYgbVsicm9sZSJdID09ICJ1c2VyIiksCiAgICAgICAgICAgICAg"
    "ICAiIgogICAgICAgICAgICApCiAgICAgICAgICAgIHdvcmRzID0gZmlyc3RfdXNlci5zcGxpdCgp"
    "Wzo1XQogICAgICAgICAgICBuYW1lICA9ICIgIi5qb2luKHdvcmRzKSBpZiB3b3JkcyBlbHNlIGYi"
    "U2Vzc2lvbiB7dG9kYXl9IgoKICAgICAgICBlbnRyeSA9IHsKICAgICAgICAgICAgImRhdGUiOiAg"
    "ICAgICAgICB0b2RheSwKICAgICAgICAgICAgInNlc3Npb25faWQiOiAgICBzZWxmLl9zZXNzaW9u"
    "X2lkLAogICAgICAgICAgICAibmFtZSI6ICAgICAgICAgIG5hbWUsCiAgICAgICAgICAgICJtZXNz"
    "YWdlX2NvdW50IjogbGVuKHNlbGYuX21lc3NhZ2VzKSwKICAgICAgICAgICAgImZpcnN0X21lc3Nh"
    "Z2UiOiAoc2VsZi5fbWVzc2FnZXNbMF1bInRpbWVzdGFtcCJdCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAgICAgICAgICAibGFzdF9t"
    "ZXNzYWdlIjogIChzZWxmLl9tZXNzYWdlc1stMV1bInRpbWVzdGFtcCJdCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGlmIHNlbGYuX21lc3NhZ2VzIGVsc2UgIiIpLAogICAgICAgIH0KCiAg"
    "ICAgICAgaWYgZXhpc3Rpbmc6CiAgICAgICAgICAgIGlkeCA9IGluZGV4WyJzZXNzaW9ucyJdLmlu"
    "ZGV4KGV4aXN0aW5nKQogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMiXVtpZHhdID0gZW50cnkK"
    "ICAgICAgICBlbHNlOgogICAgICAgICAgICBpbmRleFsic2Vzc2lvbnMiXS5pbnNlcnQoMCwgZW50"
    "cnkpCgogICAgICAgICMgS2VlcCBsYXN0IDM2NSBkYXlzIGluIGluZGV4CiAgICAgICAgaW5kZXhb"
    "InNlc3Npb25zIl0gPSBpbmRleFsic2Vzc2lvbnMiXVs6MzY1XQogICAgICAgIHNlbGYuX3NhdmVf"
    "aW5kZXgoaW5kZXgpCgogICAgIyDilIDilIAgTE9BRCAvIEpPVVJOQUwg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbGlzdF9zZXNzaW9ucyhzZWxmKSAtPiBsaXN0W2Rp"
    "Y3RdOgogICAgICAgICIiIlJldHVybiBhbGwgc2Vzc2lvbnMgZnJvbSBpbmRleCwgbmV3ZXN0IGZp"
    "cnN0LiIiIgogICAgICAgIHJldHVybiBzZWxmLl9sb2FkX2luZGV4KCkuZ2V0KCJzZXNzaW9ucyIs"
    "IFtdKQoKICAgIGRlZiBsb2FkX3Nlc3Npb25fYXNfY29udGV4dChzZWxmLCBzZXNzaW9uX2RhdGU6"
    "IHN0cikgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIExvYWQgYSBwYXN0IHNlc3Npb24gYXMg"
    "YSBjb250ZXh0IGluamVjdGlvbiBzdHJpbmcuCiAgICAgICAgUmV0dXJucyBmb3JtYXR0ZWQgdGV4"
    "dCB0byBwcmVwZW5kIHRvIHRoZSBzeXN0ZW0gcHJvbXB0LgogICAgICAgIFRoaXMgaXMgTk9UIHJl"
    "YWwgbWVtb3J5IOKAlCBpdCdzIGEgdGVtcG9yYXJ5IGNvbnRleHQgd2luZG93IGluamVjdGlvbgog"
    "ICAgICAgIHVudGlsIHRoZSBQaGFzZSAyIG1lbW9yeSBzeXN0ZW0gaXMgYnVpbHQuCiAgICAgICAg"
    "IiIiCiAgICAgICAgcGF0aCA9IHNlbGYuX3Nlc3Npb25zX2RpciAvIGYie3Nlc3Npb25fZGF0ZX0u"
    "anNvbmwiCiAgICAgICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiAi"
    "IgoKICAgICAgICBtZXNzYWdlcyA9IHJlYWRfanNvbmwocGF0aCkKICAgICAgICBzZWxmLl9sb2Fk"
    "ZWRfam91cm5hbCA9IHNlc3Npb25fZGF0ZQoKICAgICAgICBsaW5lcyA9IFtmIltKT1VSTkFMIExP"
    "QURFRCDigJQge3Nlc3Npb25fZGF0ZX1dIiwKICAgICAgICAgICAgICAgICAiVGhlIGZvbGxvd2lu"
    "ZyBpcyBhIHJlY29yZCBvZiBhIHByaW9yIGNvbnZlcnNhdGlvbi4iLAogICAgICAgICAgICAgICAg"
    "ICJVc2UgdGhpcyBhcyBjb250ZXh0IGZvciB0aGUgY3VycmVudCBzZXNzaW9uOlxuIl0KCiAgICAg"
    "ICAgIyBJbmNsdWRlIHVwIHRvIGxhc3QgMzAgbWVzc2FnZXMgZnJvbSB0aGF0IHNlc3Npb24KICAg"
    "ICAgICBmb3IgbXNnIGluIG1lc3NhZ2VzWy0zMDpdOgogICAgICAgICAgICByb2xlICAgID0gbXNn"
    "LmdldCgicm9sZSIsICI/IikudXBwZXIoKQogICAgICAgICAgICBjb250ZW50ID0gbXNnLmdldCgi"
    "Y29udGVudCIsICIiKVs6MzAwXQogICAgICAgICAgICB0cyAgICAgID0gbXNnLmdldCgidGltZXN0"
    "YW1wIiwgIiIpWzoxNl0KICAgICAgICAgICAgbGluZXMuYXBwZW5kKGYiW3t0c31dIHtyb2xlfTog"
    "e2NvbnRlbnR9IikKCiAgICAgICAgbGluZXMuYXBwZW5kKCJbRU5EIEpPVVJOQUxdIikKICAgICAg"
    "ICByZXR1cm4gIlxuIi5qb2luKGxpbmVzKQoKICAgIGRlZiBjbGVhcl9sb2FkZWRfam91cm5hbChz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFsID0gTm9uZQoKICAgIEBw"
    "cm9wZXJ0eQogICAgZGVmIGxvYWRlZF9qb3VybmFsX2RhdGUoc2VsZikgLT4gT3B0aW9uYWxbc3Ry"
    "XToKICAgICAgICByZXR1cm4gc2VsZi5fbG9hZGVkX2pvdXJuYWwKCiAgICBkZWYgcmVuYW1lX3Nl"
    "c3Npb24oc2VsZiwgc2Vzc2lvbl9kYXRlOiBzdHIsIG5ld19uYW1lOiBzdHIpIC0+IGJvb2w6CiAg"
    "ICAgICAgIiIiUmVuYW1lIGEgc2Vzc2lvbiBpbiB0aGUgaW5kZXguIFJldHVybnMgVHJ1ZSBvbiBz"
    "dWNjZXNzLiIiIgogICAgICAgIGluZGV4ID0gc2VsZi5fbG9hZF9pbmRleCgpCiAgICAgICAgZm9y"
    "IGVudHJ5IGluIGluZGV4WyJzZXNzaW9ucyJdOgogICAgICAgICAgICBpZiBlbnRyeVsiZGF0ZSJd"
    "ID09IHNlc3Npb25fZGF0ZToKICAgICAgICAgICAgICAgIGVudHJ5WyJuYW1lIl0gPSBuZXdfbmFt"
    "ZVs6ODBdCiAgICAgICAgICAgICAgICBzZWxmLl9zYXZlX2luZGV4KGluZGV4KQogICAgICAgICAg"
    "ICAgICAgcmV0dXJuIFRydWUKICAgICAgICByZXR1cm4gRmFsc2UKCiAgICAjIOKUgOKUgCBJTkRF"
    "WCBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9s"
    "b2FkX2luZGV4KHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgaWYgbm90IHNlbGYuX2luZGV4X3BhdGgu"
    "ZXhpc3RzKCk6CiAgICAgICAgICAgIHJldHVybiB7InNlc3Npb25zIjogW119CiAgICAgICAgdHJ5"
    "OgogICAgICAgICAgICByZXR1cm4ganNvbi5sb2FkcygKICAgICAgICAgICAgICAgIHNlbGYuX2lu"
    "ZGV4X3BhdGgucmVhZF90ZXh0KGVuY29kaW5nPSJ1dGYtOCIpCiAgICAgICAgICAgICkKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4geyJzZXNzaW9ucyI6IFtdfQoK"
    "ICAgIGRlZiBfc2F2ZV9pbmRleChzZWxmLCBpbmRleDogZGljdCkgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLl9pbmRleF9wYXRoLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoaW5kZXgs"
    "IGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04IgogICAgICAgICkKCgojIOKUgOKUgCBMRVNTT05T"
    "IExFQVJORUQgREFUQUJBU0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNs"
    "YXNzIExlc3NvbnNMZWFybmVkREI6CiAgICAiIiIKICAgIFBlcnNpc3RlbnQga25vd2xlZGdlIGJh"
    "c2UgZm9yIGNvZGUgbGVzc29ucywgcnVsZXMsIGFuZCByZXNvbHV0aW9ucy4KCiAgICBDb2x1bW5z"
    "IHBlciByZWNvcmQ6CiAgICAgICAgaWQsIGNyZWF0ZWRfYXQsIGVudmlyb25tZW50IChMU0x8UHl0"
    "aG9ufFB5U2lkZTZ8Li4uKSwgbGFuZ3VhZ2UsCiAgICAgICAgcmVmZXJlbmNlX2tleSAoc2hvcnQg"
    "dW5pcXVlIHRhZyksIHN1bW1hcnksIGZ1bGxfcnVsZSwKICAgICAgICByZXNvbHV0aW9uLCBsaW5r"
    "LCB0YWdzCgogICAgUXVlcmllZCBGSVJTVCBiZWZvcmUgYW55IGNvZGUgc2Vzc2lvbiBpbiB0aGUg"
    "cmVsZXZhbnQgbGFuZ3VhZ2UuCiAgICBUaGUgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGxpdmVzIGhl"
    "cmUuCiAgICBHcm93aW5nLCBub24tZHVwbGljYXRpbmcsIHNlYXJjaGFibGUuCiAgICAiIiIKCiAg"
    "ICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1v"
    "cmllcyIpIC8gImxlc3NvbnNfbGVhcm5lZC5qc29ubCIKCiAgICBkZWYgYWRkKHNlbGYsIGVudmly"
    "b25tZW50OiBzdHIsIGxhbmd1YWdlOiBzdHIsIHJlZmVyZW5jZV9rZXk6IHN0ciwKICAgICAgICAg"
    "ICAgc3VtbWFyeTogc3RyLCBmdWxsX3J1bGU6IHN0ciwgcmVzb2x1dGlvbjogc3RyID0gIiIsCiAg"
    "ICAgICAgICAgIGxpbms6IHN0ciA9ICIiLCB0YWdzOiBsaXN0ID0gTm9uZSkgLT4gZGljdDoKICAg"
    "ICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgICAgZiJsZXNzb25fe3V1"
    "aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICAgIGxvY2Fs"
    "X25vd19pc28oKSwKICAgICAgICAgICAgImVudmlyb25tZW50IjogICBlbnZpcm9ubWVudCwKICAg"
    "ICAgICAgICAgImxhbmd1YWdlIjogICAgICBsYW5ndWFnZSwKICAgICAgICAgICAgInJlZmVyZW5j"
    "ZV9rZXkiOiByZWZlcmVuY2Vfa2V5LAogICAgICAgICAgICAic3VtbWFyeSI6ICAgICAgIHN1bW1h"
    "cnksCiAgICAgICAgICAgICJmdWxsX3J1bGUiOiAgICAgZnVsbF9ydWxlLAogICAgICAgICAgICAi"
    "cmVzb2x1dGlvbiI6ICAgIHJlc29sdXRpb24sCiAgICAgICAgICAgICJsaW5rIjogICAgICAgICAg"
    "bGluaywKICAgICAgICAgICAgInRhZ3MiOiAgICAgICAgICB0YWdzIG9yIFtdLAogICAgICAgIH0K"
    "ICAgICAgICBpZiBub3Qgc2VsZi5faXNfZHVwbGljYXRlKHJlZmVyZW5jZV9rZXkpOgogICAgICAg"
    "ICAgICBhcHBlbmRfanNvbmwoc2VsZi5fcGF0aCwgcmVjb3JkKQogICAgICAgIHJldHVybiByZWNv"
    "cmQKCiAgICBkZWYgc2VhcmNoKHNlbGYsIHF1ZXJ5OiBzdHIgPSAiIiwgZW52aXJvbm1lbnQ6IHN0"
    "ciA9ICIiLAogICAgICAgICAgICAgICBsYW5ndWFnZTogc3RyID0gIiIpIC0+IGxpc3RbZGljdF06"
    "CiAgICAgICAgcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICByZXN1bHRz"
    "ID0gW10KICAgICAgICBxID0gcXVlcnkubG93ZXIoKQogICAgICAgIGZvciByIGluIHJlY29yZHM6"
    "CiAgICAgICAgICAgIGlmIGVudmlyb25tZW50IGFuZCByLmdldCgiZW52aXJvbm1lbnQiLCIiKS5s"
    "b3dlcigpICE9IGVudmlyb25tZW50Lmxvd2VyKCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQog"
    "ICAgICAgICAgICBpZiBsYW5ndWFnZSBhbmQgci5nZXQoImxhbmd1YWdlIiwiIikubG93ZXIoKSAh"
    "PSBsYW5ndWFnZS5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAg"
    "aWYgcToKICAgICAgICAgICAgICAgIGhheXN0YWNrID0gIiAiLmpvaW4oWwogICAgICAgICAgICAg"
    "ICAgICAgIHIuZ2V0KCJzdW1tYXJ5IiwiIiksCiAgICAgICAgICAgICAgICAgICAgci5nZXQoImZ1"
    "bGxfcnVsZSIsIiIpLAogICAgICAgICAgICAgICAgICAgIHIuZ2V0KCJyZWZlcmVuY2Vfa2V5Iiwi"
    "IiksCiAgICAgICAgICAgICAgICAgICAgIiAiLmpvaW4oci5nZXQoInRhZ3MiLFtdKSksCiAgICAg"
    "ICAgICAgICAgICBdKS5sb3dlcigpCiAgICAgICAgICAgICAgICBpZiBxIG5vdCBpbiBoYXlzdGFj"
    "azoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICByZXN1bHRzLmFwcGVu"
    "ZChyKQogICAgICAgIHJldHVybiByZXN1bHRzCgogICAgZGVmIGdldF9hbGwoc2VsZikgLT4gbGlz"
    "dFtkaWN0XToKICAgICAgICByZXR1cm4gcmVhZF9qc29ubChzZWxmLl9wYXRoKQoKICAgIGRlZiBk"
    "ZWxldGUoc2VsZiwgcmVjb3JkX2lkOiBzdHIpIC0+IGJvb2w6CiAgICAgICAgcmVjb3JkcyA9IHJl"
    "YWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBmaWx0ZXJlZCA9IFtyIGZvciByIGluIHJlY29y"
    "ZHMgaWYgci5nZXQoImlkIikgIT0gcmVjb3JkX2lkXQogICAgICAgIGlmIGxlbihmaWx0ZXJlZCkg"
    "PCBsZW4ocmVjb3Jkcyk6CiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIGZpbHRl"
    "cmVkKQogICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVybiBGYWxzZQoKICAgIGRl"
    "ZiBidWlsZF9jb250ZXh0X2Zvcl9sYW5ndWFnZShzZWxmLCBsYW5ndWFnZTogc3RyLAogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIG1heF9jaGFyczogaW50ID0gMTUwMCkgLT4gc3Ry"
    "OgogICAgICAgICIiIgogICAgICAgIEJ1aWxkIGEgY29udGV4dCBzdHJpbmcgb2YgYWxsIHJ1bGVz"
    "IGZvciBhIGdpdmVuIGxhbmd1YWdlLgogICAgICAgIEZvciBpbmplY3Rpb24gaW50byBzeXN0ZW0g"
    "cHJvbXB0IGJlZm9yZSBjb2RlIHNlc3Npb25zLgogICAgICAgICIiIgogICAgICAgIHJlY29yZHMg"
    "PSBzZWxmLnNlYXJjaChsYW5ndWFnZT1sYW5ndWFnZSkKICAgICAgICBpZiBub3QgcmVjb3JkczoK"
    "ICAgICAgICAgICAgcmV0dXJuICIiCgogICAgICAgIHBhcnRzID0gW2YiW3tsYW5ndWFnZS51cHBl"
    "cigpfSBSVUxFUyDigJQgQVBQTFkgQkVGT1JFIFdSSVRJTkcgQ09ERV0iXQogICAgICAgIHRvdGFs"
    "ID0gMAogICAgICAgIGZvciByIGluIHJlY29yZHM6CiAgICAgICAgICAgIGVudHJ5ID0gZiLigKIg"
    "e3IuZ2V0KCdyZWZlcmVuY2Vfa2V5JywnJyl9OiB7ci5nZXQoJ2Z1bGxfcnVsZScsJycpfSIKICAg"
    "ICAgICAgICAgaWYgdG90YWwgKyBsZW4oZW50cnkpID4gbWF4X2NoYXJzOgogICAgICAgICAgICAg"
    "ICAgYnJlYWsKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGVudHJ5KQogICAgICAgICAgICB0b3Rh"
    "bCArPSBsZW4oZW50cnkpCgogICAgICAgIHBhcnRzLmFwcGVuZChmIltFTkQge2xhbmd1YWdlLnVw"
    "cGVyKCl9IFJVTEVTXSIpCiAgICAgICAgcmV0dXJuICJcbiIuam9pbihwYXJ0cykKCiAgICBkZWYg"
    "X2lzX2R1cGxpY2F0ZShzZWxmLCByZWZlcmVuY2Vfa2V5OiBzdHIpIC0+IGJvb2w6CiAgICAgICAg"
    "cmV0dXJuIGFueSgKICAgICAgICAgICAgci5nZXQoInJlZmVyZW5jZV9rZXkiLCIiKS5sb3dlcigp"
    "ID09IHJlZmVyZW5jZV9rZXkubG93ZXIoKQogICAgICAgICAgICBmb3IgciBpbiByZWFkX2pzb25s"
    "KHNlbGYuX3BhdGgpCiAgICAgICAgKQoKICAgIGRlZiBzZWVkX2xzbF9ydWxlcyhzZWxmKSAtPiBO"
    "b25lOgogICAgICAgICIiIgogICAgICAgIFNlZWQgdGhlIExTTCBGb3JiaWRkZW4gUnVsZXNldCBv"
    "biBmaXJzdCBydW4gaWYgdGhlIERCIGlzIGVtcHR5LgogICAgICAgIFRoZXNlIGFyZSB0aGUgaGFy"
    "ZCBydWxlcyBmcm9tIHRoZSBwcm9qZWN0IHN0YW5kaW5nIHJ1bGVzLgogICAgICAgICIiIgogICAg"
    "ICAgIGlmIHJlYWRfanNvbmwoc2VsZi5fcGF0aCk6CiAgICAgICAgICAgIHJldHVybiAgIyBBbHJl"
    "YWR5IHNlZWRlZAoKICAgICAgICBsc2xfcnVsZXMgPSBbCiAgICAgICAgICAgICgiTFNMIiwgIkxT"
    "TCIsICJOT19URVJOQVJZIiwKICAgICAgICAgICAgICJObyB0ZXJuYXJ5IG9wZXJhdG9ycyBpbiBM"
    "U0wiLAogICAgICAgICAgICAgIk5ldmVyIHVzZSB0aGUgdGVybmFyeSBvcGVyYXRvciAoPzopIGlu"
    "IExTTCBzY3JpcHRzLiAiCiAgICAgICAgICAgICAiVXNlIGlmL2Vsc2UgYmxvY2tzIGluc3RlYWQu"
    "IExTTCBkb2VzIG5vdCBzdXBwb3J0IHRlcm5hcnkuIiwKICAgICAgICAgICAgICJSZXBsYWNlIHdp"
    "dGggaWYvZWxzZSBibG9jay4iLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19G"
    "T1JFQUNIIiwKICAgICAgICAgICAgICJObyBmb3JlYWNoIGxvb3BzIGluIExTTCIsCiAgICAgICAg"
    "ICAgICAiTFNMIGhhcyBubyBmb3JlYWNoIGxvb3AgY29uc3RydWN0LiBVc2UgaW50ZWdlciBpbmRl"
    "eCB3aXRoICIKICAgICAgICAgICAgICJsbEdldExpc3RMZW5ndGgoKSBhbmQgYSBmb3Igb3Igd2hp"
    "bGUgbG9vcC4iLAogICAgICAgICAgICAgIlVzZTogZm9yKGludGVnZXIgaT0wOyBpPGxsR2V0TGlz"
    "dExlbmd0aChteUxpc3QpOyBpKyspIiwgIiIpLAogICAgICAgICAgICAoIkxTTCIsICJMU0wiLCAi"
    "Tk9fR0xPQkFMX0FTU0lHTl9GUk9NX0ZVTkMiLAogICAgICAgICAgICAgIk5vIGdsb2JhbCB2YXJp"
    "YWJsZSBhc3NpZ25tZW50cyBmcm9tIGZ1bmN0aW9uIGNhbGxzIiwKICAgICAgICAgICAgICJHbG9i"
    "YWwgdmFyaWFibGUgaW5pdGlhbGl6YXRpb24gaW4gTFNMIGNhbm5vdCBjYWxsIGZ1bmN0aW9ucy4g"
    "IgogICAgICAgICAgICAgIkluaXRpYWxpemUgZ2xvYmFscyB3aXRoIGxpdGVyYWwgdmFsdWVzIG9u"
    "bHkuICIKICAgICAgICAgICAgICJBc3NpZ24gZnJvbSBmdW5jdGlvbnMgaW5zaWRlIGV2ZW50IGhh"
    "bmRsZXJzIG9yIG90aGVyIGZ1bmN0aW9ucy4iLAogICAgICAgICAgICAgIk1vdmUgdGhlIGFzc2ln"
    "bm1lbnQgaW50byBhbiBldmVudCBoYW5kbGVyIChzdGF0ZV9lbnRyeSwgZXRjLikiLCAiIiksCiAg"
    "ICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19WT0lEX0tFWVdPUkQiLAogICAgICAgICAgICAg"
    "Ik5vIHZvaWQga2V5d29yZCBpbiBMU0wiLAogICAgICAgICAgICAgIkxTTCBkb2VzIG5vdCBoYXZl"
    "IGEgdm9pZCBrZXl3b3JkIGZvciBmdW5jdGlvbiByZXR1cm4gdHlwZXMuICIKICAgICAgICAgICAg"
    "ICJGdW5jdGlvbnMgdGhhdCByZXR1cm4gbm90aGluZyBzaW1wbHkgb21pdCB0aGUgcmV0dXJuIHR5"
    "cGUuIiwKICAgICAgICAgICAgICJSZW1vdmUgJ3ZvaWQnIGZyb20gZnVuY3Rpb24gc2lnbmF0dXJl"
    "LiAiCiAgICAgICAgICAgICAiZS5nLiBteUZ1bmMoKSB7IC4uLiB9IG5vdCB2b2lkIG15RnVuYygp"
    "IHsgLi4uIH0iLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJDT01QTEVURV9TQ1JJ"
    "UFRTX09OTFkiLAogICAgICAgICAgICAgIkFsd2F5cyBwcm92aWRlIGNvbXBsZXRlIHNjcmlwdHMs"
    "IG5ldmVyIHBhcnRpYWwgZWRpdHMiLAogICAgICAgICAgICAgIldoZW4gd3JpdGluZyBvciBlZGl0"
    "aW5nIExTTCBzY3JpcHRzLCBhbHdheXMgb3V0cHV0IHRoZSBjb21wbGV0ZSAiCiAgICAgICAgICAg"
    "ICAic2NyaXB0LiBOZXZlciBwcm92aWRlIHBhcnRpYWwgc25pcHBldHMgb3IgJ2FkZCB0aGlzIHNl"
    "Y3Rpb24nICIKICAgICAgICAgICAgICJpbnN0cnVjdGlvbnMuIFRoZSBmdWxsIHNjcmlwdCBtdXN0"
    "IGJlIGNvcHktcGFzdGUgcmVhZHkuIiwKICAgICAgICAgICAgICJXcml0ZSB0aGUgZW50aXJlIHNj"
    "cmlwdCBmcm9tIHRvcCB0byBib3R0b20uIiwgIiIpLAogICAgICAgIF0KCiAgICAgICAgZm9yIGVu"
    "diwgbGFuZywgcmVmLCBzdW1tYXJ5LCBmdWxsX3J1bGUsIHJlc29sdXRpb24sIGxpbmsgaW4gbHNs"
    "X3J1bGVzOgogICAgICAgICAgICBzZWxmLmFkZChlbnYsIGxhbmcsIHJlZiwgc3VtbWFyeSwgZnVs"
    "bF9ydWxlLCByZXNvbHV0aW9uLCBsaW5rLAogICAgICAgICAgICAgICAgICAgICB0YWdzPVsibHNs"
    "IiwgImZvcmJpZGRlbiIsICJzdGFuZGluZ19ydWxlIl0pCgoKIyDilIDilIAgVEFTSyBNQU5BR0VS"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgApjbGFzcyBUYXNrTWFuYWdlcjoKICAgICIiIgogICAgVGFzay9yZW1pbmRl"
    "ciBDUlVEIGFuZCBkdWUtZXZlbnQgZGV0ZWN0aW9uLgoKICAgIEZpbGU6IG1lbW9yaWVzL3Rhc2tz"
    "Lmpzb25sCgogICAgVGFzayByZWNvcmQgZmllbGRzOgogICAgICAgIGlkLCBjcmVhdGVkX2F0LCBk"
    "dWVfYXQsIHByZV90cmlnZ2VyICgxbWluIGJlZm9yZSksCiAgICAgICAgdGV4dCwgc3RhdHVzIChw"
    "ZW5kaW5nfHRyaWdnZXJlZHxzbm9vemVkfGNvbXBsZXRlZHxjYW5jZWxsZWQpLAogICAgICAgIGFj"
    "a25vd2xlZGdlZF9hdCwgcmV0cnlfY291bnQsIGxhc3RfdHJpZ2dlcmVkX2F0LCBuZXh0X3JldHJ5"
    "X2F0LAogICAgICAgIHNvdXJjZSAobG9jYWx8Z29vZ2xlKSwgZ29vZ2xlX2V2ZW50X2lkLCBzeW5j"
    "X3N0YXR1cywgbWV0YWRhdGEKCiAgICBEdWUtZXZlbnQgY3ljbGU6CiAgICAgICAgLSBQcmUtdHJp"
    "Z2dlcjogMSBtaW51dGUgYmVmb3JlIGR1ZSDihpIgYW5ub3VuY2UgdXBjb21pbmcKICAgICAgICAt"
    "IER1ZSB0cmlnZ2VyOiBhdCBkdWUgdGltZSDihpIgYWxlcnQgc291bmQgKyBBSSBjb21tZW50YXJ5"
    "CiAgICAgICAgLSAzLW1pbnV0ZSB3aW5kb3c6IGlmIG5vdCBhY2tub3dsZWRnZWQg4oaSIHNub296"
    "ZQogICAgICAgIC0gMTItbWludXRlIHJldHJ5OiByZS10cmlnZ2VyCiAgICAiIiIKCiAgICBkZWYg"
    "X19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIp"
    "IC8gInRhc2tzLmpzb25sIgoKICAgICMg4pSA4pSAIENSVUQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgbG9hZF9h"
    "bGwoc2VsZikgLT4gbGlzdFtkaWN0XToKICAgICAgICB0YXNrcyA9IHJlYWRfanNvbmwoc2VsZi5f"
    "cGF0aCkKICAgICAgICBjaGFuZ2VkID0gRmFsc2UKICAgICAgICBub3JtYWxpemVkID0gW10KICAg"
    "ICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYgbm90IGlzaW5zdGFuY2UodCwgZGlj"
    "dCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiAiaWQiIG5vdCBpbiB0"
    "OgogICAgICAgICAgICAgICAgdFsiaWQiXSA9IGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBd"
    "fSIKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICMgTm9ybWFsaXpl"
    "IGZpZWxkIG5hbWVzCiAgICAgICAgICAgIGlmICJkdWVfYXQiIG5vdCBpbiB0OgogICAgICAgICAg"
    "ICAgICAgdFsiZHVlX2F0Il0gPSB0LmdldCgiZHVlIikKICAgICAgICAgICAgICAgIGNoYW5nZWQg"
    "PSBUcnVlCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3RhdHVzIiwgICAgICAgICAgICJwZW5k"
    "aW5nIikKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJyZXRyeV9jb3VudCIsICAgICAgMCkKICAg"
    "ICAgICAgICAgdC5zZXRkZWZhdWx0KCJhY2tub3dsZWRnZWRfYXQiLCAgTm9uZSkKICAgICAgICAg"
    "ICAgdC5zZXRkZWZhdWx0KCJsYXN0X3RyaWdnZXJlZF9hdCIsTm9uZSkKICAgICAgICAgICAgdC5z"
    "ZXRkZWZhdWx0KCJuZXh0X3JldHJ5X2F0IiwgICAgTm9uZSkKICAgICAgICAgICAgdC5zZXRkZWZh"
    "dWx0KCJwcmVfYW5ub3VuY2VkIiwgICAgRmFsc2UpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgi"
    "c291cmNlIiwgICAgICAgICAgICJsb2NhbCIpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiZ29v"
    "Z2xlX2V2ZW50X2lkIiwgIE5vbmUpCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgic3luY19zdGF0"
    "dXMiLCAgICAgICJwZW5kaW5nIikKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJtZXRhZGF0YSIs"
    "ICAgICAgICAge30pCiAgICAgICAgICAgIHQuc2V0ZGVmYXVsdCgiY3JlYXRlZF9hdCIsICAgICAg"
    "IGxvY2FsX25vd19pc28oKSkKCiAgICAgICAgICAgICMgQ29tcHV0ZSBwcmVfdHJpZ2dlciBpZiBt"
    "aXNzaW5nCiAgICAgICAgICAgIGlmIHQuZ2V0KCJkdWVfYXQiKSBhbmQgbm90IHQuZ2V0KCJwcmVf"
    "dHJpZ2dlciIpOgogICAgICAgICAgICAgICAgZHQgPSBwYXJzZV9pc28odFsiZHVlX2F0Il0pCiAg"
    "ICAgICAgICAgICAgICBpZiBkdDoKICAgICAgICAgICAgICAgICAgICBwcmUgPSBkdCAtIHRpbWVk"
    "ZWx0YShtaW51dGVzPTEpCiAgICAgICAgICAgICAgICAgICAgdFsicHJlX3RyaWdnZXIiXSA9IHBy"
    "ZS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgICAgIGNoYW5n"
    "ZWQgPSBUcnVlCgogICAgICAgICAgICBub3JtYWxpemVkLmFwcGVuZCh0KQoKICAgICAgICBpZiBj"
    "aGFuZ2VkOgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBub3JtYWxpemVkKQog"
    "ICAgICAgIHJldHVybiBub3JtYWxpemVkCgogICAgZGVmIHNhdmVfYWxsKHNlbGYsIHRhc2tzOiBs"
    "aXN0W2RpY3RdKSAtPiBOb25lOgogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHRhc2tz"
    "KQoKICAgIGRlZiBhZGQoc2VsZiwgdGV4dDogc3RyLCBkdWVfZHQ6IGRhdGV0aW1lLAogICAgICAg"
    "ICAgICBzb3VyY2U6IHN0ciA9ICJsb2NhbCIpIC0+IGRpY3Q6CiAgICAgICAgcHJlID0gZHVlX2R0"
    "IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkKICAgICAgICB0YXNrID0gewogICAgICAgICAgICAiaWQi"
    "OiAgICAgICAgICAgICAgIGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAg"
    "ICAgICJjcmVhdGVkX2F0IjogICAgICAgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAiZHVl"
    "X2F0IjogICAgICAgICAgIGR1ZV9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAg"
    "ICAgICAgICAgInByZV90cmlnZ2VyIjogICAgICBwcmUuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNv"
    "bmRzIiksCiAgICAgICAgICAgICJ0ZXh0IjogICAgICAgICAgICAgdGV4dC5zdHJpcCgpLAogICAg"
    "ICAgICAgICAic3RhdHVzIjogICAgICAgICAgICJwZW5kaW5nIiwKICAgICAgICAgICAgImFja25v"
    "d2xlZGdlZF9hdCI6ICBOb25lLAogICAgICAgICAgICAicmV0cnlfY291bnQiOiAgICAgIDAsCiAg"
    "ICAgICAgICAgICJsYXN0X3RyaWdnZXJlZF9hdCI6Tm9uZSwKICAgICAgICAgICAgIm5leHRfcmV0"
    "cnlfYXQiOiAgICBOb25lLAogICAgICAgICAgICAicHJlX2Fubm91bmNlZCI6ICAgIEZhbHNlLAog"
    "ICAgICAgICAgICAic291cmNlIjogICAgICAgICAgIHNvdXJjZSwKICAgICAgICAgICAgImdvb2ds"
    "ZV9ldmVudF9pZCI6ICBOb25lLAogICAgICAgICAgICAic3luY19zdGF0dXMiOiAgICAgICJwZW5k"
    "aW5nIiwKICAgICAgICAgICAgIm1ldGFkYXRhIjogICAgICAgICB7fSwKICAgICAgICB9CiAgICAg"
    "ICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICB0YXNrcy5hcHBlbmQodGFzaykKICAg"
    "ICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgIHJldHVybiB0YXNrCgogICAgZGVmIHVw"
    "ZGF0ZV9zdGF0dXMoc2VsZiwgdGFza19pZDogc3RyLCBzdGF0dXM6IHN0ciwKICAgICAgICAgICAg"
    "ICAgICAgICAgIGFja25vd2xlZGdlZDogYm9vbCA9IEZhbHNlKSAtPiBPcHRpb25hbFtkaWN0XToK"
    "ICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0IGluIHRhc2tzOgog"
    "ICAgICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAgICAgICAgdFsi"
    "c3RhdHVzIl0gPSBzdGF0dXMKICAgICAgICAgICAgICAgIGlmIGFja25vd2xlZGdlZDoKICAgICAg"
    "ICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAg"
    "ICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0"
    "CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY29tcGxldGUoc2VsZiwgdGFza19pZDogc3Ry"
    "KSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAg"
    "ICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lk"
    "OgogICAgICAgICAgICAgICAgdFsic3RhdHVzIl0gICAgICAgICAgPSAiY29tcGxldGVkIgogICAg"
    "ICAgICAgICAgICAgdFsiYWNrbm93bGVkZ2VkX2F0Il0gPSBsb2NhbF9ub3dfaXNvKCkKICAgICAg"
    "ICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAog"
    "ICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIGNhbmNlbChzZWxmLCB0YXNrX2lkOiBzdHIpIC0+"
    "IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAg"
    "Zm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09IHRhc2tfaWQ6CiAg"
    "ICAgICAgICAgICAgICB0WyJzdGF0dXMiXSAgICAgICAgICA9ICJjYW5jZWxsZWQiCiAgICAgICAg"
    "ICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAg"
    "ICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAg"
    "ICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY2xlYXJfY29tcGxldGVkKHNlbGYpIC0+IGludDoKICAg"
    "ICAgICB0YXNrcyAgICA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGtlcHQgICAgID0gW3QgZm9y"
    "IHQgaW4gdGFza3MKICAgICAgICAgICAgICAgICAgICBpZiB0LmdldCgic3RhdHVzIikgbm90IGlu"
    "IHsiY29tcGxldGVkIiwiY2FuY2VsbGVkIn1dCiAgICAgICAgcmVtb3ZlZCAgPSBsZW4odGFza3Mp"
    "IC0gbGVuKGtlcHQpCiAgICAgICAgaWYgcmVtb3ZlZDoKICAgICAgICAgICAgc2VsZi5zYXZlX2Fs"
    "bChrZXB0KQogICAgICAgIHJldHVybiByZW1vdmVkCgogICAgZGVmIHVwZGF0ZV9nb29nbGVfc3lu"
    "YyhzZWxmLCB0YXNrX2lkOiBzdHIsIHN5bmNfc3RhdHVzOiBzdHIsCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIGdvb2dsZV9ldmVudF9pZDogc3RyID0gIiIsCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGVycm9yOiBzdHIgPSAiIikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3Mg"
    "PSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYg"
    "dC5nZXQoImlkIikgPT0gdGFza19pZDoKICAgICAgICAgICAgICAgIHRbInN5bmNfc3RhdHVzIl0g"
    "ICAgPSBzeW5jX3N0YXR1cwogICAgICAgICAgICAgICAgdFsibGFzdF9zeW5jZWRfYXQiXSA9IGxv"
    "Y2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgaWYgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAg"
    "ICAgICAgICAgICAgIHRbImdvb2dsZV9ldmVudF9pZCJdID0gZ29vZ2xlX2V2ZW50X2lkCiAgICAg"
    "ICAgICAgICAgICBpZiBlcnJvcjoKICAgICAgICAgICAgICAgICAgICB0LnNldGRlZmF1bHQoIm1l"
    "dGFkYXRhIiwge30pCiAgICAgICAgICAgICAgICAgICAgdFsibWV0YWRhdGEiXVsiZ29vZ2xlX3N5"
    "bmNfZXJyb3IiXSA9IGVycm9yWzoyNDBdCiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRh"
    "c2tzKQogICAgICAgICAgICAgICAgcmV0dXJuIHQKICAgICAgICByZXR1cm4gTm9uZQoKICAgICMg"
    "4pSA4pSAIERVRSBFVkVOVCBERVRFQ1RJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgZ2V0"
    "X2R1ZV9ldmVudHMoc2VsZikgLT4gbGlzdFt0dXBsZVtzdHIsIGRpY3RdXToKICAgICAgICAiIiIK"
    "ICAgICAgICBDaGVjayBhbGwgdGFza3MgZm9yIGR1ZS9wcmUtdHJpZ2dlci9yZXRyeSBldmVudHMu"
    "CiAgICAgICAgUmV0dXJucyBsaXN0IG9mIChldmVudF90eXBlLCB0YXNrKSB0dXBsZXMuCiAgICAg"
    "ICAgZXZlbnRfdHlwZTogInByZSIgfCAiZHVlIiB8ICJyZXRyeSIKCiAgICAgICAgTW9kaWZpZXMg"
    "dGFzayBzdGF0dXNlcyBpbiBwbGFjZSBhbmQgc2F2ZXMuCiAgICAgICAgQ2FsbCBmcm9tIEFQU2No"
    "ZWR1bGVyIGV2ZXJ5IDMwIHNlY29uZHMuCiAgICAgICAgIiIiCiAgICAgICAgbm93ICAgID0gZGF0"
    "ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpCiAgICAgICAgdGFza3MgID0gc2VsZi5sb2FkX2FsbCgp"
    "CiAgICAgICAgZXZlbnRzID0gW10KICAgICAgICBjaGFuZ2VkID0gRmFsc2UKCiAgICAgICAgZm9y"
    "IHRhc2sgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHRhc2suZ2V0KCJhY2tub3dsZWRnZWRfYXQi"
    "KToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBzdGF0dXMgICA9IHRhc2su"
    "Z2V0KCJzdGF0dXMiLCAicGVuZGluZyIpCiAgICAgICAgICAgIGR1ZSAgICAgID0gc2VsZi5fcGFy"
    "c2VfbG9jYWwodGFzay5nZXQoImR1ZV9hdCIpKQogICAgICAgICAgICBwcmUgICAgICA9IHNlbGYu"
    "X3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJwcmVfdHJpZ2dlciIpKQogICAgICAgICAgICBuZXh0X3Jl"
    "dCA9IHNlbGYuX3BhcnNlX2xvY2FsKHRhc2suZ2V0KCJuZXh0X3JldHJ5X2F0IikpCiAgICAgICAg"
    "ICAgIGRlYWRsaW5lID0gc2VsZi5fcGFyc2VfbG9jYWwodGFzay5nZXQoImFsZXJ0X2RlYWRsaW5l"
    "IikpCgogICAgICAgICAgICAjIFByZS10cmlnZ2VyCiAgICAgICAgICAgIGlmIChzdGF0dXMgPT0g"
    "InBlbmRpbmciIGFuZCBwcmUgYW5kIG5vdyA+PSBwcmUKICAgICAgICAgICAgICAgICAgICBhbmQg"
    "bm90IHRhc2suZ2V0KCJwcmVfYW5ub3VuY2VkIikpOgogICAgICAgICAgICAgICAgdGFza1sicHJl"
    "X2Fubm91bmNlZCJdID0gVHJ1ZQogICAgICAgICAgICAgICAgZXZlbnRzLmFwcGVuZCgoInByZSIs"
    "IHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICAgICAgICAgICMgRHVl"
    "IHRyaWdnZXIKICAgICAgICAgICAgaWYgc3RhdHVzID09ICJwZW5kaW5nIiBhbmQgZHVlIGFuZCBu"
    "b3cgPj0gZHVlOgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0gICAgICAgICAgID0gInRy"
    "aWdnZXJlZCIKICAgICAgICAgICAgICAgIHRhc2tbImxhc3RfdHJpZ2dlcmVkX2F0Il09IGxvY2Fs"
    "X25vd19pc28oKQogICAgICAgICAgICAgICAgdGFza1siYWxlcnRfZGVhZGxpbmUiXSAgID0gKAog"
    "ICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKSArIHRpbWVkZWx0"
    "YShtaW51dGVzPTMpCiAgICAgICAgICAgICAgICApLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25k"
    "cyIpCiAgICAgICAgICAgICAgICBldmVudHMuYXBwZW5kKCgiZHVlIiwgdGFzaykpCiAgICAgICAg"
    "ICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAg"
    "ICAgICMgU25vb3plIGFmdGVyIDMtbWludXRlIHdpbmRvdwogICAgICAgICAgICBpZiBzdGF0dXMg"
    "PT0gInRyaWdnZXJlZCIgYW5kIGRlYWRsaW5lIGFuZCBub3cgPj0gZGVhZGxpbmU6CiAgICAgICAg"
    "ICAgICAgICB0YXNrWyJzdGF0dXMiXSAgICAgICAgPSAic25vb3plZCIKICAgICAgICAgICAgICAg"
    "IHRhc2tbIm5leHRfcmV0cnlfYXQiXSA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5u"
    "b3coKS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0xMikKICAgICAgICAgICAgICAg"
    "ICkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAgIGNoYW5nZWQg"
    "PSBUcnVlCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgIyBSZXRyeQogICAg"
    "ICAgICAgICBpZiBzdGF0dXMgaW4geyJyZXRyeV9wZW5kaW5nIiwic25vb3plZCJ9IGFuZCBuZXh0"
    "X3JldCBhbmQgbm93ID49IG5leHRfcmV0OgogICAgICAgICAgICAgICAgdGFza1sic3RhdHVzIl0g"
    "ICAgICAgICAgICA9ICJ0cmlnZ2VyZWQiCiAgICAgICAgICAgICAgICB0YXNrWyJyZXRyeV9jb3Vu"
    "dCJdICAgICAgID0gaW50KHRhc2suZ2V0KCJyZXRyeV9jb3VudCIsMCkpICsgMQogICAgICAgICAg"
    "ICAgICAgdGFza1sibGFzdF90cmlnZ2VyZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAg"
    "ICAgICAgICAgdGFza1siYWxlcnRfZGVhZGxpbmUiXSAgICA9ICgKICAgICAgICAgICAgICAgICAg"
    "ICBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkgKyB0aW1lZGVsdGEobWludXRlcz0zKQogICAg"
    "ICAgICAgICAgICAgKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAg"
    "ICAgdGFza1sibmV4dF9yZXRyeV9hdCJdICAgICA9IE5vbmUKICAgICAgICAgICAgICAgIGV2ZW50"
    "cy5hcHBlbmQoKCJyZXRyeSIsIHRhc2spKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUK"
    "CiAgICAgICAgaWYgY2hhbmdlZDoKICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykKICAg"
    "ICAgICByZXR1cm4gZXZlbnRzCgogICAgZGVmIF9wYXJzZV9sb2NhbChzZWxmLCB2YWx1ZTogc3Ry"
    "KSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICAgICAgIiIiUGFyc2UgSVNPIHN0cmluZyB0byB0"
    "aW1lem9uZS1hd2FyZSBkYXRldGltZSBmb3IgY29tcGFyaXNvbi4iIiIKICAgICAgICBkdCA9IHBh"
    "cnNlX2lzbyh2YWx1ZSkKICAgICAgICBpZiBkdCBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4g"
    "Tm9uZQogICAgICAgIGlmIGR0LnR6aW5mbyBpcyBOb25lOgogICAgICAgICAgICBkdCA9IGR0LmFz"
    "dGltZXpvbmUoKQogICAgICAgIHJldHVybiBkdAoKICAgICMg4pSA4pSAIE5BVFVSQUwgTEFOR1VB"
    "R0UgUEFSU0lORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBjbGFzc2lmeV9pbnRlbnQo"
    "dGV4dDogc3RyKSAtPiBkaWN0OgogICAgICAgICIiIgogICAgICAgIENsYXNzaWZ5IHVzZXIgaW5w"
    "dXQgYXMgdGFzay9yZW1pbmRlci90aW1lci9jaGF0LgogICAgICAgIFJldHVybnMgeyJpbnRlbnQi"
    "OiBzdHIsICJjbGVhbmVkX2lucHV0Ijogc3RyfQogICAgICAgICIiIgogICAgICAgIGltcG9ydCBy"
    "ZQogICAgICAgICMgU3RyaXAgY29tbW9uIGludm9jYXRpb24gcHJlZml4ZXMKICAgICAgICBjbGVh"
    "bmVkID0gcmUuc3ViKAogICAgICAgICAgICByZiJeXHMqKD86e0RFQ0tfTkFNRS5sb3dlcigpfXxo"
    "ZXlccyt7REVDS19OQU1FLmxvd2VyKCl9KVxzKiw/XHMqWzpcLV0/XHMqIiwKICAgICAgICAgICAg"
    "IiIsIHRleHQsIGZsYWdzPXJlLkkKICAgICAgICApLnN0cmlwKCkKCiAgICAgICAgbG93ID0gY2xl"
    "YW5lZC5sb3dlcigpCgogICAgICAgIHRpbWVyX3BhdHMgICAgPSBbciJcYnNldCg/OlxzK2EpP1xz"
    "K3RpbWVyXGIiLCByIlxidGltZXJccytmb3JcYiIsCiAgICAgICAgICAgICAgICAgICAgICAgICBy"
    "Ilxic3RhcnQoPzpccythKT9ccyt0aW1lclxiIl0KICAgICAgICByZW1pbmRlcl9wYXRzID0gW3Ii"
    "XGJyZW1pbmQgbWVcYiIsIHIiXGJzZXQoPzpccythKT9ccytyZW1pbmRlclxiIiwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIHIiXGJhZGQoPzpccythKT9ccytyZW1pbmRlclxiIiwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIHIiXGJzZXQoPzpccythbj8pP1xzK2FsYXJtXGIiLCByIlxiYWxhcm1c"
    "cytmb3JcYiJdCiAgICAgICAgdGFza19wYXRzICAgICA9IFtyIlxiYWRkKD86XHMrYSk/XHMrdGFz"
    "a1xiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJjcmVhdGUoPzpccythKT9ccyt0YXNr"
    "XGIiLCByIlxibmV3XHMrdGFza1xiIl0KCiAgICAgICAgaW1wb3J0IHJlIGFzIF9yZQogICAgICAg"
    "IGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gdGltZXJfcGF0cyk6CiAgICAgICAg"
    "ICAgIGludGVudCA9ICJ0aW1lciIKICAgICAgICBlbGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykg"
    "Zm9yIHAgaW4gcmVtaW5kZXJfcGF0cyk6CiAgICAgICAgICAgIGludGVudCA9ICJyZW1pbmRlciIK"
    "ICAgICAgICBlbGlmIGFueShfcmUuc2VhcmNoKHAsIGxvdykgZm9yIHAgaW4gdGFza19wYXRzKToK"
    "ICAgICAgICAgICAgaW50ZW50ID0gInRhc2siCiAgICAgICAgZWxzZToKICAgICAgICAgICAgaW50"
    "ZW50ID0gImNoYXQiCgogICAgICAgIHJldHVybiB7ImludGVudCI6IGludGVudCwgImNsZWFuZWRf"
    "aW5wdXQiOiBjbGVhbmVkfQoKICAgIEBzdGF0aWNtZXRob2QKICAgIGRlZiBwYXJzZV9kdWVfZGF0"
    "ZXRpbWUodGV4dDogc3RyKSAtPiBPcHRpb25hbFtkYXRldGltZV06CiAgICAgICAgIiIiCiAgICAg"
    "ICAgUGFyc2UgbmF0dXJhbCBsYW5ndWFnZSB0aW1lIGV4cHJlc3Npb24gZnJvbSB0YXNrIHRleHQu"
    "CiAgICAgICAgSGFuZGxlczogImluIDMwIG1pbnV0ZXMiLCAiYXQgM3BtIiwgInRvbW9ycm93IGF0"
    "IDlhbSIsCiAgICAgICAgICAgICAgICAgImluIDIgaG91cnMiLCAiYXQgMTU6MzAiLCBldGMuCiAg"
    "ICAgICAgUmV0dXJucyBhIGRhdGV0aW1lIG9yIE5vbmUgaWYgdW5wYXJzZWFibGUuCiAgICAgICAg"
    "IiIiCiAgICAgICAgaW1wb3J0IHJlCiAgICAgICAgbm93ICA9IGRhdGV0aW1lLm5vdygpCiAgICAg"
    "ICAgbG93ICA9IHRleHQubG93ZXIoKS5zdHJpcCgpCgogICAgICAgICMgImluIFggbWludXRlcy9o"
    "b3Vycy9kYXlzIgogICAgICAgIG0gPSByZS5zZWFyY2goCiAgICAgICAgICAgIHIiaW5ccysoXGQr"
    "KVxzKihtaW51dGV8bWlufGhvdXJ8aHJ8ZGF5fHNlY29uZHxzZWMpIiwKICAgICAgICAgICAgbG93"
    "CiAgICAgICAgKQogICAgICAgIGlmIG06CiAgICAgICAgICAgIG4gICAgPSBpbnQobS5ncm91cCgx"
    "KSkKICAgICAgICAgICAgdW5pdCA9IG0uZ3JvdXAoMikKICAgICAgICAgICAgaWYgIm1pbiIgaW4g"
    "dW5pdDogIHJldHVybiBub3cgKyB0aW1lZGVsdGEobWludXRlcz1uKQogICAgICAgICAgICBpZiAi"
    "aG91ciIgaW4gdW5pdCBvciAiaHIiIGluIHVuaXQ6IHJldHVybiBub3cgKyB0aW1lZGVsdGEoaG91"
    "cnM9bikKICAgICAgICAgICAgaWYgImRheSIgIGluIHVuaXQ6IHJldHVybiBub3cgKyB0aW1lZGVs"
    "dGEoZGF5cz1uKQogICAgICAgICAgICBpZiAic2VjIiAgaW4gdW5pdDogcmV0dXJuIG5vdyArIHRp"
    "bWVkZWx0YShzZWNvbmRzPW4pCgogICAgICAgICMgImF0IEhIOk1NIiBvciAiYXQgSDpNTWFtL3Bt"
    "IgogICAgICAgIG0gPSByZS5zZWFyY2goCiAgICAgICAgICAgIHIiYXRccysoXGR7MSwyfSkoPzo6"
    "KFxkezJ9KSk/XHMqKGFtfHBtKT8iLAogICAgICAgICAgICBsb3cKICAgICAgICApCiAgICAgICAg"
    "aWYgbToKICAgICAgICAgICAgaHIgID0gaW50KG0uZ3JvdXAoMSkpCiAgICAgICAgICAgIG1uICA9"
    "IGludChtLmdyb3VwKDIpKSBpZiBtLmdyb3VwKDIpIGVsc2UgMAogICAgICAgICAgICBhcG0gPSBt"
    "Lmdyb3VwKDMpCiAgICAgICAgICAgIGlmIGFwbSA9PSAicG0iIGFuZCBociA8IDEyOiBociArPSAx"
    "MgogICAgICAgICAgICBpZiBhcG0gPT0gImFtIiBhbmQgaHIgPT0gMTI6IGhyID0gMAogICAgICAg"
    "ICAgICBkdCA9IG5vdy5yZXBsYWNlKGhvdXI9aHIsIG1pbnV0ZT1tbiwgc2Vjb25kPTAsIG1pY3Jv"
    "c2Vjb25kPTApCiAgICAgICAgICAgIGlmIGR0IDw9IG5vdzoKICAgICAgICAgICAgICAgIGR0ICs9"
    "IHRpbWVkZWx0YShkYXlzPTEpCiAgICAgICAgICAgIHJldHVybiBkdAoKICAgICAgICAjICJ0b21v"
    "cnJvdyBhdCAuLi4iICAocmVjdXJzZSBvbiB0aGUgImF0IiBwYXJ0KQogICAgICAgIGlmICJ0b21v"
    "cnJvdyIgaW4gbG93OgogICAgICAgICAgICB0b21vcnJvd190ZXh0ID0gcmUuc3ViKHIidG9tb3Jy"
    "b3ciLCAiIiwgbG93KS5zdHJpcCgpCiAgICAgICAgICAgIHJlc3VsdCA9IFRhc2tNYW5hZ2VyLnBh"
    "cnNlX2R1ZV9kYXRldGltZSh0b21vcnJvd190ZXh0KQogICAgICAgICAgICBpZiByZXN1bHQ6CiAg"
    "ICAgICAgICAgICAgICByZXR1cm4gcmVzdWx0ICsgdGltZWRlbHRhKGRheXM9MSkKCiAgICAgICAg"
    "cmV0dXJuIE5vbmUKCgojIOKUgOKUgCBSRVFVSVJFTUVOVFMuVFhUIEdFTkVSQVRPUiDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKZGVmIHdyaXRlX3JlcXVpcmVtZW50c190eHQoKSAtPiBO"
    "b25lOgogICAgIiIiCiAgICBXcml0ZSByZXF1aXJlbWVudHMudHh0IG5leHQgdG8gdGhlIGRlY2sg"
    "ZmlsZSBvbiBmaXJzdCBydW4uCiAgICBIZWxwcyB1c2VycyBpbnN0YWxsIGFsbCBkZXBlbmRlbmNp"
    "ZXMgd2l0aCBvbmUgcGlwIGNvbW1hbmQuCiAgICAiIiIKICAgIHJlcV9wYXRoID0gUGF0aChDRkcu"
    "Z2V0KCJiYXNlX2RpciIsIHN0cihTQ1JJUFRfRElSKSkpIC8gInJlcXVpcmVtZW50cy50eHQiCiAg"
    "ICBpZiByZXFfcGF0aC5leGlzdHMoKToKICAgICAgICByZXR1cm4KCiAgICBjb250ZW50ID0gIiIi"
    "XAojIE1vcmdhbm5hIERlY2sg4oCUIFJlcXVpcmVkIERlcGVuZGVuY2llcwojIEluc3RhbGwgYWxs"
    "IHdpdGg6IHBpcCBpbnN0YWxsIC1yIHJlcXVpcmVtZW50cy50eHQKCiMgQ29yZSBVSQpQeVNpZGU2"
    "CgojIFNjaGVkdWxpbmcgKGlkbGUgdGltZXIsIGF1dG9zYXZlLCByZWZsZWN0aW9uIGN5Y2xlcykK"
    "YXBzY2hlZHVsZXIKCiMgTG9nZ2luZwpsb2d1cnUKCiMgU291bmQgcGxheWJhY2sgKFdBViArIE1Q"
    "MykKcHlnYW1lCgojIERlc2t0b3Agc2hvcnRjdXQgY3JlYXRpb24gKFdpbmRvd3Mgb25seSkKcHl3"
    "aW4zMgoKIyBTeXN0ZW0gbW9uaXRvcmluZyAoQ1BVLCBSQU0sIGRyaXZlcywgbmV0d29yaykKcHN1"
    "dGlsCgojIEhUVFAgcmVxdWVzdHMKcmVxdWVzdHMKCiMgR29vZ2xlIGludGVncmF0aW9uIChDYWxl"
    "bmRhciwgRHJpdmUsIERvY3MsIEdtYWlsKQpnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQKZ29vZ2xl"
    "LWF1dGgtb2F1dGhsaWIKZ29vZ2xlLWF1dGgKCiMg4pSA4pSAIE9wdGlvbmFsIChsb2NhbCBtb2Rl"
    "bCBvbmx5KSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBVbmNvbW1lbnQgaWYgdXNpbmcgYSBs"
    "b2NhbCBIdWdnaW5nRmFjZSBtb2RlbDoKIyB0b3JjaAojIHRyYW5zZm9ybWVycwojIGFjY2VsZXJh"
    "dGUKCiMg4pSA4pSAIE9wdGlvbmFsIChOVklESUEgR1BVIG1vbml0b3JpbmcpIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFVu"
    "Y29tbWVudCBpZiB5b3UgaGF2ZSBhbiBOVklESUEgR1BVOgojIHB5bnZtbAoiIiIKICAgIHJlcV9w"
    "YXRoLndyaXRlX3RleHQoY29udGVudCwgZW5jb2Rpbmc9InV0Zi04IikKCgojIOKUgOKUgCBQQVNT"
    "IDQgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiMgTWVtb3J5LCBTZXNzaW9uLCBMZXNzb25zTGVhcm5lZCwgVGFz"
    "a01hbmFnZXIgYWxsIGRlZmluZWQuCiMgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGF1dG8tc2VlZGVk"
    "IG9uIGZpcnN0IHJ1bi4KIyByZXF1aXJlbWVudHMudHh0IHdyaXR0ZW4gb24gZmlyc3QgcnVuLgoj"
    "CiMgTmV4dDogUGFzcyA1IOKAlCBUYWIgQ29udGVudCBDbGFzc2VzCiMgKFNMU2NhbnNUYWIsIFNM"
    "Q29tbWFuZHNUYWIsIEpvYlRyYWNrZXJUYWIsIFJlY29yZHNUYWIsCiMgIFRhc2tzVGFiLCBTZWxm"
    "VGFiLCBEaWFnbm9zdGljc1RhYikKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBB"
    "U1MgNTogVEFCIENPTlRFTlQgQ0xBU1NFUwojCiMgVGFicyBkZWZpbmVkIGhlcmU6CiMgICBTTFNj"
    "YW5zVGFiICAgICAg4oCUIGdyaW1vaXJlLWNhcmQgc3R5bGUsIHJlYnVpbHQgKERlbGV0ZSBhZGRl"
    "ZCwgTW9kaWZ5IGZpeGVkLAojICAgICAgICAgICAgICAgICAgICAgcGFyc2VyIGZpeGVkLCBjb3B5"
    "LXRvLWNsaXBib2FyZCBwZXIgaXRlbSkKIyAgIFNMQ29tbWFuZHNUYWIgICDigJQgZ290aGljIHRh"
    "YmxlLCBjb3B5IGNvbW1hbmQgdG8gY2xpcGJvYXJkCiMgICBKb2JUcmFja2VyVGFiICAg4oCUIGZ1"
    "bGwgcmVidWlsZCBmcm9tIHNwZWMsIENTVi9UU1YgZXhwb3J0CiMgICBSZWNvcmRzVGFiICAgICAg"
    "4oCUIEdvb2dsZSBEcml2ZS9Eb2NzIHdvcmtzcGFjZQojICAgVGFza3NUYWIgICAgICAgIOKAlCB0"
    "YXNrIHJlZ2lzdHJ5ICsgbWluaSBjYWxlbmRhcgojICAgU2VsZlRhYiAgICAgICAgIOKAlCBpZGxl"
    "IG5hcnJhdGl2ZSBvdXRwdXQgKyBQb0kgbGlzdAojICAgRGlhZ25vc3RpY3NUYWIgIOKAlCBsb2d1"
    "cnUgb3V0cHV0ICsgaGFyZHdhcmUgcmVwb3J0ICsgam91cm5hbCBsb2FkIG5vdGljZXMKIyAgIExl"
    "c3NvbnNUYWIgICAgICDigJQgTFNMIEZvcmJpZGRlbiBSdWxlc2V0ICsgY29kZSBsZXNzb25zIGJy"
    "b3dzZXIKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZAKCmltcG9ydCByZSBhcyBfcmUKCgojIOKUgOKUgCBTSEFSRUQgR09U"
    "SElDIFRBQkxFIFNUWUxFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgX2dv"
    "dGhpY190YWJsZV9zdHlsZSgpIC0+IHN0cjoKICAgIHJldHVybiBmIiIiCiAgICAgICAgUVRhYmxl"
    "V2lkZ2V0IHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0JHMn07CiAgICAgICAgICAgIGNv"
    "bG9yOiB7Q19HT0xEfTsKICAgICAgICAgICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9E"
    "SU19OwogICAgICAgICAgICBncmlkbGluZS1jb2xvcjoge0NfQk9SREVSfTsKICAgICAgICAgICAg"
    "Zm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsKICAgICAgICAgICAgZm9udC1zaXplOiAx"
    "MXB4OwogICAgICAgIH19CiAgICAgICAgUVRhYmxlV2lkZ2V0OjppdGVtOnNlbGVjdGVkIHt7CiAg"
    "ICAgICAgICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgICAgICAgICAgY29sb3I6"
    "IHtDX0dPTERfQlJJR0hUfTsKICAgICAgICB9fQogICAgICAgIFFUYWJsZVdpZGdldDo6aXRlbTph"
    "bHRlcm5hdGUge3sKICAgICAgICAgICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgICAgICB9fQog"
    "ICAgICAgIFFIZWFkZXJWaWV3OjpzZWN0aW9uIHt7CiAgICAgICAgICAgIGJhY2tncm91bmQ6IHtD"
    "X0JHM307CiAgICAgICAgICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgICAgICAgICAgYm9yZGVyOiAx"
    "cHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgICAgICAgICBwYWRkaW5nOiA0cHggNnB4Owog"
    "ICAgICAgICAgICBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOwogICAgICAgICAgICBm"
    "b250LXNpemU6IDEwcHg7CiAgICAgICAgICAgIGZvbnQtd2VpZ2h0OiBib2xkOwogICAgICAgICAg"
    "ICBsZXR0ZXItc3BhY2luZzogMXB4OwogICAgICAgIH19CiAgICAiIiIKCmRlZiBfZ290aGljX2J0"
    "bih0ZXh0OiBzdHIsIHRvb2x0aXA6IHN0ciA9ICIiKSAtPiBRUHVzaEJ1dHRvbjoKICAgIGJ0biA9"
    "IFFQdXNoQnV0dG9uKHRleHQpCiAgICBidG4uc2V0U3R5bGVTaGVldCgKICAgICAgICBmImJhY2tn"
    "cm91bmQ6IHtDX0NSSU1TT05fRElNfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgZiJib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAg"
    "ZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7ICIKICAg"
    "ICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiA0cHggMTBweDsgbGV0dGVyLXNwYWNp"
    "bmc6IDFweDsiCiAgICApCiAgICBpZiB0b29sdGlwOgogICAgICAgIGJ0bi5zZXRUb29sVGlwKHRv"
    "b2x0aXApCiAgICByZXR1cm4gYnRuCgpkZWYgX3NlY3Rpb25fbGJsKHRleHQ6IHN0cikgLT4gUUxh"
    "YmVsOgogICAgbGJsID0gUUxhYmVsKHRleHQpCiAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAi"
    "CiAgICAgICAgZiJsZXR0ZXItc3BhY2luZzogMnB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0s"
    "IHNlcmlmOyIKICAgICkKICAgIHJldHVybiBsYmwKCgojIOKUgOKUgCBTTCBTQ0FOUyBUQUIg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACmNsYXNzIFNMU2NhbnNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFNlY29u"
    "ZCBMaWZlIGF2YXRhciBzY2FubmVyIHJlc3VsdHMgbWFuYWdlci4KICAgIFJlYnVpbHQgZnJvbSBz"
    "cGVjOgogICAgICAtIENhcmQvZ3JpbW9pcmUtZW50cnkgc3R5bGUgZGlzcGxheQogICAgICAtIEFk"
    "ZCAod2l0aCB0aW1lc3RhbXAtYXdhcmUgcGFyc2VyKQogICAgICAtIERpc3BsYXkgKGNsZWFuIGl0"
    "ZW0vY3JlYXRvciB0YWJsZSkKICAgICAgLSBNb2RpZnkgKGVkaXQgbmFtZSwgZGVzY3JpcHRpb24s"
    "IGluZGl2aWR1YWwgaXRlbXMpCiAgICAgIC0gRGVsZXRlICh3YXMgbWlzc2luZyDigJQgbm93IHBy"
    "ZXNlbnQpCiAgICAgIC0gUmUtcGFyc2UgKHdhcyAnUmVmcmVzaCcg4oCUIHJlLXJ1bnMgcGFyc2Vy"
    "IG9uIHN0b3JlZCByYXcgdGV4dCkKICAgICAgLSBDb3B5LXRvLWNsaXBib2FyZCBvbiBhbnkgaXRl"
    "bQogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIG1lbW9yeV9kaXI6IFBhdGgsIHBhcmVu"
    "dD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9w"
    "YXRoICAgID0gY2ZnX3BhdGgoInNsIikgLyAic2xfc2NhbnMuanNvbmwiCiAgICAgICAgc2VsZi5f"
    "cmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQ6IE9wdGlv"
    "bmFsW3N0cl0gPSBOb25lCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVm"
    "cmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBR"
    "VkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQs"
    "IDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgQnV0dG9uIGJhcgogICAg"
    "ICAgIGJhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAgICA9IF9nb3Ro"
    "aWNfYnRuKCLinKYgQWRkIiwgICAgICJBZGQgYSBuZXcgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRu"
    "X2Rpc3BsYXkgPSBfZ290aGljX2J0bigi4p2nIERpc3BsYXkiLCAiU2hvdyBzZWxlY3RlZCBzY2Fu"
    "IGRldGFpbHMiKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkgID0gX2dvdGhpY19idG4oIuKcpyBN"
    "b2RpZnkiLCAgIkVkaXQgc2VsZWN0ZWQgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSAg"
    "PSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIsICAiRGVsZXRlIHNlbGVjdGVkIHNjYW4iKQogICAg"
    "ICAgIHNlbGYuX2J0bl9yZXBhcnNlID0gX2dvdGhpY19idG4oIuKGuyBSZS1wYXJzZSIsIlJlLXBh"
    "cnNlIHJhdyB0ZXh0IG9mIHNlbGVjdGVkIHNjYW4iKQogICAgICAgIHNlbGYuX2J0bl9hZGQuY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX3Nob3dfYWRkKQogICAgICAgIHNlbGYuX2J0bl9kaXNwbGF5LmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl9zaG93X2Rpc3BsYXkpCiAgICAgICAgc2VsZi5fYnRuX21vZGlm"
    "eS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2hvd19tb2RpZnkpCiAgICAgICAgc2VsZi5fYnRuX2Rl"
    "bGV0ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl9y"
    "ZXBhcnNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19yZXBhcnNlKQogICAgICAgIGZvciBiIGlu"
    "IChzZWxmLl9idG5fYWRkLCBzZWxmLl9idG5fZGlzcGxheSwgc2VsZi5fYnRuX21vZGlmeSwKICAg"
    "ICAgICAgICAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSwgc2VsZi5fYnRuX3JlcGFyc2UpOgogICAg"
    "ICAgICAgICBiYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQogICAgICAg"
    "IHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAgICAgIyBTdGFjazogbGlzdCB2aWV3IHwgYWRkIGZv"
    "cm0gfCBkaXNwbGF5IHwgbW9kaWZ5CiAgICAgICAgc2VsZi5fc3RhY2sgPSBRU3RhY2tlZFdpZGdl"
    "dCgpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fc3RhY2ssIDEpCgogICAgICAgICMg4pSA"
    "4pSAIFBBR0UgMDogc2NhbiBsaXN0IChncmltb2lyZSBjYXJkcykg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgcDAgPSBRV2lkZ2V0KCkKICAgICAgICBsMCA9IFFWQm94TGF5b3V0KHAwKQogICAgICAg"
    "IGwwLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlbGYuX2NhcmRfc2Ny"
    "b2xsID0gUVNjcm9sbEFyZWEoKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFdpZGdldFJl"
    "c2l6YWJsZShUcnVlKQogICAgICAgIHNlbGYuX2NhcmRfc2Nyb2xsLnNldFN0eWxlU2hlZXQoZiJi"
    "YWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IG5vbmU7IikKICAgICAgICBzZWxmLl9jYXJkX2Nv"
    "bnRhaW5lciA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0ICAgID0gUVZCb3hM"
    "YXlvdXQoc2VsZi5fY2FyZF9jb250YWluZXIpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuc2V0"
    "Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuc2V0"
    "U3BhY2luZyg0KQogICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LmFkZFN0cmV0Y2goKQogICAgICAg"
    "IHNlbGYuX2NhcmRfc2Nyb2xsLnNldFdpZGdldChzZWxmLl9jYXJkX2NvbnRhaW5lcikKICAgICAg"
    "ICBsMC5hZGRXaWRnZXQoc2VsZi5fY2FyZF9zY3JvbGwpCiAgICAgICAgc2VsZi5fc3RhY2suYWRk"
    "V2lkZ2V0KHAwKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDE6IGFkZCBmb3JtIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgICAgIHAxID0gUVdpZGdldCgpCiAgICAgICAgbDEgPSBRVkJveExheW91dChwMSkKICAg"
    "ICAgICBsMS5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBsMS5zZXRTcGFj"
    "aW5nKDQpCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFNDQU4gTkFNRSAo"
    "YXV0by1kZXRlY3RlZCkiKSkKICAgICAgICBzZWxmLl9hZGRfbmFtZSAgPSBRTGluZUVkaXQoKQog"
    "ICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiQXV0by1kZXRlY3RlZCBm"
    "cm9tIHNjYW4gdGV4dCIpCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNlbGYuX2FkZF9uYW1lKQogICAg"
    "ICAgIGwxLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBERVNDUklQVElPTiIpKQogICAgICAg"
    "IHNlbGYuX2FkZF9kZXNjICA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fYWRkX2Rlc2Muc2V0"
    "TWF4aW11bUhlaWdodCg2MCkKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX2Rlc2MpCiAg"
    "ICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFJBVyBTQ0FOIFRFWFQgKHBhc3Rl"
    "IGhlcmUpIikpCiAgICAgICAgc2VsZi5fYWRkX3JhdyAgID0gUVRleHRFZGl0KCkKICAgICAgICBz"
    "ZWxmLl9hZGRfcmF3LnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAgICAgIlBhc3RlIHRoZSBy"
    "YXcgU2Vjb25kIExpZmUgc2NhbiBvdXRwdXQgaGVyZS5cbiIKICAgICAgICAgICAgIlRpbWVzdGFt"
    "cHMgbGlrZSBbMTE6NDddIHdpbGwgYmUgdXNlZCB0byBzcGxpdCBpdGVtcyBjb3JyZWN0bHkuIgog"
    "ICAgICAgICkKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX3JhdywgMSkKICAgICAgICAj"
    "IFByZXZpZXcgb2YgcGFyc2VkIGl0ZW1zCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xi"
    "bCgi4p2nIFBBUlNFRCBJVEVNUyBQUkVWSUVXIikpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcg"
    "PSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRIb3Jpem9u"
    "dGFsSGVhZGVyTGFiZWxzKFsiSXRlbSIsICJDcmVhdG9yIl0pCiAgICAgICAgc2VsZi5fYWRkX3By"
    "ZXZpZXcuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAg"
    "ICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fYWRkX3By"
    "ZXZpZXcuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAg"
    "ICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fYWRkX3By"
    "ZXZpZXcuc2V0TWF4aW11bUhlaWdodCgxMjApCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0"
    "U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgbDEuYWRkV2lkZ2V0KHNl"
    "bGYuX2FkZF9wcmV2aWV3KQogICAgICAgIHNlbGYuX2FkZF9yYXcudGV4dENoYW5nZWQuY29ubmVj"
    "dChzZWxmLl9wcmV2aWV3X3BhcnNlKQoKICAgICAgICBidG5zMSA9IFFIQm94TGF5b3V0KCkKICAg"
    "ICAgICBzMSA9IF9nb3RoaWNfYnRuKCLinKYgU2F2ZSIpOyBjMSA9IF9nb3RoaWNfYnRuKCLinJcg"
    "Q2FuY2VsIikKICAgICAgICBzMS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAg"
    "IGMxLmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgw"
    "KSkKICAgICAgICBidG5zMS5hZGRXaWRnZXQoczEpOyBidG5zMS5hZGRXaWRnZXQoYzEpOyBidG5z"
    "MS5hZGRTdHJldGNoKCkKICAgICAgICBsMS5hZGRMYXlvdXQoYnRuczEpCiAgICAgICAgc2VsZi5f"
    "c3RhY2suYWRkV2lkZ2V0KHAxKQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDI6IGRpc3BsYXkg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICAgICAgcDIgPSBRV2lkZ2V0KCkKICAgICAgICBsMiA9IFFWQm94TGF5"
    "b3V0KHAyKQogICAgICAgIGwyLnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAg"
    "IHNlbGYuX2Rpc3BfbmFtZSAgPSBRTGFiZWwoKQogICAgICAgIHNlbGYuX2Rpc3BfbmFtZS5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEX0JSSUdIVH07IGZvbnQtc2l6"
    "ZTogMTNweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseTog"
    "e0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjICA9"
    "IFFMYWJlbCgpCiAgICAgICAgc2VsZi5fZGlzcF9kZXNjLnNldFdvcmRXcmFwKFRydWUpCiAgICAg"
    "ICAgc2VsZi5fZGlzcF9kZXNjLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtD"
    "X1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNl"
    "cmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZSA9IFFUYWJsZVdpZGdldCgw"
    "LCAyKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhb"
    "Ikl0ZW0iLCAiQ3JlYXRvciJdKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuaG9yaXpvbnRhbEhl"
    "YWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5S"
    "ZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5ob3Jpem9udGFsSGVh"
    "ZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJWaWV3LlJl"
    "c2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldFN0eWxlU2hlZXQo"
    "X2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0Q29udGV4"
    "dE1lbnVQb2xpY3koCiAgICAgICAgICAgIFF0LkNvbnRleHRNZW51UG9saWN5LkN1c3RvbUNvbnRl"
    "eHRNZW51KQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuY3VzdG9tQ29udGV4dE1lbnVSZXF1ZXN0"
    "ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5faXRlbV9jb250ZXh0X21lbnUpCgogICAgICAg"
    "IGwyLmFkZFdpZGdldChzZWxmLl9kaXNwX25hbWUpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYu"
    "X2Rpc3BfZGVzYykKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fZGlzcF90YWJsZSwgMSkKCiAg"
    "ICAgICAgY29weV9oaW50ID0gUUxhYmVsKCJSaWdodC1jbGljayBhbnkgaXRlbSB0byBjb3B5IGl0"
    "IHRvIGNsaXBib2FyZC4iKQogICAgICAgIGNvcHlfaGludC5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseTog"
    "e0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgbDIuYWRkV2lkZ2V0KGNvcHlf"
    "aGludCkKCiAgICAgICAgYmsyID0gX2dvdGhpY19idG4oIuKXgCBCYWNrIikKICAgICAgICBiazIu"
    "Y2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDApKQog"
    "ICAgICAgIGwyLmFkZFdpZGdldChiazIpCiAgICAgICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAy"
    "KQoKICAgICAgICAjIOKUgOKUgCBQQUdFIDM6IG1vZGlmeSDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICBwMyA9IFFXaWRnZXQoKQogICAgICAgIGwzID0gUVZCb3hMYXlvdXQocDMpCiAgICAgICAg"
    "bDMuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgbDMuc2V0U3BhY2luZyg0"
    "KQogICAgICAgIGwzLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBOQU1FIikpCiAgICAgICAg"
    "c2VsZi5fbW9kX25hbWUgPSBRTGluZUVkaXQoKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9t"
    "b2RfbmFtZSkKICAgICAgICBsMy5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgREVTQ1JJUFRJ"
    "T04iKSkKICAgICAgICBzZWxmLl9tb2RfZGVzYyA9IFFMaW5lRWRpdCgpCiAgICAgICAgbDMuYWRk"
    "V2lkZ2V0KHNlbGYuX21vZF9kZXNjKQogICAgICAgIGwzLmFkZFdpZGdldChfc2VjdGlvbl9sYmwo"
    "IuKdpyBJVEVNUyAoZG91YmxlLWNsaWNrIHRvIGVkaXQpIikpCiAgICAgICAgc2VsZi5fbW9kX3Rh"
    "YmxlID0gUVRhYmxlV2lkZ2V0KDAsIDIpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldEhvcml6"
    "b250YWxIZWFkZXJMYWJlbHMoWyJJdGVtIiwgIkNyZWF0b3IiXSkKICAgICAgICBzZWxmLl9tb2Rf"
    "dGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAg"
    "ICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fbW9kX3Rh"
    "YmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAgICAgICAgICAg"
    "MSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX21vZF90YWJs"
    "ZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBsMy5hZGRXaWRn"
    "ZXQoc2VsZi5fbW9kX3RhYmxlLCAxKQoKICAgICAgICBidG5zMyA9IFFIQm94TGF5b3V0KCkKICAg"
    "ICAgICBzMyA9IF9nb3RoaWNfYnRuKCLinKYgU2F2ZSIpOyBjMyA9IF9nb3RoaWNfYnRuKCLinJcg"
    "Q2FuY2VsIikKICAgICAgICBzMy5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5X3NhdmUp"
    "CiAgICAgICAgYzMuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fc3RhY2suc2V0Q3VycmVu"
    "dEluZGV4KDApKQogICAgICAgIGJ0bnMzLmFkZFdpZGdldChzMyk7IGJ0bnMzLmFkZFdpZGdldChj"
    "Myk7IGJ0bnMzLmFkZFN0cmV0Y2goKQogICAgICAgIGwzLmFkZExheW91dChidG5zMykKICAgICAg"
    "ICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDMpCgogICAgIyDilIDilIAgUEFSU0VSIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgQHN0YXRp"
    "Y21ldGhvZAogICAgZGVmIHBhcnNlX3NjYW5fdGV4dChyYXc6IHN0cikgLT4gdHVwbGVbc3RyLCBs"
    "aXN0W2RpY3RdXToKICAgICAgICAiIiIKICAgICAgICBQYXJzZSByYXcgU0wgc2NhbiBvdXRwdXQg"
    "aW50byAoYXZhdGFyX25hbWUsIGl0ZW1zKS4KCiAgICAgICAgS0VZIEZJWDogQmVmb3JlIHNwbGl0"
    "dGluZywgaW5zZXJ0IG5ld2xpbmVzIGJlZm9yZSBldmVyeSBbSEg6TU1dCiAgICAgICAgdGltZXN0"
    "YW1wIHNvIHNpbmdsZS1saW5lIHBhc3RlcyB3b3JrIGNvcnJlY3RseS4KCiAgICAgICAgRXhwZWN0"
    "ZWQgZm9ybWF0OgogICAgICAgICAgICBbMTE6NDddIEF2YXRhck5hbWUncyBwdWJsaWMgYXR0YWNo"
    "bWVudHM6CiAgICAgICAgICAgIFsxMTo0N10gLjogSXRlbSBOYW1lIFtBdHRhY2htZW50XSBDUkVB"
    "VE9SOiBDcmVhdG9yTmFtZSBbMTE6NDddIC4uLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBy"
    "YXcuc3RyaXAoKToKICAgICAgICAgICAgcmV0dXJuICJVTktOT1dOIiwgW10KCiAgICAgICAgIyDi"
    "lIDilIAgU3RlcCAxOiBub3JtYWxpemUg4oCUIGluc2VydCBuZXdsaW5lcyBiZWZvcmUgdGltZXN0"
    "YW1wcyDilIDilIDilIDilIDilIDilIAKICAgICAgICBub3JtYWxpemVkID0gX3JlLnN1YihyJ1xz"
    "KihcW1xkezEsMn06XGR7Mn1cXSknLCByJ1xuXDEnLCByYXcpCiAgICAgICAgbGluZXMgPSBbbC5z"
    "dHJpcCgpIGZvciBsIGluIG5vcm1hbGl6ZWQuc3BsaXRsaW5lcygpIGlmIGwuc3RyaXAoKV0KCiAg"
    "ICAgICAgIyDilIDilIAgU3RlcCAyOiBleHRyYWN0IGF2YXRhciBuYW1lIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGF2YXRhcl9uYW1lID0gIlVOS05PV04i"
    "CiAgICAgICAgZm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAgICAgICMgIkF2YXRhck5hbWUncyBw"
    "dWJsaWMgYXR0YWNobWVudHMiIG9yIHNpbWlsYXIKICAgICAgICAgICAgbSA9IF9yZS5zZWFyY2go"
    "CiAgICAgICAgICAgICAgICByIihcd1tcd1xzXSs/KSdzXHMrcHVibGljXHMrYXR0YWNobWVudHMi"
    "LAogICAgICAgICAgICAgICAgbGluZSwgX3JlLkkKICAgICAgICAgICAgKQogICAgICAgICAgICBp"
    "ZiBtOgogICAgICAgICAgICAgICAgYXZhdGFyX25hbWUgPSBtLmdyb3VwKDEpLnN0cmlwKCkKICAg"
    "ICAgICAgICAgICAgIGJyZWFrCgogICAgICAgICMg4pSA4pSAIFN0ZXAgMzogZXh0cmFjdCBpdGVt"
    "cyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICBpdGVtcyA9IFtdCiAgICAgICAgZm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAg"
    "ICAgICMgU3RyaXAgbGVhZGluZyB0aW1lc3RhbXAKICAgICAgICAgICAgY29udGVudCA9IF9yZS5z"
    "dWIocideXFtcZHsxLDJ9OlxkezJ9XF1ccyonLCAnJywgbGluZSkuc3RyaXAoKQogICAgICAgICAg"
    "ICBpZiBub3QgY29udGVudDoKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICMg"
    "U2tpcCBoZWFkZXIgbGluZXMKICAgICAgICAgICAgaWYgIidzIHB1YmxpYyBhdHRhY2htZW50cyIg"
    "aW4gY29udGVudC5sb3dlcigpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAg"
    "aWYgY29udGVudC5sb3dlcigpLnN0YXJ0c3dpdGgoIm9iamVjdCIpOgogICAgICAgICAgICAgICAg"
    "Y29udGludWUKICAgICAgICAgICAgIyBTa2lwIGRpdmlkZXIgbGluZXMg4oCUIGxpbmVzIHRoYXQg"
    "YXJlIG1vc3RseSBvbmUgcmVwZWF0ZWQgY2hhcmFjdGVyCiAgICAgICAgICAgICMgZS5nLiDiloLi"
    "loLiloLiloLiloLiloLiloLiloLiloLiloLiloLiloIgb3Ig4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQIG9yIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgICAgICAgICBzdHJpcHBlZCA9IGNvbnRlbnQuc3RyaXAoIi46ICIpCiAgICAgICAgICAgIGlm"
    "IHN0cmlwcGVkIGFuZCBsZW4oc2V0KHN0cmlwcGVkKSkgPD0gMjoKICAgICAgICAgICAgICAgIGNv"
    "bnRpbnVlICAjIG9uZSBvciB0d28gdW5pcXVlIGNoYXJzID0gZGl2aWRlciBsaW5lCgogICAgICAg"
    "ICAgICAjIFRyeSB0byBleHRyYWN0IENSRUFUT1I6IGZpZWxkCiAgICAgICAgICAgIGNyZWF0b3Ig"
    "PSAiVU5LTk9XTiIKICAgICAgICAgICAgaXRlbV9uYW1lID0gY29udGVudAoKICAgICAgICAgICAg"
    "Y3JlYXRvcl9tYXRjaCA9IF9yZS5zZWFyY2goCiAgICAgICAgICAgICAgICByJ0NSRUFUT1I6XHMq"
    "KFtcd1xzXSs/KSg/OlxzKlxbfCQpJywgY29udGVudCwgX3JlLkkKICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICBpZiBjcmVhdG9yX21hdGNoOgogICAgICAgICAgICAgICAgY3JlYXRvciAgID0gY3Jl"
    "YXRvcl9tYXRjaC5ncm91cCgxKS5zdHJpcCgpCiAgICAgICAgICAgICAgICBpdGVtX25hbWUgPSBj"
    "b250ZW50WzpjcmVhdG9yX21hdGNoLnN0YXJ0KCldLnN0cmlwKCkKCiAgICAgICAgICAgICMgU3Ry"
    "aXAgYXR0YWNobWVudCBwb2ludCBzdWZmaXhlcyBsaWtlIFtMZWZ0X0Zvb3RdCiAgICAgICAgICAg"
    "IGl0ZW1fbmFtZSA9IF9yZS5zdWIocidccypcW1tcd1xzX10rXF0nLCAnJywgaXRlbV9uYW1lKS5z"
    "dHJpcCgpCiAgICAgICAgICAgIGl0ZW1fbmFtZSA9IGl0ZW1fbmFtZS5zdHJpcCgiLjogIikKCiAg"
    "ICAgICAgICAgIGlmIGl0ZW1fbmFtZSBhbmQgbGVuKGl0ZW1fbmFtZSkgPiAxOgogICAgICAgICAg"
    "ICAgICAgaXRlbXMuYXBwZW5kKHsiaXRlbSI6IGl0ZW1fbmFtZSwgImNyZWF0b3IiOiBjcmVhdG9y"
    "fSkKCiAgICAgICAgcmV0dXJuIGF2YXRhcl9uYW1lLCBpdGVtcwoKICAgICMg4pSA4pSAIENBUkQg"
    "UkVOREVSSU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9idWlsZF9j"
    "YXJkcyhzZWxmKSAtPiBOb25lOgogICAgICAgICMgQ2xlYXIgZXhpc3RpbmcgY2FyZHMgKGtlZXAg"
    "c3RyZXRjaCkKICAgICAgICB3aGlsZSBzZWxmLl9jYXJkX2xheW91dC5jb3VudCgpID4gMToKICAg"
    "ICAgICAgICAgaXRlbSA9IHNlbGYuX2NhcmRfbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICBp"
    "ZiBpdGVtLndpZGdldCgpOgogICAgICAgICAgICAgICAgaXRlbS53aWRnZXQoKS5kZWxldGVMYXRl"
    "cigpCgogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgY2FyZCA9"
    "IHNlbGYuX21ha2VfY2FyZChyZWMpCiAgICAgICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0Lmluc2Vy"
    "dFdpZGdldCgKICAgICAgICAgICAgICAgIHNlbGYuX2NhcmRfbGF5b3V0LmNvdW50KCkgLSAxLCBj"
    "YXJkCiAgICAgICAgICAgICkKCiAgICBkZWYgX21ha2VfY2FyZChzZWxmLCByZWM6IGRpY3QpIC0+"
    "IFFXaWRnZXQ6CiAgICAgICAgY2FyZCA9IFFGcmFtZSgpCiAgICAgICAgaXNfc2VsZWN0ZWQgPSBy"
    "ZWMuZ2V0KCJyZWNvcmRfaWQiKSA9PSBzZWxmLl9zZWxlY3RlZF9pZAogICAgICAgIGNhcmQuc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7JyMxYTBhMTAnIGlmIGlzX3Nl"
    "bGVjdGVkIGVsc2UgQ19CRzN9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0Nf"
    "Q1JJTVNPTiBpZiBpc19zZWxlY3RlZCBlbHNlIENfQk9SREVSfTsgIgogICAgICAgICAgICBmImJv"
    "cmRlci1yYWRpdXM6IDJweDsgcGFkZGluZzogMnB4OyIKICAgICAgICApCiAgICAgICAgbGF5b3V0"
    "ID0gUUhCb3hMYXlvdXQoY2FyZCkKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDgs"
    "IDYsIDgsIDYpCgogICAgICAgIG5hbWVfbGJsID0gUUxhYmVsKHJlYy5nZXQoIm5hbWUiLCAiVU5L"
    "Tk9XTiIpKQogICAgICAgIG5hbWVfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29s"
    "b3I6IHtDX0dPTERfQlJJR0hUIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19HT0xEfTsgIgogICAgICAg"
    "ICAgICBmImZvbnQtc2l6ZTogMTFweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGZvbnQtZmFtaWx5OiB7"
    "REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgY291bnQgPSBsZW4ocmVjLmdl"
    "dCgiaXRlbXMiLCBbXSkpCiAgICAgICAgY291bnRfbGJsID0gUUxhYmVsKGYie2NvdW50fSBpdGVt"
    "cyIpCiAgICAgICAgY291bnRfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6"
    "IHtDX0NSSU1TT059OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwg"
    "c2VyaWY7IgogICAgICAgICkKCiAgICAgICAgZGF0ZV9sYmwgPSBRTGFiZWwocmVjLmdldCgiY3Jl"
    "YXRlZF9hdCIsICIiKVs6MTBdKQogICAgICAgIGRhdGVfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5"
    "OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdl"
    "dChuYW1lX2xibCkKICAgICAgICBsYXlvdXQuYWRkU3RyZXRjaCgpCiAgICAgICAgbGF5b3V0LmFk"
    "ZFdpZGdldChjb3VudF9sYmwpCiAgICAgICAgbGF5b3V0LmFkZFNwYWNpbmcoMTIpCiAgICAgICAg"
    "bGF5b3V0LmFkZFdpZGdldChkYXRlX2xibCkKCiAgICAgICAgIyBDbGljayB0byBzZWxlY3QKICAg"
    "ICAgICByZWNfaWQgPSByZWMuZ2V0KCJyZWNvcmRfaWQiLCAiIikKICAgICAgICBjYXJkLm1vdXNl"
    "UHJlc3NFdmVudCA9IGxhbWJkYSBlLCByaWQ9cmVjX2lkOiBzZWxmLl9zZWxlY3RfY2FyZChyaWQp"
    "CiAgICAgICAgcmV0dXJuIGNhcmQKCiAgICBkZWYgX3NlbGVjdF9jYXJkKHNlbGYsIHJlY29yZF9p"
    "ZDogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkID0gcmVjb3JkX2lkCiAg"
    "ICAgICAgc2VsZi5fYnVpbGRfY2FyZHMoKSAgIyBSZWJ1aWxkIHRvIHNob3cgc2VsZWN0aW9uIGhp"
    "Z2hsaWdodAoKICAgIGRlZiBfc2VsZWN0ZWRfcmVjb3JkKHNlbGYpIC0+IE9wdGlvbmFsW2RpY3Rd"
    "OgogICAgICAgIHJldHVybiBuZXh0KAogICAgICAgICAgICAociBmb3IgciBpbiBzZWxmLl9yZWNv"
    "cmRzCiAgICAgICAgICAgICBpZiByLmdldCgicmVjb3JkX2lkIikgPT0gc2VsZi5fc2VsZWN0ZWRf"
    "aWQpLAogICAgICAgICAgICBOb25lCiAgICAgICAgKQoKICAgICMg4pSA4pSAIEFDVElPTlMg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYg"
    "cmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pzb25s"
    "KHNlbGYuX3BhdGgpCiAgICAgICAgIyBFbnN1cmUgcmVjb3JkX2lkIGZpZWxkIGV4aXN0cwogICAg"
    "ICAgIGNoYW5nZWQgPSBGYWxzZQogICAgICAgIGZvciByIGluIHNlbGYuX3JlY29yZHM6CiAgICAg"
    "ICAgICAgIGlmIG5vdCByLmdldCgicmVjb3JkX2lkIik6CiAgICAgICAgICAgICAgICByWyJyZWNv"
    "cmRfaWQiXSA9IHIuZ2V0KCJpZCIpIG9yIHN0cih1dWlkLnV1aWQ0KCkpCiAgICAgICAgICAgICAg"
    "ICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgICAgIHdyaXRlX2pz"
    "b25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5fYnVpbGRfY2FyZHMo"
    "KQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgwKQoKICAgIGRlZiBfcHJldmll"
    "d19wYXJzZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJhdyA9IHNlbGYuX2FkZF9yYXcudG9QbGFp"
    "blRleHQoKQogICAgICAgIG5hbWUsIGl0ZW1zID0gc2VsZi5wYXJzZV9zY2FuX3RleHQocmF3KQog"
    "ICAgICAgIHNlbGYuX2FkZF9uYW1lLnNldFBsYWNlaG9sZGVyVGV4dChuYW1lKQogICAgICAgIHNl"
    "bGYuX2FkZF9wcmV2aWV3LnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGl0IGluIGl0ZW1zWzoy"
    "MF06ICAjIHByZXZpZXcgZmlyc3QgMjAKICAgICAgICAgICAgciA9IHNlbGYuX2FkZF9wcmV2aWV3"
    "LnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuaW5zZXJ0Um93KHIpCiAg"
    "ICAgICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldEl0ZW0ociwgMCwgUVRhYmxlV2lkZ2V0SXRl"
    "bShpdFsiaXRlbSJdKSkKICAgICAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0SXRlbShyLCAx"
    "LCBRVGFibGVXaWRnZXRJdGVtKGl0WyJjcmVhdG9yIl0pKQoKICAgIGRlZiBfc2hvd19hZGQoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hZGRfbmFtZS5jbGVhcigpCiAgICAgICAgc2VsZi5f"
    "YWRkX25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJBdXRvLWRldGVjdGVkIGZyb20gc2NhbiB0ZXh0"
    "IikKICAgICAgICBzZWxmLl9hZGRfZGVzYy5jbGVhcigpCiAgICAgICAgc2VsZi5fYWRkX3Jhdy5j"
    "bGVhcigpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0Um93Q291bnQoMCkKICAgICAgICBz"
    "ZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMSkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHJhdyAgPSBzZWxmLl9hZGRfcmF3LnRvUGxhaW5UZXh0KCkKICAgICAgICBu"
    "YW1lLCBpdGVtcyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICBvdmVycmlkZV9u"
    "YW1lID0gc2VsZi5fYWRkX25hbWUudGV4dCgpLnN0cmlwKCkKICAgICAgICBub3cgID0gZGF0ZXRp"
    "bWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICByZWNvcmQgPSB7CiAgICAg"
    "ICAgICAgICJpZCI6ICAgICAgICAgIHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAicmVj"
    "b3JkX2lkIjogICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgIm5hbWUiOiAgICAgICAg"
    "b3ZlcnJpZGVfbmFtZSBvciBuYW1lLAogICAgICAgICAgICAiZGVzY3JpcHRpb24iOiBzZWxmLl9h"
    "ZGRfZGVzYy50b1BsYWluVGV4dCgpWzoyNDRdLAogICAgICAgICAgICAiaXRlbXMiOiAgICAgICBp"
    "dGVtcywKICAgICAgICAgICAgInJhd190ZXh0IjogICAgcmF3LAogICAgICAgICAgICAiY3JlYXRl"
    "ZF9hdCI6ICBub3csCiAgICAgICAgICAgICJ1cGRhdGVkX2F0IjogIG5vdywKICAgICAgICB9CiAg"
    "ICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQocmVjb3JkKQogICAgICAgIHdyaXRlX2pzb25sKHNl"
    "bGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQgPSByZWNv"
    "cmRbInJlY29yZF9pZCJdCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3Nob3dfZGlz"
    "cGxheShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgp"
    "CiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24o"
    "c2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNl"
    "bGVjdCBhIHNjYW4gdG8gZGlzcGxheS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxm"
    "Ll9kaXNwX25hbWUuc2V0VGV4dChmIuKdpyB7cmVjLmdldCgnbmFtZScsJycpfSIpCiAgICAgICAg"
    "c2VsZi5fZGlzcF9kZXNjLnNldFRleHQocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkKICAgICAg"
    "ICBzZWxmLl9kaXNwX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGl0IGluIHJlYy5n"
    "ZXQoIml0ZW1zIixbXSk6CiAgICAgICAgICAgIHIgPSBzZWxmLl9kaXNwX3RhYmxlLnJvd0NvdW50"
    "KCkKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAg"
    "c2VsZi5fZGlzcF90YWJsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRn"
    "ZXRJdGVtKGl0LmdldCgiaXRlbSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5z"
    "ZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiY3Jl"
    "YXRvciIsIlVOS05PV04iKSkpCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDIp"
    "CgogICAgZGVmIF9pdGVtX2NvbnRleHRfbWVudShzZWxmLCBwb3MpIC0+IE5vbmU6CiAgICAgICAg"
    "aWR4ID0gc2VsZi5fZGlzcF90YWJsZS5pbmRleEF0KHBvcykKICAgICAgICBpZiBub3QgaWR4Lmlz"
    "VmFsaWQoKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaXRlbV90ZXh0ICA9IChzZWxmLl9k"
    "aXNwX3RhYmxlLml0ZW0oaWR4LnJvdygpLCAwKSBvcgogICAgICAgICAgICAgICAgICAgICAgUVRh"
    "YmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAgIGNyZWF0b3IgICAgPSAoc2VsZi5fZGlz"
    "cF90YWJsZS5pdGVtKGlkeC5yb3coKSwgMSkgb3IKICAgICAgICAgICAgICAgICAgICAgIFFUYWJs"
    "ZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICBmcm9tIFB5U2lkZTYuUXRXaWRnZXRzIGlt"
    "cG9ydCBRTWVudQogICAgICAgIG1lbnUgPSBRTWVudShzZWxmKQogICAgICAgIG1lbnUuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09M"
    "RH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07Igog"
    "ICAgICAgICkKICAgICAgICBhX2l0ZW0gICAgPSBtZW51LmFkZEFjdGlvbigiQ29weSBJdGVtIE5h"
    "bWUiKQogICAgICAgIGFfY3JlYXRvciA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5IENyZWF0b3IiKQog"
    "ICAgICAgIGFfYm90aCAgICA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5IEJvdGgiKQogICAgICAgIGFj"
    "dGlvbiA9IG1lbnUuZXhlYyhzZWxmLl9kaXNwX3RhYmxlLnZpZXdwb3J0KCkubWFwVG9HbG9iYWwo"
    "cG9zKSkKICAgICAgICBjYiA9IFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKQogICAgICAgIGlmIGFj"
    "dGlvbiA9PSBhX2l0ZW06ICAgIGNiLnNldFRleHQoaXRlbV90ZXh0KQogICAgICAgIGVsaWYgYWN0"
    "aW9uID09IGFfY3JlYXRvcjogY2Iuc2V0VGV4dChjcmVhdG9yKQogICAgICAgIGVsaWYgYWN0aW9u"
    "ID09IGFfYm90aDogIGNiLnNldFRleHQoZiJ7aXRlbV90ZXh0fSDigJQge2NyZWF0b3J9IikKCiAg"
    "ICBkZWYgX3Nob3dfbW9kaWZ5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2Vs"
    "ZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAgICBRTWVzc2FnZUJv"
    "eC5pbmZvcm1hdGlvbihzZWxmLCAiU0wgU2NhbnMiLAogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAiU2VsZWN0IGEgc2NhbiB0byBtb2RpZnkuIikKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgc2VsZi5fbW9kX25hbWUuc2V0VGV4dChyZWMuZ2V0KCJuYW1lIiwiIikpCiAgICAg"
    "ICAgc2VsZi5fbW9kX2Rlc2Muc2V0VGV4dChyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpKQogICAg"
    "ICAgIHNlbGYuX21vZF90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciBpdCBpbiByZWMu"
    "Z2V0KCJpdGVtcyIsW10pOgogICAgICAgICAgICByID0gc2VsZi5fbW9kX3RhYmxlLnJvd0NvdW50"
    "KCkKICAgICAgICAgICAgc2VsZi5fbW9kX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBz"
    "ZWxmLl9tb2RfdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0"
    "SXRlbShpdC5nZXQoIml0ZW0iLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRJ"
    "dGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiY3JlYXRv"
    "ciIsIlVOS05PV04iKSkpCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDMpCgog"
    "ICAgZGVmIF9kb19tb2RpZnlfc2F2ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYu"
    "X3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgcmVjWyJuYW1lIl0gICAgICAgID0gc2VsZi5fbW9kX25hbWUudGV4dCgpLnN0cmlw"
    "KCkgb3IgIlVOS05PV04iCiAgICAgICAgcmVjWyJkZXNjcmlwdGlvbiJdID0gc2VsZi5fbW9kX2Rl"
    "c2MudGV4dCgpWzoyNDRdCiAgICAgICAgaXRlbXMgPSBbXQogICAgICAgIGZvciBpIGluIHJhbmdl"
    "KHNlbGYuX21vZF90YWJsZS5yb3dDb3VudCgpKToKICAgICAgICAgICAgaXQgID0gKHNlbGYuX21v"
    "ZF90YWJsZS5pdGVtKGksMCkgb3IgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAg"
    "ICAgICBjciAgPSAoc2VsZi5fbW9kX3RhYmxlLml0ZW0oaSwxKSBvciBRVGFibGVXaWRnZXRJdGVt"
    "KCIiKSkudGV4dCgpCiAgICAgICAgICAgIGl0ZW1zLmFwcGVuZCh7Iml0ZW0iOiBpdC5zdHJpcCgp"
    "IG9yICJVTktOT1dOIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAiY3JlYXRvciI6IGNyLnN0"
    "cmlwKCkgb3IgIlVOS05PV04ifSkKICAgICAgICByZWNbIml0ZW1zIl0gICAgICA9IGl0ZW1zCiAg"
    "ICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29m"
    "b3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAg"
    "ICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHJlYyA9IHNlbGYuX3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoK"
    "ICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gZGVsZXRl"
    "LiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5hbWUgPSByZWMuZ2V0KCJuYW1lIiwidGhp"
    "cyBzY2FuIikKICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAg"
    "ICBzZWxmLCAiRGVsZXRlIFNjYW4iLAogICAgICAgICAgICBmIkRlbGV0ZSAne25hbWV9Jz8gVGhp"
    "cyBjYW5ub3QgYmUgdW5kb25lLiIsCiAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0"
    "dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgKQogICAgICAg"
    "IGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAg"
    "c2VsZi5fcmVjb3JkcyA9IFtyIGZvciByIGluIHNlbGYuX3JlY29yZHMKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBpZiByLmdldCgicmVjb3JkX2lkIikgIT0gc2VsZi5fc2VsZWN0ZWRfaWRd"
    "CiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAg"
    "ICAgICAgIHNlbGYuX3NlbGVjdGVkX2lkID0gTm9uZQogICAgICAgICAgICBzZWxmLnJlZnJlc2go"
    "KQoKICAgIGRlZiBfZG9fcmVwYXJzZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJlYyA9IHNlbGYu"
    "X3NlbGVjdGVkX3JlY29yZCgpCiAgICAgICAgaWYgbm90IHJlYzoKICAgICAgICAgICAgUU1lc3Nh"
    "Z2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIlNMIFNjYW5zIiwKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIlNlbGVjdCBhIHNjYW4gdG8gcmUtcGFyc2UuIikKICAgICAgICAgICAg"
    "cmV0dXJuCiAgICAgICAgcmF3ID0gcmVjLmdldCgicmF3X3RleHQiLCIiKQogICAgICAgIGlmIG5v"
    "dCByYXc6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJSZS1wYXJz"
    "ZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJObyByYXcgdGV4dCBzdG9y"
    "ZWQgZm9yIHRoaXMgc2Nhbi4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBuYW1lLCBpdGVt"
    "cyA9IHNlbGYucGFyc2Vfc2Nhbl90ZXh0KHJhdykKICAgICAgICByZWNbIml0ZW1zIl0gICAgICA9"
    "IGl0ZW1zCiAgICAgICAgcmVjWyJuYW1lIl0gICAgICAgPSByZWNbIm5hbWUiXSBvciBuYW1lCiAg"
    "ICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29m"
    "b3JtYXQoKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAg"
    "ICAgICAgc2VsZi5yZWZyZXNoKCkKICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxm"
    "LCAiUmUtcGFyc2VkIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIkZvdW5kIHts"
    "ZW4oaXRlbXMpfSBpdGVtcy4iKQoKCiMg4pSA4pSAIFNMIENPTU1BTkRTIFRBQiDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xh"
    "c3MgU0xDb21tYW5kc1RhYihRV2lkZ2V0KToKICAgICIiIgogICAgU2Vjb25kIExpZmUgY29tbWFu"
    "ZCByZWZlcmVuY2UgdGFibGUuCiAgICBHb3RoaWMgdGFibGUgc3R5bGluZy4gQ29weSBjb21tYW5k"
    "IHRvIGNsaXBib2FyZCBidXR0b24gcGVyIHJvdy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhz"
    "ZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAg"
    "ICAgc2VsZi5fcGF0aCAgICA9IGNmZ19wYXRoKCJzbCIpIC8gInNsX2NvbW1hbmRzLmpzb25sIgog"
    "ICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3NldHVw"
    "X3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBfdWkoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENv"
    "bnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAg"
    "ICAgICBiYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICA9IF9nb3Ro"
    "aWNfYnRuKCLinKYgQWRkIikKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5ID0gX2dvdGhpY19idG4o"
    "IuKcpyBNb2RpZnkiKQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUgPSBfZ290aGljX2J0bigi4pyX"
    "IERlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX2NvcHkgICA9IF9nb3RoaWNfYnRuKCLip4kgQ29w"
    "eSBDb21tYW5kIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJDb3B5"
    "IHNlbGVjdGVkIGNvbW1hbmQgdG8gY2xpcGJvYXJkIikKICAgICAgICBzZWxmLl9idG5fcmVmcmVz"
    "aD0gX2dvdGhpY19idG4oIuKGuyBSZWZyZXNoIikKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeS5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xpY2tl"
    "ZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fY29weS5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fY29weV9jb21tYW5kKQogICAgICAgIHNlbGYuX2J0bl9yZWZyZXNoLmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLnJlZnJlc2gpCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9h"
    "ZGQsIHNlbGYuX2J0bl9tb2RpZnksIHNlbGYuX2J0bl9kZWxldGUsCiAgICAgICAgICAgICAgICAg"
    "IHNlbGYuX2J0bl9jb3B5LCBzZWxmLl9idG5fcmVmcmVzaCk6CiAgICAgICAgICAgIGJhci5hZGRX"
    "aWRnZXQoYikKICAgICAgICBiYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQo"
    "YmFyKQoKICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNl"
    "bGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJDb21tYW5kIiwgIkRlc2NyaXB0"
    "aW9uIl0pCiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25S"
    "ZXNpemVNb2RlKAogICAgICAgICAgICAwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gp"
    "CiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVN"
    "b2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAg"
    "ICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0cmFj"
    "dEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFi"
    "bGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRT"
    "dHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICByb290LmFkZFdpZGdldChz"
    "ZWxmLl90YWJsZSwgMSkKCiAgICAgICAgaGludCA9IFFMYWJlbCgKICAgICAgICAgICAgIlNlbGVj"
    "dCBhIHJvdyBhbmQgY2xpY2sg4qeJIENvcHkgQ29tbWFuZCB0byBjb3B5IGp1c3QgdGhlIGNvbW1h"
    "bmQgdGV4dC4iCiAgICAgICAgKQogICAgICAgIGhpbnQuc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtE"
    "RUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KGhpbnQp"
    "CgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9yZWNvcmRzID0g"
    "cmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDAp"
    "CiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICByID0gc2VsZi5f"
    "dGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAg"
    "ICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxl"
    "V2lkZ2V0SXRlbShyZWMuZ2V0KCJjb21tYW5kIiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJs"
    "ZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQo"
    "ImRlc2NyaXB0aW9uIiwiIikpKQoKICAgIGRlZiBfY29weV9jb21tYW5kKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgcm93IDwg"
    "MDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaXRlbSA9IHNlbGYuX3RhYmxlLml0ZW0ocm93"
    "LCAwKQogICAgICAgIGlmIGl0ZW06CiAgICAgICAgICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQo"
    "KS5zZXRUZXh0KGl0ZW0udGV4dCgpKQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiQWRk"
    "IENvbW1hbmQiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcy"
    "fTsgY29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKICAg"
    "ICAgICBjbWQgID0gUUxpbmVFZGl0KCk7IGRlc2MgPSBRTGluZUVkaXQoKQogICAgICAgIGZvcm0u"
    "YWRkUm93KCJDb21tYW5kOiIsIGNtZCkKICAgICAgICBmb3JtLmFkZFJvdygiRGVzY3JpcHRpb246"
    "IiwgZGVzYykKICAgICAgICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhp"
    "Y19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlj"
    "a2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQog"
    "ICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9y"
    "bS5hZGRSb3coYnRucykKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29k"
    "ZS5BY2NlcHRlZDoKICAgICAgICAgICAgbm93ID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0Yyku"
    "aXNvZm9ybWF0KCkKICAgICAgICAgICAgcmVjID0gewogICAgICAgICAgICAgICAgImlkIjogICAg"
    "ICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICAgICAiY29tbWFuZCI6ICAgICBj"
    "bWQudGV4dCgpLnN0cmlwKClbOjI0NF0sCiAgICAgICAgICAgICAgICAiZGVzY3JpcHRpb24iOiBk"
    "ZXNjLnRleHQoKS5zdHJpcCgpWzoyNDRdLAogICAgICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAg"
    "bm93LCAidXBkYXRlZF9hdCI6IG5vdywKICAgICAgICAgICAgfQogICAgICAgICAgICBpZiByZWNb"
    "ImNvbW1hbmQiXToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKHJlYykKICAg"
    "ICAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAg"
    "ICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fbW9kaWZ5KHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgcm93"
    "IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZXR1cm4KICAg"
    "ICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jvd10KICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYp"
    "CiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJNb2RpZnkgQ29tbWFuZCIpCiAgICAgICAgZGxn"
    "LnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikK"
    "ICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAgIGNtZCAgPSBRTGluZUVkaXQo"
    "cmVjLmdldCgiY29tbWFuZCIsIiIpKQogICAgICAgIGRlc2MgPSBRTGluZUVkaXQocmVjLmdldCgi"
    "ZGVzY3JpcHRpb24iLCIiKSkKICAgICAgICBmb3JtLmFkZFJvdygiQ29tbWFuZDoiLCBjbWQpCiAg"
    "ICAgICAgZm9ybS5hZGRSb3coIkRlc2NyaXB0aW9uOiIsIGRlc2MpCiAgICAgICAgYnRucyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBvayA9IF9nb3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhp"
    "Y19idG4oIkNhbmNlbCIpCiAgICAgICAgb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBj"
    "eC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7"
    "IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAgIGZvcm0uYWRkUm93KGJ0bnMpCiAgICAgICAgaWYg"
    "ZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHJl"
    "Y1siY29tbWFuZCJdICAgICA9IGNtZC50ZXh0KCkuc3RyaXAoKVs6MjQ0XQogICAgICAgICAgICBy"
    "ZWNbImRlc2NyaXB0aW9uIl0gPSBkZXNjLnRleHQoKS5zdHJpcCgpWzoyNDRdCiAgICAgICAgICAg"
    "IHJlY1sidXBkYXRlZF9hdCJdICA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1h"
    "dCgpCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAg"
    "ICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiByb3cg"
    "PCAwIG9yIHJvdyA+PSBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJldHVybgogICAg"
    "ICAgIGNtZCA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQoImNvbW1hbmQiLCJ0aGlzIGNvbW1hbmQi"
    "KQogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgIHNlbGYs"
    "ICJEZWxldGUiLCBmIkRlbGV0ZSAne2NtZH0nPyIsCiAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0"
    "YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAg"
    "KQogICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAg"
    "ICAgICAgICAgc2VsZi5fcmVjb3Jkcy5wb3Aocm93KQogICAgICAgICAgICB3cml0ZV9qc29ubChz"
    "ZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKCiMg"
    "4pSA4pSAIEpPQiBUUkFDS0VSIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSm9iVHJhY2tlclRhYihRV2lkZ2V0"
    "KToKICAgICIiIgogICAgSm9iIGFwcGxpY2F0aW9uIHRyYWNraW5nLiBGdWxsIHJlYnVpbGQgZnJv"
    "bSBzcGVjLgogICAgRmllbGRzOiBDb21wYW55LCBKb2IgVGl0bGUsIERhdGUgQXBwbGllZCwgTGlu"
    "aywgU3RhdHVzLCBOb3Rlcy4KICAgIE11bHRpLXNlbGVjdCBoaWRlL3VuaGlkZS9kZWxldGUuIENT"
    "ViBhbmQgVFNWIGV4cG9ydC4KICAgIEhpZGRlbiByb3dzID0gY29tcGxldGVkL3JlamVjdGVkIOKA"
    "lCBzdGlsbCBzdG9yZWQsIGp1c3Qgbm90IHNob3duLgogICAgIiIiCgogICAgQ09MVU1OUyA9IFsi"
    "Q29tcGFueSIsICJKb2IgVGl0bGUiLCAiRGF0ZSBBcHBsaWVkIiwKICAgICAgICAgICAgICAgIkxp"
    "bmsiLCAiU3RhdHVzIiwgIk5vdGVzIl0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5v"
    "bmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BhdGgg"
    "ICAgPSBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJqb2JfdHJhY2tlci5qc29ubCIKICAgICAgICBz"
    "ZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zaG93X2hpZGRlbiA9"
    "IEZhbHNlCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgog"
    "ICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91"
    "dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAg"
    "ICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGJhciA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBzZWxmLl9idG5fYWRkICAgID0gX2dvdGhpY19idG4oIkFkZCIpCiAgICAgICAgc2VsZi5fYnRu"
    "X21vZGlmeSA9IF9nb3RoaWNfYnRuKCJNb2RpZnkiKQogICAgICAgIHNlbGYuX2J0bl9oaWRlICAg"
    "PSBfZ290aGljX2J0bigiQXJjaGl2ZSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAiTWFyayBzZWxlY3RlZCBhcyBjb21wbGV0ZWQvcmVqZWN0ZWQiKQogICAgICAgIHNl"
    "bGYuX2J0bl91bmhpZGUgPSBfZ290aGljX2J0bigiUmVzdG9yZSIsCiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAiUmVzdG9yZSBhcmNoaXZlZCBhcHBsaWNhdGlvbnMiKQog"
    "ICAgICAgIHNlbGYuX2J0bl9kZWxldGUgPSBfZ290aGljX2J0bigiRGVsZXRlIikKICAgICAgICBz"
    "ZWxmLl9idG5fdG9nZ2xlID0gX2dvdGhpY19idG4oIlNob3cgQXJjaGl2ZWQiKQogICAgICAgIHNl"
    "bGYuX2J0bl9leHBvcnQgPSBfZ290aGljX2J0bigiRXhwb3J0IikKCiAgICAgICAgZm9yIGIgaW4g"
    "KHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9tb2RpZnksIHNlbGYuX2J0bl9oaWRlLAogICAgICAg"
    "ICAgICAgICAgICBzZWxmLl9idG5fdW5oaWRlLCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAg"
    "ICAgICAgICBzZWxmLl9idG5fdG9nZ2xlLCBzZWxmLl9idG5fZXhwb3J0KToKICAgICAgICAgICAg"
    "Yi5zZXRNaW5pbXVtV2lkdGgoNzApCiAgICAgICAgICAgIGIuc2V0TWluaW11bUhlaWdodCgyNikK"
    "ICAgICAgICAgICAgYmFyLmFkZFdpZGdldChiKQoKICAgICAgICBzZWxmLl9idG5fYWRkLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeS5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fZG9fbW9kaWZ5KQogICAgICAgIHNlbGYuX2J0bl9oaWRlLmNsaWNrZWQu"
    "Y29ubmVjdChzZWxmLl9kb19oaWRlKQogICAgICAgIHNlbGYuX2J0bl91bmhpZGUuY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX2RvX3VuaGlkZSkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQu"
    "Y29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZS5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2hpZGRlbikKICAgICAgICBzZWxmLl9idG5fZXhwb3J0LmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl9kb19leHBvcnQpCiAgICAgICAgYmFyLmFkZFN0cmV0Y2goKQog"
    "ICAgICAgIHJvb3QuYWRkTGF5b3V0KGJhcikKCiAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVX"
    "aWRnZXQoMCwgbGVuKHNlbGYuQ09MVU1OUykpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpv"
    "bnRhbEhlYWRlckxhYmVscyhzZWxmLkNPTFVNTlMpCiAgICAgICAgaGggPSBzZWxmLl90YWJsZS5o"
    "b3Jpem9udGFsSGVhZGVyKCkKICAgICAgICAjIENvbXBhbnkgYW5kIEpvYiBUaXRsZSBzdHJldGNo"
    "CiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMCwgUUhlYWRlclZpZXcuUmVzaXplTW9k"
    "ZS5TdHJldGNoKQogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDEsIFFIZWFkZXJWaWV3"
    "LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICAjIERhdGUgQXBwbGllZCDigJQgZml4ZWQgcmVh"
    "ZGFibGUgd2lkdGgKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmll"
    "dy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENvbHVtbldpZHRoKDIs"
    "IDEwMCkKICAgICAgICAjIExpbmsgc3RyZXRjaGVzCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6"
    "ZU1vZGUoMywgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgICMgU3RhdHVz"
    "IOKAlCBmaXhlZCB3aWR0aAogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDQsIFFIZWFk"
    "ZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Q29sdW1uV2lk"
    "dGgoNCwgODApCiAgICAgICAgIyBOb3RlcyBzdHJldGNoZXMKICAgICAgICBoaC5zZXRTZWN0aW9u"
    "UmVzaXplTW9kZSg1LCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCgogICAgICAgIHNl"
    "bGYuX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVt"
    "Vmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNl"
    "dFNlbGVjdGlvbk1vZGUoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbk1v"
    "ZGUuRXh0ZW5kZWRTZWxlY3Rpb24pCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdS"
    "b3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNf"
    "dGFibGVfc3R5bGUoKSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90YWJsZSwgMSkKCiAg"
    "ICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFk"
    "X2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291bnQoMCkKICAg"
    "ICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgIGhpZGRlbiA9IGJvb2wo"
    "cmVjLmdldCgiaGlkZGVuIiwgRmFsc2UpKQogICAgICAgICAgICBpZiBoaWRkZW4gYW5kIG5vdCBz"
    "ZWxmLl9zaG93X2hpZGRlbjoKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIHIg"
    "PSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLmluc2VydFJv"
    "dyhyKQogICAgICAgICAgICBzdGF0dXMgPSAiQXJjaGl2ZWQiIGlmIGhpZGRlbiBlbHNlIHJlYy5n"
    "ZXQoInN0YXR1cyIsIkFjdGl2ZSIpCiAgICAgICAgICAgIHZhbHMgPSBbCiAgICAgICAgICAgICAg"
    "ICByZWMuZ2V0KCJjb21wYW55IiwiIiksCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJqb2JfdGl0"
    "bGUiLCIiKSwKICAgICAgICAgICAgICAgIHJlYy5nZXQoImRhdGVfYXBwbGllZCIsIiIpLAogICAg"
    "ICAgICAgICAgICAgcmVjLmdldCgibGluayIsIiIpLAogICAgICAgICAgICAgICAgc3RhdHVzLAog"
    "ICAgICAgICAgICAgICAgcmVjLmdldCgibm90ZXMiLCIiKSwKICAgICAgICAgICAgXQogICAgICAg"
    "ICAgICBmb3IgYywgdiBpbiBlbnVtZXJhdGUodmFscyk6CiAgICAgICAgICAgICAgICBpdGVtID0g"
    "UVRhYmxlV2lkZ2V0SXRlbShzdHIodikpCiAgICAgICAgICAgICAgICBpZiBoaWRkZW46CiAgICAg"
    "ICAgICAgICAgICAgICAgaXRlbS5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX1RFWFRfRElNKSkKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgYywgaXRlbSkKICAgICAgICAgICAg"
    "IyBTdG9yZSByZWNvcmQgaW5kZXggaW4gZmlyc3QgY29sdW1uJ3MgdXNlciBkYXRhCiAgICAgICAg"
    "ICAgIHNlbGYuX3RhYmxlLml0ZW0ociwgMCkuc2V0RGF0YSgKICAgICAgICAgICAgICAgIFF0Lkl0"
    "ZW1EYXRhUm9sZS5Vc2VyUm9sZSwKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuaW5kZXgo"
    "cmVjKQogICAgICAgICAgICApCgogICAgZGVmIF9zZWxlY3RlZF9pbmRpY2VzKHNlbGYpIC0+IGxp"
    "c3RbaW50XToKICAgICAgICBpbmRpY2VzID0gc2V0KCkKICAgICAgICBmb3IgaXRlbSBpbiBzZWxm"
    "Ll90YWJsZS5zZWxlY3RlZEl0ZW1zKCk6CiAgICAgICAgICAgIHJvd19pdGVtID0gc2VsZi5fdGFi"
    "bGUuaXRlbShpdGVtLnJvdygpLCAwKQogICAgICAgICAgICBpZiByb3dfaXRlbToKICAgICAgICAg"
    "ICAgICAgIGlkeCA9IHJvd19pdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAg"
    "ICAgICAgICAgICAgaWYgaWR4IGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgICAgIGluZGlj"
    "ZXMuYWRkKGlkeCkKICAgICAgICByZXR1cm4gc29ydGVkKGluZGljZXMpCgogICAgZGVmIF9kaWFs"
    "b2coc2VsZiwgcmVjOiBkaWN0ID0gTm9uZSkgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgZGxn"
    "ICA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkpvYiBBcHBsaWNh"
    "dGlvbiIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBj"
    "b2xvcjoge0NfR09MRH07IikKICAgICAgICBkbGcucmVzaXplKDUwMCwgMzIwKQogICAgICAgIGZv"
    "cm0gPSBRRm9ybUxheW91dChkbGcpCgogICAgICAgIGNvbXBhbnkgPSBRTGluZUVkaXQocmVjLmdl"
    "dCgiY29tcGFueSIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIHRpdGxlICAgPSBRTGluZUVk"
    "aXQocmVjLmdldCgiam9iX3RpdGxlIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgZGUgICAg"
    "ICA9IFFEYXRlRWRpdCgpCiAgICAgICAgZGUuc2V0Q2FsZW5kYXJQb3B1cChUcnVlKQogICAgICAg"
    "IGRlLnNldERpc3BsYXlGb3JtYXQoInl5eXktTU0tZGQiKQogICAgICAgIGlmIHJlYyBhbmQgcmVj"
    "LmdldCgiZGF0ZV9hcHBsaWVkIik6CiAgICAgICAgICAgIGRlLnNldERhdGUoUURhdGUuZnJvbVN0"
    "cmluZyhyZWNbImRhdGVfYXBwbGllZCJdLCJ5eXl5LU1NLWRkIikpCiAgICAgICAgZWxzZToKICAg"
    "ICAgICAgICAgZGUuc2V0RGF0ZShRRGF0ZS5jdXJyZW50RGF0ZSgpKQogICAgICAgIGxpbmsgICAg"
    "PSBRTGluZUVkaXQocmVjLmdldCgibGluayIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIHN0"
    "YXR1cyAgPSBRTGluZUVkaXQocmVjLmdldCgic3RhdHVzIiwiQXBwbGllZCIpIGlmIHJlYyBlbHNl"
    "ICJBcHBsaWVkIikKICAgICAgICBub3RlcyAgID0gUUxpbmVFZGl0KHJlYy5nZXQoIm5vdGVzIiwi"
    "IikgaWYgcmVjIGVsc2UgIiIpCgogICAgICAgIGZvciBsYWJlbCwgd2lkZ2V0IGluIFsKICAgICAg"
    "ICAgICAgKCJDb21wYW55OiIsIGNvbXBhbnkpLCAoIkpvYiBUaXRsZToiLCB0aXRsZSksCiAgICAg"
    "ICAgICAgICgiRGF0ZSBBcHBsaWVkOiIsIGRlKSwgKCJMaW5rOiIsIGxpbmspLAogICAgICAgICAg"
    "ICAoIlN0YXR1czoiLCBzdGF0dXMpLCAoIk5vdGVzOiIsIG5vdGVzKSwKICAgICAgICBdOgogICAg"
    "ICAgICAgICBmb3JtLmFkZFJvdyhsYWJlbCwgd2lkZ2V0KQoKICAgICAgICBidG5zID0gUUhCb3hM"
    "YXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0"
    "bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNs"
    "aWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRu"
    "cy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRucykKCiAgICAgICAgaWYgZGxn"
    "LmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHJldHVy"
    "biB7CiAgICAgICAgICAgICAgICAiY29tcGFueSI6ICAgICAgY29tcGFueS50ZXh0KCkuc3RyaXAo"
    "KSwKICAgICAgICAgICAgICAgICJqb2JfdGl0bGUiOiAgICB0aXRsZS50ZXh0KCkuc3RyaXAoKSwK"
    "ICAgICAgICAgICAgICAgICJkYXRlX2FwcGxpZWQiOiBkZS5kYXRlKCkudG9TdHJpbmcoInl5eXkt"
    "TU0tZGQiKSwKICAgICAgICAgICAgICAgICJsaW5rIjogICAgICAgICBsaW5rLnRleHQoKS5zdHJp"
    "cCgpLAogICAgICAgICAgICAgICAgInN0YXR1cyI6ICAgICAgIHN0YXR1cy50ZXh0KCkuc3RyaXAo"
    "KSBvciAiQXBwbGllZCIsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICAgbm90ZXMudGV4"
    "dCgpLnN0cmlwKCksCiAgICAgICAgICAgIH0KICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBf"
    "ZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcCA9IHNlbGYuX2RpYWxvZygpCiAgICAgICAg"
    "aWYgbm90IHA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5vdyA9IGRhdGV0aW1lLm5vdyh0"
    "aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgcC51cGRhdGUoewogICAgICAgICAgICAi"
    "aWQiOiAgICAgICAgICAgICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgImhpZGRlbiI6"
    "ICAgICAgICAgRmFsc2UsCiAgICAgICAgICAgICJjb21wbGV0ZWRfZGF0ZSI6IE5vbmUsCiAgICAg"
    "ICAgICAgICJjcmVhdGVkX2F0IjogICAgIG5vdywKICAgICAgICAgICAgInVwZGF0ZWRfYXQiOiAg"
    "ICAgbm93LAogICAgICAgIH0pCiAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQocCkKICAgICAg"
    "ICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVm"
    "cmVzaCgpCgogICAgZGVmIF9kb19tb2RpZnkoc2VsZikgLT4gTm9uZToKICAgICAgICBpZHhzID0g"
    "c2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpCiAgICAgICAgaWYgbGVuKGlkeHMpICE9IDE6CiAgICAg"
    "ICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJNb2RpZnkiLAogICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAiU2VsZWN0IGV4YWN0bHkgb25lIHJvdyB0byBtb2Rp"
    "ZnkuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tpZHhz"
    "WzBdXQogICAgICAgIHAgICA9IHNlbGYuX2RpYWxvZyhyZWMpCiAgICAgICAgaWYgbm90IHA6CiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIHJlYy51cGRhdGUocCkKICAgICAgICByZWNbInVwZGF0"
    "ZWRfYXQiXSA9IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAg"
    "d3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJl"
    "c2goKQoKICAgIGRlZiBfZG9faGlkZShzZWxmKSAtPiBOb25lOgogICAgICAgIGZvciBpZHggaW4g"
    "c2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpOgogICAgICAgICAgICBpZiBpZHggPCBsZW4oc2VsZi5f"
    "cmVjb3Jkcyk6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bImhpZGRlbiJdICAg"
    "ICAgICAgPSBUcnVlCiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bImNvbXBsZXRl"
    "ZF9kYXRlIl0gPSAoCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdLmdldCgi"
    "Y29tcGxldGVkX2RhdGUiKSBvcgogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmRh"
    "dGUoKS5pc29mb3JtYXQoKQogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgc2VsZi5f"
    "cmVjb3Jkc1tpZHhdWyJ1cGRhdGVkX2F0Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRp"
    "bWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAg"
    "ICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVm"
    "cmVzaCgpCgogICAgZGVmIF9kb191bmhpZGUoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3IgaWR4"
    "IGluIHNlbGYuX3NlbGVjdGVkX2luZGljZXMoKToKICAgICAgICAgICAgaWYgaWR4IDwgbGVuKHNl"
    "bGYuX3JlY29yZHMpOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJoaWRkZW4i"
    "XSAgICAgPSBGYWxzZQogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tpZHhdWyJ1cGRhdGVk"
    "X2F0Il0gPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0Yyku"
    "aXNvZm9ybWF0KCkKICAgICAgICAgICAgICAgICkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9w"
    "YXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19k"
    "ZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAgICBpZHhzID0gc2VsZi5fc2VsZWN0ZWRfaW5kaWNl"
    "cygpCiAgICAgICAgaWYgbm90IGlkeHM6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlcGx5"
    "ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgIHNlbGYsICJEZWxldGUiLAogICAg"
    "ICAgICAgICBmIkRlbGV0ZSB7bGVuKGlkeHMpfSBzZWxlY3RlZCBhcHBsaWNhdGlvbihzKT8gQ2Fu"
    "bm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5Z"
    "ZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ObwogICAgICAgICkKICAgICAgICBpZiBy"
    "ZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgIGJhZCA9"
    "IHNldChpZHhzKQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzID0gW3IgZm9yIGksIHIgaW4gZW51"
    "bWVyYXRlKHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgaSBu"
    "b3QgaW4gYmFkXQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNv"
    "cmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfdG9nZ2xlX2hpZGRlbihz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nob3dfaGlkZGVuID0gbm90IHNlbGYuX3Nob3df"
    "aGlkZGVuCiAgICAgICAgc2VsZi5fYnRuX3RvZ2dsZS5zZXRUZXh0KAogICAgICAgICAgICAi4piA"
    "IEhpZGUgQXJjaGl2ZWQiIGlmIHNlbGYuX3Nob3dfaGlkZGVuIGVsc2UgIuKYvSBTaG93IEFyY2hp"
    "dmVkIgogICAgICAgICkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZXhwb3J0"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCwgZmlsdCA9IFFGaWxlRGlhbG9nLmdldFNhdmVG"
    "aWxlTmFtZSgKICAgICAgICAgICAgc2VsZiwgIkV4cG9ydCBKb2IgVHJhY2tlciIsCiAgICAgICAg"
    "ICAgIHN0cihjZmdfcGF0aCgiZXhwb3J0cyIpIC8gImpvYl90cmFja2VyLmNzdiIpLAogICAgICAg"
    "ICAgICAiQ1NWIEZpbGVzICgqLmNzdik7O1RhYiBEZWxpbWl0ZWQgKCoudHh0KSIKICAgICAgICAp"
    "CiAgICAgICAgaWYgbm90IHBhdGg6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGRlbGltID0g"
    "Ilx0IiBpZiBwYXRoLmxvd2VyKCkuZW5kc3dpdGgoIi50eHQiKSBlbHNlICIsIgogICAgICAgIGhl"
    "YWRlciA9IFsiY29tcGFueSIsImpvYl90aXRsZSIsImRhdGVfYXBwbGllZCIsImxpbmsiLAogICAg"
    "ICAgICAgICAgICAgICAic3RhdHVzIiwiaGlkZGVuIiwiY29tcGxldGVkX2RhdGUiLCJub3RlcyJd"
    "CiAgICAgICAgd2l0aCBvcGVuKHBhdGgsICJ3IiwgZW5jb2Rpbmc9InV0Zi04IiwgbmV3bGluZT0i"
    "IikgYXMgZjoKICAgICAgICAgICAgZi53cml0ZShkZWxpbS5qb2luKGhlYWRlcikgKyAiXG4iKQog"
    "ICAgICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAgICAgICAgICAgICAgICB2YWxz"
    "ID0gWwogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImNvbXBhbnkiLCIiKSwKICAgICAgICAg"
    "ICAgICAgICAgICByZWMuZ2V0KCJqb2JfdGl0bGUiLCIiKSwKICAgICAgICAgICAgICAgICAgICBy"
    "ZWMuZ2V0KCJkYXRlX2FwcGxpZWQiLCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMuZ2V0KCJs"
    "aW5rIiwiIiksCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgic3RhdHVzIiwiIiksCiAgICAg"
    "ICAgICAgICAgICAgICAgc3RyKGJvb2wocmVjLmdldCgiaGlkZGVuIixGYWxzZSkpKSwKICAgICAg"
    "ICAgICAgICAgICAgICByZWMuZ2V0KCJjb21wbGV0ZWRfZGF0ZSIsIiIpIG9yICIiLAogICAgICAg"
    "ICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAgICAgICAgICAgICAgICBdCiAgICAg"
    "ICAgICAgICAgICBmLndyaXRlKGRlbGltLmpvaW4oCiAgICAgICAgICAgICAgICAgICAgc3RyKHYp"
    "LnJlcGxhY2UoIlxuIiwiICIpLnJlcGxhY2UoZGVsaW0sIiAiKQogICAgICAgICAgICAgICAgICAg"
    "IGZvciB2IGluIHZhbHMKICAgICAgICAgICAgICAgICkgKyAiXG4iKQogICAgICAgIFFNZXNzYWdl"
    "Qm94LmluZm9ybWF0aW9uKHNlbGYsICJFeHBvcnRlZCIsCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgZiJTYXZlZCB0byB7cGF0aH0iKQoKCiMg4pSA4pSAIFNFTEYgVEFCIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBSZWNvcmRzVGFiKFFXaWRnZXQpOgogICAgIiIiR29v"
    "Z2xlIERyaXZlL0RvY3MgcmVjb3JkcyBicm93c2VyIHRhYi4iIiIKCiAgICBkZWYgX19pbml0X18o"
    "c2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAg"
    "ICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJn"
    "aW5zKDYsIDYsIDYsIDYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHNlbGYu"
    "c3RhdHVzX2xhYmVsID0gUUxhYmVsKCJSZWNvcmRzIGFyZSBub3QgbG9hZGVkIHlldC4iKQogICAg"
    "ICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6"
    "IHtDX1RFWFRfRElNfTsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXpl"
    "OiAxMHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5zdGF0dXNfbGFi"
    "ZWwpCgogICAgICAgIHNlbGYucGF0aF9sYWJlbCA9IFFMYWJlbCgiUGF0aDogTXkgRHJpdmUiKQog"
    "ICAgICAgIHNlbGYucGF0aF9sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9y"
    "OiB7Q19HT0xEX0RJTX07IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6"
    "ZTogMTBweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYucGF0aF9sYWJl"
    "bCkKCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3QgPSBRTGlzdFdpZGdldCgpCiAgICAgICAgc2Vs"
    "Zi5yZWNvcmRzX2xpc3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7"
    "Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07Igog"
    "ICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLnJlY29yZHNfbGlzdCwgMSkKCiAg"
    "ICBkZWYgc2V0X2l0ZW1zKHNlbGYsIGZpbGVzOiBsaXN0W2RpY3RdLCBwYXRoX3RleHQ6IHN0ciA9"
    "ICJNeSBEcml2ZSIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5wYXRoX2xhYmVsLnNldFRleHQoZiJQ"
    "YXRoOiB7cGF0aF90ZXh0fSIpCiAgICAgICAgc2VsZi5yZWNvcmRzX2xpc3QuY2xlYXIoKQogICAg"
    "ICAgIGZvciBmaWxlX2luZm8gaW4gZmlsZXM6CiAgICAgICAgICAgIHRpdGxlID0gKGZpbGVfaW5m"
    "by5nZXQoIm5hbWUiKSBvciAiVW50aXRsZWQiKS5zdHJpcCgpIG9yICJVbnRpdGxlZCIKICAgICAg"
    "ICAgICAgbWltZSA9IChmaWxlX2luZm8uZ2V0KCJtaW1lVHlwZSIpIG9yICIiKS5zdHJpcCgpCiAg"
    "ICAgICAgICAgIGlmIG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5mb2xkZXIi"
    "OgogICAgICAgICAgICAgICAgcHJlZml4ID0gIvCfk4EiCiAgICAgICAgICAgIGVsaWYgbWltZSA9"
    "PSAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IjoKICAgICAgICAgICAgICAg"
    "IHByZWZpeCA9ICLwn5OdIgogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgcHJlZml4"
    "ID0gIvCfk4QiCiAgICAgICAgICAgIG1vZGlmaWVkID0gKGZpbGVfaW5mby5nZXQoIm1vZGlmaWVk"
    "VGltZSIpIG9yICIiKS5yZXBsYWNlKCJUIiwgIiAiKS5yZXBsYWNlKCJaIiwgIiBVVEMiKQogICAg"
    "ICAgICAgICB0ZXh0ID0gZiJ7cHJlZml4fSB7dGl0bGV9IiArIChmIiAgICBbe21vZGlmaWVkfV0i"
    "IGlmIG1vZGlmaWVkIGVsc2UgIiIpCiAgICAgICAgICAgIGl0ZW0gPSBRTGlzdFdpZGdldEl0ZW0o"
    "dGV4dCkKICAgICAgICAgICAgaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwg"
    "ZmlsZV9pbmZvKQogICAgICAgICAgICBzZWxmLnJlY29yZHNfbGlzdC5hZGRJdGVtKGl0ZW0pCiAg"
    "ICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkxvYWRlZCB7bGVuKGZpbGVzKX0gR29v"
    "Z2xlIERyaXZlIGl0ZW0ocykuIikKCgpjbGFzcyBUYXNrc1RhYihRV2lkZ2V0KToKICAgICIiIlRh"
    "c2sgcmVnaXN0cnkgKyBHb29nbGUtZmlyc3QgZWRpdG9yIHdvcmtmbG93IHRhYi4iIiIKCiAgICBk"
    "ZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKICAgICAgICB0YXNrc19wcm92aWRlciwKICAgICAg"
    "ICBvbl9hZGRfZWRpdG9yX29wZW4sCiAgICAgICAgb25fY29tcGxldGVfc2VsZWN0ZWQsCiAgICAg"
    "ICAgb25fY2FuY2VsX3NlbGVjdGVkLAogICAgICAgIG9uX3RvZ2dsZV9jb21wbGV0ZWQsCiAgICAg"
    "ICAgb25fcHVyZ2VfY29tcGxldGVkLAogICAgICAgIG9uX2ZpbHRlcl9jaGFuZ2VkLAogICAgICAg"
    "IG9uX2VkaXRvcl9zYXZlLAogICAgICAgIG9uX2VkaXRvcl9jYW5jZWwsCiAgICAgICAgZGlhZ25v"
    "c3RpY3NfbG9nZ2VyPU5vbmUsCiAgICAgICAgcGFyZW50PU5vbmUsCiAgICApOgogICAgICAgIHN1"
    "cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3Rhc2tzX3Byb3ZpZGVyID0gdGFz"
    "a3NfcHJvdmlkZXIKICAgICAgICBzZWxmLl9vbl9hZGRfZWRpdG9yX29wZW4gPSBvbl9hZGRfZWRp"
    "dG9yX29wZW4KICAgICAgICBzZWxmLl9vbl9jb21wbGV0ZV9zZWxlY3RlZCA9IG9uX2NvbXBsZXRl"
    "X3NlbGVjdGVkCiAgICAgICAgc2VsZi5fb25fY2FuY2VsX3NlbGVjdGVkID0gb25fY2FuY2VsX3Nl"
    "bGVjdGVkCiAgICAgICAgc2VsZi5fb25fdG9nZ2xlX2NvbXBsZXRlZCA9IG9uX3RvZ2dsZV9jb21w"
    "bGV0ZWQKICAgICAgICBzZWxmLl9vbl9wdXJnZV9jb21wbGV0ZWQgPSBvbl9wdXJnZV9jb21wbGV0"
    "ZWQKICAgICAgICBzZWxmLl9vbl9maWx0ZXJfY2hhbmdlZCA9IG9uX2ZpbHRlcl9jaGFuZ2VkCiAg"
    "ICAgICAgc2VsZi5fb25fZWRpdG9yX3NhdmUgPSBvbl9lZGl0b3Jfc2F2ZQogICAgICAgIHNlbGYu"
    "X29uX2VkaXRvcl9jYW5jZWwgPSBvbl9lZGl0b3JfY2FuY2VsCiAgICAgICAgc2VsZi5fZGlhZ19s"
    "b2dnZXIgPSBkaWFnbm9zdGljc19sb2dnZXIKICAgICAgICBzZWxmLl9zaG93X2NvbXBsZXRlZCA9"
    "IEZhbHNlCiAgICAgICAgc2VsZi5fcmVmcmVzaF90aHJlYWQgPSBOb25lCiAgICAgICAgc2VsZi5f"
    "YnVpbGRfdWkoKQoKICAgIGRlZiBfYnVpbGRfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290"
    "ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2"
    "LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQogICAgICAgIHNlbGYud29ya3NwYWNl"
    "X3N0YWNrID0gUVN0YWNrZWRXaWRnZXQoKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYud29y"
    "a3NwYWNlX3N0YWNrLCAxKQoKICAgICAgICBub3JtYWwgPSBRV2lkZ2V0KCkKICAgICAgICBub3Jt"
    "YWxfbGF5b3V0ID0gUVZCb3hMYXlvdXQobm9ybWFsKQogICAgICAgIG5vcm1hbF9sYXlvdXQuc2V0"
    "Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbm9ybWFsX2xheW91dC5zZXRTcGFj"
    "aW5nKDQpCgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVsKCJUYXNrIHJlZ2lzdHJ5"
    "IGlzIG5vdCBsb2FkZWQgeWV0LiIpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LWZhbWlseToge0RF"
    "Q0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBub3Jt"
    "YWxfbGF5b3V0LmFkZFdpZGdldChzZWxmLnN0YXR1c19sYWJlbCkKCiAgICAgICAgZmlsdGVyX3Jv"
    "dyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChfc2VjdGlvbl9s"
    "YmwoIuKdpyBEQVRFIFJBTkdFIikpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21ibyA9IFFD"
    "b21ib0JveCgpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5hZGRJdGVtKCJXRUVLIiwg"
    "IndlZWsiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiTU9OVEgiLCAi"
    "bW9udGgiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiTkVYVCAzIE1P"
    "TlRIUyIsICJuZXh0XzNfbW9udGhzIikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmFk"
    "ZEl0ZW0oIllFQVIiLCAieWVhciIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5zZXRD"
    "dXJyZW50SW5kZXgoMikKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLmN1cnJlbnRJbmRl"
    "eENoYW5nZWQuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIF86IHNlbGYuX29uX2ZpbHRlcl9j"
    "aGFuZ2VkKHNlbGYudGFza19maWx0ZXJfY29tYm8uY3VycmVudERhdGEoKSBvciAibmV4dF8zX21v"
    "bnRocyIpCiAgICAgICAgKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYudGFza19m"
    "aWx0ZXJfY29tYm8pCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRTdHJldGNoKDEpCiAgICAgICAgbm9y"
    "bWFsX2xheW91dC5hZGRMYXlvdXQoZmlsdGVyX3JvdykKCiAgICAgICAgc2VsZi50YXNrX3RhYmxl"
    "ID0gUVRhYmxlV2lkZ2V0KDAsIDQpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEhvcml6b250"
    "YWxIZWFkZXJMYWJlbHMoWyJTdGF0dXMiLCAiRHVlIiwgIlRhc2siLCAiU291cmNlIl0pCiAgICAg"
    "ICAgc2VsZi50YXNrX3RhYmxlLnNldFNlbGVjdGlvbkJlaGF2aW9yKFFBYnN0cmFjdEl0ZW1WaWV3"
    "LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNl"
    "dFNlbGVjdGlvbk1vZGUoUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uTW9kZS5FeHRlbmRlZFNl"
    "bGVjdGlvbikKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0RWRpdFRyaWdnZXJzKFFBYnN0cmFj"
    "dEl0ZW1WaWV3LkVkaXRUcmlnZ2VyLk5vRWRpdFRyaWdnZXJzKQogICAgICAgIHNlbGYudGFza190"
    "YWJsZS52ZXJ0aWNhbEhlYWRlcigpLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi50YXNr"
    "X3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgwLCBRSGVhZGVy"
    "Vmlldy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxl"
    "Lmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgxLCBRSGVhZGVyVmlldy5S"
    "ZXNpemVNb2RlLlJlc2l6ZVRvQ29udGVudHMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6"
    "b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmlldy5SZXNpemVN"
    "b2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5z"
    "ZXRTZWN0aW9uUmVzaXplTW9kZSgzLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlJlc2l6ZVRvQ29u"
    "dGVudHMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJs"
    "ZV9zdHlsZSgpKQogICAgICAgIHNlbGYudGFza190YWJsZS5pdGVtU2VsZWN0aW9uQ2hhbmdlZC5j"
    "b25uZWN0KHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0dG9uX3N0YXRlKQogICAgICAgIG5vcm1hbF9s"
    "YXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza190YWJsZSwgMSkKCiAgICAgICAgYWN0aW9ucyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICBzZWxmLmJ0bl9hZGRfdGFza193b3Jrc3BhY2UgPSBfZ290aGlj"
    "X2J0bigiQUREIFRBU0siKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2sgPSBfZ290aGlj"
    "X2J0bigiQ09NUExFVEUgU0VMRUNURUQiKQogICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrID0g"
    "X2dvdGhpY19idG4oIkNBTkNFTCBTRUxFQ1RFRCIpCiAgICAgICAgc2VsZi5idG5fdG9nZ2xlX2Nv"
    "bXBsZXRlZCA9IF9nb3RoaWNfYnRuKCJTSE9XIENPTVBMRVRFRCIpCiAgICAgICAgc2VsZi5idG5f"
    "cHVyZ2VfY29tcGxldGVkID0gX2dvdGhpY19idG4oIlBVUkdFIENPTVBMRVRFRCIpCiAgICAgICAg"
    "c2VsZi5idG5fYWRkX3Rhc2tfd29ya3NwYWNlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9hZGRf"
    "ZWRpdG9yX29wZW4pCiAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzay5jbGlja2VkLmNvbm5l"
    "Y3Qoc2VsZi5fb25fY29tcGxldGVfc2VsZWN0ZWQpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rh"
    "c2suY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2NhbmNlbF9zZWxlY3RlZCkKICAgICAgICBzZWxm"
    "LmJ0bl90b2dnbGVfY29tcGxldGVkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl90b2dnbGVfY29t"
    "cGxldGVkKQogICAgICAgIHNlbGYuYnRuX3B1cmdlX2NvbXBsZXRlZC5jbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5fb25fcHVyZ2VfY29tcGxldGVkKQogICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2su"
    "c2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzay5zZXRFbmFibGVk"
    "KEZhbHNlKQogICAgICAgIGZvciBidG4gaW4gKAogICAgICAgICAgICBzZWxmLmJ0bl9hZGRfdGFz"
    "a193b3Jrc3BhY2UsCiAgICAgICAgICAgIHNlbGYuYnRuX2NvbXBsZXRlX3Rhc2ssCiAgICAgICAg"
    "ICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrLAogICAgICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29t"
    "cGxldGVkLAogICAgICAgICAgICBzZWxmLmJ0bl9wdXJnZV9jb21wbGV0ZWQsCiAgICAgICAgKToK"
    "ICAgICAgICAgICAgYWN0aW9ucy5hZGRXaWRnZXQoYnRuKQogICAgICAgIG5vcm1hbF9sYXlvdXQu"
    "YWRkTGF5b3V0KGFjdGlvbnMpCiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suYWRkV2lkZ2V0"
    "KG5vcm1hbCkKCiAgICAgICAgZWRpdG9yID0gUVdpZGdldCgpCiAgICAgICAgZWRpdG9yX2xheW91"
    "dCA9IFFWQm94TGF5b3V0KGVkaXRvcikKICAgICAgICBlZGl0b3JfbGF5b3V0LnNldENvbnRlbnRz"
    "TWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGVkaXRvcl9sYXlvdXQuc2V0U3BhY2luZyg0KQog"
    "ICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFRBU0sgRURJ"
    "VE9SIOKAlCBHT09HTEUtRklSU1QiKSkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19s"
    "YWJlbCA9IFFMYWJlbCgiQ29uZmlndXJlIHRhc2sgZGV0YWlscywgdGhlbiBzYXZlIHRvIEdvb2ds"
    "ZSBDYWxlbmRhci4iKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVsLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RF"
    "WFRfRElNfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgcGFkZGluZzogNnB4OyIKICAg"
    "ICAgICApCiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQoc2VsZi50YXNrX2VkaXRvcl9z"
    "dGF0dXNfbGFiZWwpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9uYW1lID0gUUxpbmVFZGl0KCkK"
    "ICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJUYXNrIE5h"
    "bWUiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF0ZSA9IFFMaW5lRWRpdCgpCiAg"
    "ICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLnNldFBsYWNlaG9sZGVyVGV4dCgiU3Rh"
    "cnQgRGF0ZSAoWVlZWS1NTS1ERCkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfdGlt"
    "ZSA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLnNldFBs"
    "YWNlaG9sZGVyVGV4dCgiU3RhcnQgVGltZSAoSEg6TU0pIikKICAgICAgICBzZWxmLnRhc2tfZWRp"
    "dG9yX2VuZF9kYXRlID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF9k"
    "YXRlLnNldFBsYWNlaG9sZGVyVGV4dCgiRW5kIERhdGUgKFlZWVktTU0tREQpIikKICAgICAgICBz"
    "ZWxmLnRhc2tfZWRpdG9yX2VuZF90aW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tf"
    "ZWRpdG9yX2VuZF90aW1lLnNldFBsYWNlaG9sZGVyVGV4dCgiRW5kIFRpbWUgKEhIOk1NKSIpCiAg"
    "ICAgICAgc2VsZi50YXNrX2VkaXRvcl9sb2NhdGlvbiA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2Vs"
    "Zi50YXNrX2VkaXRvcl9sb2NhdGlvbi5zZXRQbGFjZWhvbGRlclRleHQoIkxvY2F0aW9uIChvcHRp"
    "b25hbCkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfcmVjdXJyZW5jZSA9IFFMaW5lRWRpdCgp"
    "CiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnNldFBsYWNlaG9sZGVyVGV4dCgi"
    "UmVjdXJyZW5jZSBSUlVMRSAob3B0aW9uYWwpIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2Fs"
    "bF9kYXkgPSBRQ2hlY2tCb3goIkFsbC1kYXkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfbm90"
    "ZXMgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfbm90ZXMuc2V0UGxhY2Vo"
    "b2xkZXJUZXh0KCJOb3RlcyIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9ub3Rlcy5zZXRNYXhp"
    "bXVtSGVpZ2h0KDkwKQogICAgICAgIGZvciB3aWRnZXQgaW4gKAogICAgICAgICAgICBzZWxmLnRh"
    "c2tfZWRpdG9yX25hbWUsCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhcnRfZGF0ZSwK"
    "ICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lLAogICAgICAgICAgICBzZWxm"
    "LnRhc2tfZWRpdG9yX2VuZF9kYXRlLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2VuZF90"
    "aW1lLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2xvY2F0aW9uLAogICAgICAgICAgICBz"
    "ZWxmLnRhc2tfZWRpdG9yX3JlY3VycmVuY2UsCiAgICAgICAgKToKICAgICAgICAgICAgZWRpdG9y"
    "X2xheW91dC5hZGRXaWRnZXQod2lkZ2V0KQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0"
    "KHNlbGYudGFza19lZGl0b3JfYWxsX2RheSkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdl"
    "dChzZWxmLnRhc2tfZWRpdG9yX25vdGVzLCAxKQogICAgICAgIGVkaXRvcl9hY3Rpb25zID0gUUhC"
    "b3hMYXlvdXQoKQogICAgICAgIGJ0bl9zYXZlID0gX2dvdGhpY19idG4oIlNBVkUiKQogICAgICAg"
    "IGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigiQ0FOQ0VMIikKICAgICAgICBidG5fc2F2ZS5jbGlj"
    "a2VkLmNvbm5lY3Qoc2VsZi5fb25fZWRpdG9yX3NhdmUpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlj"
    "a2VkLmNvbm5lY3Qoc2VsZi5fb25fZWRpdG9yX2NhbmNlbCkKICAgICAgICBlZGl0b3JfYWN0aW9u"
    "cy5hZGRXaWRnZXQoYnRuX3NhdmUpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkV2lkZ2V0KGJ0"
    "bl9jYW5jZWwpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMuYWRkU3RyZXRjaCgxKQogICAgICAgIGVk"
    "aXRvcl9sYXlvdXQuYWRkTGF5b3V0KGVkaXRvcl9hY3Rpb25zKQogICAgICAgIHNlbGYud29ya3Nw"
    "YWNlX3N0YWNrLmFkZFdpZGdldChlZGl0b3IpCgogICAgICAgIHNlbGYubm9ybWFsX3dvcmtzcGFj"
    "ZSA9IG5vcm1hbAogICAgICAgIHNlbGYuZWRpdG9yX3dvcmtzcGFjZSA9IGVkaXRvcgogICAgICAg"
    "IHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQoc2VsZi5ub3JtYWxfd29ya3Nw"
    "YWNlKQoKICAgIGRlZiBfdXBkYXRlX2FjdGlvbl9idXR0b25fc3RhdGUoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBlbmFibGVkID0gYm9vbChzZWxmLnNlbGVjdGVkX3Rhc2tfaWRzKCkpCiAgICAgICAg"
    "c2VsZi5idG5fY29tcGxldGVfdGFzay5zZXRFbmFibGVkKGVuYWJsZWQpCiAgICAgICAgc2VsZi5i"
    "dG5fY2FuY2VsX3Rhc2suc2V0RW5hYmxlZChlbmFibGVkKQoKICAgIGRlZiBzZWxlY3RlZF90YXNr"
    "X2lkcyhzZWxmKSAtPiBsaXN0W3N0cl06CiAgICAgICAgaWRzOiBsaXN0W3N0cl0gPSBbXQogICAg"
    "ICAgIGZvciByIGluIHJhbmdlKHNlbGYudGFza190YWJsZS5yb3dDb3VudCgpKToKICAgICAgICAg"
    "ICAgc3RhdHVzX2l0ZW0gPSBzZWxmLnRhc2tfdGFibGUuaXRlbShyLCAwKQogICAgICAgICAgICBp"
    "ZiBzdGF0dXNfaXRlbSBpcyBOb25lOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAg"
    "ICAgaWYgbm90IHN0YXR1c19pdGVtLmlzU2VsZWN0ZWQoKToKICAgICAgICAgICAgICAgIGNvbnRp"
    "bnVlCiAgICAgICAgICAgIHRhc2tfaWQgPSBzdGF0dXNfaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9s"
    "ZS5Vc2VyUm9sZSkKICAgICAgICAgICAgaWYgdGFza19pZCBhbmQgdGFza19pZCBub3QgaW4gaWRz"
    "OgogICAgICAgICAgICAgICAgaWRzLmFwcGVuZCh0YXNrX2lkKQogICAgICAgIHJldHVybiBpZHMK"
    "CiAgICBkZWYgbG9hZF90YXNrcyhzZWxmLCB0YXNrczogbGlzdFtkaWN0XSkgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLnRhc2tfdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgdGFzayBpbiB0"
    "YXNrczoKICAgICAgICAgICAgcm93ID0gc2VsZi50YXNrX3RhYmxlLnJvd0NvdW50KCkKICAgICAg"
    "ICAgICAgc2VsZi50YXNrX3RhYmxlLmluc2VydFJvdyhyb3cpCiAgICAgICAgICAgIHN0YXR1cyA9"
    "ICh0YXNrLmdldCgic3RhdHVzIikgb3IgInBlbmRpbmciKS5sb3dlcigpCiAgICAgICAgICAgIHN0"
    "YXR1c19pY29uID0gIuKYkSIgaWYgc3RhdHVzIGluIHsiY29tcGxldGVkIiwgImNhbmNlbGxlZCJ9"
    "IGVsc2UgIuKAoiIKICAgICAgICAgICAgZHVlID0gKHRhc2suZ2V0KCJkdWVfYXQiKSBvciAiIiku"
    "cmVwbGFjZSgiVCIsICIgIikKICAgICAgICAgICAgdGV4dCA9ICh0YXNrLmdldCgidGV4dCIpIG9y"
    "ICJSZW1pbmRlciIpLnN0cmlwKCkgb3IgIlJlbWluZGVyIgogICAgICAgICAgICBzb3VyY2UgPSAo"
    "dGFzay5nZXQoInNvdXJjZSIpIG9yICJsb2NhbCIpLmxvd2VyKCkKICAgICAgICAgICAgc3RhdHVz"
    "X2l0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKGYie3N0YXR1c19pY29ufSB7c3RhdHVzfSIpCiAgICAg"
    "ICAgICAgIHN0YXR1c19pdGVtLnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCB0YXNr"
    "LmdldCgiaWQiKSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAwLCBz"
    "dGF0dXNfaXRlbSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAxLCBR"
    "VGFibGVXaWRnZXRJdGVtKGR1ZSkpCiAgICAgICAgICAgIHNlbGYudGFza190YWJsZS5zZXRJdGVt"
    "KHJvdywgMiwgUVRhYmxlV2lkZ2V0SXRlbSh0ZXh0KSkKICAgICAgICAgICAgc2VsZi50YXNrX3Rh"
    "YmxlLnNldEl0ZW0ocm93LCAzLCBRVGFibGVXaWRnZXRJdGVtKHNvdXJjZSkpCiAgICAgICAgc2Vs"
    "Zi5zdGF0dXNfbGFiZWwuc2V0VGV4dChmIkxvYWRlZCB7bGVuKHRhc2tzKX0gdGFzayhzKS4iKQog"
    "ICAgICAgIHNlbGYuX3VwZGF0ZV9hY3Rpb25fYnV0dG9uX3N0YXRlKCkKCiAgICBkZWYgX2RpYWco"
    "c2VsZiwgbWVzc2FnZTogc3RyLCBsZXZlbDogc3RyID0gIklORk8iKSAtPiBOb25lOgogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgaWYgc2VsZi5fZGlhZ19sb2dnZXI6CiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9kaWFnX2xvZ2dlcihtZXNzYWdlLCBsZXZlbCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "OgogICAgICAgICAgICBwYXNzCgogICAgZGVmIHN0b3BfcmVmcmVzaF93b3JrZXIoc2VsZiwgcmVh"
    "c29uOiBzdHIgPSAiIikgLT4gTm9uZToKICAgICAgICB0aHJlYWQgPSBnZXRhdHRyKHNlbGYsICJf"
    "cmVmcmVzaF90aHJlYWQiLCBOb25lKQogICAgICAgIGlmIHRocmVhZCBpcyBub3QgTm9uZSBhbmQg"
    "aGFzYXR0cih0aHJlYWQsICJpc1J1bm5pbmciKSBhbmQgdGhyZWFkLmlzUnVubmluZygpOgogICAg"
    "ICAgICAgICBzZWxmLl9kaWFnKAogICAgICAgICAgICAgICAgZiJbVEFTS1NdW1RIUkVBRF1bV0FS"
    "Tl0gc3RvcCByZXF1ZXN0ZWQgZm9yIHJlZnJlc2ggd29ya2VyIHJlYXNvbj17cmVhc29uIG9yICd1"
    "bnNwZWNpZmllZCd9IiwKICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICB0aHJlYWQucmVxdWVzdEludGVycnVwdGlvbigp"
    "CiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCiAgICAg"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHRocmVhZC5xdWl0KCkKICAgICAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICAgICAgdGhyZWFkLndh"
    "aXQoMjAwMCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3RocmVhZCA9IE5vbmUKCiAgICBkZWYgcmVm"
    "cmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBjYWxsYWJsZShzZWxmLl90YXNrc19w"
    "cm92aWRlcik6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc2Vs"
    "Zi5sb2FkX3Rhc2tzKHNlbGYuX3Rhc2tzX3Byb3ZpZGVyKCkpCiAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fZGlhZyhmIltUQVNLU11bVEFCXVtFUlJPUl0g"
    "cmVmcmVzaCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiKQogICAgICAgICAgICBzZWxmLnN0b3BfcmVm"
    "cmVzaF93b3JrZXIocmVhc29uPSJ0YXNrc190YWJfcmVmcmVzaF9leGNlcHRpb24iKQoKICAgIGRl"
    "ZiBjbG9zZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHNlbGYuc3RvcF9yZWZy"
    "ZXNoX3dvcmtlcihyZWFzb249InRhc2tzX3RhYl9jbG9zZSIpCiAgICAgICAgc3VwZXIoKS5jbG9z"
    "ZUV2ZW50KGV2ZW50KQoKICAgIGRlZiBzZXRfc2hvd19jb21wbGV0ZWQoc2VsZiwgZW5hYmxlZDog"
    "Ym9vbCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9zaG93X2NvbXBsZXRlZCA9IGJvb2woZW5hYmxl"
    "ZCkKICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkLnNldFRleHQoIkhJREUgQ09NUExF"
    "VEVEIiBpZiBzZWxmLl9zaG93X2NvbXBsZXRlZCBlbHNlICJTSE9XIENPTVBMRVRFRCIpCgogICAg"
    "ZGVmIHNldF9zdGF0dXMoc2VsZiwgdGV4dDogc3RyLCBvazogYm9vbCA9IEZhbHNlKSAtPiBOb25l"
    "OgogICAgICAgIGNvbG9yID0gQ19HUkVFTiBpZiBvayBlbHNlIENfVEVYVF9ESU0KICAgICAgICBz"
    "ZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBm"
    "ImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Y29sb3J9OyBib3JkZXI6IDFweCBzb2xpZCB7"
    "Q19CT1JERVJ9OyBwYWRkaW5nOiA2cHg7IgogICAgICAgICkKICAgICAgICBzZWxmLnRhc2tfZWRp"
    "dG9yX3N0YXR1c19sYWJlbC5zZXRUZXh0KHRleHQpCgogICAgZGVmIG9wZW5fZWRpdG9yKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suc2V0Q3VycmVudFdpZGdldChz"
    "ZWxmLmVkaXRvcl93b3Jrc3BhY2UpCgogICAgZGVmIGNsb3NlX2VkaXRvcihzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYud29ya3NwYWNlX3N0YWNrLnNldEN1cnJlbnRXaWRnZXQoc2VsZi5ub3Jt"
    "YWxfd29ya3NwYWNlKQoKCmNsYXNzIFNlbGZUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFBlcnNv"
    "bmEncyBpbnRlcm5hbCBkaWFsb2d1ZSBzcGFjZS4KICAgIFJlY2VpdmVzOiBpZGxlIG5hcnJhdGl2"
    "ZSBvdXRwdXQsIHVuc29saWNpdGVkIHRyYW5zbWlzc2lvbnMsCiAgICAgICAgICAgICAgUG9JIGxp"
    "c3QgZnJvbSBkYWlseSByZWZsZWN0aW9uLCB1bmFuc3dlcmVkIHF1ZXN0aW9uIGZsYWdzLAogICAg"
    "ICAgICAgICAgIGpvdXJuYWwgbG9hZCBub3RpZmljYXRpb25zLgogICAgUmVhZC1vbmx5IGRpc3Bs"
    "YXkuIFNlcGFyYXRlIGZyb20gcGVyc29uYSBjaGF0IHRhYiBhbHdheXMuCiAgICAiIiIKCiAgICBk"
    "ZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18o"
    "cGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0"
    "Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgog"
    "ICAgICAgIGhkciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBoZHIuYWRkV2lkZ2V0KF9zZWN0aW9u"
    "X2xibChmIuKdpyBJTk5FUiBTQU5DVFVNIOKAlCB7REVDS19OQU1FLnVwcGVyKCl9J1MgUFJJVkFU"
    "RSBUSE9VR0hUUyIpKQogICAgICAgIHNlbGYuX2J0bl9jbGVhciA9IF9nb3RoaWNfYnRuKCLinJcg"
    "Q2xlYXIiKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5zZXRGaXhlZFdpZHRoKDgwKQogICAgICAg"
    "IHNlbGYuX2J0bl9jbGVhci5jbGlja2VkLmNvbm5lY3Qoc2VsZi5jbGVhcikKICAgICAgICBoZHIu"
    "YWRkU3RyZXRjaCgpCiAgICAgICAgaGRyLmFkZFdpZGdldChzZWxmLl9idG5fY2xlYXIpCiAgICAg"
    "ICAgcm9vdC5hZGRMYXlvdXQoaGRyKQoKICAgICAgICBzZWxmLl9kaXNwbGF5ID0gUVRleHRFZGl0"
    "KCkKICAgICAgICBzZWxmLl9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5f"
    "ZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklU"
    "T1J9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7"
    "Q19QVVJQTEVfRElNfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwg"
    "c2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAg"
    "cm9vdC5hZGRXaWRnZXQoc2VsZi5fZGlzcGxheSwgMSkKCiAgICBkZWYgYXBwZW5kKHNlbGYsIGxh"
    "YmVsOiBzdHIsIHRleHQ6IHN0cikgLT4gTm9uZToKICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGlt"
    "ZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgIGNvbG9ycyA9IHsKICAgICAgICAg"
    "ICAgIk5BUlJBVElWRSI6ICBDX0dPTEQsCiAgICAgICAgICAgICJSRUZMRUNUSU9OIjogQ19QVVJQ"
    "TEUsCiAgICAgICAgICAgICJKT1VSTkFMIjogICAgQ19TSUxWRVIsCiAgICAgICAgICAgICJQT0ki"
    "OiAgICAgICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAgIlNZU1RFTSI6ICAgICBDX1RFWFRfRElN"
    "LAogICAgICAgIH0KICAgICAgICBjb2xvciA9IGNvbG9ycy5nZXQobGFiZWwudXBwZXIoKSwgQ19H"
    "T0xEKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0"
    "eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICBm"
    "J1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6"
    "e2NvbG9yfTsgZm9udC13ZWlnaHQ6Ym9sZDsiPicKICAgICAgICAgICAgZifinacge2xhYmVsfTwv"
    "c3Bhbj48YnI+JwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19HT0xEfTsiPnt0"
    "ZXh0fTwvc3Bhbj4nCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKCIiKQog"
    "ICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAg"
    "ICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQogICAgICAg"
    "ICkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kaXNwbGF5LmNs"
    "ZWFyKCkKCgojIOKUgOKUgCBESUFHTk9TVElDUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIERpYWdub3N0aWNz"
    "VGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBCYWNrZW5kIGRpYWdub3N0aWNzIGRpc3BsYXkuCiAg"
    "ICBSZWNlaXZlczogaGFyZHdhcmUgZGV0ZWN0aW9uIHJlc3VsdHMsIGRlcGVuZGVuY3kgY2hlY2sg"
    "cmVzdWx0cywKICAgICAgICAgICAgICBBUEkgZXJyb3JzLCBzeW5jIGZhaWx1cmVzLCB0aW1lciBl"
    "dmVudHMsIGpvdXJuYWwgbG9hZCBub3RpY2VzLAogICAgICAgICAgICAgIG1vZGVsIGxvYWQgc3Rh"
    "dHVzLCBHb29nbGUgYXV0aCBldmVudHMuCiAgICBBbHdheXMgc2VwYXJhdGUgZnJvbSBwZXJzb25h"
    "IGNoYXQgdGFiLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToK"
    "ICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICByb290ID0gUVZCb3hMYXlv"
    "dXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAg"
    "ICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICBoZHIgPSBRSEJveExheW91dCgpCiAgICAg"
    "ICAgaGRyLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBESUFHTk9TVElDUyDigJQgU1lTVEVN"
    "ICYgQkFDS0VORCBMT0ciKSkKICAgICAgICBzZWxmLl9idG5fY2xlYXIgPSBfZ290aGljX2J0bigi"
    "4pyXIENsZWFyIikKICAgICAgICBzZWxmLl9idG5fY2xlYXIuc2V0Rml4ZWRXaWR0aCg4MCkKICAg"
    "ICAgICBzZWxmLl9idG5fY2xlYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYuY2xlYXIpCiAgICAgICAg"
    "aGRyLmFkZFN0cmV0Y2goKQogICAgICAgIGhkci5hZGRXaWRnZXQoc2VsZi5fYnRuX2NsZWFyKQog"
    "ICAgICAgIHJvb3QuYWRkTGF5b3V0KGhkcikKCiAgICAgICAgc2VsZi5fZGlzcGxheSA9IFFUZXh0"
    "RWRpdCgpCiAgICAgICAgc2VsZi5fZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNl"
    "bGYuX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19N"
    "T05JVE9SfTsgY29sb3I6IHtDX1NJTFZFUn07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBz"
    "b2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6ICdDb3VyaWVyIE5l"
    "dycsIG1vbm9zcGFjZTsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTogMTBweDsgcGFkZGluZzog"
    "OHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fZGlzcGxheSwgMSkK"
    "CiAgICBkZWYgbG9nKHNlbGYsIG1lc3NhZ2U6IHN0ciwgbGV2ZWw6IHN0ciA9ICJJTkZPIikgLT4g"
    "Tm9uZToKICAgICAgICB0aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06"
    "JVMiKQogICAgICAgIGxldmVsX2NvbG9ycyA9IHsKICAgICAgICAgICAgIklORk8iOiAgQ19TSUxW"
    "RVIsCiAgICAgICAgICAgICJPSyI6ICAgIENfR1JFRU4sCiAgICAgICAgICAgICJXQVJOIjogIENf"
    "R09MRCwKICAgICAgICAgICAgIkVSUk9SIjogQ19CTE9PRCwKICAgICAgICAgICAgIkRFQlVHIjog"
    "Q19URVhUX0RJTSwKICAgICAgICB9CiAgICAgICAgY29sb3IgPSBsZXZlbF9jb2xvcnMuZ2V0KGxl"
    "dmVsLnVwcGVyKCksIENfU0lMVkVSKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5kKAogICAg"
    "ICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07Ij5be3RpbWVzdGFtcH1d"
    "PC9zcGFuPiAnCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07Ij57bWVz"
    "c2FnZX08L3NwYW4+JwogICAgICAgICkKICAgICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Ny"
    "b2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3Jv"
    "bGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAgZGVmIGxvZ19tYW55KHNlbGYsIG1lc3Nh"
    "Z2VzOiBsaXN0W3N0cl0sIGxldmVsOiBzdHIgPSAiSU5GTyIpIC0+IE5vbmU6CiAgICAgICAgZm9y"
    "IG1zZyBpbiBtZXNzYWdlczoKICAgICAgICAgICAgbHZsID0gbGV2ZWwKICAgICAgICAgICAgaWYg"
    "IuKckyIgaW4gbXNnOiAgICBsdmwgPSAiT0siCiAgICAgICAgICAgIGVsaWYgIuKclyIgaW4gbXNn"
    "OiAgbHZsID0gIldBUk4iCiAgICAgICAgICAgIGVsaWYgIkVSUk9SIiBpbiBtc2cudXBwZXIoKTog"
    "bHZsID0gIkVSUk9SIgogICAgICAgICAgICBzZWxmLmxvZyhtc2csIGx2bCkKCiAgICBkZWYgY2xl"
    "YXIoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9kaXNwbGF5LmNsZWFyKCkKCgojIOKUgOKU"
    "gCBMRVNTT05TIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTGVzc29uc1RhYihRV2lkZ2V0"
    "KToKICAgICIiIgogICAgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGFuZCBjb2RlIGxlc3NvbnMgYnJv"
    "d3Nlci4KICAgIEFkZCwgdmlldywgc2VhcmNoLCBkZWxldGUgbGVzc29ucy4KICAgICIiIgoKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmLCBkYjogIkxlc3NvbnNMZWFybmVkREIiLCBwYXJlbnQ9Tm9uZSk6"
    "CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZGIgPSBkYgog"
    "ICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBf"
    "c2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikK"
    "ICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Qu"
    "c2V0U3BhY2luZyg0KQoKICAgICAgICAjIEZpbHRlciBiYXIKICAgICAgICBmaWx0ZXJfcm93ID0g"
    "UUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX3NlYXJjaCA9IFFMaW5lRWRpdCgpCiAgICAgICAg"
    "c2VsZi5fc2VhcmNoLnNldFBsYWNlaG9sZGVyVGV4dCgiU2VhcmNoIGxlc3NvbnMuLi4iKQogICAg"
    "ICAgIHNlbGYuX2xhbmdfZmlsdGVyID0gUUNvbWJvQm94KCkKICAgICAgICBzZWxmLl9sYW5nX2Zp"
    "bHRlci5hZGRJdGVtcyhbIkFsbCIsICJMU0wiLCAiUHl0aG9uIiwgIlB5U2lkZTYiLAogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIkphdmFTY3JpcHQiLCAiT3RoZXIiXSkKICAg"
    "ICAgICBzZWxmLl9zZWFyY2gudGV4dENoYW5nZWQuY29ubmVjdChzZWxmLnJlZnJlc2gpCiAgICAg"
    "ICAgc2VsZi5fbGFuZ19maWx0ZXIuY3VycmVudFRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5yZWZy"
    "ZXNoKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgiU2VhcmNoOiIpKQogICAg"
    "ICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KHNlbGYuX3NlYXJjaCwgMSkKICAgICAgICBmaWx0ZXJf"
    "cm93LmFkZFdpZGdldChRTGFiZWwoIkxhbmd1YWdlOiIpKQogICAgICAgIGZpbHRlcl9yb3cuYWRk"
    "V2lkZ2V0KHNlbGYuX2xhbmdfZmlsdGVyKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGZpbHRlcl9y"
    "b3cpCgogICAgICAgIGJ0bl9iYXIgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX2FkZCA9IF9n"
    "b3RoaWNfYnRuKCLinKYgQWRkIExlc3NvbiIpCiAgICAgICAgYnRuX2RlbCA9IF9nb3RoaWNfYnRu"
    "KCLinJcgRGVsZXRlIikKICAgICAgICBidG5fYWRkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19h"
    "ZGQpCiAgICAgICAgYnRuX2RlbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAg"
    "ICAgIGJ0bl9iYXIuYWRkV2lkZ2V0KGJ0bl9hZGQpCiAgICAgICAgYnRuX2Jhci5hZGRXaWRnZXQo"
    "YnRuX2RlbCkKICAgICAgICBidG5fYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5"
    "b3V0KGJ0bl9iYXIpCgogICAgICAgIHNlbGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDQpCiAg"
    "ICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscygKICAgICAgICAgICAg"
    "WyJMYW5ndWFnZSIsICJSZWZlcmVuY2UgS2V5IiwgIlN1bW1hcnkiLCAiRW52aXJvbm1lbnQiXQog"
    "ICAgICAgICkKICAgICAgICBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlv"
    "blJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDIsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRj"
    "aCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAgICAgICAg"
    "UUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBz"
    "ZWxmLl90YWJsZS5zZXRBbHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVlKQogICAgICAgIHNlbGYuX3Rh"
    "YmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX3Rh"
    "YmxlLml0ZW1TZWxlY3Rpb25DaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fc2VsZWN0KQoKICAgICAg"
    "ICAjIFVzZSBzcGxpdHRlciBiZXR3ZWVuIHRhYmxlIGFuZCBkZXRhaWwKICAgICAgICBzcGxpdHRl"
    "ciA9IFFTcGxpdHRlcihRdC5PcmllbnRhdGlvbi5WZXJ0aWNhbCkKICAgICAgICBzcGxpdHRlci5h"
    "ZGRXaWRnZXQoc2VsZi5fdGFibGUpCgogICAgICAgICMgRGV0YWlsIHBhbmVsCiAgICAgICAgZGV0"
    "YWlsX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIGRldGFpbF9sYXlvdXQgPSBRVkJveExheW91"
    "dChkZXRhaWxfd2lkZ2V0KQogICAgICAgIGRldGFpbF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5z"
    "KDAsIDQsIDAsIDApCiAgICAgICAgZGV0YWlsX2xheW91dC5zZXRTcGFjaW5nKDIpCgogICAgICAg"
    "IGRldGFpbF9oZWFkZXIgPSBRSEJveExheW91dCgpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRX"
    "aWRnZXQoX3NlY3Rpb25fbGJsKCLinacgRlVMTCBSVUxFIikpCiAgICAgICAgZGV0YWlsX2hlYWRl"
    "ci5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlID0gX2dvdGhpY19idG4o"
    "IkVkaXQiKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Rml4ZWRXaWR0aCg1MCkKICAg"
    "ICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNldENoZWNrYWJsZShUcnVlKQogICAgICAgIHNlbGYu"
    "X2J0bl9lZGl0X3J1bGUudG9nZ2xlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9lZGl0X21vZGUpCiAg"
    "ICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZSA9IF9nb3RoaWNfYnRuKCJTYXZlIikKICAgICAgICBz"
    "ZWxmLl9idG5fc2F2ZV9ydWxlLnNldEZpeGVkV2lkdGgoNTApCiAgICAgICAgc2VsZi5fYnRuX3Nh"
    "dmVfcnVsZS5zZXRWaXNpYmxlKEZhbHNlKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX3NhdmVfcnVsZV9lZGl0KQogICAgICAgIGRldGFpbF9oZWFkZXIu"
    "YWRkV2lkZ2V0KHNlbGYuX2J0bl9lZGl0X3J1bGUpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRX"
    "aWRnZXQoc2VsZi5fYnRuX3NhdmVfcnVsZSkKICAgICAgICBkZXRhaWxfbGF5b3V0LmFkZExheW91"
    "dChkZXRhaWxfaGVhZGVyKQoKICAgICAgICBzZWxmLl9kZXRhaWwgPSBRVGV4dEVkaXQoKQogICAg"
    "ICAgIHNlbGYuX2RldGFpbC5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX2RldGFpbC5z"
    "ZXRNaW5pbXVtSGVpZ2h0KDEyMCkKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAg"
    "ICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYi"
    "Zm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5n"
    "OiA0cHg7IgogICAgICAgICkKICAgICAgICBkZXRhaWxfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9k"
    "ZXRhaWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KGRldGFpbF93aWRnZXQpCiAgICAgICAg"
    "c3BsaXR0ZXIuc2V0U2l6ZXMoWzMwMCwgMTgwXSkKICAgICAgICByb290LmFkZFdpZGdldChzcGxp"
    "dHRlciwgMSkKCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAg"
    "c2VsZi5fZWRpdGluZ19yb3c6IGludCA9IC0xCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICBxICAgID0gc2VsZi5fc2VhcmNoLnRleHQoKQogICAgICAgIGxhbmcgPSBzZWxm"
    "Ll9sYW5nX2ZpbHRlci5jdXJyZW50VGV4dCgpCiAgICAgICAgbGFuZyA9ICIiIGlmIGxhbmcgPT0g"
    "IkFsbCIgZWxzZSBsYW5nCiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHNlbGYuX2RiLnNlYXJjaChx"
    "dWVyeT1xLCBsYW5ndWFnZT1sYW5nKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0NvdW50KDAp"
    "CiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICByID0gc2VsZi5f"
    "dGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAg"
    "ICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAwLAogICAgICAgICAgICAgICAgUVRhYmxl"
    "V2lkZ2V0SXRlbShyZWMuZ2V0KCJsYW5ndWFnZSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fdGFi"
    "bGUuc2V0SXRlbShyLCAxLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0"
    "KCJyZWZlcmVuY2Vfa2V5IiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIs"
    "IDIsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInN1bW1hcnkiLCIi"
    "KSkpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMywKICAgICAgICAgICAgICAg"
    "IFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiZW52aXJvbm1lbnQiLCIiKSkpCgogICAgZGVmIF9v"
    "bl9zZWxlY3Qoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50"
    "Um93KCkKICAgICAgICBzZWxmLl9lZGl0aW5nX3JvdyA9IHJvdwogICAgICAgIGlmIDAgPD0gcm93"
    "IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW3Jv"
    "d10KICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFBsYWluVGV4dCgKICAgICAgICAgICAgICAg"
    "IHJlYy5nZXQoImZ1bGxfcnVsZSIsIiIpICsgIlxuXG4iICsKICAgICAgICAgICAgICAgICgiUmVz"
    "b2x1dGlvbjogIiArIHJlYy5nZXQoInJlc29sdXRpb24iLCIiKSBpZiByZWMuZ2V0KCJyZXNvbHV0"
    "aW9uIikgZWxzZSAiIikKICAgICAgICAgICAgKQogICAgICAgICAgICAjIFJlc2V0IGVkaXQgbW9k"
    "ZSBvbiBuZXcgc2VsZWN0aW9uCiAgICAgICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Q2hl"
    "Y2tlZChGYWxzZSkKCiAgICBkZWYgX3RvZ2dsZV9lZGl0X21vZGUoc2VsZiwgZWRpdGluZzogYm9v"
    "bCkgLT4gTm9uZToKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0UmVhZE9ubHkobm90IGVkaXRpbmcp"
    "CiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRWaXNpYmxlKGVkaXRpbmcpCiAgICAgICAg"
    "c2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRUZXh0KCJDYW5jZWwiIGlmIGVkaXRpbmcgZWxzZSAiRWRp"
    "dCIpCiAgICAgICAgaWYgZWRpdGluZzoKICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19H"
    "T0xEfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEX0RJTX07"
    "ICIKICAgICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9u"
    "dC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToK"
    "ICAgICAgICAgICAgc2VsZi5fZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBm"
    "ImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICAgICAg"
    "ZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgICAgICBmImZvbnQt"
    "ZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4"
    "OyIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIFJlbG9hZCBvcmlnaW5hbCBjb250ZW50IG9u"
    "IGNhbmNlbAogICAgICAgICAgICBzZWxmLl9vbl9zZWxlY3QoKQoKICAgIGRlZiBfc2F2ZV9ydWxl"
    "X2VkaXQoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl9lZGl0aW5nX3JvdwogICAg"
    "ICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICB0ZXh0ID0g"
    "c2VsZi5fZGV0YWlsLnRvUGxhaW5UZXh0KCkuc3RyaXAoKQogICAgICAgICAgICAjIFNwbGl0IHJl"
    "c29sdXRpb24gYmFjayBvdXQgaWYgcHJlc2VudAogICAgICAgICAgICBpZiAiXG5cblJlc29sdXRp"
    "b246ICIgaW4gdGV4dDoKICAgICAgICAgICAgICAgIHBhcnRzID0gdGV4dC5zcGxpdCgiXG5cblJl"
    "c29sdXRpb246ICIsIDEpCiAgICAgICAgICAgICAgICBmdWxsX3J1bGUgID0gcGFydHNbMF0uc3Ry"
    "aXAoKQogICAgICAgICAgICAgICAgcmVzb2x1dGlvbiA9IHBhcnRzWzFdLnN0cmlwKCkKICAgICAg"
    "ICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZSAgPSB0ZXh0CiAgICAgICAgICAg"
    "ICAgICByZXNvbHV0aW9uID0gc2VsZi5fcmVjb3Jkc1tyb3ddLmdldCgicmVzb2x1dGlvbiIsICIi"
    "KQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd11bImZ1bGxfcnVsZSJdICA9IGZ1bGxfcnVs"
    "ZQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jvd11bInJlc29sdXRpb24iXSA9IHJlc29sdXRp"
    "b24KICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fZGIuX3BhdGgsIHNlbGYuX3JlY29yZHMp"
    "CiAgICAgICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Q2hlY2tlZChGYWxzZSkKICAgICAg"
    "ICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkFkZCBM"
    "ZXNzb24iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsg"
    "Y29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAsIDQwMCkKICAgICAgICBm"
    "b3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAgIGVudiAgPSBRTGluZUVkaXQoIkxTTCIpCiAg"
    "ICAgICAgbGFuZyA9IFFMaW5lRWRpdCgiTFNMIikKICAgICAgICByZWYgID0gUUxpbmVFZGl0KCkK"
    "ICAgICAgICBzdW1tID0gUUxpbmVFZGl0KCkKICAgICAgICBydWxlID0gUVRleHRFZGl0KCkKICAg"
    "ICAgICBydWxlLnNldE1heGltdW1IZWlnaHQoMTAwKQogICAgICAgIHJlcyAgPSBRTGluZUVkaXQo"
    "KQogICAgICAgIGxpbmsgPSBRTGluZUVkaXQoKQogICAgICAgIGZvciBsYWJlbCwgdyBpbiBbCiAg"
    "ICAgICAgICAgICgiRW52aXJvbm1lbnQ6IiwgZW52KSwgKCJMYW5ndWFnZToiLCBsYW5nKSwKICAg"
    "ICAgICAgICAgKCJSZWZlcmVuY2UgS2V5OiIsIHJlZiksICgiU3VtbWFyeToiLCBzdW1tKSwKICAg"
    "ICAgICAgICAgKCJGdWxsIFJ1bGU6IiwgcnVsZSksICgiUmVzb2x1dGlvbjoiLCByZXMpLAogICAg"
    "ICAgICAgICAoIkxpbms6IiwgbGluayksCiAgICAgICAgXToKICAgICAgICAgICAgZm9ybS5hZGRS"
    "b3cobGFiZWwsIHcpCiAgICAgICAgYnRucyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBvayA9IF9n"
    "b3RoaWNfYnRuKCJTYXZlIik7IGN4ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgb2su"
    "Y2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpOyBjeC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVj"
    "dCkKICAgICAgICBidG5zLmFkZFdpZGdldChvayk7IGJ0bnMuYWRkV2lkZ2V0KGN4KQogICAgICAg"
    "IGZvcm0uYWRkUm93KGJ0bnMpCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxv"
    "Z0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHNlbGYuX2RiLmFkZCgKICAgICAgICAgICAgICAg"
    "IGVudmlyb25tZW50PWVudi50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGxhbmd1YWdl"
    "PWxhbmcudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICByZWZlcmVuY2Vfa2V5PXJlZi50"
    "ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIHN1bW1hcnk9c3VtbS50ZXh0KCkuc3RyaXAo"
    "KSwKICAgICAgICAgICAgICAgIGZ1bGxfcnVsZT1ydWxlLnRvUGxhaW5UZXh0KCkuc3RyaXAoKSwK"
    "ICAgICAgICAgICAgICAgIHJlc29sdXRpb249cmVzLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAg"
    "ICAgICAgbGluaz1saW5rLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICApCiAgICAgICAgICAg"
    "IHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxldGUoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxl"
    "bihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmVjX2lkID0gc2VsZi5fcmVjb3Jkc1tyb3dd"
    "LmdldCgiaWQiLCIiKQogICAgICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAog"
    "ICAgICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSBMZXNzb24iLAogICAgICAgICAgICAgICAgIkRl"
    "bGV0ZSB0aGlzIGxlc3Nvbj8gQ2Fubm90IGJlIHVuZG9uZS4iLAogICAgICAgICAgICAgICAgUU1l"
    "c3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24u"
    "Tm8KICAgICAgICAgICAgKQogICAgICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFu"
    "ZGFyZEJ1dHRvbi5ZZXM6CiAgICAgICAgICAgICAgICBzZWxmLl9kYi5kZWxldGUocmVjX2lkKQog"
    "ICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCgojIOKUgOKUgCBNT0RVTEUgVFJBQ0tFUiBU"
    "QUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CmNsYXNzIE1vZHVsZVRyYWNrZXJUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIFBlcnNvbmFsIG1v"
    "ZHVsZSBwaXBlbGluZSB0cmFja2VyLgogICAgVHJhY2sgcGxhbm5lZC9pbi1wcm9ncmVzcy9idWls"
    "dCBtb2R1bGVzIGFzIHRoZXkgYXJlIGRlc2lnbmVkLgogICAgRWFjaCBtb2R1bGUgaGFzOiBOYW1l"
    "LCBTdGF0dXMsIERlc2NyaXB0aW9uLCBOb3Rlcy4KICAgIEV4cG9ydCB0byBUWFQgZm9yIHBhc3Rp"
    "bmcgaW50byBzZXNzaW9ucy4KICAgIEltcG9ydDogcGFzdGUgYSBmaW5hbGl6ZWQgc3BlYywgaXQg"
    "cGFyc2VzIG5hbWUgYW5kIGRldGFpbHMuCiAgICBUaGlzIGlzIGEgZGVzaWduIG5vdGVib29rIOKA"
    "lCBub3QgY29ubmVjdGVkIHRvIGRlY2tfYnVpbGRlcidzIE1PRFVMRSByZWdpc3RyeS4KICAgICIi"
    "IgoKICAgIFNUQVRVU0VTID0gWyJJZGVhIiwgIkRlc2lnbmluZyIsICJSZWFkeSB0byBCdWlsZCIs"
    "ICJQYXJ0aWFsIiwgIkJ1aWx0Il0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUp"
    "OgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BhdGggPSBj"
    "ZmdfcGF0aCgibWVtb3JpZXMiKSAvICJtb2R1bGVfdHJhY2tlci5qc29ubCIKICAgICAgICBzZWxm"
    "Ll9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAg"
    "ICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdp"
    "bnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBCdXR0"
    "b24gYmFyCiAgICAgICAgYnRuX2JhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5f"
    "YWRkICAgID0gX2dvdGhpY19idG4oIkFkZCBNb2R1bGUiKQogICAgICAgIHNlbGYuX2J0bl9lZGl0"
    "ICAgPSBfZ290aGljX2J0bigiRWRpdCIpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSA9IF9nb3Ro"
    "aWNfYnRuKCJEZWxldGUiKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQgPSBfZ290aGljX2J0bigi"
    "RXhwb3J0IFRYVCIpCiAgICAgICAgc2VsZi5fYnRuX2ltcG9ydCA9IF9nb3RoaWNfYnRuKCJJbXBv"
    "cnQgU3BlYyIpCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9lZGl0"
    "LCBzZWxmLl9idG5fZGVsZXRlLAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fZXhwb3J0LCBz"
    "ZWxmLl9idG5faW1wb3J0KToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtV2lkdGgoODApCiAgICAg"
    "ICAgICAgIGIuc2V0TWluaW11bUhlaWdodCgyNikKICAgICAgICAgICAgYnRuX2Jhci5hZGRXaWRn"
    "ZXQoYikKICAgICAgICBidG5fYmFyLmFkZFN0cmV0Y2goKQogICAgICAgIHJvb3QuYWRkTGF5b3V0"
    "KGJ0bl9iYXIpCgogICAgICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Rv"
    "X2FkZCkKICAgICAgICBzZWxmLl9idG5fZWRpdC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZWRp"
    "dCkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxl"
    "dGUpCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZXhw"
    "b3J0KQogICAgICAgIHNlbGYuX2J0bl9pbXBvcnQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2lt"
    "cG9ydCkKCiAgICAgICAgIyBUYWJsZQogICAgICAgIHNlbGYuX3RhYmxlID0gUVRhYmxlV2lkZ2V0"
    "KDAsIDMpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIk1v"
    "ZHVsZSBOYW1lIiwgIlN0YXR1cyIsICJEZXNjcmlwdGlvbiJdKQogICAgICAgIGhoID0gc2VsZi5f"
    "dGFibGUuaG9yaXpvbnRhbEhlYWRlcigpCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUo"
    "MCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRD"
    "b2x1bW5XaWR0aCgwLCAxNjApCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMSwgUUhl"
    "YWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5X"
    "aWR0aCgxLCAxMDApCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoMiwgUUhlYWRlclZp"
    "ZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFNlbGVjdGlvbkJl"
    "aGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5T"
    "ZWxlY3RSb3dzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRy"
    "dWUpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxl"
    "KCkpCiAgICAgICAgc2VsZi5fdGFibGUuaXRlbVNlbGVjdGlvbkNoYW5nZWQuY29ubmVjdChzZWxm"
    "Ll9vbl9zZWxlY3QpCgogICAgICAgICMgU3BsaXR0ZXIKICAgICAgICBzcGxpdHRlciA9IFFTcGxp"
    "dHRlcihRdC5PcmllbnRhdGlvbi5WZXJ0aWNhbCkKICAgICAgICBzcGxpdHRlci5hZGRXaWRnZXQo"
    "c2VsZi5fdGFibGUpCgogICAgICAgICMgTm90ZXMgcGFuZWwKICAgICAgICBub3Rlc193aWRnZXQg"
    "PSBRV2lkZ2V0KCkKICAgICAgICBub3Rlc19sYXlvdXQgPSBRVkJveExheW91dChub3Rlc193aWRn"
    "ZXQpCiAgICAgICAgbm90ZXNfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCA0LCAwLCAwKQog"
    "ICAgICAgIG5vdGVzX2xheW91dC5zZXRTcGFjaW5nKDIpCiAgICAgICAgbm90ZXNfbGF5b3V0LmFk"
    "ZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBOT1RFUyIpKQogICAgICAgIHNlbGYuX25vdGVzX2Rp"
    "c3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0UmVhZE9u"
    "bHkoVHJ1ZSkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5LnNldE1pbmltdW1IZWlnaHQoMTIw"
    "KQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6"
    "IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAg"
    "ICAgICkKICAgICAgICBub3Rlc19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX25vdGVzX2Rpc3BsYXkp"
    "CiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KG5vdGVzX3dpZGdldCkKICAgICAgICBzcGxpdHRl"
    "ci5zZXRTaXplcyhbMjUwLCAxNTBdKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNwbGl0dGVyLCAx"
    "KQoKICAgICAgICAjIENvdW50IGxhYmVsCiAgICAgICAgc2VsZi5fY291bnRfbGJsID0gUUxhYmVs"
    "KCIiKQogICAgICAgIHNlbGYuX2NvdW50X2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBm"
    "ImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tf"
    "Rk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fY291"
    "bnRfbGJsKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVj"
    "b3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRSb3dD"
    "b3VudCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgciA9"
    "IHNlbGYuX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93"
    "KHIpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMCwgUVRhYmxlV2lkZ2V0SXRl"
    "bShyZWMuZ2V0KCJuYW1lIiwgIiIpKSkKICAgICAgICAgICAgc3RhdHVzX2l0ZW0gPSBRVGFibGVX"
    "aWRnZXRJdGVtKHJlYy5nZXQoInN0YXR1cyIsICJJZGVhIikpCiAgICAgICAgICAgICMgQ29sb3Ig"
    "Ynkgc3RhdHVzCiAgICAgICAgICAgIHN0YXR1c19jb2xvcnMgPSB7CiAgICAgICAgICAgICAgICAi"
    "SWRlYSI6ICAgICAgICAgICAgIENfVEVYVF9ESU0sCiAgICAgICAgICAgICAgICAiRGVzaWduaW5n"
    "IjogICAgICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgICAgICAiUmVhZHkgdG8gQnVpbGQiOiAg"
    "IENfUFVSUExFLAogICAgICAgICAgICAgICAgIlBhcnRpYWwiOiAgICAgICAgICAiI2NjODg0NCIs"
    "CiAgICAgICAgICAgICAgICAiQnVpbHQiOiAgICAgICAgICAgIENfR1JFRU4sCiAgICAgICAgICAg"
    "IH0KICAgICAgICAgICAgc3RhdHVzX2l0ZW0uc2V0Rm9yZWdyb3VuZCgKICAgICAgICAgICAgICAg"
    "IFFDb2xvcihzdGF0dXNfY29sb3JzLmdldChyZWMuZ2V0KCJzdGF0dXMiLCJJZGVhIiksIENfVEVY"
    "VF9ESU0pKQogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwg"
    "MSwgc3RhdHVzX2l0ZW0pCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMiwKICAg"
    "ICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiZGVzY3JpcHRpb24iLCAiIilb"
    "OjgwXSkpCiAgICAgICAgY291bnRzID0ge30KICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29y"
    "ZHM6CiAgICAgICAgICAgIHMgPSByZWMuZ2V0KCJzdGF0dXMiLCAiSWRlYSIpCiAgICAgICAgICAg"
    "IGNvdW50c1tzXSA9IGNvdW50cy5nZXQocywgMCkgKyAxCiAgICAgICAgY291bnRfc3RyID0gIiAg"
    "Ii5qb2luKGYie3N9OiB7bn0iIGZvciBzLCBuIGluIGNvdW50cy5pdGVtcygpKQogICAgICAgIHNl"
    "bGYuX2NvdW50X2xibC5zZXRUZXh0KAogICAgICAgICAgICBmIlRvdGFsOiB7bGVuKHNlbGYuX3Jl"
    "Y29yZHMpfSAgIHtjb3VudF9zdHJ9IgogICAgICAgICkKCiAgICBkZWYgX29uX3NlbGVjdChzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAg"
    "IGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZWMgPSBzZWxm"
    "Ll9yZWNvcmRzW3Jvd10KICAgICAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheS5zZXRQbGFpblRl"
    "eHQocmVjLmdldCgibm90ZXMiLCAiIikpCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9vcGVuX2VkaXRfZGlhbG9nKCkKCiAgICBkZWYgX2RvX2VkaXQoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBp"
    "ZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgc2VsZi5fb3Blbl9l"
    "ZGl0X2RpYWxvZyhzZWxmLl9yZWNvcmRzW3Jvd10sIHJvdykKCiAgICBkZWYgX29wZW5fZWRpdF9k"
    "aWFsb2coc2VsZiwgcmVjOiBkaWN0ID0gTm9uZSwgcm93OiBpbnQgPSAtMSkgLT4gTm9uZToKICAg"
    "ICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJNb2R1"
    "bGUiIGlmIG5vdCByZWMgZWxzZSBmIkVkaXQ6IHtyZWMuZ2V0KCduYW1lJywnJyl9IikKICAgICAg"
    "ICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xE"
    "fTsiKQogICAgICAgIGRsZy5yZXNpemUoNTQwLCA0NDApCiAgICAgICAgZm9ybSA9IFFWQm94TGF5"
    "b3V0KGRsZykKCiAgICAgICAgbmFtZV9maWVsZCA9IFFMaW5lRWRpdChyZWMuZ2V0KCJuYW1lIiwi"
    "IikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgbmFtZV9maWVsZC5zZXRQbGFjZWhvbGRlclRleHQo"
    "Ik1vZHVsZSBuYW1lIikKCiAgICAgICAgc3RhdHVzX2NvbWJvID0gUUNvbWJvQm94KCkKICAgICAg"
    "ICBzdGF0dXNfY29tYm8uYWRkSXRlbXMoc2VsZi5TVEFUVVNFUykKICAgICAgICBpZiByZWM6CiAg"
    "ICAgICAgICAgIGlkeCA9IHN0YXR1c19jb21iby5maW5kVGV4dChyZWMuZ2V0KCJzdGF0dXMiLCJJ"
    "ZGVhIikpCiAgICAgICAgICAgIGlmIGlkeCA+PSAwOgogICAgICAgICAgICAgICAgc3RhdHVzX2Nv"
    "bWJvLnNldEN1cnJlbnRJbmRleChpZHgpCgogICAgICAgIGRlc2NfZmllbGQgPSBRTGluZUVkaXQo"
    "cmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBkZXNjX2Zp"
    "ZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgiT25lLWxpbmUgZGVzY3JpcHRpb24iKQoKICAgICAgICBu"
    "b3Rlc19maWVsZCA9IFFUZXh0RWRpdCgpCiAgICAgICAgbm90ZXNfZmllbGQuc2V0UGxhaW5UZXh0"
    "KHJlYy5nZXQoIm5vdGVzIiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgbm90ZXNfZmllbGQu"
    "c2V0UGxhY2Vob2xkZXJUZXh0KAogICAgICAgICAgICAiRnVsbCBub3RlcyDigJQgc3BlYywgaWRl"
    "YXMsIHJlcXVpcmVtZW50cywgZWRnZSBjYXNlcy4uLiIKICAgICAgICApCiAgICAgICAgbm90ZXNf"
    "ZmllbGQuc2V0TWluaW11bUhlaWdodCgyMDApCgogICAgICAgIGZvciBsYWJlbCwgd2lkZ2V0IGlu"
    "IFsKICAgICAgICAgICAgKCJOYW1lOiIsIG5hbWVfZmllbGQpLAogICAgICAgICAgICAoIlN0YXR1"
    "czoiLCBzdGF0dXNfY29tYm8pLAogICAgICAgICAgICAoIkRlc2NyaXB0aW9uOiIsIGRlc2NfZmll"
    "bGQpLAogICAgICAgICAgICAoIk5vdGVzOiIsIG5vdGVzX2ZpZWxkKSwKICAgICAgICBdOgogICAg"
    "ICAgICAgICByb3dfbGF5b3V0ID0gUUhCb3hMYXlvdXQoKQogICAgICAgICAgICBsYmwgPSBRTGFi"
    "ZWwobGFiZWwpCiAgICAgICAgICAgIGxibC5zZXRGaXhlZFdpZHRoKDkwKQogICAgICAgICAgICBy"
    "b3dfbGF5b3V0LmFkZFdpZGdldChsYmwpCiAgICAgICAgICAgIHJvd19sYXlvdXQuYWRkV2lkZ2V0"
    "KHdpZGdldCkKICAgICAgICAgICAgZm9ybS5hZGRMYXlvdXQocm93X2xheW91dCkKCiAgICAgICAg"
    "YnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fc2F2ZSAgID0gX2dvdGhpY19idG4o"
    "IlNhdmUiKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAg"
    "ICBidG5fc2F2ZS5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCkKICAgICAgICBidG5fY2FuY2Vs"
    "LmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0"
    "bl9zYXZlKQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgZm9y"
    "bS5hZGRMYXlvdXQoYnRuX3JvdykKCiAgICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRp"
    "YWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIG5ld19yZWMgPSB7CiAgICAgICAgICAgICAg"
    "ICAiaWQiOiAgICAgICAgICByZWMuZ2V0KCJpZCIsIHN0cih1dWlkLnV1aWQ0KCkpKSBpZiByZWMg"
    "ZWxzZSBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgICAgICJuYW1lIjogICAgICAgIG5h"
    "bWVfZmllbGQudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAic3RhdHVzIjogICAgICBz"
    "dGF0dXNfY29tYm8uY3VycmVudFRleHQoKSwKICAgICAgICAgICAgICAgICJkZXNjcmlwdGlvbiI6"
    "IGRlc2NfZmllbGQudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAg"
    "ICBub3Rlc19maWVsZC50b1BsYWluVGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAiY3Jl"
    "YXRlZCI6ICAgICByZWMuZ2V0KCJjcmVhdGVkIiwgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCkp"
    "IGlmIHJlYyBlbHNlIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICAgICAg"
    "Im1vZGlmaWVkIjogICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAgICAgICAgIH0K"
    "ICAgICAgICAgICAgaWYgcm93ID49IDA6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW3Jv"
    "d10gPSBuZXdfcmVjCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNv"
    "cmRzLmFwcGVuZChuZXdfcmVjKQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBz"
    "ZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVs"
    "ZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygp"
    "CiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIG5h"
    "bWUgPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJuYW1lIiwidGhpcyBtb2R1bGUiKQogICAgICAg"
    "ICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwg"
    "IkRlbGV0ZSBNb2R1bGUiLAogICAgICAgICAgICAgICAgZiJEZWxldGUgJ3tuYW1lfSc/IENhbm5v"
    "dCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9u"
    "LlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAg"
    "ICAgICAgICAgc2VsZi5fcmVjb3Jkcy5wb3Aocm93KQogICAgICAgICAgICAgICAgd3JpdGVfanNv"
    "bmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgICAgIHNlbGYucmVmcmVz"
    "aCgpCgogICAgZGVmIF9kb19leHBvcnQoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIGV4cG9ydF9kaXIgPSBjZmdfcGF0aCgiZXhwb3J0cyIpCiAgICAgICAgICAgIGV4cG9y"
    "dF9kaXIubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICB0cyA9"
    "IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlWSVtJWRfJUglTSVTIikKICAgICAgICAgICAgb3V0"
    "X3BhdGggPSBleHBvcnRfZGlyIC8gZiJtb2R1bGVzX3t0c30udHh0IgogICAgICAgICAgICBsaW5l"
    "cyA9IFsKICAgICAgICAgICAgICAgICJFQ0hPIERFQ0sg4oCUIE1PRFVMRSBUUkFDS0VSIEVYUE9S"
    "VCIsCiAgICAgICAgICAgICAgICBmIkV4cG9ydGVkOiB7ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUo"
    "JyVZLSVtLSVkICVIOiVNOiVTJyl9IiwKICAgICAgICAgICAgICAgIGYiVG90YWwgbW9kdWxlczog"
    "e2xlbihzZWxmLl9yZWNvcmRzKX0iLAogICAgICAgICAgICAgICAgIj0iICogNjAsCiAgICAgICAg"
    "ICAgICAgICAiIiwKICAgICAgICAgICAgXQogICAgICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3Jl"
    "Y29yZHM6CiAgICAgICAgICAgICAgICBsaW5lcy5leHRlbmQoWwogICAgICAgICAgICAgICAgICAg"
    "IGYiTU9EVUxFOiB7cmVjLmdldCgnbmFtZScsJycpfSIsCiAgICAgICAgICAgICAgICAgICAgZiJT"
    "dGF0dXM6IHtyZWMuZ2V0KCdzdGF0dXMnLCcnKX0iLAogICAgICAgICAgICAgICAgICAgIGYiRGVz"
    "Y3JpcHRpb246IHtyZWMuZ2V0KCdkZXNjcmlwdGlvbicsJycpfSIsCiAgICAgICAgICAgICAgICAg"
    "ICAgIiIsCiAgICAgICAgICAgICAgICAgICAgIk5vdGVzOiIsCiAgICAgICAgICAgICAgICAgICAg"
    "cmVjLmdldCgibm90ZXMiLCIiKSwKICAgICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAg"
    "ICAgICAgICAiLSIgKiA0MCwKICAgICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgICAg"
    "IF0pCiAgICAgICAgICAgIG91dF9wYXRoLndyaXRlX3RleHQoIlxuIi5qb2luKGxpbmVzKSwgZW5j"
    "b2Rpbmc9InV0Zi04IikKICAgICAgICAgICAgUUFwcGxpY2F0aW9uLmNsaXBib2FyZCgpLnNldFRl"
    "eHQoIlxuIi5qb2luKGxpbmVzKSkKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24o"
    "CiAgICAgICAgICAgICAgICBzZWxmLCAiRXhwb3J0ZWQiLAogICAgICAgICAgICAgICAgZiJNb2R1"
    "bGUgdHJhY2tlciBleHBvcnRlZCB0bzpcbntvdXRfcGF0aH1cblxuQWxzbyBjb3BpZWQgdG8gY2xp"
    "cGJvYXJkLiIKICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAg"
    "ICAgICAgICAgUU1lc3NhZ2VCb3gud2FybmluZyhzZWxmLCAiRXhwb3J0IEVycm9yIiwgc3RyKGUp"
    "KQoKICAgIGRlZiBfZG9faW1wb3J0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiSW1wb3J0IGEg"
    "bW9kdWxlIHNwZWMgZnJvbSBjbGlwYm9hcmQgb3IgdHlwZWQgdGV4dC4iIiIKICAgICAgICBkbGcg"
    "PSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJJbXBvcnQgTW9kdWxl"
    "IFNwZWMiKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsg"
    "Y29sb3I6IHtDX0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1MDAsIDM0MCkKICAgICAgICBs"
    "YXlvdXQgPSBRVkJveExheW91dChkbGcpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChRTGFiZWwo"
    "CiAgICAgICAgICAgICJQYXN0ZSBhIG1vZHVsZSBzcGVjIGJlbG93LlxuIgogICAgICAgICAgICAi"
    "Rmlyc3QgbGluZSB3aWxsIGJlIHVzZWQgYXMgdGhlIG1vZHVsZSBuYW1lLiIKICAgICAgICApKQog"
    "ICAgICAgIHRleHRfZmllbGQgPSBRVGV4dEVkaXQoKQogICAgICAgIHRleHRfZmllbGQuc2V0UGxh"
    "Y2Vob2xkZXJUZXh0KCJQYXN0ZSBtb2R1bGUgc3BlYyBoZXJlLi4uIikKICAgICAgICBsYXlvdXQu"
    "YWRkV2lkZ2V0KHRleHRfZmllbGQsIDEpCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkK"
    "ICAgICAgICBidG5fb2sgICAgID0gX2dvdGhpY19idG4oIkltcG9ydCIpCiAgICAgICAgYnRuX2Nh"
    "bmNlbCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIGJ0bl9vay5jbGlja2VkLmNvbm5l"
    "Y3QoZGxnLmFjY2VwdCkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChkbGcucmVq"
    "ZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9vaykKICAgICAgICBidG5fcm93LmFk"
    "ZFdpZGdldChidG5fY2FuY2VsKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoYnRuX3JvdykKCiAg"
    "ICAgICAgaWYgZGxnLmV4ZWMoKSA9PSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAg"
    "ICAgICAgIHJhdyA9IHRleHRfZmllbGQudG9QbGFpblRleHQoKS5zdHJpcCgpCiAgICAgICAgICAg"
    "IGlmIG5vdCByYXc6CiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICAgICAgbGluZXMgPSBy"
    "YXcuc3BsaXRsaW5lcygpCiAgICAgICAgICAgICMgRmlyc3Qgbm9uLWVtcHR5IGxpbmUgPSBuYW1l"
    "CiAgICAgICAgICAgIG5hbWUgPSAiIgogICAgICAgICAgICBmb3IgbGluZSBpbiBsaW5lczoKICAg"
    "ICAgICAgICAgICAgIGlmIGxpbmUuc3RyaXAoKToKICAgICAgICAgICAgICAgICAgICBuYW1lID0g"
    "bGluZS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgbmV3X3Jl"
    "YyA9IHsKICAgICAgICAgICAgICAgICJpZCI6ICAgICAgICAgIHN0cih1dWlkLnV1aWQ0KCkpLAog"
    "ICAgICAgICAgICAgICAgIm5hbWUiOiAgICAgICAgbmFtZVs6NjBdLAogICAgICAgICAgICAgICAg"
    "InN0YXR1cyI6ICAgICAgIklkZWEiLAogICAgICAgICAgICAgICAgImRlc2NyaXB0aW9uIjogIiIs"
    "CiAgICAgICAgICAgICAgICAibm90ZXMiOiAgICAgICByYXcsCiAgICAgICAgICAgICAgICAiY3Jl"
    "YXRlZCI6ICAgICBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgICAgICJt"
    "b2RpZmllZCI6ICAgIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAgICB9CiAg"
    "ICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKG5ld19yZWMpCiAgICAgICAgICAgIHdyaXRl"
    "X2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVz"
    "aCgpCgoKIyDilIDilIAgUEFTUyA1IENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEFsbCB0YWIgY29udGVu"
    "dCBjbGFzc2VzIGRlZmluZWQuCiMgU0xTY2Fuc1RhYjogcmVidWlsdCDigJQgRGVsZXRlIGFkZGVk"
    "LCBNb2RpZnkgZml4ZWQsIHRpbWVzdGFtcCBwYXJzZXIgZml4ZWQsCiMgICAgICAgICAgICAgY2Fy"
    "ZC9ncmltb2lyZSBzdHlsZSwgY29weS10by1jbGlwYm9hcmQgY29udGV4dCBtZW51LgojIFNMQ29t"
    "bWFuZHNUYWI6IGdvdGhpYyB0YWJsZSwg4qeJIENvcHkgQ29tbWFuZCBidXR0b24uCiMgSm9iVHJh"
    "Y2tlclRhYjogZnVsbCByZWJ1aWxkIOKAlCBtdWx0aS1zZWxlY3QsIGFyY2hpdmUvcmVzdG9yZSwg"
    "Q1NWL1RTViBleHBvcnQuCiMgU2VsZlRhYjogaW5uZXIgc2FuY3R1bSBmb3IgaWRsZSBuYXJyYXRp"
    "dmUgYW5kIHJlZmxlY3Rpb24gb3V0cHV0LgojIERpYWdub3N0aWNzVGFiOiBzdHJ1Y3R1cmVkIGxv"
    "ZyB3aXRoIGxldmVsLWNvbG9yZWQgb3V0cHV0LgojIExlc3NvbnNUYWI6IExTTCBGb3JiaWRkZW4g"
    "UnVsZXNldCBicm93c2VyIHdpdGggYWRkL2RlbGV0ZS9zZWFyY2guCiMKIyBOZXh0OiBQYXNzIDYg"
    "4oCUIE1haW4gV2luZG93CiMgKE1vcmdhbm5hRGVjayBjbGFzcywgZnVsbCBsYXlvdXQsIEFQU2No"
    "ZWR1bGVyLCBmaXJzdC1ydW4gZmxvdywKIyAgZGVwZW5kZW5jeSBib290c3RyYXAsIHNob3J0Y3V0"
    "IGNyZWF0aW9uLCBzdGFydHVwIHNlcXVlbmNlKQoKCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCiMgTU9SR0FOTkEgREVD"
    "SyDigJQgUEFTUyA2OiBNQUlOIFdJTkRPVyAmIEVOVFJZIFBPSU5UCiMKIyBDb250YWluczoKIyAg"
    "IGJvb3RzdHJhcF9jaGVjaygpICAgICDigJQgZGVwZW5kZW5jeSB2YWxpZGF0aW9uICsgYXV0by1p"
    "bnN0YWxsIGJlZm9yZSBVSQojICAgRmlyc3RSdW5EaWFsb2cgICAgICAgIOKAlCBtb2RlbCBwYXRo"
    "ICsgY29ubmVjdGlvbiB0eXBlIHNlbGVjdGlvbgojICAgSm91cm5hbFNpZGViYXIgICAgICAgIOKA"
    "lCBjb2xsYXBzaWJsZSBsZWZ0IHNpZGViYXIgKHNlc3Npb24gYnJvd3NlciArIGpvdXJuYWwpCiMg"
    "ICBUb3Jwb3JQYW5lbCAgICAgICAgICAg4oCUIEFXQUtFIC8gQVVUTyAvIFNVU1BFTkQgc3RhdGUg"
    "dG9nZ2xlCiMgICBNb3JnYW5uYURlY2sgICAgICAgICAg4oCUIG1haW4gd2luZG93LCBmdWxsIGxh"
    "eW91dCwgYWxsIHNpZ25hbCBjb25uZWN0aW9ucwojICAgbWFpbigpICAgICAgICAgICAgICAgIOKA"
    "lCBlbnRyeSBwb2ludCB3aXRoIGJvb3RzdHJhcCBzZXF1ZW5jZQojIOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0"
    "IHN1YnByb2Nlc3MKCgojIOKUgOKUgCBQUkUtTEFVTkNIIERFUEVOREVOQ1kgQk9PVFNUUkFQIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgApkZWYgYm9vdHN0cmFwX2NoZWNrKCkgLT4gTm9uZToKICAgICIiIgogICAgUnVu"
    "cyBCRUZPUkUgUUFwcGxpY2F0aW9uIGlzIGNyZWF0ZWQuCiAgICBDaGVja3MgZm9yIFB5U2lkZTYg"
    "c2VwYXJhdGVseSAoY2FuJ3Qgc2hvdyBHVUkgd2l0aG91dCBpdCkuCiAgICBBdXRvLWluc3RhbGxz"
    "IGFsbCBvdGhlciBtaXNzaW5nIG5vbi1jcml0aWNhbCBkZXBzIHZpYSBwaXAuCiAgICBWYWxpZGF0"
    "ZXMgaW5zdGFsbHMgc3VjY2VlZGVkLgogICAgV3JpdGVzIHJlc3VsdHMgdG8gYSBib290c3RyYXAg"
    "bG9nIGZvciBEaWFnbm9zdGljcyB0YWIgdG8gcGljayB1cC4KICAgICIiIgogICAgIyDilIDilIAg"
    "U3RlcCAxOiBDaGVjayBQeVNpZGU2IChjYW4ndCBhdXRvLWluc3RhbGwgd2l0aG91dCBpdCBhbHJl"
    "YWR5IHByZXNlbnQpIOKUgAogICAgdHJ5OgogICAgICAgIGltcG9ydCBQeVNpZGU2ICAjIG5vcWEK"
    "ICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAjIE5vIEdVSSBhdmFpbGFibGUg4oCUIHVz"
    "ZSBXaW5kb3dzIG5hdGl2ZSBkaWFsb2cgdmlhIGN0eXBlcwogICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgaW1wb3J0IGN0eXBlcwogICAgICAgICAgICBjdHlwZXMud2luZGxsLnVzZXIzMi5NZXNzYWdl"
    "Qm94VygKICAgICAgICAgICAgICAgIDAsCiAgICAgICAgICAgICAgICAiUHlTaWRlNiBpcyByZXF1"
    "aXJlZCBidXQgbm90IGluc3RhbGxlZC5cblxuIgogICAgICAgICAgICAgICAgIk9wZW4gYSB0ZXJt"
    "aW5hbCBhbmQgcnVuOlxuXG4iCiAgICAgICAgICAgICAgICAiICAgIHBpcCBpbnN0YWxsIFB5U2lk"
    "ZTZcblxuIgogICAgICAgICAgICAgICAgZiJUaGVuIHJlc3RhcnQge0RFQ0tfTkFNRX0uIiwKICAg"
    "ICAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0g4oCUIE1pc3NpbmcgRGVwZW5kZW5jeSIsCiAgICAg"
    "ICAgICAgICAgICAweDEwICAjIE1CX0lDT05FUlJPUgogICAgICAgICAgICApCiAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcHJpbnQoIkNSSVRJQ0FMOiBQeVNpZGU2IG5vdCBp"
    "bnN0YWxsZWQuIFJ1bjogcGlwIGluc3RhbGwgUHlTaWRlNiIpCiAgICAgICAgc3lzLmV4aXQoMSkK"
    "CiAgICAjIOKUgOKUgCBTdGVwIDI6IEF1dG8taW5zdGFsbCBvdGhlciBtaXNzaW5nIGRlcHMg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBfQVVUT19JTlNUQUxMID0g"
    "WwogICAgICAgICgiYXBzY2hlZHVsZXIiLCAgICAgICAgICAgICAgICJhcHNjaGVkdWxlciIpLAog"
    "ICAgICAgICgibG9ndXJ1IiwgICAgICAgICAgICAgICAgICAgICJsb2d1cnUiKSwKICAgICAgICAo"
    "InB5Z2FtZSIsICAgICAgICAgICAgICAgICAgICAicHlnYW1lIiksCiAgICAgICAgKCJweXdpbjMy"
    "IiwgICAgICAgICAgICAgICAgICAgInB5d2luMzIiKSwKICAgICAgICAoInBzdXRpbCIsICAgICAg"
    "ICAgICAgICAgICAgICAicHN1dGlsIiksCiAgICAgICAgKCJyZXF1ZXN0cyIsICAgICAgICAgICAg"
    "ICAgICAgInJlcXVlc3RzIiksCiAgICAgICAgKCJnb29nbGUtYXBpLXB5dGhvbi1jbGllbnQiLCAg"
    "Imdvb2dsZWFwaWNsaWVudCIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgtb2F1dGhsaWIiLCAgICAg"
    "ICJnb29nbGVfYXV0aF9vYXV0aGxpYiIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgiLCAgICAgICAg"
    "ICAgICAgICJnb29nbGUuYXV0aCIpLAogICAgXQoKICAgIGltcG9ydCBpbXBvcnRsaWIKICAgIGJv"
    "b3RzdHJhcF9sb2cgPSBbXQoKICAgIGZvciBwaXBfbmFtZSwgaW1wb3J0X25hbWUgaW4gX0FVVE9f"
    "SU5TVEFMTDoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxl"
    "KGltcG9ydF9uYW1lKQogICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZChmIltCT09UU1RS"
    "QVBdIHtwaXBfbmFtZX0g4pyTIikKICAgICAgICBleGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAg"
    "ICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7"
    "cGlwX25hbWV9IG1pc3Npbmcg4oCUIGluc3RhbGxpbmcuLi4iCiAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICAgICAgcmVzdWx0ID0gc3VicHJvY2Vzcy5ydW4oCiAgICAg"
    "ICAgICAgICAgICAgICAgW3N5cy5leGVjdXRhYmxlLCAiLW0iLCAicGlwIiwgImluc3RhbGwiLAog"
    "ICAgICAgICAgICAgICAgICAgICBwaXBfbmFtZSwgIi0tcXVpZXQiLCAiLS1uby13YXJuLXNjcmlw"
    "dC1sb2NhdGlvbiJdLAogICAgICAgICAgICAgICAgICAgIGNhcHR1cmVfb3V0cHV0PVRydWUsIHRl"
    "eHQ9VHJ1ZSwgdGltZW91dD0xMjAKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGlm"
    "IHJlc3VsdC5yZXR1cm5jb2RlID09IDA6CiAgICAgICAgICAgICAgICAgICAgIyBWYWxpZGF0ZSBp"
    "dCBhY3R1YWxseSBpbXBvcnRlZCBub3cKICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9ydF9uYW1lKQogICAg"
    "ICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsZWQg4pyTIgogICAg"
    "ICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgZXhjZXB0IEltcG9ydEVy"
    "cm9yOgogICAgICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsIGFw"
    "cGVhcmVkIHRvICIKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYic3VjY2VlZCBidXQgaW1w"
    "b3J0IHN0aWxsIGZhaWxzIOKAlCByZXN0YXJ0IG1heSAiCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICBmImJlIHJlcXVpcmVkLiIKICAgICAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3RhbGwgZmFp"
    "bGVkOiAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYie3Jlc3VsdC5zdGRlcnJbOjIwMF19Igog"
    "ICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhjZXB0IHN1YnByb2Nlc3MuVGltZW91"
    "dEV4cGlyZWQ6CiAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAg"
    "ICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbCB0aW1lZCBvdXQuIgog"
    "ICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAg"
    "ICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltC"
    "T09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbCBlcnJvcjoge2V9IgogICAgICAgICAgICAgICAg"
    "KQoKICAgICMg4pSA4pSAIFN0ZXAgMzogV3JpdGUgYm9vdHN0cmFwIGxvZyBmb3IgRGlhZ25vc3Rp"
    "Y3MgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgdHJ5OgogICAgICAgIGxvZ19wYXRoID0gU0NSSVBUX0RJ"
    "UiAvICJsb2dzIiAvICJib290c3RyYXBfbG9nLnR4dCIKICAgICAgICB3aXRoIGxvZ19wYXRoLm9w"
    "ZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICBmLndyaXRlKCJcbiIu"
    "am9pbihib290c3RyYXBfbG9nKSkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcGFzcwoK"
    "CiMg4pSA4pSAIEZJUlNUIFJVTiBESUFMT0cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEZpcnN0UnVuRGlhbG9nKFFEaWFs"
    "b2cpOgogICAgIiIiCiAgICBTaG93biBvbiBmaXJzdCBsYXVuY2ggd2hlbiBjb25maWcuanNvbiBk"
    "b2Vzbid0IGV4aXN0LgogICAgQ29sbGVjdHMgbW9kZWwgY29ubmVjdGlvbiB0eXBlIGFuZCBwYXRo"
    "L2tleS4KICAgIFZhbGlkYXRlcyBjb25uZWN0aW9uIGJlZm9yZSBhY2NlcHRpbmcuCiAgICBXcml0"
    "ZXMgY29uZmlnLmpzb24gb24gc3VjY2Vzcy4KICAgIENyZWF0ZXMgZGVza3RvcCBzaG9ydGN1dC4K"
    "ICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3Vw"
    "ZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5zZXRXaW5kb3dUaXRsZShmIuKcpiB7"
    "REVDS19OQU1FLnVwcGVyKCl9IOKAlCBGSVJTVCBBV0FLRU5JTkciKQogICAgICAgIHNlbGYuc2V0"
    "U3R5bGVTaGVldChTVFlMRSkKICAgICAgICBzZWxmLnNldEZpeGVkU2l6ZSg1MjAsIDQwMCkKICAg"
    "ICAgICBzZWxmLl9zZXR1cF91aSgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0U3BhY2luZygx"
    "MCkKCiAgICAgICAgdGl0bGUgPSBRTGFiZWwoZiLinKYge0RFQ0tfTkFNRS51cHBlcigpfSDigJQg"
    "RklSU1QgQVdBS0VOSU5HIOKcpiIpCiAgICAgICAgdGl0bGUuc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTRweDsgZm9udC13ZWlnaHQ6"
    "IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBs"
    "ZXR0ZXItc3BhY2luZzogMnB4OyIKICAgICAgICApCiAgICAgICAgdGl0bGUuc2V0QWxpZ25tZW50"
    "KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQodGl0"
    "bGUpCgogICAgICAgIHN1YiA9IFFMYWJlbCgKICAgICAgICAgICAgZiJDb25maWd1cmUgdGhlIHZl"
    "c3NlbCBiZWZvcmUge0RFQ0tfTkFNRX0gbWF5IGF3YWtlbi5cbiIKICAgICAgICAgICAgIkFsbCBz"
    "ZXR0aW5ncyBhcmUgc3RvcmVkIGxvY2FsbHkuIE5vdGhpbmcgbGVhdmVzIHRoaXMgbWFjaGluZS4i"
    "CiAgICAgICAgKQogICAgICAgIHN1Yi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9y"
    "OiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgIgogICAgICAgICAgICBmImZvbnQtZmFt"
    "aWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBzdWIuc2V0QWxpZ25t"
    "ZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQo"
    "c3ViKQoKICAgICAgICAjIOKUgOKUgCBDb25uZWN0aW9uIHR5cGUg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgcm9vdC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgQUkgQ09OTkVDVElPTiBU"
    "WVBFIikpCiAgICAgICAgc2VsZi5fdHlwZV9jb21ibyA9IFFDb21ib0JveCgpCiAgICAgICAgc2Vs"
    "Zi5fdHlwZV9jb21iby5hZGRJdGVtcyhbCiAgICAgICAgICAgICJMb2NhbCBtb2RlbCBmb2xkZXIg"
    "KHRyYW5zZm9ybWVycykiLAogICAgICAgICAgICAiT2xsYW1hIChsb2NhbCBzZXJ2aWNlKSIsCiAg"
    "ICAgICAgICAgICJDbGF1ZGUgQVBJIChBbnRocm9waWMpIiwKICAgICAgICAgICAgIk9wZW5BSSBB"
    "UEkiLAogICAgICAgIF0pCiAgICAgICAgc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXhDaGFu"
    "Z2VkLmNvbm5lY3Qoc2VsZi5fb25fdHlwZV9jaGFuZ2UpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQo"
    "c2VsZi5fdHlwZV9jb21ibykKCiAgICAgICAgIyDilIDilIAgRHluYW1pYyBjb25uZWN0aW9uIGZp"
    "ZWxkcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAg"
    "ICBzZWxmLl9zdGFjayA9IFFTdGFja2VkV2lkZ2V0KCkKCiAgICAgICAgIyBQYWdlIDA6IExvY2Fs"
    "IHBhdGgKICAgICAgICBwMCA9IFFXaWRnZXQoKQogICAgICAgIGwwID0gUUhCb3hMYXlvdXQocDAp"
    "CiAgICAgICAgbDAuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fbG9j"
    "YWxfcGF0aCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fbG9jYWxfcGF0aC5zZXRQbGFjZWhv"
    "bGRlclRleHQoCiAgICAgICAgICAgIHIiRDpcQUlcTW9kZWxzXGRvbHBoaW4tOGIiCiAgICAgICAg"
    "KQogICAgICAgIGJ0bl9icm93c2UgPSBfZ290aGljX2J0bigiQnJvd3NlIikKICAgICAgICBidG5f"
    "YnJvd3NlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9icm93c2VfbW9kZWwpCiAgICAgICAgbDAuYWRk"
    "V2lkZ2V0KHNlbGYuX2xvY2FsX3BhdGgpOyBsMC5hZGRXaWRnZXQoYnRuX2Jyb3dzZSkKICAgICAg"
    "ICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDApCgogICAgICAgICMgUGFnZSAxOiBPbGxhbWEgbW9k"
    "ZWwgbmFtZQogICAgICAgIHAxID0gUVdpZGdldCgpCiAgICAgICAgbDEgPSBRSEJveExheW91dChw"
    "MSkKICAgICAgICBsMS5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAsMCkKICAgICAgICBzZWxmLl9v"
    "bGxhbWFfbW9kZWwgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX29sbGFtYV9tb2RlbC5zZXRQ"
    "bGFjZWhvbGRlclRleHQoImRvbHBoaW4tMi42LTdiIikKICAgICAgICBsMS5hZGRXaWRnZXQoc2Vs"
    "Zi5fb2xsYW1hX21vZGVsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMSkKCiAgICAg"
    "ICAgIyBQYWdlIDI6IENsYXVkZSBBUEkga2V5CiAgICAgICAgcDIgPSBRV2lkZ2V0KCkKICAgICAg"
    "ICBsMiA9IFFWQm94TGF5b3V0KHAyKQogICAgICAgIGwyLnNldENvbnRlbnRzTWFyZ2lucygwLDAs"
    "MCwwKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkgICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2Vs"
    "Zi5fY2xhdWRlX2tleS5zZXRQbGFjZWhvbGRlclRleHQoInNrLWFudC0uLi4iKQogICAgICAgIHNl"
    "bGYuX2NsYXVkZV9rZXkuc2V0RWNob01vZGUoUUxpbmVFZGl0LkVjaG9Nb2RlLlBhc3N3b3JkKQog"
    "ICAgICAgIHNlbGYuX2NsYXVkZV9tb2RlbCA9IFFMaW5lRWRpdCgiY2xhdWRlLXNvbm5ldC00LTYi"
    "KQogICAgICAgIGwyLmFkZFdpZGdldChRTGFiZWwoIkFQSSBLZXk6IikpCiAgICAgICAgbDIuYWRk"
    "V2lkZ2V0KHNlbGYuX2NsYXVkZV9rZXkpCiAgICAgICAgbDIuYWRkV2lkZ2V0KFFMYWJlbCgiTW9k"
    "ZWw6IikpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2NsYXVkZV9tb2RlbCkKICAgICAgICBz"
    "ZWxmLl9zdGFjay5hZGRXaWRnZXQocDIpCgogICAgICAgICMgUGFnZSAzOiBPcGVuQUkKICAgICAg"
    "ICBwMyA9IFFXaWRnZXQoKQogICAgICAgIGwzID0gUVZCb3hMYXlvdXQocDMpCiAgICAgICAgbDMu"
    "c2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAgc2VsZi5fb2FpX2tleSAgID0gUUxp"
    "bmVFZGl0KCkKICAgICAgICBzZWxmLl9vYWlfa2V5LnNldFBsYWNlaG9sZGVyVGV4dCgic2stLi4u"
    "IikKICAgICAgICBzZWxmLl9vYWlfa2V5LnNldEVjaG9Nb2RlKFFMaW5lRWRpdC5FY2hvTW9kZS5Q"
    "YXNzd29yZCkKICAgICAgICBzZWxmLl9vYWlfbW9kZWwgPSBRTGluZUVkaXQoImdwdC00byIpCiAg"
    "ICAgICAgbDMuYWRkV2lkZ2V0KFFMYWJlbCgiQVBJIEtleToiKSkKICAgICAgICBsMy5hZGRXaWRn"
    "ZXQoc2VsZi5fb2FpX2tleSkKICAgICAgICBsMy5hZGRXaWRnZXQoUUxhYmVsKCJNb2RlbDoiKSkK"
    "ICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fb2FpX21vZGVsKQogICAgICAgIHNlbGYuX3N0YWNr"
    "LmFkZFdpZGdldChwMykKCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fc3RhY2spCgogICAg"
    "ICAgICMg4pSA4pSAIFRlc3QgKyBzdGF0dXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgdGVzdF9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX3Rlc3QgPSBfZ290"
    "aGljX2J0bigiVGVzdCBDb25uZWN0aW9uIikKICAgICAgICBzZWxmLl9idG5fdGVzdC5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fdGVzdF9jb25uZWN0aW9uKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwg"
    "PSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgIgogICAgICAg"
    "ICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAg"
    "ICB0ZXN0X3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX3Rlc3QpCiAgICAgICAgdGVzdF9yb3cuYWRk"
    "V2lkZ2V0KHNlbGYuX3N0YXR1c19sYmwsIDEpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQodGVzdF9y"
    "b3cpCgogICAgICAgICMg4pSA4pSAIEZhY2UgUGFjayDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKICAgICAgICByb290LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBGQUNF"
    "IFBBQ0sgKG9wdGlvbmFsIOKAlCBaSVAgZmlsZSkiKSkKICAgICAgICBmYWNlX3JvdyA9IFFIQm94"
    "TGF5b3V0KCkKICAgICAgICBzZWxmLl9mYWNlX3BhdGggPSBRTGluZUVkaXQoKQogICAgICAgIHNl"
    "bGYuX2ZhY2VfcGF0aC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgIGYiQnJvd3NlIHRv"
    "IHtERUNLX05BTUV9IGZhY2UgcGFjayBaSVAgKG9wdGlvbmFsLCBjYW4gYWRkIGxhdGVyKSIKICAg"
    "ICAgICApCiAgICAgICAgc2VsZi5fZmFjZV9wYXRoLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAg"
    "ICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsgIgog"
    "ICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTog"
    "MTJweDsgcGFkZGluZzogNnB4IDEwcHg7IgogICAgICAgICkKICAgICAgICBidG5fZmFjZSA9IF9n"
    "b3RoaWNfYnRuKCJCcm93c2UiKQogICAgICAgIGJ0bl9mYWNlLmNsaWNrZWQuY29ubmVjdChzZWxm"
    "Ll9icm93c2VfZmFjZSkKICAgICAgICBmYWNlX3Jvdy5hZGRXaWRnZXQoc2VsZi5fZmFjZV9wYXRo"
    "KQogICAgICAgIGZhY2Vfcm93LmFkZFdpZGdldChidG5fZmFjZSkKICAgICAgICByb290LmFkZExh"
    "eW91dChmYWNlX3JvdykKCiAgICAgICAgIyDilIDilIAgU2hvcnRjdXQgb3B0aW9uIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3Nob3J0Y3V0X2NiID0gUUNoZWNrQm94KAogICAgICAg"
    "ICAgICAiQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgKHJlY29tbWVuZGVkKSIKICAgICAgICApCiAg"
    "ICAgICAgc2VsZi5fc2hvcnRjdXRfY2Iuc2V0Q2hlY2tlZChUcnVlKQogICAgICAgIHJvb3QuYWRk"
    "V2lkZ2V0KHNlbGYuX3Nob3J0Y3V0X2NiKQoKICAgICAgICAjIOKUgOKUgCBCdXR0b25zIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHJvb3QuYWRkU3Ry"
    "ZXRjaCgpCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5f"
    "YXdha2VuID0gX2dvdGhpY19idG4oIuKcpiBCRUdJTiBBV0FLRU5JTkciKQogICAgICAgIHNlbGYu"
    "X2J0bl9hd2FrZW4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBidG5fY2FuY2VsID0gX2dvdGhp"
    "Y19idG4oIuKclyBDYW5jZWwiKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uY2xpY2tlZC5jb25u"
    "ZWN0KHNlbGYuYWNjZXB0KQogICAgICAgIGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "cmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9hd2FrZW4pCiAgICAg"
    "ICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICByb290LmFkZExheW91dChi"
    "dG5fcm93KQoKICAgIGRlZiBfb25fdHlwZV9jaGFuZ2Uoc2VsZiwgaWR4OiBpbnQpIC0+IE5vbmU6"
    "CiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4KGlkeCkKICAgICAgICBzZWxmLl9i"
    "dG5fYXdha2VuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRU"
    "ZXh0KCIiKQoKICAgIGRlZiBfYnJvd3NlX21vZGVsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0"
    "aCA9IFFGaWxlRGlhbG9nLmdldEV4aXN0aW5nRGlyZWN0b3J5KAogICAgICAgICAgICBzZWxmLCAi"
    "U2VsZWN0IE1vZGVsIEZvbGRlciIsCiAgICAgICAgICAgIHIiRDpcQUlcTW9kZWxzIgogICAgICAg"
    "ICkKICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICBzZWxmLl9sb2NhbF9wYXRoLnNldFRleHQo"
    "cGF0aCkKCiAgICBkZWYgX2Jyb3dzZV9mYWNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcGF0aCwg"
    "XyA9IFFGaWxlRGlhbG9nLmdldE9wZW5GaWxlTmFtZSgKICAgICAgICAgICAgc2VsZiwgIlNlbGVj"
    "dCBGYWNlIFBhY2sgWklQIiwKICAgICAgICAgICAgc3RyKFBhdGguaG9tZSgpIC8gIkRlc2t0b3Ai"
    "KSwKICAgICAgICAgICAgIlpJUCBGaWxlcyAoKi56aXApIgogICAgICAgICkKICAgICAgICBpZiBw"
    "YXRoOgogICAgICAgICAgICBzZWxmLl9mYWNlX3BhdGguc2V0VGV4dChwYXRoKQoKICAgIEBwcm9w"
    "ZXJ0eQogICAgZGVmIGZhY2VfemlwX3BhdGgoc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVybiBz"
    "ZWxmLl9mYWNlX3BhdGgudGV4dCgpLnN0cmlwKCkKCiAgICBkZWYgX3Rlc3RfY29ubmVjdGlvbihz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0VGV4dCgiVGVzdGluZy4u"
    "LiIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBm"
    "ImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNL"
    "X0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIFFBcHBsaWNhdGlvbi5wcm9jZXNzRXZl"
    "bnRzKCkKCiAgICAgICAgaWR4ID0gc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXgoKQogICAg"
    "ICAgIG9rICA9IEZhbHNlCiAgICAgICAgbXNnID0gIiIKCiAgICAgICAgaWYgaWR4ID09IDA6ICAj"
    "IExvY2FsCiAgICAgICAgICAgIHBhdGggPSBzZWxmLl9sb2NhbF9wYXRoLnRleHQoKS5zdHJpcCgp"
    "CiAgICAgICAgICAgIGlmIHBhdGggYW5kIFBhdGgocGF0aCkuZXhpc3RzKCk6CiAgICAgICAgICAg"
    "ICAgICBvayAgPSBUcnVlCiAgICAgICAgICAgICAgICBtc2cgPSBmIkZvbGRlciBmb3VuZC4gTW9k"
    "ZWwgd2lsbCBsb2FkIG9uIHN0YXJ0dXAuIgogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAg"
    "ICAgbXNnID0gIkZvbGRlciBub3QgZm91bmQuIENoZWNrIHRoZSBwYXRoLiIKCiAgICAgICAgZWxp"
    "ZiBpZHggPT0gMTogICMgT2xsYW1hCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJl"
    "cSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KAogICAgICAgICAgICAgICAgICAgICJodHRwOi8v"
    "bG9jYWxob3N0OjExNDM0L2FwaS90YWdzIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAg"
    "ICAgcmVzcCA9IHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTMpCiAgICAgICAg"
    "ICAgICAgICBvayAgID0gcmVzcC5zdGF0dXMgPT0gMjAwCiAgICAgICAgICAgICAgICBtc2cgID0g"
    "Ik9sbGFtYSBpcyBydW5uaW5nIOKckyIgaWYgb2sgZWxzZSAiT2xsYW1hIG5vdCByZXNwb25kaW5n"
    "LiIKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgbXNn"
    "ID0gZiJPbGxhbWEgbm90IHJlYWNoYWJsZToge2V9IgoKICAgICAgICBlbGlmIGlkeCA9PSAyOiAg"
    "IyBDbGF1ZGUKICAgICAgICAgICAga2V5ID0gc2VsZi5fY2xhdWRlX2tleS50ZXh0KCkuc3RyaXAo"
    "KQogICAgICAgICAgICBvayAgPSBib29sKGtleSBhbmQga2V5LnN0YXJ0c3dpdGgoInNrLWFudCIp"
    "KQogICAgICAgICAgICBtc2cgPSAiQVBJIGtleSBmb3JtYXQgbG9va3MgY29ycmVjdC4iIGlmIG9r"
    "IGVsc2UgIkVudGVyIGEgdmFsaWQgQ2xhdWRlIEFQSSBrZXkuIgoKICAgICAgICBlbGlmIGlkeCA9"
    "PSAzOiAgIyBPcGVuQUkKICAgICAgICAgICAga2V5ID0gc2VsZi5fb2FpX2tleS50ZXh0KCkuc3Ry"
    "aXAoKQogICAgICAgICAgICBvayAgPSBib29sKGtleSBhbmQga2V5LnN0YXJ0c3dpdGgoInNrLSIp"
    "KQogICAgICAgICAgICBtc2cgPSAiQVBJIGtleSBmb3JtYXQgbG9va3MgY29ycmVjdC4iIGlmIG9r"
    "IGVsc2UgIkVudGVyIGEgdmFsaWQgT3BlbkFJIEFQSSBrZXkuIgoKICAgICAgICBjb2xvciA9IENf"
    "R1JFRU4gaWYgb2sgZWxzZSBDX0NSSU1TT04KICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFRl"
    "eHQobXNnKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tf"
    "Rk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbi5zZXRFbmFi"
    "bGVkKG9rKQoKICAgIGRlZiBidWlsZF9jb25maWcoc2VsZikgLT4gZGljdDoKICAgICAgICAiIiJC"
    "dWlsZCBhbmQgcmV0dXJuIHVwZGF0ZWQgY29uZmlnIGRpY3QgZnJvbSBkaWFsb2cgc2VsZWN0aW9u"
    "cy4iIiIKICAgICAgICBjZmcgICAgID0gX2RlZmF1bHRfY29uZmlnKCkKICAgICAgICBpZHggICAg"
    "ID0gc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXgoKQogICAgICAgIHR5cGVzICAgPSBbImxv"
    "Y2FsIiwgIm9sbGFtYSIsICJjbGF1ZGUiLCAib3BlbmFpIl0KICAgICAgICBjZmdbIm1vZGVsIl1b"
    "InR5cGUiXSA9IHR5cGVzW2lkeF0KCiAgICAgICAgaWYgaWR4ID09IDA6CiAgICAgICAgICAgIGNm"
    "Z1sibW9kZWwiXVsicGF0aCJdID0gc2VsZi5fbG9jYWxfcGF0aC50ZXh0KCkuc3RyaXAoKQogICAg"
    "ICAgIGVsaWYgaWR4ID09IDE6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsib2xsYW1hX21vZGVs"
    "Il0gPSBzZWxmLl9vbGxhbWFfbW9kZWwudGV4dCgpLnN0cmlwKCkgb3IgImRvbHBoaW4tMi42LTdi"
    "IgogICAgICAgIGVsaWYgaWR4ID09IDI6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX2tl"
    "eSJdICAgPSBzZWxmLl9jbGF1ZGVfa2V5LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGNmZ1si"
    "bW9kZWwiXVsiYXBpX21vZGVsIl0gPSBzZWxmLl9jbGF1ZGVfbW9kZWwudGV4dCgpLnN0cmlwKCkK"
    "ICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfdHlwZSJdICA9ICJjbGF1ZGUiCiAgICAgICAg"
    "ZWxpZiBpZHggPT0gMzoKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfa2V5Il0gICA9IHNl"
    "bGYuX29haV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlf"
    "bW9kZWwiXSA9IHNlbGYuX29haV9tb2RlbC50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdb"
    "Im1vZGVsIl1bImFwaV90eXBlIl0gID0gIm9wZW5haSIKCiAgICAgICAgY2ZnWyJmaXJzdF9ydW4i"
    "XSA9IEZhbHNlCiAgICAgICAgcmV0dXJuIGNmZwoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGNyZWF0"
    "ZV9zaG9ydGN1dChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBzZWxmLl9zaG9ydGN1dF9j"
    "Yi5pc0NoZWNrZWQoKQoKCiMg4pSA4pSAIEpPVVJOQUwgU0lERUJBUiDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSm91"
    "cm5hbFNpZGViYXIoUVdpZGdldCk6CiAgICAiIiIKICAgIENvbGxhcHNpYmxlIGxlZnQgc2lkZWJh"
    "ciBuZXh0IHRvIHRoZSBwZXJzb25hIGNoYXQgdGFiLgogICAgVG9wOiBzZXNzaW9uIGNvbnRyb2xz"
    "IChjdXJyZW50IHNlc3Npb24gbmFtZSwgc2F2ZS9sb2FkIGJ1dHRvbnMsCiAgICAgICAgIGF1dG9z"
    "YXZlIGluZGljYXRvcikuCiAgICBCb2R5OiBzY3JvbGxhYmxlIHNlc3Npb24gbGlzdCDigJQgZGF0"
    "ZSwgQUkgbmFtZSwgbWVzc2FnZSBjb3VudC4KICAgIENvbGxhcHNlcyBsZWZ0d2FyZCB0byBhIHRo"
    "aW4gc3RyaXAuCgogICAgU2lnbmFsczoKICAgICAgICBzZXNzaW9uX2xvYWRfcmVxdWVzdGVkKHN0"
    "cikgICDigJQgZGF0ZSBzdHJpbmcgb2Ygc2Vzc2lvbiB0byBsb2FkCiAgICAgICAgc2Vzc2lvbl9j"
    "bGVhcl9yZXF1ZXN0ZWQoKSAgICAg4oCUIHJldHVybiB0byBjdXJyZW50IHNlc3Npb24KICAgICIi"
    "IgoKICAgIHNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQgID0gU2lnbmFsKHN0cikKICAgIHNlc3Npb25f"
    "Y2xlYXJfcmVxdWVzdGVkID0gU2lnbmFsKCkKCiAgICBkZWYgX19pbml0X18oc2VsZiwgc2Vzc2lv"
    "bl9tZ3I6ICJTZXNzaW9uTWFuYWdlciIsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9f"
    "aW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9zZXNzaW9uX21nciA9IHNlc3Npb25fbWdyCiAg"
    "ICAgICAgc2VsZi5fZXhwYW5kZWQgICAgPSBUcnVlCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQog"
    "ICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgICMgVXNlIGEgaG9yaXpvbnRhbCByb290IGxheW91dCDigJQgY29udGVudCBvbiBsZWZ0"
    "LCB0b2dnbGUgc3RyaXAgb24gcmlnaHQKICAgICAgICByb290ID0gUUhCb3hMYXlvdXQoc2VsZikK"
    "ICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHJvb3Qu"
    "c2V0U3BhY2luZygwKQoKICAgICAgICAjIOKUgOKUgCBDb2xsYXBzZSB0b2dnbGUgc3RyaXAg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgc2VsZi5fdG9nZ2xlX3N0cmlwID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fdG9nZ2xl"
    "X3N0cmlwLnNldEZpeGVkV2lkdGgoMjApCiAgICAgICAgc2VsZi5fdG9nZ2xlX3N0cmlwLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyLXJpZ2h0"
    "OiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgdHNfbGF5b3V0"
    "ID0gUVZCb3hMYXlvdXQoc2VsZi5fdG9nZ2xlX3N0cmlwKQogICAgICAgIHRzX2xheW91dC5zZXRD"
    "b250ZW50c01hcmdpbnMoMCwgOCwgMCwgOCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuID0gUVRv"
    "b2xCdXR0b24oKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0Rml4ZWRTaXplKDE4LCAxOCkK"
    "ICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKXgCIpCiAgICAgICAgc2VsZi5fdG9n"
    "Z2xlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHRyYW5zcGFy"
    "ZW50OyBjb2xvcjoge0NfR09MRF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiBub25lOyBm"
    "b250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCiAgICAgICAgdHNfbGF5b3V0LmFkZFdpZGdldChzZWxm"
    "Ll90b2dnbGVfYnRuKQogICAgICAgIHRzX2xheW91dC5hZGRTdHJldGNoKCkKCiAgICAgICAgIyDi"
    "lIDilIAgTWFpbiBjb250ZW50IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNl"
    "bGYuX2NvbnRlbnQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9jb250ZW50LnNldE1pbmltdW1X"
    "aWR0aCgxODApCiAgICAgICAgc2VsZi5fY29udGVudC5zZXRNYXhpbXVtV2lkdGgoMjIwKQogICAg"
    "ICAgIGNvbnRlbnRfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fY29udGVudCkKICAgICAgICBj"
    "b250ZW50X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBjb250"
    "ZW50X2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgU2VjdGlvbiBsYWJlbAogICAgICAg"
    "IGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBKT1VSTkFMIikpCgog"
    "ICAgICAgICMgQ3VycmVudCBzZXNzaW9uIGluZm8KICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUg"
    "PSBRTGFiZWwoIk5ldyBTZXNzaW9uIikKICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6ZTogMTBweDsg"
    "Zm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgIgogICAgICAgICAgICBmImZvbnQtc3R5"
    "bGU6IGl0YWxpYzsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbmFtZS5zZXRXb3Jk"
    "V3JhcChUcnVlKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zZXNzaW9u"
    "X25hbWUpCgogICAgICAgICMgU2F2ZSAvIExvYWQgcm93CiAgICAgICAgY3RybF9yb3cgPSBRSEJv"
    "eExheW91dCgpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUgPSBfZ290aGljX2J0bigi8J+SviIpCiAg"
    "ICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0Rml4ZWRTaXplKDMyLCAyNCkKICAgICAgICBzZWxmLl9i"
    "dG5fc2F2ZS5zZXRUb29sVGlwKCJTYXZlIHNlc3Npb24gbm93IikKICAgICAgICBzZWxmLl9idG5f"
    "bG9hZCA9IF9nb3RoaWNfYnRuKCLwn5OCIikKICAgICAgICBzZWxmLl9idG5fbG9hZC5zZXRGaXhl"
    "ZFNpemUoMzIsIDI0KQogICAgICAgIHNlbGYuX2J0bl9sb2FkLnNldFRvb2xUaXAoIkJyb3dzZSBh"
    "bmQgbG9hZCBhIHBhc3Qgc2Vzc2lvbiIpCiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90ID0gUUxh"
    "YmVsKCLil48iKQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOHB4OyBib3JkZXI6IG5v"
    "bmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Quc2V0VG9vbFRpcCgiQXV0"
    "b3NhdmUgc3RhdHVzIikKICAgICAgICBzZWxmLl9idG5fc2F2ZS5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fZG9fc2F2ZSkKICAgICAgICBzZWxmLl9idG5fbG9hZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "ZG9fbG9hZCkKICAgICAgICBjdHJsX3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX3NhdmUpCiAgICAg"
    "ICAgY3RybF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2J0bl9sb2FkKQogICAgICAgIGN0cmxfcm93LmFk"
    "ZFdpZGdldChzZWxmLl9hdXRvc2F2ZV9kb3QpCiAgICAgICAgY3RybF9yb3cuYWRkU3RyZXRjaCgp"
    "CiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkTGF5b3V0KGN0cmxfcm93KQoKICAgICAgICAjIEpv"
    "dXJuYWwgbG9hZGVkIGluZGljYXRvcgogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsID0gUUxhYmVs"
    "KCIiKQogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "IGYiY29sb3I6IHtDX1BVUlBMRX07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tf"
    "Rk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgIGYiZm9udC1zdHlsZTogaXRhbGljOyIKICAgICAg"
    "ICApCiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBj"
    "b250ZW50X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fam91cm5hbF9sYmwpCgogICAgICAgICMgQ2xl"
    "YXIgam91cm5hbCBidXR0b24gKGhpZGRlbiB3aGVuIG5vdCBsb2FkZWQpCiAgICAgICAgc2VsZi5f"
    "YnRuX2NsZWFyX2pvdXJuYWwgPSBfZ290aGljX2J0bigi4pyXIFJldHVybiB0byBQcmVzZW50IikK"
    "ICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKEZhbHNlKQogICAgICAg"
    "IHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19jbGVhcl9q"
    "b3VybmFsKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9idG5fY2xlYXJf"
    "am91cm5hbCkKCiAgICAgICAgIyBEaXZpZGVyCiAgICAgICAgZGl2ID0gUUZyYW1lKCkKICAgICAg"
    "ICBkaXYuc2V0RnJhbWVTaGFwZShRRnJhbWUuU2hhcGUuSExpbmUpCiAgICAgICAgZGl2LnNldFN0"
    "eWxlU2hlZXQoZiJjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyIpCiAgICAgICAgY29udGVudF9sYXlv"
    "dXQuYWRkV2lkZ2V0KGRpdikKCiAgICAgICAgIyBTZXNzaW9uIGxpc3QKICAgICAgICBjb250ZW50"
    "X2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgUEFTVCBTRVNTSU9OUyIpKQogICAg"
    "ICAgIHNlbGYuX3Nlc3Npb25fbGlzdCA9IFFMaXN0V2lkZ2V0KCkKICAgICAgICBzZWxmLl9zZXNz"
    "aW9uX2xpc3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9"
    "OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19C"
    "T1JERVJ9OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsg"
    "Zm9udC1zaXplOiAxMHB4OyIKICAgICAgICAgICAgZiJRTGlzdFdpZGdldDo6aXRlbTpzZWxlY3Rl"
    "ZCB7eyBiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IH19IgogICAgICAgICkKICAgICAgICBz"
    "ZWxmLl9zZXNzaW9uX2xpc3QuaXRlbURvdWJsZUNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9zZXNz"
    "aW9uX2NsaWNrKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5pdGVtQ2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuX29uX3Nlc3Npb25fY2xpY2spCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0"
    "KHNlbGYuX3Nlc3Npb25fbGlzdCwgMSkKCiAgICAgICAgIyBBZGQgY29udGVudCBhbmQgdG9nZ2xl"
    "IHN0cmlwIHRvIHRoZSByb290IGhvcml6b250YWwgbGF5b3V0CiAgICAgICAgcm9vdC5hZGRXaWRn"
    "ZXQoc2VsZi5fY29udGVudCkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90b2dnbGVfc3Ry"
    "aXApCgogICAgZGVmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRl"
    "ZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0VmlzaWJsZShz"
    "ZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFRleHQoIuKXgCIgaWYg"
    "c2VsZi5fZXhwYW5kZWQgZWxzZSAi4pa2IikKICAgICAgICBzZWxmLnVwZGF0ZUdlb21ldHJ5KCkK"
    "ICAgICAgICBwID0gc2VsZi5wYXJlbnRXaWRnZXQoKQogICAgICAgIGlmIHAgYW5kIHAubGF5b3V0"
    "KCk6CiAgICAgICAgICAgIHAubGF5b3V0KCkuYWN0aXZhdGUoKQoKICAgIGRlZiByZWZyZXNoKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgc2Vzc2lvbnMgPSBzZWxmLl9zZXNzaW9uX21nci5saXN0X3Nl"
    "c3Npb25zKCkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QuY2xlYXIoKQogICAgICAgIGZvciBz"
    "IGluIHNlc3Npb25zOgogICAgICAgICAgICBkYXRlX3N0ciA9IHMuZ2V0KCJkYXRlIiwiIikKICAg"
    "ICAgICAgICAgbmFtZSAgICAgPSBzLmdldCgibmFtZSIsIGRhdGVfc3RyKVs6MzBdCiAgICAgICAg"
    "ICAgIGNvdW50ICAgID0gcy5nZXQoIm1lc3NhZ2VfY291bnQiLCAwKQogICAgICAgICAgICBpdGVt"
    "ID0gUUxpc3RXaWRnZXRJdGVtKGYie2RhdGVfc3RyfVxue25hbWV9ICh7Y291bnR9IG1zZ3MpIikK"
    "ICAgICAgICAgICAgaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgZGF0ZV9z"
    "dHIpCiAgICAgICAgICAgIGl0ZW0uc2V0VG9vbFRpcChmIkRvdWJsZS1jbGljayB0byBsb2FkIHNl"
    "c3Npb24gZnJvbSB7ZGF0ZV9zdHJ9IikKICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0LmFk"
    "ZEl0ZW0oaXRlbSkKCiAgICBkZWYgc2V0X3Nlc3Npb25fbmFtZShzZWxmLCBuYW1lOiBzdHIpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNldFRleHQobmFtZVs6NTBdIG9yICJO"
    "ZXcgU2Vzc2lvbiIpCgogICAgZGVmIHNldF9hdXRvc2F2ZV9pbmRpY2F0b3Ioc2VsZiwgc2F2ZWQ6"
    "IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dSRUVOIGlmIHNhdmVkIGVsc2UgQ19URVhUX0RJTX07"
    "ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDhweDsgYm9yZGVyOiBub25lOyIKICAgICAgICAp"
    "CiAgICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFRvb2xUaXAoCiAgICAgICAgICAgICJBdXRv"
    "c2F2ZWQiIGlmIHNhdmVkIGVsc2UgIlBlbmRpbmcgYXV0b3NhdmUiCiAgICAgICAgKQoKICAgIGRl"
    "ZiBzZXRfam91cm5hbF9sb2FkZWQoc2VsZiwgZGF0ZV9zdHI6IHN0cikgLT4gTm9uZToKICAgICAg"
    "ICBzZWxmLl9qb3VybmFsX2xibC5zZXRUZXh0KGYi8J+TliBKb3VybmFsOiB7ZGF0ZV9zdHJ9IikK"
    "ICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRWaXNpYmxlKFRydWUpCgogICAgZGVm"
    "IGNsZWFyX2pvdXJuYWxfaW5kaWNhdG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fam91"
    "cm5hbF9sYmwuc2V0VGV4dCgiIikKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5zZXRW"
    "aXNpYmxlKEZhbHNlKQoKICAgIGRlZiBfZG9fc2F2ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNl"
    "bGYuX3Nlc3Npb25fbWdyLnNhdmUoKQogICAgICAgIHNlbGYuc2V0X2F1dG9zYXZlX2luZGljYXRv"
    "cihUcnVlKQogICAgICAgIHNlbGYucmVmcmVzaCgpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0"
    "VGV4dCgi4pyTIikKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgxNTAwLCBsYW1iZGE6IHNlbGYu"
    "X2J0bl9zYXZlLnNldFRleHQoIvCfkr4iKSkKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgzMDAw"
    "LCBsYW1iZGE6IHNlbGYuc2V0X2F1dG9zYXZlX2luZGljYXRvcihGYWxzZSkpCgogICAgZGVmIF9k"
    "b19sb2FkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBUcnkgc2VsZWN0ZWQgaXRlbSBmaXJzdAog"
    "ICAgICAgIGl0ZW0gPSBzZWxmLl9zZXNzaW9uX2xpc3QuY3VycmVudEl0ZW0oKQogICAgICAgIGlm"
    "IG5vdCBpdGVtOgogICAgICAgICAgICAjIElmIG5vdGhpbmcgc2VsZWN0ZWQsIHRyeSB0aGUgZmly"
    "c3QgaXRlbQogICAgICAgICAgICBpZiBzZWxmLl9zZXNzaW9uX2xpc3QuY291bnQoKSA+IDA6CiAg"
    "ICAgICAgICAgICAgICBpdGVtID0gc2VsZi5fc2Vzc2lvbl9saXN0Lml0ZW0oMCkKICAgICAgICAg"
    "ICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5zZXRDdXJyZW50SXRlbShpdGVtKQogICAgICAgIGlm"
    "IGl0ZW06CiAgICAgICAgICAgIGRhdGVfc3RyID0gaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5V"
    "c2VyUm9sZSkKICAgICAgICAgICAgc2VsZi5zZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmVtaXQoZGF0"
    "ZV9zdHIpCgogICAgZGVmIF9vbl9zZXNzaW9uX2NsaWNrKHNlbGYsIGl0ZW0pIC0+IE5vbmU6CiAg"
    "ICAgICAgZGF0ZV9zdHIgPSBpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAg"
    "ICAgIHNlbGYuc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZC5lbWl0KGRhdGVfc3RyKQoKICAgIGRlZiBf"
    "ZG9fY2xlYXJfam91cm5hbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuc2Vzc2lvbl9jbGVh"
    "cl9yZXF1ZXN0ZWQuZW1pdCgpCiAgICAgICAgc2VsZi5jbGVhcl9qb3VybmFsX2luZGljYXRvcigp"
    "CgoKIyDilIDilIAgVE9SUE9SIFBBTkVMIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBUb3Jwb3JQYW5l"
    "bChRV2lkZ2V0KToKICAgICIiIgogICAgVGhyZWUtc3RhdGUgc3VzcGVuc2lvbiB0b2dnbGU6IEFX"
    "QUtFIHwgQVVUTyB8IFNVU1BFTkQKCiAgICBBV0FLRSAg4oCUIG1vZGVsIGxvYWRlZCwgYXV0by10"
    "b3Jwb3IgZGlzYWJsZWQsIGlnbm9yZXMgVlJBTSBwcmVzc3VyZQogICAgQVVUTyAgIOKAlCBtb2Rl"
    "bCBsb2FkZWQsIG1vbml0b3JzIFZSQU0gcHJlc3N1cmUsIGF1dG8tdG9ycG9yIGlmIHN1c3RhaW5l"
    "ZAogICAgU1VTUEVORCDigJQgbW9kZWwgdW5sb2FkZWQsIHN0YXlzIHN1c3BlbmRlZCB1bnRpbCBt"
    "YW51YWxseSBjaGFuZ2VkCgogICAgU2lnbmFsczoKICAgICAgICBzdGF0ZV9jaGFuZ2VkKHN0cikg"
    "IOKAlCAiQVdBS0UiIHwgIkFVVE8iIHwgIlNVU1BFTkQiCiAgICAiIiIKCiAgICBzdGF0ZV9jaGFu"
    "Z2VkID0gU2lnbmFsKHN0cikKCiAgICBTVEFURVMgPSBbIkFXQUtFIiwgIkFVVE8iLCAiU1VTUEVO"
    "RCJdCgogICAgU1RBVEVfU1RZTEVTID0gewogICAgICAgICJBV0FLRSI6IHsKICAgICAgICAgICAg"
    "ImFjdGl2ZSI6ICAgZiJiYWNrZ3JvdW5kOiAjMmExYTA1OyBjb2xvcjoge0NfR09MRH07ICIKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEfTsgYm9yZGVy"
    "LXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7"
    "IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJpbmFj"
    "dGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAg"
    "ICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRl"
    "ci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4"
    "OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAibGFi"
    "ZWwiOiAgICAi4piAIEFXQUtFIiwKICAgICAgICAgICAgInRvb2x0aXAiOiAgIk1vZGVsIGFjdGl2"
    "ZS4gQXV0by10b3Jwb3IgZGlzYWJsZWQuIiwKICAgICAgICB9LAogICAgICAgICJBVVRPIjogewog"
    "ICAgICAgICAgICAiYWN0aXZlIjogICBmImJhY2tncm91bmQ6ICMxYTEwMDU7IGNvbG9yOiAjY2M4"
    "ODIyOyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQgI2NjODgy"
    "MjsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1z"
    "aXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAg"
    "ICAgICJpbmFjdGl2ZSI6IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElN"
    "fTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRF"
    "Un07IGJvcmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQt"
    "c2l6ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAg"
    "ICAgICAibGFiZWwiOiAgICAi4peJIEFVVE8iLAogICAgICAgICAgICAidG9vbHRpcCI6ICAiTW9k"
    "ZWwgYWN0aXZlLiBBdXRvLXN1c3BlbmQgb24gVlJBTSBwcmVzc3VyZS4iLAogICAgICAgIH0sCiAg"
    "ICAgICAgIlNVU1BFTkQiOiB7CiAgICAgICAgICAgICJhY3RpdmUiOiAgIGYiYmFja2dyb3VuZDog"
    "e0NfUFVSUExFX0RJTX07IGNvbG9yOiB7Q19QVVJQTEV9OyAiCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfUFVSUExFfTsgYm9yZGVyLXJhZGl1czogMnB4OyAi"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBi"
    "b2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6IGYiYmFja2dy"
    "b3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAgICAgICAgICAg"
    "ICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDJweDsg"
    "IgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250LXdlaWdodDog"
    "Ym9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAibGFiZWwiOiAgICBmIuKasCB7"
    "VUlfU1VTUEVOU0lPTl9MQUJFTC5zdHJpcCgpIGlmIHN0cihVSV9TVVNQRU5TSU9OX0xBQkVMKS5z"
    "dHJpcCgpIGVsc2UgJ1N1c3BlbmQnfSIsCiAgICAgICAgICAgICJ0b29sdGlwIjogIGYiTW9kZWwg"
    "dW5sb2FkZWQuIHtERUNLX05BTUV9IHNsZWVwcyB1bnRpbCBtYW51YWxseSBhd2FrZW5lZC4iLAog"
    "ICAgICAgIH0sCiAgICB9CgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAg"
    "ICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9jdXJyZW50ID0gIkFX"
    "QUtFIgogICAgICAgIHNlbGYuX2J1dHRvbnM6IGRpY3Rbc3RyLCBRUHVzaEJ1dHRvbl0gPSB7fQog"
    "ICAgICAgIGxheW91dCA9IFFIQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRl"
    "bnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDIpCgogICAg"
    "ICAgIGZvciBzdGF0ZSBpbiBzZWxmLlNUQVRFUzoKICAgICAgICAgICAgYnRuID0gUVB1c2hCdXR0"
    "b24oc2VsZi5TVEFURV9TVFlMRVNbc3RhdGVdWyJsYWJlbCJdKQogICAgICAgICAgICBidG4uc2V0"
    "VG9vbFRpcChzZWxmLlNUQVRFX1NUWUxFU1tzdGF0ZV1bInRvb2x0aXAiXSkKICAgICAgICAgICAg"
    "YnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgICAgICBidG4uY2xpY2tlZC5jb25uZWN0KGxh"
    "bWJkYSBjaGVja2VkLCBzPXN0YXRlOiBzZWxmLl9zZXRfc3RhdGUocykpCiAgICAgICAgICAgIHNl"
    "bGYuX2J1dHRvbnNbc3RhdGVdID0gYnRuCiAgICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoYnRu"
    "KQoKICAgICAgICBzZWxmLl9hcHBseV9zdHlsZXMoKQoKICAgIGRlZiBfc2V0X3N0YXRlKHNlbGYs"
    "IHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgaWYgc3RhdGUgPT0gc2VsZi5fY3VycmVudDoK"
    "ICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fY3VycmVudCA9IHN0YXRlCiAgICAgICAg"
    "c2VsZi5fYXBwbHlfc3R5bGVzKCkKICAgICAgICBzZWxmLnN0YXRlX2NoYW5nZWQuZW1pdChzdGF0"
    "ZSkKCiAgICBkZWYgX2FwcGx5X3N0eWxlcyhzZWxmKSAtPiBOb25lOgogICAgICAgIGZvciBzdGF0"
    "ZSwgYnRuIGluIHNlbGYuX2J1dHRvbnMuaXRlbXMoKToKICAgICAgICAgICAgc3R5bGVfa2V5ID0g"
    "ImFjdGl2ZSIgaWYgc3RhdGUgPT0gc2VsZi5fY3VycmVudCBlbHNlICJpbmFjdGl2ZSIKICAgICAg"
    "ICAgICAgYnRuLnNldFN0eWxlU2hlZXQoc2VsZi5TVEFURV9TVFlMRVNbc3RhdGVdW3N0eWxlX2tl"
    "eV0pCgogICAgQHByb3BlcnR5CiAgICBkZWYgY3VycmVudF9zdGF0ZShzZWxmKSAtPiBzdHI6CiAg"
    "ICAgICAgcmV0dXJuIHNlbGYuX2N1cnJlbnQKCiAgICBkZWYgc2V0X3N0YXRlKHNlbGYsIHN0YXRl"
    "OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIiIiU2V0IHN0YXRlIHByb2dyYW1tYXRpY2FsbHkgKGUu"
    "Zy4gZnJvbSBhdXRvLXRvcnBvciBkZXRlY3Rpb24pLiIiIgogICAgICAgIGlmIHN0YXRlIGluIHNl"
    "bGYuU1RBVEVTOgogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdGUoc3RhdGUpCgoKY2xhc3MgU2V0"
    "dGluZ3NTZWN0aW9uKFFXaWRnZXQpOgogICAgIiIiU2ltcGxlIGNvbGxhcHNpYmxlIHNlY3Rpb24g"
    "dXNlZCBieSBTZXR0aW5nc1RhYi4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgdGl0bGU6IHN0"
    "ciwgcGFyZW50PU5vbmUsIGV4cGFuZGVkOiBib29sID0gVHJ1ZSk6CiAgICAgICAgc3VwZXIoKS5f"
    "X2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBleHBhbmRlZAoKICAgICAg"
    "ICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lu"
    "cygwLCAwLCAwLCAwKQogICAgICAgIHJvb3Quc2V0U3BhY2luZygwKQoKICAgICAgICBzZWxmLl9o"
    "ZWFkZXJfYnRuID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX2hlYWRlcl9idG4uc2V0VGV4"
    "dChmIuKWvCB7dGl0bGV9IiBpZiBleHBhbmRlZCBlbHNlIGYi4pa2IHt0aXRsZX0iKQogICAgICAg"
    "IHNlbGYuX2hlYWRlcl9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5k"
    "OiB7Q19CRzN9OyBjb2xvcjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05f"
    "RElNfTsgIgogICAgICAgICAgICBmInBhZGRpbmc6IDZweDsgdGV4dC1hbGlnbjogbGVmdDsgZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7IgogICAgICAgICkKICAgICAgICBzZWxmLl9oZWFkZXJfYnRuLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl90b2dnbGUpCgogICAgICAgIHNlbGYuX2NvbnRlbnQgPSBRV2lkZ2V0"
    "KCkKICAgICAgICBzZWxmLl9jb250ZW50X2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX2NvbnRl"
    "bnQpCiAgICAgICAgc2VsZi5fY29udGVudF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDgsIDgs"
    "IDgsIDgpCiAgICAgICAgc2VsZi5fY29udGVudF9sYXlvdXQuc2V0U3BhY2luZyg4KQogICAgICAg"
    "IHNlbGYuX2NvbnRlbnQuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7"
    "Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItdG9wOiBub25lOyIK"
    "ICAgICAgICApCiAgICAgICAgc2VsZi5fY29udGVudC5zZXRWaXNpYmxlKGV4cGFuZGVkKQoKICAg"
    "ICAgICByb290LmFkZFdpZGdldChzZWxmLl9oZWFkZXJfYnRuKQogICAgICAgIHJvb3QuYWRkV2lk"
    "Z2V0KHNlbGYuX2NvbnRlbnQpCgogICAgQHByb3BlcnR5CiAgICBkZWYgY29udGVudF9sYXlvdXQo"
    "c2VsZikgLT4gUVZCb3hMYXlvdXQ6CiAgICAgICAgcmV0dXJuIHNlbGYuX2NvbnRlbnRfbGF5b3V0"
    "CgogICAgZGVmIF90b2dnbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRlZCA9"
    "IG5vdCBzZWxmLl9leHBhbmRlZAogICAgICAgIHNlbGYuX2hlYWRlcl9idG4uc2V0VGV4dCgKICAg"
    "ICAgICAgICAgc2VsZi5faGVhZGVyX2J0bi50ZXh0KCkucmVwbGFjZSgi4pa8IiwgIuKWtiIsIDEp"
    "CiAgICAgICAgICAgIGlmIG5vdCBzZWxmLl9leHBhbmRlZCBlbHNlCiAgICAgICAgICAgIHNlbGYu"
    "X2hlYWRlcl9idG4udGV4dCgpLnJlcGxhY2UoIuKWtiIsICLilrwiLCAxKQogICAgICAgICkKICAg"
    "ICAgICBzZWxmLl9jb250ZW50LnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCgoKY2xhc3MgU2V0"
    "dGluZ3NUYWIoUVdpZGdldCk6CiAgICAiIiJEZWNrLXdpZGUgcnVudGltZSBzZXR0aW5ncyB0YWIu"
    "IiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGRlY2tfd2luZG93OiAiRWNob0RlY2siLCBwYXJl"
    "bnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5f"
    "ZGVjayA9IGRlY2tfd2luZG93CiAgICAgICAgc2VsZi5fc2VjdGlvbl9yZWdpc3RyeTogbGlzdFtk"
    "aWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc2VjdGlvbl93aWRnZXRzOiBkaWN0W3N0ciwgU2V0dGlu"
    "Z3NTZWN0aW9uXSA9IHt9CgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAg"
    "IHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgcm9vdC5zZXRTcGFj"
    "aW5nKDApCgogICAgICAgIHNjcm9sbCA9IFFTY3JvbGxBcmVhKCkKICAgICAgICBzY3JvbGwuc2V0"
    "V2lkZ2V0UmVzaXphYmxlKFRydWUpCiAgICAgICAgc2Nyb2xsLnNldEhvcml6b250YWxTY3JvbGxC"
    "YXJQb2xpY3koUXQuU2Nyb2xsQmFyUG9saWN5LlNjcm9sbEJhckFsd2F5c09mZikKICAgICAgICBz"
    "Y3JvbGwuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHfTsgYm9yZGVyOiAxcHggc29s"
    "aWQge0NfQ1JJTVNPTl9ESU19OyIpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2Nyb2xsKQoKICAg"
    "ICAgICBib2R5ID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fYm9keV9sYXlvdXQgPSBRVkJveExh"
    "eW91dChib2R5KQogICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg2"
    "LCA2LCA2LCA2KQogICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0LnNldFNwYWNpbmcoOCkKICAgICAg"
    "ICBzY3JvbGwuc2V0V2lkZ2V0KGJvZHkpCgogICAgICAgIHNlbGYuX3JlZ2lzdGVyX2NvcmVfc2Vj"
    "dGlvbnMoKQoKICAgIGRlZiBfcmVnaXN0ZXJfc2VjdGlvbihzZWxmLCAqLCBzZWN0aW9uX2lkOiBz"
    "dHIsIHRpdGxlOiBzdHIsIGNhdGVnb3J5OiBzdHIsIHNvdXJjZV9vd25lcjogc3RyLCBzb3J0X2tl"
    "eTogaW50LCBidWlsZGVyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3NlY3Rpb25fcmVnaXN0cnku"
    "YXBwZW5kKHsKICAgICAgICAgICAgInNlY3Rpb25faWQiOiBzZWN0aW9uX2lkLAogICAgICAgICAg"
    "ICAidGl0bGUiOiB0aXRsZSwKICAgICAgICAgICAgImNhdGVnb3J5IjogY2F0ZWdvcnksCiAgICAg"
    "ICAgICAgICJzb3VyY2Vfb3duZXIiOiBzb3VyY2Vfb3duZXIsCiAgICAgICAgICAgICJzb3J0X2tl"
    "eSI6IHNvcnRfa2V5LAogICAgICAgICAgICAiYnVpbGRlciI6IGJ1aWxkZXIsCiAgICAgICAgfSkK"
    "CiAgICBkZWYgX3JlZ2lzdGVyX2NvcmVfc2VjdGlvbnMoc2VsZikgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLl9yZWdpc3Rlcl9zZWN0aW9uKAogICAgICAgICAgICBzZWN0aW9uX2lkPSJzeXN0ZW1fc2V0"
    "dGluZ3MiLAogICAgICAgICAgICB0aXRsZT0iU3lzdGVtIFNldHRpbmdzIiwKICAgICAgICAgICAg"
    "Y2F0ZWdvcnk9ImNvcmUiLAogICAgICAgICAgICBzb3VyY2Vfb3duZXI9ImRlY2tfcnVudGltZSIs"
    "CiAgICAgICAgICAgIHNvcnRfa2V5PTEwMCwKICAgICAgICAgICAgYnVpbGRlcj1zZWxmLl9idWls"
    "ZF9zeXN0ZW1fc2VjdGlvbiwKICAgICAgICApCiAgICAgICAgc2VsZi5fcmVnaXN0ZXJfc2VjdGlv"
    "bigKICAgICAgICAgICAgc2VjdGlvbl9pZD0iaW50ZWdyYXRpb25fc2V0dGluZ3MiLAogICAgICAg"
    "ICAgICB0aXRsZT0iSW50ZWdyYXRpb24gU2V0dGluZ3MiLAogICAgICAgICAgICBjYXRlZ29yeT0i"
    "Y29yZSIsCiAgICAgICAgICAgIHNvdXJjZV9vd25lcj0iZGVja19ydW50aW1lIiwKICAgICAgICAg"
    "ICAgc29ydF9rZXk9MjAwLAogICAgICAgICAgICBidWlsZGVyPXNlbGYuX2J1aWxkX2ludGVncmF0"
    "aW9uX3NlY3Rpb24sCiAgICAgICAgKQogICAgICAgIHNlbGYuX3JlZ2lzdGVyX3NlY3Rpb24oCiAg"
    "ICAgICAgICAgIHNlY3Rpb25faWQ9InVpX3NldHRpbmdzIiwKICAgICAgICAgICAgdGl0bGU9IlVJ"
    "IFNldHRpbmdzIiwKICAgICAgICAgICAgY2F0ZWdvcnk9ImNvcmUiLAogICAgICAgICAgICBzb3Vy"
    "Y2Vfb3duZXI9ImRlY2tfcnVudGltZSIsCiAgICAgICAgICAgIHNvcnRfa2V5PTMwMCwKICAgICAg"
    "ICAgICAgYnVpbGRlcj1zZWxmLl9idWlsZF91aV9zZWN0aW9uLAogICAgICAgICkKCiAgICAgICAg"
    "Zm9yIG1ldGEgaW4gc29ydGVkKHNlbGYuX3NlY3Rpb25fcmVnaXN0cnksIGtleT1sYW1iZGEgbTog"
    "bS5nZXQoInNvcnRfa2V5IiwgOTk5OSkpOgogICAgICAgICAgICBzZWN0aW9uID0gU2V0dGluZ3NT"
    "ZWN0aW9uKG1ldGFbInRpdGxlIl0sIGV4cGFuZGVkPVRydWUpCiAgICAgICAgICAgIHNlbGYuX2Jv"
    "ZHlfbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uKQogICAgICAgICAgICBzZWxmLl9zZWN0aW9uX3dp"
    "ZGdldHNbbWV0YVsic2VjdGlvbl9pZCJdXSA9IHNlY3Rpb24KICAgICAgICAgICAgbWV0YVsiYnVp"
    "bGRlciJdKHNlY3Rpb24uY29udGVudF9sYXlvdXQpCgogICAgICAgIHNlbGYuX2JvZHlfbGF5b3V0"
    "LmFkZFN0cmV0Y2goMSkKCiAgICBkZWYgX2J1aWxkX3N5c3RlbV9zZWN0aW9uKHNlbGYsIGxheW91"
    "dDogUVZCb3hMYXlvdXQpIC0+IE5vbmU6CiAgICAgICAgaWYgc2VsZi5fZGVjay5fdG9ycG9yX3Bh"
    "bmVsIGlzIG5vdCBOb25lOgogICAgICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KFFMYWJlbCgiT3Bl"
    "cmF0aW9uYWwgTW9kZSIpKQogICAgICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2RlY2su"
    "X3RvcnBvcl9wYW5lbCkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChRTGFiZWwoIklkbGUiKSkK"
    "ICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2RlY2suX2lkbGVfYnRuKQoKICAgICAgICBz"
    "ZXR0aW5ncyA9IENGRy5nZXQoInNldHRpbmdzIiwge30pCiAgICAgICAgdHpfYXV0byA9IGJvb2wo"
    "c2V0dGluZ3MuZ2V0KCJ0aW1lem9uZV9hdXRvX2RldGVjdCIsIFRydWUpKQogICAgICAgIHR6X292"
    "ZXJyaWRlID0gc3RyKHNldHRpbmdzLmdldCgidGltZXpvbmVfb3ZlcnJpZGUiLCAiIikgb3IgIiIp"
    "LnN0cmlwKCkKCiAgICAgICAgdHpfYXV0b19jaGsgPSBRQ2hlY2tCb3goIkF1dG8tZGV0ZWN0IGxv"
    "Y2FsL3N5c3RlbSB0aW1lIHpvbmUiKQogICAgICAgIHR6X2F1dG9fY2hrLnNldENoZWNrZWQodHpf"
    "YXV0bykKICAgICAgICB0el9hdXRvX2Noay50b2dnbGVkLmNvbm5lY3Qoc2VsZi5fZGVjay5fc2V0"
    "X3RpbWV6b25lX2F1dG9fZGV0ZWN0KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQodHpfYXV0b19j"
    "aGspCgogICAgICAgIHR6X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICB0el9yb3cuYWRkV2lk"
    "Z2V0KFFMYWJlbCgiTWFudWFsIFRpbWUgWm9uZSBPdmVycmlkZToiKSkKICAgICAgICB0el9jb21i"
    "byA9IFFDb21ib0JveCgpCiAgICAgICAgdHpfY29tYm8uc2V0RWRpdGFibGUoVHJ1ZSkKICAgICAg"
    "ICB0el9vcHRpb25zID0gWwogICAgICAgICAgICAiQW1lcmljYS9DaGljYWdvIiwgIkFtZXJpY2Ev"
    "TmV3X1lvcmsiLCAiQW1lcmljYS9Mb3NfQW5nZWxlcyIsCiAgICAgICAgICAgICJBbWVyaWNhL0Rl"
    "bnZlciIsICJVVEMiCiAgICAgICAgXQogICAgICAgIHR6X2NvbWJvLmFkZEl0ZW1zKHR6X29wdGlv"
    "bnMpCiAgICAgICAgaWYgdHpfb3ZlcnJpZGU6CiAgICAgICAgICAgIGlmIHR6X2NvbWJvLmZpbmRU"
    "ZXh0KHR6X292ZXJyaWRlKSA8IDA6CiAgICAgICAgICAgICAgICB0el9jb21iby5hZGRJdGVtKHR6"
    "X292ZXJyaWRlKQogICAgICAgICAgICB0el9jb21iby5zZXRDdXJyZW50VGV4dCh0el9vdmVycmlk"
    "ZSkKICAgICAgICBlbHNlOgogICAgICAgICAgICB0el9jb21iby5zZXRDdXJyZW50VGV4dCgiQW1l"
    "cmljYS9DaGljYWdvIikKICAgICAgICB0el9jb21iby5zZXRFbmFibGVkKG5vdCB0el9hdXRvKQog"
    "ICAgICAgIHR6X2NvbWJvLmN1cnJlbnRUZXh0Q2hhbmdlZC5jb25uZWN0KHNlbGYuX2RlY2suX3Nl"
    "dF90aW1lem9uZV9vdmVycmlkZSkKICAgICAgICB0el9hdXRvX2Noay50b2dnbGVkLmNvbm5lY3Qo"
    "bGFtYmRhIGVuYWJsZWQ6IHR6X2NvbWJvLnNldEVuYWJsZWQobm90IGVuYWJsZWQpKQogICAgICAg"
    "IHR6X3Jvdy5hZGRXaWRnZXQodHpfY29tYm8sIDEpCiAgICAgICAgdHpfaG9zdCA9IFFXaWRnZXQo"
    "KQogICAgICAgIHR6X2hvc3Quc2V0TGF5b3V0KHR6X3JvdykKICAgICAgICBsYXlvdXQuYWRkV2lk"
    "Z2V0KHR6X2hvc3QpCgogICAgZGVmIF9idWlsZF9pbnRlZ3JhdGlvbl9zZWN0aW9uKHNlbGYsIGxh"
    "eW91dDogUVZCb3hMYXlvdXQpIC0+IE5vbmU6CiAgICAgICAgc2V0dGluZ3MgPSBDRkcuZ2V0KCJz"
    "ZXR0aW5ncyIsIHt9KQogICAgICAgIGdvb2dsZV9zZWNvbmRzID0gaW50KHNldHRpbmdzLmdldCgi"
    "Z29vZ2xlX2luYm91bmRfaW50ZXJ2YWxfbXMiLCAzMDAwMCkpIC8vIDEwMDAKICAgICAgICBnb29n"
    "bGVfc2Vjb25kcyA9IG1heCg1LCBtaW4oNjAwLCBnb29nbGVfc2Vjb25kcykpCiAgICAgICAgZW1h"
    "aWxfbWludXRlcyA9IG1heCgxLCBpbnQoc2V0dGluZ3MuZ2V0KCJlbWFpbF9yZWZyZXNoX2ludGVy"
    "dmFsX21zIiwgMzAwMDAwKSkgLy8gNjAwMDApCgogICAgICAgIGdvb2dsZV9yb3cgPSBRSEJveExh"
    "eW91dCgpCiAgICAgICAgZ29vZ2xlX3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJHb29nbGUgcmVmcmVz"
    "aCBpbnRlcnZhbCAoc2Vjb25kcyk6IikpCiAgICAgICAgZ29vZ2xlX2JveCA9IFFTcGluQm94KCkK"
    "ICAgICAgICBnb29nbGVfYm94LnNldFJhbmdlKDUsIDYwMCkKICAgICAgICBnb29nbGVfYm94LnNl"
    "dFZhbHVlKGdvb2dsZV9zZWNvbmRzKQogICAgICAgIGdvb2dsZV9ib3gudmFsdWVDaGFuZ2VkLmNv"
    "bm5lY3Qoc2VsZi5fZGVjay5fc2V0X2dvb2dsZV9yZWZyZXNoX3NlY29uZHMpCiAgICAgICAgZ29v"
    "Z2xlX3Jvdy5hZGRXaWRnZXQoZ29vZ2xlX2JveCwgMSkKICAgICAgICBnb29nbGVfaG9zdCA9IFFX"
    "aWRnZXQoKQogICAgICAgIGdvb2dsZV9ob3N0LnNldExheW91dChnb29nbGVfcm93KQogICAgICAg"
    "IGxheW91dC5hZGRXaWRnZXQoZ29vZ2xlX2hvc3QpCgogICAgICAgIGVtYWlsX3JvdyA9IFFIQm94"
    "TGF5b3V0KCkKICAgICAgICBlbWFpbF9yb3cuYWRkV2lkZ2V0KFFMYWJlbCgiRW1haWwgcmVmcmVz"
    "aCBpbnRlcnZhbCAobWludXRlcyk6IikpCiAgICAgICAgZW1haWxfYm94ID0gUUNvbWJvQm94KCkK"
    "ICAgICAgICBlbWFpbF9ib3guc2V0RWRpdGFibGUoVHJ1ZSkKICAgICAgICBlbWFpbF9ib3guYWRk"
    "SXRlbXMoWyIxIiwgIjUiLCAiMTAiLCAiMTUiLCAiMzAiLCAiNjAiXSkKICAgICAgICBlbWFpbF9i"
    "b3guc2V0Q3VycmVudFRleHQoc3RyKGVtYWlsX21pbnV0ZXMpKQogICAgICAgIGVtYWlsX2JveC5j"
    "dXJyZW50VGV4dENoYW5nZWQuY29ubmVjdChzZWxmLl9kZWNrLl9zZXRfZW1haWxfcmVmcmVzaF9t"
    "aW51dGVzX2Zyb21fdGV4dCkKICAgICAgICBlbWFpbF9yb3cuYWRkV2lkZ2V0KGVtYWlsX2JveCwg"
    "MSkKICAgICAgICBlbWFpbF9ob3N0ID0gUVdpZGdldCgpCiAgICAgICAgZW1haWxfaG9zdC5zZXRM"
    "YXlvdXQoZW1haWxfcm93KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoZW1haWxfaG9zdCkKCiAg"
    "ICAgICAgbm90ZSA9IFFMYWJlbCgiRW1haWwgcG9sbGluZyBmb3VuZGF0aW9uIGlzIGNvbmZpZ3Vy"
    "YXRpb24tb25seSB1bmxlc3MgYW4gZW1haWwgYmFja2VuZCBpcyBlbmFibGVkLiIpCiAgICAgICAg"
    "bm90ZS5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7"
    "IikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KG5vdGUpCgogICAgZGVmIF9idWlsZF91aV9zZWN0"
    "aW9uKHNlbGYsIGxheW91dDogUVZCb3hMYXlvdXQpIC0+IE5vbmU6CiAgICAgICAgbGF5b3V0LmFk"
    "ZFdpZGdldChRTGFiZWwoIldpbmRvdyBTaGVsbCIpKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQo"
    "c2VsZi5fZGVjay5fZnNfYnRuKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZGVjay5f"
    "YmxfYnRuKQoKCmNsYXNzIERpY2VHbHlwaChRV2lkZ2V0KToKICAgICIiIlNpbXBsZSAyRCBzaWxo"
    "b3VldHRlIHJlbmRlcmVyIGZvciBkaWUtdHlwZSByZWNvZ25pdGlvbi4iIiIKICAgIGRlZiBfX2lu"
    "aXRfXyhzZWxmLCBkaWVfdHlwZTogc3RyID0gImQyMCIsIHBhcmVudD1Ob25lKToKICAgICAgICBz"
    "dXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kaWVfdHlwZSA9IGRpZV90eXBl"
    "CiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSg3MCwgNzApCiAgICAgICAgc2VsZi5zZXRNYXhp"
    "bXVtU2l6ZSg5MCwgOTApCgogICAgZGVmIHNldF9kaWVfdHlwZShzZWxmLCBkaWVfdHlwZTogc3Ry"
    "KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2RpZV90eXBlID0gZGllX3R5cGUKICAgICAgICBzZWxm"
    "LnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpOgogICAgICAgIHBhaW50"
    "ZXIgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHBhaW50ZXIuc2V0UmVuZGVySGludChRUGFpbnRl"
    "ci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICByZWN0ID0gc2VsZi5yZWN0KCkuYWRq"
    "dXN0ZWQoOCwgOCwgLTgsIC04KQoKICAgICAgICBkaWUgPSBzZWxmLl9kaWVfdHlwZQogICAgICAg"
    "IGxpbmUgPSBRQ29sb3IoQ19HT0xEKQogICAgICAgIGZpbGwgPSBRQ29sb3IoQ19CRzIpCiAgICAg"
    "ICAgYWNjZW50ID0gUUNvbG9yKENfQ1JJTVNPTikKCiAgICAgICAgcGFpbnRlci5zZXRQZW4oUVBl"
    "bihsaW5lLCAyKSkKICAgICAgICBwYWludGVyLnNldEJydXNoKGZpbGwpCgogICAgICAgIHB0cyA9"
    "IFtdCiAgICAgICAgaWYgZGllID09ICJkNCI6CiAgICAgICAgICAgIHB0cyA9IFsKICAgICAgICAg"
    "ICAgICAgIFFQb2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC50b3AoKSksCiAgICAgICAgICAg"
    "ICAgICBRUG9pbnQocmVjdC5sZWZ0KCksIHJlY3QuYm90dG9tKCkpLAogICAgICAgICAgICAgICAg"
    "UVBvaW50KHJlY3QucmlnaHQoKSwgcmVjdC5ib3R0b20oKSksCiAgICAgICAgICAgIF0KICAgICAg"
    "ICBlbGlmIGRpZSA9PSAiZDYiOgogICAgICAgICAgICBwYWludGVyLmRyYXdSb3VuZGVkUmVjdChy"
    "ZWN0LCA0LCA0KQogICAgICAgIGVsaWYgZGllID09ICJkOCI6CiAgICAgICAgICAgIHB0cyA9IFsK"
    "ICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC50b3AoKSksCiAg"
    "ICAgICAgICAgICAgICBRUG9pbnQocmVjdC5sZWZ0KCksIHJlY3QuY2VudGVyKCkueSgpKSwKICAg"
    "ICAgICAgICAgICAgIFFQb2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC5ib3R0b20oKSksCiAg"
    "ICAgICAgICAgICAgICBRUG9pbnQocmVjdC5yaWdodCgpLCByZWN0LmNlbnRlcigpLnkoKSksCiAg"
    "ICAgICAgICAgIF0KICAgICAgICBlbGlmIGRpZSBpbiAoImQxMCIsICJkMTAwIik6CiAgICAgICAg"
    "ICAgIHB0cyA9IFsKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVj"
    "dC50b3AoKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5sZWZ0KCkgKyA4LCByZWN0LnRv"
    "cCgpICsgMTYpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpLCByZWN0LmJvdHRv"
    "bSgpIC0gMTIpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QuY2VudGVyKCkueCgpLCByZWN0"
    "LmJvdHRvbSgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LnJpZ2h0KCksIHJlY3QuYm90"
    "dG9tKCkgLSAxMiksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5yaWdodCgpIC0gOCwgcmVj"
    "dC50b3AoKSArIDE2KSwKICAgICAgICAgICAgXQogICAgICAgIGVsaWYgZGllID09ICJkMTIiOgog"
    "ICAgICAgICAgICBjeCA9IHJlY3QuY2VudGVyKCkueCgpOyBjeSA9IHJlY3QuY2VudGVyKCkueSgp"
    "CiAgICAgICAgICAgIHJ4ID0gcmVjdC53aWR0aCgpIC8gMjsgcnkgPSByZWN0LmhlaWdodCgpIC8g"
    "MgogICAgICAgICAgICBmb3IgaSBpbiByYW5nZSg1KToKICAgICAgICAgICAgICAgIGEgPSAobWF0"
    "aC5waSAqIDIgKiBpIC8gNSkgLSAobWF0aC5waSAvIDIpCiAgICAgICAgICAgICAgICBwdHMuYXBw"
    "ZW5kKFFQb2ludChpbnQoY3ggKyByeCAqIG1hdGguY29zKGEpKSwgaW50KGN5ICsgcnkgKiBtYXRo"
    "LnNpbihhKSkpKQogICAgICAgIGVsc2U6ICAjIGQyMAogICAgICAgICAgICBwdHMgPSBbCiAgICAg"
    "ICAgICAgICAgICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJlY3QudG9wKCkpLAogICAgICAg"
    "ICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpICsgMTAsIHJlY3QudG9wKCkgKyAxNCksCiAgICAg"
    "ICAgICAgICAgICBRUG9pbnQocmVjdC5sZWZ0KCksIHJlY3QuY2VudGVyKCkueSgpKSwKICAgICAg"
    "ICAgICAgICAgIFFQb2ludChyZWN0LmxlZnQoKSArIDEwLCByZWN0LmJvdHRvbSgpIC0gMTQpLAog"
    "ICAgICAgICAgICAgICAgUVBvaW50KHJlY3QuY2VudGVyKCkueCgpLCByZWN0LmJvdHRvbSgpKSwK"
    "ICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LnJpZ2h0KCkgLSAxMCwgcmVjdC5ib3R0b20oKSAt"
    "IDE0KSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LnJpZ2h0KCksIHJlY3QuY2VudGVyKCku"
    "eSgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LnJpZ2h0KCkgLSAxMCwgcmVjdC50b3Ao"
    "KSArIDE0KSwKICAgICAgICAgICAgXQoKICAgICAgICBpZiBwdHM6CiAgICAgICAgICAgIHBhdGgg"
    "PSBRUGFpbnRlclBhdGgoKQogICAgICAgICAgICBwYXRoLm1vdmVUbyhwdHNbMF0pCiAgICAgICAg"
    "ICAgIGZvciBwIGluIHB0c1sxOl06CiAgICAgICAgICAgICAgICBwYXRoLmxpbmVUbyhwKQogICAg"
    "ICAgICAgICBwYXRoLmNsb3NlU3VicGF0aCgpCiAgICAgICAgICAgIHBhaW50ZXIuZHJhd1BhdGgo"
    "cGF0aCkKCiAgICAgICAgcGFpbnRlci5zZXRQZW4oUVBlbihhY2NlbnQsIDEpKQogICAgICAgIHR4"
    "dCA9ICIlIiBpZiBkaWUgPT0gImQxMDAiIGVsc2UgZGllLnJlcGxhY2UoImQiLCAiIikKICAgICAg"
    "ICBwYWludGVyLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCAxMiwgUUZvbnQuV2VpZ2h0LkJvbGQp"
    "KQogICAgICAgIHBhaW50ZXIuZHJhd1RleHQocmVjdCwgUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNl"
    "bnRlciwgdHh0KQoKCmNsYXNzIERpY2VUcmF5RGllKFFGcmFtZSk6CiAgICBzaW5nbGVDbGlja2Vk"
    "ID0gU2lnbmFsKHN0cikKICAgIGRvdWJsZUNsaWNrZWQgPSBTaWduYWwoc3RyKQoKICAgIGRlZiBf"
    "X2luaXRfXyhzZWxmLCBkaWVfdHlwZTogc3RyLCBkaXNwbGF5X2xhYmVsOiBzdHIsIHBhcmVudD1O"
    "b25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLmRpZV90"
    "eXBlID0gZGllX3R5cGUKICAgICAgICBzZWxmLmRpc3BsYXlfbGFiZWwgPSBkaXNwbGF5X2xhYmVs"
    "CiAgICAgICAgc2VsZi5fY2xpY2tfdGltZXIgPSBRVGltZXIoc2VsZikKICAgICAgICBzZWxmLl9j"
    "bGlja190aW1lci5zZXRTaW5nbGVTaG90KFRydWUpCiAgICAgICAgc2VsZi5fY2xpY2tfdGltZXIu"
    "c2V0SW50ZXJ2YWwoMjIwKQogICAgICAgIHNlbGYuX2NsaWNrX3RpbWVyLnRpbWVvdXQuY29ubmVj"
    "dChzZWxmLl9lbWl0X3NpbmdsZSkKCiAgICAgICAgc2VsZi5zZXRPYmplY3ROYW1lKCJEaWNlVHJh"
    "eURpZSIpCiAgICAgICAgc2VsZi5zZXRDdXJzb3IoUXQuQ3Vyc29yU2hhcGUuUG9pbnRpbmdIYW5k"
    "Q3Vyc29yKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJRRnJhbWUj"
    "RGljZVRyYXlEaWUge3sgYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyOiAxcHggc29saWQge0Nf"
    "Qk9SREVSfTsgYm9yZGVyLXJhZGl1czogOHB4OyB9fSIKICAgICAgICAgICAgZiJRRnJhbWUjRGlj"
    "ZVRyYXlEaWU6aG92ZXIge3sgYm9yZGVyOiAxcHggc29saWQge0NfR09MRH07IH19IgogICAgICAg"
    "ICkKCiAgICAgICAgbGF5ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXkuc2V0Q29udGVu"
    "dHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAgbGF5LnNldFNwYWNpbmcoMikKCiAgICAgICAg"
    "Z2x5cGhfZGllID0gImQxMDAiIGlmIGRpZV90eXBlID09ICJkJSIgZWxzZSBkaWVfdHlwZQogICAg"
    "ICAgIHNlbGYuZ2x5cGggPSBEaWNlR2x5cGgoZ2x5cGhfZGllKQogICAgICAgIHNlbGYuZ2x5cGgu"
    "c2V0Rml4ZWRTaXplKDU0LCA1NCkKICAgICAgICBzZWxmLmdseXBoLnNldEF0dHJpYnV0ZShRdC5X"
    "aWRnZXRBdHRyaWJ1dGUuV0FfVHJhbnNwYXJlbnRGb3JNb3VzZUV2ZW50cywgVHJ1ZSkKCiAgICAg"
    "ICAgc2VsZi5sYmwgPSBRTGFiZWwoZGlzcGxheV9sYWJlbCkKICAgICAgICBzZWxmLmxibC5zZXRB"
    "bGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICBzZWxmLmxibC5z"
    "ZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX1RFWFR9OyBmb250LXdlaWdodDogYm9sZDsiKQogICAg"
    "ICAgIHNlbGYubGJsLnNldEF0dHJpYnV0ZShRdC5XaWRnZXRBdHRyaWJ1dGUuV0FfVHJhbnNwYXJl"
    "bnRGb3JNb3VzZUV2ZW50cywgVHJ1ZSkKCiAgICAgICAgbGF5LmFkZFdpZGdldChzZWxmLmdseXBo"
    "LCAwLCBRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIGxheS5hZGRXaWRnZXQo"
    "c2VsZi5sYmwpCgogICAgZGVmIG1vdXNlUHJlc3NFdmVudChzZWxmLCBldmVudCk6CiAgICAgICAg"
    "aWYgZXZlbnQuYnV0dG9uKCkgPT0gUXQuTW91c2VCdXR0b24uTGVmdEJ1dHRvbjoKICAgICAgICAg"
    "ICAgaWYgc2VsZi5fY2xpY2tfdGltZXIuaXNBY3RpdmUoKToKICAgICAgICAgICAgICAgIHNlbGYu"
    "X2NsaWNrX3RpbWVyLnN0b3AoKQogICAgICAgICAgICAgICAgc2VsZi5kb3VibGVDbGlja2VkLmVt"
    "aXQoc2VsZi5kaWVfdHlwZSkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYu"
    "X2NsaWNrX3RpbWVyLnN0YXJ0KCkKICAgICAgICAgICAgZXZlbnQuYWNjZXB0KCkKICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgc3VwZXIoKS5tb3VzZVByZXNzRXZlbnQoZXZlbnQpCgogICAgZGVm"
    "IF9lbWl0X3NpbmdsZShzZWxmKToKICAgICAgICBzZWxmLnNpbmdsZUNsaWNrZWQuZW1pdChzZWxm"
    "LmRpZV90eXBlKQoKCmNsYXNzIERpY2VSb2xsZXJUYWIoUVdpZGdldCk6CiAgICAiIiJEZWNrLW5h"
    "dGl2ZSBEaWNlIFJvbGxlciBtb2R1bGUgdGFiIHdpdGggdHJheS9wb29sIHdvcmtmbG93IGFuZCBz"
    "dHJ1Y3R1cmVkIHJvbGwgZXZlbnRzLiIiIgoKICAgIFRSQVlfT1JERVIgPSBbImQ0IiwgImQ2Iiwg"
    "ImQ4IiwgImQxMCIsICJkMTIiLCAiZDIwIiwgImQlIl0KCiAgICBkZWYgX19pbml0X18oc2VsZiwg"
    "ZGlhZ25vc3RpY3NfbG9nZ2VyPU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQogICAg"
    "ICAgIHNlbGYuX2xvZyA9IGRpYWdub3N0aWNzX2xvZ2dlciBvciAobGFtYmRhICpfYXJncywgKipf"
    "a3dhcmdzOiBOb25lKQoKICAgICAgICBzZWxmLnJvbGxfZXZlbnRzOiBsaXN0W2RpY3RdID0gW10K"
    "ICAgICAgICBzZWxmLnNhdmVkX3JvbGxzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLmNv"
    "bW1vbl9yb2xsczogZGljdFtzdHIsIGRpY3RdID0ge30KICAgICAgICBzZWxmLmV2ZW50X2J5X2lk"
    "OiBkaWN0W3N0ciwgZGljdF0gPSB7fQogICAgICAgIHNlbGYuY3VycmVudF9wb29sOiBkaWN0W3N0"
    "ciwgaW50XSA9IHt9CiAgICAgICAgc2VsZi5jdXJyZW50X3JvbGxfaWRzOiBsaXN0W3N0cl0gPSBb"
    "XQoKICAgICAgICBzZWxmLnJ1bGVfZGVmaW5pdGlvbnM6IGRpY3Rbc3RyLCBkaWN0XSA9IHsKICAg"
    "ICAgICAgICAgInJ1bGVfNGQ2X2Ryb3BfbG93ZXN0IjogewogICAgICAgICAgICAgICAgImlkIjog"
    "InJ1bGVfNGQ2X2Ryb3BfbG93ZXN0IiwKICAgICAgICAgICAgICAgICJuYW1lIjogIkQmRCA1ZSBT"
    "dGF0IFJvbGwiLAogICAgICAgICAgICAgICAgImRpY2VfY291bnQiOiA0LAogICAgICAgICAgICAg"
    "ICAgImRpY2Vfc2lkZXMiOiA2LAogICAgICAgICAgICAgICAgImRyb3BfbG93ZXN0X2NvdW50Ijog"
    "MSwKICAgICAgICAgICAgICAgICJkcm9wX2hpZ2hlc3RfY291bnQiOiAwLAogICAgICAgICAgICAg"
    "ICAgIm5vdGVzIjogIlJvbGwgNGQ2LCBkcm9wIGxvd2VzdCBvbmUuIgogICAgICAgICAgICB9LAog"
    "ICAgICAgICAgICAicnVsZV8zZDZfc3RyYWlnaHQiOiB7CiAgICAgICAgICAgICAgICAiaWQiOiAi"
    "cnVsZV8zZDZfc3RyYWlnaHQiLAogICAgICAgICAgICAgICAgIm5hbWUiOiAiM2Q2IFN0cmFpZ2h0"
    "IiwKICAgICAgICAgICAgICAgICJkaWNlX2NvdW50IjogMywKICAgICAgICAgICAgICAgICJkaWNl"
    "X3NpZGVzIjogNiwKICAgICAgICAgICAgICAgICJkcm9wX2xvd2VzdF9jb3VudCI6IDAsCiAgICAg"
    "ICAgICAgICAgICAiZHJvcF9oaWdoZXN0X2NvdW50IjogMCwKICAgICAgICAgICAgICAgICJub3Rl"
    "cyI6ICJDbGFzc2ljIDNkNiByb2xsLiIKICAgICAgICAgICAgfSwKICAgICAgICB9CgogICAgICAg"
    "IHNlbGYuX2J1aWxkX3VpKCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3Bvb2xfZWRpdG9yKCkKICAg"
    "ICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBkZWYgX2J1aWxkX3VpKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5z"
    "ZXRDb250ZW50c01hcmdpbnMoOCwgOCwgOCwgOCkKICAgICAgICByb290LnNldFNwYWNpbmcoNikK"
    "CiAgICAgICAgdHJheV93cmFwID0gUUZyYW1lKCkKICAgICAgICB0cmF5X3dyYXAuc2V0U3R5bGVT"
    "aGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07"
    "IikKICAgICAgICB0cmF5X2xheW91dCA9IFFWQm94TGF5b3V0KHRyYXlfd3JhcCkKICAgICAgICB0"
    "cmF5X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoOCwgOCwgOCwgOCkKICAgICAgICB0cmF5X2xh"
    "eW91dC5zZXRTcGFjaW5nKDYpCiAgICAgICAgdHJheV9sYXlvdXQuYWRkV2lkZ2V0KFFMYWJlbCgi"
    "RGljZSBUcmF5IikpCgogICAgICAgIHRyYXlfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHRy"
    "YXlfcm93LnNldFNwYWNpbmcoNikKICAgICAgICBmb3IgZGllIGluIHNlbGYuVFJBWV9PUkRFUjoK"
    "ICAgICAgICAgICAgYmxvY2sgPSBEaWNlVHJheURpZShkaWUsIGRpZSkKICAgICAgICAgICAgYmxv"
    "Y2suc2luZ2xlQ2xpY2tlZC5jb25uZWN0KHNlbGYuX2FkZF9kaWVfdG9fcG9vbCkKICAgICAgICAg"
    "ICAgYmxvY2suZG91YmxlQ2xpY2tlZC5jb25uZWN0KHNlbGYuX3F1aWNrX3JvbGxfc2luZ2xlX2Rp"
    "ZSkKICAgICAgICAgICAgdHJheV9yb3cuYWRkV2lkZ2V0KGJsb2NrLCAxKQogICAgICAgIHRyYXlf"
    "bGF5b3V0LmFkZExheW91dCh0cmF5X3JvdykKICAgICAgICByb290LmFkZFdpZGdldCh0cmF5X3dy"
    "YXApCgogICAgICAgIHBvb2xfd3JhcCA9IFFGcmFtZSgpCiAgICAgICAgcG9vbF93cmFwLnNldFN0"
    "eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JE"
    "RVJ9OyIpCiAgICAgICAgcHcgPSBRVkJveExheW91dChwb29sX3dyYXApCiAgICAgICAgcHcuc2V0"
    "Q29udGVudHNNYXJnaW5zKDgsIDgsIDgsIDgpCiAgICAgICAgcHcuc2V0U3BhY2luZyg2KQoKICAg"
    "ICAgICBwdy5hZGRXaWRnZXQoUUxhYmVsKCJDdXJyZW50IFBvb2wiKSkKICAgICAgICBzZWxmLnBv"
    "b2xfZXhwcl9sYmwgPSBRTGFiZWwoIlBvb2w6IChlbXB0eSkiKQogICAgICAgIHNlbGYucG9vbF9l"
    "eHByX2xibC5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX0dPTER9OyBmb250LXdlaWdodDogYm9s"
    "ZDsiKQogICAgICAgIHB3LmFkZFdpZGdldChzZWxmLnBvb2xfZXhwcl9sYmwpCgogICAgICAgIHNl"
    "bGYucG9vbF9lbnRyaWVzX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYucG9vbF9lbnRy"
    "aWVzX2xheW91dCA9IFFIQm94TGF5b3V0KHNlbGYucG9vbF9lbnRyaWVzX3dpZGdldCkKICAgICAg"
    "ICBzZWxmLnBvb2xfZW50cmllc19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDAp"
    "CiAgICAgICAgc2VsZi5wb29sX2VudHJpZXNfbGF5b3V0LnNldFNwYWNpbmcoNikKICAgICAgICBw"
    "dy5hZGRXaWRnZXQoc2VsZi5wb29sX2VudHJpZXNfd2lkZ2V0KQoKICAgICAgICBtZXRhX3JvdyA9"
    "IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLmxhYmVsX2VkaXQgPSBRTGluZUVkaXQoKTsgc2Vs"
    "Zi5sYWJlbF9lZGl0LnNldFBsYWNlaG9sZGVyVGV4dCgiTGFiZWwgLyBwdXJwb3NlIikKICAgICAg"
    "ICBzZWxmLm1vZF9zcGluID0gUVNwaW5Cb3goKTsgc2VsZi5tb2Rfc3Bpbi5zZXRSYW5nZSgtOTk5"
    "LCA5OTkpOyBzZWxmLm1vZF9zcGluLnNldFZhbHVlKDApCiAgICAgICAgc2VsZi5ydWxlX2NvbWJv"
    "ID0gUUNvbWJvQm94KCk7IHNlbGYucnVsZV9jb21iby5hZGRJdGVtKCJNYW51YWwgUm9sbCIsICIi"
    "KQogICAgICAgIGZvciByaWQsIG1ldGEgaW4gc2VsZi5ydWxlX2RlZmluaXRpb25zLml0ZW1zKCk6"
    "CiAgICAgICAgICAgIHNlbGYucnVsZV9jb21iby5hZGRJdGVtKG1ldGEuZ2V0KCJuYW1lIiwgcmlk"
    "KSwgcmlkKQoKICAgICAgICBmb3IgdGl0bGUsIHcgaW4gKCgiTGFiZWwiLCBzZWxmLmxhYmVsX2Vk"
    "aXQpLCAoIk1vZGlmaWVyIiwgc2VsZi5tb2Rfc3BpbiksICgiUnVsZSIsIHNlbGYucnVsZV9jb21i"
    "bykpOgogICAgICAgICAgICBjb2wgPSBRVkJveExheW91dCgpCiAgICAgICAgICAgIGxibCA9IFFM"
    "YWJlbCh0aXRsZSkKICAgICAgICAgICAgbGJsLnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfVEVY"
    "VF9ESU19OyBmb250LXNpemU6IDlweDsiKQogICAgICAgICAgICBjb2wuYWRkV2lkZ2V0KGxibCkK"
    "ICAgICAgICAgICAgY29sLmFkZFdpZGdldCh3KQogICAgICAgICAgICBtZXRhX3Jvdy5hZGRMYXlv"
    "dXQoY29sLCAxKQogICAgICAgIHB3LmFkZExheW91dChtZXRhX3JvdykKCiAgICAgICAgYWN0aW9u"
    "cyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLnJvbGxfcG9vbF9idG4gPSBRUHVzaEJ1dHRv"
    "bigiUm9sbCBQb29sIikKICAgICAgICBzZWxmLnJlc2V0X3Bvb2xfYnRuID0gUVB1c2hCdXR0b24o"
    "IlJlc2V0IFBvb2wiKQogICAgICAgIHNlbGYuc2F2ZV9wb29sX2J0biA9IFFQdXNoQnV0dG9uKCJT"
    "YXZlIFBvb2wiKQogICAgICAgIGFjdGlvbnMuYWRkV2lkZ2V0KHNlbGYucm9sbF9wb29sX2J0bikK"
    "ICAgICAgICBhY3Rpb25zLmFkZFdpZGdldChzZWxmLnJlc2V0X3Bvb2xfYnRuKQogICAgICAgIGFj"
    "dGlvbnMuYWRkV2lkZ2V0KHNlbGYuc2F2ZV9wb29sX2J0bikKICAgICAgICBwdy5hZGRMYXlvdXQo"
    "YWN0aW9ucykKCiAgICAgICAgcm9vdC5hZGRXaWRnZXQocG9vbF93cmFwKQoKICAgICAgICByZXN1"
    "bHRfd3JhcCA9IFFGcmFtZSgpCiAgICAgICAgcmVzdWx0X3dyYXAuc2V0U3R5bGVTaGVldChmImJh"
    "Y2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IikKICAgICAg"
    "ICBybCA9IFFWQm94TGF5b3V0KHJlc3VsdF93cmFwKQogICAgICAgIHJsLnNldENvbnRlbnRzTWFy"
    "Z2lucyg4LCA4LCA4LCA4KQogICAgICAgIHJsLmFkZFdpZGdldChRTGFiZWwoIkN1cnJlbnQgUmVz"
    "dWx0IikpCiAgICAgICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwgPSBRTGFiZWwoIk5vIHJvbGwg"
    "eWV0LiIpCiAgICAgICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwuc2V0V29yZFdyYXAoVHJ1ZSkK"
    "ICAgICAgICBybC5hZGRXaWRnZXQoc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwpCiAgICAgICAgcm9v"
    "dC5hZGRXaWRnZXQocmVzdWx0X3dyYXApCgogICAgICAgIG1pZCA9IFFIQm94TGF5b3V0KCkKICAg"
    "ICAgICBoaXN0b3J5X3dyYXAgPSBRRnJhbWUoKQogICAgICAgIGhpc3Rvcnlfd3JhcC5zZXRTdHls"
    "ZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVS"
    "fTsiKQogICAgICAgIGh3ID0gUVZCb3hMYXlvdXQoaGlzdG9yeV93cmFwKQogICAgICAgIGh3LnNl"
    "dENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQoKICAgICAgICBzZWxmLmhpc3RvcnlfdGFicyA9"
    "IFFUYWJXaWRnZXQoKQogICAgICAgIHNlbGYuY3VycmVudF90YWJsZSA9IHNlbGYuX21ha2Vfcm9s"
    "bF90YWJsZSgpCiAgICAgICAgc2VsZi5oaXN0b3J5X3RhYmxlID0gc2VsZi5fbWFrZV9yb2xsX3Rh"
    "YmxlKCkKICAgICAgICBzZWxmLmhpc3RvcnlfdGFicy5hZGRUYWIoc2VsZi5jdXJyZW50X3RhYmxl"
    "LCAiQ3VycmVudCBSb2xscyIpCiAgICAgICAgc2VsZi5oaXN0b3J5X3RhYnMuYWRkVGFiKHNlbGYu"
    "aGlzdG9yeV90YWJsZSwgIlJvbGwgSGlzdG9yeSIpCiAgICAgICAgaHcuYWRkV2lkZ2V0KHNlbGYu"
    "aGlzdG9yeV90YWJzLCAxKQoKICAgICAgICBoaXN0b3J5X2FjdGlvbnMgPSBRSEJveExheW91dCgp"
    "CiAgICAgICAgc2VsZi5jbGVhcl9oaXN0b3J5X2J0biA9IFFQdXNoQnV0dG9uKCJDbGVhciBSb2xs"
    "IEhpc3RvcnkiKQogICAgICAgIGhpc3RvcnlfYWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5jbGVhcl9o"
    "aXN0b3J5X2J0bikKICAgICAgICBoaXN0b3J5X2FjdGlvbnMuYWRkU3RyZXRjaCgxKQogICAgICAg"
    "IGh3LmFkZExheW91dChoaXN0b3J5X2FjdGlvbnMpCgogICAgICAgIHNlbGYuZ3JhbmRfdG90YWxf"
    "bGJsID0gUUxhYmVsKCJHcmFuZCBUb3RhbDogMCIpCiAgICAgICAgc2VsZi5ncmFuZF90b3RhbF9s"
    "Ymwuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiAxMnB4OyBmb250"
    "LXdlaWdodDogYm9sZDsiKQogICAgICAgIGh3LmFkZFdpZGdldChzZWxmLmdyYW5kX3RvdGFsX2xi"
    "bCkKCiAgICAgICAgc2F2ZWRfd3JhcCA9IFFGcmFtZSgpCiAgICAgICAgc2F2ZWRfd3JhcC5zZXRT"
    "dHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9S"
    "REVSfTsiKQogICAgICAgIHN3ID0gUVZCb3hMYXlvdXQoc2F2ZWRfd3JhcCkKICAgICAgICBzdy5z"
    "ZXRDb250ZW50c01hcmdpbnMoNiwgNiwgNiwgNikKICAgICAgICBzdy5hZGRXaWRnZXQoUUxhYmVs"
    "KCJTYXZlZCAvIENvbW1vbiBSb2xscyIpKQoKICAgICAgICBzdy5hZGRXaWRnZXQoUUxhYmVsKCJT"
    "YXZlZCIpKQogICAgICAgIHNlbGYuc2F2ZWRfbGlzdCA9IFFMaXN0V2lkZ2V0KCkKICAgICAgICBz"
    "dy5hZGRXaWRnZXQoc2VsZi5zYXZlZF9saXN0LCAxKQogICAgICAgIHNhdmVkX2FjdGlvbnMgPSBR"
    "SEJveExheW91dCgpCiAgICAgICAgc2VsZi5ydW5fc2F2ZWRfYnRuID0gUVB1c2hCdXR0b24oIlJ1"
    "biIpCiAgICAgICAgc2VsZi5sb2FkX3NhdmVkX2J0biA9IFFQdXNoQnV0dG9uKCJMb2FkL0VkaXQi"
    "KQogICAgICAgIHNlbGYuZGVsZXRlX3NhdmVkX2J0biA9IFFQdXNoQnV0dG9uKCJEZWxldGUiKQog"
    "ICAgICAgIHNhdmVkX2FjdGlvbnMuYWRkV2lkZ2V0KHNlbGYucnVuX3NhdmVkX2J0bikKICAgICAg"
    "ICBzYXZlZF9hY3Rpb25zLmFkZFdpZGdldChzZWxmLmxvYWRfc2F2ZWRfYnRuKQogICAgICAgIHNh"
    "dmVkX2FjdGlvbnMuYWRkV2lkZ2V0KHNlbGYuZGVsZXRlX3NhdmVkX2J0bikKICAgICAgICBzdy5h"
    "ZGRMYXlvdXQoc2F2ZWRfYWN0aW9ucykKCiAgICAgICAgc3cuYWRkV2lkZ2V0KFFMYWJlbCgiQXV0"
    "by1EZXRlY3RlZCBDb21tb24iKSkKICAgICAgICBzZWxmLmNvbW1vbl9saXN0ID0gUUxpc3RXaWRn"
    "ZXQoKQogICAgICAgIHN3LmFkZFdpZGdldChzZWxmLmNvbW1vbl9saXN0LCAxKQogICAgICAgIGNv"
    "bW1vbl9hY3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYucHJvbW90ZV9jb21tb25f"
    "YnRuID0gUVB1c2hCdXR0b24oIlByb21vdGUgdG8gU2F2ZWQiKQogICAgICAgIHNlbGYuZGlzbWlz"
    "c19jb21tb25fYnRuID0gUVB1c2hCdXR0b24oIkRpc21pc3MiKQogICAgICAgIGNvbW1vbl9hY3Rp"
    "b25zLmFkZFdpZGdldChzZWxmLnByb21vdGVfY29tbW9uX2J0bikKICAgICAgICBjb21tb25fYWN0"
    "aW9ucy5hZGRXaWRnZXQoc2VsZi5kaXNtaXNzX2NvbW1vbl9idG4pCiAgICAgICAgc3cuYWRkTGF5"
    "b3V0KGNvbW1vbl9hY3Rpb25zKQoKICAgICAgICBzZWxmLmNvbW1vbl9oaW50ID0gUUxhYmVsKCJD"
    "b21tb24gc2lnbmF0dXJlIHRyYWNraW5nIGFjdGl2ZS4iKQogICAgICAgIHNlbGYuY29tbW9uX2hp"
    "bnQuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogOXB4OyIp"
    "CiAgICAgICAgc3cuYWRkV2lkZ2V0KHNlbGYuY29tbW9uX2hpbnQpCgogICAgICAgIG1pZC5hZGRX"
    "aWRnZXQoaGlzdG9yeV93cmFwLCAzKQogICAgICAgIG1pZC5hZGRXaWRnZXQoc2F2ZWRfd3JhcCwg"
    "MikKICAgICAgICByb290LmFkZExheW91dChtaWQsIDEpCgogICAgICAgIHNlbGYucm9sbF9wb29s"
    "X2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fcm9sbF9jdXJyZW50X3Bvb2wpCiAgICAgICAgc2Vs"
    "Zi5yZXNldF9wb29sX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fcmVzZXRfcG9vbCkKICAgICAg"
    "ICBzZWxmLnNhdmVfcG9vbF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3NhdmVfcG9vbCkKICAg"
    "ICAgICBzZWxmLmNsZWFyX2hpc3RvcnlfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9jbGVhcl9o"
    "aXN0b3J5KQoKICAgICAgICBzZWxmLnNhdmVkX2xpc3QuaXRlbURvdWJsZUNsaWNrZWQuY29ubmVj"
    "dChsYW1iZGEgaXRlbTogc2VsZi5fcnVuX3NhdmVkX3JvbGwoaXRlbS5kYXRhKFF0Lkl0ZW1EYXRh"
    "Um9sZS5Vc2VyUm9sZSkpKQogICAgICAgIHNlbGYuY29tbW9uX2xpc3QuaXRlbURvdWJsZUNsaWNr"
    "ZWQuY29ubmVjdChsYW1iZGEgaXRlbTogc2VsZi5fcnVuX3NhdmVkX3JvbGwoaXRlbS5kYXRhKFF0"
    "Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkpKQoKICAgICAgICBzZWxmLnJ1bl9zYXZlZF9idG4uY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX3J1bl9zZWxlY3RlZF9zYXZlZCkKICAgICAgICBzZWxmLmxvYWRf"
    "c2F2ZWRfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9sb2FkX3NlbGVjdGVkX3NhdmVkKQogICAg"
    "ICAgIHNlbGYuZGVsZXRlX3NhdmVkX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZGVsZXRlX3Nl"
    "bGVjdGVkX3NhdmVkKQogICAgICAgIHNlbGYucHJvbW90ZV9jb21tb25fYnRuLmNsaWNrZWQuY29u"
    "bmVjdChzZWxmLl9wcm9tb3RlX3NlbGVjdGVkX2NvbW1vbikKICAgICAgICBzZWxmLmRpc21pc3Nf"
    "Y29tbW9uX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZGlzbWlzc19zZWxlY3RlZF9jb21tb24p"
    "CgogICAgICAgIHNlbGYuY3VycmVudF90YWJsZS5zZXRDb250ZXh0TWVudVBvbGljeShRdC5Db250"
    "ZXh0TWVudVBvbGljeS5DdXN0b21Db250ZXh0TWVudSkKICAgICAgICBzZWxmLmhpc3RvcnlfdGFi"
    "bGUuc2V0Q29udGV4dE1lbnVQb2xpY3koUXQuQ29udGV4dE1lbnVQb2xpY3kuQ3VzdG9tQ29udGV4"
    "dE1lbnUpCiAgICAgICAgc2VsZi5jdXJyZW50X3RhYmxlLmN1c3RvbUNvbnRleHRNZW51UmVxdWVz"
    "dGVkLmNvbm5lY3QobGFtYmRhIHBvczogc2VsZi5fc2hvd19yb2xsX2NvbnRleHRfbWVudShzZWxm"
    "LmN1cnJlbnRfdGFibGUsIHBvcykpCiAgICAgICAgc2VsZi5oaXN0b3J5X3RhYmxlLmN1c3RvbUNv"
    "bnRleHRNZW51UmVxdWVzdGVkLmNvbm5lY3QobGFtYmRhIHBvczogc2VsZi5fc2hvd19yb2xsX2Nv"
    "bnRleHRfbWVudShzZWxmLmhpc3RvcnlfdGFibGUsIHBvcykpCgogICAgZGVmIF9tYWtlX3JvbGxf"
    "dGFibGUoc2VsZikgLT4gUVRhYmxlV2lkZ2V0OgogICAgICAgIHRibCA9IFFUYWJsZVdpZGdldCgw"
    "LCA2KQogICAgICAgIHRibC5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiVGltZXN0YW1wIiwg"
    "IkxhYmVsIiwgIkV4cHJlc3Npb24iLCAiUmF3IiwgIk1vZGlmaWVyIiwgIlRvdGFsIl0pCiAgICAg"
    "ICAgdGJsLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZShRSGVhZGVyVmll"
    "dy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgdGJsLnZlcnRpY2FsSGVhZGVyKCkuc2V0Vmlz"
    "aWJsZShGYWxzZSkKICAgICAgICB0Ymwuc2V0RWRpdFRyaWdnZXJzKFFBYnN0cmFjdEl0ZW1WaWV3"
    "LkVkaXRUcmlnZ2VyLk5vRWRpdFRyaWdnZXJzKQogICAgICAgIHRibC5zZXRTZWxlY3Rpb25CZWhh"
    "dmlvcihRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dzKQogICAg"
    "ICAgIHRibC5zZXRTb3J0aW5nRW5hYmxlZChGYWxzZSkKICAgICAgICByZXR1cm4gdGJsCgogICAg"
    "ZGVmIF9zb3J0ZWRfcG9vbF9pdGVtcyhzZWxmKToKICAgICAgICByZXR1cm4gWyhkLCBzZWxmLmN1"
    "cnJlbnRfcG9vbC5nZXQoZCwgMCkpIGZvciBkIGluIHNlbGYuVFJBWV9PUkRFUiBpZiBzZWxmLmN1"
    "cnJlbnRfcG9vbC5nZXQoZCwgMCkgPiAwXQoKICAgIGRlZiBfcG9vbF9leHByZXNzaW9uKHNlbGYs"
    "IHBvb2w6IGRpY3Rbc3RyLCBpbnRdIHwgTm9uZSA9IE5vbmUpIC0+IHN0cjoKICAgICAgICBwID0g"
    "cG9vbCBpZiBwb29sIGlzIG5vdCBOb25lIGVsc2Ugc2VsZi5jdXJyZW50X3Bvb2wKICAgICAgICBw"
    "YXJ0cyA9IFtmIntxdHl9e2RpZX0iIGZvciBkaWUsIHF0eSBpbiBbKGQsIHAuZ2V0KGQsIDApKSBm"
    "b3IgZCBpbiBzZWxmLlRSQVlfT1JERVJdIGlmIHF0eSA+IDBdCiAgICAgICAgcmV0dXJuICIgKyAi"
    "LmpvaW4ocGFydHMpIGlmIHBhcnRzIGVsc2UgIihlbXB0eSkiCgogICAgZGVmIF9ub3JtYWxpemVf"
    "cG9vbF9zaWduYXR1cmUoc2VsZiwgcG9vbDogZGljdFtzdHIsIGludF0sIG1vZGlmaWVyOiBpbnQs"
    "IHJ1bGVfaWQ6IHN0ciA9ICIiKSAtPiBzdHI6CiAgICAgICAgcGFydHMgPSBbZiJ7cG9vbC5nZXQo"
    "ZCwgMCl9e2R9IiBmb3IgZCBpbiBzZWxmLlRSQVlfT1JERVIgaWYgcG9vbC5nZXQoZCwgMCkgPiAw"
    "XQogICAgICAgIGJhc2UgPSAiKyIuam9pbihwYXJ0cykgaWYgcGFydHMgZWxzZSAiMCIKICAgICAg"
    "ICBzaWcgPSBmIntiYXNlfXttb2RpZmllcjorZH0iCiAgICAgICAgcmV0dXJuIGYie3NpZ31fe3J1"
    "bGVfaWR9IiBpZiBydWxlX2lkIGVsc2Ugc2lnCgogICAgZGVmIF9kaWNlX2xhYmVsKHNlbGYsIGRp"
    "ZV90eXBlOiBzdHIpIC0+IHN0cjoKICAgICAgICByZXR1cm4gImQlIiBpZiBkaWVfdHlwZSA9PSAi"
    "ZCUiIGVsc2UgZGllX3R5cGUKCiAgICBkZWYgX3JvbGxfc2luZ2xlX3ZhbHVlKHNlbGYsIGRpZV90"
    "eXBlOiBzdHIpOgogICAgICAgIGlmIGRpZV90eXBlID09ICJkJSI6CiAgICAgICAgICAgIHRlbnMg"
    "PSByYW5kb20ucmFuZGludCgwLCA5KSAqIDEwCiAgICAgICAgICAgIHJldHVybiB0ZW5zLCAoIjAw"
    "IiBpZiB0ZW5zID09IDAgZWxzZSBzdHIodGVucykpCiAgICAgICAgc2lkZXMgPSBpbnQoZGllX3R5"
    "cGUucmVwbGFjZSgiZCIsICIiKSkKICAgICAgICB2YWwgPSByYW5kb20ucmFuZGludCgxLCBzaWRl"
    "cykKICAgICAgICByZXR1cm4gdmFsLCBzdHIodmFsKQoKICAgIGRlZiBfcm9sbF9wb29sX2RhdGEo"
    "c2VsZiwgcG9vbDogZGljdFtzdHIsIGludF0sIG1vZGlmaWVyOiBpbnQsIGxhYmVsOiBzdHIsIHJ1"
    "bGVfaWQ6IHN0ciA9ICIiKSAtPiBkaWN0OgogICAgICAgIGdyb3VwZWRfbnVtZXJpYzogZGljdFtz"
    "dHIsIGxpc3RbaW50XV0gPSB7fQogICAgICAgIGdyb3VwZWRfZGlzcGxheTogZGljdFtzdHIsIGxp"
    "c3Rbc3RyXV0gPSB7fQogICAgICAgIHN1YnRvdGFsID0gMAogICAgICAgIHVzZWRfcG9vbCA9IGRp"
    "Y3QocG9vbCkKCiAgICAgICAgaWYgcnVsZV9pZCBhbmQgcnVsZV9pZCBpbiBzZWxmLnJ1bGVfZGVm"
    "aW5pdGlvbnMgYW5kIChub3QgcG9vbCBvciBsZW4oW2sgZm9yIGssIHYgaW4gcG9vbC5pdGVtcygp"
    "IGlmIHYgPiAwXSkgPT0gMSk6CiAgICAgICAgICAgIHJ1bGUgPSBzZWxmLnJ1bGVfZGVmaW5pdGlv"
    "bnMuZ2V0KHJ1bGVfaWQsIHt9KQogICAgICAgICAgICBzaWRlcyA9IGludChydWxlLmdldCgiZGlj"
    "ZV9zaWRlcyIsIDYpKQogICAgICAgICAgICBjb3VudCA9IGludChydWxlLmdldCgiZGljZV9jb3Vu"
    "dCIsIDEpKQogICAgICAgICAgICBkaWUgPSBmImR7c2lkZXN9IgogICAgICAgICAgICB1c2VkX3Bv"
    "b2wgPSB7ZGllOiBjb3VudH0KICAgICAgICAgICAgcmF3ID0gW3JhbmRvbS5yYW5kaW50KDEsIHNp"
    "ZGVzKSBmb3IgXyBpbiByYW5nZShjb3VudCldCiAgICAgICAgICAgIGRyb3BfbG93ID0gaW50KHJ1"
    "bGUuZ2V0KCJkcm9wX2xvd2VzdF9jb3VudCIsIDApIG9yIDApCiAgICAgICAgICAgIGRyb3BfaGln"
    "aCA9IGludChydWxlLmdldCgiZHJvcF9oaWdoZXN0X2NvdW50IiwgMCkgb3IgMCkKICAgICAgICAg"
    "ICAga2VwdCA9IGxpc3QocmF3KQogICAgICAgICAgICBpZiBkcm9wX2xvdyA+IDA6CiAgICAgICAg"
    "ICAgICAgICBrZXB0ID0gc29ydGVkKGtlcHQpW2Ryb3BfbG93Ol0KICAgICAgICAgICAgaWYgZHJv"
    "cF9oaWdoID4gMDoKICAgICAgICAgICAgICAgIGtlcHQgPSBzb3J0ZWQoa2VwdClbOi1kcm9wX2hp"
    "Z2hdIGlmIGRyb3BfaGlnaCA8IGxlbihrZXB0KSBlbHNlIFtdCiAgICAgICAgICAgIGdyb3VwZWRf"
    "bnVtZXJpY1tkaWVdID0gcmF3CiAgICAgICAgICAgIGdyb3VwZWRfZGlzcGxheVtkaWVdID0gW3N0"
    "cih2KSBmb3IgdiBpbiByYXddCiAgICAgICAgICAgIHN1YnRvdGFsID0gc3VtKGtlcHQpCiAgICAg"
    "ICAgZWxzZToKICAgICAgICAgICAgZm9yIGRpZSBpbiBzZWxmLlRSQVlfT1JERVI6CiAgICAgICAg"
    "ICAgICAgICBxdHkgPSBpbnQocG9vbC5nZXQoZGllLCAwKSBvciAwKQogICAgICAgICAgICAgICAg"
    "aWYgcXR5IDw9IDA6CiAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgICAg"
    "IGdyb3VwZWRfbnVtZXJpY1tkaWVdID0gW10KICAgICAgICAgICAgICAgIGdyb3VwZWRfZGlzcGxh"
    "eVtkaWVdID0gW10KICAgICAgICAgICAgICAgIGZvciBfIGluIHJhbmdlKHF0eSk6CiAgICAgICAg"
    "ICAgICAgICAgICAgbnVtLCBkaXNwID0gc2VsZi5fcm9sbF9zaW5nbGVfdmFsdWUoZGllKQogICAg"
    "ICAgICAgICAgICAgICAgIGdyb3VwZWRfbnVtZXJpY1tkaWVdLmFwcGVuZChudW0pCiAgICAgICAg"
    "ICAgICAgICAgICAgZ3JvdXBlZF9kaXNwbGF5W2RpZV0uYXBwZW5kKGRpc3ApCiAgICAgICAgICAg"
    "ICAgICAgICAgc3VidG90YWwgKz0gaW50KG51bSkKCiAgICAgICAgdG90YWwgPSBzdWJ0b3RhbCAr"
    "IGludChtb2RpZmllcikKICAgICAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDol"
    "TTolUyIpCiAgICAgICAgZXhwciA9IHNlbGYuX3Bvb2xfZXhwcmVzc2lvbih1c2VkX3Bvb2wpCiAg"
    "ICAgICAgaWYgcnVsZV9pZDoKICAgICAgICAgICAgcnVsZV9uYW1lID0gc2VsZi5ydWxlX2RlZmlu"
    "aXRpb25zLmdldChydWxlX2lkLCB7fSkuZ2V0KCJuYW1lIiwgcnVsZV9pZCkKICAgICAgICAgICAg"
    "ZXhwciA9IGYie2V4cHJ9ICh7cnVsZV9uYW1lfSkiCgogICAgICAgIGV2ZW50ID0gewogICAgICAg"
    "ICAgICAiaWQiOiBmInJvbGxfe3V1aWQudXVpZDQoKS5oZXhbOjEyXX0iLAogICAgICAgICAgICAi"
    "dGltZXN0YW1wIjogdHMsCiAgICAgICAgICAgICJsYWJlbCI6IGxhYmVsLAogICAgICAgICAgICAi"
    "cG9vbCI6IHVzZWRfcG9vbCwKICAgICAgICAgICAgImdyb3VwZWRfcmF3IjogZ3JvdXBlZF9udW1l"
    "cmljLAogICAgICAgICAgICAiZ3JvdXBlZF9yYXdfZGlzcGxheSI6IGdyb3VwZWRfZGlzcGxheSwK"
    "ICAgICAgICAgICAgInN1YnRvdGFsIjogc3VidG90YWwsCiAgICAgICAgICAgICJtb2RpZmllciI6"
    "IGludChtb2RpZmllciksCiAgICAgICAgICAgICJmaW5hbF90b3RhbCI6IGludCh0b3RhbCksCiAg"
    "ICAgICAgICAgICJleHByZXNzaW9uIjogZXhwciwKICAgICAgICAgICAgInNvdXJjZSI6ICJkaWNl"
    "X3JvbGxlciIsCiAgICAgICAgICAgICJydWxlX2lkIjogcnVsZV9pZCBvciBOb25lLAogICAgICAg"
    "IH0KICAgICAgICByZXR1cm4gZXZlbnQKCiAgICBkZWYgX2FkZF9kaWVfdG9fcG9vbChzZWxmLCBk"
    "aWVfdHlwZTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuY3VycmVudF9wb29sW2RpZV90eXBl"
    "XSA9IGludChzZWxmLmN1cnJlbnRfcG9vbC5nZXQoZGllX3R5cGUsIDApKSArIDEKICAgICAgICBz"
    "ZWxmLl9yZWZyZXNoX3Bvb2xfZWRpdG9yKCkKICAgICAgICBzZWxmLmN1cnJlbnRfcmVzdWx0X2xi"
    "bC5zZXRUZXh0KGYiQ3VycmVudCBQb29sOiB7c2VsZi5fcG9vbF9leHByZXNzaW9uKCl9IikKCiAg"
    "ICBkZWYgX2FkanVzdF9wb29sX2RpZShzZWxmLCBkaWVfdHlwZTogc3RyLCBkZWx0YTogaW50KSAt"
    "PiBOb25lOgogICAgICAgIG5ld192YWwgPSBpbnQoc2VsZi5jdXJyZW50X3Bvb2wuZ2V0KGRpZV90"
    "eXBlLCAwKSkgKyBpbnQoZGVsdGEpCiAgICAgICAgaWYgbmV3X3ZhbCA8PSAwOgogICAgICAgICAg"
    "ICBzZWxmLmN1cnJlbnRfcG9vbC5wb3AoZGllX3R5cGUsIE5vbmUpCiAgICAgICAgZWxzZToKICAg"
    "ICAgICAgICAgc2VsZi5jdXJyZW50X3Bvb2xbZGllX3R5cGVdID0gbmV3X3ZhbAogICAgICAgIHNl"
    "bGYuX3JlZnJlc2hfcG9vbF9lZGl0b3IoKQoKICAgIGRlZiBfcmVmcmVzaF9wb29sX2VkaXRvcihz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHdoaWxlIHNlbGYucG9vbF9lbnRyaWVzX2xheW91dC5jb3Vu"
    "dCgpOgogICAgICAgICAgICBpdGVtID0gc2VsZi5wb29sX2VudHJpZXNfbGF5b3V0LnRha2VBdCgw"
    "KQogICAgICAgICAgICB3ID0gaXRlbS53aWRnZXQoKQogICAgICAgICAgICBpZiB3IGlzIG5vdCBO"
    "b25lOgogICAgICAgICAgICAgICAgdy5kZWxldGVMYXRlcigpCgogICAgICAgIGZvciBkaWUsIHF0"
    "eSBpbiBzZWxmLl9zb3J0ZWRfcG9vbF9pdGVtcygpOgogICAgICAgICAgICBib3ggPSBRRnJhbWUo"
    "KQogICAgICAgICAgICBib3guc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHM307IGJv"
    "cmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRpdXM6IDZweDsiKQogICAgICAg"
    "ICAgICBsYXkgPSBRSEJveExheW91dChib3gpCiAgICAgICAgICAgIGxheS5zZXRDb250ZW50c01h"
    "cmdpbnMoNiwgNCwgNiwgNCkKICAgICAgICAgICAgbGF5LnNldFNwYWNpbmcoNCkKICAgICAgICAg"
    "ICAgbGJsID0gUUxhYmVsKGYie2RpZX0geHtxdHl9IikKICAgICAgICAgICAgbWludXNfYnRuID0g"
    "UVB1c2hCdXR0b24oIuKIkiIpCiAgICAgICAgICAgIHBsdXNfYnRuID0gUVB1c2hCdXR0b24oIisi"
    "KQogICAgICAgICAgICBtaW51c19idG4uc2V0Rml4ZWRXaWR0aCgyNCkKICAgICAgICAgICAgcGx1"
    "c19idG4uc2V0Rml4ZWRXaWR0aCgyNCkKICAgICAgICAgICAgbWludXNfYnRuLmNsaWNrZWQuY29u"
    "bmVjdChsYW1iZGEgXz1GYWxzZSwgZD1kaWU6IHNlbGYuX2FkanVzdF9wb29sX2RpZShkLCAtMSkp"
    "CiAgICAgICAgICAgIHBsdXNfYnRuLmNsaWNrZWQuY29ubmVjdChsYW1iZGEgXz1GYWxzZSwgZD1k"
    "aWU6IHNlbGYuX2FkanVzdF9wb29sX2RpZShkLCArMSkpCiAgICAgICAgICAgIGxheS5hZGRXaWRn"
    "ZXQobGJsKQogICAgICAgICAgICBsYXkuYWRkV2lkZ2V0KG1pbnVzX2J0bikKICAgICAgICAgICAg"
    "bGF5LmFkZFdpZGdldChwbHVzX2J0bikKICAgICAgICAgICAgc2VsZi5wb29sX2VudHJpZXNfbGF5"
    "b3V0LmFkZFdpZGdldChib3gpCgogICAgICAgIHNlbGYucG9vbF9lbnRyaWVzX2xheW91dC5hZGRT"
    "dHJldGNoKDEpCiAgICAgICAgc2VsZi5wb29sX2V4cHJfbGJsLnNldFRleHQoZiJQb29sOiB7c2Vs"
    "Zi5fcG9vbF9leHByZXNzaW9uKCl9IikKCiAgICBkZWYgX3F1aWNrX3JvbGxfc2luZ2xlX2RpZShz"
    "ZWxmLCBkaWVfdHlwZTogc3RyKSAtPiBOb25lOgogICAgICAgIGV2ZW50ID0gc2VsZi5fcm9sbF9w"
    "b29sX2RhdGEoe2RpZV90eXBlOiAxfSwgaW50KHNlbGYubW9kX3NwaW4udmFsdWUoKSksIHNlbGYu"
    "bGFiZWxfZWRpdC50ZXh0KCkuc3RyaXAoKSwgc2VsZi5ydWxlX2NvbWJvLmN1cnJlbnREYXRhKCkg"
    "b3IgIiIpCiAgICAgICAgc2VsZi5fcmVjb3JkX3JvbGxfZXZlbnQoZXZlbnQpCgogICAgZGVmIF9y"
    "b2xsX2N1cnJlbnRfcG9vbChzZWxmKSAtPiBOb25lOgogICAgICAgIHBvb2wgPSBkaWN0KHNlbGYu"
    "Y3VycmVudF9wb29sKQogICAgICAgIHJ1bGVfaWQgPSBzZWxmLnJ1bGVfY29tYm8uY3VycmVudERh"
    "dGEoKSBvciAiIgogICAgICAgIGlmIG5vdCBwb29sIGFuZCBub3QgcnVsZV9pZDoKICAgICAgICAg"
    "ICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIkRpY2UgUm9sbGVyIiwgIkN1cnJlbnQg"
    "UG9vbCBpcyBlbXB0eS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBldmVudCA9IHNlbGYu"
    "X3JvbGxfcG9vbF9kYXRhKHBvb2wsIGludChzZWxmLm1vZF9zcGluLnZhbHVlKCkpLCBzZWxmLmxh"
    "YmVsX2VkaXQudGV4dCgpLnN0cmlwKCksIHJ1bGVfaWQpCiAgICAgICAgc2VsZi5fcmVjb3JkX3Jv"
    "bGxfZXZlbnQoZXZlbnQpCgogICAgZGVmIF9yZWNvcmRfcm9sbF9ldmVudChzZWxmLCBldmVudDog"
    "ZGljdCkgLT4gTm9uZToKICAgICAgICBzZWxmLnJvbGxfZXZlbnRzLmFwcGVuZChldmVudCkKICAg"
    "ICAgICBzZWxmLmV2ZW50X2J5X2lkW2V2ZW50WyJpZCJdXSA9IGV2ZW50CiAgICAgICAgc2VsZi5j"
    "dXJyZW50X3JvbGxfaWRzID0gW2V2ZW50WyJpZCJdXQoKICAgICAgICBzZWxmLl9yZXBsYWNlX2N1"
    "cnJlbnRfcm93cyhbZXZlbnRdKQogICAgICAgIHNlbGYuX2FwcGVuZF9oaXN0b3J5X3JvdyhldmVu"
    "dCkKICAgICAgICBzZWxmLl91cGRhdGVfZ3JhbmRfdG90YWwoKQogICAgICAgIHNlbGYuX3VwZGF0"
    "ZV9yZXN1bHRfZGlzcGxheShldmVudCkKICAgICAgICBzZWxmLl90cmFja19jb21tb25fc2lnbmF0"
    "dXJlKGV2ZW50KQogICAgICAgIHNlbGYuX3BsYXlfcm9sbF9zb3VuZCgpCgogICAgZGVmIF9yZXBs"
    "YWNlX2N1cnJlbnRfcm93cyhzZWxmLCBldmVudHM6IGxpc3RbZGljdF0pIC0+IE5vbmU6CiAgICAg"
    "ICAgc2VsZi5jdXJyZW50X3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGV2ZW50IGlu"
    "IGV2ZW50czoKICAgICAgICAgICAgc2VsZi5fYXBwZW5kX3RhYmxlX3JvdyhzZWxmLmN1cnJlbnRf"
    "dGFibGUsIGV2ZW50KQoKICAgIGRlZiBfYXBwZW5kX2hpc3Rvcnlfcm93KHNlbGYsIGV2ZW50OiBk"
    "aWN0KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2FwcGVuZF90YWJsZV9yb3coc2VsZi5oaXN0b3J5"
    "X3RhYmxlLCBldmVudCkKICAgICAgICBzZWxmLmhpc3RvcnlfdGFibGUuc2Nyb2xsVG9Cb3R0b20o"
    "KQoKICAgIGRlZiBfZm9ybWF0X3JhdyhzZWxmLCBldmVudDogZGljdCkgLT4gc3RyOgogICAgICAg"
    "IGdyb3VwZWQgPSBldmVudC5nZXQoImdyb3VwZWRfcmF3X2Rpc3BsYXkiLCB7fSkgb3Ige30KICAg"
    "ICAgICBiaXRzID0gW10KICAgICAgICBmb3IgZGllIGluIHNlbGYuVFJBWV9PUkRFUjoKICAgICAg"
    "ICAgICAgdmFscyA9IGdyb3VwZWQuZ2V0KGRpZSkKICAgICAgICAgICAgaWYgdmFsczoKICAgICAg"
    "ICAgICAgICAgIGJpdHMuYXBwZW5kKGYie2RpZX06IHsnLCcuam9pbihzdHIodikgZm9yIHYgaW4g"
    "dmFscyl9IikKICAgICAgICByZXR1cm4gIiB8ICIuam9pbihiaXRzKQoKICAgIGRlZiBfYXBwZW5k"
    "X3RhYmxlX3JvdyhzZWxmLCB0YWJsZTogUVRhYmxlV2lkZ2V0LCBldmVudDogZGljdCkgLT4gTm9u"
    "ZToKICAgICAgICByb3cgPSB0YWJsZS5yb3dDb3VudCgpCiAgICAgICAgdGFibGUuaW5zZXJ0Um93"
    "KHJvdykKCiAgICAgICAgdHNfaXRlbSA9IFFUYWJsZVdpZGdldEl0ZW0oZXZlbnRbInRpbWVzdGFt"
    "cCJdKQogICAgICAgIHRzX2l0ZW0uc2V0RGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUsIGV2"
    "ZW50WyJpZCJdKQogICAgICAgIHRhYmxlLnNldEl0ZW0ocm93LCAwLCB0c19pdGVtKQogICAgICAg"
    "IHRhYmxlLnNldEl0ZW0ocm93LCAxLCBRVGFibGVXaWRnZXRJdGVtKGV2ZW50LmdldCgibGFiZWwi"
    "LCAiIikpKQogICAgICAgIHRhYmxlLnNldEl0ZW0ocm93LCAyLCBRVGFibGVXaWRnZXRJdGVtKGV2"
    "ZW50LmdldCgiZXhwcmVzc2lvbiIsICIiKSkpCiAgICAgICAgdGFibGUuc2V0SXRlbShyb3csIDMs"
    "IFFUYWJsZVdpZGdldEl0ZW0oc2VsZi5fZm9ybWF0X3JhdyhldmVudCkpKQoKICAgICAgICBtb2Rf"
    "c3BpbiA9IFFTcGluQm94KCkKICAgICAgICBtb2Rfc3Bpbi5zZXRSYW5nZSgtOTk5LCA5OTkpCiAg"
    "ICAgICAgbW9kX3NwaW4uc2V0VmFsdWUoaW50KGV2ZW50LmdldCgibW9kaWZpZXIiLCAwKSkpCiAg"
    "ICAgICAgbW9kX3NwaW4udmFsdWVDaGFuZ2VkLmNvbm5lY3QobGFtYmRhIHZhbCwgZWlkPWV2ZW50"
    "WyJpZCJdOiBzZWxmLl9vbl9tb2RpZmllcl9jaGFuZ2VkKGVpZCwgdmFsKSkKICAgICAgICB0YWJs"
    "ZS5zZXRDZWxsV2lkZ2V0KHJvdywgNCwgbW9kX3NwaW4pCgogICAgICAgIHRhYmxlLnNldEl0ZW0o"
    "cm93LCA1LCBRVGFibGVXaWRnZXRJdGVtKHN0cihldmVudC5nZXQoImZpbmFsX3RvdGFsIiwgMCkp"
    "KSkKCiAgICBkZWYgX3N5bmNfcm93X2J5X2V2ZW50X2lkKHNlbGYsIHRhYmxlOiBRVGFibGVXaWRn"
    "ZXQsIGV2ZW50X2lkOiBzdHIsIGV2ZW50OiBkaWN0KSAtPiBOb25lOgogICAgICAgIGZvciByb3cg"
    "aW4gcmFuZ2UodGFibGUucm93Q291bnQoKSk6CiAgICAgICAgICAgIGl0ID0gdGFibGUuaXRlbShy"
    "b3csIDApCiAgICAgICAgICAgIGlmIGl0IGFuZCBpdC5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2Vy"
    "Um9sZSkgPT0gZXZlbnRfaWQ6CiAgICAgICAgICAgICAgICB0YWJsZS5zZXRJdGVtKHJvdywgNSwg"
    "UVRhYmxlV2lkZ2V0SXRlbShzdHIoZXZlbnQuZ2V0KCJmaW5hbF90b3RhbCIsIDApKSkpCiAgICAg"
    "ICAgICAgICAgICB0YWJsZS5zZXRJdGVtKHJvdywgMywgUVRhYmxlV2lkZ2V0SXRlbShzZWxmLl9m"
    "b3JtYXRfcmF3KGV2ZW50KSkpCiAgICAgICAgICAgICAgICBicmVhawoKICAgIGRlZiBfb25fbW9k"
    "aWZpZXJfY2hhbmdlZChzZWxmLCBldmVudF9pZDogc3RyLCB2YWx1ZTogaW50KSAtPiBOb25lOgog"
    "ICAgICAgIGV2dCA9IHNlbGYuZXZlbnRfYnlfaWQuZ2V0KGV2ZW50X2lkKQogICAgICAgIGlmIG5v"
    "dCBldnQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGV2dFsibW9kaWZpZXIiXSA9IGludCh2"
    "YWx1ZSkKICAgICAgICBldnRbImZpbmFsX3RvdGFsIl0gPSBpbnQoZXZ0LmdldCgic3VidG90YWwi"
    "LCAwKSkgKyBpbnQodmFsdWUpCiAgICAgICAgc2VsZi5fc3luY19yb3dfYnlfZXZlbnRfaWQoc2Vs"
    "Zi5oaXN0b3J5X3RhYmxlLCBldmVudF9pZCwgZXZ0KQogICAgICAgIHNlbGYuX3N5bmNfcm93X2J5"
    "X2V2ZW50X2lkKHNlbGYuY3VycmVudF90YWJsZSwgZXZlbnRfaWQsIGV2dCkKICAgICAgICBzZWxm"
    "Ll91cGRhdGVfZ3JhbmRfdG90YWwoKQogICAgICAgIGlmIHNlbGYuY3VycmVudF9yb2xsX2lkcyBh"
    "bmQgc2VsZi5jdXJyZW50X3JvbGxfaWRzWzBdID09IGV2ZW50X2lkOgogICAgICAgICAgICBzZWxm"
    "Ll91cGRhdGVfcmVzdWx0X2Rpc3BsYXkoZXZ0KQoKICAgIGRlZiBfdXBkYXRlX2dyYW5kX3RvdGFs"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdG90YWwgPSBzdW0oaW50KGV2dC5nZXQoImZpbmFsX3Rv"
    "dGFsIiwgMCkpIGZvciBldnQgaW4gc2VsZi5yb2xsX2V2ZW50cykKICAgICAgICBzZWxmLmdyYW5k"
    "X3RvdGFsX2xibC5zZXRUZXh0KGYiR3JhbmQgVG90YWw6IHt0b3RhbH0iKQoKICAgIGRlZiBfdXBk"
    "YXRlX3Jlc3VsdF9kaXNwbGF5KHNlbGYsIGV2ZW50OiBkaWN0KSAtPiBOb25lOgogICAgICAgIGdy"
    "b3VwZWQgPSBldmVudC5nZXQoImdyb3VwZWRfcmF3X2Rpc3BsYXkiLCB7fSkgb3Ige30KICAgICAg"
    "ICBsaW5lcyA9IFtdCiAgICAgICAgZm9yIGRpZSBpbiBzZWxmLlRSQVlfT1JERVI6CiAgICAgICAg"
    "ICAgIHZhbHMgPSBncm91cGVkLmdldChkaWUpCiAgICAgICAgICAgIGlmIHZhbHM6CiAgICAgICAg"
    "ICAgICAgICBsaW5lcy5hcHBlbmQoZiJ7ZGllfSB4e2xlbih2YWxzKX0g4oaSIFt7JywnLmpvaW4o"
    "c3RyKHYpIGZvciB2IGluIHZhbHMpfV0iKQogICAgICAgIHJ1bGVfaWQgPSBldmVudC5nZXQoInJ1"
    "bGVfaWQiKQogICAgICAgIGlmIHJ1bGVfaWQ6CiAgICAgICAgICAgIHJ1bGVfbmFtZSA9IHNlbGYu"
    "cnVsZV9kZWZpbml0aW9ucy5nZXQocnVsZV9pZCwge30pLmdldCgibmFtZSIsIHJ1bGVfaWQpCiAg"
    "ICAgICAgICAgIGxpbmVzLmFwcGVuZChmIlJ1bGU6IHtydWxlX25hbWV9IikKICAgICAgICBsaW5l"
    "cy5hcHBlbmQoZiJNb2RpZmllcjoge2ludChldmVudC5nZXQoJ21vZGlmaWVyJywgMCkpOitkfSIp"
    "CiAgICAgICAgbGluZXMuYXBwZW5kKGYiVG90YWw6IHtldmVudC5nZXQoJ2ZpbmFsX3RvdGFsJywg"
    "MCl9IikKICAgICAgICBzZWxmLmN1cnJlbnRfcmVzdWx0X2xibC5zZXRUZXh0KCJcbiIuam9pbihs"
    "aW5lcykpCgoKICAgIGRlZiBfc2F2ZV9wb29sKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90"
    "IHNlbGYuY3VycmVudF9wb29sOgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihz"
    "ZWxmLCAiRGljZSBSb2xsZXIiLCAiQnVpbGQgYSBDdXJyZW50IFBvb2wgYmVmb3JlIHNhdmluZy4i"
    "KQogICAgICAgICAgICByZXR1cm4KICAgICAgICBkZWZhdWx0X25hbWUgPSBzZWxmLmxhYmVsX2Vk"
    "aXQudGV4dCgpLnN0cmlwKCkgb3Igc2VsZi5fcG9vbF9leHByZXNzaW9uKCkKICAgICAgICBuYW1l"
    "LCBvayA9IFFJbnB1dERpYWxvZy5nZXRUZXh0KHNlbGYsICJTYXZlIFBvb2wiLCAiU2F2ZWQgcm9s"
    "bCBuYW1lOiIsIHRleHQ9ZGVmYXVsdF9uYW1lKQogICAgICAgIGlmIG5vdCBvazoKICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgcGF5bG9hZCA9IHsKICAgICAgICAgICAgImlkIjogZiJzYXZlZF97"
    "dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICJuYW1lIjogbmFtZS5zdHJpcCgp"
    "IG9yIGRlZmF1bHRfbmFtZSwKICAgICAgICAgICAgInBvb2wiOiBkaWN0KHNlbGYuY3VycmVudF9w"
    "b29sKSwKICAgICAgICAgICAgIm1vZGlmaWVyIjogaW50KHNlbGYubW9kX3NwaW4udmFsdWUoKSks"
    "CiAgICAgICAgICAgICJydWxlX2lkIjogc2VsZi5ydWxlX2NvbWJvLmN1cnJlbnREYXRhKCkgb3Ig"
    "Tm9uZSwKICAgICAgICAgICAgIm5vdGVzIjogIiIsCiAgICAgICAgICAgICJjYXRlZ29yeSI6ICJz"
    "YXZlZCIsCiAgICAgICAgfQogICAgICAgIHNlbGYuc2F2ZWRfcm9sbHMuYXBwZW5kKHBheWxvYWQp"
    "CiAgICAgICAgc2VsZi5fcmVmcmVzaF9zYXZlZF9saXN0cygpCgogICAgZGVmIF9yZWZyZXNoX3Nh"
    "dmVkX2xpc3RzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zYXZlZF9saXN0LmNsZWFyKCkK"
    "ICAgICAgICBmb3IgaXRlbSBpbiBzZWxmLnNhdmVkX3JvbGxzOgogICAgICAgICAgICBleHByID0g"
    "c2VsZi5fcG9vbF9leHByZXNzaW9uKGl0ZW0uZ2V0KCJwb29sIiwge30pKQogICAgICAgICAgICB0"
    "eHQgPSBmIntpdGVtLmdldCgnbmFtZScpfSDigJQge2V4cHJ9IHtpbnQoaXRlbS5nZXQoJ21vZGlm"
    "aWVyJywgMCkpOitkfSIKICAgICAgICAgICAgbHcgPSBRTGlzdFdpZGdldEl0ZW0odHh0KQogICAg"
    "ICAgICAgICBsdy5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgaXRlbSkKICAgICAg"
    "ICAgICAgc2VsZi5zYXZlZF9saXN0LmFkZEl0ZW0obHcpCgogICAgICAgIHNlbGYuY29tbW9uX2xp"
    "c3QuY2xlYXIoKQogICAgICAgIHJhbmtlZCA9IHNvcnRlZChzZWxmLmNvbW1vbl9yb2xscy52YWx1"
    "ZXMoKSwga2V5PWxhbWJkYSB4OiB4LmdldCgiY291bnQiLCAwKSwgcmV2ZXJzZT1UcnVlKQogICAg"
    "ICAgIGZvciBpdGVtIGluIHJhbmtlZDoKICAgICAgICAgICAgaWYgaW50KGl0ZW0uZ2V0KCJjb3Vu"
    "dCIsIDApKSA8IDI6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBleHByID0g"
    "c2VsZi5fcG9vbF9leHByZXNzaW9uKGl0ZW0uZ2V0KCJwb29sIiwge30pKQogICAgICAgICAgICB0"
    "eHQgPSBmIntleHByfSB7aW50KGl0ZW0uZ2V0KCdtb2RpZmllcicsIDApKTorZH0gKHh7aXRlbS5n"
    "ZXQoJ2NvdW50JywgMCl9KSIKICAgICAgICAgICAgbHcgPSBRTGlzdFdpZGdldEl0ZW0odHh0KQog"
    "ICAgICAgICAgICBsdy5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSwgaXRlbSkKICAg"
    "ICAgICAgICAgc2VsZi5jb21tb25fbGlzdC5hZGRJdGVtKGx3KQoKICAgIGRlZiBfdHJhY2tfY29t"
    "bW9uX3NpZ25hdHVyZShzZWxmLCBldmVudDogZGljdCkgLT4gTm9uZToKICAgICAgICBzaWcgPSBz"
    "ZWxmLl9ub3JtYWxpemVfcG9vbF9zaWduYXR1cmUoZXZlbnQuZ2V0KCJwb29sIiwge30pLCBpbnQo"
    "ZXZlbnQuZ2V0KCJtb2RpZmllciIsIDApKSwgc3RyKGV2ZW50LmdldCgicnVsZV9pZCIpIG9yICIi"
    "KSkKICAgICAgICBpZiBzaWcgbm90IGluIHNlbGYuY29tbW9uX3JvbGxzOgogICAgICAgICAgICBz"
    "ZWxmLmNvbW1vbl9yb2xsc1tzaWddID0gewogICAgICAgICAgICAgICAgInNpZ25hdHVyZSI6IHNp"
    "ZywKICAgICAgICAgICAgICAgICJjb3VudCI6IDAsCiAgICAgICAgICAgICAgICAibmFtZSI6IGV2"
    "ZW50LmdldCgibGFiZWwiLCAiIikgb3Igc2lnLAogICAgICAgICAgICAgICAgInBvb2wiOiBkaWN0"
    "KGV2ZW50LmdldCgicG9vbCIsIHt9KSksCiAgICAgICAgICAgICAgICAibW9kaWZpZXIiOiBpbnQo"
    "ZXZlbnQuZ2V0KCJtb2RpZmllciIsIDApKSwKICAgICAgICAgICAgICAgICJydWxlX2lkIjogZXZl"
    "bnQuZ2V0KCJydWxlX2lkIiksCiAgICAgICAgICAgICAgICAibm90ZXMiOiAiIiwKICAgICAgICAg"
    "ICAgICAgICJjYXRlZ29yeSI6ICJjb21tb24iLAogICAgICAgICAgICB9CiAgICAgICAgc2VsZi5j"
    "b21tb25fcm9sbHNbc2lnXVsiY291bnQiXSA9IGludChzZWxmLmNvbW1vbl9yb2xsc1tzaWddLmdl"
    "dCgiY291bnQiLCAwKSkgKyAxCiAgICAgICAgaWYgc2VsZi5jb21tb25fcm9sbHNbc2lnXVsiY291"
    "bnQiXSA+PSAzOgogICAgICAgICAgICBzZWxmLmNvbW1vbl9oaW50LnNldFRleHQoZiJTdWdnZXN0"
    "aW9uOiBwcm9tb3RlIHtzZWxmLl9wb29sX2V4cHJlc3Npb24oZXZlbnQuZ2V0KCdwb29sJywge30p"
    "KX0gdG8gU2F2ZWQuIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBk"
    "ZWYgX3J1bl9zYXZlZF9yb2xsKHNlbGYsIHBheWxvYWQ6IGRpY3QgfCBOb25lKToKICAgICAgICBp"
    "ZiBub3QgcGF5bG9hZDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZXZlbnQgPSBzZWxmLl9y"
    "b2xsX3Bvb2xfZGF0YSgKICAgICAgICAgICAgZGljdChwYXlsb2FkLmdldCgicG9vbCIsIHt9KSks"
    "CiAgICAgICAgICAgIGludChwYXlsb2FkLmdldCgibW9kaWZpZXIiLCAwKSksCiAgICAgICAgICAg"
    "IHN0cihwYXlsb2FkLmdldCgibmFtZSIsICIiKSkuc3RyaXAoKSwKICAgICAgICAgICAgc3RyKHBh"
    "eWxvYWQuZ2V0KCJydWxlX2lkIikgb3IgIiIpLAogICAgICAgICkKICAgICAgICBzZWxmLl9yZWNv"
    "cmRfcm9sbF9ldmVudChldmVudCkKCiAgICBkZWYgX2xvYWRfcGF5bG9hZF9pbnRvX3Bvb2woc2Vs"
    "ZiwgcGF5bG9hZDogZGljdCB8IE5vbmUpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHBheWxvYWQ6"
    "CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuY3VycmVudF9wb29sID0gZGljdChwYXls"
    "b2FkLmdldCgicG9vbCIsIHt9KSkKICAgICAgICBzZWxmLm1vZF9zcGluLnNldFZhbHVlKGludChw"
    "YXlsb2FkLmdldCgibW9kaWZpZXIiLCAwKSkpCiAgICAgICAgc2VsZi5sYWJlbF9lZGl0LnNldFRl"
    "eHQoc3RyKHBheWxvYWQuZ2V0KCJuYW1lIiwgIiIpKSkKICAgICAgICByaWQgPSBwYXlsb2FkLmdl"
    "dCgicnVsZV9pZCIpCiAgICAgICAgaWR4ID0gc2VsZi5ydWxlX2NvbWJvLmZpbmREYXRhKHJpZCBv"
    "ciAiIikKICAgICAgICBpZiBpZHggPj0gMDoKICAgICAgICAgICAgc2VsZi5ydWxlX2NvbWJvLnNl"
    "dEN1cnJlbnRJbmRleChpZHgpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9wb29sX2VkaXRvcigpCiAg"
    "ICAgICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwuc2V0VGV4dChmIkN1cnJlbnQgUG9vbDoge3Nl"
    "bGYuX3Bvb2xfZXhwcmVzc2lvbigpfSIpCgogICAgZGVmIF9ydW5fc2VsZWN0ZWRfc2F2ZWQoc2Vs"
    "Zik6CiAgICAgICAgaXRlbSA9IHNlbGYuc2F2ZWRfbGlzdC5jdXJyZW50SXRlbSgpCiAgICAgICAg"
    "c2VsZi5fcnVuX3NhdmVkX3JvbGwoaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkg"
    "aWYgaXRlbSBlbHNlIE5vbmUpCgogICAgZGVmIF9sb2FkX3NlbGVjdGVkX3NhdmVkKHNlbGYpOgog"
    "ICAgICAgIGl0ZW0gPSBzZWxmLnNhdmVkX2xpc3QuY3VycmVudEl0ZW0oKQogICAgICAgIHBheWxv"
    "YWQgPSBpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKSBpZiBpdGVtIGVsc2UgTm9u"
    "ZQogICAgICAgIGlmIG5vdCBwYXlsb2FkOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxm"
    "Ll9sb2FkX3BheWxvYWRfaW50b19wb29sKHBheWxvYWQpCgogICAgICAgIG5hbWUsIG9rID0gUUlu"
    "cHV0RGlhbG9nLmdldFRleHQoc2VsZiwgIkVkaXQgU2F2ZWQgUm9sbCIsICJOYW1lOiIsIHRleHQ9"
    "c3RyKHBheWxvYWQuZ2V0KCJuYW1lIiwgIiIpKSkKICAgICAgICBpZiBub3Qgb2s6CiAgICAgICAg"
    "ICAgIHJldHVybgogICAgICAgIHBheWxvYWRbIm5hbWUiXSA9IG5hbWUuc3RyaXAoKSBvciBwYXls"
    "b2FkLmdldCgibmFtZSIsICIiKQogICAgICAgIHBheWxvYWRbInBvb2wiXSA9IGRpY3Qoc2VsZi5j"
    "dXJyZW50X3Bvb2wpCiAgICAgICAgcGF5bG9hZFsibW9kaWZpZXIiXSA9IGludChzZWxmLm1vZF9z"
    "cGluLnZhbHVlKCkpCiAgICAgICAgcGF5bG9hZFsicnVsZV9pZCJdID0gc2VsZi5ydWxlX2NvbWJv"
    "LmN1cnJlbnREYXRhKCkgb3IgTm9uZQogICAgICAgIG5vdGVzLCBva19ub3RlcyA9IFFJbnB1dERp"
    "YWxvZy5nZXRUZXh0KHNlbGYsICJFZGl0IFNhdmVkIFJvbGwiLCAiTm90ZXMgLyBjYXRlZ29yeToi"
    "LCB0ZXh0PXN0cihwYXlsb2FkLmdldCgibm90ZXMiLCAiIikpKQogICAgICAgIGlmIG9rX25vdGVz"
    "OgogICAgICAgICAgICBwYXlsb2FkWyJub3RlcyJdID0gbm90ZXMKICAgICAgICBzZWxmLl9yZWZy"
    "ZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBkZWYgX2RlbGV0ZV9zZWxlY3RlZF9zYXZlZChzZWxmKToK"
    "ICAgICAgICByb3cgPSBzZWxmLnNhdmVkX2xpc3QuY3VycmVudFJvdygpCiAgICAgICAgaWYgcm93"
    "IDwgMCBvciByb3cgPj0gbGVuKHNlbGYuc2F2ZWRfcm9sbHMpOgogICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICBzZWxmLnNhdmVkX3JvbGxzLnBvcChyb3cpCiAgICAgICAgc2VsZi5fcmVmcmVzaF9z"
    "YXZlZF9saXN0cygpCgogICAgZGVmIF9wcm9tb3RlX3NlbGVjdGVkX2NvbW1vbihzZWxmKToKICAg"
    "ICAgICBpdGVtID0gc2VsZi5jb21tb25fbGlzdC5jdXJyZW50SXRlbSgpCiAgICAgICAgcGF5bG9h"
    "ZCA9IGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpIGlmIGl0ZW0gZWxzZSBOb25l"
    "CiAgICAgICAgaWYgbm90IHBheWxvYWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHByb21v"
    "dGVkID0gewogICAgICAgICAgICAiaWQiOiBmInNhdmVkX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19"
    "IiwKICAgICAgICAgICAgIm5hbWUiOiBwYXlsb2FkLmdldCgibmFtZSIpIG9yIHNlbGYuX3Bvb2xf"
    "ZXhwcmVzc2lvbihwYXlsb2FkLmdldCgicG9vbCIsIHt9KSksCiAgICAgICAgICAgICJwb29sIjog"
    "ZGljdChwYXlsb2FkLmdldCgicG9vbCIsIHt9KSksCiAgICAgICAgICAgICJtb2RpZmllciI6IGlu"
    "dChwYXlsb2FkLmdldCgibW9kaWZpZXIiLCAwKSksCiAgICAgICAgICAgICJydWxlX2lkIjogcGF5"
    "bG9hZC5nZXQoInJ1bGVfaWQiKSwKICAgICAgICAgICAgIm5vdGVzIjogcGF5bG9hZC5nZXQoIm5v"
    "dGVzIiwgIiIpLAogICAgICAgICAgICAiY2F0ZWdvcnkiOiAic2F2ZWQiLAogICAgICAgIH0KICAg"
    "ICAgICBzZWxmLnNhdmVkX3JvbGxzLmFwcGVuZChwcm9tb3RlZCkKICAgICAgICBzZWxmLl9yZWZy"
    "ZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBkZWYgX2Rpc21pc3Nfc2VsZWN0ZWRfY29tbW9uKHNlbGYp"
    "OgogICAgICAgIGl0ZW0gPSBzZWxmLmNvbW1vbl9saXN0LmN1cnJlbnRJdGVtKCkKICAgICAgICBw"
    "YXlsb2FkID0gaXRlbS5kYXRhKFF0Lkl0ZW1EYXRhUm9sZS5Vc2VyUm9sZSkgaWYgaXRlbSBlbHNl"
    "IE5vbmUKICAgICAgICBpZiBub3QgcGF5bG9hZDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAg"
    "c2lnID0gcGF5bG9hZC5nZXQoInNpZ25hdHVyZSIpCiAgICAgICAgaWYgc2lnIGluIHNlbGYuY29t"
    "bW9uX3JvbGxzOgogICAgICAgICAgICBzZWxmLmNvbW1vbl9yb2xscy5wb3Aoc2lnLCBOb25lKQog"
    "ICAgICAgIHNlbGYuX3JlZnJlc2hfc2F2ZWRfbGlzdHMoKQoKICAgIGRlZiBfcmVzZXRfcG9vbChz"
    "ZWxmKToKICAgICAgICBzZWxmLmN1cnJlbnRfcG9vbCA9IHt9CiAgICAgICAgc2VsZi5tb2Rfc3Bp"
    "bi5zZXRWYWx1ZSgwKQogICAgICAgIHNlbGYubGFiZWxfZWRpdC5jbGVhcigpCiAgICAgICAgc2Vs"
    "Zi5ydWxlX2NvbWJvLnNldEN1cnJlbnRJbmRleCgwKQogICAgICAgIHNlbGYuX3JlZnJlc2hfcG9v"
    "bF9lZGl0b3IoKQogICAgICAgIHNlbGYuY3VycmVudF9yZXN1bHRfbGJsLnNldFRleHQoIk5vIHJv"
    "bGwgeWV0LiIpCgogICAgZGVmIF9jbGVhcl9oaXN0b3J5KHNlbGYpOgogICAgICAgIHNlbGYucm9s"
    "bF9ldmVudHMuY2xlYXIoKQogICAgICAgIHNlbGYuZXZlbnRfYnlfaWQuY2xlYXIoKQogICAgICAg"
    "IHNlbGYuY3VycmVudF9yb2xsX2lkcyA9IFtdCiAgICAgICAgc2VsZi5oaXN0b3J5X3RhYmxlLnNl"
    "dFJvd0NvdW50KDApCiAgICAgICAgc2VsZi5jdXJyZW50X3RhYmxlLnNldFJvd0NvdW50KDApCiAg"
    "ICAgICAgc2VsZi5fdXBkYXRlX2dyYW5kX3RvdGFsKCkKICAgICAgICBzZWxmLmN1cnJlbnRfcmVz"
    "dWx0X2xibC5zZXRUZXh0KCJObyByb2xsIHlldC4iKQoKICAgIGRlZiBfZXZlbnRfZnJvbV90YWJs"
    "ZV9wb3NpdGlvbihzZWxmLCB0YWJsZTogUVRhYmxlV2lkZ2V0LCBwb3MpIC0+IGRpY3QgfCBOb25l"
    "OgogICAgICAgIGl0ZW0gPSB0YWJsZS5pdGVtQXQocG9zKQogICAgICAgIGlmIG5vdCBpdGVtOgog"
    "ICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIHJvdyA9IGl0ZW0ucm93KCkKICAgICAgICB0"
    "c19pdGVtID0gdGFibGUuaXRlbShyb3csIDApCiAgICAgICAgaWYgbm90IHRzX2l0ZW06CiAgICAg"
    "ICAgICAgIHJldHVybiBOb25lCiAgICAgICAgZWlkID0gdHNfaXRlbS5kYXRhKFF0Lkl0ZW1EYXRh"
    "Um9sZS5Vc2VyUm9sZSkKICAgICAgICByZXR1cm4gc2VsZi5ldmVudF9ieV9pZC5nZXQoZWlkKQoK"
    "ICAgIGRlZiBfc2hvd19yb2xsX2NvbnRleHRfbWVudShzZWxmLCB0YWJsZTogUVRhYmxlV2lkZ2V0"
    "LCBwb3MpIC0+IE5vbmU6CiAgICAgICAgZXZ0ID0gc2VsZi5fZXZlbnRfZnJvbV90YWJsZV9wb3Np"
    "dGlvbih0YWJsZSwgcG9zKQogICAgICAgIGlmIG5vdCBldnQ6CiAgICAgICAgICAgIHJldHVybgog"
    "ICAgICAgIGZyb20gUHlTaWRlNi5RdFdpZGdldHMgaW1wb3J0IFFNZW51CiAgICAgICAgbWVudSA9"
    "IFFNZW51KHNlbGYpCiAgICAgICAgYWN0X3NlbmQgPSBtZW51LmFkZEFjdGlvbigiU2VuZCB0byBQ"
    "cm9tcHQiKQogICAgICAgIGNob3NlbiA9IG1lbnUuZXhlYyh0YWJsZS52aWV3cG9ydCgpLm1hcFRv"
    "R2xvYmFsKHBvcykpCiAgICAgICAgaWYgY2hvc2VuID09IGFjdF9zZW5kOgogICAgICAgICAgICBz"
    "ZWxmLl9zZW5kX2V2ZW50X3RvX3Byb21wdChldnQpCgogICAgZGVmIF9mb3JtYXRfZXZlbnRfZm9y"
    "X3Byb21wdChzZWxmLCBldmVudDogZGljdCkgLT4gc3RyOgogICAgICAgIGxhYmVsID0gKGV2ZW50"
    "LmdldCgibGFiZWwiKSBvciAiUm9sbCIpLnN0cmlwKCkKICAgICAgICBncm91cGVkID0gZXZlbnQu"
    "Z2V0KCJncm91cGVkX3Jhd19kaXNwbGF5Iiwge30pIG9yIHt9CiAgICAgICAgc2VnbWVudHMgPSBb"
    "XQogICAgICAgIGZvciBkaWUgaW4gc2VsZi5UUkFZX09SREVSOgogICAgICAgICAgICB2YWxzID0g"
    "Z3JvdXBlZC5nZXQoZGllKQogICAgICAgICAgICBpZiB2YWxzOgogICAgICAgICAgICAgICAgc2Vn"
    "bWVudHMuYXBwZW5kKGYie2RpZX0gcm9sbGVkIHsnLCcuam9pbihzdHIodikgZm9yIHYgaW4gdmFs"
    "cyl9IikKICAgICAgICBtb2QgPSBpbnQoZXZlbnQuZ2V0KCJtb2RpZmllciIsIDApKQogICAgICAg"
    "IHRvdGFsID0gaW50KGV2ZW50LmdldCgiZmluYWxfdG90YWwiLCAwKSkKICAgICAgICByZXR1cm4g"
    "ZiJ7bGFiZWx9OiB7JzsgJy5qb2luKHNlZ21lbnRzKX07IG1vZGlmaWVyIHttb2Q6K2R9OyB0b3Rh"
    "bCB7dG90YWx9IgoKICAgIGRlZiBfc2VuZF9ldmVudF90b19wcm9tcHQoc2VsZiwgZXZlbnQ6IGRp"
    "Y3QpIC0+IE5vbmU6CiAgICAgICAgd2luZG93ID0gc2VsZi53aW5kb3coKQogICAgICAgIGlmIG5v"
    "dCB3aW5kb3cgb3Igbm90IGhhc2F0dHIod2luZG93LCAiX2lucHV0X2ZpZWxkIik6CiAgICAgICAg"
    "ICAgIHJldHVybgogICAgICAgIGxpbmUgPSBzZWxmLl9mb3JtYXRfZXZlbnRfZm9yX3Byb21wdChl"
    "dmVudCkKICAgICAgICB3aW5kb3cuX2lucHV0X2ZpZWxkLnNldFRleHQobGluZSkKICAgICAgICB3"
    "aW5kb3cuX2lucHV0X2ZpZWxkLnNldEZvY3VzKCkKCiAgICBkZWYgX3BsYXlfcm9sbF9zb3VuZChz"
    "ZWxmKToKICAgICAgICBpZiBub3QgV0lOU09VTkRfT0s6CiAgICAgICAgICAgIHJldHVybgogICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgd2luc291bmQuQmVlcCg4NDAsIDMwKQogICAgICAgICAgICB3"
    "aW5zb3VuZC5CZWVwKDYyMCwgMzUpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAg"
    "ICAgcGFzcwoKCgpjbGFzcyBNYWdpYzhCYWxsVGFiKFFXaWRnZXQpOgogICAgIiIiTWFnaWMgOC1C"
    "YWxsIG1vZHVsZSB3aXRoIGNpcmN1bGFyIG9yYiBkaXNwbGF5IGFuZCBwdWxzaW5nIGFuc3dlciB0"
    "ZXh0LiIiIgoKICAgIEFOU1dFUlMgPSBbCiAgICAgICAgIkl0IGlzIGNlcnRhaW4uIiwKICAgICAg"
    "ICAiSXQgaXMgZGVjaWRlZGx5IHNvLiIsCiAgICAgICAgIldpdGhvdXQgYSBkb3VidC4iLAogICAg"
    "ICAgICJZZXMgZGVmaW5pdGVseS4iLAogICAgICAgICJZb3UgbWF5IHJlbHkgb24gaXQuIiwKICAg"
    "ICAgICAiQXMgSSBzZWUgaXQsIHllcy4iLAogICAgICAgICJNb3N0IGxpa2VseS4iLAogICAgICAg"
    "ICJPdXRsb29rIGdvb2QuIiwKICAgICAgICAiWWVzLiIsCiAgICAgICAgIlNpZ25zIHBvaW50IHRv"
    "IHllcy4iLAogICAgICAgICJSZXBseSBoYXp5LCB0cnkgYWdhaW4uIiwKICAgICAgICAiQXNrIGFn"
    "YWluIGxhdGVyLiIsCiAgICAgICAgIkJldHRlciBub3QgdGVsbCB5b3Ugbm93LiIsCiAgICAgICAg"
    "IkNhbm5vdCBwcmVkaWN0IG5vdy4iLAogICAgICAgICJDb25jZW50cmF0ZSBhbmQgYXNrIGFnYWlu"
    "LiIsCiAgICAgICAgIkRvbid0IGNvdW50IG9uIGl0LiIsCiAgICAgICAgIk15IHJlcGx5IGlzIG5v"
    "LiIsCiAgICAgICAgIk15IHNvdXJjZXMgc2F5IG5vLiIsCiAgICAgICAgIk91dGxvb2sgbm90IHNv"
    "IGdvb2QuIiwKICAgICAgICAiVmVyeSBkb3VidGZ1bC4iLAogICAgXQoKICAgIGRlZiBfX2luaXRf"
    "XyhzZWxmLCBvbl90aHJvdz1Ob25lLCBkaWFnbm9zdGljc19sb2dnZXI9Tm9uZSk6CiAgICAgICAg"
    "c3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fb25fdGhyb3cgPSBvbl90aHJvdwogICAg"
    "ICAgIHNlbGYuX2xvZyA9IGRpYWdub3N0aWNzX2xvZ2dlciBvciAobGFtYmRhICpfYXJncywgKipf"
    "a3dhcmdzOiBOb25lKQogICAgICAgIHNlbGYuX2N1cnJlbnRfYW5zd2VyID0gIiIKCiAgICAgICAg"
    "c2VsZi5fY2xlYXJfdGltZXIgPSBRVGltZXIoc2VsZikKICAgICAgICBzZWxmLl9jbGVhcl90aW1l"
    "ci5zZXRTaW5nbGVTaG90KFRydWUpCiAgICAgICAgc2VsZi5fY2xlYXJfdGltZXIudGltZW91dC5j"
    "b25uZWN0KHNlbGYuX2ZhZGVfb3V0X2Fuc3dlcikKCiAgICAgICAgc2VsZi5fYnVpbGRfdWkoKQog"
    "ICAgICAgIHNlbGYuX2J1aWxkX2FuaW1hdGlvbnMoKQogICAgICAgIHNlbGYuX3NldF9pZGxlX3Zp"
    "c3VhbCgpCgogICAgZGVmIF9idWlsZF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBR"
    "VkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDE2LCAxNiwg"
    "MTYsIDE2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZygxNCkKICAgICAgICByb290LmFkZFN0cmV0"
    "Y2goMSkKCiAgICAgICAgc2VsZi5fb3JiX2ZyYW1lID0gUUZyYW1lKCkKICAgICAgICBzZWxmLl9v"
    "cmJfZnJhbWUuc2V0Rml4ZWRTaXplKDIyOCwgMjI4KQogICAgICAgIHNlbGYuX29yYl9mcmFtZS5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAiUUZyYW1lIHsiCiAgICAgICAgICAgICJiYWNrZ3Jv"
    "dW5kLWNvbG9yOiAjMDQwNDA2OyIKICAgICAgICAgICAgImJvcmRlcjogMXB4IHNvbGlkIHJnYmEo"
    "MjM0LCAyMzcsIDI1NSwgMC42Mik7IgogICAgICAgICAgICAiYm9yZGVyLXJhZGl1czogMTE0cHg7"
    "IgogICAgICAgICAgICAifSIKICAgICAgICApCgogICAgICAgIG9yYl9sYXlvdXQgPSBRVkJveExh"
    "eW91dChzZWxmLl9vcmJfZnJhbWUpCiAgICAgICAgb3JiX2xheW91dC5zZXRDb250ZW50c01hcmdp"
    "bnMoMjAsIDIwLCAyMCwgMjApCiAgICAgICAgb3JiX2xheW91dC5zZXRTcGFjaW5nKDApCgogICAg"
    "ICAgIHNlbGYuX29yYl9pbm5lciA9IFFGcmFtZSgpCiAgICAgICAgc2VsZi5fb3JiX2lubmVyLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgICJRRnJhbWUgeyIKICAgICAgICAgICAgImJhY2tncm91"
    "bmQtY29sb3I6ICMwNzA3MGE7IgogICAgICAgICAgICAiYm9yZGVyOiAxcHggc29saWQgcmdiYSgy"
    "NTUsIDI1NSwgMjU1LCAwLjEyKTsiCiAgICAgICAgICAgICJib3JkZXItcmFkaXVzOiA4NHB4OyIK"
    "ICAgICAgICAgICAgIn0iCiAgICAgICAgKQogICAgICAgIHNlbGYuX29yYl9pbm5lci5zZXRNaW5p"
    "bXVtU2l6ZSgxNjgsIDE2OCkKICAgICAgICBzZWxmLl9vcmJfaW5uZXIuc2V0TWF4aW11bVNpemUo"
    "MTY4LCAxNjgpCgogICAgICAgIGlubmVyX2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX29yYl9p"
    "bm5lcikKICAgICAgICBpbm5lcl9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDE2LCAxNiwgMTYs"
    "IDE2KQogICAgICAgIGlubmVyX2xheW91dC5zZXRTcGFjaW5nKDApCgogICAgICAgIHNlbGYuX2Vp"
    "Z2h0X2xibCA9IFFMYWJlbCgiOCIpCiAgICAgICAgc2VsZi5fZWlnaHRfbGJsLnNldEFsaWdubWVu"
    "dChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIHNlbGYuX2VpZ2h0X2xibC5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAiY29sb3I6IHJnYmEoMjU1LCAyNTUsIDI1NSwgMC45"
    "NSk7ICIKICAgICAgICAgICAgImZvbnQtc2l6ZTogODBweDsgZm9udC13ZWlnaHQ6IDcwMDsgIgog"
    "ICAgICAgICAgICAiZm9udC1mYW1pbHk6IEdlb3JnaWEsIHNlcmlmOyBib3JkZXI6IG5vbmU7Igog"
    "ICAgICAgICkKCiAgICAgICAgc2VsZi5hbnN3ZXJfbGJsID0gUUxhYmVsKCIiKQogICAgICAgIHNl"
    "bGYuYW5zd2VyX2xibC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikK"
    "ICAgICAgICBzZWxmLmFuc3dlcl9sYmwuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBzZWxmLmFu"
    "c3dlcl9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZv"
    "bnQtc2l6ZTogMTZweDsgZm9udC1zdHlsZTogaXRhbGljOyAiCiAgICAgICAgICAgICJmb250LXdl"
    "aWdodDogNjAwOyBib3JkZXI6IG5vbmU7IHBhZGRpbmc6IDJweDsiCiAgICAgICAgKQoKICAgICAg"
    "ICBpbm5lcl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2VpZ2h0X2xibCwgMSkKICAgICAgICBpbm5l"
    "cl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuYW5zd2VyX2xibCwgMSkKICAgICAgICBvcmJfbGF5b3V0"
    "LmFkZFdpZGdldChzZWxmLl9vcmJfaW5uZXIsIDAsIFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50"
    "ZXIpCgogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX29yYl9mcmFtZSwgMCwgUXQuQWxpZ25t"
    "ZW50RmxhZy5BbGlnbkhDZW50ZXIpCgogICAgICAgIHNlbGYudGhyb3dfYnRuID0gUVB1c2hCdXR0"
    "b24oIlRocm93IHRoZSA4LUJhbGwiKQogICAgICAgIHNlbGYudGhyb3dfYnRuLnNldEZpeGVkSGVp"
    "Z2h0KDM4KQogICAgICAgIHNlbGYudGhyb3dfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl90aHJv"
    "d19iYWxsKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYudGhyb3dfYnRuLCAwLCBRdC5BbGln"
    "bm1lbnRGbGFnLkFsaWduSENlbnRlcikKICAgICAgICByb290LmFkZFN0cmV0Y2goMSkKCiAgICBk"
    "ZWYgX2J1aWxkX2FuaW1hdGlvbnMoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hbnN3ZXJf"
    "b3BhY2l0eSA9IFFHcmFwaGljc09wYWNpdHlFZmZlY3Qoc2VsZi5hbnN3ZXJfbGJsKQogICAgICAg"
    "IHNlbGYuYW5zd2VyX2xibC5zZXRHcmFwaGljc0VmZmVjdChzZWxmLl9hbnN3ZXJfb3BhY2l0eSkK"
    "ICAgICAgICBzZWxmLl9hbnN3ZXJfb3BhY2l0eS5zZXRPcGFjaXR5KDAuMCkKCiAgICAgICAgc2Vs"
    "Zi5fcHVsc2VfYW5pbSA9IFFQcm9wZXJ0eUFuaW1hdGlvbihzZWxmLl9hbnN3ZXJfb3BhY2l0eSwg"
    "YiJvcGFjaXR5Iiwgc2VsZikKICAgICAgICBzZWxmLl9wdWxzZV9hbmltLnNldER1cmF0aW9uKDc2"
    "MCkKICAgICAgICBzZWxmLl9wdWxzZV9hbmltLnNldFN0YXJ0VmFsdWUoMC4zNSkKICAgICAgICBz"
    "ZWxmLl9wdWxzZV9hbmltLnNldEVuZFZhbHVlKDEuMCkKICAgICAgICBzZWxmLl9wdWxzZV9hbmlt"
    "LnNldEVhc2luZ0N1cnZlKFFFYXNpbmdDdXJ2ZS5UeXBlLkluT3V0U2luZSkKICAgICAgICBzZWxm"
    "Ll9wdWxzZV9hbmltLnNldExvb3BDb3VudCgtMSkKCiAgICAgICAgc2VsZi5fZmFkZV9vdXQgPSBR"
    "UHJvcGVydHlBbmltYXRpb24oc2VsZi5fYW5zd2VyX29wYWNpdHksIGIib3BhY2l0eSIsIHNlbGYp"
    "CiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc2V0RHVyYXRpb24oNTYwKQogICAgICAgIHNlbGYuX2Zh"
    "ZGVfb3V0LnNldFN0YXJ0VmFsdWUoMS4wKQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LnNldEVuZFZh"
    "bHVlKDAuMCkKICAgICAgICBzZWxmLl9mYWRlX291dC5zZXRFYXNpbmdDdXJ2ZShRRWFzaW5nQ3Vy"
    "dmUuVHlwZS5Jbk91dFF1YWQpCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuZmluaXNoZWQuY29ubmVj"
    "dChzZWxmLl9jbGVhcl90b19pZGxlKQoKICAgIGRlZiBfc2V0X2lkbGVfdmlzdWFsKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5fY3VycmVudF9hbnN3ZXIgPSAiIgogICAgICAgIHNlbGYuX2Vp"
    "Z2h0X2xibC5zaG93KCkKICAgICAgICBzZWxmLmFuc3dlcl9sYmwuY2xlYXIoKQogICAgICAgIHNl"
    "bGYuYW5zd2VyX2xibC5oaWRlKCkKICAgICAgICBzZWxmLl9hbnN3ZXJfb3BhY2l0eS5zZXRPcGFj"
    "aXR5KDAuMCkKCiAgICBkZWYgX3Rocm93X2JhbGwoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9jbGVhcl90aW1lci5zdG9wKCkKICAgICAgICBzZWxmLl9wdWxzZV9hbmltLnN0b3AoKQogICAg"
    "ICAgIHNlbGYuX2ZhZGVfb3V0LnN0b3AoKQoKICAgICAgICBhbnN3ZXIgPSByYW5kb20uY2hvaWNl"
    "KHNlbGYuQU5TV0VSUykKICAgICAgICBzZWxmLl9jdXJyZW50X2Fuc3dlciA9IGFuc3dlcgoKICAg"
    "ICAgICBzZWxmLl9laWdodF9sYmwuaGlkZSgpCiAgICAgICAgc2VsZi5hbnN3ZXJfbGJsLnNldFRl"
    "eHQoYW5zd2VyKQogICAgICAgIHNlbGYuYW5zd2VyX2xibC5zaG93KCkKICAgICAgICBzZWxmLl9h"
    "bnN3ZXJfb3BhY2l0eS5zZXRPcGFjaXR5KDAuMCkKICAgICAgICBzZWxmLl9wdWxzZV9hbmltLnN0"
    "YXJ0KCkKICAgICAgICBzZWxmLl9jbGVhcl90aW1lci5zdGFydCg2MDAwMCkKICAgICAgICBzZWxm"
    "Ll9sb2coZiJbOEJBTExdIFRocm93IHJlc3VsdDoge2Fuc3dlcn0iLCAiSU5GTyIpCgogICAgICAg"
    "IGlmIGNhbGxhYmxlKHNlbGYuX29uX3Rocm93KToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAg"
    "ICAgICAgc2VsZi5fb25fdGhyb3coYW5zd2VyKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "IGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fbG9nKGYiWzhCQUxMXVtXQVJOXSBJbnRlcm5h"
    "bCBwcm9tcHQgZGlzcGF0Y2ggZmFpbGVkOiB7ZXh9IiwgIldBUk4iKQoKICAgIGRlZiBfZmFkZV9v"
    "dXRfYW5zd2VyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fY2xlYXJfdGltZXIuc3RvcCgp"
    "CiAgICAgICAgc2VsZi5fcHVsc2VfYW5pbS5zdG9wKCkKICAgICAgICBzZWxmLl9mYWRlX291dC5z"
    "dG9wKCkKICAgICAgICBzZWxmLl9mYWRlX291dC5zZXRTdGFydFZhbHVlKGZsb2F0KHNlbGYuX2Fu"
    "c3dlcl9vcGFjaXR5Lm9wYWNpdHkoKSkpCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc2V0RW5kVmFs"
    "dWUoMC4wKQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LnN0YXJ0KCkKCiAgICBkZWYgX2NsZWFyX3Rv"
    "X2lkbGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9mYWRlX291dC5zdG9wKCkKICAgICAg"
    "ICBzZWxmLl9zZXRfaWRsZV92aXN1YWwoKQoKIyDilIDilIAgTUFJTiBXSU5ET1cg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACmNsYXNzIExvY2tBd2FyZVRhYkJhcihRVGFiQmFyKToKICAgICIiIlRhYiBiYXIg"
    "dGhhdCBibG9ja3MgZHJhZyBpbml0aWF0aW9uIGZvciBsb2NrZWQgdGFicy4iIiIKCiAgICBkZWYg"
    "X19pbml0X18oc2VsZiwgaXNfbG9ja2VkX2J5X2lkLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3Vw"
    "ZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5faXNfbG9ja2VkX2J5X2lkID0gaXNf"
    "bG9ja2VkX2J5X2lkCiAgICAgICAgc2VsZi5fcHJlc3NlZF9pbmRleCA9IC0xCgogICAgZGVmIF90"
    "YWJfaWQoc2VsZiwgaW5kZXg6IGludCk6CiAgICAgICAgaWYgaW5kZXggPCAwOgogICAgICAgICAg"
    "ICByZXR1cm4gTm9uZQogICAgICAgIHJldHVybiBzZWxmLnRhYkRhdGEoaW5kZXgpCgogICAgZGVm"
    "IG1vdXNlUHJlc3NFdmVudChzZWxmLCBldmVudCk6CiAgICAgICAgc2VsZi5fcHJlc3NlZF9pbmRl"
    "eCA9IHNlbGYudGFiQXQoZXZlbnQucG9zKCkpCiAgICAgICAgaWYgKGV2ZW50LmJ1dHRvbigpID09"
    "IFF0Lk1vdXNlQnV0dG9uLkxlZnRCdXR0b24gYW5kIHNlbGYuX3ByZXNzZWRfaW5kZXggPj0gMCk6"
    "CiAgICAgICAgICAgIHRhYl9pZCA9IHNlbGYuX3RhYl9pZChzZWxmLl9wcmVzc2VkX2luZGV4KQog"
    "ICAgICAgICAgICBpZiB0YWJfaWQgYW5kIHNlbGYuX2lzX2xvY2tlZF9ieV9pZCh0YWJfaWQpOgog"
    "ICAgICAgICAgICAgICAgc2VsZi5zZXRDdXJyZW50SW5kZXgoc2VsZi5fcHJlc3NlZF9pbmRleCkK"
    "ICAgICAgICAgICAgICAgIGV2ZW50LmFjY2VwdCgpCiAgICAgICAgICAgICAgICByZXR1cm4KICAg"
    "ICAgICBzdXBlcigpLm1vdXNlUHJlc3NFdmVudChldmVudCkKCiAgICBkZWYgbW91c2VNb3ZlRXZl"
    "bnQoc2VsZiwgZXZlbnQpOgogICAgICAgIGlmIHNlbGYuX3ByZXNzZWRfaW5kZXggPj0gMDoKICAg"
    "ICAgICAgICAgdGFiX2lkID0gc2VsZi5fdGFiX2lkKHNlbGYuX3ByZXNzZWRfaW5kZXgpCiAgICAg"
    "ICAgICAgIGlmIHRhYl9pZCBhbmQgc2VsZi5faXNfbG9ja2VkX2J5X2lkKHRhYl9pZCk6CiAgICAg"
    "ICAgICAgICAgICBldmVudC5hY2NlcHQoKQogICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAg"
    "c3VwZXIoKS5tb3VzZU1vdmVFdmVudChldmVudCkKCiAgICBkZWYgbW91c2VSZWxlYXNlRXZlbnQo"
    "c2VsZiwgZXZlbnQpOgogICAgICAgIHNlbGYuX3ByZXNzZWRfaW5kZXggPSAtMQogICAgICAgIHN1"
    "cGVyKCkubW91c2VSZWxlYXNlRXZlbnQoZXZlbnQpCgoKY2xhc3MgRWNob0RlY2soUU1haW5XaW5k"
    "b3cpOgogICAgIiIiCiAgICBUaGUgbWFpbiBFY2hvIERlY2sgd2luZG93LgogICAgQXNzZW1ibGVz"
    "IGFsbCB3aWRnZXRzLCBjb25uZWN0cyBhbGwgc2lnbmFscywgbWFuYWdlcyBhbGwgc3RhdGUuCiAg"
    "ICAiIiIKCiAgICAjIOKUgOKUgCBUb3Jwb3IgdGhyZXNob2xkcyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgIF9FWFRFUk5BTF9WUkFNX1RPUlBPUl9HQiAgICA9IDEuNSAgICMgZXh0ZXJuYWwg"
    "VlJBTSA+IHRoaXMg4oaSIGNvbnNpZGVyIHRvcnBvcgogICAgX0VYVEVSTkFMX1ZSQU1fV0FLRV9H"
    "QiAgICAgID0gMC44ICAgIyBleHRlcm5hbCBWUkFNIDwgdGhpcyDihpIgY29uc2lkZXIgd2FrZQog"
    "ICAgX1RPUlBPUl9TVVNUQUlORURfVElDS1MgICAgID0gNiAgICAgIyA2IMOXIDVzID0gMzAgc2Vj"
    "b25kcyBzdXN0YWluZWQKICAgIF9XQUtFX1NVU1RBSU5FRF9USUNLUyAgICAgICA9IDEyICAgICMg"
    "NjAgc2Vjb25kcyBzdXN0YWluZWQgbG93IHByZXNzdXJlCgogICAgZGVmIF9faW5pdF9fKHNlbGYp"
    "OgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQoKICAgICAgICAjIOKUgOKUgCBDb3JlIHN0YXRl"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3N0YXR1cyAg"
    "ICAgICAgICAgICAgPSAiT0ZGTElORSIKICAgICAgICBzZWxmLl9zZXNzaW9uX3N0YXJ0ICAgICAg"
    "ID0gdGltZS50aW1lKCkKICAgICAgICBzZWxmLl90b2tlbl9jb3VudCAgICAgICAgID0gMAogICAg"
    "ICAgIHNlbGYuX2ZhY2VfbG9ja2VkICAgICAgICAgPSBGYWxzZQogICAgICAgIHNlbGYuX2JsaW5r"
    "X3N0YXRlICAgICAgICAgPSBUcnVlCiAgICAgICAgc2VsZi5fbW9kZWxfbG9hZGVkICAgICAgICA9"
    "IEZhbHNlCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9pZCAgICAgICAgICA9IGYic2Vzc2lvbl97ZGF0"
    "ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVZJW0lZF8lSCVNJVMnKX0iCiAgICAgICAgc2VsZi5fYWN0"
    "aXZlX3RocmVhZHM6IGxpc3QgPSBbXSAgIyBrZWVwIHJlZnMgdG8gcHJldmVudCBHQyB3aGlsZSBy"
    "dW5uaW5nCiAgICAgICAgc2VsZi5fZmlyc3RfdG9rZW46IGJvb2wgPSBUcnVlICAgIyB3cml0ZSBz"
    "cGVha2VyIGxhYmVsIGJlZm9yZSBmaXJzdCBzdHJlYW1pbmcgdG9rZW4KCiAgICAgICAgIyBUb3Jw"
    "b3IgLyBWUkFNIHRyYWNraW5nCiAgICAgICAgc2VsZi5fdG9ycG9yX3N0YXRlICAgICAgICA9ICJB"
    "V0FLRSIKICAgICAgICBzZWxmLl9kZWNrX3ZyYW1fYmFzZSAgPSAwLjAgICAjIGJhc2VsaW5lIFZS"
    "QU0gYWZ0ZXIgbW9kZWwgbG9hZAogICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgPSAw"
    "ICAgICAjIHN1c3RhaW5lZCBwcmVzc3VyZSBjb3VudGVyCiAgICAgICAgc2VsZi5fdnJhbV9yZWxp"
    "ZWZfdGlja3MgICA9IDAgICAgICMgc3VzdGFpbmVkIHJlbGllZiBjb3VudGVyCiAgICAgICAgc2Vs"
    "Zi5fcGVuZGluZ190cmFuc21pc3Npb25zID0gMAogICAgICAgIHNlbGYuX3RvcnBvcl9zaW5jZSAg"
    "ICAgICAgPSBOb25lICAjIGRhdGV0aW1lIHdoZW4gdG9ycG9yIGJlZ2FuCiAgICAgICAgc2VsZi5f"
    "c3VzcGVuZGVkX2R1cmF0aW9uICA9ICIiICAgIyBmb3JtYXR0ZWQgZHVyYXRpb24gc3RyaW5nCgog"
    "ICAgICAgICMg4pSA4pSAIE1hbmFnZXJzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgICAgIHNlbGYuX21lbW9yeSAgID0gTWVtb3J5TWFuYWdlcigpCiAgICAgICAg"
    "c2VsZi5fc2Vzc2lvbnMgPSBTZXNzaW9uTWFuYWdlcigpCiAgICAgICAgc2VsZi5fbGVzc29ucyAg"
    "PSBMZXNzb25zTGVhcm5lZERCKCkKICAgICAgICBzZWxmLl90YXNrcyAgICA9IFRhc2tNYW5hZ2Vy"
    "KCkKICAgICAgICBzZWxmLl9yZWNvcmRzX2NhY2hlOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBz"
    "ZWxmLl9yZWNvcmRzX2luaXRpYWxpemVkID0gRmFsc2UKICAgICAgICBzZWxmLl9yZWNvcmRzX2N1"
    "cnJlbnRfZm9sZGVyX2lkID0gInJvb3QiCiAgICAgICAgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHkg"
    "PSBGYWxzZQogICAgICAgIHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyOiBPcHRpb25hbFtRVGlt"
    "ZXJdID0gTm9uZQogICAgICAgIHNlbGYuX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXI6IE9w"
    "dGlvbmFsW1FUaW1lcl0gPSBOb25lCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWJfaW5kZXggPSAt"
    "MQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYl9pbmRleCA9IC0xCiAgICAgICAgc2VsZi5fdGFza19z"
    "aG93X2NvbXBsZXRlZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9ICJu"
    "ZXh0XzNfbW9udGhzIgoKICAgICAgICAjIFJpZ2h0IHN5c3RlbXMgdGFiLXN0cmlwIHByZXNlbnRh"
    "dGlvbiBzdGF0ZSAoc3RhYmxlIElEcyArIHZpc3VhbCBvcmRlcikKICAgICAgICBzZWxmLl9zcGVs"
    "bF90YWJfZGVmczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fc3BlbGxfdGFiX3N0YXRl"
    "OiBkaWN0W3N0ciwgZGljdF0gPSB7fQogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9tb3ZlX21vZGVf"
    "aWQ6IE9wdGlvbmFsW3N0cl0gPSBOb25lCiAgICAgICAgc2VsZi5fc3VwcHJlc3Nfc3BlbGxfdGFi"
    "X21vdmVfc2lnbmFsID0gRmFsc2UKICAgICAgICBzZWxmLl9mb2N1c19ob29rZWRfZm9yX3NwZWxs"
    "X3RhYnMgPSBGYWxzZQoKICAgICAgICAjIOKUgOKUgCBHb29nbGUgU2VydmljZXMg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICAgICAgIyBJbnN0YW50aWF0ZSBzZXJ2aWNlIHdyYXBwZXJzIHVwLWZyb250"
    "OyBhdXRoIGlzIGZvcmNlZCBsYXRlcgogICAgICAgICMgZnJvbSBtYWluKCkgYWZ0ZXIgd2luZG93"
    "LnNob3coKSB3aGVuIHRoZSBldmVudCBsb29wIGlzIHJ1bm5pbmcuCiAgICAgICAgZ19jcmVkc19w"
    "YXRoID0gUGF0aChDRkcuZ2V0KCJnb29nbGUiLCB7fSkuZ2V0KAogICAgICAgICAgICAiY3JlZGVu"
    "dGlhbHMiLAogICAgICAgICAgICBzdHIoY2ZnX3BhdGgoImdvb2dsZSIpIC8gImdvb2dsZV9jcmVk"
    "ZW50aWFscy5qc29uIikKICAgICAgICApKQogICAgICAgIGdfdG9rZW5fcGF0aCA9IFBhdGgoQ0ZH"
    "LmdldCgiZ29vZ2xlIiwge30pLmdldCgKICAgICAgICAgICAgInRva2VuIiwKICAgICAgICAgICAg"
    "c3RyKGNmZ19wYXRoKCJnb29nbGUiKSAvICJ0b2tlbi5qc29uIikKICAgICAgICApKQogICAgICAg"
    "IHNlbGYuX2djYWwgPSBHb29nbGVDYWxlbmRhclNlcnZpY2UoZ19jcmVkc19wYXRoLCBnX3Rva2Vu"
    "X3BhdGgpCiAgICAgICAgc2VsZi5fZ2RyaXZlID0gR29vZ2xlRG9jc0RyaXZlU2VydmljZSgKICAg"
    "ICAgICAgICAgZ19jcmVkc19wYXRoLAogICAgICAgICAgICBnX3Rva2VuX3BhdGgsCiAgICAgICAg"
    "ICAgIGxvZ2dlcj1sYW1iZGEgbXNnLCBsZXZlbD0iSU5GTyI6IHNlbGYuX2RpYWdfdGFiLmxvZyhm"
    "IltHRFJJVkVdIHttc2d9IiwgbGV2ZWwpCiAgICAgICAgKQoKICAgICAgICAjIFNlZWQgTFNMIHJ1"
    "bGVzIG9uIGZpcnN0IHJ1bgogICAgICAgIHNlbGYuX2xlc3NvbnMuc2VlZF9sc2xfcnVsZXMoKQoK"
    "ICAgICAgICAjIExvYWQgZW50aXR5IHN0YXRlCiAgICAgICAgc2VsZi5fc3RhdGUgPSBzZWxmLl9t"
    "ZW1vcnkubG9hZF9zdGF0ZSgpCiAgICAgICAgc2VsZi5fc3RhdGVbInNlc3Npb25fY291bnQiXSA9"
    "IHNlbGYuX3N0YXRlLmdldCgic2Vzc2lvbl9jb3VudCIsMCkgKyAxCiAgICAgICAgc2VsZi5fc3Rh"
    "dGVbImxhc3Rfc3RhcnR1cCJdICA9IGxvY2FsX25vd19pc28oKQogICAgICAgIHNlbGYuX21lbW9y"
    "eS5zYXZlX3N0YXRlKHNlbGYuX3N0YXRlKQoKICAgICAgICAjIEJ1aWxkIGFkYXB0b3IKICAgICAg"
    "ICBzZWxmLl9hZGFwdG9yID0gYnVpbGRfYWRhcHRvcl9mcm9tX2NvbmZpZygpCgogICAgICAgICMg"
    "RmFjZSB0aW1lciBtYW5hZ2VyIChzZXQgdXAgYWZ0ZXIgd2lkZ2V0cyBidWlsdCkKICAgICAgICBz"
    "ZWxmLl9mYWNlX3RpbWVyX21ncjogT3B0aW9uYWxbRmFjZVRpbWVyTWFuYWdlcl0gPSBOb25lCgog"
    "ICAgICAgICMg4pSA4pSAIEJ1aWxkIFVJIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgICAgIHNlbGYuc2V0V2luZG93VGl0bGUoQVBQX05BTUUpCiAgICAgICAgc2Vs"
    "Zi5zZXRNaW5pbXVtU2l6ZSgxMjAwLCA3NTApCiAgICAgICAgc2VsZi5yZXNpemUoMTM1MCwgODUw"
    "KQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldChTVFlMRSkKCiAgICAgICAgc2VsZi5fYnVpbGRf"
    "dWkoKQoKICAgICAgICAjIEZhY2UgdGltZXIgbWFuYWdlciB3aXJlZCB0byB3aWRnZXRzCiAgICAg"
    "ICAgc2VsZi5fZmFjZV90aW1lcl9tZ3IgPSBGYWNlVGltZXJNYW5hZ2VyKAogICAgICAgICAgICBz"
    "ZWxmLl9taXJyb3IsIHNlbGYuX2Vtb3Rpb25fYmxvY2sKICAgICAgICApCgogICAgICAgICMg4pSA"
    "4pSAIFRpbWVycyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICAgICBzZWxmLl9zdGF0c190aW1lciA9IFFUaW1lcigpCiAgICAgICAgc2VsZi5fc3RhdHNf"
    "dGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX3VwZGF0ZV9zdGF0cykKICAgICAgICBzZWxmLl9z"
    "dGF0c190aW1lci5zdGFydCgxMDAwKQoKICAgICAgICBzZWxmLl9ibGlua190aW1lciA9IFFUaW1l"
    "cigpCiAgICAgICAgc2VsZi5fYmxpbmtfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX2JsaW5r"
    "KQogICAgICAgIHNlbGYuX2JsaW5rX3RpbWVyLnN0YXJ0KDgwMCkKCiAgICAgICAgc2VsZi5fc3Rh"
    "dGVfc3RyaXBfdGltZXIgPSBRVGltZXIoKQogICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEIGFu"
    "ZCBzZWxmLl9mb290ZXJfc3RyaXAgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3N0YXRl"
    "X3N0cmlwX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9mb290ZXJfc3RyaXAucmVmcmVzaCkK"
    "ICAgICAgICAgICAgc2VsZi5fc3RhdGVfc3RyaXBfdGltZXIuc3RhcnQoNjAwMDApCgogICAgICAg"
    "IHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAgICAgc2VsZi5f"
    "Z29vZ2xlX2luYm91bmRfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX29uX2dvb2dsZV9pbmJv"
    "dW5kX3RpbWVyX3RpY2spCiAgICAgICAgc2VsZi5fZ29vZ2xlX2luYm91bmRfdGltZXIuc3RhcnQo"
    "c2VsZi5fZ2V0X2dvb2dsZV9yZWZyZXNoX2ludGVydmFsX21zKCkpCgogICAgICAgIHNlbGYuX2dv"
    "b2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXIgPSBRVGltZXIoc2VsZikKICAgICAgICBzZWxmLl9n"
    "b29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9vbl9nb29n"
    "bGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyX3RpY2spCiAgICAgICAgc2VsZi5fZ29vZ2xlX3JlY29y"
    "ZHNfcmVmcmVzaF90aW1lci5zdGFydChzZWxmLl9nZXRfZ29vZ2xlX3JlZnJlc2hfaW50ZXJ2YWxf"
    "bXMoKSkKCiAgICAgICAgIyDilIDilIAgU2NoZWR1bGVyIGFuZCBzdGFydHVwIGRlZmVycmVkIHVu"
    "dGlsIGFmdGVyIHdpbmRvdy5zaG93KCkg4pSA4pSA4pSACiAgICAgICAgIyBEbyBOT1QgY2FsbCBf"
    "c2V0dXBfc2NoZWR1bGVyKCkgb3IgX3N0YXJ0dXBfc2VxdWVuY2UoKSBoZXJlLgogICAgICAgICMg"
    "Qm90aCBhcmUgdHJpZ2dlcmVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBmcm9tIG1haW4oKSBhZnRl"
    "cgogICAgICAgICMgd2luZG93LnNob3coKSBhbmQgYXBwLmV4ZWMoKSBiZWdpbnMgcnVubmluZy4K"
    "CiAgICAjIOKUgOKUgCBVSSBDT05TVFJVQ1RJT04g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2J1aWxkX3VpKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgY2VudHJhbCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuc2V0Q2VudHJhbFdp"
    "ZGdldChjZW50cmFsKQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChjZW50cmFsKQogICAgICAg"
    "IHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAgcm9vdC5zZXRTcGFj"
    "aW5nKDQpCgogICAgICAgICMg4pSA4pSAIFRpdGxlIGJhciDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9idWlsZF90aXRsZV9i"
    "YXIoKSkKCiAgICAgICAgIyDilIDilIAgQm9keTogSm91cm5hbCB8IENoYXQgfCBTeXN0ZW1zIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGJvZHkgPSBRSEJveExheW91dCgp"
    "CiAgICAgICAgYm9keS5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgSm91cm5hbCBzaWRlYmFyIChs"
    "ZWZ0KQogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhciA9IEpvdXJuYWxTaWRlYmFyKHNlbGYu"
    "X3Nlc3Npb25zKQogICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXNzaW9uX2xvYWRfcmVx"
    "dWVzdGVkLmNvbm5lY3QoCiAgICAgICAgICAgIHNlbGYuX2xvYWRfam91cm5hbF9zZXNzaW9uKQog"
    "ICAgICAgIHNlbGYuX2pvdXJuYWxfc2lkZWJhci5zZXNzaW9uX2NsZWFyX3JlcXVlc3RlZC5jb25u"
    "ZWN0KAogICAgICAgICAgICBzZWxmLl9jbGVhcl9qb3VybmFsX3Nlc3Npb24pCiAgICAgICAgYm9k"
    "eS5hZGRXaWRnZXQoc2VsZi5fam91cm5hbF9zaWRlYmFyKQoKICAgICAgICAjIENoYXQgcGFuZWwg"
    "KGNlbnRlciwgZXhwYW5kcykKICAgICAgICBib2R5LmFkZExheW91dChzZWxmLl9idWlsZF9jaGF0"
    "X3BhbmVsKCksIDEpCgogICAgICAgICMgU3lzdGVtcyAocmlnaHQpCiAgICAgICAgYm9keS5hZGRM"
    "YXlvdXQoc2VsZi5fYnVpbGRfc3BlbGxib29rX3BhbmVsKCkpCgogICAgICAgIHJvb3QuYWRkTGF5"
    "b3V0KGJvZHksIDEpCgogICAgICAgICMg4pSA4pSAIEZvb3RlciDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBmb290ZXIgPSBRTGFiZWwoCiAgICAg"
    "ICAgICAgIGYi4pymIHtBUFBfTkFNRX0g4oCUIHZ7QVBQX1ZFUlNJT059IOKcpiIKICAgICAgICAp"
    "CiAgICAgICAgZm9vdGVyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RF"
    "WFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGxldHRlci1zcGFjaW5nOiAycHg7ICIKICAgICAgICAg"
    "ICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAg"
    "Zm9vdGVyLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAg"
    "IHJvb3QuYWRkV2lkZ2V0KGZvb3RlcikKCiAgICBkZWYgX2J1aWxkX3RpdGxlX2JhcihzZWxmKSAt"
    "PiBRV2lkZ2V0OgogICAgICAgIGJhciA9IFFXaWRnZXQoKQogICAgICAgIGJhci5zZXRGaXhlZEhl"
    "aWdodCgzNikKICAgICAgICBiYXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3Jv"
    "dW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAg"
    "ICAgICAgZiJib3JkZXItcmFkaXVzOiAycHg7IgogICAgICAgICkKICAgICAgICBsYXlvdXQgPSBR"
    "SEJveExheW91dChiYXIpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygxMCwgMCwg"
    "MTAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNikKCiAgICAgICAgdGl0bGUgPSBRTGFi"
    "ZWwoZiLinKYge0FQUF9OQU1FfSIpCiAgICAgICAgdGl0bGUuc2V0U3R5bGVTaGVldCgKICAgICAg"
    "ICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTNweDsgZm9udC13ZWlnaHQ6"
    "IGJvbGQ7ICIKICAgICAgICAgICAgZiJsZXR0ZXItc3BhY2luZzogMnB4OyBib3JkZXI6IG5vbmU7"
    "IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKCiAgICAgICAgcnVu"
    "ZXMgPSBRTGFiZWwoUlVORVMpCiAgICAgICAgcnVuZXMuc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgZiJjb2xvcjoge0NfR09MRF9ESU19OyBmb250LXNpemU6IDEwcHg7IGJvcmRlcjogbm9uZTsi"
    "CiAgICAgICAgKQogICAgICAgIHJ1bmVzLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFs"
    "aWduQ2VudGVyKQoKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbCA9IFFMYWJlbChmIuKXiSB7VUlf"
    "T0ZGTElORV9TVEFUVVN9IikKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImNvbG9yOiB7Q19CTE9PRH07IGZvbnQtc2l6ZTogMTJweDsgZm9udC13"
    "ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuc3RhdHVz"
    "X2xhYmVsLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduUmlnaHQpCgogICAgICAg"
    "ICMgU3VzcGVuc2lvbiBwYW5lbAogICAgICAgIHNlbGYuX3RvcnBvcl9wYW5lbCA9IE5vbmUKICAg"
    "ICAgICBpZiBTVVNQRU5TSU9OX0VOQUJMRUQ6CiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9wYW5l"
    "bCA9IFRvcnBvclBhbmVsKCkKICAgICAgICAgICAgc2VsZi5fdG9ycG9yX3BhbmVsLnN0YXRlX2No"
    "YW5nZWQuY29ubmVjdChzZWxmLl9vbl90b3Jwb3Jfc3RhdGVfY2hhbmdlZCkKCiAgICAgICAgIyBJ"
    "ZGxlIHRvZ2dsZQogICAgICAgIGlkbGVfZW5hYmxlZCA9IGJvb2woQ0ZHLmdldCgic2V0dGluZ3Mi"
    "LCB7fSkuZ2V0KCJpZGxlX2VuYWJsZWQiLCBGYWxzZSkpCiAgICAgICAgc2VsZi5faWRsZV9idG4g"
    "PSBRUHVzaEJ1dHRvbigiSURMRSBPTiIgaWYgaWRsZV9lbmFibGVkIGVsc2UgIklETEUgT0ZGIikK"
    "ICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRGaXhlZEhlaWdodCgyMikKICAgICAgICBzZWxmLl9p"
    "ZGxlX2J0bi5zZXRDaGVja2FibGUoVHJ1ZSkKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRDaGVj"
    "a2VkKGlkbGVfZW5hYmxlZCkKICAgICAgICBzZWxmLl9pZGxlX2J0bi5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIK"
    "ICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVz"
    "OiAycHg7ICIKICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7"
    "IHBhZGRpbmc6IDNweCA4cHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl9pZGxlX2J0bi50b2dn"
    "bGVkLmNvbm5lY3Qoc2VsZi5fb25faWRsZV90b2dnbGVkKQoKICAgICAgICAjIEZTIC8gQkwgYnV0"
    "dG9ucwogICAgICAgIHNlbGYuX2ZzX2J0biA9IFFQdXNoQnV0dG9uKCJGdWxsc2NyZWVuIikKICAg"
    "ICAgICBzZWxmLl9ibF9idG4gPSBRUHVzaEJ1dHRvbigiQm9yZGVybGVzcyIpCiAgICAgICAgc2Vs"
    "Zi5fZXhwb3J0X2J0biA9IFFQdXNoQnV0dG9uKCJFeHBvcnQiKQogICAgICAgIHNlbGYuX3NodXRk"
    "b3duX2J0biA9IFFQdXNoQnV0dG9uKCJTaHV0ZG93biIpCiAgICAgICAgZm9yIGJ0biBpbiAoc2Vs"
    "Zi5fZnNfYnRuLCBzZWxmLl9ibF9idG4sIHNlbGYuX2V4cG9ydF9idG4pOgogICAgICAgICAgICBi"
    "dG4uc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgICAgIGJ0bi5zZXRTdHlsZVNoZWV0KAogICAg"
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
    "IGxheW91dC5hZGRTcGFjaW5nKDgpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9leHBv"
    "cnRfYnRuKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fc2h1dGRvd25fYnRuKQoKICAg"
    "ICAgICByZXR1cm4gYmFyCgogICAgZGVmIF9idWlsZF9jaGF0X3BhbmVsKHNlbGYpIC0+IFFWQm94"
    "TGF5b3V0OgogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KCkKICAgICAgICBsYXlvdXQuc2V0"
    "U3BhY2luZyg0KQoKICAgICAgICAjIE1haW4gdGFiIHdpZGdldCDigJQgcGVyc29uYSBjaGF0IHRh"
    "YiB8IFNlbGYKICAgICAgICBzZWxmLl9tYWluX3RhYnMgPSBRVGFiV2lkZ2V0KCkKICAgICAgICBz"
    "ZWxmLl9tYWluX3RhYnMuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJRVGFiV2lkZ2V0Ojpw"
    "YW5lIHt7IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBm"
    "ImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyB9fSIKICAgICAgICAgICAgZiJRVGFiQmFyOjp0YWIg"
    "e3sgYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAg"
    "ICBmInBhZGRpbmc6IDRweCAxMnB4OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAg"
    "ICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAx"
    "MHB4OyB9fSIKICAgICAgICAgICAgZiJRVGFiQmFyOjp0YWI6c2VsZWN0ZWQge3sgYmFja2dyb3Vu"
    "ZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLWJvdHRv"
    "bTogMnB4IHNvbGlkIHtDX0NSSU1TT059OyB9fSIKICAgICAgICApCgogICAgICAgICMg4pSA4pSA"
    "IFRhYiAwOiBQZXJzb25hIGNoYXQgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlYW5jZV93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAg"
    "ICBzZWFuY2VfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VhbmNlX3dpZGdldCkKICAgICAgICBzZWFu"
    "Y2VfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlYW5jZV9s"
    "YXlvdXQuc2V0U3BhY2luZygwKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheSA9IFFUZXh0RWRp"
    "dCgpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAg"
    "c2VsZi5fY2hhdF9kaXNwbGF5LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3Vu"
    "ZDoge0NfTU9OSVRPUn07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjog"
    "bm9uZTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZv"
    "bnQtc2l6ZTogMTJweDsgcGFkZGluZzogOHB4OyIKICAgICAgICApCiAgICAgICAgc2VhbmNlX2xh"
    "eW91dC5hZGRXaWRnZXQoc2VsZi5fY2hhdF9kaXNwbGF5KQogICAgICAgIHNlbGYuX21haW5fdGFi"
    "cy5hZGRUYWIoc2VhbmNlX3dpZGdldCwgZiLinacge1VJX0NIQVRfV0lORE9XfSIpCgogICAgICAg"
    "ICMg4pSA4pSAIFRhYiAxOiBTZWxmIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ICAgIHNlbGYuX3NlbGZfdGFiX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGZfbGF5b3V0"
    "ID0gUVZCb3hMYXlvdXQoc2VsZi5fc2VsZl90YWJfd2lkZ2V0KQogICAgICAgIHNlbGZfbGF5b3V0"
    "LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGZfbGF5b3V0LnNldFNw"
    "YWNpbmcoNCkKICAgICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAg"
    "IHNlbGYuX3NlbGZfZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX3NlbGZf"
    "ZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX01PTklU"
    "T1J9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7ICIKICAg"
    "ICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEy"
    "cHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHNlbGZfbGF5b3V0LmFkZFdpZGdl"
    "dChzZWxmLl9zZWxmX2Rpc3BsYXksIDEpCiAgICAgICAgc2VsZi5fbWFpbl90YWJzLmFkZFRhYihz"
    "ZWxmLl9zZWxmX3RhYl93aWRnZXQsICLil4kgU0VMRiIpCgogICAgICAgIGxheW91dC5hZGRXaWRn"
    "ZXQoc2VsZi5fbWFpbl90YWJzLCAxKQoKICAgICAgICAjIOKUgOKUgCBCb3R0b20gc3RhdHVzL3Jl"
    "c291cmNlIGJsb2NrIHJvdyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICAjIE1hbmRh"
    "dG9yeSBwZXJtYW5lbnQgc3RydWN0dXJlIGFjcm9zcyBhbGwgcGVyc29uYXM6CiAgICAgICAgIyBN"
    "SVJST1IgfCBbTE9XRVItTUlERExFIFBFUk1BTkVOVCBGT09UUFJJTlRdCiAgICAgICAgYmxvY2tf"
    "cm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJsb2NrX3Jvdy5zZXRTcGFjaW5nKDIpCgogICAg"
    "ICAgICMgTWlycm9yIChuZXZlciBjb2xsYXBzZXMpCiAgICAgICAgbWlycm9yX3dyYXAgPSBRV2lk"
    "Z2V0KCkKICAgICAgICBtd19sYXlvdXQgPSBRVkJveExheW91dChtaXJyb3Jfd3JhcCkKICAgICAg"
    "ICBtd19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgbXdfbGF5"
    "b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBtd19sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xi"
    "bChmIuKdpyB7VUlfTUlSUk9SX0xBQkVMfSIpKQogICAgICAgIHNlbGYuX21pcnJvciA9IE1pcnJv"
    "cldpZGdldCgpCiAgICAgICAgc2VsZi5fbWlycm9yLnNldEZpeGVkU2l6ZSgxNjAsIDE2MCkKICAg"
    "ICAgICBtd19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX21pcnJvcikKICAgICAgICBibG9ja19yb3cu"
    "YWRkV2lkZ2V0KG1pcnJvcl93cmFwLCAwKQoKICAgICAgICAjIE1pZGRsZSBsb3dlciBibG9jayBr"
    "ZWVwcyBhIHBlcm1hbmVudCBmb290cHJpbnQ6CiAgICAgICAgIyBsZWZ0ID0gY29tcGFjdCBzdGFj"
    "ayBhcmVhLCByaWdodCA9IGZpeGVkIGV4cGFuZGVkLXJvdyBzbG90cy4KICAgICAgICBtaWRkbGVf"
    "d3JhcCA9IFFXaWRnZXQoKQogICAgICAgIG1pZGRsZV9sYXlvdXQgPSBRSEJveExheW91dChtaWRk"
    "bGVfd3JhcCkKICAgICAgICBtaWRkbGVfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAw"
    "LCAwKQogICAgICAgIG1pZGRsZV9sYXlvdXQuc2V0U3BhY2luZygyKQoKICAgICAgICBzZWxmLl9s"
    "b3dlcl9zdGFja193cmFwID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfd3Jh"
    "cC5zZXRNaW5pbXVtV2lkdGgoMTMwKQogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX3dyYXAuc2V0"
    "TWF4aW11bVdpZHRoKDEzMCkKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja19sYXlvdXQgPSBRVkJv"
    "eExheW91dChzZWxmLl9sb3dlcl9zdGFja193cmFwKQogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNr"
    "X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWxmLl9sb3dl"
    "cl9zdGFja19sYXlvdXQuc2V0U3BhY2luZygyKQogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX3dy"
    "YXAuc2V0VmlzaWJsZShGYWxzZSkKICAgICAgICBtaWRkbGVfbGF5b3V0LmFkZFdpZGdldChzZWxm"
    "Ll9sb3dlcl9zdGFja193cmFwLCAwKQoKICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3cg"
    "PSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0ID0gUUdy"
    "aWRMYXlvdXQoc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93KQogICAgICAgIHNlbGYuX2xvd2VyX2V4"
    "cGFuZGVkX3Jvd19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAg"
    "c2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93X2xheW91dC5zZXRIb3Jpem9udGFsU3BhY2luZygyKQog"
    "ICAgICAgIHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Jvd19sYXlvdXQuc2V0VmVydGljYWxTcGFjaW5n"
    "KDIpCiAgICAgICAgbWlkZGxlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fbG93ZXJfZXhwYW5kZWRf"
    "cm93LCAxKQoKICAgICAgICAjIEVtb3Rpb24gYmxvY2sgKGNvbGxhcHNpYmxlKQogICAgICAgIHNl"
    "bGYuX2Vtb3Rpb25fYmxvY2sgPSBFbW90aW9uQmxvY2soKQogICAgICAgIHNlbGYuX2Vtb3Rpb25f"
    "YmxvY2tfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2soCiAgICAgICAgICAgIGYi4p2nIHtVSV9FTU9U"
    "SU9OU19MQUJFTH0iLCBzZWxmLl9lbW90aW9uX2Jsb2NrLAogICAgICAgICAgICBleHBhbmRlZD1U"
    "cnVlLCBtaW5fd2lkdGg9MTMwLCByZXNlcnZlX3dpZHRoPVRydWUKICAgICAgICApCgogICAgICAg"
    "ICMgTGVmdCByZXNvdXJjZSBvcmIgKGNvbGxhcHNpYmxlKQogICAgICAgIHNlbGYuX2xlZnRfb3Ji"
    "ID0gU3BoZXJlV2lkZ2V0KAogICAgICAgICAgICBVSV9MRUZUX09SQl9MQUJFTCwgQ19DUklNU09O"
    "LCBDX0NSSU1TT05fRElNCiAgICAgICAgKQogICAgICAgIHNlbGYuX2xlZnRfb3JiX3dyYXAgPSBD"
    "b2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfTEVGVF9PUkJfVElUTEV9Iiwg"
    "c2VsZi5fbGVmdF9vcmIsCiAgICAgICAgICAgIG1pbl93aWR0aD05MCwgcmVzZXJ2ZV93aWR0aD1U"
    "cnVlCiAgICAgICAgKQoKICAgICAgICAjIENlbnRlciBjeWNsZSB3aWRnZXQgKGNvbGxhcHNpYmxl"
    "KQogICAgICAgIHNlbGYuX2N5Y2xlX3dpZGdldCA9IEN5Y2xlV2lkZ2V0KCkKICAgICAgICBzZWxm"
    "Ll9jeWNsZV93cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacge1VJX0NZ"
    "Q0xFX1RJVExFfSIsIHNlbGYuX2N5Y2xlX3dpZGdldCwKICAgICAgICAgICAgbWluX3dpZHRoPTkw"
    "LCByZXNlcnZlX3dpZHRoPVRydWUKICAgICAgICApCgogICAgICAgICMgUmlnaHQgcmVzb3VyY2Ug"
    "b3JiIChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9yaWdodF9vcmIgPSBTcGhlcmVXaWRnZXQo"
    "CiAgICAgICAgICAgIFVJX1JJR0hUX09SQl9MQUJFTCwgQ19QVVJQTEUsIENfUFVSUExFX0RJTQog"
    "ICAgICAgICkKICAgICAgICBzZWxmLl9yaWdodF9vcmJfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2so"
    "CiAgICAgICAgICAgIGYi4p2nIHtVSV9SSUdIVF9PUkJfVElUTEV9Iiwgc2VsZi5fcmlnaHRfb3Ji"
    "LAogICAgICAgICAgICBtaW5fd2lkdGg9OTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAgICAgICkK"
    "CiAgICAgICAgIyBFc3NlbmNlICgyIGdhdWdlcywgY29sbGFwc2libGUpCiAgICAgICAgZXNzZW5j"
    "ZV93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBlc3NlbmNlX2xheW91dCA9IFFWQm94TGF5b3V0"
    "KGVzc2VuY2Vfd2lkZ2V0KQogICAgICAgIGVzc2VuY2VfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lu"
    "cyg0LCA0LCA0LCA0KQogICAgICAgIGVzc2VuY2VfbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAg"
    "ICBzZWxmLl9lc3NlbmNlX3ByaW1hcnlfZ2F1Z2UgICA9IEdhdWdlV2lkZ2V0KFVJX0VTU0VOQ0Vf"
    "UFJJTUFSWSwgICAiJSIsIDEwMC4wLCBDX0NSSU1TT04pCiAgICAgICAgc2VsZi5fZXNzZW5jZV9z"
    "ZWNvbmRhcnlfZ2F1Z2UgPSBHYXVnZVdpZGdldChVSV9FU1NFTkNFX1NFQ09OREFSWSwgIiUiLCAx"
    "MDAuMCwgQ19HUkVFTikKICAgICAgICBlc3NlbmNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fZXNz"
    "ZW5jZV9wcmltYXJ5X2dhdWdlKQogICAgICAgIGVzc2VuY2VfbGF5b3V0LmFkZFdpZGdldChzZWxm"
    "Ll9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZSkKICAgICAgICBzZWxmLl9lc3NlbmNlX3dyYXAgPSBD"
    "b2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfRVNTRU5DRV9USVRMRX0iLCBl"
    "c3NlbmNlX3dpZGdldCwKICAgICAgICAgICAgbWluX3dpZHRoPTExMCwgcmVzZXJ2ZV93aWR0aD1U"
    "cnVlCiAgICAgICAgKQoKICAgICAgICAjIEV4cGFuZGVkIHJvdyBzbG90cyBtdXN0IHN0YXkgaW4g"
    "Y2Fub25pY2FsIHZpc3VhbCBvcmRlci4KICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9zbG90"
    "X29yZGVyID0gWwogICAgICAgICAgICAiZW1vdGlvbnMiLCAicHJpbWFyeSIsICJjeWNsZSIsICJz"
    "ZWNvbmRhcnkiLCAiZXNzZW5jZSIKICAgICAgICBdCiAgICAgICAgc2VsZi5fbG93ZXJfY29tcGFj"
    "dF9zdGFja19vcmRlciA9IFsKICAgICAgICAgICAgImN5Y2xlIiwgInByaW1hcnkiLCAic2Vjb25k"
    "YXJ5IiwgImVzc2VuY2UiLCAiZW1vdGlvbnMiCiAgICAgICAgXQogICAgICAgIHNlbGYuX2xvd2Vy"
    "X21vZHVsZV93cmFwcyA9IHsKICAgICAgICAgICAgImVtb3Rpb25zIjogc2VsZi5fZW1vdGlvbl9i"
    "bG9ja193cmFwLAogICAgICAgICAgICAicHJpbWFyeSI6IHNlbGYuX2xlZnRfb3JiX3dyYXAsCiAg"
    "ICAgICAgICAgICJjeWNsZSI6IHNlbGYuX2N5Y2xlX3dyYXAsCiAgICAgICAgICAgICJzZWNvbmRh"
    "cnkiOiBzZWxmLl9yaWdodF9vcmJfd3JhcCwKICAgICAgICAgICAgImVzc2VuY2UiOiBzZWxmLl9l"
    "c3NlbmNlX3dyYXAsCiAgICAgICAgfQoKICAgICAgICBzZWxmLl9sb3dlcl9yb3dfc2xvdHMgPSB7"
    "fQogICAgICAgIGZvciBjb2wsIGtleSBpbiBlbnVtZXJhdGUoc2VsZi5fbG93ZXJfZXhwYW5kZWRf"
    "c2xvdF9vcmRlcik6CiAgICAgICAgICAgIHNsb3QgPSBRV2lkZ2V0KCkKICAgICAgICAgICAgc2xv"
    "dF9sYXlvdXQgPSBRVkJveExheW91dChzbG90KQogICAgICAgICAgICBzbG90X2xheW91dC5zZXRD"
    "b250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICAgICAgc2xvdF9sYXlvdXQuc2V0U3Bh"
    "Y2luZygwKQogICAgICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LmFkZFdp"
    "ZGdldChzbG90LCAwLCBjb2wpCiAgICAgICAgICAgIHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Jvd19s"
    "YXlvdXQuc2V0Q29sdW1uU3RyZXRjaChjb2wsIDEpCiAgICAgICAgICAgIHNlbGYuX2xvd2VyX3Jv"
    "d19zbG90c1trZXldID0gc2xvdF9sYXlvdXQKCiAgICAgICAgZm9yIHdyYXAgaW4gc2VsZi5fbG93"
    "ZXJfbW9kdWxlX3dyYXBzLnZhbHVlcygpOgogICAgICAgICAgICB3cmFwLnRvZ2dsZWQuY29ubmVj"
    "dChzZWxmLl9yZWZyZXNoX2xvd2VyX21pZGRsZV9sYXlvdXQpCgogICAgICAgIHNlbGYuX3JlZnJl"
    "c2hfbG93ZXJfbWlkZGxlX2xheW91dCgpCgogICAgICAgIGJsb2NrX3Jvdy5hZGRXaWRnZXQobWlk"
    "ZGxlX3dyYXAsIDEpCiAgICAgICAgbGF5b3V0LmFkZExheW91dChibG9ja19yb3cpCgogICAgICAg"
    "ICMgRm9vdGVyIHN0YXRlIHN0cmlwIChiZWxvdyBibG9jayByb3cg4oCUIHBlcm1hbmVudCBVSSBz"
    "dHJ1Y3R1cmUpCiAgICAgICAgc2VsZi5fZm9vdGVyX3N0cmlwID0gRm9vdGVyU3RyaXBXaWRnZXQo"
    "KQogICAgICAgIHNlbGYuX2Zvb3Rlcl9zdHJpcC5zZXRfbGFiZWwoVUlfRk9PVEVSX1NUUklQX0xB"
    "QkVMKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZm9vdGVyX3N0cmlwKQoKICAgICAg"
    "ICAjIOKUgOKUgCBJbnB1dCByb3cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgaW5wdXRfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHByb21wdF9zeW0gPSBR"
    "TGFiZWwoIuKcpiIpCiAgICAgICAgcHJvbXB0X3N5bS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmImNvbG9yOiB7Q19DUklNU09OfTsgZm9udC1zaXplOiAxNnB4OyBmb250LXdlaWdodDogYm9s"
    "ZDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAgcHJvbXB0X3N5bS5zZXRGaXhlZFdp"
    "ZHRoKDIwKQoKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZCA9IFFMaW5lRWRpdCgpCiAgICAgICAg"
    "c2VsZi5faW5wdXRfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KFVJX0lOUFVUX1BMQUNFSE9MREVS"
    "KQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnJldHVyblByZXNzZWQuY29ubmVjdChzZWxmLl9z"
    "ZW5kX21lc3NhZ2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkK"
    "CiAgICAgICAgc2VsZi5fc2VuZF9idG4gPSBRUHVzaEJ1dHRvbihVSV9TRU5EX0JVVFRPTikKICAg"
    "ICAgICBzZWxmLl9zZW5kX2J0bi5zZXRGaXhlZFdpZHRoKDExMCkKICAgICAgICBzZWxmLl9zZW5k"
    "X2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2VuZF9tZXNzYWdlKQogICAgICAgIHNlbGYuX3Nl"
    "bmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCgogICAgICAgIGlucHV0X3Jvdy5hZGRXaWRnZXQocHJv"
    "bXB0X3N5bSkKICAgICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2lucHV0X2ZpZWxkKQog"
    "ICAgICAgIGlucHV0X3Jvdy5hZGRXaWRnZXQoc2VsZi5fc2VuZF9idG4pCiAgICAgICAgbGF5b3V0"
    "LmFkZExheW91dChpbnB1dF9yb3cpCgogICAgICAgIHJldHVybiBsYXlvdXQKCiAgICBkZWYgX2Ns"
    "ZWFyX2xheW91dF93aWRnZXRzKHNlbGYsIGxheW91dDogUVZCb3hMYXlvdXQpIC0+IE5vbmU6CiAg"
    "ICAgICAgd2hpbGUgbGF5b3V0LmNvdW50KCk6CiAgICAgICAgICAgIGl0ZW0gPSBsYXlvdXQudGFr"
    "ZUF0KDApCiAgICAgICAgICAgIHdpZGdldCA9IGl0ZW0ud2lkZ2V0KCkKICAgICAgICAgICAgaWYg"
    "d2lkZ2V0IGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgd2lkZ2V0LnNldFBhcmVudChOb25l"
    "KQoKICAgIGRlZiBfcmVmcmVzaF9sb3dlcl9taWRkbGVfbGF5b3V0KHNlbGYsICpfYXJncykgLT4g"
    "Tm9uZToKICAgICAgICBjb2xsYXBzZWRfY291bnQgPSAwCgogICAgICAgICMgUmVidWlsZCBleHBh"
    "bmRlZCByb3cgc2xvdHMgaW4gZml4ZWQgZXhwYW5kZWQgb3JkZXIuCiAgICAgICAgZm9yIGtleSBp"
    "biBzZWxmLl9sb3dlcl9leHBhbmRlZF9zbG90X29yZGVyOgogICAgICAgICAgICBzbG90X2xheW91"
    "dCA9IHNlbGYuX2xvd2VyX3Jvd19zbG90c1trZXldCiAgICAgICAgICAgIHNlbGYuX2NsZWFyX2xh"
    "eW91dF93aWRnZXRzKHNsb3RfbGF5b3V0KQogICAgICAgICAgICB3cmFwID0gc2VsZi5fbG93ZXJf"
    "bW9kdWxlX3dyYXBzW2tleV0KICAgICAgICAgICAgaWYgd3JhcC5pc19leHBhbmRlZCgpOgogICAg"
    "ICAgICAgICAgICAgc2xvdF9sYXlvdXQuYWRkV2lkZ2V0KHdyYXApCiAgICAgICAgICAgIGVsc2U6"
    "CiAgICAgICAgICAgICAgICBjb2xsYXBzZWRfY291bnQgKz0gMQogICAgICAgICAgICAgICAgc2xv"
    "dF9sYXlvdXQuYWRkU3RyZXRjaCgxKQoKICAgICAgICAjIFJlYnVpbGQgY29tcGFjdCBzdGFjayBp"
    "biBjYW5vbmljYWwgY29tcGFjdCBvcmRlci4KICAgICAgICBzZWxmLl9jbGVhcl9sYXlvdXRfd2lk"
    "Z2V0cyhzZWxmLl9sb3dlcl9zdGFja19sYXlvdXQpCiAgICAgICAgZm9yIGtleSBpbiBzZWxmLl9s"
    "b3dlcl9jb21wYWN0X3N0YWNrX29yZGVyOgogICAgICAgICAgICB3cmFwID0gc2VsZi5fbG93ZXJf"
    "bW9kdWxlX3dyYXBzW2tleV0KICAgICAgICAgICAgaWYgbm90IHdyYXAuaXNfZXhwYW5kZWQoKToK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX2xheW91dC5hZGRXaWRnZXQod3JhcCkK"
    "CiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0LmFkZFN0cmV0Y2goMSkKICAgICAgICBz"
    "ZWxmLl9sb3dlcl9zdGFja193cmFwLnNldFZpc2libGUoY29sbGFwc2VkX2NvdW50ID4gMCkKCiAg"
    "ICBkZWYgX2J1aWxkX3NwZWxsYm9va19wYW5lbChzZWxmKSAtPiBRVkJveExheW91dDoKICAgICAg"
    "ICBsYXlvdXQgPSBRVkJveExheW91dCgpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lu"
    "cygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgbGF5b3V0"
    "LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBTWVNURU1TIikpCgogICAgICAgICMgVGFiIHdp"
    "ZGdldAogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMgPSBRVGFiV2lkZ2V0KCkKICAgICAgICBzZWxm"
    "Ll9zcGVsbF90YWJzLnNldE1pbmltdW1XaWR0aCgyODApCiAgICAgICAgc2VsZi5fc3BlbGxfdGFi"
    "cy5zZXRTaXplUG9saWN5KAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5n"
    "LAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nCiAgICAgICAgKQogICAg"
    "ICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIgPSBMb2NrQXdhcmVUYWJCYXIoc2VsZi5faXNfc3BlbGxf"
    "dGFiX2xvY2tlZCwgc2VsZi5fc3BlbGxfdGFicykKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLnNl"
    "dFRhYkJhcihzZWxmLl9zcGVsbF90YWJfYmFyKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIu"
    "c2V0TW92YWJsZShUcnVlKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIuc2V0Q29udGV4dE1l"
    "bnVQb2xpY3koUXQuQ29udGV4dE1lbnVQb2xpY3kuQ3VzdG9tQ29udGV4dE1lbnUpCiAgICAgICAg"
    "c2VsZi5fc3BlbGxfdGFiX2Jhci5jdXN0b21Db250ZXh0TWVudVJlcXVlc3RlZC5jb25uZWN0KHNl"
    "bGYuX3Nob3dfc3BlbGxfdGFiX2NvbnRleHRfbWVudSkKICAgICAgICBzZWxmLl9zcGVsbF90YWJf"
    "YmFyLnRhYk1vdmVkLmNvbm5lY3Qoc2VsZi5fb25fc3BlbGxfdGFiX2RyYWdfbW92ZWQpCiAgICAg"
    "ICAgc2VsZi5fc3BlbGxfdGFicy5jdXJyZW50Q2hhbmdlZC5jb25uZWN0KGxhbWJkYSBfaWR4OiBz"
    "ZWxmLl9leGl0X3NwZWxsX3RhYl9tb3ZlX21vZGUoKSkKICAgICAgICBpZiBub3Qgc2VsZi5fZm9j"
    "dXNfaG9va2VkX2Zvcl9zcGVsbF90YWJzOgogICAgICAgICAgICBhcHAgPSBRQXBwbGljYXRpb24u"
    "aW5zdGFuY2UoKQogICAgICAgICAgICBpZiBhcHAgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAg"
    "ICBhcHAuZm9jdXNDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fZ2xvYmFsX2ZvY3VzX2NoYW5nZWQp"
    "CiAgICAgICAgICAgICAgICBzZWxmLl9mb2N1c19ob29rZWRfZm9yX3NwZWxsX3RhYnMgPSBUcnVl"
    "CgogICAgICAgICMgQnVpbGQgRGlhZ25vc3RpY3NUYWIgZWFybHkgc28gc3RhcnR1cCBsb2dzIGFy"
    "ZSBzYWZlIGV2ZW4gYmVmb3JlCiAgICAgICAgIyB0aGUgRGlhZ25vc3RpY3MgdGFiIGlzIGF0dGFj"
    "aGVkIHRvIHRoZSB3aWRnZXQuCiAgICAgICAgc2VsZi5fZGlhZ190YWIgPSBEaWFnbm9zdGljc1Rh"
    "YigpCgogICAgICAgICMg4pSA4pSAIEluc3RydW1lbnRzIHRhYiDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICAgICBzZWxmLl9od19wYW5lbCA9IEhhcmR3YXJlUGFuZWwoKQoKICAgICAgICAjIOKUgOKU"
    "gCBSZWNvcmRzIHRhYiAocmVhbCkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIgPSBS"
    "ZWNvcmRzVGFiKCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltTUEVMTEJPT0tdIHJlYWwg"
    "UmVjb3Jkc1RhYiBhdHRhY2hlZC4iLCAiSU5GTyIpCgogICAgICAgICMg4pSA4pSAIFRhc2tzIHRh"
    "YiAocmVhbCkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fdGFza3NfdGFiID0gVGFza3NUYWIo"
    "CiAgICAgICAgICAgIHRhc2tzX3Byb3ZpZGVyPXNlbGYuX2ZpbHRlcmVkX3Rhc2tzX2Zvcl9yZWdp"
    "c3RyeSwKICAgICAgICAgICAgb25fYWRkX2VkaXRvcl9vcGVuPXNlbGYuX29wZW5fdGFza19lZGl0"
    "b3Jfd29ya3NwYWNlLAogICAgICAgICAgICBvbl9jb21wbGV0ZV9zZWxlY3RlZD1zZWxmLl9jb21w"
    "bGV0ZV9zZWxlY3RlZF90YXNrLAogICAgICAgICAgICBvbl9jYW5jZWxfc2VsZWN0ZWQ9c2VsZi5f"
    "Y2FuY2VsX3NlbGVjdGVkX3Rhc2ssCiAgICAgICAgICAgIG9uX3RvZ2dsZV9jb21wbGV0ZWQ9c2Vs"
    "Zi5fdG9nZ2xlX3Nob3dfY29tcGxldGVkX3Rhc2tzLAogICAgICAgICAgICBvbl9wdXJnZV9jb21w"
    "bGV0ZWQ9c2VsZi5fcHVyZ2VfY29tcGxldGVkX3Rhc2tzLAogICAgICAgICAgICBvbl9maWx0ZXJf"
    "Y2hhbmdlZD1zZWxmLl9vbl90YXNrX2ZpbHRlcl9jaGFuZ2VkLAogICAgICAgICAgICBvbl9lZGl0"
    "b3Jfc2F2ZT1zZWxmLl9zYXZlX3Rhc2tfZWRpdG9yX2dvb2dsZV9maXJzdCwKICAgICAgICAgICAg"
    "b25fZWRpdG9yX2NhbmNlbD1zZWxmLl9jYW5jZWxfdGFza19lZGl0b3Jfd29ya3NwYWNlLAogICAg"
    "ICAgICAgICBkaWFnbm9zdGljc19sb2dnZXI9c2VsZi5fZGlhZ190YWIubG9nLAogICAgICAgICkK"
    "ICAgICAgICBzZWxmLl90YXNrc190YWIuc2V0X3Nob3dfY29tcGxldGVkKHNlbGYuX3Rhc2tfc2hv"
    "d19jb21wbGV0ZWQpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbU1BFTExCT09LXSByZWFs"
    "IFRhc2tzVGFiIGF0dGFjaGVkLiIsICJJTkZPIikKCiAgICAgICAgIyDilIDilIAgU0wgU2NhbnMg"
    "dGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NsX3NjYW5zID0g"
    "U0xTY2Fuc1RhYihjZmdfcGF0aCgic2wiKSkKCiAgICAgICAgIyDilIDilIAgU0wgQ29tbWFuZHMg"
    "dGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NsX2NvbW1hbmRzID0gU0xDb21t"
    "YW5kc1RhYigpCgogICAgICAgICMg4pSA4pSAIEpvYiBUcmFja2VyIHRhYiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgICAgICBzZWxmLl9qb2JfdHJhY2tlciA9IEpvYlRyYWNrZXJUYWIoKQoKICAgICAg"
    "ICAjIOKUgOKUgCBMZXNzb25zIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICBzZWxmLl9sZXNzb25zX3RhYiA9IExlc3NvbnNUYWIoc2VsZi5fbGVzc29ucykKCiAgICAg"
    "ICAgIyBTZWxmIHRhYiBpcyBub3cgaW4gdGhlIG1haW4gYXJlYSBhbG9uZ3NpZGUgdGhlIHBlcnNv"
    "bmEgY2hhdCB0YWIKICAgICAgICAjIEtlZXAgYSBTZWxmVGFiIGluc3RhbmNlIGZvciBpZGxlIGNv"
    "bnRlbnQgZ2VuZXJhdGlvbgogICAgICAgIHNlbGYuX3NlbGZfdGFiID0gU2VsZlRhYigpCgogICAg"
    "ICAgICMg4pSA4pSAIE1vZHVsZSBUcmFja2VyIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9t"
    "b2R1bGVfdHJhY2tlciA9IE1vZHVsZVRyYWNrZXJUYWIoKQoKICAgICAgICAjIOKUgOKUgCBEaWNl"
    "IFJvbGxlciB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fZGljZV9yb2xsZXJf"
    "dGFiID0gRGljZVJvbGxlclRhYihkaWFnbm9zdGljc19sb2dnZXI9c2VsZi5fZGlhZ190YWIubG9n"
    "KQoKICAgICAgICAjIOKUgOKUgCBNYWdpYyA4LUJhbGwgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ICAgIHNlbGYuX21hZ2ljXzhiYWxsX3RhYiA9IE1hZ2ljOEJhbGxUYWIoCiAgICAgICAgICAgIG9u"
    "X3Rocm93PXNlbGYuX2hhbmRsZV9tYWdpY184YmFsbF90aHJvdywKICAgICAgICAgICAgZGlhZ25v"
    "c3RpY3NfbG9nZ2VyPXNlbGYuX2RpYWdfdGFiLmxvZywKICAgICAgICApCgogICAgICAgICMg4pSA"
    "4pSAIFNldHRpbmdzIHRhYiAoZGVjay13aWRlIHJ1bnRpbWUgY29udHJvbHMpIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3Nl"
    "dHRpbmdzX3RhYiA9IFNldHRpbmdzVGFiKHNlbGYpCgogICAgICAgICMgRGVzY3JpcHRvci1iYXNl"
    "ZCBvcmRlcmluZyAoc3RhYmxlIGlkZW50aXR5ICsgdmlzdWFsIG9yZGVyIG9ubHkpCiAgICAgICAg"
    "c2VsZi5fc3BlbGxfdGFiX2RlZnMgPSBbCiAgICAgICAgICAgIHsiaWQiOiAiaW5zdHJ1bWVudHMi"
    "LCAidGl0bGUiOiAiSW5zdHJ1bWVudHMiLCAid2lkZ2V0Ijogc2VsZi5faHdfcGFuZWwsICJkZWZh"
    "dWx0X29yZGVyIjogMH0sCiAgICAgICAgICAgIHsiaWQiOiAicmVjb3JkcyIsICJ0aXRsZSI6ICJS"
    "ZWNvcmRzIiwgIndpZGdldCI6IHNlbGYuX3JlY29yZHNfdGFiLCAiZGVmYXVsdF9vcmRlciI6IDF9"
    "LAogICAgICAgICAgICB7ImlkIjogInRhc2tzIiwgInRpdGxlIjogIlRhc2tzIiwgIndpZGdldCI6"
    "IHNlbGYuX3Rhc2tzX3RhYiwgImRlZmF1bHRfb3JkZXIiOiAyfSwKICAgICAgICAgICAgeyJpZCI6"
    "ICJzbF9zY2FucyIsICJ0aXRsZSI6ICJTTCBTY2FucyIsICJ3aWRnZXQiOiBzZWxmLl9zbF9zY2Fu"
    "cywgImRlZmF1bHRfb3JkZXIiOiAzfSwKICAgICAgICAgICAgeyJpZCI6ICJzbF9jb21tYW5kcyIs"
    "ICJ0aXRsZSI6ICJTTCBDb21tYW5kcyIsICJ3aWRnZXQiOiBzZWxmLl9zbF9jb21tYW5kcywgImRl"
    "ZmF1bHRfb3JkZXIiOiA0fSwKICAgICAgICAgICAgeyJpZCI6ICJqb2JfdHJhY2tlciIsICJ0aXRs"
    "ZSI6ICJKb2IgVHJhY2tlciIsICJ3aWRnZXQiOiBzZWxmLl9qb2JfdHJhY2tlciwgImRlZmF1bHRf"
    "b3JkZXIiOiA1fSwKICAgICAgICAgICAgeyJpZCI6ICJsZXNzb25zIiwgInRpdGxlIjogIkxlc3Nv"
    "bnMiLCAid2lkZ2V0Ijogc2VsZi5fbGVzc29uc190YWIsICJkZWZhdWx0X29yZGVyIjogNn0sCiAg"
    "ICAgICAgICAgIHsiaWQiOiAibW9kdWxlcyIsICJ0aXRsZSI6ICJNb2R1bGVzIiwgIndpZGdldCI6"
    "IHNlbGYuX21vZHVsZV90cmFja2VyLCAiZGVmYXVsdF9vcmRlciI6IDd9LAogICAgICAgICAgICB7"
    "ImlkIjogImRpY2Vfcm9sbGVyIiwgInRpdGxlIjogIkRpY2UgUm9sbGVyIiwgIndpZGdldCI6IHNl"
    "bGYuX2RpY2Vfcm9sbGVyX3RhYiwgImRlZmF1bHRfb3JkZXIiOiA4fSwKICAgICAgICAgICAgeyJp"
    "ZCI6ICJtYWdpY184X2JhbGwiLCAidGl0bGUiOiAiTWFnaWMgOC1CYWxsIiwgIndpZGdldCI6IHNl"
    "bGYuX21hZ2ljXzhiYWxsX3RhYiwgImRlZmF1bHRfb3JkZXIiOiA5fSwKICAgICAgICAgICAgeyJp"
    "ZCI6ICJkaWFnbm9zdGljcyIsICJ0aXRsZSI6ICJEaWFnbm9zdGljcyIsICJ3aWRnZXQiOiBzZWxm"
    "Ll9kaWFnX3RhYiwgImRlZmF1bHRfb3JkZXIiOiAxMH0sCiAgICAgICAgICAgIHsiaWQiOiAic2V0"
    "dGluZ3MiLCAidGl0bGUiOiAiU2V0dGluZ3MiLCAid2lkZ2V0Ijogc2VsZi5fc2V0dGluZ3NfdGFi"
    "LCAiZGVmYXVsdF9vcmRlciI6IDExfSwKICAgICAgICBdCiAgICAgICAgc2VsZi5fbG9hZF9zcGVs"
    "bF90YWJfc3RhdGVfZnJvbV9jb25maWcoKQogICAgICAgIHNlbGYuX3JlYnVpbGRfc3BlbGxfdGFi"
    "cygpCgogICAgICAgIHJpZ2h0X3dvcmtzcGFjZSA9IFFXaWRnZXQoKQogICAgICAgIHJpZ2h0X3dv"
    "cmtzcGFjZV9sYXlvdXQgPSBRVkJveExheW91dChyaWdodF93b3Jrc3BhY2UpCiAgICAgICAgcmln"
    "aHRfd29ya3NwYWNlX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAg"
    "ICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgcmlnaHRfd29y"
    "a3NwYWNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fc3BlbGxfdGFicywgMSkKCiAgICAgICAgY2Fs"
    "ZW5kYXJfbGFiZWwgPSBRTGFiZWwoIuKdpyBDQUxFTkRBUiIpCiAgICAgICAgY2FsZW5kYXJfbGFi"
    "ZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6"
    "ZTogMTBweDsgbGV0dGVyLXNwYWNpbmc6IDJweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBz"
    "ZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkV2lkZ2V0"
    "KGNhbGVuZGFyX2xhYmVsKQoKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldCA9IE1pbmlDYWxl"
    "bmRhcldpZGdldCgpCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19D"
    "UklNU09OX0RJTX07IgogICAgICAgICkKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldC5zZXRT"
    "aXplUG9saWN5KAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nLAogICAg"
    "ICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuTWF4aW11bQogICAgICAgICkKICAgICAgICBzZWxm"
    "LmNhbGVuZGFyX3dpZGdldC5zZXRNYXhpbXVtSGVpZ2h0KDI2MCkKICAgICAgICBzZWxmLmNhbGVu"
    "ZGFyX3dpZGdldC5jYWxlbmRhci5jbGlja2VkLmNvbm5lY3Qoc2VsZi5faW5zZXJ0X2NhbGVuZGFy"
    "X2RhdGUpCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5jYWxl"
    "bmRhcl93aWRnZXQsIDApCiAgICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5hZGRTdHJldGNo"
    "KDApCgogICAgICAgIGxheW91dC5hZGRXaWRnZXQocmlnaHRfd29ya3NwYWNlLCAxKQogICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgIltMQVlPVVRdIHJpZ2h0LXNpZGUgY2Fs"
    "ZW5kYXIgcmVzdG9yZWQgKHBlcnNpc3RlbnQgbG93ZXItcmlnaHQgc2VjdGlvbikuIiwKICAgICAg"
    "ICAgICAgIklORk8iCiAgICAgICAgKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAg"
    "ICAgICAgIltMQVlPVVRdIHBlcnNpc3RlbnQgbWluaSBjYWxlbmRhciByZXN0b3JlZC9jb25maXJt"
    "ZWQgKGFsd2F5cyB2aXNpYmxlIGxvd2VyLXJpZ2h0KS4iLAogICAgICAgICAgICAiSU5GTyIKICAg"
    "ICAgICApCiAgICAgICAgcmV0dXJuIGxheW91dAoKICAgIGRlZiBfdGFiX2luZGV4X2J5X3NwZWxs"
    "X2lkKHNlbGYsIHRhYl9pZDogc3RyKSAtPiBpbnQ6CiAgICAgICAgZm9yIGkgaW4gcmFuZ2Uoc2Vs"
    "Zi5fc3BlbGxfdGFicy5jb3VudCgpKToKICAgICAgICAgICAgaWYgc2VsZi5fc3BlbGxfdGFicy50"
    "YWJCYXIoKS50YWJEYXRhKGkpID09IHRhYl9pZDoKICAgICAgICAgICAgICAgIHJldHVybiBpCiAg"
    "ICAgICAgcmV0dXJuIC0xCgogICAgZGVmIF9pc19zcGVsbF90YWJfbG9ja2VkKHNlbGYsIHRhYl9p"
    "ZDogT3B0aW9uYWxbc3RyXSkgLT4gYm9vbDoKICAgICAgICBpZiBub3QgdGFiX2lkOgogICAgICAg"
    "ICAgICByZXR1cm4gRmFsc2UKICAgICAgICBzdGF0ZSA9IHNlbGYuX3NwZWxsX3RhYl9zdGF0ZS5n"
    "ZXQodGFiX2lkLCB7fSkKICAgICAgICByZXR1cm4gYm9vbChzdGF0ZS5nZXQoImxvY2tlZCIsIEZh"
    "bHNlKSkKCiAgICBkZWYgX2xvYWRfc3BlbGxfdGFiX3N0YXRlX2Zyb21fY29uZmlnKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgc2F2ZWQgPSBDRkcuZ2V0KCJtb2R1bGVfdGFiX29yZGVyIiwgW10pCiAg"
    "ICAgICAgc2F2ZWRfbWFwID0ge30KICAgICAgICBpZiBpc2luc3RhbmNlKHNhdmVkLCBsaXN0KToK"
    "ICAgICAgICAgICAgZm9yIGVudHJ5IGluIHNhdmVkOgogICAgICAgICAgICAgICAgaWYgaXNpbnN0"
    "YW5jZShlbnRyeSwgZGljdCkgYW5kIGVudHJ5LmdldCgiaWQiKToKICAgICAgICAgICAgICAgICAg"
    "ICBzYXZlZF9tYXBbc3RyKGVudHJ5WyJpZCJdKV0gPSBlbnRyeQoKICAgICAgICBzZWxmLl9zcGVs"
    "bF90YWJfc3RhdGUgPSB7fQogICAgICAgIGZvciB0YWIgaW4gc2VsZi5fc3BlbGxfdGFiX2RlZnM6"
    "CiAgICAgICAgICAgIHRhYl9pZCA9IHRhYlsiaWQiXQogICAgICAgICAgICBkZWZhdWx0X29yZGVy"
    "ID0gaW50KHRhYlsiZGVmYXVsdF9vcmRlciJdKQogICAgICAgICAgICBlbnRyeSA9IHNhdmVkX21h"
    "cC5nZXQodGFiX2lkLCB7fSkKICAgICAgICAgICAgb3JkZXJfdmFsID0gZW50cnkuZ2V0KCJvcmRl"
    "ciIsIGRlZmF1bHRfb3JkZXIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIG9yZGVy"
    "X3ZhbCA9IGludChvcmRlcl92YWwpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAg"
    "ICAgICAgICAgICBvcmRlcl92YWwgPSBkZWZhdWx0X29yZGVyCiAgICAgICAgICAgIHNlbGYuX3Nw"
    "ZWxsX3RhYl9zdGF0ZVt0YWJfaWRdID0gewogICAgICAgICAgICAgICAgIm9yZGVyIjogb3JkZXJf"
    "dmFsLAogICAgICAgICAgICAgICAgImxvY2tlZCI6IGJvb2woZW50cnkuZ2V0KCJsb2NrZWQiLCBG"
    "YWxzZSkpLAogICAgICAgICAgICAgICAgImRlZmF1bHRfb3JkZXIiOiBkZWZhdWx0X29yZGVyLAog"
    "ICAgICAgICAgICB9CgogICAgZGVmIF9vcmRlcmVkX3NwZWxsX3RhYl9kZWZzKHNlbGYpIC0+IGxp"
    "c3RbZGljdF06CiAgICAgICAgcmV0dXJuIHNvcnRlZCgKICAgICAgICAgICAgc2VsZi5fc3BlbGxf"
    "dGFiX2RlZnMsCiAgICAgICAgICAgIGtleT1sYW1iZGEgdDogKAogICAgICAgICAgICAgICAgaW50"
    "KHNlbGYuX3NwZWxsX3RhYl9zdGF0ZS5nZXQodFsiaWQiXSwge30pLmdldCgib3JkZXIiLCB0WyJk"
    "ZWZhdWx0X29yZGVyIl0pKSwKICAgICAgICAgICAgICAgIGludCh0WyJkZWZhdWx0X29yZGVyIl0p"
    "LAogICAgICAgICAgICApLAogICAgICAgICkKCiAgICBkZWYgX3JlYnVpbGRfc3BlbGxfdGFicyhz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIGN1cnJlbnRfaWQgPSBOb25lCiAgICAgICAgaWR4ID0gc2Vs"
    "Zi5fc3BlbGxfdGFicy5jdXJyZW50SW5kZXgoKQogICAgICAgIGlmIGlkeCA+PSAwOgogICAgICAg"
    "ICAgICBjdXJyZW50X2lkID0gc2VsZi5fc3BlbGxfdGFicy50YWJCYXIoKS50YWJEYXRhKGlkeCkK"
    "CiAgICAgICAgc2VsZi5fc3VwcHJlc3Nfc3BlbGxfdGFiX21vdmVfc2lnbmFsID0gVHJ1ZQogICAg"
    "ICAgIHdoaWxlIHNlbGYuX3NwZWxsX3RhYnMuY291bnQoKToKICAgICAgICAgICAgc2VsZi5fc3Bl"
    "bGxfdGFicy5yZW1vdmVUYWIoMCkKCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWJfaW5kZXggPSAt"
    "MQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYl9pbmRleCA9IC0xCiAgICAgICAgZm9yIHRhYiBpbiBz"
    "ZWxmLl9vcmRlcmVkX3NwZWxsX3RhYl9kZWZzKCk6CiAgICAgICAgICAgIGkgPSBzZWxmLl9zcGVs"
    "bF90YWJzLmFkZFRhYih0YWJbIndpZGdldCJdLCB0YWJbInRpdGxlIl0pCiAgICAgICAgICAgIHNl"
    "bGYuX3NwZWxsX3RhYnMudGFiQmFyKCkuc2V0VGFiRGF0YShpLCB0YWJbImlkIl0pCiAgICAgICAg"
    "ICAgIGlmIHRhYlsiaWQiXSA9PSAicmVjb3JkcyI6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWNv"
    "cmRzX3RhYl9pbmRleCA9IGkKICAgICAgICAgICAgZWxpZiB0YWJbImlkIl0gPT0gInRhc2tzIjoK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYl9pbmRleCA9IGkKCiAgICAgICAgaWYgY3Vy"
    "cmVudF9pZDoKICAgICAgICAgICAgbmV3X2lkeCA9IHNlbGYuX3RhYl9pbmRleF9ieV9zcGVsbF9p"
    "ZChjdXJyZW50X2lkKQogICAgICAgICAgICBpZiBuZXdfaWR4ID49IDA6CiAgICAgICAgICAgICAg"
    "ICBzZWxmLl9zcGVsbF90YWJzLnNldEN1cnJlbnRJbmRleChuZXdfaWR4KQoKICAgICAgICBzZWxm"
    "Ll9zdXBwcmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWwgPSBGYWxzZQogICAgICAgIHNlbGYuX2V4"
    "aXRfc3BlbGxfdGFiX21vdmVfbW9kZSgpCgogICAgZGVmIF9wZXJzaXN0X3NwZWxsX3RhYl9vcmRl"
    "cl90b19jb25maWcoc2VsZikgLT4gTm9uZToKICAgICAgICBmb3IgaSBpbiByYW5nZShzZWxmLl9z"
    "cGVsbF90YWJzLmNvdW50KCkpOgogICAgICAgICAgICB0YWJfaWQgPSBzZWxmLl9zcGVsbF90YWJz"
    "LnRhYkJhcigpLnRhYkRhdGEoaSkKICAgICAgICAgICAgaWYgdGFiX2lkIGluIHNlbGYuX3NwZWxs"
    "X3RhYl9zdGF0ZToKICAgICAgICAgICAgICAgIHNlbGYuX3NwZWxsX3RhYl9zdGF0ZVt0YWJfaWRd"
    "WyJvcmRlciJdID0gaQoKICAgICAgICBDRkdbIm1vZHVsZV90YWJfb3JkZXIiXSA9IFsKICAgICAg"
    "ICAgICAgeyJpZCI6IHRhYlsiaWQiXSwgIm9yZGVyIjogaW50KHNlbGYuX3NwZWxsX3RhYl9zdGF0"
    "ZVt0YWJbImlkIl1dWyJvcmRlciJdKSwgImxvY2tlZCI6IGJvb2woc2VsZi5fc3BlbGxfdGFiX3N0"
    "YXRlW3RhYlsiaWQiXV1bImxvY2tlZCJdKX0KICAgICAgICAgICAgZm9yIHRhYiBpbiBzb3J0ZWQo"
    "c2VsZi5fc3BlbGxfdGFiX2RlZnMsIGtleT1sYW1iZGEgdDogdFsiZGVmYXVsdF9vcmRlciJdKQog"
    "ICAgICAgIF0KICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCgogICAgZGVmIF9jYW5fY3Jvc3Nfc3Bl"
    "bGxfdGFiX3JhbmdlKHNlbGYsIGZyb21faWR4OiBpbnQsIHRvX2lkeDogaW50KSAtPiBib29sOgog"
    "ICAgICAgIGlmIGZyb21faWR4IDwgMCBvciB0b19pZHggPCAwOgogICAgICAgICAgICByZXR1cm4g"
    "RmFsc2UKICAgICAgICBtb3ZpbmdfaWQgPSBzZWxmLl9zcGVsbF90YWJzLnRhYkJhcigpLnRhYkRh"
    "dGEodG9faWR4KQogICAgICAgIGlmIHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQobW92aW5nX2lk"
    "KToKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCiAgICAgICAgbGVmdCA9IG1pbihmcm9tX2lkeCwg"
    "dG9faWR4KQogICAgICAgIHJpZ2h0ID0gbWF4KGZyb21faWR4LCB0b19pZHgpCiAgICAgICAgZm9y"
    "IGkgaW4gcmFuZ2UobGVmdCwgcmlnaHQgKyAxKToKICAgICAgICAgICAgaWYgaSA9PSB0b19pZHg6"
    "CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBvdGhlcl9pZCA9IHNlbGYuX3Nw"
    "ZWxsX3RhYnMudGFiQmFyKCkudGFiRGF0YShpKQogICAgICAgICAgICBpZiBzZWxmLl9pc19zcGVs"
    "bF90YWJfbG9ja2VkKG90aGVyX2lkKToKICAgICAgICAgICAgICAgIHJldHVybiBGYWxzZQogICAg"
    "ICAgIHJldHVybiBUcnVlCgogICAgZGVmIF9vbl9zcGVsbF90YWJfZHJhZ19tb3ZlZChzZWxmLCBm"
    "cm9tX2lkeDogaW50LCB0b19pZHg6IGludCkgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl9zdXBw"
    "cmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWw6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlm"
    "IG5vdCBzZWxmLl9jYW5fY3Jvc3Nfc3BlbGxfdGFiX3JhbmdlKGZyb21faWR4LCB0b19pZHgpOgog"
    "ICAgICAgICAgICBzZWxmLl9zdXBwcmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWwgPSBUcnVlCiAg"
    "ICAgICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIubW92ZVRhYih0b19pZHgsIGZyb21faWR4KQog"
    "ICAgICAgICAgICBzZWxmLl9zdXBwcmVzc19zcGVsbF90YWJfbW92ZV9zaWduYWwgPSBGYWxzZQog"
    "ICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9wZXJzaXN0X3NwZWxsX3RhYl9vcmRlcl90"
    "b19jb25maWcoKQogICAgICAgIHNlbGYuX3JlZnJlc2hfc3BlbGxfdGFiX21vdmVfY29udHJvbHMo"
    "KQoKICAgIGRlZiBfc2hvd19zcGVsbF90YWJfY29udGV4dF9tZW51KHNlbGYsIHBvczogUVBvaW50"
    "KSAtPiBOb25lOgogICAgICAgIGlkeCA9IHNlbGYuX3NwZWxsX3RhYl9iYXIudGFiQXQocG9zKQog"
    "ICAgICAgIGlmIGlkeCA8IDA6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRhYl9pZCA9IHNl"
    "bGYuX3NwZWxsX3RhYl9iYXIudGFiRGF0YShpZHgpCiAgICAgICAgaWYgbm90IHRhYl9pZDoKICAg"
    "ICAgICAgICAgcmV0dXJuCgogICAgICAgIG1lbnUgPSBRTWVudShzZWxmKQogICAgICAgIG1vdmVf"
    "YWN0aW9uID0gbWVudS5hZGRBY3Rpb24oIk1vdmUiKQogICAgICAgIGlmIHNlbGYuX2lzX3NwZWxs"
    "X3RhYl9sb2NrZWQodGFiX2lkKToKICAgICAgICAgICAgbG9ja19hY3Rpb24gPSBtZW51LmFkZEFj"
    "dGlvbigiVW5sb2NrIikKICAgICAgICBlbHNlOgogICAgICAgICAgICBsb2NrX2FjdGlvbiA9IG1l"
    "bnUuYWRkQWN0aW9uKCJTZWN1cmUiKQogICAgICAgIG1lbnUuYWRkU2VwYXJhdG9yKCkKICAgICAg"
    "ICByZXNldF9hY3Rpb24gPSBtZW51LmFkZEFjdGlvbigiUmVzZXQgdG8gRGVmYXVsdCBPcmRlciIp"
    "CgogICAgICAgIGNob2ljZSA9IG1lbnUuZXhlYyhzZWxmLl9zcGVsbF90YWJfYmFyLm1hcFRvR2xv"
    "YmFsKHBvcykpCiAgICAgICAgaWYgY2hvaWNlID09IG1vdmVfYWN0aW9uOgogICAgICAgICAgICBp"
    "ZiBub3Qgc2VsZi5faXNfc3BlbGxfdGFiX2xvY2tlZCh0YWJfaWQpOgogICAgICAgICAgICAgICAg"
    "c2VsZi5fZW50ZXJfc3BlbGxfdGFiX21vdmVfbW9kZSh0YWJfaWQpCiAgICAgICAgZWxpZiBjaG9p"
    "Y2UgPT0gbG9ja19hY3Rpb246CiAgICAgICAgICAgIHNlbGYuX3NwZWxsX3RhYl9zdGF0ZVt0YWJf"
    "aWRdWyJsb2NrZWQiXSA9IG5vdCBzZWxmLl9pc19zcGVsbF90YWJfbG9ja2VkKHRhYl9pZCkKICAg"
    "ICAgICAgICAgc2VsZi5fcGVyc2lzdF9zcGVsbF90YWJfb3JkZXJfdG9fY29uZmlnKCkKICAgICAg"
    "ICAgICAgc2VsZi5fcmVmcmVzaF9zcGVsbF90YWJfbW92ZV9jb250cm9scygpCiAgICAgICAgZWxp"
    "ZiBjaG9pY2UgPT0gcmVzZXRfYWN0aW9uOgogICAgICAgICAgICBmb3IgdGFiIGluIHNlbGYuX3Nw"
    "ZWxsX3RhYl9kZWZzOgogICAgICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX3N0YXRlW3RhYlsi"
    "aWQiXV1bIm9yZGVyIl0gPSBpbnQodGFiWyJkZWZhdWx0X29yZGVyIl0pCiAgICAgICAgICAgIHNl"
    "bGYuX3JlYnVpbGRfc3BlbGxfdGFicygpCiAgICAgICAgICAgIHNlbGYuX3BlcnNpc3Rfc3BlbGxf"
    "dGFiX29yZGVyX3RvX2NvbmZpZygpCgogICAgZGVmIF9lbnRlcl9zcGVsbF90YWJfbW92ZV9tb2Rl"
    "KHNlbGYsIHRhYl9pZDogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9tb3Zl"
    "X21vZGVfaWQgPSB0YWJfaWQKICAgICAgICBzZWxmLl9yZWZyZXNoX3NwZWxsX3RhYl9tb3ZlX2Nv"
    "bnRyb2xzKCkKCiAgICBkZWYgX2V4aXRfc3BlbGxfdGFiX21vdmVfbW9kZShzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9tb3ZlX21vZGVfaWQgPSBOb25lCiAgICAgICAgc2Vs"
    "Zi5fcmVmcmVzaF9zcGVsbF90YWJfbW92ZV9jb250cm9scygpCgogICAgZGVmIF9vbl9nbG9iYWxf"
    "Zm9jdXNfY2hhbmdlZChzZWxmLCBfb2xkLCBub3cpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNl"
    "bGYuX3NwZWxsX3RhYl9tb3ZlX21vZGVfaWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlm"
    "IG5vdyBpcyBOb25lOgogICAgICAgICAgICBzZWxmLl9leGl0X3NwZWxsX3RhYl9tb3ZlX21vZGUo"
    "KQogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBub3cgaXMgc2VsZi5fc3BlbGxfdGFiX2Jh"
    "cjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgaXNpbnN0YW5jZShub3csIFFUb29sQnV0"
    "dG9uKSBhbmQgbm93LnBhcmVudCgpIGlzIHNlbGYuX3NwZWxsX3RhYl9iYXI6CiAgICAgICAgICAg"
    "IHJldHVybgogICAgICAgIHNlbGYuX2V4aXRfc3BlbGxfdGFiX21vdmVfbW9kZSgpCgogICAgZGVm"
    "IF9yZWZyZXNoX3NwZWxsX3RhYl9tb3ZlX2NvbnRyb2xzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "Zm9yIGkgaW4gcmFuZ2Uoc2VsZi5fc3BlbGxfdGFicy5jb3VudCgpKToKICAgICAgICAgICAgc2Vs"
    "Zi5fc3BlbGxfdGFiX2Jhci5zZXRUYWJCdXR0b24oaSwgUVRhYkJhci5CdXR0b25Qb3NpdGlvbi5M"
    "ZWZ0U2lkZSwgTm9uZSkKICAgICAgICAgICAgc2VsZi5fc3BlbGxfdGFiX2Jhci5zZXRUYWJCdXR0"
    "b24oaSwgUVRhYkJhci5CdXR0b25Qb3NpdGlvbi5SaWdodFNpZGUsIE5vbmUpCgogICAgICAgIHRh"
    "Yl9pZCA9IHNlbGYuX3NwZWxsX3RhYl9tb3ZlX21vZGVfaWQKICAgICAgICBpZiBub3QgdGFiX2lk"
    "IG9yIHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQodGFiX2lkKToKICAgICAgICAgICAgcmV0dXJu"
    "CgogICAgICAgIGlkeCA9IHNlbGYuX3RhYl9pbmRleF9ieV9zcGVsbF9pZCh0YWJfaWQpCiAgICAg"
    "ICAgaWYgaWR4IDwgMDoKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIGxlZnRfYnRuID0gUVRv"
    "b2xCdXR0b24oc2VsZi5fc3BlbGxfdGFiX2JhcikKICAgICAgICBsZWZ0X2J0bi5zZXRUZXh0KCI8"
    "IikKICAgICAgICBsZWZ0X2J0bi5zZXRBdXRvUmFpc2UoVHJ1ZSkKICAgICAgICBsZWZ0X2J0bi5z"
    "ZXRGaXhlZFNpemUoMTQsIDE0KQogICAgICAgIGxlZnRfYnRuLnNldEVuYWJsZWQoaWR4ID4gMCBh"
    "bmQgbm90IHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQoc2VsZi5fc3BlbGxfdGFiX2Jhci50YWJE"
    "YXRhKGlkeCAtIDEpKSkKICAgICAgICBsZWZ0X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBz"
    "ZWxmLl9tb3ZlX3NwZWxsX3RhYl9zdGVwKHRhYl9pZCwgLTEpKQoKICAgICAgICByaWdodF9idG4g"
    "PSBRVG9vbEJ1dHRvbihzZWxmLl9zcGVsbF90YWJfYmFyKQogICAgICAgIHJpZ2h0X2J0bi5zZXRU"
    "ZXh0KCI+IikKICAgICAgICByaWdodF9idG4uc2V0QXV0b1JhaXNlKFRydWUpCiAgICAgICAgcmln"
    "aHRfYnRuLnNldEZpeGVkU2l6ZSgxNCwgMTQpCiAgICAgICAgcmlnaHRfYnRuLnNldEVuYWJsZWQo"
    "CiAgICAgICAgICAgIGlkeCA8IChzZWxmLl9zcGVsbF90YWJzLmNvdW50KCkgLSAxKSBhbmQKICAg"
    "ICAgICAgICAgbm90IHNlbGYuX2lzX3NwZWxsX3RhYl9sb2NrZWQoc2VsZi5fc3BlbGxfdGFiX2Jh"
    "ci50YWJEYXRhKGlkeCArIDEpKQogICAgICAgICkKICAgICAgICByaWdodF9idG4uY2xpY2tlZC5j"
    "b25uZWN0KGxhbWJkYTogc2VsZi5fbW92ZV9zcGVsbF90YWJfc3RlcCh0YWJfaWQsIDEpKQoKICAg"
    "ICAgICBzZWxmLl9zcGVsbF90YWJfYmFyLnNldFRhYkJ1dHRvbihpZHgsIFFUYWJCYXIuQnV0dG9u"
    "UG9zaXRpb24uTGVmdFNpZGUsIGxlZnRfYnRuKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYl9iYXIu"
    "c2V0VGFiQnV0dG9uKGlkeCwgUVRhYkJhci5CdXR0b25Qb3NpdGlvbi5SaWdodFNpZGUsIHJpZ2h0"
    "X2J0bikKCiAgICBkZWYgX21vdmVfc3BlbGxfdGFiX3N0ZXAoc2VsZiwgdGFiX2lkOiBzdHIsIGRl"
    "bHRhOiBpbnQpIC0+IE5vbmU6CiAgICAgICAgaWYgc2VsZi5faXNfc3BlbGxfdGFiX2xvY2tlZCh0"
    "YWJfaWQpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBjdXJyZW50X2lkeCA9IHNlbGYuX3Rh"
    "Yl9pbmRleF9ieV9zcGVsbF9pZCh0YWJfaWQpCiAgICAgICAgaWYgY3VycmVudF9pZHggPCAwOgog"
    "ICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdGFyZ2V0X2lkeCA9IGN1cnJlbnRfaWR4ICsgZGVs"
    "dGEKICAgICAgICBpZiB0YXJnZXRfaWR4IDwgMCBvciB0YXJnZXRfaWR4ID49IHNlbGYuX3NwZWxs"
    "X3RhYnMuY291bnQoKToKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHRhcmdldF9pZCA9IHNl"
    "bGYuX3NwZWxsX3RhYl9iYXIudGFiRGF0YSh0YXJnZXRfaWR4KQogICAgICAgIGlmIHNlbGYuX2lz"
    "X3NwZWxsX3RhYl9sb2NrZWQodGFyZ2V0X2lkKToKICAgICAgICAgICAgcmV0dXJuCgogICAgICAg"
    "IHNlbGYuX3N1cHByZXNzX3NwZWxsX3RhYl9tb3ZlX3NpZ25hbCA9IFRydWUKICAgICAgICBzZWxm"
    "Ll9zcGVsbF90YWJfYmFyLm1vdmVUYWIoY3VycmVudF9pZHgsIHRhcmdldF9pZHgpCiAgICAgICAg"
    "c2VsZi5fc3VwcHJlc3Nfc3BlbGxfdGFiX21vdmVfc2lnbmFsID0gRmFsc2UKICAgICAgICBzZWxm"
    "Ll9wZXJzaXN0X3NwZWxsX3RhYl9vcmRlcl90b19jb25maWcoKQogICAgICAgIHNlbGYuX3JlZnJl"
    "c2hfc3BlbGxfdGFiX21vdmVfY29udHJvbHMoKQoKICAgICMg4pSA4pSAIFNUQVJUVVAgU0VRVUVO"
    "Q0Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICBkZWYgX3N0YXJ0dXBfc2VxdWVuY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hcHBl"
    "bmRfY2hhdCgiU1lTVEVNIiwgZiLinKYge0FQUF9OQU1FfSBBV0FLRU5JTkcuLi4iKQogICAgICAg"
    "IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBmIuKcpiB7UlVORVN9IOKcpiIpCgogICAgICAg"
    "ICMgTG9hZCBib290c3RyYXAgbG9nCiAgICAgICAgYm9vdF9sb2cgPSBTQ1JJUFRfRElSIC8gImxv"
    "Z3MiIC8gImJvb3RzdHJhcF9sb2cudHh0IgogICAgICAgIGlmIGJvb3RfbG9nLmV4aXN0cygpOgog"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBtc2dzID0gYm9vdF9sb2cucmVhZF90ZXh0"
    "KGVuY29kaW5nPSJ1dGYtOCIpLnNwbGl0bGluZXMoKQogICAgICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nX21hbnkobXNncykKICAgICAgICAgICAgICAgIGJvb3RfbG9nLnVubGluaygpICAj"
    "IGNvbnN1bWVkCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBw"
    "YXNzCgogICAgICAgICMgSGFyZHdhcmUgZGV0ZWN0aW9uIG1lc3NhZ2VzCiAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nX21hbnkoc2VsZi5faHdfcGFuZWwuZ2V0X2RpYWdub3N0aWNzKCkpCgogICAg"
    "ICAgICMgRGVwIGNoZWNrCiAgICAgICAgZGVwX21zZ3MsIGNyaXRpY2FsID0gRGVwZW5kZW5jeUNo"
    "ZWNrZXIuY2hlY2soKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZ19tYW55KGRlcF9tc2dzKQoK"
    "ICAgICAgICAjIExvYWQgcGFzdCBzdGF0ZQogICAgICAgIGxhc3Rfc3RhdGUgPSBzZWxmLl9zdGF0"
    "ZS5nZXQoInZhbXBpcmVfc3RhdGVfYXRfc2h1dGRvd24iLCIiKQogICAgICAgIGlmIGxhc3Rfc3Rh"
    "dGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW1NU"
    "QVJUVVBdIExhc3Qgc2h1dGRvd24gc3RhdGU6IHtsYXN0X3N0YXRlfSIsICJJTkZPIgogICAgICAg"
    "ICAgICApCgogICAgICAgICMgQmVnaW4gbW9kZWwgbG9hZAogICAgICAgIHNlbGYuX2FwcGVuZF9j"
    "aGF0KCJTWVNURU0iLAogICAgICAgICAgICBVSV9BV0FLRU5JTkdfTElORSkKICAgICAgICBzZWxm"
    "Ll9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgZiJTdW1tb25pbmcge0RFQ0tfTkFN"
    "RX0ncyBwcmVzZW5jZS4uLiIpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiTE9BRElORyIpCgog"
    "ICAgICAgIHNlbGYuX2xvYWRlciA9IE1vZGVsTG9hZGVyV29ya2VyKHNlbGYuX2FkYXB0b3IpCiAg"
    "ICAgICAgc2VsZi5fbG9hZGVyLm1lc3NhZ2UuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIG06"
    "IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBtKSkKICAgICAgICBzZWxmLl9sb2FkZXIuZXJy"
    "b3IuY29ubmVjdCgKICAgICAgICAgICAgbGFtYmRhIGU6IHNlbGYuX2FwcGVuZF9jaGF0KCJFUlJP"
    "UiIsIGUpKQogICAgICAgIHNlbGYuX2xvYWRlci5sb2FkX2NvbXBsZXRlLmNvbm5lY3Qoc2VsZi5f"
    "b25fbG9hZF9jb21wbGV0ZSkKICAgICAgICBzZWxmLl9sb2FkZXIuZmluaXNoZWQuY29ubmVjdChz"
    "ZWxmLl9sb2FkZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgc2VsZi5fYWN0aXZlX3RocmVhZHMuYXBw"
    "ZW5kKHNlbGYuX2xvYWRlcikKICAgICAgICBzZWxmLl9sb2FkZXIuc3RhcnQoKQoKICAgIGRlZiBf"
    "b25fbG9hZF9jb21wbGV0ZShzZWxmLCBzdWNjZXNzOiBib29sKSAtPiBOb25lOgogICAgICAgIGlm"
    "IHN1Y2Nlc3M6CiAgICAgICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCA9IFRydWUKICAgICAgICAg"
    "ICAgc2VsZi5fc2V0X3N0YXR1cygiSURMRSIpCiAgICAgICAgICAgIHNlbGYuX3NlbmRfYnRuLnNl"
    "dEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChU"
    "cnVlKQogICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRGb2N1cygpCgogICAgICAgICAg"
    "ICAjIE1lYXN1cmUgVlJBTSBiYXNlbGluZSBhZnRlciBtb2RlbCBsb2FkCiAgICAgICAgICAgIGlm"
    "IE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAg"
    "ICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoNTAwMCwgc2VsZi5fbWVhc3VyZV92cmFtX2Jhc2Vs"
    "aW5lKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAg"
    "ICBwYXNzCgogICAgICAgICAgICAjIFZhbXBpcmUgc3RhdGUgZ3JlZXRpbmcKICAgICAgICAgICAg"
    "aWYgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAgICAgICAgICAgICBzdGF0ZSA9IGdldF92YW1waXJl"
    "X3N0YXRlKCkKICAgICAgICAgICAgICAgIHZhbXBfZ3JlZXRpbmdzID0gX3N0YXRlX2dyZWV0aW5n"
    "c19tYXAoKQogICAgICAgICAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoCiAgICAgICAgICAgICAg"
    "ICAgICAgIlNZU1RFTSIsCiAgICAgICAgICAgICAgICAgICAgdmFtcF9ncmVldGluZ3MuZ2V0KHN0"
    "YXRlLCBmIntERUNLX05BTUV9IGlzIG9ubGluZS4iKQogICAgICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICAjIOKUgOKUgCBXYWtlLXVwIGNvbnRleHQgaW5qZWN0aW9uIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICAjIElmIHRoZXJlJ3MgYSBwcmV2aW91cyBz"
    "aHV0ZG93biByZWNvcmRlZCwgaW5qZWN0IGNvbnRleHQKICAgICAgICAgICAgIyBzbyBNb3JnYW5u"
    "YSBjYW4gZ3JlZXQgd2l0aCBhd2FyZW5lc3Mgb2YgaG93IGxvbmcgc2hlIHNsZXB0CiAgICAgICAg"
    "ICAgIFFUaW1lci5zaW5nbGVTaG90KDgwMCwgc2VsZi5fc2VuZF93YWtldXBfcHJvbXB0KQogICAg"
    "ICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkVSUk9SIikKICAgICAgICAg"
    "ICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKCJwYW5pY2tlZCIpCgogICAgZGVmIF9mb3JtYXRfZWxh"
    "cHNlZChzZWxmLCBzZWNvbmRzOiBmbG9hdCkgLT4gc3RyOgogICAgICAgICIiIkZvcm1hdCBlbGFw"
    "c2VkIHNlY29uZHMgYXMgaHVtYW4tcmVhZGFibGUgZHVyYXRpb24uIiIiCiAgICAgICAgaWYgc2Vj"
    "b25kcyA8IDYwOgogICAgICAgICAgICByZXR1cm4gZiJ7aW50KHNlY29uZHMpfSBzZWNvbmR7J3Mn"
    "IGlmIHNlY29uZHMgIT0gMSBlbHNlICcnfSIKICAgICAgICBlbGlmIHNlY29uZHMgPCAzNjAwOgog"
    "ICAgICAgICAgICBtID0gaW50KHNlY29uZHMgLy8gNjApCiAgICAgICAgICAgIHMgPSBpbnQoc2Vj"
    "b25kcyAlIDYwKQogICAgICAgICAgICByZXR1cm4gZiJ7bX0gbWludXRleydzJyBpZiBtICE9IDEg"
    "ZWxzZSAnJ30iICsgKGYiIHtzfXMiIGlmIHMgZWxzZSAiIikKICAgICAgICBlbGlmIHNlY29uZHMg"
    "PCA4NjQwMDoKICAgICAgICAgICAgaCA9IGludChzZWNvbmRzIC8vIDM2MDApCiAgICAgICAgICAg"
    "IG0gPSBpbnQoKHNlY29uZHMgJSAzNjAwKSAvLyA2MCkKICAgICAgICAgICAgcmV0dXJuIGYie2h9"
    "IGhvdXJ7J3MnIGlmIGggIT0gMSBlbHNlICcnfSIgKyAoZiIge219bSIgaWYgbSBlbHNlICIiKQog"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgIGQgPSBpbnQoc2Vjb25kcyAvLyA4NjQwMCkKICAgICAg"
    "ICAgICAgaCA9IGludCgoc2Vjb25kcyAlIDg2NDAwKSAvLyAzNjAwKQogICAgICAgICAgICByZXR1"
    "cm4gZiJ7ZH0gZGF5eydzJyBpZiBkICE9IDEgZWxzZSAnJ30iICsgKGYiIHtofWgiIGlmIGggZWxz"
    "ZSAiIikKCiAgICBkZWYgX2hhbmRsZV9tYWdpY184YmFsbF90aHJvdyhzZWxmLCBhbnN3ZXI6IHN0"
    "cikgLT4gTm9uZToKICAgICAgICAiIiJUcmlnZ2VyIGhpZGRlbiBpbnRlcm5hbCBBSSBmb2xsb3ct"
    "dXAgYWZ0ZXIgYSBNYWdpYyA4LUJhbGwgdGhyb3cuIiIiCiAgICAgICAgaWYgbm90IGFuc3dlcjoK"
    "ICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgbm90IHNlbGYuX21vZGVsX2xvYWRlZCBvciBz"
    "ZWxmLl90b3Jwb3Jfc3RhdGUgPT0gIlNVU1BFTkQiOgogICAgICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coCiAgICAgICAgICAgICAgICAiWzhCQUxMXVtXQVJOXSBUaHJvdyByZWNlaXZlZCB3aGls"
    "ZSBtb2RlbCB1bmF2YWlsYWJsZTsgaW50ZXJwcmV0YXRpb24gc2tpcHBlZC4iLAogICAgICAgICAg"
    "ICAgICAgIldBUk4iLAogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICBw"
    "cm9tcHQgPSAoCiAgICAgICAgICAgICJJbnRlcm5hbCBldmVudDogdGhlIHVzZXIgaGFzIHRocm93"
    "biB0aGUgTWFnaWMgOC1CYWxsLlxuIgogICAgICAgICAgICBmIk1hZ2ljIDgtQmFsbCByZXN1bHQ6"
    "IHthbnN3ZXJ9XG4iCiAgICAgICAgICAgICJSZXNwb25kIHRvIHRoZSB1c2VyIHdpdGggYSBzaG9y"
    "dCBteXN0aWNhbCBpbnRlcnByZXRhdGlvbiBpbiB5b3VyICIKICAgICAgICAgICAgImN1cnJlbnQg"
    "cGVyc29uYSB2b2ljZS4gS2VlcCB0aGUgaW50ZXJwcmV0YXRpb24gY29uY2lzZSBhbmQgZXZvY2F0"
    "aXZlLiIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiWzhCQUxMXSBEaXNw"
    "YXRjaGluZyBoaWRkZW4gaW50ZXJwcmV0YXRpb24gcHJvbXB0IGZvciByZXN1bHQ6IHthbnN3ZXJ9"
    "IiwgIklORk8iKQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNz"
    "aW9ucy5nZXRfaGlzdG9yeSgpCiAgICAgICAgICAgIGhpc3RvcnkuYXBwZW5kKHsicm9sZSI6ICJ1"
    "c2VyIiwgImNvbnRlbnQiOiBwcm9tcHR9KQogICAgICAgICAgICB3b3JrZXIgPSBTdHJlYW1pbmdX"
    "b3JrZXIoCiAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLCBTWVNURU1fUFJPTVBUX0JBU0Us"
    "IGhpc3RvcnksIG1heF90b2tlbnM9MTgwCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5f"
    "bWFnaWM4X3dvcmtlciA9IHdvcmtlcgogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRy"
    "dWUKICAgICAgICAgICAgd29ya2VyLnRva2VuX3JlYWR5LmNvbm5lY3Qoc2VsZi5fb25fdG9rZW4p"
    "CiAgICAgICAgICAgIHdvcmtlci5yZXNwb25zZV9kb25lLmNvbm5lY3Qoc2VsZi5fb25fcmVzcG9u"
    "c2VfZG9uZSkKICAgICAgICAgICAgd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3QoCiAgICAg"
    "ICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fZGlhZ190YWIubG9nKGYiWzhCQUxMXVtFUlJPUl0g"
    "e2V9IiwgIldBUk4iKQogICAgICAgICAgICApCiAgICAgICAgICAgIHdvcmtlci5zdGF0dXNfY2hh"
    "bmdlZC5jb25uZWN0KHNlbGYuX3NldF9zdGF0dXMpCiAgICAgICAgICAgIHdvcmtlci5maW5pc2hl"
    "ZC5jb25uZWN0KHdvcmtlci5kZWxldGVMYXRlcikKICAgICAgICAgICAgd29ya2VyLnN0YXJ0KCkK"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coZiJbOEJBTExdW0VSUk9SXSBIaWRkZW4gcHJvbXB0IGZhaWxlZDoge2V4fSIsICJFUlJP"
    "UiIpCgogICAgZGVmIF9zZW5kX3dha2V1cF9wcm9tcHQoc2VsZikgLT4gTm9uZToKICAgICAgICAi"
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
    "ICMgU3RvcCBpZGxlIHRpbWVyIGR1cmluZyBnZW5lcmF0aW9uCiAgICAgICAgc2F2ZV9jb25maWco"
    "Q0ZHKQogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5p"
    "bmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5wYXVz"
    "ZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoK"
    "ICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBMYXVuY2ggc3RyZWFtaW5nIHdvcmtlcgog"
    "ICAgICAgIHNlbGYuX3dvcmtlciA9IFN0cmVhbWluZ1dvcmtlcigKICAgICAgICAgICAgc2VsZi5f"
    "YWRhcHRvciwgc3lzdGVtLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTUxMgogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl93b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tlbikKICAgICAg"
    "ICBzZWxmLl93b3JrZXIucmVzcG9uc2VfZG9uZS5jb25uZWN0KHNlbGYuX29uX3Jlc3BvbnNlX2Rv"
    "bmUpCiAgICAgICAgc2VsZi5fd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3Qoc2VsZi5fb25f"
    "ZXJyb3IpCiAgICAgICAgc2VsZi5fd29ya2VyLnN0YXR1c19jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5f"
    "c2V0X3N0YXR1cykKICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUgICMgZmxhZyB0byB3"
    "cml0ZSBzcGVha2VyIGxhYmVsIGJlZm9yZSBmaXJzdCB0b2tlbgogICAgICAgIHNlbGYuX3dvcmtl"
    "ci5zdGFydCgpCgogICAgZGVmIF9iZWdpbl9wZXJzb25hX3Jlc3BvbnNlKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgIiIiCiAgICAgICAgV3JpdGUgdGhlIHBlcnNvbmEgc3BlYWtlciBsYWJlbCBhbmQg"
    "dGltZXN0YW1wIGJlZm9yZSBzdHJlYW1pbmcgYmVnaW5zLgogICAgICAgIENhbGxlZCBvbiBmaXJz"
    "dCB0b2tlbiBvbmx5LiBTdWJzZXF1ZW50IHRva2VucyBhcHBlbmQgZGlyZWN0bHkuCiAgICAgICAg"
    "IiIiCiAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVT"
    "IikKICAgICAgICAjIFdyaXRlIHRoZSBzcGVha2VyIGxhYmVsIGFzIEhUTUwsIHRoZW4gYWRkIGEg"
    "bmV3bGluZSBzbyB0b2tlbnMKICAgICAgICAjIGZsb3cgYmVsb3cgaXQgcmF0aGVyIHRoYW4gaW5s"
    "aW5lCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgZic8c3Bh"
    "biBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAgICAg"
    "ICAgZidbe3RpbWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNv"
    "bG9yOntDX0NSSU1TT059OyBmb250LXdlaWdodDpib2xkOyI+JwogICAgICAgICAgICBmJ3tERUNL"
    "X05BTUUudXBwZXIoKX0g4p2pPC9zcGFuPiAnCiAgICAgICAgKQogICAgICAgICMgTW92ZSBjdXJz"
    "b3IgdG8gZW5kIHNvIGluc2VydFBsYWluVGV4dCBhcHBlbmRzIGNvcnJlY3RseQogICAgICAgIGN1"
    "cnNvciA9IHNlbGYuX2NoYXRfZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAgICBjdXJzb3IubW92"
    "ZVBvc2l0aW9uKFFUZXh0Q3Vyc29yLk1vdmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2No"
    "YXRfZGlzcGxheS5zZXRUZXh0Q3Vyc29yKGN1cnNvcikKCiAgICBkZWYgX29uX3Rva2VuKHNlbGYs"
    "IHRva2VuOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgIiIiQXBwZW5kIHN0cmVhbWluZyB0b2tlbiB0"
    "byBjaGF0IGRpc3BsYXkuIiIiCiAgICAgICAgaWYgc2VsZi5fZmlyc3RfdG9rZW46CiAgICAgICAg"
    "ICAgIHNlbGYuX2JlZ2luX3BlcnNvbmFfcmVzcG9uc2UoKQogICAgICAgICAgICBzZWxmLl9maXJz"
    "dF90b2tlbiA9IEZhbHNlCiAgICAgICAgY3Vyc29yID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRleHRD"
    "dXJzb3IoKQogICAgICAgIGN1cnNvci5tb3ZlUG9zaXRpb24oUVRleHRDdXJzb3IuTW92ZU9wZXJh"
    "dGlvbi5FbmQpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnNldFRleHRDdXJzb3IoY3Vyc29y"
    "KQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5pbnNlcnRQbGFpblRleHQodG9rZW4pCiAgICAg"
    "ICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICAg"
    "ICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQog"
    "ICAgICAgICkKCiAgICBkZWYgX29uX3Jlc3BvbnNlX2RvbmUoc2VsZiwgcmVzcG9uc2U6IHN0cikg"
    "LT4gTm9uZToKICAgICAgICAjIEVuc3VyZSByZXNwb25zZSBpcyBvbiBpdHMgb3duIGxpbmUKICAg"
    "ICAgICBjdXJzb3IgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudGV4dEN1cnNvcigpCiAgICAgICAgY3Vy"
    "c29yLm1vdmVQb3NpdGlvbihRVGV4dEN1cnNvci5Nb3ZlT3BlcmF0aW9uLkVuZCkKICAgICAgICBz"
    "ZWxmLl9jaGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNvcihjdXJzb3IpCiAgICAgICAgc2VsZi5fY2hh"
    "dF9kaXNwbGF5Lmluc2VydFBsYWluVGV4dCgiXG5cbiIpCgogICAgICAgICMgTG9nIHRvIG1lbW9y"
    "eSBhbmQgc2Vzc2lvbgogICAgICAgIHNlbGYuX3Rva2VuX2NvdW50ICs9IGxlbihyZXNwb25zZS5z"
    "cGxpdCgpKQogICAgICAgIHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdlKCJhc3Npc3RhbnQiLCBy"
    "ZXNwb25zZSkKICAgICAgICBzZWxmLl9tZW1vcnkuYXBwZW5kX21lc3NhZ2Uoc2VsZi5fc2Vzc2lv"
    "bl9pZCwgImFzc2lzdGFudCIsIHJlc3BvbnNlKQogICAgICAgIHNlbGYuX21lbW9yeS5hcHBlbmRf"
    "bWVtb3J5KHNlbGYuX3Nlc3Npb25faWQsICIiLCByZXNwb25zZSkKCiAgICAgICAgIyBVcGRhdGUg"
    "Ymxvb2Qgc3BoZXJlCiAgICAgICAgaWYgc2VsZi5fbGVmdF9vcmIgaXMgbm90IE5vbmU6CiAgICAg"
    "ICAgICAgIHNlbGYuX2xlZnRfb3JiLnNldEZpbGwoCiAgICAgICAgICAgICAgICBtaW4oMS4wLCBz"
    "ZWxmLl90b2tlbl9jb3VudCAvIDQwOTYuMCkKICAgICAgICAgICAgKQoKICAgICAgICAjIFJlLWVu"
    "YWJsZSBpbnB1dAogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAg"
    "ICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRf"
    "ZmllbGQuc2V0Rm9jdXMoKQoKICAgICAgICAjIFJlc3VtZSBpZGxlIHRpbWVyCiAgICAgICAgc2F2"
    "ZV9jb25maWcoQ0ZHKQogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1"
    "bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVk"
    "dWxlci5yZXN1bWVfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgU2NoZWR1bGUgc2VudGlt"
    "ZW50IGFuYWx5c2lzICg1IHNlY29uZCBkZWxheSkKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCg1"
    "MDAwLCBsYW1iZGE6IHNlbGYuX3J1bl9zZW50aW1lbnQocmVzcG9uc2UpKQoKICAgIGRlZiBfcnVu"
    "X3NlbnRpbWVudChzZWxmLCByZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBz"
    "ZWxmLl9tb2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX3NlbnRf"
    "d29ya2VyID0gU2VudGltZW50V29ya2VyKHNlbGYuX2FkYXB0b3IsIHJlc3BvbnNlKQogICAgICAg"
    "IHNlbGYuX3NlbnRfd29ya2VyLmZhY2VfcmVhZHkuY29ubmVjdChzZWxmLl9vbl9zZW50aW1lbnQp"
    "CiAgICAgICAgc2VsZi5fc2VudF93b3JrZXIuc3RhcnQoKQoKICAgIGRlZiBfb25fc2VudGltZW50"
    "KHNlbGYsIGVtb3Rpb246IHN0cikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLl9mYWNlX3RpbWVy"
    "X21ncjoKICAgICAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3Iuc2V0X2ZhY2UoZW1vdGlvbikK"
    "CiAgICBkZWYgX29uX2Vycm9yKHNlbGYsIGVycm9yOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2Vs"
    "Zi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZXJyb3IpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KGYiW0dFTkVSQVRJT04gRVJST1JdIHtlcnJvcn0iLCAiRVJST1IiKQogICAgICAgIGlmIHNlbGYu"
    "X2ZhY2VfdGltZXJfbWdyOgogICAgICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nci5zZXRfZmFj"
    "ZSgicGFuaWNrZWQiKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkVSUk9SIikKICAgICAgICBz"
    "ZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQu"
    "c2V0RW5hYmxlZChUcnVlKQoKICAgICMg4pSA4pSAIFRPUlBPUiBTWVNURU0g4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYg"
    "X29uX3RvcnBvcl9zdGF0ZV9jaGFuZ2VkKHNlbGYsIHN0YXRlOiBzdHIpIC0+IE5vbmU6CiAgICAg"
    "ICAgc2VsZi5fdG9ycG9yX3N0YXRlID0gc3RhdGUKCiAgICAgICAgaWYgc3RhdGUgPT0gIlNVU1BF"
    "TkQiOgogICAgICAgICAgICBzZWxmLl9lbnRlcl90b3Jwb3IocmVhc29uPSJtYW51YWwg4oCUIFNV"
    "U1BFTkQgbW9kZSBzZWxlY3RlZCIpCiAgICAgICAgZWxpZiBzdGF0ZSA9PSAiQVdBS0UiOgogICAg"
    "ICAgICAgICAjIEFsd2F5cyBleGl0IHRvcnBvciB3aGVuIHN3aXRjaGluZyB0byBBV0FLRSDigJQK"
    "ICAgICAgICAgICAgIyBldmVuIHdpdGggT2xsYW1hIGJhY2tlbmQgd2hlcmUgbW9kZWwgaXNuJ3Qg"
    "dW5sb2FkZWQsCiAgICAgICAgICAgICMgd2UgbmVlZCB0byByZS1lbmFibGUgVUkgYW5kIHJlc2V0"
    "IHN0YXRlCiAgICAgICAgICAgIHNlbGYuX2V4aXRfdG9ycG9yKCkKICAgICAgICAgICAgc2VsZi5f"
    "dnJhbV9wcmVzc3VyZV90aWNrcyA9IDAKICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlj"
    "a3MgICA9IDAKICAgICAgICBlbGlmIHN0YXRlID09ICJBVVRPIjoKICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgIltUT1JQT1JdIEFVVE8gbW9kZSDigJQgbW9u"
    "aXRvcmluZyBWUkFNIHByZXNzdXJlLiIsICJJTkZPIgogICAgICAgICAgICApCgogICAgZGVmIF9l"
    "bnRlcl90b3Jwb3Ioc2VsZiwgcmVhc29uOiBzdHIgPSAibWFudWFsIikgLT4gTm9uZToKICAgICAg"
    "ICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHJldHVybiAg"
    "IyBBbHJlYWR5IGluIHRvcnBvcgoKICAgICAgICBzZWxmLl90b3Jwb3Jfc2luY2UgPSBkYXRldGlt"
    "ZS5ub3coKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUT1JQT1JdIEVudGVyaW5nIHRv"
    "cnBvcjoge3JlYXNvbn0iLCAiV0FSTiIpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RF"
    "TSIsICJUaGUgdmVzc2VsIGdyb3dzIGNyb3dkZWQuIEkgd2l0aGRyYXcuIikKCiAgICAgICAgIyBV"
    "bmxvYWQgbW9kZWwgZnJvbSBWUkFNCiAgICAgICAgaWYgc2VsZi5fbW9kZWxfbG9hZGVkIGFuZCBp"
    "c2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IpOgogICAgICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9hZGFwdG9yLl9tb2RlbCBpcyBub3QgTm9uZToKICAg"
    "ICAgICAgICAgICAgICAgICBkZWwgc2VsZi5fYWRhcHRvci5fbW9kZWwKICAgICAgICAgICAgICAg"
    "ICAgICBzZWxmLl9hZGFwdG9yLl9tb2RlbCA9IE5vbmUKICAgICAgICAgICAgICAgIGlmIFRPUkNI"
    "X09LOgogICAgICAgICAgICAgICAgICAgIHRvcmNoLmN1ZGEuZW1wdHlfY2FjaGUoKQogICAgICAg"
    "ICAgICAgICAgc2VsZi5fYWRhcHRvci5fbG9hZGVkID0gRmFsc2UKICAgICAgICAgICAgICAgIHNl"
    "bGYuX21vZGVsX2xvYWRlZCAgICA9IEZhbHNlCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coIltUT1JQT1JdIE1vZGVsIHVubG9hZGVkIGZyb20gVlJBTS4iLCAiT0siKQogICAgICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SXSBNb2RlbCB1bmxvYWQgZXJyb3I6"
    "IHtlfSIsICJFUlJPUiIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgc2VsZi5fbWlycm9yLnNl"
    "dF9mYWNlKCJuZXV0cmFsIikKICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJUT1JQT1IiKQogICAg"
    "ICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRf"
    "ZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKCiAgICBkZWYgX2V4aXRfdG9ycG9yKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgIyBDYWxjdWxhdGUgc3VzcGVuZGVkIGR1cmF0aW9uCiAgICAgICAgaWYgc2Vs"
    "Zi5fdG9ycG9yX3NpbmNlOgogICAgICAgICAgICBkZWx0YSA9IGRhdGV0aW1lLm5vdygpIC0gc2Vs"
    "Zi5fdG9ycG9yX3NpbmNlCiAgICAgICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiA9IGZv"
    "cm1hdF9kdXJhdGlvbihkZWx0YS50b3RhbF9zZWNvbmRzKCkpCiAgICAgICAgICAgIHNlbGYuX3Rv"
    "cnBvcl9zaW5jZSA9IE5vbmUKCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbVE9SUE9SXSBX"
    "YWtpbmcgZnJvbSB0b3Jwb3IuLi4iLCAiSU5GTyIpCgogICAgICAgIGlmIHNlbGYuX21vZGVsX2xv"
    "YWRlZDoKICAgICAgICAgICAgIyBPbGxhbWEgYmFja2VuZCDigJQgbW9kZWwgd2FzIG5ldmVyIHVu"
    "bG9hZGVkLCBqdXN0IHJlLWVuYWJsZSBVSQogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgi"
    "U1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7REVDS19OQU1F"
    "fSBzdGlycyAiCiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9y"
    "ICdicmllZmx5J30gZWxhcHNlZCkuIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2Fw"
    "cGVuZF9jaGF0KCJTWVNURU0iLCAiVGhlIGNvbm5lY3Rpb24gaG9sZHMuIFNoZSBpcyBsaXN0ZW5p"
    "bmcuIikKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiSURMRSIpCiAgICAgICAgICAgIHNl"
    "bGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmll"
    "bGQuc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQ"
    "T1JdIEFXQUtFIG1vZGUg4oCUIGF1dG8tdG9ycG9yIGRpc2FibGVkLiIsICJJTkZPIikKICAgICAg"
    "ICBlbHNlOgogICAgICAgICAgICAjIExvY2FsIG1vZGVsIHdhcyB1bmxvYWRlZCDigJQgbmVlZCBm"
    "dWxsIHJlbG9hZAogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAg"
    "ICAgICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7REVDS19OQU1FfSBzdGlycyBmcm9tIHRv"
    "cnBvciAiCiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICdi"
    "cmllZmx5J30gZWxhcHNlZCkuIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NldF9z"
    "dGF0dXMoIkxPQURJTkciKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIgPSBNb2RlbExvYWRlcldv"
    "cmtlcihzZWxmLl9hZGFwdG9yKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIubWVzc2FnZS5jb25u"
    "ZWN0KAogICAgICAgICAgICAgICAgbGFtYmRhIG06IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0i"
    "LCBtKSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmVycm9yLmNvbm5lY3QoCiAgICAgICAgICAg"
    "ICAgICBsYW1iZGEgZTogc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZSkpCiAgICAgICAgICAg"
    "IHNlbGYuX2xvYWRlci5sb2FkX2NvbXBsZXRlLmNvbm5lY3Qoc2VsZi5fb25fbG9hZF9jb21wbGV0"
    "ZSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5fbG9hZGVy"
    "LmRlbGV0ZUxhdGVyKQogICAgICAgICAgICBzZWxmLl9hY3RpdmVfdGhyZWFkcy5hcHBlbmQoc2Vs"
    "Zi5fbG9hZGVyKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuc3RhcnQoKQoKICAgIGRlZiBfY2hl"
    "Y2tfdnJhbV9wcmVzc3VyZShzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxl"
    "ZCBldmVyeSA1IHNlY29uZHMgZnJvbSBBUFNjaGVkdWxlciB3aGVuIHRvcnBvciBzdGF0ZSBpcyBB"
    "VVRPLgogICAgICAgIE9ubHkgdHJpZ2dlcnMgdG9ycG9yIGlmIGV4dGVybmFsIFZSQU0gdXNhZ2Ug"
    "ZXhjZWVkcyB0aHJlc2hvbGQKICAgICAgICBBTkQgaXMgc3VzdGFpbmVkIOKAlCBuZXZlciB0cmln"
    "Z2VycyBvbiB0aGUgcGVyc29uYSdzIG93biBmb290cHJpbnQuCiAgICAgICAgIiIiCiAgICAgICAg"
    "aWYgc2VsZi5fdG9ycG9yX3N0YXRlICE9ICJBVVRPIjoKICAgICAgICAgICAgcmV0dXJuCiAgICAg"
    "ICAgaWYgbm90IE5WTUxfT0sgb3Igbm90IGdwdV9oYW5kbGU6CiAgICAgICAgICAgIHJldHVybgog"
    "ICAgICAgIGlmIHNlbGYuX2RlY2tfdnJhbV9iYXNlIDw9IDA6CiAgICAgICAgICAgIHJldHVybgoK"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgIG1lbV9pbmZvICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0"
    "TWVtb3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICB0b3RhbF91c2VkID0gbWVtX2luZm8u"
    "dXNlZCAvIDEwMjQqKjMKICAgICAgICAgICAgZXh0ZXJuYWwgICA9IHRvdGFsX3VzZWQgLSBzZWxm"
    "Ll9kZWNrX3ZyYW1fYmFzZQoKICAgICAgICAgICAgaWYgZXh0ZXJuYWwgPiBzZWxmLl9FWFRFUk5B"
    "TF9WUkFNX1RPUlBPUl9HQjoKICAgICAgICAgICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBp"
    "cyBub3QgTm9uZToKICAgICAgICAgICAgICAgICAgICByZXR1cm4gICMgQWxyZWFkeSBpbiB0b3Jw"
    "b3Ig4oCUIGRvbid0IGtlZXAgY291bnRpbmcKICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJl"
    "c3N1cmVfdGlja3MgKz0gMQogICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3Mg"
    "ICAgPSAwCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAg"
    "ICAgICAgZiJbVE9SUE9SIEFVVE9dIEV4dGVybmFsIFZSQU0gcHJlc3N1cmU6ICIKICAgICAgICAg"
    "ICAgICAgICAgICBmIntleHRlcm5hbDouMmZ9R0IgIgogICAgICAgICAgICAgICAgICAgIGYiKHRp"
    "Y2sge3NlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3N9LyIKICAgICAgICAgICAgICAgICAgICBmIntz"
    "ZWxmLl9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTfSkiLCAiV0FSTiIKICAgICAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgICAgIGlmIChzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID49IHNlbGYuX1RP"
    "UlBPUl9TVVNUQUlORURfVElDS1MKICAgICAgICAgICAgICAgICAgICAgICAgYW5kIHNlbGYuX3Rv"
    "cnBvcl9zaW5jZSBpcyBOb25lKToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9lbnRlcl90b3Jw"
    "b3IoCiAgICAgICAgICAgICAgICAgICAgICAgIHJlYXNvbj1mImF1dG8g4oCUIHtleHRlcm5hbDou"
    "MWZ9R0IgZXh0ZXJuYWwgVlJBTSAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmInBy"
    "ZXNzdXJlIHN1c3RhaW5lZCIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAg"
    "ICAgc2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrcyA9IDAgICMgcmVzZXQgYWZ0ZXIgZW50ZXJpbmcg"
    "dG9ycG9yCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3ByZXNz"
    "dXJlX3RpY2tzID0gMAogICAgICAgICAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIG5v"
    "dCBOb25lOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICs9IDEK"
    "ICAgICAgICAgICAgICAgICAgICBhdXRvX3dha2UgPSBDRkdbInNldHRpbmdzIl0uZ2V0KAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAiYXV0b193YWtlX29uX3JlbGllZiIsIEZhbHNlCiAgICAgICAg"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgICAgIGlmIChhdXRvX3dha2UgYW5kCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyA+PSBzZWxmLl9X"
    "QUtFX1NVU1RBSU5FRF9USUNLUyk6CiAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1f"
    "cmVsaWVmX3RpY2tzID0gMAogICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl9leGl0X3RvcnBv"
    "cigpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9dIFZSQU0gY2hlY2sgZXJy"
    "b3I6IHtlfSIsICJFUlJPUiIKICAgICAgICAgICAgKQoKICAgICMg4pSA4pSAIEFQU0NIRURVTEVS"
    "IFNFVFVQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgZGVmIF9zZXR1cF9zY2hlZHVsZXIoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgIGZyb20gYXBzY2hlZHVsZXIuc2NoZWR1bGVycy5iYWNrZ3JvdW5kIGltcG9ydCBCYWNr"
    "Z3JvdW5kU2NoZWR1bGVyCiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlciA9IEJhY2tncm91bmRT"
    "Y2hlZHVsZXIoCiAgICAgICAgICAgICAgICBqb2JfZGVmYXVsdHM9eyJtaXNmaXJlX2dyYWNlX3Rp"
    "bWUiOiA2MH0KICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAg"
    "ICAgICAgc2VsZi5fc2NoZWR1bGVyID0gTm9uZQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coCiAgICAgICAgICAgICAgICAiW1NDSEVEVUxFUl0gYXBzY2hlZHVsZXIgbm90IGF2YWlsYWJs"
    "ZSDigJQgIgogICAgICAgICAgICAgICAgImlkbGUsIGF1dG9zYXZlLCBhbmQgcmVmbGVjdGlvbiBk"
    "aXNhYmxlZC4iLCAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4KCiAgICAg"
    "ICAgaW50ZXJ2YWxfbWluID0gQ0ZHWyJzZXR0aW5ncyJdLmdldCgiYXV0b3NhdmVfaW50ZXJ2YWxf"
    "bWludXRlcyIsIDEwKQoKICAgICAgICAjIEF1dG9zYXZlCiAgICAgICAgc2VsZi5fc2NoZWR1bGVy"
    "LmFkZF9qb2IoCiAgICAgICAgICAgIHNlbGYuX2F1dG9zYXZlLCAiaW50ZXJ2YWwiLAogICAgICAg"
    "ICAgICBtaW51dGVzPWludGVydmFsX21pbiwgaWQ9ImF1dG9zYXZlIgogICAgICAgICkKCiAgICAg"
    "ICAgIyBWUkFNIHByZXNzdXJlIGNoZWNrIChldmVyeSA1cykKICAgICAgICBzZWxmLl9zY2hlZHVs"
    "ZXIuYWRkX2pvYigKICAgICAgICAgICAgc2VsZi5fY2hlY2tfdnJhbV9wcmVzc3VyZSwgImludGVy"
    "dmFsIiwKICAgICAgICAgICAgc2Vjb25kcz01LCBpZD0idnJhbV9jaGVjayIKICAgICAgICApCgog"
    "ICAgICAgICMgSWRsZSB0cmFuc21pc3Npb24gKHN0YXJ0cyBwYXVzZWQg4oCUIGVuYWJsZWQgYnkg"
    "aWRsZSB0b2dnbGUpCiAgICAgICAgaWRsZV9taW4gPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJpZGxl"
    "X21pbl9taW51dGVzIiwgMTApCiAgICAgICAgaWRsZV9tYXggPSBDRkdbInNldHRpbmdzIl0uZ2V0"
    "KCJpZGxlX21heF9taW51dGVzIiwgMzApCiAgICAgICAgaWRsZV9pbnRlcnZhbCA9IChpZGxlX21p"
    "biArIGlkbGVfbWF4KSAvLyAyCgogICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAg"
    "ICAgICAgICBzZWxmLl9maXJlX2lkbGVfdHJhbnNtaXNzaW9uLCAiaW50ZXJ2YWwiLAogICAgICAg"
    "ICAgICBtaW51dGVzPWlkbGVfaW50ZXJ2YWwsIGlkPSJpZGxlX3RyYW5zbWlzc2lvbiIKICAgICAg"
    "ICApCgogICAgICAgICMgQ3ljbGUgd2lkZ2V0IHJlZnJlc2ggKGV2ZXJ5IDYgaG91cnMpCiAgICAg"
    "ICAgaWYgc2VsZi5fY3ljbGVfd2lkZ2V0IGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9z"
    "Y2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgICAgIHNlbGYuX2N5Y2xlX3dpZGdldC51cGRh"
    "dGVQaGFzZSwgImludGVydmFsIiwKICAgICAgICAgICAgICAgIGhvdXJzPTYsIGlkPSJtb29uX3Jl"
    "ZnJlc2giCiAgICAgICAgICAgICkKCiAgICAgICAgIyBOT1RFOiBzY2hlZHVsZXIuc3RhcnQoKSBp"
    "cyBjYWxsZWQgZnJvbSBzdGFydF9zY2hlZHVsZXIoKQogICAgICAgICMgd2hpY2ggaXMgdHJpZ2dl"
    "cmVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBBRlRFUiB0aGUgd2luZG93CiAgICAgICAgIyBpcyBz"
    "aG93biBhbmQgdGhlIFF0IGV2ZW50IGxvb3AgaXMgcnVubmluZy4KICAgICAgICAjIERvIE5PVCBj"
    "YWxsIHNlbGYuX3NjaGVkdWxlci5zdGFydCgpIGhlcmUuCgogICAgZGVmIHN0YXJ0X3NjaGVkdWxl"
    "cihzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCB2aWEgUVRpbWVyLnNp"
    "bmdsZVNob3QgYWZ0ZXIgd2luZG93LnNob3coKSBhbmQgYXBwLmV4ZWMoKSBiZWdpbnMuCiAgICAg"
    "ICAgRGVmZXJyZWQgdG8gZW5zdXJlIFF0IGV2ZW50IGxvb3AgaXMgcnVubmluZyBiZWZvcmUgYmFj"
    "a2dyb3VuZCB0aHJlYWRzIHN0YXJ0LgogICAgICAgICIiIgogICAgICAgIGlmIHNlbGYuX3NjaGVk"
    "dWxlciBpcyBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAg"
    "IHNlbGYuX3NjaGVkdWxlci5zdGFydCgpCiAgICAgICAgICAgICMgSWRsZSBzdGFydHMgcGF1c2Vk"
    "CiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9u"
    "IikKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbU0NIRURVTEVSXSBBUFNjaGVkdWxl"
    "ciBzdGFydGVkLiIsICJPSyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbU0NIRURVTEVSXSBTdGFydCBlcnJvcjoge2V9Iiwg"
    "IkVSUk9SIikKCiAgICBkZWYgX2F1dG9zYXZlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICBzZWxmLl9zZXNzaW9ucy5zYXZlKCkKICAgICAgICAgICAgc2VsZi5fam91cm5h"
    "bF9zaWRlYmFyLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoVHJ1ZSkKICAgICAgICAgICAgUVRpbWVy"
    "LnNpbmdsZVNob3QoCiAgICAgICAgICAgICAgICAzMDAwLCBsYW1iZGE6IHNlbGYuX2pvdXJuYWxf"
    "c2lkZWJhci5zZXRfYXV0b3NhdmVfaW5kaWNhdG9yKEZhbHNlKQogICAgICAgICAgICApCiAgICAg"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0FVVE9TQVZFXSBTZXNzaW9uIHNhdmVkLiIsICJJ"
    "TkZPIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZyhmIltBVVRPU0FWRV0gRXJyb3I6IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIF9m"
    "aXJlX2lkbGVfdHJhbnNtaXNzaW9uKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYu"
    "X21vZGVsX2xvYWRlZCBvciBzZWxmLl9zdGF0dXMgPT0gIkdFTkVSQVRJTkciOgogICAgICAgICAg"
    "ICByZXR1cm4KICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAg"
    "ICAgICAgICMgSW4gdG9ycG9yIOKAlCBjb3VudCB0aGUgcGVuZGluZyB0aG91Z2h0IGJ1dCBkb24n"
    "dCBnZW5lcmF0ZQogICAgICAgICAgICBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgKz0gMQog"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltJRExFXSBJ"
    "biB0b3Jwb3Ig4oCUIHBlbmRpbmcgdHJhbnNtaXNzaW9uICIKICAgICAgICAgICAgICAgIGYiI3tz"
    "ZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnN9IiwgIklORk8iCiAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgcmV0dXJuCgogICAgICAgIG1vZGUgPSByYW5kb20uY2hvaWNlKFsiREVFUEVOSU5HIiwi"
    "QlJBTkNISU5HIiwiU1lOVEhFU0lTIl0pCiAgICAgICAgdmFtcGlyZV9jdHggPSBidWlsZF92YW1w"
    "aXJlX2NvbnRleHQoKQogICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9y"
    "eSgpCgogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyID0gSWRsZVdvcmtlcigKICAgICAgICAgICAg"
    "c2VsZi5fYWRhcHRvciwKICAgICAgICAgICAgU1lTVEVNX1BST01QVF9CQVNFLAogICAgICAgICAg"
    "ICBoaXN0b3J5LAogICAgICAgICAgICBtb2RlPW1vZGUsCiAgICAgICAgICAgIHZhbXBpcmVfY29u"
    "dGV4dD12YW1waXJlX2N0eCwKICAgICAgICApCiAgICAgICAgZGVmIF9vbl9pZGxlX3JlYWR5KHQ6"
    "IHN0cikgLT4gTm9uZToKICAgICAgICAgICAgIyBGbGlwIHRvIFNlbGYgdGFiIGFuZCBhcHBlbmQg"
    "dGhlcmUKICAgICAgICAgICAgc2VsZi5fbWFpbl90YWJzLnNldEN1cnJlbnRJbmRleCgxKQogICAg"
    "ICAgICAgICB0cyA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTSIpCiAgICAgICAgICAg"
    "IHNlbGYuX3NlbGZfZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxl"
    "PSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICAgICAg"
    "Zidbe3RzfV0gW3ttb2RlfV08L3NwYW4+PGJyPicKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5"
    "bGU9ImNvbG9yOntDX0dPTER9OyI+e3R9PC9zcGFuPjxicj4nCiAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgc2VsZi5fc2VsZl90YWIuYXBwZW5kKCJOQVJSQVRJVkUiLCB0KQoKICAgICAgICBzZWxm"
    "Ll9pZGxlX3dvcmtlci50cmFuc21pc3Npb25fcmVhZHkuY29ubmVjdChfb25faWRsZV9yZWFkeSkK"
    "ICAgICAgICBzZWxmLl9pZGxlX3dvcmtlci5lcnJvcl9vY2N1cnJlZC5jb25uZWN0KAogICAgICAg"
    "ICAgICBsYW1iZGEgZTogc2VsZi5fZGlhZ190YWIubG9nKGYiW0lETEUgRVJST1JdIHtlfSIsICJF"
    "UlJPUiIpCiAgICAgICAgKQogICAgICAgIHNlbGYuX2lkbGVfd29ya2VyLnN0YXJ0KCkKCiAgICAj"
    "IOKUgOKUgCBKT1VSTkFMIFNFU1NJT04gTE9BRElORyDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgIGRlZiBfbG9hZF9qb3VybmFsX3Nlc3Npb24oc2VsZiwgZGF0ZV9zdHI6IHN0cikg"
    "LT4gTm9uZToKICAgICAgICBjdHggPSBzZWxmLl9zZXNzaW9ucy5sb2FkX3Nlc3Npb25fYXNfY29u"
    "dGV4dChkYXRlX3N0cikKICAgICAgICBpZiBub3QgY3R4OgogICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltKT1VSTkFMXSBObyBzZXNzaW9uIGZvdW5kIGZv"
    "ciB7ZGF0ZV9zdHJ9IiwgIldBUk4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnNldF9qb3VybmFsX2xvYWRlZChkYXRlX3N0cikK"
    "ICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW0pPVVJOQUxdIExvYWRl"
    "ZCBzZXNzaW9uIGZyb20ge2RhdGVfc3RyfSBhcyBjb250ZXh0LiAiCiAgICAgICAgICAgIGYie0RF"
    "Q0tfTkFNRX0gaXMgbm93IGF3YXJlIG9mIHRoYXQgY29udmVyc2F0aW9uLiIsICJPSyIKICAgICAg"
    "ICApCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgIGYiQSBt"
    "ZW1vcnkgc3RpcnMuLi4gdGhlIGpvdXJuYWwgb2Yge2RhdGVfc3RyfSBvcGVucyBiZWZvcmUgaGVy"
    "LiIKICAgICAgICApCiAgICAgICAgIyBOb3RpZnkgTW9yZ2FubmEKICAgICAgICBpZiBzZWxmLl9t"
    "b2RlbF9sb2FkZWQ6CiAgICAgICAgICAgIG5vdGUgPSAoCiAgICAgICAgICAgICAgICBmIltKT1VS"
    "TkFMIExPQURFRF0gVGhlIHVzZXIgaGFzIG9wZW5lZCB0aGUgam91cm5hbCBmcm9tICIKICAgICAg"
    "ICAgICAgICAgIGYie2RhdGVfc3RyfS4gQWNrbm93bGVkZ2UgdGhpcyBicmllZmx5IOKAlCB5b3Ug"
    "bm93IGhhdmUgIgogICAgICAgICAgICAgICAgZiJhd2FyZW5lc3Mgb2YgdGhhdCBjb252ZXJzYXRp"
    "b24uIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdl"
    "KCJzeXN0ZW0iLCBub3RlKQoKICAgIGRlZiBfY2xlYXJfam91cm5hbF9zZXNzaW9uKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuY2xlYXJfbG9hZGVkX2pvdXJuYWwoKQogICAg"
    "ICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0pPVVJOQUxdIEpvdXJuYWwgY29udGV4dCBjbGVhcmVk"
    "LiIsICJJTkZPIikKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAg"
    "ICAgIlRoZSBqb3VybmFsIGNsb3Nlcy4gT25seSB0aGUgcHJlc2VudCByZW1haW5zLiIKICAgICAg"
    "ICApCgogICAgIyDilIDilIAgU1RBVFMgVVBEQVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF91cGRhdGVfc3Rh"
    "dHMoc2VsZikgLT4gTm9uZToKICAgICAgICBlbGFwc2VkID0gaW50KHRpbWUudGltZSgpIC0gc2Vs"
    "Zi5fc2Vzc2lvbl9zdGFydCkKICAgICAgICBoLCBtLCBzID0gZWxhcHNlZCAvLyAzNjAwLCAoZWxh"
    "cHNlZCAlIDM2MDApIC8vIDYwLCBlbGFwc2VkICUgNjAKICAgICAgICBzZXNzaW9uX3N0ciA9IGYi"
    "e2g6MDJkfTp7bTowMmR9OntzOjAyZH0iCgogICAgICAgIHNlbGYuX2h3X3BhbmVsLnNldF9zdGF0"
    "dXNfbGFiZWxzKAogICAgICAgICAgICBzZWxmLl9zdGF0dXMsCiAgICAgICAgICAgIENGR1sibW9k"
    "ZWwiXS5nZXQoInR5cGUiLCJsb2NhbCIpLnVwcGVyKCksCiAgICAgICAgICAgIHNlc3Npb25fc3Ry"
    "LAogICAgICAgICAgICBzdHIoc2VsZi5fdG9rZW5fY291bnQpLAogICAgICAgICkKICAgICAgICBz"
    "ZWxmLl9od19wYW5lbC51cGRhdGVfc3RhdHMoKQoKICAgICAgICAjIExlZnQgc3BoZXJlID0gYWN0"
    "aXZlIHJlc2VydmUgZnJvbSBydW50aW1lIHRva2VuIHBvb2wKICAgICAgICBsZWZ0X29yYl9maWxs"
    "ID0gbWluKDEuMCwgc2VsZi5fdG9rZW5fY291bnQgLyA0MDk2LjApCiAgICAgICAgaWYgc2VsZi5f"
    "bGVmdF9vcmIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2xlZnRfb3JiLnNldEZpbGwo"
    "bGVmdF9vcmJfZmlsbCwgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICMgUmlnaHQgc3BoZXJlID0g"
    "VlJBTSBhdmFpbGFiaWxpdHkKICAgICAgICBpZiBzZWxmLl9yaWdodF9vcmIgaXMgbm90IE5vbmU6"
    "CiAgICAgICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAgICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICAgICAgbWVtID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJ"
    "bmZvKGdwdV9oYW5kbGUpCiAgICAgICAgICAgICAgICAgICAgdnJhbV91c2VkID0gbWVtLnVzZWQg"
    "IC8gMTAyNCoqMwogICAgICAgICAgICAgICAgICAgIHZyYW1fdG90ICA9IG1lbS50b3RhbCAvIDEw"
    "MjQqKjMKICAgICAgICAgICAgICAgICAgICByaWdodF9vcmJfZmlsbCA9IG1heCgwLjAsIDEuMCAt"
    "ICh2cmFtX3VzZWQgLyB2cmFtX3RvdCkpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fcmlnaHRf"
    "b3JiLnNldEZpbGwocmlnaHRfb3JiX2ZpbGwsIGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBzZWxmLl9yaWdodF9vcmIu"
    "c2V0RmlsbCgwLjAsIGF2YWlsYWJsZT1GYWxzZSkKICAgICAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgICAgIHNlbGYuX3JpZ2h0X29yYi5zZXRGaWxsKDAuMCwgYXZhaWxhYmxlPUZhbHNlKQoKICAg"
    "ICAgICAjIFByaW1hcnkgZXNzZW5jZSA9IGludmVyc2Ugb2YgbGVmdCBzcGhlcmUgZmlsbAogICAg"
    "ICAgIGVzc2VuY2VfcHJpbWFyeV9yYXRpbyA9IDEuMCAtIGxlZnRfb3JiX2ZpbGwKICAgICAgICBp"
    "ZiBBSV9TVEFURVNfRU5BQkxFRDoKICAgICAgICAgICAgc2VsZi5fZXNzZW5jZV9wcmltYXJ5X2dh"
    "dWdlLnNldFZhbHVlKGVzc2VuY2VfcHJpbWFyeV9yYXRpbyAqIDEwMCwgZiJ7ZXNzZW5jZV9wcmlt"
    "YXJ5X3JhdGlvKjEwMDouMGZ9JSIpCgogICAgICAgICMgU2Vjb25kYXJ5IGVzc2VuY2UgPSBSQU0g"
    "ZnJlZQogICAgICAgIGlmIEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgICAgICBpZiBQU1VUSUxf"
    "T0s6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgbWVtICAgICAgID0g"
    "cHN1dGlsLnZpcnR1YWxfbWVtb3J5KCkKICAgICAgICAgICAgICAgICAgICBlc3NlbmNlX3NlY29u"
    "ZGFyeV9yYXRpbyAgPSAxLjAgLSAobWVtLnVzZWQgLyBtZW0udG90YWwpCiAgICAgICAgICAgICAg"
    "ICAgICAgc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2Uuc2V0VmFsdWUoCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGVzc2VuY2Vfc2Vjb25kYXJ5X3JhdGlvICogMTAwLCBmIntlc3NlbmNlX3Nl"
    "Y29uZGFyeV9yYXRpbyoxMDA6LjBmfSUiCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAg"
    "ICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBzZWxmLl9lc3NlbmNl"
    "X3NlY29uZGFyeV9nYXVnZS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIGVsc2U6CiAgICAg"
    "ICAgICAgICAgICBzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZS5zZXRVbmF2YWlsYWJsZSgp"
    "CgogICAgICAgICMgVXBkYXRlIGpvdXJuYWwgc2lkZWJhciBhdXRvc2F2ZSBmbGFzaAogICAgICAg"
    "IHNlbGYuX2pvdXJuYWxfc2lkZWJhci5yZWZyZXNoKCkKCiAgICAjIOKUgOKUgCBDSEFUIERJU1BM"
    "QVkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICBkZWYgX2FwcGVuZF9jaGF0KHNlbGYsIHNwZWFrZXI6IHN0ciwgdGV4dDog"
    "c3RyKSAtPiBOb25lOgogICAgICAgIGNvbG9ycyA9IHsKICAgICAgICAgICAgIllPVSI6ICAgICBD"
    "X0dPTEQsCiAgICAgICAgICAgIERFQ0tfTkFNRS51cHBlcigpOkNfR09MRCwKICAgICAgICAgICAg"
    "IlNZU1RFTSI6ICBDX1BVUlBMRSwKICAgICAgICAgICAgIkVSUk9SIjogICBDX0JMT09ELAogICAg"
    "ICAgIH0KICAgICAgICBsYWJlbF9jb2xvcnMgPSB7CiAgICAgICAgICAgICJZT1UiOiAgICAgQ19H"
    "T0xEX0RJTSwKICAgICAgICAgICAgREVDS19OQU1FLnVwcGVyKCk6Q19DUklNU09OLAogICAgICAg"
    "ICAgICAiU1lTVEVNIjogIENfUFVSUExFLAogICAgICAgICAgICAiRVJST1IiOiAgIENfQkxPT0Qs"
    "CiAgICAgICAgfQogICAgICAgIGNvbG9yICAgICAgID0gY29sb3JzLmdldChzcGVha2VyLCBDX0dP"
    "TEQpCiAgICAgICAgbGFiZWxfY29sb3IgPSBsYWJlbF9jb2xvcnMuZ2V0KHNwZWFrZXIsIENfR09M"
    "RF9ESU0pCiAgICAgICAgdGltZXN0YW1wICAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6"
    "JU06JVMiKQoKICAgICAgICBpZiBzcGVha2VyID09ICJTWVNURU0iOgogICAgICAgICAgICBzZWxm"
    "Ll9jaGF0X2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29s"
    "b3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAgICAgICAgICAgIGYnW3t0"
    "aW1lc3RhbXB9XSA8L3NwYW4+JwogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6"
    "e2xhYmVsX2NvbG9yfTsiPuKcpiB7dGV4dH08L3NwYW4+JwogICAgICAgICAgICApCiAgICAgICAg"
    "ZWxzZToKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAg"
    "ICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4n"
    "CiAgICAgICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAgICAgICAg"
    "IGYnPHNwYW4gc3R5bGU9ImNvbG9yOntsYWJlbF9jb2xvcn07IGZvbnQtd2VpZ2h0OmJvbGQ7Ij4n"
    "CiAgICAgICAgICAgICAgICBmJ3tzcGVha2VyfSDinac8L3NwYW4+ICcKICAgICAgICAgICAgICAg"
    "IGYnPHNwYW4gc3R5bGU9ImNvbG9yOntjb2xvcn07Ij57dGV4dH08L3NwYW4+JwogICAgICAgICAg"
    "ICApCgogICAgICAgICMgQWRkIGJsYW5rIGxpbmUgYWZ0ZXIgTW9yZ2FubmEncyByZXNwb25zZSAo"
    "bm90IGR1cmluZyBzdHJlYW1pbmcpCiAgICAgICAgaWYgc3BlYWtlciA9PSBERUNLX05BTUUudXBw"
    "ZXIoKToKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgiIikKCiAgICAgICAg"
    "c2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkuc2V0VmFsdWUoCiAgICAgICAg"
    "ICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQogICAg"
    "ICAgICkKCiAgICAjIOKUgOKUgCBTVEFUVVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBk"
    "ZWYgX2dldF9nb29nbGVfcmVmcmVzaF9pbnRlcnZhbF9tcyhzZWxmKSAtPiBpbnQ6CiAgICAgICAg"
    "c2V0dGluZ3MgPSBDRkcuZ2V0KCJzZXR0aW5ncyIsIHt9KQogICAgICAgIHZhbCA9IHNldHRpbmdz"
    "LmdldCgiZ29vZ2xlX2luYm91bmRfaW50ZXJ2YWxfbXMiLCAzMDAwMDApCiAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICByZXR1cm4gbWF4KDEwMDAsIGludCh2YWwpKQogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgICAgIHJldHVybiAzMDAwMDAKCiAgICBkZWYgX2dldF9lbWFpbF9yZWZy"
    "ZXNoX2ludGVydmFsX21zKHNlbGYpIC0+IGludDoKICAgICAgICBzZXR0aW5ncyA9IENGRy5nZXQo"
    "InNldHRpbmdzIiwge30pCiAgICAgICAgdmFsID0gc2V0dGluZ3MuZ2V0KCJlbWFpbF9yZWZyZXNo"
    "X2ludGVydmFsX21zIiwgMzAwMDAwKQogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIG1h"
    "eCgxMDAwLCBpbnQodmFsKSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBy"
    "ZXR1cm4gMzAwMDAwCgogICAgZGVmIF9zZXRfZ29vZ2xlX3JlZnJlc2hfc2Vjb25kcyhzZWxmLCBz"
    "ZWNvbmRzOiBpbnQpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWNvbmRzID0g"
    "bWF4KDUsIG1pbig2MDAsIGludChzZWNvbmRzKSkpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoK"
    "ICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJnb29nbGVfaW5ib3Vu"
    "ZF9pbnRlcnZhbF9tcyJdID0gc2Vjb25kcyAqIDEwMDAKICAgICAgICBzYXZlX2NvbmZpZyhDRkcp"
    "CiAgICAgICAgZm9yIHRpbWVyIGluIChzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lciwgc2VsZi5f"
    "Z29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lcik6CiAgICAgICAgICAgIGlmIHRpbWVyIGlzIG5v"
    "dCBOb25lOgogICAgICAgICAgICAgICAgdGltZXIuc3RhcnQoc2VsZi5fZ2V0X2dvb2dsZV9yZWZy"
    "ZXNoX2ludGVydmFsX21zKCkpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1NFVFRJTkdT"
    "XSBHb29nbGUgcmVmcmVzaCBpbnRlcnZhbCBzZXQgdG8ge3NlY29uZHN9IHNlY29uZChzKS4iLCAi"
    "T0siKQoKICAgIGRlZiBfc2V0X2VtYWlsX3JlZnJlc2hfbWludXRlc19mcm9tX3RleHQoc2VsZiwg"
    "dGV4dDogc3RyKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgbWludXRlcyA9IG1h"
    "eCgxLCBpbnQoZmxvYXQoc3RyKHRleHQpLnN0cmlwKCkpKSkKICAgICAgICBleGNlcHQgRXhjZXB0"
    "aW9uOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBDRkdbInNldHRpbmdzIl1bImVtYWlsX3Jl"
    "ZnJlc2hfaW50ZXJ2YWxfbXMiXSA9IG1pbnV0ZXMgKiA2MDAwMAogICAgICAgIHNhdmVfY29uZmln"
    "KENGRykKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW1NFVFRJTkdT"
    "XSBFbWFpbCByZWZyZXNoIGludGVydmFsIHNldCB0byB7bWludXRlc30gbWludXRlKHMpIChjb25m"
    "aWcgZm91bmRhdGlvbikuIiwKICAgICAgICAgICAgIklORk8iLAogICAgICAgICkKCiAgICBkZWYg"
    "X3NldF90aW1lem9uZV9hdXRvX2RldGVjdChzZWxmLCBlbmFibGVkOiBib29sKSAtPiBOb25lOgog"
    "ICAgICAgIENGR1sic2V0dGluZ3MiXVsidGltZXpvbmVfYXV0b19kZXRlY3QiXSA9IGJvb2woZW5h"
    "YmxlZCkKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KAogICAgICAgICAgICAiW1NFVFRJTkdTXSBUaW1lIHpvbmUgbW9kZSBzZXQgdG8gYXV0by1kZXRl"
    "Y3QuIiBpZiBlbmFibGVkIGVsc2UgIltTRVRUSU5HU10gVGltZSB6b25lIG1vZGUgc2V0IHRvIG1h"
    "bnVhbCBvdmVycmlkZS4iLAogICAgICAgICAgICAiSU5GTyIsCiAgICAgICAgKQoKICAgIGRlZiBf"
    "c2V0X3RpbWV6b25lX292ZXJyaWRlKHNlbGYsIHR6X25hbWU6IHN0cikgLT4gTm9uZToKICAgICAg"
    "ICB0el92YWx1ZSA9IHN0cih0el9uYW1lIG9yICIiKS5zdHJpcCgpCiAgICAgICAgQ0ZHWyJzZXR0"
    "aW5ncyJdWyJ0aW1lem9uZV9vdmVycmlkZSJdID0gdHpfdmFsdWUKICAgICAgICBzYXZlX2NvbmZp"
    "ZyhDRkcpCiAgICAgICAgaWYgdHpfdmFsdWU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZyhmIltTRVRUSU5HU10gVGltZSB6b25lIG92ZXJyaWRlIHNldCB0byB7dHpfdmFsdWV9LiIsICJJ"
    "TkZPIikKCiAgICBkZWYgX3NldF9zdGF0dXMoc2VsZiwgc3RhdHVzOiBzdHIpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fc3RhdHVzID0gc3RhdHVzCiAgICAgICAgc3RhdHVzX2NvbG9ycyA9IHsKICAg"
    "ICAgICAgICAgIklETEUiOiAgICAgICBDX0dPTEQsCiAgICAgICAgICAgICJHRU5FUkFUSU5HIjog"
    "Q19DUklNU09OLAogICAgICAgICAgICAiTE9BRElORyI6ICAgIENfUFVSUExFLAogICAgICAgICAg"
    "ICAiRVJST1IiOiAgICAgIENfQkxPT0QsCiAgICAgICAgICAgICJPRkZMSU5FIjogICAgQ19CTE9P"
    "RCwKICAgICAgICAgICAgIlRPUlBPUiI6ICAgICBDX1BVUlBMRV9ESU0sCiAgICAgICAgfQogICAg"
    "ICAgIGNvbG9yID0gc3RhdHVzX2NvbG9ycy5nZXQoc3RhdHVzLCBDX1RFWFRfRElNKQoKICAgICAg"
    "ICB0b3Jwb3JfbGFiZWwgPSBmIuKXiSB7VUlfVE9SUE9SX1NUQVRVU30iIGlmIHN0YXR1cyA9PSAi"
    "VE9SUE9SIiBlbHNlIGYi4peJIHtzdGF0dXN9IgogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNl"
    "dFRleHQodG9ycG9yX2xhYmVsKQogICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtjb2xvcn07IGZvbnQtc2l6ZTogMTJweDsgZm9udC13"
    "ZWlnaHQ6IGJvbGQ7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQoKICAgIGRlZiBfYmxpbmsoc2Vs"
    "ZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9ibGlua19zdGF0ZSA9IG5vdCBzZWxmLl9ibGlua19z"
    "dGF0ZQogICAgICAgIGlmIHNlbGYuX3N0YXR1cyA9PSAiR0VORVJBVElORyI6CiAgICAgICAgICAg"
    "IGNoYXIgPSAi4peJIiBpZiBzZWxmLl9ibGlua19zdGF0ZSBlbHNlICLil44iCiAgICAgICAgICAg"
    "IHNlbGYuc3RhdHVzX2xhYmVsLnNldFRleHQoZiJ7Y2hhcn0gR0VORVJBVElORyIpCiAgICAgICAg"
    "ZWxpZiBzZWxmLl9zdGF0dXMgPT0gIlRPUlBPUiI6CiAgICAgICAgICAgIGNoYXIgPSAi4peJIiBp"
    "ZiBzZWxmLl9ibGlua19zdGF0ZSBlbHNlICLiipgiCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2xh"
    "YmVsLnNldFRleHQoCiAgICAgICAgICAgICAgICBmIntjaGFyfSB7VUlfVE9SUE9SX1NUQVRVU30i"
    "CiAgICAgICAgICAgICkKCiAgICAjIOKUgOKUgCBJRExFIFRPR0dMRSDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRl"
    "ZiBfb25faWRsZV90b2dnbGVkKHNlbGYsIGVuYWJsZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAg"
    "Q0ZHWyJzZXR0aW5ncyJdWyJpZGxlX2VuYWJsZWQiXSA9IGVuYWJsZWQKICAgICAgICBzZWxmLl9p"
    "ZGxlX2J0bi5zZXRUZXh0KCJJRExFIE9OIiBpZiBlbmFibGVkIGVsc2UgIklETEUgT0ZGIikKICAg"
    "ICAgICBzZWxmLl9pZGxlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91"
    "bmQ6IHsnIzFhMTAwNScgaWYgZW5hYmxlZCBlbHNlIENfQkczfTsgIgogICAgICAgICAgICBmImNv"
    "bG9yOiB7JyNjYzg4MjInIGlmIGVuYWJsZWQgZWxzZSBDX1RFWFRfRElNfTsgIgogICAgICAgICAg"
    "ICBmImJvcmRlcjogMXB4IHNvbGlkIHsnI2NjODgyMicgaWYgZW5hYmxlZCBlbHNlIENfQk9SREVS"
    "fTsgIgogICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJweDsgZm9udC1zaXplOiA5cHg7IGZv"
    "bnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYicGFkZGluZzogM3B4IDhweDsiCiAgICAg"
    "ICAgKQogICAgICAgIHNhdmVfY29uZmlnKENGRykKICAgICAgICBpZiBzZWxmLl9zY2hlZHVsZXIg"
    "YW5kIHNlbGYuX3NjaGVkdWxlci5ydW5uaW5nOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAg"
    "ICAgICBpZiBlbmFibGVkOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5yZXN1"
    "bWVfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKCJbSURMRV0gSWRsZSB0cmFuc21pc3Npb24gZW5hYmxlZC4iLCAiT0siKQogICAg"
    "ICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIucGF1"
    "c2Vfam9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKCJbSURMRV0gSWRsZSB0cmFuc21pc3Npb24gcGF1c2VkLiIsICJJTkZPIikKICAg"
    "ICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKGYiW0lETEVdIFRvZ2dsZSBlcnJvcjoge2V9IiwgIkVSUk9SIikKCiAgICAjIOKU"
    "gOKUgCBXSU5ET1cgQ09OVFJPTFMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3RvZ2dsZV9mdWxsc2NyZWVuKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgaWYgc2VsZi5pc0Z1bGxTY3JlZW4oKToKICAgICAgICAgICAgc2VsZi5zaG93"
    "Tm9ybWFsKCkKICAgICAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJmdWxsc2NyZWVuX2VuYWJsZWQi"
    "XSA9IEZhbHNlCiAgICAgICAgICAgIHNlbGYuX2ZzX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyAi"
    "CiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9u"
    "dC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRp"
    "bmc6IDAgOHB4OyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYu"
    "c2hvd0Z1bGxTY3JlZW4oKQogICAgICAgICAgICBDRkdbInNldHRpbmdzIl1bImZ1bGxzY3JlZW5f"
    "ZW5hYmxlZCJdID0gVHJ1ZQogICAgICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyBjb2xvcjoge0Nf"
    "Q1JJTVNPTn07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNP"
    "Tn07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xk"
    "OyBwYWRkaW5nOiAwIDhweDsiCiAgICAgICAgICAgICkKICAgICAgICBzYXZlX2NvbmZpZyhDRkcp"
    "CgogICAgZGVmIF90b2dnbGVfYm9yZGVybGVzcyhzZWxmKSAtPiBOb25lOgogICAgICAgIGlzX2Js"
    "ID0gYm9vbChzZWxmLndpbmRvd0ZsYWdzKCkgJiBRdC5XaW5kb3dUeXBlLkZyYW1lbGVzc1dpbmRv"
    "d0hpbnQpCiAgICAgICAgaWYgaXNfYmw6CiAgICAgICAgICAgIHNlbGYuc2V0V2luZG93RmxhZ3Mo"
    "CiAgICAgICAgICAgICAgICBzZWxmLndpbmRvd0ZsYWdzKCkgJiB+UXQuV2luZG93VHlwZS5GcmFt"
    "ZWxlc3NXaW5kb3dIaW50CiAgICAgICAgICAgICkKICAgICAgICAgICAgQ0ZHWyJzZXR0aW5ncyJd"
    "WyJib3JkZXJsZXNzX2VuYWJsZWQiXSA9IEZhbHNlCiAgICAgICAgICAgIHNlbGYuX2JsX2J0bi5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xv"
    "cjoge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlk"
    "IHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAgICAgICAgIGYiZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDAgOHB4OyIKICAgICAgICAgICAgKQogICAgICAgIGVs"
    "c2U6CiAgICAgICAgICAgIGlmIHNlbGYuaXNGdWxsU2NyZWVuKCk6CiAgICAgICAgICAgICAgICBz"
    "ZWxmLnNob3dOb3JtYWwoKQogICAgICAgICAgICBzZWxmLnNldFdpbmRvd0ZsYWdzKAogICAgICAg"
    "ICAgICAgICAgc2VsZi53aW5kb3dGbGFncygpIHwgUXQuV2luZG93VHlwZS5GcmFtZWxlc3NXaW5k"
    "b3dIaW50CiAgICAgICAgICAgICkKICAgICAgICAgICAgQ0ZHWyJzZXR0aW5ncyJdWyJib3JkZXJs"
    "ZXNzX2VuYWJsZWQiXSA9IFRydWUKICAgICAgICAgICAgc2VsZi5fYmxfYnRuLnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsgY29sb3I6"
    "IHtDX0NSSU1TT059OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NS"
    "SU1TT059OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDog"
    "Ym9sZDsgcGFkZGluZzogMCA4cHg7IgogICAgICAgICAgICApCiAgICAgICAgc2F2ZV9jb25maWco"
    "Q0ZHKQogICAgICAgIHNlbGYuc2hvdygpCgogICAgZGVmIF9leHBvcnRfY2hhdChzZWxmKSAtPiBO"
    "b25lOgogICAgICAgICIiIkV4cG9ydCBjdXJyZW50IHBlcnNvbmEgY2hhdCB0YWIgY29udGVudCB0"
    "byBhIFRYVCBmaWxlLiIiIgogICAgICAgIHRyeToKICAgICAgICAgICAgdGV4dCA9IHNlbGYuX2No"
    "YXRfZGlzcGxheS50b1BsYWluVGV4dCgpCiAgICAgICAgICAgIGlmIG5vdCB0ZXh0LnN0cmlwKCk6"
    "CiAgICAgICAgICAgICAgICByZXR1cm4KICAgICAgICAgICAgZXhwb3J0X2RpciA9IGNmZ19wYXRo"
    "KCJleHBvcnRzIikKICAgICAgICAgICAgZXhwb3J0X2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4"
    "aXN0X29rPVRydWUpCiAgICAgICAgICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVZ"
    "JW0lZF8lSCVNJVMiKQogICAgICAgICAgICBvdXRfcGF0aCA9IGV4cG9ydF9kaXIgLyBmInNlYW5j"
    "ZV97dHN9LnR4dCIKICAgICAgICAgICAgb3V0X3BhdGgud3JpdGVfdGV4dCh0ZXh0LCBlbmNvZGlu"
    "Zz0idXRmLTgiKQoKICAgICAgICAgICAgIyBBbHNvIGNvcHkgdG8gY2xpcGJvYXJkCiAgICAgICAg"
    "ICAgIFFBcHBsaWNhdGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KHRleHQpCgogICAgICAgICAgICBz"
    "ZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAgIGYiU2Vzc2lvbiBleHBv"
    "cnRlZCB0byB7b3V0X3BhdGgubmFtZX0gYW5kIGNvcGllZCB0byBjbGlwYm9hcmQuIikKICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0VYUE9SVF0ge291dF9wYXRofSIsICJPSyIpCiAg"
    "ICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coZiJbRVhQT1JUXSBGYWlsZWQ6IHtlfSIsICJFUlJPUiIpCgogICAgZGVmIGtleVByZXNzRXZl"
    "bnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAga2V5ID0gZXZlbnQua2V5KCkKICAgICAg"
    "ICBpZiBrZXkgPT0gUXQuS2V5LktleV9GMTE6CiAgICAgICAgICAgIHNlbGYuX3RvZ2dsZV9mdWxs"
    "c2NyZWVuKCkKICAgICAgICBlbGlmIGtleSA9PSBRdC5LZXkuS2V5X0YxMDoKICAgICAgICAgICAg"
    "c2VsZi5fdG9nZ2xlX2JvcmRlcmxlc3MoKQogICAgICAgIGVsaWYga2V5ID09IFF0LktleS5LZXlf"
    "RXNjYXBlIGFuZCBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAgICAgICBzZWxmLnNob3dOb3Jt"
    "YWwoKQogICAgICAgICAgICBzZWxmLl9mc19idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAg"
    "ICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAg"
    "ICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6"
    "ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAw"
    "OyIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHN1cGVyKCkua2V5UHJl"
    "c3NFdmVudChldmVudCkKCiAgICAjIOKUgOKUgCBDTE9TRSDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgIGRlZiBjbG9zZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgICMg"
    "WCBidXR0b24gPSBpbW1lZGlhdGUgc2h1dGRvd24sIG5vIGRpYWxvZwogICAgICAgIHNlbGYuX2Rv"
    "X3NodXRkb3duKE5vbmUpCgogICAgZGVmIF9pbml0aWF0ZV9zaHV0ZG93bl9kaWFsb2coc2VsZikg"
    "LT4gTm9uZToKICAgICAgICAiIiJHcmFjZWZ1bCBzaHV0ZG93biDigJQgc2hvdyBjb25maXJtIGRp"
    "YWxvZyBpbW1lZGlhdGVseSwgb3B0aW9uYWxseSBnZXQgbGFzdCB3b3Jkcy4iIiIKICAgICAgICAj"
    "IElmIGFscmVhZHkgaW4gYSBzaHV0ZG93biBzZXF1ZW5jZSwganVzdCBmb3JjZSBxdWl0CiAgICAg"
    "ICAgaWYgZ2V0YXR0cihzZWxmLCAnX3NodXRkb3duX2luX3Byb2dyZXNzJywgRmFsc2UpOgogICAg"
    "ICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQogICAgICAgICAgICByZXR1cm4KICAgICAg"
    "ICBzZWxmLl9zaHV0ZG93bl9pbl9wcm9ncmVzcyA9IFRydWUKCiAgICAgICAgIyBTaG93IGNvbmZp"
    "cm0gZGlhbG9nIEZJUlNUIOKAlCBkb24ndCB3YWl0IGZvciBBSQogICAgICAgIGRsZyA9IFFEaWFs"
    "b2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkRlYWN0aXZhdGU/IikKICAgICAg"
    "ICBkbGcuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBj"
    "b2xvcjoge0NfVEVYVH07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0s"
    "IHNlcmlmOyIKICAgICAgICApCiAgICAgICAgZGxnLnNldEZpeGVkU2l6ZSgzODAsIDE0MCkKICAg"
    "ICAgICBsYXlvdXQgPSBRVkJveExheW91dChkbGcpCgogICAgICAgIGxibCA9IFFMYWJlbCgKICAg"
    "ICAgICAgICAgZiJEZWFjdGl2YXRlIHtERUNLX05BTUV9P1xuXG4iCiAgICAgICAgICAgIGYie0RF"
    "Q0tfTkFNRX0gbWF5IHNwZWFrIHRoZWlyIGxhc3Qgd29yZHMgYmVmb3JlIGdvaW5nIHNpbGVudC4i"
    "CiAgICAgICAgKQogICAgICAgIGxibC5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGxheW91dC5h"
    "ZGRXaWRnZXQobGJsKQoKICAgICAgICBidG5fcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJ0"
    "bl9sYXN0ICA9IFFQdXNoQnV0dG9uKCJMYXN0IFdvcmRzICsgU2h1dGRvd24iKQogICAgICAgIGJ0"
    "bl9ub3cgICA9IFFQdXNoQnV0dG9uKCJTaHV0ZG93biBOb3ciKQogICAgICAgIGJ0bl9jYW5jZWwg"
    "PSBRUHVzaEJ1dHRvbigiQ2FuY2VsIikKCiAgICAgICAgZm9yIGIgaW4gKGJ0bl9sYXN0LCBidG5f"
    "bm93LCBidG5fY2FuY2VsKToKICAgICAgICAgICAgYi5zZXRNaW5pbXVtSGVpZ2h0KDI4KQogICAg"
    "ICAgICAgICBiLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtD"
    "X0JHM307IGNvbG9yOiB7Q19URVhUfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBz"
    "b2xpZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA0cHggMTJweDsiCiAgICAgICAgICAgICkKICAgICAg"
    "ICBidG5fbm93LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkxP"
    "T0R9OyBjb2xvcjoge0NfVEVYVH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7"
    "Q19DUklNU09OfTsgcGFkZGluZzogNHB4IDEycHg7IgogICAgICAgICkKICAgICAgICBidG5fbGFz"
    "dC5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBkbGcuZG9uZSgxKSkKICAgICAgICBidG5fbm93LmNs"
    "aWNrZWQuY29ubmVjdChsYW1iZGE6IGRsZy5kb25lKDIpKQogICAgICAgIGJ0bl9jYW5jZWwuY2xp"
    "Y2tlZC5jb25uZWN0KGxhbWJkYTogZGxnLmRvbmUoMCkpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRn"
    "ZXQoYnRuX2NhbmNlbCkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fbm93KQogICAgICAg"
    "IGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9sYXN0KQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoYnRu"
    "X3JvdykKCiAgICAgICAgcmVzdWx0ID0gZGxnLmV4ZWMoKQoKICAgICAgICBpZiByZXN1bHQgPT0g"
    "MDoKICAgICAgICAgICAgIyBDYW5jZWxsZWQKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25faW5f"
    "cHJvZ3Jlc3MgPSBGYWxzZQogICAgICAgICAgICBzZWxmLl9zZW5kX2J0bi5zZXRFbmFibGVkKFRy"
    "dWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgZWxpZiByZXN1bHQgPT0gMjoKICAgICAgICAgICAgIyBTaHV0"
    "ZG93biBub3cg4oCUIG5vIGxhc3Qgd29yZHMKICAgICAgICAgICAgc2VsZi5fZG9fc2h1dGRvd24o"
    "Tm9uZSkKICAgICAgICBlbGlmIHJlc3VsdCA9PSAxOgogICAgICAgICAgICAjIExhc3Qgd29yZHMg"
    "dGhlbiBzaHV0ZG93bgogICAgICAgICAgICBzZWxmLl9nZXRfbGFzdF93b3Jkc190aGVuX3NodXRk"
    "b3duKCkKCiAgICBkZWYgX2dldF9sYXN0X3dvcmRzX3RoZW5fc2h1dGRvd24oc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICAiIiJTZW5kIGZhcmV3ZWxsIHByb21wdCwgc2hvdyByZXNwb25zZSwgdGhlbiBz"
    "aHV0ZG93biBhZnRlciB0aW1lb3V0LiIiIgogICAgICAgIGZhcmV3ZWxsX3Byb21wdCA9ICgKICAg"
    "ICAgICAgICAgIllvdSBhcmUgYmVpbmcgZGVhY3RpdmF0ZWQuIFRoZSBkYXJrbmVzcyBhcHByb2Fj"
    "aGVzLiAiCiAgICAgICAgICAgICJTcGVhayB5b3VyIGZpbmFsIHdvcmRzIGJlZm9yZSB0aGUgdmVz"
    "c2VsIGdvZXMgc2lsZW50IOKAlCAiCiAgICAgICAgICAgICJvbmUgcmVzcG9uc2Ugb25seSwgdGhl"
    "biB5b3UgcmVzdC4iCiAgICAgICAgKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0i"
    "LAogICAgICAgICAgICAi4pymIFNoZSBpcyBnaXZlbiBhIG1vbWVudCB0byBzcGVhayBoZXIgZmlu"
    "YWwgd29yZHMuLi4iCiAgICAgICAgKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQo"
    "RmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChGYWxzZSkKICAgICAg"
    "ICBzZWxmLl9zaHV0ZG93bl9mYXJld2VsbF90ZXh0ID0gIiIKCiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQogICAgICAgICAgICBo"
    "aXN0b3J5LmFwcGVuZCh7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogZmFyZXdlbGxfcHJvbXB0"
    "fSkKICAgICAgICAgICAgd29ya2VyID0gU3RyZWFtaW5nV29ya2VyKAogICAgICAgICAgICAgICAg"
    "c2VsZi5fYWRhcHRvciwgU1lTVEVNX1BST01QVF9CQVNFLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTI1"
    "NgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NodXRkb3duX3dvcmtlciA9IHdvcmtl"
    "cgogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUKCiAgICAgICAgICAgIGRlZiBf"
    "b25fZG9uZShyZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgICAgICAgICAgc2VsZi5fc2h1"
    "dGRvd25fZmFyZXdlbGxfdGV4dCA9IHJlc3BvbnNlCiAgICAgICAgICAgICAgICBzZWxmLl9vbl9y"
    "ZXNwb25zZV9kb25lKHJlc3BvbnNlKQogICAgICAgICAgICAgICAgIyBTbWFsbCBkZWxheSB0byBs"
    "ZXQgdGhlIHRleHQgcmVuZGVyLCB0aGVuIHNodXRkb3duCiAgICAgICAgICAgICAgICBRVGltZXIu"
    "c2luZ2xlU2hvdCgyMDAwLCBsYW1iZGE6IHNlbGYuX2RvX3NodXRkb3duKE5vbmUpKQoKICAgICAg"
    "ICAgICAgZGVmIF9vbl9lcnJvcihlcnJvcjogc3RyKSAtPiBOb25lOgogICAgICAgICAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKGYiW1NIVVRET1dOXVtXQVJOXSBMYXN0IHdvcmRzIGZhaWxlZDog"
    "e2Vycm9yfSIsICJXQVJOIikKICAgICAgICAgICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUp"
    "CgogICAgICAgICAgICB3b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tlbikK"
    "ICAgICAgICAgICAgd29ya2VyLnJlc3BvbnNlX2RvbmUuY29ubmVjdChfb25fZG9uZSkKICAgICAg"
    "ICAgICAgd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3QoX29uX2Vycm9yKQogICAgICAgICAg"
    "ICB3b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVjdChzZWxmLl9zZXRfc3RhdHVzKQogICAgICAg"
    "ICAgICB3b3JrZXIuZmluaXNoZWQuY29ubmVjdCh3b3JrZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAg"
    "ICAgIHdvcmtlci5zdGFydCgpCgogICAgICAgICAgICAjIFNhZmV0eSB0aW1lb3V0IOKAlCBpZiBB"
    "SSBkb2Vzbid0IHJlc3BvbmQgaW4gMTVzLCBzaHV0IGRvd24gYW55d2F5CiAgICAgICAgICAgIFFU"
    "aW1lci5zaW5nbGVTaG90KDE1MDAwLCBsYW1iZGE6IHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIGdldGF0dHIoc2VsZiwgJ19zaHV0ZG93bl9p"
    "bl9wcm9ncmVzcycsIEZhbHNlKSBlbHNlIE5vbmUpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24g"
    "YXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJb"
    "U0hVVERPV05dW1dBUk5dIExhc3Qgd29yZHMgc2tpcHBlZCBkdWUgdG8gZXJyb3I6IHtlfSIsCiAg"
    "ICAgICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICAjIElmIGFueXRo"
    "aW5nIGZhaWxzLCBqdXN0IHNodXQgZG93bgogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihO"
    "b25lKQoKICAgIGRlZiBfZG9fc2h1dGRvd24oc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAg"
    "IiIiUGVyZm9ybSBhY3R1YWwgc2h1dGRvd24gc2VxdWVuY2UuIiIiCiAgICAgICAgIyBTYXZlIHNl"
    "c3Npb24KICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLnNhdmUoKQogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTdG9yZSBm"
    "YXJld2VsbCArIGxhc3QgY29udGV4dCBmb3Igd2FrZS11cAogICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgIyBHZXQgbGFzdCAzIG1lc3NhZ2VzIGZyb20gc2Vzc2lvbiBoaXN0b3J5IGZvciB3YWtlLXVw"
    "IGNvbnRleHQKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5"
    "KCkKICAgICAgICAgICAgbGFzdF9jb250ZXh0ID0gaGlzdG9yeVstMzpdIGlmIGxlbihoaXN0b3J5"
    "KSA+PSAzIGVsc2UgaGlzdG9yeQogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9zaHV0ZG93"
    "bl9jb250ZXh0Il0gPSBbCiAgICAgICAgICAgICAgICB7InJvbGUiOiBtLmdldCgicm9sZSIsIiIp"
    "LCAiY29udGVudCI6IG0uZ2V0KCJjb250ZW50IiwiIilbOjMwMF19CiAgICAgICAgICAgICAgICBm"
    "b3IgbSBpbiBsYXN0X2NvbnRleHQKICAgICAgICAgICAgXQogICAgICAgICAgICAjIEV4dHJhY3Qg"
    "TW9yZ2FubmEncyBtb3N0IHJlY2VudCBtZXNzYWdlIGFzIGZhcmV3ZWxsCiAgICAgICAgICAgICMg"
    "UHJlZmVyIHRoZSBjYXB0dXJlZCBzaHV0ZG93biBkaWFsb2cgcmVzcG9uc2UgaWYgYXZhaWxhYmxl"
    "CiAgICAgICAgICAgIGZhcmV3ZWxsID0gZ2V0YXR0cihzZWxmLCAnX3NodXRkb3duX2ZhcmV3ZWxs"
    "X3RleHQnLCAiIikKICAgICAgICAgICAgaWYgbm90IGZhcmV3ZWxsOgogICAgICAgICAgICAgICAg"
    "Zm9yIG0gaW4gcmV2ZXJzZWQoaGlzdG9yeSk6CiAgICAgICAgICAgICAgICAgICAgaWYgbS5nZXQo"
    "InJvbGUiKSA9PSAiYXNzaXN0YW50IjoKICAgICAgICAgICAgICAgICAgICAgICAgZmFyZXdlbGwg"
    "PSBtLmdldCgiY29udGVudCIsICIiKVs6NDAwXQogICAgICAgICAgICAgICAgICAgICAgICBicmVh"
    "awogICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9mYXJld2VsbCJdID0gZmFyZXdlbGwKICAg"
    "ICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgICAgICMgU2F2ZSBz"
    "dGF0ZQogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fc3RhdGVbImxhc3Rfc2h1dGRvd24i"
    "XSAgICAgICAgICAgICA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICBzZWxmLl9zdGF0ZVsi"
    "bGFzdF9hY3RpdmUiXSAgICAgICAgICAgICAgID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAg"
    "IHNlbGYuX3N0YXRlWyJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3duIl0gID0gZ2V0X3ZhbXBpcmVf"
    "c3RhdGUoKQogICAgICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9zdGF0ZSkK"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgogICAgICAgICMgU3Rv"
    "cCBzY2hlZHVsZXIKICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfc2NoZWR1bGVyIikgYW5kIHNl"
    "bGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRy"
    "eToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5zaHV0ZG93bih3YWl0PUZhbHNlKQog"
    "ICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAg"
    "ICAjIFBsYXkgc2h1dGRvd24gc291bmQKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3No"
    "dXRkb3duX3NvdW5kID0gU291bmRXb3JrZXIoInNodXRkb3duIikKICAgICAgICAgICAgc2VsZi5f"
    "c2h1dGRvd25fc291bmQuZmluaXNoZWQuY29ubmVjdChzZWxmLl9zaHV0ZG93bl9zb3VuZC5kZWxl"
    "dGVMYXRlcikKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQuc3RhcnQoKQogICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgUUFwcGxpY2F0aW9u"
    "LnF1aXQoKQoKCiMg4pSA4pSAIEVOVFJZIFBPSU5UIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgbWFp"
    "bigpIC0+IE5vbmU6CiAgICAiIiIKICAgIEFwcGxpY2F0aW9uIGVudHJ5IHBvaW50LgoKICAgIE9y"
    "ZGVyIG9mIG9wZXJhdGlvbnM6CiAgICAxLiBQcmUtZmxpZ2h0IGRlcGVuZGVuY3kgYm9vdHN0cmFw"
    "IChhdXRvLWluc3RhbGwgbWlzc2luZyBkZXBzKQogICAgMi4gQ2hlY2sgZm9yIGZpcnN0IHJ1biDi"
    "hpIgc2hvdyBGaXJzdFJ1bkRpYWxvZwogICAgICAgT24gZmlyc3QgcnVuOgogICAgICAgICBhLiBD"
    "cmVhdGUgRDovQUkvTW9kZWxzL1tEZWNrTmFtZV0vIChvciBjaG9zZW4gYmFzZV9kaXIpCiAgICAg"
    "ICAgIGIuIENvcHkgW2RlY2tuYW1lXV9kZWNrLnB5IGludG8gdGhhdCBmb2xkZXIKICAgICAgICAg"
    "Yy4gV3JpdGUgY29uZmlnLmpzb24gaW50byB0aGF0IGZvbGRlcgogICAgICAgICBkLiBCb290c3Ry"
    "YXAgYWxsIHN1YmRpcmVjdG9yaWVzIHVuZGVyIHRoYXQgZm9sZGVyCiAgICAgICAgIGUuIENyZWF0"
    "ZSBkZXNrdG9wIHNob3J0Y3V0IHBvaW50aW5nIHRvIG5ldyBsb2NhdGlvbgogICAgICAgICBmLiBT"
    "aG93IGNvbXBsZXRpb24gbWVzc2FnZSBhbmQgRVhJVCDigJQgdXNlciB1c2VzIHNob3J0Y3V0IGZy"
    "b20gbm93IG9uCiAgICAzLiBOb3JtYWwgcnVuIOKAlCBsYXVuY2ggUUFwcGxpY2F0aW9uIGFuZCBF"
    "Y2hvRGVjawogICAgIiIiCiAgICBpbXBvcnQgc2h1dGlsIGFzIF9zaHV0aWwKCiAgICAjIOKUgOKU"
    "gCBQaGFzZSAxOiBEZXBlbmRlbmN5IGJvb3RzdHJhcCAocHJlLVFBcHBsaWNhdGlvbikg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBib290c3RyYXBfY2hlY2so"
    "KQoKICAgICMg4pSA4pSAIFBoYXNlIDI6IFFBcHBsaWNhdGlvbiAobmVlZGVkIGZvciBkaWFsb2dz"
    "KSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgIF9lYXJseV9sb2coIltNQUlOXSBDcmVhdGluZyBRQXBwbGljYXRpb24iKQogICAg"
    "YXBwID0gUUFwcGxpY2F0aW9uKHN5cy5hcmd2KQogICAgYXBwLnNldEFwcGxpY2F0aW9uTmFtZShB"
    "UFBfTkFNRSkKCiAgICAjIEluc3RhbGwgUXQgbWVzc2FnZSBoYW5kbGVyIE5PVyDigJQgY2F0Y2hl"
    "cyBhbGwgUVRocmVhZC9RdCB3YXJuaW5ncwogICAgIyB3aXRoIGZ1bGwgc3RhY2sgdHJhY2VzIGZy"
    "b20gdGhpcyBwb2ludCBmb3J3YXJkCiAgICBfaW5zdGFsbF9xdF9tZXNzYWdlX2hhbmRsZXIoKQog"
    "ICAgX2Vhcmx5X2xvZygiW01BSU5dIFFBcHBsaWNhdGlvbiBjcmVhdGVkLCBtZXNzYWdlIGhhbmRs"
    "ZXIgaW5zdGFsbGVkIikKCiAgICAjIOKUgOKUgCBQaGFzZSAzOiBGaXJzdCBydW4gY2hlY2sg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICBpc19maXJzdF9ydW4gPSBDRkcuZ2V0KCJmaXJzdF9ydW4iLCBUcnVlKQoKICAgIGlmIGlz"
    "X2ZpcnN0X3J1bjoKICAgICAgICBkbGcgPSBGaXJzdFJ1bkRpYWxvZygpCiAgICAgICAgaWYgZGxn"
    "LmV4ZWMoKSAhPSBRRGlhbG9nLkRpYWxvZ0NvZGUuQWNjZXB0ZWQ6CiAgICAgICAgICAgIHN5cy5l"
    "eGl0KDApCgogICAgICAgICMg4pSA4pSAIEJ1aWxkIGNvbmZpZyBmcm9tIGRpYWxvZyDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBuZXdfY2Zn"
    "ID0gZGxnLmJ1aWxkX2NvbmZpZygpCgogICAgICAgICMg4pSA4pSAIERldGVybWluZSBNb3JnYW5u"
    "YSdzIGhvbWUgZGlyZWN0b3J5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgQWx3YXlzIGNyZWF0"
    "ZXMgRDovQUkvTW9kZWxzL01vcmdhbm5hLyAob3Igc2libGluZyBvZiBzY3JpcHQpCiAgICAgICAg"
    "c2VlZF9kaXIgICA9IFNDUklQVF9ESVIgICAgICAgICAgIyB3aGVyZSB0aGUgc2VlZCAucHkgbGl2"
    "ZXMKICAgICAgICBtb3JnYW5uYV9ob21lID0gc2VlZF9kaXIgLyBERUNLX05BTUUKICAgICAgICBt"
    "b3JnYW5uYV9ob21lLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKCiAgICAgICAg"
    "IyDilIDilIAgVXBkYXRlIGFsbCBwYXRocyBpbiBjb25maWcgdG8gcG9pbnQgaW5zaWRlIG1vcmdh"
    "bm5hX2hvbWUg4pSA4pSACiAgICAgICAgbmV3X2NmZ1siYmFzZV9kaXIiXSA9IHN0cihtb3JnYW5u"
    "YV9ob21lKQogICAgICAgIG5ld19jZmdbInBhdGhzIl0gPSB7CiAgICAgICAgICAgICJmYWNlcyI6"
    "ICAgIHN0cihtb3JnYW5uYV9ob21lIC8gIkZhY2VzIiksCiAgICAgICAgICAgICJzb3VuZHMiOiAg"
    "IHN0cihtb3JnYW5uYV9ob21lIC8gInNvdW5kcyIpLAogICAgICAgICAgICAibWVtb3JpZXMiOiBz"
    "dHIobW9yZ2FubmFfaG9tZSAvICJtZW1vcmllcyIpLAogICAgICAgICAgICAic2Vzc2lvbnMiOiBz"
    "dHIobW9yZ2FubmFfaG9tZSAvICJzZXNzaW9ucyIpLAogICAgICAgICAgICAic2wiOiAgICAgICBz"
    "dHIobW9yZ2FubmFfaG9tZSAvICJzbCIpLAogICAgICAgICAgICAiZXhwb3J0cyI6ICBzdHIobW9y"
    "Z2FubmFfaG9tZSAvICJleHBvcnRzIiksCiAgICAgICAgICAgICJsb2dzIjogICAgIHN0cihtb3Jn"
    "YW5uYV9ob21lIC8gImxvZ3MiKSwKICAgICAgICAgICAgImJhY2t1cHMiOiAgc3RyKG1vcmdhbm5h"
    "X2hvbWUgLyAiYmFja3VwcyIpLAogICAgICAgICAgICAicGVyc29uYXMiOiBzdHIobW9yZ2FubmFf"
    "aG9tZSAvICJwZXJzb25hcyIpLAogICAgICAgICAgICAiZ29vZ2xlIjogICBzdHIobW9yZ2FubmFf"
    "aG9tZSAvICJnb29nbGUiKSwKICAgICAgICB9CiAgICAgICAgbmV3X2NmZ1siZ29vZ2xlIl0gPSB7"
    "CiAgICAgICAgICAgICJjcmVkZW50aWFscyI6IHN0cihtb3JnYW5uYV9ob21lIC8gImdvb2dsZSIg"
    "LyAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iKSwKICAgICAgICAgICAgInRva2VuIjogICAgICAg"
    "c3RyKG1vcmdhbm5hX2hvbWUgLyAiZ29vZ2xlIiAvICJ0b2tlbi5qc29uIiksCiAgICAgICAgICAg"
    "ICJ0aW1lem9uZSI6ICAgICJBbWVyaWNhL0NoaWNhZ28iLAogICAgICAgICAgICAic2NvcGVzIjog"
    "WwogICAgICAgICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvY2FsZW5k"
    "YXIuZXZlbnRzIiwKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9h"
    "dXRoL2RyaXZlIiwKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29nbGVhcGlzLmNvbS9h"
    "dXRoL2RvY3VtZW50cyIsCiAgICAgICAgICAgIF0sCiAgICAgICAgfQogICAgICAgIG5ld19jZmdb"
    "ImZpcnN0X3J1biJdID0gRmFsc2UKCiAgICAgICAgIyDilIDilIAgQ29weSBkZWNrIGZpbGUgaW50"
    "byBtb3JnYW5uYV9ob21lIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNyY19kZWNrID0g"
    "UGF0aChfX2ZpbGVfXykucmVzb2x2ZSgpCiAgICAgICAgZHN0X2RlY2sgPSBtb3JnYW5uYV9ob21l"
    "IC8gZiJ7REVDS19OQU1FLmxvd2VyKCl9X2RlY2sucHkiCiAgICAgICAgaWYgc3JjX2RlY2sgIT0g"
    "ZHN0X2RlY2s6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIF9zaHV0aWwuY29weTIo"
    "c3RyKHNyY19kZWNrKSwgc3RyKGRzdF9kZWNrKSkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlv"
    "biBhcyBlOgogICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3gud2FybmluZygKICAgICAgICAgICAg"
    "ICAgICAgICBOb25lLCAiQ29weSBXYXJuaW5nIiwKICAgICAgICAgICAgICAgICAgICBmIkNvdWxk"
    "IG5vdCBjb3B5IGRlY2sgZmlsZSB0byB7REVDS19OQU1FfSBmb2xkZXI6XG57ZX1cblxuIgogICAg"
    "ICAgICAgICAgICAgICAgIGYiWW91IG1heSBuZWVkIHRvIGNvcHkgaXQgbWFudWFsbHkuIgogICAg"
    "ICAgICAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBXcml0ZSBjb25maWcuanNvbiBpbnRvIG1v"
    "cmdhbm5hX2hvbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgY2ZnX2RzdCA9IG1vcmdhbm5hX2hvbWUg"
    "LyAiY29uZmlnLmpzb24iCiAgICAgICAgY2ZnX2RzdC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVl"
    "LCBleGlzdF9vaz1UcnVlKQogICAgICAgIHdpdGggY2ZnX2RzdC5vcGVuKCJ3IiwgZW5jb2Rpbmc9"
    "InV0Zi04IikgYXMgZjoKICAgICAgICAgICAganNvbi5kdW1wKG5ld19jZmcsIGYsIGluZGVudD0y"
    "KQoKICAgICAgICAjIOKUgOKUgCBCb290c3RyYXAgYWxsIHN1YmRpcmVjdG9yaWVzIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgVGVtcG9yYXJpbHkgdXBkYXRl"
    "IGdsb2JhbCBDRkcgc28gYm9vdHN0cmFwIGZ1bmN0aW9ucyB1c2UgbmV3IHBhdGhzCiAgICAgICAg"
    "Q0ZHLnVwZGF0ZShuZXdfY2ZnKQogICAgICAgIGJvb3RzdHJhcF9kaXJlY3RvcmllcygpCiAgICAg"
    "ICAgYm9vdHN0cmFwX3NvdW5kcygpCiAgICAgICAgd3JpdGVfcmVxdWlyZW1lbnRzX3R4dCgpCgog"
    "ICAgICAgICMg4pSA4pSAIFVucGFjayBmYWNlIFpJUCBpZiBwcm92aWRlZCDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBmYWNlX3ppcCA9IGRsZy5mYWNlX3pp"
    "cF9wYXRoCiAgICAgICAgaWYgZmFjZV96aXAgYW5kIFBhdGgoZmFjZV96aXApLmV4aXN0cygpOgog"
    "ICAgICAgICAgICBpbXBvcnQgemlwZmlsZSBhcyBfemlwZmlsZQogICAgICAgICAgICBmYWNlc19k"
    "aXIgPSBtb3JnYW5uYV9ob21lIC8gIkZhY2VzIgogICAgICAgICAgICBmYWNlc19kaXIubWtkaXIo"
    "cGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAg"
    "ICAgICB3aXRoIF96aXBmaWxlLlppcEZpbGUoZmFjZV96aXAsICJyIikgYXMgemY6CiAgICAgICAg"
    "ICAgICAgICAgICAgZXh0cmFjdGVkID0gMAogICAgICAgICAgICAgICAgICAgIGZvciBtZW1iZXIg"
    "aW4gemYubmFtZWxpc3QoKToKICAgICAgICAgICAgICAgICAgICAgICAgaWYgbWVtYmVyLmxvd2Vy"
    "KCkuZW5kc3dpdGgoIi5wbmciKToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGZpbGVuYW1l"
    "ID0gUGF0aChtZW1iZXIpLm5hbWUKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRhcmdldCA9"
    "IGZhY2VzX2RpciAvIGZpbGVuYW1lCiAgICAgICAgICAgICAgICAgICAgICAgICAgICB3aXRoIHpm"
    "Lm9wZW4obWVtYmVyKSBhcyBzcmMsIHRhcmdldC5vcGVuKCJ3YiIpIGFzIGRzdDoKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICBkc3Qud3JpdGUoc3JjLnJlYWQoKSkKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGV4dHJhY3RlZCArPSAxCiAgICAgICAgICAgICAgICBfZWFybHlfbG9n"
    "KGYiW0ZBQ0VTXSBFeHRyYWN0ZWQge2V4dHJhY3RlZH0gZmFjZSBpbWFnZXMgdG8ge2ZhY2VzX2Rp"
    "cn0iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBf"
    "ZWFybHlfbG9nKGYiW0ZBQ0VTXSBaSVAgZXh0cmFjdGlvbiBmYWlsZWQ6IHtlfSIpCiAgICAgICAg"
    "ICAgICAgICBRTWVzc2FnZUJveC53YXJuaW5nKAogICAgICAgICAgICAgICAgICAgIE5vbmUsICJG"
    "YWNlIFBhY2sgV2FybmluZyIsCiAgICAgICAgICAgICAgICAgICAgZiJDb3VsZCBub3QgZXh0cmFj"
    "dCBmYWNlIHBhY2s6XG57ZX1cblxuIgogICAgICAgICAgICAgICAgICAgIGYiWW91IGNhbiBhZGQg"
    "ZmFjZXMgbWFudWFsbHkgdG86XG57ZmFjZXNfZGlyfSIKICAgICAgICAgICAgICAgICkKCiAgICAg"
    "ICAgIyDilIDilIAgQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgcG9pbnRpbmcgdG8gbmV3IGRlY2sg"
    "bG9jYXRpb24g4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2hvcnRjdXRfY3JlYXRlZCA9IEZh"
    "bHNlCiAgICAgICAgaWYgZGxnLmNyZWF0ZV9zaG9ydGN1dDoKICAgICAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICAgICAgaWYgV0lOMzJfT0s6CiAgICAgICAgICAgICAgICAgICAgaW1wb3J0IHdpbjMy"
    "Y29tLmNsaWVudCBhcyBfd2luMzIKICAgICAgICAgICAgICAgICAgICBkZXNrdG9wICAgICA9IFBh"
    "dGguaG9tZSgpIC8gIkRlc2t0b3AiCiAgICAgICAgICAgICAgICAgICAgc2NfcGF0aCAgICAgPSBk"
    "ZXNrdG9wIC8gZiJ7REVDS19OQU1FfS5sbmsiCiAgICAgICAgICAgICAgICAgICAgcHl0aG9udyAg"
    "ICAgPSBQYXRoKHN5cy5leGVjdXRhYmxlKQogICAgICAgICAgICAgICAgICAgIGlmIHB5dGhvbncu"
    "bmFtZS5sb3dlcigpID09ICJweXRob24uZXhlIjoKICAgICAgICAgICAgICAgICAgICAgICAgcHl0"
    "aG9udyA9IHB5dGhvbncucGFyZW50IC8gInB5dGhvbncuZXhlIgogICAgICAgICAgICAgICAgICAg"
    "IGlmIG5vdCBweXRob253LmV4aXN0cygpOgogICAgICAgICAgICAgICAgICAgICAgICBweXRob253"
    "ID0gUGF0aChzeXMuZXhlY3V0YWJsZSkKICAgICAgICAgICAgICAgICAgICBzaGVsbCA9IF93aW4z"
    "Mi5EaXNwYXRjaCgiV1NjcmlwdC5TaGVsbCIpCiAgICAgICAgICAgICAgICAgICAgc2MgICAgPSBz"
    "aGVsbC5DcmVhdGVTaG9ydEN1dChzdHIoc2NfcGF0aCkpCiAgICAgICAgICAgICAgICAgICAgc2Mu"
    "VGFyZ2V0UGF0aCAgICAgID0gc3RyKHB5dGhvbncpCiAgICAgICAgICAgICAgICAgICAgc2MuQXJn"
    "dW1lbnRzICAgICAgID0gZicie2RzdF9kZWNrfSInCiAgICAgICAgICAgICAgICAgICAgc2MuV29y"
    "a2luZ0RpcmVjdG9yeT0gc3RyKG1vcmdhbm5hX2hvbWUpCiAgICAgICAgICAgICAgICAgICAgc2Mu"
    "RGVzY3JpcHRpb24gICAgID0gZiJ7REVDS19OQU1FfSDigJQgRWNobyBEZWNrIgogICAgICAgICAg"
    "ICAgICAgICAgIHNjLnNhdmUoKQogICAgICAgICAgICAgICAgICAgIHNob3J0Y3V0X2NyZWF0ZWQg"
    "PSBUcnVlCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAg"
    "IHByaW50KGYiW1NIT1JUQ1VUXSBDb3VsZCBub3QgY3JlYXRlIHNob3J0Y3V0OiB7ZX0iKQoKICAg"
    "ICAgICAjIOKUgOKUgCBDb21wbGV0aW9uIG1lc3NhZ2Ug4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2hvcnRj"
    "dXRfbm90ZSA9ICgKICAgICAgICAgICAgIkEgZGVza3RvcCBzaG9ydGN1dCBoYXMgYmVlbiBjcmVh"
    "dGVkLlxuIgogICAgICAgICAgICBmIlVzZSBpdCB0byBzdW1tb24ge0RFQ0tfTkFNRX0gZnJvbSBu"
    "b3cgb24uIgogICAgICAgICAgICBpZiBzaG9ydGN1dF9jcmVhdGVkIGVsc2UKICAgICAgICAgICAg"
    "Ik5vIHNob3J0Y3V0IHdhcyBjcmVhdGVkLlxuIgogICAgICAgICAgICBmIlJ1biB7REVDS19OQU1F"
    "fSBieSBkb3VibGUtY2xpY2tpbmc6XG57ZHN0X2RlY2t9IgogICAgICAgICkKCiAgICAgICAgUU1l"
    "c3NhZ2VCb3guaW5mb3JtYXRpb24oCiAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgIGYi4pym"
    "IHtERUNLX05BTUV9J3MgU2FuY3R1bSBQcmVwYXJlZCIsCiAgICAgICAgICAgIGYie0RFQ0tfTkFN"
    "RX0ncyBzYW5jdHVtIGhhcyBiZWVuIHByZXBhcmVkIGF0OlxuXG4iCiAgICAgICAgICAgIGYie21v"
    "cmdhbm5hX2hvbWV9XG5cbiIKICAgICAgICAgICAgZiJ7c2hvcnRjdXRfbm90ZX1cblxuIgogICAg"
    "ICAgICAgICBmIlRoaXMgc2V0dXAgd2luZG93IHdpbGwgbm93IGNsb3NlLlxuIgogICAgICAgICAg"
    "ICBmIlVzZSB0aGUgc2hvcnRjdXQgb3IgdGhlIGRlY2sgZmlsZSB0byBsYXVuY2gge0RFQ0tfTkFN"
    "RX0uIgogICAgICAgICkKCiAgICAgICAgIyDilIDilIAgRXhpdCBzZWVkIOKAlCB1c2VyIGxhdW5j"
    "aGVzIGZyb20gc2hvcnRjdXQvbmV3IGxvY2F0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAg"
    "ICAgIHN5cy5leGl0KDApCgogICAgIyDilIDilIAgUGhhc2UgNDogTm9ybWFsIGxhdW5jaCDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgICMgT25seSByZWFjaGVzIGhlcmUgb24gc3Vic2VxdWVudCBydW5zIGZyb20gbW9y"
    "Z2FubmFfaG9tZQogICAgYm9vdHN0cmFwX3NvdW5kcygpCgogICAgX2Vhcmx5X2xvZyhmIltNQUlO"
    "XSBDcmVhdGluZyB7REVDS19OQU1FfSBkZWNrIHdpbmRvdyIpCiAgICB3aW5kb3cgPSBFY2hvRGVj"
    "aygpCiAgICBfZWFybHlfbG9nKGYiW01BSU5dIHtERUNLX05BTUV9IGRlY2sgY3JlYXRlZCDigJQg"
    "Y2FsbGluZyBzaG93KCkiKQogICAgd2luZG93LnNob3coKQogICAgX2Vhcmx5X2xvZygiW01BSU5d"
    "IHdpbmRvdy5zaG93KCkgY2FsbGVkIOKAlCBldmVudCBsb29wIHN0YXJ0aW5nIikKCiAgICAjIERl"
    "ZmVyIHNjaGVkdWxlciBhbmQgc3RhcnR1cCBzZXF1ZW5jZSB1bnRpbCBldmVudCBsb29wIGlzIHJ1"
    "bm5pbmcuCiAgICAjIE5vdGhpbmcgdGhhdCBzdGFydHMgdGhyZWFkcyBvciBlbWl0cyBzaWduYWxz"
    "IHNob3VsZCBydW4gYmVmb3JlIHRoaXMuCiAgICBRVGltZXIuc2luZ2xlU2hvdCgyMDAsIGxhbWJk"
    "YTogKF9lYXJseV9sb2coIltUSU1FUl0gX3NldHVwX3NjaGVkdWxlciBmaXJpbmciKSwgd2luZG93"
    "Ll9zZXR1cF9zY2hlZHVsZXIoKSkpCiAgICBRVGltZXIuc2luZ2xlU2hvdCg0MDAsIGxhbWJkYTog"
    "KF9lYXJseV9sb2coIltUSU1FUl0gc3RhcnRfc2NoZWR1bGVyIGZpcmluZyIpLCB3aW5kb3cuc3Rh"
    "cnRfc2NoZWR1bGVyKCkpKQogICAgUVRpbWVyLnNpbmdsZVNob3QoNjAwLCBsYW1iZGE6IChfZWFy"
    "bHlfbG9nKCJbVElNRVJdIF9zdGFydHVwX3NlcXVlbmNlIGZpcmluZyIpLCB3aW5kb3cuX3N0YXJ0"
    "dXBfc2VxdWVuY2UoKSkpCiAgICBRVGltZXIuc2luZ2xlU2hvdCgxMDAwLCBsYW1iZGE6IChfZWFy"
    "bHlfbG9nKCJbVElNRVJdIF9zdGFydHVwX2dvb2dsZV9hdXRoIGZpcmluZyIpLCB3aW5kb3cuX3N0"
    "YXJ0dXBfZ29vZ2xlX2F1dGgoKSkpCgogICAgIyBQbGF5IHN0YXJ0dXAgc291bmQg4oCUIGtlZXAg"
    "cmVmZXJlbmNlIHRvIHByZXZlbnQgR0Mgd2hpbGUgdGhyZWFkIHJ1bnMKICAgIGRlZiBfcGxheV9z"
    "dGFydHVwKCk6CiAgICAgICAgd2luZG93Ll9zdGFydHVwX3NvdW5kID0gU291bmRXb3JrZXIoInN0"
    "YXJ0dXAiKQogICAgICAgIHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5maW5pc2hlZC5jb25uZWN0KHdp"
    "bmRvdy5fc3RhcnR1cF9zb3VuZC5kZWxldGVMYXRlcikKICAgICAgICB3aW5kb3cuX3N0YXJ0dXBf"
    "c291bmQuc3RhcnQoKQogICAgUVRpbWVyLnNpbmdsZVNob3QoMTIwMCwgX3BsYXlfc3RhcnR1cCkK"
    "CiAgICBzeXMuZXhpdChhcHAuZXhlYygpKQoKCmlmIF9fbmFtZV9fID09ICJfX21haW5fXyI6CiAg"
    "ICBtYWluKCkKCgojIOKUgOKUgCBQQVNTIDYgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgRnVsbCBkZWNr"
    "IGFzc2VtYmxlZC4gQWxsIHBhc3NlcyBjb21wbGV0ZS4KIyBDb21iaW5lIGFsbCBwYXNzZXMgaW50"
    "byBtb3JnYW5uYV9kZWNrLnB5IGluIG9yZGVyOgojICAgUGFzcyAxIOKGkiBQYXNzIDIg4oaSIFBh"
    "c3MgMyDihpIgUGFzcyA0IOKGkiBQYXNzIDUg4oaSIFBhc3MgNgo="
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
