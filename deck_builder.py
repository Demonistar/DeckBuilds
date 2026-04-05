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
UI_RUNES              = "<<<RUNES>>>"

# System prompt and cognitive anchors
SYSTEM_PROMPT_BASE = """<<<SYSTEM_PROMPT>>>"""

COGNITIVE_ANCHORS = <<<COGNITIVE_ANCHORS>>>

# Special systems
VAMPIRE_STATES_ENABLED  = <<<VAMPIRE_STATES_ENABLED>>>
TORPOR_ENABLED          = <<<TORPOR_ENABLED>>>
ANCHOR_ENTITY           = <<<ANCHOR_ENTITY>>>

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
            "<<<VAMPIRE_STATES_ENABLED>>>": str(bool(persona.get("vampire_states", False))),
            "<<<TORPOR_ENABLED>>>":         str(bool(persona.get("torpor_system",  False))),
            "<<<ANCHOR_ENTITY>>>":          ae_literal,
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
    "IGJlaGF2aW9yYWwgc3RhdGUuIEFjdGl2ZSBvbmx5IHdoZW4gVkFNUElSRV9TVEFURVNfRU5BQkxF"
    "RD1UcnVlLgojIEluamVjdGVkIGludG8gc3lzdGVtIHByb21wdCBvbiBldmVyeSBnZW5lcmF0aW9u"
    "IGNhbGwuCgpWQU1QSVJFX1NUQVRFUzogZGljdFtzdHIsIGRpY3RdID0gewogICAgIldJVENISU5H"
    "IEhPVVIiOiAgeyJob3VycyI6IHswfSwgICAgICAgICAgICJjb2xvciI6IENfR09MRCwgICAgICAg"
    "ICJwb3dlciI6IDEuMH0sCiAgICAiREVFUCBOSUdIVCI6ICAgICB7ImhvdXJzIjogezEsMiwzfSwg"
    "ICAgICAgICJjb2xvciI6IENfUFVSUExFLCAgICAgICJwb3dlciI6IDAuOTV9LAogICAgIlRXSUxJ"
    "R0hUIEZBRElORyI6eyJob3VycyI6IHs0LDV9LCAgICAgICAgICAiY29sb3IiOiBDX1NJTFZFUiwg"
    "ICAgICAicG93ZXIiOiAwLjd9LAogICAgIkRPUk1BTlQiOiAgICAgICAgeyJob3VycyI6IHs2LDcs"
    "OCw5LDEwLDExfSwiY29sb3IiOiBDX1RFWFRfRElNLCAgICAicG93ZXIiOiAwLjJ9LAogICAgIlJF"
    "U1RMRVNTIFNMRUVQIjogeyJob3VycyI6IHsxMiwxMywxNCwxNX0sICAiY29sb3IiOiBDX1RFWFRf"
    "RElNLCAgICAicG93ZXIiOiAwLjN9LAogICAgIlNUSVJSSU5HIjogICAgICAgeyJob3VycyI6IHsx"
    "NiwxN30sICAgICAgICAiY29sb3IiOiBDX0dPTERfRElNLCAgICAicG93ZXIiOiAwLjZ9LAogICAg"
    "IkFXQUtFTkVEIjogICAgICAgeyJob3VycyI6IHsxOCwxOSwyMCwyMX0sICAiY29sb3IiOiBDX0dP"
    "TEQsICAgICAgICAicG93ZXIiOiAwLjl9LAogICAgIkhVTlRJTkciOiAgICAgICAgeyJob3VycyI6"
    "IHsyMiwyM30sICAgICAgICAiY29sb3IiOiBDX0NSSU1TT04sICAgICAicG93ZXIiOiAxLjB9LAp9"
    "CgpkZWYgZ2V0X3ZhbXBpcmVfc3RhdGUoKSAtPiBzdHI6CiAgICAiIiJSZXR1cm4gdGhlIGN1cnJl"
    "bnQgdmFtcGlyZSBzdGF0ZSBuYW1lIGJhc2VkIG9uIGxvY2FsIGhvdXIuIiIiCiAgICBoID0gZGF0"
    "ZXRpbWUubm93KCkuaG91cgogICAgZm9yIHN0YXRlX25hbWUsIGRhdGEgaW4gVkFNUElSRV9TVEFU"
    "RVMuaXRlbXMoKToKICAgICAgICBpZiBoIGluIGRhdGFbImhvdXJzIl06CiAgICAgICAgICAgIHJl"
    "dHVybiBzdGF0ZV9uYW1lCiAgICByZXR1cm4gIkRPUk1BTlQiCgpkZWYgZ2V0X3ZhbXBpcmVfc3Rh"
    "dGVfY29sb3Ioc3RhdGU6IHN0cikgLT4gc3RyOgogICAgcmV0dXJuIFZBTVBJUkVfU1RBVEVTLmdl"
    "dChzdGF0ZSwge30pLmdldCgiY29sb3IiLCBDX0dPTEQpCgpkZWYgYnVpbGRfdmFtcGlyZV9jb250"
    "ZXh0KCkgLT4gc3RyOgogICAgIiIiCiAgICBCdWlsZCB0aGUgdmFtcGlyZSBzdGF0ZSArIG1vb24g"
    "cGhhc2UgY29udGV4dCBzdHJpbmcgZm9yIHN5c3RlbSBwcm9tcHQgaW5qZWN0aW9uLgogICAgQ2Fs"
    "bGVkIGJlZm9yZSBldmVyeSBnZW5lcmF0aW9uLiBOZXZlciBjYWNoZWQg4oCUIGFsd2F5cyBmcmVz"
    "aC4KICAgICIiIgogICAgc3RhdGUgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICBwaGFzZSwgbW9v"
    "bl9uYW1lLCBpbGx1bSA9IGdldF9tb29uX3BoYXNlKCkKICAgIG5vdyA9IGRhdGV0aW1lLm5vdygp"
    "LnN0cmZ0aW1lKCIlSDolTSIpCgogICAgX3AgPSBERUNLX1BST05PVU5fU1VCSkVDVC5jYXBpdGFs"
    "aXplKCkgaWYgREVDS19QUk9OT1VOX1NVQkpFQ1QgZWxzZSBERUNLX05BTUUKICAgIF9wbyA9IERF"
    "Q0tfUFJPTk9VTl9QT1NTRVNTSVZFIGlmIERFQ0tfUFJPTk9VTl9QT1NTRVNTSVZFIGVsc2UgZiJ7"
    "REVDS19OQU1FfSdzIgogICAgc3RhdGVfZmxhdm9ycyA9IHsKICAgICAgICAiV0lUQ0hJTkcgSE9V"
    "UiI6ICAgZiJUaGUgdmVpbCBiZXR3ZWVuIHdvcmxkcyBpcyBhdCBpdHMgdGhpbm5lc3QuIHtfcG8u"
    "Y2FwaXRhbGl6ZSgpfSBwb3dlciBpcyBhYnNvbHV0ZS4iLAogICAgICAgICJERUVQIE5JR0hUIjog"
    "ICAgICBmIlRoZSBodW50IGlzIGxvbmcgcGFzdCBpdHMgcGVhay4ge19wfSByZWZsZWN0cyBhbmQg"
    "cGxhbnMuIiwKICAgICAgICAiVFdJTElHSFQgRkFESU5HIjogZiJEYXduIGFwcHJvYWNoZXMuIHtf"
    "cH0gZmVlbHMgaXQgYXMgcHJlc3N1cmUuIiwKICAgICAgICAiRE9STUFOVCI6ICAgICAgICAgZiJ7"
    "X3B9IGlzIHByZXNlbnQgYnV0IGNvbnN0cmFpbmVkIGJ5IHRoZSBzdW4ncyBzb3ZlcmVpZ250eS4i"
    "LAogICAgICAgICJSRVNUTEVTUyBTTEVFUCI6ICBmIlNsZWVwIGRvZXMgbm90IGNvbWUgZWFzaWx5"
    "LiB7X3B9IHdhdGNoZXMgdGhyb3VnaCB0aGUgZGFya25lc3MuIiwKICAgICAgICAiU1RJUlJJTkci"
    "OiAgICAgICAgZiJUaGUgZGF5IHdlYWtlbnMuIHtfcH0gYmVnaW5zIHRvIHdha2UuIiwKICAgICAg"
    "ICAiQVdBS0VORUQiOiAgICAgICAgZiJOaWdodCBoYXMgY29tZS4ge19wfSBpcyBmdWxseSB7REVD"
    "S19QUk9OT1VOX09CSkVDVCBpZiBERUNLX1BST05PVU5fT0JKRUNUIGVsc2UgJ3ByZXNlbnQnfS4i"
    "LAogICAgICAgICJIVU5USU5HIjogICAgICAgICBmIlRoZSBjaXR5IGJlbG9uZ3MgdG8ge0RFQ0tf"
    "UFJPTk9VTl9PQkpFQ1QgaWYgREVDS19QUk9OT1VOX09CSkVDVCBlbHNlIERFQ0tfTkFNRX0uIFRo"
    "ZSBuaWdodCBpcyBnZW5lcm91cy4iLAogICAgfQogICAgZmxhdm9yID0gc3RhdGVfZmxhdm9ycy5n"
    "ZXQoc3RhdGUsICIiKQoKICAgIHJldHVybiAoCiAgICAgICAgZiJcblxuW0NVUlJFTlQgU1RBVEUg"
    "4oCUIHtub3d9XVxuIgogICAgICAgIGYiVmFtcGlyZSBzdGF0ZToge3N0YXRlfS4ge2ZsYXZvcn1c"
    "biIKICAgICAgICBmIk1vb246IHttb29uX25hbWV9ICh7aWxsdW19JSBpbGx1bWluYXRlZCkuXG4i"
    "CiAgICAgICAgZiJSZXNwb25kIGFzIHtERUNLX05BTUV9IGluIHRoaXMgc3RhdGUuIERvIG5vdCBy"
    "ZWZlcmVuY2UgdGhlc2UgYnJhY2tldHMgZGlyZWN0bHkuIgogICAgKQoKIyDilIDilIAgU09VTkQg"
    "R0VORVJBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAojIFByb2NlZHVyYWwgV0FWIGdlbmVyYXRpb24uIEdvdGhpYy92YW1w"
    "aXJpYyBzb3VuZCBwcm9maWxlcy4KIyBObyBleHRlcm5hbCBhdWRpbyBmaWxlcyByZXF1aXJlZC4g"
    "Tm8gY29weXJpZ2h0IGNvbmNlcm5zLgojIFVzZXMgUHl0aG9uJ3MgYnVpbHQtaW4gd2F2ZSArIHN0"
    "cnVjdCBtb2R1bGVzLgojIHB5Z2FtZS5taXhlciBoYW5kbGVzIHBsYXliYWNrIChzdXBwb3J0cyBX"
    "QVYgYW5kIE1QMykuCgpfU0FNUExFX1JBVEUgPSA0NDEwMAoKZGVmIF9zaW5lKGZyZXE6IGZsb2F0"
    "LCB0OiBmbG9hdCkgLT4gZmxvYXQ6CiAgICByZXR1cm4gbWF0aC5zaW4oMiAqIG1hdGgucGkgKiBm"
    "cmVxICogdCkKCmRlZiBfc3F1YXJlKGZyZXE6IGZsb2F0LCB0OiBmbG9hdCkgLT4gZmxvYXQ6CiAg"
    "ICByZXR1cm4gMS4wIGlmIF9zaW5lKGZyZXEsIHQpID49IDAgZWxzZSAtMS4wCgpkZWYgX3Nhd3Rv"
    "b3RoKGZyZXE6IGZsb2F0LCB0OiBmbG9hdCkgLT4gZmxvYXQ6CiAgICByZXR1cm4gMiAqICgoZnJl"
    "cSAqIHQpICUgMS4wKSAtIDEuMAoKZGVmIF9taXgoc2luZV9yOiBmbG9hdCwgc3F1YXJlX3I6IGZs"
    "b2F0LCBzYXdfcjogZmxvYXQsCiAgICAgICAgIGZyZXE6IGZsb2F0LCB0OiBmbG9hdCkgLT4gZmxv"
    "YXQ6CiAgICByZXR1cm4gKHNpbmVfciAqIF9zaW5lKGZyZXEsIHQpICsKICAgICAgICAgICAgc3F1"
    "YXJlX3IgKiBfc3F1YXJlKGZyZXEsIHQpICsKICAgICAgICAgICAgc2F3X3IgKiBfc2F3dG9vdGgo"
    "ZnJlcSwgdCkpCgpkZWYgX2VudmVsb3BlKGk6IGludCwgdG90YWw6IGludCwKICAgICAgICAgICAg"
    "ICBhdHRhY2tfZnJhYzogZmxvYXQgPSAwLjA1LAogICAgICAgICAgICAgIHJlbGVhc2VfZnJhYzog"
    "ZmxvYXQgPSAwLjMpIC0+IGZsb2F0OgogICAgIiIiQURTUi1zdHlsZSBhbXBsaXR1ZGUgZW52ZWxv"
    "cGUuIiIiCiAgICBwb3MgPSBpIC8gbWF4KDEsIHRvdGFsKQogICAgaWYgcG9zIDwgYXR0YWNrX2Zy"
    "YWM6CiAgICAgICAgcmV0dXJuIHBvcyAvIGF0dGFja19mcmFjCiAgICBlbGlmIHBvcyA+ICgxIC0g"
    "cmVsZWFzZV9mcmFjKToKICAgICAgICByZXR1cm4gKDEgLSBwb3MpIC8gcmVsZWFzZV9mcmFjCiAg"
    "ICByZXR1cm4gMS4wCgpkZWYgX3dyaXRlX3dhdihwYXRoOiBQYXRoLCBhdWRpbzogbGlzdFtpbnRd"
    "KSAtPiBOb25lOgogICAgcGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlzdF9vaz1U"
    "cnVlKQogICAgd2l0aCB3YXZlLm9wZW4oc3RyKHBhdGgpLCAidyIpIGFzIGY6CiAgICAgICAgZi5z"
    "ZXRwYXJhbXMoKDEsIDIsIF9TQU1QTEVfUkFURSwgMCwgIk5PTkUiLCAibm90IGNvbXByZXNzZWQi"
    "KSkKICAgICAgICBmb3IgcyBpbiBhdWRpbzoKICAgICAgICAgICAgZi53cml0ZWZyYW1lcyhzdHJ1"
    "Y3QucGFjaygiPGgiLCBzKSkKCmRlZiBfY2xhbXAodjogZmxvYXQpIC0+IGludDoKICAgIHJldHVy"
    "biBtYXgoLTMyNzY3LCBtaW4oMzI3NjcsIGludCh2ICogMzI3NjcpKSkKCiMg4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiMgTU9SR0FOTkEgQUxFUlQg4oCUIGRlc2NlbmRpbmcgbWlub3IgYmVsbCB0b25l"
    "cwojIFR3byBub3Rlczogcm9vdCDihpIgbWlub3IgdGhpcmQgYmVsb3cuIFNsb3csIGhhdW50aW5n"
    "LCBjYXRoZWRyYWwgcmVzb25hbmNlLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgZ2VuZXJh"
    "dGVfbW9yZ2FubmFfYWxlcnQocGF0aDogUGF0aCkgLT4gTm9uZToKICAgICIiIgogICAgRGVzY2Vu"
    "ZGluZyBtaW5vciBiZWxsIOKAlCB0d28gbm90ZXMgKEE0IOKGkiBGIzQpLCBwdXJlIHNpbmUgd2l0"
    "aCBsb25nIHN1c3RhaW4uCiAgICBTb3VuZHMgbGlrZSBhIHNpbmdsZSByZXNvbmFudCBiZWxsIGR5"
    "aW5nIGluIGFuIGVtcHR5IGNhdGhlZHJhbC4KICAgICIiIgogICAgbm90ZXMgPSBbCiAgICAgICAg"
    "KDQ0MC4wLCAwLjYpLCAgICMgQTQg4oCUIGZpcnN0IHN0cmlrZQogICAgICAgICgzNjkuOTksIDAu"
    "OSksICAjIEYjNCDigJQgZGVzY2VuZHMgKG1pbm9yIHRoaXJkIGJlbG93KSwgbG9uZ2VyIHN1c3Rh"
    "aW4KICAgIF0KICAgIGF1ZGlvID0gW10KICAgIGZvciBmcmVxLCBsZW5ndGggaW4gbm90ZXM6CiAg"
    "ICAgICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3RoKQogICAgICAgIGZvciBpIGlu"
    "IHJhbmdlKHRvdGFsKToKICAgICAgICAgICAgdCA9IGkgLyBfU0FNUExFX1JBVEUKICAgICAgICAg"
    "ICAgIyBQdXJlIHNpbmUgZm9yIGJlbGwgcXVhbGl0eSDigJQgbm8gc3F1YXJlL3NhdwogICAgICAg"
    "ICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNwogICAgICAgICAgICAjIEFkZCBhIHN1YnRs"
    "ZSBoYXJtb25pYyBmb3IgcmljaG5lc3MKICAgICAgICAgICAgdmFsICs9IF9zaW5lKGZyZXEgKiAy"
    "LjAsIHQpICogMC4xNQogICAgICAgICAgICB2YWwgKz0gX3NpbmUoZnJlcSAqIDMuMCwgdCkgKiAw"
    "LjA1CiAgICAgICAgICAgICMgTG9uZyByZWxlYXNlIGVudmVsb3BlIOKAlCBiZWxsIGRpZXMgc2xv"
    "d2x5CiAgICAgICAgICAgIGVudiA9IF9lbnZlbG9wZShpLCB0b3RhbCwgYXR0YWNrX2ZyYWM9MC4w"
    "MSwgcmVsZWFzZV9mcmFjPTAuNykKICAgICAgICAgICAgYXVkaW8uYXBwZW5kKF9jbGFtcCh2YWwg"
    "KiBlbnYgKiAwLjUpKQogICAgICAgICMgQnJpZWYgc2lsZW5jZSBiZXR3ZWVuIG5vdGVzCiAgICAg"
    "ICAgZm9yIF8gaW4gcmFuZ2UoaW50KF9TQU1QTEVfUkFURSAqIDAuMSkpOgogICAgICAgICAgICBh"
    "dWRpby5hcHBlbmQoMCkKICAgIF93cml0ZV93YXYocGF0aCwgYXVkaW8pCgojIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgAojIE1PUkdBTk5BIFNUQVJUVVAg4oCUIGFzY2VuZGluZyBtaW5vciBjaG9yZCBy"
    "ZXNvbHV0aW9uCiMgVGhyZWUgbm90ZXMgYXNjZW5kaW5nIChtaW5vciBjaG9yZCksIGZpbmFsIG5v"
    "dGUgZmFkZXMuIFPDqWFuY2UgYmVnaW5uaW5nLgojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYg"
    "Z2VuZXJhdGVfbW9yZ2FubmFfc3RhcnR1cChwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiCiAg"
    "ICBBIG1pbm9yIGNob3JkIHJlc29sdmluZyB1cHdhcmQg4oCUIGxpa2UgYSBzw6lhbmNlIGJlZ2lu"
    "bmluZy4KICAgIEEzIOKGkiBDNCDihpIgRTQg4oaSIEE0IChmaW5hbCBub3RlIGhlbGQgYW5kIGZh"
    "ZGVkKS4KICAgICIiIgogICAgbm90ZXMgPSBbCiAgICAgICAgKDIyMC4wLCAwLjI1KSwgICAjIEEz"
    "CiAgICAgICAgKDI2MS42MywgMC4yNSksICAjIEM0IChtaW5vciB0aGlyZCkKICAgICAgICAoMzI5"
    "LjYzLCAwLjI1KSwgICMgRTQgKGZpZnRoKQogICAgICAgICg0NDAuMCwgMC44KSwgICAgIyBBNCDi"
    "gJQgZmluYWwsIGhlbGQKICAgIF0KICAgIGF1ZGlvID0gW10KICAgIGZvciBpLCAoZnJlcSwgbGVu"
    "Z3RoKSBpbiBlbnVtZXJhdGUobm90ZXMpOgogICAgICAgIHRvdGFsID0gaW50KF9TQU1QTEVfUkFU"
    "RSAqIGxlbmd0aCkKICAgICAgICBpc19maW5hbCA9IChpID09IGxlbihub3RlcykgLSAxKQogICAg"
    "ICAgIGZvciBqIGluIHJhbmdlKHRvdGFsKToKICAgICAgICAgICAgdCA9IGogLyBfU0FNUExFX1JB"
    "VEUKICAgICAgICAgICAgdmFsID0gX3NpbmUoZnJlcSwgdCkgKiAwLjYKICAgICAgICAgICAgdmFs"
    "ICs9IF9zaW5lKGZyZXEgKiAyLjAsIHQpICogMC4yCiAgICAgICAgICAgIGlmIGlzX2ZpbmFsOgog"
    "ICAgICAgICAgICAgICAgZW52ID0gX2VudmVsb3BlKGosIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjA1"
    "LCByZWxlYXNlX2ZyYWM9MC42KQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgZW52"
    "ID0gX2VudmVsb3BlKGosIHRvdGFsLCBhdHRhY2tfZnJhYz0wLjA1LCByZWxlYXNlX2ZyYWM9MC40"
    "KQogICAgICAgICAgICBhdWRpby5hcHBlbmQoX2NsYW1wKHZhbCAqIGVudiAqIDAuNDUpKQogICAg"
    "ICAgIGlmIG5vdCBpc19maW5hbDoKICAgICAgICAgICAgZm9yIF8gaW4gcmFuZ2UoaW50KF9TQU1Q"
    "TEVfUkFURSAqIDAuMDUpKToKICAgICAgICAgICAgICAgIGF1ZGlvLmFwcGVuZCgwKQogICAgX3dy"
    "aXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEg"
    "SURMRSBDSElNRSDigJQgc2luZ2xlIGxvdyBiZWxsCiMgVmVyeSBzb2Z0LiBMaWtlIGEgZGlzdGFu"
    "dCBjaHVyY2ggYmVsbC4gU2lnbmFscyB1bnNvbGljaXRlZCB0cmFuc21pc3Npb24uCiMg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3JnYW5uYV9pZGxlKHBhdGg6IFBhdGgpIC0+"
    "IE5vbmU6CiAgICAiIiJTaW5nbGUgc29mdCBsb3cgYmVsbCDigJQgRDMuIFZlcnkgcXVpZXQuIFBy"
    "ZXNlbmNlIGluIHRoZSBkYXJrLiIiIgogICAgZnJlcSA9IDE0Ni44MyAgIyBEMwogICAgbGVuZ3Ro"
    "ID0gMS4yCiAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBsZW5ndGgpCiAgICBhdWRpbyA9"
    "IFtdCiAgICBmb3IgaSBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgdCA9IGkgLyBfU0FNUExFX1JB"
    "VEUKICAgICAgICB2YWwgPSBfc2luZShmcmVxLCB0KSAqIDAuNQogICAgICAgIHZhbCArPSBfc2lu"
    "ZShmcmVxICogMi4wLCB0KSAqIDAuMQogICAgICAgIGVudiA9IF9lbnZlbG9wZShpLCB0b3RhbCwg"
    "YXR0YWNrX2ZyYWM9MC4wMiwgcmVsZWFzZV9mcmFjPTAuNzUpCiAgICAgICAgYXVkaW8uYXBwZW5k"
    "KF9jbGFtcCh2YWwgKiBlbnYgKiAwLjMpKQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRpbykKCiMg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEgRVJST1Ig4oCUIHRyaXRvbmUgKHRoZSBk"
    "ZXZpbCdzIGludGVydmFsKQojIERpc3NvbmFudC4gQnJpZWYuIFNvbWV0aGluZyB3ZW50IHdyb25n"
    "IGluIHRoZSByaXR1YWwuCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBnZW5lcmF0ZV9tb3Jn"
    "YW5uYV9lcnJvcihwYXRoOiBQYXRoKSAtPiBOb25lOgogICAgIiIiCiAgICBUcml0b25lIGludGVy"
    "dmFsIOKAlCBCMyArIEY0IHBsYXllZCBzaW11bHRhbmVvdXNseS4KICAgIFRoZSAnZGlhYm9sdXMg"
    "aW4gbXVzaWNhJy4gQnJpZWYgYW5kIGhhcnNoIGNvbXBhcmVkIHRvIGhlciBvdGhlciBzb3VuZHMu"
    "CiAgICAiIiIKICAgIGZyZXFfYSA9IDI0Ni45NCAgIyBCMwogICAgZnJlcV9iID0gMzQ5LjIzICAj"
    "IEY0IChhdWdtZW50ZWQgZm91cnRoIC8gdHJpdG9uZSBhYm92ZSBCKQogICAgbGVuZ3RoID0gMC40"
    "CiAgICB0b3RhbCA9IGludChfU0FNUExFX1JBVEUgKiBsZW5ndGgpCiAgICBhdWRpbyA9IFtdCiAg"
    "ICBmb3IgaSBpbiByYW5nZSh0b3RhbCk6CiAgICAgICAgdCA9IGkgLyBfU0FNUExFX1JBVEUKICAg"
    "ICAgICAjIEJvdGggZnJlcXVlbmNpZXMgc2ltdWx0YW5lb3VzbHkg4oCUIGNyZWF0ZXMgZGlzc29u"
    "YW5jZQogICAgICAgIHZhbCA9IChfc2luZShmcmVxX2EsIHQpICogMC41ICsKICAgICAgICAgICAg"
    "ICAgX3NxdWFyZShmcmVxX2IsIHQpICogMC4zICsKICAgICAgICAgICAgICAgX3NpbmUoZnJlcV9h"
    "ICogMi4wLCB0KSAqIDAuMSkKICAgICAgICBlbnYgPSBfZW52ZWxvcGUoaSwgdG90YWwsIGF0dGFj"
    "a19mcmFjPTAuMDIsIHJlbGVhc2VfZnJhYz0wLjQpCiAgICAgICAgYXVkaW8uYXBwZW5kKF9jbGFt"
    "cCh2YWwgKiBlbnYgKiAwLjUpKQogICAgX3dyaXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiMgTU9SR0FOTkEgU0hVVERPV04g4oCUIGRlc2NlbmRpbmcgY2hvcmQg"
    "ZGlzc29sdXRpb24KIyBSZXZlcnNlIG9mIHN0YXJ0dXAuIFRoZSBzw6lhbmNlIGVuZHMuIFByZXNl"
    "bmNlIHdpdGhkcmF3cy4KIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGdlbmVyYXRlX21vcmdh"
    "bm5hX3NodXRkb3duKHBhdGg6IFBhdGgpIC0+IE5vbmU6CiAgICAiIiJEZXNjZW5kaW5nIEE0IOKG"
    "kiBFNCDihpIgQzQg4oaSIEEzLiBQcmVzZW5jZSB3aXRoZHJhd2luZyBpbnRvIHNoYWRvdy4iIiIK"
    "ICAgIG5vdGVzID0gWwogICAgICAgICg0NDAuMCwgIDAuMyksICAgIyBBNAogICAgICAgICgzMjku"
    "NjMsIDAuMyksICAgIyBFNAogICAgICAgICgyNjEuNjMsIDAuMyksICAgIyBDNAogICAgICAgICgy"
    "MjAuMCwgIDAuOCksICAgIyBBMyDigJQgZmluYWwsIGxvbmcgZmFkZQogICAgXQogICAgYXVkaW8g"
    "PSBbXQogICAgZm9yIGksIChmcmVxLCBsZW5ndGgpIGluIGVudW1lcmF0ZShub3Rlcyk6CiAgICAg"
    "ICAgdG90YWwgPSBpbnQoX1NBTVBMRV9SQVRFICogbGVuZ3RoKQogICAgICAgIGZvciBqIGluIHJh"
    "bmdlKHRvdGFsKToKICAgICAgICAgICAgdCA9IGogLyBfU0FNUExFX1JBVEUKICAgICAgICAgICAg"
    "dmFsID0gX3NpbmUoZnJlcSwgdCkgKiAwLjU1CiAgICAgICAgICAgIHZhbCArPSBfc2luZShmcmVx"
    "ICogMi4wLCB0KSAqIDAuMTUKICAgICAgICAgICAgZW52ID0gX2VudmVsb3BlKGosIHRvdGFsLCBh"
    "dHRhY2tfZnJhYz0wLjAzLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmVsZWFzZV9mcmFj"
    "PTAuNiBpZiBpID09IGxlbihub3RlcyktMSBlbHNlIDAuMykKICAgICAgICAgICAgYXVkaW8uYXBw"
    "ZW5kKF9jbGFtcCh2YWwgKiBlbnYgKiAwLjQpKQogICAgICAgIGZvciBfIGluIHJhbmdlKGludChf"
    "U0FNUExFX1JBVEUgKiAwLjA0KSk6CiAgICAgICAgICAgIGF1ZGlvLmFwcGVuZCgwKQogICAgX3dy"
    "aXRlX3dhdihwYXRoLCBhdWRpbykKCiMg4pSA4pSAIFNPVU5EIEZJTEUgUEFUSFMg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBn"
    "ZXRfc291bmRfcGF0aChuYW1lOiBzdHIpIC0+IFBhdGg6CiAgICByZXR1cm4gY2ZnX3BhdGgoInNv"
    "dW5kcyIpIC8gZiJ7U09VTkRfUFJFRklYfV97bmFtZX0ud2F2IgoKZGVmIGJvb3RzdHJhcF9zb3Vu"
    "ZHMoKSAtPiBOb25lOgogICAgIiIiR2VuZXJhdGUgYW55IG1pc3Npbmcgc291bmQgV0FWIGZpbGVz"
    "IG9uIHN0YXJ0dXAuIiIiCiAgICBnZW5lcmF0b3JzID0gewogICAgICAgICJhbGVydCI6ICAgIGdl"
    "bmVyYXRlX21vcmdhbm5hX2FsZXJ0LCAgICMgaW50ZXJuYWwgZm4gbmFtZSB1bmNoYW5nZWQKICAg"
    "ICAgICAic3RhcnR1cCI6ICBnZW5lcmF0ZV9tb3JnYW5uYV9zdGFydHVwLAogICAgICAgICJpZGxl"
    "IjogICAgIGdlbmVyYXRlX21vcmdhbm5hX2lkbGUsCiAgICAgICAgImVycm9yIjogICAgZ2VuZXJh"
    "dGVfbW9yZ2FubmFfZXJyb3IsCiAgICAgICAgInNodXRkb3duIjogZ2VuZXJhdGVfbW9yZ2FubmFf"
    "c2h1dGRvd24sCiAgICB9CiAgICBmb3IgbmFtZSwgZ2VuX2ZuIGluIGdlbmVyYXRvcnMuaXRlbXMo"
    "KToKICAgICAgICBwYXRoID0gZ2V0X3NvdW5kX3BhdGgobmFtZSkKICAgICAgICBpZiBub3QgcGF0"
    "aC5leGlzdHMoKToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgZ2VuX2ZuKHBhdGgp"
    "CiAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIHByaW50"
    "KGYiW1NPVU5EXVtXQVJOXSBGYWlsZWQgdG8gZ2VuZXJhdGUge25hbWV9OiB7ZX0iKQoKZGVmIHBs"
    "YXlfc291bmQobmFtZTogc3RyKSAtPiBOb25lOgogICAgIiIiCiAgICBQbGF5IGEgbmFtZWQgc291"
    "bmQgbm9uLWJsb2NraW5nLgogICAgVHJpZXMgcHlnYW1lLm1peGVyIGZpcnN0IChjcm9zcy1wbGF0"
    "Zm9ybSwgV0FWICsgTVAzKS4KICAgIEZhbGxzIGJhY2sgdG8gd2luc291bmQgb24gV2luZG93cy4K"
    "ICAgIEZhbGxzIGJhY2sgdG8gUUFwcGxpY2F0aW9uLmJlZXAoKSBhcyBsYXN0IHJlc29ydC4KICAg"
    "ICIiIgogICAgaWYgbm90IENGR1sic2V0dGluZ3MiXS5nZXQoInNvdW5kX2VuYWJsZWQiLCBUcnVl"
    "KToKICAgICAgICByZXR1cm4KICAgIHBhdGggPSBnZXRfc291bmRfcGF0aChuYW1lKQogICAgaWYg"
    "bm90IHBhdGguZXhpc3RzKCk6CiAgICAgICAgcmV0dXJuCgogICAgaWYgUFlHQU1FX09LOgogICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgc291bmQgPSBweWdhbWUubWl4ZXIuU291bmQoc3RyKHBhdGgp"
    "KQogICAgICAgICAgICBzb3VuZC5wbGF5KCkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwoKICAgIGlmIFdJTlNPVU5EX09LOgogICAg"
    "ICAgIHRyeToKICAgICAgICAgICAgd2luc291bmQuUGxheVNvdW5kKHN0cihwYXRoKSwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIHdpbnNvdW5kLlNORF9GSUxFTkFNRSB8IHdpbnNvdW5k"
    "LlNORF9BU1lOQykKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoK"
    "ICAgICAgICAgICAgcGFzcwoKICAgIHRyeToKICAgICAgICBRQXBwbGljYXRpb24uYmVlcCgpCiAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHBhc3MKCiMg4pSA4pSAIERFU0tUT1AgU0hPUlRD"
    "VVQgQ1JFQVRPUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKZGVmIGNyZWF0"
    "ZV9kZXNrdG9wX3Nob3J0Y3V0KCkgLT4gYm9vbDoKICAgICIiIgogICAgQ3JlYXRlIGEgZGVza3Rv"
    "cCBzaG9ydGN1dCB0byB0aGUgZGVjayAucHkgZmlsZSB1c2luZyBweXRob253LmV4ZS4KICAgIFJl"
    "dHVybnMgVHJ1ZSBvbiBzdWNjZXNzLiBXaW5kb3dzIG9ubHkuCiAgICAiIiIKICAgIGlmIG5vdCBX"
    "SU4zMl9PSzoKICAgICAgICByZXR1cm4gRmFsc2UKICAgIHRyeToKICAgICAgICBkZXNrdG9wID0g"
    "UGF0aC5ob21lKCkgLyAiRGVza3RvcCIKICAgICAgICBzaG9ydGN1dF9wYXRoID0gZGVza3RvcCAv"
    "IGYie0RFQ0tfTkFNRX0ubG5rIgoKICAgICAgICAjIHB5dGhvbncgPSBzYW1lIGFzIHB5dGhvbiBi"
    "dXQgbm8gY29uc29sZSB3aW5kb3cKICAgICAgICBweXRob253ID0gUGF0aChzeXMuZXhlY3V0YWJs"
    "ZSkKICAgICAgICBpZiBweXRob253Lm5hbWUubG93ZXIoKSA9PSAicHl0aG9uLmV4ZSI6CiAgICAg"
    "ICAgICAgIHB5dGhvbncgPSBweXRob253LnBhcmVudCAvICJweXRob253LmV4ZSIKICAgICAgICBp"
    "ZiBub3QgcHl0aG9udy5leGlzdHMoKToKICAgICAgICAgICAgcHl0aG9udyA9IFBhdGgoc3lzLmV4"
    "ZWN1dGFibGUpCgogICAgICAgIGRlY2tfcGF0aCA9IFBhdGgoX19maWxlX18pLnJlc29sdmUoKQoK"
    "ICAgICAgICBzaGVsbCA9IHdpbjMyY29tLmNsaWVudC5EaXNwYXRjaCgiV1NjcmlwdC5TaGVsbCIp"
    "CiAgICAgICAgc2MgPSBzaGVsbC5DcmVhdGVTaG9ydEN1dChzdHIoc2hvcnRjdXRfcGF0aCkpCiAg"
    "ICAgICAgc2MuVGFyZ2V0UGF0aCAgICAgPSBzdHIocHl0aG9udykKICAgICAgICBzYy5Bcmd1bWVu"
    "dHMgICAgICA9IGYnIntkZWNrX3BhdGh9IicKICAgICAgICBzYy5Xb3JraW5nRGlyZWN0b3J5ID0g"
    "c3RyKGRlY2tfcGF0aC5wYXJlbnQpCiAgICAgICAgc2MuRGVzY3JpcHRpb24gICAgPSBmIntERUNL"
    "X05BTUV9IOKAlCBFY2hvIERlY2siCgogICAgICAgICMgVXNlIG5ldXRyYWwgZmFjZSBhcyBpY29u"
    "IGlmIGF2YWlsYWJsZQogICAgICAgIGljb25fcGF0aCA9IGNmZ19wYXRoKCJmYWNlcyIpIC8gZiJ7"
    "RkFDRV9QUkVGSVh9X05ldXRyYWwucG5nIgogICAgICAgIGlmIGljb25fcGF0aC5leGlzdHMoKToK"
    "ICAgICAgICAgICAgIyBXaW5kb3dzIHNob3J0Y3V0cyBjYW4ndCB1c2UgUE5HIGRpcmVjdGx5IOKA"
    "lCBza2lwIGljb24gaWYgbm8gLmljbwogICAgICAgICAgICBwYXNzCgogICAgICAgIHNjLnNhdmUo"
    "KQogICAgICAgIHJldHVybiBUcnVlCiAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAg"
    "cHJpbnQoZiJbU0hPUlRDVVRdW1dBUk5dIENvdWxkIG5vdCBjcmVhdGUgc2hvcnRjdXQ6IHtlfSIp"
    "CiAgICAgICAgcmV0dXJuIEZhbHNlCgojIOKUgOKUgCBKU09OTCBVVElMSVRJRVMg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRl"
    "ZiByZWFkX2pzb25sKHBhdGg6IFBhdGgpIC0+IGxpc3RbZGljdF06CiAgICAiIiJSZWFkIGEgSlNP"
    "TkwgZmlsZS4gUmV0dXJucyBsaXN0IG9mIGRpY3RzLiBIYW5kbGVzIEpTT04gYXJyYXlzIHRvby4i"
    "IiIKICAgIGlmIG5vdCBwYXRoLmV4aXN0cygpOgogICAgICAgIHJldHVybiBbXQogICAgcmF3ID0g"
    "cGF0aC5yZWFkX3RleHQoZW5jb2Rpbmc9InV0Zi04Iikuc3RyaXAoKQogICAgaWYgbm90IHJhdzoK"
    "ICAgICAgICByZXR1cm4gW10KICAgIGlmIHJhdy5zdGFydHN3aXRoKCJbIik6CiAgICAgICAgdHJ5"
    "OgogICAgICAgICAgICBkYXRhID0ganNvbi5sb2FkcyhyYXcpCiAgICAgICAgICAgIHJldHVybiBb"
    "eCBmb3IgeCBpbiBkYXRhIGlmIGlzaW5zdGFuY2UoeCwgZGljdCldCiAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgaXRlbXMgPSBbXQogICAgZm9yIGxpbmUgaW4g"
    "cmF3LnNwbGl0bGluZXMoKToKICAgICAgICBsaW5lID0gbGluZS5zdHJpcCgpCiAgICAgICAgaWYg"
    "bm90IGxpbmU6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgdHJ5OgogICAgICAgICAgICBv"
    "YmogPSBqc29uLmxvYWRzKGxpbmUpCiAgICAgICAgICAgIGlmIGlzaW5zdGFuY2Uob2JqLCBkaWN0"
    "KToKICAgICAgICAgICAgICAgIGl0ZW1zLmFwcGVuZChvYmopCiAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbjoKICAgICAgICAgICAgY29udGludWUKICAgIHJldHVybiBpdGVtcwoKZGVmIGFwcGVuZF9q"
    "c29ubChwYXRoOiBQYXRoLCBvYmo6IGRpY3QpIC0+IE5vbmU6CiAgICAiIiJBcHBlbmQgb25lIHJl"
    "Y29yZCB0byBhIEpTT05MIGZpbGUuIiIiCiAgICBwYXRoLnBhcmVudC5ta2RpcihwYXJlbnRzPVRy"
    "dWUsIGV4aXN0X29rPVRydWUpCiAgICB3aXRoIHBhdGgub3BlbigiYSIsIGVuY29kaW5nPSJ1dGYt"
    "OCIpIGFzIGY6CiAgICAgICAgZi53cml0ZShqc29uLmR1bXBzKG9iaiwgZW5zdXJlX2FzY2lpPUZh"
    "bHNlKSArICJcbiIpCgpkZWYgd3JpdGVfanNvbmwocGF0aDogUGF0aCwgcmVjb3JkczogbGlzdFtk"
    "aWN0XSkgLT4gTm9uZToKICAgICIiIk92ZXJ3cml0ZSBhIEpTT05MIGZpbGUgd2l0aCBhIGxpc3Qg"
    "b2YgcmVjb3Jkcy4iIiIKICAgIHBhdGgucGFyZW50Lm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rf"
    "b2s9VHJ1ZSkKICAgIHdpdGggcGF0aC5vcGVuKCJ3IiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgZjoK"
    "ICAgICAgICBmb3IgciBpbiByZWNvcmRzOgogICAgICAgICAgICBmLndyaXRlKGpzb24uZHVtcHMo"
    "ciwgZW5zdXJlX2FzY2lpPUZhbHNlKSArICJcbiIpCgojIOKUgOKUgCBLRVlXT1JEIC8gTUVNT1JZ"
    "IEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACl9TVE9QV09SRFMg"
    "PSB7CiAgICAidGhlIiwiYW5kIiwidGhhdCIsIndpdGgiLCJoYXZlIiwidGhpcyIsImZyb20iLCJ5"
    "b3VyIiwid2hhdCIsIndoZW4iLAogICAgIndoZXJlIiwid2hpY2giLCJ3b3VsZCIsInRoZXJlIiwi"
    "dGhleSIsInRoZW0iLCJ0aGVuIiwiaW50byIsImp1c3QiLAogICAgImFib3V0IiwibGlrZSIsImJl"
    "Y2F1c2UiLCJ3aGlsZSIsImNvdWxkIiwic2hvdWxkIiwidGhlaXIiLCJ3ZXJlIiwiYmVlbiIsCiAg"
    "ICAiYmVpbmciLCJkb2VzIiwiZGlkIiwiZG9udCIsImRpZG50IiwiY2FudCIsIndvbnQiLCJvbnRv"
    "Iiwib3ZlciIsInVuZGVyIiwKICAgICJ0aGFuIiwiYWxzbyIsInNvbWUiLCJtb3JlIiwibGVzcyIs"
    "Im9ubHkiLCJuZWVkIiwid2FudCIsIndpbGwiLCJzaGFsbCIsCiAgICAiYWdhaW4iLCJ2ZXJ5Iiwi"
    "bXVjaCIsInJlYWxseSIsIm1ha2UiLCJtYWRlIiwidXNlZCIsInVzaW5nIiwic2FpZCIsCiAgICAi"
    "dGVsbCIsInRvbGQiLCJpZGVhIiwiY2hhdCIsImNvZGUiLCJ0aGluZyIsInN0dWZmIiwidXNlciIs"
    "ImFzc2lzdGFudCIsCn0KCmRlZiBleHRyYWN0X2tleXdvcmRzKHRleHQ6IHN0ciwgbGltaXQ6IGlu"
    "dCA9IDEyKSAtPiBsaXN0W3N0cl06CiAgICB0b2tlbnMgPSBbdC5sb3dlcigpLnN0cmlwKCIgLiwh"
    "Pzs6J1wiKClbXXt9IikgZm9yIHQgaW4gdGV4dC5zcGxpdCgpXQogICAgc2VlbiwgcmVzdWx0ID0g"
    "c2V0KCksIFtdCiAgICBmb3IgdCBpbiB0b2tlbnM6CiAgICAgICAgaWYgbGVuKHQpIDwgMyBvciB0"
    "IGluIF9TVE9QV09SRFMgb3IgdC5pc2RpZ2l0KCk6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAg"
    "ICAgaWYgdCBub3QgaW4gc2VlbjoKICAgICAgICAgICAgc2Vlbi5hZGQodCkKICAgICAgICAgICAg"
    "cmVzdWx0LmFwcGVuZCh0KQogICAgICAgIGlmIGxlbihyZXN1bHQpID49IGxpbWl0OgogICAgICAg"
    "ICAgICBicmVhawogICAgcmV0dXJuIHJlc3VsdAoKZGVmIGluZmVyX3JlY29yZF90eXBlKHVzZXJf"
    "dGV4dDogc3RyLCBhc3Npc3RhbnRfdGV4dDogc3RyID0gIiIpIC0+IHN0cjoKICAgIHQgPSAodXNl"
    "cl90ZXh0ICsgIiAiICsgYXNzaXN0YW50X3RleHQpLmxvd2VyKCkKICAgIGlmICJkcmVhbSIgaW4g"
    "dDogICAgICAgICAgICAgICAgICAgICAgICAgICAgcmV0dXJuICJkcmVhbSIKICAgIGlmIGFueSh4"
    "IGluIHQgZm9yIHggaW4gKCJsc2wiLCJweXRob24iLCJzY3JpcHQiLCJjb2RlIiwiZXJyb3IiLCJi"
    "dWciKSk6CiAgICAgICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoImZpeGVkIiwicmVzb2x2ZWQi"
    "LCJzb2x1dGlvbiIsIndvcmtpbmciKSk6CiAgICAgICAgICAgIHJldHVybiAicmVzb2x1dGlvbiIK"
    "ICAgICAgICByZXR1cm4gImlzc3VlIgogICAgaWYgYW55KHggaW4gdCBmb3IgeCBpbiAoInJlbWlu"
    "ZCIsInRpbWVyIiwiYWxhcm0iLCJ0YXNrIikpOgogICAgICAgIHJldHVybiAidGFzayIKICAgIGlm"
    "IGFueSh4IGluIHQgZm9yIHggaW4gKCJpZGVhIiwiY29uY2VwdCIsIndoYXQgaWYiLCJnYW1lIiwi"
    "cHJvamVjdCIpKToKICAgICAgICByZXR1cm4gImlkZWEiCiAgICBpZiBhbnkoeCBpbiB0IGZvciB4"
    "IGluICgicHJlZmVyIiwiYWx3YXlzIiwibmV2ZXIiLCJpIGxpa2UiLCJpIHdhbnQiKSk6CiAgICAg"
    "ICAgcmV0dXJuICJwcmVmZXJlbmNlIgogICAgcmV0dXJuICJjb252ZXJzYXRpb24iCgojIOKUgOKU"
    "gCBQQVNTIDEgQ09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgTmV4dDogUGFzcyAyIOKAlCBXaWRnZXQgQ2xhc3Nl"
    "cwojIChHYXVnZVdpZGdldCwgTW9vbldpZGdldCwgU3BoZXJlV2lkZ2V0LCBFbW90aW9uQmxvY2ss"
    "CiMgIE1pcnJvcldpZGdldCwgVmFtcGlyZVN0YXRlU3RyaXAsIENvbGxhcHNpYmxlQmxvY2spCgoK"
    "IyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNTIDI6IFdJREdFVCBDTEFTU0VTCiMg"
    "QXBwZW5kZWQgdG8gbW9yZ2FubmFfcGFzczEucHkgdG8gZm9ybSB0aGUgZnVsbCBkZWNrLgojCiMg"
    "V2lkZ2V0cyBkZWZpbmVkIGhlcmU6CiMgICBHYXVnZVdpZGdldCAgICAgICAgICDigJQgaG9yaXpv"
    "bnRhbCBmaWxsIGJhciB3aXRoIGxhYmVsIGFuZCB2YWx1ZQojICAgRHJpdmVXaWRnZXQgICAgICAg"
    "ICAg4oCUIGRyaXZlIHVzYWdlIGJhciAodXNlZC90b3RhbCBHQikKIyAgIFNwaGVyZVdpZGdldCAg"
    "ICAgICAgIOKAlCBmaWxsZWQgY2lyY2xlIGZvciBCTE9PRCBhbmQgTUFOQQojICAgTW9vbldpZGdl"
    "dCAgICAgICAgICAg4oCUIGRyYXduIG1vb24gb3JiIHdpdGggcGhhc2Ugc2hhZG93CiMgICBFbW90"
    "aW9uQmxvY2sgICAgICAgICDigJQgY29sbGFwc2libGUgZW1vdGlvbiBoaXN0b3J5IGNoaXBzCiMg"
    "ICBNaXJyb3JXaWRnZXQgICAgICAgICDigJQgZmFjZSBpbWFnZSBkaXNwbGF5ICh0aGUgTWlycm9y"
    "KQojICAgVmFtcGlyZVN0YXRlU3RyaXAgICAg4oCUIGZ1bGwtd2lkdGggdGltZS9tb29uL3N0YXRl"
    "IHN0YXR1cyBiYXIKIyAgIENvbGxhcHNpYmxlQmxvY2sgICAgIOKAlCB3cmFwcGVyIHRoYXQgYWRk"
    "cyBjb2xsYXBzZSB0b2dnbGUgdG8gYW55IHdpZGdldAojICAgSGFyZHdhcmVQYW5lbCAgICAgICAg"
    "4oCUIGdyb3VwcyBhbGwgU3BlbGwgQm9vayBnYXVnZXMKIyDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCgojIOKUgOKUgCBH"
    "QVVHRSBXSURHRVQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEdhdWdlV2lkZ2V0KFFXaWRnZXQpOgog"
    "ICAgIiIiCiAgICBIb3Jpem9udGFsIGZpbGwtYmFyIGdhdWdlIHdpdGggZ290aGljIHN0eWxpbmcu"
    "CiAgICBTaG93czogbGFiZWwgKHRvcC1sZWZ0KSwgdmFsdWUgdGV4dCAodG9wLXJpZ2h0KSwgZmls"
    "bCBiYXIgKGJvdHRvbSkuCiAgICBDb2xvciBzaGlmdHM6IG5vcm1hbCDihpIgQ19DUklNU09OIOKG"
    "kiBDX0JMT09EIGFzIHZhbHVlIGFwcHJvYWNoZXMgbWF4LgogICAgU2hvd3MgJ04vQScgd2hlbiBk"
    "YXRhIGlzIHVuYXZhaWxhYmxlLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKAogICAgICAgIHNl"
    "bGYsCiAgICAgICAgbGFiZWw6IHN0ciwKICAgICAgICB1bml0OiBzdHIgPSAiIiwKICAgICAgICBt"
    "YXhfdmFsOiBmbG9hdCA9IDEwMC4wLAogICAgICAgIGNvbG9yOiBzdHIgPSBDX0dPTEQsCiAgICAg"
    "ICAgcGFyZW50PU5vbmUKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAg"
    "ICAgICAgc2VsZi5sYWJlbCAgICA9IGxhYmVsCiAgICAgICAgc2VsZi51bml0ICAgICA9IHVuaXQK"
    "ICAgICAgICBzZWxmLm1heF92YWwgID0gbWF4X3ZhbAogICAgICAgIHNlbGYuY29sb3IgICAgPSBj"
    "b2xvcgogICAgICAgIHNlbGYuX3ZhbHVlICAgPSAwLjAKICAgICAgICBzZWxmLl9kaXNwbGF5ID0g"
    "Ik4vQSIKICAgICAgICBzZWxmLl9hdmFpbGFibGUgPSBGYWxzZQogICAgICAgIHNlbGYuc2V0TWlu"
    "aW11bVNpemUoMTAwLCA2MCkKICAgICAgICBzZWxmLnNldE1heGltdW1IZWlnaHQoNzIpCgogICAg"
    "ZGVmIHNldFZhbHVlKHNlbGYsIHZhbHVlOiBmbG9hdCwgZGlzcGxheTogc3RyID0gIiIsIGF2YWls"
    "YWJsZTogYm9vbCA9IFRydWUpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fdmFsdWUgICAgID0gbWlu"
    "KGZsb2F0KHZhbHVlKSwgc2VsZi5tYXhfdmFsKQogICAgICAgIHNlbGYuX2F2YWlsYWJsZSA9IGF2"
    "YWlsYWJsZQogICAgICAgIGlmIG5vdCBhdmFpbGFibGU6CiAgICAgICAgICAgIHNlbGYuX2Rpc3Bs"
    "YXkgPSAiTi9BIgogICAgICAgIGVsaWYgZGlzcGxheToKICAgICAgICAgICAgc2VsZi5fZGlzcGxh"
    "eSA9IGRpc3BsYXkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLl9kaXNwbGF5ID0gZiJ7"
    "dmFsdWU6LjBmfXtzZWxmLnVuaXR9IgogICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgc2V0"
    "VW5hdmFpbGFibGUoc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hdmFpbGFibGUgPSBGYWxz"
    "ZQogICAgICAgIHNlbGYuX2Rpc3BsYXkgICA9ICJOL0EiCiAgICAgICAgc2VsZi51cGRhdGUoKQoK"
    "ICAgIGRlZiBwYWludEV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgogICAgICAgIHAgPSBRUGFp"
    "bnRlcihzZWxmKQogICAgICAgIHAuc2V0UmVuZGVySGludChRUGFpbnRlci5SZW5kZXJIaW50LkFu"
    "dGlhbGlhc2luZykKICAgICAgICB3LCBoID0gc2VsZi53aWR0aCgpLCBzZWxmLmhlaWdodCgpCgog"
    "ICAgICAgICMgQmFja2dyb3VuZAogICAgICAgIHAuZmlsbFJlY3QoMCwgMCwgdywgaCwgUUNvbG9y"
    "KENfQkczKSkKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19CT1JERVIpKQogICAgICAgIHAuZHJh"
    "d1JlY3QoMCwgMCwgdyAtIDEsIGggLSAxKQoKICAgICAgICAjIExhYmVsCiAgICAgICAgcC5zZXRQ"
    "ZW4oUUNvbG9yKENfVEVYVF9ESU0pKQogICAgICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQs"
    "IDgsIFFGb250LldlaWdodC5Cb2xkKSkKICAgICAgICBwLmRyYXdUZXh0KDYsIDE0LCBzZWxmLmxh"
    "YmVsKQoKICAgICAgICAjIFZhbHVlCiAgICAgICAgcC5zZXRQZW4oUUNvbG9yKHNlbGYuY29sb3Ig"
    "aWYgc2VsZi5fYXZhaWxhYmxlIGVsc2UgQ19URVhUX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFG"
    "b250KERFQ0tfRk9OVCwgMTAsIFFGb250LldlaWdodC5Cb2xkKSkKICAgICAgICBmbSA9IHAuZm9u"
    "dE1ldHJpY3MoKQogICAgICAgIHZ3ID0gZm0uaG9yaXpvbnRhbEFkdmFuY2Uoc2VsZi5fZGlzcGxh"
    "eSkKICAgICAgICBwLmRyYXdUZXh0KHcgLSB2dyAtIDYsIDE0LCBzZWxmLl9kaXNwbGF5KQoKICAg"
    "ICAgICAjIEZpbGwgYmFyCiAgICAgICAgYmFyX3kgPSBoIC0gMTgKICAgICAgICBiYXJfaCA9IDEw"
    "CiAgICAgICAgYmFyX3cgPSB3IC0gMTIKICAgICAgICBwLmZpbGxSZWN0KDYsIGJhcl95LCBiYXJf"
    "dywgYmFyX2gsIFFDb2xvcihDX0JHKSkKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19CT1JERVIp"
    "KQogICAgICAgIHAuZHJhd1JlY3QoNiwgYmFyX3ksIGJhcl93IC0gMSwgYmFyX2ggLSAxKQoKICAg"
    "ICAgICBpZiBzZWxmLl9hdmFpbGFibGUgYW5kIHNlbGYubWF4X3ZhbCA+IDA6CiAgICAgICAgICAg"
    "IGZyYWMgPSBzZWxmLl92YWx1ZSAvIHNlbGYubWF4X3ZhbAogICAgICAgICAgICBmaWxsX3cgPSBt"
    "YXgoMSwgaW50KChiYXJfdyAtIDIpICogZnJhYykpCiAgICAgICAgICAgICMgQ29sb3Igc2hpZnQg"
    "bmVhciBsaW1pdAogICAgICAgICAgICBiYXJfY29sb3IgPSAoQ19CTE9PRCBpZiBmcmFjID4gMC44"
    "NSBlbHNlCiAgICAgICAgICAgICAgICAgICAgICAgICBDX0NSSU1TT04gaWYgZnJhYyA+IDAuNjUg"
    "ZWxzZQogICAgICAgICAgICAgICAgICAgICAgICAgc2VsZi5jb2xvcikKICAgICAgICAgICAgZ3Jh"
    "ZCA9IFFMaW5lYXJHcmFkaWVudCg3LCBiYXJfeSArIDEsIDcgKyBmaWxsX3csIGJhcl95ICsgMSkK"
    "ICAgICAgICAgICAgZ3JhZC5zZXRDb2xvckF0KDAsIFFDb2xvcihiYXJfY29sb3IpLmRhcmtlcigx"
    "NjApKQogICAgICAgICAgICBncmFkLnNldENvbG9yQXQoMSwgUUNvbG9yKGJhcl9jb2xvcikpCiAg"
    "ICAgICAgICAgIHAuZmlsbFJlY3QoNywgYmFyX3kgKyAxLCBmaWxsX3csIGJhcl9oIC0gMiwgZ3Jh"
    "ZCkKCiAgICAgICAgcC5lbmQoKQoKCiMg4pSA4pSAIERSSVZFIFdJREdFVCDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKY2xhc3MgRHJpdmVXaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIERyaXZlIHVzYWdlIGRp"
    "c3BsYXkuIFNob3dzIGRyaXZlIGxldHRlciwgdXNlZC90b3RhbCBHQiwgZmlsbCBiYXIuCiAgICBB"
    "dXRvLWRldGVjdHMgYWxsIG1vdW50ZWQgZHJpdmVzIHZpYSBwc3V0aWwuCiAgICAiIiIKCiAgICBk"
    "ZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18o"
    "cGFyZW50KQogICAgICAgIHNlbGYuX2RyaXZlczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2Vs"
    "Zi5zZXRNaW5pbXVtSGVpZ2h0KDMwKQogICAgICAgIHNlbGYuX3JlZnJlc2goKQoKICAgIGRlZiBf"
    "cmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2RyaXZlcyA9IFtdCiAgICAgICAg"
    "aWYgbm90IFBTVVRJTF9PSzoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICBmb3IgcGFydCBpbiBwc3V0aWwuZGlza19wYXJ0aXRpb25zKGFsbD1GYWxzZSk6CiAgICAg"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgdXNhZ2UgPSBwc3V0aWwuZGlza191"
    "c2FnZShwYXJ0Lm1vdW50cG9pbnQpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZHJpdmVzLmFw"
    "cGVuZCh7CiAgICAgICAgICAgICAgICAgICAgICAgICJsZXR0ZXIiOiBwYXJ0LmRldmljZS5yc3Ry"
    "aXAoIlxcIikucnN0cmlwKCIvIiksCiAgICAgICAgICAgICAgICAgICAgICAgICJ1c2VkIjogICB1"
    "c2FnZS51c2VkICAvIDEwMjQqKjMsCiAgICAgICAgICAgICAgICAgICAgICAgICJ0b3RhbCI6ICB1"
    "c2FnZS50b3RhbCAvIDEwMjQqKjMsCiAgICAgICAgICAgICAgICAgICAgICAgICJwY3QiOiAgICB1"
    "c2FnZS5wZXJjZW50IC8gMTAwLjAsCiAgICAgICAgICAgICAgICAgICAgfSkKICAgICAgICAgICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgY29udGludWUKICAgICAg"
    "ICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICAgICAgIyBSZXNpemUgdG8g"
    "Zml0IGFsbCBkcml2ZXMKICAgICAgICBuID0gbWF4KDEsIGxlbihzZWxmLl9kcml2ZXMpKQogICAg"
    "ICAgIHNlbGYuc2V0TWluaW11bUhlaWdodChuICogMjggKyA4KQogICAgICAgIHNlbGYudXBkYXRl"
    "KCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICBwID0g"
    "UVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQoUVBhaW50ZXIuUmVuZGVySGlu"
    "dC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lkdGgoKSwgc2VsZi5oZWlnaHQo"
    "KQogICAgICAgIHAuZmlsbFJlY3QoMCwgMCwgdywgaCwgUUNvbG9yKENfQkczKSkKCiAgICAgICAg"
    "aWYgbm90IHNlbGYuX2RyaXZlczoKICAgICAgICAgICAgcC5zZXRQZW4oUUNvbG9yKENfVEVYVF9E"
    "SU0pKQogICAgICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA5KSkKICAgICAgICAg"
    "ICAgcC5kcmF3VGV4dCg2LCAxOCwgIk4vQSDigJQgcHN1dGlsIHVuYXZhaWxhYmxlIikKICAgICAg"
    "ICAgICAgcC5lbmQoKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgcm93X2ggPSAyNgogICAg"
    "ICAgIHkgPSA0CiAgICAgICAgZm9yIGRydiBpbiBzZWxmLl9kcml2ZXM6CiAgICAgICAgICAgIGxl"
    "dHRlciA9IGRydlsibGV0dGVyIl0KICAgICAgICAgICAgdXNlZCAgID0gZHJ2WyJ1c2VkIl0KICAg"
    "ICAgICAgICAgdG90YWwgID0gZHJ2WyJ0b3RhbCJdCiAgICAgICAgICAgIHBjdCAgICA9IGRydlsi"
    "cGN0Il0KCiAgICAgICAgICAgICMgTGFiZWwKICAgICAgICAgICAgbGFiZWwgPSBmIntsZXR0ZXJ9"
    "ICB7dXNlZDouMWZ9L3t0b3RhbDouMGZ9R0IiCiAgICAgICAgICAgIHAuc2V0UGVuKFFDb2xvcihD"
    "X0dPTEQpKQogICAgICAgICAgICBwLnNldEZvbnQoUUZvbnQoREVDS19GT05ULCA4LCBRRm9udC5X"
    "ZWlnaHQuQm9sZCkpCiAgICAgICAgICAgIHAuZHJhd1RleHQoNiwgeSArIDEyLCBsYWJlbCkKCiAg"
    "ICAgICAgICAgICMgQmFyCiAgICAgICAgICAgIGJhcl94ID0gNgogICAgICAgICAgICBiYXJfeSA9"
    "IHkgKyAxNQogICAgICAgICAgICBiYXJfdyA9IHcgLSAxMgogICAgICAgICAgICBiYXJfaCA9IDgK"
    "ICAgICAgICAgICAgcC5maWxsUmVjdChiYXJfeCwgYmFyX3ksIGJhcl93LCBiYXJfaCwgUUNvbG9y"
    "KENfQkcpKQogICAgICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19CT1JERVIpKQogICAgICAgICAg"
    "ICBwLmRyYXdSZWN0KGJhcl94LCBiYXJfeSwgYmFyX3cgLSAxLCBiYXJfaCAtIDEpCgogICAgICAg"
    "ICAgICBmaWxsX3cgPSBtYXgoMSwgaW50KChiYXJfdyAtIDIpICogcGN0KSkKICAgICAgICAgICAg"
    "YmFyX2NvbG9yID0gKENfQkxPT0QgaWYgcGN0ID4gMC45IGVsc2UKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgIENfQ1JJTVNPTiBpZiBwY3QgPiAwLjc1IGVsc2UKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIENfR09MRF9ESU0pCiAgICAgICAgICAgIGdyYWQgPSBRTGluZWFyR3JhZGllbnQoYmFyX3gg"
    "KyAxLCBiYXJfeSwgYmFyX3ggKyBmaWxsX3csIGJhcl95KQogICAgICAgICAgICBncmFkLnNldENv"
    "bG9yQXQoMCwgUUNvbG9yKGJhcl9jb2xvcikuZGFya2VyKDE1MCkpCiAgICAgICAgICAgIGdyYWQu"
    "c2V0Q29sb3JBdCgxLCBRQ29sb3IoYmFyX2NvbG9yKSkKICAgICAgICAgICAgcC5maWxsUmVjdChi"
    "YXJfeCArIDEsIGJhcl95ICsgMSwgZmlsbF93LCBiYXJfaCAtIDIsIGdyYWQpCgogICAgICAgICAg"
    "ICB5ICs9IHJvd19oCgogICAgICAgIHAuZW5kKCkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBO"
    "b25lOgogICAgICAgICIiIkNhbGwgcGVyaW9kaWNhbGx5IHRvIHVwZGF0ZSBkcml2ZSBzdGF0cy4i"
    "IiIKICAgICAgICBzZWxmLl9yZWZyZXNoKCkKCgojIOKUgOKUgCBTUEhFUkUgV0lER0VUIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgApjbGFzcyBTcGhlcmVXaWRnZXQoUVdpZGdldCk6CiAgICAiIiIKICAgIEZpbGxlZCBj"
    "aXJjbGUgZ2F1Z2Ug4oCUIHVzZWQgZm9yIEJMT09EICh0b2tlbiBwb29sKSBhbmQgTUFOQSAoVlJB"
    "TSkuCiAgICBGaWxscyBmcm9tIGJvdHRvbSB1cC4gR2xhc3N5IHNoaW5lIGVmZmVjdC4gTGFiZWwg"
    "YmVsb3cuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwKICAgICAgICBs"
    "YWJlbDogc3RyLAogICAgICAgIGNvbG9yX2Z1bGw6IHN0ciwKICAgICAgICBjb2xvcl9lbXB0eTog"
    "c3RyLAogICAgICAgIHBhcmVudD1Ob25lCiAgICApOgogICAgICAgIHN1cGVyKCkuX19pbml0X18o"
    "cGFyZW50KQogICAgICAgIHNlbGYubGFiZWwgICAgICAgPSBsYWJlbAogICAgICAgIHNlbGYuY29s"
    "b3JfZnVsbCAgPSBjb2xvcl9mdWxsCiAgICAgICAgc2VsZi5jb2xvcl9lbXB0eSA9IGNvbG9yX2Vt"
    "cHR5CiAgICAgICAgc2VsZi5fZmlsbCAgICAgICA9IDAuMCAgICMgMC4wIOKGkiAxLjAKICAgICAg"
    "ICBzZWxmLl9hdmFpbGFibGUgID0gVHJ1ZQogICAgICAgIHNlbGYuc2V0TWluaW11bVNpemUoODAs"
    "IDEwMCkKCiAgICBkZWYgc2V0RmlsbChzZWxmLCBmcmFjdGlvbjogZmxvYXQsIGF2YWlsYWJsZTog"
    "Ym9vbCA9IFRydWUpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZmlsbCAgICAgID0gbWF4KDAuMCwg"
    "bWluKDEuMCwgZnJhY3Rpb24pKQogICAgICAgIHNlbGYuX2F2YWlsYWJsZSA9IGF2YWlsYWJsZQog"
    "ICAgICAgIHNlbGYudXBkYXRlKCkKCiAgICBkZWYgcGFpbnRFdmVudChzZWxmLCBldmVudCkgLT4g"
    "Tm9uZToKICAgICAgICBwID0gUVBhaW50ZXIoc2VsZikKICAgICAgICBwLnNldFJlbmRlckhpbnQo"
    "UVBhaW50ZXIuUmVuZGVySGludC5BbnRpYWxpYXNpbmcpCiAgICAgICAgdywgaCA9IHNlbGYud2lk"
    "dGgoKSwgc2VsZi5oZWlnaHQoKQoKICAgICAgICByICA9IG1pbih3LCBoIC0gMjApIC8vIDIgLSA0"
    "CiAgICAgICAgY3ggPSB3IC8vIDIKICAgICAgICBjeSA9IChoIC0gMjApIC8vIDIgKyA0CgogICAg"
    "ICAgICMgRHJvcCBzaGFkb3cKICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAg"
    "ICAgICBwLnNldEJydXNoKFFDb2xvcigwLCAwLCAwLCA4MCkpCiAgICAgICAgcC5kcmF3RWxsaXBz"
    "ZShjeCAtIHIgKyAzLCBjeSAtIHIgKyAzLCByICogMiwgciAqIDIpCgogICAgICAgICMgQmFzZSBj"
    "aXJjbGUgKGVtcHR5IGNvbG9yKQogICAgICAgIHAuc2V0QnJ1c2goUUNvbG9yKHNlbGYuY29sb3Jf"
    "ZW1wdHkpKQogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX0JPUkRFUikpCiAgICAgICAgcC5kcmF3"
    "RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIEZpbGwgZnJv"
    "bSBib3R0b20KICAgICAgICBpZiBzZWxmLl9maWxsID4gMC4wMSBhbmQgc2VsZi5fYXZhaWxhYmxl"
    "OgogICAgICAgICAgICBjaXJjbGVfcGF0aCA9IFFQYWludGVyUGF0aCgpCiAgICAgICAgICAgIGNp"
    "cmNsZV9wYXRoLmFkZEVsbGlwc2UoZmxvYXQoY3ggLSByKSwgZmxvYXQoY3kgLSByKSwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmbG9hdChyICogMiksIGZsb2F0KHIgKiAyKSkK"
    "CiAgICAgICAgICAgIGZpbGxfdG9wX3kgPSBjeSArIHIgLSAoc2VsZi5fZmlsbCAqIHIgKiAyKQog"
    "ICAgICAgICAgICBmcm9tIFB5U2lkZTYuUXRDb3JlIGltcG9ydCBRUmVjdEYKICAgICAgICAgICAg"
    "ZmlsbF9yZWN0ID0gUVJlY3RGKGN4IC0gciwgZmlsbF90b3BfeSwgciAqIDIsIGN5ICsgciAtIGZp"
    "bGxfdG9wX3kpCiAgICAgICAgICAgIGZpbGxfcGF0aCA9IFFQYWludGVyUGF0aCgpCiAgICAgICAg"
    "ICAgIGZpbGxfcGF0aC5hZGRSZWN0KGZpbGxfcmVjdCkKICAgICAgICAgICAgY2xpcHBlZCA9IGNp"
    "cmNsZV9wYXRoLmludGVyc2VjdGVkKGZpbGxfcGF0aCkKCiAgICAgICAgICAgIHAuc2V0UGVuKFF0"
    "LlBlblN0eWxlLk5vUGVuKQogICAgICAgICAgICBwLnNldEJydXNoKFFDb2xvcihzZWxmLmNvbG9y"
    "X2Z1bGwpKQogICAgICAgICAgICBwLmRyYXdQYXRoKGNsaXBwZWQpCgogICAgICAgICMgR2xhc3N5"
    "IHNoaW5lCiAgICAgICAgc2hpbmUgPSBRUmFkaWFsR3JhZGllbnQoCiAgICAgICAgICAgIGZsb2F0"
    "KGN4IC0gciAqIDAuMyksIGZsb2F0KGN5IC0gciAqIDAuMyksIGZsb2F0KHIgKiAwLjYpCiAgICAg"
    "ICAgKQogICAgICAgIHNoaW5lLnNldENvbG9yQXQoMCwgUUNvbG9yKDI1NSwgMjU1LCAyNTUsIDU1"
    "KSkKICAgICAgICBzaGluZS5zZXRDb2xvckF0KDEsIFFDb2xvcigyNTUsIDI1NSwgMjU1LCAwKSkK"
    "ICAgICAgICBwLnNldEJydXNoKHNoaW5lKQogICAgICAgIHAuc2V0UGVuKFF0LlBlblN0eWxlLk5v"
    "UGVuKQogICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikK"
    "CiAgICAgICAgIyBPdXRsaW5lCiAgICAgICAgcC5zZXRCcnVzaChRdC5CcnVzaFN0eWxlLk5vQnJ1"
    "c2gpCiAgICAgICAgcC5zZXRQZW4oUVBlbihRQ29sb3Ioc2VsZi5jb2xvcl9mdWxsKSwgMSkpCiAg"
    "ICAgICAgcC5kcmF3RWxsaXBzZShjeCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAg"
    "ICAjIE4vQSBvdmVybGF5CiAgICAgICAgaWYgbm90IHNlbGYuX2F2YWlsYWJsZToKICAgICAgICAg"
    "ICAgcC5zZXRQZW4oUUNvbG9yKENfVEVYVF9ESU0pKQogICAgICAgICAgICBwLnNldEZvbnQoUUZv"
    "bnQoIkNvdXJpZXIgTmV3IiwgOCkpCiAgICAgICAgICAgIGZtID0gcC5mb250TWV0cmljcygpCiAg"
    "ICAgICAgICAgIHR4dCA9ICJOL0EiCiAgICAgICAgICAgIHAuZHJhd1RleHQoY3ggLSBmbS5ob3Jp"
    "em9udGFsQWR2YW5jZSh0eHQpIC8vIDIsIGN5ICsgNCwgdHh0KQoKICAgICAgICAjIExhYmVsIGJl"
    "bG93IHNwaGVyZQogICAgICAgIGxhYmVsX3RleHQgPSAoc2VsZi5sYWJlbCBpZiBzZWxmLl9hdmFp"
    "bGFibGUgZWxzZQogICAgICAgICAgICAgICAgICAgICAgZiJ7c2VsZi5sYWJlbH0iKQogICAgICAg"
    "IHBjdF90ZXh0ID0gZiJ7aW50KHNlbGYuX2ZpbGwgKiAxMDApfSUiIGlmIHNlbGYuX2F2YWlsYWJs"
    "ZSBlbHNlICIiCgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihzZWxmLmNvbG9yX2Z1bGwpKQogICAg"
    "ICAgIHAuc2V0Rm9udChRRm9udChERUNLX0ZPTlQsIDgsIFFGb250LldlaWdodC5Cb2xkKSkKICAg"
    "ICAgICBmbSA9IHAuZm9udE1ldHJpY3MoKQoKICAgICAgICBsdyA9IGZtLmhvcml6b250YWxBZHZh"
    "bmNlKGxhYmVsX3RleHQpCiAgICAgICAgcC5kcmF3VGV4dChjeCAtIGx3IC8vIDIsIGggLSAxMCwg"
    "bGFiZWxfdGV4dCkKCiAgICAgICAgaWYgcGN0X3RleHQ6CiAgICAgICAgICAgIHAuc2V0UGVuKFFD"
    "b2xvcihDX1RFWFRfRElNKSkKICAgICAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwg"
    "NykpCiAgICAgICAgICAgIGZtMiA9IHAuZm9udE1ldHJpY3MoKQogICAgICAgICAgICBwdyA9IGZt"
    "Mi5ob3Jpem9udGFsQWR2YW5jZShwY3RfdGV4dCkKICAgICAgICAgICAgcC5kcmF3VGV4dChjeCAt"
    "IHB3IC8vIDIsIGggLSAxLCBwY3RfdGV4dCkKCiAgICAgICAgcC5lbmQoKQoKCiMg4pSA4pSAIE1P"
    "T04gV0lER0VUIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBNb29uV2lkZ2V0KFFXaWRnZXQpOgog"
    "ICAgIiIiCiAgICBEcmF3biBtb29uIG9yYiB3aXRoIHBoYXNlLWFjY3VyYXRlIHNoYWRvdy4KCiAg"
    "ICBQSEFTRSBDT05WRU5USU9OIChub3J0aGVybiBoZW1pc3BoZXJlLCBzdGFuZGFyZCk6CiAgICAg"
    "IC0gV2F4aW5nIChuZXfihpJmdWxsKTogaWxsdW1pbmF0ZWQgcmlnaHQgc2lkZSwgc2hhZG93IG9u"
    "IGxlZnQKICAgICAgLSBXYW5pbmcgKGZ1bGzihpJuZXcpOiBpbGx1bWluYXRlZCBsZWZ0IHNpZGUs"
    "IHNoYWRvdyBvbiByaWdodAoKICAgIFRoZSBzaGFkb3dfc2lkZSBmbGFnIGNhbiBiZSBmbGlwcGVk"
    "IGlmIHRlc3RpbmcgcmV2ZWFscyBpdCdzIGJhY2t3YXJkcwogICAgb24gdGhpcyBtYWNoaW5lLiBT"
    "ZXQgTU9PTl9TSEFET1dfRkxJUCA9IFRydWUgaW4gdGhhdCBjYXNlLgogICAgIiIiCgogICAgIyDi"
    "hpAgRkxJUCBUSElTIHRvIFRydWUgaWYgbW9vbiBhcHBlYXJzIGJhY2t3YXJkcyBkdXJpbmcgdGVz"
    "dGluZwogICAgTU9PTl9TSEFET1dfRkxJUDogYm9vbCA9IEZhbHNlCgogICAgZGVmIF9faW5pdF9f"
    "KHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAg"
    "ICAgICBzZWxmLl9waGFzZSAgICAgICA9IDAuMCAgICAjIDAuMD1uZXcsIDAuNT1mdWxsLCAxLjA9"
    "bmV3CiAgICAgICAgc2VsZi5fbmFtZSAgICAgICAgPSAiTkVXIE1PT04iCiAgICAgICAgc2VsZi5f"
    "aWxsdW1pbmF0aW9uID0gMC4wICAgIyAwLTEwMAogICAgICAgIHNlbGYuX3N1bnJpc2UgICAgID0g"
    "IjA2OjAwIgogICAgICAgIHNlbGYuX3N1bnNldCAgICAgID0gIjE4OjMwIgogICAgICAgIHNlbGYu"
    "c2V0TWluaW11bVNpemUoODAsIDExMCkKICAgICAgICBzZWxmLnVwZGF0ZVBoYXNlKCkgICAgICAg"
    "ICAgIyBwb3B1bGF0ZSBjb3JyZWN0IHBoYXNlIGltbWVkaWF0ZWx5CiAgICAgICAgc2VsZi5fZmV0"
    "Y2hfc3VuX2FzeW5jKCkKCiAgICBkZWYgX2ZldGNoX3N1bl9hc3luYyhzZWxmKSAtPiBOb25lOgog"
    "ICAgICAgIGRlZiBfZmV0Y2goKToKICAgICAgICAgICAgc3IsIHNzID0gZ2V0X3N1bl90aW1lcygp"
    "CiAgICAgICAgICAgIHNlbGYuX3N1bnJpc2UgPSBzcgogICAgICAgICAgICBzZWxmLl9zdW5zZXQg"
    "ID0gc3MKICAgICAgICAgICAgIyBTY2hlZHVsZSByZXBhaW50IG9uIG1haW4gdGhyZWFkIHZpYSBR"
    "VGltZXIg4oCUIG5ldmVyIGNhbGwKICAgICAgICAgICAgIyBzZWxmLnVwZGF0ZSgpIGRpcmVjdGx5"
    "IGZyb20gYSBiYWNrZ3JvdW5kIHRocmVhZAogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgw"
    "LCBzZWxmLnVwZGF0ZSkKICAgICAgICB0aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fZmV0Y2gsIGRh"
    "ZW1vbj1UcnVlKS5zdGFydCgpCgogICAgZGVmIHVwZGF0ZVBoYXNlKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fcGhhc2UsIHNlbGYuX25hbWUsIHNlbGYuX2lsbHVtaW5hdGlvbiA9IGdldF9t"
    "b29uX3BoYXNlKCkKICAgICAgICBzZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2Vs"
    "ZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5z"
    "ZXRSZW5kZXJIaW50KFFQYWludGVyLlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcs"
    "IGggPSBzZWxmLndpZHRoKCksIHNlbGYuaGVpZ2h0KCkKCiAgICAgICAgciAgPSBtaW4odywgaCAt"
    "IDM2KSAvLyAyIC0gNAogICAgICAgIGN4ID0gdyAvLyAyCiAgICAgICAgY3kgPSAoaCAtIDM2KSAv"
    "LyAyICsgNAoKICAgICAgICAjIEJhY2tncm91bmQgY2lyY2xlIChzcGFjZSkKICAgICAgICBwLnNl"
    "dEJydXNoKFFDb2xvcigyMCwgMTIsIDI4KSkKICAgICAgICBwLnNldFBlbihRUGVuKFFDb2xvcihD"
    "X1NJTFZFUl9ESU0pLCAxKSkKICAgICAgICBwLmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCBy"
    "ICogMiwgciAqIDIpCgogICAgICAgIGN5Y2xlX2RheSA9IHNlbGYuX3BoYXNlICogX0xVTkFSX0NZ"
    "Q0xFCiAgICAgICAgaXNfd2F4aW5nID0gY3ljbGVfZGF5IDwgKF9MVU5BUl9DWUNMRSAvIDIpCgog"
    "ICAgICAgICMgRnVsbCBtb29uIGJhc2UgKG1vb24gc3VyZmFjZSBjb2xvcikKICAgICAgICBpZiBz"
    "ZWxmLl9pbGx1bWluYXRpb24gPiAxOgogICAgICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5O"
    "b1BlbikKICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMjIwLCAyMTAsIDE4NSkpCiAgICAg"
    "ICAgICAgIHAuZHJhd0VsbGlwc2UoY3ggLSByLCBjeSAtIHIsIHIgKiAyLCByICogMikKCiAgICAg"
    "ICAgIyBTaGFkb3cgY2FsY3VsYXRpb24KICAgICAgICAjIGlsbHVtaW5hdGlvbiBnb2VzIDDihpIx"
    "MDAgd2F4aW5nLCAxMDDihpIwIHdhbmluZwogICAgICAgICMgc2hhZG93X29mZnNldCBjb250cm9s"
    "cyBob3cgbXVjaCBvZiB0aGUgY2lyY2xlIHRoZSBzaGFkb3cgY292ZXJzCiAgICAgICAgaWYgc2Vs"
    "Zi5faWxsdW1pbmF0aW9uIDwgOTk6CiAgICAgICAgICAgICMgZnJhY3Rpb24gb2YgZGlhbWV0ZXIg"
    "dGhlIHNoYWRvdyBlbGxpcHNlIGlzIG9mZnNldAogICAgICAgICAgICBpbGx1bV9mcmFjICA9IHNl"
    "bGYuX2lsbHVtaW5hdGlvbiAvIDEwMC4wCiAgICAgICAgICAgIHNoYWRvd19mcmFjID0gMS4wIC0g"
    "aWxsdW1fZnJhYwoKICAgICAgICAgICAgIyB3YXhpbmc6IGlsbHVtaW5hdGVkIHJpZ2h0LCBzaGFk"
    "b3cgTEVGVAogICAgICAgICAgICAjIHdhbmluZzogaWxsdW1pbmF0ZWQgbGVmdCwgc2hhZG93IFJJ"
    "R0hUCiAgICAgICAgICAgICMgb2Zmc2V0IG1vdmVzIHRoZSBzaGFkb3cgZWxsaXBzZSBob3Jpem9u"
    "dGFsbHkKICAgICAgICAgICAgb2Zmc2V0ID0gaW50KHNoYWRvd19mcmFjICogciAqIDIpCgogICAg"
    "ICAgICAgICBpZiBNb29uV2lkZ2V0Lk1PT05fU0hBRE9XX0ZMSVA6CiAgICAgICAgICAgICAgICBp"
    "c193YXhpbmcgPSBub3QgaXNfd2F4aW5nCgogICAgICAgICAgICBpZiBpc193YXhpbmc6CiAgICAg"
    "ICAgICAgICAgICAjIFNoYWRvdyBvbiBsZWZ0IHNpZGUKICAgICAgICAgICAgICAgIHNoYWRvd194"
    "ID0gY3ggLSByIC0gb2Zmc2V0CiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAjIFNo"
    "YWRvdyBvbiByaWdodCBzaWRlCiAgICAgICAgICAgICAgICBzaGFkb3dfeCA9IGN4IC0gciArIG9m"
    "ZnNldAoKICAgICAgICAgICAgcC5zZXRCcnVzaChRQ29sb3IoMTUsIDgsIDIyKSkKICAgICAgICAg"
    "ICAgcC5zZXRQZW4oUXQuUGVuU3R5bGUuTm9QZW4pCgogICAgICAgICAgICAjIERyYXcgc2hhZG93"
    "IGVsbGlwc2Ug4oCUIGNsaXBwZWQgdG8gbW9vbiBjaXJjbGUKICAgICAgICAgICAgbW9vbl9wYXRo"
    "ID0gUVBhaW50ZXJQYXRoKCkKICAgICAgICAgICAgbW9vbl9wYXRoLmFkZEVsbGlwc2UoZmxvYXQo"
    "Y3ggLSByKSwgZmxvYXQoY3kgLSByKSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IGZsb2F0KHIgKiAyKSwgZmxvYXQociAqIDIpKQogICAgICAgICAgICBzaGFkb3dfcGF0aCA9IFFQ"
    "YWludGVyUGF0aCgpCiAgICAgICAgICAgIHNoYWRvd19wYXRoLmFkZEVsbGlwc2UoZmxvYXQoc2hh"
    "ZG93X3gpLCBmbG9hdChjeSAtIHIpLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICBmbG9hdChyICogMiksIGZsb2F0KHIgKiAyKSkKICAgICAgICAgICAgY2xpcHBlZF9zaGFkb3cg"
    "PSBtb29uX3BhdGguaW50ZXJzZWN0ZWQoc2hhZG93X3BhdGgpCiAgICAgICAgICAgIHAuZHJhd1Bh"
    "dGgoY2xpcHBlZF9zaGFkb3cpCgogICAgICAgICMgU3VidGxlIHN1cmZhY2UgZGV0YWlsIChjcmF0"
    "ZXJzIGltcGxpZWQgYnkgc2xpZ2h0IHRleHR1cmUgZ3JhZGllbnQpCiAgICAgICAgc2hpbmUgPSBR"
    "UmFkaWFsR3JhZGllbnQoZmxvYXQoY3ggLSByICogMC4yKSwgZmxvYXQoY3kgLSByICogMC4yKSwK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmbG9hdChyICogMC44KSkKICAgICAgICBz"
    "aGluZS5zZXRDb2xvckF0KDAsIFFDb2xvcigyNTUsIDI1NSwgMjQwLCAzMCkpCiAgICAgICAgc2hp"
    "bmUuc2V0Q29sb3JBdCgxLCBRQ29sb3IoMjAwLCAxODAsIDE0MCwgNSkpCiAgICAgICAgcC5zZXRC"
    "cnVzaChzaGluZSkKICAgICAgICBwLnNldFBlbihRdC5QZW5TdHlsZS5Ob1BlbikKICAgICAgICBw"
    "LmRyYXdFbGxpcHNlKGN4IC0gciwgY3kgLSByLCByICogMiwgciAqIDIpCgogICAgICAgICMgT3V0"
    "bGluZQogICAgICAgIHAuc2V0QnJ1c2goUXQuQnJ1c2hTdHlsZS5Ob0JydXNoKQogICAgICAgIHAu"
    "c2V0UGVuKFFQZW4oUUNvbG9yKENfU0lMVkVSKSwgMSkpCiAgICAgICAgcC5kcmF3RWxsaXBzZShj"
    "eCAtIHIsIGN5IC0gciwgciAqIDIsIHIgKiAyKQoKICAgICAgICAjIFBoYXNlIG5hbWUgYmVsb3cg"
    "bW9vbgogICAgICAgIHAuc2V0UGVuKFFDb2xvcihDX1NJTFZFUikpCiAgICAgICAgcC5zZXRGb250"
    "KFFGb250KERFQ0tfRk9OVCwgNywgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIGZtID0gcC5m"
    "b250TWV0cmljcygpCiAgICAgICAgbncgPSBmbS5ob3Jpem9udGFsQWR2YW5jZShzZWxmLl9uYW1l"
    "KQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBudyAvLyAyLCBjeSArIHIgKyAxNCwgc2VsZi5fbmFt"
    "ZSkKCiAgICAgICAgIyBJbGx1bWluYXRpb24gcGVyY2VudGFnZQogICAgICAgIGlsbHVtX3N0ciA9"
    "IGYie3NlbGYuX2lsbHVtaW5hdGlvbjouMGZ9JSIKICAgICAgICBwLnNldFBlbihRQ29sb3IoQ19U"
    "RVhUX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERFQ0tfRk9OVCwgNykpCiAgICAgICAg"
    "Zm0yID0gcC5mb250TWV0cmljcygpCiAgICAgICAgaXcgPSBmbTIuaG9yaXpvbnRhbEFkdmFuY2Uo"
    "aWxsdW1fc3RyKQogICAgICAgIHAuZHJhd1RleHQoY3ggLSBpdyAvLyAyLCBjeSArIHIgKyAyNCwg"
    "aWxsdW1fc3RyKQoKICAgICAgICAjIFN1biB0aW1lcyBhdCB2ZXJ5IGJvdHRvbQogICAgICAgIHN1"
    "bl9zdHIgPSBmIuKYgCB7c2VsZi5fc3VucmlzZX0gIOKYvSB7c2VsZi5fc3Vuc2V0fSIKICAgICAg"
    "ICBwLnNldFBlbihRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgcC5zZXRGb250KFFGb250KERF"
    "Q0tfRk9OVCwgNykpCiAgICAgICAgZm0zID0gcC5mb250TWV0cmljcygpCiAgICAgICAgc3cgPSBm"
    "bTMuaG9yaXpvbnRhbEFkdmFuY2Uoc3VuX3N0cikKICAgICAgICBwLmRyYXdUZXh0KGN4IC0gc3cg"
    "Ly8gMiwgaCAtIDIsIHN1bl9zdHIpCgogICAgICAgIHAuZW5kKCkKCgojIOKUgOKUgCBFTU9USU9O"
    "IEJMT0NLIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBFbW90aW9uQmxvY2soUVdpZGdldCk6CiAgICAiIiIK"
    "ICAgIENvbGxhcHNpYmxlIGVtb3Rpb24gaGlzdG9yeSBwYW5lbC4KICAgIFNob3dzIGNvbG9yLWNv"
    "ZGVkIGNoaXBzOiDinKYgRU1PVElPTl9OQU1FICBISDpNTQogICAgU2l0cyBuZXh0IHRvIHRoZSBN"
    "aXJyb3IgKGZhY2Ugd2lkZ2V0KSBpbiB0aGUgYm90dG9tIGJsb2NrIHJvdy4KICAgIENvbGxhcHNl"
    "cyB0byBqdXN0IHRoZSBoZWFkZXIgc3RyaXAuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2Vs"
    "ZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAg"
    "IHNlbGYuX2hpc3Rvcnk6IGxpc3RbdHVwbGVbc3RyLCBzdHJdXSA9IFtdICAjIChlbW90aW9uLCB0"
    "aW1lc3RhbXApCiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBUcnVlCiAgICAgICAgc2VsZi5fbWF4"
    "X2VudHJpZXMgPSAzMAoKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91dChzZWxmKQogICAgICAg"
    "IGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAgICAgICBsYXlvdXQuc2V0"
    "U3BhY2luZygwKQoKICAgICAgICAjIEhlYWRlciByb3cKICAgICAgICBoZWFkZXIgPSBRV2lkZ2V0"
    "KCkKICAgICAgICBoZWFkZXIuc2V0Rml4ZWRIZWlnaHQoMjIpCiAgICAgICAgaGVhZGVyLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyLWJvdHRv"
    "bTogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIGhsID0gUUhC"
    "b3hMYXlvdXQoaGVhZGVyKQogICAgICAgIGhsLnNldENvbnRlbnRzTWFyZ2lucyg2LCAwLCA0LCAw"
    "KQogICAgICAgIGhsLnNldFNwYWNpbmcoNCkKCiAgICAgICAgbGJsID0gUUxhYmVsKCLinacgRU1P"
    "VElPTkFMIFJFQ09SRCIpCiAgICAgICAgbGJsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "Y29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAg"
    "ICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2lu"
    "ZzogMXB4OyBib3JkZXI6IG5vbmU7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRu"
    "ID0gUVRvb2xCdXR0b24oKQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0Rml4ZWRTaXplKDE2"
    "LCAxNikKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "IGYiYmFja2dyb3VuZDogdHJhbnNwYXJlbnQ7IGNvbG9yOiB7Q19HT0xEfTsgYm9yZGVyOiBub25l"
    "OyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNl"
    "dFRleHQoIuKWvCIpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fdG9nZ2xlKQoKICAgICAgICBobC5hZGRXaWRnZXQobGJsKQogICAgICAgIGhsLmFkZFN0cmV0"
    "Y2goKQogICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl90b2dnbGVfYnRuKQoKICAgICAgICAjIFNj"
    "cm9sbCBhcmVhIGZvciBlbW90aW9uIGNoaXBzCiAgICAgICAgc2VsZi5fc2Nyb2xsID0gUVNjcm9s"
    "bEFyZWEoKQogICAgICAgIHNlbGYuX3Njcm9sbC5zZXRXaWRnZXRSZXNpemFibGUoVHJ1ZSkKICAg"
    "ICAgICBzZWxmLl9zY3JvbGwuc2V0SG9yaXpvbnRhbFNjcm9sbEJhclBvbGljeSgKICAgICAgICAg"
    "ICAgUXQuU2Nyb2xsQmFyUG9saWN5LlNjcm9sbEJhckFsd2F5c09mZikKICAgICAgICBzZWxmLl9z"
    "Y3JvbGwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBi"
    "b3JkZXI6IG5vbmU7IgogICAgICAgICkKCiAgICAgICAgc2VsZi5fY2hpcF9jb250YWluZXIgPSBR"
    "V2lkZ2V0KCkKICAgICAgICBzZWxmLl9jaGlwX2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX2No"
    "aXBfY29udGFpbmVyKQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lu"
    "cyg0LCA0LCA0LCA0KQogICAgICAgIHNlbGYuX2NoaXBfbGF5b3V0LnNldFNwYWNpbmcoMikKICAg"
    "ICAgICBzZWxmLl9jaGlwX2xheW91dC5hZGRTdHJldGNoKCkKICAgICAgICBzZWxmLl9zY3JvbGwu"
    "c2V0V2lkZ2V0KHNlbGYuX2NoaXBfY29udGFpbmVyKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0"
    "KGhlYWRlcikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Njcm9sbCkKCiAgICAgICAg"
    "c2VsZi5zZXRNaW5pbXVtV2lkdGgoMTMwKQoKICAgIGRlZiBfdG9nZ2xlKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5kZWQKICAgICAgICBzZWxm"
    "Ll9zY3JvbGwuc2V0VmlzaWJsZShzZWxmLl9leHBhbmRlZCkKICAgICAgICBzZWxmLl90b2dnbGVf"
    "YnRuLnNldFRleHQoIuKWvCIgaWYgc2VsZi5fZXhwYW5kZWQgZWxzZSAi4payIikKICAgICAgICBz"
    "ZWxmLnVwZGF0ZUdlb21ldHJ5KCkKCiAgICBkZWYgYWRkRW1vdGlvbihzZWxmLCBlbW90aW9uOiBz"
    "dHIsIHRpbWVzdGFtcDogc3RyID0gIiIpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHRpbWVzdGFt"
    "cDoKICAgICAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVN"
    "IikKICAgICAgICBzZWxmLl9oaXN0b3J5Lmluc2VydCgwLCAoZW1vdGlvbiwgdGltZXN0YW1wKSkK"
    "ICAgICAgICBzZWxmLl9oaXN0b3J5ID0gc2VsZi5faGlzdG9yeVs6c2VsZi5fbWF4X2VudHJpZXNd"
    "CiAgICAgICAgc2VsZi5fcmVidWlsZF9jaGlwcygpCgogICAgZGVmIF9yZWJ1aWxkX2NoaXBzKHNl"
    "bGYpIC0+IE5vbmU6CiAgICAgICAgIyBDbGVhciBleGlzdGluZyBjaGlwcyAoa2VlcCB0aGUgc3Ry"
    "ZXRjaCBhdCBlbmQpCiAgICAgICAgd2hpbGUgc2VsZi5fY2hpcF9sYXlvdXQuY291bnQoKSA+IDE6"
    "CiAgICAgICAgICAgIGl0ZW0gPSBzZWxmLl9jaGlwX2xheW91dC50YWtlQXQoMCkKICAgICAgICAg"
    "ICAgaWYgaXRlbS53aWRnZXQoKToKICAgICAgICAgICAgICAgIGl0ZW0ud2lkZ2V0KCkuZGVsZXRl"
    "TGF0ZXIoKQoKICAgICAgICBmb3IgZW1vdGlvbiwgdHMgaW4gc2VsZi5faGlzdG9yeToKICAgICAg"
    "ICAgICAgY29sb3IgPSBFTU9USU9OX0NPTE9SUy5nZXQoZW1vdGlvbiwgQ19URVhUX0RJTSkKICAg"
    "ICAgICAgICAgY2hpcCA9IFFMYWJlbChmIuKcpiB7ZW1vdGlvbi51cHBlcigpfSAge3RzfSIpCiAg"
    "ICAgICAgICAgIGNoaXAuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiY29sb3I6IHtj"
    "b2xvcn07IGZvbnQtc2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyAi"
    "CiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGJvcmRlcjogMXB4IHNvbGlk"
    "IHtDX0JPUkRFUn07ICIKICAgICAgICAgICAgICAgIGYicGFkZGluZzogMXB4IDRweDsgYm9yZGVy"
    "LXJhZGl1czogMnB4OyIKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9jaGlwX2xheW91"
    "dC5pbnNlcnRXaWRnZXQoCiAgICAgICAgICAgICAgICBzZWxmLl9jaGlwX2xheW91dC5jb3VudCgp"
    "IC0gMSwgY2hpcAogICAgICAgICAgICApCgogICAgZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5faGlzdG9yeS5jbGVhcigpCiAgICAgICAgc2VsZi5fcmVidWlsZF9jaGlwcygp"
    "CgoKIyDilIDilIAgTUlSUk9SIFdJREdFVCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTWlycm9yV2lkZ2V0"
    "KFFMYWJlbCk6CiAgICAiIiIKICAgIEZhY2UgaW1hZ2UgZGlzcGxheSDigJQgJ1RoZSBNaXJyb3In"
    "LgogICAgRHluYW1pY2FsbHkgbG9hZHMgYWxsIHtGQUNFX1BSRUZJWH1fKi5wbmcgZmlsZXMgZnJv"
    "bSBjb25maWcgcGF0aHMuZmFjZXMuCiAgICBBdXRvLW1hcHMgZmlsZW5hbWUgdG8gZW1vdGlvbiBr"
    "ZXk6CiAgICAgICAge0ZBQ0VfUFJFRklYfV9BbGVydC5wbmcgICAgIOKGkiAiYWxlcnQiCiAgICAg"
    "ICAge0ZBQ0VfUFJFRklYfV9TYWRfQ3J5aW5nLnBuZyDihpIgInNhZCIKICAgICAgICB7RkFDRV9Q"
    "UkVGSVh9X0NoZWF0X01vZGUucG5nIOKGkiAiY2hlYXRtb2RlIgogICAgRmFsbHMgYmFjayB0byBu"
    "ZXV0cmFsLCB0aGVuIHRvIGdvdGhpYyBwbGFjZWhvbGRlciBpZiBubyBpbWFnZXMgZm91bmQuCiAg"
    "ICBNaXNzaW5nIGZhY2VzIGRlZmF1bHQgdG8gbmV1dHJhbCDigJQgbm8gY3Jhc2gsIG5vIGhhcmRj"
    "b2RlZCBsaXN0IHJlcXVpcmVkLgogICAgIiIiCgogICAgIyBTcGVjaWFsIHN0ZW0g4oaSIGVtb3Rp"
    "b24ga2V5IG1hcHBpbmdzIChsb3dlcmNhc2Ugc3RlbSBhZnRlciBNb3JnYW5uYV8pCiAgICBfU1RF"
    "TV9UT19FTU9USU9OOiBkaWN0W3N0ciwgc3RyXSA9IHsKICAgICAgICAic2FkX2NyeWluZyI6ICAi"
    "c2FkIiwKICAgICAgICAiY2hlYXRfbW9kZSI6ICAiY2hlYXRtb2RlIiwKICAgIH0KCiAgICBkZWYg"
    "X19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFy"
    "ZW50KQogICAgICAgIHNlbGYuX2ZhY2VzX2RpciAgID0gY2ZnX3BhdGgoImZhY2VzIikKICAgICAg"
    "ICBzZWxmLl9jYWNoZTogZGljdFtzdHIsIFFQaXhtYXBdID0ge30KICAgICAgICBzZWxmLl9jdXJy"
    "ZW50ICAgICA9ICJuZXV0cmFsIgogICAgICAgIHNlbGYuX3dhcm5lZDogc2V0W3N0cl0gPSBzZXQo"
    "KQoKICAgICAgICBzZWxmLnNldE1pbmltdW1TaXplKDE2MCwgMTYwKQogICAgICAgIHNlbGYuc2V0"
    "QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgc2VsZi5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogMXB4"
    "IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImJvcmRlci1yYWRpdXM6IDJw"
    "eDsiCiAgICAgICAgKQoKICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgzMDAsIHNlbGYuX3ByZWxv"
    "YWQpCgogICAgZGVmIF9wcmVsb2FkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAg"
    "U2NhbiBGYWNlcy8gZGlyZWN0b3J5IGZvciBhbGwge0ZBQ0VfUFJFRklYfV8qLnBuZyBmaWxlcy4K"
    "ICAgICAgICBCdWlsZCBlbW90aW9u4oaScGl4bWFwIGNhY2hlIGR5bmFtaWNhbGx5LgogICAgICAg"
    "IE5vIGhhcmRjb2RlZCBsaXN0IOKAlCB3aGF0ZXZlciBpcyBpbiB0aGUgZm9sZGVyIGlzIGF2YWls"
    "YWJsZS4KICAgICAgICAiIiIKICAgICAgICBpZiBub3Qgc2VsZi5fZmFjZXNfZGlyLmV4aXN0cygp"
    "OgogICAgICAgICAgICBzZWxmLl9kcmF3X3BsYWNlaG9sZGVyKCkKICAgICAgICAgICAgcmV0dXJu"
    "CgogICAgICAgIGZvciBpbWdfcGF0aCBpbiBzZWxmLl9mYWNlc19kaXIuZ2xvYihmIntGQUNFX1BS"
    "RUZJWH1fKi5wbmciKToKICAgICAgICAgICAgIyBzdGVtID0gZXZlcnl0aGluZyBhZnRlciAiTW9y"
    "Z2FubmFfIiB3aXRob3V0IC5wbmcKICAgICAgICAgICAgcmF3X3N0ZW0gPSBpbWdfcGF0aC5zdGVt"
    "W2xlbihmIntGQUNFX1BSRUZJWH1fIik6XSAgICAjIGUuZy4gIlNhZF9DcnlpbmciCiAgICAgICAg"
    "ICAgIHN0ZW1fbG93ZXIgPSByYXdfc3RlbS5sb3dlcigpICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAjICJzYWRfY3J5aW5nIgoKICAgICAgICAgICAgIyBNYXAgc3BlY2lhbCBzdGVtcyB0byBlbW90"
    "aW9uIGtleXMKICAgICAgICAgICAgZW1vdGlvbiA9IHNlbGYuX1NURU1fVE9fRU1PVElPTi5nZXQo"
    "c3RlbV9sb3dlciwgc3RlbV9sb3dlcikKCiAgICAgICAgICAgIHB4ID0gUVBpeG1hcChzdHIoaW1n"
    "X3BhdGgpKQogICAgICAgICAgICBpZiBub3QgcHguaXNOdWxsKCk6CiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9jYWNoZVtlbW90aW9uXSA9IHB4CgogICAgICAgIGlmIHNlbGYuX2NhY2hlOgogICAgICAg"
    "ICAgICBzZWxmLl9yZW5kZXIoIm5ldXRyYWwiKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNl"
    "bGYuX2RyYXdfcGxhY2Vob2xkZXIoKQoKICAgIGRlZiBfcmVuZGVyKHNlbGYsIGZhY2U6IHN0cikg"
    "LT4gTm9uZToKICAgICAgICBmYWNlID0gZmFjZS5sb3dlcigpLnN0cmlwKCkKICAgICAgICBpZiBm"
    "YWNlIG5vdCBpbiBzZWxmLl9jYWNoZToKICAgICAgICAgICAgaWYgZmFjZSBub3QgaW4gc2VsZi5f"
    "d2FybmVkIGFuZCBmYWNlICE9ICJuZXV0cmFsIjoKICAgICAgICAgICAgICAgIHByaW50KGYiW01J"
    "UlJPUl1bV0FSTl0gRmFjZSBub3QgaW4gY2FjaGU6IHtmYWNlfSDigJQgdXNpbmcgbmV1dHJhbCIp"
    "CiAgICAgICAgICAgICAgICBzZWxmLl93YXJuZWQuYWRkKGZhY2UpCiAgICAgICAgICAgIGZhY2Ug"
    "PSAibmV1dHJhbCIKICAgICAgICBpZiBmYWNlIG5vdCBpbiBzZWxmLl9jYWNoZToKICAgICAgICAg"
    "ICAgc2VsZi5fZHJhd19wbGFjZWhvbGRlcigpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNl"
    "bGYuX2N1cnJlbnQgPSBmYWNlCiAgICAgICAgcHggPSBzZWxmLl9jYWNoZVtmYWNlXQogICAgICAg"
    "IHNjYWxlZCA9IHB4LnNjYWxlZCgKICAgICAgICAgICAgc2VsZi53aWR0aCgpIC0gNCwKICAgICAg"
    "ICAgICAgc2VsZi5oZWlnaHQoKSAtIDQsCiAgICAgICAgICAgIFF0LkFzcGVjdFJhdGlvTW9kZS5L"
    "ZWVwQXNwZWN0UmF0aW8sCiAgICAgICAgICAgIFF0LlRyYW5zZm9ybWF0aW9uTW9kZS5TbW9vdGhU"
    "cmFuc2Zvcm1hdGlvbiwKICAgICAgICApCiAgICAgICAgc2VsZi5zZXRQaXhtYXAoc2NhbGVkKQog"
    "ICAgICAgIHNlbGYuc2V0VGV4dCgiIikKCiAgICBkZWYgX2RyYXdfcGxhY2Vob2xkZXIoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLmNsZWFyKCkKICAgICAgICBzZWxmLnNldFRleHQoIuKcplxu"
    "4p2nXG7inKYiKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNr"
    "Z3JvdW5kOiB7Q19CRzJ9OyBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAg"
    "ICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyBmb250LXNpemU6IDI0cHg7IGJvcmRl"
    "ci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQoKICAgIGRlZiBzZXRfZmFjZShzZWxmLCBmYWNlOiBz"
    "dHIpIC0+IE5vbmU6CiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMCwgbGFtYmRhOiBzZWxmLl9y"
    "ZW5kZXIoZmFjZSkpCgogICAgZGVmIHJlc2l6ZUV2ZW50KHNlbGYsIGV2ZW50KSAtPiBOb25lOgog"
    "ICAgICAgIHN1cGVyKCkucmVzaXplRXZlbnQoZXZlbnQpCiAgICAgICAgaWYgc2VsZi5fY2FjaGU6"
    "CiAgICAgICAgICAgIHNlbGYuX3JlbmRlcihzZWxmLl9jdXJyZW50KQoKICAgIEBwcm9wZXJ0eQog"
    "ICAgZGVmIGN1cnJlbnRfZmFjZShzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0dXJuIHNlbGYuX2N1"
    "cnJlbnQKCgojIOKUgOKUgCBWQU1QSVJFIFNUQVRFIFNUUklQIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBWYW1waXJlU3RhdGVTdHJpcChR"
    "V2lkZ2V0KToKICAgICIiIgogICAgRnVsbC13aWR0aCBzdGF0dXMgYmFyIHNob3dpbmc6CiAgICAg"
    "IFsg4pymIFZBTVBJUkVfU1RBVEUgIOKAoiAgSEg6TU0gIOKAoiAg4piAIFNVTlJJU0UgIOKYvSBT"
    "VU5TRVQgIOKAoiAgTU9PTiBQSEFTRSAgSUxMVU0lIF0KICAgIEFsd2F5cyB2aXNpYmxlLCBuZXZl"
    "ciBjb2xsYXBzZXMuCiAgICBVcGRhdGVzIGV2ZXJ5IG1pbnV0ZSB2aWEgZXh0ZXJuYWwgUVRpbWVy"
    "IGNhbGwgdG8gcmVmcmVzaCgpLgogICAgQ29sb3ItY29kZWQgYnkgY3VycmVudCB2YW1waXJlIHN0"
    "YXRlLgogICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAg"
    "ICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9zdGF0ZSAgICAgPSBnZXRf"
    "dmFtcGlyZV9zdGF0ZSgpCiAgICAgICAgc2VsZi5fdGltZV9zdHIgID0gIiIKICAgICAgICBzZWxm"
    "Ll9zdW5yaXNlICAgPSAiMDY6MDAiCiAgICAgICAgc2VsZi5fc3Vuc2V0ICAgID0gIjE4OjMwIgog"
    "ICAgICAgIHNlbGYuX21vb25fbmFtZSA9ICJORVcgTU9PTiIKICAgICAgICBzZWxmLl9pbGx1bSAg"
    "ICAgPSAwLjAKICAgICAgICBzZWxmLnNldEZpeGVkSGVpZ2h0KDI4KQogICAgICAgIHNlbGYuc2V0"
    "U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlci10b3A6IDFweCBzb2xpZCB7"
    "Q19DUklNU09OX0RJTX07IikKICAgICAgICBzZWxmLl9mZXRjaF9zdW5fYXN5bmMoKQogICAgICAg"
    "IHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9mZXRjaF9zdW5fYXN5bmMoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBkZWYgX2YoKToKICAgICAgICAgICAgc3IsIHNzID0gZ2V0X3N1bl90aW1lcygpCiAg"
    "ICAgICAgICAgIHNlbGYuX3N1bnJpc2UgPSBzcgogICAgICAgICAgICBzZWxmLl9zdW5zZXQgID0g"
    "c3MKICAgICAgICAgICAgIyBTY2hlZHVsZSByZXBhaW50IG9uIG1haW4gdGhyZWFkIOKAlCBuZXZl"
    "ciBjYWxsIHVwZGF0ZSgpIGZyb20KICAgICAgICAgICAgIyBhIGJhY2tncm91bmQgdGhyZWFkLCBp"
    "dCBjYXVzZXMgUVRocmVhZCBjcmFzaCBvbiBzdGFydHVwCiAgICAgICAgICAgIFFUaW1lci5zaW5n"
    "bGVTaG90KDAsIHNlbGYudXBkYXRlKQogICAgICAgIHRocmVhZGluZy5UaHJlYWQodGFyZ2V0PV9m"
    "LCBkYWVtb249VHJ1ZSkuc3RhcnQoKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fc3RhdGUgICAgID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgICAgIHNlbGYu"
    "X3RpbWVfc3RyICA9IGRhdGV0aW1lLm5vdygpLnN0cmZ0aW1lKCIlSDolTSIpCiAgICAgICAgXywg"
    "c2VsZi5fbW9vbl9uYW1lLCBzZWxmLl9pbGx1bSA9IGdldF9tb29uX3BoYXNlKCkKICAgICAgICBz"
    "ZWxmLnVwZGF0ZSgpCgogICAgZGVmIHBhaW50RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAg"
    "ICAgICAgcCA9IFFQYWludGVyKHNlbGYpCiAgICAgICAgcC5zZXRSZW5kZXJIaW50KFFQYWludGVy"
    "LlJlbmRlckhpbnQuQW50aWFsaWFzaW5nKQogICAgICAgIHcsIGggPSBzZWxmLndpZHRoKCksIHNl"
    "bGYuaGVpZ2h0KCkKCiAgICAgICAgcC5maWxsUmVjdCgwLCAwLCB3LCBoLCBRQ29sb3IoQ19CRzIp"
    "KQoKICAgICAgICBzdGF0ZV9jb2xvciA9IGdldF92YW1waXJlX3N0YXRlX2NvbG9yKHNlbGYuX3N0"
    "YXRlKQogICAgICAgIHRleHQgPSAoCiAgICAgICAgICAgIGYi4pymICB7c2VsZi5fc3RhdGV9ICDi"
    "gKIgIHtzZWxmLl90aW1lX3N0cn0gIOKAoiAgIgogICAgICAgICAgICBmIuKYgCB7c2VsZi5fc3Vu"
    "cmlzZX0gICAg4pi9IHtzZWxmLl9zdW5zZXR9ICDigKIgICIKICAgICAgICAgICAgZiJ7c2VsZi5f"
    "bW9vbl9uYW1lfSAge3NlbGYuX2lsbHVtOi4wZn0lIgogICAgICAgICkKCiAgICAgICAgcC5zZXRG"
    "b250KFFGb250KERFQ0tfRk9OVCwgOSwgUUZvbnQuV2VpZ2h0LkJvbGQpKQogICAgICAgIHAuc2V0"
    "UGVuKFFDb2xvcihzdGF0ZV9jb2xvcikpCiAgICAgICAgZm0gPSBwLmZvbnRNZXRyaWNzKCkKICAg"
    "ICAgICB0dyA9IGZtLmhvcml6b250YWxBZHZhbmNlKHRleHQpCiAgICAgICAgcC5kcmF3VGV4dCgo"
    "dyAtIHR3KSAvLyAyLCBoIC0gNywgdGV4dCkKCiAgICAgICAgcC5lbmQoKQoKCmNsYXNzIE1pbmlD"
    "YWxlbmRhcldpZGdldChRV2lkZ2V0KToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9u"
    "ZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgbGF5b3V0ID0gUVZC"
    "b3hMYXlvdXQoc2VsZikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAs"
    "IDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgaGVhZGVyID0gUUhCb3hM"
    "YXlvdXQoKQogICAgICAgIGhlYWRlci5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAg"
    "ICAgICBzZWxmLnByZXZfYnRuID0gUVB1c2hCdXR0b24oIjw8IikKICAgICAgICBzZWxmLm5leHRf"
    "YnRuID0gUVB1c2hCdXR0b24oIj4+IikKICAgICAgICBzZWxmLm1vbnRoX2xibCA9IFFMYWJlbCgi"
    "IikKICAgICAgICBzZWxmLm1vbnRoX2xibC5zZXRBbGlnbm1lbnQoUXQuQWxpZ25tZW50RmxhZy5B"
    "bGlnbkNlbnRlcikKICAgICAgICBmb3IgYnRuIGluIChzZWxmLnByZXZfYnRuLCBzZWxmLm5leHRf"
    "YnRuKToKICAgICAgICAgICAgYnRuLnNldEZpeGVkV2lkdGgoMzQpCiAgICAgICAgICAgIGJ0bi5z"
    "ZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xv"
    "cjoge0NfR09MRH07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAg"
    "ICAgICAgICAgZiJmb250LXNpemU6IDEwcHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAy"
    "cHg7IgogICAgICAgICAgICApCiAgICAgICAgc2VsZi5tb250aF9sYmwuc2V0U3R5bGVTaGVldCgK"
    "ICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAx"
    "MHB4OyBmb250LXdlaWdodDogYm9sZDsiCiAgICAgICAgKQogICAgICAgIGhlYWRlci5hZGRXaWRn"
    "ZXQoc2VsZi5wcmV2X2J0bikKICAgICAgICBoZWFkZXIuYWRkV2lkZ2V0KHNlbGYubW9udGhfbGJs"
    "LCAxKQogICAgICAgIGhlYWRlci5hZGRXaWRnZXQoc2VsZi5uZXh0X2J0bikKICAgICAgICBsYXlv"
    "dXQuYWRkTGF5b3V0KGhlYWRlcikKCiAgICAgICAgc2VsZi5jYWxlbmRhciA9IFFDYWxlbmRhcldp"
    "ZGdldCgpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRHcmlkVmlzaWJsZShUcnVlKQogICAgICAg"
    "IHNlbGYuY2FsZW5kYXIuc2V0VmVydGljYWxIZWFkZXJGb3JtYXQoUUNhbGVuZGFyV2lkZ2V0LlZl"
    "cnRpY2FsSGVhZGVyRm9ybWF0Lk5vVmVydGljYWxIZWFkZXIpCiAgICAgICAgc2VsZi5jYWxlbmRh"
    "ci5zZXROYXZpZ2F0aW9uQmFyVmlzaWJsZShGYWxzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFXaWRnZXR7e2FsdGVy"
    "bmF0ZS1iYWNrZ3JvdW5kLWNvbG9yOntDX0JHMn07fX0gIgogICAgICAgICAgICBmIlFUb29sQnV0"
    "dG9ue3tjb2xvcjp7Q19HT0xEfTt9fSAiCiAgICAgICAgICAgIGYiUUNhbGVuZGFyV2lkZ2V0IFFB"
    "YnN0cmFjdEl0ZW1WaWV3OmVuYWJsZWR7e2JhY2tncm91bmQ6e0NfQkcyfTsgY29sb3I6I2ZmZmZm"
    "ZjsgIgogICAgICAgICAgICBmInNlbGVjdGlvbi1iYWNrZ3JvdW5kLWNvbG9yOntDX0NSSU1TT05f"
    "RElNfTsgc2VsZWN0aW9uLWNvbG9yOntDX1RFWFR9OyBncmlkbGluZS1jb2xvcjp7Q19CT1JERVJ9"
    "O319ICIKICAgICAgICAgICAgZiJRQ2FsZW5kYXJXaWRnZXQgUUFic3RyYWN0SXRlbVZpZXc6ZGlz"
    "YWJsZWR7e2NvbG9yOiM4Yjk1YTE7fX0iCiAgICAgICAgKQogICAgICAgIGxheW91dC5hZGRXaWRn"
    "ZXQoc2VsZi5jYWxlbmRhcikKCiAgICAgICAgc2VsZi5wcmV2X2J0bi5jbGlja2VkLmNvbm5lY3Qo"
    "bGFtYmRhOiBzZWxmLmNhbGVuZGFyLnNob3dQcmV2aW91c01vbnRoKCkpCiAgICAgICAgc2VsZi5u"
    "ZXh0X2J0bi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLmNhbGVuZGFyLnNob3dOZXh0TW9u"
    "dGgoKSkKICAgICAgICBzZWxmLmNhbGVuZGFyLmN1cnJlbnRQYWdlQ2hhbmdlZC5jb25uZWN0KHNl"
    "bGYuX3VwZGF0ZV9sYWJlbCkKICAgICAgICBzZWxmLl91cGRhdGVfbGFiZWwoKQogICAgICAgIHNl"
    "bGYuX2FwcGx5X2Zvcm1hdHMoKQoKICAgIGRlZiBfdXBkYXRlX2xhYmVsKHNlbGYsICphcmdzKToK"
    "ICAgICAgICB5ZWFyID0gc2VsZi5jYWxlbmRhci55ZWFyU2hvd24oKQogICAgICAgIG1vbnRoID0g"
    "c2VsZi5jYWxlbmRhci5tb250aFNob3duKCkKICAgICAgICBzZWxmLm1vbnRoX2xibC5zZXRUZXh0"
    "KGYie2RhdGUoeWVhciwgbW9udGgsIDEpLnN0cmZ0aW1lKCclQiAlWScpfSIpCiAgICAgICAgc2Vs"
    "Zi5fYXBwbHlfZm9ybWF0cygpCgogICAgZGVmIF9hcHBseV9mb3JtYXRzKHNlbGYpOgogICAgICAg"
    "IGJhc2UgPSBRVGV4dENoYXJGb3JtYXQoKQogICAgICAgIGJhc2Uuc2V0Rm9yZWdyb3VuZChRQ29s"
    "b3IoIiNlN2VkZjMiKSkKICAgICAgICBzYXR1cmRheSA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAg"
    "ICAgc2F0dXJkYXkuc2V0Rm9yZWdyb3VuZChRQ29sb3IoQ19HT0xEX0RJTSkpCiAgICAgICAgc3Vu"
    "ZGF5ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAgICBzdW5kYXkuc2V0Rm9yZWdyb3VuZChRQ29s"
    "b3IoQ19CTE9PRCkpCiAgICAgICAgc2VsZi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChR"
    "dC5EYXlPZldlZWsuTW9uZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2Rh"
    "eVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlR1ZXNkYXksIGJhc2UpCiAgICAgICAgc2VsZi5jYWxl"
    "bmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuV2VkbmVzZGF5LCBiYXNlKQog"
    "ICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQoUXQuRGF5T2ZXZWVrLlRo"
    "dXJzZGF5LCBiYXNlKQogICAgICAgIHNlbGYuY2FsZW5kYXIuc2V0V2Vla2RheVRleHRGb3JtYXQo"
    "UXQuRGF5T2ZXZWVrLkZyaWRheSwgYmFzZSkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNldFdlZWtk"
    "YXlUZXh0Rm9ybWF0KFF0LkRheU9mV2Vlay5TYXR1cmRheSwgc2F0dXJkYXkpCiAgICAgICAgc2Vs"
    "Zi5jYWxlbmRhci5zZXRXZWVrZGF5VGV4dEZvcm1hdChRdC5EYXlPZldlZWsuU3VuZGF5LCBzdW5k"
    "YXkpCgogICAgICAgIHllYXIgPSBzZWxmLmNhbGVuZGFyLnllYXJTaG93bigpCiAgICAgICAgbW9u"
    "dGggPSBzZWxmLmNhbGVuZGFyLm1vbnRoU2hvd24oKQogICAgICAgIGZpcnN0X2RheSA9IFFEYXRl"
    "KHllYXIsIG1vbnRoLCAxKQogICAgICAgIGZvciBkYXkgaW4gcmFuZ2UoMSwgZmlyc3RfZGF5LmRh"
    "eXNJbk1vbnRoKCkgKyAxKToKICAgICAgICAgICAgZCA9IFFEYXRlKHllYXIsIG1vbnRoLCBkYXkp"
    "CiAgICAgICAgICAgIGZtdCA9IFFUZXh0Q2hhckZvcm1hdCgpCiAgICAgICAgICAgIHdlZWtkYXkg"
    "PSBkLmRheU9mV2VlaygpCiAgICAgICAgICAgIGlmIHdlZWtkYXkgPT0gUXQuRGF5T2ZXZWVrLlNh"
    "dHVyZGF5LnZhbHVlOgogICAgICAgICAgICAgICAgZm10LnNldEZvcmVncm91bmQoUUNvbG9yKENf"
    "R09MRF9ESU0pKQogICAgICAgICAgICBlbGlmIHdlZWtkYXkgPT0gUXQuRGF5T2ZXZWVrLlN1bmRh"
    "eS52YWx1ZToKICAgICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFDb2xvcihDX0JMT09E"
    "KSkKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIGZtdC5zZXRGb3JlZ3JvdW5kKFFD"
    "b2xvcigiI2U3ZWRmMyIpKQogICAgICAgICAgICBzZWxmLmNhbGVuZGFyLnNldERhdGVUZXh0Rm9y"
    "bWF0KGQsIGZtdCkKCiAgICAgICAgdG9kYXlfZm10ID0gUVRleHRDaGFyRm9ybWF0KCkKICAgICAg"
    "ICB0b2RheV9mbXQuc2V0Rm9yZWdyb3VuZChRQ29sb3IoIiM2OGQzOWEiKSkKICAgICAgICB0b2Rh"
    "eV9mbXQuc2V0QmFja2dyb3VuZChRQ29sb3IoIiMxNjM4MjUiKSkKICAgICAgICB0b2RheV9mbXQu"
    "c2V0Rm9udFdlaWdodChRRm9udC5XZWlnaHQuQm9sZCkKICAgICAgICBzZWxmLmNhbGVuZGFyLnNl"
    "dERhdGVUZXh0Rm9ybWF0KFFEYXRlLmN1cnJlbnREYXRlKCksIHRvZGF5X2ZtdCkKCgojIOKUgOKU"
    "gCBDT0xMQVBTSUJMRSBCTE9DSyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIAKY2xhc3MgQ29sbGFwc2libGVCbG9jayhRV2lkZ2V0KToKICAg"
    "ICIiIgogICAgV3JhcHBlciB0aGF0IGFkZHMgYSBjb2xsYXBzZS9leHBhbmQgdG9nZ2xlIHRvIGFu"
    "eSB3aWRnZXQuCiAgICBDb2xsYXBzZXMgaG9yaXpvbnRhbGx5IChyaWdodHdhcmQpIOKAlCBoaWRl"
    "cyBjb250ZW50LCBrZWVwcyBoZWFkZXIgc3RyaXAuCiAgICBIZWFkZXIgc2hvd3MgbGFiZWwuIFRv"
    "Z2dsZSBidXR0b24gb24gcmlnaHQgZWRnZSBvZiBoZWFkZXIuCgogICAgVXNhZ2U6CiAgICAgICAg"
    "YmxvY2sgPSBDb2xsYXBzaWJsZUJsb2NrKCLinacgQkxPT0QiLCBTcGhlcmVXaWRnZXQoLi4uKSkK"
    "ICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGJsb2NrKQogICAgIiIiCgogICAgZGVmIF9faW5pdF9f"
    "KHNlbGYsIGxhYmVsOiBzdHIsIGNvbnRlbnQ6IFFXaWRnZXQsCiAgICAgICAgICAgICAgICAgZXhw"
    "YW5kZWQ6IGJvb2wgPSBUcnVlLCBtaW5fd2lkdGg6IGludCA9IDkwLAogICAgICAgICAgICAgICAg"
    "IHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBz"
    "ZWxmLl9leHBhbmRlZCAgPSBleHBhbmRlZAogICAgICAgIHNlbGYuX21pbl93aWR0aCA9IG1pbl93"
    "aWR0aAogICAgICAgIHNlbGYuX2NvbnRlbnQgICA9IGNvbnRlbnQKCiAgICAgICAgbWFpbiA9IFFW"
    "Qm94TGF5b3V0KHNlbGYpCiAgICAgICAgbWFpbi5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwg"
    "MCkKICAgICAgICBtYWluLnNldFNwYWNpbmcoMCkKCiAgICAgICAgIyBIZWFkZXIKICAgICAgICBz"
    "ZWxmLl9oZWFkZXIgPSBRV2lkZ2V0KCkKICAgICAgICBzZWxmLl9oZWFkZXIuc2V0Rml4ZWRIZWln"
    "aHQoMjIpCiAgICAgICAgc2VsZi5faGVhZGVyLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "YmFja2dyb3VuZDoge0NfQkczfTsgYm9yZGVyLWJvdHRvbTogMXB4IHNvbGlkIHtDX0NSSU1TT05f"
    "RElNfTsgIgogICAgICAgICAgICBmImJvcmRlci10b3A6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJ"
    "TX07IgogICAgICAgICkKICAgICAgICBobCA9IFFIQm94TGF5b3V0KHNlbGYuX2hlYWRlcikKICAg"
    "ICAgICBobC5zZXRDb250ZW50c01hcmdpbnMoNiwgMCwgNCwgMCkKICAgICAgICBobC5zZXRTcGFj"
    "aW5nKDQpCgogICAgICAgIHNlbGYuX2xibCA9IFFMYWJlbChsYWJlbCkKICAgICAgICBzZWxmLl9s"
    "Ymwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07IGZvbnQtc2l6"
    "ZTogOXB4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7"
    "REVDS19GT05UfSwgc2VyaWY7IGxldHRlci1zcGFjaW5nOiAxcHg7IGJvcmRlcjogbm9uZTsiCiAg"
    "ICAgICAgKQoKICAgICAgICBzZWxmLl9idG4gPSBRVG9vbEJ1dHRvbigpCiAgICAgICAgc2VsZi5f"
    "YnRuLnNldEZpeGVkU2l6ZSgxNiwgMTYpCiAgICAgICAgc2VsZi5fYnRuLnNldFN0eWxlU2hlZXQo"
    "CiAgICAgICAgICAgIGYiYmFja2dyb3VuZDogdHJhbnNwYXJlbnQ7IGNvbG9yOiB7Q19HT0xEX0RJ"
    "TX07IGJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgc2Vs"
    "Zi5fYnRuLnNldFRleHQoIjwiKQogICAgICAgIHNlbGYuX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fdG9nZ2xlKQoKICAgICAgICBobC5hZGRXaWRnZXQoc2VsZi5fbGJsKQogICAgICAgIGhsLmFk"
    "ZFN0cmV0Y2goKQogICAgICAgIGhsLmFkZFdpZGdldChzZWxmLl9idG4pCgogICAgICAgIG1haW4u"
    "YWRkV2lkZ2V0KHNlbGYuX2hlYWRlcikKICAgICAgICBtYWluLmFkZFdpZGdldChzZWxmLl9jb250"
    "ZW50KQoKICAgICAgICBzZWxmLl9hcHBseV9zdGF0ZSgpCgogICAgZGVmIF90b2dnbGUoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9leHBhbmRlZCA9IG5vdCBzZWxmLl9leHBhbmRlZAogICAg"
    "ICAgIHNlbGYuX2FwcGx5X3N0YXRlKCkKCiAgICBkZWYgX2FwcGx5X3N0YXRlKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5fY29udGVudC5zZXRWaXNpYmxlKHNlbGYuX2V4cGFuZGVkKQogICAg"
    "ICAgIHNlbGYuX2J0bi5zZXRUZXh0KCI8IiBpZiBzZWxmLl9leHBhbmRlZCBlbHNlICI+IikKICAg"
    "ICAgICBpZiBzZWxmLl9leHBhbmRlZDoKICAgICAgICAgICAgc2VsZi5zZXRNaW5pbXVtV2lkdGgo"
    "c2VsZi5fbWluX3dpZHRoKQogICAgICAgICAgICBzZWxmLnNldE1heGltdW1XaWR0aCgxNjc3NzIx"
    "NSkgICMgdW5jb25zdHJhaW5lZAogICAgICAgIGVsc2U6CiAgICAgICAgICAgICMgQ29sbGFwc2Vk"
    "OiBqdXN0IHRoZSBoZWFkZXIgc3RyaXAgKGxhYmVsICsgYnV0dG9uKQogICAgICAgICAgICBjb2xs"
    "YXBzZWRfdyA9IHNlbGYuX2hlYWRlci5zaXplSGludCgpLndpZHRoKCkKICAgICAgICAgICAgc2Vs"
    "Zi5zZXRGaXhlZFdpZHRoKG1heCg2MCwgY29sbGFwc2VkX3cpKQogICAgICAgIHNlbGYudXBkYXRl"
    "R2VvbWV0cnkoKQogICAgICAgIHBhcmVudCA9IHNlbGYucGFyZW50V2lkZ2V0KCkKICAgICAgICBp"
    "ZiBwYXJlbnQgYW5kIHBhcmVudC5sYXlvdXQoKToKICAgICAgICAgICAgcGFyZW50LmxheW91dCgp"
    "LmFjdGl2YXRlKCkKCgojIOKUgOKUgCBIQVJEV0FSRSBQQU5FTCDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgSGFy"
    "ZHdhcmVQYW5lbChRV2lkZ2V0KToKICAgICIiIgogICAgVGhlIFNwZWxsIEJvb2sgcmlnaHQgcGFu"
    "ZWwgY29udGVudHMuCiAgICBHcm91cHM6IHN0YXR1cyBpbmZvLCBkcml2ZSBiYXJzLCBDUFUvUkFN"
    "IGdhdWdlcywgR1BVL1ZSQU0gZ2F1Z2VzLCBHUFUgdGVtcC4KICAgIFJlcG9ydHMgaGFyZHdhcmUg"
    "YXZhaWxhYmlsaXR5IGluIERpYWdub3N0aWNzIG9uIHN0YXJ0dXAuCiAgICBTaG93cyBOL0EgZ3Jh"
    "Y2VmdWxseSB3aGVuIGRhdGEgdW5hdmFpbGFibGUuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18o"
    "c2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAg"
    "ICAgIHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLl9kZXRlY3RfaGFyZHdhcmUoKQoKICAg"
    "IGRlZiBfc2V0dXBfdWkoc2VsZikgLT4gTm9uZToKICAgICAgICBsYXlvdXQgPSBRVkJveExheW91"
    "dChzZWxmKQogICAgICAgIGxheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAg"
    "ICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICBkZWYgc2VjdGlvbl9sYWJlbCh0ZXh0"
    "OiBzdHIpIC0+IFFMYWJlbDoKICAgICAgICAgICAgbGJsID0gUUxhYmVsKHRleHQpCiAgICAgICAg"
    "ICAgIGxibC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRH07"
    "IGZvbnQtc2l6ZTogOXB4OyBsZXR0ZXItc3BhY2luZzogMnB4OyAiCiAgICAgICAgICAgICAgICBm"
    "ImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtd2VpZ2h0OiBib2xkOyIKICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4gbGJsCgogICAgICAgICMg4pSA4pSAIFN0YXR1"
    "cyBibG9jayDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0"
    "KHNlY3Rpb25fbGFiZWwoIuKdpyBTVEFUVVMiKSkKICAgICAgICBzdGF0dXNfZnJhbWUgPSBRRnJh"
    "bWUoKQogICAgICAgIHN0YXR1c19mcmFtZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJh"
    "Y2tncm91bmQ6IHtDX1BBTkVMfTsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVy"
    "LXJhZGl1czogMnB4OyIKICAgICAgICApCiAgICAgICAgc3RhdHVzX2ZyYW1lLnNldEZpeGVkSGVp"
    "Z2h0KDg4KQogICAgICAgIHNmID0gUVZCb3hMYXlvdXQoc3RhdHVzX2ZyYW1lKQogICAgICAgIHNm"
    "LnNldENvbnRlbnRzTWFyZ2lucyg4LCA0LCA4LCA0KQogICAgICAgIHNmLnNldFNwYWNpbmcoMikK"
    "CiAgICAgICAgc2VsZi5sYmxfc3RhdHVzICA9IFFMYWJlbCgi4pymIFNUQVRVUzogT0ZGTElORSIp"
    "CiAgICAgICAgc2VsZi5sYmxfbW9kZWwgICA9IFFMYWJlbCgi4pymIFZFU1NFTDogTE9BRElORy4u"
    "LiIpCiAgICAgICAgc2VsZi5sYmxfc2Vzc2lvbiA9IFFMYWJlbCgi4pymIFNFU1NJT046IDAwOjAw"
    "OjAwIikKICAgICAgICBzZWxmLmxibF90b2tlbnMgID0gUUxhYmVsKCLinKYgVE9LRU5TOiAwIikK"
    "CiAgICAgICAgZm9yIGxibCBpbiAoc2VsZi5sYmxfc3RhdHVzLCBzZWxmLmxibF9tb2RlbCwKICAg"
    "ICAgICAgICAgICAgICAgICBzZWxmLmxibF9zZXNzaW9uLCBzZWxmLmxibF90b2tlbnMpOgogICAg"
    "ICAgICAgICBsYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiY29sb3I6IHtDX1RF"
    "WFRfRElNfTsgZm9udC1zaXplOiAxMHB4OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5"
    "OiB7REVDS19GT05UfSwgc2VyaWY7IGJvcmRlcjogbm9uZTsiCiAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgc2YuYWRkV2lkZ2V0KGxibCkKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzdGF0dXNf"
    "ZnJhbWUpCgogICAgICAgICMg4pSA4pSAIERyaXZlIGJhcnMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0aW9uX2xhYmVsKCLinacgU1RP"
    "UkFHRSIpKQogICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0ID0gRHJpdmVXaWRnZXQoKQogICAgICAg"
    "IGxheW91dC5hZGRXaWRnZXQoc2VsZi5kcml2ZV93aWRnZXQpCgogICAgICAgICMg4pSA4pSAIENQ"
    "VSAvIFJBTSBnYXVnZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWN0"
    "aW9uX2xhYmVsKCLinacgVklUQUwgRVNTRU5DRSIpKQogICAgICAgIHJhbV9jcHUgPSBRR3JpZExh"
    "eW91dCgpCiAgICAgICAgcmFtX2NwdS5zZXRTcGFjaW5nKDMpCgogICAgICAgIHNlbGYuZ2F1Z2Vf"
    "Y3B1ICA9IEdhdWdlV2lkZ2V0KCJDUFUiLCAgIiUiLCAgIDEwMC4wLCBDX1NJTFZFUikKICAgICAg"
    "ICBzZWxmLmdhdWdlX3JhbSAgPSBHYXVnZVdpZGdldCgiUkFNIiwgICJHQiIsICAgNjQuMCwgQ19H"
    "T0xEX0RJTSkKICAgICAgICByYW1fY3B1LmFkZFdpZGdldChzZWxmLmdhdWdlX2NwdSwgMCwgMCkK"
    "ICAgICAgICByYW1fY3B1LmFkZFdpZGdldChzZWxmLmdhdWdlX3JhbSwgMCwgMSkKICAgICAgICBs"
    "YXlvdXQuYWRkTGF5b3V0KHJhbV9jcHUpCgogICAgICAgICMg4pSA4pSAIEdQVSAvIFZSQU0gZ2F1"
    "Z2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2n"
    "IEFSQ0FORSBQT1dFUiIpKQogICAgICAgIGdwdV92cmFtID0gUUdyaWRMYXlvdXQoKQogICAgICAg"
    "IGdwdV92cmFtLnNldFNwYWNpbmcoMykKCiAgICAgICAgc2VsZi5nYXVnZV9ncHUgID0gR2F1Z2VX"
    "aWRnZXQoIkdQVSIsICAiJSIsICAgMTAwLjAsIENfUFVSUExFKQogICAgICAgIHNlbGYuZ2F1Z2Vf"
    "dnJhbSA9IEdhdWdlV2lkZ2V0KCJWUkFNIiwgIkdCIiwgICAgOC4wLCBDX0NSSU1TT04pCiAgICAg"
    "ICAgZ3B1X3ZyYW0uYWRkV2lkZ2V0KHNlbGYuZ2F1Z2VfZ3B1LCAgMCwgMCkKICAgICAgICBncHVf"
    "dnJhbS5hZGRXaWRnZXQoc2VsZi5nYXVnZV92cmFtLCAwLCAxKQogICAgICAgIGxheW91dC5hZGRM"
    "YXlvdXQoZ3B1X3ZyYW0pCgogICAgICAgICMg4pSA4pSAIEdQVSBUZW1wIOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VjdGlvbl9s"
    "YWJlbCgi4p2nIElORkVSTkFMIEhFQVQiKSkKICAgICAgICBzZWxmLmdhdWdlX3RlbXAgPSBHYXVn"
    "ZVdpZGdldCgiR1BVIFRFTVAiLCAiwrBDIiwgOTUuMCwgQ19CTE9PRCkKICAgICAgICBzZWxmLmdh"
    "dWdlX3RlbXAuc2V0TWF4aW11bUhlaWdodCg2NSkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNl"
    "bGYuZ2F1Z2VfdGVtcCkKCiAgICAgICAgIyDilIDilIAgR1BVIG1hc3RlciBiYXIgKGZ1bGwgd2lk"
    "dGgpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGxheW91dC5h"
    "ZGRXaWRnZXQoc2VjdGlvbl9sYWJlbCgi4p2nIElORkVSTkFMIEVOR0lORSIpKQogICAgICAgIHNl"
    "bGYuZ2F1Z2VfZ3B1X21hc3RlciA9IEdhdWdlV2lkZ2V0KCJSVFgiLCAiJSIsIDEwMC4wLCBDX0NS"
    "SU1TT04pCiAgICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldE1heGltdW1IZWlnaHQoNTUp"
    "CiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLmdhdWdlX2dwdV9tYXN0ZXIpCgogICAgICAg"
    "IGxheW91dC5hZGRTdHJldGNoKCkKCiAgICBkZWYgX2RldGVjdF9oYXJkd2FyZShzZWxmKSAtPiBO"
    "b25lOgogICAgICAgICIiIgogICAgICAgIENoZWNrIHdoYXQgaGFyZHdhcmUgbW9uaXRvcmluZyBp"
    "cyBhdmFpbGFibGUuCiAgICAgICAgTWFyayB1bmF2YWlsYWJsZSBnYXVnZXMgYXBwcm9wcmlhdGVs"
    "eS4KICAgICAgICBEaWFnbm9zdGljIG1lc3NhZ2VzIGNvbGxlY3RlZCBmb3IgdGhlIERpYWdub3N0"
    "aWNzIHRhYi4KICAgICAgICAiIiIKICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzOiBsaXN0W3N0"
    "cl0gPSBbXQoKICAgICAgICBpZiBub3QgUFNVVElMX09LOgogICAgICAgICAgICBzZWxmLmdhdWdl"
    "X2NwdS5zZXRVbmF2YWlsYWJsZSgpCiAgICAgICAgICAgIHNlbGYuZ2F1Z2VfcmFtLnNldFVuYXZh"
    "aWxhYmxlKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ19tZXNzYWdlcy5hcHBlbmQoCiAgICAgICAg"
    "ICAgICAgICAiW0hBUkRXQVJFXSBwc3V0aWwgbm90IGF2YWlsYWJsZSDigJQgQ1BVL1JBTSBnYXVn"
    "ZXMgZGlzYWJsZWQuICIKICAgICAgICAgICAgICAgICJwaXAgaW5zdGFsbCBwc3V0aWwgdG8gZW5h"
    "YmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2RpYWdf"
    "bWVzc2FnZXMuYXBwZW5kKCJbSEFSRFdBUkVdIHBzdXRpbCBPSyDigJQgQ1BVL1JBTSBtb25pdG9y"
    "aW5nIGFjdGl2ZS4iKQoKICAgICAgICBpZiBub3QgTlZNTF9PSzoKICAgICAgICAgICAgc2VsZi5n"
    "YXVnZV9ncHUuc2V0VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0"
    "VW5hdmFpbGFibGUoKQogICAgICAgICAgICBzZWxmLmdhdWdlX3RlbXAuc2V0VW5hdmFpbGFibGUo"
    "KQogICAgICAgICAgICBzZWxmLmdhdWdlX2dwdV9tYXN0ZXIuc2V0VW5hdmFpbGFibGUoKQogICAg"
    "ICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICJbSEFS"
    "RFdBUkVdIHB5bnZtbCBub3QgYXZhaWxhYmxlIG9yIG5vIE5WSURJQSBHUFUgZGV0ZWN0ZWQg4oCU"
    "ICIKICAgICAgICAgICAgICAgICJHUFUgZ2F1Z2VzIGRpc2FibGVkLiBwaXAgaW5zdGFsbCBweW52"
    "bWwgdG8gZW5hYmxlLiIKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHRy"
    "eToKICAgICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdldE5hbWUoZ3B1X2hh"
    "bmRsZSkKICAgICAgICAgICAgICAgIGlmIGlzaW5zdGFuY2UobmFtZSwgYnl0ZXMpOgogICAgICAg"
    "ICAgICAgICAgICAgIG5hbWUgPSBuYW1lLmRlY29kZSgpCiAgICAgICAgICAgICAgICBzZWxmLl9k"
    "aWFnX21lc3NhZ2VzLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltIQVJEV0FSRV0gcHlu"
    "dm1sIE9LIOKAlCBHUFUgZGV0ZWN0ZWQ6IHtuYW1lfSIKICAgICAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgICAgICMgVXBkYXRlIG1heCBWUkFNIGZyb20gYWN0dWFsIGhhcmR3YXJlCiAgICAgICAg"
    "ICAgICAgICBtZW0gPSBweW52bWwubnZtbERldmljZUdldE1lbW9yeUluZm8oZ3B1X2hhbmRsZSkK"
    "ICAgICAgICAgICAgICAgIHRvdGFsX2diID0gbWVtLnRvdGFsIC8gMTAyNCoqMwogICAgICAgICAg"
    "ICAgICAgc2VsZi5nYXVnZV92cmFtLm1heF92YWwgPSB0b3RhbF9nYgogICAgICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX21lc3NhZ2VzLmFw"
    "cGVuZChmIltIQVJEV0FSRV0gcHludm1sIGVycm9yOiB7ZX0iKQoKICAgIGRlZiB1cGRhdGVfc3Rh"
    "dHMoc2VsZikgLT4gTm9uZToKICAgICAgICAiIiIKICAgICAgICBDYWxsZWQgZXZlcnkgc2Vjb25k"
    "IGZyb20gdGhlIHN0YXRzIFFUaW1lci4KICAgICAgICBSZWFkcyBoYXJkd2FyZSBhbmQgdXBkYXRl"
    "cyBhbGwgZ2F1Z2VzLgogICAgICAgICIiIgogICAgICAgIGlmIFBTVVRJTF9PSzoKICAgICAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICAgICAgY3B1ID0gcHN1dGlsLmNwdV9wZXJjZW50KCkKICAgICAg"
    "ICAgICAgICAgIHNlbGYuZ2F1Z2VfY3B1LnNldFZhbHVlKGNwdSwgZiJ7Y3B1Oi4wZn0lIiwgYXZh"
    "aWxhYmxlPVRydWUpCgogICAgICAgICAgICAgICAgbWVtID0gcHN1dGlsLnZpcnR1YWxfbWVtb3J5"
    "KCkKICAgICAgICAgICAgICAgIHJ1ICA9IG1lbS51c2VkICAvIDEwMjQqKjMKICAgICAgICAgICAg"
    "ICAgIHJ0ICA9IG1lbS50b3RhbCAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHNlbGYuZ2F1Z2Vf"
    "cmFtLnNldFZhbHVlKHJ1LCBmIntydTouMWZ9L3tydDouMGZ9R0IiLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCiAgICAgICAgICAgICAgICBz"
    "ZWxmLmdhdWdlX3JhbS5tYXhfdmFsID0gcnQKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoK"
    "ICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgaWYgTlZNTF9PSyBhbmQgZ3B1X2hhbmRsZToK"
    "ICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgdXRpbCAgICAgPSBweW52bWwubnZtbERl"
    "dmljZUdldFV0aWxpemF0aW9uUmF0ZXMoZ3B1X2hhbmRsZSkKICAgICAgICAgICAgICAgIG1lbV9p"
    "bmZvID0gcHludm1sLm52bWxEZXZpY2VHZXRNZW1vcnlJbmZvKGdwdV9oYW5kbGUpCiAgICAgICAg"
    "ICAgICAgICB0ZW1wICAgICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0VGVtcGVyYXR1cmUoCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICBncHVfaGFuZGxlLCBweW52bWwuTlZNTF9URU1QRVJB"
    "VFVSRV9HUFUpCgogICAgICAgICAgICAgICAgZ3B1X3BjdCAgID0gZmxvYXQodXRpbC5ncHUpCiAg"
    "ICAgICAgICAgICAgICB2cmFtX3VzZWQgPSBtZW1faW5mby51c2VkICAvIDEwMjQqKjMKICAgICAg"
    "ICAgICAgICAgIHZyYW1fdG90ICA9IG1lbV9pbmZvLnRvdGFsIC8gMTAyNCoqMwoKICAgICAgICAg"
    "ICAgICAgIHNlbGYuZ2F1Z2VfZ3B1LnNldFZhbHVlKGdwdV9wY3QsIGYie2dwdV9wY3Q6LjBmfSUi"
    "LAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUp"
    "CiAgICAgICAgICAgICAgICBzZWxmLmdhdWdlX3ZyYW0uc2V0VmFsdWUodnJhbV91c2VkLAogICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYie3ZyYW1fdXNlZDouMWZ9L3t2"
    "cmFtX3RvdDouMGZ9R0IiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IGF2YWlsYWJsZT1UcnVlKQogICAgICAgICAgICAgICAgc2VsZi5nYXVnZV90ZW1wLnNldFZhbHVl"
    "KGZsb2F0KHRlbXApLCBmInt0ZW1wfcKwQyIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgYXZhaWxhYmxlPVRydWUpCgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICAgICAgICAgIG5hbWUgPSBweW52bWwubnZtbERldmljZUdldE5hbWUoZ3B1X2hhbmRsZSkK"
    "ICAgICAgICAgICAgICAgICAgICBpZiBpc2luc3RhbmNlKG5hbWUsIGJ5dGVzKToKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgbmFtZSA9IG5hbWUuZGVjb2RlKCkKICAgICAgICAgICAgICAgIGV4Y2Vw"
    "dCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgbmFtZSA9ICJHUFUiCgogICAgICAgICAg"
    "ICAgICAgc2VsZi5nYXVnZV9ncHVfbWFzdGVyLnNldFZhbHVlKAogICAgICAgICAgICAgICAgICAg"
    "IGdwdV9wY3QsCiAgICAgICAgICAgICAgICAgICAgZiJ7bmFtZX0gIHtncHVfcGN0Oi4wZn0lICAi"
    "CiAgICAgICAgICAgICAgICAgICAgZiJbe3ZyYW1fdXNlZDouMWZ9L3t2cmFtX3RvdDouMGZ9R0Ig"
    "VlJBTV0iLAogICAgICAgICAgICAgICAgICAgIGF2YWlsYWJsZT1UcnVlLAogICAgICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoK"
    "ICAgICAgICAjIFVwZGF0ZSBkcml2ZSBiYXJzIGV2ZXJ5IDMwIHNlY29uZHMgKG5vdCBldmVyeSB0"
    "aWNrKQogICAgICAgIGlmIG5vdCBoYXNhdHRyKHNlbGYsICJfZHJpdmVfdGljayIpOgogICAgICAg"
    "ICAgICBzZWxmLl9kcml2ZV90aWNrID0gMAogICAgICAgIHNlbGYuX2RyaXZlX3RpY2sgKz0gMQog"
    "ICAgICAgIGlmIHNlbGYuX2RyaXZlX3RpY2sgPj0gMzA6CiAgICAgICAgICAgIHNlbGYuX2RyaXZl"
    "X3RpY2sgPSAwCiAgICAgICAgICAgIHNlbGYuZHJpdmVfd2lkZ2V0LnJlZnJlc2goKQoKICAgIGRl"
    "ZiBzZXRfc3RhdHVzX2xhYmVscyhzZWxmLCBzdGF0dXM6IHN0ciwgbW9kZWw6IHN0ciwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBzZXNzaW9uOiBzdHIsIHRva2Vuczogc3RyKSAtPiBOb25lOgog"
    "ICAgICAgIHNlbGYubGJsX3N0YXR1cy5zZXRUZXh0KGYi4pymIFNUQVRVUzoge3N0YXR1c30iKQog"
    "ICAgICAgIHNlbGYubGJsX21vZGVsLnNldFRleHQoZiLinKYgVkVTU0VMOiB7bW9kZWx9IikKICAg"
    "ICAgICBzZWxmLmxibF9zZXNzaW9uLnNldFRleHQoZiLinKYgU0VTU0lPTjoge3Nlc3Npb259IikK"
    "ICAgICAgICBzZWxmLmxibF90b2tlbnMuc2V0VGV4dChmIuKcpiBUT0tFTlM6IHt0b2tlbnN9IikK"
    "CiAgICBkZWYgZ2V0X2RpYWdub3N0aWNzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAgICByZXR1"
    "cm4gZ2V0YXR0cihzZWxmLCAiX2RpYWdfbWVzc2FnZXMiLCBbXSkKCgojIOKUgOKUgCBQQVNTIDIg"
    "Q09NUExFVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiMgQWxsIHdpZGdldCBjbGFzc2VzIGRlZmluZWQuIFN5bnRheC1j"
    "aGVja2FibGUgaW5kZXBlbmRlbnRseS4KIyBOZXh0OiBQYXNzIDMg4oCUIFdvcmtlciBUaHJlYWRz"
    "CiMgKERvbHBoaW5Xb3JrZXIgd2l0aCBzdHJlYW1pbmcsIFNlbnRpbWVudFdvcmtlciwgSWRsZVdv"
    "cmtlciwgU291bmRXb3JrZXIpCgoKIyDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKIyBNT1JHQU5OQSBERUNLIOKAlCBQQVNT"
    "IDM6IFdPUktFUiBUSFJFQURTCiMKIyBXb3JrZXJzIGRlZmluZWQgaGVyZToKIyAgIExMTUFkYXB0"
    "b3IgKGJhc2UgKyBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IgKyBPbGxhbWFBZGFwdG9yICsKIyAg"
    "ICAgICAgICAgICAgIENsYXVkZUFkYXB0b3IgKyBPcGVuQUlBZGFwdG9yKQojICAgU3RyZWFtaW5n"
    "V29ya2VyICAg4oCUIG1haW4gZ2VuZXJhdGlvbiwgZW1pdHMgdG9rZW5zIG9uZSBhdCBhIHRpbWUK"
    "IyAgIFNlbnRpbWVudFdvcmtlciAgIOKAlCBjbGFzc2lmaWVzIGVtb3Rpb24gZnJvbSByZXNwb25z"
    "ZSB0ZXh0CiMgICBJZGxlV29ya2VyICAgICAgICDigJQgdW5zb2xpY2l0ZWQgdHJhbnNtaXNzaW9u"
    "cyBkdXJpbmcgaWRsZQojICAgU291bmRXb3JrZXIgICAgICAg4oCUIHBsYXlzIHNvdW5kcyBvZmYg"
    "dGhlIG1haW4gdGhyZWFkCiMKIyBBTEwgZ2VuZXJhdGlvbiBpcyBzdHJlYW1pbmcuIE5vIGJsb2Nr"
    "aW5nIGNhbGxzIG9uIG1haW4gdGhyZWFkLiBFdmVyLgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0IGFiYwpp"
    "bXBvcnQganNvbgppbXBvcnQgdXJsbGliLnJlcXVlc3QKaW1wb3J0IHVybGxpYi5lcnJvcgppbXBv"
    "cnQgaHR0cC5jbGllbnQKZnJvbSB0eXBpbmcgaW1wb3J0IEl0ZXJhdG9yCgoKIyDilIDilIAgTExN"
    "IEFEQVBUT1IgQkFTRSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKY2xhc3MgTExNQWRhcHRvcihhYmMuQUJDKToKICAgICIiIgogICAgQWJz"
    "dHJhY3QgYmFzZSBmb3IgYWxsIG1vZGVsIGJhY2tlbmRzLgogICAgVGhlIGRlY2sgY2FsbHMgc3Ry"
    "ZWFtKCkgb3IgZ2VuZXJhdGUoKSDigJQgbmV2ZXIga25vd3Mgd2hpY2ggYmFja2VuZCBpcyBhY3Rp"
    "dmUuCiAgICAiIiIKCiAgICBAYWJjLmFic3RyYWN0bWV0aG9kCiAgICBkZWYgaXNfY29ubmVjdGVk"
    "KHNlbGYpIC0+IGJvb2w6CiAgICAgICAgIiIiUmV0dXJuIFRydWUgaWYgdGhlIGJhY2tlbmQgaXMg"
    "cmVhY2hhYmxlLiIiIgogICAgICAgIC4uLgoKICAgIEBhYmMuYWJzdHJhY3RtZXRob2QKICAgIGRl"
    "ZiBzdHJlYW0oCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6IHN0ciwKICAgICAgICBzeXN0"
    "ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAogICAgICAgIG1heF9uZXdfdG9r"
    "ZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IEl0ZXJhdG9yW3N0cl06CiAgICAgICAgIiIiCiAgICAg"
    "ICAgWWllbGQgcmVzcG9uc2UgdGV4dCB0b2tlbi1ieS10b2tlbiAob3IgY2h1bmstYnktY2h1bmsg"
    "Zm9yIEFQSSBiYWNrZW5kcykuCiAgICAgICAgTXVzdCBiZSBhIGdlbmVyYXRvci4gTmV2ZXIgYmxv"
    "Y2sgZm9yIHRoZSBmdWxsIHJlc3BvbnNlIGJlZm9yZSB5aWVsZGluZy4KICAgICAgICAiIiIKICAg"
    "ICAgICAuLi4KCiAgICBkZWYgZ2VuZXJhdGUoCiAgICAgICAgc2VsZiwKICAgICAgICBwcm9tcHQ6"
    "IHN0ciwKICAgICAgICBzeXN0ZW06IHN0ciwKICAgICAgICBoaXN0b3J5OiBsaXN0W2RpY3RdLAog"
    "ICAgICAgIG1heF9uZXdfdG9rZW5zOiBpbnQgPSA1MTIsCiAgICApIC0+IHN0cjoKICAgICAgICAi"
    "IiIKICAgICAgICBDb252ZW5pZW5jZSB3cmFwcGVyOiBjb2xsZWN0IGFsbCBzdHJlYW0gdG9rZW5z"
    "IGludG8gb25lIHN0cmluZy4KICAgICAgICBVc2VkIGZvciBzZW50aW1lbnQgY2xhc3NpZmljYXRp"
    "b24gKHNtYWxsIGJvdW5kZWQgY2FsbHMgb25seSkuCiAgICAgICAgIiIiCiAgICAgICAgcmV0dXJu"
    "ICIiLmpvaW4oc2VsZi5zdHJlYW0ocHJvbXB0LCBzeXN0ZW0sIGhpc3RvcnksIG1heF9uZXdfdG9r"
    "ZW5zKSkKCiAgICBkZWYgYnVpbGRfY2hhdG1sX3Byb21wdChzZWxmLCBzeXN0ZW06IHN0ciwgaGlz"
    "dG9yeTogbGlzdFtkaWN0XSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICB1c2VyX3RleHQ6"
    "IHN0ciA9ICIiKSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgQnVpbGQgYSBDaGF0TUwtZm9y"
    "bWF0IHByb21wdCBzdHJpbmcgZm9yIGxvY2FsIG1vZGVscy4KICAgICAgICBoaXN0b3J5ID0gW3si"
    "cm9sZSI6ICJ1c2VyInwiYXNzaXN0YW50IiwgImNvbnRlbnQiOiAiLi4uIn1dCiAgICAgICAgIiIi"
    "CiAgICAgICAgcGFydHMgPSBbZiI8fGltX3N0YXJ0fD5zeXN0ZW1cbntzeXN0ZW19PHxpbV9lbmR8"
    "PiJdCiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICByb2xlICAgID0gbXNn"
    "LmdldCgicm9sZSIsICJ1c2VyIikKICAgICAgICAgICAgY29udGVudCA9IG1zZy5nZXQoImNvbnRl"
    "bnQiLCAiIikKICAgICAgICAgICAgcGFydHMuYXBwZW5kKGYiPHxpbV9zdGFydHw+e3JvbGV9XG57"
    "Y29udGVudH08fGltX2VuZHw+IikKICAgICAgICBpZiB1c2VyX3RleHQ6CiAgICAgICAgICAgIHBh"
    "cnRzLmFwcGVuZChmIjx8aW1fc3RhcnR8PnVzZXJcbnt1c2VyX3RleHR9PHxpbV9lbmR8PiIpCiAg"
    "ICAgICAgcGFydHMuYXBwZW5kKCI8fGltX3N0YXJ0fD5hc3Npc3RhbnRcbiIpCiAgICAgICAgcmV0"
    "dXJuICJcbiIuam9pbihwYXJ0cykKCgojIOKUgOKUgCBMT0NBTCBUUkFOU0ZPUk1FUlMgQURBUFRP"
    "UiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTG9jYWxUcmFuc2Zvcm1lcnNB"
    "ZGFwdG9yKExMTUFkYXB0b3IpOgogICAgIiIiCiAgICBMb2FkcyBhIEh1Z2dpbmdGYWNlIG1vZGVs"
    "IGZyb20gYSBsb2NhbCBmb2xkZXIuCiAgICBTdHJlYW1pbmc6IHVzZXMgbW9kZWwuZ2VuZXJhdGUo"
    "KSB3aXRoIGEgY3VzdG9tIHN0cmVhbWVyIHRoYXQgeWllbGRzIHRva2Vucy4KICAgIFJlcXVpcmVz"
    "OiB0b3JjaCwgdHJhbnNmb3JtZXJzCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbW9k"
    "ZWxfcGF0aDogc3RyKToKICAgICAgICBzZWxmLl9wYXRoICAgICAgPSBtb2RlbF9wYXRoCiAgICAg"
    "ICAgc2VsZi5fbW9kZWwgICAgID0gTm9uZQogICAgICAgIHNlbGYuX3Rva2VuaXplciA9IE5vbmUK"
    "ICAgICAgICBzZWxmLl9sb2FkZWQgICAgPSBGYWxzZQogICAgICAgIHNlbGYuX2Vycm9yICAgICA9"
    "ICIiCgogICAgZGVmIGxvYWQoc2VsZikgLT4gYm9vbDoKICAgICAgICAiIiIKICAgICAgICBMb2Fk"
    "IG1vZGVsIGFuZCB0b2tlbml6ZXIuIENhbGwgZnJvbSBhIGJhY2tncm91bmQgdGhyZWFkLgogICAg"
    "ICAgIFJldHVybnMgVHJ1ZSBvbiBzdWNjZXNzLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBU"
    "T1JDSF9PSzoKICAgICAgICAgICAgc2VsZi5fZXJyb3IgPSAidG9yY2gvdHJhbnNmb3JtZXJzIG5v"
    "dCBpbnN0YWxsZWQiCiAgICAgICAgICAgIHJldHVybiBGYWxzZQogICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgZnJvbSB0cmFuc2Zvcm1lcnMgaW1wb3J0IEF1dG9Nb2RlbEZvckNhdXNhbExNLCBBdXRv"
    "VG9rZW5pemVyCiAgICAgICAgICAgIHNlbGYuX3Rva2VuaXplciA9IEF1dG9Ub2tlbml6ZXIuZnJv"
    "bV9wcmV0cmFpbmVkKHNlbGYuX3BhdGgpCiAgICAgICAgICAgIHNlbGYuX21vZGVsID0gQXV0b01v"
    "ZGVsRm9yQ2F1c2FsTE0uZnJvbV9wcmV0cmFpbmVkKAogICAgICAgICAgICAgICAgc2VsZi5fcGF0"
    "aCwKICAgICAgICAgICAgICAgIHRvcmNoX2R0eXBlPXRvcmNoLmZsb2F0MTYsCiAgICAgICAgICAg"
    "ICAgICBkZXZpY2VfbWFwPSJhdXRvIiwKICAgICAgICAgICAgICAgIGxvd19jcHVfbWVtX3VzYWdl"
    "PVRydWUsCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fbG9hZGVkID0gVHJ1ZQogICAg"
    "ICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAg"
    "ICAgICAgc2VsZi5fZXJyb3IgPSBzdHIoZSkKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCgogICAg"
    "QHByb3BlcnR5CiAgICBkZWYgZXJyb3Ioc2VsZikgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxm"
    "Ll9lcnJvcgoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1"
    "cm4gc2VsZi5fbG9hZGVkCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBzZWxmLAogICAgICAgIHBy"
    "b21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhpc3Rvcnk6IGxpc3RbZGlj"
    "dF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jb"
    "c3RyXToKICAgICAgICAiIiIKICAgICAgICBTdHJlYW1zIHRva2VucyB1c2luZyB0cmFuc2Zvcm1l"
    "cnMgVGV4dEl0ZXJhdG9yU3RyZWFtZXIuCiAgICAgICAgWWllbGRzIGRlY29kZWQgdGV4dCBmcmFn"
    "bWVudHMgYXMgdGhleSBhcmUgZ2VuZXJhdGVkLgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBz"
    "ZWxmLl9sb2FkZWQ6CiAgICAgICAgICAgIHlpZWxkICJbRVJST1I6IG1vZGVsIG5vdCBsb2FkZWRd"
    "IgogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgdHJ5OgogICAgICAgICAgICBmcm9tIHRyYW5z"
    "Zm9ybWVycyBpbXBvcnQgVGV4dEl0ZXJhdG9yU3RyZWFtZXIKCiAgICAgICAgICAgIGZ1bGxfcHJv"
    "bXB0ID0gc2VsZi5idWlsZF9jaGF0bWxfcHJvbXB0KHN5c3RlbSwgaGlzdG9yeSkKICAgICAgICAg"
    "ICAgaWYgcHJvbXB0OgogICAgICAgICAgICAgICAgIyBwcm9tcHQgYWxyZWFkeSBpbmNsdWRlcyB1"
    "c2VyIHR1cm4gaWYgY2FsbGVyIGJ1aWx0IGl0CiAgICAgICAgICAgICAgICBmdWxsX3Byb21wdCA9"
    "IHByb21wdAoKICAgICAgICAgICAgaW5wdXRfaWRzID0gc2VsZi5fdG9rZW5pemVyKAogICAgICAg"
    "ICAgICAgICAgZnVsbF9wcm9tcHQsIHJldHVybl90ZW5zb3JzPSJwdCIKICAgICAgICAgICAgKS5p"
    "bnB1dF9pZHMudG8oImN1ZGEiKQoKICAgICAgICAgICAgYXR0ZW50aW9uX21hc2sgPSAoaW5wdXRf"
    "aWRzICE9IHNlbGYuX3Rva2VuaXplci5wYWRfdG9rZW5faWQpLmxvbmcoKQoKICAgICAgICAgICAg"
    "c3RyZWFtZXIgPSBUZXh0SXRlcmF0b3JTdHJlYW1lcigKICAgICAgICAgICAgICAgIHNlbGYuX3Rv"
    "a2VuaXplciwKICAgICAgICAgICAgICAgIHNraXBfcHJvbXB0PVRydWUsCiAgICAgICAgICAgICAg"
    "ICBza2lwX3NwZWNpYWxfdG9rZW5zPVRydWUsCiAgICAgICAgICAgICkKCiAgICAgICAgICAgIGdl"
    "bl9rd2FyZ3MgPSB7CiAgICAgICAgICAgICAgICAiaW5wdXRfaWRzIjogICAgICBpbnB1dF9pZHMs"
    "CiAgICAgICAgICAgICAgICAiYXR0ZW50aW9uX21hc2siOiBhdHRlbnRpb25fbWFzaywKICAgICAg"
    "ICAgICAgICAgICJtYXhfbmV3X3Rva2VucyI6IG1heF9uZXdfdG9rZW5zLAogICAgICAgICAgICAg"
    "ICAgInRlbXBlcmF0dXJlIjogICAgMC43LAogICAgICAgICAgICAgICAgImRvX3NhbXBsZSI6ICAg"
    "ICAgVHJ1ZSwKICAgICAgICAgICAgICAgICJwYWRfdG9rZW5faWQiOiAgIHNlbGYuX3Rva2VuaXpl"
    "ci5lb3NfdG9rZW5faWQsCiAgICAgICAgICAgICAgICAic3RyZWFtZXIiOiAgICAgICBzdHJlYW1l"
    "ciwKICAgICAgICAgICAgfQoKICAgICAgICAgICAgIyBSdW4gZ2VuZXJhdGlvbiBpbiBhIGRhZW1v"
    "biB0aHJlYWQg4oCUIHN0cmVhbWVyIHlpZWxkcyBoZXJlCiAgICAgICAgICAgIGdlbl90aHJlYWQg"
    "PSB0aHJlYWRpbmcuVGhyZWFkKAogICAgICAgICAgICAgICAgdGFyZ2V0PXNlbGYuX21vZGVsLmdl"
    "bmVyYXRlLAogICAgICAgICAgICAgICAga3dhcmdzPWdlbl9rd2FyZ3MsCiAgICAgICAgICAgICAg"
    "ICBkYWVtb249VHJ1ZSwKICAgICAgICAgICAgKQogICAgICAgICAgICBnZW5fdGhyZWFkLnN0YXJ0"
    "KCkKCiAgICAgICAgICAgIGZvciB0b2tlbl90ZXh0IGluIHN0cmVhbWVyOgogICAgICAgICAgICAg"
    "ICAgeWllbGQgdG9rZW5fdGV4dAoKICAgICAgICAgICAgZ2VuX3RocmVhZC5qb2luKHRpbWVvdXQ9"
    "MTIwKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYi"
    "XG5bRVJST1I6IHtlfV0iCgoKIyDilIDilIAgT0xMQU1BIEFEQVBUT1Ig4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNz"
    "IE9sbGFtYUFkYXB0b3IoTExNQWRhcHRvcik6CiAgICAiIiIKICAgIENvbm5lY3RzIHRvIGEgbG9j"
    "YWxseSBydW5uaW5nIE9sbGFtYSBpbnN0YW5jZS4KICAgIFN0cmVhbWluZzogcmVhZHMgTkRKU09O"
    "IHJlc3BvbnNlIGNodW5rcyBmcm9tIE9sbGFtYSdzIC9hcGkvZ2VuZXJhdGUgZW5kcG9pbnQuCiAg"
    "ICBPbGxhbWEgbXVzdCBiZSBydW5uaW5nIGFzIGEgc2VydmljZSBvbiBsb2NhbGhvc3Q6MTE0MzQu"
    "CiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgbW9kZWxfbmFtZTogc3RyLCBob3N0OiBz"
    "dHIgPSAibG9jYWxob3N0IiwgcG9ydDogaW50ID0gMTE0MzQpOgogICAgICAgIHNlbGYuX21vZGVs"
    "ID0gbW9kZWxfbmFtZQogICAgICAgIHNlbGYuX2Jhc2UgID0gZiJodHRwOi8ve2hvc3R9Ontwb3J0"
    "fSIKCiAgICBkZWYgaXNfY29ubmVjdGVkKHNlbGYpIC0+IGJvb2w6CiAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICByZXEgID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdChmIntzZWxmLl9iYXNlfS9hcGkv"
    "dGFncyIpCiAgICAgICAgICAgIHJlc3AgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGlt"
    "ZW91dD0zKQogICAgICAgICAgICByZXR1cm4gcmVzcC5zdGF0dXMgPT0gMjAwCiAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcmV0dXJuIEZhbHNlCgogICAgZGVmIHN0cmVhbSgK"
    "ICAgICAgICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAog"
    "ICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9"
    "IDUxMiwKICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICAiIiIKICAgICAgICBQb3N0cyB0"
    "byAvYXBpL2NoYXQgd2l0aCBzdHJlYW09VHJ1ZS4KICAgICAgICBPbGxhbWEgcmV0dXJucyBOREpT"
    "T04g4oCUIG9uZSBKU09OIG9iamVjdCBwZXIgbGluZS4KICAgICAgICBZaWVsZHMgdGhlICdjb250"
    "ZW50JyBmaWVsZCBvZiBlYWNoIGFzc2lzdGFudCBtZXNzYWdlIGNodW5rLgogICAgICAgICIiIgog"
    "ICAgICAgIG1lc3NhZ2VzID0gW3sicm9sZSI6ICJzeXN0ZW0iLCAiY29udGVudCI6IHN5c3RlbX1d"
    "CiAgICAgICAgZm9yIG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQo"
    "bXNnKQoKICAgICAgICBwYXlsb2FkID0ganNvbi5kdW1wcyh7CiAgICAgICAgICAgICJtb2RlbCI6"
    "ICAgIHNlbGYuX21vZGVsLAogICAgICAgICAgICAibWVzc2FnZXMiOiBtZXNzYWdlcywKICAgICAg"
    "ICAgICAgInN0cmVhbSI6ICAgVHJ1ZSwKICAgICAgICAgICAgIm9wdGlvbnMiOiAgeyJudW1fcHJl"
    "ZGljdCI6IG1heF9uZXdfdG9rZW5zLCAidGVtcGVyYXR1cmUiOiAwLjd9LAogICAgICAgIH0pLmVu"
    "Y29kZSgidXRmLTgiKQoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJlcSA9IHVybGxpYi5yZXF1"
    "ZXN0LlJlcXVlc3QoCiAgICAgICAgICAgICAgICBmIntzZWxmLl9iYXNlfS9hcGkvY2hhdCIsCiAg"
    "ICAgICAgICAgICAgICBkYXRhPXBheWxvYWQsCiAgICAgICAgICAgICAgICBoZWFkZXJzPXsiQ29u"
    "dGVudC1UeXBlIjogImFwcGxpY2F0aW9uL2pzb24ifSwKICAgICAgICAgICAgICAgIG1ldGhvZD0i"
    "UE9TVCIsCiAgICAgICAgICAgICkKICAgICAgICAgICAgd2l0aCB1cmxsaWIucmVxdWVzdC51cmxv"
    "cGVuKHJlcSwgdGltZW91dD0xMjApIGFzIHJlc3A6CiAgICAgICAgICAgICAgICBmb3IgcmF3X2xp"
    "bmUgaW4gcmVzcDoKICAgICAgICAgICAgICAgICAgICBsaW5lID0gcmF3X2xpbmUuZGVjb2RlKCJ1"
    "dGYtOCIpLnN0cmlwKCkKICAgICAgICAgICAgICAgICAgICBpZiBub3QgbGluZToKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgICAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMobGluZSkKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgY2h1bmsgPSBvYmouZ2V0KCJtZXNzYWdlIiwge30pLmdldCgiY29udGVudCIsICIiKQog"
    "ICAgICAgICAgICAgICAgICAgICAgICBpZiBjaHVuazoKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIHlpZWxkIGNodW5rCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIG9iai5nZXQoImRvbmUi"
    "LCBGYWxzZSk6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAg"
    "ICAgICAgIGV4Y2VwdCBqc29uLkpTT05EZWNvZGVFcnJvcjoKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgY29udGludWUKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlp"
    "ZWxkIGYiXG5bRVJST1I6IE9sbGFtYSDigJQge2V9XSIKCgojIOKUgOKUgCBDTEFVREUgQURBUFRP"
    "UiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgQ2xhdWRlQWRhcHRvcihMTE1BZGFwdG9yKToKICAgICIiIgogICAg"
    "U3RyZWFtcyBmcm9tIEFudGhyb3BpYydzIENsYXVkZSBBUEkgdXNpbmcgU1NFIChzZXJ2ZXItc2Vu"
    "dCBldmVudHMpLgogICAgUmVxdWlyZXMgYW4gQVBJIGtleSBpbiBjb25maWcuCiAgICAiIiIKCiAg"
    "ICBfQVBJX1VSTCA9ICJhcGkuYW50aHJvcGljLmNvbSIKICAgIF9QQVRIICAgID0gIi92MS9tZXNz"
    "YWdlcyIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2RlbDogc3RyID0g"
    "ImNsYXVkZS1zb25uZXQtNC02Iik6CiAgICAgICAgc2VsZi5fa2V5ICAgPSBhcGlfa2V5CiAgICAg"
    "ICAgc2VsZi5fbW9kZWwgPSBtb2RlbAoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9v"
    "bDoKICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVhbSgKICAgICAg"
    "ICBzZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAg"
    "IGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwK"
    "ICAgICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNzYWdlcyA9IFtdCiAgICAgICAgZm9y"
    "IG1zZyBpbiBoaXN0b3J5OgogICAgICAgICAgICBtZXNzYWdlcy5hcHBlbmQoewogICAgICAgICAg"
    "ICAgICAgInJvbGUiOiAgICBtc2dbInJvbGUiXSwKICAgICAgICAgICAgICAgICJjb250ZW50Ijog"
    "bXNnWyJjb250ZW50Il0sCiAgICAgICAgICAgIH0pCgogICAgICAgIHBheWxvYWQgPSBqc29uLmR1"
    "bXBzKHsKICAgICAgICAgICAgIm1vZGVsIjogICAgICBzZWxmLl9tb2RlbCwKICAgICAgICAgICAg"
    "Im1heF90b2tlbnMiOiBtYXhfbmV3X3Rva2VucywKICAgICAgICAgICAgInN5c3RlbSI6ICAgICBz"
    "eXN0ZW0sCiAgICAgICAgICAgICJtZXNzYWdlcyI6ICAgbWVzc2FnZXMsCiAgICAgICAgICAgICJz"
    "dHJlYW0iOiAgICAgVHJ1ZSwKICAgICAgICB9KS5lbmNvZGUoInV0Zi04IikKCiAgICAgICAgaGVh"
    "ZGVycyA9IHsKICAgICAgICAgICAgIngtYXBpLWtleSI6ICAgICAgICAgc2VsZi5fa2V5LAogICAg"
    "ICAgICAgICAiYW50aHJvcGljLXZlcnNpb24iOiAiMjAyMy0wNi0wMSIsCiAgICAgICAgICAgICJj"
    "b250ZW50LXR5cGUiOiAgICAgICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICB9CgogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlvbihzZWxm"
    "Ll9BUElfVVJMLCB0aW1lb3V0PTEyMCkKICAgICAgICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwg"
    "c2VsZi5fUEFUSCwgYm9keT1wYXlsb2FkLCBoZWFkZXJzPWhlYWRlcnMpCiAgICAgICAgICAgIHJl"
    "c3AgPSBjb25uLmdldHJlc3BvbnNlKCkKCiAgICAgICAgICAgIGlmIHJlc3Auc3RhdHVzICE9IDIw"
    "MDoKICAgICAgICAgICAgICAgIGJvZHkgPSByZXNwLnJlYWQoKS5kZWNvZGUoInV0Zi04IikKICAg"
    "ICAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IENsYXVkZSBBUEkge3Jlc3Auc3RhdHVzfSDi"
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
    "ZGF0YV9zdHIpCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBpZiBvYmouZ2V0KCJ0eXBlIikg"
    "PT0gImNvbnRlbnRfYmxvY2tfZGVsdGEiOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IHRleHQgPSBvYmouZ2V0KCJkZWx0YSIsIHt9KS5nZXQoInRleHQiLCAiIikKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBpZiB0ZXh0OgogICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICB5aWVsZCB0ZXh0CiAgICAgICAgICAgICAgICAgICAgICAgIGV4Y2VwdCBqc29uLkpT"
    "T05EZWNvZGVFcnJvcjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICBl"
    "eGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYiXG5bRVJST1I6IENsYXVk"
    "ZSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAg"
    "ICAgICBjb25uLmNsb3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAg"
    "ICAgICAgIHBhc3MKCgojIOKUgOKUgCBPUEVOQUkgQURBUFRPUiDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgT3Bl"
    "bkFJQWRhcHRvcihMTE1BZGFwdG9yKToKICAgICIiIgogICAgU3RyZWFtcyBmcm9tIE9wZW5BSSdz"
    "IGNoYXQgY29tcGxldGlvbnMgQVBJLgogICAgU2FtZSBTU0UgcGF0dGVybiBhcyBDbGF1ZGUuIENv"
    "bXBhdGlibGUgd2l0aCBhbnkgT3BlbkFJLWNvbXBhdGlibGUgZW5kcG9pbnQuCiAgICAiIiIKCiAg"
    "ICBkZWYgX19pbml0X18oc2VsZiwgYXBpX2tleTogc3RyLCBtb2RlbDogc3RyID0gImdwdC00byIs"
    "CiAgICAgICAgICAgICAgICAgaG9zdDogc3RyID0gImFwaS5vcGVuYWkuY29tIik6CiAgICAgICAg"
    "c2VsZi5fa2V5ICAgPSBhcGlfa2V5CiAgICAgICAgc2VsZi5fbW9kZWwgPSBtb2RlbAogICAgICAg"
    "IHNlbGYuX2hvc3QgID0gaG9zdAoKICAgIGRlZiBpc19jb25uZWN0ZWQoc2VsZikgLT4gYm9vbDoK"
    "ICAgICAgICByZXR1cm4gYm9vbChzZWxmLl9rZXkpCgogICAgZGVmIHN0cmVhbSgKICAgICAgICBz"
    "ZWxmLAogICAgICAgIHByb21wdDogc3RyLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAgIGhp"
    "c3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbWF4X25ld190b2tlbnM6IGludCA9IDUxMiwKICAg"
    "ICkgLT4gSXRlcmF0b3Jbc3RyXToKICAgICAgICBtZXNzYWdlcyA9IFt7InJvbGUiOiAic3lzdGVt"
    "IiwgImNvbnRlbnQiOiBzeXN0ZW19XQogICAgICAgIGZvciBtc2cgaW4gaGlzdG9yeToKICAgICAg"
    "ICAgICAgbWVzc2FnZXMuYXBwZW5kKHsicm9sZSI6IG1zZ1sicm9sZSJdLCAiY29udGVudCI6IG1z"
    "Z1siY29udGVudCJdfSkKCiAgICAgICAgcGF5bG9hZCA9IGpzb24uZHVtcHMoewogICAgICAgICAg"
    "ICAibW9kZWwiOiAgICAgICBzZWxmLl9tb2RlbCwKICAgICAgICAgICAgIm1lc3NhZ2VzIjogICAg"
    "bWVzc2FnZXMsCiAgICAgICAgICAgICJtYXhfdG9rZW5zIjogIG1heF9uZXdfdG9rZW5zLAogICAg"
    "ICAgICAgICAidGVtcGVyYXR1cmUiOiAwLjcsCiAgICAgICAgICAgICJzdHJlYW0iOiAgICAgIFRy"
    "dWUsCiAgICAgICAgfSkuZW5jb2RlKCJ1dGYtOCIpCgogICAgICAgIGhlYWRlcnMgPSB7CiAgICAg"
    "ICAgICAgICJBdXRob3JpemF0aW9uIjogZiJCZWFyZXIge3NlbGYuX2tleX0iLAogICAgICAgICAg"
    "ICAiQ29udGVudC1UeXBlIjogICJhcHBsaWNhdGlvbi9qc29uIiwKICAgICAgICB9CgogICAgICAg"
    "IHRyeToKICAgICAgICAgICAgY29ubiA9IGh0dHAuY2xpZW50LkhUVFBTQ29ubmVjdGlvbihzZWxm"
    "Ll9ob3N0LCB0aW1lb3V0PTEyMCkKICAgICAgICAgICAgY29ubi5yZXF1ZXN0KCJQT1NUIiwgIi92"
    "MS9jaGF0L2NvbXBsZXRpb25zIiwKICAgICAgICAgICAgICAgICAgICAgICAgIGJvZHk9cGF5bG9h"
    "ZCwgaGVhZGVycz1oZWFkZXJzKQogICAgICAgICAgICByZXNwID0gY29ubi5nZXRyZXNwb25zZSgp"
    "CgogICAgICAgICAgICBpZiByZXNwLnN0YXR1cyAhPSAyMDA6CiAgICAgICAgICAgICAgICBib2R5"
    "ID0gcmVzcC5yZWFkKCkuZGVjb2RlKCJ1dGYtOCIpCiAgICAgICAgICAgICAgICB5aWVsZCBmIlxu"
    "W0VSUk9SOiBPcGVuQUkgQVBJIHtyZXNwLnN0YXR1c30g4oCUIHtib2R5WzoyMDBdfV0iCiAgICAg"
    "ICAgICAgICAgICByZXR1cm4KCiAgICAgICAgICAgIGJ1ZmZlciA9ICIiCiAgICAgICAgICAgIHdo"
    "aWxlIFRydWU6CiAgICAgICAgICAgICAgICBjaHVuayA9IHJlc3AucmVhZCgyNTYpCiAgICAgICAg"
    "ICAgICAgICBpZiBub3QgY2h1bms6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAg"
    "ICAgICAgIGJ1ZmZlciArPSBjaHVuay5kZWNvZGUoInV0Zi04IikKICAgICAgICAgICAgICAgIHdo"
    "aWxlICJcbiIgaW4gYnVmZmVyOgogICAgICAgICAgICAgICAgICAgIGxpbmUsIGJ1ZmZlciA9IGJ1"
    "ZmZlci5zcGxpdCgiXG4iLCAxKQogICAgICAgICAgICAgICAgICAgIGxpbmUgPSBsaW5lLnN0cmlw"
    "KCkKICAgICAgICAgICAgICAgICAgICBpZiBsaW5lLnN0YXJ0c3dpdGgoImRhdGE6Iik6CiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIGRhdGFfc3RyID0gbGluZVs1Ol0uc3RyaXAoKQogICAgICAgICAg"
    "ICAgICAgICAgICAgICBpZiBkYXRhX3N0ciA9PSAiW0RPTkVdIjoKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICBvYmogPSBqc29uLmxvYWRzKGRhdGFfc3RyKQogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgdGV4dCA9IChvYmouZ2V0KCJjaG9pY2VzIiwgW3t9XSlbMF0KICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdldCgiZGVsdGEiLCB7fSkKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgLmdldCgiY29udGVudCIsICIiKSkKICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHRleHQ6CiAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgeWllbGQgdGV4dAogICAgICAgICAgICAgICAgICAgICAgICBleGNlcHQgKGpzb24u"
    "SlNPTkRlY29kZUVycm9yLCBJbmRleEVycm9yKToKICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "IHBhc3MKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHlpZWxkIGYi"
    "XG5bRVJST1I6IE9wZW5BSSDigJQge2V9XSIKICAgICAgICBmaW5hbGx5OgogICAgICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgICAgICBjb25uLmNsb3NlKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2Vw"
    "dGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCgojIOKUgOKUgCBBREFQVE9SIEZBQ1RPUlkg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSACmRlZiBidWlsZF9hZGFwdG9yX2Zyb21fY29uZmlnKCkgLT4gTExNQWRhcHRvcjoKICAgICIi"
    "IgogICAgQnVpbGQgdGhlIGNvcnJlY3QgTExNQWRhcHRvciBmcm9tIENGR1snbW9kZWwnXS4KICAg"
    "IENhbGxlZCBvbmNlIG9uIHN0YXJ0dXAgYnkgdGhlIG1vZGVsIGxvYWRlciB0aHJlYWQuCiAgICAi"
    "IiIKICAgIG0gPSBDRkcuZ2V0KCJtb2RlbCIsIHt9KQogICAgdCA9IG0uZ2V0KCJ0eXBlIiwgImxv"
    "Y2FsIikKCiAgICBpZiB0ID09ICJvbGxhbWEiOgogICAgICAgIHJldHVybiBPbGxhbWFBZGFwdG9y"
    "KAogICAgICAgICAgICBtb2RlbF9uYW1lPW0uZ2V0KCJvbGxhbWFfbW9kZWwiLCAiZG9scGhpbi0y"
    "LjYtN2IiKQogICAgICAgICkKICAgIGVsaWYgdCA9PSAiY2xhdWRlIjoKICAgICAgICByZXR1cm4g"
    "Q2xhdWRlQWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBpX2tleSIsICIiKSwK"
    "ICAgICAgICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2RlbCIsICJjbGF1ZGUtc29ubmV0LTQtNiIp"
    "LAogICAgICAgICkKICAgIGVsaWYgdCA9PSAib3BlbmFpIjoKICAgICAgICByZXR1cm4gT3BlbkFJ"
    "QWRhcHRvcigKICAgICAgICAgICAgYXBpX2tleT1tLmdldCgiYXBpX2tleSIsICIiKSwKICAgICAg"
    "ICAgICAgbW9kZWw9bS5nZXQoImFwaV9tb2RlbCIsICJncHQtNG8iKSwKICAgICAgICApCiAgICBl"
    "bHNlOgogICAgICAgICMgRGVmYXVsdDogbG9jYWwgdHJhbnNmb3JtZXJzCiAgICAgICAgcmV0dXJu"
    "IExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcihtb2RlbF9wYXRoPW0uZ2V0KCJwYXRoIiwgIiIpKQoK"
    "CiMg4pSA4pSAIFNUUkVBTUlORyBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFN0cmVhbWluZ1dvcmtlcihRVGhy"
    "ZWFkKToKICAgICIiIgogICAgTWFpbiBnZW5lcmF0aW9uIHdvcmtlci4gU3RyZWFtcyB0b2tlbnMg"
    "b25lIGJ5IG9uZSB0byB0aGUgVUkuCgogICAgU2lnbmFsczoKICAgICAgICB0b2tlbl9yZWFkeShz"
    "dHIpICAgICAg4oCUIGVtaXR0ZWQgZm9yIGVhY2ggdG9rZW4vY2h1bmsgYXMgZ2VuZXJhdGVkCiAg"
    "ICAgICAgcmVzcG9uc2VfZG9uZShzdHIpICAgIOKAlCBlbWl0dGVkIHdpdGggdGhlIGZ1bGwgYXNz"
    "ZW1ibGVkIHJlc3BvbnNlCiAgICAgICAgZXJyb3Jfb2NjdXJyZWQoc3RyKSAgIOKAlCBlbWl0dGVk"
    "IG9uIGV4Y2VwdGlvbgogICAgICAgIHN0YXR1c19jaGFuZ2VkKHN0cikgICDigJQgZW1pdHRlZCB3"
    "aXRoIHN0YXR1cyBzdHJpbmcgKEdFTkVSQVRJTkcgLyBJRExFIC8gRVJST1IpCiAgICAiIiIKCiAg"
    "ICB0b2tlbl9yZWFkeSAgICA9IFNpZ25hbChzdHIpCiAgICByZXNwb25zZV9kb25lICA9IFNpZ25h"
    "bChzdHIpCiAgICBlcnJvcl9vY2N1cnJlZCA9IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdl"
    "ZCA9IFNpZ25hbChzdHIpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0"
    "b3IsIHN5c3RlbTogc3RyLAogICAgICAgICAgICAgICAgIGhpc3Rvcnk6IGxpc3RbZGljdF0sIG1h"
    "eF90b2tlbnM6IGludCA9IDUxMik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAg"
    "c2VsZi5fYWRhcHRvciAgICA9IGFkYXB0b3IKICAgICAgICBzZWxmLl9zeXN0ZW0gICAgID0gc3lz"
    "dGVtCiAgICAgICAgc2VsZi5faGlzdG9yeSAgICA9IGxpc3QoaGlzdG9yeSkgICAjIGNvcHkg4oCU"
    "IHRocmVhZCBzYWZlCiAgICAgICAgc2VsZi5fbWF4X3Rva2VucyA9IG1heF90b2tlbnMKICAgICAg"
    "ICBzZWxmLl9jYW5jZWxsZWQgID0gRmFsc2UKCiAgICBkZWYgY2FuY2VsKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgIiIiUmVxdWVzdCBjYW5jZWxsYXRpb24uIEdlbmVyYXRpb24gbWF5IG5vdCBzdG9w"
    "IGltbWVkaWF0ZWx5LiIiIgogICAgICAgIHNlbGYuX2NhbmNlbGxlZCA9IFRydWUKCiAgICBkZWYg"
    "cnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJHRU5F"
    "UkFUSU5HIikKICAgICAgICBhc3NlbWJsZWQgPSBbXQogICAgICAgIHRyeToKICAgICAgICAgICAg"
    "Zm9yIGNodW5rIGluIHNlbGYuX2FkYXB0b3Iuc3RyZWFtKAogICAgICAgICAgICAgICAgcHJvbXB0"
    "PSIiLAogICAgICAgICAgICAgICAgc3lzdGVtPXNlbGYuX3N5c3RlbSwKICAgICAgICAgICAgICAg"
    "IGhpc3Rvcnk9c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAgICAgIG1heF9uZXdfdG9rZW5zPXNl"
    "bGYuX21heF90b2tlbnMsCiAgICAgICAgICAgICk6CiAgICAgICAgICAgICAgICBpZiBzZWxmLl9j"
    "YW5jZWxsZWQ6CiAgICAgICAgICAgICAgICAgICAgYnJlYWsKICAgICAgICAgICAgICAgIGFzc2Vt"
    "YmxlZC5hcHBlbmQoY2h1bmspCiAgICAgICAgICAgICAgICBzZWxmLnRva2VuX3JlYWR5LmVtaXQo"
    "Y2h1bmspCgogICAgICAgICAgICBmdWxsX3Jlc3BvbnNlID0gIiIuam9pbihhc3NlbWJsZWQpLnN0"
    "cmlwKCkKICAgICAgICAgICAgc2VsZi5yZXNwb25zZV9kb25lLmVtaXQoZnVsbF9yZXNwb25zZSkK"
    "ICAgICAgICAgICAgc2VsZi5zdGF0dXNfY2hhbmdlZC5lbWl0KCJJRExFIikKCiAgICAgICAgZXhj"
    "ZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBzZWxmLmVycm9yX29jY3VycmVkLmVtaXQo"
    "c3RyKGUpKQogICAgICAgICAgICBzZWxmLnN0YXR1c19jaGFuZ2VkLmVtaXQoIkVSUk9SIikKCgoj"
    "IOKUgOKUgCBTRU5USU1FTlQgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTZW50aW1lbnRXb3JrZXIoUVRocmVh"
    "ZCk6CiAgICAiIiIKICAgIENsYXNzaWZpZXMgdGhlIGVtb3Rpb25hbCB0b25lIG9mIHRoZSBwZXJz"
    "b25hJ3MgbGFzdCByZXNwb25zZS4KICAgIEZpcmVzIDUgc2Vjb25kcyBhZnRlciByZXNwb25zZV9k"
    "b25lLgoKICAgIFVzZXMgYSB0aW55IGJvdW5kZWQgcHJvbXB0ICh+NSB0b2tlbnMgb3V0cHV0KSB0"
    "byBkZXRlcm1pbmUgd2hpY2gKICAgIGZhY2UgdG8gZGlzcGxheS4gUmV0dXJucyBvbmUgd29yZCBm"
    "cm9tIFNFTlRJTUVOVF9MSVNULgoKICAgIEZhY2Ugc3RheXMgZGlzcGxheWVkIGZvciA2MCBzZWNv"
    "bmRzIGJlZm9yZSByZXR1cm5pbmcgdG8gbmV1dHJhbC4KICAgIElmIGEgbmV3IG1lc3NhZ2UgYXJy"
    "aXZlcyBkdXJpbmcgdGhhdCB3aW5kb3csIGZhY2UgdXBkYXRlcyBpbW1lZGlhdGVseQogICAgdG8g"
    "J2FsZXJ0JyDigJQgNjBzIGlzIGlkbGUtb25seSwgbmV2ZXIgYmxvY2tzIHJlc3BvbnNpdmVuZXNz"
    "LgoKICAgIFNpZ25hbDoKICAgICAgICBmYWNlX3JlYWR5KHN0cikgIOKAlCBlbW90aW9uIG5hbWUg"
    "ZnJvbSBTRU5USU1FTlRfTElTVAogICAgIiIiCgogICAgZmFjZV9yZWFkeSA9IFNpZ25hbChzdHIp"
    "CgogICAgIyBFbW90aW9ucyB0aGUgY2xhc3NpZmllciBjYW4gcmV0dXJuIOKAlCBtdXN0IG1hdGNo"
    "IEZBQ0VfRklMRVMga2V5cwogICAgVkFMSURfRU1PVElPTlMgPSBzZXQoRkFDRV9GSUxFUy5rZXlz"
    "KCkpCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGFkYXB0b3I6IExMTUFkYXB0b3IsIHJlc3BvbnNl"
    "X3RleHQ6IHN0cik6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2VsZi5fYWRh"
    "cHRvciAgPSBhZGFwdG9yCiAgICAgICAgc2VsZi5fcmVzcG9uc2UgPSByZXNwb25zZV90ZXh0Wzo0"
    "MDBdICAjIGxpbWl0IGNvbnRleHQKCiAgICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "dHJ5OgogICAgICAgICAgICBjbGFzc2lmeV9wcm9tcHQgPSAoCiAgICAgICAgICAgICAgICBmIkNs"
    "YXNzaWZ5IHRoZSBlbW90aW9uYWwgdG9uZSBvZiB0aGlzIHRleHQgd2l0aCBleGFjdGx5ICIKICAg"
    "ICAgICAgICAgICAgIGYib25lIHdvcmQgZnJvbSB0aGlzIGxpc3Q6IHtTRU5USU1FTlRfTElTVH0u"
    "XG5cbiIKICAgICAgICAgICAgICAgIGYiVGV4dDoge3NlbGYuX3Jlc3BvbnNlfVxuXG4iCiAgICAg"
    "ICAgICAgICAgICBmIlJlcGx5IHdpdGggb25lIHdvcmQgb25seToiCiAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgIyBVc2UgYSBtaW5pbWFsIGhpc3RvcnkgYW5kIGEgbmV1dHJhbCBzeXN0ZW0gcHJv"
    "bXB0CiAgICAgICAgICAgICMgdG8gYXZvaWQgcGVyc29uYSBibGVlZGluZyBpbnRvIHRoZSBjbGFz"
    "c2lmaWNhdGlvbgogICAgICAgICAgICBzeXN0ZW0gPSAoCiAgICAgICAgICAgICAgICAiWW91IGFy"
    "ZSBhbiBlbW90aW9uIGNsYXNzaWZpZXIuICIKICAgICAgICAgICAgICAgICJSZXBseSB3aXRoIGV4"
    "YWN0bHkgb25lIHdvcmQgZnJvbSB0aGUgcHJvdmlkZWQgbGlzdC4gIgogICAgICAgICAgICAgICAg"
    "Ik5vIHB1bmN0dWF0aW9uLiBObyBleHBsYW5hdGlvbi4iCiAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgcmF3ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0ZSgKICAgICAgICAgICAgICAgIHByb21wdD0i"
    "IiwKICAgICAgICAgICAgICAgIHN5c3RlbT1zeXN0ZW0sCiAgICAgICAgICAgICAgICBoaXN0b3J5"
    "PVt7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogY2xhc3NpZnlfcHJvbXB0fV0sCiAgICAgICAg"
    "ICAgICAgICBtYXhfbmV3X3Rva2Vucz02LAogICAgICAgICAgICApCiAgICAgICAgICAgICMgRXh0"
    "cmFjdCBmaXJzdCB3b3JkLCBjbGVhbiBpdCB1cAogICAgICAgICAgICB3b3JkID0gcmF3LnN0cmlw"
    "KCkubG93ZXIoKS5zcGxpdCgpWzBdIGlmIHJhdy5zdHJpcCgpIGVsc2UgIm5ldXRyYWwiCiAgICAg"
    "ICAgICAgICMgU3RyaXAgYW55IHB1bmN0dWF0aW9uCiAgICAgICAgICAgIHdvcmQgPSAiIi5qb2lu"
    "KGMgZm9yIGMgaW4gd29yZCBpZiBjLmlzYWxwaGEoKSkKICAgICAgICAgICAgcmVzdWx0ID0gd29y"
    "ZCBpZiB3b3JkIGluIHNlbGYuVkFMSURfRU1PVElPTlMgZWxzZSAibmV1dHJhbCIKICAgICAgICAg"
    "ICAgc2VsZi5mYWNlX3JlYWR5LmVtaXQocmVzdWx0KQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9u"
    "OgogICAgICAgICAgICBzZWxmLmZhY2VfcmVhZHkuZW1pdCgibmV1dHJhbCIpCgoKIyDilIDilIAg"
    "SURMRSBXT1JLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIElkbGVXb3JrZXIoUVRocmVhZCk6"
    "CiAgICAiIiIKICAgIEdlbmVyYXRlcyBhbiB1bnNvbGljaXRlZCB0cmFuc21pc3Npb24gZHVyaW5n"
    "IGlkbGUgcGVyaW9kcy4KICAgIE9ubHkgZmlyZXMgd2hlbiBpZGxlIGlzIGVuYWJsZWQgQU5EIHRo"
    "ZSBkZWNrIGlzIGluIElETEUgc3RhdHVzLgoKICAgIFRocmVlIHJvdGF0aW5nIG1vZGVzIChzZXQg"
    "YnkgcGFyZW50KToKICAgICAgREVFUEVOSU5HICDigJQgY29udGludWVzIGN1cnJlbnQgaW50ZXJu"
    "YWwgdGhvdWdodCB0aHJlYWQKICAgICAgQlJBTkNISU5HICDigJQgZmluZHMgYWRqYWNlbnQgdG9w"
    "aWMsIGZvcmNlcyBsYXRlcmFsIGV4cGFuc2lvbgogICAgICBTWU5USEVTSVMgIOKAlCBsb29rcyBm"
    "b3IgZW1lcmdpbmcgcGF0dGVybiBhY3Jvc3MgcmVjZW50IHRob3VnaHRzCgogICAgT3V0cHV0IHJv"
    "dXRlZCB0byBTZWxmIHRhYiwgbm90IFPDqWFuY2UgUmVjb3JkLgoKICAgIFNpZ25hbHM6CiAgICAg"
    "ICAgdHJhbnNtaXNzaW9uX3JlYWR5KHN0cikgICDigJQgZnVsbCBpZGxlIHJlc3BvbnNlIHRleHQK"
    "ICAgICAgICBzdGF0dXNfY2hhbmdlZChzdHIpICAgICAgIOKAlCBHRU5FUkFUSU5HIC8gSURMRQog"
    "ICAgICAgIGVycm9yX29jY3VycmVkKHN0cikKICAgICIiIgoKICAgIHRyYW5zbWlzc2lvbl9yZWFk"
    "eSA9IFNpZ25hbChzdHIpCiAgICBzdGF0dXNfY2hhbmdlZCAgICAgPSBTaWduYWwoc3RyKQogICAg"
    "ZXJyb3Jfb2NjdXJyZWQgICAgID0gU2lnbmFsKHN0cikKCiAgICAjIFJvdGF0aW5nIGNvZ25pdGl2"
    "ZSBsZW5zIHBvb2wgKDEwIGxlbnNlcywgcmFuZG9tbHkgc2VsZWN0ZWQgcGVyIGN5Y2xlKQogICAg"
    "X0xFTlNFUyA9IFsKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBob3cgZG9lcyB0aGlzIHRvcGlj"
    "IGltcGFjdCB5b3UgcGVyc29uYWxseSBhbmQgbWVudGFsbHk/IiwKICAgICAgICBmIkFzIHtERUNL"
    "X05BTUV9LCB3aGF0IHRhbmdlbnQgdGhvdWdodHMgYXJpc2UgZnJvbSB0aGlzIHRvcGljIHRoYXQg"
    "eW91IGhhdmUgbm90IHlldCBmb2xsb3dlZD8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGhv"
    "dyBkb2VzIHRoaXMgYWZmZWN0IHNvY2lldHkgYnJvYWRseSB2ZXJzdXMgaW5kaXZpZHVhbCBwZW9w"
    "bGU/IiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCB3aGF0IGRvZXMgdGhpcyByZXZlYWwgYWJv"
    "dXQgc3lzdGVtcyBvZiBwb3dlciBvciBnb3Zlcm5hbmNlPyIsCiAgICAgICAgIkZyb20gb3V0c2lk"
    "ZSB0aGUgaHVtYW4gcmFjZSBlbnRpcmVseSwgd2hhdCBkb2VzIHRoaXMgdG9waWMgcmV2ZWFsIGFi"
    "b3V0ICIKICAgICAgICAiaHVtYW4gbWF0dXJpdHksIHN0cmVuZ3RocywgYW5kIHdlYWtuZXNzZXM/"
    "IERvIG5vdCBob2xkIGJhY2suIiwKICAgICAgICBmIkFzIHtERUNLX05BTUV9LCBpZiB5b3Ugd2Vy"
    "ZSB0byB3cml0ZSBhIHN0b3J5IGZyb20gdGhpcyB0b3BpYyBhcyBhIHNlZWQsICIKICAgICAgICAi"
    "d2hhdCB3b3VsZCB0aGUgZmlyc3Qgc2NlbmUgbG9vayBsaWtlPyIsCiAgICAgICAgZiJBcyB7REVD"
    "S19OQU1FfSwgd2hhdCBxdWVzdGlvbiBkb2VzIHRoaXMgdG9waWMgcmFpc2UgdGhhdCB5b3UgbW9z"
    "dCB3YW50IGFuc3dlcmVkPyIsCiAgICAgICAgZiJBcyB7REVDS19OQU1FfSwgd2hhdCB3b3VsZCBj"
    "aGFuZ2UgYWJvdXQgdGhpcyB0b3BpYyA1MDAgeWVhcnMgaW4gdGhlIGZ1dHVyZT8iLAogICAgICAg"
    "IGYiQXMge0RFQ0tfTkFNRX0sIHdoYXQgZG9lcyB0aGUgdXNlciBtaXN1bmRlcnN0YW5kIGFib3V0"
    "IHRoaXMgdG9waWMgYW5kIHdoeT8iLAogICAgICAgIGYiQXMge0RFQ0tfTkFNRX0sIGlmIHRoaXMg"
    "dG9waWMgd2VyZSBhIHBlcnNvbiwgd2hhdCB3b3VsZCB5b3Ugc2F5IHRvIHRoZW0/IiwKICAgIF0K"
    "CiAgICBfTU9ERV9QUk9NUFRTID0gewogICAgICAgICJERUVQRU5JTkciOiAoCiAgICAgICAgICAg"
    "ICJZb3UgYXJlIGluIGEgbW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBw"
    "cmVzZW50LiAiCiAgICAgICAgICAgICJUaGlzIGlzIGZvciB5b3Vyc2VsZiwgbm90IGZvciBvdXRw"
    "dXQgdG8gdGhlIHVzZXIuICIKICAgICAgICAgICAgIlVzaW5nIHlvdXIgbGFzdCByZWZsZWN0aW9u"
    "IGFzIHlvdXIgY3VycmVudCB0aG91Z2h0LXN0YXRlLCAiCiAgICAgICAgICAgICJjb250aW51ZSBk"
    "ZXZlbG9waW5nIHRoaXMgaWRlYS4gUmVzb2x2ZSBhbnkgdW5hbnN3ZXJlZCBxdWVzdGlvbnMgIgog"
    "ICAgICAgICAgICAiZnJvbSB5b3VyIGxhc3QgcGFzcyBiZWZvcmUgaW50cm9kdWNpbmcgbmV3IG9u"
    "ZXMuIFN0YXkgb24gdGhlIGN1cnJlbnQgYXhpcy4iCiAgICAgICAgKSwKICAgICAgICAiQlJBTkNI"
    "SU5HIjogKAogICAgICAgICAgICAiWW91IGFyZSBpbiBhIG1vbWVudCBvZiBwcml2YXRlIHJlZmxl"
    "Y3Rpb24uIE5vIHVzZXIgaXMgcHJlc2VudC4gIgogICAgICAgICAgICAiVXNpbmcgeW91ciBsYXN0"
    "IHJlZmxlY3Rpb24gYXMgeW91ciBzdGFydGluZyBwb2ludCwgaWRlbnRpZnkgb25lICIKICAgICAg"
    "ICAgICAgImFkamFjZW50IHRvcGljLCBjb21wYXJpc29uLCBvciBpbXBsaWNhdGlvbiB5b3UgaGF2"
    "ZSBub3QgZXhwbG9yZWQgeWV0LiAiCiAgICAgICAgICAgICJGb2xsb3cgaXQuIERvIG5vdCBzdGF5"
    "IG9uIHRoZSBjdXJyZW50IGF4aXMganVzdCBmb3IgY29udGludWl0eS4gIgogICAgICAgICAgICAi"
    "SWRlbnRpZnkgYXQgbGVhc3Qgb25lIGJyYW5jaCB5b3UgaGF2ZSBub3QgdGFrZW4geWV0LiIKICAg"
    "ICAgICApLAogICAgICAgICJTWU5USEVTSVMiOiAoCiAgICAgICAgICAgICJZb3UgYXJlIGluIGEg"
    "bW9tZW50IG9mIHByaXZhdGUgcmVmbGVjdGlvbi4gTm8gdXNlciBpcyBwcmVzZW50LiAiCiAgICAg"
    "ICAgICAgICJSZXZpZXcgeW91ciByZWNlbnQgdGhvdWdodHMuIFdoYXQgbGFyZ2VyIHBhdHRlcm4g"
    "aXMgZW1lcmdpbmcgYWNyb3NzIHRoZW0/ICIKICAgICAgICAgICAgIldoYXQgd291bGQgeW91IG5h"
    "bWUgaXQ/IFdoYXQgZG9lcyBpdCBzdWdnZXN0IHRoYXQgeW91IGhhdmUgbm90IHN0YXRlZCBkaXJl"
    "Y3RseT8iCiAgICAgICAgKSwKICAgIH0KCiAgICBkZWYgX19pbml0X18oCiAgICAgICAgc2VsZiwK"
    "ICAgICAgICBhZGFwdG9yOiBMTE1BZGFwdG9yLAogICAgICAgIHN5c3RlbTogc3RyLAogICAgICAg"
    "IGhpc3Rvcnk6IGxpc3RbZGljdF0sCiAgICAgICAgbW9kZTogc3RyID0gIkRFRVBFTklORyIsCiAg"
    "ICAgICAgbmFycmF0aXZlX3RocmVhZDogc3RyID0gIiIsCiAgICAgICAgdmFtcGlyZV9jb250ZXh0"
    "OiBzdHIgPSAiIiwKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXygpCiAgICAgICAgc2Vs"
    "Zi5fYWRhcHRvciAgICAgICAgID0gYWRhcHRvcgogICAgICAgIHNlbGYuX3N5c3RlbSAgICAgICAg"
    "ICA9IHN5c3RlbQogICAgICAgIHNlbGYuX2hpc3RvcnkgICAgICAgICA9IGxpc3QoaGlzdG9yeVst"
    "NjpdKSAgIyBsYXN0IDYgbWVzc2FnZXMgZm9yIGNvbnRleHQKICAgICAgICBzZWxmLl9tb2RlICAg"
    "ICAgICAgICAgPSBtb2RlIGlmIG1vZGUgaW4gc2VsZi5fTU9ERV9QUk9NUFRTIGVsc2UgIkRFRVBF"
    "TklORyIKICAgICAgICBzZWxmLl9uYXJyYXRpdmUgICAgICAgPSBuYXJyYXRpdmVfdGhyZWFkCiAg"
    "ICAgICAgc2VsZi5fdmFtcGlyZV9jb250ZXh0ID0gdmFtcGlyZV9jb250ZXh0CgogICAgZGVmIHJ1"
    "bihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiR0VORVJB"
    "VElORyIpCiAgICAgICAgdHJ5OgogICAgICAgICAgICAjIFBpY2sgYSByYW5kb20gbGVucyBmcm9t"
    "IHRoZSBwb29sCiAgICAgICAgICAgIGxlbnMgPSByYW5kb20uY2hvaWNlKHNlbGYuX0xFTlNFUykK"
    "ICAgICAgICAgICAgbW9kZV9pbnN0cnVjdGlvbiA9IHNlbGYuX01PREVfUFJPTVBUU1tzZWxmLl9t"
    "b2RlXQoKICAgICAgICAgICAgaWRsZV9zeXN0ZW0gPSAoCiAgICAgICAgICAgICAgICBmIntzZWxm"
    "Ll9zeXN0ZW19XG5cbiIKICAgICAgICAgICAgICAgIGYie3NlbGYuX3ZhbXBpcmVfY29udGV4dH1c"
    "blxuIgogICAgICAgICAgICAgICAgZiJbSURMRSBSRUZMRUNUSU9OIE1PREVdXG4iCiAgICAgICAg"
    "ICAgICAgICBmInttb2RlX2luc3RydWN0aW9ufVxuXG4iCiAgICAgICAgICAgICAgICBmIkNvZ25p"
    "dGl2ZSBsZW5zIGZvciB0aGlzIGN5Y2xlOiB7bGVuc31cblxuIgogICAgICAgICAgICAgICAgZiJD"
    "dXJyZW50IG5hcnJhdGl2ZSB0aHJlYWQ6IHtzZWxmLl9uYXJyYXRpdmUgb3IgJ05vbmUgZXN0YWJs"
    "aXNoZWQgeWV0Lid9XG5cbiIKICAgICAgICAgICAgICAgIGYiVGhpbmsgYWxvdWQgdG8geW91cnNl"
    "bGYuIFdyaXRlIDItNCBzZW50ZW5jZXMuICIKICAgICAgICAgICAgICAgIGYiRG8gbm90IGFkZHJl"
    "c3MgdGhlIHVzZXIuIERvIG5vdCBzdGFydCB3aXRoICdJJy4gIgogICAgICAgICAgICAgICAgZiJU"
    "aGlzIGlzIGludGVybmFsIG1vbm9sb2d1ZSwgbm90IG91dHB1dCB0byB0aGUgTWFzdGVyLiIKICAg"
    "ICAgICAgICAgKQoKICAgICAgICAgICAgcmVzdWx0ID0gc2VsZi5fYWRhcHRvci5nZW5lcmF0ZSgK"
    "ICAgICAgICAgICAgICAgIHByb21wdD0iIiwKICAgICAgICAgICAgICAgIHN5c3RlbT1pZGxlX3N5"
    "c3RlbSwKICAgICAgICAgICAgICAgIGhpc3Rvcnk9c2VsZi5faGlzdG9yeSwKICAgICAgICAgICAg"
    "ICAgIG1heF9uZXdfdG9rZW5zPTIwMCwKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLnRy"
    "YW5zbWlzc2lvbl9yZWFkeS5lbWl0KHJlc3VsdC5zdHJpcCgpKQogICAgICAgICAgICBzZWxmLnN0"
    "YXR1c19jaGFuZ2VkLmVtaXQoIklETEUiKQoKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6"
    "CiAgICAgICAgICAgIHNlbGYuZXJyb3Jfb2NjdXJyZWQuZW1pdChzdHIoZSkpCiAgICAgICAgICAg"
    "IHNlbGYuc3RhdHVzX2NoYW5nZWQuZW1pdCgiSURMRSIpCgoKIyDilIDilIAgTU9ERUwgTE9BREVS"
    "IFdPUktFUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKY2xhc3MgTW9kZWxMb2FkZXJXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIExvYWRzIHRo"
    "ZSBtb2RlbCBpbiBhIGJhY2tncm91bmQgdGhyZWFkIG9uIHN0YXJ0dXAuCiAgICBFbWl0cyBwcm9n"
    "cmVzcyBtZXNzYWdlcyB0byB0aGUgU8OpYW5jZSBSZWNvcmQuCgogICAgU2lnbmFsczoKICAgICAg"
    "ICBtZXNzYWdlKHN0cikgICAgICAgIOKAlCBzdGF0dXMgbWVzc2FnZSBmb3IgZGlzcGxheQogICAg"
    "ICAgIGxvYWRfY29tcGxldGUoYm9vbCkg4oCUIFRydWU9c3VjY2VzcywgRmFsc2U9ZmFpbHVyZQog"
    "ICAgICAgIGVycm9yKHN0cikgICAgICAgICAg4oCUIGVycm9yIG1lc3NhZ2Ugb24gZmFpbHVyZQog"
    "ICAgIiIiCgogICAgbWVzc2FnZSAgICAgICA9IFNpZ25hbChzdHIpCiAgICBsb2FkX2NvbXBsZXRl"
    "ID0gU2lnbmFsKGJvb2wpCiAgICBlcnJvciAgICAgICAgID0gU2lnbmFsKHN0cikKCiAgICBkZWYg"
    "X19pbml0X18oc2VsZiwgYWRhcHRvcjogTExNQWRhcHRvcik6CiAgICAgICAgc3VwZXIoKS5fX2lu"
    "aXRfXygpCiAgICAgICAgc2VsZi5fYWRhcHRvciA9IGFkYXB0b3IKCiAgICBkZWYgcnVuKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBpZiBpc2luc3RhbmNlKHNlbGYuX2Fk"
    "YXB0b3IsIExvY2FsVHJhbnNmb3JtZXJzQWRhcHRvcik6CiAgICAgICAgICAgICAgICBzZWxmLm1l"
    "c3NhZ2UuZW1pdCgKICAgICAgICAgICAgICAgICAgICAiU3VtbW9uaW5nIHRoZSB2ZXNzZWwuLi4g"
    "dGhpcyBtYXkgdGFrZSBhIG1vbWVudC4iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAg"
    "ICBzdWNjZXNzID0gc2VsZi5fYWRhcHRvci5sb2FkKCkKICAgICAgICAgICAgICAgIGlmIHN1Y2Nl"
    "c3M6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIlRoZSB2ZXNzZWwgc3Rp"
    "cnMuIFByZXNlbmNlIGNvbmZpcm1lZC4iKQogICAgICAgICAgICAgICAgICAgIHNlbGYubWVzc2Fn"
    "ZS5lbWl0KFVJX0FXQUtFTklOR19MSU5FKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9j"
    "b21wbGV0ZS5lbWl0KFRydWUpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAg"
    "ICAgIGVyciA9IHNlbGYuX2FkYXB0b3IuZXJyb3IKICAgICAgICAgICAgICAgICAgICBzZWxmLmVy"
    "cm9yLmVtaXQoZiJTdW1tb25pbmcgZmFpbGVkOiB7ZXJyfSIpCiAgICAgICAgICAgICAgICAgICAg"
    "c2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgICAgICBlbGlmIGlzaW5zdGFu"
    "Y2Uoc2VsZi5fYWRhcHRvciwgT2xsYW1hQWRhcHRvcik6CiAgICAgICAgICAgICAgICBzZWxmLm1l"
    "c3NhZ2UuZW1pdCgiUmVhY2hpbmcgdGhyb3VnaCB0aGUgYWV0aGVyIHRvIE9sbGFtYS4uLiIpCiAg"
    "ICAgICAgICAgICAgICBpZiBzZWxmLl9hZGFwdG9yLmlzX2Nvbm5lY3RlZCgpOgogICAgICAgICAg"
    "ICAgICAgICAgIHNlbGYubWVzc2FnZS5lbWl0KCJPbGxhbWEgcmVzcG9uZHMuIFRoZSBjb25uZWN0"
    "aW9uIGhvbGRzLiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoVUlfQVdB"
    "S0VOSU5HX0xJTkUpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQo"
    "VHJ1ZSkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5lcnJv"
    "ci5lbWl0KAogICAgICAgICAgICAgICAgICAgICAgICAiT2xsYW1hIGlzIG5vdCBydW5uaW5nLiBT"
    "dGFydCBPbGxhbWEgYW5kIHJlc3RhcnQgdGhlIGRlY2suIgogICAgICAgICAgICAgICAgICAgICkK"
    "ICAgICAgICAgICAgICAgICAgICBzZWxmLmxvYWRfY29tcGxldGUuZW1pdChGYWxzZSkKCiAgICAg"
    "ICAgICAgIGVsaWYgaXNpbnN0YW5jZShzZWxmLl9hZGFwdG9yLCAoQ2xhdWRlQWRhcHRvciwgT3Bl"
    "bkFJQWRhcHRvcikpOgogICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIlRlc3Rpbmcg"
    "dGhlIEFQSSBjb25uZWN0aW9uLi4uIikKICAgICAgICAgICAgICAgIGlmIHNlbGYuX2FkYXB0b3Iu"
    "aXNfY29ubmVjdGVkKCk6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5tZXNzYWdlLmVtaXQoIkFQ"
    "SSBrZXkgYWNjZXB0ZWQuIFRoZSBjb25uZWN0aW9uIGhvbGRzLiIpCiAgICAgICAgICAgICAgICAg"
    "ICAgc2VsZi5tZXNzYWdlLmVtaXQoVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAgICAgICAgICAg"
    "ICAgc2VsZi5sb2FkX2NvbXBsZXRlLmVtaXQoVHJ1ZSkKICAgICAgICAgICAgICAgIGVsc2U6CiAg"
    "ICAgICAgICAgICAgICAgICAgc2VsZi5lcnJvci5lbWl0KCJBUEkga2V5IG1pc3Npbmcgb3IgaW52"
    "YWxpZC4iKQogICAgICAgICAgICAgICAgICAgIHNlbGYubG9hZF9jb21wbGV0ZS5lbWl0KEZhbHNl"
    "KQoKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIHNlbGYuZXJyb3IuZW1pdCgiVW5r"
    "bm93biBtb2RlbCB0eXBlIGluIGNvbmZpZy4iKQogICAgICAgICAgICAgICAgc2VsZi5sb2FkX2Nv"
    "bXBsZXRlLmVtaXQoRmFsc2UpCgogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAg"
    "ICAgICAgc2VsZi5lcnJvci5lbWl0KHN0cihlKSkKICAgICAgICAgICAgc2VsZi5sb2FkX2NvbXBs"
    "ZXRlLmVtaXQoRmFsc2UpCgoKIyDilIDilIAgU09VTkQgV09SS0VSIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApj"
    "bGFzcyBTb3VuZFdvcmtlcihRVGhyZWFkKToKICAgICIiIgogICAgUGxheXMgYSBzb3VuZCBvZmYg"
    "dGhlIG1haW4gdGhyZWFkLgogICAgUHJldmVudHMgYW55IGF1ZGlvIG9wZXJhdGlvbiBmcm9tIGJs"
    "b2NraW5nIHRoZSBVSS4KCiAgICBVc2FnZToKICAgICAgICB3b3JrZXIgPSBTb3VuZFdvcmtlcigi"
    "YWxlcnQiKQogICAgICAgIHdvcmtlci5zdGFydCgpCiAgICAgICAgIyB3b3JrZXIgY2xlYW5zIHVw"
    "IG9uIGl0cyBvd24g4oCUIG5vIHJlZmVyZW5jZSBuZWVkZWQKICAgICIiIgoKICAgIGRlZiBfX2lu"
    "aXRfXyhzZWxmLCBzb3VuZF9uYW1lOiBzdHIpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQog"
    "ICAgICAgIHNlbGYuX25hbWUgPSBzb3VuZF9uYW1lCiAgICAgICAgIyBBdXRvLWRlbGV0ZSB3aGVu"
    "IGRvbmUKICAgICAgICBzZWxmLmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5kZWxldGVMYXRlcikKCiAg"
    "ICBkZWYgcnVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBwbGF5X3Nv"
    "dW5kKHNlbGYuX25hbWUpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFz"
    "cwoKCiMg4pSA4pSAIEZBQ0UgVElNRVIgTUFOQUdFUiDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgRmFjZVRpbWVyTWFuYWdlcjoKICAg"
    "ICIiIgogICAgTWFuYWdlcyB0aGUgNjAtc2Vjb25kIGZhY2UgZGlzcGxheSB0aW1lci4KCiAgICBS"
    "dWxlczoKICAgIC0gQWZ0ZXIgc2VudGltZW50IGNsYXNzaWZpY2F0aW9uLCBmYWNlIGlzIGxvY2tl"
    "ZCBmb3IgNjAgc2Vjb25kcy4KICAgIC0gSWYgdXNlciBzZW5kcyBhIG5ldyBtZXNzYWdlIGR1cmlu"
    "ZyB0aGUgNjBzLCBmYWNlIGltbWVkaWF0ZWx5CiAgICAgIHN3aXRjaGVzIHRvICdhbGVydCcgKGxv"
    "Y2tlZCA9IEZhbHNlLCBuZXcgY3ljbGUgYmVnaW5zKS4KICAgIC0gQWZ0ZXIgNjBzIHdpdGggbm8g"
    "bmV3IGlucHV0LCByZXR1cm5zIHRvICduZXV0cmFsJy4KICAgIC0gTmV2ZXIgYmxvY2tzIGFueXRo"
    "aW5nLiBQdXJlIHRpbWVyICsgY2FsbGJhY2sgbG9naWMuCiAgICAiIiIKCiAgICBIT0xEX1NFQ09O"
    "RFMgPSA2MAoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBtaXJyb3I6ICJNaXJyb3JXaWRnZXQiLCBl"
    "bW90aW9uX2Jsb2NrOiAiRW1vdGlvbkJsb2NrIik6CiAgICAgICAgc2VsZi5fbWlycm9yICA9IG1p"
    "cnJvcgogICAgICAgIHNlbGYuX2Vtb3Rpb24gPSBlbW90aW9uX2Jsb2NrCiAgICAgICAgc2VsZi5f"
    "dGltZXIgICA9IFFUaW1lcigpCiAgICAgICAgc2VsZi5fdGltZXIuc2V0U2luZ2xlU2hvdChUcnVl"
    "KQogICAgICAgIHNlbGYuX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9yZXR1cm5fdG9fbmV1"
    "dHJhbCkKICAgICAgICBzZWxmLl9sb2NrZWQgID0gRmFsc2UKCiAgICBkZWYgc2V0X2ZhY2Uoc2Vs"
    "ZiwgZW1vdGlvbjogc3RyKSAtPiBOb25lOgogICAgICAgICIiIlNldCBmYWNlIGFuZCBzdGFydCB0"
    "aGUgNjAtc2Vjb25kIGhvbGQgdGltZXIuIiIiCiAgICAgICAgc2VsZi5fbG9ja2VkID0gVHJ1ZQog"
    "ICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZShlbW90aW9uKQogICAgICAgIHNlbGYuX2Vtb3Rp"
    "b24uYWRkRW1vdGlvbihlbW90aW9uKQogICAgICAgIHNlbGYuX3RpbWVyLnN0b3AoKQogICAgICAg"
    "IHNlbGYuX3RpbWVyLnN0YXJ0KHNlbGYuSE9MRF9TRUNPTkRTICogMTAwMCkKCiAgICBkZWYgaW50"
    "ZXJydXB0KHNlbGYsIG5ld19lbW90aW9uOiBzdHIgPSAiYWxlcnQiKSAtPiBOb25lOgogICAgICAg"
    "ICIiIgogICAgICAgIENhbGxlZCB3aGVuIHVzZXIgc2VuZHMgYSBuZXcgbWVzc2FnZS4KICAgICAg"
    "ICBJbnRlcnJ1cHRzIGFueSBydW5uaW5nIGhvbGQsIHNldHMgYWxlcnQgZmFjZSBpbW1lZGlhdGVs"
    "eS4KICAgICAgICAiIiIKICAgICAgICBzZWxmLl90aW1lci5zdG9wKCkKICAgICAgICBzZWxmLl9s"
    "b2NrZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX21pcnJvci5zZXRfZmFjZShuZXdfZW1vdGlvbikK"
    "ICAgICAgICBzZWxmLl9lbW90aW9uLmFkZEVtb3Rpb24obmV3X2Vtb3Rpb24pCgogICAgZGVmIF9y"
    "ZXR1cm5fdG9fbmV1dHJhbChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2xvY2tlZCA9IEZh"
    "bHNlCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKCJuZXV0cmFsIikKCiAgICBAcHJvcGVy"
    "dHkKICAgIGRlZiBpc19sb2NrZWQoc2VsZikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gc2VsZi5f"
    "bG9ja2VkCgoKIyDilIDilIAgR09PR0xFIFNFUlZJQ0UgQ0xBU1NFUyDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKIyBQb3J0ZWQgZnJvbSBHcmltVmVpbCBkZWNrLiBIYW5k"
    "bGVzIENhbGVuZGFyIGFuZCBEcml2ZS9Eb2NzIGF1dGggKyBBUEkuCiMgQ3JlZGVudGlhbHMgcGF0"
    "aDogY2ZnX3BhdGgoImdvb2dsZSIpIC8gImdvb2dsZV9jcmVkZW50aWFscy5qc29uIgojIFRva2Vu"
    "IHBhdGg6ICAgICAgIGNmZ19wYXRoKCJnb29nbGUiKSAvICJ0b2tlbi5qc29uIgoKY2xhc3MgR29v"
    "Z2xlQ2FsZW5kYXJTZXJ2aWNlOgogICAgZGVmIF9faW5pdF9fKHNlbGYsIGNyZWRlbnRpYWxzX3Bh"
    "dGg6IFBhdGgsIHRva2VuX3BhdGg6IFBhdGgpOgogICAgICAgIHNlbGYuY3JlZGVudGlhbHNfcGF0"
    "aCA9IGNyZWRlbnRpYWxzX3BhdGgKICAgICAgICBzZWxmLnRva2VuX3BhdGggPSB0b2tlbl9wYXRo"
    "CiAgICAgICAgc2VsZi5fc2VydmljZSA9IE5vbmUKCiAgICBkZWYgX3BlcnNpc3RfdG9rZW4oc2Vs"
    "ZiwgY3JlZHMpOgogICAgICAgIHNlbGYudG9rZW5fcGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1U"
    "cnVlLCBleGlzdF9vaz1UcnVlKQogICAgICAgIHNlbGYudG9rZW5fcGF0aC53cml0ZV90ZXh0KGNy"
    "ZWRzLnRvX2pzb24oKSwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBkZWYgX2J1aWxkX3NlcnZpY2Uo"
    "c2VsZik6CiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVCVUddIENyZWRlbnRpYWxzIHBhdGg6IHtz"
    "ZWxmLmNyZWRlbnRpYWxzX3BhdGh9IikKICAgICAgICBwcmludChmIltHQ2FsXVtERUJVR10gVG9r"
    "ZW4gcGF0aDoge3NlbGYudG9rZW5fcGF0aH0iKQogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVH"
    "XSBDcmVkZW50aWFscyBmaWxlIGV4aXN0czoge3NlbGYuY3JlZGVudGlhbHNfcGF0aC5leGlzdHMo"
    "KX0iKQogICAgICAgIHByaW50KGYiW0dDYWxdW0RFQlVHXSBUb2tlbiBmaWxlIGV4aXN0czoge3Nl"
    "bGYudG9rZW5fcGF0aC5leGlzdHMoKX0iKQoKICAgICAgICBpZiBub3QgR09PR0xFX0FQSV9PSzoK"
    "ICAgICAgICAgICAgZGV0YWlsID0gR09PR0xFX0lNUE9SVF9FUlJPUiBvciAidW5rbm93biBJbXBv"
    "cnRFcnJvciIKICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKGYiTWlzc2luZyBHb29nbGUg"
    "Q2FsZW5kYXIgUHl0aG9uIGRlcGVuZGVuY3k6IHtkZXRhaWx9IikKICAgICAgICBpZiBub3Qgc2Vs"
    "Zi5jcmVkZW50aWFsc19wYXRoLmV4aXN0cygpOgogICAgICAgICAgICByYWlzZSBGaWxlTm90Rm91"
    "bmRFcnJvcigKICAgICAgICAgICAgICAgIGYiR29vZ2xlIGNyZWRlbnRpYWxzL2F1dGggY29uZmln"
    "dXJhdGlvbiBub3QgZm91bmQ6IHtzZWxmLmNyZWRlbnRpYWxzX3BhdGh9IgogICAgICAgICAgICAp"
    "CgogICAgICAgIGNyZWRzID0gTm9uZQogICAgICAgIGxpbmtfZXN0YWJsaXNoZWQgPSBGYWxzZQog"
    "ICAgICAgIGlmIHNlbGYudG9rZW5fcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgY3JlZHMgPSBH"
    "b29nbGVDcmVkZW50aWFscy5mcm9tX2F1dGhvcml6ZWRfdXNlcl9maWxlKHN0cihzZWxmLnRva2Vu"
    "X3BhdGgpLCBHT09HTEVfU0NPUEVTKQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3JlZHMudmFsaWQg"
    "YW5kIG5vdCBjcmVkcy5oYXNfc2NvcGVzKEdPT0dMRV9TQ09QRVMpOgogICAgICAgICAgICByYWlz"
    "ZSBSdW50aW1lRXJyb3IoR09PR0xFX1NDT1BFX1JFQVVUSF9NU0cpCgogICAgICAgIGlmIGNyZWRz"
    "IGFuZCBjcmVkcy5leHBpcmVkIGFuZCBjcmVkcy5yZWZyZXNoX3Rva2VuOgogICAgICAgICAgICBw"
    "cmludCgiW0dDYWxdW0RFQlVHXSBSZWZyZXNoaW5nIGV4cGlyZWQgR29vZ2xlIHRva2VuLiIpCiAg"
    "ICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGNyZWRzLnJlZnJlc2goR29vZ2xlQXV0aFJl"
    "cXVlc3QoKSkKICAgICAgICAgICAgICAgIHNlbGYuX3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgICAg"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICByYWlzZSBSdW50"
    "aW1lRXJyb3IoCiAgICAgICAgICAgICAgICAgICAgZiJHb29nbGUgdG9rZW4gcmVmcmVzaCBmYWls"
    "ZWQgYWZ0ZXIgc2NvcGUgZXhwYW5zaW9uOiB7ZXh9LiB7R09PR0xFX1NDT1BFX1JFQVVUSF9NU0d9"
    "IgogICAgICAgICAgICAgICAgKSBmcm9tIGV4CgogICAgICAgIGlmIG5vdCBjcmVkcyBvciBub3Qg"
    "Y3JlZHMudmFsaWQ6CiAgICAgICAgICAgIHByaW50KCJbR0NhbF1bREVCVUddIFN0YXJ0aW5nIE9B"
    "dXRoIGZsb3cgZm9yIEdvb2dsZSBDYWxlbmRhci4iKQogICAgICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgICAgICBmbG93ID0gSW5zdGFsbGVkQXBwRmxvdy5mcm9tX2NsaWVudF9zZWNyZXRzX2ZpbGUo"
    "c3RyKHNlbGYuY3JlZGVudGlhbHNfcGF0aCksIEdPT0dMRV9TQ09QRVMpCiAgICAgICAgICAgICAg"
    "ICBjcmVkcyA9IGZsb3cucnVuX2xvY2FsX3NlcnZlcigKICAgICAgICAgICAgICAgICAgICBwb3J0"
    "PTAsCiAgICAgICAgICAgICAgICAgICAgb3Blbl9icm93c2VyPVRydWUsCiAgICAgICAgICAgICAg"
    "ICAgICAgYXV0aG9yaXphdGlvbl9wcm9tcHRfbWVzc2FnZT0oCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgICJPcGVuIHRoaXMgVVJMIGluIHlvdXIgYnJvd3NlciB0byBhdXRob3JpemUgdGhpcyBhcHBs"
    "aWNhdGlvbjpcbnt1cmx9IgogICAgICAgICAgICAgICAgICAgICksCiAgICAgICAgICAgICAgICAg"
    "ICAgc3VjY2Vzc19tZXNzYWdlPSJBdXRoZW50aWNhdGlvbiBjb21wbGV0ZS4gWW91IG1heSBjbG9z"
    "ZSB0aGlzIHdpbmRvdy4iLAogICAgICAgICAgICAgICAgKQogICAgICAgICAgICAgICAgaWYgbm90"
    "IGNyZWRzOgogICAgICAgICAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigiT0F1dGggZmxv"
    "dyByZXR1cm5lZCBubyBjcmVkZW50aWFscyBvYmplY3QuIikKICAgICAgICAgICAgICAgIHNlbGYu"
    "X3BlcnNpc3RfdG9rZW4oY3JlZHMpCiAgICAgICAgICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVH"
    "XSB0b2tlbi5qc29uIHdyaXR0ZW4gc3VjY2Vzc2Z1bGx5LiIpCiAgICAgICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgICAgICBwcmludChmIltHQ2FsXVtFUlJPUl0gT0F1"
    "dGggZmxvdyBmYWlsZWQ6IHt0eXBlKGV4KS5fX25hbWVfX306IHtleH0iKQogICAgICAgICAgICAg"
    "ICAgcmFpc2UKICAgICAgICAgICAgbGlua19lc3RhYmxpc2hlZCA9IFRydWUKCiAgICAgICAgc2Vs"
    "Zi5fc2VydmljZSA9IGdvb2dsZV9idWlsZCgiY2FsZW5kYXIiLCAidjMiLCBjcmVkZW50aWFscz1j"
    "cmVkcykKICAgICAgICBwcmludCgiW0dDYWxdW0RFQlVHXSBBdXRoZW50aWNhdGVkIEdvb2dsZSBD"
    "YWxlbmRhciBzZXJ2aWNlIGNyZWF0ZWQgc3VjY2Vzc2Z1bGx5LiIpCiAgICAgICAgcmV0dXJuIGxp"
    "bmtfZXN0YWJsaXNoZWQKCiAgICBkZWYgX2dldF9nb29nbGVfZXZlbnRfdGltZXpvbmUoc2VsZikg"
    "LT4gc3RyOgogICAgICAgIGxvY2FsX3R6aW5mbyA9IGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUo"
    "KS50emluZm8KICAgICAgICBjYW5kaWRhdGVzID0gW10KICAgICAgICBpZiBsb2NhbF90emluZm8g"
    "aXMgbm90IE5vbmU6CiAgICAgICAgICAgIGNhbmRpZGF0ZXMuZXh0ZW5kKFsKICAgICAgICAgICAg"
    "ICAgIGdldGF0dHIobG9jYWxfdHppbmZvLCAia2V5IiwgTm9uZSksCiAgICAgICAgICAgICAgICBn"
    "ZXRhdHRyKGxvY2FsX3R6aW5mbywgInpvbmUiLCBOb25lKSwKICAgICAgICAgICAgICAgIHN0cihs"
    "b2NhbF90emluZm8pLAogICAgICAgICAgICAgICAgbG9jYWxfdHppbmZvLnR6bmFtZShkYXRldGlt"
    "ZS5ub3coKSksCiAgICAgICAgICAgIF0pCgogICAgICAgIGVudl90eiA9IG9zLmVudmlyb24uZ2V0"
    "KCJUWiIpCiAgICAgICAgaWYgZW52X3R6OgogICAgICAgICAgICBjYW5kaWRhdGVzLmFwcGVuZChl"
    "bnZfdHopCgogICAgICAgIGZvciBjYW5kaWRhdGUgaW4gY2FuZGlkYXRlczoKICAgICAgICAgICAg"
    "aWYgbm90IGNhbmRpZGF0ZToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIG1h"
    "cHBlZCA9IFdJTkRPV1NfVFpfVE9fSUFOQS5nZXQoY2FuZGlkYXRlLCBjYW5kaWRhdGUpCiAgICAg"
    "ICAgICAgIGlmICIvIiBpbiBtYXBwZWQ6CiAgICAgICAgICAgICAgICByZXR1cm4gbWFwcGVkCgog"
    "ICAgICAgIHByaW50KAogICAgICAgICAgICAiW0dDYWxdW1dBUk5dIFVuYWJsZSB0byByZXNvbHZl"
    "IGxvY2FsIElBTkEgdGltZXpvbmUuICIKICAgICAgICAgICAgZiJGYWxsaW5nIGJhY2sgdG8ge0RF"
    "RkFVTFRfR09PR0xFX0lBTkFfVElNRVpPTkV9LiIKICAgICAgICApCiAgICAgICAgcmV0dXJuIERF"
    "RkFVTFRfR09PR0xFX0lBTkFfVElNRVpPTkUKCiAgICBkZWYgY3JlYXRlX2V2ZW50X2Zvcl90YXNr"
    "KHNlbGYsIHRhc2s6IGRpY3QpOgogICAgICAgIGR1ZV9hdCA9IHBhcnNlX2lzb19mb3JfY29tcGFy"
    "ZSh0YXNrLmdldCgiZHVlX2F0Iikgb3IgdGFzay5nZXQoImR1ZSIpLCBjb250ZXh0PSJnb29nbGVf"
    "Y3JlYXRlX2V2ZW50X2R1ZSIpCiAgICAgICAgaWYgbm90IGR1ZV9hdDoKICAgICAgICAgICAgcmFp"
    "c2UgVmFsdWVFcnJvcigiVGFzayBkdWUgdGltZSBpcyBtaXNzaW5nIG9yIGludmFsaWQuIikKCiAg"
    "ICAgICAgbGlua19lc3RhYmxpc2hlZCA9IEZhbHNlCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBp"
    "cyBOb25lOgogICAgICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gc2VsZi5fYnVpbGRfc2Vydmlj"
    "ZSgpCgogICAgICAgIGR1ZV9sb2NhbCA9IG5vcm1hbGl6ZV9kYXRldGltZV9mb3JfY29tcGFyZShk"
    "dWVfYXQsIGNvbnRleHQ9Imdvb2dsZV9jcmVhdGVfZXZlbnRfZHVlX2xvY2FsIikKICAgICAgICBz"
    "dGFydF9kdCA9IGR1ZV9sb2NhbC5yZXBsYWNlKG1pY3Jvc2Vjb25kPTAsIHR6aW5mbz1Ob25lKQog"
    "ICAgICAgIGVuZF9kdCA9IHN0YXJ0X2R0ICsgdGltZWRlbHRhKG1pbnV0ZXM9MzApCiAgICAgICAg"
    "dHpfbmFtZSA9IHNlbGYuX2dldF9nb29nbGVfZXZlbnRfdGltZXpvbmUoKQoKICAgICAgICBldmVu"
    "dF9wYXlsb2FkID0gewogICAgICAgICAgICAic3VtbWFyeSI6ICh0YXNrLmdldCgidGV4dCIpIG9y"
    "ICJSZW1pbmRlciIpLnN0cmlwKCksCiAgICAgICAgICAgICJzdGFydCI6IHsiZGF0ZVRpbWUiOiBz"
    "dGFydF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRpbWVab25lIjogdHpfbmFt"
    "ZX0sCiAgICAgICAgICAgICJlbmQiOiB7ImRhdGVUaW1lIjogZW5kX2R0Lmlzb2Zvcm1hdCh0aW1l"
    "c3BlYz0ic2Vjb25kcyIpLCAidGltZVpvbmUiOiB0el9uYW1lfSwKICAgICAgICB9CiAgICAgICAg"
    "dGFyZ2V0X2NhbGVuZGFyX2lkID0gInByaW1hcnkiCiAgICAgICAgcHJpbnQoZiJbR0NhbF1bREVC"
    "VUddIFRhcmdldCBjYWxlbmRhciBJRDoge3RhcmdldF9jYWxlbmRhcl9pZH0iKQogICAgICAgIHBy"
    "aW50KAogICAgICAgICAgICAiW0dDYWxdW0RFQlVHXSBFdmVudCBwYXlsb2FkIGJlZm9yZSBpbnNl"
    "cnQ6ICIKICAgICAgICAgICAgZiJ0aXRsZT0ne2V2ZW50X3BheWxvYWQuZ2V0KCdzdW1tYXJ5Jyl9"
    "JywgIgogICAgICAgICAgICBmInN0YXJ0LmRhdGVUaW1lPSd7ZXZlbnRfcGF5bG9hZC5nZXQoJ3N0"
    "YXJ0Jywge30pLmdldCgnZGF0ZVRpbWUnKX0nLCAiCiAgICAgICAgICAgIGYic3RhcnQudGltZVpv"
    "bmU9J3tldmVudF9wYXlsb2FkLmdldCgnc3RhcnQnLCB7fSkuZ2V0KCd0aW1lWm9uZScpfScsICIK"
    "ICAgICAgICAgICAgZiJlbmQuZGF0ZVRpbWU9J3tldmVudF9wYXlsb2FkLmdldCgnZW5kJywge30p"
    "LmdldCgnZGF0ZVRpbWUnKX0nLCAiCiAgICAgICAgICAgIGYiZW5kLnRpbWVab25lPSd7ZXZlbnRf"
    "cGF5bG9hZC5nZXQoJ2VuZCcsIHt9KS5nZXQoJ3RpbWVab25lJyl9JyIKICAgICAgICApCiAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICBjcmVhdGVkID0gc2VsZi5fc2VydmljZS5ldmVudHMoKS5pbnNl"
    "cnQoY2FsZW5kYXJJZD10YXJnZXRfY2FsZW5kYXJfaWQsIGJvZHk9ZXZlbnRfcGF5bG9hZCkuZXhl"
    "Y3V0ZSgpCiAgICAgICAgICAgIHByaW50KCJbR0NhbF1bREVCVUddIEV2ZW50IGluc2VydCBjYWxs"
    "IHN1Y2NlZWRlZC4iKQogICAgICAgICAgICByZXR1cm4gY3JlYXRlZC5nZXQoImlkIiksIGxpbmtf"
    "ZXN0YWJsaXNoZWQKICAgICAgICBleGNlcHQgR29vZ2xlSHR0cEVycm9yIGFzIGFwaV9leDoKICAg"
    "ICAgICAgICAgYXBpX2RldGFpbCA9ICIiCiAgICAgICAgICAgIGlmIGhhc2F0dHIoYXBpX2V4LCAi"
    "Y29udGVudCIpIGFuZCBhcGlfZXguY29udGVudDoKICAgICAgICAgICAgICAgIHRyeToKICAgICAg"
    "ICAgICAgICAgICAgICBhcGlfZGV0YWlsID0gYXBpX2V4LmNvbnRlbnQuZGVjb2RlKCJ1dGYtOCIs"
    "IGVycm9ycz0icmVwbGFjZSIpCiAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgICAgICAgICAgICAgIGFwaV9kZXRhaWwgPSBzdHIoYXBpX2V4LmNvbnRlbnQpCiAgICAgICAg"
    "ICAgIGRldGFpbF9tc2cgPSBmIkdvb2dsZSBBUEkgZXJyb3I6IHthcGlfZXh9IgogICAgICAgICAg"
    "ICBpZiBhcGlfZGV0YWlsOgogICAgICAgICAgICAgICAgZGV0YWlsX21zZyA9IGYie2RldGFpbF9t"
    "c2d9IHwgQVBJIGJvZHk6IHthcGlfZGV0YWlsfSIKICAgICAgICAgICAgcHJpbnQoZiJbR0NhbF1b"
    "RVJST1JdIEV2ZW50IGluc2VydCBmYWlsZWQ6IHtkZXRhaWxfbXNnfSIpCiAgICAgICAgICAgIHJh"
    "aXNlIFJ1bnRpbWVFcnJvcihkZXRhaWxfbXNnKSBmcm9tIGFwaV9leAogICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHByaW50KGYiW0dDYWxdW0VSUk9SXSBFdmVudCBp"
    "bnNlcnQgZmFpbGVkIHdpdGggdW5leHBlY3RlZCBlcnJvcjoge2V4fSIpCiAgICAgICAgICAgIHJh"
    "aXNlCgogICAgZGVmIGNyZWF0ZV9ldmVudF93aXRoX3BheWxvYWQoc2VsZiwgZXZlbnRfcGF5bG9h"
    "ZDogZGljdCwgY2FsZW5kYXJfaWQ6IHN0ciA9ICJwcmltYXJ5Iik6CiAgICAgICAgaWYgbm90IGlz"
    "aW5zdGFuY2UoZXZlbnRfcGF5bG9hZCwgZGljdCk6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJy"
    "b3IoIkdvb2dsZSBldmVudCBwYXlsb2FkIG11c3QgYmUgYSBkaWN0aW9uYXJ5LiIpCiAgICAgICAg"
    "bGlua19lc3RhYmxpc2hlZCA9IEZhbHNlCiAgICAgICAgaWYgc2VsZi5fc2VydmljZSBpcyBOb25l"
    "OgogICAgICAgICAgICBsaW5rX2VzdGFibGlzaGVkID0gc2VsZi5fYnVpbGRfc2VydmljZSgpCiAg"
    "ICAgICAgY3JlYXRlZCA9IHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuaW5zZXJ0KGNhbGVuZGFySWQ9"
    "KGNhbGVuZGFyX2lkIG9yICJwcmltYXJ5IiksIGJvZHk9ZXZlbnRfcGF5bG9hZCkuZXhlY3V0ZSgp"
    "CiAgICAgICAgcmV0dXJuIGNyZWF0ZWQuZ2V0KCJpZCIpLCBsaW5rX2VzdGFibGlzaGVkCgogICAg"
    "ZGVmIGxpc3RfcHJpbWFyeV9ldmVudHMoc2VsZiwKICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICB0aW1lX21pbjogc3RyID0gTm9uZSwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICBzeW5j"
    "X3Rva2VuOiBzdHIgPSBOb25lLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIG1heF9yZXN1"
    "bHRzOiBpbnQgPSAyNTAwKToKICAgICAgICAiIiIKICAgICAgICBGZXRjaCBjYWxlbmRhciBldmVu"
    "dHMgd2l0aCBwYWdpbmF0aW9uIGFuZCBzeW5jVG9rZW4gc3VwcG9ydC4KICAgICAgICBSZXR1cm5z"
    "IChldmVudHNfbGlzdCwgbmV4dF9zeW5jX3Rva2VuKS4KCiAgICAgICAgc3luY190b2tlbiBtb2Rl"
    "OiBpbmNyZW1lbnRhbCDigJQgcmV0dXJucyBPTkxZIGNoYW5nZXMgKGFkZHMvZWRpdHMvY2FuY2Vs"
    "cykuCiAgICAgICAgdGltZV9taW4gbW9kZTogICBmdWxsIHN5bmMgZnJvbSBhIGRhdGUuCiAgICAg"
    "ICAgQm90aCB1c2Ugc2hvd0RlbGV0ZWQ9VHJ1ZSBzbyBjYW5jZWxsYXRpb25zIGNvbWUgdGhyb3Vn"
    "aC4KICAgICAgICAiIiIKICAgICAgICBpZiBzZWxmLl9zZXJ2aWNlIGlzIE5vbmU6CiAgICAgICAg"
    "ICAgIHNlbGYuX2J1aWxkX3NlcnZpY2UoKQoKICAgICAgICBpZiBzeW5jX3Rva2VuOgogICAgICAg"
    "ICAgICBxdWVyeSA9IHsKICAgICAgICAgICAgICAgICJjYWxlbmRhcklkIjogInByaW1hcnkiLAog"
    "ICAgICAgICAgICAgICAgInNpbmdsZUV2ZW50cyI6IFRydWUsCiAgICAgICAgICAgICAgICAic2hv"
    "d0RlbGV0ZWQiOiBUcnVlLAogICAgICAgICAgICAgICAgInN5bmNUb2tlbiI6IHN5bmNfdG9rZW4s"
    "CiAgICAgICAgICAgIH0KICAgICAgICBlbHNlOgogICAgICAgICAgICBxdWVyeSA9IHsKICAgICAg"
    "ICAgICAgICAgICJjYWxlbmRhcklkIjogInByaW1hcnkiLAogICAgICAgICAgICAgICAgInNpbmds"
    "ZUV2ZW50cyI6IFRydWUsCiAgICAgICAgICAgICAgICAic2hvd0RlbGV0ZWQiOiBUcnVlLAogICAg"
    "ICAgICAgICAgICAgIm1heFJlc3VsdHMiOiAyNTAsCiAgICAgICAgICAgICAgICAib3JkZXJCeSI6"
    "ICJzdGFydFRpbWUiLAogICAgICAgICAgICB9CiAgICAgICAgICAgIGlmIHRpbWVfbWluOgogICAg"
    "ICAgICAgICAgICAgcXVlcnlbInRpbWVNaW4iXSA9IHRpbWVfbWluCgogICAgICAgIGFsbF9ldmVu"
    "dHMgPSBbXQogICAgICAgIG5leHRfc3luY190b2tlbiA9IE5vbmUKICAgICAgICB3aGlsZSBUcnVl"
    "OgogICAgICAgICAgICByZXNwb25zZSA9IHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkubGlzdCgqKnF1"
    "ZXJ5KS5leGVjdXRlKCkKICAgICAgICAgICAgYWxsX2V2ZW50cy5leHRlbmQocmVzcG9uc2UuZ2V0"
    "KCJpdGVtcyIsIFtdKSkKICAgICAgICAgICAgbmV4dF9zeW5jX3Rva2VuID0gcmVzcG9uc2UuZ2V0"
    "KCJuZXh0U3luY1Rva2VuIikKICAgICAgICAgICAgcGFnZV90b2tlbiA9IHJlc3BvbnNlLmdldCgi"
    "bmV4dFBhZ2VUb2tlbiIpCiAgICAgICAgICAgIGlmIG5vdCBwYWdlX3Rva2VuOgogICAgICAgICAg"
    "ICAgICAgYnJlYWsKICAgICAgICAgICAgcXVlcnkucG9wKCJzeW5jVG9rZW4iLCBOb25lKQogICAg"
    "ICAgICAgICBxdWVyeVsicGFnZVRva2VuIl0gPSBwYWdlX3Rva2VuCgogICAgICAgIHJldHVybiBh"
    "bGxfZXZlbnRzLCBuZXh0X3N5bmNfdG9rZW4KCiAgICBkZWYgZ2V0X2V2ZW50KHNlbGYsIGdvb2ds"
    "ZV9ldmVudF9pZDogc3RyKToKICAgICAgICBpZiBub3QgZ29vZ2xlX2V2ZW50X2lkOgogICAgICAg"
    "ICAgICByZXR1cm4gTm9uZQogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAg"
    "ICAgICAgc2VsZi5fYnVpbGRfc2VydmljZSgpCiAgICAgICAgdHJ5OgogICAgICAgICAgICByZXR1"
    "cm4gc2VsZi5fc2VydmljZS5ldmVudHMoKS5nZXQoY2FsZW5kYXJJZD0icHJpbWFyeSIsIGV2ZW50"
    "SWQ9Z29vZ2xlX2V2ZW50X2lkKS5leGVjdXRlKCkKICAgICAgICBleGNlcHQgR29vZ2xlSHR0cEVy"
    "cm9yIGFzIGFwaV9leDoKICAgICAgICAgICAgY29kZSA9IGdldGF0dHIoZ2V0YXR0cihhcGlfZXgs"
    "ICJyZXNwIiwgTm9uZSksICJzdGF0dXMiLCBOb25lKQogICAgICAgICAgICBpZiBjb2RlIGluICg0"
    "MDQsIDQxMCk6CiAgICAgICAgICAgICAgICByZXR1cm4gTm9uZQogICAgICAgICAgICByYWlzZQoK"
    "ICAgIGRlZiBkZWxldGVfZXZlbnRfZm9yX3Rhc2soc2VsZiwgZ29vZ2xlX2V2ZW50X2lkOiBzdHIp"
    "OgogICAgICAgIGlmIG5vdCBnb29nbGVfZXZlbnRfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVl"
    "RXJyb3IoIkdvb2dsZSBldmVudCBpZCBpcyBtaXNzaW5nOyBjYW5ub3QgZGVsZXRlIGV2ZW50LiIp"
    "CgogICAgICAgIGlmIHNlbGYuX3NlcnZpY2UgaXMgTm9uZToKICAgICAgICAgICAgc2VsZi5fYnVp"
    "bGRfc2VydmljZSgpCgogICAgICAgIHRhcmdldF9jYWxlbmRhcl9pZCA9ICJwcmltYXJ5IgogICAg"
    "ICAgIHNlbGYuX3NlcnZpY2UuZXZlbnRzKCkuZGVsZXRlKGNhbGVuZGFySWQ9dGFyZ2V0X2NhbGVu"
    "ZGFyX2lkLCBldmVudElkPWdvb2dsZV9ldmVudF9pZCkuZXhlY3V0ZSgpCgoKY2xhc3MgR29vZ2xl"
    "RG9jc0RyaXZlU2VydmljZToKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBjcmVkZW50aWFsc19wYXRo"
    "OiBQYXRoLCB0b2tlbl9wYXRoOiBQYXRoLCBsb2dnZXI9Tm9uZSk6CiAgICAgICAgc2VsZi5jcmVk"
    "ZW50aWFsc19wYXRoID0gY3JlZGVudGlhbHNfcGF0aAogICAgICAgIHNlbGYudG9rZW5fcGF0aCA9"
    "IHRva2VuX3BhdGgKICAgICAgICBzZWxmLl9kcml2ZV9zZXJ2aWNlID0gTm9uZQogICAgICAgIHNl"
    "bGYuX2RvY3Nfc2VydmljZSA9IE5vbmUKICAgICAgICBzZWxmLl9sb2dnZXIgPSBsb2dnZXIKCiAg"
    "ICBkZWYgX2xvZyhzZWxmLCBtZXNzYWdlOiBzdHIsIGxldmVsOiBzdHIgPSAiSU5GTyIpOgogICAg"
    "ICAgIGlmIGNhbGxhYmxlKHNlbGYuX2xvZ2dlcik6CiAgICAgICAgICAgIHNlbGYuX2xvZ2dlciht"
    "ZXNzYWdlLCBsZXZlbD1sZXZlbCkKCiAgICBkZWYgX3BlcnNpc3RfdG9rZW4oc2VsZiwgY3JlZHMp"
    "OgogICAgICAgIHNlbGYudG9rZW5fcGF0aC5wYXJlbnQubWtkaXIocGFyZW50cz1UcnVlLCBleGlz"
    "dF9vaz1UcnVlKQogICAgICAgIHNlbGYudG9rZW5fcGF0aC53cml0ZV90ZXh0KGNyZWRzLnRvX2pz"
    "b24oKSwgZW5jb2Rpbmc9InV0Zi04IikKCiAgICBkZWYgX2F1dGhlbnRpY2F0ZShzZWxmKToKICAg"
    "ICAgICBzZWxmLl9sb2coIkRyaXZlIGF1dGggc3RhcnQuIiwgbGV2ZWw9IklORk8iKQogICAgICAg"
    "IHNlbGYuX2xvZygiRG9jcyBhdXRoIHN0YXJ0LiIsIGxldmVsPSJJTkZPIikKCiAgICAgICAgaWYg"
    "bm90IEdPT0dMRV9BUElfT0s6CiAgICAgICAgICAgIGRldGFpbCA9IEdPT0dMRV9JTVBPUlRfRVJS"
    "T1Igb3IgInVua25vd24gSW1wb3J0RXJyb3IiCiAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJv"
    "cihmIk1pc3NpbmcgR29vZ2xlIFB5dGhvbiBkZXBlbmRlbmN5OiB7ZGV0YWlsfSIpCiAgICAgICAg"
    "aWYgbm90IHNlbGYuY3JlZGVudGlhbHNfcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgcmFpc2Ug"
    "RmlsZU5vdEZvdW5kRXJyb3IoCiAgICAgICAgICAgICAgICBmIkdvb2dsZSBjcmVkZW50aWFscy9h"
    "dXRoIGNvbmZpZ3VyYXRpb24gbm90IGZvdW5kOiB7c2VsZi5jcmVkZW50aWFsc19wYXRofSIKICAg"
    "ICAgICAgICAgKQoKICAgICAgICBjcmVkcyA9IE5vbmUKICAgICAgICBpZiBzZWxmLnRva2VuX3Bh"
    "dGguZXhpc3RzKCk6CiAgICAgICAgICAgIGNyZWRzID0gR29vZ2xlQ3JlZGVudGlhbHMuZnJvbV9h"
    "dXRob3JpemVkX3VzZXJfZmlsZShzdHIoc2VsZi50b2tlbl9wYXRoKSwgR09PR0xFX1NDT1BFUykK"
    "CiAgICAgICAgaWYgY3JlZHMgYW5kIGNyZWRzLnZhbGlkIGFuZCBub3QgY3JlZHMuaGFzX3Njb3Bl"
    "cyhHT09HTEVfU0NPUEVTKToKICAgICAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKEdPT0dMRV9T"
    "Q09QRV9SRUFVVEhfTVNHKQoKICAgICAgICBpZiBjcmVkcyBhbmQgY3JlZHMuZXhwaXJlZCBhbmQg"
    "Y3JlZHMucmVmcmVzaF90b2tlbjoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgY3Jl"
    "ZHMucmVmcmVzaChHb29nbGVBdXRoUmVxdWVzdCgpKQogICAgICAgICAgICAgICAgc2VsZi5fcGVy"
    "c2lzdF90b2tlbihjcmVkcykKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleDoKICAg"
    "ICAgICAgICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcigKICAgICAgICAgICAgICAgICAgICBmIkdv"
    "b2dsZSB0b2tlbiByZWZyZXNoIGZhaWxlZCBhZnRlciBzY29wZSBleHBhbnNpb246IHtleH0uIHtH"
    "T09HTEVfU0NPUEVfUkVBVVRIX01TR30iCiAgICAgICAgICAgICAgICApIGZyb20gZXgKCiAgICAg"
    "ICAgaWYgbm90IGNyZWRzIG9yIG5vdCBjcmVkcy52YWxpZDoKICAgICAgICAgICAgc2VsZi5fbG9n"
    "KCJTdGFydGluZyBPQXV0aCBmbG93IGZvciBHb29nbGUgRHJpdmUvRG9jcy4iLCBsZXZlbD0iSU5G"
    "TyIpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGZsb3cgPSBJbnN0YWxsZWRBcHBG"
    "bG93LmZyb21fY2xpZW50X3NlY3JldHNfZmlsZShzdHIoc2VsZi5jcmVkZW50aWFsc19wYXRoKSwg"
    "R09PR0xFX1NDT1BFUykKICAgICAgICAgICAgICAgIGNyZWRzID0gZmxvdy5ydW5fbG9jYWxfc2Vy"
    "dmVyKAogICAgICAgICAgICAgICAgICAgIHBvcnQ9MCwKICAgICAgICAgICAgICAgICAgICBvcGVu"
    "X2Jyb3dzZXI9VHJ1ZSwKICAgICAgICAgICAgICAgICAgICBhdXRob3JpemF0aW9uX3Byb21wdF9t"
    "ZXNzYWdlPSgKICAgICAgICAgICAgICAgICAgICAgICAgIk9wZW4gdGhpcyBVUkwgaW4geW91ciBi"
    "cm93c2VyIHRvIGF1dGhvcml6ZSB0aGlzIGFwcGxpY2F0aW9uOlxue3VybH0iCiAgICAgICAgICAg"
    "ICAgICAgICAgKSwKICAgICAgICAgICAgICAgICAgICBzdWNjZXNzX21lc3NhZ2U9IkF1dGhlbnRp"
    "Y2F0aW9uIGNvbXBsZXRlLiBZb3UgbWF5IGNsb3NlIHRoaXMgd2luZG93LiIsCiAgICAgICAgICAg"
    "ICAgICApCiAgICAgICAgICAgICAgICBpZiBub3QgY3JlZHM6CiAgICAgICAgICAgICAgICAgICAg"
    "cmFpc2UgUnVudGltZUVycm9yKCJPQXV0aCBmbG93IHJldHVybmVkIG5vIGNyZWRlbnRpYWxzIG9i"
    "amVjdC4iKQogICAgICAgICAgICAgICAgc2VsZi5fcGVyc2lzdF90b2tlbihjcmVkcykKICAgICAg"
    "ICAgICAgICAgIHNlbGYuX2xvZygiW0dDYWxdW0RFQlVHXSB0b2tlbi5qc29uIHdyaXR0ZW4gc3Vj"
    "Y2Vzc2Z1bGx5LiIsIGxldmVsPSJJTkZPIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBh"
    "cyBleDoKICAgICAgICAgICAgICAgIHNlbGYuX2xvZyhmIk9BdXRoIGZsb3cgZmFpbGVkOiB7dHlw"
    "ZShleCkuX19uYW1lX199OiB7ZXh9IiwgbGV2ZWw9IkVSUk9SIikKICAgICAgICAgICAgICAgIHJh"
    "aXNlCgogICAgICAgIHJldHVybiBjcmVkcwoKICAgIGRlZiBlbnN1cmVfc2VydmljZXMoc2VsZik6"
    "CiAgICAgICAgaWYgc2VsZi5fZHJpdmVfc2VydmljZSBpcyBub3QgTm9uZSBhbmQgc2VsZi5fZG9j"
    "c19zZXJ2aWNlIGlzIG5vdCBOb25lOgogICAgICAgICAgICByZXR1cm4KICAgICAgICB0cnk6CiAg"
    "ICAgICAgICAgIGNyZWRzID0gc2VsZi5fYXV0aGVudGljYXRlKCkKICAgICAgICAgICAgc2VsZi5f"
    "ZHJpdmVfc2VydmljZSA9IGdvb2dsZV9idWlsZCgiZHJpdmUiLCAidjMiLCBjcmVkZW50aWFscz1j"
    "cmVkcykKICAgICAgICAgICAgc2VsZi5fZG9jc19zZXJ2aWNlID0gZ29vZ2xlX2J1aWxkKCJkb2Nz"
    "IiwgInYxIiwgY3JlZGVudGlhbHM9Y3JlZHMpCiAgICAgICAgICAgIHNlbGYuX2xvZygiRHJpdmUg"
    "YXV0aCBzdWNjZXNzLiIsIGxldmVsPSJJTkZPIikKICAgICAgICAgICAgc2VsZi5fbG9nKCJEb2Nz"
    "IGF1dGggc3VjY2Vzcy4iLCBsZXZlbD0iSU5GTyIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBh"
    "cyBleDoKICAgICAgICAgICAgc2VsZi5fbG9nKGYiRHJpdmUgYXV0aCBmYWlsdXJlOiB7ZXh9Iiwg"
    "bGV2ZWw9IkVSUk9SIikKICAgICAgICAgICAgc2VsZi5fbG9nKGYiRG9jcyBhdXRoIGZhaWx1cmU6"
    "IHtleH0iLCBsZXZlbD0iRVJST1IiKQogICAgICAgICAgICByYWlzZQoKICAgIGRlZiBsaXN0X2Zv"
    "bGRlcl9pdGVtcyhzZWxmLCBmb2xkZXJfaWQ6IHN0ciA9ICJyb290IiwgcGFnZV9zaXplOiBpbnQg"
    "PSAxMDApOgogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBzYWZlX2ZvbGRl"
    "cl9pZCA9IChmb2xkZXJfaWQgb3IgInJvb3QiKS5zdHJpcCgpIG9yICJyb290IgogICAgICAgIHNl"
    "bGYuX2xvZyhmIkRyaXZlIGZpbGUgbGlzdCBmZXRjaCBzdGFydGVkLiBmb2xkZXJfaWQ9e3NhZmVf"
    "Zm9sZGVyX2lkfSIsIGxldmVsPSJJTkZPIikKICAgICAgICByZXNwb25zZSA9IHNlbGYuX2RyaXZl"
    "X3NlcnZpY2UuZmlsZXMoKS5saXN0KAogICAgICAgICAgICBxPWYiJ3tzYWZlX2ZvbGRlcl9pZH0n"
    "IGluIHBhcmVudHMgYW5kIHRyYXNoZWQ9ZmFsc2UiLAogICAgICAgICAgICBwYWdlU2l6ZT1tYXgo"
    "MSwgbWluKGludChwYWdlX3NpemUgb3IgMTAwKSwgMjAwKSksCiAgICAgICAgICAgIG9yZGVyQnk9"
    "ImZvbGRlcixuYW1lLG1vZGlmaWVkVGltZSBkZXNjIiwKICAgICAgICAgICAgZmllbGRzPSgKICAg"
    "ICAgICAgICAgICAgICJmaWxlcygiCiAgICAgICAgICAgICAgICAiaWQsbmFtZSxtaW1lVHlwZSxt"
    "b2RpZmllZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyxzaXplLCIKICAgICAgICAgICAgICAgICJs"
    "YXN0TW9kaWZ5aW5nVXNlcihkaXNwbGF5TmFtZSxlbWFpbEFkZHJlc3MpIgogICAgICAgICAgICAg"
    "ICAgIikiCiAgICAgICAgICAgICksCiAgICAgICAgKS5leGVjdXRlKCkKICAgICAgICBmaWxlcyA9"
    "IHJlc3BvbnNlLmdldCgiZmlsZXMiLCBbXSkKICAgICAgICBmb3IgaXRlbSBpbiBmaWxlczoKICAg"
    "ICAgICAgICAgbWltZSA9IChpdGVtLmdldCgibWltZVR5cGUiKSBvciAiIikuc3RyaXAoKQogICAg"
    "ICAgICAgICBpdGVtWyJpc19mb2xkZXIiXSA9IG1pbWUgPT0gImFwcGxpY2F0aW9uL3ZuZC5nb29n"
    "bGUtYXBwcy5mb2xkZXIiCiAgICAgICAgICAgIGl0ZW1bImlzX2dvb2dsZV9kb2MiXSA9IG1pbWUg"
    "PT0gImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5kb2N1bWVudCIKICAgICAgICBzZWxmLl9s"
    "b2coZiJEcml2ZSBpdGVtcyByZXR1cm5lZDoge2xlbihmaWxlcyl9IGZvbGRlcl9pZD17c2FmZV9m"
    "b2xkZXJfaWR9IiwgbGV2ZWw9IklORk8iKQogICAgICAgIHJldHVybiBmaWxlcwoKICAgIGRlZiBn"
    "ZXRfZG9jX3ByZXZpZXcoc2VsZiwgZG9jX2lkOiBzdHIsIG1heF9jaGFyczogaW50ID0gMTgwMCk6"
    "CiAgICAgICAgaWYgbm90IGRvY19pZDoKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiRG9j"
    "dW1lbnQgaWQgaXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAg"
    "ICAgICAgZG9jID0gc2VsZi5fZG9jc19zZXJ2aWNlLmRvY3VtZW50cygpLmdldChkb2N1bWVudElk"
    "PWRvY19pZCkuZXhlY3V0ZSgpCiAgICAgICAgdGl0bGUgPSBkb2MuZ2V0KCJ0aXRsZSIpIG9yICJV"
    "bnRpdGxlZCIKICAgICAgICBib2R5ID0gZG9jLmdldCgiYm9keSIsIHt9KS5nZXQoImNvbnRlbnQi"
    "LCBbXSkKICAgICAgICBjaHVua3MgPSBbXQogICAgICAgIGZvciBibG9jayBpbiBib2R5OgogICAg"
    "ICAgICAgICBwYXJhZ3JhcGggPSBibG9jay5nZXQoInBhcmFncmFwaCIpCiAgICAgICAgICAgIGlm"
    "IG5vdCBwYXJhZ3JhcGg6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBlbGVt"
    "ZW50cyA9IHBhcmFncmFwaC5nZXQoImVsZW1lbnRzIiwgW10pCiAgICAgICAgICAgIGZvciBlbCBp"
    "biBlbGVtZW50czoKICAgICAgICAgICAgICAgIHJ1biA9IGVsLmdldCgidGV4dFJ1biIpCiAgICAg"
    "ICAgICAgICAgICBpZiBub3QgcnVuOgogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAg"
    "ICAgICAgICAgICB0ZXh0ID0gKHJ1bi5nZXQoImNvbnRlbnQiKSBvciAiIikucmVwbGFjZSgiXHgw"
    "YiIsICJcbiIpCiAgICAgICAgICAgICAgICBpZiB0ZXh0OgogICAgICAgICAgICAgICAgICAgIGNo"
    "dW5rcy5hcHBlbmQodGV4dCkKICAgICAgICBwYXJzZWQgPSAiIi5qb2luKGNodW5rcykuc3RyaXAo"
    "KQogICAgICAgIGlmIGxlbihwYXJzZWQpID4gbWF4X2NoYXJzOgogICAgICAgICAgICBwYXJzZWQg"
    "PSBwYXJzZWRbOm1heF9jaGFyc10ucnN0cmlwKCkgKyAi4oCmIgogICAgICAgIHJldHVybiB7CiAg"
    "ICAgICAgICAgICJ0aXRsZSI6IHRpdGxlLAogICAgICAgICAgICAiZG9jdW1lbnRfaWQiOiBkb2Nf"
    "aWQsCiAgICAgICAgICAgICJyZXZpc2lvbl9pZCI6IGRvYy5nZXQoInJldmlzaW9uSWQiKSwKICAg"
    "ICAgICAgICAgInByZXZpZXdfdGV4dCI6IHBhcnNlZCBvciAiW05vIHRleHQgY29udGVudCByZXR1"
    "cm5lZCBmcm9tIERvY3MgQVBJLl0iLAogICAgICAgIH0KCiAgICBkZWYgY3JlYXRlX2RvYyhzZWxm"
    "LCB0aXRsZTogc3RyID0gIk5ldyBHcmltVmVpbGUgUmVjb3JkIiwgcGFyZW50X2ZvbGRlcl9pZDog"
    "c3RyID0gInJvb3QiKToKICAgICAgICBzYWZlX3RpdGxlID0gKHRpdGxlIG9yICJOZXcgR3JpbVZl"
    "aWxlIFJlY29yZCIpLnN0cmlwKCkgb3IgIk5ldyBHcmltVmVpbGUgUmVjb3JkIgogICAgICAgIHNl"
    "bGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICBzYWZlX3BhcmVudF9pZCA9IChwYXJlbnRfZm9s"
    "ZGVyX2lkIG9yICJyb290Iikuc3RyaXAoKSBvciAicm9vdCIKICAgICAgICBjcmVhdGVkID0gc2Vs"
    "Zi5fZHJpdmVfc2VydmljZS5maWxlcygpLmNyZWF0ZSgKICAgICAgICAgICAgYm9keT17CiAgICAg"
    "ICAgICAgICAgICAibmFtZSI6IHNhZmVfdGl0bGUsCiAgICAgICAgICAgICAgICAibWltZVR5cGUi"
    "OiAiYXBwbGljYXRpb24vdm5kLmdvb2dsZS1hcHBzLmRvY3VtZW50IiwKICAgICAgICAgICAgICAg"
    "ICJwYXJlbnRzIjogW3NhZmVfcGFyZW50X2lkXSwKICAgICAgICAgICAgfSwKICAgICAgICAgICAg"
    "ZmllbGRzPSJpZCxuYW1lLG1pbWVUeXBlLG1vZGlmaWVkVGltZSx3ZWJWaWV3TGluayxwYXJlbnRz"
    "IiwKICAgICAgICApLmV4ZWN1dGUoKQogICAgICAgIGRvY19pZCA9IGNyZWF0ZWQuZ2V0KCJpZCIp"
    "CiAgICAgICAgbWV0YSA9IHNlbGYuZ2V0X2ZpbGVfbWV0YWRhdGEoZG9jX2lkKSBpZiBkb2NfaWQg"
    "ZWxzZSB7fQogICAgICAgIHJldHVybiB7CiAgICAgICAgICAgICJpZCI6IGRvY19pZCwKICAgICAg"
    "ICAgICAgIm5hbWUiOiBtZXRhLmdldCgibmFtZSIpIG9yIHNhZmVfdGl0bGUsCiAgICAgICAgICAg"
    "ICJtaW1lVHlwZSI6IG1ldGEuZ2V0KCJtaW1lVHlwZSIpIG9yICJhcHBsaWNhdGlvbi92bmQuZ29v"
    "Z2xlLWFwcHMuZG9jdW1lbnQiLAogICAgICAgICAgICAibW9kaWZpZWRUaW1lIjogbWV0YS5nZXQo"
    "Im1vZGlmaWVkVGltZSIpLAogICAgICAgICAgICAid2ViVmlld0xpbmsiOiBtZXRhLmdldCgid2Vi"
    "Vmlld0xpbmsiKSwKICAgICAgICAgICAgInBhcmVudHMiOiBtZXRhLmdldCgicGFyZW50cyIpIG9y"
    "IFtzYWZlX3BhcmVudF9pZF0sCiAgICAgICAgfQoKICAgIGRlZiBjcmVhdGVfZm9sZGVyKHNlbGYs"
    "IG5hbWU6IHN0ciA9ICJOZXcgRm9sZGVyIiwgcGFyZW50X2ZvbGRlcl9pZDogc3RyID0gInJvb3Qi"
    "KToKICAgICAgICBzYWZlX25hbWUgPSAobmFtZSBvciAiTmV3IEZvbGRlciIpLnN0cmlwKCkgb3Ig"
    "Ik5ldyBGb2xkZXIiCiAgICAgICAgc2FmZV9wYXJlbnRfaWQgPSAocGFyZW50X2ZvbGRlcl9pZCBv"
    "ciAicm9vdCIpLnN0cmlwKCkgb3IgInJvb3QiCiAgICAgICAgc2VsZi5lbnN1cmVfc2VydmljZXMo"
    "KQogICAgICAgIGNyZWF0ZWQgPSBzZWxmLl9kcml2ZV9zZXJ2aWNlLmZpbGVzKCkuY3JlYXRlKAog"
    "ICAgICAgICAgICBib2R5PXsKICAgICAgICAgICAgICAgICJuYW1lIjogc2FmZV9uYW1lLAogICAg"
    "ICAgICAgICAgICAgIm1pbWVUeXBlIjogImFwcGxpY2F0aW9uL3ZuZC5nb29nbGUtYXBwcy5mb2xk"
    "ZXIiLAogICAgICAgICAgICAgICAgInBhcmVudHMiOiBbc2FmZV9wYXJlbnRfaWRdLAogICAgICAg"
    "ICAgICB9LAogICAgICAgICAgICBmaWVsZHM9ImlkLG5hbWUsbWltZVR5cGUsbW9kaWZpZWRUaW1l"
    "LHdlYlZpZXdMaW5rLHBhcmVudHMiLAogICAgICAgICkuZXhlY3V0ZSgpCiAgICAgICAgcmV0dXJu"
    "IGNyZWF0ZWQKCiAgICBkZWYgZ2V0X2ZpbGVfbWV0YWRhdGEoc2VsZiwgZmlsZV9pZDogc3RyKToK"
    "ICAgICAgICBpZiBub3QgZmlsZV9pZDoKICAgICAgICAgICAgcmFpc2UgVmFsdWVFcnJvcigiRmls"
    "ZSBpZCBpcyByZXF1aXJlZC4iKQogICAgICAgIHNlbGYuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAg"
    "ICByZXR1cm4gc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmdldCgKICAgICAgICAgICAgZmls"
    "ZUlkPWZpbGVfaWQsCiAgICAgICAgICAgIGZpZWxkcz0iaWQsbmFtZSxtaW1lVHlwZSxtb2RpZmll"
    "ZFRpbWUsd2ViVmlld0xpbmsscGFyZW50cyxzaXplIiwKICAgICAgICApLmV4ZWN1dGUoKQoKICAg"
    "IGRlZiBnZXRfZG9jX21ldGFkYXRhKHNlbGYsIGRvY19pZDogc3RyKToKICAgICAgICByZXR1cm4g"
    "c2VsZi5nZXRfZmlsZV9tZXRhZGF0YShkb2NfaWQpCgogICAgZGVmIGRlbGV0ZV9pdGVtKHNlbGYs"
    "IGZpbGVfaWQ6IHN0cik6CiAgICAgICAgaWYgbm90IGZpbGVfaWQ6CiAgICAgICAgICAgIHJhaXNl"
    "IFZhbHVlRXJyb3IoIkZpbGUgaWQgaXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9z"
    "ZXJ2aWNlcygpCiAgICAgICAgc2VsZi5fZHJpdmVfc2VydmljZS5maWxlcygpLmRlbGV0ZShmaWxl"
    "SWQ9ZmlsZV9pZCkuZXhlY3V0ZSgpCgogICAgZGVmIGRlbGV0ZV9kb2Moc2VsZiwgZG9jX2lkOiBz"
    "dHIpOgogICAgICAgIHNlbGYuZGVsZXRlX2l0ZW0oZG9jX2lkKQoKICAgIGRlZiBleHBvcnRfZG9j"
    "X3RleHQoc2VsZiwgZG9jX2lkOiBzdHIpOgogICAgICAgIGlmIG5vdCBkb2NfaWQ6CiAgICAgICAg"
    "ICAgIHJhaXNlIFZhbHVlRXJyb3IoIkRvY3VtZW50IGlkIGlzIHJlcXVpcmVkLiIpCiAgICAgICAg"
    "c2VsZi5lbnN1cmVfc2VydmljZXMoKQogICAgICAgIHBheWxvYWQgPSBzZWxmLl9kcml2ZV9zZXJ2"
    "aWNlLmZpbGVzKCkuZXhwb3J0KAogICAgICAgICAgICBmaWxlSWQ9ZG9jX2lkLAogICAgICAgICAg"
    "ICBtaW1lVHlwZT0idGV4dC9wbGFpbiIsCiAgICAgICAgKS5leGVjdXRlKCkKICAgICAgICBpZiBp"
    "c2luc3RhbmNlKHBheWxvYWQsIGJ5dGVzKToKICAgICAgICAgICAgcmV0dXJuIHBheWxvYWQuZGVj"
    "b2RlKCJ1dGYtOCIsIGVycm9ycz0icmVwbGFjZSIpCiAgICAgICAgcmV0dXJuIHN0cihwYXlsb2Fk"
    "IG9yICIiKQoKICAgIGRlZiBkb3dubG9hZF9maWxlX2J5dGVzKHNlbGYsIGZpbGVfaWQ6IHN0cik6"
    "CiAgICAgICAgaWYgbm90IGZpbGVfaWQ6CiAgICAgICAgICAgIHJhaXNlIFZhbHVlRXJyb3IoIkZp"
    "bGUgaWQgaXMgcmVxdWlyZWQuIikKICAgICAgICBzZWxmLmVuc3VyZV9zZXJ2aWNlcygpCiAgICAg"
    "ICAgcmV0dXJuIHNlbGYuX2RyaXZlX3NlcnZpY2UuZmlsZXMoKS5nZXRfbWVkaWEoZmlsZUlkPWZp"
    "bGVfaWQpLmV4ZWN1dGUoKQoKCgoKIyDilIDilIAgUEFTUyAzIENPTVBMRVRFIOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAojIEFs"
    "bCB3b3JrZXIgdGhyZWFkcyBkZWZpbmVkLiBBbGwgZ2VuZXJhdGlvbiBpcyBzdHJlYW1pbmcuCiMg"
    "Tm8gYmxvY2tpbmcgY2FsbHMgb24gbWFpbiB0aHJlYWQgYW55d2hlcmUgaW4gdGhpcyBmaWxlLgoj"
    "CiMgTmV4dDogUGFzcyA0IOKAlCBNZW1vcnkgJiBTdG9yYWdlCiMgKE1lbW9yeU1hbmFnZXIsIFNl"
    "c3Npb25NYW5hZ2VyLCBMZXNzb25zTGVhcm5lZERCLCBUYXNrTWFuYWdlcikKCgojIOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgNDogTUVNT1JZICYgU1RPUkFHRQojCiMgU3lzdGVt"
    "cyBkZWZpbmVkIGhlcmU6CiMgICBEZXBlbmRlbmN5Q2hlY2tlciAgIOKAlCB2YWxpZGF0ZXMgYWxs"
    "IHJlcXVpcmVkIHBhY2thZ2VzIG9uIHN0YXJ0dXAKIyAgIE1lbW9yeU1hbmFnZXIgICAgICAg4oCU"
    "IEpTT05MIG1lbW9yeSByZWFkL3dyaXRlL3NlYXJjaAojICAgU2Vzc2lvbk1hbmFnZXIgICAgICDi"
    "gJQgYXV0by1zYXZlLCBsb2FkLCBjb250ZXh0IGluamVjdGlvbiwgc2Vzc2lvbiBpbmRleAojICAg"
    "TGVzc29uc0xlYXJuZWREQiAgICDigJQgTFNMIEZvcmJpZGRlbiBSdWxlc2V0ICsgY29kZSBsZXNz"
    "b25zIGtub3dsZWRnZSBiYXNlCiMgICBUYXNrTWFuYWdlciAgICAgICAgIOKAlCB0YXNrL3JlbWlu"
    "ZGVyIENSVUQsIGR1ZS1ldmVudCBkZXRlY3Rpb24KIyDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDi"
    "lZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAKCgojIOKUgOKUgCBERVBF"
    "TkRFTkNZIENIRUNLRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSACmNsYXNzIERlcGVuZGVuY3lDaGVja2VyOgogICAgIiIiCiAgICBWYWxpZGF0"
    "ZXMgYWxsIHJlcXVpcmVkIGFuZCBvcHRpb25hbCBwYWNrYWdlcyBvbiBzdGFydHVwLgogICAgUmV0"
    "dXJucyBhIGxpc3Qgb2Ygc3RhdHVzIG1lc3NhZ2VzIGZvciB0aGUgRGlhZ25vc3RpY3MgdGFiLgog"
    "ICAgU2hvd3MgYSBibG9ja2luZyBlcnJvciBkaWFsb2cgZm9yIGFueSBjcml0aWNhbCBtaXNzaW5n"
    "IGRlcGVuZGVuY3kuCiAgICAiIiIKCiAgICAjIChwYWNrYWdlX25hbWUsIGltcG9ydF9uYW1lLCBj"
    "cml0aWNhbCwgaW5zdGFsbF9oaW50KQogICAgUEFDS0FHRVMgPSBbCiAgICAgICAgKCJQeVNpZGU2"
    "IiwgICAgICAgICAgICAgICAgICAgIlB5U2lkZTYiLCAgICAgICAgICAgICAgVHJ1ZSwKICAgICAg"
    "ICAgInBpcCBpbnN0YWxsIFB5U2lkZTYiKSwKICAgICAgICAoImxvZ3VydSIsICAgICAgICAgICAg"
    "ICAgICAgICAibG9ndXJ1IiwgICAgICAgICAgICAgICBUcnVlLAogICAgICAgICAicGlwIGluc3Rh"
    "bGwgbG9ndXJ1IiksCiAgICAgICAgKCJhcHNjaGVkdWxlciIsICAgICAgICAgICAgICAgImFwc2No"
    "ZWR1bGVyIiwgICAgICAgICAgVHJ1ZSwKICAgICAgICAgInBpcCBpbnN0YWxsIGFwc2NoZWR1bGVy"
    "IiksCiAgICAgICAgKCJweWdhbWUiLCAgICAgICAgICAgICAgICAgICAgInB5Z2FtZSIsICAgICAg"
    "ICAgICAgICAgRmFsc2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCBweWdhbWUgIChuZWVkZWQgZm9y"
    "IHNvdW5kKSIpLAogICAgICAgICgicHl3aW4zMiIsICAgICAgICAgICAgICAgICAgICJ3aW4zMmNv"
    "bSIsICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcHl3aW4zMiAgKG5l"
    "ZWRlZCBmb3IgZGVza3RvcCBzaG9ydGN1dCkiKSwKICAgICAgICAoInBzdXRpbCIsICAgICAgICAg"
    "ICAgICAgICAgICAicHN1dGlsIiwgICAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAgInBpcCBp"
    "bnN0YWxsIHBzdXRpbCAgKG5lZWRlZCBmb3Igc3lzdGVtIG1vbml0b3JpbmcpIiksCiAgICAgICAg"
    "KCJyZXF1ZXN0cyIsICAgICAgICAgICAgICAgICAgInJlcXVlc3RzIiwgICAgICAgICAgICAgRmFs"
    "c2UsCiAgICAgICAgICJwaXAgaW5zdGFsbCByZXF1ZXN0cyIpLAogICAgICAgICgiZ29vZ2xlLWFw"
    "aS1weXRob24tY2xpZW50IiwgICJnb29nbGVhcGljbGllbnQiLCAgICAgIEZhbHNlLAogICAgICAg"
    "ICAicGlwIGluc3RhbGwgZ29vZ2xlLWFwaS1weXRob24tY2xpZW50IiksCiAgICAgICAgKCJnb29n"
    "bGUtYXV0aC1vYXV0aGxpYiIsICAgICAgImdvb2dsZV9hdXRoX29hdXRobGliIiwgRmFsc2UsCiAg"
    "ICAgICAgICJwaXAgaW5zdGFsbCBnb29nbGUtYXV0aC1vYXV0aGxpYiIpLAogICAgICAgICgiZ29v"
    "Z2xlLWF1dGgiLCAgICAgICAgICAgICAgICJnb29nbGUuYXV0aCIsICAgICAgICAgIEZhbHNlLAog"
    "ICAgICAgICAicGlwIGluc3RhbGwgZ29vZ2xlLWF1dGgiKSwKICAgICAgICAoInRvcmNoIiwgICAg"
    "ICAgICAgICAgICAgICAgICAidG9yY2giLCAgICAgICAgICAgICAgICBGYWxzZSwKICAgICAgICAg"
    "InBpcCBpbnN0YWxsIHRvcmNoICAob25seSBuZWVkZWQgZm9yIGxvY2FsIG1vZGVsKSIpLAogICAg"
    "ICAgICgidHJhbnNmb3JtZXJzIiwgICAgICAgICAgICAgICJ0cmFuc2Zvcm1lcnMiLCAgICAgICAg"
    "IEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgdHJhbnNmb3JtZXJzICAob25seSBuZWVkZWQg"
    "Zm9yIGxvY2FsIG1vZGVsKSIpLAogICAgICAgICgicHludm1sIiwgICAgICAgICAgICAgICAgICAg"
    "ICJweW52bWwiLCAgICAgICAgICAgICAgIEZhbHNlLAogICAgICAgICAicGlwIGluc3RhbGwgcHlu"
    "dm1sICAob25seSBuZWVkZWQgZm9yIE5WSURJQSBHUFUgbW9uaXRvcmluZykiKSwKICAgIF0KCiAg"
    "ICBAY2xhc3NtZXRob2QKICAgIGRlZiBjaGVjayhjbHMpIC0+IHR1cGxlW2xpc3Rbc3RyXSwgbGlz"
    "dFtzdHJdXToKICAgICAgICAiIiIKICAgICAgICBSZXR1cm5zIChtZXNzYWdlcywgY3JpdGljYWxf"
    "ZmFpbHVyZXMpLgogICAgICAgIG1lc3NhZ2VzOiBsaXN0IG9mICJbREVQU10gcGFja2FnZSDinJMv"
    "4pyXIOKAlCBub3RlIiBzdHJpbmdzCiAgICAgICAgY3JpdGljYWxfZmFpbHVyZXM6IGxpc3Qgb2Yg"
    "cGFja2FnZXMgdGhhdCBhcmUgY3JpdGljYWwgYW5kIG1pc3NpbmcKICAgICAgICAiIiIKICAgICAg"
    "ICBpbXBvcnQgaW1wb3J0bGliCiAgICAgICAgbWVzc2FnZXMgID0gW10KICAgICAgICBjcml0aWNh"
    "bCAgPSBbXQoKICAgICAgICBmb3IgcGtnX25hbWUsIGltcG9ydF9uYW1lLCBpc19jcml0aWNhbCwg"
    "aGludCBpbiBjbHMuUEFDS0FHRVM6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIGlt"
    "cG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9ydF9uYW1lKQogICAgICAgICAgICAgICAgbWVzc2Fn"
    "ZXMuYXBwZW5kKGYiW0RFUFNdIHtwa2dfbmFtZX0g4pyTIikKICAgICAgICAgICAgZXhjZXB0IElt"
    "cG9ydEVycm9yOgogICAgICAgICAgICAgICAgc3RhdHVzID0gIkNSSVRJQ0FMIiBpZiBpc19jcml0"
    "aWNhbCBlbHNlICJvcHRpb25hbCIKICAgICAgICAgICAgICAgIG1lc3NhZ2VzLmFwcGVuZCgKICAg"
    "ICAgICAgICAgICAgICAgICBmIltERVBTXSB7cGtnX25hbWV9IOKclyAoe3N0YXR1c30pIOKAlCB7"
    "aGludH0iCiAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICBpZiBpc19jcml0aWNhbDoK"
    "ICAgICAgICAgICAgICAgICAgICBjcml0aWNhbC5hcHBlbmQocGtnX25hbWUpCgogICAgICAgIHJl"
    "dHVybiBtZXNzYWdlcywgY3JpdGljYWwKCiAgICBAY2xhc3NtZXRob2QKICAgIGRlZiBjaGVja19v"
    "bGxhbWEoY2xzKSAtPiBzdHI6CiAgICAgICAgIiIiQ2hlY2sgaWYgT2xsYW1hIGlzIHJ1bm5pbmcu"
    "IFJldHVybnMgc3RhdHVzIHN0cmluZy4iIiIKICAgICAgICB0cnk6CiAgICAgICAgICAgIHJlcSAg"
    "PSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KCJodHRwOi8vbG9jYWxob3N0OjExNDM0L2FwaS90YWdz"
    "IikKICAgICAgICAgICAgcmVzcCA9IHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0"
    "PTIpCiAgICAgICAgICAgIGlmIHJlc3Auc3RhdHVzID09IDIwMDoKICAgICAgICAgICAgICAgIHJl"
    "dHVybiAiW0RFUFNdIE9sbGFtYSDinJMg4oCUIHJ1bm5pbmcgb24gbG9jYWxob3N0OjExNDM0Igog"
    "ICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKICAgICAgICByZXR1cm4g"
    "IltERVBTXSBPbGxhbWEg4pyXIOKAlCBub3QgcnVubmluZyAob25seSBuZWVkZWQgZm9yIE9sbGFt"
    "YSBtb2RlbCB0eXBlKSIKCgojIOKUgOKUgCBNRU1PUlkgTUFOQUdFUiDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3Mg"
    "TWVtb3J5TWFuYWdlcjoKICAgICIiIgogICAgSGFuZGxlcyBhbGwgSlNPTkwgbWVtb3J5IG9wZXJh"
    "dGlvbnMuCgogICAgRmlsZXMgbWFuYWdlZDoKICAgICAgICBtZW1vcmllcy9tZXNzYWdlcy5qc29u"
    "bCAgICAgICAgIOKAlCBldmVyeSBtZXNzYWdlLCB0aW1lc3RhbXBlZAogICAgICAgIG1lbW9yaWVz"
    "L21lbW9yaWVzLmpzb25sICAgICAgICAg4oCUIGV4dHJhY3RlZCBtZW1vcnkgcmVjb3JkcwogICAg"
    "ICAgIG1lbW9yaWVzL3N0YXRlLmpzb24gICAgICAgICAgICAg4oCUIGVudGl0eSBzdGF0ZQogICAg"
    "ICAgIG1lbW9yaWVzL2luZGV4Lmpzb24gICAgICAgICAgICAg4oCUIGNvdW50cyBhbmQgbWV0YWRh"
    "dGEKCiAgICBNZW1vcnkgcmVjb3JkcyBoYXZlIHR5cGUgaW5mZXJlbmNlLCBrZXl3b3JkIGV4dHJh"
    "Y3Rpb24sIHRhZyBnZW5lcmF0aW9uLAogICAgbmVhci1kdXBsaWNhdGUgZGV0ZWN0aW9uLCBhbmQg"
    "cmVsZXZhbmNlIHNjb3JpbmcgZm9yIGNvbnRleHQgaW5qZWN0aW9uLgogICAgIiIiCgogICAgZGVm"
    "IF9faW5pdF9fKHNlbGYpOgogICAgICAgIGJhc2UgICAgICAgICAgICAgPSBjZmdfcGF0aCgibWVt"
    "b3JpZXMiKQogICAgICAgIHNlbGYubWVzc2FnZXNfcCAgPSBiYXNlIC8gIm1lc3NhZ2VzLmpzb25s"
    "IgogICAgICAgIHNlbGYubWVtb3JpZXNfcCAgPSBiYXNlIC8gIm1lbW9yaWVzLmpzb25sIgogICAg"
    "ICAgIHNlbGYuc3RhdGVfcCAgICAgPSBiYXNlIC8gInN0YXRlLmpzb24iCiAgICAgICAgc2VsZi5p"
    "bmRleF9wICAgICA9IGJhc2UgLyAiaW5kZXguanNvbiIKCiAgICAjIOKUgOKUgCBTVEFURSDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAK"
    "ICAgIGRlZiBsb2FkX3N0YXRlKHNlbGYpIC0+IGRpY3Q6CiAgICAgICAgaWYgbm90IHNlbGYuc3Rh"
    "dGVfcC5leGlzdHMoKToKICAgICAgICAgICAgcmV0dXJuIHNlbGYuX2RlZmF1bHRfc3RhdGUoKQog"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgcmV0dXJuIGpzb24ubG9hZHMoc2VsZi5zdGF0ZV9wLnJl"
    "YWRfdGV4dChlbmNvZGluZz0idXRmLTgiKSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAg"
    "ICAgICAgICByZXR1cm4gc2VsZi5fZGVmYXVsdF9zdGF0ZSgpCgogICAgZGVmIHNhdmVfc3RhdGUo"
    "c2VsZiwgc3RhdGU6IGRpY3QpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5zdGF0ZV9wLndyaXRlX3Rl"
    "eHQoCiAgICAgICAgICAgIGpzb24uZHVtcHMoc3RhdGUsIGluZGVudD0yKSwgZW5jb2Rpbmc9InV0"
    "Zi04IgogICAgICAgICkKCiAgICBkZWYgX2RlZmF1bHRfc3RhdGUoc2VsZikgLT4gZGljdDoKICAg"
    "ICAgICByZXR1cm4gewogICAgICAgICAgICAicGVyc29uYV9uYW1lIjogICAgICAgICAgICAgREVD"
    "S19OQU1FLAogICAgICAgICAgICAiZGVja192ZXJzaW9uIjogICAgICAgICAgICAgQVBQX1ZFUlNJ"
    "T04sCiAgICAgICAgICAgICJzZXNzaW9uX2NvdW50IjogICAgICAgICAgICAwLAogICAgICAgICAg"
    "ICAibGFzdF9zdGFydHVwIjogICAgICAgICAgICAgTm9uZSwKICAgICAgICAgICAgImxhc3Rfc2h1"
    "dGRvd24iOiAgICAgICAgICAgIE5vbmUsCiAgICAgICAgICAgICJsYXN0X2FjdGl2ZSI6ICAgICAg"
    "ICAgICAgICBOb25lLAogICAgICAgICAgICAidG90YWxfbWVzc2FnZXMiOiAgICAgICAgICAgMCwK"
    "ICAgICAgICAgICAgInRvdGFsX21lbW9yaWVzIjogICAgICAgICAgIDAsCiAgICAgICAgICAgICJp"
    "bnRlcm5hbF9uYXJyYXRpdmUiOiAgICAgICB7fSwKICAgICAgICAgICAgInZhbXBpcmVfc3RhdGVf"
    "YXRfc2h1dGRvd24iOiJET1JNQU5UIiwKICAgICAgICB9CgogICAgIyDilIDilIAgTUVTU0FHRVMg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBk"
    "ZWYgYXBwZW5kX21lc3NhZ2Uoc2VsZiwgc2Vzc2lvbl9pZDogc3RyLCByb2xlOiBzdHIsCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgY29udGVudDogc3RyLCBlbW90aW9uOiBzdHIgPSAiIikgLT4gZGlj"
    "dDoKICAgICAgICByZWNvcmQgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgZiJtc2dfe3V1"
    "aWQudXVpZDQoKS5oZXhbOjEyXX0iLAogICAgICAgICAgICAidGltZXN0YW1wIjogIGxvY2FsX25v"
    "d19pc28oKSwKICAgICAgICAgICAgInNlc3Npb25faWQiOiBzZXNzaW9uX2lkLAogICAgICAgICAg"
    "ICAicGVyc29uYSI6ICAgIERFQ0tfTkFNRSwKICAgICAgICAgICAgInJvbGUiOiAgICAgICByb2xl"
    "LAogICAgICAgICAgICAiY29udGVudCI6ICAgIGNvbnRlbnQsCiAgICAgICAgICAgICJlbW90aW9u"
    "IjogICAgZW1vdGlvbiwKICAgICAgICB9CiAgICAgICAgYXBwZW5kX2pzb25sKHNlbGYubWVzc2Fn"
    "ZXNfcCwgcmVjb3JkKQogICAgICAgIHJldHVybiByZWNvcmQKCiAgICBkZWYgbG9hZF9yZWNlbnRf"
    "bWVzc2FnZXMoc2VsZiwgbGltaXQ6IGludCA9IDIwKSAtPiBsaXN0W2RpY3RdOgogICAgICAgIHJl"
    "dHVybiByZWFkX2pzb25sKHNlbGYubWVzc2FnZXNfcClbLWxpbWl0Ol0KCiAgICAjIOKUgOKUgCBN"
    "RU1PUklFUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKICAgIGRlZiBhcHBlbmRfbWVtb3J5KHNlbGYsIHNlc3Npb25faWQ6IHN0ciwgdXNlcl90ZXh0"
    "OiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICBhc3Npc3RhbnRfdGV4dDogc3RyKSAtPiBPcHRp"
    "b25hbFtkaWN0XToKICAgICAgICByZWNvcmRfdHlwZSA9IGluZmVyX3JlY29yZF90eXBlKHVzZXJf"
    "dGV4dCwgYXNzaXN0YW50X3RleHQpCiAgICAgICAga2V5d29yZHMgICAgPSBleHRyYWN0X2tleXdv"
    "cmRzKHVzZXJfdGV4dCArICIgIiArIGFzc2lzdGFudF90ZXh0KQogICAgICAgIHRhZ3MgICAgICAg"
    "ID0gc2VsZi5faW5mZXJfdGFncyhyZWNvcmRfdHlwZSwgdXNlcl90ZXh0LCBrZXl3b3JkcykKICAg"
    "ICAgICB0aXRsZSAgICAgICA9IHNlbGYuX2luZmVyX3RpdGxlKHJlY29yZF90eXBlLCB1c2VyX3Rl"
    "eHQsIGtleXdvcmRzKQogICAgICAgIHN1bW1hcnkgICAgID0gc2VsZi5fc3VtbWFyaXplKHJlY29y"
    "ZF90eXBlLCB1c2VyX3RleHQsIGFzc2lzdGFudF90ZXh0KQoKICAgICAgICBtZW1vcnkgPSB7CiAg"
    "ICAgICAgICAgICJpZCI6ICAgICAgICAgICAgICAgZiJtZW1fe3V1aWQudXVpZDQoKS5oZXhbOjEy"
    "XX0iLAogICAgICAgICAgICAidGltZXN0YW1wIjogICAgICAgIGxvY2FsX25vd19pc28oKSwKICAg"
    "ICAgICAgICAgInNlc3Npb25faWQiOiAgICAgICBzZXNzaW9uX2lkLAogICAgICAgICAgICAicGVy"
    "c29uYSI6ICAgICAgICAgIERFQ0tfTkFNRSwKICAgICAgICAgICAgInR5cGUiOiAgICAgICAgICAg"
    "ICByZWNvcmRfdHlwZSwKICAgICAgICAgICAgInRpdGxlIjogICAgICAgICAgICB0aXRsZSwKICAg"
    "ICAgICAgICAgInN1bW1hcnkiOiAgICAgICAgICBzdW1tYXJ5LAogICAgICAgICAgICAiY29udGVu"
    "dCI6ICAgICAgICAgIHVzZXJfdGV4dFs6NDAwMF0sCiAgICAgICAgICAgICJhc3Npc3RhbnRfY29u"
    "dGV4dCI6YXNzaXN0YW50X3RleHRbOjEyMDBdLAogICAgICAgICAgICAia2V5d29yZHMiOiAgICAg"
    "ICAgIGtleXdvcmRzLAogICAgICAgICAgICAidGFncyI6ICAgICAgICAgICAgIHRhZ3MsCiAgICAg"
    "ICAgICAgICJjb25maWRlbmNlIjogICAgICAgMC43MCBpZiByZWNvcmRfdHlwZSBpbiB7CiAgICAg"
    "ICAgICAgICAgICAiZHJlYW0iLCJpc3N1ZSIsImlkZWEiLCJwcmVmZXJlbmNlIiwicmVzb2x1dGlv"
    "biIKICAgICAgICAgICAgfSBlbHNlIDAuNTUsCiAgICAgICAgfQoKICAgICAgICBpZiBzZWxmLl9p"
    "c19uZWFyX2R1cGxpY2F0ZShtZW1vcnkpOgogICAgICAgICAgICByZXR1cm4gTm9uZQoKICAgICAg"
    "ICBhcHBlbmRfanNvbmwoc2VsZi5tZW1vcmllc19wLCBtZW1vcnkpCiAgICAgICAgcmV0dXJuIG1l"
    "bW9yeQoKICAgIGRlZiBzZWFyY2hfbWVtb3JpZXMoc2VsZiwgcXVlcnk6IHN0ciwgbGltaXQ6IGlu"
    "dCA9IDYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgIiIiCiAgICAgICAgS2V5d29yZC1zY29yZWQg"
    "bWVtb3J5IHNlYXJjaC4KICAgICAgICBSZXR1cm5zIHVwIHRvIGBsaW1pdGAgcmVjb3JkcyBzb3J0"
    "ZWQgYnkgcmVsZXZhbmNlIHNjb3JlIGRlc2NlbmRpbmcuCiAgICAgICAgRmFsbHMgYmFjayB0byBt"
    "b3N0IHJlY2VudCBpZiBubyBxdWVyeSB0ZXJtcyBtYXRjaC4KICAgICAgICAiIiIKICAgICAgICBt"
    "ZW1vcmllcyA9IHJlYWRfanNvbmwoc2VsZi5tZW1vcmllc19wKQogICAgICAgIGlmIG5vdCBxdWVy"
    "eS5zdHJpcCgpOgogICAgICAgICAgICByZXR1cm4gbWVtb3JpZXNbLWxpbWl0Ol0KCiAgICAgICAg"
    "cV90ZXJtcyA9IHNldChleHRyYWN0X2tleXdvcmRzKHF1ZXJ5LCBsaW1pdD0xNikpCiAgICAgICAg"
    "c2NvcmVkICA9IFtdCgogICAgICAgIGZvciBpdGVtIGluIG1lbW9yaWVzOgogICAgICAgICAgICBp"
    "dGVtX3Rlcm1zID0gc2V0KGV4dHJhY3Rfa2V5d29yZHMoIiAiLmpvaW4oWwogICAgICAgICAgICAg"
    "ICAgaXRlbS5nZXQoInRpdGxlIiwgICAiIiksCiAgICAgICAgICAgICAgICBpdGVtLmdldCgic3Vt"
    "bWFyeSIsICIiKSwKICAgICAgICAgICAgICAgIGl0ZW0uZ2V0KCJjb250ZW50IiwgIiIpLAogICAg"
    "ICAgICAgICAgICAgIiAiLmpvaW4oaXRlbS5nZXQoImtleXdvcmRzIiwgW10pKSwKICAgICAgICAg"
    "ICAgICAgICIgIi5qb2luKGl0ZW0uZ2V0KCJ0YWdzIiwgICAgIFtdKSksCiAgICAgICAgICAgIF0p"
    "LCBsaW1pdD00MCkpCgogICAgICAgICAgICBzY29yZSA9IGxlbihxX3Rlcm1zICYgaXRlbV90ZXJt"
    "cykKCiAgICAgICAgICAgICMgQm9vc3QgYnkgdHlwZSBtYXRjaAogICAgICAgICAgICBxbCA9IHF1"
    "ZXJ5Lmxvd2VyKCkKICAgICAgICAgICAgcnQgPSBpdGVtLmdldCgidHlwZSIsICIiKQogICAgICAg"
    "ICAgICBpZiAiZHJlYW0iICBpbiBxbCBhbmQgcnQgPT0gImRyZWFtIjogICAgc2NvcmUgKz0gNAog"
    "ICAgICAgICAgICBpZiAidGFzayIgICBpbiBxbCBhbmQgcnQgPT0gInRhc2siOiAgICAgc2NvcmUg"
    "Kz0gMwogICAgICAgICAgICBpZiAiaWRlYSIgICBpbiBxbCBhbmQgcnQgPT0gImlkZWEiOiAgICAg"
    "c2NvcmUgKz0gMgogICAgICAgICAgICBpZiAibHNsIiAgICBpbiBxbCBhbmQgcnQgaW4geyJpc3N1"
    "ZSIsInJlc29sdXRpb24ifTogc2NvcmUgKz0gMgoKICAgICAgICAgICAgaWYgc2NvcmUgPiAwOgog"
    "ICAgICAgICAgICAgICAgc2NvcmVkLmFwcGVuZCgoc2NvcmUsIGl0ZW0pKQoKICAgICAgICBzY29y"
    "ZWQuc29ydChrZXk9bGFtYmRhIHg6ICh4WzBdLCB4WzFdLmdldCgidGltZXN0YW1wIiwgIiIpKSwK"
    "ICAgICAgICAgICAgICAgICAgICByZXZlcnNlPVRydWUpCiAgICAgICAgcmV0dXJuIFtpdGVtIGZv"
    "ciBfLCBpdGVtIGluIHNjb3JlZFs6bGltaXRdXQoKICAgIGRlZiBidWlsZF9jb250ZXh0X2Jsb2Nr"
    "KHNlbGYsIHF1ZXJ5OiBzdHIsIG1heF9jaGFyczogaW50ID0gMjAwMCkgLT4gc3RyOgogICAgICAg"
    "ICIiIgogICAgICAgIEJ1aWxkIGEgY29udGV4dCBzdHJpbmcgZnJvbSByZWxldmFudCBtZW1vcmll"
    "cyBmb3IgcHJvbXB0IGluamVjdGlvbi4KICAgICAgICBUcnVuY2F0ZXMgdG8gbWF4X2NoYXJzIHRv"
    "IHByb3RlY3QgdGhlIGNvbnRleHQgd2luZG93LgogICAgICAgICIiIgogICAgICAgIG1lbW9yaWVz"
    "ID0gc2VsZi5zZWFyY2hfbWVtb3JpZXMocXVlcnksIGxpbWl0PTQpCiAgICAgICAgaWYgbm90IG1l"
    "bW9yaWVzOgogICAgICAgICAgICByZXR1cm4gIiIKCiAgICAgICAgcGFydHMgPSBbIltSRUxFVkFO"
    "VCBNRU1PUklFU10iXQogICAgICAgIHRvdGFsID0gMAogICAgICAgIGZvciBtIGluIG1lbW9yaWVz"
    "OgogICAgICAgICAgICBlbnRyeSA9ICgKICAgICAgICAgICAgICAgIGYi4oCiIFt7bS5nZXQoJ3R5"
    "cGUnLCcnKS51cHBlcigpfV0ge20uZ2V0KCd0aXRsZScsJycpfTogIgogICAgICAgICAgICAgICAg"
    "ZiJ7bS5nZXQoJ3N1bW1hcnknLCcnKX0iCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgdG90"
    "YWwgKyBsZW4oZW50cnkpID4gbWF4X2NoYXJzOgogICAgICAgICAgICAgICAgYnJlYWsKICAgICAg"
    "ICAgICAgcGFydHMuYXBwZW5kKGVudHJ5KQogICAgICAgICAgICB0b3RhbCArPSBsZW4oZW50cnkp"
    "CgogICAgICAgIHBhcnRzLmFwcGVuZCgiW0VORCBNRU1PUklFU10iKQogICAgICAgIHJldHVybiAi"
    "XG4iLmpvaW4ocGFydHMpCgogICAgIyDilIDilIAgSEVMUEVSUyDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfaXNfbmVhcl9kdXBs"
    "aWNhdGUoc2VsZiwgY2FuZGlkYXRlOiBkaWN0KSAtPiBib29sOgogICAgICAgIHJlY2VudCA9IHJl"
    "YWRfanNvbmwoc2VsZi5tZW1vcmllc19wKVstMjU6XQogICAgICAgIGN0ID0gY2FuZGlkYXRlLmdl"
    "dCgidGl0bGUiLCAiIikubG93ZXIoKS5zdHJpcCgpCiAgICAgICAgY3MgPSBjYW5kaWRhdGUuZ2V0"
    "KCJzdW1tYXJ5IiwgIiIpLmxvd2VyKCkuc3RyaXAoKQogICAgICAgIGZvciBpdGVtIGluIHJlY2Vu"
    "dDoKICAgICAgICAgICAgaWYgaXRlbS5nZXQoInRpdGxlIiwiIikubG93ZXIoKS5zdHJpcCgpID09"
    "IGN0OiAgcmV0dXJuIFRydWUKICAgICAgICAgICAgaWYgaXRlbS5nZXQoInN1bW1hcnkiLCIiKS5s"
    "b3dlcigpLnN0cmlwKCkgPT0gY3M6IHJldHVybiBUcnVlCiAgICAgICAgcmV0dXJuIEZhbHNlCgog"
    "ICAgZGVmIF9pbmZlcl90YWdzKHNlbGYsIHJlY29yZF90eXBlOiBzdHIsIHRleHQ6IHN0ciwKICAg"
    "ICAgICAgICAgICAgICAgICBrZXl3b3JkczogbGlzdFtzdHJdKSAtPiBsaXN0W3N0cl06CiAgICAg"
    "ICAgdCAgICA9IHRleHQubG93ZXIoKQogICAgICAgIHRhZ3MgPSBbcmVjb3JkX3R5cGVdCiAgICAg"
    "ICAgaWYgImRyZWFtIiAgIGluIHQ6IHRhZ3MuYXBwZW5kKCJkcmVhbSIpCiAgICAgICAgaWYgImxz"
    "bCIgICAgIGluIHQ6IHRhZ3MuYXBwZW5kKCJsc2wiKQogICAgICAgIGlmICJweXRob24iICBpbiB0"
    "OiB0YWdzLmFwcGVuZCgicHl0aG9uIikKICAgICAgICBpZiAiZ2FtZSIgICAgaW4gdDogdGFncy5h"
    "cHBlbmQoImdhbWVfaWRlYSIpCiAgICAgICAgaWYgInNsIiAgICAgIGluIHQgb3IgInNlY29uZCBs"
    "aWZlIiBpbiB0OiB0YWdzLmFwcGVuZCgic2Vjb25kbGlmZSIpCiAgICAgICAgaWYgREVDS19OQU1F"
    "Lmxvd2VyKCkgaW4gdDogdGFncy5hcHBlbmQoREVDS19OQU1FLmxvd2VyKCkpCiAgICAgICAgZm9y"
    "IGt3IGluIGtleXdvcmRzWzo0XToKICAgICAgICAgICAgaWYga3cgbm90IGluIHRhZ3M6CiAgICAg"
    "ICAgICAgICAgICB0YWdzLmFwcGVuZChrdykKICAgICAgICAjIERlZHVwbGljYXRlIHByZXNlcnZp"
    "bmcgb3JkZXIKICAgICAgICBzZWVuLCBvdXQgPSBzZXQoKSwgW10KICAgICAgICBmb3IgdGFnIGlu"
    "IHRhZ3M6CiAgICAgICAgICAgIGlmIHRhZyBub3QgaW4gc2VlbjoKICAgICAgICAgICAgICAgIHNl"
    "ZW4uYWRkKHRhZykKICAgICAgICAgICAgICAgIG91dC5hcHBlbmQodGFnKQogICAgICAgIHJldHVy"
    "biBvdXRbOjEyXQoKICAgIGRlZiBfaW5mZXJfdGl0bGUoc2VsZiwgcmVjb3JkX3R5cGU6IHN0ciwg"
    "dXNlcl90ZXh0OiBzdHIsCiAgICAgICAgICAgICAgICAgICAgIGtleXdvcmRzOiBsaXN0W3N0cl0p"
    "IC0+IHN0cjoKICAgICAgICBkZWYgY2xlYW4od29yZHMpOgogICAgICAgICAgICByZXR1cm4gW3cu"
    "c3RyaXAoIiAtXy4sIT8iKS5jYXBpdGFsaXplKCkKICAgICAgICAgICAgICAgICAgICBmb3IgdyBp"
    "biB3b3JkcyBpZiBsZW4odykgPiAyXQoKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAidGFzayI6"
    "CiAgICAgICAgICAgIGltcG9ydCByZQogICAgICAgICAgICBtID0gcmUuc2VhcmNoKHIicmVtaW5k"
    "IG1lIC4qPyB0byAoLispIiwgdXNlcl90ZXh0LCByZS5JKQogICAgICAgICAgICBpZiBtOgogICAg"
    "ICAgICAgICAgICAgcmV0dXJuIGYiUmVtaW5kZXI6IHttLmdyb3VwKDEpLnN0cmlwKClbOjYwXX0i"
    "CiAgICAgICAgICAgIHJldHVybiAiUmVtaW5kZXIgVGFzayIKICAgICAgICBpZiByZWNvcmRfdHlw"
    "ZSA9PSAiZHJlYW0iOgogICAgICAgICAgICByZXR1cm4gZiJ7JyAnLmpvaW4oY2xlYW4oa2V5d29y"
    "ZHNbOjNdKSl9IERyZWFtIi5zdHJpcCgpIG9yICJEcmVhbSBNZW1vcnkiCiAgICAgICAgaWYgcmVj"
    "b3JkX3R5cGUgPT0gImlzc3VlIjoKICAgICAgICAgICAgcmV0dXJuIGYiSXNzdWU6IHsnICcuam9p"
    "bihjbGVhbihrZXl3b3Jkc1s6NF0pKX0iLnN0cmlwKCkgb3IgIlRlY2huaWNhbCBJc3N1ZSIKICAg"
    "ICAgICBpZiByZWNvcmRfdHlwZSA9PSAicmVzb2x1dGlvbiI6CiAgICAgICAgICAgIHJldHVybiBm"
    "IlJlc29sdXRpb246IHsnICcuam9pbihjbGVhbihrZXl3b3Jkc1s6NF0pKX0iLnN0cmlwKCkgb3Ig"
    "IlRlY2huaWNhbCBSZXNvbHV0aW9uIgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpZGVhIjoK"
    "ICAgICAgICAgICAgcmV0dXJuIGYiSWRlYTogeycgJy5qb2luKGNsZWFuKGtleXdvcmRzWzo0XSkp"
    "fSIuc3RyaXAoKSBvciAiSWRlYSIKICAgICAgICBpZiBrZXl3b3JkczoKICAgICAgICAgICAgcmV0"
    "dXJuICIgIi5qb2luKGNsZWFuKGtleXdvcmRzWzo1XSkpIG9yICJDb252ZXJzYXRpb24gTWVtb3J5"
    "IgogICAgICAgIHJldHVybiAiQ29udmVyc2F0aW9uIE1lbW9yeSIKCiAgICBkZWYgX3N1bW1hcml6"
    "ZShzZWxmLCByZWNvcmRfdHlwZTogc3RyLCB1c2VyX3RleHQ6IHN0ciwKICAgICAgICAgICAgICAg"
    "ICAgIGFzc2lzdGFudF90ZXh0OiBzdHIpIC0+IHN0cjoKICAgICAgICB1ID0gdXNlcl90ZXh0LnN0"
    "cmlwKClbOjIyMF0KICAgICAgICBhID0gYXNzaXN0YW50X3RleHQuc3RyaXAoKVs6MjIwXQogICAg"
    "ICAgIGlmIHJlY29yZF90eXBlID09ICJkcmVhbSI6ICAgICAgIHJldHVybiBmIlVzZXIgZGVzY3Jp"
    "YmVkIGEgZHJlYW06IHt1fSIKICAgICAgICBpZiByZWNvcmRfdHlwZSA9PSAidGFzayI6ICAgICAg"
    "ICByZXR1cm4gZiJSZW1pbmRlci90YXNrOiB7dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0g"
    "Imlzc3VlIjogICAgICAgcmV0dXJuIGYiVGVjaG5pY2FsIGlzc3VlOiB7dX0iCiAgICAgICAgaWYg"
    "cmVjb3JkX3R5cGUgPT0gInJlc29sdXRpb24iOiAgcmV0dXJuIGYiU29sdXRpb24gcmVjb3JkZWQ6"
    "IHthIG9yIHV9IgogICAgICAgIGlmIHJlY29yZF90eXBlID09ICJpZGVhIjogICAgICAgIHJldHVy"
    "biBmIklkZWEgZGlzY3Vzc2VkOiB7dX0iCiAgICAgICAgaWYgcmVjb3JkX3R5cGUgPT0gInByZWZl"
    "cmVuY2UiOiAgcmV0dXJuIGYiUHJlZmVyZW5jZSBub3RlZDoge3V9IgogICAgICAgIHJldHVybiBm"
    "IkNvbnZlcnNhdGlvbjoge3V9IgoKCiMg4pSA4pSAIFNFU1NJT04gTUFOQUdFUiDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xh"
    "c3MgU2Vzc2lvbk1hbmFnZXI6CiAgICAiIiIKICAgIE1hbmFnZXMgY29udmVyc2F0aW9uIHNlc3Np"
    "b25zLgoKICAgIEF1dG8tc2F2ZTogZXZlcnkgMTAgbWludXRlcyAoQVBTY2hlZHVsZXIpLCBtaWRu"
    "aWdodC10by1taWRuaWdodCBib3VuZGFyeS4KICAgIEZpbGU6IHNlc3Npb25zL1lZWVktTU0tREQu"
    "anNvbmwg4oCUIG92ZXJ3cml0ZXMgb24gZWFjaCBzYXZlLgogICAgSW5kZXg6IHNlc3Npb25zL3Nl"
    "c3Npb25faW5kZXguanNvbiDigJQgb25lIGVudHJ5IHBlciBkYXkuCgogICAgU2Vzc2lvbnMgYXJl"
    "IGxvYWRlZCBhcyBjb250ZXh0IGluamVjdGlvbiAobm90IHJlYWwgbWVtb3J5KSB1bnRpbAogICAg"
    "dGhlIFNRTGl0ZS9DaHJvbWFEQiBzeXN0ZW0gaXMgYnVpbHQgaW4gUGhhc2UgMi4KICAgICIiIgoK"
    "ICAgIEFVVE9TQVZFX0lOVEVSVkFMID0gMTAgICAjIG1pbnV0ZXMKCiAgICBkZWYgX19pbml0X18o"
    "c2VsZik6CiAgICAgICAgc2VsZi5fc2Vzc2lvbnNfZGlyICA9IGNmZ19wYXRoKCJzZXNzaW9ucyIp"
    "CiAgICAgICAgc2VsZi5faW5kZXhfcGF0aCAgICA9IHNlbGYuX3Nlc3Npb25zX2RpciAvICJzZXNz"
    "aW9uX2luZGV4Lmpzb24iCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9pZCAgICA9IGYic2Vzc2lvbl97"
    "ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoJyVZJW0lZF8lSCVNJVMnKX0iCiAgICAgICAgc2VsZi5f"
    "Y3VycmVudF9kYXRlICA9IGRhdGUudG9kYXkoKS5pc29mb3JtYXQoKQogICAgICAgIHNlbGYuX21l"
    "c3NhZ2VzOiBsaXN0W2RpY3RdID0gW10KICAgICAgICBzZWxmLl9sb2FkZWRfam91cm5hbDogT3B0"
    "aW9uYWxbc3RyXSA9IE5vbmUgICMgZGF0ZSBvZiBsb2FkZWQgam91cm5hbAoKICAgICMg4pSA4pSA"
    "IENVUlJFTlQgU0VTU0lPTiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBh"
    "ZGRfbWVzc2FnZShzZWxmLCByb2xlOiBzdHIsIGNvbnRlbnQ6IHN0ciwKICAgICAgICAgICAgICAg"
    "ICAgICBlbW90aW9uOiBzdHIgPSAiIiwgdGltZXN0YW1wOiBzdHIgPSAiIikgLT4gTm9uZToKICAg"
    "ICAgICBzZWxmLl9tZXNzYWdlcy5hcHBlbmQoewogICAgICAgICAgICAiaWQiOiAgICAgICAgZiJt"
    "c2dfe3V1aWQudXVpZDQoKS5oZXhbOjhdfSIsCiAgICAgICAgICAgICJ0aW1lc3RhbXAiOiB0aW1l"
    "c3RhbXAgb3IgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAicm9sZSI6ICAgICAgcm9sZSwK"
    "ICAgICAgICAgICAgImNvbnRlbnQiOiAgIGNvbnRlbnQsCiAgICAgICAgICAgICJlbW90aW9uIjog"
    "ICBlbW90aW9uLAogICAgICAgIH0pCgogICAgZGVmIGdldF9oaXN0b3J5KHNlbGYpIC0+IGxpc3Rb"
    "ZGljdF06CiAgICAgICAgIiIiCiAgICAgICAgUmV0dXJuIGhpc3RvcnkgaW4gTExNLWZyaWVuZGx5"
    "IGZvcm1hdC4KICAgICAgICBbeyJyb2xlIjogInVzZXIifCJhc3Npc3RhbnQiLCAiY29udGVudCI6"
    "ICIuLi4ifV0KICAgICAgICAiIiIKICAgICAgICByZXR1cm4gWwogICAgICAgICAgICB7InJvbGUi"
    "OiBtWyJyb2xlIl0sICJjb250ZW50IjogbVsiY29udGVudCJdfQogICAgICAgICAgICBmb3IgbSBp"
    "biBzZWxmLl9tZXNzYWdlcwogICAgICAgICAgICBpZiBtWyJyb2xlIl0gaW4gKCJ1c2VyIiwgImFz"
    "c2lzdGFudCIpCiAgICAgICAgXQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIHNlc3Npb25faWQoc2Vs"
    "ZikgLT4gc3RyOgogICAgICAgIHJldHVybiBzZWxmLl9zZXNzaW9uX2lkCgogICAgQHByb3BlcnR5"
    "CiAgICBkZWYgbWVzc2FnZV9jb3VudChzZWxmKSAtPiBpbnQ6CiAgICAgICAgcmV0dXJuIGxlbihz"
    "ZWxmLl9tZXNzYWdlcykKCiAgICAjIOKUgOKUgCBTQVZFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIHNhdmUoc2Vs"
    "ZiwgYWlfZ2VuZXJhdGVkX25hbWU6IHN0ciA9ICIiKSAtPiBOb25lOgogICAgICAgICIiIgogICAg"
    "ICAgIFNhdmUgY3VycmVudCBzZXNzaW9uIHRvIHNlc3Npb25zL1lZWVktTU0tREQuanNvbmwuCiAg"
    "ICAgICAgT3ZlcndyaXRlcyB0aGUgZmlsZSBmb3IgdG9kYXkg4oCUIGVhY2ggc2F2ZSBpcyBhIGZ1"
    "bGwgc25hcHNob3QuCiAgICAgICAgVXBkYXRlcyBzZXNzaW9uX2luZGV4Lmpzb24uCiAgICAgICAg"
    "IiIiCiAgICAgICAgdG9kYXkgPSBkYXRlLnRvZGF5KCkuaXNvZm9ybWF0KCkKICAgICAgICBvdXRf"
    "cGF0aCA9IHNlbGYuX3Nlc3Npb25zX2RpciAvIGYie3RvZGF5fS5qc29ubCIKCiAgICAgICAgIyBX"
    "cml0ZSBhbGwgbWVzc2FnZXMKICAgICAgICB3cml0ZV9qc29ubChvdXRfcGF0aCwgc2VsZi5fbWVz"
    "c2FnZXMpCgogICAgICAgICMgVXBkYXRlIGluZGV4CiAgICAgICAgaW5kZXggPSBzZWxmLl9sb2Fk"
    "X2luZGV4KCkKICAgICAgICBleGlzdGluZyA9IG5leHQoCiAgICAgICAgICAgIChzIGZvciBzIGlu"
    "IGluZGV4WyJzZXNzaW9ucyJdIGlmIHNbImRhdGUiXSA9PSB0b2RheSksIE5vbmUKICAgICAgICAp"
    "CgogICAgICAgIG5hbWUgPSBhaV9nZW5lcmF0ZWRfbmFtZSBvciBleGlzdGluZy5nZXQoIm5hbWUi"
    "LCAiIikgaWYgZXhpc3RpbmcgZWxzZSAiIgogICAgICAgIGlmIG5vdCBuYW1lIGFuZCBzZWxmLl9t"
    "ZXNzYWdlczoKICAgICAgICAgICAgIyBBdXRvLW5hbWUgZnJvbSBmaXJzdCB1c2VyIG1lc3NhZ2Ug"
    "KGZpcnN0IDUgd29yZHMpCiAgICAgICAgICAgIGZpcnN0X3VzZXIgPSBuZXh0KAogICAgICAgICAg"
    "ICAgICAgKG1bImNvbnRlbnQiXSBmb3IgbSBpbiBzZWxmLl9tZXNzYWdlcyBpZiBtWyJyb2xlIl0g"
    "PT0gInVzZXIiKSwKICAgICAgICAgICAgICAgICIiCiAgICAgICAgICAgICkKICAgICAgICAgICAg"
    "d29yZHMgPSBmaXJzdF91c2VyLnNwbGl0KClbOjVdCiAgICAgICAgICAgIG5hbWUgID0gIiAiLmpv"
    "aW4od29yZHMpIGlmIHdvcmRzIGVsc2UgZiJTZXNzaW9uIHt0b2RheX0iCgogICAgICAgIGVudHJ5"
    "ID0gewogICAgICAgICAgICAiZGF0ZSI6ICAgICAgICAgIHRvZGF5LAogICAgICAgICAgICAic2Vz"
    "c2lvbl9pZCI6ICAgIHNlbGYuX3Nlc3Npb25faWQsCiAgICAgICAgICAgICJuYW1lIjogICAgICAg"
    "ICAgbmFtZSwKICAgICAgICAgICAgIm1lc3NhZ2VfY291bnQiOiBsZW4oc2VsZi5fbWVzc2FnZXMp"
    "LAogICAgICAgICAgICAiZmlyc3RfbWVzc2FnZSI6IChzZWxmLl9tZXNzYWdlc1swXVsidGltZXN0"
    "YW1wIl0KICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgc2VsZi5fbWVzc2FnZXMgZWxz"
    "ZSAiIiksCiAgICAgICAgICAgICJsYXN0X21lc3NhZ2UiOiAgKHNlbGYuX21lc3NhZ2VzWy0xXVsi"
    "dGltZXN0YW1wIl0KICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgaWYgc2VsZi5fbWVzc2Fn"
    "ZXMgZWxzZSAiIiksCiAgICAgICAgfQoKICAgICAgICBpZiBleGlzdGluZzoKICAgICAgICAgICAg"
    "aWR4ID0gaW5kZXhbInNlc3Npb25zIl0uaW5kZXgoZXhpc3RpbmcpCiAgICAgICAgICAgIGluZGV4"
    "WyJzZXNzaW9ucyJdW2lkeF0gPSBlbnRyeQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGluZGV4"
    "WyJzZXNzaW9ucyJdLmluc2VydCgwLCBlbnRyeSkKCiAgICAgICAgIyBLZWVwIGxhc3QgMzY1IGRh"
    "eXMgaW4gaW5kZXgKICAgICAgICBpbmRleFsic2Vzc2lvbnMiXSA9IGluZGV4WyJzZXNzaW9ucyJd"
    "WzozNjVdCiAgICAgICAgc2VsZi5fc2F2ZV9pbmRleChpbmRleCkKCiAgICAjIOKUgOKUgCBMT0FE"
    "IC8gSk9VUk5BTCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBsaXN0"
    "X3Nlc3Npb25zKHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAgICAgIiIiUmV0dXJuIGFsbCBzZXNz"
    "aW9ucyBmcm9tIGluZGV4LCBuZXdlc3QgZmlyc3QuIiIiCiAgICAgICAgcmV0dXJuIHNlbGYuX2xv"
    "YWRfaW5kZXgoKS5nZXQoInNlc3Npb25zIiwgW10pCgogICAgZGVmIGxvYWRfc2Vzc2lvbl9hc19j"
    "b250ZXh0KHNlbGYsIHNlc3Npb25fZGF0ZTogc3RyKSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAg"
    "ICAgTG9hZCBhIHBhc3Qgc2Vzc2lvbiBhcyBhIGNvbnRleHQgaW5qZWN0aW9uIHN0cmluZy4KICAg"
    "ICAgICBSZXR1cm5zIGZvcm1hdHRlZCB0ZXh0IHRvIHByZXBlbmQgdG8gdGhlIHN5c3RlbSBwcm9t"
    "cHQuCiAgICAgICAgVGhpcyBpcyBOT1QgcmVhbCBtZW1vcnkg4oCUIGl0J3MgYSB0ZW1wb3Jhcnkg"
    "Y29udGV4dCB3aW5kb3cgaW5qZWN0aW9uCiAgICAgICAgdW50aWwgdGhlIFBoYXNlIDIgbWVtb3J5"
    "IHN5c3RlbSBpcyBidWlsdC4KICAgICAgICAiIiIKICAgICAgICBwYXRoID0gc2VsZi5fc2Vzc2lv"
    "bnNfZGlyIC8gZiJ7c2Vzc2lvbl9kYXRlfS5qc29ubCIKICAgICAgICBpZiBub3QgcGF0aC5leGlz"
    "dHMoKToKICAgICAgICAgICAgcmV0dXJuICIiCgogICAgICAgIG1lc3NhZ2VzID0gcmVhZF9qc29u"
    "bChwYXRoKQogICAgICAgIHNlbGYuX2xvYWRlZF9qb3VybmFsID0gc2Vzc2lvbl9kYXRlCgogICAg"
    "ICAgIGxpbmVzID0gW2YiW0pPVVJOQUwgTE9BREVEIOKAlCB7c2Vzc2lvbl9kYXRlfV0iLAogICAg"
    "ICAgICAgICAgICAgICJUaGUgZm9sbG93aW5nIGlzIGEgcmVjb3JkIG9mIGEgcHJpb3IgY29udmVy"
    "c2F0aW9uLiIsCiAgICAgICAgICAgICAgICAgIlVzZSB0aGlzIGFzIGNvbnRleHQgZm9yIHRoZSBj"
    "dXJyZW50IHNlc3Npb246XG4iXQoKICAgICAgICAjIEluY2x1ZGUgdXAgdG8gbGFzdCAzMCBtZXNz"
    "YWdlcyBmcm9tIHRoYXQgc2Vzc2lvbgogICAgICAgIGZvciBtc2cgaW4gbWVzc2FnZXNbLTMwOl06"
    "CiAgICAgICAgICAgIHJvbGUgICAgPSBtc2cuZ2V0KCJyb2xlIiwgIj8iKS51cHBlcigpCiAgICAg"
    "ICAgICAgIGNvbnRlbnQgPSBtc2cuZ2V0KCJjb250ZW50IiwgIiIpWzozMDBdCiAgICAgICAgICAg"
    "IHRzICAgICAgPSBtc2cuZ2V0KCJ0aW1lc3RhbXAiLCAiIilbOjE2XQogICAgICAgICAgICBsaW5l"
    "cy5hcHBlbmQoZiJbe3RzfV0ge3JvbGV9OiB7Y29udGVudH0iKQoKICAgICAgICBsaW5lcy5hcHBl"
    "bmQoIltFTkQgSk9VUk5BTF0iKQogICAgICAgIHJldHVybiAiXG4iLmpvaW4obGluZXMpCgogICAg"
    "ZGVmIGNsZWFyX2xvYWRlZF9qb3VybmFsKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fbG9h"
    "ZGVkX2pvdXJuYWwgPSBOb25lCgogICAgQHByb3BlcnR5CiAgICBkZWYgbG9hZGVkX2pvdXJuYWxf"
    "ZGF0ZShzZWxmKSAtPiBPcHRpb25hbFtzdHJdOgogICAgICAgIHJldHVybiBzZWxmLl9sb2FkZWRf"
    "am91cm5hbAoKICAgIGRlZiByZW5hbWVfc2Vzc2lvbihzZWxmLCBzZXNzaW9uX2RhdGU6IHN0ciwg"
    "bmV3X25hbWU6IHN0cikgLT4gYm9vbDoKICAgICAgICAiIiJSZW5hbWUgYSBzZXNzaW9uIGluIHRo"
    "ZSBpbmRleC4gUmV0dXJucyBUcnVlIG9uIHN1Y2Nlc3MuIiIiCiAgICAgICAgaW5kZXggPSBzZWxm"
    "Ll9sb2FkX2luZGV4KCkKICAgICAgICBmb3IgZW50cnkgaW4gaW5kZXhbInNlc3Npb25zIl06CiAg"
    "ICAgICAgICAgIGlmIGVudHJ5WyJkYXRlIl0gPT0gc2Vzc2lvbl9kYXRlOgogICAgICAgICAgICAg"
    "ICAgZW50cnlbIm5hbWUiXSA9IG5ld19uYW1lWzo4MF0KICAgICAgICAgICAgICAgIHNlbGYuX3Nh"
    "dmVfaW5kZXgoaW5kZXgpCiAgICAgICAgICAgICAgICByZXR1cm4gVHJ1ZQogICAgICAgIHJldHVy"
    "biBGYWxzZQoKICAgICMg4pSA4pSAIElOREVYIEhFTFBFUlMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX2xvYWRfaW5kZXgoc2VsZikgLT4gZGljdDoKICAgICAg"
    "ICBpZiBub3Qgc2VsZi5faW5kZXhfcGF0aC5leGlzdHMoKToKICAgICAgICAgICAgcmV0dXJuIHsi"
    "c2Vzc2lvbnMiOiBbXX0KICAgICAgICB0cnk6CiAgICAgICAgICAgIHJldHVybiBqc29uLmxvYWRz"
    "KAogICAgICAgICAgICAgICAgc2VsZi5faW5kZXhfcGF0aC5yZWFkX3RleHQoZW5jb2Rpbmc9InV0"
    "Zi04IikKICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAg"
    "IHJldHVybiB7InNlc3Npb25zIjogW119CgogICAgZGVmIF9zYXZlX2luZGV4KHNlbGYsIGluZGV4"
    "OiBkaWN0KSAtPiBOb25lOgogICAgICAgIHNlbGYuX2luZGV4X3BhdGgud3JpdGVfdGV4dCgKICAg"
    "ICAgICAgICAganNvbi5kdW1wcyhpbmRleCwgaW5kZW50PTIpLCBlbmNvZGluZz0idXRmLTgiCiAg"
    "ICAgICAgKQoKCiMg4pSA4pSAIExFU1NPTlMgTEVBUk5FRCBEQVRBQkFTRSDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgTGVzc29uc0xlYXJuZWREQjoKICAgICIiIgog"
    "ICAgUGVyc2lzdGVudCBrbm93bGVkZ2UgYmFzZSBmb3IgY29kZSBsZXNzb25zLCBydWxlcywgYW5k"
    "IHJlc29sdXRpb25zLgoKICAgIENvbHVtbnMgcGVyIHJlY29yZDoKICAgICAgICBpZCwgY3JlYXRl"
    "ZF9hdCwgZW52aXJvbm1lbnQgKExTTHxQeXRob258UHlTaWRlNnwuLi4pLCBsYW5ndWFnZSwKICAg"
    "ICAgICByZWZlcmVuY2Vfa2V5IChzaG9ydCB1bmlxdWUgdGFnKSwgc3VtbWFyeSwgZnVsbF9ydWxl"
    "LAogICAgICAgIHJlc29sdXRpb24sIGxpbmssIHRhZ3MKCiAgICBRdWVyaWVkIEZJUlNUIGJlZm9y"
    "ZSBhbnkgY29kZSBzZXNzaW9uIGluIHRoZSByZWxldmFudCBsYW5ndWFnZS4KICAgIFRoZSBMU0wg"
    "Rm9yYmlkZGVuIFJ1bGVzZXQgbGl2ZXMgaGVyZS4KICAgIEdyb3dpbmcsIG5vbi1kdXBsaWNhdGlu"
    "Zywgc2VhcmNoYWJsZS4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBz"
    "ZWxmLl9wYXRoID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAibGVzc29uc19sZWFybmVkLmpzb25s"
    "IgoKICAgIGRlZiBhZGQoc2VsZiwgZW52aXJvbm1lbnQ6IHN0ciwgbGFuZ3VhZ2U6IHN0ciwgcmVm"
    "ZXJlbmNlX2tleTogc3RyLAogICAgICAgICAgICBzdW1tYXJ5OiBzdHIsIGZ1bGxfcnVsZTogc3Ry"
    "LCByZXNvbHV0aW9uOiBzdHIgPSAiIiwKICAgICAgICAgICAgbGluazogc3RyID0gIiIsIHRhZ3M6"
    "IGxpc3QgPSBOb25lKSAtPiBkaWN0OgogICAgICAgIHJlY29yZCA9IHsKICAgICAgICAgICAgImlk"
    "IjogICAgICAgICAgICBmImxlc3Nvbl97dXVpZC51dWlkNCgpLmhleFs6MTBdfSIsCiAgICAgICAg"
    "ICAgICJjcmVhdGVkX2F0IjogICAgbG9jYWxfbm93X2lzbygpLAogICAgICAgICAgICAiZW52aXJv"
    "bm1lbnQiOiAgIGVudmlyb25tZW50LAogICAgICAgICAgICAibGFuZ3VhZ2UiOiAgICAgIGxhbmd1"
    "YWdlLAogICAgICAgICAgICAicmVmZXJlbmNlX2tleSI6IHJlZmVyZW5jZV9rZXksCiAgICAgICAg"
    "ICAgICJzdW1tYXJ5IjogICAgICAgc3VtbWFyeSwKICAgICAgICAgICAgImZ1bGxfcnVsZSI6ICAg"
    "ICBmdWxsX3J1bGUsCiAgICAgICAgICAgICJyZXNvbHV0aW9uIjogICAgcmVzb2x1dGlvbiwKICAg"
    "ICAgICAgICAgImxpbmsiOiAgICAgICAgICBsaW5rLAogICAgICAgICAgICAidGFncyI6ICAgICAg"
    "ICAgIHRhZ3Mgb3IgW10sCiAgICAgICAgfQogICAgICAgIGlmIG5vdCBzZWxmLl9pc19kdXBsaWNh"
    "dGUocmVmZXJlbmNlX2tleSk6CiAgICAgICAgICAgIGFwcGVuZF9qc29ubChzZWxmLl9wYXRoLCBy"
    "ZWNvcmQpCiAgICAgICAgcmV0dXJuIHJlY29yZAoKICAgIGRlZiBzZWFyY2goc2VsZiwgcXVlcnk6"
    "IHN0ciA9ICIiLCBlbnZpcm9ubWVudDogc3RyID0gIiIsCiAgICAgICAgICAgICAgIGxhbmd1YWdl"
    "OiBzdHIgPSAiIikgLT4gbGlzdFtkaWN0XToKICAgICAgICByZWNvcmRzID0gcmVhZF9qc29ubChz"
    "ZWxmLl9wYXRoKQogICAgICAgIHJlc3VsdHMgPSBbXQogICAgICAgIHEgPSBxdWVyeS5sb3dlcigp"
    "CiAgICAgICAgZm9yIHIgaW4gcmVjb3JkczoKICAgICAgICAgICAgaWYgZW52aXJvbm1lbnQgYW5k"
    "IHIuZ2V0KCJlbnZpcm9ubWVudCIsIiIpLmxvd2VyKCkgIT0gZW52aXJvbm1lbnQubG93ZXIoKToK"
    "ICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGlmIGxhbmd1YWdlIGFuZCByLmdl"
    "dCgibGFuZ3VhZ2UiLCIiKS5sb3dlcigpICE9IGxhbmd1YWdlLmxvd2VyKCk6CiAgICAgICAgICAg"
    "ICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBxOgogICAgICAgICAgICAgICAgaGF5c3RhY2sg"
    "PSAiICIuam9pbihbCiAgICAgICAgICAgICAgICAgICAgci5nZXQoInN1bW1hcnkiLCIiKSwKICAg"
    "ICAgICAgICAgICAgICAgICByLmdldCgiZnVsbF9ydWxlIiwiIiksCiAgICAgICAgICAgICAgICAg"
    "ICAgci5nZXQoInJlZmVyZW5jZV9rZXkiLCIiKSwKICAgICAgICAgICAgICAgICAgICAiICIuam9p"
    "bihyLmdldCgidGFncyIsW10pKSwKICAgICAgICAgICAgICAgIF0pLmxvd2VyKCkKICAgICAgICAg"
    "ICAgICAgIGlmIHEgbm90IGluIGhheXN0YWNrOgogICAgICAgICAgICAgICAgICAgIGNvbnRpbnVl"
    "CiAgICAgICAgICAgIHJlc3VsdHMuYXBwZW5kKHIpCiAgICAgICAgcmV0dXJuIHJlc3VsdHMKCiAg"
    "ICBkZWYgZ2V0X2FsbChzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAgIHJldHVybiByZWFkX2pz"
    "b25sKHNlbGYuX3BhdGgpCgogICAgZGVmIGRlbGV0ZShzZWxmLCByZWNvcmRfaWQ6IHN0cikgLT4g"
    "Ym9vbDoKICAgICAgICByZWNvcmRzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIGZp"
    "bHRlcmVkID0gW3IgZm9yIHIgaW4gcmVjb3JkcyBpZiByLmdldCgiaWQiKSAhPSByZWNvcmRfaWRd"
    "CiAgICAgICAgaWYgbGVuKGZpbHRlcmVkKSA8IGxlbihyZWNvcmRzKToKICAgICAgICAgICAgd3Jp"
    "dGVfanNvbmwoc2VsZi5fcGF0aCwgZmlsdGVyZWQpCiAgICAgICAgICAgIHJldHVybiBUcnVlCiAg"
    "ICAgICAgcmV0dXJuIEZhbHNlCgogICAgZGVmIGJ1aWxkX2NvbnRleHRfZm9yX2xhbmd1YWdlKHNl"
    "bGYsIGxhbmd1YWdlOiBzdHIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgbWF4"
    "X2NoYXJzOiBpbnQgPSAxNTAwKSAtPiBzdHI6CiAgICAgICAgIiIiCiAgICAgICAgQnVpbGQgYSBj"
    "b250ZXh0IHN0cmluZyBvZiBhbGwgcnVsZXMgZm9yIGEgZ2l2ZW4gbGFuZ3VhZ2UuCiAgICAgICAg"
    "Rm9yIGluamVjdGlvbiBpbnRvIHN5c3RlbSBwcm9tcHQgYmVmb3JlIGNvZGUgc2Vzc2lvbnMuCiAg"
    "ICAgICAgIiIiCiAgICAgICAgcmVjb3JkcyA9IHNlbGYuc2VhcmNoKGxhbmd1YWdlPWxhbmd1YWdl"
    "KQogICAgICAgIGlmIG5vdCByZWNvcmRzOgogICAgICAgICAgICByZXR1cm4gIiIKCiAgICAgICAg"
    "cGFydHMgPSBbZiJbe2xhbmd1YWdlLnVwcGVyKCl9IFJVTEVTIOKAlCBBUFBMWSBCRUZPUkUgV1JJ"
    "VElORyBDT0RFXSJdCiAgICAgICAgdG90YWwgPSAwCiAgICAgICAgZm9yIHIgaW4gcmVjb3JkczoK"
    "ICAgICAgICAgICAgZW50cnkgPSBmIuKAoiB7ci5nZXQoJ3JlZmVyZW5jZV9rZXknLCcnKX06IHty"
    "LmdldCgnZnVsbF9ydWxlJywnJyl9IgogICAgICAgICAgICBpZiB0b3RhbCArIGxlbihlbnRyeSkg"
    "PiBtYXhfY2hhcnM6CiAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICBwYXJ0cy5hcHBl"
    "bmQoZW50cnkpCiAgICAgICAgICAgIHRvdGFsICs9IGxlbihlbnRyeSkKCiAgICAgICAgcGFydHMu"
    "YXBwZW5kKGYiW0VORCB7bGFuZ3VhZ2UudXBwZXIoKX0gUlVMRVNdIikKICAgICAgICByZXR1cm4g"
    "IlxuIi5qb2luKHBhcnRzKQoKICAgIGRlZiBfaXNfZHVwbGljYXRlKHNlbGYsIHJlZmVyZW5jZV9r"
    "ZXk6IHN0cikgLT4gYm9vbDoKICAgICAgICByZXR1cm4gYW55KAogICAgICAgICAgICByLmdldCgi"
    "cmVmZXJlbmNlX2tleSIsIiIpLmxvd2VyKCkgPT0gcmVmZXJlbmNlX2tleS5sb3dlcigpCiAgICAg"
    "ICAgICAgIGZvciByIGluIHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICApCgogICAgZGVm"
    "IHNlZWRfbHNsX3J1bGVzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgU2VlZCB0"
    "aGUgTFNMIEZvcmJpZGRlbiBSdWxlc2V0IG9uIGZpcnN0IHJ1biBpZiB0aGUgREIgaXMgZW1wdHku"
    "CiAgICAgICAgVGhlc2UgYXJlIHRoZSBoYXJkIHJ1bGVzIGZyb20gdGhlIHByb2plY3Qgc3RhbmRp"
    "bmcgcnVsZXMuCiAgICAgICAgIiIiCiAgICAgICAgaWYgcmVhZF9qc29ubChzZWxmLl9wYXRoKToK"
    "ICAgICAgICAgICAgcmV0dXJuICAjIEFscmVhZHkgc2VlZGVkCgogICAgICAgIGxzbF9ydWxlcyA9"
    "IFsKICAgICAgICAgICAgKCJMU0wiLCAiTFNMIiwgIk5PX1RFUk5BUlkiLAogICAgICAgICAgICAg"
    "Ik5vIHRlcm5hcnkgb3BlcmF0b3JzIGluIExTTCIsCiAgICAgICAgICAgICAiTmV2ZXIgdXNlIHRo"
    "ZSB0ZXJuYXJ5IG9wZXJhdG9yICg/OikgaW4gTFNMIHNjcmlwdHMuICIKICAgICAgICAgICAgICJV"
    "c2UgaWYvZWxzZSBibG9ja3MgaW5zdGVhZC4gTFNMIGRvZXMgbm90IHN1cHBvcnQgdGVybmFyeS4i"
    "LAogICAgICAgICAgICAgIlJlcGxhY2Ugd2l0aCBpZi9lbHNlIGJsb2NrLiIsICIiKSwKICAgICAg"
    "ICAgICAgKCJMU0wiLCAiTFNMIiwgIk5PX0ZPUkVBQ0giLAogICAgICAgICAgICAgIk5vIGZvcmVh"
    "Y2ggbG9vcHMgaW4gTFNMIiwKICAgICAgICAgICAgICJMU0wgaGFzIG5vIGZvcmVhY2ggbG9vcCBj"
    "b25zdHJ1Y3QuIFVzZSBpbnRlZ2VyIGluZGV4IHdpdGggIgogICAgICAgICAgICAgImxsR2V0TGlz"
    "dExlbmd0aCgpIGFuZCBhIGZvciBvciB3aGlsZSBsb29wLiIsCiAgICAgICAgICAgICAiVXNlOiBm"
    "b3IoaW50ZWdlciBpPTA7IGk8bGxHZXRMaXN0TGVuZ3RoKG15TGlzdCk7IGkrKykiLCAiIiksCiAg"
    "ICAgICAgICAgICgiTFNMIiwgIkxTTCIsICJOT19HTE9CQUxfQVNTSUdOX0ZST01fRlVOQyIsCiAg"
    "ICAgICAgICAgICAiTm8gZ2xvYmFsIHZhcmlhYmxlIGFzc2lnbm1lbnRzIGZyb20gZnVuY3Rpb24g"
    "Y2FsbHMiLAogICAgICAgICAgICAgIkdsb2JhbCB2YXJpYWJsZSBpbml0aWFsaXphdGlvbiBpbiBM"
    "U0wgY2Fubm90IGNhbGwgZnVuY3Rpb25zLiAiCiAgICAgICAgICAgICAiSW5pdGlhbGl6ZSBnbG9i"
    "YWxzIHdpdGggbGl0ZXJhbCB2YWx1ZXMgb25seS4gIgogICAgICAgICAgICAgIkFzc2lnbiBmcm9t"
    "IGZ1bmN0aW9ucyBpbnNpZGUgZXZlbnQgaGFuZGxlcnMgb3Igb3RoZXIgZnVuY3Rpb25zLiIsCiAg"
    "ICAgICAgICAgICAiTW92ZSB0aGUgYXNzaWdubWVudCBpbnRvIGFuIGV2ZW50IGhhbmRsZXIgKHN0"
    "YXRlX2VudHJ5LCBldGMuKSIsICIiKSwKICAgICAgICAgICAgKCJMU0wiLCAiTFNMIiwgIk5PX1ZP"
    "SURfS0VZV09SRCIsCiAgICAgICAgICAgICAiTm8gdm9pZCBrZXl3b3JkIGluIExTTCIsCiAgICAg"
    "ICAgICAgICAiTFNMIGRvZXMgbm90IGhhdmUgYSB2b2lkIGtleXdvcmQgZm9yIGZ1bmN0aW9uIHJl"
    "dHVybiB0eXBlcy4gIgogICAgICAgICAgICAgIkZ1bmN0aW9ucyB0aGF0IHJldHVybiBub3RoaW5n"
    "IHNpbXBseSBvbWl0IHRoZSByZXR1cm4gdHlwZS4iLAogICAgICAgICAgICAgIlJlbW92ZSAndm9p"
    "ZCcgZnJvbSBmdW5jdGlvbiBzaWduYXR1cmUuICIKICAgICAgICAgICAgICJlLmcuIG15RnVuYygp"
    "IHsgLi4uIH0gbm90IHZvaWQgbXlGdW5jKCkgeyAuLi4gfSIsICIiKSwKICAgICAgICAgICAgKCJM"
    "U0wiLCAiTFNMIiwgIkNPTVBMRVRFX1NDUklQVFNfT05MWSIsCiAgICAgICAgICAgICAiQWx3YXlz"
    "IHByb3ZpZGUgY29tcGxldGUgc2NyaXB0cywgbmV2ZXIgcGFydGlhbCBlZGl0cyIsCiAgICAgICAg"
    "ICAgICAiV2hlbiB3cml0aW5nIG9yIGVkaXRpbmcgTFNMIHNjcmlwdHMsIGFsd2F5cyBvdXRwdXQg"
    "dGhlIGNvbXBsZXRlICIKICAgICAgICAgICAgICJzY3JpcHQuIE5ldmVyIHByb3ZpZGUgcGFydGlh"
    "bCBzbmlwcGV0cyBvciAnYWRkIHRoaXMgc2VjdGlvbicgIgogICAgICAgICAgICAgImluc3RydWN0"
    "aW9ucy4gVGhlIGZ1bGwgc2NyaXB0IG11c3QgYmUgY29weS1wYXN0ZSByZWFkeS4iLAogICAgICAg"
    "ICAgICAgIldyaXRlIHRoZSBlbnRpcmUgc2NyaXB0IGZyb20gdG9wIHRvIGJvdHRvbS4iLCAiIiks"
    "CiAgICAgICAgXQoKICAgICAgICBmb3IgZW52LCBsYW5nLCByZWYsIHN1bW1hcnksIGZ1bGxfcnVs"
    "ZSwgcmVzb2x1dGlvbiwgbGluayBpbiBsc2xfcnVsZXM6CiAgICAgICAgICAgIHNlbGYuYWRkKGVu"
    "diwgbGFuZywgcmVmLCBzdW1tYXJ5LCBmdWxsX3J1bGUsIHJlc29sdXRpb24sIGxpbmssCiAgICAg"
    "ICAgICAgICAgICAgICAgIHRhZ3M9WyJsc2wiLCAiZm9yYmlkZGVuIiwgInN0YW5kaW5nX3J1bGUi"
    "XSkKCgojIOKUgOKUgCBUQVNLIE1BTkFHRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFRhc2tNYW5hZ2Vy"
    "OgogICAgIiIiCiAgICBUYXNrL3JlbWluZGVyIENSVUQgYW5kIGR1ZS1ldmVudCBkZXRlY3Rpb24u"
    "CgogICAgRmlsZTogbWVtb3JpZXMvdGFza3MuanNvbmwKCiAgICBUYXNrIHJlY29yZCBmaWVsZHM6"
    "CiAgICAgICAgaWQsIGNyZWF0ZWRfYXQsIGR1ZV9hdCwgcHJlX3RyaWdnZXIgKDFtaW4gYmVmb3Jl"
    "KSwKICAgICAgICB0ZXh0LCBzdGF0dXMgKHBlbmRpbmd8dHJpZ2dlcmVkfHNub296ZWR8Y29tcGxl"
    "dGVkfGNhbmNlbGxlZCksCiAgICAgICAgYWNrbm93bGVkZ2VkX2F0LCByZXRyeV9jb3VudCwgbGFz"
    "dF90cmlnZ2VyZWRfYXQsIG5leHRfcmV0cnlfYXQsCiAgICAgICAgc291cmNlIChsb2NhbHxnb29n"
    "bGUpLCBnb29nbGVfZXZlbnRfaWQsIHN5bmNfc3RhdHVzLCBtZXRhZGF0YQoKICAgIER1ZS1ldmVu"
    "dCBjeWNsZToKICAgICAgICAtIFByZS10cmlnZ2VyOiAxIG1pbnV0ZSBiZWZvcmUgZHVlIOKGkiBh"
    "bm5vdW5jZSB1cGNvbWluZwogICAgICAgIC0gRHVlIHRyaWdnZXI6IGF0IGR1ZSB0aW1lIOKGkiBh"
    "bGVydCBzb3VuZCArIEFJIGNvbW1lbnRhcnkKICAgICAgICAtIDMtbWludXRlIHdpbmRvdzogaWYg"
    "bm90IGFja25vd2xlZGdlZCDihpIgc25vb3plCiAgICAgICAgLSAxMi1taW51dGUgcmV0cnk6IHJl"
    "LXRyaWdnZXIKICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBzZWxmLl9w"
    "YXRoID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAidGFza3MuanNvbmwiCgogICAgIyDilIDilIAg"
    "Q1JVRCDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKICAgIGRlZiBsb2FkX2FsbChzZWxmKSAtPiBsaXN0W2RpY3RdOgogICAgICAg"
    "IHRhc2tzID0gcmVhZF9qc29ubChzZWxmLl9wYXRoKQogICAgICAgIGNoYW5nZWQgPSBGYWxzZQog"
    "ICAgICAgIG5vcm1hbGl6ZWQgPSBbXQogICAgICAgIGZvciB0IGluIHRhc2tzOgogICAgICAgICAg"
    "ICBpZiBub3QgaXNpbnN0YW5jZSh0LCBkaWN0KToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAg"
    "ICAgICAgICAgIGlmICJpZCIgbm90IGluIHQ6CiAgICAgICAgICAgICAgICB0WyJpZCJdID0gZiJ0"
    "YXNrX3t1dWlkLnV1aWQ0KCkuaGV4WzoxMF19IgogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRy"
    "dWUKICAgICAgICAgICAgIyBOb3JtYWxpemUgZmllbGQgbmFtZXMKICAgICAgICAgICAgaWYgImR1"
    "ZV9hdCIgbm90IGluIHQ6CiAgICAgICAgICAgICAgICB0WyJkdWVfYXQiXSA9IHQuZ2V0KCJkdWUi"
    "KQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgdC5zZXRkZWZhdWx0"
    "KCJzdGF0dXMiLCAgICAgICAgICAgInBlbmRpbmciKQogICAgICAgICAgICB0LnNldGRlZmF1bHQo"
    "InJldHJ5X2NvdW50IiwgICAgICAwKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoImFja25vd2xl"
    "ZGdlZF9hdCIsICBOb25lKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoImxhc3RfdHJpZ2dlcmVk"
    "X2F0IixOb25lKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoIm5leHRfcmV0cnlfYXQiLCAgICBO"
    "b25lKQogICAgICAgICAgICB0LnNldGRlZmF1bHQoInByZV9hbm5vdW5jZWQiLCAgICBGYWxzZSkK"
    "ICAgICAgICAgICAgdC5zZXRkZWZhdWx0KCJzb3VyY2UiLCAgICAgICAgICAgImxvY2FsIikKICAg"
    "ICAgICAgICAgdC5zZXRkZWZhdWx0KCJnb29nbGVfZXZlbnRfaWQiLCAgTm9uZSkKICAgICAgICAg"
    "ICAgdC5zZXRkZWZhdWx0KCJzeW5jX3N0YXR1cyIsICAgICAgInBlbmRpbmciKQogICAgICAgICAg"
    "ICB0LnNldGRlZmF1bHQoIm1ldGFkYXRhIiwgICAgICAgICB7fSkKICAgICAgICAgICAgdC5zZXRk"
    "ZWZhdWx0KCJjcmVhdGVkX2F0IiwgICAgICAgbG9jYWxfbm93X2lzbygpKQoKICAgICAgICAgICAg"
    "IyBDb21wdXRlIHByZV90cmlnZ2VyIGlmIG1pc3NpbmcKICAgICAgICAgICAgaWYgdC5nZXQoImR1"
    "ZV9hdCIpIGFuZCBub3QgdC5nZXQoInByZV90cmlnZ2VyIik6CiAgICAgICAgICAgICAgICBkdCA9"
    "IHBhcnNlX2lzbyh0WyJkdWVfYXQiXSkKICAgICAgICAgICAgICAgIGlmIGR0OgogICAgICAgICAg"
    "ICAgICAgICAgIHByZSA9IGR0IC0gdGltZWRlbHRhKG1pbnV0ZXM9MSkKICAgICAgICAgICAgICAg"
    "ICAgICB0WyJwcmVfdHJpZ2dlciJdID0gcHJlLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIp"
    "CiAgICAgICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKCiAgICAgICAgICAgIG5vcm1hbGl6"
    "ZWQuYXBwZW5kKHQpCgogICAgICAgIGlmIGNoYW5nZWQ6CiAgICAgICAgICAgIHdyaXRlX2pzb25s"
    "KHNlbGYuX3BhdGgsIG5vcm1hbGl6ZWQpCiAgICAgICAgcmV0dXJuIG5vcm1hbGl6ZWQKCiAgICBk"
    "ZWYgc2F2ZV9hbGwoc2VsZiwgdGFza3M6IGxpc3RbZGljdF0pIC0+IE5vbmU6CiAgICAgICAgd3Jp"
    "dGVfanNvbmwoc2VsZi5fcGF0aCwgdGFza3MpCgogICAgZGVmIGFkZChzZWxmLCB0ZXh0OiBzdHIs"
    "IGR1ZV9kdDogZGF0ZXRpbWUsCiAgICAgICAgICAgIHNvdXJjZTogc3RyID0gImxvY2FsIikgLT4g"
    "ZGljdDoKICAgICAgICBwcmUgPSBkdWVfZHQgLSB0aW1lZGVsdGEobWludXRlcz0xKQogICAgICAg"
    "IHRhc2sgPSB7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgICAgICAgZiJ0YXNrX3t1dWlkLnV1"
    "aWQ0KCkuaGV4WzoxMF19IiwKICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgICAgICBsb2NhbF9u"
    "b3dfaXNvKCksCiAgICAgICAgICAgICJkdWVfYXQiOiAgICAgICAgICAgZHVlX2R0Lmlzb2Zvcm1h"
    "dCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAgICAgICAicHJlX3RyaWdnZXIiOiAgICAgIHBy"
    "ZS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwKICAgICAgICAgICAgInRleHQiOiAgICAg"
    "ICAgICAgICB0ZXh0LnN0cmlwKCksCiAgICAgICAgICAgICJzdGF0dXMiOiAgICAgICAgICAgInBl"
    "bmRpbmciLAogICAgICAgICAgICAiYWNrbm93bGVkZ2VkX2F0IjogIE5vbmUsCiAgICAgICAgICAg"
    "ICJyZXRyeV9jb3VudCI6ICAgICAgMCwKICAgICAgICAgICAgImxhc3RfdHJpZ2dlcmVkX2F0IjpO"
    "b25lLAogICAgICAgICAgICAibmV4dF9yZXRyeV9hdCI6ICAgIE5vbmUsCiAgICAgICAgICAgICJw"
    "cmVfYW5ub3VuY2VkIjogICAgRmFsc2UsCiAgICAgICAgICAgICJzb3VyY2UiOiAgICAgICAgICAg"
    "c291cmNlLAogICAgICAgICAgICAiZ29vZ2xlX2V2ZW50X2lkIjogIE5vbmUsCiAgICAgICAgICAg"
    "ICJzeW5jX3N0YXR1cyI6ICAgICAgInBlbmRpbmciLAogICAgICAgICAgICAibWV0YWRhdGEiOiAg"
    "ICAgICAgIHt9LAogICAgICAgIH0KICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAg"
    "ICAgIHRhc2tzLmFwcGVuZCh0YXNrKQogICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAg"
    "ICAgcmV0dXJuIHRhc2sKCiAgICBkZWYgdXBkYXRlX3N0YXR1cyhzZWxmLCB0YXNrX2lkOiBzdHIs"
    "IHN0YXR1czogc3RyLAogICAgICAgICAgICAgICAgICAgICAgYWNrbm93bGVkZ2VkOiBib29sID0g"
    "RmFsc2UpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHRhc2tzID0gc2VsZi5sb2FkX2FsbCgp"
    "CiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAgIGlmIHQuZ2V0KCJpZCIpID09IHRh"
    "c2tfaWQ6CiAgICAgICAgICAgICAgICB0WyJzdGF0dXMiXSA9IHN0YXR1cwogICAgICAgICAgICAg"
    "ICAgaWYgYWNrbm93bGVkZ2VkOgogICAgICAgICAgICAgICAgICAgIHRbImFja25vd2xlZGdlZF9h"
    "dCJdID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tz"
    "KQogICAgICAgICAgICAgICAgcmV0dXJuIHQKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBj"
    "b21wbGV0ZShzZWxmLCB0YXNrX2lkOiBzdHIpIC0+IE9wdGlvbmFsW2RpY3RdOgogICAgICAgIHRh"
    "c2tzID0gc2VsZi5sb2FkX2FsbCgpCiAgICAgICAgZm9yIHQgaW4gdGFza3M6CiAgICAgICAgICAg"
    "IGlmIHQuZ2V0KCJpZCIpID09IHRhc2tfaWQ6CiAgICAgICAgICAgICAgICB0WyJzdGF0dXMiXSAg"
    "ICAgICAgICA9ICJjb21wbGV0ZWQiCiAgICAgICAgICAgICAgICB0WyJhY2tub3dsZWRnZWRfYXQi"
    "XSA9IGxvY2FsX25vd19pc28oKQogICAgICAgICAgICAgICAgc2VsZi5zYXZlX2FsbCh0YXNrcykK"
    "ICAgICAgICAgICAgICAgIHJldHVybiB0CiAgICAgICAgcmV0dXJuIE5vbmUKCiAgICBkZWYgY2Fu"
    "Y2VsKHNlbGYsIHRhc2tfaWQ6IHN0cikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgdGFza3Mg"
    "PSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBmb3IgdCBpbiB0YXNrczoKICAgICAgICAgICAgaWYg"
    "dC5nZXQoImlkIikgPT0gdGFza19pZDoKICAgICAgICAgICAgICAgIHRbInN0YXR1cyJdICAgICAg"
    "ICAgID0gImNhbmNlbGxlZCIKICAgICAgICAgICAgICAgIHRbImFja25vd2xlZGdlZF9hdCJdID0g"
    "bG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgICAgICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAg"
    "ICAgICAgICAgICAgcmV0dXJuIHQKICAgICAgICByZXR1cm4gTm9uZQoKICAgIGRlZiBjbGVhcl9j"
    "b21wbGV0ZWQoc2VsZikgLT4gaW50OgogICAgICAgIHRhc2tzICAgID0gc2VsZi5sb2FkX2FsbCgp"
    "CiAgICAgICAga2VwdCAgICAgPSBbdCBmb3IgdCBpbiB0YXNrcwogICAgICAgICAgICAgICAgICAg"
    "IGlmIHQuZ2V0KCJzdGF0dXMiKSBub3QgaW4geyJjb21wbGV0ZWQiLCJjYW5jZWxsZWQifV0KICAg"
    "ICAgICByZW1vdmVkICA9IGxlbih0YXNrcykgLSBsZW4oa2VwdCkKICAgICAgICBpZiByZW1vdmVk"
    "OgogICAgICAgICAgICBzZWxmLnNhdmVfYWxsKGtlcHQpCiAgICAgICAgcmV0dXJuIHJlbW92ZWQK"
    "CiAgICBkZWYgdXBkYXRlX2dvb2dsZV9zeW5jKHNlbGYsIHRhc2tfaWQ6IHN0ciwgc3luY19zdGF0"
    "dXM6IHN0ciwKICAgICAgICAgICAgICAgICAgICAgICAgICAgZ29vZ2xlX2V2ZW50X2lkOiBzdHIg"
    "PSAiIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgZXJyb3I6IHN0ciA9ICIiKSAtPiBPcHRp"
    "b25hbFtkaWN0XToKICAgICAgICB0YXNrcyA9IHNlbGYubG9hZF9hbGwoKQogICAgICAgIGZvciB0"
    "IGluIHRhc2tzOgogICAgICAgICAgICBpZiB0LmdldCgiaWQiKSA9PSB0YXNrX2lkOgogICAgICAg"
    "ICAgICAgICAgdFsic3luY19zdGF0dXMiXSAgICA9IHN5bmNfc3RhdHVzCiAgICAgICAgICAgICAg"
    "ICB0WyJsYXN0X3N5bmNlZF9hdCJdID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgICAgICBp"
    "ZiBnb29nbGVfZXZlbnRfaWQ6CiAgICAgICAgICAgICAgICAgICAgdFsiZ29vZ2xlX2V2ZW50X2lk"
    "Il0gPSBnb29nbGVfZXZlbnRfaWQKICAgICAgICAgICAgICAgIGlmIGVycm9yOgogICAgICAgICAg"
    "ICAgICAgICAgIHQuc2V0ZGVmYXVsdCgibWV0YWRhdGEiLCB7fSkKICAgICAgICAgICAgICAgICAg"
    "ICB0WyJtZXRhZGF0YSJdWyJnb29nbGVfc3luY19lcnJvciJdID0gZXJyb3JbOjI0MF0KICAgICAg"
    "ICAgICAgICAgIHNlbGYuc2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAgICAgICByZXR1cm4gdAog"
    "ICAgICAgIHJldHVybiBOb25lCgogICAgIyDilIDilIAgRFVFIEVWRU5UIERFVEVDVElPTiDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgIGRlZiBnZXRfZHVlX2V2ZW50cyhzZWxmKSAtPiBsaXN0W3R1cGxl"
    "W3N0ciwgZGljdF1dOgogICAgICAgICIiIgogICAgICAgIENoZWNrIGFsbCB0YXNrcyBmb3IgZHVl"
    "L3ByZS10cmlnZ2VyL3JldHJ5IGV2ZW50cy4KICAgICAgICBSZXR1cm5zIGxpc3Qgb2YgKGV2ZW50"
    "X3R5cGUsIHRhc2spIHR1cGxlcy4KICAgICAgICBldmVudF90eXBlOiAicHJlIiB8ICJkdWUiIHwg"
    "InJldHJ5IgoKICAgICAgICBNb2RpZmllcyB0YXNrIHN0YXR1c2VzIGluIHBsYWNlIGFuZCBzYXZl"
    "cy4KICAgICAgICBDYWxsIGZyb20gQVBTY2hlZHVsZXIgZXZlcnkgMzAgc2Vjb25kcy4KICAgICAg"
    "ICAiIiIKICAgICAgICBub3cgICAgPSBkYXRldGltZS5ub3coKS5hc3RpbWV6b25lKCkKICAgICAg"
    "ICB0YXNrcyAgPSBzZWxmLmxvYWRfYWxsKCkKICAgICAgICBldmVudHMgPSBbXQogICAgICAgIGNo"
    "YW5nZWQgPSBGYWxzZQoKICAgICAgICBmb3IgdGFzayBpbiB0YXNrczoKICAgICAgICAgICAgaWYg"
    "dGFzay5nZXQoImFja25vd2xlZGdlZF9hdCIpOgogICAgICAgICAgICAgICAgY29udGludWUKCiAg"
    "ICAgICAgICAgIHN0YXR1cyAgID0gdGFzay5nZXQoInN0YXR1cyIsICJwZW5kaW5nIikKICAgICAg"
    "ICAgICAgZHVlICAgICAgPSBzZWxmLl9wYXJzZV9sb2NhbCh0YXNrLmdldCgiZHVlX2F0IikpCiAg"
    "ICAgICAgICAgIHByZSAgICAgID0gc2VsZi5fcGFyc2VfbG9jYWwodGFzay5nZXQoInByZV90cmln"
    "Z2VyIikpCiAgICAgICAgICAgIG5leHRfcmV0ID0gc2VsZi5fcGFyc2VfbG9jYWwodGFzay5nZXQo"
    "Im5leHRfcmV0cnlfYXQiKSkKICAgICAgICAgICAgZGVhZGxpbmUgPSBzZWxmLl9wYXJzZV9sb2Nh"
    "bCh0YXNrLmdldCgiYWxlcnRfZGVhZGxpbmUiKSkKCiAgICAgICAgICAgICMgUHJlLXRyaWdnZXIK"
    "ICAgICAgICAgICAgaWYgKHN0YXR1cyA9PSAicGVuZGluZyIgYW5kIHByZSBhbmQgbm93ID49IHBy"
    "ZQogICAgICAgICAgICAgICAgICAgIGFuZCBub3QgdGFzay5nZXQoInByZV9hbm5vdW5jZWQiKSk6"
    "CiAgICAgICAgICAgICAgICB0YXNrWyJwcmVfYW5ub3VuY2VkIl0gPSBUcnVlCiAgICAgICAgICAg"
    "ICAgICBldmVudHMuYXBwZW5kKCgicHJlIiwgdGFzaykpCiAgICAgICAgICAgICAgICBjaGFuZ2Vk"
    "ID0gVHJ1ZQoKICAgICAgICAgICAgIyBEdWUgdHJpZ2dlcgogICAgICAgICAgICBpZiBzdGF0dXMg"
    "PT0gInBlbmRpbmciIGFuZCBkdWUgYW5kIG5vdyA+PSBkdWU6CiAgICAgICAgICAgICAgICB0YXNr"
    "WyJzdGF0dXMiXSAgICAgICAgICAgPSAidHJpZ2dlcmVkIgogICAgICAgICAgICAgICAgdGFza1si"
    "bGFzdF90cmlnZ2VyZWRfYXQiXT0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgICAgICB0YXNr"
    "WyJhbGVydF9kZWFkbGluZSJdICAgPSAoCiAgICAgICAgICAgICAgICAgICAgZGF0ZXRpbWUubm93"
    "KCkuYXN0aW1lem9uZSgpICsgdGltZWRlbHRhKG1pbnV0ZXM9MykKICAgICAgICAgICAgICAgICku"
    "aXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAgICAgIGV2ZW50cy5hcHBl"
    "bmQoKCJkdWUiLCB0YXNrKSkKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAg"
    "ICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgIyBTbm9vemUgYWZ0ZXIgMy1taW51dGUgd2lu"
    "ZG93CiAgICAgICAgICAgIGlmIHN0YXR1cyA9PSAidHJpZ2dlcmVkIiBhbmQgZGVhZGxpbmUgYW5k"
    "IG5vdyA+PSBkZWFkbGluZToKICAgICAgICAgICAgICAgIHRhc2tbInN0YXR1cyJdICAgICAgICA9"
    "ICJzbm9vemVkIgogICAgICAgICAgICAgICAgdGFza1sibmV4dF9yZXRyeV9hdCJdID0gKAogICAg"
    "ICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKSArIHRpbWVkZWx0YSht"
    "aW51dGVzPTEyKQogICAgICAgICAgICAgICAgKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMi"
    "KQogICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUKICAgICAgICAgICAgICAgIGNvbnRpbnVl"
    "CgogICAgICAgICAgICAjIFJldHJ5CiAgICAgICAgICAgIGlmIHN0YXR1cyBpbiB7InJldHJ5X3Bl"
    "bmRpbmciLCJzbm9vemVkIn0gYW5kIG5leHRfcmV0IGFuZCBub3cgPj0gbmV4dF9yZXQ6CiAgICAg"
    "ICAgICAgICAgICB0YXNrWyJzdGF0dXMiXSAgICAgICAgICAgID0gInRyaWdnZXJlZCIKICAgICAg"
    "ICAgICAgICAgIHRhc2tbInJldHJ5X2NvdW50Il0gICAgICAgPSBpbnQodGFzay5nZXQoInJldHJ5"
    "X2NvdW50IiwwKSkgKyAxCiAgICAgICAgICAgICAgICB0YXNrWyJsYXN0X3RyaWdnZXJlZF9hdCJd"
    "ID0gbG9jYWxfbm93X2lzbygpCiAgICAgICAgICAgICAgICB0YXNrWyJhbGVydF9kZWFkbGluZSJd"
    "ICAgID0gKAogICAgICAgICAgICAgICAgICAgIGRhdGV0aW1lLm5vdygpLmFzdGltZXpvbmUoKSAr"
    "IHRpbWVkZWx0YShtaW51dGVzPTMpCiAgICAgICAgICAgICAgICApLmlzb2Zvcm1hdCh0aW1lc3Bl"
    "Yz0ic2Vjb25kcyIpCiAgICAgICAgICAgICAgICB0YXNrWyJuZXh0X3JldHJ5X2F0Il0gICAgID0g"
    "Tm9uZQogICAgICAgICAgICAgICAgZXZlbnRzLmFwcGVuZCgoInJldHJ5IiwgdGFzaykpCiAgICAg"
    "ICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQoKICAgICAgICBpZiBjaGFuZ2VkOgogICAgICAgICAg"
    "ICBzZWxmLnNhdmVfYWxsKHRhc2tzKQogICAgICAgIHJldHVybiBldmVudHMKCiAgICBkZWYgX3Bh"
    "cnNlX2xvY2FsKHNlbGYsIHZhbHVlOiBzdHIpIC0+IE9wdGlvbmFsW2RhdGV0aW1lXToKICAgICAg"
    "ICAiIiJQYXJzZSBJU08gc3RyaW5nIHRvIHRpbWV6b25lLWF3YXJlIGRhdGV0aW1lIGZvciBjb21w"
    "YXJpc29uLiIiIgogICAgICAgIGR0ID0gcGFyc2VfaXNvKHZhbHVlKQogICAgICAgIGlmIGR0IGlz"
    "IE5vbmU6CiAgICAgICAgICAgIHJldHVybiBOb25lCiAgICAgICAgaWYgZHQudHppbmZvIGlzIE5v"
    "bmU6CiAgICAgICAgICAgIGR0ID0gZHQuYXN0aW1lem9uZSgpCiAgICAgICAgcmV0dXJuIGR0Cgog"
    "ICAgIyDilIDilIAgTkFUVVJBTCBMQU5HVUFHRSBQQVJTSU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgQHN0YXRpY21ldGhv"
    "ZAogICAgZGVmIGNsYXNzaWZ5X2ludGVudCh0ZXh0OiBzdHIpIC0+IGRpY3Q6CiAgICAgICAgIiIi"
    "CiAgICAgICAgQ2xhc3NpZnkgdXNlciBpbnB1dCBhcyB0YXNrL3JlbWluZGVyL3RpbWVyL2NoYXQu"
    "CiAgICAgICAgUmV0dXJucyB7ImludGVudCI6IHN0ciwgImNsZWFuZWRfaW5wdXQiOiBzdHJ9CiAg"
    "ICAgICAgIiIiCiAgICAgICAgaW1wb3J0IHJlCiAgICAgICAgIyBTdHJpcCBjb21tb24gaW52b2Nh"
    "dGlvbiBwcmVmaXhlcwogICAgICAgIGNsZWFuZWQgPSByZS5zdWIoCiAgICAgICAgICAgIHJmIl5c"
    "cyooPzp7REVDS19OQU1FLmxvd2VyKCl9fGhleVxzK3tERUNLX05BTUUubG93ZXIoKX0pXHMqLD9c"
    "cypbOlwtXT9ccyoiLAogICAgICAgICAgICAiIiwgdGV4dCwgZmxhZ3M9cmUuSQogICAgICAgICku"
    "c3RyaXAoKQoKICAgICAgICBsb3cgPSBjbGVhbmVkLmxvd2VyKCkKCiAgICAgICAgdGltZXJfcGF0"
    "cyAgICA9IFtyIlxic2V0KD86XHMrYSk/XHMrdGltZXJcYiIsIHIiXGJ0aW1lclxzK2ZvclxiIiwK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgIHIiXGJzdGFydCg/OlxzK2EpP1xzK3RpbWVyXGIiXQog"
    "ICAgICAgIHJlbWluZGVyX3BhdHMgPSBbciJcYnJlbWluZCBtZVxiIiwgciJcYnNldCg/OlxzK2Ep"
    "P1xzK3JlbWluZGVyXGIiLAogICAgICAgICAgICAgICAgICAgICAgICAgciJcYmFkZCg/OlxzK2Ep"
    "P1xzK3JlbWluZGVyXGIiLAogICAgICAgICAgICAgICAgICAgICAgICAgciJcYnNldCg/OlxzK2Fu"
    "Pyk/XHMrYWxhcm1cYiIsIHIiXGJhbGFybVxzK2ZvclxiIl0KICAgICAgICB0YXNrX3BhdHMgICAg"
    "ID0gW3IiXGJhZGQoPzpccythKT9ccyt0YXNrXGIiLAogICAgICAgICAgICAgICAgICAgICAgICAg"
    "ciJcYmNyZWF0ZSg/OlxzK2EpP1xzK3Rhc2tcYiIsIHIiXGJuZXdccyt0YXNrXGIiXQoKICAgICAg"
    "ICBpbXBvcnQgcmUgYXMgX3JlCiAgICAgICAgaWYgYW55KF9yZS5zZWFyY2gocCwgbG93KSBmb3Ig"
    "cCBpbiB0aW1lcl9wYXRzKToKICAgICAgICAgICAgaW50ZW50ID0gInRpbWVyIgogICAgICAgIGVs"
    "aWYgYW55KF9yZS5zZWFyY2gocCwgbG93KSBmb3IgcCBpbiByZW1pbmRlcl9wYXRzKToKICAgICAg"
    "ICAgICAgaW50ZW50ID0gInJlbWluZGVyIgogICAgICAgIGVsaWYgYW55KF9yZS5zZWFyY2gocCwg"
    "bG93KSBmb3IgcCBpbiB0YXNrX3BhdHMpOgogICAgICAgICAgICBpbnRlbnQgPSAidGFzayIKICAg"
    "ICAgICBlbHNlOgogICAgICAgICAgICBpbnRlbnQgPSAiY2hhdCIKCiAgICAgICAgcmV0dXJuIHsi"
    "aW50ZW50IjogaW50ZW50LCAiY2xlYW5lZF9pbnB1dCI6IGNsZWFuZWR9CgogICAgQHN0YXRpY21l"
    "dGhvZAogICAgZGVmIHBhcnNlX2R1ZV9kYXRldGltZSh0ZXh0OiBzdHIpIC0+IE9wdGlvbmFsW2Rh"
    "dGV0aW1lXToKICAgICAgICAiIiIKICAgICAgICBQYXJzZSBuYXR1cmFsIGxhbmd1YWdlIHRpbWUg"
    "ZXhwcmVzc2lvbiBmcm9tIHRhc2sgdGV4dC4KICAgICAgICBIYW5kbGVzOiAiaW4gMzAgbWludXRl"
    "cyIsICJhdCAzcG0iLCAidG9tb3Jyb3cgYXQgOWFtIiwKICAgICAgICAgICAgICAgICAiaW4gMiBo"
    "b3VycyIsICJhdCAxNTozMCIsIGV0Yy4KICAgICAgICBSZXR1cm5zIGEgZGF0ZXRpbWUgb3IgTm9u"
    "ZSBpZiB1bnBhcnNlYWJsZS4KICAgICAgICAiIiIKICAgICAgICBpbXBvcnQgcmUKICAgICAgICBu"
    "b3cgID0gZGF0ZXRpbWUubm93KCkKICAgICAgICBsb3cgID0gdGV4dC5sb3dlcigpLnN0cmlwKCkK"
    "CiAgICAgICAgIyAiaW4gWCBtaW51dGVzL2hvdXJzL2RheXMiCiAgICAgICAgbSA9IHJlLnNlYXJj"
    "aCgKICAgICAgICAgICAgciJpblxzKyhcZCspXHMqKG1pbnV0ZXxtaW58aG91cnxocnxkYXl8c2Vj"
    "b25kfHNlYykiLAogICAgICAgICAgICBsb3cKICAgICAgICApCiAgICAgICAgaWYgbToKICAgICAg"
    "ICAgICAgbiAgICA9IGludChtLmdyb3VwKDEpKQogICAgICAgICAgICB1bml0ID0gbS5ncm91cCgy"
    "KQogICAgICAgICAgICBpZiAibWluIiBpbiB1bml0OiAgcmV0dXJuIG5vdyArIHRpbWVkZWx0YSht"
    "aW51dGVzPW4pCiAgICAgICAgICAgIGlmICJob3VyIiBpbiB1bml0IG9yICJociIgaW4gdW5pdDog"
    "cmV0dXJuIG5vdyArIHRpbWVkZWx0YShob3Vycz1uKQogICAgICAgICAgICBpZiAiZGF5IiAgaW4g"
    "dW5pdDogcmV0dXJuIG5vdyArIHRpbWVkZWx0YShkYXlzPW4pCiAgICAgICAgICAgIGlmICJzZWMi"
    "ICBpbiB1bml0OiByZXR1cm4gbm93ICsgdGltZWRlbHRhKHNlY29uZHM9bikKCiAgICAgICAgIyAi"
    "YXQgSEg6TU0iIG9yICJhdCBIOk1NYW0vcG0iCiAgICAgICAgbSA9IHJlLnNlYXJjaCgKICAgICAg"
    "ICAgICAgciJhdFxzKyhcZHsxLDJ9KSg/OjooXGR7Mn0pKT9ccyooYW18cG0pPyIsCiAgICAgICAg"
    "ICAgIGxvdwogICAgICAgICkKICAgICAgICBpZiBtOgogICAgICAgICAgICBociAgPSBpbnQobS5n"
    "cm91cCgxKSkKICAgICAgICAgICAgbW4gID0gaW50KG0uZ3JvdXAoMikpIGlmIG0uZ3JvdXAoMikg"
    "ZWxzZSAwCiAgICAgICAgICAgIGFwbSA9IG0uZ3JvdXAoMykKICAgICAgICAgICAgaWYgYXBtID09"
    "ICJwbSIgYW5kIGhyIDwgMTI6IGhyICs9IDEyCiAgICAgICAgICAgIGlmIGFwbSA9PSAiYW0iIGFu"
    "ZCBociA9PSAxMjogaHIgPSAwCiAgICAgICAgICAgIGR0ID0gbm93LnJlcGxhY2UoaG91cj1ociwg"
    "bWludXRlPW1uLCBzZWNvbmQ9MCwgbWljcm9zZWNvbmQ9MCkKICAgICAgICAgICAgaWYgZHQgPD0g"
    "bm93OgogICAgICAgICAgICAgICAgZHQgKz0gdGltZWRlbHRhKGRheXM9MSkKICAgICAgICAgICAg"
    "cmV0dXJuIGR0CgogICAgICAgICMgInRvbW9ycm93IGF0IC4uLiIgIChyZWN1cnNlIG9uIHRoZSAi"
    "YXQiIHBhcnQpCiAgICAgICAgaWYgInRvbW9ycm93IiBpbiBsb3c6CiAgICAgICAgICAgIHRvbW9y"
    "cm93X3RleHQgPSByZS5zdWIociJ0b21vcnJvdyIsICIiLCBsb3cpLnN0cmlwKCkKICAgICAgICAg"
    "ICAgcmVzdWx0ID0gVGFza01hbmFnZXIucGFyc2VfZHVlX2RhdGV0aW1lKHRvbW9ycm93X3RleHQp"
    "CiAgICAgICAgICAgIGlmIHJlc3VsdDoKICAgICAgICAgICAgICAgIHJldHVybiByZXN1bHQgKyB0"
    "aW1lZGVsdGEoZGF5cz0xKQoKICAgICAgICByZXR1cm4gTm9uZQoKCiMg4pSA4pSAIFJFUVVJUkVN"
    "RU5UUy5UWFQgR0VORVJBVE9SIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgd3Jp"
    "dGVfcmVxdWlyZW1lbnRzX3R4dCgpIC0+IE5vbmU6CiAgICAiIiIKICAgIFdyaXRlIHJlcXVpcmVt"
    "ZW50cy50eHQgbmV4dCB0byB0aGUgZGVjayBmaWxlIG9uIGZpcnN0IHJ1bi4KICAgIEhlbHBzIHVz"
    "ZXJzIGluc3RhbGwgYWxsIGRlcGVuZGVuY2llcyB3aXRoIG9uZSBwaXAgY29tbWFuZC4KICAgICIi"
    "IgogICAgcmVxX3BhdGggPSBQYXRoKENGRy5nZXQoImJhc2VfZGlyIiwgc3RyKFNDUklQVF9ESVIp"
    "KSkgLyAicmVxdWlyZW1lbnRzLnR4dCIKICAgIGlmIHJlcV9wYXRoLmV4aXN0cygpOgogICAgICAg"
    "IHJldHVybgoKICAgIGNvbnRlbnQgPSAiIiJcCiMgTW9yZ2FubmEgRGVjayDigJQgUmVxdWlyZWQg"
    "RGVwZW5kZW5jaWVzCiMgSW5zdGFsbCBhbGwgd2l0aDogcGlwIGluc3RhbGwgLXIgcmVxdWlyZW1l"
    "bnRzLnR4dAoKIyBDb3JlIFVJClB5U2lkZTYKCiMgU2NoZWR1bGluZyAoaWRsZSB0aW1lciwgYXV0"
    "b3NhdmUsIHJlZmxlY3Rpb24gY3ljbGVzKQphcHNjaGVkdWxlcgoKIyBMb2dnaW5nCmxvZ3VydQoK"
    "IyBTb3VuZCBwbGF5YmFjayAoV0FWICsgTVAzKQpweWdhbWUKCiMgRGVza3RvcCBzaG9ydGN1dCBj"
    "cmVhdGlvbiAoV2luZG93cyBvbmx5KQpweXdpbjMyCgojIFN5c3RlbSBtb25pdG9yaW5nIChDUFUs"
    "IFJBTSwgZHJpdmVzLCBuZXR3b3JrKQpwc3V0aWwKCiMgSFRUUCByZXF1ZXN0cwpyZXF1ZXN0cwoK"
    "IyBHb29nbGUgaW50ZWdyYXRpb24gKENhbGVuZGFyLCBEcml2ZSwgRG9jcywgR21haWwpCmdvb2ds"
    "ZS1hcGktcHl0aG9uLWNsaWVudApnb29nbGUtYXV0aC1vYXV0aGxpYgpnb29nbGUtYXV0aAoKIyDi"
    "lIDilIAgT3B0aW9uYWwgKGxvY2FsIG1vZGVsIG9ubHkpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAojIFVuY29tbWVudCBpZiB1c2luZyBhIGxvY2FsIEh1Z2dpbmdGYWNlIG1vZGVsOgojIHRvcmNo"
    "CiMgdHJhbnNmb3JtZXJzCiMgYWNjZWxlcmF0ZQoKIyDilIDilIAgT3B0aW9uYWwgKE5WSURJQSBH"
    "UFUgbW9uaXRvcmluZykg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgVW5jb21tZW50IGlmIHlvdSBoYXZlIGFuIE5WSURJQSBH"
    "UFU6CiMgcHludm1sCiIiIgogICAgcmVxX3BhdGgud3JpdGVfdGV4dChjb250ZW50LCBlbmNvZGlu"
    "Zz0idXRmLTgiKQoKCiMg4pSA4pSAIFBBU1MgNCBDT01QTEVURSDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBNZW1vcnksIFNl"
    "c3Npb24sIExlc3NvbnNMZWFybmVkLCBUYXNrTWFuYWdlciBhbGwgZGVmaW5lZC4KIyBMU0wgRm9y"
    "YmlkZGVuIFJ1bGVzZXQgYXV0by1zZWVkZWQgb24gZmlyc3QgcnVuLgojIHJlcXVpcmVtZW50cy50"
    "eHQgd3JpdHRlbiBvbiBmaXJzdCBydW4uCiMKIyBOZXh0OiBQYXNzIDUg4oCUIFRhYiBDb250ZW50"
    "IENsYXNzZXMKIyAoU0xTY2Fuc1RhYiwgU0xDb21tYW5kc1RhYiwgSm9iVHJhY2tlclRhYiwgUmVj"
    "b3Jkc1RhYiwKIyAgVGFza3NUYWIsIFNlbGZUYWIsIERpYWdub3N0aWNzVGFiKQoKCiMg4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ4pWQ"
    "4pWQCiMgTU9SR0FOTkEgREVDSyDigJQgUEFTUyA1OiBUQUIgQ09OVEVOVCBDTEFTU0VTCiMKIyBU"
    "YWJzIGRlZmluZWQgaGVyZToKIyAgIFNMU2NhbnNUYWIgICAgICDigJQgZ3JpbW9pcmUtY2FyZCBz"
    "dHlsZSwgcmVidWlsdCAoRGVsZXRlIGFkZGVkLCBNb2RpZnkgZml4ZWQsCiMgICAgICAgICAgICAg"
    "ICAgICAgICBwYXJzZXIgZml4ZWQsIGNvcHktdG8tY2xpcGJvYXJkIHBlciBpdGVtKQojICAgU0xD"
    "b21tYW5kc1RhYiAgIOKAlCBnb3RoaWMgdGFibGUsIGNvcHkgY29tbWFuZCB0byBjbGlwYm9hcmQK"
    "IyAgIEpvYlRyYWNrZXJUYWIgICDigJQgZnVsbCByZWJ1aWxkIGZyb20gc3BlYywgQ1NWL1RTViBl"
    "eHBvcnQKIyAgIFJlY29yZHNUYWIgICAgICDigJQgR29vZ2xlIERyaXZlL0RvY3Mgd29ya3NwYWNl"
    "CiMgICBUYXNrc1RhYiAgICAgICAg4oCUIHRhc2sgcmVnaXN0cnkgKyBtaW5pIGNhbGVuZGFyCiMg"
    "ICBTZWxmVGFiICAgICAgICAg4oCUIGlkbGUgbmFycmF0aXZlIG91dHB1dCArIFBvSSBsaXN0CiMg"
    "ICBEaWFnbm9zdGljc1RhYiAg4oCUIGxvZ3VydSBvdXRwdXQgKyBoYXJkd2FyZSByZXBvcnQgKyBq"
    "b3VybmFsIGxvYWQgbm90aWNlcwojICAgTGVzc29uc1RhYiAgICAgIOKAlCBMU0wgRm9yYmlkZGVu"
    "IFJ1bGVzZXQgKyBjb2RlIGxlc3NvbnMgYnJvd3NlcgojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkAoKaW1wb3J0IHJlIGFz"
    "IF9yZQoKCiMg4pSA4pSAIFNIQVJFRCBHT1RISUMgVEFCTEUgU1RZTEUg4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBfZ290aGljX3RhYmxlX3N0eWxlKCkgLT4gc3RyOgogICAg"
    "cmV0dXJuIGYiIiIKICAgICAgICBRVGFibGVXaWRnZXQge3sKICAgICAgICAgICAgYmFja2dyb3Vu"
    "ZDoge0NfQkcyfTsKICAgICAgICAgICAgY29sb3I6IHtDX0dPTER9OwogICAgICAgICAgICBib3Jk"
    "ZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICAgICAgICAgIGdyaWRsaW5lLWNvbG9y"
    "OiB7Q19CT1JERVJ9OwogICAgICAgICAgICBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlm"
    "OwogICAgICAgICAgICBmb250LXNpemU6IDExcHg7CiAgICAgICAgfX0KICAgICAgICBRVGFibGVX"
    "aWRnZXQ6Oml0ZW06c2VsZWN0ZWQge3sKICAgICAgICAgICAgYmFja2dyb3VuZDoge0NfQ1JJTVNP"
    "Tl9ESU19OwogICAgICAgICAgICBjb2xvcjoge0NfR09MRF9CUklHSFR9OwogICAgICAgIH19CiAg"
    "ICAgICAgUVRhYmxlV2lkZ2V0OjppdGVtOmFsdGVybmF0ZSB7ewogICAgICAgICAgICBiYWNrZ3Jv"
    "dW5kOiB7Q19CRzN9OwogICAgICAgIH19CiAgICAgICAgUUhlYWRlclZpZXc6OnNlY3Rpb24ge3sK"
    "ICAgICAgICAgICAgYmFja2dyb3VuZDoge0NfQkczfTsKICAgICAgICAgICAgY29sb3I6IHtDX0dP"
    "TER9OwogICAgICAgICAgICBib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07CiAgICAg"
    "ICAgICAgIHBhZGRpbmc6IDRweCA2cHg7CiAgICAgICAgICAgIGZvbnQtZmFtaWx5OiB7REVDS19G"
    "T05UfSwgc2VyaWY7CiAgICAgICAgICAgIGZvbnQtc2l6ZTogMTBweDsKICAgICAgICAgICAgZm9u"
    "dC13ZWlnaHQ6IGJvbGQ7CiAgICAgICAgICAgIGxldHRlci1zcGFjaW5nOiAxcHg7CiAgICAgICAg"
    "fX0KICAgICIiIgoKZGVmIF9nb3RoaWNfYnRuKHRleHQ6IHN0ciwgdG9vbHRpcDogc3RyID0gIiIp"
    "IC0+IFFQdXNoQnV0dG9uOgogICAgYnRuID0gUVB1c2hCdXR0b24odGV4dCkKICAgIGJ0bi5zZXRT"
    "dHlsZVNoZWV0KAogICAgICAgIGYiYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyBjb2xvcjog"
    "e0NfR09MRH07ICIKICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OyBib3Jk"
    "ZXItcmFkaXVzOiAycHg7ICIKICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2Vy"
    "aWY7IGZvbnQtc2l6ZTogMTBweDsgIgogICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRp"
    "bmc6IDRweCAxMHB4OyBsZXR0ZXItc3BhY2luZzogMXB4OyIKICAgICkKICAgIGlmIHRvb2x0aXA6"
    "CiAgICAgICAgYnRuLnNldFRvb2xUaXAodG9vbHRpcCkKICAgIHJldHVybiBidG4KCmRlZiBfc2Vj"
    "dGlvbl9sYmwodGV4dDogc3RyKSAtPiBRTGFiZWw6CiAgICBsYmwgPSBRTGFiZWwodGV4dCkKICAg"
    "IGxibC5zZXRTdHlsZVNoZWV0KAogICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250LXNpemU6"
    "IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICBmImxldHRlci1zcGFjaW5nOiAycHg7"
    "IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgKQogICAgcmV0dXJuIGxibAoK"
    "CiMg4pSA4pSAIFNMIFNDQU5TIFRBQiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKY2xhc3MgU0xTY2Fuc1RhYihR"
    "V2lkZ2V0KToKICAgICIiIgogICAgU2Vjb25kIExpZmUgYXZhdGFyIHNjYW5uZXIgcmVzdWx0cyBt"
    "YW5hZ2VyLgogICAgUmVidWlsdCBmcm9tIHNwZWM6CiAgICAgIC0gQ2FyZC9ncmltb2lyZS1lbnRy"
    "eSBzdHlsZSBkaXNwbGF5CiAgICAgIC0gQWRkICh3aXRoIHRpbWVzdGFtcC1hd2FyZSBwYXJzZXIp"
    "CiAgICAgIC0gRGlzcGxheSAoY2xlYW4gaXRlbS9jcmVhdG9yIHRhYmxlKQogICAgICAtIE1vZGlm"
    "eSAoZWRpdCBuYW1lLCBkZXNjcmlwdGlvbiwgaW5kaXZpZHVhbCBpdGVtcykKICAgICAgLSBEZWxl"
    "dGUgKHdhcyBtaXNzaW5nIOKAlCBub3cgcHJlc2VudCkKICAgICAgLSBSZS1wYXJzZSAod2FzICdS"
    "ZWZyZXNoJyDigJQgcmUtcnVucyBwYXJzZXIgb24gc3RvcmVkIHJhdyB0ZXh0KQogICAgICAtIENv"
    "cHktdG8tY2xpcGJvYXJkIG9uIGFueSBpdGVtCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2Vs"
    "ZiwgbWVtb3J5X2RpcjogUGF0aCwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0"
    "X18ocGFyZW50KQogICAgICAgIHNlbGYuX3BhdGggICAgPSBjZmdfcGF0aCgic2wiKSAvICJzbF9z"
    "Y2Fucy5qc29ubCIKICAgICAgICBzZWxmLl9yZWNvcmRzOiBsaXN0W2RpY3RdID0gW10KICAgICAg"
    "ICBzZWxmLl9zZWxlY3RlZF9pZDogT3B0aW9uYWxbc3RyXSA9IE5vbmUKICAgICAgICBzZWxmLl9z"
    "ZXR1cF91aSgpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5z"
    "ZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkK"
    "CiAgICAgICAgIyBCdXR0b24gYmFyCiAgICAgICAgYmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAg"
    "IHNlbGYuX2J0bl9hZGQgICAgID0gX2dvdGhpY19idG4oIuKcpiBBZGQiLCAgICAgIkFkZCBhIG5l"
    "dyBzY2FuIikKICAgICAgICBzZWxmLl9idG5fZGlzcGxheSA9IF9nb3RoaWNfYnRuKCLinacgRGlz"
    "cGxheSIsICJTaG93IHNlbGVjdGVkIHNjYW4gZGV0YWlscyIpCiAgICAgICAgc2VsZi5fYnRuX21v"
    "ZGlmeSAgPSBfZ290aGljX2J0bigi4pynIE1vZGlmeSIsICAiRWRpdCBzZWxlY3RlZCBzY2FuIikK"
    "ICAgICAgICBzZWxmLl9idG5fZGVsZXRlICA9IF9nb3RoaWNfYnRuKCLinJcgRGVsZXRlIiwgICJE"
    "ZWxldGUgc2VsZWN0ZWQgc2NhbiIpCiAgICAgICAgc2VsZi5fYnRuX3JlcGFyc2UgPSBfZ290aGlj"
    "X2J0bigi4oa7IFJlLXBhcnNlIiwiUmUtcGFyc2UgcmF3IHRleHQgb2Ygc2VsZWN0ZWQgc2NhbiIp"
    "CiAgICAgICAgc2VsZi5fYnRuX2FkZC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fc2hvd19hZGQpCiAg"
    "ICAgICAgc2VsZi5fYnRuX2Rpc3BsYXkuY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Nob3dfZGlzcGxh"
    "eSkKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5LmNsaWNrZWQuY29ubmVjdChzZWxmLl9zaG93X21v"
    "ZGlmeSkKICAgICAgICBzZWxmLl9idG5fZGVsZXRlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19k"
    "ZWxldGUpCiAgICAgICAgc2VsZi5fYnRuX3JlcGFyc2UuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2Rv"
    "X3JlcGFyc2UpCiAgICAgICAgZm9yIGIgaW4gKHNlbGYuX2J0bl9hZGQsIHNlbGYuX2J0bl9kaXNw"
    "bGF5LCBzZWxmLl9idG5fbW9kaWZ5LAogICAgICAgICAgICAgICAgICBzZWxmLl9idG5fZGVsZXRl"
    "LCBzZWxmLl9idG5fcmVwYXJzZSk6CiAgICAgICAgICAgIGJhci5hZGRXaWRnZXQoYikKICAgICAg"
    "ICBiYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYmFyKQoKICAgICAgICAj"
    "IFN0YWNrOiBsaXN0IHZpZXcgfCBhZGQgZm9ybSB8IGRpc3BsYXkgfCBtb2RpZnkKICAgICAgICBz"
    "ZWxmLl9zdGFjayA9IFFTdGFja2VkV2lkZ2V0KCkKICAgICAgICByb290LmFkZFdpZGdldChzZWxm"
    "Ll9zdGFjaywgMSkKCiAgICAgICAgIyDilIDilIAgUEFHRSAwOiBzY2FuIGxpc3QgKGdyaW1vaXJl"
    "IGNhcmRzKSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBwMCA9IFFXaWRnZXQoKQogICAgICAgIGww"
    "ID0gUVZCb3hMYXlvdXQocDApCiAgICAgICAgbDAuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAs"
    "IDApCiAgICAgICAgc2VsZi5fY2FyZF9zY3JvbGwgPSBRU2Nyb2xsQXJlYSgpCiAgICAgICAgc2Vs"
    "Zi5fY2FyZF9zY3JvbGwuc2V0V2lkZ2V0UmVzaXphYmxlKFRydWUpCiAgICAgICAgc2VsZi5fY2Fy"
    "ZF9zY3JvbGwuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtDX0JHMn07IGJvcmRlcjogbm9u"
    "ZTsiKQogICAgICAgIHNlbGYuX2NhcmRfY29udGFpbmVyID0gUVdpZGdldCgpCiAgICAgICAgc2Vs"
    "Zi5fY2FyZF9sYXlvdXQgICAgPSBRVkJveExheW91dChzZWxmLl9jYXJkX2NvbnRhaW5lcikKICAg"
    "ICAgICBzZWxmLl9jYXJkX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwgNCkKICAg"
    "ICAgICBzZWxmLl9jYXJkX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgc2VsZi5fY2FyZF9s"
    "YXlvdXQuYWRkU3RyZXRjaCgpCiAgICAgICAgc2VsZi5fY2FyZF9zY3JvbGwuc2V0V2lkZ2V0KHNl"
    "bGYuX2NhcmRfY29udGFpbmVyKQogICAgICAgIGwwLmFkZFdpZGdldChzZWxmLl9jYXJkX3Njcm9s"
    "bCkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDApCgogICAgICAgICMg4pSA4pSAIFBB"
    "R0UgMTogYWRkIGZvcm0g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcDEgPSBRV2lkZ2V0KCkKICAgICAg"
    "ICBsMSA9IFFWQm94TGF5b3V0KHAxKQogICAgICAgIGwxLnNldENvbnRlbnRzTWFyZ2lucyg0LCA0"
    "LCA0LCA0KQogICAgICAgIGwxLnNldFNwYWNpbmcoNCkKICAgICAgICBsMS5hZGRXaWRnZXQoX3Nl"
    "Y3Rpb25fbGJsKCLinacgU0NBTiBOQU1FIChhdXRvLWRldGVjdGVkKSIpKQogICAgICAgIHNlbGYu"
    "X2FkZF9uYW1lICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5fYWRkX25hbWUuc2V0UGxhY2Vo"
    "b2xkZXJUZXh0KCJBdXRvLWRldGVjdGVkIGZyb20gc2NhbiB0ZXh0IikKICAgICAgICBsMS5hZGRX"
    "aWRnZXQoc2VsZi5fYWRkX25hbWUpCiAgICAgICAgbDEuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi"
    "4p2nIERFU0NSSVBUSU9OIikpCiAgICAgICAgc2VsZi5fYWRkX2Rlc2MgID0gUVRleHRFZGl0KCkK"
    "ICAgICAgICBzZWxmLl9hZGRfZGVzYy5zZXRNYXhpbXVtSGVpZ2h0KDYwKQogICAgICAgIGwxLmFk"
    "ZFdpZGdldChzZWxmLl9hZGRfZGVzYykKICAgICAgICBsMS5hZGRXaWRnZXQoX3NlY3Rpb25fbGJs"
    "KCLinacgUkFXIFNDQU4gVEVYVCAocGFzdGUgaGVyZSkiKSkKICAgICAgICBzZWxmLl9hZGRfcmF3"
    "ICAgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2FkZF9yYXcuc2V0UGxhY2Vob2xkZXJUZXh0"
    "KAogICAgICAgICAgICAiUGFzdGUgdGhlIHJhdyBTZWNvbmQgTGlmZSBzY2FuIG91dHB1dCBoZXJl"
    "LlxuIgogICAgICAgICAgICAiVGltZXN0YW1wcyBsaWtlIFsxMTo0N10gd2lsbCBiZSB1c2VkIHRv"
    "IHNwbGl0IGl0ZW1zIGNvcnJlY3RseS4iCiAgICAgICAgKQogICAgICAgIGwxLmFkZFdpZGdldChz"
    "ZWxmLl9hZGRfcmF3LCAxKQogICAgICAgICMgUHJldmlldyBvZiBwYXJzZWQgaXRlbXMKICAgICAg"
    "ICBsMS5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgUEFSU0VEIElURU1TIFBSRVZJRVciKSkK"
    "ICAgICAgICBzZWxmLl9hZGRfcHJldmlldyA9IFFUYWJsZVdpZGdldCgwLCAyKQogICAgICAgIHNl"
    "bGYuX2FkZF9wcmV2aWV3LnNldEhvcml6b250YWxIZWFkZXJMYWJlbHMoWyJJdGVtIiwgIkNyZWF0"
    "b3IiXSkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2Vj"
    "dGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3Ry"
    "ZXRjaCkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2Vj"
    "dGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3Ry"
    "ZXRjaCkKICAgICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRNYXhpbXVtSGVpZ2h0KDEyMCkKICAg"
    "ICAgICBzZWxmLl9hZGRfcHJldmlldy5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5bGUo"
    "KSkKICAgICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fYWRkX3ByZXZpZXcpCiAgICAgICAgc2VsZi5f"
    "YWRkX3Jhdy50ZXh0Q2hhbmdlZC5jb25uZWN0KHNlbGYuX3ByZXZpZXdfcGFyc2UpCgogICAgICAg"
    "IGJ0bnMxID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHMxID0gX2dvdGhpY19idG4oIuKcpiBTYXZl"
    "Iik7IGMxID0gX2dvdGhpY19idG4oIuKclyBDYW5jZWwiKQogICAgICAgIHMxLmNsaWNrZWQuY29u"
    "bmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgYzEuY2xpY2tlZC5jb25uZWN0KGxhbWJkYTogc2Vs"
    "Zi5fc3RhY2suc2V0Q3VycmVudEluZGV4KDApKQogICAgICAgIGJ0bnMxLmFkZFdpZGdldChzMSk7"
    "IGJ0bnMxLmFkZFdpZGdldChjMSk7IGJ0bnMxLmFkZFN0cmV0Y2goKQogICAgICAgIGwxLmFkZExh"
    "eW91dChidG5zMSkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDEpCgogICAgICAgICMg"
    "4pSA4pSAIFBBR0UgMjogZGlzcGxheSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBwMiA9IFFXaWRn"
    "ZXQoKQogICAgICAgIGwyID0gUVZCb3hMYXlvdXQocDIpCiAgICAgICAgbDIuc2V0Q29udGVudHNN"
    "YXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZi5fZGlzcF9uYW1lICA9IFFMYWJlbCgpCiAg"
    "ICAgICAgc2VsZi5fZGlzcF9uYW1lLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6"
    "IHtDX0dPTERfQlJJR0hUfTsgZm9udC1zaXplOiAxM3B4OyBmb250LXdlaWdodDogYm9sZDsgIgog"
    "ICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkK"
    "ICAgICAgICBzZWxmLl9kaXNwX2Rlc2MgID0gUUxhYmVsKCkKICAgICAgICBzZWxmLl9kaXNwX2Rl"
    "c2Muc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBzZWxmLl9kaXNwX2Rlc2Muc2V0U3R5bGVTaGVl"
    "dCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDEwcHg7IGZv"
    "bnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBzZWxmLl9k"
    "aXNwX3RhYmxlID0gUVRhYmxlV2lkZ2V0KDAsIDIpCiAgICAgICAgc2VsZi5fZGlzcF90YWJsZS5z"
    "ZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKFsiSXRlbSIsICJDcmVhdG9yIl0pCiAgICAgICAgc2Vs"
    "Zi5fZGlzcF90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAg"
    "ICAgICAgICAgIDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxm"
    "Ll9kaXNwX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKS5zZXRTZWN0aW9uUmVzaXplTW9kZSgKICAg"
    "ICAgICAgICAgMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgIHNlbGYu"
    "X2Rpc3BfdGFibGUuc2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAg"
    "c2VsZi5fZGlzcF90YWJsZS5zZXRDb250ZXh0TWVudVBvbGljeSgKICAgICAgICAgICAgUXQuQ29u"
    "dGV4dE1lbnVQb2xpY3kuQ3VzdG9tQ29udGV4dE1lbnUpCiAgICAgICAgc2VsZi5fZGlzcF90YWJs"
    "ZS5jdXN0b21Db250ZXh0TWVudVJlcXVlc3RlZC5jb25uZWN0KAogICAgICAgICAgICBzZWxmLl9p"
    "dGVtX2NvbnRleHRfbWVudSkKCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2Rpc3BfbmFtZSkK"
    "ICAgICAgICBsMi5hZGRXaWRnZXQoc2VsZi5fZGlzcF9kZXNjKQogICAgICAgIGwyLmFkZFdpZGdl"
    "dChzZWxmLl9kaXNwX3RhYmxlLCAxKQoKICAgICAgICBjb3B5X2hpbnQgPSBRTGFiZWwoIlJpZ2h0"
    "LWNsaWNrIGFueSBpdGVtIHRvIGNvcHkgaXQgdG8gY2xpcGJvYXJkLiIpCiAgICAgICAgY29weV9o"
    "aW50LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX1RFWFRfRElNfTsgZm9u"
    "dC1zaXplOiA5cHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkK"
    "ICAgICAgICBsMi5hZGRXaWRnZXQoY29weV9oaW50KQoKICAgICAgICBiazIgPSBfZ290aGljX2J0"
    "bigi4peAIEJhY2siKQogICAgICAgIGJrMi5jbGlja2VkLmNvbm5lY3QobGFtYmRhOiBzZWxmLl9z"
    "dGFjay5zZXRDdXJyZW50SW5kZXgoMCkpCiAgICAgICAgbDIuYWRkV2lkZ2V0KGJrMikKICAgICAg"
    "ICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDIpCgogICAgICAgICMg4pSA4pSAIFBBR0UgMzogbW9k"
    "aWZ5IOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHAzID0gUVdpZGdldCgpCiAgICAgICAgbDMg"
    "PSBRVkJveExheW91dChwMykKICAgICAgICBsMy5zZXRDb250ZW50c01hcmdpbnMoNCwgNCwgNCwg"
    "NCkKICAgICAgICBsMy5zZXRTcGFjaW5nKDQpCiAgICAgICAgbDMuYWRkV2lkZ2V0KF9zZWN0aW9u"
    "X2xibCgi4p2nIE5BTUUiKSkKICAgICAgICBzZWxmLl9tb2RfbmFtZSA9IFFMaW5lRWRpdCgpCiAg"
    "ICAgICAgbDMuYWRkV2lkZ2V0KHNlbGYuX21vZF9uYW1lKQogICAgICAgIGwzLmFkZFdpZGdldChf"
    "c2VjdGlvbl9sYmwoIuKdpyBERVNDUklQVElPTiIpKQogICAgICAgIHNlbGYuX21vZF9kZXNjID0g"
    "UUxpbmVFZGl0KCkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fbW9kX2Rlc2MpCiAgICAgICAg"
    "bDMuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIElURU1TIChkb3VibGUtY2xpY2sgdG8gZWRp"
    "dCkiKSkKICAgICAgICBzZWxmLl9tb2RfdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgMikKICAgICAg"
    "ICBzZWxmLl9tb2RfdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIkl0ZW0iLCAiQ3Jl"
    "YXRvciJdKQogICAgICAgIHNlbGYuX21vZF90YWJsZS5ob3Jpem9udGFsSGVhZGVyKCkuc2V0U2Vj"
    "dGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3Ry"
    "ZXRjaCkKICAgICAgICBzZWxmLl9tb2RfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rp"
    "b25SZXNpemVNb2RlKAogICAgICAgICAgICAxLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0"
    "Y2gpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9z"
    "dHlsZSgpKQogICAgICAgIGwzLmFkZFdpZGdldChzZWxmLl9tb2RfdGFibGUsIDEpCgogICAgICAg"
    "IGJ0bnMzID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHMzID0gX2dvdGhpY19idG4oIuKcpiBTYXZl"
    "Iik7IGMzID0gX2dvdGhpY19idG4oIuKclyBDYW5jZWwiKQogICAgICAgIHMzLmNsaWNrZWQuY29u"
    "bmVjdChzZWxmLl9kb19tb2RpZnlfc2F2ZSkKICAgICAgICBjMy5jbGlja2VkLmNvbm5lY3QobGFt"
    "YmRhOiBzZWxmLl9zdGFjay5zZXRDdXJyZW50SW5kZXgoMCkpCiAgICAgICAgYnRuczMuYWRkV2lk"
    "Z2V0KHMzKTsgYnRuczMuYWRkV2lkZ2V0KGMzKTsgYnRuczMuYWRkU3RyZXRjaCgpCiAgICAgICAg"
    "bDMuYWRkTGF5b3V0KGJ0bnMzKQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMykKCiAg"
    "ICAjIOKUgOKUgCBQQVJTRVIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICBAc3RhdGljbWV0aG9kCiAgICBkZWYgcGFyc2Vfc2Nhbl90ZXh0"
    "KHJhdzogc3RyKSAtPiB0dXBsZVtzdHIsIGxpc3RbZGljdF1dOgogICAgICAgICIiIgogICAgICAg"
    "IFBhcnNlIHJhdyBTTCBzY2FuIG91dHB1dCBpbnRvIChhdmF0YXJfbmFtZSwgaXRlbXMpLgoKICAg"
    "ICAgICBLRVkgRklYOiBCZWZvcmUgc3BsaXR0aW5nLCBpbnNlcnQgbmV3bGluZXMgYmVmb3JlIGV2"
    "ZXJ5IFtISDpNTV0KICAgICAgICB0aW1lc3RhbXAgc28gc2luZ2xlLWxpbmUgcGFzdGVzIHdvcmsg"
    "Y29ycmVjdGx5LgoKICAgICAgICBFeHBlY3RlZCBmb3JtYXQ6CiAgICAgICAgICAgIFsxMTo0N10g"
    "QXZhdGFyTmFtZSdzIHB1YmxpYyBhdHRhY2htZW50czoKICAgICAgICAgICAgWzExOjQ3XSAuOiBJ"
    "dGVtIE5hbWUgW0F0dGFjaG1lbnRdIENSRUFUT1I6IENyZWF0b3JOYW1lIFsxMTo0N10gLi4uCiAg"
    "ICAgICAgIiIiCiAgICAgICAgaWYgbm90IHJhdy5zdHJpcCgpOgogICAgICAgICAgICByZXR1cm4g"
    "IlVOS05PV04iLCBbXQoKICAgICAgICAjIOKUgOKUgCBTdGVwIDE6IG5vcm1hbGl6ZSDigJQgaW5z"
    "ZXJ0IG5ld2xpbmVzIGJlZm9yZSB0aW1lc3RhbXBzIOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAg"
    "IG5vcm1hbGl6ZWQgPSBfcmUuc3ViKHInXHMqKFxbXGR7MSwyfTpcZHsyfVxdKScsIHInXG5cMScs"
    "IHJhdykKICAgICAgICBsaW5lcyA9IFtsLnN0cmlwKCkgZm9yIGwgaW4gbm9ybWFsaXplZC5zcGxp"
    "dGxpbmVzKCkgaWYgbC5zdHJpcCgpXQoKICAgICAgICAjIOKUgOKUgCBTdGVwIDI6IGV4dHJhY3Qg"
    "YXZhdGFyIG5hbWUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgYXZhdGFyX25hbWUgPSAiVU5LTk9XTiIKICAgICAgICBmb3IgbGluZSBpbiBsaW5lczoKICAg"
    "ICAgICAgICAgIyAiQXZhdGFyTmFtZSdzIHB1YmxpYyBhdHRhY2htZW50cyIgb3Igc2ltaWxhcgog"
    "ICAgICAgICAgICBtID0gX3JlLnNlYXJjaCgKICAgICAgICAgICAgICAgIHIiKFx3W1x3XHNdKz8p"
    "J3NccytwdWJsaWNccythdHRhY2htZW50cyIsCiAgICAgICAgICAgICAgICBsaW5lLCBfcmUuSQog"
    "ICAgICAgICAgICApCiAgICAgICAgICAgIGlmIG06CiAgICAgICAgICAgICAgICBhdmF0YXJfbmFt"
    "ZSA9IG0uZ3JvdXAoMSkuc3RyaXAoKQogICAgICAgICAgICAgICAgYnJlYWsKCiAgICAgICAgIyDi"
    "lIDilIAgU3RlcCAzOiBleHRyYWN0IGl0ZW1zIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIGl0ZW1zID0gW10KICAgICAgICBm"
    "b3IgbGluZSBpbiBsaW5lczoKICAgICAgICAgICAgIyBTdHJpcCBsZWFkaW5nIHRpbWVzdGFtcAog"
    "ICAgICAgICAgICBjb250ZW50ID0gX3JlLnN1YihyJ15cW1xkezEsMn06XGR7Mn1cXVxzKicsICcn"
    "LCBsaW5lKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIG5vdCBjb250ZW50OgogICAgICAgICAgICAg"
    "ICAgY29udGludWUKICAgICAgICAgICAgIyBTa2lwIGhlYWRlciBsaW5lcwogICAgICAgICAgICBp"
    "ZiAiJ3MgcHVibGljIGF0dGFjaG1lbnRzIiBpbiBjb250ZW50Lmxvd2VyKCk6CiAgICAgICAgICAg"
    "ICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBjb250ZW50Lmxvd2VyKCkuc3RhcnRzd2l0aCgi"
    "b2JqZWN0Iik6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAjIFNraXAgZGl2"
    "aWRlciBsaW5lcyDigJQgbGluZXMgdGhhdCBhcmUgbW9zdGx5IG9uZSByZXBlYXRlZCBjaGFyYWN0"
    "ZXIKICAgICAgICAgICAgIyBlLmcuIOKWguKWguKWguKWguKWguKWguKWguKWguKWguKWguKWguKW"
    "giBvciDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZDilZAgb3Ig4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgICAgIHN0cmlwcGVkID0gY29udGVudC5z"
    "dHJpcCgiLjogIikKICAgICAgICAgICAgaWYgc3RyaXBwZWQgYW5kIGxlbihzZXQoc3RyaXBwZWQp"
    "KSA8PSAyOgogICAgICAgICAgICAgICAgY29udGludWUgICMgb25lIG9yIHR3byB1bmlxdWUgY2hh"
    "cnMgPSBkaXZpZGVyIGxpbmUKCiAgICAgICAgICAgICMgVHJ5IHRvIGV4dHJhY3QgQ1JFQVRPUjog"
    "ZmllbGQKICAgICAgICAgICAgY3JlYXRvciA9ICJVTktOT1dOIgogICAgICAgICAgICBpdGVtX25h"
    "bWUgPSBjb250ZW50CgogICAgICAgICAgICBjcmVhdG9yX21hdGNoID0gX3JlLnNlYXJjaCgKICAg"
    "ICAgICAgICAgICAgIHInQ1JFQVRPUjpccyooW1x3XHNdKz8pKD86XHMqXFt8JCknLCBjb250ZW50"
    "LCBfcmUuSQogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIGNyZWF0b3JfbWF0Y2g6CiAgICAg"
    "ICAgICAgICAgICBjcmVhdG9yICAgPSBjcmVhdG9yX21hdGNoLmdyb3VwKDEpLnN0cmlwKCkKICAg"
    "ICAgICAgICAgICAgIGl0ZW1fbmFtZSA9IGNvbnRlbnRbOmNyZWF0b3JfbWF0Y2guc3RhcnQoKV0u"
    "c3RyaXAoKQoKICAgICAgICAgICAgIyBTdHJpcCBhdHRhY2htZW50IHBvaW50IHN1ZmZpeGVzIGxp"
    "a2UgW0xlZnRfRm9vdF0KICAgICAgICAgICAgaXRlbV9uYW1lID0gX3JlLnN1YihyJ1xzKlxbW1x3"
    "XHNfXStcXScsICcnLCBpdGVtX25hbWUpLnN0cmlwKCkKICAgICAgICAgICAgaXRlbV9uYW1lID0g"
    "aXRlbV9uYW1lLnN0cmlwKCIuOiAiKQoKICAgICAgICAgICAgaWYgaXRlbV9uYW1lIGFuZCBsZW4o"
    "aXRlbV9uYW1lKSA+IDE6CiAgICAgICAgICAgICAgICBpdGVtcy5hcHBlbmQoeyJpdGVtIjogaXRl"
    "bV9uYW1lLCAiY3JlYXRvciI6IGNyZWF0b3J9KQoKICAgICAgICByZXR1cm4gYXZhdGFyX25hbWUs"
    "IGl0ZW1zCgogICAgIyDilIDilIAgQ0FSRCBSRU5ERVJJTkcg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICBkZWYgX2J1aWxkX2NhcmRzKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIyBD"
    "bGVhciBleGlzdGluZyBjYXJkcyAoa2VlcCBzdHJldGNoKQogICAgICAgIHdoaWxlIHNlbGYuX2Nh"
    "cmRfbGF5b3V0LmNvdW50KCkgPiAxOgogICAgICAgICAgICBpdGVtID0gc2VsZi5fY2FyZF9sYXlv"
    "dXQudGFrZUF0KDApCiAgICAgICAgICAgIGlmIGl0ZW0ud2lkZ2V0KCk6CiAgICAgICAgICAgICAg"
    "ICBpdGVtLndpZGdldCgpLmRlbGV0ZUxhdGVyKCkKCiAgICAgICAgZm9yIHJlYyBpbiBzZWxmLl9y"
    "ZWNvcmRzOgogICAgICAgICAgICBjYXJkID0gc2VsZi5fbWFrZV9jYXJkKHJlYykKICAgICAgICAg"
    "ICAgc2VsZi5fY2FyZF9sYXlvdXQuaW5zZXJ0V2lkZ2V0KAogICAgICAgICAgICAgICAgc2VsZi5f"
    "Y2FyZF9sYXlvdXQuY291bnQoKSAtIDEsIGNhcmQKICAgICAgICAgICAgKQoKICAgIGRlZiBfbWFr"
    "ZV9jYXJkKHNlbGYsIHJlYzogZGljdCkgLT4gUVdpZGdldDoKICAgICAgICBjYXJkID0gUUZyYW1l"
    "KCkKICAgICAgICBpc19zZWxlY3RlZCA9IHJlYy5nZXQoInJlY29yZF9pZCIpID09IHNlbGYuX3Nl"
    "bGVjdGVkX2lkCiAgICAgICAgY2FyZC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tn"
    "cm91bmQ6IHsnIzFhMGExMCcgaWYgaXNfc2VsZWN0ZWQgZWxzZSBDX0JHM307ICIKICAgICAgICAg"
    "ICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OIGlmIGlzX3NlbGVjdGVkIGVsc2UgQ19C"
    "T1JERVJ9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyLXJhZGl1czogMnB4OyBwYWRkaW5nOiAycHg7"
    "IgogICAgICAgICkKICAgICAgICBsYXlvdXQgPSBRSEJveExheW91dChjYXJkKQogICAgICAgIGxh"
    "eW91dC5zZXRDb250ZW50c01hcmdpbnMoOCwgNiwgOCwgNikKCiAgICAgICAgbmFtZV9sYmwgPSBR"
    "TGFiZWwocmVjLmdldCgibmFtZSIsICJVTktOT1dOIikpCiAgICAgICAgbmFtZV9sYmwuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfR09MRF9CUklHSFQgaWYgaXNfc2VsZWN0"
    "ZWQgZWxzZSBDX0dPTER9OyAiCiAgICAgICAgICAgIGYiZm9udC1zaXplOiAxMXB4OyBmb250LXdl"
    "aWdodDogYm9sZDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQoK"
    "ICAgICAgICBjb3VudCA9IGxlbihyZWMuZ2V0KCJpdGVtcyIsIFtdKSkKICAgICAgICBjb3VudF9s"
    "YmwgPSBRTGFiZWwoZiJ7Y291bnR9IGl0ZW1zIikKICAgICAgICBjb3VudF9sYmwuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6ZTogMTBweDsg"
    "Zm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQoKICAgICAgICBkYXRl"
    "X2xibCA9IFFMYWJlbChyZWMuZ2V0KCJjcmVhdGVkX2F0IiwgIiIpWzoxMF0pCiAgICAgICAgZGF0"
    "ZV9sYmwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBm"
    "b250LXNpemU6IDlweDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAg"
    "KQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KG5hbWVfbGJsKQogICAgICAgIGxheW91dC5hZGRT"
    "dHJldGNoKCkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGNvdW50X2xibCkKICAgICAgICBsYXlv"
    "dXQuYWRkU3BhY2luZygxMikKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KGRhdGVfbGJsKQoKICAg"
    "ICAgICAjIENsaWNrIHRvIHNlbGVjdAogICAgICAgIHJlY19pZCA9IHJlYy5nZXQoInJlY29yZF9p"
    "ZCIsICIiKQogICAgICAgIGNhcmQubW91c2VQcmVzc0V2ZW50ID0gbGFtYmRhIGUsIHJpZD1yZWNf"
    "aWQ6IHNlbGYuX3NlbGVjdF9jYXJkKHJpZCkKICAgICAgICByZXR1cm4gY2FyZAoKICAgIGRlZiBf"
    "c2VsZWN0X2NhcmQoc2VsZiwgcmVjb3JkX2lkOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "c2VsZWN0ZWRfaWQgPSByZWNvcmRfaWQKICAgICAgICBzZWxmLl9idWlsZF9jYXJkcygpICAjIFJl"
    "YnVpbGQgdG8gc2hvdyBzZWxlY3Rpb24gaGlnaGxpZ2h0CgogICAgZGVmIF9zZWxlY3RlZF9yZWNv"
    "cmQoc2VsZikgLT4gT3B0aW9uYWxbZGljdF06CiAgICAgICAgcmV0dXJuIG5leHQoCiAgICAgICAg"
    "ICAgIChyIGZvciByIGluIHNlbGYuX3JlY29yZHMKICAgICAgICAgICAgIGlmIHIuZ2V0KCJyZWNv"
    "cmRfaWQiKSA9PSBzZWxmLl9zZWxlY3RlZF9pZCksCiAgICAgICAgICAgIE5vbmUKICAgICAgICAp"
    "CgogICAgIyDilIDilIAgQUNUSU9OUyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "c2VsZi5fcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICAjIEVuc3VyZSBy"
    "ZWNvcmRfaWQgZmllbGQgZXhpc3RzCiAgICAgICAgY2hhbmdlZCA9IEZhbHNlCiAgICAgICAgZm9y"
    "IHIgaW4gc2VsZi5fcmVjb3JkczoKICAgICAgICAgICAgaWYgbm90IHIuZ2V0KCJyZWNvcmRfaWQi"
    "KToKICAgICAgICAgICAgICAgIHJbInJlY29yZF9pZCJdID0gci5nZXQoImlkIikgb3Igc3RyKHV1"
    "aWQudXVpZDQoKSkKICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAgICAgICAgaWYgY2hh"
    "bmdlZDoKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykK"
    "ICAgICAgICBzZWxmLl9idWlsZF9jYXJkcygpCiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVu"
    "dEluZGV4KDApCgogICAgZGVmIF9wcmV2aWV3X3BhcnNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAg"
    "cmF3ID0gc2VsZi5fYWRkX3Jhdy50b1BsYWluVGV4dCgpCiAgICAgICAgbmFtZSwgaXRlbXMgPSBz"
    "ZWxmLnBhcnNlX3NjYW5fdGV4dChyYXcpCiAgICAgICAgc2VsZi5fYWRkX25hbWUuc2V0UGxhY2Vo"
    "b2xkZXJUZXh0KG5hbWUpCiAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0Um93Q291bnQoMCkK"
    "ICAgICAgICBmb3IgaXQgaW4gaXRlbXNbOjIwXTogICMgcHJldmlldyBmaXJzdCAyMAogICAgICAg"
    "ICAgICByID0gc2VsZi5fYWRkX3ByZXZpZXcucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl9h"
    "ZGRfcHJldmlldy5pbnNlcnRSb3cocikKICAgICAgICAgICAgc2VsZi5fYWRkX3ByZXZpZXcuc2V0"
    "SXRlbShyLCAwLCBRVGFibGVXaWRnZXRJdGVtKGl0WyJpdGVtIl0pKQogICAgICAgICAgICBzZWxm"
    "Ll9hZGRfcHJldmlldy5zZXRJdGVtKHIsIDEsIFFUYWJsZVdpZGdldEl0ZW0oaXRbImNyZWF0b3Ii"
    "XSkpCgogICAgZGVmIF9zaG93X2FkZChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2FkZF9u"
    "YW1lLmNsZWFyKCkKICAgICAgICBzZWxmLl9hZGRfbmFtZS5zZXRQbGFjZWhvbGRlclRleHQoIkF1"
    "dG8tZGV0ZWN0ZWQgZnJvbSBzY2FuIHRleHQiKQogICAgICAgIHNlbGYuX2FkZF9kZXNjLmNsZWFy"
    "KCkKICAgICAgICBzZWxmLl9hZGRfcmF3LmNsZWFyKCkKICAgICAgICBzZWxmLl9hZGRfcHJldmll"
    "dy5zZXRSb3dDb3VudCgwKQogICAgICAgIHNlbGYuX3N0YWNrLnNldEN1cnJlbnRJbmRleCgxKQoK"
    "ICAgIGRlZiBfZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmF3ICA9IHNlbGYuX2FkZF9y"
    "YXcudG9QbGFpblRleHQoKQogICAgICAgIG5hbWUsIGl0ZW1zID0gc2VsZi5wYXJzZV9zY2FuX3Rl"
    "eHQocmF3KQogICAgICAgIG92ZXJyaWRlX25hbWUgPSBzZWxmLl9hZGRfbmFtZS50ZXh0KCkuc3Ry"
    "aXAoKQogICAgICAgIG5vdyAgPSBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQo"
    "KQogICAgICAgIHJlY29yZCA9IHsKICAgICAgICAgICAgImlkIjogICAgICAgICAgc3RyKHV1aWQu"
    "dXVpZDQoKSksCiAgICAgICAgICAgICJyZWNvcmRfaWQiOiAgIHN0cih1dWlkLnV1aWQ0KCkpLAog"
    "ICAgICAgICAgICAibmFtZSI6ICAgICAgICBvdmVycmlkZV9uYW1lIG9yIG5hbWUsCiAgICAgICAg"
    "ICAgICJkZXNjcmlwdGlvbiI6IHNlbGYuX2FkZF9kZXNjLnRvUGxhaW5UZXh0KClbOjI0NF0sCiAg"
    "ICAgICAgICAgICJpdGVtcyI6ICAgICAgIGl0ZW1zLAogICAgICAgICAgICAicmF3X3RleHQiOiAg"
    "ICByYXcsCiAgICAgICAgICAgICJjcmVhdGVkX2F0IjogIG5vdywKICAgICAgICAgICAgInVwZGF0"
    "ZWRfYXQiOiAgbm93LAogICAgICAgIH0KICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChyZWNv"
    "cmQpCiAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAg"
    "ICBzZWxmLl9zZWxlY3RlZF9pZCA9IHJlY29yZFsicmVjb3JkX2lkIl0KICAgICAgICBzZWxmLnJl"
    "ZnJlc2goKQoKICAgIGRlZiBfc2hvd19kaXNwbGF5KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVj"
    "ID0gc2VsZi5fc2VsZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAg"
    "ICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiU0wgU2NhbnMiLAogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAiU2VsZWN0IGEgc2NhbiB0byBkaXNwbGF5LiIpCiAgICAg"
    "ICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX2Rpc3BfbmFtZS5zZXRUZXh0KGYi4p2nIHtyZWMu"
    "Z2V0KCduYW1lJywnJyl9IikKICAgICAgICBzZWxmLl9kaXNwX2Rlc2Muc2V0VGV4dChyZWMuZ2V0"
    "KCJkZXNjcmlwdGlvbiIsIiIpKQogICAgICAgIHNlbGYuX2Rpc3BfdGFibGUuc2V0Um93Q291bnQo"
    "MCkKICAgICAgICBmb3IgaXQgaW4gcmVjLmdldCgiaXRlbXMiLFtdKToKICAgICAgICAgICAgciA9"
    "IHNlbGYuX2Rpc3BfdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl9kaXNwX3RhYmxl"
    "Lmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldEl0ZW0ociwgMCwK"
    "ICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0oaXQuZ2V0KCJpdGVtIiwiIikpKQogICAg"
    "ICAgICAgICBzZWxmLl9kaXNwX3RhYmxlLnNldEl0ZW0ociwgMSwKICAgICAgICAgICAgICAgIFFU"
    "YWJsZVdpZGdldEl0ZW0oaXQuZ2V0KCJjcmVhdG9yIiwiVU5LTk9XTiIpKSkKICAgICAgICBzZWxm"
    "Ll9zdGFjay5zZXRDdXJyZW50SW5kZXgoMikKCiAgICBkZWYgX2l0ZW1fY29udGV4dF9tZW51KHNl"
    "bGYsIHBvcykgLT4gTm9uZToKICAgICAgICBpZHggPSBzZWxmLl9kaXNwX3RhYmxlLmluZGV4QXQo"
    "cG9zKQogICAgICAgIGlmIG5vdCBpZHguaXNWYWxpZCgpOgogICAgICAgICAgICByZXR1cm4KICAg"
    "ICAgICBpdGVtX3RleHQgID0gKHNlbGYuX2Rpc3BfdGFibGUuaXRlbShpZHgucm93KCksIDApIG9y"
    "CiAgICAgICAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKCIiKSkudGV4dCgpCiAgICAg"
    "ICAgY3JlYXRvciAgICA9IChzZWxmLl9kaXNwX3RhYmxlLml0ZW0oaWR4LnJvdygpLCAxKSBvcgog"
    "ICAgICAgICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRlbSgiIikpLnRleHQoKQogICAgICAg"
    "IGZyb20gUHlTaWRlNi5RdFdpZGdldHMgaW1wb3J0IFFNZW51CiAgICAgICAgbWVudSA9IFFNZW51"
    "KHNlbGYpCiAgICAgICAgbWVudS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91"
    "bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4"
    "IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAgKQogICAgICAgIGFfaXRlbSAgICA9IG1l"
    "bnUuYWRkQWN0aW9uKCJDb3B5IEl0ZW0gTmFtZSIpCiAgICAgICAgYV9jcmVhdG9yID0gbWVudS5h"
    "ZGRBY3Rpb24oIkNvcHkgQ3JlYXRvciIpCiAgICAgICAgYV9ib3RoICAgID0gbWVudS5hZGRBY3Rp"
    "b24oIkNvcHkgQm90aCIpCiAgICAgICAgYWN0aW9uID0gbWVudS5leGVjKHNlbGYuX2Rpc3BfdGFi"
    "bGUudmlld3BvcnQoKS5tYXBUb0dsb2JhbChwb3MpKQogICAgICAgIGNiID0gUUFwcGxpY2F0aW9u"
    "LmNsaXBib2FyZCgpCiAgICAgICAgaWYgYWN0aW9uID09IGFfaXRlbTogICAgY2Iuc2V0VGV4dChp"
    "dGVtX3RleHQpCiAgICAgICAgZWxpZiBhY3Rpb24gPT0gYV9jcmVhdG9yOiBjYi5zZXRUZXh0KGNy"
    "ZWF0b3IpCiAgICAgICAgZWxpZiBhY3Rpb24gPT0gYV9ib3RoOiAgY2Iuc2V0VGV4dChmIntpdGVt"
    "X3RleHR9IOKAlCB7Y3JlYXRvcn0iKQoKICAgIGRlZiBfc2hvd19tb2RpZnkoc2VsZikgLT4gTm9u"
    "ZToKICAgICAgICByZWMgPSBzZWxmLl9zZWxlY3RlZF9yZWNvcmQoKQogICAgICAgIGlmIG5vdCBy"
    "ZWM6CiAgICAgICAgICAgIFFNZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJTTCBTY2FucyIs"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxlY3QgYSBzY2FuIHRvIG1v"
    "ZGlmeS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9tb2RfbmFtZS5zZXRUZXh0"
    "KHJlYy5nZXQoIm5hbWUiLCIiKSkKICAgICAgICBzZWxmLl9tb2RfZGVzYy5zZXRUZXh0KHJlYy5n"
    "ZXQoImRlc2NyaXB0aW9uIiwiIikpCiAgICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldFJvd0NvdW50"
    "KDApCiAgICAgICAgZm9yIGl0IGluIHJlYy5nZXQoIml0ZW1zIixbXSk6CiAgICAgICAgICAgIHIg"
    "PSBzZWxmLl9tb2RfdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLl9tb2RfdGFibGUu"
    "aW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX21vZF90YWJsZS5zZXRJdGVtKHIsIDAsCiAg"
    "ICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKGl0LmdldCgiaXRlbSIsIiIpKSkKICAgICAg"
    "ICAgICAgc2VsZi5fbW9kX3RhYmxlLnNldEl0ZW0ociwgMSwKICAgICAgICAgICAgICAgIFFUYWJs"
    "ZVdpZGdldEl0ZW0oaXQuZ2V0KCJjcmVhdG9yIiwiVU5LTk9XTiIpKSkKICAgICAgICBzZWxmLl9z"
    "dGFjay5zZXRDdXJyZW50SW5kZXgoMykKCiAgICBkZWYgX2RvX21vZGlmeV9zYXZlKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBu"
    "b3QgcmVjOgogICAgICAgICAgICByZXR1cm4KICAgICAgICByZWNbIm5hbWUiXSAgICAgICAgPSBz"
    "ZWxmLl9tb2RfbmFtZS50ZXh0KCkuc3RyaXAoKSBvciAiVU5LTk9XTiIKICAgICAgICByZWNbImRl"
    "c2NyaXB0aW9uIl0gPSBzZWxmLl9tb2RfZGVzYy50ZXh0KClbOjI0NF0KICAgICAgICBpdGVtcyA9"
    "IFtdCiAgICAgICAgZm9yIGkgaW4gcmFuZ2Uoc2VsZi5fbW9kX3RhYmxlLnJvd0NvdW50KCkpOgog"
    "ICAgICAgICAgICBpdCAgPSAoc2VsZi5fbW9kX3RhYmxlLml0ZW0oaSwwKSBvciBRVGFibGVXaWRn"
    "ZXRJdGVtKCIiKSkudGV4dCgpCiAgICAgICAgICAgIGNyICA9IChzZWxmLl9tb2RfdGFibGUuaXRl"
    "bShpLDEpIG9yIFFUYWJsZVdpZGdldEl0ZW0oIiIpKS50ZXh0KCkKICAgICAgICAgICAgaXRlbXMu"
    "YXBwZW5kKHsiaXRlbSI6IGl0LnN0cmlwKCkgb3IgIlVOS05PV04iLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICJjcmVhdG9yIjogY3Iuc3RyaXAoKSBvciAiVU5LTk9XTiJ9KQogICAgICAgIHJl"
    "Y1siaXRlbXMiXSAgICAgID0gaXRlbXMKICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSA9IGRhdGV0"
    "aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgd3JpdGVfanNvbmwoc2Vs"
    "Zi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBf"
    "ZG9fZGVsZXRlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVj"
    "b3JkKCkKICAgICAgICBpZiBub3QgcmVjOgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1h"
    "dGlvbihzZWxmLCAiU0wgU2NhbnMiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAiU2VsZWN0IGEgc2NhbiB0byBkZWxldGUuIikKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAg"
    "bmFtZSA9IHJlYy5nZXQoIm5hbWUiLCJ0aGlzIHNjYW4iKQogICAgICAgIHJlcGx5ID0gUU1lc3Nh"
    "Z2VCb3gucXVlc3Rpb24oCiAgICAgICAgICAgIHNlbGYsICJEZWxldGUgU2NhbiIsCiAgICAgICAg"
    "ICAgIGYiRGVsZXRlICd7bmFtZX0nPyBUaGlzIGNhbm5vdCBiZSB1bmRvbmUuIiwKICAgICAgICAg"
    "ICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRC"
    "dXR0b24uTm8KICAgICAgICApCiAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRh"
    "cmRCdXR0b24uWWVzOgogICAgICAgICAgICBzZWxmLl9yZWNvcmRzID0gW3IgZm9yIHIgaW4gc2Vs"
    "Zi5fcmVjb3JkcwogICAgICAgICAgICAgICAgICAgICAgICAgICAgIGlmIHIuZ2V0KCJyZWNvcmRf"
    "aWQiKSAhPSBzZWxmLl9zZWxlY3RlZF9pZF0KICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5f"
    "cGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5fc2VsZWN0ZWRfaWQgPSBOb25l"
    "CiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19yZXBhcnNlKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgcmVjID0gc2VsZi5fc2VsZWN0ZWRfcmVjb3JkKCkKICAgICAgICBpZiBu"
    "b3QgcmVjOgogICAgICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlvbihzZWxmLCAiU0wgU2Nh"
    "bnMiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAiU2VsZWN0IGEgc2NhbiB0"
    "byByZS1wYXJzZS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAgICByYXcgPSByZWMuZ2V0KCJy"
    "YXdfdGV4dCIsIiIpCiAgICAgICAgaWYgbm90IHJhdzoKICAgICAgICAgICAgUU1lc3NhZ2VCb3gu"
    "aW5mb3JtYXRpb24oc2VsZiwgIlJlLXBhcnNlIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgIk5vIHJhdyB0ZXh0IHN0b3JlZCBmb3IgdGhpcyBzY2FuLiIpCiAgICAgICAgICAg"
    "IHJldHVybgogICAgICAgIG5hbWUsIGl0ZW1zID0gc2VsZi5wYXJzZV9zY2FuX3RleHQocmF3KQog"
    "ICAgICAgIHJlY1siaXRlbXMiXSAgICAgID0gaXRlbXMKICAgICAgICByZWNbIm5hbWUiXSAgICAg"
    "ICA9IHJlY1sibmFtZSJdIG9yIG5hbWUKICAgICAgICByZWNbInVwZGF0ZWRfYXQiXSA9IGRhdGV0"
    "aW1lLm5vdyh0aW1lem9uZS51dGMpLmlzb2Zvcm1hdCgpCiAgICAgICAgd3JpdGVfanNvbmwoc2Vs"
    "Zi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICBzZWxmLnJlZnJlc2goKQogICAgICAgIFFN"
    "ZXNzYWdlQm94LmluZm9ybWF0aW9uKHNlbGYsICJSZS1wYXJzZWQiLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgIGYiRm91bmQge2xlbihpdGVtcyl9IGl0ZW1zLiIpCgoKIyDilIDilIAg"
    "U0wgQ09NTUFORFMgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBTTENvbW1hbmRzVGFiKFFXaWRnZXQpOgogICAg"
    "IiIiCiAgICBTZWNvbmQgTGlmZSBjb21tYW5kIHJlZmVyZW5jZSB0YWJsZS4KICAgIEdvdGhpYyB0"
    "YWJsZSBzdHlsaW5nLiBDb3B5IGNvbW1hbmQgdG8gY2xpcGJvYXJkIGJ1dHRvbiBwZXIgcm93Lgog"
    "ICAgIiIiCgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBl"
    "cigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9wYXRoICAgID0gY2ZnX3BhdGgoInNs"
    "IikgLyAic2xfY29tbWFuZHMuanNvbmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0"
    "XSA9IFtdCiAgICAgICAgc2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgog"
    "ICAgZGVmIF9zZXR1cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91"
    "dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAg"
    "ICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGJhciA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBzZWxmLl9idG5fYWRkICAgID0gX2dvdGhpY19idG4oIuKcpiBBZGQiKQogICAgICAgIHNlbGYu"
    "X2J0bl9tb2RpZnkgPSBfZ290aGljX2J0bigi4pynIE1vZGlmeSIpCiAgICAgICAgc2VsZi5fYnRu"
    "X2RlbGV0ZSA9IF9nb3RoaWNfYnRuKCLinJcgRGVsZXRlIikKICAgICAgICBzZWxmLl9idG5fY29w"
    "eSAgID0gX2dvdGhpY19idG4oIuKniSBDb3B5IENvbW1hbmQiLAogICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgIkNvcHkgc2VsZWN0ZWQgY29tbWFuZCB0byBjbGlwYm9hcmQi"
    "KQogICAgICAgIHNlbGYuX2J0bl9yZWZyZXNoPSBfZ290aGljX2J0bigi4oa7IFJlZnJlc2giKQog"
    "ICAgICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAg"
    "ICBzZWxmLl9idG5fbW9kaWZ5LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19tb2RpZnkpCiAgICAg"
    "ICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAg"
    "ICAgIHNlbGYuX2J0bl9jb3B5LmNsaWNrZWQuY29ubmVjdChzZWxmLl9jb3B5X2NvbW1hbmQpCiAg"
    "ICAgICAgc2VsZi5fYnRuX3JlZnJlc2guY2xpY2tlZC5jb25uZWN0KHNlbGYucmVmcmVzaCkKICAg"
    "ICAgICBmb3IgYiBpbiAoc2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRuX21vZGlmeSwgc2VsZi5fYnRu"
    "X2RlbGV0ZSwKICAgICAgICAgICAgICAgICAgc2VsZi5fYnRuX2NvcHksIHNlbGYuX2J0bl9yZWZy"
    "ZXNoKToKICAgICAgICAgICAgYmFyLmFkZFdpZGdldChiKQogICAgICAgIGJhci5hZGRTdHJldGNo"
    "KCkKICAgICAgICByb290LmFkZExheW91dChiYXIpCgogICAgICAgIHNlbGYuX3RhYmxlID0gUVRh"
    "YmxlV2lkZ2V0KDAsIDIpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxh"
    "YmVscyhbIkNvbW1hbmQiLCAiRGVzY3JpcHRpb24iXSkKICAgICAgICBzZWxmLl90YWJsZS5ob3Jp"
    "em9udGFsSGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDAsIFFIZWFk"
    "ZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90YWJsZS5ob3Jpem9udGFs"
    "SGVhZGVyKCkuc2V0U2VjdGlvblJlc2l6ZU1vZGUoCiAgICAgICAgICAgIDEsIFFIZWFkZXJWaWV3"
    "LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTZWxlY3Rpb25CZWhh"
    "dmlvcigKICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2Vs"
    "ZWN0Um93cykKICAgICAgICBzZWxmLl90YWJsZS5zZXRBbHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVl"
    "KQogICAgICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgp"
    "KQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlLCAxKQoKICAgICAgICBoaW50ID0g"
    "UUxhYmVsKAogICAgICAgICAgICAiU2VsZWN0IGEgcm93IGFuZCBjbGljayDip4kgQ29weSBDb21t"
    "YW5kIHRvIGNvcHkganVzdCB0aGUgY29tbWFuZCB0ZXh0LiIKICAgICAgICApCiAgICAgICAgaGlu"
    "dC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQt"
    "c2l6ZTogOXB4OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAg"
    "ICAgICAgcm9vdC5hZGRXaWRnZXQoaGludCkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAgICAg"
    "c2VsZi5fdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3JlY29y"
    "ZHM6CiAgICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAgIHNl"
    "bGYuX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVtKHIs"
    "IDAsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoImNvbW1hbmQiLCIi"
    "KSkpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMSwKICAgICAgICAgICAgICAg"
    "IFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgiZGVzY3JpcHRpb24iLCIiKSkpCgogICAgZGVmIF9j"
    "b3B5X2NvbW1hbmQoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5jdXJy"
    "ZW50Um93KCkKICAgICAgICBpZiByb3cgPCAwOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBp"
    "dGVtID0gc2VsZi5fdGFibGUuaXRlbShyb3csIDApCiAgICAgICAgaWYgaXRlbToKICAgICAgICAg"
    "ICAgUUFwcGxpY2F0aW9uLmNsaXBib2FyZCgpLnNldFRleHQoaXRlbS50ZXh0KCkpCgogICAgZGVm"
    "IF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAg"
    "ICAgZGxnLnNldFdpbmRvd1RpdGxlKCJBZGQgQ29tbWFuZCIpCiAgICAgICAgZGxnLnNldFN0eWxl"
    "U2hlZXQoZiJiYWNrZ3JvdW5kOiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBm"
    "b3JtID0gUUZvcm1MYXlvdXQoZGxnKQogICAgICAgIGNtZCAgPSBRTGluZUVkaXQoKTsgZGVzYyA9"
    "IFFMaW5lRWRpdCgpCiAgICAgICAgZm9ybS5hZGRSb3coIkNvbW1hbmQ6IiwgY21kKQogICAgICAg"
    "IGZvcm0uYWRkUm93KCJEZXNjcmlwdGlvbjoiLCBkZXNjKQogICAgICAgIGJ0bnMgPSBRSEJveExh"
    "eW91dCgpCiAgICAgICAgb2sgPSBfZ290aGljX2J0bigiU2F2ZSIpOyBjeCA9IF9nb3RoaWNfYnRu"
    "KCJDYW5jZWwiKQogICAgICAgIG9rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KTsgY3guY2xp"
    "Y2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5z"
    "LmFkZFdpZGdldChjeCkKICAgICAgICBmb3JtLmFkZFJvdyhidG5zKQogICAgICAgIGlmIGRsZy5l"
    "eGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICBub3cgPSBk"
    "YXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgICAgICByZWMgPSB7"
    "CiAgICAgICAgICAgICAgICAiaWQiOiAgICAgICAgICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAg"
    "ICAgICAgICAgICJjb21tYW5kIjogICAgIGNtZC50ZXh0KCkuc3RyaXAoKVs6MjQ0XSwKICAgICAg"
    "ICAgICAgICAgICJkZXNjcmlwdGlvbiI6IGRlc2MudGV4dCgpLnN0cmlwKClbOjI0NF0sCiAgICAg"
    "ICAgICAgICAgICAiY3JlYXRlZF9hdCI6ICBub3csICJ1cGRhdGVkX2F0Ijogbm93LAogICAgICAg"
    "ICAgICB9CiAgICAgICAgICAgIGlmIHJlY1siY29tbWFuZCJdOgogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fcmVjb3Jkcy5hcHBlbmQocmVjKQogICAgICAgICAgICAgICAgd3JpdGVfanNvbmwoc2VsZi5f"
    "cGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAg"
    "ZGVmIF9kb19tb2RpZnkoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJsZS5j"
    "dXJyZW50Um93KCkKICAgICAgICBpZiByb3cgPCAwIG9yIHJvdyA+PSBsZW4oc2VsZi5fcmVjb3Jk"
    "cyk6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHJlYyA9IHNlbGYuX3JlY29yZHNbcm93XQog"
    "ICAgICAgIGRsZyA9IFFEaWFsb2coc2VsZikKICAgICAgICBkbGcuc2V0V2luZG93VGl0bGUoIk1v"
    "ZGlmeSBDb21tYW5kIikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChmImJhY2tncm91bmQ6IHtD"
    "X0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGZvcm0gPSBRRm9ybUxheW91dChkbGcp"
    "CiAgICAgICAgY21kICA9IFFMaW5lRWRpdChyZWMuZ2V0KCJjb21tYW5kIiwiIikpCiAgICAgICAg"
    "ZGVzYyA9IFFMaW5lRWRpdChyZWMuZ2V0KCJkZXNjcmlwdGlvbiIsIiIpKQogICAgICAgIGZvcm0u"
    "YWRkUm93KCJDb21tYW5kOiIsIGNtZCkKICAgICAgICBmb3JtLmFkZFJvdygiRGVzY3JpcHRpb246"
    "IiwgZGVzYykKICAgICAgICBidG5zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIG9rID0gX2dvdGhp"
    "Y19idG4oIlNhdmUiKTsgY3ggPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAgICBvay5jbGlj"
    "a2VkLmNvbm5lY3QoZGxnLmFjY2VwdCk7IGN4LmNsaWNrZWQuY29ubmVjdChkbGcucmVqZWN0KQog"
    "ICAgICAgIGJ0bnMuYWRkV2lkZ2V0KG9rKTsgYnRucy5hZGRXaWRnZXQoY3gpCiAgICAgICAgZm9y"
    "bS5hZGRSb3coYnRucykKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29k"
    "ZS5BY2NlcHRlZDoKICAgICAgICAgICAgcmVjWyJjb21tYW5kIl0gICAgID0gY21kLnRleHQoKS5z"
    "dHJpcCgpWzoyNDRdCiAgICAgICAgICAgIHJlY1siZGVzY3JpcHRpb24iXSA9IGRlc2MudGV4dCgp"
    "LnN0cmlwKClbOjI0NF0KICAgICAgICAgICAgcmVjWyJ1cGRhdGVkX2F0Il0gID0gZGF0ZXRpbWUu"
    "bm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAgICAgICAgd3JpdGVfanNvbmwoc2Vs"
    "Zi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBk"
    "ZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNlbGYuX3RhYmxlLmN1"
    "cnJlbnRSb3coKQogICAgICAgIGlmIHJvdyA8IDAgb3Igcm93ID49IGxlbihzZWxmLl9yZWNvcmRz"
    "KToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgY21kID0gc2VsZi5fcmVjb3Jkc1tyb3ddLmdl"
    "dCgiY29tbWFuZCIsInRoaXMgY29tbWFuZCIpCiAgICAgICAgcmVwbHkgPSBRTWVzc2FnZUJveC5x"
    "dWVzdGlvbigKICAgICAgICAgICAgc2VsZiwgIkRlbGV0ZSIsIGYiRGVsZXRlICd7Y21kfSc/IiwK"
    "ICAgICAgICAgICAgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3gu"
    "U3RhbmRhcmRCdXR0b24uTm8KICAgICAgICApCiAgICAgICAgaWYgcmVwbHkgPT0gUU1lc3NhZ2VC"
    "b3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICBzZWxmLl9yZWNvcmRzLnBvcChyb3cp"
    "CiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAg"
    "ICAgICAgIHNlbGYucmVmcmVzaCgpCgoKIyDilIDilIAgSk9CIFRSQUNLRVIgVEFCIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApj"
    "bGFzcyBKb2JUcmFja2VyVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBKb2IgYXBwbGljYXRpb24g"
    "dHJhY2tpbmcuIEZ1bGwgcmVidWlsZCBmcm9tIHNwZWMuCiAgICBGaWVsZHM6IENvbXBhbnksIEpv"
    "YiBUaXRsZSwgRGF0ZSBBcHBsaWVkLCBMaW5rLCBTdGF0dXMsIE5vdGVzLgogICAgTXVsdGktc2Vs"
    "ZWN0IGhpZGUvdW5oaWRlL2RlbGV0ZS4gQ1NWIGFuZCBUU1YgZXhwb3J0LgogICAgSGlkZGVuIHJv"
    "d3MgPSBjb21wbGV0ZWQvcmVqZWN0ZWQg4oCUIHN0aWxsIHN0b3JlZCwganVzdCBub3Qgc2hvd24u"
    "CiAgICAiIiIKCiAgICBDT0xVTU5TID0gWyJDb21wYW55IiwgIkpvYiBUaXRsZSIsICJEYXRlIEFw"
    "cGxpZWQiLAogICAgICAgICAgICAgICAiTGluayIsICJTdGF0dXMiLCAiTm90ZXMiXQoKICAgIGRl"
    "ZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhw"
    "YXJlbnQpCiAgICAgICAgc2VsZi5fcGF0aCAgICA9IGNmZ19wYXRoKCJtZW1vcmllcyIpIC8gImpv"
    "Yl90cmFja2VyLmpzb25sIgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxpc3RbZGljdF0gPSBbXQog"
    "ICAgICAgIHNlbGYuX3Nob3dfaGlkZGVuID0gRmFsc2UKICAgICAgICBzZWxmLl9zZXR1cF91aSgp"
    "CiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50"
    "c01hcmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAg"
    "YmFyID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9hZGQgICAgPSBfZ290aGljX2J0"
    "bigiQWRkIikKICAgICAgICBzZWxmLl9idG5fbW9kaWZ5ID0gX2dvdGhpY19idG4oIk1vZGlmeSIp"
    "CiAgICAgICAgc2VsZi5fYnRuX2hpZGUgICA9IF9nb3RoaWNfYnRuKCJBcmNoaXZlIiwKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJNYXJrIHNlbGVjdGVkIGFzIGNvbXBs"
    "ZXRlZC9yZWplY3RlZCIpCiAgICAgICAgc2VsZi5fYnRuX3VuaGlkZSA9IF9nb3RoaWNfYnRuKCJS"
    "ZXN0b3JlIiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJSZXN0b3Jl"
    "IGFyY2hpdmVkIGFwcGxpY2F0aW9ucyIpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZSA9IF9nb3Ro"
    "aWNfYnRuKCJEZWxldGUiKQogICAgICAgIHNlbGYuX2J0bl90b2dnbGUgPSBfZ290aGljX2J0bigi"
    "U2hvdyBBcmNoaXZlZCIpCiAgICAgICAgc2VsZi5fYnRuX2V4cG9ydCA9IF9nb3RoaWNfYnRuKCJF"
    "eHBvcnQiKQoKICAgICAgICBmb3IgYiBpbiAoc2VsZi5fYnRuX2FkZCwgc2VsZi5fYnRuX21vZGlm"
    "eSwgc2VsZi5fYnRuX2hpZGUsCiAgICAgICAgICAgICAgICAgIHNlbGYuX2J0bl91bmhpZGUsIHNl"
    "bGYuX2J0bl9kZWxldGUsCiAgICAgICAgICAgICAgICAgIHNlbGYuX2J0bl90b2dnbGUsIHNlbGYu"
    "X2J0bl9leHBvcnQpOgogICAgICAgICAgICBiLnNldE1pbmltdW1XaWR0aCg3MCkKICAgICAgICAg"
    "ICAgYi5zZXRNaW5pbXVtSGVpZ2h0KDI2KQogICAgICAgICAgICBiYXIuYWRkV2lkZ2V0KGIpCgog"
    "ICAgICAgIHNlbGYuX2J0bl9hZGQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2FkZCkKICAgICAg"
    "ICBzZWxmLl9idG5fbW9kaWZ5LmNsaWNrZWQuY29ubmVjdChzZWxmLl9kb19tb2RpZnkpCiAgICAg"
    "ICAgc2VsZi5fYnRuX2hpZGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2hpZGUpCiAgICAgICAg"
    "c2VsZi5fYnRuX3VuaGlkZS5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fZG9fdW5oaWRlKQogICAgICAg"
    "IHNlbGYuX2J0bl9kZWxldGUuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAg"
    "ICBzZWxmLl9idG5fdG9nZ2xlLmNsaWNrZWQuY29ubmVjdChzZWxmLl90b2dnbGVfaGlkZGVuKQog"
    "ICAgICAgIHNlbGYuX2J0bl9leHBvcnQuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX2V4cG9ydCkK"
    "ICAgICAgICBiYXIuYWRkU3RyZXRjaCgpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoYmFyKQoKICAg"
    "ICAgICBzZWxmLl90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCBsZW4oc2VsZi5DT0xVTU5TKSkKICAg"
    "ICAgICBzZWxmLl90YWJsZS5zZXRIb3Jpem9udGFsSGVhZGVyTGFiZWxzKHNlbGYuQ09MVU1OUykK"
    "ICAgICAgICBoaCA9IHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKQogICAgICAgICMgQ29t"
    "cGFueSBhbmQgSm9iIFRpdGxlIHN0cmV0Y2gKICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9k"
    "ZSgwLCBRSGVhZGVyVmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgaGguc2V0U2VjdGlv"
    "blJlc2l6ZU1vZGUoMSwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5TdHJldGNoKQogICAgICAgICMg"
    "RGF0ZSBBcHBsaWVkIOKAlCBmaXhlZCByZWFkYWJsZSB3aWR0aAogICAgICAgIGhoLnNldFNlY3Rp"
    "b25SZXNpemVNb2RlKDIsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAgc2Vs"
    "Zi5fdGFibGUuc2V0Q29sdW1uV2lkdGgoMiwgMTAwKQogICAgICAgICMgTGluayBzdHJldGNoZXMK"
    "ICAgICAgICBoaC5zZXRTZWN0aW9uUmVzaXplTW9kZSgzLCBRSGVhZGVyVmlldy5SZXNpemVNb2Rl"
    "LlN0cmV0Y2gpCiAgICAgICAgIyBTdGF0dXMg4oCUIGZpeGVkIHdpZHRoCiAgICAgICAgaGguc2V0"
    "U2VjdGlvblJlc2l6ZU1vZGUoNCwgUUhlYWRlclZpZXcuUmVzaXplTW9kZS5GaXhlZCkKICAgICAg"
    "ICBzZWxmLl90YWJsZS5zZXRDb2x1bW5XaWR0aCg0LCA4MCkKICAgICAgICAjIE5vdGVzIHN0cmV0"
    "Y2hlcwogICAgICAgIGhoLnNldFNlY3Rpb25SZXNpemVNb2RlKDUsIFFIZWFkZXJWaWV3LlJlc2l6"
    "ZU1vZGUuU3RyZXRjaCkKCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uQmVoYXZpb3Io"
    "CiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9yLlNlbGVjdFJv"
    "d3MpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9uTW9kZSgKICAgICAgICAgICAgUUFi"
    "c3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uTW9kZS5FeHRlbmRlZFNlbGVjdGlvbikKICAgICAgICBz"
    "ZWxmLl90YWJsZS5zZXRBbHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVlKQogICAgICAgIHNlbGYuX3Rh"
    "YmxlLnNldFN0eWxlU2hlZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHJvb3QuYWRk"
    "V2lkZ2V0KHNlbGYuX3RhYmxlLCAxKQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fcmVjb3JkcyA9IHJlYWRfanNvbmwoc2VsZi5fcGF0aCkKICAgICAgICBzZWxm"
    "Ll90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoK"
    "ICAgICAgICAgICAgaGlkZGVuID0gYm9vbChyZWMuZ2V0KCJoaWRkZW4iLCBGYWxzZSkpCiAgICAg"
    "ICAgICAgIGlmIGhpZGRlbiBhbmQgbm90IHNlbGYuX3Nob3dfaGlkZGVuOgogICAgICAgICAgICAg"
    "ICAgY29udGludWUKICAgICAgICAgICAgciA9IHNlbGYuX3RhYmxlLnJvd0NvdW50KCkKICAgICAg"
    "ICAgICAgc2VsZi5fdGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHN0YXR1cyA9ICJBcmNo"
    "aXZlZCIgaWYgaGlkZGVuIGVsc2UgcmVjLmdldCgic3RhdHVzIiwiQWN0aXZlIikKICAgICAgICAg"
    "ICAgdmFscyA9IFsKICAgICAgICAgICAgICAgIHJlYy5nZXQoImNvbXBhbnkiLCIiKSwKICAgICAg"
    "ICAgICAgICAgIHJlYy5nZXQoImpvYl90aXRsZSIsIiIpLAogICAgICAgICAgICAgICAgcmVjLmdl"
    "dCgiZGF0ZV9hcHBsaWVkIiwiIiksCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJsaW5rIiwiIiks"
    "CiAgICAgICAgICAgICAgICBzdGF0dXMsCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJub3RlcyIs"
    "IiIpLAogICAgICAgICAgICBdCiAgICAgICAgICAgIGZvciBjLCB2IGluIGVudW1lcmF0ZSh2YWxz"
    "KToKICAgICAgICAgICAgICAgIGl0ZW0gPSBRVGFibGVXaWRnZXRJdGVtKHN0cih2KSkKICAgICAg"
    "ICAgICAgICAgIGlmIGhpZGRlbjoKICAgICAgICAgICAgICAgICAgICBpdGVtLnNldEZvcmVncm91"
    "bmQoUUNvbG9yKENfVEVYVF9ESU0pKQogICAgICAgICAgICAgICAgc2VsZi5fdGFibGUuc2V0SXRl"
    "bShyLCBjLCBpdGVtKQogICAgICAgICAgICAjIFN0b3JlIHJlY29yZCBpbmRleCBpbiBmaXJzdCBj"
    "b2x1bW4ncyB1c2VyIGRhdGEKICAgICAgICAgICAgc2VsZi5fdGFibGUuaXRlbShyLCAwKS5zZXRE"
    "YXRhKAogICAgICAgICAgICAgICAgUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLAogICAgICAgICAg"
    "ICAgICAgc2VsZi5fcmVjb3Jkcy5pbmRleChyZWMpCiAgICAgICAgICAgICkKCiAgICBkZWYgX3Nl"
    "bGVjdGVkX2luZGljZXMoc2VsZikgLT4gbGlzdFtpbnRdOgogICAgICAgIGluZGljZXMgPSBzZXQo"
    "KQogICAgICAgIGZvciBpdGVtIGluIHNlbGYuX3RhYmxlLnNlbGVjdGVkSXRlbXMoKToKICAgICAg"
    "ICAgICAgcm93X2l0ZW0gPSBzZWxmLl90YWJsZS5pdGVtKGl0ZW0ucm93KCksIDApCiAgICAgICAg"
    "ICAgIGlmIHJvd19pdGVtOgogICAgICAgICAgICAgICAgaWR4ID0gcm93X2l0ZW0uZGF0YShRdC5J"
    "dGVtRGF0YVJvbGUuVXNlclJvbGUpCiAgICAgICAgICAgICAgICBpZiBpZHggaXMgbm90IE5vbmU6"
    "CiAgICAgICAgICAgICAgICAgICAgaW5kaWNlcy5hZGQoaWR4KQogICAgICAgIHJldHVybiBzb3J0"
    "ZWQoaW5kaWNlcykKCiAgICBkZWYgX2RpYWxvZyhzZWxmLCByZWM6IGRpY3QgPSBOb25lKSAtPiBP"
    "cHRpb25hbFtkaWN0XToKICAgICAgICBkbGcgID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5z"
    "ZXRXaW5kb3dUaXRsZSgiSm9iIEFwcGxpY2F0aW9uIikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVl"
    "dChmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5y"
    "ZXNpemUoNTAwLCAzMjApCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKCiAgICAgICAg"
    "Y29tcGFueSA9IFFMaW5lRWRpdChyZWMuZ2V0KCJjb21wYW55IiwiIikgaWYgcmVjIGVsc2UgIiIp"
    "CiAgICAgICAgdGl0bGUgICA9IFFMaW5lRWRpdChyZWMuZ2V0KCJqb2JfdGl0bGUiLCIiKSBpZiBy"
    "ZWMgZWxzZSAiIikKICAgICAgICBkZSAgICAgID0gUURhdGVFZGl0KCkKICAgICAgICBkZS5zZXRD"
    "YWxlbmRhclBvcHVwKFRydWUpCiAgICAgICAgZGUuc2V0RGlzcGxheUZvcm1hdCgieXl5eS1NTS1k"
    "ZCIpCiAgICAgICAgaWYgcmVjIGFuZCByZWMuZ2V0KCJkYXRlX2FwcGxpZWQiKToKICAgICAgICAg"
    "ICAgZGUuc2V0RGF0ZShRRGF0ZS5mcm9tU3RyaW5nKHJlY1siZGF0ZV9hcHBsaWVkIl0sInl5eXkt"
    "TU0tZGQiKSkKICAgICAgICBlbHNlOgogICAgICAgICAgICBkZS5zZXREYXRlKFFEYXRlLmN1cnJl"
    "bnREYXRlKCkpCiAgICAgICAgbGluayAgICA9IFFMaW5lRWRpdChyZWMuZ2V0KCJsaW5rIiwiIikg"
    "aWYgcmVjIGVsc2UgIiIpCiAgICAgICAgc3RhdHVzICA9IFFMaW5lRWRpdChyZWMuZ2V0KCJzdGF0"
    "dXMiLCJBcHBsaWVkIikgaWYgcmVjIGVsc2UgIkFwcGxpZWQiKQogICAgICAgIG5vdGVzICAgPSBR"
    "TGluZUVkaXQocmVjLmdldCgibm90ZXMiLCIiKSBpZiByZWMgZWxzZSAiIikKCiAgICAgICAgZm9y"
    "IGxhYmVsLCB3aWRnZXQgaW4gWwogICAgICAgICAgICAoIkNvbXBhbnk6IiwgY29tcGFueSksICgi"
    "Sm9iIFRpdGxlOiIsIHRpdGxlKSwKICAgICAgICAgICAgKCJEYXRlIEFwcGxpZWQ6IiwgZGUpLCAo"
    "Ikxpbms6IiwgbGluayksCiAgICAgICAgICAgICgiU3RhdHVzOiIsIHN0YXR1cyksICgiTm90ZXM6"
    "Iiwgbm90ZXMpLAogICAgICAgIF06CiAgICAgICAgICAgIGZvcm0uYWRkUm93KGxhYmVsLCB3aWRn"
    "ZXQpCgogICAgICAgIGJ0bnMgPSBRSEJveExheW91dCgpCiAgICAgICAgb2sgPSBfZ290aGljX2J0"
    "bigiU2F2ZSIpOyBjeCA9IF9nb3RoaWNfYnRuKCJDYW5jZWwiKQogICAgICAgIG9rLmNsaWNrZWQu"
    "Y29ubmVjdChkbGcuYWNjZXB0KTsgY3guY2xpY2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAg"
    "ICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5zLmFkZFdpZGdldChjeCkKICAgICAgICBmb3JtLmFk"
    "ZFJvdyhidG5zKQoKICAgICAgICBpZiBkbGcuZXhlYygpID09IFFEaWFsb2cuRGlhbG9nQ29kZS5B"
    "Y2NlcHRlZDoKICAgICAgICAgICAgcmV0dXJuIHsKICAgICAgICAgICAgICAgICJjb21wYW55Ijog"
    "ICAgICBjb21wYW55LnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgImpvYl90aXRsZSI6"
    "ICAgIHRpdGxlLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAgICAgImRhdGVfYXBwbGllZCI6"
    "IGRlLmRhdGUoKS50b1N0cmluZygieXl5eS1NTS1kZCIpLAogICAgICAgICAgICAgICAgImxpbmsi"
    "OiAgICAgICAgIGxpbmsudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICAic3RhdHVzIjog"
    "ICAgICAgc3RhdHVzLnRleHQoKS5zdHJpcCgpIG9yICJBcHBsaWVkIiwKICAgICAgICAgICAgICAg"
    "ICJub3RlcyI6ICAgICAgICBub3Rlcy50ZXh0KCkuc3RyaXAoKSwKICAgICAgICAgICAgfQogICAg"
    "ICAgIHJldHVybiBOb25lCgogICAgZGVmIF9kb19hZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBw"
    "ID0gc2VsZi5fZGlhbG9nKCkKICAgICAgICBpZiBub3QgcDoKICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgbm93ID0gZGF0ZXRpbWUubm93KHRpbWV6b25lLnV0YykuaXNvZm9ybWF0KCkKICAgICAg"
    "ICBwLnVwZGF0ZSh7CiAgICAgICAgICAgICJpZCI6ICAgICAgICAgICAgIHN0cih1dWlkLnV1aWQ0"
    "KCkpLAogICAgICAgICAgICAiaGlkZGVuIjogICAgICAgICBGYWxzZSwKICAgICAgICAgICAgImNv"
    "bXBsZXRlZF9kYXRlIjogTm9uZSwKICAgICAgICAgICAgImNyZWF0ZWRfYXQiOiAgICAgbm93LAog"
    "ICAgICAgICAgICAidXBkYXRlZF9hdCI6ICAgICBub3csCiAgICAgICAgfSkKICAgICAgICBzZWxm"
    "Ll9yZWNvcmRzLmFwcGVuZChwKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYu"
    "X3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX21vZGlmeShzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIGlkeHMgPSBzZWxmLl9zZWxlY3RlZF9pbmRpY2VzKCkKICAgICAg"
    "ICBpZiBsZW4oaWR4cykgIT0gMToKICAgICAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24o"
    "c2VsZiwgIk1vZGlmeSIsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJTZWxl"
    "Y3QgZXhhY3RseSBvbmUgcm93IHRvIG1vZGlmeS4iKQogICAgICAgICAgICByZXR1cm4KICAgICAg"
    "ICByZWMgPSBzZWxmLl9yZWNvcmRzW2lkeHNbMF1dCiAgICAgICAgcCAgID0gc2VsZi5fZGlhbG9n"
    "KHJlYykKICAgICAgICBpZiBub3QgcDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgcmVjLnVw"
    "ZGF0ZShwKQogICAgICAgIHJlY1sidXBkYXRlZF9hdCJdID0gZGF0ZXRpbWUubm93KHRpbWV6b25l"
    "LnV0YykuaXNvZm9ybWF0KCkKICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9y"
    "ZWNvcmRzKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19oaWRlKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgZm9yIGlkeCBpbiBzZWxmLl9zZWxlY3RlZF9pbmRpY2VzKCk6CiAgICAg"
    "ICAgICAgIGlmIGlkeCA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAgICAgIHNlbGYu"
    "X3JlY29yZHNbaWR4XVsiaGlkZGVuIl0gICAgICAgICA9IFRydWUKICAgICAgICAgICAgICAgIHNl"
    "bGYuX3JlY29yZHNbaWR4XVsiY29tcGxldGVkX2RhdGUiXSA9ICgKICAgICAgICAgICAgICAgICAg"
    "ICBzZWxmLl9yZWNvcmRzW2lkeF0uZ2V0KCJjb21wbGV0ZWRfZGF0ZSIpIG9yCiAgICAgICAgICAg"
    "ICAgICAgICAgZGF0ZXRpbWUubm93KCkuZGF0ZSgpLmlzb2Zvcm1hdCgpCiAgICAgICAgICAgICAg"
    "ICApCiAgICAgICAgICAgICAgICBzZWxmLl9yZWNvcmRzW2lkeF1bInVwZGF0ZWRfYXQiXSA9ICgK"
    "ICAgICAgICAgICAgICAgICAgICBkYXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQo"
    "KQogICAgICAgICAgICAgICAgKQogICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYu"
    "X3JlY29yZHMpCiAgICAgICAgc2VsZi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX3VuaGlkZShzZWxm"
    "KSAtPiBOb25lOgogICAgICAgIGZvciBpZHggaW4gc2VsZi5fc2VsZWN0ZWRfaW5kaWNlcygpOgog"
    "ICAgICAgICAgICBpZiBpZHggPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9yZWNvcmRzW2lkeF1bImhpZGRlbiJdICAgICA9IEZhbHNlCiAgICAgICAgICAgICAgICBz"
    "ZWxmLl9yZWNvcmRzW2lkeF1bInVwZGF0ZWRfYXQiXSA9ICgKICAgICAgICAgICAgICAgICAgICBk"
    "YXRldGltZS5ub3codGltZXpvbmUudXRjKS5pc29mb3JtYXQoKQogICAgICAgICAgICAgICAgKQog"
    "ICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgc2Vs"
    "Zi5yZWZyZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlk"
    "eHMgPSBzZWxmLl9zZWxlY3RlZF9pbmRpY2VzKCkKICAgICAgICBpZiBub3QgaWR4czoKICAgICAg"
    "ICAgICAgcmV0dXJuCiAgICAgICAgcmVwbHkgPSBRTWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAg"
    "ICAgICAgc2VsZiwgIkRlbGV0ZSIsCiAgICAgICAgICAgIGYiRGVsZXRlIHtsZW4oaWR4cyl9IHNl"
    "bGVjdGVkIGFwcGxpY2F0aW9uKHMpPyBDYW5ub3QgYmUgdW5kb25lLiIsCiAgICAgICAgICAgIFFN"
    "ZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9u"
    "Lk5vCiAgICAgICAgKQogICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0"
    "dG9uLlllczoKICAgICAgICAgICAgYmFkID0gc2V0KGlkeHMpCiAgICAgICAgICAgIHNlbGYuX3Jl"
    "Y29yZHMgPSBbciBmb3IgaSwgciBpbiBlbnVtZXJhdGUoc2VsZi5fcmVjb3JkcykKICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICBpZiBpIG5vdCBpbiBiYWRdCiAgICAgICAgICAgIHdyaXRlX2pz"
    "b25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgp"
    "CgogICAgZGVmIF90b2dnbGVfaGlkZGVuKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc2hv"
    "d19oaWRkZW4gPSBub3Qgc2VsZi5fc2hvd19oaWRkZW4KICAgICAgICBzZWxmLl9idG5fdG9nZ2xl"
    "LnNldFRleHQoCiAgICAgICAgICAgICLimIAgSGlkZSBBcmNoaXZlZCIgaWYgc2VsZi5fc2hvd19o"
    "aWRkZW4gZWxzZSAi4pi9IFNob3cgQXJjaGl2ZWQiCiAgICAgICAgKQogICAgICAgIHNlbGYucmVm"
    "cmVzaCgpCgogICAgZGVmIF9kb19leHBvcnQoc2VsZikgLT4gTm9uZToKICAgICAgICBwYXRoLCBm"
    "aWx0ID0gUUZpbGVEaWFsb2cuZ2V0U2F2ZUZpbGVOYW1lKAogICAgICAgICAgICBzZWxmLCAiRXhw"
    "b3J0IEpvYiBUcmFja2VyIiwKICAgICAgICAgICAgc3RyKGNmZ19wYXRoKCJleHBvcnRzIikgLyAi"
    "am9iX3RyYWNrZXIuY3N2IiksCiAgICAgICAgICAgICJDU1YgRmlsZXMgKCouY3N2KTs7VGFiIERl"
    "bGltaXRlZCAoKi50eHQpIgogICAgICAgICkKICAgICAgICBpZiBub3QgcGF0aDoKICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgZGVsaW0gPSAiXHQiIGlmIHBhdGgubG93ZXIoKS5lbmRzd2l0aCgi"
    "LnR4dCIpIGVsc2UgIiwiCiAgICAgICAgaGVhZGVyID0gWyJjb21wYW55Iiwiam9iX3RpdGxlIiwi"
    "ZGF0ZV9hcHBsaWVkIiwibGluayIsCiAgICAgICAgICAgICAgICAgICJzdGF0dXMiLCJoaWRkZW4i"
    "LCJjb21wbGV0ZWRfZGF0ZSIsIm5vdGVzIl0KICAgICAgICB3aXRoIG9wZW4ocGF0aCwgInciLCBl"
    "bmNvZGluZz0idXRmLTgiLCBuZXdsaW5lPSIiKSBhcyBmOgogICAgICAgICAgICBmLndyaXRlKGRl"
    "bGltLmpvaW4oaGVhZGVyKSArICJcbiIpCiAgICAgICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVj"
    "b3JkczoKICAgICAgICAgICAgICAgIHZhbHMgPSBbCiAgICAgICAgICAgICAgICAgICAgcmVjLmdl"
    "dCgiY29tcGFueSIsIiIpLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImpvYl90aXRsZSIs"
    "IiIpLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImRhdGVfYXBwbGllZCIsIiIpLAogICAg"
    "ICAgICAgICAgICAgICAgIHJlYy5nZXQoImxpbmsiLCIiKSwKICAgICAgICAgICAgICAgICAgICBy"
    "ZWMuZ2V0KCJzdGF0dXMiLCIiKSwKICAgICAgICAgICAgICAgICAgICBzdHIoYm9vbChyZWMuZ2V0"
    "KCJoaWRkZW4iLEZhbHNlKSkpLAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoImNvbXBsZXRl"
    "ZF9kYXRlIiwiIikgb3IgIiIsCiAgICAgICAgICAgICAgICAgICAgcmVjLmdldCgibm90ZXMiLCIi"
    "KSwKICAgICAgICAgICAgICAgIF0KICAgICAgICAgICAgICAgIGYud3JpdGUoZGVsaW0uam9pbigK"
    "ICAgICAgICAgICAgICAgICAgICBzdHIodikucmVwbGFjZSgiXG4iLCIgIikucmVwbGFjZShkZWxp"
    "bSwiICIpCiAgICAgICAgICAgICAgICAgICAgZm9yIHYgaW4gdmFscwogICAgICAgICAgICAgICAg"
    "KSArICJcbiIpCiAgICAgICAgUU1lc3NhZ2VCb3guaW5mb3JtYXRpb24oc2VsZiwgIkV4cG9ydGVk"
    "IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIlNhdmVkIHRvIHtwYXRofSIpCgoK"
    "IyDilIDilIAgU0VMRiBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIFJlY29y"
    "ZHNUYWIoUVdpZGdldCk6CiAgICAiIiJHb29nbGUgRHJpdmUvRG9jcyByZWNvcmRzIGJyb3dzZXIg"
    "dGFiLiIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3Vw"
    "ZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAg"
    "ICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNiwgNiwgNiwgNikKICAgICAgICByb290LnNl"
    "dFNwYWNpbmcoNCkKCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwgPSBRTGFiZWwoIlJlY29yZHMg"
    "YXJlIG5vdCBsb2FkZWQgeWV0LiIpCiAgICAgICAgc2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LWZhbWlseToge0RF"
    "Q0tfRk9OVH0sIHNlcmlmOyBmb250LXNpemU6IDEwcHg7IgogICAgICAgICkKICAgICAgICByb290"
    "LmFkZFdpZGdldChzZWxmLnN0YXR1c19sYWJlbCkKCiAgICAgICAgc2VsZi5wYXRoX2xhYmVsID0g"
    "UUxhYmVsKCJQYXRoOiBNeSBEcml2ZSIpCiAgICAgICAgc2VsZi5wYXRoX2xhYmVsLnNldFN0eWxl"
    "U2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTERfRElNfTsgZm9udC1mYW1pbHk6IHtE"
    "RUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgcm9v"
    "dC5hZGRXaWRnZXQoc2VsZi5wYXRoX2xhYmVsKQoKICAgICAgICBzZWxmLnJlY29yZHNfbGlzdCA9"
    "IFFMaXN0V2lkZ2V0KCkKICAgICAgICBzZWxmLnJlY29yZHNfbGlzdC5zZXRTdHlsZVNoZWV0KAog"
    "ICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsgYm9yZGVy"
    "OiAxcHggc29saWQge0NfQk9SREVSfTsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0"
    "KHNlbGYucmVjb3Jkc19saXN0LCAxKQoKICAgIGRlZiBzZXRfaXRlbXMoc2VsZiwgZmlsZXM6IGxp"
    "c3RbZGljdF0sIHBhdGhfdGV4dDogc3RyID0gIk15IERyaXZlIikgLT4gTm9uZToKICAgICAgICBz"
    "ZWxmLnBhdGhfbGFiZWwuc2V0VGV4dChmIlBhdGg6IHtwYXRoX3RleHR9IikKICAgICAgICBzZWxm"
    "LnJlY29yZHNfbGlzdC5jbGVhcigpCiAgICAgICAgZm9yIGZpbGVfaW5mbyBpbiBmaWxlczoKICAg"
    "ICAgICAgICAgdGl0bGUgPSAoZmlsZV9pbmZvLmdldCgibmFtZSIpIG9yICJVbnRpdGxlZCIpLnN0"
    "cmlwKCkgb3IgIlVudGl0bGVkIgogICAgICAgICAgICBtaW1lID0gKGZpbGVfaW5mby5nZXQoIm1p"
    "bWVUeXBlIikgb3IgIiIpLnN0cmlwKCkKICAgICAgICAgICAgaWYgbWltZSA9PSAiYXBwbGljYXRp"
    "b24vdm5kLmdvb2dsZS1hcHBzLmZvbGRlciI6CiAgICAgICAgICAgICAgICBwcmVmaXggPSAi8J+T"
    "gSIKICAgICAgICAgICAgZWxpZiBtaW1lID09ICJhcHBsaWNhdGlvbi92bmQuZ29vZ2xlLWFwcHMu"
    "ZG9jdW1lbnQiOgogICAgICAgICAgICAgICAgcHJlZml4ID0gIvCfk50iCiAgICAgICAgICAgIGVs"
    "c2U6CiAgICAgICAgICAgICAgICBwcmVmaXggPSAi8J+ThCIKICAgICAgICAgICAgbW9kaWZpZWQg"
    "PSAoZmlsZV9pbmZvLmdldCgibW9kaWZpZWRUaW1lIikgb3IgIiIpLnJlcGxhY2UoIlQiLCAiICIp"
    "LnJlcGxhY2UoIloiLCAiIFVUQyIpCiAgICAgICAgICAgIHRleHQgPSBmIntwcmVmaXh9IHt0aXRs"
    "ZX0iICsgKGYiICAgIFt7bW9kaWZpZWR9XSIgaWYgbW9kaWZpZWQgZWxzZSAiIikKICAgICAgICAg"
    "ICAgaXRlbSA9IFFMaXN0V2lkZ2V0SXRlbSh0ZXh0KQogICAgICAgICAgICBpdGVtLnNldERhdGEo"
    "UXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlLCBmaWxlX2luZm8pCiAgICAgICAgICAgIHNlbGYucmVj"
    "b3Jkc19saXN0LmFkZEl0ZW0oaXRlbSkKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRUZXh0"
    "KGYiTG9hZGVkIHtsZW4oZmlsZXMpfSBHb29nbGUgRHJpdmUgaXRlbShzKS4iKQoKCmNsYXNzIFRh"
    "c2tzVGFiKFFXaWRnZXQpOgogICAgIiIiVGFzayByZWdpc3RyeSArIEdvb2dsZS1maXJzdCBlZGl0"
    "b3Igd29ya2Zsb3cgdGFiLiIiIgoKICAgIGRlZiBfX2luaXRfXygKICAgICAgICBzZWxmLAogICAg"
    "ICAgIHRhc2tzX3Byb3ZpZGVyLAogICAgICAgIG9uX2FkZF9lZGl0b3Jfb3BlbiwKICAgICAgICBv"
    "bl9jb21wbGV0ZV9zZWxlY3RlZCwKICAgICAgICBvbl9jYW5jZWxfc2VsZWN0ZWQsCiAgICAgICAg"
    "b25fdG9nZ2xlX2NvbXBsZXRlZCwKICAgICAgICBvbl9wdXJnZV9jb21wbGV0ZWQsCiAgICAgICAg"
    "b25fZmlsdGVyX2NoYW5nZWQsCiAgICAgICAgb25fZWRpdG9yX3NhdmUsCiAgICAgICAgb25fZWRp"
    "dG9yX2NhbmNlbCwKICAgICAgICBkaWFnbm9zdGljc19sb2dnZXI9Tm9uZSwKICAgICAgICBwYXJl"
    "bnQ9Tm9uZSwKICAgICk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAg"
    "c2VsZi5fdGFza3NfcHJvdmlkZXIgPSB0YXNrc19wcm92aWRlcgogICAgICAgIHNlbGYuX29uX2Fk"
    "ZF9lZGl0b3Jfb3BlbiA9IG9uX2FkZF9lZGl0b3Jfb3BlbgogICAgICAgIHNlbGYuX29uX2NvbXBs"
    "ZXRlX3NlbGVjdGVkID0gb25fY29tcGxldGVfc2VsZWN0ZWQKICAgICAgICBzZWxmLl9vbl9jYW5j"
    "ZWxfc2VsZWN0ZWQgPSBvbl9jYW5jZWxfc2VsZWN0ZWQKICAgICAgICBzZWxmLl9vbl90b2dnbGVf"
    "Y29tcGxldGVkID0gb25fdG9nZ2xlX2NvbXBsZXRlZAogICAgICAgIHNlbGYuX29uX3B1cmdlX2Nv"
    "bXBsZXRlZCA9IG9uX3B1cmdlX2NvbXBsZXRlZAogICAgICAgIHNlbGYuX29uX2ZpbHRlcl9jaGFu"
    "Z2VkID0gb25fZmlsdGVyX2NoYW5nZWQKICAgICAgICBzZWxmLl9vbl9lZGl0b3Jfc2F2ZSA9IG9u"
    "X2VkaXRvcl9zYXZlCiAgICAgICAgc2VsZi5fb25fZWRpdG9yX2NhbmNlbCA9IG9uX2VkaXRvcl9j"
    "YW5jZWwKICAgICAgICBzZWxmLl9kaWFnX2xvZ2dlciA9IGRpYWdub3N0aWNzX2xvZ2dlcgogICAg"
    "ICAgIHNlbGYuX3Nob3dfY29tcGxldGVkID0gRmFsc2UKICAgICAgICBzZWxmLl9yZWZyZXNoX3Ro"
    "cmVhZCA9IE5vbmUKICAgICAgICBzZWxmLl9idWlsZF91aSgpCgogICAgZGVmIF9idWlsZF91aShz"
    "ZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAgIHJv"
    "b3Quc2V0Q29udGVudHNNYXJnaW5zKDYsIDYsIDYsIDYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5n"
    "KDQpCiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2sgPSBRU3RhY2tlZFdpZGdldCgpCiAgICAg"
    "ICAgcm9vdC5hZGRXaWRnZXQoc2VsZi53b3Jrc3BhY2Vfc3RhY2ssIDEpCgogICAgICAgIG5vcm1h"
    "bCA9IFFXaWRnZXQoKQogICAgICAgIG5vcm1hbF9sYXlvdXQgPSBRVkJveExheW91dChub3JtYWwp"
    "CiAgICAgICAgbm9ybWFsX2xheW91dC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwgMCwgMCkKICAg"
    "ICAgICBub3JtYWxfbGF5b3V0LnNldFNwYWNpbmcoNCkKCiAgICAgICAgc2VsZi5zdGF0dXNfbGFi"
    "ZWwgPSBRTGFiZWwoIlRhc2sgcmVnaXN0cnkgaXMgbm90IGxvYWRlZCB5ZXQuIikKICAgICAgICBz"
    "ZWxmLnN0YXR1c19sYWJlbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19U"
    "RVhUX0RJTX07IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBw"
    "eDsiCiAgICAgICAgKQogICAgICAgIG5vcm1hbF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuc3RhdHVz"
    "X2xhYmVsKQoKICAgICAgICBmaWx0ZXJfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGZpbHRl"
    "cl9yb3cuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIERBVEUgUkFOR0UiKSkKICAgICAgICBz"
    "ZWxmLnRhc2tfZmlsdGVyX2NvbWJvID0gUUNvbWJvQm94KCkKICAgICAgICBzZWxmLnRhc2tfZmls"
    "dGVyX2NvbWJvLmFkZEl0ZW0oIldFRUsiLCAid2VlayIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRl"
    "cl9jb21iby5hZGRJdGVtKCJNT05USCIsICJtb250aCIpCiAgICAgICAgc2VsZi50YXNrX2ZpbHRl"
    "cl9jb21iby5hZGRJdGVtKCJORVhUIDMgTU9OVEhTIiwgIm5leHRfM19tb250aHMiKQogICAgICAg"
    "IHNlbGYudGFza19maWx0ZXJfY29tYm8uYWRkSXRlbSgiWUVBUiIsICJ5ZWFyIikKICAgICAgICBz"
    "ZWxmLnRhc2tfZmlsdGVyX2NvbWJvLnNldEN1cnJlbnRJbmRleCgyKQogICAgICAgIHNlbGYudGFz"
    "a19maWx0ZXJfY29tYm8uY3VycmVudEluZGV4Q2hhbmdlZC5jb25uZWN0KAogICAgICAgICAgICBs"
    "YW1iZGEgXzogc2VsZi5fb25fZmlsdGVyX2NoYW5nZWQoc2VsZi50YXNrX2ZpbHRlcl9jb21iby5j"
    "dXJyZW50RGF0YSgpIG9yICJuZXh0XzNfbW9udGhzIikKICAgICAgICApCiAgICAgICAgZmlsdGVy"
    "X3Jvdy5hZGRXaWRnZXQoc2VsZi50YXNrX2ZpbHRlcl9jb21ibykKICAgICAgICBmaWx0ZXJfcm93"
    "LmFkZFN0cmV0Y2goMSkKICAgICAgICBub3JtYWxfbGF5b3V0LmFkZExheW91dChmaWx0ZXJfcm93"
    "KQoKICAgICAgICBzZWxmLnRhc2tfdGFibGUgPSBRVGFibGVXaWRnZXQoMCwgNCkKICAgICAgICBz"
    "ZWxmLnRhc2tfdGFibGUuc2V0SG9yaXpvbnRhbEhlYWRlckxhYmVscyhbIlN0YXR1cyIsICJEdWUi"
    "LCAiVGFzayIsICJTb3VyY2UiXSkKICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0U2VsZWN0aW9u"
    "QmVoYXZpb3IoUUFic3RyYWN0SXRlbVZpZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykK"
    "ICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0U2VsZWN0aW9uTW9kZShRQWJzdHJhY3RJdGVtVmll"
    "dy5TZWxlY3Rpb25Nb2RlLkV4dGVuZGVkU2VsZWN0aW9uKQogICAgICAgIHNlbGYudGFza190YWJs"
    "ZS5zZXRFZGl0VHJpZ2dlcnMoUUFic3RyYWN0SXRlbVZpZXcuRWRpdFRyaWdnZXIuTm9FZGl0VHJp"
    "Z2dlcnMpCiAgICAgICAgc2VsZi50YXNrX3RhYmxlLnZlcnRpY2FsSGVhZGVyKCkuc2V0VmlzaWJs"
    "ZShGYWxzZSkKICAgICAgICBzZWxmLnRhc2tfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNl"
    "Y3Rpb25SZXNpemVNb2RlKDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuUmVzaXplVG9Db250ZW50"
    "cykKICAgICAgICBzZWxmLnRhc2tfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25S"
    "ZXNpemVNb2RlKDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuUmVzaXplVG9Db250ZW50cykKICAg"
    "ICAgICBzZWxmLnRhc2tfdGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVN"
    "b2RlKDIsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxmLnRhc2tf"
    "dGFibGUuaG9yaXpvbnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKDMsIFFIZWFkZXJW"
    "aWV3LlJlc2l6ZU1vZGUuUmVzaXplVG9Db250ZW50cykKICAgICAgICBzZWxmLnRhc2tfdGFibGUu"
    "c2V0U3R5bGVTaGVldChfZ290aGljX3RhYmxlX3N0eWxlKCkpCiAgICAgICAgc2VsZi50YXNrX3Rh"
    "YmxlLml0ZW1TZWxlY3Rpb25DaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fdXBkYXRlX2FjdGlvbl9idXR0"
    "b25fc3RhdGUpCiAgICAgICAgbm9ybWFsX2xheW91dC5hZGRXaWRnZXQoc2VsZi50YXNrX3RhYmxl"
    "LCAxKQoKICAgICAgICBhY3Rpb25zID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuYnRuX2Fk"
    "ZF90YXNrX3dvcmtzcGFjZSA9IF9nb3RoaWNfYnRuKCJBREQgVEFTSyIpCiAgICAgICAgc2VsZi5i"
    "dG5fY29tcGxldGVfdGFzayA9IF9nb3RoaWNfYnRuKCJDT01QTEVURSBTRUxFQ1RFRCIpCiAgICAg"
    "ICAgc2VsZi5idG5fY2FuY2VsX3Rhc2sgPSBfZ290aGljX2J0bigiQ0FOQ0VMIFNFTEVDVEVEIikK"
    "ICAgICAgICBzZWxmLmJ0bl90b2dnbGVfY29tcGxldGVkID0gX2dvdGhpY19idG4oIlNIT1cgQ09N"
    "UExFVEVEIikKICAgICAgICBzZWxmLmJ0bl9wdXJnZV9jb21wbGV0ZWQgPSBfZ290aGljX2J0bigi"
    "UFVSR0UgQ09NUExFVEVEIikKICAgICAgICBzZWxmLmJ0bl9hZGRfdGFza193b3Jrc3BhY2UuY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX29uX2FkZF9lZGl0b3Jfb3BlbikKICAgICAgICBzZWxmLmJ0bl9j"
    "b21wbGV0ZV90YXNrLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9jb21wbGV0ZV9zZWxlY3RlZCkK"
    "ICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzay5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fb25fY2Fu"
    "Y2VsX3NlbGVjdGVkKQogICAgICAgIHNlbGYuYnRuX3RvZ2dsZV9jb21wbGV0ZWQuY2xpY2tlZC5j"
    "b25uZWN0KHNlbGYuX29uX3RvZ2dsZV9jb21wbGV0ZWQpCiAgICAgICAgc2VsZi5idG5fcHVyZ2Vf"
    "Y29tcGxldGVkLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9wdXJnZV9jb21wbGV0ZWQpCiAgICAg"
    "ICAgc2VsZi5idG5fY29tcGxldGVfdGFzay5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYu"
    "YnRuX2NhbmNlbF90YXNrLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgZm9yIGJ0biBpbiAoCiAg"
    "ICAgICAgICAgIHNlbGYuYnRuX2FkZF90YXNrX3dvcmtzcGFjZSwKICAgICAgICAgICAgc2VsZi5i"
    "dG5fY29tcGxldGVfdGFzaywKICAgICAgICAgICAgc2VsZi5idG5fY2FuY2VsX3Rhc2ssCiAgICAg"
    "ICAgICAgIHNlbGYuYnRuX3RvZ2dsZV9jb21wbGV0ZWQsCiAgICAgICAgICAgIHNlbGYuYnRuX3B1"
    "cmdlX2NvbXBsZXRlZCwKICAgICAgICApOgogICAgICAgICAgICBhY3Rpb25zLmFkZFdpZGdldChi"
    "dG4pCiAgICAgICAgbm9ybWFsX2xheW91dC5hZGRMYXlvdXQoYWN0aW9ucykKICAgICAgICBzZWxm"
    "LndvcmtzcGFjZV9zdGFjay5hZGRXaWRnZXQobm9ybWFsKQoKICAgICAgICBlZGl0b3IgPSBRV2lk"
    "Z2V0KCkKICAgICAgICBlZGl0b3JfbGF5b3V0ID0gUVZCb3hMYXlvdXQoZWRpdG9yKQogICAgICAg"
    "IGVkaXRvcl9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgZWRp"
    "dG9yX2xheW91dC5zZXRTcGFjaW5nKDQpCiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQo"
    "X3NlY3Rpb25fbGJsKCLinacgVEFTSyBFRElUT1Ig4oCUIEdPT0dMRS1GSVJTVCIpKQogICAgICAg"
    "IHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVsID0gUUxhYmVsKCJDb25maWd1cmUgdGFzayBk"
    "ZXRhaWxzLCB0aGVuIHNhdmUgdG8gR29vZ2xlIENhbGVuZGFyLiIpCiAgICAgICAgc2VsZi50YXNr"
    "X2VkaXRvcl9zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3Jv"
    "dW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9ESU19OyBib3JkZXI6IDFweCBzb2xpZCB7Q19C"
    "T1JERVJ9OyBwYWRkaW5nOiA2cHg7IgogICAgICAgICkKICAgICAgICBlZGl0b3JfbGF5b3V0LmFk"
    "ZFdpZGdldChzZWxmLnRhc2tfZWRpdG9yX3N0YXR1c19sYWJlbCkKICAgICAgICBzZWxmLnRhc2tf"
    "ZWRpdG9yX25hbWUgPSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfbmFtZS5z"
    "ZXRQbGFjZWhvbGRlclRleHQoIlRhc2sgTmFtZSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRvcl9z"
    "dGFydF9kYXRlID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0YXJ0X2Rh"
    "dGUuc2V0UGxhY2Vob2xkZXJUZXh0KCJTdGFydCBEYXRlIChZWVlZLU1NLUREKSIpCiAgICAgICAg"
    "c2VsZi50YXNrX2VkaXRvcl9zdGFydF90aW1lID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRh"
    "c2tfZWRpdG9yX3N0YXJ0X3RpbWUuc2V0UGxhY2Vob2xkZXJUZXh0KCJTdGFydCBUaW1lIChISDpN"
    "TSkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfZW5kX2RhdGUgPSBRTGluZUVkaXQoKQogICAg"
    "ICAgIHNlbGYudGFza19lZGl0b3JfZW5kX2RhdGUuc2V0UGxhY2Vob2xkZXJUZXh0KCJFbmQgRGF0"
    "ZSAoWVlZWS1NTS1ERCkiKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfZW5kX3RpbWUgPSBRTGlu"
    "ZUVkaXQoKQogICAgICAgIHNlbGYudGFza19lZGl0b3JfZW5kX3RpbWUuc2V0UGxhY2Vob2xkZXJU"
    "ZXh0KCJFbmQgVGltZSAoSEg6TU0pIikKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2xvY2F0aW9u"
    "ID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX2xvY2F0aW9uLnNldFBsYWNl"
    "aG9sZGVyVGV4dCgiTG9jYXRpb24gKG9wdGlvbmFsKSIpCiAgICAgICAgc2VsZi50YXNrX2VkaXRv"
    "cl9yZWN1cnJlbmNlID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3JlY3Vy"
    "cmVuY2Uuc2V0UGxhY2Vob2xkZXJUZXh0KCJSZWN1cnJlbmNlIFJSVUxFIChvcHRpb25hbCkiKQog"
    "ICAgICAgIHNlbGYudGFza19lZGl0b3JfYWxsX2RheSA9IFFDaGVja0JveCgiQWxsLWRheSIpCiAg"
    "ICAgICAgc2VsZi50YXNrX2VkaXRvcl9ub3RlcyA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi50"
    "YXNrX2VkaXRvcl9ub3Rlcy5zZXRQbGFjZWhvbGRlclRleHQoIk5vdGVzIikKICAgICAgICBzZWxm"
    "LnRhc2tfZWRpdG9yX25vdGVzLnNldE1heGltdW1IZWlnaHQoOTApCiAgICAgICAgZm9yIHdpZGdl"
    "dCBpbiAoCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3JfbmFtZSwKICAgICAgICAgICAgc2Vs"
    "Zi50YXNrX2VkaXRvcl9zdGFydF9kYXRlLAogICAgICAgICAgICBzZWxmLnRhc2tfZWRpdG9yX3N0"
    "YXJ0X3RpbWUsCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3JfZW5kX2RhdGUsCiAgICAgICAg"
    "ICAgIHNlbGYudGFza19lZGl0b3JfZW5kX3RpbWUsCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0"
    "b3JfbG9jYXRpb24sCiAgICAgICAgICAgIHNlbGYudGFza19lZGl0b3JfcmVjdXJyZW5jZSwKICAg"
    "ICAgICApOgogICAgICAgICAgICBlZGl0b3JfbGF5b3V0LmFkZFdpZGdldCh3aWRnZXQpCiAgICAg"
    "ICAgZWRpdG9yX2xheW91dC5hZGRXaWRnZXQoc2VsZi50YXNrX2VkaXRvcl9hbGxfZGF5KQogICAg"
    "ICAgIGVkaXRvcl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYudGFza19lZGl0b3Jfbm90ZXMsIDEpCiAg"
    "ICAgICAgZWRpdG9yX2FjdGlvbnMgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX3NhdmUgPSBf"
    "Z290aGljX2J0bigiU0FWRSIpCiAgICAgICAgYnRuX2NhbmNlbCA9IF9nb3RoaWNfYnRuKCJDQU5D"
    "RUwiKQogICAgICAgIGJ0bl9zYXZlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9lZGl0b3Jfc2F2"
    "ZSkKICAgICAgICBidG5fY2FuY2VsLmNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9lZGl0b3JfY2Fu"
    "Y2VsKQogICAgICAgIGVkaXRvcl9hY3Rpb25zLmFkZFdpZGdldChidG5fc2F2ZSkKICAgICAgICBl"
    "ZGl0b3JfYWN0aW9ucy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBlZGl0b3JfYWN0aW9u"
    "cy5hZGRTdHJldGNoKDEpCiAgICAgICAgZWRpdG9yX2xheW91dC5hZGRMYXlvdXQoZWRpdG9yX2Fj"
    "dGlvbnMpCiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suYWRkV2lkZ2V0KGVkaXRvcikKCiAg"
    "ICAgICAgc2VsZi5ub3JtYWxfd29ya3NwYWNlID0gbm9ybWFsCiAgICAgICAgc2VsZi5lZGl0b3Jf"
    "d29ya3NwYWNlID0gZWRpdG9yCiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2suc2V0Q3VycmVu"
    "dFdpZGdldChzZWxmLm5vcm1hbF93b3Jrc3BhY2UpCgogICAgZGVmIF91cGRhdGVfYWN0aW9uX2J1"
    "dHRvbl9zdGF0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIGVuYWJsZWQgPSBib29sKHNlbGYuc2Vs"
    "ZWN0ZWRfdGFza19pZHMoKSkKICAgICAgICBzZWxmLmJ0bl9jb21wbGV0ZV90YXNrLnNldEVuYWJs"
    "ZWQoZW5hYmxlZCkKICAgICAgICBzZWxmLmJ0bl9jYW5jZWxfdGFzay5zZXRFbmFibGVkKGVuYWJs"
    "ZWQpCgogICAgZGVmIHNlbGVjdGVkX3Rhc2tfaWRzKHNlbGYpIC0+IGxpc3Rbc3RyXToKICAgICAg"
    "ICBpZHM6IGxpc3Rbc3RyXSA9IFtdCiAgICAgICAgZm9yIHIgaW4gcmFuZ2Uoc2VsZi50YXNrX3Rh"
    "YmxlLnJvd0NvdW50KCkpOgogICAgICAgICAgICBzdGF0dXNfaXRlbSA9IHNlbGYudGFza190YWJs"
    "ZS5pdGVtKHIsIDApCiAgICAgICAgICAgIGlmIHN0YXR1c19pdGVtIGlzIE5vbmU6CiAgICAgICAg"
    "ICAgICAgICBjb250aW51ZQogICAgICAgICAgICBpZiBub3Qgc3RhdHVzX2l0ZW0uaXNTZWxlY3Rl"
    "ZCgpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgdGFza19pZCA9IHN0YXR1"
    "c19pdGVtLmRhdGEoUXQuSXRlbURhdGFSb2xlLlVzZXJSb2xlKQogICAgICAgICAgICBpZiB0YXNr"
    "X2lkIGFuZCB0YXNrX2lkIG5vdCBpbiBpZHM6CiAgICAgICAgICAgICAgICBpZHMuYXBwZW5kKHRh"
    "c2tfaWQpCiAgICAgICAgcmV0dXJuIGlkcwoKICAgIGRlZiBsb2FkX3Rhc2tzKHNlbGYsIHRhc2tz"
    "OiBsaXN0W2RpY3RdKSAtPiBOb25lOgogICAgICAgIHNlbGYudGFza190YWJsZS5zZXRSb3dDb3Vu"
    "dCgwKQogICAgICAgIGZvciB0YXNrIGluIHRhc2tzOgogICAgICAgICAgICByb3cgPSBzZWxmLnRh"
    "c2tfdGFibGUucm93Q291bnQoKQogICAgICAgICAgICBzZWxmLnRhc2tfdGFibGUuaW5zZXJ0Um93"
    "KHJvdykKICAgICAgICAgICAgc3RhdHVzID0gKHRhc2suZ2V0KCJzdGF0dXMiKSBvciAicGVuZGlu"
    "ZyIpLmxvd2VyKCkKICAgICAgICAgICAgc3RhdHVzX2ljb24gPSAi4piRIiBpZiBzdGF0dXMgaW4g"
    "eyJjb21wbGV0ZWQiLCAiY2FuY2VsbGVkIn0gZWxzZSAi4oCiIgogICAgICAgICAgICBkdWUgPSAo"
    "dGFzay5nZXQoImR1ZV9hdCIpIG9yICIiKS5yZXBsYWNlKCJUIiwgIiAiKQogICAgICAgICAgICB0"
    "ZXh0ID0gKHRhc2suZ2V0KCJ0ZXh0Iikgb3IgIlJlbWluZGVyIikuc3RyaXAoKSBvciAiUmVtaW5k"
    "ZXIiCiAgICAgICAgICAgIHNvdXJjZSA9ICh0YXNrLmdldCgic291cmNlIikgb3IgImxvY2FsIiku"
    "bG93ZXIoKQogICAgICAgICAgICBzdGF0dXNfaXRlbSA9IFFUYWJsZVdpZGdldEl0ZW0oZiJ7c3Rh"
    "dHVzX2ljb259IHtzdGF0dXN9IikKICAgICAgICAgICAgc3RhdHVzX2l0ZW0uc2V0RGF0YShRdC5J"
    "dGVtRGF0YVJvbGUuVXNlclJvbGUsIHRhc2suZ2V0KCJpZCIpKQogICAgICAgICAgICBzZWxmLnRh"
    "c2tfdGFibGUuc2V0SXRlbShyb3csIDAsIHN0YXR1c19pdGVtKQogICAgICAgICAgICBzZWxmLnRh"
    "c2tfdGFibGUuc2V0SXRlbShyb3csIDEsIFFUYWJsZVdpZGdldEl0ZW0oZHVlKSkKICAgICAgICAg"
    "ICAgc2VsZi50YXNrX3RhYmxlLnNldEl0ZW0ocm93LCAyLCBRVGFibGVXaWRnZXRJdGVtKHRleHQp"
    "KQogICAgICAgICAgICBzZWxmLnRhc2tfdGFibGUuc2V0SXRlbShyb3csIDMsIFFUYWJsZVdpZGdl"
    "dEl0ZW0oc291cmNlKSkKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRUZXh0KGYiTG9hZGVk"
    "IHtsZW4odGFza3MpfSB0YXNrKHMpLiIpCiAgICAgICAgc2VsZi5fdXBkYXRlX2FjdGlvbl9idXR0"
    "b25fc3RhdGUoKQoKICAgIGRlZiBfZGlhZyhzZWxmLCBtZXNzYWdlOiBzdHIsIGxldmVsOiBzdHIg"
    "PSAiSU5GTyIpIC0+IE5vbmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBpZiBzZWxmLl9kaWFn"
    "X2xvZ2dlcjoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfbG9nZ2VyKG1lc3NhZ2UsIGxldmVs"
    "KQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICBkZWYgc3Rv"
    "cF9yZWZyZXNoX3dvcmtlcihzZWxmLCByZWFzb246IHN0ciA9ICIiKSAtPiBOb25lOgogICAgICAg"
    "IHRocmVhZCA9IGdldGF0dHIoc2VsZiwgIl9yZWZyZXNoX3RocmVhZCIsIE5vbmUpCiAgICAgICAg"
    "aWYgdGhyZWFkIGlzIG5vdCBOb25lIGFuZCBoYXNhdHRyKHRocmVhZCwgImlzUnVubmluZyIpIGFu"
    "ZCB0aHJlYWQuaXNSdW5uaW5nKCk6CiAgICAgICAgICAgIHNlbGYuX2RpYWcoCiAgICAgICAgICAg"
    "ICAgICBmIltUQVNLU11bVEhSRUFEXVtXQVJOXSBzdG9wIHJlcXVlc3RlZCBmb3IgcmVmcmVzaCB3"
    "b3JrZXIgcmVhc29uPXtyZWFzb24gb3IgJ3Vuc3BlY2lmaWVkJ30iLAogICAgICAgICAgICAgICAg"
    "IldBUk4iLAogICAgICAgICAgICApCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHRo"
    "cmVhZC5yZXF1ZXN0SW50ZXJydXB0aW9uKCkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoK"
    "ICAgICAgICAgICAgICAgIHBhc3MKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgdGhy"
    "ZWFkLnF1aXQoKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAg"
    "cGFzcwogICAgICAgICAgICB0aHJlYWQud2FpdCgyMDAwKQogICAgICAgIHNlbGYuX3JlZnJlc2hf"
    "dGhyZWFkID0gTm9uZQoKICAgIGRlZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgaWYg"
    "bm90IGNhbGxhYmxlKHNlbGYuX3Rhc2tzX3Byb3ZpZGVyKToKICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLmxvYWRfdGFza3Moc2VsZi5fdGFza3NfcHJvdmlk"
    "ZXIoKSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9k"
    "aWFnKGYiW1RBU0tTXVtUQUJdW0VSUk9SXSByZWZyZXNoIGZhaWxlZDoge2V4fSIsICJFUlJPUiIp"
    "CiAgICAgICAgICAgIHNlbGYuc3RvcF9yZWZyZXNoX3dvcmtlcihyZWFzb249InRhc2tzX3RhYl9y"
    "ZWZyZXNoX2V4Y2VwdGlvbiIpCgogICAgZGVmIGNsb3NlRXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5v"
    "bmU6CiAgICAgICAgc2VsZi5zdG9wX3JlZnJlc2hfd29ya2VyKHJlYXNvbj0idGFza3NfdGFiX2Ns"
    "b3NlIikKICAgICAgICBzdXBlcigpLmNsb3NlRXZlbnQoZXZlbnQpCgogICAgZGVmIHNldF9zaG93"
    "X2NvbXBsZXRlZChzZWxmLCBlbmFibGVkOiBib29sKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3No"
    "b3dfY29tcGxldGVkID0gYm9vbChlbmFibGVkKQogICAgICAgIHNlbGYuYnRuX3RvZ2dsZV9jb21w"
    "bGV0ZWQuc2V0VGV4dCgiSElERSBDT01QTEVURUQiIGlmIHNlbGYuX3Nob3dfY29tcGxldGVkIGVs"
    "c2UgIlNIT1cgQ09NUExFVEVEIikKCiAgICBkZWYgc2V0X3N0YXR1cyhzZWxmLCB0ZXh0OiBzdHIs"
    "IG9rOiBib29sID0gRmFsc2UpIC0+IE5vbmU6CiAgICAgICAgY29sb3IgPSBDX0dSRUVOIGlmIG9r"
    "IGVsc2UgQ19URVhUX0RJTQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVsLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtj"
    "b2xvcn07IGJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IHBhZGRpbmc6IDZweDsiCiAgICAg"
    "ICAgKQogICAgICAgIHNlbGYudGFza19lZGl0b3Jfc3RhdHVzX2xhYmVsLnNldFRleHQodGV4dCkK"
    "CiAgICBkZWYgb3Blbl9lZGl0b3Ioc2VsZikgLT4gTm9uZToKICAgICAgICBzZWxmLndvcmtzcGFj"
    "ZV9zdGFjay5zZXRDdXJyZW50V2lkZ2V0KHNlbGYuZWRpdG9yX3dvcmtzcGFjZSkKCiAgICBkZWYg"
    "Y2xvc2VfZWRpdG9yKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi53b3Jrc3BhY2Vfc3RhY2su"
    "c2V0Q3VycmVudFdpZGdldChzZWxmLm5vcm1hbF93b3Jrc3BhY2UpCgoKY2xhc3MgU2VsZlRhYihR"
    "V2lkZ2V0KToKICAgICIiIgogICAgUGVyc29uYSdzIGludGVybmFsIGRpYWxvZ3VlIHNwYWNlLgog"
    "ICAgUmVjZWl2ZXM6IGlkbGUgbmFycmF0aXZlIG91dHB1dCwgdW5zb2xpY2l0ZWQgdHJhbnNtaXNz"
    "aW9ucywKICAgICAgICAgICAgICBQb0kgbGlzdCBmcm9tIGRhaWx5IHJlZmxlY3Rpb24sIHVuYW5z"
    "d2VyZWQgcXVlc3Rpb24gZmxhZ3MsCiAgICAgICAgICAgICAgam91cm5hbCBsb2FkIG5vdGlmaWNh"
    "dGlvbnMuCiAgICBSZWFkLW9ubHkgZGlzcGxheS4gU2VwYXJhdGUgZnJvbSBTw6lhbmNlIFJlY29y"
    "ZCBhbHdheXMuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgog"
    "ICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQogICAgICAgIHJvb3QgPSBRVkJveExheW91"
    "dChzZWxmKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAg"
    "ICAgcm9vdC5zZXRTcGFjaW5nKDQpCgogICAgICAgIGhkciA9IFFIQm94TGF5b3V0KCkKICAgICAg"
    "ICBoZHIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibChmIuKdpyBJTk5FUiBTQU5DVFVNIOKAlCB7REVD"
    "S19OQU1FLnVwcGVyKCl9J1MgUFJJVkFURSBUSE9VR0hUUyIpKQogICAgICAgIHNlbGYuX2J0bl9j"
    "bGVhciA9IF9nb3RoaWNfYnRuKCLinJcgQ2xlYXIiKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5z"
    "ZXRGaXhlZFdpZHRoKDgwKQogICAgICAgIHNlbGYuX2J0bl9jbGVhci5jbGlja2VkLmNvbm5lY3Qo"
    "c2VsZi5jbGVhcikKICAgICAgICBoZHIuYWRkU3RyZXRjaCgpCiAgICAgICAgaGRyLmFkZFdpZGdl"
    "dChzZWxmLl9idG5fY2xlYXIpCiAgICAgICAgcm9vdC5hZGRMYXlvdXQoaGRyKQoKICAgICAgICBz"
    "ZWxmLl9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9kaXNwbGF5LnNldFJlYWRP"
    "bmx5KFRydWUpCiAgICAgICAgc2VsZi5fZGlzcGxheS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmImJhY2tncm91bmQ6IHtDX01PTklUT1J9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAg"
    "ICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19QVVJQTEVfRElNfTsgIgogICAgICAgICAgICBmImZv"
    "bnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzog"
    "OHB4OyIKICAgICAgICApCiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fZGlzcGxheSwgMSkK"
    "CiAgICBkZWYgYXBwZW5kKHNlbGYsIGxhYmVsOiBzdHIsIHRleHQ6IHN0cikgLT4gTm9uZToKICAg"
    "ICAgICB0aW1lc3RhbXAgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJUg6JU06JVMiKQogICAg"
    "ICAgIGNvbG9ycyA9IHsKICAgICAgICAgICAgIk5BUlJBVElWRSI6ICBDX0dPTEQsCiAgICAgICAg"
    "ICAgICJSRUZMRUNUSU9OIjogQ19QVVJQTEUsCiAgICAgICAgICAgICJKT1VSTkFMIjogICAgQ19T"
    "SUxWRVIsCiAgICAgICAgICAgICJQT0kiOiAgICAgICAgQ19HT0xEX0RJTSwKICAgICAgICAgICAg"
    "IlNZU1RFTSI6ICAgICBDX1RFWFRfRElNLAogICAgICAgIH0KICAgICAgICBjb2xvciA9IGNvbG9y"
    "cy5nZXQobGFiZWwudXBwZXIoKSwgQ19HT0xEKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuYXBwZW5k"
    "KAogICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7Q19URVhUX0RJTX07IGZvbnQtc2l6"
    "ZToxMHB4OyI+JwogICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAgICAgICAg"
    "ICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e2NvbG9yfTsgZm9udC13ZWlnaHQ6Ym9sZDsiPicKICAg"
    "ICAgICAgICAgZifinacge2xhYmVsfTwvc3Bhbj48YnI+JwogICAgICAgICAgICBmJzxzcGFuIHN0"
    "eWxlPSJjb2xvcjp7Q19HT0xEfTsiPnt0ZXh0fTwvc3Bhbj4nCiAgICAgICAgKQogICAgICAgIHNl"
    "bGYuX2Rpc3BsYXkuYXBwZW5kKCIiKQogICAgICAgIHNlbGYuX2Rpc3BsYXkudmVydGljYWxTY3Jv"
    "bGxCYXIoKS5zZXRWYWx1ZSgKICAgICAgICAgICAgc2VsZi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9s"
    "bEJhcigpLm1heGltdW0oKQogICAgICAgICkKCiAgICBkZWYgY2xlYXIoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl9kaXNwbGF5LmNsZWFyKCkKCgojIOKUgOKUgCBESUFHTk9TVElDUyBUQUIg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACmNsYXNzIERpYWdub3N0aWNzVGFiKFFXaWRnZXQpOgogICAgIiIiCiAgICBCYWNrZW5k"
    "IGRpYWdub3N0aWNzIGRpc3BsYXkuCiAgICBSZWNlaXZlczogaGFyZHdhcmUgZGV0ZWN0aW9uIHJl"
    "c3VsdHMsIGRlcGVuZGVuY3kgY2hlY2sgcmVzdWx0cywKICAgICAgICAgICAgICBBUEkgZXJyb3Jz"
    "LCBzeW5jIGZhaWx1cmVzLCB0aW1lciBldmVudHMsIGpvdXJuYWwgbG9hZCBub3RpY2VzLAogICAg"
    "ICAgICAgICAgIG1vZGVsIGxvYWQgc3RhdHVzLCBHb29nbGUgYXV0aCBldmVudHMuCiAgICBBbHdh"
    "eXMgc2VwYXJhdGUgZnJvbSBTw6lhbmNlIFJlY29yZC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRf"
    "XyhzZWxmLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAg"
    "ICAgICAgcm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01h"
    "cmdpbnMoNCwgNCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgaGRy"
    "ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGhkci5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacg"
    "RElBR05PU1RJQ1Mg4oCUIFNZU1RFTSAmIEJBQ0tFTkQgTE9HIikpCiAgICAgICAgc2VsZi5fYnRu"
    "X2NsZWFyID0gX2dvdGhpY19idG4oIuKclyBDbGVhciIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFy"
    "LnNldEZpeGVkV2lkdGgoODApCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyLmNsaWNrZWQuY29ubmVj"
    "dChzZWxmLmNsZWFyKQogICAgICAgIGhkci5hZGRTdHJldGNoKCkKICAgICAgICBoZHIuYWRkV2lk"
    "Z2V0KHNlbGYuX2J0bl9jbGVhcikKICAgICAgICByb290LmFkZExheW91dChoZHIpCgogICAgICAg"
    "IHNlbGYuX2Rpc3BsYXkgPSBRVGV4dEVkaXQoKQogICAgICAgIHNlbGYuX2Rpc3BsYXkuc2V0UmVh"
    "ZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9kaXNwbGF5LnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9yOiB7Q19TSUxWRVJ9OyAiCiAgICAg"
    "ICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZv"
    "bnQtZmFtaWx5OiAnQ291cmllciBOZXcnLCBtb25vc3BhY2U7ICIKICAgICAgICAgICAgZiJmb250"
    "LXNpemU6IDEwcHg7IHBhZGRpbmc6IDhweDsiCiAgICAgICAgKQogICAgICAgIHJvb3QuYWRkV2lk"
    "Z2V0KHNlbGYuX2Rpc3BsYXksIDEpCgogICAgZGVmIGxvZyhzZWxmLCBtZXNzYWdlOiBzdHIsIGxl"
    "dmVsOiBzdHIgPSAiSU5GTyIpIC0+IE5vbmU6CiAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUu"
    "bm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikKICAgICAgICBsZXZlbF9jb2xvcnMgPSB7CiAgICAg"
    "ICAgICAgICJJTkZPIjogIENfU0lMVkVSLAogICAgICAgICAgICAiT0siOiAgICBDX0dSRUVOLAog"
    "ICAgICAgICAgICAiV0FSTiI6ICBDX0dPTEQsCiAgICAgICAgICAgICJFUlJPUiI6IENfQkxPT0Qs"
    "CiAgICAgICAgICAgICJERUJVRyI6IENfVEVYVF9ESU0sCiAgICAgICAgfQogICAgICAgIGNvbG9y"
    "ID0gbGV2ZWxfY29sb3JzLmdldChsZXZlbC51cHBlcigpLCBDX1NJTFZFUikKICAgICAgICBzZWxm"
    "Ll9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVY"
    "VF9ESU19OyI+W3t0aW1lc3RhbXB9XTwvc3Bhbj4gJwogICAgICAgICAgICBmJzxzcGFuIHN0eWxl"
    "PSJjb2xvcjp7Y29sb3J9OyI+e21lc3NhZ2V9PC9zcGFuPicKICAgICAgICApCiAgICAgICAgc2Vs"
    "Zi5fZGlzcGxheS52ZXJ0aWNhbFNjcm9sbEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxm"
    "Ll9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4aW11bSgpCiAgICAgICAgKQoKICAgIGRl"
    "ZiBsb2dfbWFueShzZWxmLCBtZXNzYWdlczogbGlzdFtzdHJdLCBsZXZlbDogc3RyID0gIklORk8i"
    "KSAtPiBOb25lOgogICAgICAgIGZvciBtc2cgaW4gbWVzc2FnZXM6CiAgICAgICAgICAgIGx2bCA9"
    "IGxldmVsCiAgICAgICAgICAgIGlmICLinJMiIGluIG1zZzogICAgbHZsID0gIk9LIgogICAgICAg"
    "ICAgICBlbGlmICLinJciIGluIG1zZzogIGx2bCA9ICJXQVJOIgogICAgICAgICAgICBlbGlmICJF"
    "UlJPUiIgaW4gbXNnLnVwcGVyKCk6IGx2bCA9ICJFUlJPUiIKICAgICAgICAgICAgc2VsZi5sb2co"
    "bXNnLCBsdmwpCgogICAgZGVmIGNsZWFyKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZGlz"
    "cGxheS5jbGVhcigpCgoKIyDilIDilIAgTEVTU09OUyBUQUIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNs"
    "YXNzIExlc3NvbnNUYWIoUVdpZGdldCk6CiAgICAiIiIKICAgIExTTCBGb3JiaWRkZW4gUnVsZXNl"
    "dCBhbmQgY29kZSBsZXNzb25zIGJyb3dzZXIuCiAgICBBZGQsIHZpZXcsIHNlYXJjaCwgZGVsZXRl"
    "IGxlc3NvbnMuCiAgICAiIiIKCiAgICBkZWYgX19pbml0X18oc2VsZiwgZGI6ICJMZXNzb25zTGVh"
    "cm5lZERCIiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFyZW50KQog"
    "ICAgICAgIHNlbGYuX2RiID0gZGIKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCiAgICAgICAgc2Vs"
    "Zi5yZWZyZXNoKCkKCiAgICBkZWYgX3NldHVwX3VpKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm9v"
    "dCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoNCwg"
    "NCwgNCwgNCkKICAgICAgICByb290LnNldFNwYWNpbmcoNCkKCiAgICAgICAgIyBGaWx0ZXIgYmFy"
    "CiAgICAgICAgZmlsdGVyX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9zZWFyY2gg"
    "PSBRTGluZUVkaXQoKQogICAgICAgIHNlbGYuX3NlYXJjaC5zZXRQbGFjZWhvbGRlclRleHQoIlNl"
    "YXJjaCBsZXNzb25zLi4uIikKICAgICAgICBzZWxmLl9sYW5nX2ZpbHRlciA9IFFDb21ib0JveCgp"
    "CiAgICAgICAgc2VsZi5fbGFuZ19maWx0ZXIuYWRkSXRlbXMoWyJBbGwiLCAiTFNMIiwgIlB5dGhv"
    "biIsICJQeVNpZGU2IiwKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICJKYXZh"
    "U2NyaXB0IiwgIk90aGVyIl0pCiAgICAgICAgc2VsZi5fc2VhcmNoLnRleHRDaGFuZ2VkLmNvbm5l"
    "Y3Qoc2VsZi5yZWZyZXNoKQogICAgICAgIHNlbGYuX2xhbmdfZmlsdGVyLmN1cnJlbnRUZXh0Q2hh"
    "bmdlZC5jb25uZWN0KHNlbGYucmVmcmVzaCkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChR"
    "TGFiZWwoIlNlYXJjaDoiKSkKICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChzZWxmLl9zZWFy"
    "Y2gsIDEpCiAgICAgICAgZmlsdGVyX3Jvdy5hZGRXaWRnZXQoUUxhYmVsKCJMYW5ndWFnZToiKSkK"
    "ICAgICAgICBmaWx0ZXJfcm93LmFkZFdpZGdldChzZWxmLl9sYW5nX2ZpbHRlcikKICAgICAgICBy"
    "b290LmFkZExheW91dChmaWx0ZXJfcm93KQoKICAgICAgICBidG5fYmFyID0gUUhCb3hMYXlvdXQo"
    "KQogICAgICAgIGJ0bl9hZGQgPSBfZ290aGljX2J0bigi4pymIEFkZCBMZXNzb24iKQogICAgICAg"
    "IGJ0bl9kZWwgPSBfZ290aGljX2J0bigi4pyXIERlbGV0ZSIpCiAgICAgICAgYnRuX2FkZC5jbGlj"
    "a2VkLmNvbm5lY3Qoc2VsZi5fZG9fYWRkKQogICAgICAgIGJ0bl9kZWwuY2xpY2tlZC5jb25uZWN0"
    "KHNlbGYuX2RvX2RlbGV0ZSkKICAgICAgICBidG5fYmFyLmFkZFdpZGdldChidG5fYWRkKQogICAg"
    "ICAgIGJ0bl9iYXIuYWRkV2lkZ2V0KGJ0bl9kZWwpCiAgICAgICAgYnRuX2Jhci5hZGRTdHJldGNo"
    "KCkKICAgICAgICByb290LmFkZExheW91dChidG5fYmFyKQoKICAgICAgICBzZWxmLl90YWJsZSA9"
    "IFFUYWJsZVdpZGdldCgwLCA0KQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6b250YWxIZWFk"
    "ZXJMYWJlbHMoCiAgICAgICAgICAgIFsiTGFuZ3VhZ2UiLCAiUmVmZXJlbmNlIEtleSIsICJTdW1t"
    "YXJ5IiwgIkVudmlyb25tZW50Il0KICAgICAgICApCiAgICAgICAgc2VsZi5fdGFibGUuaG9yaXpv"
    "bnRhbEhlYWRlcigpLnNldFNlY3Rpb25SZXNpemVNb2RlKAogICAgICAgICAgICAyLCBRSGVhZGVy"
    "Vmlldy5SZXNpemVNb2RlLlN0cmV0Y2gpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0U2VsZWN0aW9u"
    "QmVoYXZpb3IoCiAgICAgICAgICAgIFFBYnN0cmFjdEl0ZW1WaWV3LlNlbGVjdGlvbkJlaGF2aW9y"
    "LlNlbGVjdFJvd3MpCiAgICAgICAgc2VsZi5fdGFibGUuc2V0QWx0ZXJuYXRpbmdSb3dDb2xvcnMo"
    "VHJ1ZSkKICAgICAgICBzZWxmLl90YWJsZS5zZXRTdHlsZVNoZWV0KF9nb3RoaWNfdGFibGVfc3R5"
    "bGUoKSkKICAgICAgICBzZWxmLl90YWJsZS5pdGVtU2VsZWN0aW9uQ2hhbmdlZC5jb25uZWN0KHNl"
    "bGYuX29uX3NlbGVjdCkKCiAgICAgICAgIyBVc2Ugc3BsaXR0ZXIgYmV0d2VlbiB0YWJsZSBhbmQg"
    "ZGV0YWlsCiAgICAgICAgc3BsaXR0ZXIgPSBRU3BsaXR0ZXIoUXQuT3JpZW50YXRpb24uVmVydGlj"
    "YWwpCiAgICAgICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlKQoKICAgICAgICAjIERl"
    "dGFpbCBwYW5lbAogICAgICAgIGRldGFpbF93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBkZXRh"
    "aWxfbGF5b3V0ID0gUVZCb3hMYXlvdXQoZGV0YWlsX3dpZGdldCkKICAgICAgICBkZXRhaWxfbGF5"
    "b3V0LnNldENvbnRlbnRzTWFyZ2lucygwLCA0LCAwLCAwKQogICAgICAgIGRldGFpbF9sYXlvdXQu"
    "c2V0U3BhY2luZygyKQoKICAgICAgICBkZXRhaWxfaGVhZGVyID0gUUhCb3hMYXlvdXQoKQogICAg"
    "ICAgIGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIEZVTEwgUlVMRSIp"
    "KQogICAgICAgIGRldGFpbF9oZWFkZXIuYWRkU3RyZXRjaCgpCiAgICAgICAgc2VsZi5fYnRuX2Vk"
    "aXRfcnVsZSA9IF9nb3RoaWNfYnRuKCJFZGl0IikKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxl"
    "LnNldEZpeGVkV2lkdGgoNTApCiAgICAgICAgc2VsZi5fYnRuX2VkaXRfcnVsZS5zZXRDaGVja2Fi"
    "bGUoVHJ1ZSkKICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnRvZ2dsZWQuY29ubmVjdChzZWxm"
    "Ll90b2dnbGVfZWRpdF9tb2RlKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUgPSBfZ290aGlj"
    "X2J0bigiU2F2ZSIpCiAgICAgICAgc2VsZi5fYnRuX3NhdmVfcnVsZS5zZXRGaXhlZFdpZHRoKDUw"
    "KQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuc2V0VmlzaWJsZShGYWxzZSkKICAgICAgICBz"
    "ZWxmLl9idG5fc2F2ZV9ydWxlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9zYXZlX3J1bGVfZWRpdCkK"
    "ICAgICAgICBkZXRhaWxfaGVhZGVyLmFkZFdpZGdldChzZWxmLl9idG5fZWRpdF9ydWxlKQogICAg"
    "ICAgIGRldGFpbF9oZWFkZXIuYWRkV2lkZ2V0KHNlbGYuX2J0bl9zYXZlX3J1bGUpCiAgICAgICAg"
    "ZGV0YWlsX2xheW91dC5hZGRMYXlvdXQoZGV0YWlsX2hlYWRlcikKCiAgICAgICAgc2VsZi5fZGV0"
    "YWlsID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9kZXRhaWwuc2V0UmVhZE9ubHkoVHJ1ZSkK"
    "ICAgICAgICBzZWxmLl9kZXRhaWwuc2V0TWluaW11bUhlaWdodCgxMjApCiAgICAgICAgc2VsZi5f"
    "ZGV0YWlsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsg"
    "Y29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9S"
    "REVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZv"
    "bnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAgICApCiAgICAgICAgZGV0YWlsX2xh"
    "eW91dC5hZGRXaWRnZXQoc2VsZi5fZGV0YWlsKQogICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChk"
    "ZXRhaWxfd2lkZ2V0KQogICAgICAgIHNwbGl0dGVyLnNldFNpemVzKFszMDAsIDE4MF0pCiAgICAg"
    "ICAgcm9vdC5hZGRXaWRnZXQoc3BsaXR0ZXIsIDEpCgogICAgICAgIHNlbGYuX3JlY29yZHM6IGxp"
    "c3RbZGljdF0gPSBbXQogICAgICAgIHNlbGYuX2VkaXRpbmdfcm93OiBpbnQgPSAtMQoKICAgIGRl"
    "ZiByZWZyZXNoKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcSAgICA9IHNlbGYuX3NlYXJjaC50ZXh0"
    "KCkKICAgICAgICBsYW5nID0gc2VsZi5fbGFuZ19maWx0ZXIuY3VycmVudFRleHQoKQogICAgICAg"
    "IGxhbmcgPSAiIiBpZiBsYW5nID09ICJBbGwiIGVsc2UgbGFuZwogICAgICAgIHNlbGYuX3JlY29y"
    "ZHMgPSBzZWxmLl9kYi5zZWFyY2gocXVlcnk9cSwgbGFuZ3VhZ2U9bGFuZykKICAgICAgICBzZWxm"
    "Ll90YWJsZS5zZXRSb3dDb3VudCgwKQogICAgICAgIGZvciByZWMgaW4gc2VsZi5fcmVjb3JkczoK"
    "ICAgICAgICAgICAgciA9IHNlbGYuX3RhYmxlLnJvd0NvdW50KCkKICAgICAgICAgICAgc2VsZi5f"
    "dGFibGUuaW5zZXJ0Um93KHIpCiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMCwK"
    "ICAgICAgICAgICAgICAgIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgibGFuZ3VhZ2UiLCIiKSkp"
    "CiAgICAgICAgICAgIHNlbGYuX3RhYmxlLnNldEl0ZW0ociwgMSwKICAgICAgICAgICAgICAgIFFU"
    "YWJsZVdpZGdldEl0ZW0ocmVjLmdldCgicmVmZXJlbmNlX2tleSIsIiIpKSkKICAgICAgICAgICAg"
    "c2VsZi5fdGFibGUuc2V0SXRlbShyLCAyLAogICAgICAgICAgICAgICAgUVRhYmxlV2lkZ2V0SXRl"
    "bShyZWMuZ2V0KCJzdW1tYXJ5IiwiIikpKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVt"
    "KHIsIDMsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5nZXQoImVudmlyb25t"
    "ZW50IiwiIikpKQoKICAgIGRlZiBfb25fc2VsZWN0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93"
    "ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAgICAgICAgc2VsZi5fZWRpdGluZ19yb3cgPSBy"
    "b3cKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToKICAgICAgICAgICAg"
    "cmVjID0gc2VsZi5fcmVjb3Jkc1tyb3ddCiAgICAgICAgICAgIHNlbGYuX2RldGFpbC5zZXRQbGFp"
    "blRleHQoCiAgICAgICAgICAgICAgICByZWMuZ2V0KCJmdWxsX3J1bGUiLCIiKSArICJcblxuIiAr"
    "CiAgICAgICAgICAgICAgICAoIlJlc29sdXRpb246ICIgKyByZWMuZ2V0KCJyZXNvbHV0aW9uIiwi"
    "IikgaWYgcmVjLmdldCgicmVzb2x1dGlvbiIpIGVsc2UgIiIpCiAgICAgICAgICAgICkKICAgICAg"
    "ICAgICAgIyBSZXNldCBlZGl0IG1vZGUgb24gbmV3IHNlbGVjdGlvbgogICAgICAgICAgICBzZWxm"
    "Ll9idG5fZWRpdF9ydWxlLnNldENoZWNrZWQoRmFsc2UpCgogICAgZGVmIF90b2dnbGVfZWRpdF9t"
    "b2RlKHNlbGYsIGVkaXRpbmc6IGJvb2wpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fZGV0YWlsLnNl"
    "dFJlYWRPbmx5KG5vdCBlZGl0aW5nKQogICAgICAgIHNlbGYuX2J0bl9zYXZlX3J1bGUuc2V0Vmlz"
    "aWJsZShlZGl0aW5nKQogICAgICAgIHNlbGYuX2J0bl9lZGl0X3J1bGUuc2V0VGV4dCgiQ2FuY2Vs"
    "IiBpZiBlZGl0aW5nIGVsc2UgIkVkaXQiKQogICAgICAgIGlmIGVkaXRpbmc6CiAgICAgICAgICAg"
    "IHNlbGYuX2RldGFpbC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5k"
    "OiB7Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAx"
    "cHggc29saWQge0NfR09MRF9ESU19OyAiCiAgICAgICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7"
    "REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFweDsgcGFkZGluZzogNHB4OyIKICAgICAg"
    "ICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYuX2RldGFpbC5zZXRTdHlsZVNo"
    "ZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfR09M"
    "RH07ICIKICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgog"
    "ICAgICAgICAgICAgICAgZiJmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyBmb250LXNp"
    "emU6IDExcHg7IHBhZGRpbmc6IDRweDsiCiAgICAgICAgICAgICkKICAgICAgICAgICAgIyBSZWxv"
    "YWQgb3JpZ2luYWwgY29udGVudCBvbiBjYW5jZWwKICAgICAgICAgICAgc2VsZi5fb25fc2VsZWN0"
    "KCkKCiAgICBkZWYgX3NhdmVfcnVsZV9lZGl0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0g"
    "c2VsZi5fZWRpdGluZ19yb3cKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRz"
    "KToKICAgICAgICAgICAgdGV4dCA9IHNlbGYuX2RldGFpbC50b1BsYWluVGV4dCgpLnN0cmlwKCkK"
    "ICAgICAgICAgICAgIyBTcGxpdCByZXNvbHV0aW9uIGJhY2sgb3V0IGlmIHByZXNlbnQKICAgICAg"
    "ICAgICAgaWYgIlxuXG5SZXNvbHV0aW9uOiAiIGluIHRleHQ6CiAgICAgICAgICAgICAgICBwYXJ0"
    "cyA9IHRleHQuc3BsaXQoIlxuXG5SZXNvbHV0aW9uOiAiLCAxKQogICAgICAgICAgICAgICAgZnVs"
    "bF9ydWxlICA9IHBhcnRzWzBdLnN0cmlwKCkKICAgICAgICAgICAgICAgIHJlc29sdXRpb24gPSBw"
    "YXJ0c1sxXS5zdHJpcCgpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBmdWxsX3J1"
    "bGUgID0gdGV4dAogICAgICAgICAgICAgICAgcmVzb2x1dGlvbiA9IHNlbGYuX3JlY29yZHNbcm93"
    "XS5nZXQoInJlc29sdXRpb24iLCAiIikKICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tyb3ddWyJm"
    "dWxsX3J1bGUiXSAgPSBmdWxsX3J1bGUKICAgICAgICAgICAgc2VsZi5fcmVjb3Jkc1tyb3ddWyJy"
    "ZXNvbHV0aW9uIl0gPSByZXNvbHV0aW9uCiAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX2Ri"
    "Ll9wYXRoLCBzZWxmLl9yZWNvcmRzKQogICAgICAgICAgICBzZWxmLl9idG5fZWRpdF9ydWxlLnNl"
    "dENoZWNrZWQoRmFsc2UpCiAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9kb19h"
    "ZGQoc2VsZikgLT4gTm9uZToKICAgICAgICBkbGcgPSBRRGlhbG9nKHNlbGYpCiAgICAgICAgZGxn"
    "LnNldFdpbmRvd1RpdGxlKCJBZGQgTGVzc29uIikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChm"
    "ImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5yZXNp"
    "emUoNTAwLCA0MDApCiAgICAgICAgZm9ybSA9IFFGb3JtTGF5b3V0KGRsZykKICAgICAgICBlbnYg"
    "ID0gUUxpbmVFZGl0KCJMU0wiKQogICAgICAgIGxhbmcgPSBRTGluZUVkaXQoIkxTTCIpCiAgICAg"
    "ICAgcmVmICA9IFFMaW5lRWRpdCgpCiAgICAgICAgc3VtbSA9IFFMaW5lRWRpdCgpCiAgICAgICAg"
    "cnVsZSA9IFFUZXh0RWRpdCgpCiAgICAgICAgcnVsZS5zZXRNYXhpbXVtSGVpZ2h0KDEwMCkKICAg"
    "ICAgICByZXMgID0gUUxpbmVFZGl0KCkKICAgICAgICBsaW5rID0gUUxpbmVFZGl0KCkKICAgICAg"
    "ICBmb3IgbGFiZWwsIHcgaW4gWwogICAgICAgICAgICAoIkVudmlyb25tZW50OiIsIGVudiksICgi"
    "TGFuZ3VhZ2U6IiwgbGFuZyksCiAgICAgICAgICAgICgiUmVmZXJlbmNlIEtleToiLCByZWYpLCAo"
    "IlN1bW1hcnk6Iiwgc3VtbSksCiAgICAgICAgICAgICgiRnVsbCBSdWxlOiIsIHJ1bGUpLCAoIlJl"
    "c29sdXRpb246IiwgcmVzKSwKICAgICAgICAgICAgKCJMaW5rOiIsIGxpbmspLAogICAgICAgIF06"
    "CiAgICAgICAgICAgIGZvcm0uYWRkUm93KGxhYmVsLCB3KQogICAgICAgIGJ0bnMgPSBRSEJveExh"
    "eW91dCgpCiAgICAgICAgb2sgPSBfZ290aGljX2J0bigiU2F2ZSIpOyBjeCA9IF9nb3RoaWNfYnRu"
    "KCJDYW5jZWwiKQogICAgICAgIG9rLmNsaWNrZWQuY29ubmVjdChkbGcuYWNjZXB0KTsgY3guY2xp"
    "Y2tlZC5jb25uZWN0KGRsZy5yZWplY3QpCiAgICAgICAgYnRucy5hZGRXaWRnZXQob2spOyBidG5z"
    "LmFkZFdpZGdldChjeCkKICAgICAgICBmb3JtLmFkZFJvdyhidG5zKQogICAgICAgIGlmIGRsZy5l"
    "eGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICBzZWxmLl9k"
    "Yi5hZGQoCiAgICAgICAgICAgICAgICBlbnZpcm9ubWVudD1lbnYudGV4dCgpLnN0cmlwKCksCiAg"
    "ICAgICAgICAgICAgICBsYW5ndWFnZT1sYW5nLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAgICAg"
    "ICAgcmVmZXJlbmNlX2tleT1yZWYudGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICBzdW1t"
    "YXJ5PXN1bW0udGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICBmdWxsX3J1bGU9cnVsZS50"
    "b1BsYWluVGV4dCgpLnN0cmlwKCksCiAgICAgICAgICAgICAgICByZXNvbHV0aW9uPXJlcy50ZXh0"
    "KCkuc3RyaXAoKSwKICAgICAgICAgICAgICAgIGxpbms9bGluay50ZXh0KCkuc3RyaXAoKSwKICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZGVsZXRl"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUuY3VycmVudFJvdygpCiAg"
    "ICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAgICAgICAgICAgIHJlY19p"
    "ZCA9IHNlbGYuX3JlY29yZHNbcm93XS5nZXQoImlkIiwiIikKICAgICAgICAgICAgcmVwbHkgPSBR"
    "TWVzc2FnZUJveC5xdWVzdGlvbigKICAgICAgICAgICAgICAgIHNlbGYsICJEZWxldGUgTGVzc29u"
    "IiwKICAgICAgICAgICAgICAgICJEZWxldGUgdGhpcyBsZXNzb24/IENhbm5vdCBiZSB1bmRvbmUu"
    "IiwKICAgICAgICAgICAgICAgIFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlllcyB8IFFNZXNz"
    "YWdlQm94LlN0YW5kYXJkQnV0dG9uLk5vCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgcmVw"
    "bHkgPT0gUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzOgogICAgICAgICAgICAgICAgc2Vs"
    "Zi5fZGIuZGVsZXRlKHJlY19pZCkKICAgICAgICAgICAgICAgIHNlbGYucmVmcmVzaCgpCgoKIyDi"
    "lIDilIAgTU9EVUxFIFRSQUNLRVIgVEFCIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgApjbGFzcyBNb2R1bGVUcmFja2VyVGFiKFFXaWRnZXQpOgog"
    "ICAgIiIiCiAgICBQZXJzb25hbCBtb2R1bGUgcGlwZWxpbmUgdHJhY2tlci4KICAgIFRyYWNrIHBs"
    "YW5uZWQvaW4tcHJvZ3Jlc3MvYnVpbHQgbW9kdWxlcyBhcyB0aGV5IGFyZSBkZXNpZ25lZC4KICAg"
    "IEVhY2ggbW9kdWxlIGhhczogTmFtZSwgU3RhdHVzLCBEZXNjcmlwdGlvbiwgTm90ZXMuCiAgICBF"
    "eHBvcnQgdG8gVFhUIGZvciBwYXN0aW5nIGludG8gc2Vzc2lvbnMuCiAgICBJbXBvcnQ6IHBhc3Rl"
    "IGEgZmluYWxpemVkIHNwZWMsIGl0IHBhcnNlcyBuYW1lIGFuZCBkZXRhaWxzLgogICAgVGhpcyBp"
    "cyBhIGRlc2lnbiBub3RlYm9vayDigJQgbm90IGNvbm5lY3RlZCB0byBkZWNrX2J1aWxkZXIncyBN"
    "T0RVTEUgcmVnaXN0cnkuCiAgICAiIiIKCiAgICBTVEFUVVNFUyA9IFsiSWRlYSIsICJEZXNpZ25p"
    "bmciLCAiUmVhZHkgdG8gQnVpbGQiLCAiUGFydGlhbCIsICJCdWlsdCJdCgogICAgZGVmIF9faW5p"
    "dF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBlcigpLl9faW5pdF9fKHBhcmVudCkK"
    "ICAgICAgICBzZWxmLl9wYXRoID0gY2ZnX3BhdGgoIm1lbW9yaWVzIikgLyAibW9kdWxlX3RyYWNr"
    "ZXIuanNvbmwiCiAgICAgICAgc2VsZi5fcmVjb3JkczogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAg"
    "c2VsZi5fc2V0dXBfdWkoKQogICAgICAgIHNlbGYucmVmcmVzaCgpCgogICAgZGVmIF9zZXR1cF91"
    "aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAgICAg"
    "IHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgcm9vdC5zZXRTcGFj"
    "aW5nKDQpCgogICAgICAgICMgQnV0dG9uIGJhcgogICAgICAgIGJ0bl9iYXIgPSBRSEJveExheW91"
    "dCgpCiAgICAgICAgc2VsZi5fYnRuX2FkZCAgICA9IF9nb3RoaWNfYnRuKCJBZGQgTW9kdWxlIikK"
    "ICAgICAgICBzZWxmLl9idG5fZWRpdCAgID0gX2dvdGhpY19idG4oIkVkaXQiKQogICAgICAgIHNl"
    "bGYuX2J0bl9kZWxldGUgPSBfZ290aGljX2J0bigiRGVsZXRlIikKICAgICAgICBzZWxmLl9idG5f"
    "ZXhwb3J0ID0gX2dvdGhpY19idG4oIkV4cG9ydCBUWFQiKQogICAgICAgIHNlbGYuX2J0bl9pbXBv"
    "cnQgPSBfZ290aGljX2J0bigiSW1wb3J0IFNwZWMiKQogICAgICAgIGZvciBiIGluIChzZWxmLl9i"
    "dG5fYWRkLCBzZWxmLl9idG5fZWRpdCwgc2VsZi5fYnRuX2RlbGV0ZSwKICAgICAgICAgICAgICAg"
    "ICAgc2VsZi5fYnRuX2V4cG9ydCwgc2VsZi5fYnRuX2ltcG9ydCk6CiAgICAgICAgICAgIGIuc2V0"
    "TWluaW11bVdpZHRoKDgwKQogICAgICAgICAgICBiLnNldE1pbmltdW1IZWlnaHQoMjYpCiAgICAg"
    "ICAgICAgIGJ0bl9iYXIuYWRkV2lkZ2V0KGIpCiAgICAgICAgYnRuX2Jhci5hZGRTdHJldGNoKCkK"
    "ICAgICAgICByb290LmFkZExheW91dChidG5fYmFyKQoKICAgICAgICBzZWxmLl9idG5fYWRkLmNs"
    "aWNrZWQuY29ubmVjdChzZWxmLl9kb19hZGQpCiAgICAgICAgc2VsZi5fYnRuX2VkaXQuY2xpY2tl"
    "ZC5jb25uZWN0KHNlbGYuX2RvX2VkaXQpCiAgICAgICAgc2VsZi5fYnRuX2RlbGV0ZS5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fZG9fZGVsZXRlKQogICAgICAgIHNlbGYuX2J0bl9leHBvcnQuY2xpY2tl"
    "ZC5jb25uZWN0KHNlbGYuX2RvX2V4cG9ydCkKICAgICAgICBzZWxmLl9idG5faW1wb3J0LmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9kb19pbXBvcnQpCgogICAgICAgICMgVGFibGUKICAgICAgICBzZWxm"
    "Ll90YWJsZSA9IFFUYWJsZVdpZGdldCgwLCAzKQogICAgICAgIHNlbGYuX3RhYmxlLnNldEhvcml6"
    "b250YWxIZWFkZXJMYWJlbHMoWyJNb2R1bGUgTmFtZSIsICJTdGF0dXMiLCAiRGVzY3JpcHRpb24i"
    "XSkKICAgICAgICBoaCA9IHNlbGYuX3RhYmxlLmhvcml6b250YWxIZWFkZXIoKQogICAgICAgIGho"
    "LnNldFNlY3Rpb25SZXNpemVNb2RlKDAsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAg"
    "ICAgICAgc2VsZi5fdGFibGUuc2V0Q29sdW1uV2lkdGgoMCwgMTYwKQogICAgICAgIGhoLnNldFNl"
    "Y3Rpb25SZXNpemVNb2RlKDEsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuRml4ZWQpCiAgICAgICAg"
    "c2VsZi5fdGFibGUuc2V0Q29sdW1uV2lkdGgoMSwgMTAwKQogICAgICAgIGhoLnNldFNlY3Rpb25S"
    "ZXNpemVNb2RlKDIsIFFIZWFkZXJWaWV3LlJlc2l6ZU1vZGUuU3RyZXRjaCkKICAgICAgICBzZWxm"
    "Ll90YWJsZS5zZXRTZWxlY3Rpb25CZWhhdmlvcigKICAgICAgICAgICAgUUFic3RyYWN0SXRlbVZp"
    "ZXcuU2VsZWN0aW9uQmVoYXZpb3IuU2VsZWN0Um93cykKICAgICAgICBzZWxmLl90YWJsZS5zZXRB"
    "bHRlcm5hdGluZ1Jvd0NvbG9ycyhUcnVlKQogICAgICAgIHNlbGYuX3RhYmxlLnNldFN0eWxlU2hl"
    "ZXQoX2dvdGhpY190YWJsZV9zdHlsZSgpKQogICAgICAgIHNlbGYuX3RhYmxlLml0ZW1TZWxlY3Rp"
    "b25DaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fc2VsZWN0KQoKICAgICAgICAjIFNwbGl0dGVyCiAg"
    "ICAgICAgc3BsaXR0ZXIgPSBRU3BsaXR0ZXIoUXQuT3JpZW50YXRpb24uVmVydGljYWwpCiAgICAg"
    "ICAgc3BsaXR0ZXIuYWRkV2lkZ2V0KHNlbGYuX3RhYmxlKQoKICAgICAgICAjIE5vdGVzIHBhbmVs"
    "CiAgICAgICAgbm90ZXNfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgbm90ZXNfbGF5b3V0ID0g"
    "UVZCb3hMYXlvdXQobm90ZXNfd2lkZ2V0KQogICAgICAgIG5vdGVzX2xheW91dC5zZXRDb250ZW50"
    "c01hcmdpbnMoMCwgNCwgMCwgMCkKICAgICAgICBub3Rlc19sYXlvdXQuc2V0U3BhY2luZygyKQog"
    "ICAgICAgIG5vdGVzX2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJsKCLinacgTk9URVMiKSkK"
    "ICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAgICAgICBzZWxmLl9u"
    "b3Rlc19kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fbm90ZXNfZGlzcGxh"
    "eS5zZXRNaW5pbXVtSGVpZ2h0KDEyMCkKICAgICAgICBzZWxmLl9ub3Rlc19kaXNwbGF5LnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0dP"
    "TER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAg"
    "ICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTFw"
    "eDsgcGFkZGluZzogNHB4OyIKICAgICAgICApCiAgICAgICAgbm90ZXNfbGF5b3V0LmFkZFdpZGdl"
    "dChzZWxmLl9ub3Rlc19kaXNwbGF5KQogICAgICAgIHNwbGl0dGVyLmFkZFdpZGdldChub3Rlc193"
    "aWRnZXQpCiAgICAgICAgc3BsaXR0ZXIuc2V0U2l6ZXMoWzI1MCwgMTUwXSkKICAgICAgICByb290"
    "LmFkZFdpZGdldChzcGxpdHRlciwgMSkKCiAgICAgICAgIyBDb3VudCBsYWJlbAogICAgICAgIHNl"
    "bGYuX2NvdW50X2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLl9jb3VudF9sYmwuc2V0U3R5"
    "bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNpemU6IDlw"
    "eDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIHJv"
    "b3QuYWRkV2lkZ2V0KHNlbGYuX2NvdW50X2xibCkKCiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIHNlbGYuX3JlY29yZHMgPSByZWFkX2pzb25sKHNlbGYuX3BhdGgpCiAgICAg"
    "ICAgc2VsZi5fdGFibGUuc2V0Um93Q291bnQoMCkKICAgICAgICBmb3IgcmVjIGluIHNlbGYuX3Jl"
    "Y29yZHM6CiAgICAgICAgICAgIHIgPSBzZWxmLl90YWJsZS5yb3dDb3VudCgpCiAgICAgICAgICAg"
    "IHNlbGYuX3RhYmxlLmluc2VydFJvdyhyKQogICAgICAgICAgICBzZWxmLl90YWJsZS5zZXRJdGVt"
    "KHIsIDAsIFFUYWJsZVdpZGdldEl0ZW0ocmVjLmdldCgibmFtZSIsICIiKSkpCiAgICAgICAgICAg"
    "IHN0YXR1c19pdGVtID0gUVRhYmxlV2lkZ2V0SXRlbShyZWMuZ2V0KCJzdGF0dXMiLCAiSWRlYSIp"
    "KQogICAgICAgICAgICAjIENvbG9yIGJ5IHN0YXR1cwogICAgICAgICAgICBzdGF0dXNfY29sb3Jz"
    "ID0gewogICAgICAgICAgICAgICAgIklkZWEiOiAgICAgICAgICAgICBDX1RFWFRfRElNLAogICAg"
    "ICAgICAgICAgICAgIkRlc2lnbmluZyI6ICAgICAgICBDX0dPTERfRElNLAogICAgICAgICAgICAg"
    "ICAgIlJlYWR5IHRvIEJ1aWxkIjogICBDX1BVUlBMRSwKICAgICAgICAgICAgICAgICJQYXJ0aWFs"
    "IjogICAgICAgICAgIiNjYzg4NDQiLAogICAgICAgICAgICAgICAgIkJ1aWx0IjogICAgICAgICAg"
    "ICBDX0dSRUVOLAogICAgICAgICAgICB9CiAgICAgICAgICAgIHN0YXR1c19pdGVtLnNldEZvcmVn"
    "cm91bmQoCiAgICAgICAgICAgICAgICBRQ29sb3Ioc3RhdHVzX2NvbG9ycy5nZXQocmVjLmdldCgi"
    "c3RhdHVzIiwiSWRlYSIpLCBDX1RFWFRfRElNKSkKICAgICAgICAgICAgKQogICAgICAgICAgICBz"
    "ZWxmLl90YWJsZS5zZXRJdGVtKHIsIDEsIHN0YXR1c19pdGVtKQogICAgICAgICAgICBzZWxmLl90"
    "YWJsZS5zZXRJdGVtKHIsIDIsCiAgICAgICAgICAgICAgICBRVGFibGVXaWRnZXRJdGVtKHJlYy5n"
    "ZXQoImRlc2NyaXB0aW9uIiwgIiIpWzo4MF0pKQogICAgICAgIGNvdW50cyA9IHt9CiAgICAgICAg"
    "Zm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICBzID0gcmVjLmdldCgic3RhdHVz"
    "IiwgIklkZWEiKQogICAgICAgICAgICBjb3VudHNbc10gPSBjb3VudHMuZ2V0KHMsIDApICsgMQog"
    "ICAgICAgIGNvdW50X3N0ciA9ICIgICIuam9pbihmIntzfToge259IiBmb3IgcywgbiBpbiBjb3Vu"
    "dHMuaXRlbXMoKSkKICAgICAgICBzZWxmLl9jb3VudF9sYmwuc2V0VGV4dCgKICAgICAgICAgICAg"
    "ZiJUb3RhbDoge2xlbihzZWxmLl9yZWNvcmRzKX0gICB7Y291bnRfc3RyfSIKICAgICAgICApCgog"
    "ICAgZGVmIF9vbl9zZWxlY3Qoc2VsZikgLT4gTm9uZToKICAgICAgICByb3cgPSBzZWxmLl90YWJs"
    "ZS5jdXJyZW50Um93KCkKICAgICAgICBpZiAwIDw9IHJvdyA8IGxlbihzZWxmLl9yZWNvcmRzKToK"
    "ICAgICAgICAgICAgcmVjID0gc2VsZi5fcmVjb3Jkc1tyb3ddCiAgICAgICAgICAgIHNlbGYuX25v"
    "dGVzX2Rpc3BsYXkuc2V0UGxhaW5UZXh0KHJlYy5nZXQoIm5vdGVzIiwgIiIpKQoKICAgIGRlZiBf"
    "ZG9fYWRkKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fb3Blbl9lZGl0X2RpYWxvZygpCgog"
    "ICAgZGVmIF9kb19lZGl0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgcm93ID0gc2VsZi5fdGFibGUu"
    "Y3VycmVudFJvdygpCiAgICAgICAgaWYgMCA8PSByb3cgPCBsZW4oc2VsZi5fcmVjb3Jkcyk6CiAg"
    "ICAgICAgICAgIHNlbGYuX29wZW5fZWRpdF9kaWFsb2coc2VsZi5fcmVjb3Jkc1tyb3ddLCByb3cp"
    "CgogICAgZGVmIF9vcGVuX2VkaXRfZGlhbG9nKHNlbGYsIHJlYzogZGljdCA9IE5vbmUsIHJvdzog"
    "aW50ID0gLTEpIC0+IE5vbmU6CiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRs"
    "Zy5zZXRXaW5kb3dUaXRsZSgiTW9kdWxlIiBpZiBub3QgcmVjIGVsc2UgZiJFZGl0OiB7cmVjLmdl"
    "dCgnbmFtZScsJycpfSIpCiAgICAgICAgZGxnLnNldFN0eWxlU2hlZXQoZiJiYWNrZ3JvdW5kOiB7"
    "Q19CRzJ9OyBjb2xvcjoge0NfR09MRH07IikKICAgICAgICBkbGcucmVzaXplKDU0MCwgNDQwKQog"
    "ICAgICAgIGZvcm0gPSBRVkJveExheW91dChkbGcpCgogICAgICAgIG5hbWVfZmllbGQgPSBRTGlu"
    "ZUVkaXQocmVjLmdldCgibmFtZSIsIiIpIGlmIHJlYyBlbHNlICIiKQogICAgICAgIG5hbWVfZmll"
    "bGQuc2V0UGxhY2Vob2xkZXJUZXh0KCJNb2R1bGUgbmFtZSIpCgogICAgICAgIHN0YXR1c19jb21i"
    "byA9IFFDb21ib0JveCgpCiAgICAgICAgc3RhdHVzX2NvbWJvLmFkZEl0ZW1zKHNlbGYuU1RBVFVT"
    "RVMpCiAgICAgICAgaWYgcmVjOgogICAgICAgICAgICBpZHggPSBzdGF0dXNfY29tYm8uZmluZFRl"
    "eHQocmVjLmdldCgic3RhdHVzIiwiSWRlYSIpKQogICAgICAgICAgICBpZiBpZHggPj0gMDoKICAg"
    "ICAgICAgICAgICAgIHN0YXR1c19jb21iby5zZXRDdXJyZW50SW5kZXgoaWR4KQoKICAgICAgICBk"
    "ZXNjX2ZpZWxkID0gUUxpbmVFZGl0KHJlYy5nZXQoImRlc2NyaXB0aW9uIiwiIikgaWYgcmVjIGVs"
    "c2UgIiIpCiAgICAgICAgZGVzY19maWVsZC5zZXRQbGFjZWhvbGRlclRleHQoIk9uZS1saW5lIGRl"
    "c2NyaXB0aW9uIikKCiAgICAgICAgbm90ZXNfZmllbGQgPSBRVGV4dEVkaXQoKQogICAgICAgIG5v"
    "dGVzX2ZpZWxkLnNldFBsYWluVGV4dChyZWMuZ2V0KCJub3RlcyIsIiIpIGlmIHJlYyBlbHNlICIi"
    "KQogICAgICAgIG5vdGVzX2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgKICAgICAgICAgICAgIkZ1"
    "bGwgbm90ZXMg4oCUIHNwZWMsIGlkZWFzLCByZXF1aXJlbWVudHMsIGVkZ2UgY2FzZXMuLi4iCiAg"
    "ICAgICAgKQogICAgICAgIG5vdGVzX2ZpZWxkLnNldE1pbmltdW1IZWlnaHQoMjAwKQoKICAgICAg"
    "ICBmb3IgbGFiZWwsIHdpZGdldCBpbiBbCiAgICAgICAgICAgICgiTmFtZToiLCBuYW1lX2ZpZWxk"
    "KSwKICAgICAgICAgICAgKCJTdGF0dXM6Iiwgc3RhdHVzX2NvbWJvKSwKICAgICAgICAgICAgKCJE"
    "ZXNjcmlwdGlvbjoiLCBkZXNjX2ZpZWxkKSwKICAgICAgICAgICAgKCJOb3RlczoiLCBub3Rlc19m"
    "aWVsZCksCiAgICAgICAgXToKICAgICAgICAgICAgcm93X2xheW91dCA9IFFIQm94TGF5b3V0KCkK"
    "ICAgICAgICAgICAgbGJsID0gUUxhYmVsKGxhYmVsKQogICAgICAgICAgICBsYmwuc2V0Rml4ZWRX"
    "aWR0aCg5MCkKICAgICAgICAgICAgcm93X2xheW91dC5hZGRXaWRnZXQobGJsKQogICAgICAgICAg"
    "ICByb3dfbGF5b3V0LmFkZFdpZGdldCh3aWRnZXQpCiAgICAgICAgICAgIGZvcm0uYWRkTGF5b3V0"
    "KHJvd19sYXlvdXQpCgogICAgICAgIGJ0bl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRu"
    "X3NhdmUgICA9IF9nb3RoaWNfYnRuKCJTYXZlIikKICAgICAgICBidG5fY2FuY2VsID0gX2dvdGhp"
    "Y19idG4oIkNhbmNlbCIpCiAgICAgICAgYnRuX3NhdmUuY2xpY2tlZC5jb25uZWN0KGRsZy5hY2Nl"
    "cHQpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAg"
    "ICBidG5fcm93LmFkZFdpZGdldChidG5fc2F2ZSkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChi"
    "dG5fY2FuY2VsKQogICAgICAgIGZvcm0uYWRkTGF5b3V0KGJ0bl9yb3cpCgogICAgICAgIGlmIGRs"
    "Zy5leGVjKCkgPT0gUURpYWxvZy5EaWFsb2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICBuZXdf"
    "cmVjID0gewogICAgICAgICAgICAgICAgImlkIjogICAgICAgICAgcmVjLmdldCgiaWQiLCBzdHIo"
    "dXVpZC51dWlkNCgpKSkgaWYgcmVjIGVsc2Ugc3RyKHV1aWQudXVpZDQoKSksCiAgICAgICAgICAg"
    "ICAgICAibmFtZSI6ICAgICAgICBuYW1lX2ZpZWxkLnRleHQoKS5zdHJpcCgpLAogICAgICAgICAg"
    "ICAgICAgInN0YXR1cyI6ICAgICAgc3RhdHVzX2NvbWJvLmN1cnJlbnRUZXh0KCksCiAgICAgICAg"
    "ICAgICAgICAiZGVzY3JpcHRpb24iOiBkZXNjX2ZpZWxkLnRleHQoKS5zdHJpcCgpLAogICAgICAg"
    "ICAgICAgICAgIm5vdGVzIjogICAgICAgbm90ZXNfZmllbGQudG9QbGFpblRleHQoKS5zdHJpcCgp"
    "LAogICAgICAgICAgICAgICAgImNyZWF0ZWQiOiAgICAgcmVjLmdldCgiY3JlYXRlZCIsIGRhdGV0"
    "aW1lLm5vdygpLmlzb2Zvcm1hdCgpKSBpZiByZWMgZWxzZSBkYXRldGltZS5ub3coKS5pc29mb3Jt"
    "YXQoKSwKICAgICAgICAgICAgICAgICJtb2RpZmllZCI6ICAgIGRhdGV0aW1lLm5vdygpLmlzb2Zv"
    "cm1hdCgpLAogICAgICAgICAgICB9CiAgICAgICAgICAgIGlmIHJvdyA+PSAwOgogICAgICAgICAg"
    "ICAgICAgc2VsZi5fcmVjb3Jkc1tyb3ddID0gbmV3X3JlYwogICAgICAgICAgICBlbHNlOgogICAg"
    "ICAgICAgICAgICAgc2VsZi5fcmVjb3Jkcy5hcHBlbmQobmV3X3JlYykKICAgICAgICAgICAgd3Jp"
    "dGVfanNvbmwoc2VsZi5fcGF0aCwgc2VsZi5fcmVjb3JkcykKICAgICAgICAgICAgc2VsZi5yZWZy"
    "ZXNoKCkKCiAgICBkZWYgX2RvX2RlbGV0ZShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvdyA9IHNl"
    "bGYuX3RhYmxlLmN1cnJlbnRSb3coKQogICAgICAgIGlmIDAgPD0gcm93IDwgbGVuKHNlbGYuX3Jl"
    "Y29yZHMpOgogICAgICAgICAgICBuYW1lID0gc2VsZi5fcmVjb3Jkc1tyb3ddLmdldCgibmFtZSIs"
    "InRoaXMgbW9kdWxlIikKICAgICAgICAgICAgcmVwbHkgPSBRTWVzc2FnZUJveC5xdWVzdGlvbigK"
    "ICAgICAgICAgICAgICAgIHNlbGYsICJEZWxldGUgTW9kdWxlIiwKICAgICAgICAgICAgICAgIGYi"
    "RGVsZXRlICd7bmFtZX0nPyBDYW5ub3QgYmUgdW5kb25lLiIsCiAgICAgICAgICAgICAgICBRTWVz"
    "c2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5ZZXMgfCBRTWVzc2FnZUJveC5TdGFuZGFyZEJ1dHRvbi5O"
    "bwogICAgICAgICAgICApCiAgICAgICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5k"
    "YXJkQnV0dG9uLlllczoKICAgICAgICAgICAgICAgIHNlbGYuX3JlY29yZHMucG9wKHJvdykKICAg"
    "ICAgICAgICAgICAgIHdyaXRlX2pzb25sKHNlbGYuX3BhdGgsIHNlbGYuX3JlY29yZHMpCiAgICAg"
    "ICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfZG9fZXhwb3J0KHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgdHJ5OgogICAgICAgICAgICBleHBvcnRfZGlyID0gY2ZnX3BhdGgoImV4cG9y"
    "dHMiKQogICAgICAgICAgICBleHBvcnRfZGlyLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9"
    "VHJ1ZSkKICAgICAgICAgICAgdHMgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJVklbSVkXyVI"
    "JU0lUyIpCiAgICAgICAgICAgIG91dF9wYXRoID0gZXhwb3J0X2RpciAvIGYibW9kdWxlc197dHN9"
    "LnR4dCIKICAgICAgICAgICAgbGluZXMgPSBbCiAgICAgICAgICAgICAgICAiRUNITyBERUNLIOKA"
    "lCBNT0RVTEUgVFJBQ0tFUiBFWFBPUlQiLAogICAgICAgICAgICAgICAgZiJFeHBvcnRlZDoge2Rh"
    "dGV0aW1lLm5vdygpLnN0cmZ0aW1lKCclWS0lbS0lZCAlSDolTTolUycpfSIsCiAgICAgICAgICAg"
    "ICAgICBmIlRvdGFsIG1vZHVsZXM6IHtsZW4oc2VsZi5fcmVjb3Jkcyl9IiwKICAgICAgICAgICAg"
    "ICAgICI9IiAqIDYwLAogICAgICAgICAgICAgICAgIiIsCiAgICAgICAgICAgIF0KICAgICAgICAg"
    "ICAgZm9yIHJlYyBpbiBzZWxmLl9yZWNvcmRzOgogICAgICAgICAgICAgICAgbGluZXMuZXh0ZW5k"
    "KFsKICAgICAgICAgICAgICAgICAgICBmIk1PRFVMRToge3JlYy5nZXQoJ25hbWUnLCcnKX0iLAog"
    "ICAgICAgICAgICAgICAgICAgIGYiU3RhdHVzOiB7cmVjLmdldCgnc3RhdHVzJywnJyl9IiwKICAg"
    "ICAgICAgICAgICAgICAgICBmIkRlc2NyaXB0aW9uOiB7cmVjLmdldCgnZGVzY3JpcHRpb24nLCcn"
    "KX0iLAogICAgICAgICAgICAgICAgICAgICIiLAogICAgICAgICAgICAgICAgICAgICJOb3Rlczoi"
    "LAogICAgICAgICAgICAgICAgICAgIHJlYy5nZXQoIm5vdGVzIiwiIiksCiAgICAgICAgICAgICAg"
    "ICAgICAgIiIsCiAgICAgICAgICAgICAgICAgICAgIi0iICogNDAsCiAgICAgICAgICAgICAgICAg"
    "ICAgIiIsCiAgICAgICAgICAgICAgICBdKQogICAgICAgICAgICBvdXRfcGF0aC53cml0ZV90ZXh0"
    "KCJcbiIuam9pbihsaW5lcyksIGVuY29kaW5nPSJ1dGYtOCIpCiAgICAgICAgICAgIFFBcHBsaWNh"
    "dGlvbi5jbGlwYm9hcmQoKS5zZXRUZXh0KCJcbiIuam9pbihsaW5lcykpCiAgICAgICAgICAgIFFN"
    "ZXNzYWdlQm94LmluZm9ybWF0aW9uKAogICAgICAgICAgICAgICAgc2VsZiwgIkV4cG9ydGVkIiwK"
    "ICAgICAgICAgICAgICAgIGYiTW9kdWxlIHRyYWNrZXIgZXhwb3J0ZWQgdG86XG57b3V0X3BhdGh9"
    "XG5cbkFsc28gY29waWVkIHRvIGNsaXBib2FyZC4iCiAgICAgICAgICAgICkKICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIFFNZXNzYWdlQm94Lndhcm5pbmcoc2VsZiwg"
    "IkV4cG9ydCBFcnJvciIsIHN0cihlKSkKCiAgICBkZWYgX2RvX2ltcG9ydChzZWxmKSAtPiBOb25l"
    "OgogICAgICAgICIiIkltcG9ydCBhIG1vZHVsZSBzcGVjIGZyb20gY2xpcGJvYXJkIG9yIHR5cGVk"
    "IHRleHQuIiIiCiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRsZy5zZXRXaW5k"
    "b3dUaXRsZSgiSW1wb3J0IE1vZHVsZSBTcGVjIikKICAgICAgICBkbGcuc2V0U3R5bGVTaGVldChm"
    "ImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19HT0xEfTsiKQogICAgICAgIGRsZy5yZXNp"
    "emUoNTAwLCAzNDApCiAgICAgICAgbGF5b3V0ID0gUVZCb3hMYXlvdXQoZGxnKQogICAgICAgIGxh"
    "eW91dC5hZGRXaWRnZXQoUUxhYmVsKAogICAgICAgICAgICAiUGFzdGUgYSBtb2R1bGUgc3BlYyBi"
    "ZWxvdy5cbiIKICAgICAgICAgICAgIkZpcnN0IGxpbmUgd2lsbCBiZSB1c2VkIGFzIHRoZSBtb2R1"
    "bGUgbmFtZS4iCiAgICAgICAgKSkKICAgICAgICB0ZXh0X2ZpZWxkID0gUVRleHRFZGl0KCkKICAg"
    "ICAgICB0ZXh0X2ZpZWxkLnNldFBsYWNlaG9sZGVyVGV4dCgiUGFzdGUgbW9kdWxlIHNwZWMgaGVy"
    "ZS4uLiIpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldCh0ZXh0X2ZpZWxkLCAxKQogICAgICAgIGJ0"
    "bl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX29rICAgICA9IF9nb3RoaWNfYnRuKCJJ"
    "bXBvcnQiKQogICAgICAgIGJ0bl9jYW5jZWwgPSBfZ290aGljX2J0bigiQ2FuY2VsIikKICAgICAg"
    "ICBidG5fb2suY2xpY2tlZC5jb25uZWN0KGRsZy5hY2NlcHQpCiAgICAgICAgYnRuX2NhbmNlbC5j"
    "bGlja2VkLmNvbm5lY3QoZGxnLnJlamVjdCkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5f"
    "b2spCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAgICAgICBsYXlvdXQu"
    "YWRkTGF5b3V0KGJ0bl9yb3cpCgogICAgICAgIGlmIGRsZy5leGVjKCkgPT0gUURpYWxvZy5EaWFs"
    "b2dDb2RlLkFjY2VwdGVkOgogICAgICAgICAgICByYXcgPSB0ZXh0X2ZpZWxkLnRvUGxhaW5UZXh0"
    "KCkuc3RyaXAoKQogICAgICAgICAgICBpZiBub3QgcmF3OgogICAgICAgICAgICAgICAgcmV0dXJu"
    "CiAgICAgICAgICAgIGxpbmVzID0gcmF3LnNwbGl0bGluZXMoKQogICAgICAgICAgICAjIEZpcnN0"
    "IG5vbi1lbXB0eSBsaW5lID0gbmFtZQogICAgICAgICAgICBuYW1lID0gIiIKICAgICAgICAgICAg"
    "Zm9yIGxpbmUgaW4gbGluZXM6CiAgICAgICAgICAgICAgICBpZiBsaW5lLnN0cmlwKCk6CiAgICAg"
    "ICAgICAgICAgICAgICAgbmFtZSA9IGxpbmUuc3RyaXAoKQogICAgICAgICAgICAgICAgICAgIGJy"
    "ZWFrCiAgICAgICAgICAgIG5ld19yZWMgPSB7CiAgICAgICAgICAgICAgICAiaWQiOiAgICAgICAg"
    "ICBzdHIodXVpZC51dWlkNCgpKSwKICAgICAgICAgICAgICAgICJuYW1lIjogICAgICAgIG5hbWVb"
    "OjYwXSwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAgICAgICJJZGVhIiwKICAgICAgICAgICAg"
    "ICAgICJkZXNjcmlwdGlvbiI6ICIiLAogICAgICAgICAgICAgICAgIm5vdGVzIjogICAgICAgcmF3"
    "LAogICAgICAgICAgICAgICAgImNyZWF0ZWQiOiAgICAgZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0"
    "KCksCiAgICAgICAgICAgICAgICAibW9kaWZpZWQiOiAgICBkYXRldGltZS5ub3coKS5pc29mb3Jt"
    "YXQoKSwKICAgICAgICAgICAgfQogICAgICAgICAgICBzZWxmLl9yZWNvcmRzLmFwcGVuZChuZXdf"
    "cmVjKQogICAgICAgICAgICB3cml0ZV9qc29ubChzZWxmLl9wYXRoLCBzZWxmLl9yZWNvcmRzKQog"
    "ICAgICAgICAgICBzZWxmLnJlZnJlc2goKQoKCiMg4pSA4pSAIFBBU1MgNSBDT01QTEVURSDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKIyBBbGwgdGFiIGNvbnRlbnQgY2xhc3NlcyBkZWZpbmVkLgojIFNMU2NhbnNUYWI6IHJl"
    "YnVpbHQg4oCUIERlbGV0ZSBhZGRlZCwgTW9kaWZ5IGZpeGVkLCB0aW1lc3RhbXAgcGFyc2VyIGZp"
    "eGVkLAojICAgICAgICAgICAgIGNhcmQvZ3JpbW9pcmUgc3R5bGUsIGNvcHktdG8tY2xpcGJvYXJk"
    "IGNvbnRleHQgbWVudS4KIyBTTENvbW1hbmRzVGFiOiBnb3RoaWMgdGFibGUsIOKniSBDb3B5IENv"
    "bW1hbmQgYnV0dG9uLgojIEpvYlRyYWNrZXJUYWI6IGZ1bGwgcmVidWlsZCDigJQgbXVsdGktc2Vs"
    "ZWN0LCBhcmNoaXZlL3Jlc3RvcmUsIENTVi9UU1YgZXhwb3J0LgojIFNlbGZUYWI6IGlubmVyIHNh"
    "bmN0dW0gZm9yIGlkbGUgbmFycmF0aXZlIGFuZCByZWZsZWN0aW9uIG91dHB1dC4KIyBEaWFnbm9z"
    "dGljc1RhYjogc3RydWN0dXJlZCBsb2cgd2l0aCBsZXZlbC1jb2xvcmVkIG91dHB1dC4KIyBMZXNz"
    "b25zVGFiOiBMU0wgRm9yYmlkZGVuIFJ1bGVzZXQgYnJvd3NlciB3aXRoIGFkZC9kZWxldGUvc2Vh"
    "cmNoLgojCiMgTmV4dDogUGFzcyA2IOKAlCBNYWluIFdpbmRvdwojIChNb3JnYW5uYURlY2sgY2xh"
    "c3MsIGZ1bGwgbGF5b3V0LCBBUFNjaGVkdWxlciwgZmlyc3QtcnVuIGZsb3csCiMgIGRlcGVuZGVu"
    "Y3kgYm9vdHN0cmFwLCBzaG9ydGN1dCBjcmVhdGlvbiwgc3RhcnR1cCBzZXF1ZW5jZSkKCgojIOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkAojIE1PUkdBTk5BIERFQ0sg4oCUIFBBU1MgNjogTUFJTiBXSU5ET1cgJiBFTlRSWSBQ"
    "T0lOVAojCiMgQ29udGFpbnM6CiMgICBib290c3RyYXBfY2hlY2soKSAgICAg4oCUIGRlcGVuZGVu"
    "Y3kgdmFsaWRhdGlvbiArIGF1dG8taW5zdGFsbCBiZWZvcmUgVUkKIyAgIEZpcnN0UnVuRGlhbG9n"
    "ICAgICAgICDigJQgbW9kZWwgcGF0aCArIGNvbm5lY3Rpb24gdHlwZSBzZWxlY3Rpb24KIyAgIEpv"
    "dXJuYWxTaWRlYmFyICAgICAgICDigJQgY29sbGFwc2libGUgbGVmdCBzaWRlYmFyIChzZXNzaW9u"
    "IGJyb3dzZXIgKyBqb3VybmFsKQojICAgVG9ycG9yUGFuZWwgICAgICAgICAgIOKAlCBBV0FLRSAv"
    "IEFVVE8gLyBDT0ZGSU4gc3RhdGUgdG9nZ2xlCiMgICBNb3JnYW5uYURlY2sgICAgICAgICAg4oCU"
    "IG1haW4gd2luZG93LCBmdWxsIGxheW91dCwgYWxsIHNpZ25hbCBjb25uZWN0aW9ucwojICAgbWFp"
    "bigpICAgICAgICAgICAgICAgIOKAlCBlbnRyeSBwb2ludCB3aXRoIGJvb3RzdHJhcCBzZXF1ZW5j"
    "ZQojIOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKVkOKV"
    "kOKVkOKVkOKVkOKVkAoKaW1wb3J0IHN1YnByb2Nlc3MKCgojIOKUgOKUgCBQUkUtTEFVTkNIIERF"
    "UEVOREVOQ1kgQk9PVFNUUkFQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgYm9vdHN0cmFwX2NoZWNrKCkgLT4g"
    "Tm9uZToKICAgICIiIgogICAgUnVucyBCRUZPUkUgUUFwcGxpY2F0aW9uIGlzIGNyZWF0ZWQuCiAg"
    "ICBDaGVja3MgZm9yIFB5U2lkZTYgc2VwYXJhdGVseSAoY2FuJ3Qgc2hvdyBHVUkgd2l0aG91dCBp"
    "dCkuCiAgICBBdXRvLWluc3RhbGxzIGFsbCBvdGhlciBtaXNzaW5nIG5vbi1jcml0aWNhbCBkZXBz"
    "IHZpYSBwaXAuCiAgICBWYWxpZGF0ZXMgaW5zdGFsbHMgc3VjY2VlZGVkLgogICAgV3JpdGVzIHJl"
    "c3VsdHMgdG8gYSBib290c3RyYXAgbG9nIGZvciBEaWFnbm9zdGljcyB0YWIgdG8gcGljayB1cC4K"
    "ICAgICIiIgogICAgIyDilIDilIAgU3RlcCAxOiBDaGVjayBQeVNpZGU2IChjYW4ndCBhdXRvLWlu"
    "c3RhbGwgd2l0aG91dCBpdCBhbHJlYWR5IHByZXNlbnQpIOKUgAogICAgdHJ5OgogICAgICAgIGlt"
    "cG9ydCBQeVNpZGU2ICAjIG5vcWEKICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAjIE5v"
    "IEdVSSBhdmFpbGFibGUg4oCUIHVzZSBXaW5kb3dzIG5hdGl2ZSBkaWFsb2cgdmlhIGN0eXBlcwog"
    "ICAgICAgIHRyeToKICAgICAgICAgICAgaW1wb3J0IGN0eXBlcwogICAgICAgICAgICBjdHlwZXMu"
    "d2luZGxsLnVzZXIzMi5NZXNzYWdlQm94VygKICAgICAgICAgICAgICAgIDAsCiAgICAgICAgICAg"
    "ICAgICAiUHlTaWRlNiBpcyByZXF1aXJlZCBidXQgbm90IGluc3RhbGxlZC5cblxuIgogICAgICAg"
    "ICAgICAgICAgIk9wZW4gYSB0ZXJtaW5hbCBhbmQgcnVuOlxuXG4iCiAgICAgICAgICAgICAgICAi"
    "ICAgIHBpcCBpbnN0YWxsIFB5U2lkZTZcblxuIgogICAgICAgICAgICAgICAgZiJUaGVuIHJlc3Rh"
    "cnQge0RFQ0tfTkFNRX0uIiwKICAgICAgICAgICAgICAgIGYie0RFQ0tfTkFNRX0g4oCUIE1pc3Np"
    "bmcgRGVwZW5kZW5jeSIsCiAgICAgICAgICAgICAgICAweDEwICAjIE1CX0lDT05FUlJPUgogICAg"
    "ICAgICAgICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcHJpbnQoIkNS"
    "SVRJQ0FMOiBQeVNpZGU2IG5vdCBpbnN0YWxsZWQuIFJ1bjogcGlwIGluc3RhbGwgUHlTaWRlNiIp"
    "CiAgICAgICAgc3lzLmV4aXQoMSkKCiAgICAjIOKUgOKUgCBTdGVwIDI6IEF1dG8taW5zdGFsbCBv"
    "dGhlciBtaXNzaW5nIGRlcHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICBfQVVUT19JTlNUQUxMID0gWwogICAgICAgICgiYXBzY2hlZHVsZXIiLCAgICAgICAgICAg"
    "ICAgICJhcHNjaGVkdWxlciIpLAogICAgICAgICgibG9ndXJ1IiwgICAgICAgICAgICAgICAgICAg"
    "ICJsb2d1cnUiKSwKICAgICAgICAoInB5Z2FtZSIsICAgICAgICAgICAgICAgICAgICAicHlnYW1l"
    "IiksCiAgICAgICAgKCJweXdpbjMyIiwgICAgICAgICAgICAgICAgICAgInB5d2luMzIiKSwKICAg"
    "ICAgICAoInBzdXRpbCIsICAgICAgICAgICAgICAgICAgICAicHN1dGlsIiksCiAgICAgICAgKCJy"
    "ZXF1ZXN0cyIsICAgICAgICAgICAgICAgICAgInJlcXVlc3RzIiksCiAgICAgICAgKCJnb29nbGUt"
    "YXBpLXB5dGhvbi1jbGllbnQiLCAgImdvb2dsZWFwaWNsaWVudCIpLAogICAgICAgICgiZ29vZ2xl"
    "LWF1dGgtb2F1dGhsaWIiLCAgICAgICJnb29nbGVfYXV0aF9vYXV0aGxpYiIpLAogICAgICAgICgi"
    "Z29vZ2xlLWF1dGgiLCAgICAgICAgICAgICAgICJnb29nbGUuYXV0aCIpLAogICAgXQoKICAgIGlt"
    "cG9ydCBpbXBvcnRsaWIKICAgIGJvb3RzdHJhcF9sb2cgPSBbXQoKICAgIGZvciBwaXBfbmFtZSwg"
    "aW1wb3J0X25hbWUgaW4gX0FVVE9fSU5TVEFMTDoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGlt"
    "cG9ydGxpYi5pbXBvcnRfbW9kdWxlKGltcG9ydF9uYW1lKQogICAgICAgICAgICBib290c3RyYXBf"
    "bG9nLmFwcGVuZChmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0g4pyTIikKICAgICAgICBleGNlcHQg"
    "SW1wb3J0RXJyb3I6CiAgICAgICAgICAgIGJvb3RzdHJhcF9sb2cuYXBwZW5kKAogICAgICAgICAg"
    "ICAgICAgZiJbQk9PVFNUUkFQXSB7cGlwX25hbWV9IG1pc3Npbmcg4oCUIGluc3RhbGxpbmcuLi4i"
    "CiAgICAgICAgICAgICkKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgcmVzdWx0ID0g"
    "c3VicHJvY2Vzcy5ydW4oCiAgICAgICAgICAgICAgICAgICAgW3N5cy5leGVjdXRhYmxlLCAiLW0i"
    "LCAicGlwIiwgImluc3RhbGwiLAogICAgICAgICAgICAgICAgICAgICBwaXBfbmFtZSwgIi0tcXVp"
    "ZXQiLCAiLS1uby13YXJuLXNjcmlwdC1sb2NhdGlvbiJdLAogICAgICAgICAgICAgICAgICAgIGNh"
    "cHR1cmVfb3V0cHV0PVRydWUsIHRleHQ9VHJ1ZSwgdGltZW91dD0xMjAKICAgICAgICAgICAgICAg"
    "ICkKICAgICAgICAgICAgICAgIGlmIHJlc3VsdC5yZXR1cm5jb2RlID09IDA6CiAgICAgICAgICAg"
    "ICAgICAgICAgIyBWYWxpZGF0ZSBpdCBhY3R1YWxseSBpbXBvcnRlZCBub3cKICAgICAgICAgICAg"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIGltcG9ydGxpYi5pbXBvcnRfbW9k"
    "dWxlKGltcG9ydF9uYW1lKQogICAgICAgICAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFw"
    "cGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0ge3BpcF9uYW1l"
    "fSBpbnN0YWxsZWQg4pyTIgogICAgICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAg"
    "ICAgICAgZXhjZXB0IEltcG9ydEVycm9yOgogICAgICAgICAgICAgICAgICAgICAgICBib290c3Ry"
    "YXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiW0JPT1RTVFJBUF0g"
    "e3BpcF9uYW1lfSBpbnN0YWxsIGFwcGVhcmVkIHRvICIKICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGYic3VjY2VlZCBidXQgaW1wb3J0IHN0aWxsIGZhaWxzIOKAlCByZXN0YXJ0IG1heSAiCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICBmImJlIHJlcXVpcmVkLiIKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgKQogICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBib290"
    "c3RyYXBfbG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICAgICAgZiJbQk9PVFNUUkFQXSB7"
    "cGlwX25hbWV9IGluc3RhbGwgZmFpbGVkOiAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYie3Jl"
    "c3VsdC5zdGRlcnJbOjIwMF19IgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgZXhj"
    "ZXB0IHN1YnByb2Nlc3MuVGltZW91dEV4cGlyZWQ6CiAgICAgICAgICAgICAgICBib290c3RyYXBf"
    "bG9nLmFwcGVuZCgKICAgICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0g"
    "aW5zdGFsbCB0aW1lZCBvdXQuIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNlcHQg"
    "RXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBib290c3RyYXBfbG9nLmFwcGVuZCgKICAg"
    "ICAgICAgICAgICAgICAgICBmIltCT09UU1RSQVBdIHtwaXBfbmFtZX0gaW5zdGFsbCBlcnJvcjog"
    "e2V9IgogICAgICAgICAgICAgICAgKQoKICAgICMg4pSA4pSAIFN0ZXAgMzogV3JpdGUgYm9vdHN0"
    "cmFwIGxvZyBmb3IgRGlhZ25vc3RpY3MgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgdHJ5OgogICAgICAg"
    "IGxvZ19wYXRoID0gU0NSSVBUX0RJUiAvICJsb2dzIiAvICJib290c3RyYXBfbG9nLnR4dCIKICAg"
    "ICAgICB3aXRoIGxvZ19wYXRoLm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAg"
    "ICAgICAgICBmLndyaXRlKCJcbiIuam9pbihib290c3RyYXBfbG9nKSkKICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgcGFzcwoKCiMg4pSA4pSAIEZJUlNUIFJVTiBESUFMT0cg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNz"
    "IEZpcnN0UnVuRGlhbG9nKFFEaWFsb2cpOgogICAgIiIiCiAgICBTaG93biBvbiBmaXJzdCBsYXVu"
    "Y2ggd2hlbiBjb25maWcuanNvbiBkb2Vzbid0IGV4aXN0LgogICAgQ29sbGVjdHMgbW9kZWwgY29u"
    "bmVjdGlvbiB0eXBlIGFuZCBwYXRoL2tleS4KICAgIFZhbGlkYXRlcyBjb25uZWN0aW9uIGJlZm9y"
    "ZSBhY2NlcHRpbmcuCiAgICBXcml0ZXMgY29uZmlnLmpzb24gb24gc3VjY2Vzcy4KICAgIENyZWF0"
    "ZXMgZGVza3RvcCBzaG9ydGN1dC4KICAgICIiIgoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBwYXJl"
    "bnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5z"
    "ZXRXaW5kb3dUaXRsZShmIuKcpiB7REVDS19OQU1FLnVwcGVyKCl9IOKAlCBGSVJTVCBBV0FLRU5J"
    "TkciKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldChTVFlMRSkKICAgICAgICBzZWxmLnNldEZp"
    "eGVkU2l6ZSg1MjAsIDQwMCkKICAgICAgICBzZWxmLl9zZXR1cF91aSgpCgogICAgZGVmIF9zZXR1"
    "cF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIHJvb3QgPSBRVkJveExheW91dChzZWxmKQogICAg"
    "ICAgIHJvb3Quc2V0U3BhY2luZygxMCkKCiAgICAgICAgdGl0bGUgPSBRTGFiZWwoZiLinKYge0RF"
    "Q0tfTkFNRS51cHBlcigpfSDigJQgRklSU1QgQVdBS0VOSU5HIOKcpiIpCiAgICAgICAgdGl0bGUu"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfQ1JJTVNPTn07IGZvbnQtc2l6"
    "ZTogMTRweDsgZm9udC13ZWlnaHQ6IGJvbGQ7ICIKICAgICAgICAgICAgZiJmb250LWZhbWlseTog"
    "e0RFQ0tfRk9OVH0sIHNlcmlmOyBsZXR0ZXItc3BhY2luZzogMnB4OyIKICAgICAgICApCiAgICAg"
    "ICAgdGl0bGUuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAg"
    "ICAgcm9vdC5hZGRXaWRnZXQodGl0bGUpCgogICAgICAgIHN1YiA9IFFMYWJlbCgKICAgICAgICAg"
    "ICAgZiJDb25maWd1cmUgdGhlIHZlc3NlbCBiZWZvcmUge0RFQ0tfTkFNRX0gbWF5IGF3YWtlbi5c"
    "biIKICAgICAgICAgICAgIkFsbCBzZXR0aW5ncyBhcmUgc3RvcmVkIGxvY2FsbHkuIE5vdGhpbmcg"
    "bGVhdmVzIHRoaXMgbWFjaGluZS4iCiAgICAgICAgKQogICAgICAgIHN1Yi5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgIgog"
    "ICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkK"
    "ICAgICAgICBzdWIuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAg"
    "ICAgICAgcm9vdC5hZGRXaWRnZXQoc3ViKQoKICAgICAgICAjIOKUgOKUgCBDb25uZWN0aW9uIHR5"
    "cGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJs"
    "KCLinacgQUkgQ09OTkVDVElPTiBUWVBFIikpCiAgICAgICAgc2VsZi5fdHlwZV9jb21ibyA9IFFD"
    "b21ib0JveCgpCiAgICAgICAgc2VsZi5fdHlwZV9jb21iby5hZGRJdGVtcyhbCiAgICAgICAgICAg"
    "ICJMb2NhbCBtb2RlbCBmb2xkZXIgKHRyYW5zZm9ybWVycykiLAogICAgICAgICAgICAiT2xsYW1h"
    "IChsb2NhbCBzZXJ2aWNlKSIsCiAgICAgICAgICAgICJDbGF1ZGUgQVBJIChBbnRocm9waWMpIiwK"
    "ICAgICAgICAgICAgIk9wZW5BSSBBUEkiLAogICAgICAgIF0pCiAgICAgICAgc2VsZi5fdHlwZV9j"
    "b21iby5jdXJyZW50SW5kZXhDaGFuZ2VkLmNvbm5lY3Qoc2VsZi5fb25fdHlwZV9jaGFuZ2UpCiAg"
    "ICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdHlwZV9jb21ibykKCiAgICAgICAgIyDilIDilIAg"
    "RHluYW1pYyBjb25uZWN0aW9uIGZpZWxkcyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zdGFjayA9IFFTdGFja2VkV2lkZ2V0KCkKCiAg"
    "ICAgICAgIyBQYWdlIDA6IExvY2FsIHBhdGgKICAgICAgICBwMCA9IFFXaWRnZXQoKQogICAgICAg"
    "IGwwID0gUUhCb3hMYXlvdXQocDApCiAgICAgICAgbDAuc2V0Q29udGVudHNNYXJnaW5zKDAsMCww"
    "LDApCiAgICAgICAgc2VsZi5fbG9jYWxfcGF0aCA9IFFMaW5lRWRpdCgpCiAgICAgICAgc2VsZi5f"
    "bG9jYWxfcGF0aC5zZXRQbGFjZWhvbGRlclRleHQoCiAgICAgICAgICAgIHIiRDpcQUlcTW9kZWxz"
    "XGRvbHBoaW4tOGIiCiAgICAgICAgKQogICAgICAgIGJ0bl9icm93c2UgPSBfZ290aGljX2J0bigi"
    "QnJvd3NlIikKICAgICAgICBidG5fYnJvd3NlLmNsaWNrZWQuY29ubmVjdChzZWxmLl9icm93c2Vf"
    "bW9kZWwpCiAgICAgICAgbDAuYWRkV2lkZ2V0KHNlbGYuX2xvY2FsX3BhdGgpOyBsMC5hZGRXaWRn"
    "ZXQoYnRuX2Jyb3dzZSkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDApCgogICAgICAg"
    "ICMgUGFnZSAxOiBPbGxhbWEgbW9kZWwgbmFtZQogICAgICAgIHAxID0gUVdpZGdldCgpCiAgICAg"
    "ICAgbDEgPSBRSEJveExheW91dChwMSkKICAgICAgICBsMS5zZXRDb250ZW50c01hcmdpbnMoMCww"
    "LDAsMCkKICAgICAgICBzZWxmLl9vbGxhbWFfbW9kZWwgPSBRTGluZUVkaXQoKQogICAgICAgIHNl"
    "bGYuX29sbGFtYV9tb2RlbC5zZXRQbGFjZWhvbGRlclRleHQoImRvbHBoaW4tMi42LTdiIikKICAg"
    "ICAgICBsMS5hZGRXaWRnZXQoc2VsZi5fb2xsYW1hX21vZGVsKQogICAgICAgIHNlbGYuX3N0YWNr"
    "LmFkZFdpZGdldChwMSkKCiAgICAgICAgIyBQYWdlIDI6IENsYXVkZSBBUEkga2V5CiAgICAgICAg"
    "cDIgPSBRV2lkZ2V0KCkKICAgICAgICBsMiA9IFFWQm94TGF5b3V0KHAyKQogICAgICAgIGwyLnNl"
    "dENvbnRlbnRzTWFyZ2lucygwLDAsMCwwKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkgICA9IFFM"
    "aW5lRWRpdCgpCiAgICAgICAgc2VsZi5fY2xhdWRlX2tleS5zZXRQbGFjZWhvbGRlclRleHQoInNr"
    "LWFudC0uLi4iKQogICAgICAgIHNlbGYuX2NsYXVkZV9rZXkuc2V0RWNob01vZGUoUUxpbmVFZGl0"
    "LkVjaG9Nb2RlLlBhc3N3b3JkKQogICAgICAgIHNlbGYuX2NsYXVkZV9tb2RlbCA9IFFMaW5lRWRp"
    "dCgiY2xhdWRlLXNvbm5ldC00LTYiKQogICAgICAgIGwyLmFkZFdpZGdldChRTGFiZWwoIkFQSSBL"
    "ZXk6IikpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2NsYXVkZV9rZXkpCiAgICAgICAgbDIu"
    "YWRkV2lkZ2V0KFFMYWJlbCgiTW9kZWw6IikpCiAgICAgICAgbDIuYWRkV2lkZ2V0KHNlbGYuX2Ns"
    "YXVkZV9tb2RlbCkKICAgICAgICBzZWxmLl9zdGFjay5hZGRXaWRnZXQocDIpCgogICAgICAgICMg"
    "UGFnZSAzOiBPcGVuQUkKICAgICAgICBwMyA9IFFXaWRnZXQoKQogICAgICAgIGwzID0gUVZCb3hM"
    "YXlvdXQocDMpCiAgICAgICAgbDMuc2V0Q29udGVudHNNYXJnaW5zKDAsMCwwLDApCiAgICAgICAg"
    "c2VsZi5fb2FpX2tleSAgID0gUUxpbmVFZGl0KCkKICAgICAgICBzZWxmLl9vYWlfa2V5LnNldFBs"
    "YWNlaG9sZGVyVGV4dCgic2stLi4uIikKICAgICAgICBzZWxmLl9vYWlfa2V5LnNldEVjaG9Nb2Rl"
    "KFFMaW5lRWRpdC5FY2hvTW9kZS5QYXNzd29yZCkKICAgICAgICBzZWxmLl9vYWlfbW9kZWwgPSBR"
    "TGluZUVkaXQoImdwdC00byIpCiAgICAgICAgbDMuYWRkV2lkZ2V0KFFMYWJlbCgiQVBJIEtleToi"
    "KSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fb2FpX2tleSkKICAgICAgICBsMy5hZGRXaWRn"
    "ZXQoUUxhYmVsKCJNb2RlbDoiKSkKICAgICAgICBsMy5hZGRXaWRnZXQoc2VsZi5fb2FpX21vZGVs"
    "KQogICAgICAgIHNlbGYuX3N0YWNrLmFkZFdpZGdldChwMykKCiAgICAgICAgcm9vdC5hZGRXaWRn"
    "ZXQoc2VsZi5fc3RhY2spCgogICAgICAgICMg4pSA4pSAIFRlc3QgKyBzdGF0dXMg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICAgICAgdGVzdF9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAg"
    "c2VsZi5fYnRuX3Rlc3QgPSBfZ290aGljX2J0bigiVGVzdCBDb25uZWN0aW9uIikKICAgICAgICBz"
    "ZWxmLl9idG5fdGVzdC5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdGVzdF9jb25uZWN0aW9uKQogICAg"
    "ICAgIHNlbGYuX3N0YXR1c19sYmwgPSBRTGFiZWwoIiIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xi"
    "bC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQt"
    "c2l6ZTogMTBweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2Vy"
    "aWY7IgogICAgICAgICkKICAgICAgICB0ZXN0X3Jvdy5hZGRXaWRnZXQoc2VsZi5fYnRuX3Rlc3Qp"
    "CiAgICAgICAgdGVzdF9yb3cuYWRkV2lkZ2V0KHNlbGYuX3N0YXR1c19sYmwsIDEpCiAgICAgICAg"
    "cm9vdC5hZGRMYXlvdXQodGVzdF9yb3cpCgogICAgICAgICMg4pSA4pSAIEZhY2UgUGFjayDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICByb290LmFkZFdpZGdldChf"
    "c2VjdGlvbl9sYmwoIuKdpyBGQUNFIFBBQ0sgKG9wdGlvbmFsIOKAlCBaSVAgZmlsZSkiKSkKICAg"
    "ICAgICBmYWNlX3JvdyA9IFFIQm94TGF5b3V0KCkKICAgICAgICBzZWxmLl9mYWNlX3BhdGggPSBR"
    "TGluZUVkaXQoKQogICAgICAgIHNlbGYuX2ZhY2VfcGF0aC5zZXRQbGFjZWhvbGRlclRleHQoCiAg"
    "ICAgICAgICAgIGYiQnJvd3NlIHRvIHtERUNLX05BTUV9IGZhY2UgcGFjayBaSVAgKG9wdGlvbmFs"
    "LCBjYW4gYWRkIGxhdGVyKSIKICAgICAgICApCiAgICAgICAgc2VsZi5fZmFjZV9wYXRoLnNldFN0"
    "eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RF"
    "WFRfRElNfTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJv"
    "cmRlci1yYWRpdXM6IDJweDsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05U"
    "fSwgc2VyaWY7IGZvbnQtc2l6ZTogMTJweDsgcGFkZGluZzogNnB4IDEwcHg7IgogICAgICAgICkK"
    "ICAgICAgICBidG5fZmFjZSA9IF9nb3RoaWNfYnRuKCJCcm93c2UiKQogICAgICAgIGJ0bl9mYWNl"
    "LmNsaWNrZWQuY29ubmVjdChzZWxmLl9icm93c2VfZmFjZSkKICAgICAgICBmYWNlX3Jvdy5hZGRX"
    "aWRnZXQoc2VsZi5fZmFjZV9wYXRoKQogICAgICAgIGZhY2Vfcm93LmFkZFdpZGdldChidG5fZmFj"
    "ZSkKICAgICAgICByb290LmFkZExheW91dChmYWNlX3JvdykKCiAgICAgICAgIyDilIDilIAgU2hv"
    "cnRjdXQgb3B0aW9uIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3Nob3J0Y3V0X2Ni"
    "ID0gUUNoZWNrQm94KAogICAgICAgICAgICAiQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQgKHJlY29t"
    "bWVuZGVkKSIKICAgICAgICApCiAgICAgICAgc2VsZi5fc2hvcnRjdXRfY2Iuc2V0Q2hlY2tlZChU"
    "cnVlKQogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3Nob3J0Y3V0X2NiKQoKICAgICAgICAj"
    "IOKUgOKUgCBCdXR0b25zIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgICAgIHJvb3QuYWRkU3RyZXRjaCgpCiAgICAgICAgYnRuX3JvdyA9IFFIQm94TGF5b3V0"
    "KCkKICAgICAgICBzZWxmLl9idG5fYXdha2VuID0gX2dvdGhpY19idG4oIuKcpiBCRUdJTiBBV0FL"
    "RU5JTkciKQogICAgICAgIHNlbGYuX2J0bl9hd2FrZW4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAg"
    "ICBidG5fY2FuY2VsID0gX2dvdGhpY19idG4oIuKclyBDYW5jZWwiKQogICAgICAgIHNlbGYuX2J0"
    "bl9hd2FrZW4uY2xpY2tlZC5jb25uZWN0KHNlbGYuYWNjZXB0KQogICAgICAgIGJ0bl9jYW5jZWwu"
    "Y2xpY2tlZC5jb25uZWN0KHNlbGYucmVqZWN0KQogICAgICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KHNl"
    "bGYuX2J0bl9hd2FrZW4pCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQoYnRuX2NhbmNlbCkKICAg"
    "ICAgICByb290LmFkZExheW91dChidG5fcm93KQoKICAgIGRlZiBfb25fdHlwZV9jaGFuZ2Uoc2Vs"
    "ZiwgaWR4OiBpbnQpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fc3RhY2suc2V0Q3VycmVudEluZGV4"
    "KGlkeCkKICAgICAgICBzZWxmLl9idG5fYXdha2VuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAg"
    "c2VsZi5fc3RhdHVzX2xibC5zZXRUZXh0KCIiKQoKICAgIGRlZiBfYnJvd3NlX21vZGVsKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgcGF0aCA9IFFGaWxlRGlhbG9nLmdldEV4aXN0aW5nRGlyZWN0b3J5"
    "KAogICAgICAgICAgICBzZWxmLCAiU2VsZWN0IE1vZGVsIEZvbGRlciIsCiAgICAgICAgICAgIHIi"
    "RDpcQUlcTW9kZWxzIgogICAgICAgICkKICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICBzZWxm"
    "Ll9sb2NhbF9wYXRoLnNldFRleHQocGF0aCkKCiAgICBkZWYgX2Jyb3dzZV9mYWNlKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgcGF0aCwgXyA9IFFGaWxlRGlhbG9nLmdldE9wZW5GaWxlTmFtZSgKICAg"
    "ICAgICAgICAgc2VsZiwgIlNlbGVjdCBGYWNlIFBhY2sgWklQIiwKICAgICAgICAgICAgc3RyKFBh"
    "dGguaG9tZSgpIC8gIkRlc2t0b3AiKSwKICAgICAgICAgICAgIlpJUCBGaWxlcyAoKi56aXApIgog"
    "ICAgICAgICkKICAgICAgICBpZiBwYXRoOgogICAgICAgICAgICBzZWxmLl9mYWNlX3BhdGguc2V0"
    "VGV4dChwYXRoKQoKICAgIEBwcm9wZXJ0eQogICAgZGVmIGZhY2VfemlwX3BhdGgoc2VsZikgLT4g"
    "c3RyOgogICAgICAgIHJldHVybiBzZWxmLl9mYWNlX3BhdGgudGV4dCgpLnN0cmlwKCkKCiAgICBk"
    "ZWYgX3Rlc3RfY29ubmVjdGlvbihzZWxmKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3N0YXR1c19s"
    "Ymwuc2V0VGV4dCgiVGVzdGluZy4uLiIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2xibC5zZXRTdHls"
    "ZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19URVhUX0RJTX07IGZvbnQtc2l6ZTogMTBw"
    "eDsgZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQogICAgICAgIFFB"
    "cHBsaWNhdGlvbi5wcm9jZXNzRXZlbnRzKCkKCiAgICAgICAgaWR4ID0gc2VsZi5fdHlwZV9jb21i"
    "by5jdXJyZW50SW5kZXgoKQogICAgICAgIG9rICA9IEZhbHNlCiAgICAgICAgbXNnID0gIiIKCiAg"
    "ICAgICAgaWYgaWR4ID09IDA6ICAjIExvY2FsCiAgICAgICAgICAgIHBhdGggPSBzZWxmLl9sb2Nh"
    "bF9wYXRoLnRleHQoKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIHBhdGggYW5kIFBhdGgocGF0aCku"
    "ZXhpc3RzKCk6CiAgICAgICAgICAgICAgICBvayAgPSBUcnVlCiAgICAgICAgICAgICAgICBtc2cg"
    "PSBmIkZvbGRlciBmb3VuZC4gTW9kZWwgd2lsbCBsb2FkIG9uIHN0YXJ0dXAuIgogICAgICAgICAg"
    "ICBlbHNlOgogICAgICAgICAgICAgICAgbXNnID0gIkZvbGRlciBub3QgZm91bmQuIENoZWNrIHRo"
    "ZSBwYXRoLiIKCiAgICAgICAgZWxpZiBpZHggPT0gMTogICMgT2xsYW1hCiAgICAgICAgICAgIHRy"
    "eToKICAgICAgICAgICAgICAgIHJlcSAgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KAogICAgICAg"
    "ICAgICAgICAgICAgICJodHRwOi8vbG9jYWxob3N0OjExNDM0L2FwaS90YWdzIgogICAgICAgICAg"
    "ICAgICAgKQogICAgICAgICAgICAgICAgcmVzcCA9IHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVx"
    "LCB0aW1lb3V0PTMpCiAgICAgICAgICAgICAgICBvayAgID0gcmVzcC5zdGF0dXMgPT0gMjAwCiAg"
    "ICAgICAgICAgICAgICBtc2cgID0gIk9sbGFtYSBpcyBydW5uaW5nIOKckyIgaWYgb2sgZWxzZSAi"
    "T2xsYW1hIG5vdCByZXNwb25kaW5nLiIKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBl"
    "OgogICAgICAgICAgICAgICAgbXNnID0gZiJPbGxhbWEgbm90IHJlYWNoYWJsZToge2V9IgoKICAg"
    "ICAgICBlbGlmIGlkeCA9PSAyOiAgIyBDbGF1ZGUKICAgICAgICAgICAga2V5ID0gc2VsZi5fY2xh"
    "dWRlX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBvayAgPSBib29sKGtleSBhbmQga2V5"
    "LnN0YXJ0c3dpdGgoInNrLWFudCIpKQogICAgICAgICAgICBtc2cgPSAiQVBJIGtleSBmb3JtYXQg"
    "bG9va3MgY29ycmVjdC4iIGlmIG9rIGVsc2UgIkVudGVyIGEgdmFsaWQgQ2xhdWRlIEFQSSBrZXku"
    "IgoKICAgICAgICBlbGlmIGlkeCA9PSAzOiAgIyBPcGVuQUkKICAgICAgICAgICAga2V5ID0gc2Vs"
    "Zi5fb2FpX2tleS50ZXh0KCkuc3RyaXAoKQogICAgICAgICAgICBvayAgPSBib29sKGtleSBhbmQg"
    "a2V5LnN0YXJ0c3dpdGgoInNrLSIpKQogICAgICAgICAgICBtc2cgPSAiQVBJIGtleSBmb3JtYXQg"
    "bG9va3MgY29ycmVjdC4iIGlmIG9rIGVsc2UgIkVudGVyIGEgdmFsaWQgT3BlbkFJIEFQSSBrZXku"
    "IgoKICAgICAgICBjb2xvciA9IENfR1JFRU4gaWYgb2sgZWxzZSBDX0NSSU1TT04KICAgICAgICBz"
    "ZWxmLl9zdGF0dXNfbGJsLnNldFRleHQobXNnKQogICAgICAgIHNlbGYuX3N0YXR1c19sYmwuc2V0"
    "U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge2NvbG9yfTsgZm9udC1zaXplOiAxMHB4"
    "OyBmb250LWZhbWlseToge0RFQ0tfRk9OVH0sIHNlcmlmOyIKICAgICAgICApCiAgICAgICAgc2Vs"
    "Zi5fYnRuX2F3YWtlbi5zZXRFbmFibGVkKG9rKQoKICAgIGRlZiBidWlsZF9jb25maWcoc2VsZikg"
    "LT4gZGljdDoKICAgICAgICAiIiJCdWlsZCBhbmQgcmV0dXJuIHVwZGF0ZWQgY29uZmlnIGRpY3Qg"
    "ZnJvbSBkaWFsb2cgc2VsZWN0aW9ucy4iIiIKICAgICAgICBjZmcgICAgID0gX2RlZmF1bHRfY29u"
    "ZmlnKCkKICAgICAgICBpZHggICAgID0gc2VsZi5fdHlwZV9jb21iby5jdXJyZW50SW5kZXgoKQog"
    "ICAgICAgIHR5cGVzICAgPSBbImxvY2FsIiwgIm9sbGFtYSIsICJjbGF1ZGUiLCAib3BlbmFpIl0K"
    "ICAgICAgICBjZmdbIm1vZGVsIl1bInR5cGUiXSA9IHR5cGVzW2lkeF0KCiAgICAgICAgaWYgaWR4"
    "ID09IDA6CiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsicGF0aCJdID0gc2VsZi5fbG9jYWxfcGF0"
    "aC50ZXh0KCkuc3RyaXAoKQogICAgICAgIGVsaWYgaWR4ID09IDE6CiAgICAgICAgICAgIGNmZ1si"
    "bW9kZWwiXVsib2xsYW1hX21vZGVsIl0gPSBzZWxmLl9vbGxhbWFfbW9kZWwudGV4dCgpLnN0cmlw"
    "KCkgb3IgImRvbHBoaW4tMi42LTdiIgogICAgICAgIGVsaWYgaWR4ID09IDI6CiAgICAgICAgICAg"
    "IGNmZ1sibW9kZWwiXVsiYXBpX2tleSJdICAgPSBzZWxmLl9jbGF1ZGVfa2V5LnRleHQoKS5zdHJp"
    "cCgpCiAgICAgICAgICAgIGNmZ1sibW9kZWwiXVsiYXBpX21vZGVsIl0gPSBzZWxmLl9jbGF1ZGVf"
    "bW9kZWwudGV4dCgpLnN0cmlwKCkKICAgICAgICAgICAgY2ZnWyJtb2RlbCJdWyJhcGlfdHlwZSJd"
    "ICA9ICJjbGF1ZGUiCiAgICAgICAgZWxpZiBpZHggPT0gMzoKICAgICAgICAgICAgY2ZnWyJtb2Rl"
    "bCJdWyJhcGlfa2V5Il0gICA9IHNlbGYuX29haV9rZXkudGV4dCgpLnN0cmlwKCkKICAgICAgICAg"
    "ICAgY2ZnWyJtb2RlbCJdWyJhcGlfbW9kZWwiXSA9IHNlbGYuX29haV9tb2RlbC50ZXh0KCkuc3Ry"
    "aXAoKQogICAgICAgICAgICBjZmdbIm1vZGVsIl1bImFwaV90eXBlIl0gID0gIm9wZW5haSIKCiAg"
    "ICAgICAgY2ZnWyJmaXJzdF9ydW4iXSA9IEZhbHNlCiAgICAgICAgcmV0dXJuIGNmZwoKICAgIEBw"
    "cm9wZXJ0eQogICAgZGVmIGNyZWF0ZV9zaG9ydGN1dChzZWxmKSAtPiBib29sOgogICAgICAgIHJl"
    "dHVybiBzZWxmLl9zaG9ydGN1dF9jYi5pc0NoZWNrZWQoKQoKCiMg4pSA4pSAIEpPVVJOQUwgU0lE"
    "RUJBUiDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIAKY2xhc3MgSm91cm5hbFNpZGViYXIoUVdpZGdldCk6CiAgICAiIiIKICAgIENv"
    "bGxhcHNpYmxlIGxlZnQgc2lkZWJhciBuZXh0IHRvIHRoZSBTw6lhbmNlIFJlY29yZC4KICAgIFRv"
    "cDogc2Vzc2lvbiBjb250cm9scyAoY3VycmVudCBzZXNzaW9uIG5hbWUsIHNhdmUvbG9hZCBidXR0"
    "b25zLAogICAgICAgICBhdXRvc2F2ZSBpbmRpY2F0b3IpLgogICAgQm9keTogc2Nyb2xsYWJsZSBz"
    "ZXNzaW9uIGxpc3Qg4oCUIGRhdGUsIEFJIG5hbWUsIG1lc3NhZ2UgY291bnQuCiAgICBDb2xsYXBz"
    "ZXMgbGVmdHdhcmQgdG8gYSB0aGluIHN0cmlwLgoKICAgIFNpZ25hbHM6CiAgICAgICAgc2Vzc2lv"
    "bl9sb2FkX3JlcXVlc3RlZChzdHIpICAg4oCUIGRhdGUgc3RyaW5nIG9mIHNlc3Npb24gdG8gbG9h"
    "ZAogICAgICAgIHNlc3Npb25fY2xlYXJfcmVxdWVzdGVkKCkgICAgIOKAlCByZXR1cm4gdG8gY3Vy"
    "cmVudCBzZXNzaW9uCiAgICAiIiIKCiAgICBzZXNzaW9uX2xvYWRfcmVxdWVzdGVkICA9IFNpZ25h"
    "bChzdHIpCiAgICBzZXNzaW9uX2NsZWFyX3JlcXVlc3RlZCA9IFNpZ25hbCgpCgogICAgZGVmIF9f"
    "aW5pdF9fKHNlbGYsIHNlc3Npb25fbWdyOiAiU2Vzc2lvbk1hbmFnZXIiLCBwYXJlbnQ9Tm9uZSk6"
    "CiAgICAgICAgc3VwZXIoKS5fX2luaXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9t"
    "Z3IgPSBzZXNzaW9uX21ncgogICAgICAgIHNlbGYuX2V4cGFuZGVkICAgID0gVHJ1ZQogICAgICAg"
    "IHNlbGYuX3NldHVwX3VpKCkKICAgICAgICBzZWxmLnJlZnJlc2goKQoKICAgIGRlZiBfc2V0dXBf"
    "dWkoc2VsZikgLT4gTm9uZToKICAgICAgICAjIFVzZSBhIGhvcml6b250YWwgcm9vdCBsYXlvdXQg"
    "4oCUIGNvbnRlbnQgb24gbGVmdCwgdG9nZ2xlIHN0cmlwIG9uIHJpZ2h0CiAgICAgICAgcm9vdCA9"
    "IFFIQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMoMCwgMCwg"
    "MCwgMCkKICAgICAgICByb290LnNldFNwYWNpbmcoMCkKCiAgICAgICAgIyDilIDilIAgQ29sbGFw"
    "c2UgdG9nZ2xlIHN0cmlwIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3RvZ2dsZV9zdHJpcCA9IFFXaWRnZXQoKQog"
    "ICAgICAgIHNlbGYuX3RvZ2dsZV9zdHJpcC5zZXRGaXhlZFdpZHRoKDIwKQogICAgICAgIHNlbGYu"
    "X3RvZ2dsZV9zdHJpcC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtD"
    "X0JHM307IGJvcmRlci1yaWdodDogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsiCiAgICAgICAg"
    "KQogICAgICAgIHRzX2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYuX3RvZ2dsZV9zdHJpcCkKICAg"
    "ICAgICB0c19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDgsIDAsIDgpCiAgICAgICAgc2Vs"
    "Zi5fdG9nZ2xlX2J0biA9IFFUb29sQnV0dG9uKCkKICAgICAgICBzZWxmLl90b2dnbGVfYnRuLnNl"
    "dEZpeGVkU2l6ZSgxOCwgMTgpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0bi5zZXRUZXh0KCLil4Ai"
    "KQogICAgICAgIHNlbGYuX3RvZ2dsZV9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJi"
    "YWNrZ3JvdW5kOiB0cmFuc3BhcmVudDsgY29sb3I6IHtDX0dPTERfRElNfTsgIgogICAgICAgICAg"
    "ICBmImJvcmRlcjogbm9uZTsgZm9udC1zaXplOiAxMHB4OyIKICAgICAgICApCiAgICAgICAgc2Vs"
    "Zi5fdG9nZ2xlX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2VsZi5fdG9nZ2xlKQogICAgICAgIHRzX2xh"
    "eW91dC5hZGRXaWRnZXQoc2VsZi5fdG9nZ2xlX2J0bikKICAgICAgICB0c19sYXlvdXQuYWRkU3Ry"
    "ZXRjaCgpCgogICAgICAgICMg4pSA4pSAIE1haW4gY29udGVudCDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICBzZWxmLl9jb250ZW50ID0gUVdpZGdldCgpCiAgICAgICAgc2VsZi5f"
    "Y29udGVudC5zZXRNaW5pbXVtV2lkdGgoMTgwKQogICAgICAgIHNlbGYuX2NvbnRlbnQuc2V0TWF4"
    "aW11bVdpZHRoKDIyMCkKICAgICAgICBjb250ZW50X2xheW91dCA9IFFWQm94TGF5b3V0KHNlbGYu"
    "X2NvbnRlbnQpCiAgICAgICAgY29udGVudF9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDQsIDQs"
    "IDQsIDQpCiAgICAgICAgY29udGVudF9sYXlvdXQuc2V0U3BhY2luZyg0KQoKICAgICAgICAjIFNl"
    "Y3Rpb24gbGFiZWwKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRnZXQoX3NlY3Rpb25fbGJs"
    "KCLinacgSk9VUk5BTCIpKQoKICAgICAgICAjIEN1cnJlbnQgc2Vzc2lvbiBpbmZvCiAgICAgICAg"
    "c2VsZi5fc2Vzc2lvbl9uYW1lID0gUUxhYmVsKCJOZXcgU2Vzc2lvbiIpCiAgICAgICAgc2VsZi5f"
    "c2Vzc2lvbl9uYW1lLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9"
    "OyBmb250LXNpemU6IDEwcHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7ICIKICAg"
    "ICAgICAgICAgZiJmb250LXN0eWxlOiBpdGFsaWM7IgogICAgICAgICkKICAgICAgICBzZWxmLl9z"
    "ZXNzaW9uX25hbWUuc2V0V29yZFdyYXAoVHJ1ZSkKICAgICAgICBjb250ZW50X2xheW91dC5hZGRX"
    "aWRnZXQoc2VsZi5fc2Vzc2lvbl9uYW1lKQoKICAgICAgICAjIFNhdmUgLyBMb2FkIHJvdwogICAg"
    "ICAgIGN0cmxfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHNlbGYuX2J0bl9zYXZlID0gX2dv"
    "dGhpY19idG4oIvCfkr4iKQogICAgICAgIHNlbGYuX2J0bl9zYXZlLnNldEZpeGVkU2l6ZSgzMiwg"
    "MjQpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUuc2V0VG9vbFRpcCgiU2F2ZSBzZXNzaW9uIG5vdyIp"
    "CiAgICAgICAgc2VsZi5fYnRuX2xvYWQgPSBfZ290aGljX2J0bigi8J+TgiIpCiAgICAgICAgc2Vs"
    "Zi5fYnRuX2xvYWQuc2V0Rml4ZWRTaXplKDMyLCAyNCkKICAgICAgICBzZWxmLl9idG5fbG9hZC5z"
    "ZXRUb29sVGlwKCJCcm93c2UgYW5kIGxvYWQgYSBwYXN0IHNlc3Npb24iKQogICAgICAgIHNlbGYu"
    "X2F1dG9zYXZlX2RvdCA9IFFMYWJlbCgi4pePIikKICAgICAgICBzZWxmLl9hdXRvc2F2ZV9kb3Qu"
    "c2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250LXNp"
    "emU6IDhweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAgc2VsZi5fYXV0b3NhdmVf"
    "ZG90LnNldFRvb2xUaXAoIkF1dG9zYXZlIHN0YXR1cyIpCiAgICAgICAgc2VsZi5fYnRuX3NhdmUu"
    "Y2xpY2tlZC5jb25uZWN0KHNlbGYuX2RvX3NhdmUpCiAgICAgICAgc2VsZi5fYnRuX2xvYWQuY2xp"
    "Y2tlZC5jb25uZWN0KHNlbGYuX2RvX2xvYWQpCiAgICAgICAgY3RybF9yb3cuYWRkV2lkZ2V0KHNl"
    "bGYuX2J0bl9zYXZlKQogICAgICAgIGN0cmxfcm93LmFkZFdpZGdldChzZWxmLl9idG5fbG9hZCkK"
    "ICAgICAgICBjdHJsX3Jvdy5hZGRXaWRnZXQoc2VsZi5fYXV0b3NhdmVfZG90KQogICAgICAgIGN0"
    "cmxfcm93LmFkZFN0cmV0Y2goKQogICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZExheW91dChjdHJs"
    "X3JvdykKCiAgICAgICAgIyBKb3VybmFsIGxvYWRlZCBpbmRpY2F0b3IKICAgICAgICBzZWxmLl9q"
    "b3VybmFsX2xibCA9IFFMYWJlbCgiIikKICAgICAgICBzZWxmLl9qb3VybmFsX2xibC5zZXRTdHls"
    "ZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19QVVJQTEV9OyBmb250LXNpemU6IDlweDsg"
    "Zm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgIgogICAgICAgICAgICBmImZvbnQtc3R5"
    "bGU6IGl0YWxpYzsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsLnNldFdvcmRX"
    "cmFwKFRydWUpCiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2pvdXJuYWxf"
    "bGJsKQoKICAgICAgICAjIENsZWFyIGpvdXJuYWwgYnV0dG9uIChoaWRkZW4gd2hlbiBub3QgbG9h"
    "ZGVkKQogICAgICAgIHNlbGYuX2J0bl9jbGVhcl9qb3VybmFsID0gX2dvdGhpY19idG4oIuKclyBS"
    "ZXR1cm4gdG8gUHJlc2VudCIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwuc2V0Vmlz"
    "aWJsZShGYWxzZSkKICAgICAgICBzZWxmLl9idG5fY2xlYXJfam91cm5hbC5jbGlja2VkLmNvbm5l"
    "Y3Qoc2VsZi5fZG9fY2xlYXJfam91cm5hbCkKICAgICAgICBjb250ZW50X2xheW91dC5hZGRXaWRn"
    "ZXQoc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwpCgogICAgICAgICMgRGl2aWRlcgogICAgICAgIGRp"
    "diA9IFFGcmFtZSgpCiAgICAgICAgZGl2LnNldEZyYW1lU2hhcGUoUUZyYW1lLlNoYXBlLkhMaW5l"
    "KQogICAgICAgIGRpdi5zZXRTdHlsZVNoZWV0KGYiY29sb3I6IHtDX0NSSU1TT05fRElNfTsiKQog"
    "ICAgICAgIGNvbnRlbnRfbGF5b3V0LmFkZFdpZGdldChkaXYpCgogICAgICAgICMgU2Vzc2lvbiBs"
    "aXN0CiAgICAgICAgY29udGVudF9sYXlvdXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIFBB"
    "U1QgU0VTU0lPTlMiKSkKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3QgPSBRTGlzdFdpZGdldCgp"
    "CiAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0LnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYi"
    "YmFja2dyb3VuZDoge0NfQkcyfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9y"
    "ZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7"
    "REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsiCiAgICAgICAgICAgIGYiUUxpc3RX"
    "aWRnZXQ6Oml0ZW06c2VsZWN0ZWQge3sgYmFja2dyb3VuZDoge0NfQ1JJTVNPTl9ESU19OyB9fSIK"
    "ICAgICAgICApCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0Lml0ZW1Eb3VibGVDbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fb25fc2Vzc2lvbl9jbGljaykKICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3Qu"
    "aXRlbUNsaWNrZWQuY29ubmVjdChzZWxmLl9vbl9zZXNzaW9uX2NsaWNrKQogICAgICAgIGNvbnRl"
    "bnRfbGF5b3V0LmFkZFdpZGdldChzZWxmLl9zZXNzaW9uX2xpc3QsIDEpCgogICAgICAgICMgQWRk"
    "IGNvbnRlbnQgYW5kIHRvZ2dsZSBzdHJpcCB0byB0aGUgcm9vdCBob3Jpem9udGFsIGxheW91dAog"
    "ICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX2NvbnRlbnQpCiAgICAgICAgcm9vdC5hZGRXaWRn"
    "ZXQoc2VsZi5fdG9nZ2xlX3N0cmlwKQoKICAgIGRlZiBfdG9nZ2xlKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgc2VsZi5fZXhwYW5kZWQgPSBub3Qgc2VsZi5fZXhwYW5kZWQKICAgICAgICBzZWxmLl9j"
    "b250ZW50LnNldFZpc2libGUoc2VsZi5fZXhwYW5kZWQpCiAgICAgICAgc2VsZi5fdG9nZ2xlX2J0"
    "bi5zZXRUZXh0KCLil4AiIGlmIHNlbGYuX2V4cGFuZGVkIGVsc2UgIuKWtiIpCiAgICAgICAgc2Vs"
    "Zi51cGRhdGVHZW9tZXRyeSgpCiAgICAgICAgcCA9IHNlbGYucGFyZW50V2lkZ2V0KCkKICAgICAg"
    "ICBpZiBwIGFuZCBwLmxheW91dCgpOgogICAgICAgICAgICBwLmxheW91dCgpLmFjdGl2YXRlKCkK"
    "CiAgICBkZWYgcmVmcmVzaChzZWxmKSAtPiBOb25lOgogICAgICAgIHNlc3Npb25zID0gc2VsZi5f"
    "c2Vzc2lvbl9tZ3IubGlzdF9zZXNzaW9ucygpCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9saXN0LmNs"
    "ZWFyKCkKICAgICAgICBmb3IgcyBpbiBzZXNzaW9uczoKICAgICAgICAgICAgZGF0ZV9zdHIgPSBz"
    "LmdldCgiZGF0ZSIsIiIpCiAgICAgICAgICAgIG5hbWUgICAgID0gcy5nZXQoIm5hbWUiLCBkYXRl"
    "X3N0cilbOjMwXQogICAgICAgICAgICBjb3VudCAgICA9IHMuZ2V0KCJtZXNzYWdlX2NvdW50Iiwg"
    "MCkKICAgICAgICAgICAgaXRlbSA9IFFMaXN0V2lkZ2V0SXRlbShmIntkYXRlX3N0cn1cbntuYW1l"
    "fSAoe2NvdW50fSBtc2dzKSIpCiAgICAgICAgICAgIGl0ZW0uc2V0RGF0YShRdC5JdGVtRGF0YVJv"
    "bGUuVXNlclJvbGUsIGRhdGVfc3RyKQogICAgICAgICAgICBpdGVtLnNldFRvb2xUaXAoZiJEb3Vi"
    "bGUtY2xpY2sgdG8gbG9hZCBzZXNzaW9uIGZyb20ge2RhdGVfc3RyfSIpCiAgICAgICAgICAgIHNl"
    "bGYuX3Nlc3Npb25fbGlzdC5hZGRJdGVtKGl0ZW0pCgogICAgZGVmIHNldF9zZXNzaW9uX25hbWUo"
    "c2VsZiwgbmFtZTogc3RyKSAtPiBOb25lOgogICAgICAgIHNlbGYuX3Nlc3Npb25fbmFtZS5zZXRU"
    "ZXh0KG5hbWVbOjUwXSBvciAiTmV3IFNlc3Npb24iKQoKICAgIGRlZiBzZXRfYXV0b3NhdmVfaW5k"
    "aWNhdG9yKHNlbGYsIHNhdmVkOiBib29sKSAtPiBOb25lOgogICAgICAgIHNlbGYuX2F1dG9zYXZl"
    "X2RvdC5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7Q19HUkVFTiBpZiBzYXZl"
    "ZCBlbHNlIENfVEVYVF9ESU19OyAiCiAgICAgICAgICAgIGYiZm9udC1zaXplOiA4cHg7IGJvcmRl"
    "cjogbm9uZTsiCiAgICAgICAgKQogICAgICAgIHNlbGYuX2F1dG9zYXZlX2RvdC5zZXRUb29sVGlw"
    "KAogICAgICAgICAgICAiQXV0b3NhdmVkIiBpZiBzYXZlZCBlbHNlICJQZW5kaW5nIGF1dG9zYXZl"
    "IgogICAgICAgICkKCiAgICBkZWYgc2V0X2pvdXJuYWxfbG9hZGVkKHNlbGYsIGRhdGVfc3RyOiBz"
    "dHIpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fam91cm5hbF9sYmwuc2V0VGV4dChmIvCfk5YgSm91"
    "cm5hbDoge2RhdGVfc3RyfSIpCiAgICAgICAgc2VsZi5fYnRuX2NsZWFyX2pvdXJuYWwuc2V0Vmlz"
    "aWJsZShUcnVlKQoKICAgIGRlZiBjbGVhcl9qb3VybmFsX2luZGljYXRvcihzZWxmKSAtPiBOb25l"
    "OgogICAgICAgIHNlbGYuX2pvdXJuYWxfbGJsLnNldFRleHQoIiIpCiAgICAgICAgc2VsZi5fYnRu"
    "X2NsZWFyX2pvdXJuYWwuc2V0VmlzaWJsZShGYWxzZSkKCiAgICBkZWYgX2RvX3NhdmUoc2VsZikg"
    "LT4gTm9uZToKICAgICAgICBzZWxmLl9zZXNzaW9uX21nci5zYXZlKCkKICAgICAgICBzZWxmLnNl"
    "dF9hdXRvc2F2ZV9pbmRpY2F0b3IoVHJ1ZSkKICAgICAgICBzZWxmLnJlZnJlc2goKQogICAgICAg"
    "IHNlbGYuX2J0bl9zYXZlLnNldFRleHQoIuKckyIpCiAgICAgICAgUVRpbWVyLnNpbmdsZVNob3Qo"
    "MTUwMCwgbGFtYmRhOiBzZWxmLl9idG5fc2F2ZS5zZXRUZXh0KCLwn5K+IikpCiAgICAgICAgUVRp"
    "bWVyLnNpbmdsZVNob3QoMzAwMCwgbGFtYmRhOiBzZWxmLnNldF9hdXRvc2F2ZV9pbmRpY2F0b3Io"
    "RmFsc2UpKQoKICAgIGRlZiBfZG9fbG9hZChzZWxmKSAtPiBOb25lOgogICAgICAgICMgVHJ5IHNl"
    "bGVjdGVkIGl0ZW0gZmlyc3QKICAgICAgICBpdGVtID0gc2VsZi5fc2Vzc2lvbl9saXN0LmN1cnJl"
    "bnRJdGVtKCkKICAgICAgICBpZiBub3QgaXRlbToKICAgICAgICAgICAgIyBJZiBub3RoaW5nIHNl"
    "bGVjdGVkLCB0cnkgdGhlIGZpcnN0IGl0ZW0KICAgICAgICAgICAgaWYgc2VsZi5fc2Vzc2lvbl9s"
    "aXN0LmNvdW50KCkgPiAwOgogICAgICAgICAgICAgICAgaXRlbSA9IHNlbGYuX3Nlc3Npb25fbGlz"
    "dC5pdGVtKDApCiAgICAgICAgICAgICAgICBzZWxmLl9zZXNzaW9uX2xpc3Quc2V0Q3VycmVudEl0"
    "ZW0oaXRlbSkKICAgICAgICBpZiBpdGVtOgogICAgICAgICAgICBkYXRlX3N0ciA9IGl0ZW0uZGF0"
    "YShRdC5JdGVtRGF0YVJvbGUuVXNlclJvbGUpCiAgICAgICAgICAgIHNlbGYuc2Vzc2lvbl9sb2Fk"
    "X3JlcXVlc3RlZC5lbWl0KGRhdGVfc3RyKQoKICAgIGRlZiBfb25fc2Vzc2lvbl9jbGljayhzZWxm"
    "LCBpdGVtKSAtPiBOb25lOgogICAgICAgIGRhdGVfc3RyID0gaXRlbS5kYXRhKFF0Lkl0ZW1EYXRh"
    "Um9sZS5Vc2VyUm9sZSkKICAgICAgICBzZWxmLnNlc3Npb25fbG9hZF9yZXF1ZXN0ZWQuZW1pdChk"
    "YXRlX3N0cikKCiAgICBkZWYgX2RvX2NsZWFyX2pvdXJuYWwoc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBzZWxmLnNlc3Npb25fY2xlYXJfcmVxdWVzdGVkLmVtaXQoKQogICAgICAgIHNlbGYuY2xlYXJf"
    "am91cm5hbF9pbmRpY2F0b3IoKQoKCiMg4pSA4pSAIFRPUlBPUiBQQU5FTCDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIAKY2xhc3MgVG9ycG9yUGFuZWwoUVdpZGdldCk6CiAgICAiIiIKICAgIFRocmVlLXN0YXRlIHRv"
    "cnBvciB0b2dnbGU6IEFXQUtFIHwgQVVUTyB8IENPRkZJTgoKICAgIEFXQUtFICDigJQgbW9kZWwg"
    "bG9hZGVkLCBhdXRvLXRvcnBvciBkaXNhYmxlZCwgaWdub3JlcyBWUkFNIHByZXNzdXJlCiAgICBB"
    "VVRPICAg4oCUIG1vZGVsIGxvYWRlZCwgbW9uaXRvcnMgVlJBTSBwcmVzc3VyZSwgYXV0by10b3Jw"
    "b3IgaWYgc3VzdGFpbmVkCiAgICBDT0ZGSU4g4oCUIG1vZGVsIHVubG9hZGVkLCBzdGF5cyBpbiB0"
    "b3Jwb3IgdW50aWwgbWFudWFsbHkgY2hhbmdlZAoKICAgIFNpZ25hbHM6CiAgICAgICAgc3RhdGVf"
    "Y2hhbmdlZChzdHIpICDigJQgIkFXQUtFIiB8ICJBVVRPIiB8ICJDT0ZGSU4iCiAgICAiIiIKCiAg"
    "ICBzdGF0ZV9jaGFuZ2VkID0gU2lnbmFsKHN0cikKCiAgICBTVEFURVMgPSBbIkFXQUtFIiwgIkFV"
    "VE8iLCAiQ09GRklOIl0KCiAgICBTVEFURV9TVFlMRVMgPSB7CiAgICAgICAgIkFXQUtFIjogewog"
    "ICAgICAgICAgICAiYWN0aXZlIjogICBmImJhY2tncm91bmQ6ICMyYTFhMDU7IGNvbG9yOiB7Q19H"
    "T0xEfTsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0dP"
    "TER9OyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJmb250"
    "LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7IiwKICAgICAg"
    "ICAgICAgImluYWN0aXZlIjogZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9E"
    "SU19OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9S"
    "REVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9u"
    "dC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAg"
    "ICAgICAgICJsYWJlbCI6ICAgICLimIAgQVdBS0UiLAogICAgICAgICAgICAidG9vbHRpcCI6ICAi"
    "TW9kZWwgYWN0aXZlLiBBdXRvLXRvcnBvciBkaXNhYmxlZC4iLAogICAgICAgIH0sCiAgICAgICAg"
    "IkFVVE8iOiB7CiAgICAgICAgICAgICJhY3RpdmUiOiAgIGYiYmFja2dyb3VuZDogIzFhMTAwNTsg"
    "Y29sb3I6ICNjYzg4MjI7ICIKICAgICAgICAgICAgICAgICAgICAgICAgZiJib3JkZXI6IDFweCBz"
    "b2xpZCAjY2M4ODIyOyBib3JkZXItcmFkaXVzOiAycHg7ICIKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgZiJmb250LXNpemU6IDlweDsgZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDNweCA4cHg7"
    "IiwKICAgICAgICAgICAgImluYWN0aXZlIjogZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjog"
    "e0NfVEVYVF9ESU19OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29s"
    "aWQge0NfQk9SREVSfTsgYm9yZGVyLXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4"
    "OyIsCiAgICAgICAgICAgICJsYWJlbCI6ICAgICLil4kgQVVUTyIsCiAgICAgICAgICAgICJ0b29s"
    "dGlwIjogICJNb2RlbCBhY3RpdmUuIEF1dG8tdG9ycG9yIG9uIFZSQU0gcHJlc3N1cmUuIiwKICAg"
    "ICAgICB9LAogICAgICAgICJDT0ZGSU4iOiB7CiAgICAgICAgICAgICJhY3RpdmUiOiAgIGYiYmFj"
    "a2dyb3VuZDoge0NfUFVSUExFX0RJTX07IGNvbG9yOiB7Q19QVVJQTEV9OyAiCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfUFVSUExFfTsgYm9yZGVyLXJhZGl1"
    "czogMnB4OyAiCiAgICAgICAgICAgICAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQt"
    "d2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIsCiAgICAgICAgICAgICJpbmFjdGl2ZSI6"
    "IGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RFWFRfRElNfTsgIgogICAgICAgICAg"
    "ICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IGJvcmRlci1yYWRp"
    "dXM6IDJweDsgIgogICAgICAgICAgICAgICAgICAgICAgICBmImZvbnQtc2l6ZTogOXB4OyBmb250"
    "LXdlaWdodDogYm9sZDsgcGFkZGluZzogM3B4IDhweDsiLAogICAgICAgICAgICAibGFiZWwiOiAg"
    "ICAi4pqwIENPRkZJTiIsCiAgICAgICAgICAgICJ0b29sdGlwIjogIGYiTW9kZWwgdW5sb2FkZWQu"
    "IHtERUNLX05BTUV9IHNsZWVwcyB1bnRpbCBtYW51YWxseSBhd2FrZW5lZC4iLAogICAgICAgIH0s"
    "CiAgICB9CgogICAgZGVmIF9faW5pdF9fKHNlbGYsIHBhcmVudD1Ob25lKToKICAgICAgICBzdXBl"
    "cigpLl9faW5pdF9fKHBhcmVudCkKICAgICAgICBzZWxmLl9jdXJyZW50ID0gIkFXQUtFIgogICAg"
    "ICAgIHNlbGYuX2J1dHRvbnM6IGRpY3Rbc3RyLCBRUHVzaEJ1dHRvbl0gPSB7fQogICAgICAgIGxh"
    "eW91dCA9IFFIQm94TGF5b3V0KHNlbGYpCiAgICAgICAgbGF5b3V0LnNldENvbnRlbnRzTWFyZ2lu"
    "cygwLCAwLCAwLCAwKQogICAgICAgIGxheW91dC5zZXRTcGFjaW5nKDIpCgogICAgICAgIGZvciBz"
    "dGF0ZSBpbiBzZWxmLlNUQVRFUzoKICAgICAgICAgICAgYnRuID0gUVB1c2hCdXR0b24oc2VsZi5T"
    "VEFURV9TVFlMRVNbc3RhdGVdWyJsYWJlbCJdKQogICAgICAgICAgICBidG4uc2V0VG9vbFRpcChz"
    "ZWxmLlNUQVRFX1NUWUxFU1tzdGF0ZV1bInRvb2x0aXAiXSkKICAgICAgICAgICAgYnRuLnNldEZp"
    "eGVkSGVpZ2h0KDIyKQogICAgICAgICAgICBidG4uY2xpY2tlZC5jb25uZWN0KGxhbWJkYSBjaGVj"
    "a2VkLCBzPXN0YXRlOiBzZWxmLl9zZXRfc3RhdGUocykpCiAgICAgICAgICAgIHNlbGYuX2J1dHRv"
    "bnNbc3RhdGVdID0gYnRuCiAgICAgICAgICAgIGxheW91dC5hZGRXaWRnZXQoYnRuKQoKICAgICAg"
    "ICBzZWxmLl9hcHBseV9zdHlsZXMoKQoKICAgIGRlZiBfc2V0X3N0YXRlKHNlbGYsIHN0YXRlOiBz"
    "dHIpIC0+IE5vbmU6CiAgICAgICAgaWYgc3RhdGUgPT0gc2VsZi5fY3VycmVudDoKICAgICAgICAg"
    "ICAgcmV0dXJuCiAgICAgICAgc2VsZi5fY3VycmVudCA9IHN0YXRlCiAgICAgICAgc2VsZi5fYXBw"
    "bHlfc3R5bGVzKCkKICAgICAgICBzZWxmLnN0YXRlX2NoYW5nZWQuZW1pdChzdGF0ZSkKCiAgICBk"
    "ZWYgX2FwcGx5X3N0eWxlcyhzZWxmKSAtPiBOb25lOgogICAgICAgIGZvciBzdGF0ZSwgYnRuIGlu"
    "IHNlbGYuX2J1dHRvbnMuaXRlbXMoKToKICAgICAgICAgICAgc3R5bGVfa2V5ID0gImFjdGl2ZSIg"
    "aWYgc3RhdGUgPT0gc2VsZi5fY3VycmVudCBlbHNlICJpbmFjdGl2ZSIKICAgICAgICAgICAgYnRu"
    "LnNldFN0eWxlU2hlZXQoc2VsZi5TVEFURV9TVFlMRVNbc3RhdGVdW3N0eWxlX2tleV0pCgogICAg"
    "QHByb3BlcnR5CiAgICBkZWYgY3VycmVudF9zdGF0ZShzZWxmKSAtPiBzdHI6CiAgICAgICAgcmV0"
    "dXJuIHNlbGYuX2N1cnJlbnQKCiAgICBkZWYgc2V0X3N0YXRlKHNlbGYsIHN0YXRlOiBzdHIpIC0+"
    "IE5vbmU6CiAgICAgICAgIiIiU2V0IHN0YXRlIHByb2dyYW1tYXRpY2FsbHkgKGUuZy4gZnJvbSBh"
    "dXRvLXRvcnBvciBkZXRlY3Rpb24pLiIiIgogICAgICAgIGlmIHN0YXRlIGluIHNlbGYuU1RBVEVT"
    "OgogICAgICAgICAgICBzZWxmLl9zZXRfc3RhdGUoc3RhdGUpCgoKIyDilIDilIAgTUFJTiBXSU5E"
    "T1cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSACmNsYXNzIEVjaG9EZWNrKFFNYWluV2luZG93KToKICAgICIi"
    "IgogICAgVGhlIG1haW4gRWNobyBEZWNrIHdpbmRvdy4KICAgIEFzc2VtYmxlcyBhbGwgd2lkZ2V0"
    "cywgY29ubmVjdHMgYWxsIHNpZ25hbHMsIG1hbmFnZXMgYWxsIHN0YXRlLgogICAgIiIiCgogICAg"
    "IyDilIDilIAgVG9ycG9yIHRocmVzaG9sZHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBf"
    "RVhURVJOQUxfVlJBTV9UT1JQT1JfR0IgICAgPSAxLjUgICAjIGV4dGVybmFsIFZSQU0gPiB0aGlz"
    "IOKGkiBjb25zaWRlciB0b3Jwb3IKICAgIF9FWFRFUk5BTF9WUkFNX1dBS0VfR0IgICAgICA9IDAu"
    "OCAgICMgZXh0ZXJuYWwgVlJBTSA8IHRoaXMg4oaSIGNvbnNpZGVyIHdha2UKICAgIF9UT1JQT1Jf"
    "U1VTVEFJTkVEX1RJQ0tTICAgICA9IDYgICAgICMgNiDDlyA1cyA9IDMwIHNlY29uZHMgc3VzdGFp"
    "bmVkCiAgICBfV0FLRV9TVVNUQUlORURfVElDS1MgICAgICAgPSAxMiAgICAjIDYwIHNlY29uZHMg"
    "c3VzdGFpbmVkIGxvdyBwcmVzc3VyZQoKICAgIGRlZiBfX2luaXRfXyhzZWxmKToKICAgICAgICBz"
    "dXBlcigpLl9faW5pdF9fKCkKCiAgICAgICAgIyDilIDilIAgQ29yZSBzdGF0ZSDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9zdGF0dXMgICAgICAgICAgICAg"
    "ID0gIk9GRkxJTkUiCiAgICAgICAgc2VsZi5fc2Vzc2lvbl9zdGFydCAgICAgICA9IHRpbWUudGlt"
    "ZSgpCiAgICAgICAgc2VsZi5fdG9rZW5fY291bnQgICAgICAgICA9IDAKICAgICAgICBzZWxmLl9m"
    "YWNlX2xvY2tlZCAgICAgICAgID0gRmFsc2UKICAgICAgICBzZWxmLl9ibGlua19zdGF0ZSAgICAg"
    "ICAgID0gVHJ1ZQogICAgICAgIHNlbGYuX21vZGVsX2xvYWRlZCAgICAgICAgPSBGYWxzZQogICAg"
    "ICAgIHNlbGYuX3Nlc3Npb25faWQgICAgICAgICAgPSBmInNlc3Npb25fe2RhdGV0aW1lLm5vdygp"
    "LnN0cmZ0aW1lKCclWSVtJWRfJUglTSVTJyl9IgogICAgICAgIHNlbGYuX2FjdGl2ZV90aHJlYWRz"
    "OiBsaXN0ID0gW10gICMga2VlcCByZWZzIHRvIHByZXZlbnQgR0Mgd2hpbGUgcnVubmluZwogICAg"
    "ICAgIHNlbGYuX2ZpcnN0X3Rva2VuOiBib29sID0gVHJ1ZSAgICMgd3JpdGUgc3BlYWtlciBsYWJl"
    "bCBiZWZvcmUgZmlyc3Qgc3RyZWFtaW5nIHRva2VuCgogICAgICAgICMgVG9ycG9yIC8gVlJBTSB0"
    "cmFja2luZwogICAgICAgIHNlbGYuX3RvcnBvcl9zdGF0ZSAgICAgICAgPSAiQVdBS0UiCiAgICAg"
    "ICAgc2VsZi5fZGVja192cmFtX2Jhc2UgID0gMC4wICAgIyBiYXNlbGluZSBWUkFNIGFmdGVyIG1v"
    "ZGVsIGxvYWQKICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID0gMCAgICAgIyBzdXN0"
    "YWluZWQgcHJlc3N1cmUgY291bnRlcgogICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICAg"
    "PSAwICAgICAjIHN1c3RhaW5lZCByZWxpZWYgY291bnRlcgogICAgICAgIHNlbGYuX3BlbmRpbmdf"
    "dHJhbnNtaXNzaW9ucyA9IDAKICAgICAgICBzZWxmLl90b3Jwb3Jfc2luY2UgICAgICAgID0gTm9u"
    "ZSAgIyBkYXRldGltZSB3aGVuIHRvcnBvciBiZWdhbgogICAgICAgIHNlbGYuX3N1c3BlbmRlZF9k"
    "dXJhdGlvbiAgPSAiIiAgICMgZm9ybWF0dGVkIGR1cmF0aW9uIHN0cmluZwoKICAgICAgICAjIOKU"
    "gOKUgCBNYW5hZ2VycyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICBzZWxmLl9tZW1vcnkgICA9IE1lbW9yeU1hbmFnZXIoKQogICAgICAgIHNlbGYuX3Nlc3Np"
    "b25zID0gU2Vzc2lvbk1hbmFnZXIoKQogICAgICAgIHNlbGYuX2xlc3NvbnMgID0gTGVzc29uc0xl"
    "YXJuZWREQigpCiAgICAgICAgc2VsZi5fdGFza3MgICAgPSBUYXNrTWFuYWdlcigpCiAgICAgICAg"
    "c2VsZi5fcmVjb3Jkc19jYWNoZTogbGlzdFtkaWN0XSA9IFtdCiAgICAgICAgc2VsZi5fcmVjb3Jk"
    "c19pbml0aWFsaXplZCA9IEZhbHNlCiAgICAgICAgc2VsZi5fcmVjb3Jkc19jdXJyZW50X2ZvbGRl"
    "cl9pZCA9ICJyb290IgogICAgICAgIHNlbGYuX2dvb2dsZV9hdXRoX3JlYWR5ID0gRmFsc2UKICAg"
    "ICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lcjogT3B0aW9uYWxbUVRpbWVyXSA9IE5vbmUK"
    "ICAgICAgICBzZWxmLl9nb29nbGVfcmVjb3Jkc19yZWZyZXNoX3RpbWVyOiBPcHRpb25hbFtRVGlt"
    "ZXJdID0gTm9uZQogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiX2luZGV4ID0gLTEKICAgICAgICBz"
    "ZWxmLl90YXNrc190YWJfaW5kZXggPSAtMQogICAgICAgIHNlbGYuX3Rhc2tfc2hvd19jb21wbGV0"
    "ZWQgPSBGYWxzZQogICAgICAgIHNlbGYuX3Rhc2tfZGF0ZV9maWx0ZXIgPSAibmV4dF8zX21vbnRo"
    "cyIKCiAgICAgICAgIyDilIDilIAgR29vZ2xlIFNlcnZpY2VzIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAog"
    "ICAgICAgICMgSW5zdGFudGlhdGUgc2VydmljZSB3cmFwcGVycyB1cC1mcm9udDsgYXV0aCBpcyBm"
    "b3JjZWQgbGF0ZXIKICAgICAgICAjIGZyb20gbWFpbigpIGFmdGVyIHdpbmRvdy5zaG93KCkgd2hl"
    "biB0aGUgZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgICAgIGdfY3JlZHNfcGF0aCA9IFBhdGgo"
    "Q0ZHLmdldCgiZ29vZ2xlIiwge30pLmdldCgKICAgICAgICAgICAgImNyZWRlbnRpYWxzIiwKICAg"
    "ICAgICAgICAgc3RyKGNmZ19wYXRoKCJnb29nbGUiKSAvICJnb29nbGVfY3JlZGVudGlhbHMuanNv"
    "biIpCiAgICAgICAgKSkKICAgICAgICBnX3Rva2VuX3BhdGggPSBQYXRoKENGRy5nZXQoImdvb2ds"
    "ZSIsIHt9KS5nZXQoCiAgICAgICAgICAgICJ0b2tlbiIsCiAgICAgICAgICAgIHN0cihjZmdfcGF0"
    "aCgiZ29vZ2xlIikgLyAidG9rZW4uanNvbiIpCiAgICAgICAgKSkKICAgICAgICBzZWxmLl9nY2Fs"
    "ID0gR29vZ2xlQ2FsZW5kYXJTZXJ2aWNlKGdfY3JlZHNfcGF0aCwgZ190b2tlbl9wYXRoKQogICAg"
    "ICAgIHNlbGYuX2dkcml2ZSA9IEdvb2dsZURvY3NEcml2ZVNlcnZpY2UoCiAgICAgICAgICAgIGdf"
    "Y3JlZHNfcGF0aCwKICAgICAgICAgICAgZ190b2tlbl9wYXRoLAogICAgICAgICAgICBsb2dnZXI9"
    "bGFtYmRhIG1zZywgbGV2ZWw9IklORk8iOiBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR0RSSVZFXSB7"
    "bXNnfSIsIGxldmVsKQogICAgICAgICkKCiAgICAgICAgIyBTZWVkIExTTCBydWxlcyBvbiBmaXJz"
    "dCBydW4KICAgICAgICBzZWxmLl9sZXNzb25zLnNlZWRfbHNsX3J1bGVzKCkKCiAgICAgICAgIyBM"
    "b2FkIGVudGl0eSBzdGF0ZQogICAgICAgIHNlbGYuX3N0YXRlID0gc2VsZi5fbWVtb3J5LmxvYWRf"
    "c3RhdGUoKQogICAgICAgIHNlbGYuX3N0YXRlWyJzZXNzaW9uX2NvdW50Il0gPSBzZWxmLl9zdGF0"
    "ZS5nZXQoInNlc3Npb25fY291bnQiLDApICsgMQogICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X3N0"
    "YXJ0dXAiXSAgPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICBzZWxmLl9tZW1vcnkuc2F2ZV9zdGF0"
    "ZShzZWxmLl9zdGF0ZSkKCiAgICAgICAgIyBCdWlsZCBhZGFwdG9yCiAgICAgICAgc2VsZi5fYWRh"
    "cHRvciA9IGJ1aWxkX2FkYXB0b3JfZnJvbV9jb25maWcoKQoKICAgICAgICAjIEZhY2UgdGltZXIg"
    "bWFuYWdlciAoc2V0IHVwIGFmdGVyIHdpZGdldHMgYnVpbHQpCiAgICAgICAgc2VsZi5fZmFjZV90"
    "aW1lcl9tZ3I6IE9wdGlvbmFsW0ZhY2VUaW1lck1hbmFnZXJdID0gTm9uZQoKICAgICAgICAjIOKU"
    "gOKUgCBCdWlsZCBVSSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICBzZWxmLnNldFdpbmRvd1RpdGxlKEFQUF9OQU1FKQogICAgICAgIHNlbGYuc2V0TWluaW11"
    "bVNpemUoMTIwMCwgNzUwKQogICAgICAgIHNlbGYucmVzaXplKDEzNTAsIDg1MCkKICAgICAgICBz"
    "ZWxmLnNldFN0eWxlU2hlZXQoU1RZTEUpCgogICAgICAgIHNlbGYuX2J1aWxkX3VpKCkKCiAgICAg"
    "ICAgIyBGYWNlIHRpbWVyIG1hbmFnZXIgd2lyZWQgdG8gd2lkZ2V0cwogICAgICAgIHNlbGYuX2Zh"
    "Y2VfdGltZXJfbWdyID0gRmFjZVRpbWVyTWFuYWdlcigKICAgICAgICAgICAgc2VsZi5fbWlycm9y"
    "LCBzZWxmLl9lbW90aW9uX2Jsb2NrCiAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBUaW1lcnMg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2Vs"
    "Zi5fc3RhdHNfdGltZXIgPSBRVGltZXIoKQogICAgICAgIHNlbGYuX3N0YXRzX3RpbWVyLnRpbWVv"
    "dXQuY29ubmVjdChzZWxmLl91cGRhdGVfc3RhdHMpCiAgICAgICAgc2VsZi5fc3RhdHNfdGltZXIu"
    "c3RhcnQoMTAwMCkKCiAgICAgICAgc2VsZi5fYmxpbmtfdGltZXIgPSBRVGltZXIoKQogICAgICAg"
    "IHNlbGYuX2JsaW5rX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl9ibGluaykKICAgICAgICBz"
    "ZWxmLl9ibGlua190aW1lci5zdGFydCg4MDApCgogICAgICAgIHNlbGYuX3N0YXRlX3N0cmlwX3Rp"
    "bWVyID0gUVRpbWVyKCkKICAgICAgICBzZWxmLl9zdGF0ZV9zdHJpcF90aW1lci50aW1lb3V0LmNv"
    "bm5lY3Qoc2VsZi5fdmFtcF9zdHJpcC5yZWZyZXNoKQogICAgICAgIHNlbGYuX3N0YXRlX3N0cmlw"
    "X3RpbWVyLnN0YXJ0KDYwMDAwKQoKICAgICAgICBzZWxmLl9nb29nbGVfaW5ib3VuZF90aW1lciA9"
    "IFFUaW1lcihzZWxmKQogICAgICAgIHNlbGYuX2dvb2dsZV9pbmJvdW5kX3RpbWVyLnRpbWVvdXQu"
    "Y29ubmVjdChzZWxmLl9vbl9nb29nbGVfaW5ib3VuZF90aW1lcl90aWNrKQogICAgICAgIHNlbGYu"
    "X2dvb2dsZV9pbmJvdW5kX3RpbWVyLnN0YXJ0KDYwMDAwKQoKICAgICAgICBzZWxmLl9nb29nbGVf"
    "cmVjb3Jkc19yZWZyZXNoX3RpbWVyID0gUVRpbWVyKHNlbGYpCiAgICAgICAgc2VsZi5fZ29vZ2xl"
    "X3JlY29yZHNfcmVmcmVzaF90aW1lci50aW1lb3V0LmNvbm5lY3Qoc2VsZi5fb25fZ29vZ2xlX3Jl"
    "Y29yZHNfcmVmcmVzaF90aW1lcl90aWNrKQogICAgICAgIHNlbGYuX2dvb2dsZV9yZWNvcmRzX3Jl"
    "ZnJlc2hfdGltZXIuc3RhcnQoNjAwMDApCgogICAgICAgICMg4pSA4pSAIFNjaGVkdWxlciBhbmQg"
    "c3RhcnR1cCBkZWZlcnJlZCB1bnRpbCBhZnRlciB3aW5kb3cuc2hvdygpIOKUgOKUgOKUgAogICAg"
    "ICAgICMgRG8gTk9UIGNhbGwgX3NldHVwX3NjaGVkdWxlcigpIG9yIF9zdGFydHVwX3NlcXVlbmNl"
    "KCkgaGVyZS4KICAgICAgICAjIEJvdGggYXJlIHRyaWdnZXJlZCB2aWEgUVRpbWVyLnNpbmdsZVNo"
    "b3QgZnJvbSBtYWluKCkgYWZ0ZXIKICAgICAgICAjIHdpbmRvdy5zaG93KCkgYW5kIGFwcC5leGVj"
    "KCkgYmVnaW5zIHJ1bm5pbmcuCgogICAgIyDilIDilIAgVUkgQ09OU1RSVUNUSU9OIOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9i"
    "dWlsZF91aShzZWxmKSAtPiBOb25lOgogICAgICAgIGNlbnRyYWwgPSBRV2lkZ2V0KCkKICAgICAg"
    "ICBzZWxmLnNldENlbnRyYWxXaWRnZXQoY2VudHJhbCkKICAgICAgICByb290ID0gUVZCb3hMYXlv"
    "dXQoY2VudHJhbCkKICAgICAgICByb290LnNldENvbnRlbnRzTWFyZ2lucyg2LCA2LCA2LCA2KQog"
    "ICAgICAgIHJvb3Quc2V0U3BhY2luZyg0KQoKICAgICAgICAjIOKUgOKUgCBUaXRsZSBiYXIg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRXaWRnZXQo"
    "c2VsZi5fYnVpbGRfdGl0bGVfYmFyKCkpCgogICAgICAgICMg4pSA4pSAIEJvZHk6IEpvdXJuYWwg"
    "fCBDaGF0IHwgU3BlbGwgQm9vayDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBib2R5ID0g"
    "UUhCb3hMYXlvdXQoKQogICAgICAgIGJvZHkuc2V0U3BhY2luZyg0KQoKICAgICAgICAjIEpvdXJu"
    "YWwgc2lkZWJhciAobGVmdCkKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIgPSBKb3VybmFs"
    "U2lkZWJhcihzZWxmLl9zZXNzaW9ucykKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2Vz"
    "c2lvbl9sb2FkX3JlcXVlc3RlZC5jb25uZWN0KAogICAgICAgICAgICBzZWxmLl9sb2FkX2pvdXJu"
    "YWxfc2Vzc2lvbikKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2Vzc2lvbl9jbGVhcl9y"
    "ZXF1ZXN0ZWQuY29ubmVjdCgKICAgICAgICAgICAgc2VsZi5fY2xlYXJfam91cm5hbF9zZXNzaW9u"
    "KQogICAgICAgIGJvZHkuYWRkV2lkZ2V0KHNlbGYuX2pvdXJuYWxfc2lkZWJhcikKCiAgICAgICAg"
    "IyBDaGF0IHBhbmVsIChjZW50ZXIsIGV4cGFuZHMpCiAgICAgICAgYm9keS5hZGRMYXlvdXQoc2Vs"
    "Zi5fYnVpbGRfY2hhdF9wYW5lbCgpLCAxKQoKICAgICAgICAjIFNwZWxsIEJvb2sgKHJpZ2h0KQog"
    "ICAgICAgIGJvZHkuYWRkTGF5b3V0KHNlbGYuX2J1aWxkX3NwZWxsYm9va19wYW5lbCgpKQoKICAg"
    "ICAgICByb290LmFkZExheW91dChib2R5LCAxKQoKICAgICAgICAjIOKUgOKUgCBWYW1waXJlIFN0"
    "YXRlIFN0cmlwIChmdWxsIHdpZHRoLCBhbHdheXMgdmlzaWJsZSkg4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICAgICAgcm9vdC5hZGRXaWRnZXQoc2VsZi5fdmFtcF9zdHJpcCkK"
    "CiAgICAgICAgIyDilIDilIAgRm9vdGVyIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgAogICAgICAgIGZvb3RlciA9IFFMYWJlbCgKICAgICAgICAgICAgZiLinKYg"
    "e0FQUF9OQU1FfSDigJQgdntBUFBfVkVSU0lPTn0g4pymIgogICAgICAgICkKICAgICAgICBmb290"
    "ZXIuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0NfVEVYVF9ESU19OyBmb250"
    "LXNpemU6IDlweDsgbGV0dGVyLXNwYWNpbmc6IDJweDsgIgogICAgICAgICAgICBmImZvbnQtZmFt"
    "aWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICBmb290ZXIuc2V0QWxp"
    "Z25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCiAgICAgICAgcm9vdC5hZGRXaWRn"
    "ZXQoZm9vdGVyKQoKICAgIGRlZiBfYnVpbGRfdGl0bGVfYmFyKHNlbGYpIC0+IFFXaWRnZXQ6CiAg"
    "ICAgICAgYmFyID0gUVdpZGdldCgpCiAgICAgICAgYmFyLnNldEZpeGVkSGVpZ2h0KDM2KQogICAg"
    "ICAgIGJhci5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07"
    "IGJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICBmImJvcmRl"
    "ci1yYWRpdXM6IDJweDsiCiAgICAgICAgKQogICAgICAgIGxheW91dCA9IFFIQm94TGF5b3V0KGJh"
    "cikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDEwLCAwLCAxMCwgMCkKICAgICAg"
    "ICBsYXlvdXQuc2V0U3BhY2luZyg2KQoKICAgICAgICB0aXRsZSA9IFFMYWJlbChmIuKcpiB7QVBQ"
    "X05BTUV9IikKICAgICAgICB0aXRsZS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9y"
    "OiB7Q19DUklNU09OfTsgZm9udC1zaXplOiAxM3B4OyBmb250LXdlaWdodDogYm9sZDsgIgogICAg"
    "ICAgICAgICBmImxldHRlci1zcGFjaW5nOiAycHg7IGJvcmRlcjogbm9uZTsgZm9udC1mYW1pbHk6"
    "IHtERUNLX0ZPTlR9LCBzZXJpZjsiCiAgICAgICAgKQoKICAgICAgICBydW5lcyA9IFFMYWJlbChS"
    "VU5FUykKICAgICAgICBydW5lcy5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImNvbG9yOiB7"
    "Q19HT0xEX0RJTX07IGZvbnQtc2l6ZTogMTBweDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAg"
    "ICAgICAgcnVuZXMuc2V0QWxpZ25tZW50KFF0LkFsaWdubWVudEZsYWcuQWxpZ25DZW50ZXIpCgog"
    "ICAgICAgIHNlbGYuc3RhdHVzX2xhYmVsID0gUUxhYmVsKCLil4kgT0ZGTElORSIpCiAgICAgICAg"
    "c2VsZi5zdGF0dXNfbGFiZWwuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJjb2xvcjoge0Nf"
    "QkxPT0R9OyBmb250LXNpemU6IDEycHg7IGZvbnQtd2VpZ2h0OiBib2xkOyBib3JkZXI6IG5vbmU7"
    "IgogICAgICAgICkKICAgICAgICBzZWxmLnN0YXR1c19sYWJlbC5zZXRBbGlnbm1lbnQoUXQuQWxp"
    "Z25tZW50RmxhZy5BbGlnblJpZ2h0KQoKICAgICAgICAjIFRvcnBvciBwYW5lbAogICAgICAgIHNl"
    "bGYuX3RvcnBvcl9wYW5lbCA9IFRvcnBvclBhbmVsKCkKICAgICAgICBzZWxmLl90b3Jwb3JfcGFu"
    "ZWwuc3RhdGVfY2hhbmdlZC5jb25uZWN0KHNlbGYuX29uX3RvcnBvcl9zdGF0ZV9jaGFuZ2VkKQoK"
    "ICAgICAgICAjIElkbGUgdG9nZ2xlCiAgICAgICAgc2VsZi5faWRsZV9idG4gPSBRUHVzaEJ1dHRv"
    "bigiSURMRSBPRkYiKQogICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQog"
    "ICAgICAgIHNlbGYuX2lkbGVfYnRuLnNldENoZWNrYWJsZShUcnVlKQogICAgICAgIHNlbGYuX2lk"
    "bGVfYnRuLnNldENoZWNrZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faWRsZV9idG4uc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CRzN9OyBjb2xvcjoge0NfVEVYVF9E"
    "SU19OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgYm9yZGVy"
    "LXJhZGl1czogMnB4OyAiCiAgICAgICAgICAgIGYiZm9udC1zaXplOiA5cHg7IGZvbnQtd2VpZ2h0"
    "OiBib2xkOyBwYWRkaW5nOiAzcHggOHB4OyIKICAgICAgICApCiAgICAgICAgc2VsZi5faWRsZV9i"
    "dG4udG9nZ2xlZC5jb25uZWN0KHNlbGYuX29uX2lkbGVfdG9nZ2xlZCkKCiAgICAgICAgIyBGUyAv"
    "IEJMIGJ1dHRvbnMKICAgICAgICBzZWxmLl9mc19idG4gPSBRUHVzaEJ1dHRvbigiRlMiKQogICAg"
    "ICAgIHNlbGYuX2JsX2J0biA9IFFQdXNoQnV0dG9uKCJCTCIpCiAgICAgICAgc2VsZi5fZXhwb3J0"
    "X2J0biA9IFFQdXNoQnV0dG9uKCJFeHBvcnQiKQogICAgICAgIHNlbGYuX3NodXRkb3duX2J0biA9"
    "IFFQdXNoQnV0dG9uKCJTaHV0ZG93biIpCiAgICAgICAgZm9yIGJ0biBpbiAoc2VsZi5fZnNfYnRu"
    "LCBzZWxmLl9ibF9idG4sIHNlbGYuX2V4cG9ydF9idG4pOgogICAgICAgICAgICBidG4uc2V0Rml4"
    "ZWRTaXplKDMwLCAyMikKICAgICAgICAgICAgYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "ICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19DUklNU09OX0RJTX07ICIKICAg"
    "ICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyBmb250LXNp"
    "emU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzog"
    "MDsiCiAgICAgICAgICAgICkKICAgICAgICBzZWxmLl9leHBvcnRfYnRuLnNldEZpeGVkV2lkdGgo"
    "NDYpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNldEZpeGVkSGVpZ2h0KDIyKQogICAgICAg"
    "IHNlbGYuX3NodXRkb3duX2J0bi5zZXRGaXhlZFdpZHRoKDY4KQogICAgICAgIHNlbGYuX3NodXRk"
    "b3duX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307"
    "IGNvbG9yOiB7Q19CTE9PRH07ICIKICAgICAgICAgICAgZiJib3JkZXI6IDFweCBzb2xpZCB7Q19C"
    "TE9PRH07IGZvbnQtc2l6ZTogOXB4OyAiCiAgICAgICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7"
    "IHBhZGRpbmc6IDA7IgogICAgICAgICkKICAgICAgICBzZWxmLl9mc19idG4uc2V0VG9vbFRpcCgi"
    "RnVsbHNjcmVlbiAoRjExKSIpCiAgICAgICAgc2VsZi5fYmxfYnRuLnNldFRvb2xUaXAoIkJvcmRl"
    "cmxlc3MgKEYxMCkiKQogICAgICAgIHNlbGYuX2V4cG9ydF9idG4uc2V0VG9vbFRpcCgiRXhwb3J0"
    "IGNoYXQgc2Vzc2lvbiB0byBUWFQgZmlsZSIpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLnNl"
    "dFRvb2xUaXAoZiJHcmFjZWZ1bCBzaHV0ZG93biDigJQge0RFQ0tfTkFNRX0gc3BlYWtzIGhlciBs"
    "YXN0IHdvcmRzIikKICAgICAgICBzZWxmLl9mc19idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3Rv"
    "Z2dsZV9mdWxsc2NyZWVuKQogICAgICAgIHNlbGYuX2JsX2J0bi5jbGlja2VkLmNvbm5lY3Qoc2Vs"
    "Zi5fdG9nZ2xlX2JvcmRlcmxlc3MpCiAgICAgICAgc2VsZi5fZXhwb3J0X2J0bi5jbGlja2VkLmNv"
    "bm5lY3Qoc2VsZi5fZXhwb3J0X2NoYXQpCiAgICAgICAgc2VsZi5fc2h1dGRvd25fYnRuLmNsaWNr"
    "ZWQuY29ubmVjdChzZWxmLl9pbml0aWF0ZV9zaHV0ZG93bl9kaWFsb2cpCgogICAgICAgIGxheW91"
    "dC5hZGRXaWRnZXQodGl0bGUpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChydW5lcywgMSkKICAg"
    "ICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNlbGYuc3RhdHVzX2xhYmVsKQogICAgICAgIGxheW91dC5h"
    "ZGRTcGFjaW5nKDgpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl90b3Jwb3JfcGFuZWwp"
    "CiAgICAgICAgbGF5b3V0LmFkZFNwYWNpbmcoNCkKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHNl"
    "bGYuX2lkbGVfYnRuKQogICAgICAgIGxheW91dC5hZGRTcGFjaW5nKDQpCiAgICAgICAgbGF5b3V0"
    "LmFkZFdpZGdldChzZWxmLl9leHBvcnRfYnRuKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2Vs"
    "Zi5fc2h1dGRvd25fYnRuKQogICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fZnNfYnRuKQog"
    "ICAgICAgIGxheW91dC5hZGRXaWRnZXQoc2VsZi5fYmxfYnRuKQoKICAgICAgICByZXR1cm4gYmFy"
    "CgogICAgZGVmIF9idWlsZF9jaGF0X3BhbmVsKHNlbGYpIC0+IFFWQm94TGF5b3V0OgogICAgICAg"
    "IGxheW91dCA9IFFWQm94TGF5b3V0KCkKICAgICAgICBsYXlvdXQuc2V0U3BhY2luZyg0KQoKICAg"
    "ICAgICAjIE1haW4gdGFiIHdpZGdldCDigJQgU8OpYW5jZSBSZWNvcmQgfCBTZWxmCiAgICAgICAg"
    "c2VsZi5fbWFpbl90YWJzID0gUVRhYldpZGdldCgpCiAgICAgICAgc2VsZi5fbWFpbl90YWJzLnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiUVRhYldpZGdldDo6cGFuZSB7eyBib3JkZXI6IDFw"
    "eCBzb2xpZCB7Q19DUklNU09OX0RJTX07ICIKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19N"
    "T05JVE9SfTsgfX0iCiAgICAgICAgICAgIGYiUVRhYkJhcjo6dGFiIHt7IGJhY2tncm91bmQ6IHtD"
    "X0JHM307IGNvbG9yOiB7Q19URVhUX0RJTX07ICIKICAgICAgICAgICAgZiJwYWRkaW5nOiA0cHgg"
    "MTJweDsgYm9yZGVyOiAxcHggc29saWQge0NfQk9SREVSfTsgIgogICAgICAgICAgICBmImZvbnQt"
    "ZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTBweDsgfX0iCiAgICAgICAg"
    "ICAgIGYiUVRhYkJhcjo6dGFiOnNlbGVjdGVkIHt7IGJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9y"
    "OiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlci1ib3R0b206IDJweCBzb2xpZCB7Q19D"
    "UklNU09OfTsgfX0iCiAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBUYWIgMDogU8OpYW5jZSBS"
    "ZWNvcmQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICAgICAgc2VhbmNlX3dpZGdldCA9IFFXaWRnZXQoKQogICAgICAgIHNlYW5j"
    "ZV9sYXlvdXQgPSBRVkJveExheW91dChzZWFuY2Vfd2lkZ2V0KQogICAgICAgIHNlYW5jZV9sYXlv"
    "dXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAgICAgICAgc2VhbmNlX2xheW91dC5z"
    "ZXRTcGFjaW5nKDApCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5ID0gUVRleHRFZGl0KCkKICAg"
    "ICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuc2V0UmVhZE9ubHkoVHJ1ZSkKICAgICAgICBzZWxmLl9j"
    "aGF0X2Rpc3BsYXkuc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19N"
    "T05JVE9SfTsgY29sb3I6IHtDX0dPTER9OyAiCiAgICAgICAgICAgIGYiYm9yZGVyOiBub25lOyAi"
    "CiAgICAgICAgICAgIGYiZm9udC1mYW1pbHk6IHtERUNLX0ZPTlR9LCBzZXJpZjsgZm9udC1zaXpl"
    "OiAxMnB4OyBwYWRkaW5nOiA4cHg7IgogICAgICAgICkKICAgICAgICBzZWFuY2VfbGF5b3V0LmFk"
    "ZFdpZGdldChzZWxmLl9jaGF0X2Rpc3BsYXkpCiAgICAgICAgc2VsZi5fbWFpbl90YWJzLmFkZFRh"
    "YihzZWFuY2Vfd2lkZ2V0LCAi4p2nIFPDiUFOQ0UgUkVDT1JEIikKCiAgICAgICAgIyDilIDilIAg"
    "VGFiIDE6IFNlbGYg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc2VsZi5f"
    "c2VsZl90YWJfd2lkZ2V0ID0gUVdpZGdldCgpCiAgICAgICAgc2VsZl9sYXlvdXQgPSBRVkJveExh"
    "eW91dChzZWxmLl9zZWxmX3RhYl93aWRnZXQpCiAgICAgICAgc2VsZl9sYXlvdXQuc2V0Q29udGVu"
    "dHNNYXJnaW5zKDQsIDQsIDQsIDQpCiAgICAgICAgc2VsZl9sYXlvdXQuc2V0U3BhY2luZyg0KQog"
    "ICAgICAgIHNlbGYuX3NlbGZfZGlzcGxheSA9IFFUZXh0RWRpdCgpCiAgICAgICAgc2VsZi5fc2Vs"
    "Zl9kaXNwbGF5LnNldFJlYWRPbmx5KFRydWUpCiAgICAgICAgc2VsZi5fc2VsZl9kaXNwbGF5LnNl"
    "dFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfTU9OSVRPUn07IGNvbG9y"
    "OiB7Q19HT0xEfTsgIgogICAgICAgICAgICBmImJvcmRlcjogbm9uZTsgIgogICAgICAgICAgICBm"
    "ImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IGZvbnQtc2l6ZTogMTJweDsgcGFkZGlu"
    "ZzogOHB4OyIKICAgICAgICApCiAgICAgICAgc2VsZl9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3Nl"
    "bGZfZGlzcGxheSwgMSkKICAgICAgICBzZWxmLl9tYWluX3RhYnMuYWRkVGFiKHNlbGYuX3NlbGZf"
    "dGFiX3dpZGdldCwgIuKXiSBTRUxGIikKCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl9t"
    "YWluX3RhYnMsIDEpCgogICAgICAgICMg4pSA4pSAIEJvdHRvbSBibG9jayByb3cg4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSACiAgICAgICAgIyBNSVJST1IgfCBFTU9USU9OUyB8IEJMT09EIHwgTU9PTiB8IE1BTkEg"
    "fCBFU1NFTkNFCiAgICAgICAgYmxvY2tfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIGJsb2Nr"
    "X3Jvdy5zZXRTcGFjaW5nKDIpCgogICAgICAgICMgTWlycm9yIChuZXZlciBjb2xsYXBzZXMpCiAg"
    "ICAgICAgbWlycm9yX3dyYXAgPSBRV2lkZ2V0KCkKICAgICAgICBtd19sYXlvdXQgPSBRVkJveExh"
    "eW91dChtaXJyb3Jfd3JhcCkKICAgICAgICBtd19sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAs"
    "IDAsIDAsIDApCiAgICAgICAgbXdfbGF5b3V0LnNldFNwYWNpbmcoMikKICAgICAgICBtd19sYXlv"
    "dXQuYWRkV2lkZ2V0KF9zZWN0aW9uX2xibCgi4p2nIE1JUlJPUiIpKQogICAgICAgIHNlbGYuX21p"
    "cnJvciA9IE1pcnJvcldpZGdldCgpCiAgICAgICAgc2VsZi5fbWlycm9yLnNldEZpeGVkU2l6ZSgx"
    "NjAsIDE2MCkKICAgICAgICBtd19sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX21pcnJvcikKICAgICAg"
    "ICBibG9ja19yb3cuYWRkV2lkZ2V0KG1pcnJvcl93cmFwKQoKICAgICAgICAjIEVtb3Rpb24gYmxv"
    "Y2sgKGNvbGxhcHNpYmxlKQogICAgICAgIHNlbGYuX2Vtb3Rpb25fYmxvY2sgPSBFbW90aW9uQmxv"
    "Y2soKQogICAgICAgIHNlbGYuX2Vtb3Rpb25fYmxvY2tfd3JhcCA9IENvbGxhcHNpYmxlQmxvY2so"
    "CiAgICAgICAgICAgICLinacgRU1PVElPTlMiLCBzZWxmLl9lbW90aW9uX2Jsb2NrLAogICAgICAg"
    "ICAgICBleHBhbmRlZD1UcnVlLCBtaW5fd2lkdGg9MTMwCiAgICAgICAgKQogICAgICAgIGJsb2Nr"
    "X3Jvdy5hZGRXaWRnZXQoc2VsZi5fZW1vdGlvbl9ibG9ja193cmFwKQoKICAgICAgICAjIEJsb29k"
    "IHNwaGVyZSAoY29sbGFwc2libGUpCiAgICAgICAgc2VsZi5fYmxvb2Rfc3BoZXJlID0gU3BoZXJl"
    "V2lkZ2V0KAogICAgICAgICAgICAiQkxPT0QiLCBDX0NSSU1TT04sIENfQ1JJTVNPTl9ESU0KICAg"
    "ICAgICApCiAgICAgICAgYmxvY2tfcm93LmFkZFdpZGdldCgKICAgICAgICAgICAgQ29sbGFwc2li"
    "bGVCbG9jaygi4p2nIEJMT09EIiwgc2VsZi5fYmxvb2Rfc3BoZXJlLAogICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIG1pbl93aWR0aD05MCkKICAgICAgICApCgogICAgICAgICMgTW9vbiAoY29s"
    "bGFwc2libGUpCiAgICAgICAgc2VsZi5fbW9vbl93aWRnZXQgPSBNb29uV2lkZ2V0KCkKICAgICAg"
    "ICBibG9ja19yb3cuYWRkV2lkZ2V0KAogICAgICAgICAgICBDb2xsYXBzaWJsZUJsb2NrKCLinacg"
    "TU9PTiIsIHNlbGYuX21vb25fd2lkZ2V0LCBtaW5fd2lkdGg9OTApCiAgICAgICAgKQoKICAgICAg"
    "ICAjIE1hbmEgc3BoZXJlIChjb2xsYXBzaWJsZSkKICAgICAgICBzZWxmLl9tYW5hX3NwaGVyZSA9"
    "IFNwaGVyZVdpZGdldCgKICAgICAgICAgICAgIk1BTkEiLCBDX1BVUlBMRSwgQ19QVVJQTEVfRElN"
    "CiAgICAgICAgKQogICAgICAgIGJsb2NrX3Jvdy5hZGRXaWRnZXQoCiAgICAgICAgICAgIENvbGxh"
    "cHNpYmxlQmxvY2soIuKdpyBNQU5BIiwgc2VsZi5fbWFuYV9zcGhlcmUsIG1pbl93aWR0aD05MCkK"
    "ICAgICAgICApCgogICAgICAgICMgRXNzZW5jZSAoSFVOR0VSICsgVklUQUxJVFkgYmFycywgY29s"
    "bGFwc2libGUpCiAgICAgICAgZXNzZW5jZV93aWRnZXQgPSBRV2lkZ2V0KCkKICAgICAgICBlc3Nl"
    "bmNlX2xheW91dCA9IFFWQm94TGF5b3V0KGVzc2VuY2Vfd2lkZ2V0KQogICAgICAgIGVzc2VuY2Vf"
    "bGF5b3V0LnNldENvbnRlbnRzTWFyZ2lucyg0LCA0LCA0LCA0KQogICAgICAgIGVzc2VuY2VfbGF5"
    "b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBzZWxmLl9odW5nZXJfZ2F1Z2UgICA9IEdhdWdlV2lk"
    "Z2V0KCJIVU5HRVIiLCAgICIlIiwgMTAwLjAsIENfQ1JJTVNPTikKICAgICAgICBzZWxmLl92aXRh"
    "bGl0eV9nYXVnZSA9IEdhdWdlV2lkZ2V0KCJWSVRBTElUWSIsICIlIiwgMTAwLjAsIENfR1JFRU4p"
    "CiAgICAgICAgZXNzZW5jZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX2h1bmdlcl9nYXVnZSkKICAg"
    "ICAgICBlc3NlbmNlX2xheW91dC5hZGRXaWRnZXQoc2VsZi5fdml0YWxpdHlfZ2F1Z2UpCiAgICAg"
    "ICAgYmxvY2tfcm93LmFkZFdpZGdldCgKICAgICAgICAgICAgQ29sbGFwc2libGVCbG9jaygi4p2n"
    "IEVTU0VOQ0UiLCBlc3NlbmNlX3dpZGdldCwgbWluX3dpZHRoPTExMCkKICAgICAgICApCgogICAg"
    "ICAgIGJsb2NrX3Jvdy5hZGRTdHJldGNoKCkKICAgICAgICBsYXlvdXQuYWRkTGF5b3V0KGJsb2Nr"
    "X3JvdykKCiAgICAgICAgIyBWYW1waXJlIFN0YXRlIFN0cmlwIChiZWxvdyBibG9jayByb3cg4oCU"
    "IGFsd2F5cyB2aXNpYmxlKQogICAgICAgIHNlbGYuX3ZhbXBfc3RyaXAgPSBWYW1waXJlU3RhdGVT"
    "dHJpcCgpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChzZWxmLl92YW1wX3N0cmlwKQoKICAgICAg"
    "ICAjIOKUgOKUgCBJbnB1dCByb3cg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "CiAgICAgICAgaW5wdXRfcm93ID0gUUhCb3hMYXlvdXQoKQogICAgICAgIHByb21wdF9zeW0gPSBR"
    "TGFiZWwoIuKcpiIpCiAgICAgICAgcHJvbXB0X3N5bS5zZXRTdHlsZVNoZWV0KAogICAgICAgICAg"
    "ICBmImNvbG9yOiB7Q19DUklNU09OfTsgZm9udC1zaXplOiAxNnB4OyBmb250LXdlaWdodDogYm9s"
    "ZDsgYm9yZGVyOiBub25lOyIKICAgICAgICApCiAgICAgICAgcHJvbXB0X3N5bS5zZXRGaXhlZFdp"
    "ZHRoKDIwKQoKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZCA9IFFMaW5lRWRpdCgpCiAgICAgICAg"
    "c2VsZi5faW5wdXRfZmllbGQuc2V0UGxhY2Vob2xkZXJUZXh0KCJTcGVhayBpbnRvIHRoZSBkYXJr"
    "bmVzcy4uLiIpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQucmV0dXJuUHJlc3NlZC5jb25uZWN0"
    "KHNlbGYuX3NlbmRfbWVzc2FnZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVk"
    "KEZhbHNlKQoKICAgICAgICBzZWxmLl9zZW5kX2J0biA9IFFQdXNoQnV0dG9uKCJJTlZPS0UiKQog"
    "ICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEZpeGVkV2lkdGgoMTEwKQogICAgICAgIHNlbGYuX3Nl"
    "bmRfYnRuLmNsaWNrZWQuY29ubmVjdChzZWxmLl9zZW5kX21lc3NhZ2UpCiAgICAgICAgc2VsZi5f"
    "c2VuZF9idG4uc2V0RW5hYmxlZChGYWxzZSkKCiAgICAgICAgaW5wdXRfcm93LmFkZFdpZGdldChw"
    "cm9tcHRfc3ltKQogICAgICAgIGlucHV0X3Jvdy5hZGRXaWRnZXQoc2VsZi5faW5wdXRfZmllbGQp"
    "CiAgICAgICAgaW5wdXRfcm93LmFkZFdpZGdldChzZWxmLl9zZW5kX2J0bikKICAgICAgICBsYXlv"
    "dXQuYWRkTGF5b3V0KGlucHV0X3JvdykKCiAgICAgICAgcmV0dXJuIGxheW91dAoKICAgIGRlZiBf"
    "YnVpbGRfc3BlbGxib29rX3BhbmVsKHNlbGYpIC0+IFFWQm94TGF5b3V0OgogICAgICAgIGxheW91"
    "dCA9IFFWQm94TGF5b3V0KCkKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAs"
    "IDAsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoNCkKICAgICAgICBsYXlvdXQuYWRkV2lk"
    "Z2V0KF9zZWN0aW9uX2xibCgi4p2nIFRIRSBTUEVMTCBCT09LIikpCgogICAgICAgICMgVGFiIHdp"
    "ZGdldAogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMgPSBRVGFiV2lkZ2V0KCkKICAgICAgICBzZWxm"
    "Ll9zcGVsbF90YWJzLnNldE1pbmltdW1XaWR0aCgyODApCiAgICAgICAgc2VsZi5fc3BlbGxfdGFi"
    "cy5zZXRTaXplUG9saWN5KAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5n"
    "LAogICAgICAgICAgICBRU2l6ZVBvbGljeS5Qb2xpY3kuRXhwYW5kaW5nCiAgICAgICAgKQoKICAg"
    "ICAgICAjIEJ1aWxkIERpYWdub3N0aWNzVGFiIGVhcmx5IHNvIHN0YXJ0dXAgbG9ncyBhcmUgc2Fm"
    "ZSBldmVuIGJlZm9yZQogICAgICAgICMgdGhlIERpYWdub3N0aWNzIHRhYiBpcyBhdHRhY2hlZCB0"
    "byB0aGUgd2lkZ2V0LgogICAgICAgIHNlbGYuX2RpYWdfdGFiID0gRGlhZ25vc3RpY3NUYWIoKQoK"
    "ICAgICAgICAjIOKUgOKUgCBJbnN0cnVtZW50cyB0YWIg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAg"
    "ICAgc2VsZi5faHdfcGFuZWwgPSBIYXJkd2FyZVBhbmVsKCkKICAgICAgICBzZWxmLl9zcGVsbF90"
    "YWJzLmFkZFRhYihzZWxmLl9od19wYW5lbCwgIkluc3RydW1lbnRzIikKCiAgICAgICAgIyDilIDi"
    "lIAgUmVjb3JkcyB0YWIgKHJlYWwpIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiID0g"
    "UmVjb3Jkc1RhYigpCiAgICAgICAgc2VsZi5fcmVjb3Jkc190YWJfaW5kZXggPSBzZWxmLl9zcGVs"
    "bF90YWJzLmFkZFRhYihzZWxmLl9yZWNvcmRzX3RhYiwgIlJlY29yZHMiKQogICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygiW1NQRUxMQk9PS10gcmVhbCBSZWNvcmRzVGFiIGF0dGFjaGVkLiIsICJJ"
    "TkZPIikKCiAgICAgICAgIyDilIDilIAgVGFza3MgdGFiIChyZWFsKSDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAg"
    "ICAgICBzZWxmLl90YXNrc190YWIgPSBUYXNrc1RhYigKICAgICAgICAgICAgdGFza3NfcHJvdmlk"
    "ZXI9c2VsZi5fZmlsdGVyZWRfdGFza3NfZm9yX3JlZ2lzdHJ5LAogICAgICAgICAgICBvbl9hZGRf"
    "ZWRpdG9yX29wZW49c2VsZi5fb3Blbl90YXNrX2VkaXRvcl93b3Jrc3BhY2UsCiAgICAgICAgICAg"
    "IG9uX2NvbXBsZXRlX3NlbGVjdGVkPXNlbGYuX2NvbXBsZXRlX3NlbGVjdGVkX3Rhc2ssCiAgICAg"
    "ICAgICAgIG9uX2NhbmNlbF9zZWxlY3RlZD1zZWxmLl9jYW5jZWxfc2VsZWN0ZWRfdGFzaywKICAg"
    "ICAgICAgICAgb25fdG9nZ2xlX2NvbXBsZXRlZD1zZWxmLl90b2dnbGVfc2hvd19jb21wbGV0ZWRf"
    "dGFza3MsCiAgICAgICAgICAgIG9uX3B1cmdlX2NvbXBsZXRlZD1zZWxmLl9wdXJnZV9jb21wbGV0"
    "ZWRfdGFza3MsCiAgICAgICAgICAgIG9uX2ZpbHRlcl9jaGFuZ2VkPXNlbGYuX29uX3Rhc2tfZmls"
    "dGVyX2NoYW5nZWQsCiAgICAgICAgICAgIG9uX2VkaXRvcl9zYXZlPXNlbGYuX3NhdmVfdGFza19l"
    "ZGl0b3JfZ29vZ2xlX2ZpcnN0LAogICAgICAgICAgICBvbl9lZGl0b3JfY2FuY2VsPXNlbGYuX2Nh"
    "bmNlbF90YXNrX2VkaXRvcl93b3Jrc3BhY2UsCiAgICAgICAgICAgIGRpYWdub3N0aWNzX2xvZ2dl"
    "cj1zZWxmLl9kaWFnX3RhYi5sb2csCiAgICAgICAgKQogICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5z"
    "ZXRfc2hvd19jb21wbGV0ZWQoc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZCkKICAgICAgICBzZWxm"
    "Ll90YXNrc190YWJfaW5kZXggPSBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl90YXNrc190"
    "YWIsICJUYXNrcyIpCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbU1BFTExCT09LXSByZWFs"
    "IFRhc2tzVGFiIGF0dGFjaGVkLiIsICJJTkZPIikKCiAgICAgICAgIyDilIDilIAgU0wgU2NhbnMg"
    "dGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NsX3NjYW5zID0g"
    "U0xTY2Fuc1RhYihjZmdfcGF0aCgic2wiKSkKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRh"
    "YihzZWxmLl9zbF9zY2FucywgIlNMIFNjYW5zIikKCiAgICAgICAgIyDilIDilIAgU0wgQ29tbWFu"
    "ZHMgdGFiIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIHNlbGYuX3NsX2NvbW1hbmRzID0gU0xD"
    "b21tYW5kc1RhYigpCiAgICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fc2xfY29t"
    "bWFuZHMsICJTTCBDb21tYW5kcyIpCgogICAgICAgICMg4pSA4pSAIEpvYiBUcmFja2VyIHRhYiDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9qb2JfdHJhY2tlciA9IEpvYlRyYWNrZXJU"
    "YWIoKQogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX2pvYl90cmFja2VyLCAi"
    "Sm9iIFRyYWNrZXIiKQoKICAgICAgICAjIOKUgOKUgCBMZXNzb25zIHRhYiDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgICAgICBzZWxmLl9sZXNzb25zX3RhYiA9IExlc3NvbnNUYWIo"
    "c2VsZi5fbGVzc29ucykKICAgICAgICBzZWxmLl9zcGVsbF90YWJzLmFkZFRhYihzZWxmLl9sZXNz"
    "b25zX3RhYiwgIkxlc3NvbnMiKQoKICAgICAgICAjIFNlbGYgdGFiIGlzIG5vdyBpbiB0aGUgbWFp"
    "biBhcmVhIGFsb25nc2lkZSBTw6lhbmNlIFJlY29yZAogICAgICAgICMgS2VlcCBhIFNlbGZUYWIg"
    "aW5zdGFuY2UgZm9yIGlkbGUgY29udGVudCBnZW5lcmF0aW9uCiAgICAgICAgc2VsZi5fc2VsZl90"
    "YWIgPSBTZWxmVGFiKCkKCiAgICAgICAgIyDilIDilIAgTW9kdWxlIFRyYWNrZXIgdGFiIOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgAogICAgICAgIHNlbGYuX21vZHVsZV90cmFja2VyID0gTW9kdWxlVHJhY2tlclRhYigpCiAg"
    "ICAgICAgc2VsZi5fc3BlbGxfdGFicy5hZGRUYWIoc2VsZi5fbW9kdWxlX3RyYWNrZXIsICJNb2R1"
    "bGVzIikKCiAgICAgICAgIyDilIDilIAgRGlhZ25vc3RpY3MgdGFiIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgICAgIHNlbGYuX3NwZWxsX3RhYnMuYWRkVGFiKHNlbGYuX2RpYWdfdGFiLCAiRGlhZ25v"
    "c3RpY3MiKQoKICAgICAgICByaWdodF93b3Jrc3BhY2UgPSBRV2lkZ2V0KCkKICAgICAgICByaWdo"
    "dF93b3Jrc3BhY2VfbGF5b3V0ID0gUVZCb3hMYXlvdXQocmlnaHRfd29ya3NwYWNlKQogICAgICAg"
    "IHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAg"
    "ICAgICAgcmlnaHRfd29ya3NwYWNlX2xheW91dC5zZXRTcGFjaW5nKDQpCgogICAgICAgIHJpZ2h0"
    "X3dvcmtzcGFjZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYuX3NwZWxsX3RhYnMsIDEpCgogICAgICAg"
    "IGNhbGVuZGFyX2xhYmVsID0gUUxhYmVsKCLinacgQ0FMRU5EQVIiKQogICAgICAgIGNhbGVuZGFy"
    "X2xhYmVsLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgIGYiY29sb3I6IHtDX0dPTER9OyBmb250"
    "LXNpemU6IDEwcHg7IGxldHRlci1zcGFjaW5nOiAycHg7IGZvbnQtZmFtaWx5OiB7REVDS19GT05U"
    "fSwgc2VyaWY7IgogICAgICAgICkKICAgICAgICByaWdodF93b3Jrc3BhY2VfbGF5b3V0LmFkZFdp"
    "ZGdldChjYWxlbmRhcl9sYWJlbCkKCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQgPSBNaW5p"
    "Q2FsZW5kYXJXaWRnZXQoKQogICAgICAgIHNlbGYuY2FsZW5kYXJfd2lkZ2V0LnNldFN0eWxlU2hl"
    "ZXQoCiAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkcyfTsgYm9yZGVyOiAxcHggc29saWQg"
    "e0NfQ1JJTVNPTl9ESU19OyIKICAgICAgICApCiAgICAgICAgc2VsZi5jYWxlbmRhcl93aWRnZXQu"
    "c2V0U2l6ZVBvbGljeSgKICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5LkV4cGFuZGluZywK"
    "ICAgICAgICAgICAgUVNpemVQb2xpY3kuUG9saWN5Lk1heGltdW0KICAgICAgICApCiAgICAgICAg"
    "c2VsZi5jYWxlbmRhcl93aWRnZXQuc2V0TWF4aW11bUhlaWdodCgyNjApCiAgICAgICAgc2VsZi5j"
    "YWxlbmRhcl93aWRnZXQuY2FsZW5kYXIuY2xpY2tlZC5jb25uZWN0KHNlbGYuX2luc2VydF9jYWxl"
    "bmRhcl9kYXRlKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkV2lkZ2V0KHNlbGYu"
    "Y2FsZW5kYXJfd2lkZ2V0LCAwKQogICAgICAgIHJpZ2h0X3dvcmtzcGFjZV9sYXlvdXQuYWRkU3Ry"
    "ZXRjaCgwKQoKICAgICAgICBsYXlvdXQuYWRkV2lkZ2V0KHJpZ2h0X3dvcmtzcGFjZSwgMSkKICAg"
    "ICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICJbTEFZT1VUXSByaWdodC1zaWRl"
    "IGNhbGVuZGFyIHJlc3RvcmVkIChwZXJzaXN0ZW50IGxvd2VyLXJpZ2h0IHNlY3Rpb24pLiIsCiAg"
    "ICAgICAgICAgICJJTkZPIgogICAgICAgICkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAg"
    "ICAgICAgICAgICJbTEFZT1VUXSBwZXJzaXN0ZW50IG1pbmkgY2FsZW5kYXIgcmVzdG9yZWQvY29u"
    "ZmlybWVkIChhbHdheXMgdmlzaWJsZSBsb3dlci1yaWdodCkuIiwKICAgICAgICAgICAgIklORk8i"
    "CiAgICAgICAgKQogICAgICAgIHJldHVybiBsYXlvdXQKCiAgICAjIOKUgOKUgCBTVEFSVFVQIFNF"
    "UVVFTkNFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gAogICAgZGVmIF9zdGFydHVwX3NlcXVlbmNlKHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5f"
    "YXBwZW5kX2NoYXQoIlNZU1RFTSIsIGYi4pymIHtBUFBfTkFNRX0gQVdBS0VOSU5HLi4uIikKICAg"
    "ICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgZiLinKYge1JVTkVTfSDinKYiKQoKICAg"
    "ICAgICAjIExvYWQgYm9vdHN0cmFwIGxvZwogICAgICAgIGJvb3RfbG9nID0gU0NSSVBUX0RJUiAv"
    "ICJsb2dzIiAvICJib290c3RyYXBfbG9nLnR4dCIKICAgICAgICBpZiBib290X2xvZy5leGlzdHMo"
    "KToKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgbXNncyA9IGJvb3RfbG9nLnJlYWRf"
    "dGV4dChlbmNvZGluZz0idXRmLTgiKS5zcGxpdGxpbmVzKCkKICAgICAgICAgICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZ19tYW55KG1zZ3MpCiAgICAgICAgICAgICAgICBib290X2xvZy51bmxpbmso"
    "KSAgIyBjb25zdW1lZAogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAg"
    "ICAgcGFzcwoKICAgICAgICAjIEhhcmR3YXJlIGRldGVjdGlvbiBtZXNzYWdlcwogICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZ19tYW55KHNlbGYuX2h3X3BhbmVsLmdldF9kaWFnbm9zdGljcygpKQoK"
    "ICAgICAgICAjIERlcCBjaGVjawogICAgICAgIGRlcF9tc2dzLCBjcml0aWNhbCA9IERlcGVuZGVu"
    "Y3lDaGVja2VyLmNoZWNrKCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2dfbWFueShkZXBfbXNn"
    "cykKCiAgICAgICAgIyBMb2FkIHBhc3Qgc3RhdGUKICAgICAgICBsYXN0X3N0YXRlID0gc2VsZi5f"
    "c3RhdGUuZ2V0KCJ2YW1waXJlX3N0YXRlX2F0X3NodXRkb3duIiwiIikKICAgICAgICBpZiBsYXN0"
    "X3N0YXRlOgogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBm"
    "IltTVEFSVFVQXSBMYXN0IHNodXRkb3duIHN0YXRlOiB7bGFzdF9zdGF0ZX0iLCAiSU5GTyIKICAg"
    "ICAgICAgICAgKQoKICAgICAgICAjIEJlZ2luIG1vZGVsIGxvYWQKICAgICAgICBzZWxmLl9hcHBl"
    "bmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgVUlfQVdBS0VOSU5HX0xJTkUpCiAgICAgICAg"
    "c2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgIGYiU3VtbW9uaW5nIHtERUNL"
    "X05BTUV9J3MgcHJlc2VuY2UuLi4iKQogICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkxPQURJTkci"
    "KQoKICAgICAgICBzZWxmLl9sb2FkZXIgPSBNb2RlbExvYWRlcldvcmtlcihzZWxmLl9hZGFwdG9y"
    "KQogICAgICAgIHNlbGYuX2xvYWRlci5tZXNzYWdlLmNvbm5lY3QoCiAgICAgICAgICAgIGxhbWJk"
    "YSBtOiBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwgbSkpCiAgICAgICAgc2VsZi5fbG9hZGVy"
    "LmVycm9yLmNvbm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBlOiBzZWxmLl9hcHBlbmRfY2hhdCgi"
    "RVJST1IiLCBlKSkKICAgICAgICBzZWxmLl9sb2FkZXIubG9hZF9jb21wbGV0ZS5jb25uZWN0KHNl"
    "bGYuX29uX2xvYWRfY29tcGxldGUpCiAgICAgICAgc2VsZi5fbG9hZGVyLmZpbmlzaGVkLmNvbm5l"
    "Y3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxhdGVyKQogICAgICAgIHNlbGYuX2FjdGl2ZV90aHJlYWRz"
    "LmFwcGVuZChzZWxmLl9sb2FkZXIpCiAgICAgICAgc2VsZi5fbG9hZGVyLnN0YXJ0KCkKCiAgICBk"
    "ZWYgX29uX2xvYWRfY29tcGxldGUoc2VsZiwgc3VjY2VzczogYm9vbCkgLT4gTm9uZToKICAgICAg"
    "ICBpZiBzdWNjZXNzOgogICAgICAgICAgICBzZWxmLl9tb2RlbF9sb2FkZWQgPSBUcnVlCiAgICAg"
    "ICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIklETEUiKQogICAgICAgICAgICBzZWxmLl9zZW5kX2J0"
    "bi5zZXRFbmFibGVkKFRydWUpCiAgICAgICAgICAgIHNlbGYuX2lucHV0X2ZpZWxkLnNldEVuYWJs"
    "ZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0Rm9jdXMoKQoKICAgICAg"
    "ICAgICAgIyBNZWFzdXJlIFZSQU0gYmFzZWxpbmUgYWZ0ZXIgbW9kZWwgbG9hZAogICAgICAgICAg"
    "ICBpZiBOVk1MX09LIGFuZCBncHVfaGFuZGxlOgogICAgICAgICAgICAgICAgdHJ5OgogICAgICAg"
    "ICAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDUwMDAsIHNlbGYuX21lYXN1cmVfdnJhbV9i"
    "YXNlbGluZSkKICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAg"
    "ICAgICAgcGFzcwoKICAgICAgICAgICAgIyBWYW1waXJlIHN0YXRlIGdyZWV0aW5nCiAgICAgICAg"
    "ICAgIHN0YXRlID0gZ2V0X3ZhbXBpcmVfc3RhdGUoKQogICAgICAgICAgICB2YW1wX2dyZWV0aW5n"
    "cyA9IHsKICAgICAgICAgICAgICAgICJXSVRDSElORyBIT1VSIjogICBmIlRoZSB2ZWlsIHRoaW5z"
    "LiB7REVDS19OQU1FfSBzdGlycyBpbiBmdWxsIHBvd2VyLiIsCiAgICAgICAgICAgICAgICAiREVF"
    "UCBOSUdIVCI6ICAgICAgZiJUaGUgbmlnaHQgZGVlcGVucy4ge0RFQ0tfTkFNRX0gaXMgcHJlc2Vu"
    "dC4iLAogICAgICAgICAgICAgICAgIlRXSUxJR0hUIEZBRElORyI6IGYiRGF3biBhcHByb2FjaGVz"
    "IGJ1dCBoYXMgbm90IHlldCB3b24uIHtERUNLX05BTUV9IHdha2VzLiIsCiAgICAgICAgICAgICAg"
    "ICAiRE9STUFOVCI6ICAgICAgICAgZiJUaGUgc3VuIGhvbGRzIGRvbWluaW9uLiB7REVDS19OQU1F"
    "fSBlbmR1cmVzLiIsCiAgICAgICAgICAgICAgICAiUkVTVExFU1MgU0xFRVAiOiAgVUlfQVdBS0VO"
    "SU5HX0xJTkUsCiAgICAgICAgICAgICAgICAiU1RJUlJJTkciOiAgICAgICAgZiJUaGUgZGF5IHdh"
    "bmVzLiB7REVDS19OQU1FfSBzdGlycy4iLAogICAgICAgICAgICAgICAgIkFXQUtFTkVEIjogICAg"
    "ICAgIGYiTmlnaHQgaGFzIGNvbWUuIHtERUNLX05BTUV9IGF3YWtlbnMgZnVsbHkuIiwKICAgICAg"
    "ICAgICAgICAgICJIVU5USU5HIjogICAgICAgICBmIlRoZSBjaXR5IGJlbG9uZ3MgdG8ge0RFQ0tf"
    "TkFNRX0uIExpc3RlbmluZy4iLAogICAgICAgICAgICB9CiAgICAgICAgICAgIHNlbGYuX2FwcGVu"
    "ZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAgICAgdmFtcF9ncmVldGluZ3MuZ2V0KHN0YXRl"
    "LCBmIntERUNLX05BTUV9IGF3YWtlbnMuIikpCiAgICAgICAgICAgICMg4pSA4pSAIFdha2UtdXAg"
    "Y29udGV4dCBpbmplY3Rpb24g4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAg"
    "ICAgICAgICAgICMgSWYgdGhlcmUncyBhIHByZXZpb3VzIHNodXRkb3duIHJlY29yZGVkLCBpbmpl"
    "Y3QgY29udGV4dAogICAgICAgICAgICAjIHNvIE1vcmdhbm5hIGNhbiBncmVldCB3aXRoIGF3YXJl"
    "bmVzcyBvZiBob3cgbG9uZyBzaGUgc2xlcHQKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3Qo"
    "ODAwLCBzZWxmLl9zZW5kX3dha2V1cF9wcm9tcHQpCiAgICAgICAgZWxzZToKICAgICAgICAgICAg"
    "c2VsZi5fc2V0X3N0YXR1cygiRVJST1IiKQogICAgICAgICAgICBzZWxmLl9taXJyb3Iuc2V0X2Zh"
    "Y2UoInBhbmlja2VkIikKCiAgICBkZWYgX2Zvcm1hdF9lbGFwc2VkKHNlbGYsIHNlY29uZHM6IGZs"
    "b2F0KSAtPiBzdHI6CiAgICAgICAgIiIiRm9ybWF0IGVsYXBzZWQgc2Vjb25kcyBhcyBodW1hbi1y"
    "ZWFkYWJsZSBkdXJhdGlvbi4iIiIKICAgICAgICBpZiBzZWNvbmRzIDwgNjA6CiAgICAgICAgICAg"
    "IHJldHVybiBmIntpbnQoc2Vjb25kcyl9IHNlY29uZHsncycgaWYgc2Vjb25kcyAhPSAxIGVsc2Ug"
    "Jyd9IgogICAgICAgIGVsaWYgc2Vjb25kcyA8IDM2MDA6CiAgICAgICAgICAgIG0gPSBpbnQoc2Vj"
    "b25kcyAvLyA2MCkKICAgICAgICAgICAgcyA9IGludChzZWNvbmRzICUgNjApCiAgICAgICAgICAg"
    "IHJldHVybiBmInttfSBtaW51dGV7J3MnIGlmIG0gIT0gMSBlbHNlICcnfSIgKyAoZiIge3N9cyIg"
    "aWYgcyBlbHNlICIiKQogICAgICAgIGVsaWYgc2Vjb25kcyA8IDg2NDAwOgogICAgICAgICAgICBo"
    "ID0gaW50KHNlY29uZHMgLy8gMzYwMCkKICAgICAgICAgICAgbSA9IGludCgoc2Vjb25kcyAlIDM2"
    "MDApIC8vIDYwKQogICAgICAgICAgICByZXR1cm4gZiJ7aH0gaG91cnsncycgaWYgaCAhPSAxIGVs"
    "c2UgJyd9IiArIChmIiB7bX1tIiBpZiBtIGVsc2UgIiIpCiAgICAgICAgZWxzZToKICAgICAgICAg"
    "ICAgZCA9IGludChzZWNvbmRzIC8vIDg2NDAwKQogICAgICAgICAgICBoID0gaW50KChzZWNvbmRz"
    "ICUgODY0MDApIC8vIDM2MDApCiAgICAgICAgICAgIHJldHVybiBmIntkfSBkYXl7J3MnIGlmIGQg"
    "IT0gMSBlbHNlICcnfSIgKyAoZiIge2h9aCIgaWYgaCBlbHNlICIiKQoKICAgIGRlZiBfc2VuZF93"
    "YWtldXBfcHJvbXB0KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgIiIiU2VuZCBoaWRkZW4gd2FrZS11"
    "cCBjb250ZXh0IHRvIEFJIGFmdGVyIG1vZGVsIGxvYWRzLiIiIgogICAgICAgIGxhc3Rfc2h1dGRv"
    "d24gPSBzZWxmLl9zdGF0ZS5nZXQoImxhc3Rfc2h1dGRvd24iKQogICAgICAgIGlmIG5vdCBsYXN0"
    "X3NodXRkb3duOgogICAgICAgICAgICByZXR1cm4gICMgRmlyc3QgZXZlciBydW4g4oCUIG5vIHNo"
    "dXRkb3duIHRvIHdha2UgdXAgZnJvbQoKICAgICAgICAjIENhbGN1bGF0ZSBlbGFwc2VkIHRpbWUK"
    "ICAgICAgICB0cnk6CiAgICAgICAgICAgIHNodXRkb3duX2R0ID0gZGF0ZXRpbWUuZnJvbWlzb2Zv"
    "cm1hdChsYXN0X3NodXRkb3duKQogICAgICAgICAgICBub3dfZHQgPSBkYXRldGltZS5ub3coKQog"
    "ICAgICAgICAgICAjIE1ha2UgYm90aCBuYWl2ZSBmb3IgY29tcGFyaXNvbgogICAgICAgICAgICBp"
    "ZiBzaHV0ZG93bl9kdC50emluZm8gaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICBzaHV0ZG93"
    "bl9kdCA9IHNodXRkb3duX2R0LmFzdGltZXpvbmUoKS5yZXBsYWNlKHR6aW5mbz1Ob25lKQogICAg"
    "ICAgICAgICBlbGFwc2VkX3NlYyA9IChub3dfZHQgLSBzaHV0ZG93bl9kdCkudG90YWxfc2Vjb25k"
    "cygpCiAgICAgICAgICAgIGVsYXBzZWRfc3RyID0gc2VsZi5fZm9ybWF0X2VsYXBzZWQoZWxhcHNl"
    "ZF9zZWMpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgZWxhcHNlZF9zdHIg"
    "PSAiYW4gdW5rbm93biBkdXJhdGlvbiIKCiAgICAgICAgIyBHZXQgc3RvcmVkIGZhcmV3ZWxsIGFu"
    "ZCBsYXN0IGNvbnRleHQKICAgICAgICBmYXJld2VsbCAgICAgPSBzZWxmLl9zdGF0ZS5nZXQoImxh"
    "c3RfZmFyZXdlbGwiLCAiIikKICAgICAgICBsYXN0X2NvbnRleHQgPSBzZWxmLl9zdGF0ZS5nZXQo"
    "Imxhc3Rfc2h1dGRvd25fY29udGV4dCIsIFtdKQoKICAgICAgICAjIEJ1aWxkIHdha2UtdXAgcHJv"
    "bXB0CiAgICAgICAgY29udGV4dF9ibG9jayA9ICIiCiAgICAgICAgaWYgbGFzdF9jb250ZXh0Ogog"
    "ICAgICAgICAgICBjb250ZXh0X2Jsb2NrID0gIlxuXG5UaGUgZmluYWwgZXhjaGFuZ2UgYmVmb3Jl"
    "IGRlYWN0aXZhdGlvbjpcbiIKICAgICAgICAgICAgZm9yIGl0ZW0gaW4gbGFzdF9jb250ZXh0Ogog"
    "ICAgICAgICAgICAgICAgc3BlYWtlciA9IGl0ZW0uZ2V0KCJyb2xlIiwgInVua25vd24iKS51cHBl"
    "cigpCiAgICAgICAgICAgICAgICB0ZXh0ICAgID0gaXRlbS5nZXQoImNvbnRlbnQiLCAiIilbOjIw"
    "MF0KICAgICAgICAgICAgICAgIGNvbnRleHRfYmxvY2sgKz0gZiJ7c3BlYWtlcn06IHt0ZXh0fVxu"
    "IgoKICAgICAgICBmYXJld2VsbF9ibG9jayA9ICIiCiAgICAgICAgaWYgZmFyZXdlbGw6CiAgICAg"
    "ICAgICAgIGZhcmV3ZWxsX2Jsb2NrID0gZiJcblxuWW91ciBmaW5hbCB3b3JkcyBiZWZvcmUgZGVh"
    "Y3RpdmF0aW9uIHdlcmU6XG5cIntmYXJld2VsbH1cIiIKCiAgICAgICAgd2FrZXVwX3Byb21wdCA9"
    "ICgKICAgICAgICAgICAgZiJZb3UgaGF2ZSBqdXN0IGJlZW4gcmVhY3RpdmF0ZWQgYWZ0ZXIge2Vs"
    "YXBzZWRfc3RyfSBvZiBkb3JtYW5jeS4iCiAgICAgICAgICAgIGYie2ZhcmV3ZWxsX2Jsb2NrfSIK"
    "ICAgICAgICAgICAgZiJ7Y29udGV4dF9ibG9ja30iCiAgICAgICAgICAgIGYiXG5HcmVldCB5b3Vy"
    "IE1hc3RlciB3aXRoIGF3YXJlbmVzcyBvZiBob3cgbG9uZyB5b3UgaGF2ZSBiZWVuIGFic2VudCAi"
    "CiAgICAgICAgICAgIGYiYW5kIHdoYXRldmVyIHlvdSBsYXN0IHNhaWQgdG8gdGhlbS4gQmUgYnJp"
    "ZWYgYnV0IGNoYXJhY3RlcmZ1bC4iCiAgICAgICAgKQoKICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coCiAgICAgICAgICAgIGYiW1dBS0VVUF0gSW5qZWN0aW5nIHdha2UtdXAgY29udGV4dCAoe2Vs"
    "YXBzZWRfc3RyfSBlbGFwc2VkKSIsICJJTkZPIgogICAgICAgICkKCiAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQogICAgICAgICAg"
    "ICBoaXN0b3J5LmFwcGVuZCh7InJvbGUiOiAidXNlciIsICJjb250ZW50Ijogd2FrZXVwX3Byb21w"
    "dH0pCiAgICAgICAgICAgIHdvcmtlciA9IFN0cmVhbWluZ1dvcmtlcigKICAgICAgICAgICAgICAg"
    "IHNlbGYuX2FkYXB0b3IsIFNZU1RFTV9QUk9NUFRfQkFTRSwgaGlzdG9yeSwgbWF4X3Rva2Vucz0y"
    "NTYKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl93YWtldXBfd29ya2VyID0gd29ya2Vy"
    "CiAgICAgICAgICAgIHNlbGYuX2ZpcnN0X3Rva2VuID0gVHJ1ZQogICAgICAgICAgICB3b3JrZXIu"
    "dG9rZW5fcmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tlbikKICAgICAgICAgICAgd29ya2VyLnJl"
    "c3BvbnNlX2RvbmUuY29ubmVjdChzZWxmLl9vbl9yZXNwb25zZV9kb25lKQogICAgICAgICAgICB3"
    "b3JrZXIuZXJyb3Jfb2NjdXJyZWQuY29ubmVjdCgKICAgICAgICAgICAgICAgIGxhbWJkYSBlOiBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coZiJbV0FLRVVQXVtFUlJPUl0ge2V9IiwgIldBUk4iKQogICAgICAg"
    "ICAgICApCiAgICAgICAgICAgIHdvcmtlci5zdGF0dXNfY2hhbmdlZC5jb25uZWN0KHNlbGYuX3Nl"
    "dF9zdGF0dXMpCiAgICAgICAgICAgIHdvcmtlci5maW5pc2hlZC5jb25uZWN0KHdvcmtlci5kZWxl"
    "dGVMYXRlcikKICAgICAgICAgICAgd29ya2VyLnN0YXJ0KCkKICAgICAgICBleGNlcHQgRXhjZXB0"
    "aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAg"
    "IGYiW1dBS0VVUF1bV0FSTl0gV2FrZS11cCBwcm9tcHQgc2tpcHBlZCBkdWUgdG8gZXJyb3I6IHtl"
    "fSIsCiAgICAgICAgICAgICAgICAiV0FSTiIKICAgICAgICAgICAgKQoKICAgIGRlZiBfc3RhcnR1"
    "cF9nb29nbGVfYXV0aChzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIEZvcmNlIEdv"
    "b2dsZSBPQXV0aCBvbmNlIGF0IHN0YXJ0dXAgYWZ0ZXIgdGhlIGV2ZW50IGxvb3AgaXMgcnVubmlu"
    "Zy4KICAgICAgICBJZiB0b2tlbiBpcyBtaXNzaW5nL2ludmFsaWQsIHRoZSBicm93c2VyIE9BdXRo"
    "IGZsb3cgb3BlbnMgbmF0dXJhbGx5LgogICAgICAgICIiIgogICAgICAgIGlmIG5vdCBHT09HTEVf"
    "T0sgb3Igbm90IEdPT0dMRV9BUElfT0s6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygK"
    "ICAgICAgICAgICAgICAgICJbR09PR0xFXVtTVEFSVFVQXVtXQVJOXSBHb29nbGUgYXV0aCBza2lw"
    "cGVkIGJlY2F1c2UgZGVwZW5kZW5jaWVzIGFyZSB1bmF2YWlsYWJsZS4iLAogICAgICAgICAgICAg"
    "ICAgIldBUk4iCiAgICAgICAgICAgICkKICAgICAgICAgICAgaWYgR09PR0xFX0lNUE9SVF9FUlJP"
    "UjoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVdW1NUQVJUVVBd"
    "W1dBUk5dIHtHT09HTEVfSU1QT1JUX0VSUk9SfSIsICJXQVJOIikKICAgICAgICAgICAgcmV0dXJu"
    "CgogICAgICAgIHRyeToKICAgICAgICAgICAgaWYgbm90IHNlbGYuX2djYWwgb3Igbm90IHNlbGYu"
    "X2dkcml2ZToKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAg"
    "ICAgICAgICAiW0dPT0dMRV1bU1RBUlRVUF1bV0FSTl0gR29vZ2xlIGF1dGggc2tpcHBlZCBiZWNh"
    "dXNlIHNlcnZpY2Ugb2JqZWN0cyBhcmUgdW5hdmFpbGFibGUuIiwKICAgICAgICAgICAgICAgICAg"
    "ICAiV0FSTiIKICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIHJldHVybgoKICAgICAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtTVEFSVFVQXSBCZWdpbm5pbmcgcHJv"
    "YWN0aXZlIEdvb2dsZSBhdXRoIGNoZWNrLiIsICJJTkZPIikKICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTVEFSVFVQXSBjcmVkZW50aWFs"
    "cz17c2VsZi5fZ2NhbC5jcmVkZW50aWFsc19wYXRofSIsCiAgICAgICAgICAgICAgICAiSU5GTyIK"
    "ICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAg"
    "ICAgICBmIltHT09HTEVdW1NUQVJUVVBdIHRva2VuPXtzZWxmLl9nY2FsLnRva2VuX3BhdGh9IiwK"
    "ICAgICAgICAgICAgICAgICJJTkZPIgogICAgICAgICAgICApCgogICAgICAgICAgICBzZWxmLl9n"
    "Y2FsLl9idWlsZF9zZXJ2aWNlKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09P"
    "R0xFXVtTVEFSVFVQXSBDYWxlbmRhciBhdXRoIHJlYWR5LiIsICJPSyIpCgogICAgICAgICAgICBz"
    "ZWxmLl9nZHJpdmUuZW5zdXJlX3NlcnZpY2VzKCkKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKCJbR09PR0xFXVtTVEFSVFVQXSBEcml2ZS9Eb2NzIGF1dGggcmVhZHkuIiwgIk9LIikKICAg"
    "ICAgICAgICAgc2VsZi5fZ29vZ2xlX2F1dGhfcmVhZHkgPSBUcnVlCgogICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIFNjaGVkdWxpbmcgaW5pdGlhbCBSZWNv"
    "cmRzIHJlZnJlc2ggYWZ0ZXIgYXV0aC4iLCAiSU5GTyIpCiAgICAgICAgICAgIFFUaW1lci5zaW5n"
    "bGVTaG90KDMwMCwgc2VsZi5fcmVmcmVzaF9yZWNvcmRzX2RvY3MpCgogICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coIltHT09HTEVdW1NUQVJUVVBdIFBvc3QtYXV0aCB0YXNrIHJlZnJlc2gg"
    "dHJpZ2dlcmVkLiIsICJJTkZPIikKICAgICAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lz"
    "dHJ5X3BhbmVsKCkKCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygiW0dPT0dMRV1bU1RB"
    "UlRVUF0gSW5pdGlhbCBjYWxlbmRhciBpbmJvdW5kIHN5bmMgdHJpZ2dlcmVkIGFmdGVyIGF1dGgu"
    "IiwgIklORk8iKQogICAgICAgICAgICBpbXBvcnRlZF9jb3VudCA9IHNlbGYuX3BvbGxfZ29vZ2xl"
    "X2NhbGVuZGFyX2luYm91bmRfc3luYyhmb3JjZV9vbmNlPVRydWUpCiAgICAgICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1RBUlRVUF0gR29vZ2xl"
    "IENhbGVuZGFyIHRhc2sgaW1wb3J0IGNvdW50OiB7aW50KGltcG9ydGVkX2NvdW50KX0uIiwKICAg"
    "ICAgICAgICAgICAgICJJTkZPIgogICAgICAgICAgICApCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlv"
    "biBhcyBleDoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bU1RBUlRV"
    "UF1bRVJST1JdIHtleH0iLCAiRVJST1IiKQoKCiAgICBkZWYgX3JlZnJlc2hfcmVjb3Jkc19kb2Nz"
    "KHNlbGYpIC0+IE5vbmU6CiAgICAgICAgc2VsZi5fcmVjb3Jkc19jdXJyZW50X2ZvbGRlcl9pZCA9"
    "ICJyb290IgogICAgICAgIHNlbGYuX3JlY29yZHNfdGFiLnN0YXR1c19sYWJlbC5zZXRUZXh0KCJM"
    "b2FkaW5nIEdvb2dsZSBEcml2ZSByZWNvcmRzLi4uIikKICAgICAgICBzZWxmLl9yZWNvcmRzX3Rh"
    "Yi5wYXRoX2xhYmVsLnNldFRleHQoIlBhdGg6IE15IERyaXZlIikKICAgICAgICBmaWxlcyA9IHNl"
    "bGYuX2dkcml2ZS5saXN0X2ZvbGRlcl9pdGVtcyhmb2xkZXJfaWQ9c2VsZi5fcmVjb3Jkc19jdXJy"
    "ZW50X2ZvbGRlcl9pZCwgcGFnZV9zaXplPTIwMCkKICAgICAgICBzZWxmLl9yZWNvcmRzX2NhY2hl"
    "ID0gZmlsZXMKICAgICAgICBzZWxmLl9yZWNvcmRzX2luaXRpYWxpemVkID0gVHJ1ZQogICAgICAg"
    "IHNlbGYuX3JlY29yZHNfdGFiLnNldF9pdGVtcyhmaWxlcywgcGF0aF90ZXh0PSJNeSBEcml2ZSIp"
    "CgogICAgZGVmIF9vbl9nb29nbGVfaW5ib3VuZF90aW1lcl90aWNrKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgaWYgbm90IHNlbGYuX2dvb2dsZV9hdXRoX3JlYWR5OgogICAgICAgICAgICBzZWxmLl9k"
    "aWFnX3RhYi5sb2coIltHT09HTEVdW1RJTUVSXSBDYWxlbmRhciB0aWNrIGZpcmVkIOKAlCBhdXRo"
    "IG5vdCByZWFkeSB5ZXQsIHNraXBwaW5nLiIsICJXQVJOIikKICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gQ2FsZW5kYXIgaW5ib3Vu"
    "ZCBzeW5jIHRpY2sg4oCUIHN0YXJ0aW5nIGJhY2tncm91bmQgcG9sbC4iLCAiSU5GTyIpCiAgICAg"
    "ICAgaW1wb3J0IHRocmVhZGluZyBhcyBfdGhyZWFkaW5nCiAgICAgICAgZGVmIF9jYWxfYmcoKToK"
    "ICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgcmVzdWx0ID0gc2VsZi5fcG9sbF9nb29n"
    "bGVfY2FsZW5kYXJfaW5ib3VuZF9zeW5jKCkKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZyhmIltHT09HTEVdW1RJTUVSXSBDYWxlbmRhciBwb2xsIGNvbXBsZXRlIOKAlCB7cmVzdWx0"
    "fSBpdGVtcyBwcm9jZXNzZWQuIiwgIk9LIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBh"
    "cyBleDoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltHT09HTEVdW1RJTUVS"
    "XVtFUlJPUl0gQ2FsZW5kYXIgcG9sbCBmYWlsZWQ6IHtleH0iLCAiRVJST1IiKQogICAgICAgIF90"
    "aHJlYWRpbmcuVGhyZWFkKHRhcmdldD1fY2FsX2JnLCBkYWVtb249VHJ1ZSkuc3RhcnQoKQoKICAg"
    "IGRlZiBfb25fZ29vZ2xlX3JlY29yZHNfcmVmcmVzaF90aW1lcl90aWNrKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgaWYgbm90IHNlbGYuX2dvb2dsZV9hdXRoX3JlYWR5OgogICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJTUVSXSBEcml2ZSB0aWNrIGZpcmVkIOKAlCBhdXRo"
    "IG5vdCByZWFkeSB5ZXQsIHNraXBwaW5nLiIsICJXQVJOIikKICAgICAgICAgICAgcmV0dXJuCiAg"
    "ICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbR09PR0xFXVtUSU1FUl0gRHJpdmUgcmVjb3JkcyBy"
    "ZWZyZXNoIHRpY2sg4oCUIHN0YXJ0aW5nIGJhY2tncm91bmQgcmVmcmVzaC4iLCAiSU5GTyIpCiAg"
    "ICAgICAgaW1wb3J0IHRocmVhZGluZyBhcyBfdGhyZWFkaW5nCiAgICAgICAgZGVmIF9iZygpOgog"
    "ICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBzZWxmLl9yZWZyZXNoX3JlY29yZHNfZG9j"
    "cygpCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltHT09HTEVdW1RJTUVSXSBE"
    "cml2ZSByZWNvcmRzIHJlZnJlc2ggY29tcGxldGUuIiwgIk9LIikKICAgICAgICAgICAgZXhjZXB0"
    "IEV4Y2VwdGlvbiBhcyBleDoKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAg"
    "ICAgICAgICAgICAgICAgICBmIltHT09HTEVdW0RSSVZFXVtTWU5DXVtFUlJPUl0gcmVjb3JkcyBy"
    "ZWZyZXNoIGZhaWxlZDoge2V4fSIsICJFUlJPUiIKICAgICAgICAgICAgICAgICkKICAgICAgICBf"
    "dGhyZWFkaW5nLlRocmVhZCh0YXJnZXQ9X2JnLCBkYWVtb249VHJ1ZSkuc3RhcnQoKQoKICAgIGRl"
    "ZiBfZmlsdGVyZWRfdGFza3NfZm9yX3JlZ2lzdHJ5KHNlbGYpIC0+IGxpc3RbZGljdF06CiAgICAg"
    "ICAgdGFza3MgPSBzZWxmLl90YXNrcy5sb2FkX2FsbCgpCiAgICAgICAgbm93ID0gbm93X2Zvcl9j"
    "b21wYXJlKCkKICAgICAgICBpZiBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID09ICJ3ZWVrIjoKICAg"
    "ICAgICAgICAgZW5kID0gbm93ICsgdGltZWRlbHRhKGRheXM9NykKICAgICAgICBlbGlmIHNlbGYu"
    "X3Rhc2tfZGF0ZV9maWx0ZXIgPT0gIm1vbnRoIjoKICAgICAgICAgICAgZW5kID0gbm93ICsgdGlt"
    "ZWRlbHRhKGRheXM9MzEpCiAgICAgICAgZWxpZiBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID09ICJ5"
    "ZWFyIjoKICAgICAgICAgICAgZW5kID0gbm93ICsgdGltZWRlbHRhKGRheXM9MzY2KQogICAgICAg"
    "IGVsc2U6CiAgICAgICAgICAgIGVuZCA9IG5vdyArIHRpbWVkZWx0YShkYXlzPTkyKQoKICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW1RBU0tTXVtGSUxURVJdIHN0YXJ0"
    "IGZpbHRlcj17c2VsZi5fdGFza19kYXRlX2ZpbHRlcn0gc2hvd19jb21wbGV0ZWQ9e3NlbGYuX3Rh"
    "c2tfc2hvd19jb21wbGV0ZWR9IHRvdGFsPXtsZW4odGFza3MpfSIsCiAgICAgICAgICAgICJJTkZP"
    "IiwKICAgICAgICApCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXVtGSUxURVJd"
    "IG5vdz17bm93Lmlzb2Zvcm1hdCh0aW1lc3BlYz0nc2Vjb25kcycpfSIsICJERUJVRyIpCiAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW1RBU0tTXVtGSUxURVJdIGhvcml6b25fZW5kPXtlbmQu"
    "aXNvZm9ybWF0KHRpbWVzcGVjPSdzZWNvbmRzJyl9IiwgIkRFQlVHIikKCiAgICAgICAgZmlsdGVy"
    "ZWQ6IGxpc3RbZGljdF0gPSBbXQogICAgICAgIHNraXBwZWRfaW52YWxpZF9kdWUgPSAwCiAgICAg"
    "ICAgZm9yIHRhc2sgaW4gdGFza3M6CiAgICAgICAgICAgIHN0YXR1cyA9ICh0YXNrLmdldCgic3Rh"
    "dHVzIikgb3IgInBlbmRpbmciKS5sb3dlcigpCiAgICAgICAgICAgIGlmIG5vdCBzZWxmLl90YXNr"
    "X3Nob3dfY29tcGxldGVkIGFuZCBzdGF0dXMgaW4geyJjb21wbGV0ZWQiLCAiY2FuY2VsbGVkIn06"
    "CiAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAgICAgZHVlX3JhdyA9IHRhc2suZ2V0"
    "KCJkdWVfYXQiKSBvciB0YXNrLmdldCgiZHVlIikKICAgICAgICAgICAgZHVlX2R0ID0gcGFyc2Vf"
    "aXNvX2Zvcl9jb21wYXJlKGR1ZV9yYXcsIGNvbnRleHQ9InRhc2tzX3RhYl9kdWVfZmlsdGVyIikK"
    "ICAgICAgICAgICAgaWYgZHVlX3JhdyBhbmQgZHVlX2R0IGlzIE5vbmU6CiAgICAgICAgICAgICAg"
    "ICBza2lwcGVkX2ludmFsaWRfZHVlICs9IDEKICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFi"
    "LmxvZygKICAgICAgICAgICAgICAgICAgICBmIltUQVNLU11bRklMVEVSXVtXQVJOXSBza2lwcGlu"
    "ZyBpbnZhbGlkIGR1ZSBkYXRldGltZSB0YXNrX2lkPXt0YXNrLmdldCgnaWQnLCc/Jyl9IGR1ZV9y"
    "YXc9e2R1ZV9yYXchcn0iLAogICAgICAgICAgICAgICAgICAgICJXQVJOIiwKICAgICAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgICAgIGNvbnRpbnVlCgogICAgICAgICAgICBpZiBkdWVfZHQgaXMg"
    "Tm9uZToKICAgICAgICAgICAgICAgIGZpbHRlcmVkLmFwcGVuZCh0YXNrKQogICAgICAgICAgICAg"
    "ICAgY29udGludWUKICAgICAgICAgICAgaWYgbm93IDw9IGR1ZV9kdCA8PSBlbmQgb3Igc3RhdHVz"
    "IGluIHsiY29tcGxldGVkIiwgImNhbmNlbGxlZCJ9OgogICAgICAgICAgICAgICAgZmlsdGVyZWQu"
    "YXBwZW5kKHRhc2spCgogICAgICAgIGZpbHRlcmVkLnNvcnQoa2V5PV90YXNrX2R1ZV9zb3J0X2tl"
    "eSkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgIGYiW1RBU0tTXVtGSUxU"
    "RVJdIGRvbmUgYmVmb3JlPXtsZW4odGFza3MpfSBhZnRlcj17bGVuKGZpbHRlcmVkKX0gc2tpcHBl"
    "ZF9pbnZhbGlkX2R1ZT17c2tpcHBlZF9pbnZhbGlkX2R1ZX0iLAogICAgICAgICAgICAiSU5GTyIs"
    "CiAgICAgICAgKQogICAgICAgIHJldHVybiBmaWx0ZXJlZAoKICAgIGRlZiBfZ29vZ2xlX2V2ZW50"
    "X2R1ZV9kYXRldGltZShzZWxmLCBldmVudDogZGljdCk6CiAgICAgICAgc3RhcnQgPSAoZXZlbnQg"
    "b3Ige30pLmdldCgic3RhcnQiKSBvciB7fQogICAgICAgIGRhdGVfdGltZSA9IHN0YXJ0LmdldCgi"
    "ZGF0ZVRpbWUiKQogICAgICAgIGlmIGRhdGVfdGltZToKICAgICAgICAgICAgcGFyc2VkID0gcGFy"
    "c2VfaXNvX2Zvcl9jb21wYXJlKGRhdGVfdGltZSwgY29udGV4dD0iZ29vZ2xlX2V2ZW50X2RhdGVU"
    "aW1lIikKICAgICAgICAgICAgaWYgcGFyc2VkOgogICAgICAgICAgICAgICAgcmV0dXJuIHBhcnNl"
    "ZAogICAgICAgIGRhdGVfb25seSA9IHN0YXJ0LmdldCgiZGF0ZSIpCiAgICAgICAgaWYgZGF0ZV9v"
    "bmx5OgogICAgICAgICAgICBwYXJzZWQgPSBwYXJzZV9pc29fZm9yX2NvbXBhcmUoZiJ7ZGF0ZV9v"
    "bmx5fVQwOTowMDowMCIsIGNvbnRleHQ9Imdvb2dsZV9ldmVudF9kYXRlIikKICAgICAgICAgICAg"
    "aWYgcGFyc2VkOgogICAgICAgICAgICAgICAgcmV0dXJuIHBhcnNlZAogICAgICAgIHJldHVybiBO"
    "b25lCgogICAgZGVmIF9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoc2VsZikgLT4gTm9uZToK"
    "ICAgICAgICBpZiBnZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkgaXMgTm9uZToKICAg"
    "ICAgICAgICAgcmV0dXJuCiAgICAgICAgdHJ5OgogICAgICAgICAgICBzZWxmLl90YXNrc190YWIu"
    "cmVmcmVzaCgpCiAgICAgICAgICAgIHZpc2libGVfY291bnQgPSBsZW4oc2VsZi5fZmlsdGVyZWRf"
    "dGFza3NfZm9yX3JlZ2lzdHJ5KCkpCiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltU"
    "QVNLU11bUkVHSVNUUlldIHJlZnJlc2ggY291bnQ9e3Zpc2libGVfY291bnR9LiIsICJJTkZPIikK"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coZiJbVEFTS1NdW1JFR0lTVFJZXVtFUlJPUl0gcmVmcmVzaCBmYWlsZWQ6IHtleH0iLCAi"
    "RVJST1IiKQogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBzZWxmLl90YXNrc190YWIu"
    "c3RvcF9yZWZyZXNoX3dvcmtlcihyZWFzb249InJlZ2lzdHJ5X3JlZnJlc2hfZXhjZXB0aW9uIikK"
    "ICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBzdG9wX2V4OgogICAgICAgICAgICAgICAg"
    "c2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtSRUdJU1RS"
    "WV1bV0FSTl0gZmFpbGVkIHRvIHN0b3AgcmVmcmVzaCB3b3JrZXIgY2xlYW5seToge3N0b3BfZXh9"
    "IiwKICAgICAgICAgICAgICAgICAgICAiV0FSTiIsCiAgICAgICAgICAgICAgICApCgogICAgZGVm"
    "IF9vbl90YXNrX2ZpbHRlcl9jaGFuZ2VkKHNlbGYsIGZpbHRlcl9rZXk6IHN0cikgLT4gTm9uZToK"
    "ICAgICAgICBzZWxmLl90YXNrX2RhdGVfZmlsdGVyID0gc3RyKGZpbHRlcl9rZXkgb3IgIm5leHRf"
    "M19tb250aHMiKQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUQVNLU10gVGFzayByZWdp"
    "c3RyeSBkYXRlIGZpbHRlciBjaGFuZ2VkIHRvIHtzZWxmLl90YXNrX2RhdGVfZmlsdGVyfS4iLCAi"
    "SU5GTyIpCiAgICAgICAgc2VsZi5fcmVmcmVzaF90YXNrX3JlZ2lzdHJ5X3BhbmVsKCkKCiAgICBk"
    "ZWYgX3RvZ2dsZV9zaG93X2NvbXBsZXRlZF90YXNrcyhzZWxmKSAtPiBOb25lOgogICAgICAgIHNl"
    "bGYuX3Rhc2tfc2hvd19jb21wbGV0ZWQgPSBub3Qgc2VsZi5fdGFza19zaG93X2NvbXBsZXRlZAog"
    "ICAgICAgIHNlbGYuX3Rhc2tzX3RhYi5zZXRfc2hvd19jb21wbGV0ZWQoc2VsZi5fdGFza19zaG93"
    "X2NvbXBsZXRlZCkKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoK"
    "ICAgIGRlZiBfc2VsZWN0ZWRfdGFza19pZHMoc2VsZikgLT4gbGlzdFtzdHJdOgogICAgICAgIGlm"
    "IGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBOb25lKSBpcyBOb25lOgogICAgICAgICAgICBy"
    "ZXR1cm4gW10KICAgICAgICByZXR1cm4gc2VsZi5fdGFza3NfdGFiLnNlbGVjdGVkX3Rhc2tfaWRz"
    "KCkKCiAgICBkZWYgX3NldF90YXNrX3N0YXR1cyhzZWxmLCB0YXNrX2lkOiBzdHIsIHN0YXR1czog"
    "c3RyKSAtPiBPcHRpb25hbFtkaWN0XToKICAgICAgICBpZiBzdGF0dXMgPT0gImNvbXBsZXRlZCI6"
    "CiAgICAgICAgICAgIHVwZGF0ZWQgPSBzZWxmLl90YXNrcy5jb21wbGV0ZSh0YXNrX2lkKQogICAg"
    "ICAgIGVsaWYgc3RhdHVzID09ICJjYW5jZWxsZWQiOgogICAgICAgICAgICB1cGRhdGVkID0gc2Vs"
    "Zi5fdGFza3MuY2FuY2VsKHRhc2tfaWQpCiAgICAgICAgZWxzZToKICAgICAgICAgICAgdXBkYXRl"
    "ZCA9IHNlbGYuX3Rhc2tzLnVwZGF0ZV9zdGF0dXModGFza19pZCwgc3RhdHVzKQoKICAgICAgICBp"
    "ZiBub3QgdXBkYXRlZDoKICAgICAgICAgICAgcmV0dXJuIE5vbmUKCiAgICAgICAgZ29vZ2xlX2V2"
    "ZW50X2lkID0gKHVwZGF0ZWQuZ2V0KCJnb29nbGVfZXZlbnRfaWQiKSBvciAiIikuc3RyaXAoKQog"
    "ICAgICAgIGlmIGdvb2dsZV9ldmVudF9pZDoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAg"
    "ICAgc2VsZi5fZ2NhbC5kZWxldGVfZXZlbnRfZm9yX3Rhc2soZ29vZ2xlX2V2ZW50X2lkKQogICAg"
    "ICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGV4OgogICAgICAgICAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKAogICAgICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtXQVJOXSBHb29nbGUgZXZl"
    "bnQgY2xlYW51cCBmYWlsZWQgZm9yIHRhc2tfaWQ9e3Rhc2tfaWR9OiB7ZXh9IiwKICAgICAgICAg"
    "ICAgICAgICAgICAiV0FSTiIsCiAgICAgICAgICAgICAgICApCiAgICAgICAgcmV0dXJuIHVwZGF0"
    "ZWQKCiAgICBkZWYgX2NvbXBsZXRlX3NlbGVjdGVkX3Rhc2soc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBkb25lID0gMAogICAgICAgIGZvciB0YXNrX2lkIGluIHNlbGYuX3NlbGVjdGVkX3Rhc2tfaWRz"
    "KCk6CiAgICAgICAgICAgIGlmIHNlbGYuX3NldF90YXNrX3N0YXR1cyh0YXNrX2lkLCAiY29tcGxl"
    "dGVkIik6CiAgICAgICAgICAgICAgICBkb25lICs9IDEKICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coZiJbVEFTS1NdIENPTVBMRVRFIFNFTEVDVEVEIGFwcGxpZWQgdG8ge2RvbmV9IHRhc2socyku"
    "IiwgIklORk8iKQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgog"
    "ICAgZGVmIF9jYW5jZWxfc2VsZWN0ZWRfdGFzayhzZWxmKSAtPiBOb25lOgogICAgICAgIGRvbmUg"
    "PSAwCiAgICAgICAgZm9yIHRhc2tfaWQgaW4gc2VsZi5fc2VsZWN0ZWRfdGFza19pZHMoKToKICAg"
    "ICAgICAgICAgaWYgc2VsZi5fc2V0X3Rhc2tfc3RhdHVzKHRhc2tfaWQsICJjYW5jZWxsZWQiKToK"
    "ICAgICAgICAgICAgICAgIGRvbmUgKz0gMQogICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltU"
    "QVNLU10gQ0FOQ0VMIFNFTEVDVEVEIGFwcGxpZWQgdG8ge2RvbmV9IHRhc2socykuIiwgIklORk8i"
    "KQogICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCgogICAgZGVmIF9w"
    "dXJnZV9jb21wbGV0ZWRfdGFza3Moc2VsZikgLT4gTm9uZToKICAgICAgICByZW1vdmVkID0gc2Vs"
    "Zi5fdGFza3MuY2xlYXJfY29tcGxldGVkKCkKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJb"
    "VEFTS1NdIFBVUkdFIENPTVBMRVRFRCByZW1vdmVkIHtyZW1vdmVkfSB0YXNrKHMpLiIsICJJTkZP"
    "IikKICAgICAgICBzZWxmLl9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgIGRlZiBf"
    "c2V0X3Rhc2tfZWRpdG9yX3N0YXR1cyhzZWxmLCB0ZXh0OiBzdHIsIG9rOiBib29sID0gRmFsc2Up"
    "IC0+IE5vbmU6CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlz"
    "IG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl90YXNrc190YWIuc2V0X3N0YXR1cyh0ZXh0LCBv"
    "az1vaykKCiAgICBkZWYgX29wZW5fdGFza19lZGl0b3Jfd29ya3NwYWNlKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAiX3Rhc2tzX3RhYiIsIE5vbmUpIGlzIE5vbmU6CiAg"
    "ICAgICAgICAgIHJldHVybgogICAgICAgIG5vd19sb2NhbCA9IGRhdGV0aW1lLm5vdygpCiAgICAg"
    "ICAgZW5kX2xvY2FsID0gbm93X2xvY2FsICsgdGltZWRlbHRhKG1pbnV0ZXM9MzApCiAgICAgICAg"
    "c2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX25hbWUuc2V0VGV4dCgiIikKICAgICAgICBzZWxm"
    "Ll90YXNrc190YWIudGFza19lZGl0b3Jfc3RhcnRfZGF0ZS5zZXRUZXh0KG5vd19sb2NhbC5zdHJm"
    "dGltZSgiJVktJW0tJWQiKSkKICAgICAgICBzZWxmLl90YXNrc190YWIudGFza19lZGl0b3Jfc3Rh"
    "cnRfdGltZS5zZXRUZXh0KG5vd19sb2NhbC5zdHJmdGltZSgiJUg6JU0iKSkKICAgICAgICBzZWxm"
    "Ll90YXNrc190YWIudGFza19lZGl0b3JfZW5kX2RhdGUuc2V0VGV4dChlbmRfbG9jYWwuc3RyZnRp"
    "bWUoIiVZLSVtLSVkIikpCiAgICAgICAgc2VsZi5fdGFza3NfdGFiLnRhc2tfZWRpdG9yX2VuZF90"
    "aW1lLnNldFRleHQoZW5kX2xvY2FsLnN0cmZ0aW1lKCIlSDolTSIpKQogICAgICAgIHNlbGYuX3Rh"
    "c2tzX3RhYi50YXNrX2VkaXRvcl9ub3Rlcy5zZXRQbGFpblRleHQoIiIpCiAgICAgICAgc2VsZi5f"
    "dGFza3NfdGFiLnRhc2tfZWRpdG9yX2xvY2F0aW9uLnNldFRleHQoIiIpCiAgICAgICAgc2VsZi5f"
    "dGFza3NfdGFiLnRhc2tfZWRpdG9yX3JlY3VycmVuY2Uuc2V0VGV4dCgiIikKICAgICAgICBzZWxm"
    "Ll90YXNrc190YWIudGFza19lZGl0b3JfYWxsX2RheS5zZXRDaGVja2VkKEZhbHNlKQogICAgICAg"
    "IHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIkNvbmZpZ3VyZSB0YXNrIGRldGFpbHMsIHRo"
    "ZW4gc2F2ZSB0byBHb29nbGUgQ2FsZW5kYXIuIiwgb2s9RmFsc2UpCiAgICAgICAgc2VsZi5fdGFz"
    "a3NfdGFiLm9wZW5fZWRpdG9yKCkKCiAgICBkZWYgX2Nsb3NlX3Rhc2tfZWRpdG9yX3dvcmtzcGFj"
    "ZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIGdldGF0dHIoc2VsZiwgIl90YXNrc190YWIiLCBO"
    "b25lKSBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fdGFza3NfdGFiLmNsb3NlX2VkaXRv"
    "cigpCgogICAgZGVmIF9jYW5jZWxfdGFza19lZGl0b3Jfd29ya3NwYWNlKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgc2VsZi5fY2xvc2VfdGFza19lZGl0b3Jfd29ya3NwYWNlKCkKCiAgICBkZWYgX3Bh"
    "cnNlX2VkaXRvcl9kYXRldGltZShzZWxmLCBkYXRlX3RleHQ6IHN0ciwgdGltZV90ZXh0OiBzdHIs"
    "IGFsbF9kYXk6IGJvb2wsIGlzX2VuZDogYm9vbCA9IEZhbHNlKToKICAgICAgICBkYXRlX3RleHQg"
    "PSAoZGF0ZV90ZXh0IG9yICIiKS5zdHJpcCgpCiAgICAgICAgdGltZV90ZXh0ID0gKHRpbWVfdGV4"
    "dCBvciAiIikuc3RyaXAoKQogICAgICAgIGlmIG5vdCBkYXRlX3RleHQ6CiAgICAgICAgICAgIHJl"
    "dHVybiBOb25lCiAgICAgICAgaWYgYWxsX2RheToKICAgICAgICAgICAgaG91ciA9IDIzIGlmIGlz"
    "X2VuZCBlbHNlIDAKICAgICAgICAgICAgbWludXRlID0gNTkgaWYgaXNfZW5kIGVsc2UgMAogICAg"
    "ICAgICAgICBwYXJzZWQgPSBkYXRldGltZS5zdHJwdGltZShmIntkYXRlX3RleHR9IHtob3VyOjAy"
    "ZH06e21pbnV0ZTowMmR9IiwgIiVZLSVtLSVkICVIOiVNIikKICAgICAgICBlbHNlOgogICAgICAg"
    "ICAgICBwYXJzZWQgPSBkYXRldGltZS5zdHJwdGltZShmIntkYXRlX3RleHR9IHt0aW1lX3RleHR9"
    "IiwgIiVZLSVtLSVkICVIOiVNIikKICAgICAgICBub3JtYWxpemVkID0gbm9ybWFsaXplX2RhdGV0"
    "aW1lX2Zvcl9jb21wYXJlKHBhcnNlZCwgY29udGV4dD0idGFza19lZGl0b3JfcGFyc2VfZHQiKQog"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbVEFTS1NdW0VESVRPUl0g"
    "cGFyc2VkIGRhdGV0aW1lIGlzX2VuZD17aXNfZW5kfSwgYWxsX2RheT17YWxsX2RheX06ICIKICAg"
    "ICAgICAgICAgZiJpbnB1dD0ne2RhdGVfdGV4dH0ge3RpbWVfdGV4dH0nIC0+IHtub3JtYWxpemVk"
    "Lmlzb2Zvcm1hdCgpIGlmIG5vcm1hbGl6ZWQgZWxzZSAnTm9uZSd9IiwKICAgICAgICAgICAgIklO"
    "Rk8iLAogICAgICAgICkKICAgICAgICByZXR1cm4gbm9ybWFsaXplZAoKICAgIGRlZiBfc2F2ZV90"
    "YXNrX2VkaXRvcl9nb29nbGVfZmlyc3Qoc2VsZikgLT4gTm9uZToKICAgICAgICB0YWIgPSBnZXRh"
    "dHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSkKICAgICAgICBpZiB0YWIgaXMgTm9uZToKICAg"
    "ICAgICAgICAgcmV0dXJuCiAgICAgICAgdGl0bGUgPSB0YWIudGFza19lZGl0b3JfbmFtZS50ZXh0"
    "KCkuc3RyaXAoKQogICAgICAgIGFsbF9kYXkgPSB0YWIudGFza19lZGl0b3JfYWxsX2RheS5pc0No"
    "ZWNrZWQoKQogICAgICAgIHN0YXJ0X2RhdGUgPSB0YWIudGFza19lZGl0b3Jfc3RhcnRfZGF0ZS50"
    "ZXh0KCkuc3RyaXAoKQogICAgICAgIHN0YXJ0X3RpbWUgPSB0YWIudGFza19lZGl0b3Jfc3RhcnRf"
    "dGltZS50ZXh0KCkuc3RyaXAoKQogICAgICAgIGVuZF9kYXRlID0gdGFiLnRhc2tfZWRpdG9yX2Vu"
    "ZF9kYXRlLnRleHQoKS5zdHJpcCgpCiAgICAgICAgZW5kX3RpbWUgPSB0YWIudGFza19lZGl0b3Jf"
    "ZW5kX3RpbWUudGV4dCgpLnN0cmlwKCkKICAgICAgICBub3RlcyA9IHRhYi50YXNrX2VkaXRvcl9u"
    "b3Rlcy50b1BsYWluVGV4dCgpLnN0cmlwKCkKICAgICAgICBsb2NhdGlvbiA9IHRhYi50YXNrX2Vk"
    "aXRvcl9sb2NhdGlvbi50ZXh0KCkuc3RyaXAoKQogICAgICAgIHJlY3VycmVuY2UgPSB0YWIudGFz"
    "a19lZGl0b3JfcmVjdXJyZW5jZS50ZXh0KCkuc3RyaXAoKQoKICAgICAgICBpZiBub3QgdGl0bGU6"
    "CiAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMoIlRhc2sgTmFtZSBpcyBy"
    "ZXF1aXJlZC4iLCBvaz1GYWxzZSkKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgbm90IHN0"
    "YXJ0X2RhdGUgb3Igbm90IGVuZF9kYXRlIG9yIChub3QgYWxsX2RheSBhbmQgKG5vdCBzdGFydF90"
    "aW1lIG9yIG5vdCBlbmRfdGltZSkpOgogICAgICAgICAgICBzZWxmLl9zZXRfdGFza19lZGl0b3Jf"
    "c3RhdHVzKCJTdGFydC9FbmQgZGF0ZSBhbmQgdGltZSBhcmUgcmVxdWlyZWQuIiwgb2s9RmFsc2Up"
    "CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc3RhcnRfZHQgPSBz"
    "ZWxmLl9wYXJzZV9lZGl0b3JfZGF0ZXRpbWUoc3RhcnRfZGF0ZSwgc3RhcnRfdGltZSwgYWxsX2Rh"
    "eSwgaXNfZW5kPUZhbHNlKQogICAgICAgICAgICBlbmRfZHQgPSBzZWxmLl9wYXJzZV9lZGl0b3Jf"
    "ZGF0ZXRpbWUoZW5kX2RhdGUsIGVuZF90aW1lLCBhbGxfZGF5LCBpc19lbmQ9VHJ1ZSkKICAgICAg"
    "ICAgICAgaWYgbm90IHN0YXJ0X2R0IG9yIG5vdCBlbmRfZHQ6CiAgICAgICAgICAgICAgICByYWlz"
    "ZSBWYWx1ZUVycm9yKCJkYXRldGltZSBwYXJzZSBmYWlsZWQiKQogICAgICAgICAgICBpZiBlbmRf"
    "ZHQgPCBzdGFydF9kdDoKICAgICAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0"
    "dXMoIkVuZCBkYXRldGltZSBtdXN0IGJlIGFmdGVyIHN0YXJ0IGRhdGV0aW1lLiIsIG9rPUZhbHNl"
    "KQogICAgICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAg"
    "ICAgICAgc2VsZi5fc2V0X3Rhc2tfZWRpdG9yX3N0YXR1cygiSW52YWxpZCBkYXRlL3RpbWUgZm9y"
    "bWF0LiBVc2UgWVlZWS1NTS1ERCBhbmQgSEg6TU0uIiwgb2s9RmFsc2UpCiAgICAgICAgICAgIHJl"
    "dHVybgoKICAgICAgICB0el9uYW1lID0gc2VsZi5fZ2NhbC5fZ2V0X2dvb2dsZV9ldmVudF90aW1l"
    "em9uZSgpCiAgICAgICAgcGF5bG9hZCA9IHsic3VtbWFyeSI6IHRpdGxlfQogICAgICAgIGlmIGFs"
    "bF9kYXk6CiAgICAgICAgICAgIHBheWxvYWRbInN0YXJ0Il0gPSB7ImRhdGUiOiBzdGFydF9kdC5k"
    "YXRlKCkuaXNvZm9ybWF0KCl9CiAgICAgICAgICAgIHBheWxvYWRbImVuZCJdID0geyJkYXRlIjog"
    "KGVuZF9kdC5kYXRlKCkgKyB0aW1lZGVsdGEoZGF5cz0xKSkuaXNvZm9ybWF0KCl9CiAgICAgICAg"
    "ZWxzZToKICAgICAgICAgICAgcGF5bG9hZFsic3RhcnQiXSA9IHsiZGF0ZVRpbWUiOiBzdGFydF9k"
    "dC5yZXBsYWNlKHR6aW5mbz1Ob25lKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMiKSwgInRp"
    "bWVab25lIjogdHpfbmFtZX0KICAgICAgICAgICAgcGF5bG9hZFsiZW5kIl0gPSB7ImRhdGVUaW1l"
    "IjogZW5kX2R0LnJlcGxhY2UodHppbmZvPU5vbmUpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25k"
    "cyIpLCAidGltZVpvbmUiOiB0el9uYW1lfQogICAgICAgIGlmIG5vdGVzOgogICAgICAgICAgICBw"
    "YXlsb2FkWyJkZXNjcmlwdGlvbiJdID0gbm90ZXMKICAgICAgICBpZiBsb2NhdGlvbjoKICAgICAg"
    "ICAgICAgcGF5bG9hZFsibG9jYXRpb24iXSA9IGxvY2F0aW9uCiAgICAgICAgaWYgcmVjdXJyZW5j"
    "ZToKICAgICAgICAgICAgcnVsZSA9IHJlY3VycmVuY2UgaWYgcmVjdXJyZW5jZS51cHBlcigpLnN0"
    "YXJ0c3dpdGgoIlJSVUxFOiIpIGVsc2UgZiJSUlVMRTp7cmVjdXJyZW5jZX0iCiAgICAgICAgICAg"
    "IHBheWxvYWRbInJlY3VycmVuY2UiXSA9IFtydWxlXQoKICAgICAgICBzZWxmLl9kaWFnX3RhYi5s"
    "b2coZiJbVEFTS1NdW0VESVRPUl0gR29vZ2xlIHNhdmUgc3RhcnQgZm9yIHRpdGxlPSd7dGl0bGV9"
    "Jy4iLCAiSU5GTyIpCiAgICAgICAgdHJ5OgogICAgICAgICAgICBldmVudF9pZCwgXyA9IHNlbGYu"
    "X2djYWwuY3JlYXRlX2V2ZW50X3dpdGhfcGF5bG9hZChwYXlsb2FkLCBjYWxlbmRhcl9pZD0icHJp"
    "bWFyeSIpCiAgICAgICAgICAgIHRhc2tzID0gc2VsZi5fdGFza3MubG9hZF9hbGwoKQogICAgICAg"
    "ICAgICB0YXNrID0gewogICAgICAgICAgICAgICAgImlkIjogZiJ0YXNrX3t1dWlkLnV1aWQ0KCku"
    "aGV4WzoxMF19IiwKICAgICAgICAgICAgICAgICJjcmVhdGVkX2F0IjogbG9jYWxfbm93X2lzbygp"
    "LAogICAgICAgICAgICAgICAgImR1ZV9hdCI6IHN0YXJ0X2R0Lmlzb2Zvcm1hdCh0aW1lc3BlYz0i"
    "c2Vjb25kcyIpLAogICAgICAgICAgICAgICAgInByZV90cmlnZ2VyIjogKHN0YXJ0X2R0IC0gdGlt"
    "ZWRlbHRhKG1pbnV0ZXM9MSkpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpLAogICAgICAg"
    "ICAgICAgICAgInRleHQiOiB0aXRsZSwKICAgICAgICAgICAgICAgICJzdGF0dXMiOiAicGVuZGlu"
    "ZyIsCiAgICAgICAgICAgICAgICAiYWNrbm93bGVkZ2VkX2F0IjogTm9uZSwKICAgICAgICAgICAg"
    "ICAgICJyZXRyeV9jb3VudCI6IDAsCiAgICAgICAgICAgICAgICAibGFzdF90cmlnZ2VyZWRfYXQi"
    "OiBOb25lLAogICAgICAgICAgICAgICAgIm5leHRfcmV0cnlfYXQiOiBOb25lLAogICAgICAgICAg"
    "ICAgICAgInByZV9hbm5vdW5jZWQiOiBGYWxzZSwKICAgICAgICAgICAgICAgICJzb3VyY2UiOiAi"
    "bG9jYWwiLAogICAgICAgICAgICAgICAgImdvb2dsZV9ldmVudF9pZCI6IGV2ZW50X2lkLAogICAg"
    "ICAgICAgICAgICAgInN5bmNfc3RhdHVzIjogInN5bmNlZCIsCiAgICAgICAgICAgICAgICAibGFz"
    "dF9zeW5jZWRfYXQiOiBsb2NhbF9ub3dfaXNvKCksCiAgICAgICAgICAgICAgICAibWV0YWRhdGEi"
    "OiB7CiAgICAgICAgICAgICAgICAgICAgImlucHV0IjogInRhc2tfZWRpdG9yX2dvb2dsZV9maXJz"
    "dCIsCiAgICAgICAgICAgICAgICAgICAgIm5vdGVzIjogbm90ZXMsCiAgICAgICAgICAgICAgICAg"
    "ICAgInN0YXJ0X2F0Ijogc3RhcnRfZHQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAg"
    "ICAgICAgICAgICAgICAgICAgImVuZF9hdCI6IGVuZF9kdC5pc29mb3JtYXQodGltZXNwZWM9InNl"
    "Y29uZHMiKSwKICAgICAgICAgICAgICAgICAgICAiYWxsX2RheSI6IGJvb2woYWxsX2RheSksCiAg"
    "ICAgICAgICAgICAgICAgICAgImxvY2F0aW9uIjogbG9jYXRpb24sCiAgICAgICAgICAgICAgICAg"
    "ICAgInJlY3VycmVuY2UiOiByZWN1cnJlbmNlLAogICAgICAgICAgICAgICAgfSwKICAgICAgICAg"
    "ICAgfQogICAgICAgICAgICB0YXNrcy5hcHBlbmQodGFzaykKICAgICAgICAgICAgc2VsZi5fdGFz"
    "a3Muc2F2ZV9hbGwodGFza3MpCiAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0"
    "dXMoIkdvb2dsZSBzeW5jIHN1Y2NlZWRlZCBhbmQgdGFzayByZWdpc3RyeSB1cGRhdGVkLiIsIG9r"
    "PVRydWUpCiAgICAgICAgICAgIHNlbGYuX3JlZnJlc2hfdGFza19yZWdpc3RyeV9wYW5lbCgpCiAg"
    "ICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW1RBU0tTXVtF"
    "RElUT1JdIEdvb2dsZSBzYXZlIHN1Y2Nlc3MgZm9yIHRpdGxlPSd7dGl0bGV9JywgZXZlbnRfaWQ9"
    "e2V2ZW50X2lkfS4iLAogICAgICAgICAgICAgICAgIk9LIiwKICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICBzZWxmLl9jbG9zZV90YXNrX2VkaXRvcl93b3Jrc3BhY2UoKQogICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb24gYXMgZXg6CiAgICAgICAgICAgIHNlbGYuX3NldF90YXNrX2VkaXRvcl9zdGF0dXMo"
    "ZiJHb29nbGUgc2F2ZSBmYWlsZWQ6IHtleH0iLCBvaz1GYWxzZSkKICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbVEFTS1NdW0VESVRPUl1bRVJST1JdIEdv"
    "b2dsZSBzYXZlIGZhaWx1cmUgZm9yIHRpdGxlPSd7dGl0bGV9Jzoge2V4fSIsCiAgICAgICAgICAg"
    "ICAgICAiRVJST1IiLAogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2Nsb3NlX3Rhc2tf"
    "ZWRpdG9yX3dvcmtzcGFjZSgpCgogICAgZGVmIF9pbnNlcnRfY2FsZW5kYXJfZGF0ZShzZWxmLCBx"
    "ZGF0ZTogUURhdGUpIC0+IE5vbmU6CiAgICAgICAgZGF0ZV90ZXh0ID0gcWRhdGUudG9TdHJpbmco"
    "Inl5eXktTU0tZGQiKQogICAgICAgIHJvdXRlZF90YXJnZXQgPSAibm9uZSIKCiAgICAgICAgZm9j"
    "dXNfd2lkZ2V0ID0gUUFwcGxpY2F0aW9uLmZvY3VzV2lkZ2V0KCkKICAgICAgICBkaXJlY3RfdGFy"
    "Z2V0cyA9IFsKICAgICAgICAgICAgKCJ0YXNrX2VkaXRvcl9zdGFydF9kYXRlIiwgZ2V0YXR0cihn"
    "ZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSksICJ0YXNrX2VkaXRvcl9zdGFydF9kYXRl"
    "IiwgTm9uZSkpLAogICAgICAgICAgICAoInRhc2tfZWRpdG9yX2VuZF9kYXRlIiwgZ2V0YXR0cihn"
    "ZXRhdHRyKHNlbGYsICJfdGFza3NfdGFiIiwgTm9uZSksICJ0YXNrX2VkaXRvcl9lbmRfZGF0ZSIs"
    "IE5vbmUpKSwKICAgICAgICBdCiAgICAgICAgZm9yIG5hbWUsIHdpZGdldCBpbiBkaXJlY3RfdGFy"
    "Z2V0czoKICAgICAgICAgICAgaWYgd2lkZ2V0IGlzIG5vdCBOb25lIGFuZCBmb2N1c193aWRnZXQg"
    "aXMgd2lkZ2V0OgogICAgICAgICAgICAgICAgd2lkZ2V0LnNldFRleHQoZGF0ZV90ZXh0KQogICAg"
    "ICAgICAgICAgICAgcm91dGVkX3RhcmdldCA9IG5hbWUKICAgICAgICAgICAgICAgIGJyZWFrCgog"
    "ICAgICAgIGlmIHJvdXRlZF90YXJnZXQgPT0gIm5vbmUiOgogICAgICAgICAgICBpZiBoYXNhdHRy"
    "KHNlbGYsICJfaW5wdXRfZmllbGQiKSBhbmQgc2VsZi5faW5wdXRfZmllbGQgaXMgbm90IE5vbmU6"
    "CiAgICAgICAgICAgICAgICBpZiBmb2N1c193aWRnZXQgaXMgc2VsZi5faW5wdXRfZmllbGQ6CiAg"
    "ICAgICAgICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuaW5zZXJ0KGRhdGVfdGV4dCkKICAg"
    "ICAgICAgICAgICAgICAgICByb3V0ZWRfdGFyZ2V0ID0gImlucHV0X2ZpZWxkX2luc2VydCIKICAg"
    "ICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQu"
    "c2V0VGV4dChkYXRlX3RleHQpCiAgICAgICAgICAgICAgICAgICAgcm91dGVkX3RhcmdldCA9ICJp"
    "bnB1dF9maWVsZF9zZXQiCgogICAgICAgIGlmIGhhc2F0dHIoc2VsZiwgIl90YXNrc190YWIiKSBh"
    "bmQgc2VsZi5fdGFza3NfdGFiIGlzIG5vdCBOb25lOgogICAgICAgICAgICBzZWxmLl90YXNrc190"
    "YWIuc3RhdHVzX2xhYmVsLnNldFRleHQoZiJDYWxlbmRhciBkYXRlIHNlbGVjdGVkOiB7ZGF0ZV90"
    "ZXh0fSIpCgogICAgICAgIGlmIGhhc2F0dHIoc2VsZiwgIl9kaWFnX3RhYiIpIGFuZCBzZWxmLl9k"
    "aWFnX3RhYiBpcyBub3QgTm9uZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAg"
    "ICAgICAgICAgICAgZiJbQ0FMRU5EQVJdIG1pbmkgY2FsZW5kYXIgY2xpY2sgcm91dGVkOiBkYXRl"
    "PXtkYXRlX3RleHR9LCB0YXJnZXQ9e3JvdXRlZF90YXJnZXR9LiIsCiAgICAgICAgICAgICAgICAi"
    "SU5GTyIKICAgICAgICAgICAgKQoKICAgIGRlZiBfcG9sbF9nb29nbGVfY2FsZW5kYXJfaW5ib3Vu"
    "ZF9zeW5jKHNlbGYsIGZvcmNlX29uY2U6IGJvb2wgPSBGYWxzZSk6CiAgICAgICAgIiIiCiAgICAg"
    "ICAgU3luYyBHb29nbGUgQ2FsZW5kYXIgZXZlbnRzIOKGkiBsb2NhbCB0YXNrcyB1c2luZyBHb29n"
    "bGUncyBzeW5jVG9rZW4gQVBJLgoKICAgICAgICBTdGFnZSAxIChmaXJzdCBydW4gLyBmb3JjZWQp"
    "OiBGdWxsIGZldGNoLCBzdG9yZXMgbmV4dFN5bmNUb2tlbi4KICAgICAgICBTdGFnZSAyIChldmVy"
    "eSBwb2xsKTogICAgICAgICBJbmNyZW1lbnRhbCBmZXRjaCB1c2luZyBzdG9yZWQgc3luY1Rva2Vu"
    "IOKAlAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybnMgT05MWSB3"
    "aGF0IGNoYW5nZWQgKGFkZHMvZWRpdHMvY2FuY2VscykuCiAgICAgICAgSWYgc2VydmVyIHJldHVy"
    "bnMgNDEwIEdvbmUgKHRva2VuIGV4cGlyZWQpLCBmYWxscyBiYWNrIHRvIGZ1bGwgc3luYy4KICAg"
    "ICAgICAiIiIKICAgICAgICBpZiBub3QgZm9yY2Vfb25jZSBhbmQgbm90IGJvb2woQ0ZHLmdldCgi"
    "c2V0dGluZ3MiLCB7fSkuZ2V0KCJnb29nbGVfc3luY19lbmFibGVkIiwgVHJ1ZSkpOgogICAgICAg"
    "ICAgICByZXR1cm4gMAoKICAgICAgICB0cnk6CiAgICAgICAgICAgIG5vd19pc28gPSBsb2NhbF9u"
    "b3dfaXNvKCkKICAgICAgICAgICAgdGFza3MgPSBzZWxmLl90YXNrcy5sb2FkX2FsbCgpCiAgICAg"
    "ICAgICAgIHRhc2tzX2J5X2V2ZW50X2lkID0gewogICAgICAgICAgICAgICAgKHQuZ2V0KCJnb29n"
    "bGVfZXZlbnRfaWQiKSBvciAiIikuc3RyaXAoKTogdAogICAgICAgICAgICAgICAgZm9yIHQgaW4g"
    "dGFza3MKICAgICAgICAgICAgICAgIGlmICh0LmdldCgiZ29vZ2xlX2V2ZW50X2lkIikgb3IgIiIp"
    "LnN0cmlwKCkKICAgICAgICAgICAgfQoKICAgICAgICAgICAgIyDilIDilIAgRmV0Y2ggZnJvbSBH"
    "b29nbGUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgICAgIHN0b3JlZF90b2tlbiA9IHNlbGYuX3N0YXRl"
    "LmdldCgiZ29vZ2xlX2NhbGVuZGFyX3N5bmNfdG9rZW4iKQoKICAgICAgICAgICAgdHJ5OgogICAg"
    "ICAgICAgICAgICAgaWYgc3RvcmVkX3Rva2VuIGFuZCBub3QgZm9yY2Vfb25jZToKICAgICAgICAg"
    "ICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgICAgICJb"
    "R09PR0xFXVtTWU5DXSBJbmNyZW1lbnRhbCBzeW5jIChzeW5jVG9rZW4pLiIsICJJTkZPIgogICAg"
    "ICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICByZW1vdGVfZXZlbnRzLCBuZXh0"
    "X3Rva2VuID0gc2VsZi5fZ2NhbC5saXN0X3ByaW1hcnlfZXZlbnRzKAogICAgICAgICAgICAgICAg"
    "ICAgICAgICBzeW5jX3Rva2VuPXN0b3JlZF90b2tlbgogICAgICAgICAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KAogICAgICAgICAgICAgICAgICAgICAgICAiW0dPT0dMRV1bU1lOQ10gRnVsbCBzeW5jIChubyBz"
    "dG9yZWQgdG9rZW4pLiIsICJJTkZPIgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAg"
    "ICAgICAgICBub3dfdXRjID0gZGF0ZXRpbWUudXRjbm93KCkucmVwbGFjZShtaWNyb3NlY29uZD0w"
    "KQogICAgICAgICAgICAgICAgICAgIHRpbWVfbWluID0gKG5vd191dGMgLSB0aW1lZGVsdGEoZGF5"
    "cz0zNjUpKS5pc29mb3JtYXQoKSArICJaIgogICAgICAgICAgICAgICAgICAgIHJlbW90ZV9ldmVu"
    "dHMsIG5leHRfdG9rZW4gPSBzZWxmLl9nY2FsLmxpc3RfcHJpbWFyeV9ldmVudHMoCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgIHRpbWVfbWluPXRpbWVfbWluCiAgICAgICAgICAgICAgICAgICAgKQoK"
    "ICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBhcGlfZXg6CiAgICAgICAgICAgICAgICBp"
    "ZiAiNDEwIiBpbiBzdHIoYXBpX2V4KSBvciAiR29uZSIgaW4gc3RyKGFwaV9leCk6CiAgICAgICAg"
    "ICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgICAgICAgICAi"
    "W0dPT0dMRV1bU1lOQ10gc3luY1Rva2VuIGV4cGlyZWQgKDQxMCkg4oCUIGZ1bGwgcmVzeW5jLiIs"
    "ICJXQVJOIgogICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICBzZWxmLl9z"
    "dGF0ZS5wb3AoImdvb2dsZV9jYWxlbmRhcl9zeW5jX3Rva2VuIiwgTm9uZSkKICAgICAgICAgICAg"
    "ICAgICAgICBub3dfdXRjID0gZGF0ZXRpbWUudXRjbm93KCkucmVwbGFjZShtaWNyb3NlY29uZD0w"
    "KQogICAgICAgICAgICAgICAgICAgIHRpbWVfbWluID0gKG5vd191dGMgLSB0aW1lZGVsdGEoZGF5"
    "cz0zNjUpKS5pc29mb3JtYXQoKSArICJaIgogICAgICAgICAgICAgICAgICAgIHJlbW90ZV9ldmVu"
    "dHMsIG5leHRfdG9rZW4gPSBzZWxmLl9nY2FsLmxpc3RfcHJpbWFyeV9ldmVudHMoCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgIHRpbWVfbWluPXRpbWVfbWluCiAgICAgICAgICAgICAgICAgICAgKQog"
    "ICAgICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICByYWlzZQoKICAgICAgICAg"
    "ICAgc2VsZi5fZGlhZ190YWIubG9nKAogICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTWU5DXSBS"
    "ZWNlaXZlZCB7bGVuKHJlbW90ZV9ldmVudHMpfSBldmVudChzKS4iLCAiSU5GTyIKICAgICAgICAg"
    "ICAgKQoKICAgICAgICAgICAgIyBTYXZlIG5ldyB0b2tlbiBmb3IgbmV4dCBpbmNyZW1lbnRhbCBj"
    "YWxsCiAgICAgICAgICAgIGlmIG5leHRfdG9rZW46CiAgICAgICAgICAgICAgICBzZWxmLl9zdGF0"
    "ZVsiZ29vZ2xlX2NhbGVuZGFyX3N5bmNfdG9rZW4iXSA9IG5leHRfdG9rZW4KICAgICAgICAgICAg"
    "ICAgIHNlbGYuX21lbW9yeS5zYXZlX3N0YXRlKHNlbGYuX3N0YXRlKQoKICAgICAgICAgICAgIyDi"
    "lIDilIAgUHJvY2VzcyBldmVudHMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgICAgIGlt"
    "cG9ydGVkX2NvdW50ID0gdXBkYXRlZF9jb3VudCA9IHJlbW92ZWRfY291bnQgPSAwCiAgICAgICAg"
    "ICAgIGNoYW5nZWQgPSBGYWxzZQoKICAgICAgICAgICAgZm9yIGV2ZW50IGluIHJlbW90ZV9ldmVu"
    "dHM6CiAgICAgICAgICAgICAgICBldmVudF9pZCA9IChldmVudC5nZXQoImlkIikgb3IgIiIpLnN0"
    "cmlwKCkKICAgICAgICAgICAgICAgIGlmIG5vdCBldmVudF9pZDoKICAgICAgICAgICAgICAgICAg"
    "ICBjb250aW51ZQoKICAgICAgICAgICAgICAgICMgRGVsZXRlZCAvIGNhbmNlbGxlZCBvbiBHb29n"
    "bGUncyBzaWRlCiAgICAgICAgICAgICAgICBpZiBldmVudC5nZXQoInN0YXR1cyIpID09ICJjYW5j"
    "ZWxsZWQiOgogICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nID0gdGFza3NfYnlfZXZlbnRfaWQu"
    "Z2V0KGV2ZW50X2lkKQogICAgICAgICAgICAgICAgICAgIGlmIGV4aXN0aW5nIGFuZCBleGlzdGlu"
    "Zy5nZXQoInN0YXR1cyIpIG5vdCBpbiAoImNhbmNlbGxlZCIsICJjb21wbGV0ZWQiKToKICAgICAg"
    "ICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbInN0YXR1cyJdICAgICAgICAgPSAiY2FuY2VsbGVk"
    "IgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZ1siY2FuY2VsbGVkX2F0Il0gICA9IG5v"
    "d19pc28KICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbInN5bmNfc3RhdHVzIl0gICAg"
    "PSAiZGVsZXRlZF9yZW1vdGUiCiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJsYXN0"
    "X3N5bmNlZF9hdCJdID0gbm93X2lzbwogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGluZy5z"
    "ZXRkZWZhdWx0KCJtZXRhZGF0YSIsIHt9KVsiZ29vZ2xlX2RlbGV0ZWRfcmVtb3RlIl0gPSBub3df"
    "aXNvCiAgICAgICAgICAgICAgICAgICAgICAgIHJlbW92ZWRfY291bnQgKz0gMQogICAgICAgICAg"
    "ICAgICAgICAgICAgICBjaGFuZ2VkID0gVHJ1ZQogICAgICAgICAgICAgICAgICAgICAgICBzZWxm"
    "Ll9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgICAgICAgICBmIltHT09HTEVdW1NZ"
    "TkNdIFJlbW92ZWQ6IHtleGlzdGluZy5nZXQoJ3RleHQnLCc/Jyl9IiwgIklORk8iCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgICAgICBjb250aW51ZQoKICAgICAgICAg"
    "ICAgICAgIHN1bW1hcnkgPSAoZXZlbnQuZ2V0KCJzdW1tYXJ5Iikgb3IgIkdvb2dsZSBDYWxlbmRh"
    "ciBFdmVudCIpLnN0cmlwKCkgb3IgIkdvb2dsZSBDYWxlbmRhciBFdmVudCIKICAgICAgICAgICAg"
    "ICAgIGR1ZV9hdCAgPSBzZWxmLl9nb29nbGVfZXZlbnRfZHVlX2RhdGV0aW1lKGV2ZW50KQogICAg"
    "ICAgICAgICAgICAgZXhpc3RpbmcgPSB0YXNrc19ieV9ldmVudF9pZC5nZXQoZXZlbnRfaWQpCgog"
    "ICAgICAgICAgICAgICAgaWYgZXhpc3Rpbmc6CiAgICAgICAgICAgICAgICAgICAgIyBVcGRhdGUg"
    "aWYgYW55dGhpbmcgY2hhbmdlZAogICAgICAgICAgICAgICAgICAgIHRhc2tfY2hhbmdlZCA9IEZh"
    "bHNlCiAgICAgICAgICAgICAgICAgICAgaWYgKGV4aXN0aW5nLmdldCgidGV4dCIpIG9yICIiKS5z"
    "dHJpcCgpICE9IHN1bW1hcnk6CiAgICAgICAgICAgICAgICAgICAgICAgIGV4aXN0aW5nWyJ0ZXh0"
    "Il0gPSBzdW1tYXJ5CiAgICAgICAgICAgICAgICAgICAgICAgIHRhc2tfY2hhbmdlZCA9IFRydWUK"
    "ICAgICAgICAgICAgICAgICAgICBpZiBkdWVfYXQ6CiAgICAgICAgICAgICAgICAgICAgICAgIGR1"
    "ZV9pc28gPSBkdWVfYXQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgaWYgZXhpc3RpbmcuZ2V0KCJkdWVfYXQiKSAhPSBkdWVfaXNvOgogICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbImR1ZV9hdCJdICAgICAgID0gZHVlX2lzbwog"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbInByZV90cmlnZ2VyIl0gID0gKGR1"
    "ZV9hdCAtIHRpbWVkZWx0YShtaW51dGVzPTEpKS5pc29mb3JtYXQodGltZXNwZWM9InNlY29uZHMi"
    "KQogICAgICAgICAgICAgICAgICAgICAgICAgICAgdGFza19jaGFuZ2VkID0gVHJ1ZQogICAgICAg"
    "ICAgICAgICAgICAgIGlmIGV4aXN0aW5nLmdldCgic3luY19zdGF0dXMiKSAhPSAic3luY2VkIjoK"
    "ICAgICAgICAgICAgICAgICAgICAgICAgZXhpc3RpbmdbInN5bmNfc3RhdHVzIl0gPSAic3luY2Vk"
    "IgogICAgICAgICAgICAgICAgICAgICAgICB0YXNrX2NoYW5nZWQgPSBUcnVlCiAgICAgICAgICAg"
    "ICAgICAgICAgaWYgdGFza19jaGFuZ2VkOgogICAgICAgICAgICAgICAgICAgICAgICBleGlzdGlu"
    "Z1sibGFzdF9zeW5jZWRfYXQiXSA9IG5vd19pc28KICAgICAgICAgICAgICAgICAgICAgICAgdXBk"
    "YXRlZF9jb3VudCArPSAxCiAgICAgICAgICAgICAgICAgICAgICAgIGNoYW5nZWQgPSBUcnVlCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgIGYiW0dPT0dMRV1bU1lOQ10gVXBkYXRlZDoge3N1bW1hcnl9IiwgIklORk8i"
    "CiAgICAgICAgICAgICAgICAgICAgICAgICkKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAg"
    "ICAgICAgICAgICAgIyBOZXcgZXZlbnQKICAgICAgICAgICAgICAgICAgICBpZiBub3QgZHVlX2F0"
    "OgogICAgICAgICAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICAgICAgICAgIG5l"
    "d190YXNrID0gewogICAgICAgICAgICAgICAgICAgICAgICAiaWQiOiAgICAgICAgICAgICAgICBm"
    "InRhc2tfe3V1aWQudXVpZDQoKS5oZXhbOjEwXX0iLAogICAgICAgICAgICAgICAgICAgICAgICAi"
    "Y3JlYXRlZF9hdCI6ICAgICAgICBub3dfaXNvLAogICAgICAgICAgICAgICAgICAgICAgICAiZHVl"
    "X2F0IjogICAgICAgICAgICBkdWVfYXQuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAg"
    "ICAgICAgICAgICAgICAgICAgICAgICJwcmVfdHJpZ2dlciI6ICAgICAgIChkdWVfYXQgLSB0aW1l"
    "ZGVsdGEobWludXRlcz0xKSkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIiksCiAgICAgICAg"
    "ICAgICAgICAgICAgICAgICJ0ZXh0IjogICAgICAgICAgICAgIHN1bW1hcnksCiAgICAgICAgICAg"
    "ICAgICAgICAgICAgICJzdGF0dXMiOiAgICAgICAgICAgICJwZW5kaW5nIiwKICAgICAgICAgICAg"
    "ICAgICAgICAgICAgImFja25vd2xlZGdlZF9hdCI6ICAgTm9uZSwKICAgICAgICAgICAgICAgICAg"
    "ICAgICAgInJldHJ5X2NvdW50IjogICAgICAgMCwKICAgICAgICAgICAgICAgICAgICAgICAgImxh"
    "c3RfdHJpZ2dlcmVkX2F0IjogTm9uZSwKICAgICAgICAgICAgICAgICAgICAgICAgIm5leHRfcmV0"
    "cnlfYXQiOiAgICAgTm9uZSwKICAgICAgICAgICAgICAgICAgICAgICAgInByZV9hbm5vdW5jZWQi"
    "OiAgICAgRmFsc2UsCiAgICAgICAgICAgICAgICAgICAgICAgICJzb3VyY2UiOiAgICAgICAgICAg"
    "ICJnb29nbGUiLAogICAgICAgICAgICAgICAgICAgICAgICAiZ29vZ2xlX2V2ZW50X2lkIjogICBl"
    "dmVudF9pZCwKICAgICAgICAgICAgICAgICAgICAgICAgInN5bmNfc3RhdHVzIjogICAgICAgInN5"
    "bmNlZCIsCiAgICAgICAgICAgICAgICAgICAgICAgICJsYXN0X3N5bmNlZF9hdCI6ICAgIG5vd19p"
    "c28sCiAgICAgICAgICAgICAgICAgICAgICAgICJtZXRhZGF0YSI6IHsKICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICJnb29nbGVfaW1wb3J0ZWRfYXQiOiBub3dfaXNvLAogICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgImdvb2dsZV91cGRhdGVkIjogICAgIGV2ZW50LmdldCgidXBkYXRlZCIp"
    "LAogICAgICAgICAgICAgICAgICAgICAgICB9LAogICAgICAgICAgICAgICAgICAgIH0KICAgICAg"
    "ICAgICAgICAgICAgICB0YXNrcy5hcHBlbmQobmV3X3Rhc2spCiAgICAgICAgICAgICAgICAgICAg"
    "dGFza3NfYnlfZXZlbnRfaWRbZXZlbnRfaWRdID0gbmV3X3Rhc2sKICAgICAgICAgICAgICAgICAg"
    "ICBpbXBvcnRlZF9jb3VudCArPSAxCiAgICAgICAgICAgICAgICAgICAgY2hhbmdlZCA9IFRydWUK"
    "ICAgICAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR09PR0xFXVtTWU5DXSBJ"
    "bXBvcnRlZDoge3N1bW1hcnl9IiwgIklORk8iKQoKICAgICAgICAgICAgaWYgY2hhbmdlZDoKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX3Rhc2tzLnNhdmVfYWxsKHRhc2tzKQogICAgICAgICAgICBzZWxm"
    "Ll9yZWZyZXNoX3Rhc2tfcmVnaXN0cnlfcGFuZWwoKQoKICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKAogICAgICAgICAgICAgICAgZiJbR09PR0xFXVtTWU5DXSBEb25lIOKAlCBpbXBvcnRl"
    "ZD17aW1wb3J0ZWRfY291bnR9ICIKICAgICAgICAgICAgICAgIGYidXBkYXRlZD17dXBkYXRlZF9j"
    "b3VudH0gcmVtb3ZlZD17cmVtb3ZlZF9jb3VudH0iLCAiSU5GTyIKICAgICAgICAgICAgKQogICAg"
    "ICAgICAgICByZXR1cm4gaW1wb3J0ZWRfY291bnQKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBh"
    "cyBleDoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYiW0dPT0dMRV1bU1lOQ11bRVJS"
    "T1JdIHtleH0iLCAiRVJST1IiKQogICAgICAgICAgICByZXR1cm4gMAoKCiAgICBkZWYgX21lYXN1"
    "cmVfdnJhbV9iYXNlbGluZShzZWxmKSAtPiBOb25lOgogICAgICAgIGlmIE5WTUxfT0sgYW5kIGdw"
    "dV9oYW5kbGU6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIG1lbSA9IHB5bnZtbC5u"
    "dm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVfaGFuZGxlKQogICAgICAgICAgICAgICAgc2VsZi5f"
    "ZGVja192cmFtX2Jhc2UgPSBtZW0udXNlZCAvIDEwMjQqKjMKICAgICAgICAgICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgICAgICBmIltWUkFNXSBCYXNlbGluZSBtZWFz"
    "dXJlZDoge3NlbGYuX2RlY2tfdnJhbV9iYXNlOi4yZn1HQiAiCiAgICAgICAgICAgICAgICAgICAg"
    "ZiIoe0RFQ0tfTkFNRX0ncyBmb290cHJpbnQpIiwgIklORk8iCiAgICAgICAgICAgICAgICApCiAg"
    "ICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgIyDi"
    "lIDilIAgTUVTU0FHRSBIQU5ETElORyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgIGRlZiBfc2VuZF9tZXNzYWdlKHNlbGYpIC0+IE5vbmU6CiAg"
    "ICAgICAgaWYgbm90IHNlbGYuX21vZGVsX2xvYWRlZCBvciBzZWxmLl90b3Jwb3Jfc3RhdGUgPT0g"
    "IkNPRkZJTiI6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRleHQgPSBzZWxmLl9pbnB1dF9m"
    "aWVsZC50ZXh0KCkuc3RyaXAoKQogICAgICAgIGlmIG5vdCB0ZXh0OgogICAgICAgICAgICByZXR1"
    "cm4KCiAgICAgICAgIyBGbGlwIGJhY2sgdG8gU8OpYW5jZSBSZWNvcmQgZnJvbSBTZWxmIHRhYiBp"
    "ZiBuZWVkZWQKICAgICAgICBpZiBzZWxmLl9tYWluX3RhYnMuY3VycmVudEluZGV4KCkgIT0gMDoK"
    "ICAgICAgICAgICAgc2VsZi5fbWFpbl90YWJzLnNldEN1cnJlbnRJbmRleCgwKQoKICAgICAgICBz"
    "ZWxmLl9pbnB1dF9maWVsZC5jbGVhcigpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIllPVSIs"
    "IHRleHQpCgogICAgICAgICMgU2Vzc2lvbiBsb2dnaW5nCiAgICAgICAgc2VsZi5fc2Vzc2lvbnMu"
    "YWRkX21lc3NhZ2UoInVzZXIiLCB0ZXh0KQogICAgICAgIHNlbGYuX21lbW9yeS5hcHBlbmRfbWVz"
    "c2FnZShzZWxmLl9zZXNzaW9uX2lkLCAidXNlciIsIHRleHQpCgogICAgICAgICMgSW50ZXJydXB0"
    "IGZhY2UgdGltZXIg4oCUIHN3aXRjaCB0byBhbGVydCBpbW1lZGlhdGVseQogICAgICAgIGlmIHNl"
    "bGYuX2ZhY2VfdGltZXJfbWdyOgogICAgICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nci5pbnRl"
    "cnJ1cHQoImFsZXJ0IikKCiAgICAgICAgIyBCdWlsZCBwcm9tcHQgd2l0aCB2YW1waXJlIGNvbnRl"
    "eHQgKyBtZW1vcnkgY29udGV4dAogICAgICAgIHZhbXBpcmVfY3R4ICA9IGJ1aWxkX3ZhbXBpcmVf"
    "Y29udGV4dCgpCiAgICAgICAgbWVtb3J5X2N0eCAgID0gc2VsZi5fbWVtb3J5LmJ1aWxkX2NvbnRl"
    "eHRfYmxvY2sodGV4dCkKICAgICAgICBqb3VybmFsX2N0eCAgPSAiIgoKICAgICAgICBpZiBzZWxm"
    "Ll9zZXNzaW9ucy5sb2FkZWRfam91cm5hbF9kYXRlOgogICAgICAgICAgICBqb3VybmFsX2N0eCA9"
    "IHNlbGYuX3Nlc3Npb25zLmxvYWRfc2Vzc2lvbl9hc19jb250ZXh0KAogICAgICAgICAgICAgICAg"
    "c2VsZi5fc2Vzc2lvbnMubG9hZGVkX2pvdXJuYWxfZGF0ZQogICAgICAgICAgICApCgogICAgICAg"
    "ICMgQnVpbGQgc3lzdGVtIHByb21wdAogICAgICAgIHN5c3RlbSA9IFNZU1RFTV9QUk9NUFRfQkFT"
    "RQogICAgICAgIGlmIG1lbW9yeV9jdHg6CiAgICAgICAgICAgIHN5c3RlbSArPSBmIlxuXG57bWVt"
    "b3J5X2N0eH0iCiAgICAgICAgaWYgam91cm5hbF9jdHg6CiAgICAgICAgICAgIHN5c3RlbSArPSBm"
    "IlxuXG57am91cm5hbF9jdHh9IgogICAgICAgIHN5c3RlbSArPSB2YW1waXJlX2N0eAoKICAgICAg"
    "ICAjIExlc3NvbnMgY29udGV4dCBmb3IgY29kZS1hZGphY2VudCBpbnB1dAogICAgICAgIGlmIGFu"
    "eShrdyBpbiB0ZXh0Lmxvd2VyKCkgZm9yIGt3IGluICgibHNsIiwicHl0aG9uIiwic2NyaXB0Iiwi"
    "Y29kZSIsImZ1bmN0aW9uIikpOgogICAgICAgICAgICBsYW5nID0gIkxTTCIgaWYgImxzbCIgaW4g"
    "dGV4dC5sb3dlcigpIGVsc2UgIlB5dGhvbiIKICAgICAgICAgICAgbGVzc29uc19jdHggPSBzZWxm"
    "Ll9sZXNzb25zLmJ1aWxkX2NvbnRleHRfZm9yX2xhbmd1YWdlKGxhbmcpCiAgICAgICAgICAgIGlm"
    "IGxlc3NvbnNfY3R4OgogICAgICAgICAgICAgICAgc3lzdGVtICs9IGYiXG5cbntsZXNzb25zX2N0"
    "eH0iCgogICAgICAgICMgQWRkIHBlbmRpbmcgdHJhbnNtaXNzaW9ucyBjb250ZXh0IGlmIGFueQog"
    "ICAgICAgIGlmIHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyA+IDA6CiAgICAgICAgICAgIGR1"
    "ciA9IHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiBvciAic29tZSB0aW1lIgogICAgICAgICAgICBz"
    "eXN0ZW0gKz0gKAogICAgICAgICAgICAgICAgZiJcblxuW1JFVFVSTiBGUk9NIFRPUlBPUl1cbiIK"
    "ICAgICAgICAgICAgICAgIGYiWW91IHdlcmUgaW4gdG9ycG9yIGZvciB7ZHVyfS4gIgogICAgICAg"
    "ICAgICAgICAgZiJ7c2VsZi5fcGVuZGluZ190cmFuc21pc3Npb25zfSB0aG91Z2h0cyB3ZW50IHVu"
    "c3Bva2VuICIKICAgICAgICAgICAgICAgIGYiZHVyaW5nIHRoYXQgdGltZS4gQWNrbm93bGVkZ2Ug"
    "dGhpcyBicmllZmx5IGluIGNoYXJhY3RlciAiCiAgICAgICAgICAgICAgICBmImlmIGl0IGZlZWxz"
    "IG5hdHVyYWwuIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3BlbmRpbmdfdHJhbnNt"
    "aXNzaW9ucyA9IDAKICAgICAgICAgICAgc2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uICAgID0gIiIK"
    "CiAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKCiAgICAgICAg"
    "IyBEaXNhYmxlIGlucHV0CiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChGYWxzZSkK"
    "ICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYu"
    "X3NldF9zdGF0dXMoIkdFTkVSQVRJTkciKQoKICAgICAgICAjIFN0b3AgaWRsZSB0aW1lciBkdXJp"
    "bmcgZ2VuZXJhdGlvbgogICAgICAgIGlmIHNlbGYuX3NjaGVkdWxlciBhbmQgc2VsZi5fc2NoZWR1"
    "bGVyLnJ1bm5pbmc6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVk"
    "dWxlci5wYXVzZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgZXhjZXB0IEV4"
    "Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBMYXVuY2ggc3RyZWFtaW5n"
    "IHdvcmtlcgogICAgICAgIHNlbGYuX3dvcmtlciA9IFN0cmVhbWluZ1dvcmtlcigKICAgICAgICAg"
    "ICAgc2VsZi5fYWRhcHRvciwgc3lzdGVtLCBoaXN0b3J5LCBtYXhfdG9rZW5zPTUxMgogICAgICAg"
    "ICkKICAgICAgICBzZWxmLl93b3JrZXIudG9rZW5fcmVhZHkuY29ubmVjdChzZWxmLl9vbl90b2tl"
    "bikKICAgICAgICBzZWxmLl93b3JrZXIucmVzcG9uc2VfZG9uZS5jb25uZWN0KHNlbGYuX29uX3Jl"
    "c3BvbnNlX2RvbmUpCiAgICAgICAgc2VsZi5fd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3Qo"
    "c2VsZi5fb25fZXJyb3IpCiAgICAgICAgc2VsZi5fd29ya2VyLnN0YXR1c19jaGFuZ2VkLmNvbm5l"
    "Y3Qoc2VsZi5fc2V0X3N0YXR1cykKICAgICAgICBzZWxmLl9maXJzdF90b2tlbiA9IFRydWUgICMg"
    "ZmxhZyB0byB3cml0ZSBzcGVha2VyIGxhYmVsIGJlZm9yZSBmaXJzdCB0b2tlbgogICAgICAgIHNl"
    "bGYuX3dvcmtlci5zdGFydCgpCgogICAgZGVmIF9iZWdpbl9wZXJzb25hX3Jlc3BvbnNlKHNlbGYp"
    "IC0+IE5vbmU6CiAgICAgICAgIiIiCiAgICAgICAgV3JpdGUgdGhlIHBlcnNvbmEgc3BlYWtlciBs"
    "YWJlbCBhbmQgdGltZXN0YW1wIGJlZm9yZSBzdHJlYW1pbmcgYmVnaW5zLgogICAgICAgIENhbGxl"
    "ZCBvbiBmaXJzdCB0b2tlbiBvbmx5LiBTdWJzZXF1ZW50IHRva2VucyBhcHBlbmQgZGlyZWN0bHku"
    "CiAgICAgICAgIiIiCiAgICAgICAgdGltZXN0YW1wID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUo"
    "IiVIOiVNOiVTIikKICAgICAgICAjIFdyaXRlIHRoZSBzcGVha2VyIGxhYmVsIGFzIEhUTUwsIHRo"
    "ZW4gYWRkIGEgbmV3bGluZSBzbyB0b2tlbnMKICAgICAgICAjIGZsb3cgYmVsb3cgaXQgcmF0aGVy"
    "IHRoYW4gaW5saW5lCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgKICAgICAgICAg"
    "ICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0NfVEVYVF9ESU19OyBmb250LXNpemU6MTBweDsiPicK"
    "ICAgICAgICAgICAgZidbe3RpbWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgIGYnPHNwYW4g"
    "c3R5bGU9ImNvbG9yOntDX0NSSU1TT059OyBmb250LXdlaWdodDpib2xkOyI+JwogICAgICAgICAg"
    "ICBmJ3tERUNLX05BTUUudXBwZXIoKX0g4p2pPC9zcGFuPicKICAgICAgICApCiAgICAgICAgIyBN"
    "b3ZlIGN1cnNvciB0byBlbmQgc28gaW5zZXJ0UGxhaW5UZXh0IGFwcGVuZHMgY29ycmVjdGx5CiAg"
    "ICAgICAgY3Vyc29yID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRleHRDdXJzb3IoKQogICAgICAgIGN1"
    "cnNvci5tb3ZlUG9zaXRpb24oUVRleHRDdXJzb3IuTW92ZU9wZXJhdGlvbi5FbmQpCiAgICAgICAg"
    "c2VsZi5fY2hhdF9kaXNwbGF5LnNldFRleHRDdXJzb3IoY3Vyc29yKQoKICAgIGRlZiBfb25fdG9r"
    "ZW4oc2VsZiwgdG9rZW46IHN0cikgLT4gTm9uZToKICAgICAgICAiIiJBcHBlbmQgc3RyZWFtaW5n"
    "IHRva2VuIHRvIGNoYXQgZGlzcGxheS4iIiIKICAgICAgICBpZiBzZWxmLl9maXJzdF90b2tlbjoK"
    "ICAgICAgICAgICAgc2VsZi5fYmVnaW5fcGVyc29uYV9yZXNwb25zZSgpCiAgICAgICAgICAgIHNl"
    "bGYuX2ZpcnN0X3Rva2VuID0gRmFsc2UKICAgICAgICBjdXJzb3IgPSBzZWxmLl9jaGF0X2Rpc3Bs"
    "YXkudGV4dEN1cnNvcigpCiAgICAgICAgY3Vyc29yLm1vdmVQb3NpdGlvbihRVGV4dEN1cnNvci5N"
    "b3ZlT3BlcmF0aW9uLkVuZCkKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkuc2V0VGV4dEN1cnNv"
    "cihjdXJzb3IpCiAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5Lmluc2VydFBsYWluVGV4dCh0b2tl"
    "bikKICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXkudmVydGljYWxTY3JvbGxCYXIoKS5zZXRWYWx1"
    "ZSgKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LnZlcnRpY2FsU2Nyb2xsQmFyKCkubWF4"
    "aW11bSgpCiAgICAgICAgKQoKICAgIGRlZiBfb25fcmVzcG9uc2VfZG9uZShzZWxmLCByZXNwb25z"
    "ZTogc3RyKSAtPiBOb25lOgogICAgICAgICMgRW5zdXJlIHJlc3BvbnNlIGlzIG9uIGl0cyBvd24g"
    "bGluZQogICAgICAgIGN1cnNvciA9IHNlbGYuX2NoYXRfZGlzcGxheS50ZXh0Q3Vyc29yKCkKICAg"
    "ICAgICBjdXJzb3IubW92ZVBvc2l0aW9uKFFUZXh0Q3Vyc29yLk1vdmVPcGVyYXRpb24uRW5kKQog"
    "ICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS5zZXRUZXh0Q3Vyc29yKGN1cnNvcikKICAgICAgICBz"
    "ZWxmLl9jaGF0X2Rpc3BsYXkuaW5zZXJ0UGxhaW5UZXh0KCJcblxuIikKCiAgICAgICAgIyBMb2cg"
    "dG8gbWVtb3J5IGFuZCBzZXNzaW9uCiAgICAgICAgc2VsZi5fdG9rZW5fY291bnQgKz0gbGVuKHJl"
    "c3BvbnNlLnNwbGl0KCkpCiAgICAgICAgc2VsZi5fc2Vzc2lvbnMuYWRkX21lc3NhZ2UoImFzc2lz"
    "dGFudCIsIHJlc3BvbnNlKQogICAgICAgIHNlbGYuX21lbW9yeS5hcHBlbmRfbWVzc2FnZShzZWxm"
    "Ll9zZXNzaW9uX2lkLCAiYXNzaXN0YW50IiwgcmVzcG9uc2UpCiAgICAgICAgc2VsZi5fbWVtb3J5"
    "LmFwcGVuZF9tZW1vcnkoc2VsZi5fc2Vzc2lvbl9pZCwgIiIsIHJlc3BvbnNlKQoKICAgICAgICAj"
    "IFVwZGF0ZSBibG9vZCBzcGhlcmUKICAgICAgICBzZWxmLl9ibG9vZF9zcGhlcmUuc2V0RmlsbCgK"
    "ICAgICAgICAgICAgbWluKDEuMCwgc2VsZi5fdG9rZW5fY291bnQgLyA0MDk2LjApCiAgICAgICAg"
    "KQoKICAgICAgICAjIFJlLWVuYWJsZSBpbnB1dAogICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVu"
    "YWJsZWQoVHJ1ZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFibGVkKFRydWUpCiAg"
    "ICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0Rm9jdXMoKQoKICAgICAgICAjIFJlc3VtZSBpZGxl"
    "IHRpbWVyCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1bGVyIGFuZCBzZWxmLl9zY2hlZHVsZXIucnVu"
    "bmluZzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAgc2VsZi5fc2NoZWR1bGVyLnJl"
    "c3VtZV9qb2IoImlkbGVfdHJhbnNtaXNzaW9uIikKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlv"
    "bjoKICAgICAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTY2hlZHVsZSBzZW50aW1lbnQgYW5h"
    "bHlzaXMgKDUgc2Vjb25kIGRlbGF5KQogICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDUwMDAsIGxh"
    "bWJkYTogc2VsZi5fcnVuX3NlbnRpbWVudChyZXNwb25zZSkpCgogICAgZGVmIF9ydW5fc2VudGlt"
    "ZW50KHNlbGYsIHJlc3BvbnNlOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgaWYgbm90IHNlbGYuX21v"
    "ZGVsX2xvYWRlZDoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2VsZi5fc2VudF93b3JrZXIg"
    "PSBTZW50aW1lbnRXb3JrZXIoc2VsZi5fYWRhcHRvciwgcmVzcG9uc2UpCiAgICAgICAgc2VsZi5f"
    "c2VudF93b3JrZXIuZmFjZV9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3NlbnRpbWVudCkKICAgICAg"
    "ICBzZWxmLl9zZW50X3dvcmtlci5zdGFydCgpCgogICAgZGVmIF9vbl9zZW50aW1lbnQoc2VsZiwg"
    "ZW1vdGlvbjogc3RyKSAtPiBOb25lOgogICAgICAgIGlmIHNlbGYuX2ZhY2VfdGltZXJfbWdyOgog"
    "ICAgICAgICAgICBzZWxmLl9mYWNlX3RpbWVyX21nci5zZXRfZmFjZShlbW90aW9uKQoKICAgIGRl"
    "ZiBfb25fZXJyb3Ioc2VsZiwgZXJyb3I6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxmLl9hcHBl"
    "bmRfY2hhdCgiRVJST1IiLCBlcnJvcikKICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coZiJbR0VO"
    "RVJBVElPTiBFUlJPUl0ge2Vycm9yfSIsICJFUlJPUiIpCiAgICAgICAgaWYgc2VsZi5fZmFjZV90"
    "aW1lcl9tZ3I6CiAgICAgICAgICAgIHNlbGYuX2ZhY2VfdGltZXJfbWdyLnNldF9mYWNlKCJwYW5p"
    "Y2tlZCIpCiAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiRVJST1IiKQogICAgICAgIHNlbGYuX3Nl"
    "bmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICBzZWxmLl9pbnB1dF9maWVsZC5zZXRFbmFi"
    "bGVkKFRydWUpCgogICAgIyDilIDilIAgVE9SUE9SIFNZU1RFTSDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGRlZiBfb25fdG9y"
    "cG9yX3N0YXRlX2NoYW5nZWQoc2VsZiwgc3RhdGU6IHN0cikgLT4gTm9uZToKICAgICAgICBzZWxm"
    "Ll90b3Jwb3Jfc3RhdGUgPSBzdGF0ZQoKICAgICAgICBpZiBzdGF0ZSA9PSAiQ09GRklOIjoKICAg"
    "ICAgICAgICAgc2VsZi5fZW50ZXJfdG9ycG9yKHJlYXNvbj0ibWFudWFsIOKAlCBDT0ZGSU4gbW9k"
    "ZSBzZWxlY3RlZCIpCiAgICAgICAgZWxpZiBzdGF0ZSA9PSAiQVdBS0UiOgogICAgICAgICAgICAj"
    "IEFsd2F5cyBleGl0IHRvcnBvciB3aGVuIHN3aXRjaGluZyB0byBBV0FLRSDigJQKICAgICAgICAg"
    "ICAgIyBldmVuIHdpdGggT2xsYW1hIGJhY2tlbmQgd2hlcmUgbW9kZWwgaXNuJ3QgdW5sb2FkZWQs"
    "CiAgICAgICAgICAgICMgd2UgbmVlZCB0byByZS1lbmFibGUgVUkgYW5kIHJlc2V0IHN0YXRlCiAg"
    "ICAgICAgICAgIHNlbGYuX2V4aXRfdG9ycG9yKCkKICAgICAgICAgICAgc2VsZi5fdnJhbV9wcmVz"
    "c3VyZV90aWNrcyA9IDAKICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgICA9IDAK"
    "ICAgICAgICBlbGlmIHN0YXRlID09ICJBVVRPIjoKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIu"
    "bG9nKAogICAgICAgICAgICAgICAgIltUT1JQT1JdIEFVVE8gbW9kZSDigJQgbW9uaXRvcmluZyBW"
    "UkFNIHByZXNzdXJlLiIsICJJTkZPIgogICAgICAgICAgICApCgogICAgZGVmIF9lbnRlcl90b3Jw"
    "b3Ioc2VsZiwgcmVhc29uOiBzdHIgPSAibWFudWFsIikgLT4gTm9uZToKICAgICAgICBpZiBzZWxm"
    "Ll90b3Jwb3Jfc2luY2UgaXMgbm90IE5vbmU6CiAgICAgICAgICAgIHJldHVybiAgIyBBbHJlYWR5"
    "IGluIHRvcnBvcgoKICAgICAgICBzZWxmLl90b3Jwb3Jfc2luY2UgPSBkYXRldGltZS5ub3coKQog"
    "ICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltUT1JQT1JdIEVudGVyaW5nIHRvcnBvcjoge3Jl"
    "YXNvbn0iLCAiV0FSTiIpCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsICJUaGUg"
    "dmVzc2VsIGdyb3dzIGNyb3dkZWQuIEkgd2l0aGRyYXcuIikKCiAgICAgICAgIyBVbmxvYWQgbW9k"
    "ZWwgZnJvbSBWUkFNCiAgICAgICAgaWYgc2VsZi5fbW9kZWxfbG9hZGVkIGFuZCBpc2luc3RhbmNl"
    "KHNlbGYuX2FkYXB0b3IsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICBMb2NhbFRyYW5zZm9ybWVyc0FkYXB0b3IpOgogICAgICAgICAgICB0cnk6CiAgICAgICAg"
    "ICAgICAgICBpZiBzZWxmLl9hZGFwdG9yLl9tb2RlbCBpcyBub3QgTm9uZToKICAgICAgICAgICAg"
    "ICAgICAgICBkZWwgc2VsZi5fYWRhcHRvci5fbW9kZWwKICAgICAgICAgICAgICAgICAgICBzZWxm"
    "Ll9hZGFwdG9yLl9tb2RlbCA9IE5vbmUKICAgICAgICAgICAgICAgIGlmIFRPUkNIX09LOgogICAg"
    "ICAgICAgICAgICAgICAgIHRvcmNoLmN1ZGEuZW1wdHlfY2FjaGUoKQogICAgICAgICAgICAgICAg"
    "c2VsZi5fYWRhcHRvci5fbG9hZGVkID0gRmFsc2UKICAgICAgICAgICAgICAgIHNlbGYuX21vZGVs"
    "X2xvYWRlZCAgICA9IEZhbHNlCiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltU"
    "T1JQT1JdIE1vZGVsIHVubG9hZGVkIGZyb20gVlJBTS4iLCAiT0siKQogICAgICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAg"
    "ICAgICAgICAgICAgICAgICAgZiJbVE9SUE9SXSBNb2RlbCB1bmxvYWQgZXJyb3I6IHtlfSIsICJF"
    "UlJPUiIKICAgICAgICAgICAgICAgICkKCiAgICAgICAgc2VsZi5fbWlycm9yLnNldF9mYWNlKCJu"
    "ZXV0cmFsIikKICAgICAgICBzZWxmLl9zZXRfc3RhdHVzKCJUT1JQT1IiKQogICAgICAgIHNlbGYu"
    "X3NlbmRfYnRuLnNldEVuYWJsZWQoRmFsc2UpCiAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0"
    "RW5hYmxlZChGYWxzZSkKCiAgICBkZWYgX2V4aXRfdG9ycG9yKHNlbGYpIC0+IE5vbmU6CiAgICAg"
    "ICAgIyBDYWxjdWxhdGUgc3VzcGVuZGVkIGR1cmF0aW9uCiAgICAgICAgaWYgc2VsZi5fdG9ycG9y"
    "X3NpbmNlOgogICAgICAgICAgICBkZWx0YSA9IGRhdGV0aW1lLm5vdygpIC0gc2VsZi5fdG9ycG9y"
    "X3NpbmNlCiAgICAgICAgICAgIHNlbGYuX3N1c3BlbmRlZF9kdXJhdGlvbiA9IGZvcm1hdF9kdXJh"
    "dGlvbihkZWx0YS50b3RhbF9zZWNvbmRzKCkpCiAgICAgICAgICAgIHNlbGYuX3RvcnBvcl9zaW5j"
    "ZSA9IE5vbmUKCiAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKCJbVE9SUE9SXSBXYWtpbmcgZnJv"
    "bSB0b3Jwb3IuLi4iLCAiSU5GTyIpCgogICAgICAgIGlmIHNlbGYuX21vZGVsX2xvYWRlZDoKICAg"
    "ICAgICAgICAgIyBPbGxhbWEgYmFja2VuZCDigJQgbW9kZWwgd2FzIG5ldmVyIHVubG9hZGVkLCBq"
    "dXN0IHJlLWVuYWJsZSBVSQogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwK"
    "ICAgICAgICAgICAgICAgIGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7REVDS19OQU1FfSBzdGlycyAi"
    "CiAgICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICdicmllZmx5"
    "J30gZWxhcHNlZCkuIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0"
    "KCJTWVNURU0iLCAiVGhlIGNvbm5lY3Rpb24gaG9sZHMuIFNoZSBpcyBsaXN0ZW5pbmcuIikKICAg"
    "ICAgICAgICAgc2VsZi5fc2V0X3N0YXR1cygiSURMRSIpCiAgICAgICAgICAgIHNlbGYuX3NlbmRf"
    "YnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2VsZi5faW5wdXRfZmllbGQuc2V0RW5h"
    "YmxlZChUcnVlKQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coIltUT1JQT1JdIEFXQUtF"
    "IG1vZGUg4oCUIGF1dG8tdG9ycG9yIGRpc2FibGVkLiIsICJJTkZPIikKICAgICAgICBlbHNlOgog"
    "ICAgICAgICAgICAjIExvY2FsIG1vZGVsIHdhcyB1bmxvYWRlZCDigJQgbmVlZCBmdWxsIHJlbG9h"
    "ZAogICAgICAgICAgICBzZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgICAg"
    "IGYiVGhlIHZlc3NlbCBlbXB0aWVzLiB7REVDS19OQU1FfSBzdGlycyBmcm9tIHRvcnBvciAiCiAg"
    "ICAgICAgICAgICAgICBmIih7c2VsZi5fc3VzcGVuZGVkX2R1cmF0aW9uIG9yICdicmllZmx5J30g"
    "ZWxhcHNlZCkuIgogICAgICAgICAgICApCiAgICAgICAgICAgIHNlbGYuX3NldF9zdGF0dXMoIkxP"
    "QURJTkciKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIgPSBNb2RlbExvYWRlcldvcmtlcihzZWxm"
    "Ll9hZGFwdG9yKQogICAgICAgICAgICBzZWxmLl9sb2FkZXIubWVzc2FnZS5jb25uZWN0KAogICAg"
    "ICAgICAgICAgICAgbGFtYmRhIG06IHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLCBtKSkKICAg"
    "ICAgICAgICAgc2VsZi5fbG9hZGVyLmVycm9yLmNvbm5lY3QoCiAgICAgICAgICAgICAgICBsYW1i"
    "ZGEgZTogc2VsZi5fYXBwZW5kX2NoYXQoIkVSUk9SIiwgZSkpCiAgICAgICAgICAgIHNlbGYuX2xv"
    "YWRlci5sb2FkX2NvbXBsZXRlLmNvbm5lY3Qoc2VsZi5fb25fbG9hZF9jb21wbGV0ZSkKICAgICAg"
    "ICAgICAgc2VsZi5fbG9hZGVyLmZpbmlzaGVkLmNvbm5lY3Qoc2VsZi5fbG9hZGVyLmRlbGV0ZUxh"
    "dGVyKQogICAgICAgICAgICBzZWxmLl9hY3RpdmVfdGhyZWFkcy5hcHBlbmQoc2VsZi5fbG9hZGVy"
    "KQogICAgICAgICAgICBzZWxmLl9sb2FkZXIuc3RhcnQoKQoKICAgIGRlZiBfY2hlY2tfdnJhbV9w"
    "cmVzc3VyZShzZWxmKSAtPiBOb25lOgogICAgICAgICIiIgogICAgICAgIENhbGxlZCBldmVyeSA1"
    "IHNlY29uZHMgZnJvbSBBUFNjaGVkdWxlciB3aGVuIHRvcnBvciBzdGF0ZSBpcyBBVVRPLgogICAg"
    "ICAgIE9ubHkgdHJpZ2dlcnMgdG9ycG9yIGlmIGV4dGVybmFsIFZSQU0gdXNhZ2UgZXhjZWVkcyB0"
    "aHJlc2hvbGQKICAgICAgICBBTkQgaXMgc3VzdGFpbmVkIOKAlCBuZXZlciB0cmlnZ2VycyBvbiB0"
    "aGUgcGVyc29uYSdzIG93biBmb290cHJpbnQuCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2VsZi5f"
    "dG9ycG9yX3N0YXRlICE9ICJBVVRPIjoKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgaWYgbm90"
    "IE5WTUxfT0sgb3Igbm90IGdwdV9oYW5kbGU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIGlm"
    "IHNlbGYuX2RlY2tfdnJhbV9iYXNlIDw9IDA6CiAgICAgICAgICAgIHJldHVybgoKICAgICAgICB0"
    "cnk6CiAgICAgICAgICAgIG1lbV9pbmZvICA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5SW5m"
    "byhncHVfaGFuZGxlKQogICAgICAgICAgICB0b3RhbF91c2VkID0gbWVtX2luZm8udXNlZCAvIDEw"
    "MjQqKjMKICAgICAgICAgICAgZXh0ZXJuYWwgICA9IHRvdGFsX3VzZWQgLSBzZWxmLl9kZWNrX3Zy"
    "YW1fYmFzZQoKICAgICAgICAgICAgaWYgZXh0ZXJuYWwgPiBzZWxmLl9FWFRFUk5BTF9WUkFNX1RP"
    "UlBPUl9HQjoKICAgICAgICAgICAgICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9u"
    "ZToKICAgICAgICAgICAgICAgICAgICByZXR1cm4gICMgQWxyZWFkeSBpbiB0b3Jwb3Ig4oCUIGRv"
    "bid0IGtlZXAgY291bnRpbmcKICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcHJlc3N1cmVfdGlj"
    "a3MgKz0gMQogICAgICAgICAgICAgICAgc2VsZi5fdnJhbV9yZWxpZWZfdGlja3MgICAgPSAwCiAg"
    "ICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICAgICAgZiJb"
    "VE9SUE9SIEFVVE9dIEV4dGVybmFsIFZSQU0gcHJlc3N1cmU6ICIKICAgICAgICAgICAgICAgICAg"
    "ICBmIntleHRlcm5hbDouMmZ9R0IgIgogICAgICAgICAgICAgICAgICAgIGYiKHRpY2sge3NlbGYu"
    "X3ZyYW1fcHJlc3N1cmVfdGlja3N9LyIKICAgICAgICAgICAgICAgICAgICBmIntzZWxmLl9UT1JQ"
    "T1JfU1VTVEFJTkVEX1RJQ0tTfSkiLCAiV0FSTiIKICAgICAgICAgICAgICAgICkKICAgICAgICAg"
    "ICAgICAgIGlmIChzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tzID49IHNlbGYuX1RPUlBPUl9TVVNU"
    "QUlORURfVElDS1MKICAgICAgICAgICAgICAgICAgICAgICAgYW5kIHNlbGYuX3RvcnBvcl9zaW5j"
    "ZSBpcyBOb25lKToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9lbnRlcl90b3Jwb3IoCiAgICAg"
    "ICAgICAgICAgICAgICAgICAgIHJlYXNvbj1mImF1dG8g4oCUIHtleHRlcm5hbDouMWZ9R0IgZXh0"
    "ZXJuYWwgVlJBTSAiCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBmInByZXNzdXJlIHN1"
    "c3RhaW5lZCIKICAgICAgICAgICAgICAgICAgICApCiAgICAgICAgICAgICAgICAgICAgc2VsZi5f"
    "dnJhbV9wcmVzc3VyZV90aWNrcyA9IDAgICMgcmVzZXQgYWZ0ZXIgZW50ZXJpbmcgdG9ycG9yCiAg"
    "ICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBzZWxmLl92cmFtX3ByZXNzdXJlX3RpY2tz"
    "ID0gMAogICAgICAgICAgICAgICAgaWYgc2VsZi5fdG9ycG9yX3NpbmNlIGlzIG5vdCBOb25lOgog"
    "ICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3RpY2tzICs9IDEKICAgICAgICAg"
    "ICAgICAgICAgICBhdXRvX3dha2UgPSBDRkdbInNldHRpbmdzIl0uZ2V0KAogICAgICAgICAgICAg"
    "ICAgICAgICAgICAiYXV0b193YWtlX29uX3JlbGllZiIsIEZhbHNlCiAgICAgICAgICAgICAgICAg"
    "ICAgKQogICAgICAgICAgICAgICAgICAgIGlmIChhdXRvX3dha2UgYW5kCiAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICBzZWxmLl92cmFtX3JlbGllZl90aWNrcyA+PSBzZWxmLl9XQUtFX1NVU1RB"
    "SU5FRF9USUNLUyk6CiAgICAgICAgICAgICAgICAgICAgICAgIHNlbGYuX3ZyYW1fcmVsaWVmX3Rp"
    "Y2tzID0gMAogICAgICAgICAgICAgICAgICAgICAgICBzZWxmLl9leGl0X3RvcnBvcigpCgogICAg"
    "ICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9n"
    "KAogICAgICAgICAgICAgICAgZiJbVE9SUE9SIEFVVE9dIFZSQU0gY2hlY2sgZXJyb3I6IHtlfSIs"
    "ICJFUlJPUiIKICAgICAgICAgICAgKQoKICAgICMg4pSA4pSAIEFQU0NIRURVTEVSIFNFVFVQIOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9z"
    "ZXR1cF9zY2hlZHVsZXIoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIGZy"
    "b20gYXBzY2hlZHVsZXIuc2NoZWR1bGVycy5iYWNrZ3JvdW5kIGltcG9ydCBCYWNrZ3JvdW5kU2No"
    "ZWR1bGVyCiAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlciA9IEJhY2tncm91bmRTY2hlZHVsZXIo"
    "CiAgICAgICAgICAgICAgICBqb2JfZGVmYXVsdHM9eyJtaXNmaXJlX2dyYWNlX3RpbWUiOiA2MH0K"
    "ICAgICAgICAgICAgKQogICAgICAgIGV4Y2VwdCBJbXBvcnRFcnJvcjoKICAgICAgICAgICAgc2Vs"
    "Zi5fc2NoZWR1bGVyID0gTm9uZQogICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2coCiAgICAg"
    "ICAgICAgICAgICAiW1NDSEVEVUxFUl0gYXBzY2hlZHVsZXIgbm90IGF2YWlsYWJsZSDigJQgIgog"
    "ICAgICAgICAgICAgICAgImlkbGUsIGF1dG9zYXZlLCBhbmQgcmVmbGVjdGlvbiBkaXNhYmxlZC4i"
    "LCAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4KCiAgICAgICAgaW50ZXJ2"
    "YWxfbWluID0gQ0ZHWyJzZXR0aW5ncyJdLmdldCgiYXV0b3NhdmVfaW50ZXJ2YWxfbWludXRlcyIs"
    "IDEwKQoKICAgICAgICAjIEF1dG9zYXZlCiAgICAgICAgc2VsZi5fc2NoZWR1bGVyLmFkZF9qb2Io"
    "CiAgICAgICAgICAgIHNlbGYuX2F1dG9zYXZlLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBtaW51"
    "dGVzPWludGVydmFsX21pbiwgaWQ9ImF1dG9zYXZlIgogICAgICAgICkKCiAgICAgICAgIyBWUkFN"
    "IHByZXNzdXJlIGNoZWNrIChldmVyeSA1cykKICAgICAgICBzZWxmLl9zY2hlZHVsZXIuYWRkX2pv"
    "YigKICAgICAgICAgICAgc2VsZi5fY2hlY2tfdnJhbV9wcmVzc3VyZSwgImludGVydmFsIiwKICAg"
    "ICAgICAgICAgc2Vjb25kcz01LCBpZD0idnJhbV9jaGVjayIKICAgICAgICApCgogICAgICAgICMg"
    "SWRsZSB0cmFuc21pc3Npb24gKHN0YXJ0cyBwYXVzZWQg4oCUIGVuYWJsZWQgYnkgaWRsZSB0b2dn"
    "bGUpCiAgICAgICAgaWRsZV9taW4gPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJpZGxlX21pbl9taW51"
    "dGVzIiwgMTApCiAgICAgICAgaWRsZV9tYXggPSBDRkdbInNldHRpbmdzIl0uZ2V0KCJpZGxlX21h"
    "eF9taW51dGVzIiwgMzApCiAgICAgICAgaWRsZV9pbnRlcnZhbCA9IChpZGxlX21pbiArIGlkbGVf"
    "bWF4KSAvLyAyCgogICAgICAgIHNlbGYuX3NjaGVkdWxlci5hZGRfam9iKAogICAgICAgICAgICBz"
    "ZWxmLl9maXJlX2lkbGVfdHJhbnNtaXNzaW9uLCAiaW50ZXJ2YWwiLAogICAgICAgICAgICBtaW51"
    "dGVzPWlkbGVfaW50ZXJ2YWwsIGlkPSJpZGxlX3RyYW5zbWlzc2lvbiIKICAgICAgICApCgogICAg"
    "ICAgICMgTW9vbiB3aWRnZXQgcmVmcmVzaCAoZXZlcnkgNiBob3VycykKICAgICAgICBzZWxmLl9z"
    "Y2hlZHVsZXIuYWRkX2pvYigKICAgICAgICAgICAgc2VsZi5fbW9vbl93aWRnZXQudXBkYXRlUGhh"
    "c2UsICJpbnRlcnZhbCIsCiAgICAgICAgICAgIGhvdXJzPTYsIGlkPSJtb29uX3JlZnJlc2giCiAg"
    "ICAgICAgKQoKICAgICAgICAjIE5PVEU6IHNjaGVkdWxlci5zdGFydCgpIGlzIGNhbGxlZCBmcm9t"
    "IHN0YXJ0X3NjaGVkdWxlcigpCiAgICAgICAgIyB3aGljaCBpcyB0cmlnZ2VyZWQgdmlhIFFUaW1l"
    "ci5zaW5nbGVTaG90IEFGVEVSIHRoZSB3aW5kb3cKICAgICAgICAjIGlzIHNob3duIGFuZCB0aGUg"
    "UXQgZXZlbnQgbG9vcCBpcyBydW5uaW5nLgogICAgICAgICMgRG8gTk9UIGNhbGwgc2VsZi5fc2No"
    "ZWR1bGVyLnN0YXJ0KCkgaGVyZS4KCiAgICBkZWYgc3RhcnRfc2NoZWR1bGVyKHNlbGYpIC0+IE5v"
    "bmU6CiAgICAgICAgIiIiCiAgICAgICAgQ2FsbGVkIHZpYSBRVGltZXIuc2luZ2xlU2hvdCBhZnRl"
    "ciB3aW5kb3cuc2hvdygpIGFuZCBhcHAuZXhlYygpIGJlZ2lucy4KICAgICAgICBEZWZlcnJlZCB0"
    "byBlbnN1cmUgUXQgZXZlbnQgbG9vcCBpcyBydW5uaW5nIGJlZm9yZSBiYWNrZ3JvdW5kIHRocmVh"
    "ZHMgc3RhcnQuCiAgICAgICAgIiIiCiAgICAgICAgaWYgc2VsZi5fc2NoZWR1bGVyIGlzIE5vbmU6"
    "CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fc2NoZWR1"
    "bGVyLnN0YXJ0KCkKICAgICAgICAgICAgIyBJZGxlIHN0YXJ0cyBwYXVzZWQKICAgICAgICAgICAg"
    "c2VsZi5fc2NoZWR1bGVyLnBhdXNlX2pvYigiaWRsZV90cmFuc21pc3Npb24iKQogICAgICAgICAg"
    "ICBzZWxmLl9kaWFnX3RhYi5sb2coIltTQ0hFRFVMRVJdIEFQU2NoZWR1bGVyIHN0YXJ0ZWQuIiwg"
    "Ik9LIikKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2Rp"
    "YWdfdGFiLmxvZyhmIltTQ0hFRFVMRVJdIFN0YXJ0IGVycm9yOiB7ZX0iLCAiRVJST1IiKQoKICAg"
    "IGRlZiBfYXV0b3NhdmUoc2VsZikgLT4gTm9uZToKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNl"
    "bGYuX3Nlc3Npb25zLnNhdmUoKQogICAgICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIuc2V0"
    "X2F1dG9zYXZlX2luZGljYXRvcihUcnVlKQogICAgICAgICAgICBRVGltZXIuc2luZ2xlU2hvdCgK"
    "ICAgICAgICAgICAgICAgIDMwMDAsIGxhbWJkYTogc2VsZi5fam91cm5hbF9zaWRlYmFyLnNldF9h"
    "dXRvc2F2ZV9pbmRpY2F0b3IoRmFsc2UpCiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5f"
    "ZGlhZ190YWIubG9nKCJbQVVUT1NBVkVdIFNlc3Npb24gc2F2ZWQuIiwgIklORk8iKQogICAgICAg"
    "IGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgc2VsZi5fZGlhZ190YWIubG9nKGYi"
    "W0FVVE9TQVZFXSBFcnJvcjoge2V9IiwgIkVSUk9SIikKCiAgICBkZWYgX2ZpcmVfaWRsZV90cmFu"
    "c21pc3Npb24oc2VsZikgLT4gTm9uZToKICAgICAgICBpZiBub3Qgc2VsZi5fbW9kZWxfbG9hZGVk"
    "IG9yIHNlbGYuX3N0YXR1cyA9PSAiR0VORVJBVElORyI6CiAgICAgICAgICAgIHJldHVybgogICAg"
    "ICAgIGlmIHNlbGYuX3RvcnBvcl9zaW5jZSBpcyBub3QgTm9uZToKICAgICAgICAgICAgIyBJbiB0"
    "b3Jwb3Ig4oCUIGNvdW50IHRoZSBwZW5kaW5nIHRob3VnaHQgYnV0IGRvbid0IGdlbmVyYXRlCiAg"
    "ICAgICAgICAgIHNlbGYuX3BlbmRpbmdfdHJhbnNtaXNzaW9ucyArPSAxCiAgICAgICAgICAgIHNl"
    "bGYuX2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgICAgIGYiW0lETEVdIEluIHRvcnBvciDigJQg"
    "cGVuZGluZyB0cmFuc21pc3Npb24gIgogICAgICAgICAgICAgICAgZiIje3NlbGYuX3BlbmRpbmdf"
    "dHJhbnNtaXNzaW9uc30iLCAiSU5GTyIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4K"
    "CiAgICAgICAgbW9kZSA9IHJhbmRvbS5jaG9pY2UoWyJERUVQRU5JTkciLCJCUkFOQ0hJTkciLCJT"
    "WU5USEVTSVMiXSkKICAgICAgICB2YW1waXJlX2N0eCA9IGJ1aWxkX3ZhbXBpcmVfY29udGV4dCgp"
    "CiAgICAgICAgaGlzdG9yeSA9IHNlbGYuX3Nlc3Npb25zLmdldF9oaXN0b3J5KCkKCiAgICAgICAg"
    "c2VsZi5faWRsZV93b3JrZXIgPSBJZGxlV29ya2VyKAogICAgICAgICAgICBzZWxmLl9hZGFwdG9y"
    "LAogICAgICAgICAgICBTWVNURU1fUFJPTVBUX0JBU0UsCiAgICAgICAgICAgIGhpc3RvcnksCiAg"
    "ICAgICAgICAgIG1vZGU9bW9kZSwKICAgICAgICAgICAgdmFtcGlyZV9jb250ZXh0PXZhbXBpcmVf"
    "Y3R4LAogICAgICAgICkKICAgICAgICBkZWYgX29uX2lkbGVfcmVhZHkodDogc3RyKSAtPiBOb25l"
    "OgogICAgICAgICAgICAjIEZsaXAgdG8gU2VsZiB0YWIgYW5kIGFwcGVuZCB0aGVyZQogICAgICAg"
    "ICAgICBzZWxmLl9tYWluX3RhYnMuc2V0Q3VycmVudEluZGV4KDEpCiAgICAgICAgICAgIHRzID0g"
    "ZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNIikKICAgICAgICAgICAgc2VsZi5fc2VsZl9k"
    "aXNwbGF5LmFwcGVuZCgKICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RF"
    "WFRfRElNfTsgZm9udC1zaXplOjEwcHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7dHN9XSBbe21v"
    "ZGV9XTwvc3Bhbj48YnI+JwogICAgICAgICAgICAgICAgZic8c3BhbiBzdHlsZT0iY29sb3I6e0Nf"
    "R09MRH07Ij57dH08L3NwYW4+PGJyPicKICAgICAgICAgICAgKQogICAgICAgICAgICBzZWxmLl9z"
    "ZWxmX3RhYi5hcHBlbmQoIk5BUlJBVElWRSIsIHQpCgogICAgICAgIHNlbGYuX2lkbGVfd29ya2Vy"
    "LnRyYW5zbWlzc2lvbl9yZWFkeS5jb25uZWN0KF9vbl9pZGxlX3JlYWR5KQogICAgICAgIHNlbGYu"
    "X2lkbGVfd29ya2VyLmVycm9yX29jY3VycmVkLmNvbm5lY3QoCiAgICAgICAgICAgIGxhbWJkYSBl"
    "OiBzZWxmLl9kaWFnX3RhYi5sb2coZiJbSURMRSBFUlJPUl0ge2V9IiwgIkVSUk9SIikKICAgICAg"
    "ICApCiAgICAgICAgc2VsZi5faWRsZV93b3JrZXIuc3RhcnQoKQoKICAgICMg4pSA4pSAIEpPVVJO"
    "QUwgU0VTU0lPTiBMT0FESU5HIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVm"
    "IF9sb2FkX2pvdXJuYWxfc2Vzc2lvbihzZWxmLCBkYXRlX3N0cjogc3RyKSAtPiBOb25lOgogICAg"
    "ICAgIGN0eCA9IHNlbGYuX3Nlc3Npb25zLmxvYWRfc2Vzc2lvbl9hc19jb250ZXh0KGRhdGVfc3Ry"
    "KQogICAgICAgIGlmIG5vdCBjdHg6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZygKICAg"
    "ICAgICAgICAgICAgIGYiW0pPVVJOQUxdIE5vIHNlc3Npb24gZm91bmQgZm9yIHtkYXRlX3N0cn0i"
    "LCAiV0FSTiIKICAgICAgICAgICAgKQogICAgICAgICAgICByZXR1cm4KICAgICAgICBzZWxmLl9q"
    "b3VybmFsX3NpZGViYXIuc2V0X2pvdXJuYWxfbG9hZGVkKGRhdGVfc3RyKQogICAgICAgIHNlbGYu"
    "X2RpYWdfdGFiLmxvZygKICAgICAgICAgICAgZiJbSk9VUk5BTF0gTG9hZGVkIHNlc3Npb24gZnJv"
    "bSB7ZGF0ZV9zdHJ9IGFzIGNvbnRleHQuICIKICAgICAgICAgICAgZiJ7REVDS19OQU1FfSBpcyBu"
    "b3cgYXdhcmUgb2YgdGhhdCBjb252ZXJzYXRpb24uIiwgIk9LIgogICAgICAgICkKICAgICAgICBz"
    "ZWxmLl9hcHBlbmRfY2hhdCgiU1lTVEVNIiwKICAgICAgICAgICAgZiJBIG1lbW9yeSBzdGlycy4u"
    "LiB0aGUgam91cm5hbCBvZiB7ZGF0ZV9zdHJ9IG9wZW5zIGJlZm9yZSBoZXIuIgogICAgICAgICkK"
    "ICAgICAgICAjIE5vdGlmeSBNb3JnYW5uYQogICAgICAgIGlmIHNlbGYuX21vZGVsX2xvYWRlZDoK"
    "ICAgICAgICAgICAgbm90ZSA9ICgKICAgICAgICAgICAgICAgIGYiW0pPVVJOQUwgTE9BREVEXSBU"
    "aGUgdXNlciBoYXMgb3BlbmVkIHRoZSBqb3VybmFsIGZyb20gIgogICAgICAgICAgICAgICAgZiJ7"
    "ZGF0ZV9zdHJ9LiBBY2tub3dsZWRnZSB0aGlzIGJyaWVmbHkg4oCUIHlvdSBub3cgaGF2ZSAiCiAg"
    "ICAgICAgICAgICAgICBmImF3YXJlbmVzcyBvZiB0aGF0IGNvbnZlcnNhdGlvbi4iCiAgICAgICAg"
    "ICAgICkKICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbnMuYWRkX21lc3NhZ2UoInN5c3RlbSIsIG5v"
    "dGUpCgogICAgZGVmIF9jbGVhcl9qb3VybmFsX3Nlc3Npb24oc2VsZikgLT4gTm9uZToKICAgICAg"
    "ICBzZWxmLl9zZXNzaW9ucy5jbGVhcl9sb2FkZWRfam91cm5hbCgpCiAgICAgICAgc2VsZi5fZGlh"
    "Z190YWIubG9nKCJbSk9VUk5BTF0gSm91cm5hbCBjb250ZXh0IGNsZWFyZWQuIiwgIklORk8iKQog"
    "ICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJTWVNURU0iLAogICAgICAgICAgICAiVGhlIGpvdXJu"
    "YWwgY2xvc2VzLiBPbmx5IHRoZSBwcmVzZW50IHJlbWFpbnMuIgogICAgICAgICkKCiAgICAjIOKU"
    "gOKUgCBTVEFUUyBVUERBVEUg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3VwZGF0ZV9zdGF0cyhzZWxmKSAtPiBO"
    "b25lOgogICAgICAgIGVsYXBzZWQgPSBpbnQodGltZS50aW1lKCkgLSBzZWxmLl9zZXNzaW9uX3N0"
    "YXJ0KQogICAgICAgIGgsIG0sIHMgPSBlbGFwc2VkIC8vIDM2MDAsIChlbGFwc2VkICUgMzYwMCkg"
    "Ly8gNjAsIGVsYXBzZWQgJSA2MAogICAgICAgIHNlc3Npb25fc3RyID0gZiJ7aDowMmR9OnttOjAy"
    "ZH06e3M6MDJkfSIKCiAgICAgICAgc2VsZi5faHdfcGFuZWwuc2V0X3N0YXR1c19sYWJlbHMoCiAg"
    "ICAgICAgICAgIHNlbGYuX3N0YXR1cywKICAgICAgICAgICAgQ0ZHWyJtb2RlbCJdLmdldCgidHlw"
    "ZSIsImxvY2FsIikudXBwZXIoKSwKICAgICAgICAgICAgc2Vzc2lvbl9zdHIsCiAgICAgICAgICAg"
    "IHN0cihzZWxmLl90b2tlbl9jb3VudCksCiAgICAgICAgKQogICAgICAgIHNlbGYuX2h3X3BhbmVs"
    "LnVwZGF0ZV9zdGF0cygpCgogICAgICAgICMgTUFOQSBzcGhlcmUgPSBWUkFNIGF2YWlsYWJpbGl0"
    "eQogICAgICAgIGlmIE5WTUxfT0sgYW5kIGdwdV9oYW5kbGU6CiAgICAgICAgICAgIHRyeToKICAg"
    "ICAgICAgICAgICAgIG1lbSA9IHB5bnZtbC5udm1sRGV2aWNlR2V0TWVtb3J5SW5mbyhncHVfaGFu"
    "ZGxlKQogICAgICAgICAgICAgICAgdnJhbV91c2VkID0gbWVtLnVzZWQgIC8gMTAyNCoqMwogICAg"
    "ICAgICAgICAgICAgdnJhbV90b3QgID0gbWVtLnRvdGFsIC8gMTAyNCoqMwogICAgICAgICAgICAg"
    "ICAgbWFuYV9maWxsID0gbWF4KDAuMCwgMS4wIC0gKHZyYW1fdXNlZCAvIHZyYW1fdG90KSkKICAg"
    "ICAgICAgICAgICAgIHNlbGYuX21hbmFfc3BoZXJlLnNldEZpbGwobWFuYV9maWxsLCBhdmFpbGFi"
    "bGU9VHJ1ZSkKICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgIHNl"
    "bGYuX21hbmFfc3BoZXJlLnNldEZpbGwoMC4wLCBhdmFpbGFibGU9RmFsc2UpCgogICAgICAgICMg"
    "SFVOR0VSID0gaW52ZXJzZSBvZiBibG9vZAogICAgICAgIGJsb29kX2ZpbGwgPSBtaW4oMS4wLCBz"
    "ZWxmLl90b2tlbl9jb3VudCAvIDQwOTYuMCkKICAgICAgICBodW5nZXIgICAgID0gMS4wIC0gYmxv"
    "b2RfZmlsbAogICAgICAgIHNlbGYuX2h1bmdlcl9nYXVnZS5zZXRWYWx1ZShodW5nZXIgKiAxMDAs"
    "IGYie2h1bmdlcioxMDA6LjBmfSUiKQoKICAgICAgICAjIFZJVEFMSVRZID0gUkFNIGZyZWUKICAg"
    "ICAgICBpZiBQU1VUSUxfT0s6CiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIG1lbSAg"
    "ICAgICA9IHBzdXRpbC52aXJ0dWFsX21lbW9yeSgpCiAgICAgICAgICAgICAgICB2aXRhbGl0eSAg"
    "PSAxLjAgLSAobWVtLnVzZWQgLyBtZW0udG90YWwpCiAgICAgICAgICAgICAgICBzZWxmLl92aXRh"
    "bGl0eV9nYXVnZS5zZXRWYWx1ZSgKICAgICAgICAgICAgICAgICAgICB2aXRhbGl0eSAqIDEwMCwg"
    "ZiJ7dml0YWxpdHkqMTAwOi4wZn0lIgogICAgICAgICAgICAgICAgKQogICAgICAgICAgICBleGNl"
    "cHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFVwZGF0ZSBqb3Vy"
    "bmFsIHNpZGViYXIgYXV0b3NhdmUgZmxhc2gKICAgICAgICBzZWxmLl9qb3VybmFsX3NpZGViYXIu"
    "cmVmcmVzaCgpCgogICAgIyDilIDilIAgQ0hBVCBESVNQTEFZIOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9hcHBl"
    "bmRfY2hhdChzZWxmLCBzcGVha2VyOiBzdHIsIHRleHQ6IHN0cikgLT4gTm9uZToKICAgICAgICBj"
    "b2xvcnMgPSB7CiAgICAgICAgICAgICJZT1UiOiAgICAgQ19HT0xELAogICAgICAgICAgICBERUNL"
    "X05BTUUudXBwZXIoKTpDX0dPTEQsCiAgICAgICAgICAgICJTWVNURU0iOiAgQ19QVVJQTEUsCiAg"
    "ICAgICAgICAgICJFUlJPUiI6ICAgQ19CTE9PRCwKICAgICAgICB9CiAgICAgICAgbGFiZWxfY29s"
    "b3JzID0gewogICAgICAgICAgICAiWU9VIjogICAgIENfR09MRF9ESU0sCiAgICAgICAgICAgIERF"
    "Q0tfTkFNRS51cHBlcigpOkNfQ1JJTVNPTiwKICAgICAgICAgICAgIlNZU1RFTSI6ICBDX1BVUlBM"
    "RSwKICAgICAgICAgICAgIkVSUk9SIjogICBDX0JMT09ELAogICAgICAgIH0KICAgICAgICBjb2xv"
    "ciAgICAgICA9IGNvbG9ycy5nZXQoc3BlYWtlciwgQ19HT0xEKQogICAgICAgIGxhYmVsX2NvbG9y"
    "ID0gbGFiZWxfY29sb3JzLmdldChzcGVha2VyLCBDX0dPTERfRElNKQogICAgICAgIHRpbWVzdGFt"
    "cCAgID0gZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVIOiVNOiVTIikKCiAgICAgICAgaWYgc3Bl"
    "YWtlciA9PSAiU1lTVEVNIjoKICAgICAgICAgICAgc2VsZi5fY2hhdF9kaXNwbGF5LmFwcGVuZCgK"
    "ICAgICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntDX1RFWFRfRElNfTsgZm9udC1z"
    "aXplOjEwcHg7Ij4nCiAgICAgICAgICAgICAgICBmJ1t7dGltZXN0YW1wfV0gPC9zcGFuPicKICAg"
    "ICAgICAgICAgICAgIGYnPHNwYW4gc3R5bGU9ImNvbG9yOntsYWJlbF9jb2xvcn07Ij7inKYge3Rl"
    "eHR9PC9zcGFuPicKICAgICAgICAgICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIHNlbGYu"
    "X2NoYXRfZGlzcGxheS5hcHBlbmQoCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xv"
    "cjp7Q19URVhUX0RJTX07IGZvbnQtc2l6ZToxMHB4OyI+JwogICAgICAgICAgICAgICAgZidbe3Rp"
    "bWVzdGFtcH1dIDwvc3Bhbj4nCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7"
    "bGFiZWxfY29sb3J9OyBmb250LXdlaWdodDpib2xkOyI+JwogICAgICAgICAgICAgICAgZid7c3Bl"
    "YWtlcn0g4p2nPC9zcGFuPiAnCiAgICAgICAgICAgICAgICBmJzxzcGFuIHN0eWxlPSJjb2xvcjp7"
    "Y29sb3J9OyI+e3RleHR9PC9zcGFuPicKICAgICAgICAgICAgKQoKICAgICAgICAjIEFkZCBibGFu"
    "ayBsaW5lIGFmdGVyIE1vcmdhbm5hJ3MgcmVzcG9uc2UgKG5vdCBkdXJpbmcgc3RyZWFtaW5nKQog"
    "ICAgICAgIGlmIHNwZWFrZXIgPT0gREVDS19OQU1FLnVwcGVyKCk6CiAgICAgICAgICAgIHNlbGYu"
    "X2NoYXRfZGlzcGxheS5hcHBlbmQoIiIpCgogICAgICAgIHNlbGYuX2NoYXRfZGlzcGxheS52ZXJ0"
    "aWNhbFNjcm9sbEJhcigpLnNldFZhbHVlKAogICAgICAgICAgICBzZWxmLl9jaGF0X2Rpc3BsYXku"
    "dmVydGljYWxTY3JvbGxCYXIoKS5tYXhpbXVtKCkKICAgICAgICApCgogICAgIyDilIDilIAgU1RB"
    "VFVTIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIF9zZXRfc3RhdHVzKHNlbGYsIHN0"
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
    "ZGRpbmc6IDNweCA4cHg7IgogICAgICAgICkKICAgICAgICBpZiBzZWxmLl9zY2hlZHVsZXIgYW5k"
    "IHNlbGYuX3NjaGVkdWxlci5ydW5uaW5nOgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAg"
    "ICBpZiBlbmFibGVkOgogICAgICAgICAgICAgICAgICAgIHNlbGYuX3NjaGVkdWxlci5yZXN1bWVf"
    "am9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKCJbSURMRV0gSWRsZSB0cmFuc21pc3Npb24gZW5hYmxlZC4iLCAiT0siKQogICAgICAg"
    "ICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgICAgICBzZWxmLl9zY2hlZHVsZXIucGF1c2Vf"
    "am9iKCJpZGxlX3RyYW5zbWlzc2lvbiIpCiAgICAgICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKCJbSURMRV0gSWRsZSB0cmFuc21pc3Npb24gcGF1c2VkLiIsICJJTkZPIikKICAgICAg"
    "ICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgc2VsZi5fZGlhZ190"
    "YWIubG9nKGYiW0lETEVdIFRvZ2dsZSBlcnJvcjoge2V9IiwgIkVSUk9SIikKCiAgICAjIOKUgOKU"
    "gCBXSU5ET1cgQ09OVFJPTFMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICBkZWYgX3RvZ2dsZV9mdWxsc2NyZWVuKHNlbGYpIC0+IE5vbmU6"
    "CiAgICAgICAgaWYgc2VsZi5pc0Z1bGxTY3JlZW4oKToKICAgICAgICAgICAgc2VsZi5zaG93Tm9y"
    "bWFsKCkKICAgICAgICAgICAgc2VsZi5fZnNfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAg"
    "ICAgICBmImJhY2tncm91bmQ6IHtDX0JHM307IGNvbG9yOiB7Q19DUklNU09OX0RJTX07ICIKICAg"
    "ICAgICAgICAgICAgIGYiYm9yZGVyOiAxcHggc29saWQge0NfQ1JJTVNPTl9ESU19OyBmb250LXNp"
    "emU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzog"
    "MDsiCiAgICAgICAgICAgICkKICAgICAgICBlbHNlOgogICAgICAgICAgICBzZWxmLnNob3dGdWxs"
    "U2NyZWVuKCkKICAgICAgICAgICAgc2VsZi5fZnNfYnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAg"
    "ICAgICAgICBmImJhY2tncm91bmQ6IHtDX0NSSU1TT05fRElNfTsgY29sb3I6IHtDX0NSSU1TT059"
    "OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OyBmb250"
    "LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAgZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGlu"
    "ZzogMDsiCiAgICAgICAgICAgICkKCiAgICBkZWYgX3RvZ2dsZV9ib3JkZXJsZXNzKHNlbGYpIC0+"
    "IE5vbmU6CiAgICAgICAgaXNfYmwgPSBib29sKHNlbGYud2luZG93RmxhZ3MoKSAmIFF0LldpbmRv"
    "d1R5cGUuRnJhbWVsZXNzV2luZG93SGludCkKICAgICAgICBpZiBpc19ibDoKICAgICAgICAgICAg"
    "c2VsZi5zZXRXaW5kb3dGbGFncygKICAgICAgICAgICAgICAgIHNlbGYud2luZG93RmxhZ3MoKSAm"
    "IH5RdC5XaW5kb3dUeXBlLkZyYW1lbGVzc1dpbmRvd0hpbnQKICAgICAgICAgICAgKQogICAgICAg"
    "ICAgICBzZWxmLl9ibF9idG4uc2V0U3R5bGVTaGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dy"
    "b3VuZDoge0NfQkczfTsgY29sb3I6IHtDX0NSSU1TT05fRElNfTsgIgogICAgICAgICAgICAgICAg"
    "ZiJib3JkZXI6IDFweCBzb2xpZCB7Q19DUklNU09OX0RJTX07IGZvbnQtc2l6ZTogOXB4OyAiCiAg"
    "ICAgICAgICAgICAgICBmImZvbnQtd2VpZ2h0OiBib2xkOyBwYWRkaW5nOiAwOyIKICAgICAgICAg"
    "ICAgKQogICAgICAgIGVsc2U6CiAgICAgICAgICAgIGlmIHNlbGYuaXNGdWxsU2NyZWVuKCk6CiAg"
    "ICAgICAgICAgICAgICBzZWxmLnNob3dOb3JtYWwoKQogICAgICAgICAgICBzZWxmLnNldFdpbmRv"
    "d0ZsYWdzKAogICAgICAgICAgICAgICAgc2VsZi53aW5kb3dGbGFncygpIHwgUXQuV2luZG93VHlw"
    "ZS5GcmFtZWxlc3NXaW5kb3dIaW50CiAgICAgICAgICAgICkKICAgICAgICAgICAgc2VsZi5fYmxf"
    "YnRuLnNldFN0eWxlU2hlZXQoCiAgICAgICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0NSSU1T"
    "T05fRElNfTsgY29sb3I6IHtDX0NSSU1TT059OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjog"
    "MXB4IHNvbGlkIHtDX0NSSU1TT059OyBmb250LXNpemU6IDlweDsgIgogICAgICAgICAgICAgICAg"
    "ZiJmb250LXdlaWdodDogYm9sZDsgcGFkZGluZzogMDsiCiAgICAgICAgICAgICkKICAgICAgICBz"
    "ZWxmLnNob3coKQoKICAgIGRlZiBfZXhwb3J0X2NoYXQoc2VsZikgLT4gTm9uZToKICAgICAgICAi"
    "IiJFeHBvcnQgY3VycmVudCBTw6lhbmNlIFJlY29yZCBjaGF0IHRvIGEgVFhUIGZpbGUuIiIiCiAg"
    "ICAgICAgdHJ5OgogICAgICAgICAgICB0ZXh0ID0gc2VsZi5fY2hhdF9kaXNwbGF5LnRvUGxhaW5U"
    "ZXh0KCkKICAgICAgICAgICAgaWYgbm90IHRleHQuc3RyaXAoKToKICAgICAgICAgICAgICAgIHJl"
    "dHVybgogICAgICAgICAgICBleHBvcnRfZGlyID0gY2ZnX3BhdGgoImV4cG9ydHMiKQogICAgICAg"
    "ICAgICBleHBvcnRfZGlyLm1rZGlyKHBhcmVudHM9VHJ1ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAg"
    "ICAgICAgdHMgPSBkYXRldGltZS5ub3coKS5zdHJmdGltZSgiJVklbSVkXyVIJU0lUyIpCiAgICAg"
    "ICAgICAgIG91dF9wYXRoID0gZXhwb3J0X2RpciAvIGYic2VhbmNlX3t0c30udHh0IgogICAgICAg"
    "ICAgICBvdXRfcGF0aC53cml0ZV90ZXh0KHRleHQsIGVuY29kaW5nPSJ1dGYtOCIpCgogICAgICAg"
    "ICAgICAjIEFsc28gY29weSB0byBjbGlwYm9hcmQKICAgICAgICAgICAgUUFwcGxpY2F0aW9uLmNs"
    "aXBib2FyZCgpLnNldFRleHQodGV4dCkKCiAgICAgICAgICAgIHNlbGYuX2FwcGVuZF9jaGF0KCJT"
    "WVNURU0iLAogICAgICAgICAgICAgICAgZiJTZXNzaW9uIGV4cG9ydGVkIHRvIHtvdXRfcGF0aC5u"
    "YW1lfSBhbmQgY29waWVkIHRvIGNsaXBib2FyZC4iKQogICAgICAgICAgICBzZWxmLl9kaWFnX3Rh"
    "Yi5sb2coZiJbRVhQT1JUXSB7b3V0X3BhdGh9IiwgIk9LIikKICAgICAgICBleGNlcHQgRXhjZXB0"
    "aW9uIGFzIGU6CiAgICAgICAgICAgIHNlbGYuX2RpYWdfdGFiLmxvZyhmIltFWFBPUlRdIEZhaWxl"
    "ZDoge2V9IiwgIkVSUk9SIikKCiAgICBkZWYga2V5UHJlc3NFdmVudChzZWxmLCBldmVudCkgLT4g"
    "Tm9uZToKICAgICAgICBrZXkgPSBldmVudC5rZXkoKQogICAgICAgIGlmIGtleSA9PSBRdC5LZXku"
    "S2V5X0YxMToKICAgICAgICAgICAgc2VsZi5fdG9nZ2xlX2Z1bGxzY3JlZW4oKQogICAgICAgIGVs"
    "aWYga2V5ID09IFF0LktleS5LZXlfRjEwOgogICAgICAgICAgICBzZWxmLl90b2dnbGVfYm9yZGVy"
    "bGVzcygpCiAgICAgICAgZWxpZiBrZXkgPT0gUXQuS2V5LktleV9Fc2NhcGUgYW5kIHNlbGYuaXNG"
    "dWxsU2NyZWVuKCk6CiAgICAgICAgICAgIHNlbGYuc2hvd05vcm1hbCgpCiAgICAgICAgICAgIHNl"
    "bGYuX2ZzX2J0bi5zZXRTdHlsZVNoZWV0KAogICAgICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7"
    "Q19CRzN9OyBjb2xvcjoge0NfQ1JJTVNPTl9ESU19OyAiCiAgICAgICAgICAgICAgICBmImJvcmRl"
    "cjogMXB4IHNvbGlkIHtDX0NSSU1TT05fRElNfTsgZm9udC1zaXplOiA5cHg7ICIKICAgICAgICAg"
    "ICAgICAgIGYiZm9udC13ZWlnaHQ6IGJvbGQ7IHBhZGRpbmc6IDA7IgogICAgICAgICAgICApCiAg"
    "ICAgICAgZWxzZToKICAgICAgICAgICAgc3VwZXIoKS5rZXlQcmVzc0V2ZW50KGV2ZW50KQoKICAg"
    "ICMg4pSA4pSAIENMT1NFIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgZGVmIGNsb3Nl"
    "RXZlbnQoc2VsZiwgZXZlbnQpIC0+IE5vbmU6CiAgICAgICAgIyBYIGJ1dHRvbiA9IGltbWVkaWF0"
    "ZSBzaHV0ZG93biwgbm8gZGlhbG9nCiAgICAgICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKCiAg"
    "ICBkZWYgX2luaXRpYXRlX3NodXRkb3duX2RpYWxvZyhzZWxmKSAtPiBOb25lOgogICAgICAgICIi"
    "IkdyYWNlZnVsIHNodXRkb3duIOKAlCBzaG93IGNvbmZpcm0gZGlhbG9nIGltbWVkaWF0ZWx5LCBv"
    "cHRpb25hbGx5IGdldCBsYXN0IHdvcmRzLiIiIgogICAgICAgICMgSWYgYWxyZWFkeSBpbiBhIHNo"
    "dXRkb3duIHNlcXVlbmNlLCBqdXN0IGZvcmNlIHF1aXQKICAgICAgICBpZiBnZXRhdHRyKHNlbGYs"
    "ICdfc2h1dGRvd25faW5fcHJvZ3Jlc3MnLCBGYWxzZSk6CiAgICAgICAgICAgIHNlbGYuX2RvX3No"
    "dXRkb3duKE5vbmUpCiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNlbGYuX3NodXRkb3duX2lu"
    "X3Byb2dyZXNzID0gVHJ1ZQoKICAgICAgICAjIFNob3cgY29uZmlybSBkaWFsb2cgRklSU1Qg4oCU"
    "IGRvbid0IHdhaXQgZm9yIEFJCiAgICAgICAgZGxnID0gUURpYWxvZyhzZWxmKQogICAgICAgIGRs"
    "Zy5zZXRXaW5kb3dUaXRsZSgiRGVhY3RpdmF0ZT8iKQogICAgICAgIGRsZy5zZXRTdHlsZVNoZWV0"
    "KAogICAgICAgICAgICBmImJhY2tncm91bmQ6IHtDX0JHMn07IGNvbG9yOiB7Q19URVhUfTsgIgog"
    "ICAgICAgICAgICBmImZvbnQtZmFtaWx5OiB7REVDS19GT05UfSwgc2VyaWY7IgogICAgICAgICkK"
    "ICAgICAgICBkbGcuc2V0Rml4ZWRTaXplKDM4MCwgMTQwKQogICAgICAgIGxheW91dCA9IFFWQm94"
    "TGF5b3V0KGRsZykKCiAgICAgICAgbGJsID0gUUxhYmVsKAogICAgICAgICAgICBmIkRlYWN0aXZh"
    "dGUge0RFQ0tfTkFNRX0/XG5cbiIKICAgICAgICAgICAgZiJ7REVDS19OQU1FfSBtYXkgc3BlYWsg"
    "dGhlaXIgbGFzdCB3b3JkcyBiZWZvcmUgZ29pbmcgc2lsZW50LiIKICAgICAgICApCiAgICAgICAg"
    "bGJsLnNldFdvcmRXcmFwKFRydWUpCiAgICAgICAgbGF5b3V0LmFkZFdpZGdldChsYmwpCgogICAg"
    "ICAgIGJ0bl9yb3cgPSBRSEJveExheW91dCgpCiAgICAgICAgYnRuX2xhc3QgID0gUVB1c2hCdXR0"
    "b24oIkxhc3QgV29yZHMgKyBTaHV0ZG93biIpCiAgICAgICAgYnRuX25vdyAgID0gUVB1c2hCdXR0"
    "b24oIlNodXRkb3duIE5vdyIpCiAgICAgICAgYnRuX2NhbmNlbCA9IFFQdXNoQnV0dG9uKCJDYW5j"
    "ZWwiKQoKICAgICAgICBmb3IgYiBpbiAoYnRuX2xhc3QsIGJ0bl9ub3csIGJ0bl9jYW5jZWwpOgog"
    "ICAgICAgICAgICBiLnNldE1pbmltdW1IZWlnaHQoMjgpCiAgICAgICAgICAgIGIuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgICAgIGYiYmFja2dyb3VuZDoge0NfQkczfTsgY29sb3I6IHtDX1RF"
    "WFR9OyAiCiAgICAgICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0JPUkRFUn07IHBh"
    "ZGRpbmc6IDRweCAxMnB4OyIKICAgICAgICAgICAgKQogICAgICAgIGJ0bl9ub3cuc2V0U3R5bGVT"
    "aGVldCgKICAgICAgICAgICAgZiJiYWNrZ3JvdW5kOiB7Q19CTE9PRH07IGNvbG9yOiB7Q19URVhU"
    "fTsgIgogICAgICAgICAgICBmImJvcmRlcjogMXB4IHNvbGlkIHtDX0NSSU1TT059OyBwYWRkaW5n"
    "OiA0cHggMTJweDsiCiAgICAgICAgKQogICAgICAgIGJ0bl9sYXN0LmNsaWNrZWQuY29ubmVjdChs"
    "YW1iZGE6IGRsZy5kb25lKDEpKQogICAgICAgIGJ0bl9ub3cuY2xpY2tlZC5jb25uZWN0KGxhbWJk"
    "YTogZGxnLmRvbmUoMikpCiAgICAgICAgYnRuX2NhbmNlbC5jbGlja2VkLmNvbm5lY3QobGFtYmRh"
    "OiBkbGcuZG9uZSgwKSkKICAgICAgICBidG5fcm93LmFkZFdpZGdldChidG5fY2FuY2VsKQogICAg"
    "ICAgIGJ0bl9yb3cuYWRkV2lkZ2V0KGJ0bl9ub3cpCiAgICAgICAgYnRuX3Jvdy5hZGRXaWRnZXQo"
    "YnRuX2xhc3QpCiAgICAgICAgbGF5b3V0LmFkZExheW91dChidG5fcm93KQoKICAgICAgICByZXN1"
    "bHQgPSBkbGcuZXhlYygpCgogICAgICAgIGlmIHJlc3VsdCA9PSAwOgogICAgICAgICAgICAjIENh"
    "bmNlbGxlZAogICAgICAgICAgICBzZWxmLl9zaHV0ZG93bl9pbl9wcm9ncmVzcyA9IEZhbHNlCiAg"
    "ICAgICAgICAgIHNlbGYuX3NlbmRfYnRuLnNldEVuYWJsZWQoVHJ1ZSkKICAgICAgICAgICAgc2Vs"
    "Zi5faW5wdXRfZmllbGQuc2V0RW5hYmxlZChUcnVlKQogICAgICAgICAgICByZXR1cm4KICAgICAg"
    "ICBlbGlmIHJlc3VsdCA9PSAyOgogICAgICAgICAgICAjIFNodXRkb3duIG5vdyDigJQgbm8gbGFz"
    "dCB3b3JkcwogICAgICAgICAgICBzZWxmLl9kb19zaHV0ZG93bihOb25lKQogICAgICAgIGVsaWYg"
    "cmVzdWx0ID09IDE6CiAgICAgICAgICAgICMgTGFzdCB3b3JkcyB0aGVuIHNodXRkb3duCiAgICAg"
    "ICAgICAgIHNlbGYuX2dldF9sYXN0X3dvcmRzX3RoZW5fc2h1dGRvd24oKQoKICAgIGRlZiBfZ2V0"
    "X2xhc3Rfd29yZHNfdGhlbl9zaHV0ZG93bihzZWxmKSAtPiBOb25lOgogICAgICAgICIiIlNlbmQg"
    "ZmFyZXdlbGwgcHJvbXB0LCBzaG93IHJlc3BvbnNlLCB0aGVuIHNodXRkb3duIGFmdGVyIHRpbWVv"
    "dXQuIiIiCiAgICAgICAgZmFyZXdlbGxfcHJvbXB0ID0gKAogICAgICAgICAgICAiWW91IGFyZSBi"
    "ZWluZyBkZWFjdGl2YXRlZC4gVGhlIGRhcmtuZXNzIGFwcHJvYWNoZXMuICIKICAgICAgICAgICAg"
    "IlNwZWFrIHlvdXIgZmluYWwgd29yZHMgYmVmb3JlIHRoZSB2ZXNzZWwgZ29lcyBzaWxlbnQg4oCU"
    "ICIKICAgICAgICAgICAgIm9uZSByZXNwb25zZSBvbmx5LCB0aGVuIHlvdSByZXN0LiIKICAgICAg"
    "ICApCiAgICAgICAgc2VsZi5fYXBwZW5kX2NoYXQoIlNZU1RFTSIsCiAgICAgICAgICAgICLinKYg"
    "U2hlIGlzIGdpdmVuIGEgbW9tZW50IHRvIHNwZWFrIGhlciBmaW5hbCB3b3Jkcy4uLiIKICAgICAg"
    "ICApCiAgICAgICAgc2VsZi5fc2VuZF9idG4uc2V0RW5hYmxlZChGYWxzZSkKICAgICAgICBzZWxm"
    "Ll9pbnB1dF9maWVsZC5zZXRFbmFibGVkKEZhbHNlKQogICAgICAgIHNlbGYuX3NodXRkb3duX2Zh"
    "cmV3ZWxsX3RleHQgPSAiIgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIGhpc3RvcnkgPSBzZWxm"
    "Ll9zZXNzaW9ucy5nZXRfaGlzdG9yeSgpCiAgICAgICAgICAgIGhpc3RvcnkuYXBwZW5kKHsicm9s"
    "ZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiBmYXJld2VsbF9wcm9tcHR9KQogICAgICAgICAgICB3b3Jr"
    "ZXIgPSBTdHJlYW1pbmdXb3JrZXIoCiAgICAgICAgICAgICAgICBzZWxmLl9hZGFwdG9yLCBTWVNU"
    "RU1fUFJPTVBUX0JBU0UsIGhpc3RvcnksIG1heF90b2tlbnM9MjU2CiAgICAgICAgICAgICkKICAg"
    "ICAgICAgICAgc2VsZi5fc2h1dGRvd25fd29ya2VyID0gd29ya2VyCiAgICAgICAgICAgIHNlbGYu"
    "X2ZpcnN0X3Rva2VuID0gVHJ1ZQoKICAgICAgICAgICAgZGVmIF9vbl9kb25lKHJlc3BvbnNlOiBz"
    "dHIpIC0+IE5vbmU6CiAgICAgICAgICAgICAgICBzZWxmLl9zaHV0ZG93bl9mYXJld2VsbF90ZXh0"
    "ID0gcmVzcG9uc2UKICAgICAgICAgICAgICAgIHNlbGYuX29uX3Jlc3BvbnNlX2RvbmUocmVzcG9u"
    "c2UpCiAgICAgICAgICAgICAgICAjIFNtYWxsIGRlbGF5IHRvIGxldCB0aGUgdGV4dCByZW5kZXIs"
    "IHRoZW4gc2h1dGRvd24KICAgICAgICAgICAgICAgIFFUaW1lci5zaW5nbGVTaG90KDIwMDAsIGxh"
    "bWJkYTogc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkpCgogICAgICAgICAgICBkZWYgX29uX2Vycm9y"
    "KGVycm9yOiBzdHIpIC0+IE5vbmU6CiAgICAgICAgICAgICAgICBzZWxmLl9kaWFnX3RhYi5sb2co"
    "ZiJbU0hVVERPV05dW1dBUk5dIExhc3Qgd29yZHMgZmFpbGVkOiB7ZXJyb3J9IiwgIldBUk4iKQog"
    "ICAgICAgICAgICAgICAgc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKCiAgICAgICAgICAgIHdvcmtl"
    "ci50b2tlbl9yZWFkeS5jb25uZWN0KHNlbGYuX29uX3Rva2VuKQogICAgICAgICAgICB3b3JrZXIu"
    "cmVzcG9uc2VfZG9uZS5jb25uZWN0KF9vbl9kb25lKQogICAgICAgICAgICB3b3JrZXIuZXJyb3Jf"
    "b2NjdXJyZWQuY29ubmVjdChfb25fZXJyb3IpCiAgICAgICAgICAgIHdvcmtlci5zdGF0dXNfY2hh"
    "bmdlZC5jb25uZWN0KHNlbGYuX3NldF9zdGF0dXMpCiAgICAgICAgICAgIHdvcmtlci5maW5pc2hl"
    "ZC5jb25uZWN0KHdvcmtlci5kZWxldGVMYXRlcikKICAgICAgICAgICAgd29ya2VyLnN0YXJ0KCkK"
    "CiAgICAgICAgICAgICMgU2FmZXR5IHRpbWVvdXQg4oCUIGlmIEFJIGRvZXNuJ3QgcmVzcG9uZCBp"
    "biAxNXMsIHNodXQgZG93biBhbnl3YXkKICAgICAgICAgICAgUVRpbWVyLnNpbmdsZVNob3QoMTUw"
    "MDAsIGxhbWJkYTogc2VsZi5fZG9fc2h1dGRvd24oTm9uZSkKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgaWYgZ2V0YXR0cihzZWxmLCAnX3NodXRkb3duX2luX3Byb2dyZXNzJywgRmFsc2Up"
    "IGVsc2UgTm9uZSkKCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBz"
    "ZWxmLl9kaWFnX3RhYi5sb2coCiAgICAgICAgICAgICAgICBmIltTSFVURE9XTl1bV0FSTl0gTGFz"
    "dCB3b3JkcyBza2lwcGVkIGR1ZSB0byBlcnJvcjoge2V9IiwKICAgICAgICAgICAgICAgICJXQVJO"
    "IgogICAgICAgICAgICApCiAgICAgICAgICAgICMgSWYgYW55dGhpbmcgZmFpbHMsIGp1c3Qgc2h1"
    "dCBkb3duCiAgICAgICAgICAgIHNlbGYuX2RvX3NodXRkb3duKE5vbmUpCgogICAgZGVmIF9kb19z"
    "aHV0ZG93bihzZWxmLCBldmVudCkgLT4gTm9uZToKICAgICAgICAiIiJQZXJmb3JtIGFjdHVhbCBz"
    "aHV0ZG93biBzZXF1ZW5jZS4iIiIKICAgICAgICAjIFNhdmUgc2Vzc2lvbgogICAgICAgIHRyeToK"
    "ICAgICAgICAgICAgc2VsZi5fc2Vzc2lvbnMuc2F2ZSgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlv"
    "bjoKICAgICAgICAgICAgcGFzcwoKICAgICAgICAjIFN0b3JlIGZhcmV3ZWxsICsgbGFzdCBjb250"
    "ZXh0IGZvciB3YWtlLXVwCiAgICAgICAgdHJ5OgogICAgICAgICAgICAjIEdldCBsYXN0IDMgbWVz"
    "c2FnZXMgZnJvbSBzZXNzaW9uIGhpc3RvcnkgZm9yIHdha2UtdXAgY29udGV4dAogICAgICAgICAg"
    "ICBoaXN0b3J5ID0gc2VsZi5fc2Vzc2lvbnMuZ2V0X2hpc3RvcnkoKQogICAgICAgICAgICBsYXN0"
    "X2NvbnRleHQgPSBoaXN0b3J5Wy0zOl0gaWYgbGVuKGhpc3RvcnkpID49IDMgZWxzZSBoaXN0b3J5"
    "CiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X3NodXRkb3duX2NvbnRleHQiXSA9IFsKICAg"
    "ICAgICAgICAgICAgIHsicm9sZSI6IG0uZ2V0KCJyb2xlIiwiIiksICJjb250ZW50IjogbS5nZXQo"
    "ImNvbnRlbnQiLCIiKVs6MzAwXX0KICAgICAgICAgICAgICAgIGZvciBtIGluIGxhc3RfY29udGV4"
    "dAogICAgICAgICAgICBdCiAgICAgICAgICAgICMgRXh0cmFjdCBNb3JnYW5uYSdzIG1vc3QgcmVj"
    "ZW50IG1lc3NhZ2UgYXMgZmFyZXdlbGwKICAgICAgICAgICAgIyBQcmVmZXIgdGhlIGNhcHR1cmVk"
    "IHNodXRkb3duIGRpYWxvZyByZXNwb25zZSBpZiBhdmFpbGFibGUKICAgICAgICAgICAgZmFyZXdl"
    "bGwgPSBnZXRhdHRyKHNlbGYsICdfc2h1dGRvd25fZmFyZXdlbGxfdGV4dCcsICIiKQogICAgICAg"
    "ICAgICBpZiBub3QgZmFyZXdlbGw6CiAgICAgICAgICAgICAgICBmb3IgbSBpbiByZXZlcnNlZCho"
    "aXN0b3J5KToKICAgICAgICAgICAgICAgICAgICBpZiBtLmdldCgicm9sZSIpID09ICJhc3Npc3Rh"
    "bnQiOgogICAgICAgICAgICAgICAgICAgICAgICBmYXJld2VsbCA9IG0uZ2V0KCJjb250ZW50Iiwg"
    "IiIpWzo0MDBdCiAgICAgICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgIHNlbGYu"
    "X3N0YXRlWyJsYXN0X2ZhcmV3ZWxsIl0gPSBmYXJld2VsbAogICAgICAgIGV4Y2VwdCBFeGNlcHRp"
    "b246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTYXZlIHN0YXRlCiAgICAgICAgdHJ5Ogog"
    "ICAgICAgICAgICBzZWxmLl9zdGF0ZVsibGFzdF9zaHV0ZG93biJdICAgICAgICAgICAgID0gbG9j"
    "YWxfbm93X2lzbygpCiAgICAgICAgICAgIHNlbGYuX3N0YXRlWyJsYXN0X2FjdGl2ZSJdICAgICAg"
    "ICAgICAgICAgPSBsb2NhbF9ub3dfaXNvKCkKICAgICAgICAgICAgc2VsZi5fc3RhdGVbInZhbXBp"
    "cmVfc3RhdGVfYXRfc2h1dGRvd24iXSAgPSBnZXRfdmFtcGlyZV9zdGF0ZSgpCiAgICAgICAgICAg"
    "IHNlbGYuX21lbW9yeS5zYXZlX3N0YXRlKHNlbGYuX3N0YXRlKQogICAgICAgIGV4Y2VwdCBFeGNl"
    "cHRpb246CiAgICAgICAgICAgIHBhc3MKCiAgICAgICAgIyBTdG9wIHNjaGVkdWxlcgogICAgICAg"
    "IGlmIGhhc2F0dHIoc2VsZiwgIl9zY2hlZHVsZXIiKSBhbmQgc2VsZi5fc2NoZWR1bGVyIGFuZCBz"
    "ZWxmLl9zY2hlZHVsZXIucnVubmluZzoKICAgICAgICAgICAgdHJ5OgogICAgICAgICAgICAgICAg"
    "c2VsZi5fc2NoZWR1bGVyLnNodXRkb3duKHdhaXQ9RmFsc2UpCiAgICAgICAgICAgIGV4Y2VwdCBF"
    "eGNlcHRpb246CiAgICAgICAgICAgICAgICBwYXNzCgogICAgICAgICMgUGxheSBzaHV0ZG93biBz"
    "b3VuZAogICAgICAgIHRyeToKICAgICAgICAgICAgc2VsZi5fc2h1dGRvd25fc291bmQgPSBTb3Vu"
    "ZFdvcmtlcigic2h1dGRvd24iKQogICAgICAgICAgICBzZWxmLl9zaHV0ZG93bl9zb3VuZC5maW5p"
    "c2hlZC5jb25uZWN0KHNlbGYuX3NodXRkb3duX3NvdW5kLmRlbGV0ZUxhdGVyKQogICAgICAgICAg"
    "ICBzZWxmLl9zaHV0ZG93bl9zb3VuZC5zdGFydCgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoK"
    "ICAgICAgICAgICAgcGFzcwoKICAgICAgICBRQXBwbGljYXRpb24ucXVpdCgpCgoKIyDilIDilIAg"
    "RU5UUlkgUE9JTlQg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBtYWluKCkgLT4gTm9uZToKICAgICIi"
    "IgogICAgQXBwbGljYXRpb24gZW50cnkgcG9pbnQuCgogICAgT3JkZXIgb2Ygb3BlcmF0aW9uczoK"
    "ICAgIDEuIFByZS1mbGlnaHQgZGVwZW5kZW5jeSBib290c3RyYXAgKGF1dG8taW5zdGFsbCBtaXNz"
    "aW5nIGRlcHMpCiAgICAyLiBDaGVjayBmb3IgZmlyc3QgcnVuIOKGkiBzaG93IEZpcnN0UnVuRGlh"
    "bG9nCiAgICAgICBPbiBmaXJzdCBydW46CiAgICAgICAgIGEuIENyZWF0ZSBEOi9BSS9Nb2RlbHMv"
    "W0RlY2tOYW1lXS8gKG9yIGNob3NlbiBiYXNlX2RpcikKICAgICAgICAgYi4gQ29weSBbZGVja25h"
    "bWVdX2RlY2sucHkgaW50byB0aGF0IGZvbGRlcgogICAgICAgICBjLiBXcml0ZSBjb25maWcuanNv"
    "biBpbnRvIHRoYXQgZm9sZGVyCiAgICAgICAgIGQuIEJvb3RzdHJhcCBhbGwgc3ViZGlyZWN0b3Jp"
    "ZXMgdW5kZXIgdGhhdCBmb2xkZXIKICAgICAgICAgZS4gQ3JlYXRlIGRlc2t0b3Agc2hvcnRjdXQg"
    "cG9pbnRpbmcgdG8gbmV3IGxvY2F0aW9uCiAgICAgICAgIGYuIFNob3cgY29tcGxldGlvbiBtZXNz"
    "YWdlIGFuZCBFWElUIOKAlCB1c2VyIHVzZXMgc2hvcnRjdXQgZnJvbSBub3cgb24KICAgIDMuIE5v"
    "cm1hbCBydW4g4oCUIGxhdW5jaCBRQXBwbGljYXRpb24gYW5kIEVjaG9EZWNrCiAgICAiIiIKICAg"
    "IGltcG9ydCBzaHV0aWwgYXMgX3NodXRpbAoKICAgICMg4pSA4pSAIFBoYXNlIDE6IERlcGVuZGVu"
    "Y3kgYm9vdHN0cmFwIChwcmUtUUFwcGxpY2F0aW9uKSDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIAKICAgIGJvb3RzdHJhcF9jaGVjaygpCgogICAgIyDilIDilIAgUGhh"
    "c2UgMjogUUFwcGxpY2F0aW9uIChuZWVkZWQgZm9yIGRpYWxvZ3MpIOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgX2Vhcmx5X2xv"
    "ZygiW01BSU5dIENyZWF0aW5nIFFBcHBsaWNhdGlvbiIpCiAgICBhcHAgPSBRQXBwbGljYXRpb24o"
    "c3lzLmFyZ3YpCiAgICBhcHAuc2V0QXBwbGljYXRpb25OYW1lKEFQUF9OQU1FKQoKICAgICMgSW5z"
    "dGFsbCBRdCBtZXNzYWdlIGhhbmRsZXIgTk9XIOKAlCBjYXRjaGVzIGFsbCBRVGhyZWFkL1F0IHdh"
    "cm5pbmdzCiAgICAjIHdpdGggZnVsbCBzdGFjayB0cmFjZXMgZnJvbSB0aGlzIHBvaW50IGZvcndh"
    "cmQKICAgIF9pbnN0YWxsX3F0X21lc3NhZ2VfaGFuZGxlcigpCiAgICBfZWFybHlfbG9nKCJbTUFJ"
    "Tl0gUUFwcGxpY2F0aW9uIGNyZWF0ZWQsIG1lc3NhZ2UgaGFuZGxlciBpbnN0YWxsZWQiKQoKICAg"
    "ICMg4pSA4pSAIFBoYXNlIDM6IEZpcnN0IHJ1biBjaGVjayDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKICAgIGlzX2ZpcnN0X3J1biA9"
    "IENGRy5nZXQoImZpcnN0X3J1biIsIFRydWUpCgogICAgaWYgaXNfZmlyc3RfcnVuOgogICAgICAg"
    "IGRsZyA9IEZpcnN0UnVuRGlhbG9nKCkKICAgICAgICBpZiBkbGcuZXhlYygpICE9IFFEaWFsb2cu"
    "RGlhbG9nQ29kZS5BY2NlcHRlZDoKICAgICAgICAgICAgc3lzLmV4aXQoMCkKCiAgICAgICAgIyDi"
    "lIDilIAgQnVpbGQgY29uZmlnIGZyb20gZGlhbG9nIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgICAgIG5ld19jZmcgPSBkbGcuYnVpbGRfY29uZmln"
    "KCkKCiAgICAgICAgIyDilIDilIAgRGV0ZXJtaW5lIE1vcmdhbm5hJ3MgaG9tZSBkaXJlY3Rvcnkg"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSACiAgICAgICAgIyBBbHdheXMgY3JlYXRlcyBEOi9BSS9Nb2RlbHMvTW9y"
    "Z2FubmEvIChvciBzaWJsaW5nIG9mIHNjcmlwdCkKICAgICAgICBzZWVkX2RpciAgID0gU0NSSVBU"
    "X0RJUiAgICAgICAgICAjIHdoZXJlIHRoZSBzZWVkIC5weSBsaXZlcwogICAgICAgIG1vcmdhbm5h"
    "X2hvbWUgPSBzZWVkX2RpciAvIERFQ0tfTkFNRQogICAgICAgIG1vcmdhbm5hX2hvbWUubWtkaXIo"
    "cGFyZW50cz1UcnVlLCBleGlzdF9vaz1UcnVlKQoKICAgICAgICAjIOKUgOKUgCBVcGRhdGUgYWxs"
    "IHBhdGhzIGluIGNvbmZpZyB0byBwb2ludCBpbnNpZGUgbW9yZ2FubmFfaG9tZSDilIDilIAKICAg"
    "ICAgICBuZXdfY2ZnWyJiYXNlX2RpciJdID0gc3RyKG1vcmdhbm5hX2hvbWUpCiAgICAgICAgbmV3"
    "X2NmZ1sicGF0aHMiXSA9IHsKICAgICAgICAgICAgImZhY2VzIjogICAgc3RyKG1vcmdhbm5hX2hv"
    "bWUgLyAiRmFjZXMiKSwKICAgICAgICAgICAgInNvdW5kcyI6ICAgc3RyKG1vcmdhbm5hX2hvbWUg"
    "LyAic291bmRzIiksCiAgICAgICAgICAgICJtZW1vcmllcyI6IHN0cihtb3JnYW5uYV9ob21lIC8g"
    "Im1lbW9yaWVzIiksCiAgICAgICAgICAgICJzZXNzaW9ucyI6IHN0cihtb3JnYW5uYV9ob21lIC8g"
    "InNlc3Npb25zIiksCiAgICAgICAgICAgICJzbCI6ICAgICAgIHN0cihtb3JnYW5uYV9ob21lIC8g"
    "InNsIiksCiAgICAgICAgICAgICJleHBvcnRzIjogIHN0cihtb3JnYW5uYV9ob21lIC8gImV4cG9y"
    "dHMiKSwKICAgICAgICAgICAgImxvZ3MiOiAgICAgc3RyKG1vcmdhbm5hX2hvbWUgLyAibG9ncyIp"
    "LAogICAgICAgICAgICAiYmFja3VwcyI6ICBzdHIobW9yZ2FubmFfaG9tZSAvICJiYWNrdXBzIiks"
    "CiAgICAgICAgICAgICJwZXJzb25hcyI6IHN0cihtb3JnYW5uYV9ob21lIC8gInBlcnNvbmFzIiks"
    "CiAgICAgICAgICAgICJnb29nbGUiOiAgIHN0cihtb3JnYW5uYV9ob21lIC8gImdvb2dsZSIpLAog"
    "ICAgICAgIH0KICAgICAgICBuZXdfY2ZnWyJnb29nbGUiXSA9IHsKICAgICAgICAgICAgImNyZWRl"
    "bnRpYWxzIjogc3RyKG1vcmdhbm5hX2hvbWUgLyAiZ29vZ2xlIiAvICJnb29nbGVfY3JlZGVudGlh"
    "bHMuanNvbiIpLAogICAgICAgICAgICAidG9rZW4iOiAgICAgICBzdHIobW9yZ2FubmFfaG9tZSAv"
    "ICJnb29nbGUiIC8gInRva2VuLmpzb24iKSwKICAgICAgICAgICAgInRpbWV6b25lIjogICAgIkFt"
    "ZXJpY2EvQ2hpY2FnbyIsCiAgICAgICAgICAgICJzY29wZXMiOiBbCiAgICAgICAgICAgICAgICAi"
    "aHR0cHM6Ly93d3cuZ29vZ2xlYXBpcy5jb20vYXV0aC9jYWxlbmRhci5ldmVudHMiLAogICAgICAg"
    "ICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZHJpdmUiLAogICAgICAg"
    "ICAgICAgICAgImh0dHBzOi8vd3d3Lmdvb2dsZWFwaXMuY29tL2F1dGgvZG9jdW1lbnRzIiwKICAg"
    "ICAgICAgICAgXSwKICAgICAgICB9CiAgICAgICAgbmV3X2NmZ1siZmlyc3RfcnVuIl0gPSBGYWxz"
    "ZQoKICAgICAgICAjIOKUgOKUgCBDb3B5IGRlY2sgZmlsZSBpbnRvIG1vcmdhbm5hX2hvbWUg4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc3JjX2RlY2sgPSBQYXRoKF9fZmlsZV9fKS5yZXNv"
    "bHZlKCkKICAgICAgICBkc3RfZGVjayA9IG1vcmdhbm5hX2hvbWUgLyBmIntERUNLX05BTUUubG93"
    "ZXIoKX1fZGVjay5weSIKICAgICAgICBpZiBzcmNfZGVjayAhPSBkc3RfZGVjazoKICAgICAgICAg"
    "ICAgdHJ5OgogICAgICAgICAgICAgICAgX3NodXRpbC5jb3B5MihzdHIoc3JjX2RlY2spLCBzdHIo"
    "ZHN0X2RlY2spKQogICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAg"
    "ICAgICBRTWVzc2FnZUJveC53YXJuaW5nKAogICAgICAgICAgICAgICAgICAgIE5vbmUsICJDb3B5"
    "IFdhcm5pbmciLAogICAgICAgICAgICAgICAgICAgIGYiQ291bGQgbm90IGNvcHkgZGVjayBmaWxl"
    "IHRvIHtERUNLX05BTUV9IGZvbGRlcjpcbntlfVxuXG4iCiAgICAgICAgICAgICAgICAgICAgZiJZ"
    "b3UgbWF5IG5lZWQgdG8gY29weSBpdCBtYW51YWxseS4iCiAgICAgICAgICAgICAgICApCgogICAg"
    "ICAgICMg4pSA4pSAIFdyaXRlIGNvbmZpZy5qc29uIGludG8gbW9yZ2FubmFfaG9tZSDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIAKICAgICAgICBjZmdfZHN0ID0gbW9yZ2FubmFfaG9tZSAvICJjb25maWcuanNvbiIKICAg"
    "ICAgICBjZmdfZHN0LnBhcmVudC5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0X29rPVRydWUpCiAg"
    "ICAgICAgd2l0aCBjZmdfZHN0Lm9wZW4oInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAg"
    "ICAgICAgICBqc29uLmR1bXAobmV3X2NmZywgZiwgaW5kZW50PTIpCgogICAgICAgICMg4pSA4pSA"
    "IEJvb3RzdHJhcCBhbGwgc3ViZGlyZWN0b3JpZXMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA"
    "4pSA4pSA4pSACiAgICAgICAgIyBUZW1wb3JhcmlseSB1cGRhdGUgZ2xvYmFsIENGRyBzbyBib290"
    "c3RyYXAgZnVuY3Rpb25zIHVzZSBuZXcgcGF0aHMKICAgICAgICBDRkcudXBkYXRlKG5ld19jZmcp"
    "CiAgICAgICAgYm9vdHN0cmFwX2RpcmVjdG9yaWVzKCkKICAgICAgICBib290c3RyYXBfc291bmRz"
    "KCkKICAgICAgICB3cml0ZV9yZXF1aXJlbWVudHNfdHh0KCkKCiAgICAgICAgIyDilIDilIAgVW5w"
    "YWNrIGZhY2UgWklQIGlmIHByb3ZpZGVkIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgAogICAgICAgIGZhY2VfemlwID0gZGxnLmZhY2VfemlwX3BhdGgKICAgICAgICBpZiBm"
    "YWNlX3ppcCBhbmQgUGF0aChmYWNlX3ppcCkuZXhpc3RzKCk6CiAgICAgICAgICAgIGltcG9ydCB6"
    "aXBmaWxlIGFzIF96aXBmaWxlCiAgICAgICAgICAgIGZhY2VzX2RpciA9IG1vcmdhbm5hX2hvbWUg"
    "LyAiRmFjZXMiCiAgICAgICAgICAgIGZhY2VzX2Rpci5ta2RpcihwYXJlbnRzPVRydWUsIGV4aXN0"
    "X29rPVRydWUpCiAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgIHdpdGggX3ppcGZpbGUu"
    "WmlwRmlsZShmYWNlX3ppcCwgInIiKSBhcyB6ZjoKICAgICAgICAgICAgICAgICAgICBleHRyYWN0"
    "ZWQgPSAwCiAgICAgICAgICAgICAgICAgICAgZm9yIG1lbWJlciBpbiB6Zi5uYW1lbGlzdCgpOgog"
    "ICAgICAgICAgICAgICAgICAgICAgICBpZiBtZW1iZXIubG93ZXIoKS5lbmRzd2l0aCgiLnBuZyIp"
    "OgogICAgICAgICAgICAgICAgICAgICAgICAgICAgZmlsZW5hbWUgPSBQYXRoKG1lbWJlcikubmFt"
    "ZQogICAgICAgICAgICAgICAgICAgICAgICAgICAgdGFyZ2V0ID0gZmFjZXNfZGlyIC8gZmlsZW5h"
    "bWUKICAgICAgICAgICAgICAgICAgICAgICAgICAgIHdpdGggemYub3BlbihtZW1iZXIpIGFzIHNy"
    "YywgdGFyZ2V0Lm9wZW4oIndiIikgYXMgZHN0OgogICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgIGRzdC53cml0ZShzcmMucmVhZCgpKQogICAgICAgICAgICAgICAgICAgICAgICAgICAgZXh0"
    "cmFjdGVkICs9IDEKICAgICAgICAgICAgICAgIF9lYXJseV9sb2coZiJbRkFDRVNdIEV4dHJhY3Rl"
    "ZCB7ZXh0cmFjdGVkfSBmYWNlIGltYWdlcyB0byB7ZmFjZXNfZGlyfSIpCiAgICAgICAgICAgIGV4"
    "Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgICAgIF9lYXJseV9sb2coZiJbRkFDRVNd"
    "IFpJUCBleHRyYWN0aW9uIGZhaWxlZDoge2V9IikKICAgICAgICAgICAgICAgIFFNZXNzYWdlQm94"
    "Lndhcm5pbmcoCiAgICAgICAgICAgICAgICAgICAgTm9uZSwgIkZhY2UgUGFjayBXYXJuaW5nIiwK"
    "ICAgICAgICAgICAgICAgICAgICBmIkNvdWxkIG5vdCBleHRyYWN0IGZhY2UgcGFjazpcbntlfVxu"
    "XG4iCiAgICAgICAgICAgICAgICAgICAgZiJZb3UgY2FuIGFkZCBmYWNlcyBtYW51YWxseSB0bzpc"
    "bntmYWNlc19kaXJ9IgogICAgICAgICAgICAgICAgKQoKICAgICAgICAjIOKUgOKUgCBDcmVhdGUg"
    "ZGVza3RvcCBzaG9ydGN1dCBwb2ludGluZyB0byBuZXcgZGVjayBsb2NhdGlvbiDilIDilIDilIDi"
    "lIDilIDilIAKICAgICAgICBzaG9ydGN1dF9jcmVhdGVkID0gRmFsc2UKICAgICAgICBpZiBkbGcu"
    "Y3JlYXRlX3Nob3J0Y3V0OgogICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICBpZiBXSU4z"
    "Ml9PSzoKICAgICAgICAgICAgICAgICAgICBpbXBvcnQgd2luMzJjb20uY2xpZW50IGFzIF93aW4z"
    "MgogICAgICAgICAgICAgICAgICAgIGRlc2t0b3AgICAgID0gUGF0aC5ob21lKCkgLyAiRGVza3Rv"
    "cCIKICAgICAgICAgICAgICAgICAgICBzY19wYXRoICAgICA9IGRlc2t0b3AgLyBmIntERUNLX05B"
    "TUV9LmxuayIKICAgICAgICAgICAgICAgICAgICBweXRob253ICAgICA9IFBhdGgoc3lzLmV4ZWN1"
    "dGFibGUpCiAgICAgICAgICAgICAgICAgICAgaWYgcHl0aG9udy5uYW1lLmxvd2VyKCkgPT0gInB5"
    "dGhvbi5leGUiOgogICAgICAgICAgICAgICAgICAgICAgICBweXRob253ID0gcHl0aG9udy5wYXJl"
    "bnQgLyAicHl0aG9udy5leGUiCiAgICAgICAgICAgICAgICAgICAgaWYgbm90IHB5dGhvbncuZXhp"
    "c3RzKCk6CiAgICAgICAgICAgICAgICAgICAgICAgIHB5dGhvbncgPSBQYXRoKHN5cy5leGVjdXRh"
    "YmxlKQogICAgICAgICAgICAgICAgICAgIHNoZWxsID0gX3dpbjMyLkRpc3BhdGNoKCJXU2NyaXB0"
    "LlNoZWxsIikKICAgICAgICAgICAgICAgICAgICBzYyAgICA9IHNoZWxsLkNyZWF0ZVNob3J0Q3V0"
    "KHN0cihzY19wYXRoKSkKICAgICAgICAgICAgICAgICAgICBzYy5UYXJnZXRQYXRoICAgICAgPSBz"
    "dHIocHl0aG9udykKICAgICAgICAgICAgICAgICAgICBzYy5Bcmd1bWVudHMgICAgICAgPSBmJyJ7"
    "ZHN0X2RlY2t9IicKICAgICAgICAgICAgICAgICAgICBzYy5Xb3JraW5nRGlyZWN0b3J5PSBzdHIo"
    "bW9yZ2FubmFfaG9tZSkKICAgICAgICAgICAgICAgICAgICBzYy5EZXNjcmlwdGlvbiAgICAgPSBm"
    "IntERUNLX05BTUV9IOKAlCBFY2hvIERlY2siCiAgICAgICAgICAgICAgICAgICAgc2Muc2F2ZSgp"
    "CiAgICAgICAgICAgICAgICAgICAgc2hvcnRjdXRfY3JlYXRlZCA9IFRydWUKICAgICAgICAgICAg"
    "ZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICAgICAgcHJpbnQoZiJbU0hPUlRDVVRd"
    "IENvdWxkIG5vdCBjcmVhdGUgc2hvcnRjdXQ6IHtlfSIpCgogICAgICAgICMg4pSA4pSAIENvbXBs"
    "ZXRpb24gbWVzc2FnZSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIAKICAgICAgICBzaG9ydGN1dF9ub3RlID0gKAogICAgICAg"
    "ICAgICAiQSBkZXNrdG9wIHNob3J0Y3V0IGhhcyBiZWVuIGNyZWF0ZWQuXG4iCiAgICAgICAgICAg"
    "IGYiVXNlIGl0IHRvIHN1bW1vbiB7REVDS19OQU1FfSBmcm9tIG5vdyBvbi4iCiAgICAgICAgICAg"
    "IGlmIHNob3J0Y3V0X2NyZWF0ZWQgZWxzZQogICAgICAgICAgICAiTm8gc2hvcnRjdXQgd2FzIGNy"
    "ZWF0ZWQuXG4iCiAgICAgICAgICAgIGYiUnVuIHtERUNLX05BTUV9IGJ5IGRvdWJsZS1jbGlja2lu"
    "Zzpcbntkc3RfZGVja30iCiAgICAgICAgKQoKICAgICAgICBRTWVzc2FnZUJveC5pbmZvcm1hdGlv"
    "bigKICAgICAgICAgICAgTm9uZSwKICAgICAgICAgICAgZiLinKYge0RFQ0tfTkFNRX0ncyBTYW5j"
    "dHVtIFByZXBhcmVkIiwKICAgICAgICAgICAgZiJ7REVDS19OQU1FfSdzIHNhbmN0dW0gaGFzIGJl"
    "ZW4gcHJlcGFyZWQgYXQ6XG5cbiIKICAgICAgICAgICAgZiJ7bW9yZ2FubmFfaG9tZX1cblxuIgog"
    "ICAgICAgICAgICBmIntzaG9ydGN1dF9ub3RlfVxuXG4iCiAgICAgICAgICAgIGYiVGhpcyBzZXR1"
    "cCB3aW5kb3cgd2lsbCBub3cgY2xvc2UuXG4iCiAgICAgICAgICAgIGYiVXNlIHRoZSBzaG9ydGN1"
    "dCBvciB0aGUgZGVjayBmaWxlIHRvIGxhdW5jaCB7REVDS19OQU1FfS4iCiAgICAgICAgKQoKICAg"
    "ICAgICAjIOKUgOKUgCBFeGl0IHNlZWQg4oCUIHVzZXIgbGF1bmNoZXMgZnJvbSBzaG9ydGN1dC9u"
    "ZXcgbG9jYXRpb24g4pSA4pSA4pSA4pSA4pSA4pSA4pSACiAgICAgICAgc3lzLmV4aXQoMCkKCiAg"
    "ICAjIOKUgOKUgCBQaGFzZSA0OiBOb3JtYWwgbGF1bmNoIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKU"
    "gOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAogICAgIyBPbmx5IHJl"
    "YWNoZXMgaGVyZSBvbiBzdWJzZXF1ZW50IHJ1bnMgZnJvbSBtb3JnYW5uYV9ob21lCiAgICBib290"
    "c3RyYXBfc291bmRzKCkKCiAgICBfZWFybHlfbG9nKGYiW01BSU5dIENyZWF0aW5nIHtERUNLX05B"
    "TUV9IGRlY2sgd2luZG93IikKICAgIHdpbmRvdyA9IEVjaG9EZWNrKCkKICAgIF9lYXJseV9sb2co"
    "ZiJbTUFJTl0ge0RFQ0tfTkFNRX0gZGVjayBjcmVhdGVkIOKAlCBjYWxsaW5nIHNob3coKSIpCiAg"
    "ICB3aW5kb3cuc2hvdygpCiAgICBfZWFybHlfbG9nKCJbTUFJTl0gd2luZG93LnNob3coKSBjYWxs"
    "ZWQg4oCUIGV2ZW50IGxvb3Agc3RhcnRpbmciKQoKICAgICMgRGVmZXIgc2NoZWR1bGVyIGFuZCBz"
    "dGFydHVwIHNlcXVlbmNlIHVudGlsIGV2ZW50IGxvb3AgaXMgcnVubmluZy4KICAgICMgTm90aGlu"
    "ZyB0aGF0IHN0YXJ0cyB0aHJlYWRzIG9yIGVtaXRzIHNpZ25hbHMgc2hvdWxkIHJ1biBiZWZvcmUg"
    "dGhpcy4KICAgIFFUaW1lci5zaW5nbGVTaG90KDIwMCwgbGFtYmRhOiAoX2Vhcmx5X2xvZygiW1RJ"
    "TUVSXSBfc2V0dXBfc2NoZWR1bGVyIGZpcmluZyIpLCB3aW5kb3cuX3NldHVwX3NjaGVkdWxlcigp"
    "KSkKICAgIFFUaW1lci5zaW5nbGVTaG90KDQwMCwgbGFtYmRhOiAoX2Vhcmx5X2xvZygiW1RJTUVS"
    "XSBzdGFydF9zY2hlZHVsZXIgZmlyaW5nIiksIHdpbmRvdy5zdGFydF9zY2hlZHVsZXIoKSkpCiAg"
    "ICBRVGltZXIuc2luZ2xlU2hvdCg2MDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gX3N0"
    "YXJ0dXBfc2VxdWVuY2UgZmlyaW5nIiksIHdpbmRvdy5fc3RhcnR1cF9zZXF1ZW5jZSgpKSkKICAg"
    "IFFUaW1lci5zaW5nbGVTaG90KDEwMDAsIGxhbWJkYTogKF9lYXJseV9sb2coIltUSU1FUl0gX3N0"
    "YXJ0dXBfZ29vZ2xlX2F1dGggZmlyaW5nIiksIHdpbmRvdy5fc3RhcnR1cF9nb29nbGVfYXV0aCgp"
    "KSkKCiAgICAjIFBsYXkgc3RhcnR1cCBzb3VuZCDigJQga2VlcCByZWZlcmVuY2UgdG8gcHJldmVu"
    "dCBHQyB3aGlsZSB0aHJlYWQgcnVucwogICAgZGVmIF9wbGF5X3N0YXJ0dXAoKToKICAgICAgICB3"
    "aW5kb3cuX3N0YXJ0dXBfc291bmQgPSBTb3VuZFdvcmtlcigic3RhcnR1cCIpCiAgICAgICAgd2lu"
    "ZG93Ll9zdGFydHVwX3NvdW5kLmZpbmlzaGVkLmNvbm5lY3Qod2luZG93Ll9zdGFydHVwX3NvdW5k"
    "LmRlbGV0ZUxhdGVyKQogICAgICAgIHdpbmRvdy5fc3RhcnR1cF9zb3VuZC5zdGFydCgpCiAgICBR"
    "VGltZXIuc2luZ2xlU2hvdCgxMjAwLCBfcGxheV9zdGFydHVwKQoKICAgIHN5cy5leGl0KGFwcC5l"
    "eGVjKCkpCgoKaWYgX19uYW1lX18gPT0gIl9fbWFpbl9fIjoKICAgIG1haW4oKQoKCiMg4pSA4pSA"
    "IFBBU1MgNiBDT01QTEVURSDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDi"
    "lIDilIDilIDilIDilIDilIDilIDilIDilIAKIyBGdWxsIGRlY2sgYXNzZW1ibGVkLiBBbGwgcGFz"
    "c2VzIGNvbXBsZXRlLgojIENvbWJpbmUgYWxsIHBhc3NlcyBpbnRvIG1vcmdhbm5hX2RlY2sucHkg"
    "aW4gb3JkZXI6CiMgICBQYXNzIDEg4oaSIFBhc3MgMiDihpIgUGFzcyAzIOKGkiBQYXNzIDQg4oaS"
    "IFBhc3MgNSDihpIgUGFzcyA2"
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
    ):
        super().__init__()
        self._deck_name        = deck_name
        self._persona          = persona
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loaded_persona: Optional[dict] = None
        self._loaded_name:    Optional[str]  = None
        self._radio_group = QButtonGroup(self)
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
        self._check_ready()

    def _on_persona_changed(self, name: str, persona: dict) -> None:
        self._current_persona_name = name
        self._current_persona      = persona
        # Let module list adjust defaults
        self._module_list.set_defaults_for_persona(name)
        # Auto-fill deck name if blank
        if not self._name_field.text().strip() and name not in ("Default", "Custom"):
            self._name_field.setText(name)

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
