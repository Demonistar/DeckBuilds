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
    "dCwgUVNjcm9sbEFyZWEsCiAgICBRU3BsaXR0ZXIsIFFJbnB1dERpYWxvZywgUVRvb2xCdXR0b24sIFFTcGluQm94LCBRR3JhcGhp"
    "Y3NPcGFjaXR5RWZmZWN0CikKZnJvbSBQeVNpZGU2LlF0Q29yZSBpbXBvcnQgKAogICAgUXQsIFFUaW1lciwgUVRocmVhZCwgU2ln"
    "bmFsLCBRRGF0ZSwgUVNpemUsIFFQb2ludCwgUVJlY3QsCiAgICBRUHJvcGVydHlBbmltYXRpb24sIFFFYXNpbmdDdXJ2ZQopCmZy"
    "b20gUHlTaWRlNi5RdEd1aSBpbXBvcnQgKAogICAgUUZvbnQsIFFDb2xvciwgUVBhaW50ZXIsIFFMaW5lYXJHcmFkaWVudCwgUVJh"
    "ZGlhbEdyYWRpZW50LAogICAgUVBpeG1hcCwgUVBlbiwgUVBhaW50ZXJQYXRoLCBRVGV4dENoYXJGb3JtYXQsIFFJY29uLAogICAg"
    "UVRleHRDdXJzb3IsIFFBY3Rpb24KKQoKIyDilIDilIAgQVBQIElERU5USVRZIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApBUFBfTkFNRSAgICAgID0gVUlfV0lORE9XX1RJVExFCkFQUF9WRVJTSU9OICAgPSAiMi4wLjAiCkFQUF9GSUxFTkFN"
    "RSAgPSBmIntERUNLX05BTUUubG93ZXIoKX1fZGVjay5weSIKQlVJTERfREFURSAgICA9ICIyMDI2LTA0LTA0IgoKIyDilIDilIAg"
    "Q09ORklHIExPQURJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgY29uZmlnLmpzb24gbGl2ZXMgbmV4dCB0"
    "byB0aGUgZGVjayAucHkgZmlsZS4KIyBBbGwgcGF0aHMgY29tZSBmcm9tIGNvbmZpZy4gTm90aGluZyBoYXJkY29kZWQgYmVsb3cg"
    "dGhpcyBwb2ludC4KClNDUklQVF9ESVIgPSBQYXRoKF9fZmlsZV9fKS5yZXNvbHZlKCkucGFyZW50CkNPTkZJR19QQVRIID0gU0NS"
    "SVBUX0RJUiAvICJjb25maWcuanNvbiIKCiMgSW5pdGlhbGl6ZSBlYXJseSBsb2cgbm93IHRoYXQgd2Uga25vdyB3aGVyZSB3ZSBh"
    "cmUKX2luaXRfZWFybHlfbG9nKFNDUklQVF9ESVIpCl9lYXJseV9sb2coZiJbSU5JVF0gU0NSSVBUX0RJUiA9IHtTQ1JJUFRfRElS"
    "fSIpCl9lYXJseV9sb2coZiJbSU5JVF0gQ09ORklHX1BBVEggPSB7Q09ORklHX1BBVEh9IikKX2Vhcmx5X2xvZyhmIltJTklUXSBj"
    "b25maWcuanNvbiBleGlzdHM6IHtDT05GSUdfUEFUSC5leGlzdHMoKX0iKQoKZGVmIF9kZWZhdWx0X2NvbmZpZygpIC0+IGRpY3Q6"
    "CiAgICAiIiJSZXR1cm5zIHRoZSBkZWZhdWx0IGNvbmZpZyBzdHJ1Y3R1cmUgZm9yIGZpcnN0LXJ1biBnZW5lcmF0aW9uLiIiIgog"
    "ICAgYmFzZSA9IHN0cihTQ1JJUFRfRElSKQogICAgcmV0dXJuIHsKICAgICAgICAiZGVja19uYW1lIjogREVDS19OQU1FLAogICAg"
    "ICAgICJkZWNrX3ZlcnNpb24iOiBBUFBfVkVSU0lPTiwKICAgICAgICAiYmFzZV9kaXIiOiBiYXNlLAogICAgICAgICJtb2RlbCI6"
    "IHsKICAgICAgICAgICAgInR5cGUiOiAibG9jYWwiLCAgICAgICAgICAjIGxvY2FsIHwgb2xsYW1hIHwgY2xhdWRlIHwgb3BlbmFp"
    "CiAgICAgICAgICAgICJwYXRoIjogIiIsICAgICAgICAgICAgICAgIyBsb2NhbCBtb2RlbCBmb2xkZXIgcGF0aAogICAgICAgICAg"
    "ICAib2xsYW1hX21vZGVsIjogIiIsICAgICAgICMgZS5nLiAiZG9scGhpbi0yLjYtN2IiCiAgICAgICAgICAgICJhcGlfa2V5Ijog"
    "IiIsICAgICAgICAgICAgIyBDbGF1ZGUgb3IgT3BlbkFJIGtleQogICAgICAgICAgICAiYXBpX3R5cGUiOiAiIiwgICAgICAgICAg"
    "ICMgImNsYXVkZSIgfCAib3BlbmFpIgogICAgICAgICAgICAiYXBpX21vZGVsIjogIiIsICAgICAgICAgICMgZS5nLiAiY2xhdWRl"
    "LXNvbm5ldC00LTYiCiAgICAgICAgfSwKICAgICAgICAiZ29vZ2xlIjogewogICAgICAgICAgICAiY3JlZGVudGlhbHMiOiBzdHIo"
    "U0NSSVBUX0RJUiAvICJnb29nbGUiIC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIiksCiAgICAgICAgICAgICJ0b2tlbiI6ICAg"
    "ICAgIHN0cihTQ1JJUFRfRElSIC8gImdvb2dsZSIgLyAidG9rZW4uanNvbiIpLAogICAgICAgICAgICAidGltZXpvbmUiOiAgICAi"
    "QW1lcmljYS9DaGljYWdvIiwKICAgICAgICAgICAgInNjb3BlcyI6IFsKICAgICAgICAgICAgICAgICJodHRwczovL3d3dy5nb29n"
    "bGVhcGlzLmNvbS9hdXRoL2NhbGVuZGFyLmV2ZW50cyIsCiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5j"
    "b20vYXV0aC9kcml2ZSIsCiAgICAgICAgICAgICAgICAiaHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9kb2N1bWVudHMi"
    "LAogICAgICAgICAgICBdLAogICAgICAgIH0sCiAgICAgICAgInBhdGhzIjogewogICAgICAgICAgICAiZmFjZXMiOiAgICBzdHIo"
    "U0NSSVBUX0RJUiAvICJGYWNlcyIpLAogICAgICAgICAgICAic291bmRzIjogICBzdHIoU0NSSVBUX0RJUiAvICJzb3VuZHMiKSwK"
    "ICAgICAgICAgICAgIm1lbW9yaWVzIjogc3RyKFNDUklQVF9ESVIgLyAibWVtb3JpZXMiKSwKICAgICAgICAgICAgInNlc3Npb25z"
    "Ijogc3RyKFNDUklQVF9ESVIgLyAic2Vzc2lvbnMiKSwKICAgICAgICAgICAgInNsIjogICAgICAgc3RyKFNDUklQVF9ESVIgLyAi"
    "c2wiKSwKICAgICAgICAgICAgImV4cG9ydHMiOiAgc3RyKFNDUklQVF9ESVIgLyAiZXhwb3J0cyIpLAogICAgICAgICAgICAibG9n"
    "cyI6ICAgICBzdHIoU0NSSVBUX0RJUiAvICJsb2dzIiksCiAgICAgICAgICAgICJiYWNrdXBzIjogIHN0cihTQ1JJUFRfRElSIC8g"
    "ImJhY2t1cHMiKSwKICAgICAgICAgICAgInBlcnNvbmFzIjogc3RyKFNDUklQVF9ESVIgLyAicGVyc29uYXMiKSwKICAgICAgICAg"
    "ICAgImdvb2dsZSI6ICAgc3RyKFNDUklQVF9ESVIgLyAiZ29vZ2xlIiksCiAgICAgICAgfSwKICAgICAgICAic2V0dGluZ3MiOiB7"
    "CiAgICAgICAgICAgICJpZGxlX2VuYWJsZWQiOiAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICAgICJpZGxlX21pbl9taW51"
    "dGVzIjogICAgICAgICAgMTAsCiAgICAgICAgICAgICJpZGxlX21heF9taW51dGVzIjogICAgICAgICAgMzAsCiAgICAgICAgICAg"
    "ICJhdXRvc2F2ZV9pbnRlcnZhbF9taW51dGVzIjogMTAsCiAgICAgICAgICAgICJtYXhfYmFja3VwcyI6ICAgICAgICAgICAgICAg"
    "MTAsCiAgICAgICAgICAgICJnb29nbGVfc3luY19lbmFibGVkIjogICAgICAgVHJ1ZSwKICAgICAgICAgICAgInNvdW5kX2VuYWJs"
    "ZWQiOiAgICAgICAgICAgICBUcnVlLAogICAgICAgICAgICAiZ29vZ2xlX2luYm91bmRfaW50ZXJ2YWxfbXMiOiAzMDAwMCwKICAg"
    "ICAgICAgICAgImVtYWlsX3JlZnJlc2hfaW50ZXJ2YWxfbXMiOiAzMDAwMDAsCiAgICAgICAgICAgICJnb29nbGVfbG9va2JhY2tf"
    "ZGF5cyI6ICAgICAgMzAsCiAgICAgICAgICAgICJ1c2VyX2RlbGF5X3RocmVzaG9sZF9taW4iOiAgMzAsCiAgICAgICAgICAgICJ0"
    "aW1lem9uZV9hdXRvX2RldGVjdCI6ICAgICAgVHJ1ZSwKICAgICAgICAgICAgInRpbWV6b25lX292ZXJyaWRlIjogICAgICAgICAi"
    "IiwKICAgICAgICAgICAgImZ1bGxzY3JlZW5fZW5hYmxlZCI6ICAgICAgICBGYWxzZSwKICAgICAgICAgICAgImJvcmRlcmxlc3Nf"
    "ZW5hYmxlZCI6ICAgICAgICBGYWxzZSwKICAgICAgICB9LAogICAgICAgICJmaXJzdF9ydW4iOiBUcnVlLAogICAgfQoKZGVmIGxv"
    "YWRfY29uZmlnKCkgLT4gZGljdDoKICAgICIiIkxvYWQgY29uZmlnLmpzb24uIFJldHVybnMgZGVmYXVsdCBpZiBtaXNzaW5nIG9y"
    "IGNvcnJ1cHQuIiIiCiAgICBpZiBub3QgQ09ORklHX1BBVEguZXhpc3RzKCk6CiAgICAgICAgcmV0dXJuIF9kZWZhdWx0X2NvbmZp"
    "ZygpCiAgICB0cnk6CiAgICAgICAgd2l0aCBDT05GSUdfUEFUSC5vcGVuKCJyIiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAg"
    "ICAgICAgICAgcmV0dXJuIGpzb24ubG9hZChmKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICByZXR1cm4gX2RlZmF1bHRf"
    "Y29uZmlnKCkKCmRlZiBzYXZlX2NvbmZpZyhjZmc6IGRpY3QpIC0+IE5vbmU6CiAgICAiIiJXcml0ZSBjb25maWcuanNvbi4iIiIK"
    "ICAgIENPTkZJR19QQVRILnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIENPTkZJR19Q"
    "QVRILm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgIGpzb24uZHVtcChjZmcsIGYsIGluZGVudD0yKQoK"
    "IyBMb2FkIGNvbmZpZyBhdCBtb2R1bGUgbGV2ZWwg4oCUIGV2ZXJ5dGhpbmcgYmVsb3cgcmVhZHMgZnJvbSBDRkcKQ0ZHID0gbG9h"
    "ZF9jb25maWcoKQpfZWFybHlfbG9nKGYiW0lOSVRdIENvbmZpZyBsb2FkZWQg4oCUIGZpcnN0X3J1bj17Q0ZHLmdldCgnZmlyc3Rf"
    "cnVuJyl9LCBtb2RlbF90eXBlPXtDRkcuZ2V0KCdtb2RlbCcse30pLmdldCgndHlwZScpfSIpCgpfREVGQVVMVF9QQVRIUzogZGlj"
    "dFtzdHIsIFBhdGhdID0gewogICAgImZhY2VzIjogICAgU0NSSVBUX0RJUiAvICJGYWNlcyIsCiAgICAic291bmRzIjogICBTQ1JJ"
    "UFRfRElSIC8gInNvdW5kcyIsCiAgICAibWVtb3JpZXMiOiBTQ1JJUFRfRElSIC8gIm1lbW9yaWVzIiwKICAgICJzZXNzaW9ucyI6"
    "IFNDUklQVF9ESVIgLyAic2Vzc2lvbnMiLAogICAgInNsIjogICAgICAgU0NSSVBUX0RJUiAvICJzbCIsCiAgICAiZXhwb3J0cyI6"
    "ICBTQ1JJUFRfRElSIC8gImV4cG9ydHMiLAogICAgImxvZ3MiOiAgICAgU0NSSVBUX0RJUiAvICJsb2dzIiwKICAgICJiYWNrdXBz"
    "IjogIFNDUklQVF9ESVIgLyAiYmFja3VwcyIsCiAgICAicGVyc29uYXMiOiBTQ1JJUFRfRElSIC8gInBlcnNvbmFzIiwKICAgICJn"
    "b29nbGUiOiAgIFNDUklQVF9ESVIgLyAiZ29vZ2xlIiwKfQoKZGVmIF9ub3JtYWxpemVfY29uZmlnX3BhdGhzKCkgLT4gTm9uZToK"
    "ICAgICIiIgogICAgU2VsZi1oZWFsIG9sZGVyIGNvbmZpZy5qc29uIGZpbGVzIG1pc3NpbmcgcmVxdWlyZWQgcGF0aCBrZXlzLgog"
    "ICAgQWRkcyBtaXNzaW5nIHBhdGgga2V5cyBhbmQgbm9ybWFsaXplcyBnb29nbGUgY3JlZGVudGlhbC90b2tlbiBsb2NhdGlvbnMs"
    "CiAgICB0aGVuIHBlcnNpc3RzIGNvbmZpZy5qc29uIGlmIGFueXRoaW5nIGNoYW5nZWQuCiAgICAiIiIKICAgIGNoYW5nZWQgPSBG"
    "YWxzZQogICAgcGF0aHMgPSBDRkcuc2V0ZGVmYXVsdCgicGF0aHMiLCB7fSkKICAgIGZvciBrZXksIGRlZmF1bHRfcGF0aCBpbiBf"
    "REVGQVVMVF9QQVRIUy5pdGVtcygpOgogICAgICAgIGlmIG5vdCBwYXRocy5nZXQoa2V5KToKICAgICAgICAgICAgcGF0aHNba2V5"
    "XSA9IHN0cihkZWZhdWx0X3BhdGgpCiAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgZ29vZ2xlX2NmZyA9IENGRy5zZXRk"
    "ZWZhdWx0KCJnb29nbGUiLCB7fSkKICAgIGdvb2dsZV9yb290ID0gUGF0aChwYXRocy5nZXQoImdvb2dsZSIsIHN0cihfREVGQVVM"
    "VF9QQVRIU1siZ29vZ2xlIl0pKSkKICAgIGRlZmF1bHRfY3JlZHMgPSBzdHIoZ29vZ2xlX3Jvb3QgLyAiZ29vZ2xlX2NyZWRlbnRp"
    "YWxzLmpzb24iKQogICAgZGVmYXVsdF90b2tlbiA9IHN0cihnb29nbGVfcm9vdCAvICJ0b2tlbi5qc29uIikKICAgIGNyZWRzX3Zh"
    "bCA9IHN0cihnb29nbGVfY2ZnLmdldCgiY3JlZGVudGlhbHMiLCAiIikpLnN0cmlwKCkKICAgIHRva2VuX3ZhbCA9IHN0cihnb29n"
    "bGVfY2ZnLmdldCgidG9rZW4iLCAiIikpLnN0cmlwKCkKICAgIGlmIChub3QgY3JlZHNfdmFsKSBvciAoImNvbmZpZyIgaW4gY3Jl"
    "ZHNfdmFsIGFuZCAiZ29vZ2xlX2NyZWRlbnRpYWxzLmpzb24iIGluIGNyZWRzX3ZhbCk6CiAgICAgICAgZ29vZ2xlX2NmZ1siY3Jl"
    "ZGVudGlhbHMiXSA9IGRlZmF1bHRfY3JlZHMKICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgaWYgbm90IHRva2VuX3ZhbDoKICAg"
    "ICAgICBnb29nbGVfY2ZnWyJ0b2tlbiJdID0gZGVmYXVsdF90b2tlbgogICAgICAgIGNoYW5nZWQgPSBUcnVlCgogICAgaWYgY2hh"
    "bmdlZDoKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCgpkZWYgY2ZnX3BhdGgoa2V5OiBzdHIpIC0+IFBhdGg6CiAgICAiIiJDb252"
    "ZW5pZW5jZTogZ2V0IGEgcGF0aCBmcm9tIENGR1sncGF0aHMnXVtrZXldIGFzIGEgUGF0aCBvYmplY3Qgd2l0aCBzYWZlIGZhbGxi"
    "YWNrIGRlZmF1bHRzLiIiIgogICAgcGF0aHMgPSBDRkcuZ2V0KCJwYXRocyIsIHt9KQogICAgdmFsdWUgPSBwYXRocy5nZXQoa2V5"
    "KQogICAgaWYgdmFsdWU6CiAgICAgICAgcmV0dXJuIFBhdGgodmFsdWUpCiAgICBmYWxsYmFjayA9IF9ERUZBVUxUX1BBVEhTLmdl"
    "dChrZXkpCiAgICBpZiBmYWxsYmFjazoKICAgICAgICBwYXRoc1trZXldID0gc3RyKGZhbGxiYWNrKQogICAgICAgIHJldHVybiBm"
    "YWxsYmFjawogICAgcmV0dXJuIFNDUklQVF9ESVIgLyBrZXkKCl9ub3JtYWxpemVfY29uZmlnX3BhdGhzKCkKCiMg4pSA4pSAIENP"
    "TE9SIENPTlNUQU5UUyDigJQgZGVyaXZlZCBmcm9tIHBlcnNvbmEgdGVtcGxhdGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgQ19QUklNQVJZLCBDX1NFQ09OREFS"
    "WSwgQ19BQ0NFTlQsIENfQkcsIENfUEFORUwsIENfQk9SREVSLAojIENfVEVYVCwgQ19URVhUX0RJTSBhcmUgaW5qZWN0ZWQgYXQg"
    "dGhlIHRvcCBvZiB0aGlzIGZpbGUgYnkgZGVja19idWlsZGVyLgojIEV2ZXJ5dGhpbmcgYmVsb3cgaXMgZGVyaXZlZCBmcm9tIHRo"
    "b3NlIGluamVjdGVkIHZhbHVlcy4KCiMgU2VtYW50aWMgYWxpYXNlcyDigJQgbWFwIHBlcnNvbmEgY29sb3JzIHRvIG5hbWVkIHJv"
    "bGVzIHVzZWQgdGhyb3VnaG91dCB0aGUgVUkKQ19DUklNU09OICAgICA9IENfUFJJTUFSWSAgICAgICAgICAjIG1haW4gYWNjZW50"
    "IChidXR0b25zLCBib3JkZXJzLCBoaWdobGlnaHRzKQpDX0NSSU1TT05fRElNID0gQ19QUklNQVJZICsgIjg4IiAgICMgZGltIGFj"
    "Y2VudCBmb3Igc3VidGxlIGJvcmRlcnMKQ19HT0xEICAgICAgICA9IENfU0VDT05EQVJZICAgICAgICAjIG1haW4gbGFiZWwvdGV4"
    "dC9BSSBvdXRwdXQgY29sb3IKQ19HT0xEX0RJTSAgICA9IENfU0VDT05EQVJZICsgIjg4IiAjIGRpbSBzZWNvbmRhcnkKQ19HT0xE"
    "X0JSSUdIVCA9IENfQUNDRU5UICAgICAgICAgICAjIGVtcGhhc2lzLCBob3ZlciBzdGF0ZXMKQ19TSUxWRVIgICAgICA9IENfVEVY"
    "VF9ESU0gICAgICAgICAjIHNlY29uZGFyeSB0ZXh0IChhbHJlYWR5IGluamVjdGVkKQpDX1NJTFZFUl9ESU0gID0gQ19URVhUX0RJ"
    "TSArICI4OCIgICMgZGltIHNlY29uZGFyeSB0ZXh0CkNfTU9OSVRPUiAgICAgPSBDX0JHICAgICAgICAgICAgICAgIyBjaGF0IGRp"
    "c3BsYXkgYmFja2dyb3VuZCAoYWxyZWFkeSBpbmplY3RlZCkKQ19CRzIgICAgICAgICA9IENfQkcgICAgICAgICAgICAgICAjIHNl"
    "Y29uZGFyeSBiYWNrZ3JvdW5kCkNfQkczICAgICAgICAgPSBDX1BBTkVMICAgICAgICAgICAgIyB0ZXJ0aWFyeS9pbnB1dCBiYWNr"
    "Z3JvdW5kIChhbHJlYWR5IGluamVjdGVkKQpDX0JMT09EICAgICAgID0gJyM4YjAwMDAnICAgICAgICAgICMgZXJyb3Igc3RhdGVz"
    "LCBkYW5nZXIg4oCUIHVuaXZlcnNhbApDX1BVUlBMRSAgICAgID0gJyM4ODU1Y2MnICAgICAgICAgICMgU1lTVEVNIG1lc3NhZ2Vz"
    "IOKAlCB1bml2ZXJzYWwKQ19QVVJQTEVfRElNICA9ICcjMmEwNTJhJyAgICAgICAgICAjIGRpbSBwdXJwbGUg4oCUIHVuaXZlcnNh"
    "bApDX0dSRUVOICAgICAgID0gJyM0NGFhNjYnICAgICAgICAgICMgcG9zaXRpdmUgc3RhdGVzIOKAlCB1bml2ZXJzYWwKQ19CTFVF"
    "ICAgICAgICA9ICcjNDQ4OGNjJyAgICAgICAgICAjIGluZm8gc3RhdGVzIOKAlCB1bml2ZXJzYWwKCiMgRm9udCBoZWxwZXIg4oCU"
    "IGV4dHJhY3RzIHByaW1hcnkgZm9udCBuYW1lIGZvciBRRm9udCgpIGNhbGxzCkRFQ0tfRk9OVCA9IFVJX0ZPTlRfRkFNSUxZLnNw"
    "bGl0KCcsJylbMF0uc3RyaXAoKS5zdHJpcCgiJyIpCgojIEVtb3Rpb24g4oaSIGNvbG9yIG1hcHBpbmcgKGZvciBlbW90aW9uIHJl"
    "Y29yZCBjaGlwcykKRU1PVElPTl9DT0xPUlM6IGRpY3Rbc3RyLCBzdHJdID0gewogICAgInZpY3RvcnkiOiAgICBDX0dPTEQsCiAg"
    "ICAic211ZyI6ICAgICAgIENfR09MRCwKICAgICJpbXByZXNzZWQiOiAgQ19HT0xELAogICAgInJlbGlldmVkIjogICBDX0dPTEQs"
    "CiAgICAiaGFwcHkiOiAgICAgIENfR09MRCwKICAgICJmbGlydHkiOiAgICAgQ19HT0xELAogICAgInBhbmlja2VkIjogICBDX0NS"
    "SU1TT04sCiAgICAiYW5ncnkiOiAgICAgIENfQ1JJTVNPTiwKICAgICJzaG9ja2VkIjogICAgQ19DUklNU09OLAogICAgImNoZWF0"
    "bW9kZSI6ICBDX0NSSU1TT04sCiAgICAiY29uY2VybmVkIjogICIjY2M2NjIyIiwKICAgICJzYWQiOiAgICAgICAgIiNjYzY2MjIi"
    "LAogICAgImh1bWlsaWF0ZWQiOiAiI2NjNjYyMiIsCiAgICAiZmx1c3RlcmVkIjogICIjY2M2NjIyIiwKICAgICJwbG90dGluZyI6"
    "ICAgQ19QVVJQTEUsCiAgICAic3VzcGljaW91cyI6IENfUFVSUExFLAogICAgImVudmlvdXMiOiAgICBDX1BVUlBMRSwKICAgICJm"
    "b2N1c2VkIjogICAgQ19TSUxWRVIsCiAgICAiYWxlcnQiOiAgICAgIENfU0lMVkVSLAogICAgIm5ldXRyYWwiOiAgICBDX1RFWFRf"
    "RElNLAp9CgojIOKUgOKUgCBERUNPUkFUSVZFIENPTlNUQU5UUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBSVU5FUyBpcyBzb3VyY2VkIGZyb20g"
    "VUlfUlVORVMgaW5qZWN0ZWQgYnkgdGhlIHBlcnNvbmEgdGVtcGxhdGUKUlVORVMgPSBVSV9SVU5FUwoKIyBGYWNlIGltYWdlIG1h"
    "cCDigJQgcHJlZml4IGZyb20gRkFDRV9QUkVGSVgsIGZpbGVzIGxpdmUgaW4gY29uZmlnIHBhdGhzLmZhY2VzCkZBQ0VfRklMRVM6"
    "IGRpY3Rbc3RyLCBzdHJdID0gewogICAgIm5ldXRyYWwiOiAgICBmIntGQUNFX1BSRUZJWH1fTmV1dHJhbC5wbmciLAogICAgImFs"
    "ZXJ0IjogICAgICBmIntGQUNFX1BSRUZJWH1fQWxlcnQucG5nIiwKICAgICJmb2N1c2VkIjogICAgZiJ7RkFDRV9QUkVGSVh9X0Zv"
    "Y3VzZWQucG5nIiwKICAgICJzbXVnIjogICAgICAgZiJ7RkFDRV9QUkVGSVh9X1NtdWcucG5nIiwKICAgICJjb25jZXJuZWQiOiAg"
    "ZiJ7RkFDRV9QUkVGSVh9X0NvbmNlcm5lZC5wbmciLAogICAgInNhZCI6ICAgICAgICBmIntGQUNFX1BSRUZJWH1fU2FkX0NyeWlu"
    "Zy5wbmciLAogICAgInJlbGlldmVkIjogICBmIntGQUNFX1BSRUZJWH1fUmVsaWV2ZWQucG5nIiwKICAgICJpbXByZXNzZWQiOiAg"
    "ZiJ7RkFDRV9QUkVGSVh9X0ltcHJlc3NlZC5wbmciLAogICAgInZpY3RvcnkiOiAgICBmIntGQUNFX1BSRUZJWH1fVmljdG9yeS5w"
    "bmciLAogICAgImh1bWlsaWF0ZWQiOiBmIntGQUNFX1BSRUZJWH1fSHVtaWxpYXRlZC5wbmciLAogICAgInN1c3BpY2lvdXMiOiBm"
    "IntGQUNFX1BSRUZJWH1fU3VzcGljaW91cy5wbmciLAogICAgInBhbmlja2VkIjogICBmIntGQUNFX1BSRUZJWH1fUGFuaWNrZWQu"
    "cG5nIiwKICAgICJjaGVhdG1vZGUiOiAgZiJ7RkFDRV9QUkVGSVh9X0NoZWF0X01vZGUucG5nIiwKICAgICJhbmdyeSI6ICAgICAg"
    "ZiJ7RkFDRV9QUkVGSVh9X0FuZ3J5LnBuZyIsCiAgICAicGxvdHRpbmciOiAgIGYie0ZBQ0VfUFJFRklYfV9QbG90dGluZy5wbmci"
    "LAogICAgInNob2NrZWQiOiAgICBmIntGQUNFX1BSRUZJWH1fU2hvY2tlZC5wbmciLAogICAgImhhcHB5IjogICAgICBmIntGQUNF"
    "X1BSRUZJWH1fSGFwcHkucG5nIiwKICAgICJmbGlydHkiOiAgICAgZiJ7RkFDRV9QUkVGSVh9X0ZsaXJ0eS5wbmciLAogICAgImZs"
    "dXN0ZXJlZCI6ICBmIntGQUNFX1BSRUZJWH1fRmx1c3RlcmVkLnBuZyIsCiAgICAiZW52aW91cyI6ICAgIGYie0ZBQ0VfUFJFRklY"
    "fV9FbnZpb3VzLnBuZyIsCn0KClNFTlRJTUVOVF9MSVNUID0gKAogICAgIm5ldXRyYWwsIGFsZXJ0LCBmb2N1c2VkLCBzbXVnLCBj"
    "b25jZXJuZWQsIHNhZCwgcmVsaWV2ZWQsIGltcHJlc3NlZCwgIgogICAgInZpY3RvcnksIGh1bWlsaWF0ZWQsIHN1c3BpY2lvdXMs"
    "IHBhbmlja2VkLCBhbmdyeSwgcGxvdHRpbmcsIHNob2NrZWQsICIKICAgICJoYXBweSwgZmxpcnR5LCBmbHVzdGVyZWQsIGVudmlv"
    "dXMiCikKCiMg4pSA4pSAIFNZU1RFTSBQUk9NUFQg4oCUIGluamVjdGVkIGZyb20gcGVyc29uYSB0ZW1wbGF0ZSBhdCB0b3Agb2Yg"
    "ZmlsZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBTWVNURU1fUFJPTVBUX0JBU0UgaXMgYWxyZWFk"
    "eSBkZWZpbmVkIGFib3ZlIGZyb20gPDw8U1lTVEVNX1BST01QVD4+PiBpbmplY3Rpb24uCiMgRG8gbm90IHJlZGVmaW5lIGl0IGhl"
    "cmUuCgojIOKUgOKUgCBHTE9CQUwgU1RZTEVTSEVFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKU1RZTEUgPSBmIiIiClFNYWluV2lu"
    "ZG93LCBRV2lkZ2V0IHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19CR307CiAgICBjb2xvcjoge0NfR09MRH07CiAgICBmb250"
    "LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKfX0KUVRleHRFZGl0IHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19NT05JVE9S"
    "fTsKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIGJvcmRlci1y"
    "YWRpdXM6IDJweDsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9OwogICAgZm9udC1zaXplOiAxMnB4OwogICAgcGFk"
    "ZGluZzogOHB4OwogICAgc2VsZWN0aW9uLWJhY2tncm91bmQtY29sb3I6IHtDX0NSSU1TT05fRElNfTsKfX0KUUxpbmVFZGl0IHt7"
    "CiAgICBiYWNrZ3JvdW5kLWNvbG9yOiB7Q19CRzN9OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQg"
    "e0NfQ1JJTVNPTn07CiAgICBib3JkZXItcmFkaXVzOiAycHg7CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKICAg"
    "IGZvbnQtc2l6ZTogMTNweDsKICAgIHBhZGRpbmc6IDhweCAxMnB4Owp9fQpRTGluZUVkaXQ6Zm9jdXMge3sKICAgIGJvcmRlcjog"
    "MXB4IHNvbGlkIHtDX0dPTER9OwogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfUEFORUx9Owp9fQpRUHVzaEJ1dHRvbiB7ewogICAg"
    "YmFja2dyb3VuZC1jb2xvcjoge0NfQ1JJTVNPTl9ESU19OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29s"
    "aWQge0NfQ1JJTVNPTn07CiAgICBib3JkZXItcmFkaXVzOiAycHg7CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsK"
    "ICAgIGZvbnQtc2l6ZTogMTJweDsKICAgIGZvbnQtd2VpZ2h0OiBib2xkOwogICAgcGFkZGluZzogOHB4IDIwcHg7CiAgICBsZXR0"
    "ZXItc3BhY2luZzogMnB4Owp9fQpRUHVzaEJ1dHRvbjpob3ZlciB7ewogICAgYmFja2dyb3VuZC1jb2xvcjoge0NfQ1JJTVNPTn07"
    "CiAgICBjb2xvcjoge0NfR09MRF9CUklHSFR9Owp9fQpRUHVzaEJ1dHRvbjpwcmVzc2VkIHt7CiAgICBiYWNrZ3JvdW5kLWNvbG9y"
    "OiB7Q19CTE9PRH07CiAgICBib3JkZXItY29sb3I6IHtDX0JMT09EfTsKICAgIGNvbG9yOiB7Q19URVhUfTsKfX0KUVB1c2hCdXR0"
    "b246ZGlzYWJsZWQge3sKICAgIGJhY2tncm91bmQtY29sb3I6IHtDX0JHM307CiAgICBjb2xvcjoge0NfVEVYVF9ESU19OwogICAg"
    "Ym9yZGVyLWNvbG9yOiB7Q19URVhUX0RJTX07Cn19ClFTY3JvbGxCYXI6dmVydGljYWwge3sKICAgIGJhY2tncm91bmQ6IHtDX0JH"
    "fTsKICAgIHdpZHRoOiA2cHg7CiAgICBib3JkZXI6IG5vbmU7Cn19ClFTY3JvbGxCYXI6OmhhbmRsZTp2ZXJ0aWNhbCB7ewogICAg"
    "YmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OwogICAgYm9yZGVyLXJhZGl1czogM3B4Owp9fQpRU2Nyb2xsQmFyOjpoYW5kbGU6"
    "dmVydGljYWw6aG92ZXIge3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT059Owp9fQpRU2Nyb2xsQmFyOjphZGQtbGluZTp2ZXJ0"
    "aWNhbCwgUVNjcm9sbEJhcjo6c3ViLWxpbmU6dmVydGljYWwge3sKICAgIGhlaWdodDogMHB4Owp9fQpRVGFiV2lkZ2V0OjpwYW5l"
    "IHt7CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzJ9Owp9fQpRVGFi"
    "QmFyOjp0YWIge3sKICAgIGJhY2tncm91bmQ6IHtDX0JHM307CiAgICBjb2xvcjoge0NfVEVYVF9ESU19OwogICAgYm9yZGVyOiAx"
    "cHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgcGFkZGluZzogNnB4IDE0cHg7CiAgICBmb250LWZhbWlseToge1VJX0ZPTlRf"
    "RkFNSUxZfTsKICAgIGZvbnQtc2l6ZTogMTBweDsKICAgIGxldHRlci1zcGFjaW5nOiAxcHg7Cn19ClFUYWJCYXI6OnRhYjpzZWxl"
    "Y3RlZCB7ewogICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OwogICAgY29sb3I6IHtDX0dPTER9OwogICAgYm9yZGVyLWJv"
    "dHRvbTogMnB4IHNvbGlkIHtDX0NSSU1TT059Owp9fQpRVGFiQmFyOjp0YWI6aG92ZXIge3sKICAgIGJhY2tncm91bmQ6IHtDX1BB"
    "TkVMfTsKICAgIGNvbG9yOiB7Q19HT0xEX0RJTX07Cn19ClFUYWJsZVdpZGdldCB7ewogICAgYmFja2dyb3VuZDoge0NfQkcyfTsK"
    "ICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsKICAgIGdyaWRsaW5lLWNv"
    "bG9yOiB7Q19CT1JERVJ9OwogICAgZm9udC1mYW1pbHk6IHtVSV9GT05UX0ZBTUlMWX07CiAgICBmb250LXNpemU6IDExcHg7Cn19"
    "ClFUYWJsZVdpZGdldDo6aXRlbTpzZWxlY3RlZCB7ewogICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OwogICAgY29sb3I6"
    "IHtDX0dPTERfQlJJR0hUfTsKfX0KUUhlYWRlclZpZXc6OnNlY3Rpb24ge3sKICAgIGJhY2tncm91bmQ6IHtDX0JHM307CiAgICBj"
    "b2xvcjoge0NfR09MRH07CiAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICBwYWRkaW5nOiA0cHg7CiAg"
    "ICBmb250LWZhbWlseToge1VJX0ZPTlRfRkFNSUxZfTsKICAgIGZvbnQtc2l6ZTogMTBweDsKICAgIGZvbnQtd2VpZ2h0OiBib2xk"
    "OwogICAgbGV0dGVyLXNwYWNpbmc6IDFweDsKfX0KUUNvbWJvQm94IHt7CiAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgY29s"
    "b3I6IHtDX0dPTER9OwogICAgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OwogICAgcGFkZGluZzogNHB4IDhweDsK"
    "ICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9Owp9fQpRQ29tYm9Cb3g6OmRyb3AtZG93biB7ewogICAgYm9yZGVyOiBu"
    "b25lOwp9fQpRQ2hlY2tCb3gge3sKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGZvbnQtZmFtaWx5OiB7VUlfRk9OVF9GQU1JTFl9"
    "Owp9fQpRTGFiZWwge3sKICAgIGNvbG9yOiB7Q19HT0xEfTsKICAgIGJvcmRlcjogbm9uZTsKfX0KUVNwbGl0dGVyOjpoYW5kbGUg"
    "e3sKICAgIGJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsKICAgIHdpZHRoOiAycHg7Cn19CiIiIgoKIyDilIDilIAgRElSRUNU"
    "T1JZIEJPT1RTVFJBUCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGJvb3RzdHJhcF9kaXJlY3RvcmllcygpIC0+IE5vbmU6CiAgICAiIiIK"
    "ICAgIENyZWF0ZSBhbGwgcmVxdWlyZWQgZGlyZWN0b3JpZXMgaWYgdGhleSBkb24ndCBleGlzdC4KICAgIENhbGxlZCBvbiBzdGFy"
    "dHVwIGJlZm9yZSBhbnl0aGluZyBlbHNlLiBTYWZlIHRvIGNhbGwgbXVsdGlwbGUgdGltZXMuCiAgICBBbHNvIG1pZ3JhdGVzIGZp"
    "bGVzIGZyb20gb2xkIFtEZWNrTmFtZV1fTWVtb3JpZXMgbGF5b3V0IGlmIGRldGVjdGVkLgogICAgIiIiCiAgICBkaXJzID0gWwog"
    "ICAgICAgIGNmZ19wYXRoKCJmYWNlcyIpLAogICAgICAgIGNmZ19wYXRoKCJzb3VuZHMiKSwKICAgICAgICBjZmdfcGF0aCgibWVt"
    "b3JpZXMiKSwKICAgICAgICBjZmdfcGF0aCgic2Vzc2lvbnMiKSwKICAgICAgICBjZmdfcGF0aCgic2wiKSwKICAgICAgICBjZmdf"
    "cGF0aCgiZXhwb3J0cyIpLAogICAgICAgIGNmZ19wYXRoKCJsb2dzIiksCiAgICAgICAgY2ZnX3BhdGgoImJhY2t1cHMiKSwKICAg"
    "ICAgICBjZmdfcGF0aCgicGVyc29uYXMiKSwKICAgICAgICBjZmdfcGF0aCgiZ29vZ2xlIiksCiAgICAgICAgY2ZnX3BhdGgoImdv"
    "b2dsZSIpIC8gImV4cG9ydHMiLAogICAgXQogICAgZm9yIGQgaW4gZGlyczoKICAgICAgICBkLm1rZGlyKHBhcmVudHM9VHJ1ZSwg"
    "ZXhpc3Rfb2s9VHJ1ZSkKCiAgICAjIENyZWF0ZSBlbXB0eSBKU09OTCBmaWxlcyBpZiB0aGV5IGRvbid0IGV4aXN0CiAgICBtZW1v"
    "cnlfZGlyID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikKICAgIGZvciBmbmFtZSBpbiAoIm1lc3NhZ2VzLmpzb25sIiwgIm1lbW9yaWVz"
    "Lmpzb25sIiwgInRhc2tzLmpzb25sIiwKICAgICAgICAgICAgICAgICAgImxlc3NvbnNfbGVhcm5lZC5qc29ubCIsICJwZXJzb25h"
    "X2hpc3RvcnkuanNvbmwiKToKICAgICAgICBmcCA9IG1lbW9yeV9kaXIgLyBmbmFtZQogICAgICAgIGlmIG5vdCBmcC5leGlzdHMo"
    "KToKICAgICAgICAgICAgZnAud3JpdGVfdGV4dCgiIiwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBzbF9kaXIgPSBjZmdfcGF0aCgi"
    "c2wiKQogICAgZm9yIGZuYW1lIGluICgic2xfc2NhbnMuanNvbmwiLCAic2xfY29tbWFuZHMuanNvbmwiKToKICAgICAgICBmcCA9"
    "IHNsX2RpciAvIGZuYW1lCiAgICAgICAgaWYgbm90IGZwLmV4aXN0cygpOgogICAgICAgICAgICBmcC53cml0ZV90ZXh0KCIiLCBl"
    "bmNvZGluZz0idXRmLTgiKQoKICAgIHNlc3Npb25zX2RpciA9IGNmZ19wYXRoKCJzZXNzaW9ucyIpCiAgICBpZHggPSBzZXNzaW9u"
    "c19kaXIgLyAic2Vzc2lvbl9pbmRleC5qc29uIgogICAgaWYgbm90IGlkeC5leGlzdHMoKToKICAgICAgICBpZHgud3JpdGVfdGV4"
    "dChqc29uLmR1bXBzKHsic2Vzc2lvbnMiOiBbXX0sIGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBzdGF0ZV9wYXRo"
    "ID0gbWVtb3J5X2RpciAvICJzdGF0ZS5qc29uIgogICAgaWYgbm90IHN0YXRlX3BhdGguZXhpc3RzKCk6CiAgICAgICAgX3dyaXRl"
    "X2RlZmF1bHRfc3RhdGUoc3RhdGVfcGF0aCkKCiAgICBpbmRleF9wYXRoID0gbWVtb3J5X2RpciAvICJpbmRleC5qc29uIgogICAg"
    "aWYgbm90IGluZGV4X3BhdGguZXhpc3RzKCk6CiAgICAgICAgaW5kZXhfcGF0aC53cml0ZV90ZXh0KAogICAgICAgICAgICBqc29u"
    "LmR1bXBzKHsidmVyc2lvbiI6IEFQUF9WRVJTSU9OLCAidG90YWxfbWVzc2FnZXMiOiAwLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAidG90YWxfbWVtb3JpZXMiOiAwfSwgaW5kZW50PTIpLAogICAgICAgICAgICBlbmNvZGluZz0idXRmLTgiCiAgICAgICAgKQoK"
    "ICAgICMgTGVnYWN5IG1pZ3JhdGlvbjogaWYgb2xkIE1vcmdhbm5hX01lbW9yaWVzIGZvbGRlciBleGlzdHMsIG1pZ3JhdGUgZmls"
    "ZXMKICAgIF9taWdyYXRlX2xlZ2FjeV9maWxlcygpCgpkZWYgX3dyaXRlX2RlZmF1bHRfc3RhdGUocGF0aDogUGF0aCkgLT4gTm9u"
    "ZToKICAgIHN0YXRlID0gewogICAgICAgICJwZXJzb25hX25hbWUiOiBERUNLX05BTUUsCiAgICAgICAgImRlY2tfdmVyc2lvbiI6"
    "IEFQUF9WRVJTSU9OLAogICAgICAgICJzZXNzaW9uX2NvdW50IjogMCwKICAgICAgICAibGFzdF9zdGFydHVwIjogTm9uZSwKICAg"
    "ICAgICAibGFzdF9zaHV0ZG93biI6IE5vbmUsCiAgICAgICAgImxhc3RfYWN0aXZlIjogTm9uZSwKICAgICAgICAidG90YWxfbWVz"
    "c2FnZXMiOiAwLAogICAgICAgICJ0b3RhbF9tZW1vcmllcyI6IDAsCiAgICAgICAgImludGVybmFsX25hcnJhdGl2ZSI6IHt9LAog"
    "ICAgICAgICJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3duIjogIkRPUk1BTlQiLAogICAgfQogICAgcGF0aC53cml0ZV90ZXh0KGpz"
    "b24uZHVtcHMoc3RhdGUsIGluZGVudD0yKSwgZW5jb2Rpbmc9InV0Zi04IikKCmRlZiBfbWlncmF0ZV9sZWdhY3lfZmlsZXMoKSAt"
    "PiBOb25lOgogICAgIiIiCiAgICBJZiBvbGQgRDpcXEFJXFxNb2RlbHNcXFtEZWNrTmFtZV1fTWVtb3JpZXMgbGF5b3V0IGlzIGRl"
    "dGVjdGVkLAogICAgbWlncmF0ZSBmaWxlcyB0byBuZXcgc3RydWN0dXJlIHNpbGVudGx5LgogICAgIiIiCiAgICAjIFRyeSB0byBm"
    "aW5kIG9sZCBsYXlvdXQgcmVsYXRpdmUgdG8gbW9kZWwgcGF0aAogICAgbW9kZWxfcGF0aCA9IFBhdGgoQ0ZHWyJtb2RlbCJdLmdl"
    "dCgicGF0aCIsICIiKSkKICAgIGlmIG5vdCBtb2RlbF9wYXRoLmV4aXN0cygpOgogICAgICAgIHJldHVybgogICAgb2xkX3Jvb3Qg"
    "PSBtb2RlbF9wYXRoLnBhcmVudCAvIGYie0RFQ0tfTkFNRX1fTWVtb3JpZXMiCiAgICBpZiBub3Qgb2xkX3Jvb3QuZXhpc3RzKCk6"
    "CiAgICAgICAgcmV0dXJuCgogICAgbWlncmF0aW9ucyA9IFsKICAgICAgICAob2xkX3Jvb3QgLyAibWVtb3JpZXMuanNvbmwiLCAg"
    "ICAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAibWVtb3JpZXMuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAibWVz"
    "c2FnZXMuanNvbmwiLCAgICAgICAgICAgIGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gIm1lc3NhZ2VzLmpzb25sIiksCiAgICAgICAg"
    "KG9sZF9yb290IC8gInRhc2tzLmpzb25sIiwgICAgICAgICAgICAgICBjZmdfcGF0aCgibWVtb3JpZXMiKSAvICJ0YXNrcy5qc29u"
    "bCIpLAogICAgICAgIChvbGRfcm9vdCAvICJzdGF0ZS5qc29uIiwgICAgICAgICAgICAgICAgY2ZnX3BhdGgoIm1lbW9yaWVzIikg"
    "LyAic3RhdGUuanNvbiIpLAogICAgICAgIChvbGRfcm9vdCAvICJpbmRleC5qc29uIiwgICAgICAgICAgICAgICAgY2ZnX3BhdGgo"
    "Im1lbW9yaWVzIikgLyAiaW5kZXguanNvbiIpLAogICAgICAgIChvbGRfcm9vdCAvICJzbF9zY2Fucy5qc29ubCIsICAgICAgICAg"
    "ICAgY2ZnX3BhdGgoInNsIikgLyAic2xfc2NhbnMuanNvbmwiKSwKICAgICAgICAob2xkX3Jvb3QgLyAic2xfY29tbWFuZHMuanNv"
    "bmwiLCAgICAgICAgIGNmZ19wYXRoKCJzbCIpIC8gInNsX2NvbW1hbmRzLmpzb25sIiksCiAgICAgICAgKG9sZF9yb290IC8gImdv"
    "b2dsZSIgLyAidG9rZW4uanNvbiIsICAgICBQYXRoKENGR1siZ29vZ2xlIl1bInRva2VuIl0pKSwKICAgICAgICAob2xkX3Jvb3Qg"
    "LyAiY29uZmlnIiAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgUGF0aChDRkdbImdvb2dsZSJdWyJjcmVkZW50aWFscyJdKSksCiAgICAgICAgKG9sZF9yb290IC8gInNv"
    "dW5kcyIgLyBmIntTT1VORF9QUkVGSVh9X2FsZXJ0LndhdiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgY2ZnX3BhdGgoInNvdW5kcyIpIC8gZiJ7U09VTkRfUFJFRklYfV9hbGVydC53YXYiKSwKICAgIF0KCiAgICBm"
    "b3Igc3JjLCBkc3QgaW4gbWlncmF0aW9uczoKICAgICAgICBpZiBzcmMuZXhpc3RzKCkgYW5kIG5vdCBkc3QuZXhpc3RzKCk6CiAg"
    "ICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGRzdC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVl"
    "KQogICAgICAgICAgICAgICAgaW1wb3J0IHNodXRpbAogICAgICAgICAgICAgICAgc2h1dGlsLmNvcHkyKHN0cihzcmMpLCBzdHIo"
    "ZHN0KSkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAjIE1pZ3JhdGUgZmFj"
    "ZSBpbWFnZXMKICAgIG9sZF9mYWNlcyA9IG9sZF9yb290IC8gIkZhY2VzIgogICAgbmV3X2ZhY2VzID0gY2ZnX3BhdGgoImZhY2Vz"
    "IikKICAgIGlmIG9sZF9mYWNlcy5leGlzdHMoKToKICAgICAgICBmb3IgaW1nIGluIG9sZF9mYWNlcy5nbG9iKCIqLnBuZyIpOgog"
    "ICAgICAgICAgICBkc3QgPSBuZXdfZmFjZXMgLyBpbWcubmFtZQogICAgICAgICAgICBpZiBub3QgZHN0LmV4aXN0cygpOgogICAg"
    "ICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgIGltcG9ydCBzaHV0aWwKICAgICAgICAgICAgICAgICAgICBzaHV0"
    "aWwuY29weTIoc3RyKGltZyksIHN0cihkc3QpKQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAg"
    "ICAgICAgICBwYXNzCgojIOKUgOKUgCBEQVRFVElNRSBIRUxQRVJTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgbG9jYWxf"
    "bm93X2lzbygpIC0+IHN0cjoKICAgIHJldHVybiBkYXRldGltZS5ub3coKS5yZXBsYWNlKG1pY3Jvc2Vjb25kPTApLmlzb2Zvcm1h"
    "dCgpCgpkZWYgcGFyc2VfaXNvKHZhbHVlOiBzdHIpIC0+IE9wdGlvbmFsW2RhdGV0aW1lXToKICAgIGlmIG5vdCB2YWx1ZToKICAg"
    "ICAgICByZXR1cm4gTm9uZQogICAgdmFsdWUgPSB2YWx1ZS5zdHJpcCgpCiAgICB0cnk6CiAgICAgICAgaWYgdmFsdWUuZW5kc3dp"
    "dGgoIloiKToKICAgICAgICAgICAgcmV0dXJuIGRhdGV0aW1lLmZyb21pc29mb3JtYXQodmFsdWVbOi0xXSkucmVwbGFjZSh0emlu"
    "Zm89dGltZXpvbmUudXRjKQogICAgICAgIHJldHVybiBkYXRldGltZS5mcm9taXNvZm9ybWF0KHZhbHVlKQogICAgZXhjZXB0IEV4"
    "Y2VwdGlvbjoKICAgICAgICByZXR1cm4gTm9uZQoKX0RBVEVUSU1FX05PUk1BTElaQVRJT05fTE9HR0VEOiBzZXRbdHVwbGVdID0g"
    "c2V0KCkKCgpkZWYgX3Jlc29sdmVfZGVja190aW1lem9uZV9uYW1lKCkgLT4gT3B0aW9uYWxbc3RyXToKICAgIHNldHRpbmdzID0g"
    "Q0ZHLmdldCgic2V0dGluZ3MiLCB7fSkgaWYgaXNpbnN0YW5jZShDRkcsIGRpY3QpIGVsc2Uge30KICAgIGF1dG9fZGV0ZWN0ID0g"
    "Ym9vbChzZXR0aW5ncy5nZXQoInRpbWV6b25lX2F1dG9fZGV0ZWN0IiwgVHJ1ZSkpCiAgICBvdmVycmlkZSA9IHN0cihzZXR0aW5n"
    "cy5nZXQoInRpbWV6b25lX292ZXJyaWRlIiwgIiIpIG9yICIiKS5zdHJpcCgpCiAgICBpZiBub3QgYXV0b19kZXRlY3QgYW5kIG92"
    "ZXJyaWRlOgogICAgICAgIHJldHVybiBvdmVycmlkZQogICAgbG9jYWxfdHppbmZvID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9u"
    "ZSgpLnR6aW5mbwogICAgaWYgbG9jYWxfdHppbmZvIGlzIG5vdCBOb25lOgogICAgICAgIHR6X2tleSA9IGdldGF0dHIobG9jYWxf"
    "dHppbmZvLCAia2V5IiwgTm9uZSkKICAgICAgICBpZiB0el9rZXk6CiAgICAgICAgICAgIHJldHVybiBzdHIodHpfa2V5KQogICAg"
    "ICAgIHR6X25hbWUgPSBzdHIobG9jYWxfdHppbmZvKQogICAgICAgIGlmIHR6X25hbWUgYW5kIHR6X25hbWUudXBwZXIoKSAhPSAi"
    "TE9DQUwiOgogICAgICAgICAgICByZXR1cm4gdHpfbmFtZQogICAgcmV0dXJuIE5vbmUKCgpkZWYgX2xvY2FsX3R6aW5mbygpOgog"
    "ICAgdHpfbmFtZSA9IF9yZXNvbHZlX2RlY2tfdGltZXpvbmVfbmFtZSgpCiAgICBpZiB0el9uYW1lOgogICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgcmV0dXJuIFpvbmVJbmZvKHR6X25hbWUpCiAgICAgICAgZXhjZXB0IFpvbmVJbmZvTm90Rm91bmRFcnJvcjoKICAg"
    "ICAgICAgICAgX2Vhcmx5X2xvZyhmIltEQVRFVElNRV1bV0FSTl0gVW5rbm93biB0aW1lem9uZSBvdmVycmlkZSAne3R6X25hbWV9"
    "JywgdXNpbmcgc3lzdGVtIGxvY2FsIHRpbWV6b25lLiIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFz"
    "cwogICAgcmV0dXJuIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS50emluZm8gb3IgdGltZXpvbmUudXRjCgoKZGVmIG5vd19m"
    "b3JfY29tcGFyZSgpOgogICAgcmV0dXJuIGRhdGV0aW1lLm5vdyhfbG9jYWxfdHppbmZvKCkpCgoKZGVmIG5vcm1hbGl6ZV9kYXRl"
    "dGltZV9mb3JfY29tcGFyZShkdF92YWx1ZSwgY29udGV4dDogc3RyID0gIiIpOgogICAgaWYgZHRfdmFsdWUgaXMgTm9uZToKICAg"
    "ICAgICByZXR1cm4gTm9uZQogICAgaWYgbm90IGlzaW5zdGFuY2UoZHRfdmFsdWUsIGRhdGV0aW1lKToKICAgICAgICByZXR1cm4g"
    "Tm9uZQogICAgbG9jYWxfdHogPSBfbG9jYWxfdHppbmZvKCkKICAgIGlmIGR0X3ZhbHVlLnR6aW5mbyBpcyBOb25lOgogICAgICAg"
    "IG5vcm1hbGl6ZWQgPSBkdF92YWx1ZS5yZXBsYWNlKHR6aW5mbz1sb2NhbF90eikKICAgICAgICBrZXkgPSAoIm5haXZlIiwgY29u"
    "dGV4dCkKICAgICAgICBpZiBrZXkgbm90IGluIF9EQVRFVElNRV9OT1JNQUxJWkFUSU9OX0xPR0dFRDoKICAgICAgICAgICAgX2Vh"
    "cmx5X2xvZygKICAgICAgICAgICAgICAgIGYiW0RBVEVUSU1FXVtJTkZPXSBOb3JtYWxpemVkIG5haXZlIGRhdGV0aW1lIHRvIGxv"
    "Y2FsIHRpbWV6b25lIGZvciB7Y29udGV4dCBvciAnZ2VuZXJhbCd9IGNvbXBhcmlzb25zLiIKICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICBfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQuYWRkKGtleSkKICAgICAgICByZXR1cm4gbm9ybWFsaXplZAogICAg"
    "bm9ybWFsaXplZCA9IGR0X3ZhbHVlLmFzdGltZXpvbmUobG9jYWxfdHopCiAgICBkdF90el9uYW1lID0gc3RyKGR0X3ZhbHVlLnR6"
    "aW5mbykKICAgIGtleSA9ICgiYXdhcmUiLCBjb250ZXh0LCBkdF90el9uYW1lKQogICAgaWYga2V5IG5vdCBpbiBfREFURVRJTUVf"
    "Tk9STUFMSVpBVElPTl9MT0dHRUQgYW5kIGR0X3R6X25hbWUgbm90IGluIHsiVVRDIiwgc3RyKGxvY2FsX3R6KX06CiAgICAgICAg"
    "X2Vhcmx5X2xvZygKICAgICAgICAgICAgZiJbREFURVRJTUVdW0lORk9dIE5vcm1hbGl6ZWQgdGltZXpvbmUtYXdhcmUgZGF0ZXRp"
    "bWUgZnJvbSB7ZHRfdHpfbmFtZX0gdG8gbG9jYWwgdGltZXpvbmUgZm9yIHtjb250ZXh0IG9yICdnZW5lcmFsJ30gY29tcGFyaXNv"
    "bnMuIgogICAgICAgICkKICAgICAgICBfREFURVRJTUVfTk9STUFMSVpBVElPTl9MT0dHRUQuYWRkKGtleSkKICAgIHJldHVybiBu"
    "b3JtYWxpemVkCgoKZGVmIHBhcnNlX2lzb19mb3JfY29tcGFyZSh2YWx1ZSwgY29udGV4dDogc3RyID0gIiIpOgogICAgcmV0dXJu"
    "IG5vcm1hbGl6ZV9kYXRldGltZV9mb3JfY29tcGFyZShwYXJzZV9pc28odmFsdWUpLCBjb250ZXh0PWNvbnRleHQpCgoKZGVmIF90"
    "YXNrX2R1ZV9zb3J0X2tleSh0YXNrOiBkaWN0KToKICAgIGR1ZSA9IHBhcnNlX2lzb19mb3JfY29tcGFyZSgodGFzayBvciB7fSku"
    "Z2V0KCJkdWVfYXQiKSBvciAodGFzayBvciB7fSkuZ2V0KCJkdWUiKSwgY29udGV4dD0idGFza19zb3J0IikKICAgIGlmIGR1ZSBp"
    "cyBOb25lOgogICAgICAgIHJldHVybiAoMSwgZGF0ZXRpbWUubWF4LnJlcGxhY2UodHppbmZvPXRpbWV6b25lLnV0YykpCiAgICBy"
    "ZXR1cm4gKDAsIGR1ZS5hc3RpbWV6b25lKHRpbWV6b25lLnV0YyksICgodGFzayBvciB7fSkuZ2V0KCJ0ZXh0Iikgb3IgIiIpLmxv"
    "d2VyKCkpCgoKZGVmIGZvcm1hdF9kdXJhdGlvbihzZWNvbmRzOiBmbG9hdCkgLT4gc3RyOgogICAgdG90YWwgPSBtYXgoMCwgaW50"
    "KHNlY29uZHMpKQogICAgZGF5cywgcmVtID0gZGl2bW9kKHRvdGFsLCA4NjQwMCkKICAgIGhvdXJzLCByZW0gPSBkaXZtb2QocmVt"
    "LCAzNjAwKQogICAgbWludXRlcywgc2VjcyA9IGRpdm1vZChyZW0sIDYwKQogICAgcGFydHMgPSBbXQogICAgaWYgZGF5czogICAg"
    "cGFydHMuYXBwZW5kKGYie2RheXN9ZCIpCiAgICBpZiBob3VyczogICBwYXJ0cy5hcHBlbmQoZiJ7aG91cnN9aCIpCiAgICBpZiBt"
    "aW51dGVzOiBwYXJ0cy5hcHBlbmQoZiJ7bWludXRlc31tIikKICAgIGlmIG5vdCBwYXJ0czogcGFydHMuYXBwZW5kKGYie3NlY3N9"
    "cyIpCiAgICByZXR1cm4gIiAiLmpvaW4ocGFydHNbOjNdKQoKIyDilIDilIAgTU9PTiBQSEFTRSBIRUxQRVJTIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAojIENvcnJlY3RlZCBpbGx1bWluYXRpb24gbWF0aCDigJQgZGlzcGxheWVkIG1vb24gbWF0Y2hlcyBsYWJlbGVkIHBo"
    "YXNlLgoKX0tOT1dOX05FV19NT09OID0gZGF0ZSgyMDAwLCAxLCA2KQpfTFVOQVJfQ1lDTEUgICAgPSAyOS41MzA1ODg2NwoKZGVm"
    "IGdldF9tb29uX3BoYXNlKCkgLT4gdHVwbGVbZmxvYXQsIHN0ciwgZmxvYXRdOgogICAgIiIiCiAgICBSZXR1cm5zIChwaGFzZV9m"
    "cmFjdGlvbiwgcGhhc2VfbmFtZSwgaWxsdW1pbmF0aW9uX3BjdCkuCiAgICBwaGFzZV9mcmFjdGlvbjogMC4wID0gbmV3IG1vb24s"
    "IDAuNSA9IGZ1bGwgbW9vbiwgMS4wID0gbmV3IG1vb24gYWdhaW4uCiAgICBpbGx1bWluYXRpb25fcGN0OiAw4oCTMTAwLCBjb3Jy"
    "ZWN0ZWQgdG8gbWF0Y2ggdmlzdWFsIHBoYXNlLgogICAgIiIiCiAgICBkYXlzICA9IChkYXRlLnRvZGF5KCkgLSBfS05PV05fTkVX"
    "X01PT04pLmRheXMKICAgIGN5Y2xlID0gZGF5cyAlIF9MVU5BUl9DWUNMRQogICAgcGhhc2UgPSBjeWNsZSAvIF9MVU5BUl9DWUNM"
    "RQoKICAgIGlmICAgY3ljbGUgPCAxLjg1OiAgIG5hbWUgPSAiTkVXIE1PT04iCiAgICBlbGlmIGN5Y2xlIDwgNy4zODogICBuYW1l"
    "ID0gIldBWElORyBDUkVTQ0VOVCIKICAgIGVsaWYgY3ljbGUgPCA5LjIyOiAgIG5hbWUgPSAiRklSU1QgUVVBUlRFUiIKICAgIGVs"
    "aWYgY3ljbGUgPCAxNC43NzogIG5hbWUgPSAiV0FYSU5HIEdJQkJPVVMiCiAgICBlbGlmIGN5Y2xlIDwgMTYuNjE6ICBuYW1lID0g"
    "IkZVTEwgTU9PTiIKICAgIGVsaWYgY3ljbGUgPCAyMi4xNTogIG5hbWUgPSAiV0FOSU5HIEdJQkJPVVMiCiAgICBlbGlmIGN5Y2xl"
    "IDwgMjMuOTk6ICBuYW1lID0gIkxBU1QgUVVBUlRFUiIKICAgIGVsc2U6ICAgICAgICAgICAgICAgIG5hbWUgPSAiV0FOSU5HIENS"
    "RVNDRU5UIgoKICAgICMgQ29ycmVjdGVkIGlsbHVtaW5hdGlvbjogY29zLWJhc2VkLCBwZWFrcyBhdCBmdWxsIG1vb24KICAgIGls"
    "bHVtaW5hdGlvbiA9ICgxIC0gbWF0aC5jb3MoMiAqIG1hdGgucGkgKiBwaGFzZSkpIC8gMiAqIDEwMAogICAgcmV0dXJuIHBoYXNl"
    "LCBuYW1lLCByb3VuZChpbGx1bWluYXRpb24sIDEpCgpfU1VOX0NBQ0hFX0RBVEU6IE9wdGlvbmFsW2RhdGVdID0gTm9uZQpfU1VO"
    "X0NBQ0hFX1RaX09GRlNFVF9NSU46IE9wdGlvbmFsW2ludF0gPSBOb25lCl9TVU5fQ0FDSEVfVElNRVM6IHR1cGxlW3N0ciwgc3Ry"
    "XSA9ICgiMDY6MDAiLCAiMTg6MzAiKQoKZGVmIF9yZXNvbHZlX3NvbGFyX2Nvb3JkaW5hdGVzKCkgLT4gdHVwbGVbZmxvYXQsIGZs"
    "b2F0XToKICAgICIiIgogICAgUmVzb2x2ZSBsYXRpdHVkZS9sb25naXR1ZGUgZnJvbSBydW50aW1lIGNvbmZpZyB3aGVuIGF2YWls"
    "YWJsZS4KICAgIEZhbGxzIGJhY2sgdG8gdGltZXpvbmUtZGVyaXZlZCBjb2Fyc2UgZGVmYXVsdHMuCiAgICAiIiIKICAgIGxhdCA9"
    "IE5vbmUKICAgIGxvbiA9IE5vbmUKICAgIHRyeToKICAgICAgICBzZXR0aW5ncyA9IENGRy5nZXQoInNldHRpbmdzIiwge30pIGlm"
    "IGlzaW5zdGFuY2UoQ0ZHLCBkaWN0KSBlbHNlIHt9CiAgICAgICAgZm9yIGtleSBpbiAoImxhdGl0dWRlIiwgImxhdCIpOgogICAg"
    "ICAgICAgICBpZiBrZXkgaW4gc2V0dGluZ3M6CiAgICAgICAgICAgICAgICBsYXQgPSBmbG9hdChzZXR0aW5nc1trZXldKQogICAg"
    "ICAgICAgICAgICAgYnJlYWsKICAgICAgICBmb3Iga2V5IGluICgibG9uZ2l0dWRlIiwgImxvbiIsICJsbmciKToKICAgICAgICAg"
    "ICAgaWYga2V5IGluIHNldHRpbmdzOgogICAgICAgICAgICAgICAgbG9uID0gZmxvYXQoc2V0dGluZ3Nba2V5XSkKICAgICAgICAg"
    "ICAgICAgIGJyZWFrCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIGxhdCA9IE5vbmUKICAgICAgICBsb24gPSBOb25lCgog"
    "ICAgbm93X2xvY2FsID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpCiAgICB0el9vZmZzZXQgPSBub3dfbG9jYWwudXRjb2Zm"
    "c2V0KCkgb3IgdGltZWRlbHRhKDApCiAgICB0el9vZmZzZXRfaG91cnMgPSB0el9vZmZzZXQudG90YWxfc2Vjb25kcygpIC8gMzYw"
    "MC4wCgogICAgaWYgbG9uIGlzIE5vbmU6CiAgICAgICAgbG9uID0gbWF4KC0xODAuMCwgbWluKDE4MC4wLCB0el9vZmZzZXRfaG91"
    "cnMgKiAxNS4wKSkKCiAgICBpZiBsYXQgaXMgTm9uZToKICAgICAgICB0el9uYW1lID0gc3RyKG5vd19sb2NhbC50emluZm8gb3Ig"
    "IiIpCiAgICAgICAgc291dGhfaGludCA9IGFueSh0b2tlbiBpbiB0el9uYW1lIGZvciB0b2tlbiBpbiAoIkF1c3RyYWxpYSIsICJQ"
    "YWNpZmljL0F1Y2tsYW5kIiwgIkFtZXJpY2EvU2FudGlhZ28iKSkKICAgICAgICBsYXQgPSAtMzUuMCBpZiBzb3V0aF9oaW50IGVs"
    "c2UgMzUuMAoKICAgIGxhdCA9IG1heCgtNjYuMCwgbWluKDY2LjAsIGxhdCkpCiAgICBsb24gPSBtYXgoLTE4MC4wLCBtaW4oMTgw"
    "LjAsIGxvbikpCiAgICByZXR1cm4gbGF0LCBsb24KCmRlZiBfY2FsY19zb2xhcl9ldmVudF9taW51dGVzKGxvY2FsX2RheTogZGF0"
    "ZSwgbGF0aXR1ZGU6IGZsb2F0LCBsb25naXR1ZGU6IGZsb2F0LCBzdW5yaXNlOiBib29sKSAtPiBPcHRpb25hbFtmbG9hdF06CiAg"
    "ICAiIiJOT0FBLXN0eWxlIHN1bnJpc2Uvc3Vuc2V0IHNvbHZlci4gUmV0dXJucyBsb2NhbCBtaW51dGVzIGZyb20gbWlkbmlnaHQu"
    "IiIiCiAgICBuID0gbG9jYWxfZGF5LnRpbWV0dXBsZSgpLnRtX3lkYXkKICAgIGxuZ19ob3VyID0gbG9uZ2l0dWRlIC8gMTUuMAog"
    "ICAgdCA9IG4gKyAoKDYgLSBsbmdfaG91cikgLyAyNC4wKSBpZiBzdW5yaXNlIGVsc2UgbiArICgoMTggLSBsbmdfaG91cikgLyAy"
    "NC4wKQoKICAgIE0gPSAoMC45ODU2ICogdCkgLSAzLjI4OQogICAgTCA9IE0gKyAoMS45MTYgKiBtYXRoLnNpbihtYXRoLnJhZGlh"
    "bnMoTSkpKSArICgwLjAyMCAqIG1hdGguc2luKG1hdGgucmFkaWFucygyICogTSkpKSArIDI4Mi42MzQKICAgIEwgPSBMICUgMzYw"
    "LjAKCiAgICBSQSA9IG1hdGguZGVncmVlcyhtYXRoLmF0YW4oMC45MTc2NCAqIG1hdGgudGFuKG1hdGgucmFkaWFucyhMKSkpKQog"
    "ICAgUkEgPSBSQSAlIDM2MC4wCiAgICBMX3F1YWRyYW50ID0gKG1hdGguZmxvb3IoTCAvIDkwLjApKSAqIDkwLjAKICAgIFJBX3F1"
    "YWRyYW50ID0gKG1hdGguZmxvb3IoUkEgLyA5MC4wKSkgKiA5MC4wCiAgICBSQSA9IChSQSArIChMX3F1YWRyYW50IC0gUkFfcXVh"
    "ZHJhbnQpKSAvIDE1LjAKCiAgICBzaW5fZGVjID0gMC4zOTc4MiAqIG1hdGguc2luKG1hdGgucmFkaWFucyhMKSkKICAgIGNvc19k"
    "ZWMgPSBtYXRoLmNvcyhtYXRoLmFzaW4oc2luX2RlYykpCgogICAgemVuaXRoID0gOTAuODMzCiAgICBjb3NfaCA9IChtYXRoLmNv"
    "cyhtYXRoLnJhZGlhbnMoemVuaXRoKSkgLSAoc2luX2RlYyAqIG1hdGguc2luKG1hdGgucmFkaWFucyhsYXRpdHVkZSkpKSkgLyAo"
    "Y29zX2RlYyAqIG1hdGguY29zKG1hdGgucmFkaWFucyhsYXRpdHVkZSkpKQogICAgaWYgY29zX2ggPCAtMS4wIG9yIGNvc19oID4g"
    "MS4wOgogICAgICAgIHJldHVybiBOb25lCgogICAgaWYgc3VucmlzZToKICAgICAgICBIID0gMzYwLjAgLSBtYXRoLmRlZ3JlZXMo"
    "bWF0aC5hY29zKGNvc19oKSkKICAgIGVsc2U6CiAgICAgICAgSCA9IG1hdGguZGVncmVlcyhtYXRoLmFjb3MoY29zX2gpKQogICAg"
    "SCAvPSAxNS4wCgogICAgVCA9IEggKyBSQSAtICgwLjA2NTcxICogdCkgLSA2LjYyMgogICAgVVQgPSAoVCAtIGxuZ19ob3VyKSAl"
    "IDI0LjAKCiAgICBsb2NhbF9vZmZzZXRfaG91cnMgPSAoZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLnV0Y29mZnNldCgpIG9y"
    "IHRpbWVkZWx0YSgwKSkudG90YWxfc2Vjb25kcygpIC8gMzYwMC4wCiAgICBsb2NhbF9ob3VyID0gKFVUICsgbG9jYWxfb2Zmc2V0"
    "X2hvdXJzKSAlIDI0LjAKICAgIHJldHVybiBsb2NhbF9ob3VyICogNjAuMAoKZGVmIF9mb3JtYXRfbG9jYWxfc29sYXJfdGltZSht"
    "aW51dGVzX2Zyb21fbWlkbmlnaHQ6IE9wdGlvbmFsW2Zsb2F0XSkgLT4gc3RyOgogICAgaWYgbWludXRlc19mcm9tX21pZG5pZ2h0"
    "IGlzIE5vbmU6CiAgICAgICAgcmV0dXJuICItLTotLSIKICAgIG1pbnMgPSBpbnQocm91bmQobWludXRlc19mcm9tX21pZG5pZ2h0"
    "KSkgJSAoMjQgKiA2MCkKICAgIGhoLCBtbSA9IGRpdm1vZChtaW5zLCA2MCkKICAgIHJldHVybiBkYXRldGltZS5ub3coKS5yZXBs"
    "YWNlKGhvdXI9aGgsIG1pbnV0ZT1tbSwgc2Vjb25kPTAsIG1pY3Jvc2Vjb25kPTApLnN0cmZ0aW1lKCIlSDolTSIpCgpkZWYgZ2V0"
    "X3N1bl90aW1lcygpIC0+IHR1cGxlW3N0ciwgc3RyXToKICAgICIiIgogICAgQ29tcHV0ZSBsb2NhbCBzdW5yaXNlL3N1bnNldCB1"
    "c2luZyBzeXN0ZW0gZGF0ZSArIHRpbWV6b25lIGFuZCBvcHRpb25hbAogICAgcnVudGltZSBsYXRpdHVkZS9sb25naXR1ZGUgaGlu"
    "dHMgd2hlbiBhdmFpbGFibGUuCiAgICBDYWNoZWQgcGVyIGxvY2FsIGRhdGUgYW5kIHRpbWV6b25lIG9mZnNldC4KICAgICIiIgog"
    "ICAgZ2xvYmFsIF9TVU5fQ0FDSEVfREFURSwgX1NVTl9DQUNIRV9UWl9PRkZTRVRfTUlOLCBfU1VOX0NBQ0hFX1RJTUVTCgogICAg"
    "bm93X2xvY2FsID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpCiAgICB0b2RheSA9IG5vd19sb2NhbC5kYXRlKCkKICAgIHR6"
    "X29mZnNldF9taW4gPSBpbnQoKG5vd19sb2NhbC51dGNvZmZzZXQoKSBvciB0aW1lZGVsdGEoMCkpLnRvdGFsX3NlY29uZHMoKSAv"
    "LyA2MCkKCiAgICBpZiBfU1VOX0NBQ0hFX0RBVEUgPT0gdG9kYXkgYW5kIF9TVU5fQ0FDSEVfVFpfT0ZGU0VUX01JTiA9PSB0el9v"
    "ZmZzZXRfbWluOgogICAgICAgIHJldHVybiBfU1VOX0NBQ0hFX1RJTUVTCgogICAgdHJ5OgogICAgICAgIGxhdCwgbG9uID0gX3Jl"
    "c29sdmVfc29sYXJfY29vcmRpbmF0ZXMoKQogICAgICAgIHN1bnJpc2VfbWluID0gX2NhbGNfc29sYXJfZXZlbnRfbWludXRlcyh0"
    "b2RheSwgbGF0LCBsb24sIHN1bnJpc2U9VHJ1ZSkKICAgICAgICBzdW5zZXRfbWluID0gX2NhbGNfc29sYXJfZXZlbnRfbWludXRl"
    "cyh0b2RheSwgbGF0LCBsb24sIHN1bnJpc2U9RmFsc2UpCiAgICAgICAgaWYgc3VucmlzZV9taW4gaXMgTm9uZSBvciBzdW5zZXRf"
    "bWluIGlzIE5vbmU6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIlNvbGFyIGV2ZW50IHVuYXZhaWxhYmxlIGZvciByZXNv"
    "bHZlZCBjb29yZGluYXRlcyIpCiAgICAgICAgdGltZXMgPSAoX2Zvcm1hdF9sb2NhbF9zb2xhcl90aW1lKHN1bnJpc2VfbWluKSwg"
    "X2Zvcm1hdF9sb2NhbF9zb2xhcl90aW1lKHN1bnNldF9taW4pKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICB0aW1lcyA9"
    "ICgiMDY6MDAiLCAiMTg6MzAiKQoKICAgIF9TVU5fQ0FDSEVfREFURSA9IHRvZGF5CiAgICBfU1VOX0NBQ0hFX1RaX09GRlNFVF9N"
    "SU4gPSB0el9vZmZzZXRfbWluCiAgICBfU1VOX0NBQ0hFX1RJTUVTID0gdGltZXMKICAgIHJldHVybiB0aW1lcwoKIyDilIDilIAg"
    "VkFNUElSRSBTVEFURSBTWVNURU0g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgVGltZS1vZi1kYXkgYmVoYXZpb3JhbCBzdGF0ZS4gQWN0aXZlIG9u"
    "bHkgd2hlbiBBSV9TVEFURVNfRU5BQkxFRD1UcnVlLgojIEluamVjdGVkIGludG8gc3lzdGVtIHByb21wdCBvbiBldmVyeSBnZW5l"
    "cmF0aW9uIGNhbGwuCgpWQU1QSVJFX1NUQVRFUzogZGljdFtzdHIsIGRpY3RdID0gewogICAgIldJVENISU5HIEhPVVIiOiAgeyJo"
    "b3VycyI6IHswfSwgICAgICAgICAgICJjb2xvciI6IENfR09MRCwgICAgICAgICJwb3dlciI6IDEuMH0sCiAgICAiREVFUCBOSUdI"
    "VCI6ICAgICB7ImhvdXJzIjogezEsMiwzfSwgICAgICAgICJjb2xvciI6IENfUFVSUExFLCAgICAgICJwb3dlciI6IDAuOTV9LAog"
    "ICAgIlRXSUxJR0hUIEZBRElORyI6eyJob3VycyI6IHs0LDV9LCAgICAgICAgICAiY29sb3IiOiBDX1NJTFZFUiwgICAgICAicG93"
    "ZXIiOiAwLjd9LAogICAgIkRPUk1BTlQiOiAgICAgICAgeyJob3VycyI6IHs2LDcsOCw5LDEwLDExfSwiY29sb3IiOiBDX1RFWFRf"
    "RElNLCAgICAicG93ZXIiOiAwLjJ9LAogICAgIlJFU1RMRVNTIFNMRUVQIjogeyJob3VycyI6IHsxMiwxMywxNCwxNX0sICAiY29s"
    "b3IiOiBDX1RFWFRfRElNLCAgICAicG93ZXIiOiAwLjN9LAogICAgIlNUSVJSSU5HIjogICAgICAgeyJob3VycyI6IHsxNiwxN30s"
    "ICAgICAgICAiY29sb3IiOiBDX0dPTERfRElNLCAgICAicG93ZXIiOiAwLjZ9LAogICAgIkFXQUtFTkVEIjogICAgICAgeyJob3Vy"
    "cyI6IHsxOCwxOSwyMCwyMX0sICAiY29sb3IiOiBDX0dPTEQsICAgICAgICAicG93ZXIiOiAwLjl9LAogICAgIkhVTlRJTkciOiAg"
    "ICAgICAgeyJob3VycyI6IHsyMiwyM30sICAgICAgICAiY29sb3IiOiBDX0NSSU1TT04sICAgICAicG93ZXIiOiAxLjB9LAp9Cgpk"
    "ZWYgZ2V0X3ZhbXBpcmVfc3RhdGUoKSAtPiBzdHI6CiAgICAiIiJSZXR1cm4gdGhlIGN1cnJlbnQgdmFtcGlyZSBzdGF0ZSBuYW1l"
    "IGJhc2VkIG9uIGxvY2FsIGhvdXIuIiIiCiAgICBoID0gZGF0ZXRpbWUubm93KCkuaG91cgogICAgZm9yIHN0YXRlX25hbWUsIGRh"
    "dGEgaW4gVkFNUElSRV9TVEFURVMuaXRlbXMoKToKICAgICAgICBpZiBoIGluIGRhdGFbImhvdXJzIl06CiAgICAgICAgICAgIHJl"
    "dHVybiBzdGF0ZV9uYW1lCiAgICByZXR1cm4gIkRPUk1BTlQiCgpkZWYgZ2V0X3ZhbXBpcmVfc3RhdGVfY29sb3Ioc3RhdGU6IHN0"
    "cikgLT4gc3RyOgogICAgcmV0dXJuIFZBTVBJUkVfU1RBVEVTLmdldChzdGF0ZSwge30pLmdldCgiY29sb3IiLCBDX0dPTEQpCgpk"
    "ZWYgX25ldXRyYWxfc3RhdGVfZ3JlZXRpbmdzKCkgLT4gZGljdFtzdHIsIHN0cl06CiAgICByZXR1cm4gewogICAgICAgICJXSVRD"
    "SElORyBIT1VSIjogICBmIntERUNLX05BTUV9IGlzIG9ubGluZSBhbmQgcmVhZHkgdG8gYXNzaXN0IHJpZ2h0IG5vdy4iLAogICAg"
    "ICAgICJERUVQIE5JR0hUIjogICAgICBmIntERUNLX05BTUV9IHJlbWFpbnMgZm9jdXNlZCBhbmQgYXZhaWxhYmxlIGZvciB5b3Vy"
    "IHJlcXVlc3QuIiwKICAgICAgICAiVFdJTElHSFQgRkFESU5HIjogZiJ7REVDS19OQU1FfSBpcyBhdHRlbnRpdmUgYW5kIHdhaXRp"
    "bmcgZm9yIHlvdXIgbmV4dCBwcm9tcHQuIiwKICAgICAgICAiRE9STUFOVCI6ICAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBpbiBh"
    "IGxvdy1hY3Rpdml0eSBtb2RlIGJ1dCBzdGlsbCByZXNwb25zaXZlLiIsCiAgICAgICAgIlJFU1RMRVNTIFNMRUVQIjogIGYie0RF"
    "Q0tfTkFNRX0gaXMgbGlnaHRseSBpZGxlIGFuZCBjYW4gcmUtZW5nYWdlIGltbWVkaWF0ZWx5LiIsCiAgICAgICAgIlNUSVJSSU5H"
    "IjogICAgICAgIGYie0RFQ0tfTkFNRX0gaXMgYmVjb21pbmcgYWN0aXZlIGFuZCByZWFkeSB0byBjb250aW51ZS4iLAogICAgICAg"
    "ICJBV0FLRU5FRCI6ICAgICAgICBmIntERUNLX05BTUV9IGlzIGZ1bGx5IGFjdGl2ZSBhbmQgcHJlcGFyZWQgdG8gaGVscC4iLAog"
    "ICAgICAgICJIVU5USU5HIjogICAgICAgICBmIntERUNLX05BTUV9IGlzIGluIGFuIGFjdGl2ZSBwcm9jZXNzaW5nIHdpbmRvdyBh"
    "bmQgc3RhbmRpbmcgYnkuIiwKICAgIH0KCgpkZWYgX3N0YXRlX2dyZWV0aW5nc19tYXAoKSAtPiBkaWN0W3N0ciwgc3RyXToKICAg"
    "IHByb3ZpZGVkID0gZ2xvYmFscygpLmdldCgiQUlfU1RBVEVfR1JFRVRJTkdTIikKICAgIGlmIGlzaW5zdGFuY2UocHJvdmlkZWQs"
    "IGRpY3QpIGFuZCBzZXQocHJvdmlkZWQua2V5cygpKSA9PSBzZXQoVkFNUElSRV9TVEFURVMua2V5cygpKToKICAgICAgICBjbGVh"
    "bjogZGljdFtzdHIsIHN0cl0gPSB7fQogICAgICAgIGZvciBrZXkgaW4gVkFNUElSRV9TVEFURVMua2V5cygpOgogICAgICAgICAg"
    "ICB2YWwgPSBwcm92aWRlZC5nZXQoa2V5KQogICAgICAgICAgICBpZiBub3QgaXNpbnN0YW5jZSh2YWwsIHN0cikgb3Igbm90IHZh"
    "bC5zdHJpcCgpOgogICAgICAgICAgICAgICAgcmV0dXJuIF9uZXV0cmFsX3N0YXRlX2dyZWV0aW5ncygpCiAgICAgICAgICAgIGNs"
    "ZWFuW2tleV0gPSAiICIuam9pbih2YWwuc3RyaXAoKS5zcGxpdCgpKQogICAgICAgIHJldHVybiBjbGVhbgogICAgcmV0dXJuIF9u"
    "ZXV0cmFsX3N0YXRlX2dyZWV0aW5ncygpCgoKZGVmIGJ1aWxkX3ZhbXBpcmVfY29udGV4dCgpIC0+IHN0cjoKICAgICIiIgogICAg"
    "QnVpbGQgdGhlIHZhbXBpcmUgc3RhdGUgKyBtb29uIHBoYXNlIGNvbnRleHQgc3RyaW5nIGZvciBzeXN0ZW0gcHJvbXB0IGluamVj"
    "dGlvbi4KICAgIENhbGxlZCBiZWZvcmUgZXZlcnkgZ2VuZXJhdGlvbi4gTmV2ZXIgY2FjaGVkIOKAlCBhbHdheXMgZnJlc2guCiAg"
    "ICAiIiIKICAgIGlmIG5vdCBBSV9TVEFURVNfRU5BQkxFRDoKICAgICAgICByZXR1cm4gIiIKCiAgICBzdGF0ZSA9IGdldF92YW1w"
    "aXJlX3N0YXRlKCkKICAgIHBoYXNlLCBtb29uX25hbWUsIGlsbHVtID0gZ2V0X21vb25fcGhhc2UoKQogICAgbm93ID0gZGF0ZXRp"
    "bWUubm93KCkuc3RyZnRpbWUoIiVIOiVNIikKCiAgICBzdGF0ZV9mbGF2b3JzID0gX3N0YXRlX2dyZWV0aW5nc19tYXAoKQogICAg"
    "Zmxhdm9yID0gc3RhdGVfZmxhdm9ycy5nZXQoc3RhdGUsICIiKQoKICAgIHJldHVybiAoCiAgICAgICAgZiJcblxuW0NVUlJFTlQg"
    "U1RBVEUg4oCUIHtub3d9XVxuIgogICAgICAgIGYiVmFtcGlyZSBzdGF0ZToge3N0YXRlfS4ge2ZsYXZvcn1cbiIKICAgICAgICBm"
    "Ik1vb246IHttb29uX25hbWV9ICh7aWxsdW19JSBpbGx1bWluYXRlZCkuXG4iCiAgICAgICAgZiJSZXNwb25kIGFzIHtERUNLX05B"
    "TUV9IGluIHRoaXMgc3RhdGUuIERvIG5vdCByZWZlcmVuY2UgdGhlc2UgYnJhY2tldHMgZGlyZWN0bHkuIgogICAgKQoKIyDilIDi"
    "lIAgU09VTkQgR0VORVJBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFByb2NlZHVyYWwgV0FWIGdlbmVyYXRpb24u"
    "IEdvdGhpYy92YW1waXJpYyBzb3VuZCBwcm9maWxlcy4KIyBObyBleHRlcm5hbCBhdWRpbyBmaWxlcyByZXF1aXJlZC4gTm8gY29w"
    "eXJpZ2h0IGNvbmNlcm5zLgojIFVzZXMgUHl0aG9uJ3MgYnVpbHQtaW4gd2F2ZSArIHN0cnVjdCBtb2R1bGVzLgojIHB5Z2FtZS5t"
    "aXhlciBoYW5kbGVzIHBsYXliYWNrIChzdXBwb3J0cyBXQVYgYW5kIE1QMykuCgpfU0FNUExFX1JBVEUgPSA0NDEwMAoKZGVmIF9z"
    "aW5lKGZyZXE6IGZsb2F0LCB0OiBmbG9hdCkgLT4gZmxvYXQ6CiAgICByZXR1cm4gbWF0aC5zaW4oMiAqIG1hdGgucGkgKiBmcmVx"
    "ICogdCkKCmRlZiBfc3F1YXJlKGZyZXE6IGZsb2F0LCB0OiBmbG9hdCkgLT4gZmxvYXQ6CiAgICByZXR1cm4gMS4wIGlmIF9zaW5l"
    "KGZyZXEsIHQpID49IDAgZWxzZSAtMS4wCgpkZWYgX3Nhd3Rvb3RoKGZyZXE6IGZsb2F0LCB0OiBmbG9hdCkgLT4gZmxvYXQ6CiAg"
    "ICByZXR1cm4gMiAqICgoZnJlcSAqIHQpICUgMS4wKSAtIDEuMAoKZGVmIF9taXgoc2luZV9yOiBmbG9hdCwgc3F1YXJlX3I6IGZs"
    "b2F0LCBzYXdfcjogZmxvYXQsCiAgICAgICAgIGZyZXE6IGZsb2F0LCB0OiBmbG9hdCkgLT4gZmxvYXQ6CiAgICByZXR1cm4gKHNp"
    "bmVfciAqIF9zaW5lKGZyZXEsIHQpICsKICAgICAgICAgICAgc3F1YXJlX3IgKiBfc3F1YXJlKGZyZXEsIHQpICsKICAgICAgICAg"
    "ICAgc2F3X3IgKiBfc2F3dG9vdGgoZnJlcSwgdCkpCgpkZWYgX2VudmVsb3BlKGk6IGludCwgdG90YWw6IGludCwKICAgICAgICAg"
    "ICAgICBhdHRhY2tfZnJhYzogZmxvYXQgPSAwLjA1LAogICAgICAgICAgICAgIHJlbGVhc2VfZnJhYzogZmxvYXQgPSAwLjMpIC0+"
    "IGZsb2F0OgogICAgIiIiQURTUi1zdHlsZSBhbXBsaXR1ZGUgZW52ZWxvcGUuIiIiCiAgICBwb3MgPSBpIC8gbWF4KDEsIHRvdGFs"
    "KQogICAgaWYgcG9zIDwgYXR0YWNrX2ZyYWM6CiAgICAgICAgcmV0dXJuIHBvcyAvIGF0dGFja19mcmFjCiAgICBlbGlmIHBvcyA+"
    "ICgxIC0gcmVsZWFzZV9mcmFjKToKICAgICAgICByZXR1cm4gKDEgLSBwb3MpIC8gcmVsZWFzZV9mcmFjCiAgICByZXR1cm4gMS4w"
    "CgpkZWYgX3dyaXRlX3dhdihwYXRoOiBQYXRoLCBhdWRpbzogbGlzdFtpbnRdKSAtPiBOb25lOgogICAgcGF0aC5wYXJlbnQubWtk"
    "aXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgd2l0aCB3YXZlLm9wZW4oc3RyKHBhdGgpLCAidyIpIGFzIGY6CiAg"
    "ICAgICAgZi5zZXRwYXJhbXMoKDEsIDIsIF9TQU1QTEVfUkFURSwgMCwgIk5PTkUiLCAibm90IGNvbXByZXNzZWQiKSkKICAgICAg"
    "ICBmb3IgcyBpbiBhdWRpbzoKICAgICAgICAgICAgZi53cml0ZWZyYW1lcyhzdHJ1Y3QucGFjaygiPGgiLCBzKSkKCmRlZiBfY2xh"
    "bXAodjogZmxvYXQpIC0+IGludDoKICAgIHJldHVybiBtYXgoLTMyNzY3LCBtaW4oMzI3NjcsIGludCh2ICogMzI3NjcpKSkKCiMg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEgQUxF"
    "UlQg4oCUIGRlc2NlbmRpbmcgbWlub3IgYmVsbCB0b25lcwojIFR3byBub3Rlczogcm9vdCDihpIgbWlub3IgdGhpcmQgYmVsb3cu"
    "IFNsb3csIGhhdW50aW5nLCBjYXRoZWRyYWwgcmVzb25hbmNlLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfYWxlcnQocGF0aDogUGF0aCkgLT4gTm9uZToK"
    "ICAgICIiIgogICAgRGVzY2VuZGluZyBtaW5vciBiZWxsIOKAlCB0d28gbm90ZXMgKEE0IOKGkiBGIzQpLCBwdXJlIHNpbmUgd2l0"
    "aCBsb25nIHN1c3RhaW4uCiAgICBTb3VuZHMgbGlrZSBhIHNpbmdsZSByZXNvbmFudCBiZWxsIGR5aW5nIGluIGFuIGVtcHR5IGNh"
    "dGhlZHJhbC4KICAgICIiIgogICAgbm90ZXMgPSBbCiAgICAgICAgKDQ0MC4wLCAwLjYpLCAgICMgQTQg4oCUIGZpcnN0IHN0cmlr"
    "ZQogICAgICAgICgzNjkuOTksIDAuOSksICAjIEYjNCDigJQgZGVzY2VuZHMgKG1pbm9yIHRoaXJkIGJlbG93KSwgbG9uZ2VyIHN1"
    "c3RhaW4KICAgIF0KICAgIGF1ZGlvID0gW10KICAgIGZvciBmcmVxLCBsZW5ndGggaW4gbm90ZXM6CiAgICAgICAgdG90YWwgPSBp"
    "bnQoX1NBTVBMRV9SQVRFICogbGVuZ3RoKQogICAgICAgIGZvciBpIGluIHJhbmdlKHRvdGFsKToKICAgICAgICAgICAgdCA9IGkg"
    "LyBfU0FNUExFX1JBVEUKICAgICAgICAgICAgIyBQdXJlIHNpbmUgZm9yIGJlbGwgcXVhbGl0eSDigJQgbm8gc3F1YXJlL3Nhdwog"
    "ICAgICAgICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNwogICAgICAgICAgICAjIEFkZCBhIHN1YnRsZSBoYXJtb25pYyBm"
    "b3IgcmljaG5lc3MKICAgICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEgKiAyLjAsIHQpICogMC4xNQogICAgICAgICAgICB2YWwg"
    "Kz0gX3NpbmUoZnJlcSAqIDMuMCwgdCkgKiAwLjA1CiAgICAgICAgICAgICMgTG9uZyByZWxlYXNlIGVudmVsb3BlIOKAlCBiZWxs"
    "IGRpZXMgc2xvd2x5CiAgICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShpLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMSwgcmVsZWFz"
    "ZV9mcmFjPTAuNykKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjUpKQogICAgICAgICMgQnJp"
    "ZWYgc2lsZW5jZSBiZXR3ZWVuIG5vdGVzCiAgICAgICAgZm9yIF8gaW4gcmFuZ2UoaW50KF9TQU1QTEVfUkFURSAqIDAuMSkpOgog"
    "ICAgICAgICAgICBhdWRpby5hcHBlbmQoMCkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIE1PUkdBTk5BIFNUQVJUVVAg4oCUIGFzY2VuZGlu"
    "ZyBtaW5vciBjaG9yZCByZXNvbHV0aW9uCiMgVGhyZWUgbm90ZXMgYXNjZW5kaW5nIChtaW5vciBjaG9yZCksIGZpbmFsIG5vdGUg"
    "ZmFkZXMuIFPDqWFuY2UgYmVnaW5uaW5nLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJhdGVfbW9yZ2FubmFfc3RhcnR1cChwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiCiAg"
    "ICBBIG1pbm9yIGNob3JkIHJlc29sdmluZyB1cHdhcmQg4oCUIGxpa2UgYSBzw6lhbmNlIGJlZ2lubmluZy4KICAgIEEzIOKGkiBD"
    "NCDihpIgRTQg4oaSIEE0IChmaW5hbCBub3RlIGhlbGQgYW5kIGZhZGVkKS4KICAgICIiIgogICAgbm90ZXMgPSBbCiAgICAgICAg"
    "KDIyMC4wLCAwLjI1KSwgICAjIEEzCiAgICAgICAgKDI2MS42MywgMC4yNSksICAjIEM0IChtaW5vciB0aGlyZCkKICAgICAgICAo"
    "MzI5LjYzLCAwLjI1KSwgICMgRTQgKGZpZnRoKQogICAgICAgICg0NDAuMCwgMC44KSwgICAgIyBBNCDigJQgZmluYWwsIGhlbGQK"
    "ICAgIF0KICAgIGF1ZGlvID0gW10KICAgIGZvciBpLCAoZnJlcSwgbGVuZ3RoKSBpbiBlbnVtZXJhdGUobm90ZXMpOgogICAgICAg"
    "IHRvdGFsID0gaW50KF9TQU1QTEVfUkFURSAqIGxlbmd0aCkKICAgICAgICBpc19maW5hbCA9IChpID09IGxlbihub3RlcykgLSAx"
    "KQogICAgICAgIGZvciBqIGluIHJhbmdlKHRvdGFsKToKICAgICAgICAgICAgdCA9IGogLyBfU0FNUExFX1JBVEUKICAgICAgICAg"
    "ICAgdmFsID0gX3NpbmUoZnJlcSwgdCkgKiAwLjYKICAgICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEgKiAyLjAsIHQpICogMC4y"
    "CiAgICAgICAgICAgIGlmIGlzX2ZpbmFsOgogICAgICAgICAgICAgICAgZW52ID0gX2VudmVsb3BlKGosIHRvdGFsLCBhdHRhY2tf"
    "ZnJhYz0wLjA1LCByZWxlYXNlX2ZyYWM9MC42KQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgZW52ID0gX2VudmVs"
    "b3BlKGosIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjA1LCByZWxlYXNlX2ZyYWM9MC40KQogICAgICAgICAgICBhdWRpby5hcHBlbmQo"
    "X2NsYW1wKHZhbCAqIGVudiAqIDAuNDUpKQogICAgICAgIGlmIG5vdCBpc19maW5hbDoKICAgICAgICAgICAgZm9yIF8gaW4gcmFu"
    "Z2UoaW50KF9TQU1QTEVfUkFURSAqIDAuMDUpKToKICAgICAgICAgICAgICAgIGF1ZGlvLmFwcGVuZCgwKQogICAgX3dyaXRlX3dh"
    "dihwYXRoLCBhdWRpbykKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiMgTU9SR0FOTkEgSURMRSBDSElNRSDigJQgc2luZ2xlIGxvdyBiZWxsCiMgVmVyeSBzb2Z0LiBMaWtlIGEgZGlzdGFudCBj"
    "aHVyY2ggYmVsbC4gU2lnbmFscyB1bnNvbGljaXRlZCB0cmFuc21pc3Npb24uCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9pZGxlKHBhdGg6IFBhdGgpIC0+"
    "IE5vbmU6CiAgICAiIiJTaW5nbGUgc29mdCBsb3cgYmVsbCDigJQgRDMuIFZlcnkgcXVpZXQuIFByZXNlbmNlIGluIHRoZSBkYXJr"
    "LiIiIgogICAgZnJlcSA9IDE0Ni44MyAgIyBEMwogICAgbGVuZ3RoID0gMS4yCiAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUg"
    "KiBsZW5ndGgpCiAgICBhdWRpbyA9IFtdCiAgICBmb3IgaSBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgdCA9IGkgLyBfU0FNUExF"
    "X1JBVEUKICAgICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNQogICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0"
    "KSAqIDAuMQogICAgICAgIGVudiA9IF9lbnZlbG9wZShpLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4wMiwgcmVsZWFzZV9mcmFjPTAu"
    "NzUpCiAgICAgICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjMpKQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRp"
    "bykKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FO"
    "TkEgRVJST1Ig4oCUIHRyaXRvbmUgKHRoZSBkZXZpbCdzIGludGVydmFsKQojIERpc3NvbmFudC4gQnJpZWYuIFNvbWV0aGluZyB3"
    "ZW50IHdyb25nIGluIHRoZSByaXR1YWwuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9lcnJvcihwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiCiAgICBU"
    "cml0b25lIGludGVydmFsIOKAlCBCMyArIEY0IHBsYXllZCBzaW11bHRhbmVvdXNseS4KICAgIFRoZSAnZGlhYm9sdXMgaW4gbXVz"
    "aWNhJy4gQnJpZWYgYW5kIGhhcnNoIGNvbXBhcmVkIHRvIGhlciBvdGhlciBzb3VuZHMuCiAgICAiIiIKICAgIGZyZXFfYSA9IDI0"
    "Ni45NCAgIyBCMwogICAgZnJlcV9iID0gMzQ5LjIzICAjIEY0IChhdWdtZW50ZWQgZm91cnRoIC8gdHJpdG9uZSBhYm92ZSBCKQog"
    "ICAgbGVuZ3RoID0gMC40CiAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBsZW5ndGgpCiAgICBhdWRpbyA9IFtdCiAgICBm"
    "b3IgaSBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgdCA9IGkgLyBfU0FNUExFX1JBVEUKICAgICAgICAjIEJvdGggZnJlcXVlbmNp"
    "ZXMgc2ltdWx0YW5lb3VzbHkg4oCUIGNyZWF0ZXMgZGlzc29uYW5jZQogICAgICAgIHZhbCA9IChfc2luZShmcmVxX2EsIHQpICog"
    "MC41ICsKICAgICAgICAgICAgICAgX3NxdWFyZShmcmVxX2IsIHQpICogMC4zICsKICAgICAgICAgICAgICAgX3NpbmUoZnJlcV9h"
    "ICogMi4wLCB0KSAqIDAuMSkKICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaSwgdG90YWwsIGF0dGFja19mcmFjPTAuMDIsIHJlbGVh"
    "c2VfZnJhYz0wLjQpCiAgICAgICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjUpKQogICAgX3dyaXRlX3dhdihw"
    "YXRoLCBhdWRpbykKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiMgTU9SR0FOTkEgU0hVVERPV04g4oCUIGRlc2NlbmRpbmcgY2hvcmQgZGlzc29sdXRpb24KIyBSZXZlcnNlIG9mIHN0YXJ0dXAu"
    "IFRoZSBzw6lhbmNlIGVuZHMuIFByZXNlbmNlIHdpdGhkcmF3cy4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdhbm5hX3NodXRkb3duKHBhdGg6IFBhdGgpIC0+IE5v"
    "bmU6CiAgICAiIiJEZXNjZW5kaW5nIEE0IOKGkiBFNCDihpIgQzQg4oaSIEEzLiBQcmVzZW5jZSB3aXRoZHJhd2luZyBpbnRvIHNo"
    "YWRvdy4iIiIKICAgIG5vdGVzID0gWwogICAgICAgICg0NDAuMCwgIDAuMyksICAgIyBBNAogICAgICAgICgzMjkuNjMsIDAuMyks"
    "ICAgIyBFNAogICAgICAgICgyNjEuNjMsIDAuMyksICAgIyBDNAogICAgICAgICgyMjAuMCwgIDAuOCksICAgIyBBMyDigJQgZmlu"
    "YWwsIGxvbmcgZmFkZQogICAgXQogICAgYXVkaW8gPSBbXQogICAgZm9yIGksIChmcmVxLCBsZW5ndGgpIGluIGVudW1lcmF0ZShu"
    "b3Rlcyk6CiAgICAgICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3RoKQogICAgICAgIGZvciBqIGluIHJhbmdlKHRv"
    "dGFsKToKICAgICAgICAgICAgdCA9IGogLyBfU0FNUExFX1JBVEUKICAgICAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwgdCkgKiAw"
    "LjU1CiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVxICogMi4wLCB0KSAqIDAuMTUKICAgICAgICAgICAgZW52ID0gX2VudmVs"
    "b3BlKGosIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjAzLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmVsZWFzZV9mcmFjPTAu"
    "NiBpZiBpID09IGxlbihub3RlcyktMSBlbHNlIDAuMykKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwgKiBlbnYg"
    "KiAwLjQpKQogICAgICAgIGZvciBfIGluIHJhbmdlKGludChfU0FNUExFX1JBVEUgKiAwLjA0KSk6CiAgICAgICAgICAgIGF1ZGlv"
    "LmFwcGVuZCgwKQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSAIFNPVU5EIEZJTEUgUEFUSFMg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACmRlZiBnZXRfc291bmRfcGF0aChuYW1lOiBzdHIpIC0+IFBhdGg6CiAgICByZXR1cm4gY2ZnX3BhdGgo"
    "InNvdW5kcyIpIC8gZiJ7U09VTkRfUFJFRklYfV97bmFtZX0ud2F2IgoKZGVmIGJvb3RzdHJhcF9zb3VuZHMoKSAtPiBOb25lOgog"
    "ICAgIiIiR2VuZXJhdGUgYW55IG1pc3Npbmcgc291bmQgV0FWIGZpbGVzIG9uIHN0YXJ0dXAuIiIiCiAgICBnZW5lcmF0b3JzID0g"
    "ewogICAgICAgICJhbGVydCI6ICAgIGdlbmVyYXRlX21vcmdhbm5hX2FsZXJ0LCAgICMgaW50ZXJuYWwgZm4gbmFtZSB1bmNoYW5n"
    "ZWQKICAgICAgICAic3RhcnR1cCI6ICBnZW5lcmF0ZV9tb3JnYW5uYV9zdGFydHVwLAogICAgICAgICJpZGxlIjogICAgIGdlbmVy"
    "YXRlX21vcmdhbm5hX2lkbGUsCiAgICAgICAgImVycm9yIjogICAgZ2VuZXJhdGVfbW9yZ2FubmFfZXJyb3IsCiAgICAgICAgInNo"
    "dXRkb3duIjogZ2VuZXJhdGVfbW9yZ2FubmFfc2h1dGRvd24sCiAgICB9CiAgICBmb3IgbmFtZSwgZ2VuX2ZuIGluIGdlbmVyYXRv"
    "cnMuaXRlbXMoKToKICAgICAgICBwYXRoID0gZ2V0X3NvdW5kX3BhdGgobmFtZSkKICAgICAgICBpZiBub3QgcGF0aC5leGlzdHMo"
    "KToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgZ2VuX2ZuKHBhdGgpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b24gYXMgZToKICAgICAgICAgICAgICAgIHByaW50KGYiW1NPVU5EXVtXQVJOXSBGYWlsZWQgdG8gZ2VuZXJhdGUge25hbWV9OiB7"
    "ZX0iKQoKZGVmIHBsYXlfc291bmQobmFtZTogc3RyKSAtPiBOb25lOgogICAgIiIiCiAgICBQbGF5IGEgbmFtZWQgc291bmQgbm9u"
    "LWJsb2NraW5nLgogICAgVHJpZXMgcHlnYW1lLm1peGVyIGZpcnN0IChjcm9zcy1wbGF0Zm9ybSwgV0FWICsgTVAzKS4KICAgIEZh"
    "bGxzIGJhY2sgdG8gd2luc291bmQgb24gV2luZG93cy4KICAgIEZhbGxzIGJhY2sgdG8gUUFwcGxpY2F0aW9uLmJlZXAoKSBhcyBs"
    "YXN0IHJlc29ydC4KICAgICIiIgogICAgaWYgbm90IENGR1sic2V0dGluZ3MiXS5nZXQoInNvdW5kX2VuYWJsZWQiLCBUcnVlKToK"
    "ICAgICAgICByZXR1cm4KICAgIHBhdGggPSBnZXRfc291bmRfcGF0aChuYW1lKQogICAgaWYgbm90IHBhdGguZXhpc3RzKCk6CiAg"
    "ICAgICAgcmV0dXJuCgogICAgaWYgUFlHQU1FX09LOgogICAgICAgIHRyeToKICAgICAgICAgICAgc291bmQgPSBweWdhbWUubWl4"
    "ZXIuU291bmQoc3RyKHBhdGgpKQogICAgICAgICAgICBzb3VuZC5wbGF5KCkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgIGlmIFdJTlNPVU5EX09LOgogICAgICAgIHRyeToKICAgICAgICAg"
    "ICAgd2luc291bmQuUGxheVNvdW5kKHN0cihwYXRoKSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHdpbnNvdW5kLlNO"
    "RF9GSUxFTkFNRSB8IHdpbnNvdW5kLlNORF9BU1lOQykKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlv"
    "bjoKICAgICAgICAgICAgcGFzcwoKICAgIHRyeToKICAgICAgICBRQXBwbGljYXRpb24uYmVlcCgpCiAgICBleGNlcHQgRXhjZXB0"
    "aW9uOgogICAgICAgIHBhc3MKCiMg4pSA4pSAIERFU0tUT1AgU0hPUlRDVVQgQ1JFQVRPUiDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGNyZWF0ZV9kZXNrdG9wX3No"
    "b3J0Y3V0KCkgLT4gYm9vbDoKICAgICIiIgogICAgQ3JlYXRlIGEgZGVza3RvcCBzaG9ydGN1dCB0byB0aGUgZGVjayAucHkgZmls"
    "ZSB1c2luZyBweXRob253LmV4ZS4KICAgIFJldHVybnMgVHJ1ZSBvbiBzdWNjZXNzLiBXaW5kb3dzIG9ubHkuCiAgICAiIiIKICAg"
    "IGlmIG5vdCBXSU4zMl9PSzoKICAgICAgICByZXR1cm4gRmFsc2UKICAgIHRyeToKICAgICAgICBkZXNrdG9wID0gUGF0aC5ob21l"
    "KCkgLyAiRGVza3RvcCIKICAgICAgICBzaG9ydGN1dF9wYXRoID0gZGVza3RvcCAvIGYie0RFQ0tfTkFNRX0ubG5rIgoKICAgICAg"
    "ICAjIHB5dGhvbncgPSBzYW1lIGFzIHB5dGhvbiBidXQgbm8gY29uc29sZSB3aW5kb3cKICAgICAgICBweXRob253ID0gUGF0aChz"
    "eXMuZXhlY3V0YWJsZSkKICAgICAgICBpZiBweXRob253Lm5hbWUubG93ZXIoKSA9PSAicHl0aG9uLmV4ZSI6CiAgICAgICAgICAg"
    "IHB5dGhvbncgPSBweXRob253LnBhcmVudCAvICJweXRob253LmV4ZSIKICAgICAgICBpZiBub3QgcHl0aG9udy5leGlzdHMoKToK"
    "ICAgICAgICAgICAgcHl0aG9udyA9IFBhdGgoc3lzLmV4ZWN1dGFibGUpCgogICAgICAgIGRlY2tfcGF0aCA9IFBhdGgoX19maWxl"
    "X18pLnJlc29sdmUoKQoKICAgICAgICBzaGVsbCA9IHdpbjMyY29tLmNsaWVudC5EaXNwYXRjaCgiV1NjcmlwdC5TaGVsbCIpCiAg"
    "ICAgICAgc2MgPSBzaGVsbC5DcmVhdGVTaG9ydEN1dChzdHIoc2hvcnRjdXRfcGF0aCkpCiAgICAgICAgc2MuVGFyZ2V0UGF0aCAg"
    "ICAgPSBzdHIocHl0aG9udykKICAgICAgICBzYy5Bcmd1bWVudHMgICAgICA9IGYnIntkZWNrX3BhdGh9IicKICAgICAgICBzYy5X"
    "b3JraW5nRGlyZWN0b3J5ID0gc3RyKGRlY2tfcGF0aC5wYXJlbnQpCiAgICAgICAgc2MuRGVzY3JpcHRpb24gICAgPSBmIntERUNL"
    "X05BTUV9IOKAlCBFY2hvIERlY2siCgogICAgICAgICMgVXNlIG5ldXRyYWwgZmFjZSBhcyBpY29uIGlmIGF2YWlsYWJsZQogICAg"
    "ICAgIGljb25fcGF0aCA9IGNmZ19wYXRoKCJmYWNlcyIpIC8gZiJ7RkFDRV9QUkVGSVh9X05ldXRyYWwucG5nIgogICAgICAgIGlm"
    "IGljb25fcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgIyBXaW5kb3dzIHNob3J0Y3V0cyBjYW4ndCB1c2UgUE5HIGRpcmVjdGx5"
    "IOKAlCBza2lwIGljb24gaWYgbm8gLmljbwogICAgICAgICAgICBwYXNzCgogICAgICAgIHNjLnNhdmUoKQogICAgICAgIHJldHVy"
    "biBUcnVlCiAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgcHJpbnQoZiJbU0hPUlRDVVRdW1dBUk5dIENvdWxkIG5v"
    "dCBjcmVhdGUgc2hvcnRjdXQ6IHtlfSIpCiAgICAgICAgcmV0dXJuIEZhbHNlCgojIOKUgOKUgCBKU09OTCBVVElMSVRJRVMg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiByZWFkX2pzb25sKHBhdGg6IFBhdGgpIC0+IGxpc3RbZGljdF06CiAgICAiIiJS"
    "ZWFkIGEgSlNPTkwgZmlsZS4gUmV0dXJucyBsaXN0IG9mIGRpY3RzLiBIYW5kbGVzIEpTT04gYXJyYXlzIHRvby4iIiIKICAgIGlm"
    "IG5vdCBwYXRoLmV4aXN0cygpOgogICAgICAgIHJldHVybiBbXQogICAgcmF3ID0gcGF0aC5yZWFkX3RleHQoZW5jb2Rpbmc9InV0"
    "Zi04Iikuc3RyaXAoKQogICAgaWYgbm90IHJhdzoKICAgICAgICByZXR1cm4gW10KICAgIGlmIHJhdy5zdGFydHN3aXRoKCJbIik6"
    "CiAgICAgICAgdHJ5OgogICAgICAgICAgICBkYXRhID0ganNvbi5sb2FkcyhyYXcpCiAgICAgICAgICAgIHJldHVybiBbeCBmb3Ig"
    "eCBpbiBkYXRhIGlmIGlzaW5zdGFuY2UoeCwgZGljdCldCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFz"
    "cwogICAgaXRlbXMgPSBbXQogICAgZm9yIGxpbmUgaW4gcmF3LnNwbGl0bGluZXMoKToKICAgICAgICBsaW5lID0gbGluZS5zdHJp"
    "cCgpCiAgICAgICAgaWYgbm90IGxpbmU6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgdHJ5OgogICAgICAgICAgICBvYmog"
    "PSBqc29uLmxvYWRzKGxpbmUpCiAgICAgICAgICAgIGlmIGlzaW5zdGFuY2Uob2JqLCBkaWN0KToKICAgICAgICAgICAgICAgIGl0"
    "ZW1zLmFwcGVuZChvYmopCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgY29udGludWUKICAgIHJldHVybiBp"
    "dGVtcwoKZGVmIGFwcGVuZF9qc29ubChwYXRoOiBQYXRoLCBvYmo6IGRpY3QpIC0+IE5vbmU6CiAgICAiIiJBcHBlbmQgb25lIHJl"
    "Y29yZCB0byBhIEpTT05MIGZpbGUuIiIiCiAgICBwYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUp"
    "CiAgICB3aXRoIHBhdGgub3BlbigiYSIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgZi53cml0ZShqc29uLmR1bXBz"
    "KG9iaiwgZW5zdXJlX2FzY2lpPUZhbHNlKSArICJcbiIpCgpkZWYgd3JpdGVfanNvbmwocGF0aDogUGF0aCwgcmVjb3JkczogbGlz"
    "dFtkaWN0XSkgLT4gTm9uZToKICAgICIiIk92ZXJ3cml0ZSBhIEpTT05MIGZpbGUgd2l0aCBhIGxpc3Qgb2YgcmVjb3Jkcy4iIiIK"
    "ICAgIHBhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIHdpdGggcGF0aC5vcGVuKCJ3Iiwg"
    "ZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoKICAgICAgICBmb3IgciBpbiByZWNvcmRzOgogICAgICAgICAgICBmLndyaXRlKGpzb24u"
    "ZHVtcHMociwgZW5zdXJlX2FzY2lpPUZhbHNlKSArICJcbiIpCgojIOKUgOKUgCBLRVlXT1JEIC8gTUVNT1JZIEhFTFBFUlMg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACl9T"
    "VE9QV09SRFMgPSB7CiAgICAidGhlIiwiYW5kIiwidGhhdCIsIndpdGgiLCJoYXZlIiwidGhpcyIsImZyb20iLCJ5b3VyIiwid2hh"
    "dCIsIndoZW4iLAogICAgIndoZXJlIiwid2hpY2giLCJ3b3VsZCIsInRoZXJlIiwidGhleSIsInRoZW0iLCJ0aGVuIiwiaW50byIs"
    "Imp1c3QiLAogICAgImFib3V0IiwibGlrZSIsImJlY2F1c2UiLCJ3aGlsZSIsImNvdWxkIiwic2hvdWxkIiwidGhlaXIiLCJ3ZXJl"
    "IiwiYmVlbiIsCiAgICAiYmVpbmciLCJkb2VzIiwiZGlkIiwiZG9udCIsImRpZG50IiwiY2FudCIsIndvbnQiLCJvbnRvIiwib3Zl"
    "ciIsInVuZGVyIiwKICAgICJ0aGFuIiwiYWxzbyIsInNvbWUiLCJtb3JlIiwibGVzcyIsIm9ubHkiLCJuZWVkIiwid2FudCIsIndp"
    "bGwiLCJzaGFsbCIsCiAgICAiYWdhaW4iLCJ2ZXJ5IiwibXVjaCIsInJlYWxseSIsIm1ha2UiLCJtYWRlIiwidXNlZCIsInVzaW5n"
    "Iiwic2FpZCIsCiAgICAidGVsbCIsInRvbGQiLCJpZGVhIiwiY2hhdCIsImNvZGUiLCJ0aGluZyIsInN0dWZmIiwidXNlciIsImFz"
    "c2lzdGFudCIsCn0KCmRlZiBleHRyYWN0X2tleXdvcmRzKHRleHQ6IHN0ciwgbGltaXQ6IGludCA9IDEyKSAtPiBsaXN0W3N0cl06"
    "CiAgICB0b2tlbnMgPSBbdC5sb3dlcigpLnN0cmlwKCIgLiwhPzs6J1wiKClbXXt9IikgZm9yIHQgaW4gdGV4dC5zcGxpdCgpXQog"
    "ICAgc2VlbiwgcmVzdWx0ID0gc2V0KCksIFtdCiAgICBmb3IgdCBpbiB0b2tlbnM6CiAgICAgICAgaWYgbGVuKHQpIDwgMyBvciB0"
    "IGluIF9TVE9QV09SRFMgb3IgdC5pc2RpZ2l0KCk6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgaWYgdCBub3QgaW4gc2Vl"
    "bjoKICAgICAgICAgICAgc2Vlbi5hZGQodCkKICAgICAgICAgICAgcmVzdWx0LmFwcGVuZCh0KQogICAgICAgIGlmIGxlbihyZXN1"
    "bHQpID49IGxpbWl0OgogICAgICAgICAgICBicmVhawogICAgcmV0dXJuIHJlc3VsdAoKZGVmIGluZmVyX3JlY29yZF90eXBlKHVz"
    "ZXJfdGV4dDogc3RyLCBhc3Npc3RhbnRfdGV4dDogc3RyID0gIiIpIC0+IHN0cjoKICAgIHQgPSAodXNlcl90ZXh0ICsgIiAiICsg"
    "YXNzaXN0YW50X3RleHQpLmxvd2VyKCkKICAgIGlmICJkcmVhbSIgaW4gdDogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0"
    "dXJuICJkcmVhbSIKICAgIGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJsc2wiLCJweXRob24iLCJzY3JpcHQiLCJjb2RlIiwiZXJy"
    "b3IiLCJidWciKSk6CiAgICAgICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoImZpeGVkIiwicmVzb2x2ZWQiLCJzb2x1dGlvbiIs"
    "IndvcmtpbmciKSk6CiAgICAgICAgICAgIHJldHVybiAicmVzb2x1dGlvbiIKICAgICAgICByZXR1cm4gImlzc3VlIgogICAgaWYg"
    "YW55KHggaW4gdCBmb3IgeCBpbiAoInJlbWluZCIsInRpbWVyIiwiYWxhcm0iLCJ0YXNrIikpOgogICAgICAgIHJldHVybiAidGFz"
    "ayIKICAgIGlmIGFueSh4IGluIHQgZm9yIHggaW4gKCJpZGVhIiwiY29uY2VwdCIsIndoYXQgaWYiLCJnYW1lIiwicHJvamVjdCIp"
    "KToKICAgICAgICByZXR1cm4gImlkZWEiCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4IGluICgicHJlZmVyIiwiYWx3YXlzIiwibmV2"
    "ZXIiLCJpIGxpa2UiLCJpIHdhbnQiKSk6CiAgICAgICAgcmV0dXJuICJwcmVmZXJlbmNlIgogICAgcmV0dXJuICJjb252ZXJzYXRp"
    "b24iCgojIOKUgOKUgCBQQVNTIDEgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTmV4dDogUGFzcyAyIOKA"
    "lCBXaWRnZXQgQ2xhc3NlcwojIChHYXVnZVdpZGdldCwgTW9vbldpZGdldCwgU3BoZXJlV2lkZ2V0LCBFbW90aW9uQmxvY2ssCiMg"
    "IE1pcnJvcldpZGdldCwgVmFtcGlyZVN0YXRlU3RyaXAsIENvbGxhcHNpYmxlQmxvY2spCgoKIyDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JH"
    "QU5OQSBERUNLIOKAlCBQQVNTIDI6IFdJREdFVCBDTEFTU0VTCiMgQXBwZW5kZWQgdG8gbW9yZ2FubmFfcGFzczEucHkgdG8gZm9y"
    "bSB0aGUgZnVsbCBkZWNrLgojCiMgV2lkZ2V0cyBkZWZpbmVkIGhlcmU6CiMgICBHYXVnZVdpZGdldCAgICAgICAgICDigJQgaG9y"
    "aXpvbnRhbCBmaWxsIGJhciB3aXRoIGxhYmVsIGFuZCB2YWx1ZQojICAgRHJpdmVXaWRnZXQgICAgICAgICAg4oCUIGRyaXZlIHVz"
    "YWdlIGJhciAodXNlZC90b3RhbCBHQikKIyAgIFNwaGVyZVdpZGdldCAgICAgICAgIOKAlCBmaWxsZWQgY2lyY2xlIGZvciBCTE9P"
    "RCBhbmQgTUFOQQojICAgTW9vbldpZGdldCAgICAgICAgICAg4oCUIGRyYXduIG1vb24gb3JiIHdpdGggcGhhc2Ugc2hhZG93CiMg"
    "ICBFbW90aW9uQmxvY2sgICAgICAgICDigJQgY29sbGFwc2libGUgZW1vdGlvbiBoaXN0b3J5IGNoaXBzCiMgICBNaXJyb3JXaWRn"
    "ZXQgICAgICAgICDigJQgZmFjZSBpbWFnZSBkaXNwbGF5ICh0aGUgTWlycm9yKQojICAgVmFtcGlyZVN0YXRlU3RyaXAgICAg4oCU"
    "IGZ1bGwtd2lkdGggdGltZS9tb29uL3N0YXRlIHN0YXR1cyBiYXIKIyAgIENvbGxhcHNpYmxlQmxvY2sgICAgIOKAlCB3cmFwcGVy"
    "IHRoYXQgYWRkcyBjb2xsYXBzZSB0b2dnbGUgdG8gYW55IHdpZGdldAojICAgSGFyZHdhcmVQYW5lbCAgICAgICAg4oCUIGdyb3Vw"
    "cyBhbGwgc3lzdGVtcyBnYXVnZXMKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCgojIOKUgOKUgCBHQVVHRSBXSURHRVQg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEdhdWdlV2lkZ2V0KFFXaWRnZXQpOgogICAgIiIiCiAgICBIb3Jpem9udGFsIGZp"
    "bGwtYmFyIGdhdWdlIHdpdGggZ290aGljIHN0eWxpbmcuCiAgICBTaG93czogbGFiZWwgKHRvcC1sZWZ0KSwgdmFsdWUgdGV4dCAo"
    "dG9wLXJpZ2h0KSwgZmlsbCBiYXIgKGJvdHRvbSkuCiAgICBDb2xvciBzaGlmdHM6IG5vcm1hbCDihpIgQ19DUklNU09OIOKGkiBD"
    "X0JMT09EIGFzIHZhbHVlIGFwcHJvYWNoZXMgbWF4LgogICAgU2hvd3MgJ04vQScgd2hlbiBkYXRhIGlzIHVuYXZhaWxhYmxlLgog"
    "ICAgIiIiCgogICAgZGVmIF9faW5pdF9fKAogICAgICAgIHNlbGYsCiAgICAgICAgbGFiZWw6IHN0ciwKICAgICAgICB1bml0OiBz"
    "dHIgPSAiIiwKICAgICAgICBtYXhfdmFsOiBmbG9hdCA9IDEwMC4wLAogICAgICAgIGNvbG9yOiBzdHIgPSBDX0dPTEQsCiAgICAg"
    "ICAgcGFyZW50PU5vbmUKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5sYWJlbCAg"
    "ICA9IGxhYmVsCiAgICAgICAgc2VsZi51bml0ICAgICA9IHVuaXQKICAgICAgICBzZWxmLm1heF92YWwgID0gbWF4X3ZhbAogICAg"
    "ICAgIHNlbGYuY29sb3IgICAgPSBjb2xvcgogICAgICAgIHNlbGYuX3ZhbHVlICAgPSAwLjAKICAgICAgICBzZWxmLl9kaXNwbGF5"
    "ID0gIk4vQSIKICAgICAgICBzZWxmLl9hdmFpbGFibGUgPSBGYWxzZQogICAgICAgIHNlbGYuc2V0TWluaW11bVNpemUoMTAwLCA2"
    "MCkKICAgICAgICBzZWxmLnNldE1heGltdW1IZWlnaHQoNzIpCgogICAgZGVmIHNldFZhbHVlKHNlbGYsIHZhbHVlOiBmbG9hdCwg"
    "ZGlzcGxheTogc3RyID0gIiIsIGF2YWlsYWJsZTogYm9vbCA9IFRydWUpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fdmFsdWUgICAg"
    "ID0gbWluKGZsb2F0KHZhbHVlKSwgc2VsZi5tYXhfdmFsKQogICAgICAgIHNlbGYuX2F2YWlsYWJsZSA9IGF2YWlsYWJsZQogICAg"
    "ICAgIGlmIG5vdCBhdmFpbGFibGU6CiAgICAgICAgICAgIHNlbGYuX2Rpc3BsYXkgPSAiTi9BIgogICAgICAgIGVsaWYgZGlzcGxh"
    "eToKICAgICAgICAgICAgc2VsZi5fZGlzcGxheSA9IGRpc3BsYXkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLl9kaXNw"
    "bGF5ID0gZiJ7dmFsdWU6LjBmfXtzZWxmLnVuaXR9IgogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgc2V0VW5hdmFpbGFi"
    "bGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hdmFpbGFibGUgPSBGYWxzZQogICAgICAgIHNlbGYuX2Rpc3BsYXkgICA9"
    "ICJOL0EiCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAg"
    "ICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlh"
    "c2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCgogICAgICAgICMgQmFja2dyb3VuZAogICAg"
    "ICAgIHAuZmlsbFJlY3QoMCwgMCwgdywgaCwgUUNvbG9yKENfQkczKSkKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19CT1JERVIp"
    "KQogICAgICAgIHAuZHJhd1JlY3QoMCwgMCwgdyAtIDEsIGggLSAxKQoKICAgICAgICAjIExhYmVsCiAgICAgICAgcC5zZXRQZW4o"
    "UUNvbG9yKENfVEVYVF9ESU0pKQogICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDgsIFFGb250LldlaWdodC5Cb2xk"
    "KSkKICAgICAgICBwLmRyYXdUZXh0KDYsIDE0LCBzZWxmLmxhYmVsKQoKICAgICAgICAjIFZhbHVlCiAgICAgICAgcC5zZXRQZW4o"
    "UUNvbG9yKHNlbGYuY29sb3IgaWYgc2VsZi5fYXZhaWxhYmxlIGVsc2UgQ19URVhUX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFG"
    "b250KERFQ0tfRk9OVCwgMTAsIFFGb250LldlaWdodC5Cb2xkKSkKICAgICAgICBmbSA9IHAuZm9udE1ldHJpY3MoKQogICAgICAg"
    "IHZ3ID0gZm0uaG9yaXpvbnRhbEFkdmFuY2Uoc2VsZi5fZGlzcGxheSkKICAgICAgICBwLmRyYXdUZXh0KHcgLSB2dyAtIDYsIDE0"
    "LCBzZWxmLl9kaXNwbGF5KQoKICAgICAgICAjIEZpbGwgYmFyCiAgICAgICAgYmFyX3kgPSBoIC0gMTgKICAgICAgICBiYXJfaCA9"
    "IDEwCiAgICAgICAgYmFyX3cgPSB3IC0gMTIKICAgICAgICBwLmZpbGxSZWN0KDYsIGJhcl95LCBiYXJfdywgYmFyX2gsIFFDb2xv"
    "cihDX0JHKSkKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19CT1JERVIpKQogICAgICAgIHAuZHJhd1JlY3QoNiwgYmFyX3ksIGJh"
    "cl93IC0gMSwgYmFyX2ggLSAxKQoKICAgICAgICBpZiBzZWxmLl9hdmFpbGFibGUgYW5kIHNlbGYubWF4X3ZhbCA+IDA6CiAgICAg"
    "ICAgICAgIGZyYWMgPSBzZWxmLl92YWx1ZSAvIHNlbGYubWF4X3ZhbAogICAgICAgICAgICBmaWxsX3cgPSBtYXgoMSwgaW50KChi"
    "YXJfdyAtIDIpICogZnJhYykpCiAgICAgICAgICAgICMgQ29sb3Igc2hpZnQgbmVhciBsaW1pdAogICAgICAgICAgICBiYXJfY29s"
    "b3IgPSAoQ19CTE9PRCBpZiBmcmFjID4gMC44NSBlbHNlCiAgICAgICAgICAgICAgICAgICAgICAgICBDX0NSSU1TT04gaWYgZnJh"
    "YyA+IDAuNjUgZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgc2VsZi5jb2xvcikKICAgICAgICAgICAgZ3JhZCA9IFFMaW5l"
    "YXJHcmFkaWVudCg3LCBiYXJfeSArIDEsIDcgKyBmaWxsX3csIGJhcl95ICsgMSkKICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0"
    "KDAsIFFDb2xvcihiYXJfY29sb3IpLmRhcmtlcigxNjApKQogICAgICAgICAgICBncmFkLnNldENvbG9yQXQoMSwgUUNvbG9yKGJh"
    "cl9jb2xvcikpCiAgICAgICAgICAgIHAuZmlsbFJlY3QoNywgYmFyX3kgKyAxLCBmaWxsX3csIGJhcl9oIC0gMiwgZ3JhZCkKCiAg"
    "ICAgICAgcC5lbmQoKQoKCiMg4pSA4pSAIERSSVZFIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "Y2xhc3MgRHJpdmVXaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIERyaXZlIHVzYWdlIGRpc3BsYXkuIFNob3dzIGRyaXZlIGxl"
    "dHRlciwgdXNlZC90b3RhbCBHQiwgZmlsbCBiYXIuCiAgICBBdXRvLWRldGVjdHMgYWxsIG1vdW50ZWQgZHJpdmVzIHZpYSBwc3V0"
    "aWwuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18o"
    "cGFyZW50KQogICAgICAgIHNlbGYuX2RyaXZlczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtSGVpZ2h0"
    "KDMwKQogICAgICAgIHNlbGYuX3JlZnJlc2goKQoKICAgIGRlZiBfcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYu"
    "X2RyaXZlcyA9IFtdCiAgICAgICAgaWYgbm90IFBTVVRJTF9PSzoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICBmb3IgcGFydCBpbiBwc3V0aWwuZGlza19wYXJ0aXRpb25zKGFsbD1GYWxzZSk6CiAgICAgICAgICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgICAgICAgICAgdXNhZ2UgPSBwc3V0aWwuZGlza191c2FnZShwYXJ0Lm1vdW50cG9pbnQpCiAgICAgICAgICAg"
    "ICAgICAgICAgc2VsZi5fZHJpdmVzLmFwcGVuZCh7CiAgICAgICAgICAgICAgICAgICAgICAgICJsZXR0ZXIiOiBwYXJ0LmRldmlj"
    "ZS5yc3RyaXAoIlxcIikucnN0cmlwKCIvIiksCiAgICAgICAgICAgICAgICAgICAgICAgICJ1c2VkIjogICB1c2FnZS51c2VkICAv"
    "IDEwMjQqKjMsCiAgICAgICAgICAgICAgICAgICAgICAgICJ0b3RhbCI6ICB1c2FnZS50b3RhbCAvIDEwMjQqKjMsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJwY3QiOiAgICB1c2FnZS5wZXJjZW50IC8gMTAwLjAsCiAgICAgICAgICAgICAgICAgICAgfSkKICAg"
    "ICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICAgICAgIyBSZXNpemUgdG8gZml0IGFsbCBkcml2ZXMKICAgICAgICBuID0g"
    "bWF4KDEsIGxlbihzZWxmLl9kcml2ZXMpKQogICAgICAgIHNlbGYuc2V0TWluaW11bUhlaWdodChuICogMjggKyA4KQogICAgICAg"
    "IHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBwID0gUVBhaW50"
    "ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAg"
    "dywgaCA9IHNlbGYud2lkdGgoKSwgc2VsZi5oZWlnaHQoKQogICAgICAgIHAuZmlsbFJlY3QoMCwgMCwgdywgaCwgUUNvbG9yKENf"
    "QkczKSkKCiAgICAgICAgaWYgbm90IHNlbGYuX2RyaXZlczoKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfVEVYVF9ESU0p"
    "KQogICAgICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA5KSkKICAgICAgICAgICAgcC5kcmF3VGV4dCg2LCAxOCwg"
    "Ik4vQSDigJQgcHN1dGlsIHVuYXZhaWxhYmxlIikKICAgICAgICAgICAgcC5lbmQoKQogICAgICAgICAgICByZXR1cm4KCiAgICAg"
    "ICAgcm93X2ggPSAyNgogICAgICAgIHkgPSA0CiAgICAgICAgZm9yIGRydiBpbiBzZWxmLl9kcml2ZXM6CiAgICAgICAgICAgIGxl"
    "dHRlciA9IGRydlsibGV0dGVyIl0KICAgICAgICAgICAgdXNlZCAgID0gZHJ2WyJ1c2VkIl0KICAgICAgICAgICAgdG90YWwgID0g"
    "ZHJ2WyJ0b3RhbCJdCiAgICAgICAgICAgIHBjdCAgICA9IGRydlsicGN0Il0KCiAgICAgICAgICAgICMgTGFiZWwKICAgICAgICAg"
    "ICAgbGFiZWwgPSBmIntsZXR0ZXJ9ICB7dXNlZDouMWZ9L3t0b3RhbDouMGZ9R0IiCiAgICAgICAgICAgIHAuc2V0UGVuKFFDb2xv"
    "cihDX0dPTEQpKQogICAgICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA4LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAg"
    "ICAgICAgICAgIHAuZHJhd1RleHQoNiwgeSArIDEyLCBsYWJlbCkKCiAgICAgICAgICAgICMgQmFyCiAgICAgICAgICAgIGJhcl94"
    "ID0gNgogICAgICAgICAgICBiYXJfeSA9IHkgKyAxNQogICAgICAgICAgICBiYXJfdyA9IHcgLSAxMgogICAgICAgICAgICBiYXJf"
    "aCA9IDgKICAgICAgICAgICAgcC5maWxsUmVjdChiYXJfeCwgYmFyX3ksIGJhcl93LCBiYXJfaCwgUUNvbG9yKENfQkcpKQogICAg"
    "ICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19CT1JERVIpKQogICAgICAgICAgICBwLmRyYXdSZWN0KGJhcl94LCBiYXJfeSwgYmFy"
    "X3cgLSAxLCBiYXJfaCAtIDEpCgogICAgICAgICAgICBmaWxsX3cgPSBtYXgoMSwgaW50KChiYXJfdyAtIDIpICogcGN0KSkKICAg"
    "ICAgICAgICAgYmFyX2NvbG9yID0gKENfQkxPT0QgaWYgcGN0ID4gMC45IGVsc2UKICAgICAgICAgICAgICAgICAgICAgICAgIENf"
    "Q1JJTVNPTiBpZiBwY3QgPiAwLjc1IGVsc2UKICAgICAgICAgICAgICAgICAgICAgICAgIENfR09MRF9ESU0pCiAgICAgICAgICAg"
    "IGdyYWQgPSBRTGluZWFyR3JhZGllbnQoYmFyX3ggKyAxLCBiYXJfeSwgYmFyX3ggKyBmaWxsX3csIGJhcl95KQogICAgICAgICAg"
    "ICBncmFkLnNldENvbG9yQXQoMCwgUUNvbG9yKGJhcl9jb2xvcikuZGFya2VyKDE1MCkpCiAgICAgICAgICAgIGdyYWQuc2V0Q29s"
    "b3JBdCgxLCBRQ29sb3IoYmFyX2NvbG9yKSkKICAgICAgICAgICAgcC5maWxsUmVjdChiYXJfeCArIDEsIGJhcl95ICsgMSwgZmls"
    "bF93LCBiYXJfaCAtIDIsIGdyYWQpCgogICAgICAgICAgICB5ICs9IHJvd19oCgogICAgICAgIHAuZW5kKCkKCiAgICBkZWYgcmVm"
    "cmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIkNhbGwgcGVyaW9kaWNhbGx5IHRvIHVwZGF0ZSBkcml2ZSBzdGF0cy4iIiIK"
    "ICAgICAgICBzZWxmLl9yZWZyZXNoKCkKCgojIOKUgOKUgCBTUEhFUkUgV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApjbGFzcyBTcGhlcmVXaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIEZpbGxlZCBjaXJjbGUgZ2F1Z2Ug4oCUIHVz"
    "ZWQgZm9yIEJMT09EICh0b2tlbiBwb29sKSBhbmQgTUFOQSAoVlJBTSkuCiAgICBGaWxscyBmcm9tIGJvdHRvbSB1cC4gR2xhc3N5"
    "IHNoaW5lIGVmZmVjdC4gTGFiZWwgYmVsb3cuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKICAgICAg"
    "ICBsYWJlbDogc3RyLAogICAgICAgIGNvbG9yX2Z1bGw6IHN0ciwKICAgICAgICBjb2xvcl9lbXB0eTogc3RyLAogICAgICAgIHBh"
    "cmVudD1Ob25lCiAgICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYubGFiZWwgICAgICAg"
    "PSBsYWJlbAogICAgICAgIHNlbGYuY29sb3JfZnVsbCAgPSBjb2xvcl9mdWxsCiAgICAgICAgc2VsZi5jb2xvcl9lbXB0eSA9IGNv"
    "bG9yX2VtcHR5CiAgICAgICAgc2VsZi5fZmlsbCAgICAgICA9IDAuMCAgICMgMC4wIOKGkiAxLjAKICAgICAgICBzZWxmLl9hdmFp"
    "bGFibGUgID0gVHJ1ZQogICAgICAgIHNlbGYuc2V0TWluaW11bVNpemUoODAsIDEwMCkKCiAgICBkZWYgc2V0RmlsbChzZWxmLCBm"
    "cmFjdGlvbjogZmxvYXQsIGF2YWlsYWJsZTogYm9vbCA9IFRydWUpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZmlsbCAgICAgID0g"
    "bWF4KDAuMCwgbWluKDEuMCwgZnJhY3Rpb24pKQogICAgICAgIHNlbGYuX2F2YWlsYWJsZSA9IGF2YWlsYWJsZQogICAgICAgIHNl"
    "bGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBwID0gUVBhaW50ZXIo"
    "c2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywg"
    "aCA9IHNlbGYud2lkdGgoKSwgc2VsZi5oZWlnaHQoKQoKICAgICAgICByICA9IG1pbih3LCBoIC0gMjApIC8vIDIgLSA0CiAgICAg"
    "ICAgY3ggPSB3IC8vIDIKICAgICAgICBjeSA9IChoIC0gMjApIC8vIDIgKyA0CgogICAgICAgICMgRHJvcCBzaGFkb3cKICAgICAg"
    "ICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICBwLnNldEJydXNoKFFDb2xvcigwLCAwLCAwLCA4MCkpCiAgICAg"
    "ICAgcC5kcmF3RWxsaXBzZShjeCAtIHIgKyAzLCBjeSAtIHIgKyAzLCByICogMiwgciAqIDIpCgogICAgICAgICMgQmFzZSBjaXJj"
    "bGUgKGVtcHR5IGNvbG9yKQogICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKHNlbGYuY29sb3JfZW1wdHkpKQogICAgICAgIHAuc2V0"
    "UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoK"
    "ICAgICAgICAjIEZpbGwgZnJvbSBib3R0b20KICAgICAgICBpZiBzZWxmLl9maWxsID4gMC4wMSBhbmQgc2VsZi5fYXZhaWxhYmxl"
    "OgogICAgICAgICAgICBjaXJjbGVfcGF0aCA9IFFQYWludGVyUGF0aCgpCiAgICAgICAgICAgIGNpcmNsZV9wYXRoLmFkZEVsbGlw"
    "c2UoZmxvYXQoY3ggLSByKSwgZmxvYXQoY3kgLSByKSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmbG9hdChy"
    "ICogMiksIGZsb2F0KHIgKiAyKSkKCiAgICAgICAgICAgIGZpbGxfdG9wX3kgPSBjeSArIHIgLSAoc2VsZi5fZmlsbCAqIHIgKiAy"
    "KQogICAgICAgICAgICBmcm9tIFB5U2lkZTYuUXRDb3JlIGltcG9ydCBRUmVjdEYKICAgICAgICAgICAgZmlsbF9yZWN0ID0gUVJl"
    "Y3RGKGN4IC0gciwgZmlsbF90b3BfeSwgciAqIDIsIGN5ICsgciAtIGZpbGxfdG9wX3kpCiAgICAgICAgICAgIGZpbGxfcGF0aCA9"
    "IFFQYWludGVyUGF0aCgpCiAgICAgICAgICAgIGZpbGxfcGF0aC5hZGRSZWN0KGZpbGxfcmVjdCkKICAgICAgICAgICAgY2xpcHBl"
    "ZCA9IGNpcmNsZV9wYXRoLmludGVyc2VjdGVkKGZpbGxfcGF0aCkKCiAgICAgICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5v"
    "UGVuKQogICAgICAgICAgICBwLnNldEJydXNoKFFDb2xvcihzZWxmLmNvbG9yX2Z1bGwpKQogICAgICAgICAgICBwLmRyYXdQYXRo"
    "KGNsaXBwZWQpCgogICAgICAgICMgR2xhc3N5IHNoaW5lCiAgICAgICAgc2hpbmUgPSBRUmFkaWFsR3JhZGllbnQoCiAgICAgICAg"
    "ICAgIGZsb2F0KGN4IC0gciAqIDAuMyksIGZsb2F0KGN5IC0gciAqIDAuMyksIGZsb2F0KHIgKiAwLjYpCiAgICAgICAgKQogICAg"
    "ICAgIHNoaW5lLnNldENvbG9yQXQoMCwgUUNvbG9yKDI1NSwgMjU1LCAyNTUsIDU1KSkKICAgICAgICBzaGluZS5zZXRDb2xvckF0"
    "KDEsIFFDb2xvcigyNTUsIDI1NSwgMjU1LCAwKSkKICAgICAgICBwLnNldEJydXNoKHNoaW5lKQogICAgICAgIHAuc2V0UGVuKFF0"
    "LlBlblN0eWxlLk5vUGVuKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAg"
    "ICAgIyBPdXRsaW5lCiAgICAgICAgcC5zZXRCcnVzaChRdC5CcnVzaFN0eWxlLk5vQnJ1c2gpCiAgICAgICAgcC5zZXRQZW4oUVBl"
    "bihRQ29sb3Ioc2VsZi5jb2xvcl9mdWxsKSwgMSkpCiAgICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIs"
    "IHIgKiAyKQoKICAgICAgICAjIE4vQSBvdmVybGF5CiAgICAgICAgaWYgbm90IHNlbGYuX2F2YWlsYWJsZToKICAgICAgICAgICAg"
    "cC5zZXRQZW4oUUNvbG9yKENfVEVYVF9ESU0pKQogICAgICAgICAgICBwLnNldEZvbnQoUUZvbnQoIkNvdXJpZXIgTmV3IiwgOCkp"
    "CiAgICAgICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAgICAgICAgICAgIHR4dCA9ICJOL0EiCiAgICAgICAgICAgIHAuZHJh"
    "d1RleHQoY3ggLSBmbS5ob3Jpem9udGFsQWR2YW5jZSh0eHQpIC8vIDIsIGN5ICsgNCwgdHh0KQoKICAgICAgICAjIExhYmVsIGJl"
    "bG93IHNwaGVyZQogICAgICAgIGxhYmVsX3RleHQgPSAoc2VsZi5sYWJlbCBpZiBzZWxmLl9hdmFpbGFibGUgZWxzZQogICAgICAg"
    "ICAgICAgICAgICAgICAgZiJ7c2VsZi5sYWJlbH0iKQogICAgICAgIHBjdF90ZXh0ID0gZiJ7aW50KHNlbGYuX2ZpbGwgKiAxMDAp"
    "fSUiIGlmIHNlbGYuX2F2YWlsYWJsZSBlbHNlICIiCgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihzZWxmLmNvbG9yX2Z1bGwpKQog"
    "ICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDgsIFFGb250LldlaWdodC5Cb2xkKSkKICAgICAgICBmbSA9IHAuZm9u"
    "dE1ldHJpY3MoKQoKICAgICAgICBsdyA9IGZtLmhvcml6b250YWxBZHZhbmNlKGxhYmVsX3RleHQpCiAgICAgICAgcC5kcmF3VGV4"
    "dChjeCAtIGx3IC8vIDIsIGggLSAxMCwgbGFiZWxfdGV4dCkKCiAgICAgICAgaWYgcGN0X3RleHQ6CiAgICAgICAgICAgIHAuc2V0"
    "UGVuKFFDb2xvcihDX1RFWFRfRElNKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgNykpCiAgICAgICAg"
    "ICAgIGZtMiA9IHAuZm9udE1ldHJpY3MoKQogICAgICAgICAgICBwdyA9IGZtMi5ob3Jpem9udGFsQWR2YW5jZShwY3RfdGV4dCkK"
    "ICAgICAgICAgICAgcC5kcmF3VGV4dChjeCAtIHB3IC8vIDIsIGggLSAxLCBwY3RfdGV4dCkKCiAgICAgICAgcC5lbmQoKQoKCiMg"
    "4pSA4pSAIE1PT04gV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBNb29uV2lkZ2V0"
    "KFFXaWRnZXQpOgogICAgIiIiCiAgICBEcmF3biBtb29uIG9yYiB3aXRoIHBoYXNlLWFjY3VyYXRlIHNoYWRvdy4KCiAgICBQSEFT"
    "RSBDT05WRU5USU9OIChub3J0aGVybiBoZW1pc3BoZXJlLCBzdGFuZGFyZCk6CiAgICAgIC0gV2F4aW5nIChuZXfihpJmdWxsKTog"
    "aWxsdW1pbmF0ZWQgcmlnaHQgc2lkZSwgc2hhZG93IG9uIGxlZnQKICAgICAgLSBXYW5pbmcgKGZ1bGzihpJuZXcpOiBpbGx1bWlu"
    "YXRlZCBsZWZ0IHNpZGUsIHNoYWRvdyBvbiByaWdodAoKICAgIFRoZSBzaGFkb3dfc2lkZSBmbGFnIGNhbiBiZSBmbGlwcGVkIGlm"
    "IHRlc3RpbmcgcmV2ZWFscyBpdCdzIGJhY2t3YXJkcwogICAgb24gdGhpcyBtYWNoaW5lLiBTZXQgTU9PTl9TSEFET1dfRkxJUCA9"
    "IFRydWUgaW4gdGhhdCBjYXNlLgogICAgIiIiCgogICAgIyDihpAgRkxJUCBUSElTIHRvIFRydWUgaWYgbW9vbiBhcHBlYXJzIGJh"
    "Y2t3YXJkcyBkdXJpbmcgdGVzdGluZwogICAgTU9PTl9TSEFET1dfRkxJUDogYm9vbCA9IEZhbHNlCgogICAgZGVmIF9faW5pdF9f"
    "KHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9waGFzZSAg"
    "ICAgICA9IDAuMCAgICAjIDAuMD1uZXcsIDAuNT1mdWxsLCAxLjA9bmV3CiAgICAgICAgc2VsZi5fbmFtZSAgICAgICAgPSAiTkVX"
    "IE1PT04iCiAgICAgICAgc2VsZi5faWxsdW1pbmF0aW9uID0gMC4wICAgIyAwLTEwMAogICAgICAgIHNlbGYuX3N1bnJpc2UgICAg"
    "ICA9ICIwNjowMCIKICAgICAgICBzZWxmLl9zdW5zZXQgICAgICAgPSAiMTg6MzAiCiAgICAgICAgc2VsZi5fc3VuX2RhdGUgICAg"
    "ID0gTm9uZQogICAgICAgIHNlbGYuc2V0TWluaW11bVNpemUoODAsIDExMCkKICAgICAgICBzZWxmLnVwZGF0ZVBoYXNlKCkgICAg"
    "ICAgICAgIyBwb3B1bGF0ZSBjb3JyZWN0IHBoYXNlIGltbWVkaWF0ZWx5CiAgICAgICAgc2VsZi5fZmV0Y2hfc3VuX2FzeW5jKCkK"
    "CiAgICBkZWYgX2ZldGNoX3N1bl9hc3luYyhzZWxmKSAtPiBOb25lOgogICAgICAgIGRlZiBfZmV0Y2goKToKICAgICAgICAgICAg"
    "c3IsIHNzID0gZ2V0X3N1bl90aW1lcygpCiAgICAgICAgICAgIHNlbGYuX3N1bnJpc2UgPSBzcgogICAgICAgICAgICBzZWxmLl9z"
    "dW5zZXQgID0gc3MKICAgICAgICAgICAgc2VsZi5fc3VuX2RhdGUgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkuZGF0ZSgp"
    "CiAgICAgICAgICAgICMgU2NoZWR1bGUgcmVwYWludCBvbiBtYWluIHRocmVhZCB2aWEgUVRpbWVyIOKAlCBuZXZlciBjYWxsCiAg"
    "ICAgICAgICAgICMgc2VsZi51cGRhdGUoKSBkaXJlY3RseSBmcm9tIGEgYmFja2dyb3VuZCB0aHJlYWQKICAgICAgICAgICAgUVRp"
    "bWVyLnNpbmdsZVNob3QoMCwgc2VsZi51cGRhdGUpCiAgICAgICAgdGhyZWFkaW5nLlRocmVhZCh0YXJnZXQ9X2ZldGNoLCBkYWVt"
    "b249VHJ1ZSkuc3RhcnQoKQoKICAgIGRlZiB1cGRhdGVQaGFzZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3BoYXNlLCBz"
    "ZWxmLl9uYW1lLCBzZWxmLl9pbGx1bWluYXRpb24gPSBnZXRfbW9vbl9waGFzZSgpCiAgICAgICAgdG9kYXkgPSBkYXRldGltZS5u"
    "b3coKS5hc3RpbWV6b25lKCkuZGF0ZSgpCiAgICAgICAgaWYgc2VsZi5fc3VuX2RhdGUgIT0gdG9kYXk6CiAgICAgICAgICAgIHNl"
    "bGYuX2ZldGNoX3N1bl9hc3luYygpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50"
    "KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5k"
    "ZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCgogICAgICAgIHIg"
    "ID0gbWluKHcsIGggLSAzNikgLy8gMiAtIDQKICAgICAgICBjeCA9IHcgLy8gMgogICAgICAgIGN5ID0gKGggLSAzNikgLy8gMiAr"
    "IDQKCiAgICAgICAgIyBCYWNrZ3JvdW5kIGNpcmNsZSAoc3BhY2UpCiAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMjAsIDEyLCAy"
    "OCkpCiAgICAgICAgcC5zZXRQZW4oUVBlbihRQ29sb3IoQ19TSUxWRVJfRElNKSwgMSkpCiAgICAgICAgcC5kcmF3RWxsaXBzZShj"
    "eCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICBjeWNsZV9kYXkgPSBzZWxmLl9waGFzZSAqIF9MVU5BUl9DWUNM"
    "RQogICAgICAgIGlzX3dheGluZyA9IGN5Y2xlX2RheSA8IChfTFVOQVJfQ1lDTEUgLyAyKQoKICAgICAgICAjIEZ1bGwgbW9vbiBi"
    "YXNlIChtb29uIHN1cmZhY2UgY29sb3IpCiAgICAgICAgaWYgc2VsZi5faWxsdW1pbmF0aW9uID4gMToKICAgICAgICAgICAgcC5z"
    "ZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAgICAgICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDIyMCwgMjEwLCAxODUpKQogICAg"
    "ICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgU2hhZG93IGNhbGN1"
    "bGF0aW9uCiAgICAgICAgIyBpbGx1bWluYXRpb24gZ29lcyAw4oaSMTAwIHdheGluZywgMTAw4oaSMCB3YW5pbmcKICAgICAgICAj"
    "IHNoYWRvd19vZmZzZXQgY29udHJvbHMgaG93IG11Y2ggb2YgdGhlIGNpcmNsZSB0aGUgc2hhZG93IGNvdmVycwogICAgICAgIGlm"
    "IHNlbGYuX2lsbHVtaW5hdGlvbiA8IDk5OgogICAgICAgICAgICAjIGZyYWN0aW9uIG9mIGRpYW1ldGVyIHRoZSBzaGFkb3cgZWxs"
    "aXBzZSBpcyBvZmZzZXQKICAgICAgICAgICAgaWxsdW1fZnJhYyAgPSBzZWxmLl9pbGx1bWluYXRpb24gLyAxMDAuMAogICAgICAg"
    "ICAgICBzaGFkb3dfZnJhYyA9IDEuMCAtIGlsbHVtX2ZyYWMKCiAgICAgICAgICAgICMgd2F4aW5nOiBpbGx1bWluYXRlZCByaWdo"
    "dCwgc2hhZG93IExFRlQKICAgICAgICAgICAgIyB3YW5pbmc6IGlsbHVtaW5hdGVkIGxlZnQsIHNoYWRvdyBSSUdIVAogICAgICAg"
    "ICAgICAjIG9mZnNldCBtb3ZlcyB0aGUgc2hhZG93IGVsbGlwc2UgaG9yaXpvbnRhbGx5CiAgICAgICAgICAgIG9mZnNldCA9IGlu"
    "dChzaGFkb3dfZnJhYyAqIHIgKiAyKQoKICAgICAgICAgICAgaWYgTW9vbldpZGdldC5NT09OX1NIQURPV19GTElQOgogICAgICAg"
    "ICAgICAgICAgaXNfd2F4aW5nID0gbm90IGlzX3dheGluZwoKICAgICAgICAgICAgaWYgaXNfd2F4aW5nOgogICAgICAgICAgICAg"
    "ICAgIyBTaGFkb3cgb24gbGVmdCBzaWRlCiAgICAgICAgICAgICAgICBzaGFkb3dfeCA9IGN4IC0gciAtIG9mZnNldAogICAgICAg"
    "ICAgICBlbHNlOgogICAgICAgICAgICAgICAgIyBTaGFkb3cgb24gcmlnaHQgc2lkZQogICAgICAgICAgICAgICAgc2hhZG93X3gg"
    "PSBjeCAtIHIgKyBvZmZzZXQKCiAgICAgICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKDE1LCA4LCAyMikpCiAgICAgICAgICAgIHAu"
    "c2V0UGVuKFF0LlBlblN0eWxlLk5vUGVuKQoKICAgICAgICAgICAgIyBEcmF3IHNoYWRvdyBlbGxpcHNlIOKAlCBjbGlwcGVkIHRv"
    "IG1vb24gY2lyY2xlCiAgICAgICAgICAgIG1vb25fcGF0aCA9IFFQYWludGVyUGF0aCgpCiAgICAgICAgICAgIG1vb25fcGF0aC5h"
    "ZGRFbGxpcHNlKGZsb2F0KGN4IC0gciksIGZsb2F0KGN5IC0gciksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBm"
    "bG9hdChyICogMiksIGZsb2F0KHIgKiAyKSkKICAgICAgICAgICAgc2hhZG93X3BhdGggPSBRUGFpbnRlclBhdGgoKQogICAgICAg"
    "ICAgICBzaGFkb3dfcGF0aC5hZGRFbGxpcHNlKGZsb2F0KHNoYWRvd194KSwgZmxvYXQoY3kgLSByKSwKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgZmxvYXQociAqIDIpLCBmbG9hdChyICogMikpCiAgICAgICAgICAgIGNsaXBwZWRfc2hhZG93"
    "ID0gbW9vbl9wYXRoLmludGVyc2VjdGVkKHNoYWRvd19wYXRoKQogICAgICAgICAgICBwLmRyYXdQYXRoKGNsaXBwZWRfc2hhZG93"
    "KQoKICAgICAgICAjIFN1YnRsZSBzdXJmYWNlIGRldGFpbCAoY3JhdGVycyBpbXBsaWVkIGJ5IHNsaWdodCB0ZXh0dXJlIGdyYWRp"
    "ZW50KQogICAgICAgIHNoaW5lID0gUVJhZGlhbEdyYWRpZW50KGZsb2F0KGN4IC0gciAqIDAuMiksIGZsb2F0KGN5IC0gciAqIDAu"
    "MiksCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZmxvYXQociAqIDAuOCkpCiAgICAgICAgc2hpbmUuc2V0Q29sb3JB"
    "dCgwLCBRQ29sb3IoMjU1LCAyNTUsIDI0MCwgMzApKQogICAgICAgIHNoaW5lLnNldENvbG9yQXQoMSwgUUNvbG9yKDIwMCwgMTgw"
    "LCAxNDAsIDUpKQogICAgICAgIHAuc2V0QnJ1c2goc2hpbmUpCiAgICAgICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCiAg"
    "ICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIE91dGxpbmUKICAgICAg"
    "ICBwLnNldEJydXNoKFF0LkJydXNoU3R5bGUuTm9CcnVzaCkKICAgICAgICBwLnNldFBlbihRUGVuKFFDb2xvcihDX1NJTFZFUiks"
    "IDEpKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAgICAgIyBQaGFzZSBu"
    "YW1lIGJlbG93IG1vb24KICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19TSUxWRVIpKQogICAgICAgIHAuc2V0Rm9udChRRm9udChE"
    "RUNLX0ZPTlQsIDcsIFFGb250LldlaWdodC5Cb2xkKSkKICAgICAgICBmbSA9IHAuZm9udE1ldHJpY3MoKQogICAgICAgIG53ID0g"
    "Zm0uaG9yaXpvbnRhbEFkdmFuY2Uoc2VsZi5fbmFtZSkKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gbncgLy8gMiwgY3kgKyByICsg"
    "MTQsIHNlbGYuX25hbWUpCgogICAgICAgICMgSWxsdW1pbmF0aW9uIHBlcmNlbnRhZ2UKICAgICAgICBpbGx1bV9zdHIgPSBmIntz"
    "ZWxmLl9pbGx1bWluYXRpb246LjBmfSUiCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfVEVYVF9ESU0pKQogICAgICAgIHAuc2V0"
    "Rm9udChRRm9udChERUNLX0ZPTlQsIDcpKQogICAgICAgIGZtMiA9IHAuZm9udE1ldHJpY3MoKQogICAgICAgIGl3ID0gZm0yLmhv"
    "cml6b250YWxBZHZhbmNlKGlsbHVtX3N0cikKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gaXcgLy8gMiwgY3kgKyByICsgMjQsIGls"
    "bHVtX3N0cikKCiAgICAgICAgIyBTdW4gdGltZXMgYXQgdmVyeSBib3R0b20KICAgICAgICBzdW5fc3RyID0gZiLimIAge3NlbGYu"
    "X3N1bnJpc2V9ICDimL0ge3NlbGYuX3N1bnNldH0iCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfR09MRF9ESU0pKQogICAgICAg"
    "IHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDcpKQogICAgICAgIGZtMyA9IHAuZm9udE1ldHJpY3MoKQogICAgICAgIHN3ID0g"
    "Zm0zLmhvcml6b250YWxBZHZhbmNlKHN1bl9zdHIpCiAgICAgICAgcC5kcmF3VGV4dChjeCAtIHN3IC8vIDIsIGggLSAyLCBzdW5f"
    "c3RyKQoKICAgICAgICBwLmVuZCgpCgoKIyDilIDilIAgRU1PVElPTiBCTE9DSyDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKY2xhc3MgRW1vdGlvbkJsb2NrKFFXaWRnZXQpOgogICAgIiIiCiAgICBDb2xsYXBzaWJsZSBlbW90aW9uIGhpc3Rvcnkg"
    "cGFuZWwuCiAgICBTaG93cyBjb2xvci1jb2RlZCBjaGlwczog4pymIEVNT1RJT05fTkFNRSAgSEg6TU0KICAgIFNpdHMgbmV4dCB0"
    "byB0aGUgTWlycm9yIChmYWNlIHdpZGdldCkgaW4gdGhlIGJvdHRvbSBibG9jayByb3cuCiAgICBDb2xsYXBzZXMgdG8ganVzdCB0"
    "aGUgaGVhZGVyIHN0cmlwLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBl"
    "cigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9oaXN0b3J5OiBsaXN0W3R1cGxlW3N0ciwgc3RyXV0gPSBbXSAgIyAo"
    "ZW1vdGlvbiwgdGltZXN0YW1wKQogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gVHJ1ZQogICAgICAgIHNlbGYuX21heF9lbnRyaWVz"
    "ID0gMzAKCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5z"
    "KDAsIDAsIDAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoMCkKCiAgICAgICAgIyBIZWFkZXIgcm93CiAgICAgICAgaGVh"
    "ZGVyID0gUVdpZGdldCgpCiAgICAgICAgaGVhZGVyLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgIGhlYWRlci5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGJvcmRlci1ib3R0b206IDFweCBzb2xpZCB7Q19DUklNU09O"
    "X0RJTX07IgogICAgICAgICkKICAgICAgICBobCA9IFFIQm94TGF5b3V0KGhlYWRlcikKICAgICAgICBobC5zZXRDb250ZW50c01h"
    "cmdpbnMoNiwgMCwgNCwgMCkKICAgICAgICBobC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGxibCA9IFFMYWJlbCgi4p2nIEVNT1RJ"
    "T05BTCBSRUNPUkQiKQogICAgICAgIGxibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9u"
    "dC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBz"
    "ZXJpZjsgbGV0dGVyLXNwYWNpbmc6IDFweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0"
    "biA9IFFUb29sQnV0dG9uKCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldEZpeGVkU2l6ZSgxNiwgMTYpCiAgICAgICAgc2Vs"
    "Zi5fdG9nZ2xlX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHRyYW5zcGFyZW50OyBjb2xvcjog"
    "e0NfR09MRH07IGJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0"
    "bi5zZXRUZXh0KCLilrwiKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZSkKCiAg"
    "ICAgICAgaGwuYWRkV2lkZ2V0KGxibCkKICAgICAgICBobC5hZGRTdHJldGNoKCkKICAgICAgICBobC5hZGRXaWRnZXQoc2VsZi5f"
    "dG9nZ2xlX2J0bikKCiAgICAgICAgIyBTY3JvbGwgYXJlYSBmb3IgZW1vdGlvbiBjaGlwcwogICAgICAgIHNlbGYuX3Njcm9sbCA9"
    "IFFTY3JvbGxBcmVhKCkKICAgICAgICBzZWxmLl9zY3JvbGwuc2V0V2lkZ2V0UmVzaXphYmxlKFRydWUpCiAgICAgICAgc2VsZi5f"
    "c2Nyb2xsLnNldEhvcml6b250YWxTY3JvbGxCYXJQb2xpY3koCiAgICAgICAgICAgIFF0LlNjcm9sbEJhclBvbGljeS5TY3JvbGxC"
    "YXJBbHdheXNPZmYpCiAgICAgICAgc2VsZi5fc2Nyb2xsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDog"
    "e0NfQkcyfTsgYm9yZGVyOiBub25lOyIKICAgICAgICApCgogICAgICAgIHNlbGYuX2NoaXBfY29udGFpbmVyID0gUVdpZGdldCgp"
    "CiAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQgPSBRVkJveExheW91dChzZWxmLl9jaGlwX2NvbnRhaW5lcikKICAgICAgICBzZWxm"
    "Ll9jaGlwX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5zZXRT"
    "cGFjaW5nKDIpCiAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQuYWRkU3RyZXRjaCgpCiAgICAgICAgc2VsZi5fc2Nyb2xsLnNldFdp"
    "ZGdldChzZWxmLl9jaGlwX2NvbnRhaW5lcikKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChoZWFkZXIpCiAgICAgICAgbGF5b3V0"
    "LmFkZFdpZGdldChzZWxmLl9zY3JvbGwpCgogICAgICAgIHNlbGYuc2V0TWluaW11bVdpZHRoKDEzMCkKCiAgICBkZWYgX3RvZ2ds"
    "ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAgICAgICAgc2VsZi5f"
    "c2Nyb2xsLnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRUZXh0KCLilrwiIGlm"
    "IHNlbGYuX2V4cGFuZGVkIGVsc2UgIuKWsiIpCiAgICAgICAgc2VsZi51cGRhdGVHZW9tZXRyeSgpCgogICAgZGVmIGFkZEVtb3Rp"
    "b24oc2VsZiwgZW1vdGlvbjogc3RyLCB0aW1lc3RhbXA6IHN0ciA9ICIiKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCB0aW1lc3Rh"
    "bXA6CiAgICAgICAgICAgIHRpbWVzdGFtcCA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTSIpCiAgICAgICAgc2VsZi5f"
    "aGlzdG9yeS5pbnNlcnQoMCwgKGVtb3Rpb24sIHRpbWVzdGFtcCkpCiAgICAgICAgc2VsZi5faGlzdG9yeSA9IHNlbGYuX2hpc3Rv"
    "cnlbOnNlbGYuX21heF9lbnRyaWVzXQogICAgICAgIHNlbGYuX3JlYnVpbGRfY2hpcHMoKQoKICAgIGRlZiBfcmVidWlsZF9jaGlw"
    "cyhzZWxmKSAtPiBOb25lOgogICAgICAgICMgQ2xlYXIgZXhpc3RpbmcgY2hpcHMgKGtlZXAgdGhlIHN0cmV0Y2ggYXQgZW5kKQog"
    "ICAgICAgIHdoaWxlIHNlbGYuX2NoaXBfbGF5b3V0LmNvdW50KCkgPiAxOgogICAgICAgICAgICBpdGVtID0gc2VsZi5fY2hpcF9s"
    "YXlvdXQudGFrZUF0KDApCiAgICAgICAgICAgIGlmIGl0ZW0ud2lkZ2V0KCk6CiAgICAgICAgICAgICAgICBpdGVtLndpZGdldCgp"
    "LmRlbGV0ZUxhdGVyKCkKCiAgICAgICAgZm9yIGVtb3Rpb24sIHRzIGluIHNlbGYuX2hpc3Rvcnk6CiAgICAgICAgICAgIGNvbG9y"
    "ID0gRU1PVElPTl9DT0xPUlMuZ2V0KGVtb3Rpb24sIENfVEVYVF9ESU0pCiAgICAgICAgICAgIGNoaXAgPSBRTGFiZWwoZiLinKYg"
    "e2Vtb3Rpb24udXBwZXIoKX0gIHt0c30iKQogICAgICAgICAgICBjaGlwLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBm"
    "ImNvbG9yOiB7Y29sb3J9OyBmb250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgIgogICAgICAg"
    "ICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyAiCiAgICAgICAgICAg"
    "ICAgICBmInBhZGRpbmc6IDFweCA0cHg7IGJvcmRlci1yYWRpdXM6IDJweDsiCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2Vs"
    "Zi5fY2hpcF9sYXlvdXQuaW5zZXJ0V2lkZ2V0KAogICAgICAgICAgICAgICAgc2VsZi5fY2hpcF9sYXlvdXQuY291bnQoKSAtIDEs"
    "IGNoaXAKICAgICAgICAgICAgKQoKICAgIGRlZiBjbGVhcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2hpc3RvcnkuY2xl"
    "YXIoKQogICAgICAgIHNlbGYuX3JlYnVpbGRfY2hpcHMoKQoKCiMg4pSA4pSAIE1JUlJPUiBXSURHRVQg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIE1pcnJvcldpZGdldChRTGFiZWwpOgogICAgIiIiCiAgICBGYWNlIGltYWdlIGRpc3Bs"
    "YXkg4oCUICdUaGUgTWlycm9yJy4KICAgIER5bmFtaWNhbGx5IGxvYWRzIGFsbCB7RkFDRV9QUkVGSVh9XyoucG5nIGZpbGVzIGZy"
    "b20gY29uZmlnIHBhdGhzLmZhY2VzLgogICAgQXV0by1tYXBzIGZpbGVuYW1lIHRvIGVtb3Rpb24ga2V5OgogICAgICAgIHtGQUNF"
    "X1BSRUZJWH1fQWxlcnQucG5nICAgICDihpIgImFsZXJ0IgogICAgICAgIHtGQUNFX1BSRUZJWH1fU2FkX0NyeWluZy5wbmcg4oaS"
    "ICJzYWQiCiAgICAgICAge0ZBQ0VfUFJFRklYfV9DaGVhdF9Nb2RlLnBuZyDihpIgImNoZWF0bW9kZSIKICAgIEZhbGxzIGJhY2sg"
    "dG8gbmV1dHJhbCwgdGhlbiB0byBnb3RoaWMgcGxhY2Vob2xkZXIgaWYgbm8gaW1hZ2VzIGZvdW5kLgogICAgTWlzc2luZyBmYWNl"
    "cyBkZWZhdWx0IHRvIG5ldXRyYWwg4oCUIG5vIGNyYXNoLCBubyBoYXJkY29kZWQgbGlzdCByZXF1aXJlZC4KICAgICIiIgoKICAg"
    "ICMgU3BlY2lhbCBzdGVtIOKGkiBlbW90aW9uIGtleSBtYXBwaW5ncyAobG93ZXJjYXNlIHN0ZW0gYWZ0ZXIgTW9yZ2FubmFfKQog"
    "ICAgX1NURU1fVE9fRU1PVElPTjogZGljdFtzdHIsIHN0cl0gPSB7CiAgICAgICAgInNhZF9jcnlpbmciOiAgInNhZCIsCiAgICAg"
    "ICAgImNoZWF0X21vZGUiOiAgImNoZWF0bW9kZSIsCiAgICB9CgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToK"
    "ICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9mYWNlc19kaXIgICA9IGNmZ19wYXRoKCJmYWNl"
    "cyIpCiAgICAgICAgc2VsZi5fY2FjaGU6IGRpY3Rbc3RyLCBRUGl4bWFwXSA9IHt9CiAgICAgICAgc2VsZi5fY3VycmVudCAgICAg"
    "PSAibmV1dHJhbCIKICAgICAgICBzZWxmLl93YXJuZWQ6IHNldFtzdHJdID0gc2V0KCkKCiAgICAgICAgc2VsZi5zZXRNaW5pbXVt"
    "U2l6ZSgxNjAsIDE2MCkKICAgICAgICBzZWxmLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAg"
    "ICAgIHNlbGYuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xp"
    "ZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXItcmFkaXVzOiAycHg7IgogICAgICAgICkKCiAgICAgICAg"
    "UVRpbWVyLnNpbmdsZVNob3QoMzAwLCBzZWxmLl9wcmVsb2FkKQoKICAgIGRlZiBfcHJlbG9hZChzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgICIiIgogICAgICAgIFNjYW4gRmFjZXMvIGRpcmVjdG9yeSBmb3IgYWxsIHtGQUNFX1BSRUZJWH1fKi5wbmcgZmlsZXMuCiAg"
    "ICAgICAgQnVpbGQgZW1vdGlvbuKGknBpeG1hcCBjYWNoZSBkeW5hbWljYWxseS4KICAgICAgICBObyBoYXJkY29kZWQgbGlzdCDi"
    "gJQgd2hhdGV2ZXIgaXMgaW4gdGhlIGZvbGRlciBpcyBhdmFpbGFibGUuCiAgICAgICAgIiIiCiAgICAgICAgaWYgbm90IHNlbGYu"
    "X2ZhY2VzX2Rpci5leGlzdHMoKToKICAgICAgICAgICAgc2VsZi5fZHJhd19wbGFjZWhvbGRlcigpCiAgICAgICAgICAgIHJldHVy"
    "bgoKICAgICAgICBmb3IgaW1nX3BhdGggaW4gc2VsZi5fZmFjZXNfZGlyLmdsb2IoZiJ7RkFDRV9QUkVGSVh9XyoucG5nIik6CiAg"
    "ICAgICAgICAgICMgc3RlbSA9IGV2ZXJ5dGhpbmcgYWZ0ZXIgIk1vcmdhbm5hXyIgd2l0aG91dCAucG5nCiAgICAgICAgICAgIHJh"
    "d19zdGVtID0gaW1nX3BhdGguc3RlbVtsZW4oZiJ7RkFDRV9QUkVGSVh9XyIpOl0gICAgIyBlLmcuICJTYWRfQ3J5aW5nIgogICAg"
    "ICAgICAgICBzdGVtX2xvd2VyID0gcmF3X3N0ZW0ubG93ZXIoKSAgICAgICAgICAgICAgICAgICAgICAgICAgIyAic2FkX2NyeWlu"
    "ZyIKCiAgICAgICAgICAgICMgTWFwIHNwZWNpYWwgc3RlbXMgdG8gZW1vdGlvbiBrZXlzCiAgICAgICAgICAgIGVtb3Rpb24gPSBz"
    "ZWxmLl9TVEVNX1RPX0VNT1RJT04uZ2V0KHN0ZW1fbG93ZXIsIHN0ZW1fbG93ZXIpCgogICAgICAgICAgICBweCA9IFFQaXhtYXAo"
    "c3RyKGltZ19wYXRoKSkKICAgICAgICAgICAgaWYgbm90IHB4LmlzTnVsbCgpOgogICAgICAgICAgICAgICAgc2VsZi5fY2FjaGVb"
    "ZW1vdGlvbl0gPSBweAoKICAgICAgICBpZiBzZWxmLl9jYWNoZToKICAgICAgICAgICAgc2VsZi5fcmVuZGVyKCJuZXV0cmFsIikK"
    "ICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLl9kcmF3X3BsYWNlaG9sZGVyKCkKCiAgICBkZWYgX3JlbmRlcihzZWxmLCBm"
    "YWNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgZmFjZSA9IGZhY2UubG93ZXIoKS5zdHJpcCgpCiAgICAgICAgaWYgZmFjZSBub3Qg"
    "aW4gc2VsZi5fY2FjaGU6CiAgICAgICAgICAgIGlmIGZhY2Ugbm90IGluIHNlbGYuX3dhcm5lZCBhbmQgZmFjZSAhPSAibmV1dHJh"
    "bCI6CiAgICAgICAgICAgICAgICBwcmludChmIltNSVJST1JdW1dBUk5dIEZhY2Ugbm90IGluIGNhY2hlOiB7ZmFjZX0g4oCUIHVz"
    "aW5nIG5ldXRyYWwiKQogICAgICAgICAgICAgICAgc2VsZi5fd2FybmVkLmFkZChmYWNlKQogICAgICAgICAgICBmYWNlID0gIm5l"
    "dXRyYWwiCiAgICAgICAgaWYgZmFjZSBub3QgaW4gc2VsZi5fY2FjaGU6CiAgICAgICAgICAgIHNlbGYuX2RyYXdfcGxhY2Vob2xk"
    "ZXIoKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9jdXJyZW50ID0gZmFjZQogICAgICAgIHB4ID0gc2VsZi5fY2Fj"
    "aGVbZmFjZV0KICAgICAgICBzY2FsZWQgPSBweC5zY2FsZWQoCiAgICAgICAgICAgIHNlbGYud2lkdGgoKSAtIDQsCiAgICAgICAg"
    "ICAgIHNlbGYuaGVpZ2h0KCkgLSA0LAogICAgICAgICAgICBRdC5Bc3BlY3RSYXRpb01vZGUuS2VlcEFzcGVjdFJhdGlvLAogICAg"
    "ICAgICAgICBRdC5UcmFuc2Zvcm1hdGlvbk1vZGUuU21vb3RoVHJhbnNmb3JtYXRpb24sCiAgICAgICAgKQogICAgICAgIHNlbGYu"
    "c2V0UGl4bWFwKHNjYWxlZCkKICAgICAgICBzZWxmLnNldFRleHQoIiIpCgogICAgZGVmIF9kcmF3X3BsYWNlaG9sZGVyKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgc2VsZi5jbGVhcigpCiAgICAgICAgc2VsZi5zZXRUZXh0KCLinKZcbuKdp1xu4pymIikKICAgICAg"
    "ICBzZWxmLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQg"
    "e0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiAyNHB4OyBi"
    "b3JkZXItcmFkaXVzOiAycHg7IgogICAgICAgICkKCiAgICBkZWYgc2V0X2ZhY2Uoc2VsZiwgZmFjZTogc3RyKSAtPiBOb25lOgog"
    "ICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDAsIGxhbWJkYTogc2VsZi5fcmVuZGVyKGZhY2UpKQoKICAgIGRlZiByZXNpemVFdmVu"
    "dChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBzdXBlcigpLnJlc2l6ZUV2ZW50KGV2ZW50KQogICAgICAgIGlmIHNlbGYu"
    "X2NhY2hlOgogICAgICAgICAgICBzZWxmLl9yZW5kZXIoc2VsZi5fY3VycmVudCkKCiAgICBAcHJvcGVydHkKICAgIGRlZiBjdXJy"
    "ZW50X2ZhY2Uoc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9jdXJyZW50CgoKIyDilIDilIAgVkFNUElSRSBTVEFU"
    "RSBTVFJJUCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgQ3ljbGVXaWRnZXQoTW9vbldpZGdldCk6CiAgICAiIiJHZW5lcmljIGN5Y2xl"
    "IHZpc3VhbGl6YXRpb24gd2lkZ2V0IChjdXJyZW50bHkgbHVuYXItcGhhc2UgZHJpdmVuKS4iIiIKCgpjbGFzcyBWYW1waXJlU3Rh"
    "dGVTdHJpcChRV2lkZ2V0KToKICAgICIiIgogICAgRnVsbC13aWR0aCBzdGF0dXMgYmFyIHNob3dpbmc6CiAgICAgIFsg4pymIFZB"
    "TVBJUkVfU1RBVEUgIOKAoiAgSEg6TU0gIOKAoiAg4piAIFNVTlJJU0UgIOKYvSBTVU5TRVQgIOKAoiAgTU9PTiBQSEFTRSAgSUxM"
    "VU0lIF0KICAgIEFsd2F5cyB2aXNpYmxlLCBuZXZlciBjb2xsYXBzZXMuCiAgICBVcGRhdGVzIGV2ZXJ5IG1pbnV0ZSB2aWEgZXh0"
    "ZXJuYWwgUVRpbWVyIGNhbGwgdG8gcmVmcmVzaCgpLgogICAgQ29sb3ItY29kZWQgYnkgY3VycmVudCB2YW1waXJlIHN0YXRlLgog"
    "ICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVu"
    "dCkKICAgICAgICBzZWxmLl9sYWJlbF9wcmVmaXggPSAiU1RBVEUiCiAgICAgICAgc2VsZi5fc3RhdGUgICAgID0gZ2V0X3ZhbXBp"
    "cmVfc3RhdGUoKQogICAgICAgIHNlbGYuX3RpbWVfc3RyICA9ICIiCiAgICAgICAgc2VsZi5fc3VucmlzZSAgID0gIjA2OjAwIgog"
    "ICAgICAgIHNlbGYuX3N1bnNldCAgICA9ICIxODozMCIKICAgICAgICBzZWxmLl9zdW5fZGF0ZSAgPSBOb25lCiAgICAgICAgc2Vs"
    "Zi5fbW9vbl9uYW1lID0gIk5FVyBNT09OIgogICAgICAgIHNlbGYuX2lsbHVtICAgICA9IDAuMAogICAgICAgIHNlbGYuc2V0Rml4"
    "ZWRIZWlnaHQoMjgpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyLXRvcDog"
    "MXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiKQogICAgICAgIHNlbGYuX2ZldGNoX3N1bl9hc3luYygpCiAgICAgICAgc2VsZi5y"
    "ZWZyZXNoKCkKCiAgICBkZWYgc2V0X2xhYmVsKHNlbGYsIGxhYmVsOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fbGFiZWxf"
    "cHJlZml4ID0gKGxhYmVsIG9yICJTVEFURSIpLnN0cmlwKCkudXBwZXIoKQogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYg"
    "X2ZldGNoX3N1bl9hc3luYyhzZWxmKSAtPiBOb25lOgogICAgICAgIGRlZiBfZigpOgogICAgICAgICAgICBzciwgc3MgPSBnZXRf"
    "c3VuX3RpbWVzKCkKICAgICAgICAgICAgc2VsZi5fc3VucmlzZSA9IHNyCiAgICAgICAgICAgIHNlbGYuX3N1bnNldCAgPSBzcwog"
    "ICAgICAgICAgICBzZWxmLl9zdW5fZGF0ZSA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5kYXRlKCkKICAgICAgICAgICAg"
    "IyBTY2hlZHVsZSByZXBhaW50IG9uIG1haW4gdGhyZWFkIOKAlCBuZXZlciBjYWxsIHVwZGF0ZSgpIGZyb20KICAgICAgICAgICAg"
    "IyBhIGJhY2tncm91bmQgdGhyZWFkLCBpdCBjYXVzZXMgUVRocmVhZCBjcmFzaCBvbiBzdGFydHVwCiAgICAgICAgICAgIFFUaW1l"
    "ci5zaW5nbGVTaG90KDAsIHNlbGYudXBkYXRlKQogICAgICAgIHRocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9mLCBkYWVtb249VHJ1"
    "ZSkuc3RhcnQoKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhdGUgICAgID0gZ2V0X3Zh"
    "bXBpcmVfc3RhdGUoKQogICAgICAgIHNlbGYuX3RpbWVfc3RyICA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS5zdHJmdGlt"
    "ZSgiJVgiKQogICAgICAgIHRvZGF5ID0gZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpLmRhdGUoKQogICAgICAgIGlmIHNlbGYu"
    "X3N1bl9kYXRlICE9IHRvZGF5OgogICAgICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQogICAgICAgIF8sIHNlbGYuX21v"
    "b25fbmFtZSwgc2VsZi5faWxsdW0gPSBnZXRfbW9vbl9waGFzZSgpCiAgICAgICAgc2VsZi51cGRhdGUoKQoKICAgIGRlZiBwYWlu"
    "dEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFpbnRlcihzZWxmKQogICAgICAgIHAuc2V0UmVuZGVy"
    "SGludChRUGFpbnRlci5SZW5kZXJIaW50LkFudGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxmLmhl"
    "aWdodCgpCgogICAgICAgIHAuZmlsbFJlY3QoMCwgMCwgdywgaCwgUUNvbG9yKENfQkcyKSkKCiAgICAgICAgc3RhdGVfY29sb3Ig"
    "PSBnZXRfdmFtcGlyZV9zdGF0ZV9jb2xvcihzZWxmLl9zdGF0ZSkKICAgICAgICB0ZXh0ID0gKAogICAgICAgICAgICBmIuKcpiAg"
    "e3NlbGYuX2xhYmVsX3ByZWZpeH06IHtzZWxmLl9zdGF0ZX0gIOKAoiAge3NlbGYuX3RpbWVfc3RyfSAg4oCiICAiCiAgICAgICAg"
    "ICAgIGYi4piAIHtzZWxmLl9zdW5yaXNlfSAgICDimL0ge3NlbGYuX3N1bnNldH0gIOKAoiAgIgogICAgICAgICAgICBmIntzZWxm"
    "Ll9tb29uX25hbWV9ICB7c2VsZi5faWxsdW06LjBmfSUiCiAgICAgICAgKQoKICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19G"
    "T05ULCA5LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKHN0YXRlX2NvbG9yKSkKICAgICAgICBm"
    "bSA9IHAuZm9udE1ldHJpY3MoKQogICAgICAgIHR3ID0gZm0uaG9yaXpvbnRhbEFkdmFuY2UodGV4dCkKICAgICAgICBwLmRyYXdU"
    "ZXh0KCh3IC0gdHcpIC8vIDIsIGggLSA3LCB0ZXh0KQoKICAgICAgICBwLmVuZCgpCgoKY2xhc3MgTWluaUNhbGVuZGFyV2lkZ2V0"
    "KFFXaWRnZXQpOgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBh"
    "cmVudCkKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMo"
    "MCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICBoZWFkZXIgPSBRSEJveExheW91dCgpCiAg"
    "ICAgICAgaGVhZGVyLnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHNlbGYucHJldl9idG4gPSBRUHVzaEJ1"
    "dHRvbigiPDwiKQogICAgICAgIHNlbGYubmV4dF9idG4gPSBRUHVzaEJ1dHRvbigiPj4iKQogICAgICAgIHNlbGYubW9udGhfbGJs"
    "ID0gUUxhYmVsKCIiKQogICAgICAgIHNlbGYubW9udGhfbGJsLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2Vu"
    "dGVyKQogICAgICAgIGZvciBidG4gaW4gKHNlbGYucHJldl9idG4sIHNlbGYubmV4dF9idG4pOgogICAgICAgICAgICBidG4uc2V0"
    "Rml4ZWRXaWR0aCgzNCkKICAgICAgICAgICAgYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6"
    "IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAg"
    "ICAgICBmImZvbnQtc2l6ZTogMTBweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDJweDsiCiAgICAgICAgICAgICkKICAg"
    "ICAgICBzZWxmLm1vbnRoX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiBu"
    "b25lOyBmb250LXNpemU6IDEwcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyIKICAgICAgICApCiAgICAgICAgaGVhZGVyLmFkZFdpZGdl"
    "dChzZWxmLnByZXZfYnRuKQogICAgICAgIGhlYWRlci5hZGRXaWRnZXQoc2VsZi5tb250aF9sYmwsIDEpCiAgICAgICAgaGVhZGVy"
    "LmFkZFdpZGdldChzZWxmLm5leHRfYnRuKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoaGVhZGVyKQoKICAgICAgICBzZWxmLmNh"
    "bGVuZGFyID0gUUNhbGVuZGFyV2lkZ2V0KCkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldEdyaWRWaXNpYmxlKFRydWUpCiAgICAg"
    "ICAgc2VsZi5jYWxlbmRhci5zZXRWZXJ0aWNhbEhlYWRlckZvcm1hdChRQ2FsZW5kYXJXaWRnZXQuVmVydGljYWxIZWFkZXJGb3Jt"
    "YXQuTm9WZXJ0aWNhbEhlYWRlcikKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldE5hdmlnYXRpb25CYXJWaXNpYmxlKEZhbHNlKQog"
    "ICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJRQ2FsZW5kYXJXaWRnZXQgUVdpZGdldHt7"
    "YWx0ZXJuYXRlLWJhY2tncm91bmQtY29sb3I6e0NfQkcyfTt9fSAiCiAgICAgICAgICAgIGYiUVRvb2xCdXR0b257e2NvbG9yOntD"
    "X0dPTER9O319ICIKICAgICAgICAgICAgZiJRQ2FsZW5kYXJXaWRnZXQgUUFic3RyYWN0SXRlbVZpZXc6ZW5hYmxlZHt7YmFja2dy"
    "b3VuZDp7Q19CRzJ9OyBjb2xvcjojZmZmZmZmOyAiCiAgICAgICAgICAgIGYic2VsZWN0aW9uLWJhY2tncm91bmQtY29sb3I6e0Nf"
    "Q1JJTVNPTl9ESU19OyBzZWxlY3Rpb24tY29sb3I6e0NfVEVYVH07IGdyaWRsaW5lLWNvbG9yOntDX0JPUkRFUn07fX0gIgogICAg"
    "ICAgICAgICBmIlFDYWxlbmRhcldpZGdldCBRQWJzdHJhY3RJdGVtVmlldzpkaXNhYmxlZHt7Y29sb3I6IzhiOTVhMTt9fSIKICAg"
    "ICAgICApCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmNhbGVuZGFyKQoKICAgICAgICBzZWxmLnByZXZfYnRuLmNsaWNr"
    "ZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuY2FsZW5kYXIuc2hvd1ByZXZpb3VzTW9udGgoKSkKICAgICAgICBzZWxmLm5leHRfYnRu"
    "LmNsaWNrZWQuY29ubmVjdChsYW1iZGE6IHNlbGYuY2FsZW5kYXIuc2hvd05leHRNb250aCgpKQogICAgICAgIHNlbGYuY2FsZW5k"
    "YXIuY3VycmVudFBhZ2VDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fdXBkYXRlX2xhYmVsKQogICAgICAgIHNlbGYuX3VwZGF0ZV9sYWJl"
    "bCgpCiAgICAgICAgc2VsZi5fYXBwbHlfZm9ybWF0cygpCgogICAgZGVmIF91cGRhdGVfbGFiZWwoc2VsZiwgKmFyZ3MpOgogICAg"
    "ICAgIHllYXIgPSBzZWxmLmNhbGVuZGFyLnllYXJTaG93bigpCiAgICAgICAgbW9udGggPSBzZWxmLmNhbGVuZGFyLm1vbnRoU2hv"
    "d24oKQogICAgICAgIHNlbGYubW9udGhfbGJsLnNldFRleHQoZiJ7ZGF0ZSh5ZWFyLCBtb250aCwgMSkuc3RyZnRpbWUoJyVCICVZ"
    "Jyl9IikKICAgICAgICBzZWxmLl9hcHBseV9mb3JtYXRzKCkKCiAgICBkZWYgX2FwcGx5X2Zvcm1hdHMoc2VsZik6CiAgICAgICAg"
    "YmFzZSA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgYmFzZS5zZXRGb3JlZ3JvdW5kKFFDb2xvcigiI2U3ZWRmMyIpKQogICAg"
    "ICAgIHNhdHVyZGF5ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICBzYXR1cmRheS5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0dP"
    "TERfRElNKSkKICAgICAgICBzdW5kYXkgPSBRVGV4dENoYXJGb3JtYXQoKQogICAgICAgIHN1bmRheS5zZXRGb3JlZ3JvdW5kKFFD"
    "b2xvcihDX0JMT09EKSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5Nb25k"
    "YXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuVHVlc2RheSwg"
    "YmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5XZWRuZXNkYXksIGJh"
    "c2UpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuVGh1cnNkYXksIGJhc2Up"
    "CiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuRnJpZGF5LCBiYXNlKQogICAg"
    "ICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlNhdHVyZGF5LCBzYXR1cmRheSkKICAg"
    "ICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtkYXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5TdW5kYXksIHN1bmRheSkKCiAgICAg"
    "ICAgeWVhciA9IHNlbGYuY2FsZW5kYXIueWVhclNob3duKCkKICAgICAgICBtb250aCA9IHNlbGYuY2FsZW5kYXIubW9udGhTaG93"
    "bigpCiAgICAgICAgZmlyc3RfZGF5ID0gUURhdGUoeWVhciwgbW9udGgsIDEpCiAgICAgICAgZm9yIGRheSBpbiByYW5nZSgxLCBm"
    "aXJzdF9kYXkuZGF5c0luTW9udGgoKSArIDEpOgogICAgICAgICAgICBkID0gUURhdGUoeWVhciwgbW9udGgsIGRheSkKICAgICAg"
    "ICAgICAgZm10ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICAgICAgd2Vla2RheSA9IGQuZGF5T2ZXZWVrKCkKICAgICAgICAg"
    "ICAgaWYgd2Vla2RheSA9PSBRdC5EYXlPZldlZWsuU2F0dXJkYXkudmFsdWU6CiAgICAgICAgICAgICAgICBmbXQuc2V0Rm9yZWdy"
    "b3VuZChRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgICAgIGVsaWYgd2Vla2RheSA9PSBRdC5EYXlPZldlZWsuU3VuZGF5LnZh"
    "bHVlOgogICAgICAgICAgICAgICAgZm10LnNldEZvcmVncm91bmQoUUNvbG9yKENfQkxPT0QpKQogICAgICAgICAgICBlbHNlOgog"
    "ICAgICAgICAgICAgICAgZm10LnNldEZvcmVncm91bmQoUUNvbG9yKCIjZTdlZGYzIikpCiAgICAgICAgICAgIHNlbGYuY2FsZW5k"
    "YXIuc2V0RGF0ZVRleHRGb3JtYXQoZCwgZm10KQoKICAgICAgICB0b2RheV9mbXQgPSBRVGV4dENoYXJGb3JtYXQoKQogICAgICAg"
    "IHRvZGF5X2ZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcigiIzY4ZDM5YSIpKQogICAgICAgIHRvZGF5X2ZtdC5zZXRCYWNrZ3JvdW5k"
    "KFFDb2xvcigiIzE2MzgyNSIpKQogICAgICAgIHRvZGF5X2ZtdC5zZXRGb250V2VpZ2h0KFFGb250LldlaWdodC5Cb2xkKQogICAg"
    "ICAgIHNlbGYuY2FsZW5kYXIuc2V0RGF0ZVRleHRGb3JtYXQoUURhdGUuY3VycmVudERhdGUoKSwgdG9kYXlfZm10KQoKCiMg4pSA"
    "4pSAIENPTExBUFNJQkxFIEJMT0NLIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBDb2xsYXBzaWJsZUJsb2NrKFFXaWRnZXQp"
    "OgogICAgIiIiCiAgICBXcmFwcGVyIHRoYXQgYWRkcyBhIGNvbGxhcHNlL2V4cGFuZCB0b2dnbGUgdG8gYW55IHdpZGdldC4KICAg"
    "IENvbGxhcHNlcyBob3Jpem9udGFsbHkgKHJpZ2h0d2FyZCkg4oCUIGhpZGVzIGNvbnRlbnQsIGtlZXBzIGhlYWRlciBzdHJpcC4K"
    "ICAgIEhlYWRlciBzaG93cyBsYWJlbC4gVG9nZ2xlIGJ1dHRvbiBvbiByaWdodCBlZGdlIG9mIGhlYWRlci4KCiAgICBVc2FnZToK"
    "ICAgICAgICBibG9jayA9IENvbGxhcHNpYmxlQmxvY2soIuKdpyBCTE9PRCIsIFNwaGVyZVdpZGdldCguLi4pKQogICAgICAgIGxh"
    "eW91dC5hZGRXaWRnZXQoYmxvY2spCiAgICAiIiIKCiAgICB0b2dnbGVkID0gU2lnbmFsKGJvb2wpCgogICAgZGVmIF9faW5pdF9f"
    "KHNlbGYsIGxhYmVsOiBzdHIsIGNvbnRlbnQ6IFFXaWRnZXQsCiAgICAgICAgICAgICAgICAgZXhwYW5kZWQ6IGJvb2wgPSBUcnVl"
    "LCBtaW5fd2lkdGg6IGludCA9IDkwLAogICAgICAgICAgICAgICAgIHJlc2VydmVfd2lkdGg6IGJvb2wgPSBGYWxzZSwKICAgICAg"
    "ICAgICAgICAgICBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fZXhw"
    "YW5kZWQgICAgICAgPSBleHBhbmRlZAogICAgICAgIHNlbGYuX21pbl93aWR0aCAgICAgID0gbWluX3dpZHRoCiAgICAgICAgc2Vs"
    "Zi5fcmVzZXJ2ZV93aWR0aCAgPSByZXNlcnZlX3dpZHRoCiAgICAgICAgc2VsZi5fY29udGVudCAgICAgICAgPSBjb250ZW50Cgog"
    "ICAgICAgIG1haW4gPSBRVkJveExheW91dChzZWxmKQogICAgICAgIG1haW4uc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDAp"
    "CiAgICAgICAgbWFpbi5zZXRTcGFjaW5nKDApCgogICAgICAgICMgSGVhZGVyCiAgICAgICAgc2VsZi5faGVhZGVyID0gUVdpZGdl"
    "dCgpCiAgICAgICAgc2VsZi5faGVhZGVyLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAgIHNlbGYuX2hlYWRlci5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGJvcmRlci1ib3R0b206IDFweCBzb2xpZCB7Q19DUklNU09O"
    "X0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXItdG9wOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAg"
    "ICAgICAgaGwgPSBRSEJveExheW91dChzZWxmLl9oZWFkZXIpCiAgICAgICAgaGwuc2V0Q29udGVudHNNYXJnaW5zKDYsIDAsIDQs"
    "IDApCiAgICAgICAgaGwuc2V0U3BhY2luZyg0KQoKICAgICAgICBzZWxmLl9sYmwgPSBRTGFiZWwobGFiZWwpCiAgICAgICAgc2Vs"
    "Zi5fbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDlweDsgZm9udC13"
    "ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2lu"
    "ZzogMXB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKCiAgICAgICAgc2VsZi5fYnRuID0gUVRvb2xCdXR0b24oKQogICAgICAg"
    "IHNlbGYuX2J0bi5zZXRGaXhlZFNpemUoMTYsIDE2KQogICAgICAgIHNlbGYuX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmImJhY2tncm91bmQ6IHRyYW5zcGFyZW50OyBjb2xvcjoge0NfR09MRF9ESU19OyBib3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTog"
    "MTBweDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2J0bi5zZXRUZXh0KCI8IikKICAgICAgICBzZWxmLl9idG4uY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX3RvZ2dsZSkKCiAgICAgICAgaGwuYWRkV2lkZ2V0KHNlbGYuX2xibCkKICAgICAgICBobC5hZGRTdHJldGNo"
    "KCkKICAgICAgICBobC5hZGRXaWRnZXQoc2VsZi5fYnRuKQoKICAgICAgICBtYWluLmFkZFdpZGdldChzZWxmLl9oZWFkZXIpCiAg"
    "ICAgICAgbWFpbi5hZGRXaWRnZXQoc2VsZi5fY29udGVudCkKCiAgICAgICAgc2VsZi5fYXBwbHlfc3RhdGUoKQoKICAgIGRlZiBp"
    "c19leHBhbmRlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBzZWxmLl9leHBhbmRlZAoKICAgIGRlZiBfdG9nZ2xlKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5kZWQKICAgICAgICBzZWxmLl9hcHBs"
    "eV9zdGF0ZSgpCiAgICAgICAgc2VsZi50b2dnbGVkLmVtaXQoc2VsZi5fZXhwYW5kZWQpCgogICAgZGVmIF9hcHBseV9zdGF0ZShz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0VmlzaWJsZShzZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxm"
    "Ll9idG4uc2V0VGV4dCgiPCIgaWYgc2VsZi5fZXhwYW5kZWQgZWxzZSAiPiIpCgogICAgICAgICMgUmVzZXJ2ZSBmaXhlZCBzbG90"
    "IHdpZHRoIHdoZW4gcmVxdWVzdGVkICh1c2VkIGJ5IG1pZGRsZSBsb3dlciBibG9jaykKICAgICAgICBpZiBzZWxmLl9yZXNlcnZl"
    "X3dpZHRoOgogICAgICAgICAgICBzZWxmLnNldE1pbmltdW1XaWR0aChzZWxmLl9taW5fd2lkdGgpCiAgICAgICAgICAgIHNlbGYu"
    "c2V0TWF4aW11bVdpZHRoKDE2Nzc3MjE1KQogICAgICAgIGVsaWYgc2VsZi5fZXhwYW5kZWQ6CiAgICAgICAgICAgIHNlbGYuc2V0"
    "TWluaW11bVdpZHRoKHNlbGYuX21pbl93aWR0aCkKICAgICAgICAgICAgc2VsZi5zZXRNYXhpbXVtV2lkdGgoMTY3NzcyMTUpICAj"
    "IHVuY29uc3RyYWluZWQKICAgICAgICBlbHNlOgogICAgICAgICAgICAjIENvbGxhcHNlZDoganVzdCB0aGUgaGVhZGVyIHN0cmlw"
    "IChsYWJlbCArIGJ1dHRvbikKICAgICAgICAgICAgY29sbGFwc2VkX3cgPSBzZWxmLl9oZWFkZXIuc2l6ZUhpbnQoKS53aWR0aCgp"
    "CiAgICAgICAgICAgIHNlbGYuc2V0Rml4ZWRXaWR0aChtYXgoNjAsIGNvbGxhcHNlZF93KSkKCiAgICAgICAgc2VsZi51cGRhdGVH"
    "ZW9tZXRyeSgpCiAgICAgICAgcGFyZW50ID0gc2VsZi5wYXJlbnRXaWRnZXQoKQogICAgICAgIGlmIHBhcmVudCBhbmQgcGFyZW50"
    "LmxheW91dCgpOgogICAgICAgICAgICBwYXJlbnQubGF5b3V0KCkuYWN0aXZhdGUoKQoKCiMg4pSA4pSAIEhBUkRXQVJFIFBBTkVM"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBIYXJkd2FyZVBhbmVsKFFXaWRnZXQpOgogICAgIiIiCiAgICBU"
    "aGUgc3lzdGVtcyByaWdodCBwYW5lbCBjb250ZW50cy4KICAgIEdyb3Vwczogc3RhdHVzIGluZm8sIGRyaXZlIGJhcnMsIENQVS9S"
    "QU0gZ2F1Z2VzLCBHUFUvVlJBTSBnYXVnZXMsIEdQVSB0ZW1wLgogICAgUmVwb3J0cyBoYXJkd2FyZSBhdmFpbGFiaWxpdHkgaW4g"
    "RGlhZ25vc3RpY3Mgb24gc3RhcnR1cC4KICAgIFNob3dzIE4vQSBncmFjZWZ1bGx5IHdoZW4gZGF0YSB1bmF2YWlsYWJsZS4KICAg"
    "ICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQp"
    "CiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYuX2RldGVjdF9oYXJkd2FyZSgpCgogICAgZGVmIF9zZXR1cF91"
    "aShzZWxmKSAtPiBOb25lOgogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRl"
    "bnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGRlZiBzZWN0aW9uX2xh"
    "YmVsKHRleHQ6IHN0cikgLT4gUUxhYmVsOgogICAgICAgICAgICBsYmwgPSBRTGFiZWwodGV4dCkKICAgICAgICAgICAgbGJsLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiA5cHg7IGxldHRlci1zcGFj"
    "aW5nOiAycHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC13ZWlnaHQ6"
    "IGJvbGQ7IgogICAgICAgICAgICApCiAgICAgICAgICAgIHJldHVybiBsYmwKCiAgICAgICAgIyDilIDilIAgU3RhdHVzIGJsb2Nr"
    "IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxh"
    "eW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIFNUQVRVUyIpKQogICAgICAgIHN0YXR1c19mcmFtZSA9IFFGcmFtZSgp"
    "CiAgICAgICAgc3RhdHVzX2ZyYW1lLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfUEFORUx9OyBi"
    "b3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiAycHg7IgogICAgICAgICkKICAgICAgICBzdGF0dXNf"
    "ZnJhbWUuc2V0Rml4ZWRIZWlnaHQoODgpCiAgICAgICAgc2YgPSBRVkJveExheW91dChzdGF0dXNfZnJhbWUpCiAgICAgICAgc2Yu"
    "c2V0Q29udGVudHNNYXJnaW5zKDgsIDQsIDgsIDQpCiAgICAgICAgc2Yuc2V0U3BhY2luZygyKQoKICAgICAgICBzZWxmLmxibF9z"
    "dGF0dXMgID0gUUxhYmVsKCLinKYgU1RBVFVTOiBPRkZMSU5FIikKICAgICAgICBzZWxmLmxibF9tb2RlbCAgID0gUUxhYmVsKCLi"
    "nKYgVkVTU0VMOiBMT0FESU5HLi4uIikKICAgICAgICBzZWxmLmxibF9zZXNzaW9uID0gUUxhYmVsKCLinKYgU0VTU0lPTjogMDA6"
    "MDA6MDAiKQogICAgICAgIHNlbGYubGJsX3Rva2VucyAgPSBRTGFiZWwoIuKcpiBUT0tFTlM6IDAiKQoKICAgICAgICBmb3IgbGJs"
    "IGluIChzZWxmLmxibF9zdGF0dXMsIHNlbGYubGJsX21vZGVsLAogICAgICAgICAgICAgICAgICAgIHNlbGYubGJsX3Nlc3Npb24s"
    "IHNlbGYubGJsX3Rva2Vucyk6CiAgICAgICAgICAgIGxibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJjb2xvcjog"
    "e0NfVEVYVF9ESU19OyBmb250LXNpemU6IDEwcHg7ICIKICAgICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9"
    "LCBzZXJpZjsgYm9yZGVyOiBub25lOyIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZi5hZGRXaWRnZXQobGJsKQoKICAgICAg"
    "ICBsYXlvdXQuYWRkV2lkZ2V0KHN0YXR1c19mcmFtZSkKCiAgICAgICAgIyDilIDilIAgRHJpdmUgYmFycyDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRk"
    "V2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKdpyBTVE9SQUdFIikpCiAgICAgICAgc2VsZi5kcml2ZV93aWRnZXQgPSBEcml2ZVdpZGdl"
    "dCgpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmRyaXZlX3dpZGdldCkKCiAgICAgICAgIyDilIDilIAgQ1BVIC8gUkFN"
    "IGdhdWdlcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQu"
    "YWRkV2lkZ2V0KHNlY3Rpb25fbGFiZWwoIuKdpyBWSVRBTCBFU1NFTkNFIikpCiAgICAgICAgcmFtX2NwdSA9IFFHcmlkTGF5b3V0"
    "KCkKICAgICAgICByYW1fY3B1LnNldFNwYWNpbmcoMykKCiAgICAgICAgc2VsZi5nYXVnZV9jcHUgID0gR2F1Z2VXaWRnZXQoIkNQ"
    "VSIsICAiJSIsICAgMTAwLjAsIENfU0lMVkVSKQogICAgICAgIHNlbGYuZ2F1Z2VfcmFtICA9IEdhdWdlV2lkZ2V0KCJSQU0iLCAg"
    "IkdCIiwgICA2NC4wLCBDX0dPTERfRElNKQogICAgICAgIHJhbV9jcHUuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfY3B1LCAwLCAwKQog"
    "ICAgICAgIHJhbV9jcHUuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfcmFtLCAwLCAxKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQocmFt"
    "X2NwdSkKCiAgICAgICAgIyDilIDilIAgR1BVIC8gVlJBTSBnYXVnZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgQVJDQU5FIFBPV0VSIikp"
    "CiAgICAgICAgZ3B1X3ZyYW0gPSBRR3JpZExheW91dCgpCiAgICAgICAgZ3B1X3ZyYW0uc2V0U3BhY2luZygzKQoKICAgICAgICBz"
    "ZWxmLmdhdWdlX2dwdSAgPSBHYXVnZVdpZGdldCgiR1BVIiwgICIlIiwgICAxMDAuMCwgQ19QVVJQTEUpCiAgICAgICAgc2VsZi5n"
    "YXVnZV92cmFtID0gR2F1Z2VXaWRnZXQoIlZSQU0iLCAiR0IiLCAgICA4LjAsIENfQ1JJTVNPTikKICAgICAgICBncHVfdnJhbS5h"
    "ZGRXaWRnZXQoc2VsZi5nYXVnZV9ncHUsICAwLCAwKQogICAgICAgIGdwdV92cmFtLmFkZFdpZGdldChzZWxmLmdhdWdlX3ZyYW0s"
    "IDAsIDEpCiAgICAgICAgbGF5b3V0LmFkZExheW91dChncHVfdnJhbSkKCiAgICAgICAgIyDilIDilIAgR1BVIFRlbXAg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgSU5GRVJOQUwgSEVBVCIpKQogICAgICAgIHNlbGYuZ2F1Z2Vf"
    "dGVtcCA9IEdhdWdlV2lkZ2V0KCJHUFUgVEVNUCIsICLCsEMiLCA5NS4wLCBDX0JMT09EKQogICAgICAgIHNlbGYuZ2F1Z2VfdGVt"
    "cC5zZXRNYXhpbXVtSGVpZ2h0KDY1KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5nYXVnZV90ZW1wKQoKICAgICAgICAj"
    "IOKUgOKUgCBHUFUgbWFzdGVyIGJhciAoZnVsbCB3aWR0aCkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdp"
    "ZGdldChzZWN0aW9uX2xhYmVsKCLinacgSU5GRVJOQUwgRU5HSU5FIikpCiAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyID0g"
    "R2F1Z2VXaWRnZXQoIlJUWCIsICIlIiwgMTAwLjAsIENfQ1JJTVNPTikKICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIuc2V0"
    "TWF4aW11bUhlaWdodCg1NSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfZ3B1X21hc3RlcikKCiAgICAgICAg"
    "bGF5b3V0LmFkZFN0cmV0Y2goKQoKICAgIGRlZiBfZGV0ZWN0X2hhcmR3YXJlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAg"
    "ICAgICAgQ2hlY2sgd2hhdCBoYXJkd2FyZSBtb25pdG9yaW5nIGlzIGF2YWlsYWJsZS4KICAgICAgICBNYXJrIHVuYXZhaWxhYmxl"
    "IGdhdWdlcyBhcHByb3ByaWF0ZWx5LgogICAgICAgIERpYWdub3N0aWMgbWVzc2FnZXMgY29sbGVjdGVkIGZvciB0aGUgRGlhZ25v"
    "c3RpY3MgdGFiLgogICAgICAgICIiIgogICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXM6IGxpc3Rbc3RyXSA9IFtdCgogICAgICAg"
    "IGlmIG5vdCBQU1VUSUxfT0s6CiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfY3B1LnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAg"
    "c2VsZi5nYXVnZV9yYW0uc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAg"
    "ICAgICAgICAgICAgICJbSEFSRFdBUkVdIHBzdXRpbCBub3QgYXZhaWxhYmxlIOKAlCBDUFUvUkFNIGdhdWdlcyBkaXNhYmxlZC4g"
    "IgogICAgICAgICAgICAgICAgInBpcCBpbnN0YWxsIHBzdXRpbCB0byBlbmFibGUuIgogICAgICAgICAgICApCiAgICAgICAgZWxz"
    "ZToKICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoIltIQVJEV0FSRV0gcHN1dGlsIE9LIOKAlCBDUFUvUkFN"
    "IG1vbml0b3JpbmcgYWN0aXZlLiIpCgogICAgICAgIGlmIG5vdCBOVk1MX09LOgogICAgICAgICAgICBzZWxmLmdhdWdlX2dwdS5z"
    "ZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfdnJhbS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNl"
    "bGYuZ2F1Z2VfdGVtcC5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfZ3B1X21hc3Rlci5zZXRVbmF2YWls"
    "YWJsZSgpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKAogICAgICAgICAgICAgICAgIltIQVJEV0FSRV0g"
    "cHludm1sIG5vdCBhdmFpbGFibGUgb3Igbm8gTlZJRElBIEdQVSBkZXRlY3RlZCDigJQgIgogICAgICAgICAgICAgICAgIkdQVSBn"
    "YXVnZXMgZGlzYWJsZWQuIHBpcCBpbnN0YWxsIHB5bnZtbCB0byBlbmFibGUuIgogICAgICAgICAgICApCiAgICAgICAgZWxzZToK"
    "ICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgbmFtZSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TmFtZShncHVfaGFuZGxl"
    "KQogICAgICAgICAgICAgICAgaWYgaXNpbnN0YW5jZShuYW1lLCBieXRlcyk6CiAgICAgICAgICAgICAgICAgICAgbmFtZSA9IG5h"
    "bWUuZGVjb2RlKCkKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKAogICAgICAgICAgICAgICAgICAg"
    "IGYiW0hBUkRXQVJFXSBweW52bWwgT0sg4oCUIEdQVSBkZXRlY3RlZDoge25hbWV9IgogICAgICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICAgICAgIyBVcGRhdGUgbWF4IFZSQU0gZnJvbSBhY3R1YWwgaGFyZHdhcmUKICAgICAgICAgICAgICAgIG1lbSA9IHB5bnZt"
    "bC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgdG90YWxfZ2IgPSBtZW0udG90YWwg"
    "LyAxMDI0KiozCiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3ZyYW0ubWF4X3ZhbCA9IHRvdGFsX2diCiAgICAgICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfbWVzc2FnZXMuYXBwZW5kKGYiW0hBUkRXQVJF"
    "XSBweW52bWwgZXJyb3I6IHtlfSIpCgogICAgZGVmIHVwZGF0ZV9zdGF0cyhzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAg"
    "ICAgIENhbGxlZCBldmVyeSBzZWNvbmQgZnJvbSB0aGUgc3RhdHMgUVRpbWVyLgogICAgICAgIFJlYWRzIGhhcmR3YXJlIGFuZCB1"
    "cGRhdGVzIGFsbCBnYXVnZXMuCiAgICAgICAgIiIiCiAgICAgICAgaWYgUFNVVElMX09LOgogICAgICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICAgICBjcHUgPSBwc3V0aWwuY3B1X3BlcmNlbnQoKQogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9jcHUuc2V0VmFs"
    "dWUoY3B1LCBmIntjcHU6LjBmfSUiLCBhdmFpbGFibGU9VHJ1ZSkKCiAgICAgICAgICAgICAgICBtZW0gPSBwc3V0aWwudmlydHVh"
    "bF9tZW1vcnkoKQogICAgICAgICAgICAgICAgcnUgID0gbWVtLnVzZWQgIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgcnQgID0g"
    "bWVtLnRvdGFsIC8gMTAyNCoqMwogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9yYW0uc2V0VmFsdWUocnUsIGYie3J1Oi4xZn0v"
    "e3J0Oi4wZn1HQiIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBhdmFpbGFibGU9VHJ1ZSkKICAgICAg"
    "ICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLm1heF92YWwgPSBydAogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAg"
    "ICAgICAgICAgcGFzcwoKICAgICAgICBpZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgICAgICB1dGlsICAgICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0VXRpbGl6YXRpb25SYXRlcyhncHVfaGFuZGxlKQogICAgICAg"
    "ICAgICAgICAgbWVtX2luZm8gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAg"
    "ICAgIHRlbXAgICAgID0gcHludm1sLm52bWxEZXZpY2VHZXRUZW1wZXJhdHVyZSgKICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGdwdV9oYW5kbGUsIHB5bnZtbC5OVk1MX1RFTVBFUkFUVVJFX0dQVSkKCiAgICAgICAgICAgICAgICBncHVfcGN0ICAgPSBm"
    "bG9hdCh1dGlsLmdwdSkKICAgICAgICAgICAgICAgIHZyYW1fdXNlZCA9IG1lbV9pbmZvLnVzZWQgIC8gMTAyNCoqMwogICAgICAg"
    "ICAgICAgICAgdnJhbV90b3QgID0gbWVtX2luZm8udG90YWwgLyAxMDI0KiozCgogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV9n"
    "cHUuc2V0VmFsdWUoZ3B1X3BjdCwgZiJ7Z3B1X3BjdDouMGZ9JSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICBhdmFpbGFibGU9VHJ1ZSkKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2VfdnJhbS5zZXRWYWx1ZSh2cmFtX3VzZWQsCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJ7dnJhbV91c2VkOi4xZn0ve3ZyYW1fdG90Oi4wZn1HQiIs"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBz"
    "ZWxmLmdhdWdlX3RlbXAuc2V0VmFsdWUoZmxvYXQodGVtcCksIGYie3RlbXB9wrBDIiwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICBhdmFpbGFibGU9VHJ1ZSkKCiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAg"
    "bmFtZSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TmFtZShncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgICAgIGlmIGlzaW5zdGFu"
    "Y2UobmFtZSwgYnl0ZXMpOgogICAgICAgICAgICAgICAgICAgICAgICBuYW1lID0gbmFtZS5kZWNvZGUoKQogICAgICAgICAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBuYW1lID0gIkdQVSIKCiAgICAgICAgICAgICAgICBzZWxm"
    "LmdhdWdlX2dwdV9tYXN0ZXIuc2V0VmFsdWUoCiAgICAgICAgICAgICAgICAgICAgZ3B1X3BjdCwKICAgICAgICAgICAgICAgICAg"
    "ICBmIntuYW1lfSAge2dwdV9wY3Q6LjBmfSUgICIKICAgICAgICAgICAgICAgICAgICBmIlt7dnJhbV91c2VkOi4xZn0ve3ZyYW1f"
    "dG90Oi4wZn1HQiBWUkFNXSIsCiAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUsCiAgICAgICAgICAgICAgICApCiAg"
    "ICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgVXBkYXRlIGRyaXZlIGJh"
    "cnMgZXZlcnkgMzAgc2Vjb25kcyAobm90IGV2ZXJ5IHRpY2spCiAgICAgICAgaWYgbm90IGhhc2F0dHIoc2VsZiwgIl9kcml2ZV90"
    "aWNrIik6CiAgICAgICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgPSAwCiAgICAgICAgc2VsZi5fZHJpdmVfdGljayArPSAxCiAgICAg"
    "ICAgaWYgc2VsZi5fZHJpdmVfdGljayA+PSAzMDoKICAgICAgICAgICAgc2VsZi5fZHJpdmVfdGljayA9IDAKICAgICAgICAgICAg"
    "c2VsZi5kcml2ZV93aWRnZXQucmVmcmVzaCgpCgogICAgZGVmIHNldF9zdGF0dXNfbGFiZWxzKHNlbGYsIHN0YXR1czogc3RyLCBt"
    "b2RlbDogc3RyLAogICAgICAgICAgICAgICAgICAgICAgICAgIHNlc3Npb246IHN0ciwgdG9rZW5zOiBzdHIpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5sYmxfc3RhdHVzLnNldFRleHQoZiLinKYgU1RBVFVTOiB7c3RhdHVzfSIpCiAgICAgICAgc2VsZi5sYmxfbW9k"
    "ZWwuc2V0VGV4dChmIuKcpiBWRVNTRUw6IHttb2RlbH0iKQogICAgICAgIHNlbGYubGJsX3Nlc3Npb24uc2V0VGV4dChmIuKcpiBT"
    "RVNTSU9OOiB7c2Vzc2lvbn0iKQogICAgICAgIHNlbGYubGJsX3Rva2Vucy5zZXRUZXh0KGYi4pymIFRPS0VOUzoge3Rva2Vuc30i"
    "KQoKICAgIGRlZiBnZXRfZGlhZ25vc3RpY3Moc2VsZikgLT4gbGlzdFtzdHJdOgogICAgICAgIHJldHVybiBnZXRhdHRyKHNlbGYs"
    "ICJfZGlhZ19tZXNzYWdlcyIsIFtdKQoKCiMg4pSA4pSAIFBBU1MgMiBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKIyBBbGwgd2lkZ2V0IGNsYXNzZXMgZGVmaW5lZC4gU3ludGF4LWNoZWNrYWJsZSBpbmRlcGVuZGVudGx5LgojIE5leHQ6"
    "IFBhc3MgMyDigJQgV29ya2VyIFRocmVhZHMKIyAoRG9scGhpbldvcmtlciB3aXRoIHN0cmVhbWluZywgU2VudGltZW50V29ya2Vy"
    "LCBJZGxlV29ya2VyLCBTb3VuZFdvcmtlcikKCgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgMzogV09S"
    "S0VSIFRIUkVBRFMKIwojIFdvcmtlcnMgZGVmaW5lZCBoZXJlOgojICAgTExNQWRhcHRvciAoYmFzZSArIExvY2FsVHJhbnNmb3Jt"
    "ZXJzQWRhcHRvciArIE9sbGFtYUFkYXB0b3IgKwojICAgICAgICAgICAgICAgQ2xhdWRlQWRhcHRvciArIE9wZW5BSUFkYXB0b3Ip"
    "CiMgICBTdHJlYW1pbmdXb3JrZXIgICDigJQgbWFpbiBnZW5lcmF0aW9uLCBlbWl0cyB0b2tlbnMgb25lIGF0IGEgdGltZQojICAg"
    "U2VudGltZW50V29ya2VyICAg4oCUIGNsYXNzaWZpZXMgZW1vdGlvbiBmcm9tIHJlc3BvbnNlIHRleHQKIyAgIElkbGVXb3JrZXIg"
    "ICAgICAgIOKAlCB1bnNvbGljaXRlZCB0cmFuc21pc3Npb25zIGR1cmluZyBpZGxlCiMgICBTb3VuZFdvcmtlciAgICAgICDigJQg"
    "cGxheXMgc291bmRzIG9mZiB0aGUgbWFpbiB0aHJlYWQKIwojIEFMTCBnZW5lcmF0aW9uIGlzIHN0cmVhbWluZy4gTm8gYmxvY2tp"
    "bmcgY2FsbHMgb24gbWFpbiB0aHJlYWQuIEV2ZXIuCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgppbXBvcnQgYWJjCmltcG9ydCBqc29uCmltcG9y"
    "dCB1cmxsaWIucmVxdWVzdAppbXBvcnQgdXJsbGliLmVycm9yCmltcG9ydCBodHRwLmNsaWVudApmcm9tIHR5cGluZyBpbXBvcnQg"
    "SXRlcmF0b3IKCgojIOKUgOKUgCBMTE0gQURBUFRPUiBCQVNFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBMTE1BZGFwdG9y"
    "KGFiYy5BQkMpOgogICAgIiIiCiAgICBBYnN0cmFjdCBiYXNlIGZvciBhbGwgbW9kZWwgYmFja2VuZHMuCiAgICBUaGUgZGVjayBj"
    "YWxscyBzdHJlYW0oKSBvciBnZW5lcmF0ZSgpIOKAlCBuZXZlciBrbm93cyB3aGljaCBiYWNrZW5kIGlzIGFjdGl2ZS4KICAgICIi"
    "IgoKICAgIEBhYmMuYWJzdHJhY3RtZXRob2QKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICAiIiJS"
    "ZXR1cm4gVHJ1ZSBpZiB0aGUgYmFja2VuZCBpcyByZWFjaGFibGUuIiIiCiAgICAgICAgLi4uCgogICAgQGFiYy5hYnN0cmFjdG1l"
    "dGhvZAogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3Ry"
    "LAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4g"
    "SXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAgICBZaWVsZCByZXNwb25zZSB0ZXh0IHRva2VuLWJ5LXRva2VuIChvciBj"
    "aHVuay1ieS1jaHVuayBmb3IgQVBJIGJhY2tlbmRzKS4KICAgICAgICBNdXN0IGJlIGEgZ2VuZXJhdG9yLiBOZXZlciBibG9jayBm"
    "b3IgdGhlIGZ1bGwgcmVzcG9uc2UgYmVmb3JlIHlpZWxkaW5nLgogICAgICAgICIiIgogICAgICAgIC4uLgoKICAgIGRlZiBnZW5l"
    "cmF0ZSgKICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rv"
    "cnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gc3RyOgogICAgICAgICIi"
    "IgogICAgICAgIENvbnZlbmllbmNlIHdyYXBwZXI6IGNvbGxlY3QgYWxsIHN0cmVhbSB0b2tlbnMgaW50byBvbmUgc3RyaW5nLgog"
    "ICAgICAgIFVzZWQgZm9yIHNlbnRpbWVudCBjbGFzc2lmaWNhdGlvbiAoc21hbGwgYm91bmRlZCBjYWxscyBvbmx5KS4KICAgICAg"
    "ICAiIiIKICAgICAgICByZXR1cm4gIiIuam9pbihzZWxmLnN0cmVhbShwcm9tcHQsIHN5c3RlbSwgaGlzdG9yeSwgbWF4X25ld190"
    "b2tlbnMpKQoKICAgIGRlZiBidWlsZF9jaGF0bWxfcHJvbXB0KHNlbGYsIHN5c3RlbTogc3RyLCBoaXN0b3J5OiBsaXN0W2RpY3Rd"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIHVzZXJfdGV4dDogc3RyID0gIiIpIC0+IHN0cjoKICAgICAgICAiIiIKICAg"
    "ICAgICBCdWlsZCBhIENoYXRNTC1mb3JtYXQgcHJvbXB0IHN0cmluZyBmb3IgbG9jYWwgbW9kZWxzLgogICAgICAgIGhpc3Rvcnkg"
    "PSBbeyJyb2xlIjogInVzZXIifCJhc3Npc3RhbnQiLCAiY29udGVudCI6ICIuLi4ifV0KICAgICAgICAiIiIKICAgICAgICBwYXJ0"
    "cyA9IFtmIjx8aW1fc3RhcnR8PnN5c3RlbVxue3N5c3RlbX08fGltX2VuZHw+Il0KICAgICAgICBmb3IgbXNnIGluIGhpc3Rvcnk6"
    "CiAgICAgICAgICAgIHJvbGUgICAgPSBtc2cuZ2V0KCJyb2xlIiwgInVzZXIiKQogICAgICAgICAgICBjb250ZW50ID0gbXNnLmdl"
    "dCgiY29udGVudCIsICIiKQogICAgICAgICAgICBwYXJ0cy5hcHBlbmQoZiI8fGltX3N0YXJ0fD57cm9sZX1cbntjb250ZW50fTx8"
    "aW1fZW5kfD4iKQogICAgICAgIGlmIHVzZXJfdGV4dDoKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGYiPHxpbV9zdGFydHw+dXNl"
    "clxue3VzZXJfdGV4dH08fGltX2VuZHw+IikKICAgICAgICBwYXJ0cy5hcHBlbmQoIjx8aW1fc3RhcnR8PmFzc2lzdGFudFxuIikK"
    "ICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBhcnRzKQoKCiMg4pSA4pSAIExPQ0FMIFRSQU5TRk9STUVSUyBBREFQVE9SIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBMb2Nh"
    "bFRyYW5zZm9ybWVyc0FkYXB0b3IoTExNQWRhcHRvcik6CiAgICAiIiIKICAgIExvYWRzIGEgSHVnZ2luZ0ZhY2UgbW9kZWwgZnJv"
    "bSBhIGxvY2FsIGZvbGRlci4KICAgIFN0cmVhbWluZzogdXNlcyBtb2RlbC5nZW5lcmF0ZSgpIHdpdGggYSBjdXN0b20gc3RyZWFt"
    "ZXIgdGhhdCB5aWVsZHMgdG9rZW5zLgogICAgUmVxdWlyZXM6IHRvcmNoLCB0cmFuc2Zvcm1lcnMKICAgICIiIgoKICAgIGRlZiBf"
    "X2luaXRfXyhzZWxmLCBtb2RlbF9wYXRoOiBzdHIpOgogICAgICAgIHNlbGYuX3BhdGggICAgICA9IG1vZGVsX3BhdGgKICAgICAg"
    "ICBzZWxmLl9tb2RlbCAgICAgPSBOb25lCiAgICAgICAgc2VsZi5fdG9rZW5pemVyID0gTm9uZQogICAgICAgIHNlbGYuX2xvYWRl"
    "ZCAgICA9IEZhbHNlCiAgICAgICAgc2VsZi5fZXJyb3IgICAgID0gIiIKCiAgICBkZWYgbG9hZChzZWxmKSAtPiBib29sOgogICAg"
    "ICAgICIiIgogICAgICAgIExvYWQgbW9kZWwgYW5kIHRva2VuaXplci4gQ2FsbCBmcm9tIGEgYmFja2dyb3VuZCB0aHJlYWQuCiAg"
    "ICAgICAgUmV0dXJucyBUcnVlIG9uIHN1Y2Nlc3MuCiAgICAgICAgIiIiCiAgICAgICAgaWYgbm90IFRPUkNIX09LOgogICAgICAg"
    "ICAgICBzZWxmLl9lcnJvciA9ICJ0b3JjaC90cmFuc2Zvcm1lcnMgbm90IGluc3RhbGxlZCIKICAgICAgICAgICAgcmV0dXJuIEZh"
    "bHNlCiAgICAgICAgdHJ5OgogICAgICAgICAgICBmcm9tIHRyYW5zZm9ybWVycyBpbXBvcnQgQXV0b01vZGVsRm9yQ2F1c2FsTE0s"
    "IEF1dG9Ub2tlbml6ZXIKICAgICAgICAgICAgc2VsZi5fdG9rZW5pemVyID0gQXV0b1Rva2VuaXplci5mcm9tX3ByZXRyYWluZWQo"
    "c2VsZi5fcGF0aCkKICAgICAgICAgICAgc2VsZi5fbW9kZWwgPSBBdXRvTW9kZWxGb3JDYXVzYWxMTS5mcm9tX3ByZXRyYWluZWQo"
    "CiAgICAgICAgICAgICAgICBzZWxmLl9wYXRoLAogICAgICAgICAgICAgICAgdG9yY2hfZHR5cGU9dG9yY2guZmxvYXQxNiwKICAg"
    "ICAgICAgICAgICAgIGRldmljZV9tYXA9ImF1dG8iLAogICAgICAgICAgICAgICAgbG93X2NwdV9tZW1fdXNhZ2U9VHJ1ZSwKICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9sb2FkZWQgPSBUcnVlCiAgICAgICAgICAgIHJldHVybiBUcnVlCiAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9lcnJvciA9IHN0cihlKQogICAgICAgICAgICByZXR1cm4g"
    "RmFsc2UKCiAgICBAcHJvcGVydHkKICAgIGRlZiBlcnJvcihzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2Vycm9y"
    "CgogICAgZGVmIGlzX2Nvbm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBzZWxmLl9sb2FkZWQKCiAgICBkZWYg"
    "c3RyZWFtKAogICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlz"
    "dG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVyYXRvcltzdHJd"
    "OgogICAgICAgICIiIgogICAgICAgIFN0cmVhbXMgdG9rZW5zIHVzaW5nIHRyYW5zZm9ybWVycyBUZXh0SXRlcmF0b3JTdHJlYW1l"
    "ci4KICAgICAgICBZaWVsZHMgZGVjb2RlZCB0ZXh0IGZyYWdtZW50cyBhcyB0aGV5IGFyZSBnZW5lcmF0ZWQuCiAgICAgICAgIiIi"
    "CiAgICAgICAgaWYgbm90IHNlbGYuX2xvYWRlZDoKICAgICAgICAgICAgeWllbGQgIltFUlJPUjogbW9kZWwgbm90IGxvYWRlZF0i"
    "CiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGZyb20gdHJhbnNmb3JtZXJzIGltcG9ydCBUZXh0"
    "SXRlcmF0b3JTdHJlYW1lcgoKICAgICAgICAgICAgZnVsbF9wcm9tcHQgPSBzZWxmLmJ1aWxkX2NoYXRtbF9wcm9tcHQoc3lzdGVt"
    "LCBoaXN0b3J5KQogICAgICAgICAgICBpZiBwcm9tcHQ6CiAgICAgICAgICAgICAgICAjIHByb21wdCBhbHJlYWR5IGluY2x1ZGVz"
    "IHVzZXIgdHVybiBpZiBjYWxsZXIgYnVpbHQgaXQKICAgICAgICAgICAgICAgIGZ1bGxfcHJvbXB0ID0gcHJvbXB0CgogICAgICAg"
    "ICAgICBpbnB1dF9pZHMgPSBzZWxmLl90b2tlbml6ZXIoCiAgICAgICAgICAgICAgICBmdWxsX3Byb21wdCwgcmV0dXJuX3RlbnNv"
    "cnM9InB0IgogICAgICAgICAgICApLmlucHV0X2lkcy50bygiY3VkYSIpCgogICAgICAgICAgICBhdHRlbnRpb25fbWFzayA9IChp"
    "bnB1dF9pZHMgIT0gc2VsZi5fdG9rZW5pemVyLnBhZF90b2tlbl9pZCkubG9uZygpCgogICAgICAgICAgICBzdHJlYW1lciA9IFRl"
    "eHRJdGVyYXRvclN0cmVhbWVyKAogICAgICAgICAgICAgICAgc2VsZi5fdG9rZW5pemVyLAogICAgICAgICAgICAgICAgc2tpcF9w"
    "cm9tcHQ9VHJ1ZSwKICAgICAgICAgICAgICAgIHNraXBfc3BlY2lhbF90b2tlbnM9VHJ1ZSwKICAgICAgICAgICAgKQoKICAgICAg"
    "ICAgICAgZ2VuX2t3YXJncyA9IHsKICAgICAgICAgICAgICAgICJpbnB1dF9pZHMiOiAgICAgIGlucHV0X2lkcywKICAgICAgICAg"
    "ICAgICAgICJhdHRlbnRpb25fbWFzayI6IGF0dGVudGlvbl9tYXNrLAogICAgICAgICAgICAgICAgIm1heF9uZXdfdG9rZW5zIjog"
    "bWF4X25ld190b2tlbnMsCiAgICAgICAgICAgICAgICAidGVtcGVyYXR1cmUiOiAgICAwLjcsCiAgICAgICAgICAgICAgICAiZG9f"
    "c2FtcGxlIjogICAgICBUcnVlLAogICAgICAgICAgICAgICAgInBhZF90b2tlbl9pZCI6ICAgc2VsZi5fdG9rZW5pemVyLmVvc190"
    "b2tlbl9pZCwKICAgICAgICAgICAgICAgICJzdHJlYW1lciI6ICAgICAgIHN0cmVhbWVyLAogICAgICAgICAgICB9CgogICAgICAg"
    "ICAgICAjIFJ1biBnZW5lcmF0aW9uIGluIGEgZGFlbW9uIHRocmVhZCDigJQgc3RyZWFtZXIgeWllbGRzIGhlcmUKICAgICAgICAg"
    "ICAgZ2VuX3RocmVhZCA9IHRocmVhZGluZy5UaHJlYWQoCiAgICAgICAgICAgICAgICB0YXJnZXQ9c2VsZi5fbW9kZWwuZ2VuZXJh"
    "dGUsCiAgICAgICAgICAgICAgICBrd2FyZ3M9Z2VuX2t3YXJncywKICAgICAgICAgICAgICAgIGRhZW1vbj1UcnVlLAogICAgICAg"
    "ICAgICApCiAgICAgICAgICAgIGdlbl90aHJlYWQuc3RhcnQoKQoKICAgICAgICAgICAgZm9yIHRva2VuX3RleHQgaW4gc3RyZWFt"
    "ZXI6CiAgICAgICAgICAgICAgICB5aWVsZCB0b2tlbl90ZXh0CgogICAgICAgICAgICBnZW5fdGhyZWFkLmpvaW4odGltZW91dD0x"
    "MjApCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjoge2V9XSIKCgoj"
    "IOKUgOKUgCBPTExBTUEgQURBUFRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgT2xsYW1hQWRhcHRvcihM"
    "TE1BZGFwdG9yKToKICAgICIiIgogICAgQ29ubmVjdHMgdG8gYSBsb2NhbGx5IHJ1bm5pbmcgT2xsYW1hIGluc3RhbmNlLgogICAg"
    "U3RyZWFtaW5nOiByZWFkcyBOREpTT04gcmVzcG9uc2UgY2h1bmtzIGZyb20gT2xsYW1hJ3MgL2FwaS9nZW5lcmF0ZSBlbmRwb2lu"
    "dC4KICAgIE9sbGFtYSBtdXN0IGJlIHJ1bm5pbmcgYXMgYSBzZXJ2aWNlIG9uIGxvY2FsaG9zdDoxMTQzNC4KICAgICIiIgoKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmLCBtb2RlbF9uYW1lOiBzdHIsIGhvc3Q6IHN0ciA9ICJsb2NhbGhvc3QiLCBwb3J0OiBpbnQgPSAx"
    "MTQzNCk6CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbF9uYW1lCiAgICAgICAgc2VsZi5fYmFzZSAgPSBmImh0dHA6Ly97aG9z"
    "dH06e3BvcnR9IgoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJl"
    "cSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KGYie3NlbGYuX2Jhc2V9L2FwaS90YWdzIikKICAgICAgICAgICAgcmVzcCA9IHVy"
    "bGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTMpCiAgICAgICAgICAgIHJldHVybiByZXNwLnN0YXR1cyA9PSAyMDAK"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4gRmFsc2UKCiAgICBkZWYgc3RyZWFtKAogICAgICAg"
    "IHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0"
    "XSwKICAgICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVyYXRvcltzdHJdOgogICAgICAgICIiIgog"
    "ICAgICAgIFBvc3RzIHRvIC9hcGkvY2hhdCB3aXRoIHN0cmVhbT1UcnVlLgogICAgICAgIE9sbGFtYSByZXR1cm5zIE5ESlNPTiDi"
    "gJQgb25lIEpTT04gb2JqZWN0IHBlciBsaW5lLgogICAgICAgIFlpZWxkcyB0aGUgJ2NvbnRlbnQnIGZpZWxkIG9mIGVhY2ggYXNz"
    "aXN0YW50IG1lc3NhZ2UgY2h1bmsuCiAgICAgICAgIiIiCiAgICAgICAgbWVzc2FnZXMgPSBbeyJyb2xlIjogInN5c3RlbSIsICJj"
    "b250ZW50Ijogc3lzdGVtfV0KICAgICAgICBmb3IgbXNnIGluIGhpc3Rvcnk6CiAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZCht"
    "c2cpCgogICAgICAgIHBheWxvYWQgPSBqc29uLmR1bXBzKHsKICAgICAgICAgICAgIm1vZGVsIjogICAgc2VsZi5fbW9kZWwsCiAg"
    "ICAgICAgICAgICJtZXNzYWdlcyI6IG1lc3NhZ2VzLAogICAgICAgICAgICAic3RyZWFtIjogICBUcnVlLAogICAgICAgICAgICAi"
    "b3B0aW9ucyI6ICB7Im51bV9wcmVkaWN0IjogbWF4X25ld190b2tlbnMsICJ0ZW1wZXJhdHVyZSI6IDAuN30sCiAgICAgICAgfSku"
    "ZW5jb2RlKCJ1dGYtOCIpCgogICAgICAgIHRyeToKICAgICAgICAgICAgcmVxID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdCgKICAg"
    "ICAgICAgICAgICAgIGYie3NlbGYuX2Jhc2V9L2FwaS9jaGF0IiwKICAgICAgICAgICAgICAgIGRhdGE9cGF5bG9hZCwKICAgICAg"
    "ICAgICAgICAgIGhlYWRlcnM9eyJDb250ZW50LVR5cGUiOiAiYXBwbGljYXRpb24vanNvbiJ9LAogICAgICAgICAgICAgICAgbWV0"
    "aG9kPSJQT1NUIiwKICAgICAgICAgICAgKQogICAgICAgICAgICB3aXRoIHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1l"
    "b3V0PTEyMCkgYXMgcmVzcDoKICAgICAgICAgICAgICAgIGZvciByYXdfbGluZSBpbiByZXNwOgogICAgICAgICAgICAgICAgICAg"
    "IGxpbmUgPSByYXdfbGluZS5kZWNvZGUoInV0Zi04Iikuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgIGlmIG5vdCBsaW5lOgog"
    "ICAgICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgb2JqID0ganNvbi5sb2FkcyhsaW5lKQogICAgICAgICAgICAgICAgICAgICAgICBjaHVuayA9IG9iai5nZXQoIm1lc3Nh"
    "Z2UiLCB7fSkuZ2V0KCJjb250ZW50IiwgIiIpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIGNodW5rOgogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgeWllbGQgY2h1bmsKICAgICAgICAgICAgICAgICAgICAgICAgaWYgb2JqLmdldCgiZG9uZSIsIEZhbHNl"
    "KToKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgICAgICAgICAgZXhjZXB0IGpzb24uSlNPTkRl"
    "Y29kZUVycm9yOgogICAgICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToK"
    "ICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogT2xsYW1hIOKAlCB7ZX1dIgoKCiMg4pSA4pSAIENMQVVERSBBREFQVE9SIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBDbGF1ZGVBZGFwdG9yKExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBT"
    "dHJlYW1zIGZyb20gQW50aHJvcGljJ3MgQ2xhdWRlIEFQSSB1c2luZyBTU0UgKHNlcnZlci1zZW50IGV2ZW50cykuCiAgICBSZXF1"
    "aXJlcyBhbiBBUEkga2V5IGluIGNvbmZpZy4KICAgICIiIgoKICAgIF9BUElfVVJMID0gImFwaS5hbnRocm9waWMuY29tIgogICAg"
    "X1BBVEggICAgPSAiL3YxL21lc3NhZ2VzIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhcGlfa2V5OiBzdHIsIG1vZGVsOiBzdHIg"
    "PSAiY2xhdWRlLXNvbm5ldC00LTYiKToKICAgICAgICBzZWxmLl9rZXkgICA9IGFwaV9rZXkKICAgICAgICBzZWxmLl9tb2RlbCA9"
    "IG1vZGVsCgogICAgZGVmIGlzX2Nvbm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBib29sKHNlbGYuX2tleSkK"
    "CiAgICBkZWYgc3RyZWFtKAogICAgICAgIHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAg"
    "ICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVy"
    "YXRvcltzdHJdOgogICAgICAgIG1lc3NhZ2VzID0gW10KICAgICAgICBmb3IgbXNnIGluIGhpc3Rvcnk6CiAgICAgICAgICAgIG1l"
    "c3NhZ2VzLmFwcGVuZCh7CiAgICAgICAgICAgICAgICAicm9sZSI6ICAgIG1zZ1sicm9sZSJdLAogICAgICAgICAgICAgICAgImNv"
    "bnRlbnQiOiBtc2dbImNvbnRlbnQiXSwKICAgICAgICAgICAgfSkKCiAgICAgICAgcGF5bG9hZCA9IGpzb24uZHVtcHMoewogICAg"
    "ICAgICAgICAibW9kZWwiOiAgICAgIHNlbGYuX21vZGVsLAogICAgICAgICAgICAibWF4X3Rva2VucyI6IG1heF9uZXdfdG9rZW5z"
    "LAogICAgICAgICAgICAic3lzdGVtIjogICAgIHN5c3RlbSwKICAgICAgICAgICAgIm1lc3NhZ2VzIjogICBtZXNzYWdlcywKICAg"
    "ICAgICAgICAgInN0cmVhbSI6ICAgICBUcnVlLAogICAgICAgIH0pLmVuY29kZSgidXRmLTgiKQoKICAgICAgICBoZWFkZXJzID0g"
    "ewogICAgICAgICAgICAieC1hcGkta2V5IjogICAgICAgICBzZWxmLl9rZXksCiAgICAgICAgICAgICJhbnRocm9waWMtdmVyc2lv"
    "biI6ICIyMDIzLTA2LTAxIiwKICAgICAgICAgICAgImNvbnRlbnQtdHlwZSI6ICAgICAgImFwcGxpY2F0aW9uL2pzb24iLAogICAg"
    "ICAgIH0KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBjb25uID0gaHR0cC5jbGllbnQuSFRUUFNDb25uZWN0aW9uKHNlbGYuX0FQ"
    "SV9VUkwsIHRpbWVvdXQ9MTIwKQogICAgICAgICAgICBjb25uLnJlcXVlc3QoIlBPU1QiLCBzZWxmLl9QQVRILCBib2R5PXBheWxv"
    "YWQsIGhlYWRlcnM9aGVhZGVycykKICAgICAgICAgICAgcmVzcCA9IGNvbm4uZ2V0cmVzcG9uc2UoKQoKICAgICAgICAgICAgaWYg"
    "cmVzcC5zdGF0dXMgIT0gMjAwOgogICAgICAgICAgICAgICAgYm9keSA9IHJlc3AucmVhZCgpLmRlY29kZSgidXRmLTgiKQogICAg"
    "ICAgICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogQ2xhdWRlIEFQSSB7cmVzcC5zdGF0dXN9IOKAlCB7Ym9keVs6MjAwXX1dIgog"
    "ICAgICAgICAgICAgICAgcmV0dXJuCgogICAgICAgICAgICBidWZmZXIgPSAiIgogICAgICAgICAgICB3aGlsZSBUcnVlOgogICAg"
    "ICAgICAgICAgICAgY2h1bmsgPSByZXNwLnJlYWQoMjU2KQogICAgICAgICAgICAgICAgaWYgbm90IGNodW5rOgogICAgICAgICAg"
    "ICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgICAgICBidWZmZXIgKz0gY2h1bmsuZGVjb2RlKCJ1dGYtOCIpCiAgICAgICAgICAg"
    "ICAgICB3aGlsZSAiXG4iIGluIGJ1ZmZlcjoKICAgICAgICAgICAgICAgICAgICBsaW5lLCBidWZmZXIgPSBidWZmZXIuc3BsaXQo"
    "IlxuIiwgMSkKICAgICAgICAgICAgICAgICAgICBsaW5lID0gbGluZS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgaWYgbGlu"
    "ZS5zdGFydHN3aXRoKCJkYXRhOiIpOgogICAgICAgICAgICAgICAgICAgICAgICBkYXRhX3N0ciA9IGxpbmVbNTpdLnN0cmlwKCkK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgaWYgZGF0YV9zdHIgPT0gIltET05FXSI6CiAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICByZXR1cm4KICAgICAgICAgICAgICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgb2JqID0ganNv"
    "bi5sb2FkcyhkYXRhX3N0cikKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIG9iai5nZXQoInR5cGUiKSA9PSAiY29udGVu"
    "dF9ibG9ja19kZWx0YSI6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgdGV4dCA9IG9iai5nZXQoImRlbHRhIiwge30p"
    "LmdldCgidGV4dCIsICIiKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHRleHQ6CiAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgIHlpZWxkIHRleHQKICAgICAgICAgICAgICAgICAgICAgICAgZXhjZXB0IGpzb24uSlNPTkRlY29k"
    "ZUVycm9yOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcGFzcwogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAg"
    "ICAgICAgICAgeWllbGQgZiJcbltFUlJPUjogQ2xhdWRlIOKAlCB7ZX1dIgogICAgICAgIGZpbmFsbHk6CiAgICAgICAgICAgIHRy"
    "eToKICAgICAgICAgICAgICAgIGNvbm4uY2xvc2UoKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAg"
    "ICAgcGFzcwoKCiMg4pSA4pSAIE9QRU5BSSBBREFQVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBPcGVu"
    "QUlBZGFwdG9yKExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBTdHJlYW1zIGZyb20gT3BlbkFJJ3MgY2hhdCBjb21wbGV0aW9ucyBB"
    "UEkuCiAgICBTYW1lIFNTRSBwYXR0ZXJuIGFzIENsYXVkZS4gQ29tcGF0aWJsZSB3aXRoIGFueSBPcGVuQUktY29tcGF0aWJsZSBl"
    "bmRwb2ludC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBhcGlfa2V5OiBzdHIsIG1vZGVsOiBzdHIgPSAiZ3B0LTRv"
    "IiwKICAgICAgICAgICAgICAgICBob3N0OiBzdHIgPSAiYXBpLm9wZW5haS5jb20iKToKICAgICAgICBzZWxmLl9rZXkgICA9IGFw"
    "aV9rZXkKICAgICAgICBzZWxmLl9tb2RlbCA9IG1vZGVsCiAgICAgICAgc2VsZi5faG9zdCAgPSBob3N0CgogICAgZGVmIGlzX2Nv"
    "bm5lY3RlZChzZWxmKSAtPiBib29sOgogICAgICAgIHJldHVybiBib29sKHNlbGYuX2tleSkKCiAgICBkZWYgc3RyZWFtKAogICAg"
    "ICAgIHNlbGYsCiAgICAgICAgcHJvbXB0OiBzdHIsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAgICAgICAgaGlzdG9yeTogbGlzdFtk"
    "aWN0XSwKICAgICAgICBtYXhfbmV3X3Rva2VuczogaW50ID0gNTEyLAogICAgKSAtPiBJdGVyYXRvcltzdHJdOgogICAgICAgIG1l"
    "c3NhZ2VzID0gW3sicm9sZSI6ICJzeXN0ZW0iLCAiY29udGVudCI6IHN5c3RlbX1dCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5"
    "OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoeyJyb2xlIjogbXNnWyJyb2xlIl0sICJjb250ZW50IjogbXNnWyJjb250ZW50"
    "Il19KQoKICAgICAgICBwYXlsb2FkID0ganNvbi5kdW1wcyh7CiAgICAgICAgICAgICJtb2RlbCI6ICAgICAgIHNlbGYuX21vZGVs"
    "LAogICAgICAgICAgICAibWVzc2FnZXMiOiAgICBtZXNzYWdlcywKICAgICAgICAgICAgIm1heF90b2tlbnMiOiAgbWF4X25ld190"
    "b2tlbnMsCiAgICAgICAgICAgICJ0ZW1wZXJhdHVyZSI6IDAuNywKICAgICAgICAgICAgInN0cmVhbSI6ICAgICAgVHJ1ZSwKICAg"
    "ICAgICB9KS5lbmNvZGUoInV0Zi04IikKCiAgICAgICAgaGVhZGVycyA9IHsKICAgICAgICAgICAgIkF1dGhvcml6YXRpb24iOiBm"
    "IkJlYXJlciB7c2VsZi5fa2V5fSIsCiAgICAgICAgICAgICJDb250ZW50LVR5cGUiOiAgImFwcGxpY2F0aW9uL2pzb24iLAogICAg"
    "ICAgIH0KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBjb25uID0gaHR0cC5jbGllbnQuSFRUUFNDb25uZWN0aW9uKHNlbGYuX2hv"
    "c3QsIHRpbWVvdXQ9MTIwKQogICAgICAgICAgICBjb25uLnJlcXVlc3QoIlBPU1QiLCAiL3YxL2NoYXQvY29tcGxldGlvbnMiLAog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgYm9keT1wYXlsb2FkLCBoZWFkZXJzPWhlYWRlcnMpCiAgICAgICAgICAgIHJlc3AgPSBj"
    "b25uLmdldHJlc3BvbnNlKCkKCiAgICAgICAgICAgIGlmIHJlc3Auc3RhdHVzICE9IDIwMDoKICAgICAgICAgICAgICAgIGJvZHkg"
    "PSByZXNwLnJlYWQoKS5kZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IE9wZW5BSSBBUEkg"
    "e3Jlc3Auc3RhdHVzfSDigJQge2JvZHlbOjIwMF19XSIKICAgICAgICAgICAgICAgIHJldHVybgoKICAgICAgICAgICAgYnVmZmVy"
    "ID0gIiIKICAgICAgICAgICAgd2hpbGUgVHJ1ZToKICAgICAgICAgICAgICAgIGNodW5rID0gcmVzcC5yZWFkKDI1NikKICAgICAg"
    "ICAgICAgICAgIGlmIG5vdCBjaHVuazoKICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgYnVmZmVyICs9"
    "IGNodW5rLmRlY29kZSgidXRmLTgiKQogICAgICAgICAgICAgICAgd2hpbGUgIlxuIiBpbiBidWZmZXI6CiAgICAgICAgICAgICAg"
    "ICAgICAgbGluZSwgYnVmZmVyID0gYnVmZmVyLnNwbGl0KCJcbiIsIDEpCiAgICAgICAgICAgICAgICAgICAgbGluZSA9IGxpbmUu"
    "c3RyaXAoKQogICAgICAgICAgICAgICAgICAgIGlmIGxpbmUuc3RhcnRzd2l0aCgiZGF0YToiKToKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgZGF0YV9zdHIgPSBsaW5lWzU6XS5zdHJpcCgpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIGRhdGFfc3RyID09ICJb"
    "RE9ORV0iOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgICAgICAgICAgICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMoZGF0YV9zdHIpCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICB0ZXh0ID0gKG9iai5nZXQoImNob2ljZXMiLCBbe31dKVswXQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAuZ2V0KCJkZWx0YSIsIHt9KQogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAuZ2V0KCJjb250ZW50"
    "IiwgIiIpKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgdGV4dDoKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICB5aWVsZCB0ZXh0CiAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCAoanNvbi5KU09ORGVjb2RlRXJyb3IsIEluZGV4RXJy"
    "b3IpOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgcGFzcwogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAg"
    "ICAgICAgeWllbGQgZiJcbltFUlJPUjogT3BlbkFJIOKAlCB7ZX1dIgogICAgICAgIGZpbmFsbHk6CiAgICAgICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgICAgIGNvbm4uY2xvc2UoKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAg"
    "cGFzcwoKCiMg4pSA4pSAIEFEQVBUT1IgRkFDVE9SWSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGJ1aWxkX2FkYXB0"
    "b3JfZnJvbV9jb25maWcoKSAtPiBMTE1BZGFwdG9yOgogICAgIiIiCiAgICBCdWlsZCB0aGUgY29ycmVjdCBMTE1BZGFwdG9yIGZy"
    "b20gQ0ZHWydtb2RlbCddLgogICAgQ2FsbGVkIG9uY2Ugb24gc3RhcnR1cCBieSB0aGUgbW9kZWwgbG9hZGVyIHRocmVhZC4KICAg"
    "ICIiIgogICAgbSA9IENGRy5nZXQoIm1vZGVsIiwge30pCiAgICB0ID0gbS5nZXQoInR5cGUiLCAibG9jYWwiKQoKICAgIGlmIHQg"
    "PT0gIm9sbGFtYSI6CiAgICAgICAgcmV0dXJuIE9sbGFtYUFkYXB0b3IoCiAgICAgICAgICAgIG1vZGVsX25hbWU9bS5nZXQoIm9s"
    "bGFtYV9tb2RlbCIsICJkb2xwaGluLTIuNi03YiIpCiAgICAgICAgKQogICAgZWxpZiB0ID09ICJjbGF1ZGUiOgogICAgICAgIHJl"
    "dHVybiBDbGF1ZGVBZGFwdG9yKAogICAgICAgICAgICBhcGlfa2V5PW0uZ2V0KCJhcGlfa2V5IiwgIiIpLAogICAgICAgICAgICBt"
    "b2RlbD1tLmdldCgiYXBpX21vZGVsIiwgImNsYXVkZS1zb25uZXQtNC02IiksCiAgICAgICAgKQogICAgZWxpZiB0ID09ICJvcGVu"
    "YWkiOgogICAgICAgIHJldHVybiBPcGVuQUlBZGFwdG9yKAogICAgICAgICAgICBhcGlfa2V5PW0uZ2V0KCJhcGlfa2V5IiwgIiIp"
    "LAogICAgICAgICAgICBtb2RlbD1tLmdldCgiYXBpX21vZGVsIiwgImdwdC00byIpLAogICAgICAgICkKICAgIGVsc2U6CiAgICAg"
    "ICAgIyBEZWZhdWx0OiBsb2NhbCB0cmFuc2Zvcm1lcnMKICAgICAgICByZXR1cm4gTG9jYWxUcmFuc2Zvcm1lcnNBZGFwdG9yKG1v"
    "ZGVsX3BhdGg9bS5nZXQoInBhdGgiLCAiIikpCgoKIyDilIDilIAgU1RSRUFNSU5HIFdPUktFUiDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKY2xhc3MgU3RyZWFtaW5nV29ya2VyKFFUaHJlYWQpOgogICAgIiIiCiAgICBNYWluIGdlbmVyYXRpb24gd29ya2VyLiBT"
    "dHJlYW1zIHRva2VucyBvbmUgYnkgb25lIHRvIHRoZSBVSS4KCiAgICBTaWduYWxzOgogICAgICAgIHRva2VuX3JlYWR5KHN0cikg"
    "ICAgICDigJQgZW1pdHRlZCBmb3IgZWFjaCB0b2tlbi9jaHVuayBhcyBnZW5lcmF0ZWQKICAgICAgICByZXNwb25zZV9kb25lKHN0"
    "cikgICAg4oCUIGVtaXR0ZWQgd2l0aCB0aGUgZnVsbCBhc3NlbWJsZWQgcmVzcG9uc2UKICAgICAgICBlcnJvcl9vY2N1cnJlZChz"
    "dHIpICAg4oCUIGVtaXR0ZWQgb24gZXhjZXB0aW9uCiAgICAgICAgc3RhdHVzX2NoYW5nZWQoc3RyKSAgIOKAlCBlbWl0dGVkIHdp"
    "dGggc3RhdHVzIHN0cmluZyAoR0VORVJBVElORyAvIElETEUgLyBFUlJPUikKICAgICIiIgoKICAgIHRva2VuX3JlYWR5ICAgID0g"
    "U2lnbmFsKHN0cikKICAgIHJlc3BvbnNlX2RvbmUgID0gU2lnbmFsKHN0cikKICAgIGVycm9yX29jY3VycmVkID0gU2lnbmFsKHN0"
    "cikKICAgIHN0YXR1c19jaGFuZ2VkID0gU2lnbmFsKHN0cikKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYWRhcHRvcjogTExNQWRh"
    "cHRvciwgc3lzdGVtOiBzdHIsCiAgICAgICAgICAgICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwgbWF4X3Rva2VuczogaW50ID0g"
    "NTEyKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yICAgID0gYWRhcHRvcgogICAgICAg"
    "IHNlbGYuX3N5c3RlbSAgICAgPSBzeXN0ZW0KICAgICAgICBzZWxmLl9oaXN0b3J5ICAgID0gbGlzdChoaXN0b3J5KSAgICMgY29w"
    "eSDigJQgdGhyZWFkIHNhZmUKICAgICAgICBzZWxmLl9tYXhfdG9rZW5zID0gbWF4X3Rva2VucwogICAgICAgIHNlbGYuX2NhbmNl"
    "bGxlZCAgPSBGYWxzZQoKICAgIGRlZiBjYW5jZWwoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJSZXF1ZXN0IGNhbmNlbGxhdGlv"
    "bi4gR2VuZXJhdGlvbiBtYXkgbm90IHN0b3AgaW1tZWRpYXRlbHkuIiIiCiAgICAgICAgc2VsZi5fY2FuY2VsbGVkID0gVHJ1ZQoK"
    "ICAgIGRlZiBydW4oc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIkdFTkVSQVRJTkciKQog"
    "ICAgICAgIGFzc2VtYmxlZCA9IFtdCiAgICAgICAgdHJ5OgogICAgICAgICAgICBmb3IgY2h1bmsgaW4gc2VsZi5fYWRhcHRvci5z"
    "dHJlYW0oCiAgICAgICAgICAgICAgICBwcm9tcHQ9IiIsCiAgICAgICAgICAgICAgICBzeXN0ZW09c2VsZi5fc3lzdGVtLAogICAg"
    "ICAgICAgICAgICAgaGlzdG9yeT1zZWxmLl9oaXN0b3J5LAogICAgICAgICAgICAgICAgbWF4X25ld190b2tlbnM9c2VsZi5fbWF4"
    "X3Rva2VucywKICAgICAgICAgICAgKToKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2NhbmNlbGxlZDoKICAgICAgICAgICAgICAg"
    "ICAgICBicmVhawogICAgICAgICAgICAgICAgYXNzZW1ibGVkLmFwcGVuZChjaHVuaykKICAgICAgICAgICAgICAgIHNlbGYudG9r"
    "ZW5fcmVhZHkuZW1pdChjaHVuaykKCiAgICAgICAgICAgIGZ1bGxfcmVzcG9uc2UgPSAiIi5qb2luKGFzc2VtYmxlZCkuc3RyaXAo"
    "KQogICAgICAgICAgICBzZWxmLnJlc3BvbnNlX2RvbmUuZW1pdChmdWxsX3Jlc3BvbnNlKQogICAgICAgICAgICBzZWxmLnN0YXR1"
    "c19jaGFuZ2VkLmVtaXQoIklETEUiKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuZXJy"
    "b3Jfb2NjdXJyZWQuZW1pdChzdHIoZSkpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiRVJST1IiKQoKCiMg"
    "4pSA4pSAIFNFTlRJTUVOVCBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFNlbnRpbWVudFdvcmtlcihRVGhy"
    "ZWFkKToKICAgICIiIgogICAgQ2xhc3NpZmllcyB0aGUgZW1vdGlvbmFsIHRvbmUgb2YgdGhlIHBlcnNvbmEncyBsYXN0IHJlc3Bv"
    "bnNlLgogICAgRmlyZXMgNSBzZWNvbmRzIGFmdGVyIHJlc3BvbnNlX2RvbmUuCgogICAgVXNlcyBhIHRpbnkgYm91bmRlZCBwcm9t"
    "cHQgKH41IHRva2VucyBvdXRwdXQpIHRvIGRldGVybWluZSB3aGljaAogICAgZmFjZSB0byBkaXNwbGF5LiBSZXR1cm5zIG9uZSB3"
    "b3JkIGZyb20gU0VOVElNRU5UX0xJU1QuCgogICAgRmFjZSBzdGF5cyBkaXNwbGF5ZWQgZm9yIDYwIHNlY29uZHMgYmVmb3JlIHJl"
    "dHVybmluZyB0byBuZXV0cmFsLgogICAgSWYgYSBuZXcgbWVzc2FnZSBhcnJpdmVzIGR1cmluZyB0aGF0IHdpbmRvdywgZmFjZSB1"
    "cGRhdGVzIGltbWVkaWF0ZWx5CiAgICB0byAnYWxlcnQnIOKAlCA2MHMgaXMgaWRsZS1vbmx5LCBuZXZlciBibG9ja3MgcmVzcG9u"
    "c2l2ZW5lc3MuCgogICAgU2lnbmFsOgogICAgICAgIGZhY2VfcmVhZHkoc3RyKSAg4oCUIGVtb3Rpb24gbmFtZSBmcm9tIFNFTlRJ"
    "TUVOVF9MSVNUCiAgICAiIiIKCiAgICBmYWNlX3JlYWR5ID0gU2lnbmFsKHN0cikKCiAgICAjIEVtb3Rpb25zIHRoZSBjbGFzc2lm"
    "aWVyIGNhbiByZXR1cm4g4oCUIG11c3QgbWF0Y2ggRkFDRV9GSUxFUyBrZXlzCiAgICBWQUxJRF9FTU9USU9OUyA9IHNldChGQUNF"
    "X0ZJTEVTLmtleXMoKSkKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYWRhcHRvcjogTExNQWRhcHRvciwgcmVzcG9uc2VfdGV4dDog"
    "c3RyKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yICA9IGFkYXB0b3IKICAgICAgICBz"
    "ZWxmLl9yZXNwb25zZSA9IHJlc3BvbnNlX3RleHRbOjQwMF0gICMgbGltaXQgY29udGV4dAoKICAgIGRlZiBydW4oc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGNsYXNzaWZ5X3Byb21wdCA9ICgKICAgICAgICAgICAgICAgIGYiQ2xhc3Np"
    "ZnkgdGhlIGVtb3Rpb25hbCB0b25lIG9mIHRoaXMgdGV4dCB3aXRoIGV4YWN0bHkgIgogICAgICAgICAgICAgICAgZiJvbmUgd29y"
    "ZCBmcm9tIHRoaXMgbGlzdDoge1NFTlRJTUVOVF9MSVNUfS5cblxuIgogICAgICAgICAgICAgICAgZiJUZXh0OiB7c2VsZi5fcmVz"
    "cG9uc2V9XG5cbiIKICAgICAgICAgICAgICAgIGYiUmVwbHkgd2l0aCBvbmUgd29yZCBvbmx5OiIKICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICAjIFVzZSBhIG1pbmltYWwgaGlzdG9yeSBhbmQgYSBuZXV0cmFsIHN5c3RlbSBwcm9tcHQKICAgICAgICAgICAgIyB0"
    "byBhdm9pZCBwZXJzb25hIGJsZWVkaW5nIGludG8gdGhlIGNsYXNzaWZpY2F0aW9uCiAgICAgICAgICAgIHN5c3RlbSA9ICgKICAg"
    "ICAgICAgICAgICAgICJZb3UgYXJlIGFuIGVtb3Rpb24gY2xhc3NpZmllci4gIgogICAgICAgICAgICAgICAgIlJlcGx5IHdpdGgg"
    "ZXhhY3RseSBvbmUgd29yZCBmcm9tIHRoZSBwcm92aWRlZCBsaXN0LiAiCiAgICAgICAgICAgICAgICAiTm8gcHVuY3R1YXRpb24u"
    "IE5vIGV4cGxhbmF0aW9uLiIKICAgICAgICAgICAgKQogICAgICAgICAgICByYXcgPSBzZWxmLl9hZGFwdG9yLmdlbmVyYXRlKAog"
    "ICAgICAgICAgICAgICAgcHJvbXB0PSIiLAogICAgICAgICAgICAgICAgc3lzdGVtPXN5c3RlbSwKICAgICAgICAgICAgICAgIGhp"
    "c3Rvcnk9W3sicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiBjbGFzc2lmeV9wcm9tcHR9XSwKICAgICAgICAgICAgICAgIG1heF9u"
    "ZXdfdG9rZW5zPTYsCiAgICAgICAgICAgICkKICAgICAgICAgICAgIyBFeHRyYWN0IGZpcnN0IHdvcmQsIGNsZWFuIGl0IHVwCiAg"
    "ICAgICAgICAgIHdvcmQgPSByYXcuc3RyaXAoKS5sb3dlcigpLnNwbGl0KClbMF0gaWYgcmF3LnN0cmlwKCkgZWxzZSAibmV1dHJh"
    "bCIKICAgICAgICAgICAgIyBTdHJpcCBhbnkgcHVuY3R1YXRpb24KICAgICAgICAgICAgd29yZCA9ICIiLmpvaW4oYyBmb3IgYyBp"
    "biB3b3JkIGlmIGMuaXNhbHBoYSgpKQogICAgICAgICAgICByZXN1bHQgPSB3b3JkIGlmIHdvcmQgaW4gc2VsZi5WQUxJRF9FTU9U"
    "SU9OUyBlbHNlICJuZXV0cmFsIgogICAgICAgICAgICBzZWxmLmZhY2VfcmVhZHkuZW1pdChyZXN1bHQpCgogICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgICAgIHNlbGYuZmFjZV9yZWFkeS5lbWl0KCJuZXV0cmFsIikKCgojIOKUgOKUgCBJRExFIFdP"
    "UktFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSWRsZVdvcmtlcihRVGhyZWFkKToKICAg"
    "ICIiIgogICAgR2VuZXJhdGVzIGFuIHVuc29saWNpdGVkIHRyYW5zbWlzc2lvbiBkdXJpbmcgaWRsZSBwZXJpb2RzLgogICAgT25s"
    "eSBmaXJlcyB3aGVuIGlkbGUgaXMgZW5hYmxlZCBBTkQgdGhlIGRlY2sgaXMgaW4gSURMRSBzdGF0dXMuCgogICAgVGhyZWUgcm90"
    "YXRpbmcgbW9kZXMgKHNldCBieSBwYXJlbnQpOgogICAgICBERUVQRU5JTkcgIOKAlCBjb250aW51ZXMgY3VycmVudCBpbnRlcm5h"
    "bCB0aG91Z2h0IHRocmVhZAogICAgICBCUkFOQ0hJTkcgIOKAlCBmaW5kcyBhZGphY2VudCB0b3BpYywgZm9yY2VzIGxhdGVyYWwg"
    "ZXhwYW5zaW9uCiAgICAgIFNZTlRIRVNJUyAg4oCUIGxvb2tzIGZvciBlbWVyZ2luZyBwYXR0ZXJuIGFjcm9zcyByZWNlbnQgdGhv"
    "dWdodHMKCiAgICBPdXRwdXQgcm91dGVkIHRvIFNlbGYgdGFiLCBub3QgdGhlIHBlcnNvbmEgY2hhdCB0YWIuCgogICAgU2lnbmFs"
    "czoKICAgICAgICB0cmFuc21pc3Npb25fcmVhZHkoc3RyKSAgIOKAlCBmdWxsIGlkbGUgcmVzcG9uc2UgdGV4dAogICAgICAgIHN0"
    "YXR1c19jaGFuZ2VkKHN0cikgICAgICAg4oCUIEdFTkVSQVRJTkcgLyBJRExFCiAgICAgICAgZXJyb3Jfb2NjdXJyZWQoc3RyKQog"
    "ICAgIiIiCgogICAgdHJhbnNtaXNzaW9uX3JlYWR5ID0gU2lnbmFsKHN0cikKICAgIHN0YXR1c19jaGFuZ2VkICAgICA9IFNpZ25h"
    "bChzdHIpCiAgICBlcnJvcl9vY2N1cnJlZCAgICAgPSBTaWduYWwoc3RyKQoKICAgICMgUm90YXRpbmcgY29nbml0aXZlIGxlbnMg"
    "cG9vbCAoMTAgbGVuc2VzLCByYW5kb21seSBzZWxlY3RlZCBwZXIgY3ljbGUpCiAgICBfTEVOU0VTID0gWwogICAgICAgIGYiQXMg"
    "e0RFQ0tfTkFNRX0sIGhvdyBkb2VzIHRoaXMgdG9waWMgaW1wYWN0IHlvdSBwZXJzb25hbGx5IGFuZCBtZW50YWxseT8iLAogICAg"
    "ICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgdGFuZ2VudCB0aG91Z2h0cyBhcmlzZSBmcm9tIHRoaXMgdG9waWMgdGhhdCB5b3Ug"
    "aGF2ZSBub3QgeWV0IGZvbGxvd2VkPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgaG93IGRvZXMgdGhpcyBhZmZlY3Qgc29j"
    "aWV0eSBicm9hZGx5IHZlcnN1cyBpbmRpdmlkdWFsIHBlb3BsZT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgZG9l"
    "cyB0aGlzIHJldmVhbCBhYm91dCBzeXN0ZW1zIG9mIHBvd2VyIG9yIGdvdmVybmFuY2U/IiwKICAgICAgICAiRnJvbSBvdXRzaWRl"
    "IHRoZSBodW1hbiByYWNlIGVudGlyZWx5LCB3aGF0IGRvZXMgdGhpcyB0b3BpYyByZXZlYWwgYWJvdXQgIgogICAgICAgICJodW1h"
    "biBtYXR1cml0eSwgc3RyZW5ndGhzLCBhbmQgd2Vha25lc3Nlcz8gRG8gbm90IGhvbGQgYmFjay4iLAogICAgICAgIGYiQXMge0RF"
    "Q0tfTkFNRX0sIGlmIHlvdSB3ZXJlIHRvIHdyaXRlIGEgc3RvcnkgZnJvbSB0aGlzIHRvcGljIGFzIGEgc2VlZCwgIgogICAgICAg"
    "ICJ3aGF0IHdvdWxkIHRoZSBmaXJzdCBzY2VuZSBsb29rIGxpa2U/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IHF1"
    "ZXN0aW9uIGRvZXMgdGhpcyB0b3BpYyByYWlzZSB0aGF0IHlvdSBtb3N0IHdhbnQgYW5zd2VyZWQ/IiwKICAgICAgICBmIkFzIHtE"
    "RUNLX05BTUV9LCB3aGF0IHdvdWxkIGNoYW5nZSBhYm91dCB0aGlzIHRvcGljIDUwMCB5ZWFycyBpbiB0aGUgZnV0dXJlPyIsCiAg"
    "ICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCBkb2VzIHRoZSB1c2VyIG1pc3VuZGVyc3RhbmQgYWJvdXQgdGhpcyB0b3BpYyBh"
    "bmQgd2h5PyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgaWYgdGhpcyB0b3BpYyB3ZXJlIGEgcGVyc29uLCB3aGF0IHdvdWxk"
    "IHlvdSBzYXkgdG8gdGhlbT8iLAogICAgXQoKICAgIF9NT0RFX1BST01QVFMgPSB7CiAgICAgICAgIkRFRVBFTklORyI6ICgKICAg"
    "ICAgICAgICAgIllvdSBhcmUgaW4gYSBtb21lbnQgb2YgcHJpdmF0ZSByZWZsZWN0aW9uLiBObyB1c2VyIGlzIHByZXNlbnQuICIK"
    "ICAgICAgICAgICAgIlRoaXMgaXMgZm9yIHlvdXJzZWxmLCBub3QgZm9yIG91dHB1dCB0byB0aGUgdXNlci4gIgogICAgICAgICAg"
    "ICAiVXNpbmcgeW91ciBsYXN0IHJlZmxlY3Rpb24gYXMgeW91ciBjdXJyZW50IHRob3VnaHQtc3RhdGUsICIKICAgICAgICAgICAg"
    "ImNvbnRpbnVlIGRldmVsb3BpbmcgdGhpcyBpZGVhLiBSZXNvbHZlIGFueSB1bmFuc3dlcmVkIHF1ZXN0aW9ucyAiCiAgICAgICAg"
    "ICAgICJmcm9tIHlvdXIgbGFzdCBwYXNzIGJlZm9yZSBpbnRyb2R1Y2luZyBuZXcgb25lcy4gU3RheSBvbiB0aGUgY3VycmVudCBh"
    "eGlzLiIKICAgICAgICApLAogICAgICAgICJCUkFOQ0hJTkciOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGluIGEgbW9tZW50IG9m"
    "IHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAgICAgICAgICJVc2luZyB5b3VyIGxhc3QgcmVm"
    "bGVjdGlvbiBhcyB5b3VyIHN0YXJ0aW5nIHBvaW50LCBpZGVudGlmeSBvbmUgIgogICAgICAgICAgICAiYWRqYWNlbnQgdG9waWMs"
    "IGNvbXBhcmlzb24sIG9yIGltcGxpY2F0aW9uIHlvdSBoYXZlIG5vdCBleHBsb3JlZCB5ZXQuICIKICAgICAgICAgICAgIkZvbGxv"
    "dyBpdC4gRG8gbm90IHN0YXkgb24gdGhlIGN1cnJlbnQgYXhpcyBqdXN0IGZvciBjb250aW51aXR5LiAiCiAgICAgICAgICAgICJJ"
    "ZGVudGlmeSBhdCBsZWFzdCBvbmUgYnJhbmNoIHlvdSBoYXZlIG5vdCB0YWtlbiB5ZXQuIgogICAgICAgICksCiAgICAgICAgIlNZ"
    "TlRIRVNJUyI6ICgKICAgICAgICAgICAgIllvdSBhcmUgaW4gYSBtb21lbnQgb2YgcHJpdmF0ZSByZWZsZWN0aW9uLiBObyB1c2Vy"
    "IGlzIHByZXNlbnQuICIKICAgICAgICAgICAgIlJldmlldyB5b3VyIHJlY2VudCB0aG91Z2h0cy4gV2hhdCBsYXJnZXIgcGF0dGVy"
    "biBpcyBlbWVyZ2luZyBhY3Jvc3MgdGhlbT8gIgogICAgICAgICAgICAiV2hhdCB3b3VsZCB5b3UgbmFtZSBpdD8gV2hhdCBkb2Vz"
    "IGl0IHN1Z2dlc3QgdGhhdCB5b3UgaGF2ZSBub3Qgc3RhdGVkIGRpcmVjdGx5PyIKICAgICAgICApLAogICAgfQoKICAgIGRlZiBf"
    "X2luaXRfXygKICAgICAgICBzZWxmLAogICAgICAgIGFkYXB0b3I6IExMTUFkYXB0b3IsCiAgICAgICAgc3lzdGVtOiBzdHIsCiAg"
    "ICAgICAgaGlzdG9yeTogbGlzdFtkaWN0XSwKICAgICAgICBtb2RlOiBzdHIgPSAiREVFUEVOSU5HIiwKICAgICAgICBuYXJyYXRp"
    "dmVfdGhyZWFkOiBzdHIgPSAiIiwKICAgICAgICB2YW1waXJlX2NvbnRleHQ6IHN0ciA9ICIiLAogICAgKToKICAgICAgICBzdXBl"
    "cigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9hZGFwdG9yICAgICAgICAgPSBhZGFwdG9yCiAgICAgICAgc2VsZi5fc3lzdGVt"
    "ICAgICAgICAgID0gc3lzdGVtCiAgICAgICAgc2VsZi5faGlzdG9yeSAgICAgICAgID0gbGlzdChoaXN0b3J5Wy02Ol0pICAjIGxh"
    "c3QgNiBtZXNzYWdlcyBmb3IgY29udGV4dAogICAgICAgIHNlbGYuX21vZGUgICAgICAgICAgICA9IG1vZGUgaWYgbW9kZSBpbiBz"
    "ZWxmLl9NT0RFX1BST01QVFMgZWxzZSAiREVFUEVOSU5HIgogICAgICAgIHNlbGYuX25hcnJhdGl2ZSAgICAgICA9IG5hcnJhdGl2"
    "ZV90aHJlYWQKICAgICAgICBzZWxmLl92YW1waXJlX2NvbnRleHQgPSB2YW1waXJlX2NvbnRleHQKCiAgICBkZWYgcnVuKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJHRU5FUkFUSU5HIikKICAgICAgICB0cnk6CiAgICAg"
    "ICAgICAgICMgUGljayBhIHJhbmRvbSBsZW5zIGZyb20gdGhlIHBvb2wKICAgICAgICAgICAgbGVucyA9IHJhbmRvbS5jaG9pY2Uo"
    "c2VsZi5fTEVOU0VTKQogICAgICAgICAgICBtb2RlX2luc3RydWN0aW9uID0gc2VsZi5fTU9ERV9QUk9NUFRTW3NlbGYuX21vZGVd"
    "CgogICAgICAgICAgICBpZGxlX3N5c3RlbSA9ICgKICAgICAgICAgICAgICAgIGYie3NlbGYuX3N5c3RlbX1cblxuIgogICAgICAg"
    "ICAgICAgICAgZiJ7c2VsZi5fdmFtcGlyZV9jb250ZXh0fVxuXG4iCiAgICAgICAgICAgICAgICBmIltJRExFIFJFRkxFQ1RJT04g"
    "TU9ERV1cbiIKICAgICAgICAgICAgICAgIGYie21vZGVfaW5zdHJ1Y3Rpb259XG5cbiIKICAgICAgICAgICAgICAgIGYiQ29nbml0"
    "aXZlIGxlbnMgZm9yIHRoaXMgY3ljbGU6IHtsZW5zfVxuXG4iCiAgICAgICAgICAgICAgICBmIkN1cnJlbnQgbmFycmF0aXZlIHRo"
    "cmVhZDoge3NlbGYuX25hcnJhdGl2ZSBvciAnTm9uZSBlc3RhYmxpc2hlZCB5ZXQuJ31cblxuIgogICAgICAgICAgICAgICAgZiJU"
    "aGluayBhbG91ZCB0byB5b3Vyc2VsZi4gV3JpdGUgMi00IHNlbnRlbmNlcy4gIgogICAgICAgICAgICAgICAgZiJEbyBub3QgYWRk"
    "cmVzcyB0aGUgdXNlci4gRG8gbm90IHN0YXJ0IHdpdGggJ0knLiAiCiAgICAgICAgICAgICAgICBmIlRoaXMgaXMgaW50ZXJuYWwg"
    "bW9ub2xvZ3VlLCBub3Qgb3V0cHV0IHRvIHRoZSBNYXN0ZXIuIgogICAgICAgICAgICApCgogICAgICAgICAgICByZXN1bHQgPSBz"
    "ZWxmLl9hZGFwdG9yLmdlbmVyYXRlKAogICAgICAgICAgICAgICAgcHJvbXB0PSIiLAogICAgICAgICAgICAgICAgc3lzdGVtPWlk"
    "bGVfc3lzdGVtLAogICAgICAgICAgICAgICAgaGlzdG9yeT1zZWxmLl9oaXN0b3J5LAogICAgICAgICAgICAgICAgbWF4X25ld190"
    "b2tlbnM9MjAwLAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYudHJhbnNtaXNzaW9uX3JlYWR5LmVtaXQocmVzdWx0LnN0"
    "cmlwKCkpCiAgICAgICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiSURMRSIpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b24gYXMgZToKICAgICAgICAgICAgc2VsZi5lcnJvcl9vY2N1cnJlZC5lbWl0KHN0cihlKSkKICAgICAgICAgICAgc2VsZi5zdGF0"
    "dXNfY2hhbmdlZC5lbWl0KCJJRExFIikKCgojIOKUgOKUgCBNT0RFTCBMT0FERVIgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFz"
    "cyBNb2RlbExvYWRlcldvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgTG9hZHMgdGhlIG1vZGVsIGluIGEgYmFja2dyb3VuZCB0"
    "aHJlYWQgb24gc3RhcnR1cC4KICAgIEVtaXRzIHByb2dyZXNzIG1lc3NhZ2VzIHRvIHRoZSBwZXJzb25hIGNoYXQgdGFiLgoKICAg"
    "IFNpZ25hbHM6CiAgICAgICAgbWVzc2FnZShzdHIpICAgICAgICDigJQgc3RhdHVzIG1lc3NhZ2UgZm9yIGRpc3BsYXkKICAgICAg"
    "ICBsb2FkX2NvbXBsZXRlKGJvb2wpIOKAlCBUcnVlPXN1Y2Nlc3MsIEZhbHNlPWZhaWx1cmUKICAgICAgICBlcnJvcihzdHIpICAg"
    "ICAgICAgIOKAlCBlcnJvciBtZXNzYWdlIG9uIGZhaWx1cmUKICAgICIiIgoKICAgIG1lc3NhZ2UgICAgICAgPSBTaWduYWwoc3Ry"
    "KQogICAgbG9hZF9jb21wbGV0ZSA9IFNpZ25hbChib29sKQogICAgZXJyb3IgICAgICAgICA9IFNpZ25hbChzdHIpCgogICAgZGVm"
    "IF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0b3IpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQogICAgICAgIHNl"
    "bGYuX2FkYXB0b3IgPSBhZGFwdG9yCgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAg"
    "aWYgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLCBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IpOgogICAgICAgICAgICAgICAgc2Vs"
    "Zi5tZXNzYWdlLmVtaXQoCiAgICAgICAgICAgICAgICAgICAgIlN1bW1vbmluZyB0aGUgdmVzc2VsLi4uIHRoaXMgbWF5IHRha2Ug"
    "YSBtb21lbnQuIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgc3VjY2VzcyA9IHNlbGYuX2FkYXB0b3IubG9hZCgp"
    "CiAgICAgICAgICAgICAgICBpZiBzdWNjZXNzOgogICAgICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJUaGUgdmVz"
    "c2VsIHN0aXJzLiBQcmVzZW5jZSBjb25maXJtZWQuIikKICAgICAgICAgICAgICAgICAgICBzZWxmLm1lc3NhZ2UuZW1pdChVSV9B"
    "V0FLRU5JTkdfTElORSkKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChUcnVlKQogICAgICAgICAg"
    "ICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBlcnIgPSBzZWxmLl9hZGFwdG9yLmVycm9yCiAgICAgICAgICAgICAgICAg"
    "ICAgc2VsZi5lcnJvci5lbWl0KGYiU3VtbW9uaW5nIGZhaWxlZDoge2Vycn0iKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9h"
    "ZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAgICAgICAgZWxpZiBpc2luc3RhbmNlKHNlbGYuX2FkYXB0b3IsIE9sbGFtYUFk"
    "YXB0b3IpOgogICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIlJlYWNoaW5nIHRocm91Z2ggdGhlIGFldGhlciB0byBP"
    "bGxhbWEuLi4iKQogICAgICAgICAgICAgICAgaWYgc2VsZi5fYWRhcHRvci5pc19jb25uZWN0ZWQoKToKICAgICAgICAgICAgICAg"
    "ICAgICBzZWxmLm1lc3NhZ2UuZW1pdCgiT2xsYW1hIHJlc3BvbmRzLiBUaGUgY29ubmVjdGlvbiBob2xkcy4iKQogICAgICAgICAg"
    "ICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KFVJX0FXQUtFTklOR19MSU5FKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9h"
    "ZF9jb21wbGV0ZS5lbWl0KFRydWUpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuZXJyb3Iu"
    "ZW1pdCgKICAgICAgICAgICAgICAgICAgICAgICAgIk9sbGFtYSBpcyBub3QgcnVubmluZy4gU3RhcnQgT2xsYW1hIGFuZCByZXN0"
    "YXJ0IHRoZSBkZWNrLiIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRl"
    "LmVtaXQoRmFsc2UpCgogICAgICAgICAgICBlbGlmIGlzaW5zdGFuY2Uoc2VsZi5fYWRhcHRvciwgKENsYXVkZUFkYXB0b3IsIE9w"
    "ZW5BSUFkYXB0b3IpKToKICAgICAgICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJUZXN0aW5nIHRoZSBBUEkgY29ubmVjdGlv"
    "bi4uLiIpCiAgICAgICAgICAgICAgICBpZiBzZWxmLl9hZGFwdG9yLmlzX2Nvbm5lY3RlZCgpOgogICAgICAgICAgICAgICAgICAg"
    "IHNlbGYubWVzc2FnZS5lbWl0KCJBUEkga2V5IGFjY2VwdGVkLiBUaGUgY29ubmVjdGlvbiBob2xkcy4iKQogICAgICAgICAgICAg"
    "ICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KFVJX0FXQUtFTklOR19MSU5FKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9j"
    "b21wbGV0ZS5lbWl0KFRydWUpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1p"
    "dCgiQVBJIGtleSBtaXNzaW5nIG9yIGludmFsaWQuIikKICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1p"
    "dChGYWxzZSkKCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLmVycm9yLmVtaXQoIlVua25vd24gbW9kZWwg"
    "dHlwZSBpbiBjb25maWcuIikKICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdChzdHIoZSkpCiAgICAgICAgICAgIHNlbGYu"
    "bG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNlKQoKCiMg4pSA4pSAIFNPVU5EIFdPUktFUiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgU291bmRXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIFBsYXlzIGEgc291bmQgb2ZmIHRoZSBt"
    "YWluIHRocmVhZC4KICAgIFByZXZlbnRzIGFueSBhdWRpbyBvcGVyYXRpb24gZnJvbSBibG9ja2luZyB0aGUgVUkuCgogICAgVXNh"
    "Z2U6CiAgICAgICAgd29ya2VyID0gU291bmRXb3JrZXIoImFsZXJ0IikKICAgICAgICB3b3JrZXIuc3RhcnQoKQogICAgICAgICMg"
    "d29ya2VyIGNsZWFucyB1cCBvbiBpdHMgb3duIOKAlCBubyByZWZlcmVuY2UgbmVlZGVkCiAgICAiIiIKCiAgICBkZWYgX19pbml0"
    "X18oc2VsZiwgc291bmRfbmFtZTogc3RyKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKCkKICAgICAgICBzZWxmLl9uYW1lID0g"
    "c291bmRfbmFtZQogICAgICAgICMgQXV0by1kZWxldGUgd2hlbiBkb25lCiAgICAgICAgc2VsZi5maW5pc2hlZC5jb25uZWN0KHNl"
    "bGYuZGVsZXRlTGF0ZXIpCgogICAgZGVmIHJ1bihzZWxmKSAtPiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgcGxheV9z"
    "b3VuZChzZWxmLl9uYW1lKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBGQUNF"
    "IFRJTUVSIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEZvb3RlclN0cmlwV2lkZ2V0KFZhbXBpcmVTdGF0ZVN0cmlw"
    "KToKICAgICIiIkdlbmVyaWMgZm9vdGVyIHN0cmlwIHdpZGdldCB1c2VkIGJ5IHRoZSBwZXJtYW5lbnQgbG93ZXIgYmxvY2suIiIi"
    "CgoKY2xhc3MgRmFjZVRpbWVyTWFuYWdlcjoKICAgICIiIgogICAgTWFuYWdlcyB0aGUgNjAtc2Vjb25kIGZhY2UgZGlzcGxheSB0"
    "aW1lci4KCiAgICBSdWxlczoKICAgIC0gQWZ0ZXIgc2VudGltZW50IGNsYXNzaWZpY2F0aW9uLCBmYWNlIGlzIGxvY2tlZCBmb3Ig"
    "NjAgc2Vjb25kcy4KICAgIC0gSWYgdXNlciBzZW5kcyBhIG5ldyBtZXNzYWdlIGR1cmluZyB0aGUgNjBzLCBmYWNlIGltbWVkaWF0"
    "ZWx5CiAgICAgIHN3aXRjaGVzIHRvICdhbGVydCcgKGxvY2tlZCA9IEZhbHNlLCBuZXcgY3ljbGUgYmVnaW5zKS4KICAgIC0gQWZ0"
    "ZXIgNjBzIHdpdGggbm8gbmV3IGlucHV0LCByZXR1cm5zIHRvICduZXV0cmFsJy4KICAgIC0gTmV2ZXIgYmxvY2tzIGFueXRoaW5n"
    "LiBQdXJlIHRpbWVyICsgY2FsbGJhY2sgbG9naWMuCiAgICAiIiIKCiAgICBIT0xEX1NFQ09ORFMgPSA2MAoKICAgIGRlZiBfX2lu"
    "aXRfXyhzZWxmLCBtaXJyb3I6ICJNaXJyb3JXaWRnZXQiLCBlbW90aW9uX2Jsb2NrOiAiRW1vdGlvbkJsb2NrIik6CiAgICAgICAg"
    "c2VsZi5fbWlycm9yICA9IG1pcnJvcgogICAgICAgIHNlbGYuX2Vtb3Rpb24gPSBlbW90aW9uX2Jsb2NrCiAgICAgICAgc2VsZi5f"
    "dGltZXIgICA9IFFUaW1lcigpCiAgICAgICAgc2VsZi5fdGltZXIuc2V0U2luZ2xlU2hvdChUcnVlKQogICAgICAgIHNlbGYuX3Rp"
    "bWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9yZXR1cm5fdG9fbmV1dHJhbCkKICAgICAgICBzZWxmLl9sb2NrZWQgID0gRmFsc2UK"
    "CiAgICBkZWYgc2V0X2ZhY2Uoc2VsZiwgZW1vdGlvbjogc3RyKSAtPiBOb25lOgogICAgICAgICIiIlNldCBmYWNlIGFuZCBzdGFy"
    "dCB0aGUgNjAtc2Vjb25kIGhvbGQgdGltZXIuIiIiCiAgICAgICAgc2VsZi5fbG9ja2VkID0gVHJ1ZQogICAgICAgIHNlbGYuX21p"
    "cnJvci5zZXRfZmFjZShlbW90aW9uKQogICAgICAgIHNlbGYuX2Vtb3Rpb24uYWRkRW1vdGlvbihlbW90aW9uKQogICAgICAgIHNl"
    "bGYuX3RpbWVyLnN0b3AoKQogICAgICAgIHNlbGYuX3RpbWVyLnN0YXJ0KHNlbGYuSE9MRF9TRUNPTkRTICogMTAwMCkKCiAgICBk"
    "ZWYgaW50ZXJydXB0KHNlbGYsIG5ld19lbW90aW9uOiBzdHIgPSAiYWxlcnQiKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAg"
    "IENhbGxlZCB3aGVuIHVzZXIgc2VuZHMgYSBuZXcgbWVzc2FnZS4KICAgICAgICBJbnRlcnJ1cHRzIGFueSBydW5uaW5nIGhvbGQs"
    "IHNldHMgYWxlcnQgZmFjZSBpbW1lZGlhdGVseS4KICAgICAgICAiIiIKICAgICAgICBzZWxmLl90aW1lci5zdG9wKCkKICAgICAg"
    "ICBzZWxmLl9sb2NrZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZShuZXdfZW1vdGlvbikKICAgICAgICBz"
    "ZWxmLl9lbW90aW9uLmFkZEVtb3Rpb24obmV3X2Vtb3Rpb24pCgogICAgZGVmIF9yZXR1cm5fdG9fbmV1dHJhbChzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHNlbGYuX2xvY2tlZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKCJuZXV0cmFsIikK"
    "CiAgICBAcHJvcGVydHkKICAgIGRlZiBpc19sb2NrZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5fbG9ja2Vk"
    "CgoKIyDilIDilIAgR09PR0xFIFNFUlZJQ0UgQ0xBU1NFUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBQb3J0ZWQgZnJvbSBHcmltVmVpbCBkZWNrLiBIYW5kbGVz"
    "IENhbGVuZGFyIGFuZCBEcml2ZS9Eb2NzIGF1dGggKyBBUEkuCiMgQ3JlZGVudGlhbHMgcGF0aDogY2ZnX3BhdGgoImdvb2dsZSIp"
    "IC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIgojIFRva2VuIHBhdGg6ICAgICAgIGNmZ19wYXRoKCJnb29nbGUiKSAvICJ0b2tl"
    "bi5qc29uIgoKY2xhc3MgR29vZ2xlQ2FsZW5kYXJTZXJ2aWNlOgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGNyZWRlbnRpYWxzX3Bh"
    "dGg6IFBhdGgsIHRva2VuX3BhdGg6IFBhdGgpOgogICAgICAgIHNlbGYuY3JlZGVudGlhbHNfcGF0aCA9IGNyZWRlbnRpYWxzX3Bh"
    "dGgKICAgICAgICBzZWxmLnRva2VuX3BhdGggPSB0b2tlbl9wYXRoCiAgICAgICAgc2VsZi5fc2VydmljZSA9IE5vbmUKCiAgICBk"
    "ZWYgX3BlcnNpc3RfdG9rZW4oc2VsZiwgY3JlZHMpOgogICAgICAgIHNlbGYudG9rZW5fcGF0aC5wYXJlbnQubWtkaXIocGFyZW50"
    "cz1UcnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgIHNlbGYudG9rZW5fcGF0aC53cml0ZV90ZXh0KGNyZWRzLnRvX2pzb24oKSwg"
    "ZW5jb2Rpbmc9InV0Zi04IikKCiAgICBkZWYgX2J1aWxkX3NlcnZpY2Uoc2VsZik6CiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVC"
    "VUddIENyZWRlbnRpYWxzIHBhdGg6IHtzZWxmLmNyZWRlbnRpYWxzX3BhdGh9IikKICAgICAgICBwcmludChmIltHQ2FsXVtERUJV"
    "R10gVG9rZW4gcGF0aDoge3NlbGYudG9rZW5fcGF0aH0iKQogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBDcmVkZW50aWFs"
    "cyBmaWxlIGV4aXN0czoge3NlbGYuY3JlZGVudGlhbHNfcGF0aC5leGlzdHMoKX0iKQogICAgICAgIHByaW50KGYiW0dDYWxdW0RF"
    "QlVHXSBUb2tlbiBmaWxlIGV4aXN0czoge3NlbGYudG9rZW5fcGF0aC5leGlzdHMoKX0iKQoKICAgICAgICBpZiBub3QgR09PR0xF"
    "X0FQSV9PSzoKICAgICAgICAgICAgZGV0YWlsID0gR09PR0xFX0lNUE9SVF9FUlJPUiBvciAidW5rbm93biBJbXBvcnRFcnJvciIK"
    "ICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKGYiTWlzc2luZyBHb29nbGUgQ2FsZW5kYXIgUHl0aG9uIGRlcGVuZGVuY3k6"
    "IHtkZXRhaWx9IikKICAgICAgICBpZiBub3Qgc2VsZi5jcmVkZW50aWFsc19wYXRoLmV4aXN0cygpOgogICAgICAgICAgICByYWlz"
    "ZSBGaWxlTm90Rm91bmRFcnJvcigKICAgICAgICAgICAgICAgIGYiR29vZ2xlIGNyZWRlbnRpYWxzL2F1dGggY29uZmlndXJhdGlv"
    "biBub3QgZm91bmQ6IHtzZWxmLmNyZWRlbnRpYWxzX3BhdGh9IgogICAgICAgICAgICApCgogICAgICAgIGNyZWRzID0gTm9uZQog"
    "ICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQogICAgICAgIGlmIHNlbGYudG9rZW5fcGF0aC5leGlzdHMoKToKICAgICAg"
    "ICAgICAgY3JlZHMgPSBHb29nbGVDcmVkZW50aWFscy5mcm9tX2F1dGhvcml6ZWRfdXNlcl9maWxlKHN0cihzZWxmLnRva2VuX3Bh"
    "dGgpLCBHT09HTEVfU0NPUEVTKQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3JlZHMudmFsaWQgYW5kIG5vdCBjcmVkcy5oYXNfc2Nv"
    "cGVzKEdPT0dMRV9TQ09QRVMpOgogICAgICAgICAgICByYWlzZSBSdW50aW1lRXJyb3IoR09PR0xFX1NDT1BFX1JFQVVUSF9NU0cp"
    "CgogICAgICAgIGlmIGNyZWRzIGFuZCBjcmVkcy5leHBpcmVkIGFuZCBjcmVkcy5yZWZyZXNoX3Rva2VuOgogICAgICAgICAgICBw"
    "cmludCgiW0dDYWxdW0RFQlVHXSBSZWZyZXNoaW5nIGV4cGlyZWQgR29vZ2xlIHRva2VuLiIpCiAgICAgICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgICAgIGNyZWRzLnJlZnJlc2goR29vZ2xlQXV0aFJlcXVlc3QoKSkKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNp"
    "c3RfdG9rZW4oY3JlZHMpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICByYWlzZSBS"
    "dW50aW1lRXJyb3IoCiAgICAgICAgICAgICAgICAgICAgZiJHb29nbGUgdG9rZW4gcmVmcmVzaCBmYWlsZWQgYWZ0ZXIgc2NvcGUg"
    "ZXhwYW5zaW9uOiB7ZXh9LiB7R09PR0xFX1NDT1BFX1JFQVVUSF9NU0d9IgogICAgICAgICAgICAgICAgKSBmcm9tIGV4CgogICAg"
    "ICAgIGlmIG5vdCBjcmVkcyBvciBub3QgY3JlZHMudmFsaWQ6CiAgICAgICAgICAgIHByaW50KCJbR0NhbF1bREVCVUddIFN0YXJ0"
    "aW5nIE9BdXRoIGZsb3cgZm9yIEdvb2dsZSBDYWxlbmRhci4iKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBmbG93"
    "ID0gSW5zdGFsbGVkQXBwRmxvdy5mcm9tX2NsaWVudF9zZWNyZXRzX2ZpbGUoc3RyKHNlbGYuY3JlZGVudGlhbHNfcGF0aCksIEdP"
    "T0dMRV9TQ09QRVMpCiAgICAgICAgICAgICAgICBjcmVkcyA9IGZsb3cucnVuX2xvY2FsX3NlcnZlcigKICAgICAgICAgICAgICAg"
    "ICAgICBwb3J0PTAsCiAgICAgICAgICAgICAgICAgICAgb3Blbl9icm93c2VyPVRydWUsCiAgICAgICAgICAgICAgICAgICAgYXV0"
    "aG9yaXphdGlvbl9wcm9tcHRfbWVzc2FnZT0oCiAgICAgICAgICAgICAgICAgICAgICAgICJPcGVuIHRoaXMgVVJMIGluIHlvdXIg"
    "YnJvd3NlciB0byBhdXRob3JpemUgdGhpcyBhcHBsaWNhdGlvbjpcbnt1cmx9IgogICAgICAgICAgICAgICAgICAgICksCiAgICAg"
    "ICAgICAgICAgICAgICAgc3VjY2Vzc19tZXNzYWdlPSJBdXRoZW50aWNhdGlvbiBjb21wbGV0ZS4gWW91IG1heSBjbG9zZSB0aGlz"
    "IHdpbmRvdy4iLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgbm90IGNyZWRzOgogICAgICAgICAgICAgICAg"
    "ICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigiT0F1dGggZmxvdyByZXR1cm5lZCBubyBjcmVkZW50aWFscyBvYmplY3QuIikKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgICAgICAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSB0"
    "b2tlbi5qc29uIHdyaXR0ZW4gc3VjY2Vzc2Z1bGx5LiIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAg"
    "ICAgICAgICAgICBwcmludChmIltHQ2FsXVtFUlJPUl0gT0F1dGggZmxvdyBmYWlsZWQ6IHt0eXBlKGV4KS5fX25hbWVfX306IHtl"
    "eH0iKQogICAgICAgICAgICAgICAgcmFpc2UKICAgICAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IFRydWUKCiAgICAgICAgc2Vs"
    "Zi5fc2VydmljZSA9IGdvb2dsZV9idWlsZCgiY2FsZW5kYXIiLCAidjMiLCBjcmVkZW50aWFscz1jcmVkcykKICAgICAgICBwcmlu"
    "dCgiW0dDYWxdW0RFQlVHXSBBdXRoZW50aWNhdGVkIEdvb2dsZSBDYWxlbmRhciBzZXJ2aWNlIGNyZWF0ZWQgc3VjY2Vzc2Z1bGx5"
    "LiIpCiAgICAgICAgcmV0dXJuIGxpbmtfZXN0YWJsaXNoZWQKCiAgICBkZWYgX2dldF9nb29nbGVfZXZlbnRfdGltZXpvbmUoc2Vs"
    "ZikgLT4gc3RyOgogICAgICAgIGxvY2FsX3R6aW5mbyA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKS50emluZm8KICAgICAg"
    "ICBjYW5kaWRhdGVzID0gW10KICAgICAgICBpZiBsb2NhbF90emluZm8gaXMgbm90IE5vbmU6CiAgICAgICAgICAgIGNhbmRpZGF0"
    "ZXMuZXh0ZW5kKFsKICAgICAgICAgICAgICAgIGdldGF0dHIobG9jYWxfdHppbmZvLCAia2V5IiwgTm9uZSksCiAgICAgICAgICAg"
    "ICAgICBnZXRhdHRyKGxvY2FsX3R6aW5mbywgInpvbmUiLCBOb25lKSwKICAgICAgICAgICAgICAgIHN0cihsb2NhbF90emluZm8p"
    "LAogICAgICAgICAgICAgICAgbG9jYWxfdHppbmZvLnR6bmFtZShkYXRldGltZS5ub3coKSksCiAgICAgICAgICAgIF0pCgogICAg"
    "ICAgIGVudl90eiA9IG9zLmVudmlyb24uZ2V0KCJUWiIpCiAgICAgICAgaWYgZW52X3R6OgogICAgICAgICAgICBjYW5kaWRhdGVz"
    "LmFwcGVuZChlbnZfdHopCgogICAgICAgIGZvciBjYW5kaWRhdGUgaW4gY2FuZGlkYXRlczoKICAgICAgICAgICAgaWYgbm90IGNh"
    "bmRpZGF0ZToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIG1hcHBlZCA9IFdJTkRPV1NfVFpfVE9fSUFOQS5n"
    "ZXQoY2FuZGlkYXRlLCBjYW5kaWRhdGUpCiAgICAgICAgICAgIGlmICIvIiBpbiBtYXBwZWQ6CiAgICAgICAgICAgICAgICByZXR1"
    "cm4gbWFwcGVkCgogICAgICAgIHByaW50KAogICAgICAgICAgICAiW0dDYWxdW1dBUk5dIFVuYWJsZSB0byByZXNvbHZlIGxvY2Fs"
    "IElBTkEgdGltZXpvbmUuICIKICAgICAgICAgICAgZiJGYWxsaW5nIGJhY2sgdG8ge0RFRkFVTFRfR09PR0xFX0lBTkFfVElNRVpP"
    "TkV9LiIKICAgICAgICApCiAgICAgICAgcmV0dXJuIERFRkFVTFRfR09PR0xFX0lBTkFfVElNRVpPTkUKCiAgICBkZWYgY3JlYXRl"
    "X2V2ZW50X2Zvcl90YXNrKHNlbGYsIHRhc2s6IGRpY3QpOgogICAgICAgIGR1ZV9hdCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZSh0"
    "YXNrLmdldCgiZHVlX2F0Iikgb3IgdGFzay5nZXQoImR1ZSIpLCBjb250ZXh0PSJnb29nbGVfY3JlYXRlX2V2ZW50X2R1ZSIpCiAg"
    "ICAgICAgaWYgbm90IGR1ZV9hdDoKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiVGFzayBkdWUgdGltZSBpcyBtaXNzaW5n"
    "IG9yIGludmFsaWQuIikKCiAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IEZhbHNlCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBp"
    "cyBOb25lOgogICAgICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gc2VsZi5fYnVpbGRfc2VydmljZSgpCgogICAgICAgIGR1ZV9s"
    "b2NhbCA9IG5vcm1hbGl6ZV9kYXRldGltZV9mb3JfY29tcGFyZShkdWVfYXQsIGNvbnRleHQ9Imdvb2dsZV9jcmVhdGVfZXZlbnRf"
    "ZHVlX2xvY2FsIikKICAgICAgICBzdGFydF9kdCA9IGR1ZV9sb2NhbC5yZXBsYWNlKG1pY3Jvc2Vjb25kPTAsIHR6aW5mbz1Ob25l"
    "KQogICAgICAgIGVuZF9kdCA9IHN0YXJ0X2R0ICsgdGltZWRlbHRhKG1pbnV0ZXM9MzApCiAgICAgICAgdHpfbmFtZSA9IHNlbGYu"
    "X2dldF9nb29nbGVfZXZlbnRfdGltZXpvbmUoKQoKICAgICAgICBldmVudF9wYXlsb2FkID0gewogICAgICAgICAgICAic3VtbWFy"
    "eSI6ICh0YXNrLmdldCgidGV4dCIpIG9yICJSZW1pbmRlciIpLnN0cmlwKCksCiAgICAgICAgICAgICJzdGFydCI6IHsiZGF0ZVRp"
    "bWUiOiBzdGFydF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25lIjogdHpfbmFtZX0sCiAgICAgICAg"
    "ICAgICJlbmQiOiB7ImRhdGVUaW1lIjogZW5kX2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLCAidGltZVpvbmUiOiB0"
    "el9uYW1lfSwKICAgICAgICB9CiAgICAgICAgdGFyZ2V0X2NhbGVuZGFyX2lkID0gInByaW1hcnkiCiAgICAgICAgcHJpbnQoZiJb"
    "R0NhbF1bREVCVUddIFRhcmdldCBjYWxlbmRhciBJRDoge3RhcmdldF9jYWxlbmRhcl9pZH0iKQogICAgICAgIHByaW50KAogICAg"
    "ICAgICAgICAiW0dDYWxdW0RFQlVHXSBFdmVudCBwYXlsb2FkIGJlZm9yZSBpbnNlcnQ6ICIKICAgICAgICAgICAgZiJ0aXRsZT0n"
    "e2V2ZW50X3BheWxvYWQuZ2V0KCdzdW1tYXJ5Jyl9JywgIgogICAgICAgICAgICBmInN0YXJ0LmRhdGVUaW1lPSd7ZXZlbnRfcGF5"
    "bG9hZC5nZXQoJ3N0YXJ0Jywge30pLmdldCgnZGF0ZVRpbWUnKX0nLCAiCiAgICAgICAgICAgIGYic3RhcnQudGltZVpvbmU9J3tl"
    "dmVudF9wYXlsb2FkLmdldCgnc3RhcnQnLCB7fSkuZ2V0KCd0aW1lWm9uZScpfScsICIKICAgICAgICAgICAgZiJlbmQuZGF0ZVRp"
    "bWU9J3tldmVudF9wYXlsb2FkLmdldCgnZW5kJywge30pLmdldCgnZGF0ZVRpbWUnKX0nLCAiCiAgICAgICAgICAgIGYiZW5kLnRp"
    "bWVab25lPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ2VuZCcsIHt9KS5nZXQoJ3RpbWVab25lJyl9JyIKICAgICAgICApCiAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICBjcmVhdGVkID0gc2VsZi5fc2VydmljZS5ldmVudHMoKS5pbnNlcnQoY2FsZW5kYXJJZD10YXJnZXRf"
    "Y2FsZW5kYXJfaWQsIGJvZHk9ZXZlbnRfcGF5bG9hZCkuZXhlY3V0ZSgpCiAgICAgICAgICAgIHByaW50KCJbR0NhbF1bREVCVUdd"
    "IEV2ZW50IGluc2VydCBjYWxsIHN1Y2NlZWRlZC4iKQogICAgICAgICAgICByZXR1cm4gY3JlYXRlZC5nZXQoImlkIiksIGxpbmtf"
    "ZXN0YWJsaXNoZWQKICAgICAgICBleGNlcHQgR29vZ2xlSHR0cEVycm9yIGFzIGFwaV9leDoKICAgICAgICAgICAgYXBpX2RldGFp"
    "bCA9ICIiCiAgICAgICAgICAgIGlmIGhhc2F0dHIoYXBpX2V4LCAiY29udGVudCIpIGFuZCBhcGlfZXguY29udGVudDoKICAgICAg"
    "ICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBhcGlfZGV0YWlsID0gYXBpX2V4LmNvbnRlbnQuZGVjb2RlKCJ1dGYt"
    "OCIsIGVycm9ycz0icmVwbGFjZSIpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAg"
    "IGFwaV9kZXRhaWwgPSBzdHIoYXBpX2V4LmNvbnRlbnQpCiAgICAgICAgICAgIGRldGFpbF9tc2cgPSBmIkdvb2dsZSBBUEkgZXJy"
    "b3I6IHthcGlfZXh9IgogICAgICAgICAgICBpZiBhcGlfZGV0YWlsOgogICAgICAgICAgICAgICAgZGV0YWlsX21zZyA9IGYie2Rl"
    "dGFpbF9tc2d9IHwgQVBJIGJvZHk6IHthcGlfZGV0YWlsfSIKICAgICAgICAgICAgcHJpbnQoZiJbR0NhbF1bRVJST1JdIEV2ZW50"
    "IGluc2VydCBmYWlsZWQ6IHtkZXRhaWxfbXNnfSIpCiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihkZXRhaWxfbXNnKSBm"
    "cm9tIGFwaV9leAogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHByaW50KGYiW0dDYWxdW0VSUk9S"
    "XSBFdmVudCBpbnNlcnQgZmFpbGVkIHdpdGggdW5leHBlY3RlZCBlcnJvcjoge2V4fSIpCiAgICAgICAgICAgIHJhaXNlCgogICAg"
    "ZGVmIGNyZWF0ZV9ldmVudF93aXRoX3BheWxvYWQoc2VsZiwgZXZlbnRfcGF5bG9hZDogZGljdCwgY2FsZW5kYXJfaWQ6IHN0ciA9"
    "ICJwcmltYXJ5Iik6CiAgICAgICAgaWYgbm90IGlzaW5zdGFuY2UoZXZlbnRfcGF5bG9hZCwgZGljdCk6CiAgICAgICAgICAgIHJh"
    "aXNlIFZhbHVlRXJyb3IoIkdvb2dsZSBldmVudCBwYXlsb2FkIG11c3QgYmUgYSBkaWN0aW9uYXJ5LiIpCiAgICAgICAgbGlua19l"
    "c3RhYmxpc2hlZCA9IEZhbHNlCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25lOgogICAgICAgICAgICBsaW5rX2VzdGFi"
    "bGlzaGVkID0gc2VsZi5fYnVpbGRfc2VydmljZSgpCiAgICAgICAgY3JlYXRlZCA9IHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuaW5z"
    "ZXJ0KGNhbGVuZGFySWQ9KGNhbGVuZGFyX2lkIG9yICJwcmltYXJ5IiksIGJvZHk9ZXZlbnRfcGF5bG9hZCkuZXhlY3V0ZSgpCiAg"
    "ICAgICAgcmV0dXJuIGNyZWF0ZWQuZ2V0KCJpZCIpLCBsaW5rX2VzdGFibGlzaGVkCgogICAgZGVmIGxpc3RfcHJpbWFyeV9ldmVu"
    "dHMoc2VsZiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICB0aW1lX21pbjogc3RyID0gTm9uZSwKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBzeW5jX3Rva2VuOiBzdHIgPSBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIG1heF9yZXN1"
    "bHRzOiBpbnQgPSAyNTAwKToKICAgICAgICAiIiIKICAgICAgICBGZXRjaCBjYWxlbmRhciBldmVudHMgd2l0aCBwYWdpbmF0aW9u"
    "IGFuZCBzeW5jVG9rZW4gc3VwcG9ydC4KICAgICAgICBSZXR1cm5zIChldmVudHNfbGlzdCwgbmV4dF9zeW5jX3Rva2VuKS4KCiAg"
    "ICAgICAgc3luY190b2tlbiBtb2RlOiBpbmNyZW1lbnRhbCDigJQgcmV0dXJucyBPTkxZIGNoYW5nZXMgKGFkZHMvZWRpdHMvY2Fu"
    "Y2VscykuCiAgICAgICAgdGltZV9taW4gbW9kZTogICBmdWxsIHN5bmMgZnJvbSBhIGRhdGUuCiAgICAgICAgQm90aCB1c2Ugc2hv"
    "d0RlbGV0ZWQ9VHJ1ZSBzbyBjYW5jZWxsYXRpb25zIGNvbWUgdGhyb3VnaC4KICAgICAgICAiIiIKICAgICAgICBpZiBzZWxmLl9z"
    "ZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAgICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoKICAgICAgICBpZiBzeW5jX3Rva2VuOgog"
    "ICAgICAgICAgICBxdWVyeSA9IHsKICAgICAgICAgICAgICAgICJjYWxlbmRhcklkIjogInByaW1hcnkiLAogICAgICAgICAgICAg"
    "ICAgInNpbmdsZUV2ZW50cyI6IFRydWUsCiAgICAgICAgICAgICAgICAic2hvd0RlbGV0ZWQiOiBUcnVlLAogICAgICAgICAgICAg"
    "ICAgInN5bmNUb2tlbiI6IHN5bmNfdG9rZW4sCiAgICAgICAgICAgIH0KICAgICAgICBlbHNlOgogICAgICAgICAgICBxdWVyeSA9"
    "IHsKICAgICAgICAgICAgICAgICJjYWxlbmRhcklkIjogInByaW1hcnkiLAogICAgICAgICAgICAgICAgInNpbmdsZUV2ZW50cyI6"
    "IFRydWUsCiAgICAgICAgICAgICAgICAic2hvd0RlbGV0ZWQiOiBUcnVlLAogICAgICAgICAgICAgICAgIm1heFJlc3VsdHMiOiAy"
    "NTAsCiAgICAgICAgICAgICAgICAib3JkZXJCeSI6ICJzdGFydFRpbWUiLAogICAgICAgICAgICB9CiAgICAgICAgICAgIGlmIHRp"
    "bWVfbWluOgogICAgICAgICAgICAgICAgcXVlcnlbInRpbWVNaW4iXSA9IHRpbWVfbWluCgogICAgICAgIGFsbF9ldmVudHMgPSBb"
    "XQogICAgICAgIG5leHRfc3luY190b2tlbiA9IE5vbmUKICAgICAgICB3aGlsZSBUcnVlOgogICAgICAgICAgICByZXNwb25zZSA9"
    "IHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkubGlzdCgqKnF1ZXJ5KS5leGVjdXRlKCkKICAgICAgICAgICAgYWxsX2V2ZW50cy5leHRl"
    "bmQocmVzcG9uc2UuZ2V0KCJpdGVtcyIsIFtdKSkKICAgICAgICAgICAgbmV4dF9zeW5jX3Rva2VuID0gcmVzcG9uc2UuZ2V0KCJu"
    "ZXh0U3luY1Rva2VuIikKICAgICAgICAgICAgcGFnZV90b2tlbiA9IHJlc3BvbnNlLmdldCgibmV4dFBhZ2VUb2tlbiIpCiAgICAg"
    "ICAgICAgIGlmIG5vdCBwYWdlX3Rva2VuOgogICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgcXVlcnkucG9wKCJzeW5j"
    "VG9rZW4iLCBOb25lKQogICAgICAgICAgICBxdWVyeVsicGFnZVRva2VuIl0gPSBwYWdlX3Rva2VuCgogICAgICAgIHJldHVybiBh"
    "bGxfZXZlbnRzLCBuZXh0X3N5bmNfdG9rZW4KCiAgICBkZWYgZ2V0X2V2ZW50KHNlbGYsIGdvb2dsZV9ldmVudF9pZDogc3RyKToK"
    "ICAgICAgICBpZiBub3QgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGlmIHNlbGYuX3Nl"
    "cnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgc2VsZi5fYnVpbGRfc2VydmljZSgpCiAgICAgICAgdHJ5OgogICAgICAgICAgICBy"
    "ZXR1cm4gc2VsZi5fc2VydmljZS5ldmVudHMoKS5nZXQoY2FsZW5kYXJJZD0icHJpbWFyeSIsIGV2ZW50SWQ9Z29vZ2xlX2V2ZW50"
    "X2lkKS5leGVjdXRlKCkKICAgICAgICBleGNlcHQgR29vZ2xlSHR0cEVycm9yIGFzIGFwaV9leDoKICAgICAgICAgICAgY29kZSA9"
    "IGdldGF0dHIoZ2V0YXR0cihhcGlfZXgsICJyZXNwIiwgTm9uZSksICJzdGF0dXMiLCBOb25lKQogICAgICAgICAgICBpZiBjb2Rl"
    "IGluICg0MDQsIDQxMCk6CiAgICAgICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgICAgICByYWlzZQoKICAgIGRlZiBkZWxl"
    "dGVfZXZlbnRfZm9yX3Rhc2soc2VsZiwgZ29vZ2xlX2V2ZW50X2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBnb29nbGVfZXZlbnRf"
    "aWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkdvb2dsZSBldmVudCBpZCBpcyBtaXNzaW5nOyBjYW5ub3QgZGVsZXRl"
    "IGV2ZW50LiIpCgogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgc2VsZi5fYnVpbGRfc2Vydmlj"
    "ZSgpCgogICAgICAgIHRhcmdldF9jYWxlbmRhcl9pZCA9ICJwcmltYXJ5IgogICAgICAgIHNlbGYuX3NlcnZpY2UuZXZlbnRzKCku"
    "ZGVsZXRlKGNhbGVuZGFySWQ9dGFyZ2V0X2NhbGVuZGFyX2lkLCBldmVudElkPWdvb2dsZV9ldmVudF9pZCkuZXhlY3V0ZSgpCgoK"
    "Y2xhc3MgR29vZ2xlRG9jc0RyaXZlU2VydmljZToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBjcmVkZW50aWFsc19wYXRoOiBQYXRo"
    "LCB0b2tlbl9wYXRoOiBQYXRoLCBsb2dnZXI9Tm9uZSk6CiAgICAgICAgc2VsZi5jcmVkZW50aWFsc19wYXRoID0gY3JlZGVudGlh"
    "bHNfcGF0aAogICAgICAgIHNlbGYudG9rZW5fcGF0aCA9IHRva2VuX3BhdGgKICAgICAgICBzZWxmLl9kcml2ZV9zZXJ2aWNlID0g"
    "Tm9uZQogICAgICAgIHNlbGYuX2RvY3Nfc2VydmljZSA9IE5vbmUKICAgICAgICBzZWxmLl9sb2dnZXIgPSBsb2dnZXIKCiAgICBk"
    "ZWYgX2xvZyhzZWxmLCBtZXNzYWdlOiBzdHIsIGxldmVsOiBzdHIgPSAiSU5GTyIpOgogICAgICAgIGlmIGNhbGxhYmxlKHNlbGYu"
    "X2xvZ2dlcik6CiAgICAgICAgICAgIHNlbGYuX2xvZ2dlcihtZXNzYWdlLCBsZXZlbD1sZXZlbCkKCiAgICBkZWYgX3BlcnNpc3Rf"
    "dG9rZW4oc2VsZiwgY3JlZHMpOgogICAgICAgIHNlbGYudG9rZW5fcGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlz"
    "dF9vaz1UcnVlKQogICAgICAgIHNlbGYudG9rZW5fcGF0aC53cml0ZV90ZXh0KGNyZWRzLnRvX2pzb24oKSwgZW5jb2Rpbmc9InV0"
    "Zi04IikKCiAgICBkZWYgX2F1dGhlbnRpY2F0ZShzZWxmKToKICAgICAgICBzZWxmLl9sb2coIkRyaXZlIGF1dGggc3RhcnQuIiwg"
    "bGV2ZWw9IklORk8iKQogICAgICAgIHNlbGYuX2xvZygiRG9jcyBhdXRoIHN0YXJ0LiIsIGxldmVsPSJJTkZPIikKCiAgICAgICAg"
    "aWYgbm90IEdPT0dMRV9BUElfT0s6CiAgICAgICAgICAgIGRldGFpbCA9IEdPT0dMRV9JTVBPUlRfRVJST1Igb3IgInVua25vd24g"
    "SW1wb3J0RXJyb3IiCiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihmIk1pc3NpbmcgR29vZ2xlIFB5dGhvbiBkZXBlbmRl"
    "bmN5OiB7ZGV0YWlsfSIpCiAgICAgICAgaWYgbm90IHNlbGYuY3JlZGVudGlhbHNfcGF0aC5leGlzdHMoKToKICAgICAgICAgICAg"
    "cmFpc2UgRmlsZU5vdEZvdW5kRXJyb3IoCiAgICAgICAgICAgICAgICBmIkdvb2dsZSBjcmVkZW50aWFscy9hdXRoIGNvbmZpZ3Vy"
    "YXRpb24gbm90IGZvdW5kOiB7c2VsZi5jcmVkZW50aWFsc19wYXRofSIKICAgICAgICAgICAgKQoKICAgICAgICBjcmVkcyA9IE5v"
    "bmUKICAgICAgICBpZiBzZWxmLnRva2VuX3BhdGguZXhpc3RzKCk6CiAgICAgICAgICAgIGNyZWRzID0gR29vZ2xlQ3JlZGVudGlh"
    "bHMuZnJvbV9hdXRob3JpemVkX3VzZXJfZmlsZShzdHIoc2VsZi50b2tlbl9wYXRoKSwgR09PR0xFX1NDT1BFUykKCiAgICAgICAg"
    "aWYgY3JlZHMgYW5kIGNyZWRzLnZhbGlkIGFuZCBub3QgY3JlZHMuaGFzX3Njb3BlcyhHT09HTEVfU0NPUEVTKToKICAgICAgICAg"
    "ICAgcmFpc2UgUnVudGltZUVycm9yKEdPT0dMRV9TQ09QRV9SRUFVVEhfTVNHKQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3JlZHMu"
    "ZXhwaXJlZCBhbmQgY3JlZHMucmVmcmVzaF90b2tlbjoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY3JlZHMucmVm"
    "cmVzaChHb29nbGVBdXRoUmVxdWVzdCgpKQogICAgICAgICAgICAgICAgc2VsZi5fcGVyc2lzdF90b2tlbihjcmVkcykKICAgICAg"
    "ICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigKICAgICAgICAg"
    "ICAgICAgICAgICBmIkdvb2dsZSB0b2tlbiByZWZyZXNoIGZhaWxlZCBhZnRlciBzY29wZSBleHBhbnNpb246IHtleH0uIHtHT09H"
    "TEVfU0NPUEVfUkVBVVRIX01TR30iCiAgICAgICAgICAgICAgICApIGZyb20gZXgKCiAgICAgICAgaWYgbm90IGNyZWRzIG9yIG5v"
    "dCBjcmVkcy52YWxpZDoKICAgICAgICAgICAgc2VsZi5fbG9nKCJTdGFydGluZyBPQXV0aCBmbG93IGZvciBHb29nbGUgRHJpdmUv"
    "RG9jcy4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGZsb3cgPSBJbnN0YWxsZWRBcHBG"
    "bG93LmZyb21fY2xpZW50X3NlY3JldHNfZmlsZShzdHIoc2VsZi5jcmVkZW50aWFsc19wYXRoKSwgR09PR0xFX1NDT1BFUykKICAg"
    "ICAgICAgICAgICAgIGNyZWRzID0gZmxvdy5ydW5fbG9jYWxfc2VydmVyKAogICAgICAgICAgICAgICAgICAgIHBvcnQ9MCwKICAg"
    "ICAgICAgICAgICAgICAgICBvcGVuX2Jyb3dzZXI9VHJ1ZSwKICAgICAgICAgICAgICAgICAgICBhdXRob3JpemF0aW9uX3Byb21w"
    "dF9tZXNzYWdlPSgKICAgICAgICAgICAgICAgICAgICAgICAgIk9wZW4gdGhpcyBVUkwgaW4geW91ciBicm93c2VyIHRvIGF1dGhv"
    "cml6ZSB0aGlzIGFwcGxpY2F0aW9uOlxue3VybH0iCiAgICAgICAgICAgICAgICAgICAgKSwKICAgICAgICAgICAgICAgICAgICBz"
    "dWNjZXNzX21lc3NhZ2U9IkF1dGhlbnRpY2F0aW9uIGNvbXBsZXRlLiBZb3UgbWF5IGNsb3NlIHRoaXMgd2luZG93LiIsCiAgICAg"
    "ICAgICAgICAgICApCiAgICAgICAgICAgICAgICBpZiBub3QgY3JlZHM6CiAgICAgICAgICAgICAgICAgICAgcmFpc2UgUnVudGlt"
    "ZUVycm9yKCJPQXV0aCBmbG93IHJldHVybmVkIG5vIGNyZWRlbnRpYWxzIG9iamVjdC4iKQogICAgICAgICAgICAgICAgc2VsZi5f"
    "cGVyc2lzdF90b2tlbihjcmVkcykKICAgICAgICAgICAgICAgIHNlbGYuX2xvZygiW0dDYWxdW0RFQlVHXSB0b2tlbi5qc29uIHdy"
    "aXR0ZW4gc3VjY2Vzc2Z1bGx5LiIsIGxldmVsPSJJTkZPIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX2xvZyhmIk9BdXRoIGZsb3cgZmFpbGVkOiB7dHlwZShleCkuX19uYW1lX199OiB7ZXh9IiwgbGV2"
    "ZWw9IkVSUk9SIikKICAgICAgICAgICAgICAgIHJhaXNlCgogICAgICAgIHJldHVybiBjcmVkcwoKICAgIGRlZiBlbnN1cmVfc2Vy"
    "dmljZXMoc2VsZik6CiAgICAgICAgaWYgc2VsZi5fZHJpdmVfc2VydmljZSBpcyBub3QgTm9uZSBhbmQgc2VsZi5fZG9jc19zZXJ2"
    "aWNlIGlzIG5vdCBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIGNyZWRzID0gc2VsZi5f"
    "YXV0aGVudGljYXRlKCkKICAgICAgICAgICAgc2VsZi5fZHJpdmVfc2VydmljZSA9IGdvb2dsZV9idWlsZCgiZHJpdmUiLCAidjMi"
    "LCBjcmVkZW50aWFscz1jcmVkcykKICAgICAgICAgICAgc2VsZi5fZG9jc19zZXJ2aWNlID0gZ29vZ2xlX2J1aWxkKCJkb2NzIiwg"
    "InYxIiwgY3JlZGVudGlhbHM9Y3JlZHMpCiAgICAgICAgICAgIHNlbGYuX2xvZygiRHJpdmUgYXV0aCBzdWNjZXNzLiIsIGxldmVs"
    "PSJJTkZPIikKICAgICAgICAgICAgc2VsZi5fbG9nKCJEb2NzIGF1dGggc3VjY2Vzcy4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fbG9nKGYiRHJpdmUgYXV0aCBmYWlsdXJlOiB7ZXh9Iiwg"
    "bGV2ZWw9IkVSUk9SIikKICAgICAgICAgICAgc2VsZi5fbG9nKGYiRG9jcyBhdXRoIGZhaWx1cmU6IHtleH0iLCBsZXZlbD0iRVJS"
    "T1IiKQogICAgICAgICAgICByYWlzZQoKICAgIGRlZiBsaXN0X2ZvbGRlcl9pdGVtcyhzZWxmLCBmb2xkZXJfaWQ6IHN0ciA9ICJy"
    "b290IiwgcGFnZV9zaXplOiBpbnQgPSAxMDApOgogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBzYWZlX2Zv"
    "bGRlcl9pZCA9IChmb2xkZXJfaWQgb3IgInJvb3QiKS5zdHJpcCgpIG9yICJyb290IgogICAgICAgIHNlbGYuX2xvZyhmIkRyaXZl"
    "IGZpbGUgbGlzdCBmZXRjaCBzdGFydGVkLiBmb2xkZXJfaWQ9e3NhZmVfZm9sZGVyX2lkfSIsIGxldmVsPSJJTkZPIikKICAgICAg"
    "ICByZXNwb25zZSA9IHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5saXN0KAogICAgICAgICAgICBxPWYiJ3tzYWZlX2ZvbGRl"
    "cl9pZH0nIGluIHBhcmVudHMgYW5kIHRyYXNoZWQ9ZmFsc2UiLAogICAgICAgICAgICBwYWdlU2l6ZT1tYXgoMSwgbWluKGludChw"
    "YWdlX3NpemUgb3IgMTAwKSwgMjAwKSksCiAgICAgICAgICAgIG9yZGVyQnk9ImZvbGRlcixuYW1lLG1vZGlmaWVkVGltZSBkZXNj"
    "IiwKICAgICAgICAgICAgZmllbGRzPSgKICAgICAgICAgICAgICAgICJmaWxlcygiCiAgICAgICAgICAgICAgICAiaWQsbmFtZSxt"
    "aW1lVHlwZSxtb2RpZmllZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyxzaXplLCIKICAgICAgICAgICAgICAgICJsYXN0TW9kaWZ5"
    "aW5nVXNlcihkaXNwbGF5TmFtZSxlbWFpbEFkZHJlc3MpIgogICAgICAgICAgICAgICAgIikiCiAgICAgICAgICAgICksCiAgICAg"
    "ICAgKS5leGVjdXRlKCkKICAgICAgICBmaWxlcyA9IHJlc3BvbnNlLmdldCgiZmlsZXMiLCBbXSkKICAgICAgICBmb3IgaXRlbSBp"
    "biBmaWxlczoKICAgICAgICAgICAgbWltZSA9IChpdGVtLmdldCgibWltZVR5cGUiKSBvciAiIikuc3RyaXAoKQogICAgICAgICAg"
    "ICBpdGVtWyJpc19mb2xkZXIiXSA9IG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5mb2xkZXIiCiAgICAgICAg"
    "ICAgIGl0ZW1bImlzX2dvb2dsZV9kb2MiXSA9IG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5kb2N1bWVudCIK"
    "ICAgICAgICBzZWxmLl9sb2coZiJEcml2ZSBpdGVtcyByZXR1cm5lZDoge2xlbihmaWxlcyl9IGZvbGRlcl9pZD17c2FmZV9mb2xk"
    "ZXJfaWR9IiwgbGV2ZWw9IklORk8iKQogICAgICAgIHJldHVybiBmaWxlcwoKICAgIGRlZiBnZXRfZG9jX3ByZXZpZXcoc2VsZiwg"
    "ZG9jX2lkOiBzdHIsIG1heF9jaGFyczogaW50ID0gMTgwMCk6CiAgICAgICAgaWYgbm90IGRvY19pZDoKICAgICAgICAgICAgcmFp"
    "c2UgVmFsdWVFcnJvcigiRG9jdW1lbnQgaWQgaXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAg"
    "ICAgICAgZG9jID0gc2VsZi5fZG9jc19zZXJ2aWNlLmRvY3VtZW50cygpLmdldChkb2N1bWVudElkPWRvY19pZCkuZXhlY3V0ZSgp"
    "CiAgICAgICAgdGl0bGUgPSBkb2MuZ2V0KCJ0aXRsZSIpIG9yICJVbnRpdGxlZCIKICAgICAgICBib2R5ID0gZG9jLmdldCgiYm9k"
    "eSIsIHt9KS5nZXQoImNvbnRlbnQiLCBbXSkKICAgICAgICBjaHVua3MgPSBbXQogICAgICAgIGZvciBibG9jayBpbiBib2R5Ogog"
    "ICAgICAgICAgICBwYXJhZ3JhcGggPSBibG9jay5nZXQoInBhcmFncmFwaCIpCiAgICAgICAgICAgIGlmIG5vdCBwYXJhZ3JhcGg6"
    "CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBlbGVtZW50cyA9IHBhcmFncmFwaC5nZXQoImVsZW1lbnRzIiwg"
    "W10pCiAgICAgICAgICAgIGZvciBlbCBpbiBlbGVtZW50czoKICAgICAgICAgICAgICAgIHJ1biA9IGVsLmdldCgidGV4dFJ1biIp"
    "CiAgICAgICAgICAgICAgICBpZiBub3QgcnVuOgogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgICAgICB0"
    "ZXh0ID0gKHJ1bi5nZXQoImNvbnRlbnQiKSBvciAiIikucmVwbGFjZSgiXHgwYiIsICJcbiIpCiAgICAgICAgICAgICAgICBpZiB0"
    "ZXh0OgogICAgICAgICAgICAgICAgICAgIGNodW5rcy5hcHBlbmQodGV4dCkKICAgICAgICBwYXJzZWQgPSAiIi5qb2luKGNodW5r"
    "cykuc3RyaXAoKQogICAgICAgIGlmIGxlbihwYXJzZWQpID4gbWF4X2NoYXJzOgogICAgICAgICAgICBwYXJzZWQgPSBwYXJzZWRb"
    "Om1heF9jaGFyc10ucnN0cmlwKCkgKyAi4oCmIgogICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICJ0aXRsZSI6IHRpdGxlLAog"
    "ICAgICAgICAgICAiZG9jdW1lbnRfaWQiOiBkb2NfaWQsCiAgICAgICAgICAgICJyZXZpc2lvbl9pZCI6IGRvYy5nZXQoInJldmlz"
    "aW9uSWQiKSwKICAgICAgICAgICAgInByZXZpZXdfdGV4dCI6IHBhcnNlZCBvciAiW05vIHRleHQgY29udGVudCByZXR1cm5lZCBm"
    "cm9tIERvY3MgQVBJLl0iLAogICAgICAgIH0KCiAgICBkZWYgY3JlYXRlX2RvYyhzZWxmLCB0aXRsZTogc3RyID0gIk5ldyBHcmlt"
    "VmVpbGUgUmVjb3JkIiwgcGFyZW50X2ZvbGRlcl9pZDogc3RyID0gInJvb3QiKToKICAgICAgICBzYWZlX3RpdGxlID0gKHRpdGxl"
    "IG9yICJOZXcgR3JpbVZlaWxlIFJlY29yZCIpLnN0cmlwKCkgb3IgIk5ldyBHcmltVmVpbGUgUmVjb3JkIgogICAgICAgIHNlbGYu"
    "ZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBzYWZlX3BhcmVudF9pZCA9IChwYXJlbnRfZm9sZGVyX2lkIG9yICJyb290Iikuc3Ry"
    "aXAoKSBvciAicm9vdCIKICAgICAgICBjcmVhdGVkID0gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmNyZWF0ZSgKICAgICAg"
    "ICAgICAgYm9keT17CiAgICAgICAgICAgICAgICAibmFtZSI6IHNhZmVfdGl0bGUsCiAgICAgICAgICAgICAgICAibWltZVR5cGUi"
    "OiAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IiwKICAgICAgICAgICAgICAgICJwYXJlbnRzIjogW3NhZmVf"
    "cGFyZW50X2lkXSwKICAgICAgICAgICAgfSwKICAgICAgICAgICAgZmllbGRzPSJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVkVGlt"
    "ZSx3ZWJWaWV3TGluayxwYXJlbnRzIiwKICAgICAgICApLmV4ZWN1dGUoKQogICAgICAgIGRvY19pZCA9IGNyZWF0ZWQuZ2V0KCJp"
    "ZCIpCiAgICAgICAgbWV0YSA9IHNlbGYuZ2V0X2ZpbGVfbWV0YWRhdGEoZG9jX2lkKSBpZiBkb2NfaWQgZWxzZSB7fQogICAgICAg"
    "IHJldHVybiB7CiAgICAgICAgICAgICJpZCI6IGRvY19pZCwKICAgICAgICAgICAgIm5hbWUiOiBtZXRhLmdldCgibmFtZSIpIG9y"
    "IHNhZmVfdGl0bGUsCiAgICAgICAgICAgICJtaW1lVHlwZSI6IG1ldGEuZ2V0KCJtaW1lVHlwZSIpIG9yICJhcHBsaWNhdGlvbi92"
    "bmQuZ29vZ2xlLWFwcHMuZG9jdW1lbnQiLAogICAgICAgICAgICAibW9kaWZpZWRUaW1lIjogbWV0YS5nZXQoIm1vZGlmaWVkVGlt"
    "ZSIpLAogICAgICAgICAgICAid2ViVmlld0xpbmsiOiBtZXRhLmdldCgid2ViVmlld0xpbmsiKSwKICAgICAgICAgICAgInBhcmVu"
    "dHMiOiBtZXRhLmdldCgicGFyZW50cyIpIG9yIFtzYWZlX3BhcmVudF9pZF0sCiAgICAgICAgfQoKICAgIGRlZiBjcmVhdGVfZm9s"
    "ZGVyKHNlbGYsIG5hbWU6IHN0ciA9ICJOZXcgRm9sZGVyIiwgcGFyZW50X2ZvbGRlcl9pZDogc3RyID0gInJvb3QiKToKICAgICAg"
    "ICBzYWZlX25hbWUgPSAobmFtZSBvciAiTmV3IEZvbGRlciIpLnN0cmlwKCkgb3IgIk5ldyBGb2xkZXIiCiAgICAgICAgc2FmZV9w"
    "YXJlbnRfaWQgPSAocGFyZW50X2ZvbGRlcl9pZCBvciAicm9vdCIpLnN0cmlwKCkgb3IgInJvb3QiCiAgICAgICAgc2VsZi5lbnN1"
    "cmVfc2VydmljZXMoKQogICAgICAgIGNyZWF0ZWQgPSBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuY3JlYXRlKAogICAgICAg"
    "ICAgICBib2R5PXsKICAgICAgICAgICAgICAgICJuYW1lIjogc2FmZV9uYW1lLAogICAgICAgICAgICAgICAgIm1pbWVUeXBlIjog"
    "ImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5mb2xkZXIiLAogICAgICAgICAgICAgICAgInBhcmVudHMiOiBbc2FmZV9wYXJl"
    "bnRfaWRdLAogICAgICAgICAgICB9LAogICAgICAgICAgICBmaWVsZHM9ImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1lLHdl"
    "YlZpZXdMaW5rLHBhcmVudHMiLAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAgcmV0dXJuIGNyZWF0ZWQKCiAgICBkZWYgZ2V0"
    "X2ZpbGVfbWV0YWRhdGEoc2VsZiwgZmlsZV9pZDogc3RyKToKICAgICAgICBpZiBub3QgZmlsZV9pZDoKICAgICAgICAgICAgcmFp"
    "c2UgVmFsdWVFcnJvcigiRmlsZSBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAg"
    "ICByZXR1cm4gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmdldCgKICAgICAgICAgICAgZmlsZUlkPWZpbGVfaWQsCiAgICAg"
    "ICAgICAgIGZpZWxkcz0iaWQsbmFtZSxtaW1lVHlwZSxtb2RpZmllZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyxzaXplIiwKICAg"
    "ICAgICApLmV4ZWN1dGUoKQoKICAgIGRlZiBnZXRfZG9jX21ldGFkYXRhKHNlbGYsIGRvY19pZDogc3RyKToKICAgICAgICByZXR1"
    "cm4gc2VsZi5nZXRfZmlsZV9tZXRhZGF0YShkb2NfaWQpCgogICAgZGVmIGRlbGV0ZV9pdGVtKHNlbGYsIGZpbGVfaWQ6IHN0cik6"
    "CiAgICAgICAgaWYgbm90IGZpbGVfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkZpbGUgaWQgaXMgcmVxdWlyZWQu"
    "IikKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmRlbGV0"
    "ZShmaWxlSWQ9ZmlsZV9pZCkuZXhlY3V0ZSgpCgogICAgZGVmIGRlbGV0ZV9kb2Moc2VsZiwgZG9jX2lkOiBzdHIpOgogICAgICAg"
    "IHNlbGYuZGVsZXRlX2l0ZW0oZG9jX2lkKQoKICAgIGRlZiBleHBvcnRfZG9jX3RleHQoc2VsZiwgZG9jX2lkOiBzdHIpOgogICAg"
    "ICAgIGlmIG5vdCBkb2NfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkRvY3VtZW50IGlkIGlzIHJlcXVpcmVkLiIp"
    "CiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHBheWxvYWQgPSBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVz"
    "KCkuZXhwb3J0KAogICAgICAgICAgICBmaWxlSWQ9ZG9jX2lkLAogICAgICAgICAgICBtaW1lVHlwZT0idGV4dC9wbGFpbiIsCiAg"
    "ICAgICAgKS5leGVjdXRlKCkKICAgICAgICBpZiBpc2luc3RhbmNlKHBheWxvYWQsIGJ5dGVzKToKICAgICAgICAgICAgcmV0dXJu"
    "IHBheWxvYWQuZGVjb2RlKCJ1dGYtOCIsIGVycm9ycz0icmVwbGFjZSIpCiAgICAgICAgcmV0dXJuIHN0cihwYXlsb2FkIG9yICIi"
    "KQoKICAgIGRlZiBkb3dubG9hZF9maWxlX2J5dGVzKHNlbGYsIGZpbGVfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGZpbGVfaWQ6"
    "CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkZpbGUgaWQgaXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9z"
    "ZXJ2aWNlcygpCiAgICAgICAgcmV0dXJuIHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5nZXRfbWVkaWEoZmlsZUlkPWZpbGVf"
    "aWQpLmV4ZWN1dGUoKQoKCgoKIyDilIDilIAgUEFTUyAzIENPTVBMRVRFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEFs"
    "bCB3b3JrZXIgdGhyZWFkcyBkZWZpbmVkLiBBbGwgZ2VuZXJhdGlvbiBpcyBzdHJlYW1pbmcuCiMgTm8gYmxvY2tpbmcgY2FsbHMg"
    "b24gbWFpbiB0aHJlYWQgYW55d2hlcmUgaW4gdGhpcyBmaWxlLgojCiMgTmV4dDogUGFzcyA0IOKAlCBNZW1vcnkgJiBTdG9yYWdl"
    "CiMgKE1lbW9yeU1hbmFnZXIsIFNlc3Npb25NYW5hZ2VyLCBMZXNzb25zTGVhcm5lZERCLCBUYXNrTWFuYWdlcikKCgojIOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgNDogTUVNT1JZICYgU1RPUkFHRQojCiMgU3lzdGVtcyBkZWZpbmVkIGhl"
    "cmU6CiMgICBEZXBlbmRlbmN5Q2hlY2tlciAgIOKAlCB2YWxpZGF0ZXMgYWxsIHJlcXVpcmVkIHBhY2thZ2VzIG9uIHN0YXJ0dXAK"
    "IyAgIE1lbW9yeU1hbmFnZXIgICAgICAg4oCUIEpTT05MIG1lbW9yeSByZWFkL3dyaXRlL3NlYXJjaAojICAgU2Vzc2lvbk1hbmFn"
    "ZXIgICAgICDigJQgYXV0by1zYXZlLCBsb2FkLCBjb250ZXh0IGluamVjdGlvbiwgc2Vzc2lvbiBpbmRleAojICAgTGVzc29uc0xl"
    "YXJuZWREQiAgICDigJQgTFNMIEZvcmJpZGRlbiBSdWxlc2V0ICsgY29kZSBsZXNzb25zIGtub3dsZWRnZSBiYXNlCiMgICBUYXNr"
    "TWFuYWdlciAgICAgICAgIOKAlCB0YXNrL3JlbWluZGVyIENSVUQsIGR1ZS1ldmVudCBkZXRlY3Rpb24KIyDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAK"
    "CgojIOKUgOKUgCBERVBFTkRFTkNZIENIRUNLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIERlcGVuZGVuY3lDaGVja2VyOgog"
    "ICAgIiIiCiAgICBWYWxpZGF0ZXMgYWxsIHJlcXVpcmVkIGFuZCBvcHRpb25hbCBwYWNrYWdlcyBvbiBzdGFydHVwLgogICAgUmV0"
    "dXJucyBhIGxpc3Qgb2Ygc3RhdHVzIG1lc3NhZ2VzIGZvciB0aGUgRGlhZ25vc3RpY3MgdGFiLgogICAgU2hvd3MgYSBibG9ja2lu"
    "ZyBlcnJvciBkaWFsb2cgZm9yIGFueSBjcml0aWNhbCBtaXNzaW5nIGRlcGVuZGVuY3kuCiAgICAiIiIKCiAgICAjIChwYWNrYWdl"
    "X25hbWUsIGltcG9ydF9uYW1lLCBjcml0aWNhbCwgaW5zdGFsbF9oaW50KQogICAgUEFDS0FHRVMgPSBbCiAgICAgICAgKCJQeVNp"
    "ZGU2IiwgICAgICAgICAgICAgICAgICAgIlB5U2lkZTYiLCAgICAgICAgICAgICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0YWxs"
    "IFB5U2lkZTYiKSwKICAgICAgICAoImxvZ3VydSIsICAgICAgICAgICAgICAgICAgICAibG9ndXJ1IiwgICAgICAgICAgICAgICBU"
    "cnVlLAogICAgICAgICAicGlwIGluc3RhbGwgbG9ndXJ1IiksCiAgICAgICAgKCJhcHNjaGVkdWxlciIsICAgICAgICAgICAgICAg"
    "ImFwc2NoZWR1bGVyIiwgICAgICAgICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGFwc2NoZWR1bGVyIiksCiAgICAgICAg"
    "KCJweWdhbWUiLCAgICAgICAgICAgICAgICAgICAgInB5Z2FtZSIsICAgICAgICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAg"
    "aW5zdGFsbCBweWdhbWUgIChuZWVkZWQgZm9yIHNvdW5kKSIpLAogICAgICAgICgicHl3aW4zMiIsICAgICAgICAgICAgICAgICAg"
    "ICJ3aW4zMmNvbSIsICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcHl3aW4zMiAgKG5lZWRlZCBmb3Ig"
    "ZGVza3RvcCBzaG9ydGN1dCkiKSwKICAgICAgICAoInBzdXRpbCIsICAgICAgICAgICAgICAgICAgICAicHN1dGlsIiwgICAgICAg"
    "ICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBpbnN0YWxsIHBzdXRpbCAgKG5lZWRlZCBmb3Igc3lzdGVtIG1vbml0b3Jpbmcp"
    "IiksCiAgICAgICAgKCJyZXF1ZXN0cyIsICAgICAgICAgICAgICAgICAgInJlcXVlc3RzIiwgICAgICAgICAgICAgRmFsc2UsCiAg"
    "ICAgICAgICJwaXAgaW5zdGFsbCByZXF1ZXN0cyIpLAogICAgICAgICgiZ29vZ2xlLWFwaS1weXRob24tY2xpZW50IiwgICJnb29n"
    "bGVhcGljbGllbnQiLCAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgZ29vZ2xlLWFwaS1weXRob24tY2xpZW50Iiks"
    "CiAgICAgICAgKCJnb29nbGUtYXV0aC1vYXV0aGxpYiIsICAgICAgImdvb2dsZV9hdXRoX29hdXRobGliIiwgRmFsc2UsCiAgICAg"
    "ICAgICJwaXAgaW5zdGFsbCBnb29nbGUtYXV0aC1vYXV0aGxpYiIpLAogICAgICAgICgiZ29vZ2xlLWF1dGgiLCAgICAgICAgICAg"
    "ICAgICJnb29nbGUuYXV0aCIsICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgZ29vZ2xlLWF1dGgiKSwKICAg"
    "ICAgICAoInRvcmNoIiwgICAgICAgICAgICAgICAgICAgICAidG9yY2giLCAgICAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAg"
    "InBpcCBpbnN0YWxsIHRvcmNoICAob25seSBuZWVkZWQgZm9yIGxvY2FsIG1vZGVsKSIpLAogICAgICAgICgidHJhbnNmb3JtZXJz"
    "IiwgICAgICAgICAgICAgICJ0cmFuc2Zvcm1lcnMiLCAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgdHJhbnNm"
    "b3JtZXJzICAob25seSBuZWVkZWQgZm9yIGxvY2FsIG1vZGVsKSIpLAogICAgICAgICgicHludm1sIiwgICAgICAgICAgICAgICAg"
    "ICAgICJweW52bWwiLCAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcHludm1sICAob25seSBuZWVk"
    "ZWQgZm9yIE5WSURJQSBHUFUgbW9uaXRvcmluZykiKSwKICAgIF0KCiAgICBAY2xhc3NtZXRob2QKICAgIGRlZiBjaGVjayhjbHMp"
    "IC0+IHR1cGxlW2xpc3Rbc3RyXSwgbGlzdFtzdHJdXToKICAgICAgICAiIiIKICAgICAgICBSZXR1cm5zIChtZXNzYWdlcywgY3Jp"
    "dGljYWxfZmFpbHVyZXMpLgogICAgICAgIG1lc3NhZ2VzOiBsaXN0IG9mICJbREVQU10gcGFja2FnZSDinJMv4pyXIOKAlCBub3Rl"
    "IiBzdHJpbmdzCiAgICAgICAgY3JpdGljYWxfZmFpbHVyZXM6IGxpc3Qgb2YgcGFja2FnZXMgdGhhdCBhcmUgY3JpdGljYWwgYW5k"
    "IG1pc3NpbmcKICAgICAgICAiIiIKICAgICAgICBpbXBvcnQgaW1wb3J0bGliCiAgICAgICAgbWVzc2FnZXMgID0gW10KICAgICAg"
    "ICBjcml0aWNhbCAgPSBbXQoKICAgICAgICBmb3IgcGtnX25hbWUsIGltcG9ydF9uYW1lLCBpc19jcml0aWNhbCwgaGludCBpbiBj"
    "bHMuUEFDS0FHRVM6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9y"
    "dF9uYW1lKQogICAgICAgICAgICAgICAgbWVzc2FnZXMuYXBwZW5kKGYiW0RFUFNdIHtwa2dfbmFtZX0g4pyTIikKICAgICAgICAg"
    "ICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICAgICAgc3RhdHVzID0gIkNSSVRJQ0FMIiBpZiBpc19jcml0aWNhbCBl"
    "bHNlICJvcHRpb25hbCIKICAgICAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltERVBT"
    "XSB7cGtnX25hbWV9IOKclyAoe3N0YXR1c30pIOKAlCB7aGludH0iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBp"
    "ZiBpc19jcml0aWNhbDoKICAgICAgICAgICAgICAgICAgICBjcml0aWNhbC5hcHBlbmQocGtnX25hbWUpCgogICAgICAgIHJldHVy"
    "biBtZXNzYWdlcywgY3JpdGljYWwKCiAgICBAY2xhc3NtZXRob2QKICAgIGRlZiBjaGVja19vbGxhbWEoY2xzKSAtPiBzdHI6CiAg"
    "ICAgICAgIiIiQ2hlY2sgaWYgT2xsYW1hIGlzIHJ1bm5pbmcuIFJldHVybnMgc3RhdHVzIHN0cmluZy4iIiIKICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgIHJlcSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KCJodHRwOi8vbG9jYWxob3N0OjExNDM0L2FwaS90YWdz"
    "IikKICAgICAgICAgICAgcmVzcCA9IHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTIpCiAgICAgICAgICAgIGlm"
    "IHJlc3Auc3RhdHVzID09IDIwMDoKICAgICAgICAgICAgICAgIHJldHVybiAiW0RFUFNdIE9sbGFtYSDinJMg4oCUIHJ1bm5pbmcg"
    "b24gbG9jYWxob3N0OjExNDM0IgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKICAgICAgICByZXR1"
    "cm4gIltERVBTXSBPbGxhbWEg4pyXIOKAlCBub3QgcnVubmluZyAob25seSBuZWVkZWQgZm9yIE9sbGFtYSBtb2RlbCB0eXBlKSIK"
    "CgojIOKUgOKUgCBNRU1PUlkgTUFOQUdFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTWVtb3J5TWFuYWdl"
    "cjoKICAgICIiIgogICAgSGFuZGxlcyBhbGwgSlNPTkwgbWVtb3J5IG9wZXJhdGlvbnMuCgogICAgRmlsZXMgbWFuYWdlZDoKICAg"
    "ICAgICBtZW1vcmllcy9tZXNzYWdlcy5qc29ubCAgICAgICAgIOKAlCBldmVyeSBtZXNzYWdlLCB0aW1lc3RhbXBlZAogICAgICAg"
    "IG1lbW9yaWVzL21lbW9yaWVzLmpzb25sICAgICAgICAg4oCUIGV4dHJhY3RlZCBtZW1vcnkgcmVjb3JkcwogICAgICAgIG1lbW9y"
    "aWVzL3N0YXRlLmpzb24gICAgICAgICAgICAg4oCUIGVudGl0eSBzdGF0ZQogICAgICAgIG1lbW9yaWVzL2luZGV4Lmpzb24gICAg"
    "ICAgICAgICAg4oCUIGNvdW50cyBhbmQgbWV0YWRhdGEKCiAgICBNZW1vcnkgcmVjb3JkcyBoYXZlIHR5cGUgaW5mZXJlbmNlLCBr"
    "ZXl3b3JkIGV4dHJhY3Rpb24sIHRhZyBnZW5lcmF0aW9uLAogICAgbmVhci1kdXBsaWNhdGUgZGV0ZWN0aW9uLCBhbmQgcmVsZXZh"
    "bmNlIHNjb3JpbmcgZm9yIGNvbnRleHQgaW5qZWN0aW9uLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAg"
    "IGJhc2UgICAgICAgICAgICAgPSBjZmdfcGF0aCgibWVtb3JpZXMiKQogICAgICAgIHNlbGYubWVzc2FnZXNfcCAgPSBiYXNlIC8g"
    "Im1lc3NhZ2VzLmpzb25sIgogICAgICAgIHNlbGYubWVtb3JpZXNfcCAgPSBiYXNlIC8gIm1lbW9yaWVzLmpzb25sIgogICAgICAg"
    "IHNlbGYuc3RhdGVfcCAgICAgPSBiYXNlIC8gInN0YXRlLmpzb24iCiAgICAgICAgc2VsZi5pbmRleF9wICAgICA9IGJhc2UgLyAi"
    "aW5kZXguanNvbiIKCiAgICAjIOKUgOKUgCBTVEFURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBsb2FkX3N0YXRl"
    "KHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgaWYgbm90IHNlbGYuc3RhdGVfcC5leGlzdHMoKToKICAgICAgICAgICAgcmV0dXJuIHNl"
    "bGYuX2RlZmF1bHRfc3RhdGUoKQogICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIGpzb24ubG9hZHMoc2VsZi5zdGF0ZV9w"
    "LnJlYWRfdGV4dChlbmNvZGluZz0idXRmLTgiKSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4g"
    "c2VsZi5fZGVmYXVsdF9zdGF0ZSgpCgogICAgZGVmIHNhdmVfc3RhdGUoc2VsZiwgc3RhdGU6IGRpY3QpIC0+IE5vbmU6CiAgICAg"
    "ICAgc2VsZi5zdGF0ZV9wLndyaXRlX3RleHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoc3RhdGUsIGluZGVudD0yKSwgZW5jb2Rp"
    "bmc9InV0Zi04IgogICAgICAgICkKCiAgICBkZWYgX2RlZmF1bHRfc3RhdGUoc2VsZikgLT4gZGljdDoKICAgICAgICByZXR1cm4g"
    "ewogICAgICAgICAgICAicGVyc29uYV9uYW1lIjogICAgICAgICAgICAgREVDS19OQU1FLAogICAgICAgICAgICAiZGVja192ZXJz"
    "aW9uIjogICAgICAgICAgICAgQVBQX1ZFUlNJT04sCiAgICAgICAgICAgICJzZXNzaW9uX2NvdW50IjogICAgICAgICAgICAwLAog"
    "ICAgICAgICAgICAibGFzdF9zdGFydHVwIjogICAgICAgICAgICAgTm9uZSwKICAgICAgICAgICAgImxhc3Rfc2h1dGRvd24iOiAg"
    "ICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgICJsYXN0X2FjdGl2ZSI6ICAgICAgICAgICAgICBOb25lLAogICAgICAgICAgICAi"
    "dG90YWxfbWVzc2FnZXMiOiAgICAgICAgICAgMCwKICAgICAgICAgICAgInRvdGFsX21lbW9yaWVzIjogICAgICAgICAgIDAsCiAg"
    "ICAgICAgICAgICJpbnRlcm5hbF9uYXJyYXRpdmUiOiAgICAgICB7fSwKICAgICAgICAgICAgInZhbXBpcmVfc3RhdGVfYXRfc2h1"
    "dGRvd24iOiJET1JNQU5UIiwKICAgICAgICB9CgogICAgIyDilIDilIAgTUVTU0FHRVMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYg"
    "YXBwZW5kX21lc3NhZ2Uoc2VsZiwgc2Vzc2lvbl9pZDogc3RyLCByb2xlOiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICAgY29u"
    "dGVudDogc3RyLCBlbW90aW9uOiBzdHIgPSAiIikgLT4gZGljdDoKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6"
    "ICAgICAgICAgZiJtc2dfe3V1aWQudXVpZDQoKS5oZXhbOjEyXX0iLAogICAgICAgICAgICAidGltZXN0YW1wIjogIGxvY2FsX25v"
    "d19pc28oKSwKICAgICAgICAgICAgInNlc3Npb25faWQiOiBzZXNzaW9uX2lkLAogICAgICAgICAgICAicGVyc29uYSI6ICAgIERF"
    "Q0tfTkFNRSwKICAgICAgICAgICAgInJvbGUiOiAgICAgICByb2xlLAogICAgICAgICAgICAiY29udGVudCI6ICAgIGNvbnRlbnQs"
    "CiAgICAgICAgICAgICJlbW90aW9uIjogICAgZW1vdGlvbiwKICAgICAgICB9CiAgICAgICAgYXBwZW5kX2pzb25sKHNlbGYubWVz"
    "c2FnZXNfcCwgcmVjb3JkKQogICAgICAgIHJldHVybiByZWNvcmQKCiAgICBkZWYgbG9hZF9yZWNlbnRfbWVzc2FnZXMoc2VsZiwg"
    "bGltaXQ6IGludCA9IDIwKSAtPiBsaXN0W2RpY3RdOgogICAgICAgIHJldHVybiByZWFkX2pzb25sKHNlbGYubWVzc2FnZXNfcClb"
    "LWxpbWl0Ol0KCiAgICAjIOKUgOKUgCBNRU1PUklFUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBhcHBlbmRfbWVtb3J5KHNlbGYs"
    "IHNlc3Npb25faWQ6IHN0ciwgdXNlcl90ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICBhc3Npc3RhbnRfdGV4dDogc3Ry"
    "KSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICByZWNvcmRfdHlwZSA9IGluZmVyX3JlY29yZF90eXBlKHVzZXJfdGV4dCwgYXNz"
    "aXN0YW50X3RleHQpCiAgICAgICAga2V5d29yZHMgICAgPSBleHRyYWN0X2tleXdvcmRzKHVzZXJfdGV4dCArICIgIiArIGFzc2lz"
    "dGFudF90ZXh0KQogICAgICAgIHRhZ3MgICAgICAgID0gc2VsZi5faW5mZXJfdGFncyhyZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBr"
    "ZXl3b3JkcykKICAgICAgICB0aXRsZSAgICAgICA9IHNlbGYuX2luZmVyX3RpdGxlKHJlY29yZF90eXBlLCB1c2VyX3RleHQsIGtl"
    "eXdvcmRzKQogICAgICAgIHN1bW1hcnkgICAgID0gc2VsZi5fc3VtbWFyaXplKHJlY29yZF90eXBlLCB1c2VyX3RleHQsIGFzc2lz"
    "dGFudF90ZXh0KQoKICAgICAgICBtZW1vcnkgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgICAgICAgZiJtZW1fe3V1aWQu"
    "dXVpZDQoKS5oZXhbOjEyXX0iLAogICAgICAgICAgICAidGltZXN0YW1wIjogICAgICAgIGxvY2FsX25vd19pc28oKSwKICAgICAg"
    "ICAgICAgInNlc3Npb25faWQiOiAgICAgICBzZXNzaW9uX2lkLAogICAgICAgICAgICAicGVyc29uYSI6ICAgICAgICAgIERFQ0tf"
    "TkFNRSwKICAgICAgICAgICAgInR5cGUiOiAgICAgICAgICAgICByZWNvcmRfdHlwZSwKICAgICAgICAgICAgInRpdGxlIjogICAg"
    "ICAgICAgICB0aXRsZSwKICAgICAgICAgICAgInN1bW1hcnkiOiAgICAgICAgICBzdW1tYXJ5LAogICAgICAgICAgICAiY29udGVu"
    "dCI6ICAgICAgICAgIHVzZXJfdGV4dFs6NDAwMF0sCiAgICAgICAgICAgICJhc3Npc3RhbnRfY29udGV4dCI6YXNzaXN0YW50X3Rl"
    "eHRbOjEyMDBdLAogICAgICAgICAgICAia2V5d29yZHMiOiAgICAgICAgIGtleXdvcmRzLAogICAgICAgICAgICAidGFncyI6ICAg"
    "ICAgICAgICAgIHRhZ3MsCiAgICAgICAgICAgICJjb25maWRlbmNlIjogICAgICAgMC43MCBpZiByZWNvcmRfdHlwZSBpbiB7CiAg"
    "ICAgICAgICAgICAgICAiZHJlYW0iLCJpc3N1ZSIsImlkZWEiLCJwcmVmZXJlbmNlIiwicmVzb2x1dGlvbiIKICAgICAgICAgICAg"
    "fSBlbHNlIDAuNTUsCiAgICAgICAgfQoKICAgICAgICBpZiBzZWxmLl9pc19uZWFyX2R1cGxpY2F0ZShtZW1vcnkpOgogICAgICAg"
    "ICAgICByZXR1cm4gTm9uZQoKICAgICAgICBhcHBlbmRfanNvbmwoc2VsZi5tZW1vcmllc19wLCBtZW1vcnkpCiAgICAgICAgcmV0"
    "dXJuIG1lbW9yeQoKICAgIGRlZiBzZWFyY2hfbWVtb3JpZXMoc2VsZiwgcXVlcnk6IHN0ciwgbGltaXQ6IGludCA9IDYpIC0+IGxp"
    "c3RbZGljdF06CiAgICAgICAgIiIiCiAgICAgICAgS2V5d29yZC1zY29yZWQgbWVtb3J5IHNlYXJjaC4KICAgICAgICBSZXR1cm5z"
    "IHVwIHRvIGBsaW1pdGAgcmVjb3JkcyBzb3J0ZWQgYnkgcmVsZXZhbmNlIHNjb3JlIGRlc2NlbmRpbmcuCiAgICAgICAgRmFsbHMg"
    "YmFjayB0byBtb3N0IHJlY2VudCBpZiBubyBxdWVyeSB0ZXJtcyBtYXRjaC4KICAgICAgICAiIiIKICAgICAgICBtZW1vcmllcyA9"
    "IHJlYWRfanNvbmwoc2VsZi5tZW1vcmllc19wKQogICAgICAgIGlmIG5vdCBxdWVyeS5zdHJpcCgpOgogICAgICAgICAgICByZXR1"
    "cm4gbWVtb3JpZXNbLWxpbWl0Ol0KCiAgICAgICAgcV90ZXJtcyA9IHNldChleHRyYWN0X2tleXdvcmRzKHF1ZXJ5LCBsaW1pdD0x"
    "NikpCiAgICAgICAgc2NvcmVkICA9IFtdCgogICAgICAgIGZvciBpdGVtIGluIG1lbW9yaWVzOgogICAgICAgICAgICBpdGVtX3Rl"
    "cm1zID0gc2V0KGV4dHJhY3Rfa2V5d29yZHMoIiAiLmpvaW4oWwogICAgICAgICAgICAgICAgaXRlbS5nZXQoInRpdGxlIiwgICAi"
    "IiksCiAgICAgICAgICAgICAgICBpdGVtLmdldCgic3VtbWFyeSIsICIiKSwKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0KCJjb250"
    "ZW50IiwgIiIpLAogICAgICAgICAgICAgICAgIiAiLmpvaW4oaXRlbS5nZXQoImtleXdvcmRzIiwgW10pKSwKICAgICAgICAgICAg"
    "ICAgICIgIi5qb2luKGl0ZW0uZ2V0KCJ0YWdzIiwgICAgIFtdKSksCiAgICAgICAgICAgIF0pLCBsaW1pdD00MCkpCgogICAgICAg"
    "ICAgICBzY29yZSA9IGxlbihxX3Rlcm1zICYgaXRlbV90ZXJtcykKCiAgICAgICAgICAgICMgQm9vc3QgYnkgdHlwZSBtYXRjaAog"
    "ICAgICAgICAgICBxbCA9IHF1ZXJ5Lmxvd2VyKCkKICAgICAgICAgICAgcnQgPSBpdGVtLmdldCgidHlwZSIsICIiKQogICAgICAg"
    "ICAgICBpZiAiZHJlYW0iICBpbiBxbCBhbmQgcnQgPT0gImRyZWFtIjogICAgc2NvcmUgKz0gNAogICAgICAgICAgICBpZiAidGFz"
    "ayIgICBpbiBxbCBhbmQgcnQgPT0gInRhc2siOiAgICAgc2NvcmUgKz0gMwogICAgICAgICAgICBpZiAiaWRlYSIgICBpbiBxbCBh"
    "bmQgcnQgPT0gImlkZWEiOiAgICAgc2NvcmUgKz0gMgogICAgICAgICAgICBpZiAibHNsIiAgICBpbiBxbCBhbmQgcnQgaW4geyJp"
    "c3N1ZSIsInJlc29sdXRpb24ifTogc2NvcmUgKz0gMgoKICAgICAgICAgICAgaWYgc2NvcmUgPiAwOgogICAgICAgICAgICAgICAg"
    "c2NvcmVkLmFwcGVuZCgoc2NvcmUsIGl0ZW0pKQoKICAgICAgICBzY29yZWQuc29ydChrZXk9bGFtYmRhIHg6ICh4WzBdLCB4WzFd"
    "LmdldCgidGltZXN0YW1wIiwgIiIpKSwKICAgICAgICAgICAgICAgICAgICByZXZlcnNlPVRydWUpCiAgICAgICAgcmV0dXJuIFtp"
    "dGVtIGZvciBfLCBpdGVtIGluIHNjb3JlZFs6bGltaXRdXQoKICAgIGRlZiBidWlsZF9jb250ZXh0X2Jsb2NrKHNlbGYsIHF1ZXJ5"
    "OiBzdHIsIG1heF9jaGFyczogaW50ID0gMjAwMCkgLT4gc3RyOgogICAgICAgICIiIgogICAgICAgIEJ1aWxkIGEgY29udGV4dCBz"
    "dHJpbmcgZnJvbSByZWxldmFudCBtZW1vcmllcyBmb3IgcHJvbXB0IGluamVjdGlvbi4KICAgICAgICBUcnVuY2F0ZXMgdG8gbWF4"
    "X2NoYXJzIHRvIHByb3RlY3QgdGhlIGNvbnRleHQgd2luZG93LgogICAgICAgICIiIgogICAgICAgIG1lbW9yaWVzID0gc2VsZi5z"
    "ZWFyY2hfbWVtb3JpZXMocXVlcnksIGxpbWl0PTQpCiAgICAgICAgaWYgbm90IG1lbW9yaWVzOgogICAgICAgICAgICByZXR1cm4g"
    "IiIKCiAgICAgICAgcGFydHMgPSBbIltSRUxFVkFOVCBNRU1PUklFU10iXQogICAgICAgIHRvdGFsID0gMAogICAgICAgIGZvciBt"
    "IGluIG1lbW9yaWVzOgogICAgICAgICAgICBlbnRyeSA9ICgKICAgICAgICAgICAgICAgIGYi4oCiIFt7bS5nZXQoJ3R5cGUnLCcn"
    "KS51cHBlcigpfV0ge20uZ2V0KCd0aXRsZScsJycpfTogIgogICAgICAgICAgICAgICAgZiJ7bS5nZXQoJ3N1bW1hcnknLCcnKX0i"
    "CiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgdG90YWwgKyBsZW4oZW50cnkpID4gbWF4X2NoYXJzOgogICAgICAgICAgICAg"
    "ICAgYnJlYWsKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGVudHJ5KQogICAgICAgICAgICB0b3RhbCArPSBsZW4oZW50cnkpCgog"
    "ICAgICAgIHBhcnRzLmFwcGVuZCgiW0VORCBNRU1PUklFU10iKQogICAgICAgIHJldHVybiAiXG4iLmpvaW4ocGFydHMpCgogICAg"
    "IyDilIDilIAgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfaXNfbmVhcl9kdXBsaWNhdGUoc2VsZiwgY2FuZGlk"
    "YXRlOiBkaWN0KSAtPiBib29sOgogICAgICAgIHJlY2VudCA9IHJlYWRfanNvbmwoc2VsZi5tZW1vcmllc19wKVstMjU6XQogICAg"
    "ICAgIGN0ID0gY2FuZGlkYXRlLmdldCgidGl0bGUiLCAiIikubG93ZXIoKS5zdHJpcCgpCiAgICAgICAgY3MgPSBjYW5kaWRhdGUu"
    "Z2V0KCJzdW1tYXJ5IiwgIiIpLmxvd2VyKCkuc3RyaXAoKQogICAgICAgIGZvciBpdGVtIGluIHJlY2VudDoKICAgICAgICAgICAg"
    "aWYgaXRlbS5nZXQoInRpdGxlIiwiIikubG93ZXIoKS5zdHJpcCgpID09IGN0OiAgcmV0dXJuIFRydWUKICAgICAgICAgICAgaWYg"
    "aXRlbS5nZXQoInN1bW1hcnkiLCIiKS5sb3dlcigpLnN0cmlwKCkgPT0gY3M6IHJldHVybiBUcnVlCiAgICAgICAgcmV0dXJuIEZh"
    "bHNlCgogICAgZGVmIF9pbmZlcl90YWdzKHNlbGYsIHJlY29yZF90eXBlOiBzdHIsIHRleHQ6IHN0ciwKICAgICAgICAgICAgICAg"
    "ICAgICBrZXl3b3JkczogbGlzdFtzdHJdKSAtPiBsaXN0W3N0cl06CiAgICAgICAgdCAgICA9IHRleHQubG93ZXIoKQogICAgICAg"
    "IHRhZ3MgPSBbcmVjb3JkX3R5cGVdCiAgICAgICAgaWYgImRyZWFtIiAgIGluIHQ6IHRhZ3MuYXBwZW5kKCJkcmVhbSIpCiAgICAg"
    "ICAgaWYgImxzbCIgICAgIGluIHQ6IHRhZ3MuYXBwZW5kKCJsc2wiKQogICAgICAgIGlmICJweXRob24iICBpbiB0OiB0YWdzLmFw"
    "cGVuZCgicHl0aG9uIikKICAgICAgICBpZiAiZ2FtZSIgICAgaW4gdDogdGFncy5hcHBlbmQoImdhbWVfaWRlYSIpCiAgICAgICAg"
    "aWYgInNsIiAgICAgIGluIHQgb3IgInNlY29uZCBsaWZlIiBpbiB0OiB0YWdzLmFwcGVuZCgic2Vjb25kbGlmZSIpCiAgICAgICAg"
    "aWYgREVDS19OQU1FLmxvd2VyKCkgaW4gdDogdGFncy5hcHBlbmQoREVDS19OQU1FLmxvd2VyKCkpCiAgICAgICAgZm9yIGt3IGlu"
    "IGtleXdvcmRzWzo0XToKICAgICAgICAgICAgaWYga3cgbm90IGluIHRhZ3M6CiAgICAgICAgICAgICAgICB0YWdzLmFwcGVuZChr"
    "dykKICAgICAgICAjIERlZHVwbGljYXRlIHByZXNlcnZpbmcgb3JkZXIKICAgICAgICBzZWVuLCBvdXQgPSBzZXQoKSwgW10KICAg"
    "ICAgICBmb3IgdGFnIGluIHRhZ3M6CiAgICAgICAgICAgIGlmIHRhZyBub3QgaW4gc2VlbjoKICAgICAgICAgICAgICAgIHNlZW4u"
    "YWRkKHRhZykKICAgICAgICAgICAgICAgIG91dC5hcHBlbmQodGFnKQogICAgICAgIHJldHVybiBvdXRbOjEyXQoKICAgIGRlZiBf"
    "aW5mZXJfdGl0bGUoc2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwgdXNlcl90ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICAgIGtl"
    "eXdvcmRzOiBsaXN0W3N0cl0pIC0+IHN0cjoKICAgICAgICBkZWYgY2xlYW4od29yZHMpOgogICAgICAgICAgICByZXR1cm4gW3cu"
    "c3RyaXAoIiAtXy4sIT8iKS5jYXBpdGFsaXplKCkKICAgICAgICAgICAgICAgICAgICBmb3IgdyBpbiB3b3JkcyBpZiBsZW4odykg"
    "PiAyXQoKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAidGFzayI6CiAgICAgICAgICAgIGltcG9ydCByZQogICAgICAgICAgICBt"
    "ID0gcmUuc2VhcmNoKHIicmVtaW5kIG1lIC4qPyB0byAoLispIiwgdXNlcl90ZXh0LCByZS5JKQogICAgICAgICAgICBpZiBtOgog"
    "ICAgICAgICAgICAgICAgcmV0dXJuIGYiUmVtaW5kZXI6IHttLmdyb3VwKDEpLnN0cmlwKClbOjYwXX0iCiAgICAgICAgICAgIHJl"
    "dHVybiAiUmVtaW5kZXIgVGFzayIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAiZHJlYW0iOgogICAgICAgICAgICByZXR1cm4g"
    "ZiJ7JyAnLmpvaW4oY2xlYW4oa2V5d29yZHNbOjNdKSl9IERyZWFtIi5zdHJpcCgpIG9yICJEcmVhbSBNZW1vcnkiCiAgICAgICAg"
    "aWYgcmVjb3JkX3R5cGUgPT0gImlzc3VlIjoKICAgICAgICAgICAgcmV0dXJuIGYiSXNzdWU6IHsnICcuam9pbihjbGVhbihrZXl3"
    "b3Jkc1s6NF0pKX0iLnN0cmlwKCkgb3IgIlRlY2huaWNhbCBJc3N1ZSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAicmVzb2x1"
    "dGlvbiI6CiAgICAgICAgICAgIHJldHVybiBmIlJlc29sdXRpb246IHsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0pKX0iLnN0"
    "cmlwKCkgb3IgIlRlY2huaWNhbCBSZXNvbHV0aW9uIgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpZGVhIjoKICAgICAgICAg"
    "ICAgcmV0dXJuIGYiSWRlYTogeycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzo0XSkpfSIuc3RyaXAoKSBvciAiSWRlYSIKICAgICAg"
    "ICBpZiBrZXl3b3JkczoKICAgICAgICAgICAgcmV0dXJuICIgIi5qb2luKGNsZWFuKGtleXdvcmRzWzo1XSkpIG9yICJDb252ZXJz"
    "YXRpb24gTWVtb3J5IgogICAgICAgIHJldHVybiAiQ29udmVyc2F0aW9uIE1lbW9yeSIKCiAgICBkZWYgX3N1bW1hcml6ZShzZWxm"
    "LCByZWNvcmRfdHlwZTogc3RyLCB1c2VyX3RleHQ6IHN0ciwKICAgICAgICAgICAgICAgICAgIGFzc2lzdGFudF90ZXh0OiBzdHIp"
    "IC0+IHN0cjoKICAgICAgICB1ID0gdXNlcl90ZXh0LnN0cmlwKClbOjIyMF0KICAgICAgICBhID0gYXNzaXN0YW50X3RleHQuc3Ry"
    "aXAoKVs6MjIwXQogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJkcmVhbSI6ICAgICAgIHJldHVybiBmIlVzZXIgZGVzY3JpYmVk"
    "IGEgZHJlYW06IHt1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAidGFzayI6ICAgICAgICByZXR1cm4gZiJSZW1pbmRlci90"
    "YXNrOiB7dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gImlzc3VlIjogICAgICAgcmV0dXJuIGYiVGVjaG5pY2FsIGlzc3Vl"
    "OiB7dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInJlc29sdXRpb24iOiAgcmV0dXJuIGYiU29sdXRpb24gcmVjb3JkZWQ6"
    "IHthIG9yIHV9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpZGVhIjogICAgICAgIHJldHVybiBmIklkZWEgZGlzY3Vzc2Vk"
    "OiB7dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInByZWZlcmVuY2UiOiAgcmV0dXJuIGYiUHJlZmVyZW5jZSBub3RlZDog"
    "e3V9IgogICAgICAgIHJldHVybiBmIkNvbnZlcnNhdGlvbjoge3V9IgoKCiMg4pSA4pSAIFNFU1NJT04gTUFOQUdFUiDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU2Vzc2lvbk1hbmFnZXI6CiAgICAiIiIKICAgIE1hbmFnZXMgY29udmVyc2F0aW9u"
    "IHNlc3Npb25zLgoKICAgIEF1dG8tc2F2ZTogZXZlcnkgMTAgbWludXRlcyAoQVBTY2hlZHVsZXIpLCBtaWRuaWdodC10by1taWRu"
    "aWdodCBib3VuZGFyeS4KICAgIEZpbGU6IHNlc3Npb25zL1lZWVktTU0tREQuanNvbmwg4oCUIG92ZXJ3cml0ZXMgb24gZWFjaCBz"
    "YXZlLgogICAgSW5kZXg6IHNlc3Npb25zL3Nlc3Npb25faW5kZXguanNvbiDigJQgb25lIGVudHJ5IHBlciBkYXkuCgogICAgU2Vz"
    "c2lvbnMgYXJlIGxvYWRlZCBhcyBjb250ZXh0IGluamVjdGlvbiAobm90IHJlYWwgbWVtb3J5KSB1bnRpbAogICAgdGhlIFNRTGl0"
    "ZS9DaHJvbWFEQiBzeXN0ZW0gaXMgYnVpbHQgaW4gUGhhc2UgMi4KICAgICIiIgoKICAgIEFVVE9TQVZFX0lOVEVSVkFMID0gMTAg"
    "ICAjIG1pbnV0ZXMKCiAgICBkZWYgX19pbml0X18oc2VsZik6CiAgICAgICAgc2VsZi5fc2Vzc2lvbnNfZGlyICA9IGNmZ19wYXRo"
    "KCJzZXNzaW9ucyIpCiAgICAgICAgc2VsZi5faW5kZXhfcGF0aCAgICA9IHNlbGYuX3Nlc3Npb25zX2RpciAvICJzZXNzaW9uX2lu"
    "ZGV4Lmpzb24iCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9pZCAgICA9IGYic2Vzc2lvbl97ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUo"
    "JyVZJW0lZF8lSCVNJVMnKX0iCiAgICAgICAgc2VsZi5fY3VycmVudF9kYXRlICA9IGRhdGUudG9kYXkoKS5pc29mb3JtYXQoKQog"
    "ICAgICAgIHNlbGYuX21lc3NhZ2VzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9sb2FkZWRfam91cm5hbDogT3B0aW9u"
    "YWxbc3RyXSA9IE5vbmUgICMgZGF0ZSBvZiBsb2FkZWQgam91cm5hbAoKICAgICMg4pSA4pSAIENVUlJFTlQgU0VTU0lPTiDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBh"
    "ZGRfbWVzc2FnZShzZWxmLCByb2xlOiBzdHIsIGNvbnRlbnQ6IHN0ciwKICAgICAgICAgICAgICAgICAgICBlbW90aW9uOiBzdHIg"
    "PSAiIiwgdGltZXN0YW1wOiBzdHIgPSAiIikgLT4gTm9uZToKICAgICAgICBzZWxmLl9tZXNzYWdlcy5hcHBlbmQoewogICAgICAg"
    "ICAgICAiaWQiOiAgICAgICAgZiJtc2dfe3V1aWQudXVpZDQoKS5oZXhbOjhdfSIsCiAgICAgICAgICAgICJ0aW1lc3RhbXAiOiB0"
    "aW1lc3RhbXAgb3IgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAicm9sZSI6ICAgICAgcm9sZSwKICAgICAgICAgICAgImNv"
    "bnRlbnQiOiAgIGNvbnRlbnQsCiAgICAgICAgICAgICJlbW90aW9uIjogICBlbW90aW9uLAogICAgICAgIH0pCgogICAgZGVmIGdl"
    "dF9oaXN0b3J5KHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgIiIiCiAgICAgICAgUmV0dXJuIGhpc3RvcnkgaW4gTExNLWZy"
    "aWVuZGx5IGZvcm1hdC4KICAgICAgICBbeyJyb2xlIjogInVzZXIifCJhc3Npc3RhbnQiLCAiY29udGVudCI6ICIuLi4ifV0KICAg"
    "ICAgICAiIiIKICAgICAgICByZXR1cm4gWwogICAgICAgICAgICB7InJvbGUiOiBtWyJyb2xlIl0sICJjb250ZW50IjogbVsiY29u"
    "dGVudCJdfQogICAgICAgICAgICBmb3IgbSBpbiBzZWxmLl9tZXNzYWdlcwogICAgICAgICAgICBpZiBtWyJyb2xlIl0gaW4gKCJ1"
    "c2VyIiwgImFzc2lzdGFudCIpCiAgICAgICAgXQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIHNlc3Npb25faWQoc2VsZikgLT4gc3Ry"
    "OgogICAgICAgIHJldHVybiBzZWxmLl9zZXNzaW9uX2lkCgogICAgQHByb3BlcnR5CiAgICBkZWYgbWVzc2FnZV9jb3VudChzZWxm"
    "KSAtPiBpbnQ6CiAgICAgICAgcmV0dXJuIGxlbihzZWxmLl9tZXNzYWdlcykKCiAgICAjIOKUgOKUgCBTQVZFIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIHNhdmUoc2VsZiwgYWlfZ2VuZXJhdGVkX25hbWU6IHN0ciA9ICIiKSAtPiBOb25lOgog"
    "ICAgICAgICIiIgogICAgICAgIFNhdmUgY3VycmVudCBzZXNzaW9uIHRvIHNlc3Npb25zL1lZWVktTU0tREQuanNvbmwuCiAgICAg"
    "ICAgT3ZlcndyaXRlcyB0aGUgZmlsZSBmb3IgdG9kYXkg4oCUIGVhY2ggc2F2ZSBpcyBhIGZ1bGwgc25hcHNob3QuCiAgICAgICAg"
    "VXBkYXRlcyBzZXNzaW9uX2luZGV4Lmpzb24uCiAgICAgICAgIiIiCiAgICAgICAgdG9kYXkgPSBkYXRlLnRvZGF5KCkuaXNvZm9y"
    "bWF0KCkKICAgICAgICBvdXRfcGF0aCA9IHNlbGYuX3Nlc3Npb25zX2RpciAvIGYie3RvZGF5fS5qc29ubCIKCiAgICAgICAgIyBX"
    "cml0ZSBhbGwgbWVzc2FnZXMKICAgICAgICB3cml0ZV9qc29ubChvdXRfcGF0aCwgc2VsZi5fbWVzc2FnZXMpCgogICAgICAgICMg"
    "VXBkYXRlIGluZGV4CiAgICAgICAgaW5kZXggPSBzZWxmLl9sb2FkX2luZGV4KCkKICAgICAgICBleGlzdGluZyA9IG5leHQoCiAg"
    "ICAgICAgICAgIChzIGZvciBzIGluIGluZGV4WyJzZXNzaW9ucyJdIGlmIHNbImRhdGUiXSA9PSB0b2RheSksIE5vbmUKICAgICAg"
    "ICApCgogICAgICAgIG5hbWUgPSBhaV9nZW5lcmF0ZWRfbmFtZSBvciBleGlzdGluZy5nZXQoIm5hbWUiLCAiIikgaWYgZXhpc3Rp"
    "bmcgZWxzZSAiIgogICAgICAgIGlmIG5vdCBuYW1lIGFuZCBzZWxmLl9tZXNzYWdlczoKICAgICAgICAgICAgIyBBdXRvLW5hbWUg"
    "ZnJvbSBmaXJzdCB1c2VyIG1lc3NhZ2UgKGZpcnN0IDUgd29yZHMpCiAgICAgICAgICAgIGZpcnN0X3VzZXIgPSBuZXh0KAogICAg"
    "ICAgICAgICAgICAgKG1bImNvbnRlbnQiXSBmb3IgbSBpbiBzZWxmLl9tZXNzYWdlcyBpZiBtWyJyb2xlIl0gPT0gInVzZXIiKSwK"
    "ICAgICAgICAgICAgICAgICIiCiAgICAgICAgICAgICkKICAgICAgICAgICAgd29yZHMgPSBmaXJzdF91c2VyLnNwbGl0KClbOjVd"
    "CiAgICAgICAgICAgIG5hbWUgID0gIiAiLmpvaW4od29yZHMpIGlmIHdvcmRzIGVsc2UgZiJTZXNzaW9uIHt0b2RheX0iCgogICAg"
    "ICAgIGVudHJ5ID0gewogICAgICAgICAgICAiZGF0ZSI6ICAgICAgICAgIHRvZGF5LAogICAgICAgICAgICAic2Vzc2lvbl9pZCI6"
    "ICAgIHNlbGYuX3Nlc3Npb25faWQsCiAgICAgICAgICAgICJuYW1lIjogICAgICAgICAgbmFtZSwKICAgICAgICAgICAgIm1lc3Nh"
    "Z2VfY291bnQiOiBsZW4oc2VsZi5fbWVzc2FnZXMpLAogICAgICAgICAgICAiZmlyc3RfbWVzc2FnZSI6IChzZWxmLl9tZXNzYWdl"
    "c1swXVsidGltZXN0YW1wIl0KICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgc2VsZi5fbWVzc2FnZXMgZWxzZSAiIiks"
    "CiAgICAgICAgICAgICJsYXN0X21lc3NhZ2UiOiAgKHNlbGYuX21lc3NhZ2VzWy0xXVsidGltZXN0YW1wIl0KICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgaWYgc2VsZi5fbWVzc2FnZXMgZWxzZSAiIiksCiAgICAgICAgfQoKICAgICAgICBpZiBleGlzdGlu"
    "ZzoKICAgICAgICAgICAgaWR4ID0gaW5kZXhbInNlc3Npb25zIl0uaW5kZXgoZXhpc3RpbmcpCiAgICAgICAgICAgIGluZGV4WyJz"
    "ZXNzaW9ucyJdW2lkeF0gPSBlbnRyeQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGluZGV4WyJzZXNzaW9ucyJdLmluc2VydCgw"
    "LCBlbnRyeSkKCiAgICAgICAgIyBLZWVwIGxhc3QgMzY1IGRheXMgaW4gaW5kZXgKICAgICAgICBpbmRleFsic2Vzc2lvbnMiXSA9"
    "IGluZGV4WyJzZXNzaW9ucyJdWzozNjVdCiAgICAgICAgc2VsZi5fc2F2ZV9pbmRleChpbmRleCkKCiAgICAjIOKUgOKUgCBMT0FE"
    "IC8gSk9VUk5BTCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgIGRlZiBsaXN0X3Nlc3Npb25zKHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgIiIiUmV0dXJuIGFsbCBz"
    "ZXNzaW9ucyBmcm9tIGluZGV4LCBuZXdlc3QgZmlyc3QuIiIiCiAgICAgICAgcmV0dXJuIHNlbGYuX2xvYWRfaW5kZXgoKS5nZXQo"
    "InNlc3Npb25zIiwgW10pCgogICAgZGVmIGxvYWRfc2Vzc2lvbl9hc19jb250ZXh0KHNlbGYsIHNlc3Npb25fZGF0ZTogc3RyKSAt"
    "PiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgTG9hZCBhIHBhc3Qgc2Vzc2lvbiBhcyBhIGNvbnRleHQgaW5qZWN0aW9uIHN0cmlu"
    "Zy4KICAgICAgICBSZXR1cm5zIGZvcm1hdHRlZCB0ZXh0IHRvIHByZXBlbmQgdG8gdGhlIHN5c3RlbSBwcm9tcHQuCiAgICAgICAg"
    "VGhpcyBpcyBOT1QgcmVhbCBtZW1vcnkg4oCUIGl0J3MgYSB0ZW1wb3JhcnkgY29udGV4dCB3aW5kb3cgaW5qZWN0aW9uCiAgICAg"
    "ICAgdW50aWwgdGhlIFBoYXNlIDIgbWVtb3J5IHN5c3RlbSBpcyBidWlsdC4KICAgICAgICAiIiIKICAgICAgICBwYXRoID0gc2Vs"
    "Zi5fc2Vzc2lvbnNfZGlyIC8gZiJ7c2Vzc2lvbl9kYXRlfS5qc29ubCIKICAgICAgICBpZiBub3QgcGF0aC5leGlzdHMoKToKICAg"
    "ICAgICAgICAgcmV0dXJuICIiCgogICAgICAgIG1lc3NhZ2VzID0gcmVhZF9qc29ubChwYXRoKQogICAgICAgIHNlbGYuX2xvYWRl"
    "ZF9qb3VybmFsID0gc2Vzc2lvbl9kYXRlCgogICAgICAgIGxpbmVzID0gW2YiW0pPVVJOQUwgTE9BREVEIOKAlCB7c2Vzc2lvbl9k"
    "YXRlfV0iLAogICAgICAgICAgICAgICAgICJUaGUgZm9sbG93aW5nIGlzIGEgcmVjb3JkIG9mIGEgcHJpb3IgY29udmVyc2F0aW9u"
    "LiIsCiAgICAgICAgICAgICAgICAgIlVzZSB0aGlzIGFzIGNvbnRleHQgZm9yIHRoZSBjdXJyZW50IHNlc3Npb246XG4iXQoKICAg"
    "ICAgICAjIEluY2x1ZGUgdXAgdG8gbGFzdCAzMCBtZXNzYWdlcyBmcm9tIHRoYXQgc2Vzc2lvbgogICAgICAgIGZvciBtc2cgaW4g"
    "bWVzc2FnZXNbLTMwOl06CiAgICAgICAgICAgIHJvbGUgICAgPSBtc2cuZ2V0KCJyb2xlIiwgIj8iKS51cHBlcigpCiAgICAgICAg"
    "ICAgIGNvbnRlbnQgPSBtc2cuZ2V0KCJjb250ZW50IiwgIiIpWzozMDBdCiAgICAgICAgICAgIHRzICAgICAgPSBtc2cuZ2V0KCJ0"
    "aW1lc3RhbXAiLCAiIilbOjE2XQogICAgICAgICAgICBsaW5lcy5hcHBlbmQoZiJbe3RzfV0ge3JvbGV9OiB7Y29udGVudH0iKQoK"
    "ICAgICAgICBsaW5lcy5hcHBlbmQoIltFTkQgSk9VUk5BTF0iKQogICAgICAgIHJldHVybiAiXG4iLmpvaW4obGluZXMpCgogICAg"
    "ZGVmIGNsZWFyX2xvYWRlZF9qb3VybmFsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fbG9hZGVkX2pvdXJuYWwgPSBOb25l"
    "CgogICAgQHByb3BlcnR5CiAgICBkZWYgbG9hZGVkX2pvdXJuYWxfZGF0ZShzZWxmKSAtPiBPcHRpb25hbFtzdHJdOgogICAgICAg"
    "IHJldHVybiBzZWxmLl9sb2FkZWRfam91cm5hbAoKICAgIGRlZiByZW5hbWVfc2Vzc2lvbihzZWxmLCBzZXNzaW9uX2RhdGU6IHN0"
    "ciwgbmV3X25hbWU6IHN0cikgLT4gYm9vbDoKICAgICAgICAiIiJSZW5hbWUgYSBzZXNzaW9uIGluIHRoZSBpbmRleC4gUmV0dXJu"
    "cyBUcnVlIG9uIHN1Y2Nlc3MuIiIiCiAgICAgICAgaW5kZXggPSBzZWxmLl9sb2FkX2luZGV4KCkKICAgICAgICBmb3IgZW50cnkg"
    "aW4gaW5kZXhbInNlc3Npb25zIl06CiAgICAgICAgICAgIGlmIGVudHJ5WyJkYXRlIl0gPT0gc2Vzc2lvbl9kYXRlOgogICAgICAg"
    "ICAgICAgICAgZW50cnlbIm5hbWUiXSA9IG5ld19uYW1lWzo4MF0KICAgICAgICAgICAgICAgIHNlbGYuX3NhdmVfaW5kZXgoaW5k"
    "ZXgpCiAgICAgICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVybiBGYWxzZQoKICAgICMg4pSA4pSAIElOREVYIEhF"
    "TFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICBkZWYgX2xvYWRfaW5kZXgoc2VsZikgLT4gZGljdDoKICAgICAgICBpZiBub3Qgc2VsZi5faW5kZXhfcGF0aC5l"
    "eGlzdHMoKToKICAgICAgICAgICAgcmV0dXJuIHsic2Vzc2lvbnMiOiBbXX0KICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVy"
    "biBqc29uLmxvYWRzKAogICAgICAgICAgICAgICAgc2VsZi5faW5kZXhfcGF0aC5yZWFkX3RleHQoZW5jb2Rpbmc9InV0Zi04IikK"
    "ICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHJldHVybiB7InNlc3Npb25zIjogW119"
    "CgogICAgZGVmIF9zYXZlX2luZGV4KHNlbGYsIGluZGV4OiBkaWN0KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2luZGV4X3BhdGgu"
    "d3JpdGVfdGV4dCgKICAgICAgICAgICAganNvbi5kdW1wcyhpbmRleCwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiCiAgICAg"
    "ICAgKQoKCiMg4pSA4pSAIExFU1NPTlMgTEVBUk5FRCBEQVRBQkFTRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTGVzc29uc0xlYXJuZWREQjoKICAgICIiIgog"
    "ICAgUGVyc2lzdGVudCBrbm93bGVkZ2UgYmFzZSBmb3IgY29kZSBsZXNzb25zLCBydWxlcywgYW5kIHJlc29sdXRpb25zLgoKICAg"
    "IENvbHVtbnMgcGVyIHJlY29yZDoKICAgICAgICBpZCwgY3JlYXRlZF9hdCwgZW52aXJvbm1lbnQgKExTTHxQeXRob258UHlTaWRl"
    "NnwuLi4pLCBsYW5ndWFnZSwKICAgICAgICByZWZlcmVuY2Vfa2V5IChzaG9ydCB1bmlxdWUgdGFnKSwgc3VtbWFyeSwgZnVsbF9y"
    "dWxlLAogICAgICAgIHJlc29sdXRpb24sIGxpbmssIHRhZ3MKCiAgICBRdWVyaWVkIEZJUlNUIGJlZm9yZSBhbnkgY29kZSBzZXNz"
    "aW9uIGluIHRoZSByZWxldmFudCBsYW5ndWFnZS4KICAgIFRoZSBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgbGl2ZXMgaGVyZS4KICAg"
    "IEdyb3dpbmcsIG5vbi1kdXBsaWNhdGluZywgc2VhcmNoYWJsZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAg"
    "ICAgICBzZWxmLl9wYXRoID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAibGVzc29uc19sZWFybmVkLmpzb25sIgoKICAgIGRlZiBh"
    "ZGQoc2VsZiwgZW52aXJvbm1lbnQ6IHN0ciwgbGFuZ3VhZ2U6IHN0ciwgcmVmZXJlbmNlX2tleTogc3RyLAogICAgICAgICAgICBz"
    "dW1tYXJ5OiBzdHIsIGZ1bGxfcnVsZTogc3RyLCByZXNvbHV0aW9uOiBzdHIgPSAiIiwKICAgICAgICAgICAgbGluazogc3RyID0g"
    "IiIsIHRhZ3M6IGxpc3QgPSBOb25lKSAtPiBkaWN0OgogICAgICAgIHJlY29yZCA9IHsKICAgICAgICAgICAgImlkIjogICAgICAg"
    "ICAgICBmImxlc3Nvbl97dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogICAgbG9jYWxf"
    "bm93X2lzbygpLAogICAgICAgICAgICAiZW52aXJvbm1lbnQiOiAgIGVudmlyb25tZW50LAogICAgICAgICAgICAibGFuZ3VhZ2Ui"
    "OiAgICAgIGxhbmd1YWdlLAogICAgICAgICAgICAicmVmZXJlbmNlX2tleSI6IHJlZmVyZW5jZV9rZXksCiAgICAgICAgICAgICJz"
    "dW1tYXJ5IjogICAgICAgc3VtbWFyeSwKICAgICAgICAgICAgImZ1bGxfcnVsZSI6ICAgICBmdWxsX3J1bGUsCiAgICAgICAgICAg"
    "ICJyZXNvbHV0aW9uIjogICAgcmVzb2x1dGlvbiwKICAgICAgICAgICAgImxpbmsiOiAgICAgICAgICBsaW5rLAogICAgICAgICAg"
    "ICAidGFncyI6ICAgICAgICAgIHRhZ3Mgb3IgW10sCiAgICAgICAgfQogICAgICAgIGlmIG5vdCBzZWxmLl9pc19kdXBsaWNhdGUo"
    "cmVmZXJlbmNlX2tleSk6CiAgICAgICAgICAgIGFwcGVuZF9qc29ubChzZWxmLl9wYXRoLCByZWNvcmQpCiAgICAgICAgcmV0dXJu"
    "IHJlY29yZAoKICAgIGRlZiBzZWFyY2goc2VsZiwgcXVlcnk6IHN0ciA9ICIiLCBlbnZpcm9ubWVudDogc3RyID0gIiIsCiAgICAg"
    "ICAgICAgICAgIGxhbmd1YWdlOiBzdHIgPSAiIikgLT4gbGlzdFtkaWN0XToKICAgICAgICByZWNvcmRzID0gcmVhZF9qc29ubChz"
    "ZWxmLl9wYXRoKQogICAgICAgIHJlc3VsdHMgPSBbXQogICAgICAgIHEgPSBxdWVyeS5sb3dlcigpCiAgICAgICAgZm9yIHIgaW4g"
    "cmVjb3JkczoKICAgICAgICAgICAgaWYgZW52aXJvbm1lbnQgYW5kIHIuZ2V0KCJlbnZpcm9ubWVudCIsIiIpLmxvd2VyKCkgIT0g"
    "ZW52aXJvbm1lbnQubG93ZXIoKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIGxhbmd1YWdlIGFuZCBy"
    "LmdldCgibGFuZ3VhZ2UiLCIiKS5sb3dlcigpICE9IGxhbmd1YWdlLmxvd2VyKCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQog"
    "ICAgICAgICAgICBpZiBxOgogICAgICAgICAgICAgICAgaGF5c3RhY2sgPSAiICIuam9pbihbCiAgICAgICAgICAgICAgICAgICAg"
    "ci5nZXQoInN1bW1hcnkiLCIiKSwKICAgICAgICAgICAgICAgICAgICByLmdldCgiZnVsbF9ydWxlIiwiIiksCiAgICAgICAgICAg"
    "ICAgICAgICAgci5nZXQoInJlZmVyZW5jZV9rZXkiLCIiKSwKICAgICAgICAgICAgICAgICAgICAiICIuam9pbihyLmdldCgidGFn"
    "cyIsW10pKSwKICAgICAgICAgICAgICAgIF0pLmxvd2VyKCkKICAgICAgICAgICAgICAgIGlmIHEgbm90IGluIGhheXN0YWNrOgog"
    "ICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIHJlc3VsdHMuYXBwZW5kKHIpCiAgICAgICAgcmV0dXJuIHJl"
    "c3VsdHMKCiAgICBkZWYgZ2V0X2FsbChzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgIHJldHVybiByZWFkX2pzb25sKHNlbGYu"
    "X3BhdGgpCgogICAgZGVmIGRlbGV0ZShzZWxmLCByZWNvcmRfaWQ6IHN0cikgLT4gYm9vbDoKICAgICAgICByZWNvcmRzID0gcmVh"
    "ZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIGZpbHRlcmVkID0gW3IgZm9yIHIgaW4gcmVjb3JkcyBpZiByLmdldCgiaWQiKSAh"
    "PSByZWNvcmRfaWRdCiAgICAgICAgaWYgbGVuKGZpbHRlcmVkKSA8IGxlbihyZWNvcmRzKToKICAgICAgICAgICAgd3JpdGVfanNv"
    "bmwoc2VsZi5fcGF0aCwgZmlsdGVyZWQpCiAgICAgICAgICAgIHJldHVybiBUcnVlCiAgICAgICAgcmV0dXJuIEZhbHNlCgogICAg"
    "ZGVmIGJ1aWxkX2NvbnRleHRfZm9yX2xhbmd1YWdlKHNlbGYsIGxhbmd1YWdlOiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgbWF4X2NoYXJzOiBpbnQgPSAxNTAwKSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgQnVpbGQgYSBjb250"
    "ZXh0IHN0cmluZyBvZiBhbGwgcnVsZXMgZm9yIGEgZ2l2ZW4gbGFuZ3VhZ2UuCiAgICAgICAgRm9yIGluamVjdGlvbiBpbnRvIHN5"
    "c3RlbSBwcm9tcHQgYmVmb3JlIGNvZGUgc2Vzc2lvbnMuCiAgICAgICAgIiIiCiAgICAgICAgcmVjb3JkcyA9IHNlbGYuc2VhcmNo"
    "KGxhbmd1YWdlPWxhbmd1YWdlKQogICAgICAgIGlmIG5vdCByZWNvcmRzOgogICAgICAgICAgICByZXR1cm4gIiIKCiAgICAgICAg"
    "cGFydHMgPSBbZiJbe2xhbmd1YWdlLnVwcGVyKCl9IFJVTEVTIOKAlCBBUFBMWSBCRUZPUkUgV1JJVElORyBDT0RFXSJdCiAgICAg"
    "ICAgdG90YWwgPSAwCiAgICAgICAgZm9yIHIgaW4gcmVjb3JkczoKICAgICAgICAgICAgZW50cnkgPSBmIuKAoiB7ci5nZXQoJ3Jl"
    "ZmVyZW5jZV9rZXknLCcnKX06IHtyLmdldCgnZnVsbF9ydWxlJywnJyl9IgogICAgICAgICAgICBpZiB0b3RhbCArIGxlbihlbnRy"
    "eSkgPiBtYXhfY2hhcnM6CiAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBwYXJ0cy5hcHBlbmQoZW50cnkpCiAgICAg"
    "ICAgICAgIHRvdGFsICs9IGxlbihlbnRyeSkKCiAgICAgICAgcGFydHMuYXBwZW5kKGYiW0VORCB7bGFuZ3VhZ2UudXBwZXIoKX0g"
    "UlVMRVNdIikKICAgICAgICByZXR1cm4gIlxuIi5qb2luKHBhcnRzKQoKICAgIGRlZiBfaXNfZHVwbGljYXRlKHNlbGYsIHJlZmVy"
    "ZW5jZV9rZXk6IHN0cikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gYW55KAogICAgICAgICAgICByLmdldCgicmVmZXJlbmNlX2tl"
    "eSIsIiIpLmxvd2VyKCkgPT0gcmVmZXJlbmNlX2tleS5sb3dlcigpCiAgICAgICAgICAgIGZvciByIGluIHJlYWRfanNvbmwoc2Vs"
    "Zi5fcGF0aCkKICAgICAgICApCgogICAgZGVmIHNlZWRfbHNsX3J1bGVzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAg"
    "ICAgU2VlZCB0aGUgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IG9uIGZpcnN0IHJ1biBpZiB0aGUgREIgaXMgZW1wdHkuCiAgICAgICAg"
    "VGhlc2UgYXJlIHRoZSBoYXJkIHJ1bGVzIGZyb20gdGhlIHByb2plY3Qgc3RhbmRpbmcgcnVsZXMuCiAgICAgICAgIiIiCiAgICAg"
    "ICAgaWYgcmVhZF9qc29ubChzZWxmLl9wYXRoKToKICAgICAgICAgICAgcmV0dXJuICAjIEFscmVhZHkgc2VlZGVkCgogICAgICAg"
    "IGxzbF9ydWxlcyA9IFsKICAgICAgICAgICAgKCJMU0wiLCAiTFNMIiwgIk5PX1RFUk5BUlkiLAogICAgICAgICAgICAgIk5vIHRl"
    "cm5hcnkgb3BlcmF0b3JzIGluIExTTCIsCiAgICAgICAgICAgICAiTmV2ZXIgdXNlIHRoZSB0ZXJuYXJ5IG9wZXJhdG9yICg/Oikg"
    "aW4gTFNMIHNjcmlwdHMuICIKICAgICAgICAgICAgICJVc2UgaWYvZWxzZSBibG9ja3MgaW5zdGVhZC4gTFNMIGRvZXMgbm90IHN1"
    "cHBvcnQgdGVybmFyeS4iLAogICAgICAgICAgICAgIlJlcGxhY2Ugd2l0aCBpZi9lbHNlIGJsb2NrLiIsICIiKSwKICAgICAgICAg"
    "ICAgKCJMU0wiLCAiTFNMIiwgIk5PX0ZPUkVBQ0giLAogICAgICAgICAgICAgIk5vIGZvcmVhY2ggbG9vcHMgaW4gTFNMIiwKICAg"
    "ICAgICAgICAgICJMU0wgaGFzIG5vIGZvcmVhY2ggbG9vcCBjb25zdHJ1Y3QuIFVzZSBpbnRlZ2VyIGluZGV4IHdpdGggIgogICAg"
    "ICAgICAgICAgImxsR2V0TGlzdExlbmd0aCgpIGFuZCBhIGZvciBvciB3aGlsZSBsb29wLiIsCiAgICAgICAgICAgICAiVXNlOiBm"
    "b3IoaW50ZWdlciBpPTA7IGk8bGxHZXRMaXN0TGVuZ3RoKG15TGlzdCk7IGkrKykiLCAiIiksCiAgICAgICAgICAgICgiTFNMIiwg"
    "IkxTTCIsICJOT19HTE9CQUxfQVNTSUdOX0ZST01fRlVOQyIsCiAgICAgICAgICAgICAiTm8gZ2xvYmFsIHZhcmlhYmxlIGFzc2ln"
    "bm1lbnRzIGZyb20gZnVuY3Rpb24gY2FsbHMiLAogICAgICAgICAgICAgIkdsb2JhbCB2YXJpYWJsZSBpbml0aWFsaXphdGlvbiBp"
    "biBMU0wgY2Fubm90IGNhbGwgZnVuY3Rpb25zLiAiCiAgICAgICAgICAgICAiSW5pdGlhbGl6ZSBnbG9iYWxzIHdpdGggbGl0ZXJh"
    "bCB2YWx1ZXMgb25seS4gIgogICAgICAgICAgICAgIkFzc2lnbiBmcm9tIGZ1bmN0aW9ucyBpbnNpZGUgZXZlbnQgaGFuZGxlcnMg"
    "b3Igb3RoZXIgZnVuY3Rpb25zLiIsCiAgICAgICAgICAgICAiTW92ZSB0aGUgYXNzaWdubWVudCBpbnRvIGFuIGV2ZW50IGhhbmRs"
    "ZXIgKHN0YXRlX2VudHJ5LCBldGMuKSIsICIiKSwKICAgICAgICAgICAgKCJMU0wiLCAiTFNMIiwgIk5PX1ZPSURfS0VZV09SRCIs"
    "CiAgICAgICAgICAgICAiTm8gdm9pZCBrZXl3b3JkIGluIExTTCIsCiAgICAgICAgICAgICAiTFNMIGRvZXMgbm90IGhhdmUgYSB2"
    "b2lkIGtleXdvcmQgZm9yIGZ1bmN0aW9uIHJldHVybiB0eXBlcy4gIgogICAgICAgICAgICAgIkZ1bmN0aW9ucyB0aGF0IHJldHVy"
    "biBub3RoaW5nIHNpbXBseSBvbWl0IHRoZSByZXR1cm4gdHlwZS4iLAogICAgICAgICAgICAgIlJlbW92ZSAndm9pZCcgZnJvbSBm"
    "dW5jdGlvbiBzaWduYXR1cmUuICIKICAgICAgICAgICAgICJlLmcuIG15RnVuYygpIHsgLi4uIH0gbm90IHZvaWQgbXlGdW5jKCkg"
    "eyAuLi4gfSIsICIiKSwKICAgICAgICAgICAgKCJMU0wiLCAiTFNMIiwgIkNPTVBMRVRFX1NDUklQVFNfT05MWSIsCiAgICAgICAg"
    "ICAgICAiQWx3YXlzIHByb3ZpZGUgY29tcGxldGUgc2NyaXB0cywgbmV2ZXIgcGFydGlhbCBlZGl0cyIsCiAgICAgICAgICAgICAi"
    "V2hlbiB3cml0aW5nIG9yIGVkaXRpbmcgTFNMIHNjcmlwdHMsIGFsd2F5cyBvdXRwdXQgdGhlIGNvbXBsZXRlICIKICAgICAgICAg"
    "ICAgICJzY3JpcHQuIE5ldmVyIHByb3ZpZGUgcGFydGlhbCBzbmlwcGV0cyBvciAnYWRkIHRoaXMgc2VjdGlvbicgIgogICAgICAg"
    "ICAgICAgImluc3RydWN0aW9ucy4gVGhlIGZ1bGwgc2NyaXB0IG11c3QgYmUgY29weS1wYXN0ZSByZWFkeS4iLAogICAgICAgICAg"
    "ICAgIldyaXRlIHRoZSBlbnRpcmUgc2NyaXB0IGZyb20gdG9wIHRvIGJvdHRvbS4iLCAiIiksCiAgICAgICAgXQoKICAgICAgICBm"
    "b3IgZW52LCBsYW5nLCByZWYsIHN1bW1hcnksIGZ1bGxfcnVsZSwgcmVzb2x1dGlvbiwgbGluayBpbiBsc2xfcnVsZXM6CiAgICAg"
    "ICAgICAgIHNlbGYuYWRkKGVudiwgbGFuZywgcmVmLCBzdW1tYXJ5LCBmdWxsX3J1bGUsIHJlc29sdXRpb24sIGxpbmssCiAgICAg"
    "ICAgICAgICAgICAgICAgIHRhZ3M9WyJsc2wiLCAiZm9yYmlkZGVuIiwgInN0YW5kaW5nX3J1bGUiXSkKCgojIOKUgOKUgCBUQVNL"
    "IE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFRhc2tNYW5hZ2VyOgogICAgIiIiCiAgICBU"
    "YXNrL3JlbWluZGVyIENSVUQgYW5kIGR1ZS1ldmVudCBkZXRlY3Rpb24uCgogICAgRmlsZTogbWVtb3JpZXMvdGFza3MuanNvbmwK"
    "CiAgICBUYXNrIHJlY29yZCBmaWVsZHM6CiAgICAgICAgaWQsIGNyZWF0ZWRfYXQsIGR1ZV9hdCwgcHJlX3RyaWdnZXIgKDFtaW4g"
    "YmVmb3JlKSwKICAgICAgICB0ZXh0LCBzdGF0dXMgKHBlbmRpbmd8dHJpZ2dlcmVkfHNub296ZWR8Y29tcGxldGVkfGNhbmNlbGxl"
    "ZCksCiAgICAgICAgYWNrbm93bGVkZ2VkX2F0LCByZXRyeV9jb3VudCwgbGFzdF90cmlnZ2VyZWRfYXQsIG5leHRfcmV0cnlfYXQs"
    "CiAgICAgICAgc291cmNlIChsb2NhbHxnb29nbGUpLCBnb29nbGVfZXZlbnRfaWQsIHN5bmNfc3RhdHVzLCBtZXRhZGF0YQoKICAg"
    "IER1ZS1ldmVudCBjeWNsZToKICAgICAgICAtIFByZS10cmlnZ2VyOiAxIG1pbnV0ZSBiZWZvcmUgZHVlIOKGkiBhbm5vdW5jZSB1"
    "cGNvbWluZwogICAgICAgIC0gRHVlIHRyaWdnZXI6IGF0IGR1ZSB0aW1lIOKGkiBhbGVydCBzb3VuZCArIEFJIGNvbW1lbnRhcnkK"
    "ICAgICAgICAtIDMtbWludXRlIHdpbmRvdzogaWYgbm90IGFja25vd2xlZGdlZCDihpIgc25vb3plCiAgICAgICAgLSAxMi1taW51"
    "dGUgcmV0cnk6IHJlLXRyaWdnZXIKICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBzZWxmLl9wYXRoID0g"
    "Y2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAidGFza3MuanNvbmwiCgogICAgIyDilIDilIAgQ1JVRCDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgIGRlZiBsb2FkX2FsbChzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgIHRhc2tzID0gcmVhZF9qc29ubChz"
    "ZWxmLl9wYXRoKQogICAgICAgIGNoYW5nZWQgPSBGYWxzZQogICAgICAgIG5vcm1hbGl6ZWQgPSBbXQogICAgICAgIGZvciB0IGlu"
    "IHRhc2tzOgogICAgICAgICAgICBpZiBub3QgaXNpbnN0YW5jZSh0LCBkaWN0KToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAg"
    "ICAgICAgICAgIGlmICJpZCIgbm90IGluIHQ6CiAgICAgICAgICAgICAgICB0WyJpZCJdID0gZiJ0YXNrX3t1dWlkLnV1aWQ0KCku"
    "aGV4WzoxMF19IgogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgIyBOb3JtYWxpemUgZmllbGQgbmFt"
    "ZXMKICAgICAgICAgICAgaWYgImR1ZV9hdCIgbm90IGluIHQ6CiAgICAgICAgICAgICAgICB0WyJkdWVfYXQiXSA9IHQuZ2V0KCJk"
    "dWUiKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJzdGF0dXMiLCAgICAg"
    "ICAgICAgInBlbmRpbmciKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoInJldHJ5X2NvdW50IiwgICAgICAwKQogICAgICAgICAg"
    "ICB0LnNldGRlZmF1bHQoImFja25vd2xlZGdlZF9hdCIsICBOb25lKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoImxhc3RfdHJp"
    "Z2dlcmVkX2F0IixOb25lKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoIm5leHRfcmV0cnlfYXQiLCAgICBOb25lKQogICAgICAg"
    "ICAgICB0LnNldGRlZmF1bHQoInByZV9hbm5vdW5jZWQiLCAgICBGYWxzZSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJzb3Vy"
    "Y2UiLCAgICAgICAgICAgImxvY2FsIikKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJnb29nbGVfZXZlbnRfaWQiLCAgTm9uZSkK"
    "ICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJzeW5jX3N0YXR1cyIsICAgICAgInBlbmRpbmciKQogICAgICAgICAgICB0LnNldGRl"
    "ZmF1bHQoIm1ldGFkYXRhIiwgICAgICAgICB7fSkKICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJjcmVhdGVkX2F0IiwgICAgICAg"
    "bG9jYWxfbm93X2lzbygpKQoKICAgICAgICAgICAgIyBDb21wdXRlIHByZV90cmlnZ2VyIGlmIG1pc3NpbmcKICAgICAgICAgICAg"
    "aWYgdC5nZXQoImR1ZV9hdCIpIGFuZCBub3QgdC5nZXQoInByZV90cmlnZ2VyIik6CiAgICAgICAgICAgICAgICBkdCA9IHBhcnNl"
    "X2lzbyh0WyJkdWVfYXQiXSkKICAgICAgICAgICAgICAgIGlmIGR0OgogICAgICAgICAgICAgICAgICAgIHByZSA9IGR0IC0gdGlt"
    "ZWRlbHRhKG1pbnV0ZXM9MSkKICAgICAgICAgICAgICAgICAgICB0WyJwcmVfdHJpZ2dlciJdID0gcHJlLmlzb2Zvcm1hdCh0aW1l"
    "c3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICAgICAgICAgIG5vcm1hbGl6ZWQu"
    "YXBwZW5kKHQpCgogICAgICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIG5vcm1hbGl6"
    "ZWQpCiAgICAgICAgcmV0dXJuIG5vcm1hbGl6ZWQKCiAgICBkZWYgc2F2ZV9hbGwoc2VsZiwgdGFza3M6IGxpc3RbZGljdF0pIC0+"
    "IE5vbmU6CiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgdGFza3MpCgogICAgZGVmIGFkZChzZWxmLCB0ZXh0OiBzdHIs"
    "IGR1ZV9kdDogZGF0ZXRpbWUsCiAgICAgICAgICAgIHNvdXJjZTogc3RyID0gImxvY2FsIikgLT4gZGljdDoKICAgICAgICBwcmUg"
    "PSBkdWVfZHQgLSB0aW1lZGVsdGEobWludXRlcz0xKQogICAgICAgIHRhc2sgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAg"
    "ICAgICAgZiJ0YXNrX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19IiwKICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgICAgICBsb2Nh"
    "bF9ub3dfaXNvKCksCiAgICAgICAgICAgICJkdWVfYXQiOiAgICAgICAgICAgZHVlX2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vj"
    "b25kcyIpLAogICAgICAgICAgICAicHJlX3RyaWdnZXIiOiAgICAgIHByZS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwK"
    "ICAgICAgICAgICAgInRleHQiOiAgICAgICAgICAgICB0ZXh0LnN0cmlwKCksCiAgICAgICAgICAgICJzdGF0dXMiOiAgICAgICAg"
    "ICAgInBlbmRpbmciLAogICAgICAgICAgICAiYWNrbm93bGVkZ2VkX2F0IjogIE5vbmUsCiAgICAgICAgICAgICJyZXRyeV9jb3Vu"
    "dCI6ICAgICAgMCwKICAgICAgICAgICAgImxhc3RfdHJpZ2dlcmVkX2F0IjpOb25lLAogICAgICAgICAgICAibmV4dF9yZXRyeV9h"
    "dCI6ICAgIE5vbmUsCiAgICAgICAgICAgICJwcmVfYW5ub3VuY2VkIjogICAgRmFsc2UsCiAgICAgICAgICAgICJzb3VyY2UiOiAg"
    "ICAgICAgICAgc291cmNlLAogICAgICAgICAgICAiZ29vZ2xlX2V2ZW50X2lkIjogIE5vbmUsCiAgICAgICAgICAgICJzeW5jX3N0"
    "YXR1cyI6ICAgICAgInBlbmRpbmciLAogICAgICAgICAgICAibWV0YWRhdGEiOiAgICAgICAgIHt9LAogICAgICAgIH0KICAgICAg"
    "ICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIHRhc2tzLmFwcGVuZCh0YXNrKQogICAgICAgIHNlbGYuc2F2ZV9hbGwo"
    "dGFza3MpCiAgICAgICAgcmV0dXJuIHRhc2sKCiAgICBkZWYgdXBkYXRlX3N0YXR1cyhzZWxmLCB0YXNrX2lkOiBzdHIsIHN0YXR1"
    "czogc3RyLAogICAgICAgICAgICAgICAgICAgICAgYWNrbm93bGVkZ2VkOiBib29sID0gRmFsc2UpIC0+IE9wdGlvbmFsW2RpY3Rd"
    "OgogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHQu"
    "Z2V0KCJpZCIpID09IHRhc2tfaWQ6CiAgICAgICAgICAgICAgICB0WyJzdGF0dXMiXSA9IHN0YXR1cwogICAgICAgICAgICAgICAg"
    "aWYgYWNrbm93bGVkZ2VkOgogICAgICAgICAgICAgICAgICAgIHRbImFja25vd2xlZGdlZF9hdCJdID0gbG9jYWxfbm93X2lzbygp"
    "CiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICAgICAgcmV0dXJuIHQKICAgICAgICByZXR1"
    "cm4gTm9uZQoKICAgIGRlZiBjb21wbGV0ZShzZWxmLCB0YXNrX2lkOiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHRh"
    "c2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09"
    "IHRhc2tfaWQ6CiAgICAgICAgICAgICAgICB0WyJzdGF0dXMiXSAgICAgICAgICA9ICJjb21wbGV0ZWQiCiAgICAgICAgICAgICAg"
    "ICB0WyJhY2tub3dsZWRnZWRfYXQiXSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNr"
    "cykKICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY2FuY2VsKHNlbGYsIHRhc2tf"
    "aWQ6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3MgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBmb3IgdCBp"
    "biB0YXNrczoKICAgICAgICAgICAgaWYgdC5nZXQoImlkIikgPT0gdGFza19pZDoKICAgICAgICAgICAgICAgIHRbInN0YXR1cyJd"
    "ICAgICAgICAgID0gImNhbmNlbGxlZCIKICAgICAgICAgICAgICAgIHRbImFja25vd2xlZGdlZF9hdCJdID0gbG9jYWxfbm93X2lz"
    "bygpCiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICAgICAgcmV0dXJuIHQKICAgICAgICBy"
    "ZXR1cm4gTm9uZQoKICAgIGRlZiBjbGVhcl9jb21wbGV0ZWQoc2VsZikgLT4gaW50OgogICAgICAgIHRhc2tzICAgID0gc2VsZi5s"
    "b2FkX2FsbCgpCiAgICAgICAga2VwdCAgICAgPSBbdCBmb3IgdCBpbiB0YXNrcwogICAgICAgICAgICAgICAgICAgIGlmIHQuZ2V0"
    "KCJzdGF0dXMiKSBub3QgaW4geyJjb21wbGV0ZWQiLCJjYW5jZWxsZWQifV0KICAgICAgICByZW1vdmVkICA9IGxlbih0YXNrcykg"
    "LSBsZW4oa2VwdCkKICAgICAgICBpZiByZW1vdmVkOgogICAgICAgICAgICBzZWxmLnNhdmVfYWxsKGtlcHQpCiAgICAgICAgcmV0"
    "dXJuIHJlbW92ZWQKCiAgICBkZWYgdXBkYXRlX2dvb2dsZV9zeW5jKHNlbGYsIHRhc2tfaWQ6IHN0ciwgc3luY19zdGF0dXM6IHN0"
    "ciwKICAgICAgICAgICAgICAgICAgICAgICAgICAgZ29vZ2xlX2V2ZW50X2lkOiBzdHIgPSAiIiwKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgZXJyb3I6IHN0ciA9ICIiKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwo"
    "KQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAgICAg"
    "ICAgICAgdFsic3luY19zdGF0dXMiXSAgICA9IHN5bmNfc3RhdHVzCiAgICAgICAgICAgICAgICB0WyJsYXN0X3N5bmNlZF9hdCJd"
    "ID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgICAgICBpZiBnb29nbGVfZXZlbnRfaWQ6CiAgICAgICAgICAgICAgICAgICAg"
    "dFsiZ29vZ2xlX2V2ZW50X2lkIl0gPSBnb29nbGVfZXZlbnRfaWQKICAgICAgICAgICAgICAgIGlmIGVycm9yOgogICAgICAgICAg"
    "ICAgICAgICAgIHQuc2V0ZGVmYXVsdCgibWV0YWRhdGEiLCB7fSkKICAgICAgICAgICAgICAgICAgICB0WyJtZXRhZGF0YSJdWyJn"
    "b29nbGVfc3luY19lcnJvciJdID0gZXJyb3JbOjI0MF0KICAgICAgICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAg"
    "ICAgICAgICAgICByZXR1cm4gdAogICAgICAgIHJldHVybiBOb25lCgogICAgIyDilIDilIAgRFVFIEVWRU5UIERFVEVDVElPTiDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBnZXRfZHVlX2V2"
    "ZW50cyhzZWxmKSAtPiBsaXN0W3R1cGxlW3N0ciwgZGljdF1dOgogICAgICAgICIiIgogICAgICAgIENoZWNrIGFsbCB0YXNrcyBm"
    "b3IgZHVlL3ByZS10cmlnZ2VyL3JldHJ5IGV2ZW50cy4KICAgICAgICBSZXR1cm5zIGxpc3Qgb2YgKGV2ZW50X3R5cGUsIHRhc2sp"
    "IHR1cGxlcy4KICAgICAgICBldmVudF90eXBlOiAicHJlIiB8ICJkdWUiIHwgInJldHJ5IgoKICAgICAgICBNb2RpZmllcyB0YXNr"
    "IHN0YXR1c2VzIGluIHBsYWNlIGFuZCBzYXZlcy4KICAgICAgICBDYWxsIGZyb20gQVBTY2hlZHVsZXIgZXZlcnkgMzAgc2Vjb25k"
    "cy4KICAgICAgICAiIiIKICAgICAgICBub3cgICAgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkKICAgICAgICB0YXNrcyAg"
    "PSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBldmVudHMgPSBbXQogICAgICAgIGNoYW5nZWQgPSBGYWxzZQoKICAgICAgICBmb3Ig"
    "dGFzayBpbiB0YXNrczoKICAgICAgICAgICAgaWYgdGFzay5nZXQoImFja25vd2xlZGdlZF9hdCIpOgogICAgICAgICAgICAgICAg"
    "Y29udGludWUKCiAgICAgICAgICAgIHN0YXR1cyAgID0gdGFzay5nZXQoInN0YXR1cyIsICJwZW5kaW5nIikKICAgICAgICAgICAg"
    "ZHVlICAgICAgPSBzZWxmLl9wYXJzZV9sb2NhbCh0YXNrLmdldCgiZHVlX2F0IikpCiAgICAgICAgICAgIHByZSAgICAgID0gc2Vs"
    "Zi5fcGFyc2VfbG9jYWwodGFzay5nZXQoInByZV90cmlnZ2VyIikpCiAgICAgICAgICAgIG5leHRfcmV0ID0gc2VsZi5fcGFyc2Vf"
    "bG9jYWwodGFzay5nZXQoIm5leHRfcmV0cnlfYXQiKSkKICAgICAgICAgICAgZGVhZGxpbmUgPSBzZWxmLl9wYXJzZV9sb2NhbCh0"
    "YXNrLmdldCgiYWxlcnRfZGVhZGxpbmUiKSkKCiAgICAgICAgICAgICMgUHJlLXRyaWdnZXIKICAgICAgICAgICAgaWYgKHN0YXR1"
    "cyA9PSAicGVuZGluZyIgYW5kIHByZSBhbmQgbm93ID49IHByZQogICAgICAgICAgICAgICAgICAgIGFuZCBub3QgdGFzay5nZXQo"
    "InByZV9hbm5vdW5jZWQiKSk6CiAgICAgICAgICAgICAgICB0YXNrWyJwcmVfYW5ub3VuY2VkIl0gPSBUcnVlCiAgICAgICAgICAg"
    "ICAgICBldmVudHMuYXBwZW5kKCgicHJlIiwgdGFzaykpCiAgICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgICAgICAg"
    "ICAgIyBEdWUgdHJpZ2dlcgogICAgICAgICAgICBpZiBzdGF0dXMgPT0gInBlbmRpbmciIGFuZCBkdWUgYW5kIG5vdyA+PSBkdWU6"
    "CiAgICAgICAgICAgICAgICB0YXNrWyJzdGF0dXMiXSAgICAgICAgICAgPSAidHJpZ2dlcmVkIgogICAgICAgICAgICAgICAgdGFz"
    "a1sibGFzdF90cmlnZ2VyZWRfYXQiXT0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgICAgICB0YXNrWyJhbGVydF9kZWFkbGlu"
    "ZSJdICAgPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93KCkuYXN0aW1lem9uZSgpICsgdGltZWRlbHRhKG1pbnV0"
    "ZXM9MykKICAgICAgICAgICAgICAgICkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAgIGV2ZW50"
    "cy5hcHBlbmQoKCJkdWUiLCB0YXNrKSkKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICBjb250"
    "aW51ZQoKICAgICAgICAgICAgIyBTbm9vemUgYWZ0ZXIgMy1taW51dGUgd2luZG93CiAgICAgICAgICAgIGlmIHN0YXR1cyA9PSAi"
    "dHJpZ2dlcmVkIiBhbmQgZGVhZGxpbmUgYW5kIG5vdyA+PSBkZWFkbGluZToKICAgICAgICAgICAgICAgIHRhc2tbInN0YXR1cyJd"
    "ICAgICAgICA9ICJzbm9vemVkIgogICAgICAgICAgICAgICAgdGFza1sibmV4dF9yZXRyeV9hdCJdID0gKAogICAgICAgICAgICAg"
    "ICAgICAgIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKSArIHRpbWVkZWx0YShtaW51dGVzPTEyKQogICAgICAgICAgICAgICAg"
    "KS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAg"
    "ICAgIGNvbnRpbnVlCgogICAgICAgICAgICAjIFJldHJ5CiAgICAgICAgICAgIGlmIHN0YXR1cyBpbiB7InJldHJ5X3BlbmRpbmci"
    "LCJzbm9vemVkIn0gYW5kIG5leHRfcmV0IGFuZCBub3cgPj0gbmV4dF9yZXQ6CiAgICAgICAgICAgICAgICB0YXNrWyJzdGF0dXMi"
    "XSAgICAgICAgICAgID0gInRyaWdnZXJlZCIKICAgICAgICAgICAgICAgIHRhc2tbInJldHJ5X2NvdW50Il0gICAgICAgPSBpbnQo"
    "dGFzay5nZXQoInJldHJ5X2NvdW50IiwwKSkgKyAxCiAgICAgICAgICAgICAgICB0YXNrWyJsYXN0X3RyaWdnZXJlZF9hdCJdID0g"
    "bG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgICAgICB0YXNrWyJhbGVydF9kZWFkbGluZSJdICAgID0gKAogICAgICAgICAgICAg"
    "ICAgICAgIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKSArIHRpbWVkZWx0YShtaW51dGVzPTMpCiAgICAgICAgICAgICAgICAp"
    "Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICB0YXNrWyJuZXh0X3JldHJ5X2F0Il0gICAgID0g"
    "Tm9uZQogICAgICAgICAgICAgICAgZXZlbnRzLmFwcGVuZCgoInJldHJ5IiwgdGFzaykpCiAgICAgICAgICAgICAgICBjaGFuZ2Vk"
    "ID0gVHJ1ZQoKICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgIHJldHVy"
    "biBldmVudHMKCiAgICBkZWYgX3BhcnNlX2xvY2FsKHNlbGYsIHZhbHVlOiBzdHIpIC0+IE9wdGlvbmFsW2RhdGV0aW1lXToKICAg"
    "ICAgICAiIiJQYXJzZSBJU08gc3RyaW5nIHRvIHRpbWV6b25lLWF3YXJlIGRhdGV0aW1lIGZvciBjb21wYXJpc29uLiIiIgogICAg"
    "ICAgIGR0ID0gcGFyc2VfaXNvKHZhbHVlKQogICAgICAgIGlmIGR0IGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybiBOb25lCiAg"
    "ICAgICAgaWYgZHQudHppbmZvIGlzIE5vbmU6CiAgICAgICAgICAgIGR0ID0gZHQuYXN0aW1lem9uZSgpCiAgICAgICAgcmV0dXJu"
    "IGR0CgogICAgIyDilIDilIAgTkFUVVJBTCBMQU5HVUFHRSBQQVJTSU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAogICAgQHN0YXRpY21ldGhvZAogICAgZGVmIGNsYXNzaWZ5X2ludGVudCh0ZXh0OiBzdHIpIC0+IGRpY3Q6CiAg"
    "ICAgICAgIiIiCiAgICAgICAgQ2xhc3NpZnkgdXNlciBpbnB1dCBhcyB0YXNrL3JlbWluZGVyL3RpbWVyL2NoYXQuCiAgICAgICAg"
    "UmV0dXJucyB7ImludGVudCI6IHN0ciwgImNsZWFuZWRfaW5wdXQiOiBzdHJ9CiAgICAgICAgIiIiCiAgICAgICAgaW1wb3J0IHJl"
    "CiAgICAgICAgIyBTdHJpcCBjb21tb24gaW52b2NhdGlvbiBwcmVmaXhlcwogICAgICAgIGNsZWFuZWQgPSByZS5zdWIoCiAgICAg"
    "ICAgICAgIHJmIl5ccyooPzp7REVDS19OQU1FLmxvd2VyKCl9fGhleVxzK3tERUNLX05BTUUubG93ZXIoKX0pXHMqLD9ccypbOlwt"
    "XT9ccyoiLAogICAgICAgICAgICAiIiwgdGV4dCwgZmxhZ3M9cmUuSQogICAgICAgICkuc3RyaXAoKQoKICAgICAgICBsb3cgPSBj"
    "bGVhbmVkLmxvd2VyKCkKCiAgICAgICAgdGltZXJfcGF0cyAgICA9IFtyIlxic2V0KD86XHMrYSk/XHMrdGltZXJcYiIsIHIiXGJ0"
    "aW1lclxzK2ZvclxiIiwKICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJzdGFydCg/OlxzK2EpP1xzK3RpbWVyXGIiXQogICAg"
    "ICAgIHJlbWluZGVyX3BhdHMgPSBbciJcYnJlbWluZCBtZVxiIiwgciJcYnNldCg/OlxzK2EpP1xzK3JlbWluZGVyXGIiLAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgciJcYmFkZCg/OlxzK2EpP1xzK3JlbWluZGVyXGIiLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAgciJcYnNldCg/OlxzK2FuPyk/XHMrYWxhcm1cYiIsIHIiXGJhbGFybVxzK2ZvclxiIl0KICAgICAgICB0YXNrX3BhdHMgICAg"
    "ID0gW3IiXGJhZGQoPzpccythKT9ccyt0YXNrXGIiLAogICAgICAgICAgICAgICAgICAgICAgICAgciJcYmNyZWF0ZSg/OlxzK2Ep"
    "P1xzK3Rhc2tcYiIsIHIiXGJuZXdccyt0YXNrXGIiXQoKICAgICAgICBpbXBvcnQgcmUgYXMgX3JlCiAgICAgICAgaWYgYW55KF9y"
    "ZS5zZWFyY2gocCwgbG93KSBmb3IgcCBpbiB0aW1lcl9wYXRzKToKICAgICAgICAgICAgaW50ZW50ID0gInRpbWVyIgogICAgICAg"
    "IGVsaWYgYW55KF9yZS5zZWFyY2gocCwgbG93KSBmb3IgcCBpbiByZW1pbmRlcl9wYXRzKToKICAgICAgICAgICAgaW50ZW50ID0g"
    "InJlbWluZGVyIgogICAgICAgIGVsaWYgYW55KF9yZS5zZWFyY2gocCwgbG93KSBmb3IgcCBpbiB0YXNrX3BhdHMpOgogICAgICAg"
    "ICAgICBpbnRlbnQgPSAidGFzayIKICAgICAgICBlbHNlOgogICAgICAgICAgICBpbnRlbnQgPSAiY2hhdCIKCiAgICAgICAgcmV0"
    "dXJuIHsiaW50ZW50IjogaW50ZW50LCAiY2xlYW5lZF9pbnB1dCI6IGNsZWFuZWR9CgogICAgQHN0YXRpY21ldGhvZAogICAgZGVm"
    "IHBhcnNlX2R1ZV9kYXRldGltZSh0ZXh0OiBzdHIpIC0+IE9wdGlvbmFsW2RhdGV0aW1lXToKICAgICAgICAiIiIKICAgICAgICBQ"
    "YXJzZSBuYXR1cmFsIGxhbmd1YWdlIHRpbWUgZXhwcmVzc2lvbiBmcm9tIHRhc2sgdGV4dC4KICAgICAgICBIYW5kbGVzOiAiaW4g"
    "MzAgbWludXRlcyIsICJhdCAzcG0iLCAidG9tb3Jyb3cgYXQgOWFtIiwKICAgICAgICAgICAgICAgICAiaW4gMiBob3VycyIsICJh"
    "dCAxNTozMCIsIGV0Yy4KICAgICAgICBSZXR1cm5zIGEgZGF0ZXRpbWUgb3IgTm9uZSBpZiB1bnBhcnNlYWJsZS4KICAgICAgICAi"
    "IiIKICAgICAgICBpbXBvcnQgcmUKICAgICAgICBub3cgID0gZGF0ZXRpbWUubm93KCkKICAgICAgICBsb3cgID0gdGV4dC5sb3dl"
    "cigpLnN0cmlwKCkKCiAgICAgICAgIyAiaW4gWCBtaW51dGVzL2hvdXJzL2RheXMiCiAgICAgICAgbSA9IHJlLnNlYXJjaCgKICAg"
    "ICAgICAgICAgciJpblxzKyhcZCspXHMqKG1pbnV0ZXxtaW58aG91cnxocnxkYXl8c2Vjb25kfHNlYykiLAogICAgICAgICAgICBs"
    "b3cKICAgICAgICApCiAgICAgICAgaWYgbToKICAgICAgICAgICAgbiAgICA9IGludChtLmdyb3VwKDEpKQogICAgICAgICAgICB1"
    "bml0ID0gbS5ncm91cCgyKQogICAgICAgICAgICBpZiAibWluIiBpbiB1bml0OiAgcmV0dXJuIG5vdyArIHRpbWVkZWx0YShtaW51"
    "dGVzPW4pCiAgICAgICAgICAgIGlmICJob3VyIiBpbiB1bml0IG9yICJociIgaW4gdW5pdDogcmV0dXJuIG5vdyArIHRpbWVkZWx0"
    "YShob3Vycz1uKQogICAgICAgICAgICBpZiAiZGF5IiAgaW4gdW5pdDogcmV0dXJuIG5vdyArIHRpbWVkZWx0YShkYXlzPW4pCiAg"
    "ICAgICAgICAgIGlmICJzZWMiICBpbiB1bml0OiByZXR1cm4gbm93ICsgdGltZWRlbHRhKHNlY29uZHM9bikKCiAgICAgICAgIyAi"
    "YXQgSEg6TU0iIG9yICJhdCBIOk1NYW0vcG0iCiAgICAgICAgbSA9IHJlLnNlYXJjaCgKICAgICAgICAgICAgciJhdFxzKyhcZHsx"
    "LDJ9KSg/OjooXGR7Mn0pKT9ccyooYW18cG0pPyIsCiAgICAgICAgICAgIGxvdwogICAgICAgICkKICAgICAgICBpZiBtOgogICAg"
    "ICAgICAgICBociAgPSBpbnQobS5ncm91cCgxKSkKICAgICAgICAgICAgbW4gID0gaW50KG0uZ3JvdXAoMikpIGlmIG0uZ3JvdXAo"
    "MikgZWxzZSAwCiAgICAgICAgICAgIGFwbSA9IG0uZ3JvdXAoMykKICAgICAgICAgICAgaWYgYXBtID09ICJwbSIgYW5kIGhyIDwg"
    "MTI6IGhyICs9IDEyCiAgICAgICAgICAgIGlmIGFwbSA9PSAiYW0iIGFuZCBociA9PSAxMjogaHIgPSAwCiAgICAgICAgICAgIGR0"
    "ID0gbm93LnJlcGxhY2UoaG91cj1ociwgbWludXRlPW1uLCBzZWNvbmQ9MCwgbWljcm9zZWNvbmQ9MCkKICAgICAgICAgICAgaWYg"
    "ZHQgPD0gbm93OgogICAgICAgICAgICAgICAgZHQgKz0gdGltZWRlbHRhKGRheXM9MSkKICAgICAgICAgICAgcmV0dXJuIGR0Cgog"
    "ICAgICAgICMgInRvbW9ycm93IGF0IC4uLiIgIChyZWN1cnNlIG9uIHRoZSAiYXQiIHBhcnQpCiAgICAgICAgaWYgInRvbW9ycm93"
    "IiBpbiBsb3c6CiAgICAgICAgICAgIHRvbW9ycm93X3RleHQgPSByZS5zdWIociJ0b21vcnJvdyIsICIiLCBsb3cpLnN0cmlwKCkK"
    "ICAgICAgICAgICAgcmVzdWx0ID0gVGFza01hbmFnZXIucGFyc2VfZHVlX2RhdGV0aW1lKHRvbW9ycm93X3RleHQpCiAgICAgICAg"
    "ICAgIGlmIHJlc3VsdDoKICAgICAgICAgICAgICAgIHJldHVybiByZXN1bHQgKyB0aW1lZGVsdGEoZGF5cz0xKQoKICAgICAgICBy"
    "ZXR1cm4gTm9uZQoKCiMg4pSA4pSAIFJFUVVJUkVNRU5UUy5UWFQgR0VORVJBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgd3JpdGVfcmVxdWlyZW1lbnRzX3R4dCgpIC0+"
    "IE5vbmU6CiAgICAiIiIKICAgIFdyaXRlIHJlcXVpcmVtZW50cy50eHQgbmV4dCB0byB0aGUgZGVjayBmaWxlIG9uIGZpcnN0IHJ1"
    "bi4KICAgIEhlbHBzIHVzZXJzIGluc3RhbGwgYWxsIGRlcGVuZGVuY2llcyB3aXRoIG9uZSBwaXAgY29tbWFuZC4KICAgICIiIgog"
    "ICAgcmVxX3BhdGggPSBQYXRoKENGRy5nZXQoImJhc2VfZGlyIiwgc3RyKFNDUklQVF9ESVIpKSkgLyAicmVxdWlyZW1lbnRzLnR4"
    "dCIKICAgIGlmIHJlcV9wYXRoLmV4aXN0cygpOgogICAgICAgIHJldHVybgoKICAgIGNvbnRlbnQgPSAiIiJcCiMgTW9yZ2FubmEg"
    "RGVjayDigJQgUmVxdWlyZWQgRGVwZW5kZW5jaWVzCiMgSW5zdGFsbCBhbGwgd2l0aDogcGlwIGluc3RhbGwgLXIgcmVxdWlyZW1l"
    "bnRzLnR4dAoKIyBDb3JlIFVJClB5U2lkZTYKCiMgU2NoZWR1bGluZyAoaWRsZSB0aW1lciwgYXV0b3NhdmUsIHJlZmxlY3Rpb24g"
    "Y3ljbGVzKQphcHNjaGVkdWxlcgoKIyBMb2dnaW5nCmxvZ3VydQoKIyBTb3VuZCBwbGF5YmFjayAoV0FWICsgTVAzKQpweWdhbWUK"
    "CiMgRGVza3RvcCBzaG9ydGN1dCBjcmVhdGlvbiAoV2luZG93cyBvbmx5KQpweXdpbjMyCgojIFN5c3RlbSBtb25pdG9yaW5nIChD"
    "UFUsIFJBTSwgZHJpdmVzLCBuZXR3b3JrKQpwc3V0aWwKCiMgSFRUUCByZXF1ZXN0cwpyZXF1ZXN0cwoKIyBHb29nbGUgaW50ZWdy"
    "YXRpb24gKENhbGVuZGFyLCBEcml2ZSwgRG9jcywgR21haWwpCmdvb2dsZS1hcGktcHl0aG9uLWNsaWVudApnb29nbGUtYXV0aC1v"
    "YXV0aGxpYgpnb29nbGUtYXV0aAoKIyDilIDilIAgT3B0aW9uYWwgKGxvY2FsIG1vZGVsIG9ubHkpIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIFVuY29tbWVudCBpZiB1c2luZyBhIGxvY2Fs"
    "IEh1Z2dpbmdGYWNlIG1vZGVsOgojIHRvcmNoCiMgdHJhbnNmb3JtZXJzCiMgYWNjZWxlcmF0ZQoKIyDilIDilIAgT3B0aW9uYWwg"
    "KE5WSURJQSBHUFUgbW9uaXRvcmluZykg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgVW5j"
    "b21tZW50IGlmIHlvdSBoYXZlIGFuIE5WSURJQSBHUFU6CiMgcHludm1sCiIiIgogICAgcmVxX3BhdGgud3JpdGVfdGV4dChjb250"
    "ZW50LCBlbmNvZGluZz0idXRmLTgiKQoKCiMg4pSA4pSAIFBBU1MgNCBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKIyBNZW1vcnksIFNlc3Npb24sIExlc3NvbnNMZWFybmVkLCBUYXNrTWFuYWdlciBhbGwgZGVmaW5lZC4KIyBMU0wgRm9yYmlk"
    "ZGVuIFJ1bGVzZXQgYXV0by1zZWVkZWQgb24gZmlyc3QgcnVuLgojIHJlcXVpcmVtZW50cy50eHQgd3JpdHRlbiBvbiBmaXJzdCBy"
    "dW4uCiMKIyBOZXh0OiBQYXNzIDUg4oCUIFRhYiBDb250ZW50IENsYXNzZXMKIyAoU0xTY2Fuc1RhYiwgU0xDb21tYW5kc1RhYiwg"
    "Sm9iVHJhY2tlclRhYiwgUmVjb3Jkc1RhYiwKIyAgVGFza3NUYWIsIFNlbGZUYWIsIERpYWdub3N0aWNzVGFiKQoKCiMg4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyA1OiBUQUIgQ09OVEVOVCBDTEFTU0VTCiMKIyBUYWJzIGRlZmluZWQgaGVy"
    "ZToKIyAgIFNMU2NhbnNUYWIgICAgICDigJQgZ3JpbW9pcmUtY2FyZCBzdHlsZSwgcmVidWlsdCAoRGVsZXRlIGFkZGVkLCBNb2Rp"
    "ZnkgZml4ZWQsCiMgICAgICAgICAgICAgICAgICAgICBwYXJzZXIgZml4ZWQsIGNvcHktdG8tY2xpcGJvYXJkIHBlciBpdGVtKQoj"
    "ICAgU0xDb21tYW5kc1RhYiAgIOKAlCBnb3RoaWMgdGFibGUsIGNvcHkgY29tbWFuZCB0byBjbGlwYm9hcmQKIyAgIEpvYlRyYWNr"
    "ZXJUYWIgICDigJQgZnVsbCByZWJ1aWxkIGZyb20gc3BlYywgQ1NWL1RTViBleHBvcnQKIyAgIFJlY29yZHNUYWIgICAgICDigJQg"
    "R29vZ2xlIERyaXZlL0RvY3Mgd29ya3NwYWNlCiMgICBUYXNrc1RhYiAgICAgICAg4oCUIHRhc2sgcmVnaXN0cnkgKyBtaW5pIGNh"
    "bGVuZGFyCiMgICBTZWxmVGFiICAgICAgICAg4oCUIGlkbGUgbmFycmF0aXZlIG91dHB1dCArIFBvSSBsaXN0CiMgICBEaWFnbm9z"
    "dGljc1RhYiAg4oCUIGxvZ3VydSBvdXRwdXQgKyBoYXJkd2FyZSByZXBvcnQgKyBqb3VybmFsIGxvYWQgbm90aWNlcwojICAgTGVz"
    "c29uc1RhYiAgICAgIOKAlCBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgKyBjb2RlIGxlc3NvbnMgYnJvd3NlcgojIOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kAoKaW1wb3J0IHJlIGFzIF9yZQoKCiMg4pSA4pSAIFNIQVJFRCBHT1RISUMgVEFCTEUgU1RZTEUg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBfZ290aGljX3RhYmxlX3N0"
    "eWxlKCkgLT4gc3RyOgogICAgcmV0dXJuIGYiIiIKICAgICAgICBRVGFibGVXaWRnZXQge3sKICAgICAgICAgICAgYmFja2dyb3Vu"
    "ZDoge0NfQkcyfTsKICAgICAgICAgICAgY29sb3I6IHtDX0dPTER9OwogICAgICAgICAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19D"
    "UklNU09OX0RJTX07CiAgICAgICAgICAgIGdyaWRsaW5lLWNvbG9yOiB7Q19CT1JERVJ9OwogICAgICAgICAgICBmb250LWZhbWls"
    "eToge0RFQ0tfRk9OVH0sIHNlcmlmOwogICAgICAgICAgICBmb250LXNpemU6IDExcHg7CiAgICAgICAgfX0KICAgICAgICBRVGFi"
    "bGVXaWRnZXQ6Oml0ZW06c2VsZWN0ZWQge3sKICAgICAgICAgICAgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OwogICAgICAg"
    "ICAgICBjb2xvcjoge0NfR09MRF9CUklHSFR9OwogICAgICAgIH19CiAgICAgICAgUVRhYmxlV2lkZ2V0OjppdGVtOmFsdGVybmF0"
    "ZSB7ewogICAgICAgICAgICBiYWNrZ3JvdW5kOiB7Q19CRzN9OwogICAgICAgIH19CiAgICAgICAgUUhlYWRlclZpZXc6OnNlY3Rp"
    "b24ge3sKICAgICAgICAgICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgICAgICAgICAgY29sb3I6IHtDX0dPTER9OwogICAgICAg"
    "ICAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICAgICAgICAgIHBhZGRpbmc6IDRweCA2cHg7CiAgICAg"
    "ICAgICAgIGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7CiAgICAgICAgICAgIGZvbnQtc2l6ZTogMTBweDsKICAgICAg"
    "ICAgICAgZm9udC13ZWlnaHQ6IGJvbGQ7CiAgICAgICAgICAgIGxldHRlci1zcGFjaW5nOiAxcHg7CiAgICAgICAgfX0KICAgICIi"
    "IgoKZGVmIF9nb3RoaWNfYnRuKHRleHQ6IHN0ciwgdG9vbHRpcDogc3RyID0gIiIpIC0+IFFQdXNoQnV0dG9uOgogICAgYnRuID0g"
    "UVB1c2hCdXR0b24odGV4dCkKICAgIGJ0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9E"
    "SU19OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OyBib3JkZXItcmFk"
    "aXVzOiAycHg7ICIKICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsgIgog"
    "ICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDRweCAxMHB4OyBsZXR0ZXItc3BhY2luZzogMXB4OyIKICAgICkK"
    "ICAgIGlmIHRvb2x0aXA6CiAgICAgICAgYnRuLnNldFRvb2xUaXAodG9vbHRpcCkKICAgIHJldHVybiBidG4KCmRlZiBfc2VjdGlv"
    "bl9sYmwodGV4dDogc3RyKSAtPiBRTGFiZWw6CiAgICBsYmwgPSBRTGFiZWwodGV4dCkKICAgIGxibC5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICBmImxl"
    "dHRlci1zcGFjaW5nOiAycHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgKQogICAgcmV0dXJuIGxibAoK"
    "CiMg4pSA4pSAIFNMIFNDQU5TIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU0xTY2Fuc1Rh"
    "YihRV2lkZ2V0KToKICAgICIiIgogICAgU2Vjb25kIExpZmUgYXZhdGFyIHNjYW5uZXIgcmVzdWx0cyBtYW5hZ2VyLgogICAgUmVi"
    "dWlsdCBmcm9tIHNwZWM6CiAgICAgIC0gQ2FyZC9ncmltb2lyZS1lbnRyeSBzdHlsZSBkaXNwbGF5CiAgICAgIC0gQWRkICh3aXRo"
    "IHRpbWVzdGFtcC1hd2FyZSBwYXJzZXIpCiAgICAgIC0gRGlzcGxheSAoY2xlYW4gaXRlbS9jcmVhdG9yIHRhYmxlKQogICAgICAt"
    "IE1vZGlmeSAoZWRpdCBuYW1lLCBkZXNjcmlwdGlvbiwgaW5kaXZpZHVhbCBpdGVtcykKICAgICAgLSBEZWxldGUgKHdhcyBtaXNz"
    "aW5nIOKAlCBub3cgcHJlc2VudCkKICAgICAgLSBSZS1wYXJzZSAod2FzICdSZWZyZXNoJyDigJQgcmUtcnVucyBwYXJzZXIgb24g"
    "c3RvcmVkIHJhdyB0ZXh0KQogICAgICAtIENvcHktdG8tY2xpcGJvYXJkIG9uIGFueSBpdGVtCiAgICAiIiIKCiAgICBkZWYgX19p"
    "bml0X18oc2VsZiwgbWVtb3J5X2RpcjogUGF0aCwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50"
    "KQogICAgICAgIHNlbGYuX3BhdGggICAgPSBjZmdfcGF0aCgic2wiKSAvICJzbF9zY2Fucy5qc29ubCIKICAgICAgICBzZWxmLl9y"
    "ZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zZWxlY3RlZF9pZDogT3B0aW9uYWxbc3RyXSA9IE5vbmUKICAg"
    "ICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwg"
    "NCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBCdXR0b24gYmFyCiAgICAgICAgYmFyID0gUUhCb3hM"
    "YXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hZGQgICAgID0gX2dvdGhpY19idG4oIuKcpiBBZGQiLCAgICAgIkFkZCBhIG5ldyBz"
    "Y2FuIikKICAgICAgICBzZWxmLl9idG5fZGlzcGxheSA9IF9nb3RoaWNfYnRuKCLinacgRGlzcGxheSIsICJTaG93IHNlbGVjdGVk"
    "IHNjYW4gZGV0YWlscyIpCiAgICAgICAgc2VsZi5fYnRuX21vZGlmeSAgPSBfZ290aGljX2J0bigi4pynIE1vZGlmeSIsICAiRWRp"
    "dCBzZWxlY3RlZCBzY2FuIikKICAgICAgICBzZWxmLl9idG5fZGVsZXRlICA9IF9nb3RoaWNfYnRuKCLinJcgRGVsZXRlIiwgICJE"
    "ZWxldGUgc2VsZWN0ZWQgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRuX3JlcGFyc2UgPSBfZ290aGljX2J0bigi4oa7IFJlLXBhcnNl"
    "IiwiUmUtcGFyc2UgcmF3IHRleHQgb2Ygc2VsZWN0ZWQgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRuX2FkZC5jbGlja2VkLmNvbm5l"
    "Y3Qoc2VsZi5fc2hvd19hZGQpCiAgICAgICAgc2VsZi5fYnRuX2Rpc3BsYXkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Nob3dfZGlz"
    "cGxheSkKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5LmNsaWNrZWQuY29ubmVjdChzZWxmLl9zaG93X21vZGlmeSkKICAgICAgICBz"
    "ZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX3JlcGFyc2Uu"
    "Y2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX3JlcGFyc2UpCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0"
    "bl9kaXNwbGF5LCBzZWxmLl9idG5fbW9kaWZ5LAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fZGVsZXRlLCBzZWxmLl9idG5f"
    "cmVwYXJzZSk6CiAgICAgICAgICAgIGJhci5hZGRXaWRnZXQoYikKICAgICAgICBiYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9v"
    "dC5hZGRMYXlvdXQoYmFyKQoKICAgICAgICAjIFN0YWNrOiBsaXN0IHZpZXcgfCBhZGQgZm9ybSB8IGRpc3BsYXkgfCBtb2RpZnkK"
    "ICAgICAgICBzZWxmLl9zdGFjayA9IFFTdGFja2VkV2lkZ2V0KCkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9zdGFjaywg"
    "MSkKCiAgICAgICAgIyDilIDilIAgUEFHRSAwOiBzY2FuIGxpc3QgKGdyaW1vaXJlIGNhcmRzKSDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBwMCA9IFFXaWRnZXQo"
    "KQogICAgICAgIGwwID0gUVZCb3hMYXlvdXQocDApCiAgICAgICAgbDAuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAg"
    "ICAgICAgc2VsZi5fY2FyZF9zY3JvbGwgPSBRU2Nyb2xsQXJlYSgpCiAgICAgICAgc2VsZi5fY2FyZF9zY3JvbGwuc2V0V2lkZ2V0"
    "UmVzaXphYmxlKFRydWUpCiAgICAgICAgc2VsZi5fY2FyZF9zY3JvbGwuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JH"
    "Mn07IGJvcmRlcjogbm9uZTsiKQogICAgICAgIHNlbGYuX2NhcmRfY29udGFpbmVyID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5f"
    "Y2FyZF9sYXlvdXQgICAgPSBRVkJveExheW91dChzZWxmLl9jYXJkX2NvbnRhaW5lcikKICAgICAgICBzZWxmLl9jYXJkX2xheW91"
    "dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBzZWxmLl9jYXJkX2xheW91dC5zZXRTcGFjaW5nKDQpCiAg"
    "ICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuYWRkU3RyZXRjaCgpCiAgICAgICAgc2VsZi5fY2FyZF9zY3JvbGwuc2V0V2lkZ2V0KHNl"
    "bGYuX2NhcmRfY29udGFpbmVyKQogICAgICAgIGwwLmFkZFdpZGdldChzZWxmLl9jYXJkX3Njcm9sbCkKICAgICAgICBzZWxmLl9z"
    "dGFjay5hZGRXaWRnZXQocDApCgogICAgICAgICMg4pSA4pSAIFBBR0UgMTogYWRkIGZvcm0g4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDEgPSBRV2lkZ2V0KCkKICAgICAgICBsMSA9IFFWQm94TGF5"
    "b3V0KHAxKQogICAgICAgIGwxLnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIGwxLnNldFNwYWNpbmcoNCkK"
    "ICAgICAgICBsMS5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgU0NBTiBOQU1FIChhdXRvLWRldGVjdGVkKSIpKQogICAgICAg"
    "IHNlbGYuX2FkZF9uYW1lICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fYWRkX25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJB"
    "dXRvLWRldGVjdGVkIGZyb20gc2NhbiB0ZXh0IikKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX25hbWUpCiAgICAgICAg"
    "bDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIERFU0NSSVBUSU9OIikpCiAgICAgICAgc2VsZi5fYWRkX2Rlc2MgID0gUVRl"
    "eHRFZGl0KCkKICAgICAgICBzZWxmLl9hZGRfZGVzYy5zZXRNYXhpbXVtSGVpZ2h0KDYwKQogICAgICAgIGwxLmFkZFdpZGdldChz"
    "ZWxmLl9hZGRfZGVzYykKICAgICAgICBsMS5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgUkFXIFNDQU4gVEVYVCAocGFzdGUg"
    "aGVyZSkiKSkKICAgICAgICBzZWxmLl9hZGRfcmF3ICAgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2FkZF9yYXcuc2V0UGxh"
    "Y2Vob2xkZXJUZXh0KAogICAgICAgICAgICAiUGFzdGUgdGhlIHJhdyBTZWNvbmQgTGlmZSBzY2FuIG91dHB1dCBoZXJlLlxuIgog"
    "ICAgICAgICAgICAiVGltZXN0YW1wcyBsaWtlIFsxMTo0N10gd2lsbCBiZSB1c2VkIHRvIHNwbGl0IGl0ZW1zIGNvcnJlY3RseS4i"
    "CiAgICAgICAgKQogICAgICAgIGwxLmFkZFdpZGdldChzZWxmLl9hZGRfcmF3LCAxKQogICAgICAgICMgUHJldmlldyBvZiBwYXJz"
    "ZWQgaXRlbXMKICAgICAgICBsMS5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgUEFSU0VEIElURU1TIFBSRVZJRVciKSkKICAg"
    "ICAgICBzZWxmLl9hZGRfcHJldmlldyA9IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNlbGYuX2FkZF9wcmV2aWV3LnNldEhv"
    "cml6b250YWxIZWFkZXJMYWJlbHMoWyJJdGVtIiwgIkNyZWF0b3IiXSkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5ob3Jpem9u"
    "dGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3Ry"
    "ZXRjaCkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAg"
    "ICAgICAgICAgIDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRN"
    "YXhpbXVtSGVpZ2h0KDEyMCkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5"
    "bGUoKSkKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX3ByZXZpZXcpCiAgICAgICAgc2VsZi5fYWRkX3Jhdy50ZXh0Q2hh"
    "bmdlZC5jb25uZWN0KHNlbGYuX3ByZXZpZXdfcGFyc2UpCgogICAgICAgIGJ0bnMxID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHMx"
    "ID0gX2dvdGhpY19idG4oIuKcpiBTYXZlIik7IGMxID0gX2dvdGhpY19idG4oIuKclyBDYW5jZWwiKQogICAgICAgIHMxLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgYzEuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2VsZi5fc3RhY2suc2V0"
    "Q3VycmVudEluZGV4KDApKQogICAgICAgIGJ0bnMxLmFkZFdpZGdldChzMSk7IGJ0bnMxLmFkZFdpZGdldChjMSk7IGJ0bnMxLmFk"
    "ZFN0cmV0Y2goKQogICAgICAgIGwxLmFkZExheW91dChidG5zMSkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDEpCgog"
    "ICAgICAgICMg4pSA4pSAIFBBR0UgMjogZGlzcGxheSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKICAgICAgICBwMiA9IFFXaWRnZXQoKQogICAgICAgIGwyID0gUVZCb3hMYXlvdXQocDIpCiAgICAgICAgbDIu"
    "c2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZi5fZGlzcF9uYW1lICA9IFFMYWJlbCgpCiAgICAgICAg"
    "c2VsZi5fZGlzcF9uYW1lLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTERfQlJJR0hUfTsgZm9udC1z"
    "aXplOiAxM3B4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2Vy"
    "aWY7IgogICAgICAgICkKICAgICAgICBzZWxmLl9kaXNwX2Rlc2MgID0gUUxhYmVsKCkKICAgICAgICBzZWxmLl9kaXNwX2Rlc2Mu"
    "c2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBzZWxmLl9kaXNwX2Rlc2Muc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xv"
    "cjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAg"
    "ICkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDIpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5z"
    "ZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiSXRlbSIsICJDcmVhdG9yIl0pCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5ob3Jp"
    "em9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUu"
    "U3RyZXRjaCkKICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgK"
    "ICAgICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0"
    "U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5zZXRDb250ZXh0TWVudVBv"
    "bGljeSgKICAgICAgICAgICAgUXQuQ29udGV4dE1lbnVQb2xpY3kuQ3VzdG9tQ29udGV4dE1lbnUpCiAgICAgICAgc2VsZi5fZGlz"
    "cF90YWJsZS5jdXN0b21Db250ZXh0TWVudVJlcXVlc3RlZC5jb25uZWN0KAogICAgICAgICAgICBzZWxmLl9pdGVtX2NvbnRleHRf"
    "bWVudSkKCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2Rpc3BfbmFtZSkKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fZGlz"
    "cF9kZXNjKQogICAgICAgIGwyLmFkZFdpZGdldChzZWxmLl9kaXNwX3RhYmxlLCAxKQoKICAgICAgICBjb3B5X2hpbnQgPSBRTGFi"
    "ZWwoIlJpZ2h0LWNsaWNrIGFueSBpdGVtIHRvIGNvcHkgaXQgdG8gY2xpcGJvYXJkLiIpCiAgICAgICAgY29weV9oaW50LnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7"
    "REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBsMi5hZGRXaWRnZXQoY29weV9oaW50KQoKICAgICAgICBiazIg"
    "PSBfZ290aGljX2J0bigi4peAIEJhY2siKQogICAgICAgIGJrMi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9zdGFjay5z"
    "ZXRDdXJyZW50SW5kZXgoMCkpCiAgICAgICAgbDIuYWRkV2lkZ2V0KGJrMikKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQo"
    "cDIpCgogICAgICAgICMg4pSA4pSAIFBBR0UgMzogbW9kaWZ5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAzID0gUVdpZGdldCgpCiAgICAgICAgbDMgPSBRVkJveExheW91dChwMykKICAg"
    "ICAgICBsMy5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICBsMy5zZXRTcGFjaW5nKDQpCiAgICAgICAgbDMu"
    "YWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIE5BTUUiKSkKICAgICAgICBzZWxmLl9tb2RfbmFtZSA9IFFMaW5lRWRpdCgpCiAg"
    "ICAgICAgbDMuYWRkV2lkZ2V0KHNlbGYuX21vZF9uYW1lKQogICAgICAgIGwzLmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBE"
    "RVNDUklQVElPTiIpKQogICAgICAgIHNlbGYuX21vZF9kZXNjID0gUUxpbmVFZGl0KCkKICAgICAgICBsMy5hZGRXaWRnZXQoc2Vs"
    "Zi5fbW9kX2Rlc2MpCiAgICAgICAgbDMuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIElURU1TIChkb3VibGUtY2xpY2sgdG8g"
    "ZWRpdCkiKSkKICAgICAgICBzZWxmLl9tb2RfdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAgICBzZWxmLl9tb2RfdGFi"
    "bGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIkl0ZW0iLCAiQ3JlYXRvciJdKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5o"
    "b3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1v"
    "ZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2Rl"
    "KAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNl"
    "dFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9tb2RfdGFibGUsIDEp"
    "CgogICAgICAgIGJ0bnMzID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHMzID0gX2dvdGhpY19idG4oIuKcpiBTYXZlIik7IGMzID0g"
    "X2dvdGhpY19idG4oIuKclyBDYW5jZWwiKQogICAgICAgIHMzLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19tb2RpZnlfc2F2ZSkK"
    "ICAgICAgICBjMy5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMCkpCiAgICAgICAg"
    "YnRuczMuYWRkV2lkZ2V0KHMzKTsgYnRuczMuYWRkV2lkZ2V0KGMzKTsgYnRuczMuYWRkU3RyZXRjaCgpCiAgICAgICAgbDMuYWRk"
    "TGF5b3V0KGJ0bnMzKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMykKCiAgICAjIOKUgOKUgCBQQVJTRVIg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICBAc3RhdGljbWV0aG9kCiAgICBkZWYgcGFyc2Vfc2Nhbl90ZXh0KHJhdzogc3RyKSAtPiB0dXBsZVtz"
    "dHIsIGxpc3RbZGljdF1dOgogICAgICAgICIiIgogICAgICAgIFBhcnNlIHJhdyBTTCBzY2FuIG91dHB1dCBpbnRvIChhdmF0YXJf"
    "bmFtZSwgaXRlbXMpLgoKICAgICAgICBLRVkgRklYOiBCZWZvcmUgc3BsaXR0aW5nLCBpbnNlcnQgbmV3bGluZXMgYmVmb3JlIGV2"
    "ZXJ5IFtISDpNTV0KICAgICAgICB0aW1lc3RhbXAgc28gc2luZ2xlLWxpbmUgcGFzdGVzIHdvcmsgY29ycmVjdGx5LgoKICAgICAg"
    "ICBFeHBlY3RlZCBmb3JtYXQ6CiAgICAgICAgICAgIFsxMTo0N10gQXZhdGFyTmFtZSdzIHB1YmxpYyBhdHRhY2htZW50czoKICAg"
    "ICAgICAgICAgWzExOjQ3XSAuOiBJdGVtIE5hbWUgW0F0dGFjaG1lbnRdIENSRUFUT1I6IENyZWF0b3JOYW1lIFsxMTo0N10gLi4u"
    "CiAgICAgICAgIiIiCiAgICAgICAgaWYgbm90IHJhdy5zdHJpcCgpOgogICAgICAgICAgICByZXR1cm4gIlVOS05PV04iLCBbXQoK"
    "ICAgICAgICAjIOKUgOKUgCBTdGVwIDE6IG5vcm1hbGl6ZSDigJQgaW5zZXJ0IG5ld2xpbmVzIGJlZm9yZSB0aW1lc3RhbXBzIOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgICAgIG5vcm1hbGl6ZWQgPSBfcmUuc3ViKHInXHMqKFxbXGR7MSwyfTpcZHsyfVxdKScsIHIn"
    "XG5cMScsIHJhdykKICAgICAgICBsaW5lcyA9IFtsLnN0cmlwKCkgZm9yIGwgaW4gbm9ybWFsaXplZC5zcGxpdGxpbmVzKCkgaWYg"
    "bC5zdHJpcCgpXQoKICAgICAgICAjIOKUgOKUgCBTdGVwIDI6IGV4dHJhY3QgYXZhdGFyIG5hbWUg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACiAgICAgICAgYXZhdGFyX25hbWUgPSAiVU5LTk9XTiIKICAgICAgICBmb3IgbGluZSBpbiBsaW5lczoKICAgICAgICAgICAg"
    "IyAiQXZhdGFyTmFtZSdzIHB1YmxpYyBhdHRhY2htZW50cyIgb3Igc2ltaWxhcgogICAgICAgICAgICBtID0gX3JlLnNlYXJjaCgK"
    "ICAgICAgICAgICAgICAgIHIiKFx3W1x3XHNdKz8pJ3NccytwdWJsaWNccythdHRhY2htZW50cyIsCiAgICAgICAgICAgICAgICBs"
    "aW5lLCBfcmUuSQogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIG06CiAgICAgICAgICAgICAgICBhdmF0YXJfbmFtZSA9IG0u"
    "Z3JvdXAoMSkuc3RyaXAoKQogICAgICAgICAgICAgICAgYnJlYWsKCiAgICAgICAgIyDilIDilIAgU3RlcCAzOiBleHRyYWN0IGl0"
    "ZW1zIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGl0ZW1zID0gW10KICAgICAgICBmb3Ig"
    "bGluZSBpbiBsaW5lczoKICAgICAgICAgICAgIyBTdHJpcCBsZWFkaW5nIHRpbWVzdGFtcAogICAgICAgICAgICBjb250ZW50ID0g"
    "X3JlLnN1YihyJ15cW1xkezEsMn06XGR7Mn1cXVxzKicsICcnLCBsaW5lKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIG5vdCBjb250"
    "ZW50OgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgIyBTa2lwIGhlYWRlciBsaW5lcwogICAgICAgICAgICBp"
    "ZiAiJ3MgcHVibGljIGF0dGFjaG1lbnRzIiBpbiBjb250ZW50Lmxvd2VyKCk6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAg"
    "ICAgICAgICBpZiBjb250ZW50Lmxvd2VyKCkuc3RhcnRzd2l0aCgib2JqZWN0Iik6CiAgICAgICAgICAgICAgICBjb250aW51ZQog"
    "ICAgICAgICAgICAjIFNraXAgZGl2aWRlciBsaW5lcyDigJQgbGluZXMgdGhhdCBhcmUgbW9zdGx5IG9uZSByZXBlYXRlZCBjaGFy"
    "YWN0ZXIKICAgICAgICAgICAgIyBlLmcuIOKWguKWguKWguKWguKWguKWguKWguKWguKWguKWguKWguKWgiBvciDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZAgb3Ig4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAg"
    "ICAgIHN0cmlwcGVkID0gY29udGVudC5zdHJpcCgiLjogIikKICAgICAgICAgICAgaWYgc3RyaXBwZWQgYW5kIGxlbihzZXQoc3Ry"
    "aXBwZWQpKSA8PSAyOgogICAgICAgICAgICAgICAgY29udGludWUgICMgb25lIG9yIHR3byB1bmlxdWUgY2hhcnMgPSBkaXZpZGVy"
    "IGxpbmUKCiAgICAgICAgICAgICMgVHJ5IHRvIGV4dHJhY3QgQ1JFQVRPUjogZmllbGQKICAgICAgICAgICAgY3JlYXRvciA9ICJV"
    "TktOT1dOIgogICAgICAgICAgICBpdGVtX25hbWUgPSBjb250ZW50CgogICAgICAgICAgICBjcmVhdG9yX21hdGNoID0gX3JlLnNl"
    "YXJjaCgKICAgICAgICAgICAgICAgIHInQ1JFQVRPUjpccyooW1x3XHNdKz8pKD86XHMqXFt8JCknLCBjb250ZW50LCBfcmUuSQog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIGlmIGNyZWF0b3JfbWF0Y2g6CiAgICAgICAgICAgICAgICBjcmVhdG9yICAgPSBjcmVh"
    "dG9yX21hdGNoLmdyb3VwKDEpLnN0cmlwKCkKICAgICAgICAgICAgICAgIGl0ZW1fbmFtZSA9IGNvbnRlbnRbOmNyZWF0b3JfbWF0"
    "Y2guc3RhcnQoKV0uc3RyaXAoKQoKICAgICAgICAgICAgIyBTdHJpcCBhdHRhY2htZW50IHBvaW50IHN1ZmZpeGVzIGxpa2UgW0xl"
    "ZnRfRm9vdF0KICAgICAgICAgICAgaXRlbV9uYW1lID0gX3JlLnN1YihyJ1xzKlxbW1x3XHNfXStcXScsICcnLCBpdGVtX25hbWUp"
    "LnN0cmlwKCkKICAgICAgICAgICAgaXRlbV9uYW1lID0gaXRlbV9uYW1lLnN0cmlwKCIuOiAiKQoKICAgICAgICAgICAgaWYgaXRl"
    "bV9uYW1lIGFuZCBsZW4oaXRlbV9uYW1lKSA+IDE6CiAgICAgICAgICAgICAgICBpdGVtcy5hcHBlbmQoeyJpdGVtIjogaXRlbV9u"
    "YW1lLCAiY3JlYXRvciI6IGNyZWF0b3J9KQoKICAgICAgICByZXR1cm4gYXZhdGFyX25hbWUsIGl0ZW1zCgogICAgIyDilIDilIAg"
    "Q0FSRCBSRU5ERVJJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICBkZWYgX2J1aWxkX2NhcmRzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBDbGVhciBleGlzdGluZyBjYXJk"
    "cyAoa2VlcCBzdHJldGNoKQogICAgICAgIHdoaWxlIHNlbGYuX2NhcmRfbGF5b3V0LmNvdW50KCkgPiAxOgogICAgICAgICAgICBp"
    "dGVtID0gc2VsZi5fY2FyZF9sYXlvdXQudGFrZUF0KDApCiAgICAgICAgICAgIGlmIGl0ZW0ud2lkZ2V0KCk6CiAgICAgICAgICAg"
    "ICAgICBpdGVtLndpZGdldCgpLmRlbGV0ZUxhdGVyKCkKCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAg"
    "ICAgICBjYXJkID0gc2VsZi5fbWFrZV9jYXJkKHJlYykKICAgICAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuaW5zZXJ0V2lkZ2V0"
    "KAogICAgICAgICAgICAgICAgc2VsZi5fY2FyZF9sYXlvdXQuY291bnQoKSAtIDEsIGNhcmQKICAgICAgICAgICAgKQoKICAgIGRl"
    "ZiBfbWFrZV9jYXJkKHNlbGYsIHJlYzogZGljdCkgLT4gUVdpZGdldDoKICAgICAgICBjYXJkID0gUUZyYW1lKCkKICAgICAgICBp"
    "c19zZWxlY3RlZCA9IHJlYy5nZXQoInJlY29yZF9pZCIpID09IHNlbGYuX3NlbGVjdGVkX2lkCiAgICAgICAgY2FyZC5zZXRTdHls"
    "ZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHsnIzFhMGExMCcgaWYgaXNfc2VsZWN0ZWQgZWxzZSBDX0JHM307ICIK"
    "ICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19CT1JERVJ9OyAi"
    "CiAgICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyBwYWRkaW5nOiAycHg7IgogICAgICAgICkKICAgICAgICBsYXlvdXQg"
    "PSBRSEJveExheW91dChjYXJkKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoOCwgNiwgOCwgNikKCiAgICAgICAg"
    "bmFtZV9sYmwgPSBRTGFiZWwocmVjLmdldCgibmFtZSIsICJVTktOT1dOIikpCiAgICAgICAgbmFtZV9sYmwuc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRF9CUklHSFQgaWYgaXNfc2VsZWN0ZWQgZWxzZSBDX0dPTER9OyAiCiAgICAg"
    "ICAgICAgIGYiZm9udC1zaXplOiAxMXB4OyBmb250LXdlaWdodDogYm9sZDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJp"
    "ZjsiCiAgICAgICAgKQoKICAgICAgICBjb3VudCA9IGxlbihyZWMuZ2V0KCJpdGVtcyIsIFtdKSkKICAgICAgICBjb3VudF9sYmwg"
    "PSBRTGFiZWwoZiJ7Y291bnR9IGl0ZW1zIikKICAgICAgICBjb3VudF9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJj"
    "b2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTBweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAg"
    "ICAgKQoKICAgICAgICBkYXRlX2xibCA9IFFMYWJlbChyZWMuZ2V0KCJjcmVhdGVkX2F0IiwgIiIpWzoxMF0pCiAgICAgICAgZGF0"
    "ZV9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsgZm9u"
    "dC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KG5hbWVfbGJs"
    "KQogICAgICAgIGxheW91dC5hZGRTdHJldGNoKCkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGNvdW50X2xibCkKICAgICAgICBs"
    "YXlvdXQuYWRkU3BhY2luZygxMikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGRhdGVfbGJsKQoKICAgICAgICAjIENsaWNrIHRv"
    "IHNlbGVjdAogICAgICAgIHJlY19pZCA9IHJlYy5nZXQoInJlY29yZF9pZCIsICIiKQogICAgICAgIGNhcmQubW91c2VQcmVzc0V2"
    "ZW50ID0gbGFtYmRhIGUsIHJpZD1yZWNfaWQ6IHNlbGYuX3NlbGVjdF9jYXJkKHJpZCkKICAgICAgICByZXR1cm4gY2FyZAoKICAg"
    "IGRlZiBfc2VsZWN0X2NhcmQoc2VsZiwgcmVjb3JkX2lkOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQg"
    "PSByZWNvcmRfaWQKICAgICAgICBzZWxmLl9idWlsZF9jYXJkcygpICAjIFJlYnVpbGQgdG8gc2hvdyBzZWxlY3Rpb24gaGlnaGxp"
    "Z2h0CgogICAgZGVmIF9zZWxlY3RlZF9yZWNvcmQoc2VsZikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgcmV0dXJuIG5leHQo"
    "CiAgICAgICAgICAgIChyIGZvciByIGluIHNlbGYuX3JlY29yZHMKICAgICAgICAgICAgIGlmIHIuZ2V0KCJyZWNvcmRfaWQiKSA9"
    "PSBzZWxmLl9zZWxlY3RlZF9pZCksCiAgICAgICAgICAgIE5vbmUKICAgICAgICApCgogICAgIyDilIDilIAgQUNUSU9OUyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRfanNv"
    "bmwoc2VsZi5fcGF0aCkKICAgICAgICAjIEVuc3VyZSByZWNvcmRfaWQgZmllbGQgZXhpc3RzCiAgICAgICAgY2hhbmdlZCA9IEZh"
    "bHNlCiAgICAgICAgZm9yIHIgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgaWYgbm90IHIuZ2V0KCJyZWNvcmRfaWQiKToK"
    "ICAgICAgICAgICAgICAgIHJbInJlY29yZF9pZCJdID0gci5nZXQoImlkIikgb3Igc3RyKHV1aWQudXVpZDQoKSkKICAgICAgICAg"
    "ICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgaWYgY2hhbmdlZDoKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0"
    "aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLl9idWlsZF9jYXJkcygpCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVu"
    "dEluZGV4KDApCgogICAgZGVmIF9wcmV2aWV3X3BhcnNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmF3ID0gc2VsZi5fYWRkX3Jh"
    "dy50b1BsYWluVGV4dCgpCiAgICAgICAgbmFtZSwgaXRlbXMgPSBzZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcpCiAgICAgICAgc2Vs"
    "Zi5fYWRkX25hbWUuc2V0UGxhY2Vob2xkZXJUZXh0KG5hbWUpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0Um93Q291bnQo"
    "MCkKICAgICAgICBmb3IgaXQgaW4gaXRlbXNbOjIwXTogICMgcHJldmlldyBmaXJzdCAyMAogICAgICAgICAgICByID0gc2VsZi5f"
    "YWRkX3ByZXZpZXcucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5pbnNlcnRSb3cocikKICAgICAgICAg"
    "ICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0SXRlbShyLCAwLCBRVGFibGVXaWRnZXRJdGVtKGl0WyJpdGVtIl0pKQogICAgICAgICAg"
    "ICBzZWxmLl9hZGRfcHJldmlldy5zZXRJdGVtKHIsIDEsIFFUYWJsZVdpZGdldEl0ZW0oaXRbImNyZWF0b3IiXSkpCgogICAgZGVm"
    "IF9zaG93X2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2FkZF9uYW1lLmNsZWFyKCkKICAgICAgICBzZWxmLl9hZGRf"
    "bmFtZS5zZXRQbGFjZWhvbGRlclRleHQoIkF1dG8tZGV0ZWN0ZWQgZnJvbSBzY2FuIHRleHQiKQogICAgICAgIHNlbGYuX2FkZF9k"
    "ZXNjLmNsZWFyKCkKICAgICAgICBzZWxmLl9hZGRfcmF3LmNsZWFyKCkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRSb3dD"
    "b3VudCgwKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgxKQoKICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgcmF3ICA9IHNlbGYuX2FkZF9yYXcudG9QbGFpblRleHQoKQogICAgICAgIG5hbWUsIGl0ZW1zID0gc2VsZi5w"
    "YXJzZV9zY2FuX3RleHQocmF3KQogICAgICAgIG92ZXJyaWRlX25hbWUgPSBzZWxmLl9hZGRfbmFtZS50ZXh0KCkuc3RyaXAoKQog"
    "ICAgICAgIG5vdyAgPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgIHJlY29yZCA9IHsKICAg"
    "ICAgICAgICAgImlkIjogICAgICAgICAgc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAgICJyZWNvcmRfaWQiOiAgIHN0cih1"
    "dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAibmFtZSI6ICAgICAgICBvdmVycmlkZV9uYW1lIG9yIG5hbWUsCiAgICAgICAgICAg"
    "ICJkZXNjcmlwdGlvbiI6IHNlbGYuX2FkZF9kZXNjLnRvUGxhaW5UZXh0KClbOjI0NF0sCiAgICAgICAgICAgICJpdGVtcyI6ICAg"
    "ICAgIGl0ZW1zLAogICAgICAgICAgICAicmF3X3RleHQiOiAgICByYXcsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogIG5vdywK"
    "ICAgICAgICAgICAgInVwZGF0ZWRfYXQiOiAgbm93LAogICAgICAgIH0KICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChyZWNv"
    "cmQpCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLl9zZWxlY3RlZF9p"
    "ZCA9IHJlY29yZFsicmVjb3JkX2lkIl0KICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2hvd19kaXNwbGF5KHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAg"
    "ICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiU0wgU2NhbnMiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAiU2VsZWN0IGEgc2NhbiB0byBkaXNwbGF5LiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2Rpc3Bf"
    "bmFtZS5zZXRUZXh0KGYi4p2nIHtyZWMuZ2V0KCduYW1lJywnJyl9IikKICAgICAgICBzZWxmLl9kaXNwX2Rlc2Muc2V0VGV4dChy"
    "ZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBm"
    "b3IgaXQgaW4gcmVjLmdldCgiaXRlbXMiLFtdKToKICAgICAgICAgICAgciA9IHNlbGYuX2Rpc3BfdGFibGUucm93Q291bnQoKQog"
    "ICAgICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldEl0"
    "ZW0ociwgMCwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oaXQuZ2V0KCJpdGVtIiwiIikpKQogICAgICAgICAgICBz"
    "ZWxmLl9kaXNwX3RhYmxlLnNldEl0ZW0ociwgMSwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oaXQuZ2V0KCJjcmVh"
    "dG9yIiwiVU5LTk9XTiIpKSkKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMikKCiAgICBkZWYgX2l0ZW1fY29u"
    "dGV4dF9tZW51KHNlbGYsIHBvcykgLT4gTm9uZToKICAgICAgICBpZHggPSBzZWxmLl9kaXNwX3RhYmxlLmluZGV4QXQocG9zKQog"
    "ICAgICAgIGlmIG5vdCBpZHguaXNWYWxpZCgpOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpdGVtX3RleHQgID0gKHNlbGYu"
    "X2Rpc3BfdGFibGUuaXRlbShpZHgucm93KCksIDApIG9yCiAgICAgICAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKCIi"
    "KSkudGV4dCgpCiAgICAgICAgY3JlYXRvciAgICA9IChzZWxmLl9kaXNwX3RhYmxlLml0ZW0oaWR4LnJvdygpLCAxKSBvcgogICAg"
    "ICAgICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAgIGZyb20gUHlTaWRlNi5RdFdpZGdl"
    "dHMgaW1wb3J0IFFNZW51CiAgICAgICAgbWVudSA9IFFNZW51KHNlbGYpCiAgICAgICAgbWVudS5zZXRTdHlsZVNoZWV0KAogICAg"
    "ICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4"
    "IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIGFfaXRlbSAgICA9IG1lbnUuYWRkQWN0aW9uKCJDb3B5"
    "IEl0ZW0gTmFtZSIpCiAgICAgICAgYV9jcmVhdG9yID0gbWVudS5hZGRBY3Rpb24oIkNvcHkgQ3JlYXRvciIpCiAgICAgICAgYV9i"
    "b3RoICAgID0gbWVudS5hZGRBY3Rpb24oIkNvcHkgQm90aCIpCiAgICAgICAgYWN0aW9uID0gbWVudS5leGVjKHNlbGYuX2Rpc3Bf"
    "dGFibGUudmlld3BvcnQoKS5tYXBUb0dsb2JhbChwb3MpKQogICAgICAgIGNiID0gUUFwcGxpY2F0aW9uLmNsaXBib2FyZCgpCiAg"
    "ICAgICAgaWYgYWN0aW9uID09IGFfaXRlbTogICAgY2Iuc2V0VGV4dChpdGVtX3RleHQpCiAgICAgICAgZWxpZiBhY3Rpb24gPT0g"
    "YV9jcmVhdG9yOiBjYi5zZXRUZXh0KGNyZWF0b3IpCiAgICAgICAgZWxpZiBhY3Rpb24gPT0gYV9ib3RoOiAgY2Iuc2V0VGV4dChm"
    "IntpdGVtX3RleHR9IOKAlCB7Y3JlYXRvcn0iKQoKICAgIGRlZiBfc2hvd19tb2RpZnkoc2VsZikgLT4gTm9uZToKICAgICAgICBy"
    "ZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCByZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94Lmlu"
    "Zm9ybWF0aW9uKHNlbGYsICJTTCBTY2FucyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBz"
    "Y2FuIHRvIG1vZGlmeS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9tb2RfbmFtZS5zZXRUZXh0KHJlYy5nZXQo"
    "Im5hbWUiLCIiKSkKICAgICAgICBzZWxmLl9tb2RfZGVzYy5zZXRUZXh0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikpCiAgICAg"
    "ICAgc2VsZi5fbW9kX3RhYmxlLnNldFJvd0NvdW50KDApCiAgICAgICAgZm9yIGl0IGluIHJlYy5nZXQoIml0ZW1zIixbXSk6CiAg"
    "ICAgICAgICAgIHIgPSBzZWxmLl9tb2RfdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl9tb2RfdGFibGUuaW5zZXJ0"
    "Um93KHIpCiAgICAgICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRn"
    "ZXRJdGVtKGl0LmdldCgiaXRlbSIsIiIpKSkKICAgICAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldEl0ZW0ociwgMSwKICAgICAg"
    "ICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oaXQuZ2V0KCJjcmVhdG9yIiwiVU5LTk9XTiIpKSkKICAgICAgICBzZWxmLl9zdGFj"
    "ay5zZXRDdXJyZW50SW5kZXgoMykKCiAgICBkZWYgX2RvX21vZGlmeV9zYXZlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVjID0g"
    "c2VsZi5fc2VsZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAgICByZXR1cm4KICAgICAgICByZWNb"
    "Im5hbWUiXSAgICAgICAgPSBzZWxmLl9tb2RfbmFtZS50ZXh0KCkuc3RyaXAoKSBvciAiVU5LTk9XTiIKICAgICAgICByZWNbImRl"
    "c2NyaXB0aW9uIl0gPSBzZWxmLl9tb2RfZGVzYy50ZXh0KClbOjI0NF0KICAgICAgICBpdGVtcyA9IFtdCiAgICAgICAgZm9yIGkg"
    "aW4gcmFuZ2Uoc2VsZi5fbW9kX3RhYmxlLnJvd0NvdW50KCkpOgogICAgICAgICAgICBpdCAgPSAoc2VsZi5fbW9kX3RhYmxlLml0"
    "ZW0oaSwwKSBvciBRVGFibGVXaWRnZXRJdGVtKCIiKSkudGV4dCgpCiAgICAgICAgICAgIGNyICA9IChzZWxmLl9tb2RfdGFibGUu"
    "aXRlbShpLDEpIG9yIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICAgICAgaXRlbXMuYXBwZW5kKHsiaXRlbSI6"
    "IGl0LnN0cmlwKCkgb3IgIlVOS05PV04iLAogICAgICAgICAgICAgICAgICAgICAgICAgICJjcmVhdG9yIjogY3Iuc3RyaXAoKSBv"
    "ciAiVU5LTk9XTiJ9KQogICAgICAgIHJlY1siaXRlbXMiXSAgICAgID0gaXRlbXMKICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSA9"
    "IGRhdGV0aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2Vs"
    "Zi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAgICBRTWVzc2FnZUJv"
    "eC5pbmZvcm1hdGlvbihzZWxmLCAiU0wgU2NhbnMiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiU2VsZWN0"
    "IGEgc2NhbiB0byBkZWxldGUuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgbmFtZSA9IHJlYy5nZXQoIm5hbWUiLCJ0aGlz"
    "IHNjYW4iKQogICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgIHNlbGYsICJEZWxldGUgU2Nh"
    "biIsCiAgICAgICAgICAgIGYiRGVsZXRlICd7bmFtZX0nPyBUaGlzIGNhbm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAgICAgUU1l"
    "c3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICApCiAgICAg"
    "ICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICBzZWxmLl9yZWNvcmRzID0g"
    "W3IgZm9yIHIgaW4gc2VsZi5fcmVjb3JkcwogICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHIuZ2V0KCJyZWNvcmRfaWQi"
    "KSAhPSBzZWxmLl9zZWxlY3RlZF9pZF0KICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykK"
    "ICAgICAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQgPSBOb25lCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9k"
    "b19yZXBhcnNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBu"
    "b3QgcmVjOgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiU0wgU2NhbnMiLAogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAiU2VsZWN0IGEgc2NhbiB0byByZS1wYXJzZS4iKQogICAgICAgICAgICByZXR1cm4KICAg"
    "ICAgICByYXcgPSByZWMuZ2V0KCJyYXdfdGV4dCIsIiIpCiAgICAgICAgaWYgbm90IHJhdzoKICAgICAgICAgICAgUU1lc3NhZ2VC"
    "b3guaW5mb3JtYXRpb24oc2VsZiwgIlJlLXBhcnNlIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIk5vIHJh"
    "dyB0ZXh0IHN0b3JlZCBmb3IgdGhpcyBzY2FuLiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIG5hbWUsIGl0ZW1zID0gc2Vs"
    "Zi5wYXJzZV9zY2FuX3RleHQocmF3KQogICAgICAgIHJlY1siaXRlbXMiXSAgICAgID0gaXRlbXMKICAgICAgICByZWNbIm5hbWUi"
    "XSAgICAgICA9IHJlY1sibmFtZSJdIG9yIG5hbWUKICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSA9IGRhdGV0aW1lLm5vdyh0aW1l"
    "em9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAg"
    "ICBzZWxmLnJlZnJlc2goKQogICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJSZS1wYXJzZWQiLAogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIGYiRm91bmQge2xlbihpdGVtcyl9IGl0ZW1zLiIpCgoKIyDilIDilIAgU0wgQ09NTUFO"
    "RFMgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTTENvbW1hbmRzVGFiKFFXaWRnZXQpOgogICAgIiIiCiAg"
    "ICBTZWNvbmQgTGlmZSBjb21tYW5kIHJlZmVyZW5jZSB0YWJsZS4KICAgIEdvdGhpYyB0YWJsZSBzdHlsaW5nLiBDb3B5IGNvbW1h"
    "bmQgdG8gY2xpcGJvYXJkIGJ1dHRvbiBwZXIgcm93LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25l"
    "KToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRoICAgID0gY2ZnX3BhdGgoInNsIikg"
    "LyAic2xfY29tbWFuZHMuanNvbmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5f"
    "c2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAg"
    "ICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGJhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fYWRkICAg"
    "ID0gX2dvdGhpY19idG4oIuKcpiBBZGQiKQogICAgICAgIHNlbGYuX2J0bl9tb2RpZnkgPSBfZ290aGljX2J0bigi4pynIE1vZGlm"
    "eSIpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSA9IF9nb3RoaWNfYnRuKCLinJcgRGVsZXRlIikKICAgICAgICBzZWxmLl9idG5f"
    "Y29weSAgID0gX2dvdGhpY19idG4oIuKniSBDb3B5IENvbW1hbmQiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIkNvcHkgc2VsZWN0ZWQgY29tbWFuZCB0byBjbGlwYm9hcmQiKQogICAgICAgIHNlbGYuX2J0bl9yZWZyZXNoPSBfZ290"
    "aGljX2J0bigi4oa7IFJlZnJlc2giKQogICAgICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkK"
    "ICAgICAgICBzZWxmLl9idG5fbW9kaWZ5LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19tb2RpZnkpCiAgICAgICAgc2VsZi5fYnRu"
    "X2RlbGV0ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl9jb3B5LmNsaWNrZWQuY29u"
    "bmVjdChzZWxmLl9jb3B5X2NvbW1hbmQpCiAgICAgICAgc2VsZi5fYnRuX3JlZnJlc2guY2xpY2tlZC5jb25uZWN0KHNlbGYucmVm"
    "cmVzaCkKICAgICAgICBmb3IgYiBpbiAoc2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRuX21vZGlmeSwgc2VsZi5fYnRuX2RlbGV0ZSwK"
    "ICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX2NvcHksIHNlbGYuX2J0bl9yZWZyZXNoKToKICAgICAgICAgICAgYmFyLmFkZFdp"
    "ZGdldChiKQogICAgICAgIGJhci5hZGRTdHJldGNoKCkKICAgICAgICByb290LmFkZExheW91dChiYXIpCgogICAgICAgIHNlbGYu"
    "X3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDIpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhb"
    "IkNvbW1hbmQiLCAiRGVzY3JpcHRpb24iXSkKICAgICAgICBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlv"
    "blJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90"
    "YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJWaWV3LlJl"
    "c2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAgICAgICAgUUFi"
    "c3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLl90YWJsZS5zZXRBbHRlcm5h"
    "dGluZ1Jvd0NvbG9ycyhUcnVlKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgp"
    "KQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlLCAxKQoKICAgICAgICBoaW50ID0gUUxhYmVsKAogICAgICAgICAg"
    "ICAiU2VsZWN0IGEgcm93IGFuZCBjbGljayDip4kgQ29weSBDb21tYW5kIHRvIGNvcHkganVzdCB0aGUgY29tbWFuZCB0ZXh0LiIK"
    "ICAgICAgICApCiAgICAgICAgaGludC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZv"
    "bnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRX"
    "aWRnZXQoaGludCkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pz"
    "b25sKHNlbGYuX3BhdGgpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNlbGYu"
    "X3JlY29yZHM6CiAgICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLmlu"
    "c2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRn"
    "ZXRJdGVtKHJlYy5nZXQoImNvbW1hbmQiLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMSwKICAgICAg"
    "ICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkpCgogICAgZGVmIF9jb3B5X2NvbW1h"
    "bmQoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiByb3cgPCAw"
    "OgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpdGVtID0gc2VsZi5fdGFibGUuaXRlbShyb3csIDApCiAgICAgICAgaWYgaXRl"
    "bToKICAgICAgICAgICAgUUFwcGxpY2F0aW9uLmNsaXBib2FyZCgpLnNldFRleHQoaXRlbS50ZXh0KCkpCgogICAgZGVmIF9kb19h"
    "ZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxnLnNldFdpbmRvd1RpdGxlKCJB"
    "ZGQgQ29tbWFuZCIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09M"
    "RH07IikKICAgICAgICBmb3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAgIGNtZCAgPSBRTGluZUVkaXQoKTsgZGVzYyA9IFFM"
    "aW5lRWRpdCgpCiAgICAgICAgZm9ybS5hZGRSb3coIkNvbW1hbmQ6IiwgY21kKQogICAgICAgIGZvcm0uYWRkUm93KCJEZXNjcmlw"
    "dGlvbjoiLCBkZXNjKQogICAgICAgIGJ0bnMgPSBRSEJveExheW91dCgpCiAgICAgICAgb2sgPSBfZ290aGljX2J0bigiU2F2ZSIp"
    "OyBjeCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIG9rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KTsgY3guY2xp"
    "Y2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5zLmFkZFdpZGdldChjeCkKICAg"
    "ICAgICBmb3JtLmFkZFJvdyhidG5zKQogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVk"
    "OgogICAgICAgICAgICBub3cgPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgICAgICByZWMg"
    "PSB7CiAgICAgICAgICAgICAgICAiaWQiOiAgICAgICAgICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgICAgICJjb21t"
    "YW5kIjogICAgIGNtZC50ZXh0KCkuc3RyaXAoKVs6MjQ0XSwKICAgICAgICAgICAgICAgICJkZXNjcmlwdGlvbiI6IGRlc2MudGV4"
    "dCgpLnN0cmlwKClbOjI0NF0sCiAgICAgICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICBub3csICJ1cGRhdGVkX2F0Ijogbm93LAog"
    "ICAgICAgICAgICB9CiAgICAgICAgICAgIGlmIHJlY1siY29tbWFuZCJdOgogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5h"
    "cHBlbmQocmVjKQogICAgICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAg"
    "ICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19tb2RpZnkoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxm"
    "Ll90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiByb3cgPCAwIG9yIHJvdyA+PSBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgIHJlYyA9IHNlbGYuX3JlY29yZHNbcm93XQogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikK"
    "ICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIk1vZGlmeSBDb21tYW5kIikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJh"
    "Y2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGZvcm0gPSBRRm9ybUxheW91dChkbGcpCiAgICAg"
    "ICAgY21kICA9IFFMaW5lRWRpdChyZWMuZ2V0KCJjb21tYW5kIiwiIikpCiAgICAgICAgZGVzYyA9IFFMaW5lRWRpdChyZWMuZ2V0"
    "KCJkZXNjcmlwdGlvbiIsIiIpKQogICAgICAgIGZvcm0uYWRkUm93KCJDb21tYW5kOiIsIGNtZCkKICAgICAgICBmb3JtLmFkZFJv"
    "dygiRGVzY3JpcHRpb246IiwgZGVzYykKICAgICAgICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19i"
    "dG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2Vw"
    "dCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRn"
    "ZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRucykKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29k"
    "ZS5BY2NlcHRlZDoKICAgICAgICAgICAgcmVjWyJjb21tYW5kIl0gICAgID0gY21kLnRleHQoKS5zdHJpcCgpWzoyNDRdCiAgICAg"
    "ICAgICAgIHJlY1siZGVzY3JpcHRpb24iXSA9IGRlc2MudGV4dCgpLnN0cmlwKClbOjI0NF0KICAgICAgICAgICAgcmVjWyJ1cGRh"
    "dGVkX2F0Il0gID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAgd3JpdGVfanNvbmwo"
    "c2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIHJvdyA8IDAgb3Ig"
    "cm93ID49IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgY21kID0gc2VsZi5fcmVjb3Jkc1ty"
    "b3ddLmdldCgiY29tbWFuZCIsInRoaXMgY29tbWFuZCIpCiAgICAgICAgcmVwbHkgPSBRTWVzc2FnZUJveC5xdWVzdGlvbigKICAg"
    "ICAgICAgICAgc2VsZiwgIkRlbGV0ZSIsIGYiRGVsZXRlICd7Y21kfSc/IiwKICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRh"
    "cmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uTm8KICAgICAgICApCiAgICAgICAgaWYgcmVwbHkgPT0g"
    "UU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICBzZWxmLl9yZWNvcmRzLnBvcChyb3cpCiAgICAgICAg"
    "ICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgoKIyDi"
    "lIDilIAgSk9CIFRSQUNLRVIgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBKb2JUcmFja2VyVGFiKFFXaWRn"
    "ZXQpOgogICAgIiIiCiAgICBKb2IgYXBwbGljYXRpb24gdHJhY2tpbmcuIEZ1bGwgcmVidWlsZCBmcm9tIHNwZWMuCiAgICBGaWVs"
    "ZHM6IENvbXBhbnksIEpvYiBUaXRsZSwgRGF0ZSBBcHBsaWVkLCBMaW5rLCBTdGF0dXMsIE5vdGVzLgogICAgTXVsdGktc2VsZWN0"
    "IGhpZGUvdW5oaWRlL2RlbGV0ZS4gQ1NWIGFuZCBUU1YgZXhwb3J0LgogICAgSGlkZGVuIHJvd3MgPSBjb21wbGV0ZWQvcmVqZWN0"
    "ZWQg4oCUIHN0aWxsIHN0b3JlZCwganVzdCBub3Qgc2hvd24uCiAgICAiIiIKCiAgICBDT0xVTU5TID0gWyJDb21wYW55IiwgIkpv"
    "YiBUaXRsZSIsICJEYXRlIEFwcGxpZWQiLAogICAgICAgICAgICAgICAiTGluayIsICJTdGF0dXMiLCAiTm90ZXMiXQoKICAgIGRl"
    "ZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2Vs"
    "Zi5fcGF0aCAgICA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gImpvYl90cmFja2VyLmpzb25sIgogICAgICAgIHNlbGYuX3JlY29y"
    "ZHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3Nob3dfaGlkZGVuID0gRmFsc2UKICAgICAgICBzZWxmLl9zZXR1cF91"
    "aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9"
    "IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290"
    "LnNldFNwYWNpbmcoNCkKCiAgICAgICAgYmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hZGQgICAgPSBfZ290"
    "aGljX2J0bigiQWRkIikKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5ID0gX2dvdGhpY19idG4oIk1vZGlmeSIpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX2hpZGUgICA9IF9nb3RoaWNfYnRuKCJBcmNoaXZlIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICJNYXJrIHNlbGVjdGVkIGFzIGNvbXBsZXRlZC9yZWplY3RlZCIpCiAgICAgICAgc2VsZi5fYnRuX3VuaGlkZSA9IF9nb3Ro"
    "aWNfYnRuKCJSZXN0b3JlIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJSZXN0b3JlIGFyY2hpdmVk"
    "IGFwcGxpY2F0aW9ucyIpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSA9IF9nb3RoaWNfYnRuKCJEZWxldGUiKQogICAgICAgIHNl"
    "bGYuX2J0bl90b2dnbGUgPSBfZ290aGljX2J0bigiU2hvdyBBcmNoaXZlZCIpCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydCA9IF9n"
    "b3RoaWNfYnRuKCJFeHBvcnQiKQoKICAgICAgICBmb3IgYiBpbiAoc2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRuX21vZGlmeSwgc2Vs"
    "Zi5fYnRuX2hpZGUsCiAgICAgICAgICAgICAgICAgIHNlbGYuX2J0bl91bmhpZGUsIHNlbGYuX2J0bl9kZWxldGUsCiAgICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2J0bl90b2dnbGUsIHNlbGYuX2J0bl9leHBvcnQpOgogICAgICAgICAgICBiLnNldE1pbmltdW1XaWR0"
    "aCg3MCkKICAgICAgICAgICAgYi5zZXRNaW5pbXVtSGVpZ2h0KDI2KQogICAgICAgICAgICBiYXIuYWRkV2lkZ2V0KGIpCgogICAg"
    "ICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5LmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl9kb19tb2RpZnkpCiAgICAgICAgc2VsZi5fYnRuX2hpZGUuY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "X2RvX2hpZGUpCiAgICAgICAgc2VsZi5fYnRuX3VuaGlkZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fdW5oaWRlKQogICAgICAg"
    "IHNlbGYuX2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBzZWxmLl9idG5fdG9nZ2xl"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGVfaGlkZGVuKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQuY2xpY2tlZC5jb25u"
    "ZWN0KHNlbGYuX2RvX2V4cG9ydCkKICAgICAgICBiYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYmFyKQoK"
    "ICAgICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCBsZW4oc2VsZi5DT0xVTU5TKSkKICAgICAgICBzZWxmLl90YWJs"
    "ZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKHNlbGYuQ09MVU1OUykKICAgICAgICBoaCA9IHNlbGYuX3RhYmxlLmhvcml6b250"
    "YWxIZWFkZXIoKQogICAgICAgICMgQ29tcGFueSBhbmQgSm9iIFRpdGxlIHN0cmV0Y2gKICAgICAgICBoaC5zZXRTZWN0aW9uUmVz"
    "aXplTW9kZSgwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUo"
    "MSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgICMgRGF0ZSBBcHBsaWVkIOKAlCBmaXhlZCByZWFkYWJs"
    "ZSB3aWR0aAogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDIsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAg"
    "ICAgICAgc2VsZi5fdGFibGUuc2V0Q29sdW1uV2lkdGgoMiwgMTAwKQogICAgICAgICMgTGluayBzdHJldGNoZXMKICAgICAgICBo"
    "aC5zZXRTZWN0aW9uUmVzaXplTW9kZSgzLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgIyBTdGF0dXMg"
    "4oCUIGZpeGVkIHdpZHRoCiAgICAgICAgaGguc2V0U2VjdGlvblJlc2l6ZU1vZGUoNCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5G"
    "aXhlZCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCg0LCA4MCkKICAgICAgICAjIE5vdGVzIHN0cmV0Y2hlcwog"
    "ICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDUsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKCiAgICAgICAg"
    "c2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJl"
    "aGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uTW9kZSgKICAgICAgICAgICAgUUFic3Ry"
    "YWN0SXRlbVZpZXcuU2VsZWN0aW9uTW9kZS5FeHRlbmRlZFNlbGVjdGlvbikKICAgICAgICBzZWxmLl90YWJsZS5zZXRBbHRlcm5h"
    "dGluZ1Jvd0NvbG9ycyhUcnVlKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgp"
    "KQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlLCAxKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRSb3dDb3Vu"
    "dCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgaGlkZGVuID0gYm9vbChyZWMuZ2V0KCJo"
    "aWRkZW4iLCBGYWxzZSkpCiAgICAgICAgICAgIGlmIGhpZGRlbiBhbmQgbm90IHNlbGYuX3Nob3dfaGlkZGVuOgogICAgICAgICAg"
    "ICAgICAgY29udGludWUKICAgICAgICAgICAgciA9IHNlbGYuX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5fdGFi"
    "bGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHN0YXR1cyA9ICJBcmNoaXZlZCIgaWYgaGlkZGVuIGVsc2UgcmVjLmdldCgic3Rh"
    "dHVzIiwiQWN0aXZlIikKICAgICAgICAgICAgdmFscyA9IFsKICAgICAgICAgICAgICAgIHJlYy5nZXQoImNvbXBhbnkiLCIiKSwK"
    "ICAgICAgICAgICAgICAgIHJlYy5nZXQoImpvYl90aXRsZSIsIiIpLAogICAgICAgICAgICAgICAgcmVjLmdldCgiZGF0ZV9hcHBs"
    "aWVkIiwiIiksCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJsaW5rIiwiIiksCiAgICAgICAgICAgICAgICBzdGF0dXMsCiAgICAg"
    "ICAgICAgICAgICByZWMuZ2V0KCJub3RlcyIsIiIpLAogICAgICAgICAgICBdCiAgICAgICAgICAgIGZvciBjLCB2IGluIGVudW1l"
    "cmF0ZSh2YWxzKToKICAgICAgICAgICAgICAgIGl0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKHN0cih2KSkKICAgICAgICAgICAgICAg"
    "IGlmIGhpZGRlbjoKICAgICAgICAgICAgICAgICAgICBpdGVtLnNldEZvcmVncm91bmQoUUNvbG9yKENfVEVYVF9ESU0pKQogICAg"
    "ICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCBjLCBpdGVtKQogICAgICAgICAgICAjIFN0b3JlIHJlY29yZCBpbmRl"
    "eCBpbiBmaXJzdCBjb2x1bW4ncyB1c2VyIGRhdGEKICAgICAgICAgICAgc2VsZi5fdGFibGUuaXRlbShyLCAwKS5zZXREYXRhKAog"
    "ICAgICAgICAgICAgICAgUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLAogICAgICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5pbmRl"
    "eChyZWMpCiAgICAgICAgICAgICkKCiAgICBkZWYgX3NlbGVjdGVkX2luZGljZXMoc2VsZikgLT4gbGlzdFtpbnRdOgogICAgICAg"
    "IGluZGljZXMgPSBzZXQoKQogICAgICAgIGZvciBpdGVtIGluIHNlbGYuX3RhYmxlLnNlbGVjdGVkSXRlbXMoKToKICAgICAgICAg"
    "ICAgcm93X2l0ZW0gPSBzZWxmLl90YWJsZS5pdGVtKGl0ZW0ucm93KCksIDApCiAgICAgICAgICAgIGlmIHJvd19pdGVtOgogICAg"
    "ICAgICAgICAgICAgaWR4ID0gcm93X2l0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpCiAgICAgICAgICAgICAgICBp"
    "ZiBpZHggaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICAgICAgaW5kaWNlcy5hZGQoaWR4KQogICAgICAgIHJldHVybiBzb3J0"
    "ZWQoaW5kaWNlcykKCiAgICBkZWYgX2RpYWxvZyhzZWxmLCByZWM6IGRpY3QgPSBOb25lKSAtPiBPcHRpb25hbFtkaWN0XToKICAg"
    "ICAgICBkbGcgID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5kb3dUaXRsZSgiSm9iIEFwcGxpY2F0aW9uIikKICAg"
    "ICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRs"
    "Zy5yZXNpemUoNTAwLCAzMjApCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKCiAgICAgICAgY29tcGFueSA9IFFMaW5l"
    "RWRpdChyZWMuZ2V0KCJjb21wYW55IiwiIikgaWYgcmVjIGVsc2UgIiIpCiAgICAgICAgdGl0bGUgICA9IFFMaW5lRWRpdChyZWMu"
    "Z2V0KCJqb2JfdGl0bGUiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBkZSAgICAgID0gUURhdGVFZGl0KCkKICAgICAgICBk"
    "ZS5zZXRDYWxlbmRhclBvcHVwKFRydWUpCiAgICAgICAgZGUuc2V0RGlzcGxheUZvcm1hdCgieXl5eS1NTS1kZCIpCiAgICAgICAg"
    "aWYgcmVjIGFuZCByZWMuZ2V0KCJkYXRlX2FwcGxpZWQiKToKICAgICAgICAgICAgZGUuc2V0RGF0ZShRRGF0ZS5mcm9tU3RyaW5n"
    "KHJlY1siZGF0ZV9hcHBsaWVkIl0sInl5eXktTU0tZGQiKSkKICAgICAgICBlbHNlOgogICAgICAgICAgICBkZS5zZXREYXRlKFFE"
    "YXRlLmN1cnJlbnREYXRlKCkpCiAgICAgICAgbGluayAgICA9IFFMaW5lRWRpdChyZWMuZ2V0KCJsaW5rIiwiIikgaWYgcmVjIGVs"
    "c2UgIiIpCiAgICAgICAgc3RhdHVzICA9IFFMaW5lRWRpdChyZWMuZ2V0KCJzdGF0dXMiLCJBcHBsaWVkIikgaWYgcmVjIGVsc2Ug"
    "IkFwcGxpZWQiKQogICAgICAgIG5vdGVzICAgPSBRTGluZUVkaXQocmVjLmdldCgibm90ZXMiLCIiKSBpZiByZWMgZWxzZSAiIikK"
    "CiAgICAgICAgZm9yIGxhYmVsLCB3aWRnZXQgaW4gWwogICAgICAgICAgICAoIkNvbXBhbnk6IiwgY29tcGFueSksICgiSm9iIFRp"
    "dGxlOiIsIHRpdGxlKSwKICAgICAgICAgICAgKCJEYXRlIEFwcGxpZWQ6IiwgZGUpLCAoIkxpbms6IiwgbGluayksCiAgICAgICAg"
    "ICAgICgiU3RhdHVzOiIsIHN0YXR1cyksICgiTm90ZXM6Iiwgbm90ZXMpLAogICAgICAgIF06CiAgICAgICAgICAgIGZvcm0uYWRk"
    "Um93KGxhYmVsLCB3aWRnZXQpCgogICAgICAgIGJ0bnMgPSBRSEJveExheW91dCgpCiAgICAgICAgb2sgPSBfZ290aGljX2J0bigi"
    "U2F2ZSIpOyBjeCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIG9rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KTsg"
    "Y3guY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5zLmFkZFdpZGdldChj"
    "eCkKICAgICAgICBmb3JtLmFkZFJvdyhidG5zKQoKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5B"
    "Y2NlcHRlZDoKICAgICAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgICAgICJjb21wYW55IjogICAgICBjb21wYW55LnRleHQo"
    "KS5zdHJpcCgpLAogICAgICAgICAgICAgICAgImpvYl90aXRsZSI6ICAgIHRpdGxlLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAg"
    "ICAgICAgImRhdGVfYXBwbGllZCI6IGRlLmRhdGUoKS50b1N0cmluZygieXl5eS1NTS1kZCIpLAogICAgICAgICAgICAgICAgImxp"
    "bmsiOiAgICAgICAgIGxpbmsudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAic3RhdHVzIjogICAgICAgc3RhdHVzLnRl"
    "eHQoKS5zdHJpcCgpIG9yICJBcHBsaWVkIiwKICAgICAgICAgICAgICAgICJub3RlcyI6ICAgICAgICBub3Rlcy50ZXh0KCkuc3Ry"
    "aXAoKSwKICAgICAgICAgICAgfQogICAgICAgIHJldHVybiBOb25lCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAg"
    "ICAgICBwID0gc2VsZi5fZGlhbG9nKCkKICAgICAgICBpZiBub3QgcDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgbm93ID0g"
    "ZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICBwLnVwZGF0ZSh7CiAgICAgICAgICAgICJpZCI6"
    "ICAgICAgICAgICAgIHN0cih1dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAiaGlkZGVuIjogICAgICAgICBGYWxzZSwKICAgICAg"
    "ICAgICAgImNvbXBsZXRlZF9kYXRlIjogTm9uZSwKICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgICAgbm93LAogICAgICAgICAg"
    "ICAidXBkYXRlZF9hdCI6ICAgICBub3csCiAgICAgICAgfSkKICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChwKQogICAgICAg"
    "IHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2Rv"
    "X21vZGlmeShzZWxmKSAtPiBOb25lOgogICAgICAgIGlkeHMgPSBzZWxmLl9zZWxlY3RlZF9pbmRpY2VzKCkKICAgICAgICBpZiBs"
    "ZW4oaWR4cykgIT0gMToKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIk1vZGlmeSIsCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgZXhhY3RseSBvbmUgcm93IHRvIG1vZGlmeS4iKQogICAgICAgICAg"
    "ICByZXR1cm4KICAgICAgICByZWMgPSBzZWxmLl9yZWNvcmRzW2lkeHNbMF1dCiAgICAgICAgcCAgID0gc2VsZi5fZGlhbG9nKHJl"
    "YykKICAgICAgICBpZiBub3QgcDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjLnVwZGF0ZShwKQogICAgICAgIHJlY1si"
    "dXBkYXRlZF9hdCJdID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICB3cml0ZV9qc29ubChz"
    "ZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19oaWRlKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgZm9yIGlkeCBpbiBzZWxmLl9zZWxlY3RlZF9pbmRpY2VzKCk6CiAgICAgICAgICAgIGlmIGlkeCA8IGxl"
    "bihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsiaGlkZGVuIl0gICAgICAgICA9IFRy"
    "dWUKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbaWR4XVsiY29tcGxldGVkX2RhdGUiXSA9ICgKICAgICAgICAgICAgICAg"
    "ICAgICBzZWxmLl9yZWNvcmRzW2lkeF0uZ2V0KCJjb21wbGV0ZWRfZGF0ZSIpIG9yCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRp"
    "bWUubm93KCkuZGF0ZSgpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRz"
    "W2lkeF1bInVwZGF0ZWRfYXQiXSA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29m"
    "b3JtYXQoKQogICAgICAgICAgICAgICAgKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAg"
    "ICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX3VuaGlkZShzZWxmKSAtPiBOb25lOgogICAgICAgIGZvciBpZHggaW4g"
    "c2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpOgogICAgICAgICAgICBpZiBpZHggPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAg"
    "ICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bImhpZGRlbiJdICAgICA9IEZhbHNlCiAgICAgICAgICAgICAgICBzZWxmLl9yZWNv"
    "cmRzW2lkeF1bInVwZGF0ZWRfYXQiXSA9ICgKICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5p"
    "c29mb3JtYXQoKQogICAgICAgICAgICAgICAgKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMp"
    "CiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlkeHMgPSBz"
    "ZWxmLl9zZWxlY3RlZF9pbmRpY2VzKCkKICAgICAgICBpZiBub3QgaWR4czoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVw"
    "bHkgPSBRTWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSIsCiAgICAgICAgICAgIGYiRGVsZXRl"
    "IHtsZW4oaWR4cyl9IHNlbGVjdGVkIGFwcGxpY2F0aW9uKHMpPyBDYW5ub3QgYmUgdW5kb25lLiIsCiAgICAgICAgICAgIFFNZXNz"
    "YWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgKQogICAgICAg"
    "IGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoKICAgICAgICAgICAgYmFkID0gc2V0KGlkeHMpCiAg"
    "ICAgICAgICAgIHNlbGYuX3JlY29yZHMgPSBbciBmb3IgaSwgciBpbiBlbnVtZXJhdGUoc2VsZi5fcmVjb3JkcykKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBpZiBpIG5vdCBpbiBiYWRdCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNl"
    "bGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF90b2dnbGVfaGlkZGVuKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fc2hvd19oaWRkZW4gPSBub3Qgc2VsZi5fc2hvd19oaWRkZW4KICAgICAgICBzZWxmLl9idG5fdG9n"
    "Z2xlLnNldFRleHQoCiAgICAgICAgICAgICLimIAgSGlkZSBBcmNoaXZlZCIgaWYgc2VsZi5fc2hvd19oaWRkZW4gZWxzZSAi4pi9"
    "IFNob3cgQXJjaGl2ZWQiCiAgICAgICAgKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19leHBvcnQoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBwYXRoLCBmaWx0ID0gUUZpbGVEaWFsb2cuZ2V0U2F2ZUZpbGVOYW1lKAogICAgICAgICAgICBzZWxm"
    "LCAiRXhwb3J0IEpvYiBUcmFja2VyIiwKICAgICAgICAgICAgc3RyKGNmZ19wYXRoKCJleHBvcnRzIikgLyAiam9iX3RyYWNrZXIu"
    "Y3N2IiksCiAgICAgICAgICAgICJDU1YgRmlsZXMgKCouY3N2KTs7VGFiIERlbGltaXRlZCAoKi50eHQpIgogICAgICAgICkKICAg"
    "ICAgICBpZiBub3QgcGF0aDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZGVsaW0gPSAiXHQiIGlmIHBhdGgubG93ZXIoKS5l"
    "bmRzd2l0aCgiLnR4dCIpIGVsc2UgIiwiCiAgICAgICAgaGVhZGVyID0gWyJjb21wYW55Iiwiam9iX3RpdGxlIiwiZGF0ZV9hcHBs"
    "aWVkIiwibGluayIsCiAgICAgICAgICAgICAgICAgICJzdGF0dXMiLCJoaWRkZW4iLCJjb21wbGV0ZWRfZGF0ZSIsIm5vdGVzIl0K"
    "ICAgICAgICB3aXRoIG9wZW4ocGF0aCwgInciLCBlbmNvZGluZz0idXRmLTgiLCBuZXdsaW5lPSIiKSBhcyBmOgogICAgICAgICAg"
    "ICBmLndyaXRlKGRlbGltLmpvaW4oaGVhZGVyKSArICJcbiIpCiAgICAgICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoK"
    "ICAgICAgICAgICAgICAgIHZhbHMgPSBbCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgiY29tcGFueSIsIiIpLAogICAgICAg"
    "ICAgICAgICAgICAgIHJlYy5nZXQoImpvYl90aXRsZSIsIiIpLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImRhdGVfYXBw"
    "bGllZCIsIiIpLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImxpbmsiLCIiKSwKICAgICAgICAgICAgICAgICAgICByZWMu"
    "Z2V0KCJzdGF0dXMiLCIiKSwKICAgICAgICAgICAgICAgICAgICBzdHIoYm9vbChyZWMuZ2V0KCJoaWRkZW4iLEZhbHNlKSkpLAog"
    "ICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImNvbXBsZXRlZF9kYXRlIiwiIikgb3IgIiIsCiAgICAgICAgICAgICAgICAgICAg"
    "cmVjLmdldCgibm90ZXMiLCIiKSwKICAgICAgICAgICAgICAgIF0KICAgICAgICAgICAgICAgIGYud3JpdGUoZGVsaW0uam9pbigK"
    "ICAgICAgICAgICAgICAgICAgICBzdHIodikucmVwbGFjZSgiXG4iLCIgIikucmVwbGFjZShkZWxpbSwiICIpCiAgICAgICAgICAg"
    "ICAgICAgICAgZm9yIHYgaW4gdmFscwogICAgICAgICAgICAgICAgKSArICJcbiIpCiAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3Jt"
    "YXRpb24oc2VsZiwgIkV4cG9ydGVkIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIlNhdmVkIHRvIHtwYXRofSIp"
    "CgoKIyDilIDilIAgU0VMRiBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNz"
    "IFJlY29yZHNUYWIoUVdpZGdldCk6CiAgICAiIiJHb29nbGUgRHJpdmUvRG9jcyByZWNvcmRzIGJyb3dzZXIgdGFiLiIiIgoKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAg"
    "cm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNiwgNiwgNiwgNikKICAgICAg"
    "ICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwgPSBRTGFiZWwoIlJlY29yZHMgYXJlIG5vdCBs"
    "b2FkZWQgeWV0LiIpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjog"
    "e0NfVEVYVF9ESU19OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkK"
    "ICAgICAgICByb290LmFkZFdpZGdldChzZWxmLnN0YXR1c19sYWJlbCkKCiAgICAgICAgc2VsZi5wYXRoX2xhYmVsID0gUUxhYmVs"
    "KCJQYXRoOiBNeSBEcml2ZSIpCiAgICAgICAgc2VsZi5wYXRoX2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29s"
    "b3I6IHtDX0dPTERfRElNfTsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAg"
    "ICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5wYXRoX2xhYmVsKQoKICAgICAgICBzZWxmLnJlY29yZHNfbGlzdCA9IFFM"
    "aXN0V2lkZ2V0KCkKICAgICAgICBzZWxmLnJlY29yZHNfbGlzdC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91"
    "bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsiCiAgICAgICAgKQogICAg"
    "ICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYucmVjb3Jkc19saXN0LCAxKQoKICAgIGRlZiBzZXRfaXRlbXMoc2VsZiwgZmlsZXM6IGxp"
    "c3RbZGljdF0sIHBhdGhfdGV4dDogc3RyID0gIk15IERyaXZlIikgLT4gTm9uZToKICAgICAgICBzZWxmLnBhdGhfbGFiZWwuc2V0"
    "VGV4dChmIlBhdGg6IHtwYXRoX3RleHR9IikKICAgICAgICBzZWxmLnJlY29yZHNfbGlzdC5jbGVhcigpCiAgICAgICAgZm9yIGZp"
    "bGVfaW5mbyBpbiBmaWxlczoKICAgICAgICAgICAgdGl0bGUgPSAoZmlsZV9pbmZvLmdldCgibmFtZSIpIG9yICJVbnRpdGxlZCIp"
    "LnN0cmlwKCkgb3IgIlVudGl0bGVkIgogICAgICAgICAgICBtaW1lID0gKGZpbGVfaW5mby5nZXQoIm1pbWVUeXBlIikgb3IgIiIp"
    "LnN0cmlwKCkKICAgICAgICAgICAgaWYgbWltZSA9PSAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmZvbGRlciI6CiAgICAg"
    "ICAgICAgICAgICBwcmVmaXggPSAi8J+TgSIKICAgICAgICAgICAgZWxpZiBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xl"
    "LWFwcHMuZG9jdW1lbnQiOgogICAgICAgICAgICAgICAgcHJlZml4ID0gIvCfk50iCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAg"
    "ICAgICAgICBwcmVmaXggPSAi8J+ThCIKICAgICAgICAgICAgbW9kaWZpZWQgPSAoZmlsZV9pbmZvLmdldCgibW9kaWZpZWRUaW1l"
    "Iikgb3IgIiIpLnJlcGxhY2UoIlQiLCAiICIpLnJlcGxhY2UoIloiLCAiIFVUQyIpCiAgICAgICAgICAgIHRleHQgPSBmIntwcmVm"
    "aXh9IHt0aXRsZX0iICsgKGYiICAgIFt7bW9kaWZpZWR9XSIgaWYgbW9kaWZpZWQgZWxzZSAiIikKICAgICAgICAgICAgaXRlbSA9"
    "IFFMaXN0V2lkZ2V0SXRlbSh0ZXh0KQogICAgICAgICAgICBpdGVtLnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCBm"
    "aWxlX2luZm8pCiAgICAgICAgICAgIHNlbGYucmVjb3Jkc19saXN0LmFkZEl0ZW0oaXRlbSkKICAgICAgICBzZWxmLnN0YXR1c19s"
    "YWJlbC5zZXRUZXh0KGYiTG9hZGVkIHtsZW4oZmlsZXMpfSBHb29nbGUgRHJpdmUgaXRlbShzKS4iKQoKCmNsYXNzIFRhc2tzVGFi"
    "KFFXaWRnZXQpOgogICAgIiIiVGFzayByZWdpc3RyeSArIEdvb2dsZS1maXJzdCBlZGl0b3Igd29ya2Zsb3cgdGFiLiIiIgoKICAg"
    "IGRlZiBfX2luaXRfXygKICAgICAgICBzZWxmLAogICAgICAgIHRhc2tzX3Byb3ZpZGVyLAogICAgICAgIG9uX2FkZF9lZGl0b3Jf"
    "b3BlbiwKICAgICAgICBvbl9jb21wbGV0ZV9zZWxlY3RlZCwKICAgICAgICBvbl9jYW5jZWxfc2VsZWN0ZWQsCiAgICAgICAgb25f"
    "dG9nZ2xlX2NvbXBsZXRlZCwKICAgICAgICBvbl9wdXJnZV9jb21wbGV0ZWQsCiAgICAgICAgb25fZmlsdGVyX2NoYW5nZWQsCiAg"
    "ICAgICAgb25fZWRpdG9yX3NhdmUsCiAgICAgICAgb25fZWRpdG9yX2NhbmNlbCwKICAgICAgICBkaWFnbm9zdGljc19sb2dnZXI9"
    "Tm9uZSwKICAgICAgICBwYXJlbnQ9Tm9uZSwKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAg"
    "c2VsZi5fdGFza3NfcHJvdmlkZXIgPSB0YXNrc19wcm92aWRlcgogICAgICAgIHNlbGYuX29uX2FkZF9lZGl0b3Jfb3BlbiA9IG9u"
    "X2FkZF9lZGl0b3Jfb3BlbgogICAgICAgIHNlbGYuX29uX2NvbXBsZXRlX3NlbGVjdGVkID0gb25fY29tcGxldGVfc2VsZWN0ZWQK"
    "ICAgICAgICBzZWxmLl9vbl9jYW5jZWxfc2VsZWN0ZWQgPSBvbl9jYW5jZWxfc2VsZWN0ZWQKICAgICAgICBzZWxmLl9vbl90b2dn"
    "bGVfY29tcGxldGVkID0gb25fdG9nZ2xlX2NvbXBsZXRlZAogICAgICAgIHNlbGYuX29uX3B1cmdlX2NvbXBsZXRlZCA9IG9uX3B1"
    "cmdlX2NvbXBsZXRlZAogICAgICAgIHNlbGYuX29uX2ZpbHRlcl9jaGFuZ2VkID0gb25fZmlsdGVyX2NoYW5nZWQKICAgICAgICBz"
    "ZWxmLl9vbl9lZGl0b3Jfc2F2ZSA9IG9uX2VkaXRvcl9zYXZlCiAgICAgICAgc2VsZi5fb25fZWRpdG9yX2NhbmNlbCA9IG9uX2Vk"
    "aXRvcl9jYW5jZWwKICAgICAgICBzZWxmLl9kaWFnX2xvZ2dlciA9IGRpYWdub3N0aWNzX2xvZ2dlcgogICAgICAgIHNlbGYuX3No"
    "b3dfY29tcGxldGVkID0gRmFsc2UKICAgICAgICBzZWxmLl9yZWZyZXNoX3RocmVhZCA9IE5vbmUKICAgICAgICBzZWxmLl9idWls"
    "ZF91aSgpCgogICAgZGVmIF9idWlsZF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQog"
    "ICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCiAgICAg"
    "ICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2sgPSBRU3RhY2tlZFdpZGdldCgpCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi53b3Jr"
    "c3BhY2Vfc3RhY2ssIDEpCgogICAgICAgIG5vcm1hbCA9IFFXaWRnZXQoKQogICAgICAgIG5vcm1hbF9sYXlvdXQgPSBRVkJveExh"
    "eW91dChub3JtYWwpCiAgICAgICAgbm9ybWFsX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBu"
    "b3JtYWxfbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwgPSBRTGFiZWwoIlRhc2sgcmVnaXN0"
    "cnkgaXMgbm90IGxvYWRlZCB5ZXQuIikKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsi"
    "CiAgICAgICAgKQogICAgICAgIG5vcm1hbF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuc3RhdHVzX2xhYmVsKQoKICAgICAgICBmaWx0"
    "ZXJfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIERBVEUg"
    "UkFOR0UiKSkKICAgICAgICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvID0gUUNvbWJvQm94KCkKICAgICAgICBzZWxmLnRhc2tfZmls"
    "dGVyX2NvbWJvLmFkZEl0ZW0oIldFRUsiLCAid2VlayIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5hZGRJdGVtKCJN"
    "T05USCIsICJtb250aCIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRlcl9jb21iby5hZGRJdGVtKCJORVhUIDMgTU9OVEhTIiwgIm5l"
    "eHRfM19tb250aHMiKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiWUVBUiIsICJ5ZWFyIikKICAgICAg"
    "ICBzZWxmLnRhc2tfZmlsdGVyX2NvbWJvLnNldEN1cnJlbnRJbmRleCgyKQogICAgICAgIHNlbGYudGFza19maWx0ZXJfY29tYm8u"
    "Y3VycmVudEluZGV4Q2hhbmdlZC5jb25uZWN0KAogICAgICAgICAgICBsYW1iZGEgXzogc2VsZi5fb25fZmlsdGVyX2NoYW5nZWQo"
    "c2VsZi50YXNrX2ZpbHRlcl9jb21iby5jdXJyZW50RGF0YSgpIG9yICJuZXh0XzNfbW9udGhzIikKICAgICAgICApCiAgICAgICAg"
    "ZmlsdGVyX3Jvdy5hZGRXaWRnZXQoc2VsZi50YXNrX2ZpbHRlcl9jb21ibykKICAgICAgICBmaWx0ZXJfcm93LmFkZFN0cmV0Y2go"
    "MSkKICAgICAgICBub3JtYWxfbGF5b3V0LmFkZExheW91dChmaWx0ZXJfcm93KQoKICAgICAgICBzZWxmLnRhc2tfdGFibGUgPSBR"
    "VGFibGVXaWRnZXQoMCwgNCkKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIlN0YXR1"
    "cyIsICJEdWUiLCAiVGFzayIsICJTb3VyY2UiXSkKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3Io"
    "UUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0"
    "U2VsZWN0aW9uTW9kZShRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25Nb2RlLkV4dGVuZGVkU2VsZWN0aW9uKQogICAgICAgIHNl"
    "bGYudGFza190YWJsZS5zZXRFZGl0VHJpZ2dlcnMoUUFic3RyYWN0SXRlbVZpZXcuRWRpdFRyaWdnZXIuTm9FZGl0VHJpZ2dlcnMp"
    "CiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnZlcnRpY2FsSGVhZGVyKCkuc2V0VmlzaWJsZShGYWxzZSkKICAgICAgICBzZWxmLnRh"
    "c2tfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUu"
    "UmVzaXplVG9Db250ZW50cykKICAgICAgICBzZWxmLnRhc2tfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNp"
    "emVNb2RlKDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuUmVzaXplVG9Db250ZW50cykKICAgICAgICBzZWxmLnRhc2tfdGFibGUu"
    "aG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKDIsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkK"
    "ICAgICAgICBzZWxmLnRhc2tfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKDMsIFFIZWFkZXJW"
    "aWV3LlJlc2l6ZU1vZGUuUmVzaXplVG9Db250ZW50cykKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0U3R5bGVTaGVldChfZ290"
    "aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLml0ZW1TZWxlY3Rpb25DaGFuZ2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fdXBkYXRlX2FjdGlvbl9idXR0b25fc3RhdGUpCiAgICAgICAgbm9ybWFsX2xheW91dC5hZGRXaWRnZXQoc2VsZi50YXNrX3Rh"
    "YmxlLCAxKQoKICAgICAgICBhY3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuYnRuX2FkZF90YXNrX3dvcmtzcGFj"
    "ZSA9IF9nb3RoaWNfYnRuKCJBREQgVEFTSyIpCiAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzayA9IF9nb3RoaWNfYnRuKCJD"
    "T01QTEVURSBTRUxFQ1RFRCIpCiAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2sgPSBfZ290aGljX2J0bigiQ0FOQ0VMIFNFTEVD"
    "VEVEIikKICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkID0gX2dvdGhpY19idG4oIlNIT1cgQ09NUExFVEVEIikKICAg"
    "ICAgICBzZWxmLmJ0bl9wdXJnZV9jb21wbGV0ZWQgPSBfZ290aGljX2J0bigiUFVSR0UgQ09NUExFVEVEIikKICAgICAgICBzZWxm"
    "LmJ0bl9hZGRfdGFza193b3Jrc3BhY2UuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX2FkZF9lZGl0b3Jfb3BlbikKICAgICAgICBz"
    "ZWxmLmJ0bl9jb21wbGV0ZV90YXNrLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9jb21wbGV0ZV9zZWxlY3RlZCkKICAgICAgICBz"
    "ZWxmLmJ0bl9jYW5jZWxfdGFzay5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fY2FuY2VsX3NlbGVjdGVkKQogICAgICAgIHNlbGYu"
    "YnRuX3RvZ2dsZV9jb21wbGV0ZWQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX29uX3RvZ2dsZV9jb21wbGV0ZWQpCiAgICAgICAgc2Vs"
    "Zi5idG5fcHVyZ2VfY29tcGxldGVkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9wdXJnZV9jb21wbGV0ZWQpCiAgICAgICAgc2Vs"
    "Zi5idG5fY29tcGxldGVfdGFzay5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuYnRuX2NhbmNlbF90YXNrLnNldEVuYWJs"
    "ZWQoRmFsc2UpCiAgICAgICAgZm9yIGJ0biBpbiAoCiAgICAgICAgICAgIHNlbGYuYnRuX2FkZF90YXNrX3dvcmtzcGFjZSwKICAg"
    "ICAgICAgICAgc2VsZi5idG5fY29tcGxldGVfdGFzaywKICAgICAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2ssCiAgICAgICAg"
    "ICAgIHNlbGYuYnRuX3RvZ2dsZV9jb21wbGV0ZWQsCiAgICAgICAgICAgIHNlbGYuYnRuX3B1cmdlX2NvbXBsZXRlZCwKICAgICAg"
    "ICApOgogICAgICAgICAgICBhY3Rpb25zLmFkZFdpZGdldChidG4pCiAgICAgICAgbm9ybWFsX2xheW91dC5hZGRMYXlvdXQoYWN0"
    "aW9ucykKICAgICAgICBzZWxmLndvcmtzcGFjZV9zdGFjay5hZGRXaWRnZXQobm9ybWFsKQoKICAgICAgICBlZGl0b3IgPSBRV2lk"
    "Z2V0KCkKICAgICAgICBlZGl0b3JfbGF5b3V0ID0gUVZCb3hMYXlvdXQoZWRpdG9yKQogICAgICAgIGVkaXRvcl9sYXlvdXQuc2V0"
    "Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgZWRpdG9yX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgZWRp"
    "dG9yX2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgVEFTSyBFRElUT1Ig4oCUIEdPT0dMRS1GSVJTVCIpKQogICAg"
    "ICAgIHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVsID0gUUxhYmVsKCJDb25maWd1cmUgdGFzayBkZXRhaWxzLCB0aGVuIHNh"
    "dmUgdG8gR29vZ2xlIENhbGVuZGFyLiIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyBib3JkZXI6IDFweCBzb2xp"
    "ZCB7Q19CT1JERVJ9OyBwYWRkaW5nOiA2cHg7IgogICAgICAgICkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldChzZWxm"
    "LnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25hbWUgPSBRTGluZUVkaXQoKQogICAg"
    "ICAgIHNlbGYudGFza19lZGl0b3JfbmFtZS5zZXRQbGFjZWhvbGRlclRleHQoIlRhc2sgTmFtZSIpCiAgICAgICAgc2VsZi50YXNr"
    "X2VkaXRvcl9zdGFydF9kYXRlID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUuc2V0UGxh"
    "Y2Vob2xkZXJUZXh0KCJTdGFydCBEYXRlIChZWVlZLU1NLUREKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1l"
    "ID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJTdGFy"
    "dCBUaW1lIChISDpNTSkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfZW5kX2RhdGUgPSBRTGluZUVkaXQoKQogICAgICAgIHNl"
    "bGYudGFza19lZGl0b3JfZW5kX2RhdGUuc2V0UGxhY2Vob2xkZXJUZXh0KCJFbmQgRGF0ZSAoWVlZWS1NTS1ERCkiKQogICAgICAg"
    "IHNlbGYudGFza19lZGl0b3JfZW5kX3RpbWUgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfZW5kX3RpbWUu"
    "c2V0UGxhY2Vob2xkZXJUZXh0KCJFbmQgVGltZSAoSEg6TU0pIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2xvY2F0aW9uID0g"
    "UUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2xvY2F0aW9uLnNldFBsYWNlaG9sZGVyVGV4dCgiTG9jYXRpb24g"
    "KG9wdGlvbmFsKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxm"
    "LnRhc2tfZWRpdG9yX3JlY3VycmVuY2Uuc2V0UGxhY2Vob2xkZXJUZXh0KCJSZWN1cnJlbmNlIFJSVUxFIChvcHRpb25hbCkiKQog"
    "ICAgICAgIHNlbGYudGFza19lZGl0b3JfYWxsX2RheSA9IFFDaGVja0JveCgiQWxsLWRheSIpCiAgICAgICAgc2VsZi50YXNrX2Vk"
    "aXRvcl9ub3RlcyA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9ub3Rlcy5zZXRQbGFjZWhvbGRlclRleHQo"
    "Ik5vdGVzIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX25vdGVzLnNldE1heGltdW1IZWlnaHQoOTApCiAgICAgICAgZm9yIHdp"
    "ZGdldCBpbiAoCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3JfbmFtZSwKICAgICAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9z"
    "dGFydF9kYXRlLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUsCiAgICAgICAgICAgIHNlbGYudGFza19l"
    "ZGl0b3JfZW5kX2RhdGUsCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3JfZW5kX3RpbWUsCiAgICAgICAgICAgIHNlbGYudGFz"
    "a19lZGl0b3JfbG9jYXRpb24sCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3JfcmVjdXJyZW5jZSwKICAgICAgICApOgogICAg"
    "ICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldCh3aWRnZXQpCiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQoc2Vs"
    "Zi50YXNrX2VkaXRvcl9hbGxfZGF5KQogICAgICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza19lZGl0b3Jfbm90"
    "ZXMsIDEpCiAgICAgICAgZWRpdG9yX2FjdGlvbnMgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX3NhdmUgPSBfZ290aGljX2J0"
    "bigiU0FWRSIpCiAgICAgICAgYnRuX2NhbmNlbCA9IF9nb3RoaWNfYnRuKCJDQU5DRUwiKQogICAgICAgIGJ0bl9zYXZlLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9vbl9lZGl0b3Jfc2F2ZSkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChzZWxmLl9v"
    "bl9lZGl0b3JfY2FuY2VsKQogICAgICAgIGVkaXRvcl9hY3Rpb25zLmFkZFdpZGdldChidG5fc2F2ZSkKICAgICAgICBlZGl0b3Jf"
    "YWN0aW9ucy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBlZGl0b3JfYWN0aW9ucy5hZGRTdHJldGNoKDEpCiAgICAgICAg"
    "ZWRpdG9yX2xheW91dC5hZGRMYXlvdXQoZWRpdG9yX2FjdGlvbnMpCiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suYWRkV2lk"
    "Z2V0KGVkaXRvcikKCiAgICAgICAgc2VsZi5ub3JtYWxfd29ya3NwYWNlID0gbm9ybWFsCiAgICAgICAgc2VsZi5lZGl0b3Jfd29y"
    "a3NwYWNlID0gZWRpdG9yCiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suc2V0Q3VycmVudFdpZGdldChzZWxmLm5vcm1hbF93"
    "b3Jrc3BhY2UpCgogICAgZGVmIF91cGRhdGVfYWN0aW9uX2J1dHRvbl9zdGF0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIGVuYWJs"
    "ZWQgPSBib29sKHNlbGYuc2VsZWN0ZWRfdGFza19pZHMoKSkKICAgICAgICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrLnNldEVuYWJs"
    "ZWQoZW5hYmxlZCkKICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzay5zZXRFbmFibGVkKGVuYWJsZWQpCgogICAgZGVmIHNlbGVj"
    "dGVkX3Rhc2tfaWRzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICBpZHM6IGxpc3Rbc3RyXSA9IFtdCiAgICAgICAgZm9yIHIg"
    "aW4gcmFuZ2Uoc2VsZi50YXNrX3RhYmxlLnJvd0NvdW50KCkpOgogICAgICAgICAgICBzdGF0dXNfaXRlbSA9IHNlbGYudGFza190"
    "YWJsZS5pdGVtKHIsIDApCiAgICAgICAgICAgIGlmIHN0YXR1c19pdGVtIGlzIE5vbmU6CiAgICAgICAgICAgICAgICBjb250aW51"
    "ZQogICAgICAgICAgICBpZiBub3Qgc3RhdHVzX2l0ZW0uaXNTZWxlY3RlZCgpOgogICAgICAgICAgICAgICAgY29udGludWUKICAg"
    "ICAgICAgICAgdGFza19pZCA9IHN0YXR1c19pdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAgICAgICAgICBp"
    "ZiB0YXNrX2lkIGFuZCB0YXNrX2lkIG5vdCBpbiBpZHM6CiAgICAgICAgICAgICAgICBpZHMuYXBwZW5kKHRhc2tfaWQpCiAgICAg"
    "ICAgcmV0dXJuIGlkcwoKICAgIGRlZiBsb2FkX3Rhc2tzKHNlbGYsIHRhc2tzOiBsaXN0W2RpY3RdKSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYudGFza190YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciB0YXNrIGluIHRhc2tzOgogICAgICAgICAgICByb3cg"
    "PSBzZWxmLnRhc2tfdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLnRhc2tfdGFibGUuaW5zZXJ0Um93KHJvdykKICAg"
    "ICAgICAgICAgc3RhdHVzID0gKHRhc2suZ2V0KCJzdGF0dXMiKSBvciAicGVuZGluZyIpLmxvd2VyKCkKICAgICAgICAgICAgc3Rh"
    "dHVzX2ljb24gPSAi4piRIiBpZiBzdGF0dXMgaW4geyJjb21wbGV0ZWQiLCAiY2FuY2VsbGVkIn0gZWxzZSAi4oCiIgogICAgICAg"
    "ICAgICBkdWUgPSAodGFzay5nZXQoImR1ZV9hdCIpIG9yICIiKS5yZXBsYWNlKCJUIiwgIiAiKQogICAgICAgICAgICB0ZXh0ID0g"
    "KHRhc2suZ2V0KCJ0ZXh0Iikgb3IgIlJlbWluZGVyIikuc3RyaXAoKSBvciAiUmVtaW5kZXIiCiAgICAgICAgICAgIHNvdXJjZSA9"
    "ICh0YXNrLmdldCgic291cmNlIikgb3IgImxvY2FsIikubG93ZXIoKQogICAgICAgICAgICBzdGF0dXNfaXRlbSA9IFFUYWJsZVdp"
    "ZGdldEl0ZW0oZiJ7c3RhdHVzX2ljb259IHtzdGF0dXN9IikKICAgICAgICAgICAgc3RhdHVzX2l0ZW0uc2V0RGF0YShRdC5JdGVt"
    "RGF0YVJvbGUuVXNlclJvbGUsIHRhc2suZ2V0KCJpZCIpKQogICAgICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0SXRlbShyb3cs"
    "IDAsIHN0YXR1c19pdGVtKQogICAgICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0SXRlbShyb3csIDEsIFFUYWJsZVdpZGdldEl0"
    "ZW0oZHVlKSkKICAgICAgICAgICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAyLCBRVGFibGVXaWRnZXRJdGVtKHRleHQp"
    "KQogICAgICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0SXRlbShyb3csIDMsIFFUYWJsZVdpZGdldEl0ZW0oc291cmNlKSkKICAg"
    "ICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRUZXh0KGYiTG9hZGVkIHtsZW4odGFza3MpfSB0YXNrKHMpLiIpCiAgICAgICAgc2Vs"
    "Zi5fdXBkYXRlX2FjdGlvbl9idXR0b25fc3RhdGUoKQoKICAgIGRlZiBfZGlhZyhzZWxmLCBtZXNzYWdlOiBzdHIsIGxldmVsOiBz"
    "dHIgPSAiSU5GTyIpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBpZiBzZWxmLl9kaWFnX2xvZ2dlcjoKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfbG9nZ2VyKG1lc3NhZ2UsIGxldmVsKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAg"
    "ICAgICAgIHBhc3MKCiAgICBkZWYgc3RvcF9yZWZyZXNoX3dvcmtlcihzZWxmLCByZWFzb246IHN0ciA9ICIiKSAtPiBOb25lOgog"
    "ICAgICAgIHRocmVhZCA9IGdldGF0dHIoc2VsZiwgIl9yZWZyZXNoX3RocmVhZCIsIE5vbmUpCiAgICAgICAgaWYgdGhyZWFkIGlz"
    "IG5vdCBOb25lIGFuZCBoYXNhdHRyKHRocmVhZCwgImlzUnVubmluZyIpIGFuZCB0aHJlYWQuaXNSdW5uaW5nKCk6CiAgICAgICAg"
    "ICAgIHNlbGYuX2RpYWcoCiAgICAgICAgICAgICAgICBmIltUQVNLU11bVEhSRUFEXVtXQVJOXSBzdG9wIHJlcXVlc3RlZCBmb3Ig"
    "cmVmcmVzaCB3b3JrZXIgcmVhc29uPXtyZWFzb24gb3IgJ3Vuc3BlY2lmaWVkJ30iLAogICAgICAgICAgICAgICAgIldBUk4iLAog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHRocmVhZC5yZXF1ZXN0SW50ZXJydXB0aW9uKCkK"
    "ICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICAgICAgdGhyZWFkLnF1aXQoKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwog"
    "ICAgICAgICAgICB0aHJlYWQud2FpdCgyMDAwKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGhyZWFkID0gTm9uZQoKICAgIGRlZiBy"
    "ZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IGNhbGxhYmxlKHNlbGYuX3Rhc2tzX3Byb3ZpZGVyKToKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLmxvYWRfdGFza3Moc2VsZi5fdGFza3NfcHJvdmlkZXIo"
    "KSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnKGYiW1RBU0tTXVtUQUJdW0VS"
    "Uk9SXSByZWZyZXNoIGZhaWxlZDoge2V4fSIsICJFUlJPUiIpCiAgICAgICAgICAgIHNlbGYuc3RvcF9yZWZyZXNoX3dvcmtlcihy"
    "ZWFzb249InRhc2tzX3RhYl9yZWZyZXNoX2V4Y2VwdGlvbiIpCgogICAgZGVmIGNsb3NlRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5zdG9wX3JlZnJlc2hfd29ya2VyKHJlYXNvbj0idGFza3NfdGFiX2Nsb3NlIikKICAgICAgICBzdXBl"
    "cigpLmNsb3NlRXZlbnQoZXZlbnQpCgogICAgZGVmIHNldF9zaG93X2NvbXBsZXRlZChzZWxmLCBlbmFibGVkOiBib29sKSAtPiBO"
    "b25lOgogICAgICAgIHNlbGYuX3Nob3dfY29tcGxldGVkID0gYm9vbChlbmFibGVkKQogICAgICAgIHNlbGYuYnRuX3RvZ2dsZV9j"
    "b21wbGV0ZWQuc2V0VGV4dCgiSElERSBDT01QTEVURUQiIGlmIHNlbGYuX3Nob3dfY29tcGxldGVkIGVsc2UgIlNIT1cgQ09NUExF"
    "VEVEIikKCiAgICBkZWYgc2V0X3N0YXR1cyhzZWxmLCB0ZXh0OiBzdHIsIG9rOiBib29sID0gRmFsc2UpIC0+IE5vbmU6CiAgICAg"
    "ICAgY29sb3IgPSBDX0dSRUVOIGlmIG9rIGVsc2UgQ19URVhUX0RJTQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xh"
    "YmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtjb2xvcn07IGJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IHBhZGRpbmc6IDZweDsiCiAgICAgICAgKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jf"
    "c3RhdHVzX2xhYmVsLnNldFRleHQodGV4dCkKCiAgICBkZWYgb3Blbl9lZGl0b3Ioc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "LndvcmtzcGFjZV9zdGFjay5zZXRDdXJyZW50V2lkZ2V0KHNlbGYuZWRpdG9yX3dvcmtzcGFjZSkKCiAgICBkZWYgY2xvc2VfZWRp"
    "dG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suc2V0Q3VycmVudFdpZGdldChzZWxmLm5vcm1h"
    "bF93b3Jrc3BhY2UpCgoKY2xhc3MgU2VsZlRhYihRV2lkZ2V0KToKICAgICIiIgogICAgUGVyc29uYSdzIGludGVybmFsIGRpYWxv"
    "Z3VlIHNwYWNlLgogICAgUmVjZWl2ZXM6IGlkbGUgbmFycmF0aXZlIG91dHB1dCwgdW5zb2xpY2l0ZWQgdHJhbnNtaXNzaW9ucywK"
    "ICAgICAgICAgICAgICBQb0kgbGlzdCBmcm9tIGRhaWx5IHJlZmxlY3Rpb24sIHVuYW5zd2VyZWQgcXVlc3Rpb24gZmxhZ3MsCiAg"
    "ICAgICAgICAgICAgam91cm5hbCBsb2FkIG5vdGlmaWNhdGlvbnMuCiAgICBSZWFkLW9ubHkgZGlzcGxheS4gU2VwYXJhdGUgZnJv"
    "bSBwZXJzb25hIGNoYXQgdGFiIGFsd2F5cy4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAg"
    "ICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9v"
    "dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgaGRyID0g"
    "UUhCb3hMYXlvdXQoKQogICAgICAgIGhkci5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKGYi4p2nIElOTkVSIFNBTkNUVU0g4oCUIHtE"
    "RUNLX05BTUUudXBwZXIoKX0nUyBQUklWQVRFIFRIT1VHSFRTIikpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyID0gX2dvdGhpY19i"
    "dG4oIuKclyBDbGVhciIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyLnNldEZpeGVkV2lkdGgoODApCiAgICAgICAgc2VsZi5fYnRu"
    "X2NsZWFyLmNsaWNrZWQuY29ubmVjdChzZWxmLmNsZWFyKQogICAgICAgIGhkci5hZGRTdHJldGNoKCkKICAgICAgICBoZHIuYWRk"
    "V2lkZ2V0KHNlbGYuX2J0bl9jbGVhcikKICAgICAgICByb290LmFkZExheW91dChoZHIpCgogICAgICAgIHNlbGYuX2Rpc3BsYXkg"
    "PSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9kaXNwbGF5"
    "LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9yOiB7Q19HT0xEfTsgIgog"
    "ICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX1BVUlBMRV9ESU19OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6"
    "IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMXB4OyBwYWRkaW5nOiA4cHg7IgogICAgICAgICkKICAgICAgICByb290"
    "LmFkZFdpZGdldChzZWxmLl9kaXNwbGF5LCAxKQoKICAgIGRlZiBhcHBlbmQoc2VsZiwgbGFiZWw6IHN0ciwgdGV4dDogc3RyKSAt"
    "PiBOb25lOgogICAgICAgIHRpbWVzdGFtcCA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUyIpCiAgICAgICAgY29s"
    "b3JzID0gewogICAgICAgICAgICAiTkFSUkFUSVZFIjogIENfR09MRCwKICAgICAgICAgICAgIlJFRkxFQ1RJT04iOiBDX1BVUlBM"
    "RSwKICAgICAgICAgICAgIkpPVVJOQUwiOiAgICBDX1NJTFZFUiwKICAgICAgICAgICAgIlBPSSI6ICAgICAgICBDX0dPTERfRElN"
    "LAogICAgICAgICAgICAiU1lTVEVNIjogICAgIENfVEVYVF9ESU0sCiAgICAgICAgfQogICAgICAgIGNvbG9yID0gY29sb3JzLmdl"
    "dChsYWJlbC51cHBlcigpLCBDX0dPTEQpCiAgICAgICAgc2VsZi5fZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgIGYnPHNwYW4g"
    "c3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgIGYnW3t0aW1lc3RhbXB9XSA8"
    "L3NwYW4+JwogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Y29sb3J9OyBmb250LXdlaWdodDpib2xkOyI+JwogICAg"
    "ICAgICAgICBmJ+KdpyB7bGFiZWx9PC9zcGFuPjxicj4nCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX0dPTER9"
    "OyI+e3RleHR9PC9zcGFuPicKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlzcGxheS5hcHBlbmQoIiIpCiAgICAgICAgc2VsZi5f"
    "ZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9kaXNwbGF5LnZlcnRpY2FsU2Ny"
    "b2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgIGRlZiBjbGVhcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Rp"
    "c3BsYXkuY2xlYXIoKQoKCiMg4pSA4pSAIERJQUdOT1NUSUNTIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3Mg"
    "RGlhZ25vc3RpY3NUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIEJhY2tlbmQgZGlhZ25vc3RpY3MgZGlzcGxheS4KICAgIFJlY2Vp"
    "dmVzOiBoYXJkd2FyZSBkZXRlY3Rpb24gcmVzdWx0cywgZGVwZW5kZW5jeSBjaGVjayByZXN1bHRzLAogICAgICAgICAgICAgIEFQ"
    "SSBlcnJvcnMsIHN5bmMgZmFpbHVyZXMsIHRpbWVyIGV2ZW50cywgam91cm5hbCBsb2FkIG5vdGljZXMsCiAgICAgICAgICAgICAg"
    "bW9kZWwgbG9hZCBzdGF0dXMsIEdvb2dsZSBhdXRoIGV2ZW50cy4KICAgIEFsd2F5cyBzZXBhcmF0ZSBmcm9tIHBlcnNvbmEgY2hh"
    "dCB0YWIuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0"
    "X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5z"
    "KDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGhkciA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBoZHIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIERJQUdOT1NUSUNTIOKAlCBTWVNURU0gJiBCQUNLRU5EIExPRyIpKQog"
    "ICAgICAgIHNlbGYuX2J0bl9jbGVhciA9IF9nb3RoaWNfYnRuKCLinJcgQ2xlYXIiKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5z"
    "ZXRGaXhlZFdpZHRoKDgwKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5jbGlja2VkLmNvbm5lY3Qoc2VsZi5jbGVhcikKICAgICAg"
    "ICBoZHIuYWRkU3RyZXRjaCgpCiAgICAgICAgaGRyLmFkZFdpZGdldChzZWxmLl9idG5fY2xlYXIpCiAgICAgICAgcm9vdC5hZGRM"
    "YXlvdXQoaGRyKQoKICAgICAgICBzZWxmLl9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9kaXNwbGF5LnNldFJl"
    "YWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6"
    "IHtDX01PTklUT1J9OyBjb2xvcjoge0NfU0lMVkVSfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRF"
    "Un07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseTogJ0NvdXJpZXIgTmV3JywgbW9ub3NwYWNlOyAiCiAgICAgICAgICAgIGYi"
    "Zm9udC1zaXplOiAxMHB4OyBwYWRkaW5nOiA4cHg7IgogICAgICAgICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9kaXNw"
    "bGF5LCAxKQoKICAgIGRlZiBsb2coc2VsZiwgbWVzc2FnZTogc3RyLCBsZXZlbDogc3RyID0gIklORk8iKSAtPiBOb25lOgogICAg"
    "ICAgIHRpbWVzdGFtcCA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUyIpCiAgICAgICAgbGV2ZWxfY29sb3JzID0g"
    "ewogICAgICAgICAgICAiSU5GTyI6ICBDX1NJTFZFUiwKICAgICAgICAgICAgIk9LIjogICAgQ19HUkVFTiwKICAgICAgICAgICAg"
    "IldBUk4iOiAgQ19HT0xELAogICAgICAgICAgICAiRVJST1IiOiBDX0JMT09ELAogICAgICAgICAgICAiREVCVUciOiBDX1RFWFRf"
    "RElNLAogICAgICAgIH0KICAgICAgICBjb2xvciA9IGxldmVsX2NvbG9ycy5nZXQobGV2ZWwudXBwZXIoKSwgQ19TSUxWRVIpCiAg"
    "ICAgICAgc2VsZi5fZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsi"
    "Plt7dGltZXN0YW1wfV08L3NwYW4+ICcKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2NvbG9yfTsiPnttZXNzYWdl"
    "fTwvc3Bhbj4nCiAgICAgICAgKQogICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAg"
    "ICAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLm1heGltdW0oKQogICAgICAgICkKCiAgICBkZWYgbG9n"
    "X21hbnkoc2VsZiwgbWVzc2FnZXM6IGxpc3Rbc3RyXSwgbGV2ZWw6IHN0ciA9ICJJTkZPIikgLT4gTm9uZToKICAgICAgICBmb3Ig"
    "bXNnIGluIG1lc3NhZ2VzOgogICAgICAgICAgICBsdmwgPSBsZXZlbAogICAgICAgICAgICBpZiAi4pyTIiBpbiBtc2c6ICAgIGx2"
    "bCA9ICJPSyIKICAgICAgICAgICAgZWxpZiAi4pyXIiBpbiBtc2c6ICBsdmwgPSAiV0FSTiIKICAgICAgICAgICAgZWxpZiAiRVJS"
    "T1IiIGluIG1zZy51cHBlcigpOiBsdmwgPSAiRVJST1IiCiAgICAgICAgICAgIHNlbGYubG9nKG1zZywgbHZsKQoKICAgIGRlZiBj"
    "bGVhcihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Rpc3BsYXkuY2xlYXIoKQoKCiMg4pSA4pSAIExFU1NPTlMgVEFCIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBMZXNzb25zVGFiKFFXaWRnZXQpOgogICAgIiIiCiAg"
    "ICBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgYW5kIGNvZGUgbGVzc29ucyBicm93c2VyLgogICAgQWRkLCB2aWV3LCBzZWFyY2gsIGRl"
    "bGV0ZSBsZXNzb25zLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGRiOiAiTGVzc29uc0xlYXJuZWREQiIsIHBhcmVu"
    "dD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kYiA9IGRiCiAgICAgICAgc2Vs"
    "Zi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAg"
    "ICAgICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgICMgRmlsdGVyIGJhcgogICAgICAgIGZpbHRlcl9yb3cgPSBRSEJveExh"
    "eW91dCgpCiAgICAgICAgc2VsZi5fc2VhcmNoID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9zZWFyY2guc2V0UGxhY2Vob2xk"
    "ZXJUZXh0KCJTZWFyY2ggbGVzc29ucy4uLiIpCiAgICAgICAgc2VsZi5fbGFuZ19maWx0ZXIgPSBRQ29tYm9Cb3goKQogICAgICAg"
    "IHNlbGYuX2xhbmdfZmlsdGVyLmFkZEl0ZW1zKFsiQWxsIiwgIkxTTCIsICJQeXRob24iLCAiUHlTaWRlNiIsCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAiSmF2YVNjcmlwdCIsICJPdGhlciJdKQogICAgICAgIHNlbGYuX3NlYXJjaC50ZXh0"
    "Q2hhbmdlZC5jb25uZWN0KHNlbGYucmVmcmVzaCkKICAgICAgICBzZWxmLl9sYW5nX2ZpbHRlci5jdXJyZW50VGV4dENoYW5nZWQu"
    "Y29ubmVjdChzZWxmLnJlZnJlc2gpCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJTZWFyY2g6IikpCiAgICAg"
    "ICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoc2VsZi5fc2VhcmNoLCAxKQogICAgICAgIGZpbHRlcl9yb3cuYWRkV2lkZ2V0KFFMYWJl"
    "bCgiTGFuZ3VhZ2U6IikpCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoc2VsZi5fbGFuZ19maWx0ZXIpCiAgICAgICAgcm9v"
    "dC5hZGRMYXlvdXQoZmlsdGVyX3JvdykKCiAgICAgICAgYnRuX2JhciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBidG5fYWRkID0g"
    "X2dvdGhpY19idG4oIuKcpiBBZGQgTGVzc29uIikKICAgICAgICBidG5fZGVsID0gX2dvdGhpY19idG4oIuKclyBEZWxldGUiKQog"
    "ICAgICAgIGJ0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAgICBidG5fZGVsLmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLl9kb19kZWxldGUpCiAgICAgICAgYnRuX2Jhci5hZGRXaWRnZXQoYnRuX2FkZCkKICAgICAgICBidG5fYmFyLmFkZFdp"
    "ZGdldChidG5fZGVsKQogICAgICAgIGJ0bl9iYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYnRuX2JhcikK"
    "CiAgICAgICAgc2VsZi5fdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgNCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRIb3Jpem9udGFs"
    "SGVhZGVyTGFiZWxzKAogICAgICAgICAgICBbIkxhbmd1YWdlIiwgIlJlZmVyZW5jZSBLZXkiLCAiU3VtbWFyeSIsICJFbnZpcm9u"
    "bWVudCJdCiAgICAgICAgKQogICAgICAgIHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9k"
    "ZSgKICAgICAgICAgICAgMiwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFNl"
    "bGVjdGlvbkJlaGF2aW9yKAogICAgICAgICAgICBRQWJzdHJhY3RJdGVtVmlldy5TZWxlY3Rpb25CZWhhdmlvci5TZWxlY3RSb3dz"
    "KQogICAgICAgIHNlbGYuX3RhYmxlLnNldEFsdGVybmF0aW5nUm93Q29sb3JzKFRydWUpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0"
    "U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2VsZi5fdGFibGUuaXRlbVNlbGVjdGlvbkNoYW5nZWQu"
    "Y29ubmVjdChzZWxmLl9vbl9zZWxlY3QpCgogICAgICAgICMgVXNlIHNwbGl0dGVyIGJldHdlZW4gdGFibGUgYW5kIGRldGFpbAog"
    "ICAgICAgIHNwbGl0dGVyID0gUVNwbGl0dGVyKFF0Lk9yaWVudGF0aW9uLlZlcnRpY2FsKQogICAgICAgIHNwbGl0dGVyLmFkZFdp"
    "ZGdldChzZWxmLl90YWJsZSkKCiAgICAgICAgIyBEZXRhaWwgcGFuZWwKICAgICAgICBkZXRhaWxfd2lkZ2V0ID0gUVdpZGdldCgp"
    "CiAgICAgICAgZGV0YWlsX2xheW91dCA9IFFWQm94TGF5b3V0KGRldGFpbF93aWRnZXQpCiAgICAgICAgZGV0YWlsX2xheW91dC5z"
    "ZXRDb250ZW50c01hcmdpbnMoMCwgNCwgMCwgMCkKICAgICAgICBkZXRhaWxfbGF5b3V0LnNldFNwYWNpbmcoMikKCiAgICAgICAg"
    "ZGV0YWlsX2hlYWRlciA9IFFIQm94TGF5b3V0KCkKICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFdpZGdldChfc2VjdGlvbl9sYmwo"
    "IuKdpyBGVUxMIFJVTEUiKSkKICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFN0cmV0Y2goKQogICAgICAgIHNlbGYuX2J0bl9lZGl0"
    "X3J1bGUgPSBfZ290aGljX2J0bigiRWRpdCIpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRGaXhlZFdpZHRoKDUwKQog"
    "ICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0Q2hlY2thYmxlKFRydWUpCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS50"
    "b2dnbGVkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlX2VkaXRfbW9kZSkKICAgICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlID0gX2dvdGhp"
    "Y19idG4oIlNhdmUiKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuc2V0Rml4ZWRXaWR0aCg1MCkKICAgICAgICBzZWxmLl9i"
    "dG5fc2F2ZV9ydWxlLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5jbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5fc2F2ZV9ydWxlX2VkaXQpCiAgICAgICAgZGV0YWlsX2hlYWRlci5hZGRXaWRnZXQoc2VsZi5fYnRuX2VkaXRfcnVsZSkK"
    "ICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFdpZGdldChzZWxmLl9idG5fc2F2ZV9ydWxlKQogICAgICAgIGRldGFpbF9sYXlvdXQu"
    "YWRkTGF5b3V0KGRldGFpbF9oZWFkZXIpCgogICAgICAgIHNlbGYuX2RldGFpbCA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5f"
    "ZGV0YWlsLnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fZGV0YWlsLnNldE1pbmltdW1IZWlnaHQoMTIwKQogICAgICAg"
    "IHNlbGYuX2RldGFpbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19H"
    "T0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJmb250LWZh"
    "bWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDExcHg7IHBhZGRpbmc6IDRweDsiCiAgICAgICAgKQogICAgICAg"
    "IGRldGFpbF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2RldGFpbCkKICAgICAgICBzcGxpdHRlci5hZGRXaWRnZXQoZGV0YWlsX3dp"
    "ZGdldCkKICAgICAgICBzcGxpdHRlci5zZXRTaXplcyhbMzAwLCAxODBdKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNwbGl0dGVy"
    "LCAxKQoKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9lZGl0aW5nX3JvdzogaW50"
    "ID0gLTEKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHEgICAgPSBzZWxmLl9zZWFyY2gudGV4dCgpCiAg"
    "ICAgICAgbGFuZyA9IHNlbGYuX2xhbmdfZmlsdGVyLmN1cnJlbnRUZXh0KCkKICAgICAgICBsYW5nID0gIiIgaWYgbGFuZyA9PSAi"
    "QWxsIiBlbHNlIGxhbmcKICAgICAgICBzZWxmLl9yZWNvcmRzID0gc2VsZi5fZGIuc2VhcmNoKHF1ZXJ5PXEsIGxhbmd1YWdlPWxh"
    "bmcpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29yZHM6CiAg"
    "ICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLmluc2VydFJvdyhyKQog"
    "ICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDAsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5n"
    "ZXQoImxhbmd1YWdlIiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIsIDEsCiAgICAgICAgICAgICAgICBR"
    "VGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoInJlZmVyZW5jZV9rZXkiLCIiKSkpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0"
    "ZW0ociwgMiwKICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgic3VtbWFyeSIsIiIpKSkKICAgICAgICAg"
    "ICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAzLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJlbnZp"
    "cm9ubWVudCIsIiIpKSkKCiAgICBkZWYgX29uX3NlbGVjdChzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxl"
    "LmN1cnJlbnRSb3coKQogICAgICAgIHNlbGYuX2VkaXRpbmdfcm93ID0gcm93CiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2Vs"
    "Zi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJlYyA9IHNlbGYuX3JlY29yZHNbcm93XQogICAgICAgICAgICBzZWxmLl9kZXRhaWwu"
    "c2V0UGxhaW5UZXh0KAogICAgICAgICAgICAgICAgcmVjLmdldCgiZnVsbF9ydWxlIiwiIikgKyAiXG5cbiIgKwogICAgICAgICAg"
    "ICAgICAgKCJSZXNvbHV0aW9uOiAiICsgcmVjLmdldCgicmVzb2x1dGlvbiIsIiIpIGlmIHJlYy5nZXQoInJlc29sdXRpb24iKSBl"
    "bHNlICIiKQogICAgICAgICAgICApCiAgICAgICAgICAgICMgUmVzZXQgZWRpdCBtb2RlIG9uIG5ldyBzZWxlY3Rpb24KICAgICAg"
    "ICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRDaGVja2VkKEZhbHNlKQoKICAgIGRlZiBfdG9nZ2xlX2VkaXRfbW9kZShzZWxm"
    "LCBlZGl0aW5nOiBib29sKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2RldGFpbC5zZXRSZWFkT25seShub3QgZWRpdGluZykKICAg"
    "ICAgICBzZWxmLl9idG5fc2F2ZV9ydWxlLnNldFZpc2libGUoZWRpdGluZykKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNl"
    "dFRleHQoIkNhbmNlbCIgaWYgZWRpdGluZyBlbHNlICJFZGl0IikKICAgICAgICBpZiBlZGl0aW5nOgogICAgICAgICAgICBzZWxm"
    "Ll9kZXRhaWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dP"
    "TER9OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0dPTERfRElNfTsgIgogICAgICAgICAgICAgICAg"
    "ZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDExcHg7IHBhZGRpbmc6IDRweDsiCiAgICAgICAg"
    "ICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLl9kZXRhaWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAg"
    "IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNv"
    "bGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1z"
    "aXplOiAxMXB4OyBwYWRkaW5nOiA0cHg7IgogICAgICAgICAgICApCiAgICAgICAgICAgICMgUmVsb2FkIG9yaWdpbmFsIGNvbnRl"
    "bnQgb24gY2FuY2VsCiAgICAgICAgICAgIHNlbGYuX29uX3NlbGVjdCgpCgogICAgZGVmIF9zYXZlX3J1bGVfZWRpdChzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX2VkaXRpbmdfcm93CiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVj"
    "b3Jkcyk6CiAgICAgICAgICAgIHRleHQgPSBzZWxmLl9kZXRhaWwudG9QbGFpblRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgICMg"
    "U3BsaXQgcmVzb2x1dGlvbiBiYWNrIG91dCBpZiBwcmVzZW50CiAgICAgICAgICAgIGlmICJcblxuUmVzb2x1dGlvbjogIiBpbiB0"
    "ZXh0OgogICAgICAgICAgICAgICAgcGFydHMgPSB0ZXh0LnNwbGl0KCJcblxuUmVzb2x1dGlvbjogIiwgMSkKICAgICAgICAgICAg"
    "ICAgIGZ1bGxfcnVsZSAgPSBwYXJ0c1swXS5zdHJpcCgpCiAgICAgICAgICAgICAgICByZXNvbHV0aW9uID0gcGFydHNbMV0uc3Ry"
    "aXAoKQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgZnVsbF9ydWxlICA9IHRleHQKICAgICAgICAgICAgICAgIHJl"
    "c29sdXRpb24gPSBzZWxmLl9yZWNvcmRzW3Jvd10uZ2V0KCJyZXNvbHV0aW9uIiwgIiIpCiAgICAgICAgICAgIHNlbGYuX3JlY29y"
    "ZHNbcm93XVsiZnVsbF9ydWxlIl0gID0gZnVsbF9ydWxlCiAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbcm93XVsicmVzb2x1dGlv"
    "biJdID0gcmVzb2x1dGlvbgogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9kYi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAg"
    "ICAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRDaGVja2VkKEZhbHNlKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoK"
    "ICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRX"
    "aW5kb3dUaXRsZSgiQWRkIExlc3NvbiIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBj"
    "b2xvcjoge0NfR09MRH07IikKICAgICAgICBkbGcucmVzaXplKDUwMCwgNDAwKQogICAgICAgIGZvcm0gPSBRRm9ybUxheW91dChk"
    "bGcpCiAgICAgICAgZW52ICA9IFFMaW5lRWRpdCgiTFNMIikKICAgICAgICBsYW5nID0gUUxpbmVFZGl0KCJMU0wiKQogICAgICAg"
    "IHJlZiAgPSBRTGluZUVkaXQoKQogICAgICAgIHN1bW0gPSBRTGluZUVkaXQoKQogICAgICAgIHJ1bGUgPSBRVGV4dEVkaXQoKQog"
    "ICAgICAgIHJ1bGUuc2V0TWF4aW11bUhlaWdodCgxMDApCiAgICAgICAgcmVzICA9IFFMaW5lRWRpdCgpCiAgICAgICAgbGluayA9"
    "IFFMaW5lRWRpdCgpCiAgICAgICAgZm9yIGxhYmVsLCB3IGluIFsKICAgICAgICAgICAgKCJFbnZpcm9ubWVudDoiLCBlbnYpLCAo"
    "Ikxhbmd1YWdlOiIsIGxhbmcpLAogICAgICAgICAgICAoIlJlZmVyZW5jZSBLZXk6IiwgcmVmKSwgKCJTdW1tYXJ5OiIsIHN1bW0p"
    "LAogICAgICAgICAgICAoIkZ1bGwgUnVsZToiLCBydWxlKSwgKCJSZXNvbHV0aW9uOiIsIHJlcyksCiAgICAgICAgICAgICgiTGlu"
    "azoiLCBsaW5rKSwKICAgICAgICBdOgogICAgICAgICAgICBmb3JtLmFkZFJvdyhsYWJlbCwgdykKICAgICAgICBidG5zID0gUUhC"
    "b3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhpY19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAg"
    "ICAgICBvay5jbGlja2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQogICAgICAg"
    "IGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9ybS5hZGRSb3coYnRucykKICAgICAgICBp"
    "ZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgc2VsZi5fZGIuYWRkKAogICAg"
    "ICAgICAgICAgICAgZW52aXJvbm1lbnQ9ZW52LnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgbGFuZ3VhZ2U9bGFuZy50"
    "ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIHJlZmVyZW5jZV9rZXk9cmVmLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAg"
    "ICAgICAgc3VtbWFyeT1zdW1tLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgZnVsbF9ydWxlPXJ1bGUudG9QbGFpblRl"
    "eHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgcmVzb2x1dGlvbj1yZXMudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAg"
    "ICBsaW5rPWxpbmsudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBk"
    "ZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAg"
    "IGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAgICAgICAgICByZWNfaWQgPSBzZWxmLl9yZWNvcmRzW3Jvd10u"
    "Z2V0KCJpZCIsIiIpCiAgICAgICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgICAgICBzZWxm"
    "LCAiRGVsZXRlIExlc3NvbiIsCiAgICAgICAgICAgICAgICAiRGVsZXRlIHRoaXMgbGVzc29uPyBDYW5ub3QgYmUgdW5kb25lLiIs"
    "CiAgICAgICAgICAgICAgICBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRv"
    "bi5ObwogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllczoK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX2RiLmRlbGV0ZShyZWNfaWQpCiAgICAgICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKCiMg"
    "4pSA4pSAIE1PRFVMRSBUUkFDS0VSIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTW9kdWxlVHJhY2tlclRhYihRV2lkZ2V0"
    "KToKICAgICIiIgogICAgUGVyc29uYWwgbW9kdWxlIHBpcGVsaW5lIHRyYWNrZXIuCiAgICBUcmFjayBwbGFubmVkL2luLXByb2dy"
    "ZXNzL2J1aWx0IG1vZHVsZXMgYXMgdGhleSBhcmUgZGVzaWduZWQuCiAgICBFYWNoIG1vZHVsZSBoYXM6IE5hbWUsIFN0YXR1cywg"
    "RGVzY3JpcHRpb24sIE5vdGVzLgogICAgRXhwb3J0IHRvIFRYVCBmb3IgcGFzdGluZyBpbnRvIHNlc3Npb25zLgogICAgSW1wb3J0"
    "OiBwYXN0ZSBhIGZpbmFsaXplZCBzcGVjLCBpdCBwYXJzZXMgbmFtZSBhbmQgZGV0YWlscy4KICAgIFRoaXMgaXMgYSBkZXNpZ24g"
    "bm90ZWJvb2sg4oCUIG5vdCBjb25uZWN0ZWQgdG8gZGVja19idWlsZGVyJ3MgTU9EVUxFIHJlZ2lzdHJ5LgogICAgIiIiCgogICAg"
    "U1RBVFVTRVMgPSBbIklkZWEiLCAiRGVzaWduaW5nIiwgIlJlYWR5IHRvIEJ1aWxkIiwgIlBhcnRpYWwiLCAiQnVpbHQiXQoKICAg"
    "IGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAg"
    "c2VsZi5fcGF0aCA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gIm1vZHVsZV90cmFja2VyLmpzb25sIgogICAgICAgIHNlbGYuX3Jl"
    "Y29yZHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAg"
    "IGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290"
    "LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICAjIEJ1dHRv"
    "biBiYXIKICAgICAgICBidG5fYmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hZGQgICAgPSBfZ290aGljX2J0"
    "bigiQWRkIE1vZHVsZSIpCiAgICAgICAgc2VsZi5fYnRuX2VkaXQgICA9IF9nb3RoaWNfYnRuKCJFZGl0IikKICAgICAgICBzZWxm"
    "Ll9idG5fZGVsZXRlID0gX2dvdGhpY19idG4oIkRlbGV0ZSIpCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydCA9IF9nb3RoaWNfYnRu"
    "KCJFeHBvcnQgVFhUIikKICAgICAgICBzZWxmLl9idG5faW1wb3J0ID0gX2dvdGhpY19idG4oIkltcG9ydCBTcGVjIikKICAgICAg"
    "ICBmb3IgYiBpbiAoc2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRuX2VkaXQsIHNlbGYuX2J0bl9kZWxldGUsCiAgICAgICAgICAgICAg"
    "ICAgIHNlbGYuX2J0bl9leHBvcnQsIHNlbGYuX2J0bl9pbXBvcnQpOgogICAgICAgICAgICBiLnNldE1pbmltdW1XaWR0aCg4MCkK"
    "ICAgICAgICAgICAgYi5zZXRNaW5pbXVtSGVpZ2h0KDI2KQogICAgICAgICAgICBidG5fYmFyLmFkZFdpZGdldChiKQogICAgICAg"
    "IGJ0bl9iYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYnRuX2JhcikKCiAgICAgICAgc2VsZi5fYnRuX2Fk"
    "ZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIHNlbGYuX2J0bl9lZGl0LmNsaWNrZWQuY29ubmVjdChzZWxm"
    "Ll9kb19lZGl0KQogICAgICAgIHNlbGYuX2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAg"
    "ICBzZWxmLl9idG5fZXhwb3J0LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19leHBvcnQpCiAgICAgICAgc2VsZi5fYnRuX2ltcG9y"
    "dC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9faW1wb3J0KQoKICAgICAgICAjIFRhYmxlCiAgICAgICAgc2VsZi5fdGFibGUgPSBR"
    "VGFibGVXaWRnZXQoMCwgMykKICAgICAgICBzZWxmLl90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiTW9kdWxlIE5h"
    "bWUiLCAiU3RhdHVzIiwgIkRlc2NyaXB0aW9uIl0pCiAgICAgICAgaGggPSBzZWxmLl90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkK"
    "ICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNl"
    "bGYuX3RhYmxlLnNldENvbHVtbldpZHRoKDAsIDE2MCkKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgxLCBRSGVhZGVy"
    "Vmlldy5SZXNpemVNb2RlLkZpeGVkKQogICAgICAgIHNlbGYuX3RhYmxlLnNldENvbHVtbldpZHRoKDEsIDEwMCkKICAgICAgICBo"
    "aC5zZXRTZWN0aW9uUmVzaXplTW9kZSgyLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFi"
    "bGUuc2V0U2VsZWN0aW9uQmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNl"
    "bGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMoVHJ1ZSkKICAgICAgICBzZWxmLl90"
    "YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUoKSkKICAgICAgICBzZWxmLl90YWJsZS5pdGVtU2VsZWN0aW9u"
    "Q2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX3NlbGVjdCkKCiAgICAgICAgIyBTcGxpdHRlcgogICAgICAgIHNwbGl0dGVyID0gUVNw"
    "bGl0dGVyKFF0Lk9yaWVudGF0aW9uLlZlcnRpY2FsKQogICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChzZWxmLl90YWJsZSkKCiAg"
    "ICAgICAgIyBOb3RlcyBwYW5lbAogICAgICAgIG5vdGVzX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIG5vdGVzX2xheW91dCA9"
    "IFFWQm94TGF5b3V0KG5vdGVzX3dpZGdldCkKICAgICAgICBub3Rlc19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDQsIDAs"
    "IDApCiAgICAgICAgbm90ZXNfbGF5b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBub3Rlc19sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0"
    "aW9uX2xibCgi4p2nIE5PVEVTIikpCiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2Vs"
    "Zi5fbm90ZXNfZGlzcGxheS5zZXRSZWFkT25seShUcnVlKQogICAgICAgIHNlbGYuX25vdGVzX2Rpc3BsYXkuc2V0TWluaW11bUhl"
    "aWdodCgxMjApCiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91"
    "bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07"
    "ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDExcHg7IHBhZGRpbmc6"
    "IDRweDsiCiAgICAgICAgKQogICAgICAgIG5vdGVzX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fbm90ZXNfZGlzcGxheSkKICAgICAg"
    "ICBzcGxpdHRlci5hZGRXaWRnZXQobm90ZXNfd2lkZ2V0KQogICAgICAgIHNwbGl0dGVyLnNldFNpemVzKFsyNTAsIDE1MF0pCiAg"
    "ICAgICAgcm9vdC5hZGRXaWRnZXQoc3BsaXR0ZXIsIDEpCgogICAgICAgICMgQ291bnQgbGFiZWwKICAgICAgICBzZWxmLl9jb3Vu"
    "dF9sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5fY291bnRfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29s"
    "b3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAg"
    "ICkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9jb3VudF9sYmwpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9yZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFJvd0Nv"
    "dW50KDApCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICByID0gc2VsZi5fdGFibGUucm93Q291"
    "bnQoKQogICAgICAgICAgICBzZWxmLl90YWJsZS5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShy"
    "LCAwLCBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoIm5hbWUiLCAiIikpKQogICAgICAgICAgICBzdGF0dXNfaXRlbSA9IFFUYWJs"
    "ZVdpZGdldEl0ZW0ocmVjLmdldCgic3RhdHVzIiwgIklkZWEiKSkKICAgICAgICAgICAgIyBDb2xvciBieSBzdGF0dXMKICAgICAg"
    "ICAgICAgc3RhdHVzX2NvbG9ycyA9IHsKICAgICAgICAgICAgICAgICJJZGVhIjogICAgICAgICAgICAgQ19URVhUX0RJTSwKICAg"
    "ICAgICAgICAgICAgICJEZXNpZ25pbmciOiAgICAgICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAgICAgICJSZWFkeSB0byBCdWls"
    "ZCI6ICAgQ19QVVJQTEUsCiAgICAgICAgICAgICAgICAiUGFydGlhbCI6ICAgICAgICAgICIjY2M4ODQ0IiwKICAgICAgICAgICAg"
    "ICAgICJCdWlsdCI6ICAgICAgICAgICAgQ19HUkVFTiwKICAgICAgICAgICAgfQogICAgICAgICAgICBzdGF0dXNfaXRlbS5zZXRG"
    "b3JlZ3JvdW5kKAogICAgICAgICAgICAgICAgUUNvbG9yKHN0YXR1c19jb2xvcnMuZ2V0KHJlYy5nZXQoInN0YXR1cyIsIklkZWEi"
    "KSwgQ19URVhUX0RJTSkpCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAxLCBzdGF0dXNf"
    "aXRlbSkKICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRlbShyLCAyLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRl"
    "bShyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsICIiKVs6ODBdKSkKICAgICAgICBjb3VudHMgPSB7fQogICAgICAgIGZvciByZWMgaW4g"
    "c2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgcyA9IHJlYy5nZXQoInN0YXR1cyIsICJJZGVhIikKICAgICAgICAgICAgY291bnRz"
    "W3NdID0gY291bnRzLmdldChzLCAwKSArIDEKICAgICAgICBjb3VudF9zdHIgPSAiICAiLmpvaW4oZiJ7c306IHtufSIgZm9yIHMs"
    "IG4gaW4gY291bnRzLml0ZW1zKCkpCiAgICAgICAgc2VsZi5fY291bnRfbGJsLnNldFRleHQoCiAgICAgICAgICAgIGYiVG90YWw6"
    "IHtsZW4oc2VsZi5fcmVjb3Jkcyl9ICAge2NvdW50X3N0cn0iCiAgICAgICAgKQoKICAgIGRlZiBfb25fc2VsZWN0KHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2Vs"
    "Zi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJlYyA9IHNlbGYuX3JlY29yZHNbcm93XQogICAgICAgICAgICBzZWxmLl9ub3Rlc19k"
    "aXNwbGF5LnNldFBsYWluVGV4dChyZWMuZ2V0KCJub3RlcyIsICIiKSkKCiAgICBkZWYgX2RvX2FkZChzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHNlbGYuX29wZW5fZWRpdF9kaWFsb2coKQoKICAgIGRlZiBfZG9fZWRpdChzZWxmKSAtPiBOb25lOgogICAgICAgIHJv"
    "dyA9IHNlbGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3JlY29yZHMpOgogICAg"
    "ICAgICAgICBzZWxmLl9vcGVuX2VkaXRfZGlhbG9nKHNlbGYuX3JlY29yZHNbcm93XSwgcm93KQoKICAgIGRlZiBfb3Blbl9lZGl0"
    "X2RpYWxvZyhzZWxmLCByZWM6IGRpY3QgPSBOb25lLCByb3c6IGludCA9IC0xKSAtPiBOb25lOgogICAgICAgIGRsZyA9IFFEaWFs"
    "b2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIk1vZHVsZSIgaWYgbm90IHJlYyBlbHNlIGYiRWRpdDoge3JlYy5n"
    "ZXQoJ25hbWUnLCcnKX0iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtD"
    "X0dPTER9OyIpCiAgICAgICAgZGxnLnJlc2l6ZSg1NDAsIDQ0MCkKICAgICAgICBmb3JtID0gUVZCb3hMYXlvdXQoZGxnKQoKICAg"
    "ICAgICBuYW1lX2ZpZWxkID0gUUxpbmVFZGl0KHJlYy5nZXQoIm5hbWUiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAgICBuYW1l"
    "X2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgiTW9kdWxlIG5hbWUiKQoKICAgICAgICBzdGF0dXNfY29tYm8gPSBRQ29tYm9Cb3go"
    "KQogICAgICAgIHN0YXR1c19jb21iby5hZGRJdGVtcyhzZWxmLlNUQVRVU0VTKQogICAgICAgIGlmIHJlYzoKICAgICAgICAgICAg"
    "aWR4ID0gc3RhdHVzX2NvbWJvLmZpbmRUZXh0KHJlYy5nZXQoInN0YXR1cyIsIklkZWEiKSkKICAgICAgICAgICAgaWYgaWR4ID49"
    "IDA6CiAgICAgICAgICAgICAgICBzdGF0dXNfY29tYm8uc2V0Q3VycmVudEluZGV4KGlkeCkKCiAgICAgICAgZGVzY19maWVsZCA9"
    "IFFMaW5lRWRpdChyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIGRlc2NfZmllbGQuc2V0"
    "UGxhY2Vob2xkZXJUZXh0KCJPbmUtbGluZSBkZXNjcmlwdGlvbiIpCgogICAgICAgIG5vdGVzX2ZpZWxkID0gUVRleHRFZGl0KCkK"
    "ICAgICAgICBub3Rlc19maWVsZC5zZXRQbGFpblRleHQocmVjLmdldCgibm90ZXMiLCIiKSBpZiByZWMgZWxzZSAiIikKICAgICAg"
    "ICBub3Rlc19maWVsZC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgICJGdWxsIG5vdGVzIOKAlCBzcGVjLCBpZGVhcywg"
    "cmVxdWlyZW1lbnRzLCBlZGdlIGNhc2VzLi4uIgogICAgICAgICkKICAgICAgICBub3Rlc19maWVsZC5zZXRNaW5pbXVtSGVpZ2h0"
    "KDIwMCkKCiAgICAgICAgZm9yIGxhYmVsLCB3aWRnZXQgaW4gWwogICAgICAgICAgICAoIk5hbWU6IiwgbmFtZV9maWVsZCksCiAg"
    "ICAgICAgICAgICgiU3RhdHVzOiIsIHN0YXR1c19jb21ibyksCiAgICAgICAgICAgICgiRGVzY3JpcHRpb246IiwgZGVzY19maWVs"
    "ZCksCiAgICAgICAgICAgICgiTm90ZXM6Iiwgbm90ZXNfZmllbGQpLAogICAgICAgIF06CiAgICAgICAgICAgIHJvd19sYXlvdXQg"
    "PSBRSEJveExheW91dCgpCiAgICAgICAgICAgIGxibCA9IFFMYWJlbChsYWJlbCkKICAgICAgICAgICAgbGJsLnNldEZpeGVkV2lk"
    "dGgoOTApCiAgICAgICAgICAgIHJvd19sYXlvdXQuYWRkV2lkZ2V0KGxibCkKICAgICAgICAgICAgcm93X2xheW91dC5hZGRXaWRn"
    "ZXQod2lkZ2V0KQogICAgICAgICAgICBmb3JtLmFkZExheW91dChyb3dfbGF5b3V0KQoKICAgICAgICBidG5fcm93ID0gUUhCb3hM"
    "YXlvdXQoKQogICAgICAgIGJ0bl9zYXZlICAgPSBfZ290aGljX2J0bigiU2F2ZSIpCiAgICAgICAgYnRuX2NhbmNlbCA9IF9nb3Ro"
    "aWNfYnRuKCJDYW5jZWwiKQogICAgICAgIGJ0bl9zYXZlLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KQogICAgICAgIGJ0bl9j"
    "YW5jZWwuY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX3NhdmUpCiAgICAg"
    "ICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBmb3JtLmFkZExheW91dChidG5fcm93KQoKICAgICAgICBp"
    "ZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgbmV3X3JlYyA9IHsKICAgICAg"
    "ICAgICAgICAgICJpZCI6ICAgICAgICAgIHJlYy5nZXQoImlkIiwgc3RyKHV1aWQudXVpZDQoKSkpIGlmIHJlYyBlbHNlIHN0cih1"
    "dWlkLnV1aWQ0KCkpLAogICAgICAgICAgICAgICAgIm5hbWUiOiAgICAgICAgbmFtZV9maWVsZC50ZXh0KCkuc3RyaXAoKSwKICAg"
    "ICAgICAgICAgICAgICJzdGF0dXMiOiAgICAgIHN0YXR1c19jb21iby5jdXJyZW50VGV4dCgpLAogICAgICAgICAgICAgICAgImRl"
    "c2NyaXB0aW9uIjogZGVzY19maWVsZC50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJub3RlcyI6ICAgICAgIG5vdGVz"
    "X2ZpZWxkLnRvUGxhaW5UZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgICJjcmVhdGVkIjogICAgIHJlYy5nZXQoImNyZWF0"
    "ZWQiLCBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSkgaWYgcmVjIGVsc2UgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAg"
    "ICAgICAgICAgICAgICAibW9kaWZpZWQiOiAgICBkYXRldGltZS5ub3coKS5pc29mb3JtYXQoKSwKICAgICAgICAgICAgfQogICAg"
    "ICAgICAgICBpZiByb3cgPj0gMDoKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHNbcm93XSA9IG5ld19yZWMKICAgICAgICAg"
    "ICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMuYXBwZW5kKG5ld19yZWMpCiAgICAgICAgICAgIHdyaXRlX2pz"
    "b25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19kZWxl"
    "dGUoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJv"
    "dyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgbmFtZSA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQoIm5hbWUiLCJ0"
    "aGlzIG1vZHVsZSIpCiAgICAgICAgICAgIHJlcGx5ID0gUU1lc3NhZ2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgICAgICBzZWxm"
    "LCAiRGVsZXRlIE1vZHVsZSIsCiAgICAgICAgICAgICAgICBmIkRlbGV0ZSAne25hbWV9Jz8gQ2Fubm90IGJlIHVuZG9uZS4iLAog"
    "ICAgICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24u"
    "Tm8KICAgICAgICAgICAgKQogICAgICAgICAgICBpZiByZXBseSA9PSBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXM6CiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzLnBvcChyb3cpCiAgICAgICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRo"
    "LCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2V4cG9ydChzZWxmKSAt"
    "PiBOb25lOgogICAgICAgIHRyeToKICAgICAgICAgICAgZXhwb3J0X2RpciA9IGNmZ19wYXRoKCJleHBvcnRzIikKICAgICAgICAg"
    "ICAgZXhwb3J0X2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAgICAgICAgICAgIHRzID0gZGF0ZXRpbWUu"
    "bm93KCkuc3RyZnRpbWUoIiVZJW0lZF8lSCVNJVMiKQogICAgICAgICAgICBvdXRfcGF0aCA9IGV4cG9ydF9kaXIgLyBmIm1vZHVs"
    "ZXNfe3RzfS50eHQiCiAgICAgICAgICAgIGxpbmVzID0gWwogICAgICAgICAgICAgICAgIkVDSE8gREVDSyDigJQgTU9EVUxFIFRS"
    "QUNLRVIgRVhQT1JUIiwKICAgICAgICAgICAgICAgIGYiRXhwb3J0ZWQ6IHtkYXRldGltZS5ub3coKS5zdHJmdGltZSgnJVktJW0t"
    "JWQgJUg6JU06JVMnKX0iLAogICAgICAgICAgICAgICAgZiJUb3RhbCBtb2R1bGVzOiB7bGVuKHNlbGYuX3JlY29yZHMpfSIsCiAg"
    "ICAgICAgICAgICAgICAiPSIgKiA2MCwKICAgICAgICAgICAgICAgICIiLAogICAgICAgICAgICBdCiAgICAgICAgICAgIGZvciBy"
    "ZWMgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgICAgIGxpbmVzLmV4dGVuZChbCiAgICAgICAgICAgICAgICAgICAgZiJN"
    "T0RVTEU6IHtyZWMuZ2V0KCduYW1lJywnJyl9IiwKICAgICAgICAgICAgICAgICAgICBmIlN0YXR1czoge3JlYy5nZXQoJ3N0YXR1"
    "cycsJycpfSIsCiAgICAgICAgICAgICAgICAgICAgZiJEZXNjcmlwdGlvbjoge3JlYy5nZXQoJ2Rlc2NyaXB0aW9uJywnJyl9IiwK"
    "ICAgICAgICAgICAgICAgICAgICAiIiwKICAgICAgICAgICAgICAgICAgICAiTm90ZXM6IiwKICAgICAgICAgICAgICAgICAgICBy"
    "ZWMuZ2V0KCJub3RlcyIsIiIpLAogICAgICAgICAgICAgICAgICAgICIiLAogICAgICAgICAgICAgICAgICAgICItIiAqIDQwLAog"
    "ICAgICAgICAgICAgICAgICAgICIiLAogICAgICAgICAgICAgICAgXSkKICAgICAgICAgICAgb3V0X3BhdGgud3JpdGVfdGV4dCgi"
    "XG4iLmpvaW4obGluZXMpLCBlbmNvZGluZz0idXRmLTgiKQogICAgICAgICAgICBRQXBwbGljYXRpb24uY2xpcGJvYXJkKCkuc2V0"
    "VGV4dCgiXG4iLmpvaW4obGluZXMpKQogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbigKICAgICAgICAgICAgICAg"
    "IHNlbGYsICJFeHBvcnRlZCIsCiAgICAgICAgICAgICAgICBmIk1vZHVsZSB0cmFja2VyIGV4cG9ydGVkIHRvOlxue291dF9wYXRo"
    "fVxuXG5BbHNvIGNvcGllZCB0byBjbGlwYm9hcmQuIgogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBl"
    "OgogICAgICAgICAgICBRTWVzc2FnZUJveC53YXJuaW5nKHNlbGYsICJFeHBvcnQgRXJyb3IiLCBzdHIoZSkpCgogICAgZGVmIF9k"
    "b19pbXBvcnQoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiJJbXBvcnQgYSBtb2R1bGUgc3BlYyBmcm9tIGNsaXBib2FyZCBvciB0"
    "eXBlZCB0ZXh0LiIiIgogICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIkltcG9y"
    "dCBNb2R1bGUgU3BlYyIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0Nf"
    "R09MRH07IikKICAgICAgICBkbGcucmVzaXplKDUwMCwgMzQwKQogICAgICAgIGxheW91dCA9IFFWQm94TGF5b3V0KGRsZykKICAg"
    "ICAgICBsYXlvdXQuYWRkV2lkZ2V0KFFMYWJlbCgKICAgICAgICAgICAgIlBhc3RlIGEgbW9kdWxlIHNwZWMgYmVsb3cuXG4iCiAg"
    "ICAgICAgICAgICJGaXJzdCBsaW5lIHdpbGwgYmUgdXNlZCBhcyB0aGUgbW9kdWxlIG5hbWUuIgogICAgICAgICkpCiAgICAgICAg"
    "dGV4dF9maWVsZCA9IFFUZXh0RWRpdCgpCiAgICAgICAgdGV4dF9maWVsZC5zZXRQbGFjZWhvbGRlclRleHQoIlBhc3RlIG1vZHVs"
    "ZSBzcGVjIGhlcmUuLi4iKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQodGV4dF9maWVsZCwgMSkKICAgICAgICBidG5fcm93ID0g"
    "UUhCb3hMYXlvdXQoKQogICAgICAgIGJ0bl9vayAgICAgPSBfZ290aGljX2J0bigiSW1wb3J0IikKICAgICAgICBidG5fY2FuY2Vs"
    "ID0gX2dvdGhpY19idG4oIkNhbmNlbCIpCiAgICAgICAgYnRuX29rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KQogICAgICAg"
    "IGJ0bl9jYW5jZWwuY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX29rKQog"
    "ICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9jYW5jZWwpCiAgICAgICAgbGF5b3V0LmFkZExheW91dChidG5fcm93KQoKICAg"
    "ICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgcmF3ID0gdGV4dF9m"
    "aWVsZC50b1BsYWluVGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgaWYgbm90IHJhdzoKICAgICAgICAgICAgICAgIHJldHVybgog"
    "ICAgICAgICAgICBsaW5lcyA9IHJhdy5zcGxpdGxpbmVzKCkKICAgICAgICAgICAgIyBGaXJzdCBub24tZW1wdHkgbGluZSA9IG5h"
    "bWUKICAgICAgICAgICAgbmFtZSA9ICIiCiAgICAgICAgICAgIGZvciBsaW5lIGluIGxpbmVzOgogICAgICAgICAgICAgICAgaWYg"
    "bGluZS5zdHJpcCgpOgogICAgICAgICAgICAgICAgICAgIG5hbWUgPSBsaW5lLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBi"
    "cmVhawogICAgICAgICAgICBuZXdfcmVjID0gewogICAgICAgICAgICAgICAgImlkIjogICAgICAgICAgc3RyKHV1aWQudXVpZDQo"
    "KSksCiAgICAgICAgICAgICAgICAibmFtZSI6ICAgICAgICBuYW1lWzo2MF0sCiAgICAgICAgICAgICAgICAic3RhdHVzIjogICAg"
    "ICAiSWRlYSIsCiAgICAgICAgICAgICAgICAiZGVzY3JpcHRpb24iOiAiIiwKICAgICAgICAgICAgICAgICJub3RlcyI6ICAgICAg"
    "IHJhdywKICAgICAgICAgICAgICAgICJjcmVhdGVkIjogICAgIGRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCgpLAogICAgICAgICAg"
    "ICAgICAgIm1vZGlmaWVkIjogICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KCksCiAgICAgICAgICAgIH0KICAgICAgICAgICAg"
    "c2VsZi5fcmVjb3Jkcy5hcHBlbmQobmV3X3JlYykKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVj"
    "b3JkcykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCgojIOKUgOKUgCBQQVNTIDUgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiMgQWxsIHRhYiBjb250ZW50IGNsYXNzZXMgZGVmaW5lZC4KIyBTTFNjYW5zVGFiOiByZWJ1aWx0IOKA"
    "lCBEZWxldGUgYWRkZWQsIE1vZGlmeSBmaXhlZCwgdGltZXN0YW1wIHBhcnNlciBmaXhlZCwKIyAgICAgICAgICAgICBjYXJkL2dy"
    "aW1vaXJlIHN0eWxlLCBjb3B5LXRvLWNsaXBib2FyZCBjb250ZXh0IG1lbnUuCiMgU0xDb21tYW5kc1RhYjogZ290aGljIHRhYmxl"
    "LCDip4kgQ29weSBDb21tYW5kIGJ1dHRvbi4KIyBKb2JUcmFja2VyVGFiOiBmdWxsIHJlYnVpbGQg4oCUIG11bHRpLXNlbGVjdCwg"
    "YXJjaGl2ZS9yZXN0b3JlLCBDU1YvVFNWIGV4cG9ydC4KIyBTZWxmVGFiOiBpbm5lciBzYW5jdHVtIGZvciBpZGxlIG5hcnJhdGl2"
    "ZSBhbmQgcmVmbGVjdGlvbiBvdXRwdXQuCiMgRGlhZ25vc3RpY3NUYWI6IHN0cnVjdHVyZWQgbG9nIHdpdGggbGV2ZWwtY29sb3Jl"
    "ZCBvdXRwdXQuCiMgTGVzc29uc1RhYjogTFNMIEZvcmJpZGRlbiBSdWxlc2V0IGJyb3dzZXIgd2l0aCBhZGQvZGVsZXRlL3NlYXJj"
    "aC4KIwojIE5leHQ6IFBhc3MgNiDigJQgTWFpbiBXaW5kb3cKIyAoTW9yZ2FubmFEZWNrIGNsYXNzLCBmdWxsIGxheW91dCwgQVBT"
    "Y2hlZHVsZXIsIGZpcnN0LXJ1biBmbG93LAojICBkZXBlbmRlbmN5IGJvb3RzdHJhcCwgc2hvcnRjdXQgY3JlYXRpb24sIHN0YXJ0"
    "dXAgc2VxdWVuY2UpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDY6IE1BSU4gV0lORE9XICYgRU5U"
    "UlkgUE9JTlQKIwojIENvbnRhaW5zOgojICAgYm9vdHN0cmFwX2NoZWNrKCkgICAgIOKAlCBkZXBlbmRlbmN5IHZhbGlkYXRpb24g"
    "KyBhdXRvLWluc3RhbGwgYmVmb3JlIFVJCiMgICBGaXJzdFJ1bkRpYWxvZyAgICAgICAg4oCUIG1vZGVsIHBhdGggKyBjb25uZWN0"
    "aW9uIHR5cGUgc2VsZWN0aW9uCiMgICBKb3VybmFsU2lkZWJhciAgICAgICAg4oCUIGNvbGxhcHNpYmxlIGxlZnQgc2lkZWJhciAo"
    "c2Vzc2lvbiBicm93c2VyICsgam91cm5hbCkKIyAgIFRvcnBvclBhbmVsICAgICAgICAgICDigJQgQVdBS0UgLyBBVVRPIC8gU1VT"
    "UEVORCBzdGF0ZSB0b2dnbGUKIyAgIE1vcmdhbm5hRGVjayAgICAgICAgICDigJQgbWFpbiB3aW5kb3csIGZ1bGwgbGF5b3V0LCBh"
    "bGwgc2lnbmFsIGNvbm5lY3Rpb25zCiMgICBtYWluKCkgICAgICAgICAgICAgICAg4oCUIGVudHJ5IHBvaW50IHdpdGggYm9vdHN0"
    "cmFwIHNlcXVlbmNlCiMg4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQCgppbXBvcnQgc3VicHJvY2VzcwoKCiMg4pSA4pSAIFBSRS1MQVVOQ0ggREVQRU5E"
    "RU5DWSBCT09UU1RSQVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBib290"
    "c3RyYXBfY2hlY2soKSAtPiBOb25lOgogICAgIiIiCiAgICBSdW5zIEJFRk9SRSBRQXBwbGljYXRpb24gaXMgY3JlYXRlZC4KICAg"
    "IENoZWNrcyBmb3IgUHlTaWRlNiBzZXBhcmF0ZWx5IChjYW4ndCBzaG93IEdVSSB3aXRob3V0IGl0KS4KICAgIEF1dG8taW5zdGFs"
    "bHMgYWxsIG90aGVyIG1pc3Npbmcgbm9uLWNyaXRpY2FsIGRlcHMgdmlhIHBpcC4KICAgIFZhbGlkYXRlcyBpbnN0YWxscyBzdWNj"
    "ZWVkZWQuCiAgICBXcml0ZXMgcmVzdWx0cyB0byBhIGJvb3RzdHJhcCBsb2cgZm9yIERpYWdub3N0aWNzIHRhYiB0byBwaWNrIHVw"
    "LgogICAgIiIiCiAgICAjIOKUgOKUgCBTdGVwIDE6IENoZWNrIFB5U2lkZTYgKGNhbid0IGF1dG8taW5zdGFsbCB3aXRob3V0IGl0"
    "IGFscmVhZHkgcHJlc2VudCkg4pSACiAgICB0cnk6CiAgICAgICAgaW1wb3J0IFB5U2lkZTYgICMgbm9xYQogICAgZXhjZXB0IElt"
    "cG9ydEVycm9yOgogICAgICAgICMgTm8gR1VJIGF2YWlsYWJsZSDigJQgdXNlIFdpbmRvd3MgbmF0aXZlIGRpYWxvZyB2aWEgY3R5"
    "cGVzCiAgICAgICAgdHJ5OgogICAgICAgICAgICBpbXBvcnQgY3R5cGVzCiAgICAgICAgICAgIGN0eXBlcy53aW5kbGwudXNlcjMy"
    "Lk1lc3NhZ2VCb3hXKAogICAgICAgICAgICAgICAgMCwKICAgICAgICAgICAgICAgICJQeVNpZGU2IGlzIHJlcXVpcmVkIGJ1dCBu"
    "b3QgaW5zdGFsbGVkLlxuXG4iCiAgICAgICAgICAgICAgICAiT3BlbiBhIHRlcm1pbmFsIGFuZCBydW46XG5cbiIKICAgICAgICAg"
    "ICAgICAgICIgICAgcGlwIGluc3RhbGwgUHlTaWRlNlxuXG4iCiAgICAgICAgICAgICAgICBmIlRoZW4gcmVzdGFydCB7REVDS19O"
    "QU1FfS4iLAogICAgICAgICAgICAgICAgZiJ7REVDS19OQU1FfSDigJQgTWlzc2luZyBEZXBlbmRlbmN5IiwKICAgICAgICAgICAg"
    "ICAgIDB4MTAgICMgTUJfSUNPTkVSUk9SCiAgICAgICAgICAgICkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAg"
    "ICBwcmludCgiQ1JJVElDQUw6IFB5U2lkZTYgbm90IGluc3RhbGxlZC4gUnVuOiBwaXAgaW5zdGFsbCBQeVNpZGU2IikKICAgICAg"
    "ICBzeXMuZXhpdCgxKQoKICAgICMg4pSA4pSAIFN0ZXAgMjogQXV0by1pbnN0YWxsIG90aGVyIG1pc3NpbmcgZGVwcyDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgIF9BVVRPX0lOU1RBTEwgPSBbCiAgICAgICAgKCJhcHNjaGVkdWxlciIsICAgICAgICAgICAgICAg"
    "ImFwc2NoZWR1bGVyIiksCiAgICAgICAgKCJsb2d1cnUiLCAgICAgICAgICAgICAgICAgICAgImxvZ3VydSIpLAogICAgICAgICgi"
    "cHlnYW1lIiwgICAgICAgICAgICAgICAgICAgICJweWdhbWUiKSwKICAgICAgICAoInB5d2luMzIiLCAgICAgICAgICAgICAgICAg"
    "ICAicHl3aW4zMiIpLAogICAgICAgICgicHN1dGlsIiwgICAgICAgICAgICAgICAgICAgICJwc3V0aWwiKSwKICAgICAgICAoInJl"
    "cXVlc3RzIiwgICAgICAgICAgICAgICAgICAicmVxdWVzdHMiKSwKICAgICAgICAoImdvb2dsZS1hcGktcHl0aG9uLWNsaWVudCIs"
    "ICAiZ29vZ2xlYXBpY2xpZW50IiksCiAgICAgICAgKCJnb29nbGUtYXV0aC1vYXV0aGxpYiIsICAgICAgImdvb2dsZV9hdXRoX29h"
    "dXRobGliIiksCiAgICAgICAgKCJnb29nbGUtYXV0aCIsICAgICAgICAgICAgICAgImdvb2dsZS5hdXRoIiksCiAgICBdCgogICAg"
    "aW1wb3J0IGltcG9ydGxpYgogICAgYm9vdHN0cmFwX2xvZyA9IFtdCgogICAgZm9yIHBpcF9uYW1lLCBpbXBvcnRfbmFtZSBpbiBf"
    "QVVUT19JTlNUQUxMOgogICAgICAgIHRyeToKICAgICAgICAgICAgaW1wb3J0bGliLmltcG9ydF9tb2R1bGUoaW1wb3J0X25hbWUp"
    "CiAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSDinJMiKQogICAgICAgIGV4"
    "Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgYm9vdHN0cmFwX2xvZy5hcHBlbmQoCiAgICAgICAgICAgICAgICBmIltCT09U"
    "U1RSQVBdIHtwaXBfbmFtZX0gbWlzc2luZyDigJQgaW5zdGFsbGluZy4uLiIKICAgICAgICAgICAgKQogICAgICAgICAgICB0cnk6"
    "CiAgICAgICAgICAgICAgICByZXN1bHQgPSBzdWJwcm9jZXNzLnJ1bigKICAgICAgICAgICAgICAgICAgICBbc3lzLmV4ZWN1dGFi"
    "bGUsICItbSIsICJwaXAiLCAiaW5zdGFsbCIsCiAgICAgICAgICAgICAgICAgICAgIHBpcF9uYW1lLCAiLS1xdWlldCIsICItLW5v"
    "LXdhcm4tc2NyaXB0LWxvY2F0aW9uIl0sCiAgICAgICAgICAgICAgICAgICAgY2FwdHVyZV9vdXRwdXQ9VHJ1ZSwgdGV4dD1UcnVl"
    "LCB0aW1lb3V0PTEyMAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgcmVzdWx0LnJldHVybmNvZGUgPT0gMDoK"
    "ICAgICAgICAgICAgICAgICAgICAjIFZhbGlkYXRlIGl0IGFjdHVhbGx5IGltcG9ydGVkIG5vdwogICAgICAgICAgICAgICAgICAg"
    "IHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgaW1wb3J0bGliLmltcG9ydF9tb2R1bGUoaW1wb3J0X25hbWUpCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNU"
    "UkFQXSB7cGlwX25hbWV9IGluc3RhbGxlZCDinJMiCiAgICAgICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAg"
    "ICBleGNlcHQgSW1wb3J0RXJyb3I6CiAgICAgICAgICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IGluc3RhbGwgYXBwZWFyZWQgdG8gIgogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgZiJzdWNjZWVkIGJ1dCBpbXBvcnQgc3RpbGwgZmFpbHMg4oCUIHJlc3RhcnQgbWF5ICIKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIGYiYmUgcmVxdWlyZWQuIgogICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAg"
    "ICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgICAg"
    "ICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbCBmYWlsZWQ6ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJ7"
    "cmVzdWx0LnN0ZGVycls6MjAwXX0iCiAgICAgICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgc3VicHJvY2Vzcy5U"
    "aW1lb3V0RXhwaXJlZDoKICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAgICAgIGYi"
    "W0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsIHRpbWVkIG91dC4iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAgICAgICAg"
    "ICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1lfSBpbnN0YWxsIGVycm9yOiB7ZX0iCiAgICAgICAgICAgICAgICApCgogICAgIyDi"
    "lIDilIAgU3RlcCAzOiBXcml0ZSBib290c3RyYXAgbG9nIGZvciBEaWFnbm9zdGljcyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICB0cnk6CiAgICAgICAgbG9nX3BhdGgg"
    "PSBTQ1JJUFRfRElSIC8gImxvZ3MiIC8gImJvb3RzdHJhcF9sb2cudHh0IgogICAgICAgIHdpdGggbG9nX3BhdGgub3BlbigidyIs"
    "IGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgIGYud3JpdGUoIlxuIi5qb2luKGJvb3RzdHJhcF9sb2cpKQogICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICBwYXNzCgoKIyDilIDilIAgRklSU1QgUlVOIERJQUxPRyDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKY2xhc3MgRmlyc3RSdW5EaWFsb2coUURpYWxvZyk6CiAgICAiIiIKICAgIFNob3duIG9uIGZpcnN0IGxhdW5jaCB3"
    "aGVuIGNvbmZpZy5qc29uIGRvZXNuJ3QgZXhpc3QuCiAgICBDb2xsZWN0cyBtb2RlbCBjb25uZWN0aW9uIHR5cGUgYW5kIHBhdGgv"
    "a2V5LgogICAgVmFsaWRhdGVzIGNvbm5lY3Rpb24gYmVmb3JlIGFjY2VwdGluZy4KICAgIFdyaXRlcyBjb25maWcuanNvbiBvbiBz"
    "dWNjZXNzLgogICAgQ3JlYXRlcyBkZXNrdG9wIHNob3J0Y3V0LgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVu"
    "dD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLnNldFdpbmRvd1RpdGxlKGYi4pym"
    "IHtERUNLX05BTUUudXBwZXIoKX0g4oCUIEZJUlNUIEFXQUtFTklORyIpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KFNUWUxF"
    "KQogICAgICAgIHNlbGYuc2V0Rml4ZWRTaXplKDUyMCwgNDAwKQogICAgICAgIHNlbGYuX3NldHVwX3VpKCkKCiAgICBkZWYgX3Nl"
    "dHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRTcGFj"
    "aW5nKDEwKQoKICAgICAgICB0aXRsZSA9IFFMYWJlbChmIuKcpiB7REVDS19OQU1FLnVwcGVyKCl9IOKAlCBGSVJTVCBBV0FLRU5J"
    "Tkcg4pymIikKICAgICAgICB0aXRsZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19DUklNU09OfTsgZm9u"
    "dC1zaXplOiAxNHB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwg"
    "c2VyaWY7IGxldHRlci1zcGFjaW5nOiAycHg7IgogICAgICAgICkKICAgICAgICB0aXRsZS5zZXRBbGlnbm1lbnQoUXQuQWxpZ25t"
    "ZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICByb290LmFkZFdpZGdldCh0aXRsZSkKCiAgICAgICAgc3ViID0gUUxhYmVsKAog"
    "ICAgICAgICAgICBmIkNvbmZpZ3VyZSB0aGUgdmVzc2VsIGJlZm9yZSB7REVDS19OQU1FfSBtYXkgYXdha2VuLlxuIgogICAgICAg"
    "ICAgICAiQWxsIHNldHRpbmdzIGFyZSBzdG9yZWQgbG9jYWxseS4gTm90aGluZyBsZWF2ZXMgdGhpcyBtYWNoaW5lLiIKICAgICAg"
    "ICApCiAgICAgICAgc3ViLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXpl"
    "OiAxMHB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAg"
    "IHN1Yi5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKICAgICAgICByb290LmFkZFdpZGdldChzdWIp"
    "CgogICAgICAgICMg4pSA4pSAIENvbm5lY3Rpb24gdHlwZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICByb290LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBBSSBDT05ORUNUSU9OIFRZ"
    "UEUiKSkKICAgICAgICBzZWxmLl90eXBlX2NvbWJvID0gUUNvbWJvQm94KCkKICAgICAgICBzZWxmLl90eXBlX2NvbWJvLmFkZEl0"
    "ZW1zKFsKICAgICAgICAgICAgIkxvY2FsIG1vZGVsIGZvbGRlciAodHJhbnNmb3JtZXJzKSIsCiAgICAgICAgICAgICJPbGxhbWEg"
    "KGxvY2FsIHNlcnZpY2UpIiwKICAgICAgICAgICAgIkNsYXVkZSBBUEkgKEFudGhyb3BpYykiLAogICAgICAgICAgICAiT3BlbkFJ"
    "IEFQSSIsCiAgICAgICAgXSkKICAgICAgICBzZWxmLl90eXBlX2NvbWJvLmN1cnJlbnRJbmRleENoYW5nZWQuY29ubmVjdChzZWxm"
    "Ll9vbl90eXBlX2NoYW5nZSkKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl90eXBlX2NvbWJvKQoKICAgICAgICAjIOKUgOKU"
    "gCBEeW5hbWljIGNvbm5lY3Rpb24gZmllbGRzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3N0YWNr"
    "ID0gUVN0YWNrZWRXaWRnZXQoKQoKICAgICAgICAjIFBhZ2UgMDogTG9jYWwgcGF0aAogICAgICAgIHAwID0gUVdpZGdldCgpCiAg"
    "ICAgICAgbDAgPSBRSEJveExheW91dChwMCkKICAgICAgICBsMC5zZXRDb250ZW50c01hcmdpbnMoMCwwLDAsMCkKICAgICAgICBz"
    "ZWxmLl9sb2NhbF9wYXRoID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9sb2NhbF9wYXRoLnNldFBsYWNlaG9sZGVyVGV4dCgK"
    "ICAgICAgICAgICAgciJEOlxBSVxNb2RlbHNcZG9scGhpbi04YiIKICAgICAgICApCiAgICAgICAgYnRuX2Jyb3dzZSA9IF9nb3Ro"
    "aWNfYnRuKCJCcm93c2UiKQogICAgICAgIGJ0bl9icm93c2UuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Jyb3dzZV9tb2RlbCkKICAg"
    "ICAgICBsMC5hZGRXaWRnZXQoc2VsZi5fbG9jYWxfcGF0aCk7IGwwLmFkZFdpZGdldChidG5fYnJvd3NlKQogICAgICAgIHNlbGYu"
    "X3N0YWNrLmFkZFdpZGdldChwMCkKCiAgICAgICAgIyBQYWdlIDE6IE9sbGFtYSBtb2RlbCBuYW1lCiAgICAgICAgcDEgPSBRV2lk"
    "Z2V0KCkKICAgICAgICBsMSA9IFFIQm94TGF5b3V0KHAxKQogICAgICAgIGwxLnNldENvbnRlbnRzTWFyZ2lucygwLDAsMCwwKQog"
    "ICAgICAgIHNlbGYuX29sbGFtYV9tb2RlbCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fb2xsYW1hX21vZGVsLnNldFBsYWNl"
    "aG9sZGVyVGV4dCgiZG9scGhpbi0yLjYtN2IiKQogICAgICAgIGwxLmFkZFdpZGdldChzZWxmLl9vbGxhbWFfbW9kZWwpCiAgICAg"
    "ICAgc2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAxKQoKICAgICAgICAjIFBhZ2UgMjogQ2xhdWRlIEFQSSBrZXkKICAgICAgICBwMiA9"
    "IFFXaWRnZXQoKQogICAgICAgIGwyID0gUVZCb3hMYXlvdXQocDIpCiAgICAgICAgbDIuc2V0Q29udGVudHNNYXJnaW5zKDAsMCww"
    "LDApCiAgICAgICAgc2VsZi5fY2xhdWRlX2tleSAgID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9jbGF1ZGVfa2V5LnNldFBs"
    "YWNlaG9sZGVyVGV4dCgic2stYW50LS4uLiIpCiAgICAgICAgc2VsZi5fY2xhdWRlX2tleS5zZXRFY2hvTW9kZShRTGluZUVkaXQu"
    "RWNob01vZGUuUGFzc3dvcmQpCiAgICAgICAgc2VsZi5fY2xhdWRlX21vZGVsID0gUUxpbmVFZGl0KCJjbGF1ZGUtc29ubmV0LTQt"
    "NiIpCiAgICAgICAgbDIuYWRkV2lkZ2V0KFFMYWJlbCgiQVBJIEtleToiKSkKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fY2xh"
    "dWRlX2tleSkKICAgICAgICBsMi5hZGRXaWRnZXQoUUxhYmVsKCJNb2RlbDoiKSkKICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5f"
    "Y2xhdWRlX21vZGVsKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMikKCiAgICAgICAgIyBQYWdlIDM6IE9wZW5BSQog"
    "ICAgICAgIHAzID0gUVdpZGdldCgpCiAgICAgICAgbDMgPSBRVkJveExheW91dChwMykKICAgICAgICBsMy5zZXRDb250ZW50c01h"
    "cmdpbnMoMCwwLDAsMCkKICAgICAgICBzZWxmLl9vYWlfa2V5ICAgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX29haV9rZXku"
    "c2V0UGxhY2Vob2xkZXJUZXh0KCJzay0uLi4iKQogICAgICAgIHNlbGYuX29haV9rZXkuc2V0RWNob01vZGUoUUxpbmVFZGl0LkVj"
    "aG9Nb2RlLlBhc3N3b3JkKQogICAgICAgIHNlbGYuX29haV9tb2RlbCA9IFFMaW5lRWRpdCgiZ3B0LTRvIikKICAgICAgICBsMy5h"
    "ZGRXaWRnZXQoUUxhYmVsKCJBUEkgS2V5OiIpKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9vYWlfa2V5KQogICAgICAgIGwz"
    "LmFkZFdpZGdldChRTGFiZWwoIk1vZGVsOiIpKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9vYWlfbW9kZWwpCiAgICAgICAg"
    "c2VsZi5fc3RhY2suYWRkV2lkZ2V0KHAzKQoKICAgICAgICByb290LmFkZFdpZGdldChzZWxmLl9zdGFjaykKCiAgICAgICAgIyDi"
    "lIDilIAgVGVzdCArIHN0YXR1cyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICB0ZXN0X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fdGVzdCA9IF9nb3RoaWNf"
    "YnRuKCJUZXN0IENvbm5lY3Rpb24iKQogICAgICAgIHNlbGYuX2J0bl90ZXN0LmNsaWNrZWQuY29ubmVjdChzZWxmLl90ZXN0X2Nv"
    "bm5lY3Rpb24pCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAg"
    "ICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHRlc3Rfcm93LmFkZFdpZGdl"
    "dChzZWxmLl9idG5fdGVzdCkKICAgICAgICB0ZXN0X3Jvdy5hZGRXaWRnZXQoc2VsZi5fc3RhdHVzX2xibCwgMSkKICAgICAgICBy"
    "b290LmFkZExheW91dCh0ZXN0X3JvdykKCiAgICAgICAgIyDilIDilIAgRmFjZSBQYWNrIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHJvb3QuYWRkV2lkZ2V0"
    "KF9zZWN0aW9uX2xibCgi4p2nIEZBQ0UgUEFDSyAob3B0aW9uYWwg4oCUIFpJUCBmaWxlKSIpKQogICAgICAgIGZhY2Vfcm93ID0g"
    "UUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2ZhY2VfcGF0aCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fZmFjZV9wYXRo"
    "LnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAgICAgZiJCcm93c2UgdG8ge0RFQ0tfTkFNRX0gZmFjZSBwYWNrIFpJUCAob3B0"
    "aW9uYWwsIGNhbiBhZGQgbGF0ZXIpIgogICAgICAgICkKICAgICAgICBzZWxmLl9mYWNlX3BhdGguc2V0U3R5bGVTaGVldCgKICAg"
    "ICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVy"
    "OiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtE"
    "RUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMnB4OyBwYWRkaW5nOiA2cHggMTBweDsiCiAgICAgICAgKQogICAgICAgIGJ0"
    "bl9mYWNlID0gX2dvdGhpY19idG4oIkJyb3dzZSIpCiAgICAgICAgYnRuX2ZhY2UuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Jyb3dz"
    "ZV9mYWNlKQogICAgICAgIGZhY2Vfcm93LmFkZFdpZGdldChzZWxmLl9mYWNlX3BhdGgpCiAgICAgICAgZmFjZV9yb3cuYWRkV2lk"
    "Z2V0KGJ0bl9mYWNlKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGZhY2Vfcm93KQoKICAgICAgICAjIOKUgOKUgCBTaG9ydGN1dCBv"
    "cHRpb24g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2Vs"
    "Zi5fc2hvcnRjdXRfY2IgPSBRQ2hlY2tCb3goCiAgICAgICAgICAgICJDcmVhdGUgZGVza3RvcCBzaG9ydGN1dCAocmVjb21tZW5k"
    "ZWQpIgogICAgICAgICkKICAgICAgICBzZWxmLl9zaG9ydGN1dF9jYi5zZXRDaGVja2VkKFRydWUpCiAgICAgICAgcm9vdC5hZGRX"
    "aWRnZXQoc2VsZi5fc2hvcnRjdXRfY2IpCgogICAgICAgICMg4pSA4pSAIEJ1dHRvbnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRT"
    "dHJldGNoKCkKICAgICAgICBidG5fcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4gPSBfZ290aGlj"
    "X2J0bigi4pymIEJFR0lOIEFXQUtFTklORyIpCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbi5zZXRFbmFibGVkKEZhbHNlKQogICAg"
    "ICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigi4pyXIENhbmNlbCIpCiAgICAgICAgc2VsZi5fYnRuX2F3YWtlbi5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5hY2NlcHQpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5yZWplY3QpCiAgICAg"
    "ICAgYnRuX3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX2F3YWtlbikKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2FuY2Vs"
    "KQogICAgICAgIHJvb3QuYWRkTGF5b3V0KGJ0bl9yb3cpCgogICAgZGVmIF9vbl90eXBlX2NoYW5nZShzZWxmLCBpZHg6IGludCkg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoaWR4KQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4u"
    "c2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9zdGF0dXNfbGJsLnNldFRleHQoIiIpCgogICAgZGVmIF9icm93c2VfbW9k"
    "ZWwoc2VsZikgLT4gTm9uZToKICAgICAgICBwYXRoID0gUUZpbGVEaWFsb2cuZ2V0RXhpc3RpbmdEaXJlY3RvcnkoCiAgICAgICAg"
    "ICAgIHNlbGYsICJTZWxlY3QgTW9kZWwgRm9sZGVyIiwKICAgICAgICAgICAgciJEOlxBSVxNb2RlbHMiCiAgICAgICAgKQogICAg"
    "ICAgIGlmIHBhdGg6CiAgICAgICAgICAgIHNlbGYuX2xvY2FsX3BhdGguc2V0VGV4dChwYXRoKQoKICAgIGRlZiBfYnJvd3NlX2Zh"
    "Y2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBwYXRoLCBfID0gUUZpbGVEaWFsb2cuZ2V0T3BlbkZpbGVOYW1lKAogICAgICAgICAg"
    "ICBzZWxmLCAiU2VsZWN0IEZhY2UgUGFjayBaSVAiLAogICAgICAgICAgICBzdHIoUGF0aC5ob21lKCkgLyAiRGVza3RvcCIpLAog"
    "ICAgICAgICAgICAiWklQIEZpbGVzICgqLnppcCkiCiAgICAgICAgKQogICAgICAgIGlmIHBhdGg6CiAgICAgICAgICAgIHNlbGYu"
    "X2ZhY2VfcGF0aC5zZXRUZXh0KHBhdGgpCgogICAgQHByb3BlcnR5CiAgICBkZWYgZmFjZV96aXBfcGF0aChzZWxmKSAtPiBzdHI6"
    "CiAgICAgICAgcmV0dXJuIHNlbGYuX2ZhY2VfcGF0aC50ZXh0KCkuc3RyaXAoKQoKICAgIGRlZiBfdGVzdF9jb25uZWN0aW9uKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRUZXh0KCJUZXN0aW5nLi4uIikKICAgICAgICBzZWxmLl9z"
    "dGF0dXNfbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiAxMHB4"
    "OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgUUFwcGxpY2F0aW9uLnByb2Nlc3NF"
    "dmVudHMoKQoKICAgICAgICBpZHggPSBzZWxmLl90eXBlX2NvbWJvLmN1cnJlbnRJbmRleCgpCiAgICAgICAgb2sgID0gRmFsc2UK"
    "ICAgICAgICBtc2cgPSAiIgoKICAgICAgICBpZiBpZHggPT0gMDogICMgTG9jYWwKICAgICAgICAgICAgcGF0aCA9IHNlbGYuX2xv"
    "Y2FsX3BhdGgudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgaWYgcGF0aCBhbmQgUGF0aChwYXRoKS5leGlzdHMoKToKICAgICAg"
    "ICAgICAgICAgIG9rICA9IFRydWUKICAgICAgICAgICAgICAgIG1zZyA9IGYiRm9sZGVyIGZvdW5kLiBNb2RlbCB3aWxsIGxvYWQg"
    "b24gc3RhcnR1cC4iCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBtc2cgPSAiRm9sZGVyIG5vdCBmb3VuZC4gQ2hl"
    "Y2sgdGhlIHBhdGguIgoKICAgICAgICBlbGlmIGlkeCA9PSAxOiAgIyBPbGxhbWEKICAgICAgICAgICAgdHJ5OgogICAgICAgICAg"
    "ICAgICAgcmVxICA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QoCiAgICAgICAgICAgICAgICAgICAgImh0dHA6Ly9sb2NhbGhvc3Q6"
    "MTE0MzQvYXBpL3RhZ3MiCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICByZXNwID0gdXJsbGliLnJlcXVlc3QudXJs"
    "b3BlbihyZXEsIHRpbWVvdXQ9MykKICAgICAgICAgICAgICAgIG9rICAgPSByZXNwLnN0YXR1cyA9PSAyMDAKICAgICAgICAgICAg"
    "ICAgIG1zZyAgPSAiT2xsYW1hIGlzIHJ1bm5pbmcg4pyTIiBpZiBvayBlbHNlICJPbGxhbWEgbm90IHJlc3BvbmRpbmcuIgogICAg"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBtc2cgPSBmIk9sbGFtYSBub3QgcmVhY2hhYmxl"
    "OiB7ZX0iCgogICAgICAgIGVsaWYgaWR4ID09IDI6ICAjIENsYXVkZQogICAgICAgICAgICBrZXkgPSBzZWxmLl9jbGF1ZGVfa2V5"
    "LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIG9rICA9IGJvb2woa2V5IGFuZCBrZXkuc3RhcnRzd2l0aCgic2stYW50IikpCiAg"
    "ICAgICAgICAgIG1zZyA9ICJBUEkga2V5IGZvcm1hdCBsb29rcyBjb3JyZWN0LiIgaWYgb2sgZWxzZSAiRW50ZXIgYSB2YWxpZCBD"
    "bGF1ZGUgQVBJIGtleS4iCgogICAgICAgIGVsaWYgaWR4ID09IDM6ICAjIE9wZW5BSQogICAgICAgICAgICBrZXkgPSBzZWxmLl9v"
    "YWlfa2V5LnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIG9rICA9IGJvb2woa2V5IGFuZCBrZXkuc3RhcnRzd2l0aCgic2stIikp"
    "CiAgICAgICAgICAgIG1zZyA9ICJBUEkga2V5IGZvcm1hdCBsb29rcyBjb3JyZWN0LiIgaWYgb2sgZWxzZSAiRW50ZXIgYSB2YWxp"
    "ZCBPcGVuQUkgQVBJIGtleS4iCgogICAgICAgIGNvbG9yID0gQ19HUkVFTiBpZiBvayBlbHNlIENfQ1JJTVNPTgogICAgICAgIHNl"
    "bGYuX3N0YXR1c19sYmwuc2V0VGV4dChtc2cpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICBmImNvbG9yOiB7Y29sb3J9OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7Igog"
    "ICAgICAgICkKICAgICAgICBzZWxmLl9idG5fYXdha2VuLnNldEVuYWJsZWQob2spCgogICAgZGVmIGJ1aWxkX2NvbmZpZyhzZWxm"
    "KSAtPiBkaWN0OgogICAgICAgICIiIkJ1aWxkIGFuZCByZXR1cm4gdXBkYXRlZCBjb25maWcgZGljdCBmcm9tIGRpYWxvZyBzZWxl"
    "Y3Rpb25zLiIiIgogICAgICAgIGNmZyAgICAgPSBfZGVmYXVsdF9jb25maWcoKQogICAgICAgIGlkeCAgICAgPSBzZWxmLl90eXBl"
    "X2NvbWJvLmN1cnJlbnRJbmRleCgpCiAgICAgICAgdHlwZXMgICA9IFsibG9jYWwiLCAib2xsYW1hIiwgImNsYXVkZSIsICJvcGVu"
    "YWkiXQogICAgICAgIGNmZ1sibW9kZWwiXVsidHlwZSJdID0gdHlwZXNbaWR4XQoKICAgICAgICBpZiBpZHggPT0gMDoKICAgICAg"
    "ICAgICAgY2ZnWyJtb2RlbCJdWyJwYXRoIl0gPSBzZWxmLl9sb2NhbF9wYXRoLnRleHQoKS5zdHJpcCgpCiAgICAgICAgZWxpZiBp"
    "ZHggPT0gMToKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJvbGxhbWFfbW9kZWwiXSA9IHNlbGYuX29sbGFtYV9tb2RlbC50ZXh0"
    "KCkuc3RyaXAoKSBvciAiZG9scGhpbi0yLjYtN2IiCiAgICAgICAgZWxpZiBpZHggPT0gMjoKICAgICAgICAgICAgY2ZnWyJtb2Rl"
    "bCJdWyJhcGlfa2V5Il0gICA9IHNlbGYuX2NsYXVkZV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJd"
    "WyJhcGlfbW9kZWwiXSA9IHNlbGYuX2NsYXVkZV9tb2RlbC50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdbIm1vZGVsIl1b"
    "ImFwaV90eXBlIl0gID0gImNsYXVkZSIKICAgICAgICBlbGlmIGlkeCA9PSAzOgogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFw"
    "aV9rZXkiXSAgID0gc2VsZi5fb2FpX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV9tb2Rl"
    "bCJdID0gc2VsZi5fb2FpX21vZGVsLnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX3R5cGUiXSAg"
    "PSAib3BlbmFpIgoKICAgICAgICBjZmdbImZpcnN0X3J1biJdID0gRmFsc2UKICAgICAgICByZXR1cm4gY2ZnCgogICAgQHByb3Bl"
    "cnR5CiAgICBkZWYgY3JlYXRlX3Nob3J0Y3V0KHNlbGYpIC0+IGJvb2w6CiAgICAgICAgcmV0dXJuIHNlbGYuX3Nob3J0Y3V0X2Ni"
    "LmlzQ2hlY2tlZCgpCgoKIyDilIDilIAgSk9VUk5BTCBTSURFQkFSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBK"
    "b3VybmFsU2lkZWJhcihRV2lkZ2V0KToKICAgICIiIgogICAgQ29sbGFwc2libGUgbGVmdCBzaWRlYmFyIG5leHQgdG8gdGhlIHBl"
    "cnNvbmEgY2hhdCB0YWIuCiAgICBUb3A6IHNlc3Npb24gY29udHJvbHMgKGN1cnJlbnQgc2Vzc2lvbiBuYW1lLCBzYXZlL2xvYWQg"
    "YnV0dG9ucywKICAgICAgICAgYXV0b3NhdmUgaW5kaWNhdG9yKS4KICAgIEJvZHk6IHNjcm9sbGFibGUgc2Vzc2lvbiBsaXN0IOKA"
    "lCBkYXRlLCBBSSBuYW1lLCBtZXNzYWdlIGNvdW50LgogICAgQ29sbGFwc2VzIGxlZnR3YXJkIHRvIGEgdGhpbiBzdHJpcC4KCiAg"
    "ICBTaWduYWxzOgogICAgICAgIHNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQoc3RyKSAgIOKAlCBkYXRlIHN0cmluZyBvZiBzZXNzaW9u"
    "IHRvIGxvYWQKICAgICAgICBzZXNzaW9uX2NsZWFyX3JlcXVlc3RlZCgpICAgICDigJQgcmV0dXJuIHRvIGN1cnJlbnQgc2Vzc2lv"
    "bgogICAgIiIiCgogICAgc2Vzc2lvbl9sb2FkX3JlcXVlc3RlZCAgPSBTaWduYWwoc3RyKQogICAgc2Vzc2lvbl9jbGVhcl9yZXF1"
    "ZXN0ZWQgPSBTaWduYWwoKQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBzZXNzaW9uX21ncjogIlNlc3Npb25NYW5hZ2VyIiwgcGFy"
    "ZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuX3Nlc3Npb25fbWdyID0gc2Vz"
    "c2lvbl9tZ3IKICAgICAgICBzZWxmLl9leHBhbmRlZCAgICA9IFRydWUKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAg"
    "c2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBVc2UgYSBob3Jpem9udGFs"
    "IHJvb3QgbGF5b3V0IOKAlCBjb250ZW50IG9uIGxlZnQsIHRvZ2dsZSBzdHJpcCBvbiByaWdodAogICAgICAgIHJvb3QgPSBRSEJv"
    "eExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgcm9vdC5zZXRT"
    "cGFjaW5nKDApCgogICAgICAgICMg4pSA4pSAIENvbGxhcHNlIHRvZ2dsZSBzdHJpcCDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl90b2dnbGVfc3RyaXAgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl90b2dnbGVf"
    "c3RyaXAuc2V0Rml4ZWRXaWR0aCgyMCkKICAgICAgICBzZWxmLl90b2dnbGVfc3RyaXAuc2V0U3R5bGVTaGVldCgKICAgICAgICAg"
    "ICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXItcmlnaHQ6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IgogICAgICAg"
    "ICkKICAgICAgICB0c19sYXlvdXQgPSBRVkJveExheW91dChzZWxmLl90b2dnbGVfc3RyaXApCiAgICAgICAgdHNfbGF5b3V0LnNl"
    "dENvbnRlbnRzTWFyZ2lucygwLCA4LCAwLCA4KQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4gPSBRVG9vbEJ1dHRvbigpCiAgICAg"
    "ICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRGaXhlZFNpemUoMTgsIDE4KQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0VGV4dCgi"
    "4peAIikKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogdHJh"
    "bnNwYXJlbnQ7IGNvbG9yOiB7Q19HT0xEX0RJTX07ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7IGZvbnQtc2l6ZTogMTBw"
    "eDsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZSkKICAgICAg"
    "ICB0c19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3RvZ2dsZV9idG4pCiAgICAgICAgdHNfbGF5b3V0LmFkZFN0cmV0Y2goKQoKICAg"
    "ICAgICAjIOKUgOKUgCBNYWluIGNvbnRlbnQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fY29udGVudCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2NvbnRlbnQu"
    "c2V0TWluaW11bVdpZHRoKDE4MCkKICAgICAgICBzZWxmLl9jb250ZW50LnNldE1heGltdW1XaWR0aCgyMjApCiAgICAgICAgY29u"
    "dGVudF9sYXlvdXQgPSBRVkJveExheW91dChzZWxmLl9jb250ZW50KQogICAgICAgIGNvbnRlbnRfbGF5b3V0LnNldENvbnRlbnRz"
    "TWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIGNvbnRlbnRfbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBTZWN0aW9u"
    "IGxhYmVsCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIEpPVVJOQUwiKSkKCiAgICAg"
    "ICAgIyBDdXJyZW50IHNlc3Npb24gaW5mbwogICAgICAgIHNlbGYuX3Nlc3Npb25fbmFtZSA9IFFMYWJlbCgiTmV3IFNlc3Npb24i"
    "KQogICAgICAgIHNlbGYuX3Nlc3Npb25fbmFtZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsg"
    "Zm9udC1zaXplOiAxMHB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyAiCiAgICAgICAgICAgIGYiZm9udC1zdHls"
    "ZTogaXRhbGljOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9uYW1lLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAg"
    "Y29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Nlc3Npb25fbmFtZSkKCiAgICAgICAgIyBTYXZlIC8gTG9hZCByb3cKICAg"
    "ICAgICBjdHJsX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9idG5fc2F2ZSA9IF9nb3RoaWNfYnRuKCLwn5K+IikK"
    "ICAgICAgICBzZWxmLl9idG5fc2F2ZS5zZXRGaXhlZFNpemUoMzIsIDI0KQogICAgICAgIHNlbGYuX2J0bl9zYXZlLnNldFRvb2xU"
    "aXAoIlNhdmUgc2Vzc2lvbiBub3ciKQogICAgICAgIHNlbGYuX2J0bl9sb2FkID0gX2dvdGhpY19idG4oIvCfk4IiKQogICAgICAg"
    "IHNlbGYuX2J0bl9sb2FkLnNldEZpeGVkU2l6ZSgzMiwgMjQpCiAgICAgICAgc2VsZi5fYnRuX2xvYWQuc2V0VG9vbFRpcCgiQnJv"
    "d3NlIGFuZCBsb2FkIGEgcGFzdCBzZXNzaW9uIikKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3QgPSBRTGFiZWwoIuKXjyIpCiAg"
    "ICAgICAgc2VsZi5fYXV0b3NhdmVfZG90LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsg"
    "Zm9udC1zaXplOiA4cHg7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRUb29s"
    "VGlwKCJBdXRvc2F2ZSBzdGF0dXMiKQogICAgICAgIHNlbGYuX2J0bl9zYXZlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19zYXZl"
    "KQogICAgICAgIHNlbGYuX2J0bl9sb2FkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19sb2FkKQogICAgICAgIGN0cmxfcm93LmFk"
    "ZFdpZGdldChzZWxmLl9idG5fc2F2ZSkKICAgICAgICBjdHJsX3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX2xvYWQpCiAgICAgICAg"
    "Y3RybF9yb3cuYWRkV2lkZ2V0KHNlbGYuX2F1dG9zYXZlX2RvdCkKICAgICAgICBjdHJsX3Jvdy5hZGRTdHJldGNoKCkKICAgICAg"
    "ICBjb250ZW50X2xheW91dC5hZGRMYXlvdXQoY3RybF9yb3cpCgogICAgICAgICMgSm91cm5hbCBsb2FkZWQgaW5kaWNhdG9yCiAg"
    "ICAgICAgc2VsZi5fam91cm5hbF9sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfUFVSUExFfTsgZm9udC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05U"
    "fSwgc2VyaWY7ICIKICAgICAgICAgICAgZiJmb250LXN0eWxlOiBpdGFsaWM7IgogICAgICAgICkKICAgICAgICBzZWxmLl9qb3Vy"
    "bmFsX2xibC5zZXRXb3JkV3JhcChUcnVlKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9qb3VybmFsX2xi"
    "bCkKCiAgICAgICAgIyBDbGVhciBqb3VybmFsIGJ1dHRvbiAoaGlkZGVuIHdoZW4gbm90IGxvYWRlZCkKICAgICAgICBzZWxmLl9i"
    "dG5fY2xlYXJfam91cm5hbCA9IF9nb3RoaWNfYnRuKCLinJcgUmV0dXJuIHRvIFByZXNlbnQiKQogICAgICAgIHNlbGYuX2J0bl9j"
    "bGVhcl9qb3VybmFsLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwuY2xpY2tlZC5jb25u"
    "ZWN0KHNlbGYuX2RvX2NsZWFyX2pvdXJuYWwpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2J0bl9jbGVh"
    "cl9qb3VybmFsKQoKICAgICAgICAjIERpdmlkZXIKICAgICAgICBkaXYgPSBRRnJhbWUoKQogICAgICAgIGRpdi5zZXRGcmFtZVNo"
    "YXBlKFFGcmFtZS5TaGFwZS5ITGluZSkKICAgICAgICBkaXYuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19DUklNU09OX0RJTX07"
    "IikKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoZGl2KQoKICAgICAgICAjIFNlc3Npb24gbGlzdAogICAgICAgIGNv"
    "bnRlbnRfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlvbl9sYmwoIuKdpyBQQVNUIFNFU1NJT05TIikpCiAgICAgICAgc2VsZi5fc2Vz"
    "c2lvbl9saXN0ID0gUUxpc3RXaWRnZXQoKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5zZXRTdHlsZVNoZWV0KAogICAgICAg"
    "ICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNv"
    "bGlkIHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6"
    "IDEwcHg7IgogICAgICAgICAgICBmIlFMaXN0V2lkZ2V0OjppdGVtOnNlbGVjdGVkIHt7IGJhY2tncm91bmQ6IHtDX0NSSU1TT05f"
    "RElNfTsgfX0iCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5pdGVtRG91YmxlQ2xpY2tlZC5jb25uZWN0KHNl"
    "bGYuX29uX3Nlc3Npb25fY2xpY2spCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0Lml0ZW1DbGlja2VkLmNvbm5lY3Qoc2VsZi5f"
    "b25fc2Vzc2lvbl9jbGljaykKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoc2VsZi5fc2Vzc2lvbl9saXN0LCAxKQoK"
    "ICAgICAgICAjIEFkZCBjb250ZW50IGFuZCB0b2dnbGUgc3RyaXAgdG8gdGhlIHJvb3QgaG9yaXpvbnRhbCBsYXlvdXQKICAgICAg"
    "ICByb290LmFkZFdpZGdldChzZWxmLl9jb250ZW50KQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3RvZ2dsZV9zdHJpcCkK"
    "CiAgICBkZWYgX3RvZ2dsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVk"
    "CiAgICAgICAgc2VsZi5fY29udGVudC5zZXRWaXNpYmxlKHNlbGYuX2V4cGFuZGVkKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4u"
    "c2V0VGV4dCgi4peAIiBpZiBzZWxmLl9leHBhbmRlZCBlbHNlICLilrYiKQogICAgICAgIHNlbGYudXBkYXRlR2VvbWV0cnkoKQog"
    "ICAgICAgIHAgPSBzZWxmLnBhcmVudFdpZGdldCgpCiAgICAgICAgaWYgcCBhbmQgcC5sYXlvdXQoKToKICAgICAgICAgICAgcC5s"
    "YXlvdXQoKS5hY3RpdmF0ZSgpCgogICAgZGVmIHJlZnJlc2goc2VsZikgLT4gTm9uZToKICAgICAgICBzZXNzaW9ucyA9IHNlbGYu"
    "X3Nlc3Npb25fbWdyLmxpc3Rfc2Vzc2lvbnMoKQogICAgICAgIHNlbGYuX3Nlc3Npb25fbGlzdC5jbGVhcigpCiAgICAgICAgZm9y"
    "IHMgaW4gc2Vzc2lvbnM6CiAgICAgICAgICAgIGRhdGVfc3RyID0gcy5nZXQoImRhdGUiLCIiKQogICAgICAgICAgICBuYW1lICAg"
    "ICA9IHMuZ2V0KCJuYW1lIiwgZGF0ZV9zdHIpWzozMF0KICAgICAgICAgICAgY291bnQgICAgPSBzLmdldCgibWVzc2FnZV9jb3Vu"
    "dCIsIDApCiAgICAgICAgICAgIGl0ZW0gPSBRTGlzdFdpZGdldEl0ZW0oZiJ7ZGF0ZV9zdHJ9XG57bmFtZX0gKHtjb3VudH0gbXNn"
    "cykiKQogICAgICAgICAgICBpdGVtLnNldERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCBkYXRlX3N0cikKICAgICAgICAg"
    "ICAgaXRlbS5zZXRUb29sVGlwKGYiRG91YmxlLWNsaWNrIHRvIGxvYWQgc2Vzc2lvbiBmcm9tIHtkYXRlX3N0cn0iKQogICAgICAg"
    "ICAgICBzZWxmLl9zZXNzaW9uX2xpc3QuYWRkSXRlbShpdGVtKQoKICAgIGRlZiBzZXRfc2Vzc2lvbl9uYW1lKHNlbGYsIG5hbWU6"
    "IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9zZXNzaW9uX25hbWUuc2V0VGV4dChuYW1lWzo1MF0gb3IgIk5ldyBTZXNzaW9u"
    "IikKCiAgICBkZWYgc2V0X2F1dG9zYXZlX2luZGljYXRvcihzZWxmLCBzYXZlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll9hdXRvc2F2ZV9kb3Quc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR1JFRU4gaWYgc2F2ZWQgZWxzZSBD"
    "X1RFWFRfRElNfTsgIgogICAgICAgICAgICBmImZvbnQtc2l6ZTogOHB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl9hdXRvc2F2ZV9kb3Quc2V0VG9vbFRpcCgKICAgICAgICAgICAgIkF1dG9zYXZlZCIgaWYgc2F2ZWQgZWxzZSAiUGVu"
    "ZGluZyBhdXRvc2F2ZSIKICAgICAgICApCgogICAgZGVmIHNldF9qb3VybmFsX2xvYWRlZChzZWxmLCBkYXRlX3N0cjogc3RyKSAt"
    "PiBOb25lOgogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsLnNldFRleHQoZiLwn5OWIEpvdXJuYWw6IHtkYXRlX3N0cn0iKQogICAg"
    "ICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsLnNldFZpc2libGUoVHJ1ZSkKCiAgICBkZWYgY2xlYXJfam91cm5hbF9pbmRpY2F0"
    "b3Ioc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRUZXh0KCIiKQogICAgICAgIHNlbGYuX2J0bl9j"
    "bGVhcl9qb3VybmFsLnNldFZpc2libGUoRmFsc2UpCgogICAgZGVmIF9kb19zYXZlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2Vs"
    "Zi5fc2Vzc2lvbl9tZ3Iuc2F2ZSgpCiAgICAgICAgc2VsZi5zZXRfYXV0b3NhdmVfaW5kaWNhdG9yKFRydWUpCiAgICAgICAgc2Vs"
    "Zi5yZWZyZXNoKCkKICAgICAgICBzZWxmLl9idG5fc2F2ZS5zZXRUZXh0KCLinJMiKQogICAgICAgIFFUaW1lci5zaW5nbGVTaG90"
    "KDE1MDAsIGxhbWJkYTogc2VsZi5fYnRuX3NhdmUuc2V0VGV4dCgi8J+SviIpKQogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDMw"
    "MDAsIGxhbWJkYTogc2VsZi5zZXRfYXV0b3NhdmVfaW5kaWNhdG9yKEZhbHNlKSkKCiAgICBkZWYgX2RvX2xvYWQoc2VsZikgLT4g"
    "Tm9uZToKICAgICAgICAjIFRyeSBzZWxlY3RlZCBpdGVtIGZpcnN0CiAgICAgICAgaXRlbSA9IHNlbGYuX3Nlc3Npb25fbGlzdC5j"
    "dXJyZW50SXRlbSgpCiAgICAgICAgaWYgbm90IGl0ZW06CiAgICAgICAgICAgICMgSWYgbm90aGluZyBzZWxlY3RlZCwgdHJ5IHRo"
    "ZSBmaXJzdCBpdGVtCiAgICAgICAgICAgIGlmIHNlbGYuX3Nlc3Npb25fbGlzdC5jb3VudCgpID4gMDoKICAgICAgICAgICAgICAg"
    "IGl0ZW0gPSBzZWxmLl9zZXNzaW9uX2xpc3QuaXRlbSgwKQogICAgICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0LnNldEN1"
    "cnJlbnRJdGVtKGl0ZW0pCiAgICAgICAgaWYgaXRlbToKICAgICAgICAgICAgZGF0ZV9zdHIgPSBpdGVtLmRhdGEoUXQuSXRlbURh"
    "dGFSb2xlLlVzZXJSb2xlKQogICAgICAgICAgICBzZWxmLnNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQuZW1pdChkYXRlX3N0cikKCiAg"
    "ICBkZWYgX29uX3Nlc3Npb25fY2xpY2soc2VsZiwgaXRlbSkgLT4gTm9uZToKICAgICAgICBkYXRlX3N0ciA9IGl0ZW0uZGF0YShR"
    "dC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpCiAgICAgICAgc2VsZi5zZXNzaW9uX2xvYWRfcmVxdWVzdGVkLmVtaXQoZGF0ZV9zdHIp"
    "CgogICAgZGVmIF9kb19jbGVhcl9qb3VybmFsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zZXNzaW9uX2NsZWFyX3JlcXVl"
    "c3RlZC5lbWl0KCkKICAgICAgICBzZWxmLmNsZWFyX2pvdXJuYWxfaW5kaWNhdG9yKCkKCgojIOKUgOKUgCBUT1JQT1IgUEFORUwg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFRvcnBvclBhbmVsKFFXaWRnZXQpOgogICAgIiIiCiAg"
    "ICBUaHJlZS1zdGF0ZSBzdXNwZW5zaW9uIHRvZ2dsZTogQVdBS0UgfCBBVVRPIHwgU1VTUEVORAoKICAgIEFXQUtFICDigJQgbW9k"
    "ZWwgbG9hZGVkLCBhdXRvLXRvcnBvciBkaXNhYmxlZCwgaWdub3JlcyBWUkFNIHByZXNzdXJlCiAgICBBVVRPICAg4oCUIG1vZGVs"
    "IGxvYWRlZCwgbW9uaXRvcnMgVlJBTSBwcmVzc3VyZSwgYXV0by10b3Jwb3IgaWYgc3VzdGFpbmVkCiAgICBTVVNQRU5EIOKAlCBt"
    "b2RlbCB1bmxvYWRlZCwgc3RheXMgc3VzcGVuZGVkIHVudGlsIG1hbnVhbGx5IGNoYW5nZWQKCiAgICBTaWduYWxzOgogICAgICAg"
    "IHN0YXRlX2NoYW5nZWQoc3RyKSAg4oCUICJBV0FLRSIgfCAiQVVUTyIgfCAiU1VTUEVORCIKICAgICIiIgoKICAgIHN0YXRlX2No"
    "YW5nZWQgPSBTaWduYWwoc3RyKQoKICAgIFNUQVRFUyA9IFsiQVdBS0UiLCAiQVVUTyIsICJTVVNQRU5EIl0KCiAgICBTVEFURV9T"
    "VFlMRVMgPSB7CiAgICAgICAgIkFXQUtFIjogewogICAgICAgICAgICAiYWN0aXZlIjogICBmImJhY2tncm91bmQ6ICMyYTFhMDU7"
    "IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0dPTER9OyBi"
    "b3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6"
    "IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAgICAgICAgImluYWN0aXZlIjogZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBj"
    "b2xvcjoge0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVS"
    "fTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2Vp"
    "Z2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJsYWJlbCI6ICAgICLimIAgQVdBS0UiLAogICAgICAg"
    "ICAgICAidG9vbHRpcCI6ICAiTW9kZWwgYWN0aXZlLiBBdXRvLXRvcnBvciBkaXNhYmxlZC4iLAogICAgICAgIH0sCiAgICAgICAg"
    "IkFVVE8iOiB7CiAgICAgICAgICAgICJhY3RpdmUiOiAgIGYiYmFja2dyb3VuZDogIzFhMTAwNTsgY29sb3I6ICNjYzg4MjI7ICIK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCAjY2M4ODIyOyBib3JkZXItcmFkaXVzOiAycHg7ICIK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4"
    "cHg7IiwKICAgICAgICAgICAgImluYWN0aXZlIjogZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAi"
    "CiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4"
    "OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAz"
    "cHggOHB4OyIsCiAgICAgICAgICAgICJsYWJlbCI6ICAgICLil4kgQVVUTyIsCiAgICAgICAgICAgICJ0b29sdGlwIjogICJNb2Rl"
    "bCBhY3RpdmUuIEF1dG8tc3VzcGVuZCBvbiBWUkFNIHByZXNzdXJlLiIsCiAgICAgICAgfSwKICAgICAgICAiU1VTUEVORCI6IHsK"
    "ICAgICAgICAgICAgImFjdGl2ZSI6ICAgZiJiYWNrZ3JvdW5kOiB7Q19QVVJQTEVfRElNfTsgY29sb3I6IHtDX1BVUlBMRX07ICIK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19QVVJQTEV9OyBib3JkZXItcmFkaXVzOiAycHg7"
    "ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNw"
    "eCA4cHg7IiwKICAgICAgICAgICAgImluYWN0aXZlIjogZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19"
    "OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czog"
    "MnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5n"
    "OiAzcHggOHB4OyIsCiAgICAgICAgICAgICJsYWJlbCI6ICAgIGYi4pqwIHtVSV9TVVNQRU5TSU9OX0xBQkVMLnN0cmlwKCkgaWYg"
    "c3RyKFVJX1NVU1BFTlNJT05fTEFCRUwpLnN0cmlwKCkgZWxzZSAnU3VzcGVuZCd9IiwKICAgICAgICAgICAgInRvb2x0aXAiOiAg"
    "ZiJNb2RlbCB1bmxvYWRlZC4ge0RFQ0tfTkFNRX0gc2xlZXBzIHVudGlsIG1hbnVhbGx5IGF3YWtlbmVkLiIsCiAgICAgICAgfSwK"
    "ICAgIH0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50"
    "KQogICAgICAgIHNlbGYuX2N1cnJlbnQgPSAiQVdBS0UiCiAgICAgICAgc2VsZi5fYnV0dG9uczogZGljdFtzdHIsIFFQdXNoQnV0"
    "dG9uXSA9IHt9CiAgICAgICAgbGF5b3V0ID0gUUhCb3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJn"
    "aW5zKDAsIDAsIDAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoMikKCiAgICAgICAgZm9yIHN0YXRlIGluIHNlbGYuU1RB"
    "VEVTOgogICAgICAgICAgICBidG4gPSBRUHVzaEJ1dHRvbihzZWxmLlNUQVRFX1NUWUxFU1tzdGF0ZV1bImxhYmVsIl0pCiAgICAg"
    "ICAgICAgIGJ0bi5zZXRUb29sVGlwKHNlbGYuU1RBVEVfU1RZTEVTW3N0YXRlXVsidG9vbHRpcCJdKQogICAgICAgICAgICBidG4u"
    "c2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgICAgIGJ0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhIGNoZWNrZWQsIHM9c3RhdGU6"
    "IHNlbGYuX3NldF9zdGF0ZShzKSkKICAgICAgICAgICAgc2VsZi5fYnV0dG9uc1tzdGF0ZV0gPSBidG4KICAgICAgICAgICAgbGF5"
    "b3V0LmFkZFdpZGdldChidG4pCgogICAgICAgIHNlbGYuX2FwcGx5X3N0eWxlcygpCgogICAgZGVmIF9zZXRfc3RhdGUoc2VsZiwg"
    "c3RhdGU6IHN0cikgLT4gTm9uZToKICAgICAgICBpZiBzdGF0ZSA9PSBzZWxmLl9jdXJyZW50OgogICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICBzZWxmLl9jdXJyZW50ID0gc3RhdGUKICAgICAgICBzZWxmLl9hcHBseV9zdHlsZXMoKQogICAgICAgIHNlbGYuc3Rh"
    "dGVfY2hhbmdlZC5lbWl0KHN0YXRlKQoKICAgIGRlZiBfYXBwbHlfc3R5bGVzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZm9yIHN0"
    "YXRlLCBidG4gaW4gc2VsZi5fYnV0dG9ucy5pdGVtcygpOgogICAgICAgICAgICBzdHlsZV9rZXkgPSAiYWN0aXZlIiBpZiBzdGF0"
    "ZSA9PSBzZWxmLl9jdXJyZW50IGVsc2UgImluYWN0aXZlIgogICAgICAgICAgICBidG4uc2V0U3R5bGVTaGVldChzZWxmLlNUQVRF"
    "X1NUWUxFU1tzdGF0ZV1bc3R5bGVfa2V5XSkKCiAgICBAcHJvcGVydHkKICAgIGRlZiBjdXJyZW50X3N0YXRlKHNlbGYpIC0+IHN0"
    "cjoKICAgICAgICByZXR1cm4gc2VsZi5fY3VycmVudAoKICAgIGRlZiBzZXRfc3RhdGUoc2VsZiwgc3RhdGU6IHN0cikgLT4gTm9u"
    "ZToKICAgICAgICAiIiJTZXQgc3RhdGUgcHJvZ3JhbW1hdGljYWxseSAoZS5nLiBmcm9tIGF1dG8tdG9ycG9yIGRldGVjdGlvbiku"
    "IiIiCiAgICAgICAgaWYgc3RhdGUgaW4gc2VsZi5TVEFURVM6CiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0ZShzdGF0ZSkKCgpj"
    "bGFzcyBTZXR0aW5nc1NlY3Rpb24oUVdpZGdldCk6CiAgICAiIiJTaW1wbGUgY29sbGFwc2libGUgc2VjdGlvbiB1c2VkIGJ5IFNl"
    "dHRpbmdzVGFiLiIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCB0aXRsZTogc3RyLCBwYXJlbnQ9Tm9uZSwgZXhwYW5kZWQ6IGJv"
    "b2wgPSBUcnVlKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IGV4cGFu"
    "ZGVkCgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDAsIDAs"
    "IDAsIDApCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDApCgogICAgICAgIHNlbGYuX2hlYWRlcl9idG4gPSBRVG9vbEJ1dHRvbigp"
    "CiAgICAgICAgc2VsZi5faGVhZGVyX2J0bi5zZXRUZXh0KGYi4pa8IHt0aXRsZX0iIGlmIGV4cGFuZGVkIGVsc2UgZiLilrYge3Rp"
    "dGxlfSIpCiAgICAgICAgc2VsZi5faGVhZGVyX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtD"
    "X0JHM307IGNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgIGYi"
    "cGFkZGluZzogNnB4OyB0ZXh0LWFsaWduOiBsZWZ0OyBmb250LXdlaWdodDogYm9sZDsiCiAgICAgICAgKQogICAgICAgIHNlbGYu"
    "X2hlYWRlcl9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZSkKCiAgICAgICAgc2VsZi5fY29udGVudCA9IFFXaWRnZXQo"
    "KQogICAgICAgIHNlbGYuX2NvbnRlbnRfbGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fY29udGVudCkKICAgICAgICBzZWxmLl9j"
    "b250ZW50X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoOCwgOCwgOCwgOCkKICAgICAgICBzZWxmLl9jb250ZW50X2xheW91dC5z"
    "ZXRTcGFjaW5nKDgpCiAgICAgICAgc2VsZi5fY29udGVudC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6"
    "IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci10b3A6IG5vbmU7IgogICAgICAgICkKICAgICAg"
    "ICBzZWxmLl9jb250ZW50LnNldFZpc2libGUoZXhwYW5kZWQpCgogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2hlYWRlcl9i"
    "dG4pCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fY29udGVudCkKCiAgICBAcHJvcGVydHkKICAgIGRlZiBjb250ZW50X2xh"
    "eW91dChzZWxmKSAtPiBRVkJveExheW91dDoKICAgICAgICByZXR1cm4gc2VsZi5fY29udGVudF9sYXlvdXQKCiAgICBkZWYgX3Rv"
    "Z2dsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2V4cGFuZGVkID0gbm90IHNlbGYuX2V4cGFuZGVkCiAgICAgICAgc2Vs"
    "Zi5faGVhZGVyX2J0bi5zZXRUZXh0KAogICAgICAgICAgICBzZWxmLl9oZWFkZXJfYnRuLnRleHQoKS5yZXBsYWNlKCLilrwiLCAi"
    "4pa2IiwgMSkKICAgICAgICAgICAgaWYgbm90IHNlbGYuX2V4cGFuZGVkIGVsc2UKICAgICAgICAgICAgc2VsZi5faGVhZGVyX2J0"
    "bi50ZXh0KCkucmVwbGFjZSgi4pa2IiwgIuKWvCIsIDEpCiAgICAgICAgKQogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0VmlzaWJs"
    "ZShzZWxmLl9leHBhbmRlZCkKCgpjbGFzcyBTZXR0aW5nc1RhYihRV2lkZ2V0KToKICAgICIiIkRlY2std2lkZSBydW50aW1lIHNl"
    "dHRpbmdzIHRhYi4iIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgZGVja193aW5kb3c6ICJFY2hvRGVjayIsIHBhcmVudD1Ob25l"
    "KToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9kZWNrID0gZGVja193aW5kb3cKICAgICAg"
    "ICBzZWxmLl9zZWN0aW9uX3JlZ2lzdHJ5OiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9zZWN0aW9uX3dpZGdldHM6IGRp"
    "Y3Rbc3RyLCBTZXR0aW5nc1NlY3Rpb25dID0ge30KCiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9v"
    "dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICByb290LnNldFNwYWNpbmcoMCkKCiAgICAgICAgc2Nyb2xs"
    "ID0gUVNjcm9sbEFyZWEoKQogICAgICAgIHNjcm9sbC5zZXRXaWRnZXRSZXNpemFibGUoVHJ1ZSkKICAgICAgICBzY3JvbGwuc2V0"
    "SG9yaXpvbnRhbFNjcm9sbEJhclBvbGljeShRdC5TY3JvbGxCYXJQb2xpY3kuU2Nyb2xsQmFyQWx3YXlzT2ZmKQogICAgICAgIHNj"
    "cm9sbC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkd9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07"
    "IikKICAgICAgICByb290LmFkZFdpZGdldChzY3JvbGwpCgogICAgICAgIGJvZHkgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9i"
    "b2R5X2xheW91dCA9IFFWQm94TGF5b3V0KGJvZHkpCiAgICAgICAgc2VsZi5fYm9keV9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5z"
    "KDYsIDYsIDYsIDYpCiAgICAgICAgc2VsZi5fYm9keV9sYXlvdXQuc2V0U3BhY2luZyg4KQogICAgICAgIHNjcm9sbC5zZXRXaWRn"
    "ZXQoYm9keSkKCiAgICAgICAgc2VsZi5fcmVnaXN0ZXJfY29yZV9zZWN0aW9ucygpCgogICAgZGVmIF9yZWdpc3Rlcl9zZWN0aW9u"
    "KHNlbGYsICosIHNlY3Rpb25faWQ6IHN0ciwgdGl0bGU6IHN0ciwgY2F0ZWdvcnk6IHN0ciwgc291cmNlX293bmVyOiBzdHIsIHNv"
    "cnRfa2V5OiBpbnQsIGJ1aWxkZXIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2VjdGlvbl9yZWdpc3RyeS5hcHBlbmQoewogICAg"
    "ICAgICAgICAic2VjdGlvbl9pZCI6IHNlY3Rpb25faWQsCiAgICAgICAgICAgICJ0aXRsZSI6IHRpdGxlLAogICAgICAgICAgICAi"
    "Y2F0ZWdvcnkiOiBjYXRlZ29yeSwKICAgICAgICAgICAgInNvdXJjZV9vd25lciI6IHNvdXJjZV9vd25lciwKICAgICAgICAgICAg"
    "InNvcnRfa2V5Ijogc29ydF9rZXksCiAgICAgICAgICAgICJidWlsZGVyIjogYnVpbGRlciwKICAgICAgICB9KQoKICAgIGRlZiBf"
    "cmVnaXN0ZXJfY29yZV9zZWN0aW9ucyhzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlZ2lzdGVyX3NlY3Rpb24oCiAgICAg"
    "ICAgICAgIHNlY3Rpb25faWQ9InN5c3RlbV9zZXR0aW5ncyIsCiAgICAgICAgICAgIHRpdGxlPSJTeXN0ZW0gU2V0dGluZ3MiLAog"
    "ICAgICAgICAgICBjYXRlZ29yeT0iY29yZSIsCiAgICAgICAgICAgIHNvdXJjZV9vd25lcj0iZGVja19ydW50aW1lIiwKICAgICAg"
    "ICAgICAgc29ydF9rZXk9MTAwLAogICAgICAgICAgICBidWlsZGVyPXNlbGYuX2J1aWxkX3N5c3RlbV9zZWN0aW9uLAogICAgICAg"
    "ICkKICAgICAgICBzZWxmLl9yZWdpc3Rlcl9zZWN0aW9uKAogICAgICAgICAgICBzZWN0aW9uX2lkPSJpbnRlZ3JhdGlvbl9zZXR0"
    "aW5ncyIsCiAgICAgICAgICAgIHRpdGxlPSJJbnRlZ3JhdGlvbiBTZXR0aW5ncyIsCiAgICAgICAgICAgIGNhdGVnb3J5PSJjb3Jl"
    "IiwKICAgICAgICAgICAgc291cmNlX293bmVyPSJkZWNrX3J1bnRpbWUiLAogICAgICAgICAgICBzb3J0X2tleT0yMDAsCiAgICAg"
    "ICAgICAgIGJ1aWxkZXI9c2VsZi5fYnVpbGRfaW50ZWdyYXRpb25fc2VjdGlvbiwKICAgICAgICApCiAgICAgICAgc2VsZi5fcmVn"
    "aXN0ZXJfc2VjdGlvbigKICAgICAgICAgICAgc2VjdGlvbl9pZD0idWlfc2V0dGluZ3MiLAogICAgICAgICAgICB0aXRsZT0iVUkg"
    "U2V0dGluZ3MiLAogICAgICAgICAgICBjYXRlZ29yeT0iY29yZSIsCiAgICAgICAgICAgIHNvdXJjZV9vd25lcj0iZGVja19ydW50"
    "aW1lIiwKICAgICAgICAgICAgc29ydF9rZXk9MzAwLAogICAgICAgICAgICBidWlsZGVyPXNlbGYuX2J1aWxkX3VpX3NlY3Rpb24s"
    "CiAgICAgICAgKQoKICAgICAgICBmb3IgbWV0YSBpbiBzb3J0ZWQoc2VsZi5fc2VjdGlvbl9yZWdpc3RyeSwga2V5PWxhbWJkYSBt"
    "OiBtLmdldCgic29ydF9rZXkiLCA5OTk5KSk6CiAgICAgICAgICAgIHNlY3Rpb24gPSBTZXR0aW5nc1NlY3Rpb24obWV0YVsidGl0"
    "bGUiXSwgZXhwYW5kZWQ9VHJ1ZSkKICAgICAgICAgICAgc2VsZi5fYm9keV9sYXlvdXQuYWRkV2lkZ2V0KHNlY3Rpb24pCiAgICAg"
    "ICAgICAgIHNlbGYuX3NlY3Rpb25fd2lkZ2V0c1ttZXRhWyJzZWN0aW9uX2lkIl1dID0gc2VjdGlvbgogICAgICAgICAgICBtZXRh"
    "WyJidWlsZGVyIl0oc2VjdGlvbi5jb250ZW50X2xheW91dCkKCiAgICAgICAgc2VsZi5fYm9keV9sYXlvdXQuYWRkU3RyZXRjaCgx"
    "KQoKICAgIGRlZiBfYnVpbGRfc3lzdGVtX3NlY3Rpb24oc2VsZiwgbGF5b3V0OiBRVkJveExheW91dCkgLT4gTm9uZToKICAgICAg"
    "ICBpZiBzZWxmLl9kZWNrLl90b3Jwb3JfcGFuZWwgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoUUxh"
    "YmVsKCJPcGVyYXRpb25hbCBNb2RlIikpCiAgICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZGVjay5fdG9ycG9yX3Bh"
    "bmVsKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KFFMYWJlbCgiSWRsZSIpKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2Vs"
    "Zi5fZGVjay5faWRsZV9idG4pCgogICAgICAgIHNldHRpbmdzID0gQ0ZHLmdldCgic2V0dGluZ3MiLCB7fSkKICAgICAgICB0el9h"
    "dXRvID0gYm9vbChzZXR0aW5ncy5nZXQoInRpbWV6b25lX2F1dG9fZGV0ZWN0IiwgVHJ1ZSkpCiAgICAgICAgdHpfb3ZlcnJpZGUg"
    "PSBzdHIoc2V0dGluZ3MuZ2V0KCJ0aW1lem9uZV9vdmVycmlkZSIsICIiKSBvciAiIikuc3RyaXAoKQoKICAgICAgICB0el9hdXRv"
    "X2NoayA9IFFDaGVja0JveCgiQXV0by1kZXRlY3QgbG9jYWwvc3lzdGVtIHRpbWUgem9uZSIpCiAgICAgICAgdHpfYXV0b19jaGsu"
    "c2V0Q2hlY2tlZCh0el9hdXRvKQogICAgICAgIHR6X2F1dG9fY2hrLnRvZ2dsZWQuY29ubmVjdChzZWxmLl9kZWNrLl9zZXRfdGlt"
    "ZXpvbmVfYXV0b19kZXRlY3QpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldCh0el9hdXRvX2NoaykKCiAgICAgICAgdHpfcm93ID0g"
    "UUhCb3hMYXlvdXQoKQogICAgICAgIHR6X3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJNYW51YWwgVGltZSBab25lIE92ZXJyaWRlOiIp"
    "KQogICAgICAgIHR6X2NvbWJvID0gUUNvbWJvQm94KCkKICAgICAgICB0el9jb21iby5zZXRFZGl0YWJsZShUcnVlKQogICAgICAg"
    "IHR6X29wdGlvbnMgPSBbCiAgICAgICAgICAgICJBbWVyaWNhL0NoaWNhZ28iLCAiQW1lcmljYS9OZXdfWW9yayIsICJBbWVyaWNh"
    "L0xvc19BbmdlbGVzIiwKICAgICAgICAgICAgIkFtZXJpY2EvRGVudmVyIiwgIlVUQyIKICAgICAgICBdCiAgICAgICAgdHpfY29t"
    "Ym8uYWRkSXRlbXModHpfb3B0aW9ucykKICAgICAgICBpZiB0el9vdmVycmlkZToKICAgICAgICAgICAgaWYgdHpfY29tYm8uZmlu"
    "ZFRleHQodHpfb3ZlcnJpZGUpIDwgMDoKICAgICAgICAgICAgICAgIHR6X2NvbWJvLmFkZEl0ZW0odHpfb3ZlcnJpZGUpCiAgICAg"
    "ICAgICAgIHR6X2NvbWJvLnNldEN1cnJlbnRUZXh0KHR6X292ZXJyaWRlKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHR6X2Nv"
    "bWJvLnNldEN1cnJlbnRUZXh0KCJBbWVyaWNhL0NoaWNhZ28iKQogICAgICAgIHR6X2NvbWJvLnNldEVuYWJsZWQobm90IHR6X2F1"
    "dG8pCiAgICAgICAgdHpfY29tYm8uY3VycmVudFRleHRDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fZGVjay5fc2V0X3RpbWV6b25lX292"
    "ZXJyaWRlKQogICAgICAgIHR6X2F1dG9fY2hrLnRvZ2dsZWQuY29ubmVjdChsYW1iZGEgZW5hYmxlZDogdHpfY29tYm8uc2V0RW5h"
    "YmxlZChub3QgZW5hYmxlZCkpCiAgICAgICAgdHpfcm93LmFkZFdpZGdldCh0el9jb21ibywgMSkKICAgICAgICB0el9ob3N0ID0g"
    "UVdpZGdldCgpCiAgICAgICAgdHpfaG9zdC5zZXRMYXlvdXQodHpfcm93KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQodHpfaG9z"
    "dCkKCiAgICBkZWYgX2J1aWxkX2ludGVncmF0aW9uX3NlY3Rpb24oc2VsZiwgbGF5b3V0OiBRVkJveExheW91dCkgLT4gTm9uZToK"
    "ICAgICAgICBzZXR0aW5ncyA9IENGRy5nZXQoInNldHRpbmdzIiwge30pCiAgICAgICAgZ29vZ2xlX3NlY29uZHMgPSBpbnQoc2V0"
    "dGluZ3MuZ2V0KCJnb29nbGVfaW5ib3VuZF9pbnRlcnZhbF9tcyIsIDMwMDAwKSkgLy8gMTAwMAogICAgICAgIGdvb2dsZV9zZWNv"
    "bmRzID0gbWF4KDUsIG1pbig2MDAsIGdvb2dsZV9zZWNvbmRzKSkKICAgICAgICBlbWFpbF9taW51dGVzID0gbWF4KDEsIGludChz"
    "ZXR0aW5ncy5nZXQoImVtYWlsX3JlZnJlc2hfaW50ZXJ2YWxfbXMiLCAzMDAwMDApKSAvLyA2MDAwMCkKCiAgICAgICAgZ29vZ2xl"
    "X3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBnb29nbGVfcm93LmFkZFdpZGdldChRTGFiZWwoIkdvb2dsZSByZWZyZXNoIGlu"
    "dGVydmFsIChzZWNvbmRzKToiKSkKICAgICAgICBnb29nbGVfYm94ID0gUVNwaW5Cb3goKQogICAgICAgIGdvb2dsZV9ib3guc2V0"
    "UmFuZ2UoNSwgNjAwKQogICAgICAgIGdvb2dsZV9ib3guc2V0VmFsdWUoZ29vZ2xlX3NlY29uZHMpCiAgICAgICAgZ29vZ2xlX2Jv"
    "eC52YWx1ZUNoYW5nZWQuY29ubmVjdChzZWxmLl9kZWNrLl9zZXRfZ29vZ2xlX3JlZnJlc2hfc2Vjb25kcykKICAgICAgICBnb29n"
    "bGVfcm93LmFkZFdpZGdldChnb29nbGVfYm94LCAxKQogICAgICAgIGdvb2dsZV9ob3N0ID0gUVdpZGdldCgpCiAgICAgICAgZ29v"
    "Z2xlX2hvc3Quc2V0TGF5b3V0KGdvb2dsZV9yb3cpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChnb29nbGVfaG9zdCkKCiAgICAg"
    "ICAgZW1haWxfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGVtYWlsX3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJFbWFpbCByZWZy"
    "ZXNoIGludGVydmFsIChtaW51dGVzKToiKSkKICAgICAgICBlbWFpbF9ib3ggPSBRQ29tYm9Cb3goKQogICAgICAgIGVtYWlsX2Jv"
    "eC5zZXRFZGl0YWJsZShUcnVlKQogICAgICAgIGVtYWlsX2JveC5hZGRJdGVtcyhbIjEiLCAiNSIsICIxMCIsICIxNSIsICIzMCIs"
    "ICI2MCJdKQogICAgICAgIGVtYWlsX2JveC5zZXRDdXJyZW50VGV4dChzdHIoZW1haWxfbWludXRlcykpCiAgICAgICAgZW1haWxf"
    "Ym94LmN1cnJlbnRUZXh0Q2hhbmdlZC5jb25uZWN0KHNlbGYuX2RlY2suX3NldF9lbWFpbF9yZWZyZXNoX21pbnV0ZXNfZnJvbV90"
    "ZXh0KQogICAgICAgIGVtYWlsX3Jvdy5hZGRXaWRnZXQoZW1haWxfYm94LCAxKQogICAgICAgIGVtYWlsX2hvc3QgPSBRV2lkZ2V0"
    "KCkKICAgICAgICBlbWFpbF9ob3N0LnNldExheW91dChlbWFpbF9yb3cpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChlbWFpbF9o"
    "b3N0KQoKICAgICAgICBub3RlID0gUUxhYmVsKCJFbWFpbCBwb2xsaW5nIGZvdW5kYXRpb24gaXMgY29uZmlndXJhdGlvbi1vbmx5"
    "IHVubGVzcyBhbiBlbWFpbCBiYWNrZW5kIGlzIGVuYWJsZWQuIikKICAgICAgICBub3RlLnNldFN0eWxlU2hlZXQoZiJjb2xvcjog"
    "e0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlweDsiKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQobm90ZSkKCiAgICBkZWYgX2J1"
    "aWxkX3VpX3NlY3Rpb24oc2VsZiwgbGF5b3V0OiBRVkJveExheW91dCkgLT4gTm9uZToKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0"
    "KFFMYWJlbCgiV2luZG93IFNoZWxsIikpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9kZWNrLl9mc19idG4pCiAgICAg"
    "ICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9kZWNrLl9ibF9idG4pCgoKY2xhc3MgRGljZUdseXBoKFFXaWRnZXQpOgogICAgIiIi"
    "U2ltcGxlIDJEIHNpbGhvdWV0dGUgcmVuZGVyZXIgZm9yIGRpZS10eXBlIHJlY29nbml0aW9uLiIiIgogICAgZGVmIF9faW5pdF9f"
    "KHNlbGYsIGRpZV90eXBlOiBzdHIgPSAiZDIwIiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50"
    "KQogICAgICAgIHNlbGYuX2RpZV90eXBlID0gZGllX3R5cGUKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDcwLCA3MCkKICAg"
    "ICAgICBzZWxmLnNldE1heGltdW1TaXplKDkwLCA5MCkKCiAgICBkZWYgc2V0X2RpZV90eXBlKHNlbGYsIGRpZV90eXBlOiBzdHIp"
    "IC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZGllX3R5cGUgPSBkaWVfdHlwZQogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYg"
    "cGFpbnRFdmVudChzZWxmLCBldmVudCk6CiAgICAgICAgcGFpbnRlciA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcGFpbnRlci5z"
    "ZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHJlY3QgPSBzZWxmLnJlY3QoKS5h"
    "ZGp1c3RlZCg4LCA4LCAtOCwgLTgpCgogICAgICAgIGRpZSA9IHNlbGYuX2RpZV90eXBlCiAgICAgICAgbGluZSA9IFFDb2xvcihD"
    "X0dPTEQpCiAgICAgICAgZmlsbCA9IFFDb2xvcihDX0JHMikKICAgICAgICBhY2NlbnQgPSBRQ29sb3IoQ19DUklNU09OKQoKICAg"
    "ICAgICBwYWludGVyLnNldFBlbihRUGVuKGxpbmUsIDIpKQogICAgICAgIHBhaW50ZXIuc2V0QnJ1c2goZmlsbCkKCiAgICAgICAg"
    "cHRzID0gW10KICAgICAgICBpZiBkaWUgPT0gImQ0IjoKICAgICAgICAgICAgcHRzID0gWwogICAgICAgICAgICAgICAgUVBvaW50"
    "KHJlY3QuY2VudGVyKCkueCgpLCByZWN0LnRvcCgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmxlZnQoKSwgcmVjdC5i"
    "b3R0b20oKSksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5yaWdodCgpLCByZWN0LmJvdHRvbSgpKSwKICAgICAgICAgICAg"
    "XQogICAgICAgIGVsaWYgZGllID09ICJkNiI6CiAgICAgICAgICAgIHBhaW50ZXIuZHJhd1JvdW5kZWRSZWN0KHJlY3QsIDQsIDQp"
    "CiAgICAgICAgZWxpZiBkaWUgPT0gImQ4IjoKICAgICAgICAgICAgcHRzID0gWwogICAgICAgICAgICAgICAgUVBvaW50KHJlY3Qu"
    "Y2VudGVyKCkueCgpLCByZWN0LnRvcCgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmxlZnQoKSwgcmVjdC5jZW50ZXIo"
    "KS55KCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QuY2VudGVyKCkueCgpLCByZWN0LmJvdHRvbSgpKSwKICAgICAgICAg"
    "ICAgICAgIFFQb2ludChyZWN0LnJpZ2h0KCksIHJlY3QuY2VudGVyKCkueSgpKSwKICAgICAgICAgICAgXQogICAgICAgIGVsaWYg"
    "ZGllIGluICgiZDEwIiwgImQxMDAiKToKICAgICAgICAgICAgcHRzID0gWwogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QuY2Vu"
    "dGVyKCkueCgpLCByZWN0LnRvcCgpKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmxlZnQoKSArIDgsIHJlY3QudG9wKCkg"
    "KyAxNiksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5sZWZ0KCksIHJlY3QuYm90dG9tKCkgLSAxMiksCiAgICAgICAgICAg"
    "ICAgICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJlY3QuYm90dG9tKCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3Qu"
    "cmlnaHQoKSwgcmVjdC5ib3R0b20oKSAtIDEyKSwKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LnJpZ2h0KCkgLSA4LCByZWN0"
    "LnRvcCgpICsgMTYpLAogICAgICAgICAgICBdCiAgICAgICAgZWxpZiBkaWUgPT0gImQxMiI6CiAgICAgICAgICAgIGN4ID0gcmVj"
    "dC5jZW50ZXIoKS54KCk7IGN5ID0gcmVjdC5jZW50ZXIoKS55KCkKICAgICAgICAgICAgcnggPSByZWN0LndpZHRoKCkgLyAyOyBy"
    "eSA9IHJlY3QuaGVpZ2h0KCkgLyAyCiAgICAgICAgICAgIGZvciBpIGluIHJhbmdlKDUpOgogICAgICAgICAgICAgICAgYSA9ICht"
    "YXRoLnBpICogMiAqIGkgLyA1KSAtIChtYXRoLnBpIC8gMikKICAgICAgICAgICAgICAgIHB0cy5hcHBlbmQoUVBvaW50KGludChj"
    "eCArIHJ4ICogbWF0aC5jb3MoYSkpLCBpbnQoY3kgKyByeSAqIG1hdGguc2luKGEpKSkpCiAgICAgICAgZWxzZTogICMgZDIwCiAg"
    "ICAgICAgICAgIHB0cyA9IFsKICAgICAgICAgICAgICAgIFFQb2ludChyZWN0LmNlbnRlcigpLngoKSwgcmVjdC50b3AoKSksCiAg"
    "ICAgICAgICAgICAgICBRUG9pbnQocmVjdC5sZWZ0KCkgKyAxMCwgcmVjdC50b3AoKSArIDE0KSwKICAgICAgICAgICAgICAgIFFQ"
    "b2ludChyZWN0LmxlZnQoKSwgcmVjdC5jZW50ZXIoKS55KCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QubGVmdCgpICsg"
    "MTAsIHJlY3QuYm90dG9tKCkgLSAxNCksCiAgICAgICAgICAgICAgICBRUG9pbnQocmVjdC5jZW50ZXIoKS54KCksIHJlY3QuYm90"
    "dG9tKCkpLAogICAgICAgICAgICAgICAgUVBvaW50KHJlY3QucmlnaHQoKSAtIDEwLCByZWN0LmJvdHRvbSgpIC0gMTQpLAogICAg"
    "ICAgICAgICAgICAgUVBvaW50KHJlY3QucmlnaHQoKSwgcmVjdC5jZW50ZXIoKS55KCkpLAogICAgICAgICAgICAgICAgUVBvaW50"
    "KHJlY3QucmlnaHQoKSAtIDEwLCByZWN0LnRvcCgpICsgMTQpLAogICAgICAgICAgICBdCgogICAgICAgIGlmIHB0czoKICAgICAg"
    "ICAgICAgcGF0aCA9IFFQYWludGVyUGF0aCgpCiAgICAgICAgICAgIHBhdGgubW92ZVRvKHB0c1swXSkKICAgICAgICAgICAgZm9y"
    "IHAgaW4gcHRzWzE6XToKICAgICAgICAgICAgICAgIHBhdGgubGluZVRvKHApCiAgICAgICAgICAgIHBhdGguY2xvc2VTdWJwYXRo"
    "KCkKICAgICAgICAgICAgcGFpbnRlci5kcmF3UGF0aChwYXRoKQoKICAgICAgICBwYWludGVyLnNldFBlbihRUGVuKGFjY2VudCwg"
    "MSkpCiAgICAgICAgdHh0ID0gIiUiIGlmIGRpZSA9PSAiZDEwMCIgZWxzZSBkaWUucmVwbGFjZSgiZCIsICIiKQogICAgICAgIHBh"
    "aW50ZXIuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDEyLCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgcGFpbnRlci5kcmF3"
    "VGV4dChyZWN0LCBRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyLCB0eHQpCgoKY2xhc3MgRGljZVRyYXlEaWUoUUZyYW1lKToK"
    "ICAgIHNpbmdsZUNsaWNrZWQgPSBTaWduYWwoc3RyKQogICAgZG91YmxlQ2xpY2tlZCA9IFNpZ25hbChzdHIpCgogICAgZGVmIF9f"
    "aW5pdF9fKHNlbGYsIGRpZV90eXBlOiBzdHIsIGRpc3BsYXlfbGFiZWw6IHN0ciwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVy"
    "KCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHNlbGYuZGllX3R5cGUgPSBkaWVfdHlwZQogICAgICAgIHNlbGYuZGlzcGxheV9s"
    "YWJlbCA9IGRpc3BsYXlfbGFiZWwKICAgICAgICBzZWxmLl9jbGlja190aW1lciA9IFFUaW1lcihzZWxmKQogICAgICAgIHNlbGYu"
    "X2NsaWNrX3RpbWVyLnNldFNpbmdsZVNob3QoVHJ1ZSkKICAgICAgICBzZWxmLl9jbGlja190aW1lci5zZXRJbnRlcnZhbCgyMjAp"
    "CiAgICAgICAgc2VsZi5fY2xpY2tfdGltZXIudGltZW91dC5jb25uZWN0KHNlbGYuX2VtaXRfc2luZ2xlKQoKICAgICAgICBzZWxm"
    "LnNldE9iamVjdE5hbWUoIkRpY2VUcmF5RGllIikKICAgICAgICBzZWxmLnNldEN1cnNvcihRdC5DdXJzb3JTaGFwZS5Qb2ludGlu"
    "Z0hhbmRDdXJzb3IpCiAgICAgICAgc2VsZi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmIlFGcmFtZSNEaWNlVHJheURpZSB7"
    "eyBiYWNrZ3JvdW5kOiB7Q19CRzN9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19CT1JERVJ9OyBib3JkZXItcmFkaXVzOiA4cHg7IH19"
    "IgogICAgICAgICAgICBmIlFGcmFtZSNEaWNlVHJheURpZTpob3ZlciB7eyBib3JkZXI6IDFweCBzb2xpZCB7Q19HT0xEfTsgfX0i"
    "CiAgICAgICAgKQoKICAgICAgICBsYXkgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIGxheS5zZXRDb250ZW50c01hcmdpbnMo"
    "NiwgNiwgNiwgNikKICAgICAgICBsYXkuc2V0U3BhY2luZygyKQoKICAgICAgICBnbHlwaF9kaWUgPSAiZDEwMCIgaWYgZGllX3R5"
    "cGUgPT0gImQlIiBlbHNlIGRpZV90eXBlCiAgICAgICAgc2VsZi5nbHlwaCA9IERpY2VHbHlwaChnbHlwaF9kaWUpCiAgICAgICAg"
    "c2VsZi5nbHlwaC5zZXRGaXhlZFNpemUoNTQsIDU0KQogICAgICAgIHNlbGYuZ2x5cGguc2V0QXR0cmlidXRlKFF0LldpZGdldEF0"
    "dHJpYnV0ZS5XQV9UcmFuc3BhcmVudEZvck1vdXNlRXZlbnRzLCBUcnVlKQoKICAgICAgICBzZWxmLmxibCA9IFFMYWJlbChkaXNw"
    "bGF5X2xhYmVsKQogICAgICAgIHNlbGYubGJsLnNldEFsaWdubWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAg"
    "ICAgIHNlbGYubGJsLnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfVEVYVH07IGZvbnQtd2VpZ2h0OiBib2xkOyIpCiAgICAgICAg"
    "c2VsZi5sYmwuc2V0QXR0cmlidXRlKFF0LldpZGdldEF0dHJpYnV0ZS5XQV9UcmFuc3BhcmVudEZvck1vdXNlRXZlbnRzLCBUcnVl"
    "KQoKICAgICAgICBsYXkuYWRkV2lkZ2V0KHNlbGYuZ2x5cGgsIDAsIFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAg"
    "ICAgbGF5LmFkZFdpZGdldChzZWxmLmxibCkKCiAgICBkZWYgbW91c2VQcmVzc0V2ZW50KHNlbGYsIGV2ZW50KToKICAgICAgICBp"
    "ZiBldmVudC5idXR0b24oKSA9PSBRdC5Nb3VzZUJ1dHRvbi5MZWZ0QnV0dG9uOgogICAgICAgICAgICBpZiBzZWxmLl9jbGlja190"
    "aW1lci5pc0FjdGl2ZSgpOgogICAgICAgICAgICAgICAgc2VsZi5fY2xpY2tfdGltZXIuc3RvcCgpCiAgICAgICAgICAgICAgICBz"
    "ZWxmLmRvdWJsZUNsaWNrZWQuZW1pdChzZWxmLmRpZV90eXBlKQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fY2xpY2tfdGltZXIuc3RhcnQoKQogICAgICAgICAgICBldmVudC5hY2NlcHQoKQogICAgICAgICAgICByZXR1cm4KICAgICAg"
    "ICBzdXBlcigpLm1vdXNlUHJlc3NFdmVudChldmVudCkKCiAgICBkZWYgX2VtaXRfc2luZ2xlKHNlbGYpOgogICAgICAgIHNlbGYu"
    "c2luZ2xlQ2xpY2tlZC5lbWl0KHNlbGYuZGllX3R5cGUpCgoKY2xhc3MgRGljZVJvbGxlclRhYihRV2lkZ2V0KToKICAgICIiIkRl"
    "Y2stbmF0aXZlIERpY2UgUm9sbGVyIG1vZHVsZSB0YWIgd2l0aCB0cmF5L3Bvb2wgd29ya2Zsb3cgYW5kIHN0cnVjdHVyZWQgcm9s"
    "bCBldmVudHMuIiIiCgogICAgVFJBWV9PUkRFUiA9IFsiZDQiLCAiZDYiLCAiZDgiLCAiZDEwIiwgImQxMiIsICJkMjAiLCAiZCUi"
    "XQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBkaWFnbm9zdGljc19sb2dnZXI9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRf"
    "XygpCiAgICAgICAgc2VsZi5fbG9nID0gZGlhZ25vc3RpY3NfbG9nZ2VyIG9yIChsYW1iZGEgKl9hcmdzLCAqKl9rd2FyZ3M6IE5v"
    "bmUpCgogICAgICAgIHNlbGYucm9sbF9ldmVudHM6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuc2F2ZWRfcm9sbHM6IGxp"
    "c3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuY29tbW9uX3JvbGxzOiBkaWN0W3N0ciwgZGljdF0gPSB7fQogICAgICAgIHNlbGYu"
    "ZXZlbnRfYnlfaWQ6IGRpY3Rbc3RyLCBkaWN0XSA9IHt9CiAgICAgICAgc2VsZi5jdXJyZW50X3Bvb2w6IGRpY3Rbc3RyLCBpbnRd"
    "ID0ge30KICAgICAgICBzZWxmLmN1cnJlbnRfcm9sbF9pZHM6IGxpc3Rbc3RyXSA9IFtdCgogICAgICAgIHNlbGYucnVsZV9kZWZp"
    "bml0aW9uczogZGljdFtzdHIsIGRpY3RdID0gewogICAgICAgICAgICAicnVsZV80ZDZfZHJvcF9sb3dlc3QiOiB7CiAgICAgICAg"
    "ICAgICAgICAiaWQiOiAicnVsZV80ZDZfZHJvcF9sb3dlc3QiLAogICAgICAgICAgICAgICAgIm5hbWUiOiAiRCZEIDVlIFN0YXQg"
    "Um9sbCIsCiAgICAgICAgICAgICAgICAiZGljZV9jb3VudCI6IDQsCiAgICAgICAgICAgICAgICAiZGljZV9zaWRlcyI6IDYsCiAg"
    "ICAgICAgICAgICAgICAiZHJvcF9sb3dlc3RfY291bnQiOiAxLAogICAgICAgICAgICAgICAgImRyb3BfaGlnaGVzdF9jb3VudCI6"
    "IDAsCiAgICAgICAgICAgICAgICAibm90ZXMiOiAiUm9sbCA0ZDYsIGRyb3AgbG93ZXN0IG9uZS4iCiAgICAgICAgICAgIH0sCiAg"
    "ICAgICAgICAgICJydWxlXzNkNl9zdHJhaWdodCI6IHsKICAgICAgICAgICAgICAgICJpZCI6ICJydWxlXzNkNl9zdHJhaWdodCIs"
    "CiAgICAgICAgICAgICAgICAibmFtZSI6ICIzZDYgU3RyYWlnaHQiLAogICAgICAgICAgICAgICAgImRpY2VfY291bnQiOiAzLAog"
    "ICAgICAgICAgICAgICAgImRpY2Vfc2lkZXMiOiA2LAogICAgICAgICAgICAgICAgImRyb3BfbG93ZXN0X2NvdW50IjogMCwKICAg"
    "ICAgICAgICAgICAgICJkcm9wX2hpZ2hlc3RfY291bnQiOiAwLAogICAgICAgICAgICAgICAgIm5vdGVzIjogIkNsYXNzaWMgM2Q2"
    "IHJvbGwuIgogICAgICAgICAgICB9LAogICAgICAgIH0KCiAgICAgICAgc2VsZi5fYnVpbGRfdWkoKQogICAgICAgIHNlbGYuX3Jl"
    "ZnJlc2hfcG9vbF9lZGl0b3IoKQogICAgICAgIHNlbGYuX3JlZnJlc2hfc2F2ZWRfbGlzdHMoKQoKICAgIGRlZiBfYnVpbGRfdWko"
    "c2VsZikgLT4gTm9uZToKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoc2VsZikKICAgICAgICByb290LnNldENvbnRlbnRzTWFy"
    "Z2lucyg4LCA4LCA4LCA4KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg2KQoKICAgICAgICB0cmF5X3dyYXAgPSBRRnJhbWUoKQog"
    "ICAgICAgIHRyYXlfd3JhcC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0Nf"
    "Qk9SREVSfTsiKQogICAgICAgIHRyYXlfbGF5b3V0ID0gUVZCb3hMYXlvdXQodHJheV93cmFwKQogICAgICAgIHRyYXlfbGF5b3V0"
    "LnNldENvbnRlbnRzTWFyZ2lucyg4LCA4LCA4LCA4KQogICAgICAgIHRyYXlfbGF5b3V0LnNldFNwYWNpbmcoNikKICAgICAgICB0"
    "cmF5X2xheW91dC5hZGRXaWRnZXQoUUxhYmVsKCJEaWNlIFRyYXkiKSkKCiAgICAgICAgdHJheV9yb3cgPSBRSEJveExheW91dCgp"
    "CiAgICAgICAgdHJheV9yb3cuc2V0U3BhY2luZyg2KQogICAgICAgIGZvciBkaWUgaW4gc2VsZi5UUkFZX09SREVSOgogICAgICAg"
    "ICAgICBibG9jayA9IERpY2VUcmF5RGllKGRpZSwgZGllKQogICAgICAgICAgICBibG9jay5zaW5nbGVDbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5fYWRkX2RpZV90b19wb29sKQogICAgICAgICAgICBibG9jay5kb3VibGVDbGlja2VkLmNvbm5lY3Qoc2VsZi5fcXVpY2tf"
    "cm9sbF9zaW5nbGVfZGllKQogICAgICAgICAgICB0cmF5X3Jvdy5hZGRXaWRnZXQoYmxvY2ssIDEpCiAgICAgICAgdHJheV9sYXlv"
    "dXQuYWRkTGF5b3V0KHRyYXlfcm93KQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHRyYXlfd3JhcCkKCiAgICAgICAgcG9vbF93cmFw"
    "ID0gUUZyYW1lKCkKICAgICAgICBwb29sX3dyYXAuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjog"
    "MXB4IHNvbGlkIHtDX0JPUkRFUn07IikKICAgICAgICBwdyA9IFFWQm94TGF5b3V0KHBvb2xfd3JhcCkKICAgICAgICBwdy5zZXRD"
    "b250ZW50c01hcmdpbnMoOCwgOCwgOCwgOCkKICAgICAgICBwdy5zZXRTcGFjaW5nKDYpCgogICAgICAgIHB3LmFkZFdpZGdldChR"
    "TGFiZWwoIkN1cnJlbnQgUG9vbCIpKQogICAgICAgIHNlbGYucG9vbF9leHByX2xibCA9IFFMYWJlbCgiUG9vbDogKGVtcHR5KSIp"
    "CiAgICAgICAgc2VsZi5wb29sX2V4cHJfbGJsLnNldFN0eWxlU2hlZXQoZiJjb2xvcjoge0NfR09MRH07IGZvbnQtd2VpZ2h0OiBi"
    "b2xkOyIpCiAgICAgICAgcHcuYWRkV2lkZ2V0KHNlbGYucG9vbF9leHByX2xibCkKCiAgICAgICAgc2VsZi5wb29sX2VudHJpZXNf"
    "d2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5wb29sX2VudHJpZXNfbGF5b3V0ID0gUUhCb3hMYXlvdXQoc2VsZi5wb29s"
    "X2VudHJpZXNfd2lkZ2V0KQogICAgICAgIHNlbGYucG9vbF9lbnRyaWVzX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwg"
    "MCwgMCkKICAgICAgICBzZWxmLnBvb2xfZW50cmllc19sYXlvdXQuc2V0U3BhY2luZyg2KQogICAgICAgIHB3LmFkZFdpZGdldChz"
    "ZWxmLnBvb2xfZW50cmllc193aWRnZXQpCgogICAgICAgIG1ldGFfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYubGFi"
    "ZWxfZWRpdCA9IFFMaW5lRWRpdCgpOyBzZWxmLmxhYmVsX2VkaXQuc2V0UGxhY2Vob2xkZXJUZXh0KCJMYWJlbCAvIHB1cnBvc2Ui"
    "KQogICAgICAgIHNlbGYubW9kX3NwaW4gPSBRU3BpbkJveCgpOyBzZWxmLm1vZF9zcGluLnNldFJhbmdlKC05OTksIDk5OSk7IHNl"
    "bGYubW9kX3NwaW4uc2V0VmFsdWUoMCkKICAgICAgICBzZWxmLnJ1bGVfY29tYm8gPSBRQ29tYm9Cb3goKTsgc2VsZi5ydWxlX2Nv"
    "bWJvLmFkZEl0ZW0oIk1hbnVhbCBSb2xsIiwgIiIpCiAgICAgICAgZm9yIHJpZCwgbWV0YSBpbiBzZWxmLnJ1bGVfZGVmaW5pdGlv"
    "bnMuaXRlbXMoKToKICAgICAgICAgICAgc2VsZi5ydWxlX2NvbWJvLmFkZEl0ZW0obWV0YS5nZXQoIm5hbWUiLCByaWQpLCByaWQp"
    "CgogICAgICAgIGZvciB0aXRsZSwgdyBpbiAoKCJMYWJlbCIsIHNlbGYubGFiZWxfZWRpdCksICgiTW9kaWZpZXIiLCBzZWxmLm1v"
    "ZF9zcGluKSwgKCJSdWxlIiwgc2VsZi5ydWxlX2NvbWJvKSk6CiAgICAgICAgICAgIGNvbCA9IFFWQm94TGF5b3V0KCkKICAgICAg"
    "ICAgICAgbGJsID0gUUxhYmVsKHRpdGxlKQogICAgICAgICAgICBsYmwuc2V0U3R5bGVTaGVldChmImNvbG9yOiB7Q19URVhUX0RJ"
    "TX07IGZvbnQtc2l6ZTogOXB4OyIpCiAgICAgICAgICAgIGNvbC5hZGRXaWRnZXQobGJsKQogICAgICAgICAgICBjb2wuYWRkV2lk"
    "Z2V0KHcpCiAgICAgICAgICAgIG1ldGFfcm93LmFkZExheW91dChjb2wsIDEpCiAgICAgICAgcHcuYWRkTGF5b3V0KG1ldGFfcm93"
    "KQoKICAgICAgICBhY3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYucm9sbF9wb29sX2J0biA9IFFQdXNoQnV0dG9u"
    "KCJSb2xsIFBvb2wiKQogICAgICAgIHNlbGYucmVzZXRfcG9vbF9idG4gPSBRUHVzaEJ1dHRvbigiUmVzZXQgUG9vbCIpCiAgICAg"
    "ICAgc2VsZi5zYXZlX3Bvb2xfYnRuID0gUVB1c2hCdXR0b24oIlNhdmUgUG9vbCIpCiAgICAgICAgYWN0aW9ucy5hZGRXaWRnZXQo"
    "c2VsZi5yb2xsX3Bvb2xfYnRuKQogICAgICAgIGFjdGlvbnMuYWRkV2lkZ2V0KHNlbGYucmVzZXRfcG9vbF9idG4pCiAgICAgICAg"
    "YWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5zYXZlX3Bvb2xfYnRuKQogICAgICAgIHB3LmFkZExheW91dChhY3Rpb25zKQoKICAgICAg"
    "ICByb290LmFkZFdpZGdldChwb29sX3dyYXApCgogICAgICAgIHJlc3VsdF93cmFwID0gUUZyYW1lKCkKICAgICAgICByZXN1bHRf"
    "d3JhcC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsiKQog"
    "ICAgICAgIHJsID0gUVZCb3hMYXlvdXQocmVzdWx0X3dyYXApCiAgICAgICAgcmwuc2V0Q29udGVudHNNYXJnaW5zKDgsIDgsIDgs"
    "IDgpCiAgICAgICAgcmwuYWRkV2lkZ2V0KFFMYWJlbCgiQ3VycmVudCBSZXN1bHQiKSkKICAgICAgICBzZWxmLmN1cnJlbnRfcmVz"
    "dWx0X2xibCA9IFFMYWJlbCgiTm8gcm9sbCB5ZXQuIikKICAgICAgICBzZWxmLmN1cnJlbnRfcmVzdWx0X2xibC5zZXRXb3JkV3Jh"
    "cChUcnVlKQogICAgICAgIHJsLmFkZFdpZGdldChzZWxmLmN1cnJlbnRfcmVzdWx0X2xibCkKICAgICAgICByb290LmFkZFdpZGdl"
    "dChyZXN1bHRfd3JhcCkKCiAgICAgICAgbWlkID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGhpc3Rvcnlfd3JhcCA9IFFGcmFtZSgp"
    "CiAgICAgICAgaGlzdG9yeV93cmFwLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xp"
    "ZCB7Q19CT1JERVJ9OyIpCiAgICAgICAgaHcgPSBRVkJveExheW91dChoaXN0b3J5X3dyYXApCiAgICAgICAgaHcuc2V0Q29udGVu"
    "dHNNYXJnaW5zKDYsIDYsIDYsIDYpCgogICAgICAgIHNlbGYuaGlzdG9yeV90YWJzID0gUVRhYldpZGdldCgpCiAgICAgICAgc2Vs"
    "Zi5jdXJyZW50X3RhYmxlID0gc2VsZi5fbWFrZV9yb2xsX3RhYmxlKCkKICAgICAgICBzZWxmLmhpc3RvcnlfdGFibGUgPSBzZWxm"
    "Ll9tYWtlX3JvbGxfdGFibGUoKQogICAgICAgIHNlbGYuaGlzdG9yeV90YWJzLmFkZFRhYihzZWxmLmN1cnJlbnRfdGFibGUsICJD"
    "dXJyZW50IFJvbGxzIikKICAgICAgICBzZWxmLmhpc3RvcnlfdGFicy5hZGRUYWIoc2VsZi5oaXN0b3J5X3RhYmxlLCAiUm9sbCBI"
    "aXN0b3J5IikKICAgICAgICBody5hZGRXaWRnZXQoc2VsZi5oaXN0b3J5X3RhYnMsIDEpCgogICAgICAgIGhpc3RvcnlfYWN0aW9u"
    "cyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLmNsZWFyX2hpc3RvcnlfYnRuID0gUVB1c2hCdXR0b24oIkNsZWFyIFJvbGwg"
    "SGlzdG9yeSIpCiAgICAgICAgaGlzdG9yeV9hY3Rpb25zLmFkZFdpZGdldChzZWxmLmNsZWFyX2hpc3RvcnlfYnRuKQogICAgICAg"
    "IGhpc3RvcnlfYWN0aW9ucy5hZGRTdHJldGNoKDEpCiAgICAgICAgaHcuYWRkTGF5b3V0KGhpc3RvcnlfYWN0aW9ucykKCiAgICAg"
    "ICAgc2VsZi5ncmFuZF90b3RhbF9sYmwgPSBRTGFiZWwoIkdyYW5kIFRvdGFsOiAwIikKICAgICAgICBzZWxmLmdyYW5kX3RvdGFs"
    "X2xibC5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDEycHg7IGZvbnQtd2VpZ2h0OiBib2xkOyIp"
    "CiAgICAgICAgaHcuYWRkV2lkZ2V0KHNlbGYuZ3JhbmRfdG90YWxfbGJsKQoKICAgICAgICBzYXZlZF93cmFwID0gUUZyYW1lKCkK"
    "ICAgICAgICBzYXZlZF93cmFwLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7"
    "Q19CT1JERVJ9OyIpCiAgICAgICAgc3cgPSBRVkJveExheW91dChzYXZlZF93cmFwKQogICAgICAgIHN3LnNldENvbnRlbnRzTWFy"
    "Z2lucyg2LCA2LCA2LCA2KQogICAgICAgIHN3LmFkZFdpZGdldChRTGFiZWwoIlNhdmVkIC8gQ29tbW9uIFJvbGxzIikpCgogICAg"
    "ICAgIHN3LmFkZFdpZGdldChRTGFiZWwoIlNhdmVkIikpCiAgICAgICAgc2VsZi5zYXZlZF9saXN0ID0gUUxpc3RXaWRnZXQoKQog"
    "ICAgICAgIHN3LmFkZFdpZGdldChzZWxmLnNhdmVkX2xpc3QsIDEpCiAgICAgICAgc2F2ZWRfYWN0aW9ucyA9IFFIQm94TGF5b3V0"
    "KCkKICAgICAgICBzZWxmLnJ1bl9zYXZlZF9idG4gPSBRUHVzaEJ1dHRvbigiUnVuIikKICAgICAgICBzZWxmLmxvYWRfc2F2ZWRf"
    "YnRuID0gUVB1c2hCdXR0b24oIkxvYWQvRWRpdCIpCiAgICAgICAgc2VsZi5kZWxldGVfc2F2ZWRfYnRuID0gUVB1c2hCdXR0b24o"
    "IkRlbGV0ZSIpCiAgICAgICAgc2F2ZWRfYWN0aW9ucy5hZGRXaWRnZXQoc2VsZi5ydW5fc2F2ZWRfYnRuKQogICAgICAgIHNhdmVk"
    "X2FjdGlvbnMuYWRkV2lkZ2V0KHNlbGYubG9hZF9zYXZlZF9idG4pCiAgICAgICAgc2F2ZWRfYWN0aW9ucy5hZGRXaWRnZXQoc2Vs"
    "Zi5kZWxldGVfc2F2ZWRfYnRuKQogICAgICAgIHN3LmFkZExheW91dChzYXZlZF9hY3Rpb25zKQoKICAgICAgICBzdy5hZGRXaWRn"
    "ZXQoUUxhYmVsKCJBdXRvLURldGVjdGVkIENvbW1vbiIpKQogICAgICAgIHNlbGYuY29tbW9uX2xpc3QgPSBRTGlzdFdpZGdldCgp"
    "CiAgICAgICAgc3cuYWRkV2lkZ2V0KHNlbGYuY29tbW9uX2xpc3QsIDEpCiAgICAgICAgY29tbW9uX2FjdGlvbnMgPSBRSEJveExh"
    "eW91dCgpCiAgICAgICAgc2VsZi5wcm9tb3RlX2NvbW1vbl9idG4gPSBRUHVzaEJ1dHRvbigiUHJvbW90ZSB0byBTYXZlZCIpCiAg"
    "ICAgICAgc2VsZi5kaXNtaXNzX2NvbW1vbl9idG4gPSBRUHVzaEJ1dHRvbigiRGlzbWlzcyIpCiAgICAgICAgY29tbW9uX2FjdGlv"
    "bnMuYWRkV2lkZ2V0KHNlbGYucHJvbW90ZV9jb21tb25fYnRuKQogICAgICAgIGNvbW1vbl9hY3Rpb25zLmFkZFdpZGdldChzZWxm"
    "LmRpc21pc3NfY29tbW9uX2J0bikKICAgICAgICBzdy5hZGRMYXlvdXQoY29tbW9uX2FjdGlvbnMpCgogICAgICAgIHNlbGYuY29t"
    "bW9uX2hpbnQgPSBRTGFiZWwoIkNvbW1vbiBzaWduYXR1cmUgdHJhY2tpbmcgYWN0aXZlLiIpCiAgICAgICAgc2VsZi5jb21tb25f"
    "aGludC5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9udC1zaXplOiA5cHg7IikKICAgICAgICBzdy5hZGRX"
    "aWRnZXQoc2VsZi5jb21tb25faGludCkKCiAgICAgICAgbWlkLmFkZFdpZGdldChoaXN0b3J5X3dyYXAsIDMpCiAgICAgICAgbWlk"
    "LmFkZFdpZGdldChzYXZlZF93cmFwLCAyKQogICAgICAgIHJvb3QuYWRkTGF5b3V0KG1pZCwgMSkKCiAgICAgICAgc2VsZi5yb2xs"
    "X3Bvb2xfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9yb2xsX2N1cnJlbnRfcG9vbCkKICAgICAgICBzZWxmLnJlc2V0X3Bvb2xf"
    "YnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9yZXNldF9wb29sKQogICAgICAgIHNlbGYuc2F2ZV9wb29sX2J0bi5jbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fc2F2ZV9wb29sKQogICAgICAgIHNlbGYuY2xlYXJfaGlzdG9yeV9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYu"
    "X2NsZWFyX2hpc3RvcnkpCgogICAgICAgIHNlbGYuc2F2ZWRfbGlzdC5pdGVtRG91YmxlQ2xpY2tlZC5jb25uZWN0KGxhbWJkYSBp"
    "dGVtOiBzZWxmLl9ydW5fc2F2ZWRfcm9sbChpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKSkpCiAgICAgICAgc2Vs"
    "Zi5jb21tb25fbGlzdC5pdGVtRG91YmxlQ2xpY2tlZC5jb25uZWN0KGxhbWJkYSBpdGVtOiBzZWxmLl9ydW5fc2F2ZWRfcm9sbChp"
    "dGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKSkpCgogICAgICAgIHNlbGYucnVuX3NhdmVkX2J0bi5jbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fcnVuX3NlbGVjdGVkX3NhdmVkKQogICAgICAgIHNlbGYubG9hZF9zYXZlZF9idG4uY2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuX2xvYWRfc2VsZWN0ZWRfc2F2ZWQpCiAgICAgICAgc2VsZi5kZWxldGVfc2F2ZWRfYnRuLmNsaWNrZWQuY29ubmVjdChz"
    "ZWxmLl9kZWxldGVfc2VsZWN0ZWRfc2F2ZWQpCiAgICAgICAgc2VsZi5wcm9tb3RlX2NvbW1vbl9idG4uY2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuX3Byb21vdGVfc2VsZWN0ZWRfY29tbW9uKQogICAgICAgIHNlbGYuZGlzbWlzc19jb21tb25fYnRuLmNsaWNrZWQuY29u"
    "bmVjdChzZWxmLl9kaXNtaXNzX3NlbGVjdGVkX2NvbW1vbikKCiAgICAgICAgc2VsZi5jdXJyZW50X3RhYmxlLnNldENvbnRleHRN"
    "ZW51UG9saWN5KFF0LkNvbnRleHRNZW51UG9saWN5LkN1c3RvbUNvbnRleHRNZW51KQogICAgICAgIHNlbGYuaGlzdG9yeV90YWJs"
    "ZS5zZXRDb250ZXh0TWVudVBvbGljeShRdC5Db250ZXh0TWVudVBvbGljeS5DdXN0b21Db250ZXh0TWVudSkKICAgICAgICBzZWxm"
    "LmN1cnJlbnRfdGFibGUuY3VzdG9tQ29udGV4dE1lbnVSZXF1ZXN0ZWQuY29ubmVjdChsYW1iZGEgcG9zOiBzZWxmLl9zaG93X3Jv"
    "bGxfY29udGV4dF9tZW51KHNlbGYuY3VycmVudF90YWJsZSwgcG9zKSkKICAgICAgICBzZWxmLmhpc3RvcnlfdGFibGUuY3VzdG9t"
    "Q29udGV4dE1lbnVSZXF1ZXN0ZWQuY29ubmVjdChsYW1iZGEgcG9zOiBzZWxmLl9zaG93X3JvbGxfY29udGV4dF9tZW51KHNlbGYu"
    "aGlzdG9yeV90YWJsZSwgcG9zKSkKCiAgICBkZWYgX21ha2Vfcm9sbF90YWJsZShzZWxmKSAtPiBRVGFibGVXaWRnZXQ6CiAgICAg"
    "ICAgdGJsID0gUVRhYmxlV2lkZ2V0KDAsIDYpCiAgICAgICAgdGJsLnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJUaW1lc3Rh"
    "bXAiLCAiTGFiZWwiLCAiRXhwcmVzc2lvbiIsICJSYXciLCAiTW9kaWZpZXIiLCAiVG90YWwiXSkKICAgICAgICB0YmwuaG9yaXpv"
    "bnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICB0"
    "YmwudmVydGljYWxIZWFkZXIoKS5zZXRWaXNpYmxlKEZhbHNlKQogICAgICAgIHRibC5zZXRFZGl0VHJpZ2dlcnMoUUFic3RyYWN0"
    "SXRlbVZpZXcuRWRpdFRyaWdnZXIuTm9FZGl0VHJpZ2dlcnMpCiAgICAgICAgdGJsLnNldFNlbGVjdGlvbkJlaGF2aW9yKFFBYnN0"
    "cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJvd3MpCiAgICAgICAgdGJsLnNldFNvcnRpbmdFbmFibGVkKEZh"
    "bHNlKQogICAgICAgIHJldHVybiB0YmwKCiAgICBkZWYgX3NvcnRlZF9wb29sX2l0ZW1zKHNlbGYpOgogICAgICAgIHJldHVybiBb"
    "KGQsIHNlbGYuY3VycmVudF9wb29sLmdldChkLCAwKSkgZm9yIGQgaW4gc2VsZi5UUkFZX09SREVSIGlmIHNlbGYuY3VycmVudF9w"
    "b29sLmdldChkLCAwKSA+IDBdCgogICAgZGVmIF9wb29sX2V4cHJlc3Npb24oc2VsZiwgcG9vbDogZGljdFtzdHIsIGludF0gfCBO"
    "b25lID0gTm9uZSkgLT4gc3RyOgogICAgICAgIHAgPSBwb29sIGlmIHBvb2wgaXMgbm90IE5vbmUgZWxzZSBzZWxmLmN1cnJlbnRf"
    "cG9vbAogICAgICAgIHBhcnRzID0gW2Yie3F0eX17ZGllfSIgZm9yIGRpZSwgcXR5IGluIFsoZCwgcC5nZXQoZCwgMCkpIGZvciBk"
    "IGluIHNlbGYuVFJBWV9PUkRFUl0gaWYgcXR5ID4gMF0KICAgICAgICByZXR1cm4gIiArICIuam9pbihwYXJ0cykgaWYgcGFydHMg"
    "ZWxzZSAiKGVtcHR5KSIKCiAgICBkZWYgX25vcm1hbGl6ZV9wb29sX3NpZ25hdHVyZShzZWxmLCBwb29sOiBkaWN0W3N0ciwgaW50"
    "XSwgbW9kaWZpZXI6IGludCwgcnVsZV9pZDogc3RyID0gIiIpIC0+IHN0cjoKICAgICAgICBwYXJ0cyA9IFtmIntwb29sLmdldChk"
    "LCAwKX17ZH0iIGZvciBkIGluIHNlbGYuVFJBWV9PUkRFUiBpZiBwb29sLmdldChkLCAwKSA+IDBdCiAgICAgICAgYmFzZSA9ICIr"
    "Ii5qb2luKHBhcnRzKSBpZiBwYXJ0cyBlbHNlICIwIgogICAgICAgIHNpZyA9IGYie2Jhc2V9e21vZGlmaWVyOitkfSIKICAgICAg"
    "ICByZXR1cm4gZiJ7c2lnfV97cnVsZV9pZH0iIGlmIHJ1bGVfaWQgZWxzZSBzaWcKCiAgICBkZWYgX2RpY2VfbGFiZWwoc2VsZiwg"
    "ZGllX3R5cGU6IHN0cikgLT4gc3RyOgogICAgICAgIHJldHVybiAiZCUiIGlmIGRpZV90eXBlID09ICJkJSIgZWxzZSBkaWVfdHlw"
    "ZQoKICAgIGRlZiBfcm9sbF9zaW5nbGVfdmFsdWUoc2VsZiwgZGllX3R5cGU6IHN0cik6CiAgICAgICAgaWYgZGllX3R5cGUgPT0g"
    "ImQlIjoKICAgICAgICAgICAgdGVucyA9IHJhbmRvbS5yYW5kaW50KDAsIDkpICogMTAKICAgICAgICAgICAgcmV0dXJuIHRlbnMs"
    "ICgiMDAiIGlmIHRlbnMgPT0gMCBlbHNlIHN0cih0ZW5zKSkKICAgICAgICBzaWRlcyA9IGludChkaWVfdHlwZS5yZXBsYWNlKCJk"
    "IiwgIiIpKQogICAgICAgIHZhbCA9IHJhbmRvbS5yYW5kaW50KDEsIHNpZGVzKQogICAgICAgIHJldHVybiB2YWwsIHN0cih2YWwp"
    "CgogICAgZGVmIF9yb2xsX3Bvb2xfZGF0YShzZWxmLCBwb29sOiBkaWN0W3N0ciwgaW50XSwgbW9kaWZpZXI6IGludCwgbGFiZWw6"
    "IHN0ciwgcnVsZV9pZDogc3RyID0gIiIpIC0+IGRpY3Q6CiAgICAgICAgZ3JvdXBlZF9udW1lcmljOiBkaWN0W3N0ciwgbGlzdFtp"
    "bnRdXSA9IHt9CiAgICAgICAgZ3JvdXBlZF9kaXNwbGF5OiBkaWN0W3N0ciwgbGlzdFtzdHJdXSA9IHt9CiAgICAgICAgc3VidG90"
    "YWwgPSAwCiAgICAgICAgdXNlZF9wb29sID0gZGljdChwb29sKQoKICAgICAgICBpZiBydWxlX2lkIGFuZCBydWxlX2lkIGluIHNl"
    "bGYucnVsZV9kZWZpbml0aW9ucyBhbmQgKG5vdCBwb29sIG9yIGxlbihbayBmb3IgaywgdiBpbiBwb29sLml0ZW1zKCkgaWYgdiA+"
    "IDBdKSA9PSAxKToKICAgICAgICAgICAgcnVsZSA9IHNlbGYucnVsZV9kZWZpbml0aW9ucy5nZXQocnVsZV9pZCwge30pCiAgICAg"
    "ICAgICAgIHNpZGVzID0gaW50KHJ1bGUuZ2V0KCJkaWNlX3NpZGVzIiwgNikpCiAgICAgICAgICAgIGNvdW50ID0gaW50KHJ1bGUu"
    "Z2V0KCJkaWNlX2NvdW50IiwgMSkpCiAgICAgICAgICAgIGRpZSA9IGYiZHtzaWRlc30iCiAgICAgICAgICAgIHVzZWRfcG9vbCA9"
    "IHtkaWU6IGNvdW50fQogICAgICAgICAgICByYXcgPSBbcmFuZG9tLnJhbmRpbnQoMSwgc2lkZXMpIGZvciBfIGluIHJhbmdlKGNv"
    "dW50KV0KICAgICAgICAgICAgZHJvcF9sb3cgPSBpbnQocnVsZS5nZXQoImRyb3BfbG93ZXN0X2NvdW50IiwgMCkgb3IgMCkKICAg"
    "ICAgICAgICAgZHJvcF9oaWdoID0gaW50KHJ1bGUuZ2V0KCJkcm9wX2hpZ2hlc3RfY291bnQiLCAwKSBvciAwKQogICAgICAgICAg"
    "ICBrZXB0ID0gbGlzdChyYXcpCiAgICAgICAgICAgIGlmIGRyb3BfbG93ID4gMDoKICAgICAgICAgICAgICAgIGtlcHQgPSBzb3J0"
    "ZWQoa2VwdClbZHJvcF9sb3c6XQogICAgICAgICAgICBpZiBkcm9wX2hpZ2ggPiAwOgogICAgICAgICAgICAgICAga2VwdCA9IHNv"
    "cnRlZChrZXB0KVs6LWRyb3BfaGlnaF0gaWYgZHJvcF9oaWdoIDwgbGVuKGtlcHQpIGVsc2UgW10KICAgICAgICAgICAgZ3JvdXBl"
    "ZF9udW1lcmljW2RpZV0gPSByYXcKICAgICAgICAgICAgZ3JvdXBlZF9kaXNwbGF5W2RpZV0gPSBbc3RyKHYpIGZvciB2IGluIHJh"
    "d10KICAgICAgICAgICAgc3VidG90YWwgPSBzdW0oa2VwdCkKICAgICAgICBlbHNlOgogICAgICAgICAgICBmb3IgZGllIGluIHNl"
    "bGYuVFJBWV9PUkRFUjoKICAgICAgICAgICAgICAgIHF0eSA9IGludChwb29sLmdldChkaWUsIDApIG9yIDApCiAgICAgICAgICAg"
    "ICAgICBpZiBxdHkgPD0gMDoKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAgICAgZ3JvdXBlZF9udW1l"
    "cmljW2RpZV0gPSBbXQogICAgICAgICAgICAgICAgZ3JvdXBlZF9kaXNwbGF5W2RpZV0gPSBbXQogICAgICAgICAgICAgICAgZm9y"
    "IF8gaW4gcmFuZ2UocXR5KToKICAgICAgICAgICAgICAgICAgICBudW0sIGRpc3AgPSBzZWxmLl9yb2xsX3NpbmdsZV92YWx1ZShk"
    "aWUpCiAgICAgICAgICAgICAgICAgICAgZ3JvdXBlZF9udW1lcmljW2RpZV0uYXBwZW5kKG51bSkKICAgICAgICAgICAgICAgICAg"
    "ICBncm91cGVkX2Rpc3BsYXlbZGllXS5hcHBlbmQoZGlzcCkKICAgICAgICAgICAgICAgICAgICBzdWJ0b3RhbCArPSBpbnQobnVt"
    "KQoKICAgICAgICB0b3RhbCA9IHN1YnRvdGFsICsgaW50KG1vZGlmaWVyKQogICAgICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3Ry"
    "ZnRpbWUoIiVIOiVNOiVTIikKICAgICAgICBleHByID0gc2VsZi5fcG9vbF9leHByZXNzaW9uKHVzZWRfcG9vbCkKICAgICAgICBp"
    "ZiBydWxlX2lkOgogICAgICAgICAgICBydWxlX25hbWUgPSBzZWxmLnJ1bGVfZGVmaW5pdGlvbnMuZ2V0KHJ1bGVfaWQsIHt9KS5n"
    "ZXQoIm5hbWUiLCBydWxlX2lkKQogICAgICAgICAgICBleHByID0gZiJ7ZXhwcn0gKHtydWxlX25hbWV9KSIKCiAgICAgICAgZXZl"
    "bnQgPSB7CiAgICAgICAgICAgICJpZCI6IGYicm9sbF97dXVpZC51dWlkNCgpLmhleFs6MTJdfSIsCiAgICAgICAgICAgICJ0aW1l"
    "c3RhbXAiOiB0cywKICAgICAgICAgICAgImxhYmVsIjogbGFiZWwsCiAgICAgICAgICAgICJwb29sIjogdXNlZF9wb29sLAogICAg"
    "ICAgICAgICAiZ3JvdXBlZF9yYXciOiBncm91cGVkX251bWVyaWMsCiAgICAgICAgICAgICJncm91cGVkX3Jhd19kaXNwbGF5Ijog"
    "Z3JvdXBlZF9kaXNwbGF5LAogICAgICAgICAgICAic3VidG90YWwiOiBzdWJ0b3RhbCwKICAgICAgICAgICAgIm1vZGlmaWVyIjog"
    "aW50KG1vZGlmaWVyKSwKICAgICAgICAgICAgImZpbmFsX3RvdGFsIjogaW50KHRvdGFsKSwKICAgICAgICAgICAgImV4cHJlc3Np"
    "b24iOiBleHByLAogICAgICAgICAgICAic291cmNlIjogImRpY2Vfcm9sbGVyIiwKICAgICAgICAgICAgInJ1bGVfaWQiOiBydWxl"
    "X2lkIG9yIE5vbmUsCiAgICAgICAgfQogICAgICAgIHJldHVybiBldmVudAoKICAgIGRlZiBfYWRkX2RpZV90b19wb29sKHNlbGYs"
    "IGRpZV90eXBlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5jdXJyZW50X3Bvb2xbZGllX3R5cGVdID0gaW50KHNlbGYuY3Vy"
    "cmVudF9wb29sLmdldChkaWVfdHlwZSwgMCkpICsgMQogICAgICAgIHNlbGYuX3JlZnJlc2hfcG9vbF9lZGl0b3IoKQogICAgICAg"
    "IHNlbGYuY3VycmVudF9yZXN1bHRfbGJsLnNldFRleHQoZiJDdXJyZW50IFBvb2w6IHtzZWxmLl9wb29sX2V4cHJlc3Npb24oKX0i"
    "KQoKICAgIGRlZiBfYWRqdXN0X3Bvb2xfZGllKHNlbGYsIGRpZV90eXBlOiBzdHIsIGRlbHRhOiBpbnQpIC0+IE5vbmU6CiAgICAg"
    "ICAgbmV3X3ZhbCA9IGludChzZWxmLmN1cnJlbnRfcG9vbC5nZXQoZGllX3R5cGUsIDApKSArIGludChkZWx0YSkKICAgICAgICBp"
    "ZiBuZXdfdmFsIDw9IDA6CiAgICAgICAgICAgIHNlbGYuY3VycmVudF9wb29sLnBvcChkaWVfdHlwZSwgTm9uZSkKICAgICAgICBl"
    "bHNlOgogICAgICAgICAgICBzZWxmLmN1cnJlbnRfcG9vbFtkaWVfdHlwZV0gPSBuZXdfdmFsCiAgICAgICAgc2VsZi5fcmVmcmVz"
    "aF9wb29sX2VkaXRvcigpCgogICAgZGVmIF9yZWZyZXNoX3Bvb2xfZWRpdG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgd2hpbGUg"
    "c2VsZi5wb29sX2VudHJpZXNfbGF5b3V0LmNvdW50KCk6CiAgICAgICAgICAgIGl0ZW0gPSBzZWxmLnBvb2xfZW50cmllc19sYXlv"
    "dXQudGFrZUF0KDApCiAgICAgICAgICAgIHcgPSBpdGVtLndpZGdldCgpCiAgICAgICAgICAgIGlmIHcgaXMgbm90IE5vbmU6CiAg"
    "ICAgICAgICAgICAgICB3LmRlbGV0ZUxhdGVyKCkKCiAgICAgICAgZm9yIGRpZSwgcXR5IGluIHNlbGYuX3NvcnRlZF9wb29sX2l0"
    "ZW1zKCk6CiAgICAgICAgICAgIGJveCA9IFFGcmFtZSgpCiAgICAgICAgICAgIGJveC5zZXRTdHlsZVNoZWV0KGYiYmFja2dyb3Vu"
    "ZDoge0NfQkczfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogNnB4OyIpCiAgICAgICAgICAg"
    "IGxheSA9IFFIQm94TGF5b3V0KGJveCkKICAgICAgICAgICAgbGF5LnNldENvbnRlbnRzTWFyZ2lucyg2LCA0LCA2LCA0KQogICAg"
    "ICAgICAgICBsYXkuc2V0U3BhY2luZyg0KQogICAgICAgICAgICBsYmwgPSBRTGFiZWwoZiJ7ZGllfSB4e3F0eX0iKQogICAgICAg"
    "ICAgICBtaW51c19idG4gPSBRUHVzaEJ1dHRvbigi4oiSIikKICAgICAgICAgICAgcGx1c19idG4gPSBRUHVzaEJ1dHRvbigiKyIp"
    "CiAgICAgICAgICAgIG1pbnVzX2J0bi5zZXRGaXhlZFdpZHRoKDI0KQogICAgICAgICAgICBwbHVzX2J0bi5zZXRGaXhlZFdpZHRo"
    "KDI0KQogICAgICAgICAgICBtaW51c19idG4uY2xpY2tlZC5jb25uZWN0KGxhbWJkYSBfPUZhbHNlLCBkPWRpZTogc2VsZi5fYWRq"
    "dXN0X3Bvb2xfZGllKGQsIC0xKSkKICAgICAgICAgICAgcGx1c19idG4uY2xpY2tlZC5jb25uZWN0KGxhbWJkYSBfPUZhbHNlLCBk"
    "PWRpZTogc2VsZi5fYWRqdXN0X3Bvb2xfZGllKGQsICsxKSkKICAgICAgICAgICAgbGF5LmFkZFdpZGdldChsYmwpCiAgICAgICAg"
    "ICAgIGxheS5hZGRXaWRnZXQobWludXNfYnRuKQogICAgICAgICAgICBsYXkuYWRkV2lkZ2V0KHBsdXNfYnRuKQogICAgICAgICAg"
    "ICBzZWxmLnBvb2xfZW50cmllc19sYXlvdXQuYWRkV2lkZ2V0KGJveCkKCiAgICAgICAgc2VsZi5wb29sX2VudHJpZXNfbGF5b3V0"
    "LmFkZFN0cmV0Y2goMSkKICAgICAgICBzZWxmLnBvb2xfZXhwcl9sYmwuc2V0VGV4dChmIlBvb2w6IHtzZWxmLl9wb29sX2V4cHJl"
    "c3Npb24oKX0iKQoKICAgIGRlZiBfcXVpY2tfcm9sbF9zaW5nbGVfZGllKHNlbGYsIGRpZV90eXBlOiBzdHIpIC0+IE5vbmU6CiAg"
    "ICAgICAgZXZlbnQgPSBzZWxmLl9yb2xsX3Bvb2xfZGF0YSh7ZGllX3R5cGU6IDF9LCBpbnQoc2VsZi5tb2Rfc3Bpbi52YWx1ZSgp"
    "KSwgc2VsZi5sYWJlbF9lZGl0LnRleHQoKS5zdHJpcCgpLCBzZWxmLnJ1bGVfY29tYm8uY3VycmVudERhdGEoKSBvciAiIikKICAg"
    "ICAgICBzZWxmLl9yZWNvcmRfcm9sbF9ldmVudChldmVudCkKCiAgICBkZWYgX3JvbGxfY3VycmVudF9wb29sKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgcG9vbCA9IGRpY3Qoc2VsZi5jdXJyZW50X3Bvb2wpCiAgICAgICAgcnVsZV9pZCA9IHNlbGYucnVsZV9jb21i"
    "by5jdXJyZW50RGF0YSgpIG9yICIiCiAgICAgICAgaWYgbm90IHBvb2wgYW5kIG5vdCBydWxlX2lkOgogICAgICAgICAgICBRTWVz"
    "c2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiRGljZSBSb2xsZXIiLCAiQ3VycmVudCBQb29sIGlzIGVtcHR5LiIpCiAgICAgICAg"
    "ICAgIHJldHVybgogICAgICAgIGV2ZW50ID0gc2VsZi5fcm9sbF9wb29sX2RhdGEocG9vbCwgaW50KHNlbGYubW9kX3NwaW4udmFs"
    "dWUoKSksIHNlbGYubGFiZWxfZWRpdC50ZXh0KCkuc3RyaXAoKSwgcnVsZV9pZCkKICAgICAgICBzZWxmLl9yZWNvcmRfcm9sbF9l"
    "dmVudChldmVudCkKCiAgICBkZWYgX3JlY29yZF9yb2xsX2V2ZW50KHNlbGYsIGV2ZW50OiBkaWN0KSAtPiBOb25lOgogICAgICAg"
    "IHNlbGYucm9sbF9ldmVudHMuYXBwZW5kKGV2ZW50KQogICAgICAgIHNlbGYuZXZlbnRfYnlfaWRbZXZlbnRbImlkIl1dID0gZXZl"
    "bnQKICAgICAgICBzZWxmLmN1cnJlbnRfcm9sbF9pZHMgPSBbZXZlbnRbImlkIl1dCgogICAgICAgIHNlbGYuX3JlcGxhY2VfY3Vy"
    "cmVudF9yb3dzKFtldmVudF0pCiAgICAgICAgc2VsZi5fYXBwZW5kX2hpc3Rvcnlfcm93KGV2ZW50KQogICAgICAgIHNlbGYuX3Vw"
    "ZGF0ZV9ncmFuZF90b3RhbCgpCiAgICAgICAgc2VsZi5fdXBkYXRlX3Jlc3VsdF9kaXNwbGF5KGV2ZW50KQogICAgICAgIHNlbGYu"
    "X3RyYWNrX2NvbW1vbl9zaWduYXR1cmUoZXZlbnQpCiAgICAgICAgc2VsZi5fcGxheV9yb2xsX3NvdW5kKCkKCiAgICBkZWYgX3Jl"
    "cGxhY2VfY3VycmVudF9yb3dzKHNlbGYsIGV2ZW50czogbGlzdFtkaWN0XSkgLT4gTm9uZToKICAgICAgICBzZWxmLmN1cnJlbnRf"
    "dGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgZXZlbnQgaW4gZXZlbnRzOgogICAgICAgICAgICBzZWxmLl9hcHBlbmRf"
    "dGFibGVfcm93KHNlbGYuY3VycmVudF90YWJsZSwgZXZlbnQpCgogICAgZGVmIF9hcHBlbmRfaGlzdG9yeV9yb3coc2VsZiwgZXZl"
    "bnQ6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fYXBwZW5kX3RhYmxlX3JvdyhzZWxmLmhpc3RvcnlfdGFibGUsIGV2ZW50"
    "KQogICAgICAgIHNlbGYuaGlzdG9yeV90YWJsZS5zY3JvbGxUb0JvdHRvbSgpCgogICAgZGVmIF9mb3JtYXRfcmF3KHNlbGYsIGV2"
    "ZW50OiBkaWN0KSAtPiBzdHI6CiAgICAgICAgZ3JvdXBlZCA9IGV2ZW50LmdldCgiZ3JvdXBlZF9yYXdfZGlzcGxheSIsIHt9KSBv"
    "ciB7fQogICAgICAgIGJpdHMgPSBbXQogICAgICAgIGZvciBkaWUgaW4gc2VsZi5UUkFZX09SREVSOgogICAgICAgICAgICB2YWxz"
    "ID0gZ3JvdXBlZC5nZXQoZGllKQogICAgICAgICAgICBpZiB2YWxzOgogICAgICAgICAgICAgICAgYml0cy5hcHBlbmQoZiJ7ZGll"
    "fTogeycsJy5qb2luKHN0cih2KSBmb3IgdiBpbiB2YWxzKX0iKQogICAgICAgIHJldHVybiAiIHwgIi5qb2luKGJpdHMpCgogICAg"
    "ZGVmIF9hcHBlbmRfdGFibGVfcm93KHNlbGYsIHRhYmxlOiBRVGFibGVXaWRnZXQsIGV2ZW50OiBkaWN0KSAtPiBOb25lOgogICAg"
    "ICAgIHJvdyA9IHRhYmxlLnJvd0NvdW50KCkKICAgICAgICB0YWJsZS5pbnNlcnRSb3cocm93KQoKICAgICAgICB0c19pdGVtID0g"
    "UVRhYmxlV2lkZ2V0SXRlbShldmVudFsidGltZXN0YW1wIl0pCiAgICAgICAgdHNfaXRlbS5zZXREYXRhKFF0Lkl0ZW1EYXRhUm9s"
    "ZS5Vc2VyUm9sZSwgZXZlbnRbImlkIl0pCiAgICAgICAgdGFibGUuc2V0SXRlbShyb3csIDAsIHRzX2l0ZW0pCiAgICAgICAgdGFi"
    "bGUuc2V0SXRlbShyb3csIDEsIFFUYWJsZVdpZGdldEl0ZW0oZXZlbnQuZ2V0KCJsYWJlbCIsICIiKSkpCiAgICAgICAgdGFibGUu"
    "c2V0SXRlbShyb3csIDIsIFFUYWJsZVdpZGdldEl0ZW0oZXZlbnQuZ2V0KCJleHByZXNzaW9uIiwgIiIpKSkKICAgICAgICB0YWJs"
    "ZS5zZXRJdGVtKHJvdywgMywgUVRhYmxlV2lkZ2V0SXRlbShzZWxmLl9mb3JtYXRfcmF3KGV2ZW50KSkpCgogICAgICAgIG1vZF9z"
    "cGluID0gUVNwaW5Cb3goKQogICAgICAgIG1vZF9zcGluLnNldFJhbmdlKC05OTksIDk5OSkKICAgICAgICBtb2Rfc3Bpbi5zZXRW"
    "YWx1ZShpbnQoZXZlbnQuZ2V0KCJtb2RpZmllciIsIDApKSkKICAgICAgICBtb2Rfc3Bpbi52YWx1ZUNoYW5nZWQuY29ubmVjdChs"
    "YW1iZGEgdmFsLCBlaWQ9ZXZlbnRbImlkIl06IHNlbGYuX29uX21vZGlmaWVyX2NoYW5nZWQoZWlkLCB2YWwpKQogICAgICAgIHRh"
    "YmxlLnNldENlbGxXaWRnZXQocm93LCA0LCBtb2Rfc3BpbikKCiAgICAgICAgdGFibGUuc2V0SXRlbShyb3csIDUsIFFUYWJsZVdp"
    "ZGdldEl0ZW0oc3RyKGV2ZW50LmdldCgiZmluYWxfdG90YWwiLCAwKSkpKQoKICAgIGRlZiBfc3luY19yb3dfYnlfZXZlbnRfaWQo"
    "c2VsZiwgdGFibGU6IFFUYWJsZVdpZGdldCwgZXZlbnRfaWQ6IHN0ciwgZXZlbnQ6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgZm9y"
    "IHJvdyBpbiByYW5nZSh0YWJsZS5yb3dDb3VudCgpKToKICAgICAgICAgICAgaXQgPSB0YWJsZS5pdGVtKHJvdywgMCkKICAgICAg"
    "ICAgICAgaWYgaXQgYW5kIGl0LmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKSA9PSBldmVudF9pZDoKICAgICAgICAgICAg"
    "ICAgIHRhYmxlLnNldEl0ZW0ocm93LCA1LCBRVGFibGVXaWRnZXRJdGVtKHN0cihldmVudC5nZXQoImZpbmFsX3RvdGFsIiwgMCkp"
    "KSkKICAgICAgICAgICAgICAgIHRhYmxlLnNldEl0ZW0ocm93LCAzLCBRVGFibGVXaWRnZXRJdGVtKHNlbGYuX2Zvcm1hdF9yYXco"
    "ZXZlbnQpKSkKICAgICAgICAgICAgICAgIGJyZWFrCgogICAgZGVmIF9vbl9tb2RpZmllcl9jaGFuZ2VkKHNlbGYsIGV2ZW50X2lk"
    "OiBzdHIsIHZhbHVlOiBpbnQpIC0+IE5vbmU6CiAgICAgICAgZXZ0ID0gc2VsZi5ldmVudF9ieV9pZC5nZXQoZXZlbnRfaWQpCiAg"
    "ICAgICAgaWYgbm90IGV2dDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZXZ0WyJtb2RpZmllciJdID0gaW50KHZhbHVlKQog"
    "ICAgICAgIGV2dFsiZmluYWxfdG90YWwiXSA9IGludChldnQuZ2V0KCJzdWJ0b3RhbCIsIDApKSArIGludCh2YWx1ZSkKICAgICAg"
    "ICBzZWxmLl9zeW5jX3Jvd19ieV9ldmVudF9pZChzZWxmLmhpc3RvcnlfdGFibGUsIGV2ZW50X2lkLCBldnQpCiAgICAgICAgc2Vs"
    "Zi5fc3luY19yb3dfYnlfZXZlbnRfaWQoc2VsZi5jdXJyZW50X3RhYmxlLCBldmVudF9pZCwgZXZ0KQogICAgICAgIHNlbGYuX3Vw"
    "ZGF0ZV9ncmFuZF90b3RhbCgpCiAgICAgICAgaWYgc2VsZi5jdXJyZW50X3JvbGxfaWRzIGFuZCBzZWxmLmN1cnJlbnRfcm9sbF9p"
    "ZHNbMF0gPT0gZXZlbnRfaWQ6CiAgICAgICAgICAgIHNlbGYuX3VwZGF0ZV9yZXN1bHRfZGlzcGxheShldnQpCgogICAgZGVmIF91"
    "cGRhdGVfZ3JhbmRfdG90YWwoc2VsZikgLT4gTm9uZToKICAgICAgICB0b3RhbCA9IHN1bShpbnQoZXZ0LmdldCgiZmluYWxfdG90"
    "YWwiLCAwKSkgZm9yIGV2dCBpbiBzZWxmLnJvbGxfZXZlbnRzKQogICAgICAgIHNlbGYuZ3JhbmRfdG90YWxfbGJsLnNldFRleHQo"
    "ZiJHcmFuZCBUb3RhbDoge3RvdGFsfSIpCgogICAgZGVmIF91cGRhdGVfcmVzdWx0X2Rpc3BsYXkoc2VsZiwgZXZlbnQ6IGRpY3Qp"
    "IC0+IE5vbmU6CiAgICAgICAgZ3JvdXBlZCA9IGV2ZW50LmdldCgiZ3JvdXBlZF9yYXdfZGlzcGxheSIsIHt9KSBvciB7fQogICAg"
    "ICAgIGxpbmVzID0gW10KICAgICAgICBmb3IgZGllIGluIHNlbGYuVFJBWV9PUkRFUjoKICAgICAgICAgICAgdmFscyA9IGdyb3Vw"
    "ZWQuZ2V0KGRpZSkKICAgICAgICAgICAgaWYgdmFsczoKICAgICAgICAgICAgICAgIGxpbmVzLmFwcGVuZChmIntkaWV9IHh7bGVu"
    "KHZhbHMpfSDihpIgW3snLCcuam9pbihzdHIodikgZm9yIHYgaW4gdmFscyl9XSIpCiAgICAgICAgcnVsZV9pZCA9IGV2ZW50Lmdl"
    "dCgicnVsZV9pZCIpCiAgICAgICAgaWYgcnVsZV9pZDoKICAgICAgICAgICAgcnVsZV9uYW1lID0gc2VsZi5ydWxlX2RlZmluaXRp"
    "b25zLmdldChydWxlX2lkLCB7fSkuZ2V0KCJuYW1lIiwgcnVsZV9pZCkKICAgICAgICAgICAgbGluZXMuYXBwZW5kKGYiUnVsZTog"
    "e3J1bGVfbmFtZX0iKQogICAgICAgIGxpbmVzLmFwcGVuZChmIk1vZGlmaWVyOiB7aW50KGV2ZW50LmdldCgnbW9kaWZpZXInLCAw"
    "KSk6K2R9IikKICAgICAgICBsaW5lcy5hcHBlbmQoZiJUb3RhbDoge2V2ZW50LmdldCgnZmluYWxfdG90YWwnLCAwKX0iKQogICAg"
    "ICAgIHNlbGYuY3VycmVudF9yZXN1bHRfbGJsLnNldFRleHQoIlxuIi5qb2luKGxpbmVzKSkKCgogICAgZGVmIF9zYXZlX3Bvb2wo"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5jdXJyZW50X3Bvb2w6CiAgICAgICAgICAgIFFNZXNzYWdlQm94Lmlu"
    "Zm9ybWF0aW9uKHNlbGYsICJEaWNlIFJvbGxlciIsICJCdWlsZCBhIEN1cnJlbnQgUG9vbCBiZWZvcmUgc2F2aW5nLiIpCiAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgIGRlZmF1bHRfbmFtZSA9IHNlbGYubGFiZWxfZWRpdC50ZXh0KCkuc3RyaXAoKSBvciBzZWxm"
    "Ll9wb29sX2V4cHJlc3Npb24oKQogICAgICAgIG5hbWUsIG9rID0gUUlucHV0RGlhbG9nLmdldFRleHQoc2VsZiwgIlNhdmUgUG9v"
    "bCIsICJTYXZlZCByb2xsIG5hbWU6IiwgdGV4dD1kZWZhdWx0X25hbWUpCiAgICAgICAgaWYgbm90IG9rOgogICAgICAgICAgICBy"
    "ZXR1cm4KICAgICAgICBwYXlsb2FkID0gewogICAgICAgICAgICAiaWQiOiBmInNhdmVkX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19"
    "IiwKICAgICAgICAgICAgIm5hbWUiOiBuYW1lLnN0cmlwKCkgb3IgZGVmYXVsdF9uYW1lLAogICAgICAgICAgICAicG9vbCI6IGRp"
    "Y3Qoc2VsZi5jdXJyZW50X3Bvb2wpLAogICAgICAgICAgICAibW9kaWZpZXIiOiBpbnQoc2VsZi5tb2Rfc3Bpbi52YWx1ZSgpKSwK"
    "ICAgICAgICAgICAgInJ1bGVfaWQiOiBzZWxmLnJ1bGVfY29tYm8uY3VycmVudERhdGEoKSBvciBOb25lLAogICAgICAgICAgICAi"
    "bm90ZXMiOiAiIiwKICAgICAgICAgICAgImNhdGVnb3J5IjogInNhdmVkIiwKICAgICAgICB9CiAgICAgICAgc2VsZi5zYXZlZF9y"
    "b2xscy5hcHBlbmQocGF5bG9hZCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBkZWYgX3JlZnJlc2hf"
    "c2F2ZWRfbGlzdHMoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLnNhdmVkX2xpc3QuY2xlYXIoKQogICAgICAgIGZvciBpdGVt"
    "IGluIHNlbGYuc2F2ZWRfcm9sbHM6CiAgICAgICAgICAgIGV4cHIgPSBzZWxmLl9wb29sX2V4cHJlc3Npb24oaXRlbS5nZXQoInBv"
    "b2wiLCB7fSkpCiAgICAgICAgICAgIHR4dCA9IGYie2l0ZW0uZ2V0KCduYW1lJyl9IOKAlCB7ZXhwcn0ge2ludChpdGVtLmdldCgn"
    "bW9kaWZpZXInLCAwKSk6K2R9IgogICAgICAgICAgICBsdyA9IFFMaXN0V2lkZ2V0SXRlbSh0eHQpCiAgICAgICAgICAgIGx3LnNl"
    "dERhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCBpdGVtKQogICAgICAgICAgICBzZWxmLnNhdmVkX2xpc3QuYWRkSXRlbShs"
    "dykKCiAgICAgICAgc2VsZi5jb21tb25fbGlzdC5jbGVhcigpCiAgICAgICAgcmFua2VkID0gc29ydGVkKHNlbGYuY29tbW9uX3Jv"
    "bGxzLnZhbHVlcygpLCBrZXk9bGFtYmRhIHg6IHguZ2V0KCJjb3VudCIsIDApLCByZXZlcnNlPVRydWUpCiAgICAgICAgZm9yIGl0"
    "ZW0gaW4gcmFua2VkOgogICAgICAgICAgICBpZiBpbnQoaXRlbS5nZXQoImNvdW50IiwgMCkpIDwgMjoKICAgICAgICAgICAgICAg"
    "IGNvbnRpbnVlCiAgICAgICAgICAgIGV4cHIgPSBzZWxmLl9wb29sX2V4cHJlc3Npb24oaXRlbS5nZXQoInBvb2wiLCB7fSkpCiAg"
    "ICAgICAgICAgIHR4dCA9IGYie2V4cHJ9IHtpbnQoaXRlbS5nZXQoJ21vZGlmaWVyJywgMCkpOitkfSAoeHtpdGVtLmdldCgnY291"
    "bnQnLCAwKX0pIgogICAgICAgICAgICBsdyA9IFFMaXN0V2lkZ2V0SXRlbSh0eHQpCiAgICAgICAgICAgIGx3LnNldERhdGEoUXQu"
    "SXRlbURhdGFSb2xlLlVzZXJSb2xlLCBpdGVtKQogICAgICAgICAgICBzZWxmLmNvbW1vbl9saXN0LmFkZEl0ZW0obHcpCgogICAg"
    "ZGVmIF90cmFja19jb21tb25fc2lnbmF0dXJlKHNlbGYsIGV2ZW50OiBkaWN0KSAtPiBOb25lOgogICAgICAgIHNpZyA9IHNlbGYu"
    "X25vcm1hbGl6ZV9wb29sX3NpZ25hdHVyZShldmVudC5nZXQoInBvb2wiLCB7fSksIGludChldmVudC5nZXQoIm1vZGlmaWVyIiwg"
    "MCkpLCBzdHIoZXZlbnQuZ2V0KCJydWxlX2lkIikgb3IgIiIpKQogICAgICAgIGlmIHNpZyBub3QgaW4gc2VsZi5jb21tb25fcm9s"
    "bHM6CiAgICAgICAgICAgIHNlbGYuY29tbW9uX3JvbGxzW3NpZ10gPSB7CiAgICAgICAgICAgICAgICAic2lnbmF0dXJlIjogc2ln"
    "LAogICAgICAgICAgICAgICAgImNvdW50IjogMCwKICAgICAgICAgICAgICAgICJuYW1lIjogZXZlbnQuZ2V0KCJsYWJlbCIsICIi"
    "KSBvciBzaWcsCiAgICAgICAgICAgICAgICAicG9vbCI6IGRpY3QoZXZlbnQuZ2V0KCJwb29sIiwge30pKSwKICAgICAgICAgICAg"
    "ICAgICJtb2RpZmllciI6IGludChldmVudC5nZXQoIm1vZGlmaWVyIiwgMCkpLAogICAgICAgICAgICAgICAgInJ1bGVfaWQiOiBl"
    "dmVudC5nZXQoInJ1bGVfaWQiKSwKICAgICAgICAgICAgICAgICJub3RlcyI6ICIiLAogICAgICAgICAgICAgICAgImNhdGVnb3J5"
    "IjogImNvbW1vbiIsCiAgICAgICAgICAgIH0KICAgICAgICBzZWxmLmNvbW1vbl9yb2xsc1tzaWddWyJjb3VudCJdID0gaW50KHNl"
    "bGYuY29tbW9uX3JvbGxzW3NpZ10uZ2V0KCJjb3VudCIsIDApKSArIDEKICAgICAgICBpZiBzZWxmLmNvbW1vbl9yb2xsc1tzaWdd"
    "WyJjb3VudCJdID49IDM6CiAgICAgICAgICAgIHNlbGYuY29tbW9uX2hpbnQuc2V0VGV4dChmIlN1Z2dlc3Rpb246IHByb21vdGUg"
    "e3NlbGYuX3Bvb2xfZXhwcmVzc2lvbihldmVudC5nZXQoJ3Bvb2wnLCB7fSkpfSB0byBTYXZlZC4iKQogICAgICAgIHNlbGYuX3Jl"
    "ZnJlc2hfc2F2ZWRfbGlzdHMoKQoKICAgIGRlZiBfcnVuX3NhdmVkX3JvbGwoc2VsZiwgcGF5bG9hZDogZGljdCB8IE5vbmUpOgog"
    "ICAgICAgIGlmIG5vdCBwYXlsb2FkOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBldmVudCA9IHNlbGYuX3JvbGxfcG9vbF9k"
    "YXRhKAogICAgICAgICAgICBkaWN0KHBheWxvYWQuZ2V0KCJwb29sIiwge30pKSwKICAgICAgICAgICAgaW50KHBheWxvYWQuZ2V0"
    "KCJtb2RpZmllciIsIDApKSwKICAgICAgICAgICAgc3RyKHBheWxvYWQuZ2V0KCJuYW1lIiwgIiIpKS5zdHJpcCgpLAogICAgICAg"
    "ICAgICBzdHIocGF5bG9hZC5nZXQoInJ1bGVfaWQiKSBvciAiIiksCiAgICAgICAgKQogICAgICAgIHNlbGYuX3JlY29yZF9yb2xs"
    "X2V2ZW50KGV2ZW50KQoKICAgIGRlZiBfbG9hZF9wYXlsb2FkX2ludG9fcG9vbChzZWxmLCBwYXlsb2FkOiBkaWN0IHwgTm9uZSkg"
    "LT4gTm9uZToKICAgICAgICBpZiBub3QgcGF5bG9hZDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5jdXJyZW50X3Bv"
    "b2wgPSBkaWN0KHBheWxvYWQuZ2V0KCJwb29sIiwge30pKQogICAgICAgIHNlbGYubW9kX3NwaW4uc2V0VmFsdWUoaW50KHBheWxv"
    "YWQuZ2V0KCJtb2RpZmllciIsIDApKSkKICAgICAgICBzZWxmLmxhYmVsX2VkaXQuc2V0VGV4dChzdHIocGF5bG9hZC5nZXQoIm5h"
    "bWUiLCAiIikpKQogICAgICAgIHJpZCA9IHBheWxvYWQuZ2V0KCJydWxlX2lkIikKICAgICAgICBpZHggPSBzZWxmLnJ1bGVfY29t"
    "Ym8uZmluZERhdGEocmlkIG9yICIiKQogICAgICAgIGlmIGlkeCA+PSAwOgogICAgICAgICAgICBzZWxmLnJ1bGVfY29tYm8uc2V0"
    "Q3VycmVudEluZGV4KGlkeCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3Bvb2xfZWRpdG9yKCkKICAgICAgICBzZWxmLmN1cnJlbnRf"
    "cmVzdWx0X2xibC5zZXRUZXh0KGYiQ3VycmVudCBQb29sOiB7c2VsZi5fcG9vbF9leHByZXNzaW9uKCl9IikKCiAgICBkZWYgX3J1"
    "bl9zZWxlY3RlZF9zYXZlZChzZWxmKToKICAgICAgICBpdGVtID0gc2VsZi5zYXZlZF9saXN0LmN1cnJlbnRJdGVtKCkKICAgICAg"
    "ICBzZWxmLl9ydW5fc2F2ZWRfcm9sbChpdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKSBpZiBpdGVtIGVsc2UgTm9u"
    "ZSkKCiAgICBkZWYgX2xvYWRfc2VsZWN0ZWRfc2F2ZWQoc2VsZik6CiAgICAgICAgaXRlbSA9IHNlbGYuc2F2ZWRfbGlzdC5jdXJy"
    "ZW50SXRlbSgpCiAgICAgICAgcGF5bG9hZCA9IGl0ZW0uZGF0YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpIGlmIGl0ZW0gZWxz"
    "ZSBOb25lCiAgICAgICAgaWYgbm90IHBheWxvYWQ6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2xvYWRfcGF5bG9h"
    "ZF9pbnRvX3Bvb2wocGF5bG9hZCkKCiAgICAgICAgbmFtZSwgb2sgPSBRSW5wdXREaWFsb2cuZ2V0VGV4dChzZWxmLCAiRWRpdCBT"
    "YXZlZCBSb2xsIiwgIk5hbWU6IiwgdGV4dD1zdHIocGF5bG9hZC5nZXQoIm5hbWUiLCAiIikpKQogICAgICAgIGlmIG5vdCBvazoK"
    "ICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcGF5bG9hZFsibmFtZSJdID0gbmFtZS5zdHJpcCgpIG9yIHBheWxvYWQuZ2V0KCJu"
    "YW1lIiwgIiIpCiAgICAgICAgcGF5bG9hZFsicG9vbCJdID0gZGljdChzZWxmLmN1cnJlbnRfcG9vbCkKICAgICAgICBwYXlsb2Fk"
    "WyJtb2RpZmllciJdID0gaW50KHNlbGYubW9kX3NwaW4udmFsdWUoKSkKICAgICAgICBwYXlsb2FkWyJydWxlX2lkIl0gPSBzZWxm"
    "LnJ1bGVfY29tYm8uY3VycmVudERhdGEoKSBvciBOb25lCiAgICAgICAgbm90ZXMsIG9rX25vdGVzID0gUUlucHV0RGlhbG9nLmdl"
    "dFRleHQoc2VsZiwgIkVkaXQgU2F2ZWQgUm9sbCIsICJOb3RlcyAvIGNhdGVnb3J5OiIsIHRleHQ9c3RyKHBheWxvYWQuZ2V0KCJu"
    "b3RlcyIsICIiKSkpCiAgICAgICAgaWYgb2tfbm90ZXM6CiAgICAgICAgICAgIHBheWxvYWRbIm5vdGVzIl0gPSBub3RlcwogICAg"
    "ICAgIHNlbGYuX3JlZnJlc2hfc2F2ZWRfbGlzdHMoKQoKICAgIGRlZiBfZGVsZXRlX3NlbGVjdGVkX3NhdmVkKHNlbGYpOgogICAg"
    "ICAgIHJvdyA9IHNlbGYuc2F2ZWRfbGlzdC5jdXJyZW50Um93KCkKICAgICAgICBpZiByb3cgPCAwIG9yIHJvdyA+PSBsZW4oc2Vs"
    "Zi5zYXZlZF9yb2xscyk6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuc2F2ZWRfcm9sbHMucG9wKHJvdykKICAgICAg"
    "ICBzZWxmLl9yZWZyZXNoX3NhdmVkX2xpc3RzKCkKCiAgICBkZWYgX3Byb21vdGVfc2VsZWN0ZWRfY29tbW9uKHNlbGYpOgogICAg"
    "ICAgIGl0ZW0gPSBzZWxmLmNvbW1vbl9saXN0LmN1cnJlbnRJdGVtKCkKICAgICAgICBwYXlsb2FkID0gaXRlbS5kYXRhKFF0Lkl0"
    "ZW1EYXRhUm9sZS5Vc2VyUm9sZSkgaWYgaXRlbSBlbHNlIE5vbmUKICAgICAgICBpZiBub3QgcGF5bG9hZDoKICAgICAgICAgICAg"
    "cmV0dXJuCiAgICAgICAgcHJvbW90ZWQgPSB7CiAgICAgICAgICAgICJpZCI6IGYic2F2ZWRfe3V1aWQudXVpZDQoKS5oZXhbOjEw"
    "XX0iLAogICAgICAgICAgICAibmFtZSI6IHBheWxvYWQuZ2V0KCJuYW1lIikgb3Igc2VsZi5fcG9vbF9leHByZXNzaW9uKHBheWxv"
    "YWQuZ2V0KCJwb29sIiwge30pKSwKICAgICAgICAgICAgInBvb2wiOiBkaWN0KHBheWxvYWQuZ2V0KCJwb29sIiwge30pKSwKICAg"
    "ICAgICAgICAgIm1vZGlmaWVyIjogaW50KHBheWxvYWQuZ2V0KCJtb2RpZmllciIsIDApKSwKICAgICAgICAgICAgInJ1bGVfaWQi"
    "OiBwYXlsb2FkLmdldCgicnVsZV9pZCIpLAogICAgICAgICAgICAibm90ZXMiOiBwYXlsb2FkLmdldCgibm90ZXMiLCAiIiksCiAg"
    "ICAgICAgICAgICJjYXRlZ29yeSI6ICJzYXZlZCIsCiAgICAgICAgfQogICAgICAgIHNlbGYuc2F2ZWRfcm9sbHMuYXBwZW5kKHBy"
    "b21vdGVkKQogICAgICAgIHNlbGYuX3JlZnJlc2hfc2F2ZWRfbGlzdHMoKQoKICAgIGRlZiBfZGlzbWlzc19zZWxlY3RlZF9jb21t"
    "b24oc2VsZik6CiAgICAgICAgaXRlbSA9IHNlbGYuY29tbW9uX2xpc3QuY3VycmVudEl0ZW0oKQogICAgICAgIHBheWxvYWQgPSBp"
    "dGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKSBpZiBpdGVtIGVsc2UgTm9uZQogICAgICAgIGlmIG5vdCBwYXlsb2Fk"
    "OgogICAgICAgICAgICByZXR1cm4KICAgICAgICBzaWcgPSBwYXlsb2FkLmdldCgic2lnbmF0dXJlIikKICAgICAgICBpZiBzaWcg"
    "aW4gc2VsZi5jb21tb25fcm9sbHM6CiAgICAgICAgICAgIHNlbGYuY29tbW9uX3JvbGxzLnBvcChzaWcsIE5vbmUpCiAgICAgICAg"
    "c2VsZi5fcmVmcmVzaF9zYXZlZF9saXN0cygpCgogICAgZGVmIF9yZXNldF9wb29sKHNlbGYpOgogICAgICAgIHNlbGYuY3VycmVu"
    "dF9wb29sID0ge30KICAgICAgICBzZWxmLm1vZF9zcGluLnNldFZhbHVlKDApCiAgICAgICAgc2VsZi5sYWJlbF9lZGl0LmNsZWFy"
    "KCkKICAgICAgICBzZWxmLnJ1bGVfY29tYm8uc2V0Q3VycmVudEluZGV4KDApCiAgICAgICAgc2VsZi5fcmVmcmVzaF9wb29sX2Vk"
    "aXRvcigpCiAgICAgICAgc2VsZi5jdXJyZW50X3Jlc3VsdF9sYmwuc2V0VGV4dCgiTm8gcm9sbCB5ZXQuIikKCiAgICBkZWYgX2Ns"
    "ZWFyX2hpc3Rvcnkoc2VsZik6CiAgICAgICAgc2VsZi5yb2xsX2V2ZW50cy5jbGVhcigpCiAgICAgICAgc2VsZi5ldmVudF9ieV9p"
    "ZC5jbGVhcigpCiAgICAgICAgc2VsZi5jdXJyZW50X3JvbGxfaWRzID0gW10KICAgICAgICBzZWxmLmhpc3RvcnlfdGFibGUuc2V0"
    "Um93Q291bnQoMCkKICAgICAgICBzZWxmLmN1cnJlbnRfdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBzZWxmLl91cGRhdGVf"
    "Z3JhbmRfdG90YWwoKQogICAgICAgIHNlbGYuY3VycmVudF9yZXN1bHRfbGJsLnNldFRleHQoIk5vIHJvbGwgeWV0LiIpCgogICAg"
    "ZGVmIF9ldmVudF9mcm9tX3RhYmxlX3Bvc2l0aW9uKHNlbGYsIHRhYmxlOiBRVGFibGVXaWRnZXQsIHBvcykgLT4gZGljdCB8IE5v"
    "bmU6CiAgICAgICAgaXRlbSA9IHRhYmxlLml0ZW1BdChwb3MpCiAgICAgICAgaWYgbm90IGl0ZW06CiAgICAgICAgICAgIHJldHVy"
    "biBOb25lCiAgICAgICAgcm93ID0gaXRlbS5yb3coKQogICAgICAgIHRzX2l0ZW0gPSB0YWJsZS5pdGVtKHJvdywgMCkKICAgICAg"
    "ICBpZiBub3QgdHNfaXRlbToKICAgICAgICAgICAgcmV0dXJuIE5vbmUKICAgICAgICBlaWQgPSB0c19pdGVtLmRhdGEoUXQuSXRl"
    "bURhdGFSb2xlLlVzZXJSb2xlKQogICAgICAgIHJldHVybiBzZWxmLmV2ZW50X2J5X2lkLmdldChlaWQpCgogICAgZGVmIF9zaG93"
    "X3JvbGxfY29udGV4dF9tZW51KHNlbGYsIHRhYmxlOiBRVGFibGVXaWRnZXQsIHBvcykgLT4gTm9uZToKICAgICAgICBldnQgPSBz"
    "ZWxmLl9ldmVudF9mcm9tX3RhYmxlX3Bvc2l0aW9uKHRhYmxlLCBwb3MpCiAgICAgICAgaWYgbm90IGV2dDoKICAgICAgICAgICAg"
    "cmV0dXJuCiAgICAgICAgZnJvbSBQeVNpZGU2LlF0V2lkZ2V0cyBpbXBvcnQgUU1lbnUKICAgICAgICBtZW51ID0gUU1lbnUoc2Vs"
    "ZikKICAgICAgICBhY3Rfc2VuZCA9IG1lbnUuYWRkQWN0aW9uKCJTZW5kIHRvIFByb21wdCIpCiAgICAgICAgY2hvc2VuID0gbWVu"
    "dS5leGVjKHRhYmxlLnZpZXdwb3J0KCkubWFwVG9HbG9iYWwocG9zKSkKICAgICAgICBpZiBjaG9zZW4gPT0gYWN0X3NlbmQ6CiAg"
    "ICAgICAgICAgIHNlbGYuX3NlbmRfZXZlbnRfdG9fcHJvbXB0KGV2dCkKCiAgICBkZWYgX2Zvcm1hdF9ldmVudF9mb3JfcHJvbXB0"
    "KHNlbGYsIGV2ZW50OiBkaWN0KSAtPiBzdHI6CiAgICAgICAgbGFiZWwgPSAoZXZlbnQuZ2V0KCJsYWJlbCIpIG9yICJSb2xsIiku"
    "c3RyaXAoKQogICAgICAgIGdyb3VwZWQgPSBldmVudC5nZXQoImdyb3VwZWRfcmF3X2Rpc3BsYXkiLCB7fSkgb3Ige30KICAgICAg"
    "ICBzZWdtZW50cyA9IFtdCiAgICAgICAgZm9yIGRpZSBpbiBzZWxmLlRSQVlfT1JERVI6CiAgICAgICAgICAgIHZhbHMgPSBncm91"
    "cGVkLmdldChkaWUpCiAgICAgICAgICAgIGlmIHZhbHM6CiAgICAgICAgICAgICAgICBzZWdtZW50cy5hcHBlbmQoZiJ7ZGllfSBy"
    "b2xsZWQgeycsJy5qb2luKHN0cih2KSBmb3IgdiBpbiB2YWxzKX0iKQogICAgICAgIG1vZCA9IGludChldmVudC5nZXQoIm1vZGlm"
    "aWVyIiwgMCkpCiAgICAgICAgdG90YWwgPSBpbnQoZXZlbnQuZ2V0KCJmaW5hbF90b3RhbCIsIDApKQogICAgICAgIHJldHVybiBm"
    "IntsYWJlbH06IHsnOyAnLmpvaW4oc2VnbWVudHMpfTsgbW9kaWZpZXIge21vZDorZH07IHRvdGFsIHt0b3RhbH0iCgogICAgZGVm"
    "IF9zZW5kX2V2ZW50X3RvX3Byb21wdChzZWxmLCBldmVudDogZGljdCkgLT4gTm9uZToKICAgICAgICB3aW5kb3cgPSBzZWxmLndp"
    "bmRvdygpCiAgICAgICAgaWYgbm90IHdpbmRvdyBvciBub3QgaGFzYXR0cih3aW5kb3csICJfaW5wdXRfZmllbGQiKToKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgbGluZSA9IHNlbGYuX2Zvcm1hdF9ldmVudF9mb3JfcHJvbXB0KGV2ZW50KQogICAgICAgIHdp"
    "bmRvdy5faW5wdXRfZmllbGQuc2V0VGV4dChsaW5lKQogICAgICAgIHdpbmRvdy5faW5wdXRfZmllbGQuc2V0Rm9jdXMoKQoKICAg"
    "IGRlZiBfcGxheV9yb2xsX3NvdW5kKHNlbGYpOgogICAgICAgIGlmIG5vdCBXSU5TT1VORF9PSzoKICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgdHJ5OgogICAgICAgICAgICB3aW5zb3VuZC5CZWVwKDg0MCwgMzApCiAgICAgICAgICAgIHdpbnNvdW5kLkJlZXAo"
    "NjIwLCAzNSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCgoKY2xhc3MgTWFnaWM4QmFsbFRhYihR"
    "V2lkZ2V0KToKICAgICIiIlNpbXBsZSBNYWdpYyA4LUJhbGwgbW9kdWxlIHRhYiB3aXRoIHN0YW5kYXJkIGFuc3dlcnMgYW5kIGZh"
    "ZGUgZWZmZWN0cy4iIiIKCiAgICBBTlNXRVJTID0gWwogICAgICAgICJJdCBpcyBjZXJ0YWluLiIsCiAgICAgICAgIkl0IGlzIGRl"
    "Y2lkZWRseSBzby4iLAogICAgICAgICJXaXRob3V0IGEgZG91YnQuIiwKICAgICAgICAiWWVzIGRlZmluaXRlbHkuIiwKICAgICAg"
    "ICAiWW91IG1heSByZWx5IG9uIGl0LiIsCiAgICAgICAgIkFzIEkgc2VlIGl0LCB5ZXMuIiwKICAgICAgICAiTW9zdCBsaWtlbHku"
    "IiwKICAgICAgICAiT3V0bG9vayBnb29kLiIsCiAgICAgICAgIlllcy4iLAogICAgICAgICJTaWducyBwb2ludCB0byB5ZXMuIiwK"
    "ICAgICAgICAiUmVwbHkgaGF6eSwgdHJ5IGFnYWluLiIsCiAgICAgICAgIkFzayBhZ2FpbiBsYXRlci4iLAogICAgICAgICJCZXR0"
    "ZXIgbm90IHRlbGwgeW91IG5vdy4iLAogICAgICAgICJDYW5ub3QgcHJlZGljdCBub3cuIiwKICAgICAgICAiQ29uY2VudHJhdGUg"
    "YW5kIGFzayBhZ2Fpbi4iLAogICAgICAgICJEb24ndCBjb3VudCBvbiBpdC4iLAogICAgICAgICJNeSByZXBseSBpcyBuby4iLAog"
    "ICAgICAgICJNeSBzb3VyY2VzIHNheSBuby4iLAogICAgICAgICJPdXRsb29rIG5vdCBzbyBnb29kLiIsCiAgICAgICAgIlZlcnkg"
    "ZG91YnRmdWwuIiwKICAgIF0KCiAgICBkZWYgX19pbml0X18oc2VsZiwgb25fdGhyb3c9Tm9uZSwgZGlhZ25vc3RpY3NfbG9nZ2Vy"
    "PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQogICAgICAgIHNlbGYuX29uX3Rocm93ID0gb25fdGhyb3cKICAgICAg"
    "ICBzZWxmLl9sb2cgPSBkaWFnbm9zdGljc19sb2dnZXIgb3IgKGxhbWJkYSAqX2FyZ3MsICoqX2t3YXJnczogTm9uZSkKICAgICAg"
    "ICBzZWxmLl9jdXJyZW50X2Fuc3dlciA9ICIiCgogICAgICAgIHNlbGYuX2NsZWFyX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAg"
    "ICAgc2VsZi5fY2xlYXJfdGltZXIuc2V0U2luZ2xlU2hvdChUcnVlKQogICAgICAgIHNlbGYuX2NsZWFyX3RpbWVyLnRpbWVvdXQu"
    "Y29ubmVjdChzZWxmLl9mYWRlX291dF9hbnN3ZXIpCgogICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKICAgICAgICBzZWxmLl9idWls"
    "ZF9hbmltYXRpb25zKCkKCiAgICBkZWYgX2J1aWxkX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0"
    "KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoMTYsIDE2LCAxNiwgMTYpCiAgICAgICAgcm9vdC5zZXRTcGFj"
    "aW5nKDE0KQogICAgICAgIHJvb3QuYWRkU3RyZXRjaCgxKQoKICAgICAgICBvcmJfZnJhbWUgPSBRRnJhbWUoKQogICAgICAgIG9y"
    "Yl9mcmFtZS5zZXRGaXhlZFNpemUoMjEwLCAyMTApCiAgICAgICAgb3JiX2ZyYW1lLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "ICJRRnJhbWUgeyIKICAgICAgICAgICAgImJhY2tncm91bmQtY29sb3I6ICMwODA4MDg7IgogICAgICAgICAgICAiYm9yZGVyOiAy"
    "cHggc29saWQgIzIzMjMzNjsiCiAgICAgICAgICAgICJib3JkZXItcmFkaXVzOiAxMDVweDsiCiAgICAgICAgICAgICJ9IgogICAg"
    "ICAgICkKICAgICAgICBvcmJfbGF5b3V0ID0gUVZCb3hMYXlvdXQob3JiX2ZyYW1lKQogICAgICAgIG9yYl9sYXlvdXQuc2V0Q29u"
    "dGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgb3JiX2xheW91dC5zZXRTcGFjaW5nKDApCgogICAgICAgIGVpZ2h0X2Nv"
    "cmUgPSBRTGFiZWwoIjgiKQogICAgICAgIGVpZ2h0X2NvcmUuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50"
    "ZXIpCiAgICAgICAgZWlnaHRfY29yZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAiY29sb3I6ICNmZmZmZmY7IGZvbnQtc2l6"
    "ZTogNzJweDsgZm9udC13ZWlnaHQ6IDcwMDsgIgogICAgICAgICAgICAiZm9udC1mYW1pbHk6IEdlb3JnaWEsIHNlcmlmOyBib3Jk"
    "ZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBvcmJfbGF5b3V0LmFkZFdpZGdldChlaWdodF9jb3JlKQogICAgICAgIHJvb3Qu"
    "YWRkV2lkZ2V0KG9yYl9mcmFtZSwgMCwgUXQuQWxpZ25tZW50RmxhZy5BbGlnbkhDZW50ZXIpCgogICAgICAgIHNlbGYuYW5zd2Vy"
    "X2xibCA9IFFMYWJlbCgiQXNrIGFuZCBjYXN0IHlvdXIgZmF0ZS4uLiIpCiAgICAgICAgc2VsZi5hbnN3ZXJfbGJsLnNldEFsaWdu"
    "bWVudChRdC5BbGlnbm1lbnRGbGFnLkFsaWduQ2VudGVyKQogICAgICAgIHNlbGYuYW5zd2VyX2xibC5zZXRXb3JkV3JhcChUcnVl"
    "KQogICAgICAgIHNlbGYuYW5zd2VyX2xibC5zZXRNaW5pbXVtSGVpZ2h0KDU4KQogICAgICAgIHNlbGYuYW5zd2VyX2xibC5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiAxNnB4OyBmb250LXN0eWxlOiBpdGFs"
    "aWM7ICIKICAgICAgICAgICAgInBhZGRpbmc6IDZweCAxMHB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICByb290"
    "LmFkZFdpZGdldChzZWxmLmFuc3dlcl9sYmwpCgogICAgICAgIHNlbGYudGhyb3dfYnRuID0gUVB1c2hCdXR0b24oIlRocm93IHRo"
    "ZSA4LUJhbGwiKQogICAgICAgIHNlbGYudGhyb3dfYnRuLnNldEZpeGVkSGVpZ2h0KDM4KQogICAgICAgIHNlbGYudGhyb3dfYnRu"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl90aHJvd19iYWxsKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYudGhyb3dfYnRuLCAw"
    "LCBRdC5BbGlnbm1lbnRGbGFnLkFsaWduSENlbnRlcikKICAgICAgICByb290LmFkZFN0cmV0Y2goMSkKCiAgICBkZWYgX2J1aWxk"
    "X2FuaW1hdGlvbnMoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hbnN3ZXJfb3BhY2l0eSA9IFFHcmFwaGljc09wYWNpdHlF"
    "ZmZlY3Qoc2VsZi5hbnN3ZXJfbGJsKQogICAgICAgIHNlbGYuYW5zd2VyX2xibC5zZXRHcmFwaGljc0VmZmVjdChzZWxmLl9hbnN3"
    "ZXJfb3BhY2l0eSkKICAgICAgICBzZWxmLl9hbnN3ZXJfb3BhY2l0eS5zZXRPcGFjaXR5KDAuNTUpCgogICAgICAgIHNlbGYuX2Zh"
    "ZGVfaW4gPSBRUHJvcGVydHlBbmltYXRpb24oc2VsZi5fYW5zd2VyX29wYWNpdHksIGIib3BhY2l0eSIsIHNlbGYpCiAgICAgICAg"
    "c2VsZi5fZmFkZV9pbi5zZXREdXJhdGlvbig0MjApCiAgICAgICAgc2VsZi5fZmFkZV9pbi5zZXRTdGFydFZhbHVlKDAuMCkKICAg"
    "ICAgICBzZWxmLl9mYWRlX2luLnNldEVuZFZhbHVlKDEuMCkKICAgICAgICBzZWxmLl9mYWRlX2luLnNldEVhc2luZ0N1cnZlKFFF"
    "YXNpbmdDdXJ2ZS5UeXBlLkluT3V0UXVhZCkKCiAgICAgICAgc2VsZi5fZmFkZV9vdXQgPSBRUHJvcGVydHlBbmltYXRpb24oc2Vs"
    "Zi5fYW5zd2VyX29wYWNpdHksIGIib3BhY2l0eSIsIHNlbGYpCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc2V0RHVyYXRpb24oNTAw"
    "KQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LnNldFN0YXJ0VmFsdWUoMS4wKQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LnNldEVuZFZh"
    "bHVlKDAuMCkKICAgICAgICBzZWxmLl9mYWRlX291dC5zZXRFYXNpbmdDdXJ2ZShRRWFzaW5nQ3VydmUuVHlwZS5Jbk91dFF1YWQp"
    "CiAgICAgICAgc2VsZi5fZmFkZV9vdXQuZmluaXNoZWQuY29ubmVjdChzZWxmLl9jbGVhcl90b19pZGxlKQoKICAgIGRlZiBfdGhy"
    "b3dfYmFsbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2NsZWFyX3RpbWVyLnN0b3AoKQogICAgICAgIHNlbGYuX2ZhZGVf"
    "aW4uc3RvcCgpCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc3RvcCgpCgogICAgICAgIGFuc3dlciA9IHJhbmRvbS5jaG9pY2Uoc2Vs"
    "Zi5BTlNXRVJTKQogICAgICAgIHNlbGYuX2N1cnJlbnRfYW5zd2VyID0gYW5zd2VyCiAgICAgICAgc2VsZi5hbnN3ZXJfbGJsLnNl"
    "dFRleHQoYW5zd2VyKQogICAgICAgIHNlbGYuX2Fuc3dlcl9vcGFjaXR5LnNldE9wYWNpdHkoMC4wKQogICAgICAgIHNlbGYuX2Zh"
    "ZGVfaW4uc3RhcnQoKQogICAgICAgIHNlbGYuX2NsZWFyX3RpbWVyLnN0YXJ0KDYwMDAwKQogICAgICAgIHNlbGYuX2xvZyhmIls4"
    "QkFMTF0gVGhyb3cgcmVzdWx0OiB7YW5zd2VyfSIsICJJTkZPIikKCiAgICAgICAgaWYgY2FsbGFibGUoc2VsZi5fb25fdGhyb3cp"
    "OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBzZWxmLl9vbl90aHJvdyhhbnN3ZXIpCiAgICAgICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9sb2coZiJbOEJBTExdW1dBUk5dIEludGVybmFsIHByb21w"
    "dCBkaXNwYXRjaCBmYWlsZWQ6IHtleH0iLCAiV0FSTiIpCgogICAgZGVmIF9mYWRlX291dF9hbnN3ZXIoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9mYWRlX2luLnN0b3AoKQogICAgICAgIHNlbGYuX2ZhZGVfb3V0LnN0b3AoKQogICAgICAgIHNlbGYuX2Zh"
    "ZGVfb3V0LnNldFN0YXJ0VmFsdWUoZmxvYXQoc2VsZi5fYW5zd2VyX29wYWNpdHkub3BhY2l0eSgpKSkKICAgICAgICBzZWxmLl9m"
    "YWRlX291dC5zZXRFbmRWYWx1ZSgwLjApCiAgICAgICAgc2VsZi5fZmFkZV9vdXQuc3RhcnQoKQoKICAgIGRlZiBfY2xlYXJfdG9f"
    "aWRsZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2N1cnJlbnRfYW5zd2VyID0gIiIKICAgICAgICBzZWxmLmFuc3dlcl9s"
    "Ymwuc2V0VGV4dCgiQXNrIGFuZCBjYXN0IHlvdXIgZmF0ZS4uLiIpCiAgICAgICAgc2VsZi5fYW5zd2VyX29wYWNpdHkuc2V0T3Bh"
    "Y2l0eSgwLjU1KQoKIyDilIDilIAgTUFJTiBXSU5ET1cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNs"
    "YXNzIEVjaG9EZWNrKFFNYWluV2luZG93KToKICAgICIiIgogICAgVGhlIG1haW4gRWNobyBEZWNrIHdpbmRvdy4KICAgIEFzc2Vt"
    "YmxlcyBhbGwgd2lkZ2V0cywgY29ubmVjdHMgYWxsIHNpZ25hbHMsIG1hbmFnZXMgYWxsIHN0YXRlLgogICAgIiIiCgogICAgIyDi"
    "lIDilIAgVG9ycG9yIHRocmVzaG9sZHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACiAgICBfRVhURVJOQUxfVlJBTV9UT1JQT1JfR0IgICAgPSAxLjUgICAjIGV4dGVybmFsIFZSQU0gPiB0aGlz"
    "IOKGkiBjb25zaWRlciB0b3Jwb3IKICAgIF9FWFRFUk5BTF9WUkFNX1dBS0VfR0IgICAgICA9IDAuOCAgICMgZXh0ZXJuYWwgVlJB"
    "TSA8IHRoaXMg4oaSIGNvbnNpZGVyIHdha2UKICAgIF9UT1JQT1JfU1VTVEFJTkVEX1RJQ0tTICAgICA9IDYgICAgICMgNiDDlyA1"
    "cyA9IDMwIHNlY29uZHMgc3VzdGFpbmVkCiAgICBfV0FLRV9TVVNUQUlORURfVElDS1MgICAgICAgPSAxMiAgICAjIDYwIHNlY29u"
    "ZHMgc3VzdGFpbmVkIGxvdyBwcmVzc3VyZQoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBzdXBlcigpLl9faW5pdF9f"
    "KCkKCiAgICAgICAgIyDilIDilIAgQ29yZSBzdGF0ZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zdGF0dXMgICAgICAgICAgICAgID0gIk9GRkxJTkUi"
    "CiAgICAgICAgc2VsZi5fc2Vzc2lvbl9zdGFydCAgICAgICA9IHRpbWUudGltZSgpCiAgICAgICAgc2VsZi5fdG9rZW5fY291bnQg"
    "ICAgICAgICA9IDAKICAgICAgICBzZWxmLl9mYWNlX2xvY2tlZCAgICAgICAgID0gRmFsc2UKICAgICAgICBzZWxmLl9ibGlua19z"
    "dGF0ZSAgICAgICAgID0gVHJ1ZQogICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCAgICAgICAgPSBGYWxzZQogICAgICAgIHNlbGYu"
    "X3Nlc3Npb25faWQgICAgICAgICAgPSBmInNlc3Npb25fe2RhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9"
    "IgogICAgICAgIHNlbGYuX2FjdGl2ZV90aHJlYWRzOiBsaXN0ID0gW10gICMga2VlcCByZWZzIHRvIHByZXZlbnQgR0Mgd2hpbGUg"
    "cnVubmluZwogICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuOiBib29sID0gVHJ1ZSAgICMgd3JpdGUgc3BlYWtlciBsYWJlbCBiZWZv"
    "cmUgZmlyc3Qgc3RyZWFtaW5nIHRva2VuCgogICAgICAgICMgVG9ycG9yIC8gVlJBTSB0cmFja2luZwogICAgICAgIHNlbGYuX3Rv"
    "cnBvcl9zdGF0ZSAgICAgICAgPSAiQVdBS0UiCiAgICAgICAgc2VsZi5fZGVja192cmFtX2Jhc2UgID0gMC4wICAgIyBiYXNlbGlu"
    "ZSBWUkFNIGFmdGVyIG1vZGVsIGxvYWQKICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMCAgICAgIyBzdXN0YWlu"
    "ZWQgcHJlc3N1cmUgY291bnRlcgogICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICAgPSAwICAgICAjIHN1c3RhaW5lZCBy"
    "ZWxpZWYgY291bnRlcgogICAgICAgIHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyA9IDAKICAgICAgICBzZWxmLl90b3Jwb3Jf"
    "c2luY2UgICAgICAgID0gTm9uZSAgIyBkYXRldGltZSB3aGVuIHRvcnBvciBiZWdhbgogICAgICAgIHNlbGYuX3N1c3BlbmRlZF9k"
    "dXJhdGlvbiAgPSAiIiAgICMgZm9ybWF0dGVkIGR1cmF0aW9uIHN0cmluZwoKICAgICAgICAjIOKUgOKUgCBNYW5hZ2VycyDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICAgICBzZWxmLl9tZW1vcnkgICA9IE1lbW9yeU1hbmFnZXIoKQogICAgICAgIHNlbGYuX3Nlc3Npb25zID0gU2Vzc2lvbk1h"
    "bmFnZXIoKQogICAgICAgIHNlbGYuX2xlc3NvbnMgID0gTGVzc29uc0xlYXJuZWREQigpCiAgICAgICAgc2VsZi5fdGFza3MgICAg"
    "PSBUYXNrTWFuYWdlcigpCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jYWNoZTogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5f"
    "cmVjb3Jkc19pbml0aWFsaXplZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jdXJyZW50X2ZvbGRlcl9pZCA9ICJyb290"
    "IgogICAgICAgIHNlbGYuX2dvb2dsZV9hdXRoX3JlYWR5ID0gRmFsc2UKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1l"
    "cjogT3B0aW9uYWxbUVRpbWVyXSA9IE5vbmUKICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyOiBPcHRp"
    "b25hbFtRVGltZXJdID0gTm9uZQogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiX2luZGV4ID0gLTEKICAgICAgICBzZWxmLl90YXNr"
    "c190YWJfaW5kZXggPSAtMQogICAgICAgIHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX3Rh"
    "c2tfZGF0ZV9maWx0ZXIgPSAibmV4dF8zX21vbnRocyIKCiAgICAgICAgIyDilIDilIAgR29vZ2xlIFNlcnZpY2VzIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICMgSW5zdGFudGlhdGUgc2Vy"
    "dmljZSB3cmFwcGVycyB1cC1mcm9udDsgYXV0aCBpcyBmb3JjZWQgbGF0ZXIKICAgICAgICAjIGZyb20gbWFpbigpIGFmdGVyIHdp"
    "bmRvdy5zaG93KCkgd2hlbiB0aGUgZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgICAgIGdfY3JlZHNfcGF0aCA9IFBhdGgoQ0ZH"
    "LmdldCgiZ29vZ2xlIiwge30pLmdldCgKICAgICAgICAgICAgImNyZWRlbnRpYWxzIiwKICAgICAgICAgICAgc3RyKGNmZ19wYXRo"
    "KCJnb29nbGUiKSAvICJnb29nbGVfY3JlZGVudGlhbHMuanNvbiIpCiAgICAgICAgKSkKICAgICAgICBnX3Rva2VuX3BhdGggPSBQ"
    "YXRoKENGRy5nZXQoImdvb2dsZSIsIHt9KS5nZXQoCiAgICAgICAgICAgICJ0b2tlbiIsCiAgICAgICAgICAgIHN0cihjZmdfcGF0"
    "aCgiZ29vZ2xlIikgLyAidG9rZW4uanNvbiIpCiAgICAgICAgKSkKICAgICAgICBzZWxmLl9nY2FsID0gR29vZ2xlQ2FsZW5kYXJT"
    "ZXJ2aWNlKGdfY3JlZHNfcGF0aCwgZ190b2tlbl9wYXRoKQogICAgICAgIHNlbGYuX2dkcml2ZSA9IEdvb2dsZURvY3NEcml2ZVNl"
    "cnZpY2UoCiAgICAgICAgICAgIGdfY3JlZHNfcGF0aCwKICAgICAgICAgICAgZ190b2tlbl9wYXRoLAogICAgICAgICAgICBsb2dn"
    "ZXI9bGFtYmRhIG1zZywgbGV2ZWw9IklORk8iOiBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR0RSSVZFXSB7bXNnfSIsIGxldmVsKQog"
    "ICAgICAgICkKCiAgICAgICAgIyBTZWVkIExTTCBydWxlcyBvbiBmaXJzdCBydW4KICAgICAgICBzZWxmLl9sZXNzb25zLnNlZWRf"
    "bHNsX3J1bGVzKCkKCiAgICAgICAgIyBMb2FkIGVudGl0eSBzdGF0ZQogICAgICAgIHNlbGYuX3N0YXRlID0gc2VsZi5fbWVtb3J5"
    "LmxvYWRfc3RhdGUoKQogICAgICAgIHNlbGYuX3N0YXRlWyJzZXNzaW9uX2NvdW50Il0gPSBzZWxmLl9zdGF0ZS5nZXQoInNlc3Np"
    "b25fY291bnQiLDApICsgMQogICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X3N0YXJ0dXAiXSAgPSBsb2NhbF9ub3dfaXNvKCkKICAg"
    "ICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9zdGF0ZSkKCiAgICAgICAgIyBCdWlsZCBhZGFwdG9yCiAgICAgICAg"
    "c2VsZi5fYWRhcHRvciA9IGJ1aWxkX2FkYXB0b3JfZnJvbV9jb25maWcoKQoKICAgICAgICAjIEZhY2UgdGltZXIgbWFuYWdlciAo"
    "c2V0IHVwIGFmdGVyIHdpZGdldHMgYnVpbHQpCiAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3I6IE9wdGlvbmFsW0ZhY2VUaW1l"
    "ck1hbmFnZXJdID0gTm9uZQoKICAgICAgICAjIOKUgOKUgCBCdWlsZCBVSSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLnNldFdpbmRvd1RpdGxl"
    "KEFQUF9OQU1FKQogICAgICAgIHNlbGYuc2V0TWluaW11bVNpemUoMTIwMCwgNzUwKQogICAgICAgIHNlbGYucmVzaXplKDEzNTAs"
    "IDg1MCkKICAgICAgICBzZWxmLnNldFN0eWxlU2hlZXQoU1RZTEUpCgogICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKCiAgICAgICAg"
    "IyBGYWNlIHRpbWVyIG1hbmFnZXIgd2lyZWQgdG8gd2lkZ2V0cwogICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyID0gRmFjZVRp"
    "bWVyTWFuYWdlcigKICAgICAgICAgICAgc2VsZi5fbWlycm9yLCBzZWxmLl9lbW90aW9uX2Jsb2NrCiAgICAgICAgKQoKICAgICAg"
    "ICAjIOKUgOKUgCBUaW1lcnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fc3RhdHNfdGltZXIgPSBRVGltZXIoKQogICAgICAgIHNl"
    "bGYuX3N0YXRzX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl91cGRhdGVfc3RhdHMpCiAgICAgICAgc2VsZi5fc3RhdHNfdGlt"
    "ZXIuc3RhcnQoMTAwMCkKCiAgICAgICAgc2VsZi5fYmxpbmtfdGltZXIgPSBRVGltZXIoKQogICAgICAgIHNlbGYuX2JsaW5rX3Rp"
    "bWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9ibGluaykKICAgICAgICBzZWxmLl9ibGlua190aW1lci5zdGFydCg4MDApCgogICAg"
    "ICAgIHNlbGYuX3N0YXRlX3N0cmlwX3RpbWVyID0gUVRpbWVyKCkKICAgICAgICBpZiBBSV9TVEFURVNfRU5BQkxFRCBhbmQgc2Vs"
    "Zi5fZm9vdGVyX3N0cmlwIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl9zdGF0ZV9zdHJpcF90aW1lci50aW1lb3V0LmNv"
    "bm5lY3Qoc2VsZi5fZm9vdGVyX3N0cmlwLnJlZnJlc2gpCiAgICAgICAgICAgIHNlbGYuX3N0YXRlX3N0cmlwX3RpbWVyLnN0YXJ0"
    "KDYwMDAwKQoKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lciA9IFFUaW1lcihzZWxmKQogICAgICAgIHNlbGYuX2dv"
    "b2dsZV9pbmJvdW5kX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9vbl9nb29nbGVfaW5ib3VuZF90aW1lcl90aWNrKQogICAg"
    "ICAgIHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyLnN0YXJ0KHNlbGYuX2dldF9nb29nbGVfcmVmcmVzaF9pbnRlcnZhbF9tcygp"
    "KQoKICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAgICAgc2VsZi5f"
    "Z29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fb25fZ29vZ2xlX3JlY29yZHNfcmVmcmVz"
    "aF90aW1lcl90aWNrKQogICAgICAgIHNlbGYuX2dvb2dsZV9yZWNvcmRzX3JlZnJlc2hfdGltZXIuc3RhcnQoc2VsZi5fZ2V0X2dv"
    "b2dsZV9yZWZyZXNoX2ludGVydmFsX21zKCkpCgogICAgICAgICMg4pSA4pSAIFNjaGVkdWxlciBhbmQgc3RhcnR1cCBkZWZlcnJl"
    "ZCB1bnRpbCBhZnRlciB3aW5kb3cuc2hvdygpIOKUgOKUgOKUgAogICAgICAgICMgRG8gTk9UIGNhbGwgX3NldHVwX3NjaGVkdWxl"
    "cigpIG9yIF9zdGFydHVwX3NlcXVlbmNlKCkgaGVyZS4KICAgICAgICAjIEJvdGggYXJlIHRyaWdnZXJlZCB2aWEgUVRpbWVyLnNp"
    "bmdsZVNob3QgZnJvbSBtYWluKCkgYWZ0ZXIKICAgICAgICAjIHdpbmRvdy5zaG93KCkgYW5kIGFwcC5leGVjKCkgYmVnaW5zIHJ1"
    "bm5pbmcuCgogICAgIyDilIDilIAgVUkgQ09OU1RSVUNUSU9OIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9idWlsZF91aShz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIGNlbnRyYWwgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLnNldENlbnRyYWxXaWRnZXQoY2Vu"
    "dHJhbCkKICAgICAgICByb290ID0gUVZCb3hMYXlvdXQoY2VudHJhbCkKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg2"
    "LCA2LCA2LCA2KQogICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICAjIOKUgOKUgCBUaXRsZSBiYXIg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAg"
    "cm9vdC5hZGRXaWRnZXQoc2VsZi5fYnVpbGRfdGl0bGVfYmFyKCkpCgogICAgICAgICMg4pSA4pSAIEJvZHk6IEpvdXJuYWwgfCBD"
    "aGF0IHwgU3lzdGVtcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBib2R5ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJvZHkuc2V0U3Bh"
    "Y2luZyg0KQoKICAgICAgICAjIEpvdXJuYWwgc2lkZWJhciAobGVmdCkKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIgPSBK"
    "b3VybmFsU2lkZWJhcihzZWxmLl9zZXNzaW9ucykKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2Vzc2lvbl9sb2FkX3Jl"
    "cXVlc3RlZC5jb25uZWN0KAogICAgICAgICAgICBzZWxmLl9sb2FkX2pvdXJuYWxfc2Vzc2lvbikKICAgICAgICBzZWxmLl9qb3Vy"
    "bmFsX3NpZGViYXIuc2Vzc2lvbl9jbGVhcl9yZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5fY2xlYXJfam91cm5h"
    "bF9zZXNzaW9uKQogICAgICAgIGJvZHkuYWRkV2lkZ2V0KHNlbGYuX2pvdXJuYWxfc2lkZWJhcikKCiAgICAgICAgIyBDaGF0IHBh"
    "bmVsIChjZW50ZXIsIGV4cGFuZHMpCiAgICAgICAgYm9keS5hZGRMYXlvdXQoc2VsZi5fYnVpbGRfY2hhdF9wYW5lbCgpLCAxKQoK"
    "ICAgICAgICAjIFN5c3RlbXMgKHJpZ2h0KQogICAgICAgIGJvZHkuYWRkTGF5b3V0KHNlbGYuX2J1aWxkX3NwZWxsYm9va19wYW5l"
    "bCgpKQoKICAgICAgICByb290LmFkZExheW91dChib2R5LCAxKQoKICAgICAgICAjIOKUgOKUgCBGb290ZXIg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgZm9vdGVyID0gUUxhYmVsKAogICAgICAgICAgICBmIuKcpiB7QVBQX05BTUV9IOKAlCB2e0FQUF9WRVJTSU9OfSDinKYi"
    "CiAgICAgICAgKQogICAgICAgIGZvb3Rlci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07"
    "IGZvbnQtc2l6ZTogOXB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZP"
    "TlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIGZvb3Rlci5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNl"
    "bnRlcikKICAgICAgICByb290LmFkZFdpZGdldChmb290ZXIpCgogICAgZGVmIF9idWlsZF90aXRsZV9iYXIoc2VsZikgLT4gUVdp"
    "ZGdldDoKICAgICAgICBiYXIgPSBRV2lkZ2V0KCkKICAgICAgICBiYXIuc2V0Rml4ZWRIZWlnaHQoMzYpCiAgICAgICAgYmFyLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNP"
    "Tl9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyIKICAgICAgICApCiAgICAgICAgbGF5b3V0ID0gUUhC"
    "b3hMYXlvdXQoYmFyKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMTAsIDAsIDEwLCAwKQogICAgICAgIGxheW91"
    "dC5zZXRTcGFjaW5nKDYpCgogICAgICAgIHRpdGxlID0gUUxhYmVsKGYi4pymIHtBUFBfTkFNRX0iKQogICAgICAgIHRpdGxlLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0NSSU1TT059OyBmb250LXNpemU6IDEzcHg7IGZvbnQtd2VpZ2h0"
    "OiBib2xkOyAiCiAgICAgICAgICAgIGYibGV0dGVyLXNwYWNpbmc6IDJweDsgYm9yZGVyOiBub25lOyBmb250LWZhbWlseToge0RF"
    "Q0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCgogICAgICAgIHJ1bmVzID0gUUxhYmVsKFJVTkVTKQogICAgICAgIHJ1bmVzLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTERfRElNfTsgZm9udC1zaXplOiAxMHB4OyBib3JkZXI6IG5v"
    "bmU7IgogICAgICAgICkKICAgICAgICBydW5lcy5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnbkNlbnRlcikKCiAg"
    "ICAgICAgc2VsZi5zdGF0dXNfbGFiZWwgPSBRTGFiZWwoZiLil4kge1VJX09GRkxJTkVfU1RBVFVTfSIpCiAgICAgICAgc2VsZi5z"
    "dGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQkxPT0R9OyBmb250LXNpemU6IDEycHg7"
    "IGZvbnQtd2VpZ2h0OiBib2xkOyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRB"
    "bGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5BbGlnblJpZ2h0KQoKICAgICAgICAjIFN1c3BlbnNpb24gcGFuZWwKICAgICAgICBz"
    "ZWxmLl90b3Jwb3JfcGFuZWwgPSBOb25lCiAgICAgICAgaWYgU1VTUEVOU0lPTl9FTkFCTEVEOgogICAgICAgICAgICBzZWxmLl90"
    "b3Jwb3JfcGFuZWwgPSBUb3Jwb3JQYW5lbCgpCiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9wYW5lbC5zdGF0ZV9jaGFuZ2VkLmNv"
    "bm5lY3Qoc2VsZi5fb25fdG9ycG9yX3N0YXRlX2NoYW5nZWQpCgogICAgICAgICMgSWRsZSB0b2dnbGUKICAgICAgICBpZGxlX2Vu"
    "YWJsZWQgPSBib29sKENGRy5nZXQoInNldHRpbmdzIiwge30pLmdldCgiaWRsZV9lbmFibGVkIiwgRmFsc2UpKQogICAgICAgIHNl"
    "bGYuX2lkbGVfYnRuID0gUVB1c2hCdXR0b24oIklETEUgT04iIGlmIGlkbGVfZW5hYmxlZCBlbHNlICJJRExFIE9GRiIpCiAgICAg"
    "ICAgc2VsZi5faWRsZV9idG4uc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0Q2hlY2thYmxlKFRy"
    "dWUpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0Q2hlY2tlZChpZGxlX2VuYWJsZWQpCiAgICAgICAgc2VsZi5faWRsZV9idG4u"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyAiCiAg"
    "ICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAg"
    "IGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIKICAgICAgICApCiAgICAgICAg"
    "c2VsZi5faWRsZV9idG4udG9nZ2xlZC5jb25uZWN0KHNlbGYuX29uX2lkbGVfdG9nZ2xlZCkKCiAgICAgICAgIyBGUyAvIEJMIGJ1"
    "dHRvbnMKICAgICAgICBzZWxmLl9mc19idG4gPSBRUHVzaEJ1dHRvbigiRnVsbHNjcmVlbiIpCiAgICAgICAgc2VsZi5fYmxfYnRu"
    "ID0gUVB1c2hCdXR0b24oIkJvcmRlcmxlc3MiKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4gPSBRUHVzaEJ1dHRvbigiRXhwb3J0"
    "IikKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4gPSBRUHVzaEJ1dHRvbigiU2h1dGRvd24iKQogICAgICAgIGZvciBidG4gaW4g"
    "KHNlbGYuX2ZzX2J0biwgc2VsZi5fYmxfYnRuLCBzZWxmLl9leHBvcnRfYnRuKToKICAgICAgICAgICAgYnRuLnNldEZpeGVkSGVp"
    "Z2h0KDIyKQogICAgICAgICAgICBidG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcz"
    "fTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09O"
    "X0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIK"
    "ICAgICAgICAgICAgKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4uc2V0Rml4ZWRXaWR0aCg0NikKICAgICAgICBzZWxmLl9zaHV0"
    "ZG93bl9idG4uc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldEZpeGVkV2lkdGgoNjgpCiAg"
    "ICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsg"
    "Y29sb3I6IHtDX0JMT09EfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JMT09EfTsgZm9udC1zaXplOiA5"
    "cHg7ICIKICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMDsiCiAgICAgICAgKQogICAgICAgIHNlbGYu"
    "X2ZzX2J0bi5zZXRUb29sVGlwKCJGdWxsc2NyZWVuIChGMTEpIikKICAgICAgICBzZWxmLl9ibF9idG4uc2V0VG9vbFRpcCgiQm9y"
    "ZGVybGVzcyAoRjEwKSIpCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0bi5zZXRUb29sVGlwKCJFeHBvcnQgY2hhdCBzZXNzaW9uIHRv"
    "IFRYVCBmaWxlIikKICAgICAgICBzZWxmLl9zaHV0ZG93bl9idG4uc2V0VG9vbFRpcChmIkdyYWNlZnVsIHNodXRkb3duIOKAlCB7"
    "REVDS19OQU1FfSBzcGVha3MgdGhlaXIgbGFzdCB3b3JkcyIpCiAgICAgICAgc2VsZi5fZnNfYnRuLmNsaWNrZWQuY29ubmVjdChz"
    "ZWxmLl90b2dnbGVfZnVsbHNjcmVlbikKICAgICAgICBzZWxmLl9ibF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3RvZ2dsZV9i"
    "b3JkZXJsZXNzKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX2V4cG9ydF9jaGF0KQogICAg"
    "ICAgIHNlbGYuX3NodXRkb3duX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5faW5pdGlhdGVfc2h1dGRvd25fZGlhbG9nKQoKICAg"
    "ICAgICBsYXlvdXQuYWRkV2lkZ2V0KHRpdGxlKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQocnVuZXMsIDEpCiAgICAgICAgbGF5"
    "b3V0LmFkZFdpZGdldChzZWxmLnN0YXR1c19sYWJlbCkKICAgICAgICBsYXlvdXQuYWRkU3BhY2luZyg4KQogICAgICAgIGxheW91"
    "dC5hZGRXaWRnZXQoc2VsZi5fZXhwb3J0X2J0bikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3NodXRkb3duX2J0bikK"
    "CiAgICAgICAgcmV0dXJuIGJhcgoKICAgIGRlZiBfYnVpbGRfY2hhdF9wYW5lbChzZWxmKSAtPiBRVkJveExheW91dDoKICAgICAg"
    "ICBsYXlvdXQgPSBRVkJveExheW91dCgpCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBNYWluIHRhYiB3"
    "aWRnZXQg4oCUIHBlcnNvbmEgY2hhdCB0YWIgfCBTZWxmCiAgICAgICAgc2VsZi5fbWFpbl90YWJzID0gUVRhYldpZGdldCgpCiAg"
    "ICAgICAgc2VsZi5fbWFpbl90YWJzLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUVRhYldpZGdldDo6cGFuZSB7eyBib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgfX0i"
    "CiAgICAgICAgICAgIGYiUVRhYkJhcjo6dGFiIHt7IGJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIK"
    "ICAgICAgICAgICAgZiJwYWRkaW5nOiA0cHggMTJweDsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAg"
    "ICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsgfX0iCiAgICAgICAgICAgIGYiUVRh"
    "YkJhcjo6dGFiOnNlbGVjdGVkIHt7IGJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBm"
    "ImJvcmRlci1ib3R0b206IDJweCBzb2xpZCB7Q19DUklNU09OfTsgfX0iCiAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBUYWIg"
    "MDogUGVyc29uYSBjaGF0IHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWFuY2Vfd2lkZ2V0ID0g"
    "UVdpZGdldCgpCiAgICAgICAgc2VhbmNlX2xheW91dCA9IFFWQm94TGF5b3V0KHNlYW5jZV93aWRnZXQpCiAgICAgICAgc2VhbmNl"
    "X2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBzZWFuY2VfbGF5b3V0LnNldFNwYWNpbmcoMCkK"
    "ICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRSZWFk"
    "T25seShUcnVlKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91"
    "bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IG5vbmU7ICIKICAgICAgICAg"
    "ICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEycHg7IHBhZGRpbmc6IDhweDsiCiAgICAg"
    "ICAgKQogICAgICAgIHNlYW5jZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2NoYXRfZGlzcGxheSkKICAgICAgICBzZWxmLl9tYWlu"
    "X3RhYnMuYWRkVGFiKHNlYW5jZV93aWRnZXQsIGYi4p2nIHtVSV9DSEFUX1dJTkRPV30iKQoKICAgICAgICAjIOKUgOKUgCBUYWIg"
    "MTogU2VsZiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgICAgICBzZWxmLl9zZWxmX3RhYl93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmX2xheW91dCA9IFFWQm94TGF5"
    "b3V0KHNlbGYuX3NlbGZfdGFiX3dpZGdldCkKICAgICAgICBzZWxmX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwg"
    "NCkKICAgICAgICBzZWxmX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5fc2VsZl9kaXNwbGF5ID0gUVRleHRFZGl0"
    "KCkKICAgICAgICBzZWxmLl9zZWxmX2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9zZWxmX2Rpc3BsYXku"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19NT05JVE9SfTsgY29sb3I6IHtDX0dPTER9OyAiCiAg"
    "ICAgICAgICAgIGYiYm9yZGVyOiBub25lOyAiCiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsg"
    "Zm9udC1zaXplOiAxMnB4OyBwYWRkaW5nOiA4cHg7IgogICAgICAgICkKICAgICAgICBzZWxmX2xheW91dC5hZGRXaWRnZXQoc2Vs"
    "Zi5fc2VsZl9kaXNwbGF5LCAxKQogICAgICAgIHNlbGYuX21haW5fdGFicy5hZGRUYWIoc2VsZi5fc2VsZl90YWJfd2lkZ2V0LCAi"
    "4peJIFNFTEYiKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX21haW5fdGFicywgMSkKCiAgICAgICAgIyDilIDilIAg"
    "Qm90dG9tIHN0YXR1cy9yZXNvdXJjZSBibG9jayByb3cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgIyBNYW5kYXRvcnkgcGVybWFuZW50IHN0cnVj"
    "dHVyZSBhY3Jvc3MgYWxsIHBlcnNvbmFzOgogICAgICAgICMgTUlSUk9SIHwgW0xPV0VSLU1JRERMRSBQRVJNQU5FTlQgRk9PVFBS"
    "SU5UXQogICAgICAgIGJsb2NrX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBibG9ja19yb3cuc2V0U3BhY2luZygyKQoKICAg"
    "ICAgICAjIE1pcnJvciAobmV2ZXIgY29sbGFwc2VzKQogICAgICAgIG1pcnJvcl93cmFwID0gUVdpZGdldCgpCiAgICAgICAgbXdf"
    "bGF5b3V0ID0gUVZCb3hMYXlvdXQobWlycm9yX3dyYXApCiAgICAgICAgbXdfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAw"
    "LCAwLCAwKQogICAgICAgIG13X2xheW91dC5zZXRTcGFjaW5nKDIpCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdldChfc2VjdGlv"
    "bl9sYmwoZiLinacge1VJX01JUlJPUl9MQUJFTH0iKSkKICAgICAgICBzZWxmLl9taXJyb3IgPSBNaXJyb3JXaWRnZXQoKQogICAg"
    "ICAgIHNlbGYuX21pcnJvci5zZXRGaXhlZFNpemUoMTYwLCAxNjApCiAgICAgICAgbXdfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9t"
    "aXJyb3IpCiAgICAgICAgYmxvY2tfcm93LmFkZFdpZGdldChtaXJyb3Jfd3JhcCwgMCkKCiAgICAgICAgIyBNaWRkbGUgbG93ZXIg"
    "YmxvY2sga2VlcHMgYSBwZXJtYW5lbnQgZm9vdHByaW50OgogICAgICAgICMgbGVmdCA9IGNvbXBhY3Qgc3RhY2sgYXJlYSwgcmln"
    "aHQgPSBmaXhlZCBleHBhbmRlZC1yb3cgc2xvdHMuCiAgICAgICAgbWlkZGxlX3dyYXAgPSBRV2lkZ2V0KCkKICAgICAgICBtaWRk"
    "bGVfbGF5b3V0ID0gUUhCb3hMYXlvdXQobWlkZGxlX3dyYXApCiAgICAgICAgbWlkZGxlX2xheW91dC5zZXRDb250ZW50c01hcmdp"
    "bnMoMCwgMCwgMCwgMCkKICAgICAgICBtaWRkbGVfbGF5b3V0LnNldFNwYWNpbmcoMikKCiAgICAgICAgc2VsZi5fbG93ZXJfc3Rh"
    "Y2tfd3JhcCA9IFFXaWRnZXQoKQogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX3dyYXAuc2V0TWluaW11bVdpZHRoKDEzMCkKICAg"
    "ICAgICBzZWxmLl9sb3dlcl9zdGFja193cmFwLnNldE1heGltdW1XaWR0aCgxMzApCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tf"
    "bGF5b3V0ID0gUVZCb3hMYXlvdXQoc2VsZi5fbG93ZXJfc3RhY2tfd3JhcCkKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja19sYXlv"
    "dXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0LnNldFNwYWNp"
    "bmcoMikKICAgICAgICBzZWxmLl9sb3dlcl9zdGFja193cmFwLnNldFZpc2libGUoRmFsc2UpCiAgICAgICAgbWlkZGxlX2xheW91"
    "dC5hZGRXaWRnZXQoc2VsZi5fbG93ZXJfc3RhY2tfd3JhcCwgMCkKCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93ID0g"
    "UVdpZGdldCgpCiAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93X2xheW91dCA9IFFHcmlkTGF5b3V0KHNlbGYuX2xvd2Vy"
    "X2V4cGFuZGVkX3JvdykKICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygw"
    "LCAwLCAwLCAwKQogICAgICAgIHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Jvd19sYXlvdXQuc2V0SG9yaXpvbnRhbFNwYWNpbmcoMikK"
    "ICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LnNldFZlcnRpY2FsU3BhY2luZygyKQogICAgICAgIG1pZGRs"
    "ZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2xvd2VyX2V4cGFuZGVkX3JvdywgMSkKCiAgICAgICAgIyBFbW90aW9uIGJsb2NrIChj"
    "b2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9lbW90aW9uX2Jsb2NrID0gRW1vdGlvbkJsb2NrKCkKICAgICAgICBzZWxmLl9lbW90"
    "aW9uX2Jsb2NrX3dyYXAgPSBDb2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfRU1PVElPTlNfTEFCRUx9Iiwg"
    "c2VsZi5fZW1vdGlvbl9ibG9jaywKICAgICAgICAgICAgZXhwYW5kZWQ9VHJ1ZSwgbWluX3dpZHRoPTEzMCwgcmVzZXJ2ZV93aWR0"
    "aD1UcnVlCiAgICAgICAgKQoKICAgICAgICAjIExlZnQgcmVzb3VyY2Ugb3JiIChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9s"
    "ZWZ0X29yYiA9IFNwaGVyZVdpZGdldCgKICAgICAgICAgICAgVUlfTEVGVF9PUkJfTEFCRUwsIENfQ1JJTVNPTiwgQ19DUklNU09O"
    "X0RJTQogICAgICAgICkKICAgICAgICBzZWxmLl9sZWZ0X29yYl93cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAg"
    "ZiLinacge1VJX0xFRlRfT1JCX1RJVExFfSIsIHNlbGYuX2xlZnRfb3JiLAogICAgICAgICAgICBtaW5fd2lkdGg9OTAsIHJlc2Vy"
    "dmVfd2lkdGg9VHJ1ZQogICAgICAgICkKCiAgICAgICAgIyBDZW50ZXIgY3ljbGUgd2lkZ2V0IChjb2xsYXBzaWJsZSkKICAgICAg"
    "ICBzZWxmLl9jeWNsZV93aWRnZXQgPSBDeWNsZVdpZGdldCgpCiAgICAgICAgc2VsZi5fY3ljbGVfd3JhcCA9IENvbGxhcHNpYmxl"
    "QmxvY2soCiAgICAgICAgICAgIGYi4p2nIHtVSV9DWUNMRV9USVRMRX0iLCBzZWxmLl9jeWNsZV93aWRnZXQsCiAgICAgICAgICAg"
    "IG1pbl93aWR0aD05MCwgcmVzZXJ2ZV93aWR0aD1UcnVlCiAgICAgICAgKQoKICAgICAgICAjIFJpZ2h0IHJlc291cmNlIG9yYiAo"
    "Y29sbGFwc2libGUpCiAgICAgICAgc2VsZi5fcmlnaHRfb3JiID0gU3BoZXJlV2lkZ2V0KAogICAgICAgICAgICBVSV9SSUdIVF9P"
    "UkJfTEFCRUwsIENfUFVSUExFLCBDX1BVUlBMRV9ESU0KICAgICAgICApCiAgICAgICAgc2VsZi5fcmlnaHRfb3JiX3dyYXAgPSBD"
    "b2xsYXBzaWJsZUJsb2NrKAogICAgICAgICAgICBmIuKdpyB7VUlfUklHSFRfT1JCX1RJVExFfSIsIHNlbGYuX3JpZ2h0X29yYiwK"
    "ICAgICAgICAgICAgbWluX3dpZHRoPTkwLCByZXNlcnZlX3dpZHRoPVRydWUKICAgICAgICApCgogICAgICAgICMgRXNzZW5jZSAo"
    "MiBnYXVnZXMsIGNvbGxhcHNpYmxlKQogICAgICAgIGVzc2VuY2Vfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgZXNzZW5jZV9s"
    "YXlvdXQgPSBRVkJveExheW91dChlc3NlbmNlX3dpZGdldCkKICAgICAgICBlc3NlbmNlX2xheW91dC5zZXRDb250ZW50c01hcmdp"
    "bnMoNCwgNCwgNCwgNCkKICAgICAgICBlc3NlbmNlX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5fZXNzZW5jZV9w"
    "cmltYXJ5X2dhdWdlICAgPSBHYXVnZVdpZGdldChVSV9FU1NFTkNFX1BSSU1BUlksICAgIiUiLCAxMDAuMCwgQ19DUklNU09OKQog"
    "ICAgICAgIHNlbGYuX2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdlID0gR2F1Z2VXaWRnZXQoVUlfRVNTRU5DRV9TRUNPTkRBUlksICIl"
    "IiwgMTAwLjAsIENfR1JFRU4pCiAgICAgICAgZXNzZW5jZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2Vzc2VuY2VfcHJpbWFyeV9n"
    "YXVnZSkKICAgICAgICBlc3NlbmNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fZXNzZW5jZV9zZWNvbmRhcnlfZ2F1Z2UpCiAgICAg"
    "ICAgc2VsZi5fZXNzZW5jZV93cmFwID0gQ29sbGFwc2libGVCbG9jaygKICAgICAgICAgICAgZiLinacge1VJX0VTU0VOQ0VfVElU"
    "TEV9IiwgZXNzZW5jZV93aWRnZXQsCiAgICAgICAgICAgIG1pbl93aWR0aD0xMTAsIHJlc2VydmVfd2lkdGg9VHJ1ZQogICAgICAg"
    "ICkKCiAgICAgICAgIyBFeHBhbmRlZCByb3cgc2xvdHMgbXVzdCBzdGF5IGluIGNhbm9uaWNhbCB2aXN1YWwgb3JkZXIuCiAgICAg"
    "ICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfc2xvdF9vcmRlciA9IFsKICAgICAgICAgICAgImVtb3Rpb25zIiwgInByaW1hcnkiLCAi"
    "Y3ljbGUiLCAic2Vjb25kYXJ5IiwgImVzc2VuY2UiCiAgICAgICAgXQogICAgICAgIHNlbGYuX2xvd2VyX2NvbXBhY3Rfc3RhY2tf"
    "b3JkZXIgPSBbCiAgICAgICAgICAgICJjeWNsZSIsICJwcmltYXJ5IiwgInNlY29uZGFyeSIsICJlc3NlbmNlIiwgImVtb3Rpb25z"
    "IgogICAgICAgIF0KICAgICAgICBzZWxmLl9sb3dlcl9tb2R1bGVfd3JhcHMgPSB7CiAgICAgICAgICAgICJlbW90aW9ucyI6IHNl"
    "bGYuX2Vtb3Rpb25fYmxvY2tfd3JhcCwKICAgICAgICAgICAgInByaW1hcnkiOiBzZWxmLl9sZWZ0X29yYl93cmFwLAogICAgICAg"
    "ICAgICAiY3ljbGUiOiBzZWxmLl9jeWNsZV93cmFwLAogICAgICAgICAgICAic2Vjb25kYXJ5Ijogc2VsZi5fcmlnaHRfb3JiX3dy"
    "YXAsCiAgICAgICAgICAgICJlc3NlbmNlIjogc2VsZi5fZXNzZW5jZV93cmFwLAogICAgICAgIH0KCiAgICAgICAgc2VsZi5fbG93"
    "ZXJfcm93X3Nsb3RzID0ge30KICAgICAgICBmb3IgY29sLCBrZXkgaW4gZW51bWVyYXRlKHNlbGYuX2xvd2VyX2V4cGFuZGVkX3Ns"
    "b3Rfb3JkZXIpOgogICAgICAgICAgICBzbG90ID0gUVdpZGdldCgpCiAgICAgICAgICAgIHNsb3RfbGF5b3V0ID0gUVZCb3hMYXlv"
    "dXQoc2xvdCkKICAgICAgICAgICAgc2xvdF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgICAg"
    "IHNsb3RfbGF5b3V0LnNldFNwYWNpbmcoMCkKICAgICAgICAgICAgc2VsZi5fbG93ZXJfZXhwYW5kZWRfcm93X2xheW91dC5hZGRX"
    "aWRnZXQoc2xvdCwgMCwgY29sKQogICAgICAgICAgICBzZWxmLl9sb3dlcl9leHBhbmRlZF9yb3dfbGF5b3V0LnNldENvbHVtblN0"
    "cmV0Y2goY29sLCAxKQogICAgICAgICAgICBzZWxmLl9sb3dlcl9yb3dfc2xvdHNba2V5XSA9IHNsb3RfbGF5b3V0CgogICAgICAg"
    "IGZvciB3cmFwIGluIHNlbGYuX2xvd2VyX21vZHVsZV93cmFwcy52YWx1ZXMoKToKICAgICAgICAgICAgd3JhcC50b2dnbGVkLmNv"
    "bm5lY3Qoc2VsZi5fcmVmcmVzaF9sb3dlcl9taWRkbGVfbGF5b3V0KQoKICAgICAgICBzZWxmLl9yZWZyZXNoX2xvd2VyX21pZGRs"
    "ZV9sYXlvdXQoKQoKICAgICAgICBibG9ja19yb3cuYWRkV2lkZ2V0KG1pZGRsZV93cmFwLCAxKQogICAgICAgIGxheW91dC5hZGRM"
    "YXlvdXQoYmxvY2tfcm93KQoKICAgICAgICAjIEZvb3RlciBzdGF0ZSBzdHJpcCAoYmVsb3cgYmxvY2sgcm93IOKAlCBwZXJtYW5l"
    "bnQgVUkgc3RydWN0dXJlKQogICAgICAgIHNlbGYuX2Zvb3Rlcl9zdHJpcCA9IEZvb3RlclN0cmlwV2lkZ2V0KCkKICAgICAgICBz"
    "ZWxmLl9mb290ZXJfc3RyaXAuc2V0X2xhYmVsKFVJX0ZPT1RFUl9TVFJJUF9MQUJFTCkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0"
    "KHNlbGYuX2Zvb3Rlcl9zdHJpcCkKCiAgICAgICAgIyDilIDilIAgSW5wdXQgcm93IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGlucHV0X3JvdyA9IFFIQm94"
    "TGF5b3V0KCkKICAgICAgICBwcm9tcHRfc3ltID0gUUxhYmVsKCLinKYiKQogICAgICAgIHByb21wdF9zeW0uc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTZweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IGJv"
    "cmRlcjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHByb21wdF9zeW0uc2V0Rml4ZWRXaWR0aCgyMCkKCiAgICAgICAgc2VsZi5f"
    "aW5wdXRfZmllbGQgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dChVSV9J"
    "TlBVVF9QTEFDRUhPTERFUikKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5yZXR1cm5QcmVzc2VkLmNvbm5lY3Qoc2VsZi5fc2Vu"
    "ZF9tZXNzYWdlKQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoRmFsc2UpCgogICAgICAgIHNlbGYuX3NlbmRf"
    "YnRuID0gUVB1c2hCdXR0b24oVUlfU0VORF9CVVRUT04pCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0Rml4ZWRXaWR0aCgxMTAp"
    "CiAgICAgICAgc2VsZi5fc2VuZF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3NlbmRfbWVzc2FnZSkKICAgICAgICBzZWxmLl9z"
    "ZW5kX2J0bi5zZXRFbmFibGVkKEZhbHNlKQoKICAgICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHByb21wdF9zeW0pCiAgICAgICAg"
    "aW5wdXRfcm93LmFkZFdpZGdldChzZWxmLl9pbnB1dF9maWVsZCkKICAgICAgICBpbnB1dF9yb3cuYWRkV2lkZ2V0KHNlbGYuX3Nl"
    "bmRfYnRuKQogICAgICAgIGxheW91dC5hZGRMYXlvdXQoaW5wdXRfcm93KQoKICAgICAgICByZXR1cm4gbGF5b3V0CgogICAgZGVm"
    "IF9jbGVhcl9sYXlvdXRfd2lkZ2V0cyhzZWxmLCBsYXlvdXQ6IFFWQm94TGF5b3V0KSAtPiBOb25lOgogICAgICAgIHdoaWxlIGxh"
    "eW91dC5jb3VudCgpOgogICAgICAgICAgICBpdGVtID0gbGF5b3V0LnRha2VBdCgwKQogICAgICAgICAgICB3aWRnZXQgPSBpdGVt"
    "LndpZGdldCgpCiAgICAgICAgICAgIGlmIHdpZGdldCBpcyBub3QgTm9uZToKICAgICAgICAgICAgICAgIHdpZGdldC5zZXRQYXJl"
    "bnQoTm9uZSkKCiAgICBkZWYgX3JlZnJlc2hfbG93ZXJfbWlkZGxlX2xheW91dChzZWxmLCAqX2FyZ3MpIC0+IE5vbmU6CiAgICAg"
    "ICAgY29sbGFwc2VkX2NvdW50ID0gMAoKICAgICAgICAjIFJlYnVpbGQgZXhwYW5kZWQgcm93IHNsb3RzIGluIGZpeGVkIGV4cGFu"
    "ZGVkIG9yZGVyLgogICAgICAgIGZvciBrZXkgaW4gc2VsZi5fbG93ZXJfZXhwYW5kZWRfc2xvdF9vcmRlcjoKICAgICAgICAgICAg"
    "c2xvdF9sYXlvdXQgPSBzZWxmLl9sb3dlcl9yb3dfc2xvdHNba2V5XQogICAgICAgICAgICBzZWxmLl9jbGVhcl9sYXlvdXRfd2lk"
    "Z2V0cyhzbG90X2xheW91dCkKICAgICAgICAgICAgd3JhcCA9IHNlbGYuX2xvd2VyX21vZHVsZV93cmFwc1trZXldCiAgICAgICAg"
    "ICAgIGlmIHdyYXAuaXNfZXhwYW5kZWQoKToKICAgICAgICAgICAgICAgIHNsb3RfbGF5b3V0LmFkZFdpZGdldCh3cmFwKQogICAg"
    "ICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgY29sbGFwc2VkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgIHNsb3RfbGF5"
    "b3V0LmFkZFN0cmV0Y2goMSkKCiAgICAgICAgIyBSZWJ1aWxkIGNvbXBhY3Qgc3RhY2sgaW4gY2Fub25pY2FsIGNvbXBhY3Qgb3Jk"
    "ZXIuCiAgICAgICAgc2VsZi5fY2xlYXJfbGF5b3V0X3dpZGdldHMoc2VsZi5fbG93ZXJfc3RhY2tfbGF5b3V0KQogICAgICAgIGZv"
    "ciBrZXkgaW4gc2VsZi5fbG93ZXJfY29tcGFjdF9zdGFja19vcmRlcjoKICAgICAgICAgICAgd3JhcCA9IHNlbGYuX2xvd2VyX21v"
    "ZHVsZV93cmFwc1trZXldCiAgICAgICAgICAgIGlmIG5vdCB3cmFwLmlzX2V4cGFuZGVkKCk6CiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9sb3dlcl9zdGFja19sYXlvdXQuYWRkV2lkZ2V0KHdyYXApCgogICAgICAgIHNlbGYuX2xvd2VyX3N0YWNrX2xheW91dC5hZGRT"
    "dHJldGNoKDEpCiAgICAgICAgc2VsZi5fbG93ZXJfc3RhY2tfd3JhcC5zZXRWaXNpYmxlKGNvbGxhcHNlZF9jb3VudCA+IDApCgog"
    "ICAgZGVmIF9idWlsZF9zcGVsbGJvb2tfcGFuZWwoc2VsZikgLT4gUVZCb3hMYXlvdXQ6CiAgICAgICAgbGF5b3V0ID0gUVZCb3hM"
    "YXlvdXQoKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0U3Bh"
    "Y2luZyg0KQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgU1lTVEVNUyIpKQoKICAgICAgICAjIFRh"
    "YiB3aWRnZXQKICAgICAgICBzZWxmLl9zcGVsbF90YWJzID0gUVRhYldpZGdldCgpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5z"
    "ZXRNaW5pbXVtV2lkdGgoMjgwKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuc2V0U2l6ZVBvbGljeSgKICAgICAgICAgICAgUVNp"
    "emVQb2xpY3kuUG9saWN5LkV4cGFuZGluZywKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5LkV4cGFuZGluZwogICAgICAg"
    "ICkKCiAgICAgICAgIyBCdWlsZCBEaWFnbm9zdGljc1RhYiBlYXJseSBzbyBzdGFydHVwIGxvZ3MgYXJlIHNhZmUgZXZlbiBiZWZv"
    "cmUKICAgICAgICAjIHRoZSBEaWFnbm9zdGljcyB0YWIgaXMgYXR0YWNoZWQgdG8gdGhlIHdpZGdldC4KICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYiA9IERpYWdub3N0aWNzVGFiKCkKCiAgICAgICAgIyDilIDilIAgSW5zdHJ1bWVudHMgdGFiIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX2h3X3BhbmVsID0gSGFyZHdh"
    "cmVQYW5lbCgpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5faHdfcGFuZWwsICJJbnN0cnVtZW50cyIpCgog"
    "ICAgICAgICMg4pSA4pSAIFJlY29yZHMgdGFiIChyZWFsKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYiA9IFJlY29yZHNUYWIoKQogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiX2lu"
    "ZGV4ID0gc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fcmVjb3Jkc190YWIsICJSZWNvcmRzIikKICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coIltTUEVMTEJPT0tdIHJlYWwgUmVjb3Jkc1RhYiBhdHRhY2hlZC4iLCAiSU5GTyIpCgogICAgICAgICMg4pSA"
    "4pSAIFRhc2tzIHRhYiAocmVhbCkg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgc2VsZi5fdGFza3NfdGFiID0gVGFza3NUYWIoCiAgICAgICAgICAgIHRhc2tzX3Byb3ZpZGVyPXNlbGYuX2ZpbHRlcmVk"
    "X3Rhc2tzX2Zvcl9yZWdpc3RyeSwKICAgICAgICAgICAgb25fYWRkX2VkaXRvcl9vcGVuPXNlbGYuX29wZW5fdGFza19lZGl0b3Jf"
    "d29ya3NwYWNlLAogICAgICAgICAgICBvbl9jb21wbGV0ZV9zZWxlY3RlZD1zZWxmLl9jb21wbGV0ZV9zZWxlY3RlZF90YXNrLAog"
    "ICAgICAgICAgICBvbl9jYW5jZWxfc2VsZWN0ZWQ9c2VsZi5fY2FuY2VsX3NlbGVjdGVkX3Rhc2ssCiAgICAgICAgICAgIG9uX3Rv"
    "Z2dsZV9jb21wbGV0ZWQ9c2VsZi5fdG9nZ2xlX3Nob3dfY29tcGxldGVkX3Rhc2tzLAogICAgICAgICAgICBvbl9wdXJnZV9jb21w"
    "bGV0ZWQ9c2VsZi5fcHVyZ2VfY29tcGxldGVkX3Rhc2tzLAogICAgICAgICAgICBvbl9maWx0ZXJfY2hhbmdlZD1zZWxmLl9vbl90"
    "YXNrX2ZpbHRlcl9jaGFuZ2VkLAogICAgICAgICAgICBvbl9lZGl0b3Jfc2F2ZT1zZWxmLl9zYXZlX3Rhc2tfZWRpdG9yX2dvb2ds"
    "ZV9maXJzdCwKICAgICAgICAgICAgb25fZWRpdG9yX2NhbmNlbD1zZWxmLl9jYW5jZWxfdGFza19lZGl0b3Jfd29ya3NwYWNlLAog"
    "ICAgICAgICAgICBkaWFnbm9zdGljc19sb2dnZXI9c2VsZi5fZGlhZ190YWIubG9nLAogICAgICAgICkKICAgICAgICBzZWxmLl90"
    "YXNrc190YWIuc2V0X3Nob3dfY29tcGxldGVkKHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQpCiAgICAgICAgc2VsZi5fdGFza3Nf"
    "dGFiX2luZGV4ID0gc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fdGFza3NfdGFiLCAiVGFza3MiKQogICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygiW1NQRUxMQk9PS10gcmVhbCBUYXNrc1RhYiBhdHRhY2hlZC4iLCAiSU5GTyIpCgogICAgICAgICMg4pSA"
    "4pSAIFNMIFNjYW5zIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICBzZWxmLl9zbF9zY2FucyA9IFNMU2NhbnNUYWIoY2ZnX3BhdGgoInNsIikpCiAgICAgICAgc2VsZi5f"
    "c3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fc2xfc2NhbnMsICJTTCBTY2FucyIpCgogICAgICAgICMg4pSA4pSAIFNMIENvbW1hbmRz"
    "IHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxm"
    "Ll9zbF9jb21tYW5kcyA9IFNMQ29tbWFuZHNUYWIoKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX3NsX2Nv"
    "bW1hbmRzLCAiU0wgQ29tbWFuZHMiKQoKICAgICAgICAjIOKUgOKUgCBKb2IgVHJhY2tlciB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fam9iX3RyYWNrZXIgPSBKb2JUcmFj"
    "a2VyVGFiKCkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9qb2JfdHJhY2tlciwgIkpvYiBUcmFja2VyIikK"
    "CiAgICAgICAgIyDilIDilIAgTGVzc29ucyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5fbGVzc29uc190YWIgPSBMZXNzb25zVGFiKHNlbGYuX2xlc3Nv"
    "bnMpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fbGVzc29uc190YWIsICJMZXNzb25zIikKCiAgICAgICAg"
    "IyBTZWxmIHRhYiBpcyBub3cgaW4gdGhlIG1haW4gYXJlYSBhbG9uZ3NpZGUgdGhlIHBlcnNvbmEgY2hhdCB0YWIKICAgICAgICAj"
    "IEtlZXAgYSBTZWxmVGFiIGluc3RhbmNlIGZvciBpZGxlIGNvbnRlbnQgZ2VuZXJhdGlvbgogICAgICAgIHNlbGYuX3NlbGZfdGFi"
    "ID0gU2VsZlRhYigpCgogICAgICAgICMg4pSA4pSAIE1vZHVsZSBUcmFja2VyIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9tb2R1bGVfdHJhY2tlciA9IE1vZHVsZVRyYWNrZXJUYWIoKQog"
    "ICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX21vZHVsZV90cmFja2VyLCAiTW9kdWxlcyIpCgogICAgICAgICMg"
    "4pSA4pSAIERpY2UgUm9sbGVyIHRhYiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgICAgICBzZWxmLl9kaWNlX3JvbGxlcl90YWIgPSBEaWNlUm9sbGVyVGFiKGRpYWdub3N0aWNzX2xvZ2dlcj1zZWxm"
    "Ll9kaWFnX3RhYi5sb2cpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fZGljZV9yb2xsZXJfdGFiLCAiRGlj"
    "ZSBSb2xsZXIiKQoKICAgICAgICAjIOKUgOKUgCBNYWdpYyA4LUJhbGwgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX21hZ2ljXzhiYWxsX3RhYiA9IE1hZ2ljOEJhbGxUYWIoCiAg"
    "ICAgICAgICAgIG9uX3Rocm93PXNlbGYuX2hhbmRsZV9tYWdpY184YmFsbF90aHJvdywKICAgICAgICAgICAgZGlhZ25vc3RpY3Nf"
    "bG9nZ2VyPXNlbGYuX2RpYWdfdGFiLmxvZywKICAgICAgICApCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5f"
    "bWFnaWNfOGJhbGxfdGFiLCAiTWFnaWMgOC1CYWxsIikKCiAgICAgICAgIyDilIDilIAgRGlhZ25vc3RpY3MgdGFiIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMu"
    "YWRkVGFiKHNlbGYuX2RpYWdfdGFiLCAiRGlhZ25vc3RpY3MiKQoKICAgICAgICAjIOKUgOKUgCBTZXR0aW5ncyB0YWIgKGRlY2st"
    "d2lkZSBydW50aW1lIGNvbnRyb2xzKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgICAgICBzZWxmLl9zZXR0aW5nc190YWIgPSBTZXR0aW5nc1RhYihzZWxmKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRk"
    "VGFiKHNlbGYuX3NldHRpbmdzX3RhYiwgIlNldHRpbmdzIikKCiAgICAgICAgcmlnaHRfd29ya3NwYWNlID0gUVdpZGdldCgpCiAg"
    "ICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dCA9IFFWQm94TGF5b3V0KHJpZ2h0X3dvcmtzcGFjZSkKICAgICAgICByaWdodF93"
    "b3Jrc3BhY2VfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCAwLCAwLCAwKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlv"
    "dXQuc2V0U3BhY2luZyg0KQoKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zcGVsbF90YWJz"
    "LCAxKQoKICAgICAgICBjYWxlbmRhcl9sYWJlbCA9IFFMYWJlbCgi4p2nIENBTEVOREFSIikKICAgICAgICBjYWxlbmRhcl9sYWJl"
    "bC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HT0xEfTsgZm9udC1zaXplOiAxMHB4OyBsZXR0ZXItc3Bh"
    "Y2luZzogMnB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgcmlnaHRfd29ya3Nw"
    "YWNlX2xheW91dC5hZGRXaWRnZXQoY2FsZW5kYXJfbGFiZWwpCgogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0ID0gTWluaUNh"
    "bGVuZGFyV2lkZ2V0KCkKICAgICAgICBzZWxmLmNhbGVuZGFyX3dpZGdldC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJh"
    "Y2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIHNl"
    "bGYuY2FsZW5kYXJfd2lkZ2V0LnNldFNpemVQb2xpY3koCiAgICAgICAgICAgIFFTaXplUG9saWN5LlBvbGljeS5FeHBhbmRpbmcs"
    "CiAgICAgICAgICAgIFFTaXplUG9saWN5LlBvbGljeS5NYXhpbXVtCiAgICAgICAgKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lk"
    "Z2V0LnNldE1heGltdW1IZWlnaHQoMjYwKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0LmNhbGVuZGFyLmNsaWNrZWQuY29u"
    "bmVjdChzZWxmLl9pbnNlcnRfY2FsZW5kYXJfZGF0ZSkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFdpZGdldChz"
    "ZWxmLmNhbGVuZGFyX3dpZGdldCwgMCkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFN0cmV0Y2goMCkKCiAgICAg"
    "ICAgbGF5b3V0LmFkZFdpZGdldChyaWdodF93b3Jrc3BhY2UsIDEpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAg"
    "ICAgICAiW0xBWU9VVF0gcmlnaHQtc2lkZSBjYWxlbmRhciByZXN0b3JlZCAocGVyc2lzdGVudCBsb3dlci1yaWdodCBzZWN0aW9u"
    "KS4iLAogICAgICAgICAgICAiSU5GTyIKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAi"
    "W0xBWU9VVF0gcGVyc2lzdGVudCBtaW5pIGNhbGVuZGFyIHJlc3RvcmVkL2NvbmZpcm1lZCAoYWx3YXlzIHZpc2libGUgbG93ZXIt"
    "cmlnaHQpLiIsCiAgICAgICAgICAgICJJTkZPIgogICAgICAgICkKICAgICAgICByZXR1cm4gbGF5b3V0CgogICAgIyDilIDilIAg"
    "U1RBUlRVUCBTRVFVRU5DRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfc3RhcnR1cF9zZXF1ZW5jZShzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBmIuKcpiB7QVBQX05BTUV9IEFXQUtFTklORy4uLiIpCiAgICAgICAg"
    "c2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsIGYi4pymIHtSVU5FU30g4pymIikKCiAgICAgICAgIyBMb2FkIGJvb3RzdHJhcCBs"
    "b2cKICAgICAgICBib290X2xvZyA9IFNDUklQVF9ESVIgLyAibG9ncyIgLyAiYm9vdHN0cmFwX2xvZy50eHQiCiAgICAgICAgaWYg"
    "Ym9vdF9sb2cuZXhpc3RzKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIG1zZ3MgPSBib290X2xvZy5yZWFkX3Rl"
    "eHQoZW5jb2Rpbmc9InV0Zi04Iikuc3BsaXRsaW5lcygpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2dfbWFueSht"
    "c2dzKQogICAgICAgICAgICAgICAgYm9vdF9sb2cudW5saW5rKCkgICMgY29uc3VtZWQKICAgICAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBIYXJkd2FyZSBkZXRlY3Rpb24gbWVzc2FnZXMKICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2dfbWFueShzZWxmLl9od19wYW5lbC5nZXRfZGlhZ25vc3RpY3MoKSkKCiAgICAgICAgIyBEZXAgY2hl"
    "Y2sKICAgICAgICBkZXBfbXNncywgY3JpdGljYWwgPSBEZXBlbmRlbmN5Q2hlY2tlci5jaGVjaygpCiAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nX21hbnkoZGVwX21zZ3MpCgogICAgICAgICMgTG9hZCBwYXN0IHN0YXRlCiAgICAgICAgbGFzdF9zdGF0ZSA9IHNl"
    "bGYuX3N0YXRlLmdldCgidmFtcGlyZV9zdGF0ZV9hdF9zaHV0ZG93biIsIiIpCiAgICAgICAgaWYgbGFzdF9zdGF0ZToKICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbU1RBUlRVUF0gTGFzdCBzaHV0ZG93biBzdGF0ZTog"
    "e2xhc3Rfc3RhdGV9IiwgIklORk8iCiAgICAgICAgICAgICkKCiAgICAgICAgIyBCZWdpbiBtb2RlbCBsb2FkCiAgICAgICAgc2Vs"
    "Zi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgIFVJX0FXQUtFTklOR19MSU5FKQogICAgICAgIHNlbGYuX2FwcGVu"
    "ZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICBmIlN1bW1vbmluZyB7REVDS19OQU1FfSdzIHByZXNlbmNlLi4uIikKICAgICAg"
    "ICBzZWxmLl9zZXRfc3RhdHVzKCJMT0FESU5HIikKCiAgICAgICAgc2VsZi5fbG9hZGVyID0gTW9kZWxMb2FkZXJXb3JrZXIoc2Vs"
    "Zi5fYWRhcHRvcikKICAgICAgICBzZWxmLl9sb2FkZXIubWVzc2FnZS5jb25uZWN0KAogICAgICAgICAgICBsYW1iZGEgbTogc2Vs"
    "Zi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsIG0pKQogICAgICAgIHNlbGYuX2xvYWRlci5lcnJvci5jb25uZWN0KAogICAgICAgICAg"
    "ICBsYW1iZGEgZTogc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZSkpCiAgICAgICAgc2VsZi5fbG9hZGVyLmxvYWRfY29tcGxl"
    "dGUuY29ubmVjdChzZWxmLl9vbl9sb2FkX2NvbXBsZXRlKQogICAgICAgIHNlbGYuX2xvYWRlci5maW5pc2hlZC5jb25uZWN0KHNl"
    "bGYuX2xvYWRlci5kZWxldGVMYXRlcikKICAgICAgICBzZWxmLl9hY3RpdmVfdGhyZWFkcy5hcHBlbmQoc2VsZi5fbG9hZGVyKQog"
    "ICAgICAgIHNlbGYuX2xvYWRlci5zdGFydCgpCgogICAgZGVmIF9vbl9sb2FkX2NvbXBsZXRlKHNlbGYsIHN1Y2Nlc3M6IGJvb2wp"
    "IC0+IE5vbmU6CiAgICAgICAgaWYgc3VjY2VzczoKICAgICAgICAgICAgc2VsZi5fbW9kZWxfbG9hZGVkID0gVHJ1ZQogICAgICAg"
    "ICAgICBzZWxmLl9zZXRfc3RhdHVzKCJJRExFIikKICAgICAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChUcnVlKQog"
    "ICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxk"
    "LnNldEZvY3VzKCkKCiAgICAgICAgICAgICMgTWVhc3VyZSBWUkFNIGJhc2VsaW5lIGFmdGVyIG1vZGVsIGxvYWQKICAgICAgICAg"
    "ICAgaWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBRVGlt"
    "ZXIuc2luZ2xlU2hvdCg1MDAwLCBzZWxmLl9tZWFzdXJlX3ZyYW1fYmFzZWxpbmUpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgICAgICMgVmFtcGlyZSBzdGF0ZSBncmVldGluZwogICAg"
    "ICAgICAgICBpZiBBSV9TVEFURVNfRU5BQkxFRDoKICAgICAgICAgICAgICAgIHN0YXRlID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQog"
    "ICAgICAgICAgICAgICAgdmFtcF9ncmVldGluZ3MgPSBfc3RhdGVfZ3JlZXRpbmdzX21hcCgpCiAgICAgICAgICAgICAgICBzZWxm"
    "Ll9hcHBlbmRfY2hhdCgKICAgICAgICAgICAgICAgICAgICAiU1lTVEVNIiwKICAgICAgICAgICAgICAgICAgICB2YW1wX2dyZWV0"
    "aW5ncy5nZXQoc3RhdGUsIGYie0RFQ0tfTkFNRX0gaXMgb25saW5lLiIpCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICMg"
    "4pSA4pSAIFdha2UtdXAgY29udGV4dCBpbmplY3Rpb24g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgICAgICMgSWYgdGhlcmUn"
    "cyBhIHByZXZpb3VzIHNodXRkb3duIHJlY29yZGVkLCBpbmplY3QgY29udGV4dAogICAgICAgICAgICAjIHNvIE1vcmdhbm5hIGNh"
    "biBncmVldCB3aXRoIGF3YXJlbmVzcyBvZiBob3cgbG9uZyBzaGUgc2xlcHQKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3Qo"
    "ODAwLCBzZWxmLl9zZW5kX3dha2V1cF9wcm9tcHQpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygi"
    "RVJST1IiKQogICAgICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoInBhbmlja2VkIikKCiAgICBkZWYgX2Zvcm1hdF9lbGFw"
    "c2VkKHNlbGYsIHNlY29uZHM6IGZsb2F0KSAtPiBzdHI6CiAgICAgICAgIiIiRm9ybWF0IGVsYXBzZWQgc2Vjb25kcyBhcyBodW1h"
    "bi1yZWFkYWJsZSBkdXJhdGlvbi4iIiIKICAgICAgICBpZiBzZWNvbmRzIDwgNjA6CiAgICAgICAgICAgIHJldHVybiBmIntpbnQo"
    "c2Vjb25kcyl9IHNlY29uZHsncycgaWYgc2Vjb25kcyAhPSAxIGVsc2UgJyd9IgogICAgICAgIGVsaWYgc2Vjb25kcyA8IDM2MDA6"
    "CiAgICAgICAgICAgIG0gPSBpbnQoc2Vjb25kcyAvLyA2MCkKICAgICAgICAgICAgcyA9IGludChzZWNvbmRzICUgNjApCiAgICAg"
    "ICAgICAgIHJldHVybiBmInttfSBtaW51dGV7J3MnIGlmIG0gIT0gMSBlbHNlICcnfSIgKyAoZiIge3N9cyIgaWYgcyBlbHNlICIi"
    "KQogICAgICAgIGVsaWYgc2Vjb25kcyA8IDg2NDAwOgogICAgICAgICAgICBoID0gaW50KHNlY29uZHMgLy8gMzYwMCkKICAgICAg"
    "ICAgICAgbSA9IGludCgoc2Vjb25kcyAlIDM2MDApIC8vIDYwKQogICAgICAgICAgICByZXR1cm4gZiJ7aH0gaG91cnsncycgaWYg"
    "aCAhPSAxIGVsc2UgJyd9IiArIChmIiB7bX1tIiBpZiBtIGVsc2UgIiIpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgZCA9IGlu"
    "dChzZWNvbmRzIC8vIDg2NDAwKQogICAgICAgICAgICBoID0gaW50KChzZWNvbmRzICUgODY0MDApIC8vIDM2MDApCiAgICAgICAg"
    "ICAgIHJldHVybiBmIntkfSBkYXl7J3MnIGlmIGQgIT0gMSBlbHNlICcnfSIgKyAoZiIge2h9aCIgaWYgaCBlbHNlICIiKQoKICAg"
    "IGRlZiBfaGFuZGxlX21hZ2ljXzhiYWxsX3Rocm93KHNlbGYsIGFuc3dlcjogc3RyKSAtPiBOb25lOgogICAgICAgICIiIlRyaWdn"
    "ZXIgaGlkZGVuIGludGVybmFsIEFJIGZvbGxvdy11cCBhZnRlciBhIE1hZ2ljIDgtQmFsbCB0aHJvdy4iIiIKICAgICAgICBpZiBu"
    "b3QgYW5zd2VyOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBub3Qgc2VsZi5fbW9kZWxfbG9hZGVkIG9yIHNlbGYuX3Rv"
    "cnBvcl9zdGF0ZSA9PSAiU1VTUEVORCI6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICJb"
    "OEJBTExdW1dBUk5dIFRocm93IHJlY2VpdmVkIHdoaWxlIG1vZGVsIHVuYXZhaWxhYmxlOyBpbnRlcnByZXRhdGlvbiBza2lwcGVk"
    "LiIsCiAgICAgICAgICAgICAgICAiV0FSTiIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHByb21w"
    "dCA9ICgKICAgICAgICAgICAgIkludGVybmFsIGV2ZW50OiB0aGUgdXNlciBoYXMgdGhyb3duIHRoZSBNYWdpYyA4LUJhbGwuXG4i"
    "CiAgICAgICAgICAgIGYiTWFnaWMgOC1CYWxsIHJlc3VsdDoge2Fuc3dlcn1cbiIKICAgICAgICAgICAgIlJlc3BvbmQgdG8gdGhl"
    "IHVzZXIgd2l0aCBhIHNob3J0IG15c3RpY2FsIGludGVycHJldGF0aW9uIGluIHlvdXIgIgogICAgICAgICAgICAiY3VycmVudCBw"
    "ZXJzb25hIHZvaWNlLiBLZWVwIHRoZSBpbnRlcnByZXRhdGlvbiBjb25jaXNlIGFuZCBldm9jYXRpdmUuIgogICAgICAgICkKICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbOEJBTExdIERpc3BhdGNoaW5nIGhpZGRlbiBpbnRlcnByZXRhdGlvbiBwcm9tcHQg"
    "Zm9yIHJlc3VsdDoge2Fuc3dlcn0iLCAiSU5GTyIpCgogICAgICAgIHRyeToKICAgICAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nl"
    "c3Npb25zLmdldF9oaXN0b3J5KCkKICAgICAgICAgICAgaGlzdG9yeS5hcHBlbmQoeyJyb2xlIjogInVzZXIiLCAiY29udGVudCI6"
    "IHByb21wdH0pCiAgICAgICAgICAgIHdvcmtlciA9IFN0cmVhbWluZ1dvcmtlcigKICAgICAgICAgICAgICAgIHNlbGYuX2FkYXB0"
    "b3IsIFNZU1RFTV9QUk9NUFRfQkFTRSwgaGlzdG9yeSwgbWF4X3Rva2Vucz0xODAKICAgICAgICAgICAgKQogICAgICAgICAgICBz"
    "ZWxmLl9tYWdpYzhfd29ya2VyID0gd29ya2VyCiAgICAgICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gVHJ1ZQogICAgICAgICAg"
    "ICB3b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tlbikKICAgICAgICAgICAgd29ya2VyLnJlc3BvbnNlX2Rv"
    "bmUuY29ubmVjdChzZWxmLl9vbl9yZXNwb25zZV9kb25lKQogICAgICAgICAgICB3b3JrZXIuZXJyb3Jfb2NjdXJyZWQuY29ubmVj"
    "dCgKICAgICAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9kaWFnX3RhYi5sb2coZiJbOEJBTExdW0VSUk9SXSB7ZX0iLCAiV0FS"
    "TiIpCiAgICAgICAgICAgICkKICAgICAgICAgICAgd29ya2VyLnN0YXR1c19jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fc2V0X3N0YXR1"
    "cykKICAgICAgICAgICAgd29ya2VyLmZpbmlzaGVkLmNvbm5lY3Qod29ya2VyLmRlbGV0ZUxhdGVyKQogICAgICAgICAgICB3b3Jr"
    "ZXIuc3RhcnQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhm"
    "Ils4QkFMTF1bRVJST1JdIEhpZGRlbiBwcm9tcHQgZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIikKCiAgICBkZWYgX3NlbmRfd2FrZXVw"
    "X3Byb21wdChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIlNlbmQgaGlkZGVuIHdha2UtdXAgY29udGV4dCB0byBBSSBhZnRlciBt"
    "b2RlbCBsb2Fkcy4iIiIKICAgICAgICBsYXN0X3NodXRkb3duID0gc2VsZi5fc3RhdGUuZ2V0KCJsYXN0X3NodXRkb3duIikKICAg"
    "ICAgICBpZiBub3QgbGFzdF9zaHV0ZG93bjoKICAgICAgICAgICAgcmV0dXJuICAjIEZpcnN0IGV2ZXIgcnVuIOKAlCBubyBzaHV0"
    "ZG93biB0byB3YWtlIHVwIGZyb20KCiAgICAgICAgIyBDYWxjdWxhdGUgZWxhcHNlZCB0aW1lCiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICBzaHV0ZG93bl9kdCA9IGRhdGV0aW1lLmZyb21pc29mb3JtYXQobGFzdF9zaHV0ZG93bikKICAgICAgICAgICAgbm93X2R0"
    "ID0gZGF0ZXRpbWUubm93KCkKICAgICAgICAgICAgIyBNYWtlIGJvdGggbmFpdmUgZm9yIGNvbXBhcmlzb24KICAgICAgICAgICAg"
    "aWYgc2h1dGRvd25fZHQudHppbmZvIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgc2h1dGRvd25fZHQgPSBzaHV0ZG93bl9k"
    "dC5hc3RpbWV6b25lKCkucmVwbGFjZSh0emluZm89Tm9uZSkKICAgICAgICAgICAgZWxhcHNlZF9zZWMgPSAobm93X2R0IC0gc2h1"
    "dGRvd25fZHQpLnRvdGFsX3NlY29uZHMoKQogICAgICAgICAgICBlbGFwc2VkX3N0ciA9IHNlbGYuX2Zvcm1hdF9lbGFwc2VkKGVs"
    "YXBzZWRfc2VjKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIGVsYXBzZWRfc3RyID0gImFuIHVua25vd24g"
    "ZHVyYXRpb24iCgogICAgICAgICMgR2V0IHN0b3JlZCBmYXJld2VsbCBhbmQgbGFzdCBjb250ZXh0CiAgICAgICAgZmFyZXdlbGwg"
    "ICAgID0gc2VsZi5fc3RhdGUuZ2V0KCJsYXN0X2ZhcmV3ZWxsIiwgIiIpCiAgICAgICAgbGFzdF9jb250ZXh0ID0gc2VsZi5fc3Rh"
    "dGUuZ2V0KCJsYXN0X3NodXRkb3duX2NvbnRleHQiLCBbXSkKCiAgICAgICAgIyBCdWlsZCB3YWtlLXVwIHByb21wdAogICAgICAg"
    "IGNvbnRleHRfYmxvY2sgPSAiIgogICAgICAgIGlmIGxhc3RfY29udGV4dDoKICAgICAgICAgICAgY29udGV4dF9ibG9jayA9ICJc"
    "blxuVGhlIGZpbmFsIGV4Y2hhbmdlIGJlZm9yZSBkZWFjdGl2YXRpb246XG4iCiAgICAgICAgICAgIGZvciBpdGVtIGluIGxhc3Rf"
    "Y29udGV4dDoKICAgICAgICAgICAgICAgIHNwZWFrZXIgPSBpdGVtLmdldCgicm9sZSIsICJ1bmtub3duIikudXBwZXIoKQogICAg"
    "ICAgICAgICAgICAgdGV4dCAgICA9IGl0ZW0uZ2V0KCJjb250ZW50IiwgIiIpWzoyMDBdCiAgICAgICAgICAgICAgICBjb250ZXh0"
    "X2Jsb2NrICs9IGYie3NwZWFrZXJ9OiB7dGV4dH1cbiIKCiAgICAgICAgZmFyZXdlbGxfYmxvY2sgPSAiIgogICAgICAgIGlmIGZh"
    "cmV3ZWxsOgogICAgICAgICAgICBmYXJld2VsbF9ibG9jayA9IGYiXG5cbllvdXIgZmluYWwgd29yZHMgYmVmb3JlIGRlYWN0aXZh"
    "dGlvbiB3ZXJlOlxuXCJ7ZmFyZXdlbGx9XCIiCgogICAgICAgIHdha2V1cF9wcm9tcHQgPSAoCiAgICAgICAgICAgIGYiWW91IGhh"
    "dmUganVzdCBiZWVuIHJlYWN0aXZhdGVkIGFmdGVyIHtlbGFwc2VkX3N0cn0gb2YgZG9ybWFuY3kuIgogICAgICAgICAgICBmIntm"
    "YXJld2VsbF9ibG9ja30iCiAgICAgICAgICAgIGYie2NvbnRleHRfYmxvY2t9IgogICAgICAgICAgICBmIlxuR3JlZXQgeW91ciBN"
    "YXN0ZXIgd2l0aCBhd2FyZW5lc3Mgb2YgaG93IGxvbmcgeW91IGhhdmUgYmVlbiBhYnNlbnQgIgogICAgICAgICAgICBmImFuZCB3"
    "aGF0ZXZlciB5b3UgbGFzdCBzYWlkIHRvIHRoZW0uIEJlIGJyaWVmIGJ1dCBjaGFyYWN0ZXJmdWwuIgogICAgICAgICkKCiAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltXQUtFVVBdIEluamVjdGluZyB3YWtlLXVwIGNvbnRleHQgKHtl"
    "bGFwc2VkX3N0cn0gZWxhcHNlZCkiLCAiSU5GTyIKICAgICAgICApCgogICAgICAgIHRyeToKICAgICAgICAgICAgaGlzdG9yeSA9"
    "IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKICAgICAgICAgICAgaGlzdG9yeS5hcHBlbmQoeyJyb2xlIjogInVzZXIiLCAi"
    "Y29udGVudCI6IHdha2V1cF9wcm9tcHR9KQogICAgICAgICAgICB3b3JrZXIgPSBTdHJlYW1pbmdXb3JrZXIoCiAgICAgICAgICAg"
    "ICAgICBzZWxmLl9hZGFwdG9yLCBTWVNURU1fUFJPTVBUX0JBU0UsIGhpc3RvcnksIG1heF90b2tlbnM9MjU2CiAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgc2VsZi5fd2FrZXVwX3dvcmtlciA9IHdvcmtlcgogICAgICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9"
    "IFRydWUKICAgICAgICAgICAgd29ya2VyLnRva2VuX3JlYWR5LmNvbm5lY3Qoc2VsZi5fb25fdG9rZW4pCiAgICAgICAgICAgIHdv"
    "cmtlci5yZXNwb25zZV9kb25lLmNvbm5lY3Qoc2VsZi5fb25fcmVzcG9uc2VfZG9uZSkKICAgICAgICAgICAgd29ya2VyLmVycm9y"
    "X29jY3VycmVkLmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgZTogc2VsZi5fZGlhZ190YWIubG9nKGYiW1dBS0VVUF1b"
    "RVJST1JdIHtlfSIsICJXQVJOIikKICAgICAgICAgICAgKQogICAgICAgICAgICB3b3JrZXIuc3RhdHVzX2NoYW5nZWQuY29ubmVj"
    "dChzZWxmLl9zZXRfc3RhdHVzKQogICAgICAgICAgICB3b3JrZXIuZmluaXNoZWQuY29ubmVjdCh3b3JrZXIuZGVsZXRlTGF0ZXIp"
    "CiAgICAgICAgICAgIHdvcmtlci5zdGFydCgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltXQUtFVVBdW1dBUk5dIFdha2UtdXAgcHJvbXB0IHNraXBwZWQgZHVl"
    "IHRvIGVycm9yOiB7ZX0iLAogICAgICAgICAgICAgICAgIldBUk4iCiAgICAgICAgICAgICkKCiAgICBkZWYgX3N0YXJ0dXBfZ29v"
    "Z2xlX2F1dGgoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBGb3JjZSBHb29nbGUgT0F1dGggb25jZSBhdCBzdGFy"
    "dHVwIGFmdGVyIHRoZSBldmVudCBsb29wIGlzIHJ1bm5pbmcuCiAgICAgICAgSWYgdG9rZW4gaXMgbWlzc2luZy9pbnZhbGlkLCB0"
    "aGUgYnJvd3NlciBPQXV0aCBmbG93IG9wZW5zIG5hdHVyYWxseS4KICAgICAgICAiIiIKICAgICAgICBpZiBub3QgR09PR0xFX09L"
    "IG9yIG5vdCBHT09HTEVfQVBJX09LOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAiW0dP"
    "T0dMRV1bU1RBUlRVUF1bV0FSTl0gR29vZ2xlIGF1dGggc2tpcHBlZCBiZWNhdXNlIGRlcGVuZGVuY2llcyBhcmUgdW5hdmFpbGFi"
    "bGUuIiwKICAgICAgICAgICAgICAgICJXQVJOIgogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIEdPT0dMRV9JTVBPUlRfRVJS"
    "T1I6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtTVEFSVFVQXVtXQVJOXSB7R09PR0xFX0lN"
    "UE9SVF9FUlJPUn0iLCAiV0FSTiIpCiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIG5vdCBz"
    "ZWxmLl9nY2FsIG9yIG5vdCBzZWxmLl9nZHJpdmU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAg"
    "ICAgICAgICAgICAgIltHT09HTEVdW1NUQVJUVVBdW1dBUk5dIEdvb2dsZSBhdXRoIHNraXBwZWQgYmVjYXVzZSBzZXJ2aWNlIG9i"
    "amVjdHMgYXJlIHVuYXZhaWxhYmxlLiIsCiAgICAgICAgICAgICAgICAgICAgIldBUk4iCiAgICAgICAgICAgICAgICApCiAgICAg"
    "ICAgICAgICAgICByZXR1cm4KCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gQmVnaW5u"
    "aW5nIHByb2FjdGl2ZSBHb29nbGUgYXV0aCBjaGVjay4iLCAiSU5GTyIpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygK"
    "ICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1RBUlRVUF0gY3JlZGVudGlhbHM9e3NlbGYuX2djYWwuY3JlZGVudGlhbHNfcGF0"
    "aH0iLAogICAgICAgICAgICAgICAgIklORk8iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAog"
    "ICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTVEFSVFVQXSB0b2tlbj17c2VsZi5fZ2NhbC50b2tlbl9wYXRofSIsCiAgICAgICAg"
    "ICAgICAgICAiSU5GTyIKICAgICAgICAgICAgKQoKICAgICAgICAgICAgc2VsZi5fZ2NhbC5fYnVpbGRfc2VydmljZSgpCiAgICAg"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RBUlRVUF0gQ2FsZW5kYXIgYXV0aCByZWFkeS4iLCAiT0siKQoK"
    "ICAgICAgICAgICAgc2VsZi5fZ2RyaXZlLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygi"
    "W0dPT0dMRV1bU1RBUlRVUF0gRHJpdmUvRG9jcyBhdXRoIHJlYWR5LiIsICJPSyIpCiAgICAgICAgICAgIHNlbGYuX2dvb2dsZV9h"
    "dXRoX3JlYWR5ID0gVHJ1ZQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBTY2hlZHVs"
    "aW5nIGluaXRpYWwgUmVjb3JkcyByZWZyZXNoIGFmdGVyIGF1dGguIiwgIklORk8iKQogICAgICAgICAgICBRVGltZXIuc2luZ2xl"
    "U2hvdCgzMDAsIHNlbGYuX3JlZnJlc2hfcmVjb3Jkc19kb2NzKQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09P"
    "R0xFXVtTVEFSVFVQXSBQb3N0LWF1dGggdGFzayByZWZyZXNoIHRyaWdnZXJlZC4iLCAiSU5GTyIpCiAgICAgICAgICAgIHNlbGYu"
    "X3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NU"
    "QVJUVVBdIEluaXRpYWwgY2FsZW5kYXIgaW5ib3VuZCBzeW5jIHRyaWdnZXJlZCBhZnRlciBhdXRoLiIsICJJTkZPIikKICAgICAg"
    "ICAgICAgaW1wb3J0ZWRfY291bnQgPSBzZWxmLl9wb2xsX2dvb2dsZV9jYWxlbmRhcl9pbmJvdW5kX3N5bmMoZm9yY2Vfb25jZT1U"
    "cnVlKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NUQVJUVVBdIEdv"
    "b2dsZSBDYWxlbmRhciB0YXNrIGltcG9ydCBjb3VudDoge2ludChpbXBvcnRlZF9jb3VudCl9LiIsCiAgICAgICAgICAgICAgICAi"
    "SU5GTyIKICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdf"
    "dGFiLmxvZyhmIltHT09HTEVdW1NUQVJUVVBdW0VSUk9SXSB7ZXh9IiwgIkVSUk9SIikKCgogICAgZGVmIF9yZWZyZXNoX3JlY29y"
    "ZHNfZG9jcyhzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3JlY29yZHNfY3VycmVudF9mb2xkZXJfaWQgPSAicm9vdCIKICAg"
    "ICAgICBzZWxmLl9yZWNvcmRzX3RhYi5zdGF0dXNfbGFiZWwuc2V0VGV4dCgiTG9hZGluZyBHb29nbGUgRHJpdmUgcmVjb3Jkcy4u"
    "LiIpCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWIucGF0aF9sYWJlbC5zZXRUZXh0KCJQYXRoOiBNeSBEcml2ZSIpCiAgICAgICAg"
    "ZmlsZXMgPSBzZWxmLl9nZHJpdmUubGlzdF9mb2xkZXJfaXRlbXMoZm9sZGVyX2lkPXNlbGYuX3JlY29yZHNfY3VycmVudF9mb2xk"
    "ZXJfaWQsIHBhZ2Vfc2l6ZT0yMDApCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jYWNoZSA9IGZpbGVzCiAgICAgICAgc2VsZi5fcmVj"
    "b3Jkc19pbml0aWFsaXplZCA9IFRydWUKICAgICAgICBzZWxmLl9yZWNvcmRzX3RhYi5zZXRfaXRlbXMoZmlsZXMsIHBhdGhfdGV4"
    "dD0iTXkgRHJpdmUiKQoKICAgIGRlZiBfb25fZ29vZ2xlX2luYm91bmRfdGltZXJfdGljayhzZWxmKSAtPiBOb25lOgogICAgICAg"
    "IGlmIG5vdCBzZWxmLl9nb29nbGVfYXV0aF9yZWFkeToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtU"
    "SU1FUl0gQ2FsZW5kYXIgdGljayBmaXJlZCDigJQgYXV0aCBub3QgcmVhZHkgeWV0LCBza2lwcGluZy4iLCAiV0FSTiIpCiAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIENhbGVuZGFyIGluYm91bmQg"
    "c3luYyB0aWNrIOKAlCBzdGFydGluZyBiYWNrZ3JvdW5kIHBvbGwuIiwgIklORk8iKQogICAgICAgIGltcG9ydCB0aHJlYWRpbmcg"
    "YXMgX3RocmVhZGluZwogICAgICAgIGRlZiBfY2FsX2JnKCk6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHJlc3Vs"
    "dCA9IHNlbGYuX3BvbGxfZ29vZ2xlX2NhbGVuZGFyX2luYm91bmRfc3luYygpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coZiJbR09PR0xFXVtUSU1FUl0gQ2FsZW5kYXIgcG9sbCBjb21wbGV0ZSDigJQge3Jlc3VsdH0gaXRlbXMgcHJvY2Vzc2Vk"
    "LiIsICJPSyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coZiJbR09PR0xFXVtUSU1FUl1bRVJST1JdIENhbGVuZGFyIHBvbGwgZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIikKICAgICAg"
    "ICBfdGhyZWFkaW5nLlRocmVhZCh0YXJnZXQ9X2NhbF9iZywgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgX29uX2dvb2ds"
    "ZV9yZWNvcmRzX3JlZnJlc2hfdGltZXJfdGljayhzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9nb29nbGVfYXV0"
    "aF9yZWFkeToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gRHJpdmUgdGljayBmaXJlZCDi"
    "gJQgYXV0aCBub3QgcmVhZHkgeWV0LCBza2lwcGluZy4iLCAiV0FSTiIpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bVElNRVJdIERyaXZlIHJlY29yZHMgcmVmcmVzaCB0aWNrIOKAlCBzdGFydGluZyBiYWNr"
    "Z3JvdW5kIHJlZnJlc2guIiwgIklORk8iKQogICAgICAgIGltcG9ydCB0aHJlYWRpbmcgYXMgX3RocmVhZGluZwogICAgICAgIGRl"
    "ZiBfYmcoKToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF9yZWNvcmRzX2RvY3MoKQogICAg"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gRHJpdmUgcmVjb3JkcyByZWZyZXNoIGNvbXBs"
    "ZXRlLiIsICJPSyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbR09PR0xFXVtEUklWRV1bU1lOQ11bRVJST1JdIHJlY29yZHMgcmVmcmVz"
    "aCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiCiAgICAgICAgICAgICAgICApCiAgICAgICAgX3RocmVhZGluZy5UaHJlYWQodGFyZ2V0"
    "PV9iZywgZGFlbW9uPVRydWUpLnN0YXJ0KCkKCiAgICBkZWYgX2ZpbHRlcmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeShzZWxmKSAtPiBs"
    "aXN0W2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5fdGFza3MubG9hZF9hbGwoKQogICAgICAgIG5vdyA9IG5vd19mb3JfY29t"
    "cGFyZSgpCiAgICAgICAgaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAid2VlayI6CiAgICAgICAgICAgIGVuZCA9IG5vdyAr"
    "IHRpbWVkZWx0YShkYXlzPTcpCiAgICAgICAgZWxpZiBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID09ICJtb250aCI6CiAgICAgICAg"
    "ICAgIGVuZCA9IG5vdyArIHRpbWVkZWx0YShkYXlzPTMxKQogICAgICAgIGVsaWYgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9PSAi"
    "eWVhciI6CiAgICAgICAgICAgIGVuZCA9IG5vdyArIHRpbWVkZWx0YShkYXlzPTM2NikKICAgICAgICBlbHNlOgogICAgICAgICAg"
    "ICBlbmQgPSBub3cgKyB0aW1lZGVsdGEoZGF5cz05MikKCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICBm"
    "IltUQVNLU11bRklMVEVSXSBzdGFydCBmaWx0ZXI9e3NlbGYuX3Rhc2tfZGF0ZV9maWx0ZXJ9IHNob3dfY29tcGxldGVkPXtzZWxm"
    "Ll90YXNrX3Nob3dfY29tcGxldGVkfSB0b3RhbD17bGVuKHRhc2tzKX0iLAogICAgICAgICAgICAiSU5GTyIsCiAgICAgICAgKQog"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bRklMVEVSXSBub3c9e25vdy5pc29mb3JtYXQodGltZXNwZWM9J3Nl"
    "Y29uZHMnKX0iLCAiREVCVUciKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU11bRklMVEVSXSBob3Jpem9uX2Vu"
    "ZD17ZW5kLmlzb2Zvcm1hdCh0aW1lc3BlYz0nc2Vjb25kcycpfSIsICJERUJVRyIpCgogICAgICAgIGZpbHRlcmVkOiBsaXN0W2Rp"
    "Y3RdID0gW10KICAgICAgICBza2lwcGVkX2ludmFsaWRfZHVlID0gMAogICAgICAgIGZvciB0YXNrIGluIHRhc2tzOgogICAgICAg"
    "ICAgICBzdGF0dXMgPSAodGFzay5nZXQoInN0YXR1cyIpIG9yICJwZW5kaW5nIikubG93ZXIoKQogICAgICAgICAgICBpZiBub3Qg"
    "c2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCBhbmQgc3RhdHVzIGluIHsiY29tcGxldGVkIiwgImNhbmNlbGxlZCJ9OgogICAgICAg"
    "ICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgIGR1ZV9yYXcgPSB0YXNrLmdldCgiZHVlX2F0Iikgb3IgdGFzay5nZXQoImR1"
    "ZSIpCiAgICAgICAgICAgIGR1ZV9kdCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZShkdWVfcmF3LCBjb250ZXh0PSJ0YXNrc190YWJf"
    "ZHVlX2ZpbHRlciIpCiAgICAgICAgICAgIGlmIGR1ZV9yYXcgYW5kIGR1ZV9kdCBpcyBOb25lOgogICAgICAgICAgICAgICAgc2tp"
    "cHBlZF9pbnZhbGlkX2R1ZSArPSAxCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAg"
    "ICAgZiJbVEFTS1NdW0ZJTFRFUl1bV0FSTl0gc2tpcHBpbmcgaW52YWxpZCBkdWUgZGF0ZXRpbWUgdGFza19pZD17dGFzay5nZXQo"
    "J2lkJywnPycpfSBkdWVfcmF3PXtkdWVfcmF3IXJ9IiwKICAgICAgICAgICAgICAgICAgICAiV0FSTiIsCiAgICAgICAgICAgICAg"
    "ICApCiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgaWYgZHVlX2R0IGlzIE5vbmU6CiAgICAgICAgICAgICAg"
    "ICBmaWx0ZXJlZC5hcHBlbmQodGFzaykKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIG5vdyA8PSBkdWVf"
    "ZHQgPD0gZW5kIG9yIHN0YXR1cyBpbiB7ImNvbXBsZXRlZCIsICJjYW5jZWxsZWQifToKICAgICAgICAgICAgICAgIGZpbHRlcmVk"
    "LmFwcGVuZCh0YXNrKQoKICAgICAgICBmaWx0ZXJlZC5zb3J0KGtleT1fdGFza19kdWVfc29ydF9rZXkpCiAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKAogICAgICAgICAgICBmIltUQVNLU11bRklMVEVSXSBkb25lIGJlZm9yZT17bGVuKHRhc2tzKX0gYWZ0ZXI9"
    "e2xlbihmaWx0ZXJlZCl9IHNraXBwZWRfaW52YWxpZF9kdWU9e3NraXBwZWRfaW52YWxpZF9kdWV9IiwKICAgICAgICAgICAgIklO"
    "Rk8iLAogICAgICAgICkKICAgICAgICByZXR1cm4gZmlsdGVyZWQKCiAgICBkZWYgX2dvb2dsZV9ldmVudF9kdWVfZGF0ZXRpbWUo"
    "c2VsZiwgZXZlbnQ6IGRpY3QpOgogICAgICAgIHN0YXJ0ID0gKGV2ZW50IG9yIHt9KS5nZXQoInN0YXJ0Iikgb3Ige30KICAgICAg"
    "ICBkYXRlX3RpbWUgPSBzdGFydC5nZXQoImRhdGVUaW1lIikKICAgICAgICBpZiBkYXRlX3RpbWU6CiAgICAgICAgICAgIHBhcnNl"
    "ZCA9IHBhcnNlX2lzb19mb3JfY29tcGFyZShkYXRlX3RpbWUsIGNvbnRleHQ9Imdvb2dsZV9ldmVudF9kYXRlVGltZSIpCiAgICAg"
    "ICAgICAgIGlmIHBhcnNlZDoKICAgICAgICAgICAgICAgIHJldHVybiBwYXJzZWQKICAgICAgICBkYXRlX29ubHkgPSBzdGFydC5n"
    "ZXQoImRhdGUiKQogICAgICAgIGlmIGRhdGVfb25seToKICAgICAgICAgICAgcGFyc2VkID0gcGFyc2VfaXNvX2Zvcl9jb21wYXJl"
    "KGYie2RhdGVfb25seX1UMDk6MDA6MDAiLCBjb250ZXh0PSJnb29nbGVfZXZlbnRfZGF0ZSIpCiAgICAgICAgICAgIGlmIHBhcnNl"
    "ZDoKICAgICAgICAgICAgICAgIHJldHVybiBwYXJzZWQKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBfcmVmcmVzaF90YXNr"
    "X3JlZ2lzdHJ5X3BhbmVsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUp"
    "IGlzIE5vbmU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLnJlZnJl"
    "c2goKQogICAgICAgICAgICB2aXNpYmxlX2NvdW50ID0gbGVuKHNlbGYuX2ZpbHRlcmVkX3Rhc2tzX2Zvcl9yZWdpc3RyeSgpKQog"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdW1JFR0lTVFJZXSByZWZyZXNoIGNvdW50PXt2aXNpYmxlX2Nv"
    "dW50fS4iLCAiSU5GTyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKGYiW1RBU0tTXVtSRUdJU1RSWV1bRVJST1JdIHJlZnJlc2ggZmFpbGVkOiB7ZXh9IiwgIkVSUk9SIikKICAgICAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLnN0b3BfcmVmcmVzaF93b3JrZXIocmVhc29uPSJyZWdpc3RyeV9y"
    "ZWZyZXNoX2V4Y2VwdGlvbiIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgc3RvcF9leDoKICAgICAgICAgICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltUQVNLU11bUkVHSVNUUlldW1dBUk5dIGZhaWxlZCB0"
    "byBzdG9wIHJlZnJlc2ggd29ya2VyIGNsZWFubHk6IHtzdG9wX2V4fSIsCiAgICAgICAgICAgICAgICAgICAgIldBUk4iLAogICAg"
    "ICAgICAgICAgICAgKQoKICAgIGRlZiBfb25fdGFza19maWx0ZXJfY2hhbmdlZChzZWxmLCBmaWx0ZXJfa2V5OiBzdHIpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fdGFza19kYXRlX2ZpbHRlciA9IHN0cihmaWx0ZXJfa2V5IG9yICJuZXh0XzNfbW9udGhzIikKICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdIFRhc2sgcmVnaXN0cnkgZGF0ZSBmaWx0ZXIgY2hhbmdlZCB0byB7c2Vs"
    "Zi5fdGFza19kYXRlX2ZpbHRlcn0uIiwgIklORk8iKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgp"
    "CgogICAgZGVmIF90b2dnbGVfc2hvd19jb21wbGV0ZWRfdGFza3Moc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl90YXNrX3No"
    "b3dfY29tcGxldGVkID0gbm90IHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQKICAgICAgICBzZWxmLl90YXNrc190YWIuc2V0X3No"
    "b3dfY29tcGxldGVkKHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5"
    "X3BhbmVsKCkKCiAgICBkZWYgX3NlbGVjdGVkX3Rhc2tfaWRzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICBpZiBnZXRhdHRy"
    "KHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkgaXMgTm9uZToKICAgICAgICAgICAgcmV0dXJuIFtdCiAgICAgICAgcmV0dXJuIHNl"
    "bGYuX3Rhc2tzX3RhYi5zZWxlY3RlZF90YXNrX2lkcygpCgogICAgZGVmIF9zZXRfdGFza19zdGF0dXMoc2VsZiwgdGFza19pZDog"
    "c3RyLCBzdGF0dXM6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgaWYgc3RhdHVzID09ICJjb21wbGV0ZWQiOgogICAg"
    "ICAgICAgICB1cGRhdGVkID0gc2VsZi5fdGFza3MuY29tcGxldGUodGFza19pZCkKICAgICAgICBlbGlmIHN0YXR1cyA9PSAiY2Fu"
    "Y2VsbGVkIjoKICAgICAgICAgICAgdXBkYXRlZCA9IHNlbGYuX3Rhc2tzLmNhbmNlbCh0YXNrX2lkKQogICAgICAgIGVsc2U6CiAg"
    "ICAgICAgICAgIHVwZGF0ZWQgPSBzZWxmLl90YXNrcy51cGRhdGVfc3RhdHVzKHRhc2tfaWQsIHN0YXR1cykKCiAgICAgICAgaWYg"
    "bm90IHVwZGF0ZWQ6CiAgICAgICAgICAgIHJldHVybiBOb25lCgogICAgICAgIGdvb2dsZV9ldmVudF9pZCA9ICh1cGRhdGVkLmdl"
    "dCgiZ29vZ2xlX2V2ZW50X2lkIikgb3IgIiIpLnN0cmlwKCkKICAgICAgICBpZiBnb29nbGVfZXZlbnRfaWQ6CiAgICAgICAgICAg"
    "IHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX2djYWwuZGVsZXRlX2V2ZW50X2Zvcl90YXNrKGdvb2dsZV9ldmVudF9pZCkKICAg"
    "ICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAg"
    "ICAgICAgICAgICAgICBmIltUQVNLU11bV0FSTl0gR29vZ2xlIGV2ZW50IGNsZWFudXAgZmFpbGVkIGZvciB0YXNrX2lkPXt0YXNr"
    "X2lkfToge2V4fSIsCiAgICAgICAgICAgICAgICAgICAgIldBUk4iLAogICAgICAgICAgICAgICAgKQogICAgICAgIHJldHVybiB1"
    "cGRhdGVkCgogICAgZGVmIF9jb21wbGV0ZV9zZWxlY3RlZF90YXNrKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgZG9uZSA9IDAKICAg"
    "ICAgICBmb3IgdGFza19pZCBpbiBzZWxmLl9zZWxlY3RlZF90YXNrX2lkcygpOgogICAgICAgICAgICBpZiBzZWxmLl9zZXRfdGFz"
    "a19zdGF0dXModGFza19pZCwgImNvbXBsZXRlZCIpOgogICAgICAgICAgICAgICAgZG9uZSArPSAxCiAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKGYiW1RBU0tTXSBDT01QTEVURSBTRUxFQ1RFRCBhcHBsaWVkIHRvIHtkb25lfSB0YXNrKHMpLiIsICJJTkZPIikK"
    "ICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBfY2FuY2VsX3NlbGVjdGVkX3Rhc2so"
    "c2VsZikgLT4gTm9uZToKICAgICAgICBkb25lID0gMAogICAgICAgIGZvciB0YXNrX2lkIGluIHNlbGYuX3NlbGVjdGVkX3Rhc2tf"
    "aWRzKCk6CiAgICAgICAgICAgIGlmIHNlbGYuX3NldF90YXNrX3N0YXR1cyh0YXNrX2lkLCAiY2FuY2VsbGVkIik6CiAgICAgICAg"
    "ICAgICAgICBkb25lICs9IDEKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbVEFTS1NdIENBTkNFTCBTRUxFQ1RFRCBhcHBs"
    "aWVkIHRvIHtkb25lfSB0YXNrKHMpLiIsICJJTkZPIikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwo"
    "KQoKICAgIGRlZiBfcHVyZ2VfY29tcGxldGVkX3Rhc2tzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVtb3ZlZCA9IHNlbGYuX3Rh"
    "c2tzLmNsZWFyX2NvbXBsZXRlZCgpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXSBQVVJHRSBDT01QTEVURUQg"
    "cmVtb3ZlZCB7cmVtb3ZlZH0gdGFzayhzKS4iLCAiSU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3Bh"
    "bmVsKCkKCiAgICBkZWYgX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoc2VsZiwgdGV4dDogc3RyLCBvazogYm9vbCA9IEZhbHNlKSAt"
    "PiBOb25lOgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBub3QgTm9uZToKICAgICAgICAg"
    "ICAgc2VsZi5fdGFza3NfdGFiLnNldF9zdGF0dXModGV4dCwgb2s9b2spCgogICAgZGVmIF9vcGVuX3Rhc2tfZWRpdG9yX3dvcmtz"
    "cGFjZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBOb25lOgog"
    "ICAgICAgICAgICByZXR1cm4KICAgICAgICBub3dfbG9jYWwgPSBkYXRldGltZS5ub3coKQogICAgICAgIGVuZF9sb2NhbCA9IG5v"
    "d19sb2NhbCArIHRpbWVkZWx0YShtaW51dGVzPTMwKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9uYW1lLnNl"
    "dFRleHQoIiIpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X2RhdGUuc2V0VGV4dChub3dfbG9jYWwu"
    "c3RyZnRpbWUoIiVZLSVtLSVkIikpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUuc2V0VGV4"
    "dChub3dfbG9jYWwuc3RyZnRpbWUoIiVIOiVNIikpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX2VuZF9kYXRl"
    "LnNldFRleHQoZW5kX2xvY2FsLnN0cmZ0aW1lKCIlWS0lbS0lZCIpKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRv"
    "cl9lbmRfdGltZS5zZXRUZXh0KGVuZF9sb2NhbC5zdHJmdGltZSgiJUg6JU0iKSkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFz"
    "a19lZGl0b3Jfbm90ZXMuc2V0UGxhaW5UZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9sb2NhdGlv"
    "bi5zZXRUZXh0KCIiKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi50YXNrX2VkaXRvcl9yZWN1cnJlbmNlLnNldFRleHQoIiIpCiAg"
    "ICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX2FsbF9kYXkuc2V0Q2hlY2tlZChGYWxzZSkKICAgICAgICBzZWxmLl9z"
    "ZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJDb25maWd1cmUgdGFzayBkZXRhaWxzLCB0aGVuIHNhdmUgdG8gR29vZ2xlIENhbGVuZGFy"
    "LiIsIG9rPUZhbHNlKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5vcGVuX2VkaXRvcigpCgogICAgZGVmIF9jbG9zZV90YXNrX2Vk"
    "aXRvcl93b3Jrc3BhY2Uoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkg"
    "aXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5jbG9zZV9lZGl0b3IoKQoKICAgIGRlZiBfY2FuY2VsX3Rh"
    "c2tfZWRpdG9yX3dvcmtzcGFjZShzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtzcGFj"
    "ZSgpCgogICAgZGVmIF9wYXJzZV9lZGl0b3JfZGF0ZXRpbWUoc2VsZiwgZGF0ZV90ZXh0OiBzdHIsIHRpbWVfdGV4dDogc3RyLCBh"
    "bGxfZGF5OiBib29sLCBpc19lbmQ6IGJvb2wgPSBGYWxzZSk6CiAgICAgICAgZGF0ZV90ZXh0ID0gKGRhdGVfdGV4dCBvciAiIiku"
    "c3RyaXAoKQogICAgICAgIHRpbWVfdGV4dCA9ICh0aW1lX3RleHQgb3IgIiIpLnN0cmlwKCkKICAgICAgICBpZiBub3QgZGF0ZV90"
    "ZXh0OgogICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgIGlmIGFsbF9kYXk6CiAgICAgICAgICAgIGhvdXIgPSAyMyBpZiBp"
    "c19lbmQgZWxzZSAwCiAgICAgICAgICAgIG1pbnV0ZSA9IDU5IGlmIGlzX2VuZCBlbHNlIDAKICAgICAgICAgICAgcGFyc2VkID0g"
    "ZGF0ZXRpbWUuc3RycHRpbWUoZiJ7ZGF0ZV90ZXh0fSB7aG91cjowMmR9OnttaW51dGU6MDJkfSIsICIlWS0lbS0lZCAlSDolTSIp"
    "CiAgICAgICAgZWxzZToKICAgICAgICAgICAgcGFyc2VkID0gZGF0ZXRpbWUuc3RycHRpbWUoZiJ7ZGF0ZV90ZXh0fSB7dGltZV90"
    "ZXh0fSIsICIlWS0lbS0lZCAlSDolTSIpCiAgICAgICAgbm9ybWFsaXplZCA9IG5vcm1hbGl6ZV9kYXRldGltZV9mb3JfY29tcGFy"
    "ZShwYXJzZWQsIGNvbnRleHQ9InRhc2tfZWRpdG9yX3BhcnNlX2R0IikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAg"
    "ICAgICAgIGYiW1RBU0tTXVtFRElUT1JdIHBhcnNlZCBkYXRldGltZSBpc19lbmQ9e2lzX2VuZH0sIGFsbF9kYXk9e2FsbF9kYXl9"
    "OiAiCiAgICAgICAgICAgIGYiaW5wdXQ9J3tkYXRlX3RleHR9IHt0aW1lX3RleHR9JyAtPiB7bm9ybWFsaXplZC5pc29mb3JtYXQo"
    "KSBpZiBub3JtYWxpemVkIGVsc2UgJ05vbmUnfSIsCiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCiAgICAgICAgcmV0dXJu"
    "IG5vcm1hbGl6ZWQKCiAgICBkZWYgX3NhdmVfdGFza19lZGl0b3JfZ29vZ2xlX2ZpcnN0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "dGFiID0gZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpCiAgICAgICAgaWYgdGFiIGlzIE5vbmU6CiAgICAgICAgICAg"
    "IHJldHVybgogICAgICAgIHRpdGxlID0gdGFiLnRhc2tfZWRpdG9yX25hbWUudGV4dCgpLnN0cmlwKCkKICAgICAgICBhbGxfZGF5"
    "ID0gdGFiLnRhc2tfZWRpdG9yX2FsbF9kYXkuaXNDaGVja2VkKCkKICAgICAgICBzdGFydF9kYXRlID0gdGFiLnRhc2tfZWRpdG9y"
    "X3N0YXJ0X2RhdGUudGV4dCgpLnN0cmlwKCkKICAgICAgICBzdGFydF90aW1lID0gdGFiLnRhc2tfZWRpdG9yX3N0YXJ0X3RpbWUu"
    "dGV4dCgpLnN0cmlwKCkKICAgICAgICBlbmRfZGF0ZSA9IHRhYi50YXNrX2VkaXRvcl9lbmRfZGF0ZS50ZXh0KCkuc3RyaXAoKQog"
    "ICAgICAgIGVuZF90aW1lID0gdGFiLnRhc2tfZWRpdG9yX2VuZF90aW1lLnRleHQoKS5zdHJpcCgpCiAgICAgICAgbm90ZXMgPSB0"
    "YWIudGFza19lZGl0b3Jfbm90ZXMudG9QbGFpblRleHQoKS5zdHJpcCgpCiAgICAgICAgbG9jYXRpb24gPSB0YWIudGFza19lZGl0"
    "b3JfbG9jYXRpb24udGV4dCgpLnN0cmlwKCkKICAgICAgICByZWN1cnJlbmNlID0gdGFiLnRhc2tfZWRpdG9yX3JlY3VycmVuY2Uu"
    "dGV4dCgpLnN0cmlwKCkKCiAgICAgICAgaWYgbm90IHRpdGxlOgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3Rh"
    "dHVzKCJUYXNrIE5hbWUgaXMgcmVxdWlyZWQuIiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlmIG5vdCBz"
    "dGFydF9kYXRlIG9yIG5vdCBlbmRfZGF0ZSBvciAobm90IGFsbF9kYXkgYW5kIChub3Qgc3RhcnRfdGltZSBvciBub3QgZW5kX3Rp"
    "bWUpKToKICAgICAgICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiU3RhcnQvRW5kIGRhdGUgYW5kIHRpbWUgYXJl"
    "IHJlcXVpcmVkLiIsIG9rPUZhbHNlKQogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAgICAgICAgICAgIHN0YXJ0X2R0"
    "ID0gc2VsZi5fcGFyc2VfZWRpdG9yX2RhdGV0aW1lKHN0YXJ0X2RhdGUsIHN0YXJ0X3RpbWUsIGFsbF9kYXksIGlzX2VuZD1GYWxz"
    "ZSkKICAgICAgICAgICAgZW5kX2R0ID0gc2VsZi5fcGFyc2VfZWRpdG9yX2RhdGV0aW1lKGVuZF9kYXRlLCBlbmRfdGltZSwgYWxs"
    "X2RheSwgaXNfZW5kPVRydWUpCiAgICAgICAgICAgIGlmIG5vdCBzdGFydF9kdCBvciBub3QgZW5kX2R0OgogICAgICAgICAgICAg"
    "ICAgcmFpc2UgVmFsdWVFcnJvcigiZGF0ZXRpbWUgcGFyc2UgZmFpbGVkIikKICAgICAgICAgICAgaWYgZW5kX2R0IDwgc3RhcnRf"
    "ZHQ6CiAgICAgICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJFbmQgZGF0ZXRpbWUgbXVzdCBiZSBhZnRl"
    "ciBzdGFydCBkYXRldGltZS4iLCBvaz1GYWxzZSkKICAgICAgICAgICAgICAgIHJldHVybgogICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b246CiAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIkludmFsaWQgZGF0ZS90aW1lIGZvcm1hdC4gVXNl"
    "IFlZWVktTU0tREQgYW5kIEhIOk1NLiIsIG9rPUZhbHNlKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHpfbmFtZSA9IHNl"
    "bGYuX2djYWwuX2dldF9nb29nbGVfZXZlbnRfdGltZXpvbmUoKQogICAgICAgIHBheWxvYWQgPSB7InN1bW1hcnkiOiB0aXRsZX0K"
    "ICAgICAgICBpZiBhbGxfZGF5OgogICAgICAgICAgICBwYXlsb2FkWyJzdGFydCJdID0geyJkYXRlIjogc3RhcnRfZHQuZGF0ZSgp"
    "Lmlzb2Zvcm1hdCgpfQogICAgICAgICAgICBwYXlsb2FkWyJlbmQiXSA9IHsiZGF0ZSI6IChlbmRfZHQuZGF0ZSgpICsgdGltZWRl"
    "bHRhKGRheXM9MSkpLmlzb2Zvcm1hdCgpfQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHBheWxvYWRbInN0YXJ0Il0gPSB7ImRh"
    "dGVUaW1lIjogc3RhcnRfZHQucmVwbGFjZSh0emluZm89Tm9uZSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksICJ0aW1l"
    "Wm9uZSI6IHR6X25hbWV9CiAgICAgICAgICAgIHBheWxvYWRbImVuZCJdID0geyJkYXRlVGltZSI6IGVuZF9kdC5yZXBsYWNlKHR6"
    "aW5mbz1Ob25lKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25lIjogdHpfbmFtZX0KICAgICAgICBpZiBu"
    "b3RlczoKICAgICAgICAgICAgcGF5bG9hZFsiZGVzY3JpcHRpb24iXSA9IG5vdGVzCiAgICAgICAgaWYgbG9jYXRpb246CiAgICAg"
    "ICAgICAgIHBheWxvYWRbImxvY2F0aW9uIl0gPSBsb2NhdGlvbgogICAgICAgIGlmIHJlY3VycmVuY2U6CiAgICAgICAgICAgIHJ1"
    "bGUgPSByZWN1cnJlbmNlIGlmIHJlY3VycmVuY2UudXBwZXIoKS5zdGFydHN3aXRoKCJSUlVMRToiKSBlbHNlIGYiUlJVTEU6e3Jl"
    "Y3VycmVuY2V9IgogICAgICAgICAgICBwYXlsb2FkWyJyZWN1cnJlbmNlIl0gPSBbcnVsZV0KCiAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKGYiW1RBU0tTXVtFRElUT1JdIEdvb2dsZSBzYXZlIHN0YXJ0IGZvciB0aXRsZT0ne3RpdGxlfScuIiwgIklORk8iKQog"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgZXZlbnRfaWQsIF8gPSBzZWxmLl9nY2FsLmNyZWF0ZV9ldmVudF93aXRoX3BheWxvYWQo"
    "cGF5bG9hZCwgY2FsZW5kYXJfaWQ9InByaW1hcnkiKQogICAgICAgICAgICB0YXNrcyA9IHNlbGYuX3Rhc2tzLmxvYWRfYWxsKCkK"
    "ICAgICAgICAgICAgdGFzayA9IHsKICAgICAgICAgICAgICAgICJpZCI6IGYidGFza197dXVpZC51dWlkNCgpLmhleFs6MTBdfSIs"
    "CiAgICAgICAgICAgICAgICAiY3JlYXRlZF9hdCI6IGxvY2FsX25vd19pc28oKSwKICAgICAgICAgICAgICAgICJkdWVfYXQiOiBz"
    "dGFydF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAgICJwcmVfdHJpZ2dlciI6IChzdGFy"
    "dF9kdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgICAg"
    "ICJ0ZXh0IjogdGl0bGUsCiAgICAgICAgICAgICAgICAic3RhdHVzIjogInBlbmRpbmciLAogICAgICAgICAgICAgICAgImFja25v"
    "d2xlZGdlZF9hdCI6IE5vbmUsCiAgICAgICAgICAgICAgICAicmV0cnlfY291bnQiOiAwLAogICAgICAgICAgICAgICAgImxhc3Rf"
    "dHJpZ2dlcmVkX2F0IjogTm9uZSwKICAgICAgICAgICAgICAgICJuZXh0X3JldHJ5X2F0IjogTm9uZSwKICAgICAgICAgICAgICAg"
    "ICJwcmVfYW5ub3VuY2VkIjogRmFsc2UsCiAgICAgICAgICAgICAgICAic291cmNlIjogImxvY2FsIiwKICAgICAgICAgICAgICAg"
    "ICJnb29nbGVfZXZlbnRfaWQiOiBldmVudF9pZCwKICAgICAgICAgICAgICAgICJzeW5jX3N0YXR1cyI6ICJzeW5jZWQiLAogICAg"
    "ICAgICAgICAgICAgImxhc3Rfc3luY2VkX2F0IjogbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAgICAgIm1ldGFkYXRhIjog"
    "ewogICAgICAgICAgICAgICAgICAgICJpbnB1dCI6ICJ0YXNrX2VkaXRvcl9nb29nbGVfZmlyc3QiLAogICAgICAgICAgICAgICAg"
    "ICAgICJub3RlcyI6IG5vdGVzLAogICAgICAgICAgICAgICAgICAgICJzdGFydF9hdCI6IHN0YXJ0X2R0Lmlzb2Zvcm1hdCh0aW1l"
    "c3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgICAgICJlbmRfYXQiOiBlbmRfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJz"
    "ZWNvbmRzIiksCiAgICAgICAgICAgICAgICAgICAgImFsbF9kYXkiOiBib29sKGFsbF9kYXkpLAogICAgICAgICAgICAgICAgICAg"
    "ICJsb2NhdGlvbiI6IGxvY2F0aW9uLAogICAgICAgICAgICAgICAgICAgICJyZWN1cnJlbmNlIjogcmVjdXJyZW5jZSwKICAgICAg"
    "ICAgICAgICAgIH0sCiAgICAgICAgICAgIH0KICAgICAgICAgICAgdGFza3MuYXBwZW5kKHRhc2spCiAgICAgICAgICAgIHNlbGYu"
    "X3Rhc2tzLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jfc3RhdHVzKCJHb29nbGUgc3lu"
    "YyBzdWNjZWVkZWQgYW5kIHRhc2sgcmVnaXN0cnkgdXBkYXRlZC4iLCBvaz1UcnVlKQogICAgICAgICAgICBzZWxmLl9yZWZyZXNo"
    "X3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltU"
    "QVNLU11bRURJVE9SXSBHb29nbGUgc2F2ZSBzdWNjZXNzIGZvciB0aXRsZT0ne3RpdGxlfScsIGV2ZW50X2lkPXtldmVudF9pZH0u"
    "IiwKICAgICAgICAgICAgICAgICJPSyIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fY2xvc2VfdGFza19lZGl0b3Jf"
    "d29ya3NwYWNlKCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0"
    "b3Jfc3RhdHVzKGYiR29vZ2xlIHNhdmUgZmFpbGVkOiB7ZXh9Iiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZygKICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtFRElUT1JdW0VSUk9SXSBHb29nbGUgc2F2ZSBmYWlsdXJlIGZvciB0aXRs"
    "ZT0ne3RpdGxlfSc6IHtleH0iLAogICAgICAgICAgICAgICAgIkVSUk9SIiwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxm"
    "Ll9jbG9zZV90YXNrX2VkaXRvcl93b3Jrc3BhY2UoKQoKICAgIGRlZiBfaW5zZXJ0X2NhbGVuZGFyX2RhdGUoc2VsZiwgcWRhdGU6"
    "IFFEYXRlKSAtPiBOb25lOgogICAgICAgIGRhdGVfdGV4dCA9IHFkYXRlLnRvU3RyaW5nKCJ5eXl5LU1NLWRkIikKICAgICAgICBy"
    "b3V0ZWRfdGFyZ2V0ID0gIm5vbmUiCgogICAgICAgIGZvY3VzX3dpZGdldCA9IFFBcHBsaWNhdGlvbi5mb2N1c1dpZGdldCgpCiAg"
    "ICAgICAgZGlyZWN0X3RhcmdldHMgPSBbCiAgICAgICAgICAgICgidGFza19lZGl0b3Jfc3RhcnRfZGF0ZSIsIGdldGF0dHIoZ2V0"
    "YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpLCAidGFza19lZGl0b3Jfc3RhcnRfZGF0ZSIsIE5vbmUpKSwKICAgICAgICAg"
    "ICAgKCJ0YXNrX2VkaXRvcl9lbmRfZGF0ZSIsIGdldGF0dHIoZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpLCAidGFz"
    "a19lZGl0b3JfZW5kX2RhdGUiLCBOb25lKSksCiAgICAgICAgXQogICAgICAgIGZvciBuYW1lLCB3aWRnZXQgaW4gZGlyZWN0X3Rh"
    "cmdldHM6CiAgICAgICAgICAgIGlmIHdpZGdldCBpcyBub3QgTm9uZSBhbmQgZm9jdXNfd2lkZ2V0IGlzIHdpZGdldDoKICAgICAg"
    "ICAgICAgICAgIHdpZGdldC5zZXRUZXh0KGRhdGVfdGV4dCkKICAgICAgICAgICAgICAgIHJvdXRlZF90YXJnZXQgPSBuYW1lCiAg"
    "ICAgICAgICAgICAgICBicmVhawoKICAgICAgICBpZiByb3V0ZWRfdGFyZ2V0ID09ICJub25lIjoKICAgICAgICAgICAgaWYgaGFz"
    "YXR0cihzZWxmLCAiX2lucHV0X2ZpZWxkIikgYW5kIHNlbGYuX2lucHV0X2ZpZWxkIGlzIG5vdCBOb25lOgogICAgICAgICAgICAg"
    "ICAgaWYgZm9jdXNfd2lkZ2V0IGlzIHNlbGYuX2lucHV0X2ZpZWxkOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2lucHV0X2Zp"
    "ZWxkLmluc2VydChkYXRlX3RleHQpCiAgICAgICAgICAgICAgICAgICAgcm91dGVkX3RhcmdldCA9ICJpbnB1dF9maWVsZF9pbnNl"
    "cnQiCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldFRleHQoZGF0"
    "ZV90ZXh0KQogICAgICAgICAgICAgICAgICAgIHJvdXRlZF90YXJnZXQgPSAiaW5wdXRfZmllbGRfc2V0IgoKICAgICAgICBpZiBo"
    "YXNhdHRyKHNlbGYsICJfdGFza3NfdGFiIikgYW5kIHNlbGYuX3Rhc2tzX3RhYiBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2Vs"
    "Zi5fdGFza3NfdGFiLnN0YXR1c19sYWJlbC5zZXRUZXh0KGYiQ2FsZW5kYXIgZGF0ZSBzZWxlY3RlZDoge2RhdGVfdGV4dH0iKQoK"
    "ICAgICAgICBpZiBoYXNhdHRyKHNlbGYsICJfZGlhZ190YWIiKSBhbmQgc2VsZi5fZGlhZ190YWIgaXMgbm90IE5vbmU6CiAgICAg"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0NBTEVOREFSXSBtaW5pIGNhbGVuZGFyIGNsaWNr"
    "IHJvdXRlZDogZGF0ZT17ZGF0ZV90ZXh0fSwgdGFyZ2V0PXtyb3V0ZWRfdGFyZ2V0fS4iLAogICAgICAgICAgICAgICAgIklORk8i"
    "CiAgICAgICAgICAgICkKCiAgICBkZWYgX3BvbGxfZ29vZ2xlX2NhbGVuZGFyX2luYm91bmRfc3luYyhzZWxmLCBmb3JjZV9vbmNl"
    "OiBib29sID0gRmFsc2UpOgogICAgICAgICIiIgogICAgICAgIFN5bmMgR29vZ2xlIENhbGVuZGFyIGV2ZW50cyDihpIgbG9jYWwg"
    "dGFza3MgdXNpbmcgR29vZ2xlJ3Mgc3luY1Rva2VuIEFQSS4KCiAgICAgICAgU3RhZ2UgMSAoZmlyc3QgcnVuIC8gZm9yY2VkKTog"
    "RnVsbCBmZXRjaCwgc3RvcmVzIG5leHRTeW5jVG9rZW4uCiAgICAgICAgU3RhZ2UgMiAoZXZlcnkgcG9sbCk6ICAgICAgICAgSW5j"
    "cmVtZW50YWwgZmV0Y2ggdXNpbmcgc3RvcmVkIHN5bmNUb2tlbiDigJQKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICByZXR1cm5zIE9OTFkgd2hhdCBjaGFuZ2VkIChhZGRzL2VkaXRzL2NhbmNlbHMpLgogICAgICAgIElmIHNlcnZlciByZXR1"
    "cm5zIDQxMCBHb25lICh0b2tlbiBleHBpcmVkKSwgZmFsbHMgYmFjayB0byBmdWxsIHN5bmMuCiAgICAgICAgIiIiCiAgICAgICAg"
    "aWYgbm90IGZvcmNlX29uY2UgYW5kIG5vdCBib29sKENGRy5nZXQoInNldHRpbmdzIiwge30pLmdldCgiZ29vZ2xlX3N5bmNfZW5h"
    "YmxlZCIsIFRydWUpKToKICAgICAgICAgICAgcmV0dXJuIDAKCiAgICAgICAgdHJ5OgogICAgICAgICAgICBub3dfaXNvID0gbG9j"
    "YWxfbm93X2lzbygpCiAgICAgICAgICAgIHRhc2tzID0gc2VsZi5fdGFza3MubG9hZF9hbGwoKQogICAgICAgICAgICB0YXNrc19i"
    "eV9ldmVudF9pZCA9IHsKICAgICAgICAgICAgICAgICh0LmdldCgiZ29vZ2xlX2V2ZW50X2lkIikgb3IgIiIpLnN0cmlwKCk6IHQK"
    "ICAgICAgICAgICAgICAgIGZvciB0IGluIHRhc2tzCiAgICAgICAgICAgICAgICBpZiAodC5nZXQoImdvb2dsZV9ldmVudF9pZCIp"
    "IG9yICIiKS5zdHJpcCgpCiAgICAgICAgICAgIH0KCiAgICAgICAgICAgICMg4pSA4pSAIEZldGNoIGZyb20gR29vZ2xlIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBzdG9yZWRfdG9rZW4gPSBz"
    "ZWxmLl9zdGF0ZS5nZXQoImdvb2dsZV9jYWxlbmRhcl9zeW5jX3Rva2VuIikKCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAg"
    "ICAgIGlmIHN0b3JlZF90b2tlbiBhbmQgbm90IGZvcmNlX29uY2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKAogICAgICAgICAgICAgICAgICAgICAgICAiW0dPT0dMRV1bU1lOQ10gSW5jcmVtZW50YWwgc3luYyAoc3luY1Rva2VuKS4i"
    "LCAiSU5GTyIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgcmVtb3RlX2V2ZW50cywgbmV4dF90b2tl"
    "biA9IHNlbGYuX2djYWwubGlzdF9wcmltYXJ5X2V2ZW50cygKICAgICAgICAgICAgICAgICAgICAgICAgc3luY190b2tlbj1zdG9y"
    "ZWRfdG9rZW4KICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAgICAgIltHT09HTEVdW1NZTkNdIEZ1bGwgc3luYyAobm8gc3Rv"
    "cmVkIHRva2VuKS4iLCAiSU5GTyIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgbm93X3V0YyA9IGRh"
    "dGV0aW1lLnV0Y25vdygpLnJlcGxhY2UobWljcm9zZWNvbmQ9MCkKICAgICAgICAgICAgICAgICAgICB0aW1lX21pbiA9IChub3df"
    "dXRjIC0gdGltZWRlbHRhKGRheXM9MzY1KSkuaXNvZm9ybWF0KCkgKyAiWiIKICAgICAgICAgICAgICAgICAgICByZW1vdGVfZXZl"
    "bnRzLCBuZXh0X3Rva2VuID0gc2VsZi5fZ2NhbC5saXN0X3ByaW1hcnlfZXZlbnRzKAogICAgICAgICAgICAgICAgICAgICAgICB0"
    "aW1lX21pbj10aW1lX21pbgogICAgICAgICAgICAgICAgICAgICkKCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgYXBp"
    "X2V4OgogICAgICAgICAgICAgICAgaWYgIjQxMCIgaW4gc3RyKGFwaV9leCkgb3IgIkdvbmUiIGluIHN0cihhcGlfZXgpOgogICAg"
    "ICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICAgICAgIltHT09HTEVdW1NZTkNd"
    "IHN5bmNUb2tlbiBleHBpcmVkICg0MTApIOKAlCBmdWxsIHJlc3luYy4iLCAiV0FSTiIKICAgICAgICAgICAgICAgICAgICApCiAg"
    "ICAgICAgICAgICAgICAgICAgc2VsZi5fc3RhdGUucG9wKCJnb29nbGVfY2FsZW5kYXJfc3luY190b2tlbiIsIE5vbmUpCiAgICAg"
    "ICAgICAgICAgICAgICAgbm93X3V0YyA9IGRhdGV0aW1lLnV0Y25vdygpLnJlcGxhY2UobWljcm9zZWNvbmQ9MCkKICAgICAgICAg"
    "ICAgICAgICAgICB0aW1lX21pbiA9IChub3dfdXRjIC0gdGltZWRlbHRhKGRheXM9MzY1KSkuaXNvZm9ybWF0KCkgKyAiWiIKICAg"
    "ICAgICAgICAgICAgICAgICByZW1vdGVfZXZlbnRzLCBuZXh0X3Rva2VuID0gc2VsZi5fZ2NhbC5saXN0X3ByaW1hcnlfZXZlbnRz"
    "KAogICAgICAgICAgICAgICAgICAgICAgICB0aW1lX21pbj10aW1lX21pbgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgcmFpc2UKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAg"
    "ICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1lOQ10gUmVjZWl2ZWQge2xlbihyZW1vdGVfZXZlbnRzKX0gZXZlbnQocykuIiwgIklO"
    "Rk8iCiAgICAgICAgICAgICkKCiAgICAgICAgICAgICMgU2F2ZSBuZXcgdG9rZW4gZm9yIG5leHQgaW5jcmVtZW50YWwgY2FsbAog"
    "ICAgICAgICAgICBpZiBuZXh0X3Rva2VuOgogICAgICAgICAgICAgICAgc2VsZi5fc3RhdGVbImdvb2dsZV9jYWxlbmRhcl9zeW5j"
    "X3Rva2VuIl0gPSBuZXh0X3Rva2VuCiAgICAgICAgICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0ZShzZWxmLl9zdGF0ZSkK"
    "CiAgICAgICAgICAgICMg4pSA4pSAIFByb2Nlc3MgZXZlbnRzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgICAgICBpbXBvcnRlZF9jb3VudCA9IHVwZGF0ZWRfY291bnQgPSByZW1vdmVk"
    "X2NvdW50ID0gMAogICAgICAgICAgICBjaGFuZ2VkID0gRmFsc2UKCiAgICAgICAgICAgIGZvciBldmVudCBpbiByZW1vdGVfZXZl"
    "bnRzOgogICAgICAgICAgICAgICAgZXZlbnRfaWQgPSAoZXZlbnQuZ2V0KCJpZCIpIG9yICIiKS5zdHJpcCgpCiAgICAgICAgICAg"
    "ICAgICBpZiBub3QgZXZlbnRfaWQ6CiAgICAgICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICAgICAjIERlbGV0"
    "ZWQgLyBjYW5jZWxsZWQgb24gR29vZ2xlJ3Mgc2lkZQogICAgICAgICAgICAgICAgaWYgZXZlbnQuZ2V0KCJzdGF0dXMiKSA9PSAi"
    "Y2FuY2VsbGVkIjoKICAgICAgICAgICAgICAgICAgICBleGlzdGluZyA9IHRhc2tzX2J5X2V2ZW50X2lkLmdldChldmVudF9pZCkK"
    "ICAgICAgICAgICAgICAgICAgICBpZiBleGlzdGluZyBhbmQgZXhpc3RpbmcuZ2V0KCJzdGF0dXMiKSBub3QgaW4gKCJjYW5jZWxs"
    "ZWQiLCAiY29tcGxldGVkIik6CiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJzdGF0dXMiXSAgICAgICAgID0gImNh"
    "bmNlbGxlZCIKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbImNhbmNlbGxlZF9hdCJdICAgPSBub3dfaXNvCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJzeW5jX3N0YXR1cyJdICAgID0gImRlbGV0ZWRfcmVtb3RlIgogICAgICAgICAg"
    "ICAgICAgICAgICAgICBleGlzdGluZ1sibGFzdF9zeW5jZWRfYXQiXSA9IG5vd19pc28KICAgICAgICAgICAgICAgICAgICAgICAg"
    "ZXhpc3Rpbmcuc2V0ZGVmYXVsdCgibWV0YWRhdGEiLCB7fSlbImdvb2dsZV9kZWxldGVkX3JlbW90ZSJdID0gbm93X2lzbwogICAg"
    "ICAgICAgICAgICAgICAgICAgICByZW1vdmVkX2NvdW50ICs9IDEKICAgICAgICAgICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRy"
    "dWUKICAgICAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ZiJbR09PR0xFXVtTWU5DXSBSZW1vdmVkOiB7ZXhpc3RpbmcuZ2V0KCd0ZXh0JywnPycpfSIsICJJTkZPIgogICAgICAgICAgICAg"
    "ICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgY29udGludWUKCiAgICAgICAgICAgICAgICBzdW1tYXJ5ID0gKGV2ZW50"
    "LmdldCgic3VtbWFyeSIpIG9yICJHb29nbGUgQ2FsZW5kYXIgRXZlbnQiKS5zdHJpcCgpIG9yICJHb29nbGUgQ2FsZW5kYXIgRXZl"
    "bnQiCiAgICAgICAgICAgICAgICBkdWVfYXQgID0gc2VsZi5fZ29vZ2xlX2V2ZW50X2R1ZV9kYXRldGltZShldmVudCkKICAgICAg"
    "ICAgICAgICAgIGV4aXN0aW5nID0gdGFza3NfYnlfZXZlbnRfaWQuZ2V0KGV2ZW50X2lkKQoKICAgICAgICAgICAgICAgIGlmIGV4"
    "aXN0aW5nOgogICAgICAgICAgICAgICAgICAgICMgVXBkYXRlIGlmIGFueXRoaW5nIGNoYW5nZWQKICAgICAgICAgICAgICAgICAg"
    "ICB0YXNrX2NoYW5nZWQgPSBGYWxzZQogICAgICAgICAgICAgICAgICAgIGlmIChleGlzdGluZy5nZXQoInRleHQiKSBvciAiIiku"
    "c3RyaXAoKSAhPSBzdW1tYXJ5OgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1sidGV4dCJdID0gc3VtbWFyeQogICAg"
    "ICAgICAgICAgICAgICAgICAgICB0YXNrX2NoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgaWYgZHVlX2F0OgogICAg"
    "ICAgICAgICAgICAgICAgICAgICBkdWVfaXNvID0gZHVlX2F0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGlmIGV4aXN0aW5nLmdldCgiZHVlX2F0IikgIT0gZHVlX2lzbzoKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIGV4aXN0aW5nWyJkdWVfYXQiXSAgICAgICA9IGR1ZV9pc28KICAgICAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0"
    "aW5nWyJwcmVfdHJpZ2dlciJdICA9IChkdWVfYXQgLSB0aW1lZGVsdGEobWludXRlcz0xKSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJz"
    "ZWNvbmRzIikKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHRhc2tfY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgICAg"
    "ICBpZiBleGlzdGluZy5nZXQoInN5bmNfc3RhdHVzIikgIT0gInN5bmNlZCI6CiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0"
    "aW5nWyJzeW5jX3N0YXR1cyJdID0gInN5bmNlZCIKICAgICAgICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gVHJ1ZQog"
    "ICAgICAgICAgICAgICAgICAgIGlmIHRhc2tfY2hhbmdlZDoKICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbImxhc3Rf"
    "c3luY2VkX2F0Il0gPSBub3dfaXNvCiAgICAgICAgICAgICAgICAgICAgICAgIHVwZGF0ZWRfY291bnQgKz0gMQogICAgICAgICAg"
    "ICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NZTkNdIFVwZGF0ZWQ6IHtzdW1tYXJ5fSIsICJJTkZPIgogICAg"
    "ICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgICMgTmV3IGV2ZW50"
    "CiAgICAgICAgICAgICAgICAgICAgaWYgbm90IGR1ZV9hdDoKICAgICAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAg"
    "ICAgICAgICAgICAgICBuZXdfdGFzayA9IHsKICAgICAgICAgICAgICAgICAgICAgICAgImlkIjogICAgICAgICAgICAgICAgZiJ0"
    "YXNrX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19IiwKICAgICAgICAgICAgICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgICAgICAg"
    "bm93X2lzbywKICAgICAgICAgICAgICAgICAgICAgICAgImR1ZV9hdCI6ICAgICAgICAgICAgZHVlX2F0Lmlzb2Zvcm1hdCh0aW1l"
    "c3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgICAgICAgICAicHJlX3RyaWdnZXIiOiAgICAgICAoZHVlX2F0IC0gdGlt"
    "ZWRlbHRhKG1pbnV0ZXM9MSkpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAgICAgICAgICAgICAi"
    "dGV4dCI6ICAgICAgICAgICAgICBzdW1tYXJ5LAogICAgICAgICAgICAgICAgICAgICAgICAic3RhdHVzIjogICAgICAgICAgICAi"
    "cGVuZGluZyIsCiAgICAgICAgICAgICAgICAgICAgICAgICJhY2tub3dsZWRnZWRfYXQiOiAgIE5vbmUsCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJyZXRyeV9jb3VudCI6ICAgICAgIDAsCiAgICAgICAgICAgICAgICAgICAgICAgICJsYXN0X3RyaWdnZXJlZF9h"
    "dCI6IE5vbmUsCiAgICAgICAgICAgICAgICAgICAgICAgICJuZXh0X3JldHJ5X2F0IjogICAgIE5vbmUsCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJwcmVfYW5ub3VuY2VkIjogICAgIEZhbHNlLAogICAgICAgICAgICAgICAgICAgICAgICAic291cmNlIjogICAg"
    "ICAgICAgICAiZ29vZ2xlIiwKICAgICAgICAgICAgICAgICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6ICAgZXZlbnRfaWQsCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICJzeW5jX3N0YXR1cyI6ICAgICAgICJzeW5jZWQiLAogICAgICAgICAgICAgICAgICAgICAg"
    "ICAibGFzdF9zeW5jZWRfYXQiOiAgICBub3dfaXNvLAogICAgICAgICAgICAgICAgICAgICAgICAibWV0YWRhdGEiOiB7CiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAiZ29vZ2xlX2ltcG9ydGVkX2F0Ijogbm93X2lzbywKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICJnb29nbGVfdXBkYXRlZCI6ICAgICBldmVudC5nZXQoInVwZGF0ZWQiKSwKICAgICAgICAgICAgICAgICAgICAgICAg"
    "fSwKICAgICAgICAgICAgICAgICAgICB9CiAgICAgICAgICAgICAgICAgICAgdGFza3MuYXBwZW5kKG5ld190YXNrKQogICAgICAg"
    "ICAgICAgICAgICAgIHRhc2tzX2J5X2V2ZW50X2lkW2V2ZW50X2lkXSA9IG5ld190YXNrCiAgICAgICAgICAgICAgICAgICAgaW1w"
    "b3J0ZWRfY291bnQgKz0gMQogICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgICAgICAgICAgICAgc2Vs"
    "Zi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bU1lOQ10gSW1wb3J0ZWQ6IHtzdW1tYXJ5fSIsICJJTkZPIikKCiAgICAgICAgICAg"
    "IGlmIGNoYW5nZWQ6CiAgICAgICAgICAgICAgICBzZWxmLl90YXNrcy5zYXZlX2FsbCh0YXNrcykKICAgICAgICAgICAgc2VsZi5f"
    "cmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAg"
    "ICAgIGYiW0dPT0dMRV1bU1lOQ10gRG9uZSDigJQgaW1wb3J0ZWQ9e2ltcG9ydGVkX2NvdW50fSAiCiAgICAgICAgICAgICAgICBm"
    "InVwZGF0ZWQ9e3VwZGF0ZWRfY291bnR9IHJlbW92ZWQ9e3JlbW92ZWRfY291bnR9IiwgIklORk8iCiAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgcmV0dXJuIGltcG9ydGVkX2NvdW50CgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVdW1NZTkNdW0VSUk9SXSB7ZXh9IiwgIkVSUk9SIikKICAgICAgICAgICAgcmV0"
    "dXJuIDAKCgogICAgZGVmIF9tZWFzdXJlX3ZyYW1fYmFzZWxpbmUoc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBOVk1MX09LIGFu"
    "ZCBncHVfaGFuZGxlOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1l"
    "bW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIHNlbGYuX2RlY2tfdnJhbV9iYXNlID0gbWVtLnVzZWQgLyAxMDI0"
    "KiozCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJbVlJBTV0gQmFzZWxp"
    "bmUgbWVhc3VyZWQ6IHtzZWxmLl9kZWNrX3ZyYW1fYmFzZTouMmZ9R0IgIgogICAgICAgICAgICAgICAgICAgIGYiKHtERUNLX05B"
    "TUV9J3MgZm9vdHByaW50KSIsICJJTkZPIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgog"
    "ICAgICAgICAgICAgICAgcGFzcwoKICAgICMg4pSA4pSAIE1FU1NBR0UgSEFORExJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYg"
    "X3NlbmRfbWVzc2FnZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIG5vdCBzZWxmLl9tb2RlbF9sb2FkZWQgb3Igc2VsZi5fdG9y"
    "cG9yX3N0YXRlID09ICJTVVNQRU5EIjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdGV4dCA9IHNlbGYuX2lucHV0X2ZpZWxk"
    "LnRleHQoKS5zdHJpcCgpCiAgICAgICAgaWYgbm90IHRleHQ6CiAgICAgICAgICAgIHJldHVybgoKICAgICAgICAjIEZsaXAgYmFj"
    "ayB0byBwZXJzb25hIGNoYXQgdGFiIGZyb20gU2VsZiB0YWIgaWYgbmVlZGVkCiAgICAgICAgaWYgc2VsZi5fbWFpbl90YWJzLmN1"
    "cnJlbnRJbmRleCgpICE9IDA6CiAgICAgICAgICAgIHNlbGYuX21haW5fdGFicy5zZXRDdXJyZW50SW5kZXgoMCkKCiAgICAgICAg"
    "c2VsZi5faW5wdXRfZmllbGQuY2xlYXIoKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJZT1UiLCB0ZXh0KQoKICAgICAgICAj"
    "IFNlc3Npb24gbG9nZ2luZwogICAgICAgIHNlbGYuX3Nlc3Npb25zLmFkZF9tZXNzYWdlKCJ1c2VyIiwgdGV4dCkKICAgICAgICBz"
    "ZWxmLl9tZW1vcnkuYXBwZW5kX21lc3NhZ2Uoc2VsZi5fc2Vzc2lvbl9pZCwgInVzZXIiLCB0ZXh0KQoKICAgICAgICAjIEludGVy"
    "cnVwdCBmYWNlIHRpbWVyIOKAlCBzd2l0Y2ggdG8gYWxlcnQgaW1tZWRpYXRlbHkKICAgICAgICBpZiBzZWxmLl9mYWNlX3RpbWVy"
    "X21ncjoKICAgICAgICAgICAgc2VsZi5fZmFjZV90aW1lcl9tZ3IuaW50ZXJydXB0KCJhbGVydCIpCgogICAgICAgICMgQnVpbGQg"
    "cHJvbXB0IHdpdGggdmFtcGlyZSBjb250ZXh0ICsgbWVtb3J5IGNvbnRleHQKICAgICAgICB2YW1waXJlX2N0eCAgPSBidWlsZF92"
    "YW1waXJlX2NvbnRleHQoKQogICAgICAgIG1lbW9yeV9jdHggICA9IHNlbGYuX21lbW9yeS5idWlsZF9jb250ZXh0X2Jsb2NrKHRl"
    "eHQpCiAgICAgICAgam91cm5hbF9jdHggID0gIiIKCiAgICAgICAgaWYgc2VsZi5fc2Vzc2lvbnMubG9hZGVkX2pvdXJuYWxfZGF0"
    "ZToKICAgICAgICAgICAgam91cm5hbF9jdHggPSBzZWxmLl9zZXNzaW9ucy5sb2FkX3Nlc3Npb25fYXNfY29udGV4dCgKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLmxvYWRlZF9qb3VybmFsX2RhdGUKICAgICAgICAgICAgKQoKICAgICAgICAjIEJ1aWxk"
    "IHN5c3RlbSBwcm9tcHQKICAgICAgICBzeXN0ZW0gPSBTWVNURU1fUFJPTVBUX0JBU0UKICAgICAgICBpZiBtZW1vcnlfY3R4Ogog"
    "ICAgICAgICAgICBzeXN0ZW0gKz0gZiJcblxue21lbW9yeV9jdHh9IgogICAgICAgIGlmIGpvdXJuYWxfY3R4OgogICAgICAgICAg"
    "ICBzeXN0ZW0gKz0gZiJcblxue2pvdXJuYWxfY3R4fSIKICAgICAgICBzeXN0ZW0gKz0gdmFtcGlyZV9jdHgKCiAgICAgICAgIyBM"
    "ZXNzb25zIGNvbnRleHQgZm9yIGNvZGUtYWRqYWNlbnQgaW5wdXQKICAgICAgICBpZiBhbnkoa3cgaW4gdGV4dC5sb3dlcigpIGZv"
    "ciBrdyBpbiAoImxzbCIsInB5dGhvbiIsInNjcmlwdCIsImNvZGUiLCJmdW5jdGlvbiIpKToKICAgICAgICAgICAgbGFuZyA9ICJM"
    "U0wiIGlmICJsc2wiIGluIHRleHQubG93ZXIoKSBlbHNlICJQeXRob24iCiAgICAgICAgICAgIGxlc3NvbnNfY3R4ID0gc2VsZi5f"
    "bGVzc29ucy5idWlsZF9jb250ZXh0X2Zvcl9sYW5ndWFnZShsYW5nKQogICAgICAgICAgICBpZiBsZXNzb25zX2N0eDoKICAgICAg"
    "ICAgICAgICAgIHN5c3RlbSArPSBmIlxuXG57bGVzc29uc19jdHh9IgoKICAgICAgICAjIEFkZCBwZW5kaW5nIHRyYW5zbWlzc2lv"
    "bnMgY29udGV4dCBpZiBhbnkKICAgICAgICBpZiBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgPiAwOgogICAgICAgICAgICBk"
    "dXIgPSBzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gb3IgInNvbWUgdGltZSIKICAgICAgICAgICAgc3lzdGVtICs9ICgKICAgICAg"
    "ICAgICAgICAgIGYiXG5cbltSRVRVUk4gRlJPTSBUT1JQT1JdXG4iCiAgICAgICAgICAgICAgICBmIllvdSB3ZXJlIGluIHRvcnBv"
    "ciBmb3Ige2R1cn0uICIKICAgICAgICAgICAgICAgIGYie3NlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9uc30gdGhvdWdodHMgd2Vu"
    "dCB1bnNwb2tlbiAiCiAgICAgICAgICAgICAgICBmImR1cmluZyB0aGF0IHRpbWUuIEFja25vd2xlZGdlIHRoaXMgYnJpZWZseSBp"
    "biBjaGFyYWN0ZXIgIgogICAgICAgICAgICAgICAgZiJpZiBpdCBmZWVscyBuYXR1cmFsLiIKICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICBzZWxmLl9wZW5kaW5nX3RyYW5zbWlzc2lvbnMgPSAwCiAgICAgICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiAg"
    "ICA9ICIiCgogICAgICAgIGhpc3RvcnkgPSBzZWxmLl9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCgogICAgICAgICMgRGlzYWJsZSBp"
    "bnB1dAogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0"
    "RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJHRU5FUkFUSU5HIikKCiAgICAgICAgIyBTdG9wIGlkbGUg"
    "dGltZXIgZHVyaW5nIGdlbmVyYXRpb24KICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1bGVy"
    "IGFuZCBzZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1"
    "bGVyLnBhdXNlX2pvYigiaWRsZV90cmFuc21pc3Npb24iKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAg"
    "ICAgICAgcGFzcwoKICAgICAgICAjIExhdW5jaCBzdHJlYW1pbmcgd29ya2VyCiAgICAgICAgc2VsZi5fd29ya2VyID0gU3RyZWFt"
    "aW5nV29ya2VyKAogICAgICAgICAgICBzZWxmLl9hZGFwdG9yLCBzeXN0ZW0sIGhpc3RvcnksIG1heF90b2tlbnM9NTEyCiAgICAg"
    "ICAgKQogICAgICAgIHNlbGYuX3dvcmtlci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3Rva2VuKQogICAgICAgIHNlbGYu"
    "X3dvcmtlci5yZXNwb25zZV9kb25lLmNvbm5lY3Qoc2VsZi5fb25fcmVzcG9uc2VfZG9uZSkKICAgICAgICBzZWxmLl93b3JrZXIu"
    "ZXJyb3Jfb2NjdXJyZWQuY29ubmVjdChzZWxmLl9vbl9lcnJvcikKICAgICAgICBzZWxmLl93b3JrZXIuc3RhdHVzX2NoYW5nZWQu"
    "Y29ubmVjdChzZWxmLl9zZXRfc3RhdHVzKQogICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gVHJ1ZSAgIyBmbGFnIHRvIHdyaXRl"
    "IHNwZWFrZXIgbGFiZWwgYmVmb3JlIGZpcnN0IHRva2VuCiAgICAgICAgc2VsZi5fd29ya2VyLnN0YXJ0KCkKCiAgICBkZWYgX2Jl"
    "Z2luX3BlcnNvbmFfcmVzcG9uc2Uoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBXcml0ZSB0aGUgcGVyc29uYSBz"
    "cGVha2VyIGxhYmVsIGFuZCB0aW1lc3RhbXAgYmVmb3JlIHN0cmVhbWluZyBiZWdpbnMuCiAgICAgICAgQ2FsbGVkIG9uIGZpcnN0"
    "IHRva2VuIG9ubHkuIFN1YnNlcXVlbnQgdG9rZW5zIGFwcGVuZCBkaXJlY3RseS4KICAgICAgICAiIiIKICAgICAgICB0aW1lc3Rh"
    "bXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAgICAgICMgV3JpdGUgdGhlIHNwZWFrZXIgbGFiZWwg"
    "YXMgSFRNTCwgdGhlbiBhZGQgYSBuZXdsaW5lIHNvIHRva2VucwogICAgICAgICMgZmxvdyBiZWxvdyBpdCByYXRoZXIgdGhhbiBp"
    "bmxpbmUKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7"
    "Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAg"
    "ICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfQ1JJTVNPTn07IGZvbnQtd2VpZ2h0OmJvbGQ7Ij4nCiAgICAgICAgICAgIGYn"
    "e0RFQ0tfTkFNRS51cHBlcigpfSDinak8L3NwYW4+ICcKICAgICAgICApCiAgICAgICAgIyBNb3ZlIGN1cnNvciB0byBlbmQgc28g"
    "aW5zZXJ0UGxhaW5UZXh0IGFwcGVuZHMgY29ycmVjdGx5CiAgICAgICAgY3Vyc29yID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRleHRD"
    "dXJzb3IoKQogICAgICAgIGN1cnNvci5tb3ZlUG9zaXRpb24oUVRleHRDdXJzb3IuTW92ZU9wZXJhdGlvbi5FbmQpCiAgICAgICAg"
    "c2VsZi5fY2hhdF9kaXNwbGF5LnNldFRleHRDdXJzb3IoY3Vyc29yKQoKICAgIGRlZiBfb25fdG9rZW4oc2VsZiwgdG9rZW46IHN0"
    "cikgLT4gTm9uZToKICAgICAgICAiIiJBcHBlbmQgc3RyZWFtaW5nIHRva2VuIHRvIGNoYXQgZGlzcGxheS4iIiIKICAgICAgICBp"
    "ZiBzZWxmLl9maXJzdF90b2tlbjoKICAgICAgICAgICAgc2VsZi5fYmVnaW5fcGVyc29uYV9yZXNwb25zZSgpCiAgICAgICAgICAg"
    "IHNlbGYuX2ZpcnN0X3Rva2VuID0gRmFsc2UKICAgICAgICBjdXJzb3IgPSBzZWxmLl9jaGF0X2Rpc3BsYXkudGV4dEN1cnNvcigp"
    "CiAgICAgICAgY3Vyc29yLm1vdmVQb3NpdGlvbihRVGV4dEN1cnNvci5Nb3ZlT3BlcmF0aW9uLkVuZCkKICAgICAgICBzZWxmLl9j"
    "aGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNvcihjdXJzb3IpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5Lmluc2VydFBsYWluVGV4"
    "dCh0b2tlbikKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAg"
    "ICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgIGRlZiBfb25f"
    "cmVzcG9uc2VfZG9uZShzZWxmLCByZXNwb25zZTogc3RyKSAtPiBOb25lOgogICAgICAgICMgRW5zdXJlIHJlc3BvbnNlIGlzIG9u"
    "IGl0cyBvd24gbGluZQogICAgICAgIGN1cnNvciA9IHNlbGYuX2NoYXRfZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAgICAgICBjdXJz"
    "b3IubW92ZVBvc2l0aW9uKFFUZXh0Q3Vyc29yLk1vdmVPcGVyYXRpb24uRW5kKQogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5z"
    "ZXRUZXh0Q3Vyc29yKGN1cnNvcikKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuaW5zZXJ0UGxhaW5UZXh0KCJcblxuIikKCiAg"
    "ICAgICAgIyBMb2cgdG8gbWVtb3J5IGFuZCBzZXNzaW9uCiAgICAgICAgc2VsZi5fdG9rZW5fY291bnQgKz0gbGVuKHJlc3BvbnNl"
    "LnNwbGl0KCkpCiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuYWRkX21lc3NhZ2UoImFzc2lzdGFudCIsIHJlc3BvbnNlKQogICAgICAg"
    "IHNlbGYuX21lbW9yeS5hcHBlbmRfbWVzc2FnZShzZWxmLl9zZXNzaW9uX2lkLCAiYXNzaXN0YW50IiwgcmVzcG9uc2UpCiAgICAg"
    "ICAgc2VsZi5fbWVtb3J5LmFwcGVuZF9tZW1vcnkoc2VsZi5fc2Vzc2lvbl9pZCwgIiIsIHJlc3BvbnNlKQoKICAgICAgICAjIFVw"
    "ZGF0ZSBibG9vZCBzcGhlcmUKICAgICAgICBpZiBzZWxmLl9sZWZ0X29yYiBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5f"
    "bGVmdF9vcmIuc2V0RmlsbCgKICAgICAgICAgICAgICAgIG1pbigxLjAsIHNlbGYuX3Rva2VuX2NvdW50IC8gNDA5Ni4wKQogICAg"
    "ICAgICAgICApCgogICAgICAgICMgUmUtZW5hYmxlIGlucHV0CiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChUcnVl"
    "KQogICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRG"
    "b2N1cygpCgogICAgICAgICMgUmVzdW1lIGlkbGUgdGltZXIKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgaWYgc2Vs"
    "Zi5fc2NoZWR1bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAg"
    "c2VsZi5fc2NoZWR1bGVyLnJlc3VtZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlv"
    "bjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTY2hlZHVsZSBzZW50aW1lbnQgYW5hbHlzaXMgKDUgc2Vjb25kIGRl"
    "bGF5KQogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDUwMDAsIGxhbWJkYTogc2VsZi5fcnVuX3NlbnRpbWVudChyZXNwb25zZSkp"
    "CgogICAgZGVmIF9ydW5fc2VudGltZW50KHNlbGYsIHJlc3BvbnNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYu"
    "X21vZGVsX2xvYWRlZDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fc2VudF93b3JrZXIgPSBTZW50aW1lbnRXb3Jr"
    "ZXIoc2VsZi5fYWRhcHRvciwgcmVzcG9uc2UpCiAgICAgICAgc2VsZi5fc2VudF93b3JrZXIuZmFjZV9yZWFkeS5jb25uZWN0KHNl"
    "bGYuX29uX3NlbnRpbWVudCkKICAgICAgICBzZWxmLl9zZW50X3dvcmtlci5zdGFydCgpCgogICAgZGVmIF9vbl9zZW50aW1lbnQo"
    "c2VsZiwgZW1vdGlvbjogc3RyKSAtPiBOb25lOgogICAgICAgIGlmIHNlbGYuX2ZhY2VfdGltZXJfbWdyOgogICAgICAgICAgICBz"
    "ZWxmLl9mYWNlX3RpbWVyX21nci5zZXRfZmFjZShlbW90aW9uKQoKICAgIGRlZiBfb25fZXJyb3Ioc2VsZiwgZXJyb3I6IHN0cikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiRVJST1IiLCBlcnJvcikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coZiJbR0VORVJBVElPTiBFUlJPUl0ge2Vycm9yfSIsICJFUlJPUiIpCiAgICAgICAgaWYgc2VsZi5fZmFjZV90aW1lcl9tZ3I6"
    "CiAgICAgICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyLnNldF9mYWNlKCJwYW5pY2tlZCIpCiAgICAgICAgc2VsZi5fc2V0X3N0"
    "YXR1cygiRVJST1IiKQogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICBzZWxmLl9pbnB1dF9m"
    "aWVsZC5zZXRFbmFibGVkKFRydWUpCgogICAgIyDilIDilIAgVE9SUE9SIFNZU1RFTSDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgIGRlZiBfb25fdG9ycG9yX3N0YXRlX2NoYW5nZWQoc2VsZiwgc3RhdGU6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl90"
    "b3Jwb3Jfc3RhdGUgPSBzdGF0ZQoKICAgICAgICBpZiBzdGF0ZSA9PSAiU1VTUEVORCI6CiAgICAgICAgICAgIHNlbGYuX2VudGVy"
    "X3RvcnBvcihyZWFzb249Im1hbnVhbCDigJQgU1VTUEVORCBtb2RlIHNlbGVjdGVkIikKICAgICAgICBlbGlmIHN0YXRlID09ICJB"
    "V0FLRSI6CiAgICAgICAgICAgICMgQWx3YXlzIGV4aXQgdG9ycG9yIHdoZW4gc3dpdGNoaW5nIHRvIEFXQUtFIOKAlAogICAgICAg"
    "ICAgICAjIGV2ZW4gd2l0aCBPbGxhbWEgYmFja2VuZCB3aGVyZSBtb2RlbCBpc24ndCB1bmxvYWRlZCwKICAgICAgICAgICAgIyB3"
    "ZSBuZWVkIHRvIHJlLWVuYWJsZSBVSSBhbmQgcmVzZXQgc3RhdGUKICAgICAgICAgICAgc2VsZi5fZXhpdF90b3Jwb3IoKQogICAg"
    "ICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMAogICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyAg"
    "ID0gMAogICAgICAgIGVsaWYgc3RhdGUgPT0gIkFVVE8iOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAg"
    "ICAgICAgICAiW1RPUlBPUl0gQVVUTyBtb2RlIOKAlCBtb25pdG9yaW5nIFZSQU0gcHJlc3N1cmUuIiwgIklORk8iCiAgICAgICAg"
    "ICAgICkKCiAgICBkZWYgX2VudGVyX3RvcnBvcihzZWxmLCByZWFzb246IHN0ciA9ICJtYW51YWwiKSAtPiBOb25lOgogICAgICAg"
    "IGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgcmV0dXJuICAjIEFscmVhZHkgaW4gdG9ycG9y"
    "CgogICAgICAgIHNlbGYuX3RvcnBvcl9zaW5jZSA9IGRhdGV0aW1lLm5vdygpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYi"
    "W1RPUlBPUl0gRW50ZXJpbmcgdG9ycG9yOiB7cmVhc29ufSIsICJXQVJOIikKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lT"
    "VEVNIiwgIlRoZSB2ZXNzZWwgZ3Jvd3MgY3Jvd2RlZC4gSSB3aXRoZHJhdy4iKQoKICAgICAgICAjIFVubG9hZCBtb2RlbCBmcm9t"
    "IFZSQU0KICAgICAgICBpZiBzZWxmLl9tb2RlbF9sb2FkZWQgYW5kIGlzaW5zdGFuY2Uoc2VsZi5fYWRhcHRvciwKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcik6CiAgICAgICAgICAg"
    "IHRyeToKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2FkYXB0b3IuX21vZGVsIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAg"
    "ICAgIGRlbCBzZWxmLl9hZGFwdG9yLl9tb2RlbAogICAgICAgICAgICAgICAgICAgIHNlbGYuX2FkYXB0b3IuX21vZGVsID0gTm9u"
    "ZQogICAgICAgICAgICAgICAgaWYgVE9SQ0hfT0s6CiAgICAgICAgICAgICAgICAgICAgdG9yY2guY3VkYS5lbXB0eV9jYWNoZSgp"
    "CiAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLl9sb2FkZWQgPSBGYWxzZQogICAgICAgICAgICAgICAgc2VsZi5fbW9kZWxf"
    "bG9hZGVkICAgID0gRmFsc2UKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW1RPUlBPUl0gTW9kZWwgdW5sb2Fk"
    "ZWQgZnJvbSBWUkFNLiIsICJPSyIpCiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltUT1JQT1JdIE1vZGVsIHVubG9hZCBlcnJvcjoge2V9Iiwg"
    "IkVSUk9SIgogICAgICAgICAgICAgICAgKQoKICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2ZhY2UoIm5ldXRyYWwiKQogICAgICAg"
    "IHNlbGYuX3NldF9zdGF0dXMoIlRPUlBPUiIpCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAg"
    "ICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKEZhbHNlKQoKICAgIGRlZiBfZXhpdF90b3Jwb3Ioc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICAjIENhbGN1bGF0ZSBzdXNwZW5kZWQgZHVyYXRpb24KICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2U6CiAgICAg"
    "ICAgICAgIGRlbHRhID0gZGF0ZXRpbWUubm93KCkgLSBzZWxmLl90b3Jwb3Jfc2luY2UKICAgICAgICAgICAgc2VsZi5fc3VzcGVu"
    "ZGVkX2R1cmF0aW9uID0gZm9ybWF0X2R1cmF0aW9uKGRlbHRhLnRvdGFsX3NlY29uZHMoKSkKICAgICAgICAgICAgc2VsZi5fdG9y"
    "cG9yX3NpbmNlID0gTm9uZQoKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIFdha2luZyBmcm9tIHRvcnBvci4u"
    "LiIsICJJTkZPIikKCiAgICAgICAgaWYgc2VsZi5fbW9kZWxfbG9hZGVkOgogICAgICAgICAgICAjIE9sbGFtYSBiYWNrZW5kIOKA"
    "lCBtb2RlbCB3YXMgbmV2ZXIgdW5sb2FkZWQsIGp1c3QgcmUtZW5hYmxlIFVJCiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0"
    "KCJTWVNURU0iLAogICAgICAgICAgICAgICAgZiJUaGUgdmVzc2VsIGVtcHRpZXMuIHtERUNLX05BTUV9IHN0aXJzICIKICAgICAg"
    "ICAgICAgICAgIGYiKHtzZWxmLl9zdXNwZW5kZWRfZHVyYXRpb24gb3IgJ2JyaWVmbHknfSBlbGFwc2VkKS4iCiAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsICJUaGUgY29ubmVjdGlvbiBob2xkcy4gU2hlIGlzIGxp"
    "c3RlbmluZy4iKQogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJJRExFIikKICAgICAgICAgICAgc2VsZi5fc2VuZF9idG4u"
    "c2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAg"
    "IHNlbGYuX2RpYWdfdGFiLmxvZygiW1RPUlBPUl0gQVdBS0UgbW9kZSDigJQgYXV0by10b3Jwb3IgZGlzYWJsZWQuIiwgIklORk8i"
    "KQogICAgICAgIGVsc2U6CiAgICAgICAgICAgICMgTG9jYWwgbW9kZWwgd2FzIHVubG9hZGVkIOKAlCBuZWVkIGZ1bGwgcmVsb2Fk"
    "CiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAgICAgZiJUaGUgdmVzc2VsIGVtcHRp"
    "ZXMuIHtERUNLX05BTUV9IHN0aXJzIGZyb20gdG9ycG9yICIKICAgICAgICAgICAgICAgIGYiKHtzZWxmLl9zdXNwZW5kZWRfZHVy"
    "YXRpb24gb3IgJ2JyaWVmbHknfSBlbGFwc2VkKS4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygi"
    "TE9BRElORyIpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlciA9IE1vZGVsTG9hZGVyV29ya2VyKHNlbGYuX2FkYXB0b3IpCiAgICAg"
    "ICAgICAgIHNlbGYuX2xvYWRlci5tZXNzYWdlLmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1iZGEgbTogc2VsZi5fYXBwZW5k"
    "X2NoYXQoIlNZU1RFTSIsIG0pKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuZXJyb3IuY29ubmVjdCgKICAgICAgICAgICAgICAg"
    "IGxhbWJkYSBlOiBzZWxmLl9hcHBlbmRfY2hhdCgiRVJST1IiLCBlKSkKICAgICAgICAgICAgc2VsZi5fbG9hZGVyLmxvYWRfY29t"
    "cGxldGUuY29ubmVjdChzZWxmLl9vbl9sb2FkX2NvbXBsZXRlKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuZmluaXNoZWQuY29u"
    "bmVjdChzZWxmLl9sb2FkZXIuZGVsZXRlTGF0ZXIpCiAgICAgICAgICAgIHNlbGYuX2FjdGl2ZV90aHJlYWRzLmFwcGVuZChzZWxm"
    "Ll9sb2FkZXIpCiAgICAgICAgICAgIHNlbGYuX2xvYWRlci5zdGFydCgpCgogICAgZGVmIF9jaGVja192cmFtX3ByZXNzdXJlKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIGV2ZXJ5IDUgc2Vjb25kcyBmcm9tIEFQU2NoZWR1bGVyIHdo"
    "ZW4gdG9ycG9yIHN0YXRlIGlzIEFVVE8uCiAgICAgICAgT25seSB0cmlnZ2VycyB0b3Jwb3IgaWYgZXh0ZXJuYWwgVlJBTSB1c2Fn"
    "ZSBleGNlZWRzIHRocmVzaG9sZAogICAgICAgIEFORCBpcyBzdXN0YWluZWQg4oCUIG5ldmVyIHRyaWdnZXJzIG9uIHRoZSBwZXJz"
    "b25hJ3Mgb3duIGZvb3RwcmludC4KICAgICAgICAiIiIKICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc3RhdGUgIT0gIkFVVE8iOgog"
    "ICAgICAgICAgICByZXR1cm4KICAgICAgICBpZiBub3QgTlZNTF9PSyBvciBub3QgZ3B1X2hhbmRsZToKICAgICAgICAgICAgcmV0"
    "dXJuCiAgICAgICAgaWYgc2VsZi5fZGVja192cmFtX2Jhc2UgPD0gMDoKICAgICAgICAgICAgcmV0dXJuCgogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgbWVtX2luZm8gID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAg"
    "ICAgIHRvdGFsX3VzZWQgPSBtZW1faW5mby51c2VkIC8gMTAyNCoqMwogICAgICAgICAgICBleHRlcm5hbCAgID0gdG90YWxfdXNl"
    "ZCAtIHNlbGYuX2RlY2tfdnJhbV9iYXNlCgogICAgICAgICAgICBpZiBleHRlcm5hbCA+IHNlbGYuX0VYVEVSTkFMX1ZSQU1fVE9S"
    "UE9SX0dCOgogICAgICAgICAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAg"
    "ICAgIHJldHVybiAgIyBBbHJlYWR5IGluIHRvcnBvciDigJQgZG9uJ3Qga2VlcCBjb3VudGluZwogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fdnJhbV9wcmVzc3VyZV90aWNrcyArPSAxCiAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyAgICA9IDAK"
    "ICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltUT1JQT1IgQVVUT10gRXh0"
    "ZXJuYWwgVlJBTSBwcmVzc3VyZTogIgogICAgICAgICAgICAgICAgICAgIGYie2V4dGVybmFsOi4yZn1HQiAiCiAgICAgICAgICAg"
    "ICAgICAgICAgZiIodGljayB7c2VsZi5fdnJhbV9wcmVzc3VyZV90aWNrc30vIgogICAgICAgICAgICAgICAgICAgIGYie3NlbGYu"
    "X1RPUlBPUl9TVVNUQUlORURfVElDS1N9KSIsICJXQVJOIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgKHNl"
    "bGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgPj0gc2VsZi5fVE9SUE9SX1NVU1RBSU5FRF9USUNLUwogICAgICAgICAgICAgICAgICAg"
    "ICAgICBhbmQgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIE5vbmUpOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX2VudGVyX3RvcnBv"
    "cigKICAgICAgICAgICAgICAgICAgICAgICAgcmVhc29uPWYiYXV0byDigJQge2V4dGVybmFsOi4xZn1HQiBleHRlcm5hbCBWUkFN"
    "ICIKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYicHJlc3N1cmUgc3VzdGFpbmVkIgogICAgICAgICAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMCAgIyByZXNldCBhZnRlciBlbnRlcmlu"
    "ZyB0b3Jwb3IKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlja3MgPSAwCiAg"
    "ICAgICAgICAgICAgICBpZiBzZWxmLl90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5f"
    "dnJhbV9yZWxpZWZfdGlja3MgKz0gMQogICAgICAgICAgICAgICAgICAgIGF1dG9fd2FrZSA9IENGR1sic2V0dGluZ3MiXS5nZXQo"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICJhdXRvX3dha2Vfb25fcmVsaWVmIiwgRmFsc2UKICAgICAgICAgICAgICAgICAgICAp"
    "CiAgICAgICAgICAgICAgICAgICAgaWYgKGF1dG9fd2FrZSBhbmQKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX3Zy"
    "YW1fcmVsaWVmX3RpY2tzID49IHNlbGYuX1dBS0VfU1VTVEFJTkVEX1RJQ0tTKToKICAgICAgICAgICAgICAgICAgICAgICAgc2Vs"
    "Zi5fdnJhbV9yZWxpZWZfdGlja3MgPSAwCiAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX2V4aXRfdG9ycG9yKCkKCiAgICAg"
    "ICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBm"
    "IltUT1JQT1IgQVVUT10gVlJBTSBjaGVjayBlcnJvcjoge2V9IiwgIkVSUk9SIgogICAgICAgICAgICApCgogICAgIyDilIDilIAg"
    "QVBTQ0hFRFVMRVIgU0VUVVAg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3NldHVwX3NjaGVkdWxlcihzZWxmKSAtPiBOb25lOgogICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgZnJvbSBhcHNjaGVkdWxlci5zY2hlZHVsZXJzLmJhY2tncm91bmQgaW1wb3J0IEJhY2tncm91"
    "bmRTY2hlZHVsZXIKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyID0gQmFja2dyb3VuZFNjaGVkdWxlcigKICAgICAgICAgICAg"
    "ICAgIGpvYl9kZWZhdWx0cz17Im1pc2ZpcmVfZ3JhY2VfdGltZSI6IDYwfQogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IElt"
    "cG9ydEVycm9yOgogICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIgPSBOb25lCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxv"
    "ZygKICAgICAgICAgICAgICAgICJbU0NIRURVTEVSXSBhcHNjaGVkdWxlciBub3QgYXZhaWxhYmxlIOKAlCAiCiAgICAgICAgICAg"
    "ICAgICAiaWRsZSwgYXV0b3NhdmUsIGFuZCByZWZsZWN0aW9uIGRpc2FibGVkLiIsICJXQVJOIgogICAgICAgICAgICApCiAgICAg"
    "ICAgICAgIHJldHVybgoKICAgICAgICBpbnRlcnZhbF9taW4gPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJhdXRvc2F2ZV9pbnRlcnZh"
    "bF9taW51dGVzIiwgMTApCgogICAgICAgICMgQXV0b3NhdmUKICAgICAgICBzZWxmLl9zY2hlZHVsZXIuYWRkX2pvYigKICAgICAg"
    "ICAgICAgc2VsZi5fYXV0b3NhdmUsICJpbnRlcnZhbCIsCiAgICAgICAgICAgIG1pbnV0ZXM9aW50ZXJ2YWxfbWluLCBpZD0iYXV0"
    "b3NhdmUiCiAgICAgICAgKQoKICAgICAgICAjIFZSQU0gcHJlc3N1cmUgY2hlY2sgKGV2ZXJ5IDVzKQogICAgICAgIHNlbGYuX3Nj"
    "aGVkdWxlci5hZGRfam9iKAogICAgICAgICAgICBzZWxmLl9jaGVja192cmFtX3ByZXNzdXJlLCAiaW50ZXJ2YWwiLAogICAgICAg"
    "ICAgICBzZWNvbmRzPTUsIGlkPSJ2cmFtX2NoZWNrIgogICAgICAgICkKCiAgICAgICAgIyBJZGxlIHRyYW5zbWlzc2lvbiAoc3Rh"
    "cnRzIHBhdXNlZCDigJQgZW5hYmxlZCBieSBpZGxlIHRvZ2dsZSkKICAgICAgICBpZGxlX21pbiA9IENGR1sic2V0dGluZ3MiXS5n"
    "ZXQoImlkbGVfbWluX21pbnV0ZXMiLCAxMCkKICAgICAgICBpZGxlX21heCA9IENGR1sic2V0dGluZ3MiXS5nZXQoImlkbGVfbWF4"
    "X21pbnV0ZXMiLCAzMCkKICAgICAgICBpZGxlX2ludGVydmFsID0gKGlkbGVfbWluICsgaWRsZV9tYXgpIC8vIDIKCiAgICAgICAg"
    "c2VsZi5fc2NoZWR1bGVyLmFkZF9qb2IoCiAgICAgICAgICAgIHNlbGYuX2ZpcmVfaWRsZV90cmFuc21pc3Npb24sICJpbnRlcnZh"
    "bCIsCiAgICAgICAgICAgIG1pbnV0ZXM9aWRsZV9pbnRlcnZhbCwgaWQ9ImlkbGVfdHJhbnNtaXNzaW9uIgogICAgICAgICkKCiAg"
    "ICAgICAgIyBDeWNsZSB3aWRnZXQgcmVmcmVzaCAoZXZlcnkgNiBob3VycykKICAgICAgICBpZiBzZWxmLl9jeWNsZV93aWRnZXQg"
    "aXMgbm90IE5vbmU6CiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAgICAgICAgICAgc2VsZi5fY3lj"
    "bGVfd2lkZ2V0LnVwZGF0ZVBoYXNlLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICAgICAgaG91cnM9NiwgaWQ9Im1vb25fcmVmcmVz"
    "aCIKICAgICAgICAgICAgKQoKICAgICAgICAjIE5PVEU6IHNjaGVkdWxlci5zdGFydCgpIGlzIGNhbGxlZCBmcm9tIHN0YXJ0X3Nj"
    "aGVkdWxlcigpCiAgICAgICAgIyB3aGljaCBpcyB0cmlnZ2VyZWQgdmlhIFFUaW1lci5zaW5nbGVTaG90IEFGVEVSIHRoZSB3aW5k"
    "b3cKICAgICAgICAjIGlzIHNob3duIGFuZCB0aGUgUXQgZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgICAgICMgRG8gTk9UIGNh"
    "bGwgc2VsZi5fc2NoZWR1bGVyLnN0YXJ0KCkgaGVyZS4KCiAgICBkZWYgc3RhcnRfc2NoZWR1bGVyKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBhZnRlciB3aW5kb3cuc2hvdygpIGFuZCBhcHAu"
    "ZXhlYygpIGJlZ2lucy4KICAgICAgICBEZWZlcnJlZCB0byBlbnN1cmUgUXQgZXZlbnQgbG9vcCBpcyBydW5uaW5nIGJlZm9yZSBi"
    "YWNrZ3JvdW5kIHRocmVhZHMgc3RhcnQuCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1bGVyIGlzIE5vbmU6CiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnN0YXJ0KCkKICAgICAgICAg"
    "ICAgIyBJZGxlIHN0YXJ0cyBwYXVzZWQKICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFuc21p"
    "c3Npb24iKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltTQ0hFRFVMRVJdIEFQU2NoZWR1bGVyIHN0YXJ0ZWQuIiwg"
    "Ik9LIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltTQ0hF"
    "RFVMRVJdIFN0YXJ0IGVycm9yOiB7ZX0iLCAiRVJST1IiKQoKICAgIGRlZiBfYXV0b3NhdmUoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICB0cnk6CiAgICAgICAgICAgIHNlbGYuX3Nlc3Npb25zLnNhdmUoKQogICAgICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIu"
    "c2V0X2F1dG9zYXZlX2luZGljYXRvcihUcnVlKQogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgKICAgICAgICAgICAgICAg"
    "IDMwMDAsIGxhbWJkYTogc2VsZi5fam91cm5hbF9zaWRlYmFyLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3IoRmFsc2UpCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbQVVUT1NBVkVdIFNlc3Npb24gc2F2ZWQuIiwgIklORk8iKQog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0FVVE9TQVZFXSBF"
    "cnJvcjoge2V9IiwgIkVSUk9SIikKCiAgICBkZWYgX2ZpcmVfaWRsZV90cmFuc21pc3Npb24oc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBpZiBub3Qgc2VsZi5fbW9kZWxfbG9hZGVkIG9yIHNlbGYuX3N0YXR1cyA9PSAiR0VORVJBVElORyI6CiAgICAgICAgICAgIHJl"
    "dHVybgogICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgIyBJbiB0b3Jwb3Ig4oCU"
    "IGNvdW50IHRoZSBwZW5kaW5nIHRob3VnaHQgYnV0IGRvbid0IGdlbmVyYXRlCiAgICAgICAgICAgIHNlbGYuX3BlbmRpbmdfdHJh"
    "bnNtaXNzaW9ucyArPSAxCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0lETEVdIElu"
    "IHRvcnBvciDigJQgcGVuZGluZyB0cmFuc21pc3Npb24gIgogICAgICAgICAgICAgICAgZiIje3NlbGYuX3BlbmRpbmdfdHJhbnNt"
    "aXNzaW9uc30iLCAiSU5GTyIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgbW9kZSA9IHJhbmRvbS5j"
    "aG9pY2UoWyJERUVQRU5JTkciLCJCUkFOQ0hJTkciLCJTWU5USEVTSVMiXSkKICAgICAgICB2YW1waXJlX2N0eCA9IGJ1aWxkX3Zh"
    "bXBpcmVfY29udGV4dCgpCiAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKCiAgICAgICAgc2Vs"
    "Zi5faWRsZV93b3JrZXIgPSBJZGxlV29ya2VyKAogICAgICAgICAgICBzZWxmLl9hZGFwdG9yLAogICAgICAgICAgICBTWVNURU1f"
    "UFJPTVBUX0JBU0UsCiAgICAgICAgICAgIGhpc3RvcnksCiAgICAgICAgICAgIG1vZGU9bW9kZSwKICAgICAgICAgICAgdmFtcGly"
    "ZV9jb250ZXh0PXZhbXBpcmVfY3R4LAogICAgICAgICkKICAgICAgICBkZWYgX29uX2lkbGVfcmVhZHkodDogc3RyKSAtPiBOb25l"
    "OgogICAgICAgICAgICAjIEZsaXAgdG8gU2VsZiB0YWIgYW5kIGFwcGVuZCB0aGVyZQogICAgICAgICAgICBzZWxmLl9tYWluX3Rh"
    "YnMuc2V0Q3VycmVudEluZGV4KDEpCiAgICAgICAgICAgIHRzID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNIikKICAg"
    "ICAgICAgICAgc2VsZi5fc2VsZl9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntD"
    "X1RFWFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7dHN9XSBbe21vZGV9XTwvc3Bhbj48YnI+"
    "JwogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfR09MRH07Ij57dH08L3NwYW4+PGJyPicKICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICBzZWxmLl9zZWxmX3RhYi5hcHBlbmQoIk5BUlJBVElWRSIsIHQpCgogICAgICAgIHNlbGYuX2lkbGVf"
    "d29ya2VyLnRyYW5zbWlzc2lvbl9yZWFkeS5jb25uZWN0KF9vbl9pZGxlX3JlYWR5KQogICAgICAgIHNlbGYuX2lkbGVfd29ya2Vy"
    "LmVycm9yX29jY3VycmVkLmNvbm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9kaWFnX3RhYi5sb2coZiJbSURMRSBF"
    "UlJPUl0ge2V9IiwgIkVSUk9SIikKICAgICAgICApCiAgICAgICAgc2VsZi5faWRsZV93b3JrZXIuc3RhcnQoKQoKICAgICMg4pSA"
    "4pSAIEpPVVJOQUwgU0VTU0lPTiBMT0FESU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9sb2FkX2pvdXJuYWxfc2Vzc2lvbihzZWxmLCBkYXRlX3N0cjogc3RyKSAt"
    "PiBOb25lOgogICAgICAgIGN0eCA9IHNlbGYuX3Nlc3Npb25zLmxvYWRfc2Vzc2lvbl9hc19jb250ZXh0KGRhdGVfc3RyKQogICAg"
    "ICAgIGlmIG5vdCBjdHg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0pPVVJOQUxd"
    "IE5vIHNlc3Npb24gZm91bmQgZm9yIHtkYXRlX3N0cn0iLCAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4K"
    "ICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2V0X2pvdXJuYWxfbG9hZGVkKGRhdGVfc3RyKQogICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbSk9VUk5BTF0gTG9hZGVkIHNlc3Npb24gZnJvbSB7ZGF0ZV9zdHJ9IGFzIGNvbnRl"
    "eHQuICIKICAgICAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBub3cgYXdhcmUgb2YgdGhhdCBjb252ZXJzYXRpb24uIiwgIk9LIgog"
    "ICAgICAgICkKICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgZiJBIG1lbW9yeSBzdGlycy4u"
    "LiB0aGUgam91cm5hbCBvZiB7ZGF0ZV9zdHJ9IG9wZW5zIGJlZm9yZSBoZXIuIgogICAgICAgICkKICAgICAgICAjIE5vdGlmeSBN"
    "b3JnYW5uYQogICAgICAgIGlmIHNlbGYuX21vZGVsX2xvYWRlZDoKICAgICAgICAgICAgbm90ZSA9ICgKICAgICAgICAgICAgICAg"
    "IGYiW0pPVVJOQUwgTE9BREVEXSBUaGUgdXNlciBoYXMgb3BlbmVkIHRoZSBqb3VybmFsIGZyb20gIgogICAgICAgICAgICAgICAg"
    "ZiJ7ZGF0ZV9zdHJ9LiBBY2tub3dsZWRnZSB0aGlzIGJyaWVmbHkg4oCUIHlvdSBub3cgaGF2ZSAiCiAgICAgICAgICAgICAgICBm"
    "ImF3YXJlbmVzcyBvZiB0aGF0IGNvbnZlcnNhdGlvbi4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbnMu"
    "YWRkX21lc3NhZ2UoInN5c3RlbSIsIG5vdGUpCgogICAgZGVmIF9jbGVhcl9qb3VybmFsX3Nlc3Npb24oc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9zZXNzaW9ucy5jbGVhcl9sb2FkZWRfam91cm5hbCgpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJb"
    "Sk9VUk5BTF0gSm91cm5hbCBjb250ZXh0IGNsZWFyZWQuIiwgIklORk8iKQogICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNU"
    "RU0iLAogICAgICAgICAgICAiVGhlIGpvdXJuYWwgY2xvc2VzLiBPbmx5IHRoZSBwcmVzZW50IHJlbWFpbnMuIgogICAgICAgICkK"
    "CiAgICAjIOKUgOKUgCBTVEFUUyBVUERBVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3VwZGF0ZV9zdGF0"
    "cyhzZWxmKSAtPiBOb25lOgogICAgICAgIGVsYXBzZWQgPSBpbnQodGltZS50aW1lKCkgLSBzZWxmLl9zZXNzaW9uX3N0YXJ0KQog"
    "ICAgICAgIGgsIG0sIHMgPSBlbGFwc2VkIC8vIDM2MDAsIChlbGFwc2VkICUgMzYwMCkgLy8gNjAsIGVsYXBzZWQgJSA2MAogICAg"
    "ICAgIHNlc3Npb25fc3RyID0gZiJ7aDowMmR9OnttOjAyZH06e3M6MDJkfSIKCiAgICAgICAgc2VsZi5faHdfcGFuZWwuc2V0X3N0"
    "YXR1c19sYWJlbHMoCiAgICAgICAgICAgIHNlbGYuX3N0YXR1cywKICAgICAgICAgICAgQ0ZHWyJtb2RlbCJdLmdldCgidHlwZSIs"
    "ImxvY2FsIikudXBwZXIoKSwKICAgICAgICAgICAgc2Vzc2lvbl9zdHIsCiAgICAgICAgICAgIHN0cihzZWxmLl90b2tlbl9jb3Vu"
    "dCksCiAgICAgICAgKQogICAgICAgIHNlbGYuX2h3X3BhbmVsLnVwZGF0ZV9zdGF0cygpCgogICAgICAgICMgTGVmdCBzcGhlcmUg"
    "PSBhY3RpdmUgcmVzZXJ2ZSBmcm9tIHJ1bnRpbWUgdG9rZW4gcG9vbAogICAgICAgIGxlZnRfb3JiX2ZpbGwgPSBtaW4oMS4wLCBz"
    "ZWxmLl90b2tlbl9jb3VudCAvIDQwOTYuMCkKICAgICAgICBpZiBzZWxmLl9sZWZ0X29yYiBpcyBub3QgTm9uZToKICAgICAgICAg"
    "ICAgc2VsZi5fbGVmdF9vcmIuc2V0RmlsbChsZWZ0X29yYl9maWxsLCBhdmFpbGFibGU9VHJ1ZSkKCiAgICAgICAgIyBSaWdodCBz"
    "cGhlcmUgPSBWUkFNIGF2YWlsYWJpbGl0eQogICAgICAgIGlmIHNlbGYuX3JpZ2h0X29yYiBpcyBub3QgTm9uZToKICAgICAgICAg"
    "ICAgaWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBtZW0g"
    "PSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgICAgICB2cmFtX3VzZWQg"
    "PSBtZW0udXNlZCAgLyAxMDI0KiozCiAgICAgICAgICAgICAgICAgICAgdnJhbV90b3QgID0gbWVtLnRvdGFsIC8gMTAyNCoqMwog"
    "ICAgICAgICAgICAgICAgICAgIHJpZ2h0X29yYl9maWxsID0gbWF4KDAuMCwgMS4wIC0gKHZyYW1fdXNlZCAvIHZyYW1fdG90KSkK"
    "ICAgICAgICAgICAgICAgICAgICBzZWxmLl9yaWdodF9vcmIuc2V0RmlsbChyaWdodF9vcmJfZmlsbCwgYXZhaWxhYmxlPVRydWUp"
    "CiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3JpZ2h0X29yYi5zZXRG"
    "aWxsKDAuMCwgYXZhaWxhYmxlPUZhbHNlKQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgc2VsZi5fcmlnaHRfb3Ji"
    "LnNldEZpbGwoMC4wLCBhdmFpbGFibGU9RmFsc2UpCgogICAgICAgICMgUHJpbWFyeSBlc3NlbmNlID0gaW52ZXJzZSBvZiBsZWZ0"
    "IHNwaGVyZSBmaWxsCiAgICAgICAgZXNzZW5jZV9wcmltYXJ5X3JhdGlvID0gMS4wIC0gbGVmdF9vcmJfZmlsbAogICAgICAgIGlm"
    "IEFJX1NUQVRFU19FTkFCTEVEOgogICAgICAgICAgICBzZWxmLl9lc3NlbmNlX3ByaW1hcnlfZ2F1Z2Uuc2V0VmFsdWUoZXNzZW5j"
    "ZV9wcmltYXJ5X3JhdGlvICogMTAwLCBmIntlc3NlbmNlX3ByaW1hcnlfcmF0aW8qMTAwOi4wZn0lIikKCiAgICAgICAgIyBTZWNv"
    "bmRhcnkgZXNzZW5jZSA9IFJBTSBmcmVlCiAgICAgICAgaWYgQUlfU1RBVEVTX0VOQUJMRUQ6CiAgICAgICAgICAgIGlmIFBTVVRJ"
    "TF9PSzoKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBtZW0gICAgICAgPSBwc3V0aWwudmlydHVhbF9t"
    "ZW1vcnkoKQogICAgICAgICAgICAgICAgICAgIGVzc2VuY2Vfc2Vjb25kYXJ5X3JhdGlvICA9IDEuMCAtIChtZW0udXNlZCAvIG1l"
    "bS50b3RhbCkKICAgICAgICAgICAgICAgICAgICBzZWxmLl9lc3NlbmNlX3NlY29uZGFyeV9nYXVnZS5zZXRWYWx1ZSgKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgZXNzZW5jZV9zZWNvbmRhcnlfcmF0aW8gKiAxMDAsIGYie2Vzc2VuY2Vfc2Vjb25kYXJ5X3JhdGlv"
    "KjEwMDouMGZ9JSIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAg"
    "ICAgICAgICAgICAgIHNlbGYuX2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdlLnNldFVuYXZhaWxhYmxlKCkKICAgICAgICAgICAgZWxz"
    "ZToKICAgICAgICAgICAgICAgIHNlbGYuX2Vzc2VuY2Vfc2Vjb25kYXJ5X2dhdWdlLnNldFVuYXZhaWxhYmxlKCkKCiAgICAgICAg"
    "IyBVcGRhdGUgam91cm5hbCBzaWRlYmFyIGF1dG9zYXZlIGZsYXNoCiAgICAgICAgc2VsZi5fam91cm5hbF9zaWRlYmFyLnJlZnJl"
    "c2goKQoKICAgICMg4pSA4pSAIENIQVQgRElTUExBWSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfYXBwZW5k"
    "X2NoYXQoc2VsZiwgc3BlYWtlcjogc3RyLCB0ZXh0OiBzdHIpIC0+IE5vbmU6CiAgICAgICAgY29sb3JzID0gewogICAgICAgICAg"
    "ICAiWU9VIjogICAgIENfR09MRCwKICAgICAgICAgICAgREVDS19OQU1FLnVwcGVyKCk6Q19HT0xELAogICAgICAgICAgICAiU1lT"
    "VEVNIjogIENfUFVSUExFLAogICAgICAgICAgICAiRVJST1IiOiAgIENfQkxPT0QsCiAgICAgICAgfQogICAgICAgIGxhYmVsX2Nv"
    "bG9ycyA9IHsKICAgICAgICAgICAgIllPVSI6ICAgICBDX0dPTERfRElNLAogICAgICAgICAgICBERUNLX05BTUUudXBwZXIoKTpD"
    "X0NSSU1TT04sCiAgICAgICAgICAgICJTWVNURU0iOiAgQ19QVVJQTEUsCiAgICAgICAgICAgICJFUlJPUiI6ICAgQ19CTE9PRCwK"
    "ICAgICAgICB9CiAgICAgICAgY29sb3IgICAgICAgPSBjb2xvcnMuZ2V0KHNwZWFrZXIsIENfR09MRCkKICAgICAgICBsYWJlbF9j"
    "b2xvciA9IGxhYmVsX2NvbG9ycy5nZXQoc3BlYWtlciwgQ19HT0xEX0RJTSkKICAgICAgICB0aW1lc3RhbXAgICA9IGRhdGV0aW1l"
    "Lm5vdygpLnN0cmZ0aW1lKCIlSDolTTolUyIpCgogICAgICAgIGlmIHNwZWFrZXIgPT0gIlNZU1RFTSI6CiAgICAgICAgICAgIHNl"
    "bGYuX2NoYXRfZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07"
    "IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICAgICAgZidbe3RpbWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgICAg"
    "ICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7bGFiZWxfY29sb3J9OyI+4pymIHt0ZXh0fTwvc3Bhbj4nCiAgICAgICAgICAgICkKICAg"
    "ICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKAogICAgICAgICAgICAgICAgZic8c3BhbiBz"
    "dHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicKICAgICAgICAgICAgICAgIGYnW3t0aW1lc3RhbXB9"
    "XSA8L3NwYW4+JwogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2xhYmVsX2NvbG9yfTsgZm9udC13ZWlnaHQ6"
    "Ym9sZDsiPicKICAgICAgICAgICAgICAgIGYne3NwZWFrZXJ9IOKdpzwvc3Bhbj4gJwogICAgICAgICAgICAgICAgZic8c3BhbiBz"
    "dHlsZT0iY29sb3I6e2NvbG9yfTsiPnt0ZXh0fTwvc3Bhbj4nCiAgICAgICAgICAgICkKCiAgICAgICAgIyBBZGQgYmxhbmsgbGlu"
    "ZSBhZnRlciBNb3JnYW5uYSdzIHJlc3BvbnNlIChub3QgZHVyaW5nIHN0cmVhbWluZykKICAgICAgICBpZiBzcGVha2VyID09IERF"
    "Q0tfTkFNRS51cHBlcigpOgogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuYXBwZW5kKCIiKQoKICAgICAgICBzZWxmLl9j"
    "aGF0X2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZl"
    "cnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgICMg4pSA4pSAIFNUQVRVUyDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfZ2V0X2dvb2dsZV9yZWZyZXNoX2ludGVydmFsX21zKHNlbGYp"
    "IC0+IGludDoKICAgICAgICBzZXR0aW5ncyA9IENGRy5nZXQoInNldHRpbmdzIiwge30pCiAgICAgICAgdmFsID0gc2V0dGluZ3Mu"
    "Z2V0KCJnb29nbGVfaW5ib3VuZF9pbnRlcnZhbF9tcyIsIDMwMDAwMCkKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVybiBt"
    "YXgoMTAwMCwgaW50KHZhbCkpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIDMwMDAwMAoKICAg"
    "IGRlZiBfZ2V0X2VtYWlsX3JlZnJlc2hfaW50ZXJ2YWxfbXMoc2VsZikgLT4gaW50OgogICAgICAgIHNldHRpbmdzID0gQ0ZHLmdl"
    "dCgic2V0dGluZ3MiLCB7fSkKICAgICAgICB2YWwgPSBzZXR0aW5ncy5nZXQoImVtYWlsX3JlZnJlc2hfaW50ZXJ2YWxfbXMiLCAz"
    "MDAwMDApCiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXR1cm4gbWF4KDEwMDAsIGludCh2YWwpKQogICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb246CiAgICAgICAgICAgIHJldHVybiAzMDAwMDAKCiAgICBkZWYgX3NldF9nb29nbGVfcmVmcmVzaF9zZWNvbmRzKHNl"
    "bGYsIHNlY29uZHM6IGludCkgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNlY29uZHMgPSBtYXgoNSwgbWluKDYw"
    "MCwgaW50KHNlY29uZHMpKSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBDRkdb"
    "InNldHRpbmdzIl1bImdvb2dsZV9pbmJvdW5kX2ludGVydmFsX21zIl0gPSBzZWNvbmRzICogMTAwMAogICAgICAgIHNhdmVfY29u"
    "ZmlnKENGRykKICAgICAgICBmb3IgdGltZXIgaW4gKHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyLCBzZWxmLl9nb29nbGVfcmVj"
    "b3Jkc19yZWZyZXNoX3RpbWVyKToKICAgICAgICAgICAgaWYgdGltZXIgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICB0aW1l"
    "ci5zdGFydChzZWxmLl9nZXRfZ29vZ2xlX3JlZnJlc2hfaW50ZXJ2YWxfbXMoKSkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "ZiJbU0VUVElOR1NdIEdvb2dsZSByZWZyZXNoIGludGVydmFsIHNldCB0byB7c2Vjb25kc30gc2Vjb25kKHMpLiIsICJPSyIpCgog"
    "ICAgZGVmIF9zZXRfZW1haWxfcmVmcmVzaF9taW51dGVzX2Zyb21fdGV4dChzZWxmLCB0ZXh0OiBzdHIpIC0+IE5vbmU6CiAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICBtaW51dGVzID0gbWF4KDEsIGludChmbG9hdChzdHIodGV4dCkuc3RyaXAoKSkpKQogICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHJldHVybgogICAgICAgIENGR1sic2V0dGluZ3MiXVsiZW1haWxfcmVmcmVz"
    "aF9pbnRlcnZhbF9tcyJdID0gbWludXRlcyAqIDYwMDAwCiAgICAgICAgc2F2ZV9jb25maWcoQ0ZHKQogICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbU0VUVElOR1NdIEVtYWlsIHJlZnJlc2ggaW50ZXJ2YWwgc2V0IHRvIHttaW51dGVz"
    "fSBtaW51dGUocykgKGNvbmZpZyBmb3VuZGF0aW9uKS4iLAogICAgICAgICAgICAiSU5GTyIsCiAgICAgICAgKQoKICAgIGRlZiBf"
    "c2V0X3RpbWV6b25lX2F1dG9fZGV0ZWN0KHNlbGYsIGVuYWJsZWQ6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgQ0ZHWyJzZXR0aW5n"
    "cyJdWyJ0aW1lem9uZV9hdXRvX2RldGVjdCJdID0gYm9vbChlbmFibGVkKQogICAgICAgIHNhdmVfY29uZmlnKENGRykKICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICJbU0VUVElOR1NdIFRpbWUgem9uZSBtb2RlIHNldCB0byBhdXRvLWRl"
    "dGVjdC4iIGlmIGVuYWJsZWQgZWxzZSAiW1NFVFRJTkdTXSBUaW1lIHpvbmUgbW9kZSBzZXQgdG8gbWFudWFsIG92ZXJyaWRlLiIs"
    "CiAgICAgICAgICAgICJJTkZPIiwKICAgICAgICApCgogICAgZGVmIF9zZXRfdGltZXpvbmVfb3ZlcnJpZGUoc2VsZiwgdHpfbmFt"
    "ZTogc3RyKSAtPiBOb25lOgogICAgICAgIHR6X3ZhbHVlID0gc3RyKHR6X25hbWUgb3IgIiIpLnN0cmlwKCkKICAgICAgICBDRkdb"
    "InNldHRpbmdzIl1bInRpbWV6b25lX292ZXJyaWRlIl0gPSB0el92YWx1ZQogICAgICAgIHNhdmVfY29uZmlnKENGRykKICAgICAg"
    "ICBpZiB0el92YWx1ZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1NFVFRJTkdTXSBUaW1lIHpvbmUgb3ZlcnJp"
    "ZGUgc2V0IHRvIHt0el92YWx1ZX0uIiwgIklORk8iKQoKICAgIGRlZiBfc2V0X3N0YXR1cyhzZWxmLCBzdGF0dXM6IHN0cikgLT4g"
    "Tm9uZToKICAgICAgICBzZWxmLl9zdGF0dXMgPSBzdGF0dXMKICAgICAgICBzdGF0dXNfY29sb3JzID0gewogICAgICAgICAgICAi"
    "SURMRSI6ICAgICAgIENfR09MRCwKICAgICAgICAgICAgIkdFTkVSQVRJTkciOiBDX0NSSU1TT04sCiAgICAgICAgICAgICJMT0FE"
    "SU5HIjogICAgQ19QVVJQTEUsCiAgICAgICAgICAgICJFUlJPUiI6ICAgICAgQ19CTE9PRCwKICAgICAgICAgICAgIk9GRkxJTkUi"
    "OiAgICBDX0JMT09ELAogICAgICAgICAgICAiVE9SUE9SIjogICAgIENfUFVSUExFX0RJTSwKICAgICAgICB9CiAgICAgICAgY29s"
    "b3IgPSBzdGF0dXNfY29sb3JzLmdldChzdGF0dXMsIENfVEVYVF9ESU0pCgogICAgICAgIHRvcnBvcl9sYWJlbCA9IGYi4peJIHtV"
    "SV9UT1JQT1JfU1RBVFVTfSIgaWYgc3RhdHVzID09ICJUT1JQT1IiIGVsc2UgZiLil4kge3N0YXR1c30iCiAgICAgICAgc2VsZi5z"
    "dGF0dXNfbGFiZWwuc2V0VGV4dCh0b3Jwb3JfbGFiZWwpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiAxMnB4OyBmb250LXdlaWdodDogYm9sZDsgYm9yZGVyOiBu"
    "b25lOyIKICAgICAgICApCgogICAgZGVmIF9ibGluayhzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2JsaW5rX3N0YXRlID0g"
    "bm90IHNlbGYuX2JsaW5rX3N0YXRlCiAgICAgICAgaWYgc2VsZi5fc3RhdHVzID09ICJHRU5FUkFUSU5HIjoKICAgICAgICAgICAg"
    "Y2hhciA9ICLil4kiIGlmIHNlbGYuX2JsaW5rX3N0YXRlIGVsc2UgIuKXjiIKICAgICAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwu"
    "c2V0VGV4dChmIntjaGFyfSBHRU5FUkFUSU5HIikKICAgICAgICBlbGlmIHNlbGYuX3N0YXR1cyA9PSAiVE9SUE9SIjoKICAgICAg"
    "ICAgICAgY2hhciA9ICLil4kiIGlmIHNlbGYuX2JsaW5rX3N0YXRlIGVsc2UgIuKKmCIKICAgICAgICAgICAgc2VsZi5zdGF0dXNf"
    "bGFiZWwuc2V0VGV4dCgKICAgICAgICAgICAgICAgIGYie2NoYXJ9IHtVSV9UT1JQT1JfU1RBVFVTfSIKICAgICAgICAgICAgKQoK"
    "ICAgICMg4pSA4pSAIElETEUgVE9HR0xFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9vbl9pZGxlX3Rv"
    "Z2dsZWQoc2VsZiwgZW5hYmxlZDogYm9vbCkgLT4gTm9uZToKICAgICAgICBDRkdbInNldHRpbmdzIl1bImlkbGVfZW5hYmxlZCJd"
    "ID0gZW5hYmxlZAogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldFRleHQoIklETEUgT04iIGlmIGVuYWJsZWQgZWxzZSAiSURMRSBP"
    "RkYiKQogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogeycjMWEx"
    "MDA1JyBpZiBlbmFibGVkIGVsc2UgQ19CRzN9OyAiCiAgICAgICAgICAgIGYiY29sb3I6IHsnI2NjODgyMicgaWYgZW5hYmxlZCBl"
    "bHNlIENfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQgeycjY2M4ODIyJyBpZiBlbmFibGVkIGVs"
    "c2UgQ19CT1JERVJ9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyBmb250LXNpemU6IDlweDsgZm9udC13ZWln"
    "aHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJwYWRkaW5nOiAzcHggOHB4OyIKICAgICAgICApCiAgICAgICAgc2F2ZV9jb25maWco"
    "Q0ZHKQogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRy"
    "eToKICAgICAgICAgICAgICAgIGlmIGVuYWJsZWQ6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnJlc3VtZV9q"
    "b2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltJRExFXSBJZGxl"
    "IHRyYW5zbWlzc2lvbiBlbmFibGVkLiIsICJPSyIpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIHNl"
    "bGYuX3NjaGVkdWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFn"
    "X3RhYi5sb2coIltJRExFXSBJZGxlIHRyYW5zbWlzc2lvbiBwYXVzZWQuIiwgIklORk8iKQogICAgICAgICAgICBleGNlcHQgRXhj"
    "ZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbSURMRV0gVG9nZ2xlIGVycm9yOiB7ZX0i"
    "LCAiRVJST1IiKQoKICAgICMg4pSA4pSAIFdJTkRPVyBDT05UUk9MUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfdG9nZ2xl"
    "X2Z1bGxzY3JlZW4oc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBzZWxmLmlzRnVsbFNjcmVlbigpOgogICAgICAgICAgICBzZWxm"
    "LnNob3dOb3JtYWwoKQogICAgICAgICAgICBDRkdbInNldHRpbmdzIl1bImZ1bGxzY3JlZW5fZW5hYmxlZCJdID0gRmFsc2UKICAg"
    "ICAgICAgICAgc2VsZi5fZnNfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307"
    "IGNvbG9yOiB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9E"
    "SU19OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMCA4cHg7"
    "IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAgc2VsZi5zaG93RnVsbFNjcmVlbigpCiAgICAgICAgICAg"
    "IENGR1sic2V0dGluZ3MiXVsiZnVsbHNjcmVlbl9lbmFibGVkIl0gPSBUcnVlCiAgICAgICAgICAgIHNlbGYuX2ZzX2J0bi5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19DUklNU09OX0RJTX07IGNvbG9yOiB7Q19DUklNU09O"
    "fTsgIgogICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OfTsgZm9udC1zaXplOiA5cHg7ICIKICAg"
    "ICAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDAgOHB4OyIKICAgICAgICAgICAgKQogICAgICAgIHNh"
    "dmVfY29uZmlnKENGRykKCiAgICBkZWYgX3RvZ2dsZV9ib3JkZXJsZXNzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaXNfYmwgPSBi"
    "b29sKHNlbGYud2luZG93RmxhZ3MoKSAmIFF0LldpbmRvd1R5cGUuRnJhbWVsZXNzV2luZG93SGludCkKICAgICAgICBpZiBpc19i"
    "bDoKICAgICAgICAgICAgc2VsZi5zZXRXaW5kb3dGbGFncygKICAgICAgICAgICAgICAgIHNlbGYud2luZG93RmxhZ3MoKSAmIH5R"
    "dC5XaW5kb3dUeXBlLkZyYW1lbGVzc1dpbmRvd0hpbnQKICAgICAgICAgICAgKQogICAgICAgICAgICBDRkdbInNldHRpbmdzIl1b"
    "ImJvcmRlcmxlc3NfZW5hYmxlZCJdID0gRmFsc2UKICAgICAgICAgICAgc2VsZi5fYmxfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAg"
    "ICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgICAg"
    "IGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJm"
    "b250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMCA4cHg7IgogICAgICAgICAgICApCiAgICAgICAgZWxzZToKICAgICAgICAgICAg"
    "aWYgc2VsZi5pc0Z1bGxTY3JlZW4oKToKICAgICAgICAgICAgICAgIHNlbGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAgIHNlbGYu"
    "c2V0V2luZG93RmxhZ3MoCiAgICAgICAgICAgICAgICBzZWxmLndpbmRvd0ZsYWdzKCkgfCBRdC5XaW5kb3dUeXBlLkZyYW1lbGVz"
    "c1dpbmRvd0hpbnQKICAgICAgICAgICAgKQogICAgICAgICAgICBDRkdbInNldHRpbmdzIl1bImJvcmRlcmxlc3NfZW5hYmxlZCJd"
    "ID0gVHJ1ZQogICAgICAgICAgICBzZWxmLl9ibF9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3Vu"
    "ZDoge0NfQ1JJTVNPTl9ESU19OyBjb2xvcjoge0NfQ1JJTVNPTn07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29s"
    "aWQge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRk"
    "aW5nOiAwIDhweDsiCiAgICAgICAgICAgICkKICAgICAgICBzYXZlX2NvbmZpZyhDRkcpCiAgICAgICAgc2VsZi5zaG93KCkKCiAg"
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
    "hpIgUGFzcyA2Cg=="
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
